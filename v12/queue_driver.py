"""v12 queue driver: advances the turn state machine with SQL ONLY.

The complement of QueueWorker: no client, no tools, no network. Each
pump() inspects the tables, performs one durable transition per open turn
(seal a batch and enqueue a wake-up, route an answered batch, enqueue an
effect, deliver a guarded draft, close or escalate), and loops until the
turn is waiting on external work. The driver and worker can run in the
same process (tests, simple deployments) or on different hosts — they
share nothing but the database.

Transitions mirror the inline TurnRunner one-for-one; the only difference
is where external IO happens. Effect identity comes from v12_effect_id
(SQL uuid5), which G6 asserts equals the inline runner's Python uuid5.
"""
from __future__ import annotations

import json

from v12.worker import _Base


class QueueDriver(_Base):

    def __init__(self, conn):
        super().__init__(conn)

    # ------------------------------------------------------------------ loop
    def pump(self) -> int:
        """Advance every open turn until each waits on external work.
        Returns the number of durable transitions performed."""
        self.cur.execute(
            "SELECT session_id FROM sessions s WHERE v12_turn_open(s.session_id)")
        sessions = [r[0] for r in self.cur.fetchall()]
        total = 0
        for sid in sessions:
            while (self._one("SELECT v12_turn_open(%s)", (sid,))[0]
                   and self._advance(sid)):
                total += 1
        return total

    def run_until_idle(self, worker, timeout: float = 30.0,
                       poll: float = 0.05) -> None:
        """Convenience loop for tests and single-process deployments:
        alternate driver/worker pumps until no open turns remain."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            worker.pump()
            self.cur.execute(
                "SELECT count(*) FROM sessions s WHERE v12_turn_open(s.session_id)")
            if self.cur.fetchone()[0] == 0:
                self.conn.commit()
                return
            time.sleep(poll)
        raise TimeoutError("queue turn did not settle in time")

    # ------------------------------------------------------------------ steps
    def _advance(self, sid: str) -> bool:
        if self._one("SELECT v12_turn_cycles(%s)", (sid,))[0] >= self.MAX_CYCLES:
            self._force_human(sid, "budget_exhausted")
            return True
        route = self._last_event(sid, "turn/route")
        if route is None:
            return self._decide_step(sid)
        return self._route_step(sid, route)

    def _latest_batch(self, sid: str, purpose: str):
        """Latest batch of a purpose created AFTER the last user message
        (older ones belong to previous turns in the same session)."""
        return self._one(
            "SELECT batch_id, status FROM jev_batches b "
            "WHERE b.session_id = %s AND b.purpose = %s "
            "AND b.created_at > (SELECT e.created_at FROM events e "
            "  WHERE e.session_id = %s AND e.type = 'user/message' "
            "  ORDER BY e.seq DESC LIMIT 1) "
            "ORDER BY b.created_at DESC LIMIT 1", (sid, purpose, sid))

    def _decide_step(self, sid: str) -> bool:
        row = self._latest_batch(sid, "turn")
        if row is None:
            state = self._one("SELECT v12_fold_state(%s)", (sid,))[0]
            batch = self._one("SELECT v12_open_batch(%s, 'turn', %s)",
                              (sid, json.dumps(state)))[0]
            self._one("SELECT v12_build_turn_questions(%s, %s)", (batch, sid))
            status = self._one("SELECT v12_seal_batch(%s)", (batch,))[0]
            if status == "ready":
                self._one("SELECT v12_send_work('jev', %s)", (batch,))
            self.conn.commit()
            return True
        batch, status = row
        if status == "answered":
            self._one("SELECT v12_route_turn(%s)", (batch,))
            self.conn.commit()
            return True
        if status == "failed":
            self._force_human(sid, "decision_failed")
            return True
        return False  # ready: waiting on the queue worker

    def _route_step(self, sid: str, route: dict) -> bool:
        r = route["route"]
        if r == "human":
            self._force_human(sid, route.get("reason", "human"))
            return True
        if r == "sql":
            tool = route["tool"]
            handler = self._one(
                "SELECT handler FROM tools WHERE name = %s", (tool,))[0]
            result = self._one(f"SELECT {handler}(%s)", (sid,))[0]
            self._append_event(sid, "tool/result",
                               {"tool": tool, "result": result,
                                "source": "sql_handler"})
            self._close(sid, True, "sql")
            return True
        if r == "tool":
            return self._tool_step(sid, route)
        if r == "llm":
            return self._llm_step(sid)
        raise RuntimeError(f"unknown route {r}")

    def _effect_job(self, sid: str, kind: str):
        eff = self._one("SELECT v12_effect_id(%s, %s)", (sid, kind))[0]
        return self._one(
            "SELECT job_id, status, result FROM jobs WHERE effect_id = %s",
            (eff,))

    def _tool_step(self, sid: str, route: dict) -> bool:
        tool = route["tool"]
        row = self._effect_job(sid, tool)
        if row is None:
            params = self._one("SELECT v12_resolve_tool_params(%s, %s)",
                               (route["batch_id"], tool))[0]
            job_id = self._one(
                "SELECT v12_enqueue_effect(%s, v12_effect_id(%s, %s), %s, %s)",
                (sid, sid, tool, tool,
                 json.dumps({"params": params, "batch_id": route["batch_id"]})))[0]
            self._one("SELECT v12_send_work('job', %s)", (job_id,))
            self.conn.commit()
            return True
        job_id, status, result = row
        if status == "succeeded":
            params = self._one("SELECT payload -> 'params' FROM jobs "
                               "WHERE job_id = %s", (job_id,))[0]
            self._append_event(sid, "tool/result",
                               {"tool": tool, "params": params,
                                "result": result, "job_id": job_id,
                                "source": "queue_worker"})
            self._close(sid, True, "tool")
            return True
        if status == "failed":
            self._force_human(sid, "tool_failed")
            return True
        if status in ("unknown", "resolved_ok", "resolved_abandoned"):
            self._force_human(sid, "job_unknown")
            return True
        return False  # queued/claimed: waiting on the queue worker

    def _llm_step(self, sid: str) -> bool:
        draft = self._last_event(sid, "turn/llm_draft")
        if draft is None:
            row = self._effect_job(sid, "llm")
            if row is None:
                messages = self._one(
                    "SELECT v12_fold_state(%s) -> 'messages'", (sid,))[0]
                job_id = self._one(
                    "SELECT v12_enqueue_effect(%s, v12_effect_id(%s, 'llm'), "
                    "'llm', %s)",
                    (sid, sid, json.dumps({"messages": messages})))[0]
                self._one("SELECT v12_send_work('job', %s)", (job_id,))
                self.conn.commit()
                return True
            job_id, status, result = row
            if status == "succeeded":
                self._append_event(sid, "turn/llm_draft",
                                   {"text": result["text"], "job_id": job_id})
                return True
            if status == "failed":
                self._force_human(sid, "llm_failed")
                return True
            if status in ("unknown", "resolved_ok", "resolved_abandoned"):
                self._force_human(sid, "job_unknown")
                return True
            return False

        row = self._latest_batch(sid, "guardrail")
        if row is None:
            state = {"messages": self._one(
                "SELECT v12_fold_state(%s) -> 'messages'", (sid,))[0],
                "draft": draft["text"]}
            g = self._one("SELECT v12_open_batch(%s, 'guardrail', %s)",
                          (sid, json.dumps(state)))[0]
            self._one("SELECT v12_build_guardrail_questions(%s)", (g,))
            status = self._one("SELECT v12_seal_batch(%s)", (g,))[0]
            if status == "ready":
                self._one("SELECT v12_send_work('jev', %s)", (g,))
            self.conn.commit()
            return True
        g, status = row
        if status == "answered":
            ok = self._one("SELECT v12_guardrail_ok(%s)", (g,))[0]
            if ok:
                self._append_event(sid, "llm/message", {"text": draft["text"]})
                self._close(sid, True, "llm")
            else:
                self._force_human(sid, "guardrail")
            return True
        if status == "failed":
            self._force_human(sid, "guardrail_batch_failed")
            return True
        return False
