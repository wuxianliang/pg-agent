"""W4 subagent_fanout gates: concurrent children, parent wait, exactly-once wake."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v4.queue_kinds.worker import AgentWorker
from v4.subagent_fanout.setup_db import DB, main as setup_db

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
    cur.execute("CREATE TABLE demo_sales (month text, segment text, revenue int)")
    cur.execute("INSERT INTO demo_sales VALUES ('2025-02','South',250)")


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


def test_sql_no_nested_loop() -> None:
    print("\n[1] SQL 无 nested LLM loop")
    sql = (ROOT / "subagent_fanout.sql").read_text()
    check("无 http_call_llm", "http_call_llm" not in sql)
    check("无 WHILE 调 model", "WHILE" not in sql.upper() or "http_call_llm" not in sql)
    check("无 recursive spawn SQL loop", "rlm_spawn" not in sql and "codeact_spawn" not in sql)


def test_happy_and_replay(uri) -> None:
    print("\n[2] parent spawn two children, resume once, replay 不重复唤醒")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "spawn two")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "spawn", "action": "execute_sql",
                 "action_input": (
                     "SELECT wb_spawn_agents("
                     "'[\"child question A\",\"child question B\"]'::jsonb, "
                     "'[\"alpha\",\"beta\"]'::jsonb)"
                 ),
                 "final_answer": None},
                {"thought": "combine", "action": None, "action_input": None, "final_answer": "A+B"},
            ]),
        )

        def child_or_parent(messages, **kwargs):
            user = messages[1]["content"] if len(messages) > 1 else ""
            if "child question" in user:
                return json.dumps({
                    "thought": "child", "action": None, "final_answer": user[-1] + "-done",
                })
            return w.llm_fn.__wrapped__(messages, **kwargs) if False else None

        # Combined llm_fn: children final immediately; parent uses scripted.
        parent_fn = w.llm_fn

        def routed(messages, **kwargs):
            user = messages[1]["content"] if len(messages) > 1 else ""
            if user.startswith("child question"):
                return json.dumps({
                    "thought": "child", "action": None, "action_input": None,
                    "final_answer": user[-1] + "-done",
                })
            return parent_fn(messages, **kwargs)

        w.llm_fn = routed
        first = w.pump_once()
        st = run_state(c, run_id)
        check("parent waiting after spawn", first.get("waiting") is True, first)
        check("parent WAITING_QUEUE until children done", st[0] == "WAITING_QUEUE", st)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM agent_wait_members w "
                "JOIN agent_wait_groups g ON g.wait_id=w.wait_id WHERE g.parent_run_id=%s",
                (run_id,),
            )
            n_children = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            qn = cur.fetchone()[0]
        check("created two children", n_children == 2, n_children)
        check("two child llm messages", qn == 2, qn)

        result = w.drain(run_id, timeout=40)
        st = run_state(c, run_id)
        check("parent SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("parent answer A+B", st[2] == "A+B", st[2])
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'observation' FROM agent_steps "
                "WHERE run_id=%s AND kind='tool' ORDER BY seq",
                (run_id,),
            )
            obs = [r[0] or "" for r in cur.fetchall()]
            cur.execute(
                "SELECT resumed_at IS NOT NULL FROM agent_wait_groups WHERE parent_run_id=%s",
                (run_id,),
            )
            resumed = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM pgmq.a_llm_requests WHERE message->>'run_id'=%s",
                (run_id,),
            )
            parent_arch = cur.fetchone()[0]
        check("child results 按 seq 出现", "alpha" in "".join(obs) and "beta" in "".join(obs), obs[-1][:200] if obs else "")
        check("wait group resumed_at set", resumed is True)
        check("parent 只有两次 LLM archive（spawn+final）", parent_arch == 2, parent_arch)

        # replay child apply does not re-enqueue parent
        with c.cursor() as cur:
            cur.execute(
                "SELECT child_run_id FROM agent_wait_members m "
                "JOIN agent_wait_groups g ON g.wait_id=m.wait_id "
                "WHERE g.parent_run_id=%s ORDER BY seq LIMIT 1",
                (run_id,),
            )
            child_id = cur.fetchone()[0]
            cur.execute(
                "SELECT queue_name, msg_id FROM processed_queue_messages WHERE run_id=%s LIMIT 1",
                (child_id,),
            )
            row = cur.fetchone()
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            before_q = cur.fetchone()[0]
            cur.execute(
                "SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                (row[0], row[1], child_id, json.dumps({"raw": '{"final_answer":"nope"}'})),
            )
            replay = as_json(cur.fetchone()[0])
            cur.execute("SELECT maybe_resume_parent(%s)", (child_id,))
            again = as_json(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            after_q = cur.fetchone()[0]
        check("child duplicate apply replayed", replay.get("replayed") is True, replay)
        check("second maybe_resume 不 enqueue", after_q == before_q, (before_q, after_q, again))
        check("already_resumed", again.get("reason") in ("already_resumed",) or again.get("resumed") is False, again)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_concurrent_children(uri) -> None:
    print("\n[3] two workers 并发 child + barrier")
    c = conn(uri)
    parent_w = None
    workers = []
    try:
        run_id = start_run(c, "concurrent spawn")
        parent_fn = scripted([
            {"thought": "spawn", "action": "execute_sql",
             "action_input": "SELECT wb_spawn_agents('[\"child question A\",\"child question B\"]'::jsonb)",
             "final_answer": None},
            {"thought": "done", "action": None, "action_input": None, "final_answer": "both"},
        ])
        parent_w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_fn=parent_fn,
        )
        parent_w.pump_once()
        st = run_state(c, run_id)
        check("parent waiting before children", st[0] == "WAITING_QUEUE", st)

        barrier = threading.Barrier(2, timeout=15)
        seen = []
        lock = threading.Lock()

        def child_fn(messages, **kwargs):
            barrier.wait()
            user = messages[1]["content"] if len(messages) > 1 else ""
            with lock:
                seen.append(user)
            return json.dumps({
                "thought": "c", "action": None, "action_input": None,
                "final_answer": "ok:" + user[-1],
            })

        def run_worker():
            w = AgentWorker(
                uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
                sticky=True, poll=0.05, llm_fn=child_fn, vt=10,
            )
            workers.append(w)
            try:
                # Process until this worker handles one done child (or timeout)
                deadline = __import__("time").time() + 20
                while __import__("time").time() < deadline:
                    r = w.pump_once()
                    if r and r.get("done"):
                        return r
                    if r is None:
                        __import__("time").sleep(0.05)
            finally:
                pass

        t1 = threading.Thread(target=run_worker)
        t2 = threading.Thread(target=run_worker)
        t1.start(); t2.start()
        t1.join(25); t2.join(25)
        check("barrier 两边都跑过", len(seen) == 2, seen)
        check("children 问题不同", len(set(seen)) == 2, seen)

        result = parent_w.drain(run_id, timeout=20)
        st = run_state(c, run_id)
        check("parent 在 children 之后 SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        with c.cursor() as cur:
            cur.execute(
                "SELECT m.seq, (run_state(m.child_run_id)).status "
                "FROM agent_wait_members m JOIN agent_wait_groups g ON g.wait_id=m.wait_id "
                "WHERE g.parent_run_id=%s ORDER BY m.seq",
                (run_id,),
            )
            child_st = cur.fetchall()
        check("两个 child 都 terminal", child_st == [(1, "SUCCESS"), (2, "SUCCESS")], child_st)
    finally:
        if parent_w is not None:
            parent_w.close()
        for w in workers:
            w.close()
        c.close()


def test_limits(uri) -> None:
    print("\n[4] depth / count / malformed / duplicate name")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            seed(cur)
            cur.execute("SELECT agent_start(%s, 5)", ("limits",))
            run_id = cur.fetchone()[0]
            cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_id,))

            def call(sql):
                cur.execute(sql)
                return as_json(cur.fetchone()[0])

            too_many = call("SELECT wb_spawn_agents('[\"1\",\"2\",\"3\",\"4\",\"5\",\"6\",\"7\",\"8\",\"9\"]'::jsonb)")
            check("9 prompts 拒绝", too_many.get("success") is False, too_many)
            empty = call("SELECT wb_spawn_agents('[\"ok\",\"\"]'::jsonb)")
            check("empty prompt 拒绝", empty.get("success") is False, empty)
            bad = call("SELECT wb_spawn_agents('\"not-array\"'::jsonb)")
            check("malformed prompts 拒绝", bad.get("success") is False, bad)
            dup = call("SELECT wb_spawn_agents('[\"a\",\"b\"]'::jsonb, '[\"x\",\"x\"]'::jsonb)")
            check("duplicate name 拒绝", dup.get("success") is False, dup)

            cur.execute("UPDATE agent_runs SET depth=4 WHERE run_id=%s", (run_id,))
            deep = call("SELECT wb_spawn_agents('[\"a\"]'::jsonb)")
            check("depth cap 拒绝", deep.get("success") is False, deep)
            cur.execute("UPDATE agent_runs SET depth=0, max_steps=10 WHERE run_id=%s", (run_id,))
            ok = call("SELECT wb_spawn_agents('[\"only\"]'::jsonb)")
            check("合法 spawn success", ok.get("success") is True, ok)
            child_id = ok["children"][0]["child_run_id"]
            cur.execute("SELECT max_steps, depth FROM agent_runs WHERE run_id=%s", (child_id,))
            ms, depth = cur.fetchone()
            check("child max_steps cap 6", ms == 6, ms)
            check("child depth = parent+1", depth == 1, depth)
    finally:
        c.close()


def test_child_error_surfaces(uri) -> None:
    print("\n[5] child error 作为 parent data")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "spawn error child")
        parent_fn = scripted([
            {"thought": "spawn", "action": "execute_sql",
             "action_input": "SELECT wb_spawn_agents('[\"boom-child\"]'::jsonb)",
             "final_answer": None},
            {"thought": "saw error", "action": None, "action_input": None, "final_answer": "got-error"},
        ])

        def routed(messages, **kwargs):
            user = messages[1]["content"] if len(messages) > 1 else ""
            if user == "boom-child":
                return "this is not json"
            return parent_fn(messages, **kwargs)

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_fn=routed,
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'observation' FROM agent_steps "
                "WHERE run_id=%s AND kind='tool' ORDER BY seq DESC LIMIT 1",
                (run_id,),
            )
            last = cur.fetchone()[0] or ""
        check("parent 仍 SUCCESS（child error 当数据）", st[0] == "SUCCESS" and result.get("ok"), st)
        check("parent observation 含 child error/status", "ERROR" in last or "error" in last or "boom" in last, last[:200])
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_subagent_fanout] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_sql_no_nested_loop()
    test_happy_and_replay(uri)
    test_concurrent_children(uri)
    test_limits(uri)
    test_child_error_surfaces(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
