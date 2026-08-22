-- ============================================================
-- PG-Agent · Recursive Language Model（独立版）
--
-- 对照 prime-agent RLM / 原论文：
--   1. prompt-as-a-variable —— 大段上下文进 rlm_vars，不进 system prompt
--   2. 持久 SQL REPL        —— 变量跨轮次保留；模型唯一动作是写一条 SELECT
--   3. 递归子 agent         —— rlm_spawn / rlm_map 在 REPL 里当函数调用
--
-- 阅读顺序即架构顺序：
--   L0 基础设施    —— 扩展、表（步骤只追加）
--   L1 组合子      —— sql_retry
--   L2 纯函数      —— prompt / 解析 / 折叠 messages
--   L3 副作用外壳  —— HTTP、env、eval、spawn
--   L4 插件层      —— COMMENT 即注册
--   L5 运行时      —— rlm_run 主循环 + worker
--
-- 口诀：上下文是变量，工具是 SQL，子 agent 是函数。
-- ============================================================

-- ============================================================
-- L0. 基础设施
-- ============================================================
CREATE EXTENSION IF NOT EXISTS http;

DO $$
BEGIN
    PERFORM http_set_curlopt('CURLOPT_TIMEOUT', '90');
EXCEPTION WHEN undefined_function THEN
    RAISE NOTICE 'http_set_curlopt 不可用，跳过';
END $$;

-- ---------- 运行 ----------
CREATE TABLE IF NOT EXISTS rlm_runs (
    run_id        text PRIMARY KEY,
    question      text NOT NULL,
    parent_run_id text REFERENCES rlm_runs(run_id) ON DELETE CASCADE,
    name          text,
    depth         int  NOT NULL DEFAULT 0,
    max_depth     int  NOT NULL DEFAULT 1,
    max_steps     int  NOT NULL DEFAULT 10,
    max_rows      int  NOT NULL DEFAULT 50,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rlm_runs_parent ON rlm_runs(parent_run_id);

-- ---------- 步骤流（只追加；状态由 run_state() 折叠） ----------
CREATE TABLE IF NOT EXISTS rlm_steps (
    run_id     text NOT NULL REFERENCES rlm_runs(run_id) ON DELETE CASCADE,
    seq        bigserial,
    kind       text NOT NULL,            -- 'llm' | 'tool' | 'spawn' | 'final' | 'error'
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

-- ---------- 持久 REPL 命名空间（prompt-as-a-variable 的载体） ----------
CREATE TABLE IF NOT EXISTS rlm_vars (
    run_id     text NOT NULL REFERENCES rlm_runs(run_id) ON DELETE CASCADE,
    name       text NOT NULL,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, name)
);

-- ---------- 子 agent 登记 ----------
CREATE TABLE IF NOT EXISTS rlm_children (
    parent_run_id text NOT NULL REFERENCES rlm_runs(run_id) ON DELETE CASCADE,
    child_run_id  text NOT NULL REFERENCES rlm_runs(run_id) ON DELETE CASCADE,
    name          text NOT NULL,
    status        text NOT NULL DEFAULT 'RUNNING',  -- RUNNING/SUCCESS/ERROR
    answer        text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_run_id, name)
);

