#!/usr/bin/env python3
"""Disposable, socket-free M4 acceptance, retaining the exact M2 regressions."""
from __future__ import annotations

import ast
import hashlib
import copy
import contextlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from psycopg2 import connect
from v24.host.canonical import compact_json, pg_jsonb_text, descriptor_digest
from v24.host.deepseek import _canonical as provider_json, DeepSeekAdapter, AdapterFailure
from v24.host.registry import AdapterNotFound
from v24.host.journal import EVENT_TYPES, JournalCorrupt
from v24.host.worker import HostWorker, HostCrash
from v24.load import SQL_LOAD_ORDER, validate_manifest
from v24.host.descriptor import (TOOL_KEYS, ANNOTATION_KEYS, CONCURRENCY,
                                 REPLAY_CLASSES, LIMIT_RANGES, validate_descriptor)
from v24.host.tool_pages import validate_page
from v24.host.tool_schema import compile_schema
from v24.host.renderers import RENDERERS
from v24.host.tool_results import join_content
from v24.s1.setup_db import setup_db
from v24.ui import catalog
from v24.ui.control import AgentRuntime
from v24.ui.fake import ScriptedUiAdapter
from v24.ui.render import StepRecord, render_effect, render_generating, render_run_start, render_state
from v24.s11.plugin_fixtures import model_adapter, tool_reply, final_reply
import urllib.request
import v24.ui.env as env_module

PASS_LAST = "[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2"
SECRET_STRINGS = ("Authorization", "Bearer ", "postgres://")
HISTORICAL_COMMIT = "243dd9d33cc54725955709f10e162f153757141d"
HISTORICAL_KEYS = frozenset({"read", "file_search"})
READ_KEYS = frozenset({"read", "grep", "find", "ls", "read_file", "file_search", "get_file_tree"})
WRITE_KEYS = READ_KEYS | {"write", "edit", "apply_edits"}
EXEC_KEYS = WRITE_KEYS | {"bash"}
BUILD_MEASUREMENTS = []
# Stable owner handoff measured with wc -l -c on 2026-11-03; ceil(actual*1.20).
# Pi 1160 lines/52732 B; RP 1121 lines/52222 B. Hard caps still apply.
ARTIFACT_MEASURED_LIMITS = {'pi_tools.py': (1392, 63279), 'rp_tools.py': (1346, 62667)}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _good_value(key):
    value = {"text": "ok", "truncated": False, "spill_path": ""}
    if key == "bash": value["exit_code"] = 0
    if key == "apply_edits": value["status"] = "success"
    return value


def _descriptor_contract(spec, item):
    read_only = spec.key in READ_KEYS
    timeout = 20000 if spec.key == "bash" else 15000 if spec.key in {"grep", "find", "file_search"} else 5000
    args_bytes = 65536 if not read_only else 16384 if spec.key in {"grep", "file_search"} else 8192
    check(item["limits"] == dict(timeout_ms=timeout, max_args_bytes=args_bytes,
        max_value_bytes=40960, max_content_bytes=41984, max_meta_bytes=4096), (spec.key, "limits"))
    check(item["concurrency"] == ("parallel" if read_only else "exclusive"), spec.key)
    check(item["replay_class"] == ("read_only" if read_only else "external" if spec.key == "bash" else "mutating"), spec.key)
    check(item["annotations"] == dict(read_only=read_only, destructive=not read_only,
        idempotent=read_only, open_world=spec.key == "bash"), spec.key)
    check(item["parameters"]["additionalProperties"] is False, spec.key)
    if spec.key == "apply_edits": check(item["parameters"]["required"] == [], "apply required")


@contextlib.contextmanager
def _historical_catalog(directory):
    """Execute the complete committed artifacts, never pin-derived declarations."""
    production = catalog.families
    artifacts = []
    for name in ("pi_tools.py", "rp_tools.py"):
        relative = "v24/ui/plugins/" + name
        data = subprocess.run(["git", "show", f"{HISTORICAL_COMMIT}:{relative}"],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        path = directory / name
        path.write_bytes(data)
        artifacts.append((path, catalog._artifact_specs(path)))
        print(f"[fixture] historical {name} commit={HISTORICAL_COMMIT} bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}", flush=True)
    def families(realm, toolset):
        if not realm.startswith("historical-"):
            return production(realm, toolset)
        return tuple(catalog.FamilySpec(identity, version, path, realm,
            tuple(tool for tool in declared if tool.key in catalog._TOOLSETS[toolset]))
            for path, (identity, version, declared) in artifacts)
    with patch.object(catalog, "families", side_effect=families):
        check({tool.key for family in families("historical-fixture", "exec") for tool in family.tools} == HISTORICAL_KEYS, "historical declarations changed")
        yield


def _measure(prepared, pins, scenario, ordinal):
    admission = dict(prepared.body)
    admission.pop("max_tokens")
    raw = provider_json(admission).encode("utf-8")
    keys = sorted(pin["key"] for pin in pins)
    row = dict(scenario=scenario, ordinal=ordinal, pins=keys, body_bytes=len(raw),
        estimate=prepared.estimate, reserve=prepared.reserve_tokens, max_tokens=prepared.max_tokens,
        admission_body_sha256=hashlib.sha256(raw).hexdigest(),
        body_sha256=hashlib.sha256(provider_json(prepared.body).encode("utf-8")).hexdigest())
    check(prepared.estimate == len(raw) + 256 and 0 < prepared.max_tokens <= min(512, prepared.reserve_tokens), row)
    BUILD_MEASUREMENTS.append(row)
    print("[measurement] " + json.dumps(row, sort_keys=True), flush=True)
    return row


def _app_prompt(history=""):
    # Compile the actual pure helper only: gate has no Chainlit dependency.
    tree = ast.parse((ROOT / "v24/ui/app.py").read_bytes())
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_system_prompt"]
    check(len(helpers) == 1, "actual app prompt helper missing")
    namespace = {}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), "actual-app-prompt", "exec"), namespace)
    prompt = namespace["build_system_prompt"](catalog.available_skills(), history)
    check(prompt.endswith("\n" + history), 'actual app history-last ordering')
    for fact in ("stream:false", "complete answer", "Reply in the user's language", "read_file", "start_line", "grep", "file_search", "edit", "apply_edits", "512", "reasoning", 'finish_reason="length"', 'finish_length', 'read its location in full'):
        check(fact in prompt, ("app prompt fact", fact))
    check(prompt.count(catalog.available_skills()) == 1 and catalog.MAX_SAFE_ARGS_BYTES is None, "skills/safe args prompt")
    return prompt


def _artifact_structure(paths):
    expected = ({"read", "write", "edit", "bash", "grep", "find", "ls"},
                {"read_file", "file_search", "get_file_tree", "apply_edits"})
    forbidden = {"socket", "ssl", "http", "urllib", "requests", "psycopg2", "pgembed", "v24"}
    for path, keys in zip(paths, expected):
        data = path.read_bytes()
        lines, size = data.count(b"\n"), len(data)
        check(lines <= 3000 and size <= 160 * 1024, (path.name, lines, size))
        if ARTIFACT_MEASURED_LIMITS:
            line_cap, byte_cap = ARTIFACT_MEASURED_LIMITS[path.name]
            check(lines <= line_cap <= 3000 and size <= byte_cap <= 160 * 1024, "measured artifact cap")
        imports = set()
        for node in ast.walk(ast.parse(data)):
            if isinstance(node, ast.Import): imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                check(node.level == 0, "relative artifact import")
                imports.add((node.module or "").split(".")[0])
        check(imports <= sys.stdlib_module_names and not imports & forbidden, (path.name, imports))
        identity, version, tools = catalog._artifact_specs(path)
        check(version == "1" and {tool.key for tool in tools} == keys, (identity, keys))
        print(f"[artifact] {path.name} lines={lines} bytes={size} sha256={hashlib.sha256(data).hexdigest()}", flush=True)


def _only_shared(path):
    text = path.read_bytes()
    begin = b"# ==== BEGIN SHARED CORE (v24-ui-family-v1) ====\n"
    end = b"# ==== END SHARED CORE ====\n"
    check(text.count(begin) == text.count(end) == 1, f"shared markers {path}")
    return text[text.index(begin):text.index(end) + len(end)]


def _assert_shared_core(pi, rp):
    check(_only_shared(pi) == _only_shared(rp), "shared core differs")
    import importlib.util
    spec = importlib.util.spec_from_file_location("rp_tools_gate", rp)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    constants = {'MAX_FILE_BYTES': 1024 * 1024, 'MAX_TEXT_LINES': 2000, 'MAX_TEXT_BYTES': 32768,
                 'MAX_VALUE_BYTES': 40960, 'MAX_CONTENT_BYTES': 41984, 'MAX_META_BYTES': 4096,
                 'MAX_SPILL_BYTES': 8 * 1024 * 1024, 'SPILL_RESERVE': 128}
    check(all(getattr(module, key) == value for key, value in constants.items()), 'artifact budget constants')
    from v24.host.canonical import compact_json as host_json
    values = [None, True, False, 0, -17, "", "é/😀", "\b\t\n\f\r\"\\", {"é": 1, "z": [True, None]},
              {"x": "q" * 4096}, ["", 1, {"a": "b"}], {"a": 1, "é": 2}]
    check(len(values) == 12, 'canonical parity requires twelve fixtures')
    for value in values:
        check(module.canonical_json(value).encode() == (host_json(value) if isinstance(host_json(value), bytes) else host_json(value).encode()), "canonical JSON mismatch")
    for value in (float('nan'), float('inf'), '\ud800', 2 ** 53):
        for encoder in (module.canonical_json, host_json):
            try: encoder(value)
            except (ValueError, TypeError, UnicodeError): pass
            else: raise AssertionError('canonical accepted invalid domain')
    return module


