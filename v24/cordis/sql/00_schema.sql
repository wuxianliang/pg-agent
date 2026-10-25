-- Cordis is independent of the frozen v24 schema.
CREATE SCHEMA v24_cordis;
REVOKE ALL ON SCHEMA v24_cordis FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA v24_cordis REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
DO $$
DECLARE f oid;
BEGIN
  IF current_setting('server_version_num')::integer / 10000 <> 18 THEN
    RAISE EXCEPTION 'Cordis DP1 requires PostgreSQL 18';
  END IF;
  FOREACH f IN ARRAY ARRAY['pg_catalog.sha256(bytea)'::regprocedure::oid,
                           'pg_catalog.gen_random_uuid()'::regprocedure::oid] LOOP
    IF EXISTS (SELECT FROM pg_catalog.pg_depend WHERE classid='pg_proc'::regclass
               AND objid=f AND deptype='e') THEN
      RAISE EXCEPTION 'Cordis core function must not require an extension';
    END IF;
  END LOOP;
END $$;
