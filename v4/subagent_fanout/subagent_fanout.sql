-- ============================================================
-- PG-Agent v4 · subagent fan-out (W4)
--
-- Flat PGMQ parent/child. No nested SQL model loop.
-- ============================================================

ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS parent_run_id text;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS depth int NOT NULL DEFAULT 0;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS max_depth int NOT NULL DEFAULT 4;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS run_name text;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS session_mode text NOT NULL DEFAULT 'temp';

CREATE TABLE IF NOT EXISTS agent_wait_groups (
    wait_id        text PRIMARY KEY,
    parent_run_id  text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    expected_count int  NOT NULL,
    wait_kind      text NOT NULL,
    resumed_at     timestamptz
);

CREATE TABLE IF NOT EXISTS agent_wait_members (
    wait_id      text NOT NULL REFERENCES agent_wait_groups(wait_id) ON DELETE CASCADE,
    child_run_id text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    seq          int  NOT NULL,
    run_name     text NOT NULL,
    PRIMARY KEY (wait_id, child_run_id),
    UNIQUE (wait_id, seq),
    UNIQUE (wait_id, run_name)
);

CREATE TABLE IF NOT EXISTS agent_wait_deliveries (
    wait_id      text NOT NULL REFERENCES agent_wait_groups(wait_id) ON DELETE CASCADE,
    child_run_id text NOT NULL,
    delivered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (wait_id, child_run_id)
);

