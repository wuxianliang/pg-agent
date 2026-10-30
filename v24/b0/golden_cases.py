"""Inputs and live producers for the v1 ABI baseline (B0 only)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

B0 = Path(__file__).resolve().parent
ROOT = B0.parents[1]
S1 = ROOT / "v24" / "s1"
S11 = ROOT / "v24" / "s11"
for path in (str(S1), str(S11), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from setup_db import server_helper_scope, setup_db  # noqa: E402
from plugin_fixtures import final_reply, model_adapter, tool_reply, build_spec, descriptor_for  # noqa: E402
from v24.host import line_json  # noqa: E402
from v24.host.registry import pg_jsonb_text  # noqa: E402

FIXED_RESERVATION = "v24:host_prepare:b0-golden-reservation"
FRAME_ARGS = {
    "empty": "", "newline": "line1\nline2", "unicode": "雪🙂",
    "separator": "left\u2028right", "zero": 0,
    "nested": {"z": [1, {"a": True}], "a": None},
}
OPERATIONS = ("prepare", "invoke", "release", "inspect")


def _case(case_id, domain, producer, input_id, raw, *, text=True, semantic=None):
    data = bytes(raw)
    item = {"id": case_id, "domain": domain, "producer": producer,
            "input_id": input_id, "expected_hex": data.hex(),
            "expected_length": len(data),
            "expected_sha256": hashlib.sha256(data).hexdigest(),
            "expected_text": data.decode("utf-8") if text else None}
    if semantic is not None:
        item["semantic"] = semantic
    return item


def _pg_canonical(conn, value):
    with conn.cursor() as cur:
        cur.execute("SELECT v24.canonical_json(%s::jsonb)",
                    (json.dumps(value, ensure_ascii=False),))
        result = cur.fetchone()[0]
    conn.rollback()
    return result


def _descriptor_vectors(conn):
    out = []
    for language in ("python", "node"):
        descriptor = descriptor_for(f"echo.{language}")
        raw = pg_jsonb_text(descriptor).encode("utf-8")
        pg = _pg_canonical(conn, descriptor)
        out.append(_case(f"descriptor.echo.{language}", "descriptor_pg_jsonb",
                         "registry.pg_jsonb_text", f"echo.{language}", raw,
                         semantic={"descriptor": descriptor,
                                   "descriptor_digest": hashlib.sha256(raw).hexdigest(),
                                   "pg_oracle_text": pg}))
    v2 = {"v": 2, "tool": {"key": "read", "description": "Read UTF-8 text",
          "parameters": {"type": "object", "additionalProperties": False},
          "limits": {"timeout_ms": 5000}, "flags": [True, None, 0]}}
    for name, value in (("v1_echo", descriptor_for("echo.python")),
                        ("v2_contract", v2), ("empty_object", {})):
        raw = pg_jsonb_text(value).encode("utf-8")
        pg = _pg_canonical(conn, value)
        out.append(_case(f"descriptor.pg.{name}", "descriptor_pg_jsonb",
                         "registry.pg_jsonb_text", name, raw,
                         semantic={"descriptor": value,
                                   "descriptor_digest": hashlib.sha256(raw).hexdigest(),
                                   "pg_oracle_text": pg}))
    return out


def _frame_vectors():
    out = []
    for op in OPERATIONS:
        args = FRAME_ARGS if op == "invoke" else {}
        raw = line_json.build_frame(op, FIXED_RESERVATION, args)
        out.append(_case(f"frame.{op}", "line_json_v1_request",
                         "line_json.build_frame", f"operation={op};fixed-reservation",
                         raw, semantic={"operation": op, "args": args}))
    return out


def _stdout_vectors(include_node=True):
    out = []
    node = shutil.which("node")
    languages = ("python", "node") if include_node else ("python",)
    for language in languages:
        if language == "node" and not node:
            raise RuntimeError("node_unavailable")
        artifact = S11 / "plugins" / ("echo.py" if language == "python" else "echo.js")
        interpreter = sys.executable if language == "python" else node
        spec = build_spec(language, realm="b0-golden", artifact_path=artifact,
                          interpreter=interpreter)
        requests = [("prepare", "v24:host_prepare:b0-golden", {}),
                    ("invoke_success", "v24:tool_call:b0-golden", {"text": "snow 雪", "zero": 0}),
                    ("invoke_error", "v24:tool_call:b0-golden", {"__tool_error__": True}),
                    ("release", "v24:host_release:b0-golden", {}),
                    ("inspect", FIXED_RESERVATION, {})]
        for label, reservation, args in requests:
            operation = "invoke" if label.startswith("invoke") else label
            invocation = line_json.run(spec.entry, operation, reservation, args)
            expected_class = "failure" if label == "invoke_error" else "success"
            if invocation.class_name != expected_class:
                raise AssertionError(f"{language} {label} returned {invocation.class_name}/{invocation.reason}")
            out.append(_case(f"stdout.{language}.{label}", "plugin_v1_stdout",
                             f"{language} echo subprocess Invocation.stdout",
                             f"{label};{reservation}", invocation.stdout,
                             semantic={"exit_class": invocation.class_name,
                                       "returncode": invocation.returncode,
                                       "result": invocation.result}))
    return out


def _provider_and_messages(db, workdir):
    from plugin_fixtures import PluginHarness, build_registry
    result = []
    for label, args in (("success", {"text": "snow 雪", "zero": 0}),
                        ("known_error", {"__tool_error__": True})):
        realm = f"b0-golden-{label}"
        spec = build_spec("python", realm=realm, tool_key="echo.python",
                          identity=f"v24.b0.golden.{label}")
        journal_dir = workdir / label
        journal_dir.mkdir(mode=0o700)
        harness = PluginHarness(db, build_registry(spec), journal_dir, realm=realm)
        try:
            install_id = harness.admit(spec)
            harness.prepare([install_id])
            harness.activate(install_id, spec.tool_key)
            fiber = harness.fiber(install_id)
            start = harness.start(fiber["fiber_id"], [spec.tool_key],
                                  [{"role": "user", "content": "B0 fixed echo"}],
                                  key=f"b0-golden-start-{label}")
            run_id = start["emitted"][0]
            script = [tool_reply(f"call_b0_{label}", spec.tool_key, args,
                                 reasoning="B0 fixed", usage=(17, 9),
                                 response_id=f"resp_b0_{label}"),
                      final_reply("B0 final", reasoning="B0 done", usage=(22, 3),
                                  response_id=f"final_b0_{label}")]
            adapter, transport = model_adapter(script)
            harness.worker.adapter = adapter
            lease_observations = []
            original_lease_for = harness.worker._lease_for
            def observe_lease(item):
                lease_ms = original_lease_for(item)
                if item.get("kind") == "tool_call":
                    lease_observations.append(lease_ms)
                return lease_ms
            with patch.object(harness.worker, "_lease_for", side_effect=observe_lease):
                harness.worker.run_until_idle(harness.scope, max_rounds=30)
            if len(lease_observations) != 1:
                raise AssertionError(f"{label} expected one actual tool claim lease, got {lease_observations}")
            if len(transport.calls) != 2:
                raise AssertionError(f"{label} expected initial+continuation provider requests, got {len(transport.calls)}")
            for index, call in enumerate(transport.calls):
                result.append(_case(f"provider.{label}.request{index + 1}", "provider_request",
                                    "DeepSeekAdapter.send -> ScriptedTransport.post body",
                                    f"{label};request={index + 1};fixed-script", call["body"],
                                    semantic={"request_index": index + 1,
                                              "expected_tool_call_id": f"call_b0_{label}"}))
            records = [r for r in harness.journal.records_for_run(str(run_id))
                       if r["event_type"] == "dispatch_finished"]
            tool_record = next(r for r in records
                               if r.get("payload", {}).get("kind") == "tool_call")
            message = tool_record["payload"]["tool_message"]
            started = next(r for r in harness.journal.records_for_run(str(run_id))
                           if r["event_type"] == "dispatch_started"
                           and r["effect_id"] == tool_record["effect_id"])
            journal_event_types = sorted({r["event_type"]
                                          for r in harness.journal.records})
            dispatch_keys = {
                "dispatch_started": sorted(started["payload"]),
                "dispatch_finished": sorted(tool_record["payload"]),
            }
            tool_lease_ms = lease_observations[0]
            content = message["content"].encode("utf-8")
            result.append(_case(f"tool_message.{label}.content", "tool_message",
                                "dispatch_finished.payload.tool_message.content UTF-8",
                                f"worker-journal;{label};fixed-tool-call-id", content,
                                semantic={"message": message,
                                          "message_shape": sorted(message),
                                          "dispatch_payload_keys": dispatch_keys,
                                          "journal_event_types": journal_event_types,
                                          "tool_lease_ms": tool_lease_ms}))
        finally:
            harness.close()
    return result


def _parser_vectors():
    samples = {
        "eof": b"", "bad_json": b"{bad}\n",
        "non_object_result": b'{"ok":true,"result":"[]"}\n',
        "missing_lf": b'{"ok":true,"result":"{}"}',
        "crlf": b'{"ok":true,"result":"{}"}\r\n',
        "extra_frame": b'{"ok":true,"result":"{}"}\n{}\n',
        "non_utf8": b"\xff\xfe\x00",
        "u2028": '{"ok":true,"result":"{}"}\u2028{}'.encode("utf-8"),
        "u2029": '{"ok":true,"result":"{}"}\u2029{}'.encode("utf-8"),
    }
    out = []
    for name, raw in samples.items():
        try:
            frame = line_json._frames(raw)
            classification = "accepted" if line_json._success_frame(frame) is not None else "bad_frame"
        except ValueError as exc:
            classification = str(exc)
        out.append(_case(f"parser.{name}", "line_json_v1_parser", "line_json._frames",
                         name, raw, text=False,
                         semantic={"classification": classification}))
    return out


def _structure_vectors(message_cases):
    from v24.host.journal import EVENT_TYPES
    message_shape = sorted(message_cases[0]["semantic"]["message_shape"])
    dispatch_payload_keys = message_cases[0]["semantic"]["dispatch_payload_keys"]
    journal_event_types = message_cases[0]["semantic"]["journal_event_types"]
    tool_lease_ms = message_cases[0]["semantic"]["tool_lease_ms"]
    if any(case["semantic"]["message_shape"] != message_shape
           or case["semantic"]["dispatch_payload_keys"] != dispatch_payload_keys
           or case["semantic"]["journal_event_types"] != journal_event_types
           or case["semantic"]["tool_lease_ms"] != tool_lease_ms
           for case in message_cases[1:]):
        raise AssertionError("success/error journal structural vectors differ")
    return [{"id": "structure.journal_event_set", "kind": "structural",
             "expected": {"observed": journal_event_types,
                          "declared": sorted(EVENT_TYPES)}},
            {"id": "structure.tool_message_keys", "kind": "structural",
             "expected": message_shape},
            {"id": "structure.dispatch_payload_keys", "kind": "structural",
             "expected": dispatch_payload_keys},
            {"id": "structure.tool_lease_ms", "kind": "structural",
             "expected": {"observed_tool_effect_ms": tool_lease_ms,
                          "worker_default_ms": harness_default_tool_lease}},
            {"id": "structure.transport_limits", "kind": "structural",
             "expected": {"stdout": line_json.STDOUT_LIMIT,
                          "stderr": line_json.STDERR_LIMIT}},
            {"id": "structure.descriptor_v2_rejected", "kind": "structural",
             "expected": "descriptor_invalid"}]


def harness_default_tool_lease():
    import inspect
    from v24.host.worker import HostWorker
    return inspect.signature(HostWorker).parameters["default_lease_ms"].default


def capture_all(db, workdir, *, include_node=True):
    conn = db.connect("owner")
    try:
        descriptors = _descriptor_vectors(conn)
    finally:
        conn.close()
    provider = _provider_and_messages(db, workdir)
    provider_cases = [case for case in provider if case["domain"] == "provider_request"]
    message_cases = [case for case in provider if case["domain"] == "tool_message"]
    return {
        "descriptor_v1.json": descriptors,
        "frames_v1.json": _frame_vectors() + _stdout_vectors(include_node=include_node) + _parser_vectors(),
        "provider_requests_v1.json": provider_cases,
        "tool_messages_v1.json": message_cases + _structure_vectors(message_cases),
    }


def verify_descriptor_pg_vectors(db):
    conn = db.connect("owner")
    try:
        for case in _descriptor_vectors(conn):
            expected = case["semantic"]["pg_oracle_text"]
            actual = _pg_canonical(conn, case["semantic"]["descriptor"])
            if actual != expected or actual.encode("utf-8").hex() != case["expected_hex"]:
                raise AssertionError(f"PostgreSQL canonical mismatch: {case['id']}")
    finally:
        conn.close()
