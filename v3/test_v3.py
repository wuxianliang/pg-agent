"""v3 门闩：prepare/apply、粘连接、VT 崩溃重放、LiteLLM 步内重试、read_ct 死信。"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
from server import get_server
from setup_db import DB, main as setup_db
from worker import AgentWorker, QUEUE, DLQ, call_llm

RESULTS: list[tuple[str, str, str]] = []
QUESTION = "demo_sales 表里 South 在 2025-02 的 revenue 是多少？只给数字。"


def check(name: str, cond, detail: str = "") -> None:
    RESULTS.append((name, "pass" if cond else "fail", str(detail)[:240]))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  | {detail}" if detail != "" else ""))


def conn(uri: str):
    c = psycopg2.connect(uri)
    c.autocommit = True
    return c


def seed(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS demo_sales")
    cur.execute("""
        CREATE TABLE demo_sales (
            month text NOT NULL, segment text NOT NULL, revenue int NOT NULL)
    """)
    cur.execute("""
        INSERT INTO demo_sales (month, segment, revenue) VALUES
            ('2025-01','North',100),('2025-01','South',200),
            ('2025-02','North',150),('2025-02','South',250)
    """)


def purge(cur) -> None:
    cur.execute("SELECT pgmq.purge_queue(%s)", (QUEUE,))
    cur.execute("SELECT pgmq.purge_queue(%s)", (DLQ,))


def scripted(script: list[dict]):
    state = {"n": 0}

    def fn(messages, **kwargs):
        i = min(state["n"], len(script) - 1)
        state["n"] += 1
        return json.dumps(script[i], ensure_ascii=False)

    fn.state = state  # type: ignore[attr-defined]
    return fn


def start_run(c, question: str = QUESTION, max_steps: int = 5) -> str:
    with c.cursor() as cur:
        seed(cur)
        purge(cur)
        cur.execute("SELECT set_config('openai.api_uri', 'http://127.0.0.1/v1', false)")
        cur.execute("SELECT set_config('openai.model', 'mock', false)")
        cur.execute("SELECT agent_start(%s, %s)", (question, max_steps))
        return cur.fetchone()[0]


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def tool_obs(c, run_id: str) -> list[str]:
    with c.cursor() as cur:
        cur.execute(
            "SELECT payload->>'observation' FROM agent_steps "
            "WHERE run_id=%s AND kind='tool' ORDER BY seq",
            (run_id,),
        )
        return [r[0] or "" for r in cur.fetchall()]


def test_happy(uri) -> None:
    print("\n[1] prepare/apply 主路径")
    c = conn(uri)
    try:
        run_id = start_run(c)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "查表", "action": "execute_sql",
                 "action_input": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
                 "final_answer": None},
                {"thought": "有了", "action": None, "action_input": None, "final_answer": "250"},
            ]),
        )
        try:
            result = w.drain(run_id, timeout=30)
        finally:
            w.close()
        st = run_state(c, run_id)
        check("happy SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("happy answer 250", st[2] == "250", st[2])
        check("happy 2 llm steps", st[1] == 2, st[1])
    finally:
        c.close()


def test_sticky(uri) -> None:
    print("\n[2] 粘连接：session_set 跨 LLM 轮次可见")
    script = [
        {"thought": "写会话", "action": "execute_sql",
         "action_input": "SELECT session_set('token','sticky-ok')",
         "final_answer": None},
        {"thought": "读会话", "action": "execute_sql",
         "action_input": "SELECT session_get('token')",
         "final_answer": None},
        {"thought": "交卷", "action": None, "action_input": None, "final_answer": "sticky-ok"},
    ]
    c = conn(uri)
    try:
        run_id = start_run(c, "把 token 放进会话再读出来，final_answer 用读到的值")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_fn=scripted(script),
        )
        try:
            w.drain(run_id, timeout=30)
        finally:
            w.close()
        obs = tool_obs(c, run_id)
        sticky_hit = any("sticky-ok" in o for o in obs)
        check("sticky session_get 看见写入", sticky_hit, obs[-1][:180] if obs else "no obs")

        run_id2 = start_run(c, "把 token 放进会话再读出来")
        w2 = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=False, poll=0.05, llm_fn=scripted(script),
        )
        try:
            w2.drain(run_id2, timeout=30)
        finally:
            w2.close()
        obs2 = tool_obs(c, run_id2)
        lost = any(
            '"value": null' in o or '"value":null' in o
            for o in obs2[1:]
        ) if len(obs2) > 1 else False
        check("非粘连 session_get 读不到上一轮", lost, obs2[-1][:180] if obs2 else "no obs")
    finally:
        c.close()


def test_vt_crash(uri) -> None:
    print("\n[3] 读出后崩溃：VT 到期重放，apply 不重复")
    c = conn(uri)
    try:
        run_id = start_run(c)
        fn = scripted([
            {"thought": "查表", "action": "execute_sql",
             "action_input": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
             "final_answer": None},
            {"thought": "有了", "action": None, "action_input": None, "final_answer": "250"},
        ])
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, vt=1, llm_fn=fn,
        )
        w.crash_after_read = 1
        try:
            result = w.drain(run_id, timeout=20)
        finally:
            w.close()
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='llm'",
                (run_id,),
            )
            llm_n = cur.fetchone()[0]
        check("crash 后仍 SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("crash 重放不重复 llm 步", llm_n == 2, llm_n)
        check("崩溃在 LLM 之前，成功路径仍只调两次模型", fn.state["n"] == 2, fn.state["n"])
    finally:
        c.close()


class RetryHandler(BaseHTTPRequestHandler):
    hits = 0
    fail_first = 2
    responses = [
        {"thought": "交卷", "action": None, "action_input": None, "final_answer": "250"},
    ]

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        RetryHandler.hits += 1
        if RetryHandler.hits <= RetryHandler.fail_first:
            body = b'{"error":{"message":"rate","type":"rate_limit_error"}}'
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        payload = self.responses[0]
        body = json.dumps({
            "id": "mock",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "finish_reason": "stop",
            }],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_litellm_retries(uri) -> None:
    print("\n[4] LiteLLM 步内重试（429），PGMQ 只消费一次")
    RetryHandler.hits = 0
    RetryHandler.fail_first = 2
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RetryHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    api_uri = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    c = conn(uri)
    try:
        raw = call_llm(
            [{"role": "user", "content": "hi"}],
            model="mock", api_uri=api_uri, api_key="none", num_retries=3,
        )
        check("call_llm 消化 429 后成功", "250" in raw, raw[:80])
        check("call_llm HTTP 命中=3", RetryHandler.hits == 3, RetryHandler.hits)
    finally:
        httpd.shutdown()

    # 新的 listener，避免上一轮 429 把 LiteLLM 客户端打坏
    RetryHandler.hits = 0
    RetryHandler.fail_first = 2
    httpd2 = ThreadingHTTPServer(("127.0.0.1", 0), RetryHandler)
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    api_uri2 = f"http://127.0.0.1:{httpd2.server_address[1]}/v1"
    try:
        run_id = start_run(c)
        w = AgentWorker(
            uri, api_uri=api_uri2, api_key="none", model="mock",
            sticky=True, poll=0.05, llm_retries=3, vt=5,
        )
        try:
            result = w.drain(run_id, timeout=20)
        finally:
            w.close()
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pgmq.a_llm_requests WHERE message->>'run_id'=%s",
                (run_id,),
            )
            archived = cur.fetchone()[0]
        check("worker 重试后 SUCCESS", st[0] == "SUCCESS" and result.get("ok"), (st, result))
        check("worker HTTP 命中>=3", RetryHandler.hits >= 3, RetryHandler.hits)
        check("PGMQ archive 1 条（不是每 429 一次）", archived == 1, archived)
    finally:
        httpd2.shutdown()
        c.close()


def test_dlq(uri) -> None:
    print("\n[5] read_ct 超限进死信，run 标 error")
    c = conn(uri)
    try:
        run_id = start_run(c)

        def boom(*args, **kwargs):
            raise RuntimeError("provider down")

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, vt=1, max_read_ct=2, llm_fn=boom,
        )
        try:
            result = w.drain(run_id, timeout=20)
        finally:
            w.close()
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests_dlq")
            dlq_n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            q_n = cur.fetchone()[0]
        check("DLQ 标记 dead_lettered", result.get("dead_lettered") is True, result)
        check("run ERROR", st[0] == "ERROR", st)
        check("死信队列有消息", dlq_n >= 1, dlq_n)
        check("主队列已清空该消息", q_n == 0, q_n)
    finally:
        c.close()


def test_session_pid_sql(uri) -> None:
    print("\n[2b] SQL 层：不同连接看不到对方 TEMP KV")
    a = conn(uri)
    b = conn(uri)
    try:
        with a.cursor() as cur:
            cur.execute("SELECT session_set('k','from-a')")
            cur.execute("SELECT session_get('k')")
            got_a = cur.fetchone()[0]
            cur.execute("SELECT session_backend_pid()")
            pid_a = cur.fetchone()[0]
        with b.cursor() as cur:
            cur.execute("SELECT session_get('k')")
            got_b = cur.fetchone()[0]
            cur.execute("SELECT session_backend_pid()")
            pid_b = cur.fetchone()[0]
        if isinstance(got_a, str):
            got_a = json.loads(got_a)
        if isinstance(got_b, str):
            got_b = json.loads(got_b)
        check("连接 A 读到自己写的值", got_a.get("value") == "from-a", got_a)
        check("连接 B 读不到 A 的 TEMP", got_b.get("value") is None, got_b)
        check("两条连接 pid 不同", pid_a != pid_b, (pid_a, pid_b))
    finally:
        a.close()
        b.close()


def main() -> int:
    print("[test_v3] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_happy(uri)
    test_session_pid_sql(uri)
    test_sticky(uri)
    test_vt_crash(uri)
    test_litellm_retries(uri)
    test_dlq(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
