CREATE FUNCTION v15.v15_tree_bind_context(
  p_invoke_id uuid,
  p_stmt_index integer
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_arg text;
  v_depth integer;
  v_max integer;
  v_manifest integer;
  v_bindings jsonb;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_stmt_index IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT s.arg_sql
    INTO v_arg
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.stmt_index = p_stmt_index
    AND s.kind = 'bind_invoke';
  SELECT i.depth
    INTO v_depth
  FROM v15.invokes i
  WHERE i.invoke_id = p_invoke_id;
  IF v_depth IS NULL THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_max := v15.v15_baseline_max(p_invoke_id, 'governance_depth');
  SELECT g.max_depth
    INTO v_manifest
  FROM v15.governance_manifest g
  WHERE g.manifest_id = 1;
  SELECT coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'name', b.name,
        'kind', b.kind,
        'show_in_prompt', b.show_in_prompt,
        'description', t.description
      )
      ORDER BY b.name
    ),
    '[]'::jsonb
  )
    INTO v_bindings
  FROM v15.bindings b
  LEFT JOIN v15.tool_catalog t ON t.tool_id = b.tool_id
  WHERE b.invoke_id = p_invoke_id
    AND (
      b.kind = 'scope'
      OR (b.kind = 'tool' AND b.provenance = 'scope')
    );
  RETURN pg_catalog.jsonb_build_object(
    'arg_sql', v_arg,
    'depth', v_depth,
    'max_depth', v_max,
    'manifest_max_depth', v_manifest,
    'bindings', v_bindings
  );
END;
$fn$;

CREATE FUNCTION v15.v15_tree_parent_ceilings(p_invoke_id uuid) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  RETURN pg_catalog.jsonb_build_object(
    'max_iterations', v15.v15_baseline_max(p_invoke_id, 'governance_iterations'),
    'max_depth', v15.v15_baseline_max(p_invoke_id, 'governance_depth'),
    'max_io_attempts', v15.v15_baseline_max(p_invoke_id, 'governance_io'),
    'max_statement_ms', v15.v15_baseline_max(p_invoke_id, 'governance_statement')
  );
END;
$fn$;

CREATE FUNCTION v15.v15_tree_store_child_bindings(
  p_parent uuid,
  p_child uuid,
  p_inputs jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_name text;
BEGIN
  IF p_inputs IS NULL OR pg_catalog.jsonb_typeof(p_inputs) <> 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  FOR v_name IN
    SELECT k.key
    FROM pg_catalog.jsonb_object_keys(p_inputs) AS k(key)
  LOOP
    PERFORM v15.v15_check_binding_name(v_name);
    IF p_inputs -> v_name IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.jsonb_object_keys(p_inputs) AS k(key)
    JOIN v15.bindings b
      ON b.invoke_id = p_parent
     AND b.name = k.key
     AND (
       b.kind = 'scope'
       OR (b.kind = 'tool' AND b.provenance = 'scope')
     )
  ) THEN
    RAISE EXCEPTION 'V15_SCOPE_CONFLICT' USING ERRCODE = 'P1509';
  END IF;
  FOR v_name IN
    SELECT k.key
    FROM pg_catalog.jsonb_object_keys(p_inputs) AS k(key)
  LOOP
    INSERT INTO v15.bindings (
      invoke_id, name, kind, value, show_in_prompt, provenance
    ) VALUES (
      p_child, v_name, 'input', p_inputs -> v_name, true, 'explicit'
    );
  END LOOP;
  INSERT INTO v15.bindings (
    invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
  )
  SELECT p_child, b.name, b.kind, b.value, b.tool_id, b.show_in_prompt, b.provenance
  FROM v15.bindings b
  WHERE b.invoke_id = p_parent
    AND b.kind = 'scope';
  INSERT INTO v15.bindings (
    invoke_id, name, kind, value, tool_id, show_in_prompt, provenance
  )
  SELECT p_child, b.name, b.kind, b.value, b.tool_id, b.show_in_prompt, b.provenance
  FROM v15.bindings b
  WHERE b.invoke_id = p_parent
    AND b.kind = 'tool'
    AND b.provenance = 'scope';
  INSERT INTO v15.tool_grants (invoke_id, tool_id)
  SELECT p_child, b.tool_id
  FROM v15.bindings b
  WHERE b.invoke_id = p_parent
    AND b.kind = 'tool'
    AND b.provenance = 'scope';
END;
$fn$;

