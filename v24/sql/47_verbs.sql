-- S3 W1: closed read-only DEFINER surface. Verb wrappers follow in W2+.
CREATE FUNCTION v24.run_owner(p_run uuid)
RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
  SELECT e.requester_id
  FROM v24.effects e
  WHERE e.run_id = p_run AND e.kind = 'command_start'
  ORDER BY e.created_at
  LIMIT 1;
$$;

-- Frozen S3 C14 projection: expose only these run fields.
CREATE FUNCTION v24.run_projection(p_run uuid)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
  SELECT jsonb_build_object(
    'run_id', r.run_id, 'scope_id', r.scope_id, 'status', r.status,
    'epoch_no', r.epoch_no, 'registration_generation', r.registration_generation,
    'turn_no', r.turn_no, 'driving_generation', r.driving_generation,
    'interaction', r.interaction, 'pending_steer', r.pending_steer,
    'close_intent', r.close_intent, 'result', r.result,
    'remaining_steps', r.remaining_steps, 'remaining_tokens', r.remaining_tokens,
    'remaining_tool_calls', r.remaining_tool_calls,
    'remaining_wall_ms', r.remaining_wall_ms, 'revision', r.revision,
    'created_at', r.created_at, 'updated_at', r.updated_at, 'ended_at', r.ended_at,
    'owner_fiber_id', r.owner_fiber_id, 'owner_episode_id', r.owner_episode_id)
  FROM v24.runs r
  WHERE r.run_id = p_run;
$$;

-- S3 W3 read entry points. Authorization is based on the authenticated login,
-- and the projection is never returned before that check succeeds.
CREATE FUNCTION v24.poll(p_run_id uuid, p_after_revision bigint DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  current_run v24.runs%ROWTYPE;
  projection jsonb;
  run_events jsonb;
BEGIN
  SELECT * INTO current_run FROM v24.runs WHERE run_id = p_run_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('v', 1, 'error', jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v24.run_owner(p_run_id) IS DISTINCT FROM v24.principal_id(session_user)
     AND NOT pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE') THEN
    RETURN jsonb_build_object('v', 1, 'error', jsonb_build_object('code', 'not_found_or_denied'));
  END IF;

  projection := v24.run_projection(p_run_id);
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'seq', e.seq, 'event_kind', e.event_kind,
           'payload', e.payload, 'created_at', e.created_at) ORDER BY e.seq), '[]'::jsonb)
    INTO run_events
    FROM (SELECT seq, event_kind, payload, created_at
            FROM v24.events
           WHERE entity_type = 'run' AND entity_id = p_run_id
           ORDER BY seq
           LIMIT 64) AS e;
  RETURN jsonb_build_object(
    'v', 1,
    'revision', current_run.revision,
    'changed', current_run.revision > p_after_revision,
    'run', projection,
    'events', run_events);
END;
$$;

