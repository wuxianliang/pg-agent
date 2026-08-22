-- ============================================================
-- PG-Agent v2 · RLM × CodeAct（数据分析系统用）
--
-- 与 v1/pg_agent_rlm_integrated.sql 同源，v2 改动：
--   rlm_loop 按 agent_runs.paradigm 分支：
--     data_analysis → make_da_prompt + 成功 SELECT 后才能 final_answer
--     其它           → 原 RLM prompt / 行为
-- 入口：agent_run_rlm、agent_run_hybrid、agent_run_data_analysis（后者在
-- pg_agent_data_analysis.sql）。
-- ============================================================

-- ============================================================
-- L0. 扩表（只加列 / 新表，不改 CodeAct 既有行语义）
-- ============================================================
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS paradigm text NOT NULL DEFAULT 'codeact';
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS parent_run_id text;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS depth int NOT NULL DEFAULT 0;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS max_depth int NOT NULL DEFAULT 1;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS name text;

CREATE INDEX IF NOT EXISTS idx_agent_runs_parent ON agent_runs(parent_run_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_paradigm ON agent_runs(paradigm);

CREATE TABLE IF NOT EXISTS rlm_vars (
    run_id     text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    name       text NOT NULL,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS rlm_children (
    parent_run_id text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    child_run_id  text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    name          text NOT NULL,
    kind          text NOT NULL DEFAULT 'rlm',   -- 'rlm' | 'codeact'
    status        text NOT NULL DEFAULT 'RUNNING',
    answer        text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (parent_run_id, name)
);

-- ============================================================
-- L2. RLM 纯函数（与独立版同一套决策；不碰 CodeAct 的 make_system_prompt）
-- ============================================================
DO $$ BEGIN
    CREATE TYPE rlm_decision AS (
        thought      text,
        code         text,
        final_answer text
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

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
你与 CodeAct agent 共用 agent_runs / agent_steps。

严格按 JSON 回复（不要输出其他文字）：
{"thought":"思考","code":"一条 SELECT 或 WITH","final_answer":"答案或 null"}

规则：
1. 每轮最多一条 SQL，必须是 SELECT 或 WITH，不要分号结尾。
2. 信息足够后填 final_answer，并把 code 设为 null。
3. 禁止编造数据。需要看上下文时先 env_peek / env_search / env_len。
4. 查询最多返回 %s 行；过长结果会截断，全文写入变量 last_obs。
5. 可用 WITH 在一条语句里组合多个调用。

REPL API（均在 SELECT 中调用）：
- env_keys() / env_get('name') / env_set('name','value') / env_set_text('name','value')
- env_len('name') / env_peek('name', start, len) / env_search('name','regex') / env_chunk('name', size)
- rlm_query('SELECT ...')                 只读查询（也可直接写 SELECT）
- codeact_spawn('问题')                   把简单「查库直到有答案」交给 CodeAct 子 agent
%s
预置变量：question%s。不要假设你已经读过它们的内容。

当前递归深度：%s / 最大 %s。%s
$sys$,
        p_max_rows,
        CASE WHEN p_depth < p_max_depth THEN
$spawn$
- rlm_spawn('子任务', '可选名字')         同步跑一个子 RLM
- rlm_map(chunks_json, '前缀')            对最多 8 块同步 map
- rlm_list()                              列出子 agent
$spawn$
        ELSE
            E'- 已达最大递归深度，禁止 rlm_spawn / rlm_map，直接作答。'
        END,
        CASE WHEN p_has_context THEN '、context' ELSE '' END,
        p_depth, p_max_depth,
        CASE WHEN p_depth > 0 THEN '你是子 agent，作答后填 final_answer。'
             ELSE '你是根 agent。独立子任务请 rlm_spawn；简单查库可 codeact_spawn。' END)
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

CREATE OR REPLACE FUNCTION make_hybrid_prompt(p_max_rows int, p_has_context boolean DEFAULT false)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT format($sys$
你是运行在 PostgreSQL 内部的混合 Agent（CodeAct + RLM）。
默认走 CodeAct：用 execute_sql 查库。遇到长上下文、需要切片/搜索/子任务时，把子任务交给 RLM。

严格按 JSON 回复（不要输出其他文字）：
{"thought":"思考","action":"execute_sql 或 rlm 或 null","action_input":"SQL 或 RLM 子任务","final_answer":"答案"}

规则：
1. 简单查询用 execute_sql，一次一条 SQL，不要分号，最多返回 %s 行。
2. 长文本检索、拆分并行子任务、需要持久变量时，action 设为 rlm，action_input 写清子任务。
3. 信息足够后填 final_answer，action 设为 null。
4. 禁止编造数据。写操作禁止（只读）。
%s
$sys$,
        p_max_rows,
        CASE WHEN p_has_context THEN
            E'\n长上下文已放入 RLM 环境变量 context（未写入本 prompt）。需要阅读时请 action=rlm。'
        ELSE '' END)
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
-- L3. REPL 外壳（写 rlm_vars；读库走既有 exec_sql_readonly）
-- ============================================================
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
        RAISE EXCEPTION 'rlm.run_id 未绑定：先 rlm_bind() 或在 rlm_eval / agent_run_rlm 内调用';
    END IF;
    RETURN id;
END;
$$;

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
DECLARE v jsonb;
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
DECLARE v jsonb;
BEGIN
    SELECT value INTO v FROM rlm_vars
     WHERE run_id = rlm_current_run() AND name = p_name;
    RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION env_text(p_name text)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb := env_get(p_name);
BEGIN
    IF v IS NULL THEN RETURN NULL; END IF;
    IF jsonb_typeof(v) = 'string' THEN RETURN v #>> '{}'; END IF;
    RETURN v::text;
END;
$$;

CREATE OR REPLACE FUNCTION env_keys()
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE k jsonb;
BEGIN
    SELECT COALESCE(jsonb_agg(name ORDER BY name), '[]'::jsonb)
      INTO k FROM rlm_vars WHERE run_id = rlm_current_run();
    RETURN k;
END;
$$;

CREATE OR REPLACE FUNCTION env_len(p_name text)
RETURNS int
LANGUAGE sql STABLE AS $$ SELECT COALESCE(length(env_text(p_name)), 0) $$;

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

CREATE OR REPLACE FUNCTION rlm_query(p_sql text, p_max_rows int DEFAULT 50)
RETURNS jsonb
LANGUAGE sql VOLATILE AS $$
    SELECT exec_sql_readonly(p_sql, p_max_rows)
$$;

CREATE OR REPLACE FUNCTION rlm_clip(p jsonb, p_max int DEFAULT 4000)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE t text := COALESCE(p::text, '');
BEGIN
    IF length(t) <= p_max THEN RETURN t; END IF;
    RETURN left(t, p_max) || format('…[truncated, full in env last_obs, len=%s]', length(t));
END;
$$;

CREATE OR REPLACE FUNCTION rlm_eval(p_run_id text, p_sql text, p_max_rows int DEFAULT 50)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_prev text := current_setting('rlm.run_id', true);
    v_out  jsonb;
BEGIN
    PERFORM set_config('rlm.run_id', p_run_id, false);
    BEGIN
        v_out := exec_sql_readonly(p_sql, p_max_rows);
    EXCEPTION WHEN OTHERS THEN
        v_out := jsonb_build_object('success',false,'error',SQLERRM,'sqlstate',SQLSTATE);
    END;
    PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
    RETURN v_out;
END;
$$;

CREATE OR REPLACE FUNCTION rlm_system_prompt(p_run_id text)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE r record;
BEGIN
    SELECT depth, max_depth, max_rows INTO r FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'run % 不存在', p_run_id; END IF;
    RETURN make_rlm_prompt(
        COALESCE(r.depth, 0), COALESCE(r.max_depth, 1), COALESCE(r.max_rows, 50),
        EXISTS (SELECT 1 FROM rlm_vars WHERE run_id = p_run_id AND name = 'context'));
END;
$$;

-- ============================================================
-- L5. RLM 循环（步骤写入共用的 agent_steps）
-- ============================================================
CREATE OR REPLACE FUNCTION rlm_loop(p_run_id text)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    r         record;
    v_dec     rlm_decision;
    v_raw     text;
    v_msgs    jsonb;
    v_system  text;
    v_user    text;
    v_steps   jsonb;
    v_used    int := 0;
    v_obs     jsonb;
    v_obs_t   text;
    v_has_ctx boolean;
    v_prev    text := current_setting('rlm.run_id', true);
    v_max     int;
    v_da      boolean;
    v_got_q   boolean := false;
BEGIN
    SELECT * INTO r FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'run_id % 不存在', p_run_id; END IF;

    v_max := COALESCE(r.max_steps, 10);
    v_da := COALESCE(r.paradigm, 'rlm') = 'data_analysis';
    v_has_ctx := EXISTS (SELECT 1 FROM rlm_vars WHERE run_id = p_run_id AND name = 'context');
    IF v_da THEN
        v_system := make_da_prompt(COALESCE(r.max_rows, 50));
    ELSE
        v_system := make_rlm_prompt(COALESCE(r.depth,0), COALESCE(r.max_depth,1),
                                   COALESCE(r.max_rows,50), v_has_ctx);
    END IF;
    v_user := make_rlm_user(r.question, v_has_ctx);

    WHILE v_used < v_max LOOP
        SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                                  ORDER BY seq), '[]'::jsonb)
          INTO v_steps FROM agent_steps WHERE run_id = p_run_id;
        v_msgs := fold_rlm_messages(v_system, v_user, v_steps);

        BEGIN
            v_raw := sql_retry('http_call_llm(jsonb)'::regprocedure, v_msgs, 2) ->> 'raw';
        EXCEPTION WHEN OTHERS THEN
            PERFORM emit_step(p_run_id, 'error',
                    jsonb_build_object('message','LLM 调用失败: '||SQLERRM));
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN '失败：LLM 调用失败，run_id=' || p_run_id;
        END;

        BEGIN
            v_dec := parse_rlm_output(v_raw);
        EXCEPTION WHEN OTHERS THEN
            PERFORM emit_step(p_run_id, 'error',
                    jsonb_build_object('message','LLM 返回非法 JSON: '||left(v_raw,300)));
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN '失败：LLM 返回非法 JSON，run_id=' || p_run_id;
        END;
        PERFORM emit_step(p_run_id, 'llm',
                jsonb_build_object('raw', v_raw, 'thought', v_dec.thought, 'code', v_dec.code));
        v_used := v_used + 1;

        IF v_dec.final_answer IS NOT NULL AND v_dec.code IS NULL THEN
            IF (NOT v_da) OR v_got_q THEN
                PERFORM emit_step(p_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
                PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
                RETURN v_dec.final_answer;
            END IF;
            v_obs := jsonb_build_object(
                'success', false,
                'error', '必须先成功执行至少一条 SELECT 才能 final_answer',
                'Type', 'PROTOCOL',
                'Phase', 'Finalization',
                'Problem', '尚未成功查库',
                'Solution', '先 SELECT information_schema 或业务表，再作答。');
            PERFORM set_config('rlm.run_id', p_run_id, false);
            PERFORM env_set_json('last_obs', v_obs);
            PERFORM emit_step(p_run_id, 'tool',
                    jsonb_build_object('code', NULL, 'observation', rlm_clip(v_obs, 4000)));
            CONTINUE;
        END IF;

        IF v_dec.code IS NULL THEN
            v_obs := jsonb_build_object('success', false,
                     'error', '必须提供 code 或 final_answer');
        ELSE
            v_obs := rlm_eval(p_run_id, v_dec.code, COALESCE(r.max_rows, 50));
        END IF;
        IF v_da THEN
            v_obs := da_wrap_obs(v_obs);
        END IF;
        IF COALESCE(v_obs->>'success', 'false') = 'true' THEN
            v_got_q := true;
        END IF;

        PERFORM set_config('rlm.run_id', p_run_id, false);
        PERFORM env_set_json('last_obs', v_obs);
        v_obs_t := rlm_clip(v_obs, 4000);
        PERFORM emit_step(p_run_id, 'tool',
                jsonb_build_object('code', v_dec.code, 'observation', v_obs_t));
    END LOOP;

    PERFORM emit_step(p_run_id, 'error', jsonb_build_object('message','达到最大步数'));
    PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
    RETURN '达到最大步数，run_id=' || p_run_id;
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

    SELECT * INTO r FROM agent_runs WHERE run_id = v_parent;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'error', 'parent run 不存在');
    END IF;
    IF COALESCE(r.depth,0) >= COALESCE(r.max_depth,1) OR COALESCE(r.depth,0) >= 4 THEN
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
    INSERT INTO agent_runs (run_id, question, max_steps, max_rows, paradigm,
                            parent_run_id, depth, max_depth, name)
    VALUES (v_child, p_prompt, LEAST(COALESCE(r.max_steps,10), 6),
            COALESCE(r.max_rows,50), 'rlm',
            v_parent, COALESCE(r.depth,0) + 1, COALESCE(r.max_depth,1), v_name);
    INSERT INTO rlm_children (parent_run_id, child_run_id, name, kind, status)
    VALUES (v_parent, v_child, v_name, 'rlm', 'RUNNING');

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
DECLARE out jsonb;
BEGIN
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'name', name,
               'kind', kind,
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

