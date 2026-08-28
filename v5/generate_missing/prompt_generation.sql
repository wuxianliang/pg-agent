-- ============================================================
-- PG-Agent v5 · generate_missing (W6)
-- Visible first llm turn stores recipe-global parts via wb_store_prompt_part.
-- ============================================================

CREATE OR REPLACE FUNCTION assemble_prompt_messages_for(p_run_id text, p_recipe_name text, p_recipe_version integer)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    c_max_slots int := 32;
    c_max_msgs  int := 128;
    c_max_bytes int := 262144;
    c_max_chars int := 8000;
    v_name      text;
    v_ver       int;
    v_slot      record;
    v_fn        regprocedure;
    v_nsp       text;
    v_proname   text;
    v_cfg       jsonb;
    v_env       jsonb;
    v_msgs      jsonb := '[]'::jsonb;
    v_item      jsonb;
    v_trace     jsonb := '[]'::jsonb;
    v_missing   jsonb := '[]'::jsonb;
    v_nslots    int := 0;
    v_role      text;
    v_content   text;
    v_err       text;
BEGIN
    v_name := p_recipe_name;
    v_ver := p_recipe_version;
    IF v_name IS NULL OR v_ver IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'error', 'success', false,
            'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Recipe',
            'Problem', 'run has no pinned recipe',
            'Solution', 'agent_start after an active recipe exists');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM agent_runs WHERE run_id = p_run_id) THEN
        RETURN jsonb_build_object(
            'status', 'error', 'success', false,
            'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Recipe',
            'Problem', 'unknown run');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM prompt_recipes WHERE recipe_name = v_name AND version = v_ver
    ) THEN
        RETURN jsonb_build_object(
            'status', 'error', 'success', false,
            'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Recipe',
            'Problem', 'pinned recipe missing',
            'Solution', 'do not delete recipes with pinned runs');
    END IF;

    FOR v_slot IN
        SELECT * FROM prompt_slots
         WHERE recipe_name = v_name AND recipe_version = v_ver
         ORDER BY position
    LOOP
        v_nslots := v_nslots + 1;
        IF v_nslots > c_max_slots THEN
            RETURN jsonb_build_object(
                'status', 'error', 'success', false,
                'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Validation',
                'Problem', 'more than 32 slots',
                'Solution', 'split the recipe');
        END IF;

        SELECT fn INTO v_fn
          FROM plugin_bindings
         WHERE binding_type = 'prompt_slot'
           AND binding_name = v_slot.retriever_name;
        IF NOT FOUND THEN
            RETURN jsonb_build_object(
                'status', 'error', 'success', false,
                'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Resolution',
                'Problem', 'missing retriever ' || v_slot.retriever_name,
                'Solution', 'refresh_plugins after installing retrievers');
        END IF;

        v_cfg := COALESCE(v_slot.config, '{}'::jsonb)
                 || jsonb_build_object(
                        'slot_key', v_slot.slot_key,
                        'component', v_slot.component_type,
                        'recipe_name', v_name,
                        'recipe_version', v_ver);

        SELECT n.nspname, p.proname INTO v_nsp, v_proname
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE p.oid = v_fn;

        BEGIN
            EXECUTE format('SELECT %I.%I($1::text, $2::jsonb)', v_nsp, v_proname)
               INTO v_env USING p_run_id, v_cfg;
        EXCEPTION WHEN OTHERS THEN
            RETURN jsonb_build_object(
                'status', 'error', 'success', false,
                'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Execution',
                'Problem', 'retriever ' || v_slot.retriever_name || ' failed: ' || SQLERRM,
                'Solution', 'fix the retriever');
        END;

        IF v_env IS NULL OR jsonb_typeof(v_env) <> 'object' THEN
            RETURN jsonb_build_object(
                'status', 'error', 'success', false,
                'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Validation',
                'Problem', 'malformed retriever envelope',
                'Solution', 'retrievers must return a jsonb object');
        END IF;

        IF COALESCE((v_env->>'success')::boolean, false) IS NOT TRUE THEN
            IF v_env->>'Type' = 'PROMPT_PART_MISSING' THEN
                IF NOT v_slot.required THEN
                    v_trace := v_trace || jsonb_build_array(jsonb_build_object(
                        'slot_key', v_slot.slot_key, 'omitted', true));
                    CONTINUE;
                END IF;
                IF v_slot.generation_policy = 'if_missing' THEN
                    v_missing := v_missing || jsonb_build_array(jsonb_build_object(
                        'position', v_slot.position,
                        'slot_key', v_slot.slot_key,
                        'component', v_slot.component_type,
                        'generation_policy', v_slot.generation_policy,
                        'config', v_slot.config
                    ));
                    v_trace := v_trace || jsonb_build_array(jsonb_build_object(
                        'slot_key', v_slot.slot_key, 'missing', true));
                    CONTINUE;
                END IF;
            END IF;
            RETURN jsonb_build_object(
                'status', 'error', 'success', false,
                'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Resolution',
                'Problem', COALESCE(v_env->>'Problem', 'required part missing and not generatable'),
                'slot_key', v_slot.slot_key);
        END IF;

        IF jsonb_typeof(v_env->'messages') <> 'array' THEN
            RETURN jsonb_build_object(
                'status', 'error', 'success', false,
                'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Validation',
                'Problem', 'retriever messages must be an array');
        END IF;

        FOR v_item IN SELECT * FROM jsonb_array_elements(v_env->'messages')
        LOOP
            v_role := v_item->>'role';
            v_content := v_item->>'content';
            IF v_role IS NULL OR v_role NOT IN ('system','user','assistant','tool') THEN
                RETURN jsonb_build_object(
                    'status', 'error', 'success', false,
                    'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Validation',
                    'Problem', 'invalid message role');
            END IF;
            IF v_content IS NULL OR v_content = '' OR length(v_content) > c_max_chars THEN
                RETURN jsonb_build_object(
                    'status', 'error', 'success', false,
                    'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Validation',
                    'Problem', 'invalid message content');
            END IF;
            v_msgs := v_msgs || jsonb_build_array(
                jsonb_build_object('role', v_role, 'content', v_content));
        END LOOP;

        v_trace := v_trace || jsonb_build_array(jsonb_build_object(
            'slot_key', v_slot.slot_key,
            'component', v_slot.component_type,
            'n', jsonb_array_length(v_env->'messages')));
    END LOOP;

    IF jsonb_array_length(v_msgs) > c_max_msgs THEN
        RETURN jsonb_build_object(
            'status', 'error', 'success', false,
            'Type', 'PROMPT_TOO_LARGE', 'Phase', 'Validation',
            'Problem', 'more than 128 messages');
    END IF;
    IF octet_length(v_msgs::text) > c_max_bytes THEN
        RETURN jsonb_build_object(
            'status', 'error', 'success', false,
            'Type', 'PROMPT_TOO_LARGE', 'Phase', 'Validation',
            'Problem', 'serialized messages exceed 262144 bytes');
    END IF;

    IF jsonb_array_length(v_missing) > 0 THEN
        RETURN jsonb_build_object(
            'status', 'missing',
            'recipe_name', v_name,
            'recipe_version', v_ver,
            'missing', v_missing,
            'slot_trace', v_trace
        );
    END IF;

    RETURN jsonb_build_object(
        'status', 'ready',
        'recipe_name', v_name,
        'recipe_version', v_ver,
        'messages', v_msgs,
        'slot_trace', v_trace
    );
