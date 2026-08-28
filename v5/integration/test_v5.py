"""W7 integration: missing → visible store → retrieve → named tool → final; reuse."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent
V5_ROOT = ROOT.parent
AGENT_ROOT = V5_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v5.integration.setup_db import DB, main as setup_db
from v5.kernel_freeze.worker import AgentWorker

RESULTS: list[tuple[str, str, str]] = []
Q1 = "South 2025-02 revenue?"
Q2 = "North 2025-01 revenue?"
TASK_TEXT = "Integration-generated task: use named wb_* then answer."


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


def peek_mode(c) -> str | None:
    with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT message FROM pgmq.q_llm_requests ORDER BY msg_id LIMIT 1")
        row = cur.fetchone()
    msg = row["message"]
    if isinstance(msg, str):
        msg = json.loads(msg)
    return dict(msg).get("prompt_mode")


def test_full_flow(uri) -> None:
    print("\n[1] missing → store → named tool → final; second run reuses")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            seed(cur)
            purge(cur)
            cur.execute(
                "DELETE FROM prompt_parts WHERE recipe_name='agent_system' "
                "AND recipe_version=2 AND slot_key='task'"
            )
            cur.execute("SELECT agent_start(%s, %s)", (Q1, 10))
            run_id = cur.fetchone()[0]
        check("first payload is bootstrap", peek_mode(c) == "generate_missing")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "store", "action": "wb_store_prompt_part",
                 "action_input": {"p_slot_key": "task", "p_value": TASK_TEXT},
                 "final_answer": None},
                {"thought": "view", "action": "wb_temp_view_create",
                 "action_input": {
                     "p_view": "south_rev",
                     "p_select_sql": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
                 },
                 "final_answer": None},
                {"thought": "query", "action": "wb_brief_query",
                 "action_input": {"p_view": "south_rev", "p_limit": 5},
                 "final_answer": None},
                {"thought": "done", "action": None, "final_answer": "250"},
            ]),
        )
        result = w.drain(run_id, timeout=40)
        with c.cursor() as cur:
            cur.execute("SELECT status, answer FROM run_state(%s)", (run_id,))
            st = cur.fetchone()
        check("SUCCESS 250", st[0] == "SUCCESS" and st[1] == "250" and result.get("ok"), st)
        w.close()

        with c.cursor() as cur:
            purge(cur)
            cur.execute("SELECT agent_start(%s, %s)", (Q2, 6))
            run2 = cur.fetchone()[0]
        check("reuse skips bootstrap", peek_mode(c) is None)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "sql", "action": "execute_sql",
                 "action_input": "SELECT revenue FROM demo_sales WHERE segment='North' AND month='2025-01'",
                 "final_answer": None},
                {"thought": "done", "action": None, "final_answer": "100"},
            ]),
        )
        w.drain(run2, timeout=30)
        with c.cursor() as cur:
            cur.execute("SELECT status, answer FROM run_state(%s)", (run2,))
            st2 = cur.fetchone()
            cur.execute(
                "SELECT value #>> '{}' FROM prompt_parts "
                "WHERE recipe_name='agent_system' AND recipe_version=2 AND slot_key='task'"
            )
            task = cur.fetchone()[0]
        check("second run SUCCESS", st2[0] == "SUCCESS" and st2[1] == "100", st2)
        check("task globally reused", task == TASK_TEXT, task)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_immutability() -> None:
    print("\n[2] v1–v4 / pgembed 未被本树修改")
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", "v1", "v2", "v3", "v4"],
        cwd=str(AGENT_ROOT),
        capture_output=True,
        text=True,
    )
    staged = [ln for ln in r.stdout.splitlines() if ln[:2].strip() in {"A", "D"} or ln.startswith("M  ")]
    check("未 git add v1–v4", staged == [], r.stdout[:200])
    sqls = list(V5_ROOT.joinpath("kernel_freeze").glob("**/*.sql"))
    check("kernel_freeze 无 sql 拷贝", sqls == [])
    wsrc = (V5_ROOT / "kernel_freeze" / "worker.py").read_text()
    check("worker 无 import v4", not re.search(r"^\s*(from|import)\s+v4\b", wsrc, re.M))


def main() -> int:
    print("[test_v5] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_full_flow(uri)
    test_immutability()
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
