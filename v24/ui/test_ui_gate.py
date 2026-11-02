#!/usr/bin/env python3
"""Disposable, socket-free M2 acceptance gate for the v24 UI slice."""
from __future__ import annotations

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
from v24.host.deepseek import _canonical as provider_json
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


def check(condition, message):
    if not condition:
        raise AssertionError(message)


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
    from v24.host.canonical import compact_json as host_json
    values = [None, True, False, 0, -17, "", "é/😀", "\b\t\n\f\r\"\\", {"é": 1, "z": [True, None]},
              {"x": "q" * 4096}, ["", 1, {"a": "b"}], {"a": 1, "é": 2}]
    for value in values:
        check(module.canonical_json(value).encode() == (host_json(value) if isinstance(host_json(value), bytes) else host_json(value).encode()), "canonical JSON mismatch")
    return module


def _temp_env(db, work):
    root = work.resolve()
    for name in ("workspace", "spawn", "spill"):
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
        "skills_root": ROOT / "v24" / "ui" / "skills",
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
    result = subprocess.run(plugin.argv, cwd=plugin.cwd, env=environment, input=compact_json(request) + b"\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    check(result.stdout.endswith(b"\n") and result.stdout.count(b"\n") == 1, "artifact frame shape")
    return result, json.loads(result.stdout)


def _schema_and_page_checks():
    families = catalog.families("ui-test", "read")
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
            good = {"text": "ok", "truncated": False, "spill_path": ""}
            validate(good)
            try:
                validate({**good, "unexpected": True})
            except Exception:
                pass
            else:
                raise AssertionError("schema accepted unknown key")
            ref = RENDERERS.by_id("v24.text.plain", 1).ref
            try:
                validate_page(ref, {}, {"text": "ok", "truncated": False, "spill_path": "x"})
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
    names = {provider_tool_name(key): key for key in ("read", "file_search")}
    for reply in transport.script:
        for call in reply.get("raw", {}).get("choices", [{}])[0].get("message", {}).get("tool_calls", []):
            function = call["function"]
            function["name"] = names[function["name"]]


def _main_run(rt, scope, owner, workspace):
    (workspace / "README.md").write_text("# v24 M2 acceptance\n", encoding="utf-8")
    adapter, transport = model_adapter([
        tool_reply("call_1", "read", {"path": "README.md", "limit": 5}),
        tool_reply("call_2", "file_search", {"pattern": "v24", "mode": "content", "max_results": 3}),
        final_reply("done"),
    ])
    _v2_script_names(transport)
    rt.adapter = adapter; rt.worker.adapter = adapter
    families = rt._families(scope, "read")
    installs = rt.install_tools(scope, families)
    check(len(installs) == 2 and {Path(f.artifact).stem for f in families} == {"pi_tools", "rp_tools"}, installs)
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "read and search"}], toolset="read", key=f"m2-main-{uuid.uuid4().hex}")
    pins = rt.db.host_run_pins(run, None, 64).get("items", [])
    pin_keys = {item["key"] for item in pins}
    check(pin_keys == {"read", "file_search"}, f"owner fiber pin set mismatch: {pin_keys}")
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


def _big_text_run(rt, scope, owner, workspace):
    target = workspace / "long.txt"
    target.write_text("A" * 2001, encoding="ascii")
    adapter, transport = model_adapter([
        tool_reply("call_big", "read", {"path": "long.txt"}),
        final_reply("large complete"),
    ])
    _v2_script_names(transport)
    rt.adapter = adapter; rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "read long"}], toolset="read", key=f"m2-big-{uuid.uuid4().hex}")
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
        observations.append({"estimate": prepared.estimate, "reserve": prepared.reserve_tokens,
                             "max_tokens": prepared.max_tokens,
                             "body_sha256": hashlib.sha256(provider_json(prepared.body).encode()).hexdigest(),
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
    check(continuation["reserve"] == 4096 and continuation["max_tokens"] >= 5 and continuation["estimate"] <= continuation["reserve"], continuation)
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
    for identity in ("v24.ui.pi_tools", "v24.ui.rp_tools"):
        for label, (frame, exit_code, expected_class, expected_code) in cases.items():
            realm = "probe-" + uuid.uuid4().hex[:8]
            scope = rt.create_scope(realm)
            family = next(f for f in rt._families(scope, "read") if f.identity == identity)
            key = family.tools[0].key
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
                rt.install_tools(scope, tuple(replace(item, artifact=artifact) if item.identity == identity else item for item in rt._families(scope, "read")))
                owner = rt.fiber_for(scope, identity)
                args = {"path": "README.md"} if key == "read" else {"pattern": "v24"}
                adapter = ScriptedUiAdapter([{"kind": "tool", "key": key, "args": args}, {"kind": "final", "text": "probe done"}])
                rt.adapter = rt.worker.adapter = adapter
                run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "probe"}], toolset="read", key="probe-" + uuid.uuid4().hex)
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
    print("[case] dispatcher: both families; output_check unknown key / page relation -> invalid_tool_output; malformed frame -> unknown/bad_frame", flush=True)