CREATE FUNCTION v15.v15_tree_install_child_hooks(
  p_parent uuid,
  p_child uuid,
  p_scope_id uuid,
  p_ceilings jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ord integer := 4;
  v_hooks jsonb;
  v_i integer;
  v_key text;
  v_hook record;
BEGIN
  PERFORM v15.v15_loop_install_hook(
    p_child, 0, 'governance_iterations', 'baseline',
    pg_catalog.jsonb_build_object('max', (p_ceilings ->> 'max_iterations')::integer)
  );
  PERFORM v15.v15_loop_install_hook(
    p_child, 1, 'governance_depth', 'baseline',
    pg_catalog.jsonb_build_object('max', (p_ceilings ->> 'max_depth')::integer)
  );
  PERFORM v15.v15_loop_install_hook(
    p_child, 2, 'governance_io', 'baseline',
    pg_catalog.jsonb_build_object('max', (p_ceilings ->> 'max_io_attempts')::integer)
  );
  PERFORM v15.v15_loop_install_hook(
    p_child, 3, 'governance_statement', 'baseline',
    pg_catalog.jsonb_build_object('max', (p_ceilings ->> 'max_statement_ms')::integer)
  );
  SELECT p.baseline_hooks
    INTO v_hooks
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
      WHERE h.invoke_id = p_child
        AND d.hook_key = v_key
    ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    PERFORM v15.v15_loop_install_hook(
      p_child, v_ord, v_key, 'baseline', '{}'::jsonb
    );
    v_ord := v_ord + 1;
  END LOOP;
  FOR v_hook IN
    SELECT h.hook_def_id, h.channel, h.config
    FROM v15.invoke_hooks h
    WHERE h.invoke_id = p_parent
      AND h.channel = 'propagating'
    ORDER BY h.ordinal
  LOOP
    INSERT INTO v15.invoke_hooks (
      invoke_id, ordinal, hook_def_id, channel, config, state
    ) VALUES (
      p_child, v_ord, v_hook.hook_def_id, v_hook.channel, v_hook.config, '{}'::jsonb
    );
    v_ord := v_ord + 1;
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_tree_finish_open(
  p_child uuid,
  p_depth integer,
  p_max_depth integer,
  p_config_digest text,
  p_manifest text,
  p_system text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ret jsonb;
  v_inputs text;
  v_seq bigint;
  v_i integer;
  v_msg jsonb;
  v_fatal boolean;
  v_code text;
BEGIN
  PERFORM v15.v15_repl_event(
    p_child, 'span', 'invoke', 'enter', NULL,
    pg_catalog.jsonb_build_object(
      'depth', p_depth,
      'config_digest', p_config_digest,
      'manifest_digest', p_manifest
    ),
    1
  );
  IF p_depth > p_max_depth THEN
    PERFORM v15.v15_loop_close_open(
      p_child, 'V15_RECURSION_EXCEEDED', false, ''
    );
    PERFORM v15.v15_io_deliver_child(p_child);
    RETURN;
  END IF;
  v_ret := v15.v15_on_phase(
    p_child, 0, 'invoke', 'enter',
    pg_catalog.jsonb_build_object('depth', p_depth)
  );
  PERFORM v15.v15_repl_assert_phase(v_ret);
  IF v_ret->>'action' = 'abort' THEN
    v_fatal := coalesce((v_ret->>'fatal')::boolean, false);
    v_code := v_ret->>'code';
    IF v_fatal THEN
      PERFORM v15.v15_repl_fatal_expand(p_child, v_code, '');
    ELSE
      PERFORM v15.v15_loop_close_open(p_child, v_code, false, '');
      PERFORM v15.v15_io_deliver_child(p_child);
    END IF;
    RETURN;
  END IF;
  INSERT INTO v15.llm_messages (
    invoke_id, msg_seq, message_id, iteration, role, kind, content
  ) VALUES (
    p_child, 0, 'seed:system', NULL, 'system', 'seed', p_system
  );
  v_inputs := v15.v15_loop_compose_inputs(p_child);
  IF v_inputs IS NOT NULL THEN
    INSERT INTO v15.llm_messages (
      invoke_id, msg_seq, message_id, iteration, role, kind, content
    ) VALUES (
      p_child, 1, 'seed:inputs', NULL, 'user', 'seed', v_inputs
    );
  END IF;
  IF v_ret ? 'messages'
     AND pg_catalog.jsonb_typeof(v_ret -> 'messages') = 'array' THEN
    FOR v_i IN 0 .. pg_catalog.jsonb_array_length(v_ret -> 'messages') - 1 LOOP
      v_msg := v_ret -> 'messages' -> v_i;
      SELECT coalesce(max(m.msg_seq), -1) + 1
        INTO v_seq
      FROM v15.llm_messages m
      WHERE m.invoke_id = p_child;
      INSERT INTO v15.llm_messages (
        invoke_id, msg_seq, message_id, iteration, role, kind, content
      ) VALUES (
        p_child,
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
  WHERE i.invoke_id = p_child;
END;
$fn$;

CREATE FUNCTION v15.v15_suspend_for_child(
  p_invoke_id uuid,
  p_fence bigint,
  p_owner text,
  p_stmt_index integer,
  p_statement_fence bigint,
  p_child_inputs jsonb,
  p_child_system text,
  p_child_user text
) RETURNS uuid
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
  v_bind text;
  v_arg text;
  v_ctx v15.exec_context;
  v_scratch text;
  v_child uuid;
  v_depth integer;
  v_ceilings jsonb;
  v_manifest text;
  v_resolved jsonb;
  v_config_digest text;
  v_max_depth integer;
  v_fence bigint;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR p_stmt_index IS NULL OR p_statement_fence IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, p_fence, p_owner);
  SELECT count(*)
    INTO v_n
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing';
  IF v_n <> 1 OR NOT v15.v15_span_open(p_invoke_id, 'repl_exec') THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT i.iteration, i.resume_stmt
    INTO v_iter, v_resume
  FROM v15.iterations i
  WHERE i.invoke_id = p_invoke_id
    AND i.status = 'executing'
  FOR UPDATE;
  IF p_stmt_index IS DISTINCT FROM v_resume THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.kind, s.bind_name, s.arg_sql
    INTO v_kind, v_bind, v_arg
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.status = 'running'
    AND s.error IS NULL
  FOR UPDATE;
  IF NOT FOUND OR v_kind IS DISTINCT FROM 'bind_invoke' THEN
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
  IF NOT v_inv.recursion_available THEN
    RAISE EXCEPTION 'V15_RECURSION_DISABLED' USING ERRCODE = 'P1518';
  END IF;
  IF v_arg IS NULL OR v_arg = '' OR v_bind IS NULL OR v_bind = '' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_child_system IS NULL OR p_child_system = '' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_scratch := v_inv.scratch_schema;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.pg_stat_xact_user_tables s
    JOIN pg_catalog.pg_class c ON c.oid = s.relid
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = v_scratch
      AND (s.n_tup_ins > 0 OR s.n_tup_upd > 0 OR s.n_tup_del > 0)
  ) THEN
    RAISE EXCEPTION 'V15_INVOKE_FORM' USING ERRCODE = 'P1503';
  END IF;
  IF p_child_inputs IS NULL OR pg_catalog.jsonb_typeof(p_child_inputs) <> 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT c.ceilings, c.manifest_digest
    INTO v_ceilings, v_manifest
  FROM v15.v15_effective_ceilings(
    NULL, v15.v15_tree_parent_ceilings(p_invoke_id)
  ) AS c;
  v_depth := v_inv.depth + 1;
  v_max_depth := (v_ceilings ->> 'max_depth')::integer;
  SELECT r.resolved_config, r.config_digest
    INTO v_resolved, v_config_digest
  FROM v15.v15_resolve_child_config(v_inv.config_scope_id, NULL, v_depth) AS r;
  v_child := pg_catalog.gen_random_uuid();
  INSERT INTO v15.invokes (
    invoke_id, parent_invoke_id, parent_iteration, root_invoke_id, depth,
    status, fatal, recursion_available, resolved_config, config_digest,
    config_scope_id, local_layer_id, pool_id, manifest_digest, scratch_schema,
    fence, created_at, updated_at
  ) VALUES (
    v_child, p_invoke_id, v_iter, v_inv.root_invoke_id, v_depth,
    'pending', false, (v_depth < v_max_depth), v_resolved, v_config_digest,
    v_inv.config_scope_id, NULL, v_inv.pool_id, v_manifest,
    's_' || replace(v_child::text, '-', ''),
    1, pg_catalog.clock_timestamp(), pg_catalog.clock_timestamp()
  );
  EXECUTE pg_catalog.format(
    'CREATE SCHEMA %I AUTHORIZATION v15_owner',
    's_' || replace(v_child::text, '-', '')
  );
  INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
  VALUES (v_child, 0, 'pending', 0, '');
  PERFORM v15.v15_tree_store_child_bindings(p_invoke_id, v_child, p_child_inputs);
  PERFORM v15.v15_tree_install_child_hooks(
    p_invoke_id, v_child, v_inv.config_scope_id, v_ceilings
  );
  UPDATE v15.statements s
  SET child_invoke_id = v_child,
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.status = 'running';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  UPDATE v15.iterations i
  SET status = 'suspended',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.iteration = v_iter;
  UPDATE v15.invokes i
  SET status = 'suspended',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id
  RETURNING i.fence INTO v_fence;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'suspend',
      'child_invoke_id', v_child,
      'bind_name', v_bind,
      'stmt_index', p_stmt_index
    ),
    v_fence
  );
  PERFORM v15.v15_repl_revoke_scratch(v_scratch);
  PERFORM 1
  FROM v15.invokes i
  WHERE i.invoke_id = v_child
  FOR UPDATE;
  PERFORM v15.v15_tree_finish_open(
    v_child, v_depth, v_max_depth, v_config_digest, v_manifest, p_child_system
  );
  RETURN v_child;
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

ALTER FUNCTION v15.v15_tree_bind_context(uuid, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_tree_parent_ceilings(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_tree_store_child_bindings(uuid, uuid, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_tree_install_child_hooks(uuid, uuid, uuid, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_tree_finish_open(uuid, integer, integer, text, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_suspend_for_child(uuid, bigint, text, integer, bigint, jsonb, text, text) OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_tree_bind_context(uuid, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_tree_parent_ceilings(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_tree_store_child_bindings(uuid, uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_tree_install_child_hooks(uuid, uuid, uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_tree_finish_open(uuid, integer, integer, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_suspend_for_child(uuid, bigint, text, integer, bigint, jsonb, text, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_tree_bind_context(uuid, integer) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_suspend_for_child(uuid, bigint, text, integer, bigint, jsonb, text, text) TO v15_worker;
