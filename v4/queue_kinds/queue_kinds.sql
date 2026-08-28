-- ============================================================
-- PG-Agent v4 · queue kinds (W3)
--
-- Additional queues + handlers. apply_queue_result() is not modified.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'embed_requests') THEN
        PERFORM pgmq.create('embed_requests');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'embed_requests_dlq') THEN
        PERFORM pgmq.create('embed_requests_dlq');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'sql_heavy_requests') THEN
        PERFORM pgmq.create('sql_heavy_requests');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'sql_heavy_requests_dlq') THEN
        PERFORM pgmq.create('sql_heavy_requests_dlq');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'human_inbox') THEN
        PERFORM pgmq.create('human_inbox');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'human_inbox_dlq') THEN
        PERFORM pgmq.create('human_inbox_dlq');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS human_requests (
    request_id  text PRIMARY KEY,
    run_id      text NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    prompt      text NOT NULL,
    context     text,
    msg_id      bigint,
    status      text NOT NULL CHECK (status IN ('OPEN', 'ANSWERED', 'CANCELLED')),
    answer      text,
    answered_by text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz
);

CREATE OR REPLACE FUNCTION _resume_from_queue_result(
    p_run_id text,
    p_wait_kind text,
    p_result jsonb
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_qid bigint;
    v_used int;
    v_max int;
BEGIN
    SELECT max_steps INTO v_max FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;

    PERFORM emit_step(p_run_id, 'tool', jsonb_build_object(
        'observation', jsonb_build_object(
            'success', true,
            'wait_kind', p_wait_kind,
            'result', p_result
        )::text
    ));

    SELECT count(*) FILTER (WHERE kind = 'llm') INTO v_used
      FROM agent_steps WHERE run_id = p_run_id;
    IF v_used >= COALESCE(v_max, 10) THEN
        PERFORM emit_step(p_run_id, 'error', jsonb_build_object('message', '达到最大步数'));
        RETURN jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id, 'error', 'max_steps');
    END IF;

    v_qid := enqueue_llm_request(p_run_id);
    RETURN jsonb_build_object(
        'done', false, 'ok', true, 'enqueued', v_qid,
        'run_id', p_run_id, 'resumed', true, 'wait_kind', p_wait_kind
    );
END;
$$;

CREATE OR REPLACE FUNCTION apply_embed_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    RETURN _resume_from_queue_result(p_run_id, 'embed', p_result);
END;
$$;

COMMENT ON FUNCTION apply_embed_result(text, jsonb) IS $v4$
{"plugin":{"name":"plugin_embed"},"queue_handler":{"queue_name":"embed_requests","queue_kind":"embed","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v4$;

CREATE OR REPLACE FUNCTION apply_sql_heavy_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    RETURN _resume_from_queue_result(p_run_id, 'sql_heavy', p_result);
END;
$$;

COMMENT ON FUNCTION apply_sql_heavy_result(text, jsonb) IS $v4$
{"plugin":{"name":"plugin_sql_heavy"},"queue_handler":{"queue_name":"sql_heavy_requests","queue_kind":"sql_heavy","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v4$;

CREATE OR REPLACE FUNCTION apply_human_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    RETURN _resume_from_queue_result(p_run_id, 'human', p_result);
END;
$$;

COMMENT ON FUNCTION apply_human_result(text, jsonb) IS $v4$
{"plugin":{"name":"plugin_human"},"queue_handler":{"queue_name":"human_inbox","queue_kind":"human_inbox","consumer":"human","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v4$;

CREATE OR REPLACE FUNCTION human_inbox_list()
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object(
        'success', true,
        'requests', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'request_id', request_id,
                       'run_id', run_id,
                       'prompt', prompt,
                       'context', context,
                       'msg_id', msg_id,
                       'status', status,
                       'created_at', created_at
                   ) ORDER BY created_at)
              FROM human_requests
             WHERE status = 'OPEN'
        ), '[]'::jsonb)
    )
$$;

CREATE OR REPLACE FUNCTION human_answer(
    p_request_id text,
    p_answer text,
    p_answered_by text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_req    human_requests;
    v_apply  jsonb;
BEGIN
    IF p_request_id IS NULL OR trim(p_request_id) = '' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'HUMAN_INBOX_ERROR', 'Phase', 'Validation',
            'Problem', 'request_id required', 'conflict', false);
    END IF;
    IF p_answer IS NULL OR trim(p_answer) = '' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'HUMAN_INBOX_ERROR', 'Phase', 'Validation',
            'Problem', 'answer required', 'conflict', false);
    END IF;

    SELECT * INTO v_req
      FROM human_requests
     WHERE request_id = p_request_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'HUMAN_INBOX_ERROR', 'Phase', 'Resolution',
            'Problem', format('missing request: %s', p_request_id),
            'conflict', true);
    END IF;
    IF v_req.status <> 'OPEN' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'HUMAN_INBOX_ERROR', 'Phase', 'Resolution',
            'Problem', format('request %s is %s', p_request_id, v_req.status),
            'conflict', true, 'status', v_req.status);
    END IF;

    UPDATE human_requests
       SET status = 'ANSWERED',
           answer = p_answer,
           answered_by = p_answered_by,
           answered_at = now()
     WHERE request_id = p_request_id;

    v_apply := apply_queue_result(
        'human_inbox',
        v_req.msg_id,
        v_req.run_id,
        jsonb_build_object(
            'request_id', p_request_id,
            'answer', p_answer,
            'answered_by', p_answered_by
        )
    );

    IF v_req.msg_id IS NOT NULL THEN
        PERFORM pgmq.archive('human_inbox', v_req.msg_id);
    END IF;

    RETURN jsonb_build_object(
        'success', true,
        'request_id', p_request_id,
        'run_id', v_req.run_id,
        'apply', v_apply
    );
END;
$$;

CREATE OR REPLACE FUNCTION run_state(p_run_id text)
RETURNS TABLE(status text, steps_used int, answer text, error text)
LANGUAGE sql STABLE AS $$
    WITH last_step AS (
        SELECT kind, payload
          FROM agent_steps
         WHERE run_id = p_run_id
         ORDER BY seq DESC
         LIMIT 1
    )
    SELECT CASE
             WHEN bool_or(s.kind = 'final') THEN 'SUCCESS'
             WHEN bool_or(s.kind = 'error') THEN 'ERROR'
             WHEN (SELECT kind FROM last_step) = 'wait'
                  AND COALESCE((SELECT payload->>'wait_kind' FROM last_step), '') IN ('human', 'human_inbox')
                  THEN 'WAITING_HUMAN'
             WHEN (SELECT kind FROM last_step) = 'wait' THEN 'WAITING_QUEUE'
             ELSE 'RUNNING'
           END,
           count(*) FILTER (WHERE s.kind = 'llm')::int,
           max(s.payload->>'answer') FILTER (WHERE s.kind = 'final'),
           max(s.payload->>'message') FILTER (WHERE s.kind = 'error')
      FROM agent_steps s
     WHERE s.run_id = p_run_id
$$;

-- Overlay: same v3 apply path, plus async wait detection. No queue-kind IF in
-- apply_queue_result; wait is decided from plugin_bindings.llm_tool.async.
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

    -- Async defer: only registered llm_tool.async=true may emit wait.
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
