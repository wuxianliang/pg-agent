"""v6 W1 worker baseline: a version-local copy of the v5 worker structure.
It does not import v4/v5 runtime modules; inherited SQL remains path-loaded.
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
import psycopg2.errors
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v6.queue_bridge.duckdb_processor import DuckDBWorkerProcessor
from v6.source_ingress.duckdb_ingress import PostgresSourceResolver, SourceConfig

DB = "agent_v6_kernel_freeze"
QUEUE = "llm_requests"
DLQ = "llm_requests_dlq"
VT_SECONDS = 180
MAX_READ_CT = 5
POLL_QUEUES = ("llm_requests", "embed_requests", "sql_heavy_requests", "duck_heavy_requests")
QUEUE_DLQ = {
    "llm_requests": "llm_requests_dlq",
    "embed_requests": "embed_requests_dlq",
    "sql_heavy_requests": "sql_heavy_requests_dlq",
    "duck_heavy_requests": "duck_heavy_requests_dlq",
}
ALLOWED_METRIC_KEYS = {
    "queue", "queue_kind", "msg_id", "worker_id", "attempts", "duration_ms",
    "model", "provider", "input_tokens", "output_tokens", "total_tokens", "cost_usd",
}


def connect(uri: str, autocommit: bool = True):
    conn = psycopg2.connect(uri)
    conn.autocommit = autocommit
    return conn


def _as_dict(row) -> dict:
    if row is None:
        return {}
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


def normalize_metrics(metrics: dict | None, **extra) -> dict:
    out = {}
    src = dict(metrics or {})
    src.update({k: v for k, v in extra.items() if v is not None})
    for k in ALLOWED_METRIC_KEYS:
        if k in src and src[k] is not None:
            out[k] = src[k]
    return out


class AgentWorker:
    """Poll connection reads queues; each run_id keeps a sticky apply connection."""

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
        embed_fn: Callable[..., Any] | None = None,
        sql_heavy_fn: Callable[..., dict] | None = None,
        duck_processor: DuckDBWorkerProcessor | None = None,
        db: str = DB,
        queue: str = QUEUE,
        dlq: str = DLQ,
        poll_queues: tuple[str, ...] = POLL_QUEUES,
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
        self.embed_fn = embed_fn
        self.sql_heavy_fn = sql_heavy_fn
        self.duck_processor = duck_processor
        self.db = db
        self.queue = queue
        self.dlq = dlq
        self.poll_queues = poll_queues
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
        if self.duck_processor is not None:
            try:
                self.duck_processor.close()
            except Exception:
                pass
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
        prev = self.dlq
        self.dlq = QUEUE_DLQ.get(q, prev)
        try:
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
                if q == "duck_heavy_requests" and payload.get("request_id"):
                    with self.poll_conn.cursor() as cur:
                        cur.execute(
                            "UPDATE duck_operations SET status='DLQ', error=%s::jsonb, finished_at=now() WHERE request_id=%s AND status NOT IN ('SUCCEEDED','FAILED','DLQ','REPLAYED')",
                            (json.dumps({"Type": "DUCK_QUEUE_DLQ", "Problem": reason[:500]}, ensure_ascii=False), payload.get("request_id")),
                        )
                self.drop_run_conn(run_id)
            fail["dead_lettered"] = True
            fail["msg_id"] = msg_id
            return fail
        finally:
            self.dlq = prev

    def process_message(self, queue: str, payload: dict) -> dict:
        if queue != "llm_requests":
            if queue == "embed_requests":
                if self.embed_fn is None:
                    raise RuntimeError("embed_fn is required for embed_requests")
                vec = self.embed_fn(payload.get("text") or "")
                if hasattr(vec, "tolist"):
                    vec = vec.tolist()
                body = {
                    "embedding": list(vec),
                    "dim": len(list(vec)),
                    "request_id": payload.get("request_id"),
                }
            elif queue == "sql_heavy_requests":
                if self.sql_heavy_fn is not None:
                    body = self.sql_heavy_fn(payload)
                else:
                    body = self._run_sql_heavy(payload)
            elif queue == "duck_heavy_requests":
                if self.duck_processor is None:
                    raise RuntimeError("duck_processor is required for duck_heavy_requests")
                body = self.duck_processor.process(payload)
            else:
                raise RuntimeError(f"worker does not process queue {queue}")
            if isinstance(body, dict):
                body.setdefault("metrics", normalize_metrics(
                    {},
                    queue=queue,
                    queue_kind={
                        "embed_requests": "embed",
                        "sql_heavy_requests": "sql_heavy",
                        "duck_heavy_requests": "duck_heavy",
                    }.get(queue),
                    model=self.model,
                    provider="openai",
                ))
            return body

        t0 = time.time()
        last: Exception | None = None
        attempts = max(1, self.llm_retries + 1)
        used = 0
        out: Any = None
        for i in range(attempts):
            used = i + 1
            try:
                if self.llm_fn is not None:
                    out = self.llm_fn(
                        payload["messages"],
                        model=self.model,
                        api_uri=self.api_uri,
                        api_key=self.api_key,
                    )
                else:
                    out = call_llm(
                        payload["messages"],
                        model=self.model,
                        api_uri=self.api_uri,
                        api_key=self.api_key,
                        num_retries=0,
                    )
                last = None
                break
            except Exception as exc:
                last = exc
                time.sleep(0.05 * (i + 1))
        if last is not None:
            raise last
        duration_ms = round((time.time() - t0) * 1000, 3)
        raw = out
        metrics: dict = {}
        if isinstance(out, dict) and ("raw" in out or "metrics" in out):
            raw = out.get("raw")
            if isinstance(raw, dict):
                raw = json.dumps(raw, ensure_ascii=False)
            metrics = dict(out.get("metrics") or {})
        elif isinstance(out, dict):
            raw = json.dumps(out, ensure_ascii=False)
        return {
            "raw": raw,
            "metrics": normalize_metrics(
                metrics,
                queue=queue,
                queue_kind="llm",
                attempts=used,
                duration_ms=duration_ms,
                model=self.model,
                provider="openai",
                worker_id="worker-1",
            ),
        }

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
            return {
                "success": False,
                "error": str(exc),
                "sqlstate": getattr(exc, "pgcode", None),
            }
        finally:
            conn.close()

    def handle_row(self, row) -> dict:
        row = _as_dict(row)
        msg_id = int(row["msg_id"])
        read_ct = int(row.get("read_ct") or 0)
        queue = row.get("_queue") or self.queue
        try:
            payload = _payload(row["message"])
            if not isinstance(payload, dict):
                raise ValueError("message must be a JSON object")
            run_id = payload.get("run_id")
            if not run_id:
                raise ValueError("message missing run_id")
        except Exception as exc:
            return self.dead_letter(msg_id, {"payload_error": str(exc)}, read_ct, "malformed queue message", queue=queue)

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

        if queue == "duck_heavy_requests" and body.get("status") == "retry":
            return {"done": False, "ok": False, "retry_wait": True, "run_id": run_id, "msg_id": msg_id, "error": body.get("Problem"), "out_of_order": True}

        result_body = json.dumps(body, ensure_ascii=False, default=str)
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
            if result.get("waiting"):
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
    p.add_argument("--db", default=os.environ.get("PG_AGENT_DB", "agent_v6_integration"))
    p.add_argument("--sources-json", default=os.environ.get("PG_AGENT_DUCK_SOURCES", "{}"))
    args = p.parse_args()
    server = get_server()
    source_data = json.loads(args.sources_json)
    configs = []
    for source_id, raw in source_data.items():
        configs.append(SourceConfig(
            source_id=source_id,
            uri=raw["uri"],
            allowed_tables=frozenset((item[0], item[1]) for item in raw.get("allowed_tables", [])),
            max_rows=int(raw.get("max_rows", 100000)),
            max_bytes=int(raw.get("max_bytes", 64 * 1024 * 1024)),
        ))
    resolver = PostgresSourceResolver(configs)
    duck_processor = DuckDBWorkerProcessor(server.get_uri(args.db), resolver=resolver, worker_id=os.environ.get("PG_AGENT_WORKER_ID", "v6-worker-1"))
    worker = AgentWorker(
        server.get_uri(args.db),
        api_uri=args.api_uri,
        api_key=args.api_key,
        model=args.model,
        vt=args.vt,
        max_read_ct=args.max_read_ct,
        llm_retries=args.llm_retries,
        sticky=not args.no_sticky,
        poll=args.poll,
        db=args.db,
        duck_processor=duck_processor,
    )
    try:
        worker.run_forever()
    finally:
        worker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
