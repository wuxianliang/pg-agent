-- ============================================================
-- PG-Agent v3 · 库内 PGMQ + 库外 worker
--
-- 与 v2 共用同一套纯函数（prompt / parse / fold）和 HTTP 基线循环。
-- 新增：SQL 只拼 messages 并 pgmq.send；HTTP 由库外 worker 完成。
-- ============================================================

CREATE EXTENSION IF NOT EXISTS http;
CREATE EXTENSION IF NOT EXISTS pgmq;

DO $$
BEGIN
    PERFORM http_set_curlopt('CURLOPT_TIMEOUT', '90');
EXCEPTION WHEN undefined_function THEN
    RAISE NOTICE 'http_set_curlopt 不可用，跳过';
END $$;

-- ---------- Agent 运行（状态由 steps 折叠，无冗余 status 列） ----------
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id             text PRIMARY KEY,
    question           text NOT NULL,
    max_steps          int  NOT NULL DEFAULT 10,
    max_rows           int  NOT NULL DEFAULT 50,
    last_applied_hash  text,
    created_at         timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS last_applied_hash text;

CREATE TABLE IF NOT EXISTS agent_steps (
    run_id     text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    seq        bigserial,
    kind       text NOT NULL,
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

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
            PERFORM pg_sleep(0.2 * i);
        END;
    END LOOP;
END;
$$;

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
6. 同一数据库会话可跨轮次保留键值：SELECT session_set('k','v')；SELECT session_get('k')。
%2$s
$sys$, p_max_rows,
    CASE WHEN p_context IS NOT NULL AND p_context <> ''
         THEN E'\n【数据库上下文】\n' || p_context || E'\n【上下文结束】'
         ELSE '' END)
$$;

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
    IF v ~ '^```' THEN
        v := trim(regexp_replace(regexp_replace(v, '^```[[:alpha:]]*\s*', ''), '\s*```$', ''));
    END IF;
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

CREATE OR REPLACE FUNCTION http_call_llm(p_messages jsonb)
RETURNS jsonb
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

-- 会话级 KV：TEMP TABLE，只对当前 backend 可见。worker 必须按 run_id 粘住连接。
CREATE OR REPLACE FUNCTION session_set(p_key text, p_val text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    CREATE TEMP TABLE IF NOT EXISTS agent_session_kv (
        k text PRIMARY KEY,
        v text NOT NULL
    );
    INSERT INTO agent_session_kv(k, v) VALUES (p_key, p_val)
    ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v;
    RETURN jsonb_build_object('success', true, 'key', p_key, 'pid', pg_backend_pid());
END;
$$;

CREATE OR REPLACE FUNCTION session_get(p_key text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_val text;
BEGIN
    CREATE TEMP TABLE IF NOT EXISTS agent_session_kv (
        k text PRIMARY KEY,
        v text NOT NULL
    );
    SELECT kv.v INTO v_val FROM agent_session_kv kv WHERE kv.k = p_key;
    RETURN jsonb_build_object(
        'success', true, 'key', p_key, 'value', v_val, 'pid', pg_backend_pid()
    );
END;
$$;

CREATE OR REPLACE FUNCTION session_backend_pid()
RETURNS int
LANGUAGE sql STABLE AS $$
    SELECT pg_backend_pid()
$$;

CREATE OR REPLACE FUNCTION emit_step(p_run_id text, p_kind text, p_payload jsonb)
RETURNS void
LANGUAGE sql VOLATILE AS $$
    INSERT INTO agent_steps (run_id, kind, payload) VALUES (p_run_id, p_kind, p_payload);
$$;

CREATE OR REPLACE FUNCTION fail_run(p_run_id text, p_message text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status FROM run_state(p_run_id);
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;
    IF v_status = 'SUCCESS' THEN
        RETURN jsonb_build_object('done', true, 'ok', true, 'run_id', p_run_id, 'skipped', true);
    END IF;
    IF v_status <> 'ERROR' THEN
        PERFORM emit_step(p_run_id, 'error', jsonb_build_object('message', p_message));
    END IF;
    RETURN jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id, 'error', p_message);
END;
$$;

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

-- ============================================================
-- HTTP 基线：WHILE 循环在 backend 里同步 http()
-- ============================================================
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

    v_system := make_system_prompt(50);

    WHILE v_used < p_max_steps LOOP
        SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                                  ORDER BY seq), '[]'::jsonb)
          INTO v_steps FROM agent_steps WHERE run_id = v_run_id;
        v_msgs := fold_messages(v_system, p_question, v_steps);
        v_raw := sql_retry('http_call_llm(jsonb)'::regprocedure, v_msgs, 2) ->> 'raw';

        BEGIN
            v_dec := parse_llm_output(v_raw);
        EXCEPTION WHEN OTHERS THEN
            PERFORM emit_step(v_run_id, 'error',
                    jsonb_build_object('message','LLM 返回非法 JSON: '||left(v_raw,300)));
            RETURN '失败：LLM 返回非法 JSON，run_id=' || v_run_id;
        END;
        PERFORM emit_step(v_run_id, 'llm', jsonb_build_object('raw', v_raw, 'thought', v_dec.thought));
        v_used := v_used + 1;

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

