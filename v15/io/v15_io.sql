CREATE FUNCTION v15.v15_io_sqlstate(p_code text) RETURNS text
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
    ELSE NULL
  END
$fn$;

CREATE FUNCTION v15.v15_io_error(p_code text, p_message text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_state text;
BEGIN
  v_state := v15.v15_io_sqlstate(p_code);
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

CREATE FUNCTION v15.v15_io_abort_result(p_fatal boolean, p_code text) RETURNS jsonb
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT pg_catalog.jsonb_build_object(
    'attempt_id', 'null'::jsonb,
    'action', 'abort',
    'fatal', p_fatal,
    'code', p_code
  )
$fn$;

CREATE FUNCTION v15.v15_io_pool_reserve(
  p_pool uuid,
  p_calls integer,
  p_cost numeric
) RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_n integer;
BEGIN
  IF p_pool IS NULL THEN
    RETURN true;
  END IF;
  IF p_calls IS NULL OR p_calls < 1 OR p_cost IS NULL OR p_cost < 0 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  UPDATE v15.budget_pools b
  SET calls_reserved = b.calls_reserved + p_calls,
      cost_reserved = b.cost_reserved + p_cost,
      revision = b.revision + 1
  WHERE b.pool_id = p_pool
    AND (b.calls_limit IS NULL
         OR b.calls_used + b.calls_reserved + p_calls <= b.calls_limit)
    AND (b.cost_limit IS NULL
         OR b.cost_used + b.cost_reserved + p_cost <= b.cost_limit);
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n = 1;
END;
$fn$;

CREATE FUNCTION v15.v15_io_pool_release(
  p_pool uuid,
  p_calls integer,
  p_cost numeric,
  p_charge_calls boolean,
  p_cost_used_delta numeric
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_n integer;
BEGIN
  IF p_pool IS NULL THEN
    RETURN;
  END IF;
  UPDATE v15.budget_pools b
  SET calls_reserved = b.calls_reserved - p_calls,
      calls_used = b.calls_used + CASE WHEN p_charge_calls THEN p_calls ELSE 0 END,
      cost_reserved = b.cost_reserved - p_cost,
      cost_used = b.cost_used + p_cost_used_delta,
      revision = b.revision + 1
  WHERE b.pool_id = p_pool
    AND b.calls_reserved >= p_calls
    AND b.cost_reserved >= p_cost;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_io_exit_query(
  p_invoke_id uuid,
  p_iteration integer,
  p_outcome text,
  p_attempt_id uuid,
  p_fence bigint
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_io jsonb;
  v_ret jsonb;
BEGIN
  IF NOT v15.v15_span_open(p_invoke_id, 'llm_query') THEN
    RETURN;
  END IF;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'llm_query', 'exit', p_outcome,
    pg_catalog.jsonb_build_object('outcome', p_outcome),
    p_fence
  );
  v_io := pg_catalog.jsonb_build_object(
    'attempt_id',
    CASE
      WHEN p_attempt_id IS NULL THEN 'null'::jsonb
      ELSE pg_catalog.to_jsonb(p_attempt_id)
    END
  );
  v_ret := v15.v15_on_phase(p_invoke_id, p_iteration, 'llm_query', 'exit', v_io);
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_io_close_self(
  p_invoke_id uuid,
  p_iteration integer,
  p_code text,
  p_fatal boolean,
  p_attempt_id uuid
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
  v_scratch text;
BEGIN
  v_err := v15.v15_io_error(p_code, '');
  v_outcome := CASE WHEN p_fatal THEN 'aborted' ELSE 'failed' END;
  UPDATE v15.iterations i
  SET status = 'done',
      result_kind = 'continue',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.iteration = p_iteration
    AND i.status <> 'done';
  INSERT INTO v15.repl_history (
    invoke_id, iteration, llm_response, repl_output, repl_exception
  )
  SELECT p_invoke_id,
         p_iteration,
         coalesce((
           SELECT m.content
           FROM v15.llm_messages m
           WHERE m.invoke_id = p_invoke_id
             AND m.iteration = p_iteration
             AND m.kind = 'assistant'
           ORDER BY m.msg_seq
           LIMIT 1
         ), ''),
         '',
         v_err
  WHERE NOT EXISTS (
    SELECT 1
    FROM v15.repl_history h
    WHERE h.invoke_id = p_invoke_id
      AND h.iteration = p_iteration
  );
  UPDATE v15.invokes i
  SET status = v_outcome,
      fatal = p_fatal,
      error = v_err,
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id
  RETURNING i.fence, i.scratch_schema INTO v_fence, v_scratch;
  PERFORM v15.v15_io_exit_query(
    p_invoke_id, p_iteration, v_outcome, p_attempt_id, v_fence
  );
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, p_iteration, 'repl_exec', v_outcome, v_fence
  );
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, p_iteration, 'invoke', v_outcome, v_fence
  );
  IF p_fatal THEN
    PERFORM v15.v15_repl_event(
      p_invoke_id, 'audit', NULL, NULL, NULL,
      pg_catalog.jsonb_build_object('op', 'fatal', 'code', p_code),
      v_fence
    );
  END IF;
  IF v_scratch IS NOT NULL AND EXISTS (
    SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname = v_scratch
  ) THEN
    EXECUTE pg_catalog.format('DROP SCHEMA %I CASCADE', v_scratch);
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_io_terminal(
  p_invoke_id uuid,
  p_iteration integer,
  p_code text,
  p_fatal boolean,
  p_attempt_id uuid
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
    IF p_fatal THEN
      PERFORM v15.v15_repl_fatal_expand(p_invoke_id, p_code, '');
    ELSE
      PERFORM v15.v15_io_close_self(
        p_invoke_id, p_iteration, p_code, false, p_attempt_id
      );
      PERFORM v15.v15_repl_deliver_nonfatal(p_invoke_id);
    END IF;
    RETURN;
  END IF;
  PERFORM v15.v15_io_close_self(
    p_invoke_id, p_iteration, p_code, p_fatal, p_attempt_id
  );
END;
$fn$;

CREATE FUNCTION v15.v15_io_append_hook_messages(
  p_messages jsonb,
  p_phase_messages jsonb
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_out jsonb;
  v_seq integer;
  v_elem jsonb;
  v_id text;
  v_role text;
  v_content text;
  v_persistent boolean;
  v_kind text;
BEGIN
  v_out := p_messages;
  IF p_phase_messages IS NULL
     OR pg_catalog.jsonb_typeof(p_phase_messages) = 'null'
     OR pg_catalog.jsonb_typeof(p_phase_messages) <> 'array'
     OR pg_catalog.jsonb_array_length(p_phase_messages) = 0 THEN
    RETURN v_out;
  END IF;
  v_seq := pg_catalog.jsonb_array_length(v_out);
  FOR v_elem IN
    SELECT e.value
    FROM pg_catalog.jsonb_array_elements(p_phase_messages) AS e(value)
  LOOP
    IF pg_catalog.jsonb_typeof(v_elem) <> 'object'
       OR NOT pg_catalog.jsonb_exists(v_elem, 'id')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'role')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'content')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'persistent')
       OR pg_catalog.jsonb_typeof(v_elem->'id') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'role') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'content') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'persistent') <> 'boolean' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_id := v_elem->>'id';
    v_role := v_elem->>'role';
    v_content := v_elem->>'content';
    v_persistent := (v_elem->>'persistent')::boolean;
    IF v_id IS NULL OR pg_catalog.char_length(v_id) < 1
       OR pg_catalog.char_length(v_id) > 200
       OR v_role NOT IN ('system', 'user', 'assistant') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_kind := CASE WHEN v_persistent THEN 'persistent_hook' ELSE 'transient_hook' END;
    v_out := v_out || pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'seq', v_seq,
        'message_id', v_id,
        'role', v_role,
        'kind', v_kind,
        'content', v_content
      )
    );
    v_seq := v_seq + 1;
  END LOOP;
  RETURN v_out;
