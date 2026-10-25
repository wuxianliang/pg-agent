CREATE SCHEMA v24;

-- v24 uses PostgreSQL core functions; no extension is installed into this schema.
DO $v24$
BEGIN
    IF pg_catalog.to_regprocedure('pg_catalog.sha256(bytea)') IS NULL THEN
        RAISE EXCEPTION 'required core function pg_catalog.sha256(bytea) is unavailable';
    END IF;
    IF pg_catalog.to_regprocedure('pg_catalog.gen_random_uuid()') IS NULL THEN
        RAISE EXCEPTION 'required core function pg_catalog.gen_random_uuid() is unavailable';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_extension AS e
          JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
         WHERE n.nspname = 'v24'
    ) THEN
        RAISE EXCEPTION 'unexpected extension installed in schema v24';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_depend AS d
         WHERE d.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
           AND d.objid IN (
               'pg_catalog.sha256(bytea)'::pg_catalog.regprocedure,
               'pg_catalog.gen_random_uuid()'::pg_catalog.regprocedure
           )
           AND d.refclassid = 'pg_catalog.pg_extension'::pg_catalog.regclass
           AND d.deptype = 'e'
    ) THEN
        RAISE EXCEPTION 'required core functions unexpectedly depend on an extension';
    END IF;
END
$v24$;
