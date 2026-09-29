CREATE SCHEMA v15 AUTHORIZATION v15_owner;
CREATE SCHEMA jaz AUTHORIZATION v15_owner;

REVOKE ALL ON SCHEMA v15 FROM PUBLIC;
REVOKE ALL ON SCHEMA jaz FROM PUBLIC;
GRANT USAGE ON SCHEMA v15 TO v15_worker, v15_repl, v15_bootstrap;
GRANT USAGE ON SCHEMA jaz TO v15_worker, v15_repl, v15_bootstrap;

DO $do$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM v15_repl', current_database());
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM v15_worker', current_database());
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM v15_bootstrap', current_database());
END
$do$;

DO $do$
DECLARE
  fn regprocedure;
BEGIN
  FOR fn IN
    SELECT p.oid::regprocedure
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'pg_catalog'
      AND (
        p.proname IN (
          'set_config', 'pg_sleep', 'pg_sleep_for', 'pg_sleep_until',
          'pg_read_file', 'pg_read_binary_file', 'pg_ls_dir', 'pg_stat_file',
          'pg_terminate_backend', 'pg_cancel_backend', 'lo_import', 'lo_export'
        )
        OR p.proname LIKE 'pg\_advisory%'
        OR p.proname LIKE 'pg\_try\_advisory%'
      )
  LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM v15_repl', fn);
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM v15_worker', fn);
  END LOOP;
  EXECUTE 'GRANT EXECUTE ON FUNCTION pg_catalog.pg_cancel_backend(integer) TO v15_worker';
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proname = 'dblink'
  ) THEN
    FOR fn IN
      SELECT p.oid::regprocedure
      FROM pg_catalog.pg_proc p
      JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
      WHERE p.proname LIKE 'dblink%'
    LOOP
      EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
      EXECUTE format('REVOKE ALL ON FUNCTION %s FROM v15_repl', fn);
      EXECUTE format('REVOKE ALL ON FUNCTION %s FROM v15_worker', fn);
    END LOOP;
  END IF;
END
$do$;

CREATE TABLE v15.budget_pools (
  pool_id uuid PRIMARY KEY,
  calls_limit int NULL CHECK (calls_limit IS NULL OR calls_limit >= 1),
  cost_limit numeric NULL CHECK (cost_limit IS NULL OR cost_limit >= 0),
  calls_used int NOT NULL DEFAULT 0 CHECK (calls_used >= 0),
  calls_reserved int NOT NULL DEFAULT 0 CHECK (calls_reserved >= 0),
  cost_used numeric NOT NULL DEFAULT 0 CHECK (cost_used >= 0),
  cost_reserved numeric NOT NULL DEFAULT 0 CHECK (cost_reserved >= 0),
  revision bigint NOT NULL DEFAULT 0
);

CREATE TABLE v15.tool_catalog (
  tool_id uuid PRIMARY KEY,
  name text NOT NULL UNIQUE,
  arg_schema jsonb NOT NULL,
  handler oid NOT NULL,
  description text NOT NULL,
  external boolean NOT NULL DEFAULT false,
  handler_digest text NOT NULL,
  CONSTRAINT tool_catalog_name CHECK (name ~ '^[a-z][a-z0-9_]{0,53}$')
);

