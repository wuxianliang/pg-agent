"""W5 session_durability gates: TEMP loss vs run_schema persistence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v4.queue_kinds.worker import AgentWorker
from v4.session_durability.setup_db import DB, main as setup_db

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


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def schema_name(run_id: str) -> str:
    return "agent_run_" + run_id.replace("-", "")


def test_temp_default_lost_on_close(uri) -> None:
    print("\n[1] TEMP default：sticky close 后 view/KV 消失")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            purge(cur)
            cur.execute("SELECT agent_start(%s, 5)", ("temp default",))
            run_id = cur.fetchone()[0]
            cur.execute("SELECT session_mode FROM agent_runs WHERE run_id=%s", (run_id,))
            mode = cur.fetchone()[0]
        check("agent_start 默认 temp", mode == "temp", mode)
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "kv", "action": "execute_sql",
                 "action_input": "SELECT session_set('k','temp-v')",
                 "final_answer": None},
                {"thought": "view", "action": "execute_sql",
                 "action_input": "SELECT wb_temp_view_create('tv', 'SELECT 1 AS n')",
                 "final_answer": None},
                {"thought": "done", "action": None, "action_input": None, "final_answer": "ok"},
            ]),
        )
        w.drain(run_id, timeout=20)
        wconn = w.conn_for(run_id)
        # drain already dropped conn on done; reconnecting is a new backend
        w.close()
        other = conn(uri)
        try:
            with other.cursor() as cur:
                cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_id,))
                cur.execute("SELECT session_get('k')")
                kv = as_json(cur.fetchone()[0])
                cur.execute("SELECT wb_temp_view_list()")
                listing = as_json(cur.fetchone()[0])
            check("新连接看不到 TEMP KV", kv.get("value") is None, kv)
            check("新连接看不到 TEMP VIEW", listing.get("views") == [], listing)
        finally:
            other.close()
    finally:
        if w is not None:
            w.close()
        c.close()


def test_run_schema_persists(uri) -> None:
    print("\n[2] run_schema：关连接后仍在，新 worker 可 resume")
    c = conn(uri)
    w1 = w2 = None
    try:
        with c.cursor() as cur:
            purge(cur)
            cur.execute("SELECT agent_start_session(%s, 6, %s)", ("durable", "run_schema"))
            run_id = cur.fetchone()[0]
            nsp = schema_name(run_id)
            cur.execute("SELECT session_mode FROM agent_runs WHERE run_id=%s", (run_id,))
            mode = cur.fetchone()[0]
            cur.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)", (nsp,))
            existed = cur.fetchone()[0]
        check("session_mode=run_schema", mode == "run_schema", mode)
        check("schema 在 start 事务内创建", existed is True, nsp)

        w1 = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "kv", "action": "execute_sql",
                 "action_input": "SELECT session_set('k','dur-v')",
                 "final_answer": None},
                {"thought": "view", "action": "execute_sql",
                 "action_input": "SELECT wb_temp_view_create('dv', 'SELECT 7 AS n')",
                 "final_answer": None},
                {"thought": "wait-ish", "action": None, "action_input": None, "final_answer": "parked"},
            ]),
        )
        w1.drain(run_id, timeout=20)
        w1.close()

        other = conn(uri)
        try:
            with other.cursor() as cur:
                cur.execute(f"SELECT v FROM {nsp}.agent_session_kv WHERE k='k'")
                kv = cur.fetchone()
                cur.execute(f"SELECT n FROM {nsp}.dv")
                row = cur.fetchone()
            check("关连接后 KV 仍在 schema", kv and kv[0] == "dur-v", kv)
            check("关连接后 VIEW 仍在 schema", row and row[0] == 7, row)
        finally:
            other.close()

        w2 = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([{"thought": "x", "action": None, "final_answer": "x"}]),
        )
        wconn = w2.conn_for(run_id)
        with wconn.cursor() as cur:
            cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_id,))
            cur.execute("SELECT session_get('k')")
            kv2 = as_json(cur.fetchone()[0])
            cur.execute("SELECT wb_brief_query('dv', 10)")
            brief = as_json(cur.fetchone()[0])
        check("新 worker 连接读到 KV", kv2.get("value") == "dur-v", kv2)
        check("新 worker 连接读到 VIEW", brief.get("success") is True and brief.get("row_count") == 1, brief)
    finally:
        if w1 is not None:
            w1.close()
        if w2 is not None:
            w2.close()
        c.close()


def test_isolation_and_cleanup(uri) -> None:
    print("\n[3] cross-run isolation + cleanup")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            purge(cur)
            cur.execute("SELECT agent_start_session(%s, 5, %s)", ("A", "run_schema"))
            run_a = cur.fetchone()[0]
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "v", "action": "execute_sql",
                 "action_input": "SELECT wb_temp_view_create('only_a', 'SELECT 1 AS n')",
                 "final_answer": None},
                {"thought": "d", "action": None, "action_input": None, "final_answer": "a"},
            ]),
        )
        # Process only run A by draining A; B's queued LLM stays
        w.drain(run_a, timeout=20)
        with c.cursor() as cur:
            cur.execute("SELECT agent_start_session(%s, 5, %s)", ("B", "run_schema"))
            run_b = cur.fetchone()[0]
            cur.execute("SELECT pgmq.purge_queue(%s)", ("llm_requests",))
        wconn = conn(uri)
        try:
            with wconn.cursor() as cur:
                cur.execute("SELECT set_config('pg_agent.current_run_id', %s, false)", (run_b,))
                cur.execute("SELECT wb_temp_view_list()")
                listing = as_json(cur.fetchone()[0])
                cur.execute("SELECT wb_brief_query('only_a')")
                brief = as_json(cur.fetchone()[0])
            check("run B 看不见 run A 的 view", listing.get("views") == [], listing)
            check("run B 不能 resolve A 的 only_a", brief.get("success") is False, brief)
        finally:
            wconn.close()

        with c.cursor() as cur:
            try:
                cur.execute("SELECT agent_start_session(%s, 3, %s)", ("bad", "nope"))
                check("invalid mode 拒绝", False)
            except Exception as exc:
                check("invalid mode 拒绝", "invalid session_mode" in str(exc), exc)
            cur.execute("SELECT cleanup_run_session(%s)", (run_b,))
            early = as_json(cur.fetchone()[0])
            check("非 terminal 不能 cleanup", early.get("success") is False, early)
            cur.execute("SELECT cleanup_run_session(%s)", (run_a,))
            cleaned = as_json(cur.fetchone()[0])
            check("terminal cleanup 删目标 schema", cleaned.get("success") is True and cleaned.get("cleaned") is True, cleaned)
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                (schema_name(run_a),),
            )
            gone = not cur.fetchone()[0]
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)",
                (schema_name(run_b),),
            )
            b_left = cur.fetchone()[0]
            check("A schema 已删", gone)
            check("B schema 未动", b_left is True)
            cur.execute("SELECT cleanup_run_session(%s)", (run_a,))
            again = as_json(cur.fetchone()[0])
            check("cleanup 幂等", again.get("success") is True, again)
    finally:
        if w is not None:
            w.close()
        c.close()


def test_child_inherits_mode(uri) -> None:
    print("\n[4] child 继承 session_mode 且不共享 schema")
    c = conn(uri)
    w = None
    try:
        with c.cursor() as cur:
            purge(cur)
            cur.execute("SELECT agent_start_session(%s, 6, %s)", ("parent-dur", "run_schema"))
            parent = cur.fetchone()[0]

        def routed(messages, **kwargs):
            user = messages[1]["content"] if len(messages) > 1 else ""
            if user.startswith("kid"):
                return json.dumps({"thought": "c", "action": None, "final_answer": "kid-ok"})
            # parent scripted via closure
            return parent_fn(messages, **kwargs)

        parent_fn = scripted([
            {"thought": "spawn", "action": "execute_sql",
             "action_input": "SELECT wb_spawn_agents('[\"kid-1\",\"kid-2\"]'::jsonb)",
             "final_answer": None},
            {"thought": "done", "action": None, "action_input": None, "final_answer": "p"},
        ])
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_fn=routed,
        )
        w.drain(parent, timeout=30)
        with c.cursor() as cur:
            cur.execute(
                "SELECT run_id, session_mode FROM agent_runs WHERE parent_run_id=%s ORDER BY run_name",
                (parent,),
            )
            kids = cur.fetchall()
        check("两个 child", len(kids) == 2, kids)
        check("child 继承 run_schema", all(k[1] == "run_schema" for k in kids), kids)
        schemas = {schema_name(k[0]) for k in kids} | {schema_name(parent)}
        check("parent/child schema 互不相同", len(schemas) == 3, schemas)
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_session_durability] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_temp_default_lost_on_close(uri)
    test_run_schema_persists(uri)
    test_isolation_and_cleanup(uri)
    test_child_inherits_mode(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
