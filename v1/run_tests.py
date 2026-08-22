"""pg-agent SQL agent 系统的端到端测试。

覆盖：
  A. pg_agent_fixed.sql           —— execute_sql_safe / run_agent_sql / 上下文构建链 / worker
  B. pg_agent_functional.sql      —— 组合子 / 纯函数 / exec_sql_readonly / handler 注册 / agent_run / worker
  C. pg_agent_poml.sql            —— 模板引擎 / poml_render / render_template / agent_run_poml
  D. pg_agent_rlm.sql             —— 独立 RLM：env REPL / eval / spawn 深度 / rlm_run
  E. pg_agent_rlm_integrated.sql  —— 与 CodeAct 共用 agent_runs/steps/jobs

LLM 依赖项通过 DeepSeek 真实调用（openai.* GUC）。
"""
import json
import os
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server

RESULTS: list[tuple[str, str, str]] = []  # (name, status, detail) status: pass/fail/skip


def check(name: str, cond, detail: str = ""):
    RESULTS.append((name, "pass" if cond else "fail", str(detail)[:200]))
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"  | {detail}" if detail else ""))


def skip(name: str, reason: str = ""):
    RESULTS.append((name, "skip", reason))
    print(f"  ○ {name}  | SKIP: {reason}")


def conn(server, db):
    c = psycopg2.connect(server.get_uri(db))
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SET openai.api_uri = 'https://api.deepseek.com/v1'")
        cur.execute(f"SET openai.api_key = '{os.environ['DEEPSEEK_API_KEY']}'")
        cur.execute("SET openai.model   = 'deepseek-chat'")
        cur.execute("SET statement_timeout = '300s'")
        try:  # curl 超时是会话级，测试连接需自行设置（fixed 版 call_llm 无 retry 护甲）
            cur.execute("SELECT http_set_curlopt('CURLOPT_CONNECTTIMEOUT', '15')")
            cur.execute("SELECT http_set_curlopt('CURLOPT_TIMEOUT', '90')")
        except Exception:
            pass
    return c


