-- v13 external_exec (stage 43). STABLE read. Not a tools row.
BEGIN;

CREATE FUNCTION public.v13_external_exec_classify(p_sid uuid, p_spec jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_value jsonb;
  v_version integer;
BEGIN
  IF p_spec IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'shape');
  END IF;
  IF jsonb_typeof(p_spec) IS DISTINCT FROM 'object' THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'shape');
  END IF;

  IF p_spec ? 'source_principal' THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'unsupported');
  END IF;

  IF EXISTS (
    SELECT 1
      FROM jsonb_object_keys(p_spec) AS k
     WHERE k NOT IN ('schema_version', 'verb')
  ) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'unsupported');
  END IF;

  IF public.v13_json_keys(p_spec) IS DISTINCT FROM ARRAY['schema_version', 'verb'] THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'shape');
  END IF;
  IF public.v13_json_int_ok(p_spec->'schema_version', 1) IS NOT TRUE THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'shape');
  END IF;
  IF (p_spec->>'schema_version') IS DISTINCT FROM '1' THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'shape');
  END IF;
  IF jsonb_typeof(p_spec->'verb') IS DISTINCT FROM 'string' THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'shape');
  END IF;

  IF p_sid IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'unsupported');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'unsupported');
  END IF;

  SELECT value, version
    INTO v_value, v_version
    FROM public.v13_policies
   WHERE name = 'external_executor'
     AND active;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: no active policy row for external_executor (seed lost?)';
  END IF;

  IF public.v13_json_keys(v_value) IS DISTINCT FROM ARRAY['schema_version', 'verbs'] THEN
    RAISE EXCEPTION 'v13: external_executor policy';
  END IF;
  IF public.v13_json_int_ok(v_value->'schema_version', 1) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: external_executor policy';
  END IF;
  IF (v_value->>'schema_version') IS DISTINCT FROM '1' THEN
    RAISE EXCEPTION 'v13: external_executor policy';
  END IF;

  IF jsonb_typeof(v_value->'verbs') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: external_executor policy';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM jsonb_array_elements(v_value->'verbs') AS e
     WHERE jsonb_typeof(e) IS DISTINCT FROM 'string'
  ) THEN
    RAISE EXCEPTION 'v13: external_executor policy';
  END IF;
  IF (
       SELECT count(*) FROM jsonb_array_elements_text(v_value->'verbs')
     ) IS DISTINCT FROM (
       SELECT count(DISTINCT t) FROM jsonb_array_elements_text(v_value->'verbs') AS t
     )
  THEN
    RAISE EXCEPTION 'v13: external_executor policy';
  END IF;

  IF NOT ((v_value->'verbs') ? (p_spec->>'verb')) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'unsupported');
  END IF;

  RETURN jsonb_build_object(
    'schema_version', 1,
    'ok', true,
    'classified', true,
    'executed', false,
    'verb', p_spec->>'verb',
    'policy_name', 'external_executor',
    'policy_version', v_version);
END
$fn$;

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'external_executor',
  1,
  '{"schema_version":1,"verbs":["agentctl_observe","agentctl_steer","agentctl_answer","agentctl_cancel"]}'::jsonb,
  true);

REVOKE EXECUTE ON FUNCTION public.v13_external_exec_classify(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_external_exec_classify(uuid, jsonb) TO v13_route;

COMMENT ON FUNCTION public.v13_external_exec_classify(uuid, jsonb) IS
  'STABLE read; classifies one verb against the active external_executor row; does not execute; success carries executed false and the row version; not a tools row; does not raise on shape or unsupported.';

COMMIT;
