-- W6 host ACL: schema use and exact entry-point EXECUTE only.
REVOKE ALL ON SCHEMA v24 FROM PUBLIC;
GRANT USAGE ON SCHEMA v24 TO v24_admin, v24_service, v24_operator;

-- Never revoke from v24_owner: its table privileges power advance's DEFINER.
-- No table-level grants: protocol roles reach domain state only through advance.
REVOKE ALL ON ALL TABLES IN SCHEMA v24 FROM PUBLIC, v24_admin, v24_service, v24_operator;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24 FROM PUBLIC, v24_admin, v24_service, v24_operator;

-- PostgreSQL's global function default is PUBLIC EXECUTE; revoke both scopes.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA v24 REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Pure helpers and the three application wrappers are the only exposed calls.
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
-- W1 capability read surface: STABLE, INVOKER, writes nothing.
GRANT EXECUTE ON FUNCTION v24.resolve(uuid, text[])
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
  FOR f IN
    SELECT p.oid, p.proname, p.prosecdef, p.proconfig, p.proowner, p.proacl
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
  END LOOP;
END
$acl$;
