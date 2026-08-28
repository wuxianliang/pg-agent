-- ============================================================
-- PG-Agent v5 · named tools (W5)
-- Overlay apply_llm_response so action may be a registered llm_tool
-- name with JSON args. execute_sql remains. Activates agent_system v2.
-- ============================================================

CREATE OR REPLACE FUNCTION invoke_named_llm_tool(p_action text, p_action_input text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_fn      regprocedure;
    v_meta    jsonb;
    v_args    jsonb;
    v_json    jsonb;
    v_nsp     text;
    v_proname text;
    v_names   text[];
    v_types   text;
    v_n       int;
    v_i       int;
    v_aname   text;
    v_atype   text;
    v_j       jsonb;
    v_jt      text;
    v_parts   text[] := '{}';
    v_lit     text;
    v_out     jsonb;
    v_key     text;
BEGIN
    SELECT fn, metadata INTO v_fn, v_meta
      FROM plugin_bindings
     WHERE binding_type = 'llm_tool' AND binding_name = p_action;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'error', '未知 action: '||COALESCE(p_action,'null'),
            'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Resolution');
    END IF;

    BEGIN
        v_json := COALESCE(p_action_input, '{}')::jsonb;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Validation',
            'Problem', 'action_input must be a JSON object');
    END;
    IF jsonb_typeof(v_json) <> 'object' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Validation',
            'Problem', 'action_input must be a JSON object');
    END IF;

    v_args := v_meta->'llm_tool'->'args';
    FOR v_key IN SELECT jsonb_object_keys(v_json) LOOP
        IF v_args IS NULL OR NOT (v_args ? v_key) THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Validation',
                'Problem', 'unknown arg '||v_key);
        END IF;
    END LOOP;

    SELECT n.nspname, p.proname, p.proargnames, p.proargtypes::text, p.pronargs
      INTO v_nsp, v_proname, v_names, v_types, v_n
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE p.oid = v_fn;

    v_n := COALESCE(v_n, 0);
    FOR v_i IN 1..v_n LOOP
        v_aname := v_names[v_i];
        v_atype := ((string_to_array(v_types, ' ')::oid[])[v_i]::regtype)::text;
        IF NOT (v_json ? v_aname) THEN
            CONTINUE;
        END IF;
        IF v_atype NOT IN ('text', 'integer', 'boolean', 'jsonb') THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Validation',
                'Problem', 'unsupported pg type '||v_atype);
        END IF;
        v_j := v_json -> v_aname;
        v_jt := jsonb_typeof(v_j);
        BEGIN
            IF v_j = 'null'::jsonb THEN
                v_lit := 'NULL::' || v_atype;
            ELSIF v_atype = 'text' THEN
                IF v_jt NOT IN ('string', 'number', 'boolean') THEN
                    RAISE EXCEPTION 'type';
                END IF;
                v_lit := quote_literal(v_j #>> '{}') || '::text';
            ELSIF v_atype = 'integer' THEN
                IF v_jt = 'number' THEN
                    v_lit := (v_j #>> '{}') || '::integer';
                ELSIF v_jt = 'string' AND (v_j #>> '{}') ~ '^-?[0-9]+$' THEN
                    v_lit := quote_literal(v_j #>> '{}') || '::integer';
                ELSE
                    RAISE EXCEPTION 'type';
                END IF;
            ELSIF v_atype = 'boolean' THEN
                IF v_jt = 'boolean' THEN
                    v_lit := (v_j #>> '{}') || '::boolean';
                ELSIF v_jt = 'string' AND lower(v_j #>> '{}') IN ('true','false') THEN
                    v_lit := quote_literal(v_j #>> '{}') || '::boolean';
                ELSE
                    RAISE EXCEPTION 'type';
                END IF;
            ELSE
                v_lit := quote_literal(v_j::text) || '::jsonb';
            END IF;
        EXCEPTION WHEN OTHERS THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Validation',
                'Problem', 'type mismatch for '||v_aname);
        END;
        v_parts := array_append(v_parts, format('%I := %s', v_aname, v_lit));
    END LOOP;

    BEGIN
        IF array_length(v_parts, 1) IS NULL THEN
            EXECUTE format('SELECT %I.%I()', v_nsp, v_proname) INTO v_out;
        ELSE
            EXECUTE format('SELECT %I.%I(%s)', v_nsp, v_proname, array_to_string(v_parts, ', '))
               INTO v_out;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'NAMED_TOOL_ERROR', 'Phase', 'Execution',
            'Problem', SQLERRM, 'tool', p_action, 'args', v_json);
    END;

    RETURN jsonb_build_object(
        'success', true,
        'data', jsonb_build_array(jsonb_build_object(p_action, v_out)),
        'row_count', 1,
        'tool', p_action,
        'args', v_json
    );
END;
$$;

CREATE OR REPLACE FUNCTION apply_llm_response(p_run_id text, p_raw text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_dec     llm_decision;
    v_obs     jsonb;
    v_used    int;
    v_max     int;
    v_qid     bigint;
    v_hash    text;
    v_prev    text;
    v_status  text;
    v_answer  text;
    v_err     text;
    v_key     text;
    v_nested  jsonb;
    v_async   boolean;
    v_wait    text;
    v_meta    jsonb;
    v_budget  jsonb;
    v_tool    jsonb;
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

    v_meta := sanitize_step_metrics(
        COALESCE(NULLIF(current_setting('pg_agent.pending_metrics', true), ''), '{}')::jsonb
    );
    PERFORM emit_step(p_run_id, 'llm',
                      jsonb_build_object('raw', p_raw, 'thought', v_dec.thought),
                      v_meta);

    v_budget := record_budget_step(p_run_id, v_meta);
    IF COALESCE((v_budget->>'exceeded')::boolean, false) THEN
        PERFORM emit_step(p_run_id, 'error', jsonb_build_object(
            'message', COALESCE(v_budget->>'reason', 'budget_exceeded'),
            'budget', v_budget
        ), v_meta);
        UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
        RETURN jsonb_build_object(
            'done', true, 'ok', false, 'run_id', p_run_id,
            'error', v_budget->>'reason', 'budget', v_budget
        );
    END IF;

    IF v_dec.final_answer IS NOT NULL AND v_dec.action IS NULL THEN
        PERFORM emit_step(p_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
        UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
        RETURN jsonb_build_object('done', true, 'ok', true, 'answer', v_dec.final_answer,
                                 'run_id', p_run_id);
    END IF;

    IF v_dec.action = 'execute_sql' THEN
        v_obs := exec_sql_readonly(v_dec.sql, 50);
        v_tool := jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text);
    ELSIF v_dec.action IS NOT NULL THEN
        v_obs := invoke_named_llm_tool(v_dec.action, v_dec.sql);
        v_tool := jsonb_build_object(
            'tool', v_dec.action,
            'args', COALESCE(v_obs->'args', '{}'::jsonb),
            'observation', v_obs::text);
    ELSE
        v_obs := jsonb_build_object('success',false,'error','未知 action: '||COALESCE(v_dec.action,'null'));
        v_tool := jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text);
    END IF;
    PERFORM emit_step(p_run_id, 'tool', v_tool);

    IF COALESCE((v_obs->>'success')::boolean, false)
       AND jsonb_typeof(v_obs->'data') = 'array'
       AND jsonb_array_length(v_obs->'data') = 1
       AND jsonb_typeof(v_obs->'data'->0) = 'object' THEN
        SELECT jsonb_object_keys(v_obs->'data'->0) INTO v_key;
        v_nested := v_obs->'data'->0->v_key;
        SELECT COALESCE((metadata->'llm_tool'->>'async')::boolean, false)
          INTO v_async
          FROM plugin_bindings
         WHERE binding_type = 'llm_tool'
           AND binding_name = v_key;
        IF COALESCE(v_async, false)
           AND jsonb_typeof(v_nested) = 'object'
           AND COALESCE((v_nested->>'success')::boolean, false)
           AND COALESCE((v_nested->>'defer')::boolean, false) THEN
            v_wait := COALESCE(v_nested->>'wait_kind', 'queue');
            PERFORM emit_step(p_run_id, 'wait', jsonb_build_object(
                'wait_kind', v_wait,
                'queue', v_nested->>'queue',
                'request_id', v_nested->>'request_id',
                'tool', v_key
            ));
            UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
            RETURN jsonb_build_object(
                'done', false, 'ok', true, 'waiting', true,
                'wait_kind', v_wait, 'run_id', p_run_id
            );
        END IF;
    END IF;

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

SELECT compile_prompt_recipe(
    'agent_system',
    2,
    xmlparse(document $poml$
<poml>
  <role generate="if_missing">你是运行在 PostgreSQL 内部的 AI 数据 Agent。action 可以是 execute_sql，或已注册的 wb_* 工具名。</role>
  <task generate="if_missing">规则：
1. 按名调用 wb_*：action 为工具名，action_input 为 JSON 对象，键与函数参数同名。
2. execute_sql 仍可用，action_input 为单条 SQL，不要分号结尾。
3. 一次一个 action。
4. 写操作禁止（只读模式）；禁止 DDL。
5. 信息足够后填 final_answer 并将 action 设为 null。
6. 同一数据库会话可跨轮次保留键值：SELECT session_set('k','v')；SELECT session_get('k')。
7. observation 外层 success=true 不等于嵌套工具 success。</task>
  <output-format generate="if_missing">严格按此 JSON 回复（不要输出其他文字）：
{"thought":"...","action":"execute_sql 或 wb_* 或 null","action_input":"SQL 或 JSON 对象","final_answer":"答案"}</output-format>
  <tools/>
  <question/>
  <history/>
</poml>
$poml$),
    true
);