-- RLM → CodeAct：共用 agent_runs，走既有 agent_run
CREATE OR REPLACE FUNCTION codeact_spawn(p_prompt text, p_name text DEFAULT NULL)
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
    v_max    int;
BEGIN
    IF p_prompt IS NULL OR trim(p_prompt) = '' THEN
        RETURN jsonb_build_object('success', false, 'error', 'spawn prompt 为空');
    END IF;
    SELECT * INTO r FROM agent_runs WHERE run_id = v_parent;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'error', 'parent run 不存在');
    END IF;
    IF COALESCE(r.depth,0) >= COALESCE(r.max_depth,1) OR COALESCE(r.depth,0) >= 4 THEN
        RETURN jsonb_build_object('success', false, 'error',
            format('已达最大递归深度 depth=%s max_depth=%s', r.depth, r.max_depth));
    END IF;

    SELECT count(*) INTO v_n FROM rlm_children WHERE parent_run_id = v_parent;
    v_name := COALESCE(NULLIF(trim(COALESCE(p_name,'')), ''), 'codeact-' || (v_n + 1)::text);
    IF EXISTS (SELECT 1 FROM rlm_children WHERE parent_run_id = v_parent AND name = v_name) THEN
        RETURN jsonb_build_object('success', false, 'error', '子 agent 名已占用: '||v_name);
    END IF;

    v_max := LEAST(COALESCE(r.max_steps,10), 6);
    v_answer := agent_run(p_prompt, v_max);

    SELECT run_id INTO v_child
      FROM agent_runs
     WHERE run_id <> v_parent
     ORDER BY created_at DESC
     LIMIT 1;

    UPDATE agent_runs
       SET parent_run_id = v_parent,
           depth = COALESCE(r.depth,0) + 1,
           max_depth = COALESCE(r.max_depth,1),
           paradigm = COALESCE(paradigm, 'codeact'),
           name = v_name
     WHERE run_id = v_child;

    INSERT INTO rlm_children (parent_run_id, child_run_id, name, kind, status, answer)
    VALUES (v_parent, v_child, v_name, 'codeact', 'SUCCESS', v_answer)
    ON CONFLICT (parent_run_id, name) DO UPDATE
        SET status = 'SUCCESS', answer = EXCLUDED.answer, child_run_id = EXCLUDED.child_run_id;

    PERFORM set_config('rlm.run_id', v_prev, false);
    RETURN jsonb_build_object('success', true, 'name', v_name,
                              'child_run_id', v_child, 'answer', v_answer);