END;
$fn$;

CREATE FUNCTION v15.v15_io_store_statements(
  p_invoke_id uuid,
  p_iteration integer,
  p_statements jsonb,
  p_apply boolean
) RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_i integer;
  v_n integer;
  v_elem jsonb;
  v_sql text;
  v_digest text;
  v_kind text;
  v_bind text;
  v_arg text;
  v_code text;
  v_err jsonb;
  v_status text;
BEGIN
  IF p_statements IS NULL OR pg_catalog.jsonb_typeof(p_statements) <> 'array' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_n := pg_catalog.jsonb_array_length(p_statements);
  IF v_n = 0 THEN
    RETURN 0;
  END IF;
  FOR v_i IN 0 .. v_n - 1 LOOP
    v_elem := p_statements -> v_i;
    IF pg_catalog.jsonb_typeof(v_elem) <> 'object'
       OR (
         SELECT count(*)
         FROM pg_catalog.jsonb_object_keys(v_elem) AS k(key)
       ) <> 6
       OR NOT (
         pg_catalog.jsonb_exists(v_elem, 'sql')
         AND pg_catalog.jsonb_exists(v_elem, 'sql_digest')
         AND pg_catalog.jsonb_exists(v_elem, 'kind')
         AND pg_catalog.jsonb_exists(v_elem, 'bind_name')
         AND pg_catalog.jsonb_exists(v_elem, 'arg_sql')
         AND pg_catalog.jsonb_exists(v_elem, 'reject_code')
       )
       OR pg_catalog.jsonb_typeof(v_elem->'sql') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'sql_digest') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'kind') <> 'string' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_sql := v_elem->>'sql';
    v_digest := v_elem->>'sql_digest';
    v_kind := v_elem->>'kind';
    IF pg_catalog.jsonb_typeof(v_elem->'bind_name') = 'null' THEN
      v_bind := NULL;
    ELSIF pg_catalog.jsonb_typeof(v_elem->'bind_name') = 'string' THEN
      v_bind := v_elem->>'bind_name';
    ELSE
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_typeof(v_elem->'arg_sql') = 'null' THEN
      v_arg := NULL;
    ELSIF pg_catalog.jsonb_typeof(v_elem->'arg_sql') = 'string' THEN
      v_arg := v_elem->>'arg_sql';
    ELSE
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF pg_catalog.jsonb_typeof(v_elem->'reject_code') = 'null' THEN
      v_code := NULL;
    ELSIF pg_catalog.jsonb_typeof(v_elem->'reject_code') = 'string' THEN
      v_code := v_elem->>'reject_code';
      IF v_code = '' THEN
        v_code := NULL;
      END IF;
    ELSE
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_sql IS NULL
       OR v_digest IS DISTINCT FROM pg_catalog.md5(v_sql)
       OR v_kind NOT IN ('plain', 'bind_invoke', 'return', 'raise', 'print', 'assign')
       OR (
         v_code IS NOT NULL
         AND v_code NOT IN (
           'V15_INVOKE_FORM', 'V15_DIALECT', 'V15_DDL', 'V15_VALUE_INVALID'
         )
       ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_kind = 'bind_invoke' THEN
      IF v_bind IS NULL OR v_bind = ''
         OR (v_code IS NULL AND (v_arg IS NULL OR v_arg = '')) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    ELSIF v_kind IN ('plain', 'print', 'return', 'raise') THEN
      IF v_bind IS NOT NULL THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END IF;
    IF v_code IS NULL THEN
      v_status := 'pending';
      v_err := NULL;
    ELSE
      v_status := 'failed';
      v_err := v15.v15_io_error(v_code, '');
    END IF;
    IF NOT p_apply THEN
      CONTINUE;
    END IF;
    INSERT INTO v15.statements (
      invoke_id, iteration, stmt_index, sql, sql_digest, kind,
      bind_name, arg_sql, status, error, error_sqlstate
    ) VALUES (
      p_invoke_id, p_iteration, v_i, v_sql, pg_catalog.md5(v_sql), v_kind,
      v_bind, v_arg, v_status, v_err, v_err->>'sqlstate'
    );
  END LOOP;
  RETURN v_n;
END;
$fn$;

CREATE FUNCTION v15.v15_io_lock_ids(p_ids uuid[]) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ids uuid[];
  v_pools uuid[];
  v_after uuid[];
  v_after_pools uuid[];
  v_id uuid;
  v_pool uuid;
BEGIN
  IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
    RETURN;
  END IF;
  SELECT coalesce(pg_catalog.array_agg(s.invoke_id ORDER BY s.invoke_id), '{}'::uuid[])
    INTO v_ids
  FROM (
    SELECT DISTINCT u.invoke_id
    FROM pg_catalog.unnest(p_ids) AS seed(invoke_id)
    CROSS JOIN LATERAL pg_catalog.unnest(v15.v15_repl_closure(seed.invoke_id)) AS u(invoke_id)
  ) s;
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
  SELECT coalesce(pg_catalog.array_agg(s.invoke_id ORDER BY s.invoke_id), '{}'::uuid[])
    INTO v_after
  FROM (
    SELECT DISTINCT u.invoke_id
    FROM pg_catalog.unnest(p_ids) AS seed(invoke_id)
    CROSS JOIN LATERAL pg_catalog.unnest(v15.v15_repl_closure(seed.invoke_id)) AS u(invoke_id)
  ) s;
  v_after_pools := v15.v15_repl_pools(v_after);
  IF v_after IS DISTINCT FROM v_ids OR v_after_pools IS DISTINCT FROM v_pools THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_io_deliver_completed(p_child uuid) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_parent uuid;
  v_iter integer;
  v_stmt integer;
  v_name text;
  v_value jsonb;
  v_kind text;
  v_capture text;
  v_fence bigint;
  v_err jsonb;
  v_block text;
  v_output text;
  v_n integer;
BEGIN
  SELECT c.parent_invoke_id, c.return_value, s.iteration, s.stmt_index, s.bind_name,
         it.capture, p.fence
    INTO v_parent, v_value, v_iter, v_stmt, v_name, v_capture, v_fence
  FROM v15.invokes c
  JOIN v15.statements s
    ON s.invoke_id = c.parent_invoke_id
   AND s.child_invoke_id = c.invoke_id
   AND s.status = 'running'
  JOIN v15.invokes p ON p.invoke_id = c.parent_invoke_id
  JOIN v15.iterations it
    ON it.invoke_id = p.invoke_id
   AND it.iteration = s.iteration
  WHERE c.invoke_id = p_child
    AND c.status = 'completed';
  IF NOT FOUND OR v_name IS NULL OR v_value IS NULL THEN
    RAISE EXCEPTION 'V15_DELIVERY_CONFLICT' USING ERRCODE = 'P1527';
  END IF;
  SELECT b.kind INTO v_kind
  FROM v15.bindings b
  WHERE b.invoke_id = v_parent
    AND b.name = v_name;
  IF FOUND AND v_kind IN ('input', 'scope', 'tool') THEN
    v_err := v15.v15_io_error('V15_DELIVERY_CONFLICT', '');
    UPDATE v15.statements s
    SET status = 'failed',
        error = v_err,
        error_sqlstate = v_err->>'sqlstate',
        revision = s.revision + 1
    WHERE s.invoke_id = v_parent
      AND s.iteration = v_iter
      AND s.stmt_index = v_stmt;
    PERFORM v15.v15_repl_skip_after(v_parent, v_iter, v_stmt);
    v_block := '[v15 exception V15_DELIVERY_CONFLICT]' || E'\n';
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
             SELECT max(m.msg_seq) FROM v15.llm_messages m WHERE m.invoke_id = v_parent
           ), -1) + 1,
           'iter:' || v_iter::text || ':observation',
           v_iter, 'user', 'observation', v_output;
    INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
    VALUES (v_parent, v_iter + 1, 'pending', 0, '');
    PERFORM v15.v15_repl_close_span(v_parent, v_iter, 'repl_exec', 'failed', v_fence);
    UPDATE v15.invokes i
    SET status = 'runnable',
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = v_parent;
    PERFORM v15.v15_repl_event(
      v_parent, 'audit', NULL, NULL, NULL,
      pg_catalog.jsonb_build_object('op', 'child_error', 'code', 'V15_DELIVERY_CONFLICT'),
      v_fence
    );
    RETURN;
  END IF;
  IF FOUND THEN
    UPDATE v15.bindings b
    SET value = v_value,
        provenance = 'delivery',
        revision = b.revision + 1
    WHERE b.invoke_id = v_parent
      AND b.name = v_name
      AND b.kind = 'var';
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'V15_DELIVERY_CONFLICT' USING ERRCODE = 'P1527';
    END IF;
  ELSE
    INSERT INTO v15.bindings (
      invoke_id, name, kind, value, show_in_prompt, provenance
    ) VALUES (
      v_parent, v_name, 'var', v_value, true, 'delivery'
    );
  END IF;
  UPDATE v15.statements s
  SET status = 'done',
      error = NULL,
      error_sqlstate = NULL,
      revision = s.revision + 1
  WHERE s.invoke_id = v_parent
    AND s.iteration = v_iter
    AND s.stmt_index = v_stmt
    AND s.status = 'running';
  UPDATE v15.iterations i
  SET status = 'executing',
      resume_stmt = v_stmt + 1,
      revision = i.revision + 1
  WHERE i.invoke_id = v_parent
    AND i.iteration = v_iter;
  UPDATE v15.invokes i
  SET status = 'runnable',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = v_parent;
  PERFORM v15.v15_repl_event(
    v_parent, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'deliver',
      'child_invoke_id', p_child,
      'bind_name', v_name
    ),
    v_fence
  );
