"""Import-safe Fake CE host and Stage 40's sixteen executable probe groups.

Run: UV_FROZEN=1 uv run python v13/ce_run/test_ce_run.py
No provider, native spawn handler, or production takeover is implemented here.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import importlib.util
import inspect
import json
import math
import select
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
BASE = "fb295ac6c7459bb98dac57e37883af549d2d8a4c"
PHASE_D = "78e77c710bf06a0a1c771b822a3837c5db4c66d0"
WAIT_KEYS = frozenset(("schema_version", "reason", "snapshot", "registration_generation",
                       "epoch_ordinal", "continuity_generation", "interaction", "wake_id"))
DISCOVERY_KEYS = frozenset(("schema_version", "ok", "run_id", "registration_generation",
                           "epoch_ordinal", "continuity_generation", "revision", "status",
                           "current_driving_operation_id", "operations"))
OP_KEYS = frozenset(("operation_id", "request_id", "verb", "attempt_seq", "effect_id",
                    "effect_status", "queued"))


def sql(conn, statement, args=()):
    """One statement, deliberately never commits the caller's transaction."""
    with conn.cursor() as cur:
        cur.execute(statement, args)
        return cur.fetchone()[0] if cur.description else None


def idle(conn):
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise RuntimeError("CE host requires an IDLE connection")


def ce_start(conn, actor, message, request_id, parent=None, **envelope):
    if envelope:
        return {"schema_version": 1, "ok": False, "reason": "invalid_args"}
    return sql(conn, "SELECT public.v13_ce_run_start(%s::uuid,%s,%s,%s::uuid)",
               (actor, message, request_id, parent))


def discover(conn, actor, run_id):
    return sql(conn, "SELECT public.v13_ce_discover_work(%s::uuid,%s::uuid)", (actor, run_id))


def poll(conn, actor, run_id, registration=None):
    return sql(conn, "SELECT public.v13_ce_run_poll(%s::uuid,%s::uuid,%s::bigint)",
               (actor, run_id, registration))


def cancel(conn, actor, run_id, request_id):
    return sql(conn, "SELECT public.v13_ce_run_cancel(%s::uuid,%s::uuid,%s)", (actor, run_id, request_id))


def steer(conn, actor, run_id, message, request_id, epoch):
    return sql(conn, "SELECT public.v13_ce_run_steer(%s::uuid,%s::uuid,%s,%s,%s::bigint)",
               (actor, run_id, message, request_id, epoch))


def respond(conn, actor, run_id, interaction_id, response, request_id):
    return sql(conn, "SELECT public.v13_ce_run_respond(%s::uuid,%s::uuid,%s,%s::jsonb,%s)",
               (actor, run_id, interaction_id, Json(response), request_id))


def admit(conn, actor, run_id, epoch, verb, payload, request_id, driving):
    return sql(conn, "SELECT public.v13_ce_admit_operation(%s::uuid,%s::uuid,%s::bigint,%s,%s::jsonb,%s,%s::uuid)",
               (actor, run_id, epoch, verb, Json(payload), request_id, driving))


def claim(conn, actor, operation_id, worker="ce-fake", lease_ms=600000):
    return sql(conn, "SELECT public.v13_ce_claim_effect(%s::uuid,%s::uuid,%s,%s::integer)",
               (actor, operation_id, worker, lease_ms))


def receipt_payload(tokens, result):
    return {"effect_id": tokens["effect_id"], "attempt_no": tokens["attempt_no"],
            "fence": tokens["fence"], "effect_result": result}


def accept(conn, actor, operation_id, tokens, result, status="succeeded", request_id=None):
    return sql(conn, "SELECT public.v13_ce_accept_receipt(%s::uuid,%s::uuid,%s,%s,%s::jsonb)",
               (actor, operation_id, request_id or f"ce:{operation_id}:receipt", status,
                Json(receipt_payload(tokens, result))))


def publish(conn, actor, operation_id, revision, snapshot, purpose="terminal", request_id=None):
    return sql(conn, "SELECT public.v13_ce_publish_snapshot(%s::uuid,%s::uuid,%s,%s::bigint,%s::jsonb)",
               (actor, operation_id, request_id or f"ce:{operation_id}:publish:{purpose}",
                revision, Json(snapshot)))


def wait_check(conn, actor, run_id, registration, epoch, after=0):
    return sql(conn, "SELECT public.v13_ce_run_wait_check(%s::uuid,%s::uuid,%s::bigint,%s::bigint,%s::bigint)",
               (actor, run_id, registration, epoch, after))


def ce_wait(conn, actor, run_id, registration_gen, epoch_ordinal, timeout_seconds=5.0,
            poll_interval=0.05, after_wake_id=0):
    """Wait with short read transactions and a caller-owned steering cursor."""
    idle(conn)
    invalid = {key: None for key in WAIT_KEYS}
    invalid.update(schema_version=1, reason="invalid_wait_args")
    numeric = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if (not numeric(timeout_seconds) or not 0 <= timeout_seconds <= 3600
            or not numeric(poll_interval) or not 0.01 <= poll_interval <= 1
            or not isinstance(after_wake_id, int) or isinstance(after_wake_id, bool) or after_wake_id < 0
            or not isinstance(registration_gen, int) or isinstance(registration_gen, bool) or registration_gen < 1
            or not isinstance(epoch_ordinal, int) or isinstance(epoch_ordinal, bool) or epoch_ordinal < 1):
        return invalid
    deadline = time.monotonic() + timeout_seconds
    epoch, cursor = epoch_ordinal, after_wake_id
    active_error = False
    listening = False
    try:
        sql(conn, "LISTEN v13_ce_run_changed")
        conn.commit()
        listening = True
        while True:
            result = wait_check(conn, actor, run_id, registration_gen, epoch, cursor)
            conn.commit()
            if set(result) != WAIT_KEYS:
                raise AssertionError(f"wait DTO is not the fixed eight-key contract: {result}")
            if result["reason"] == "epoch_advanced":
                epoch = result["epoch_ordinal"]
                continue
            if result["reason"] != "waiting":
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # The query above is also the deadline's final actionable check.
                result["reason"] = "timed_out"
                return result
            idle(conn)
            if select.select([conn], [], [], min(poll_interval, remaining))[0]:
                conn.poll()
                conn.notifies.clear()
    except BaseException:
        active_error = True
        raise
    finally:
        if listening:
            try:
                if not conn.closed:
                    conn.rollback()
                    sql(conn, "UNLISTEN v13_ce_run_changed")
                    conn.commit()
            except BaseException:
                if not active_error:
                    raise


class FakeLLM:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, conn, request, history, idempotency_key):
        idle(conn)
        self.calls.append(copy.deepcopy({"request": request, "history": history, "key": idempotency_key}))
        if not self.responses:
            return {"text": "CE fake complete"}
        response = self.responses.pop(0)
        return response(conn, request, history, idempotency_key) if callable(response) else copy.deepcopy(response)


class FakeTool:
    """The only adapter: preserve task verbatim; never invoke native spawn."""
    def __init__(self):
        self.calls = []

    def __call__(self, conn, request, history, idempotency_key):
        idle(conn)
        if request.get("tool") != "spawn_subsession":
            raise ValueError("no CE Fake adapter for this tool")
        self.calls.append(copy.deepcopy(request))
        return {"schema_version": 1, "adapter": "ce-fake-spawn", "simulated": True,
                "tool": "spawn_subsession", "task": request["params"]["task"],
                "tool_call_id": request.get("tool_call_id")}


class DefinitelyUnsent(Exception):
    """Only this explicit Fake transient is eligible for a bounded retry."""


class ContinuationRejected(RuntimeError):
    pass


@dataclass
class PreparedWork:
    run_id: str
    epoch: int
    operation: dict
    tokens: dict
    history: list
    result: dict | None = None
    status: str = "succeeded"


