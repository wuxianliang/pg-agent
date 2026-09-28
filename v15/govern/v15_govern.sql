CREATE FUNCTION v15.v15_govern_known_code(p_code text) RETURNS boolean
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
    'V15_HOOK_ABORT'
  )
$fn$;

CREATE FUNCTION v15.v15_govern_has_reserved(p_value jsonb) RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE
    WHEN p_value IS NULL OR pg_catalog.jsonb_typeof(p_value) NOT IN ('object', 'array') THEN false
    WHEN pg_catalog.jsonb_typeof(p_value) = 'array' THEN EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_array_elements(p_value) AS e(value)
      WHERE v15.v15_govern_has_reserved(e.value)
    )
    ELSE EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_object_keys(p_value) AS k(key)
      WHERE k.key IN (
        'supply_llm_response',
        'supply_invoke_result',
        'modify_invoke_result',
        'supply_exec_result',
        'modify_llm_response'
      )
    ) OR EXISTS (
      SELECT 1
      FROM pg_catalog.jsonb_each(p_value) AS e(key, value)
      WHERE v15.v15_govern_has_reserved(e.value)
    )
  END
$fn$;

CREATE FUNCTION v15.v15_govern_allow(p_span text, p_phase text, p_effect text) RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE p_span || '/' || p_phase
    WHEN 'invoke/enter' THEN p_effect IN (
      'abort', 'add_messages', 'disable_recursion', 'add_inputs', 'drop_inputs', 'blackboard_write'
    )
    WHEN 'invoke/complete' THEN p_effect = 'blackboard_write'
    WHEN 'invoke/exit' THEN p_effect = 'blackboard_write'
    WHEN 'llm_query/enter' THEN p_effect IN (
      'abort', 'add_messages', 'drop_messages', 'disable_recursion', 'blackboard_write'
    )
    WHEN 'llm_query/send' THEN p_effect IN (
      'abort', 'add_messages', 'drop_messages', 'blackboard_write', 'budget'
    )
    WHEN 'llm_query/complete' THEN p_effect IN (
      'abort', 'add_messages', 'drop_messages', 'blackboard_write'
    )
    WHEN 'llm_query/exit' THEN p_effect = 'blackboard_write'
    WHEN 'repl_exec/enter' THEN p_effect IN (
      'abort', 'add_messages', 'drop_messages', 'blackboard_write'
    )
    WHEN 'repl_exec/send' THEN p_effect IN ('abort', 'blackboard_write')
    WHEN 'repl_exec/complete' THEN p_effect IN (
      'abort', 'modify_exec_result', 'add_messages', 'drop_messages', 'blackboard_write'
    )
    WHEN 'repl_exec/exit' THEN p_effect = 'blackboard_write'
    ELSE false
  END
$fn$;

CREATE FUNCTION v15.v15_govern_io_keys(p_span text, p_phase text) RETURNS text[]
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE p_span || '/' || p_phase
    WHEN 'invoke/enter' THEN ARRAY['depth']
    WHEN 'llm_query/enter' THEN ARRAY['iteration', 'next_attempt_n']
    WHEN 'llm_query/send' THEN ARRAY[
      'enter_messages', 'enter_overlay', 'input_chars', 'iteration', 'logical_digest'
    ]
    WHEN 'llm_query/complete' THEN ARRAY['attempt_id']
    WHEN 'llm_query/exit' THEN ARRAY['attempt_id']
    WHEN 'repl_exec/enter' THEN ARRAY['iteration', 'resume_stmt']
    WHEN 'repl_exec/send' THEN ARRAY[]::text[]
    WHEN 'repl_exec/complete' THEN ARRAY['capture', 'error', 'result_kind', 'return_value']
    WHEN 'repl_exec/exit' THEN ARRAY['outcome']
    WHEN 'invoke/complete' THEN ARRAY['outcome']
    WHEN 'invoke/exit' THEN ARRAY['outcome']
    ELSE NULL
  END
$fn$;

