"""v12 queue worker: polls PGMQ and does ALL external IO for queue mode.

This is the v3-v6 shape: a separate process whose only job is
message -> IO -> rows. It never advances the turn state machine (that is
the QueueDriver's SQL-only job); it answers batches (v12_record_answers)
and executes jobs through the G3 fence/lease discipline. Crash safety is
inherited: a message read but not archived reappears after its VT; the
state machine dedupes by status ('ready' CAS, claim fence).

Message shape on queue 'v12_work': {"kind": "jev"|"job", "id": uuid}.
Messages are wake-ups only — v12_requeue_stale rebuilds them from tables.
"""
from __future__ import annotations

import json

import psycopg2

QUEUE = "v12_work"


def _as_json(value) -> dict:
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


class QueueWorker:
    VT_SECONDS = 180
    RETRY_VT = 2          # redelivery delay for transient failures
    MAX_READ_CT = 5       # give up threshold -> mark failed + archive
    LEASE_SECONDS = 300

    def __init__(self, conn, client, tool_impls: dict | None = None,
                 llm_fn=None, worker_id: str = "v12-qw-1"):
        self.conn = conn
        self.cur = conn.cursor()
        self.client = client
        self.tool_impls = tool_impls or {}
        self.llm_fn = llm_fn
        self.worker_id = worker_id

    # ------------------------------------------------------------------ loop
    def _one(self, sql: str, params: tuple = ()):
        self.cur.execute(sql, params)
        return self.cur.fetchone()

    def _archive(self, msg_id: int) -> None:
        self._one("SELECT pgmq.archive(%s, %s)", (QUEUE, int(msg_id)))
        self.conn.commit()

    def _retry_later(self, msg_id: int) -> None:
        self.conn.rollback()
        self._one("SELECT pgmq.set_vt(%s, %s, %s)",
                  (QUEUE, int(msg_id), self.RETRY_VT))
        self.conn.commit()

    def pump(self, limit: int = 10) -> int:
        """One poll cycle. Returns the number of archived messages."""
        self.cur.execute("SELECT msg_id, read_ct, message FROM pgmq.read(%s, %s, %s)",
                         (QUEUE, self.VT_SECONDS, limit))
        messages = self.cur.fetchall()
        self.conn.commit()  # release the read's row locks promptly
        archived = 0
        for msg_id, read_ct, message in messages:
            if self._handle(msg_id, read_ct, _as_json(message)):
                self._archive(msg_id)
                archived += 1
        return archived

    def _handle(self, msg_id: int, read_ct: int, payload: dict) -> bool:
        """Returns True when the message is done (archive)."""
        try:
            if payload.get("kind") == "jev":
                return self._do_batch(msg_id, read_ct, payload["id"])
            if payload.get("kind") == "job":
                return self._do_job(msg_id, payload["id"])
        except KeyError:
            pass  # malformed wake-up: drop it, requeue_stale can rebuild
        except psycopg2.Error:
            self.conn.rollback()
            raise
        return True

    # ------------------------------------------------------------------ jev
    def _do_batch(self, msg_id: int, read_ct: int, batch_id: str) -> bool:
        row = self._one(
            "SELECT b.status, p -> 'state', p -> 'questions' "
            "FROM jev_batches b, LATERAL v12_request_payload(b.batch_id) p "
            "WHERE b.batch_id = %s", (batch_id,))
        if row is None or row[0] != "ready":
            return True  # stale or already handled wake-up
        _, state, questions = row

        from v12.jev_client import JevError
        try:
            resp = self.client.ask(state, questions)
        except JevError as exc:
            if exc.transient and read_ct < self.MAX_READ_CT:
                self._retry_later(msg_id)
                return False
            self.conn.rollback()
            self._fail_batch(batch_id, str(exc))
            return True

        try:
            self._one("SELECT v12_record_answers(%s, %s, %s, %s)",
                      (batch_id, json.dumps(resp["answers"]),
                       json.dumps(resp.get("usage", {})), None))
        except psycopg2.Error:
            self.conn.rollback()
            status = self._one(
                "SELECT status FROM jev_batches WHERE batch_id = %s",
                (batch_id,))[0]
            if status == "answered":
                return True  # a racing worker won the CAS
            self._fail_batch(batch_id, "answer validation rejected the payload")
            return True
        self.conn.commit()
        return True

    def _fail_batch(self, batch_id: str, error: str) -> None:
        self.cur.execute(
            "UPDATE jev_batches SET status = 'failed', "
            "usage = jsonb_build_object('error', %s) "
            "WHERE batch_id = %s AND status = 'ready'",
            (error[:400], batch_id))
        self.conn.commit()

    # ------------------------------------------------------------------ jobs
    def _do_job(self, msg_id: int, job_id: str) -> bool:
        row = self._one(
            "SELECT kind, payload, status FROM jobs WHERE job_id = %s",
            (job_id,))
        if row is None:
            return True
        kind, payload, status = row
        if status in ("succeeded", "failed", "unknown",
                      "resolved_ok", "resolved_abandoned"):
            return True  # settled; stale wake-up

        try:
            fence = self._one("SELECT v12_claim_job(%s, %s, %s)",
                              (job_id, self.worker_id,
                               self.LEASE_SECONDS))[0]
        except psycopg2.Error:
            # live lease elsewhere or mid-transition: try again after VT
            self._retry_later(msg_id)
            return False

        if isinstance(payload, str):
            payload = json.loads(payload)
        try:
            if kind == "llm":
                if self.llm_fn is None:
                    raise RuntimeError("no llm_fn configured")
                result, outcome, error = {"text": self.llm_fn(payload)}, \
                    "succeeded", None
            else:
                if kind not in self.tool_impls:
                    raise RuntimeError(f"no tool impl for {kind}")
                result, outcome, error = self.tool_impls[kind](payload), \
                    "succeeded", None
        except Exception as exc:  # noqa: BLE001 — worker boundary
            result, outcome, error = None, "failed", str(exc)

        self._one("SELECT v12_complete_job(%s, %s, %s, %s, %s)",
                  (job_id, fence, outcome,
                   json.dumps(result) if result is not None else None, error))
        self.conn.commit()
        return True
