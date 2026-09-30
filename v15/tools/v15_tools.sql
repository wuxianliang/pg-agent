DO $status$
DECLARE
  v_name text;
BEGIN
  SELECT c.conname
    INTO STRICT v_name
  FROM pg_catalog.pg_constraint c
  JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
  JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
  WHERE n.nspname = 'v15'
    AND t.relname = 'invokes'
    AND c.contype = 'c'
    AND c.conname NOT IN (
      'invokes_parent_pair', 'invokes_lease', 'invokes_completed',
      'invokes_failed', 'invokes_aborted', 'invokes_scratch_schema'
    )
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%pending%'
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%runnable%'
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%suspended%'
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%completed%'
    AND pg_catalog.pg_get_constraintdef(c.oid) NOT LIKE '%tool_wait%';
  EXECUTE format('ALTER TABLE v15.invokes DROP CONSTRAINT %I', v_name);
  EXECUTE format(
    'ALTER TABLE v15.invokes ADD CONSTRAINT %I CHECK (status IN (
      ''pending'', ''runnable'', ''leased'', ''suspended'', ''tool_wait'',
      ''completed'', ''failed'', ''aborted''
    ))',
    v_name
  );
END
$status$;

ALTER TABLE v15.statements ADD COLUMN tool_name text NULL;

DO $kind$
DECLARE
  v_name text;
BEGIN
  SELECT c.conname
    INTO STRICT v_name
  FROM pg_catalog.pg_constraint c
  JOIN pg_catalog.pg_class t ON t.oid = c.conrelid
  JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
  WHERE n.nspname = 'v15'
    AND t.relname = 'statements'
    AND c.contype = 'c'
    AND c.conname NOT IN (
      'statements_bind_name', 'statements_error_sqlstate', 'statements_sql_digest'
    )
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%plain%'
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%bind_invoke%'
    AND pg_catalog.pg_get_constraintdef(c.oid) LIKE '%assign%'
    AND pg_catalog.pg_get_constraintdef(c.oid) NOT LIKE '%bind_tool%';
  EXECUTE format('ALTER TABLE v15.statements DROP CONSTRAINT %I', v_name);
  EXECUTE format(
    'ALTER TABLE v15.statements ADD CONSTRAINT %I CHECK (kind IN (
      ''plain'', ''bind_invoke'', ''return'', ''raise'', ''print'', ''assign'',
      ''bind_tool''
    ))',
    v_name
  );
END
$kind$;

ALTER TABLE v15.statements DROP CONSTRAINT statements_bind_name;
ALTER TABLE v15.statements ADD CONSTRAINT statements_bind_name CHECK (
  kind NOT IN ('bind_invoke', 'bind_tool') OR bind_name IS NOT NULL
);
ALTER TABLE v15.statements ADD CONSTRAINT statements_tool_name CHECK (
  (kind = 'bind_tool') = (tool_name IS NOT NULL)
);

CREATE TABLE v15.tool_requests (
  request_id uuid PRIMARY KEY,
  invoke_id uuid NOT NULL,
  iteration int NOT NULL CHECK (iteration >= 0),
  stmt_index int NOT NULL CHECK (stmt_index >= 0),
  tool_id uuid NOT NULL REFERENCES v15.tool_catalog (tool_id),
  bind_name text NOT NULL,
  args jsonb NOT NULL,
  args_digest text NOT NULL,
  status text NOT NULL CHECK (status IN ('open', 'settled', 'failed', 'exhausted')),
  revision bigint NOT NULL DEFAULT 0,
  UNIQUE (invoke_id, iteration, stmt_index),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES v15.iterations (invoke_id, iteration),
  CONSTRAINT tool_requests_args_digest CHECK (args_digest = md5(args::text)),
  CONSTRAINT tool_requests_args_object CHECK (jsonb_typeof(args) = 'object')
);