def one(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchone()


def llm_one(cur, sql, params=None, tries: int = 3):
    """LLM 端到端调用的外层重试（网络瞬态失败快速失败后重试）。"""
    last = None
    for i in range(tries):
        try:
            return one(cur, sql, params)
        except psycopg2.Error as e:
            last = e
            print(f"    (网络/LLM 失败，第 {i + 1} 次重试: {str(e).splitlines()[0][:80]})")
            time.sleep(3)
    raise last


# ============================================================
# A. pg_agent_fixed.sql
# ============================================================
def test_fixed(c):
    print("\n=== A. pg_agent_fixed.sql ===")
    cur = c.cursor()

    # --- A1. execute_sql_safe ---
    print(" A1 execute_sql_safe")
    r = one(cur, "SELECT execute_sql_safe(%s)", ("SELECT 1 AS n, 'x' AS s",))
    check("A1a 正常查询返回数据", r[0]["success"] and r[0]["row_count"] == 1, json.dumps(r[0], ensure_ascii=False)[:120])

    r = one(cur, "SELECT execute_sql_safe(%s)", ("DROP TABLE t;",))
    check("A1b 拒绝 DROP", not r[0]["success"] and "危险关键字" in r[0].get("error", ""), r[0].get("error", ""))

    r = one(cur, "SELECT execute_sql_safe(%s)", ("SELECT 1; SELECT 2;",))
    check("A1c 拒绝多语句", not r[0]["success"] and "多条" in r[0].get("error", ""), r[0].get("error", ""))

    r = one(cur, "SELECT execute_sql_safe(%s, 50, false)", ("INSERT INTO agent_runs(run_id, question) VALUES ('x','y')",))
    check("A1d 只读模式拒绝写", not r[0]["success"] and "禁止写" in r[0].get("error", ""), r[0].get("error", ""))

    # --- A2. run_agent_sql 端到端（LLM）---
    print(" A2 run_agent_sql（DeepSeek）")
    t0 = time.time()
    answer = llm_one(cur, "SELECT run_agent_sql(p_question => %s, p_max_steps => 6)",
                     ("public 模式下有多少张表？请先查询再回答，答案里给出具体数字。",))[0]
    dt = time.time() - t0
    row = one(cur, "SELECT status, final_answer FROM agent_runs ORDER BY created_at DESC LIMIT 1")
    steps = one(cur, "SELECT count(*) FROM agent_steps")[0]
    check("A2a agent 跑通 status=SUCCESS", row[0] == "SUCCESS", f"{dt:.0f}s, {steps} steps, answer={str(answer)[:80]}")
    check("A2b final_answer 含数字", any(ch.isdigit() for ch in (row[1] or "")), str(row[1])[:120])

    # --- A3. 上下文构建链（无 LLM）---
    print(" A3 上下文构建链")
    build_id = one(cur, "SELECT build_context_parallel('测试构建')")[0]
    worker_msg = one(cur, "SELECT agent_worker('test-worker')")[0]
    fin = one(cur, "SELECT finalize_context_build(%s)", (build_id,))[0]
    check("A3a worker 跑完队列", "没有更多任务" in worker_msg, worker_msg[:80])
    check("A3b finalize 完成", "完成" in fin, fin[:80])
    segs = one(cur, "SELECT count(*), count(DISTINCT segment_type) FROM context_segments WHERE build_id=%s", (build_id,))
    check("A3c 生成了 schema/stats/sample 片段", segs[0] >= 3 and segs[1] >= 3, f"segments={segs[0]}, types={segs[1]}")
    ctx = one(cur, "SELECT get_context_for_agent(%s)", (build_id,))[0]
    check("A3d 上下文可检索且非空", ctx and len(ctx) > 50, f"ctx len={len(ctx or '')}")

    # --- A4. 带上下文的 agent 经 worker 队列（LLM）---
    print(" A4 submit_context_agent + agent_worker（DeepSeek）")
    job = None
    for attempt in range(2):  # 网络瞬态失败时重新提交一个新 job
        job_id = one(cur, "SELECT submit_context_agent('agent_runs 表里现在有多少条记录？请查询后回答。', %s)", (build_id,))[0]
        t0 = time.time()
        worker_msg = llm_one(cur, "SELECT agent_worker('test-worker2')")
        dt = time.time() - t0
        job = one(cur, "SELECT status, result, run_id FROM agent_jobs WHERE job_id=%s", (job_id,))
        if job[0] == "DONE":
            break
        print(f"    (job 未 DONE，第 {attempt + 1} 轮重试)")
    check("A4a 队列 job DONE", job[0] == "DONE", f"{dt:.0f}s, result={str(job[1])[:80]}")
    check("A4b agent 给出数字答案", job[1] and any(ch.isdigit() for ch in job[1]), str(job[1])[:120])


# ============================================================
# B. pg_agent_functional.sql
# ============================================================
def test_functional(c):
    print("\n=== B. pg_agent_functional.sql ===")
    cur = c.cursor()

    # --- B1. 组合子 ---
    print(" B1 组合子 sql_pipe / sql_map / sql_retry")
    cur.execute("""
        CREATE OR REPLACE FUNCTION t_inc(p jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS
        $$ SELECT jsonb_build_object('n', COALESCE((p->>'n')::int,0)+1) $$;
        CREATE OR REPLACE FUNCTION t_double(p jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS
        $$ SELECT jsonb_build_object('n', (p->>'n')::int*2) $$;
        CREATE OR REPLACE FUNCTION t_boom(p jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS
        $$ BEGIN RAISE EXCEPTION 'boom'; END $$;
    """)
    r = one(cur, "SELECT sql_pipe(ARRAY['t_inc(jsonb)','t_double(jsonb)']::regprocedure[], '{\"n\":3}')")
    check("B1a sql_pipe 串联 (3+1)*2=8", r[0]["n"] == 8, json.dumps(r[0]))

    r = one(cur, "SELECT sql_map('t_inc(jsonb)'::regprocedure, '[{\"n\":1},{\"n\":2},{\"n\":3}]')")
    check("B1b sql_map 映射 [2,3,4]", [x["n"] for x in r[0]] == [2, 3, 4], json.dumps(r[0]))

    try:
        one(cur, "SELECT sql_retry('t_boom(jsonb)'::regprocedure, '{}', 3)")
        check("B1c sql_retry 重试后抛出异常", False, "未抛异常")
    except Exception as e:
        check("B1c sql_retry 重试后抛出异常", "boom" in str(e), str(e).splitlines()[0][:80])

    # --- B2. 纯函数 ---
    print(" B2 纯函数 make_system_prompt / parse_llm_output / fold_messages")
    s = one(cur, "SELECT make_system_prompt(77)")[0]
    check("B2a prompt 含行数限制", "77" in s and "execute_sql" in s, s[:60])

    s2 = one(cur, "SELECT make_system_prompt(50, 'CTX-HERE')")[0]
    check("B2b prompt 含上下文", "CTX-HERE" in s2)

    d = one(cur, "SELECT (parse_llm_output(%s)).*", ('{"thought":"t","action":"execute_sql","action_input":"SELECT 1","final_answer":null}',))
    check("B2c 解析工具决策", d[1] == "execute_sql" and d[2] == "SELECT 1" and d[3] is None, str(d))

    d = one(cur, "SELECT (parse_llm_output(%s)).*", ('```json\n{"thought":"t","action":null,"final_answer":"答案42"}\n```',))
    check("B2d 解析 markdown 围栏", d[1] is None and d[3] == "答案42", str(d))

    d = one(cur, "SELECT (parse_llm_output(%s)).*", ('好的：{"thought":"t","action":null,"final_answer":"7"} 完毕。',))
    check("B2e 噪声文本中提取 JSON", d[3] == "7", str(d))

    steps = json.dumps([
        {"seq": 1, "kind": "llm", "payload": {"raw": "R1"}},
        {"seq": 2, "kind": "tool", "payload": {"observation": "O1"}},
        {"seq": 3, "kind": "llm", "payload": {"raw": "R2"}},
    ])
    msgs = one(cur, "SELECT fold_messages('SYS', 'Q', %s::jsonb)", (steps,))[0]
    roles = [m["role"] for m in msgs]
    check("B2f fold_messages 角色序列", roles == ["system", "user", "assistant", "user", "assistant"], str(roles))
    check("B2g observation 注入", "Observation: O1" in msgs[3]["content"])

    # --- B3. exec_sql_readonly ---
    print(" B3 exec_sql_readonly")
    r = one(cur, "SELECT exec_sql_readonly('SELECT count(*) AS n FROM pg_tables WHERE schemaname=''public''')")
    check("B3a 查询成功", r[0]["success"] and r[0]["row_count"] == 1, json.dumps(r[0])[:100])
    r = one(cur, "SELECT exec_sql_readonly(%s)", ("DELETE FROM jobs;",))
    check("B3b 拒绝写", not r[0]["success"], r[0].get("error", "")[:60])

    # --- B4. handler 元编程注册 ---
    print(" B4 refresh_handlers")
    n = one(cur, "SELECT refresh_handlers()")[0]
    cur.execute("SELECT job_type, fn FROM handlers ORDER BY job_type")
    rows = cur.fetchall()
    got = {r[0] for r in rows}
    core = {"schema_all_tables", "sample_table", "agent_run"}
    check("B4a 注册核心 handler（允许 RLM 扩展）", n >= 3 and core <= got,
          f"n={n}, {[(r[0], str(r[1])) for r in rows]}")

    # --- B5. agent_run 端到端（LLM）---
    print(" B5 agent_run（DeepSeek）")
    t0 = time.time()
    answer = llm_one(cur, "SELECT agent_run(%s, 6)", ("public 模式下有多少张表？先查询再回答，给出具体数字。",))[0]
    dt = time.time() - t0
    state = one(cur, "SELECT status, steps_used FROM run_state((SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1))")
    check("B5a agent_run status=SUCCESS", state[0] == "SUCCESS", f"{dt:.0f}s, steps={state[1]}, answer={str(answer)[:80]}")
    check("B5b 答案含数字", any(ch.isdigit() for ch in str(answer)), str(answer)[:120])

    # --- B6. jobs 队列 + worker ---
    print(" B6 jobs + worker")
    cur.execute("""
        INSERT INTO jobs (job_type, payload) VALUES ('schema_all_tables', '{}');
        INSERT INTO jobs (job_type, payload) VALUES ('sample_table', '{"target_table":"agent_runs"}');
    """)
    msg = one(cur, "SELECT worker('w-test')")[0]
    cur.execute("SELECT job_type, status, result IS NOT NULL FROM jobs ORDER BY job_id")
    rows = cur.fetchall()
    check("B6a worker 清空队列", "队列已空" in msg, msg[:60])
    check("B6b 两个 job 均 DONE", all(r[1] == "DONE" for r in rows), str([(r[0], r[1], r[2]) for r in rows]))


# ============================================================
# C. pg_agent_poml.sql
# ============================================================
def test_poml(c):
    print("\n=== C. pg_agent_poml.sql ===")
    cur = c.cursor()

    # XML 能力探测（pgembed 构建无 libxml 则 xpath/xmlparse 不可用，渲染层整体受限）
    xml_ok = True
    try:
        cur.execute("SELECT xmlcomment('t')")
        cur.fetchone()
    except Exception:
        xml_ok = False
    if not xml_ok:
        print("  ! 本 pgembed 构建无 libxml：xmlparse/xpath 不可用，P2-P4 渲染层受限")

    # --- C1. 模板引擎 ---
    print(" C1 模板引擎 expand_vars / expand_for / expand_if")
    r = one(cur, "SELECT poml_expand_vars('a={{x.y}} b={{z}}', '{\"x\":{\"y\":\"V\"}}')")[0]
    check("C1a 变量替换+缺失容忍", r == "a=V b=", r)

    r = one(cur, "SELECT poml_expand_for(%s, '{\"items\":[\"a\",\"b\"]}')",
            ("<for items=\"items\" item=\"x\">- {{x}}\n</for>",))[0]
    check("C1b for 循环展开", r == "- a\n- b\n", repr(r))

    r = one(cur, "SELECT poml_expand_if(poml_expand_vars('<if cond=\"{{flag}}\">YES</if>', '{\"flag\":true}'))")[0]
    check("C1c if 为真保留", r == "YES", repr(r))
    r = one(cur, "SELECT poml_expand_if(poml_expand_vars('<if cond=\"{{flag}}\">YES</if>', '{}'))")[0]
    check("C1d if 为假剔除", r == "", repr(r))

    # --- C2. poml_render 数据组件 ---
    print(" C2 poml_render <table>")
    if not xml_ok:
        skip("C2a 渲染 Markdown 表格", "需 xmlparse/xpath（libxml）")
        skip("C2b 查询失败优雅降级", "需 xmlparse/xpath（libxml）")
    else:
        r = one(cur, "SELECT poml_render($p$<poml><task>汇总</task><table query=\"SELECT 1 AS a, 'x' AS b UNION ALL SELECT 2, 'y'\" limit=\"5\"/></poml>$p$)")[0]
        check("C2a 渲染 Markdown 表格", "| a | b |" in r and "| 1 | x |" in r and "| 2 | y |" in r, r.replace("\n", "\\n")[:150])

        r = one(cur, "SELECT poml_render($p$<poml><table query=\"SELECT * FROM nonexistent_t\"/></poml>$p$)")[0]
        check("C2b 查询失败优雅降级", "查询失败" in r, r.strip()[:80])

    # --- C3. 模板表 + <tools/> ---
    print(" C3 render_template('agent_system')")
    if not xml_ok:
        skip("C3a 模板渲染含 Role/规则", "需 xmlparse/xpath（libxml）")
        skip("C3b 默认无 llm_tool 注释 → 工具清单为空", "需 xmlparse/xpath（libxml）")
        skip("C3c 加注释后 <tools/> 收进工具", "需 xmlparse/xpath（libxml）")
    else:
        r = one(cur, "SELECT render_template('agent_system')")[0]
        check("C3a 模板渲染含 Role/规则", "**Role:**" in r and "50" in r, r[:100].replace("\n", "\\n"))
        check("C3b 默认无 llm_tool 注释 → 工具清单为空", r.count("- `") == 0, "（按 README 需手动加 llm_tool 注释）")

        cur.execute("COMMENT ON FUNCTION h_sample_table(jobs) IS "
                    "'{\"job_handler\":\"sample_table\",\"llm_tool\":{\"name\":\"sample_table\",\"description\":\"抓取指定表的3行样本\"}}'")
        r2 = one(cur, "SELECT render_template('agent_system')")[0]
        check("C3c 加注释后 <tools/> 收进工具", "- `sample_table`" in r2, [l for l in r2.splitlines() if l.startswith("- ")])
        cur.execute("COMMENT ON FUNCTION h_sample_table(jobs) IS '{\"job_handler\":\"sample_table\"}'")  # 还原

    # --- C4. agent_run_poml 端到端（LLM）---
    print(" C4 agent_run_poml（DeepSeek）")
    if not xml_ok:
        skip("C4a agent_run_poml SUCCESS", "需 xmlparse/xpath（libxml）")
        skip("C4b 答案含数字", "需 xmlparse/xpath（libxml）")
    else:
        t0 = time.time()
        answer = llm_one(cur, "SELECT agent_run_poml(%s)", ("agent_steps 表里现在有多少行？先查询再回答，给出具体数字。",))[0]
        dt = time.time() - t0
        state = one(cur, "SELECT status, steps_used FROM run_state((SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1))")
        check("C4a agent_run_poml SUCCESS", state[0] == "SUCCESS", f"{dt:.0f}s, steps={state[1]}, answer={str(answer)[:80]}")
        check("C4b 答案含数字", any(ch.isdigit() for ch in str(answer)), str(answer)[:120])


# ============================================================
# D. pg_agent_rlm.sql（独立 RLM）
# ============================================================
def test_rlm(c):
    print("\n=== D. pg_agent_rlm.sql ===")
    cur = c.cursor()

    print(" D1 env REPL")
    run_id = one(cur, "SELECT gen_random_uuid()::text")[0]
    cur.execute("INSERT INTO rlm_runs (run_id, question) VALUES (%s, 't')", (run_id,))
    one(cur, "SELECT rlm_bind(%s)", (run_id,))
    one(cur, "SELECT env_set_text('question', 'hello')")
    one(cur, "SELECT env_set('n', '5')")
    one(cur, "SELECT env_set_text('context', %s)", ("aaa SECRET_TOKEN=pg-rlm-42 bbb",))
    q = one(cur, "SELECT env_get('question')")[0]
    n = one(cur, "SELECT env_get('n')")[0]
    keys = one(cur, "SELECT env_keys()")[0]
    check("D1a env_get 文本", q == "hello", json.dumps(q, ensure_ascii=False))
    check("D1b env_set 解析 JSON 数字", n == 5, json.dumps(n))
    check("D1c env_keys 含 question/n/context", set(keys) >= {"question", "n", "context"}, json.dumps(keys))
    check("D1d env_peek", one(cur, "SELECT env_peek('question', 1, 2)")[0] == "he")
    check("D1e env_len", one(cur, "SELECT env_len('question')")[0] == 5)
    hits = one(cur, "SELECT env_search('context', %s)", (r"SECRET_TOKEN=\S+",))[0]
    check("D1f env_search", hits.get("n") == 1 and "pg-rlm-42" in json.dumps(hits), json.dumps(hits))
    chunks = one(cur, "SELECT env_chunk('context', 10)")[0]
    check("D1g env_chunk", isinstance(chunks, list) and len(chunks) >= 2, json.dumps(chunks)[:120])

    print(" D2 rlm_eval 安全")
    r = one(cur, "SELECT rlm_eval(%s, %s)", (run_id, "SELECT env_peek('question',1,5)"))[0]
    check("D2a eval 可读 env", r.get("success") and r.get("row_count") == 1, json.dumps(r, ensure_ascii=False)[:160])
    r = one(cur, "SELECT rlm_eval(%s, %s)", (run_id, "DROP TABLE t"))[0]
    check("D2b 拒绝 DROP", not r.get("success"), r.get("error", "")[:80])
    r = one(cur, "SELECT rlm_query(%s)", ("SELECT 1 AS n",))[0]
    check("D2c rlm_query 只读查询", r.get("success") and r.get("row_count") == 1, json.dumps(r)[:120])

    print(" D3 纯函数 prompt/parse/fold")
    d = one(cur, "SELECT (parse_rlm_output(%s)).*",
            ('{"thought":"t","code":"SELECT 1","final_answer":null}',))
    check("D3a 解析 code", d[1] == "SELECT 1" and d[2] is None, str(d))
    d = one(cur, "SELECT (parse_rlm_output(%s)).*",
            ('```json\n{"thought":"t","code":null,"final_answer":"答案42"}\n```',))
    check("D3b 解析 markdown 围栏", d[1] is None and d[2] == "答案42", str(d))
    prompt = one(cur, "SELECT make_rlm_prompt(0,1,50,true)")[0]
    check("D3c prompt 含 REPL API 且不含业务数据",
          "env_peek" in prompt and "rlm_spawn" in prompt and "SECRET_TOKEN" not in prompt,
          prompt[:80].replace("\n", " "))
    steps = json.dumps([
        {"seq": 1, "kind": "llm", "payload": {"raw": "R1"}},
        {"seq": 2, "kind": "tool", "payload": {"observation": "O1"}},
    ])
    msgs = one(cur, "SELECT fold_rlm_messages('SYS', 'U', %s::jsonb)", (steps,))[0]
    roles = [m["role"] for m in msgs]
    check("D3d fold_rlm_messages 是 JSON 数组", roles == ["system", "user", "assistant", "user"], str(roles))
    sys_p = one(cur, "SELECT rlm_system_prompt(%s)", (run_id,))[0]
    check("D3e rlm_system_prompt 不含 context 正文", "SECRET_TOKEN" not in sys_p, sys_p[:80].replace("\n", " "))

    print(" D4 spawn 深度上限（无 LLM）")
    deep = one(cur, "SELECT gen_random_uuid()::text")[0]
    cur.execute("INSERT INTO rlm_runs (run_id, question, depth, max_depth) VALUES (%s,'q',1,1)", (deep,))
    one(cur, "SELECT rlm_bind(%s)", (deep,))
    r = one(cur, "SELECT rlm_spawn('x', 'c1')")[0]
    check("D4a depth>=max_depth 拒绝 spawn", r.get("success") is False and "深度" in (r.get("error") or ""), json.dumps(r, ensure_ascii=False)[:160])

    print(" D5 rlm_run（DeepSeek）")
    t0 = time.time()
    answer = llm_one(cur, "SELECT rlm_run(%s, NULL, 6, 0)",
                     ("public 模式下有多少张表？先查询再回答，给出具体数字。",))[0]
    dt = time.time() - t0
    state = one(cur, "SELECT status, steps_used FROM rlm_run_state((SELECT run_id FROM rlm_runs WHERE parent_run_id IS NULL ORDER BY created_at DESC LIMIT 1))")
    check("D5a rlm_run status=SUCCESS", state[0] == "SUCCESS", f"{dt:.0f}s, steps={state[1]}, answer={str(answer)[:80]}")
    check("D5b 答案含数字", any(ch.isdigit() for ch in str(answer)), str(answer)[:120])

    print(" D6 prompt-as-variable 大海捞针（DeepSeek）")
    padding = ("lorem ipsum dolor sit amet " * 80)
    context = padding + "SECRET_TOKEN=pg-rlm-42" + padding
    t0 = time.time()
    answer = llm_one(cur, "SELECT rlm_run(%s, %s, 8, 0)",
                     ("使用 env_search 或 env_peek 在 context 变量中查找 SECRET_TOKEN 的值，只要那个值。", context))[0]
    dt = time.time() - t0
    rid = one(cur, "SELECT run_id FROM rlm_runs WHERE parent_run_id IS NULL ORDER BY created_at DESC LIMIT 1")[0]
    sys_p = one(cur, "SELECT rlm_system_prompt(%s)", (rid,))[0]
    one(cur, "SELECT rlm_bind(%s)", (rid,))
    ctx_in_env = one(cur, "SELECT env_text('context')")[0]
    check("D6a context 在 env 而不在 prompt", "SECRET_TOKEN=pg-rlm-42" in (ctx_in_env or "") and "SECRET_TOKEN=pg-rlm-42" not in sys_p,
          f"prompt_has={('SECRET_TOKEN=pg-rlm-42' in sys_p)} env_len={len(ctx_in_env or '')}")
    check("D6b agent 找出 token", "pg-rlm-42" in str(answer), f"{dt:.0f}s, answer={str(answer)[:120]}")


# ============================================================
# E. pg_agent_rlm_integrated.sql（与 CodeAct 共用表）
# ============================================================
def test_rlm_integrated(c):
    print("\n=== E. pg_agent_rlm_integrated.sql ===")
    cur = c.cursor()

    print(" E1 共用 schema")
    cur.execute("SELECT paradigm, parent_run_id, depth, max_depth, name FROM agent_runs LIMIT 0")
    check("E1a agent_runs 扩展列存在", True)
    cur.execute("SELECT run_id, name, value FROM rlm_vars LIMIT 0")
    cur.execute("SELECT parent_run_id, child_run_id, kind FROM rlm_children LIMIT 0")
    check("E1b rlm_vars / rlm_children 存在", True)
    n = one(cur, "SELECT count(*) FROM handlers WHERE job_type IN ('rlm_run','hybrid_run','agent_run')")[0]
    check("E1c 同一 handlers 表含 codeact + rlm", n == 3, f"n={n}")

    print(" E2 共用 agent_runs 上的 env")
    run_id = one(cur, "INSERT INTO agent_runs (run_id, question, paradigm) VALUES (gen_random_uuid()::text, 't', 'rlm') RETURNING run_id")[0]
    one(cur, "SELECT rlm_bind(%s)", (run_id,))
    one(cur, "SELECT env_set_text('question', 'shared')")
    v = one(cur, "SELECT value FROM rlm_vars WHERE run_id=%s AND name='question'", (run_id,))[0]
    check("E2a rlm_vars 挂在 agent_runs 上", v == "shared", json.dumps(v, ensure_ascii=False))
    r = one(cur, "SELECT rlm_eval(%s, %s)", (run_id, "SELECT env_peek('question',1,6)"))[0]
    check("E2b rlm_eval 走 exec_sql_readonly", r.get("success"), json.dumps(r, ensure_ascii=False)[:160])
    r = one(cur, "SELECT rlm_eval(%s, %s)", (run_id, "DELETE FROM agent_runs"))[0]
    check("E2c eval 仍拒绝写", not r.get("success"), r.get("error", "")[:80])

    print(" E3 hybrid prompt")
    p = one(cur, "SELECT make_hybrid_prompt(50, true)")[0]
    check("E3a hybrid 同时描述 execute_sql 与 rlm", "execute_sql" in p and "rlm" in p,
          p[:100].replace("\n", " "))
    check("E3b 长上下文提示不把正文塞进 prompt", "未写入本 prompt" in p or "context" in p, p[:80].replace("\n", " "))

    print(" E4 spawn 深度上限（无 LLM）")
    deep = one(cur, "INSERT INTO agent_runs (run_id, question, paradigm, depth, max_depth) VALUES (gen_random_uuid()::text,'q','rlm',1,1) RETURNING run_id")[0]
    one(cur, "SELECT rlm_bind(%s)", (deep,))
    r = one(cur, "SELECT rlm_spawn('x', 'c1')")[0]
    check("E4a 共用 run 上的深度拒绝", r.get("success") is False and "深度" in (r.get("error") or ""), json.dumps(r, ensure_ascii=False)[:160])

    print(" E5 agent_run_rlm（DeepSeek，写入共用 steps）")
    t0 = time.time()
    answer = llm_one(cur, "SELECT agent_run_rlm(%s, NULL, 6, 0)",
                     ("public 模式下有多少张表？先查询再回答，给出具体数字。",))[0]
    dt = time.time() - t0
    row = one(cur, "SELECT run_id, paradigm FROM agent_runs WHERE paradigm='rlm' ORDER BY created_at DESC LIMIT 1")
    state = one(cur, "SELECT status, steps_used FROM run_state(%s)", (row[0],))
    n_steps = one(cur, "SELECT count(*) FROM agent_steps WHERE run_id=%s", (row[0],))[0]
    check("E5a 写入共用 agent_runs paradigm=rlm", row[1] == "rlm", str(row))
    check("E5b 共用 run_state=SUCCESS", state[0] == "SUCCESS", f"{dt:.0f}s, steps={state[1]}, n_steps={n_steps}, answer={str(answer)[:80]}")
    check("E5c 答案含数字", any(ch.isdigit() for ch in str(answer)), str(answer)[:120])

    print(" E6 整合版大海捞针：prompt 不含正文")
    padding = ("lorem ipsum dolor sit amet " * 80)
    context = padding + "SECRET_TOKEN=pg-rlm-42" + padding
    t0 = time.time()
    answer = llm_one(cur, "SELECT agent_run_rlm(%s, %s, 8, 0)",
                     ("使用 env_search 或 env_peek 在 context 变量中查找 SECRET_TOKEN 的值，只要那个值。", context))[0]
    dt = time.time() - t0
    rid = one(cur, "SELECT run_id FROM agent_runs WHERE paradigm='rlm' ORDER BY created_at DESC LIMIT 1")[0]
    sys_p = one(cur, "SELECT rlm_system_prompt(%s)", (rid,))[0]
    check("E6a 共用 run 的 prompt 不含 token", "SECRET_TOKEN=pg-rlm-42" not in sys_p)
    check("E6b agent 找出 token", "pg-rlm-42" in str(answer), f"{dt:.0f}s, answer={str(answer)[:120]}")


def main():
    server = get_server()

    c1 = conn(server, "agent_fixed")
    test_fixed(c1)
    c1.close()

    c2 = conn(server, "agent_func")
    test_functional(c2)
    test_poml(c2)
    test_rlm_integrated(c2)
    c2.close()

    c3 = conn(server, "agent_rlm")
    test_rlm(c3)
    c3.close()

    print("\n" + "=" * 60)
    print("汇总")
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
