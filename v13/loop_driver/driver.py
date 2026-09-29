"""v13 loop_driver — Phase A B1 exits, B2 four layers, B6 discipline, C7 mapping.

Gate: UV_FROZEN=1 uv run python v13/loop_driver/test_loop_driver.py

Control SQL closed set (plan §7.4) — the driver only drives control through
these verbs. Read-only helpers (v13_probe, v13_plan_map_root, v13_plan_todo_fold,
v13_goal_lifecycle, v13_context_required) cover reads; the worker claim is a
scoped lease UPDATE on the exact effect the driver is about to complete
(same shape as the live v13_claim body / stage-test settle helper, inside the
complete transaction); see README and the deviation ledger.

Discipline:
- No raw INSERTs against live tables (effects, events, sessions,
  artifacts); no cron registration; no credentials in request bodies.
  Persistent effects go through named SQL that re-checks under the session
  lock.
- External IO (FakeLLM/FakeTool in the gate) happens only with no open
  database transaction: claim+complete+settlement run in one committed
  transaction after the IO returns.
- Four layers are emitted as an ordered list of four segments, never merged
  into a single-line system prompt, never written back to v13_policies.
"""
from __future__ import annotations

import json

EXIT_WORDS = ("wait", "user_action", "provider", "terminal", "stopping")
NOT_EXIT_WORDS = ("repair", "replan", "capability_adapter_handoff")

# Plan §7.4 closed set: the only control verbs this driver may drive.
ALLOWED_CONTROL_SQL = (
    "v13_plan_prelude",
    "v13_plan_admit",
    "v13_plan_commit_entry",
    "v13_plan_writer",
    "v13_plan_current",
    "v13_selected_todo",
    "v13_plan_gate",
    "v13_plan_inventory",
    "v13_plan_horizon",
    "v13_harness_result_project",
    "v13_submit_override",
    "v13_advance",
    "v13_complete",
    "v13_goal_stop",
    "v13_should_run",
    "v13_scheduler_hint",
    "v13_wake_is_satisfied_v1",
)

# Read-only projections plus the scoped worker claim; not control verbs.
READ_HELPERS = (
    "v13_probe",
    "v13_plan_map_root",
    "v13_plan_todo_fold",
    "v13_goal_lifecycle",
    "v13_context_required",
)

TERMINAL_STATUS = ("completed", "failed", "cancelled")
HUMAN_CLASSES = ("user_gate", "user_action", "blocker")
OPERATOR_STATUS = ("pending", "runnable", "blocked")
LAYER_ORDER = ("assertion", "assembly", "judgment", "workflow")
PROVIDER_ATTEMPT_CAP = 2

_ABSENT = object()


