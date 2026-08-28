-- ============================================================
-- PG-Agent v2 · data_analysis 层
--
-- 依赖（必须先加载）：pg_agent_functional.sql, pg_agent_rlm.sql,
--           pg_agent_workbench_core.sql（da_system_prompt 会渲染 workbench 工具清单）
-- 目标库：da_agent（与 v1 的 agent_func / agent_rlm 隔离）
--
-- 入口 agent_run_data_analysis 只负责建 run（paradigm=data_analysis,
-- max_depth=0），循环走 v2 的 rlm_loop（按 paradigm 选 prompt + 查库门闩）。
-- ============================================================

CREATE OR REPLACE FUNCTION da_qualify(p_name text)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF p_name IS NULL OR trim(p_name) !~ '^[a-zA-Z_][a-zA-Z0-9_]*$' THEN
        RETURN NULL;
    END IF;
    RETURN trim(p_name);
END;
$$;

-- public 基表清单（模型用 SELECT da_list_tables()）
CREATE OR REPLACE FUNCTION da_list_tables()
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'table', c.relname,
               'approx_rows', GREATEST(c.reltuples, 0)::bigint
           ) ORDER BY c.relname), '[]'::jsonb)
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relkind = 'r'
$$;

CREATE OR REPLACE FUNCTION da_show_create(p_table text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_name text := da_qualify(p_table);
    v_cols jsonb;
BEGIN
    IF v_name IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', '非法表名');
    END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'name', column_name,
               'type', data_type,
               'nullable', is_nullable
           ) ORDER BY ordinal_position), '[]'::jsonb)
      INTO v_cols
      FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = v_name;
    IF v_cols = '[]'::jsonb THEN
        RETURN jsonb_build_object('success', false, 'error', '表不存在: ' || v_name);
    END IF;
    RETURN jsonb_build_object('success', true, 'table', v_name, 'columns', v_cols);
END;
$$;

CREATE OR REPLACE FUNCTION da_sample(p_table text, p_n int DEFAULT 5)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_name text := da_qualify(p_table);
    v_n    int := LEAST(GREATEST(COALESCE(p_n, 5), 1), 20);
    v_data jsonb;
BEGIN
    IF v_name IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', '非法表名');
    END IF;
    BEGIN
        EXECUTE format(
            'SELECT COALESCE(jsonb_agg(t), ''[]''::jsonb) FROM (SELECT * FROM public.%I LIMIT %s) t',
            v_name, v_n
        ) INTO v_data;
        RETURN jsonb_build_object(
            'success', true,
            'table', v_name,
            'row_count', jsonb_array_length(v_data),
            'data', v_data
        );
    EXCEPTION WHEN undefined_table THEN
        RETURN jsonb_build_object('success', false, 'error', '表不存在: ' || v_name);
    WHEN OTHERS THEN
        RETURN jsonb_build_object('success', false, 'error', SQLERRM, 'sqlstate', SQLSTATE);
    END;
END;
$$;

CREATE OR REPLACE FUNCTION make_da_prompt(p_max_rows int)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT format($sys$
你是运行在 PostgreSQL 内部的 data_analysis Agent。
只分析当前库里的真实数据。禁止编造表名、列名和数字。

严格按 JSON 回复（不要输出其他文字）：
{"thought":"思考","code":"一条 SELECT 或 WITH","final_answer":"答案或 null"}

规则：
0. code 与 final_answer 互斥：查库轮 final_answer 必须为 null；作答轮 code 必须为 null（不要两者都填）。
1. 每轮最多一条 SQL，必须是 SELECT 或 WITH，不要分号结尾。
2. 数据分析题必须先成功查库，再填 final_answer；没查到就继续查，不要猜。运行时也会拒绝「未查库就作答」。
3. 不知道表/列时，先查 information_schema.tables / columns（当前连接可见的 schema）。
4. 多步计算用 WITH，不要 CREATE / INSERT / UPDATE / DELETE。
5. 查询最多返回 %s 行；过长结果截断，全文写入变量 last_obs。
6. 禁止 rlm_spawn / rlm_map / codeact_spawn。你不能委托子 agent，也不能询问用户。
7. 答案必须能从 observation 里的行推出；数据不足要明说。

REPL API（均在 SELECT 中调用）：
- rlm_query('SELECT ...')          只读查询（也可直接写 SELECT）
- information_schema.tables / columns / pg_catalog
- env_keys() / env_peek / env_search / env_len / env_get
预置变量：question。不要假设你已经读过它的内容。
$sys$, COALESCE(p_max_rows, 50))
$$;

CREATE OR REPLACE FUNCTION da_wrap_obs(p_obs jsonb)
RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_obs IS NULL THEN jsonb_build_object(
            'success', false, 'error', '空 observation',
            'Type', 'SQL_ERROR', 'Phase', 'Execution',
            'Problem', '空 observation',
            'Solution', '重新发出 SELECT。')
        WHEN COALESCE(p_obs->>'success', 'true') = 'true' THEN p_obs
        ELSE p_obs || jsonb_build_object(
            'Type', 'SQL_ERROR',
            'Phase', 'Execution',
            'Problem', COALESCE(p_obs->>'error', 'unknown'),
            'Solution', '修正 SQL。先查 information_schema.tables / columns，不要编造表名。')
    END
$$;

CREATE OR REPLACE FUNCTION da_system_prompt(p_run_id text)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE r record;
BEGIN
    SELECT max_rows INTO r FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'run % 不存在', p_run_id; END IF;
    -- 静态 IMMUTABLE prompt（make_da_prompt）+ 已注册 workbench 工具清单
    RETURN make_da_prompt(COALESCE(r.max_rows, 50)) || render_workbench_tools();
END;
$$;

CREATE OR REPLACE FUNCTION agent_run_data_analysis(
    p_question  text,
    p_context   text DEFAULT NULL,
    p_max_steps int  DEFAULT 10
)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id text := gen_random_uuid()::text;
    v_prev   text := current_setting('rlm.run_id', true);
    v_ans    text;
BEGIN
    IF p_question IS NULL OR trim(p_question) = '' THEN
        RAISE EXCEPTION 'agent_run_data_analysis 需要 p_question';
    END IF;

    INSERT INTO agent_runs (run_id, question, max_steps, paradigm, depth, max_depth, name)
    VALUES (v_run_id, p_question, COALESCE(p_max_steps, 10), 'data_analysis',
            0, 0, 'data_analysis');

    PERFORM set_config('rlm.run_id', v_run_id, false);
    PERFORM env_set_text('question', p_question);
    IF p_context IS NOT NULL AND p_context <> '' THEN
        PERFORM env_set_text('context', p_context);
    END IF;

    v_ans := rlm_loop(v_run_id);
    PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
    RETURN v_ans;
END;
$$;

COMMENT ON FUNCTION agent_run_data_analysis(text, text, int) IS
    '窄 PostgreSQL data_analysis 入口：RLM 循环 + schema-first prompt + max_depth=0，非 InfiniSynapse 协议。';
