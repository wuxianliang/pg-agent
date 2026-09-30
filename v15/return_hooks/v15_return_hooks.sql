CREATE FUNCTION v15.v15_return_validation_effect(
  p_snapshot jsonb,
  p_valid boolean,
  p_message text
) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
  v_hook text;
  v_ord text;
  v_n bigint;
  v_ctr jsonb;
  v_max_json jsonb;
  v_max integer;
  v_unlimited boolean := false;
  v_message text;
  v_id text;
  v_ok_meta boolean := true;
  v_key text;
BEGIN
  IF p_valid IS TRUE
     OR p_snapshot->>'span' IS DISTINCT FROM 'repl_exec'
     OR p_snapshot->>'phase' IS DISTINCT FROM 'complete'
     OR p_snapshot #>> '{io,result_kind}' IS DISTINCT FROM 'return'
     OR p_snapshot #>> '{io,capture}' IS DISTINCT FROM '' THEN
    RETURN '{"contract":1,"action":"proceed"}'::jsonb;
  END IF;
  IF p_message IS NULL THEN
    v_message := 'validation message missing';
  ELSE
    v_message := pg_catalog.left(p_message, 1024);
  END IF;
  v_hook := p_snapshot #>> '{self,hook_key}';
  v_ord := p_snapshot #>> '{self,ordinal}';
  IF v_hook IS NULL
     OR v_ord IS NULL
     OR v_ord !~ '^[0-9]+$'
     OR v_ord::numeric > 2147483647
     OR (
       v_hook <> ALL (ARRAY['budget_forcing', 'return_type', 'validate_return']::text[])
       AND NOT pg_catalog.starts_with(v_hook, 'validate_return_')
     ) THEN
    v_ok_meta := false;
  END IF;
  v_max_json := p_snapshot #> '{self,config,max_failures}';
  IF v_max_json = 'null'::jsonb THEN
    v_unlimited := true;
  ELSIF pg_catalog.jsonb_typeof(v_max_json) = 'number'
        AND (v_max_json #>> '{}') ~ '^[0-9]+$'
        AND (v_max_json #>> '{}')::numeric <= 2147483647 THEN
    v_max := (v_max_json #>> '{}')::integer;
  ELSE
    v_max := 0;
  END IF;
  v_n := 0;
  IF v_ok_meta THEN
    v_key := v_hook || ':' || v_ord;
    IF p_snapshot->'counters' IS NULL THEN
      v_n := 0;
    ELSIF pg_catalog.jsonb_typeof(p_snapshot->'counters') IS DISTINCT FROM 'object' THEN
      v_ok_meta := false;
    ELSE
      v_ctr := p_snapshot #> ARRAY['counters', v_key];
      IF v_ctr IS NULL THEN
        v_n := 0;
      ELSIF pg_catalog.jsonb_typeof(v_ctr) IS DISTINCT FROM 'number'
            OR (v_ctr #>> '{}') !~ '^[0-9]+$' THEN
        v_ok_meta := false;
      ELSE
        BEGIN
          v_n := (v_ctr #>> '{}')::bigint;
        EXCEPTION
          WHEN numeric_value_out_of_range THEN
            v_ok_meta := false;
            v_n := NULL;
        END;
      END IF;
    END IF;
  END IF;
  IF v_ok_meta
     AND v_n IS NOT NULL
     AND (v_unlimited OR v_n < v_max) THEN
    v_id := v_hook || ':' || v_ord || ':' || v_n::text;
    RETURN pg_catalog.jsonb_build_object(
      'contract', 1,
      'action', 'proceed',
      'exec_result', pg_catalog.jsonb_build_object(
        'result_kind', 'continue',
        'return_value', 'null'::jsonb,
        'error', 'null'::jsonb
      ),
      'messages', pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'id', v_id,
        'role', 'user',
        'content', v_message,
        'persistent', true
      ))
    );
  END IF;
  RETURN pg_catalog.jsonb_build_object(
    'contract', 1,
    'action', 'proceed',
    'exec_result', pg_catalog.jsonb_build_object(
      'result_kind', 'raise',
      'return_value', 'null'::jsonb,
      'error', pg_catalog.jsonb_build_object(
        'code', 'V15_VALIDATION_FAILED',
        'message', v_message
      )
    )
  );
END;
$fn$;

ALTER FUNCTION v15.v15_return_validation_effect(jsonb, boolean, text) OWNER TO v15_owner;
REVOKE ALL ON FUNCTION v15.v15_return_validation_effect(jsonb, boolean, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v15.v15_return_validation_effect(jsonb, boolean, text) TO v15_owner;
GRANT EXECUTE ON FUNCTION v15.v15_return_validation_effect(jsonb, boolean, text) TO v15_hook_return_type;
GRANT USAGE ON SCHEMA v15 TO v15_hook_return_type;
