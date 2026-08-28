"""W4 prompt_pipeline gates: ordered messages; missing raises until W6."""
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
from v5.prompt_pipeline.setup_db import DB, main as setup_db

RESULTS: list[tuple[str, str, str]] = []
QUESTION = "demo_sales 表里 South 在 2025-02 的 revenue 是多少？只给数字。"


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


def test_source() -> None:
    print("\n[1] overlay 不再拼接 make_system_prompt")
    sql = (ROOT / "prompt_pipeline.sql").read_text()
    check("无 make_system_prompt", "make_system_prompt" not in sql)
    check("无直接 render_plugin_tools", "render_plugin_tools" not in sql)
    check("有 assemble_prompt_messages", "assemble_prompt_messages" in sql)


def test_order_and_missing(uri) -> None:
    print("\n[2] message order + missing status")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            seed(cur)
            purge(cur)
            cur.execute("SELECT agent_start(%s, %s)", (QUESTION, 5))
            run_id = cur.fetchone()[0]
            cur.execute(
                "SELECT prompt_recipe_version FROM agent_runs WHERE run_id=%s", (run_id,)
            )
            check("pins version 1", cur.fetchone()[0] == 1)
            cur.execute("SELECT assemble_prompt_messages(%s)", (run_id,))
            asm = as_json(cur.fetchone()[0])
            check("status ready", asm.get("status") == "ready", asm.get("status"))
            roles = [m["role"] for m in asm["messages"]]
            # role, task, example user, example assistant, output, tools, question
            check("roles start system,system,user,assistant,system,system,user",
                  roles[:7] == ["system", "system", "user", "assistant", "system", "system", "user"],
                  roles)
            check("last is question", asm["messages"][-1]["content"] == QUESTION, asm["messages"][-1])
            cur.execute("SELECT prepare_llm_request(%s)", (run_id,))
            prep = as_json(cur.fetchone()[0])
            check("prepare request_type llm", prep.get("request_type") == "llm", prep)
            check("prepare has recipe", prep.get("prompt_recipe", {}).get("version") == 1, prep)

            cur.execute(
                "CREATE TEMP TABLE saved_task_part AS "
                "SELECT * FROM prompt_parts WHERE recipe_name='agent_system' "
                "AND recipe_version=1 AND slot_key='task'"
            )
            cur.execute(
                "DELETE FROM prompt_parts WHERE recipe_name='agent_system' "
                "AND recipe_version=1 AND slot_key='task'"
            )
            cur.execute("SELECT assemble_prompt_messages(%s)", (run_id,))
            miss = as_json(cur.fetchone()[0])
            check("assemble missing", miss.get("status") == "missing", miss)
            check("missing slot task",
                  any(x.get("slot_key") == "task" for x in miss.get("missing") or []),
                  miss.get("missing"))
            try:
                cur.execute("SELECT prepare_llm_request(%s)", (run_id,))
                check("W4 missing raises", False, cur.fetchone())
            except Exception as exc:
                check("W4 missing raises", "PROMPT_ASSEMBLY_ERROR" in str(exc), exc)
            cur.execute("INSERT INTO prompt_parts SELECT * FROM saved_task_part")
            cur.execute("DROP TABLE saved_task_part")
    finally:
        c.close()


def test_scripted_run(uri) -> None:
    print("\n[3] scripted execute_sql 仍 SUCCESS")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            seed(cur)
            purge(cur)
            # restore task if previous test deleted it in a new run's recipe (global)
            cur.execute(
                "SELECT count(*) FROM prompt_parts WHERE recipe_name='agent_system' "
                "AND recipe_version=1 AND slot_key='task'"
            )
            if cur.fetchone()[0] == 0:
                check("task part still present for run", False, "deleted by missing test")
                return
            cur.execute("SELECT agent_start(%s, %s)", (QUESTION, 5))
            run_id = cur.fetchone()[0]
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "查表", "action": "execute_sql",
                 "action_input": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
                 "final_answer": None},
                {"thought": "有了", "action": None, "action_input": None, "final_answer": "250"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        with c.cursor() as cur:
            cur.execute("SELECT status, steps_used, answer FROM run_state(%s)", (run_id,))
            st = cur.fetchone()
        check("SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("answer 250", st[2] == "250", st[2])
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_prompt_pipeline] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_source()
    test_order_and_missing(uri)
    test_scripted_run(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
