"""W3 queue_kinds gates: embed, sql-heavy, human inbox wait/resume."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v4.plugin_taxonomy.worker import QUEUE, DLQ
from v4.queue_kinds.setup_db import DB, main as setup_db
from v4.queue_kinds.worker import POLL_QUEUES, AgentWorker

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, cond, detail: str = "") -> None:
    RESULTS.append((name, "pass" if cond else "fail", str(detail)[:240]))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  | {detail}" if detail != "" else ""))


def conn(uri: str):
    c = psycopg2.connect(uri)
    c.autocommit = True
    return c


def as_json(value):
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, memoryview):
        return json.loads(bytes(value))
    return value


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


def purge_all(cur) -> None:
    for q in (
        "llm_requests", "llm_requests_dlq",
        "embed_requests", "embed_requests_dlq",
        "sql_heavy_requests", "sql_heavy_requests_dlq",
        "human_inbox", "human_inbox_dlq",
    ):
        cur.execute("SELECT pgmq.purge_queue(%s)", (q,))


def scripted(script: list):
    state = {"n": 0}

    def fn(messages, **kwargs):
        i = min(state["n"], len(script) - 1)
        state["n"] += 1
        item = script[i]
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)

    fn.state = state  # type: ignore[attr-defined]
    return fn


def start_run(c, question: str, max_steps: int = 8) -> str:
    with c.cursor() as cur:
        seed(cur)
        purge_all(cur)
        cur.execute("SELECT agent_start(%s, %s)", (question, max_steps))
        return cur.fetchone()[0]


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def q_count(c, queue: str) -> int:
    with c.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM pgmq.q_{queue}")
        return cur.fetchone()[0]


def test_registry(uri) -> None:
    print("\n[1] queues + handlers; generic apply 无 kind 分支")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT queue_name, queue_kind FROM plugin_bindings "
                "WHERE binding_type='queue_handler' ORDER BY queue_kind"
            )
            handlers = cur.fetchall()
        kinds = {r[1] for r in handlers}
        names = {r[0] for r in handlers}
        check("四种 queue_handler", kinds == {"llm", "embed", "sql_heavy", "human_inbox"}, handlers)
        check(
            "三 extra queues + llm",
            names == {"llm_requests", "embed_requests", "sql_heavy_requests", "human_inbox"},
            names,
        )
        tax = (AGENT_ROOT / "v4" / "plugin_taxonomy" / "plugin_taxonomy.sql").read_text()
        body = re.search(
            r"CREATE OR REPLACE FUNCTION apply_queue_result\s*\(.*?\$\$\s*(.*?)\$\$;",
            tax, re.S,
        )
        check("apply_queue_result 源仍无 kind 分支",
              body is not None and not re.search(
                  r"IF\s+.*kind\s*=\s*'?(llm|embed|sql_heavy|human_inbox)", body.group(1), re.I))
        check("worker 不 poll human_inbox", "human_inbox" not in POLL_QUEUES, POLL_QUEUES)
        src = (ROOT / "worker.py").read_text()
        check("worker 走 apply_queue_result", "apply_queue_result" in src)
        check("worker 不直接 apply_llm_response", "apply_llm_response(" not in src)
        with c.cursor() as cur:
            try:
                cur.execute("SELECT http_call_llm('[]'::jsonb)")
                check("HTTP guard", False)
            except Exception as exc:
                check("HTTP guard", "v4 forbids SQL-side model HTTP" in str(exc), exc)
            cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
            check("pgvector 可用", cur.fetchone() is not None)
    finally:
        c.close()


def test_embed(uri) -> None:
    print("\n[2] injected embedding + wait/resume once")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "embed hello then finish")
        hits = {"n": 0}

        def embed_fn(text, **kwargs):
            hits["n"] += 1
            return [0.1, 0.2, 0.3]

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, embed_fn=embed_fn,
            llm_fn=scripted([
                {"thought": "embed", "action": "execute_sql",
                 "action_input": "SELECT wb_request_embedding('hello')",
                 "final_answer": None},
                {"thought": "done", "action": None, "action_input": None, "final_answer": "embedded"},
            ]),
        )
        # First pump: LLM -> wait, do not consume embed yet.
        first = w.pump_once()
        st = run_state(c, run_id)
        check("async 后 waiting", first and first.get("waiting") is True, first)
        check("run_state WAITING_QUEUE", st[0] == "WAITING_QUEUE", st)
        check("未立即再入队 LLM", q_count(c, "llm_requests") == 0, q_count(c, "llm_requests"))
        check("embed 队列有消息", q_count(c, "embed_requests") == 1, q_count(c, "embed_requests"))
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='wait'", (run_id,))
            waits = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='llm'", (run_id,))
            llms = cur.fetchone()[0]
        check("只 emit wait（尚未 resume）", waits == 1 and llms == 1, (waits, llms))

        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        check("embed resume SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("embed_fn 恰好一次", hits["n"] == 1, hits["n"])
        check("resume 后 llm 步=2", st[1] == 2, st[1])
        check("answer embedded", st[2] == "embedded", st[2])

        with c.cursor() as cur:
            cur.execute(
                "SELECT queue_name, msg_id FROM processed_queue_messages "
                "WHERE queue_name='embed_requests' LIMIT 1"
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='llm'", (run_id,)
            )
            before = cur.fetchone()[0]
            cur.execute(
                "SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                (row[0], row[1], run_id, json.dumps({"embedding": [9, 9]})),
            )
            replay = as_json(cur.fetchone()[0])
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='llm'", (run_id,)
            )
            after = cur.fetchone()[0]
        check("duplicate embed apply replayed", replay.get("replayed") is True, replay)
        check("duplicate embed 不新增 llm 步", after == before, after)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_sql_heavy(uri) -> None:
    print("\n[3] sql-heavy 独立连接、看不见 TEMP、timeout")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "sql heavy")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            embed_fn=lambda *a, **k: [0.0],
            llm_fn=scripted([
                {"thought": "temp", "action": "execute_sql",
                 "action_input": (
                     "SELECT wb_temp_view_create('hidden_v', "
                     "'SELECT revenue FROM demo_sales WHERE segment=''South'' AND month=''2025-02''')"
                 ),
                 "final_answer": None},
                {"thought": "heavy", "action": "execute_sql",
                 "action_input": "SELECT wb_request_sql_heavy('SELECT * FROM hidden_v', 20, 5000)",
                 "final_answer": None},
                {"thought": "done", "action": None, "action_input": None, "final_answer": "ok"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'observation' FROM agent_steps "
                "WHERE run_id=%s AND kind='tool' ORDER BY seq",
                (run_id,),
            )
            obs = [r[0] or "" for r in cur.fetchall()]
        check("sql-heavy run 最终 SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        hidden = any(
            "does not exist" in o or "不存在" in o or '"success": false' in o or '"success":false' in o
            for o in obs
        )
        check("独立连接读不到 sticky TEMP VIEW", hidden, obs[-1][:200] if obs else "")

        # timeout + structured error via direct worker processor
        heavy = w._run_sql_heavy(
            {"sql": "SELECT pg_sleep(2)", "max_rows": 1, "timeout_ms": 200, "request_id": "t"}
        )
        check("sql-heavy timeout", heavy.get("error") == "timeout" or heavy.get("success") is False, heavy)
        err = w._run_sql_heavy(
            {"sql": "SELECT no_such_col FROM demo_sales", "max_rows": 5, "timeout_ms": 5000}
        )
        check("sql-heavy structured SQL error", err.get("success") is False, err)

        # submit-time reject of pg_temp / session
        with c.cursor() as cur:
            cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_id,))
            cur.execute(
                "SELECT wb_request_sql_heavy('SELECT * FROM pg_temp.hidden_v')"
            )
            rejected = as_json(cur.fetchone()[0])
        check("提交期拒绝 pg_temp", rejected.get("success") is False, rejected)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_human(uri) -> None:
    print("\n[4] human wait / answer / conflict / resume once")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "ask a human")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            embed_fn=lambda *a, **k: [0.0],
            llm_fn=scripted([
                {"thought": "ask", "action": "execute_sql",
                 "action_input": "SELECT wb_request_human('what is south revenue?', 'ctx')",
                 "final_answer": None},
                {"thought": "use answer", "action": None, "action_input": None, "final_answer": "250"},
            ]),
        )
        first = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        check("human drain 停在 wait", first.get("waiting") is True, first)
        check("run_state WAITING_HUMAN", st[0] == "WAITING_HUMAN", st)
        check("worker 未消费 human_inbox", q_count(c, "human_inbox") == 1, q_count(c, "human_inbox"))

        with c.cursor() as cur:
            cur.execute("SELECT human_inbox_list()")
            listing = as_json(cur.fetchone()[0])
            reqs = listing.get("requests") or []
            check("human_inbox_list OPEN", listing.get("success") is True and len(reqs) == 1, listing)
            rid = reqs[0]["request_id"]
            cur.execute("SELECT human_answer(%s, %s, %s)", (rid, "250", "tester"))
            ans = as_json(cur.fetchone()[0])
            check("human_answer OPEN 成功", ans.get("success") is True, ans)
            cur.execute("SELECT human_answer(%s, %s, %s)", (rid, "again", "tester"))
            dup = as_json(cur.fetchone()[0])
            check("duplicate answer conflict", dup.get("conflict") is True, dup)
            cur.execute("SELECT human_answer(%s, %s)", ("missing-id", "x"))
            missing = as_json(cur.fetchone()[0])
            check("missing request conflict", missing.get("conflict") is True, missing)
            cur.execute("SELECT count(*) FROM pgmq.q_human_inbox")
            inbox_left = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM processed_queue_messages WHERE queue_name='human_inbox'"
            )
            processed = cur.fetchone()[0]
        check("answer 后 inbox archive", inbox_left == 0, inbox_left)
        check("processed_queue_messages 有 human apply", processed >= 1, processed)
        check("answer 后只入队一次 LLM", q_count(c, "llm_requests") == 1, q_count(c, "llm_requests"))

        result = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        check("human resume SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("human resume 不重复 final", st[1] == 2, st[1])
    finally:
        if w is not None:
            w.close()
        c.close()


def test_plain_defer_does_not_wait(uri) -> None:
    print("\n[5] 普通 SELECT defer=true 不能暂停 run")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "fake defer")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "fake", "action": "execute_sql",
                 "action_input": "SELECT jsonb_build_object('success', true, 'defer', true)",
                 "final_answer": None},
                {"thought": "done", "action": None, "action_input": None, "final_answer": "no-wait"},
            ]),
        )
        result = w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='wait'", (run_id,)
            )
            waits = cur.fetchone()[0]
        check("fake defer 不 emit wait", waits == 0, waits)
        check("fake defer 仍 SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_queue_kinds] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_registry(uri)
    test_embed(uri)
    test_sql_heavy(uri)
    test_human(uri)
    test_plain_defer_does_not_wait(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