END;
$$;


CREATE OR REPLACE FUNCTION assemble_prompt_messages(p_run_id text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_name text;
    v_ver  int;
BEGIN
    SELECT prompt_recipe_name, prompt_recipe_version INTO v_name, v_ver
      FROM agent_runs WHERE run_id = p_run_id;
    RETURN assemble_prompt_messages_for(p_run_id, v_name, v_ver);
END;
$$;

CREATE OR REPLACE FUNCTION prompt_live_missing(p_run_id text, p_config jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_name text;
    v_ver  int;
    v_list jsonb;
    v_txt  text;
BEGIN
    SELECT prompt_recipe_name, prompt_recipe_version INTO v_name, v_ver
      FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'PROMPT_ASSEMBLY_ERROR',
            'Phase', 'Recipe', 'Problem', 'unknown run');
    END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'slot_key', s.slot_key,
               'component', s.component_type,
               'hint', s.config->>'hint'
           ) ORDER BY s.position), '[]'::jsonb)
      INTO v_list
      FROM prompt_slots s
      LEFT JOIN prompt_parts p
        ON p.recipe_name = s.recipe_name
       AND p.recipe_version = s.recipe_version
       AND p.slot_key = s.slot_key
     WHERE s.recipe_name = v_name
       AND s.recipe_version = v_ver
       AND s.required
       AND s.generation_policy = 'if_missing'
       AND p.slot_key IS NULL;
    v_txt := 'Missing prompt parts (store with wb_store_prompt_part): ' || v_list::text;
    RETURN jsonb_build_object(
        'success', true,
        'messages', jsonb_build_array(jsonb_build_object('role','system','content', v_txt)),
        'source', 'live',
        'component', 'task'
    );