CREATE FUNCTION v15.v15_govern_json_int(p_value jsonb, p_min integer, p_max integer) RETURNS integer
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE
    WHEN pg_catalog.jsonb_typeof(p_value) = 'number'
         AND (p_value #>> '{}') ~ '^[0-9]+$'
         AND (p_value #>> '{}')::numeric BETWEEN p_min AND p_max
      THEN (p_value #>> '{}')::integer
    ELSE NULL
  END
$fn$;

CREATE FUNCTION v15.v15_govern_recheck(
  p_fn oid,
  p_owner_name text,
  p_digest text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  proc pg_catalog.pg_proc%ROWTYPE;
  owner_name text;
  lang text;
  digest text;
BEGIN
  SELECT * INTO proc FROM pg_catalog.pg_proc WHERE oid = p_fn;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_HANDLER_DIGEST' USING ERRCODE = 'P1536';
  END IF;
  SELECT r.rolname INTO owner_name
  FROM pg_catalog.pg_roles r
  WHERE r.oid = proc.proowner;
  SELECT l.lanname INTO lang
  FROM pg_catalog.pg_language l
  WHERE l.oid = proc.prolang;
  digest := v15.v15_handler_digest(p_fn);
  IF owner_name IS DISTINCT FROM p_owner_name
     OR proc.provolatile IS DISTINCT FROM 's'
     OR NOT proc.prosecdef
     OR lang NOT IN ('sql', 'plpgsql')
     OR proc.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
     OR digest IS DISTINCT FROM p_digest THEN
    RAISE EXCEPTION 'V15_HANDLER_DIGEST' USING ERRCODE = 'P1536';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('v15', 'jaz')
      AND c.relkind IN ('r', 'p')
      AND (
        pg_catalog.has_table_privilege(proc.proowner, c.oid, 'SELECT')
        OR pg_catalog.has_table_privilege(proc.proowner, c.oid, 'INSERT')
        OR pg_catalog.has_table_privilege(proc.proowner, c.oid, 'UPDATE')
        OR pg_catalog.has_table_privilege(proc.proowner, c.oid, 'DELETE')
        OR pg_catalog.has_table_privilege(proc.proowner, c.oid, 'TRUNCATE')
        OR pg_catalog.has_table_privilege(proc.proowner, c.oid, 'REFERENCES')
        OR pg_catalog.has_table_privilege(proc.proowner, c.oid, 'TRIGGER')
      )
  ) THEN
    RAISE EXCEPTION 'V15_HANDLER_DIGEST' USING ERRCODE = 'P1536';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_govern_exact_keys(p_value jsonb, p_keys text[]) RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT pg_catalog.jsonb_typeof(p_value) = 'object'
    AND (
      SELECT coalesce(pg_catalog.array_agg(k.key ORDER BY k.key), '{}'::text[])
      FROM pg_catalog.jsonb_object_keys(p_value) AS k(key)
    ) IS NOT DISTINCT FROM (
      SELECT coalesce(pg_catalog.array_agg(x ORDER BY x), '{}'::text[])
      FROM pg_catalog.unnest(p_keys) AS x
    )
$fn$;

CREATE FUNCTION v15.v15_govern_check_return(
  p_span text,
  p_phase text,
  p_io jsonb,
  p_ret jsonb
) RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_key text;
  v_elem jsonb;
  v_id text;
  v_persistent boolean;
BEGIN
  IF p_ret IS NULL OR pg_catalog.jsonb_typeof(p_ret) <> 'object'
     OR p_ret->'contract' IS DISTINCT FROM '1'::jsonb
     OR pg_catalog.jsonb_typeof(p_ret->'action') <> 'string'
     OR (p_ret->>'action') NOT IN ('proceed', 'abort') THEN
    RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
  END IF;
  IF v15.v15_govern_has_reserved(p_ret) THEN
    RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
  END IF;
  FOR v_key IN SELECT pg_catalog.jsonb_object_keys(p_ret) LOOP
    IF v_key <> ALL (ARRAY[
      'contract', 'action', 'fatal', 'error', 'messages', 'message_drops',
      'exec_result', 'recursion_available', 'input_adds', 'input_drops',
      'blackboard_writes', 'budget'
    ]::text[]) THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  END LOOP;
  IF p_ret->>'action' = 'abort' THEN
    IF NOT v15.v15_govern_allow(p_span, p_phase, 'abort') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    IF pg_catalog.jsonb_typeof(p_ret->'fatal') IS DISTINCT FROM 'boolean'
       OR NOT v15.v15_govern_exact_keys(p_ret->'error', ARRAY['code', 'message'])
       OR pg_catalog.jsonb_typeof(p_ret->'error'->'code') <> 'string'
       OR pg_catalog.jsonb_typeof(p_ret->'error'->'message') <> 'string' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF NOT v15.v15_govern_known_code(p_ret #>> '{error,code}') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
  END IF;
  IF p_ret ? 'recursion_available'
     AND p_ret->'recursion_available' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_ret->'recursion_available') <> 'boolean' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF (p_ret->>'recursion_available')::boolean THEN
      RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
    END IF;
    IF NOT v15.v15_govern_allow(p_span, p_phase, 'disable_recursion') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
  END IF;
  IF p_ret ? 'budget' AND p_ret->'budget' IS DISTINCT FROM 'null'::jsonb THEN
    IF NOT v15.v15_govern_allow(p_span, p_phase, 'budget') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    IF NOT v15.v15_govern_exact_keys(p_ret->'budget', ARRAY['reserve_calls', 'reserve_cost'])
       OR v15.v15_govern_json_int(p_ret->'budget'->'reserve_calls', 1, 2147483647) IS NULL
       OR pg_catalog.jsonb_typeof(p_ret->'budget'->'reserve_cost') <> 'number'
       OR (p_ret #>> '{budget,reserve_cost}')::numeric < 0 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END IF;
  IF p_ret ? 'exec_result' AND p_ret->'exec_result' IS DISTINCT FROM 'null'::jsonb THEN
    IF NOT v15.v15_govern_allow(p_span, p_phase, 'modify_exec_result') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    IF NOT v15.v15_govern_exact_keys(
         p_ret->'exec_result', ARRAY['error', 'result_kind', 'return_value']
       )
       OR p_ret #>> '{exec_result,result_kind}' IS DISTINCT FROM 'continue'
       OR p_ret->'exec_result'->'return_value' IS DISTINCT FROM 'null'::jsonb
       OR p_ret->'exec_result'->'error' IS DISTINCT FROM 'null'::jsonb
       OR p_io->>'result_kind' IS DISTINCT FROM 'return'
       OR p_io->>'capture' IS DISTINCT FROM '' THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
  END IF;
  IF p_ret ? 'messages' AND p_ret->'messages' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_ret->'messages') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF pg_catalog.jsonb_array_length(p_ret->'messages') > 0
       AND NOT v15.v15_govern_allow(p_span, p_phase, 'add_messages') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    FOR v_elem IN SELECT e.value FROM pg_catalog.jsonb_array_elements(p_ret->'messages') AS e(value) LOOP
      IF NOT v15.v15_govern_exact_keys(v_elem, ARRAY['content', 'id', 'persistent', 'role'])
         OR pg_catalog.jsonb_typeof(v_elem->'id') <> 'string'
         OR pg_catalog.jsonb_typeof(v_elem->'role') <> 'string'
         OR pg_catalog.jsonb_typeof(v_elem->'content') <> 'string'
         OR pg_catalog.jsonb_typeof(v_elem->'persistent') <> 'boolean' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      v_id := v_elem->>'id';
      v_persistent := (v_elem->>'persistent')::boolean;
      IF v_id IS NULL
         OR pg_catalog.char_length(v_id) < 1
         OR pg_catalog.char_length(v_id) > 200
         OR v_id IN ('seed:system', 'seed:inputs')
         OR v_id ~ '^iter:[0-9]+:(assistant|observation)$'
         OR (v_elem->>'role') NOT IN ('system', 'user', 'assistant') THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      IF NOT v_persistent AND NOT (p_span = 'llm_query' AND p_phase = 'send') THEN
        RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
      END IF;
      IF p_span = 'invoke' AND p_phase = 'enter' AND NOT v_persistent THEN
        RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
      END IF;
    END LOOP;
  END IF;
  IF p_ret ? 'message_drops' AND p_ret->'message_drops' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_ret->'message_drops') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF pg_catalog.jsonb_array_length(p_ret->'message_drops') > 0
       AND NOT v15.v15_govern_allow(p_span, p_phase, 'drop_messages') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    FOR v_elem IN SELECT e.value FROM pg_catalog.jsonb_array_elements(p_ret->'message_drops') AS e(value) LOOP
      IF NOT v15.v15_govern_exact_keys(v_elem, ARRAY['id'])
         OR pg_catalog.jsonb_typeof(v_elem->'id') <> 'string'
         OR pg_catalog.char_length(v_elem->>'id') < 1 THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
  END IF;
  IF p_ret ? 'input_adds' AND p_ret->'input_adds' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_ret->'input_adds') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF pg_catalog.jsonb_array_length(p_ret->'input_adds') > 0
       AND NOT v15.v15_govern_allow(p_span, p_phase, 'add_inputs') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    FOR v_elem IN SELECT e.value FROM pg_catalog.jsonb_array_elements(p_ret->'input_adds') AS e(value) LOOP
      IF NOT v15.v15_govern_exact_keys(v_elem, ARRAY['name', 'show_in_prompt', 'value'])
         OR pg_catalog.jsonb_typeof(v_elem->'name') <> 'string'
         OR pg_catalog.jsonb_typeof(v_elem->'show_in_prompt') <> 'boolean'
         OR NOT (v_elem ? 'value')
         OR v_elem->'value' IS NULL THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      PERFORM v15.v15_check_binding_name(v_elem->>'name');
    END LOOP;
  END IF;
  IF p_ret ? 'input_drops' AND p_ret->'input_drops' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_ret->'input_drops') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF pg_catalog.jsonb_array_length(p_ret->'input_drops') > 0
       AND NOT v15.v15_govern_allow(p_span, p_phase, 'drop_inputs') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    FOR v_elem IN SELECT e.value FROM pg_catalog.jsonb_array_elements(p_ret->'input_drops') AS e(value) LOOP
      IF NOT v15.v15_govern_exact_keys(v_elem, ARRAY['name'])
         OR pg_catalog.jsonb_typeof(v_elem->'name') <> 'string' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      PERFORM v15.v15_check_binding_name(v_elem->>'name');
    END LOOP;
  END IF;
  IF p_ret ? 'blackboard_writes' AND p_ret->'blackboard_writes' IS DISTINCT FROM 'null'::jsonb THEN
    IF pg_catalog.jsonb_typeof(p_ret->'blackboard_writes') <> 'array' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF pg_catalog.jsonb_array_length(p_ret->'blackboard_writes') > 0
       AND NOT v15.v15_govern_allow(p_span, p_phase, 'blackboard_write') THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    FOR v_elem IN SELECT e.value FROM pg_catalog.jsonb_array_elements(p_ret->'blackboard_writes') AS e(value) LOOP
      IF NOT v15.v15_govern_exact_keys(v_elem, ARRAY['key', 'value'])
         OR pg_catalog.jsonb_typeof(v_elem->'key') <> 'string'
         OR pg_catalog.char_length(v_elem->>'key') < 1
         OR pg_catalog.char_length(v_elem->>'key') > 200
         OR NOT (v_elem ? 'value')
         OR v_elem->'value' IS NULL THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
  END IF;
