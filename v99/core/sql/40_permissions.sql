-- Final host ACL. Roles are created by setup_db.py before this manifest runs.
REVOKE ALL ON SCHEMA v99_core FROM PUBLIC;
GRANT USAGE ON SCHEMA v99_core TO v99_core_operator, v99_core_service, v99_core_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA v99_core FROM PUBLIC, v99_core_operator, v99_core_service, v99_core_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA v99_core FROM PUBLIC, v99_core_operator, v99_core_service, v99_core_reader;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA v99_core FROM PUBLIC, v99_core_operator, v99_core_service, v99_core_reader;

-- Make future objects private too (the fixture schema is owner-managed).
ALTER DEFAULT PRIVILEGES IN SCHEMA v99_core REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA v99_core REVOKE ALL ON SEQUENCES FROM PUBLIC;
-- Function EXECUTE is granted to PUBLIC by PostgreSQL's global defaults.
-- Schema-level REVOKE cannot subtract that grant; this isolated database's
-- owner default must be private before applying schema-specific defaults.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA v99_core REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

GRANT EXECUTE ON FUNCTION v99_core.v99_core_start(uuid,text,text),
    v99_core.v99_core_cancel(uuid,uuid,text),
    v99_core.v99_core_steer(uuid,uuid,text,text,bigint),
    v99_core.v99_core_respond(uuid,uuid,text,jsonb,text)
    TO v99_core_operator;
GRANT EXECUTE ON FUNCTION v99_core.v99_core_poll(uuid,uuid,bigint),
    v99_core.v99_core_wait_check(uuid,uuid,bigint,bigint,bigint)
    TO v99_core_reader, v99_core_operator;
GRANT EXECUTE ON FUNCTION v99_core.v99_core_driver_acquire(uuid,text,integer),
    v99_core.v99_core_discover(uuid,text,bigint),
    v99_core.v99_core_claim_effect(uuid,uuid,text,bigint),
    v99_core.v99_core_worker_history(uuid,text,bigint),
    v99_core.v99_core_accept_receipt(uuid,text,text,bigint,jsonb),
    v99_core.v99_core_recover_unknown(uuid,text,bigint)
    TO v99_core_service;

-- Fail closed if a future definer function drifts from the fixed path/owner contract.
DO $acl$
DECLARE f record;
BEGIN
  FOR f IN
    SELECT p.oid, p.proname, p.prosecdef, p.proconfig, p.proowner, p.proacl
    FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='v99_core'
  LOOP
    IF f.proowner <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user) THEN
      RAISE EXCEPTION 'v99_core function owner drift: %', f.proname;
    END IF;
    IF f.prosecdef AND NOT ('search_path=pg_catalog, v99_core' = ANY(coalesce(f.proconfig, ARRAY[]::text[]))) THEN
      RAISE EXCEPTION 'v99_core SECURITY DEFINER search_path drift: % %', f.proname, f.proconfig;
    END IF;
    IF EXISTS (
      SELECT 1 FROM pg_catalog.aclexplode(coalesce(f.proacl, pg_catalog.acldefault('f', f.proowner))) a
      WHERE a.grantee=0 AND a.privilege_type='EXECUTE'
    ) THEN
      RAISE EXCEPTION 'PUBLIC can execute v99_core function: %', f.proname;
    END IF;
  END LOOP;
END
$acl$;