CREATE TABLE v15.tool_attempts (
  attempt_id uuid PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES v15.tool_requests (request_id),
  n int NOT NULL CHECK (n >= 1),
  status text NOT NULL CHECK (status IN ('leased', 'settled', 'failed', 'unknown')),
  fence bigint NOT NULL CHECK (fence >= 1),
  lease_owner text NULL,
  lease_until timestamptz NULL,
  pool_id uuid NULL REFERENCES v15.budget_pools (pool_id),
  reserved_calls int NOT NULL DEFAULT 1 CHECK (reserved_calls >= 1),
  reserved_cost numeric NOT NULL DEFAULT 0 CHECK (reserved_cost >= 0),
  call_started boolean NOT NULL DEFAULT false,
  calls_charged boolean NOT NULL DEFAULT false,
  result jsonb NULL,
  revision bigint NOT NULL DEFAULT 0,
  UNIQUE (request_id, n),
  CONSTRAINT tool_attempts_failed CHECK (
    status <> 'failed' OR (NOT call_started AND NOT calls_charged)
  ),
  CONSTRAINT tool_attempts_unknown CHECK (
    status <> 'unknown' OR (call_started AND calls_charged)
  ),
  CONSTRAINT tool_attempts_settled CHECK (
    status <> 'settled' OR (call_started AND calls_charged)
  ),
  CONSTRAINT tool_attempts_leased CHECK (
    status <> 'leased' OR NOT calls_charged
  )
);

CREATE UNIQUE INDEX tool_attempts_one_leased
  ON v15.tool_attempts (request_id)
  WHERE status = 'leased';

ALTER TABLE v15.tool_requests OWNER TO v15_owner;
ALTER TABLE v15.tool_attempts OWNER TO v15_owner;
ALTER INDEX v15.tool_attempts_one_leased OWNER TO v15_owner;

REVOKE ALL ON TABLE v15.tool_requests FROM PUBLIC, v15_repl, v15_worker, v15_bootstrap;
REVOKE ALL ON TABLE v15.tool_attempts FROM PUBLIC, v15_repl, v15_worker, v15_bootstrap;

CREATE OR REPLACE FUNCTION v15.v15_io_sqlstate(p_code text) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT CASE p_code
    WHEN 'V15_INVOKE_FORM' THEN 'P1503'
    WHEN 'V15_TOOL_UNAUTHORIZED' THEN 'P1507'
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
    WHEN 'V15_TOOL_BINDING' THEN 'P1543'
    WHEN 'V15_TOOL_FAILED' THEN 'P1544'
    WHEN 'V15_TOOL_EXHAUSTED' THEN 'P1545'
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
    'V15_REPLAY_MISSING',
    'V15_TOOL_BINDING',
    'V15_TOOL_FAILED',
    'V15_TOOL_EXHAUSTED'
  )
$fn$;