def _temp_env(db, work):
    root = work.resolve()
    for name in ("workspace", "spawn", "spill", "skills"):
        (root / name).mkdir(exist_ok=True)
    # S1 setup provides an isolated disposable DB and roles; its fixture-only
    # journal schema is removed so the UI gate proves the closed ten-table set.
    conn = connect(db.admin_dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS v24_fake CASCADE")
    finally:
        conn.close()
    return type("UiTestEnv", (), {
        "repo_root": ROOT, "data_dir": root, "db_name": db.name,
        "socket_dir": Path("/tmp"), "port": 0,
        "maintenance_dsn": db.maintenance_dsn,
        "admin_dsn": db.role_dsn("admin"), "service_dsn": db.role_dsn("service"),
        "journal_path": root / "journal.jsonl", "spawn_dir": root / "spawn",
        "workspace_root": root / "workspace", "spill_root": root / "spill",
        "skills_root": root / "skills",
    })()


def _assert_closed_schema(db):
    with connect(db.admin_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='v24' ORDER BY tablename")
            tables = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT count(*) FROM pg_class WHERE relnamespace='v24'::regnamespace AND relkind IN ('v','m')")
            views = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pg_extension WHERE extnamespace='v24'::regnamespace")
            extensions = cur.fetchone()[0]
    check(len(tables) == 10 and views == 0 and extensions == 0, (tables, views, extensions))


def _run_artifact(plugin, *, tool, args, work_env, extra_env=None):
    source = dict(os.environ)
    if extra_env:
        source.update(extra_env)
    environment = plugin.environment(source)
    request = {"v": 2, "operation": "invoke", "reservation": "v24:tool_call:00000000-0000-0000-0000-000000000001", "tool": tool, "args": args}
    result = subprocess.run(plugin.argv, cwd=plugin.cwd, env=environment, input=compact_json(request) + b"\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    check(result.stdout.endswith(b"\n") and result.stdout.count(b"\n") == 1, "artifact frame shape")
    return result, json.loads(result.stdout)


def _schema_and_page_checks():
    families = catalog.families("ui-test", "exec")
    check({tool.key for family in families for tool in family.tools} == EXEC_KEYS and [len(family.tools) for family in families] == [7, 4], 'catalog != Pi7/RP4')
    check({family.identity for family in families} == {"v24.ui.pi_tools", "v24.ui.rp_tools"}, families)
    for family in families:
        manifest = catalog.manifest(family)
        for spec in family.tools:
            descriptor = manifest["provides"]
            item = next(row for row in descriptor if row["key"] == spec.key)["descriptor"]["tool"]
            check(set(item) == TOOL_KEYS == {"key", "description", "parameters", "output_schema", "render", "limits", "concurrency", "replay_class", "annotations"}, spec.key)
            check(set(item["annotations"]) == ANNOTATION_KEYS == {"read_only", "destructive", "idempotent", "open_world"}, spec.key)
            check(CONCURRENCY == {"parallel", "exclusive"} and REPLAY_CLASSES == {"read_only", "idempotent", "mutating", "external"}, spec.key)
            check(item["concurrency"] in {"parallel", "exclusive"} and item["replay_class"] in {"read_only", "idempotent", "mutating", "external"}, spec.key)
            ranges = {"timeout_ms": (1, 25000), "max_args_bytes": (1, 65536), "max_value_bytes": (1, 49152), "max_content_bytes": (1, 65536), "max_meta_bytes": (2, 16384)}
            check(LIMIT_RANGES == ranges and set(item["limits"]) == set(ranges), spec.key)
            check(all(type(item["limits"][name]) is int and low <= item["limits"][name] <= high for name, (low, high) in ranges.items()), spec.key)
            annotations = item["annotations"]
            check(all(type(value) is bool for value in annotations.values()), spec.key)
            if item["replay_class"] == "read_only":
                check(annotations["read_only"] and not annotations["destructive"] and annotations["idempotent"], spec.key)
            if annotations["read_only"]:
                check(not annotations["destructive"], spec.key)
            if item["concurrency"] == "parallel":
                check(annotations["read_only"], spec.key)
            check(item["render"]["id"] == "v24.text.plain" and item["render"]["digest"] == RENDERERS.by_id("v24.text.plain", 1).ref.digest, spec.key)
            validate_descriptor(next(row for row in descriptor if row["key"] == spec.key)["descriptor"], provide_key=spec.key)
            schema = item["output_schema"]
            validate = compile_schema(schema, kind="output_schema")
            good = _good_value(spec.key)
            expected = {"text", "truncated", "spill_path"} | ({"exit_code"} if spec.key == "bash" else {"status"} if spec.key == "apply_edits" else set())
            check(set(schema["properties"]) == set(schema["required"]) == expected and schema["additionalProperties"] is False, spec.key)
            validate(good)
            _descriptor_contract(spec, item)
            try:
                validate({**good, "unexpected": True})
            except Exception:
                pass
            else:
                raise AssertionError("schema accepted unknown key")
            ref = RENDERERS.by_id("v24.text.plain", 1).ref
            try:
                validate_page(ref, {}, {**good, "spill_path": "x"})
            except Exception as exc:
                check(getattr(exc, "reason", "invalid_tool_output") == "invalid_tool_output", repr(exc))
            else:
                raise AssertionError("page accepted invalid truncated/spill relation")
            RENDERERS.render(ref, {}, good)
            validate_page(ref, {}, good)
    return True


def _effect_map(records):
    return {str(row["effect_id"]): (row.get("status"), render_effect(row)) for row in records}


def _secret_check(records):
    text = "\n".join(step.output for step in records)
    for secret in SECRET_STRINGS:
        check(secret not in text, f"secret leaked: {secret}")


def _v2_script_names(transport):
    # The S11 helper emits v1 hashed names. v2 legal provider names are the
    # descriptor key itself; adapt only the scripted provider response fixture.
    from v24.host.deepseek import provider_tool_name
    names = {provider_tool_name(key): key for key in EXEC_KEYS}
    for reply in transport.script:
        for call in reply.get("raw", {}).get("choices", [{}])[0].get("message", {}).get("tool_calls", []):
            function = call["function"]
            function["name"] = names[function["name"]]


def _main_run(rt, scope, owner, workspace, *, expected_keys=HISTORICAL_KEYS, ceiling=None):
    (workspace / "README.md").write_text("# v24 M2 acceptance\n", encoding="utf-8")
    adapter, transport = model_adapter([
        tool_reply("call_1", "read", {"path": "README.md", "limit": 5}),
        tool_reply("call_2", "file_search", {"pattern": "v24", "mode": "content", "max_results": 3}),
        final_reply("done"),
    ])
    _v2_script_names(transport)
    adapter.body_byte_ceiling = ceiling
    rt.adapter = adapter; rt.worker.adapter = adapter
    families = rt._families(scope, "read")
    installs = rt.install_tools(scope, families)
    check(len(installs) == 2 and {Path(f.artifact).stem for f in families} == {"pi_tools", "rp_tools"}, installs)
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "read and search"}], toolset="read", key=f"m2-main-{uuid.uuid4().hex}")
    pins = rt.db.host_run_pins(run, None, 64).get("items", [])
    pin_keys = {item["key"] for item in pins}
    check(pin_keys == expected_keys and not rt.db.host_run_pins(run, None, 64)["has_more"], f"owner fiber pin set mismatch: {pin_keys}")
    initial_state = rt.run_state(run, 0).get("run") or {}
    rt._active_run = run
    timeline = []
    report = rt.drive(scope, on_effect=lambda effect: timeline.append(effect))
    check(report.status == "completed" and report.final_text == "done" and report.rounds <= 64, {"report": report, "state": rt.run_state(run, 0), "effects": timeline})
    check(transport.script == [] and len(transport.calls) == 3, "script not exhausted exactly")
    bodies = [json.loads(item["body"]) for item in transport.calls]
    for body in bodies:
        check(body.get("model") == "deepseek-flash" and body.get("stream") is False and "tool_choice" not in body, "provider contract")
        check(b"OPENAI_API_URI" not in compact_json(body), "provider URI leaked")
    check({tool["function"]["name"] for tool in bodies[0]["tools"]} == pin_keys, "body.tools != pins")
    check(all(set(tool["function"]["name"] for tool in body["tools"]) == pin_keys for body in bodies), "tools drift")
    d = rt.discovery(run)
    incremental = _effect_map(d.records)
    replay = _effect_map(rt.replay(run))
    check(incremental == replay, "incremental timeline differs from full replay")
    check(len(d.finalized) == len(d.records) and len(d.finalized) == len(set(d.finalized)), "effect finalized more than once")
    check(len(timeline) == 5, f"expected five durable effects, saw {len(timeline)}")
    records = [StepRecord(f"install · {Path(f.artifact).stem}", "run", "installed") for f in families]
    records.extend([render_run_start(scope=scope, run_id=run, budget={"tokens": rt.run_state(run, 0).get("run", {}).get("remaining_tokens", 0)}, requires=sorted(pin_keys)), render_generating()])
    records.extend(record for effect in timeline if (record := render_effect(effect)) is not None)
    final_state = rt.run_state(run, 0)
    check(final_state["run"]["status"] == "completed" and final_state["run"]["result"]["final_text"] == "done" and final_state["run"]["turn_no"] >= 3, final_state)
    records.extend(render_state(final_state, seen=frozenset()))
    expected = [("install · pi_tools", "run"), ("install · rp_tools", "run"), ("run · started", "run"), ("generating", "llm"), ("model · tools (1)", "llm"), ("tool · read", "tool"), ("model · tools (1)", "llm"), ("tool · file_search", "tool"), ("model · final", "llm"), ("run · completed", "run")]
    actual = [(record.name, record.type) for record in records]
    check(actual == expected, f"step sequence mismatch: {actual}")
    _secret_check(records)
    tool_records = [record for record in records if record.type == "tool"]
    durable_tools = [effect for effect in timeline if effect.get("kind") == "tool_call"]
    check(len(tool_records) == len(durable_tools) == 2, "tool step/effect count")
    for record, effect in zip(tool_records, durable_tools):
        content = effect["outcome"]["body"]["result"]["output"]["content"]
        check(record.output.encode() == join_content(content).encode(), "rendered tool bytes differ from model text")
    search_record = next(record for record in tool_records if record.name == "tool · file_search")
    check("README.md" in search_record.output and "1: # v24 M2 acceptance" in search_record.output, search_record)
    check(initial_state.get("status") == "running", "initial run state")
    return run, timeline, records, adapter, families


def _big_text_run(rt, scope, owner, workspace, *, expected_keys=HISTORICAL_KEYS, ceiling=None):
    target = workspace / "long.txt"
    target.write_text("A" * 2001, encoding="ascii")
    adapter, transport = model_adapter([
        tool_reply("call_big", "read", {"path": "long.txt"}),
        final_reply("large complete"),
    ])
    _v2_script_names(transport)
    adapter.body_byte_ceiling = ceiling
    rt.adapter = adapter; rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "read long"}], toolset="read", key=f"m2-big-{uuid.uuid4().hex}")
    check({item['key'] for item in rt.db.host_run_pins(run, None, 64)['items']} == expected_keys, 'large run pins')
    rt._active_run = run
    note = render_run_start(scope=scope, run_id=run, budget={}, requires=["read", "file_search"])
    check(len(note.output) <= 2000, "run note presentation cap")
    args_note = render_effect({"kind":"model_call", "status":"succeeded", "effect_id":"e", "outcome":{"body":{"result":{"result":{"tool_calls":[{"key":"read","args":{"x":"x"*1000}}]}}}}})
    check(len(args_note.output) <= 2000 and len(args_note.output.split(" ",1)[1]) <= 600, "tool args presentation cap")
    print("[case] explanation caps: run note <=2000 chars; tool args <=500 chars, model tools step <=2000 chars", flush=True)
    timeline = []
    observations = []
    original_build = adapter.build
    def observe_build(effect, history, pins):
        prepared = original_build(effect, history, pins)
        observations.append({**_measure(prepared, pins, 'historical-2001' if ceiling is None else 'read7-2001', len(observations) + 1),
                             "body": copy.deepcopy(prepared.body)})
        return prepared
    with patch.object(adapter, "build", side_effect=observe_build):
        report = rt.drive(scope, on_effect=lambda effect: timeline.append(effect))
    effect = next(item for item in timeline if item.get("kind") == "tool_call")
    check(effect["status"] == "succeeded", effect["status"])
    step = render_effect(effect)
    model_text = join_content(effect["outcome"]["body"]["result"]["output"]["content"])
    history_text = next(message["content"] for message in rt.worker._history(run) if message.get("role") == "tool")
    expected_bytes = target.read_bytes()
    check(all(text.encode() == expected_bytes for text in (step.output, model_text, history_text)), "durable/UI/history bytes differ")
    check(report.status == "completed" and report.final_text == "large complete", report)
    check(len(expected_bytes) == 2001 and len(observations) == 2, "expected two real builds")
    continuation = observations[-1]
    check(continuation["reserve"] == 4096 and continuation["max_tokens"] >= 5, continuation)
    if ceiling is None:
        check((continuation['body_bytes'], continuation['estimate'], continuation['max_tokens']) == (3655, 3911, 185), continuation)
    else:
        check(continuation['body_bytes'] <= 8000, continuation)
    check(all({tool['function']['name'] for tool in row['body']['tools']} == expected_keys for row in observations), 'large body tools != pins')
    built_tool_messages = [message for message in continuation["body"]["messages"] if message.get("role") == "tool"]
    check(built_tool_messages and built_tool_messages[-1]["content"].encode() == expected_bytes, "second build lacks 2001-byte tool message")
    check(len(transport.calls) == 2 and transport.script == [], "2001-byte script not exhausted")
    next_body = json.loads(transport.calls[-1]["body"])
    check(next_body == continuation["body"], "second built body differs from sent body")
    tool_messages = [message for message in next_body["messages"] if message.get("role") == "tool"]
    check(step.output.encode() == target.read_bytes() and model_text.encode() == target.read_bytes(), "large text was altered")
    check(tool_messages and tool_messages[-1]["content"].encode() == target.read_bytes(), "model context differs from UI bytes")
    check(len(step.output) > 2000 and "[truncated" not in step.output, "tool output hit presentation cap")
    print(f"[case] 2001-byte continuation: bytes=2001 sha256={hashlib.sha256(expected_bytes).hexdigest()} estimate={continuation['estimate']} reserve={continuation['reserve']} max_tokens={continuation['max_tokens']} body_sha256={continuation['body_sha256']} calls=2 consumed=2", flush=True)
    return effect


def _interaction_runs(rt, scope, owner):
    adapter = ScriptedUiAdapter([{"kind": "interaction", "payload": {"prompt": "continue?"}}, {"kind": "final", "text": "answered"}])
    rt.adapter = adapter; rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "ask"}], toolset="read", key=f"m2-interaction-{uuid.uuid4().hex}")
    rt._active_run = run
    waiting = rt.drive(scope)
    state = rt.run_state(run, 0).get("run") or {}
    effects = rt.db.host_run_effects(run, None, None, 64).get("items", [])
    origin = next(effect for effect in effects if str(effect.get("effect_id")) == str(state.get("interaction", {}).get("interaction_id")))
    model_result = origin["outcome"]["body"]["result"]
    payload = model_result["interaction"]["payload"]
    check(waiting.waiting_interaction and state.get("status") == "waiting" and payload.get("prompt") == "continue?", {"state":state,"payload":payload})
    waiting_records = render_state({"run": state}, seen=frozenset(), interaction_payload=payload)
    check("continue?" in waiting_records[0].output, "waiting prompt missing from actual render")
    check(len(waiting_records) == 1 and waiting_records[0].name == "run · waiting" and waiting_records[0].type == "run" and waiting_records[0].effect_id == str(state["interaction"]["interaction_id"]), waiting_records)
    check(render_state({"run": state}, seen=frozenset({str(state["interaction"]["interaction_id"])})) == [], "waiting emitted twice")
    before = len(adapter.calls)
    # Empty UI answers must never call the runtime verb. SQL's nonempty-object
    # contract alone does not reject {"text": ""}.
    with patch.object(rt, "respond", wraps=rt.respond) as respond:
        answer_text = ""
        if answer_text:
            respond(run, state["interaction"]["interaction_id"], {"text":answer_text}, f"m2-empty-{uuid.uuid4().hex}")
        respond.assert_not_called()
    check(len(adapter.calls) == before and (rt.run_state(run,0).get("run") or {}).get("status") == "waiting", "empty response changed waiting run")
    response = rt.respond(run, state["interaction"]["interaction_id"], {"text":"ok"}, f"m2-respond-{uuid.uuid4().hex}")
    check(response.get("disposition") == "committed", response)
    rt._active_run = run
    completed = rt.drive(scope)
    check(completed.status == "completed" and completed.final_text == "answered", completed)
    check(adapter.outcomes == [] and len(adapter.calls) == 2, "interaction script not exhausted")
    print("[case] interaction/respond: waiting payload readable; empty UI answer makes zero respond calls; nonempty answer -> answered", flush=True)
    # The first real build needs a positive reserve. Its interaction outcome
    # spends the admitted 4096 tokens, leaving waiting with exactly zero.
    zero_adapter = ScriptedUiAdapter([{"kind":"interaction", "payload":{"prompt":"zero?"}, "usage":{"tokens":4096,"wall_ms":1}}])
    rt.adapter = zero_adapter; rt.worker.adapter = zero_adapter
    zero, _ = rt.start_run(scope, owner, [{"role":"user", "content":"zero"}], toolset="read", budget={"steps":8,"tool_calls":2,"tokens":4096,"wall_ms":600000}, key=f"m2-token0-{uuid.uuid4().hex}")
    rt._active_run = zero
    wait_zero = rt.drive(scope)
    zero_state = rt.run_state(zero, 0).get("run") or {}
    check(wait_zero.waiting_interaction and zero_state.get("status") == "waiting" and zero_state.get("remaining_tokens") == 0, zero_state)
    check(len(zero_adapter.calls) == 1 and zero_adapter.outcomes == [], "interaction must consume the only scripted response")
    check(zero_adapter.calls[0]["max_tokens"] > 0, "initial positive reserve did not build")
    answer = rt.respond(zero, zero_state["interaction"]["interaction_id"], {"text":"ok"}, f"m2-token0-respond-{uuid.uuid4().hex}")
    check(answer.get("disposition") == "committed", answer)
    rt._active_run = zero
    result = rt.drive(scope)
    final_state = rt.run_state(zero, 0).get("run") or {}
    check(result.status == final_state.get("status") == "completed", final_state)
    check((final_state.get("result") or {}).get("close_reason") == "budget_exhausted", final_state)
    check(final_state.get("interaction") is None and result.final_text is None, final_state)
    effects = rt.db.host_run_effects(zero, None, None, 64)
    check(not effects.get("has_more") and len(effects["items"]) == 1, "budget seal created a model successor")
    check(all(effect["status"] not in ("ready", "claimed") for effect in effects["items"]), effects)
    check(len(zero_adapter.calls) == 1, "budget seal sent another provider request")
    rendered = render_state({"run":final_state}, seen=frozenset())
    check(len(rendered) == 1 and rendered[0].name == "run · budget exhausted" and rendered[0].type == "error", rendered)
    check("reason=budget_exhausted" in rendered[0].output and "run · completed" not in rendered[0].name, rendered)
    print("[case] interaction/token-0: start=4096 usage=4096 -> waiting/tokens=0 -> respond committed -> completed/budget_exhausted; UI=run · budget exhausted (error); transport=1; successors=0", flush=True)
    return {"kernel_status":final_state["status"], "close_reason":final_state["result"]["close_reason"], "ui":rendered[0].__dict__, "transport_calls":len(zero_adapter.calls)}


