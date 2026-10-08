-- v13 agentctl (stage 40). Read-only observe wrapper. No new tables.
BEGIN;

CREATE FUNCTION public.v13_agentctl_observe(p_sid uuid, p_spec jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_keys text[];
  v_ids uuid[];
  v_elem jsonb;
  v_text text;
  v_n int;
  v_distinct int;
  v_want_hint boolean := false;
  v_rows jsonb;
  v_hints jsonb;
  v_pointers jsonb;
  v_shape jsonb := jsonb_build_object(
    'schema_version', 1,
    'ok', false,
    'reason', 'shape',
    'rows', '[]'::jsonb,
    'hints', '[]'::jsonb,
    'pointers', '[]'::jsonb);
BEGIN
  IF p_spec IS NULL THEN
    RETURN v_shape;
  END IF;
  IF jsonb_typeof(p_spec) IS DISTINCT FROM 'object' THEN
    RETURN v_shape;
  END IF;
  v_keys := public.v13_json_keys(p_spec);
  IF v_keys IS DISTINCT FROM ARRAY['ids']
     AND v_keys IS DISTINCT FROM ARRAY['hint', 'ids'] THEN
    RETURN v_shape;
  END IF;
  IF jsonb_typeof(p_spec->'ids') = 'string' THEN
    v_text := p_spec->>'ids';
    IF public.v13_canonical_uuid(v_text) IS NOT TRUE THEN
      RETURN v_shape;
    END IF;
    v_ids := ARRAY[v_text::uuid];
  ELSIF jsonb_typeof(p_spec->'ids') = 'array' THEN
    IF jsonb_array_length(p_spec->'ids') = 0 THEN
      RETURN v_shape;
    END IF;
    FOR v_elem IN SELECT value FROM jsonb_array_elements(p_spec->'ids') LOOP
      IF jsonb_typeof(v_elem) IS DISTINCT FROM 'string' THEN
        RETURN v_shape;
      END IF;
      v_text := v_elem #>> '{}';
      IF public.v13_canonical_uuid(v_text) IS NOT TRUE THEN
        RETURN v_shape;
      END IF;
    END LOOP;
    SELECT coalesce(
             array_agg((elem.value #>> '{}')::uuid ORDER BY elem.ordinality),
             '{}'::uuid[])
      INTO v_ids
      FROM jsonb_array_elements(p_spec->'ids')
        WITH ORDINALITY AS elem(value, ordinality);
  ELSE
    RETURN v_shape;
  END IF;
  SELECT count(*)::int, count(DISTINCT x)::int
    INTO v_n, v_distinct
    FROM unnest(v_ids) AS x;
  IF v_n IS NULL OR v_n = 0 OR v_n IS DISTINCT FROM v_distinct THEN
    RETURN v_shape;
  END IF;
  IF v_keys IS DISTINCT FROM ARRAY['ids'] THEN
    IF jsonb_typeof(p_spec->'hint') = 'boolean' THEN
      v_want_hint := (p_spec->>'hint')::boolean;
    ELSIF jsonb_typeof(p_spec->'hint') = 'string' THEN
      v_text := p_spec->>'hint';
      IF v_text = 'true' THEN
        v_want_hint := true;
      ELSIF v_text = 'false' THEN
        v_want_hint := false;
      ELSE
        RETURN v_shape;
      END IF;
    ELSE
      RETURN v_shape;
    END IF;
  END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(o) ORDER BY o.ordinal), '[]'::jsonb)
    INTO v_rows
    FROM public.v13_observe(p_sid, v_ids) AS o;
  IF v_rows = '[]'::jsonb THEN
    RETURN jsonb_build_object(
      'schema_version', 1,
      'ok', true,
      'rows', '[]'::jsonb,
      'hints', '[]'::jsonb,
      'pointers', '[]'::jsonb);
  END IF;
  IF v_want_hint THEN
    SELECT coalesce(jsonb_agg(
             jsonb_build_object(
               'session_id', elem->>'session_id',
               'hint', public.v13_scheduler_hint((elem->>'session_id')::uuid))
             ORDER BY (elem->>'ordinal')::int), '[]'::jsonb)
      INTO v_hints
      FROM jsonb_array_elements(v_rows) AS elem;
  ELSE
    v_hints := '[]'::jsonb;
  END IF;
  SELECT coalesce(jsonb_agg(
           jsonb_build_object(
             'session_id', e.session_id,
             'event_id', e.event_id,
             'seq', e.seq,
             'payload', e.payload)
           ORDER BY (elem->>'ordinal')::int, e.seq, e.event_id),
           '[]'::jsonb)
    INTO v_pointers
    FROM jsonb_array_elements(v_rows) AS elem
    JOIN public.events e
      ON e.session_id = (elem->>'session_id')::uuid
     AND e.type = 'workflow/pointer';
  RETURN jsonb_build_object(
    'schema_version', 1,
    'ok', true,
    'rows', v_rows,
    'hints', v_hints,
    'pointers', v_pointers);
END
$fn$;

REVOKE EXECUTE ON FUNCTION public.v13_agentctl_observe(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_agentctl_observe(uuid, jsonb) TO v13_route;

INSERT INTO tools (name, description, kind, handler, param_spec, enabled)
VALUES (
  'agentctl_observe',
  'Observe authorized child sessions, optional scheduler hints, and existing workflow pointers.',
  'sql',
  'v13_agentctl_observe',
  jsonb_build_object(
    'ids', jsonb_build_object(
      'question', 'Which session UUID or UUIDs should be observed?',
      'stated', 'Does the user specify the session UUIDs to observe?'),
    'hint', jsonb_build_object(
      'question', 'Should scheduler hints be included?',
      'stated', 'Does the user explicitly request scheduler hints?')),
  true);

COMMENT ON FUNCTION public.v13_agentctl_observe(uuid, jsonb) IS
  'Read-only. Unauthorized ids hide the whole batch. Does not write a workflow pointer.';

COMMIT;
