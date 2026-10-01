"""v13 goal_supervisor — one-tick G3 consumer. Unique settler is LoopDriver.settle_once.

Gate: UV_FROZEN=1 uv run python v13/goal_supervisor/test_goal_supervisor.py

No SQL, no load.py key, no B1 exit machine, no provider IO.
"""
from __future__ import annotations

from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from v13.loop_driver.driver import LoopDriver

SUPERVISOR_MAX_TICKS = 2
UNPAID_REMAINING = "v13: supervisor: unpaid_remaining"
TERMINAL_STATUS = ("completed", "failed", "cancelled")
ALLOWED_V13 = (
    "v13_unpaid_harness_turn",
    "v13_scheduler_hint",
    "v13_notify_project",
    "v13_observe_fold",
    "v13_goal_ambiguous_hold",
    "v13_should_run",
    "v13_plan_current",
    "v13_selected_todo",
    "v13_wake_is_satisfied_v1",
    "v13_frontier_project",
    "v13_goal_lifecycle",
    "v13_replan_gap_insert",
    "v13_goal_lease_once",
    "v13_recover_idle",
    "v13_goal_stop",
)


class SupervisorFail(RuntimeError):
    """Tick failed; message is the exact process token."""


class GoalSupervisor:
    """One process-owned connection plus a LoopDriver used only for settle_once."""

    def __init__(self, connect):
        self._connect = connect
        self.conn = None
        self.settler = LoopDriver(connect)
        self.calls = []
        self.ticks_used = 0
        self.report = None

    def connection(self):
        if self.conn is None:
            self.conn = self._connect()
            self.conn.autocommit = False
        return self.conn

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        self.settler.close()

    def _idle(self):
        conn = self.connection()
        if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise RuntimeError("v13: supervisor: open transaction")
        return conn

    def _read(self, sql, params=None):
        conn = self._idle()
        was = conn.autocommit
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            conn.autocommit = was

    def _write(self, name, sql, params, sid):
        conn = self._idle()
        cur = conn.cursor()
        try:
            cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cur.execute("SHOW transaction_isolation")
            isolation = cur.fetchone()[0]
            if isolation != "read committed":
                raise RuntimeError("v13: supervisor: isolation")
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        self.calls.append((name, sid))
        return rows

    def _unpaid(self, sid):
        rows = self._read(
            "SELECT effect_id::text FROM v13_unpaid_harness_turn(%s::uuid)",
            (sid,))
        self.calls.append(("v13_unpaid_harness_turn", sid))
        return [row[0] for row in rows]

    def _lifecycle(self, sid):
        row = self._read("SELECT v13_goal_lifecycle(%s::uuid)", (sid,))
        self.calls.append(("v13_goal_lifecycle", sid))
        return None if not row else row[0][0]

    def _session_status(self, sid):
        row = self._read(
            "SELECT status FROM sessions WHERE session_id = %s", (sid,))
        return None if not row else row[0][0]

    def _human_pending(self, sid):
        rows = self._read(
            "SELECT effect_id::text FROM effects "
            "WHERE session_id = %s AND kind = 'human' "
            "AND status IN ('ready', 'claimed', 'unknown')",
            (sid,))
        return [row[0] for row in rows]

    def _holds(self, sid):
        rows = self._read(
            "SELECT effect_id::text FROM v13_goal_ambiguous_hold(%s::uuid)",
            (sid,))
        self.calls.append(("v13_goal_ambiguous_hold", sid))
        return [row[0] for row in rows]

    def _maybe_replan(self, sid):
        rows = self._read(
            "SELECT frontier, frontier_hash, has_obligation, omitted_complete "
            "FROM v13_frontier_project(%s::uuid, NULL)",
            (sid,))
        self.calls.append(("v13_frontier_project", sid))
        if not rows:
            return
        frontier, frontier_hash, has_obl, omitted_complete = rows[0]
        if omitted_complete is not True:
            return
        gaps = []
        if isinstance(frontier, dict):
            gaps = frontier.get("gaps") or []
        flags = list(has_obl or [])
        chosen = None
        for idx, gap in enumerate(gaps):
            obligated = flags[idx] if idx < len(flags) else False
            if obligated:
                continue
            chosen = gap
            break
        if not isinstance(chosen, dict):
            return
        subject = chosen.get("subject_todo_id")
        obj = chosen.get("object_todo_id")
        kind = chosen.get("gap_kind")
        if not kind or not subject:
            return
        last = None
        for _attempt in (1, 2):
            try:
                self._write(
                    "v13_replan_gap_insert",
                    "SELECT v13_replan_gap_insert("
                    "%s::uuid, %s::uuid, %s, %s::uuid, %s::uuid, %s)",
                    (None, sid, kind, subject, obj, frontier_hash),
                    sid)
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        if last is not None:
            raise last

    def tick(self, sid, request_stop=False, lease_effect_id=None):
        if self.ticks_used >= SUPERVISOR_MAX_TICKS:
            raise RuntimeError("v13: supervisor: max_ticks")
        self.ticks_used += 1
        report = {
            "word": "waiting",
            "request_stop_consumed": False,
            "settle_word": None,
            "notify": None,
            "observe": None,
            "recover": None,
            "hold": False,
            "unpaid": [],
            "human": [],
        }
        status = self._session_status(sid)
        if status in TERMINAL_STATUS:
            report["word"] = status
            self.report = report
            return report
        life = self._lifecycle(sid)
        unpaid = self._unpaid(sid)
        report["unpaid"] = list(unpaid)
        if unpaid:
            if len(unpaid) != 1:
                raise SupervisorFail(UNPAID_REMAINING)
            candidate = unpaid[0]
            word = self.settler.settle_once(sid)
            self.calls.append(("settle_once", sid))
            report["settle_word"] = word
            if word == "skipped_failed":
                report["word"] = "skipped_failed"
                self.report = report
                return report
            still = self._unpaid(sid)
            if candidate in still:
                raise SupervisorFail(UNPAID_REMAINING)
        human = self._human_pending(sid)
        report["human"] = human
        if human:
            report["word"] = "waiting"
            self.report = report
            return report
        if life != "stopped" and status not in TERMINAL_STATUS:
            self._maybe_replan(sid)
        holds = self._holds(sid)
        report["hold"] = bool(holds)
        if holds:
            notify = self._read(
                "SELECT v13_notify_project(%s::uuid)", (sid,))
            self.calls.append(("v13_notify_project", sid))
            report["notify"] = None if not notify else notify[0][0]
            observe = self._read(
                "SELECT v13_observe_fold(%s::uuid, %s::uuid)", (None, sid))
            self.calls.append(("v13_observe_fold", sid))
            report["observe"] = None if not observe else observe[0][0]
            self.report = report
            return report
        if (lease_effect_id is not None
                and life != "stopped"
                and status not in TERMINAL_STATUS):
            self._write(
                "v13_goal_lease_once",
                "SELECT v13_goal_lease_once(%s::uuid, %s::uuid, %s::uuid)",
                (None, sid, lease_effect_id),
                sid)
        recover_rows = self._write(
            "v13_recover_idle", "SELECT v13_recover_idle()", (), sid)
        report["recover"] = None if not recover_rows else recover_rows[0][0]
        hint = self._read("SELECT v13_scheduler_hint(%s::uuid)", (sid,))
        self.calls.append(("v13_scheduler_hint", sid))
        report["hint"] = None if not hint else hint[0][0]
        self._read("SELECT v13_should_run(%s::uuid)", (sid,))
        self.calls.append(("v13_should_run", sid))
        self._read("SELECT v13_plan_current(%s::uuid)", (sid,))
        self.calls.append(("v13_plan_current", sid))
        self._read("SELECT * FROM v13_selected_todo(%s::uuid)", (sid,))
        self.calls.append(("v13_selected_todo", sid))
        notify = self._read("SELECT v13_notify_project(%s::uuid)", (sid,))
        self.calls.append(("v13_notify_project", sid))
        report["notify"] = None if not notify else notify[0][0]
        observe = self._read(
            "SELECT v13_observe_fold(%s::uuid, %s::uuid)", (None, sid))
        self.calls.append(("v13_observe_fold", sid))
        report["observe"] = None if not observe else observe[0][0]
        if request_stop and status not in TERMINAL_STATUS:
            stop_rows = self._write(
                "v13_goal_stop",
                "SELECT v13_goal_stop(%s::uuid, %s)",
                (sid, "supervisor-stop"),
                sid)
            report["request_stop_consumed"] = True
            report["stop"] = None if not stop_rows else stop_rows[0][0]
        self.report = report
        return report