CREATE TABLE v15.config_profiles (
  profile_id uuid PRIMARY KEY,
  llm jsonb NOT NULL,
  repl jsonb NOT NULL,
  protocol jsonb NOT NULL,
  baseline_hooks jsonb NOT NULL,
  profile_digest text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE v15.config_scopes (
  scope_id uuid PRIMARY KEY,
  profile_id uuid NOT NULL REFERENCES v15.config_profiles (profile_id),
  scope_digest text NOT NULL
);

CREATE TABLE v15.config_layers (
  layer_id uuid PRIMARY KEY,
  scope_id uuid NULL REFERENCES v15.config_scopes (scope_id),
  ordinal int NOT NULL CHECK (ordinal >= 0),
  kind text NOT NULL CHECK (kind IN ('plain', 'depth')),
  llm jsonb NULL,
  repl jsonb NULL,
  protocol jsonb NULL,
  depth_map jsonb NULL,
  extra_hooks jsonb NULL,
  layer_digest text NOT NULL,
  CONSTRAINT config_layers_plain CHECK (kind <> 'plain' OR depth_map IS NULL),
  CONSTRAINT config_layers_depth CHECK (
    kind <> 'depth'
    OR (llm IS NULL AND repl IS NULL AND protocol IS NULL AND depth_map IS NOT NULL)
  ),
  CONSTRAINT config_layers_local CHECK (scope_id IS NOT NULL OR kind = 'plain')
);

CREATE UNIQUE INDEX config_layers_scope_ordinal_key
  ON v15.config_layers (scope_id, ordinal)
  WHERE scope_id IS NOT NULL;

CREATE TABLE v15.governance_manifest (
  manifest_id smallint PRIMARY KEY CHECK (manifest_id = 1),
  max_iterations int NOT NULL CHECK (max_iterations >= 1),
  max_depth int NOT NULL CHECK (max_depth >= 1),
  max_io_attempts int NOT NULL CHECK (max_io_attempts >= 1),
  max_statement_ms int NOT NULL CHECK (max_statement_ms >= 1),
  manifest_digest text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE v15.invokes (
  invoke_id uuid PRIMARY KEY,
  parent_invoke_id uuid NULL REFERENCES v15.invokes (invoke_id),
  parent_iteration int NULL CHECK (parent_iteration >= 0),
  root_invoke_id uuid NOT NULL,
  depth int NOT NULL CHECK (depth >= 1),
  status text NOT NULL CHECK (status IN (
    'pending', 'runnable', 'leased', 'suspended',
    'completed', 'failed', 'aborted'
  )),
  return_value jsonb NULL,
  error jsonb NULL,
  fatal boolean NOT NULL DEFAULT false,
  recursion_available boolean NOT NULL,
  resolved_config jsonb NOT NULL,
  config_digest text NOT NULL,
  config_scope_id uuid NULL,
  local_layer_id uuid NULL,
  pool_id uuid NULL REFERENCES v15.budget_pools (pool_id),
  manifest_digest text NOT NULL,
  scratch_schema text NOT NULL UNIQUE,
  fence bigint NOT NULL CHECK (fence >= 1),
  lease_owner text NULL,
  lease_until timestamptz NULL,
  revision bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT invokes_parent_pair CHECK (
    (parent_invoke_id IS NULL) = (parent_iteration IS NULL)
  ),
  CONSTRAINT invokes_lease CHECK (
    (status = 'leased' AND lease_owner IS NOT NULL AND lease_until IS NOT NULL)
    OR (status <> 'leased' AND lease_owner IS NULL AND lease_until IS NULL)
  ),
  CONSTRAINT invokes_completed CHECK (
    status <> 'completed'
    OR (return_value IS NOT NULL AND error IS NULL AND NOT fatal)
  ),
  CONSTRAINT invokes_failed CHECK (
    status <> 'failed' OR (error IS NOT NULL AND NOT fatal)
  ),
  CONSTRAINT invokes_aborted CHECK (
    status <> 'aborted' OR (error IS NOT NULL AND fatal)
  ),
  CONSTRAINT invokes_scratch_schema CHECK (scratch_schema ~ '^s_[0-9a-f]{32}$')
);

CREATE UNIQUE INDEX invokes_local_layer_id_key
  ON v15.invokes (local_layer_id)
  WHERE local_layer_id IS NOT NULL;

CREATE TABLE v15.iterations (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  iteration int NOT NULL CHECK (iteration >= 0),
  status text NOT NULL CHECK (status IN (
    'pending', 'llm', 'executing', 'suspended', 'done'
  )),
  resume_stmt int NOT NULL DEFAULT 0 CHECK (resume_stmt >= 0),
  result_kind text NULL CHECK (result_kind IN ('continue', 'return', 'raise')),
  capture text NOT NULL DEFAULT '',
  revision bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, iteration),
  CONSTRAINT iterations_done_result CHECK (
    (status = 'done') = (result_kind IS NOT NULL)
  )
);

CREATE TABLE v15.statements (
  invoke_id uuid NOT NULL,
  iteration int NOT NULL,
  stmt_index int NOT NULL CHECK (stmt_index >= 0),
  sql text NOT NULL,
  sql_digest text NOT NULL,
  kind text NOT NULL CHECK (kind IN (
    'plain', 'bind_invoke', 'return', 'raise', 'print', 'assign'
  )),
  bind_name text NULL,
  arg_sql text NULL,
  status text NOT NULL CHECK (status IN (
    'pending', 'running', 'done', 'failed', 'skipped'
  )),
  child_invoke_id uuid NULL REFERENCES v15.invokes (invoke_id),
  error_sqlstate text NULL,
  error jsonb NULL,
  revision bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, iteration, stmt_index),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES v15.iterations (invoke_id, iteration),
  CONSTRAINT statements_bind_name CHECK (
    kind <> 'bind_invoke' OR bind_name IS NOT NULL
  ),
  CONSTRAINT statements_error_sqlstate CHECK (
    error_sqlstate IS NOT DISTINCT FROM (error->>'sqlstate')
  ),
  CONSTRAINT statements_sql_digest CHECK (sql_digest = md5(sql))
);

CREATE TABLE v15.llm_requests (
  request_id uuid PRIMARY KEY,
  invoke_id uuid NOT NULL,
  iteration int NOT NULL,
  status text NOT NULL CHECK (status IN ('open', 'settled', 'exhausted')),
  logical_digest text NOT NULL,
  revision bigint NOT NULL DEFAULT 0,
  UNIQUE (invoke_id, iteration),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES v15.iterations (invoke_id, iteration)
);