END;
$fn$;

CREATE FUNCTION v15.v15_io_deliver_child(p_child uuid) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_status text;
  v_fatal boolean;
  v_code text;
BEGIN
  SELECT i.status, i.fatal, i.error->>'code'
    INTO v_status, v_fatal, v_code
  FROM v15.invokes i
  WHERE i.invoke_id = p_child;
  IF NOT FOUND OR v_status NOT IN ('completed', 'failed', 'aborted') THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_assert_bind_wait(p_child);
  IF v_fatal OR v_status = 'aborted' THEN
    IF v_code IS NULL OR v15.v15_repl_sqlstate(v_code) IS NULL THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    PERFORM v15.v15_repl_fatal_expand(p_child, v_code, '');
  ELSIF v_status = 'failed' THEN
    PERFORM v15.v15_repl_deliver_nonfatal(p_child);
  ELSE
    PERFORM v15.v15_io_deliver_completed(p_child);
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_io_reclaim_invoke(p_invoke_id uuid) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_running integer;
  v_terminal integer;
  v_iter integer;
  v_child uuid;
  v_child_status text;
  v_fence bigint;
BEGIN
  SELECT count(*) INTO v_running
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.status = 'running';
  SELECT count(*) INTO v_terminal
  FROM v15.statements s
  JOIN v15.invokes c ON c.invoke_id = s.child_invoke_id
  WHERE s.invoke_id = p_invoke_id
    AND s.status = 'running'
    AND c.status IN ('completed', 'failed', 'aborted');
  IF v_terminal > 0 THEN
    SELECT s.iteration, s.child_invoke_id
      INTO v_iter, v_child
    FROM v15.statements s
    JOIN v15.invokes c ON c.invoke_id = s.child_invoke_id
    WHERE s.invoke_id = p_invoke_id
      AND s.status = 'running'
      AND c.status IN ('completed', 'failed', 'aborted')
    ORDER BY s.stmt_index
    LIMIT 1;
    UPDATE v15.invokes i
    SET status = 'suspended',
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = p_invoke_id
    RETURNING i.fence INTO v_fence;
    UPDATE v15.iterations it
    SET status = 'suspended',
        revision = it.revision + 1
    WHERE it.invoke_id = p_invoke_id
      AND it.iteration = v_iter;
    PERFORM v15.v15_repl_event(
      p_invoke_id, 'audit', NULL, NULL, NULL,
      pg_catalog.jsonb_build_object('op', 'lease_reclaimed'),
      v_fence
    );
    PERFORM v15.v15_io_deliver_child(v_child);
    RETURN;
  END IF;
  SELECT s.iteration, s.child_invoke_id, c.status
    INTO v_iter, v_child, v_child_status
  FROM v15.statements s
  LEFT JOIN v15.invokes c ON c.invoke_id = s.child_invoke_id
  WHERE s.invoke_id = p_invoke_id
    AND s.status = 'running'
  ORDER BY s.stmt_index
  LIMIT 1;
  IF v_running = 0 THEN
    UPDATE v15.invokes i
    SET fence = i.fence + 1,
        status = 'runnable',
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = p_invoke_id
    RETURNING i.fence INTO v_fence;
  ELSIF v_child IS NULL THEN
    UPDATE v15.statements s
    SET status = 'pending',
        revision = s.revision + 1
    WHERE s.invoke_id = p_invoke_id
      AND s.status = 'running'
      AND s.child_invoke_id IS NULL;
    UPDATE v15.invokes i
    SET fence = i.fence + 1,
        status = 'runnable',
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = p_invoke_id
    RETURNING i.fence INTO v_fence;
  ELSE
    UPDATE v15.invokes i
    SET fence = i.fence + 1,
        status = 'suspended',
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = p_invoke_id
    RETURNING i.fence INTO v_fence;
    UPDATE v15.iterations it
    SET status = 'suspended',
        revision = it.revision + 1
    WHERE it.invoke_id = p_invoke_id
      AND it.iteration = v_iter;
  END IF;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object('op', 'lease_reclaimed'),
    v_fence
  );
