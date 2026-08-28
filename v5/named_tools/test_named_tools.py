"""W5 named_tools gates: action=wb_* JSON args; execute_sql still works."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v5.kernel_freeze.worker import AgentWorker
from v5.named_tools.setup_db import DB, main as setup_db

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


def start_run(c, question: str, max_steps: int = 8) -> str:
    with c.cursor() as cur:
        seed(cur)
        purge(cur)
        cur.execute("SELECT agent_start(%s, %s)", (question, max_steps))
        return cur.fetchone()[0]


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def test_sticky_named(uri) -> None:
    print("\n[1] named wb_temp_view_create + wb_brief_query")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "south via named tools")
        with c.cursor() as cur:
            cur.execute(
                "SELECT prompt_recipe_version FROM agent_runs WHERE run_id=%s", (run_id,)
            )
            check("pins v2", cur.fetchone()[0] == 2)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "create view", "action": "wb_temp_view_create",
                 "action_input": {
                     "p_view": "south_rev",
                     "p_select_sql": "SELECT month, revenue FROM demo_sales WHERE segment='South'",
                 },
                 "final_answer": None},
                {"thought": "query view", "action": "wb_brief_query",
                 "action_input": {"p_view": "south_rev", "p_limit": 20},
                 "final_answer": None},
                {"thought": "done", "action": None, "final_answer": "250"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        check("SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("answer 250", st[2] == "250", st[2])
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'tool' FROM agent_steps WHERE run_id=%s AND kind='tool' ORDER BY seq",
                (run_id,),
            )
            tools = [r[0] for r in cur.fetchall()]
        check("named tool steps", tools[:2] == ["wb_temp_view_create", "wb_brief_query"], tools)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_unknown_and_bad_args(uri) -> None:
    print("\n[2] unknown name + bad args")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "bad tools")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "nope", "action": "wb_does_not_exist",
                 "action_input": {"p_x": 1}, "final_answer": None},
                {"thought": "bad", "action": "wb_brief_query",
                 "action_input": {"p_view": "south_rev", "p_limit": "nope"},
                 "final_answer": None},
                {"thought": "sql still works", "action": "execute_sql",
                 "action_input": "SELECT 1 AS n", "final_answer": None},
                {"thought": "done", "action": None, "final_answer": "ok"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        check("still SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'observation' FROM agent_steps "
                "WHERE run_id=%s AND kind='tool' ORDER BY seq",
                (run_id,),
            )
            obs = [as_json(r[0]) for r in cur.fetchall()]
        check("unknown action NAMED_TOOL_ERROR",
              obs[0].get("Type") == "NAMED_TOOL_ERROR" or "未知 action" in json.dumps(obs[0], ensure_ascii=False),
              obs[0])
        check("bad args NAMED_TOOL_ERROR", obs[1].get("Type") == "NAMED_TOOL_ERROR", obs[1])
        check("execute_sql still works", obs[2].get("success") is True, obs[2])
    finally:
        if w is not None:
            w.close()
        c.close()


def test_no_parse_overlay() -> None:
    print("\n[3] 只 overlay apply_llm_response")
    sql = (ROOT / "named_tools.sql").read_text()
    check("不 overlay parse_llm_output", "parse_llm_output" not in sql.split("apply_llm_response")[0]
          or "CREATE OR REPLACE FUNCTION parse_llm_output" not in sql)


def main() -> int:
    print("[test_named_tools] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_no_parse_overlay()
    test_sticky_named(uri)
    test_unknown_and_bad_args(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