CREATE TABLE v15.llm_attempts (
  attempt_id uuid PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES v15.llm_requests (request_id),
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
  request jsonb NOT NULL,
  response jsonb NULL,
  prompt_tokens int NULL CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
  cost_usd numeric NULL CHECK (cost_usd IS NULL OR cost_usd >= 0),
  revision bigint NOT NULL DEFAULT 0,
  UNIQUE (request_id, n),
  CONSTRAINT llm_attempts_failed CHECK (
    status <> 'failed' OR (NOT call_started AND NOT calls_charged)
  ),
  CONSTRAINT llm_attempts_unknown CHECK (
    status <> 'unknown' OR (call_started AND calls_charged)
  ),
  CONSTRAINT llm_attempts_settled CHECK (
    status <> 'settled' OR (call_started AND calls_charged)
  ),
  CONSTRAINT llm_attempts_leased CHECK (
    status <> 'leased' OR NOT calls_charged
  )
);

CREATE TABLE v15.llm_messages (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  msg_seq bigint NOT NULL CHECK (msg_seq >= 0),
  message_id text NOT NULL,
  iteration int NULL CHECK (iteration IS NULL OR iteration >= 0),
  role text NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
  kind text NOT NULL CHECK (kind IN (
    'seed', 'assistant', 'observation', 'persistent_hook'
  )),
  content text NOT NULL,
  PRIMARY KEY (invoke_id, msg_seq),
  UNIQUE (invoke_id, message_id),
  CONSTRAINT llm_messages_seed_iteration CHECK (
    kind <> 'seed' OR iteration IS NULL
  )
);

CREATE TABLE v15.repl_history (
  invoke_id uuid NOT NULL,
  iteration int NOT NULL CHECK (iteration >= 0),
  llm_response text NOT NULL,
  repl_output text NOT NULL,
  repl_exception jsonb NULL,
  PRIMARY KEY (invoke_id, iteration),
  FOREIGN KEY (invoke_id, iteration)
    REFERENCES v15.iterations (invoke_id, iteration)
);

CREATE TABLE v15.bindings (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('input', 'scope', 'var', 'tool')),
  value jsonb NOT NULL,
  tool_id uuid NULL REFERENCES v15.tool_catalog (tool_id),
  show_in_prompt boolean NOT NULL,
  provenance text NOT NULL CHECK (provenance IN (
    'explicit', 'scope', 'hook', 'repl', 'delivery'
  )),
  revision bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, name),
  CONSTRAINT bindings_tool_pair CHECK ((kind = 'tool') = (tool_id IS NOT NULL)),
  CONSTRAINT bindings_name CHECK (
    name ~ '^[A-Za-z_][A-Za-z0-9_]*$'
    AND char_length(name) BETWEEN 1 AND 63
    AND name <> ALL (ARRAY[
      '__history__', 'history', 'request_messages', 'return', 'raise', 'print',
      'assign', 'var', 'tool', 'bind_invoke', 'prior_history', 'exec_context',
      'invoke_id', 'iteration'
    ])
  )
);

CREATE TABLE v15.exec_context (
  backend_pid int PRIMARY KEY,
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  iteration int NOT NULL,
  stmt_index int NOT NULL,
  scratch_schema text NOT NULL,
  revision bigint NOT NULL DEFAULT 0
);

CREATE TABLE v15.invoke_events (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  seq bigint NOT NULL CHECK (seq >= 0),
  event_class text NOT NULL CHECK (event_class IN ('span', 'audit')),
  span text NULL CHECK (span IN ('invoke', 'llm_query', 'repl_exec')),
  phase text NULL CHECK (phase IN ('enter', 'send', 'complete', 'exit', 'retry')),
  outcome text NULL CHECK (outcome IN ('completed', 'aborted', 'failed')),
  payload jsonb NOT NULL,
  fence bigint NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (invoke_id, seq),
  CONSTRAINT invoke_events_shape CHECK (
    (
      event_class = 'audit'
      AND span IS NULL AND phase IS NULL AND outcome IS NULL
    )
    OR (
      event_class = 'span'
      AND span IS NOT NULL
      AND phase IS NOT NULL
      AND (
        (phase = 'exit' AND outcome IS NOT NULL)
        OR (phase = 'retry')
        OR (phase NOT IN ('exit', 'retry') AND outcome IS NULL)
      )
    )
  )
);

CREATE TABLE v15.hook_defs (
  hook_def_id uuid PRIMARY KEY,
  hook_key text NOT NULL UNIQUE,
  regprocedure oid NOT NULL,
  owner_role oid NOT NULL,
  baseline_required boolean NOT NULL,
  handler_digest text NOT NULL,
  search_path text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT hook_defs_hook_key CHECK (hook_key ~ '^[a-z][a-z0-9_]{0,53}$')
);

