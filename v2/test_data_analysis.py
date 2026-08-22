"""pg-agent v2 data_analysis 测试。

前置：uv run python v2/setup_db.py  （库 da_agent，不动 v1 的库）
本脚本再 CREATE OR REPLACE 加载 v2 三份 SQL，然后跑确定性检查 + DeepSeek。
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
    ROOT / "pg_agent_data_analysis.sql",
]

RESULTS: list[tuple[str, str, str]] = []


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
    try:
        _test_data_analysis_body(cur)
    finally:
        cur.execute("DROP TABLE IF EXISTS da_sales_fixture")


def _test_data_analysis_body(cur):
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
    grounded = one(cur, """
        SELECT exists(
            SELECT 1 FROM agent_steps
             WHERE run_id=%s AND kind='tool'
               AND coalesce(payload->>'code','') ILIKE '%%da_sales_fixture%%'
               AND coalesce(payload->>'observation','') NOT ILIKE '%%"success": false%%'
        )
    """, (run_id,))[0]
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
    grounded2 = one(cur, """
        SELECT exists(
            SELECT 1 FROM agent_steps
             WHERE run_id=%s AND kind='tool'
               AND coalesce(payload->>'code','') ILIKE '%%da_sales_fixture%%'
               AND coalesce(payload->>'observation','') NOT ILIKE '%%"success": false%%'
        )
    """, (rid2,))[0] if rid2 else False
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
