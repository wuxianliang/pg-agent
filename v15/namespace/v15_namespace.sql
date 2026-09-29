CREATE FUNCTION v15.v15_exec_running() RETURNS v15.exec_context
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  st text;
BEGIN
  SELECT * INTO ctx
  FROM v15.exec_context
  WHERE backend_pid = pg_catalog.pg_backend_pid();
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  SELECT s.status INTO st
  FROM v15.statements s
  WHERE s.invoke_id = ctx.invoke_id
    AND s.iteration = ctx.iteration
    AND s.stmt_index = ctx.stmt_index;
  IF st IS DISTINCT FROM 'running' THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  RETURN ctx;
END;
$fn$;

CREATE FUNCTION v15.v15_exec_view()
RETURNS TABLE (invoke_id uuid, iteration integer)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  RETURN QUERY
    SELECT e.invoke_id, e.iteration
    FROM v15.exec_context e
    WHERE e.backend_pid = pg_catalog.pg_backend_pid();
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_check_binding_name(p_name text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_name IS NULL
     OR p_name !~ '^[A-Za-z_][A-Za-z0-9_]*$'
     OR pg_catalog.char_length(p_name) < 1
     OR pg_catalog.char_length(p_name) > 63
     OR p_name = ANY (ARRAY[
       '__history__', 'history', 'request_messages', 'return', 'raise', 'print',
       'assign', 'var', 'tool', 'bind_invoke', 'prior_history', 'exec_context',
       'invoke_id', 'iteration'
     ]::text[]) THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.v15_reject_bind_eval(p_ctx v15.exec_context) RETURNS void
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
  IF k = 'bind_invoke' THEN
    RAISE EXCEPTION 'V15_INVOKE_FORM' USING ERRCODE = 'P1503';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.jaz_var(name text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  p_name text;
  found_kind text;
  found_value jsonb;
BEGIN
  p_name := name;
  ctx := v15.v15_exec_running();
  PERFORM v15.v15_check_binding_name(p_name);
  SELECT b.kind, b.value INTO found_kind, found_value
  FROM v15.bindings b
  WHERE b.invoke_id = ctx.invoke_id AND b.name = p_name;
  IF NOT FOUND OR found_kind = 'tool' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  RETURN found_value;
END;
$fn$;

CREATE FUNCTION v15.jaz_assign(name text, value jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  p_name text;
  p_value jsonb;
  found_kind text;
  n integer;
BEGIN
  p_name := name;
  p_value := value;
  ctx := v15.v15_exec_running();
  PERFORM v15.v15_reject_bind_eval(ctx);
  IF p_value IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  PERFORM v15.v15_check_binding_name(p_name);
  SELECT b.kind INTO found_kind
  FROM v15.bindings b
  WHERE b.invoke_id = ctx.invoke_id AND b.name = p_name;
  IF FOUND THEN
    IF found_kind <> 'var' THEN
      RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
    END IF;
    UPDATE v15.bindings b
    SET value = p_value,
        provenance = 'repl',
        revision = b.revision + 1
    WHERE b.invoke_id = ctx.invoke_id AND b.name = p_name;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
      RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
    END IF;
    RETURN p_value;
  END IF;
  INSERT INTO v15.bindings (
    invoke_id, name, kind, value, tool_id, show_in_prompt, provenance, revision
  ) VALUES (
    ctx.invoke_id, p_name, 'var', p_value, NULL, true, 'repl', 0
  );
  RETURN p_value;
END;
$fn$;

CREATE FUNCTION v15.jaz_print(line text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  p_line text;
  n integer;
BEGIN
  p_line := line;
  ctx := v15.v15_exec_running();
  PERFORM v15.v15_reject_bind_eval(ctx);
  IF p_line IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  UPDATE v15.iterations i
  SET capture = i.capture || p_line,
      revision = i.revision + 1
  WHERE i.invoke_id = ctx.invoke_id AND i.iteration = ctx.iteration;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.jaz_tool(name text, args jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  p_name text;
  p_args jsonb;
  cat v15.tool_catalog%ROWTYPE;
  proc pg_catalog.pg_proc%ROWTYPE;
  owner_name text;
  lang text;
  ns text;
  fn text;
  call_sql text;
  result jsonb;
BEGIN
  p_name := name;
  p_args := args;
  ctx := v15.v15_exec_running();
  PERFORM v15.v15_reject_bind_eval(ctx);
  SELECT c.* INTO cat
  FROM v15.bindings b
  JOIN v15.tool_grants g
    ON g.invoke_id = b.invoke_id AND g.tool_id = b.tool_id
  JOIN v15.tool_catalog c ON c.tool_id = b.tool_id
  WHERE b.invoke_id = ctx.invoke_id
    AND b.name = p_name
    AND b.kind = 'tool';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_TOOL_UNAUTHORIZED' USING ERRCODE = 'P1507';
  END IF;
  IF cat.external THEN
    RAISE EXCEPTION 'V15_EXTERNAL_TOOL' USING ERRCODE = 'P1517';
  END IF;
  IF pg_catalog.jsonb_typeof(p_args) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT * INTO proc FROM pg_catalog.pg_proc WHERE oid = cat.handler;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'V15_HANDLER_DIGEST' USING ERRCODE = 'P1536';
  END IF;
  SELECT r.rolname INTO owner_name
  FROM pg_catalog.pg_roles r
  WHERE r.oid = proc.proowner;
  SELECT l.lanname INTO lang
  FROM pg_catalog.pg_language l
  WHERE l.oid = proc.prolang;
  IF owner_name IS DISTINCT FROM 'v15_tool_' || cat.name
     OR proc.provolatile IS DISTINCT FROM 's'
     OR NOT proc.prosecdef
     OR lang NOT IN ('sql', 'plpgsql')
     OR proc.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
     OR v15.v15_handler_digest(cat.handler) IS DISTINCT FROM cat.handler_digest THEN
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
  SELECT n.nspname, p.proname INTO ns, fn
  FROM pg_catalog.pg_proc p
  JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
  WHERE p.oid = cat.handler;
  call_sql := pg_catalog.quote_ident(ns) || '.'
    || pg_catalog.quote_ident(fn) || '($1::jsonb)';
  BEGIN
    EXECUTE 'SELECT ' || call_sql INTO result USING p_args;
  EXCEPTION
    WHEN OTHERS THEN
      IF SQLSTATE >= 'P1501' AND SQLSTATE <= 'P1538' THEN
        RAISE;
      END IF;
      RAISE EXCEPTION 'V15_HANDLER_FAILED' USING ERRCODE = 'P1525';
  END;
  RETURN result;
END;
$fn$;

CREATE FUNCTION v15.jaz_return(value jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  p_value jsonb;
  k text;
  cap text;
  n integer;
BEGIN
  p_value := value;
  ctx := v15.v15_exec_running();
  SELECT s.kind INTO k
  FROM v15.statements s
  WHERE s.invoke_id = ctx.invoke_id
    AND s.iteration = ctx.iteration
    AND s.stmt_index = ctx.stmt_index;
  IF k IS DISTINCT FROM 'return' THEN
    RAISE EXCEPTION 'V15_INVOKE_FORM' USING ERRCODE = 'P1503';
  END IF;
  IF p_value IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT i.capture INTO cap
  FROM v15.iterations i
  WHERE i.invoke_id = ctx.invoke_id AND i.iteration = ctx.iteration;
  IF cap <> '' THEN
    RAISE EXCEPTION 'V15_PRINT_AND_RETURN' USING ERRCODE = 'P1515';
  END IF;
  UPDATE v15.invokes i
  SET return_value = p_value,
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = ctx.invoke_id;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
  RETURN p_value;
END;
$fn$;

CREATE FUNCTION v15.jaz_raise(message text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  p_message text;
  k text;
  cap text;
  n integer;
BEGIN
  p_message := message;
  ctx := v15.v15_exec_running();
  SELECT s.kind INTO k
  FROM v15.statements s
  WHERE s.invoke_id = ctx.invoke_id
    AND s.iteration = ctx.iteration
    AND s.stmt_index = ctx.stmt_index;
  IF k IS DISTINCT FROM 'raise' THEN
    RAISE EXCEPTION 'V15_INVOKE_FORM' USING ERRCODE = 'P1503';
  END IF;
  IF p_message IS NULL THEN
    RAISE EXCEPTION 'V15_VALUE_INVALID' USING ERRCODE = 'P1524';
  END IF;
  SELECT i.capture INTO cap
  FROM v15.iterations i
  WHERE i.invoke_id = ctx.invoke_id AND i.iteration = ctx.iteration;
  IF cap <> '' THEN
    RAISE EXCEPTION 'V15_PRINT_AND_RETURN' USING ERRCODE = 'P1515';
  END IF;
  UPDATE v15.invokes i
  SET error = pg_catalog.jsonb_build_object(
        'sqlstate', 'P1529',
        'code', 'V15_RAISE',
        'message', pg_catalog.left(p_message, 1024)
      ),
      revision = i.revision + 1,
      updated_at = pg_catalog.clock_timestamp()
  WHERE i.invoke_id = ctx.invoke_id;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION 'V15_INVALID_TRANSITION' USING ERRCODE = 'P1523';
  END IF;
END;
$fn$;

CREATE FUNCTION v15.jaz_bind_invoke(name text, args jsonb) RETURNS jsonb
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

CREATE FUNCTION v15.jaz_prior_history(ancestor uuid)
RETURNS TABLE (
  iteration integer,
  llm_response text,
  repl_output text,
  repl_exception jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE
  ctx v15.exec_context;
  cur_id uuid;
  nxt uuid;
  seen uuid[] := ARRAY[]::uuid[];
  found boolean := false;
BEGIN
  ctx := v15.v15_exec_running();
  cur_id := ctx.invoke_id;
  LOOP
    EXIT WHEN cur_id IS NULL;
    IF cur_id = ancestor THEN
      found := true;
      EXIT;
    END IF;
    EXIT WHEN cur_id = ANY (seen);
    seen := seen || cur_id;
    nxt := NULL;
    SELECT i.parent_invoke_id INTO nxt
    FROM v15.invokes i
    WHERE i.invoke_id = cur_id;
    cur_id := nxt;
  END LOOP;
  IF NOT found THEN
    RAISE EXCEPTION 'V15_HISTORY_SCOPE' USING ERRCODE = 'P1510';
  END IF;
  RETURN QUERY
    SELECT h.iteration, h.llm_response, h.repl_output, h.repl_exception
    FROM v15.repl_history h
    WHERE h.invoke_id = ancestor
    ORDER BY h.iteration;
END;
$fn$;

CREATE FUNCTION jaz.var(name text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN v15.jaz_var(name);
END;
$fn$;

CREATE FUNCTION jaz.assign(name text, value jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN v15.jaz_assign(name, value);
END;
$fn$;

CREATE FUNCTION jaz.print(line text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  PERFORM v15.jaz_print(line);
END;
$fn$;

CREATE FUNCTION jaz.tool(name text, args jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN v15.jaz_tool(name, args);
END;
$fn$;

CREATE FUNCTION jaz."return"(value jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN v15.jaz_return(value);
END;
$fn$;

CREATE FUNCTION jaz."raise"(message text) RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  PERFORM v15.jaz_raise(message);
END;
$fn$;

CREATE FUNCTION jaz.bind_invoke(name text, args jsonb) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN v15.jaz_bind_invoke(name, args);
END;
$fn$;

CREATE FUNCTION jaz.prior_history(ancestor uuid)
RETURNS TABLE (
  iteration integer,
  llm_response text,
  repl_output text,
  repl_exception jsonb
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF current_user <> 'v15_repl'::name THEN
    RAISE EXCEPTION 'V15_ROLE' USING ERRCODE = 'P1522';
  END IF;
  RETURN QUERY
    SELECT h.iteration, h.llm_response, h.repl_output, h.repl_exception
    FROM v15.jaz_prior_history(ancestor) h;
END;
$fn$;

CREATE VIEW jaz.history
WITH (security_barrier = true, security_invoker = false) AS
SELECT h.iteration, h.llm_response, h.repl_output, h.repl_exception
FROM v15.v15_exec_view() ctx
JOIN v15.repl_history h ON h.invoke_id = ctx.invoke_id;

CREATE VIEW jaz.request_messages
WITH (security_barrier = true, security_invoker = false) AS
SELECT
  (elem.value ->> 'seq')::integer AS seq,
  elem.value ->> 'role' AS role,
  elem.value ->> 'kind' AS kind,
  elem.value ->> 'content' AS content
FROM v15.v15_exec_view() ctx
JOIN LATERAL (
  SELECT a.request
  FROM v15.llm_requests r
  JOIN v15.llm_attempts a ON a.request_id = r.request_id
  WHERE r.invoke_id = ctx.invoke_id
    AND r.iteration = ctx.iteration
    AND a.status = 'settled'
  ORDER BY a.n DESC
  LIMIT 1
) att ON true
CROSS JOIN LATERAL pg_catalog.jsonb_array_elements(att.request -> 'messages')
  AS elem(value);

ALTER FUNCTION v15.v15_exec_running() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_exec_view() OWNER TO v15_owner;
ALTER FUNCTION v15.v15_check_binding_name(text) OWNER TO v15_owner;
ALTER FUNCTION v15.v15_reject_bind_eval(v15.exec_context) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_var(text) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_assign(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_print(text) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_tool(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_return(jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_raise(text) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_bind_invoke(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION v15.jaz_prior_history(uuid) OWNER TO v15_owner;
ALTER FUNCTION jaz.var(text) OWNER TO v15_owner;
ALTER FUNCTION jaz.assign(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION jaz.print(text) OWNER TO v15_owner;
ALTER FUNCTION jaz.tool(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION jaz."return"(jsonb) OWNER TO v15_owner;
ALTER FUNCTION jaz."raise"(text) OWNER TO v15_owner;
ALTER FUNCTION jaz.bind_invoke(text, jsonb) OWNER TO v15_owner;
ALTER FUNCTION jaz.prior_history(uuid) OWNER TO v15_owner;
ALTER VIEW jaz.history OWNER TO v15_owner;
ALTER VIEW jaz.request_messages OWNER TO v15_owner;

REVOKE ALL ON FUNCTION v15.v15_exec_running() FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_exec_view() FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_check_binding_name(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION v15.v15_reject_bind_eval(v15.exec_context) FROM PUBLIC;

REVOKE ALL ON FUNCTION v15.jaz_var(text) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_assign(text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_print(text) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_tool(text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_return(jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_raise(text) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_bind_invoke(text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION v15.jaz_prior_history(uuid) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
GRANT EXECUTE ON FUNCTION v15.jaz_var(text) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_assign(text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_print(text) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_tool(text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_return(jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_raise(text) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_bind_invoke(text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION v15.jaz_prior_history(uuid) TO v15_repl;

REVOKE ALL ON FUNCTION jaz.var(text) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz.assign(text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz.print(text) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz.tool(text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz."return"(jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz."raise"(text) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz.bind_invoke(text, jsonb) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
REVOKE ALL ON FUNCTION jaz.prior_history(uuid) FROM PUBLIC, v15_owner, v15_worker, v15_bootstrap;
GRANT EXECUTE ON FUNCTION jaz.var(text) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz.assign(text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz.print(text) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz.tool(text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz."return"(jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz."raise"(text) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz.bind_invoke(text, jsonb) TO v15_repl;
GRANT EXECUTE ON FUNCTION jaz.prior_history(uuid) TO v15_repl;

GRANT EXECUTE ON FUNCTION v15.v15_exec_view() TO v15_repl;

REVOKE ALL ON jaz.history FROM PUBLIC, v15_worker, v15_bootstrap;
REVOKE ALL ON jaz.request_messages FROM PUBLIC, v15_worker, v15_bootstrap;
GRANT SELECT ON jaz.history TO v15_repl;
GRANT SELECT ON jaz.request_messages TO v15_repl;

REVOKE ALL ON TABLE
  v15.exec_context,
  v15.bindings,
  v15.iterations,
  v15.invokes,
  v15.statements,
  v15.repl_history,
  v15.llm_attempts,
  v15.llm_requests,
  v15.tool_catalog,
  v15.tool_grants
FROM PUBLIC, v15_repl, v15_worker;