def _spill_and_sensitive(rt, scope, owner, workspace):
    target = workspace / "long-lines.txt"
    content = "".join(f"line-{i:04d}\n" for i in range(2505))
    target.write_text(content, encoding="utf-8")
    # Call the real artifact in its approved environment to verify the virtual mount.
    family = next(f for f in rt._families(scope, "read") if f.identity == "v24.ui.pi_tools")
    plugin = catalog.build_plugin(family, rt.env)
    env = {"V24_WORKSPACE_ROOT": str(workspace.resolve()), "V24_SPILL_ROOT": str(rt.env.spill_root.resolve())}
    first, frame = _run_artifact(plugin, tool="read", args={"path":"long-lines.txt"}, work_env=rt.env, extra_env=env)
    check(first.returncode == 0 and frame["ok"], frame)
    value = frame["result"]["value"]
    check(value["truncated"] is True and re.fullmatch(r"\.v24/spill/[0-9a-f]{32}\.txt", value["spill_path"]), value)
    spill = rt.env.spill_root / (value["spill_path"].split("/")[-1])
    reconstructed = []
    for offset in (1, 1001, 2001):
        page, page_frame = _run_artifact(plugin, tool="read", args={"path":value["spill_path"], "offset":offset, "limit":1000}, work_env=rt.env, extra_env=env)
        check(page.returncode == 0 and page_frame["ok"], page_frame)
        page_value = page_frame["result"]["value"]
        shown = page_value["text"]
        if page_value["truncated"]:
            shown, notice = shown.rsplit("[Showing lines ", 1)
            check(notice.startswith(f"{offset}-{offset + 999} of 2505. Use offset={offset + 1000} to continue."), notice)
        reconstructed.append(shown)
    check("".join(reconstructed).encode() == spill.read_bytes(), "spill page reconstruction differs")
    for secret_path in (".env", "a.pem", "id_rsa", ".git/config", ".uidata/x", "missing/.env"):
        result, rejected = _run_artifact(plugin, tool="read", args={"path":secret_path}, work_env=rt.env, extra_env=env)
        check(result.returncode == 3 and rejected.get("error",{}).get("code") == "path_excluded", (secret_path, rejected))
    rp_family = next(f for f in rt._families(scope, "read") if f.identity == "v24.ui.rp_tools")
    rp_plugin = catalog.build_plugin(rp_family, rt.env)
    for secret_path in (".env", "a.pem", "id_rsa", ".git/config", ".uidata/x", "missing/.env"):
        result, rejected = _run_artifact(rp_plugin, tool="file_search", args={"pattern":"v24", "mode":"content", "filter":{"paths":[secret_path]}}, work_env=rt.env, extra_env=env)
        check(result.returncode == 3 and rejected.get("error",{}).get("code") == "path_excluded", (secret_path, rejected))
    result, rejected = _run_artifact(plugin, tool="read", args={"path":".uidata/spill/secret.txt"}, work_env=rt.env, extra_env=env)
    check(result.returncode == 3 and rejected["error"]["code"] == "path_excluded", rejected)
    return value


def _database_digest_assertions(rt, scope, families):
    rows = rt.db.host_scope_installs(scope, None, 64).get("items", [])
    check(len(rows) == 2, rows)
    for row in rows:
        family = next(item for item in families if item.identity == row["identity"])
        plugin = catalog.build_plugin(family, rt.env)
        check(plugin.timeout_ms == 5000 and plugin.timeout_cap_ms == 25000 and max(tool.timeout_ms for tool in plugin.tools) + 5000 <= rt.worker.default_lease_ms == 30000, 'plugin lifecycle/tool/worker timeout contract')
        manifest = catalog.manifest(family)
        check(rt.dispatcher.registry.lookup_install(row) == plugin, row["identity"])
        for field in ("manifest_digest", "artifact_digest", "adapter_digest"):
            check(row[field] == getattr(plugin, field), (field, row[field]))
        check(row["manifest"] == manifest, row["identity"])
        for provided in row["provides"]:
            expected = next(item for item in manifest["provides"] if item["key"] == provided["key"])
            check(pg_jsonb_text(provided["descriptor"]) == pg_jsonb_text(expected["descriptor"]), provided["key"])
            check(descriptor_digest(provided["descriptor"]) == plugin.tool_for(provided["key"]).descriptor_digest, provided["key"])
        fibers = rt.db.host_install_fibers(row["install_id"], None, 64).get("items", [])
        check(len(fibers) == 1 and fibers[0]["install_id"] == row["install_id"], fibers)
        def rejected(changed):
            try:
                catalog.build_registry((changed,)).lookup_install(row)
            except AdapterNotFound as exc:
                check(exc.reason == "adapter_not_approved", exc.reason)
            else:
                raise AssertionError("digest negative control accepted")
        with tempfile.TemporaryDirectory(prefix="m2-digest-") as temp:
            artifact = Path(temp) / family.artifact.name
            artifact.write_bytes(family.artifact.read_bytes() + b"\n")
            rejected(catalog.build_plugin(replace(family, artifact=artifact), rt.env))
        rejected(catalog.build_plugin(replace(family, realm=family.realm + "x"), rt.env))


def _search_semantics(rt, scope, workspace):
    """Exercise advertised search modes and retrieve a multi-file RP spill."""
    families = rt._families(scope, "read")
    rp = catalog.build_plugin(next(f for f in families if f.identity.endswith("rp_tools")), rt.env)
    pi = catalog.build_plugin(next(f for f in families if f.identity.endswith("pi_tools")), rt.env)
    with tempfile.TemporaryDirectory(prefix="m2-search-") as temp:
        root = Path(temp).resolve()
        rp = replace(rp, workspace_root=str(root))
        pi = replace(pi, workspace_root=str(root))
        (root / "src").mkdir()
        (root / "src" / "alpha.py").write_text("before\nneedle value\nafter\nneedles\n")
        (root / "beta.txt").write_text("needle other\n")
        (root / "binary-a").write_bytes(b"needle\x00")
        (root / "binary-b").write_bytes(b"needle\x00")
        def invoke(plugin, key, args):
            result, frame = _run_artifact(plugin, tool=key, args=args, work_env=rt.env)
            check(result.returncode == 0 and frame["ok"], frame)
            return frame["result"]["value"]
        cases = [
            ({"pattern": "*.py"}, ("matches=1; files=1", "src/alpha.py"), ("beta.txt",)),
            ({"pattern": r"^src/.*\.py$", "mode": "path", "regex": True}, ("matches=1; files=1", "src/alpha.py"), ("beta.txt",)),
            ({"pattern": "needle", "mode": "content", "regex": False, "whole_word": True, "context_lines": 1, "filter": {"extensions": [".py"]}}, ("matches=1; files=1", "1: before", "2: needle value", "3: after"), ("4: needles",)),
            ({"pattern": "needle", "mode": "content", "filter": {"exclude": ["beta.txt"], "extensions": [".py"]}}, ("matches=2; files=1", "src/alpha.py"), ("beta.txt",)),
            ({"pattern": "needle", "mode": "content", "count_only": True, "whole_word": True, "max_results": 1}, ("matches=1; files=1", "limit_reached=true"), ("\n",)),
            ({"pattern": "needle", "mode": "content", "whole_word": True}, ("matches=2; files=2", "skipped_binary=2"), ("binary-a\n",)),
            ({"pattern": "binary|alpha", "mode": "both", "max_results": 1}, ("matches=1; files=1", "skipped_binary=2", "src/alpha.py", "limit_reached=true"), ("binary-a\n",)),
            ({"pattern": "*.txt", "mode": "path", "regex": False}, ("matches=1; files=1", "beta.txt"), ("src/alpha.py",)),
        ]
        for args, required, excluded in cases:
            text = invoke(rp, "file_search", args)["text"]
            check(all(part in text for part in required) and all(part not in text for part in excluded), {"args": args, "text": text})
        # Two inputs aggregate beyond the Pi read 1-MiB spill limit: reject
        # before writing, rather than return an unreadable or pruned spill.
        for name in ("large-a.txt", "large-b.txt"):
            (root / name).write_text(("hit " + "x" * 1195 + "\n") * 600)
        before_spills = set(rt.env.spill_root.iterdir())
        result, frame = _run_artifact(rp, tool="file_search", args={"pattern": "hit", "mode": "content", "max_results": 1000, "filter": {"paths": ["large-a.txt", "large-b.txt"]}}, work_env=rt.env)
        check(result.returncode == 3 and frame["error"]["code"] == "output_too_large" and set(rt.env.spill_root.iterdir()) == before_spills, frame)
        for name in ("large-a.txt", "large-b.txt"):
            (root / name).write_text(("hit " + "x" * 995 + "\n") * 40)
        value = invoke(rp, "file_search", {"pattern": "hit", "mode": "content", "max_results": 1000, "filter": {"paths": ["large-a.txt", "large-b.txt"]}})
        check(value["truncated"] and value["spill_path"], value)
        spill_bytes = (rt.env.spill_root / Path(value["spill_path"]).name).read_bytes()
        check(len(spill_bytes) < 1024 * 1024 and b"large-a.txt" in spill_bytes and b"large-b.txt" in spill_bytes, "bad RP spill")
        reconstructed = []
        total_lines = len(spill_bytes.decode().splitlines(keepends=True))
        for offset in range(1, total_lines + 1, 20):
            page = invoke(pi, "read", {"path": value["spill_path"], "offset": offset, "limit": 20})
            text = page["text"]
            if page["truncated"]:
                text, _ = text.rsplit("[Showing lines ", 1)
            reconstructed.append(text)
        check("".join(reconstructed).encode() == spill_bytes, "RP spill cannot be reconstructed with Pi read")
    print("[case] file_search semantics: auto glob/regex path/both/literal/whole-word/context/filters/count/binary/cap; oversize fails before spill; multi-file spill read back", flush=True)


def _env_isolation(rt, scope):
    families = rt._families(scope, "read")
    for family in families:
        plugin = catalog.build_plugin(family, rt.env)
        fake_env = {"V24_WORKSPACE_ROOT":"/not-the-workspace", "DEEPSEEK_API_KEY":"dummy", "OPENAI_API_KEY":"dummy", "PGPASSWORD":"dummy", "PGHOST":"dummy", "PGSERVICE":"dummy", "PG_UNEXPECTED":"dummy"}
        actual = plugin.environment(fake_env)
        check(actual["V24_WORKSPACE_ROOT"] == str(rt.env.workspace_root.resolve()), actual)
        check(not ({"DEEPSEEK_API_KEY", "OPENAI_API_KEY"} & set(actual)) and not any(name.startswith("PG") for name in actual), actual.keys())
        real_run = subprocess.run
        executed_envs = []
        def capture_run(*args, **kwargs):
            executed_envs.append(dict(kwargs["env"]))
            return real_run(*args, **kwargs)
        with patch.object(subprocess, "run", side_effect=capture_run):
            result, frame = _run_artifact(plugin, tool="read" if family.identity.endswith("pi_tools") else "file_search",
                args={"path":"README.md"} if family.identity.endswith("pi_tools") else {"pattern":"v24", "mode":"content"},
                work_env=rt.env, extra_env=fake_env)
        check(result.returncode == 0 and frame["ok"] and len(executed_envs) == 1, frame)
        executed = executed_envs[0]
        check(executed["V24_WORKSPACE_ROOT"] == str(rt.env.workspace_root.resolve()), "executed workspace root mismatch")
        check(not ({"DEEPSEEK_API_KEY", "OPENAI_API_KEY"} & set(executed)) and not any(name.startswith("PG") for name in executed), executed.keys())


def _dispatcher_checks(rt, workspace):
    """Real approved subprocess -> line decoder -> dispatcher -> durable receipt."""
    from v24.host import plugins as host_plugins
    cases = {
        "schema": ({"ok": True, "v": 2, "result": {"value": {"text": "ok", "truncated": False, "spill_path": "", "unexpected": True}, "meta": {}}}, 0, "failure", "invalid_tool_output"),
        "page": ({"ok": True, "v": 2, "result": {"value": {"text": "ok", "truncated": False, "spill_path": "x"}, "meta": {}}}, 0, "failure", "invalid_tool_output"),
        "frame": ({"ok": False, "v": 2, "error": {"code": "io_error", "message": "/absolute/path"}}, 3, "unknown", "bad_frame"),
    }
    for key in sorted(EXEC_KEYS):
        identity = "v24.ui.pi_tools" if key in {"read", "write", "edit", "bash", "grep", "find", "ls"} else "v24.ui.rp_tools"
        for label, (template, exit_code, expected_class, expected_code) in cases.items():
            frame = copy.deepcopy(template)
            if label != "frame":
                frame['result']['value'].update({k: v for k, v in _good_value(key).items() if k not in {'text', 'truncated', 'spill_path'}})
            realm = "probe-" + uuid.uuid4().hex[:8]
            scope = rt.create_scope(realm)
            family = next(f for f in rt._families(scope, "exec") if f.identity == identity)
            with tempfile.TemporaryDirectory(prefix="m2-dispatch-") as temp:
                artifact = Path(temp) / family.artifact.name
                source = family.artifact.read_text()
                source = source[:source.index("def main():")] + '''def main():
    request = json.loads(sys.stdin.buffer.readline())
    if request["operation"] == "invoke":
        sys.stdout.buffer.write(PROBE_FRAME)
        raise SystemExit(PROBE_EXIT)
    result = {"prepare": {"prepared": True}, "release": {"released": True}, "inspect": {"observed": "known"}}[request["operation"]]
    print(frame({"ok": True, "v": 2, "result": result}))
if __name__ == "__main__":
    main()
'''
                source = source.replace("def main():", f"PROBE_FRAME = {compact_json(frame) + bytes([10])!r}\nPROBE_EXIT = {exit_code}\ndef main():", 1)
                artifact.write_text(source)
                probe_families = tuple(replace(item, artifact=artifact) if item.identity == identity else item for item in rt._families(scope, "exec"))
                rt.install_tools(scope, probe_families)
                _database_digest_assertions(rt, scope, probe_families)
                owner = rt.fiber_for(scope, identity)
                args = _valid_args(key)
                adapter = ScriptedUiAdapter([{"kind": "tool", "key": key, "args": args}, {"kind": "final", "text": "probe done"}])
                adapter.body_byte_ceiling = 8000
                rt.adapter = rt.worker.adapter = adapter
                run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "probe"}], toolset="exec", key="probe-" + uuid.uuid4().hex)
                with patch.object(host_plugins, "validate_page", wraps=host_plugins.validate_page) as page_check:
                    report = rt.drive(scope)
                effects = rt.replay(run)
                tool = next(effect for effect in effects if effect["kind"] == "tool_call")
                finish = rt.journal.last("dispatch_finished", str(tool["effect_id"]))
                check(finish["payload"]["outcome"]["class"] == expected_class, finish)
                check(tool["outcome"]["body"]["result"]["output"]["error"]["code"] == expected_code, tool)
                if label == "schema":
                    check(page_check.call_count == 0 and "unexpected" in tool["outcome"]["body"]["result"]["output"]["error"]["message"], tool)
                elif label == "page":
                    check(page_check.call_count == 1, "schema-valid relation did not reach page layer")
                else:
                    check(rt.dispatcher.last_invocation.reason == "bad_frame" and report.status == "blocked_unknown", report)
                    check(finish["payload"]["tool_result"]["output"]["error"]["code"] == "bad_frame", finish)
                    check(render_effect(tool).name == f"tool · {key} · unknown" and render_effect(tool).type == "error" and render_effect(tool).output == "bad_frame", tool)
                if expected_class == "failure":
                    check(report.status == "completed" and render_effect(tool).output == join_content(tool["outcome"]["body"]["result"]["output"]["content"]), report)
    print("[case] dispatcher: all11 independently; schema unknown key / schema-valid page relation -> invalid_tool_output; malformed frame -> unknown/bad_frame", flush=True)