def _unpinned_sql_negative(rt, scope, owner):
    calls = [{"key": "write", "args": {"path": "never.txt", "content": "never"}}]
    adapter = ScriptedUiAdapter([{"kind": "tool", **calls[0]}])
    rt.adapter = rt.worker.adapter = adapter
    run, _ = rt.start_run(scope, owner, [{"role": "user", "content": "unpinned"}], toolset="read", key="unpinned-" + uuid.uuid4().hex)
    pins = rt.db.host_run_pins(run, None, 64)
    check(not pins["has_more"] and {pin["key"] for pin in pins["items"]} == {"read", "file_search"}, pins)
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
    print("[case] scripted unpinned write: SQL settlement committed; model=unknown; run=blocked_unknown; reason=semantic_violation; close_reason=unknown; tool effects=0; subprocesses=0", flush=True)


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
    realm = "crash-" + uuid.uuid4().hex[:8]
    scope = rt.create_scope(realm)
    rt.install_tools(scope, rt._families(scope, "read"))
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


def _main():
    ui_root = ROOT / "v24" / "ui"
    pi = ui_root / "plugins" / "pi_tools.py"
    rp = ui_root / "plugins" / "rp_tools.py"
    check(tuple(path.name for path in validate_manifest()) == SQL_LOAD_ORDER and len(SQL_LOAD_ORDER) == 12, "SQL manifest/order mismatch")
    _assert_shared_core(pi, rp)
    print("[case] family shared core and canonical JSON parity: passed", flush=True)
    _schema_and_page_checks()
    print("[case] v24.text.plain schema/page/render semantics for M2 tools: passed", flush=True)
    _interaction_render_smoke()
    print("[case] generating and normal terminal render: passed", flush=True)
    original = {key: os.environ.get(key) for key in ("V24_WORKSPACE_ROOT", "V24_SPILL_ROOT", "V24_UI_MODE", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "PGPASSWORD")}
    try:
        with setup_db() as db, tempfile.TemporaryDirectory(prefix="v24-ui-m2-") as temp:
            work = Path(temp).resolve()
            env = _temp_env(db, work)
            workspace = env.workspace_root
            workspace.mkdir(exist_ok=True)
            (workspace / "README.md").write_text("# v24 M2 acceptance\n", encoding="utf-8")
            os.environ["V24_WORKSPACE_ROOT"] = "/intentionally/wrong"
            os.environ["V24_SPILL_ROOT"] = str(env.spill_root)
            rt = AgentRuntime(env, mode="fake", adapter=ScriptedUiAdapter([]))
            try:
                realm = "ui-" + uuid.uuid4().hex[:8]
                scope = rt.create_scope(realm)
                families = rt._families(scope, "read")
                rt.install_tools(scope, families)
                owner = rt.fiber_for(scope, "v24.ui.pi_tools")
                run, timeline, steps, adapter, families = _main_run(rt, scope, owner, workspace)
                print("[case] primary sequence: exact 10 steps; 2 requires/2 pins; owner=pi_tools; provider has 3 scripted calls", flush=True)
                _database_digest_assertions(rt, scope, families)
                print("[case] DB install/fiber digest checks and artifact/realm negative controls: passed", flush=True)
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
                _unpinned_sql_negative(rt, scope, owner)
                _journal_checks(rt)
                _claimed_recovery(rt, workspace)
                check(rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service), "database connection left in transaction")
                check(len(rt.db.host_run_pins(run, None, 64).get("items", [])) == 2, "main run pin count")
                print("[gate] owner fiber=pi_tools; requires=2; non-owner provider=rp_tools:file_search; pins={read,file_search}")
                print("[gate] exact step sequence, scripted calls, incremental/full replay, page/schema, spill, path fence, environment isolation verified")
                _drift_checks(db, env, work)
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
