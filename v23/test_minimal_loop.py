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
    # Positive ParentActor instruction steer, independent of Host continuation.
    instructed_child = uid()
    instructed = c.execute("start", actor, request(instructed_child) | {"parent_run_id": parent["run_id"]})["snapshot"]
    pq = {"run_id": instructed_child, "expected_revision": instructed["revision"],
          "request_id": uid(), "parent_instruction": "take the parent-directed branch"}
    count = len(w.calls)
    directed = c.execute("steer", actor, pq)
    ds = directed["snapshot"]
    audit = durable(c, ds)
    wr = w.calls[-1]
    proof(19, "ParentActor instruction steer durable", len(w.calls) == count + 1,
          wr.input_kind == "parent_instruction", wr.instruction == pq["parent_instruction"],
          wr.response is None, wr.continuation is False, ds["status"] == "ready",
          ds["turns_used"] == 2, ds["revision"] == instructed["revision"] + 2,
          ds["latest_receipt"]["input_kind"] == "parent_instruction",
          ds["latest_receipt"]["input_digest"] == wr.input_digest,
          audit["op_cache"][pq["request_id"]]["state"] == "done",
          audit["op_cache"][pq["request_id"]]["response"] == directed)
    before = row(instructed_child)
    proof(24, "parent_instruction same-ID replay no Worker", c.execute("steer", actor, pq | {"expected_revision": 0}) == directed,
          row(instructed_child) == before, len(w.calls) == count + 1)
    zero_write(25, "parent_instruction changed-instruction conflict", c, ds, "idempotency_conflict",
               lambda: c.execute("steer", actor, pq | {"parent_instruction": "different branch"}))
    proof(4, "parent_instruction exactly one admitted Worker", len(w.calls) == count + 1)

    cancel(c, parent)
    count = len(w.calls)
    new_child = request() | {"parent_run_id": parent["run_id"]}
    expect("not_found_or_unauthorized", lambda: c.execute("start", actor, new_child))
    proof(19, "stopped parent cannot create", row(new_child["run_id"]) is None, len(w.calls) == count)
    new_child = request() | {"parent_run_id": finished["run_id"]}
    before, count = row(finished["run_id"]), len(w.calls)
    expect("not_found_or_unauthorized", lambda: c.execute("start", ParentActor(finished["run_id"]), new_child))
    proof(19, "completed parent cannot create", row(new_child["run_id"]) is None,
          row(finished["run_id"]) == before, len(w.calls) == count)

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


class CommitBarrier(Control):
    def __init__(self, *args, phase="T2", **kwargs):
        self.phase = phase
        self.at_commit, self.release_commit = threading.Event(), threading.Event()
        self.armed = False
        super().__init__(*args, **kwargs)

    def _commit(self, conn, phase):
        if self.armed and phase == self.phase:
            self.armed = False
            self.at_commit.set()
            barrier(self.release_commit, phase + " commit")
        super()._commit(conn, phase)


def locked_row(run_id):
    try:
        query("SELECT * FROM v23_runs WHERE run_id=%s FOR UPDATE NOWAIT", (run_id,))
    except psycopg2.errors.LockNotAvailable:
        return True
    return False


def assert_idle(c, listener=None):
    conn = c._runtime.conn
    assert conn.get_transaction_status() == TRANSACTION_STATUS_IDLE
    pids = [conn.get_backend_pid()]
    if listener is not None:
        assert listener.get_transaction_status() == TRANSACTION_STATUS_IDLE
        pids.append(listener.get_backend_pid())
    states = query(
        "SELECT pid, state, xact_start, usename, client_addr FROM pg_stat_activity WHERE pid=ANY(%s)", (pids,))
    assert len(states) == len(pids)
    assert all(state == "idle" and xact is None and user == "v23_control" and addr is None for _, state, xact, user, addr in states), states


def test_pending_cancel_and_competition():
    """Blocking T1/Worker/T2, owner join, two CAS consumers, both lock orders."""
    w = Blocking(default="progress")
    c = control(w, cls=CommitBarrier, phase="cancel")
    q = request()
    task = Task(lambda: c.execute("start", H, q))
    barrier(w.enter)
    try:
        s = poll(c, q["run_id"])
        assert_idle(c)
        a = durable(c, s)
        entry = a["op_cache"][q["request_id"]]
        proof(2, "confirmed admission visible during Worker", s["status"] == "running", s["revision"] == 1,
              entry["state"] == "pending", entry["response"] is None, not locked_row(s["run_id"]))
        normalized = c._request("start", q)
        expected_input = {"input_kind": "initial", "instruction": "one", "response": None, "continuation": False}
        proof(26, "pending independent canonical digests", entry["request_digest"] == c._request_digest("start", H, normalized),
              entry["input_digest"] == hashlib.sha256(cm._canonical(expected_input)).hexdigest(),
              entry["input_digest"] == s["active_input_digest"], entry["input_digest"] != entry["request_digest"], entry["admission_revision"] == 1)
        equivalent = make_dsn(**(parse_dsn(DSN) | {"host": parse_dsn(DSN)["host"] + "/.", "port": str(c.db_identity[1])}))
        sibling = Control(equivalent, FakeWorker())
        CONTROLS.append(sibling)
        proof(35, "same-process same db_identity shares healthy runtime", sibling._runtime is c._runtime, poll(sibling, s["run_id"]) == s,
              row(s["run_id"]) == a)
        incompatible = make_dsn(**(parse_dsn(DSN) | {"options": "-c statement_timeout=1234"}))
        expect("control_runtime_incompatible", lambda: Control(incompatible, FakeWorker()))
        proof(49, "incompatible sharing rejected without recovery", row(s["run_id"]) == a)
        joined = control(cls=JoinProbe)
        duplicate = Task(lambda: joined.execute("start", H, q))
        barrier(joined.joined)
        assert_idle(c)
        proof(16, "owner join outside transaction and runtime lock", poll(sibling, s["run_id"]) == s, not locked_row(s["run_id"]))
        zero_write(17, "respond running", c, s, "not_waiting_input", lambda: c.execute("respond", H, {
            "run_id": s["run_id"], "request_id": uid(), "expected_revision": 1, "interaction_id": uid(), "response": None}))
        zero_write(25, "pending same ID different input", c, s, "idempotency_conflict", lambda: c.execute("start", H, q | {"instruction": "other"}))
        zero_write(25, "pending same ID different op", c, s, "idempotency_conflict", lambda: c.execute("cancel", H, {
            "run_id": s["run_id"], "request_id": q["request_id"], "expected_revision": 1}))
        zero_write(25, "pending unauthorized actor with cached ID", c, s, "not_found_or_unauthorized", lambda: c.execute("start", ParentActor(uid()), q))
        cq = {"run_id": s["run_id"], "expected_revision": 1, "request_id": uid()}
        c.armed = True
        ct = Task(lambda: c.execute("cancel", H, cq))
        barrier(c.at_commit)
        proof(33, "cancel actual row lock held before commit", locked_row(s["run_id"]), row(s["run_id"])["revision"] == 1)
        c.release_commit.set()
        cancelled = ct.finish()
        durable(c, cancelled["snapshot"])
        proof(31, "running cancel only durable request no receipt", cancelled["snapshot"]["status"] == "running",
              cancelled["snapshot"]["cancel_requested"] is True, cancelled["snapshot"]["latest_receipt"] is None,
              cancelled["snapshot"]["turns_used"] == 0, cancelled["snapshot"]["active_operation_id"] == q["request_id"])
        before = row(s["run_id"])
        proof(28, "cancel exact cache with new CAS", c.execute("cancel", H, cq | {"expected_revision": 0}) == cancelled,
              row(s["run_id"]) == before, before["op_cache"][cq["request_id"]]["state"] == "done")
        no_op = c.execute("cancel", H, cq | {"request_id": uid(), "expected_revision": 2})
        proof(28, "new ID cancel-requested genuinely zero write", no_op["snapshot"] == cancelled["snapshot"], row(s["run_id"]) == before)
        zero_write(28, "stale CAS still precedes no-op", c, cancelled["snapshot"], "revision_conflict", lambda: c.execute("cancel", H, cq | {"request_id": uid()}))
        w.release.set()
        final = task.finish()
        proof(24, "pending exact retry joins same receipt", duplicate.finish() == final, len(w.calls) == 1)
        fs = final["snapshot"]
        durable(c, fs)
        proof(32, "cancel commit first discards first-turn receipt", fs["status"] == "stopped", fs["close_reason"] == "late_result_after_cancel",
              fs["turns_used"] == 0, fs["latest_receipt"] is None, fs["revision"] == 3)
        proof(33, "cancel first then T2 serializes", row(s["run_id"])["op_cache"][q["request_id"]]["state"] == "done")
        before = row(s["run_id"])
        proof(28, "cancel historical receipt immutable after close", c.execute("cancel", H, cq) == cancelled, poll(c, s["run_id"]) == fs)
        cancel(c, fs)
        proof(28, "closed cancel no cache growth", row(s["run_id"]) == before)
        proof(4, "join/cancel never replay Worker", len(w.calls) == 1)
        assert_idle(c)
        proof(16, "T2 transaction committed and idle", True)
    finally:
        c.release_commit.set()
        w.release.set()
        task.thread.join(DEADLINE)

    # Two consumers actually arrive together with the same observed revision.
    w = FakeWorker(default="progress")
    c = control(w, cls=CommitBarrier)
    q = request()
    ready = c.execute("start", H, q)["snapshot"]
    entered, release = threading.Event(), threading.Event()
    original = w.run
    def block(wr):
        entered.set()
        barrier(release)
        return original(wr)
    w.run = block
    rendezvous = threading.Barrier(3)
    def consume(req):
        rendezvous.wait(DEADLINE)
        return c.execute("steer", H, req)
    t1, t2 = Task(lambda: consume(steer(ready))), Task(lambda: consume(steer(ready)))
    rendezvous.wait(DEADLINE)
    barrier(entered)
    try:
        # Exactly one loser can finish while the admitted Worker is still blocked.
        end = time.monotonic() + DEADLINE
        while t1.thread.is_alive() and t2.thread.is_alive() and time.monotonic() < end:
            threading.Event().wait(0.005)
        loser = t1 if not t1.thread.is_alive() else t2
        loser.finish("revision_conflict")
        c.armed = True
        release.set()
        barrier(c.at_commit)
        proof(33, "T2 actual row lock held before commit", locked_row(ready["run_id"]))
        c.release_commit.set()
        winner = t2 if loser is t1 else t1
        result = winner.finish()["snapshot"]
        durable(c, result)
        proof(23, "two simultaneous consumers one admission", len(w.calls) == 2, result["turns_used"] == 2, result["revision"] == 4)
        zero_write(33, "T2 first stale cancel conflicts", c, result, "revision_conflict", lambda: cancel(c, ready))
        closed = cancel(c, result)["snapshot"]
        durable(c, closed)
        proof(33, "T2 first then fresh cancel preserves accepted receipt", closed["latest_receipt"] == result["latest_receipt"],
              closed["turns_used"] == 2, closed["close_reason"] == "cancelled", closed["revision"] == 5)
    finally:
        release.set()
        c.release_commit.set()
        t1.thread.join(DEADLINE)
        t2.thread.join(DEADLINE)
    # T2 completed first: cancel must never replace completed.
    w.run = original
    w.default = "completed"
    completed = c.execute("start", H, request())["snapshot"]
    before = row(completed["run_id"])
    proof(33, "completed T2 wins against later cancel", cancel(c, completed)["snapshot"] == completed, row(completed["run_id"]) == before)