END;
$fn$;

CREATE FUNCTION v15.invoke_hooks_optional_guard() RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_key text;
  v_required boolean;
  v_max integer;
  v_ceiling integer;
  v_pool uuid;
  v_cfg_key text;
BEGIN
  SELECT d.hook_key, d.baseline_required
    INTO v_key, v_required
  FROM v15.hook_defs d
  WHERE d.hook_def_id = NEW.hook_def_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF v_required THEN
    RETURN NEW;
  END IF;
  IF NEW.channel = 'baseline' OR NEW.channel NOT IN ('propagating', 'local') THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF pg_catalog.jsonb_typeof(NEW.config) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF v_key IN ('iteration_limit', 'recursion_limit') THEN
    FOR v_cfg_key IN SELECT pg_catalog.jsonb_object_keys(NEW.config) LOOP
      IF v_cfg_key <> 'max' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    v_max := v15.v15_govern_json_int(NEW.config->'max', 1, 2147483647);
    IF v_max IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    v_ceiling := v15.v15_baseline_max(
      NEW.invoke_id,
      CASE v_key
        WHEN 'iteration_limit' THEN 'governance_iterations'
        ELSE 'governance_depth'
      END
    );
    IF v_max > v_ceiling THEN
      RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
    END IF;
  ELSIF v_key = 'budget_pool' THEN
    FOR v_cfg_key IN SELECT pg_catalog.jsonb_object_keys(NEW.config) LOOP
      IF v_cfg_key <> ALL (ARRAY['reserve_calls', 'reserve_cost']::text[]) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    IF NEW.config ? 'reserve_calls'
       AND v15.v15_govern_json_int(NEW.config->'reserve_calls', 1, 2147483647) IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    IF NEW.config ? 'reserve_cost'
       AND (
         pg_catalog.jsonb_typeof(NEW.config->'reserve_cost') <> 'number'
         OR (NEW.config->>'reserve_cost')::numeric < 0
       ) THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    SELECT i.pool_id INTO v_pool
    FROM v15.invokes i
    WHERE i.invoke_id = NEW.invoke_id;
    IF v_pool IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  ELSIF v_key = 'budget_forcing' THEN
    FOR v_cfg_key IN SELECT pg_catalog.jsonb_object_keys(NEW.config) LOOP
      IF v_cfg_key <> 'max_rejections' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    IF v15.v15_govern_json_int(NEW.config->'max_rejections', 1, 2147483647) IS NULL THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  ELSIF v_key = 'context_window_warning' THEN
    FOR v_cfg_key IN SELECT pg_catalog.jsonb_object_keys(NEW.config) LOOP
      IF v_cfg_key <> 'ratio' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    END LOOP;
    IF pg_catalog.jsonb_typeof(NEW.config->'ratio') IS DISTINCT FROM 'number'
       OR (NEW.config->>'ratio')::numeric <= 0
       OR (NEW.config->>'ratio')::numeric > 1 THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
  END IF;
  RETURN NEW;
END;
$fn$;

CREATE TRIGGER invoke_hooks_optional
  BEFORE INSERT OR UPDATE ON v15.invoke_hooks
  FOR EACH ROW EXECUTE FUNCTION v15.invoke_hooks_optional_guard();

CREATE FUNCTION v15.v15_register_hook(
  p_hook_key text,
  p_fn oid,
  p_baseline_required boolean
) RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_id uuid;
  v_owner oid;
BEGIN
  IF p_hook_key IS NULL OR p_fn IS NULL OR p_baseline_required IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.oid INTO v_owner
  FROM pg_catalog.pg_roles r
  WHERE r.rolname = 'v15_hook_' || p_hook_key;
  IF v_owner IS NULL THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: owner' USING ERRCODE = 'P1537';
  END IF;
  INSERT INTO v15.hook_defs (
    hook_def_id, hook_key, regprocedure, owner_role, baseline_required,
    handler_digest, search_path, created_at
  ) VALUES (
    pg_catalog.gen_random_uuid(),
    p_hook_key,
    p_fn,
    v_owner,
    p_baseline_required,
    v15.v15_handler_digest(p_fn),
    'pg_catalog',
    pg_catalog.clock_timestamp()
  )
  RETURNING hook_def_id INTO v_id;
  RETURN v_id;
END;
$fn$;

