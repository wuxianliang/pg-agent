-- =============================================
-- 1. 扩展 & 配置
-- =============================================
CREATE EXTENSION IF NOT EXISTS http;          -- 需要超级用户/云平台白名单
-- gen_random_uuid() 在 PG13+ 为内置；PG12 及以下需 CREATE EXTENSION pgcrypto;

-- 兼容处理：若 http_set_curlopt 不存在则静默跳过
DO $$
BEGIN
    PERFORM http_set_curlopt('CURLOPT_TIMEOUT', '90');
EXCEPTION WHEN undefined_function THEN
    RAISE NOTICE 'http_set_curlopt 不可用，跳过超时设置';
END $$;

-- LLM 配置（按需修改）
-- SET openai.api_uri = 'http://127.0.0.1:11434/v1/';
-- SET openai.api_key = 'none';
-- SET openai.model   = 'qwen2.5';

-- =============================================
-- 2. 上下文存储表（Context in Database）
-- =============================================
CREATE TABLE IF NOT EXISTS context_segments (
    segment_id      serial PRIMARY KEY,
    build_id        text NOT NULL,
    segment_type    text NOT NULL,
    source_table    text,
    content         text NOT NULL,
    content_json    jsonb,
    token_estimate  int DEFAULT 0,
    priority        int DEFAULT 0,
    created_at      timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ctx_seg_build ON context_segments(build_id);
CREATE INDEX IF NOT EXISTS idx_ctx_seg_type ON context_segments(segment_type, build_id);

CREATE TABLE IF NOT EXISTS context_builds (
    build_id        text PRIMARY KEY,
    target_database text,
    description     text,
    status          text DEFAULT 'PENDING',     -- PENDING/QUEUED/BUILDING/DONE/ERROR
    total_segments  int DEFAULT 0,
    created_at      timestamptz DEFAULT now(),
    completed_at    timestamptz
);

-- =============================================
-- 3. Agent 核心表
-- =============================================
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          text PRIMARY KEY,
    question        text NOT NULL,
    context_build_id text REFERENCES context_builds(build_id),
    status          text NOT NULL DEFAULT 'PENDING',
    current_step    int  NOT NULL DEFAULT 0,
    final_answer    text,
    error_message   text,
    max_steps       int  NOT NULL DEFAULT 10,
    max_rows        int  NOT NULL DEFAULT 50,
    allow_writes    boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_steps (
    run_id          text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    step_no         int  NOT NULL,
    step_type       text NOT NULL,          -- 'llm' | 'tool'
    input_data      jsonb,
    output_data     jsonb,
    thought         text,
    action          text,
    observation     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, step_no)
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_agent_steps_run_id ON agent_steps(run_id);

-- =============================================
-- 4. 并行任务队列
-- =============================================
CREATE TABLE IF NOT EXISTS agent_jobs (
    job_id          bigserial PRIMARY KEY,
    build_id        text,
    run_id          text,
    job_type        text NOT NULL,
    task_name       text NOT NULL,
    payload         jsonb DEFAULT '{}',
    status          text DEFAULT 'PENDING', -- PENDING/RUNNING/DONE/ERROR
    priority        int DEFAULT 0,
    parent_job_id   bigint REFERENCES agent_jobs(job_id),
    result          text,
    result_json     jsonb,
    error_msg       text,
    worker_id       text,
    created_at      timestamptz DEFAULT now(),
    started_at      timestamptz,
    completed_at    timestamptz
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON agent_jobs(status, priority, job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_build ON agent_jobs(build_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_parent ON agent_jobs(parent_job_id);

-- =============================================
-- 5. Cordis 风格服务注册表
-- =============================================
CREATE TABLE IF NOT EXISTS cordis_services (
    service_id      serial PRIMARY KEY,
    service_name    text UNIQUE NOT NULL,
    provider_run_id text,
    config          jsonb DEFAULT '{}',
    is_default      boolean DEFAULT true,
    created_at      timestamptz DEFAULT now()
);

-- =============================================
-- 6. 安全 SQL 执行工具
-- =============================================
CREATE OR REPLACE FUNCTION execute_sql_safe(
    p_sql       text,
    p_max_rows  int     DEFAULT 50,
    p_allow_writes boolean DEFAULT false
)
RETURNS jsonb
LANGUAGE plpgsql
-- 注意：默认 SECURITY INVOKER 更安全；确需统一提权再加 SECURITY DEFINER
AS $$
DECLARE
    v_sql       text;
    v_lower     text;
    v_result    jsonb;
    v_rowcount  bigint;
    v_forbidden text[] := ARRAY[
        'drop', 'truncate', 'alter', 'create', 'grant', 'revoke',
        'copy', 'execute', 'call', 'do', 'vacuum', 'analyze',
        'reindex', 'cluster', 'discard', 'lock', 'set role',
        'reset role', 'load', 'listen', 'notify', 'unlisten'
    ];
    kw          text;
BEGIN
    IF p_sql IS NULL OR trim(p_sql) = '' THEN
        RETURN jsonb_build_object('success', false, 'error', 'SQL 不能为空');
    END IF;

    v_sql := trim(p_sql);
    v_sql := rtrim(v_sql, ';');
    IF v_sql ~ ';' THEN
        RETURN jsonb_build_object(
            'success', false,
            'error', '禁止执行多条 SQL 语句'
        );
    END IF;

    v_lower := lower(v_sql);

    FOREACH kw IN ARRAY v_forbidden LOOP
        IF v_lower ~ ('\m' || kw || '\M') THEN
            RETURN jsonb_build_object(
                'success', false,
                'error', format('禁止使用危险关键字: %s', kw)
            );
        END IF;
    END LOOP;

    IF NOT p_allow_writes THEN
        IF v_lower ~ '\m(insert|update|delete|merge)\M' THEN
            RETURN jsonb_build_object(
                'success', false,
                'error', '当前模式禁止写操作'
            );
        END IF;
    END IF;

    BEGIN
        IF v_lower ~ '^\s*select\b' OR v_lower ~ '^\s*with\b' THEN
            EXECUTE format(
                'SELECT COALESCE(jsonb_agg(t), ''[]''::jsonb) FROM (%s LIMIT %s) t',
                v_sql, p_max_rows
            ) INTO v_result;

            v_rowcount := COALESCE(jsonb_array_length(v_result), 0);

            RETURN jsonb_build_object(
                'success', true,
                'type', 'query',
                'row_count', v_rowcount,
                'max_rows_limit', p_max_rows,
                'data', v_result,
                'truncated', v_rowcount >= p_max_rows  -- 注意：恰好满额也会标记
            );
        ELSE
            EXECUTE v_sql;
            GET DIAGNOSTICS v_rowcount = ROW_COUNT;
            RETURN jsonb_build_object(
                'success', true,
                'type', 'dml',
                'row_count', v_rowcount,
                'message', format('成功影响 %s 行', v_rowcount)
            );
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false,
            'error', SQLERRM,
            'sqlstate', SQLSTATE
        );
    END;
END;
$$;

-- =============================================
-- 7. LLM 调用
-- =============================================
CREATE OR REPLACE FUNCTION call_llm(p_messages jsonb)
RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_uri     text := current_setting('openai.api_uri', true);
    v_key     text := current_setting('openai.api_key', true);
    v_model   text := current_setting('openai.model', true);
    v_body    text;
    v_resp    http_response;
    v_content text;
BEGIN
    IF v_uri IS NULL OR v_model IS NULL THEN
        RAISE EXCEPTION '请先执行: SET openai.api_uri / openai.api_key / openai.model';
    END IF;

    v_body := jsonb_build_object(
        'model', v_model,
        'messages', p_messages,
        'temperature', 0.1,
        'response_format', jsonb_build_object('type', 'json_object')
    )::text;

    SELECT * INTO v_resp
    FROM http((
        'POST',
        rtrim(v_uri, '/') || '/chat/completions',
        ARRAY[
            http_header('Content-Type', 'application/json'),
            http_header('Authorization', 'Bearer ' || COALESCE(v_key, 'none'))
        ],
        'application/json',
        v_body
    )::http_request);

    IF v_resp.status <> 200 THEN
        RAISE EXCEPTION 'LLM 调用失败 [%]: %', v_resp.status, left(v_resp.content, 500);
    END IF;

    v_content := (v_resp.content::jsonb) -> 'choices' -> 0 -> 'message' ->> 'content';
    IF v_content IS NULL OR trim(v_content) = '' THEN
        RAISE EXCEPTION 'LLM 返回内容为空';
    END IF;
    RETURN v_content;
END;
$$;

-- =============================================
-- 8. 上下文检索函数
-- =============================================
CREATE OR REPLACE FUNCTION get_context_for_agent(
    p_build_id text,
    p_segment_types text[] DEFAULT ARRAY['schema', 'sample', 'stats'],
    p_max_tokens int DEFAULT 4000
)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_tokens int := 0;
    v_seg record;
    v_parts text[] := ARRAY[]::text[];
BEGIN
    FOR v_seg IN
        SELECT segment_type, content, token_estimate
        FROM context_segments
        WHERE build_id = p_build_id
          AND segment_type = ANY(p_segment_types)
        ORDER BY priority DESC, segment_type, segment_id
    LOOP
        IF v_total_tokens + COALESCE(v_seg.token_estimate, 100) > p_max_tokens THEN
            EXIT;
        END IF;
        v_parts := array_append(v_parts, format('[%s] %s', v_seg.segment_type, v_seg.content));
        v_total_tokens := v_total_tokens + COALESCE(v_seg.token_estimate, 100);
    END LOOP;

    RETURN array_to_string(v_parts, E'\n---\n');
END;
$$;

-- =============================================
-- 9. 可恢复 Agent 主函数
-- =============================================
CREATE OR REPLACE FUNCTION run_agent_sql(
    p_run_id       text    DEFAULT NULL,
    p_question     text    DEFAULT NULL,
    p_context_build_id text DEFAULT NULL,
    p_max_steps    int     DEFAULT 10,
    p_allow_writes boolean DEFAULT false,
    p_max_rows     int     DEFAULT 50
)
RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_run_id      text;
    v_status      text;
    v_step        int := 0;          -- 当前已用 LLM 步数
    v_step_seq    int := 0;          -- agent_steps 序号（含 tool 步）
    v_max_steps   int;
    v_max_rows    int;
    v_question    text;
    v_allow_writes boolean;
    v_context_build_id text;
    v_context     text;
    v_messages    jsonb := '[]'::jsonb;
    v_system      text;
    v_response    text;
    v_clean_resp  text;
    v_json        jsonb;
    v_thought     text;
    v_action      text;
    v_sql         text;
    v_final       text;
    v_observation jsonb;
    v_obs_text    text;
    r             record;
BEGIN
    -- ---------- 初始化 / 恢复 ----------
    IF p_run_id IS NULL THEN
        IF p_question IS NULL OR trim(p_question) = '' THEN
            RAISE EXCEPTION '新建时必须提供 p_question';
        END IF;

        v_run_id := gen_random_uuid()::text;
        INSERT INTO agent_runs (run_id, question, context_build_id, status, max_steps, max_rows, allow_writes)
        VALUES (v_run_id, p_question, p_context_build_id, 'RUNNING', p_max_steps, p_max_rows, p_allow_writes);

        v_question     := p_question;
        v_max_steps    := p_max_steps;
        v_max_rows     := p_max_rows;
        v_allow_writes := p_allow_writes;
        v_context_build_id := p_context_build_id;
        v_step         := 0;
    ELSE
        SELECT status, question, max_steps, max_rows, allow_writes, context_build_id
          INTO v_status, v_question, v_max_steps, v_max_rows, v_allow_writes, v_context_build_id
          FROM agent_runs
         WHERE run_id = p_run_id
         FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'run_id % 不存在', p_run_id;
        END IF;

        IF v_status IN ('SUCCESS', 'CANCELLED') THEN
            RETURN COALESCE(
                (SELECT final_answer FROM agent_runs WHERE run_id = p_run_id),
                '已结束，状态: ' || v_status
            );
        END IF;

        v_run_id := p_run_id;
        UPDATE agent_runs SET status = 'RUNNING', updated_at = now() WHERE run_id = v_run_id;
    END IF;

    -- 已用的 LLM 步数 / 总步序号
    SELECT count(*) FILTER (WHERE step_type = 'llm'),
           COALESCE(max(step_no), 0)
      INTO v_step, v_step_seq
      FROM agent_steps
     WHERE run_id = v_run_id;

    -- ---------- 加载上下文 ----------
    IF v_context_build_id IS NOT NULL THEN
        v_context := get_context_for_agent(v_context_build_id);
    END IF;

    -- ---------- System Prompt ----------
    v_system := format($sys$
你是运行在 PostgreSQL 内部的 AI 数据 Agent。
你只能使用唯一的工具 execute_sql 来查询或修改数据。

必须严格按照以下 JSON 格式回复（不要输出任何其他文字）：

{
  "thought": "你的思考过程",
  "action": "execute_sql 或 null",
  "action_input": "完整的 SQL 语句",
  "final_answer": "最终给用户的答案"
}

规则：
1. 需要数据时，必须先通过 execute_sql 获取，禁止编造数据。
2. 一次只生成一条 SQL，不要以分号结尾。
3. 查询结果最多返回 %s 行。
4. 当前写操作权限：%s
5. 得到足够信息后，把 final_answer 填上，action 设为 null。
$sys$, v_max_rows, CASE WHEN v_allow_writes THEN '允许' ELSE '禁止（只读）' END);

    IF v_context IS NOT NULL AND v_context != '' THEN
        v_system := v_system || E'\n\n【数据库上下文】\n' || v_context || E'\n【上下文结束】\n';
    END IF;

    v_messages := v_messages
        || jsonb_build_object('role', 'system', 'content', v_system)
        || jsonb_build_object('role', 'user',   'content', v_question);

    -- ---------- 回放历史 ----------
    FOR r IN
        SELECT step_no, step_type, output_data, observation
          FROM agent_steps
         WHERE run_id = v_run_id
         ORDER BY step_no
    LOOP
        IF r.step_type = 'llm' THEN
            v_messages := v_messages || jsonb_build_object(
                'role', 'assistant',
                'content', r.output_data ->> 'raw_response'
            );
        ELSIF r.step_type = 'tool' THEN
            v_messages := v_messages || jsonb_build_object(
                'role', 'user',
                'content', 'Observation: ' || COALESCE(r.observation, r.output_data::text)
            );
        END IF;
    END LOOP;

    -- ---------- 主循环（仅 LLM 步计入 max_steps） ----------
    WHILE v_step < v_max_steps LOOP
        v_step := v_step + 1;
        v_step_seq := v_step_seq + 1;
        RAISE NOTICE '[%] LLM Step % (seq %)', v_run_id, v_step, v_step_seq;

        BEGIN
            v_response := call_llm(v_messages);
        EXCEPTION WHEN OTHERS THEN
            UPDATE agent_runs SET status = 'ERROR', error_message = SQLERRM, updated_at = now()
            WHERE run_id = v_run_id;
            RAISE;
        END;

        BEGIN
            v_clean_resp := trim(v_response);
            IF v_clean_resp ~ '^```' THEN
                v_clean_resp := regexp_replace(v_clean_resp, '^```[[:alpha:]]*\s*', '');
                v_clean_resp := regexp_replace(v_clean_resp, '\s*```$', '');
                v_clean_resp := trim(v_clean_resp);
            END IF;
            IF v_clean_resp !~ '^\s*\{' THEN
                v_clean_resp := COALESCE(substring(v_clean_resp from '\{[\s\S]*\}'), '');
            END IF;
            v_json := v_clean_resp::jsonb;
        EXCEPTION WHEN OTHERS THEN
            UPDATE agent_runs SET status = 'ERROR',
                error_message = 'LLM 返回非法 JSON: ' || left(v_response, 300),
                updated_at = now()
            WHERE run_id = v_run_id;
            RAISE EXCEPTION 'LLM 返回非法 JSON';
        END;

        v_thought := v_json ->> 'thought';
        v_action  := NULLIF(trim(COALESCE(v_json ->> 'action', '')), 'null');
        v_action  := NULLIF(v_action, '');
        v_sql     := v_json ->> 'action_input';
        v_final   := NULLIF(NULLIF(trim(COALESCE(v_json ->> 'final_answer', '')), 'null'), '');

        INSERT INTO agent_steps (run_id, step_no, step_type, output_data, thought, action)
        VALUES (v_run_id, v_step_seq, 'llm',
            jsonb_build_object('raw_response', v_response),
            v_thought, v_action
        );
        UPDATE agent_runs SET current_step = v_step_seq, updated_at = now() WHERE run_id = v_run_id;

        IF v_final IS NOT NULL AND v_action IS NULL THEN
            UPDATE agent_runs
               SET status = 'SUCCESS', final_answer = v_final, updated_at = now()
             WHERE run_id = v_run_id;
            RETURN v_final;
        END IF;

        IF v_action = 'execute_sql' THEN
            v_observation := execute_sql_safe(v_sql, v_max_rows, v_allow_writes);
        ELSE
            v_observation := jsonb_build_object('success', false, 'error', '未知 action: ' || COALESCE(v_action, 'null'));
        END IF;
        v_obs_text := v_observation::text;

        v_step_seq := v_step_seq + 1;
        INSERT INTO agent_steps (run_id, step_no, step_type, input_data, output_data, observation, action)
        VALUES (v_run_id, v_step_seq, 'tool',
            jsonb_build_object('sql', v_sql),
            v_observation, v_obs_text, 'execute_sql'
        );
        UPDATE agent_runs SET current_step = v_step_seq, updated_at = now() WHERE run_id = v_run_id;

        v_messages := v_messages
            || jsonb_build_object('role', 'assistant', 'content', v_response)
            || jsonb_build_object('role', 'user', 'content', 'Observation: ' || v_obs_text);
    END LOOP;

    UPDATE agent_runs
       SET status = 'ERROR', error_message = '达到最大步数限制', updated_at = now()
     WHERE run_id = v_run_id;

    RETURN format('达到最大步数（%s），未能完成。run_id = %s', v_max_steps, v_run_id);
END;
$$;

-- =============================================
-- 10. 上下文构建任务（单任务，供 Worker 调用）
-- =============================================
CREATE OR REPLACE FUNCTION context_retrieve_task(
    p_job_id bigint,
    p_build_id text,
    p_task_name text,
    p_payload jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_sql text;
    v_result jsonb;
    v_content text;
    v_token_est int;
BEGIN
    -- 修正：sample 任务名是 'sample_data_' || 表名，用 LIKE 匹配
    CASE
        WHEN p_task_name = 'schema_all_tables' THEN
            v_sql := $q$
                SELECT jsonb_agg(jsonb_build_object(
                    'table', table_name,
                    'columns', (SELECT jsonb_agg(jsonb_build_object(
                        'name', column_name,
                        'type', data_type,
                        'nullable', is_nullable
                    )) FROM information_schema.columns c2
                    WHERE c2.table_name = c1.table_name AND c2.table_schema = c1.table_schema)
                )) FROM information_schema.tables c1
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            $q$;

        WHEN p_task_name = 'table_stats' THEN
            v_sql := $q$
                SELECT jsonb_agg(jsonb_build_object(
                    'table', relname,
                    'rows', n_live_tup,
                    'size', pg_size_pretty(pg_total_relation_size(relid))
                )) FROM pg_stat_user_tables
            $q$;

        WHEN p_task_name LIKE 'sample_data%' THEN
            v_sql := format($q$
                SELECT jsonb_agg(t) FROM (
                    SELECT * FROM %I LIMIT 3
                ) t
            $q$, p_payload->>'target_table');

        ELSE
            v_sql := p_payload->>'custom_sql';
    END CASE;

    v_result := execute_sql_safe(v_sql, 100, false);

    IF (v_result->>'success')::boolean THEN
        v_content := v_result->>'data';
        v_token_est := length(v_content) / 4;

        INSERT INTO context_segments (build_id, segment_type, source_table, content, content_json, token_estimate)
        VALUES (p_build_id,
                COALESCE(p_payload->>'segment_type', 'custom'),
                p_payload->>'target_table',
                v_content,
                v_result,
                v_token_est);

        UPDATE agent_jobs
        SET status = 'DONE', result = v_content, result_json = v_result, completed_at = now()
        WHERE job_id = p_job_id;
    ELSE
        UPDATE agent_jobs
        SET status = 'ERROR', error_msg = v_result->>'error', completed_at = now()
        WHERE job_id = p_job_id;
    END IF;
END;
$$;

-- =============================================
-- 11. 并行 Worker
-- =============================================
CREATE OR REPLACE FUNCTION agent_worker(
    p_worker_id text DEFAULT 'worker-' || gen_random_uuid()::text
)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_job record;
    v_answer text;
    v_run_id text;
BEGIN
    LOOP
        SELECT * INTO v_job
        FROM agent_jobs
        WHERE status = 'PENDING'
          AND (parent_job_id IS NULL OR
               EXISTS (SELECT 1 FROM agent_jobs j2
                       WHERE j2.job_id = agent_jobs.parent_job_id AND j2.status = 'DONE'))
        ORDER BY priority DESC, job_id
        FOR UPDATE SKIP LOCKED
        LIMIT 1;

        IF NOT FOUND THEN
            RETURN format('Worker %s: 没有更多任务', p_worker_id);
        END IF;

        UPDATE agent_jobs
        SET status = 'RUNNING', started_at = now(), worker_id = p_worker_id
        WHERE job_id = v_job.job_id;

        BEGIN
            IF v_job.job_type = 'context_retrieve' THEN
                PERFORM context_retrieve_task(v_job.job_id, v_job.build_id, v_job.task_name, v_job.payload);

            ELSIF v_job.job_type = 'agent_run' THEN
                v_run_id := COALESCE(v_job.run_id, gen_random_uuid()::text);

                SELECT run_agent_sql(
                    p_run_id := v_run_id,
                    p_question := v_job.payload->>'question',
                    p_context_build_id := v_job.build_id,
                    p_max_steps := COALESCE((v_job.payload->>'max_steps')::int, 10)
                ) INTO v_answer;

                UPDATE agent_jobs
                SET status = 'DONE', result = v_answer, run_id = v_run_id, completed_at = now()
                WHERE job_id = v_job.job_id;

            ELSIF v_job.job_type = 'synthesize' THEN
                v_answer := run_agent_sql(
                    p_question := v_job.payload->>'question' || E'\n\n' || COALESCE((
                        SELECT string_agg(format('[%s] %s', task_name, COALESCE(result, '无结果')), E'\n---\n')
                        FROM agent_jobs
                        WHERE build_id = v_job.build_id
                          AND parent_job_id = v_job.parent_job_id
                          AND status = 'DONE'
                    ), '（无子任务结果）'),
                    p_context_build_id := v_job.build_id,
                    p_max_steps := 5
                );

                UPDATE agent_jobs
                SET status = 'DONE', result = v_answer, completed_at = now()
                WHERE job_id = v_job.job_id;
            END IF;

        EXCEPTION WHEN OTHERS THEN
            UPDATE agent_jobs
            SET status = 'ERROR', error_msg = SQLERRM, completed_at = now()
            WHERE job_id = v_job.job_id;
            RAISE WARNING 'Worker % 任务 % 失败: %', p_worker_id, v_job.job_id, SQLERRM;
        END;
    END LOOP;
END;
$$;

-- =============================================
-- 12. 上下文并行构建器（Map 阶段）
-- =============================================
CREATE OR REPLACE FUNCTION build_context_parallel(
    p_description text DEFAULT '自动构建数据库上下文',
    p_worker_count int DEFAULT 3
)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_build_id text;
    v_tables text[];
    v_t text;
    v_limit int;
BEGIN
    v_build_id := gen_random_uuid()::text;

    INSERT INTO context_builds (build_id, description, status)
    VALUES (v_build_id, p_description, 'QUEUED');

    -- Map 阶段：提交并行检索任务
    INSERT INTO agent_jobs (build_id, job_type, task_name, payload, priority)
    VALUES (v_build_id, 'context_retrieve', 'schema_all_tables',
            '{"segment_type":"schema"}'::jsonb, 10);

    INSERT INTO agent_jobs (build_id, job_type, task_name, payload, priority)
    VALUES (v_build_id, 'context_retrieve', 'table_stats',
            '{"segment_type":"stats"}'::jsonb, 9);

    SELECT array_agg(table_name) INTO v_tables
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

    IF v_tables IS NOT NULL THEN
        v_limit := least(array_length(v_tables, 1), 5);
        FOREACH v_t IN ARRAY v_tables[1:v_limit] LOOP
            INSERT INTO agent_jobs (build_id, job_type, task_name, payload, priority)
            VALUES (v_build_id, 'context_retrieve', 'sample_data_' || v_t,
                    jsonb_build_object('segment_type', 'sample', 'target_table', v_t), 5);
        END LOOP;
    END IF;

    -- 注意：此处不再提前置 DONE。
    -- 请并行启动 p_worker_count 个会话执行 SELECT agent_worker();
    -- 全部任务结束后调用 finalize_context_build(build_id) 收尾。
    RETURN v_build_id;
END;
$$;

-- =============================================
-- 12b. 构建收尾（Reduce 阶段）
-- =============================================
CREATE OR REPLACE FUNCTION finalize_context_build(p_build_id text)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_unfinished int;
    v_total int;
BEGIN
    SELECT count(*) INTO v_unfinished
    FROM agent_jobs
    WHERE build_id = p_build_id AND status NOT IN ('DONE', 'ERROR');

    IF v_unfinished > 0 THEN
        RETURN format('构建 %s 仍有 %s 个任务未完成', p_build_id, v_unfinished);
    END IF;

    SELECT count(*) INTO v_total
    FROM context_segments WHERE build_id = p_build_id;

    UPDATE context_builds
    SET status = 'DONE', total_segments = v_total, completed_at = now()
    WHERE build_id = p_build_id;

    RETURN format('构建 %s 完成，共 %s 个上下文片段', p_build_id, v_total);
END;
$$;

-- =============================================
-- 13. 带上下文的 Agent 提交
-- =============================================
CREATE OR REPLACE FUNCTION submit_context_agent(
    p_question text,
    p_build_id text DEFAULT NULL,
    p_priority int DEFAULT 0
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id bigint;
BEGIN
    INSERT INTO agent_jobs (build_id, job_type, task_name, payload, priority)
    VALUES (p_build_id, 'agent_run', 'agent_' || gen_random_uuid()::text,
            jsonb_build_object('question', p_question, 'max_steps', 10), p_priority)
    RETURNING job_id INTO v_job_id;

    RETURN v_job_id;
END;
$$;

-- =============================================
-- 14. 等待任务完成（轮询）
-- =============================================
CREATE OR REPLACE FUNCTION wait_for_jobs(
    p_job_ids bigint[],
    p_timeout_sec int DEFAULT 60
)
RETURNS TABLE(job_id bigint, status text, result text)
LANGUAGE plpgsql
AS $$
DECLARE
    v_start timestamptz := now();
    v_pending int;
BEGIN
    LOOP
        SELECT count(*) INTO v_pending
        FROM agent_jobs aj
        WHERE aj.job_id = ANY(p_job_ids)
          AND aj.status NOT IN ('DONE', 'ERROR');

        IF v_pending = 0 THEN
            EXIT;
        END IF;

        IF now() - v_start > (p_timeout_sec || ' seconds')::interval THEN
            EXIT;
        END IF;

        PERFORM pg_sleep(0.5);
    END LOOP;

    RETURN QUERY
    SELECT j.job_id, j.status, j.result
    FROM agent_jobs j
    WHERE j.job_id = ANY(p_job_ids);
END;
$$;