CREATE TABLE v15.invoke_hooks (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  ordinal int NOT NULL CHECK (ordinal >= 0),
  hook_def_id uuid NOT NULL REFERENCES v15.hook_defs (hook_def_id),
  channel text NOT NULL CHECK (channel IN ('baseline', 'propagating', 'local')),
  config jsonb NOT NULL,
  state jsonb NOT NULL,
  revision bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, ordinal),
  CONSTRAINT invoke_hooks_state CHECK (channel = 'baseline' OR state = '{}'::jsonb)
);

CREATE TABLE v15.blackboard (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  key text NOT NULL,
  value jsonb NOT NULL,
  generation bigint NOT NULL CHECK (generation >= 0),
  revision bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, key)
);

CREATE TABLE v15.hook_counters (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  counter_key text NOT NULL,
  n bigint NOT NULL DEFAULT 0 CHECK (n >= 0),
  revision bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (invoke_id, counter_key)
);

CREATE TABLE v15.tool_grants (
  invoke_id uuid NOT NULL REFERENCES v15.invokes (invoke_id),
  tool_id uuid NOT NULL REFERENCES v15.tool_catalog (tool_id),
  PRIMARY KEY (invoke_id, tool_id)
);

DO $do$
DECLARE
  rel regclass;
BEGIN
  FOR rel IN
    SELECT c.oid::regclass
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'v15' AND c.relkind = 'r'
  LOOP
    EXECUTE format('ALTER TABLE %s OWNER TO v15_owner', rel);
  END LOOP;
  FOR rel IN
    SELECT c.oid::regclass
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'v15' AND c.relkind = 'i'
  LOOP
    EXECUTE format('ALTER INDEX %s OWNER TO v15_owner', rel);
  END LOOP;
END
$do$;

REVOKE ALL ON ALL TABLES IN SCHEMA v15 FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA v15 FROM v15_repl, v15_worker, v15_bootstrap;

CREATE FUNCTION v15.invoke_events_append_only() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $fn$
BEGIN
  RAISE EXCEPTION 'invoke_events is append-only' USING ERRCODE = '55000';
END;
$fn$;

CREATE TRIGGER invoke_events_no_update
  BEFORE UPDATE ON v15.invoke_events
  FOR EACH ROW EXECUTE FUNCTION v15.invoke_events_append_only();

CREATE TRIGGER invoke_events_no_delete
  BEFORE DELETE ON v15.invoke_events
  FOR EACH ROW EXECUTE FUNCTION v15.invoke_events_append_only();

CREATE TRIGGER invoke_events_no_truncate
  BEFORE TRUNCATE ON v15.invoke_events
  FOR EACH STATEMENT EXECUTE FUNCTION v15.invoke_events_append_only();

CREATE FUNCTION v15.invoke_events_seq_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $fn$
DECLARE
  expected bigint;
BEGIN
  SELECT coalesce(max(seq), -1) + 1 INTO expected
  FROM v15.invoke_events
  WHERE invoke_id = NEW.invoke_id;
  IF NEW.seq IS DISTINCT FROM expected THEN
    RAISE EXCEPTION 'invoke_events seq must be contiguous' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$fn$;

CREATE TRIGGER invoke_events_seq
  BEFORE INSERT ON v15.invoke_events
  FOR EACH ROW EXECUTE FUNCTION v15.invoke_events_seq_guard();

CREATE FUNCTION v15.llm_messages_immutable() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $fn$
BEGIN
  RAISE EXCEPTION 'llm_messages is immutable' USING ERRCODE = '55000';
END;
$fn$;

CREATE TRIGGER llm_messages_no_update
  BEFORE UPDATE ON v15.llm_messages
  FOR EACH ROW EXECUTE FUNCTION v15.llm_messages_immutable();

CREATE TRIGGER llm_messages_no_delete
  BEFORE DELETE ON v15.llm_messages
  FOR EACH ROW EXECUTE FUNCTION v15.llm_messages_immutable();

CREATE TRIGGER llm_messages_no_truncate
  BEFORE TRUNCATE ON v15.llm_messages
  FOR EACH STATEMENT EXECUTE FUNCTION v15.llm_messages_immutable();

CREATE FUNCTION v15.llm_messages_seq_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $fn$
DECLARE
  expected bigint;
BEGIN
  SELECT coalesce(max(msg_seq), -1) + 1 INTO expected
  FROM v15.llm_messages
  WHERE invoke_id = NEW.invoke_id;
  IF NEW.msg_seq IS DISTINCT FROM expected THEN
    RAISE EXCEPTION 'llm_messages msg_seq must be contiguous' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$fn$;

CREATE TRIGGER llm_messages_seq
  BEFORE INSERT ON v15.llm_messages
  FOR EACH ROW EXECUTE FUNCTION v15.llm_messages_seq_guard();