END;
$$;

COMMENT ON FUNCTION prompt_live_missing(text, jsonb) IS $v5$
{"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"prompt_live_missing","description":"List missing required generatable parts of the pinned user recipe","component_types":["task"],"source":"live","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
$v5$;

CREATE OR REPLACE FUNCTION wb_store_prompt_part(p_slot_key text, p_value jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run   text;
    v_name  text;
    v_ver   int;
    v_q     text;
    v_slot  prompt_slots%ROWTYPE;
    v_kind  text;
    v_n     int;
    v_txt   text;
    v_item  jsonb;
    v_role  text;
    v_content text;
BEGIN
    v_run := agent_current_run_id();
    IF v_run IS NULL OR v_run = '' THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Validation', 'Problem', 'no current run');
    END IF;
    SELECT prompt_recipe_name, prompt_recipe_version, question
      INTO v_name, v_ver, v_q
      FROM agent_runs WHERE run_id = v_run;
    SELECT * INTO v_slot FROM prompt_slots
     WHERE recipe_name = v_name AND recipe_version = v_ver AND slot_key = p_slot_key;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Resolution', 'Problem', 'unknown slot_key');
    END IF;
    IF v_slot.generation_policy <> 'if_missing' THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Validation', 'Problem', 'slot is not generatable');
    END IF;
    IF v_slot.component_type IN ('tools','question','history') THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Validation', 'Problem', 'live slot cannot be stored');
    END IF;
    IF p_value IS NULL THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Validation', 'Problem', 'value required');
    END IF;
    IF v_slot.component_type = 'example' THEN
        v_kind := 'messages';
        IF jsonb_typeof(p_value) <> 'array'
           OR jsonb_array_length(p_value) < 1
           OR jsonb_array_length(p_value) > 16 THEN
            RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
                'Phase', 'Validation', 'Problem', 'example must be 1..16 messages');
        END IF;
        FOR v_item IN SELECT * FROM jsonb_array_elements(p_value) LOOP
            v_role := v_item->>'role';
            v_content := v_item->>'content';
            IF v_role IS NULL OR v_role NOT IN ('user','assistant')
               OR v_content IS NULL OR v_content = '' OR length(v_content) > 8000 THEN
                RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
                    'Phase', 'Validation', 'Problem', 'invalid example message');
            END IF;
        END LOOP;
    ELSE
        v_kind := 'text';
        IF jsonb_typeof(p_value) <> 'string' THEN
            RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
                'Phase', 'Validation', 'Problem', 'text component requires a JSON string');
        END IF;
        v_txt := p_value #>> '{}';
        IF v_txt IS NULL OR length(v_txt) < 1 OR length(v_txt) > 8000 THEN
            RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
                'Phase', 'Validation', 'Problem', 'text length 1..8000');
        END IF;
        IF v_txt = v_q THEN
            RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
                'Phase', 'Validation', 'Problem', 'stored text must not equal the user question');
        END IF;
    END IF;
    v_txt := COALESCE(v_txt, p_value::text);
    IF v_txt ~* 'api[_-]?key' OR v_txt ~ 'Bearer ' OR v_txt ~ 'sk-[A-Za-z0-9]'
       OR v_txt ~ '(^|")/(etc|usr|Users|home)/' OR v_txt ~ '[A-Za-z]:\\\\' THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Validation', 'Problem', 'value failed hygiene check');
    END IF;
    IF jsonb_typeof(p_value) = 'object' AND (p_value ? 'choices' OR p_value ? 'usage') THEN
        RETURN jsonb_build_object('success', false, 'Type', 'NAMED_TOOL_ERROR',
            'Phase', 'Validation', 'Problem', 'looks like a provider payload');
    END IF;

    INSERT INTO prompt_parts (
        recipe_name, recipe_version, slot_key, component_type,
        value_kind, value, source, generator_request_id, content_hash
    ) VALUES (
        v_name, v_ver, p_slot_key, v_slot.component_type,
        v_kind, p_value, 'generated', v_run, prompt_part_hash(p_value)
    )
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN jsonb_build_object(
        'success', true,
        'stored', v_n > 0,
        'replayed', v_n = 0,
        'slot_key', p_slot_key,
        'recipe_name', v_name,
        'recipe_version', v_ver
    );
