-- ============================================================
-- PG-Agent v5 · prompt pipeline (W4)
--
-- Ordered SQL retrieval into PGMQ messages.
-- Missing generatable parts raise until W6 bootstrap exists.
-- ============================================================

CREATE OR REPLACE FUNCTION assemble_prompt_messages(p_run_id text)
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
    SELECT prompt_recipe_name, prompt_recipe_version INTO v_name, v_ver
      FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND OR v_name IS NULL THEN
        RETURN jsonb_build_object(
            'status', 'error', 'success', false,
            'Type', 'PROMPT_ASSEMBLY_ERROR', 'Phase', 'Recipe',
            'Problem', 'run has no pinned recipe',
            'Solution', 'agent_start after an active recipe exists');
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
                        'component', v_slot.component_type);

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

CREATE OR REPLACE FUNCTION prepare_llm_request(p_run_id text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_run  agent_runs;
    v_asm  jsonb;
    v_used int;
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
        RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: missing generatable parts';
    END IF;
    IF v_asm->>'status' IS DISTINCT FROM 'ready' THEN
        RAISE EXCEPTION 'PROMPT_ASSEMBLY_ERROR: unexpected assemble status';
    END IF;

    SELECT count(*) FILTER (WHERE kind='llm') INTO v_used
      FROM agent_steps WHERE run_id = p_run_id;

    RETURN jsonb_build_object(
        'request_type', 'llm',
        'run_id', p_run_id,
        'question', v_run.question,
        'step', v_used + 1,
        'max_steps', v_run.max_steps,
        'messages', v_asm->'messages',
        'prompt_recipe', jsonb_build_object(
            'name', v_asm->>'recipe_name',
            'version', (v_asm->>'recipe_version')::int
        ),
        'model', current_setting('openai.model', true),
        'api_uri', current_setting('openai.api_uri', true)
    );
END;
$$;
