-- ============================================================
-- PG-Agent · 函数式 + 元编程重构版
--
-- 阅读顺序即架构顺序：
--   L0 基础设施    —— 扩展、表（只追加，不更新业务状态）
--   L1 组合子      —— regproc 高阶函数：pipe / map / retry
--   L2 纯函数核心  —— 所有"决策"：拼 prompt、解析 LLM 输出（IMMUTABLE）
--   L3 副作用外壳  —— 所有"动作"：HTTP、执行 SQL、落库（VOLATILE）
--   L4 插件层      —— 任务 handler，COMMENT 即注册（元编程）
--   L5 运行时      —— agent 主循环 + worker（只做编排，不含决策）
--
-- 设计口诀：决策是纯函数，动作是薄外壳，编排是数据，注册是注释。
-- ============================================================

-- ============================================================
-- L0. 基础设施
-- ============================================================
CREATE EXTENSION IF NOT EXISTS http;       -- PG13+，gen_random_uuid 内置

DO $$
BEGIN
    PERFORM http_set_curlopt('CURLOPT_TIMEOUT', '90');
EXCEPTION WHEN undefined_function THEN
    RAISE NOTICE 'http_set_curlopt 不可用，跳过';
END $$;

-- LLM 配置（会话级；生产环境建议 ALTER DATABASE ... SET）
-- SET openai.api_uri = 'http://127.0.0.1:11434/v1/';
-- SET openai.api_key = 'none';
-- SET openai.model   = 'qwen2.5';

-- ---------- 任务队列（时间的载体） ----------
CREATE TABLE IF NOT EXISTS jobs (
    job_id       bigserial PRIMARY KEY,
    job_type     text NOT NULL,          -- 查 handler 注册表路由到函数
    payload      jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'PENDING',  -- PENDING/RUNNING/DONE/ERROR
    priority     int  NOT NULL DEFAULT 0,
    run_id       text,                   -- 若属于某个 agent run
    result       jsonb,
    error_msg    text,
    worker_id    text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_jobs_ready
    ON jobs (priority DESC, job_id) WHERE status = 'PENDING';  -- 部分索引：就绪集保持小

-- ---------- Agent 运行 ----------
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      text PRIMARY KEY,
    question    text NOT NULL,
    max_steps   int  NOT NULL DEFAULT 10,
    max_rows    int  NOT NULL DEFAULT 50,
    created_at  timestamptz NOT NULL DEFAULT now()
    -- 注意：没有 status/current_step 字段。
    -- 状态由 steps 流折叠推出（见 L5 的 run_state()），单一事实来源。
);