-- S3 W4: only local call shape is checked outside advance.
CREATE FUNCTION v24.cancel(p_run_id uuid, p_expected_generation bigint,
  p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_run_id IS NULL OR p_expected_generation IS NULL OR p_expected_generation < 0
     OR p_request_key IS NULL OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  payload := jsonb_build_object('run_id',p_run_id,
    'expected_generation',p_expected_generation);
  RETURN v24.advance(
    v24.effect_id_for(v24.principal_id(session_user),p_request_key,'command_cancel'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object(
      'op','admit_and_apply','kind','command_cancel','request_key',p_request_key,
      'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;

CREATE FUNCTION v24.wait_check(p_run_id uuid, p_registration_generation bigint,
  p_epoch bigint, p_after_event_seq bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  current_run v24.runs%ROWTYPE;
  projection jsonb;
  run_events jsonb;
  wake_reason text;
BEGIN
  SELECT * INTO current_run FROM v24.runs WHERE run_id = p_run_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('v', 1, 'error', jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v24.run_owner(p_run_id) IS DISTINCT FROM v24.principal_id(session_user)
     AND NOT pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE') THEN
    RETURN jsonb_build_object('v', 1, 'error', jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF current_run.registration_generation IS DISTINCT FROM p_registration_generation THEN
    RETURN jsonb_build_object('v', 1, 'error', jsonb_build_object('code', 'registration_stale'));
  END IF;

  projection := v24.run_projection(p_run_id);
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'seq', e.seq, 'event_kind', e.event_kind,
           'payload', e.payload, 'created_at', e.created_at) ORDER BY e.seq), '[]'::jsonb)
    INTO run_events
    FROM (SELECT seq, event_kind, payload, created_at
            FROM v24.events
           WHERE entity_type = 'run' AND entity_id = p_run_id
             AND seq > p_after_event_seq
           ORDER BY seq
           LIMIT 64) AS e;

  wake_reason := CASE
    WHEN current_run.status IN ('completed', 'failed', 'cancelled', 'blocked_unknown') THEN 'terminal'
    WHEN current_run.interaction IS NOT NULL THEN 'interaction'
    WHEN p_epoch IS DISTINCT FROM current_run.epoch_no THEN 'epoch'
    WHEN jsonb_array_length(run_events) > 0 THEN 'event'
    ELSE 'none'
  END;
  RETURN jsonb_build_object(
    'v', 1,
    'run', projection,
    'events', run_events,
    'wake', jsonb_build_object('ready', wake_reason <> 'none', 'reason', wake_reason));
END;
$$;

-- S3 W5: steer defers behind claims and never cancels claimed work.
CREATE FUNCTION v24.steer(p_run_id uuid, p_expected_generation bigint,
  p_instruction text, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_run_id IS NULL OR p_expected_generation IS NULL OR p_expected_generation < 0
     OR p_instruction IS NULL OR length(p_instruction) NOT BETWEEN 1 AND 8192
     OR p_request_key IS NULL OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  payload := jsonb_build_object('run_id',p_run_id,
    'expected_generation',p_expected_generation,'instruction',p_instruction);
  RETURN v24.advance(
    v24.effect_id_for(v24.principal_id(session_user),p_request_key,'command_steer'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object(
      'op','admit_and_apply','kind','command_steer','request_key',p_request_key,
      'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;

-- S3 W6: consume an interaction only through advance's locked command path.
CREATE FUNCTION v24.respond(p_run_id uuid, p_interaction_id uuid, p_response jsonb,
  p_expected_generation bigint, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_run_id IS NULL OR p_interaction_id IS NULL
     OR p_response IS NULL OR jsonb_typeof(p_response) IS DISTINCT FROM 'object'
     OR p_expected_generation IS NULL OR p_expected_generation < 0
     OR p_request_key IS NULL OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  payload := jsonb_build_object('run_id',p_run_id,'interaction_id',p_interaction_id,
    'response',p_response,'expected_generation',p_expected_generation);
  RETURN v24.advance(
    v24.effect_id_for(v24.principal_id(session_user),p_request_key,'command_respond'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object(
      'op','admit_and_apply','kind','command_respond','request_key',p_request_key,
      'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;

-- S3 W2 start entry point: validate only the local call shape, then delegate.
CREATE FUNCTION v24.start(p_scope_id uuid, p_owner_fiber_id uuid,
  p_input jsonb, p_budget jsonb, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_scope_id IS NULL
     OR p_input IS NULL OR jsonb_typeof(p_input) IS DISTINCT FROM 'object'
     OR p_budget IS NULL OR jsonb_typeof(p_budget) IS DISTINCT FROM 'object'
     OR p_request_key IS NULL OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  payload := jsonb_build_object(
    'scope_id', p_scope_id,
    'owner_fiber_id', p_owner_fiber_id,
    'input', p_input,
    'budget', p_budget);
  RETURN v24.advance(
    v24.effect_id_for(v24.principal_id(session_user), p_request_key, 'command_start'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object(
      'op','admit_and_apply','kind','command_start','request_key',p_request_key,
      'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;
