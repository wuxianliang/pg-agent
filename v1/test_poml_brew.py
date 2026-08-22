"""poml 层补充测试：在带 libxml 的 Homebrew PostgreSQL 17 上运行 C2/C3/C4。

pgembed 构建无 libxml（xmlparse/xpath 不可用），POML 渲染层（P2-P4）在 pgembed
环境不可测；本脚本起一个临时 brew PG 实例把 poml 层测完，测完即关。

用法: uv run python v1/test_poml_brew.py
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent))
from run_tests import RESULTS, check, skip, llm_one
from setup_db import PATCHES

ROOT = Path(__file__).parent
BREW_BIN = Path("/opt/homebrew/opt/postgresql@17/bin")
PGDATA = Path("/tmp/pgbrew_pgdata")
SOCK_DIR = Path("/tmp/pgbrew_sock")
DB = "agent_func"


def sh(*cmd, env=None, check_rc=True):
    p = subprocess.run(cmd, capture_output=True, env=env, text=True)
    if check_rc and p.returncode != 0:
        raise RuntimeError(f"{cmd} failed:\n{p.stdout}\n{p.stderr}")
    return p.stdout


def main():
    # ---------- 1. 起临时实例 ----------
    if PGDATA.exists():
        shutil.rmtree(PGDATA)
    SOCK_DIR.mkdir(exist_ok=True)
    env = {**os.environ, "LC_ALL": "C"}
    sh(str(BREW_BIN / "initdb"), "-D", str(PGDATA), "-U", "postgres", "-E", "UTF8", env=env)
    sh(str(BREW_BIN / "pg_ctl"), "-D", str(PGDATA),
       "-o", f"-c listen_addresses='' -c unix_socket_directories='{SOCK_DIR}' -p 5499",
       "-l", "/tmp/pgbrew.log", "start", env=env)
    uri = f"postgresql://postgres@/{DB}?host={SOCK_DIR}&port=5499"
    for _ in range(20):
        if "accepting" in sh(str(BREW_BIN / "pg_isready"), "-h", str(SOCK_DIR), "-p", "5499", check_rc=False):
            break
        time.sleep(0.3)

    try:
        c0 = psycopg2.connect(f"postgresql://postgres@/postgres?host={SOCK_DIR}&port=5499")
        c0.autocommit = True
        with c0.cursor() as cur:
            cur.execute("CREATE EXTENSION http")
            cur.execute(f"CREATE DATABASE {DB}")
        c0.close()
        print("[brew PG] 临时实例就绪（libxml ✓）")

        # ---------- 2. 加载 SQL（应用 PATCHES）----------
        c = psycopg2.connect(uri)
        c.autocommit = True
        cur = c.cursor()
        for name in ["pg_agent_functional.sql", "pg_agent_poml.sql"]:
            text = (ROOT / name).read_text()
            for old, new in PATCHES[name]:
                assert old in text, f"补丁未命中: {name}"
                text = text.replace(old, new)
            cur.execute(text)
        print("[brew PG] functional + poml 加载完成")

        cur.execute("SET openai.api_uri = 'https://api.deepseek.com/v1'")
        cur.execute(f"SET openai.api_key = '{os.environ['DEEPSEEK_API_KEY']}'")
        cur.execute("SET openai.model   = 'deepseek-chat'")
        cur.execute("SET statement_timeout = '300s'")
        cur.execute("SELECT http_set_curlopt('CURLOPT_CONNECTTIMEOUT', '15')")
        cur.execute("SELECT http_set_curlopt('CURLOPT_TIMEOUT', '90')")

        # ---------- 3. C2/C3/C4 ----------
        print("\n=== C（续）. poml 渲染层（brew PG + libxml）===")

        print(" C2 poml_render <table>")
        r = llm_one(cur, "SELECT poml_render($p$<poml><task>汇总</task><table query=\"SELECT 1 AS a, 'x' AS b UNION ALL SELECT 2, 'y'\" limit=\"5\"/></poml>$p$)")[0]
        check("C2a 渲染 Markdown 表格", "| a | b |" in r and "| 1 | x |" in r and "| 2 | y |" in r, r.replace("\n", "\\n")[:150])

        r = llm_one(cur, "SELECT poml_render($p$<poml><table query=\"SELECT * FROM nonexistent_t\"/></poml>$p$)")[0]
        check("C2b 查询失败优雅降级", "查询失败" in r, r.strip()[:80])

        print(" C3 render_template('agent_system')")
        r = llm_one(cur, "SELECT render_template('agent_system', %s::jsonb)", ('{"max_rows":"50"}',))[0]
        check("C3a 模板渲染含 Role/规则", "**Role:**" in r and "50" in r, r[:100].replace("\n", "\\n"))
        check("C3b 默认无 llm_tool 注释 → 工具清单为空", r.count("- `") == 0, "（按 README 需手动加 llm_tool 注释）")

        cur.execute("COMMENT ON FUNCTION h_sample_table(jobs) IS "
                    "'{\"job_handler\":\"sample_table\",\"llm_tool\":{\"name\":\"sample_table\",\"description\":\"抓取指定表的3行样本\"}}'")
        r2 = llm_one(cur, "SELECT render_template('agent_system')")[0]
        check("C3c 加注释后 <tools/> 收进工具", "- `sample_table`" in r2,
              [line for line in r2.splitlines() if line.startswith("- ")])
        cur.execute("COMMENT ON FUNCTION h_sample_table(jobs) IS '{\"job_handler\":\"sample_table\"}'")  # 还原

        print(" C4 agent_run_poml（DeepSeek）")
        t0 = time.time()
        answer = llm_one(cur, "SELECT agent_run_poml(%s)",
                         ("agent_steps 表里现在有多少行？先查询再回答，给出具体数字。",))[0]
        dt = time.time() - t0
        cur.execute("SELECT status, steps_used FROM run_state("
                    "(SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1))")
        state = cur.fetchone()
        check("C4a agent_run_poml SUCCESS", state[0] == "SUCCESS",
              f"{dt:.0f}s, steps={state[1]}, answer={str(answer)[:80]}")
        check("C4b 答案含数字", any(ch.isdigit() for ch in str(answer)), str(answer)[:120])

        c.close()
    finally:
        # ---------- 4. 关闭并清理 ----------
        sh(str(BREW_BIN / "pg_ctl"), "-D", str(PGDATA), "stop", "-m", "fast", env=env, check_rc=False)
        shutil.rmtree(PGDATA, ignore_errors=True)
        print("\n[brew PG] 临时实例已关闭并清理")

    print("\n补充测试结果：")
    for name, status, detail in RESULTS:
        print(f"  {'✓' if status == 'pass' else '✗' if status == 'fail' else '○'} {name}" +
              ("" if status == "pass" else f"  | {detail}"))
    return 0 if all(s != "fail" for _, s, _ in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
