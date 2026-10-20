-- Fresh isolated fixture only: never relocate an existing extension.
CREATE SCHEMA v99_core;
DO $v99$
DECLARE installed_schema text;
BEGIN
    SELECT n.nspname INTO installed_schema
      FROM pg_catalog.pg_extension e
      JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
     WHERE e.extname = 'pgcrypto';
    IF installed_schema IS NOT NULL AND installed_schema <> 'v99_core' THEN
        RAISE EXCEPTION 'pgcrypto already installed in %, expected v99_core', installed_schema;
    END IF;
END
$v99$;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA v99_core;
