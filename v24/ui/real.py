"""Shared DeepSeek startup and opt-in manual CLI; no Chainlit/fake dependency.

Manual commands use --real-provider-smoke with scenarios short, write10,
exec11, skill, or probe. Each invocation owns a fresh private DB/workspace.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import re
import time
import json
import logging
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from psycopg2.extensions import parse_dsn
from v24.host.deepseek import FRAMING_MARGIN
from v24.ui import catalog
from v24.ui.provider import create_real_adapter


@contextmanager
def _isolated_helper_environment():
    """Keep credentials and ambient libpq overrides out of helper children."""
    old = dict(os.environ)
    try:
        for name in list(os.environ):
            if name.startswith(("PG", "DEEPSEEK_", "OPENAI_")):
                os.environ.pop(name, None)
        os.environ["UV_NO_ENV_FILE"] = "1"
        os.environ["UV_NO_SYNC"] = "1"
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def _private_db_helper(pgdata: Path) -> None:
    """Child-only entry: explicit private path or fail before server startup.

    Unlike sitecustomize, exceptions here terminate the child. No repository
    server.get_server() or default-PGDATA path is ever called.
    """
    if (not pgdata.is_absolute() or pgdata.resolve() != pgdata
            or pgdata.name != "pgdata" or pgdata.exists()
            or stat.S_IMODE(pgdata.parent.stat().st_mode) != 0o700):
        raise RuntimeError("private_pgdata_invalid")
    import pgembed
    server = None
    try:
        server = pgembed.get_server(pgdata, cleanup_mode="stop")
        info = server.get_postmaster_info()
        if (Path(info.pgdata).resolve() != pgdata or info.socket_dir is None
                or info.port is None):
            raise RuntimeError("private_pgdata_mismatch")
        print(json.dumps({"uri": server.get_uri("postgres"),
                          "socket": str(info.socket_dir), "port": info.port,
                          "pgdata": str(pgdata)}), flush=True)
        sys.stdin.read()
    finally:
        if server is not None:
            server.cleanup()


@contextmanager
def _private_fixture_server(evidence: Path):
    """Attest a new explicit helper before allowing the S1 fixture to run."""
    from v24.s1 import setup_db as fixtures
    if fixtures._setup_process is not None or fixtures._setup_endpoint is not None:
        raise RuntimeError("private_helper_conflict")
    pgdata = evidence / "pgdata"
    if (evidence.resolve() != evidence or not evidence.is_dir()
            or stat.S_IMODE(evidence.stat().st_mode) != 0o700 or pgdata.exists()):
        raise RuntimeError("private_pgdata_invalid")
    # -I ignores PYTHONPATH/sitecustomize supplied through the environment.
    # Imports and explicit PGDATA binding are part of the main program: any
    # failure exits; there is no interpreter startup fallback to server.py.
    command = [sys.executable, "-I", "-c",
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "from v24.ui.real import _private_db_helper; _private_db_helper(Path(sys.argv[2]))",
        str(Path(__file__).resolve().parents[2]), str(pgdata)]
    with _isolated_helper_environment(), fixtures.server_helper_scope():
        fixtures._setup_process = subprocess.Popen(
            command, cwd=evidence, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True)
        endpoint = fixtures._read_helper_endpoint(fixtures._setup_process)
        if endpoint.get("pgdata") != str(pgdata):
            raise RuntimeError("private_pgdata_mismatch")
        fixtures._setup_endpoint = endpoint
        # Also retain S1's active Unix endpoint attestation. setup_db cannot
        # reach its default launcher while this live helper is registered.
        fixtures._server_and_base_dsn()
        yield


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _private_json(path: Path, value) -> None:
    data = _json_bytes(value) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def _source_hashes() -> dict:
    root = Path(__file__).resolve().parents[2]
    paths = [root / "v24/load.py", root / "v24/s1/setup_db.py"]
    for folder, pattern in (("host", "*.py"), ("ui", "*.py"), ("ui/plugins", "*.py"),
                            ("ui/skills", "*/SKILL.md"), ("sql", "*.sql")):
        paths.extend((root / "v24" / folder).glob(pattern))
    return {str(p.relative_to(root)): _digest(p.read_bytes()) for p in sorted(set(paths)) if p.is_file()}


EXEC11_COMMAND = 'test "$(cat result.txt)" = WI2_EXEC_MARKER'
EXEC11_PROMPT = (
    "Read the full v24 surgical-edit skill at .v24/skills/surgical-edit/SKILL.md. "
    "Then use write to create result.txt containing exactly WI2_EXEC_MARKER. "
    "Then call bash with command set verbatim to exactly: " + EXEC11_COMMAND +
    " — character for character, with no echo, no chaining, no pipes, and no quoting changes. "
    "Read result.txt back and give a short final answer."
)


def _probe_content(target: int, family: str) -> str:
    """Exact complete write args bytes, including keys/path/append and escaping.

    The escape family is generated newline-terminated lines: it covers JSON
    ``\\n`` escaping only. Quotes, backslashes and tabs are deliberately absent
    because exact-copy failures there measure model JSON fidelity, not capacity.
    """
    def size(value):
        return len(_json_bytes({"path": "result.txt", "content": value, "append": False}))
    overhead = size("")
    if not overhead <= target <= 4096:
        raise ValueError("probe_size_invalid")
    if family == "escape":
        chunks, index, used = [], 0, overhead
        while True:
            chunk = f"E{index:04d}\n"
            cost = size(chunk) - overhead
            if used + cost > target:
                break
            chunks.append(chunk)
            used += cost
            index += 1
        content = "".join(chunks) + "a" * (target - used)
    else:
        unit = {"ascii": "Abc123", "cjk": "中文"}[family]
        cost = size(unit) - overhead
        content = unit * ((target - overhead) // cost)
        content += "a" * (target - size(content))
    assert size(content) == target
    return content


def _enum(value, allowed):
    return value if value in allowed else (None if value is None else "unrecognized")


class _ObservedTransport:
    """Forward unchanged bytes to the actual transport; expose only safe metrics."""
    def __init__(self, delegate):
        self.delegate, self.runtime, self.rows = delegate, None, []

    def post(self, url, body, headers, deadline):
        self.runtime.db.assert_all_idle()
        row = {"sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "request_wire_bytes": len(body), "request_sha256": _digest(body),
               "connections_idle": True}
        self.rows.append(row)
        started = time.monotonic()
        try:
            status, raw = self.delegate.post(url, body, headers, deadline)
            row.update(http_status=status, response_bytes=len(raw), response_sha256=_digest(raw))
            return status, raw
        finally:
            row["elapsed_ms"] = int((time.monotonic() - started) * 1000)


def _effects(rt, run_id):
    page = rt.db.host_run_effects(run_id, None, None, 64)
    if page.get("has_more"):
        raise RuntimeError("evidence_page_incomplete")
    return [rt.db.host_effect(row["effect_id"])["effect"] for row in page.get("items", [])]


def _drive_measurement(rt, scope, run_id, scenario, expected, observer):
    """One-effect rounds. Never send a probe continuation or retry unknown work."""
    from v24.ui.control import DriveReport
    reason = None
    for round_no in range(1, 65):
        run = rt.run_state(run_id).get("run") or {}
        status = run.get("status")
        effects = _effects(rt, run_id)
        if status in ("completed", "failed", "cancelled", "blocked_unknown", "waiting"):
            break
        rejected = [e for e in effects if e["kind"] == "tool_call" and e["status"] == "failed"]
        if rejected:
            reason = "tool_failure"
            rt.cancel(run_id, "measurement-tool-failure-" + uuid4().hex)
            run = rt.run_state(run_id).get("run") or {}
            status = run.get("status")
            break
        if scenario == "probe":
            models = [e for e in effects if e["kind"] == "model_call" and e["status"] == "succeeded"]
            tools = [e for e in effects if e["kind"] == "tool_call"]
            if models:
                valid = len(tools) == 1 and tools[0].get("request", {}).get("key") == "write" and tools[0]["request"].get("args") == expected
                if not valid:
                    reason = "target_missed"
                elif tools[0]["status"] in ("succeeded", "failed", "cancelled", "unknown"):
                    reason = "measurement_complete" if tools[0]["status"] == "succeeded" else "tool_failure"
                if reason:
                    rt.cancel(run_id, "measurement-cancel-" + uuid4().hex)
                    # Do not drive again: cancel settles pending continuations locally.
                    run = rt.run_state(run_id).get("run") or {}
                    status = run.get("status")
                    break
        if len(observer.rows) >= (1 if scenario == "probe" else 8) and any(
                e["kind"] == "model_call" and e["status"] == "ready" for e in effects):
            reason = "measurement_call_limit"
            rt.cancel(run_id, "measurement-limit-" + uuid4().hex)
            run = rt.run_state(run_id).get("run") or {}
            status = run.get("status")
            break
        stats = rt.worker.run_once(scope)
        if stats.progress == 0:
            reason, status = "stalled", "stalled"
            break
    else:
        reason, status = "measurement_round_limit", "stalled"
    rt.db.assert_all_idle()
    return DriveReport(round_no, status, False, status == "stalled", status == "cancelled", status == "waiting",
                       int(run.get("revision", 0)), (run.get("result") or {}).get("final_text")), reason


def _safe_receipt(args, limits, rt, run_id, report, reason, expected, records, observer, before, secrets=()):
    """Allowlisted projection of the retained private journal and durable readers."""
    from v24.host.deepseek import MODEL
    events = [r for r in records if r.get("run_id") == run_id]
    effects = _effects(rt, run_id)
    starts = {str(r["effect_id"]): r["payload"] for r in events if r["event_type"] == "dispatch_started"}
    finishes = {str(r["effect_id"]): r["payload"] for r in events if r["event_type"] == "dispatch_finished"}
    prepared_events = {str(r["effect_id"]): r["payload"] for r in events if r["event_type"] == "effect_prepared"}
    pins_page = rt.db.host_run_pins(run_id, None, 64)
    if pins_page.get("has_more"):
        raise RuntimeError("evidence_page_incomplete")
    pins = pins_page.get("items", [])
    models, tools = [], []
    for effect in effects:
        ident = str(effect["effect_id"])
        request, start, finish = effect.get("request", {}), starts.get(ident, {}), finishes.get(ident, {})
        if effect["kind"] == "model_call":
            prepared = start.get("prepared") or {}
            body, mapping = prepared.get("body") or {}, finish.get("mapping") or {}
            reply = mapping.get("reply") or {}
            args_rows = []
            for call in mapping.get("tool_calls") or []:
                canonical = _json_bytes(call["args"])
                raw = call["arguments"].encode("utf-8")
                args_rows.append({"key": call["key"], "actual_complete_args_bytes": len(canonical),
                    "actual_complete_args_sha256": _digest(canonical), "provider_arguments_bytes": len(raw),
                    "provider_arguments_sha256": _digest(raw), "target_equal": call["args"] == expected if expected else None})
            local_reason = prepared_events.get(ident, {}).get("local_failure")
            provider_keys = sorted((prepared.get("tool_map") or {}).get("by_key", {}))
            models.append({"effect_id": ident, "durable_status": effect["status"], "cause": request.get("cause"),
                "canonical_body_bytes": prepared.get("estimate", FRAMING_MARGIN) - FRAMING_MARGIN if prepared else None,
                "wire_body_bytes": len(_json_bytes(body)) if body else None,
                "canonical_body_sha256": _digest(_json_bytes({k:v for k,v in body.items() if k != "max_tokens"})) if body else None,
                "sql_reserve_tokens": request.get("reserve", {}).get("tokens"), "estimate": prepared.get("estimate"),
                "requested_max_tokens": (request.get("input") or {}).get("max_output_tokens"),
                "actual_max_tokens": body.get("max_tokens"), "prompt_tokens": reply.get("prompt_tokens"),
                "completion_tokens": reply.get("completion_tokens"), "finish_reason": _enum(reply.get("finish_kind"),
                    ("stop", "tool_calls", "length", "content_filter", "aborted", "insufficient_system_resource", "other", "unknown", None)),
                "interpret_class": mapping.get("class"), "interpret_reason": _reason(mapping.get("reason") or local_reason),
                "tool_args": args_rows, "provider_tool_keys": provider_keys,
                "provider_tools_sha256": _digest(_json_bytes(body.get("tools", []))) if body else None,
                "dispatch_count": sum(r["event_type"] == "dispatch_started" and str(r["effect_id"]) == ident for r in events),
                "assistant_message_absent": mapping.get("assistant_message") is None,
                "complete_args_available": bool(mapping.get("tool_calls")),
                "http_status": finish.get("http_status"), "wall_ms": finish.get("wall_ms")})
        elif effect["kind"] == "tool_call":
            result = ((effect.get("outcome") or {}).get("body") or {}).get("result") or {}
            output = result.get("output") or {}
            value = output.get("value") or {}
            text = value.get("text") if isinstance(value, dict) else None
            tools.append({"effect_id": ident, "key": request.get("key"), "durable_status": effect["status"],
                "args_bytes": len(_json_bytes(request.get("args"))), "args_sha256": _digest(_json_bytes(request.get("args"))),
                "output_sha256": _digest(_json_bytes(output)), "output_text_bytes": len(text.encode("utf-8")) if isinstance(text, str) else None,
                "output_text_sha256": _digest(text.encode("utf-8")) if isinstance(text, str) else None,
                "truncated": value.get("truncated") if isinstance(value, dict) else None,
                "exit_code": value.get("exit_code") if isinstance(value, dict) else None,
                "error_code": _reason(value.get("code") or output.get("code")) if isinstance(value, dict) else None,
                "dispatch_count": sum(r["event_type"] == "dispatch_started" and str(r["effect_id"]) == ident for r in events)})
    state = rt.run_state(run_id).get("run") or {}
    file = rt.env.workspace_root / "result.txt"
    file_bytes = file.read_bytes() if file.is_file() and not file.is_symlink() else None
    expected_text = expected.get("content") if expected else None
    skill = "surgical-edit" if args.scenario in ("write10", "exec11") else "repo-recon"
    skill_bytes = (rt.env.skills_root / skill / "SKILL.md").read_bytes()
    skill_reads = [e for e in effects if e["kind"] == "tool_call" and e.get("request", {}).get("key") in ("read", "read_file")
                   and e["request"].get("args", {}).get("path") == f".v24/skills/{skill}/SKILL.md"]
    skill_complete = []
    for effect in skill_reads:
        tool = next(t for t in tools if t["effect_id"] == str(effect["effect_id"]))
        if tool["durable_status"] == "succeeded" and tool["truncated"] is False and tool["output_text_sha256"] == _digest(skill_bytes):
            skill_complete.append(str(effect["effect_id"]))
    def event_index(kind, ident, default):
        return next((i for i, r in enumerate(events)
                     if r["event_type"] == kind and str(r["effect_id"]) == ident), default)

    write_effects = [e for e in effects if e["kind"] == "tool_call" and e.get("request", {}).get("key") == "write"]
    first_write = min((event_index("dispatch_started", str(e["effect_id"]), -1)
                       for e in write_effects), default=-1)
    skill_before_write = first_write >= 0 and any(
        event_index("dispatch_finished", ident, len(events)) < first_write for ident in skill_complete)
    # Prove the exact full tool message reached each model which produced a
    # write. Missing parent IDs cannot establish that relationship.
    parents = [str(e["parent_effect_id"]) for e in write_effects if e.get("parent_effect_id")]
    def continued_to(model_id):
        messages = (starts.get(model_id, {}).get("prepared") or {}).get("body", {}).get("messages", [])
        model_start = event_index("dispatch_started", model_id, -1)
        return any(finishes.get(ident, {}).get("tool_message") is not None
                   and finishes[ident]["tool_message"] in messages
                   and event_index("dispatch_finished", ident, len(events)) < model_start
                   for ident in skill_complete)

    skill_continued = (len(parents) == len(write_effects) and all(continued_to(parent) for parent in parents)
                       if write_effects else any(continued_to(model_id) for model_id in starts))
    writes = [t for t in tools if t["key"] == "write"]
    write_once = len(writes) == 1 and writes[0]["durable_status"] == "succeeded" and writes[0]["dispatch_count"] == 1
    write_finish = event_index("dispatch_finished", writes[0]["effect_id"], len(events)) if write_once else len(events)
    successful_bash = next((t for t in tools if t["key"] == "bash"
                            and t["durable_status"] == "succeeded" and t["dispatch_count"] == 1
                            and t["exit_code"] == 0
                            and event_index("dispatch_finished", t["effect_id"], len(events)) < len(events)), None)
    bash_finish = event_index("dispatch_finished", successful_bash["effect_id"], len(events)) if successful_bash else len(events)
    # One successful read must prove the final bytes AND all required ordering.
    # A matching early read and a different late read cannot combine into proof.
    readback = any(
        e["kind"] == "tool_call" and e.get("request", {}).get("key") in ("read", "read_file")
        and e["request"].get("args", {}).get("path") == "result.txt"
        and e["status"] == "succeeded" and file_bytes is not None
        and next((t["output_text_sha256"] for t in tools if t["effect_id"] == str(e["effect_id"])), None) == _digest(file_bytes)
        and write_finish < event_index("dispatch_finished", str(e["effect_id"]), -1)
        and (args.scenario != "exec11" or bash_finish < event_index("dispatch_finished", str(e["effect_id"]), -1))
        for e in effects)
    expected_count = 7 if args.scenario == "short" else (10 if args.scenario in ("write10", "probe") else 11)
    pin_keys = sorted(p.get("key") for p in pins)
    pins_ok = len(pins) == expected_count and all(m["provider_tool_keys"] == pin_keys for m in models if m["actual_max_tokens"] is not None)
    checks = {"full_pins_and_provider_tools": pins_ok,
        "file_matches_expected": file_bytes == expected_text.encode("utf-8") if expected_text is not None else None,
        "write_executed_once": write_once, "readback_after_write": readback,
        "readback_after_bash": readback if args.scenario == "exec11" else None,
        "durable_readback": readback, "full_skill_read": bool(skill_complete), "skill_continuation": skill_continued,
        "skill_before_write": skill_before_write,
        "durable_final": report.status == "completed" and bool(report.final_text),
        "bash_executed": successful_bash is not None}
    passed = checks["durable_final"] and pins_ok
    if args.scenario in ("write10", "exec11"):
        passed = passed and checks["file_matches_expected"] and readback and bool(skill_complete) and skill_continued and skill_before_write
        if args.scenario == "exec11": passed = passed and checks["bash_executed"]
    if args.scenario == "skill": passed = passed and bool(skill_complete) and skill_continued
    if args.scenario == "probe": passed = reason == "measurement_complete" and report.status == "cancelled" and checks["file_matches_expected"] and write_once and len(observer.rows) == 1 and pins_ok
    length = any(m["interpret_reason"] == "finish_length" for m in models)
    length_contract = None
    if length:
        truncated_ids = {m["effect_id"] for m in models if m["interpret_reason"] == "finish_length"}
        length_contract = (report.status == "blocked_unknown" and not report.final_text
            and not any(str(e.get("parent_effect_id")) in truncated_ids for e in effects)
            and all(m["assistant_message_absent"] and not m["complete_args_available"] and m["durable_status"] == "unknown"
                    for m in models if m["effect_id"] in truncated_ids)
            and all(sum(r["event_type"] == "dispatch_started" and str(r["effect_id"]) == ident for r in events) == 1 for ident in truncated_ids))
        if args.scenario in ("short", "probe"):
            length_contract = length_contract and not tools and file_bytes is None
    after = _source_hashes()
    passed = bool(passed and before == after)
    result = {"schema": 1, "scenario": args.scenario, "profile": args.profile, "model": MODEL,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "status": report.status, "run_id": run_id,
        "measurement_reason": reason, "contract_passed": passed, "checks": checks, "finish_length_contract": length_contract,
        "final_text_present": bool(report.final_text), "final_text_sha256": _digest(report.final_text.encode("utf-8")) if report.final_text else None,
        "remaining_budget": {k:state.get(k) for k in ("remaining_tokens", "remaining_steps", "remaining_tool_calls", "remaining_wall_ms")},
        "pin_count": len(pins), "pin_keys": pin_keys, "pins_sha256": _digest(_json_bytes(pins)),
        "models": models, "tools": tools, "http": observer.rows, "http_count": len(observer.rows),
        "expected_args_sha256": _digest(_json_bytes(expected)) if expected else None,
        "actual_file_bytes": len(file_bytes) if file_bytes is not None else None,
        "actual_file_sha256": _digest(file_bytes) if file_bytes is not None else None,
        "skill_source_bytes": len(skill_bytes), "skill_source_sha256": _digest(skill_bytes),
        "limits": dataclasses.asdict(limits), "source_sha256": before, "source_unchanged": before == after,
        "connections_idle": rt.db.idle(rt.db.control) and rt.db.idle(rt.db.service)}
    if args.scenario == "probe":
        result.update(target_args_bytes=args.target_args_bytes, content_class=args.content_class)
    _assert_safe(result, secrets)
    return result


def _reason(value):
    allowed = {"body_too_large", "reserve_insufficient", "lease_insufficient", "finish_length", "finish_aborted",
        "finish_None", "finish_other", "finish_unknown", "finish_insufficient_system_resource", "transport", "http_status",
        "invalid_tool_arguments", "unknown_tool_name", "tool_call_invalid", "history_missing_reasoning", "content_filter",
        "zero_tool_calls", "too_many_tool_calls", "duplicate_tool_call_id", "invalid_arguments", "tool_executor_error",
        "semantic_violation", "schema_invalid", "output_invalid", "history_invalid", "request_invalid", "measurement_guard_rejected"}
    return value if value in allowed or value is None or re.fullmatch(r"http_[0-9]{3}", str(value)) else "unrecognized"


def _assert_safe(value, secrets=()):
    data = _json_bytes(value)
    for key in secrets:
        if key and key.encode("utf-8") in data:
            raise RuntimeError("receipt_privacy_failed")
    for marker in (b"Authorization", b"Bearer ", b"postgres://", b"postgresql://", b'"content":', b'"reasoning_content":', b'"resume_token":'):
        if marker in data:
            raise RuntimeError("receipt_privacy_failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-provider-smoke", action="store_true")
    parser.add_argument("--scenario", choices=("short", "write10", "exec11", "skill", "probe"), default="short")
    parser.add_argument("--profile", choices=("legacy", "current"), default="legacy")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--target-args-bytes", type=int)
    parser.add_argument("--content-class", choices=("ascii", "cjk", "escape"), default="ascii")
    args = parser.parse_args(argv)
    if not args.real_provider_smoke:
        print("not_requested")
        return 0
    if args.scenario == "probe" and (args.target_args_bytes is None or not 64 <= args.target_args_bytes <= 4096):
        print("probe_size_invalid")
        return 1
    limits = catalog.LEGACY_UI_LIMITS if args.profile == "legacy" else catalog.REAL_UI_LIMITS
    try:
        adapter = create_real_adapter(limits)
    except RuntimeError as exc:
        reason = str(exc)
        print(reason)
        return 2 if reason == "credentials_absent" else 1
    return _run_live(args, adapter, limits)


def _run_live(args, adapter, limits) -> int:
    """Run one bounded real request and retain its private journal.

    A fresh child directory prevents reusing a journal or workspace. The helper
    process gets a private pgdata and never inherits provider keys or libpq
    overrides. Persistent UI environment verbs are not used.
    """
    from v24.s1.setup_db import setup_db
    from v24.ui.control import AgentRuntime
    from v24.ui.env import UiEnv

    logging.getLogger("pgembed").setLevel(logging.WARNING)
    evidence = None
    status, code = "entry_failed", 1
    before = _source_hashes()
    secrets = tuple(os.environ.get(name, "") for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"))
    observer = _ObservedTransport(adapter.transport)
    adapter.transport = observer
    build_rows = []
    original_build = adapter.build
    def observed_build(effect, history, pins):
        from v24.host.deepseek import AdapterFailure, MODEL
        row = {"effect_id": str(effect["effect_id"])}
        build_rows.append(row)
        try:
            prepared = original_build(effect, history, pins)
            row.update(canonical_body_bytes=prepared.estimate - FRAMING_MARGIN, actual_max_tokens=prepared.max_tokens)
            return prepared
        except AdapterFailure as exc:
            row["failure"] = _reason(exc.reason)
            # Read-only diagnostic reconstruction using the adapter's exact pure
            # projection. It never changes the actual admission result or sends.
            try:
                request = effect["request"]
                messages, _, _ = adapter._messages(request, request["cause"], history)
                tools, _ = adapter._tools(pins)
                body = {"model": MODEL, "messages": adapter._provider_messages(messages), "stream": False}
                if tools: body["tools"] = tools
                row["canonical_body_bytes"] = len(_json_bytes(body))
            except Exception:
                row["canonical_body_bytes"] = None
            raise
    adapter.build = observed_build
    try:
        parent = (args.evidence_dir or Path(__file__).resolve().parents[2] / "prompt-exports/v24-m5-evidence").resolve()
        root = Path(__file__).resolve().parents[2]
        if parent.is_relative_to(root) and not parent.is_relative_to(root / "prompt-exports"):
            raise RuntimeError("evidence_dir_not_ignored")
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(parent.stat().st_mode) != 0o700:
            raise RuntimeError("evidence_parent_not_private")
        evidence = Path(tempfile.mkdtemp(prefix="v24-real-", dir=parent))
        os.chmod(evidence, 0o700)
        for name in ("workspace", "spawn", "spill"):
            (evidence / name).mkdir(mode=0o700)
        with _private_fixture_server(evidence):
            with setup_db() as fixture:
                params = parse_dsn(fixture.role_dsn("admin"))
                env = UiEnv(
                    repo_root=Path(__file__).resolve().parents[2],
                    data_dir=evidence, db_name=fixture.name,
                    socket_dir=Path(params["host"]), port=int(params["port"]),
                    maintenance_dsn=fixture.maintenance_dsn,
                    admin_dsn=fixture.role_dsn("admin"),
                    service_dsn=fixture.role_dsn("service"),
                    journal_path=evidence / "journal.jsonl",
                    spawn_dir=evidence / "spawn",
                    workspace_root=evidence / "workspace",
                    spill_root=evidence / "spill",
                    skills_root=Path(__file__).resolve().parent / "skills",
                )
                os.environ["V24_SPILL_ROOT"] = str(env.spill_root)
                os.environ["V24_SKILLS_ROOT"] = str(env.skills_root)
                rt = None
                try:
                    rt = AgentRuntime(env, mode="real", adapter=adapter, limits=limits)
                    observer.runtime = rt
                    realm = "real-" + uuid4().hex[:8]
                    scope = rt.create_scope(realm)
                    scenario = args.scenario
                    toolset = "read" if scenario == "short" else ("write" if scenario in ("write10", "probe") else "exec")
                    families = catalog.families(realm, toolset)
                    rt.install_tools(scope, families)
                    owner = rt.fiber_for(scope, "v24.ui.pi_tools")
                    skills = catalog.available_skills()
                    system = catalog.build_system_prompt(skills, "", limits.completion_cap,
                                                         limits.body_byte_ceiling)
                    prompts = {
                        "short": "Reply briefly to confirm readiness. Do not call tools.",
                        "write10": "Read the full v24 surgical-edit skill at .v24/skills/surgical-edit/SKILL.md. Then use write to create result.txt containing exactly WI2_WRITE_MARKER. Read it back and give a short final answer.",
                        "exec11": EXEC11_PROMPT,
                        "skill": "Read the full v24 repo-recon skill at .v24/skills/repo-recon/SKILL.md. Then summarize the skill briefly. This empty workspace has no repository to investigate; do not edit files.",
                    }
                    expected = None
                    if scenario == "probe":
                        content = _probe_content(args.target_args_bytes, args.content_class)
                        expected = {"path": "result.txt", "content": content, "append": False}
                        prompts[scenario] = "Call write exactly once with path result.txt, append false, and content exactly between <target> tags. Do not call another tool or explain. <target>" + content + "</target>"
                    elif scenario in ("write10", "exec11"):
                        expected = {"path": "result.txt", "content": "WI2_WRITE_MARKER" if scenario == "write10" else "WI2_EXEC_MARKER"}
                    original_tool = rt.worker.tool_handler
                    guard_rejections = []
                    delegated_writes = set()
                    def guard_predicate(key, params):
                        allowed_reads = ("result.txt", ".v24/skills/surgical-edit/SKILL.md", ".v24/skills/repo-recon/SKILL.md")
                        if key in ("read", "read_file"):
                            return None if params.get("path") in allowed_reads else "path_mismatch"
                        if key == "write":
                            if expected is None:
                                return "write_not_expected"
                            if key in delegated_writes:
                                return "duplicate_write"
                            if params.get("path") != "result.txt":
                                return "path_mismatch"
                            if params.get("content") != expected["content"]:
                                return "content_mismatch"
                            if params.get("append", False) is not False:
                                return "append_mismatch"
                            return None
                        if key == "bash":
                            if scenario != "exec11":
                                return "bash_not_expected"
                            if key in delegated_writes:
                                return "duplicate_bash"
                            if params.get("command") != EXEC11_COMMAND:
                                return "command_mismatch"
                            return None
                        if key in ("get_file_tree", "ls", "find", "grep", "file_search") and scenario == "skill":
                            return None if params.get("path", ".") in (".", "") else "path_mismatch"
                        return "key_not_allowed"

                    def guarded_tool(effect):
                        request = effect.get("request", {})
                        key, params = request.get("key"), request.get("args") or {}
                        predicate = guard_predicate(key, params)
                        if predicate:
                            guard_rejections.append({"effect_id": str(effect["effect_id"]),
                                                     "key": str(key), "predicate": predicate})
                            return {"class": "failure", "result": {"status": "error", "output": {"code": "measurement_guard_rejected"}, "usage": {"wall_ms": 0}}, "model_text": "measurement_guard_rejected"}
                        if key in ("write", "bash"):
                            delegated_writes.add(key)
                        return original_tool(effect)
                    rt.worker.tool_handler = guarded_tool
                    run_id, _ = rt.start_run(scope, owner, [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompts[scenario]},
                    ], toolset=toolset, key="v24-real-start-" + uuid4().hex)
                    report, reason = _drive_measurement(rt, scope, run_id, scenario, expected, observer)
                    status = report.status if report.status in {
                        "completed", "failed", "cancelled", "blocked_unknown", "waiting", "stalled"
                    } else "entry_failed"
                    records = [json.loads(line) for line in env.journal_path.read_text().splitlines()]
                    summary = _safe_receipt(args, limits, rt, run_id, report, reason, expected, records, observer, before, secrets)
                    summary["builds"] = build_rows
                    summary["guard_rejections"] = guard_rejections
                    summary["contract_passed"] = summary["contract_passed"] and not guard_rejections
                    _assert_safe(summary, secrets)
                    _private_json(evidence / "summary.json", summary)
                    # Private durable export is needed because disposable DBs
                    # are torn down; never print or copy it to public reports.
                    _private_json(evidence / "durable-private.json", {"run": rt.run_state(run_id), "effects": _effects(rt, run_id), "pins": rt.db.host_run_pins(run_id, None, 64)})
                    code = 0 if summary["contract_passed"] else 1
                    if status in {"completed", "failed", "cancelled"}:
                        rt.close_scope(scope)
                finally:
                    if rt is not None:
                        rt.close()
    except Exception as exc:
        # Exception text can contain provider content or credentials.
        status, code = "entry_failed", 1
        if evidence is not None:
            _private_json(evidence / "entry-error.json", {"exception_type": type(exc).__name__, "builds": build_rows,
                          "source_sha256": before, "http": observer.rows})
    finally:
        adapter.build = original_build
        adapter.transport = observer.delegate
    journal = evidence / "journal.jsonl" if evidence is not None else None
    retained = bool(journal and journal.exists())
    print(f"[real] scenario={args.scenario}; profile={args.profile}; status={status}; journal={'retained' if retained else 'absent'}; contract={'passed' if code == 0 else 'incomplete'}; evidence={evidence.name if evidence else 'absent'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