CREATE OR REPLACE FUNCTION maybe_resume_parent(p_child_run_id text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_wait_id text;
    v_grp     agent_wait_groups;
    v_n       int;
    v_results jsonb;
    v_qid     bigint;
BEGIN
    SELECT wait_id INTO v_wait_id
      FROM agent_wait_members
     WHERE child_run_id = p_child_run_id;
    IF v_wait_id IS NULL THEN
        RETURN jsonb_build_object('resumed', false, 'reason', 'not_a_child');
    END IF;

    SELECT * INTO v_grp
      FROM agent_wait_groups
     WHERE wait_id = v_wait_id
     FOR UPDATE;

    INSERT INTO agent_wait_deliveries (wait_id, child_run_id)
    VALUES (v_wait_id, p_child_run_id)
    ON CONFLICT (wait_id, child_run_id) DO NOTHING;

    SELECT count(*) INTO v_n
      FROM agent_wait_deliveries
     WHERE wait_id = v_wait_id;

    IF v_n < v_grp.expected_count THEN
        RETURN jsonb_build_object('resumed', false, 'reason', 'waiting_siblings', 'got', v_n);
    END IF;
    IF v_grp.resumed_at IS NOT NULL THEN
        RETURN jsonb_build_object('resumed', false, 'reason', 'already_resumed', 'replayed', true);
    END IF;

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'seq', m.seq,
               'name', m.run_name,
               'child_run_id', m.child_run_id,
               'status', rs.status,
               'answer', rs.answer,
               'error', rs.error
           ) ORDER BY m.seq), '[]'::jsonb)
      INTO v_results
      FROM agent_wait_members m
      LEFT JOIN LATERAL (
          SELECT status, answer, error FROM run_state(m.child_run_id)
      ) rs ON TRUE
     WHERE m.wait_id = v_wait_id;

    PERFORM emit_step(v_grp.parent_run_id, 'tool', jsonb_build_object(
        'observation', jsonb_build_object(
            'success', true,
            'wait_kind', 'subagent',
            'wait_id', v_wait_id,
            'children', v_results
        )::text
    ));

    UPDATE agent_wait_groups
       SET resumed_at = now()
     WHERE wait_id = v_wait_id;

    v_qid := enqueue_llm_request(v_grp.parent_run_id);
    RETURN jsonb_build_object(
        'resumed', true, 'wait_id', v_wait_id, 'enqueued', v_qid,
        'parent_run_id', v_grp.parent_run_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION apply_llm_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_raw text;
    v_out jsonb;
BEGIN
    IF p_result IS NULL THEN
        RAISE EXCEPTION 'apply_llm_result: result is null';
    END IF;
    v_raw := p_result->>'raw';
    IF v_raw IS NULL OR trim(v_raw) = '' THEN
        IF p_result ? 'thought' OR p_result ? 'final_answer' OR p_result ? 'action' THEN
            v_raw := p_result::text;
        ELSE
            RAISE EXCEPTION 'apply_llm_result: missing raw text';
        END IF;
    END IF;
    v_out := apply_llm_response(p_run_id, v_raw);
    IF COALESCE((v_out->>'done')::boolean, false) THEN
        PERFORM maybe_resume_parent(p_run_id);
    END IF;
    RETURN v_out;
END;
$$;

COMMENT ON FUNCTION apply_llm_result(text, jsonb) IS $v4$
{"plugin":{"name":"plugin_llm"},"queue_handler":{"queue_name":"llm_requests","queue_kind":"llm","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v4$;

CREATE OR REPLACE FUNCTION fail_run(p_run_id text, p_message text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_status text;
    v_out jsonb;
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
    v_out := jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id, 'error', p_message);
    PERFORM maybe_resume_parent(p_run_id);
    RETURN v_out;
END;
$$;

CREATE OR REPLACE FUNCTION wb_spawn_agents(p_prompts jsonb, p_names jsonb DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_parent  agent_runs;
    v_run     text;
    v_n       int;
    v_i       int;
    v_prompt  text;
    v_name    text;
    v_child   text;
    v_wait    text;
    v_names   text[] := '{}';
    v_ids     jsonb := '[]'::jsonb;
    v_depth   int;
BEGIN
    v_run := agent_current_run_id();
    IF v_run IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
            'Problem', 'wb_spawn_agents 只能在 apply 事务内调用');
    END IF;
    SELECT * INTO v_parent FROM agent_runs WHERE run_id = v_run;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Resolution',
            'Problem', 'unknown parent run');
    END IF;

    v_depth := LEAST(COALESCE(v_parent.max_depth, 4), 4);
    IF COALESCE(v_parent.depth, 0) >= v_depth THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
            'Problem', format('depth limit: parent depth %s max %s', v_parent.depth, v_depth));
    END IF;

    IF p_prompts IS NULL OR jsonb_typeof(p_prompts) <> 'array' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
            'Problem', 'prompts 必须是 1..8 个非空字符串的 JSON 数组');
    END IF;
    v_n := jsonb_array_length(p_prompts);
    IF v_n < 1 OR v_n > 8 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
            'Problem', format('prompts count %s not in 1..8', v_n));
    END IF;
    IF p_names IS NOT NULL THEN
        IF jsonb_typeof(p_names) <> 'array' OR jsonb_array_length(p_names) <> v_n THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
                'Problem', 'names 必须与 prompts 等长');
        END IF;
    END IF;

    FOR v_i IN 0..v_n-1 LOOP
        IF jsonb_typeof(p_prompts->v_i) <> 'string' THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
                'Problem', format('prompt %s is not a string', v_i));
        END IF;
        v_prompt := p_prompts->>v_i;
        IF v_prompt IS NULL OR trim(v_prompt) = '' THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
                'Problem', format('prompt %s is empty', v_i));
        END IF;
        IF p_names IS NULL THEN
            v_name := format('child-%s', v_i + 1);
        ELSE
            IF jsonb_typeof(p_names->v_i) <> 'string' THEN
                RETURN jsonb_build_object(
                    'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
                    'Problem', format('name %s is not a string', v_i));
            END IF;
            v_name := p_names->>v_i;
        END IF;
        IF v_name IS NULL OR trim(v_name) = '' THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
                'Problem', format('name %s is empty', v_i));
        END IF;
        IF v_name = ANY (v_names) THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'SPAWN_ERROR', 'Phase', 'Validation',
                'Problem', format('duplicate name: %s', v_name));
        END IF;
        v_names := array_append(v_names, v_name);
    END LOOP;

    v_wait := gen_random_uuid()::text;
    INSERT INTO agent_wait_groups (wait_id, parent_run_id, expected_count, wait_kind)
    VALUES (v_wait, v_run, v_n, 'subagent');

    FOR v_i IN 0..v_n-1 LOOP
        v_child := gen_random_uuid()::text;
        v_prompt := p_prompts->>v_i;
        v_name := v_names[v_i + 1];
        INSERT INTO agent_runs (
            run_id, question, max_steps, max_rows,
            parent_run_id, depth, max_depth, run_name, session_mode
        ) VALUES (
            v_child,
            v_prompt,
            LEAST(COALESCE(v_parent.max_steps, 10), 6),
            COALESCE(v_parent.max_rows, 50),
            v_run,
            COALESCE(v_parent.depth, 0) + 1,
            v_parent.max_depth,
            v_name,
            COALESCE(v_parent.session_mode, 'temp')
        );
        INSERT INTO agent_wait_members (wait_id, child_run_id, seq, run_name)
        VALUES (v_wait, v_child, v_i + 1, v_name);
        PERFORM enqueue_llm_request(v_child);
        v_ids := v_ids || jsonb_build_array(jsonb_build_object(
            'seq', v_i + 1, 'name', v_name, 'child_run_id', v_child));
    END LOOP;

    RETURN jsonb_build_object(
        'success', true, 'defer', true, 'wait_kind', 'subagent',
        'queue', 'llm_requests', 'request_id', v_wait,
        'children', v_ids);
END;
$$;

COMMENT ON FUNCTION wb_spawn_agents(jsonb, jsonb) IS $v4$
{"plugin":{"name":"plugin_subagent"},"llm_tool":{"name":"wb_spawn_agents","description":"把 1..8 个子问题扇出成独立 child runs（PGMQ group=child_run_id），父 run 进入 wait，全部结束后只唤醒一次。不能传入 run_id","args":{"p_prompts":"jsonb","p_names":"jsonb"},"returns":"jsonb","session_scope":"run_connection","capability":"spawn","async":true}}
$v4$;
