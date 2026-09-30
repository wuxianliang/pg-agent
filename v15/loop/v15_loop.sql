DO $grant$
BEGIN
  EXECUTE format(
    'GRANT CREATE ON DATABASE %I TO v15_owner',
    current_database()
  );
END
$grant$;

CREATE FUNCTION v15.v15_loop_sqlstate(p_code text) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT coalesce(
    v15.v15_repl_sqlstate(p_code),
    v15.v15_io_sqlstate(p_code),
    CASE p_code
      WHEN 'V15_SCOPE_CONFLICT' THEN 'P1509'
      WHEN 'V15_RAISE' THEN 'P1529'
      WHEN 'V15_VALIDATION_FAILED' THEN 'P1540'
      WHEN 'V15_VALUE_INVALID' THEN 'P1524'
      WHEN 'V15_INVALID_EFFECT' THEN 'P1506'
      ELSE NULL
    END
  )
$fn$;

CREATE FUNCTION v15.v15_loop_error(p_code text, p_message text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_state text;
BEGIN
  v_state := v15.v15_loop_sqlstate(p_code);
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

CREATE FUNCTION v15.v15_loop_drop_scratch(p_name text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_name IS NOT NULL AND EXISTS (
    SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname = p_name
  ) THEN
    EXECUTE pg_catalog.format('DROP SCHEMA %I CASCADE', p_name);
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_loop_assistant(p_invoke_id uuid, p_iteration integer)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT coalesce((
    SELECT m.content
    FROM v15.llm_messages m
    WHERE m.invoke_id = p_invoke_id
      AND m.iteration = p_iteration
      AND m.kind = 'assistant'
    ORDER BY m.msg_seq
    LIMIT 1
  ), '')
$fn$;

CREATE FUNCTION v15.v15_loop_compose_inputs(p_invoke_id uuid) RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT CASE
    WHEN count(*) = 0 THEN NULL
    ELSE 'inputs:' || E'\n' || string_agg(
      b.name || ': ' || b.value::text,
      E'\n' ORDER BY convert_to(b.name, 'UTF8')
    )
  END
  FROM v15.bindings b
  WHERE b.invoke_id = p_invoke_id
    AND b.kind = 'input'
    AND b.show_in_prompt
$fn$;

CREATE FUNCTION v15.v15_loop_install_hook(
  p_invoke_id uuid,
  p_ordinal integer,
  p_key text,
  p_channel text,
  p_config jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  INSERT INTO v15.invoke_hooks (
    invoke_id, ordinal, hook_def_id, channel, config, state
  )
  SELECT p_invoke_id, p_ordinal, d.hook_def_id, p_channel, p_config, '{}'::jsonb
  FROM v15.hook_defs d
  WHERE d.hook_key = p_key;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_loop_install_hooks(
  p_invoke_id uuid,
  p_scope_id uuid,
  p_local_layer_id uuid,
  p_iterations integer,
  p_depth integer,
  p_io integer,
  p_statement integer
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ord integer := 0;
  v_hooks jsonb;
  v_i integer;
  v_key text;
  v_elem jsonb;
  v_layer record;
BEGIN
  PERFORM v15.v15_loop_install_hook(
    p_invoke_id, 0, 'governance_iterations', 'baseline',
    pg_catalog.jsonb_build_object('max', p_iterations)
  );
  PERFORM v15.v15_loop_install_hook(
    p_invoke_id, 1, 'governance_depth', 'baseline',
    pg_catalog.jsonb_build_object('max', p_depth)
  );
  PERFORM v15.v15_loop_install_hook(
    p_invoke_id, 2, 'governance_io', 'baseline',
    pg_catalog.jsonb_build_object('max', p_io)
  );
  PERFORM v15.v15_loop_install_hook(
    p_invoke_id, 3, 'governance_statement', 'baseline',
    pg_catalog.jsonb_build_object('max', p_statement)
  );
  v_ord := 4;
  SELECT p.baseline_hooks INTO v_hooks
  FROM v15.config_scopes s
  JOIN v15.config_profiles p ON p.profile_id = s.profile_id
  WHERE s.scope_id = p_scope_id;
  IF v_hooks IS NULL OR pg_catalog.jsonb_typeof(v_hooks) <> 'array' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  FOR v_i IN 0 .. pg_catalog.jsonb_array_length(v_hooks) - 1 LOOP
    v_key := v_hooks ->> v_i;
    IF EXISTS (
      SELECT 1
      FROM v15.invoke_hooks h
      JOIN v15.hook_defs d ON d.hook_def_id = h.hook_def_id
      WHERE h.invoke_id = p_invoke_id
        AND d.hook_key = v_key
    ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    PERFORM v15.v15_loop_install_hook(
      p_invoke_id, v_ord, v_key, 'baseline', '{}'::jsonb
    );
    v_ord := v_ord + 1;
  END LOOP;
  FOR v_layer IN
    SELECT l.extra_hooks
    FROM v15.config_layers l
    WHERE l.scope_id = p_scope_id
      AND l.kind = 'plain'
      AND l.extra_hooks IS NOT NULL
    ORDER BY l.ordinal
  LOOP
    IF pg_catalog.jsonb_typeof(v_layer.extra_hooks) <> 'array' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    FOR v_i IN 0 .. pg_catalog.jsonb_array_length(v_layer.extra_hooks) - 1 LOOP
      v_elem := v_layer.extra_hooks -> v_i;
      v_key := v_elem ->> 'hook_key';
      PERFORM v15.v15_loop_install_hook(
        p_invoke_id, v_ord, v_key, 'propagating',
        coalesce(v_elem -> 'config', '{}'::jsonb)
      );
      v_ord := v_ord + 1;
    END LOOP;
  END LOOP;
  IF p_local_layer_id IS NOT NULL THEN
    SELECT l.extra_hooks INTO v_hooks
    FROM v15.config_layers l
    WHERE l.layer_id = p_local_layer_id;
    IF v_hooks IS NOT NULL THEN
      FOR v_i IN 0 .. pg_catalog.jsonb_array_length(v_hooks) - 1 LOOP
        v_elem := v_hooks -> v_i;
        v_key := v_elem ->> 'hook_key';
        PERFORM v15.v15_loop_install_hook(
          p_invoke_id, v_ord, v_key, 'local',
          coalesce(v_elem -> 'config', '{}'::jsonb)
        );
        v_ord := v_ord + 1;
      END LOOP;
    END IF;
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_loop_close_open(
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
  v_scratch text;
  v_ret jsonb;
BEGIN
  v_err := v15.v15_loop_error(p_code, p_message);
  v_outcome := CASE WHEN p_fatal THEN 'aborted' ELSE 'failed' END;
  UPDATE v15.iterations i
  SET status = 'done',
      result_kind = 'continue',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.iteration = 0;
  INSERT INTO v15.repl_history (
    invoke_id, iteration, llm_response, repl_output, repl_exception
  ) VALUES (
    p_invoke_id, 0, '', '', v_err
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
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'invoke', 'exit', v_outcome,
    pg_catalog.jsonb_build_object('outcome', v_outcome),
    v_fence
  );
  v_ret := v15.v15_on_phase(
    p_invoke_id, 0, 'invoke', 'exit',
    pg_catalog.jsonb_build_object('outcome', v_outcome)
  );
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
  END IF;
  PERFORM v15.v15_loop_drop_scratch(v_scratch);
END;
$fn$;

CREATE FUNCTION v15.v15_loop_validate_inputs(p_inputs jsonb) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_i integer;
  v_elem jsonb;
  v_key text;
  v_name text;
  v_kind text;
  v_prov text;
  v_tool uuid;
  v_seen text[] := '{}'::text[];
BEGIN
  IF p_inputs IS NULL OR pg_catalog.jsonb_typeof(p_inputs) <> 'array' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  FOR v_i IN 0 .. pg_catalog.jsonb_array_length(p_inputs) - 1 LOOP
    v_elem := p_inputs -> v_i;
    IF pg_catalog.jsonb_typeof(v_elem) <> 'object' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    FOR v_key IN SELECT pg_catalog.jsonb_object_keys(v_elem) LOOP
      IF v_key <> ALL (ARRAY[
        'name', 'kind', 'value', 'show_in_prompt', 'tool_id', 'provenance'
      ]::text[]) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    IF NOT pg_catalog.jsonb_exists(v_elem, 'name')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'kind')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'value')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'show_in_prompt')
       OR NOT pg_catalog.jsonb_exists(v_elem, 'provenance')
       OR pg_catalog.jsonb_typeof(v_elem -> 'name') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem -> 'kind') <> 'string'
       OR pg_catalog.jsonb_typeof(v_elem -> 'show_in_prompt') <> 'boolean'
       OR pg_catalog.jsonb_typeof(v_elem -> 'provenance') <> 'string' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_name := v_elem ->> 'name';
    v_kind := v_elem ->> 'kind';
    v_prov := v_elem ->> 'provenance';
    PERFORM v15.v15_check_binding_name(v_name);
    IF v_kind NOT IN ('input', 'scope', 'tool') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_kind = 'input' AND v_prov IS DISTINCT FROM 'explicit' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_kind = 'scope' AND v_prov IS DISTINCT FROM 'scope' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_kind = 'tool' AND v_prov NOT IN ('explicit', 'scope') THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF v_name = ANY (v_seen) THEN
      RAISE EXCEPTION 'V15_SCOPE_CONFLICT' USING ERRCODE = 'P1509';
    END IF;
    v_seen := v_seen || v_name;
    IF v_kind = 'tool' THEN
      IF NOT pg_catalog.jsonb_exists(v_elem, 'tool_id')
         OR pg_catalog.jsonb_typeof(v_elem -> 'tool_id') <> 'string' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      v_tool := (v_elem ->> 'tool_id')::uuid;
      IF NOT EXISTS (
        SELECT 1 FROM v15.tool_catalog t WHERE t.tool_id = v_tool
      ) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    ELSIF pg_catalog.jsonb_exists(v_elem, 'tool_id')
          AND v_elem -> 'tool_id' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_loop_store_inputs(
  p_invoke_id uuid,
  p_inputs jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_i integer;
  v_elem jsonb;
  v_tool uuid;
BEGIN
  FOR v_i IN 0 .. pg_catalog.jsonb_array_length(p_inputs) - 1 LOOP
    v_elem := p_inputs -> v_i;
    v_tool := NULL;
    IF v_elem ->> 'kind' = 'tool' THEN
      v_tool := (v_elem ->> 'tool_id')::uuid;
    END IF;
    INSERT INTO v15.bindings (
      invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
    ) VALUES (
      p_invoke_id,
      v_elem ->> 'name',
      v_elem ->> 'kind',
      v_elem -> 'value',
      v_tool,
      (v_elem ->> 'show_in_prompt')::boolean,
      v_elem ->> 'provenance'
    );
    IF v_tool IS NOT NULL THEN
      INSERT INTO v15.tool_grants (invoke_id, tool_id)
      VALUES (p_invoke_id, v_tool);
    END IF;
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_open_invoke(
  p_invoke_id uuid,
  p_config_scope_id uuid,
  p_local_layer_id uuid,
  p_inputs jsonb,
  p_pool_id uuid,
  p_ceilings jsonb,
  p_system text,
  p_user text
) RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ceilings jsonb;
  v_manifest text;
  v_resolved jsonb;
  v_config_digest text;
  v_scratch text;
  v_depth integer;
  v_max_depth integer;
  v_ret jsonb;
  v_inputs text;
  v_seq bigint;
  v_i integer;
  v_msg jsonb;
  v_fatal boolean;
  v_code text;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_system IS NULL OR p_system = '' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_assert_manifest();
  PERFORM v15.v15_loop_validate_inputs(p_inputs);
  SELECT c.ceilings, c.manifest_digest
    INTO v_ceilings, v_manifest
  FROM v15.v15_effective_ceilings(p_ceilings, NULL) AS c;
  SELECT r.resolved_config, r.config_digest
    INTO v_resolved, v_config_digest
  FROM v15.v15_resolve_config(p_config_scope_id, p_local_layer_id, 1) AS r;
  v_max_depth := (v_ceilings ->> 'max_depth')::integer;
  v_scratch := 's_' || replace(p_invoke_id::text, '-', '');
  INSERT INTO v15.invokes (
    invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
    status, fatal, recursion_available, resolved_config, config_digest,
    config_scope_id, local_layer_id, pool_id, manifest_digest, scratch_schema,
    fence, created_at, updated_at
  ) VALUES (
    p_invoke_id, NULL, NULL, p_invoke_id, 1,
    'pending', false, (1 < v_max_depth), v_resolved, v_config_digest,
    p_config_scope_id, p_local_layer_id, p_pool_id, v_manifest, v_scratch,
    1, pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
  );
  EXECUTE pg_catalog.format('CREATE SCHEMA %I AUTHORIZATION v15_owner', v_scratch);
  INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
  VALUES (p_invoke_id, 0, 'pending', 0, '');
  PERFORM v15.v15_loop_store_inputs(p_invoke_id, p_inputs);
  PERFORM v15.v15_loop_install_hooks(
    p_invoke_id,
    p_config_scope_id,
    p_local_layer_id,
    (v_ceilings ->> 'max_iterations')::integer,
    v_max_depth,
    (v_ceilings ->> 'max_io_attempts')::integer,
    (v_ceilings ->> 'max_statement_ms')::integer
  );
  v_depth := 1;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'invoke', 'enter', NULL,
    pg_catalog.jsonb_build_object(
      'depth', v_depth,
      'config_digest', v_config_digest,
      'manifest_digest', v_manifest
    ),
    1
  );
  IF v_depth > v_max_depth THEN
    PERFORM v15.v15_loop_close_open(
      p_invoke_id, 'V15_RECURSION_EXCEEDED', false, ''
    );
    RETURN p_invoke_id;
  END IF;
  v_ret := v15.v15_on_phase(
    p_invoke_id, 0, 'invoke', 'enter',
    pg_catalog.jsonb_build_object('depth', v_depth)
  );
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    v_fatal := coalesce((v_ret->>'fatal')::boolean, false);
    v_code := v_ret->>'code';
    PERFORM v15.v15_loop_close_open(p_invoke_id, v_code, v_fatal, '');
    RETURN p_invoke_id;
  END IF;
  INSERT INTO v15.llm_messages (
    invoke_id, msg_seq, message_id, iteration, role, kind, content
  ) VALUES (
    p_invoke_id, 0, 'seed:system', NULL, 'system', 'seed', p_system
  );
  v_inputs := v15.v15_loop_compose_inputs(p_invoke_id);
  IF v_inputs IS NOT NULL THEN
    INSERT INTO v15.llm_messages (
      invoke_id, msg_seq, message_id, iteration, role, kind, content
    ) VALUES (
      p_invoke_id, 1, 'seed:inputs', NULL, 'user', 'seed', v_inputs
    );
  END IF;
  IF v_ret ? 'messages'
     AND pg_catalog.jsonb_typeof(v_ret -> 'messages') = 'array' THEN
    FOR v_i IN 0 .. pg_catalog.jsonb_array_length(v_ret -> 'messages') - 1 LOOP
      v_msg := v_ret -> 'messages' -> v_i;
      SELECT coalesce(max(m.msg_seq), -1) + 1 INTO v_seq
      FROM v15.llm_messages m
      WHERE m.invoke_id = p_invoke_id;
      INSERT INTO v15.llm_messages (
        invoke_id, msg_seq, message_id, iteration, role, kind, content
      ) VALUES (
        p_invoke_id,
        v_seq,
        v_msg ->> 'id',
        NULL,
        v_msg ->> 'role',
        'persistent_hook',
        v_msg ->> 'content'
      );
    END LOOP;
  END IF;
  UPDATE v15.invokes i
  SET status = 'runnable',
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id;
  RETURN p_invoke_id;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_loop_snapshot(p_invoke_id uuid) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_it v15.iterations;
  v_attempt jsonb;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  SELECT * INTO v_inv FROM v15.invokes i WHERE i.invoke_id = p_invoke_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO v_it
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
  ORDER BY i.iteration DESC
  LIMIT 1;
  SELECT pg_catalog.jsonb_build_object(
    'attempt_id', a.attempt_id,
    'n', a.n,
    'status', a.status,
    'call_started', a.call_started,
    'fence', a.fence,
    'logical_digest', r.logical_digest,
    'request', a.request
  )
    INTO v_attempt
  FROM v15.llm_attempts a
  JOIN v15.llm_requests r ON r.request_id = a.request_id
  WHERE r.invoke_id = p_invoke_id
    AND r.iteration = v_it.iteration
    AND a.status = 'leased';
  RETURN pg_catalog.jsonb_build_object(
    'invoke_id', v_inv.invoke_id,
    'status', v_inv.status,
    'fence', v_inv.fence,
    'lease_owner', v_inv.lease_owner,
    'depth', v_inv.depth,
    'recursion_available', v_inv.recursion_available,
    'parent_invoke_id', v_inv.parent_invoke_id,
    'resolved_config', v_inv.resolved_config,
    'scratch_schema', v_inv.scratch_schema,
    'iteration', v_it.iteration,
    'iter_status', v_it.status,
    'resume_stmt', v_it.resume_stmt,
    'capture', v_it.capture,
    'repl_exec_open', v15.v15_span_open(p_invoke_id, 'repl_exec'),
    'llm_query_open', v15.v15_span_open(p_invoke_id, 'llm_query'),
    'attempt', coalesce(v_attempt, 'null'::jsonb),
    'statements', coalesce((
      SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'stmt_index', s.stmt_index,
        'kind', s.kind,
        'status', s.status,
        'error', coalesce(s.error, 'null'::jsonb),
        'sql', s.sql
      ) ORDER BY s.stmt_index)
      FROM v15.statements s
      WHERE s.invoke_id = p_invoke_id
        AND s.iteration = v_it.iteration
    ), '[]'::jsonb),
    'messages', coalesce((
      SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'msg_seq', m.msg_seq,
        'message_id', m.message_id,
        'role', m.role,
        'kind', m.kind,
        'content', m.content
      ) ORDER BY m.msg_seq)
      FROM v15.llm_messages m
      WHERE m.invoke_id = p_invoke_id
    ), '[]'::jsonb),
    'bindings', coalesce((
      SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'name', b.name,
        'kind', b.kind,
        'show_in_prompt', b.show_in_prompt,
        'description', t.description
      ) ORDER BY b.name)
      FROM v15.bindings b
      LEFT JOIN v15.tool_catalog t ON t.tool_id = b.tool_id
      WHERE b.invoke_id = p_invoke_id
    ), '[]'::jsonb)
  );