CREATE FUNCTION v15.governance_manifest_singleton() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $fn$
BEGIN
  RAISE EXCEPTION 'governance_manifest singleton' USING ERRCODE = '55000';
END;
$fn$;

CREATE TRIGGER governance_manifest_no_delete
  BEFORE DELETE ON v15.governance_manifest
  FOR EACH ROW EXECUTE FUNCTION v15.governance_manifest_singleton();

CREATE TRIGGER governance_manifest_no_truncate
  BEFORE TRUNCATE ON v15.governance_manifest
  FOR EACH STATEMENT EXECUTE FUNCTION v15.governance_manifest_singleton();

CREATE FUNCTION v15.invoke_hooks_baseline_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION 'V15_BASELINE_IMMUTABLE' USING ERRCODE = 'P1532';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.channel = 'baseline' THEN
    IF NEW.config IS DISTINCT FROM OLD.config
       OR NEW.channel IS DISTINCT FROM OLD.channel
       OR NEW.hook_def_id IS DISTINCT FROM OLD.hook_def_id
       OR NEW.ordinal IS DISTINCT FROM OLD.ordinal THEN
      RAISE EXCEPTION 'V15_BASELINE_IMMUTABLE' USING ERRCODE = 'P1532';
    END IF;
  END IF;
  RETURN NEW;
END;
$fn$;

CREATE TRIGGER invoke_hooks_no_delete
  BEFORE DELETE ON v15.invoke_hooks
  FOR EACH ROW EXECUTE FUNCTION v15.invoke_hooks_baseline_guard();

CREATE TRIGGER invoke_hooks_no_truncate
  BEFORE TRUNCATE ON v15.invoke_hooks
  FOR EACH STATEMENT EXECUTE FUNCTION v15.invoke_hooks_baseline_guard();

CREATE TRIGGER invoke_hooks_baseline
  BEFORE UPDATE ON v15.invoke_hooks
  FOR EACH ROW EXECUTE FUNCTION v15.invoke_hooks_baseline_guard();

CREATE FUNCTION v15.v15_handler_digest(p_fn oid) RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT md5(
    pg_catalog.pg_get_functiondef(p.oid) || E'\n'
    || pg_catalog.pg_get_userbyid(p.proowner) || E'\n'
    || p.provolatile::text || E'\n'
    || CASE WHEN p.prosecdef THEN 'true' ELSE 'false' END || E'\n'
    || l.lanname || E'\n'
    || coalesce(p.proconfig::text, '') || E'\n'
    || coalesce((
      SELECT string_agg(x::text, ',' ORDER BY x::text)
      FROM unnest(p.proacl) AS x
    ), '')
  )
  FROM pg_catalog.pg_proc p
  JOIN pg_catalog.pg_language l ON l.oid = p.prolang
  WHERE p.oid = p_fn
$fn$;

CREATE FUNCTION v15.v15_assert_handler_shape(
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
  owner_login boolean;
  owner_super boolean;
  lang text;
  digest text;
  acl_bad boolean;
  acl_ok int;
BEGIN
  SELECT * INTO proc FROM pg_catalog.pg_proc WHERE oid = p_fn;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: missing function' USING ERRCODE = 'P1537';
  END IF;
  SELECT r.rolname, r.rolcanlogin, r.rolsuper
    INTO owner_name, owner_login, owner_super
  FROM pg_catalog.pg_roles r
  WHERE r.oid = proc.proowner;
  SELECT l.lanname INTO lang
  FROM pg_catalog.pg_language l
  WHERE l.oid = proc.prolang;
  IF proc.provolatile IS DISTINCT FROM 's'
     OR lang NOT IN ('sql', 'plpgsql')
     OR NOT proc.prosecdef
     OR owner_login
     OR owner_super
     OR owner_name IS DISTINCT FROM p_owner_name
     OR p_owner_name !~ '^v15_(hook|tool)_[a-z][a-z0-9_]{0,53}$'
     OR proc.pronargs <> 1
     OR proc.proargtypes[0] IS DISTINCT FROM 'jsonb'::regtype
     OR proc.prorettype IS DISTINCT FROM 'jsonb'::regtype
     OR proc.proargmodes IS NOT NULL
     OR proc.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[] THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: contract' USING ERRCODE = 'P1537';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('v15', 'jaz')
      AND c.relkind IN ('r', 'p')
      AND (
        has_table_privilege(proc.proowner, c.oid, 'SELECT')
        OR has_table_privilege(proc.proowner, c.oid, 'INSERT')
        OR has_table_privilege(proc.proowner, c.oid, 'UPDATE')
        OR has_table_privilege(proc.proowner, c.oid, 'DELETE')
        OR has_table_privilege(proc.proowner, c.oid, 'TRUNCATE')
        OR has_table_privilege(proc.proowner, c.oid, 'REFERENCES')
        OR has_table_privilege(proc.proowner, c.oid, 'TRIGGER')
      )
  ) THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: table privilege' USING ERRCODE = 'P1537';
  END IF;
  IF proc.proacl IS NULL THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: null acl' USING ERRCODE = 'P1537';
  END IF;
  SELECT EXISTS (
    SELECT 1
    FROM aclexplode(proc.proacl) a
    WHERE a.grantee <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'v15_owner')
       OR a.privilege_type <> 'EXECUTE'
       OR a.is_grantable
  ) INTO acl_bad;
  SELECT count(*) INTO acl_ok
  FROM aclexplode(proc.proacl) a
  WHERE a.privilege_type = 'EXECUTE'
    AND NOT a.is_grantable
    AND a.grantee = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'v15_owner');
  IF acl_bad OR acl_ok <> 1 THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: acl' USING ERRCODE = 'P1537';
  END IF;
  digest := v15.v15_handler_digest(p_fn);
  IF digest IS DISTINCT FROM p_digest THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: digest' USING ERRCODE = 'P1537';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.hook_defs_shape_guard() RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  expected_owner oid;