def as_obj(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def collapse_exit_word(word):
    """Unknown exit words (repair/replan/capability_adapter_handoff, anything
    else) collapse to wait with zero SQL side effects."""
    return word if word in EXIT_WORDS else "wait"


def t0_advance_blocked(lifecycle, snap):
    """T0 driver discipline: on a stopped root, do not call v13_advance when
    the top-level snap carries a non-null `failed` value. JSON false, 0, and
    non-empty text all count; a missing key and JSON null do not."""
    if lifecycle != "stopped" or not isinstance(snap, dict):
        return False
    failed = snap.get("failed", _ABSENT)
    if failed is _ABSENT:
        return False
    return failed is not None


def decide_exit(*, session_status, stop_requested=False, stop_authorized=True,
                upstream_word=None, needs_human=False, dispatch=None,
                plan_gate=False, should_run=True, hint="wait", human_pending=False):
    """B1 five exits, judgment order per plan §5.6:
    terminal -> stopping -> user_action -> (upstream non-exit words -> wait)
    -> wait conditions -> provider -> wait."""
    if session_status in TERMINAL_STATUS:
        return "terminal"
    if stop_requested and stop_authorized:
        return "stopping"
    if needs_human or dispatch == "operator":
        return "user_action"
    if upstream_word in NOT_EXIT_WORDS:
        return "wait"
    if (not plan_gate) or (not should_run) or hint in ("wait", "dont_notify"):
        return "wait"
    if human_pending:
        return "wait"
    if dispatch == "provider" and hint == "run_now" and plan_gate and should_run:
        return "provider"
    return "wait"


class LoopDriver:
    """One driver instance owns one psycopg2 connection with explicit
    transaction boundaries. `calls` records (name, session_id) in order so
    tests can prove ordering (override before first advance, settlement after
    complete, exactly one requeue advance)."""

    def __init__(self, connect, llm=None, tools=None, layers=None,
                 worker="loop_driver"):
        self._connect = connect
        self.conn = None
        self.llm = llm
        self.tools = dict(tools or {})
        self.layers = dict(layers or {})
        self.worker = worker
        self.calls = []
        self.txids = []
        self.attempts_used = 0

    # ---- connection plumbing -------------------------------------------
    def connection(self):
        if self.conn is None:
            self.conn = self._connect()
            self.conn.autocommit = False
        return self.conn

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _sql(self, name, sql, params, sid=None):
        conn = self.connection()
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
        self.calls.append((name, sid))
        return rows

    def _read(self, sql, params):
        conn = self.connection()
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
        return rows

    # ---- closed-set control verbs --------------------------------------
    def submit_override(self, sid):
        payload = {"schema_version": 1, "intent": "direct", "reason": "",
                   "source_principal": "operator"}
        self._sql("v13_submit_override",
                  "SELECT v13_submit_override(%s::uuid, %s::jsonb)",
                  (sid, json.dumps(payload)), sid)

    def advance(self, sid, snap=None):
        snap = snap if snap is not None else self.snap_of(sid)
        rows = self._sql("v13_advance",
                         "SELECT v13_advance(%s::uuid, %s::jsonb)",
                         (sid, json.dumps(snap)), sid)
        return rows[0][0]

    def complete(self, effect, attempt, fence, status, result):
        rows = self._sql("v13_complete",
                         "SELECT v13_complete(%s::uuid, %s, %s, %s, %s::jsonb)",
                         (effect, attempt, fence, status, json.dumps(result)),
                         None)
        return rows[0][0]

    def goal_stop(self, sid, reason="operator_stop"):
        self._sql("v13_goal_stop", "SELECT v13_goal_stop(%s::uuid, %s)",
                  (sid, reason), sid)

    def project(self, payload):
        rows = self._sql("v13_harness_result_project",
                         "SELECT v13_harness_result_project(%s::jsonb)",
                         (json.dumps(payload),), None)
        return as_obj(rows[0][0])

    def plan_prelude(self, spec):
        rows = self._sql("v13_plan_prelude",
                         "SELECT v13_plan_prelude(%s::jsonb)",
                         (json.dumps(spec),), None)
        return as_obj(rows[0][0])

    def plan_admit(self, actor, session):
        rows = self._sql("v13_plan_admit", "SELECT v13_plan_admit(%s::uuid, %s::uuid)",
                         (actor, session), None)
        return rows[0][0]

    def plan_commit_entry(self, spec):
        rows = self._sql("v13_plan_commit_entry",
                         "SELECT v13_plan_commit_entry(%s::jsonb)",
                         (json.dumps(spec),), None)
        return str(rows[0][0])

    def plan_writer(self, session, apply_id, call_kind, canonical, now=None):
        rows = self._sql("v13_plan_writer",
                         "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
                         (None, session, apply_id, call_kind,
                          json.dumps(canonical), now), None)
        return as_obj(rows[0][0])

    def plan_current(self, sid):
        rows = self._sql("v13_plan_current", "SELECT v13_plan_current(%s::uuid)",
                         (sid,), sid)
        return as_obj(rows[0][0])

    def plan_inventory(self, sid):
        rows = self._sql("v13_plan_inventory", "SELECT v13_plan_inventory(%s::uuid)",
                         (sid,), sid)
        return as_obj(rows[0][0])

    def plan_horizon(self, sid):
        rows = self._sql("v13_plan_horizon", "SELECT v13_plan_horizon(%s::uuid)",
                         (sid,), sid)
        return as_obj(rows[0][0])

    def should_run(self, sid):
        rows = self._sql("v13_should_run", "SELECT v13_should_run(%s::uuid)",
                         (sid,), sid)
        return rows[0][0]

    def scheduler_hint(self, sid):
        rows = self._sql("v13_scheduler_hint",
                         "SELECT v13_scheduler_hint(%s::uuid)", (sid,), sid)
        return rows[0][0]

    def wake_satisfied(self, sid, effect, wake):
        rows = self._sql("v13_wake_is_satisfied_v1",
                         "SELECT v13_wake_is_satisfied_v1(%s::uuid, %s::uuid, %s::jsonb)",
                         (sid, effect, json.dumps(wake)), sid)
        return rows[0][0]

    # ---- read helpers ----------------------------------------------------
    def session_status(self, sid):
        return self._read("SELECT status FROM sessions WHERE session_id=%s",
                          (sid,))[0][0]

    def lifecycle(self, sid):
        return self._read("SELECT v13_goal_lifecycle(%s::uuid)", (sid,))[0][0]

    def plan_gate(self, sid):
        return self._read("SELECT v13_plan_gate(%s::uuid)", (sid,))[0][0]

    def selected_dispatch(self, sid):
        rows = self._read(
            "SELECT dispatch FROM v13_selected_todo(%s::uuid) LIMIT 1", (sid,))
        return rows[0][0] if rows else None

    def needs_human(self, sid):
        rows = self._read(
            "SELECT EXISTS (SELECT 1 FROM v13_plan_todo_fold(v13_plan_map_root(%s::uuid)) f "
            "WHERE f.task_class IN ('user_gate','user_action','blocker') "
            "AND f.status IN ('pending','runnable','blocked'))", (sid,))
        return rows[0][0]

    def human_pending(self, sid):
        rows = self._read(
            "SELECT EXISTS (SELECT 1 FROM effects WHERE session_id=%s "
            "AND kind='human' AND status IN ('ready','claimed'))", (sid,))
        return rows[0][0]

    def snap_of(self, sid, failed=_ABSENT):
        conn = self.connection()
        cur = conn.cursor()
        snap = self._snap_with(cur, sid, failed)
        conn.commit()
        return snap

    @staticmethod
    def _snap_with(cur, sid, failed=_ABSENT):
        cur.execute(
            "UPDATE sessions SET context_active_revision = v13_context_required(session_id) "
            "WHERE session_id=%s", (sid,))
        cur.execute("SELECT v13_probe(%s::uuid)", (sid,))
        probe = as_obj(cur.fetchone()[0])
        snap = {"snap": dict(probe, sid=sid), "envelope": {"sid": sid},
                "remaining": 0, "abandon": False}
        if failed is not _ABSENT:
            snap["failed"] = failed
        return snap

    # ---- claim path ------------------------------------------------------
    def _peek_servable(self, sid):
        """Oldest ready effect for this session. Human effects are left for
        their own channel: the driver never claims, skips, or completes them."""
        rows = self._read(
            "SELECT effect_id::text, kind, tool_name, request FROM effects "
            "WHERE session_id=%s AND status='ready' "
            "ORDER BY created_at, effect_id LIMIT 1", (sid,))
        if not rows or rows[0][1] == "human":
            return None
        return {"effect_id": rows[0][0], "kind": rows[0][1],
                "tool_name": rows[0][2], "request": as_obj(rows[0][3])}

    # ---- one provider jump ----------------------------------------------
    def serve(self, sid):
        """Serve one servable effect: IO outside any transaction, then
        claim+complete+settlement advance in one committed transaction.
        Returns ('served'|'blocked'|'none', outcome)."""
        peek = self._peek_servable(sid)
        if peek is None:
            return "none", None
        kind = peek["kind"]
        if kind == "llm":
            result = None
            for _ in range(PROVIDER_ATTEMPT_CAP):
                answer = self.llm(self.four_layers(), peek)
                if (isinstance(answer, dict)
                        and isinstance(answer.get("text"), str)
                        and answer["text"].strip()):
                    result = answer
                    break
                self.attempts_used += 1
            if result is None:
                return "blocked", None
        elif kind == "tool":
            handler = self.tools.get(peek["tool_name"])
            if handler is None:
                return "none", None
            if peek["tool_name"] == "harness_turn":
                result = None
                for _ in range(PROVIDER_ATTEMPT_CAP):
                    payload = handler(peek)
                    dto = self.project(payload)
                    if dto and dto.get("ok"):
                        result = dto["harness"]
                        break
                    self.attempts_used += 1
                if result is None:
                    return "blocked", None
            else:
                result = handler(peek)
        else:
            return "none", None

        conn = self.connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT txid_current()")
            txid_a = cur.fetchone()[0]
            cur.execute(
                "UPDATE effects SET status='claimed', attempt_no=attempt_no+1, "
                "fence=fence+1, lease_owner=%s, "
                "lease_until=clock_timestamp()+interval '1 hour' "
                "WHERE effect_id=%s::uuid AND status='ready' "
                "RETURNING attempt_no, fence",
                (self.worker, peek["effect_id"]))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return "none", None
            attempt, fence = row
            cur.execute("SELECT v13_complete(%s::uuid, %s, %s, %s, %s::jsonb)",
                        (peek["effect_id"], attempt, fence,
                         "succeeded", json.dumps(result)))
            outcome = cur.fetchone()[0]
            self._settlement_advance(cur, sid)
            cur.execute("SELECT txid_current()")
            txid_b = cur.fetchone()[0]
            conn.commit()
            self.calls.append(("v13_complete", sid))
            self.txids.append((txid_a, txid_b))
        except Exception:
            conn.rollback()
            raise
        return "served", outcome

    def _settlement_advance(self, cur, sid, failed=_ABSENT):
        """T0 settlement advance on an already-open cursor (same transaction
        as the preceding complete). Skipped when T0 forbids it."""
        cur.execute("SELECT v13_goal_lifecycle(%s::uuid)", (sid,))
        lifecycle = cur.fetchone()[0]
        snap = self._snap_with(cur, sid, failed)
        if t0_advance_blocked(lifecycle, snap):
            return None
        cur.execute("SELECT v13_advance(%s::uuid, %s::jsonb)",
                    (sid, json.dumps(snap)))
        word = cur.fetchone()[0]
        self.calls.append(("v13_advance", sid))
        return word

    # ---- B2 four layers ---------------------------------------------------
    def four_layers(self):
        """Ordered four segments: assertion, assembly, judgment, workflow.
        Never merged into one line, never written back."""
        return [(name, self.layers[name]) for name in LAYER_ORDER]

    # ---- B1 exits ----------------------------------------------------------
    def decide(self, sid, *, stop_requested=False, stop_authorized=True,
               upstream_word=None):
        return decide_exit(
            session_status=self.session_status(sid),
            stop_requested=stop_requested,
            stop_authorized=stop_authorized,
            upstream_word=upstream_word,
            needs_human=self.needs_human(sid),
            dispatch=self.selected_dispatch(sid),
            plan_gate=self.plan_gate(sid),
            should_run=self.should_run(sid),
            hint=self.scheduler_hint(sid),
            human_pending=self.human_pending(sid),
        )

    def take_exit(self, word, sid):
        """Act on a B1 exit. wait/user_action/terminal do nothing; unknown
        words collapse to wait with zero side effects; provider enqueues
        exactly one requeue advance (never counted as the T0 settlement);
        stopping only calls v13_goal_stop."""
        word = collapse_exit_word(word)
        if word == "provider":
            lifecycle = self.lifecycle(sid)
            snap = self.snap_of(sid)
            if not t0_advance_blocked(lifecycle, snap):
                self.advance(sid, snap)
                self.calls[-1] = ("v13_advance:requeue", sid)
            return "provider"
        if word == "stopping":
            self.goal_stop(sid)
            return "stopping"
        return word

    def run_turn(self, sid, *, first=False, stop_requested=False,
                 stop_authorized=True, snap_failed=_ABSENT,
                 upstream_word=None, max_serves=3):
        """One driver turn: optional override before the first advance, one
        entry advance under T0 discipline, a bounded serve loop, then the B1
        exit decision and its (at most one) action."""
        if first:
            self.submit_override(sid)
        if self.session_status(sid) in TERMINAL_STATUS:
            return "terminal", self.attempts_used
        if stop_requested and stop_authorized:
            self.goal_stop(sid)
            return "stopping", self.attempts_used
        lifecycle = self.lifecycle(sid)
        snap = self.snap_of(sid, failed=snap_failed)
        if not t0_advance_blocked(lifecycle, snap):
            self.advance(sid, snap)
        for _ in range(max_serves):
            state, _outcome = self.serve(sid)
            if state != "served":
                break
        word = self.decide(sid, stop_requested=stop_requested,
                           stop_authorized=stop_authorized,
                           upstream_word=upstream_word)
        self.take_exit(word, sid)
        return word, self.attempts_used