END;
$$;

CREATE OR REPLACE FUNCTION agent_run_rlm(
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
        RAISE EXCEPTION 'agent_run_rlm 需要 p_question';
    END IF;

    INSERT INTO agent_runs (run_id, question, max_steps, paradigm, depth, max_depth, name)
    VALUES (v_run_id, p_question, COALESCE(p_max_steps, 10), 'rlm',
            0, GREATEST(COALESCE(p_max_depth, 1), 0), 'root');

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

-- 与独立版同名，便于两套库用同一调用方式
CREATE OR REPLACE FUNCTION rlm_run(
    p_question  text,
    p_context   text DEFAULT NULL,
    p_max_steps int  DEFAULT 10,
    p_max_depth int  DEFAULT 1
)
RETURNS text
LANGUAGE sql VOLATILE AS $$
    SELECT agent_run_rlm($1, $2, $3, $4)
$$;

-- CodeAct 主循环 + 可委派 RLM（不替换原 agent_run）
CREATE OR REPLACE FUNCTION agent_run_hybrid(
    p_question  text,
    p_max_steps int  DEFAULT 10,
    p_context   text DEFAULT NULL
)
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
    v_rlm     jsonb;
    v_has_ctx boolean := p_context IS NOT NULL AND p_context <> '';
    v_prev    text := current_setting('rlm.run_id', true);
BEGIN
    INSERT INTO agent_runs (run_id, question, max_steps, paradigm, depth, max_depth, name)
    VALUES (v_run_id, p_question, COALESCE(p_max_steps, 10), 'hybrid', 0, 1, 'root');

    PERFORM set_config('rlm.run_id', v_run_id, false);
    PERFORM env_set_text('question', p_question);
    IF v_has_ctx THEN
        PERFORM env_set_text('context', p_context);
    END IF;

    v_system := make_hybrid_prompt(50, v_has_ctx);

    WHILE v_used < COALESCE(p_max_steps, 10) LOOP
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
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN '失败：LLM 返回非法 JSON，run_id=' || v_run_id;
        END;
        PERFORM emit_step(v_run_id, 'llm', jsonb_build_object('raw', v_raw, 'thought', v_dec.thought));
        v_used := v_used + 1;

        IF v_dec.final_answer IS NOT NULL AND v_dec.action IS NULL THEN
            PERFORM emit_step(v_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
            PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
            RETURN v_dec.final_answer;
        END IF;

        IF v_dec.action = 'execute_sql' THEN
            v_obs := exec_sql_readonly(v_dec.sql, 50);
        ELSIF v_dec.action = 'rlm' THEN
            PERFORM set_config('rlm.run_id', v_run_id, false);
            v_rlm := rlm_spawn(COALESCE(v_dec.sql, p_question), 'hybrid-' || v_used::text);
            v_obs := v_rlm;
        ELSE
            v_obs := jsonb_build_object('success',false,'error','未知 action: '||COALESCE(v_dec.action,'null'));
        END IF;
        PERFORM emit_step(v_run_id, 'tool',
                jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text,
                                   'action', v_dec.action));
    END LOOP;

    PERFORM emit_step(v_run_id, 'error', jsonb_build_object('message','达到最大步数'));
    PERFORM set_config('rlm.run_id', COALESCE(v_prev,''), false);
    RETURN '达到最大步数，run_id=' || v_run_id;
END;
$$;

-- ============================================================
-- L4. 注册到共用 handlers / worker
-- ============================================================
CREATE OR REPLACE FUNCTION h_rlm_run(p_job jobs)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    v := agent_run_rlm(p_job.payload->>'question',
                       p_job.payload->>'context',
                       COALESCE((p_job.payload->>'max_steps')::int, 10),
                       COALESCE((p_job.payload->>'max_depth')::int, 1));
    UPDATE jobs SET status='DONE', result=jsonb_build_object('answer',v),
                run_id = (SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1),
                completed_at=now()
     WHERE job_id = p_job.job_id;
END;
$$;
COMMENT ON FUNCTION h_rlm_run(jobs) IS '{"job_handler":"rlm_run"}';

CREATE OR REPLACE FUNCTION h_hybrid_run(p_job jobs)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
    v := agent_run_hybrid(p_job.payload->>'question',
                          COALESCE((p_job.payload->>'max_steps')::int, 10),
                          p_job.payload->>'context');
    UPDATE jobs SET status='DONE', result=jsonb_build_object('answer',v),
                run_id = (SELECT run_id FROM agent_runs ORDER BY created_at DESC LIMIT 1),
                completed_at=now()
     WHERE job_id = p_job.job_id;
END;
$$;
COMMENT ON FUNCTION h_hybrid_run(jobs) IS '{"job_handler":"hybrid_run"}';

SELECT refresh_handlers();

-- ============================================================
-- 使用示例
-- ============================================================
-- -- 纯 RLM（与独立版同一调用）：
-- SELECT agent_run_rlm('public 模式下有多少张表？');
-- SELECT rlm_run('找出 context 里的 SECRET_TOKEN', '....SECRET_TOKEN=x....');
--
-- -- CodeAct 主循环，必要时委派 RLM：
-- SELECT agent_run_hybrid('先查有多少张表，再总结');
--
-- -- 队列（与原有 schema_all_tables 同一 worker）：
-- INSERT INTO jobs (job_type, payload) VALUES
--   ('rlm_run', '{"question":"有多少张表？"}'),
--   ('agent_run', '{"question":"有多少张表？"}');
-- SELECT worker();
--
-- -- 两种范式的 run 在同一张表：
-- SELECT run_id, paradigm, question FROM agent_runs ORDER BY created_at;
-- SELECT * FROM run_state('某-run-id');
