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
    WHEN 'V15_REPLAY_DIVERGED' THEN 'P1541'
    WHEN 'V15_REPLAY_MISSING' THEN 'P1542'
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
    'V15_VALIDATION_FAILED',
    'V15_REPLAY_DIVERGED',
    'V15_REPLAY_MISSING'
  )
$fn$;

CREATE FUNCTION v15.v15_replay_invoke_path(p_invoke_id uuid) RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_parent uuid;
  v_parent_path text;
  v_n integer;
  v_iter integer;
  v_stmt integer;
  v_bind text;
BEGIN
  IF p_invoke_id IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT i.parent_invoke_id INTO v_parent
  FROM v15.invokes i
  WHERE i.invoke_id = p_invoke_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_parent IS NULL THEN
    RETURN '';
  END IF;
  v_parent_path := v15.v15_replay_invoke_path(v_parent);
  SELECT count(*) INTO v_n
  FROM v15.statements s
  WHERE s.child_invoke_id = p_invoke_id;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.iteration, s.stmt_index, s.bind_name
    INTO v_iter, v_stmt, v_bind
  FROM v15.statements s
  WHERE s.child_invoke_id = p_invoke_id;
  IF v_bind IS NULL OR pg_catalog.char_length(v_bind) < 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_bind ~ '[/:]' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  RETURN v_parent_path || '/' || v_iter::text || ':' || v_stmt::text || ':' || v_bind;
END;
$fn$;

CREATE FUNCTION v15.v15_replay_attempt_context(p_attempt_id uuid) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_att v15.llm_attempts;
  v_req v15.llm_requests;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT * INTO v_att
  FROM v15.llm_attempts a
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO STRICT v_req
  FROM v15.llm_requests r
  WHERE r.request_id = v_att.request_id;
  RETURN pg_catalog.jsonb_build_object(
    'attempt_id', v_att.attempt_id,
    'invoke_id', v_req.invoke_id,
    'iteration', v_req.iteration,
    'logical_digest', v_req.logical_digest,
    'lease_owner', v_att.lease_owner,
    'path', v15.v15_replay_invoke_path(v_req.invoke_id),
    'call_started', v_att.call_started
  );
END;
$fn$;