def _unpinned_sql_negative(rt, scope, owner, *, expected_keys=HISTORICAL_KEYS, ceiling=None):
    calls = [{"key": "write", "args": {"path": "never.txt", "content": "never"}}]
    adapter = ScriptedUiAdapter([{"kind": "tool", **calls[0]}])
    adapter.body_byte_ceiling = ceiling
    rt.adapter = rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "unpinned"}], toolset="read", key="unpinned-" + uuid.uuid4().hex)
    pins = rt.db.host_run_pins(run, None, 64)
    check(not pins["has_more"] and {pin["key"] for pin in pins["items"]} == expected_keys, pins)
    before = rt.db.host_run_effects(run, None, None, 64)
    check(not before["has_more"] and len(before["items"]) == 1 and before["items"][0]["kind"] == "model_call" and before["items"][0]["status"] == "ready", before)
    model_id = before["items"][0]["effect_id"]
    responses = []
    original = rt.db.settle
    def capture(*args, **kwargs):
        response = original(*args, **kwargs)
        responses.append(response)
        return response
    with patch.object(rt.db, "settle", side_effect=capture), patch("v24.host.line_json.run", side_effect=AssertionError("unpinned call spawned a process")) as spawn:
        rt.worker.run_once(scope)
    page = rt.db.host_run_effects(run, None, None, 64)
    effects = page["items"]
    check(len(responses) == 1 and responses[0].get("disposition") == "committed" and responses[0].get("emitted") == [] and responses[0].get("effect_id") == model_id and "error" not in responses[0], responses)
    check(not page["has_more"] and len(effects) == 1 and effects[0]["effect_id"] == model_id and effects[0]["kind"] == "model_call" and effects[0]["status"] == "unknown", effects)
    check(not any(effect["kind"] == "tool_call" for effect in effects), effects)
    receipt = effects[0]["outcome"]
    check(receipt["class"] == "success" and receipt["body"]["result"]["tool_calls"] == calls and receipt["body"]["result"]["usage"]["tokens"] == 5, receipt)
    state = rt.run_state(run, 0)
    projection = state["run"]
    check(projection["status"] == "blocked_unknown" and projection["close_intent"] == {"kind": "unknown", "reason": "semantic_violation", "effect_id": model_id}, projection)
    check(projection["result"]["close_reason"] == "unknown" and projection["result"].get("final_text") is None and projection["interaction"] is None, projection)
    check(len(adapter.calls) == 1 and adapter.outcomes == [], "unpinned script not consumed exactly")
    spawn.assert_not_called()
    check(not (rt.env.workspace_root / "never.txt").exists(), "unpinned write ran")
    check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), "unpinned connections not idle")
    effect_record = render_effect(effects[0])
    check(effect_record.name == "model · unknown" and effect_record.type == "error" and effect_record.output == "unknown", effect_record)
    terminal = render_state(state, seen=frozenset())
    check(len(terminal) == 1 and terminal[0].type == "error" and "reason=semantic_violation" in terminal[0].output, terminal)
    print(f"[case] scripted unpinned write: requires={len(expected_keys)}; SQL settlement committed; model=unknown; run=blocked_unknown; reason=semantic_violation; close_reason=unknown; tool effects=0; subprocesses=0", flush=True)


def _journal_checks(rt):
    expected = {"command_prepared", "command_committed", "effect_prepared", "dispatch_started", "dispatch_finished", "settlement_committed"}
    check(EVENT_TYPES == expected, "journal event vocabulary changed")
    rows = [json.loads(line) for line in rt.env.journal_path.read_text().splitlines()]
    check(rows == list(rt.journal.records) and rows, "journal disk/in-memory mismatch")
    for index, row in enumerate(rows, 1):
        check(row["event_type"] in expected and row["seq"] == index, row)
    starts = [row for row in rows if row["event_type"] == "dispatch_started"]
    check(starts, "journal has no physical dispatch")
    for start in starts:
        finishes = [row for row in rows if row["event_type"] == "dispatch_finished" and row["effect_id"] == start["effect_id"] and row["claim"] == start["claim"]]
        check(len(finishes) == 1 and finishes[0]["seq"] > start["seq"] and finishes[0]["request_digest"] == start["request_digest"], start)
    # Verify the journal itself rejects a seventh event type.
    try:
        rt.journal.append("unknown_event", "probe", "0" * 64, {})
    except JournalCorrupt:
        pass
    else:
        raise AssertionError("journal accepted a seventh event type")
    print(f"[case] journal before crash: disk records={len(rows)}; six-event closed vocabulary; dispatch pairs={len(starts)}", flush=True)


def _claimed_recovery(rt, workspace):
    realm = "historical-crash-" + uuid.uuid4().hex[:8]
    scope = rt.create_scope(realm)
    crash_families = rt._families(scope, "read")
    rt.install_tools(scope, crash_families)
    _database_digest_assertions(rt, scope, crash_families)
    adapter = ScriptedUiAdapter([{"kind": "tool", "key": "read", "args": {"path": "README.md"}}])
    rt.adapter = rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, rt.fiber_for(scope, "v24.ui.pi_tools"), [{"role": "user", "content": "crash"}], toolset="read", key="crash-" + uuid.uuid4().hex)
    rt.worker.run_once(scope)  # Real model settlement emits the ready tool.
    crash_worker = HostWorker(rt.db, rt.journal, adapter=adapter, tool_handler=rt.dispatcher.tool_handler, resource_handler=rt.dispatcher.resource_handler, default_lease_ms=1, crash_after="started")
    with patch("v24.host.line_json.run", side_effect=AssertionError("crash window ran a subprocess")) as spawn:
        try:
            crash_worker.run_once(scope)
        except HostCrash as exc:
            check(str(exc) == "scripted crash after dispatch_started", str(exc))
        else:
            raise AssertionError("missing scripted crash")
        spawn.assert_not_called()
    effects = rt.db.host_run_effects(run, None, None, 64)["items"]
    claimed = next(effect for effect in effects if effect["kind"] == "tool_call")
    ident = str(claimed["effect_id"])
    check(claimed["status"] == "claimed" and rt.journal.has("dispatch_started", ident) and not rt.journal.has("dispatch_finished", ident), claimed)
    discovery = rt.discovery(run)
    notified = []
    rt.advance(discovery, on_effect=notified.append)
    check(ident in discovery.active and ident not in discovery.finalized, discovery)
    deadline = time.monotonic() + 3
    while rt.db.remaining_lease_ms(claimed["lease_until"]) > 0:
        check(time.monotonic() < deadline, "one-ms crash lease did not expire")
        time.sleep(0.005)
    recovery = HostWorker(rt.db, rt.journal, adapter=adapter, tool_handler=rt.dispatcher.tool_handler, resource_handler=rt.dispatcher.resource_handler, default_lease_ms=1)
    recovery.run_once(scope)
    rt.advance(discovery, on_effect=notified.append)
    rt.advance(discovery, on_effect=notified.append)
    terminal = rt.db.host_effect(ident)["effect"]
    check(terminal["status"] == "unknown" and ident not in discovery.active and ident in discovery.finalized, terminal)
    check(sum(str(effect["effect_id"]) == ident for effect in notified) == 1, notified)
    check(_effect_map(discovery.records) == _effect_map(rt.replay(run)), "recovered timeline differs")
    check((rt.run_state(run, 0)["run"])["status"] == "blocked_unknown", "crash recovery did not terminate")
    print("[case] crash-after-started: claimed enters active; real lease recovery -> unknown; exactly one terminal notification; full replay equal", flush=True)


def _drift_checks(db, env, work):
    # env.main is exercised against this disposable DB and SQL source copy.
    # No tracked source or persistent UI environment is changed.
    source_root = work / "source-copy"
    shutil.copytree(ROOT / "v24" / "sql", source_root / "v24" / "sql")
    metadata = env.data_dir / "loaded.json"
    def status():
        output = io.StringIO()
        with patch.object(env_module, "open_env", return_value=env), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = env_module.main(["--status"])
        return code, output.getvalue().strip().splitlines()[-1]
    with patch.object(env_module, "ROOT", source_root):
        baseline = env_module._current(env)
        env_module._write_json(metadata, baseline)
        check(status()[0] == 0, "disposable status baseline failed")
        sql = source_root / "v24" / "sql" / SQL_LOAD_ORDER[0]
        original = sql.read_bytes()
        try:
            sql.write_bytes(original + b"\n")
            code, last = status()
            check(code == 2 and json.loads(last)["status"] == "schema_drift" and "file_digests" in json.loads(last)["diffs"], (code, last))
            print(f"[case] drift SQL copy: exit={code}; last={last}", flush=True)
        finally:
            sql.write_bytes(original)
        for field, value in (("database_oid", baseline["database_oid"] + 1), ("sql_manifest_digest", "0" * 64)):
            env_module._write_json(metadata, {**baseline, field: value})
            code, last = status()
            check(code == 2 and field in json.loads(last)["diffs"], (code, last))
            print(f"[case] drift {field}: exit={code}; last={last}", flush=True)
        env_module._write_json(metadata, baseline)
        check(status()[0] == 0, "metadata restoration failed")
        conn = connect(db.admin_dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET ROLE v24_owner")
                cur.execute("DROP TABLE v24.events CASCADE")
            conn.commit()
            check(env_module._fingerprint(conn) != baseline["db_fingerprint"], "dropped table did not change db_fingerprint")
        finally:
            conn.close()
        code, last = status()
        check((code, last) == (2, "schema_drift"), (code, last))
        print(f"[case] drift dropped table: db_fingerprint changed; exit={code}; last={last}", flush=True)


def _interaction_render_smoke():
    record = render_generating()
    check(record.name == "generating" and record.output == "生成中…（完成后一次性给出回答）", record)
    state = {"run":{"run_id":"r","status":"completed","turn_no":3,"remaining_tokens":0,"result":{"final_text":"done"}}}
    check(render_state(state, seen=frozenset())[0].name == "run · completed", state)
    for reason in ("transport", "finish_length"):
        effect = {"kind": "model_call", "status": "unknown", "outcome": {"body": {"result": {"reason": reason}}}}
        check(render_effect(effect).output == reason, effect)
    check(render_effect({"kind": "model_call", "status": "unknown", "outcome": {"body": None}}).output == "unknown", "unknown None fallback")
    # A credential-shaped source is refused, not byte-equality PASS and not a
    # redacted placeholder. Ordinary source examples can be false positives.
    for text in ("Bearer token-shaped-example", "postgres://example"):
        effect = {"kind": "tool_call", "status": "succeeded", "outcome": {"body": {"result": {"output": {"content": [{"type": "text", "text": text}]}}}}}
        before = copy.deepcopy(effect)
        try:
            render_effect(effect)
        except ValueError as exc:
            check(str(exc) == "render_secret_detected", str(exc))
            check(effect == before, "refusal mutated durable tool bytes")
        else:
            raise AssertionError("credential-shaped content was rendered")
    plain = "def token_count(): return 1\n# Authorization and token are ordinary source words\n"
    check(render_effect({"kind":"tool_call", "status":"succeeded", "outcome":{"body":{"result":{"output":{"content":[{"type":"text", "text":plain}]}}}}}).output == plain, "ordinary source text changed")
    for payload in ({"api_key":"example"}, {"prompt":"x" * 2100 + " Bearer example"}):
        try:
            render_state({"run":{"status":"waiting", "interaction":{"interaction_id":"i"}}}, seen=frozenset(), interaction_payload=payload)
        except ValueError as exc:
            check(str(exc) == "render_secret_detected", str(exc))
        else:
            raise AssertionError("separate waiting payload bypassed credential scan")
    print("[case] render credential scan: refusal/no record/no mutation; source examples may match; ordinary token words verbatim; full waiting payload checked", flush=True)


def _valid_args(key):
    return {"read": {"path": "README.md"}, "read_file": {"path": "README.md"},
        "write": {"path": "probe.txt", "content": "ok"},
        "edit": {"path": "README.md", "edits": [{"oldText": "v24", "newText": "v24-new"}]},
        "bash": {"command": "printf ok"}, "grep": {"pattern": "v24"},
        "find": {"pattern": "*.md"}, "ls": {"path": "."},
        "file_search": {"pattern": "v24"}, "get_file_tree": {"max_depth": 1},
        "apply_edits": {"path": "README.md", "rewrite": "ok"}}[key]


def _production_run(rt, toolset):
    realm = "m4-" + toolset + "-" + uuid.uuid4().hex[:8]
    scope = rt.create_scope(realm)
    families = rt._families(scope, toolset)
    rt.install_tools(scope, families)
    expected = {"read": READ_KEYS, "write": WRITE_KEYS, "exec": EXEC_KEYS}[toolset]
    # Both families execute inside this SAME run, including write10's mutation.
    if toolset == 'write':
        script = [tool_reply('mutation', 'write', {'path': 'write10.txt', 'content': 'write10 persisted\n'}),
                  tool_reply('readback', 'read_file', {'path': 'write10.txt'})]
        called_keys = {'write', 'read_file'}
    else:
        script = [tool_reply("skill", "read", {"path": ".v24/skills/repo-recon/SKILL.md", "limit": 4}),
                  tool_reply("rp", "get_file_tree", {"max_depth": 0})]
        called_keys = {'read', 'get_file_tree'}
    script.append(final_reply("m4 complete"))
    adapter, transport = model_adapter(script)
    _v2_script_names(transport)
    adapter.body_byte_ceiling = 8000
    rt.adapter = rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, rt.fiber_for(scope, "v24.ui.pi_tools"),
        [{"role": "system", "content": _app_prompt()}, {"role": "user", "content": "inspect"}],
        toolset=toolset, key="m4-" + uuid.uuid4().hex,
        budget={"steps": 40, "tool_calls": 24, "tokens": 40000, "wall_ms": 600000})
    pin_page = rt.db.host_run_pins(run, None, 64)
    pins = pin_page["items"]
    check(not pin_page["has_more"] and {pin['key'] for pin in pins} == expected, (toolset, pins))
    observed = []
    original = adapter.build
    def build(effect, history, actual_pins):
        prepared = original(effect, history, actual_pins)
        row = _measure(prepared, actual_pins, toolset + str(len(expected)) + "-actual-app", len(observed) + 1)
        check(row["body_bytes"] <= 8000 and {tool['function']['name'] for tool in prepared.body['tools']} == expected, row)
        observed.append(prepared)
        return prepared
    with patch.object(adapter, "build", side_effect=build):
        report = rt.drive(scope)
    check(report.status == "completed" and report.final_text == "m4 complete", (toolset, report, rt.run_state(run, 0)))
    check(len(observed) == len(transport.calls) == len(script) and transport.script == [], "production build/send counts")
    for prepared, sent in zip(observed, transport.calls):
        check(json.loads(sent["body"]) == prepared.body, "production sent body differs")
        print(f"[wire] scenario={toolset}{len(expected)} sha256={hashlib.sha256(sent['body']).hexdigest()}", flush=True)
    tools = [effect for effect in rt.replay(run) if effect['kind'] == 'tool_call']
    check(len(tools) == len(script) - 1 and {effect['request']['key'] for effect in tools} == called_keys, "same-run both families")
    if toolset == 'write':
        check('bash' not in expected and all(effect['status'] == 'succeeded' for effect in tools)
              and (rt.env.workspace_root / 'write10.txt').read_bytes() == b'write10 persisted\n', 'write10 mutation/continuation')
        readback = next(effect for effect in tools if effect['request']['key'] == 'read_file')
        check(readback['outcome']['body']['result']['output']['value']['text'] == 'write10 persisted\n', 'write10 durable readback')
    for effect in tools:
        durable = rt.db.host_effect(effect['effect_id'])['effect']
        check(durable == effect, "durable outcome unreadable")
        output = durable['outcome']['body']['result']['output']
        step = render_effect(durable)
        check(step.output.encode() == join_content(output['content']).encode(), "production UI/model bytes")
        if effect['request']['key'] == 'bash':
            value = output['value']
            check(effect['status'] == 'succeeded' and '\x00' not in value['text'], effect)
            if effect['request']['args']['command'].startswith('printf'):
                check(value['text'] == 'a\ufffdb' and value['exit_code'] == 0, effect)
            else: check(value['exit_code'] == 2 and 'Command exited with code 2' in value['text'], effect)
        if effect['request']['key'] == 'apply_edits':
            if 'rewrite' in effect['request']['args']:
                check(effect['status'] == 'failed' and output['error']['code'] == 'mode_conflict', effect)
            else: check(effect['status'] == 'succeeded' and output['value']['status'] == 'failed', effect)
    _database_digest_assertions(rt, scope, families)
    check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), 'production connection not idle')
    print(f"[case] production {toolset}{len(expected)} same-run both families; body.tools==durable pins; actual-app start+continuations<=8000; terminal", flush=True)
    return scope, run, families