class WaitProbe(Control):
    def __init__(self, *args, hook="second", **kwargs):
        self.hook = hook
        self.at_wait, self.release_wait = threading.Event(), threading.Event()
        self.reads = 0
        self.listener = None
        super().__init__(*args, **kwargs)

    def _before_listen(self):
        if self.hook == "before":
            self.at_wait.set()
            barrier(self.release_wait, "before LISTEN")

    def _after_listen(self, listener):
        self.listener = listener
        assert_idle(self, listener)

    def _read(self, *args):
        s = super()._read(*args)
        self.reads += 1
        if self.hook == "second" and self.reads == 2:
            self.at_wait.set()
            barrier(self.release_wait, "wait second read")
        return s


def notify(payload):
    # Notifications must really commit, unlike the audit helper's short reads.
    conn = psycopg2.connect(ADMIN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_notify(%s,%s)", (cm.CHANNEL, json.dumps(payload)))
    finally:
        conn.close()


def test_waits_and_notifications():
    """Real read/LISTEN windows, lost/merged/forged/other-Run notifications."""
    c = control(FakeWorker(default="progress"))
    for scenario in ["race", "lost", "merged", "forged", "other_run"]:
        s = c.execute("start", H, request())["snapshot"]
        waiter = control(cls=WaitProbe, hook="before" if scenario == "race" else "second")
        before = row(s["run_id"])
        started = time.monotonic()
        task = Task(lambda: waiter.execute("wait", H, {"run_id": s["run_id"], "since_revision": s["revision"], "timeout_seconds": 0.12}))
        barrier(waiter.at_wait)
        try:
            assert_idle(c, waiter.listener)
            if scenario == "race":
                latest = cancel(c, s)["snapshot"]
            elif scenario in {"lost", "merged"}:
                with patch.object(c, "_notify", return_value=None):
                    if scenario == "merged":
                        latest = c.execute("steer", H, steer(s))["snapshot"]
                        latest = cancel(c, latest)["snapshot"]
                    else:
                        latest = cancel(c, s)["snapshot"]
            else:
                latest = s
                if scenario == "other_run":
                    c.execute("start", H, request())  # real other-Run commits/notifications
                else:
                    notify({"run_id": s["run_id"], "revision": 999999,
                            "status": "completed", "result": "forged"})
            if scenario == "merged":
                notify({"run_id": s["run_id"], "revision": 0})
            waiter.release_wait.set()
            waited = task.finish()
            assert waited["snapshot"] == poll(c, s["run_id"]) == latest
            assert waiter.listener.closed
            if scenario == "race":
                proof(13, "commit between read and LISTEN discovered by reread", waited["wait_result"] == "changed", waiter.reads >= 3)
            elif scenario == "lost":
                proof(12, "positive timeout rereads newer revision", waiter.reads >= 3, latest["revision"] > s["revision"],
                      time.monotonic() - started >= 0.12, waited["wait_result"] == "changed")
                proof(14, "suppressed notify still converges", durable(c, latest)["revision"] == latest["revision"])
            elif scenario == "merged":
                proof(15, "multiple committed revisions one wake returns final DB state", waited["wait_result"] == "changed",
                      latest["revision"] == s["revision"] + 3, waiter.reads >= 3)
            else:
                proof(11, "payload cannot construct state " + scenario, waited["snapshot"] == s,
                      waited["wait_result"] == "timed_out", waiter.reads >= 4, row(s["run_id"]) == before)
            proof(16, "LISTEN autocommit and listener closed " + scenario, waiter.listener.closed)
        finally:
            waiter.release_wait.set()
            task.thread.join(DEADLINE)
        durable(c, latest)
    # Notify failure occurs after commit, never causes retry/write replay.
    s = c.execute("start", H, request())["snapshot"]
    before = len(c.worker.calls)
    with patch.object(c, "_notify", side_effect=RuntimeError("lost hint")):
        latest = c.execute("steer", H, steer(s))["snapshot"]
    assert_idle(c)
    proof(16, "post-commit notifier failure no remutation", latest["revision"] == s["revision"] + 2,
          len(c.worker.calls) == before + 1, durable(c, latest)["turns_used"] == 2)


def test_commit_faults_and_owner_loss():
    """T1/T2 known rollback, healthy/dead ack loss, original-owner-only retry."""
    close_controls()
    for sqlstate in ["40001", "40P01"]:
        c = control(cls=Fault, phase="T1", mode="rollback", sqlstate=sqlstate)
        q = request()
        exc = rejects(lambda: c.execute("start", H, q), psycopg2.Error)
        proof(27, "T1 known rollback " + sqlstate, exc.pgcode == sqlstate, row(q["run_id"]) is None, not c.worker.calls)
        first = c.execute("start", H, q)
        proof(4, "T1 rollback permits same-ID admission once", len(c.worker.calls) == 1, first["snapshot"]["revision"] == 2)
        durable(c, first["snapshot"])
        c.close()

    for phase, mode, sqlstate in [("T2", "rollback", "40001"), ("T2", "rollback", "40P01"),
                                  ("T2", "ack", "40001"), ("T2", "dead_after", "40001"),
                                  ("T1", "ack", "40001")]:
        c = control(cls=Fault, phase=phase, mode=mode, sqlstate=sqlstate)
        q = request()
        receipt_objects = []
        original = c._finalize
        def traced(*args):
            receipt_objects.append(args[3])
            return original(*args)
        c._finalize = traced
        first = c.execute("start", H, q)
        s = first["snapshot"]
        audit = durable(c, s)
        entry = audit["op_cache"][q["request_id"]]
        before = copy.deepcopy(audit)
        proof(27, phase + " " + mode + " " + sqlstate, c.execute("start", H, q) == first,
              row(q["run_id"]) == before, entry["state"] == ("recovered" if phase == "T1" else "done"),
              len(c.worker.calls) == (0 if phase == "T1" else 1), s["revision"] == 2,
              len({pid for _, pid in c.commits}) == 1)
        if phase == "T1":
            proof(26, "unknown T1 commit closes pending never supplements Worker", first["outcome"] == "recovered_orphan",
                  first["error_code"] == "owner_lost", s["turns_used"] == 0, s["latest_receipt"] is None,
                  entry["error_code"] == "owner_lost", entry["admission_revision"] == 1)
        else:
            proof(30, "owner same frozen receipt " + mode + sqlstate,
                  len(receipt_objects) == (2 if mode == "rollback" else 1),
                  all(value is receipt_objects[0] for value in receipt_objects), len(c.worker.calls) == 1)
        if mode == "dead_after":
            assert c._runtime.lost
            fresh = control()
            proof(27, "dead fence reads committed done no new generation T2", fresh.execute("start", H, q) == first,
                  not fresh.worker.calls, row(q["run_id"]) == before)
            fresh.close()
        c.close()

    # T1 already confirmed, but calling thread still awaits the same original owner.
    w = Blocking()
    c = control(w)
    q = request()
    task = Task(lambda: c.execute("start", H, q))
    barrier(w.enter)
    j = control(cls=JoinProbe)
    retry = Task(lambda: j.execute("start", H, q))
    barrier(j.joined)
    w.release.set()
    first = task.finish()
    proof(27, "confirmed T1 retry joins live owner", retry.finish() == first, len(w.calls) == 1,
          row(q["run_id"])["op_cache"][q["request_id"]]["state"] == "done")
    close_controls()

    # Real caller transport loss while confirmed T1's original Worker still runs.
    class CallerLoss(JoinProbe):
        def __init__(self, *args, **kwargs):
            self.original_task = None
            self.requests = []
            super().__init__(*args, **kwargs)

        def execute(self, op=None, actor=None, request=None):
            if op == "start":
                self.requests.append(copy.deepcopy(request))
                if self.original_task is None:
                    self.original_task = Task(lambda: super(CallerLoss, self).execute(op, actor, request))
                    barrier(self.worker.enter)
                    raise TimeoutError("caller lost confirmed admission acknowledgement")
            return super().execute(op, actor, request)
    w = Blocking(default="completed")
    c = control(w, cls=CallerLoss)
    q = request()
    driver = Task(lambda: Host(c).drive(q["run_id"], instruction=q["instruction"],
                                       turn_budget=q["turn_budget"], run_request_id=q["request_id"]))
    barrier(c.joined)
    try:
        assert_idle(c)
        proof(27, "confirmed T1 ack loss Host retries join pending original", len(c.requests) == 2,
              c.requests[0] == c.requests[1], row(q["run_id"])["op_cache"][q["request_id"]]["state"] == "pending")
        w.release.set()
        completed = driver.finish()
        c.original_task.finish()
        proof(4, "confirmed T1 lost caller ack exactly one Worker", len(w.calls) == 1, completed["status"] == "completed",
              completed["turns_used"] == 1, completed["revision"] == 2)
    finally:
        w.release.set()
        driver.thread.join(DEADLINE)
    close_controls()

    # T2 pending after fence dies before commit: new generation recovers, not replays.
    c = control(cls=Fault, phase="T2", mode="dead_before")
    q = request()
    expect("control_runtime_lost", lambda: c.execute("start", H, q))
    pending = row(q["run_id"])
    proof(27, "T2 fence death leaves pending not accepted", pending["status"] == "running", pending["turns_used"] == 0,
          pending["op_cache"][q["request_id"]]["state"] == "pending", len(c.worker.calls) == 1)
    new = control()
    recovered = new.execute("start", H, q)
    proof(26, "new fence pending-to-recovered exact replay", recovered["outcome"] == "recovered_orphan", recovered["error_code"] == "owner_lost",
          recovered["snapshot"]["revision"] == 2, new.execute("start", H, q) == recovered, c.execute("start", H, q) == recovered,
          not new.worker.calls)
    close_controls()

    # Only original owner's thread/generation may submit a pending T2.
    w = Blocking(default="progress")
    c = control(w)
    q = request()
    task = Task(lambda: c.execute("start", H, q))
    barrier(w.enter)
    try:
        with c._runtime.mutex, cm._owners_lock:
            owner = cm._owners[c._owner_key(q["run_id"], q["request_id"])]
        wr = owner.worker_request
        receipt = TurnReceipt(1, wr.turn_id, wr.run_id, wr.base_revision, wr.input_kind, wr.input_digest, "completed", {})
        before = row(q["run_id"])
        expect("active_operation_conflict", lambda: c._finalize("start", q, owner, receipt, None))
        proof(30, "foreign-thread T2 rejected zero write", row(q["run_id"]) == before)
        with c._runtime.mutex, cm._owners_lock:
            cm._owners.pop(c._owner_key(q["run_id"], q["request_id"]))
        recovered = c.execute("start", H, q)
        before = row(q["run_id"])
        proof(35, "healthy fenced owner disappearance recovers once", recovered["outcome"] == "recovered_orphan",
              recovered["snapshot"]["close_reason"] == "cancelled", recovered["snapshot"]["cancel_requested"],
              recovered["snapshot"]["turns_used"] == 0, recovered["snapshot"]["latest_receipt"] is None)
        proof(26, "recovered immutable exact receipt", c.execute("start", H, q) == recovered, row(q["run_id"]) == before)
        for op, req, actor, code in [
            ("start", q | {"instruction": "changed"}, H, "idempotency_conflict"),
            ("cancel", {"run_id": q["run_id"], "request_id": q["request_id"], "expected_revision": 2}, H, "idempotency_conflict"),
            ("start", q, ParentActor(uid()), "not_found_or_unauthorized")]:
            expect(code, lambda op=op, req=req, actor=actor: c.execute(op, actor, req))
            proof(26, "recovered operation/input/authority match", row(q["run_id"]) == before)
        w.release.set()
        proof(35, "old late receipt cannot reopen recovered Run", task.finish() == recovered, row(q["run_id"]) == before, len(w.calls) == 1)
    finally:
        w.release.set()
        task.thread.join(DEADLINE)
    close_controls()

    # Authorized Host/Parent actor conflicts during a pending child continuation.
    w = FakeWorker(default="progress")
    c = control(w)
    parent = c.execute("start", H, request())["snapshot"]
    cq = request() | {"parent_run_id": parent["run_id"]}
    actor = ParentActor(parent["run_id"])
    child = c.execute("start", actor, cq)["snapshot"]
    enter, release = threading.Event(), threading.Event()
    original = w.run
    def block_child(wr):
        enter.set()
        barrier(release)
        return original(wr)
    w.run = block_child
    sq = steer(child)
    task = Task(lambda: c.execute("steer", H, sq))
    barrier(enter)
    try:
        running = poll(c, child["run_id"])
        zero_write(25, "pending authorized actor changed", c, running, "idempotency_conflict",
                   lambda: c.execute("steer", actor, sq))
        zero_write(25, "pending continuation becomes parent instruction", c, running, "idempotency_conflict",
                   lambda: c.execute("steer", actor, {k: v for k, v in sq.items() if k != "continuation"} | {"parent_instruction": "different"}))
        release.set()
        proof(4, "pending conflict never calls another Worker", task.finish()["snapshot"]["turns_used"] == 2,
              len([wr for wr in w.calls if str(wr.run_id) == child["run_id"]]) == 2)
    finally:
        release.set()
        task.thread.join(DEADLINE)
    close_controls()

    # Old Python/Worker remains alive after its real backend is killed.
    w = Blocking(default="completed")
    c = control(w)
    q = request()
    task = Task(lambda: c.execute("start", H, q))
    barrier(w.enter)
    try:
        old_pid = c._runtime.conn.get_backend_pid()
        assert query("SELECT pg_terminate_backend(%s)", (old_pid,))[0][0]
        # Constructing a new Control detects dead session, obtains a new fence,
        # and performs recovery while the old Worker is provably still blocked.
        new = control()
        recovered = new.execute("start", H, q)
        before = row(q["run_id"])
        proof(35, "new generation fences still-live old Worker", new._runtime is not c._runtime,
              recovered["outcome"] == "recovered_orphan", task.thread.is_alive(), not w.release.is_set())
        w.release.set()
        task.finish("control_runtime_lost")
        proof(49, "killed old fence T2 has no durable writes", row(q["run_id"]) == before, c.execute("start", H, q) == recovered,
              not new.worker.calls, len(w.calls) == 1)
    finally:
        w.release.set()
        task.thread.join(DEADLINE)
    close_controls()


def wait_file(path, process):
    deadline = time.monotonic() + DEADLINE
    while not path.exists():
        if process.poll() is not None:
            out, err = process.communicate()
            raise AssertionError(f"child exited before barrier: {process.returncode}: {out} {err}")
        if time.monotonic() >= deadline:
            raise AssertionError("child file barrier deadline")
        threading.Event().wait(0.005)
    return json.loads(path.read_text())


def child_start(mode, directory):
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--fixture", mode, str(directory)],
                               cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    CHILDREN.append(process)
    return process


def child_finish(process):
    out, err = process.communicate(timeout=DEADLINE)
    if process.returncode:
        raise AssertionError(f"child failure {process.returncode}: {out} {err}")
    return json.loads(out.strip())


def fixture(mode, directory):
    """Independent interpreter: file-coordinated pending/recovery/fence fixtures."""
    global DSN, ADMIN
    config = json.loads((directory / "config.json").read_text())
    DSN, ADMIN = config["dsn"], config["admin"]
    if mode == "busy":
        try:
            c = Control(DSN, FakeWorker())
        except ControlError as exc:
            assert exc.code == "control_runtime_busy"
            print(json.dumps({"code": exc.code, "tables": query("SELECT count(*) FROM v23_runs")[0][0]}))
            return 0
        c.close()
        raise AssertionError("competing process acquired active fence")
    if mode == "recover":
        w = FakeWorker()
        with Control(DSN, w) as c:
            values = [c.execute("start" if index == 0 else "steer", H, req) for index, req in enumerate(config["pending"])]
            assert not w.calls
            print(json.dumps({"values": values, "worker_calls": len(w.calls), "pid": os.getpid()}))
        return 0
    if mode != "pending":
        raise AssertionError("unknown fixture")
    w = FakeWorker(default="progress")
    c = Control(DSN, w)
    # Second pending Run has an accepted prior receipt; restart must preserve it.
    prior = c.execute("start", H, config["initial_second"])["snapshot"]
    assert config["pending"][1]["expected_revision"] == prior["revision"]
    original = w.run
    def block(wr):
        marker = directory / ("worker-" + str(wr.run_id) + ".json")
        marker.write_text(json.dumps({"run_id": str(wr.run_id), "pid": os.getpid(), "base_revision": wr.base_revision,
                                      "fence_pid": c._runtime.conn.get_backend_pid()}))
        deadline = time.monotonic() + 30
        while not (directory / "release").exists():
            if time.monotonic() >= deadline:
                raise AssertionError("fixture release deadline")
            threading.Event().wait(0.01)
        return original(wr)
    w.run = block
    tasks = [Task(lambda req=req, op=op: c.execute(op, H, req))
             for op, req in zip(["start", "steer"], config["pending"])]
    # Parent normally terminates us with both Workers still blocked. If released,
    # collect every thread exception and close normally; never hide a fixture error.
    for task in tasks:
        task.finish()
    c.close()
    return 0


def test_process_restart():
    """Actual process death, contender fence failure, new-process recovery of two Runs."""
    close_controls()
    with tempfile.TemporaryDirectory(prefix="v23-gate-") as raw:
        directory = Path(raw)
        q = request()
        second = request()
        sq = {"run_id": second["run_id"], "expected_revision": 2, "request_id": uid(), "continuation": True}
        config = {"dsn": DSN, "admin": ADMIN, "pending": [q, sq], "initial_second": second}
        (directory / "config.json").write_text(json.dumps(config))
        old = child_start("pending", directory)
        one = wait_file(directory / ("worker-" + q["run_id"] + ".json"), old)
        two = wait_file(directory / ("worker-" + second["run_id"] + ".json"), old)
        pending = [row(req["run_id"]) for req in [q, sq]]
        assert one["pid"] == two["pid"] != os.getpid()
        contender = child_finish(child_start("busy", directory))
        proof(35, "separate process fence loser no recovery", contender["code"] == "control_runtime_busy",
              [row(req["run_id"]) for req in [q, sq]] == pending, old.poll() is None)
        proof(49, "startup fence failure releases candidate backend", query(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND application_name='v23_control_fence'", (setup.DB,))[0][0] == 1)
        old.terminate()
        old.communicate(timeout=DEADLINE)
        assert old.returncode != 0  # intentional real process boundary, not a new instance
        result = child_finish(child_start("recover", directory))
        proof(36, "new process acquired fence and recovered all pending", result["pid"] != one["pid"], result["pid"] != os.getpid(),
              result["worker_calls"] == 0, len(result["values"]) == 2)
        c = control()
        for index, (op, req, original) in enumerate(zip(["start", "steer"], [q, sq], pending)):
            value = result["values"][index]
            s = value["snapshot"]
            a = durable(c, s)
            before = copy.deepcopy(a)
            proof(36, "recovery preserves turns/receipt " + str(index), s["status"] == "stopped", s["close_reason"] == "cancelled",
                  s["cancel_requested"] is True, s["revision"] == original["revision"] + 1,
                  s["turns_used"] == original["turns_used"], s["latest_receipt"] == original["latest_receipt"],
                  s["active_operation_id"] is None, a["op_cache"][req["request_id"]]["state"] == "recovered")
            proof(26, "recovered process exact receipt " + str(index), c.execute(op, H, req) == value,
                  c.execute(op, H, req) == value, row(req["run_id"]) == before, not c.worker.calls)
        close_controls()


class RawWorker(FakeWorker):
    """Test-only unvalidated public return, to exercise Control's DTO boundary."""
    def __init__(self, transform, *, prior=False):
        super().__init__()
        self.transform, self.prior = transform, prior

    def run(self, wr):
        wm.validate_request(wr)
        self.calls.append(wr)
        valid = TurnReceipt(1, wr.turn_id, wr.run_id, wr.base_revision, wr.input_kind, wr.input_digest,
                            "progress" if self.prior and len(self.calls) == 1 else "completed", {})
        if self.prior and len(self.calls) == 1:
            return valid
        return self.transform(valid)


def sized_record(size, index=1):
    record = {"call_id": index, "name": "echo", "input": None, "output": "", "error": None}
    record["output"] = "x" * (size - wm._json_bytes(record))
    assert wm._json_bytes(record) == size
    return record


def test_storage_safe_receipts():
    """Actual U+0000 (not literal backslash text) must never reach durable jsonb."""
    nul = "\x00"
    assert len(nul) == 1 and ord(nul) == 0 and nul != "\\x00"
    normal_call = {"call_id": 1, "name": "echo", "input": None, "output": None, "error": None}
    cases = [
        ("result actual NUL", lambda dto: replace(dto, result={"nested": [nul]})),
        ("result key actual NUL", lambda dto: replace(dto, result={nul: "value"})),
        ("input_request prompt actual NUL", lambda dto: replace(dto, outcome="needs_input",
            input_request={"interaction_id": uid(), "prompt": nul, "options": []})),
        ("input_request options actual NUL", lambda dto: replace(dto, outcome="needs_input",
            input_request={"interaction_id": uid(), "options": [{"value": nul}]})),
        ("result surrogate", lambda dto: replace(dto, result="\ud800")),
        ("result numeric overflow", lambda dto: replace(dto, result=10**131072)),
    ]
    for field in ["name", "input", "output"]:
        cases.append(("tool " + field + " actual NUL", lambda dto, field=field:
                      replace(dto, tool_calls=(normal_call | {field: nul},))))
    for prior_flag in [False, True]:
        for name, transform in cases:
            w = RawWorker(transform, prior=prior_flag)
            c = control(w)
            q = request()
            previous = c.execute("start", H, q)["snapshot"] if prior_flag else None
            op, req = ("steer", steer(previous)) if previous else ("start", q)
            error = expect("invalid_worker_receipt", lambda: c.execute(op, H, req))
            s = poll(c, q["run_id"])
            audit = durable(c, s)
            replay = expect("invalid_worker_receipt", lambda: c.execute(op, H, req))
            entry = audit["op_cache"][req["request_id"]]
            proof(37, name + "/prior=" + str(prior_flag), type(error) is type(replay) is WorkerContractError,
                  error.response == replay.response, s == error.response["snapshot"],
                  s["status"] == "stopped", s["close_reason"] == "invalid_worker_receipt",
                  s["latest_receipt"] == (previous["latest_receipt"] if previous else None),
                  s["turns_used"] == (1 if previous else 0),
                  s["revision"] == (previous["revision"] + 2 if previous else 2),
                  all(s[key] is None for key in ["active_operation_id", "active_base_revision", "active_input_digest"]),
                  entry["state"] == "done", entry["error_code"] == "invalid_worker_receipt",
                  row(q["run_id"]) == audit, len(w.calls) == (2 if previous else 1))
            c.close()

    # Literal escape-looking text remains legal and round-trips unchanged.
    literal = {"text": "\\x00", "unicode_escape_text": "\\u0000"}
    w = RawWorker(lambda dto: replace(dto, result=literal))
    c = control(w)
    q = request()
    accepted = c.execute("start", H, q)
    durable(c, accepted["snapshot"])
    proof(37, "literal backslash text is not NUL", accepted["snapshot"]["status"] == "completed",
          accepted["snapshot"]["latest_receipt"]["result"] == literal,
          c.execute("start", H, q) == accepted, len(w.calls) == 1)
    c.close()

    # Even a failure-marker name with unsafe characters is sanitized and bounded.
    marker = wm._failure_record(1, "bad" + nul + "\x01\ud800", b"null", "handler_exception")
    failure = wm.WorkerExecutionError("handler_exception", (marker,))
    w = RawWorker(lambda dto: (_ for _ in ()).throw(failure))
    c = control(w)
    q = request()
    error = expect("worker_failed", lambda: c.execute("start", H, q))
    s = error.response["snapshot"]
    audit = durable(c, s)
    replay = expect("worker_failed", lambda: c.execute("start", H, q))
    proof(38, "storage-safe execution failure marker durable no replay",
          s["close_reason"] == "worker_failed", s["latest_receipt"]["tool_calls"] == [marker],
          wm._json_bytes(marker) <= 512, wm._safe_text(marker["name"]),
          replay.response == error.response, row(q["run_id"]) == audit, len(w.calls) == 1)
    c.close()
    rejects(lambda: wm.WorkerExecutionError("handler_exception", (normal_call | {"output": nul},)), WorkerContractError)
    for value in [nul, {nul: 1}, "\ud800", 10**131072]:
        rejects(lambda value=value: cm._canonical(value), WorkerContractError)
    # Depth and node limits prevent unbounded validation before a durable write.
    nested = None
    for _ in range(130):
        nested = [nested]
    rejects(lambda: wm.storage_safe_json(nested), WorkerContractError)
    rejects(lambda: wm.storage_safe_json([None] * 100, limit=32), WorkerContractError)
    proof(39, "bounded storage-safe Worker/Control JSON boundary", True)


def test_json_text_controls():
    """Valid decoded controls survive instruction/parent answer and jsonb roundtrip."""
    for index, text in enumerate(["first\nsecond", "left\tright", "before\rafter",
                                  "other\x01\x7f\x85controls"]):
        assert wm._safe_text(text)
        key = "key:" + text
        value = {key: [text, {"nested": text}]}
        instruction = "initial:" + text
        parent_instruction = "parent:" + text
        run = uid()
        child = uid()
        iq = {"interaction_id": uid(), "prompt": text, "options": [value],
              "response_schema": {"type": "object", "required": [key]}}
        name = "echo:" + text
        tools = {name: FakeTool(name, lambda v: v)}
        plan = {"outcome": "completed", "result": value,
                "tool_calls": [{"name": name, "input": value}]}
        w = FakeWorker({run: [{"outcome": "progress", "result": value}],
                        child: ["progress", {"outcome": "needs_input", "result": value,
                                              "input_request": iq}, plan]}, tools=tools)
        c = control(w)
        q = request(run) | {"instruction": instruction}
        parent = c.execute("start", H, q)["snapshot"]
        durable(c, parent)
        proof(3, "multiline/control initial and result preserved " + str(index),
              w.calls[0].instruction == instruction, parent["latest_receipt"]["result"] == value,
              parent["status"] == "ready")
        actor = ParentActor(run)
        child_s = c.execute("start", actor, request(child) | {"parent_run_id": run})["snapshot"]
        sq = {"run_id": child, "expected_revision": child_s["revision"], "request_id": uid(),
              "parent_instruction": parent_instruction}
        if index == 0:
            zero_write(1, "actual NUL initial instruction rejected", c, parent, "invalid_request",
                       lambda: c.execute("start", H, q | {"instruction": "bad\x00input"}))
            zero_write(20, "actual NUL parent_instruction rejected", c, child_s, "invalid_request",
                       lambda: c.execute("steer", actor, sq | {"parent_instruction": "bad\x00input"}))
        directed = c.execute("steer", actor, sq)
        waiting = directed["snapshot"]
        durable(c, waiting)
        proof(19, "multiline/control parent_instruction and input_request preserved " + str(index),
              w.calls[-1].instruction == parent_instruction, w.calls[-1].input_kind == "parent_instruction",
              waiting["latest_receipt"]["input_request"] == iq, waiting["latest_receipt"]["result"] == value)
        rq = response(waiting, value)
        if index == 0:
            zero_write(18, "actual NUL response rejected before admission", c, waiting, "invalid_request",
                       lambda: c.execute("respond", actor, rq | {"response": {"bad": "\x00"}}))
        answered = c.execute("respond", actor, rq)
        completed = answered["snapshot"]
        audit = durable(c, completed)
        calls = completed["latest_receipt"]["tool_calls"]
        proof(18, "multiline/control arbitrary response preserved " + str(index),
              w.calls[-1].response == value, w.calls[-1].input_kind == "parent_response",
              completed["status"] == "completed", completed["latest_receipt"]["result"] == value)
        proof(39, "valid control keys/text/tool data jsonb roundtrip " + str(index),
              calls == [{"call_id": 1, "name": name, "input": value, "output": value, "error": None}],
              audit["latest_receipt"]["result"] == value,
              wm.storage_safe_json(value) == cm._canonical(value))
        before = row(child)
        proof(24, "valid control request exact replay " + str(index),
              c.execute("respond", actor, rq | {"expected_revision": 0}) == answered,
              c.execute("steer", actor, sq | {"expected_revision": 0}) == directed,
              row(child) == before, len(w.calls) == 4)
        c.close()


def test_receipts_and_tools():
    """Strict malformed DTOs and real bounded handlers, always committed via Control."""
    invalid = [("mapping not DTO", lambda dto: dto.as_dict()), ("none not DTO", lambda dto: None)]
    for field, values in {
        "schema_version": [True, 1.0, "1", 999], "run_id": [uuid4(), uid()], "turn_id": [uuid4(), None],
        "base_revision": [True, 1.0, "1", 0, -1, 2**63], "input_kind": ["wrong", [], "parent_response"],
        "input_digest": ["A"*64, "a"*63, None, "b"*64], "outcome": [None, [], "replan"],
        "result": [float("nan"), float("inf"), object(), {1: "invalid"}, "x"*65535, "\ud800"],
        "input_request": [{}, {"interaction_id": uid()}], "tool_calls": [[], ({},), ({},)*9],
    }.items():
        for index, value in enumerate(values):
            invalid.append((f"{field}/{index}", lambda dto, field=field, value=value: replace(dto, **{field: value})))
    iq = {"interaction_id": uid(), "options": []}
    for value in [None, {}, [], iq | {"interaction_id": iq["interaction_id"].upper()}, iq | {"options": {}},
                  iq | {"options": [float("nan")]}, iq | {"response_schema": {"properties": {}}},
                  iq | {"response_schema": {"type": "object", "required": ["x", "x"]}},
                  iq | {"response_schema": {"type": "string", "required": []}}]:
        invalid.append(("needs_input shape " + str(len(invalid)), lambda dto, value=value: replace(dto, outcome="needs_input", input_request=value)))
    circular = []
    circular.append(circular)
    invalid.append(("cyclic JSON", lambda dto: replace(dto, result=circular)))
    for name, transform in invalid:
        w = RawWorker(transform)
        c = control(w)
        q = request()
        error = expect("invalid_worker_receipt", lambda: c.execute("start", H, q))
        s = poll(c, q["run_id"])
        audit = durable(c, s)
        before = copy.deepcopy(audit)
        replay = expect("invalid_worker_receipt", lambda: c.execute("start", H, q))
        proof(37, "first-turn invalid " + name, type(error) is WorkerContractError, error.response == replay.response,
              s["status"] == "stopped", s["close_reason"] == "invalid_worker_receipt", s["latest_receipt"] is None,
              s["turns_used"] == 0, s["revision"] == 2, len(w.calls) == 1, row(q["run_id"]) == before)
        assert decide(s, True)["decision"] == "stop"
        c.close()
    w = RawWorker(lambda dto: {}, prior=True)
    c = control(w)
    q = request()
    prior = c.execute("start", H, q)["snapshot"]
    error = expect("invalid_worker_receipt", lambda: c.execute("steer", H, steer(prior)))
    s = error.response["snapshot"]
    durable(c, s)
    proof(37, "invalid subsequent turn preserves accepted receipt", s["latest_receipt"] == prior["latest_receipt"], s["turns_used"] == 1)

    # Generic Worker exceptions are converted outside T2, stable errors replayed.
    def boom(dto):
        raise RuntimeError("SENSITIVE_DO_NOT_PERSIST")
    for prior_flag in [False, True]:
        w = RawWorker(boom, prior=prior_flag)
        c = control(w)
        q = request()
        if prior_flag:
            prior = c.execute("start", H, q)["snapshot"]
            op, req = "steer", steer(prior)
        else:
            op, req = "start", q
        err = expect("worker_failed", lambda: c.execute(op, H, req))
        s = err.response["snapshot"]
        a = durable(c, s)
        before = copy.deepcopy(a)
        replay = expect("worker_failed", lambda: c.execute(op, H, req | ({"expected_revision": 0} if op == "steer" else {})))
        proof(38, "exception failed receipt " + str(prior_flag), type(err) is type(replay) is WorkerError,
              err.response == replay.response, s["close_reason"] == "worker_failed", s["latest_receipt"]["outcome"] == "failed",
              s["turns_used"] == (2 if prior_flag else 1), row(q["run_id"]) == before,
              "SENSITIVE_DO_NOT_PERSIST" not in json.dumps(a, default=str))
        # Host consumes the durable error/closed state, never repairs/re-runs.
        proof(40, "Host observes Worker failure without scheduling", Host(c).drive(q["run_id"]) == s,
              len(w.calls) == (2 if prior_flag else 1))

    def run_tools(plan, handler, *, failure=None, prior=False):
        events = []
        def handle(value):
            assert getattr(cm._worker_scope, "active", False)
            events.append(copy.deepcopy(value))
            return handler(value)
        w = FakeWorker(default=plan, tools={"echo": FakeTool("echo", handle)})
        c = control(w)
        q = request()
        if prior:
            w._plans[q["run_id"]] = ["progress"]
            old = c.execute("start", H, q)["snapshot"]
            op, req = "steer", steer(old)
        else:
            op, req = "start", q
        if failure:
            result = expect("worker_failed", lambda: c.execute(op, H, req)).response
        else:
            result = c.execute(op, H, req)
        s = result["snapshot"]
        audit = durable(c, s)
        assert audit["op_cache"][req["request_id"]]["response"] == result
        assert len(w.calls) == (2 if prior else 1)
        if failure:
            calls = s["latest_receipt"]["tool_calls"]
            assert s["status"] == "stopped" and s["close_reason"] == "worker_failed"
            assert s["latest_receipt"]["result"]["error"]["code"] == failure
            assert wm._json_bytes(calls) <= 32768
            assert all(wm._json_bytes(call) <= 4096 for call in calls)
            assert s["turns_used"] == (2 if prior else 1)
            replay = expect("worker_failed", lambda: c.execute(op, H, req)).response
            assert replay == result and row(q["run_id"]) == audit
            assert len(w.calls) == (2 if prior else 1)
        c.close()
        return s, events

    plan = {"outcome": "completed", "result": {"final": True},
            "tool_calls": [{"name": "echo", "input": {"n": n}} for n in [1, 2, 3]]}
    def business(value):
        n = value["n"]
        value["mutated"] = True
        return {"ok": False, "error": {"code": "business"}} if n == 2 else {"ok": True, "n": n}
    s, events = run_tools(plan, business)
    calls = s["latest_receipt"]["tool_calls"]
    proof(39, "ordered real handlers same committed receipt", events == [{"n": 1}, {"n": 2}, {"n": 3}],
          [call["input"] for call in calls] == events, calls[1]["output"]["ok"] is False,
          calls[1]["error"] is None, s["latest_receipt"]["result"] == {"final": True})
    proof(40, "business failure remains same-turn data no automatic schedule", s["status"] == "completed", s["turns_used"] == 1)

    specs = [{"name": "echo", "input": None}]
    exact = sized_record(4096)
    s, events = run_tools({"tool_calls": specs}, lambda _: exact["output"])
    proof(39, "real output 4096 bytes inclusive", len(events) == 1, wm._json_bytes(s["latest_receipt"]["tool_calls"][0]) == 4096)
    s, events = run_tools({"tool_calls": specs}, lambda _: exact["output"] + "x", failure="tool_overflow")
    proof(39, "real output 4097 rejected bounded marker", len(events) == 1, wm._json_bytes(s["latest_receipt"]["tool_calls"][0]) <= 512)
    outputs = [sized_record(4096, i)["output"] for i in range(1, 8)] + [sized_record(4087, 8)["output"]]
    iterator = iter(outputs)
    s, events = run_tools({"tool_calls": specs*8}, lambda _: next(iterator))
    proof(39, "real aggregate 32768 includes framing", len(events) == 8,
          wm._json_bytes(s["latest_receipt"]["tool_calls"]) == 32768)
    outputs[-1] += "x"
    iterator = iter(outputs)
    s, events = run_tools({"tool_calls": specs*8}, lambda _: next(iterator), failure="tool_overflow")
    calls = s["latest_receipt"]["tool_calls"]
    proof(39, "real aggregate 32769 rejected preserves seven outputs", len(events) == 8, len(calls) == 8,
          all(wm._json_bytes(call) == 4096 for call in calls[:7]), wm._json_bytes(calls[-1]) <= 512)
    for name, plan, code in [
        ("nine calls", {"tool_calls": specs*9}, "invalid_plan"),
        ("unknown second tool", {"tool_calls": specs + [{"name": "unknown", "input": None}]}, "unknown_tool"),
        ("nonfinite second input", {"tool_calls": specs + [{"name": "echo", "input": float("nan")}]}, "invalid_plan"),
        ("actual NUL second input", {"tool_calls": specs + [{"name": "echo", "input": "\x00"}]}, "invalid_plan"),
        ("actual NUL tool name", {"tool_calls": [{"name": "echo\x00", "input": None}]}, "invalid_plan"),
        ("oversized input", {"tool_calls": [{"name": "echo", "input": "x"*4096}]}, "invalid_plan"),
        ("forged output", {"tool_calls": [{"name": "echo", "input": None, "output": "fake"}]}, "invalid_plan"),
    ]:
        s, events = run_tools(plan, lambda v: v, failure=code)
        proof(39, "full prevalidation zero effects " + name, not events, s["latest_receipt"]["tool_calls"] == [])

    for prior_flag in [False, True]:
        for bad, code in [(object(), "tool_serialization"), (float("nan"), "tool_serialization"), ("\x00", "tool_serialization"), ({"\x00": "value"}, "tool_serialization"), ("x"*4096, "tool_overflow"), (None, "handler_exception")]:
            def handle(n, bad=bad):
                if n == 2:
                    if bad is None:
                        raise RuntimeError("SENSITIVE_TOOL_ERROR")
                    return bad
                return {"ok": True}
            plan = {"tool_calls": [{"name": "echo", "input": n} for n in [1, 2, 3]]}
            s, events = run_tools(plan, handle, failure=code, prior=prior_flag)
            calls = s["latest_receipt"]["tool_calls"]
            proof(40, "runtime tool failure stops same turn " + code + str(prior_flag), events == [1, 2], len(calls) == 2,
                  calls[0]["output"] == {"ok": True}, calls[1]["error"]["code"] == code,
                  "SENSITIVE_TOOL_ERROR" not in json.dumps(s), wm._json_bytes(calls[-1]) <= 512)

    for size in [65536, 65537]:
        result = "x"*(size-2)
        s, _ = run_tools({"result": result}, lambda x: x, failure="invalid_plan" if size > 65536 else None)
        proof(39, "result canonical bytes " + str(size), wm._json_bytes(s["latest_receipt"]["result"]) == size if size == 65536 else s["status"] == "stopped")
        padded = {"interaction_id": uid(), "options": [], "prompt": ""}
        padded["prompt"] = "x"*(size-wm._json_bytes(padded))
        assert wm._json_bytes(padded) == size
        s, _ = run_tools({"outcome": "needs_input", "input_request": padded}, lambda x: x, failure="invalid_plan" if size > 65536 else None)
        proof(39, "input_request canonical bytes " + str(size), s["status"] == ("waiting_input" if size == 65536 else "stopped"))
    for invalid_json in [float("nan"), float("inf"), {1: "bad"}]:
        s, events = run_tools({"result": invalid_json, "tool_calls": specs}, lambda x: x, failure="invalid_plan")
        proof(39, "finite result validated before tools", not events, s["latest_receipt"]["tool_calls"] == [])

    # A late malformed/failed DTO never overrides cancellation or prior history.
    for prior_flag in [False, True]:
        for variant in ["normal", "invalid", "exception"]:
            w = FakeWorker(default="progress")
            c = control(w)
            q = request()
            previous = c.execute("start", H, q)["snapshot"] if prior_flag else None
            enter, release = threading.Event(), threading.Event()
            original = w.run
            def block(wr, variant=variant):
                enter.set()
                barrier(release)
                dto = original(wr)
                if variant == "invalid":
                    return dto.as_dict()
                if variant == "exception":
                    raise RuntimeError("late failure")
                return dto
            w.run = block
            task = Task(lambda: c.execute("steer", H, steer(previous)) if previous else c.execute("start", H, q))
            barrier(enter)
            try:
                running = poll(c, q["run_id"])
                cancel(c, running)
                release.set()
                late = task.finish()["snapshot"]
                durable(c, late)
                proof(32, "cancel priority history preserved " + variant + str(prior_flag), late["close_reason"] == "late_result_after_cancel",
                      late["turns_used"] == (1 if prior_flag else 0), late["latest_receipt"] == (previous["latest_receipt"] if previous else None),
                      len(w.calls) == (2 if prior_flag else 1))
            finally:
                release.set()
                task.thread.join(DEADLINE)
    # Supplement the durable cases with strict request/record shape validation.
    wr = wm.WorkerRequest(uuid4(), uuid4(), 1, "initial", "a"*64, "go")
    dto = TurnReceipt(1, wr.turn_id, wr.run_id, 1, "initial", "a"*64, "completed", {})
    for field, value in [("base_revision", True), ("run_id", uid()), ("instruction", " "), ("continuation", 1), ("response", {})]:
        rejects(lambda field=field, value=value: wm.validate_request(replace(wr, **{field: value})), WorkerContractError)
    record = sized_record(100)
    for calls in [[record], ({},), (dict(record, call_id=True),), (dict(record, name=""),), (dict(record, error={"code": "business"}),)]:
        rejects(lambda calls=calls: wm.validate_receipt(replace(dto, tool_calls=calls), wr), WorkerContractError)
    proof(39, "DTO-only request and ordered bounded tool records", True)
    # UTF-8 byte accounting is not character counting.
    wm.validate_receipt(replace(dto, result="中"*21844), wr)
    rejects(lambda: wm.validate_receipt(replace(dto, result="中"*21845), wr), WorkerContractError)
    proof(39, "UTF-8 byte result bound", True)
    for name in ["中"*500, "\\x00"*200+"x"]:
        def boom_name(_):
            raise RuntimeError("SENSITIVE_NAME_ERROR")
        w = FakeWorker(default={"tool_calls": [{"name": name, "input": None}]}, tools={name: FakeTool(name, boom_name)})
        c = control(w)
        q = request()
        s = expect("worker_failed", lambda: c.execute("start", H, q)).response["snapshot"]
        durable(c, s)
        proof(39, "bounded unicode/control-character failure name", wm._json_bytes(s["latest_receipt"]["tool_calls"][0]) <= 512,
              "SENSITIVE_NAME_ERROR" not in json.dumps(s))


class TraceControl(Control):
    def __init__(self, *args, **kwargs):
        self.ops = []
        super().__init__(*args, **kwargs)

    def execute(self, op=None, actor=None, request=None):
        self.ops.append((op, copy.deepcopy(request)))
        return super().execute(op, actor, request)


class ParkHost(Host):
    def __init__(self, *args, **kwargs):
        self.parks = 0
        self.parked = threading.Event()
        self.condition = threading.Condition()
        self.last_event = None
        self.fail_park = False
        self.probes = []
        super().__init__(*args, **kwargs)

    def _park(self, event):
        assert_idle(self.control)
        # Prove parking does not retain either mutex; another thread must get it.
        def lock_probe():
            with hm._registry_lock, self.control._runtime.mutex:
                return True
        self.probes.append(Task(lock_probe))
        assert self.probes[-1].finish()
        with self.condition:
            self.parks += 1
            self.last_event = event
            self.parked.set()
            self.condition.notify_all()
        if self.fail_park:
            raise ValueError("gate invalid parking")
        super()._park(event)

    def wait_parks(self, count):
        with self.condition:
            assert self.condition.wait_for(lambda: self.parks >= count, timeout=DEADLINE), "park deadline"


def test_host_registry_parking_and_ids():
    """Cross-instance/sync-async uniqueness, all Event wake paths and stable IDs."""
    for bad in [0, -1, True, float("nan"), 1.01]:
        c = control()
        rejects(lambda bad=bad: Host(c, idle_interval=bad))
        c.close()
    c = control(FakeWorker(default="progress"), cls=TraceControl)
    s = c.execute("start", H, request())["snapshot"]
    host = ParkHost(c, execution_accepted=False, idle_interval=0.04)
    sibling = control(c.worker, cls=TraceControl)
    second = Host(sibling)
    task = Task(lambda: host.drive(s["run_id"]))
    host.wait_parks(1)
    try:
        count, before = len(c.ops), row(s["run_id"])
        rejects(lambda: second.drive(s["run_id"]), HostBusyError)
        rejects(lambda: asyncio.run(second.drive_async(s["run_id"])), HostBusyError)
        proof(41, "different Host/Control sync and async second driver zero effects", not sibling.ops,
              row(s["run_id"]) == before, len(c.worker.calls) == 1)
        host.wait_parks(3)
        polls = len([op for op, _ in c.ops if op == "poll"])
        proof(41, "execution refused parks no hot loop", host.parks >= 3, polls <= 2*host.parks + 4,
              not [op for op, _ in c.ops if op == "wait"], row(s["run_id"]) == before)
        c.worker.default = "completed"
        host.execution_accepted = True
        proof(41, "admission property setter signals Event", host.last_event.is_set())
        final = task.finish()
        proof(41, "admission wake resumes and registry releases", final["status"] == "completed", second.drive(s["run_id"]) == final)
        proof(16, "Event parking no transaction or held locks", all(t.value for t in host.probes))
    finally:
        host.execution_accepted = True
        if task.thread.is_alive():
            Host(c).stop(s["run_id"])
        task.thread.join(DEADLINE)

    # Shared per-Run acceptance setter on another Host wakes the active driver.
    c.worker.default = "progress"
    s = c.execute("start", H, request())["snapshot"]
    host = ParkHost(c, execution_accepted=False)
    task = Task(lambda: host.drive(s["run_id"]))
    host.wait_parks(1)
    c.worker.default = "completed"
    second.set_execution_accepted(s["run_id"], True)
    proof(41, "cross-Host admission signal", host.last_event.is_set(), task.finish()["status"] == "completed")

    # Child needs_input parks. Explicit ParentActor response signals shared Event.
    # Ensure live parent (previous default was completed).
    c.worker.default = "progress"
    parent = c.execute("start", H, request())["snapshot"]
    actor = ParentActor(parent["run_id"])
    child = uid()
    c.worker._plans[child] = ["needs_input", "progress", "completed"]
    waiting = c.execute("start", actor, request(child) | {"parent_run_id": parent["run_id"]})["snapshot"]
    host = ParkHost(c, idle_interval=0.04)
    task = Task(lambda: host.drive(child))
    host.wait_parks(3)
    before = row(child)
    count = len(c.ops)
    proof(41, "waiting_input parks no hot wait scheduling", host.parks >= 3, not any(op in {"steer", "respond", "cancel"} for op, _ in c.ops[-6:]),
          row(child) == before)
    second.respond(actor, response(waiting, None))
    final = task.finish()
    proof(41, "Parent respond signal discovered by parked Host", final["status"] == "completed", len(c.ops) > count)

    # Direct Control mutation has no Host signal; positive finite idle timeout discovers it.
    c.worker._plans[child := uid()] = ["needs_input", "completed"]
    waiting = c.execute("start", H, request(child))["snapshot"]
    host = ParkHost(c, idle_interval=0.08)
    task = Task(lambda: host.drive(child))
    host.wait_parks(1)
    c.execute("respond", H, response(waiting, None))
    proof(41, "unsignalled mutation via finite poll timeout", task.finish()["status"] == "completed", host.parks >= 1)

    # Exhausted waiting_input remains parked until external stop, not auto-budget cancel.
    c.worker._plans[child := uid()] = ["needs_input"]
    waiting = c.execute("start", H, request(child, 1))["snapshot"]
    host = ParkHost(c)
    task = Task(lambda: host.drive(child))
    host.wait_parks(1)
    stopped = second.stop(child)
    final = task.finish()
    proof(41, "external stop signals exhausted waiting parking", final == stopped, final["status"] == "stopped", final["turns_used"] == 1)
    proof(29, "waiting exhausted explicit stop exit", stopped["close_reason"] == "cancelled")

    # Hard invalid snapshots and park exceptions release the driver reservation.
    c.worker.default = "progress"
    s = c.execute("start", H, request())["snapshot"]
    host = ParkHost(c, execution_accepted=False)
    host.fail_park = True
    rejects(lambda: host.drive(s["run_id"]))
    stop = second.stop(s["run_id"])
    proof(41, "park exception finally releases slot", second.drive(s["run_id"]) == stop)
    s = c.execute("start", H, request())["snapshot"]
    original = c.execute
    def invalid_poll(op=None, actor=None, request=None):
        result = original(op, actor, request)
        if op == "poll" and request["run_id"] == s["run_id"]:
            return result | {"snapshot": result["snapshot"] | {"schema_version": 99}}
        return result
    c.execute = invalid_poll
    rejects(lambda: Host(c).drive(s["run_id"]))
    c.execute = original
    stop = second.stop(s["run_id"])
    proof(41, "invalid snapshot propagates hard failure releases slot", second.drive(s["run_id"]) == stop)

    # Host durable failure during its own start and continuation also releases registry.
    for during_start in [True, False]:
        w = RawWorker(lambda dto: {}, prior=not during_start)
        bad = control(w)
        run = uid()
        result = Host(bad).drive(run, instruction="bad", turn_budget=3, run_request_id=uid())
        proof(41, "durable WorkerContractError cleanup " + str(during_start), result["status"] == "stopped",
              Host(bad).drive(run) == result, len(w.calls) == (1 if during_start else 2))

    # A definite CAS conflict changes the observation but not the unconsumed ID.
    run = uid()
    w = FakeWorker({run: ["progress", "progress", "progress", "completed"]})
    c = control(w, cls=TraceControl)
    original = c.execute
    attempted = []
    fired = False
    def conflict(op=None, actor=None, request=None):
        nonlocal fired
        if op == "steer":
            attempted.append(copy.deepcopy(request))
            if not fired:
                fired = True
                original("steer", H, request | {"request_id": uid()})
                raise ControlError("revision_conflict")
        return original(op, actor, request)
    c.execute = conflict
    result = Host(c).drive(run, instruction="stable", turn_budget=5, run_request_id=uid())
    proof(41, "stable continuation ID across CAS poll/redecide", result["status"] == "completed",
          attempted[0]["request_id"] == attempted[1]["request_id"], attempted[0]["expected_revision"] != attempted[1]["expected_revision"],
          attempted[2]["request_id"] != attempted[1]["request_id"], len(w.calls) == 4)

    # Actual commit then lost caller acknowledgement: same ID exact retry, new ID next turn.
    run = uid()
    w = FakeWorker({run: ["progress", "progress", "completed"]})
    c = control(w)
    original = c.execute
    requests = []
    fired = False
    def ack_loss(op=None, actor=None, request=None):
        nonlocal fired
        result = original(op, actor, request)
        if op == "steer":
            requests.append(copy.deepcopy(request))
            if not fired:
                fired = True
                raise TimeoutError("caller acknowledgement lost")
        return result
    c.execute = ack_loss
    final = Host(c).drive(run, instruction="ack", turn_budget=4, run_request_id=uid())
    proof(41, "Host confirmation loss exact retry not replacement", requests[0] == requests[1],
          requests[2]["request_id"] != requests[1]["request_id"], len(w.calls) == 3, final["turns_used"] == 3)
    proof(27, "Host retry does not replay committed Worker", row(run)["revision"] == 6)

    # Historical start receipt must be polled before deciding a new continuation.
    run = uid()
    w = FakeWorker({run: ["progress", "completed"]})
    c = control(w, cls=TraceControl)
    q = request(run)
    historical = c.execute("start", H, q)
    completed = c.execute("steer", H, steer(historical["snapshot"]))["snapshot"]
    count = len(c.ops)
    result = Host(c).drive(run, instruction=q["instruction"], turn_budget=q["turn_budget"], run_request_id=q["request_id"])
    proof(41, "cached start receipt followed by current poll", result == completed, len(w.calls) == 2,
          [op for op, _ in c.ops[count:]] == ["start", "poll"])

    # Explicit forwarding keeps actor and a pending answer's ID across ack loss.
    w = FakeWorker(default="needs_input")
    c = control(w)
    waiting = c.execute("start", H, request())["snapshot"]
    w.default = "completed"
    original = c.execute
    reqs = []
    def respond_loss(op=None, actor=None, request=None):
        result = original(op, actor, request)
        if op == "respond":
            assert actor == H
            reqs.append(copy.deepcopy(request))
            if len(reqs) == 1:
                raise ConnectionError("answer ack lost")
        return result
    c.execute = respond_loss
    answer = response(waiting, None)
    result = Host(c).respond(H, answer)
    proof(41, "respond retry preserves exact actor interaction and ID", reqs == [answer, answer], len(w.calls) == 2,
          result["snapshot"]["status"] == "completed")


def test_host_stop_and_cached_cancel():
    """External stop never calls decide; historical running cache never returned as current."""
    w = Blocking(default="completed")
    c = control(w, cls=TraceControl)
    q = request()
    task = Task(lambda: c.execute("start", H, q))
    barrier(w.enter)
    original = c.execute
    try:
        # Stop first sees a genuinely committed running snapshot. Before it acts,
        # a competing same semantic cancel + T2 closes Run, leaving cached running.
        at_poll, release_poll = threading.Event(), threading.Event()
        stop_thread = None
        def delayed_poll(op=None, actor=None, request=None):
            result = original(op, actor, request)
            if op == "poll" and threading.current_thread() is stop_thread:
                at_poll.set()
                barrier(release_poll)
            return result
        c.execute = delayed_poll
        cancel_id = uid()
        def stopping():
            nonlocal stop_thread
            stop_thread = threading.current_thread()
            return Host(c).stop(q["run_id"], cancel_id)
        # Patch decide globally; no driver runs during this external stop proof.
        with patch.object(hm, "decide", side_effect=AssertionError("stop must not decide")):
            st = Task(stopping)
            barrier(at_poll)
            cq = {"run_id": q["run_id"], "request_id": cancel_id, "expected_revision": 1}
            historical = original("cancel", H, cq)
            w.release.set()
            committed = task.finish()["snapshot"]
            # Only the first poll is paused; further polls read current truth.
            c.execute = original
            release_poll.set()
            current = st.finish()
        proof(42, "external stop calls cancel not decide", current == committed, current["status"] == "stopped",
              any(op == "cancel" and req["request_id"] == cancel_id for op, req in c.ops))
        proof(42, "cached running cancel polled to actual closed snapshot", historical["snapshot"]["status"] == "running",
              current["revision"] == 3, len(w.calls) == 1)
    finally:
        c.execute = original
        w.release.set()
        task.thread.join(DEADLINE)
    # Stop of a genuinely live running Run sets cancel once, then waits for T2.
    w = Blocking(default="progress")
    c = control(w, cls=TraceControl)
    q = request()
    task = Task(lambda: c.execute("start", H, q))
    barrier(w.enter)
    hint = threading.Event()
    original = c.execute
    def tracked(op=None, actor=None, request=None):
        result = original(op, actor, request)
        if op == "cancel":
            hint.set()
        return result
    c.execute = tracked
    with patch.object(hm, "decide", side_effect=AssertionError("external stop must not decide")):
        stop = Task(lambda: Host(c).stop(q["run_id"], uid()))
        barrier(hint)
        proof(42, "stop still waits after durable running cancel", stop.thread.is_alive(), row(q["run_id"])["cancel_requested"])
        w.release.set()
        current = stop.finish()
    task.finish()
    proof(42, "one cancel then wait closes not just coroutine", current["status"] == "stopped",
          len([op for op, _ in c.ops if op == "cancel"]) == 1, any(op == "wait" for op, _ in c.ops))
    # A definite pre-admission CAS conflict keeps the one semantic stop ID.
    w = FakeWorker(default="progress")
    c = control(w)
    s = c.execute("start", H, request())["snapshot"]
    original = c.execute
    attempts = []
    def stop_conflict(op=None, actor=None, request=None):
        if op == "cancel":
            attempts.append(copy.deepcopy(request))
            if len(attempts) == 1:
                original("steer", H, steer(poll(c, s["run_id"])))
        return original(op, actor, request)
    c.execute = stop_conflict
    cancel_id = uid()
    with patch.object(hm, "decide", side_effect=AssertionError("stop must not decide")):
        final = Host(c).stop(s["run_id"], cancel_id)
    proof(42, "stop stable ID on revision conflict", len(attempts) == 2,
          all(req["request_id"] == cancel_id for req in attempts), attempts[0]["expected_revision"] != attempts[1]["expected_revision"],
          final["status"] == "stopped", final["turns_used"] == 2)


def test_schema_permissions_and_isolation(loads):
    """All user relations, actual role CRUD denial and six-op session/fence audit."""
    tables = query("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                   "WHERE c.relkind IN ('r','p','f','m') AND n.nspname NOT IN ('pg_catalog','information_schema') "
                   "AND n.nspname NOT LIKE 'pg_toast%%' AND n.nspname NOT LIKE 'pg_temp%%'")
    proof(44, "all non-system data tables", tables == [("public", "v23_runs")])
    proof(48, "no events effects sessions steps history in any user schema", tables == [("public", "v23_runs")])
    proof(45, "recorded actual DDL execution exactly one SQL", loads == [setup.SQL_FILE.name])
    source = {}
    for path in Path(__file__).parent.glob("*.py"):
        source[path.name] = path.read_text()
        tree = ast.parse(source[path.name])
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(module.startswith(("v13", "v15")) for module in modules)
        if path.name != "test_minimal_loop.py":
            assert not any(module.startswith(("http", "requests", "httpx", "aiohttp", "openai", "socket")) for module in modules)
    proof(46, "AST independent imports supplementary to positive chains", len(source) == 6)
    proof(47, "no static CE map artifacts alongside runtime", {p.name for p in Path(__file__).parent.iterdir() if p.is_file()} ==
          {"README.md", "v23.sql", "setup_db.py", "worker.py", "control.py", "disposition.py", "host.py", "test_minimal_loop.py"})
    assert query("SELECT has_database_privilege('public',%s,'CONNECT'), has_database_privilege('v23_worker',%s,'CONNECT'), "
                 "(SELECT rolcanlogin FROM pg_roles WHERE rolname='v23_worker')", (setup.DB, setup.DB)) == [(False, False, False)]
    rejects(lambda: psycopg2.connect(setup.local_dsn(user="v23_worker"), connect_timeout=2), psycopg2.Error)
    for sql in ["SELECT * FROM v23_runs", "INSERT INTO v23_runs(run_id,status,revision,turn_budget) VALUES ('" + uid() + "','ready',0,1)",
                "UPDATE v23_runs SET revision=revision", "DELETE FROM v23_runs"]:
        rejects(lambda sql=sql: query(sql, role="v23_worker"), psycopg2.errors.InsufficientPrivilege)
    for column, expr in [("run_id", "run_id"), ("parent_run_id", "parent_run_id"), ("turn_budget", "turn_budget")]:
        rejects(lambda column=column, expr=expr: query("UPDATE v23_runs SET " + column + "=" + expr, dsn=DSN), psycopg2.errors.InsufficientPrivilege)
    for role in ["v23_control", "v23_worker"]:
        rejects(lambda role=role: query("CREATE TABLE v23_forbidden(id int)", role=role), psycopg2.errors.InsufficientPrivilege)
    proof(49, "actual SET ROLE Worker CRUD and limited Control UPDATE/DDL denied", True)
    # SQL backstop regression: CHECK must reject SQL NULL, not pass UNKNOWN.
    for digest in [None, "A"*64, "a"*63]:
        run = uid()
        rejects(lambda run=run, digest=digest: query(
            "INSERT INTO v23_runs(run_id,status,revision,turn_budget,active_operation_id,active_base_revision,active_input_digest) "
            "VALUES (%s,'running',1,1,%s,1,%s)", (run, uid(), digest)), psycopg2.errors.CheckViolation)
        proof(49, "SQL complete active triple rejects NULL/invalid digest " + str(digest), row(run) is None)
    run = uid()
    query("INSERT INTO v23_runs(run_id,status,revision,turn_budget,active_operation_id,active_base_revision,active_input_digest) "
          "VALUES (%s,'running',1,1,%s,1,%s)", (run, uid(), "a"*64))
    proof(49, "SQL complete active triple positive rollback probe", row(run) is None)
    for receipt in [None, {}, {"outcome": "needs_input"}, {"outcome": "needs_input", "input_request": None}]:
        run = uid()
        rejects(lambda run=run, receipt=receipt: query(
            "INSERT INTO v23_runs(run_id,status,revision,turn_budget,latest_receipt) VALUES (%s,'waiting_input',1,1,%s)",
            (run, psycopg2.extras.Json(receipt) if receipt is not None else None)), psycopg2.errors.CheckViolation)
        proof(49, "SQL waiting_input rejects missing/NULL object", row(run) is None)

    class PermissionControl(Control):
        def __init__(self, *args, **kwargs):
            self.identities = []
            self.phases = []
            super().__init__(*args, **kwargs)

        @contextmanager
        def _read_tx(self):
            with super()._read_tx() as cur:
                cur.execute("SELECT session_user,current_user,pg_backend_pid()")
                self.identities.append(cur.fetchone())
                yield cur

        def _commit(self, conn, phase):
            with conn.cursor() as cur:
                cur.execute("SELECT session_user,current_user,pg_backend_pid()")
                identity = cur.fetchone()
            self.phases.append((phase, identity))
            super()._commit(conn, phase)

        def _after_listen(self, listener):
            with listener.cursor() as cur:
                cur.execute("SELECT session_user,current_user,pg_backend_pid()")
                identity = cur.fetchone()
            assert identity[:2] == ("v23_control", "v23_control")
            assert listener.get_transaction_status() == TRANSACTION_STATUS_IDLE
            self.identities.append(dict(zip(["session_user", "current_user", "pg_backend_pid"], identity)))

    close_controls()
    run = uid()
    w = FakeWorker({run: ["progress", "needs_input", "progress"]})
    c = control(w, cls=PermissionControl)
    s = c.execute("start", H, request(run))["snapshot"]
    c.execute("poll", H, {"run_id": run})
    c.execute("wait", H, {"run_id": run, "since_revision": s["revision"], "timeout_seconds": 0.01})
    s = c.execute("steer", H, steer(s))["snapshot"]
    s = c.execute("respond", H, response(s, None))["snapshot"]
    s = cancel(c, s)["snapshot"]
    durable(c, s)
    proof(49, "all six op real v23_control session and current role", bool(c.identities),
          all(i["session_user"] == i["current_user"] == "v23_control" for i in c.identities))
    fence_pid = c._runtime.conn.get_backend_pid()
    proof(49, "all T1 T2 cancel recovery same fenced backend", {phase for phase, _ in c.phases} >= {"T1", "T2", "cancel", "recovery"},
          all(i == ("v23_control", "v23_control", fence_pid) for _, i in c.phases), len(w.calls) == 3)
    assert_idle(c)
    proof(16, "six-op gate exits idle", True)
    rejects(lambda: socket.socket(socket.AF_INET), AssertionError)
    rejects(lambda: socket.socket(socket.AF_INET6), AssertionError)
    rejects(lambda: psycopg2.connect("host=localhost dbname=postgres"), AssertionError)
    rejects(lambda: Control("host=localhost user=v23_control dbname=" + setup.DB, FakeWorker()))
    proof(5, "runtime AF_INET AF_INET6 and TCP PostgreSQL prohibited", NETWORK["blocked"] >= 3, NETWORK["postgres"] > 0)
    proof(50, "fake-only positive chains with Unix-only network guard", NETWORK["postgres"] > 0, True)


def main():
    global DSN, ADMIN
    if len(sys.argv) == 4 and sys.argv[1] == "--fixture":
        with network_guard():
            return fixture(sys.argv[2], Path(sys.argv[3]))
    loads = []
    # Observe the actual loader SQL execution, not a string-count source check.
    with network_guard():
        DSN, ADMIN = setup.local_dsn(), setup.local_dsn(user=None)
        real_connect = psycopg2.connect
        class LoadCursor(psycopg2.extensions.cursor):
            def execute(self, statement, *args, **kwargs):
                if isinstance(statement, str) and "CREATE TABLE v23_runs" in statement:
                    assert statement == setup.SQL_FILE.read_text(encoding="utf-8")
                    loads.append(setup.SQL_FILE.name)
                return super().execute(statement, *args, **kwargs)
        class LoadConnection(psycopg2.extensions.connection):
            def cursor(self, *args, **kwargs):
                kwargs.setdefault("cursor_factory", LoadCursor)
                return super().cursor(*args, **kwargs)
        def connect(*args, **kwargs):
            return real_connect(*args, connection_factory=LoadConnection, **kwargs)
        with patch.object(psycopg2, "connect", connect):
            assert setup.main() == 0
        groups = [test_api_vertical_and_authority, test_disposition_validation,
                  test_pending_cancel_and_competition, test_waits_and_notifications,
                  test_commit_faults_and_owner_loss, test_process_restart, test_storage_safe_receipts,
                  test_json_text_controls, test_receipts_and_tools,
                  test_host_registry_parking_and_ids, test_host_stop_and_cached_cancel,
                  lambda: test_schema_permissions_and_isolation(loads)]
        try:
            for group in groups:
                print("\n[GROUP] " + group.__name__, flush=True)
                group()
                close_controls()
            assert set(EVIDENCE) == set(range(1, 51)), "missing labels: " + str(set(range(1, 51)) - set(EVIDENCE))
            assert len(LABELS) == len(set(LABELS)) == 50
            for number, label in enumerate(LABELS, 1):
                print(f"[PASS] {number:02d} {label} ({len(EVIDENCE[number])} subcases)")
            print(f"v23 M1 runtime gate: green; 50/50 labels, {sum(map(len, EVIDENCE.values()))} subcases; fake-only Unix PostgreSQL")
            return 0
        finally:
            close_controls()
            for process in CHILDREN:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=DEADLINE)
            alive = [task for task in TASKS if task.thread.is_alive()]
            if alive:
                raise AssertionError("gate leaked Worker/Host threads")


if __name__ == "__main__":
    raise SystemExit(main())
