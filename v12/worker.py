"""v12 worker: the only place external IO happens.

The database owns the state machine (events, batches, decisions, jobs);
this runner only executes what is already persisted. All external IO —
Jev calls, LLM calls, side-effect tools — happens here, outside any
database transaction's critical decisions, and results land back as rows.

Protocol per cycle (durable across crashes — every step appends events or
settles rows before the next):
  no turn/route since last user message  -> decide (fold -> batch -> ask -> route)
  turn/route pending                     -> execute (sql | tool | llm | human)
  llm draft present                      -> guardrail -> deliver or escalate
The step budget is durable too: v12_turn_cycles counts persisted turn/route
events; MAX_CYCLES forces a human handoff instead of an endless loop.
"""
from __future__ import annotations

import json
import time
import uuid

import psycopg2


class TurnRunner:
    MAX_CYCLES = 3
    LEASE_SECONDS = 300

    def __init__(self, conn, client, tool_impls: dict | None = None,
                 llm_fn=None, worker_name: str = "v12-worker"):
        self.conn = conn
        self.cur = conn.cursor()
        self.client = client          # .ask(state, questions) -> {"answers": ...}
        self.tool_impls = tool_impls or {}
        self.llm_fn = llm_fn
        self.worker_name = worker_name

    # ------------------------------------------------------------------ SQL helpers
    def _one(self, sql: str, params: tuple = ()):
        self.cur.execute(sql, params)
        return self.cur.fetchone()

    def _append_event(self, session_id: str, type_: str, payload: dict) -> int:
        seq = self._one("SELECT v12_append_event(%s, %s, %s)",
                        (session_id, type_, json.dumps(payload)))[0]
        self.conn.commit()
        return seq

    # ------------------------------------------------------------------ decide plane
    def _ask_batch(self, batch_id: str) -> None:
        """If the batch is ready, call the client and record answers.
        Cached/answered batches already carry their decisions. The request
        object comes from v12_request_payload — the single source that also
        feeds request_hash, so state/questions can never drift apart."""
        row = self._one(
            "SELECT b.status, p -> 'state', p -> 'questions' "
            "FROM jev_batches b, LATERAL v12_request_payload(b.batch_id) p "
            "WHERE b.batch_id = %s", (batch_id,))
        status, state, questions = row
        if status == "ready":
            t0 = time.monotonic()
            resp = self.client.ask(state, questions)
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._one("SELECT v12_record_answers(%s, %s, %s, %s)",
                      (batch_id, json.dumps(resp["answers"]),
                       json.dumps(resp.get("usage", {})), latency_ms))
            self.conn.commit()
        elif status not in ("cached", "answered"):
            raise RuntimeError(f"batch {batch_id} in unexpected state {status}")

    def _decide(self, session_id: str) -> None:
        state = self._one("SELECT v12_fold_state(%s)", (session_id,))[0]
        batch = self._one("SELECT v12_open_batch(%s, 'turn', %s)",
                          (session_id, json.dumps(state)))[0]
        self._one("SELECT v12_build_turn_questions(%s, %s)", (batch, session_id))
        self._one("SELECT v12_seal_batch(%s)", (batch,))
        self.conn.commit()
        self._ask_batch(batch)
        self._one("SELECT v12_route_turn(%s)", (batch,))
        self.conn.commit()

    # ------------------------------------------------------------------ action plane
    def _effect_id(self, session_id: str, kind: str) -> str:
        user_seq = self._one("SELECT v12_last_user_seq(%s)", (session_id,))[0]
        return str(uuid.uuid5(uuid.UUID(int=0),
                              f"{session_id}:{user_seq}:{kind}"))

    def _run_job(self, job_id: str, kind: str, payload: dict):
        """Claim -> execute -> complete. If the job is already settled
        (crash between complete and the next append), replay its result."""
        try:
            fence = self._one("SELECT v12_claim_job(%s, %s, %s)",
                              (job_id, self.worker_name, self.LEASE_SECONDS))[0]
        except psycopg2.Error:
            self.conn.rollback()
            status, result = self._one(
                "SELECT status, result FROM jobs WHERE job_id = %s", (job_id,))
            if status == "succeeded":
                return result
            raise
        try:
            if kind == "llm":
                if self.llm_fn is None:
                    raise RuntimeError("no llm_fn configured")
                result = {"text": self.llm_fn(payload)}
            else:
                if kind not in self.tool_impls:
                    raise RuntimeError(f"no tool impl for {kind}")
                result = self.tool_impls[kind](payload)
            outcome, error = "succeeded", None
        except Exception as exc:  # noqa: BLE001 — worker boundary
            result, outcome, error = None, "failed", str(exc)
        self._one("SELECT v12_complete_job(%s, %s, %s, %s, %s)",
                  (job_id, fence, outcome,
                   json.dumps(result) if result is not None else None, error))
        self.conn.commit()
        status, result = self._one(
            "SELECT status, result FROM jobs WHERE job_id = %s", (job_id,))
        if status != "succeeded":
            raise RuntimeError(f"job {kind} ended {status}: {result}")
        return result

    def _run_effect(self, session_id: str, kind: str, payload: dict):
        effect_id = self._effect_id(session_id, kind)
        job_id = self._one("SELECT v12_enqueue_effect(%s, %s, %s, %s)",
                           (session_id, effect_id, kind,
                            json.dumps(payload)))[0]
        self.conn.commit()
        return job_id, self._run_job(job_id, kind, payload)

    # ------------------------------------------------------------------ routes
    def _last_event(self, session_id: str, type_: str, after_user=True):
        sql = ("SELECT payload FROM events WHERE session_id = %s AND type = %s "
               + ("AND seq > v12_last_user_seq(%s) " if after_user else "")
               + "ORDER BY seq DESC LIMIT 1")
        params = (session_id, type_, session_id) if after_user else (session_id, type_)
        row = self._one(sql, params)
        return row[0] if row else None

    def _close(self, session_id: str, delivered: bool, reason: str) -> None:
        self._one("SELECT v12_close_turn(%s, %s, %s)",
                  (session_id, delivered, reason))
        self.conn.commit()

    def _force_human(self, session_id: str, reason: str) -> None:
        self._one("SELECT v12_set_status(%s, 'awaiting_human')", (session_id,))
        self.conn.commit()
        self._close(session_id, False, reason)

    def _execute_route(self, session_id: str, route_payload: dict) -> None:
        route = route_payload["route"]
        if route == "human":
            self._force_human(session_id, route_payload.get("reason", "human"))
        elif route == "sql":
            tool = route_payload.get("tool")
            handler = self._one(
                "SELECT handler FROM tools WHERE name = %s", (tool,))[0]
            result = self._one(f"SELECT {handler}(%s)", (session_id,))[0]
            self._append_event(session_id, "tool/result",
                               {"tool": tool, "result": result,
                                "source": "sql_handler"})
            self._close(session_id, True, "sql")
        elif route == "tool":
            tool = route_payload["tool"]
            batch = route_payload["batch_id"]
            params = self._one("SELECT v12_resolve_tool_params(%s, %s)",
                               (batch, tool))[0]
            job_id, result = self._run_effect(
                session_id, tool,
                {"params": params, "batch_id": batch})
            self._append_event(session_id, "tool/result",
                               {"tool": tool, "params": params,
                                "result": result, "job_id": job_id,
                                "source": "worker_tool"})
            self._close(session_id, True, "tool")
        elif route == "llm":
            draft = self._last_event(session_id, "turn/llm_draft")
            if draft is None:
                messages = self._one(
                    "SELECT v12_fold_state(%s) -> 'messages'",
                    (session_id,))[0]
                _, result = self._run_effect(
                    session_id, "llm", {"messages": messages})
                self._append_event(session_id, "turn/llm_draft",
                                   {"text": result["text"]})
            else:
                text = draft["text"]
                state = {"messages": self._one(
                    "SELECT v12_fold_state(%s) -> 'messages'", (session_id,))[0],
                    "draft": text}
                gbatch = self._one(
                    "SELECT v12_open_batch(%s, 'guardrail', %s)",
                    (session_id, json.dumps(state)))[0]
                self._one("SELECT v12_build_guardrail_questions(%s)", (gbatch,))
                self._one("SELECT v12_seal_batch(%s)", (gbatch,))
                self.conn.commit()
                self._ask_batch(gbatch)
                ok = self._one("SELECT v12_guardrail_ok(%s)", (gbatch,))[0]
                if ok:
                    self._append_event(session_id, "llm/message", {"text": text})
                    self._close(session_id, True, "llm")
                else:
                    self._force_human(session_id, "guardrail")
        else:
            raise RuntimeError(f"unknown route {route}")

    # ------------------------------------------------------------------ main loop
    def run_turn(self, session_id: str) -> None:
        while True:
            if not self._one("SELECT v12_turn_open(%s)", (session_id,))[0]:
                return
            if self._one("SELECT v12_turn_cycles(%s)", (session_id,))[0] \
                    >= self.MAX_CYCLES:
                self._force_human(session_id, "budget_exhausted")
                return
            route_payload = self._last_event(session_id, "turn/route")
            if route_payload is None:
                self._decide(session_id)
            else:
                self._execute_route(session_id, route_payload)


def say_user(runner: TurnRunner, session_id: str, text: str) -> None:
    """Append a user message — the entry point that opens a turn."""
    runner._append_event(session_id, "user/message", {"text": text})