def _observed_app_drive(rt, scope, adapter, scenario, *, expected_system=None, expected_tool_text=None):
    """Observe the real adapter's admission encoding without changing its policy."""
    from v24.host import deepseek
    rows = []
    original = adapter.build
    def build(effect, history, pins):
        check({pin['key'] for pin in pins} == EXEC_KEYS, 'actual-app boundary durable exec11 pins')
        bodies = []
        def canonical(value):
            encoded = provider_json(value)
            if isinstance(value, dict) and value.get('model') == 'deepseek-flash' and 'messages' in value:
                bodies.append((copy.deepcopy(value), encoded.encode('utf-8')))
            return encoded
        try:
            with patch.object(deepseek, '_canonical', side_effect=canonical):
                prepared = original(effect, history, pins)
        except AdapterFailure as exc:
            check(exc.reason == 'body_too_large' and len(bodies) == 1, ('unexpected app build failure', exc.reason))
            body, raw = bodies[0]
            if expected_system is not None:
                check(body['messages'][0] == {'role': 'system', 'content': expected_system}, 'oversize app prompt/history altered')
            if expected_tool_text is not None:
                messages = [message['content'] for message in body['messages'] if message['role'] == 'tool']
                check(messages and messages[-1] == expected_tool_text, 'oversize build lacks complete tool result')
            check('max_tokens' not in body and len(raw) > 8000
                  and {item['function']['name'] for item in body['tools']} == EXEC_KEYS, 'oversized actual app body')
            row = dict(scenario=scenario, ordinal=len(rows) + 1, pins=sorted(pin['key'] for pin in pins),
                body_bytes=len(raw), estimate=len(raw) + 256, reserve=effect['request']['reserve']['tokens'], failure=exc.reason,
                admission_body_sha256=hashlib.sha256(raw).hexdigest())
            rows.append(row)
            BUILD_MEASUREMENTS.append(row)
            print('[measurement] ' + json.dumps(row, sort_keys=True), flush=True)
            raise
        row = _measure(prepared, pins, scenario, len(rows) + 1)
        rows.append(row)
        return prepared
    with patch.object(adapter, 'build', side_effect=build):
        report = rt.drive(scope)
    return report, rows


def _assert_app_admission_failure(rt, run, transport, sent_count):
    effects = rt.replay(run)
    failed = [effect for effect in effects if effect['kind'] == 'model_call' and effect['status'] == 'failed']
    check(len(failed) == 1 and effects[-1] == failed[0], ('app failure successors', effects))
    effect = failed[0]
    check(rt.db.host_effect(effect['effect_id'])['effect'] == effect and effect['outcome']['class'] == 'failure', 'app failure not durable')
    check(rt.journal.last('effect_prepared', str(effect['effect_id']))['payload']['local_failure'] == 'body_too_large', 'app failure reason')
    check(not rt.journal.has('dispatch_started', str(effect['effect_id'])) and len(transport.calls) == sent_count
          and len(transport.script) == 1, 'app oversized build sent/consumed provider script')
    check(rt.run_state(run, 0)['run']['status'] == 'failed', 'app admission did not terminate run')
    check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), 'app admission connections not IDLE')


def _actual_app_limits(rt, scope):
    path = rt.env.workspace_root / 'exec11-2001.txt'
    data = b'q' * 2000 + b'\n'
    path.write_bytes(data)
    adapter, transport = model_adapter([tool_reply('full-read', 'read', {'path': path.name}), final_reply('must not send')])
    _v2_script_names(transport)
    adapter.body_byte_ceiling = 8000
    rt.adapter = rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, rt.fiber_for(scope, 'v24.ui.pi_tools'),
        [{'role': 'system', 'content': _app_prompt()}, {'role': 'user', 'content': 'inspect'}], toolset='exec')
    check({pin['key'] for pin in rt.db.host_run_pins(run, None, 64)['items']} == EXEC_KEYS, 'exec2001 pins')
    report, rows = _observed_app_drive(rt, scope, adapter, 'exec11-actual-app-2001',
        expected_system=_app_prompt(), expected_tool_text=data.decode())
    check(len(rows) == 2 and rows[0]['body_bytes'] <= 8000 and rows[1].get('failure') == 'body_too_large', ('exec2001 builds', report, rows))
    _assert_app_admission_failure(rt, run, transport, 1)
    tool = next(effect for effect in rt.replay(run) if effect['kind'] == 'tool_call')
    output = tool['outcome']['body']['result']['output']
    check(tool['status'] == 'succeeded' and rt.db.host_effect(tool['effect_id'])['effect'] == tool
          and output['value']['text'].encode() == data and join_content(output['content']).encode() == data
          and render_effect(tool).output.encode() == data, 'exec2001 retained exact durable/UI bytes')
    path.unlink()
    print('[case] exec11 complete actual-app + exact2001 read: first send succeeds; second real build body_too_large; result retained; no extra send; terminal failed; IDLE', flush=True)

    # Use the real SessionStore renderer and SQL final outcomes with the actual
    # app helper. Backend orchestration/Chainlit belongs to the separate M3 probe.
    from v24.ui.sessions import SessionStore
    with tempfile.TemporaryDirectory(prefix='m4-history-') as temp:
        store = SessionStore(temp, read_run=lambda run_id: rt.run_state(run_id, 0)['run'])
        conversation = str(uuid.uuid4())
        prior = []
        for ordinal in range(1, 4):
            history = store.history_block(conversation)
            for _, final in prior:
                check(final in history, 'history was shortened before admission')
            final = chr(64 + ordinal) * 700
            adapter, transport = model_adapter([final_reply(final)])
            adapter.body_byte_ceiling = 8000
            rt.adapter = rt.worker.adapter = adapter
            run, _ = rt.start_run(scope, rt.fiber_for(scope, 'v24.ui.pi_tools'),
                [{'role': 'system', 'content': _app_prompt(history)}, {'role': 'user', 'content': 'inspect'}], toolset='exec')
            report, rows = _observed_app_drive(rt, scope, adapter, 'exec11-actual-app-history-turn' + str(ordinal),
                expected_system=_app_prompt(history))
            check(len(rows) == 1, 'history build count')
            if ordinal < 3:
                check(report.status == 'completed' and report.final_text == final and len(transport.calls) == 1
                      and not transport.script and rows[0]['body_bytes'] <= 8000, ('history prior run', ordinal, report))
                store.append_turn(conversation_id=conversation, run_id=run, seq=ordinal, user_text='inspect')
                prior.append((run, final))
            else:
                check(rows[0].get('failure') == 'body_too_large', ('history failed boundary', rows))
                _assert_app_admission_failure(rt, run, transport, 0)
                check(len(store.history(conversation)) == 4 and store.history_block(conversation) == history, 'admission altered conversation history')
                for old_run, old_final in prior:
                    check(rt.run_state(old_run, 0)['run']['result']['final_text'] == old_final, 'prior durable final lost')
    print('[case] exec11 real SessionStore accumulated history + actual app helper: two durable final turns; third first-build body_too_large; no history trimming/extra send; prior results retained; IDLE; Backend/browser covered separately', flush=True)


def _workspace_gone_lifecycle(rt):
    """Exercise approved lifecycle frames through the real dispatcher, no mocks."""
    with tempfile.TemporaryDirectory(prefix='m4-gone-workspace-') as temp:
        env = copy.copy(rt.env)
        env.workspace_root = Path(temp) / 'workspace'
        env.workspace_root.mkdir()
        env.journal_path = Path(temp) / 'journal.jsonl'
        env.spawn_dir = Path(temp) / 'spawn'
        env.spawn_dir.mkdir()
        child = AgentRuntime(env, mode='fake', adapter=ScriptedUiAdapter([]))
        try:
            scope = child.create_scope('workspace-gone-' + uuid.uuid4().hex[:8])
            families = child._families(scope, 'exec')
            installs = child.install_tools(scope, families)
            _database_digest_assertions(child, scope, families)
            from v24.host import line_json
            def resource(effect):
                with patch.object(line_json, 'run_process', wraps=line_json.run_process) as process:
                    result = child.dispatcher.resource_handler(effect)
                check(process.call_count == 1, 'lifecycle spawned extra/repeated preparation')
                wire = json.loads(process.call_args.args[0].stdin)
                request = effect['request']
                if effect['kind'] == 'inspect_resource':
                    expected_frame = {'v': 2, 'operation': 'inspect', 'reservation': request['target_reservation'],
                        'args': {'install_id': request['install_id'], 'target': request['target']}}
                else:
                    expected_frame = {'v': 2, 'operation': 'release', 'reservation': request['reservation'],
                        'args': {'install_id': request['install_id']}}
                check(wire == expected_frame, ('actual lifecycle stdin ABI', wire, expected_frame))
                return result
            prepared = [row for row in child.journal.records if row['event_type'] == 'dispatch_started'
                        and row['payload'].get('kind') == 'host_prepare']
            check(len(prepared) == 2, 'workspace gone preparation count')
            moved = Path(temp) / 'moved'
            env.workspace_root.rename(moved)
            for state in ('moved', 'deleted'):
                if state == 'deleted': moved.rmdir()
                for install in installs.values():
                    reservation = 'v24:host_release:' + str(uuid.uuid4())
                    effect = {'kind': 'host_release', 'scope_id': scope, 'effect_id': str(uuid.uuid4()),
                              'request': {'install_id': install, 'reservation': reservation}}
                    status, result = resource(effect)
                    check(status == 'success' and result['released'] is True, ('workspace gone release', state, status, result))
                    for target in ('host_prepare', 'host_release'):
                        inspection = {'kind': 'inspect_resource', 'scope_id': scope, 'effect_id': str(uuid.uuid4()),
                            'request': {'install_id': install, 'target': target, 'target_reservation': 'v24:' + target + ':' + str(uuid.uuid4())}}
                        status, result = resource(inspection)
                        check(status == 'success' and result['observed'] == 'known', ('workspace gone recovery inspect', state, target, result))
                adapter, transport = model_adapter([tool_reply('gone-pi', 'read', {'path': 'README.md'}),
                    tool_reply('gone-rp', 'read_file', {'path': 'README.md'}), final_reply('gone rejected')])
                _v2_script_names(transport)
                adapter.body_byte_ceiling = 8000
                child.adapter = child.worker.adapter = adapter
                run, _ = child.start_run(scope, child.fiber_for(scope, 'v24.ui.pi_tools'), [{'role': 'user', 'content': 'gone'}], toolset='exec')
                report = child.drive(scope)
                tools = [effect for effect in child.replay(run) if effect['kind'] == 'tool_call']
                check(report.status == 'completed' and len(tools) == 2 and len(transport.calls) == 3 and not transport.script, 'workspace gone invoke continuation')
                check(all(effect['status'] == 'failed' and effect['outcome']['body']['result']['output']['error']['code'] == 'workspace_unavailable'
                          for effect in tools), ('workspace gone dispatcher preflight', tools))
                for family, key in zip(families, ('read', 'read_file')):
                    plugin = child.plugins[(scope, family.identity)]
                    result, frame = _run_artifact(plugin, tool=key, args={'path': 'README.md'}, work_env=env)
                    check(result.returncode == 3 and frame['ok'] is False and frame['error']['code'] == 'root_unavailable',
                          ('workspace gone artifact invoke', state, family.identity, frame))
            check(sum(row['event_type'] == 'dispatch_started' and row['payload'].get('kind') == 'host_prepare'
                      for row in child.journal.records) == 2, 'workspace gone repeated prepare')
            check(child.db.idle(child.db.control) and child.db.idle(child.db.service), 'workspace gone connections not IDLE')
        finally:
            child.close()
    print('[case] real approved dispatcher both families workspace moved/deleted: stateless release+recovery inspect succeed; exact actual stdin ABI; no prepare repeated; dispatcher workspace_unavailable/artifact root_unavailable; IDLE', flush=True)