BEGIN
  SELECT oid INTO expected_owner
  FROM pg_catalog.pg_roles
  WHERE rolname = 'v15_hook_' || NEW.hook_key;
  IF expected_owner IS NULL OR NEW.owner_role IS DISTINCT FROM expected_owner THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: owner_role' USING ERRCODE = 'P1537';
  END IF;
  IF NEW.search_path IS DISTINCT FROM 'pg_catalog' THEN
    RAISE EXCEPTION 'V15_HANDLER_SHAPE: search_path' USING ERRCODE = 'P1537';
  END IF;
  PERFORM v15.v15_assert_handler_shape(
    NEW.regprocedure,
    'v15_hook_' || NEW.hook_key,
    NEW.handler_digest
  );
  RETURN NEW;
END;
$fn$;

CREATE TRIGGER hook_defs_shape
  BEFORE INSERT OR UPDATE ON v15.hook_defs
  FOR EACH ROW EXECUTE FUNCTION v15.hook_defs_shape_guard();

CREATE FUNCTION v15.tool_catalog_shape_guard() RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  PERFORM v15.v15_assert_handler_shape(
    NEW.handler,
    'v15_tool_' || NEW.name,
    NEW.handler_digest
  );
  RETURN NEW;
END;
$fn$;

CREATE TRIGGER tool_catalog_shape
  BEFORE INSERT OR UPDATE ON v15.tool_catalog
  FOR EACH ROW EXECUTE FUNCTION v15.tool_catalog_shape_guard();

CREATE FUNCTION v15.v15_manifest_digest(
  p_max_iterations integer,
  p_max_depth integer,
  p_max_io_attempts integer,
  p_max_statement_ms integer
) RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog
AS $fn$
  SELECT md5(pg_catalog.jsonb_build_object(
    'max_depth', p_max_depth,
    'max_io_attempts', p_max_io_attempts,
    'max_iterations', p_max_iterations,
    'max_statement_ms', p_max_statement_ms
  )::text)
$fn$;

CREATE FUNCTION v15.v15_assert_manifest() RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  rec v15.governance_manifest%ROWTYPE;
  digest text;
BEGIN
  LOCK TABLE v15.governance_manifest IN SHARE MODE;
  SELECT * INTO rec FROM v15.governance_manifest WHERE manifest_id = 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_GOVERNANCE_MISSING' USING ERRCODE = 'P1504';
  END IF;
  digest := v15.v15_manifest_digest(
    rec.max_iterations, rec.max_depth, rec.max_io_attempts, rec.max_statement_ms
  );
  IF rec.max_iterations < 1
     OR rec.max_depth < 1
     OR rec.max_io_attempts < 1
     OR rec.max_statement_ms < 1
     OR rec.manifest_digest IS DISTINCT FROM digest THEN
    RAISE EXCEPTION 'V15_GOVERNANCE_MISSING' USING ERRCODE = 'P1504';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_baseline_max(p_invoke_id uuid, p_hook_key text) RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  cfg jsonb;
  raw text;
BEGIN
  SELECT ih.config INTO STRICT cfg
  FROM v15.invoke_hooks ih
  JOIN v15.hook_defs hd ON hd.hook_def_id = ih.hook_def_id
  WHERE ih.invoke_id = p_invoke_id
    AND ih.channel = 'baseline'
    AND hd.hook_key = p_hook_key;
  IF cfg IS NULL OR pg_catalog.jsonb_typeof(cfg->'max') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  raw := cfg->>'max';
  IF raw !~ '^[0-9]+$' THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  IF raw::integer < 1 THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  RETURN raw::integer;
EXCEPTION
  WHEN no_data_found OR too_many_rows THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
END;
$fn$;

