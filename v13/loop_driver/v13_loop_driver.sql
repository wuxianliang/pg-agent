-- v13 loop_driver stage 33. C7 SQL key layer: the single STABLE projection.
-- This file does NOT CREATE OR REPLACE v13_advance (plan §6: plan_arm owns the
-- only replacement). No other parser exists in Python or real_chain.

CREATE FUNCTION public.v13_harness_result_project(p_result jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_known text[] := ARRAY['content_hash', 'delivery_kind', 'harness_session_ref',
                          'interaction_id', 'partial', 'resume_token', 'result_kind',
                          'signals', 'wait_reason', 'wake'];
  v_keys text[];
  v_k text;
  v_kind text;
  v_wait text;
  v_fail jsonb := jsonb_build_object('ok', false, 'result_kind', NULL,
                                     'wait_reason', NULL, 'harness', NULL);
BEGIN
  IF p_result IS NULL
     OR jsonb_typeof(p_result) IS DISTINCT FROM 'object'
     OR p_result = '{}'::jsonb THEN
    RETURN v_fail;
  END IF;
  SELECT coalesce(array_agg(k ORDER BY k), '{}') INTO v_keys
    FROM jsonb_object_keys(p_result) AS k;
  FOREACH v_k IN ARRAY v_keys LOOP
    IF NOT (v_k = ANY (v_known)) THEN
      RETURN v_fail;
    END IF;
  END LOOP;
  IF NOT (p_result ? 'result_kind') THEN
    RETURN v_fail;
  END IF;
  v_kind := p_result->>'result_kind';
  IF v_kind IS NULL OR v_kind NOT IN ('progress', 'finish', 'wait', 'reject') THEN
    RETURN v_fail;
  END IF;
  IF p_result ? 'wait_reason' THEN
    v_wait := p_result->>'wait_reason';
    IF v_wait IS NULL OR v_wait NOT IN ('approval', 'evidence', 'quota') THEN
      RETURN v_fail;
    END IF;
  END IF;
  RETURN jsonb_build_object('ok', true, 'result_kind', v_kind,
                            'wait_reason', v_wait, 'harness', p_result);
END
$fn$;
