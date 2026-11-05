#!/usr/bin/env python3
"""Headless S0-M1 gate: v2 store, start, poll, replay, migration.

Run: uv run python v24/session/test_session_verbs.py
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.session import SessionService, SessionStore, StartResult, StoreError  # noqa: E402
from v24.session import wire  # noqa: E402

PASS = "[passed] v24 session M1 gate"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_id():
    return str(uuid.uuid4())


class FakeBackend:
    def __init__(self, *, fail=None, events=3, start_calls=None):
        self.fail = fail
        self.events = events
        self.start_calls = start_calls if start_calls is not None else []
        self.runs = {}
        self.budgets = []
        self.messages = []

    def start(self, *, session_id, message, toolset, budget, run_key, workspace_root, model):
        self.start_calls.append((session_id, run_key))
        self.budgets.append(dict(budget))
        self.messages.append(message)
        if self.fail is not None:
            raise self.fail
        rid = run_id()
        run = {"run_id": rid, "status": "running", "epoch_no": 1,
               "registration_generation": 1, "turn_no": 0,
               "driving_generation": 1, "revision": 1,
               "created_at": "2026-11-05T00:00:00+00:00",
               "updated_at": "2026-11-05T00:00:00+00:00",
               "interaction": None, "pending_steer": None, "result": None}
        self.runs[rid] = run
        return StartResult(run_id=rid, scope_id=str(uuid.uuid4()), realm="test",
                           binding={}, run=dict(run))

    def poll(self, rid, after_revision=0):
        run = self.runs.get(rid)
        if run is None:
            return {"v": 1, "error": {"code": "not_found_or_denied"}}
        events = [{"seq": seq, "event_kind": "run_started" if seq == 1 else "tool_call_settled",
                   "payload": {"run_id": rid}, "created_at": "2026-11-05T00:00:00+00:00"}
                  for seq in range(1, self.events + 1)]
        return {"v": 1, "revision": run["revision"], "changed": True,
                "run": dict(run), "events": events}

    def finish(self, rid, status):
        self.runs[rid]["status"] = status
        self.runs[rid]["revision"] += 1


def _new_store(directory):
    return SessionStore(directory)


def _service(store, **kwargs):
    return SessionService(store, FakeBackend(**kwargs))


def test_import_boundary():
    for path in sorted(p for p in (ROOT / "v24" / "session").glob("*.py") if not p.name.startswith("test_")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                check(not module.startswith("chainlit"), (path.name, module))
                check(not module.startswith("v24.ui"), (path.name, module))
    from v24.ui import sessions
    check(sessions.VERSION == 2, "UI compatibility facade is not v2")


def test_start_poll():
    with tempfile.TemporaryDirectory(prefix="v24-session-m1-") as temp:
        store = _new_store(temp)
        backend = FakeBackend(events=3)
        service = SessionService(store, backend)
        response = service.start({"message": "read the parser", "request_key": "k-1"})
        check(response["ok"] and response["disposition"] == "committed", response)
        sid = response["session_id"]
        snapshot = response["snapshot"]
        check(snapshot["state"] == "active", snapshot)
        check(snapshot["status"] == "running", snapshot)
        check(snapshot["run_no"] == 1 and snapshot["user_turn_no"] == 1, snapshot)
        check(snapshot["cursor"]["session_revision"] >= 2, snapshot)
        check(snapshot["cursor"]["event_seq"] == 0, snapshot)
        check(len(store.sessions) == 1, store.sessions)
        row = store.get(sid)
        check(row["counter_origin"] == "native_v2", row)
        check(row["receipts"][-1]["phase"] == "completed", row["receipts"])
        check(row["pending_intent"] is None, row)
        check((Path(temp) / "sessions.json.prev").exists(), "atomic replace did not keep .prev")
        check(json.loads((Path(temp) / "sessions.json").read_text())["format_version"] == 2, "not v2")

        replay = service.start({"message": "read the parser", "request_key": "k-1"})
        check(replay["disposition"] == "replay" and replay["ok"], replay)
        check(replay["session_id"] == sid, replay)
        check(len(backend.start_calls) == 1, backend.start_calls)
        check(store.get(sid)["run_no"] == 1 and store.get(sid)["user_turn_no"] == 1, store.get(sid))

        conflict = service.start({"message": "different", "request_key": "k-1"})
        check(conflict["ok"] is False and conflict["error"]["code"] == "request_conflict", conflict)
        check(len(store.sessions) == 1, store.sessions)

        invalid = service.start({"message": "x", "request_key": "k-2", "session_id": sid})
        check(invalid["error"]["code"] == "invalid_args", invalid)
        check(len(store.sessions) == 1, store.sessions)

        poll = service.poll({"session_id": sid, "include_events": True})
        check(poll["ok"] and poll["changed"] is True, poll)
        check(len(poll["events"]) == 3, poll)
        check(poll["cursor"]["event_seq"] == 3, poll)
        poll_again = service.poll({"session_id": sid, "cursor": poll["cursor"], "include_events": True})
        check(poll_again["changed"] is False, poll_again)
        check(poll_again["cursor"]["event_seq"] == 3, poll_again)
        no_events = service.poll({"session_id": sid, "include_events": False})
        check(no_events["events"] == [], no_events)
        check(no_events["cursor"]["event_seq"] == 0, no_events)
        unknown = service.poll({"session_id": str(uuid.uuid4())})
        check(unknown["ok"] is False and unknown["error"]["code"] == "not_found_or_denied", unknown)

        # Restart: committed start is replayed from the durable envelope and
        # the backend is not called a second time.
        store2 = _new_store(temp)
        backend2 = FakeBackend()
        service2 = SessionService(store2, backend2)
        replay2 = service2.start({"message": "read the parser", "request_key": "k-1"})
        check(replay2["disposition"] == "replay" and replay2["session_id"] == sid, replay2)
        check(backend2.start_calls == [], backend2.start_calls)


def test_event_prefix_and_multi_session():
    with tempfile.TemporaryDirectory(prefix="v24-session-m1-events-") as temp:
        store = _new_store(temp)
        backend = FakeBackend(events=70)
        service = SessionService(store, backend)
        first = service.start({"message": "a", "request_key": "a"})
        second = service.start({"message": "b", "request_key": "b"})
        page = service.poll({"session_id": first["session_id"], "include_events": True})
        check(len(page["events"]) == 64, len(page["events"]))
        check(page["cursor"]["event_seq"] == 64, page["cursor"])
        check([e["seq"] for e in page["events"]] == list(range(1, 65)), "poll did not return earliest prefix")

        many = service.poll({"session_ids": [first["session_id"], second["session_id"], str(uuid.uuid4())],
                              "include_events": False})
        check(many["ok"] and len(many["sessions"]) == 3, many)
        check(many["sessions"][0]["ok"] and many["sessions"][1]["ok"], many)
        check(many["sessions"][2]["ok"] is False, many)
        check(many["sessions"][2]["error"]["code"] == "not_found_or_denied", many)

        # A cursor from another session is ignored for change detection.
        wrong = service.poll({"session_id": first["session_id"], "cursor": second["cursor"]})
        check(wrong["changed"] is True, wrong)
        check(wrong["cursor"]["event_seq"] == 0, wrong)


def test_budget_and_deferred():
    with tempfile.TemporaryDirectory(prefix="v24-session-m1-budget-") as temp:
        store = _new_store(temp)
        backend = FakeBackend()
        service = SessionService(store, backend)
        response = service.start({"message": "x", "request_key": "budget",
                                  "budget": {"steps": 1, "tool_calls": 0, "wall_ms": 1}})
        check(response["ok"], response)
        check(backend.budgets[-1] == {"steps": 1, "tool_calls": 0, "wall_ms": 1}, backend.budgets)
        null_token = service.start({"message": "x", "request_key": "null-token",
                                    "budget": {"steps": 1, "tool_calls": 0, "tokens": None, "wall_ms": 1}})
        check(null_token["error"]["code"] == "invalid_args", null_token)
        extra = service.start({"message": "x", "request_key": "extra",
                               "budget": {"steps": 1, "tool_calls": 0, "tokens": 1, "wall_ms": 1, "x": 1}})
        check(extra["error"]["code"] == "invalid_args", extra)

    with tempfile.TemporaryDirectory(prefix="v24-session-m1-deferred-") as temp:
        store = _new_store(temp)
        failing = FakeBackend(fail=RuntimeError("setup_incomplete"))
        service = SessionService(store, failing)
        first = service.start({"message": "x", "request_key": "deferred"})
        check(first["ok"] is False and first["disposition"] == "deferred", first)
        check(first["error"]["code"] == "setup_incomplete", first)
        check(len(store.sessions) == 1, store.sessions)
        sid = first["session_id"]
        row = store.get(sid)
        check(row["pending_intent"]["phase"] == "deferred", row)
        check(row["receipts"][-1]["frozen_deferred"] is True, row["receipts"])
        retry = service.start({"message": "x", "request_key": "deferred"})
        check(retry["disposition"] == "deferred" and retry["session_id"] == sid, retry)
        check(retry == first, "deferred response was not frozen byte-for-byte")
        check(len(store.sessions) == 1 and len(failing.start_calls) == 1, failing.start_calls)
        deferred_poll = service.poll({"session_id": sid})
        check(deferred_poll["snapshot"]["status"] == "starting", deferred_poll)


def test_migration_and_fail_closed():
    with tempfile.TemporaryDirectory(prefix="v24-session-m1-migrate-") as temp:
        directory = Path(temp)
        sid = str(uuid.uuid4())
        scope = str(uuid.uuid4())
        runs = [str(uuid.uuid4()), str(uuid.uuid4())]
        v1 = {
            "format_version": 1,
            "active_conversation_id": sid,
            "conversations": [{
                "conversation_id": sid,
                "resume_token_hash": "a" * 64,
                "created_at": "2026-11-05T00:00:00+00:00",
                "updated_at": "2026-11-05T00:00:00+00:00",
                "bindings": [{"scope_id": scope, "run_id": rid} for rid in runs],
                "active_binding": {"scope_id": scope, "run_id": runs[-1]},
            }],
        }
        (directory / "sessions.json").write_text(json.dumps(v1), encoding="utf-8")
        (directory / "turns.jsonl").write_text(
            "".join(json.dumps({"conversation_id": sid, "run_id": rid, "seq": seq,
                                "user_text": f"u{seq}", "created_at": "t"}) + "\n"
                    for seq, rid in enumerate(runs, 1)), encoding="utf-8")
        store = _new_store(directory)
        row = store.get(sid)
        check(row is not None and row["run_no"] == 2 and row["user_turn_no"] == 2, row)
        check(row["counter_origin"] == "legacy_approx", row)
        check((directory / "sessions.json.v1.bak").exists(), "missing sessions .v1.bak")
        check((directory / "turns.jsonl.v1.bak").exists(), "missing turns .v1.bak")
        v2 = json.loads((directory / "sessions.json").read_text())
        check(v2["format_version"] == 2 and v2["conversations"][0]["session_id"] == sid, v2)
        check(len(store.history(sid)) == 2, store.history(sid))
        check(store.get(sid) is not None, "conversation_id alias lookup failed")

    with tempfile.TemporaryDirectory(prefix="v24-session-m1-corrupt-") as temp:
        directory = Path(temp)
        original = b"{not-json\n"
        (directory / "sessions.json").write_bytes(original)
        store = _new_store(directory)
        check(store.failed == "session_store_corrupt", store.failed)
        check((directory / "sessions.json").read_bytes() == original, "corrupt store was overwritten")
        try:
            store.flush()
        except StoreError as exc:
            check(str(exc) == "session_store_corrupt", exc)
        else:
            raise AssertionError("corrupt store was writable")


def main():
    test_import_boundary()
    test_start_poll()
    test_event_prefix_and_multi_session()
    test_budget_and_deferred()
    test_migration_and_fail_closed()
    print(PASS, flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[failed] v24 session M1 gate; {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
