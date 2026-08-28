-- ============================================================
-- PG-Agent v4 · observability + budget (W6)
--
-- Bounded non-secret step metadata. SQL records worker-chosen
-- model/provider; it does not route.
-- ============================================================

ALTER TABLE agent_steps ADD COLUMN IF NOT EXISTS meta jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS max_total_tokens bigint;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS max_cost_usd numeric(20, 8);

DROP FUNCTION IF EXISTS emit_step(text, text, jsonb);

CREATE OR REPLACE FUNCTION emit_step(
    p_run_id text,
    p_kind text,
    p_payload jsonb,
    p_meta jsonb DEFAULT '{}'::jsonb
)
RETURNS void
LANGUAGE sql VOLATILE AS $$
    INSERT INTO agent_steps (run_id, kind, payload, meta)
    VALUES (p_run_id, p_kind, p_payload, COALESCE(p_meta, '{}'::jsonb));
$$;

CREATE OR REPLACE FUNCTION sanitize_step_metrics(p_metrics jsonb)
RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE((
        SELECT jsonb_object_agg(key, value)
          FROM jsonb_each(COALESCE(p_metrics, '{}'::jsonb))
         WHERE key IN (
             'queue', 'queue_kind', 'msg_id', 'worker_id', 'attempts',
             'duration_ms', 'model', 'provider',
             'input_tokens', 'output_tokens', 'total_tokens', 'cost_usd'
         )
    ), '{}'::jsonb)
$$;

CREATE OR REPLACE FUNCTION run_budget(p_run_id text)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object(
        'run_id', p_run_id,
        'max_total_tokens', (SELECT max_total_tokens FROM agent_runs WHERE run_id = p_run_id),
        'max_cost_usd', (SELECT max_cost_usd FROM agent_runs WHERE run_id = p_run_id),
        'total_tokens', COALESCE((
            SELECT (payload->>'cumulative_tokens')::bigint
              FROM agent_steps
             WHERE run_id = p_run_id AND kind = 'budget'
             ORDER BY seq DESC LIMIT 1
        ), 0),
        'cost_usd', COALESCE((
            SELECT (payload->>'cumulative_cost_usd')::numeric
              FROM agent_steps
             WHERE run_id = p_run_id AND kind = 'budget'
             ORDER BY seq DESC LIMIT 1
        ), 0),
        'steps', (SELECT count(*) FROM agent_steps WHERE run_id = p_run_id AND kind = 'budget')
    )
$$;

CREATE OR REPLACE FUNCTION record_budget_step(p_run_id text, p_metrics jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run agent_runs;
    v_in bigint;
    v_out bigint;
    v_tot bigint;
    v_cost numeric;
    v_cum_tok bigint;
    v_cum_cost numeric;
    v_need boolean;
    v_has boolean;
    v_ex boolean := false;
    v_reason text;
BEGIN
    SELECT * INTO v_run FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;

    v_need := (v_run.max_total_tokens IS NOT NULL OR v_run.max_cost_usd IS NOT NULL);
    v_in := NULLIF(p_metrics->>'input_tokens', '')::bigint;
    v_out := NULLIF(p_metrics->>'output_tokens', '')::bigint;
    v_tot := NULLIF(p_metrics->>'total_tokens', '')::bigint;
    v_cost := NULLIF(p_metrics->>'cost_usd', '')::numeric;
    v_has := (v_tot IS NOT NULL OR v_in IS NOT NULL OR v_out IS NOT NULL OR v_cost IS NOT NULL);

    IF v_tot IS NULL AND (v_in IS NOT NULL OR v_out IS NOT NULL) THEN
        v_tot := COALESCE(v_in, 0) + COALESCE(v_out, 0);
    END IF;

    IF v_need AND NOT v_has THEN
        v_ex := true;
        v_reason := 'budget_unavailable';
        v_tot := 0;
        v_cost := 0;
    END IF;

    SELECT COALESCE(max((payload->>'cumulative_tokens')::bigint), 0),
           COALESCE(max((payload->>'cumulative_cost_usd')::numeric), 0)
      INTO v_cum_tok, v_cum_cost
      FROM agent_steps
     WHERE run_id = p_run_id AND kind = 'budget';

    v_cum_tok := v_cum_tok + COALESCE(v_tot, 0);
    v_cum_cost := v_cum_cost + COALESCE(v_cost, 0);

    IF NOT v_ex AND v_run.max_total_tokens IS NOT NULL AND v_cum_tok > v_run.max_total_tokens THEN
        v_ex := true;
        v_reason := 'token_exceeded';
    END IF;
    IF NOT v_ex AND v_run.max_cost_usd IS NOT NULL AND v_cum_cost > v_run.max_cost_usd THEN
        v_ex := true;
        v_reason := 'cost_exceeded';
    END IF;

    PERFORM emit_step(p_run_id, 'budget', jsonb_build_object(
        'delta_tokens', COALESCE(v_tot, 0),
        'delta_cost_usd', COALESCE(v_cost, 0),
        'cumulative_tokens', v_cum_tok,
        'cumulative_cost_usd', v_cum_cost,
        'max_total_tokens', v_run.max_total_tokens,
        'max_cost_usd', v_run.max_cost_usd,
        'exceeded', v_ex,
        'reason', v_reason
    ), sanitize_step_metrics(p_metrics));

    RETURN jsonb_build_object(
        'exceeded', v_ex,
        'reason', v_reason,
        'cumulative_tokens', v_cum_tok,
        'cumulative_cost_usd', v_cum_cost
    );
END;
$$;

CREATE OR REPLACE FUNCTION apply_queue_failure(
    p_queue_name text,
    p_msg_id bigint,
    p_run_id text,
    p_error text,
    p_meta jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    PERFORM emit_step(
        p_run_id, 'error',
        jsonb_build_object('message', p_error, 'queue', p_queue_name, 'msg_id', p_msg_id),
        sanitize_step_metrics(p_meta)
    );
    RETURN fail_run(p_run_id, p_error);
END;
$$;

CREATE OR REPLACE FUNCTION apply_llm_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_raw text;
    v_out jsonb;
    v_metrics jsonb;
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
    v_metrics := sanitize_step_metrics(COALESCE(p_result->'metrics', '{}'::jsonb));
    PERFORM set_config('pg_agent.pending_metrics', v_metrics::text, true);
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
    ELSE
        v_obs := jsonb_build_object('success',false,'error','未知 action: '||COALESCE(v_dec.action,'null'));
    END IF;
    PERFORM emit_step(p_run_id, 'tool', jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text));

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
