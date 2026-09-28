CREATE FUNCTION v15.v15_repl_sqlstate(p_code text) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE p_code
    WHEN 'V15_IO_EXHAUSTED' THEN 'P1513'
    WHEN 'V15_BUDGET_EXHAUSTED' THEN 'P1514'
    WHEN 'V15_RECURSION_EXCEEDED' THEN 'P1519'
    WHEN 'V15_ITERATION_EXCEEDED' THEN 'P1520'
    WHEN 'V15_HOOK_ABORT' THEN 'P1538'
    WHEN 'V15_CHILD_ERROR' THEN 'P1528'
    ELSE NULL
  END
$fn$;

CREATE FUNCTION v15.v15_repl_require_worker() RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF session_user <> 'v15_worker'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_closure(p_invoke_id uuid) RETURNS uuid[]
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  WITH RECURSIVE anc AS (
    SELECT i.invoke_id, i.parent_invoke_id
    FROM v15.invokes i
    WHERE i.invoke_id = p_invoke_id
    UNION ALL
    SELECT i.invoke_id, i.parent_invoke_id
    FROM v15.invokes i
    JOIN anc a ON i.invoke_id = a.parent_invoke_id
  ),
  down AS (
    SELECT i.invoke_id
    FROM v15.invokes i
    WHERE i.parent_invoke_id IN (SELECT anc.invoke_id FROM anc)
    UNION ALL
    SELECT i.invoke_id
    FROM v15.invokes i
    JOIN down d ON i.parent_invoke_id = d.invoke_id
  )
  SELECT coalesce(array_agg(s.invoke_id ORDER BY s.invoke_id), '{}'::uuid[])
  FROM (
    SELECT anc.invoke_id FROM anc
    UNION
    SELECT d.invoke_id
    FROM down d
    JOIN v15.invokes i ON i.invoke_id = d.invoke_id
    WHERE i.status NOT IN ('completed', 'failed', 'aborted')
  ) s
$fn$;

CREATE FUNCTION v15.v15_repl_pools(p_ids uuid[]) RETURNS uuid[]
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT coalesce(
    array_agg(DISTINCT i.pool_id ORDER BY i.pool_id),
    '{}'::uuid[]
  )
  FROM v15.invokes i
  WHERE i.invoke_id = ANY (p_ids)
    AND i.pool_id IS NOT NULL
$fn$;

CREATE FUNCTION v15.v15_repl_lock(p_invoke_id uuid) RETURNS v15.invokes
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ids uuid[];
  v_pools uuid[];
  v_after_ids uuid[];
  v_after_pools uuid[];
  v_id uuid;
  v_pool uuid;
  v_inv v15.invokes;