CREATE FUNCTION v15.v15_replay_lock_attempt(
  p_attempt_id uuid,
  p_owner text,
  OUT o_att v15.llm_attempts,
  OUT o_req v15.llm_requests,
  OUT o_inv v15.invokes
) RETURNS record
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iter integer;
  v_iter_status text;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id, r.iteration INTO v_invoke, v_iter
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO o_inv
  FROM v15.invokes i
  WHERE i.invoke_id = v_invoke
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO o_att
  FROM v15.llm_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF o_att.status IN ('unknown', 'failed', 'settled') THEN
    RAISE EXCEPTION 'V15_ATTEMPT_NOT_SETTLEABLE' USING ERRCODE = 'P1502';
  END IF;
  IF o_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF o_inv.status IS DISTINCT FROM 'leased'
     OR o_inv.lease_owner IS DISTINCT FROM p_owner
     OR o_att.lease_owner IS DISTINCT FROM p_owner
     OR o_inv.lease_until IS NULL
     OR o_inv.lease_until <= pg_catalog.clock_timestamp() THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO o_req
  FROM v15.llm_requests r
  WHERE r.request_id = o_att.request_id
  FOR UPDATE;
  IF o_req.status IS DISTINCT FROM 'open' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.status INTO v_iter_status
  FROM v15.iterations i
  WHERE i.invoke_id = v_invoke
    AND i.iteration = v_iter
  FOR UPDATE;
  IF v_iter_status IS DISTINCT FROM 'llm' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  RETURN;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_replay_assert_digest(
  p_attempt_id uuid,
  p_owner text,
  p_expected_digest text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_row record;
  v_att v15.llm_attempts;
  v_req v15.llm_requests;
  v_inv v15.invokes;
BEGIN
  SELECT * INTO v_row
  FROM v15.v15_replay_lock_attempt(p_attempt_id, p_owner);
  v_att := v_row.o_att;
  v_req := v_row.o_req;
  v_inv := v_row.o_inv;
  IF p_expected_digest IS NULL
     OR p_expected_digest !~ '^[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF v_req.logical_digest IS DISTINCT FROM p_expected_digest THEN
    RAISE EXCEPTION 'V15_REPLAY_DIVERGED'
      USING ERRCODE = 'P1541',
            DETAIL = v_req.logical_digest || ' ' || p_expected_digest;
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_replay_missing(
  p_attempt_id uuid,
  p_owner text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_row record;
  v_att v15.llm_attempts;
  v_req v15.llm_requests;
  v_inv v15.invokes;
BEGIN
  SELECT * INTO v_row
  FROM v15.v15_replay_lock_attempt(p_attempt_id, p_owner);
  v_att := v_row.o_att;
  v_req := v_row.o_req;
  v_inv := v_row.o_inv;
  RAISE EXCEPTION 'V15_REPLAY_MISSING' USING ERRCODE = 'P1542';
END;
$fn$;

CREATE FUNCTION v15.v15_replay_export(p_root uuid) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ids uuid[];
  v_status text;
  v_n integer;
  v_pools uuid[];
  v_pool uuid;
  v_pool_obj jsonb;
  v_outcome jsonb;
  v_invokes jsonb := '[]'::jsonb;
  v_id uuid;
  v_path text;
  v_depth integer;
  v_fatal boolean;
  v_error_code text;
  v_return jsonb;
  v_steps jsonb;
  v_bindings jsonb;
  v_board jsonb;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_root IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  WITH RECURSIVE tree AS (
    SELECT i.invoke_id
    FROM v15.invokes i
    WHERE i.invoke_id = p_root
    UNION ALL
    SELECT c.invoke_id
    FROM v15.invokes c
    JOIN tree t ON c.parent_invoke_id = t.invoke_id
  )
  SELECT coalesce(array_agg(tree.invoke_id ORDER BY tree.invoke_id), '{}'::uuid[])
    INTO v_ids
  FROM tree;
  IF v_ids IS NULL OR cardinality(v_ids) = 0 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT count(*) INTO v_n
  FROM v15.invokes i
  WHERE i.invoke_id = ANY (v_ids)
    AND i.status NOT IN ('completed', 'failed', 'aborted');
  IF v_n <> 0 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT count(*) INTO v_n
  FROM v15.llm_requests r
  WHERE r.invoke_id = ANY (v_ids)
    AND r.status = 'open';
  IF v_n <> 0 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT count(*) INTO v_n
  FROM v15.llm_requests r
  JOIN LATERAL (
    SELECT count(*) AS n_att,
           count(*) FILTER (
             WHERE a.n = 1 AND a.status = 'settled'
           ) AS n_ok
    FROM v15.llm_attempts a
    WHERE a.request_id = r.request_id
  ) s ON true
  WHERE r.invoke_id = ANY (v_ids)
    AND (s.n_att <> 1 OR s.n_ok <> 1);
  IF v_n <> 0 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT array_agg(DISTINCT i.pool_id ORDER BY i.pool_id) INTO v_pools
  FROM v15.invokes i
  WHERE i.invoke_id = ANY (v_ids);
  IF v_pools IS NOT NULL AND cardinality(v_pools) > 1 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF v_pools IS NULL OR cardinality(v_pools) = 0 THEN
    v_pool := NULL;
  ELSE
    v_pool := v_pools[1];
  END IF;
  IF v_pool IS NULL THEN
    v_pool_obj := NULL;
    v_outcome := NULL;
  ELSE
    SELECT jsonb_build_object(
             'calls_limit', b.calls_limit,
             'cost_limit', b.cost_limit
           ),
           jsonb_build_object(
             'calls_used', b.calls_used,
             'cost_used', b.cost_used
           )
      INTO v_pool_obj, v_outcome
    FROM v15.budget_pools b
    WHERE b.pool_id = v_pool;
  END IF;
  FOR v_id, v_path, v_depth, v_status, v_fatal, v_error_code, v_return IN
    SELECT i.invoke_id,
           v15.v15_replay_invoke_path(i.invoke_id),
           i.depth,
           i.status,
           i.fatal,
           i.error->>'code',
           i.return_value
    FROM v15.invokes i
    WHERE i.invoke_id = ANY (v_ids)
    ORDER BY v15.v15_replay_invoke_path(i.invoke_id) COLLATE "C"
  LOOP
    SELECT coalesce(jsonb_agg(step ORDER BY (step->>'iteration')::integer), '[]'::jsonb)
      INTO v_steps
    FROM (
      SELECT jsonb_build_object(
        'iteration', it.iteration,
        'result_kind', it.result_kind,
        'logical_digest', r.logical_digest,
        'response_content', a.response->>'content',
        'recorded_cost_usd', CASE
          WHEN a.cost_usd IS NULL THEN NULL
          ELSE a.cost_usd::text
        END,
        'statements', coalesce((
          SELECT jsonb_agg(
            jsonb_build_object(
              'stmt_index', s.stmt_index,
              'sql_digest', s.sql_digest,
              'kind', s.kind,
              'status', s.status,
              'bind_name', s.bind_name
            ) ORDER BY s.stmt_index
          )
          FROM v15.statements s
          WHERE s.invoke_id = it.invoke_id AND s.iteration = it.iteration
        ), '[]'::jsonb),
        'repl_output', coalesce(h.repl_output, ''),
        'repl_exception_code', h.repl_exception->>'code'
      ) AS step
      FROM v15.iterations it
      LEFT JOIN v15.llm_requests r
        ON r.invoke_id = it.invoke_id AND r.iteration = it.iteration
      LEFT JOIN v15.llm_attempts a
        ON a.request_id = r.request_id AND a.n = 1 AND a.status = 'settled'
      LEFT JOIN v15.repl_history h
        ON h.invoke_id = it.invoke_id AND h.iteration = it.iteration
      WHERE it.invoke_id = v_id
    ) q;
    SELECT coalesce(jsonb_agg(
      jsonb_build_object(
        'name', b.name,
        'kind', b.kind,
        'provenance', b.provenance,
        'tool_name', t.name,
        'value', b.value
      ) ORDER BY b.name COLLATE "C"
    ), '[]'::jsonb)
      INTO v_bindings
    FROM v15.bindings b
    LEFT JOIN v15.tool_catalog t ON t.tool_id = b.tool_id
    WHERE b.invoke_id = v_id;
    SELECT coalesce(jsonb_agg(
      jsonb_build_object('key', bb.key, 'value', bb.value) ORDER BY bb.key COLLATE "C"
    ), '[]'::jsonb)
      INTO v_board
    FROM v15.blackboard bb
    WHERE bb.invoke_id = v_id;
    v_invokes := v_invokes || jsonb_build_array(jsonb_build_object(
      'path', v_path,
      'depth', v_depth,
      'status', v_status,
      'fatal', v_fatal,
      'error_code', v_error_code,
      'return_value', v_return,
      'steps', v_steps,
      'bindings', v_bindings,
      'blackboard', v_board
    ));
  END LOOP;
  RETURN jsonb_build_object(
    'version', 1,
    'digest_scheme', 'md5((request-''attempt_id'')::text)',
    'pool', v_pool_obj,
    'pool_outcome', v_outcome,
    'invokes', v_invokes
  );
END;
$fn$;

ALTER FUNCTION v15.v15_io_sqlstate(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_known_code(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_replay_invoke_path(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_replay_attempt_context(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_replay_lock_attempt(uuid, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_replay_assert_digest(uuid, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_replay_missing(uuid, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_replay_export(uuid) OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_io_sqlstate(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_known_code(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_replay_invoke_path(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_replay_attempt_context(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_replay_lock_attempt(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_replay_assert_digest(uuid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_replay_missing(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_replay_export(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_io_sqlstate(text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_known_code(text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_replay_invoke_path(uuid) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_replay_lock_attempt(uuid, text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_replay_attempt_context(uuid) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_replay_assert_digest(uuid, text, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_replay_missing(uuid, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_replay_export(uuid) TO v15_worker;