CREATE OR REPLACE FUNCTION v15.governance_iterations(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_max integer;
  v_ceiling integer;
  v_iter integer;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'llm_query'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'enter' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,config,max}') IS NULL
     OR (p_snapshot #>> '{self,config,max}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max}')::integer < 1
     OR (p_snapshot #>> '{ceilings,max_iterations}') IS DISTINCT FROM (p_snapshot #>> '{self,config,max}')
     OR (p_snapshot->>'iteration') IS NULL
     OR (p_snapshot->>'iteration') !~ '^[0-9]+$' THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  v_max := (p_snapshot #>> '{self,config,max}')::integer;
  v_iter := (p_snapshot->>'iteration')::integer;
  IF v_iter >= v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'abort',
      'fatal', false,
      'error', pg_catalog.jsonb_build_object('code', 'V15_ITERATION_EXCEEDED', 'message', '')
    );
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE OR REPLACE FUNCTION v15.governance_depth(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_max integer;
  v_ceiling integer;
  v_depth integer;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'invoke'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'enter' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,config,max}') IS NULL
     OR (p_snapshot #>> '{self,config,max}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max}')::integer < 1
     OR (p_snapshot #>> '{ceilings,max_depth}') IS DISTINCT FROM (p_snapshot #>> '{self,config,max}')
     OR (p_snapshot #>> '{io,depth}') IS NULL
     OR (p_snapshot #>> '{io,depth}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{io,depth}')::integer < 1 THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  v_max := (p_snapshot #>> '{self,config,max}')::integer;
  v_depth := (p_snapshot #>> '{io,depth}')::integer;
  IF v_depth > v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'abort',
      'fatal', false,
      'error', pg_catalog.jsonb_build_object('code', 'V15_RECURSION_EXCEEDED', 'message', '')
    );
  END IF;
  IF v_depth = v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'proceed',
      'recursion_available', false
    );
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE OR REPLACE FUNCTION v15.governance_io(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_max integer;
  v_ceiling integer;
  v_next integer;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'llm_query'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'enter' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,config,max}') IS NULL
     OR (p_snapshot #>> '{self,config,max}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max}')::integer < 1
     OR (p_snapshot #>> '{ceilings,max_io_attempts}') IS DISTINCT FROM (p_snapshot #>> '{self,config,max}')
     OR (p_snapshot #>> '{io,next_attempt_n}') IS NULL
     OR (p_snapshot #>> '{io,next_attempt_n}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{io,next_attempt_n}')::integer < 1 THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  v_max := (p_snapshot #>> '{self,config,max}')::integer;
  v_next := (p_snapshot #>> '{io,next_attempt_n}')::integer;
  IF v_next > v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'abort',
      'fatal', false,
      'error', pg_catalog.jsonb_build_object('code', 'V15_IO_EXHAUSTED', 'message', '')
    );
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE OR REPLACE FUNCTION v15.governance_statement(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_max integer;
  v_ceiling integer;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'repl_exec'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'enter' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,config,max}') IS NULL
     OR (p_snapshot #>> '{self,config,max}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max}')::integer < 1
     OR (p_snapshot #>> '{ceilings,max_statement_ms}') IS DISTINCT FROM (p_snapshot #>> '{self,config,max}') THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE FUNCTION v15.iteration_limit(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_max integer;
  v_iter integer;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'llm_query'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'enter' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,config,max}') IS NULL
     OR (p_snapshot #>> '{self,config,max}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max}')::integer < 1
     OR (p_snapshot->>'iteration') IS NULL
     OR (p_snapshot->>'iteration') !~ '^[0-9]+$' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_max := (p_snapshot #>> '{self,config,max}')::integer;
  v_iter := (p_snapshot->>'iteration')::integer;
  IF v_iter >= v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'abort',
      'fatal', false,
      'error', pg_catalog.jsonb_build_object('code', 'V15_ITERATION_EXCEEDED', 'message', '')
    );
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE FUNCTION v15.recursion_limit(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_max integer;
  v_depth integer;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'invoke'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'enter' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,config,max}') IS NULL
     OR (p_snapshot #>> '{self,config,max}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max}')::integer < 1
     OR (p_snapshot #>> '{io,depth}') IS NULL
     OR (p_snapshot #>> '{io,depth}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{io,depth}')::integer < 1 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_max := (p_snapshot #>> '{self,config,max}')::integer;
  v_depth := (p_snapshot #>> '{io,depth}')::integer;
  IF v_depth > v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'abort',
      'fatal', false,
      'error', pg_catalog.jsonb_build_object('code', 'V15_RECURSION_EXCEEDED', 'message', '')
    );
  END IF;
  IF v_depth = v_max THEN
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'proceed',
      'recursion_available', false
    );
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE FUNCTION v15.budget_pool(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_calls integer;
  v_cost numeric;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'llm_query'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'send' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF p_snapshot #> '{self,config,reserve_calls}' IS NULL
     OR p_snapshot #> '{self,config,reserve_calls}' = 'null'::jsonb THEN
    v_calls := 1;
  ELSIF (p_snapshot #>> '{self,config,reserve_calls}') !~ '^[0-9]+$'
        OR (p_snapshot #>> '{self,config,reserve_calls}')::integer < 1 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  ELSE
    v_calls := (p_snapshot #>> '{self,config,reserve_calls}')::integer;
  END IF;
  IF p_snapshot #> '{self,config,reserve_cost}' IS NULL
     OR p_snapshot #> '{self,config,reserve_cost}' = 'null'::jsonb THEN
    v_cost := 0;
  ELSE
    v_cost := (p_snapshot #>> '{self,config,reserve_cost}')::numeric;
  END IF;
  RETURN pg_catalog.jsonb_build_object(
    'contract', 1,
    'action', 'proceed',
    'budget', pg_catalog.jsonb_build_object('reserve_calls', v_calls, 'reserve_cost', v_cost)
  );
END;
$fn$;

CREATE FUNCTION v15.budget_forcing(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ord integer;
  v_max integer;
  v_key text;
  v_n bigint;
  v_id text;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'repl_exec'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'complete' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF (p_snapshot #>> '{self,ordinal}') IS NULL
     OR (p_snapshot #>> '{self,ordinal}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max_rejections}') IS NULL
     OR (p_snapshot #>> '{self,config,max_rejections}') !~ '^[0-9]+$'
     OR (p_snapshot #>> '{self,config,max_rejections}')::integer < 1 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_ord := (p_snapshot #>> '{self,ordinal}')::integer;
  v_max := (p_snapshot #>> '{self,config,max_rejections}')::integer;
  v_key := 'budget_forcing:' || v_ord::text;
  v_n := coalesce((p_snapshot->'counters'->>v_key)::bigint, 0);
  IF p_snapshot #>> '{io,result_kind}' = 'return'
     AND p_snapshot #>> '{io,capture}' = ''
     AND v_n < v_max THEN
    v_id := v_key || ':' || v_n::text;
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'proceed',
      'exec_result', pg_catalog.jsonb_build_object(
        'result_kind', 'continue',
        'return_value', 'null'::jsonb,
        'error', 'null'::jsonb
      ),
      'messages', pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'id', v_id,
        'role', 'user',
        'content', $bf$[v15 budget_forcing] The finish was not accepted. Continue the task. Finished iterations are rows of jaz.history.$bf$,
        'persistent', true
      ))
    );
  END IF;
  RETURN '{"contract":1,"action":"proceed"}'::jsonb;
END;
$fn$;

CREATE FUNCTION v15.context_window_warning(p_snapshot jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_ratio numeric;
  v_limit numeric;
  v_chars numeric;
  v_text text;
BEGIN
  IF p_snapshot->>'span' IS DISTINCT FROM 'llm_query'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'send' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF pg_catalog.jsonb_typeof(p_snapshot #> '{self,config,ratio}') IS DISTINCT FROM 'number'
     OR pg_catalog.jsonb_typeof(p_snapshot #> '{config,protocol,max_invoke_input_length}') IS DISTINCT FROM 'number'
     OR pg_catalog.jsonb_typeof(p_snapshot #> '{io,input_chars}') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_ratio := (p_snapshot #>> '{self,config,ratio}')::numeric;
  v_limit := (p_snapshot #>> '{config,protocol,max_invoke_input_length}')::numeric;
  v_chars := (p_snapshot #>> '{io,input_chars}')::numeric;
  IF v_chars < floor(v_limit * v_ratio) THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF coalesce((p_snapshot->>'recursion_available')::boolean, false) THEN
    v_text := $warn$[v15 context_window_warning] The prompt is near max_invoke_input_length. Finished iterations are rows of jaz.history. Ancestor history is jaz.prior_history(invoke_id). To delegate, end with exactly these two statements and no further statements after them:
SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);
SELECT jaz."return"(jaz.var('<ident>'));$warn$;
  ELSE
    v_text := $leaf$[v15 context_window_warning] The prompt is near max_invoke_input_length. Finished iterations are rows of jaz.history. Ancestor history is jaz.prior_history(invoke_id).$leaf$;
  END IF;
  RETURN pg_catalog.jsonb_build_object(
    'contract', 1,
    'action', 'proceed',
    'messages', pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'id', 'context_window_warning',
      'role', 'user',
      'content', v_text,
      'persistent', false
    ))
  );
END;
$fn$;

CREATE OR REPLACE FUNCTION v15.v15_on_phase(
  invoke_id uuid,
  iteration integer,
  span text,
  phase text,
  io jsonb
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
#variable_conflict use_column
DECLARE
  v_invoke uuid;
  v_iter integer;
  v_span text;
  v_phase text;
  v_io jsonb;
  v_got text[];
  v_config jsonb;
  v_recur boolean;
  v_pool uuid;
  v_ceilings jsonb;
  v_snap jsonb;
  v_overlay jsonb;
  v_enter_msgs jsonb;
  v_hook record;
  v_nsp text;
  v_proname text;
  v_ret jsonb;
  v_call jsonb;
  v_state text;
  v_msg text;
  v_abort boolean := false;
  v_top text;
  v_differ boolean := false;
  v_fatal boolean := false;
  v_norm text;
  v_nf boolean;
  v_msg_acc jsonb := '[]'::jsonb;
  v_elem jsonb;
  v_prev jsonb;
  v_i integer;
  v_drops jsonb := '{}'::jsonb;
  v_inputs jsonb := '[]'::jsonb;
  v_idrops jsonb := '{}'::jsonb;
  v_boards jsonb := '[]'::jsonb;
  v_exec jsonb;
  v_budget jsonb;
  v_disable boolean := false;
  v_out jsonb;
  v_final_msgs jsonb := '[]'::jsonb;
  v_id text;
  v_seq bigint;
  v_kind text;
  v_name text;
  v_calls integer;
  v_cost numeric;
  v_write jsonb;
  v_key text;
BEGIN
  v_invoke := invoke_id;
  v_iter := iteration;
  v_span := span;
  v_phase := phase;
  v_io := io;
  IF v15.v15_govern_io_keys(v_span, v_phase) IS NULL THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_io IS NULL OR pg_catalog.jsonb_typeof(v_io) <> 'object' THEN
    RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
  END IF;
  SELECT coalesce(pg_catalog.array_agg(k.key ORDER BY k.key), '{}'::text[])
    INTO v_got
  FROM pg_catalog.jsonb_object_keys(v_io) AS k(key);
  IF v_got IS DISTINCT FROM v15.v15_govern_io_keys(v_span, v_phase) THEN
    RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
  END IF;
  IF v_span = 'invoke' AND v_phase = 'enter' THEN
    IF v15.v15_govern_json_int(v_io->'depth', 1, 2147483647) IS NULL THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  ELSIF v_span = 'llm_query' AND v_phase = 'enter' THEN
    IF v15.v15_govern_json_int(v_io->'iteration', 0, 2147483647) IS DISTINCT FROM v_iter
       OR v15.v15_govern_json_int(v_io->'next_attempt_n', 1, 2147483647) IS NULL THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  ELSIF v_span = 'llm_query' AND v_phase = 'send' THEN
    IF v15.v15_govern_json_int(v_io->'iteration', 0, 2147483647) IS DISTINCT FROM v_iter
       OR pg_catalog.jsonb_typeof(v_io->'logical_digest') <> 'string'
       OR pg_catalog.char_length(v_io->>'logical_digest') < 1
       OR v15.v15_govern_json_int(v_io->'input_chars', 0, 2147483647) IS NULL
       OR (
         v_io->'enter_messages' IS DISTINCT FROM 'null'::jsonb
         AND pg_catalog.jsonb_typeof(v_io->'enter_messages') <> 'array'
       )
       OR (
         v_io->'enter_overlay' IS DISTINCT FROM 'null'::jsonb
         AND pg_catalog.jsonb_typeof(v_io->'enter_overlay') <> 'object'
       ) THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
    IF pg_catalog.jsonb_typeof(v_io->'enter_overlay') = 'object' THEN
      FOR v_key IN SELECT pg_catalog.jsonb_object_keys(v_io->'enter_overlay') LOOP
        IF v_key <> ALL (ARRAY['recursion_available', 'blackboard_writes']::text[]) THEN
          RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
        END IF;
      END LOOP;
      IF v_io->'enter_overlay' ? 'recursion_available'
         AND pg_catalog.jsonb_typeof(v_io #> '{enter_overlay,recursion_available}') <> 'boolean' THEN
        RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
      END IF;
      IF v_io->'enter_overlay' ? 'blackboard_writes'
         AND pg_catalog.jsonb_typeof(v_io #> '{enter_overlay,blackboard_writes}') <> 'array' THEN
        RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
      END IF;
    END IF;
  ELSIF v_span = 'llm_query' AND v_phase = 'complete' THEN
    IF pg_catalog.jsonb_typeof(v_io->'attempt_id') <> 'string'
       OR (v_io->>'attempt_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  ELSIF v_span = 'llm_query' AND v_phase = 'exit' THEN
    IF v_io->'attempt_id' IS DISTINCT FROM 'null'::jsonb
       AND (
         pg_catalog.jsonb_typeof(v_io->'attempt_id') <> 'string'
         OR (v_io->>'attempt_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
       ) THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  ELSIF v_span = 'repl_exec' AND v_phase = 'enter' THEN
    IF v15.v15_govern_json_int(v_io->'iteration', 0, 2147483647) IS DISTINCT FROM v_iter
       OR v15.v15_govern_json_int(v_io->'resume_stmt', 0, 2147483647) IS NULL THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  ELSIF v_span = 'repl_exec' AND v_phase = 'complete' THEN
    IF pg_catalog.jsonb_typeof(v_io->'result_kind') <> 'string'
       OR (v_io->>'result_kind') NOT IN ('continue', 'return', 'raise')
       OR pg_catalog.jsonb_typeof(v_io->'capture') <> 'string' THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  ELSIF v_phase = 'exit' OR (v_span = 'invoke' AND v_phase = 'complete') THEN
    IF pg_catalog.jsonb_typeof(v_io->'outcome') <> 'string'
       OR (v_io->>'outcome') NOT IN ('completed', 'aborted', 'failed') THEN
      RAISE EXCEPTION 'V15_PHASE_CONTRACT' USING ERRCODE = 'P1516';
    END IF;
  END IF;
  SELECT i.resolved_config, i.recursion_available, i.pool_id
    INTO v_config, v_recur, v_pool
  FROM v15.invokes i
  WHERE i.invoke_id = v_invoke;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_ceilings := pg_catalog.jsonb_build_object(
    'max_iterations', v15.v15_baseline_max(v_invoke, 'governance_iterations'),
    'max_depth', v15.v15_baseline_max(v_invoke, 'governance_depth'),
    'max_io_attempts', v15.v15_baseline_max(v_invoke, 'governance_io'),
    'max_statement_ms', v15.v15_baseline_max(v_invoke, 'governance_statement')
  );
  v_enter_msgs := v_io->'enter_messages';
  v_overlay := v_io->'enter_overlay';
  SELECT pg_catalog.jsonb_build_object(
    'contract', 1,
    'invoke_id', v_invoke,
    'iteration', v_iter,
    'span', v_span,
    'phase', v_phase,
    'io', v_io - 'enter_messages' - 'enter_overlay',
    'config', v_config,
    'ceilings', v_ceilings,
    'recursion_available', v_recur,
    'blackboard', pg_catalog.jsonb_build_object(
      'values', coalesce((
        SELECT pg_catalog.jsonb_object_agg(b.key, b.value)
        FROM v15.blackboard b WHERE b.invoke_id = v_invoke
      ), '{}'::jsonb),
      'generation', coalesce((
        SELECT pg_catalog.jsonb_object_agg(b.key, b.generation)
        FROM v15.blackboard b WHERE b.invoke_id = v_invoke
      ), '{}'::jsonb)
    ),
    'counters', coalesce((
      SELECT pg_catalog.jsonb_object_agg(c.counter_key, c.n)
      FROM v15.hook_counters c WHERE c.invoke_id = v_invoke
    ), '{}'::jsonb),
    'hooks', coalesce((
      SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'ordinal', h.ordinal,
        'hook_key', d.hook_key,
        'channel', h.channel,
        'config', h.config,
        'state', h.state
      ) ORDER BY h.ordinal)
      FROM v15.invoke_hooks h
      JOIN v15.hook_defs d ON d.hook_def_id = h.hook_def_id
      WHERE h.invoke_id = v_invoke
    ), '[]'::jsonb)
  ) INTO v_snap;
  IF v_span = 'llm_query' AND v_phase = 'send'
     AND pg_catalog.jsonb_typeof(v_overlay) = 'object' THEN
    IF v_overlay ? 'recursion_available' THEN
      v_snap := pg_catalog.jsonb_set(
        v_snap, '{recursion_available}', v_overlay->'recursion_available', true
      );
    END IF;
    IF v_overlay ? 'blackboard_writes' THEN
      FOR v_elem IN
        SELECT e.value FROM pg_catalog.jsonb_array_elements(v_overlay->'blackboard_writes') AS e(value)
      LOOP
        v_key := v_elem->>'key';
        v_seq := coalesce((v_snap #>> ARRAY['blackboard', 'generation', v_key])::bigint, 0) + 1;
        v_snap := pg_catalog.jsonb_set(
          v_snap, ARRAY['blackboard', 'values', v_key], v_elem->'value', true
        );
        v_snap := pg_catalog.jsonb_set(
          v_snap, ARRAY['blackboard', 'generation', v_key], pg_catalog.to_jsonb(v_seq), true
        );
      END LOOP;
    END IF;
  END IF;
  FOR v_hook IN
    SELECT h.ordinal, h.channel, h.config, h.state, d.hook_key,
           d.regprocedure, d.handler_digest, d.baseline_required
    FROM v15.invoke_hooks h
    JOIN v15.hook_defs d ON d.hook_def_id = h.hook_def_id
    WHERE h.invoke_id = v_invoke
    ORDER BY h.ordinal
  LOOP
    PERFORM v15.v15_govern_recheck(
      v_hook.regprocedure, 'v15_hook_' || v_hook.hook_key, v_hook.handler_digest
    );
    SELECT n.nspname, p.proname
      INTO v_nsp, v_proname
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE p.oid = v_hook.regprocedure;
    v_call := v_snap || pg_catalog.jsonb_build_object(
      'self', pg_catalog.jsonb_build_object(
        'ordinal', v_hook.ordinal,
        'hook_key', v_hook.hook_key,
        'channel', v_hook.channel,
        'config', v_hook.config,
        'state', v_hook.state
      )
    );
    v_ret := NULL;
    BEGIN
      EXECUTE format('SELECT %I.%I($1::jsonb)', v_nsp, v_proname)
        INTO v_ret
        USING v_call;
    EXCEPTION
      WHEN OTHERS THEN
        IF v_hook.baseline_required OR v_hook.channel = 'baseline' THEN
          RAISE EXCEPTION 'V15_GOVERNANCE_FAULT' USING ERRCODE = 'P1508';
        END IF;
        GET STACKED DIAGNOSTICS v_state = RETURNED_SQLSTATE, v_msg = MESSAGE_TEXT;
        PERFORM v15.v15_repl_event(
          v_invoke, 'audit', NULL, NULL, NULL,
          pg_catalog.jsonb_build_object(
            'op', 'handler_exception',
            'hook_key', v_hook.hook_key,
            'sqlstate', v_state,
            'message', pg_catalog.left(coalesce(v_msg, ''), 200)
          ),
          NULL
        );
        v_ret := NULL;
    END;
    IF v_ret IS NULL THEN
      CONTINUE;
    END IF;
    PERFORM v15.v15_govern_check_return(v_span, v_phase, v_io, v_ret);
    IF v_ret->>'action' = 'abort' THEN
      v_norm := v_ret #>> '{error,code}';
      IF v_norm = 'V15_BUDGET_EXHAUSTED' THEN
        v_nf := true;
      ELSIF v_norm IN (
        'V15_IO_EXHAUSTED', 'V15_RECURSION_EXCEEDED', 'V15_ITERATION_EXCEEDED'
      ) THEN
        v_nf := false;
      ELSE
        v_norm := 'V15_HOOK_ABORT';
        v_nf := (v_ret->>'fatal')::boolean;
      END IF;
      IF NOT v_abort THEN
        v_top := v_norm;
      ELSIF v_top IS DISTINCT FROM v_norm THEN
        v_differ := true;
      END IF;
      v_abort := true;
      v_fatal := v_fatal OR v_nf;
    END IF;
    v_i := 0;
    FOR v_elem IN
      SELECT e.value
      FROM pg_catalog.jsonb_array_elements(coalesce(v_ret->'messages', '[]'::jsonb)) AS e(value)
    LOOP
      SELECT x.value->'msg' INTO v_prev
      FROM pg_catalog.jsonb_array_elements(v_msg_acc) AS x(value)
      WHERE x.value->'msg'->>'id' = v_elem->>'id'
      LIMIT 1;
      IF v_prev IS NOT NULL AND v_prev IS DISTINCT FROM v_elem THEN
        RAISE EXCEPTION 'V15_EFFECT_CONFLICT' USING ERRCODE = 'P1535';
      END IF;
      IF v_prev IS NULL THEN
        v_msg_acc := v_msg_acc || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
          'ord', v_hook.ordinal, 'idx', v_i, 'msg', v_elem
        ));
      END IF;
      v_i := v_i + 1;
    END LOOP;
    IF v_ret ? 'message_drops' AND pg_catalog.jsonb_typeof(v_ret->'message_drops') = 'array' THEN
      FOR v_elem IN
        SELECT e.value FROM pg_catalog.jsonb_array_elements(v_ret->'message_drops') AS e(value)
      LOOP
        v_drops := v_drops || pg_catalog.jsonb_build_object(v_elem->>'id', true);
      END LOOP;
    END IF;
    v_i := 0;
    IF v_ret ? 'input_adds' AND pg_catalog.jsonb_typeof(v_ret->'input_adds') = 'array' THEN
      FOR v_elem IN
        SELECT e.value FROM pg_catalog.jsonb_array_elements(v_ret->'input_adds') AS e(value)
      LOOP
        SELECT x.value INTO v_prev
        FROM pg_catalog.jsonb_array_elements(v_inputs) AS x(value)
        WHERE x.value->>'name' = v_elem->>'name'
        LIMIT 1;
        IF v_prev IS NOT NULL AND (
          v_prev->'value' IS DISTINCT FROM v_elem->'value'
          OR v_prev->'show_in_prompt' IS DISTINCT FROM v_elem->'show_in_prompt'
        ) THEN
          RAISE EXCEPTION 'V15_INPUT_CONFLICT' USING ERRCODE = 'P1534';
        END IF;
        IF v_prev IS NULL THEN
          v_inputs := v_inputs || pg_catalog.jsonb_build_array(v_elem);
        END IF;
        v_i := v_i + 1;
      END LOOP;
    END IF;
    IF v_ret ? 'input_drops' AND pg_catalog.jsonb_typeof(v_ret->'input_drops') = 'array' THEN
      FOR v_elem IN
        SELECT e.value FROM pg_catalog.jsonb_array_elements(v_ret->'input_drops') AS e(value)
      LOOP
        v_idrops := v_idrops || pg_catalog.jsonb_build_object(v_elem->>'name', true);
      END LOOP;
    END IF;
    IF v_ret ? 'blackboard_writes' AND pg_catalog.jsonb_typeof(v_ret->'blackboard_writes') = 'array' THEN
      FOR v_elem IN
        SELECT e.value FROM pg_catalog.jsonb_array_elements(v_ret->'blackboard_writes') AS e(value)
      LOOP
        SELECT x.value INTO v_prev
        FROM pg_catalog.jsonb_array_elements(v_boards) AS x(value)
        WHERE x.value->>'key' = v_elem->>'key'
        LIMIT 1;
        IF v_prev IS NOT NULL AND v_prev->'value' IS DISTINCT FROM v_elem->'value' THEN
          RAISE EXCEPTION 'V15_BLACKBOARD_CONFLICT' USING ERRCODE = 'P1533';
        END IF;
        IF v_prev IS NULL THEN
          v_boards := v_boards || pg_catalog.jsonb_build_array(v_elem);
        END IF;
      END LOOP;
    END IF;
    IF v_ret ? 'exec_result' AND v_ret->'exec_result' IS DISTINCT FROM 'null'::jsonb THEN
      IF v_exec IS NOT NULL AND v_exec IS DISTINCT FROM v_ret->'exec_result' THEN
        RAISE EXCEPTION 'V15_EFFECT_CONFLICT' USING ERRCODE = 'P1535';
      END IF;
      v_exec := v_ret->'exec_result';
    END IF;
    IF v_ret ? 'budget' AND v_ret->'budget' IS DISTINCT FROM 'null'::jsonb THEN
      IF v_budget IS NOT NULL AND v_budget IS DISTINCT FROM v_ret->'budget' THEN
        RAISE EXCEPTION 'V15_EFFECT_CONFLICT' USING ERRCODE = 'P1535';
      END IF;
      v_budget := v_ret->'budget';
    END IF;
    IF v_ret ? 'recursion_available'
       AND v_ret->'recursion_available' = 'false'::jsonb THEN
      v_disable := true;
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.jsonb_object_keys(v_drops) AS d(key)
    JOIN pg_catalog.jsonb_array_elements(v_msg_acc) AS e(value)
      ON e.value->'msg'->>'id' = d.key
  ) THEN
    RAISE EXCEPTION 'V15_EFFECT_CONFLICT' USING ERRCODE = 'P1535';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.jsonb_object_keys(v_idrops) AS d(key)
    JOIN pg_catalog.jsonb_array_elements(v_inputs) AS e(value)
      ON e.value->>'name' = d.key
  ) THEN
    RAISE EXCEPTION 'V15_INPUT_CONFLICT' USING ERRCODE = 'P1534';
  END IF;
  SELECT coalesce(pg_catalog.jsonb_agg(x.msg ORDER BY x.ord, x.idx), '[]'::jsonb)
    INTO v_final_msgs
  FROM (
    SELECT (e.value->>'ord')::integer AS ord,
           (e.value->>'idx')::integer AS idx,
           e.value->'msg' AS msg
    FROM pg_catalog.jsonb_array_elements(v_msg_acc) AS e(value)
  ) x;
  IF v_abort THEN
    IF v_differ THEN
      v_top := 'V15_HOOK_ABORT';
    END IF;
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'abort',
      'fatal', v_fatal,
      'code', v_top
    );
  END IF;
  v_out := pg_catalog.jsonb_build_object('contract', 1, 'action', 'proceed');
  IF pg_catalog.jsonb_array_length(v_final_msgs) > 0 THEN
    v_out := v_out || pg_catalog.jsonb_build_object('messages', v_final_msgs);
  END IF;
  IF v_disable THEN
    v_out := v_out || pg_catalog.jsonb_build_object('recursion_available', false);
  END IF;
  IF pg_catalog.jsonb_array_length(v_inputs) > 0 THEN
    v_out := v_out || pg_catalog.jsonb_build_object('input_adds', v_inputs);
  END IF;
  IF v_idrops <> '{}'::jsonb THEN
    v_out := v_out || pg_catalog.jsonb_build_object(
      'input_drops',
      coalesce((
        SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name', d.key))
        FROM pg_catalog.jsonb_object_keys(v_idrops) AS d(key)
      ), '[]'::jsonb)
    );
  END IF;
  IF pg_catalog.jsonb_array_length(v_boards) > 0 THEN
    v_out := v_out || pg_catalog.jsonb_build_object('blackboard_writes', v_boards);
  END IF;
  IF v_exec IS NOT NULL THEN
    v_out := v_out || pg_catalog.jsonb_build_object('exec_result', v_exec);
  END IF;
  IF v_span = 'llm_query' AND v_phase = 'enter' THEN
    RETURN v_out;
  END IF;
  IF v_span = 'llm_query' AND v_phase = 'send' THEN
    IF v_budget IS NULL THEN
      v_budget := pg_catalog.jsonb_build_object('reserve_calls', 1, 'reserve_cost', 0);
    END IF;
    v_calls := (v_budget->>'reserve_calls')::integer;
    v_cost := (v_budget->>'reserve_cost')::numeric;
    IF NOT v15.v15_io_pool_reserve(v_pool, v_calls, v_cost) THEN
      RETURN pg_catalog.jsonb_build_object(
        'contract', 1,
        'action', 'abort',
        'fatal', true,
        'code', 'V15_BUDGET_EXHAUSTED'
      );
    END IF;
    IF pg_catalog.jsonb_typeof(v_overlay) = 'object'
       AND v_overlay ? 'recursion_available' THEN
      IF (v_overlay->>'recursion_available')::boolean THEN
        RAISE EXCEPTION 'V15_GOVERNANCE_RAISE' USING ERRCODE = 'P1505';
      END IF;
      UPDATE v15.invokes i
      SET recursion_available = false,
          revision = i.revision + 1,
          updated_at = pg_catalog.clock_timestamp()
      WHERE i.invoke_id = v_invoke
        AND i.recursion_available;
    END IF;
    IF pg_catalog.jsonb_typeof(v_overlay) = 'object' AND v_overlay ? 'blackboard_writes' THEN
      FOR v_elem IN
        SELECT e.value FROM pg_catalog.jsonb_array_elements(v_overlay->'blackboard_writes') AS e(value)
      LOOP
        INSERT INTO v15.blackboard (invoke_id, key, value, generation)
        VALUES (v_invoke, v_elem->>'key', v_elem->'value', 1)
        ON CONFLICT (invoke_id, key) DO UPDATE
          SET value = EXCLUDED.value,
              generation = v15.blackboard.generation + 1,
              revision = v15.blackboard.revision + 1;
      END LOOP;
    END IF;
    FOR v_elem IN
      SELECT e.value FROM pg_catalog.jsonb_array_elements(v_boards) AS e(value)
    LOOP
      INSERT INTO v15.blackboard (invoke_id, key, value, generation)
      VALUES (v_invoke, v_elem->>'key', v_elem->'value', 1)
      ON CONFLICT (invoke_id, key) DO UPDATE
        SET value = EXCLUDED.value,
            generation = v15.blackboard.generation + 1,
            revision = v15.blackboard.revision + 1;
    END LOOP;
    v_write := '[]'::jsonb;
    IF pg_catalog.jsonb_typeof(v_enter_msgs) = 'array' THEN
      v_write := v_enter_msgs;
    END IF;
    v_write := v_write || v_final_msgs;
    FOR v_elem IN
      SELECT e.value FROM pg_catalog.jsonb_array_elements(v_write) AS e(value)
    LOOP
      IF NOT coalesce((v_elem->>'persistent')::boolean, false) THEN
        CONTINUE;
      END IF;
      v_id := v_elem->>'id';
      IF EXISTS (
        SELECT 1 FROM v15.llm_messages m
        WHERE m.invoke_id = v_invoke AND m.message_id = v_id
      ) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      SELECT coalesce(max(m.msg_seq), -1) + 1 INTO v_seq
      FROM v15.llm_messages m
      WHERE m.invoke_id = v_invoke;
      INSERT INTO v15.llm_messages (
        invoke_id, msg_seq, message_id, iteration, role, kind, content
      ) VALUES (
        v_invoke, v_seq, v_id, NULL, v_elem->>'role', 'persistent_hook', v_elem->>'content'
      );
    END LOOP;
    RETURN v_out || pg_catalog.jsonb_build_object('budget', v_budget);
  END IF;
  FOR v_key IN SELECT pg_catalog.jsonb_object_keys(v_idrops) LOOP
    SELECT b.kind INTO v_kind
    FROM v15.bindings b
    WHERE b.invoke_id = v_invoke AND b.name = v_key;
    IF FOUND AND v_kind <> 'input' THEN
      RAISE EXCEPTION 'V15_INVALID_EFFECT' USING ERRCODE = 'P1506';
    END IF;
    IF FOUND THEN
      DELETE FROM v15.bindings b
      WHERE b.invoke_id = v_invoke AND b.name = v_key;
    END IF;
  END LOOP;
  FOR v_elem IN
    SELECT e.value FROM pg_catalog.jsonb_array_elements(v_inputs) AS e(value)
  LOOP
    v_name := v_elem->>'name';
    SELECT b.kind INTO v_kind
    FROM v15.bindings b
    WHERE b.invoke_id = v_invoke AND b.name = v_name;
    IF FOUND THEN
      RAISE EXCEPTION 'V15_INPUT_CONFLICT' USING ERRCODE = 'P1534';
    END IF;
    INSERT INTO v15.bindings (
      invoke_id, name, kind, value, show_in_prompt, provenance
    ) VALUES (
      v_invoke,
      v_name,
      'input',
      v_elem->'value',
      (v_elem->>'show_in_prompt')::boolean,
      'hook'
    );
  END LOOP;
  IF v_disable THEN
    UPDATE v15.invokes i
    SET recursion_available = false,
        revision = i.revision + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE i.invoke_id = v_invoke
      AND i.recursion_available;
  END IF;
  IF NOT (v_span = 'invoke' AND v_phase = 'enter') THEN
    FOR v_elem IN
      SELECT e.value FROM pg_catalog.jsonb_array_elements(v_final_msgs) AS e(value)
    LOOP
      IF NOT coalesce((v_elem->>'persistent')::boolean, false) THEN
        CONTINUE;
      END IF;
      v_id := v_elem->>'id';
      IF EXISTS (
        SELECT 1 FROM v15.llm_messages m
        WHERE m.invoke_id = v_invoke AND m.message_id = v_id
      ) THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      SELECT coalesce(max(m.msg_seq), -1) + 1 INTO v_seq
      FROM v15.llm_messages m
      WHERE m.invoke_id = v_invoke;
      INSERT INTO v15.llm_messages (
        invoke_id, msg_seq, message_id, iteration, role, kind, content
      ) VALUES (
        v_invoke, v_seq, v_id, NULL, v_elem->>'role', 'persistent_hook', v_elem->>'content'
      );
    END LOOP;
  END IF;
  FOR v_elem IN
    SELECT e.value FROM pg_catalog.jsonb_array_elements(v_boards) AS e(value)
  LOOP
    INSERT INTO v15.blackboard (invoke_id, key, value, generation)
    VALUES (v_invoke, v_elem->>'key', v_elem->'value', 1)
    ON CONFLICT (invoke_id, key) DO UPDATE
      SET value = EXCLUDED.value,
          generation = v15.blackboard.generation + 1,
          revision = v15.blackboard.revision + 1;
  END LOOP;
  RETURN v_out;
END;
$fn$;

ALTER FUNCTION v15.v15_govern_known_code(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_has_reserved(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_allow(text, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_io_keys(text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_json_int(jsonb, integer, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_recheck(oid, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_exact_keys(jsonb, text[]) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_check_return(text, text, jsonb, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.invoke_hooks_optional_guard() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_register_hook(text, oid, boolean) OWNER TO v15_owner;

ALTER FUNCTION v15.iteration_limit(jsonb) OWNER TO v15_hook_iteration_limit;
ALTER FUNCTION v15.recursion_limit(jsonb) OWNER TO v15_hook_recursion_limit;
ALTER FUNCTION v15.budget_pool(jsonb) OWNER TO v15_hook_budget_pool;
ALTER FUNCTION v15.budget_forcing(jsonb) OWNER TO v15_hook_budget_forcing;
ALTER FUNCTION v15.context_window_warning(jsonb) OWNER TO v15_hook_context_window_warning;

REVOKE ALL ON FUNCTION v15.v15_govern_known_code(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_has_reserved(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_allow(text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_io_keys(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_json_int(jsonb, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_recheck(oid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_exact_keys(jsonb, text[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_check_return(text, text, jsonb, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.invoke_hooks_optional_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_register_hook(text, oid, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.iteration_limit(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.recursion_limit(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.budget_pool(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.budget_forcing(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.context_window_warning(jsonb) FROM PUBLIC;

REVOKE ALL ON FUNCTION v15.iteration_limit(jsonb) FROM v15_hook_iteration_limit;
REVOKE ALL ON FUNCTION v15.recursion_limit(jsonb) FROM v15_hook_recursion_limit;
REVOKE ALL ON FUNCTION v15.budget_pool(jsonb) FROM v15_hook_budget_pool;
REVOKE ALL ON FUNCTION v15.budget_forcing(jsonb) FROM v15_hook_budget_forcing;
REVOKE ALL ON FUNCTION v15.context_window_warning(jsonb) FROM v15_hook_context_window_warning;

GRANT EXECUTE ON FUNCTION v15.v15_govern_known_code(text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_has_reserved(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_allow(text, text, text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_io_keys(text, text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_json_int(jsonb, integer, integer) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_recheck(oid, text, text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_exact_keys(jsonb, text[]) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_check_return(text, text, jsonb, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_register_hook(text, oid, boolean) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_register_hook(text, oid, boolean) TO v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.iteration_limit(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.recursion_limit(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.budget_pool(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.budget_forcing(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.context_window_warning(jsonb) TO v15_owner;

UPDATE v15.hook_defs
SET handler_digest = v15.v15_handler_digest(regprocedure)
WHERE hook_key IN (
  'governance_iterations',
  'governance_depth',
  'governance_io',
  'governance_statement'
);

INSERT INTO v15.hook_defs (
  hook_def_id, hook_key, regprocedure, owner_role, baseline_required,
  handler_digest, search_path, created_at
)
SELECT
  pg_catalog.gen_random_uuid(),
  k.hook_key,
  k.fn,
  k.owner_role,
  false,
  v15.v15_handler_digest(k.fn),
  'pg_catalog',
  pg_catalog.clock_timestamp()
FROM (
  VALUES
    (
      'iteration_limit',
      'v15.iteration_limit(jsonb)'::regprocedure,
      'v15_hook_iteration_limit'::regrole
    ),
    (
      'recursion_limit',
      'v15.recursion_limit(jsonb)'::regprocedure,
      'v15_hook_recursion_limit'::regrole
    ),
    (
      'budget_pool',
      'v15.budget_pool(jsonb)'::regprocedure,
      'v15_hook_budget_pool'::regrole
    ),
    (
      'budget_forcing',
      'v15.budget_forcing(jsonb)'::regprocedure,
      'v15_hook_budget_forcing'::regrole
    ),
    (
      'context_window_warning',
      'v15.context_window_warning(jsonb)'::regprocedure,
      'v15_hook_context_window_warning'::regrole
    )
) AS k(hook_key, fn, owner_role);
