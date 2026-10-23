-- W6 host ACL: schema use and exact entry-point EXECUTE only.
REVOKE ALL ON SCHEMA v24 FROM PUBLIC;
GRANT USAGE ON SCHEMA v24 TO v24_admin, v24_service, v24_operator;

-- Never revoke from v24_owner: its table privileges power advance's DEFINER.
-- No table-level grants: writes go through advance; reads use the closed DEFINER surface.
REVOKE ALL ON ALL TABLES IN SCHEMA v24 FROM PUBLIC, v24_admin, v24_service, v24_operator;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24 FROM PUBLIC, v24_admin, v24_service, v24_operator;

-- PostgreSQL's global function default is PUBLIC EXECUTE; revoke both scopes.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA v24 REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Pure helpers and exact application entry points are the only exposed calls.
GRANT EXECUTE ON FUNCTION v24.canonical_json(jsonb)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.effect_id_for(uuid, text, text)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.principal_id(name)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.error_v1(text, jsonb)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.advance(uuid, jsonb)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.scope_control(text, uuid, jsonb, text, text)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.install(uuid, uuid, bytea, bytea, text)
  TO v24_service, v24_operator;
-- S3 W1 read surface: STABLE DEFINER, fixed search_path, writes nothing.
GRANT EXECUTE ON FUNCTION v24.resolve(uuid, text[])
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.poll(uuid, bigint)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.wait_check(uuid, bigint, bigint, bigint)
  TO v24_admin, v24_service, v24_operator;
-- S3 W2 run creation entry point.
GRANT EXECUTE ON FUNCTION v24.start(uuid, uuid, jsonb, jsonb, text)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.cancel(uuid, bigint, text)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.steer(uuid, bigint, text, text)
  TO v24_admin, v24_service, v24_operator;
GRANT EXECUTE ON FUNCTION v24.respond(uuid, uuid, jsonb, bigint, text)
  TO v24_admin, v24_service, v24_operator;
-- W4 lifecycle entry point.
GRANT EXECUTE ON FUNCTION v24.fiber_control(uuid, text, bigint, text)
  TO v24_admin, v24_service, v24_operator;
-- W6 dispose entry point.
GRANT EXECUTE ON FUNCTION v24.dispose(uuid, text)
  TO v24_admin, v24_service, v24_operator;

-- Fail closed if a later function drifts from the owner/path/PUBLIC contract.
DO $acl$
DECLARE
  f record;
BEGIN
  IF (SELECT array_agg(p.proname::text ORDER BY p.proname)
        FROM pg_catalog.pg_proc p
        WHERE p.pronamespace = 'v24'::regnamespace AND p.prosecdef)
     IS DISTINCT FROM ARRAY['advance', 'poll', 'resolve', 'run_owner', 'run_projection', 'wait_check']::text[] THEN
    RAISE EXCEPTION 'v24 SECURITY DEFINER allowlist drift';
  END IF;
  FOR f IN
    SELECT p.oid, p.proname, p.prosecdef, p.provolatile, p.prosrc,
           p.proconfig, p.proowner, p.proacl
      FROM pg_catalog.pg_proc AS p
      JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
     WHERE n.nspname = 'v24'
  LOOP
    IF f.proowner <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'v24_owner') THEN
      RAISE EXCEPTION 'v24 function owner drift: %', f.proname;
    END IF;
    IF f.prosecdef
       AND f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, v24']::text[] THEN
      RAISE EXCEPTION 'v24 SECURITY DEFINER search_path drift: % %', f.proname, f.proconfig;
    END IF;
    IF EXISTS (
      SELECT 1
        FROM pg_catalog.aclexplode(
          coalesce(f.proacl, pg_catalog.acldefault('f', f.proowner))
        ) AS a
       WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE'
    ) THEN
      RAISE EXCEPTION 'PUBLIC can execute v24 function: %', f.proname;
    END IF;
    IF f.proname IN ('start', 'cancel', 'steer', 'respond') AND (
       f.prosecdef
       OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, v24']::text[]
       OR NOT pg_catalog.has_function_privilege('v24_admin', f.oid, 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('v24_service', f.oid, 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('v24_operator', f.oid, 'EXECUTE')) THEN
      RAISE EXCEPTION 'v24 write verb entry-point contract drift: %', f.proname;
    END IF;
    IF f.prosecdef AND f.proname <> 'advance' THEN
      IF f.provolatile <> 's'
         OR f.prosrc ~* '\m(insert|update|delete|pg_advisory[a-z_0-9]*)\M' THEN
        RAISE EXCEPTION 'v24 read-only SECURITY DEFINER drift: %', f.proname;
      END IF;
    END IF;
    IF f.proname IN ('poll', 'wait_check') AND (
       NOT f.prosecdef OR f.provolatile <> 's'
       OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, v24']::text[]
       OR NOT pg_catalog.has_function_privilege('v24_admin', f.oid, 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('v24_service', f.oid, 'EXECUTE')
       OR NOT pg_catalog.has_function_privilege('v24_operator', f.oid, 'EXECUTE')) THEN
      RAISE EXCEPTION 'v24 poll/wait_check entry-point contract drift: %', f.proname;
    END IF;
  END LOOP;
END
$acl$;
