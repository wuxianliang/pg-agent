"""v4 W1 worker: PGMQ read, LLM outside SQL, apply_queue_result + archive in one txn.

Copied from v3/worker.py semantics; does not import or patch v3.
v4 apply goes through the generic dispatcher (apply_queue_result),
never the v3 hardcoded apply helper, and never SQL-side model HTTP.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

import litellm
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server

DB = "agent_v4_plugin_taxonomy"
QUEUE = "llm_requests"
DLQ = "llm_requests_dlq"
VT_SECONDS = 180
MAX_READ_CT = 5


def connect(uri: str, autocommit: bool = True):
    conn = psycopg2.connect(uri)
    conn.autocommit = autocommit
    return conn


def _as_dict(row) -> dict:
    if row is None:
        return {}
    # RealDictRow is a dict subclass that rejects unknown keys such as _queue.
    return dict(row)


def _payload(value) -> dict:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, memoryview):
        return json.loads(bytes(value))
    return dict(value)


def _result(value) -> dict:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, memoryview):
        return json.loads(bytes(value))
    return dict(value)


def call_llm(
    messages,
    *,
    model: str,
    api_uri: str,
    api_key: str,
    num_retries: int = 2,
    timeout: float = 90,
) -> str:
    """LiteLLM SDK in-process. 429/5xx retry stays in this step; no archive."""
    api_base = (api_uri or "").rstrip("/")
    last: Exception | None = None
    attempts = max(1, num_retries + 1)
    for i in range(attempts):
        try:
            resp = litellm.completion(
                model=f"openai/{model}",
                messages=messages,
                api_base=api_base,
                api_key=api_key or "none",
                temperature=0.1,
                response_format={"type": "json_object"},
                num_retries=0,
                timeout=timeout,
            )
            content = resp.choices[0].message.content
            if not content or not str(content).strip():
                raise RuntimeError("LLM 返回为空")
            return str(content)
        except Exception as exc:
            last = exc
            if i + 1 >= attempts:
                break
            time.sleep(0.05 * (i + 1))
    assert last is not None
    raise last


class AgentWorker:
    """Poll connection reads the queue; each run_id keeps a sticky apply connection."""

    def __init__(
        self,
        uri: str,
        *,
        api_uri: str,
        api_key: str,
        model: str,
        vt: int = VT_SECONDS,
        max_read_ct: int = MAX_READ_CT,
        llm_retries: int = 2,
        sticky: bool = True,
        poll: float = 0.2,
        llm_fn: Callable[..., str] | None = None,
        db: str = DB,
        queue: str = QUEUE,
        dlq: str = DLQ,
    ) -> None:
        self.uri = uri
        self.api_uri = api_uri
        self.api_key = api_key
        self.model = model
        self.vt = vt
        self.max_read_ct = max_read_ct
        self.llm_retries = llm_retries
        self.sticky = sticky
        self.poll = poll
        self.llm_fn = llm_fn
        self.db = db
        self.queue = queue
        self.dlq = dlq
        self.poll_conn = connect(uri, autocommit=True)
        self._run_conns: dict[str, Any] = {}
        self.crash_after_read = 0

    def close(self) -> None:
        for conn in list(self._run_conns.values()):
            try:
                conn.close()
            except Exception:
                pass
        self._run_conns.clear()
        try:
            self.poll_conn.close()
        except Exception:
            pass

    def conn_for(self, run_id: str):
        if not self.sticky:
            return connect(self.uri, autocommit=True)
        conn = self._run_conns.get(run_id)
        if conn is None or getattr(conn, "closed", 1):
            conn = connect(self.uri, autocommit=True)
            self._run_conns[run_id] = conn
        return conn

    def drop_run_conn(self, run_id: str, conn=None) -> None:
        owned = self._run_conns.pop(run_id, None)
        target = owned or conn
        if target is not None and (owned is not None or not self.sticky):
            try:
                target.close()
            except Exception:
                pass

    def read_one(self, queue: str | None = None):
        q = queue or self.queue
        with self.poll_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT msg_id, read_ct, message FROM pgmq.read(%s, %s, 1)",
                (q, self.vt),
            )
            row = cur.fetchone()
        if row is None:
            return None
        out = _as_dict(row)
        out["_queue"] = q
        return out

    def _invoke_llm(self, payload: dict) -> str:
        messages = payload["messages"]
        model = self.model or payload.get("model")
        api_uri = self.api_uri or payload.get("api_uri")
        last: Exception | None = None
        attempts = max(1, self.llm_retries + 1)
        for i in range(attempts):
            try:
                if self.llm_fn is not None:
                    return self.llm_fn(
                        messages, model=model, api_uri=api_uri, api_key=self.api_key
                    )
                return call_llm(
                    messages,
                    model=model,
                    api_uri=api_uri,
                    api_key=self.api_key,
                    num_retries=0,
                )
            except Exception as exc:
                last = exc
                if i + 1 >= attempts:
                    break
                time.sleep(0.05 * (i + 1))
        assert last is not None
        raise last

    def dead_letter(self, msg_id: int, payload: dict, read_ct: int, reason: str,
                    queue: str | None = None) -> dict:
        q = queue or self.queue
        run_id = payload.get("run_id")
        body = {
            **payload,
            "dlq_reason": reason,
            "read_ct": read_ct,
            "original_msg_id": msg_id,
        }
        with self.poll_conn.cursor() as cur:
            cur.execute(
                "SELECT pgmq.send(%s, %s::jsonb)",
                (self.dlq, json.dumps(body, ensure_ascii=False)),
            )
            cur.execute("SELECT pgmq.archive(%s, %s::bigint)", (q, msg_id))
            if run_id:
                cur.execute("SELECT fail_run(%s, %s)", (run_id, reason))
                fail = _result(cur.fetchone()[0])
            else:
                fail = {"done": True, "ok": False, "error": reason}
        if run_id:
            self.drop_run_conn(run_id)
        fail["dead_lettered"] = True
        fail["msg_id"] = msg_id
        return fail

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
            raw = self._invoke_llm(payload)
        except Exception as exc:
            return {
                "done": False,
                "ok": False,
                "retry_wait": True,
                "run_id": run_id,
                "msg_id": msg_id,
                "error": str(exc),
            }

        result_body = json.dumps({"raw": raw}, ensure_ascii=False)
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
        row = self.read_one()
        if not row:
            return None
        return self.handle_row(row)

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
            if result.get("run_id") == run_id and result.get("done"):
                return result
        return last or {"done": True, "ok": False, "error": "timeout", "run_id": run_id}

    def run_forever(self) -> None:
        print(
            f"[worker] queue={self.queue} db={self.db} model={self.model} "
            f"sticky={self.sticky} vt={self.vt} max_read_ct={self.max_read_ct}",
            flush=True,
        )
        while True:
            try:
                result = self.pump_once()
                if result is None:
                    time.sleep(self.poll)
                    continue
                print(
                    f"[worker] run={result.get('run_id')} done={result.get('done')} "
                    f"ok={result.get('ok')} dlq={result.get('dead_lettered', False)}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[worker] ERROR: {exc}", flush=True)
                time.sleep(1)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--poll", type=float, default=0.2)
    p.add_argument("--vt", type=int, default=VT_SECONDS)
    p.add_argument("--max-read-ct", type=int, default=MAX_READ_CT)
    p.add_argument("--llm-retries", type=int, default=2)
    p.add_argument("--no-sticky", action="store_true")
    p.add_argument("--api-uri", default=os.environ.get("OPENAI_API_URI", "https://api.deepseek.com/v1"))
    p.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or "none")
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "deepseek-chat"))
    args = p.parse_args()
    server = get_server()
    worker = AgentWorker(
        server.get_uri(DB),
        api_uri=args.api_uri,
        api_key=args.api_key,
        model=args.model,
        vt=args.vt,
        max_read_ct=args.max_read_ct,
        llm_retries=args.llm_retries,
        sticky=not args.no_sticky,
        poll=args.poll,
    )
    try:
        worker.run_forever()
    finally:
        worker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