END;
$fn$;

CREATE FUNCTION v15.v15_claim(
  p_invoke_id uuid,
  p_owner text,
  p_lease interval
) RETURNS bigint
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_fence bigint;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL
     OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200
     OR p_lease IS NULL
     OR NOT pg_catalog.isfinite(p_lease)
     OR p_lease <= interval '0' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT * INTO v_inv
  FROM v15.invokes i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'runnable'
    AND (i.lease_owner IS NULL OR i.lease_until <= pg_catalog.clock_timestamp())
  FOR UPDATE SKIP LOCKED;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  UPDATE v15.invokes i
  SET fence = i.fence + 1,
      status = 'leased',
      lease_owner = p_owner,
      lease_until = pg_catalog.clock_timestamp() + p_lease,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id
  RETURNING i.fence INTO v_fence;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object('op', 'claim', 'fence', v_fence, 'owner', p_owner),
    v_fence
  );
  RETURN v_fence;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_begin_llm(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_base_messages jsonb
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_n integer;
  v_iter integer;
  v_status text;
  v_retry boolean;
  v_req v15.llm_requests;
  v_prev v15.llm_attempts;
  v_next integer;
  v_max_iter integer;
  v_max_io integer;
  v_limit integer;
  v_raw text;
  v_chars bigint := 0;
  v_stored jsonb;
  v_elem jsonb;
  v_row jsonb;
  v_i integer;
  v_expected_kind text;
  v_base jsonb := '[]'::jsonb;
  v_base_digest text;
  v_enter_io jsonb;
  v_enter_ret jsonb;
  v_send_io jsonb;
  v_send_ret jsonb;
  v_enter_messages jsonb := 'null'::jsonb;
  v_send_messages jsonb := 'null'::jsonb;
  v_overlay jsonb := '{}'::jsonb;
  v_final jsonb;
  v_attempt uuid;
  v_request jsonb;
  v_request_id uuid;
  v_digest text;
  v_calls integer;
  v_cost numeric;
  v_budget jsonb;
  v_calls_text text;
  v_cost_text text;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR p_base_messages IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_assert_manifest();
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  PERFORM v15.v15_assert_invoke_manifest(p_invoke_id);
  SELECT count(*) INTO v_n
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status IN ('pending', 'llm');
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.iteration, i.status INTO STRICT v_iter, v_status
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status IN ('pending', 'llm')
  FOR UPDATE;
  IF EXISTS (
    SELECT 1
    FROM v15.llm_attempts a
    JOIN v15.llm_requests r ON r.request_id = a.request_id
    WHERE r.invoke_id = p_invoke_id
      AND r.iteration = v_iter
      AND a.status = 'leased'
  ) THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_status = 'pending' THEN
    IF v15.v15_span_open(p_invoke_id, 'llm_query')
       OR EXISTS (
         SELECT 1 FROM v15.llm_requests r
         WHERE r.invoke_id = p_invoke_id AND r.iteration = v_iter
       ) THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    v_retry := false;
    v_next := 1;
  ELSIF v_status = 'llm' THEN
    IF NOT v15.v15_span_open(p_invoke_id, 'llm_query') THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    SELECT * INTO v_req
    FROM v15.llm_requests r
    WHERE r.invoke_id = p_invoke_id
      AND r.iteration = v_iter
      AND r.status = 'open'
    FOR UPDATE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    SELECT count(*), coalesce(max(a.n), 0)
      INTO v_n, v_next
    FROM v15.llm_attempts a
    WHERE a.request_id = v_req.request_id;
    IF v_n < 1 THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    v_next := v_next + 1;
    v_retry := true;
  ELSE
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_max_iter := v15.v15_baseline_max(p_invoke_id, 'governance_iterations');
  v_max_io := v15.v15_baseline_max(p_invoke_id, 'governance_io');
  IF v_iter >= v_max_iter THEN
    PERFORM v15.v15_io_terminal(
      p_invoke_id, v_iter, 'V15_ITERATION_EXCEEDED', false, NULL
    );
    RETURN v15.v15_io_abort_result(false, 'V15_ITERATION_EXCEEDED');
  END IF;
  IF v_next > v_max_io THEN
    IF v_retry THEN
      UPDATE v15.llm_requests r
      SET status = 'exhausted',
          revision = r.revision + 1
      WHERE r.request_id = v_req.request_id
        AND r.status = 'open';
    END IF;
    PERFORM v15.v15_io_terminal(
      p_invoke_id, v_iter, 'V15_IO_EXHAUSTED', false, NULL
    );
    RETURN v15.v15_io_abort_result(false, 'V15_IO_EXHAUSTED');
  END IF;
  IF v_retry THEN
    SELECT * INTO v_prev
    FROM v15.llm_attempts a
    WHERE a.request_id = v_req.request_id
    ORDER BY a.n DESC
    LIMIT 1;
    IF pg_catalog.jsonb_typeof(v_prev.request->'messages') <> 'array' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_attempt := pg_catalog.gen_random_uuid();
    v_request := pg_catalog.jsonb_build_object(
      'attempt_id', v_attempt,
      'messages', v_prev.request->'messages'
    );
    v_digest := pg_catalog.md5((v_request - 'attempt_id')::text);
    IF v_digest IS DISTINCT FROM v_req.logical_digest THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF NOT v15.v15_io_pool_reserve(
      v_inv.pool_id, v_prev.reserved_calls, v_prev.reserved_cost
    ) THEN
      PERFORM v15.v15_io_terminal(
        p_invoke_id, v_iter, 'V15_BUDGET_EXHAUSTED', true, NULL
      );
      RETURN v15.v15_io_abort_result(true, 'V15_BUDGET_EXHAUSTED');
    END IF;
    INSERT INTO v15.llm_attempts (
      attempt_id, request_id, n, status, fence, lease_owner, lease_until,
      pool_id, reserved_calls, reserved_cost, call_started, calls_charged, request
    ) VALUES (
      v_attempt, v_req.request_id, v_next, 'leased', 1, p_owner, v_inv.lease_until,
      v_inv.pool_id, v_prev.reserved_calls, v_prev.reserved_cost,
      false, false, v_request
    );
    SELECT coalesce(sum(pg_catalog.char_length(e.value->>'content')), 0)
      INTO v_chars
    FROM pg_catalog.jsonb_array_elements(v_prev.request->'messages') AS e(value);
    PERFORM v15.v15_repl_event(
      p_invoke_id, 'audit', NULL, NULL, NULL,
      pg_catalog.jsonb_build_object(
        'op', 'attempt_leased', 'attempt_id', v_attempt, 'n', v_next
      ),
      v_inv.fence
    );
    RETURN pg_catalog.jsonb_build_object(
      'attempt_id', v_attempt,
      'request', v_request,
      'logical_digest', v_digest,
      'input_chars', v_chars,
      'n', v_next,
      'action', 'proceed'
    );
  END IF;
  IF pg_catalog.jsonb_typeof(p_base_messages) <> 'array' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(
    pg_catalog.jsonb_build_object(
      'message_id', m.message_id,
      'role', m.role,
      'kind', m.kind
    ) ORDER BY m.msg_seq
  ), '[]'::jsonb)
    INTO v_stored
  FROM v15.llm_messages m
  WHERE m.invoke_id = p_invoke_id;
  IF pg_catalog.jsonb_array_length(p_base_messages)
     IS DISTINCT FROM pg_catalog.jsonb_array_length(v_stored)
     OR pg_catalog.jsonb_array_length(v_stored) < 1
     OR v_stored->0->>'message_id' IS DISTINCT FROM 'seed:system' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  FOR v_i IN 0 .. pg_catalog.jsonb_array_length(p_base_messages) - 1 LOOP
    v_elem := p_base_messages -> v_i;
    v_row := v_stored -> v_i;
    IF pg_catalog.jsonb_typeof(v_elem) <> 'object'
       OR (
         SELECT count(*) FROM pg_catalog.jsonb_object_keys(v_elem) AS k(key)
       ) <> 4
       OR NOT (
         pg_catalog.jsonb_exists(v_elem, 'message_id')
         AND pg_catalog.jsonb_exists(v_elem, 'role')
         AND pg_catalog.jsonb_exists(v_elem, 'kind')
         AND pg_catalog.jsonb_exists(v_elem, 'content')
       )
       OR pg_catalog.jsonb_typeof(v_elem->'message_id') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'role') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'kind') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem->'content') <> 'string'
       OR v_elem->>'message_id' IS DISTINCT FROM v_row->>'message_id'
       OR v_elem->>'role' IS DISTINCT FROM v_row->>'role'
       OR v_elem->>'role' NOT IN ('system', 'user', 'assistant') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_row->>'message_id' = 'seed:system' THEN
      v_expected_kind := 'system';
    ELSIF v_row->>'message_id' = 'seed:inputs' THEN
      v_expected_kind := 'input';
    ELSE
      v_expected_kind := v_row->>'kind';
    END IF;
    IF v_elem->>'kind' IS DISTINCT FROM v_expected_kind
       OR v_elem->>'kind' NOT IN (
         'system', 'input', 'assistant', 'observation', 'persistent_hook'
       ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_chars := v_chars + pg_catalog.char_length(v_elem->>'content');
    v_base := v_base || pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'seq', v_i,
        'message_id', v_elem->>'message_id',
        'role', v_elem->>'role',
        'kind', v_elem->>'kind',
        'content', v_elem->>'content'
      )
    );
  END LOOP;
  v_raw := v_inv.resolved_config->'protocol'->>'max_invoke_input_length';
  IF v_raw IS NULL OR v_raw !~ '^[0-9]+$'
     OR v_raw::numeric < 1 OR v_raw::numeric > 2147483647 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_limit := v_raw::integer;
  IF v_chars > v_limit THEN
    PERFORM v15.v15_io_terminal(
      p_invoke_id, v_iter, 'V15_VALUE_INVALID', false, NULL
    );
    RETURN v15.v15_io_abort_result(false, 'V15_VALUE_INVALID');
  END IF;
  v_base_digest := pg_catalog.md5(
    pg_catalog.jsonb_build_object('messages', v_base)::text
  );
  v_enter_io := pg_catalog.jsonb_build_object(
    'iteration', v_iter,
    'next_attempt_n', v_next
  );
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'llm_query', 'enter', NULL, v_enter_io, v_inv.fence
  );
  v_enter_ret := v15.v15_on_phase(
    p_invoke_id, v_iter, 'llm_query', 'enter', v_enter_io
  );
  PERFORM v15.v15_repl_assert_phase(v_enter_ret);
  IF v_enter_ret->>'action' = 'abort' THEN
    PERFORM v15.v15_io_terminal(
      p_invoke_id, v_iter, v_enter_ret->>'code',
      (v_enter_ret->>'fatal')::boolean, NULL
    );
    RETURN v15.v15_io_abort_result(
      (v_enter_ret->>'fatal')::boolean, v_enter_ret->>'code'
    );
  END IF;
  IF pg_catalog.jsonb_exists(v_enter_ret, 'messages')
     AND v_enter_ret->'messages' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(v_enter_ret->'messages') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    ELSIF pg_catalog.jsonb_array_length(v_enter_ret->'messages') > 0 THEN
      v_enter_messages := v_enter_ret->'messages';
    END IF;
  END IF;
  IF pg_catalog.jsonb_exists(v_enter_ret, 'recursion_available')
     AND v_enter_ret->'recursion_available' IS DISTINCT FROM 'null'::jsonb THEN
    v_overlay := v_overlay || pg_catalog.jsonb_build_object(
      'recursion_available', v_enter_ret->'recursion_available'
    );
  END IF;
  IF pg_catalog.jsonb_exists(v_enter_ret, 'blackboard_writes')
     AND v_enter_ret->'blackboard_writes' IS DISTINCT FROM 'null'::jsonb THEN
    v_overlay := v_overlay || pg_catalog.jsonb_build_object(
      'blackboard_writes', v_enter_ret->'blackboard_writes'
    );
  END IF;
  IF v_overlay = '{}'::jsonb THEN
    v_overlay := 'null'::jsonb;
  END IF;
  v_send_io := pg_catalog.jsonb_build_object(
    'iteration', v_iter,
    'logical_digest', v_base_digest,
    'input_chars', v_chars,
    'enter_messages', v_enter_messages,
    'enter_overlay', v_overlay
  );
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'llm_query', 'send', NULL, v_send_io, v_inv.fence
  );
  v_send_ret := v15.v15_on_phase(
    p_invoke_id, v_iter, 'llm_query', 'send', v_send_io
  );
  PERFORM v15.v15_repl_assert_phase(v_send_ret);
  IF v_send_ret->>'action' = 'abort' THEN
    PERFORM v15.v15_io_terminal(
      p_invoke_id, v_iter, v_send_ret->>'code',
      (v_send_ret->>'fatal')::boolean, NULL
    );
    RETURN v15.v15_io_abort_result(
      (v_send_ret->>'fatal')::boolean, v_send_ret->>'code'
    );
  END IF;
  IF pg_catalog.jsonb_exists(v_send_ret, 'messages')
     AND v_send_ret->'messages' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(v_send_ret->'messages') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    ELSIF pg_catalog.jsonb_array_length(v_send_ret->'messages') > 0 THEN
      v_send_messages := v_send_ret->'messages';
    END IF;
  END IF;
  v_final := v_base;
  IF v_enter_messages <> 'null'::jsonb THEN
    v_final := v15.v15_io_append_hook_messages(v_final, v_enter_messages);
  END IF;
  IF v_send_messages <> 'null'::jsonb THEN
    v_final := v15.v15_io_append_hook_messages(v_final, v_send_messages);
  END IF;
  IF (
    SELECT count(*) <> count(DISTINCT e.value->>'message_id')
    FROM pg_catalog.jsonb_array_elements(v_final) AS e(value)
  ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF pg_catalog.jsonb_exists(v_send_ret, 'budget')
     AND v_send_ret->'budget' IS DISTINCT FROM 'null'::jsonb THEN
    v_budget := v_send_ret->'budget';
    IF pg_catalog.jsonb_typeof(v_budget) <> 'object'
       OR NOT pg_catalog.jsonb_exists(v_budget, 'reserve_calls')
       OR NOT pg_catalog.jsonb_exists(v_budget, 'reserve_cost') THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    v_calls_text := v_budget->>'reserve_calls';
    v_cost_text := v_budget->>'reserve_cost';
    IF v_calls_text !~ '^[0-9]+$' OR v_calls_text::numeric < 1
       OR v_calls_text::numeric > 2147483647
       OR v_cost_text IS NULL OR v_cost_text::numeric < 0 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_calls := v_calls_text::integer;
    v_cost := v_cost_text::numeric;
  ELSE
    v_calls := 1;
    v_cost := 0;
    IF NOT v15.v15_io_pool_reserve(v_inv.pool_id, v_calls, v_cost) THEN
      PERFORM v15.v15_io_terminal(
        p_invoke_id, v_iter, 'V15_BUDGET_EXHAUSTED', true, NULL
      );
      RETURN v15.v15_io_abort_result(true, 'V15_BUDGET_EXHAUSTED');
    END IF;
  END IF;
  v_attempt := pg_catalog.gen_random_uuid();
  v_request_id := pg_catalog.gen_random_uuid();
  v_request := pg_catalog.jsonb_build_object(
    'attempt_id', v_attempt,
    'messages', v_final
  );
  v_digest := pg_catalog.md5((v_request - 'attempt_id')::text);
  INSERT INTO v15.llm_requests (
    request_id, invoke_id, iteration, status, logical_digest
  ) VALUES (
    v_request_id, p_invoke_id, v_iter, 'open', v_digest
  );
  INSERT INTO v15.llm_attempts (
    attempt_id, request_id, n, status, fence, lease_owner, lease_until,
    pool_id, reserved_calls, reserved_cost, call_started, calls_charged, request
  ) VALUES (
    v_attempt, v_request_id, v_next, 'leased', 1, p_owner, v_inv.lease_until,
    v_inv.pool_id, v_calls, v_cost, false, false, v_request
  );
  UPDATE v15.iterations i
  SET status = 'llm',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.iteration = v_iter
    AND i.status = 'pending';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'attempt_leased', 'attempt_id', v_attempt, 'n', v_next
    ),
    v_inv.fence
  );
  RETURN pg_catalog.jsonb_build_object(
    'attempt_id', v_attempt,
    'request', v_request,
    'logical_digest', v_digest,
    'input_chars', v_chars,
    'n', v_next,
    'action', 'proceed'
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_mark_call_started(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_inv v15.invokes;
  v_att v15.llm_attempts;
  v_n integer;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL OR p_attempt_fence IS NULL
     OR p_invoke_fence IS NULL OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id INTO v_invoke
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO v_inv
  FROM v15.invokes i
  WHERE i.invoke_id = v_invoke
  FOR UPDATE;
  SELECT * INTO v_att
  FROM v15.llm_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.fence IS DISTINCT FROM p_attempt_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  IF v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_check_holder(v_inv, p_invoke_fence, p_owner);
  UPDATE v15.llm_attempts a
  SET call_started = true,
      revision = a.revision + 1
  WHERE a.attempt_id = p_attempt_id
    AND a.status = 'leased'
    AND NOT a.call_started
    AND a.fence = p_attempt_fence;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_event(
    v_invoke, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object('op', 'call_started', 'attempt_id', p_attempt_id),
    v_inv.fence
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_settle_llm(
  p_attempt_id uuid,
  p_attempt_fence bigint,
  p_invoke_fence bigint,
  p_owner text,
  p_response jsonb,
  p_statements jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iter integer;
  v_inv v15.invokes;
  v_att v15.llm_attempts;
  v_tokens integer := 0;
  v_usd numeric := 0;
  v_text text;
  v_limit numeric;
  v_used numeric;
  v_io jsonb;
  v_ret jsonb;
  v_n integer;
  v_resume integer;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL OR p_attempt_fence IS NULL
     OR p_invoke_fence IS NULL OR p_owner IS NULL
     OR p_response IS NULL OR p_statements IS NULL
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
  IF NOT v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_check_holder(v_inv, p_invoke_fence, p_owner);
  IF pg_catalog.jsonb_typeof(p_response) <> 'object'
     OR NOT pg_catalog.jsonb_exists(p_response, 'content')
     OR pg_catalog.jsonb_typeof(p_response->'content') <> 'string' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF pg_catalog.jsonb_exists(p_response, 'prompt_tokens')
     AND p_response->'prompt_tokens' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_response->'prompt_tokens') <> 'number' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_text := p_response->>'prompt_tokens';
    IF v_text !~ '^[0-9]+$' OR v_text::numeric > 2147483647 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_tokens := v_text::integer;
  END IF;
  IF pg_catalog.jsonb_exists(p_response, 'cost_usd')
     AND p_response->'cost_usd' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_response->'cost_usd') <> 'number'
       OR (p_response->>'cost_usd')::numeric < 0 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_usd := (p_response->>'cost_usd')::numeric;
  END IF;
  PERFORM v15.v15_io_store_statements(v_invoke, v_iter, p_statements, false);
  PERFORM v15.v15_io_pool_release(
    v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, true, v_usd
  );
  UPDATE v15.llm_attempts a
  SET status = 'settled',
      calls_charged = true,
      lease_owner = NULL,
      lease_until = NULL,
      response = p_response,
      prompt_tokens = v_tokens,
      cost_usd = v_usd,
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
  SET status = 'settled',
      revision = r.revision + 1
  WHERE r.request_id = v_att.request_id
    AND r.status = 'open';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.pool_id IS NOT NULL THEN
    SELECT b.cost_limit, b.cost_used INTO v_limit, v_used
    FROM v15.budget_pools b
    WHERE b.pool_id = v_att.pool_id;
    IF v_limit IS NOT NULL AND v_used > v_limit THEN
      PERFORM v15.v15_io_terminal(
        v_invoke, v_iter, 'V15_BUDGET_EXHAUSTED', true, p_attempt_id
      );
      RETURN;
    END IF;
  END IF;
  v_io := pg_catalog.jsonb_build_object('attempt_id', p_attempt_id);
  PERFORM v15.v15_repl_event(
    v_invoke, 'span', 'llm_query', 'complete', NULL, v_io, v_inv.fence
  );
  v_ret := v15.v15_on_phase(v_invoke, v_iter, 'llm_query', 'complete', v_io);
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    PERFORM v15.v15_io_terminal(
      v_invoke, v_iter, v_ret->>'code',
      (v_ret->>'fatal')::boolean, p_attempt_id
    );
    RETURN;
  END IF;
  PERFORM v15.v15_io_exit_query(
    v_invoke, v_iter, 'completed', p_attempt_id, v_inv.fence
  );
  INSERT INTO v15.llm_messages (
    invoke_id, msg_seq, message_id, iteration, role, kind, content
  )
  SELECT v_invoke,
         coalesce((
           SELECT max(m.msg_seq) FROM v15.llm_messages m WHERE m.invoke_id = v_invoke
         ), -1) + 1,
         'iter:' || v_iter::text || ':assistant',
         v_iter,
         'assistant',
         'assistant',
         p_response->>'content';
  PERFORM v15.v15_io_store_statements(v_invoke, v_iter, p_statements, true);
  SELECT coalesce(
    min(s.stmt_index) FILTER (WHERE s.status NOT IN ('done', 'skipped')),
    count(*)::integer
  )
    INTO v_resume
  FROM v15.statements s
  WHERE s.invoke_id = v_invoke
    AND s.iteration = v_iter;
  UPDATE v15.iterations i
  SET status = 'executing',
      resume_stmt = coalesce(v_resume, 0),
      revision = i.revision + 1
  WHERE i.invoke_id = v_invoke
    AND i.iteration = v_iter
    AND i.status = 'llm';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  PERFORM v15.v15_repl_event(
    v_invoke, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'statements_stored',
      'count', pg_catalog.jsonb_array_length(p_statements)
    ),
    v_inv.fence
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_reclaim_expired() RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_attempt_ids uuid[] := '{}'::uuid[];
  v_seed_ids uuid[] := '{}'::uuid[];
  v_terminated uuid[] := '{}'::uuid[];
  v_candidates uuid[] := '{}'::uuid[];
  v_attempt uuid;
  v_invoke uuid;
  v_att v15.llm_attempts;
  v_status text;
  v_fence bigint;
  v_count integer := 0;
  v_id uuid;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  SELECT coalesce(pg_catalog.array_agg(a.attempt_id ORDER BY a.attempt_id), '{}'::uuid[]),
         coalesce(pg_catalog.array_agg(DISTINCT r.invoke_id), '{}'::uuid[])
    INTO v_attempt_ids, v_seed_ids
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE a.status = 'leased'
    AND a.lease_until <= pg_catalog.clock_timestamp();
  SELECT coalesce(pg_catalog.array_agg(i.invoke_id ORDER BY i.invoke_id), '{}'::uuid[])
    INTO v_candidates
  FROM v15.invokes i
  WHERE i.status = 'leased'
    AND i.lease_until <= pg_catalog.clock_timestamp();
  v_seed_ids := (
    SELECT coalesce(pg_catalog.array_agg(s.invoke_id ORDER BY s.invoke_id), '{}'::uuid[])
    FROM (
      SELECT pg_catalog.unnest(v_seed_ids) AS invoke_id
      UNION
      SELECT pg_catalog.unnest(v_candidates)
    ) s
  );
  IF cardinality(v_attempt_ids) = 0 AND cardinality(v_seed_ids) = 0 THEN
    RETURN 0;
  END IF;
  PERFORM v15.v15_io_lock_ids(v_seed_ids);
  FOREACH v_attempt IN ARRAY v_attempt_ids LOOP
    SELECT a.* INTO v_att
    FROM v15.llm_attempts a
    WHERE a.attempt_id = v_attempt
      AND a.status = 'leased'
      AND a.lease_until <= pg_catalog.clock_timestamp()
    FOR UPDATE;
    IF NOT FOUND THEN
      CONTINUE;
    END IF;
    SELECT r.invoke_id, i.fence
      INTO v_invoke, v_fence
    FROM v15.llm_requests r
    JOIN v15.invokes i ON i.invoke_id = r.invoke_id
    WHERE r.request_id = v_att.request_id;
    IF v_att.call_started THEN
      v_status := 'unknown';
      PERFORM v15.v15_io_pool_release(
        v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, true, 0
      );
      UPDATE v15.llm_attempts a
      SET status = 'unknown',
          calls_charged = true,
          lease_owner = NULL,
          lease_until = NULL,
          revision = a.revision + 1
      WHERE a.attempt_id = v_attempt
        AND a.status = 'leased'
        AND a.call_started
        AND NOT a.calls_charged;
    ELSE
      v_status := 'failed';
      PERFORM v15.v15_io_pool_release(
        v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, false, 0
      );
      UPDATE v15.llm_attempts a
      SET status = 'failed',
          lease_owner = NULL,
          lease_until = NULL,
          revision = a.revision + 1
      WHERE a.attempt_id = v_attempt
        AND a.status = 'leased'
        AND NOT a.call_started
        AND NOT a.calls_charged;
    END IF;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    PERFORM v15.v15_repl_event(
      v_invoke, 'span', 'llm_query', 'retry', NULL,
      pg_catalog.jsonb_build_object(
        'old_attempt_id', v_attempt,
        'old_status', v_status,
        'new_attempt_id', 'null'::jsonb
      ),
      v_fence
    );
    v_terminated := v_terminated || ARRAY[v_invoke];
    v_count := v_count + 1;
  END LOOP;
  SELECT coalesce(pg_catalog.array_agg(s.invoke_id ORDER BY s.invoke_id), '{}'::uuid[])
    INTO v_candidates
  FROM (
    SELECT pg_catalog.unnest(v_candidates) AS invoke_id
    UNION
    SELECT pg_catalog.unnest(v_terminated)
  ) s;
  FOREACH v_id IN ARRAY v_candidates LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM v15.invokes i
      WHERE i.invoke_id = v_id
        AND i.status = 'leased'
    ) THEN
      CONTINUE;
    END IF;
    IF EXISTS (
      SELECT 1
      FROM v15.llm_attempts a
      JOIN v15.llm_requests r ON r.request_id = a.request_id
      WHERE r.invoke_id = v_id
        AND a.status = 'leased'
    ) THEN
      CONTINUE;
    END IF;
    IF NOT EXISTS (
      SELECT 1
      FROM v15.invokes i
      WHERE i.invoke_id = v_id
        AND (
          i.lease_until <= pg_catalog.clock_timestamp()
          OR v_id = ANY (v_terminated)
        )
    ) THEN
      CONTINUE;
    END IF;
    PERFORM v15.v15_io_reclaim_invoke(v_id);
  END LOOP;
  RETURN v_count;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

ALTER FUNCTION v15.v15_io_sqlstate(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_error(text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_abort_result(boolean, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_pool_reserve(uuid, integer, numeric) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_pool_release(uuid, integer, numeric, boolean, numeric) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_exit_query(uuid, integer, text, uuid, bigint) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_close_self(uuid, integer, text, boolean, uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_terminal(uuid, integer, text, boolean, uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_append_hook_messages(jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_store_statements(uuid, integer, jsonb, boolean) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_lock_ids(uuid[]) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_deliver_completed(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_deliver_child(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_reclaim_invoke(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_claim(uuid, text, interval) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_begin_llm(uuid, bigint, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_mark_call_started(uuid, bigint, bigint, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_settle_llm(uuid, bigint, bigint, text, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_reclaim_expired() OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_io_sqlstate(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_error(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_abort_result(boolean, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_pool_reserve(uuid, integer, numeric) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_pool_release(uuid, integer, numeric, boolean, numeric) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_exit_query(uuid, integer, text, uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_close_self(uuid, integer, text, boolean, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_terminal(uuid, integer, text, boolean, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_append_hook_messages(jsonb, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_store_statements(uuid, integer, jsonb, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_lock_ids(uuid[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_deliver_completed(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_deliver_child(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_reclaim_invoke(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_claim(uuid, text, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_begin_llm(uuid, bigint, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_mark_call_started(uuid, bigint, bigint, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_settle_llm(uuid, bigint, bigint, text, jsonb, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_reclaim_expired() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_claim(uuid, text, interval) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_begin_llm(uuid, bigint, text, jsonb) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_mark_call_started(uuid, bigint, bigint, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_settle_llm(uuid, bigint, bigint, text, jsonb, jsonb) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_reclaim_expired() TO v15_worker;