def _durable_tool_cases(rt, scope):
    for key, args, status, detail in [
        ('bash', {'command': "printf 'a\\000b'"}, 'succeeded', 'nul'),
        ('bash', {'command': 'exit 2'}, 'succeeded', 'exit'),
        ('apply_edits', {'path': 'README.md', 'rewrite': 'x', 'edits': [{'oldText': 'v24', 'newText': 'x'}]}, 'failed', 'conflict'),
        ('apply_edits', {'path': 'README.md', 'edits': [{'oldText': 'never-present', 'newText': 'x'}]}, 'succeeded', 'miss')]:
        adapter, transport = model_adapter([tool_reply(detail, key, args), final_reply('continued')])
        _v2_script_names(transport)
        adapter.body_byte_ceiling = 8000
        rt.adapter = rt.worker.adapter = adapter
        run, _ = rt.start_run(scope, rt.fiber_for(scope, 'v24.ui.pi_tools'), [{'role': 'user', 'content': detail}], toolset='exec')
        check({pin['key'] for pin in rt.db.host_run_pins(run, None, 64)['items']} == EXEC_KEYS, 'durable exec pins')
        report = rt.drive(scope)
        check(report.status == 'completed' and report.final_text == 'continued' and len(transport.calls) == 2 and not transport.script, ('durable case', detail, report))
        effect = next(item for item in rt.replay(run) if item['kind'] == 'tool_call')
        durable = rt.db.host_effect(effect['effect_id'])['effect']
        check(durable == effect and effect['status'] == status, ('jsonb durable read', detail, effect))
        output = effect['outcome']['body']['result']['output']
        check(render_effect(effect).output.encode() == join_content(output['content']).encode(), 'durable UI bytes')
        if detail == 'nul': check(output['value']['text'] == 'a\ufffdb' and '\x00' not in output['value']['text'] and output['value']['exit_code'] == 0, effect)
        elif detail == 'exit': check(output['value']['exit_code'] == 2 and 'Command exited with code 2' in output['value']['text'], effect)
        elif detail == 'conflict': check(output['error']['code'] == 'mode_conflict', effect)
        else: check(output['value']['status'] == 'failed', effect)
        body = json.loads(transport.calls[-1]['body'])
        check([msg['content'] for msg in body['messages'] if msg['role'] == 'tool'][-1].encode() == join_content(output['content']).encode(), 'durable continuation bytes')
    print('[case] durable exec11 NUL/nonzero/mode_conflict/all-miss: JSONB outcome readable; correct settlement class; UI/model bytes equal; real second send; terminal continues', flush=True)


def _coexistence(rt, old_scope, old_families, new_scope, new_families):
    # No replacement registry: runtime contains old and new approvals together.
    check(rt.scopes[old_scope] != rt.scopes[new_scope], 'coexist realms collide')
    for scope, families in ((old_scope, old_families), (new_scope, new_families)):
        for row in rt.db.host_scope_installs(scope, None, 64)['items']:
            approved = rt.dispatcher.registry.lookup_install(row)
            family = next(item for item in families if item.identity == row['identity'])
            check(approved.artifact_digest == hashlib.sha256(family.artifact.read_bytes()).hexdigest(), 'coexist digest')
        adapter, transport = model_adapter([tool_reply('coexist', 'read', {'path': 'README.md', 'limit': 1}), final_reply('coexists')])
        _v2_script_names(transport)
        adapter.body_byte_ceiling = None if scope == old_scope else 8000
        rt.adapter = rt.worker.adapter = adapter
        run, _ = rt.start_run(scope, rt.fiber_for(scope, 'v24.ui.pi_tools'), [{'role': 'user', 'content': 'coexist'}], toolset='read')
        report = rt.drive(scope)
        check(report.status == 'completed' and report.final_text == 'coexists' and len(transport.calls) == 2 and not transport.script, 'coexist legitimate call')
        check(next(effect for effect in rt.replay(run) if effect['kind'] == 'tool_call')['status'] == 'succeeded', 'coexist tool failed')
    old = {family.identity: catalog.build_plugin(family, rt.env) for family in old_families}
    new = {family.identity: catalog.build_plugin(family, rt.env) for family in new_families}
    check(all(old[key].artifact_digest != new[key].artifact_digest for key in old), 'coexist same artifact')
    print('[case] simultaneous old/new registry coexistence: two distinct realms; all four approvals live; legitimate old and new calls completed', flush=True)


def _durable_body_failure(rt):
    scope = rt.create_scope('oversize-' + uuid.uuid4().hex[:8])
    families = rt._families(scope, 'exec')
    rt.install_tools(scope, families)
    _database_digest_assertions(rt, scope, families)
    adapter, transport = model_adapter([final_reply('must not send')])
    adapter.body_byte_ceiling = 8000
    rt.adapter = rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, rt.fiber_for(scope, 'v24.ui.pi_tools'), [{'role': 'user', 'content': '雪' * 8001}], toolset='exec')
    with patch('v24.host.line_json.run', side_effect=AssertionError('oversize spawned tool')) as spawn:
        rt.drive(scope)
    effects = rt.db.host_run_effects(run, None, None, 64)
    check(not effects['has_more'] and len(effects['items']) == 1, 'oversize successor')
    effect = effects['items'][0]
    check(effect['kind'] == 'model_call' and effect['status'] == 'failed' and effect['outcome']['class'] == 'failure', effect)
    check(rt.journal.last('effect_prepared', str(effect['effect_id']))['payload']['local_failure'] == 'body_too_large', 'oversize reason')
    check(not transport.calls and len(transport.script) == 1 and not rt.journal.has('dispatch_started', str(effect['effect_id'])), 'oversize sent provider')
    spawn.assert_not_called()
    check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), 'oversize IDLE')
    print('[case] durable body_too_large: failure/failed; zero sends/tools/successors; original script retained; both connections IDLE', flush=True)