END;
$fn$;

CREATE FUNCTION v15.v15_loop_invoke_complete(
  p_invoke_id uuid,
  p_iteration integer,
  p_outcome text,
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
  v_io := pg_catalog.jsonb_build_object('outcome', p_outcome);
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'invoke', 'complete', NULL, v_io, p_fence
  );
  v_ret := v15.v15_on_phase(p_invoke_id, p_iteration, 'invoke', 'complete', v_io);
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_loop_accept_forcing(
  p_invoke_id uuid,
  p_iteration integer,
  p_stmt integer,
  p_messages jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_i integer;
  v_id text;
  v_parts text[];
  v_hook text;
  v_ord integer;
  v_n bigint;
  v_cur bigint;
  v_key text;
  v_seen jsonb := '{}'::jsonb;
  v_bumped boolean := false;
BEGIN
  IF p_messages IS NULL OR pg_catalog.jsonb_typeof(p_messages) <> 'array' THEN
    RETURN;
  END IF;
  FOR v_i IN 0 .. pg_catalog.jsonb_array_length(p_messages) - 1 LOOP
    v_id := p_messages -> v_i ->> 'id';
    IF v_id IS NULL THEN
      CONTINUE;
    END IF;
    v_parts := pg_catalog.regexp_match(
      v_id, '^([a-z][a-z0-9_]{0,53}):([0-9]+):([0-9]+)$'
    );
    IF v_parts IS NULL THEN
      CONTINUE;
    END IF;
    v_hook := v_parts[1];
    IF v_hook <> ALL (ARRAY['budget_forcing', 'return_type', 'validate_return']::text[])
       AND NOT pg_catalog.starts_with(v_hook, 'validate_return_') THEN
      CONTINUE;
    END IF;
    IF v_seen ? v_id THEN
      CONTINUE;
    END IF;
    BEGIN
      v_ord := v_parts[2]::integer;
      v_n := v_parts[3]::bigint;
    EXCEPTION
      WHEN numeric_value_out_of_range THEN
        CONTINUE;
    END;
    IF NOT EXISTS (
      SELECT 1
      FROM v15.invoke_hooks h
      JOIN v15.hook_defs d ON d.hook_def_id = h.hook_def_id
      WHERE h.invoke_id = p_invoke_id
        AND h.ordinal = v_ord
        AND d.hook_key = v_hook
    ) THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    v_seen := v_seen || pg_catalog.jsonb_build_object(v_id, true);
    v_key := v_hook || ':' || v_ord::text;
    SELECT c.n INTO v_cur
    FROM v15.hook_counters c
    WHERE c.invoke_id = p_invoke_id
      AND c.counter_key = v_key;
    IF FOUND AND v_cur >= 9223372036854775807 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    INSERT INTO v15.hook_counters (invoke_id, counter_key, n)
    VALUES (p_invoke_id, v_key, 1)
    ON CONFLICT (invoke_id, counter_key) DO UPDATE
      SET n = v15.hook_counters.n + 1,
          revision = v15.hook_counters.revision + 1;
    v_bumped := true;
  END LOOP;
  IF v_bumped THEN
    UPDATE v15.statements s
    SET revision = s.revision + 1
    WHERE s.invoke_id = p_invoke_id
      AND s.iteration = p_iteration
      AND s.stmt_index = p_stmt;
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_finish_exec(
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
  v_it v15.iterations;
  v_cut integer;
  v_ret_at integer;
  v_raise_at integer;
  v_failed integer;
  v_failed_at integer;
  v_pending integer;
  v_running integer;
  v_skipped integer;
  v_done_before integer;
  v_kind text;
  v_capture text;
  v_io jsonb;
  v_ret jsonb;
  v_err jsonb;
  v_output text;
  v_block text;
  v_parent uuid;
  v_stmt integer;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200
     OR p_fence IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  SELECT * INTO v_it
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing';
  IF NOT FOUND OR NOT v15.v15_span_open(p_invoke_id, 'repl_exec') THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT min(s.stmt_index) INTO v_ret_at
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_it.iteration
    AND s.kind = 'return'
    AND s.status = 'done';
  SELECT min(s.stmt_index) INTO v_raise_at
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_it.iteration
    AND s.kind = 'raise'
    AND s.status = 'done';
  IF v_ret_at IS NOT NULL OR v_raise_at IS NOT NULL THEN
    v_cut := least(
      coalesce(v_ret_at, 2147483647),
      coalesce(v_raise_at, 2147483647)
    );
  ELSE
    v_cut := v_it.resume_stmt;
  END IF;
  PERFORM v15.v15_repl_skip_after(p_invoke_id, v_it.iteration, v_cut);
  SELECT
    count(*) FILTER (WHERE s.status = 'failed'),
    min(s.stmt_index) FILTER (WHERE s.status = 'failed'),
    count(*) FILTER (WHERE s.status = 'pending' AND s.error IS NULL),
    count(*) FILTER (WHERE s.status = 'running'),
    count(*) FILTER (WHERE s.status = 'skipped')
    INTO v_failed, v_failed_at, v_pending, v_running, v_skipped
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_it.iteration;
  SELECT count(*) INTO v_done_before
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_it.iteration
    AND s.status = 'done'
    AND s.stmt_index < coalesce(v_failed_at, 2147483647);
  IF v_ret_at IS NOT NULL
     AND v_raise_at IS NULL
     AND v_failed = 0
     AND v_pending = 0
     AND v_running = 0
     AND v_inv.return_value IS NOT NULL THEN
    v_kind := 'return';
  ELSIF v_raise_at IS NOT NULL
        AND v_ret_at IS NULL
        AND v_failed = 0
        AND v_pending = 0
        AND v_running = 0
        AND v_inv.error IS NOT NULL THEN
    v_kind := 'raise';
  ELSIF v_ret_at IS NULL
        AND v_raise_at IS NULL
        AND v_running = 0
        AND v_pending = 0
        AND (
          v_failed = 0 AND v_skipped = 0
          OR (
            v_failed = 1
            AND v_done_before = v_failed_at
            AND NOT EXISTS (
              SELECT 1
              FROM v15.statements s
              WHERE s.invoke_id = p_invoke_id
                AND s.iteration = v_it.iteration
                AND s.stmt_index > v_failed_at
                AND s.status IS DISTINCT FROM 'skipped'
            )
          )
        ) THEN
    v_kind := 'continue';
  ELSE
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_capture := v_it.capture;
  v_io := pg_catalog.jsonb_build_object(
    'result_kind', v_kind,
    'return_value', v_inv.return_value,
    'error', CASE WHEN v_kind = 'raise' THEN v_inv.error ELSE NULL END,
    'capture', v_capture
  );
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'span', 'repl_exec', 'complete', NULL, v_io, v_inv.fence
  );
  v_ret := v15.v15_on_phase(
    p_invoke_id, v_it.iteration, 'repl_exec', 'complete', v_io
  );
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    PERFORM v15.v15_repl_abort_exec(
      p_invoke_id,
      v_ret->>'code',
      coalesce((v_ret->>'fatal')::boolean, false),
      ''
    );
    RETURN;
  END IF;
  IF v_ret ? 'exec_result'
     AND pg_catalog.jsonb_typeof(v_ret -> 'exec_result') = 'object' THEN
    IF v_kind = 'return'
       AND v_ret -> 'exec_result' ->> 'result_kind' = 'continue'
       AND v_ret -> 'exec_result' -> 'return_value' = 'null'::jsonb
       AND v_ret -> 'exec_result' -> 'error' = 'null'::jsonb
       AND v_capture = '' THEN
      UPDATE v15.invokes i
      SET return_value = NULL,
          revision = i.revision + 1,
          updated_at = pg_catalog.clock_timestamp()
      WHERE i.invoke_id = p_invoke_id;
      v_stmt := v_ret_at;
      PERFORM v15.v15_loop_accept_forcing(
        p_invoke_id, v_it.iteration, v_stmt, v_ret -> 'messages'
      );
      v_kind := 'continue';
      v_inv.return_value := NULL;
    ELSIF v_kind = 'return'
          AND v_ret -> 'exec_result' ->> 'result_kind' = 'raise'
          AND v_ret -> 'exec_result' -> 'return_value' = 'null'::jsonb
          AND v_capture = ''
          AND v_ret #>> '{exec_result,error,code}' = 'V15_VALIDATION_FAILED' THEN
      v_err := v15.v15_loop_error(
        v_ret #>> '{exec_result,error,code}',
        v_ret #>> '{exec_result,error,message}'
      );
      UPDATE v15.invokes i
      SET return_value = NULL,
          error = v_err,
          revision = i.revision + 1,
          updated_at = pg_catalog.clock_timestamp()
      WHERE i.invoke_id = p_invoke_id;
      v_inv.return_value := NULL;
      v_inv.error := v_err;
      v_kind := 'raise';
    ELSE
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
  END IF;
  IF v_kind = 'return' THEN
    UPDATE v15.iterations i
    SET status = 'done',
        result_kind = 'return',
        revision = i.revision + 1
    WHERE i.invoke_id = p_invoke_id
      AND i.iteration = v_it.iteration;
    INSERT INTO v15.repl_history (
      invoke_id, iteration, llm_response, repl_output, repl_exception
    ) VALUES (
      p_invoke_id,
      v_it.iteration,
      v15.v15_loop_assistant(p_invoke_id, v_it.iteration),
      '',
      NULL
    );
    UPDATE v15.invokes i
    SET status = 'completed',
        fatal = false,
        error = NULL,
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = p_invoke_id
    RETURNING i.parent_invoke_id, i.scratch_schema, i.fence
      INTO v_parent, v_inv.scratch_schema, v_inv.fence;
    PERFORM v15.v15_repl_close_span(
      p_invoke_id, v_it.iteration, 'repl_exec', 'completed', v_inv.fence
    );
    PERFORM v15.v15_loop_invoke_complete(
      p_invoke_id, v_it.iteration, 'completed', v_inv.fence
    );
    PERFORM v15.v15_repl_close_span(
      p_invoke_id, v_it.iteration, 'invoke', 'completed', v_inv.fence
    );
    PERFORM v15.v15_loop_drop_scratch(v_inv.scratch_schema);
    IF v_parent IS NOT NULL THEN
      PERFORM v15.v15_io_deliver_child(p_invoke_id);
    END IF;
    RETURN;
  END IF;
  IF v_kind = 'raise' THEN
    UPDATE v15.iterations i
    SET status = 'done',
        result_kind = 'raise',
        revision = i.revision + 1
    WHERE i.invoke_id = p_invoke_id
      AND i.iteration = v_it.iteration;
    INSERT INTO v15.repl_history (
      invoke_id, iteration, llm_response, repl_output, repl_exception
    ) VALUES (
      p_invoke_id,
      v_it.iteration,
      v15.v15_loop_assistant(p_invoke_id, v_it.iteration),
      '',
      v_inv.error
    );
    UPDATE v15.invokes i
    SET status = 'failed',
        fatal = false,
        lease_owner = NULL,
        lease_until = NULL,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = p_invoke_id
    RETURNING i.parent_invoke_id, i.scratch_schema, i.fence
      INTO v_parent, v_inv.scratch_schema, v_inv.fence;
    PERFORM v15.v15_repl_close_span(
      p_invoke_id, v_it.iteration, 'repl_exec', 'failed', v_inv.fence
    );
    PERFORM v15.v15_repl_close_span(
      p_invoke_id, v_it.iteration, 'invoke', 'failed', v_inv.fence
    );
    PERFORM v15.v15_loop_drop_scratch(v_inv.scratch_schema);
    IF v_parent IS NOT NULL THEN
      PERFORM v15.v15_io_deliver_child(p_invoke_id);
    END IF;
    RETURN;
  END IF;
  SELECT s.error INTO v_err
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_it.iteration
    AND s.status = 'failed'
  ORDER BY s.stmt_index
  LIMIT 1;
  IF v_err IS NULL THEN
    v_output := v_capture;
  ELSE
    v_block := '[v15 exception ' || (v_err ->> 'code') || ']'
      || E'\n' || coalesce(v_err ->> 'message', '');
    IF v_capture = '' THEN
      v_output := v_block;
    ELSE
      v_output := v_capture || E'\n' || v_block;
    END IF;
  END IF;
  UPDATE v15.iterations i
  SET status = 'done',
      result_kind = 'continue',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.iteration = v_it.iteration;
  INSERT INTO v15.repl_history (
    invoke_id, iteration, llm_response, repl_output, repl_exception
  ) VALUES (
    p_invoke_id,
    v_it.iteration,
    v15.v15_loop_assistant(p_invoke_id, v_it.iteration),
    v_output,
    v_err
  );
  INSERT INTO v15.llm_messages (
    invoke_id, msg_seq, message_id, iteration, role, kind, content
  )
  SELECT p_invoke_id,
         coalesce((
           SELECT max(m.msg_seq)
           FROM v15.llm_messages m
           WHERE m.invoke_id = p_invoke_id
         ), -1) + 1,
         'iter:' || v_it.iteration::text || ':observation',
         v_it.iteration,
         'user',
         'observation',
         v_output;
  INSERT INTO v15.iterations (
    invoke_id, iteration, status, resume_stmt, capture
  ) VALUES (
    p_invoke_id, v_it.iteration + 1, 'pending', 0, ''
  );
  UPDATE v15.invokes i
  SET status = 'runnable',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id
  RETURNING i.fence INTO v_inv.fence;
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, v_it.iteration, 'repl_exec', 'completed', v_inv.fence
  );
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'continue',
      'next_iteration', v_it.iteration + 1
    ),
    v_inv.fence
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

