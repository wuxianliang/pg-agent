-- v13 agentctl verbs (stage 41). Three DEFINER writers plus predicate replacements.
-- Comments that name IO routines stay outside $fn$ bodies.
BEGIN;

CREATE OR REPLACE FUNCTION public.v13_named_sql_writer(p_handler text) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $named$
  SELECT CASE
    WHEN p_handler IN ('v13_spawn_subsession', 'public.v13_spawn_subsession') THEN
      '{"mutating":false,"write_targets":["artifacts","events","latches","sessions"]}'::jsonb
    WHEN p_handler IN ('v13_agentctl_steer', 'public.v13_agentctl_steer') THEN
      '{"mutating":false,"write_targets":["events","sessions"]}'::jsonb
    WHEN p_handler IN ('v13_agentctl_answer', 'public.v13_agentctl_answer') THEN
      '{"mutating":false,"write_targets":["effects","events","sessions"]}'::jsonb
    WHEN p_handler IN ('v13_agentctl_cancel', 'public.v13_agentctl_cancel') THEN
      '{"mutating":false,"write_targets":["effects","events","sessions"]}'::jsonb
    ELSE NULL
  END
$named$;

CREATE OR REPLACE FUNCTION public.v13_spawn_writer_ok(p_handler text) RETURNS boolean
LANGUAGE sql STABLE AS $writer$
  SELECT EXISTS (
    SELECT 1
      FROM pg_proc p
      JOIN pg_roles r ON r.oid = p.proowner
     WHERE p.proname = CASE
             WHEN p_handler LIKE 'public.%' THEN split_part(p_handler, '.', 2)
             ELSE p_handler END
       AND oidvectortypes(p.proargtypes) = 'uuid, jsonb'
       AND p.prorettype = 'jsonb'::regtype
       AND p.provolatile = 'v'
       AND p.prosecdef
       AND r.rolname = 'v13_spawn_owner'
       AND cardinality(p.proconfig) = 1
       AND replace(p.proconfig[1], ' ', '') = 'search_path=pg_catalog,public'
       AND p.proacl IS NOT NULL
       AND NOT EXISTS (
         SELECT 1 FROM aclexplode(p.proacl) a
          WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE')
       AND has_function_privilege('v13_route', p.oid, 'EXECUTE')
       AND position('dblink' in lower(p.prosrc)) = 0
       AND position('pg_net' in lower(p.prosrc)) = 0
       AND position('copy program' in lower(p.prosrc)) = 0
       AND position('lo_import' in lower(p.prosrc)) = 0
       AND position('lo_export' in lower(p.prosrc)) = 0
       AND position('pg_read_file' in lower(p.prosrc)) = 0
       AND position('pg_write_file' in lower(p.prosrc)) = 0
       AND v13_named_sql_writer(p_handler) = CASE
             WHEN p_handler IN ('v13_spawn_subsession', 'public.v13_spawn_subsession') THEN
               '{"mutating":false,"write_targets":["artifacts","events","latches","sessions"]}'::jsonb
             WHEN p_handler IN ('v13_agentctl_steer', 'public.v13_agentctl_steer') THEN
               '{"mutating":false,"write_targets":["events","sessions"]}'::jsonb
             WHEN p_handler IN ('v13_agentctl_answer', 'public.v13_agentctl_answer') THEN
               '{"mutating":false,"write_targets":["effects","events","sessions"]}'::jsonb
             WHEN p_handler IN ('v13_agentctl_cancel', 'public.v13_agentctl_cancel') THEN
               '{"mutating":false,"write_targets":["effects","events","sessions"]}'::jsonb
             ELSE NULL
           END)
$writer$;

CREATE FUNCTION public.v13_agentctl_steer(p_sid uuid, p_spec jsonb)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $steer$
DECLARE
  v_keys text[];
  v_target_text text;
  v_target uuid;
  v_text text;
  v_name text;
  v_ver int;
  v_event uuid;
  v_seq bigint;
  v_payload jsonb;
BEGIN
  IF p_spec IS NULL THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF jsonb_typeof(p_spec) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_keys := public.v13_json_keys(p_spec);
  IF v_keys IS DISTINCT FROM ARRAY['target', 'text'] THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF jsonb_typeof(p_spec->'target') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_target_text := p_spec->>'target';
  IF public.v13_canonical_uuid(v_target_text) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_target := v_target_text::uuid;
  IF jsonb_typeof(p_spec->'text') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_text := btrim(p_spec->>'text');
  IF char_length(v_text) < 1 THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF char_length(v_text) > 1024 THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  SELECT route_policy_name, route_policy_version
    INTO v_name, v_ver
    FROM public.sessions
   WHERE session_id = p_sid
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF v_name IS DISTINCT FROM 'controller' THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF v_ver IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF public.v13_control_authorized(p_sid, v_target) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  v_event := gen_random_uuid();
  v_payload := jsonb_build_object(
    'schema_version', 1,
    'text', v_text,
    'source_principal', 'controller');
  v_seq := public.v13_append_event(v_target, v_event, 'steer/injected', v_payload);
  RETURN jsonb_build_object(
    'schema_version', 1,
    'caller', p_sid::text,
    'target', v_target_text,
    'event_id', v_event,
    'seq', v_seq);
END
$steer$;

CREATE FUNCTION public.v13_agentctl_answer(p_sid uuid, p_spec jsonb)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $answer$
DECLARE
  v_keys text[];
  v_target_text text;
  v_target uuid;
  v_eid_text text;
  v_eid uuid;
  v_response text;
  v_name text;
  v_ver int;
  v_row effects;
  v_attempt int;
  v_fence bigint;
  v_result jsonb;
  v_word text;
BEGIN
  IF p_spec IS NULL THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF jsonb_typeof(p_spec) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_keys := public.v13_json_keys(p_spec);
  IF v_keys IS DISTINCT FROM ARRAY['effect_id', 'response', 'target'] THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF jsonb_typeof(p_spec->'target') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_target_text := p_spec->>'target';
  IF public.v13_canonical_uuid(v_target_text) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_target := v_target_text::uuid;
  IF jsonb_typeof(p_spec->'effect_id') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_eid_text := p_spec->>'effect_id';
  IF public.v13_canonical_uuid(v_eid_text) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_eid := v_eid_text::uuid;
  IF jsonb_typeof(p_spec->'response') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_response := btrim(p_spec->>'response');
  IF char_length(v_response) < 1 THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF char_length(v_response) > 1024 THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  SELECT route_policy_name, route_policy_version
    INTO v_name, v_ver
    FROM public.sessions
   WHERE session_id = p_sid
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF v_name IS DISTINCT FROM 'controller' THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF v_ver IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF public.v13_control_authorized(p_sid, v_target) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  PERFORM 1 FROM public.sessions WHERE session_id = v_target FOR UPDATE;
  SELECT * INTO v_row FROM public.effects WHERE effect_id = v_eid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: agentctl answer';
  END IF;
  IF v_row.session_id IS DISTINCT FROM v_target THEN
    RAISE EXCEPTION 'v13: agentctl answer';
  END IF;
  IF v_row.kind IS DISTINCT FROM 'human' THEN
    RAISE EXCEPTION 'v13: agentctl answer';
  END IF;
  IF v_row.status IS DISTINCT FROM 'ready' THEN
    RAISE EXCEPTION 'v13: agentctl answer';
  END IF;
  IF NOT (v_row.request ? 'interaction_ref') THEN
    RAISE EXCEPTION 'v13: agentctl answer';
  END IF;
  UPDATE public.effects
     SET status = 'claimed',
         attempt_no = attempt_no + 1,
         fence = fence + 1,
         lease_owner = 'agentctl_answer',
         lease_until = clock_timestamp() + interval '1 hour'
   WHERE effect_id = v_eid
     AND session_id = v_target
     AND status = 'ready'
     AND kind = 'human'
   RETURNING attempt_no, fence
    INTO v_attempt, v_fence;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: agentctl answer';
  END IF;
  v_result := jsonb_build_object(
    'schema_version', 1,
    'interaction_ref', v_row.request->'interaction_ref',
    'response', v_response);
  v_word := public.v13_complete(p_sid, v_eid, v_attempt, v_fence, 'succeeded', v_result);
  IF v_word IS DISTINCT FROM 'accepted' THEN
    RAISE EXCEPTION 'v13: agentctl answer not accepted';
  END IF;
  RETURN jsonb_build_object(
    'schema_version', 1,
    'caller', p_sid::text,
    'target', v_target_text,
    'effect_id', v_eid_text,
    'outcome', 'accepted');
END
$answer$;

CREATE FUNCTION public.v13_agentctl_cancel(p_sid uuid, p_spec jsonb)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $cancel$
DECLARE
  v_keys text[];
  v_target_text text;
  v_target uuid;
  v_name text;
  v_ver int;
  v_word text;
BEGIN
  IF p_spec IS NULL THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF jsonb_typeof(p_spec) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_keys := public.v13_json_keys(p_spec);
  IF v_keys IS DISTINCT FROM ARRAY['target'] THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  IF jsonb_typeof(p_spec->'target') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_target_text := p_spec->>'target';
  IF public.v13_canonical_uuid(v_target_text) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: agentctl args';
  END IF;
  v_target := v_target_text::uuid;
  SELECT route_policy_name, route_policy_version
    INTO v_name, v_ver
    FROM public.sessions
   WHERE session_id = p_sid
   FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF v_name IS DISTINCT FROM 'controller' THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF v_ver IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'v13: agentctl policy';
  END IF;
  IF public.v13_control_authorized(p_sid, v_target) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  v_word := public.v13_cancel(p_sid, v_target);
  IF v_word IS DISTINCT FROM 'accepted' THEN
    IF v_word IS DISTINCT FROM 'replay' THEN
      RAISE EXCEPTION 'v13: agentctl cancel';
    END IF;
  END IF;
  RETURN jsonb_build_object(
    'schema_version', 1,
    'caller', p_sid::text,
    'target', v_target_text,
    'outcome', v_word);
END
$cancel$;

ALTER FUNCTION public.v13_agentctl_steer(uuid, jsonb) OWNER TO v13_spawn_owner;
ALTER FUNCTION public.v13_agentctl_answer(uuid, jsonb) OWNER TO v13_spawn_owner;
ALTER FUNCTION public.v13_agentctl_cancel(uuid, jsonb) OWNER TO v13_spawn_owner;

REVOKE EXECUTE ON FUNCTION
  public.v13_agentctl_steer(uuid, jsonb),
  public.v13_agentctl_answer(uuid, jsonb),
  public.v13_agentctl_cancel(uuid, jsonb)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
  public.v13_agentctl_steer(uuid, jsonb),
  public.v13_agentctl_answer(uuid, jsonb),
  public.v13_agentctl_cancel(uuid, jsonb)
TO v13_route;

INSERT INTO tools (name, description, kind, handler, param_spec, enabled)
VALUES (
  'agentctl_steer',
  'Inject steering text into an authorized child session.',
  'sql',
  'v13_agentctl_steer',
  jsonb_build_object(
    'target', jsonb_build_object(
      'question', 'Which child session UUID should receive steering text?',
      'stated', 'Does the user specify the child session UUID to steer?'),
    'text', jsonb_build_object(
      'question', 'What steering text should be injected?',
      'stated', 'Does the user specify the steering text?')),
  true),
(
  'agentctl_answer',
  'Answer a ready human interaction in an authorized child session.',
  'sql',
  'v13_agentctl_answer',
  jsonb_build_object(
    'target', jsonb_build_object(
      'question', 'Which child session UUID contains the human interaction?',
      'stated', 'Does the user specify the child session UUID to answer?'),
    'effect_id', jsonb_build_object(
      'question', 'Which human effect UUID should be answered?',
      'stated', 'Does the user specify the human effect UUID to answer?'),
    'response', jsonb_build_object(
      'question', 'What response should be submitted to the human interaction?',
      'stated', 'Does the user specify the response to the human interaction?')),
  true),
(
  'agentctl_cancel',
  'Request cancellation of an authorized child session.',
  'sql',
  'v13_agentctl_cancel',
  jsonb_build_object(
    'target', jsonb_build_object(
      'question', 'Which child session UUID should be cancelled?',
      'stated', 'Does the user specify the child session UUID to cancel?')),
  true);

DO $policy$
DECLARE
  v_state text;
  v_extra int;
  v_missing int;
BEGIN
  SELECT state INTO v_state
    FROM public.v13_route_policies
   WHERE policy_name = 'default' AND policy_version = 2;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: agentctl default/2 missing';
  END IF;
  IF v_state IS DISTINCT FROM 'frozen' THEN
    RAISE EXCEPTION 'v13: agentctl default/2';
  END IF;
  INSERT INTO public.v13_route_policies (policy_name, policy_version)
  VALUES ('controller', 1);
  INSERT INTO public.thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
  SELECT 'controller', 1, signal, band_no, lo, hi, action
    FROM public.thresholds
   WHERE policy_name = 'default' AND policy_version = 2;
  INSERT INTO public.thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
  VALUES
    ('controller', 1, 'param::agentctl_observe::ids', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_observe::ids', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_observe::hint', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_observe::hint', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_steer::target', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_steer::target', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_steer::text', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_steer::text', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_answer::target', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_answer::target', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_answer::effect_id', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_answer::effect_id', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_answer::response', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_answer::response', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'param::agentctl_cancel::target', 1, 0.60, 'Infinity', 'pass'),
    ('controller', 1, 'stated::agentctl_cancel::target', 1, 0.60, 'Infinity', 'pass');
  SELECT count(*) INTO v_extra
    FROM (
      SELECT signal, band_no, lo, hi, action
        FROM public.thresholds
       WHERE policy_name = 'controller' AND policy_version = 1
      EXCEPT
      SELECT signal, band_no, lo, hi, action
        FROM (
          SELECT signal, band_no, lo, hi, action
            FROM public.thresholds
           WHERE policy_name = 'default' AND policy_version = 2
          UNION ALL
          SELECT *
            FROM (VALUES
              ('param::agentctl_observe::ids', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_observe::ids', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_observe::hint', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_observe::hint', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_steer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_steer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_steer::text', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_steer::text', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_answer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_answer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_answer::effect_id', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_answer::effect_id', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_answer::response', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_answer::response', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_cancel::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_cancel::target', 1, 0.60::float8, 'Infinity'::float8, 'pass')
            ) AS band(signal, band_no, lo, hi, action)
        ) expected
    ) extra;
  SELECT count(*) INTO v_missing
    FROM (
      SELECT signal, band_no, lo, hi, action
        FROM (
          SELECT signal, band_no, lo, hi, action
            FROM public.thresholds
           WHERE policy_name = 'default' AND policy_version = 2
          UNION ALL
          SELECT *
            FROM (VALUES
              ('param::agentctl_observe::ids', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_observe::ids', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_observe::hint', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_observe::hint', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_steer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_steer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_steer::text', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_steer::text', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_answer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_answer::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_answer::effect_id', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_answer::effect_id', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_answer::response', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_answer::response', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('param::agentctl_cancel::target', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
              ('stated::agentctl_cancel::target', 1, 0.60::float8, 'Infinity'::float8, 'pass')
            ) AS band(signal, band_no, lo, hi, action)
        ) expected
      EXCEPT
      SELECT signal, band_no, lo, hi, action
        FROM public.thresholds
       WHERE policy_name = 'controller' AND policy_version = 1
    ) missing;
  IF v_extra <> 0 OR v_missing <> 0 THEN
    RAISE EXCEPTION 'v13: agentctl controller bands';
  END IF;
  UPDATE public.v13_route_policies
     SET state = 'frozen'
   WHERE policy_name = 'controller' AND policy_version = 1;
END
$policy$;

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'controller_surface',
  1,
  jsonb_build_object(
    'schema_version', 1,
    'route_policy_name', 'controller',
    'route_policy_version', 1,
    'tools', jsonb_build_array(
      'agentctl_observe',
      'agentctl_steer',
      'agentctl_answer',
      'agentctl_cancel')),
  true);

COMMENT ON FUNCTION public.v13_agentctl_steer(uuid, jsonb) IS
  'DEFINER writer. Actor is p_sid. Payload keys are schema_version, text, source_principal.';
COMMENT ON FUNCTION public.v13_agentctl_answer(uuid, jsonb) IS
  'DEFINER writer. Claims one ready human row, then six-arg complete with literal succeeded.';
COMMENT ON FUNCTION public.v13_agentctl_cancel(uuid, jsonb) IS
  'DEFINER writer. Calls two-arg cancel with actor p_sid. Does not close out.';

COMMIT;
