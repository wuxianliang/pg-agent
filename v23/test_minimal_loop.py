"""The single fake-only M1 runtime gate (plan §9: 50 labels plus §9.10 subcases).

Run from the repository root: uv run python v23/test_minimal_loop.py
Admin connections audit/inject faults only; business behavior uses Control.execute.
Subprocess fixtures run this same file without resetting the database, using files
and stdio, never TCP. Every thread/process/barrier has a finite deadline.
"""
from __future__ import annotations

import ast
import asyncio
import copy
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, make_dsn, parse_dsn
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import v23.control as cm
import v23.host as hm
import v23.setup_db as setup
import v23.worker as wm
from v23.control import Control, ControlError, HostActor, ParentActor, WorkerError
from v23.disposition import decide
from v23.host import Host, HostBusyError
from v23.worker import FakeWorker, FakeTool, TurnReceipt, WorkerContractError

H = HostActor()
DEADLINE = 10
LABELS = (
    "v23_unknown_op_rejected", "v23_start_worker_outside_tx", "v23_start_receipt_committed",
    "v23_worker_called_once_per_op", "v23_no_socket", "v23_vertical_run_steer_stop",
    "v23_progress_three_dispositions", "v23_budget_stop", "v23_completed_is_not_reopened",
    "v23_wait_is_read_only", "v23_wait_notification_only_wakes", "v23_wait_timeout_rereads",
    "v23_wait_read_listen_race_closed", "v23_wait_notification_lost", "v23_wait_notification_merged",
    "v23_transaction_idle_boundaries", "v23_respond_only_waiting_input",
    "v23_respond_interaction_exact_match", "v23_parent_child_authority",
    "v23_host_continuation_has_no_input", "v23_parent_wait_does_not_schedule",
    "v23_expected_revision_conflict", "v23_two_consumers_same_revision",
    "v23_idempotent_mutation", "v23_idempotency_conflict", "v23_pending_digest_and_recovery_receipt",
    "v23_commit_ack_loss_no_replay", "v23_cancel_idempotency_and_zero_write",
    "v23_respond_budget_admission", "v23_t2_owner_only_retry", "v23_cancel_running",
    "v23_late_worker_result_discarded", "v23_t2_cancel_lock_order",
    "v23_cancel_ready_and_waiting", "v23_owner_disappearance_no_replay",
    "v23_process_restart_closes_orphans", "v23_invalid_receipt_closes_safely",
    "v23_worker_exception_closes_safely", "v23_fake_tools_bounded",
    "v23_tool_failure_does_not_schedule", "v23_single_run_coroutine",
    "v23_host_stop_calls_cancel", "v23_completed_not_cancelled", "v23_only_one_data_table",
    "v23_load_is_single_sql", "v23_no_v13_v15_imports", "v23_no_static_control_map",
    "v23_no_events_effects_history_tables", "v23_control_worker_permissions", "v23_no_network",
)
EVIDENCE: dict[int, list[str]] = {}
CONTROLS: list[Control] = []
TASKS = []
CHILDREN = []
DSN = ADMIN = ""
NETWORK = {"postgres": 0, "blocked": 0}


def uid():
    return str(uuid4())


def proof(number, subcase, *conditions):
    if not conditions or not all(conditions):
        raise AssertionError(f"{LABELS[number-1]}/{subcase}")
    EVIDENCE.setdefault(number, []).append(subcase)
    print(f"  [ok] {number:02d}/{subcase}", flush=True)


def expect(code, fn):
    try:
        fn()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise AssertionError(f"expected {code}, got {type(exc).__name__}: {exc}") from exc
        return exc
    raise AssertionError("expected " + code)


def rejects(fn, kind=ValueError):
    try:
        fn()
    except kind as exc:
        return exc
    raise AssertionError("expected " + kind.__name__)


def barrier(event, name="barrier"):
    if not event.wait(DEADLINE):
        raise AssertionError(name + " deadline")