CREATE FUNCTION v15.v15_assert_invoke_manifest(p_invoke_id uuid) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  stored text;
  n_iterations integer;
  n_depth integer;
  n_io integer;
  n_stmt integer;
  digest text;
BEGIN
  SELECT manifest_digest INTO stored
  FROM v15.invokes
  WHERE invoke_id = p_invoke_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
  n_iterations := v15.v15_baseline_max(p_invoke_id, 'governance_iterations');
  n_depth := v15.v15_baseline_max(p_invoke_id, 'governance_depth');
  n_io := v15.v15_baseline_max(p_invoke_id, 'governance_io');
  n_stmt := v15.v15_baseline_max(p_invoke_id, 'governance_statement');
  digest := v15.v15_manifest_digest(n_iterations, n_depth, n_io, n_stmt);
  IF stored IS DISTINCT FROM digest THEN
    RAISE EXCEPTION 'V15_MANIFEST_DIGEST' USING ERRCODE = 'P1521';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_on_phase(
  invoke_id uuid,
  iteration integer,
  span text,
  phase text,
  io jsonb
) RETURNS jsonb
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT '{"contract":1,"action":"proceed"}'::jsonb
$fn$;

CREATE FUNCTION v15.v15_span_open(p_invoke_id uuid, p_span text) RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  open boolean;
BEGIN
  IF session_user <> 'v15_worker'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  SELECT EXISTS (
    SELECT 1
    FROM v15.invoke_events e
    WHERE e.invoke_id = p_invoke_id
      AND e.event_class = 'span'
      AND e.span = p_span
      AND e.phase = 'enter'
      AND e.seq > coalesce((
        SELECT max(x.seq)
        FROM v15.invoke_events x
        WHERE x.invoke_id = p_invoke_id
          AND x.event_class = 'span'
          AND x.span = p_span
          AND x.phase = 'exit'
      ), -1)
  ) INTO open;
  RETURN open;
END;
$fn$;

CREATE FUNCTION v15.v15_next_runnable() RETURNS SETOF uuid
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF session_user <> 'v15_worker'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN QUERY
    SELECT i.invoke_id
    FROM v15.invokes i
    WHERE i.status = 'runnable'
      AND (i.lease_until IS NULL OR i.lease_until <= pg_catalog.clock_timestamp())
    ORDER BY i.root_invoke_id, i.depth DESC, i.invoke_id;
END;
$fn$;

CREATE FUNCTION v15.v15_current_scratch_schema() RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT scratch_schema
  FROM v15.exec_context
  WHERE backend_pid = pg_catalog.pg_backend_pid()
$fn$;

CREATE FUNCTION v15.governance_iterations(p_snapshot jsonb) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT '{"contract":1,"action":"proceed"}'::jsonb
$fn$;

CREATE FUNCTION v15.governance_depth(p_snapshot jsonb) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT '{"contract":1,"action":"proceed"}'::jsonb
$fn$;

CREATE FUNCTION v15.governance_io(p_snapshot jsonb) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT '{"contract":1,"action":"proceed"}'::jsonb
$fn$;

CREATE FUNCTION v15.governance_statement(p_snapshot jsonb) RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
  SELECT '{"contract":1,"action":"proceed"}'::jsonb
$fn$;

