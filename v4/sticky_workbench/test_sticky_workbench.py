"""W2 sticky_workbench gates: six tools on the worker sticky connection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v4.plugin_taxonomy.worker import AgentWorker, QUEUE, DLQ
from v4.sticky_workbench.setup_db import DB, main as setup_db

RESULTS: list[tuple[str, str, str]] = []
TOOLS = [
    "wb_brief_query",
    "wb_temp_view_list",
    "wb_temp_view_columns",
    "wb_temp_view_create",
    "wb_temp_view_drop",
    "wb_sql_curate",
]


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


def purge(cur) -> None:
    cur.execute("SELECT pgmq.purge_queue(%s)", (QUEUE,))
    cur.execute("SELECT pgmq.purge_queue(%s)", (DLQ,))


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


def nested_from_obs(obs_text: str, fn: str):
    outer = json.loads(obs_text) if isinstance(obs_text, str) else obs_text
    if not outer.get("success"):
        return outer
    data = outer.get("data") or []
    if not data:
        return outer
    return data[0].get(fn) or data[0]


def test_registry_and_prompt(uri) -> None:
    print("\n[1] registry + render_plugin_tools")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT binding_name, metadata FROM plugin_bindings "
                "WHERE binding_type='llm_tool' ORDER BY binding_name"
            )
            rows = cur.fetchall()
            names = [r[0] for r in rows]
            metas = [as_json(r[1]) for r in rows]
        check("exactly six llm_tool bindings", names == sorted(TOOLS), names)
        check(
            "metadata 是 v4 plugin+llm_tool",
            all("plugin" in m and "llm_tool" in m and "workbench_plugin" not in m for m in metas),
            metas[0] if metas else None,
        )
        check(
            "session_scope=run_connection",
            all(m["llm_tool"].get("session_scope") == "run_connection" for m in metas),
        )
        with c.cursor() as cur:
            cur.execute("SELECT render_plugin_tools()")
            rendered = cur.fetchone()[0]
            cur.execute("SELECT agent_start(%s, 3)", ("ping",))
            run_id = cur.fetchone()[0]
            cur.execute("SELECT prepare_llm_request(%s)", (run_id,))
            payload = as_json(cur.fetchone()[0])
            cur.execute("SELECT pgmq.purge_queue(%s)", (QUEUE,))
        check("render 含 v3 action 协议", "action_input" in rendered and "thought" in rendered, rendered[:120])
        check("render 含嵌套 envelope", "外层" in rendered and "嵌套" in rendered, rendered[-180:])
        check("render 含 sticky run 作用域", "粘住" in rendered or "run_connection" in rendered)
        sys_msg = payload["messages"][0]["content"]
        check("prepare_llm_request 拼上了工具清单", "wb_brief_query" in sys_msg, sys_msg[-200:])
        with c.cursor() as cur:
            try:
                cur.execute("SELECT http_call_llm('[]'::jsonb)")
                check("HTTP guard 仍禁用", False)
            except Exception as exc:
                check("HTTP guard 仍禁用", "v4 forbids SQL-side model HTTP" in str(exc), exc)
            cur.execute(
                "SELECT proname, prosecdef FROM pg_proc "
                "WHERE proname = ANY(%s) AND pronamespace = 'public'::regnamespace",
                (TOOLS,),
            )
            defs = cur.fetchall()
        check("全部 workbench SECURITY INVOKER", defs and all(not r[1] for r in defs), defs)
        sql_text = "\n".join(p.read_text() for p in ROOT.glob("*.sql"))
        check("不经过 v2 worker()", "worker()" not in sql_text and "FROM jobs" not in sql_text)
    finally:
        c.close()


def test_scripted_sticky_run(uri) -> None:
    print("\n[2] scripted create view -> query view -> final on sticky conn")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "用 workbench 建 south_rev 再查出 revenue")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "建视图", "action": "execute_sql",
                 "action_input": (
                     "SELECT wb_temp_view_create('south_rev', "
                     "'SELECT revenue FROM demo_sales WHERE segment=''South'' AND month=''2025-02''')"
                 ),
                 "final_answer": None},
                {"thought": "查询视图", "action": "execute_sql",
                 "action_input": "SELECT wb_brief_query('south_rev', 20)",
                 "final_answer": None},
                {"thought": "交卷", "action": None, "action_input": None, "final_answer": "250"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        check("scripted SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        check("scripted answer 250", st[2] == "250", st[2])
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'observation' FROM agent_steps "
                "WHERE run_id=%s AND kind='tool' ORDER BY seq",
                (run_id,),
            )
            obs = [r[0] or "" for r in cur.fetchall()]
        created = any("south_rev" in o and "success" in o for o in obs)
        queried = any("250" in o for o in obs)
        check("observation 含建视图", created, obs[0][:180] if obs else "no obs")
        check("后续 turn 看见视图行", queried, obs[-1][:180] if obs else "no obs")
    finally:
        if w is not None:
            w.close()
        c.close()


def test_isolation(uri) -> None:
    print("\n[3] sticky isolation vs caller connection")
    caller = conn(uri)
    other = conn(uri)
    w = AgentWorker(
        uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock", sticky=True, poll=0.05,
        llm_fn=scripted([{"thought": "x", "action": None, "final_answer": "x"}]),
    )
    try:
        with caller.cursor() as cur:
            seed(cur)
            purge(cur)
            cur.execute("SELECT agent_start(%s, 4)", ("isolation",))
            run_id = cur.fetchone()[0]
            cur.execute("CREATE TEMP VIEW caller_only AS SELECT 1 AS x")
            cur.execute("SELECT wb_temp_view_list()")
            caller_list = as_json(cur.fetchone()[0])
        wconn = w.conn_for(run_id)
        with wconn.cursor() as cur:
            cur.execute(
                "SELECT wb_temp_view_create('worker_only', 'SELECT 2 AS y')"
            )
            created = as_json(cur.fetchone()[0])
            cur.execute("SELECT wb_temp_view_list()")
            worker_list = as_json(cur.fetchone()[0])
            cur.execute("SELECT session_set('k','sticky-wb')")
        with other.cursor() as cur:
            cur.execute("SELECT wb_temp_view_list()")
            other_list = as_json(cur.fetchone()[0])
            cur.execute("SELECT session_get('k')")
            other_kv = as_json(cur.fetchone()[0])
        caller_names = [v["view"] for v in caller_list.get("views") or []]
        worker_names = [v["view"] for v in worker_list.get("views") or []]
        other_names = [v["view"] for v in other_list.get("views") or []]
        check("worker 建视图 success", created.get("success") is True, created)
        check("caller 只看见 caller_only", caller_names == ["caller_only"], caller_names)
        check("worker 只看见 worker_only", worker_names == ["worker_only"], worker_names)
        check("第三者连接看不见两边 TEMP", other_names == [], other_names)
        check("第三者读不到 sticky KV", other_kv.get("value") is None, other_kv)
        with caller.cursor() as cur:
            cur.execute("DROP VIEW caller_only")
        with wconn.cursor() as cur:
            cur.execute("SELECT wb_temp_view_drop('worker_only')")
    finally:
        w.close()
        caller.close()
        other.close()


def test_validators(uri) -> None:
    print("\n[4] structured errors: identifier / relkind / SQL / drop")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            def call(sql):
                cur.execute(sql)
                return as_json(cur.fetchone()[0])

            cur.execute("DROP VIEW IF EXISTS perm_view")
            cur.execute("CREATE VIEW perm_view AS SELECT 1 AS x")
            perm = call("SELECT wb_brief_query('perm_view')")
            check("永久视图拒绝", perm.get("success") is False and perm.get("Type") == "WORKBENCH_ERROR", perm)

            cur.execute("CREATE TEMP TABLE not_a_view (x int)")
            tbl = call("SELECT wb_brief_query('not_a_view')")
            check("TEMP table 拒绝", tbl.get("success") is False, tbl)
            cur.execute("DROP TABLE not_a_view")

            bad_name = call("SELECT wb_temp_view_create('pg_temp.foo', 'SELECT 1 AS x')")
            check("dotted 名拒绝", bad_name.get("success") is False and bad_name.get("Phase") == "Validation", bad_name)
            quoted = call("SELECT wb_temp_view_create('\"Quoted\"', 'SELECT 1 AS x')")
            check("quoted 名拒绝", quoted.get("success") is False, quoted)
            empty = call("SELECT wb_temp_view_create('', 'SELECT 1 AS x')")
            check("empty 名拒绝", empty.get("success") is False, empty)

            semi = call("SELECT wb_temp_view_create('v_semi', 'SELECT 1 AS x; SELECT 2')")
            check("分号拒绝", semi.get("success") is False, semi)
            cmt = call("SELECT wb_temp_view_create('v_cmt', 'SELECT 1 AS x -- hi')")
            check("SQL 注释拒绝", cmt.get("success") is False, cmt)
            dml = call("SELECT wb_temp_view_create('v_dml', 'INSERT INTO demo_sales VALUES (''x'',''y'',1)')")
            check("DML 拒绝", dml.get("success") is False, dml)

            ok = call("SELECT wb_temp_view_create('v_repl', 'SELECT 1 AS a')")
            check("初次 create 成功", ok.get("success") is True, ok)
            bad_repl = call("SELECT wb_temp_view_create('v_repl', 'SELECT 2 AS b')")
            check("不兼容 replacement 拒绝", bad_repl.get("success") is False, bad_repl)
            still = call("SELECT wb_temp_view_columns('v_repl')")
            cols = [col["name"] for col in still.get("columns") or []]
            check("失败 replacement 保留原列", cols == ["a"], still)

            call("SELECT wb_temp_view_create('v_base', 'SELECT 1 AS x')")
            call("SELECT wb_temp_view_create('v_child', 'SELECT * FROM v_base')")
            dep = call("SELECT wb_temp_view_drop('v_base')")
            check("dependent drop 拒绝且无 CASCADE", dep.get("success") is False, dep)
            still_base = call("SELECT wb_temp_view_columns('v_base')")
            check("依赖 drop 失败后基视图仍在", still_base.get("success") is True, still_base)
            call("SELECT wb_temp_view_drop('v_child')")
            call("SELECT wb_temp_view_drop('v_base')")
            call("SELECT wb_temp_view_drop('v_repl')")
            cur.execute("DROP VIEW perm_view")
    finally:
        c.close()


def test_curate_and_kv_turns(uri) -> None:
    print("\n[5] curate + session KV across LLM turns")
    c = conn(uri)
    w = None
    try:
        run_id = start_run(c, "curate 一个视图并跨轮读 KV")
        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05,
            llm_fn=scripted([
                {"thought": "写 KV", "action": "execute_sql",
                 "action_input": "SELECT session_set('token','wb-ok')",
                 "final_answer": None},
                {"thought": "策展", "action": "execute_sql",
                 "action_input": (
                     "SELECT wb_sql_curate('curated', "
                     "'SELECT 1 AS n', 'note-one')"
                 ),
                 "final_answer": None},
                {"thought": "读 KV 和 list", "action": "execute_sql",
                 "action_input": "SELECT session_get('token') AS kv, (SELECT wb_temp_view_list()) AS views",
                 "final_answer": None},
                {"thought": "交卷", "action": None, "action_input": None, "final_answer": "wb-ok"},
            ]),
        )
        result = w.drain(run_id, timeout=30)
        st = run_state(c, run_id)
        check("curate run SUCCESS", st[0] == "SUCCESS" and result.get("ok"), st)
        with c.cursor() as cur:
            cur.execute(
                "SELECT payload->>'observation' FROM agent_steps "
                "WHERE run_id=%s AND kind='tool' ORDER BY seq",
                (run_id,),
            )
            obs = [r[0] or "" for r in cur.fetchall()]
        check("跨轮 KV 可见", any("wb-ok" in o for o in obs), obs[-1][:180] if obs else "")
        check("跨轮看见 curated 视图", any("curated" in o for o in obs), [o[:80] for o in obs])
    finally:
        if w is not None:
            w.close()
        c.close()


def main() -> int:
    print("[test_sticky_workbench] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_registry_and_prompt(uri)
    test_scripted_sticky_run(uri)
    test_isolation(uri)
    test_validators(uri)
    test_curate_and_kv_turns(uri)
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
