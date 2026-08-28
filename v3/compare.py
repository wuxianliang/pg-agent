"""对比 HTTP 同步循环 vs PGMQ+库外 worker 的占用与结果。

默认用本地慢速 mock LLM（每步 sleep 3s），量化 backend 是否在等网。
加 --live 则打真实 DeepSeek（需 DEEPSEEK_API_KEY）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))
from server import get_server
from setup_db import DB, main as setup_db
from worker import AgentWorker

QUESTION = "demo_sales 表里 South 在 2025-02 的 revenue 是多少？只给数字。"
MOCK_SLEEP = 3.0
MOCK_RESPONSES = [
    {
        "thought": "先查表",
        "action": "execute_sql",
        "action_input": "SELECT month, segment, revenue FROM demo_sales WHERE segment = 'South' AND month = '2025-02'",
        "final_answer": None,
    },
    {
        "thought": "已经有数",
        "action": None,
        "action_input": None,
        "final_answer": "250",
    },
]


class Occupancy:
    def __init__(self):
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def add(self, rows, label: str):
        now = time.time()
        with self._lock:
            for row in rows:
                item = dict(row)
                item["t"] = now
                item["label"] = label
                if item.get("query_age") is not None:
                    item["query_age"] = float(item["query_age"])
                self.samples.append(item)

    def stop(self):
        self._stop.set()

    def snapshot(self, label: str) -> list[dict]:
        with self._lock:
            return [s for s in self.samples if s["label"] == label]


def seed(cur):
    cur.execute("DROP TABLE IF EXISTS demo_sales")
    cur.execute("""
        CREATE TABLE demo_sales (
            month   text NOT NULL,
            segment text NOT NULL,
            revenue int  NOT NULL
        )
    """)
    cur.execute("""
        INSERT INTO demo_sales (month, segment, revenue) VALUES
            ('2025-01', 'North', 100),
            ('2025-01', 'South', 200),
            ('2025-02', 'North', 150),
            ('2025-02', 'South', 250)
    """)


def set_gucs(cur, api_uri, api_key, model):
    cur.execute("SELECT set_config('openai.api_uri', %s, false)", (api_uri,))
    cur.execute("SELECT set_config('openai.api_key', %s, false)", (api_key or "none",))
    cur.execute("SELECT set_config('openai.model', %s, false)", (model,))
    cur.execute("SET statement_timeout = '300s'")


def sampler_loop(uri: str, occ: Occupancy, label_holder: list[str], interval: float = 0.05):
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    sql = """
        SELECT pid, state, wait_event_type, wait_event,
               EXTRACT(EPOCH FROM (now() - query_start)) AS query_age,
               left(query, 120) AS query
          FROM pg_stat_activity
         WHERE datname = current_database()
           AND pid <> pg_backend_pid()
           AND state IS DISTINCT FROM 'idle'
           AND query NOT LIKE '%pg_stat_activity%'
    """
    try:
        while not occ._stop.is_set():
            label = label_holder[0]
            if label:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql)
                    rows = cur.fetchall()
                occ.add(rows, label)
            time.sleep(interval)
    finally:
        conn.close()


class MockLLM(BaseHTTPRequestHandler):
    lock = threading.Lock()
    seq = 0
    sleep = MOCK_SLEEP
    responses = MOCK_RESPONSES

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length)
        time.sleep(self.sleep)
        with self.lock:
            i = min(self.seq, len(self.responses) - 1)
            payload = self.responses[i]
            MockLLM.seq += 1
        body = json.dumps({
            "id": "mock",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                "finish_reason": "stop",
            }],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @classmethod
    def reset(cls):
        with cls.lock:
            cls.seq = 0


def start_mock(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), MockLLM)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, bound = httpd.server_address
    return httpd, f"http://{host}:{bound}/v1"


def summarize(samples: list[dict], needle: str) -> dict:
    matching = [s for s in samples if needle in (s.get("query") or "")]
    active = [s for s in matching if s.get("state") == "active"]
    ages = [s["query_age"] for s in active if s.get("query_age") is not None]
    wait_events = {}
    for s in matching:
        key = f"{s.get('wait_event_type')}/{s.get('wait_event')}"
        wait_events[key] = wait_events.get(key, 0) + 1
    return {
        "samples": len(samples),
        "matching": len(matching),
        "active": len(active),
        "max_query_age_s": round(max(ages), 2) if ages else 0.0,
        "wait_events": wait_events,
    }


def run_http(uri, api_uri, api_key, model, occ, label_holder) -> dict:
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    t0 = time.perf_counter()
    label_holder[0] = "http"
    try:
        with conn.cursor() as cur:
            set_gucs(cur, api_uri, api_key, model)
            seed(cur)
            cur.execute("SELECT agent_run(%s, 5)", (QUESTION,))
            answer = cur.fetchone()[0]
            cur.execute("""
                SELECT run_id FROM agent_runs
                 WHERE question = %s
                 ORDER BY created_at DESC LIMIT 1
            """, (QUESTION,))
            run_id = cur.fetchone()[0]
            cur.execute("SELECT * FROM run_state(%s)", (run_id,))
            state = cur.fetchone()
    finally:
        elapsed = time.perf_counter() - t0
        label_holder[0] = ""
        conn.close()
    return {
        "mode": "http",
        "elapsed_s": round(elapsed, 2),
        "answer": answer,
        "run_id": run_id,
        "status": state[0],
        "steps_used": state[1],
        "caller_blocked_s": round(elapsed, 2),
    }


def run_pgmq(uri, api_uri, api_key, model, occ, label_holder) -> dict:
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    t0 = time.perf_counter()
    start_elapsed = 0.0
    run_id = None
    label_holder[0] = "pgmq"
    try:
        with conn.cursor() as cur:
            set_gucs(cur, api_uri, api_key, model)
            seed(cur)
            t_start = time.perf_counter()
            cur.execute("SELECT agent_start(%s, 5)", (QUESTION,))
            run_id = cur.fetchone()[0]
            start_elapsed = time.perf_counter() - t_start

        worker = AgentWorker(
            uri,
            api_uri=api_uri,
            api_key=api_key,
            model=model,
            sticky=True,
            poll=0.05,
        )
        try:
            result = worker.drain(run_id, timeout=120)
        finally:
            worker.close()

        with conn.cursor() as cur:
            cur.execute("SELECT * FROM run_state(%s)", (run_id,))
            state = cur.fetchone()
        answer = (result or {}).get("answer") or (state[2] if state else None)
    finally:
        elapsed = time.perf_counter() - t0
        label_holder[0] = ""
        conn.close()
    return {
        "mode": "pgmq",
        "elapsed_s": round(elapsed, 2),
        "answer": answer,
        "run_id": run_id,
        "status": state[0] if state else None,
        "steps_used": state[1] if state else None,
        "caller_blocked_s": round(start_elapsed, 3),
    }


def print_report(http_res, pgmq_res, occ: Occupancy, mock_sleep: float):
    http_occ = summarize(occ.snapshot("http"), "agent_run")
    pgmq_start = summarize(occ.snapshot("pgmq"), "agent_start")
    pgmq_apply = summarize(occ.snapshot("pgmq"), "apply_llm_response")
    pgmq_any_sql = summarize(occ.snapshot("pgmq"), "")
    print("\n======== HTTP vs PGMQ ========")
    print(f"mock_sleep_per_step = {mock_sleep}s" if mock_sleep else "live LLM")
    print()
    print(f"{'':22} {'HTTP':>12} {'PGMQ':>12}")
    print(f"{'wall_time_s':22} {http_res['elapsed_s']:12} {pgmq_res['elapsed_s']:12}")
    print(f"{'caller_blocked_s':22} {http_res['caller_blocked_s']:12} {pgmq_res['caller_blocked_s']:12}")
    print(f"{'steps_used':22} {http_res['steps_used']:12} {pgmq_res['steps_used']:12}")
    print(f"{'status':22} {str(http_res['status']):>12} {str(pgmq_res['status']):>12}")
    print(f"{'answer':22} {str(http_res['answer'])[:12]:>12} {str(pgmq_res['answer'])[:12]:>12}")
    print()
    print("backend occupancy while labelled:")
    print(f"  HTTP  agent_run max active query_age = {http_occ['max_query_age_s']}s  "
          f"(active samples {http_occ['active']}/{http_occ['matching']})")
    print(f"         wait_events = {http_occ['wait_events']}")
    print(f"  PGMQ  agent_start max active query_age = {pgmq_start['max_query_age_s']}s")
    print(f"  PGMQ  apply_llm_response max active query_age = {pgmq_apply['max_query_age_s']}s")
    print()
    print("解释：")
    print("  HTTP：SELECT agent_run(...) 在整个 LLM 往返期间保持 active，"
          f"max query_age 应接近 {MOCK_SLEEP}*步数。")
    print("  PGMQ：agent_start 立即返回（caller_blocked 毫秒级）；"
          "等 LLM 时 backend 不应长时间 active，apply 只在落库瞬间忙碌。")
    print("  两边答案/步数应对齐（同一 prompt + 同一 mock/模型）。")
    print()
    print("HTTP run_id:", http_res["run_id"], "answer:", http_res["answer"])
    print("PGMQ run_id:", pgmq_res["run_id"], "answer:", pgmq_res["answer"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="打真实 DeepSeek，而不是慢速 mock")
    parser.add_argument("--sleep", type=float, default=MOCK_SLEEP)
    args = parser.parse_args()

    print("[compare] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc

    server = get_server()
    uri = server.get_uri(DB)

    httpd = None
    if args.live:
        api_uri = "https://api.deepseek.com/v1"
        api_key = os.environ.get("DEEPSEEK_API_KEY") or ""
        model = "deepseek-chat"
        mock_sleep = 0.0
        if not api_key:
            print("DEEPSEEK_API_KEY 未设置")
            return 1
    else:
        MockLLM.sleep = args.sleep
        MockLLM.reset()
        httpd, api_uri = start_mock()
        api_key = "none"
        model = "mock"
        mock_sleep = args.sleep
        print(f"[compare] mock LLM at {api_uri} sleep={mock_sleep}s")

    occ = Occupancy()
    label_holder = [""]
    t = threading.Thread(target=sampler_loop, args=(uri, occ, label_holder), daemon=True)
    t.start()
    time.sleep(0.2)

    try:
        print("[compare] HTTP agent_run...")
        if not args.live:
            MockLLM.reset()
        http_res = run_http(uri, api_uri, api_key, model, occ, label_holder)
        print(f"  -> {http_res['elapsed_s']}s  {http_res['status']}  {http_res['answer']}")

        print("[compare] PGMQ agent_start + in-process worker...")
        if not args.live:
            MockLLM.reset()
        pgmq_res = run_pgmq(uri, api_uri, api_key, model, occ, label_holder)
        print(f"  -> wall {pgmq_res['elapsed_s']}s  start {pgmq_res['caller_blocked_s']}s  "
              f"{pgmq_res['status']}  {pgmq_res['answer']}")
    finally:
        occ.stop()
        if httpd:
            httpd.shutdown()

    print_report(http_res, pgmq_res, occ, mock_sleep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