ALTER FUNCTION v15.v15_handler_digest(oid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_assert_handler_shape(oid, text, text) OWNER TO v15_owner;
ALTER FUNCTION v15.hook_defs_shape_guard() OWNER TO v15_owner;
ALTER FUNCTION v15.tool_catalog_shape_guard() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_manifest_digest(integer, integer, integer, integer) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_assert_manifest() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_baseline_max(uuid, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_assert_invoke_manifest(uuid) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_on_phase(uuid, integer, text, text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_span_open(uuid, text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_next_runnable() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_current_scratch_schema() OWNER TO v15_owner;
ALTER FUNCTION v15.invoke_events_append_only() OWNER TO v15_owner;
ALTER FUNCTION v15.invoke_events_seq_guard() OWNER TO v15_owner;
ALTER FUNCTION v15.llm_messages_immutable() OWNER TO v15_owner;
ALTER FUNCTION v15.llm_messages_seq_guard() OWNER TO v15_owner;
ALTER FUNCTION v15.governance_manifest_singleton() OWNER TO v15_owner;
ALTER FUNCTION v15.invoke_hooks_baseline_guard() OWNER TO v15_owner;

ALTER FUNCTION v15.governance_iterations(jsonb) OWNER TO v15_hook_governance_iterations;
ALTER FUNCTION v15.governance_depth(jsonb) OWNER TO v15_hook_governance_depth;
ALTER FUNCTION v15.governance_io(jsonb) OWNER TO v15_hook_governance_io;
ALTER FUNCTION v15.governance_statement(jsonb) OWNER TO v15_hook_governance_statement;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v15 FROM PUBLIC;

REVOKE ALL ON FUNCTION v15.governance_iterations(jsonb) FROM v15_hook_governance_iterations;
REVOKE ALL ON FUNCTION v15.governance_depth(jsonb) FROM v15_hook_governance_depth;
REVOKE ALL ON FUNCTION v15.governance_io(jsonb) FROM v15_hook_governance_io;
REVOKE ALL ON FUNCTION v15.governance_statement(jsonb) FROM v15_hook_governance_statement;

GRANT EXECUTE ON FUNCTION v15.governance_iterations(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.governance_depth(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.governance_io(jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.governance_statement(jsonb) TO v15_owner;

GRANT EXECUTE ON FUNCTION v15.v15_on_phase(uuid, integer, text, text, jsonb) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_assert_manifest() TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_assert_invoke_manifest(uuid) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_span_open(uuid, text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_span_open(uuid, text) TO v15_worker;
GRANT EXECUTE ON FUNCTION v15.v15_next_runnable() TO v15_worker;

REVOKE ALL ON FUNCTION v15.v15_current_scratch_schema() FROM v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_current_scratch_schema() TO v15_repl;

INSERT INTO v15.hook_defs (
  hook_def_id, hook_key, regprocedure, owner_role, baseline_required,
  handler_digest, search_path, created_at
)
SELECT
  pg_catalog.gen_random_uuid(),
  k.hook_key,
  k.fn,
  k.owner_role,
  true,
  v15.v15_handler_digest(k.fn),
  'pg_catalog',
  pg_catalog.clock_timestamp()
FROM (
  VALUES
    (
      'governance_iterations',
      'v15.governance_iterations(jsonb)'::regprocedure,
      'v15_hook_governance_iterations'::regrole
    ),
    (
      'governance_depth',
      'v15.governance_depth(jsonb)'::regprocedure,
      'v15_hook_governance_depth'::regrole
    ),
    (
      'governance_io',
      'v15.governance_io(jsonb)'::regprocedure,
      'v15_hook_governance_io'::regrole
    ),
    (
      'governance_statement',
      'v15.governance_statement(jsonb)'::regprocedure,
      'v15_hook_governance_statement'::regrole
    )
) AS k(hook_key, fn, owner_role);

INSERT INTO v15.governance_manifest (
  manifest_id, max_iterations, max_depth, max_io_attempts, max_statement_ms,
  manifest_digest, created_at
)
SELECT
  1, 10, 8, 3, 30000,
  v15.v15_manifest_digest(10, 8, 3, 30000),
  pg_catalog.clock_timestamp();

CREATE FUNCTION v15.v15_scratch_guard() RETURNS event_trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
  scratch text;
  cmd record;
  allowed boolean;
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RETURN;
  END IF;
  scratch := v15.v15_current_scratch_schema();
  FOR cmd IN
    SELECT command_tag, schema_name
    FROM pg_catalog.pg_event_trigger_ddl_commands()
  LOOP
    IF cmd.command_tag IN ('DROP TABLE', 'DROP INDEX', 'DROP VIEW') THEN
      CONTINUE;
    END IF;
    allowed := cmd.command_tag IN (
      'CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO', 'CREATE INDEX', 'CREATE VIEW'
    )
      AND scratch IS NOT NULL
      AND cmd.schema_name IS NOT DISTINCT FROM scratch;
    IF NOT allowed THEN
      RAISE EXCEPTION 'V15_DDL' USING ERRCODE = 'P1512';
    END IF;
  END LOOP;
END;
$fn$;

CREATE FUNCTION v15.v15_scratch_sql_drop() RETURNS event_trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
  scratch text;
  obj record;
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RETURN;
  END IF;
  IF TG_TAG NOT IN ('DROP TABLE', 'DROP INDEX', 'DROP VIEW') THEN
    RAISE EXCEPTION 'V15_DDL' USING ERRCODE = 'P1512';
  END IF;
  scratch := v15.v15_current_scratch_schema();
  FOR obj IN
    SELECT schema_name, original
    FROM pg_catalog.pg_event_trigger_dropped_objects()
  LOOP
    IF obj.original AND (
      scratch IS NULL OR obj.schema_name IS DISTINCT FROM scratch
    ) THEN
      RAISE EXCEPTION 'V15_DDL' USING ERRCODE = 'P1512';
    END IF;
  END LOOP;
END;
$fn$;

ALTER FUNCTION v15.v15_scratch_guard() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_scratch_sql_drop() OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_scratch_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_scratch_sql_drop() FROM PUBLIC;

CREATE EVENT TRIGGER v15_scratch_guard
  ON ddl_command_end
  EXECUTE FUNCTION v15.v15_scratch_guard();

CREATE EVENT TRIGGER v15_scratch_sql_drop
  ON sql_drop
  EXECUTE FUNCTION v15.v15_scratch_sql_drop();