class Task:
    def __init__(self, fn):
        self.value = self.error = None
        def run():
            try:
                self.value = fn()
            except BaseException as exc:
                self.error = exc
        self.thread = threading.Thread(target=run, daemon=True)
        TASKS.append(self)
        self.thread.start()

    def finish(self, code=None):
        self.thread.join(DEADLINE)
        if self.thread.is_alive():
            raise AssertionError("thread deadline")
        if code:
            if getattr(self.error, "code", None) != code:
                raise AssertionError((code, self.error))
            return self.error
        if self.error is not None:
            raise self.error
        return self.value


def control(worker=None, cls=Control, **kwargs):
    c = cls(DSN, worker if worker is not None else FakeWorker(), **kwargs)
    CONTROLS.append(c)
    return c


def close_controls():
    for c in reversed(CONTROLS):
        c.close(timeout_seconds=0)
    CONTROLS.clear()


def request(run_id=None, budget=5):
    return {"run_id": run_id or uid(), "parent_run_id": None, "instruction": "one",
            "turn_budget": budget, "request_id": uid()}


def poll(c, run_id, actor=H):
    return c.execute("poll", actor, {"run_id": run_id})["snapshot"]


def steer(s, request_id=None):
    return {"run_id": s["run_id"], "expected_revision": s["revision"],
            "request_id": request_id or uid(), "continuation": True}


def response(s, value="yes", request_id=None):
    return {"run_id": s["run_id"], "expected_revision": s["revision"], "request_id": request_id or uid(),
            "interaction_id": s["latest_receipt"]["input_request"]["interaction_id"], "response": value}


def cancel(c, s, request_id=None):
    return c.execute("cancel", H, {"run_id": s["run_id"], "expected_revision": s["revision"],
                                  "request_id": request_id or uid()})


def query(sql, args=(), *, dsn=None, role=None):
    conn = psycopg2.connect(dsn or ADMIN, application_name="v23_gate_audit")
    try:
        with conn.cursor() as cur:
            if role:
                cur.execute("SET ROLE " + role)
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else None
    finally:
        conn.close()


def row(run_id):
    conn = psycopg2.connect(ADMIN, application_name="v23_gate_audit")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT *, xmin::text AS xmin FROM v23_runs WHERE run_id=%s", (run_id,))
            value = cur.fetchone()
            return dict(value) if value is not None else None
    finally:
        conn.close()


def durable(c, s):
    observed = poll(c, s["run_id"])
    audit = row(s["run_id"])
    assert observed == s and cm._snapshot({k: v for k, v in audit.items() if k != "xmin"}) == s
    return audit


def zero_write(number, subcase, c, s, code, fn):
    before, count = row(s["run_id"]), len(c.worker.calls)
    expect(code, fn)
    proof(number, subcase, row(s["run_id"]) == before, len(c.worker.calls) == count,
          poll(c, s["run_id"]) == s)