class CeWorker:
    """Fake-only single-run host; discovery is its only CE work source.

    finish() is one T2 transaction: accept + every successor + publication.
    PreparedWork can replay a known receipt after a lost COMMIT response, but a
    restarted worker holding only run_id never repeats an already claimed IO.
    """
    def __init__(self, connect, llm=None, tool=None, actor=None, lease_ms=600000, max_attempts=2):
        if max_attempts not in (1, 2):
            raise ValueError("Fake retries are bounded to at most two attempts")
        self._connect, self.actor = connect, actor
        self.llm = llm if llm is not None else FakeLLM()
        self.tool = tool if tool is not None else FakeTool()
        self.lease_ms, self.max_attempts = lease_ms, max_attempts
        self.conn = None
        self.calls = []

    def connection(self):
        if self.conn is None:
            self.conn = self._connect()
            idle(self.conn)
            with self.conn:
                superuser = sql(self.conn, "SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
                route = sql(self.conn, "SELECT pg_has_role(current_user,'v13_route','USAGE')")
            if superuser or not route:
                self.conn.close()
                self.conn = None
                raise ValueError("CeWorker requires a non-superuser route LOGIN")
        return self.conn

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _history(self, conn, run_id):
        # Only the already-readable frozen events/effects provenance is used.
        with conn.cursor() as cur:
            cur.execute("SELECT e.seq,e.type,e.payload,e.source_effect_id::text,f.request "
                        "FROM public.events e LEFT JOIN public.effects f ON f.effect_id=e.source_effect_id "
                        "WHERE e.session_id=%s::uuid ORDER BY e.seq", (run_id,))
            events = cur.fetchall()
            cur.execute("SELECT request FROM public.effects WHERE session_id=%s::uuid AND kind='tool'", (run_id,))
            admitted = {(r[0].get("source_operation_id"), r[0].get("tool_call_index"), r[0].get("tool_call_id"))
                        for r in cur.fetchall()}
        history = []
        for seq, kind, payload, source_effect, request in events:
            payload = copy.deepcopy(payload)
            source = (request or {}).get("operation_id")
            if kind == "llm/message" and "tool_calls" in payload:
                calls = payload.pop("tool_calls")
                paired = []
                orphaned = []
                for index, call in enumerate(calls):
                    if ((source, index, call.get("id")) in admitted
                            or (source, index, None) in admitted):
                        paired.append(call)
                    else:
                        orphaned.append(call)
                if paired:
                    payload["tool_calls"] = paired
                if orphaned:
                    payload["superseded"] = True
                    payload["history_text"] = json.dumps({"superseded_tool_calls": orphaned}, sort_keys=True)
            if kind == "tool/call":
                call_id = payload.get("id")
                if not any(src == source and cid == call_id for src, _, cid in admitted):
                    kind = "history"
                    payload = {"superseded": True, "text": json.dumps(payload, sort_keys=True)}
            history.append({"seq": seq, "type": kind, "payload": payload, "source_effect_id": source_effect})
        return history

    def prepare(self, run_id):
        conn = self.connection()
        idle(conn)
        # Frozen requeue is intentionally global and committed before CE locks.
        with conn:
            maintenance = sql(conn, "SELECT public.v13_ce_requeue_stale()")
            if (set(maintenance) != {"schema_version", "ok", "recovery"}
                    or maintenance["schema_version"] != 1 or maintenance["ok"] is not True
                    or not isinstance(maintenance["recovery"], dict)):
                raise AssertionError(f"invalid CE maintenance response: {maintenance}")
        self.calls.append("requeue_commit")
        with conn:
            state = discover(conn, self.actor, run_id)
            if not state.get("ok") or state["status"] != "running":
                return None
            ready = next((o for o in state["operations"] if o["effect_status"] == "ready"), None)
            if ready is None:
                return None
            tokens = claim(conn, self.actor, ready["operation_id"], lease_ms=self.lease_ms)
            if not tokens.get("ok"):
                return None
        self.calls.append("claim_commit")
        idle(conn)
        with conn:
            history = self._history(conn, run_id)
        idle(conn)
        return PreparedWork(run_id, state["epoch_ordinal"], ready, tokens, history)

    def perform(self, work):
        conn = self.connection()
        idle(conn)
        if work.result is not None:
            raise RuntimeError("known Fake result must be replayed, never executed twice")
        adapter = self.tool if work.operation["verb"] == "admit_tool" else self.llm
        for attempt in range(self.max_attempts):
            idle(conn)
            try:
                work.result = adapter(conn, work.tokens["request"], work.history, work.tokens["idempotency_key"])
                break
            except DefinitelyUnsent:
                if attempt + 1 == self.max_attempts:
                    raise
        if not isinstance(work.result, dict):
            raise TypeError("Fake effect_result must be an object")
        idle(conn)
        self.calls.append("fake_io_idle")
        return work.result

    @staticmethod
    def _required(result):
        if not result.get("ok"):
            raise ContinuationRejected(json.dumps(result, sort_keys=True))
        return result

    def finish(self, work, after_accept=None, after_commit=None):
        conn = self.connection()
        idle(conn)
        if work.result is None:
            raise ValueError("cannot invent a receipt without a known result")
        op = work.operation["operation_id"]
        successors = []
        with conn:
            received = accept(conn, self.actor, op, work.tokens, work.result, work.status)
            if after_accept is not None:
                after_accept(conn, work, received)
            # SQL already performs legitimate late settlement and promotion.
            # Stored replay must never re-enter continuation, even if ok=true.
            if (received.get("ok") and not received.get("replayed")
                    and received.get("effect_outcome") != "unknown"):
                if received.get("replayed") is not False:
                    raise AssertionError("first receipt must explicitly report replayed=false")
                revision = received["revision"]
                if work.operation["verb"] == "admit_tool":
                    state = self._required(discover(conn, self.actor, work.run_id))
                    if not state["operations"]:
                        successors.append(self._required(admit(
                            conn, self.actor, work.run_id, work.epoch, "admit_turn",
                            {"after_operation_id": op}, f"ce:{op}:next_turn",
                            state["current_driving_operation_id"])))
                elif received["effect_outcome"] != "succeeded":
                    successors.append(self._required(publish(
                        conn, self.actor, op, revision,
                        {"status": "failed", "failure_reason": {"effect_outcome": received["effect_outcome"]}},
                        "terminal")))
                elif work.result.get("tool_calls"):
                    for index, call in enumerate(work.result["tool_calls"]):
                        payload = {"tool": call["name"], "params": call["args"],
                                   "source_operation_id": op, "tool_call_index": index, "tool_call_id": call["id"]}
                        successors.append(self._required(admit(
                            conn, self.actor, work.run_id, work.epoch, "admit_tool", payload,
                            f"ce:{op}:tool:{index}", op)))
                else:
                    status = work.result.get("ce_status", "completed")
                    purpose = {"waiting_for_input": "waiting", "running": "running",
                               "completed": "terminal", "failed": "terminal"}.get(status)
                    if purpose is None:
                        raise ContinuationRejected("invalid Fake CE status")
                    snapshot = {"status": status, "assistant_text": work.result.get("text")}
                    if "failure_reason" in work.result:
                        snapshot["failure_reason"] = work.result["failure_reason"]
                    if status == "waiting_for_input":
                        snapshot["interaction"] = work.result["interaction"]
                    successors.append(self._required(publish(conn, self.actor, op, revision, snapshot, purpose)))
                    if status == "running":
                        successors.append(self._required(admit(
                            conn, self.actor, work.run_id, work.epoch, "admit_turn",
                            {"after_operation_id": op}, f"ce:{op}:next_turn", op)))
        idle(conn)
        self.calls.append("t2_commit")
        if after_commit is not None:
            after_commit(conn, work, received)
        return {"receipt": received, "successors": successors}

    def step(self, run_id, after_accept=None, after_commit=None):
        work = self.prepare(run_id)
        if work is None:
            return None
        self.perform(work)
        return self.finish(work, after_accept, after_commit)

    def run(self, run_id, max_steps=32):
        results = []
        for _ in range(max_steps):
            result = self.step(run_id)
            if result is None:
                return results
            results.append(result)
        raise RuntimeError("Fake worker step budget exhausted")


# The remaining code is gate-only. Importing the module does not create a DB,
# inspect the worktree, connect, execute subprocesses, or start a thread.
def setup_module():
    name = "ce_run_gate_setup"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("setup_db.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def uid():
    return str(uuid.uuid4())


class Gate:
    def __init__(self, database):
        self.db = database
        self.setup = setup_module()
        self.checks = 0
        self.case_failures = []

    @contextlib.contextmanager
    def case(self, label):
        """Independent cases continue gathering evidence, never turn green."""
        try:
            yield
        except Exception as exc:
            self.case_failures.append((label, repr(exc)))
            print("  CASE FAIL", label, repr(exc), flush=True)
            traceback.print_exc()

    def check(self, label, condition, evidence=None):
        self.checks += 1
        if not condition:
            raise AssertionError(f"{label}: {evidence!r}")
        print(f"  ok {self.checks}: {label}", flush=True)

    @contextlib.contextmanager
    def connection(self, alias="route"):
        conn = (self.setup.connect_owner_database(self.db) if alias == "owner"
                else self.setup.connect_test_database(self.db, role=alias))
        try:
            yield conn
        finally:
            conn.close()

    def committed(self, func, *args, alias="route", **kwargs):
        with self.connection(alias) as conn:
            with conn:
                return func(conn, *args, **kwargs)

    def audit(self, statement, args=()):
        with self.connection("owner") as conn:
            with conn:
                return sql(conn, statement, args)

    def start(self, message="CE task", actor=None, parent=None, request=None):
        result = self.committed(ce_start, actor, message, request or "external:" + uid(), parent)
        self.check("start admitted", result.get("ok"), result)
        return result

    def worker(self, responses=(), **kwargs):
        worker = CeWorker(lambda: self.setup.connect_route(self.db), llm=FakeLLM(responses), **kwargs)
        return contextlib.closing(worker)

    def state(self, run_id):
        return self.committed(poll, None, run_id)

    def fingerprint(self, run_id=None, conn=None):
        # Owner audit only; this is never used for worker execution/discovery.
        query = ("SELECT jsonb_build_object(" 
                          "'sessions',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY session_id),'[]') FROM sessions s WHERE %s::uuid IS NULL OR session_id=%s::uuid),"
                          "'effects',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY effect_id),'[]') FROM effects e WHERE %s::uuid IS NULL OR session_id=%s::uuid),"
                          "'events',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY session_id,seq),'[]') FROM events e WHERE %s::uuid IS NULL OR session_id=%s::uuid),"
                          "'runs',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY run_id),'[]') FROM v13_ce_runs r WHERE %s::uuid IS NULL OR run_id=%s::uuid),"
                          "'operations',(SELECT coalesce(jsonb_agg(to_jsonb(o) ORDER BY operation_id),'[]') FROM v13_ce_operations o WHERE %s::uuid IS NULL OR run_id=%s::uuid),"
                          "'epochs',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY epoch_id),'[]') FROM v13_ce_epochs e WHERE %s::uuid IS NULL OR run_id=%s::uuid),"
                          "'snapshots',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY run_id),'[]') FROM v13_ce_snapshots s WHERE %s::uuid IS NULL OR run_id=%s::uuid),"
                          "'wakes',(SELECT coalesce(jsonb_agg(to_jsonb(w) ORDER BY wake_id),'[]') FROM v13_ce_wakes w WHERE %s::uuid IS NULL OR run_id=%s::uuid))")
        args = (run_id, run_id) * 8
        return self.audit(query, args) if conn is None else sql(conn, query, args)

    def denied(self, conn, statement, args=(), code="42501", message=None):
        try:
            sql(conn, statement, args)
        except psycopg2.Error as exc:
            conn.rollback()
            self.check("SQL rejected with expected boundary", exc.pgcode == code and (message is None or message in str(exc)),
                       (exc.pgcode, str(exc)))
        else:
            conn.rollback()
            self.check("SQL must be rejected", False, statement)

    def zero(self, run_id, func, *args, reason, **kwargs):
        before = self.fingerprint(run_id)
        with self.connection() as conn:
            with conn:
                result = func(conn, *args, **kwargs)
                self.check(f"zero-write rejection {reason}", not result.get("ok") and result.get("reason") == reason, result)
        self.check("rejection preserved all business rows", self.fingerprint(run_id) == before)
        return result


class ThreadCall:
    """Explicit entry/result/commit barriers; exceptions are re-raised on join."""
    def __init__(self, connect, action, hold_commit=False):
        self.entered, self.finished, self.release = threading.Event(), threading.Event(), threading.Event()
        self.committed = threading.Event()
        self.result = self.error = self.pid = None
        self.hold_commit = hold_commit
        self.connect, self.action = connect, action
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        conn = None
        try:
            conn = self.connect()
            self.pid = conn.get_backend_pid()
            self.entered.set()
            with conn:
                sql(conn, "SET LOCAL statement_timeout='15s'")
                self.result = self.action(conn)
                self.finished.set()
                if self.hold_commit and not self.release.wait(10):
                    raise TimeoutError("commit barrier not released")
            self.committed.set()
        except BaseException as exc:
            self.error = exc
            self.finished.set()
        finally:
            if conn is not None:
                conn.close()

    def __enter__(self):
        self.thread.start()
        if not self.entered.wait(10):
            raise TimeoutError("thread did not enter")
        return self

    def __exit__(self, *exc):
        self.release.set()
        self.thread.join(20)
        if self.thread.is_alive():
            raise TimeoutError("database thread leaked")
        if self.error is not None and exc[0] is None:
            raise self.error


def wait_blocked(g, call, blocker):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        blocked = g.audit("SELECT %s=ANY(pg_blocking_pids(%s))", (blocker, call.pid))
        if blocked:
            g.check("second connection is really blocked on first transaction", not call.finished.is_set())
            return
        if call.finished.is_set():
            raise AssertionError(f"expected real lock wait, completed early: {call.result!r}, {call.error!r}")
        time.sleep(0.005)
    raise TimeoutError("did not observe PostgreSQL lock barrier")


def tool_call(task="original task", call_id="call_0"):
    return {"id": call_id, "name": "spawn_subsession", "args": {"task": task}}


def tool_payload(source, index=0, task="original task", call_id="call_0"):
    return {"tool": "spawn_subsession", "params": {"task": task}, "source_operation_id": source,
            "tool_call_index": index, "tool_call_id": call_id}


def waiting(channel="human", kind="question"):
    return {"text": "A question", "ce_status": "waiting_for_input",
            "interaction": {"id": uid(), "kind": kind, "channel": channel}}


def native_load_untouched(g):
    g.check("real before/after captured", g.db.before is not None and g.db.after is not None)
    g.setup.validate_delta(g.db.before, g.db.after)
    for key in ("functions", "relations", "roles", "memberships", "db_acl", "schema_acl"):
        old = g.db.before[key]
        new = g.db.after[key]
        g.check("Stage 39 immutable " + key, all(row in new for row in old))
    load = load_module(ROOT / "load.py", "ce_gate_v13_load")
    g.check("loader tail exactly Stage 39 then CE/40", len(load.SQL_LOAD_ORDER) == 40
            and [p.name for p in load.SQL_LOAD_ORDER[-2:]] == ["v13_fair_claim.sql", "v13_ce_run.sql"])
    for path in load.SQL_LOAD_ORDER[:39]:
        rel = str(path.relative_to(REPO))
        revision = PHASE_D if "fair_claim/" in rel else BASE
        original = subprocess.check_output(["git", "show", f"{revision}:{rel}"], cwd=REPO)
        if rel == "v13/plan_arm/v13_plan_arm.sql":
            plan = load_module(ROOT / "plan_arm/test_plan_arm.py", "ce_gate_r0_bytes")
            plan.r0_source_scope()
            g.check("plan_arm R0 sentinel removal restores every baseline byte", True)
        else:
            g.check("frozen SQL bytes " + rel, path.read_bytes() == original)
    g.setup.validate_deployment_restrictions(g.db.server, g.db.name, g.db.roles)
    g.check("database/schema ACL separately verified", True)


def native_plan_arm_closed_set(g):
    plan = load_module(ROOT / "plan_arm/test_plan_arm.py", "ce_gate_plan_arm")
    # Includes in-memory missing-file/extra.py/41/40a/not_scheduled negatives.
    plan.r1_phase_d_prefix_allowance()
    g.check("real plan_arm closure and all synthetic negative mutations", True)
    files = {p.name for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in (".py", ".sql", ".md")}
    g.check("CE exact four source files", files == {"test_ce_run.py", "setup_db.py", "v13_ce_run.sql", "README.md"}, files)
    plan.r0_source_scope()
    g.check("frozen protected function/module closed set", True)


def native_frozen_driver_bytes(g):
    plan = load_module(ROOT / "plan_arm/test_plan_arm.py", "ce_gate_driver_freeze")
    current = (ROOT / "loop_driver/driver.py").read_bytes()
    original = subprocess.check_output(["git", "show", f"{BASE}:v13/loop_driver/driver.py"], cwd=REPO)
    plan.r1_driver_restore(current, original)
    plan.r1_freeze_positive_proof()
    g.check("unique R1 sentinel and exact outside bytes, including negative mutations", True)
    g.check("no controller or second advance host", b"run_controller_once" not in current
            and "v13_advance" not in inspect.getsource(CeWorker))
    definitions = [r[0] for r in g.db.after["functions"] if r[0].startswith("v13_advance(")]
    g.check("single frozen advance definition", len(definitions) == 1, definitions)


def native_start_identity(g):
    a = g.start("root original")
    sid = a["run_id"]
    g.check("new run is headless session initial identity", sid == a["session_id"] and a["status"] == "running"
            and all(a[k] == 1 for k in ("registration_generation", "epoch_ordinal", "continuity_generation", "revision")))
    row = g.audit("SELECT jsonb_build_array(parent_session_id,parent_cutoff_seq,status,next_seq,turn_no,route_policy_name,route_policy_version) FROM sessions WHERE session_id=%s", (sid,))
    g.check("root defaults followed by user/message turn increment", row == [None, None, "ready", 1, 1, "default", 1], row)
    g.check("frozen turn_no default remains zero", g.audit(
        "SELECT pg_get_expr(d.adbin,d.adrelid)='0' FROM pg_attrdef d JOIN pg_attribute a "
        "ON a.attrelid=d.adrelid AND a.attnum=d.adnum WHERE a.attrelid='sessions'::regclass AND a.attname='turn_no'"))
    g.check("initial epoch is open", g.audit("SELECT transition_kind='initial' AND closed_at IS NULL FROM v13_ce_epochs WHERE run_id=%s", (sid,)))
    different = g.start("root original")
    g.check("different request always creates a different run", different["run_id"] != sid)
    for request_id in (None, "", "r" * 513):
        g.zero(None, ce_start, None, "valid message", request_id, reason="invalid_args")
    for message in (None, "", "  ", "x" * 65537, "\u4e2d" * 21846):
        g.zero(None, ce_start, None, message, "external:" + uid(), reason="invalid_args")
    with g.connection() as conn:
        before = g.fingerprint()
        rejected = ce_start(conn, None, "foreign", uid(), session_id=uid())
        g.check("foreign session_id rejected before SQL", rejected["reason"] == "invalid_args"
                and conn.get_transaction_status() == TRANSACTION_STATUS_IDLE and g.fingerprint() == before)
    request = "external:concurrent:" + uid()
    with g.connection() as first:
        result = ce_start(first, None, "same request", request)
        with ThreadCall(lambda: g.setup.connect_route(g.db), lambda c: ce_start(c, None, "same request", request)) as other:
            wait_blocked(g, other, first.get_backend_pid())
            first.commit()
        g.check("concurrent request replay keeps exact identity", other.result == result, other.result)
    g.check("only one concurrent start row", g.audit("SELECT count(*) FROM v13_ce_operations WHERE request_id=%s", (request,)) == 1)
    g.zero(None, ce_start, None, "changed", request, reason="request_id_conflict")
    n = g.audit("SELECT next_seq FROM sessions WHERE session_id=%s", (sid,))
    child_request = "external:child:" + uid()
    with g.connection() as first:
        child = ce_start(first, sid, "child", child_request, sid)
        g.check("self actor can create child", child.get("ok"), child)
        with ThreadCall(lambda: g.setup.connect_owner_database(g.db), lambda c: sql(
                c, "SELECT v13_append_event(%s::uuid,%s::uuid,'user/message',%s::jsonb)",
                (sid, uid(), Json({"message": "after child cutoff"})))) as append:
            wait_blocked(g, append, first.get_backend_pid())
            first.commit()
    cid = child["run_id"]
    g.check("child cutoff includes precisely committed prefix", g.audit(
        "SELECT parent_session_id=%s::uuid AND parent_cutoff_seq=%s FROM sessions WHERE session_id=%s", (sid, n - 1, cid)))
    inherited = g.audit("WITH RECURSIVE lineage(sid,cut,depth) AS ("
                        "SELECT session_id,NULL::bigint,0 FROM sessions WHERE session_id=%s UNION ALL "
                        "SELECT s.parent_session_id,s.parent_cutoff_seq,l.depth+1 FROM lineage l "
                        "JOIN sessions s ON s.session_id=l.sid WHERE s.parent_session_id IS NOT NULL) "
                        "SELECT jsonb_agg(jsonb_build_array(e.session_id,e.seq,e.payload) ORDER BY depth,e.seq) "
                        "FROM lineage l JOIN events e ON e.session_id=l.sid WHERE l.cut IS NULL OR e.seq<=l.cut", (cid,))
    g.check("actual event lineage contains before and excludes after cutoff", any(x[0] == sid for x in inherited)
            and not any(x[2].get("message") == "after child cutoff" for x in inherited), inherited)
    g.check("child replay never recalculates cutoff", g.committed(ce_start, sid, "child", child_request, sid) == child)
    g.check("frozen goal tree exposes actual CE child lineage", g.audit(
        "SELECT count(*) FROM v_goal_tree(%s::uuid) WHERE session_id=%s::uuid AND parent_session_id=%s::uuid",
        (sid, cid, sid)) == 1)
    grandchild = g.start("direct-parent actor authorizes child start", actor=sid, parent=cid)
    g.check("allowed direct parent actor can start grandchild", g.audit(
        "SELECT parent_session_id=%s::uuid FROM sessions WHERE session_id=%s", (cid, grandchild["run_id"])))
    # Reverse serialization: parent append owns session lock before start.
    with g.connection("owner") as first:
        seq = sql(first, "SELECT v13_append_event(%s::uuid,%s::uuid,'user/message',%s::jsonb)", (sid, uid(), Json({"message": "before second child"})))
        with ThreadCall(lambda: g.setup.connect_route(g.db), lambda c: ce_start(c, sid, "child two", uid(), sid)) as other:
            wait_blocked(g, other, first.get_backend_pid())
            first.commit()
    second = other.result
    g.check("append-first cutoff includes committed append", second.get("ok") and g.audit(
        "SELECT parent_cutoff_seq=%s FROM sessions WHERE session_id=%s", (seq, second["run_id"])), second)
    stranger = g.start()["run_id"]
    g.zero(None, ce_start, stranger, "unauthorized child", uid(), sid, reason="unauthorized")
    with g.connection("owner") as owner:
        empty = str(sql(owner, "SELECT v13_open_session('{}'::jsonb)"))
        owner.commit()
    g.zero(None, ce_start, None, "empty parent", uid(), empty, reason="parent_prefix_empty")
    before = g.fingerprint()
    with g.connection() as conn:
        rolled = ce_start(conn, None, "rollback entire start", uid())
        g.check("uncommitted start invisible to second connection", g.audit("SELECT count(*) FROM sessions WHERE session_id=%s", (rolled["run_id"],)) == 0)
        conn.rollback()
    g.check("start rollback leaves no sessions/CE/effects/events/wakes", g.fingerprint() == before)
    # Fail after the private INSERT has succeeded: the original trigger/whole
    # transaction must roll the new session back rather than compensate later.
    request = "external:start-fault:" + uid()
    before = g.fingerprint()
    with g.connection("owner") as owner:
        sql(owner, "CREATE FUNCTION public.ce_gate_start_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                   "IF NEW.request_id='" + request + "' THEN RAISE EXCEPTION 'ce_gate_start_after_insert'; END IF; RETURN NEW; END $$")
        sql(owner, "CREATE TRIGGER ce_gate_start_fault BEFORE INSERT ON v13_ce_operations FOR EACH ROW EXECUTE FUNCTION ce_gate_start_fault()")
        owner.commit()
    try:
        with g.connection() as conn:
            g.denied(conn, "SELECT v13_ce_run_start(NULL::uuid,'whole start rollback',%s,NULL::uuid)",
                     (request,), code="P0001", message="ce_gate_start_after_insert")
        g.check("post-insert SQL exception rolls back all start objects", g.fingerprint() == before)
    finally:
        with g.connection("owner") as owner:
            sql(owner, "DROP TRIGGER ce_gate_start_fault ON v13_ce_operations")
            sql(owner, "DROP FUNCTION public.ce_gate_start_fault()")
            owner.commit()


def native_poll_pure(g):
    a = g.start()
    sid = a["run_id"]
    before = g.fingerprint()
    with g.connection() as conn:
        sql(conn, "SET TRANSACTION READ ONLY")
        for _ in range(3):
            p = poll(conn, None, sid)
        conn.commit()
    g.check("poll works inside READ ONLY", p["status"] == "running" and p["revision"] == 1)
    stranger = g.start()["run_id"]
    before = g.fingerprint()
    for actor, target, registration in ((stranger, sid, None), (None, uid(), None), (None, sid, 2)):
        p = g.committed(poll, actor, target, registration)
        g.check("poll uniformly synthesizes expired", p == {"schema_version": 1, "ok": True, "reason": "expired"}, p)
    g.check("poll zero writes to every business object", g.fingerprint() == before)


def native_wait_cursor(g):
    a = g.start()
    sid = a["run_id"]
    with g.connection("recall") as conn:
        start_time = time.monotonic()
        r = ce_wait(conn, None, sid, 1, 1, 0.02, 0.01)
        g.check("finite idle timeout fixed eight-key DTO", set(r) == WAIT_KEYS and r["reason"] == "timed_out"
                and 0.015 <= time.monotonic() - start_time < 2, r)
        idle(conn)
        for timeout, interval, cursor in ((float("nan"), .05, 0), (float("inf"), .05, 0), (-1, .05, 0),
                                           (3601, .05, 0), (0, float("nan"), 0), (0, .001, 0), (0, 2, 0), (0, .05, -1)):
            with mock.patch(__name__ + ".sql", side_effect=AssertionError("invalid wait executed SQL")):
                invalid = ce_wait(conn, None, sid, 1, 1, timeout, interval, cursor)
            g.check("invalid wait is zero SQL", set(invalid) == WAIT_KEYS and invalid["reason"] == "invalid_wait_args")
        sql(conn, "SELECT 1")
        try:
            ce_wait(conn, None, sid, 1, 1, 0)
        except RuntimeError:
            g.check("wait never commits another caller transaction", conn.get_transaction_status() != TRANSACTION_STATUS_IDLE)
        else:
            g.check("busy wait connection must reject", False)
        conn.rollback()
    for registration, epoch, cursor in ((None, 1, 0), (1, None, 0), (1, 1, None), (0, 1, 0), (1, 0, 0), (1, 1, -1)):
        with g.case(f"SQL wait args {registration}/{epoch}/{cursor}"):
            invalid = g.committed(wait_check, None, sid, registration, epoch, cursor)
            g.check("SQL wait rejects null/nonpositive identities and null/negative cursor", set(invalid) == WAIT_KEYS
                    and invalid["reason"] == "invalid_wait_args", invalid)
    future = g.committed(wait_check, None, sid, 1, 2)
    g.check("future epoch invalid, fixed keys", set(future) == WAIT_KEYS and future["reason"] == "invalid_wait_args", future)
    for actor, target, reg in ((None, uid(), 1), (None, sid, 2), (uid(), sid, 1)):
        r = g.committed(wait_check, actor, target, reg, 1)
        g.check("wait hides missing/unauthorized/stale registration", set(r) == WAIT_KEYS and r["reason"] == "expired", r)
    g.committed(steer, sid, sid, "self interruption suppressed", uid(), 1)
    g.committed(steer, None, sid, "operator interruption", uid(), 1)
    g.committed(cancel, None, sid, uid())
    r = g.committed(wait_check, sid, sid, 1, 1)
    g.check("self-origin still interrupts with wake ID but hides only body", r["reason"] == "interrupted_by_steering"
            and r["wake_id"] is not None and "steering_message" in r["snapshot"] and r["snapshot"]["steering_message"] is None, r)
    g.check("interrupted annotation preserves current terminal snapshot", r["snapshot"]["status"] == "cancelled"
            and r["snapshot"]["revision"] == g.state(sid)["revision"] and r["snapshot"]["interaction"] is None)
    external = g.committed(wait_check, sid, sid, 1, r["epoch_ordinal"], r["wake_id"])
    g.check("ordinary snapshot wake cannot swallow next external steering", external["reason"] == "interrupted_by_steering"
            and external["wake_id"] > r["wake_id"] and external["snapshot"]["steering_message"] == "operator interruption", external)
    next_r = g.committed(wait_check, sid, sid, 1, external["epoch_ordinal"], external["wake_id"])
    g.check("same waiter cursor consumes self/external wakes once then actionable", next_r["reason"] == "actionable", next_r)
    again = g.committed(wait_check, None, sid, 1, 1)
    g.check("independent NULL-operator waiter sees full original self wake", again["reason"] == "interrupted_by_steering"
            and again["wake_id"] == r["wake_id"] and again["snapshot"]["steering_message"] == "self interruption suppressed", again)
    g.check("poll remains unannotated", "steering_message" not in g.state(sid))
    # Active wakes use current epoch; reactivation wakes retain the OLD epoch.
    g.committed(steer, None, sid, "epoch two", uid(), 1)
    with g.worker() as worker:
        worker.run(sid)
    g.committed(steer, None, sid, "epoch three", uid(), 2)
    with g.worker() as worker:
        worker.run(sid)
    cursor, epoch, seen = 0, 1, []
    for _ in range(8):
        with g.connection("recall") as conn:
            r = ce_wait(conn, None, sid, 1, epoch, 0, .01, cursor)
        if r["reason"] != "interrupted_by_steering":
            break
        seen.append((r["wake_id"], r["epoch_ordinal"]))
        cursor, epoch = r["wake_id"], r["epoch_ordinal"]
    g.check("cross-call cursor drains every old-epoch wake in order", len(seen) == 4
            and [e for _, e in seen] == [1, 1, 1, 2] and r["reason"] == "actionable" and r["epoch_ordinal"] == 3, (seen, r))
    # Lost notification: no LISTEN existed when terminal was committed.
    with g.connection("recall") as conn:
        r = ce_wait(conn, None, sid, 1, 1, 0, .01, cursor)
        g.check("deadline reread returns actionable without any notification", r["reason"] == "actionable")
        g.check("finally removed listener", sql(conn, "SELECT count(*) FROM pg_listening_channels()") == 0)
        conn.commit()
    # A notification can be discarded while the real second connection commits;
    # polling still finds actionable state without trusting a NOTIFY payload.
    missed = g.start()["run_id"]
    select_entered = threading.Event()
    def cancel_after_listener(conn):
        if not select_entered.wait(5):
            raise TimeoutError("waiter never reached idle select")
        return cancel(conn, None, missed, uid())
    with ThreadCall(lambda: g.setup.connect_route(g.db), cancel_after_listener) as control:
        with g.connection("recall") as conn:
            def discard_notification(*_):
                idle(conn)
                select_entered.set()
                if not control.committed.wait(5):
                    raise TimeoutError("cancel did not commit")
                return [], [], []
            with mock.patch.object(select, "select", side_effect=discard_notification):
                outcome = ce_wait(conn, None, missed, 1, 1, 1, .01)
    g.check("lost live notification rereads committed actionable state", outcome["reason"] == "actionable"
            and outcome["snapshot"]["status"] == "cancelled", outcome)
    advanced = g.start()["run_id"]
    g.committed(cancel, None, advanced, uid())
    g.committed(steer, None, advanced, "new epoch without actionable", uid(), 1)
    interruption = g.committed(wait_check, None, advanced, 1, 1)
    followed = g.committed(wait_check, None, advanced, 1, 1, interruption["wake_id"])
    g.check("same continuity epoch advancement after steering is explicit", followed["reason"] == "epoch_advanced" and followed["epoch_ordinal"] == 2, followed)
    with g.connection("recall") as conn:
        followed = ce_wait(conn, None, advanced, 1, 1, 0, .01, interruption["wake_id"])
    g.check("ce_wait follows epoch cursor before local timeout", followed["reason"] == "timed_out" and followed["epoch_ordinal"] == 2, followed)
    b = g.start()["run_id"]
    # Reserved fixture only: no six-verb producer changes continuity.
    with g.connection("owner") as conn:
        sql(conn, "UPDATE v13_ce_epochs SET closed_at=now() WHERE run_id=%s", (b,))
        sql(conn, "INSERT INTO v13_ce_epochs(run_id,ordinal,continuity_generation,registration_generation,transition_kind) "
                  "VALUES (%s,2,2,1,'unrelated')", (b,))
        sql(conn, "UPDATE v13_ce_runs SET current_epoch_ordinal=2,continuity_generation=2 WHERE run_id=%s", (b,))
        sql(conn, "UPDATE v13_ce_snapshots SET epoch_ordinal=2 WHERE run_id=%s", (b,))
        conn.commit()
    r = g.committed(wait_check, None, b, 1, 1)
    g.check("reserved continuity mismatch is superseded (fixture, not producer)", r["reason"] == "superseded", r)


def native_cancel_scope(g):
    parent = g.start()
    sid = parent["run_id"]
    child = g.start("child unaffected", parent=sid)
    child_before = g.fingerprint(child["run_id"])
    with g.worker() as worker:
        work = worker.prepare(sid)
        worker.perform(work)
        cancelled = g.committed(cancel, None, sid, "external:cancel:" + uid())
        snapshot = g.state(sid)
        result = worker.finish(work)
    g.check("cancel retains run and epoch ordinal", cancelled.get("ok") and snapshot["run_id"] == sid
            and snapshot["epoch_ordinal"] == 1 and snapshot["status"] == "cancelled", cancelled)
    g.check("claimed late success is truly settled, not provider-cancelled", result["receipt"]["outcome"] == "archived_stale"
            and result["receipt"]["effect_outcome"] == "succeeded" and not result["successors"], result)
    g.check("late receipt cannot revive either state", g.state(sid) == snapshot and g.audit(
        "SELECT status='cancelled' FROM sessions WHERE session_id=%s", (sid,)))
    g.check("cancel never cascades into child", g.fingerprint(child["run_id"]) == child_before)
    g.check("closed pending stays closed", g.audit("SELECT status FROM v13_ce_operations WHERE operation_id=%s", (parent["operation_id"],)) == "closed")
    events = g.audit("SELECT jsonb_agg(jsonb_build_array(type,payload) ORDER BY seq) FROM events WHERE session_id=%s AND type IN ('cancel/requested','session/cancelled')", (sid,))
    g.check("cancelled event seals request, preserving real actor/request audit", len(events) == 2
            and any(e[0] == "session/cancelled" for e in events), events)
    a = g.start()
    result = g.committed(cancel, a["run_id"], a["run_id"], "external:single:" + uid())
    g.check("ready only target effect cancelled and lease cleared", result.get("ok") and g.audit(
        "SELECT status='cancelled' AND fence>0 AND lease_owner IS NULL AND lease_until IS NULL FROM effects WHERE effect_id=%s", (a["effect_id"],)))
    request = "external:cancel-replay:" + uid()
    b = g.start()
    first = g.committed(cancel, None, b["run_id"], request)
    before = g.fingerprint(b["run_id"])
    replay = g.committed(cancel, None, b["run_id"], request)
    g.check("cancel stored replay is zero-write", replay == first and g.fingerprint(b["run_id"]) == before)
    # Wall-clock lease expiry alone does not invalidate a real, unrequeued claim.
    b = g.start()
    with g.worker(lease_ms=20) as worker:
        work = worker.prepare(b["run_id"])
        worker.perform(work)
        g.committed(cancel, None, b["run_id"], uid())
        time.sleep(.03)
        result = worker.finish(work)
        g.check("unrequeued expired tokens may still settle known late IO", result["receipt"]["effect_outcome"] == "succeeded", result)
    b = g.start()
    with g.worker(lease_ms=20) as worker:
        work = worker.prepare(b["run_id"])
        worker.perform(work)
        g.committed(cancel, None, b["run_id"], uid())
        time.sleep(.03)
        g.committed(sql, "SELECT public.v13_ce_requeue_stale()")
        before = g.fingerprint(b["run_id"])
        result = worker.finish(work)
        g.check("cancelled late recycled tokens cannot fake success or revive", result["receipt"].get("outcome") in ("stale_claim", "unknown_wall")
                and not result["successors"] and g.fingerprint(b["run_id"]) == before, result)


def native_steer_paths(g):
    a = g.start("old bound request")
    sid = a["run_id"]
    for epoch in (None, 0, -1):
        g.zero(sid, steer, None, sid, "invalid active epoch", uid(), epoch, reason="invalid_args")
    s = g.committed(steer, None, sid, "new queued instruction", "external:steer:" + uid(), 1)
    g.check("active steer remains same epoch and queues behind old ready", s.get("ok") and s["epoch_ordinal"] == 1, s)
    llm = FakeLLM([{"text": "old result", "tool_calls": [tool_call("must not execute", "orphan")]}, {"text": "new result"}])
    with contextlib.closing(CeWorker(lambda: g.setup.connect_route(g.db), llm=llm)) as worker:
        old = worker.prepare(sid)
        g.check("old ready effect is claimable after active steer", old.tokens["effect_id"] == a["effect_id"])
        worker.perform(old)
        result = worker.finish(old)
        g.check("old driving receipt archived and never publishes", result["receipt"]["outcome"] == "archived_stale"
                and not result["successors"] and g.state(sid)["status"] == "running", result)
        worker.run(sid)
    g.check("queued follow-up actually consumes steer message", llm.calls[1]["request"].get("message") == "new queued instruction", llm.calls)
    projected = llm.calls[1]["history"]
    g.check("orphan tool protocol becomes superseded ordinary history", any(e["payload"].get("superseded") for e in projected)
            and not any(e["type"] == "tool/call" or e["payload"].get("tool_calls") for e in projected), projected)
    g.check("raw transcript retains orphan call, no Fake execution/effect", g.audit(
        "SELECT count(*) FROM events WHERE session_id=%s AND type='tool/call'", (sid,)) == 1
        and g.audit("SELECT count(*) FROM effects WHERE session_id=%s AND kind='tool'", (sid,)) == 0)
    g.zero(sid, steer, None, sid, "missing epoch", uid(), None, reason="invalid_args")
    g.zero(sid, steer, None, sid, "nonpositive epoch", uid(), 0, reason="invalid_args")
    g.zero(sid, steer, None, sid, "stale CAS", uid(), 2, reason="stale_epoch")
    for terminal in ("completed", "failed", "cancelled"):
        b = g.start()["run_id"]
        if terminal == "cancelled":
            g.committed(cancel, None, b, uid())
        else:
            with g.worker([{"text": "old terminal text", "ce_status": terminal,
                            "failure_reason": {"old": "terminal failure"}}]) as worker:
                worker.run(b)
        terminal_state = g.state(b)
        if terminal != "cancelled":
            g.check("reactivation fixture contains obsolete terminal fields " + terminal,
                    terminal_state["failure_reason"] == {"old": "terminal failure"}
                    and terminal_state["assistant_text"] == "old terminal text", terminal_state)
        for epoch in (None, 0, -1):
            g.zero(b, steer, None, b, "invalid terminal epoch", uid(), epoch, reason="invalid_args")
        request = "external:revive:" + uid()
        r = g.committed(steer, None, b, "revive " + terminal, request, 1)
        revived_state = g.state(b)
        g.check("terminal reactivation creates epoch and keeps continuity " + terminal,
                r.get("ok") and r["epoch_ordinal"] == 2 and revived_state["continuity_generation"] == 1, r)
        g.check("terminal reactivation clears obsolete terminal fields " + terminal,
                revived_state["status"] == "running" and revived_state["failure_reason"] is None
                and revived_state["assistant_text"] is None, revived_state)
        g.check("both persisted failure fields clear before any Worker step " + terminal,
                g.audit("SELECT r.failure_reason IS NULL AND s.failure_reason IS NULL "
                        "FROM v13_ce_runs r JOIN v13_ce_snapshots s USING(run_id) WHERE run_id=%s", (b,)))
        waited = g.committed(wait_check, None, b, 1, 1)
        g.check("reactivation wait snapshot has no obsolete terminal fields " + terminal,
                waited["snapshot"]["status"] == "running" and waited["snapshot"]["failure_reason"] is None
                and waited["snapshot"]["assistant_text"] is None, waited)
        before = g.fingerprint(b)
        replay = g.committed(steer, None, b, "revive " + terminal, request, 1)
        g.check("reactivation replay precedes old-epoch CAS " + terminal,
                replay == r and g.fingerprint(b) == before, replay)
        g.zero(b, steer, None, b, "stale old epoch", uid(), 1, reason="stale_epoch")
        with g.worker([{"text": "revived with tool", "tool_calls": [tool_call()]}, {"text": "revived done"}]) as worker:
            worker.run(b)
        g.check("reactivated run actually completes including tool", g.state(b)["status"] == "completed")
    # Reactivation cannot skip a still-claimed effect from the closed epoch.
    b = g.start()
    with g.worker() as worker:
        late = worker.prepare(b["run_id"])
        worker.perform(late)
        g.committed(cancel, None, b["run_id"], uid())
        revived = g.committed(steer, None, b["run_id"], "after late old epoch", uid(), 1)
        state = g.state(b["run_id"])
        d = g.committed(discover, None, b["run_id"])
        g.check("new epoch queues behind still-claimed old effect", revived.get("ok") and revived["epoch_ordinal"] == 2
                and len(d["operations"]) == 1 and d["operations"][0]["queued"], d)
        settled = worker.finish(late)
        g.check("old epoch late settlement commits archive and current-epoch promotion", settled["receipt"]["outcome"] == "archived_stale"
                and not settled["successors"] and g.state(b["run_id"]) == state, settled)
        worker.run(b["run_id"])
        g.check("old claimed handoff actually resumes new epoch", g.state(b["run_id"])["status"] == "completed")
    for channel in ("human", "ce"):
        b = g.start()["run_id"]
        w = waiting(channel, "instruction")
        with g.worker([w]) as worker:
            worker.run(b)
        answer = "instruction delivered " + channel
        r = g.committed(steer, None, b, answer, uid(), 1)
        g.check("instruction steer resumes same epoch " + channel, r.get("ok") and r["epoch_ordinal"] == 1 and g.state(b)["interaction"] is None, r)
        if channel == "human":
            h = g.audit("SELECT result FROM effects WHERE session_id=%s AND kind='human'", (b,))
            g.check("human instruction is exact one-of response", h == {"schema_version": 1, "interaction_ref": w["interaction"]["id"], "response": answer}, h)
        else:
            g.check("CE instruction never creates human effect", g.audit("SELECT count(*) FROM effects WHERE session_id=%s AND kind='human'", (b,)) == 0)
        promoted = g.committed(discover, None, b)
        g.check("instruction follow-up is promoted to a bound ready continuation " + channel,
                len(promoted["operations"]) == 1 and promoted["operations"][0]["verb"] == "admit_turn"
                and promoted["operations"][0]["effect_status"] == "ready"
                and not promoted["operations"][0]["queued"], promoted)
        with g.worker() as worker:
            worker.run(b)
            g.check("instruction steer is consumed and completes " + channel,
                    len(worker.llm.calls) == 1 and worker.llm.calls[0]["request"].get("message") == answer
                    and g.state(b)["status"] == "completed", worker.llm.calls)
    b = g.start()["run_id"]
    with g.worker([waiting()]) as worker:
        worker.run(b)
    g.zero(b, steer, None, b, "not instruction", uid(), 1, reason="use_respond")


def native_respond_once(g):
    for channel in ("human", "ce"):
        a = g.start()
        sid = a["run_id"]
        w = waiting(channel)
        with g.worker([w]) as worker:
            worker.run(sid)
        iid = w["interaction"]["id"]
        g.zero(sid, respond, None, sid, uid(), {"schema_version": 1, "response": "wrong"}, uid(), reason="interaction_mismatch")
        for response in ({"schema_version": 1, "skip": False},
                         {"schema_version": 1, "answers": {}},
                         {"schema_version": 1, "answers": None},
                         {"schema_version": 1, "response": None},
                         {"schema_version": 1, "response": ""},
                         {"schema_version": 1, "response": "   "},
                         {"schema_version": 1, "skip": None},
                         {"schema_version": 1, "skip": "true"},
                         {"schema_version": 1, "response": {}},
                         {"schema_version": 1, "response": []},
                         {"schema_version": 1, "response": "yes", "skip": False},
                         {"schema_version": 1, "response": "yes", "answers": None},
                         {"schema_version": 1, "approval": "yes"}):
            g.zero(sid, respond, None, sid, iid, response, uid(), reason="unsupported_response")
        answer = {"schema_version": 1, "response": "external answer"}
        request = "external:respond:" + uid()
        first = g.committed(respond, None, sid, iid, answer, request)
        g.check("respond clears interaction without changing epoch " + channel,
                first.get("ok") and g.state(sid)["epoch_ordinal"] == 1 and g.state(sid)["interaction"] is None, first)
        before = g.fingerprint(sid)
        g.check("same request replay preserves response", g.committed(respond, None, sid, iid, answer, request) == first)
        g.check("respond replay changes no rows", g.fingerprint(sid) == before)
        g.zero(sid, respond, None, sid, iid, answer, uid(), reason="interaction_mismatch")
        g.zero(sid, respond, None, sid, iid, {"schema_version": 1, "response": "changed"}, request, reason="request_id_conflict")
        if channel == "human":
            result = g.audit("SELECT jsonb_build_object('status',status,'result',result,'request',request) FROM effects WHERE session_id=%s AND kind='human'", (sid,))
            g.check("human exact interaction_ref and non-null one-of", result["status"] == "succeeded"
                    and result["request"]["interaction_ref"] == iid
                    and result["result"] == {"schema_version": 1, "interaction_ref": iid, "response": "external answer"}, result)
        else:
            g.check("CE response has no human effect", g.audit("SELECT count(*) FROM effects WHERE session_id=%s AND kind='human'", (sid,)) == 0)
        with g.worker() as worker:
            worker.run(sid)
        g.check("both respond channels actually continue LLM", g.state(sid)["status"] == "completed")
        for value in ({"response": False}, {"response": 0}, {"answers": {"choice": "yes"}}, {"skip": True}):
            a = g.start()
            sid = a["run_id"]
            question = waiting(channel)
            with g.worker([question]) as worker:
                worker.run(sid)
            answer = {"schema_version": 1, **value}
            result = g.committed(respond, None, sid, question["interaction"]["id"], answer, uid())
            g.check("legal one-of value admitted on " + channel, result.get("ok"), (answer, result))
            with g.worker() as worker:
                worker.run(sid)
                g.check("legal one-of answer consumed and completes on " + channel,
                        len(worker.llm.calls) == 1
                        and worker.llm.calls[0]["request"].get("response") == answer
                        and g.state(sid)["status"] == "completed", worker.llm.calls)


def native_acl_roles(g):
    a = g.start()
    sid = a["run_id"]
    child = g.start("ACL child", actor=sid, parent=sid)["run_id"]
    stranger = g.start()["run_id"]
    for alias in ("route", "recall", "worker", "plain"):
        with g.connection(alias) as conn:
            login = sql(conn, "SELECT jsonb_build_array(session_user,current_user,(SELECT rolsuper FROM pg_roles WHERE rolname=current_user))")
            conn.commit()
            g.check("real distinct non-superuser LOGIN " + alias, login == [g.db.roles[alias], g.db.roles[alias], False], login)
            for table in ("v13_ce_runs", "v13_ce_epochs", "v13_ce_operations", "v13_ce_snapshots", "v13_ce_wakes"):
                for statement in (f"SELECT * FROM public.{table}", f"DELETE FROM public.{table} WHERE false"):
                    g.denied(conn, statement)
            g.denied(conn, "SELECT v13_ce_insert_session(%s::uuid,NULL::uuid,NULL::bigint)", (uid(),))
            g.denied(conn, "SELECT v13_ce_tool_schema('spawn_subsession')")
            g.denied(conn, "CREATE TEMP TABLE effects(x int)")
            g.denied(conn, "CREATE TABLE public.ce_shadow(x int)")
            g.denied(conn, "SET ROLE v13_spawn_owner")
            if alias not in ("route",):
                g.denied(conn, "SELECT public.v13_ce_requeue_stale()")
                g.denied(conn, "SELECT v13_ce_run_start(NULL::uuid,'forbidden',%s,NULL::uuid)", (uid(),))
                g.denied(conn, "SELECT v13_ce_discover_work(NULL::uuid,%s::uuid)", (sid,))
    maintenance = g.committed(sql, "SELECT public.v13_ce_requeue_stale()")
    g.check("non-superuser route maintenance wrapper exact DTO", set(maintenance) == {"schema_version", "ok", "recovery"}
            and maintenance["schema_version"] == 1 and maintenance["ok"] is True and isinstance(maintenance["recovery"], dict), maintenance)
    for actor in (None, sid, child):
        r = g.committed(poll, actor, child, alias="recall")
        g.check("recall NULL/self/parent read allowed", r.get("status") == "running", r)
    r = g.committed(poll, stranger, child, alias="recall")
    g.check("recall foreign actor uniformly expired", r.get("reason") == "expired", r)
    g.zero(sid, steer, stranger, sid, "stranger", uid(), 1, reason="unauthorized")
    with g.connection() as conn:
        sql(conn, "SET ROLE v13_route")
        r = ce_start(conn, None, "SET ROLE route", uid())
        conn.commit()
        g.check("route SET ROLE preserves real caller operator", r.get("ok"), r)
        sql(conn, "RESET ROLE")
        conn.commit()
        g.denied(conn, "INSERT INTO public.sessions DEFAULT VALUES")
    with g.connection("owner") as conn:
        for role in ("v13_worker", "v13_recall", g.db.roles["plain"]):
            sql(conn, 'SET ROLE "' + role + '"')
            g.denied(conn, "SELECT v13_ce_run_start(NULL::uuid,'downgraded',%s,NULL::uuid)", (uid(),))
            sql(conn, "RESET ROLE")
            conn.commit()
        g.denied(conn, "INSERT INTO public.sessions DEFAULT VALUES", code="P0001", message="sessions insert owner")
    g.setup.validate_delta(g.db.before, g.setup.snapshot(g.db.server, g.db))
    g.check("unique insert-helper owner exception and frozen ACL/roles preserved", True)


def native_io_boundary(g):
    a, b = g.start(), g.start()
    sid = a["run_id"]
    with g.connection() as first:
        winner = claim(first, None, a["operation_id"])
        with ThreadCall(lambda: g.setup.connect_route(g.db), lambda c: claim(c, None, a["operation_id"])) as other:
            wait_blocked(g, other, first.get_backend_pid())
            first.commit()
    g.check("same effect two real connections have single claim winner", winner.get("ok") and not other.result.get("ok"), other.result)
    g.check("scoped claim leaves different run ready", g.audit("SELECT status FROM effects WHERE effect_id=%s", (b["effect_id"],)) == "ready")
    with g.worker() as worker:
        g.check("restart only run_id never repeats claimed IO", worker.step(sid) is None and not worker.llm.calls)
    # Scoped claim preserves all frozen readiness gates, not just status.
    capped = g.start()
    with g.connection("owner") as owner:
        sql(owner, "UPDATE effects SET attempt_no=2147483647 WHERE effect_id=%s", (capped["effect_id"],))
        owner.commit()
    before = g.fingerprint(capped["run_id"])
    capped_claim = g.committed(claim, None, capped["operation_id"])
    g.check("scoped claim preserves frozen attempt cap", not capped_claim.get("ok")
            and g.fingerprint(capped["run_id"]) == before, capped_claim)
    ordered = g.start()
    with g.worker([{"text": "ordered predecessor", "tool_calls": [tool_call()]}]) as worker:
        first = worker.step(ordered["run_id"])
    next_op = first["successors"][0]
    with g.connection("owner") as owner:
        sql(owner, "UPDATE effects SET status='failed',op_seq=1,mutation_scope='ce_gate_order' WHERE effect_id=%s", (ordered["effect_id"],))
        sql(owner, "UPDATE effects SET op_seq=2,mutation_scope='ce_gate_order' WHERE effect_id=%s", (next_op["effect_id"],))
        owner.commit()
    before = g.fingerprint(ordered["run_id"])
    out_of_order = g.committed(claim, None, next_op["operation_id"])
    g.check("scoped claim rejects out-of-order mutation scope", not out_of_order.get("ok")
            and g.fingerprint(ordered["run_id"]) == before, out_of_order)
    with g.connection("owner") as owner:
        sql(owner, "UPDATE effects SET status='succeeded' WHERE effect_id=%s", (ordered["effect_id"],))
        owner.commit()
    in_order = g.committed(claim, None, next_op["operation_id"])
    g.check("same operation becomes claimable only after predecessor success", in_order.get("ok"), in_order)
    # Settle the original known tokens without a duplicate IO.
    with g.connection() as conn:
        r = accept(conn, None, a["operation_id"], winner, {"text": "single winner"})
        p = publish(conn, None, a["operation_id"], r["revision"], {"status": "completed"})
        conn.commit()
    g.check("claim winner can complete once", p.get("ok"), p)
    with g.worker() as worker:
        result = worker.step(b["run_id"])
        g.check("T1 commit -> IDLE fake -> complete T2 commit order", worker.calls == ["requeue_commit", "claim_commit", "fake_io_idle", "t2_commit"], worker.calls)
        g.check("T2 publication visible to second audit connection", result["receipt"]["replayed"] is False and g.state(b["run_id"])["status"] == "completed")
    a = g.start()
    sid = a["run_id"]
    steers = [g.committed(steer, None, sid, "queued " + str(i), uid(), 1) for i in range(3)]
    d = g.committed(discover, None, sid)
    g.check("discovery top-level and per-operation closed sets", set(d) == DISCOVERY_KEYS and all(set(o) == OP_KEYS for o in d["operations"]), d)
    g.check("discovery distinguishes ready and queued and is ordered", d["operations"][0]["effect_status"] == "ready"
            and all(o["queued"] and o["effect_id"] is None for o in d["operations"][1:])
            and [o["attempt_seq"] for o in d["operations"]] == sorted(o["attempt_seq"] for o in d["operations"]), d)
    with g.worker() as worker:
        for _ in range(4):
            worker.step(sid)
        g.check("multiple queued steer promotions retain admission order", [c["request"].get("message") for c in worker.llm.calls]
                == ["CE task", "queued 0", "queued 1", "queued 2"], worker.llm.calls)
    # Real promotion revalidation: tool queued behind original LLM, followed by steer.
    a = g.start()
    sid, source = a["run_id"], a["operation_id"]
    payload = tool_payload(source)
    queued = g.committed(admit, None, sid, 1, "admit_tool", payload, f"ce:{source}:tool:0", source)
    g.check("tool queued while previous effect active", queued.get("ok") and queued["queued"] and queued["effect_id"] is None, queued)
    s = g.committed(steer, None, sid, "after disabled tool", uid(), 1)
    with g.connection("owner") as owner:
        sql(owner, "UPDATE public.tools SET enabled=false WHERE name='spawn_subsession'")
        owner.commit()
    try:
        with g.worker() as worker:
            worker.step(sid)
        o = g.audit("SELECT jsonb_build_array(status,effect_id,result) FROM v13_ce_operations WHERE operation_id=%s", (queued["operation_id"],))
        g.check("disabled queued tool archived before enqueue", o[0] == "archived" and o[1] is None
                and o[2]["reason"] == "invalid_tool_at_promotion", o)
        d = g.committed(discover, None, sid)
        g.check("promotion continues past invalid tool to next queued steer", len(d["operations"]) == 1
                and d["operations"][0]["operation_id"] == s["operation_id"] and d["operations"][0]["effect_status"] == "ready", d)
        with g.worker() as worker:
            worker.run(sid)
        g.check("revalidated queue not running empty", g.state(sid)["status"] == "completed")
    finally:
        with g.connection("owner") as owner:
            sql(owner, "UPDATE public.tools SET enabled=true WHERE name='spawn_subsession'")
            owner.commit()


def native_receipt_fences(g):
    a = g.start()
    sid, op = a["run_id"], a["operation_id"]
    with g.worker() as worker:
        work = worker.prepare(sid)
        worker.perform(work)
        good_payload = receipt_payload(work.tokens, work.result)
        for key, bad in (("attempt_no", "1"), ("fence", "1"), ("effect_result", []),
                         ("effect_id", None), ("extra", 1)):
            payload = dict(good_payload)
            payload[key] = bad
            before_bad = g.fingerprint(sid)
            rejected = g.committed(sql, "SELECT v13_ce_accept_receipt(NULL::uuid,%s::uuid,%s,'succeeded',%s::jsonb)",
                                   (op, f"ce:{op}:receipt", Json(payload)))
            g.check("receipt types and exact four-key envelope reject " + key,
                    rejected.get("reason") == "invalid_receipt" and g.fingerprint(sid) == before_bad, rejected)
        before = g.audit("SELECT to_jsonb(o) FROM v13_ce_operations o WHERE operation_id=%s", (op,))
        mismatch = g.committed(accept, None, op, work.tokens, work.result, request_id="bad receipt")
        g.check("receipt request mismatch only appends dedicated audit", mismatch["reason"] == "receipt_request_mismatch"
                and g.audit("SELECT to_jsonb(o) FROM v13_ce_operations o WHERE operation_id=%s", (op,)) == before, mismatch)
        g.check("mismatch audit visible after COMMIT", g.audit("SELECT count(*) FROM events WHERE session_id=%s AND type='ce/receipt_request_mismatch'", (sid,)) == 1)
        class CrashBeforeCommit(Exception):
            pass
        before = g.fingerprint(sid)
        def crash(conn, item, received):
            g.check("accept has entered before simulated process crash", received.get("ok") and received["replayed"] is False)
            g.check("second connection still sees pre-T2 claim", g.audit("SELECT status FROM effects WHERE effect_id=%s", (item.tokens["effect_id"],)) == "claimed")
            raise CrashBeforeCommit()
        try:
            worker.finish(work, after_accept=crash)
        except CrashBeforeCommit:
            pass
        g.check("accept-before-COMMIT crash rolls entire T2 back", g.fingerprint(sid) == before)
        with g.worker() as restarted:
            g.check("restart does not repeat crashed claimed IO", restarted.step(sid) is None and not restarted.llm.calls)
        # Also fail after accept AND successor publication, before COMMIT.
        real_publish = publish
        def publish_then_crash(*args, **kwargs):
            result = real_publish(*args, **kwargs)
            g.check("publication executed before injected crash", result.get("ok"), result)
            raise CrashBeforeCommit()
        with mock.patch(__name__ + ".publish", side_effect=publish_then_crash):
            try:
                worker.finish(work)
            except CrashBeforeCommit:
                pass
        g.check("receipt and publication roll back together", g.fingerprint(sid) == before)
        class LostCommitResponse(Exception):
            pass
        def lost(*_):
            raise LostCommitResponse()
        try:
            worker.finish(work, after_commit=lost)
        except LostCommitResponse:
            pass
        committed = g.fingerprint(sid)
        replay = worker.finish(work)
        g.check("lost COMMIT response uses storage replay, never repeats continuation/IO",
                replay["receipt"]["replayed"] is True and not replay["successors"]
                and len(worker.llm.calls) == 1 and g.fingerprint(sid) == committed, replay)
        conflict = g.committed(accept, None, op, work.tokens, work.result, "failed")
        g.check("outcome participates in receipt conflict", conflict.get("reason") == "receipt_conflict", conflict)
    # Crash after the first successor admission must also undo accept and the
    # whole partial queue. No second IO is needed to replay the known result.
    a = g.start()
    sid = a["run_id"]
    with g.worker([{"text": "atomic multi-call", "tool_calls": [tool_call("one", "one"), tool_call("two", "two")]}]) as worker:
        work = worker.prepare(sid)
        worker.perform(work)
        before = g.fingerprint(sid)
        real_admit = admit
        class CrashAfterAdmit(Exception):
            pass
        def admit_then_crash(*args, **kwargs):
            admitted = real_admit(*args, **kwargs)
            g.check("first successor admit entered inside T2", admitted.get("ok"), admitted)
            raise CrashAfterAdmit()
        with mock.patch(__name__ + ".admit", side_effect=admit_then_crash):
            try:
                worker.finish(work)
            except CrashAfterAdmit:
                pass
        g.check("partial tool queue and receipt roll back atomically", g.fingerprint(sid) == before)
        completed = worker.finish(work)
        g.check("known result retry creates complete queue without more IO", len(completed["successors"]) == 2 and len(worker.llm.calls) == 1)
    # Control wins after old T2 BEGIN, before its first session/run lock.
    for control in ("steer", "cancel"):
        a = g.start()
        sid = a["run_id"]
        with g.worker() as worker:
            work = worker.prepare(sid)
            worker.perform(work)
            sql(worker.conn, "BEGIN")
            if control == "steer":
                g.committed(steer, None, sid, "control wins", uid(), 1)
            else:
                g.committed(cancel, None, sid, uid())
            snap = g.state(sid)
            # BEGIN really predates control COMMIT; no intervening COMMIT may
            # replace this T2 before it acquires the session/run locks.
            with worker.conn:
                received = accept(worker.conn, None, work.operation["operation_id"], work.tokens, work.result)
                g.check("control-before-lock returns archive without continuation " + control,
                        not received.get("ok") and received["outcome"] == "archived_stale", received)
            g.check("control-before-lock archives real receipt " + control,
                    received["effect_outcome"] == "succeeded" and g.state(sid) == snap, received)
            g.check("archive COMMIT independently visible " + control,
                    g.audit("SELECT status IN ('archived','closed') AND result IS NOT NULL FROM v13_ce_operations WHERE operation_id=%s", (a["operation_id"],)))
    # Opposite legal ordering: T2 already owns locks, control must await COMMIT.
    for control in ("steer", "cancel"):
        a = g.start()
        sid = a["run_id"]
        with g.worker() as worker:
            work = worker.prepare(sid)
            worker.perform(work)
            def barrier(conn, item, received):
                action = ((lambda c: steer(c, None, sid, "after T2", uid(), 1)) if control == "steer"
                          else (lambda c: cancel(c, None, sid, uid())))
                with ThreadCall(lambda: g.setup.connect_route(g.db), action) as other:
                    wait_blocked(g, other, conn.get_backend_pid())
                    # Hold the control thread until outer T2 can actually commit.
                    pending.append(other)
                    # ThreadCall normally joins on exit; here publication/commit
                    # is performed explicitly while this barrier owns the context.
                    p = publish(conn, None, item.operation["operation_id"], received["revision"], {"status": "running"}, "running")
                    CeWorker._required(p)
                    nxt = admit(conn, None, sid, 1, "admit_turn", {"after_operation_id": item.operation["operation_id"]},
                                f"ce:{item.operation['operation_id']}:next_turn", item.operation["operation_id"])
                    CeWorker._required(nxt)
                    conn.commit()
                outcomes.append(other.result)
                raise StopAfterFixtureCommit()
            class StopAfterFixtureCommit(Exception):
                pass
            pending, outcomes = [], []
            try:
                worker.finish(work, after_accept=barrier)
            except StopAfterFixtureCommit:
                pass
            g.check("T2-first control observes COMMIT then becomes final state " + control,
                    outcomes[0].get("ok") and (g.state(sid)["status"] == "cancelled" if control == "cancel"
                                               else g.committed(discover, None, sid)["current_driving_operation_id"] == outcomes[0]["operation_id"]), outcomes)


def native_unknown_vs_archive(g):
    # Worker stops after committed claim/IO; only a restarted worker requeues.
    a, other = g.start(), g.start()
    sid = a["run_id"]
    with g.worker(lease_ms=20) as worker:
        work = worker.prepare(sid)
        worker.perform(work)
    with g.connection() as conn:
        tokens = claim(conn, None, other["operation_id"], lease_ms=20)
        conn.commit()
    time.sleep(.04)
    g.check("stopped Worker has not spontaneously requeued", g.audit("SELECT status FROM effects WHERE effect_id=%s", (a["effect_id"],)) == "claimed")
    with g.worker() as restarted:
        g.check("restart first scan requeues without duplicate IO", restarted.step(sid) is None and not restarted.llm.calls)
    g.check("frozen requeue is really global, including another run", all(g.audit(
        "SELECT status FROM effects WHERE effect_id=%s", (eid,)) == "unknown" for eid in (a["effect_id"], other["effect_id"])))
    g.zero(sid, steer, None, sid, "unknown steer", uid(), 1, reason="unknown_wall")
    for verb, payload in (("admit_turn", {}), ("admit_tool", tool_payload(a["operation_id"]))):
        g.zero(sid, admit, None, sid, 1, verb, payload, uid(), a["operation_id"], reason="unknown_wall")
    # Old tokens cannot release a newer fence, whether status is claimed/unknown.
    before = g.fingerprint(sid)
    r = g.committed(accept, None, a["operation_id"], work.tokens, work.result)
    g.check("reclaimed old tokens reject and do not release lease", r.get("outcome") in ("stale_claim", "unknown_wall")
            and g.fingerprint(sid) == before, r)
    # A human host claim lost to a real lease expiry exercises respond's wall.
    b = g.start()
    with g.worker([waiting("human", "instruction")]) as worker:
        worker.run(b["run_id"])
    state = g.state(b["run_id"])
    human = g.audit("SELECT interaction_effect_id FROM v13_ce_snapshots WHERE run_id=%s", (b["run_id"],))
    with g.connection("owner") as conn:
        human_claim = sql(conn, "SELECT public.v13_ce_claim_bound_effect(%s::uuid,%s::uuid,%s,20)",
                          (b["run_id"], human, "ce-gate-human-host"))
        conn.commit()
    g.check("fixture claims the bound human, not the completed driving LLM", human_claim["effect_id"] == human
            and human != b["effect_id"] and human_claim.get("ok"), human_claim)
    time.sleep(.04)
    with g.connection() as conn:
        recovery = sql(conn, "SELECT public.v13_ce_requeue_stale()")
        conn.commit()
    g.check("real human lease recovery creates the session unknown wall", recovery.get("ok")
            and g.audit("SELECT status FROM effects WHERE effect_id=%s", (human,)) == "unknown"
            and g.audit("SELECT status FROM sessions WHERE session_id=%s", (b["run_id"],)) == "blocked_unknown", recovery)
    g.zero(b["run_id"], respond, None, b["run_id"], state["interaction"]["id"],
           {"schema_version": 1, "response": "blocked"}, uid(), reason="unknown_wall")
    g.zero(b["run_id"], steer, None, b["run_id"], "blocked instruction", uid(), 1, reason="unknown_wall")
    # A genuine unknown tool receipt leaves a completed driving LLM whose new
    # waiting publication must not enqueue a human effect through the wall.
    c = g.start()
    with g.worker([{"text": "tool before waiting", "tool_calls": [tool_call()]}]) as worker:
        driving = worker.step(c["run_id"])
        uncertain_tool = worker.prepare(c["run_id"])
        uncertain_tool.result, uncertain_tool.status = {"uncertain": True}, "unknown"
        unknown_result = worker.finish(uncertain_tool)
        g.check("unknown tool receipt commits without continuation", not unknown_result["successors"]
                and unknown_result["receipt"]["effect_outcome"] == "unknown", unknown_result)
        before = g.fingerprint(c["run_id"])
        rejected = g.committed(publish, None, c["operation_id"], driving["receipt"]["revision"],
                               {"status": "waiting_for_input", "interaction": waiting()["interaction"]}, "waiting")
        g.check("waiting publication cannot enqueue through session unknown wall", not rejected.get("ok")
                and rejected.get("reason") == "unknown_wall" and g.fingerprint(c["run_id"]) == before, rejected)
    # A real unknown outcome is committed without any successor or publication.
    b = g.start()
    with g.worker() as worker:
        uncertain = worker.prepare(b["run_id"])
        uncertain.result, uncertain.status = {"uncertain": True}, "unknown"
        outcome = worker.finish(uncertain)
    g.check("unknown receipt never fabricates a terminal run or continuation", not outcome["successors"]
            and g.audit("SELECT status FROM effects WHERE effect_id=%s", (b["effect_id"],)) == "unknown"
            and g.state(b["run_id"])["status"] == "running", outcome)
    # Claimed tokens with a different fence never release somebody else's lease.
    b = g.start()
    with g.connection() as conn:
        current = claim(conn, None, b["operation_id"])
        conn.commit()
    stale = dict(current, fence=current["fence"] + 1)
    before = g.fingerprint(b["run_id"])
    rejected = g.committed(accept, None, b["operation_id"], stale, {"text": "stale tokens"})
    g.check("mismatched tokens preserve current claimed lease exactly", rejected.get("outcome") == "stale_claim"
            and g.fingerprint(b["run_id"]) == before, rejected)
    # Known bridge shape errors are archived, but do not fake-settle the claim.
    b = g.start()
    with g.worker() as worker:
        prepared = worker.prepare(b["run_id"])
        prepared.result = {"text": "bad protocol", "tool_calls": [{"name": "unknown"}]}
        r = worker.finish(prepared)
    g.check("known tool_calls bridge rejection commits archive only", r["receipt"]["outcome"] == "bridge_rejected"
            and g.audit("SELECT status FROM effects WHERE effect_id=%s", (b["effect_id"],)) == "claimed"
            and g.audit("SELECT status FROM v13_ce_operations WHERE operation_id=%s", (b["operation_id"],)) == "archived", r)
    # Unexpected P0001 must propagate unchanged and roll back the entire T2.
    b = g.start()
    with g.worker() as worker:
        prepared = worker.prepare(b["run_id"])
        worker.perform(prepared)
        before = g.fingerprint(b["run_id"])
        with g.connection("owner") as owner:
            sql(owner, "CREATE FUNCTION public.ce_gate_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                       "IF NEW.effect_id='" + b["effect_id"] + "'::uuid THEN RAISE EXCEPTION 'ce_gate_unique_unexpected_p0001'; END IF; RETURN NEW; END $$")
            sql(owner, "CREATE TRIGGER ce_gate_fault BEFORE UPDATE ON public.effects FOR EACH ROW EXECUTE FUNCTION public.ce_gate_fault()")
            owner.commit()
        try:
            try:
                worker.finish(prepared)
            except psycopg2.Error as exc:
                g.check("unexpected P0001 propagates verbatim", exc.pgcode == "P0001" and "ce_gate_unique_unexpected_p0001" in str(exc), str(exc))
            else:
                g.check("unexpected database fault cannot be swallowed", False)
            g.check("unexpected database fault leaves no fake archive/settlement", g.fingerprint(b["run_id"]) == before)
        finally:
            with g.connection("owner") as owner:
                sql(owner, "DROP TRIGGER ce_gate_fault ON public.effects")
                sql(owner, "DROP FUNCTION public.ce_gate_fault()")
                owner.commit()


def native_operation_handoff(g):
    a = g.start()
    sid, source = a["run_id"], a["operation_id"]
    with g.case("oversized admit payload structured refusal"):
        g.zero(sid, admit, None, sid, 1, "admit_turn", {"oversized": "x" * 1048576}, uid(), source, reason="invalid_args")
    for params in ({}, {"task": ""}, {"task": 1}, {"task": "x" * 1025}, {"task": "x", "extra": 1}):
        payload = tool_payload(source)
        payload["params"] = params
        g.zero(sid, admit, None, sid, 1, "admit_tool", payload, uid(), source, reason="invalid_tool_args")
    for tool in ("unknown", "send_summary_email", "harness_turn", "session_stats"):
        payload = tool_payload(source)
        payload["tool"] = tool
        g.zero(sid, admit, None, sid, 1, "admit_tool", payload, uid(), source, reason="invalid_tool")
    for missing in ("tool", "params", "source_operation_id", "tool_call_index"):
        payload = tool_payload(source)
        del payload[missing]
        with g.case("missing required tool envelope field " + missing):
            g.zero(sid, admit, None, sid, 1, "admit_tool", payload, uid(), source, reason="invalid_args")
    for key, value, reason in (("extra", 1, "invalid_args"), ("source_operation_id", uid(), "invalid_tool_source"),
                               ("tool_call_index", -1, "invalid_args"), ("tool_call_index", 1.5, "invalid_args"),
                               ("tool_call_index", "1", "invalid_args"), ("tool_call_id", "bad id", "invalid_args"),
                               ("tool_call_id", "x" * 129, "invalid_args"), ("tool_call_id", "", "invalid_args")):
        payload = tool_payload(source)
        payload[key] = value
        g.zero(sid, admit, None, sid, 1, "admit_tool", payload, uid(), source, reason=reason)
    original_task = "  original task\nverbatim  "
    calls = [tool_call(original_task, "same_0"), tool_call(original_task, "same_1")]
    with g.worker([{"text": "two calls", "tool_calls": calls}, {"text": "done after tools"}]) as worker:
        first = worker.step(sid)
        tools = first["successors"]
        g.check("all ordered calls admitted atomically, independent identities", len(tools) == 2 and tools[0]["operation_id"] != tools[1]["operation_id"]
                and not tools[0]["queued"] and tools[1]["queued"], tools)
        g.check("receipt exact four keys with JSON numbers/object", set(receipt_payload({"effect_id": uid(), "attempt_no": 1, "fence": 1}, {}))
                == {"effect_id", "attempt_no", "fence", "effect_result"})
        before = g.fingerprint(sid)
        replay = g.committed(admit, None, sid, 1, "admit_tool", tool_payload(source, 0, original_task, "same_0"), f"ce:{source}:tool:0", source)
        g.check("tool deterministic request replays stored admission", replay == tools[0] and g.fingerprint(sid) == before, replay)
        g.zero(sid, admit, None, sid, 1, "admit_tool", tool_payload(source, 0, "different", "same_0"), f"ce:{source}:tool:0", source, reason="request_id_conflict")
        with g.connection() as conn:
            not_bound = claim(conn, None, tools[1]["operation_id"])
            conn.commit()
        g.check("queued operation has no fictitious claim tokens/IO", not not_bound.get("ok") and tools[1]["attempt_no"] is None and tools[1]["fence"] is None, not_bound)
        sessions_before = g.audit("SELECT count(*) FROM sessions")
        result0 = worker.step(sid)
        g.check("first tool promotes second but cannot finish run", result0["receipt"]["effect_outcome"] == "succeeded"
                and not result0["successors"] and g.state(sid)["status"] == "running", result0)
        result1 = worker.step(sid)
        g.check("last tool and next_turn commit in same T2", result1["receipt"]["replayed"] is False and len(result1["successors"]) == 1, result1)
        worker.run(sid)
        g.check("Fake adapter preserves task and creates no native sessions", len(worker.tool.calls) == 2
                and all(c["params"] == {"task": original_task} for c in worker.tool.calls)
                and g.audit("SELECT count(*) FROM sessions") == sessions_before)
        results = g.audit("SELECT jsonb_agg(result ORDER BY created_at,effect_id) FROM effects WHERE session_id=%s AND kind='tool'", (sid,))
        g.check("stored tool results label adapter/simulated honestly", len(results) == 2 and all(
            r["adapter"] == "ce-fake-spawn" and r["simulated"] is True and r["task"] == original_task for r in results), results)
        g.check("paired admitted protocol remains in derived input", any(e["type"] == "llm/message" and len(e["payload"].get("tool_calls", [])) == 2
                for e in worker.llm.calls[-1]["history"]))
    # A tool admitted before steer must still settle, unlike an orphan call.
    a = g.start()
    sid = a["run_id"]
    with g.worker([{"text": "admitted before steer", "tool_calls": [tool_call("already admitted", "paired")]}, {"text": "steer final"}]) as worker:
        first = worker.step(sid)
        s = g.committed(steer, None, sid, "steer after admission", uid(), 1)
        worker.run(sid)
        g.check("pre-steer admitted tool survives and settles", len(worker.tool.calls) == 1
                and worker.tool.calls[0]["params"]["task"] == "already admitted"
                and g.audit("SELECT status FROM v13_ce_operations WHERE operation_id=%s", (first["successors"][0]["operation_id"],)) == "completed")
        g.check("paired call remains protocol history after steer", any(e["payload"].get("tool_calls") for e in worker.llm.calls[-1]["history"]))
    # Retries are only for an explicitly unsent Fake failure; uncertain failures
    # leave the committed claim for lease handling, not duplicate execution.
    a = g.start()
    keys = []
    def unsent(conn, request, history, key):
        idle(conn)
        keys.append(key)
        if len(keys) == 1:
            raise DefinitelyUnsent()
        return {"text": "bounded retry"}
    with contextlib.closing(CeWorker(lambda: g.setup.connect_route(g.db), llm=unsent)) as worker:
        worker.step(a["run_id"])
    g.check("explicit unsent retry keeps original idempotency key", len(keys) == 2 and keys[0] == keys[1])
    a = g.start()
    attempts = []
    def uncertain(conn, request, history, key):
        idle(conn)
        attempts.append(key)
        raise RuntimeError("uncertain external Fake failure")
    with contextlib.closing(CeWorker(lambda: g.setup.connect_route(g.db), llm=uncertain)) as worker:
        try:
            worker.step(a["run_id"])
        except RuntimeError as exc:
            g.check("uncertain IO is never automatically retried", str(exc) == "uncertain external Fake failure" and len(attempts) == 1)
        else:
            g.check("uncertain IO must propagate", False)
    g.check("uncertain IO leaves real claim for lease rules", g.audit("SELECT status FROM effects WHERE effect_id=%s", (a["effect_id"],)) == "claimed")
    # Actual lowered LLM result must branch on effect outcome, not input status.
    a = g.start()
    with g.worker([{"text": ""}]) as worker:
        r = worker.step(a["run_id"])
        g.check("actual llm_result_shape failure cannot publish success", r["receipt"]["effect_outcome"] == "failed" and g.state(a["run_id"])["status"] == "failed", r)


def native_snapshot_once(g):
    a = g.start()
    sid, op = a["run_id"], a["operation_id"]
    with g.worker([waiting()]) as worker:
        result = worker.step(sid)
    g.check("waiting human producer is atomic with receipt", result["receipt"]["revision"] == 1 and g.state(sid)["revision"] == 2
            and g.audit("SELECT status='waiting' FROM sessions WHERE session_id=%s", (sid,)))
    snapshot = g.audit("SELECT to_jsonb(s) FROM v13_ce_snapshots s WHERE run_id=%s", (sid,))
    before = g.fingerprint(sid)
    for status in ("running", "waiting_for_input", "completed", "failed"):
        r = g.committed(publish, None, op, 2, {"status": status, "assistant_text": "cannot overwrite",
            "interaction": waiting()["interaction"]}, "waiting" if status == "waiting_for_input" else "running" if status == "running" else "terminal",
            "ce:" + op + ":negative:" + status)
        g.check("unconsumed interaction blocks every new publication " + status, r.get("reason") == "interaction_pending", r)
        g.check("interaction/binding/effect/revision byte-for-byte unchanged", g.fingerprint(sid) == before)
    iid = snapshot["interaction"]["id"]
    g.committed(respond, None, sid, iid, {"schema_version": 1, "skip": True}, uid())
    with g.worker() as worker:
        worker.run(sid)
    g.check("only exact external response consumes then completes both facts", g.state(sid)["status"] == "completed" and g.audit(
        "SELECT status='completed' FROM sessions WHERE session_id=%s", (sid,)))
    a = g.start()
    sid, op = a["run_id"], a["operation_id"]
    with g.worker() as worker:
        work = worker.prepare(sid)
        worker.perform(work)
        # Explicit protocol fixture tests CAS/replay within one normal T2.
        with worker.conn:
            r = accept(worker.conn, None, op, work.tokens, work.result)
            conflict = publish(worker.conn, None, op, r["revision"] + 1, {"status": "completed"})
            g.check("fixed receipt CAS rejects stale revision without reread", conflict.get("reason") == "revision_conflict", conflict)
            p = publish(worker.conn, None, op, r["revision"], {"status": "completed"})
            g.check("valid publication succeeds", p.get("ok"), p)
        before = g.fingerprint(sid)
        p2 = g.committed(publish, None, op, r["revision"], {"status": "completed"})
        g.check("publication stored replay after terminal adds no revision/wake", p2 == p and g.fingerprint(sid) == before)
        g.zero(sid, publish, None, op, r["revision"], {"status": "failed"}, reason="request_id_conflict")
        rejected = g.committed(publish, None, op, p["revision"], {"status": "completed"}, request_id="ce:" + op + ":new-terminal")
        g.check("new terminal publication cannot rewrite closed run", rejected.get("reason") in ("run_not_running", "archived_stale"), rejected)
    a = g.start()
    sid = a["run_id"]
    with g.worker([{"text": "pending tool", "tool_calls": [tool_call()]}]) as worker:
        r = worker.step(sid)
    before = g.fingerprint(sid)
    rejected = g.committed(publish, None, a["operation_id"], 1, {"status": "completed"}, request_id="ce:" + a["operation_id"] + ":pending-terminal")
    g.check("pending tool work prevents terminal", rejected.get("reason") == "pending_work" and g.fingerprint(sid) == before, rejected)
    g.check("receipt alone never advances revision or CE wakes", g.state(sid)["revision"] == 1
            and g.audit("SELECT count(*) FROM v13_ce_wakes WHERE run_id=%s", (sid,)) == 1)
    for channel in ("human", "ce"):
        for missing in ("id", "kind"):
            a = g.start()
            malformed = waiting(channel)["interaction"]
            malformed.pop(missing)
            response = {"text": f"missing {missing}", "ce_status": "waiting_for_input",
                        "interaction": malformed}
            with g.worker([response]) as worker:
                work = worker.prepare(a["run_id"])
                worker.perform(work)
                before = g.fingerprint(a["run_id"])
                try:
                    worker.finish(work)
                except ContinuationRejected as exc:
                    g.check(f"missing interaction {missing} rejects on {channel}",
                            "invalid_interaction" in str(exc), str(exc))
                else:
                    g.check(f"missing interaction {missing} must reject on {channel}", False)
                g.check(f"missing interaction {missing} leaves {channel} zero-write",
                        g.fingerprint(a["run_id"]) == before)
                with g.connection("owner") as owner:
                    g.denied(owner, "UPDATE v13_ce_runs SET interaction=%s::jsonb WHERE run_id=%s::uuid",
                             (Json(malformed), a["run_id"]), code="23514")
                    with owner:
                        received = accept(owner, None, a["operation_id"], work.tokens, work.result)
                        g.check("malformed interaction fixture settled driving receipt", received.get("ok"), received)
                        settled = g.fingerprint(a["run_id"], conn=owner)
                        rejected = publish(owner, None, a["operation_id"], received["revision"],
                                           {"status": "waiting_for_input", "interaction": malformed}, "waiting")
                        g.check(f"missing {missing} publication returns structured rejection on {channel}",
                                rejected.get("ok") is False and rejected.get("reason") == "invalid_interaction", rejected)
                        g.check("invalid publication alone preserves all business rows inside T2",
                                g.fingerprint(a["run_id"], conn=owner) == settled)
                        completed = publish(owner, None, a["operation_id"], received["revision"],
                                            {"status": "completed"})
                        g.check("rejected waiting publication can atomically complete valid T2", completed.get("ok"), completed)
    a = g.start()
    invalid_waiting = {"text": "invalid waiting interaction", "ce_status": "waiting_for_input",
                       "interaction": {"id": "not-a-uuid", "kind": "question"}}
    with g.worker([invalid_waiting]) as worker:
        work = worker.prepare(a["run_id"])
        worker.perform(work)
        before = g.fingerprint(a["run_id"])
        try:
            worker.finish(work)
        except ContinuationRejected as exc:
            g.check("unexpected continuation refusal propagates", "invalid_interaction" in str(exc), str(exc))
        else:
            g.check("normal T2 must never commit accept after continuation rejection", False)
        g.check("continuation rejection rolls accept/llm events back", g.fingerprint(a["run_id"]) == before)
        def sql_fault(conn, *_):
            sql(conn, "SELECT 1/0")
        try:
            worker.finish(work, after_accept=sql_fault)
        except psycopg2.Error as exc:
            g.check("unexpected real SQL fault propagates", exc.pgcode == "22012", str(exc))
        else:
            g.check("real SQL fault cannot be swallowed", False)
        g.check("real SQL fault never leaves committed accept", g.fingerprint(a["run_id"]) == before)


def native_static_setup(g):
    source = Path(__file__).read_text()
    setup_source = Path(__file__).with_name("setup_db.py").read_text()
    tree = ast.parse(source)
    g.check("no real network/provider imports", not any(isinstance(n, (ast.Import, ast.ImportFrom)) and any(
        word in ast.unparse(n) for word in ("socket", "requests", "httpx", "openai", "DeepSeekProvider")) for n in ast.walk(tree)))
    worker_source = inspect.getsource(CeWorker)
    g.check("worker never SELECT/JOIN/DML CE base tables", "FROM public.v13_ce_" not in worker_source
            and "JOIN public.v13_ce_" not in worker_source and "UPDATE " not in worker_source
            and "INSERT " not in worker_source and "DELETE " not in worker_source)
    g.check("no pg_sleep or native spawn execution", "pg_" + "sleep(" not in source and "v13_spawn_subsession(" not in worker_source)
    g.check("setup never prefix-drops and local loader calls only CE", "LIKE 'll_ce_run_" not in setup_source
            and 'load_stage(server, name, "ce_run")' not in setup_source)
    with mock.patch.object(psycopg2, "connect", side_effect=AssertionError("import connected")), \
            mock.patch.object(subprocess, "run", side_effect=AssertionError("import subprocess")), \
            mock.patch.object(subprocess, "check_output", side_effect=AssertionError("import subprocess")):
        load_module(Path(__file__), "ce_gate_import_safe")
        load_module(Path(__file__).with_name("setup_db.py"), "ce_gate_setup_import_safe")
    g.check("both modules import without DB/subprocess side effects", True)
    g.setup.probe_extension(g.db.server)
    g.check("real stannum and pg_jsonschema available", True)
    with mock.patch.object(g.setup, "_new_name", return_value=g.db.name):
        try:
            g.setup.create_test_database(server=g.db.server)
        except RuntimeError as exc:
            g.check("existing exact database refused, never dropped", "exists" in str(exc)
                    and g.setup._database_oid(g.db.server, g.db.name) == g.db.oid)
        else:
            g.check("same name must not create or drop", False)
    real_run = g.setup.run_psql
    def fail_create(server, name, statement, **kwargs):
        if statement.startswith('CREATE DATABASE '):
            raise RuntimeError("ce_gate_create_failure")
        return real_run(server, name, statement, **kwargs)
    with mock.patch.object(g.setup, "run_psql", side_effect=fail_create), \
            mock.patch.object(g.setup, "_drop_database_exact", side_effect=AssertionError("failed CREATE attempted DROP")):
        try:
            g.setup.create_test_database(server=g.db.server)
        except RuntimeError as exc:
            g.check("CREATE failure never triggers DROP", str(exc) == "ce_gate_create_failure")
    with mock.patch.object(g.setup, "run_psql", side_effect=AssertionError("OID mismatch attempted DROP")):
        try:
            g.setup._drop_database_exact(g.db.server, g.db.name, g.db.oid + 1)
        except RuntimeError as exc:
            g.check("cleanup refuses an unexpected database OID", "OID changed" in str(exc))
        else:
            g.check("OID mismatch must not be cleaned up", False)
    original = RuntimeError("ce_gate_original_failure")
    with mock.patch.object(g.setup, "create_test_database", return_value=g.db), \
            mock.patch.object(g.setup, "drop_test_database", side_effect=RuntimeError("ce_gate_cleanup_failure")):
        try:
            with g.setup.test_database():
                raise original
        except RuntimeError as exc:
            g.check("contextmanager cleanup failure preserves original exception", exc is original)
    with mock.patch.object(g.setup, "probe_extension", side_effect=RuntimeError("ce_gate_extension_absent")), \
            mock.patch.object(g.setup, "run_psql", side_effect=AssertionError("extension failure attempted CREATE")):
        try:
            g.setup.create_test_database(server=g.db.server)
        except RuntimeError as exc:
            g.check("extension preflight failure executes no DDL", str(exc) == "ce_gate_extension_absent")
    for bad in ("agent_v13_ce_run", "ll_ce_run_1_abcdef", "ll_ce_run_x_abcdef", "ll_ce_run_0_abcdef_extra"):
        try:
            g.setup._validate_name(bad)
        except ValueError:
            g.check("strict lifecycle name rejection " + bad, True)
        else:
            g.check("bad lifecycle name accepted", False, bad)
    with g.setup.test_database(server=g.db.server, load_sql=False) as prefix:
        with contextlib.closing(g.setup.connect_owner_database(prefix)) as owner:
            g.check("load_sql=False still loads fair_claim but not CE", sql(owner,
                "SELECT to_regprocedure('v13_claim(text,integer)') IS NOT NULL AND to_regclass('v13_ce_runs') IS NULL"))
        g.setup.validate_deployment_restrictions(prefix.server, prefix.name, prefix.roles)
        g.check("load_sql=False enforces host ACL before CE", True)
        prefix_name = prefix.name
    g.check("exact contextmanager removes only its own database", not g.setup.name_exists(g.db.server, prefix_name)
            and g.setup._database_oid(g.db.server, g.db.name) == g.db.oid)


PROBES = (native_load_untouched, native_plan_arm_closed_set, native_frozen_driver_bytes,
          native_start_identity, native_poll_pure, native_wait_cursor, native_cancel_scope,
          native_steer_paths, native_respond_once, native_acl_roles, native_io_boundary,
          native_receipt_fences, native_unknown_vs_archive, native_operation_handoff,
          native_snapshot_once, native_static_setup)


def main():
    failures = []
    setup = setup_module()
    with setup.test_database() as database:
        gate = Gate(database)
        print("CE fake gate database:", database.name, "OID:", database.oid, flush=True)
        for probe in PROBES:
            print("\nGROUP", probe.__name__, flush=True)
            before = gate.checks
            cases_before = len(gate.case_failures)
            try:
                probe(gate)
                if len(gate.case_failures) != cases_before:
                    raise AssertionError(f"independent cases failed: {gate.case_failures[cases_before:]}")
            except Exception as exc:
                failures.append(probe.__name__)
                print("GROUP FAIL", probe.__name__, repr(exc), flush=True)
                traceback.print_exc()
            else:
                print("GROUP PASS", probe.__name__, "checks", gate.checks - before, flush=True)
        print("\nSUMMARY", "groups", len(PROBES), "passed", len(PROBES) - len(failures),
              "failed", len(failures), "checks", gate.checks, "independent_case_failures", len(gate.case_failures),
              "failures", failures, flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
