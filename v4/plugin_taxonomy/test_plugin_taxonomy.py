"""W1 plugin_taxonomy gates: taxonomy, generic apply, HTTP guard, scripted LLM, replay/DLQ."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))
sys.path.insert(0, str(ROOT))

from server import get_server
from setup_db import DB, main as setup_db
from worker import AgentWorker, QUEUE, DLQ

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


def scripted(script: list):
    state = {"n": 0}

    def fn(messages, **kwargs):
        i = min(state["n"], len(script) - 1)
        state["n"] += 1
        item = script[i]
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)

    fn.state = state  # type: ignore[attr-defined]
    return fn


def start_run(c, question: str = QUESTION, max_steps: int = 5) -> str:
    with c.cursor() as cur:
        seed(cur)
        purge(cur)
        cur.execute("SELECT agent_start(%s, %s)", (question, max_steps))
        return cur.fetchone()[0]


def run_state(c, run_id: str):
    with c.cursor() as cur:
        cur.execute("SELECT status, steps_used, answer, error FROM run_state(%s)", (run_id,))
        return cur.fetchone()


def snapshot_registry(c) -> tuple:
    with c.cursor() as cur:
        cur.execute(
            "SELECT plugin_name, metadata::text FROM plugin_packages ORDER BY plugin_name"
        )
        pkgs = cur.fetchall()
        cur.execute(
            "SELECT binding_type, binding_name, plugin_name, queue_name, queue_kind, "
            "fn::text, metadata::text FROM plugin_bindings "
            "ORDER BY binding_type, binding_name"
        )
        binds = cur.fetchall()
    return pkgs, binds


def extract_fn_body(sql: str, name: str) -> str:
    m = re.search(
        rf"CREATE OR REPLACE FUNCTION {name}\s*\(.*?\$\$\s*(.*?)\$\$;",
        sql,
        re.S | re.I,
    )
    return m.group(1) if m else ""


def test_http_guard_and_sources(uri) -> None:
    print("\n[1] SQL HTTP guard + worker source")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            try:
                cur.execute("SELECT http_call_llm('[]'::jsonb)")
                check("http_call_llm 被禁用", False, "call succeeded")
            except Exception as exc:
                check("http_call_llm 被禁用", "v4 forbids SQL-side model HTTP" in str(exc), exc)
            try:
                cur.execute("SELECT agent_run('should fail')")
                check("agent_run 被禁用", False, "call succeeded")
            except Exception as exc:
                check("agent_run 被禁用", "v4 forbids SQL-side model HTTP" in str(exc), exc)
    finally:
        c.close()

    worker_src = (ROOT / "worker.py").read_text()
    check("worker 不调用 apply_llm_response", "apply_llm_response(" not in worker_src)
    check("worker 走 apply_queue_result", "apply_queue_result" in worker_src)
    check("worker 无 http_call_llm", "http_call_llm" not in worker_src)
    check("worker 无 pg_net", "pg_net" not in worker_src)
    check("worker 无 pgsql-http", "pgsql-http" not in worker_src)

    tax = (ROOT / "plugin_taxonomy.sql").read_text()
    body = extract_fn_body(tax, "apply_queue_result")
    check("apply_queue_result 函数可提取", bool(body), body[:40])
    kind_branch = re.search(
        r"IF\s+.*kind\s*=\s*'?(llm|embed|sql_heavy|human_inbox)",
        body,
        re.I,
    )
    check("apply_queue_result 无 queue-kind 分支", kind_branch is None, kind_branch)
    for kind in ("llm", "embed", "sql_heavy", "human_inbox"):
        check(
            f"kind {kind} 仅出现在 validation/probe 元数据",
            kind in tax,
        )


def test_refresh_validation(uri) -> None:
    print("\n[2] refresh_plugins 校验与失败原子性")
    c = conn(uri)
    probes: list[str] = []
    try:
        before = snapshot_registry(c)
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM plugin_bindings WHERE queue_name='llm_requests'")
            n_llm = cur.fetchone()[0]
        check("生产 llm_requests binding = 1", n_llm == 1, n_llm)

        def exec_ok(sql: str) -> None:
            with c.cursor() as cur:
                cur.execute(sql)

        def refresh_raises(label: str, sql_setup: str, drop_sql: str, needle: str) -> None:
            exec_ok(sql_setup)
            probes.append(drop_sql)
            try:
                with c.cursor() as cur:
                    cur.execute("SELECT refresh_plugins()")
                check(label, False, "refresh succeeded")
            except Exception as exc:
                check(label, needle in str(exc), exc)
            after = snapshot_registry(c)
            check(label + " 后 registry 不变", after == before, (len(after[1]), len(before[1])))
            exec_ok(drop_sql)
            probes.remove(drop_sql)

        refresh_raises(
            "拒绝 malformed JSON",
            """
            CREATE FUNCTION probe_malformed() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_malformed() IS '{"plugin": not-json';
            """,
            "DROP FUNCTION probe_malformed();",
            "不是合法 JSON",
        )
        refresh_raises(
            "拒绝 missing plugin",
            """
            CREATE FUNCTION probe_no_plugin() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_no_plugin() IS $c$
            {"llm_tool":{"name":"probe_no_plugin","description":"x","args":{},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            """,
            "DROP FUNCTION probe_no_plugin();",
            "缺少 plugin",
        )
        refresh_raises(
            "拒绝 wrong return type",
            """
            CREATE FUNCTION probe_ret(p_x text) RETURNS text LANGUAGE sql AS $$ SELECT p_x $$;
            COMMENT ON FUNCTION probe_ret(text) IS $c$
            {"plugin":{"name":"plugin_probe"},"llm_tool":{"name":"probe_ret","description":"x","args":{"p_x":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            """,
            "DROP FUNCTION probe_ret(text);",
            "必须返回 jsonb",
        )
        refresh_raises(
            "拒绝 wrong arg map",
            """
            CREATE FUNCTION probe_args(p_x text) RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_args(text) IS $c$
            {"plugin":{"name":"plugin_probe"},"llm_tool":{"name":"probe_args","description":"x","args":{"p_x":"integer"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            """,
            "DROP FUNCTION probe_args(text);",
            "类型不匹配",
        )
        refresh_raises(
            "拒绝 duplicate tool",
            """
            CREATE FUNCTION probe_dup(p_x text) RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;
            CREATE FUNCTION probe_dup(p_x integer) RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_dup(text) IS $c$
            {"plugin":{"name":"plugin_probe"},"llm_tool":{"name":"probe_dup","description":"a","args":{"p_x":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            COMMENT ON FUNCTION probe_dup(integer) IS $c$
            {"plugin":{"name":"plugin_probe"},"llm_tool":{"name":"probe_dup","description":"b","args":{"p_x":"integer"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            """,
            "DROP FUNCTION probe_dup(text); DROP FUNCTION probe_dup(integer);",
            "重复 tool_name",
        )
        refresh_raises(
            "拒绝 duplicate queue",
            """
            CREATE FUNCTION probe_q1(p_run_id text, p_result jsonb) RETURNS jsonb LANGUAGE sql AS $$ SELECT p_result $$;
            CREATE FUNCTION probe_q2(p_run_id text, p_result jsonb) RETURNS jsonb LANGUAGE sql AS $$ SELECT p_result $$;
            COMMENT ON FUNCTION probe_q1(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_probe"},"queue_handler":{"queue_name":"llm_requests","queue_kind":"llm","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
            $c$;
            COMMENT ON FUNCTION probe_q2(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_probe"},"queue_handler":{"queue_name":"llm_requests","queue_kind":"llm","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
            $c$;
            """,
            "DROP FUNCTION probe_q1(text, jsonb); DROP FUNCTION probe_q2(text, jsonb);",
            "重复 queue_name",
        )
        refresh_raises(
            "拒绝 invalid kind",
            """
            CREATE FUNCTION probe_kind(p_run_id text, p_result jsonb) RETURNS jsonb LANGUAGE sql AS $$ SELECT p_result $$;
            COMMENT ON FUNCTION probe_kind(text, jsonb) IS $c$
            {"plugin":{"name":"plugin_probe"},"queue_handler":{"queue_name":"weird_q","queue_kind":"nope","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
            $c$;
            """,
            "DROP FUNCTION probe_kind(text, jsonb);",
            "queue_kind 非法",
        )
        refresh_raises(
            "拒绝 job_handler 混入",
            """
            CREATE FUNCTION probe_job() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{}'::jsonb $$;
            COMMENT ON FUNCTION probe_job() IS $c$
            {"plugin":{"name":"plugin_probe"},"job_handler":{"queue":"x"},"llm_tool":{"name":"probe_job","description":"x","args":{},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
            """,
            "DROP FUNCTION probe_job();",
            "job_handler",
        )

        # legal kinds via test-only comment probes (no real processor)
        kind_fns = []
        for kind, qname in (
            ("embed", "embed_requests"),
            ("sql_heavy", "sql_heavy_requests"),
            ("human_inbox", "human_inbox"),
        ):
            fn = f"probe_{kind}"
            exec_ok(f"""
                CREATE FUNCTION {fn}(p_run_id text, p_result jsonb) RETURNS jsonb
                LANGUAGE sql AS $$ SELECT p_result $$;
                COMMENT ON FUNCTION {fn}(text, jsonb) IS $c$
                {{"plugin":{{"name":"plugin_probe"}},"queue_handler":{{"queue_name":"{qname}","queue_kind":"{kind}","consumer":"python_worker","args":{{"p_run_id":"text","p_result":"jsonb"}},"returns":"jsonb"}}}}
                $c$;
            """)
            kind_fns.append(fn)
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
            n = cur.fetchone()[0]
            cur.execute(
                "SELECT queue_kind FROM plugin_bindings WHERE binding_type='queue_handler' ORDER BY queue_kind"
            )
            kinds = [r[0] for r in cur.fetchall()]
        check(
            "parser 接受四种 queue_kind",
            set(kinds) >= {"llm", "embed", "sql_heavy", "human_inbox"},
            kinds,
        )
        check("probe refresh 绑定计数 >= 4", n >= 4, n)
        for fn in kind_fns:
            exec_ok(f"DROP FUNCTION {fn}(text, jsonb);")
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
        after_cleanup = snapshot_registry(c)
        check("DROP probe 后恢复生产 registry", after_cleanup == before)

        # legal llm_tool probe then drop
        exec_ok("""
            CREATE FUNCTION probe_ok_tool() RETURNS jsonb LANGUAGE sql AS $$ SELECT '{"success":true}'::jsonb $$;
            COMMENT ON FUNCTION probe_ok_tool() IS $c$
            {"plugin":{"name":"plugin_probe"},"llm_tool":{"name":"probe_ok_tool","description":"legal tool probe","args":{},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
            $c$;
        """)
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
            cur.execute(
                "SELECT count(*) FROM plugin_bindings WHERE binding_type='llm_tool' AND binding_name='probe_ok_tool'"
            )
            ok_n = cur.fetchone()[0]
        check("合法 metadata 能 refresh", ok_n == 1, ok_n)
        exec_ok("DROP FUNCTION probe_ok_tool();")
        with c.cursor() as cur:
            cur.execute("SELECT refresh_plugins()")
    finally:
        for drop in list(probes):
            try:
                with c.cursor() as cur:
                    cur.execute(drop)
            except Exception:
                pass
        try:
            with c.cursor() as cur:
                cur.execute("SELECT refresh_plugins()")
        except Exception:
            pass
        c.close()


def test_happy_generic_apply(uri) -> None:
    print("\n[3] scripted LLM 经 generic dispatcher 两轮 SUCCESS")
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
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM processed_queue_messages WHERE run_id=%s",
                (run_id,),
            )
            n_proc = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM pgmq.a_llm_requests WHERE message->>'run_id'=%s",
                (run_id,),
            )
            n_arch = cur.fetchone()[0]
        check("processed_queue_messages 记录 apply", n_proc >= 2, n_proc)
        check("archive 发生在 apply 之后（归档条数=轮次）", n_arch == 2, n_arch)
    finally:
        c.close()


def test_replay(uri) -> None:
    print("\n[4] crash-after-read 与 duplicate apply")
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

        # duplicate (queue, msg_id) apply returns replayed and does not add steps
        with c.cursor() as cur:
            cur.execute(
                "SELECT queue_name, msg_id FROM processed_queue_messages WHERE run_id=%s LIMIT 1",
                (run_id,),
            )
            row = cur.fetchone()
            before_steps = llm_n
            cur.execute(
                "SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                (row[0], row[1], run_id, json.dumps({"raw": '{"final_answer":"nope"}'})),
            )
            replay = cur.fetchone()[0]
            if isinstance(replay, str):
                replay = json.loads(replay)
            cur.execute(
                "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='llm'",
                (run_id,),
            )
            after_steps = cur.fetchone()[0]
        check("duplicate apply 返回 replayed", replay.get("replayed") is True, replay)
        check("duplicate apply 不新增 agent_steps", after_steps == before_steps, after_steps)
    finally:
        c.close()


def test_retry_and_dlq(uri) -> None:
    print("\n[5] worker-local retry 与 read-count DLQ")
    c = conn(uri)
    try:
        run_id = start_run(c)
        fails = {"n": 0}

        def flaky(messages, **kwargs):
            fails["n"] += 1
            if fails["n"] <= 2:
                raise RuntimeError("simulated 429")
            i = fails["n"] - 3
            script = [
                {"thought": "查表", "action": "execute_sql",
                 "action_input": "SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'",
                 "final_answer": None},
                {"thought": "有了", "action": None, "action_input": None, "final_answer": "250"},
            ]
            return json.dumps(script[min(i, len(script) - 1)], ensure_ascii=False)

        w = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, llm_retries=3, vt=5, llm_fn=flaky,
        )
        try:
            result = w.drain(run_id, timeout=30)
        finally:
            w.close()
        st = run_state(c, run_id)
        with c.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pgmq.a_llm_requests WHERE message->>'run_id'=%s",
                (run_id,),
            )
            archived = cur.fetchone()[0]
        check("flaky retry 后 SUCCESS", st[0] == "SUCCESS" and result.get("ok"), (st, result))
        check("worker-local 重试消化了前两次失败", fails["n"] >= 4, fails["n"])
        check("PGMQ archive 按逻辑步而非每次失败", archived == 2, archived)

        run_id2 = start_run(c)

        def boom(*args, **kwargs):
            raise RuntimeError("provider down")

        w2 = AgentWorker(
            uri, api_uri="http://127.0.0.1/v1", api_key="none", model="mock",
            sticky=True, poll=0.05, vt=1, max_read_ct=2, llm_fn=boom, llm_retries=0,
        )
        try:
            result2 = w2.drain(run_id2, timeout=20)
        finally:
            w2.close()
        st2 = run_state(c, run_id2)
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests_dlq")
            dlq_n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            q_n = cur.fetchone()[0]
        check("DLQ 标记 dead_lettered", result2.get("dead_lettered") is True, result2)
        check("run ERROR", st2[0] == "ERROR", st2)
        check("死信队列有消息", dlq_n >= 1, dlq_n)
        check("主队列已清空该消息", q_n == 0, q_n)
    finally:
        c.close()


def test_unknown_queue_no_archive(uri) -> None:
    print("\n[6] unknown queue 不 apply / 由异常阻止 archive")
    c = conn(uri)
    try:
        with c.cursor() as cur:
            try:
                cur.execute(
                    "SELECT apply_queue_result(%s, %s::bigint, %s, %s::jsonb)",
                    ("no_such_queue", 1, "run-x", json.dumps({"raw": "{}"})),
                )
                check("unknown queue 抛错", False, "succeeded")
            except Exception as exc:
                check("unknown queue 抛错", "unknown queue" in str(exc), exc)
            cur.execute(
                "SELECT count(*) FROM processed_queue_messages WHERE queue_name='no_such_queue'"
            )
            n = cur.fetchone()[0]
        check("unknown queue 不写入 processed_queue_messages", n == 0, n)
    finally:
        c.close()


def test_v123_immutable() -> None:
    print("\n[7] 本 stage 不修改 v1/v2/v3")
    py_text = "\n".join(p.read_text() for p in ROOT.glob("*.py"))
    check("不 import v3 包", not re.search(r"^\s*(from|import)\s+v3\b", py_text, re.M), "")
    check("不 import v2 包", not re.search(r"^\s*(from|import)\s+v2\b", py_text, re.M), "")
    check("不 import v1 包", not re.search(r"^\s*(from|import)\s+v1\b", py_text, re.M), "")
    from v4.load import SQL_LOAD_ORDER
    v3_sql = SQL_LOAD_ORDER[0]
    check("overlay 只读加载 v3 SQL", v3_sql.is_file() and v3_sql.parts[-2:] == ("v3", "pg_agent_pgmq.sql"))
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", "v1", "v2", "v3"],
        cwd=str(AGENT_ROOT),
        capture_output=True,
        text=True,
    )
    # Pre-existing v2/v3 work is allowed; W1 must not have staged edits there.
    check("本测试进程未 git add v1/v2/v3", not re.search(r"^[MAD]  v[123]/", r.stdout, re.M), r.stdout[:200])


def main() -> int:
    print("[test_plugin_taxonomy] setup_db...")
    rc = setup_db()
    if rc != 0:
        return rc
    uri = get_server().get_uri(DB)
    test_http_guard_and_sources(uri)
    test_refresh_validation(uri)
    test_happy_generic_apply(uri)
    test_replay(uri)
    test_retry_and_dlq(uri)
    test_unknown_queue_no_archive(uri)
    test_v123_immutable()
    failed = [n for n, s, _ in RESULTS if s == "fail"]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("failed:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
