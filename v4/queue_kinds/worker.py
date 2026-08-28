"""W3 worker: llm + embed + sql_heavy processors. Does not poll human_inbox."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import psycopg2
import psycopg2.errors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from v4.plugin_taxonomy.worker import AgentWorker as BaseWorker
from v4.plugin_taxonomy.worker import _as_dict, _payload, _result, connect

DB = "agent_v4_queue_kinds"
POLL_QUEUES = ("llm_requests", "embed_requests", "sql_heavy_requests")
QUEUE_DLQ = {
    "llm_requests": "llm_requests_dlq",
    "embed_requests": "embed_requests_dlq",
    "sql_heavy_requests": "sql_heavy_requests_dlq",
}


class AgentWorker(BaseWorker):
    def __init__(
        self,
        uri: str,
        *,
        embed_fn: Callable[..., Any] | None = None,
        sql_heavy_fn: Callable[..., dict] | None = None,
        poll_queues: tuple[str, ...] = POLL_QUEUES,
        **kwargs,
    ) -> None:
        kwargs.setdefault("db", DB)
        super().__init__(uri, **kwargs)
        self.embed_fn = embed_fn
        self.sql_heavy_fn = sql_heavy_fn
        self.poll_queues = poll_queues

    def dead_letter(self, msg_id: int, payload: dict, read_ct: int, reason: str,
                    queue: str | None = None) -> dict:
        q = queue or self.queue
        prev = self.dlq
        self.dlq = QUEUE_DLQ.get(q, prev)
        try:
            return super().dead_letter(msg_id, payload, read_ct, reason, queue=q)
        finally:
            self.dlq = prev

    def process_message(self, queue: str, payload: dict) -> dict:
        if queue == "llm_requests":
            raw = self._invoke_llm(payload)
            return {"raw": raw}
        if queue == "embed_requests":
            if self.embed_fn is None:
                raise RuntimeError("embed_fn is required for embed_requests")
            vec = self.embed_fn(payload.get("text") or "")
            if hasattr(vec, "tolist"):
                vec = vec.tolist()
            return {
                "embedding": list(vec),
                "dim": len(list(vec)),
                "request_id": payload.get("request_id"),
            }
        if queue == "sql_heavy_requests":
            if self.sql_heavy_fn is not None:
                return self.sql_heavy_fn(payload)
            return self._run_sql_heavy(payload)
        raise RuntimeError(f"worker does not process queue {queue}")

    def _run_sql_heavy(self, payload: dict) -> dict:
        sql = payload.get("sql") or ""
        max_rows = int(payload.get("max_rows") or 50)
        timeout_ms = int(payload.get("timeout_ms") or 120000)
        conn = connect(self.uri, autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {int(timeout_ms)}")
                cur.execute(
                    "SELECT COALESCE(jsonb_agg(t), '[]'::jsonb) FROM ("
                    + sql
                    + f" LIMIT {int(max_rows)}) t"
                )
                data = cur.fetchone()[0]
            if isinstance(data, str):
                data = json.loads(data)
            return {
                "success": True,
                "data": data,
                "row_count": len(data) if isinstance(data, list) else None,
                "request_id": payload.get("request_id"),
            }
        except psycopg2.errors.QueryCanceled as exc:
            return {"success": False, "error": "timeout", "detail": str(exc)}
        except Exception as exc:
            return {"success": False, "error": str(exc), "sqlstate": getattr(exc, "pgcode", None)}
        finally:
            conn.close()

    def handle_row(self, row) -> dict:
        row = _as_dict(row)
        msg_id = int(row["msg_id"])
        read_ct = int(row.get("read_ct") or 0)
        payload = _payload(row["message"])
        run_id = payload["run_id"]
        queue = row.get("_queue") or self.queue

        if read_ct > self.max_read_ct:
            return self.dead_letter(
                msg_id, payload, read_ct,
                f"read_ct {read_ct} exceeded max {self.max_read_ct}",
                queue=queue,
            )

        if self.crash_after_read > 0:
            self.crash_after_read -= 1
            raise RuntimeError("simulated crash after read")

        try:
            body = self.process_message(queue, payload)
        except Exception as exc:
            return {
                "done": False,
                "ok": False,
                "retry_wait": True,
                "run_id": run_id,
                "msg_id": msg_id,
                "error": str(exc),
            }

        result_body = json.dumps(body, ensure_ascii=False)
        run_conn = self.conn_for(run_id)
        was_autocommit = run_conn.autocommit
        run_conn.autocommit = False
        try:
            with run_conn.cursor() as cur:
                cur.execute(
                    "SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                    (queue, msg_id, run_id, result_body),
                )
                result = _result(cur.fetchone()[0])
                cur.execute("SELECT pgmq.archive(%s, %s::bigint)", (queue, msg_id))
            run_conn.commit()
        except Exception:
            run_conn.rollback()
            raise
        finally:
            run_conn.autocommit = was_autocommit

        result["msg_id"] = msg_id
        result["run_id"] = run_id
        if result.get("done"):
            self.drop_run_conn(run_id, conn=run_conn)
        elif not self.sticky:
            self.drop_run_conn(run_id, conn=run_conn)
        return result

    def pump_once(self) -> dict | None:
        for q in self.poll_queues:
            row = self.read_one(q)
            if row:
                return self.handle_row(row)
        return None

    def drain(self, run_id: str, timeout: float = 120) -> dict:
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            try:
                result = self.pump_once()
            except RuntimeError as exc:
                if "simulated crash" in str(exc):
                    time.sleep(min(self.vt + 0.2, 2.0))
                    continue
                raise
            if result is None:
                time.sleep(self.poll)
                continue
            last = result
            if result.get("retry_wait"):
                time.sleep(min(max(self.vt, 0.2), 2.0))
                continue
            if result.get("run_id") != run_id:
                continue
            if result.get("done") or result.get("dead_lettered"):
                return result
            if result.get("waiting") and result.get("wait_kind") in ("human", "human_inbox"):
                return result
        return last or {"done": True, "ok": False, "error": "timeout", "run_id": run_id}
