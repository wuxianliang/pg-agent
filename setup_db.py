"""建库并加载三个 pg-agent SQL 文件。

- agent_fixed 库 ← pg_agent_fixed.sql
- agent_func  库 ← pg_agent_functional.sql + pg_agent_poml.sql（poml 依赖 functional）

幂等：重复运行会先 DROP 再建。
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from server import get_server

ROOT = Path(__file__).parent

DATABASES = {
    "agent_fixed": [ROOT / "pg_agent_fixed.sql"],
    "agent_func": [
        ROOT / "pg_agent_functional.sql",
        ROOT / "pg_agent_poml.sql",
    ],
}

# 测试环境兼容补丁与 bug 修复（源文件不动，加载时替换；测试报告会列出）
PATCHES = {
    "pg_agent_fixed.sql": [
        # bug#1: PG 正则无 \b 词边界（静默失败）→ SELECT 永远走 dml 分支，agent 拿不到数据
        (r"IF v_lower ~ '^\s*select\b' OR v_lower ~ '^\s*with\b' THEN",
         r"IF v_lower ~ '^\s*select\M' OR v_lower ~ '^\s*with\M' THEN"),
        # bug#2: worker 给 run_agent_sql 传了随机生成的 p_run_id，触发"恢复"路径报 run_id 不存在；
        #        应传 NULL 走新建路径
        ("""            ELSIF v_job.job_type = 'agent_run' THEN
                v_run_id := COALESCE(v_job.run_id, gen_random_uuid()::text);

                SELECT run_agent_sql(
                    p_run_id := v_run_id,
                    p_question := v_job.payload->>'question',
                    p_context_build_id := v_job.build_id,
                    p_max_steps := COALESCE((v_job.payload->>'max_steps')::int, 10)
                ) INTO v_answer;

                UPDATE agent_jobs
                SET status = 'DONE', result = v_answer, run_id = v_run_id, completed_at = now()
                WHERE job_id = v_job.job_id;""",
         """            ELSIF v_job.job_type = 'agent_run' THEN
                v_answer := run_agent_sql(
                    p_run_id := v_job.run_id,
                    p_question := v_job.payload->>'question',
                    p_context_build_id := v_job.build_id,
                    p_max_steps := COALESCE((v_job.payload->>'max_steps')::int, 10)
                );

                UPDATE agent_jobs
                SET status = 'DONE', result = v_answer,
                    run_id = COALESCE(v_job.run_id,
                        (SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1)),
                    completed_at = now()
                WHERE job_id = v_job.job_id;"""),
    ],
    "pg_agent_functional.sql": [
        # bug#3: PG17 中 'name(args)'::regproc 无法定位带参函数（内置函数同败），需 regprocedure
        (r"'http_call_llm(jsonb)'::regproc", r"'http_call_llm(jsonb)'::regprocedure"),
        # bug#4: jsonb || 对 object 是合并而非拼接 → system 消息被 user 覆盖（LLM 收不到 system prompt）
        ("""    SELECT jsonb_build_object('role','system','content',p_system)
        || jsonb_build_object('role','user','content',p_question)
        || COALESCE((""",
         """    SELECT jsonb_build_array(
               jsonb_build_object('role','system','content',p_system),
               jsonb_build_object('role','user','content',p_question))
        || COALESCE(("""),
    ],
    "pg_agent_poml.sql": [
        (r"'http_call_llm(jsonb)'::regproc", r"'http_call_llm(jsonb)'::regprocedure"),
        # bug#5: PG 的 regexp_match 返回捕获组数组（1-based，无整体匹配），m[0] 恒为 NULL
        #        → replace(p_src, NULL, ...) 返回 NULL → 三个模板函数全部返回 NULL。
        #        修复：正则外包一层捕获组，m[1]=整体匹配，原 m[1..n] 顺移为 m[2..n+1]。
        (r"""        m := regexp_match(p_src, '\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}');
        IF m IS NULL THEN RETURN p_src; END IF;
        v := p_params #>> string_to_array(m[1], '.');
        p_src := replace(p_src, m[0], COALESCE(v, ''));""",
         r"""        m := regexp_match(p_src, '(\{\{\s*([a-zA-Z_][\w.]*)\s*\}\})');
        IF m IS NULL THEN RETURN p_src; END IF;
        v := p_params #>> string_to_array(m[2], '.');
        p_src := replace(p_src, m[1], COALESCE(v, ''));"""),
        (r"""        m := regexp_match(p_src,
            '<for\s+items="([^"]+)"\s+item="([^"]+)"\s*>([\s\S]*?)</for>');
        IF m IS NULL THEN RETURN p_src; END IF;
        result := '';
        FOR item IN
            SELECT value FROM jsonb_array_elements(
                COALESCE(p_params #> string_to_array(m[1], '.'), '[]'::jsonb))
        LOOP
            body := replace(m[3], '{{' || m[2] || '}}',
                            CASE jsonb_typeof(item) WHEN 'object' THEN '' ELSE item #>> '{}' END);
            -- {{item.field}} 形式
            body := poml_expand_vars(body, jsonb_build_object(m[2], item));
            result := result || body;
        END LOOP;
        p_src := replace(p_src, m[0], result);""",
         r"""        m := regexp_match(p_src,
            '(<for\s+items="([^"]+)"\s+item="([^"]+)"\s*>([\s\S]*?)</for>)');
        IF m IS NULL THEN RETURN p_src; END IF;
        result := '';
        FOR item IN
            SELECT value FROM jsonb_array_elements(
                COALESCE(p_params #> string_to_array(m[2], '.'), '[]'::jsonb))
        LOOP
            body := replace(m[4], '{{' || m[3] || '}}',
                            CASE jsonb_typeof(item) WHEN 'object' THEN '' ELSE item #>> '{}' END);
            -- {{item.field}} 形式
            body := poml_expand_vars(body, jsonb_build_object(m[3], item));
            result := result || body;
        END LOOP;
        p_src := replace(p_src, m[1], result);"""),
        (r"""        m := regexp_match(p_src, '<if\s+cond="([^"]*)"\s*>([\s\S]*?)</if>');
        IF m IS NULL THEN RETURN p_src; END IF;
        p_src := replace(p_src, m[0],
            -- 语义：cond 展开后非空且不是显式假值即为真（适合 {{context}} 这类存在性判断）
            CASE WHEN trim(m[1]) <> ''
                  AND lower(trim(m[1])) NOT IN ('false','0','no','null')
                 THEN m[2] ELSE '' END);""",
         r"""        m := regexp_match(p_src, '(<if\s+cond="([^"]*)"\s*>([\s\S]*?)</if>)');
        IF m IS NULL THEN RETURN p_src; END IF;
        p_src := replace(p_src, m[1],
            -- 语义：cond 展开后非空且不是显式假值即为真（适合 {{context}} 这类存在性判断）
            CASE WHEN trim(m[2]) <> ''
                  AND lower(trim(m[2])) NOT IN ('false','0','no','null')
                 THEN m[3] ELSE '' END);"""),
    ],
}


def run_psql(server, database: str, sql: str, on_error_stop: bool = False) -> str:
    """在指定库上执行 SQL，返回输出。"""
    uri = server.get_uri(database)
    cmd = [str(Path(sys.prefix) / "bin" / "psql")] if False else None
    from pgembed.postgres_server import POSTGRES_BIN_PATH

    proc = subprocess.run(
        [str(POSTGRES_BIN_PATH / "psql"), uri, "-v", "ON_ERROR_STOP=" + ("1" if on_error_stop else "0"), "-q"],
        input=sql.encode(),
        capture_output=True,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0 and on_error_stop:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out


def main():
    server = get_server()

    for db, sql_files in DATABASES.items():
        # 幂等重建：先删后建（terminate 活连接）
        run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {db} WITH (FORCE);")
        run_psql(server, "postgres", f"CREATE DATABASE {db};")
        print(f"[created] {db}")

        for sql_file in sql_files:
            sql_text = sql_file.read_text()
            for old, new in PATCHES.get(sql_file.name, []):
                if old in sql_text:
                    sql_text = sql_text.replace(old, new)
                    print(f"[patched] {sql_file.name}: {old[:60].splitlines()[0]}...")
                else:
                    raise RuntimeError(f"补丁未命中（源文件可能已改）: {sql_file.name}: {old[:80]!r}")
            out = run_psql(server, db, sql_text)
            errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
            status = "OK" if not errors else "OK (with errors below)"
            print(f"[loaded ] {db} <- {sql_file.name}: {status}")
            for e in errors:
                print(f"          {e}")

    # 验证关键对象
    checks = {
        "agent_fixed": ["http extension", "execute_sql_safe", "call_llm", "run_agent_sql", "agent_worker", "build_context_parallel"],
        "agent_func": ["http extension", "exec_sql_readonly", "http_call_llm", "agent_run", "worker", "poml_render", "agent_run_poml", "render_template"],
    }
    print("\n=== 验证 ===")
    ok = True
    for db, names in checks.items():
        for name in names:
            if name == "http extension":
                out = run_psql(server, db, "SELECT extname FROM pg_extension WHERE extname='http';")
            else:
                out = run_psql(server, db, f"SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname='{name}';")
            found = "1 row" in out or "http" in out
            print(f"  {db}.{name}: {'✓' if found else '✗ MISSING'}")
            ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
