-- ============================================================
-- PG-Agent v4 · async queue-submit tools (W3)
--
-- Run id is taken from agent_current_run_id() only.
-- ============================================================

CREATE OR REPLACE FUNCTION wb_request_embedding(p_text text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_run text;
    v_req text;
    v_msg bigint;
BEGIN
    v_run := agent_current_run_id();
    IF v_run IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'wb_request_embedding 只能在 apply 事务内调用（需要 agent_current_run_id）',
            'Solution', '通过 worker apply_queue_result 路径调用，不要从任意会话传入 run_id。');
    END IF;
    IF p_text IS NULL OR trim(p_text) = '' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'p_text 为空',
            'Solution', '提供非空文本。');
    END IF;
    IF length(p_text) > 8000 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', format('p_text 超长: %s', length(p_text)),
            'Solution', '缩短到 8000 字符以内。');
    END IF;

    v_req := gen_random_uuid()::text;
    SELECT pgmq.send(
        'embed_requests',
        jsonb_build_object('run_id', v_run, 'request_id', v_req, 'text', p_text),
        jsonb_build_object('x-pgmq-group', v_run)
    ) INTO v_msg;

    RETURN jsonb_build_object(
        'success', true, 'defer', true, 'wait_kind', 'embed',
        'queue', 'embed_requests', 'request_id', v_req, 'msg_id', v_msg);
END;
$$;

COMMENT ON FUNCTION wb_request_embedding(text) IS $v4$
{"plugin":{"name":"plugin_async_tasks"},"llm_tool":{"name":"wb_request_embedding","description":"把一段文本送入 embedding 队列并暂停当前 run；结果由库外 worker 写回后才会继续。不能传入 run_id","args":{"p_text":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}
$v4$;

CREATE OR REPLACE FUNCTION wb_request_sql_heavy(
    p_sql text,
    p_max_rows integer DEFAULT 50,
    p_timeout_ms integer DEFAULT 120000
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_run text;
    v_req text;
    v_msg bigint;
    v_err jsonb;
    v_rows int;
    v_to int;
    v_low text;
BEGIN
    v_run := agent_current_run_id();
    IF v_run IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'wb_request_sql_heavy 只能在 apply 事务内调用',
            'Solution', '通过 worker apply_queue_result 路径调用。');
    END IF;

    v_err := _wb_validate_select_sql(p_sql, 16000);
    IF v_err IS NOT NULL THEN
        RETURN v_err;
    END IF;

    v_low := lower(p_sql);
    IF v_low ~ 'pg_temp' OR v_low ~ 'wb_temp_view_'
       OR v_low ~ '\msession_set\M' OR v_low ~ '\msession_get\M' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'sql-heavy 不能依赖 pg_temp / wb_temp_view_* / session_set / session_get',
            'Solution', '改写为不引用 sticky TEMP 状态的查询。');
    END IF;

    v_rows := COALESCE(p_max_rows, 50);
    IF v_rows < 1 OR v_rows > 50 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', format('p_max_rows 超出范围: %s', v_rows),
            'Solution', '传入 1..50。');
    END IF;
    v_to := COALESCE(p_timeout_ms, 120000);
    IF v_to < 1 OR v_to > 120000 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', format('p_timeout_ms 超出范围: %s', v_to),
            'Solution', '传入 1..120000。');
    END IF;

    v_req := gen_random_uuid()::text;
    SELECT pgmq.send(
        'sql_heavy_requests',
        jsonb_build_object(
            'run_id', v_run,
            'request_id', v_req,
            'sql', p_sql,
            'max_rows', v_rows,
            'timeout_ms', v_to
        ),
        jsonb_build_object('x-pgmq-group', v_run)
    ) INTO v_msg;

    RETURN jsonb_build_object(
        'success', true, 'defer', true, 'wait_kind', 'sql_heavy',
        'queue', 'sql_heavy_requests', 'request_id', v_req, 'msg_id', v_msg);
END;
$$;

COMMENT ON FUNCTION wb_request_sql_heavy(text, integer, integer) IS $v4$
{"plugin":{"name":"plugin_async_tasks"},"llm_tool":{"name":"wb_request_sql_heavy","description":"把一条只读 SELECT/WITH 送到独立连接的 sql-heavy 队列并暂停 run；看不见 sticky TEMP VIEW/KV。不能传入 run_id","args":{"p_sql":"text","p_max_rows":"integer","p_timeout_ms":"integer"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}
$v4$;

CREATE OR REPLACE FUNCTION wb_request_human(p_prompt text, p_context text DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_run text;
    v_req text;
    v_msg bigint;
BEGIN
    v_run := agent_current_run_id();
    IF v_run IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'wb_request_human 只能在 apply 事务内调用',
            'Solution', '通过 worker apply_queue_result 路径调用。');
    END IF;
    IF p_prompt IS NULL OR trim(p_prompt) = '' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'p_prompt 为空',
            'Solution', '提供要问人的非空提示。');
    END IF;
    IF length(p_prompt) > 4000 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'p_prompt 超长',
            'Solution', '缩短到 4000 字符以内。');
    END IF;
    IF p_context IS NOT NULL AND length(p_context) > 4000 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'QUEUE_SUBMIT_ERROR', 'Phase', 'Validation',
            'Problem', 'p_context 超长',
            'Solution', '缩短到 4000 字符以内。');
    END IF;

    v_req := gen_random_uuid()::text;
    INSERT INTO human_requests (request_id, run_id, prompt, context, status)
    VALUES (v_req, v_run, p_prompt, p_context, 'OPEN');

    SELECT pgmq.send(
        'human_inbox',
        jsonb_build_object(
            'run_id', v_run,
            'request_id', v_req,
            'prompt', p_prompt,
            'context', p_context
        ),
        jsonb_build_object('x-pgmq-group', v_run)
    ) INTO v_msg;

    UPDATE human_requests SET msg_id = v_msg WHERE request_id = v_req;

    RETURN jsonb_build_object(
        'success', true, 'defer', true, 'wait_kind', 'human',
        'queue', 'human_inbox', 'request_id', v_req, 'msg_id', v_msg);
END;
$$;

COMMENT ON FUNCTION wb_request_human(text, text) IS $v4$
{"plugin":{"name":"plugin_async_tasks"},"llm_tool":{"name":"wb_request_human","description":"向 human_inbox 提交一个问题并暂停 run，等待 human_answer()；自动化 worker 不会消费该队列。不能传入 run_id","args":{"p_prompt":"text","p_context":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}
$v4$;