END;
$$;

COMMENT ON FUNCTION wb_store_prompt_part(text, jsonb) IS $v5$
{"plugin":{"name":"plugin_prompt_components"},"llm_tool":{"name":"wb_store_prompt_part","description":"Store a generated recipe-global prompt part (role/task/example/output_format). First writer wins.","args":{"p_slot_key":"text","p_value":"jsonb"},"returns":"jsonb","session_scope":"run_connection","capability":"prompt_mutation"}}
$v5$;

CREATE OR REPLACE FUNCTION prompt_user_parts_missing(p_run_id text)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1
          FROM agent_runs r
          JOIN prompt_slots s
            ON s.recipe_name = r.prompt_recipe_name
           AND s.recipe_version = r.prompt_recipe_version
          LEFT JOIN prompt_parts p
            ON p.recipe_name = s.recipe_name
           AND p.recipe_version = s.recipe_version
           AND p.slot_key = s.slot_key
         WHERE r.run_id = p_run_id
           AND s.required
           AND s.generation_policy = 'if_missing'
           AND p.slot_key IS NULL
    )
$$;

CREATE OR REPLACE FUNCTION prepare_llm_request(p_run_id text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_run   agent_runs;
    v_asm   jsonb;
    v_boot  jsonb;
    v_bname text := 'agent_system_generate';
    v_bver  int;
    v_used  int;
    v_mode  text := NULL;
    v_msgs  jsonb;
BEGIN
    SELECT * INTO v_run FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;

    v_asm := assemble_prompt_messages(p_run_id);
    IF v_asm IS NULL THEN
        RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: assemble returned null';
    END IF;
    IF v_asm->>'status' = 'error' THEN
        RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: %', COALESCE(v_asm->>'Problem', v_asm::text);
    END IF;

    IF v_asm->>'status' = 'missing' THEN
        SELECT version INTO v_bver
          FROM prompt_recipes WHERE recipe_name = v_bname AND active;
        IF v_bver IS NULL THEN
            RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: bootstrap recipe missing';
        END IF;
        v_boot := assemble_prompt_messages_for(p_run_id, v_bname, v_bver);
        IF v_boot->>'status' IS DISTINCT FROM 'ready' THEN
            RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: bootstrap assemble failed: %',
                COALESCE(v_boot->>'Problem', v_boot->>'status');
        END IF;
        v_msgs := v_boot->'messages';
        v_mode := 'generate_missing';
    ELSIF v_asm->>'status' = 'ready' THEN
        v_msgs := v_asm->'messages';
    ELSE
        RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: unexpected assemble status';
    END IF;

    SELECT count(*) FILTER (WHERE kind='llm') INTO v_used
      FROM agent_steps WHERE run_id = p_run_id;

    RETURN jsonb_strip_nulls(jsonb_build_object(
        'request_type', 'llm',
        'run_id', p_run_id,
        'question', v_run.question,
        'step', v_used + 1,
        'max_steps', v_run.max_steps,
        'messages', v_msgs,
        'prompt_recipe', jsonb_build_object(
            'name', v_run.prompt_recipe_name,
            'version', v_run.prompt_recipe_version
        ),
        'prompt_mode', v_mode,
        'missing_parts', CASE WHEN v_mode = 'generate_missing' THEN v_asm->'missing' END,
        'model', current_setting('openai.model', true),
        'api_uri', current_setting('openai.api_uri', true)
    ));
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
        IF prompt_user_parts_missing(p_run_id) THEN
            SELECT count(*) FILTER (WHERE kind='llm') INTO v_used
              FROM agent_steps WHERE run_id = p_run_id;
            IF v_used >= v_max THEN
                PERFORM emit_step(p_run_id, 'error', jsonb_build_object(
                    'message', 'missing_prompt_parts'));
                UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
                RETURN jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id,
                                         'error', 'missing_prompt_parts');
            END IF;
            v_qid := enqueue_llm_request(p_run_id);
            UPDATE agent_runs SET last_applied_hash = v_hash WHERE run_id = p_run_id;
            RETURN jsonb_build_object('done', false, 'ok', true, 'enqueued', v_qid,
                                     'run_id', p_run_id, 'prompt_mode', 'generate_missing');
        END IF;
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