def _admission_boundaries():
    adapter = DeepSeekAdapter(api_key="gate-fake-only", body_byte_ceiling=8000)
    def effect(size, reserve=4096, unicode=False):
        value = {"request": {"cause": "start", "reserve": {"tokens": reserve},
            "input": {"messages": [{"role": "user", "content": ""}], "max_output_tokens": 512}}}
        overhead = len(provider_json({"model": "deepseek-flash", "stream": False,
            "messages": value["request"]["input"]["messages"]}).encode())
        count = size - overhead
        value["request"]["input"]["messages"][0]["content"] = ("雪" * (count // 3) + "x" * (count % 3)) if unicode else "x" * count
        return value
    for unicode in (False, True):
        for size, allowance in ((3655, 185), (3839, 1), (3840, 512), (8000, 512)):
            prepared = adapter.build(effect(size, unicode=unicode), [], [])
            row = _measure(prepared, [], f"boundary-{'utf8' if unicode else 'ascii'}-{size}", 1)
            check(row["body_bytes"] == size and prepared.max_tokens == allowance, row)
        try: adapter.build(effect(8001, unicode=unicode), [], [])
        except AdapterFailure as exc: check(exc.reason == "body_too_large", exc.reason)
        else: raise AssertionError("8001 admitted")
    default = DeepSeekAdapter(api_key="gate-fake-only")
    check(default.body_byte_ceiling is None and default.build(effect(3655), [], []).max_tokens == 185, "default positive arithmetic")
    try: default.build(effect(3840), [], [])
    except AdapterFailure as exc: check(exc.reason == "reserve_insufficient", exc.reason)
    else: raise AssertionError("default policy changed")
    for reserve in (1, 7, 64, 185):
        check(adapter.build(effect(8000, reserve), [], []).max_tokens == reserve, "small reserve exceeded")
    for reserve in (0, -1, True, False, None, "4096"):
        try: adapter.build(effect(8000, reserve), [], [])
        except AdapterFailure as exc: check(exc.reason == "reserve_zero", exc.reason)
        else: raise AssertionError("invalid reserve admitted")
    print("[case] admission: UTF-8 exact8000 admitted/exact8001 body_too_large; default185 and reserve_insufficient; small/invalid reserves preserved", flush=True)


def _skills_contract(env):
    import xml.etree.ElementTree as ET
    shutil.copytree(ROOT / "v24/ui/skills", env.skills_root, dirs_exist_ok=True)
    os.environ["V24_SKILLS_ROOT"] = str(env.skills_root)
    block = catalog.available_skills()
    tree = ET.fromstring(block)
    check(tree.tag == "available_skills" and not tree.attrib and not (tree.text or "").strip(), "skills root shape")
    names = []
    for skill in tree:
        check(skill.tag == "skill" and not skill.attrib and [node.tag for node in skill] == ["name", "description", "location"], "skill fields")
        check(all(not node.attrib and len(node) == 0 for node in skill), "skill nested shape")
        name, description, location = [node.text for node in skill]
        check(re.fullmatch(r"[a-z0-9-]{1,64}", name) and 0 < len(description) <= 1024, "skill metadata")
        check(location == f".v24/skills/{name}/SKILL.md", "skill location")
        raw = (env.skills_root / name / "SKILL.md").read_text()
        check(raw.startswith(f"---\nname: {name}\ndescription: {description}\n---\n"), "skill frontmatter bytes")
        names.append(name)
    check(names == ["repo-recon", "surgical-edit"], names)
    with tempfile.TemporaryDirectory(prefix="v24-skills-invalid-") as temp:
        root = Path(temp).resolve()
        (root / "sample").mkdir()
        file = root / "sample/SKILL.md"
        invalid = ["---\nname: Bad\ndescription: ok\n---\n", "---\nname: sample\ndescription: \n---\n",
            "---\nname: sample\ndescription: " + "x" * 1025 + "\n---\n",
            "---\nname: other\ndescription: ok\n---\n", "---\nname: sample\nname: sample\n---\n",
            "---\nname: sample\ndescription: ok\nextra: bad\n---\n", "---\nname: sample\ndescription: |\n  multiline\n---\n"]
        with patch.dict(os.environ, {"V24_SKILLS_ROOT": str(root)}):
            for text in invalid:
                file.write_text(text)
                try: catalog.available_skills()
                except ValueError as exc: check(str(exc) == "invalid_skill", str(exc))
                else: raise AssertionError("invalid skill accepted")
            file.write_text("---\nname: sample\ndescription: A < B & C\n---\n")
            check(ET.fromstring(catalog.available_skills())[0][1].text == "A < B & C", "skill XML escaping")
            file.unlink(); file.symlink_to(env.skills_root / "repo-recon/SKILL.md")
            try: catalog.available_skills()
            except ValueError as exc: check(str(exc) == "invalid_skill", str(exc))
            else: raise AssertionError("symlink skill accepted")
        with patch.dict(os.environ, {"V24_SKILLS_ROOT": str(root / "missing")}):
            check(len(ET.fromstring(catalog.available_skills())) == 0, "missing skills root")
    print("[case] skills: exact XML/frontmatter shape; two real skills; malformed/duplicate/extra/length/symlink rejected; XML escaped", flush=True)


def _tool_semantics(rt, scope):
    """Black-box approved subprocess checks against independently known bytes."""
    families = rt._families(scope, "exec")
    plugins = {tool.key: catalog.build_plugin(family, rt.env) for family in families for tool in family.tools}
    specs = {tool.key: tool for family in families for tool in family.tools}
    workspace = rt.env.workspace_root
    called = set()
    def invoke(key, args, error=None):
        called.add(key)
        result, frame = _run_artifact(plugins[key], tool=key, args=args, work_env=rt.env)
        check(result.stderr == b"" and set(frame) == ({"ok", "v", "error"} if error else {"ok", "v", "result"}), (key, frame, result.stderr))
        if error:
            check(result.returncode == 3 and frame["ok"] is False and frame["error"] == {"code": error, "message": error}, (key, args, frame))
            return frame
        check(result.returncode == 0 and frame["ok"] is True and frame["v"] == 2 and set(frame["result"]) == {"value", "meta"} and frame["result"]["meta"] == {}, (key, args, frame))
        value = frame["result"]["value"]
        compile_schema(specs[key].output_schema, kind="output_schema")(value)
        validate_page(RENDERERS.by_id("v24.text.plain", 1).ref, args, value)
        check("\x00" not in value["text"] and len(value["text"].encode()) <= 32768 and len(value["text"].splitlines()) <= 2000 and len(compact_json(value)) <= 40960 - 128, (key, "budgets"))
        return value
    target = workspace / "semantics.txt"
    target.write_text("first\n雪😀\nlast\n")
    check(invoke("read", {"path": target.name})["text"] == target.read_text(), "read verbatim")
    check(invoke("read", {"path": target.name, "offset": 99})["text"] == "", "read beyond EOF")
    check(invoke("read_file", {"path": target.name, "start_line": -1})["text"] == "last\n", "RP tail")
    check(invoke("read_file", {"path": target.name, "start_line": -99})["text"] == target.read_text(), "RP large tail")
    invoke("read_file", {"path": target.name, "start_line": 0}, "invalid_arguments")
    invoke("read_file", {"path": target.name, "start_line": -1, "limit": 1}, "invalid_arguments")
    (workspace / "empty.txt").write_bytes(b"")
    check(invoke("read", {"path": "empty.txt"})["text"] == invoke("read_file", {"path": "empty.txt"})["text"] == "", "empty read")
    check(invoke("write", {"path": "nested/new.txt", "content": "é"})["text"] == "wrote 2 bytes", "write byte count")
    invoke("write", {"path": "nested/new.txt", "content": "雪", "append": True})
    check((workspace / "nested/new.txt").read_bytes() == "é雪".encode(), "append")
    invoke("write", {"path": "nested/new.txt", "content": "replacement"})
    check((workspace / "nested/new.txt").read_text() == "replacement", "overwrite")
    check((workspace / "nested/new.txt").stat().st_mode & 0o777 == 0o600, "new file permissions")
    for original, edits, expected in [
        ("alpha beta gamma", [{"oldText": "alpha", "newText": "beta"}, {"oldText": "beta", "newText": "B"}], "beta B gamma"),
        ('x “café”—ﬁne\t  end z', [{"oldText": '"café"-fine end', "newText": "OK"}], "x OK z"),
        ("before cafe\u0301 after", [{"oldText": "café", "newText": "tea"}], "before tea after")]:
        target.write_text(original)
        invoke("edit", {"path": target.name, "edits": edits})
        check(target.read_text() == expected, ("Pi edit", original, target.read_text()))
    for original, edits, error in [
        ("abc", [{"oldText": "", "newText": "x"}], "edit_empty_old"),
        ("abc", [{"oldText": "z", "newText": "x"}], "edit_not_found"),
        ("aaa", [{"oldText": "aa", "newText": "x"}], "edit_ambiguous"),
        ("abc", [{"oldText": "abc", "newText": "x"}, {"oldText": "bc", "newText": "y"}], "edit_overlap"),
        ("abc", [{"oldText": "abc", "newText": "abc"}], "edit_noop"),
        ("ﬁne  fine", [{"oldText": "ｆｉｎｅ", "newText": "x"}], "edit_ambiguous"),
        ("ﬁne fine", [{"oldText": "ＦＩＮＥ", "newText": "x"}], "edit_not_found")]:
        target.write_text(original)
        invoke("edit", {"path": target.name, "edits": edits}, error)
        check(target.read_text() == original, "failed Pi edit mutated target")
    target.write_text("alpha beta")
    invoke("apply_edits", {"path": target.name, "rewrite": "bad", "edits": [{"oldText": "alpha", "newText": "x"}]}, "mode_conflict")
    for args in ({"path": target.name}, {"path": target.name, "edits": []}, {"path": target.name, "search": "alpha"}, {"path": target.name, "search": "alpha", "replace": "x", "on_missing": "create"}):
        invoke("apply_edits", args, "invalid_mode")
    for args, status, expected in [
        ({"edits": [{"oldText": "missing", "newText": "x"}]}, "failed", "alpha beta"),
        ({"edits": [{"oldText": "alpha", "newText": "A"}, {"oldText": "missing", "newText": "x"}]}, "partial", "A beta"),
        ({"search": "A", "replace": "Alpha"}, "success", "Alpha beta"),
        ({"rewrite": "Alpha beta"}, "no_change", "Alpha beta"),
        ({"edits": [{"oldText": "Alpha", "newText": "Alpha"}]}, "no_change", "Alpha beta"),
        ({"search": "MISSING", "replace": "x"}, "failed", "Alpha beta"),
        ({"rewrite": "rewritten"}, "success", "rewritten")]:
        check(invoke("apply_edits", {"path": target.name, **args})["status"] == status, (args, status))
        check(target.read_text() == expected, "RP mutation bytes")
    check(invoke("apply_edits", {"path": "created-empty", "rewrite": "", "on_missing": "create"})["status"] == "success" and (workspace / "created-empty").exists(), "empty create")
    invoke("apply_edits", {"path": "absent-rp", "rewrite": "x"}, "not_found")
    target.write_text("aaa")
    invoke("apply_edits", {"path": target.name, "search": "a", "replace": "b"}, "match_not_unique")
    check(target.read_text() == "aaa", "ambiguous RP mutated")
    invoke("apply_edits", {"path": target.name, "edits": [{"oldText": "a", "newText": "b"}]}, "edit_ambiguous")
    target.write_text("abcdef")
    invoke("apply_edits", {"path": target.name, "edits": [{"oldText": "abc", "newText": "x"}, {"oldText": "bc", "newText": "y"}]}, "edit_overlap")
    check(target.read_text() == "abcdef", "RP overlap mutated")
    target.write_text("“fuzzy”")
    check(invoke("apply_edits", {"path": target.name, "edits": [{"oldText": '"fuzzy"', "newText": "x"}]})["status"] == "failed" and target.read_text() == "“fuzzy”", "RP applied Pi normalization")
    for name, data, error in (("binary.dat", b"a\0b", "binary_file"), ("invalid.dat", b"\xff", "not_utf8"), ("oversize.dat", b"x" * (1024 * 1024 + 1), "file_too_large"), ("long-line.txt", b"x" * 40000, "line_too_long")):
        (workspace / name).write_bytes(data)
        for key in ("read", "read_file"):
            invoke(key, {"path": name}, error)
        if error in {"binary_file", "not_utf8", "file_too_large"}:
            for key in ("edit", "apply_edits"):
                invoke(key, {"path": name, "edits": [{"oldText": "a", "newText": "b"}]}, error)
            check((workspace / name).read_bytes() == data, "invalid input mutated")
    # Existing and absent sensitive targets must fail before existence checks.
    for name in (".env", "a.pem", "id_rsa", ".git/config", ".uidata/x"):
        path = workspace / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("private")
    for key in ("read", "write", "grep", "find", "ls", "read_file", "file_search", "get_file_tree", "edit", "apply_edits"):
        for name in (".env", "a.pem", "id_rsa", ".git/config", ".uidata/x", "missing/.env", "missing/a.PEM", "missing/ID_RSA"):
            args = {"path": name}
            if key == "write": args["content"] = "no"
            if key in {"grep", "find"}: args["pattern"] = "*" if key == "find" else "private"
            if key == "file_search": args = {"pattern": "private", "mode": "content", "filter": {"paths": [name]}}
            if key == "edit": args["edits"] = [{"oldText": "private", "newText": "no"}]
            if key == "apply_edits": args["rewrite"] = "no"
            invoke(key, args, "path_excluded")
    (workspace / "link.txt").symlink_to(target)
    for path, error in (("link.txt", "symlink_denied"), ("../outside", "path_escape"), (str(workspace.parent / "outside"), "path_escape"), (".v24/other", "path_excluded")):
        invoke("read", {"path": path}, error)
    for key in ("write", "edit", "apply_edits"):
        for path in (".v24/skills/repo-recon/SKILL.md", str(workspace / ".v24/skills/repo-recon/SKILL.md"), ".v24/spill/absent.txt"):
            args = {"path": path, **({"content": "x"} if key == "write" else {"rewrite": "x"} if key == "apply_edits" else {"edits": [{"oldText": "x", "newText": "y"}]})}
            invoke(key, args, "path_excluded")
    for name in ("repo-recon", "surgical-edit"):
        path = f".v24/skills/{name}/SKILL.md"
        for key in ("read", "read_file"):
            check(invoke(key, {"path": path})["text"].encode() == (rt.env.skills_root / name / "SKILL.md").read_bytes(), "skill mounted bytes")
    check(".v24" not in invoke("ls", {"path": "."})["text"] and not (workspace / ".v24").exists(), "virtual skills leaked into workspace")
    check(invoke("bash", {"command": "printf 'out'; printf 'err' >&2; exit 2"}) == {"text": "outerr\n\nCommand exited with code 2", "exit_code": 2, "truncated": False, "spill_path": ""}, "bash nonzero success")
    check(invoke("bash", {"command": "printf '\\377a\\000b'"})["text"] == "\ufffda\ufffdb", "bash UTF-8/NUL replacement")
    invoke("bash", {"command": "sleep 5 & echo $! > child.pid; wait", "timeout_ms": 100}, "timeout")
    pid = int((workspace / "child.pid").read_text())
    try: os.kill(pid, 0)
    except ProcessLookupError: pass
    else:
        # A reaped shell may leave a short-lived OS zombie, never a running child.
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], stdout=subprocess.PIPE, check=False).stdout.decode().strip()
        check(not state or state.startswith("Z"), ("bash timeout left running child", pid, state))
    check(called == EXEC_KEYS, ("tool coverage", called))
    print(f"[case] all11 approved subprocess semantics; exact/fuzzy/atomic edits; RP four statuses; sensitive exists/missing-first; readonly skills; bash nonzero/NUL/timeout cleanup; covered={sorted(called)}", flush=True)
    return invoke


def _discovery_semantics(invoke, workspace):
    base = workspace / 'discovery'
    (base / 'src/deep').mkdir(parents=True)
    (base / '.gitignore').write_text('*.tmp\n!keep.tmp\nignored/\n')
    (base / '.ignore').write_text('blocked.txt\n')
    (base / '.fdignore').write_text('last.txt\n')
    files = {'src/alpha.py': 'before\nNeedle one\nNeedle two\nafter\n', 'src/deep/leaf.txt': 'needle\n',
        'a.tmp': 'needle\n', 'keep.tmp': 'needle\n', 'blocked.txt': 'needle\n', 'last.txt': 'needle\n',
        'ignored/reopen.txt': 'needle\n', '.hidden': 'needle\n'}
    for name, text in files.items():
        path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    (base / 'binary.dat').write_bytes(b'needle\0')
    found = invoke('find', {'path': 'discovery', 'pattern': '*'})['text'].splitlines()
    check(found == ['discovery/binary.dat', 'discovery/keep.tmp', 'discovery/src/alpha.py', 'discovery/src/deep/leaf.txt'], ('Pi ignore subset', found))
    check(invoke('find', {'path': 'discovery', 'pattern': '**/*.py'})['text'] == 'discovery/src/alpha.py', 'Pi recursive glob')
    grep = invoke('grep', {'path': 'discovery', 'pattern': 'needle', 'ignoreCase': True, 'glob': '*.py', 'context': 1})['text']
    check(all(f'discovery/src/alpha.py:{line}:' in grep for line in (1, 2, 3, 4)) and grep.count(':2:') == 1 and 'matches=2' in grep, ('grep merged context', grep))
    check('matches=1' in invoke('grep', {'path': 'discovery', 'pattern': 'Needle one', 'literal': True, 'limit': 1})['text'], 'grep literal/limit')
    check('skipped_binary=1' in invoke('grep', {'path': 'discovery', 'pattern': 'needle', 'ignoreCase': True})['text'], 'grep binary accounting')
    invoke('grep', {'pattern': '['}, 'invalid_arguments')
    (base / 'wide.txt').write_text('needle ' + 'x' * 700 + '\n')
    line = invoke('grep', {'path': 'discovery/wide.txt', 'pattern': 'needle'})['text'].splitlines()[0].split(': ', 1)[1]
    check(len(line) == 500 and line.endswith('…'), 'grep display line cap')
    listing = invoke('ls', {'path': 'discovery'})['text'].splitlines()
    check(listing == sorted(listing) and 'src/' in listing and '.hidden' not in listing and '.v24' not in listing, 'ls sort/exclusions')
    check(invoke('ls', {'path': 'discovery', 'limit': 2})['text'].splitlines() == listing[:2], 'ls cap')
    zero = invoke('get_file_tree', {'path': 'discovery', 'max_depth': 0})['text']
    check(zero == 'discovery/', ('tree depth0', zero))
    auto = invoke('get_file_tree', {'path': 'discovery'})['text']
    full = invoke('get_file_tree', {'path': 'discovery', 'mode': 'full'})['text']
    folders = invoke('get_file_tree', {'path': 'discovery', 'mode': 'folders'})['text']
    selected = invoke('get_file_tree', {'path': 'discovery', 'mode': 'selected'})['text']
    check('leaf.txt' not in auto and 'leaf.txt' in full and 'alpha.py' not in folders and 'deep/' in folders, 'tree modes/depth')
    check('[No selection; showing full tree.]' in selected and selected.replace('\n[No selection; showing full tree.]', '') == full, 'tree selected')
    check('.hidden' not in full and 'ignored/' in full, 'tree hidden/no added ignore policy')
    print('[case] Pi ignore/glob/case/literal/context/binary/line cap; ls sorted/capped; RP tree auto/full/folders/selected/depth0', flush=True)


def _bash_spill(invoke, env):
    # 63 pages exceeds the 50-file retention window; bytes are independent of
    # artifact formatting, include UTF-8, CRLF, an unterminated line and a literal
    # placeholder path that must never be replaced inside source content.
    endings = ('\n', '\r\n', '\r', '\u2028', '\v', '\n', '\n')
    placeholder = '.v24/spill/' + '0' * 32 + '.txt literal-source'
    lines = ''.join(f'line-{number:04d} 雪😀 café payload' + (' ' + placeholder if number in (0, 2800) else '') + endings[number % len(endings)] for number in range(3101))
    lines += placeholder
    (env.workspace_root / 'bash-lines.txt').write_text(lines)
    value = invoke('bash', {'command': "cat bash-lines.txt; printf 'a\\000b'; exit 2"})
    check(value['truncated'] and value['exit_code'] == 2 and re.fullmatch(r'\.v24/spill/[0-9a-f]{32}\.txt', value['spill_path']), value)
    source = env.spill_root / Path(value['spill_path']).name
    full = source.read_bytes()
    check(full == (lines + 'a\ufffdb\n\nCommand exited with code 2').encode() and b'\0' not in full and 'line-3100' in value['text'] and 'line-0000' not in value['text'], 'bash tail/full spill')
    check('.v24/spill/' + '0' * 32 + '.txt literal-source' in value['text'], 'command formatter replaced source placeholder bytes')
    before = set(env.spill_root.iterdir())
    mtime = source.stat().st_mtime_ns
    source_lines = full.decode().splitlines(keepends=True)
    total = len(source_lines)
    for key, coordinate in (('read', 'offset'), ('read_file', 'start_line')):
        for path in (value['spill_path'], str(env.workspace_root / value['spill_path'])):
            reconstructed = []
            for offset in range(1, total + 1, 50):
                page = invoke(key, {'path': path, coordinate: offset, 'limit': 50})
                selected = ''.join(source_lines[offset - 1:offset + 49])
                last = min(offset + 49, total)
                truncated = last < total
                suffix = (f'[Showing lines {offset}-{last} of {total}. Use {coordinate}={last + 1} to continue. Full text: {value["spill_path"]}]') if truncated else ''
                expected = selected + ('' if not suffix or not selected or selected.endswith(tuple('\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029')) else '\n') + suffix
                check(page['text'] == expected and page['truncated'] is truncated and page['spill_path'] == (value['spill_path'] if truncated else ''), (key, path, offset, 'spill page bytes/reference'))
                reconstructed.append(selected)
                check(source.exists() and set(env.spill_root.iterdir()) == before and source.stat().st_mtime_ns == mtime, f'spill paging allocated/pruned/rewrote source at offset={offset}')
            check(''.join(reconstructed).encode() == full and source.read_bytes() == full, 'bash spill reconstruction')
            check(invoke(key, {'path': path, coordinate: total + 1})['text'] == '', 'spill EOF')
    tail = invoke('read_file', {'path': value['spill_path'], 'start_line': -total})
    check(tail['truncated'] and tail['spill_path'] == value['spill_path'] and 'Use start_line=' in tail['text'] and set(env.spill_root.iterdir()) == before, 'spill negative tail')
    invoke('read', {'path': '.v24/spill/' + 'f' * 32 + '.txt'}, 'not_found')
    check(set(env.spill_root.iterdir()) == before, 'missing spill allocated')
    print(f'[case] bash tail+NUL+nonzero spill; four Pi/RP relative/absolute cases; pages={(total + 49) // 50} each; >50 retention boundary; exact UTF-8/LF/CRLF/lone-CR/U+2028/VT/placeholder bytes; zero page allocations', flush=True)