-- ---------- 步骤流（只追加，空间换可恢复性） ----------
CREATE TABLE IF NOT EXISTS agent_steps (
    run_id     text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    seq        bigserial,                -- 全局有序，天然幂等
    kind       text NOT NULL,            -- 'llm' | 'tool' | 'final' | 'error'
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

-- ============================================================
-- L1. 组合子（函数式的"运行时"）
--     三个通用高阶函数，编排逻辑从此是数据而非控制流。
-- ============================================================

-- 串联：依次执行函数数组，上一步输出作下一步输入
--   SELECT sql_pipe(ARRAY['f1(jsonb)','f2(jsonb)']::regproc[], '{}');
CREATE OR REPLACE FUNCTION sql_pipe(fns regproc[], initial jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    fn regproc;
    v  jsonb := initial;
BEGIN
    FOREACH fn IN ARRAY fns LOOP
        EXECUTE format('SELECT %s($1)', fn) INTO v USING v;
    END LOOP;
    RETURN v;
END;
$$;

-- 映射：对数组每个元素应用同一函数，收集结果
--   SELECT sql_map('process_one(jsonb)', '["a","b"]');
CREATE OR REPLACE FUNCTION sql_map(fn regproc, items jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_out jsonb := '[]'::jsonb;
    v_one jsonb;
    item jsonb;
BEGIN
    FOR item IN SELECT * FROM jsonb_array_elements(items) LOOP
        EXECUTE format('SELECT %s($1)', fn) INTO v_one USING item;
        v_out := v_out || COALESCE(v_one, 'null'::jsonb);
    END LOOP;
    RETURN v_out;
END;
$$;

-- 重试：失败重跑 n 次（副作用函数的外层护甲）
CREATE OR REPLACE FUNCTION sql_retry(fn regprocedure, arg jsonb, times int DEFAULT 2)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v jsonb;
BEGIN
    FOR i IN 1..times LOOP
        BEGIN
            EXECUTE format('SELECT %s($1)', fn::regproc) INTO v USING arg;
            RETURN v;
        EXCEPTION WHEN OTHERS THEN
            IF i = times THEN RAISE; END IF;
            PERFORM pg_sleep(0.2 * i);   -- 简单退避
        END;
    END LOOP;
END;
$$;

-- ============================================================
-- L2. 纯函数核心（所有"决策"都在这里，不碰任何表）
--     IMMUTABLE = 可缓存、可并行、可无库测试。
-- ============================================================

-- 决策 1：构造 system prompt
CREATE OR REPLACE FUNCTION make_system_prompt(p_max_rows int, p_context text DEFAULT NULL)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT format($sys$
你是运行在 PostgreSQL 内部的 AI 数据 Agent。唯一工具是 execute_sql。

严格按此 JSON 回复（不要输出其他文字）：
{"thought":"思考","action":"execute_sql 或 null","action_input":"SQL","final_answer":"答案"}

规则：
1. 需要数据必须先 execute_sql，禁止编造。
2. 一次一条 SQL，不要分号结尾。
3. 查询最多返回 %s 行。
4. 写操作禁止（只读模式）。
5. 信息足够后填 final_answer 并将 action 设为 null。
%2$s
$sys$, p_max_rows,
    CASE WHEN p_context IS NOT NULL AND p_context <> ''
         THEN E'\n【数据库上下文】\n' || p_context || E'\n【上下文结束】'
         ELSE '' END)
$$;

-- 决策 2：解析 LLM 返回 → 统一的"决策记录"类型
DO $$ BEGIN
    CREATE TYPE llm_decision AS (
        thought      text,
        action       text,
        sql          text,
        final_answer text
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION parse_llm_output(p_raw text)
RETURNS llm_decision
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v text := trim(p_raw);
    j jsonb;
    d llm_decision;
BEGIN
    -- 剥 markdown 代码栅栏
    IF v ~ '^```' THEN
        v := trim(regexp_replace(regexp_replace(v, '^```[[:alpha:]]*\s*', ''), '\s*```$', ''));
    END IF;
    -- 宽容提取第一个 JSON 对象
    IF v !~ '^\s*\{' THEN
        v := COALESCE(substring(v from '\{[\s\S]*\}'), '');
    END IF;
    j := v::jsonb;

    d.thought := j ->> 'thought';
    d.action  := NULLIF(NULLIF(trim(COALESCE(j ->> 'action', '')), 'null'), '');
    d.sql     := j ->> 'action_input';
    d.final_answer := NULLIF(NULLIF(trim(COALESCE(j ->> 'final_answer', '')), 'null'), '');
    RETURN d;
END;
$$;

-- 决策 3：由历史步骤折叠出要发给 LLM 的消息数组
--         （这就是"回放"，纯函数：输入步骤流，输出 messages）
CREATE OR REPLACE FUNCTION fold_messages(p_system text, p_question text, p_steps jsonb)
RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_build_array(
               jsonb_build_object('role','system','content',p_system),
               jsonb_build_object('role','user','content',p_question))
        || COALESCE((
            SELECT jsonb_agg(
                CASE s->>'kind'
                    WHEN 'llm'  THEN jsonb_build_object('role','assistant','content',s->'payload'->>'raw')
                    WHEN 'tool' THEN jsonb_build_object('role','user','content','Observation: '||(s->'payload'->>'observation'))
                END ORDER BY (s->>'seq')::bigint)
            FROM jsonb_array_elements(p_steps) s
            WHERE s->>'kind' IN ('llm','tool')
        ), '[]'::jsonb)
$$;

-- ============================================================
-- L3. 副作用外壳（所有"动作"，薄，不含决策）
-- ============================================================

-- 动作 1：HTTP 调用 LLM
CREATE OR REPLACE FUNCTION http_call_llm(p_messages jsonb)
RETURNS jsonb          -- 返回 {'raw': 文本}，便于套 retry 等 jsonb 组合子
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_uri  text := current_setting('openai.api_uri', true);
    v_key  text := current_setting('openai.api_key', true);
    v_mod  text := current_setting('openai.model', true);
    v_resp http_response;
    v_out  text;
BEGIN
    IF v_uri IS NULL OR v_mod IS NULL THEN
        RAISE EXCEPTION '请先 SET openai.api_uri / openai.model';
    END IF;

    SELECT * INTO v_resp FROM http((
        'POST',
        rtrim(v_uri,'/') || '/chat/completions',
        ARRAY[http_header('Content-Type','application/json'),
              http_header('Authorization','Bearer '||COALESCE(v_key,'none'))],
        'application/json',
        jsonb_build_object('model', v_mod, 'messages', p_messages,
                           'temperature', 0.1,
                           'response_format', jsonb_build_object('type','json_object'))::text
    )::http_request);

    IF v_resp.status <> 200 THEN
        RAISE EXCEPTION 'LLM 调用失败 [%]: %', v_resp.status, left(v_resp.content, 500);
    END IF;
    v_out := (v_resp.content::jsonb)->'choices'->0->'message'->>'content';
    IF v_out IS NULL OR trim(v_out) = '' THEN RAISE EXCEPTION 'LLM 返回为空'; END IF;
    RETURN jsonb_build_object('raw', v_out);
END;
$$;

-- 动作 2：安全执行 SQL（只读；关键字黑名单；结果转 jsonb）
CREATE OR REPLACE FUNCTION exec_sql_readonly(p_sql text, p_max_rows int DEFAULT 50)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_sql  text := rtrim(trim(COALESCE(p_sql,'')), ';');
    v_low  text := lower(v_sql);
    v_data jsonb;
    v_forbidden text[] := ARRAY['drop','truncate','alter','create','grant','revoke',
        'copy','execute','call','do','vacuum','analyze','reindex','cluster',
        'discard','lock','set','reset','load','listen','notify','unlisten',
        'insert','update','delete','merge'];
    kw text;
BEGIN
    IF v_sql = '' THEN
        RETURN jsonb_build_object('success',false,'error','SQL 为空');
    END IF;
    IF v_sql ~ ';' THEN
        RETURN jsonb_build_object('success',false,'error','禁止多语句');
    END IF;
    FOREACH kw IN ARRAY v_forbidden LOOP
        IF v_low ~ ('\m'||kw||'\M') THEN
            RETURN jsonb_build_object('success',false,'error','禁止关键字: '||kw);
        END IF;
    END LOOP;

    BEGIN
        EXECUTE format('SELECT COALESCE(jsonb_agg(t),''[]''::jsonb) FROM (%s LIMIT %s) t',
                       v_sql, p_max_rows)
           INTO v_data;
        RETURN jsonb_build_object('success',true,'data',v_data,
                                  'row_count', jsonb_array_length(v_data));
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object('success',false,'error',SQLERRM,'sqlstate',SQLSTATE);
    END;
END;
$$;

-- 动作 3：追加一个步骤（唯一的"写"，Append-only）
CREATE OR REPLACE FUNCTION emit_step(p_run_id text, p_kind text, p_payload jsonb)
RETURNS void
LANGUAGE sql VOLATILE AS $$
    INSERT INTO agent_steps (run_id, kind, payload) VALUES (p_run_id, p_kind, p_payload);
$$;

-- ============================================================
-- L4. 插件层：handler + 元编程注册
--     约定：所有 handler 签名统一为 (p_job jobs) RETURNS void
--     注册方式：给函数写 COMMENT，refresh_handlers() 扫描 catalog 生成注册表。
--     新增插件 = 写一个函数 + 一行注释，其他任何文件都不用动。
-- ============================================================

CREATE TABLE IF NOT EXISTS handlers (
    job_type text PRIMARY KEY,
    fn       regproc NOT NULL
);

-- 元编程：扫描函数注释，重建注册表
CREATE OR REPLACE FUNCTION refresh_handlers()
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    n int;
BEGIN
    TRUNCATE handlers;
    INSERT INTO handlers (job_type, fn)
    SELECT obj_description(p.oid, 'pg_proc')::jsonb ->> 'job_handler',
           p.oid::regproc
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND obj_description(p.oid, 'pg_proc') ~ '^\s*\{'
       AND obj_description(p.oid, 'pg_proc')::jsonb ? 'job_handler';
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

-- ---------- 插件 1：抓取所有表结构 ----------
CREATE OR REPLACE FUNCTION h_schema_all_tables(p_job jobs)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v jsonb;
BEGIN
    v := exec_sql_readonly($q$
        SELECT jsonb_agg(jsonb_build_object(
            'table', table_name,
            'columns', (SELECT jsonb_agg(jsonb_build_object(
                'name', column_name, 'type', data_type))
              FROM information_schema.columns c2
             WHERE c2.table_name = c1.table_name
               AND c2.table_schema = c1.table_schema)))
          FROM information_schema.tables c1
         WHERE table_schema='public' AND table_type='BASE TABLE'
        $q$, 1);
    UPDATE jobs SET status='DONE', result=v, completed_at=now()
     WHERE job_id = p_job.job_id;
END;
$$;
COMMENT ON FUNCTION h_schema_all_tables(jobs) IS '{"job_handler":"schema_all_tables"}';

-- ---------- 插件 2：抓取某表样本 ----------
CREATE OR REPLACE FUNCTION h_sample_table(p_job jobs)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v jsonb;
BEGIN
    v := exec_sql_readonly(
        format('SELECT jsonb_agg(t) FROM (SELECT * FROM %I LIMIT 3) t',
               p_job.payload->>'target_table'), 1);
    UPDATE jobs SET status='DONE', result=v, completed_at=now()
     WHERE job_id = p_job.job_id;
END;
$$;
COMMENT ON FUNCTION h_sample_table(jobs) IS '{"job_handler":"sample_table"}';

-- ---------- 插件 3：运行一个完整 agent（把 agent_run 也变成插件） ----------
CREATE OR REPLACE FUNCTION h_agent_run(p_job jobs)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    v := agent_run(p_job.payload->>'question',
                   COALESCE((p_job.payload->>'max_steps')::int, 10));
    UPDATE jobs SET status='DONE', result=jsonb_build_object('answer',v),
                run_id = (SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1),
                completed_at=now()
     WHERE job_id = p_job.job_id;
END;
$$;
COMMENT ON FUNCTION h_agent_run(jobs) IS '{"job_handler":"agent_run"}';

SELECT refresh_handlers();   -- 部署时执行一次；以后每加插件重跑一次

-- ============================================================
-- L5. 运行时（只编排，不含决策）
-- ============================================================

-- 状态折叠：从步骤流推出 run 的当前状态（单一事实来源）
CREATE OR REPLACE FUNCTION run_state(p_run_id text)
RETURNS TABLE(status text, steps_used int, answer text, error text)
LANGUAGE sql STABLE AS $$
    SELECT CASE
             WHEN bool_or(kind='final') THEN 'SUCCESS'
             WHEN bool_or(kind='error') THEN 'ERROR'
             ELSE 'RUNNING'
           END,
           count(*) FILTER (WHERE kind='llm')::int,
           max(payload->>'answer') FILTER (WHERE kind='final'),
           max(payload->>'message') FILTER (WHERE kind='error')
      FROM agent_steps
     WHERE run_id = p_run_id
$$;

-- Agent 主循环：循环体 = 纯函数决策 + 外壳动作，一眼能读完
CREATE OR REPLACE FUNCTION agent_run(p_question text, p_max_steps int DEFAULT 10)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id  text := gen_random_uuid()::text;
    v_dec     llm_decision;
    v_raw     text;
    v_msgs    jsonb;
    v_system  text;
    v_steps   jsonb;
    v_used    int := 0;
    v_obs     jsonb;
BEGIN
    INSERT INTO agent_runs (run_id, question, max_steps)
    VALUES (v_run_id, p_question, p_max_steps);

    v_system := make_system_prompt(50);   -- L2 纯函数

    WHILE v_used < p_max_steps LOOP
        -- ① 折叠历史 → messages（纯）
        SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                                  ORDER BY seq), '[]'::jsonb)
          INTO v_steps FROM agent_steps WHERE run_id = v_run_id;
        v_msgs := fold_messages(v_system, p_question, v_steps);

        -- ② 调用 LLM（外壳 + retry 组合子护甲）
        v_raw := sql_retry('http_call_llm(jsonb)'::regprocedure, v_msgs, 2) ->> 'raw';

        -- ③ 解析决策（纯）
        BEGIN
            v_dec := parse_llm_output(v_raw);
        EXCEPTION WHEN OTHERS THEN
            PERFORM emit_step(v_run_id, 'error',
                    jsonb_build_object('message','LLM 返回非法 JSON: '||left(v_raw,300)));
            RETURN '失败：LLM 返回非法 JSON，run_id=' || v_run_id;
        END;
        PERFORM emit_step(v_run_id, 'llm', jsonb_build_object('raw', v_raw, 'thought', v_dec.thought));
        v_used := v_used + 1;

        -- ④ 路由：终局 or 工具
        IF v_dec.final_answer IS NOT NULL AND v_dec.action IS NULL THEN
            PERFORM emit_step(v_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
            RETURN v_dec.final_answer;
        END IF;

        IF v_dec.action = 'execute_sql' THEN
            v_obs := exec_sql_readonly(v_dec.sql, 50);
        ELSE
            v_obs := jsonb_build_object('success',false,'error','未知 action: '||COALESCE(v_dec.action,'null'));
        END IF;
        PERFORM emit_step(v_run_id, 'tool', jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text));
    END LOOP;

    PERFORM emit_step(v_run_id, 'error', jsonb_build_object('message','达到最大步数'));
    RETURN '达到最大步数，run_id=' || v_run_id;
END;
$$;

-- Worker：dispatch 由 handlers 表驱动，不含任何 IF 链
CREATE OR REPLACE FUNCTION worker(p_worker_id text DEFAULT 'worker-'||gen_random_uuid()::text)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_job jobs;
    v_fn  regproc;
BEGIN
    LOOP
        SELECT * INTO v_job FROM jobs
         WHERE status='PENDING'
         ORDER BY priority DESC, job_id
         FOR UPDATE SKIP LOCKED LIMIT 1;
        IF NOT FOUND THEN RETURN format('Worker %s: 队列已空', p_worker_id); END IF;

        UPDATE jobs SET status='RUNNING', worker_id=p_worker_id WHERE job_id=v_job.job_id;

        SELECT fn INTO v_fn FROM handlers WHERE job_type = v_job.job_type;
        BEGIN
            IF v_fn IS NULL THEN
                RAISE EXCEPTION '未注册的 job_type: %', v_job.job_type;
            END IF;
            EXECUTE format('SELECT %s($1)', v_fn) USING v_job;
        EXCEPTION WHEN OTHERS THEN
            UPDATE jobs SET status='ERROR', error_msg=SQLERRM, completed_at=now()
             WHERE job_id=v_job.job_id;
            RAISE WARNING '任务 % 失败: %', v_job.job_id, SQLERRM;
        END;
    END LOOP;
END;
$$;

-- ============================================================
-- 使用示例
-- ============================================================
-- SET openai.api_uri='http://127.0.0.1:11434/v1/'; SET openai.model='qwen2.5';
--
-- -- 直接跑一个 agent：
-- SELECT agent_run('public 模式下行数最多的表是哪个？');
--
-- -- 或走队列 + 并行 worker：
-- INSERT INTO jobs (job_type, payload) VALUES
--   ('schema_all_tables', '{}'),
--   ('sample_table', '{"target_table":"agent_runs"}'),
--   ('agent_run', '{"question":"有多少张表？"}');
-- SELECT worker();   -- 开多个会话并行执行即为多 worker
--
-- -- 查看 run 状态（折叠出来的，不存冗余字段）：
-- SELECT * FROM run_state('某-run-id');
--
-- -- 加新插件后重建注册表：
-- SELECT refresh_handlers();
