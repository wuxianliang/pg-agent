"""W6 generate_missing gates: visible bootstrap, global role/task reuse."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v5.generate_missing.setup_db import DB, main as setup_db
from v5.kernel_freeze.worker import AgentWorker

RESULTS: list[tuple[str, str, str]] = []
Q1 = "What is South revenue in 2025-02?"
Q2 = "A completely different question about North."
TASK_TEXT = "Generated task: query before answering; one SQL per round; named wb_* allowed."


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


def peek_payload(c) -> dict:
    with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT message FROM pgmq.q_llm_requests ORDER BY msg_id LIMIT 1")
        row = cur.fetchone()
    msg = row["message"]
    if isinstance(msg, str):
        msg = json.loads(msg)
    return dict(msg)


def test_bootstrap_and_reuse(uri) -> None:
    print("\n[1] visible bootstrap → store → reuse")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            seed(cur)
            purge(cur)
            cur.execute(
                "CREATE TEMP TABLE saved_task AS SELECT * FROM prompt_parts "
                "WHERE recipe_name='agent_system' AND recipe_version=2 AND slot_key='task'"
            )
            cur.execute(
                "DELETE FROM prompt_parts WHERE recipe_name='agent_system' "
                "AND recipe_version=2 AND slot_key='task'"
            )
            cur.execute("SELECT agent_start(%s, %s)", (Q1, 8))
            run_id = cur.fetchone()[0]
        payload = peek_payload(c)
        check("request_type llm", payload.get("request_type") == "llm", payload.get("request_type"))
        check("prompt_mode generate_missing", payload.get("prompt_mode") == "generate_missing", payload)
        blob = json.dumps(payload.get("messages"), ensure_ascii=False)
        check("question in bootstrap messages", Q1 in blob, blob[:200])
        check("wb_store mentioned", "wb_store_prompt_part" in blob, "")

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "store task", "action": "wb_store_prompt_part",
                 "action_input": {"p_slot_key": "task", "p_value": TASK_TEXT},
                 "final_answer": None},
                {"thought": "answer", "action": "execute_sql",
                 "action_input": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
                 "final_answer": None},
                {"thought": "done", "action": None, "final_answer": "250"},
            ]),
        )
        result = w.drain(run_id, timeout=40)
        with c.cursor() as cur:
            cur.execute("SELECT status, answer FROM run_state(%s)", (run_id,))
            st = cur.fetchone()
            cur.execute(
                "SELECT value #>> '{}', source FROM prompt_parts "
                "WHERE recipe_name='agent_system' AND recipe_version=2 AND slot_key='task'"
            )
            part = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind IN ('llm','tool')",
                (run_id,),
            )
            n_hist = cur.fetchone()[0]
        check("run SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("stored generated task", part and part[0] == TASK_TEXT and part[1] == "generated", part)
        check("bootstrap llm/tool remain", n_hist >= 4, n_hist)

        with c.cursor() as cur:
            purge(cur)
            cur.execute("SELECT agent_start(%s, %s)", (Q2, 5))
            run2 = cur.fetchone()[0]
        payload2 = peek_payload(c)
        check("second run skips bootstrap", payload2.get("prompt_mode") is None, payload2.get("prompt_mode"))
        msgs2 = payload2.get("messages") or []
        systems = [m["content"] for m in msgs2 if m["role"] == "system"]
        check("reuses generated task", TASK_TEXT in systems, systems[:2])
        check("new question only in question slot",
              msgs2[-1]["content"] == Q2, msgs2[-1] if msgs2 else None)

        w.close()
        # first-writer-wins replay
        with c.cursor() as cur:
            cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_id,))
            cur.execute(
                "SELECT wb_store_prompt_part(%s, %s::jsonb)",
                ("task", json.dumps(TASK_TEXT)),
            )
            replay = as_json(cur.fetchone()[0])
        check("second store replayed", replay.get("replayed") is True and replay.get("stored") is False, replay)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_premature_final(uri) -> None:
    print("\n[2] premature final_answer does not SUCCESS")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            seed(cur)
            purge(cur)
            cur.execute(
                "DELETE FROM prompt_parts WHERE recipe_name='agent_system' "
                "AND recipe_version=2 AND slot_key='role'"
            )
            cur.execute("SELECT agent_start(%s, %s)", ("need a role", 3))
            run_id = cur.fetchone()[0]
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, db=DB,
            llm_fn=scripted([
                {"thought": "skip", "action": None, "final_answer": "nope"},
                {"thought": "store", "action": "wb_store_prompt_part",
                 "action_input": {"p_slot_key": "role", "p_value": "A generated role text."},
                 "final_answer": None},
                {"thought": "done", "action": None, "final_answer": "ok"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        with c.cursor() as cur:
            cur.execute("SELECT status, answer, error FROM run_state(%s)", (run_id,))
            st = cur.fetchone()
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='final'", (run_id,)
            )
            n_final = cur.fetchone()[0]
        check("did not keep premature final", st[2] != "nope", st)
        check("eventually SUCCESS or stored", st[0] in ("SUCCESS", "ERROR") and n_final <= 1, (st, n_final))
        check("drain finished", result.get("done") is True, result)
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_generate_missing] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_bootstrap_and_reuse(uri)
    test_premature_final(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