-- ---------- 任务队列 ----------
CREATE TABLE IF NOT EXISTS jobs (
    job_id       bigserial PRIMARY KEY,
    job_type     text NOT NULL,
    payload      jsonb NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'PENDING',
    priority     int  NOT NULL DEFAULT 0,
    run_id       text,
    result       jsonb,
    error_msg    text,
    worker_id    text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_rlm_jobs_ready
    ON jobs (priority DESC, job_id) WHERE status = 'PENDING';

-- ============================================================
-- L1. 组合子
-- ============================================================
CREATE OR REPLACE FUNCTION sql_retry(fn regproc, arg jsonb, times int DEFAULT 2)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v jsonb;
BEGIN
    FOR i IN 1..times LOOP
        BEGIN
            EXECUTE format('SELECT %s($1)', fn) INTO v USING arg;
            RETURN v;
        EXCEPTION WHEN OTHERS THEN
            IF i = times THEN RAISE; END IF;
            PERFORM pg_sleep(0.2 * i);
        END;
    END LOOP;
END;
$$;

-- ============================================================
-- L2. 纯函数核心
-- ============================================================
CREATE TYPE rlm_decision AS (
    thought      text,
    code         text,     -- 一条 SELECT/WITH；NULL 表示本轮不 eval
    final_answer text
);

CREATE OR REPLACE FUNCTION make_rlm_prompt(
    p_depth int,
    p_max_depth int,
    p_max_rows int,
    p_has_context boolean
)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT format($sys$
你是运行在 PostgreSQL 内部的 Recursive Language Model (RLM) Agent。
工作面是持久 SQL REPL：命名变量跨轮次保留。大段上下文是变量，不在本 prompt 里。

严格按 JSON 回复（不要输出其他文字）：
{"thought":"思考","code":"一条 SELECT 或 WITH","final_answer":"答案或 null"}

规则：
1. 每轮最多一条 SQL，必须是 SELECT 或 WITH，不要分号结尾。
2. 信息足够后填 final_answer，并把 code 设为 null。
3. 禁止编造数据。需要看上下文时先 env_peek / env_search / env_len。
4. 查询最多返回 %s 行；过长结果会截断，全文写入变量 last_obs。
5. 可用 WITH 在一条语句里组合多个调用。

REPL API（均在 SELECT 中调用）：
- env_keys()                              列出变量名
- env_get('name')                         取 JSON 值
- env_set('name', 'value')                写入（文本或 JSON）
- env_set_text('name', 'value')           强制存成 JSON 字符串
- env_len('name')                         文本长度
- env_peek('name', start, len)            切片（start 从 1 计）
- env_search('name', 'regex')             正则搜索
- env_chunk('name', size)                 切成文本块数组
- rlm_query('SELECT ...')                 只读查询业务表（也允许直接写 SELECT）
%s
预置变量：question%s。不要假设你已经读过它们的内容。

当前递归深度：%s / 最大 %s。%s
$sys$,
        p_max_rows,
        CASE WHEN p_depth < p_max_depth THEN
$spawn$
- rlm_spawn('子任务', '可选名字')         同步跑一个子 RLM，返回 {name,child_run_id,answer}
- rlm_map(chunks_json, '前缀')            对最多 8 块同步 map
- rlm_list()                              列出已生成的子 agent
$spawn$
        ELSE
            E'- 已达最大递归深度，禁止 rlm_spawn / rlm_map，直接作答。'
        END,
        CASE WHEN p_has_context THEN '、context' ELSE '' END,
        p_depth, p_max_depth,
        CASE WHEN p_depth > 0 THEN '你是子 agent，作答后填 final_answer。'
             ELSE '你是根 agent。独立子任务请 rlm_spawn。' END)
$$;

CREATE OR REPLACE FUNCTION make_rlm_user(p_question text, p_has_context boolean)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN length(p_question) <= 1500 THEN
            '任务：' || p_question || E'\n\n'
            || '环境已预置变量 question'
            || CASE WHEN p_has_context THEN ' 与 context' ELSE '' END
            || '。用 env_keys() / env_peek / env_search 查看，不要假设内容已在 prompt 中。'
        ELSE
            '任务过长，只放在 env 变量 question 里。'
            || CASE WHEN p_has_context THEN ' 大段上下文在 env 变量 context。' ELSE '' END
            || ' 用 env_peek / env_search 读取后再作答。'
    END
$$;

CREATE OR REPLACE FUNCTION parse_rlm_output(p_raw text)
RETURNS rlm_decision
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v text := trim(p_raw);
    j jsonb;
    d rlm_decision;
    v_action text;
BEGIN
    IF v ~ '^```' THEN
        v := trim(regexp_replace(regexp_replace(v, '^```[[:alpha:]]*\s*', ''), '\s*```$', ''));
    END IF;
    IF v !~ '^\s*\{' THEN
        v := COALESCE(substring(v from '\{[\s\S]*\}'), '');
    END IF;
    j := v::jsonb;

    d.thought := j ->> 'thought';
    v_action := NULLIF(NULLIF(trim(COALESCE(j ->> 'action', '')), 'null'), '');
    d.code := NULLIF(NULLIF(trim(COALESCE(
        j ->> 'code',
        CASE WHEN COALESCE(v_action, 'eval') IN ('execute_sql','eval','ipython','sql')
             THEN j ->> 'action_input' END,
        j ->> 'action_input',
        '')), 'null'), '');
    d.final_answer := NULLIF(NULLIF(trim(COALESCE(j ->> 'final_answer', '')), 'null'), '');
    RETURN d;
END;
$$;

CREATE OR REPLACE FUNCTION fold_rlm_messages(p_system text, p_user text, p_steps jsonb)
RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_build_array(
               jsonb_build_object('role','system','content',p_system),
               jsonb_build_object('role','user','content',p_user))
        || COALESCE((
            SELECT jsonb_agg(
                CASE s->>'kind'
                    WHEN 'llm'  THEN jsonb_build_object('role','assistant','content',s->'payload'->>'raw')
                    WHEN 'tool' THEN jsonb_build_object('role','user','content','Observation: '||(s->'payload'->>'observation'))
                    WHEN 'spawn' THEN jsonb_build_object('role','user','content','Spawn: '||(s->'payload'->>'observation'))
                END ORDER BY (s->>'seq')::bigint)
            FROM jsonb_array_elements(p_steps) s
            WHERE s->>'kind' IN ('llm','tool','spawn')
        ), '[]'::jsonb)
$$;

-- ============================================================
-- L3. 副作用外壳
-- ============================================================

-- 动作 1：HTTP 调用 LLM
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

-- 绑定当前 REPL 会话（session 级 GUC，autocommit 下也有效）
CREATE OR REPLACE FUNCTION rlm_bind(p_run_id text)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    IF p_run_id IS NULL OR p_run_id = '' THEN
        RAISE EXCEPTION 'rlm_bind: run_id 为空';
    END IF;
    PERFORM set_config('rlm.run_id', p_run_id, false);
    RETURN p_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_current_run()
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    id text := current_setting('rlm.run_id', true);
BEGIN
    IF id IS NULL OR id = '' THEN
        RAISE EXCEPTION 'rlm.run_id 未绑定：先 rlm_bind() 或在 rlm_eval / rlm_run 内调用';
    END IF;
    RETURN id;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_emit(p_run_id text, p_kind text, p_payload jsonb)
RETURNS void
LANGUAGE sql VOLATILE AS $$
    INSERT INTO rlm_steps (run_id, kind, payload) VALUES (p_run_id, p_kind, p_payload);
$$;

-- ---------- env：持久变量 ----------
CREATE OR REPLACE FUNCTION env_set_json(p_name text, p_value jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    id text := rlm_current_run();
BEGIN
    IF p_name IS NULL OR trim(p_name) = '' THEN
        RAISE EXCEPTION 'env_set: 变量名不能为空';
    END IF;
    INSERT INTO rlm_vars (run_id, name, value)
    VALUES (id, p_name, COALESCE(p_value, 'null'::jsonb))
    ON CONFLICT (run_id, name) DO UPDATE
        SET value = EXCLUDED.value, updated_at = now();
    RETURN p_value;
END;
$$;

CREATE OR REPLACE FUNCTION env_set(p_name text, p_value text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v jsonb;
BEGIN
    BEGIN
        v := p_value::jsonb;
    EXCEPTION WHEN OTHERS THEN
        v := to_jsonb(p_value);
    END;
    RETURN env_set_json(p_name, v);
END;
$$;

CREATE OR REPLACE FUNCTION env_set_text(p_name text, p_value text)
RETURNS jsonb
LANGUAGE sql VOLATILE AS $$
    SELECT env_set_json(p_name, to_jsonb(COALESCE(p_value, '')))
$$;

CREATE OR REPLACE FUNCTION env_get(p_name text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v jsonb;
BEGIN
    SELECT value INTO v FROM rlm_vars
     WHERE run_id = rlm_current_run() AND name = p_name;
    RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION env_text(p_name text)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v jsonb := env_get(p_name);
BEGIN
    IF v IS NULL THEN RETURN NULL; END IF;
    IF jsonb_typeof(v) = 'string' THEN RETURN v #>> '{}'; END IF;
    RETURN v::text;
END;
$$;

CREATE OR REPLACE FUNCTION env_keys()
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    k jsonb;
BEGIN
    SELECT COALESCE(jsonb_agg(name ORDER BY name), '[]'::jsonb)
      INTO k FROM rlm_vars WHERE run_id = rlm_current_run();
    RETURN k;
END;
$$;

CREATE OR REPLACE FUNCTION env_len(p_name text)
RETURNS int
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(length(env_text(p_name)), 0)
$$;

CREATE OR REPLACE FUNCTION env_peek(p_name text, p_start int DEFAULT 1, p_len int DEFAULT 500)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    t text := env_text(p_name);
    s int := GREATEST(COALESCE(p_start, 1), 1);
    n int := GREATEST(COALESCE(p_len, 500), 0);
BEGIN
    IF t IS NULL THEN RETURN NULL; END IF;
    RETURN substr(t, s, n);
END;
$$;

CREATE OR REPLACE FUNCTION env_search(p_name text, p_pattern text, p_max int DEFAULT 20)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    t   text := env_text(p_name);
    m   text;
    out jsonb := '[]'::jsonb;
    n   int := 0;
    cap int := LEAST(GREATEST(COALESCE(p_max, 20), 1), 50);
BEGIN
    IF t IS NULL THEN
        RETURN jsonb_build_object('error', 'no such var', 'n', 0, 'matches', '[]'::jsonb);
    END IF;
    FOR m IN SELECT unnest(regexp_matches(t, p_pattern, 'g')) LOOP
        out := out || jsonb_build_array(m);
        n := n + 1;
        EXIT WHEN n >= cap;
    END LOOP;
    RETURN jsonb_build_object('n', n, 'matches', out);
END;
$$;

CREATE OR REPLACE FUNCTION env_chunk(p_name text, p_size int DEFAULT 2000)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    t   text := env_text(p_name);
    i   int;
    sz  int := GREATEST(COALESCE(p_size, 2000), 1);
    out jsonb := '[]'::jsonb;
BEGIN
    IF t IS NULL OR t = '' THEN RETURN '[]'::jsonb; END IF;
    FOR i IN 1..length(t) BY sz LOOP
        out := out || jsonb_build_array(substr(t, i, sz));
    END LOOP;
    RETURN out;
END;
$$;

-- 只读查询（模型也可在 eval 里直接写 SELECT）
CREATE OR REPLACE FUNCTION rlm_query(p_sql text, p_max_rows int DEFAULT 50)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_sql  text := rtrim(trim(COALESCE(p_sql,'')), ';');
    v_low  text := lower(v_sql);
    v_data jsonb;
    v_forbidden text[] := ARRAY['drop','truncate','alter','create','grant','revoke',
        'copy','execute','call','do','vacuum','analyze','reindex','cluster',
        'discard','lock','set role','reset','load','listen','notify','unlisten',
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
    IF v_low !~ '^\s*(select|with)\M' THEN
        RETURN jsonb_build_object('success',false,'error','只允许 SELECT / WITH');
    END IF;

    BEGIN
        EXECUTE format('SELECT COALESCE(jsonb_agg(t),''[]''::jsonb) FROM (%s LIMIT %s) t',
                       v_sql, COALESCE(p_max_rows, 50))
           INTO v_data;
        RETURN jsonb_build_object('success',true,'data',v_data,
                                  'row_count', jsonb_array_length(v_data));
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object('success',false,'error',SQLERRM,'sqlstate',SQLSTATE);
    END;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_clip(p jsonb, p_max int DEFAULT 4000)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    t text := COALESCE(p::text, '');
BEGIN
    IF length(t) <= p_max THEN RETURN t; END IF;
    RETURN left(t, p_max) || format('…[truncated, full in env last_obs, len=%s]', length(t));
END;
$$;

-- 执行模型给出的一条 SELECT；绑定 GUC 并在结束后恢复
CREATE OR REPLACE FUNCTION rlm_eval(p_run_id text, p_sql text, p_max_rows int DEFAULT 50)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_prev text := current_setting('rlm.run_id', true);
    v_out  jsonb;
BEGIN
    PERFORM set_config('rlm.run_id', p_run_id, false);
    BEGIN
        v_out := rlm_query(p_sql, p_max_rows);
    EXCEPTION WHEN OTHERS THEN
        v_out := jsonb_build_object('success',false,'error',SQLERRM,'sqlstate',SQLSTATE);
    END;
    IF v_prev IS NULL OR v_prev = '' THEN
        PERFORM set_config('rlm.run_id', '', false);
    ELSE
        PERFORM set_config('rlm.run_id', v_prev, false);
    END IF;
    RETURN v_out;
END;
$$;

-- ---------- 递归子 agent（前向声明用 stub，L5 再替换为真正实现） ----------
CREATE OR REPLACE FUNCTION rlm_loop(p_run_id text)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    RAISE EXCEPTION 'rlm_loop 尚未安装';
END;
$$;

CREATE OR REPLACE FUNCTION rlm_spawn(p_prompt text, p_name text DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_parent text := rlm_current_run();
    v_prev   text := v_parent;
    r        record;
    v_name   text;
    v_child  text;
    v_answer text;
    v_n      int;
BEGIN
    IF p_prompt IS NULL OR trim(p_prompt) = '' THEN
        RETURN jsonb_build_object('success', false, 'error', 'spawn prompt 为空');
    END IF;

    SELECT * INTO r FROM rlm_runs WHERE run_id = v_parent;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'error', 'parent run 不存在');
    END IF;
    IF r.depth >= r.max_depth OR r.depth >= 4 THEN
        RETURN jsonb_build_object('success', false, 'error',
            format('已达最大递归深度 depth=%s max_depth=%s', r.depth, r.max_depth));
    END IF;

    SELECT count(*) INTO v_n FROM rlm_children WHERE parent_run_id = v_parent;
    IF v_n >= 16 THEN
        RETURN jsonb_build_object('success', false, 'error', '同一父 run 最多 16 个子 agent');
    END IF;

    v_name := NULLIF(trim(COALESCE(p_name, '')), '');
    IF v_name IS NULL THEN
        v_name := 'child-' || (v_n + 1)::text;
    END IF;
    IF EXISTS (SELECT 1 FROM rlm_children WHERE parent_run_id = v_parent AND name = v_name) THEN
        RETURN jsonb_build_object('success', false, 'error', '子 agent 名已占用: '||v_name);
    END IF;

    v_child := gen_random_uuid()::text;
    INSERT INTO rlm_runs (run_id, question, parent_run_id, name, depth, max_depth, max_steps, max_rows)
    VALUES (v_child, p_prompt, v_parent, v_name, r.depth + 1, r.max_depth,
            LEAST(r.max_steps, 6), r.max_rows);
    INSERT INTO rlm_children (parent_run_id, child_run_id, name, status)
    VALUES (v_parent, v_child, v_name, 'RUNNING');
    PERFORM set_config('rlm.run_id', v_child, false);
    PERFORM env_set_text('question', p_prompt);

    BEGIN
        v_answer := rlm_loop(v_child);
        UPDATE rlm_children
           SET status = 'SUCCESS', answer = v_answer
         WHERE parent_run_id = v_parent AND child_run_id = v_child;
    EXCEPTION WHEN OTHERS THEN
        UPDATE rlm_children
           SET status = 'ERROR', answer = SQLERRM
         WHERE parent_run_id = v_parent AND child_run_id = v_child;
        PERFORM set_config('rlm.run_id', v_prev, false);
        RETURN jsonb_build_object('success', false, 'name', v_name,
                                  'child_run_id', v_child, 'error', SQLERRM);
    END;

    PERFORM set_config('rlm.run_id', v_prev, false);
    RETURN jsonb_build_object('success', true, 'name', v_name,
                              'child_run_id', v_child, 'answer', v_answer);
END;
$$;

CREATE OR REPLACE FUNCTION rlm_map(p_chunks jsonb, p_prefix text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    chunk jsonb;
    i     int := 0;
    answers jsonb := '[]'::jsonb;
    piece text;
    r     jsonb;
BEGIN
    IF jsonb_typeof(COALESCE(p_chunks, 'null'::jsonb)) <> 'array' THEN
        RETURN jsonb_build_object('success', false, 'error', 'chunks 必须是 JSON 数组');
    END IF;
    IF jsonb_array_length(p_chunks) > 8 THEN
        RETURN jsonb_build_object('success', false, 'error', 'rlm_map 最多 8 块，请先切片');
    END IF;
    FOR chunk IN SELECT value FROM jsonb_array_elements(p_chunks) LOOP
        i := i + 1;
        piece := CASE jsonb_typeof(chunk)
                    WHEN 'string' THEN chunk #>> '{}'
                    ELSE chunk::text
                 END;
        r := rlm_spawn(COALESCE(p_prefix, '') || E'\n' || piece, 'map-' || i);
        answers := answers || jsonb_build_array(r);
    END LOOP;
    RETURN answers;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_list()
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    out jsonb;
BEGIN
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'name', name,
               'child_run_id', child_run_id,
               'status', status,
               'answer', answer
           ) ORDER BY created_at), '[]'::jsonb)
      INTO out
      FROM rlm_children
     WHERE parent_run_id = rlm_current_run();
    RETURN out;
END;
$$;

-- ============================================================
-- L4. 插件层
-- ============================================================
CREATE TABLE IF NOT EXISTS handlers (
    job_type text PRIMARY KEY,
    fn       regproc NOT NULL
);

CREATE OR REPLACE FUNCTION refresh_handlers()
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE n int;
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

CREATE OR REPLACE FUNCTION h_rlm_run(p_job jobs)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    v := rlm_run(p_job.payload->>'question',
                 p_job.payload->>'context',
                 COALESCE((p_job.payload->>'max_steps')::int, 10),
                 COALESCE((p_job.payload->>'max_depth')::int, 1));
    UPDATE jobs SET status='DONE', result=jsonb_build_object('answer',v),
                run_id = (SELECT run_id FROM rlm_runs ORDER BY created_at DESC LIMIT 1),
                completed_at=now()
     WHERE job_id = p_job.job_id;
END;
$$;
COMMENT ON FUNCTION h_rlm_run(jobs) IS '{"job_handler":"rlm_run"}';

-- ============================================================
-- L5. 运行时
-- ============================================================
CREATE OR REPLACE FUNCTION rlm_run_state(p_run_id text)
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
      FROM rlm_steps
     WHERE run_id = p_run_id
$$;

-- 给测试用：当前 run 的 system prompt（断言大段 context 不在 prompt 里）
CREATE OR REPLACE FUNCTION rlm_system_prompt(p_run_id text)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE r record;
BEGIN
    SELECT depth, max_depth, max_rows INTO r FROM rlm_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'run % 不存在', p_run_id; END IF;
    RETURN make_rlm_prompt(
        r.depth, r.max_depth, r.max_rows,
        EXISTS (SELECT 1 FROM rlm_vars WHERE run_id = p_run_id AND name = 'context'));
END;
$$;

CREATE OR REPLACE FUNCTION rlm_loop(p_run_id text)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    r        record;
    v_dec    rlm_decision;
    v_raw    text;
    v_msgs   jsonb;
    v_system text;
    v_user   text;
    v_steps  jsonb;
    v_used   int := 0;
    v_obs    jsonb;
    v_obs_t  text;
    v_has_ctx boolean;
    v_prev   text := current_setting('rlm.run_id', true);
BEGIN
    SELECT * INTO r FROM rlm_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'run_id % 不存在', p_run_id; END IF;

    v_has_ctx := EXISTS (SELECT 1 FROM rlm_vars WHERE run_id = p_run_id AND name = 'context');
    v_system := make_rlm_prompt(r.depth, r.max_depth, r.max_rows, v_has_ctx);
    v_user   := make_rlm_user(r.question, v_has_ctx);

    WHILE v_used < r.max_steps LOOP
        SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                                  ORDER BY seq), '[]'::jsonb)
          INTO v_steps FROM rlm_steps WHERE run_id = p_run_id;
        v_msgs := fold_rlm_messages(v_system, v_user, v_steps);

        BEGIN
            v_raw := sql_retry('http_call_llm'::regproc, v_msgs, 2) ->> 'raw';
        EXCEPTION WHEN OTHERS THEN
            PERFORM rlm_emit(p_run_id, 'error',
                    jsonb_build_object('message','LLM 调用失败: '||SQLERRM));
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN '失败：LLM 调用失败，run_id=' || p_run_id;
        END;

        BEGIN
            v_dec := parse_rlm_output(v_raw);
        EXCEPTION WHEN OTHERS THEN
            PERFORM rlm_emit(p_run_id, 'error',
                    jsonb_build_object('message','LLM 返回非法 JSON: '||left(v_raw,300)));
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN '失败：LLM 返回非法 JSON，run_id=' || p_run_id;
        END;
        PERFORM rlm_emit(p_run_id, 'llm',
                jsonb_build_object('raw', v_raw, 'thought', v_dec.thought, 'code', v_dec.code));
        v_used := v_used + 1;

        IF v_dec.final_answer IS NOT NULL AND v_dec.code IS NULL THEN
            PERFORM rlm_emit(p_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN v_dec.final_answer;
        END IF;

        IF v_dec.code IS NULL THEN
            v_obs := jsonb_build_object('success', false,
                     'error', '必须提供 code 或 final_answer');
        ELSE
            v_obs := rlm_eval(p_run_id, v_dec.code, r.max_rows);
        END IF;

        PERFORM set_config('rlm.run_id', p_run_id, false);
        PERFORM env_set_json('last_obs', v_obs);
        v_obs_t := rlm_clip(v_obs, 4000);
        PERFORM rlm_emit(p_run_id, 'tool',
                jsonb_build_object('code', v_dec.code, 'observation', v_obs_t));
    END LOOP;

    PERFORM rlm_emit(p_run_id, 'error', jsonb_build_object('message','达到最大步数'));
    PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
    RETURN '达到最大步数，run_id=' || p_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_run(
    p_question  text,
    p_context   text DEFAULT NULL,
    p_max_steps int  DEFAULT 10,
    p_max_depth int  DEFAULT 1
)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id text := gen_random_uuid()::text;
    v_prev   text := current_setting('rlm.run_id', true);
    v_ans    text;
BEGIN
    IF p_question IS NULL OR trim(p_question) = '' THEN
        RAISE EXCEPTION 'rlm_run 需要 p_question';
    END IF;

    INSERT INTO rlm_runs (run_id, question, depth, max_depth, max_steps, name)
    VALUES (v_run_id, p_question, 0, GREATEST(COALESCE(p_max_depth, 1), 0),
            COALESCE(p_max_steps, 10), 'root');

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

-- 修正 h_rlm_run：rlm_run 此时已存在，CREATE OR REPLACE 上面已引用它。
-- PG 允许函数互相前向引用，只要在会话中最终都存在。

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
             WHERE job_id = v_job.job_id;
            RAISE WARNING '任务 % 失败: %', v_job.job_id, SQLERRM;
        END;
    END LOOP;
END;
$$;

SELECT refresh_handlers();

-- ============================================================
-- 使用示例
-- ============================================================
-- SET openai.api_uri='http://127.0.0.1:11434/v1/'; SET openai.model='qwen2.5';
--
-- -- 普通问答（模型自己写 SELECT）：
-- SELECT rlm_run('public 模式下有多少张表？');
--
-- -- prompt-as-variable：长上下文不进 prompt，模型必须 env_search：
-- SELECT rlm_run(
--   '在 context 里找出 SECRET_TOKEN 的值',
--   repeat('padding ', 200) || 'SECRET_TOKEN=abc' || repeat(' padding', 200));
--
-- -- 查看某次 run 的变量与步骤：
-- SELECT * FROM rlm_vars;
-- SELECT * FROM rlm_run_state('某-run-id');
-- SELECT rlm_system_prompt('某-run-id');   -- 其中不应出现 SECRET_TOKEN
