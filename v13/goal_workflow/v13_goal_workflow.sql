-- v13 goal_workflow (stage 42). STABLE read. Not a tools row.
-- A shape failure or a missing session returns jsonb and does not raise.
BEGIN;

CREATE FUNCTION public.v13_macro_suggestion(p_sid uuid, p_suggestion jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_keys text[];
  v_subject text;
  v_gate text;
  v_should_run boolean;
  v_quota_eligible boolean;
  v_shape jsonb := jsonb_build_object(
    'ok', false,
    'reason', 'shape',
    'admitted', false);
  v_missing jsonb := jsonb_build_object(
    'ok', false,
    'reason', 'missing',
    'admitted', false);
BEGIN
  IF p_suggestion IS NULL THEN
    RETURN v_shape;
  END IF;
  IF jsonb_typeof(p_suggestion) IS DISTINCT FROM 'object' THEN
    RETURN v_shape;
  END IF;

  v_keys := public.v13_json_keys(p_suggestion);
  IF v_keys IS DISTINCT FROM ARRAY['kind', 'schema_version', 'subject_session_id', 'suggested_should_run'] THEN
    IF v_keys IS DISTINCT FROM ARRAY['kind', 'note', 'schema_version', 'subject_session_id', 'suggested_should_run'] THEN
      RETURN v_shape;
    END IF;
  END IF;

  IF public.v13_json_int_ok(p_suggestion->'schema_version', 1) IS NOT TRUE THEN
    RETURN v_shape;
  END IF;
  IF (p_suggestion->>'schema_version') IS DISTINCT FROM '1' THEN
    RETURN v_shape;
  END IF;

  IF jsonb_typeof(p_suggestion->'kind') IS DISTINCT FROM 'string' THEN
    RETURN v_shape;
  END IF;
  IF (p_suggestion->>'kind') IS DISTINCT FROM 'macro_suggestion' THEN
    RETURN v_shape;
  END IF;

  v_subject := p_suggestion->>'subject_session_id';
  IF public.v13_canonical_uuid(v_subject) IS NOT TRUE THEN
    RETURN v_shape;
  END IF;
  IF v_subject IS DISTINCT FROM p_sid::text THEN
    RETURN v_shape;
  END IF;

  IF jsonb_typeof(p_suggestion->'suggested_should_run') IS DISTINCT FROM 'boolean' THEN
    RETURN v_shape;
  END IF;

  IF v_keys = ARRAY['kind', 'note', 'schema_version', 'subject_session_id', 'suggested_should_run'] THEN
    IF jsonb_typeof(p_suggestion->'note') IS DISTINCT FROM 'string' THEN
      RETURN v_shape;
    END IF;
    IF char_length(btrim(p_suggestion->>'note')) > 256 THEN
      RETURN v_shape;
    END IF;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RETURN v_missing;
  END IF;

  v_gate := public.v13_should_run_gate(p_sid);
  v_should_run := public.v13_should_run(p_sid);
  v_quota_eligible := public.v13_quota_eligible(p_sid);
  RETURN jsonb_build_object(
    'schema_version', 1,
    'ok', true,
    'admitted', v_should_run AND v_quota_eligible,
    'should_run', v_should_run,
    'quota_eligible', v_quota_eligible,
    'gate', v_gate);
END
$fn$;

REVOKE EXECUTE ON FUNCTION public.v13_macro_suggestion(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_macro_suggestion(uuid, jsonb) TO v13_route;

COMMENT ON FUNCTION public.v13_macro_suggestion(uuid, jsonb) IS
  'STABLE read; discards suggested_should_run; admitted is v13_should_run AND v13_quota_eligible; not a tools row; does not raise on a shape or missing session.';

COMMIT;
