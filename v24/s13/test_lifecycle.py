"""W4c lifecycle, mixed batch, replay and legacy-byte gate.

G12-A…H + G12-L from design §7.3.  The tests use real Python/Node plugin
subprocesses, the local PostgreSQL test database and the existing journal
replay path.  No provider socket is opened and no real provider is constructed.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _path in (HERE, HERE / "plugins", ROOT, ROOT / "v24" / "s11",
              ROOT / "v24" / "s1", ROOT / "v24" / "s2", ROOT / "v24" / "s4"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import server_helper_scope, setup_db  # noqa: E402

from plugin_fixtures import (  # noqa: E402
    PluginHarness,
    _chat_body,
    build_registry,
    build_spec,
    final_reply,
    model_adapter,
    tool_reply,
)
from fixtures import (  # noqa: E402
    DESCRIPTORS,
    V2Spec,
    manifest_bytes,
    node_spec,
    open_harness,
    read_spec,
    spawn_count,
    workspace,
)
from v24.host import line_json  # noqa: E402
from v24.host.deepseek import _v2_provider_name  # noqa: E402
from v24.host.journal import HostJournal  # noqa: E402
from v24.host.registry import (  # noqa: E402
    ApprovedAdapterRegistry,
    ApprovedPlugin,
    ApprovedTool,
    adapter_declaration_digest,
)
from v24.host.renderers import (  # noqa: E402
    RENDERERS, RendererError, RendererRef,
)
from v24.host.tool_pages import validate_page  # noqa: E402
from v24.host.worker import HostCrash, HostWorker  # noqa: E402

STUB = HERE / "w4_stub_plugin.py"
B0 = ROOT / "v24" / "b0" / "golden"


def node_path():
    return shutil.which("node")


class ZeroSpawn:
    def __init__(self):
        self.calls = []
        self._saved = None

    def __enter__(self):
        self._saved = line_json.run_process

        def sentinel(*args, **kwargs):
            self.calls.append((args, kwargs))
            raise AssertionError("unexpected run_process call")

        line_json.run_process = sentinel
        return self

    def __exit__(self, exc_type, exc, tb):
        line_json.run_process = self._saved
        assert self.calls == [], self.calls
        return False


def batch_reply(calls, *, reasoning="plan", usage=(10, 5),
                response_id="resp-tool"):
    encoded = []
    for call_id, key, args in calls:
        encoded.append({
            "id": call_id,
            "type": "function",
            "function": {
                "name": _v2_provider_name(key),
                "arguments": json.dumps(args, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")),
            },
        })
    return {
        "status": 200,
        "advance_ms": 7,
        "raw": _chat_body(content=None, finish="tool_calls",
                          tool_calls=encoded, usage=usage,
                          reasoning=reasoning, response_id=response_id),
    }


def tool_effects(harness, model_id):
    found = []
    for record in harness.journal.records:
        if record.get("event_type") != "dispatch_finished":
            continue
        payload = record.get("payload") or {}
        if (payload.get("kind") == "tool_call"
                and str(payload.get("parent_effect_id")) == str(model_id)):
            found.append(harness.effect_row(record["effect_id"]))
    return found


def run_pins(harness, run_id):
    response = harness.db.host_run_pins(run_id, None, 64)
    assert not response.get("error"), response
    return {item["key"]: item for item in response.get("items", [])}


def two_install_harness(fixture, base, realm):
    portable = workspace(base / "portable", "portable")
    listing = workspace(base / "list", "list")
    read = read_spec(base / "read", portable.root, realm=realm)
    node = node_spec(base / "node", listing.root, realm=realm)
    harness = open_harness(fixture, [read, node], base / "harness", realm=realm)
    read_id = harness.admit(read)
    node_id = harness.admit(node)
    harness.prepare([read_id, node_id])
    harness.activate(read_id, "read")
    harness.activate(node_id, "list")
    return harness, read_id, node_id, read, node


def start_run(harness, owner_install, requires, text):
    fiber = harness.fiber(owner_install)
    response = harness.start(fiber["fiber_id"], requires,
                             [{"role": "user", "content": text}])
    return response["emitted"][0], response["emitted"][1]


def teardown_two_install(harness, install_ids):
    for install_id in install_ids:
        harness.off(install_id)
    for install_id in install_ids:
        harness.dispose(install_id)
    harness.run(None, max_rounds=16)
    for install_id in install_ids:
        row = harness.install_row(install_id)
        assert row["state"] == "disposed", row
        assert row["disposed_at"] is not None, row
        fiber = harness.fiber(install_id)
        assert fiber["disposed_at"] is not None, fiber
        assert harness.count(
            "v24.slots WHERE fiber_id=%s AND released_at IS NULL",
            (fiber["fiber_id"],)) == 0
    scope = harness.close_scope()
    assert scope["closed_at"] is not None, scope


def stub_spec(base, workspace_root, scenario, *, timeout_ms=5000):
    base = Path(base)
    install = base / "install"
    install.mkdir(parents=True, exist_ok=True)
    artifact = install / "w4_stub_plugin.py"
    shutil.copyfile(STUB, artifact)
    descriptor = copy.deepcopy(DESCRIPTORS["read"])
    descriptor["tool"]["key"] = "read"
    descriptor["tool"]["description"] = "W4c stub read"
    descriptor["tool"]["limits"]["timeout_ms"] = timeout_ms
    descriptor["tool"]["parameters"]["properties"]["scenario"] = {
        "type": "string",
        "enum": ["ok", "known_error", "bad_frame", "extra_frame", "no_lf",
                 "timeout", "nonempty_meta", "bad_value", "bad_relation",
                 "huge_value", "crash"],
    }
    realm = f"w4c-stub-{uuid.uuid4().hex[:8]}"
    manifest = manifest_bytes("v24.w4c.stub", realm, [descriptor], "python")
    spawn = base / "spawn"; spawn.mkdir(exist_ok=True)
    log = spawn / f"{uuid.uuid4().hex}.log"
    tool = ApprovedTool.from_descriptor(descriptor, key="read")
    plugin = ApprovedPlugin(
        adapter_id=f"v24.w4c.stub.{realm}",
        language="python",
        identity="v24.w4c.stub",
        version="1",
        manifest_digest=hashlib.sha256(manifest).hexdigest(),
        artifact_digest=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        adapter_digest=adapter_declaration_digest("python"),
        argv=(sys.executable, str(artifact), "serve",
              "--spawn-log", str(log)),
        cwd=str(install),
        environment_allowlist=("PATH", "HOME", "V24_WORKSPACE_ROOT"),
        tools=(tool,),
        workspace_root=os.path.realpath(workspace_root),
    )
    return V2Spec(
        language="python", identity="v24.w4c.stub", realm=realm,
        tool_keys=("read",), manifest=manifest,
        artifact_digest=plugin.artifact_digest, entry=plugin,
        spawn_log=log, workspace=os.path.realpath(workspace_root),
        env_overlay=(),
    )


def run_stub(fixture, base, scenario, args, *, timeout_ms=5000):
    empty = workspace(base / "empty", "empty")
    spec = stub_spec(base, empty.root, scenario, timeout_ms=timeout_ms)
    harness = open_harness(fixture, [spec], base / "harness", realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        run_id, model_id = start_run(harness, install_id, ["read"], scenario)
        script = [batch_reply([("call_1", "read", args)]),
                  final_reply("must-not-run")]
        harness.run(script, max_rounds=20)
        effects = tool_effects(harness, model_id)
        assert len(effects) == 1, effects
        return harness, install_id, run_id, model_id, effects[0], spec
    except Exception:
        harness.close()
        raise


def g12_a(fixture, base):
    harness, read_id, node_id, read, node = two_install_harness(
        fixture, base / "a", f"w4c-a-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "g12-a")
        script = [
            batch_reply([
                ("call_read", "read", {"path": "tail"}),
                ("call_list", "list", {"path": "."}),
                ("call_search", "search", {"query": "x"}),
            ]),
            final_reply("g12-a-final"),
        ]
        harness.run(script, max_rounds=30)
        run = harness.run_row(run_id)
        assert run["status"] == "completed", run
        assert run["result"]["final_text"] == "g12-a-final", run
        effects = tool_effects(harness, model_id)
        assert len(effects) == 3, effects
        by_key = {item["request"]["key"]: item for item in effects}
        assert set(by_key) == {"read", "list", "search"}, by_key
        for key in by_key:
            assert by_key[key]["outcome"]["class"] == "success", by_key[key]
            value = by_key[key]["outcome"]["body"]["result"]["output"]["value"]
            assert value["path"] in ("tail", "."), value
            tool = (read.entry if key == "read" else node.entry).tool_for(key)
            assert tool is not None
            tool.output_check(value)
            validate_page(tool.render, by_key[key]["request"]["args"], value)
        pins = run_pins(harness, run_id)
        assert pins["list"]["provider_install_id"] == \
            pins["search"]["provider_install_id"]
        assert pins["read"]["provider_install_id"] != \
            pins["list"]["provider_install_id"]
        assert spawn_count(harness, read_id) == 2, spawn_count(harness, read_id)
        assert spawn_count(harness, node_id) == 3, spawn_count(harness, node_id)
        teardown_two_install(harness, [read_id, node_id])
    finally:
        harness.close()


def g12_b(fixture, base):
    harness, read_id, node_id, _read, _node = two_install_harness(
        fixture, base / "b", f"w4c-b-{uuid.uuid4().hex[:8]}")
    try:
        run_id, model_id = start_run(
            harness, read_id, ["read", "list", "search"], "g12-b")
        script = [
            batch_reply([
                ("call_read", "read", {"path": "tail"}),
                ("call_list", "list", {"path": "."}),
                ("call_search", "search", {"query": "x"}),
            ]),
            final_reply("g12-b-final"),
        ]
        harness.run(script, max_rounds=30)
        assert len(harness._transport.calls) == 2, len(harness._transport.calls)
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call'",
            (run_id,)) == 2
        assert harness.count(
            "v24.effects WHERE run_id=%s AND kind='model_call' "
            "AND request->>'cause'='continuation'", (run_id,)) == 1
        pins = run_pins(harness, run_id)
        assert pins["list"]["provider_install_id"] == \
            pins["search"]["provider_install_id"]
        assert len(tool_effects(harness, model_id)) == 3
    finally:
        harness.close()


def g12_c(fixture, base):
    portable = workspace(base / "c" / "portable", "portable")
    spec = read_spec(base / "c" / "read", portable.root,
                     realm=f"w4c-c-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "c" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        baseline = spawn_count(harness, install_id)
        run_id, model_id = start_run(harness, install_id, ["read"], "g12-c")
        with ZeroSpawn():
            harness.run([
                batch_reply([("call_1", "read",
                              {"path": "tail", "offset": 0})]),
                final_reply("after-invalid"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "invalid_tool_arguments", result
        assert spawn_count(harness, install_id) == baseline
    finally:
        harness.close()


def g12_d(fixture, base):
    for scenario in ("bad_value", "bad_relation"):
        harness, install_id, _run_id, _model_id, effect, _spec = run_stub(
            fixture, base / "d" / scenario, scenario,
            {"path": "a.txt", "scenario": scenario})
        try:
            assert effect["outcome"]["class"] == "failure", effect
            result = effect["outcome"]["body"]["result"]
            assert result["output"]["error"]["code"] == "invalid_tool_output", result
            assert spawn_count(harness, install_id) == 2
        finally:
            harness.close()

    portable = workspace(base / "d" / "render", "portable")
    spec = read_spec(base / "d" / "render-read", portable.root,
                     realm=f"w4c-d-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "d" / "render-harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        _run_id, model_id = start_run(harness, install_id, ["read"], "g12-d")
        with patch.object(RENDERERS, "render",
                          side_effect=RendererError("render_failed")):
            harness.run([
                batch_reply([("call_1", "read", {"path": "tail"})]),
                final_reply("after-render"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "render_failed", result
        assert spawn_count(harness, install_id) == 2
    finally:
        harness.close()


def g12_e(fixture, base):
    harness, install_id, run_id, _model_id, effect, _spec = run_stub(
        fixture, base / "e", "timeout", {"path": "a.txt", "scenario": "timeout"},
        timeout_ms=300)
    try:
        assert effect["outcome"]["class"] == "unknown", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "timeout", result
        assert harness.run_row(run_id)["status"] == "blocked_unknown"
        assert spawn_count(harness, install_id) == 2
        assert len(harness._transport.calls) == 1
    finally:
        harness.close()


def tamper_case(fixture, base, kind):
    portable = workspace(base / "portable", "portable")
    spec = read_spec(base / "read", portable.root,
                     realm=f"w4c-f-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "harness", realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        baseline = spawn_count(harness, install_id)
        _run_id, model_id = start_run(harness, install_id, ["read"], kind)
        if kind == "artifact":
            broken = dataclasses.replace(spec.entry, artifact_digest="0" * 64)
            expected = "adapter_not_approved"
        elif kind == "adapter":
            broken = dataclasses.replace(spec.entry, adapter_digest="0" * 64)
            expected = "adapter_not_approved"
        else:
            changed = json.loads(json.dumps(spec.entry.tools[0].descriptor))
            changed["tool"]["description"] = "tampered descriptor"
            broken = dataclasses.replace(
                spec.entry, tools=(ApprovedTool.from_descriptor(
                    changed, key="read"),))
            expected = "descriptor_mismatch"
        harness.dispatcher.registry = ApprovedAdapterRegistry((broken,))
        with ZeroSpawn():
            harness.run([
                batch_reply([("call_1", "read", {"path": "tail"})]),
                final_reply("after-tamper"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        output = result["output"]
        code = (output.get("error") or {}).get("code") or output.get("code")
        assert code == expected, result
        assert spawn_count(harness, install_id) == baseline
    finally:
        harness.close()


def g12_f(fixture, base):
    for kind in ("artifact", "adapter", "descriptor"):
        tamper_case(fixture, base / "f" / kind, kind)


def g12_g(fixture, base):
    portable = workspace(base / "g" / "portable", "portable")
    spec = read_spec(base / "g" / "read", portable.root,
                     realm=f"w4c-g-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "g" / "harness",
                           realm=spec.realm)
    called = []
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "read")
        _run_id, model_id = start_run(harness, install_id, ["read"], "g12-g")
        original_execute_tool = harness.worker._execute_tool

        def crash_after_tool(*args, **kwargs):
            harness.worker.crash_after = "finished"
            return original_execute_tool(*args, **kwargs)

        harness.worker._execute_tool = crash_after_tool
        try:
            harness.run([
                batch_reply([("call_1", "read", {"path": "tail"})]),
                final_reply("after-crash"),
            ], max_rounds=20)
        except HostCrash:
            pass
        else:
            raise AssertionError("crash_after=finished did not raise")
        harness.worker.crash_after = None
        effects = tool_effects(harness, model_id)
        assert len(effects) == 1, effects
        effect = effects[0]
        record = next(item for item in harness.journal.records
                      if item["event_type"] == "dispatch_finished"
                      and item["effect_id"] == effect["effect_id"])
        original_content = record["payload"]["tool_message"]["content"]
        original_types = {item["event_type"] for item in harness.journal.records}
        original_spawn = spawn_count(harness, install_id)
        tool = spec.entry.tools[0]
        original_render = tool.render
        object.__setattr__(
            tool, "render",
            RendererRef(original_render.id, original_render.version, "0" * 64))
        assert tool.render.digest != original_render.digest
        original_settlements = len([
            item for item in harness.journal.records
            if item["event_type"] == "settlement_committed"
            and item["effect_id"] == effect["effect_id"]])
        harness.journal.close()
        journal = HostJournal.open(harness.workdir / "plugin-journal.jsonl")

        def raising(effect):
            called.append(effect["effect_id"])
            raise AssertionError("replay called the tool handler")

        worker = HostWorker(harness.db, journal, tool_handler=raising,
                            resource_handler=harness.dispatcher.resource_handler)
        harness.journal = journal
        harness.worker = worker
        settled = worker._reconcile(harness.scope)
        assert settled >= 1, settled
        assert called == [], called
        after = harness.effect_row(effect["effect_id"])
        assert after["status"] == "succeeded", after
        settlement = journal.last("settlement_committed", effect["effect_id"])
        assert settlement is not None
        assert settlement["payload"].get("reconciled") is True, settlement
        after_record = next(item for item in journal.records
                            if item["event_type"] == "dispatch_finished"
                            and item["effect_id"] == effect["effect_id"])
        assert after_record["payload"]["tool_message"]["content"] == \
            original_content
        assert spawn_count(harness, install_id) == original_spawn
        assert {item["event_type"] for item in journal.records} == original_types
        settlements = len([
            item for item in journal.records
            if item["event_type"] == "settlement_committed"
            and item["effect_id"] == effect["effect_id"]])
        assert settlements == original_settlements + 1, (
            original_settlements, settlements)
        return {
            "replay_source": "journal tool_message",
            "rerender": False,
            "second_spawn": False,
            "journal_event_types_unchanged": True,
            "model_text_source": "journal",
        }
    finally:
        harness.close()


def g12_h(fixture, base):
    listing = workspace(base / "h" / "list", "list")
    spec = node_spec(base / "h" / "node", listing.root,
                     realm=f"w4c-h-{uuid.uuid4().hex[:8]}")
    harness = open_harness(fixture, [spec], base / "h" / "harness",
                           realm=spec.realm)
    try:
        install_id = harness.admit(spec)
        harness.prepare([install_id])
        harness.activate(install_id, "search")
        harness.worker.default_lease_ms = 19999
        baseline = spawn_count(harness, install_id)
        _run_id, model_id = start_run(harness, install_id, ["search"], "g12-h")
        with ZeroSpawn():
            harness.run([
                batch_reply([("call_1", "search", {"query": "x"})]),
                final_reply("after-lease"),
            ], max_rounds=20)
        effect = tool_effects(harness, model_id)[0]
        assert effect["outcome"]["class"] == "failure", effect
        result = effect["outcome"]["body"]["result"]
        assert result["output"]["error"]["code"] == "lease_insufficient", result
        assert spawn_count(harness, install_id) == baseline
    finally:
        harness.close()


def g12_l(fixture, base):
    requests = json.loads((B0 / "provider_requests_v1.json").read_text(
        encoding="utf-8"))["cases"]
    messages = json.loads((B0 / "tool_messages_v1.json").read_text(
        encoding="utf-8"))["cases"]
    request_by_id = {case["id"]: case for case in requests}
    message_by_id = {case["id"]: case for case in messages}
    for label, args in (("success", {"text": "snow 雪", "zero": 0}),
                        ("known_error", {"__tool_error__": True})):
        realm = f"w4c-l-{label}-{uuid.uuid4().hex[:8]}"
        spec = build_spec("python", realm=realm, tool_key="echo.python",
                          identity=f"v24.w4c.legacy.{label}")
        harness_dir = base / "l" / label / "harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(harness_dir, 0o700)
        harness = PluginHarness(fixture, build_registry(spec),
                                harness_dir, realm=realm)
        try:
            install_id = harness.admit(spec)
            harness.prepare([install_id])
            harness.activate(install_id, spec.tool_key)
            run_id, _model_id = start_run(
                harness, install_id, [spec.tool_key], "B0 fixed echo")
            call_id = f"call_b0_{label}"
            script = [
                tool_reply(call_id, spec.tool_key, args,
                           reasoning="B0 fixed", usage=(17, 9),
                           response_id=f"resp_b0_{label}"),
                final_reply("B0 final", reasoning="B0 done", usage=(22, 3),
                            response_id=f"final_b0_{label}"),
            ]
            harness.run(script, max_rounds=30)
            assert len(harness._transport.calls) == 2
            for index, case_id in enumerate(
                    (f"provider.{label}.request1",
                     f"provider.{label}.request2")):
                expected = bytes.fromhex(request_by_id[case_id]["expected_hex"])
                assert harness._transport.calls[index]["body"] == expected, (
                    label, index)
            record = next(item for item in harness.journal.records
                          if item["event_type"] == "dispatch_finished"
                          and item["payload"].get("kind") == "tool_call")
            content = record["payload"]["tool_message"]["content"]
            expected_message = bytes.fromhex(
                message_by_id[f"tool_message.{label}.content"]["expected_hex"])
            assert content.encode("utf-8") == expected_message, (label, content)
        finally:
            harness.close()


def replay_vector_probe():
    document = json.loads((HERE / "vectors" / "results_v2.json").read_text(
        encoding="utf-8"))
    by_id = {case["id"]: case for case in document["cases"]}
    expected = {
        "result.replay_no_rerender": "m4_pending",
        "lifecycle.journal_replay_no_rerender": "m4_pending",
        "lifecycle.tool_message_model_text_stable": "m4_pending",
    }
    for case_id, status in expected.items():
        assert by_id[case_id]["status"] == status, case_id
    return expected


def main() -> int:
    if node_path() is None:
        print("[SKIP] W4 lifecycle; node_missing")
        return 2
    with tempfile.TemporaryDirectory(prefix="w4c-life-") as temp:
        base = Path(temp)
        with server_helper_scope(), setup_db() as fixture:
            g12_a(fixture, base)
            g12_b(fixture, base)
            g12_c(fixture, base)
            g12_d(fixture, base)
            g12_e(fixture, base)
            g12_f(fixture, base)
            replay = g12_g(fixture, base)
            assert replay["replay_source"] == "journal tool_message"
            assert replay["rerender"] is False
            assert replay["second_spawn"] is False
            assert replay["journal_event_types_unchanged"] is True
            g12_h(fixture, base)
            g12_l(fixture, base)
        replay_vector_probe()
    print("[passed] W4 lifecycle; cases=14; python=ok node=ok; "
          "second_spawn=false; rerender=false; journal_events_unchanged=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