BEGIN
  v_ids := v15.v15_repl_closure(p_invoke_id);
  IF v_ids IS NULL OR cardinality(v_ids) = 0 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_pools := v15.v15_repl_pools(v_ids);
  IF cardinality(v_pools) > 0 THEN
    FOR v_pool IN
      SELECT b.pool_id
      FROM v15.budget_pools b
      WHERE b.pool_id = ANY (v_pools)
      ORDER BY b.pool_id
      FOR UPDATE
    LOOP
      NULL;
    END LOOP;
  END IF;
  FOR v_id IN
    SELECT i.invoke_id
    FROM v15.invokes i
    WHERE i.invoke_id = ANY (v_ids)
    ORDER BY i.invoke_id
    FOR UPDATE
  LOOP
    NULL;
  END LOOP;
  v_after_ids := v15.v15_repl_closure(p_invoke_id);
  v_after_pools := v15.v15_repl_pools(v_after_ids);
  IF v_after_ids IS DISTINCT FROM v_ids
     OR v_after_pools IS DISTINCT FROM v_pools THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO v_inv FROM v15.invokes i WHERE i.invoke_id = p_invoke_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  RETURN v_inv;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_repl_check_holder(
  p_inv v15.invokes,
  p_fence bigint,
  p_owner text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_inv.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF p_inv.fence IS DISTINCT FROM p_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  IF p_inv.lease_owner IS DISTINCT FROM p_owner
     OR p_inv.lease_until IS NULL
     OR p_inv.lease_until <= pg_catalog.clock_timestamp() THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_event(
  p_invoke_id uuid,
  p_class text,
  p_span text,
  p_phase text,
  p_outcome text,
  p_payload jsonb,
  p_fence bigint
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  INSERT INTO v15.invoke_events (
    invoke_id, seq, event_class, span, phase, outcome, payload, fence, created_at
  )
  SELECT p_invoke_id,
         coalesce((
           SELECT max(e.seq)
           FROM v15.invoke_events e
           WHERE e.invoke_id = p_invoke_id
         ), -1) + 1,
         p_class,
         p_span,
         p_phase,
         p_outcome,
         coalesce(p_payload, '{}'::jsonb),
         p_fence,
         pg_catalog.clock_timestamp();
END;
$fn$;

CREATE FUNCTION v15.v15_repl_assert_phase(p_phase jsonb) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_phase IS NULL
     OR pg_catalog.jsonb_typeof(p_phase) <> 'object'
     OR p_phase->'contract' IS DISTINCT FROM '1'::jsonb
     OR pg_catalog.jsonb_typeof(p_phase->'action') <> 'string'
     OR (p_phase->>'action') NOT IN ('proceed', 'abort') THEN
    RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.jsonb_object_keys(p_phase) AS k(key)
    WHERE k.key <> ALL (ARRAY[
      'contract', 'action', 'fatal', 'code', 'messages', 'exec_result',
      'recursion_available', 'input_adds', 'input_drops',
      'blackboard_writes', 'budget'
    ]::text[])
  ) THEN
    RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
  END IF;
  IF p_phase->>'action' = 'abort' THEN
    IF pg_catalog.jsonb_typeof(p_phase->'fatal') IS DISTINCT FROM 'boolean'
       OR pg_catalog.jsonb_typeof(p_phase->'code') IS DISTINCT FROM 'string'
       OR p_phase->>'code' = ''
       OR p_phase->>'code' NOT IN (
         'V15_IO_EXHAUSTED',
         'V15_BUDGET_EXHAUSTED',
         'V15_RECURSION_EXCEEDED',
         'V15_ITERATION_EXCEEDED',
         'V15_HOOK_ABORT'
       ) THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_error(p_code text, p_message text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_state text;
BEGIN
  v_state := v15.v15_repl_sqlstate(p_code);
  IF v_state IS NULL THEN
    RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
  END IF;
  RETURN pg_catalog.jsonb_build_object(
    'sqlstate', v_state,
    'code', p_code,
    'message', pg_catalog.left(coalesce(p_message, ''), 1024)
  );
END;
$fn$;

CREATE FUNCTION v15.v15_repl_close_span(
  p_invoke_id uuid,
  p_iteration integer,
  p_span text,
  p_outcome text,
  p_fence bigint
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ret jsonb;
BEGIN
  IF NOT v15.v15_span_open(p_invoke_id, p_span) THEN
    RETURN;
  END IF;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', p_span, 'exit', p_outcome,
    pg_catalog.jsonb_build_object('outcome', p_outcome),
    p_fence
  );
  v_ret := v15.v15_on_phase(
    p_invoke_id,
    p_iteration,
    p_span,
    'exit',
    pg_catalog.jsonb_build_object('outcome', p_outcome)
  );
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_close_one(
  p_invoke_id uuid,
  p_code text,
  p_fatal boolean,
  p_message text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_err jsonb;
  v_outcome text;
  v_fence bigint;
  v_iter integer;
  v_scratch text;
BEGIN
  v_err := v15.v15_repl_error(p_code, p_message);
  v_outcome := CASE WHEN p_fatal THEN 'aborted' ELSE 'failed' END;
  UPDATE v15.iterations i
  SET status = 'done',
      result_kind = 'continue',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.status <> 'done';
  INSERT INTO v15.repl_history (
    invoke_id, iteration, llm_response, repl_output, repl_exception
  )
  SELECT i.invoke_id,
         i.iteration,
         coalesce((
           SELECT m.content
           FROM v15.llm_messages m
           WHERE m.invoke_id = i.invoke_id
             AND m.iteration = i.iteration
             AND m.kind = 'assistant'
           ORDER BY m.msg_seq
           LIMIT 1
         ), ''),
         '',
         v_err
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'done'
    AND NOT EXISTS (
      SELECT 1
      FROM v15.repl_history h
      WHERE h.invoke_id = i.invoke_id
        AND h.iteration = i.iteration
    );
  UPDATE v15.invokes i
  SET status = v_outcome,
      fatal = p_fatal,
      error = v_err,
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id;
  SELECT i.fence, i.scratch_schema
    INTO v_fence, v_scratch
  FROM v15.invokes i
  WHERE i.invoke_id = p_invoke_id;
  SELECT max(i.iteration) INTO v_iter
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id;
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, coalesce(v_iter, 0), 'repl_exec', v_outcome, v_fence
  );
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, coalesce(v_iter, 0), 'llm_query', v_outcome, v_fence
  );
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, coalesce(v_iter, 0), 'invoke', v_outcome, v_fence
  );
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname = v_scratch
  ) THEN
    EXECUTE format('DROP SCHEMA %I CASCADE', v_scratch);
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_skip_after(
  p_invoke_id uuid,
  p_iteration integer,
  p_cut integer
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  UPDATE v15.statements s
  SET status = 'skipped',
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = p_iteration
    AND s.stmt_index > p_cut
    AND s.status IN ('pending', 'failed');
END;
$fn$;

CREATE FUNCTION v15.v15_repl_fail_running(
  p_invoke_id uuid,
  p_code text,
  p_message text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_err jsonb;
  v_rec record;
BEGIN
  v_err := v15.v15_repl_error(p_code, p_message);
  FOR v_rec IN
    SELECT s.iteration, min(s.stmt_index) AS cut
    FROM v15.statements s
    WHERE s.invoke_id = p_invoke_id
      AND s.status = 'running'
    GROUP BY s.iteration
  LOOP
    UPDATE v15.statements s
    SET status = 'failed',
        error = v_err,
        error_sqlstate = v_err->>'sqlstate',
        revision = s.revision + 1
    WHERE s.invoke_id = p_invoke_id
      AND s.iteration = v_rec.iteration
      AND s.status = 'running';
    PERFORM v15.v15_repl_skip_after(p_invoke_id, v_rec.iteration, v_rec.cut);
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_assert_bind_wait(p_child uuid) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_n integer;
BEGIN
  SELECT count(*) INTO v_n
  FROM v15.statements s
  JOIN v15.invokes c ON c.invoke_id = p_child
  JOIN v15.invokes p ON p.invoke_id = c.parent_invoke_id
  JOIN v15.iterations it
    ON it.invoke_id = p.invoke_id
   AND it.iteration = s.iteration
  WHERE s.invoke_id = c.parent_invoke_id
    AND s.child_invoke_id = p_child
    AND s.status = 'running'
    AND p.status = 'suspended'
    AND p.lease_owner IS NULL
    AND p.lease_until IS NULL
    AND it.status = 'suspended';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_DELIVERY_CONFLICT' USING ERRCODE = 'P1527';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_deliver_nonfatal(p_child uuid) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_parent uuid;
  v_iter integer;
  v_stmt integer;
  v_capture text;
  v_fence bigint;
  v_err jsonb;
  v_block text;
  v_output text;
  v_n integer;
BEGIN
  v_err := v15.v15_repl_error('V15_CHILD_ERROR', '');
  SELECT c.parent_invoke_id, s.iteration, s.stmt_index, it.capture, p.fence
    INTO v_parent, v_iter, v_stmt, v_capture, v_fence
  FROM v15.invokes c
  JOIN v15.statements s
    ON s.invoke_id = c.parent_invoke_id
   AND s.child_invoke_id = c.invoke_id
   AND s.status = 'running'
  JOIN v15.invokes p ON p.invoke_id = c.parent_invoke_id
  JOIN v15.iterations it
    ON it.invoke_id = p.invoke_id
   AND it.iteration = s.iteration
  WHERE c.invoke_id = p_child;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_DELIVERY_CONFLICT' USING ERRCODE = 'P1527';
  END IF;
  UPDATE v15.statements s
  SET status = 'failed',
      error = v_err,
      error_sqlstate = v_err->>'sqlstate',
      revision = s.revision + 1
  WHERE s.invoke_id = v_parent
    AND s.iteration = v_iter
    AND s.stmt_index = v_stmt;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_DELIVERY_CONFLICT' USING ERRCODE = 'P1527';
  END IF;
  PERFORM v15.v15_repl_skip_after(v_parent, v_iter, v_stmt);
  v_block := '[v15 exception V15_CHILD_ERROR]' || E'\n';
  IF v_capture = '' THEN
    v_output := v_block;
  ELSE
    v_output := v_capture || E'\n' || v_block;
  END IF;
  UPDATE v15.iterations i
  SET status = 'done',
      result_kind = 'continue',
      revision = i.revision + 1
  WHERE i.invoke_id = v_parent
    AND i.iteration = v_iter;
  INSERT INTO v15.repl_history (
    invoke_id, iteration, llm_response, repl_output, repl_exception
  )
  SELECT v_parent,
         v_iter,
         coalesce((
           SELECT m.content
           FROM v15.llm_messages m
           WHERE m.invoke_id = v_parent
             AND m.iteration = v_iter
             AND m.kind = 'assistant'
           ORDER BY m.msg_seq
           LIMIT 1
         ), ''),
         v_output,
         v_err;
  INSERT INTO v15.llm_messages (
    invoke_id, msg_seq, message_id, iteration, role, kind, content
  )
  SELECT v_parent,
         coalesce((
           SELECT max(m.msg_seq)
           FROM v15.llm_messages m
           WHERE m.invoke_id = v_parent
         ), -1) + 1,
         'iter:' || v_iter::text || ':observation',
         v_iter,
         'user',
         'observation',
         v_output;
  INSERT INTO v15.iterations (
    invoke_id, iteration, status, resume_stmt, capture
  ) VALUES (
    v_parent, v_iter + 1, 'pending', 0, ''
  );
  PERFORM v15.v15_repl_close_span(
    v_parent, v_iter, 'repl_exec', 'failed', v_fence
  );
  UPDATE v15.invokes i
  SET status = 'runnable',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = v_parent;
  PERFORM v15.v15_repl_event(
    v_parent, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object('op', 'child_error', 'code', 'V15_CHILD_ERROR'),
    v_fence
  );
END;
$fn$;

CREATE FUNCTION v15.v15_repl_fatal_expand(
  p_child uuid,
  p_code text,
  p_message text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ids uuid[];
  v_id uuid;
  v_fence bigint;
BEGIN
  v_ids := v15.v15_repl_closure(p_child);
  FOREACH v_id IN ARRAY v_ids LOOP
    PERFORM v15.v15_repl_close_one(v_id, p_code, true, p_message);
    PERFORM v15.v15_repl_fail_running(v_id, p_code, p_message);
    SELECT i.fence INTO v_fence FROM v15.invokes i WHERE i.invoke_id = v_id;
    PERFORM v15.v15_repl_event(
      v_id, 'audit', NULL, NULL, NULL,
      pg_catalog.jsonb_build_object('op', 'fatal', 'code', p_code),
      v_fence
    );
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_abort_exec(
  p_invoke_id uuid,
  p_code text,
  p_fatal boolean,
  p_message text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_parent uuid;
BEGIN
  SELECT i.parent_invoke_id INTO v_parent
  FROM v15.invokes i
  WHERE i.invoke_id = p_invoke_id;
  IF v_parent IS NOT NULL THEN
    PERFORM v15.v15_repl_assert_bind_wait(p_invoke_id);
  END IF;
  IF v_parent IS NOT NULL AND p_fatal THEN
    PERFORM v15.v15_repl_fatal_expand(p_invoke_id, p_code, p_message);
  ELSIF v_parent IS NOT NULL THEN
    PERFORM v15.v15_repl_close_one(p_invoke_id, p_code, false, p_message);
    PERFORM v15.v15_repl_deliver_nonfatal(p_invoke_id);
  ELSE
    PERFORM v15.v15_repl_close_one(p_invoke_id, p_code, p_fatal, p_message);
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_timeout_ms(
  p_invoke_id uuid,
  p_sql text,
  p_config jsonb
) RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_best numeric;
  v_line text;
  v_match text[];
  v_seconds numeric;
  v_raw text;
  v_attempt text := '^[ \t\f\v]*--[ \t\f\v]*timeout:';
  v_full text := '^[ \t\f\v]*--[ \t\f\v]*timeout:[ \t\f\v]*([0-9]+(\.[0-9]+)?|\.[0-9]+)[ \t\f\v]*$';
BEGIN
  v_best := v15.v15_baseline_max(p_invoke_id, 'governance_statement');
  IF pg_catalog.jsonb_exists(p_config, 'repl')
     AND pg_catalog.jsonb_typeof(p_config->'repl') = 'object'
     AND pg_catalog.jsonb_exists(p_config->'repl', 'timeout_ms') THEN
    v_raw := p_config->'repl'->>'timeout_ms';
    IF v_raw IS NULL OR v_raw !~ '^[0-9]+$' OR v_raw::integer < 1 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_best := least(v_best, v_raw::numeric);
  END IF;
  v_line := split_part(p_sql, E'\n', 1);
  IF right(v_line, 1) = E'\r' THEN
    v_line := left(v_line, -1);
  END IF;
  IF v_line ~ v_attempt THEN
    v_match := pg_catalog.regexp_match(v_line, v_full);
    IF v_match IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_seconds := v_match[1]::numeric;
    IF v_seconds <= 0 OR floor(v_seconds * 1000) < 1 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_best := least(v_best, floor(v_seconds * 1000));
  END IF;
  RETURN v_best::integer;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_grant_scratch(p_schema text, p_create boolean) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_create THEN
    EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO v15_repl', p_schema);
  ELSE
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO v15_repl', p_schema);
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_repl_revoke_scratch(p_schema text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  EXECUTE format('REVOKE ALL ON SCHEMA %I FROM v15_repl', p_schema);
END;
$fn$;

CREATE FUNCTION v15.v15_begin_exec(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_iter integer;
  v_resume integer;
  v_n integer;
  v_io jsonb;
  v_ret jsonb;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_fence IS NULL OR p_owner IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  SELECT count(*) INTO v_n
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.iteration, i.resume_stmt
    INTO v_iter, v_resume
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing'
  FOR UPDATE;
  IF v15.v15_span_open(p_invoke_id, 'repl_exec') THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_io := pg_catalog.jsonb_build_object(
    'iteration', v_iter,
    'resume_stmt', v_resume
  );
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'repl_exec', 'enter', NULL, v_io, v_inv.fence
  );
  v_ret := v15.v15_on_phase(p_invoke_id, v_iter, 'repl_exec', 'enter', v_io);
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    PERFORM v15.v15_repl_abort_exec(
      p_invoke_id, v_ret->>'code', (v_ret->>'fatal')::boolean, ''
    );
    RETURN;
  END IF;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'repl_exec', 'send', NULL, '{}'::jsonb, v_inv.fence
  );
  v_ret := v15.v15_on_phase(
    p_invoke_id, v_iter, 'repl_exec', 'send', '{}'::jsonb
  );
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    PERFORM v15.v15_repl_abort_exec(
      p_invoke_id, v_ret->>'code', (v_ret->>'fatal')::boolean, ''
    );
  END IF;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_prepare_statement(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index integer
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_iter integer;
  v_resume integer;
  v_n integer;
  v_kind text;
  v_sql text;
  v_scratch text;
  v_timeout integer;
  v_fence bigint;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR p_stmt_index IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  SELECT count(*) INTO v_n
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.iteration, i.resume_stmt
    INTO v_iter, v_resume
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing'
  FOR UPDATE;
  IF NOT v15.v15_span_open(p_invoke_id, 'repl_exec') THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF p_stmt_index IS DISTINCT FROM v_resume THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.kind, s.sql
    INTO v_kind, v_sql
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.status = 'pending'
    AND s.error IS NULL
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_scratch := v_inv.scratch_schema;
  v_timeout := v15.v15_repl_timeout_ms(p_invoke_id, v_sql, v_inv.resolved_config);
  UPDATE v15.statements s
  SET status = 'running',
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  INSERT INTO v15.exec_context (
    backend_pid, invoke_id, iteration, stmt_index, scratch_schema, revision
  ) VALUES (
    pg_catalog.pg_backend_pid(),
    p_invoke_id,
    v_iter,
    p_stmt_index,
    v_scratch,
    1
  )
  ON CONFLICT (backend_pid) DO UPDATE
  SET invoke_id = EXCLUDED.invoke_id,
      iteration = EXCLUDED.iteration,
      stmt_index = EXCLUDED.stmt_index,
      scratch_schema = EXCLUDED.scratch_schema,
      revision = v15.exec_context.revision + 1
  RETURNING revision INTO v_fence;
  PERFORM v15.v15_repl_grant_scratch(v_scratch, v_kind IS DISTINCT FROM 'bind_invoke');
  RETURN pg_catalog.jsonb_build_object(
    'statement_fence', v_fence,
    'timeout_ms', v_timeout,
    'kind', v_kind,
    'scratch_schema', v_scratch
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_complete_statement(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index integer,
  p_statement_fence bigint,
  p_status text,
  p_error jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_iter integer;
  v_n integer;
  v_kind text;
  v_ctx v15.exec_context;
  v_err jsonb;
  v_next integer;
  v_ok boolean;
  v_scratch text;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR p_stmt_index IS NULL OR p_statement_fence IS NULL OR p_status IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_status NOT IN ('done', 'failed') THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_status = 'done' AND p_error IS NOT NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_status = 'failed' THEN
    IF p_error IS NULL
       OR pg_catalog.jsonb_typeof(p_error) <> 'object'
       OR pg_catalog.jsonb_typeof(p_error->'sqlstate') <> 'string'
       OR pg_catalog.jsonb_typeof(p_error->'code') <> 'string'
       OR p_error->>'sqlstate' = ''
       OR p_error->>'code' = ''
       OR (
         pg_catalog.jsonb_exists(p_error, 'message')
         AND pg_catalog.jsonb_typeof(p_error->'message') <> 'string'
       ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_err := pg_catalog.jsonb_build_object(
      'sqlstate', p_error->>'sqlstate',
      'code', p_error->>'code',
      'message', pg_catalog.left(coalesce(p_error->>'message', ''), 1024)
    );
  END IF;
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  SELECT count(*) INTO v_n
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.iteration INTO v_iter
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing'
  FOR UPDATE;
  SELECT s.kind INTO v_kind
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.status = 'running'
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO v_ctx
  FROM v15.exec_context e
  WHERE e.backend_pid = pg_catalog.pg_backend_pid();
  IF NOT FOUND
     OR v_ctx.invoke_id IS DISTINCT FROM p_invoke_id
     OR v_ctx.iteration IS DISTINCT FROM v_iter
     OR v_ctx.stmt_index IS DISTINCT FROM p_stmt_index THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_ctx.revision IS DISTINCT FROM p_statement_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  IF p_status = 'done' AND v_kind = 'return' THEN
    SELECT i.return_value IS NOT NULL INTO v_ok
    FROM v15.invokes i
    WHERE i.invoke_id = p_invoke_id;
    IF NOT v_ok THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
  ELSIF p_status = 'done' AND v_kind = 'raise' THEN
    SELECT i.error IS NOT NULL INTO v_ok
    FROM v15.invokes i
    WHERE i.invoke_id = p_invoke_id;
    IF NOT v_ok THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
  END IF;
  UPDATE v15.statements s
  SET status = p_status,
      error = v_err,
      error_sqlstate = v_err->>'sqlstate',
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index;
  IF p_status = 'done' THEN
    IF v_kind IN ('return', 'raise') THEN
      SELECT count(*)::integer INTO v_next
      FROM v15.statements s
      WHERE s.invoke_id = p_invoke_id
        AND s.iteration = v_iter;
    ELSE
      v_next := p_stmt_index + 1;
    END IF;
    UPDATE v15.iterations i
    SET resume_stmt = v_next,
        revision = i.revision + 1
    WHERE i.invoke_id = p_invoke_id
      AND i.iteration = v_iter;
  END IF;
  v_scratch := v_inv.scratch_schema;
  PERFORM v15.v15_repl_revoke_scratch(v_scratch);
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_fail_statement(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index integer,
  p_error jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_iter integer;
  v_resume integer;
  v_n integer;
  v_err jsonb;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR p_stmt_index IS NULL OR p_error IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF pg_catalog.jsonb_typeof(p_error) <> 'object'
     OR pg_catalog.jsonb_typeof(p_error->'sqlstate') <> 'string'
     OR pg_catalog.jsonb_typeof(p_error->'code') <> 'string'
     OR p_error->>'sqlstate' = ''
     OR p_error->>'code' = ''
     OR (
       pg_catalog.jsonb_exists(p_error, 'message')
       AND pg_catalog.jsonb_typeof(p_error->'message') <> 'string'
     ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_err := pg_catalog.jsonb_build_object(
    'sqlstate', p_error->>'sqlstate',
    'code', p_error->>'code',
    'message', pg_catalog.left(coalesce(p_error->>'message', ''), 1024)
  );
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  SELECT count(*) INTO v_n
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.iteration, i.resume_stmt
    INTO v_iter, v_resume
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing'
  FOR UPDATE;
  IF NOT v15.v15_span_open(p_invoke_id, 'repl_exec') THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF p_stmt_index IS DISTINCT FROM v_resume THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  UPDATE v15.statements s
  SET status = 'failed',
      error = v_err,
      error_sqlstate = v_err->>'sqlstate',
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.status = 'pending'
    AND s.error IS NULL;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_register_tool(
  p_name text,
  p_handler oid,
  p_description text,
  p_arg_schema jsonb,
  p_external boolean
) RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_id uuid;
  v_digest text;
BEGIN
  IF p_name IS NULL OR p_handler IS NULL OR p_description IS NULL
     OR p_arg_schema IS NULL OR p_external IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_digest := v15.v15_handler_digest(p_handler);
  IF v_digest IS NULL THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE' USING ERRCODE = 'P1537';
  END IF;
  INSERT INTO v15.tool_catalog (
    tool_id, name, arg_schema, handler, description, external, handler_digest
  ) VALUES (
    pg_catalog.gen_random_uuid(),
    p_name,
    p_arg_schema,
    p_handler,
    p_description,
    p_external,
    v_digest
  )
  RETURNING tool_id INTO v_id;
  RETURN v_id;
END;
$fn$;

ALTER FUNCTION v15.v15_repl_sqlstate(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_require_worker() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_closure(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_pools(uuid[]) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_lock(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_check_holder(v15.invokes, bigint, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_event(uuid, text, text, text, text, jsonb, bigint) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_assert_phase(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_error(text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_close_span(uuid, integer, text, text, bigint) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_close_one(uuid, text, boolean, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_skip_after(uuid, integer, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_fail_running(uuid, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_assert_bind_wait(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_deliver_nonfatal(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_fatal_expand(uuid, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_abort_exec(uuid, text, boolean, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_timeout_ms(uuid, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_grant_scratch(text, boolean) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_repl_revoke_scratch(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_begin_exec(uuid, bigint, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_prepare_statement(uuid, bigint, text, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_complete_statement(uuid, bigint, text, integer, bigint, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_fail_statement(uuid, bigint, text, integer, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_register_tool(text, oid, text, jsonb, boolean) OWNER TO v15_owner;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v15 FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_begin_exec(uuid, bigint, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_prepare_statement(uuid, bigint, text, integer) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_complete_statement(uuid, bigint, text, integer, bigint, text, jsonb) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_fail_statement(uuid, bigint, text, integer, jsonb) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_register_tool(text, oid, text, jsonb, boolean) TO v15_worker;
