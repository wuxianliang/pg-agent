CREATE OR REPLACE FUNCTION v15.v15_io_sqlstate(p_code text) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE p_code
    WHEN 'V15_INVOKE_FORM' THEN 'P1503'
    WHEN 'V15_DIALECT' THEN 'P1511'
    WHEN 'V15_DDL' THEN 'P1512'
    WHEN 'V15_IO_EXHAUSTED' THEN 'P1513'
    WHEN 'V15_BUDGET_EXHAUSTED' THEN 'P1514'
    WHEN 'V15_RECURSION_EXCEEDED' THEN 'P1519'
    WHEN 'V15_ITERATION_EXCEEDED' THEN 'P1520'
    WHEN 'V15_VALUE_INVALID' THEN 'P1524'
    WHEN 'V15_DELIVERY_CONFLICT' THEN 'P1527'
    WHEN 'V15_CHILD_ERROR' THEN 'P1528'
    WHEN 'V15_HOOK_ABORT' THEN 'P1538'
    WHEN 'V15_PROVIDER_REJECTED' THEN 'P1539'
    ELSE NULL
  END
$fn$;

CREATE OR REPLACE FUNCTION v15.v15_govern_known_code(p_code text) RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT p_code IN (
    'V15_STALE_FENCE',
    'V15_ATTEMPT_NOT_SETTLEABLE',
    'V15_INVOKE_FORM',
    'V15_GOVERNANCE_MISSING',
    'V15_GOVERNANCE_RAISE',
    'V15_INVALID_EFFECT',
    'V15_TOOL_UNAUTHORIZED',
    'V15_GOVERNANCE_FAULT',
    'V15_SCOPE_CONFLICT',
    'V15_HISTORY_SCOPE',
    'V15_DIALECT',
    'V15_DDL',
    'V15_IO_EXHAUSTED',
    'V15_BUDGET_EXHAUSTED',
    'V15_PRINT_AND_RETURN',
    'V15_PHASE_CONTRACT',
    'V15_EXTERNAL_TOOL',
    'V15_RECURSION_DISABLED',
    'V15_RECURSION_EXCEEDED',
    'V15_ITERATION_EXCEEDED',
    'V15_MANIFEST_DIGEST',
    'V15_ROLE',
    'V15_INVALID_TRANSITION',
    'V15_VALUE_INVALID',
    'V15_HANDLER_FAILED',
    'V15_STATEMENT_TIMEOUT',
    'V15_DELIVERY_CONFLICT',
    'V15_CHILD_ERROR',
    'V15_RAISE',
    'V15_DEPTH_SELF',
    'V15_CONFIG_LOCAL',
    'V15_BASELINE_IMMUTABLE',
    'V15_BLACKBOARD_CONFLICT',
    'V15_INPUT_CONFLICT',
    'V15_EFFECT_CONFLICT',
    'V15_HANDLER_DIGEST',
    'V15_HANDLER_SHAPE',
    'V15_HOOK_ABORT',
    'V15_PROVIDER_REJECTED',
    'V15_VALIDATION_FAILED'
  )
$fn$;

