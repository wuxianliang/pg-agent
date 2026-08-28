"""库外 LLM worker：PGMQ 取消息，LiteLLM 发请求，粘住 run 连接写回 apply。

边界：
- 等模型时不持有打开的 SQL 事务。
- 每个 run_id 一条粘住的连接（TEMP / session_set 跨轮次可见）。
- LLM 429/5xx 由 LiteLLM 在同一步内重试；进程崩溃靠 PGMQ visibility timeout 整步重放。
- read_ct 超限进 llm_requests_dlq，run 标 error。
- apply + archive 同一事务，避免「已落库未出队」。
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server

DB = "agent_v3"
QUEUE = "llm_requests"
DLQ = "llm_requests_dlq"
VT_SECONDS = 180
MAX_READ_CT = 5


def connect(uri: str, autocommit: bool = True):
    conn = psycopg2.connect(uri)
    conn.autocommit = autocommit
    return conn


def set_llm_gucs(cur, api_uri: str, api_key: str, model: str) -> None:
    cur.execute("SELECT set_config('openai.api_uri', %s, false)", (api_uri,))
    cur.execute("SELECT set_config('openai.api_key', %s, false)", (api_key or "none",))
    cur.execute("SELECT set_config('openai.model', %s, false)", (model,))


def _as_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
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
    """LiteLLM 发请求；429/5xx/超时在同一步内重试，不 archive、不加 read_ct。"""
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
    """Poll 连接专门读队列；每个 run 一条粘住的连接跑 apply / 工具 SQL。"""

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

    def read_one(self):
        with self.poll_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT msg_id, read_ct, message FROM pgmq.read(%s, %s, 1)",
                (QUEUE, self.vt),
            )
            return cur.fetchone()

    def _invoke_llm(self, payload: dict) -> str:
        messages = payload["messages"]
        # 模型与网关由 worker 持有；payload 里的 uri 只是 SQL 当时的 GUC 快照。
        model = self.model or payload.get("model")
        api_uri = self.api_uri or payload.get("api_uri")
        if self.llm_fn is not None:
            return self.llm_fn(messages, model=model, api_uri=api_uri, api_key=self.api_key)
        return call_llm(
            messages,
            model=model,
            api_uri=api_uri,
            api_key=self.api_key,
            num_retries=self.llm_retries,
        )

    def dead_letter(self, msg_id: int, payload: dict, read_ct: int, reason: str) -> dict:
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
                (DLQ, json.dumps(body, ensure_ascii=False)),
            )
            cur.execute("SELECT pgmq.archive(%s, %s::bigint)", (QUEUE, msg_id))
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

        if read_ct > self.max_read_ct:
            return self.dead_letter(
                msg_id, payload, read_ct,
                f"read_ct {read_ct} exceeded max {self.max_read_ct}",
            )

        if self.crash_after_read > 0:
            self.crash_after_read -= 1
            raise RuntimeError("simulated crash after read")

        # LLM 在任何 SQL 事务之外。失败不 archive，等 VT 整步重放。
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

        run_conn = self.conn_for(run_id)
        was_autocommit = run_conn.autocommit
        run_conn.autocommit = False
        try:
            with run_conn.cursor() as cur:
                set_llm_gucs(cur, self.api_uri, self.api_key, self.model)
                cur.execute("SELECT apply_llm_response(%s, %s)", (run_id, raw))
                result = _result(cur.fetchone()[0])
                cur.execute("SELECT pgmq.archive(%s, %s::bigint)", (QUEUE, msg_id))
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
            f"[worker] queue={QUEUE} db={DB} model={self.model} "
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


# compare.py 兼容：无粘连的单次处理（测试占用时仍把 LLM 放在 SQL 外）
def read_one(cur):
    cur.execute(
        "SELECT msg_id, read_ct, message FROM pgmq.read(%s, %s, 1)",
        (QUEUE, VT_SECONDS),
    )
    return cur.fetchone()


def process_one(cur, msg_id, payload: dict, *, api_key: str, default_uri: str, default_model: str) -> dict:
    run_id = payload["run_id"]
    messages = payload["messages"]
    model = payload.get("model") or default_model
    api_uri = payload.get("api_uri") or default_uri
    raw = call_llm(messages, model=model, api_uri=api_uri, api_key=api_key, num_retries=2)
    cur.execute("SELECT apply_llm_response(%s, %s)", (run_id, raw))
    result = _result(cur.fetchone()[0])
    cur.execute("SELECT pgmq.archive(%s, %s::bigint)", (QUEUE, msg_id))
    return result


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