ALTER FUNCTION v15.v15_io_sqlstate(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_govern_known_code(text) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_io_sqlstate(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_govern_known_code(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v15.v15_io_sqlstate(text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_govern_known_code(text) TO v15_owner;

CREATE FUNCTION v15.jaz_bind_tool(name text, tool_name text, args jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  PERFORM v15.v15_exec_running();
  RAISE EXCEPTION 'V15_INVOKE_FORM' USING ERRCODE = 'P1503';
END;
$fn$;

CREATE FUNCTION jaz.bind_tool(name text, tool_name text, args jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN v15.jaz_bind_tool(name, tool_name, args);
END;
$fn$;

ALTER FUNCTION v15.jaz_bind_tool(text, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION jaz.bind_tool(text, text, jsonb) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.jaz_bind_tool(text, text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz.bind_tool(text, text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.jaz_bind_tool(text, text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz.bind_tool(text, text, jsonb) TO v15_repl;

CREATE FUNCTION v15.fake_search(p jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  RAISE EXCEPTION 'V15_EXTERNAL_TOOL' USING ERRCODE = 'P1517';
END;
$fn$;

ALTER FUNCTION v15.fake_search(jsonb) OWNER TO v15_tool_fake_search;
REVOKE ALL ON FUNCTION v15.fake_search(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.fake_search(jsonb) FROM v15_tool_fake_search;
GRANT EXECUTE ON FUNCTION v15.fake_search(jsonb) TO v15_owner;

SELECT v15.v15_register_tool(
  'fake_search',
  'v15.fake_search(jsonb)'::regprocedure,
  'Fake external search tool',
  '{}'::jsonb,
  true
);

CREATE OR REPLACE FUNCTION v15.v15_io_store_statements(
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
  v_tool text;
  v_nkeys integer;
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
    SELECT count(*)
      INTO v_nkeys
    FROM pg_catalog.jsonb_object_keys(v_elem) AS k(key);
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
    IF v_kind = 'bind_tool' THEN
      IF v_nkeys <> 7
         OR NOT pg_catalog.jsonb_exists(v_elem, 'tool_name')
         OR pg_catalog.jsonb_typeof(v_elem->'tool_name') <> 'string' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      v_tool := v_elem->>'tool_name';
      IF v_tool IS NULL OR v_tool !~ '^[a-z][a-z0-9_]{0,53}$' THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
    ELSE
      IF v_nkeys <> 6 THEN
        RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
      END IF;
      v_tool := NULL;
    END IF;
    IF v_sql IS NULL
       OR v_digest IS DISTINCT FROM pg_catalog.md5(v_sql)
       OR v_kind NOT IN (
         'plain', 'bind_invoke', 'return', 'raise', 'print', 'assign', 'bind_tool'
       )
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
    ELSIF v_kind = 'bind_tool' THEN
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
      bind_name, arg_sql, tool_name, status, error, error_sqlstate
    ) VALUES (
      p_invoke_id, p_iteration, v_i, v_sql, pg_catalog.md5(v_sql), v_kind,
      v_bind, v_arg, v_tool, v_status, v_err, v_err->>'sqlstate'
    );
  END LOOP;
  RETURN v_n;
END;
$fn$;

ALTER FUNCTION v15.v15_io_store_statements(uuid, integer, jsonb, boolean) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_io_store_statements(uuid, integer, jsonb, boolean) FROM PUBLIC;

CREATE OR REPLACE FUNCTION v15.v15_reject_bind_eval(p_ctx v15.exec_context) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  k text;
BEGIN
  SELECT s.kind INTO k
  FROM v15.statements s
  WHERE s.invoke_id = p_ctx.invoke_id
    AND s.iteration = p_ctx.iteration
    AND s.stmt_index = p_ctx.stmt_index;
  IF k IN ('bind_invoke', 'bind_tool') THEN
    RAISE EXCEPTION 'V15_INVOKE_FORM' USING ERRCODE = 'P1503';
  END IF;
END;
$fn$;

ALTER FUNCTION v15.v15_reject_bind_eval(v15.exec_context) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_reject_bind_eval(v15.exec_context) FROM PUBLIC;

CREATE FUNCTION v15.v15_suspend_for_tool(
  p_invoke_id uuid,
  p_iteration integer,
  p_stmt_index integer,
  p_owner text,
  p_args jsonb
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
  v_bind text;
  v_tool text;
  v_status text;
  v_cat v15.tool_catalog%ROWTYPE;
  v_reject text;
  v_err jsonb;
  v_req uuid;
  v_fence bigint;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_invoke_id IS NULL OR p_iteration IS NULL OR p_stmt_index IS NULL
     OR p_owner IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF p_args IS NULL OR pg_catalog.jsonb_typeof(p_args) <> 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  v_inv := v15.v15_repl_lock(p_invoke_id);
  PERFORM v15.v15_repl_check_holder(v_inv, v_inv.fence, p_owner);
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
  IF p_iteration IS DISTINCT FROM v_iter
     OR p_stmt_index IS DISTINCT FROM v_resume THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.kind, s.bind_name, s.tool_name, s.status
    INTO v_kind, v_bind, v_tool, v_status
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.error IS NULL
  FOR UPDATE;
  IF NOT FOUND
     OR v_status NOT IN ('pending', 'running')
     OR v_kind IS DISTINCT FROM 'bind_tool'
     OR v_bind IS NULL OR v_bind = ''
     OR v_tool IS NULL OR v_tool = '' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT c.* INTO v_cat
  FROM v15.tool_catalog c
  WHERE c.name = v_tool;
  IF NOT FOUND THEN
    v_reject := 'V15_TOOL_UNAUTHORIZED';
  ELSIF NOT EXISTS (
    SELECT 1
    FROM v15.bindings b
    JOIN v15.tool_grants g
      ON g.invoke_id = b.invoke_id AND g.tool_id = b.tool_id
    WHERE b.invoke_id = p_invoke_id
      AND b.name = v_tool
      AND b.kind = 'tool'
      AND b.tool_id = v_cat.tool_id
  ) THEN
    v_reject := 'V15_TOOL_UNAUTHORIZED';
  ELSIF NOT v_cat.external THEN
    v_reject := 'V15_TOOL_BINDING';
  END IF;
  IF v_reject IS NOT NULL THEN
    v_err := v15.v15_io_error(v_reject, '');
    UPDATE v15.statements s
    SET status = 'failed',
        error = v_err,
        error_sqlstate = v_err->>'sqlstate',
        revision = s.revision + 1
    WHERE s.invoke_id = p_invoke_id
      AND s.iteration = v_iter
      AND s.stmt_index = p_stmt_index;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    UPDATE v15.iterations i
    SET resume_stmt = p_stmt_index + 1,
        revision = i.revision + 1
    WHERE i.invoke_id = p_invoke_id
      AND i.iteration = v_iter;
    RETURN pg_catalog.jsonb_build_object('action', 'reject', 'code', v_reject);
  END IF;
  v_req := pg_catalog.gen_random_uuid();
  INSERT INTO v15.tool_requests (
    request_id, invoke_id, iteration, stmt_index, tool_id, bind_name,
    args, args_digest, status
  ) VALUES (
    v_req, p_invoke_id, v_iter, p_stmt_index, v_cat.tool_id, v_bind,
    p_args, pg_catalog.md5(p_args::text), 'open'
  );
  UPDATE v15.statements s
  SET status = 'running',
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_iter
    AND s.stmt_index = p_stmt_index
    AND s.status IN ('pending', 'running');
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
  SET status = 'tool_wait',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id
  RETURNING i.fence INTO v_fence;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'tool_suspend',
      'request_id', v_req,
      'bind_name', v_bind,
      'tool_name', v_tool,
      'stmt_index', p_stmt_index
    ),
    v_fence
  );
  RETURN pg_catalog.jsonb_build_object(
    'action', 'wait',
    'request_id', v_req
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

ALTER FUNCTION v15.v15_suspend_for_tool(uuid, integer, integer, text, jsonb) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_suspend_for_tool(uuid, integer, integer, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v15.v15_suspend_for_tool(uuid, integer, integer, text, jsonb) TO v15_worker;

-- D24: bind_tool arg_sql is evaluated in scratch, same as bind_invoke.
-- USAGE without CREATE so INSERT/SELECT INTO cannot succeed during eval.
CREATE OR REPLACE FUNCTION v15.v15_prepare_statement(
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
  PERFORM v15.v15_repl_grant_scratch(
    v_scratch,
    v_kind IS DISTINCT FROM 'bind_invoke'
      AND v_kind IS DISTINCT FROM 'bind_tool'
  );
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

CREATE FUNCTION v15.v15_tool_fail_wrap(
  p_invoke_id uuid,
  p_iteration integer,
  p_stmt_index integer,
  p_code text,
  p_fence bigint
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_err jsonb;
  v_capture text;
  v_block text;
  v_output text;
BEGIN
  v_err := v15.v15_io_error(p_code, '');
  UPDATE v15.statements s
  SET status = 'failed',
      error = v_err,
      error_sqlstate = v_err->>'sqlstate',
      revision = s.revision + 1
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = p_iteration
    AND s.stmt_index = p_stmt_index;
  PERFORM v15.v15_repl_skip_after(p_invoke_id, p_iteration, p_stmt_index);
  SELECT it.capture INTO v_capture
  FROM v15.iterations it
  WHERE it.invoke_id = p_invoke_id
    AND it.iteration = p_iteration;
  v_block := '[v15 exception ' || p_code || ']' || E'\n';
  IF v_capture = '' THEN
    v_output := v_block;
  ELSE
    v_output := v_capture || E'\n' || v_block;
  END IF;
  UPDATE v15.iterations i
  SET status = 'done',
      result_kind = 'continue',
      revision = i.revision + 1
  WHERE i.invoke_id = p_invoke_id
    AND i.iteration = p_iteration;
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
         v_output,
         v_err;
  INSERT INTO v15.llm_messages (
    invoke_id, msg_seq, message_id, iteration, role, kind, content
  )
  SELECT p_invoke_id,
         coalesce((
           SELECT max(m.msg_seq) FROM v15.llm_messages m WHERE m.invoke_id = p_invoke_id
         ), -1) + 1,
         'iter:' || p_iteration::text || ':observation',
         p_iteration, 'user', 'observation', v_output;
  INSERT INTO v15.iterations (invoke_id, iteration, status, resume_stmt, capture)
  VALUES (p_invoke_id, p_iteration + 1, 'pending', 0, '');
  PERFORM v15.v15_repl_close_span(
    p_invoke_id, p_iteration, 'repl_exec', 'failed', p_fence
  );
  UPDATE v15.invokes i
  SET status = 'runnable',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = p_invoke_id;
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object('op', 'tool_failed', 'code', p_code),
    p_fence
  );
END;
$fn$;

CREATE FUNCTION v15.v15_next_tool() RETURNS SETOF uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  PERFORM v15.v15_repl_require_worker();
  RETURN QUERY
    SELECT i.invoke_id
    FROM v15.invokes i
    JOIN v15.tool_requests r
      ON r.invoke_id = i.invoke_id
     AND r.status = 'open'
    WHERE i.status = 'tool_wait'
      AND NOT EXISTS (
        SELECT 1
        FROM v15.tool_attempts a
        WHERE a.request_id = r.request_id
          AND a.status = 'leased'
      )
    ORDER BY i.invoke_id;
END;
$fn$;

CREATE FUNCTION v15.v15_begin_tool(
  p_invoke_id uuid,
  p_owner text,
  p_lease interval
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_inv v15.invokes;
  v_req v15.tool_requests;
  v_n integer;
  v_next integer;
  v_max_io integer;
  v_tool text;
  v_kind text;
  v_stmt_status text;
  v_child uuid;
  v_attempt uuid;
  v_until timestamptz;
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
  v_inv := v15.v15_repl_lock(p_invoke_id);
  IF v_inv.status IS DISTINCT FROM 'tool_wait' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO v_req
  FROM v15.tool_requests r
  WHERE r.invoke_id = p_invoke_id
    AND r.status = 'open'
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF (
    SELECT count(*)
    FROM v15.tool_requests r
    WHERE r.invoke_id = p_invoke_id
      AND r.status = 'open'
  ) <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.kind, s.status, s.child_invoke_id
    INTO v_kind, v_stmt_status, v_child
  FROM v15.statements s
  WHERE s.invoke_id = p_invoke_id
    AND s.iteration = v_req.iteration
    AND s.stmt_index = v_req.stmt_index
  FOR UPDATE;
  IF NOT FOUND
     OR v_kind IS DISTINCT FROM 'bind_tool'
     OR v_stmt_status IS DISTINCT FROM 'running'
     OR v_child IS NOT NULL THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM v15.tool_attempts a
    WHERE a.request_id = v_req.request_id
      AND a.status = 'leased'
  ) THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT coalesce(max(a.n), 0) + 1
    INTO v_next
  FROM v15.tool_attempts a
  WHERE a.request_id = v_req.request_id;
  v_max_io := v15.v15_baseline_max(p_invoke_id, 'governance_io');
  IF v_next > v_max_io THEN
    UPDATE v15.tool_requests r
    SET status = 'exhausted',
        revision = r.revision + 1
    WHERE r.request_id = v_req.request_id
      AND r.status = 'open';
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    PERFORM v15.v15_tool_fail_wrap(
      p_invoke_id, v_req.iteration, v_req.stmt_index,
      'V15_TOOL_EXHAUSTED', v_inv.fence
    );
    RETURN v15.v15_io_abort_result(false, 'V15_TOOL_EXHAUSTED');
  END IF;
  IF NOT v15.v15_io_pool_reserve(v_inv.pool_id, 1, 0) THEN
    UPDATE v15.tool_requests r
    SET status = 'failed',
        revision = r.revision + 1
    WHERE r.request_id = v_req.request_id
      AND r.status = 'open';
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    PERFORM v15.v15_io_terminal(
      p_invoke_id, v_req.iteration, 'V15_BUDGET_EXHAUSTED', true, NULL
    );
    RETURN v15.v15_io_abort_result(true, 'V15_BUDGET_EXHAUSTED');
  END IF;
  SELECT c.name INTO STRICT v_tool
  FROM v15.tool_catalog c
  WHERE c.tool_id = v_req.tool_id;
  v_attempt := pg_catalog.gen_random_uuid();
  v_until := pg_catalog.clock_timestamp() + p_lease;
  INSERT INTO v15.tool_attempts (
    attempt_id, request_id, n, status, fence, lease_owner, lease_until,
    pool_id, reserved_calls, reserved_cost, call_started, calls_charged
  ) VALUES (
    v_attempt, v_req.request_id, v_next, 'leased', 1, p_owner, v_until,
    v_inv.pool_id, 1, 0, false, false
  );
  PERFORM v15.v15_repl_event(
    p_invoke_id, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'attempt_leased', 'attempt_id', v_attempt, 'n', v_next
    ),
    v_inv.fence
  );
  RETURN pg_catalog.jsonb_build_object(
    'action', 'proceed',
    'attempt_id', v_attempt,
    'n', v_next,
    'tool_name', v_tool,
    'args', v_req.args,
    'args_digest', v_req.args_digest
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE FUNCTION v15.v15_mark_tool_started(
  p_attempt_id uuid,
  p_fence bigint,
  p_owner text
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iter integer;
  v_stmt integer;
  v_inv v15.invokes;
  v_att v15.tool_attempts;
  v_kind text;
  v_stmt_status text;
  v_n integer;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id, r.iteration, r.stmt_index
    INTO v_invoke, v_iter, v_stmt
  FROM v15.tool_attempts a
  JOIN v15.tool_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT * INTO v_inv
  FROM v15.invokes i
  WHERE i.invoke_id = v_invoke
  FOR UPDATE;
  SELECT * INTO v_att
  FROM v15.tool_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.fence IS DISTINCT FROM p_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  IF v_att.lease_owner IS DISTINCT FROM p_owner
     OR v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_inv.status IS DISTINCT FROM 'tool_wait' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.kind, s.status INTO v_kind, v_stmt_status
  FROM v15.statements s
  WHERE s.invoke_id = v_invoke
    AND s.iteration = v_iter
    AND s.stmt_index = v_stmt;
  IF v_kind IS DISTINCT FROM 'bind_tool'
     OR v_stmt_status IS DISTINCT FROM 'running' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  UPDATE v15.tool_attempts a
  SET call_started = true,
      revision = a.revision + 1
  WHERE a.attempt_id = p_attempt_id
    AND a.status = 'leased'
    AND NOT a.call_started
    AND a.fence = p_fence;
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

CREATE FUNCTION v15.v15_settle_tool(
  p_attempt_id uuid,
  p_fence bigint,
  p_owner text,
  p_result jsonb
) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_invoke uuid;
  v_iter integer;
  v_stmt integer;
  v_name text;
  v_inv v15.invokes;
  v_att v15.tool_attempts;
  v_ok boolean;
  v_value jsonb;
  v_kind text;
  v_n integer;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  IF p_attempt_id IS NULL OR p_fence IS NULL OR p_owner IS NULL
     OR p_result IS NULL
     OR pg_catalog.char_length(p_owner) < 1
     OR pg_catalog.char_length(p_owner) > 200 THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT r.invoke_id, r.iteration, r.stmt_index, r.bind_name
    INTO v_invoke, v_iter, v_stmt, v_name
  FROM v15.tool_attempts a
  JOIN v15.tool_requests r ON r.request_id = a.request_id
  WHERE a.attempt_id = p_attempt_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  v_inv := v15.v15_repl_lock(v_invoke);
  SELECT * INTO v_att
  FROM v15.tool_attempts a
  WHERE a.attempt_id = p_attempt_id
  FOR UPDATE;
  IF v_att.status IN ('unknown', 'failed', 'settled') THEN
    RAISE EXCEPTION 'V15_ATTEMPT_NOT_SETTLEABLE' USING ERRCODE = 'P1502';
  END IF;
  IF v_att.status IS DISTINCT FROM 'leased' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_att.fence IS DISTINCT FROM p_fence THEN
    RAISE EXCEPTION 'V15_STALE_FENCE' USING ERRCODE = 'P1501';
  END IF;
  IF v_att.lease_owner IS DISTINCT FROM p_owner THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF NOT v_att.call_started THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF v_inv.status IS DISTINCT FROM 'tool_wait' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF pg_catalog.jsonb_typeof(p_result) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  IF (p_result->'ok') = 'true'::jsonb
     AND pg_catalog.jsonb_exists(p_result, 'value')
     AND p_result = pg_catalog.jsonb_build_object(
       'ok', true, 'value', p_result->'value'
     ) THEN
    v_ok := true;
    v_value := p_result->'value';
  ELSIF p_result = '{"ok": false}'::jsonb THEN
    v_ok := false;
    v_value := NULL;
  ELSE
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_io_pool_release(
    v_att.pool_id, v_att.reserved_calls, v_att.reserved_cost, true, 0
  );
  UPDATE v15.tool_attempts a
  SET status = 'settled',
      calls_charged = true,
      lease_owner = NULL,
      lease_until = NULL,
      result = p_result,
      revision = a.revision + 1
  WHERE a.attempt_id = p_attempt_id
    AND a.status = 'leased'
    AND a.call_started
    AND NOT a.calls_charged;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  IF NOT v_ok THEN
    UPDATE v15.tool_requests r
    SET status = 'failed',
        revision = r.revision + 1
    WHERE r.request_id = v_att.request_id
      AND r.status = 'open';
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    PERFORM v15.v15_tool_fail_wrap(
      v_invoke, v_iter, v_stmt, 'V15_TOOL_FAILED', v_inv.fence
    );
    RETURN;
  END IF;
  UPDATE v15.tool_requests r
  SET status = 'settled',
      revision = r.revision + 1
  WHERE r.request_id = v_att.request_id
    AND r.status = 'open';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT b.kind INTO v_kind
  FROM v15.bindings b
  WHERE b.invoke_id = v_invoke
    AND b.name = v_name;
  IF FOUND AND v_kind IN ('input', 'scope', 'tool') THEN
    PERFORM v15.v15_tool_fail_wrap(
      v_invoke, v_iter, v_stmt, 'V15_DELIVERY_CONFLICT', v_inv.fence
    );
    RETURN;
  END IF;
  IF FOUND THEN
    UPDATE v15.bindings b
    SET value = v_value,
        provenance = 'delivery',
        revision = b.revision + 1
    WHERE b.invoke_id = v_invoke
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
      v_invoke, v_name, 'var', v_value, true, 'delivery'
    );
  END IF;
  UPDATE v15.statements s
  SET status = 'done',
      error = NULL,
      error_sqlstate = NULL,
      revision = s.revision + 1
  WHERE s.invoke_id = v_invoke
    AND s.iteration = v_iter
    AND s.stmt_index = v_stmt
    AND s.status = 'running';
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  UPDATE v15.iterations i
  SET status = 'executing',
      resume_stmt = v_stmt + 1,
      revision = i.revision + 1
  WHERE i.invoke_id = v_invoke
    AND i.iteration = v_iter;
  UPDATE v15.invokes i
  SET status = 'runnable',
      lease_owner = NULL,
      lease_until = NULL,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = v_invoke;
  PERFORM v15.v15_repl_event(
    v_invoke, 'audit', NULL, NULL, NULL,
    pg_catalog.jsonb_build_object(
      'op', 'deliver',
      'bind_name', v_name,
      'request_id', v_att.request_id
    ),
    v_inv.fence
  );
EXCEPTION
  WHEN lock_not_available THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
END;
$fn$;

CREATE OR REPLACE FUNCTION v15.v15_io_reclaim_invoke(p_invoke_id uuid) RETURNS void
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
  IF EXISTS (
    SELECT 1
    FROM v15.invokes i
    WHERE i.invoke_id = p_invoke_id
      AND i.status = 'tool_wait'
  ) OR EXISTS (
    SELECT 1
    FROM v15.statements s
    WHERE s.invoke_id = p_invoke_id
      AND s.status = 'running'
      AND s.kind = 'bind_tool'
  ) THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
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

CREATE OR REPLACE FUNCTION v15.v15_reclaim_expired() RETURNS integer
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_tool_attempt_ids uuid[] := '{}'::uuid[];
  v_tool_seed uuid[] := '{}'::uuid[];
  v_attempt_ids uuid[] := '{}'::uuid[];
  v_seed_ids uuid[] := '{}'::uuid[];
  v_terminated uuid[] := '{}'::uuid[];
  v_candidates uuid[] := '{}'::uuid[];
  v_attempt uuid;
  v_invoke uuid;
  v_tatt v15.tool_attempts;
  v_att v15.llm_attempts;
  v_status text;
  v_fence bigint;
  v_count integer := 0;
  v_id uuid;
BEGIN
  PERFORM v15.v15_repl_require_worker();
  SELECT coalesce(pg_catalog.array_agg(a.attempt_id ORDER BY a.attempt_id), '{}'::uuid[]),
         coalesce(pg_catalog.array_agg(DISTINCT r.invoke_id), '{}'::uuid[])
    INTO v_tool_attempt_ids, v_tool_seed
  FROM v15.tool_attempts a
  JOIN v15.tool_requests r ON r.request_id = a.request_id
  WHERE a.status = 'leased'
    AND a.lease_until <= pg_catalog.clock_timestamp();
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
      SELECT pg_catalog.unnest(v_tool_seed) AS invoke_id
      UNION
      SELECT pg_catalog.unnest(v_seed_ids)
      UNION
      SELECT pg_catalog.unnest(v_candidates)
    ) s
  );
  IF cardinality(v_tool_attempt_ids) = 0
     AND cardinality(v_attempt_ids) = 0
     AND cardinality(v_seed_ids) = 0 THEN
    RETURN 0;
  END IF;
  PERFORM v15.v15_io_lock_ids(v_seed_ids);
  FOREACH v_attempt IN ARRAY v_tool_attempt_ids LOOP
    SELECT a.* INTO v_tatt
    FROM v15.tool_attempts a
    WHERE a.attempt_id = v_attempt
      AND a.status = 'leased'
      AND a.lease_until <= pg_catalog.clock_timestamp()
    FOR UPDATE;
    IF NOT FOUND THEN
      CONTINUE;
    END IF;
    SELECT r.invoke_id, i.fence
      INTO v_invoke, v_fence
    FROM v15.tool_requests r
    JOIN v15.invokes i ON i.invoke_id = r.invoke_id
    WHERE r.request_id = v_tatt.request_id;
    IF v_tatt.call_started THEN
      v_status := 'unknown';
      PERFORM v15.v15_io_pool_release(
        v_tatt.pool_id, v_tatt.reserved_calls, v_tatt.reserved_cost, true, 0
      );
      UPDATE v15.tool_attempts a
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
        v_tatt.pool_id, v_tatt.reserved_calls, v_tatt.reserved_cost, false, 0
      );
      UPDATE v15.tool_attempts a
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
      v_invoke, 'audit', NULL, NULL, NULL,
      pg_catalog.jsonb_build_object(
        'op', 'tool_retry',
        'attempt_id', v_attempt,
        'old_status', v_status
      ),
      v_fence
    );
    v_count := v_count + 1;
  END LOOP;
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

ALTER FUNCTION v15.v15_prepare_statement(uuid, bigint, text, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_tool_fail_wrap(uuid, integer, integer, text, bigint) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_next_tool() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_begin_tool(uuid, text, interval) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_mark_tool_started(uuid, bigint, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_settle_tool(uuid, bigint, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_io_reclaim_invoke(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_reclaim_expired() OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_prepare_statement(uuid, bigint, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_tool_fail_wrap(uuid, integer, integer, text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_next_tool() FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_begin_tool(uuid, text, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_mark_tool_started(uuid, bigint, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_settle_tool(uuid, bigint, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_io_reclaim_invoke(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_reclaim_expired() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v15.v15_prepare_statement(uuid, bigint, text, integer) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_next_tool() TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_begin_tool(uuid, text, interval) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_mark_tool_started(uuid, bigint, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_settle_tool(uuid, bigint, text, jsonb) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_reclaim_expired() TO v15_worker;

-- No v15_replay_import in v15_replay.sql; Python load_trace already
-- rejects bind_tool via STMT_KIND. Export rejects bind_tool/tool_wait as P1524.
CREATE OR REPLACE FUNCTION v15.v15_replay_export(p_root uuid) RETURNS jsonb
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
  IF EXISTS (
    SELECT 1
    FROM v15.invokes i
    WHERE i.invoke_id = ANY (v_ids)
      AND i.status = 'tool_wait'
  ) OR EXISTS (
    SELECT 1
    FROM v15.statements s
    WHERE s.invoke_id = ANY (v_ids)
      AND s.kind = 'bind_tool'
  ) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
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

ALTER FUNCTION v15.v15_replay_export(uuid) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_replay_export(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v15.v15_replay_export(uuid) TO v15_worker;