SELECT refresh_plugins();

INSERT INTO prompt_recipes (recipe_name, version, source_xml, format_version, active)
VALUES (
    'agent_system_generate',
    1,
    xmlparse(document '<poml><role>bootstrap</role></poml>'),
    1,
    true
);

INSERT INTO prompt_slots (
    recipe_name, recipe_version, position, slot_key, component_type,
    retriever_name, required, generation_policy, config
) VALUES
    ('agent_system_generate', 1, 10, 'generate_role', 'role',
     'prompt_stored_part', true, 'never', '{"slot_key":"generate_role"}'::jsonb),
    ('agent_system_generate', 1, 20, 'generate_task', 'task',
     'prompt_stored_part', true, 'never', '{"slot_key":"generate_task"}'::jsonb),
    ('agent_system_generate', 1, 50, 'tools', 'tools',
     'prompt_live_tools', true, 'never', '{"slot_key":"tools"}'::jsonb),
    ('agent_system_generate', 1, 60, 'missing_list', 'task',
     'prompt_live_missing', true, 'never', '{"slot_key":"missing_list"}'::jsonb),
    ('agent_system_generate', 1, 100, 'question', 'question',
     'prompt_live_question', true, 'never', '{"slot_key":"question"}'::jsonb),
    ('agent_system_generate', 1, 110, 'history', 'history',
     'prompt_live_history', true, 'never', '{"slot_key":"history"}'::jsonb);

INSERT INTO prompt_parts (
    recipe_name, recipe_version, slot_key, component_type,
    value_kind, value, source, content_hash
) VALUES
    ('agent_system_generate', 1, 'generate_role', 'role', 'text',
     to_jsonb('You write missing recipe-global prompt parts for the pinned user recipe.'::text),
     'seeded', prompt_part_hash(to_jsonb('You write missing recipe-global prompt parts for the pinned user recipe.'::text))),
    ('agent_system_generate', 1, 'generate_task', 'task', 'text',
     to_jsonb($t$Call wb_store_prompt_part for each missing slot_key. p_value is a JSON string for text slots. Use the user question only as a hint; do not store the question as the part. If replayed=true, another run already stored that slot — continue with remaining slots. Do not emit final_answer until missing slots are stored.$t$::text),
     'seeded', prompt_part_hash(to_jsonb($t$Call wb_store_prompt_part for each missing slot_key. p_value is a JSON string for text slots. Use the user question only as a hint; do not store the question as the part. If replayed=true, another run already stored that slot — continue with remaining slots. Do not emit final_answer until missing slots are stored.$t$::text)));
