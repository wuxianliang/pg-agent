"""pg-agent v2 data_analysis 测试。

前置：uv run python v2/setup_db.py  （库 da_agent，不动 v1 的库）
本脚本再 CREATE OR REPLACE 加载 v2 七份 SQL（core + 三个 plugin），
然后 refresh_workbench_tools()（brief + list/columns/create/drop + curate
→ 最终 6 工具），再跑确定性检查、mock 的 rlm_loop 序列 + DeepSeek。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
from pgembed import POSTGRES_BIN_PATH

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server

ROOT = Path(__file__).parent
DB = "da_agent"
SQL_FILES = [
    ROOT / "pg_agent_functional.sql",
    ROOT / "pg_agent_rlm.sql",
    ROOT / "pg_agent_workbench_core.sql",
    ROOT / "pg_agent_data_analysis.sql",
    ROOT / "plugin_brief_query.sql",
    ROOT / "plugin_temp_views.sql",
    ROOT / "plugin_sql_curator.sql",
]

RESULTS: list[tuple[str, str, str]] = []

# W1d 探针：合法 workbench 元数据 / 加了 job_handler 的非法版本（美元引号，避免转义）
_PROBE_TOOL = {
    "workbench_plugin": "plugin_probe",
    "llm_tool": {
        "name": "_wb_probe",
        "description": "batch A registry probe",
        "args": {},
        "returns": "jsonb",
        "session_scope": "current_session",
        "capability": "read_only",
    },
}
_PROBE_COMMENT_VALID = (
    "COMMENT ON FUNCTION _wb_probe() IS $wb$"
    + json.dumps(_PROBE_TOOL, separators=(",", ":")) + "$wb$"
)
_PROBE_COMMENT_BAD = (
    "COMMENT ON FUNCTION _wb_probe() IS $wb$"
    + json.dumps({**_PROBE_TOOL, "job_handler": "x"}, separators=(",", ":")) + "$wb$"
)
_PROBE_COMMENT_OVERLOAD = (
    "COMMENT ON FUNCTION _wb_probe(integer) IS $wb$"
    + json.dumps({
        **_PROBE_TOOL,
        "llm_tool": {**_PROBE_TOOL["llm_tool"],
                     "description": "batch C duplicate-name probe",
                     "args": {"p_x": "integer"}},
    }, separators=(",", ":")) + "$wb$"
)


def check(name: str, cond, detail: str = ""):
    RESULTS.append((name, "pass" if cond else "fail", str(detail)[:240]))
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"  | {detail}" if detail else ""))


def skip(name: str, reason: str = ""):
    RESULTS.append((name, "skip", reason))
    print(f"  ○ {name}  | SKIP: {reason}")


def load_sql(server, database: str, path: Path):
    uri = server.get_uri(database)
    proc = subprocess.run(
        [str(POSTGRES_BIN_PATH / "psql"), uri, "-v", "ON_ERROR_STOP=1", "-q"],
        input=path.read_text().encode(),
        capture_output=True,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0:
        raise RuntimeError(f"load {path.name} failed ({proc.returncode}):\n{out}")
    errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
    if errors:
        raise RuntimeError("psql errors:\n" + "\n".join(errors))
    return out


def conn(server, db):
    c = psycopg2.connect(server.get_uri(db))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SET openai.api_uri = 'https://api.deepseek.com/v1'")
        cur.execute(f"SET openai.api_key = '{os.environ['DEEPSEEK_API_KEY']}'")
        cur.execute("SET openai.model   = 'deepseek-chat'")
        cur.execute("SET statement_timeout = '300s'")
        try:
            cur.execute("SELECT http_set_curlopt('CURLOPT_CONNECTTIMEOUT', '15')")
            cur.execute("SELECT http_set_curlopt('CURLOPT_TIMEOUT', '90')")
        except Exception:
            pass
    return c


def one(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()


def llm_one(cur, sql, params=None, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            return one(cur, sql, params)
        except psycopg2.Error as e:
            last = e
            print(f"    (网络/LLM 失败，第 {i + 1} 次重试: {str(e).splitlines()[0][:80]})")
            time.sleep(3)
    raise last


def all_rows(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def mock_load(cur, responses):
    """预载 mock 的 LLM JSON 响应队列（配合 _mock_llm_queue / stub http_call_llm）。"""
    cur.execute("TRUNCATE _mock_llm_queue")
    for resp in responses:
        cur.execute("INSERT INTO _mock_llm_queue (raw) VALUES (%s)",
                    (json.dumps(resp, ensure_ascii=False),))


def grounded_tool_step(cur, run_id, needle="da_sales_fixture"):
    """存在一步 code 提到 needle 且 observation 外层 success=true，且 data 内
    嵌套的插件对象没有 success=false——外层 true 包着嵌套 false 不算通过。"""
    for code, obs_text in all_rows(cur, """
            SELECT payload->>'code', payload->>'observation'
              FROM agent_steps WHERE run_id=%s AND kind='tool' ORDER BY seq
        """, (run_id,)):
        if needle.lower() not in (code or "").lower():
            continue
        try:
            obs = json.loads(obs_text or "")
        except (ValueError, TypeError):
            continue
        if obs.get("success") is not True:
            continue
        nested_bad = any(
            val.get("success") is False
            for row in (obs.get("data") or [])
            if isinstance(row, dict)
            for val in row.values() if isinstance(val, dict)
        )
        if not nested_bad:
            return True
    return False


def seed_fixture(cur):
    cur.execute("DROP TABLE IF EXISTS da_sales_fixture")
    cur.execute("""
        CREATE TABLE da_sales_fixture (
            month   text NOT NULL,
            segment text NOT NULL,
            revenue int  NOT NULL,
            units   int  NOT NULL
        )
    """)
    cur.execute("""
        INSERT INTO da_sales_fixture (month, segment, revenue, units) VALUES
            ('2025-01', 'North', 100, 10),
            ('2025-01', 'South', 200, 20),
            ('2025-02', 'North', 150, 12),
            ('2025-02', 'South', 250, 25)
    """)
    # 100+200+150+250 = 700


def test_data_analysis(c):
    cur = c.cursor()
    seed_fixture(cur)
    c2 = psycopg2.connect(c.dsn)   # 独立 backend：验证 TEMP VIEW 会话隔离
    c2.autocommit = True
    try:
        _test_data_analysis_body(cur, c2.cursor())
    finally:
        c2.close()
        cur.execute("DROP TABLE IF EXISTS da_sales_fixture")


def _test_data_analysis_body(cur, cur2):
    print(" F0 加载与签名")
    n = one(cur, """
        SELECT count(*) FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname='public' AND p.proname='agent_run_data_analysis'
    """)[0]
    check("F0a agent_run_data_analysis 存在", n >= 1, f"n={n}")
    args = one(cur, """
        SELECT pg_get_function_identity_arguments(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
         WHERE n.nspname='public' AND p.proname='agent_run_data_analysis'
         ORDER BY p.oid LIMIT 1
    """)[0]
    check("F0b 签名含 question/context/max_steps", "text" in args and "integer" in args, args)

    orig = one(cur, "SELECT make_rlm_prompt(0, 0, 50, false)")[0]
    da = one(cur, "SELECT make_da_prompt(50)")[0]
    check("F0c 未改 make_rlm_prompt（不含 da_list_tables）",
          "da_list_tables" not in orig, orig[:80].replace("\n", " "))
    check("F0d make_da_prompt 含 schema-first 与 information_schema",
          "information_schema" in da and "必须先成功查库" in da and "禁止 rlm_spawn" in da,
          da[:100].replace("\n", " "))

    print(" W workbench core（W1–W3：无 plugin_*.sql，期望 0 工具）")
    wcols = one(cur, """
        SELECT array_agg(column_name::text ORDER BY ordinal_position)
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='workbench_tools'
    """)[0]
    check("W1a workbench_tools 列齐全",
          wcols is not None
          and set(wcols) >= {"tool_name", "plugin_name", "fn", "metadata", "refreshed_at"},
          str(wcols))
    n_wb = one(cur, "SELECT count(*) FROM workbench_tools")[0]
    wrender = one(cur, "SELECT render_workbench_tools()")[0]
    wpos = [wrender.find(t) for t in
            ["wb_brief_query", "wb_temp_view_columns", "wb_temp_view_list",
             "wb_sql_curate", "wb_temp_view_create", "wb_temp_view_drop"]]
    check("W1b 注册表恰 6 工具（最终门闩）", n_wb == 6, f"n={n_wb}")
    check("W1c 渲染 6 工具齐全且 read_only 在前、顺序确定（curator 居 mutation 组首）",
          all(p >= 0 for p in wpos) and wpos == sorted(wpos)
          and "read_only" in wrender and "temp_view_mutation" in wrender,
          str(wpos))

    # 探针：合法注册 1 个工具 → 注释加 job_handler → refresh 失败且旧注册表保留 → 清理回 0
    wb_msg = ""
    try:
        cur.execute("""
            CREATE OR REPLACE FUNCTION _wb_probe() RETURNS jsonb
            LANGUAGE sql STABLE AS $probe$ SELECT '{}'::jsonb $probe$
        """)
        cur.execute(_PROBE_COMMENT_VALID)
        n_reg = one(cur, "SELECT refresh_workbench_tools()")[0]
        rendered = one(cur, "SELECT render_workbench_tools()")[0]
        cur.execute(_PROBE_COMMENT_BAD)
        raised = False
        try:
            one(cur, "SELECT refresh_workbench_tools()")
        except psycopg2.Error as e:
            raised = True
            wb_msg = str(e).splitlines()[0][:120]
        n_keep = one(cur, "SELECT count(*) FROM workbench_tools")[0]
        check("W1d 探针=6+1 且渲染；job_handler 互斥拒绝且失败回滚（表保留 7 行）",
              n_reg == 7 and "_wb_probe" in rendered and "read_only" in rendered
              and raised and "job_handler" in wb_msg and n_keep == 7,
              f"n_reg={n_reg} raised={raised} keep={n_keep} err={wb_msg}")
    finally:
        cur.execute("DROP FUNCTION IF EXISTS _wb_probe()")
    n_back = one(cur, "SELECT refresh_workbench_tools()")[0]
    check("W1e 清理后 refresh=6", n_back == 6, f"n={n_back}")

    # W1f 队列注册表隔离：refresh_handlers 后 wb_* 不入 handlers，队列插件仍在
    n_handlers = one(cur, "SELECT refresh_handlers()")[0]
    wb_leak = one(cur, r"""
        SELECT count(*) FROM handlers h
         WHERE EXISTS (SELECT 1 FROM pg_proc p
                        WHERE p.oid = h.fn::oid
                          AND (p.proname LIKE 'wb\_%' ESCAPE '\'
                               OR p.proname LIKE '\_wb\_%' ESCAPE '\'))
    """)[0]
    agent_run_in = one(cur, "SELECT count(*) FROM handlers WHERE job_type='agent_run'")[0]
    check("W1f refresh_handlers 后 handlers 无 wb_*（两注册表不相交），队列插件仍在",
          n_handlers >= 1 and wb_leak == 0 and agent_run_in == 1,
          f"handlers={n_handlers} wb_leak={wb_leak}")

    # W1g 畸形 JSON 探针：疑似 workbench 注释但非法 JSON → refresh 失败且回滚保留旧注册表。
    # 注意：{-开头的非法注释同样会炸 refresh_handlers() 与 SQL 重载——探针存续期间
    # 绝不触发 handler refresh / SQL reload（finally 里恢复，随后才再 refresh）。
    bad_msg = ""
    try:
        cur.execute("""
            CREATE OR REPLACE FUNCTION _wb_probe() RETURNS jsonb
            LANGUAGE sql STABLE AS $probe$ SELECT '{}'::jsonb $probe$
        """)
        cur.execute('COMMENT ON FUNCTION _wb_probe() IS $wb${"workbench_plugin":"plugin_probe"$wb$')
        raised = False
        try:
            one(cur, "SELECT refresh_workbench_tools()")
        except psycopg2.Error as e:
            raised = True
            bad_msg = str(e).splitlines()[0][:120]
        n_keep = one(cur, "SELECT count(*) FROM workbench_tools")[0]
        check("W1g 畸形 JSON COMMENT → refresh 失败且回滚保留旧注册表 6 行",
              raised and "不是合法 JSON" in bad_msg and n_keep == 6,
              f"raised={raised} keep={n_keep} err={bad_msg}")
    finally:
        cur.execute("DROP FUNCTION IF EXISTS _wb_probe()")
    n_back = one(cur, "SELECT refresh_workbench_tools()")[0]
    check("W1h 畸形探针清理后 refresh=6", n_back == 6, f"n={n_back}")

    # W1i 重名 tool_name（同名重载）→ refresh 失败，无 last-wins
    dup_msg = ""
    try:
        cur.execute("""
            CREATE OR REPLACE FUNCTION _wb_probe() RETURNS jsonb
            LANGUAGE sql STABLE AS $probe$ SELECT '{}'::jsonb $probe$
        """)
        cur.execute(_PROBE_COMMENT_VALID)
        cur.execute("""
            CREATE OR REPLACE FUNCTION _wb_probe(p_x integer) RETURNS jsonb
            LANGUAGE sql STABLE AS $probe$ SELECT '{}'::jsonb $probe$
        """)
        cur.execute(_PROBE_COMMENT_OVERLOAD)
        raised = False
        try:
            one(cur, "SELECT refresh_workbench_tools()")
        except psycopg2.Error as e:
            raised = True
            dup_msg = str(e).splitlines()[0][:120]
        n_keep = one(cur, "SELECT count(*) FROM workbench_tools")[0]
        check("W1i 同名重载（重复 llm_tool.name）→ refresh 失败且回滚保留 6 行",
              raised and "重复" in dup_msg and n_keep == 6,
              f"raised={raised} keep={n_keep} err={dup_msg}")
    finally:
        cur.execute("DROP FUNCTION IF EXISTS _wb_probe(integer)")
        cur.execute("DROP FUNCTION IF EXISTS _wb_probe()")
    n_back = one(cur, "SELECT refresh_workbench_tools()")[0]
    check("W1j 重名探针清理后 refresh=6", n_back == 6, f"n={n_back}")

    check("W2a make_da_prompt 不再广告 da_* 捷径",
          "da_list_tables" not in da and "da_sample" not in da,
          "已移除可选捷径行")
    wrun = one(cur, """
        INSERT INTO agent_runs (run_id, question, paradigm, depth, max_depth, name)
        VALUES (gen_random_uuid()::text, 'wb-probe', 'data_analysis', 0, 0, 'data_analysis')
        RETURNING run_id
    """)[0]
    sysw = one(cur, "SELECT da_system_prompt(%s)", (wrun,))[0]
    check("W2b da_system_prompt 附带 workbench 工具清单（6 工具）",
          "wb_brief_query" in sysw and "wb_temp_view_create" in sysw
          and "wb_sql_curate" in sysw
          and "information_schema" in sysw,
          sysw.replace("\n", " ")[-120:])
    prosrc = one(cur, """
        SELECT p.prosrc FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname='public' AND p.proname='rlm_loop'
         ORDER BY p.oid LIMIT 1
    """)[0]
    check("W2c rlm_loop DA 分支改调 da_system_prompt",
          "da_system_prompt" in prosrc and "make_da_prompt" not in prosrc,
          "DA 分支仅 da_system_prompt(p_run_id)")

    print(" W4 brief_query（宿主 TEMP VIEW 预览，只读）")
    # 宿主直接建 TEMP VIEW（不经插件），验证插件只读消费
    cur.execute("CREATE TEMP VIEW tv_sales AS SELECT month, segment, revenue FROM da_sales_fixture")
    cur.execute("CREATE TEMP VIEW tv_empty AS SELECT month FROM da_sales_fixture WHERE false")
    r = one(cur, "SELECT wb_brief_query('tv_sales')")[0]
    check("W4a 预览成功：列序/行数/无截断",
          r.get("success") is True and r.get("view") == "tv_sales"
          and [(c["ordinal"], c["name"], c["type"]) for c in r.get("columns", [])]
              == [(1, "month", "text"), (2, "segment", "text"), (3, "revenue", "integer")]
          and r.get("row_count") == 4 and r.get("truncated") is False
          and len(r.get("data", [])) == 4,
          json.dumps(r, ensure_ascii=False)[:180])
    r = one(cur, "SELECT wb_brief_query('tv_sales', NULL)")[0]
    check("W4b 显式 NULL p_limit → 默认 20",
          r.get("success") is True and r.get("row_count") == 4 and r.get("truncated") is False,
          f"row_count={r.get('row_count')}")
    r = one(cur, "SELECT wb_brief_query('tv_sales', 2)")[0]
    check("W4c limit=2：取 3 返 2，truncated=true",
          r.get("row_count") == 2 and r.get("truncated") is True and len(r.get("data", [])) == 2,
          json.dumps(r.get("data", []), ensure_ascii=False)[:120])
    r = one(cur, "SELECT wb_brief_query('tv_empty', 5)")[0]
    check("W4d 空视图：data=[] row_count=0 truncated=false",
          r.get("success") is True and r.get("data") == [] and r.get("row_count") == 0
          and r.get("truncated") is False,
          json.dumps(r, ensure_ascii=False)[:140])
    r1 = one(cur, "SELECT wb_brief_query('tv_sales', 1)")[0]
    r50 = one(cur, "SELECT wb_brief_query('tv_sales', 50)")[0]
    check("W4e p_limit 边界 1/50 合法",
          r1.get("success") is True and r1.get("row_count") == 1 and r1.get("truncated") is True
          and r50.get("success") is True and r50.get("row_count") == 4,
          "1 与 50 均通过")
    bads = []
    for expr in ("''", "'   '", "'pg.tv_sales'", "'\"tv_sales\"'", "repeat('a', 64)"):
        bads.append(one(cur, f"SELECT wb_brief_query({expr})")[0])
    check("W4f 非法名（空/空白/带点/引号/64 字符）→ Validation",
          all(b.get("success") is False and b.get("Type") == "WORKBENCH_ERROR"
              and b.get("Phase") == "Validation" and b.get("Problem") and b.get("Solution")
              for b in bads),
          json.dumps(bads[0], ensure_ascii=False)[:140])
    r = one(cur, "SELECT wb_brief_query('no_such_tv_view')")[0]
    check("W4g 缺视图 → Resolution",
          r.get("success") is False and r.get("Phase") == "Resolution",
          json.dumps(r, ensure_ascii=False)[:120])
    lims = []
    for lim in ("0", "51", "-3"):
        lims.append(one(cur, f"SELECT wb_brief_query('tv_sales', {lim})")[0])
    check("W4h p_limit 0/51/-3 → Validation",
          all(l.get("success") is False and l.get("Phase") == "Validation" for l in lims),
          "越界值均拒")

    print(" W5 temp_views 只读半边（list / columns / 会话隔离）")
    cur.execute("CREATE TEMP TABLE tt_wb_probe (x int)")
    cur.execute("CREATE VIEW pv_wb_probe AS SELECT 1 AS one")
    try:
        r = one(cur, "SELECT wb_temp_view_list()")[0]
        names = [v["view"] for v in r.get("views", [])]
        counts = {v["view"]: v["column_count"] for v in r.get("views", [])}
        notes = {v["view"]: v["note"] for v in r.get("views", [])}
        check("W5a list：仅本会话 TEMP VIEW，字母序，含列数与 note",
              r.get("success") is True and names == sorted(names)
              and {"tv_sales", "tv_empty"} <= set(names)
              and "tt_wb_probe" not in names and "pv_wb_probe" not in names
              and counts.get("tv_sales") == 3 and notes.get("tv_sales") is None,
              json.dumps(r, ensure_ascii=False)[:180])
        r = one(cur, "SELECT wb_temp_view_columns('tv_sales')")[0]
        check("W5b columns：有序列结构且不读行",
              r.get("success") is True
              and [(c["ordinal"], c["name"], c["type"]) for c in r.get("columns", [])]
                  == [(1, "month", "text"), (2, "segment", "text"), (3, "revenue", "integer")]
              and "data" not in r,
              json.dumps(r, ensure_ascii=False)[:160])
        rb1 = one(cur, "SELECT wb_brief_query('tt_wb_probe')")[0]
        rb2 = one(cur, "SELECT wb_brief_query('pv_wb_probe')")[0]
        rc1 = one(cur, "SELECT wb_temp_view_columns('bad.name')")[0]
        rc2 = one(cur, "SELECT wb_temp_view_columns('no_such_tv_view')")[0]
        check("W5c TEMP 表/永久视图不满足解析；columns 非法名/缺名 → Validation/Resolution",
              rb1.get("Phase") == "Resolution" and rb2.get("Phase") == "Resolution"
              and rc1.get("Phase") == "Validation" and rc2.get("Phase") == "Resolution",
              json.dumps([rb1.get("Phase"), rb2.get("Phase"), rc1.get("Phase"), rc2.get("Phase")]))
        # §7.3 会话隔离：B（独立连接/后端）看不到 A 的 TEMP VIEW，反之亦然
        rb = one(cur2, "SELECT wb_brief_query('tv_sales')")[0]
        lb = one(cur2, "SELECT wb_temp_view_list()")[0]
        cur2.execute("CREATE TEMP VIEW tv_only_b AS SELECT 1 AS x")
        rb2b = one(cur2, "SELECT wb_brief_query('tv_only_b')")[0]
        la = one(cur, "SELECT wb_temp_view_list()")[0]
        check("W5d 会话隔离：B 看不到 A 的视图；A 看不到 B 的；B 自建可见",
              rb.get("Phase") == "Resolution" and lb.get("views") == []
              and rb2b.get("success") is True
              and "tv_only_b" not in [v["view"] for v in la.get("views", [])],
              json.dumps([str(rb.get("Phase")), lb.get("views")], ensure_ascii=False)[:140])
    finally:
        cur.execute("DROP VIEW IF EXISTS public.pv_wb_probe")
        cur.execute("DROP TABLE IF EXISTS pg_temp.tt_wb_probe")

    print(" W6 temp_views 变更半边（create / drop / 校验器 / 外层守卫）")
    pub_before = one(cur, """
        SELECT array_agg(c.relname ORDER BY c.relname)
          FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='public' AND c.relkind IN ('r','v')
    """)[0]
    try:
        r = one(cur, "SELECT wb_temp_view_create('tv_sum', %s, true)",
                ("SELECT segment, sum(revenue) AS total FROM da_sales_fixture GROUP BY segment",))[0]
        in_temp = one(cur, """
            SELECT count(*) FROM pg_class
             WHERE pg_my_temp_schema() <> 0
               AND relnamespace = pg_my_temp_schema()
               AND relname = 'tv_sum' AND relkind = 'v'
        """)[0]
        in_pub = one(cur, "SELECT to_regclass('public.tv_sum') IS NULL")[0]
        check("W6a create SELECT 成功：只进 temp 命名空间",
              r.get("success") is True and r.get("replaced") is False and in_temp == 1 and in_pub
              and [(c["name"], c["type"]) for c in r.get("columns", [])]
                  == [("segment", "text"), ("total", "bigint")],
              json.dumps(r, ensure_ascii=False)[:160])
        r = one(cur, "SELECT wb_temp_view_create('tv_w', %s)",
                ("WITH t AS (SELECT 1 AS x) SELECT * FROM t",))[0]
        check("W6b create WITH 成功", r.get("success") is True, json.dumps(r, ensure_ascii=False)[:120])
        r = one(cur, "SELECT wb_temp_view_create('tv_sum', %s, true)",
                ("SELECT segment, sum(revenue) AS total FROM da_sales_fixture WHERE segment='North' GROUP BY segment",))[0]
        check("W6c 覆盖成功 replaced=true",
              r.get("success") is True and r.get("replaced") is True,
              json.dumps(r, ensure_ascii=False)[:120])
        r = one(cur, "SELECT wb_temp_view_create('tv_sum', %s, false)",
                ("SELECT segment, sum(revenue) AS total FROM da_sales_fixture GROUP BY segment",))[0]
        still = one(cur, "SELECT wb_brief_query('tv_sum')")[0]
        check("W6d p_replace=false 冲突 → Resolution 且视图未变",
              r.get("success") is False and r.get("Phase") == "Resolution"
              and still.get("row_count") == 1,
              json.dumps(r, ensure_ascii=False)[:140])
        rejects = [
            ("tv_bad", "SELECT 1 AS a; SELECT 2", "分号"),
            ("tv_bad", "SELECT 1 AS a -- c", "行注释"),
            ("tv_bad", "/* c */ SELECT 1 AS a", "块注释"),
            ("tv_bad", "DELETE FROM da_sales_fixture", "DML"),
            ("tv_bad", "WITH d AS (DELETE FROM da_sales_fixture RETURNING *) SELECT * FROM d", "DML CTE"),
            ("tv_bad", "SELECT 1 AS a INTO wb_leak_table", "SELECT INTO"),
            ("tv_bad", "SET work_mem TO '64MB'", "SET"),
            ("tv_bad", "EXPLAIN SELECT 1", "首 token"),
            ("bad.name", "SELECT 1 AS a", "非法名"),
            ("tv_bad", None, "NULL SQL"),
            ("tv_bad", "SELECT " + "1+" * 8000 + "1", "超长"),
        ]
        rej = []
        for vname, sql, _tag in rejects:
            rr = one(cur, "SELECT wb_temp_view_create(%s, %s)", (vname, sql))[0]
            rej.append(bool(rr.get("success") is False and rr.get("Type") == "WORKBENCH_ERROR"
                            and rr.get("Phase") == "Validation" and rr.get("Problem") and rr.get("Solution")))
        no_left = one(cur, "SELECT _wb_temp_view_oid('tv_bad') IS NULL")[0]
        no_leak = one(cur, "SELECT to_regclass('public.wb_leak_table') IS NULL")[0]
        check("W6e 校验器拒绝（分号/注释/DML/DML-CTE/INTO/SET/首token/非法名/NULL/超长）全 Validation",
              all(rej) and no_left and no_leak, f"{sum(1 for x in rej if x)}/{len(rej)} 通过拒")
        r = one(cur, "SELECT wb_temp_view_create('tv_bad2', 'SELECT no_col_zz FROM da_sales_fixture')")[0]
        check("W6f CREATE VIEW 定义错误 → Validation",
              r.get("success") is False and r.get("Phase") == "Validation"
              and "no_col_zz" in r.get("Problem", ""),
              json.dumps(r, ensure_ascii=False)[:140])
        r = one(cur, "SELECT wb_temp_view_create('tv_sum', %s, true)",
                ("SELECT month, sum(revenue) AS total FROM da_sales_fixture GROUP BY month",))[0]
        r_after = one(cur, "SELECT wb_temp_view_columns('tv_sum')")[0]
        check("W6g 不兼容替换 → Execution 且原视图保留",
              r.get("success") is False and r.get("Phase") == "Execution"
              and "cannot change" in r.get("Problem", "")
              and [c["name"] for c in r_after.get("columns", [])] == ["segment", "total"],
              json.dumps(r, ensure_ascii=False)[:140])
        cur.execute("CREATE TEMP TABLE tt_coll (x int)")
        r = one(cur, "SELECT wb_temp_view_create('tt_coll', 'SELECT 1 AS a')")[0]
        tt_alive = one(cur, """
            SELECT count(*) FROM pg_class
             WHERE pg_my_temp_schema() <> 0
               AND relnamespace = pg_my_temp_schema()
               AND relname = 'tt_coll' AND relkind = 'r'
        """)[0]
        check("W6h temp 表同名冲突 → Resolution 且表保留",
              r.get("success") is False and r.get("Phase") == "Resolution" and tt_alive == 1,
              json.dumps(r, ensure_ascii=False)[:140])
        r = one(cur, "SELECT wb_temp_view_drop('tv_w')")[0]
        r2 = one(cur, "SELECT wb_temp_view_drop('tv_w')")[0]
        check("W6i drop 成功；重复 drop → Resolution（非静默成功）",
              r.get("success") is True and r.get("dropped") is True
              and r2.get("success") is False and r2.get("Phase") == "Resolution",
              json.dumps(r2, ensure_ascii=False)[:120])
        one(cur, "SELECT wb_temp_view_create('tv_base', 'SELECT 1 AS a')")
        one(cur, "SELECT wb_temp_view_create('tv_dep', 'SELECT a FROM tv_base')")
        r = one(cur, "SELECT wb_temp_view_drop('tv_base')")[0]
        both_alive = one(cur, "SELECT _wb_temp_view_oid('tv_base') IS NOT NULL"
                             " AND _wb_temp_view_oid('tv_dep') IS NOT NULL")[0]
        check("W6j 受限 drop：依赖阻止 → Execution，两视图保留（无 CASCADE）",
              r.get("success") is False and r.get("Phase") == "Execution" and both_alive,
              json.dumps(r, ensure_ascii=False)[:140])
        rd1 = one(cur, "SELECT wb_temp_view_drop('bad.name')")[0]
        rd2 = one(cur, "SELECT wb_temp_view_drop('tv_never_exists')")[0]
        check("W6k drop 非法名 → Validation；缺视图 → Resolution",
              rd1.get("Phase") == "Validation" and rd2.get("Phase") == "Resolution", "")
        rid3 = one(cur, """
            INSERT INTO agent_runs (run_id, question, paradigm, depth, max_depth, name)
            VALUES (gen_random_uuid()::text, 'wb', 'data_analysis', 0, 0, 'data_analysis')
            RETURNING run_id
        """)[0]
        one(cur, "SELECT rlm_bind(%s)", (rid3,))
        r = one(cur, "SELECT rlm_eval(%s, %s)", (rid3, "CREATE TEMP VIEW evil_v AS SELECT 1"))[0]
        evil_free = one(cur, "SELECT _wb_temp_view_oid('evil_v') IS NULL")[0]
        check("W6l 外层仍拒绝原生 CREATE 且 evil_v 未创建",
              not r.get("success") and "create" in r.get("error", "") and evil_free,
              r.get("error", "")[:80])
        r = one(cur, "SELECT rlm_eval(%s, %s)",
                (rid3, "SELECT wb_temp_view_create('tv_via_eval', 'SELECT 1 AS a')"))[0]
        nested = (r.get("data") or [{}])[0].get("wb_temp_view_create", {})
        made = one(cur, "SELECT _wb_temp_view_oid('tv_via_eval') IS NOT NULL")[0]
        check("W6m 合法 wb_temp_view_create 经 rlm_eval 成功（外层+嵌套 success）",
              r.get("success") is True and nested.get("success") is True and made,
              json.dumps(nested, ensure_ascii=False)[:140])
        one(cur, "SELECT wb_temp_view_drop('tv_via_eval')")
        r = one(cur, "SELECT rlm_eval(%s, %s)",
                (rid3, "SELECT wb_temp_view_create('tv_fpos', 'SELECT 1 AS set')"))[0]
        fpos_free = one(cur, "SELECT _wb_temp_view_oid('tv_fpos') IS NULL")[0]
        check("W6n 外层黑名单对字面量独立词误报（文档化限制）：'set' 拒绝且插件未执行",
              not r.get("success") and "set" in r.get("error", "") and fpos_free,
              r.get("error", "")[:80])
        pub_after = one(cur, """
            SELECT array_agg(c.relname ORDER BY c.relname)
              FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname='public' AND c.relkind IN ('r','v')
        """)[0]
        check("W6o 全程无永久对象增减", pub_before == pub_after, str(pub_after)[:160])
    finally:
        for v in ("tv_sales", "tv_empty", "tv_sum", "tv_w", "tv_dep", "tv_base", "tv_via_eval"):
            cur.execute(f"DROP VIEW IF EXISTS pg_temp.{v}")
        cur.execute("DROP TABLE IF EXISTS pg_temp.tt_coll")

    print(" W7 sql_curator（curate / note / clear / 原子性 / 8000 上限）")
    sql_all = "SELECT segment, sum(revenue) AS total FROM da_sales_fixture GROUP BY segment"
    sql_north = ("SELECT segment, sum(revenue) AS total FROM da_sales_fixture "
                 "WHERE segment='North' GROUP BY segment")
    try:
        r = one(cur, "SELECT wb_sql_curate('cv_sum', %s, %s)", (sql_all, "按 segment 汇总收入"))[0]
        listed = one(cur, "SELECT wb_temp_view_list()")[0]
        notes = {v["view"]: v["note"] for v in listed.get("views", [])}
        check("W7a curate 成功：建视图+备注（replaced=false），list 的 note 可见",
              r.get("success") is True and r.get("view") == "cv_sum"
              and r.get("replaced") is False and r.get("note") == "按 segment 汇总收入"
              and [(c["name"], c["type"]) for c in r.get("columns", [])]
                  == [("segment", "text"), ("total", "bigint")]
              and notes.get("cv_sum") == "按 segment 汇总收入",
              json.dumps(r, ensure_ascii=False)[:170])
        r = one(cur, "SELECT wb_sql_curate('cv_sum', %s, %s)", (sql_north, "仅 North"))[0]
        listed = one(cur, "SELECT wb_temp_view_list()")[0]
        notes = {v["view"]: v["note"] for v in listed.get("views", [])}
        rows = one(cur, "SELECT wb_brief_query('cv_sum')")[0]
        check("W7b 重述：replaced=true、新定义生效（1 行）、备注更新",
              r.get("success") is True and r.get("replaced") is True and r.get("note") == "仅 North"
              and notes.get("cv_sum") == "仅 North" and rows.get("row_count") == 1,
              json.dumps(r, ensure_ascii=False)[:140])
        r = one(cur, "SELECT wb_sql_curate('cv_sum', %s)", (sql_all,))[0]
        listed = one(cur, "SELECT wb_temp_view_list()")[0]
        notes = {v["view"]: v["note"] for v in listed.get("views", [])}
        check("W7c 省略 p_note = 全量重述：替换视图并清除备注（无“保留旧备注”模式）",
              r.get("success") is True and r.get("replaced") is True and r.get("note") is None
              and notes.get("cv_sum") is None, json.dumps(r, ensure_ascii=False)[:140])
        one(cur, "SELECT wb_sql_curate('cv_sum', %s, %s)", (sql_all, "临时备注"))
        r = one(cur, "SELECT wb_sql_curate('cv_sum', %s, %s)", (sql_all, "   "))[0]
        listed = one(cur, "SELECT wb_temp_view_list()")[0]
        notes = {v["view"]: v["note"] for v in listed.get("views", [])}
        check("W7d 纯空白 p_note 同样清除备注",
              r.get("success") is True and r.get("note") is None
              and notes.get("cv_sum") is None, "")
        r = one(cur, "SELECT wb_sql_curate('cv_sum', %s, %s)", (sql_north, "x" * 1001))[0]
        listed = one(cur, "SELECT wb_temp_view_list()")[0]
        rows = one(cur, "SELECT wb_brief_query('cv_sum')")[0]
        check("W7e 备注 1001 字符 → 先拒后改（Validation；定义仍全量 2 行、备注仍空）",
              r.get("success") is False and r.get("Type") == "WORKBENCH_ERROR"
              and r.get("Phase") == "Validation" and rows.get("row_count") == 2
              and {v["view"]: v["note"] for v in listed.get("views", [])}.get("cv_sum") is None,
              json.dumps(r, ensure_ascii=False)[:140])
        r = one(cur, "SELECT wb_sql_curate('cv_sum', %s, %s)",
                ("DELETE FROM da_sales_fixture", "n"))[0]
        rows = one(cur, "SELECT wb_brief_query('cv_sum')")[0]
        check("W7f 非法 SQL：透传 wb_temp_view_create 的结构化错误，视图未动",
              r.get("success") is False and r.get("Phase") == "Validation"
              and "p_select_sql" in r.get("Problem", "") and rows.get("row_count") == 2,
              json.dumps(r, ensure_ascii=False)[:140])
        long_sql = "SELECT " + "1+" * 4000 + "1"    # 8008 字符（>8000 且 ≤16000）
        exact_sql = "SELECT " + "1+" * 3996 + "1"   # 恰 8000 字符
        r_over = one(cur, "SELECT wb_sql_curate('cv_len', %s, 'n')", (long_sql,))[0]
        r_exact = one(cur, "SELECT wb_sql_curate('cv_len', %s, 'n')", (exact_sql,))[0]
        r_plain = one(cur, "SELECT wb_temp_view_create('cv_len2', %s)", (long_sql,))[0]
        check("W7g 策展 8000 上限：>8000 拒（Validation），=8000 收；生命周期工具收同一段 8008 SQL",
              r_over.get("success") is False and r_over.get("Phase") == "Validation"
              and "8000" in r_over.get("Problem", "")
              and r_exact.get("success") is True and r_plain.get("success") is True,
              f"over={r_over.get('success')} exact={r_exact.get('success')} plain={r_plain.get('success')}")
        r = one(cur, "SELECT wb_sql_curate('bad.name', 'SELECT 1 AS a', 'n')")[0]
        check("W7h 非法视图名 → Validation（同一标识符策略）",
              r.get("success") is False and r.get("Phase") == "Validation", "")
        # W7i 原子性：event trigger 阻断 COMMENT → create 已成功的替换也一并回滚。
        # 触发器存续期间不触发 handler refresh / SQL reload，也不执行其他 COMMENT。
        one(cur, "SELECT wb_sql_curate('cv_atom', %s, 'orig')", (sql_north,))
        cur.execute("""
            CREATE OR REPLACE FUNCTION _wb_block_comment() RETURNS event_trigger
            LANGUAGE plpgsql AS $f$ BEGIN RAISE EXCEPTION 'comment blocked (W7i)'; END $f$
        """)
        cur.execute("CREATE EVENT TRIGGER _wb_block_comment ON ddl_command_start "
                    "WHEN tag IN ('COMMENT') EXECUTE FUNCTION _wb_block_comment()")
        try:
            r = one(cur, "SELECT wb_sql_curate('cv_atom', %s, 'new')", (sql_all,))[0]
            rows = one(cur, "SELECT wb_brief_query('cv_atom')")[0]
            listed = one(cur, "SELECT wb_temp_view_list()")[0]
            notes = {v["view"]: v["note"] for v in listed.get("views", [])}
            check("W7i 备注应用失败 → 子事务整体回滚：原定义（1 行）/原备注保留，返回 Execution",
                  r.get("success") is False and r.get("Type") == "WORKBENCH_ERROR"
                  and r.get("Phase") == "Execution" and "回滚" in r.get("Problem", "")
                  and rows.get("row_count") == 1 and notes.get("cv_atom") == "orig",
                  json.dumps(r, ensure_ascii=False)[:150])
        finally:
            cur.execute("DROP EVENT TRIGGER IF EXISTS _wb_block_comment")
            cur.execute("DROP FUNCTION IF EXISTS _wb_block_comment()")
        r = one(cur, "SELECT wb_sql_curate('cv_atom', %s, 'new')", (sql_all,))[0]
        listed = one(cur, "SELECT wb_temp_view_list()")[0]
        check("W7j 触发器移除后重试成功（回滚未留脏状态，会话健康）",
              r.get("success") is True and r.get("replaced") is True and r.get("note") == "new"
              and {v["view"]: v["note"] for v in listed.get("views", [])}.get("cv_atom") == "new",
              json.dumps(r, ensure_ascii=False)[:140])
    finally:
        for v in ("cv_sum", "cv_len", "cv_len2", "cv_atom"):
            cur.execute(f"DROP VIEW IF EXISTS pg_temp.{v}")

    print(" F1 空问题")
    raised = False
    try:
        one(cur, "SELECT agent_run_data_analysis(%s)", ("   ",))
    except psycopg2.Error as e:
        raised = "p_question" in str(e) or "需要" in str(e)
        check("F1a 空 question 抛错", raised, str(e).splitlines()[0][:120])
    if not raised and RESULTS[-1][0] != "F1a 空 question 抛错":
        check("F1a 空 question 抛错", False, "未抛错")

    print(" F2 发现函数（无 LLM）")
    tables = one(cur, "SELECT da_list_tables()")[0]
    names = {row["table"] for row in tables}
    check("F2a da_list_tables 含 fixture", "da_sales_fixture" in names, json.dumps(sorted(names))[:160])
    schema = one(cur, "SELECT da_show_create('da_sales_fixture')")[0]
    col_names = {c["name"] for c in schema.get("columns", [])}
    check("F2b da_show_create 列", schema.get("success") is True and col_names >= {"month", "segment", "revenue", "units"},
          json.dumps(schema, ensure_ascii=False)[:180])
    bad = one(cur, "SELECT da_show_create('not a table')")[0]
    check("F2c 非法表名拒绝", bad.get("success") is False, json.dumps(bad, ensure_ascii=False)[:120])
    missing = one(cur, "SELECT da_show_create('no_such_da_table')")[0]
    check("F2d 缺表", missing.get("success") is False, json.dumps(missing, ensure_ascii=False)[:120])
    sample = one(cur, "SELECT da_sample('da_sales_fixture', 3)")[0]
    check("F2e da_sample 行数", sample.get("success") is True and sample.get("row_count") == 3,
          json.dumps(sample, ensure_ascii=False)[:180])

    print(" F3 只读守卫仍走 exec_sql_readonly")
    rid = one(cur, """
        INSERT INTO agent_runs (run_id, question, paradigm, depth, max_depth, name)
        VALUES (gen_random_uuid()::text, 't', 'data_analysis', 0, 0, 'data_analysis')
        RETURNING run_id
    """)[0]
    one(cur, "SELECT rlm_bind(%s)", (rid,))
    r = one(cur, "SELECT rlm_eval(%s, %s)", (rid, "DELETE FROM da_sales_fixture"))[0]
    check("F3a eval 拒绝 DELETE", not r.get("success"), r.get("error", "")[:80])
    r = one(cur, "SELECT rlm_eval(%s, %s)", (rid, "DROP TABLE da_sales_fixture"))[0]
    check("F3b eval 拒绝 DROP", not r.get("success"), r.get("error", "")[:80])
    wrapped = one(cur, "SELECT da_wrap_obs(%s::jsonb)", (json.dumps(r),))[0]
    check("F3c da_wrap_obs 含 Type/Phase/Problem/Solution",
          wrapped.get("Type") == "SQL_ERROR" and "Solution" in wrapped,
          json.dumps(wrapped, ensure_ascii=False)[:160])
    r = one(cur, "SELECT rlm_eval(%s, %s)", (rid, "CREATE TEMP VIEW evil_f3 AS SELECT 1"))[0]
    check("F3d eval 拒绝原生 CREATE（插件不绕过外层黑名单）",
          not r.get("success") and "create" in r.get("error", ""),
          r.get("error", "")[:80])

    print(" M mock http_call_llm 的 rlm_loop 确定性序列")
    orig_llm_def = one(cur, """
        SELECT pg_get_functiondef(p.oid) FROM pg_proc p
          JOIN pg_namespace n ON n.oid=p.pronamespace
         WHERE n.nspname='public' AND p.proname='http_call_llm' LIMIT 1
    """)[0]
    try:
        cur.execute("CREATE TEMP TABLE _mock_llm_queue (id serial PRIMARY KEY, raw text)")
        cur.execute("""
            CREATE OR REPLACE FUNCTION http_call_llm(p_messages jsonb)
            RETURNS jsonb
            LANGUAGE plpgsql VOLATILE AS $mock$
            DECLARE
                v_id  int;
                v_raw text;
            BEGIN
                SELECT id, raw INTO v_id, v_raw FROM _mock_llm_queue ORDER BY id LIMIT 1;
                IF v_id IS NULL THEN
                    RAISE EXCEPTION '_mock_llm_queue 为空：mock 序列长度不足';
                END IF;
                DELETE FROM _mock_llm_queue WHERE id = v_id;
                RETURN jsonb_build_object('raw', v_raw);
            END
            $mock$
        """)
        cur.execute("CREATE TEMP VIEW tv_mock AS "
                    "SELECT segment, sum(revenue) AS total FROM da_sales_fixture GROUP BY segment")

        # M1 工具 SQL → final
        mock_load(cur, [
            {"thought": "先预览视图", "code": "SELECT wb_brief_query('tv_mock')", "final_answer": None},
            {"thought": "已读到数据", "code": None, "final_answer": "North 250，South 450"},
        ])
        ans = one(cur, "SELECT agent_run_data_analysis(%s, NULL, 6)",
                  ("mock：tv_mock 里各 segment 的 total？",))[0]
        rid_m1 = one(cur, "SELECT run_id FROM agent_runs WHERE paradigm='data_analysis' "
                          "ORDER BY created_at DESC LIMIT 1")[0]
        kinds1 = one(cur, """
            SELECT coalesce(jsonb_agg(kind ORDER BY seq), '[]'::jsonb)
              FROM agent_steps WHERE run_id=%s
        """, (rid_m1,))[0]
        code1, obs1_text = one(cur, """
            SELECT payload->>'code', payload->>'observation'
              FROM agent_steps WHERE run_id=%s AND kind='tool' ORDER BY seq LIMIT 1
        """, (rid_m1,))
        obs1 = json.loads(obs1_text)
        nested1 = (obs1.get("data") or [{}])[0].get("wb_brief_query", {})
        n_final1 = one(cur, "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='final'",
                       (rid_m1,))[0]
        check("M1a 插件 SQL → final：步骤序列 llm,tool,llm,final，final 在 tool 之后",
              ans == "North 250，South 450" and kinds1 == ["llm", "tool", "llm", "final"]
              and n_final1 == 1,
              f"ans={ans} kinds={kinds1}")
        check("M1b tool 步骤 code 即 wb 调用；外层/嵌套双 success，行数 2，North=250",
              code1 == "SELECT wb_brief_query('tv_mock')"
              and obs1.get("success") is True and nested1.get("success") is True
              and nested1.get("row_count") == 2
              and any(d.get("segment") == "North" and d.get("total") == 250
                      for d in nested1.get("data", [])),
              json.dumps(nested1, ensure_ascii=False)[:140])

        # M2 未查库先作答：门闩拒绝
        mock_load(cur, [
            {"thought": "直接回答", "code": None, "final_answer": "没查库的答案"},
            {"thought": "还是直接回答", "code": None, "final_answer": "没查库的答案2"},
        ])
        ans = one(cur, "SELECT agent_run_data_analysis(%s, NULL, 2)", ("mock：跳过查库",))[0]
        rid_m2 = one(cur, "SELECT run_id FROM agent_runs WHERE paradigm='data_analysis' "
                          "ORDER BY created_at DESC LIMIT 1")[0]
        kinds2 = one(cur, """
            SELECT coalesce(jsonb_agg(kind ORDER BY seq), '[]'::jsonb)
              FROM agent_steps WHERE run_id=%s
        """, (rid_m2,))[0]
        n_final2 = one(cur, "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='final'",
                       (rid_m2,))[0]
        gate_obs2 = one(cur, """
            SELECT count(*) FROM agent_steps
             WHERE run_id=%s AND kind='tool'
               AND payload->>'observation' ILIKE '%%"Phase": "Finalization"%%'
        """, (rid_m2,))[0]
        check("M2 过早 final 被拒：无 final 步，门闩反馈 Finalization，跑满步数",
              "达到最大步数" in ans and n_final2 == 0 and gate_obs2 >= 1
              and kinds2[-1] == "error",
              f"ans={ans[:40]} kinds={kinds2}")

        # M3 失败 SQL 的 observation 不开作答门
        mock_load(cur, [
            {"thought": "查询", "code": "SELECT segment FROM no_such_table_mock", "final_answer": None},
            {"thought": "作答", "code": None, "final_answer": "250"},
        ])
        ans = one(cur, "SELECT agent_run_data_analysis(%s, NULL, 2)", ("mock：失败 SQL 不得作答",))[0]
        rid_m3 = one(cur, "SELECT run_id FROM agent_runs WHERE paradigm='data_analysis' "
                          "ORDER BY created_at DESC LIMIT 1")[0]
        kinds3 = one(cur, """
            SELECT coalesce(jsonb_agg(kind ORDER BY seq), '[]'::jsonb)
              FROM agent_steps WHERE run_id=%s
        """, (rid_m3,))[0]
        n_final3 = one(cur, "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='final'",
                       (rid_m3,))[0]
        obs3 = json.loads(one(cur, """
            SELECT payload->>'observation' FROM agent_steps
             WHERE run_id=%s AND kind='tool' AND payload->>'code' IS NOT NULL
             ORDER BY seq LIMIT 1
        """, (rid_m3,))[0])
        check("M3 失败 SQL 的 observation 不开作答门：无 final，外层 success=false",
              "达到最大步数" in ans and n_final3 == 0
              and obs3.get("success") is False and obs3.get("Type") == "SQL_ERROR",
              json.dumps(obs3, ensure_ascii=False)[:110])
    finally:
        # F4/F5 前恢复真实 http_call_llm；stub 不跨 SQL 重载/refresh_handlers 存续
        cur.execute(orig_llm_def)
        cur.execute("DROP TABLE IF EXISTS pg_temp._mock_llm_queue")
        cur.execute("DROP VIEW IF EXISTS pg_temp.tv_mock")
    llm_def_now = one(cur, "SELECT pg_get_functiondef('http_call_llm(jsonb)'::regprocedure)")[0]
    check("M4 真实 http_call_llm 已恢复（DeepSeek 前，不含 mock 队列）",
          "_mock_llm_queue" not in llm_def_now and "http(" in llm_def_now, "")

    print(" F4 agent_run_data_analysis（DeepSeek + fixture）")
    t0 = time.time()
    answer = llm_one(
        cur,
        "SELECT agent_run_data_analysis(%s, NULL, 12)",
        ("da_sales_fixture 表里 revenue 列的总和是多少？必须先查询该表再回答，答案里写出这个整数。",),
    )[0]
    dt = time.time() - t0
    row = one(cur, """
        SELECT run_id, paradigm, depth, max_depth, name
          FROM agent_runs WHERE paradigm='data_analysis'
         ORDER BY created_at DESC LIMIT 1
    """)
    run_id, paradigm, depth, max_depth, name = row
    kinds = one(cur, """
        SELECT coalesce(jsonb_agg(kind ORDER BY seq), '[]'::jsonb)
          FROM agent_steps WHERE run_id=%s
    """, (run_id,))[0]
    n_tool = one(cur, "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='tool'", (run_id,))[0]
    n_final = one(cur, "SELECT count(*) FROM agent_steps WHERE run_id=%s AND kind='final'", (run_id,))[0]
    grounded = grounded_tool_step(cur, run_id)
    n_child = one(cur, "SELECT count(*) FROM rlm_children WHERE parent_run_id=%s", (run_id,))[0]
    sys_p = one(cur, "SELECT da_system_prompt(%s)", (run_id,))[0]
    check("F4a paradigm=data_analysis depth/max_depth=0",
          paradigm == "data_analysis" and depth == 0 and max_depth == 0 and name == "data_analysis",
          str(row))
    check("F4b 至少一步 tool 查询", n_tool >= 1, f"dt={dt:.0f}s kinds={kinds} n_tool={n_tool}")
    check("F4c SQL 命中 fixture 且查询成功", grounded, f"grounded={grounded}")
    check("F4d final 步存在", n_final >= 1, f"n_final={n_final} answer={str(answer)[:100]}")
    check("F4e 答案含 700（fixture 总和）", "700" in str(answer), str(answer)[:160])
    check("F4f 无 child run", n_child == 0, f"n_child={n_child}")
    check("F4g system prompt 以 information_schema 为主",
          "information_schema" in sys_p and "禁止 rlm_spawn" in sys_p,
          sys_p[:80].replace("\n", " "))

    print(" F5 同一连接连续两次不串 run_id")
    t0 = time.time()
    answer2 = llm_one(
        cur,
        "SELECT agent_run_data_analysis(%s, NULL, 6)",
        ("da_sales_fixture 里 North 段的 revenue 总和是多少？先查询再回答，写出整数。",),
    )[0]
    dt2 = time.time() - t0
    ids = one(cur, """
        SELECT array_agg(run_id ORDER BY created_at DESC)
          FROM (
            SELECT run_id, created_at FROM agent_runs
             WHERE paradigm='data_analysis' ORDER BY created_at DESC LIMIT 2
          ) t
    """)[0]
    rid2 = ids[0] if ids else None
    grounded2 = grounded_tool_step(cur, rid2) if rid2 else False
    check("F5a 两次 run_id 不同", ids is not None and len(ids) == 2 and ids[0] != ids[1], str(ids))
    check("F5b 第二次 SQL 命中 fixture", grounded2, f"grounded2={grounded2}")
    check("F5c 第二次答案含 250（100+150）", "250" in str(answer2), f"{dt2:.0f}s answer={str(answer2)[:120]}")


def main():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("需要 DEEPSEEK_API_KEY")
        return 1
    missing = [p for p in SQL_FILES if not p.exists()]
    if missing:
        print("缺少: " + ", ".join(p.name for p in missing))
        return 1

    server = get_server()
    exists = False
    c0 = __import__("psycopg2").connect(server.get_uri("postgres"))
    c0.autocommit = True
    with c0.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB,))
        exists = cur.fetchone() is not None
    c0.close()
    if not exists:
        print(f"库 {DB} 不存在。请先：uv run python v2/setup_db.py")
        return 1

    print(f"reloading v2 SQL into {DB} …")
    for path in SQL_FILES:
        load_sql(server, DB, path)
        print(f"  loaded {path.name}")

    c = conn(server, DB)
    try:
        cur0 = c.cursor()
        n_wb = one(cur0, "SELECT refresh_workbench_tools()")[0]
        check("W0 加载后 refresh_workbench_tools()=6（最终门闩）", n_wb == 6, f"n={n_wb}")
        test_data_analysis(c)
    finally:
        c.close()

    print("\n" + "=" * 60)
    print("data_analysis 汇总")
    print("=" * 60)
    counts = {"pass": 0, "fail": 0, "skip": 0}
    marks = {"pass": "✓", "fail": "✗", "skip": "○"}
    for name, status, detail in RESULTS:
        if status != "pass":
            print(f"  {marks[status]} {name}  | {detail}")
        counts[status] += 1
    print(f"\n共 {len(RESULTS)} 项：通过 {counts['pass']}，失败 {counts['fail']}，跳过 {counts['skip']}")
    return 0 if counts["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
