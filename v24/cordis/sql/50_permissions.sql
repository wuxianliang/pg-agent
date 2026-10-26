-- Same transaction as the DEFINER creation: no publicly executable intermediate state.
DO $$
DECLARE family text; alias text; role_name text;
BEGIN
 family:=v24_cordis.role_family();
 IF family IS NULL THEN RAISE EXCEPTION 'unsafe Cordis role family' USING ERRCODE='42501'; END IF;
 REVOKE ALL ON SCHEMA v24_cordis FROM PUBLIC;
 REVOKE ALL ON ALL TABLES IN SCHEMA v24_cordis FROM PUBLIC;
 REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24_cordis FROM PUBLIC;
 FOREACH alias IN ARRAY ARRAY['admin','service','operator'] LOOP
  role_name:=family||'_'||alias;
  EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA v24_cordis FROM %I',role_name);
  EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24_cordis FROM %I',role_name);
  EXECUTE format('GRANT USAGE ON SCHEMA v24_cordis TO %I',role_name);
  EXECUTE format('GRANT EXECUTE ON FUNCTION v24_cordis.advance(uuid,jsonb) TO %I',role_name);
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace AND prosecdef
   AND oid<>'v24_cordis.advance(uuid,jsonb)'::regprocedure) THEN
  RAISE EXCEPTION 'unexpected DEFINER entry point' USING ERRCODE='42501';
 END IF;
END $$;