CREATE FUNCTION v15.v15_provider_reject_unstarted(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text,
  p_class text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iteration integer;
  v_request_status text;
  v_iteration_status text;
  v_inv v15.invokes;
  v_att v15.llm_attempts;
  v_n integer;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL
     OR p_attempt_fence IS NULL
     OR p_invoke_fence IS NULL
     OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id, r.iteration
    INTO v_invoke, v_iteration
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_inv := v15.v15_repl_lock(v_invoke);
  SELECT * INTO v_att
  FROM v15.llm_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF v_att.status IN ('unknown', 'failed', 'settled') THEN
    RAISE EXCEPTION 'V15_ATTEMPT_NOT_SETTLEABLE' USING ERRCODE = 'P1502';
  END IF;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.fence IS DISTINCT FROM p_attempt_fence
     OR v_inv.fence IS DISTINCT FROM p_invoke_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  PERFORM v15.v15_repl_check_holder(v_inv, p_invoke_fence, p_owner);
  SELECT r.status, it.status INTO v_request_status, v_iteration_status
  FROM v15.llm_requests r
  JOIN v15.iterations it ON it.invoke_id = r.invoke_id AND it.iteration = r.iteration
  WHERE r.request_id = v_att.request_id;
  IF v_request_status IS DISTINCT FROM 'open'
     OR v_iteration_status IS DISTINCT FROM 'llm'
     OR v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF p_class IS NULL OR p_class NOT IN (
    'credentials_absent', 'model_not_allowlisted', 'model_missing', 'endpoint_rejected'
  ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_io_pool_release(
    v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, false, 0
  );
  UPDATE v15.llm_attempts a
  SET status = 'failed',
      calls_charged = false,
      lease_owner = NULL,
      lease_until = NULL,
      response = NULL,
      revision = a.revision + 1
  WHERE a.attempt_id = p_attempt_id
    AND a.status = 'leased'
    AND NOT a.call_started
    AND NOT a.calls_charged;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  UPDATE v15.llm_requests r
  SET status = 'exhausted', revision = r.revision + 1
  WHERE r.invoke_id = v_invoke
    AND r.iteration = v_iteration
    AND r.status = 'open';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_event(
    v_invoke, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'provider_rejected',
      'attempt_id', p_attempt_id,
      'class', p_class,
      'call_started', false
    ),
    v_inv.fence
  );
  PERFORM v15.v15_io_terminal(
    v_invoke, v_iteration, 'V15_PROVIDER_REJECTED', false, p_attempt_id
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_provider_reject_started(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text,
  p_detail jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iteration integer;
  v_request_status text;
  v_iteration_status text;
  v_inv v15.invokes;
  v_att v15.llm_attempts;
  v_class text;
  v_http integer;
  v_finish text;
  v_n integer;
  v_valid boolean := false;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL
     OR p_attempt_fence IS NULL
     OR p_invoke_fence IS NULL
     OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id, r.iteration
    INTO v_invoke, v_iteration
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_inv := v15.v15_repl_lock(v_invoke);
  SELECT * INTO v_att
  FROM v15.llm_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF v_att.status IN ('unknown', 'failed', 'settled') THEN
    RAISE EXCEPTION 'V15_ATTEMPT_NOT_SETTLEABLE' USING ERRCODE = 'P1502';
  END IF;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.fence IS DISTINCT FROM p_attempt_fence
     OR v_inv.fence IS DISTINCT FROM p_invoke_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  PERFORM v15.v15_repl_check_holder(v_inv, p_invoke_fence, p_owner);
  SELECT r.status, it.status INTO v_request_status, v_iteration_status
  FROM v15.llm_requests r
  JOIN v15.iterations it ON it.invoke_id = r.invoke_id AND it.iteration = r.iteration
  WHERE r.request_id = v_att.request_id;
  IF v_request_status IS DISTINCT FROM 'open'
     OR v_iteration_status IS DISTINCT FROM 'llm'
     OR NOT v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF pg_catalog.jsonb_typeof(p_detail) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF NOT v15.v15_govern_exact_keys(p_detail, ARRAY['class', 'http_status', 'finish_reason'])
     OR pg_catalog.jsonb_typeof(p_detail->'class') IS DISTINCT FROM 'string'
     OR pg_catalog.jsonb_typeof(p_detail->'finish_reason') NOT IN ('null', 'string') THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_class := p_detail->>'class';
  v_finish := p_detail->>'finish_reason';
  v_http := v15.v15_govern_json_int(p_detail->'http_status', 300, 599);
  IF p_detail->'http_status' <> 'null'::jsonb AND v_http IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_valid :=
    (v_class = 'http_status'
     AND v_http IS NOT NULL
     AND v_http BETWEEN 400 AND 499
     AND v_http NOT IN (408, 429)
     AND v_finish IS NULL)
    OR (v_class = 'finish_reason'
        AND v_finish IN ('content_filter', 'model_mismatch')
        AND v_http IS NULL)
    OR (v_class = 'request_invalid'
        AND v_http IS NULL
        AND v_finish IS NULL);
  IF v_valid IS NOT TRUE THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_io_pool_release(
    v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, true, 0
  );
  UPDATE v15.llm_attempts a
  SET status = 'unknown',
      calls_charged = true,
      lease_owner = NULL,
      lease_until = NULL,
      response = NULL,
      revision = a.revision + 1
  WHERE a.attempt_id = p_attempt_id
    AND a.status = 'leased'
    AND a.call_started
    AND NOT a.calls_charged;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  UPDATE v15.llm_requests r
  SET status = 'exhausted', revision = r.revision + 1
  WHERE r.invoke_id = v_invoke
    AND r.iteration = v_iteration
    AND r.status = 'open';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_event(
    v_invoke, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'provider_rejected',
      'attempt_id', p_attempt_id,
      'class', v_class,
      'call_started', true,
      'http_status', p_detail->'http_status',
      'finish_reason', p_detail->'finish_reason'
    ),
    v_inv.fence
  );
  PERFORM v15.v15_io_terminal(
    v_invoke, v_iteration, 'V15_PROVIDER_REJECTED', false, p_attempt_id
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_provider_abandon(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text,
  p_detail jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iteration integer;
  v_request_status text;
  v_iteration_status text;
  v_inv v15.invokes;
  v_att v15.llm_attempts;
  v_class text;
  v_http integer;
  v_finish text;
  v_n integer;
  v_valid boolean := false;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL
     OR p_attempt_fence IS NULL
     OR p_invoke_fence IS NULL
     OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id, r.iteration
    INTO v_invoke, v_iteration
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_inv := v15.v15_repl_lock(v_invoke);
  SELECT * INTO v_att
  FROM v15.llm_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF v_att.status IN ('unknown', 'failed', 'settled') THEN
    RAISE EXCEPTION 'V15_ATTEMPT_NOT_SETTLEABLE' USING ERRCODE = 'P1502';
  END IF;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.fence IS DISTINCT FROM p_attempt_fence
     OR v_inv.fence IS DISTINCT FROM p_invoke_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  PERFORM v15.v15_repl_check_holder(v_inv, p_invoke_fence, p_owner);
  SELECT r.status, it.status INTO v_request_status, v_iteration_status
  FROM v15.llm_requests r
  JOIN v15.iterations it ON it.invoke_id = r.invoke_id AND it.iteration = r.iteration
  WHERE r.request_id = v_att.request_id;
  IF v_request_status IS DISTINCT FROM 'open'
     OR v_iteration_status IS DISTINCT FROM 'llm'
     OR NOT v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF pg_catalog.jsonb_typeof(p_detail) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF NOT v15.v15_govern_exact_keys(p_detail, ARRAY['class', 'http_status', 'finish_reason'])
     OR pg_catalog.jsonb_typeof(p_detail->'class') IS DISTINCT FROM 'string'
     OR pg_catalog.jsonb_typeof(p_detail->'finish_reason') NOT IN ('null', 'string') THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_class := p_detail->>'class';
  v_finish := p_detail->>'finish_reason';
  v_http := v15.v15_govern_json_int(p_detail->'http_status', 300, 599);
  IF p_detail->'http_status' <> 'null'::jsonb AND v_http IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_valid :=
    (v_class = 'transport'
     AND v_finish IS NULL
     AND (v_http IS NULL OR v_http BETWEEN 300 AND 399 OR v_http = 400))
    OR (v_class = 'http_status'
        AND v_http IS NOT NULL
        AND (v_http IN (400, 408, 429) OR v_http BETWEEN 500 AND 599)
        AND v_finish IS NULL)
    OR (v_class = 'finish_reason'
        AND v_finish IN ('insufficient_system_resource', 'aborted', 'other')
        AND v_http IS NULL)
    OR (v_class IN ('unpriced', 'usage_invalid')
        AND v_http IS NULL
        AND v_finish IS NULL);
  IF v_valid IS NOT TRUE THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_io_pool_release(
    v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, true, 0
  );
  UPDATE v15.llm_attempts a
  SET status = 'unknown',
      calls_charged = true,
      lease_owner = NULL,
      lease_until = NULL,
      response = NULL,
      revision = a.revision + 1
  WHERE a.attempt_id = p_attempt_id
    AND a.status = 'leased'
    AND a.call_started
    AND NOT a.calls_charged;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_event(
    v_invoke, 'span', 'llm_query', 'retry', NULL,
    pg_catalog.jsonb_build_object(
      'old_attempt_id', p_attempt_id,
      'old_status', 'unknown',
      'new_attempt_id', 'null'::jsonb,
      'provider', p_detail
    ),
    v_inv.fence
  );
  PERFORM v15.v15_io_reclaim_invoke(v_invoke);
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

ALTER FUNCTION v15.v15_provider_reject_unstarted(uuid, bigint, bigint, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_provider_reject_started(uuid, bigint, bigint, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_provider_abandon(uuid, bigint, bigint, text, jsonb) OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_provider_reject_unstarted(uuid, bigint, bigint, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_provider_reject_started(uuid, bigint, bigint, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_provider_abandon(uuid, bigint, bigint, text, jsonb) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_provider_reject_unstarted(uuid, bigint, bigint, text, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_provider_reject_started(uuid, bigint, bigint, text, jsonb) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_provider_abandon(uuid, bigint, bigint, text, jsonb) TO v15_worker;

CREATE FUNCTION v15.v15_invoke_lease_seconds(p_invoke_id uuid) RETURNS numeric
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_seconds numeric;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  SELECT EXTRACT(EPOCH FROM (i.lease_until - pg_catalog.clock_timestamp()))
    INTO v_seconds
  FROM v15.invokes i
  WHERE i.invoke_id = p_invoke_id;
  RETURN v_seconds;
END;
$fn$;

ALTER FUNCTION v15.v15_invoke_lease_seconds(uuid) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_invoke_lease_seconds(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v15.v15_invoke_lease_seconds(uuid) TO v15_worker;
