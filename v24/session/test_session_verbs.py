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

PASS = "[passed] v24 session M1/M2 gate"


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
        self.cancel_calls = []
        self.cancel_fail = None

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

    def cancel(self, rid, key):
        self.cancel_calls.append((rid, key))
        if self.cancel_fail is not None:
            raise self.cancel_fail
        run = self.runs.get(rid)
        if run is None:
            return {"error": {"code": "not_found_or_denied"}}
        if run["status"] in ("completed", "failed", "cancelled", "blocked_unknown"):
            return {"error": {"code": "already_terminal"}}
        run["status"] = "cancelled"
        run["revision"] += 1
        return {"run": dict(run)}

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


def test_wait_cancel():
    with tempfile.TemporaryDirectory(prefix="v24-session-m2-") as temp:
        store = _new_store(temp)
        backend = FakeBackend(events=3)
        service = SessionService(store, backend)
        started = service.start({"message": "wait", "request_key": "wait"})
        sid, rid, cursor = started["session_id"], started["run_id"], started["cursor"]

        # timeout, then revision-only (changed but no wake), then none at timeout 0.
        timed = service.wait({"session_id": sid, "cursor": cursor, "timeout_ms": 20,
                              "include_events": False})
        check(timed["wake"] == {"ready": False, "reason": "timeout"}, timed)
        check(timed["changed"] is False, timed)
        backend.runs[rid]["revision"] += 1
        revision_only = service.wait({"session_id": sid, "cursor": cursor, "timeout_ms": 20,
                                      "include_events": False})
        check(revision_only["wake"]["reason"] == "timeout", revision_only)
        check(revision_only["changed"] is True, revision_only)
        no_wait = service.wait({"session_id": sid, "cursor": cursor, "timeout_ms": 0,
                                "include_events": False})
        check(no_wait["wake"] == {"ready": False, "reason": "none"}, no_wait)

        # event wake uses the returned prefix and advances only to its max seq.
        backend.events = 5
        event = service.wait({"session_id": sid, "cursor": cursor, "timeout_ms": 100,
                              "include_events": True})
        check(event["wake"]["reason"] == "event", event)
        check(event["cursor"]["event_seq"] == 5, event)
        check([item["seq"] for item in event["events"]] == [1, 2, 3, 4, 5], event)
        no_event = service.wait({"session_id": sid, "cursor": event["cursor"], "timeout_ms": 20,
                                 "include_events": True})
        check(no_event["wake"]["reason"] == "timeout", no_event)

        # No cursor takes the current high-water mark, so existing events do not wake.
        high = service.wait({"session_id": sid, "timeout_ms": 0, "include_events": True})
        check(high["wake"]["reason"] == "none", high)
        check(high["cursor"]["event_seq"] == 5, high)
        check(high["events"] == [], high)

        # terminal.
        backend.finish(rid, "completed")
        terminal = service.wait({"session_id": sid, "cursor": cursor, "timeout_ms": 0})
        check(terminal["wake"]["reason"] == "terminal", terminal)
        check(terminal["snapshot"]["status"] == "completed", terminal)

        # interaction (separate session) is top-level and does not need event pagination.
        interaction_start = service.start({"message": "ask", "request_key": "ask"})
        irid = interaction_start["run_id"]
        backend.runs[irid]["status"] = "waiting"
        backend.runs[irid]["interaction"] = {"interaction_id": str(uuid.uuid4())}
        backend.runs[irid]["revision"] += 1
        interaction = service.wait({"session_id": interaction_start["session_id"],
                                    "cursor": interaction_start["cursor"], "timeout_ms": 0})
        check(interaction["wake"]["reason"] == "interaction", interaction)
        check(interaction["interaction_id"] == backend.runs[irid]["interaction"]["interaction_id"],
              interaction)

        # epoch resets event_seq to 0 and is not reported as not-found.
        epoch_start = service.start({"message": "epoch", "request_key": "epoch"})
        erid = epoch_start["run_id"]
        backend.runs[erid]["epoch_no"] = 2
        backend.runs[erid]["driving_generation"] = 2
        backend.runs[erid]["revision"] += 1
        epoch = service.wait({"session_id": epoch_start["session_id"],
                              "cursor": epoch_start["cursor"], "timeout_ms": 0,
                              "include_events": True})
        check(epoch["wake"]["reason"] == "epoch", epoch)
        check(epoch["cursor"]["event_seq"] == 0, epoch)

        # registration-generation mismatch is the same epoch wake, not not-found.
        reg_start = service.start({"message": "registration", "request_key": "registration"})
        reg_rid = reg_start["run_id"]
        backend.runs[reg_rid]["registration_generation"] = 2
        backend.runs[reg_rid]["revision"] += 1
        stale_registration = service.wait({"session_id": reg_start["session_id"],
                                           "cursor": reg_start["cursor"],
                                           "timeout_ms": 0, "include_events": True})
        check(stale_registration["wake"]["reason"] == "epoch", stale_registration)
        check(stale_registration["cursor"]["event_seq"] == 0, stale_registration)

        # run_started outranks terminal on the new run.
        run_started = service.start({"message": "switch", "request_key": "switch"})
        old_cursor = run_started["cursor"]
        second = backend.start(session_id=run_started["session_id"], message="next",
                               toolset=None, budget={}, run_key="second-run",
                               workspace_root=None, model=None)
        store.bind(run_started["session_id"], second.scope_id, second.run_id,
                   realm="test", workspace_root="", toolset="", catalog_digest="",
                   mode="fake", limits_digest="")
        backend.finish(second.run_id, "completed")
        switched = service.wait({"session_id": run_started["session_id"],
                                  "cursor": old_cursor, "timeout_ms": 0})
        check(switched["wake"]["reason"] == "run_started", switched)
        check(switched["snapshot"]["current_run"]["run_id"] == second.run_id, switched)

        # Multi-session: terminal winner, pending ids, full cursor map, all_terminal.
        terminal_session = service.start({"message": "t", "request_key": "multi-t"})
        running_session = service.start({"message": "r", "request_key": "multi-r"})
        backend.finish(terminal_session["run_id"], "completed")
        terminal_sid = terminal_session["session_id"]
        running_sid = running_session["session_id"]
        multi = service.wait({"session_ids": [terminal_sid, running_sid],
                              "timeout_ms": 0, "include_events": False})
        check(multi["ok"] and multi["wake"]["reason"] == "terminal", multi)
        check(multi["winner_session_id"] in (terminal_sid, running_sid), multi)
        check(len(multi["cursors"]) == 2, multi)
        check(multi["all_terminal"] is False, multi)
        check(set(multi["pending_session_ids"]) == {terminal_sid, running_sid}
              - {multi["winner_session_id"]}, multi)
        backend.finish(running_session["run_id"], "completed")
        all_done = service.wait({"session_ids": [terminal_sid, running_sid],
                                 "timeout_ms": 0, "include_events": False})
        check(all_done["all_terminal"] is True, all_done)
        check(all_done["wake"]["reason"] == "terminal", all_done)

        # Cancel: committed, replay does not call backend twice, terminal is rejected.
        cancel_session = service.start({"message": "cancel", "request_key": "cancel"})
        crid = cancel_session["run_id"]
        cancelled = service.cancel({"session_id": cancel_session["session_id"],
                                    "expected_run_id": crid, "expected_generation": 1,
                                    "request_key": "cancel-1"})
        check(cancelled["ok"] and cancelled["already_terminal"] is False, cancelled)
        check(cancelled["snapshot"]["status"] == "cancelled", cancelled)
        calls = len(backend.cancel_calls)
        replay = service.cancel({"session_id": cancel_session["session_id"],
                                 "expected_run_id": crid, "expected_generation": 1,
                                 "request_key": "cancel-1"})
        check(replay["disposition"] == "replay" and replay["ok"], replay)
        check(len(backend.cancel_calls) == calls, backend.cancel_calls)
        terminal_cancel = service.cancel({"session_id": cancel_session["session_id"],
                                          "request_key": "cancel-2"})
        check(terminal_cancel["ok"] is False and terminal_cancel["already_terminal"], terminal_cancel)
        conflict = service.cancel({"session_id": cancel_session["session_id"],
                                   "expected_run_id": "different", "request_key": "cancel-1"})
        check(conflict["error"]["code"] == "request_conflict", conflict)

        # Expected-generation CAS happens before the backend call.
        cas_session = service.start({"message": "cas", "request_key": "cas"})
        before = len(backend.cancel_calls)
        stale = service.cancel({"session_id": cas_session["session_id"],
                                "expected_generation": 99, "request_key": "cas-1"})
        check(stale["error"]["code"] == "stale_generation", stale)
        check(len(backend.cancel_calls) == before, backend.cancel_calls)

        # A failing cancel freezes; the same key is replayed without a second call.
        frozen_session = service.start({"message": "frozen", "request_key": "frozen"})
        backend.cancel_fail = RuntimeError("provider_unavailable")
        frozen = service.cancel({"session_id": frozen_session["session_id"],
                                 "request_key": "frozen-1"})
        check(frozen["disposition"] == "deferred" and frozen["ok"] is False, frozen)
        calls = len(backend.cancel_calls)
        frozen_replay = service.cancel({"session_id": frozen_session["session_id"],
                                        "request_key": "frozen-1"})
        check(frozen_replay["disposition"] == "deferred", frozen_replay)
        check(len(backend.cancel_calls) == calls, backend.cancel_calls)
        backend.cancel_fail = None

        # Unknown and idle sessions are rejected without touching a run.
        unknown = service.wait({"session_id": str(uuid.uuid4()), "timeout_ms": 0})
        check(unknown["error"]["code"] == "not_found_or_denied", unknown)
        unknown_many = service.wait({"session_ids": [running_sid, str(uuid.uuid4())],
                                     "timeout_ms": 0})
        check(unknown_many["ok"] is False and len(unknown_many["errors"]) == 1, unknown_many)

        # Wait is a pure read: the store bytes do not change.
        before = (Path(temp) / "sessions.json").read_bytes()
        service.wait({"session_id": running_session["session_id"], "timeout_ms": 10})
        check((Path(temp) / "sessions.json").read_bytes() == before, "wait wrote the store")

    with tempfile.TemporaryDirectory(prefix="v24-session-m2-starting-") as temp:
        store = _new_store(temp)
        service = SessionService(store, FakeBackend(fail=RuntimeError("setup_incomplete")))
        deferred = service.start({"message": "start", "request_key": "starting"})
        sid = deferred["session_id"]
        closed = service.cancel({"session_id": sid, "request_key": "start-cancel"})
        check(closed["ok"] and closed["snapshot"]["state"] == "closed", closed)
        check(store.get(sid)["state"] == "closed", store.get(sid))
        again = service.cancel({"session_id": sid, "request_key": "start-cancel-2"})
        check(again["error"]["code"] == "session_closed", again)


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
    test_wait_cancel()
    test_budget_and_deferred()
    test_migration_and_fail_closed()
    print(PASS, flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[failed] v24 session M1/M2 gate; {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