-- ============================================================
-- PGMQ 路径：SQL 只组织 prompt，入队后立即返回
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'llm_requests') THEN
        PERFORM pgmq.create('llm_requests');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'llm_requests_dlq') THEN
        PERFORM pgmq.create('llm_requests_dlq');
    END IF;
END $$;

CREATE OR REPLACE FUNCTION prepare_llm_request(p_run_id text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_run    agent_runs;
    v_steps  jsonb;
    v_msgs   jsonb;
    v_system text;
    v_used   int;
BEGIN
    SELECT * INTO v_run FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;

    SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                              ORDER BY seq), '[]'::jsonb),
           count(*) FILTER (WHERE kind='llm')
      INTO v_steps, v_used
      FROM agent_steps WHERE run_id = p_run_id;

    v_system := make_system_prompt(COALESCE(v_run.max_rows, 50));
    v_msgs := fold_messages(v_system, v_run.question, v_steps);

    RETURN jsonb_build_object(
        'run_id',   p_run_id,
        'question', v_run.question,
        'step',     v_used + 1,
        'max_steps', v_run.max_steps,
        'messages', v_msgs,
        'model',    current_setting('openai.model', true),
        'api_uri',  current_setting('openai.api_uri', true)
    );
END;
$$;

CREATE OR REPLACE FUNCTION enqueue_llm_request(p_run_id text)
RETURNS bigint
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_payload jsonb;
    v_msg_id  bigint;
BEGIN
    v_payload := prepare_llm_request(p_run_id);
    SELECT pgmq.send(
        'llm_requests',
        v_payload,
        jsonb_build_object('x-pgmq-group', p_run_id)
    ) INTO v_msg_id;
    RETURN v_msg_id;
END;
$$;

CREATE OR REPLACE FUNCTION agent_start(p_question text, p_max_steps int DEFAULT 10)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id text := gen_random_uuid()::text;
BEGIN
    INSERT INTO agent_runs (run_id, question, max_steps)
    VALUES (v_run_id, p_question, p_max_steps);
    PERFORM enqueue_llm_request(v_run_id);
    RETURN v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION apply_llm_response(p_run_id text, p_raw text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_dec    llm_decision;
    v_obs    jsonb;
    v_used   int;
    v_max    int;
    v_qid    bigint;
    v_hash   text;
    v_prev   text;
    v_status text;
    v_answer text;
    v_err    text;
    v_result jsonb;
BEGIN
    SELECT max_steps, last_applied_hash INTO v_max, v_prev
      FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;

    v_hash := md5(p_raw);
    IF v_prev IS NOT NULL AND v_prev = v_hash THEN
        SELECT status, steps_used, answer, error
          INTO v_status, v_used, v_answer, v_err
          FROM run_state(p_run_id);
        RETURN jsonb_build_object(
            'done', v_status IN ('SUCCESS','ERROR'),
            'ok', v_status = 'SUCCESS',
            'answer', v_answer,
            'run_id', p_run_id,
            'replayed', true,
            'error', v_err
        );
    END IF;

    BEGIN
        v_dec := parse_llm_output(p_raw);
    EXCEPTION WHEN OTHERS THEN
        PERFORM emit_step(p_run_id, 'error',
                jsonb_build_object('message','LLM 返回非法 JSON: '||left(p_raw,300)));
        UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
        RETURN jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id,
                                 'error', 'invalid_json');
    END;

    PERFORM emit_step(p_run_id, 'llm', jsonb_build_object('raw', p_raw, 'thought', v_dec.thought));

    IF v_dec.final_answer IS NOT NULL AND v_dec.action IS NULL THEN
        PERFORM emit_step(p_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
        UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
        RETURN jsonb_build_object('done', true, 'ok', true, 'answer', v_dec.final_answer,
                                 'run_id', p_run_id);
    END IF;

    IF v_dec.action = 'execute_sql' THEN
        v_obs := exec_sql_readonly(v_dec.sql, 50);
    ELSE
        v_obs := jsonb_build_object('success',false,'error','未知 action: '||COALESCE(v_dec.action,'null'));
    END IF;
    PERFORM emit_step(p_run_id, 'tool', jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text));

    SELECT count(*) FILTER (WHERE kind='llm') INTO v_used FROM agent_steps WHERE run_id = p_run_id;
    IF v_used >= v_max THEN
        PERFORM emit_step(p_run_id, 'error', jsonb_build_object('message','达到最大步数'));
        UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
        RETURN jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id,
                                 'error', 'max_steps');
    END IF;

    v_qid := enqueue_llm_request(p_run_id);
    UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
    RETURN jsonb_build_object('done', false, 'ok', true, 'enqueued', v_qid, 'run_id', p_run_id);
END;
$$;