def _escaped_budget_projection(invoke, env):
    # Canonical escaping, rather than raw text size alone, must drive shrinking.
    text = ('\b\t"\\' * 24 + '\n') * 800
    (env.workspace_root / 'escape-budget.txt').write_text(text)
    for key in ('read', 'read_file'):
        value = invoke(key, {'path': 'escape-budget.txt'})
        check(value['truncated'] and len(value['text'].encode()) < 32768 and len(compact_json(value)) <= 40832, 'escaped value did not shrink to canonical budget')
        spill = env.spill_root / Path(value['spill_path']).name
        check(spill.read_bytes() == text.encode(), 'escaped source spill bytes')
        reconstructed = []
        for offset in range(1, 801, 50):
            page = invoke('read', {'path': value['spill_path'], 'offset': offset, 'limit': 50})
            payload = page['text'].rsplit('[Showing lines ', 1)[0] if page['truncated'] else page['text']
            reconstructed.append(payload)
        check(''.join(reconstructed).encode() == text.encode(), 'escaped spill readback')
    print('[case] escape-heavy text: canonical value budget converges before spill; Pi/RP whole-line projections and exact readback', flush=True)


def _teardown_runs(rt):
    """Multi-key family retirement must converge in SQL, not just UI caches."""
    for toolset, expected in (('read', READ_KEYS), ('exec', EXEC_KEYS)):
        scope = rt.create_scope('teardown-' + toolset + '-' + uuid.uuid4().hex[:8])
        families = rt._families(scope, toolset)
        installs = rt.install_tools(scope, families)
        check(len(installs) == 2, ('teardown install count', toolset, installs))
        _database_digest_assertions(rt, scope, families)
        adapter, transport = model_adapter([final_reply('ready to close')])
        adapter.body_byte_ceiling = 8000
        rt.adapter = rt.worker.adapter = adapter
        run, _ = rt.start_run(scope, rt.fiber_for(scope, 'v24.ui.pi_tools'),
            [{'role': 'user', 'content': 'teardown'}], toolset=toolset)
        pins = rt.db.host_run_pins(run, None, 64)
        check(not pins['has_more'] and {pin['key'] for pin in pins['items']} == expected, 'teardown actual pins')
        report = rt.drive(scope)
        check(report.status == 'completed' and report.final_text == 'ready to close'
              and len(transport.calls) == 1 and not transport.script, ('teardown run', report))
        before = {}
        for install in installs.values():
            page = rt.db.host_install_fibers(install, None, 64)
            check(not page['has_more'] and len(page['items']) == 1, 'teardown fiber count')
            fiber = page['items'][0]
            check(fiber['want_on'] and fiber['disposed_at'] is None, 'teardown initially active fiber')
            before[install] = fiber
        if toolset == 'read':
            # One already-off fiber exercises the retry/re-entry boundary.
            install = installs['v24.ui.pi_tools']
            fiber = before[install]
            value = rt._rpc("SELECT v24.fiber_control(%s,'off',%s,%s)",
                (fiber['fiber_id'], fiber['control_seq'], 'gate-off-' + uuid.uuid4().hex))
            check(value.get('disposition') in ('committed', 'deferred'), value)
            before[install] = rt.db.host_install_fibers(install, None, 64)['items'][0]
            check(before[install]['want_on'] is False, 'pre-off did not commit')
            rt.uninstall_tools(scope, [family.identity for family in families])
            rows = rt.db.host_scope_installs(scope, None, 64)
            check(not rows['has_more'] and len(rows['items']) == 2
                  and all(row['state'] == 'disposed' and row['disposed_at'] is not None for row in rows['items']),
                  ('explicit uninstall did not converge', rows))
        # exec takes the actual browser close path, including implicit uninstall.
        closed = rt.close_scope(scope)
        check(closed.get('disposition') in ('committed', 'replay'), closed)
        scopes = rt.db.host_scopes(scope, None, 64)
        check(not scopes['has_more'] and len(scopes['items']) == 1
              and scopes['items'][0]['closed_at'] is not None, ('SQL scope not terminal', toolset, scopes))
        rows = rt.db.host_scope_installs(scope, None, 64)
        check(not rows['has_more'] and {str(row['install_id']) for row in rows['items']} == set(installs.values()), 'teardown install identities')
        for row in rows['items']:
            install = str(row['install_id'])
            check(row['state'] == 'disposed' and row['disposed_at'] is not None, ('install not disposed', row))
            fibers = rt.db.host_install_fibers(install, None, 64)
            check(not fibers['has_more'] and len(fibers['items']) == 1, 'disposed fiber count')
            fiber = fibers['items'][0]
            original = before[install]
            check(fiber['disposed_at'] is not None and fiber['want_on'] is False
                  and fiber['control_seq'] == original['control_seq'] + int(original['want_on']),
                  ('fiber not disposed or repeated off', fiber, original))
        effects = rt.db.host_effects(scope, None, None, 64)
        # host_effects is the ACTIVE-only queue, not a history endpoint.
        check(not effects['has_more'] and effects['items'] == [], ('teardown active host effects remain', effects))
        starts = [row for row in rt.journal.records if row['event_type'] == 'dispatch_started'
                  and row['payload'].get('kind') == 'host_release'
                  and str(row['payload'].get('request', {}).get('install_id')) in set(installs.values())]
        releases = [rt.db.host_effect(row['effect_id'])['effect'] for row in starts]
        check(len(releases) == 2 and all(effect['kind'] == 'host_release' and effect['status'] == 'succeeded' for effect in releases)
              and {str(effect['request']['install_id']) for effect in releases} == set(installs.values()), 'missing/duplicate host release')
        for effect in releases:
            for event in ('dispatch_started', 'dispatch_finished'):
                check(sum(row['event_type'] == event and str(row.get('effect_id')) == str(effect['effect_id'])
                          for row in rt.journal.records) == 1, ('duplicate physical release', event, effect['effect_id']))
        check(len(transport.calls) == 1 and not transport.script, 'teardown sent another model request')
        check(rt.run_state(run, 0)['run']['status'] == 'completed', 'teardown changed terminal run')
        check(scope not in rt.scopes and scope not in rt.caches
              and not any(key[0] == scope for key in rt.plugins), 'teardown cache/approval retained')
        check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), 'teardown connections not IDLE')
        print(f'[case] teardown {toolset}{len(expected)}: both family installs/fibers disposed; off once; releases=2/physical dispatches=2; extra model sends=0; SQL scope.closed_at set; connections IDLE', flush=True)


def _main():
    check('chainlit' not in sys.modules, 'gate imported Chainlit')
    ui_root = ROOT / "v24" / "ui"
    sources = [ui_root / 'plugins/pi_tools.py', ui_root / 'plugins/rp_tools.py', ui_root / 'app.py', ui_root / 'catalog.py', ui_root / 'control.py', ROOT / 'v24/host/deepseek.py', *sorted((ui_root / 'skills').glob('*/SKILL.md'))]
    before_sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    print('[source] ' + json.dumps(before_sources, sort_keys=True), flush=True)
    pi = ui_root / "plugins" / "pi_tools.py"
    rp = ui_root / "plugins" / "rp_tools.py"
    check(tuple(path.name for path in validate_manifest()) == SQL_LOAD_ORDER and len(SQL_LOAD_ORDER) == 12, "SQL manifest/order mismatch")
    _artifact_structure((pi, rp))
    _assert_shared_core(pi, rp)
    print("[case] family shared core and canonical JSON parity: passed", flush=True)
    _schema_and_page_checks()
    print("[case] v24.text.plain all11 schema/page/render + exact descriptor contracts: passed", flush=True)
    _interaction_render_smoke()
    print("[case] generating and normal terminal render: passed", flush=True)
    original = {key: os.environ.get(key) for key in ("V24_WORKSPACE_ROOT", "V24_SPILL_ROOT", "V24_SKILLS_ROOT", "V24_UI_MODE", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "PGPASSWORD")}
    try:
        with contextlib.ExitStack() as fixtures, setup_db() as db, tempfile.TemporaryDirectory(prefix="v24-ui-m4-") as temp:
            work = Path(temp).resolve()
            env = _temp_env(db, work)
            _skills_contract(env)
            _admission_boundaries()
            historical = work / 'historical'
            historical.mkdir()
            fixtures.enter_context(_historical_catalog(historical))
            workspace = env.workspace_root
            workspace.mkdir(exist_ok=True)
            (workspace / "README.md").write_text("# v24 M2 acceptance\n", encoding="utf-8")
            os.environ["V24_WORKSPACE_ROOT"] = "/intentionally/wrong"
            os.environ["V24_SPILL_ROOT"] = str(env.spill_root)
            rt = AgentRuntime(env, mode="fake", adapter=ScriptedUiAdapter([]))
            try:
                realm = "historical-ui-" + uuid.uuid4().hex[:8]
                scope = rt.create_scope(realm)
                families = rt._families(scope, "read")
                rt.install_tools(scope, families)
                owner = rt.fiber_for(scope, "v24.ui.pi_tools")
                run, timeline, steps, adapter, families = _main_run(rt, scope, owner, workspace)
                print("[case] primary sequence: exact 10 steps; 2 requires/2 pins; owner=pi_tools; provider has 3 scripted calls", flush=True)
                _database_digest_assertions(rt, scope, families)
                print("[case] DB install/fiber digest checks and artifact/realm negative controls: passed", flush=True)
                read_scope, read_run, read_families = _production_run(rt, 'read')
                exec_scope, exec_run, exec_families = _production_run(rt, 'exec')
                _production_run(rt, 'write')
                _actual_app_limits(rt, exec_scope)
                _workspace_gone_lifecycle(rt)
                _coexistence(rt, scope, families, read_scope, read_families)
                _durable_tool_cases(rt, exec_scope)
                _durable_body_failure(rt)
                invoke = _tool_semantics(rt, exec_scope)
                _discovery_semantics(invoke, workspace)
                _bash_spill(invoke, env)
                _escaped_budget_projection(invoke, env)
                _search_semantics(rt, read_scope, workspace)
                _spill_and_sensitive(rt, read_scope, rt.fiber_for(read_scope, 'v24.ui.pi_tools'), workspace)
                _big_text_run(rt, read_scope, rt.fiber_for(read_scope, 'v24.ui.pi_tools'), workspace, expected_keys=READ_KEYS, ceiling=8000)
                _env_isolation(rt, read_scope)
                _interaction_runs(rt, scope, owner)
                _spill_and_sensitive(rt, scope, owner, workspace)
                print("[case] spill paging and sensitive-path rejection: passed", flush=True)
                _search_semantics(rt, scope, workspace)
                _env_isolation(rt, scope)
                print("[case] subprocess environment allowlist/workspace-root isolation: passed", flush=True)
                _assert_closed_schema(db)
                print("[case] SQL catalog closure: ten tables, no views/extensions", flush=True)
                _big_text_run(rt, scope, owner, workspace)
                _dispatcher_checks(rt, workspace)
                _teardown_runs(rt)
                _unpinned_sql_negative(rt, scope, owner)
                _unpinned_sql_negative(rt, read_scope, rt.fiber_for(read_scope, 'v24.ui.pi_tools'), expected_keys=READ_KEYS, ceiling=8000)
                _journal_checks(rt)
                _claimed_recovery(rt, workspace)
                check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), "database connection left in transaction")
                check(len(rt.db.host_run_pins(run, None, 64).get("items", [])) == 2, "main run pin count")
                print("[gate] owner fiber=pi_tools; requires=2; non-owner provider=rp_tools:file_search; pins={read,file_search}")
                print("[gate] exact step sequence, scripted calls, incremental/full replay, page/schema, spill, path fence, environment isolation verified")
                check({str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources} == before_sources, 'source changed mid-gate: discard fixture and rerun')
                _drift_checks(db, env, work)
                check('chainlit' not in sys.modules, 'gate gained Chainlit dependency')
                marker = f"[passed] v24 UI gate; steps={len(steps)}; effects={len(timeline)}; artifacts={len(families)}; families={len(families)}"
                check(marker == PASS_LAST, marker)
                print(marker)
            finally:
                rt.close()
    finally:
        for key, value in original.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
    return 0


def main():
    with contextlib.ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.create_connection", "urllib.request.urlopen"):
            stack.enter_context(patch(target, side_effect=AssertionError("UI gate attempted network I/O")))
        for call in (lambda: socket.socket().connect(("127.0.0.1", 1)), lambda: socket.create_connection(("127.0.0.1", 1)), lambda: urllib.request.urlopen("https://example.invalid")):
            try:
                call()
            except AssertionError as exc:
                check(str(exc) == "UI gate attempted network I/O", str(exc))
            else:
                raise AssertionError("no-network guard ineffective")
        return _main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[failed] v24 UI gate; {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