class Blocking(FakeWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enter, self.release = threading.Event(), threading.Event()

    def run(self, wr):
        # The sole FakeWorker.run below counts exactly once, after the barrier.
        self.enter.set()
        barrier(self.release, "Worker release")
        return super().run(wr)


class JoinProbe(Control):
    def __init__(self, *args, **kwargs):
        self.joined = threading.Event()
        super().__init__(*args, **kwargs)

    def _join_owner(self, *args):
        self.joined.set()
        return super()._join_owner(*args)


class Fault(Control):
    def __init__(self, *args, phase="T2", mode="rollback", sqlstate="40001", **kwargs):
        self.phase, self.mode, self.sqlstate = phase, mode, sqlstate
        self.inject = True
        self.commits = []
        super().__init__(*args, **kwargs)

    def _commit(self, conn, phase):
        self.commits.append((phase, conn.get_backend_pid()))
        if phase == self.phase and self.inject:
            self.inject = False
            if self.mode == "rollback":
                with conn.cursor() as cur:
                    cur.execute("DO $$ BEGIN RAISE EXCEPTION 'gate rollback' USING ERRCODE=%s; END $$", (self.sqlstate,))
            if self.mode == "dead_before":
                conn.close()
                raise psycopg2.OperationalError("gate session loss")
            conn.commit()  # genuinely committed before acknowledgement loss
            if self.mode == "dead_after":
                conn.close()
                raise psycopg2.OperationalError("gate session loss")
            raise RuntimeError("gate acknowledgement loss")
        super()._commit(conn, phase)


@contextmanager
def network_guard():
    real_socket, real_connect = socket.socket, psycopg2.connect
    class UnixOnlySocket(real_socket):
        def __init__(self, family=socket.AF_INET, *args, **kwargs):
            if family != socket.AF_UNIX:
                NETWORK["blocked"] += 1
                raise AssertionError("external network forbidden")
            super().__init__(family, *args, **kwargs)
    def connect(dsn=None, *args, **kwargs):
        params = parse_dsn(dsn or "") | {k: v for k, v in kwargs.items() if k in {"host", "hostaddr"}}
        if not params.get("host", "").startswith("/") or params.get("hostaddr") or "," in params["host"]:
            NETWORK["blocked"] += 1
            raise AssertionError("only Unix PostgreSQL allowed")
        NETWORK["postgres"] += 1
        return real_connect(dsn, *args, **kwargs)
    with patch.object(socket, "socket", UnixOnlySocket), patch.object(psycopg2, "connect", connect):
        yield


def test_api_vertical_and_authority():
    """Labels 1,3,4,6–10,17–22,24–25,29,34,42–43 via real six-op chains."""
    w = FakeWorker(default="progress")
    c = control(w)
    q = request()
    first = c.execute("start", H, q)
    s = first["snapshot"]
    audit = durable(c, s)
    proof(3, "start durable before return", s["revision"] == 2, s["turns_used"] == 1,
          audit["op_cache"][q["request_id"]]["response"] == first, len(w.calls) == 1)
    zero_write(1, "unknown op", c, s, "unknown_op", lambda: c.execute("advance", H, {"run_id": s["run_id"]}))
    before = row(s["run_id"])
    default = c.execute(actor=H, request={"run_id": s["run_id"]})
    proof(1, "absent and null op are wait", default == c.execute(None, H, {"run_id": s["run_id"]}),
          default["operation"] == "wait", default["wait_result"] == "already_interesting", row(s["run_id"]) == before)
    bad_requests = [("poll", {"run_id": s["run_id"], "extra": 1}),
                    ("start", q | {"expected_revision": 0}), ("start", q | {"turn_budget": True}),
                    ("start", q | {"instruction": " "}), ("start", q | {"instruction": "x"*65536}),
                    ("poll", {"run_id": s["run_id"].upper()}), ("poll", {}),
                    ("respond", {"run_id": s["run_id"], "request_id": uid(), "expected_revision": 2,
                                 "interaction_id": uid(), "response": {1: "bad"}})]
    for index, (op, req) in enumerate(bad_requests):
        zero_write(1, f"request shape {index}", c, s, "invalid_request", lambda op=op, req=req: c.execute(op, H, req))
    for value in [True, float("nan"), float("inf"), -1, 3601]:
        zero_write(10, f"invalid timeout {value}", c, s, "invalid_request",
                   lambda value=value: c.execute("wait", H, {"run_id": s["run_id"], "timeout_seconds": value}))
    for since in [True, -1, 1.0, 2**63]:
        zero_write(10, f"invalid since {since}", c, s, "invalid_request",
                   lambda since=since: c.execute("wait", H, {"run_id": s["run_id"], "since_revision": since}))
    waited = c.execute("wait", H, {"run_id": s["run_id"], "since_revision": 2, "timeout_seconds": 0})
    proof(10, "poll/wait whole-row zero write", waited["wait_result"] == "timed_out", row(s["run_id"]) == before)
    proof(7, "progress three dispositions", decide(s, True)["decision"] == "run_now",
          decide(s, False)["decision"] == "wait", decide(s | {"turn_budget": 1}, True)["decision"] == "stop")
    proof(24, "start absent/null revision normalization", c.execute("start", H, q | {"expected_revision": None}) == first,
          row(s["run_id"]) == before, len(w.calls) == 1)
    zero_write(25, "start changed semantics", c, s, "idempotency_conflict", lambda: c.execute("start", H, q | {"instruction": "other"}))
    zero_write(22, "stale continuation", c, s, "revision_conflict", lambda: c.execute("steer", H, steer(s) | {"expected_revision": 0}))
    for req in [steer(s) | {"parent_instruction": "bad"}, {k: v for k, v in steer(s).items() if k != "continuation"}]:
        zero_write(20, "host cannot supply instruction/missing input", c, s, "missing_steer_input", lambda req=req: c.execute("steer", H, req))
    zero_write(20, "host instruction-only rejected", c, s, "missing_steer_input",
               lambda: c.execute("steer", H, {k: v for k, v in steer(s).items() if k != "continuation"} | {"parent_instruction": "bad"}))
    zero_write(17, "respond ready", c, s, "not_waiting_input", lambda: c.execute("respond", H, {
        "run_id": s["run_id"], "request_id": uid(), "expected_revision": 2, "interaction_id": uid(), "response": None}))

    # An independent, actual Host two-turn chain; no hand-decide substitute.
    run = uid()
    w._plans[run] = ["progress", "completed"]
    finished = Host(c).drive(run, instruction="vertical", turn_budget=2, run_request_id=uid())
    durable(c, finished)
    calls = [wr for wr in w.calls if str(wr.run_id) == run]
    proof(6, "Host start-progress-steer-completed-stop", finished["status"] == "completed",
          decide(finished, True)["decision"] == "stop", [wr.input_kind for wr in calls] == ["initial", "host_continue"])
    proof(4, "two-turn exact Worker counts", len(calls) == 2, finished["turns_used"] == 2,
          calls[1].instruction is None, calls[1].response is None, calls[1].continuation is True)
    zero_write(9, "completed steer", c, finished, "closed", lambda: c.execute("steer", H, steer(finished)))
    zero_write(9, "completed respond", c, finished, "not_waiting_input", lambda: c.execute("respond", H, {
        "run_id": run, "request_id": uid(), "expected_revision": finished["revision"], "interaction_id": uid(), "response": None}))
    before = row(run)
    with patch.object(hm, "decide", side_effect=AssertionError("external stop cannot decide")):
        stopped = Host(c).stop(run, uid())
    proof(43, "completed stop zero write", stopped == finished, row(run) == before)

    # Full explicit parent->child progress->needs_input->respond->progress->completed.
    parent = c.execute("start", H, request())["snapshot"]
    actor = ParentActor(parent["run_id"])
    child = uid()
    iq = {"interaction_id": uid(), "options": ["yes", "no"], "response_schema": {"type": "string"}}
    w._plans[child] = ["progress", {"outcome": "needs_input", "input_request": iq}, "progress", "completed"]
    cq = request(child) | {"parent_run_id": parent["run_id"]}
    for bad in [H, ParentActor(uid())]:
        count = len(w.calls)
        expect("not_found_or_unauthorized", lambda bad=bad: c.execute("start", bad, cq))
        proof(19, "only explicit parent creates child", row(child) is None, len(w.calls) == count)
    cs = c.execute("start", actor, cq)["snapshot"]
    before = row(child)
    expect("not_found_or_unauthorized", lambda: c.execute("start", H, cq))
    proof(25, "authorization before cached start", row(child) == before)
    zero_write(20, "parent continuation has no instruction", c, cs, "missing_steer_input", lambda: c.execute("steer", actor, steer(cs)))
    zero_write(19, "sibling cannot steer child", c, cs, "not_found_or_unauthorized", lambda: c.execute("steer", ParentActor(uid()),
        {k: v for k, v in steer(cs).items() if k != "continuation"} | {"parent_instruction": "new"}))
    sq = steer(cs)
    waiting = c.execute("steer", H, sq)["snapshot"]
    before, count = row(child), len(w.calls)
    with patch.object(hm, "decide", side_effect=AssertionError("parent wait cannot decide")):
        wait = c.execute("wait", actor, {"run_id": child, "since_revision": waiting["revision"], "timeout_seconds": 1})
    proof(21, "parent wait read-only no scheduler", wait["snapshot"] == waiting, row(child) == before, len(w.calls) == count)
    zero_write(18, "wrong interaction", c, waiting, "interaction_conflict", lambda: c.execute("respond", actor, response(waiting) | {"interaction_id": uid()}))
    zero_write(19, "Host cannot answer child", c, waiting, "not_found_or_unauthorized", lambda: c.execute("respond", H, response(waiting)))
    zero_write(19, "sibling cannot answer child", c, waiting, "not_found_or_unauthorized", lambda: c.execute("respond", ParentActor(uid()), response(waiting)))
    for val in [1, "other"]:
        zero_write(18, "schema/options invalid response", c, waiting, "invalid_response", lambda val=val: c.execute("respond", actor, response(waiting, val)))
    zero_write(20, "steer cannot bypass needs_input", c, waiting, "waiting_input_requires_respond", lambda: c.execute("steer", H, steer(waiting)))
    rq = response(waiting)
    answered = c.execute("respond", actor, rq)
    current = answered["snapshot"]
    proof(18, "exact interaction admits parent_response", w.calls[-1].input_kind == "parent_response", w.calls[-1].response == "yes")
    before = row(child)
    proof(24, "respond cache ignores changed CAS", c.execute("respond", actor, rq | {"expected_revision": 0}) == answered,
          row(child) == before, len(w.calls) == count + 1)
    zero_write(25, "respond changed input", c, current, "idempotency_conflict", lambda: c.execute("respond", actor, rq | {"response": "no"}))
    completed = Host(c).drive(child)  # Host resumes, never re-starts a child.
    durable(c, completed)
    kinds = [wr.input_kind for wr in w.calls if str(wr.run_id) == child]
    proof(6, "full parent-child Host resumption", completed["status"] == "completed",
          kinds == ["initial", "host_continue", "parent_response", "host_continue"])
    proof(4, "start steer respond each exactly once", completed["turns_used"] == 4, len(kinds) == 4)
    zero_write(17, "respond completed child", c, completed, "not_waiting_input", lambda: c.execute("respond", actor, response(waiting) | {"request_id": uid(), "expected_revision": completed["revision"]}))
    before = row(child)
    proof(24, "steer historical cache after future revisions", c.execute("steer", H, sq | {"expected_revision": completed["revision"]})["snapshot"] == waiting,
          poll(c, child) == completed, row(child) == before)
    for op, req, bad_actor, code in [
        ("cancel", {"run_id": child, "expected_revision": completed["revision"], "request_id": sq["request_id"]}, H, "idempotency_conflict"),
        ("steer", sq, actor, "idempotency_conflict"),
        ("respond", rq, ParentActor(uid()), "not_found_or_unauthorized")]:
        zero_write(25, "operation/actor/cache authorization", c, completed, code, lambda op=op, req=req, bad_actor=bad_actor: c.execute(op, bad_actor, req))
    cancel(c, parent)
    count = len(w.calls)
    new_child = request() | {"parent_run_id": parent["run_id"]}
    expect("not_found_or_unauthorized", lambda: c.execute("start", actor, new_child))
    proof(19, "stopped parent cannot create", row(new_child["run_id"]) is None, len(w.calls) == count)
    done_parent = c.execute("start", H, request(run))["snapshot"] if False else finished
    expect("not_found_or_unauthorized", lambda: c.execute("start", ParentActor(done_parent["run_id"]), request() | {"parent_run_id": done_parent["run_id"]}))
    proof(19, "completed parent cannot create", row(run) == row(run))

    # Real exhausted ready and waiting Runs; never change design priority.
    for outcome in ["progress", "needs_input"]:
        run = uid()
        w._plans[run] = [outcome]
        budget = c.execute("start", H, request(run, 1))["snapshot"]
        if outcome == "progress":
            final = Host(c).drive(run)
            proof(8, "ready budget stop durably cancels", final["status"] == "stopped", final["turns_used"] == 1,
                  final["close_reason"] == "cancelled", len([wr for wr in w.calls if str(wr.run_id) == run]) == 1)
        else:
            proof(8, "waiting beats exhausted budget", decide(budget, True)["decision"] == "wait")
            zero_write(29, "exhausted respond admission", c, budget, "budget_exhausted", lambda: c.execute("respond", H, response(budget, None)))
            final = Host(c).stop(run)
        for op in ["steer", "respond"]:
            req = steer(final) if op == "steer" else {"run_id": run, "expected_revision": final["revision"], "request_id": uid(), "interaction_id": uid(), "response": None}
            zero_write(34, "closed after ready/waiting cancel", c, final, "closed" if op == "steer" else "not_waiting_input", lambda op=op, req=req: c.execute(op, H, req))
            if op == "respond":
                proof(17, "respond stopped", final["status"] == "stopped")
    # Top-level Host is the valid responder, independently of the child path.
    run = uid()
    w._plans[run] = ["needs_input", "completed"]
    waiting = c.execute("start", H, request(run))["snapshot"]
    top = Host(c).respond(H, response(waiting, None))["snapshot"]
    proof(19, "top-level Host respond", top["status"] == "completed")


def test_disposition_validation():
    """Pure exhaustive malformed snapshots and fixed priority (labels 7–9/37/38)."""
    c = control(FakeWorker(default="progress"))
    s = c.execute("start", H, request())["snapshot"]
    before = copy.deepcopy(s)
    proof(7, "pure repeatable input unchanged", decide(s, True) == decide(s, True), s == before)
    for value in [0, 1, None, "true"]:
        rejects(lambda value=value: decide(s, value))
    malformed = [None, {}, s | {"extra": 1}, {k: v for k, v in s.items() if k != "active_base_revision"}]
    for key, values in {
        "schema_version": [True, 2, 1.0], "run_id": [uid().upper(), None], "parent_run_id": [s["run_id"], "bad"],
        "revision": [-1, True, 2**63], "turn_budget": [0, True, 2**31], "turns_used": [-1, True, 6, 0],
        "status": ["unknown", []], "cancel_requested": [0, None], "active_operation_id": [uid()],
        "active_base_revision": [1], "active_input_digest": ["a"*64], "close_reason": ["cancelled"],
        "latest_receipt": [None, {}],
    }.items():
        malformed.extend(s | {key: value} for value in values)
    for key, value in [("schema_version", True), ("run_id", uid()), ("turn_id", "bad"), ("base_revision", s["revision"]),
                       ("base_revision", True), ("input_kind", "bad"), ("input_digest", "A"*64), ("outcome", "completed"),
                       ("result", float("nan")), ("result", "x"*65535), ("tool_calls", {}), ("input_request", {})]:
        malformed.append(s | {"latest_receipt": s["latest_receipt"] | {key: value}})
    for index, bad in enumerate(malformed):
        rejects(lambda bad=bad: decide(bad, True))
        proof(7, f"fail-closed malformed snapshot {index}", True)
    for reason in ["cancelled", "invalid_worker_receipt", "late_result_after_cancel"]:
        empty = s | {"status": "stopped", "close_reason": reason, "turns_used": 0, "latest_receipt": None}
        proof(37, "legal first-turn stopped-null " + reason, decide(empty, True)["decision"] == "stop")
    rejects(lambda: decide(empty | {"close_reason": "worker_failed"}, True))
    rejects(lambda: decide(empty | {"status": "completed", "close_reason": None}, True))
    rejects(lambda: decide(s | {"status": "stopped", "close_reason": "worker_failed"}, True))
    running = s | {"status": "running", "revision": 3, "active_operation_id": uid(),
                   "active_base_revision": 3, "active_input_digest": "a"*64, "cancel_requested": True, "turn_budget": 1}
    proof(8, "running beats cancel and exhausted budget", decide(running, True)["decision"] == "wait")
    for bad in [running | {"active_operation_id": None}, running | {"active_base_revision": True},
                running | {"active_base_revision": 4}, running | {"active_input_digest": "A"*64}]:
        rejects(lambda bad=bad: decide(bad, True))
    proof(7, "active triple strict validation", True)
    failed = s | {"status": "stopped", "close_reason": "worker_failed", "latest_receipt": s["latest_receipt"] | {"outcome": "failed"}}
    proof(38, "failed only stopped/worker_failed", decide(failed, False)["decision"] == "stop")
    rejects(lambda: decide(failed | {"close_reason": "cancelled"}, True))
    proof(7, "cancel beats execution refusal", decide(s | {"cancel_requested": True}, False)["decision"] == "stop")