ALTER FUNCTION v15.v15_loop_sqlstate(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_error(text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_drop_scratch(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_assistant(uuid, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_compose_inputs(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_install_hook(uuid, integer, text, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_install_hooks(uuid, uuid, uuid, integer, integer, integer, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_close_open(uuid, text, boolean, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_validate_inputs(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_store_inputs(uuid, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_open_invoke(uuid, uuid, uuid, jsonb, uuid, jsonb, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_snapshot(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_invoke_complete(uuid, integer, text, bigint) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_loop_accept_forcing(uuid, integer, integer, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_finish_exec(uuid, bigint, text) OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_loop_sqlstate(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_error(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_drop_scratch(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_assistant(uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_compose_inputs(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_install_hook(uuid, integer, text, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_install_hooks(uuid, uuid, uuid, integer, integer, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_close_open(uuid, text, boolean, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_validate_inputs(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_store_inputs(uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_open_invoke(uuid, uuid, uuid, jsonb, uuid, jsonb, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_snapshot(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_invoke_complete(uuid, integer, text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_loop_accept_forcing(uuid, integer, integer, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_finish_exec(uuid, bigint, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_open_invoke(uuid, uuid, uuid, jsonb, uuid, jsonb, text, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_loop_snapshot(uuid) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_finish_exec(uuid, bigint, text) TO v15_worker;
