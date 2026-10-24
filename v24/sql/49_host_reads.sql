-- M-H host discovery surface: nine public read-only functions plus one
-- internal scope-authorization helper.  Every function is STABLE, runs with a
-- fixed search_path, takes no G lock, and only observes committed rows.  The
-- helper is deliberately not granted to protocol roles; the nine public
-- functions are granted in 50_permissions.sql.
--
-- Error envelopes mirror poll: a denied caller cannot distinguish a missing
-- object from a foreign one.  Shape errors use invalid_args.  Successful empty
-- reads return an empty list and a null cursor.

CREATE FUNCTION v24.host_scope_allowed(p_scope uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM v24.scopes s
     WHERE s.scope_id = p_scope
       AND (s.owner_principal = v24.principal_id(session_user)
            OR pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE')));
$$;

CREATE FUNCTION v24.host_scopes(p_scope uuid DEFAULT NULL,
  p_after uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_scope IS NOT NULL AND NOT v24.host_scope_allowed(p_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY scope_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT s.scope_id,
             jsonb_build_object(
               'scope_id', s.scope_id,
               'parent_id', s.parent_id,
               'root_id', s.root_id,
               'owner_principal', s.owner_principal,
               'close_requested_at', s.close_requested_at,
               'closed_at', s.closed_at) AS item
        FROM v24.scopes s
       WHERE (p_scope IS NULL OR s.scope_id = p_scope)
         AND (p_after IS NULL OR s.scope_id > p_after)
         AND (pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE')
              OR s.owner_principal = v24.principal_id(session_user))
       ORDER BY s.scope_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object('scope_id', v_last -> 'scope_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_runs(p_scope uuid,
  p_after_created_at timestamptz DEFAULT NULL,
  p_after_run_id uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_scope IS NULL
     OR ((p_after_created_at IS NULL) <> (p_after_run_id IS NULL)) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  IF NOT v24.host_scope_allowed(p_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY created_at, run_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT r.created_at, r.run_id, v24.run_projection(r.run_id) AS item
        FROM v24.runs r
       WHERE r.scope_id = p_scope
         AND (p_after_created_at IS NULL
              OR (r.created_at, r.run_id) > (p_after_created_at, p_after_run_id))
       ORDER BY r.created_at, r.run_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object(
        'created_at', v_last -> 'created_at',
        'run_id', v_last -> 'run_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_effects(p_scope uuid,
  p_after_created_at timestamptz DEFAULT NULL,
  p_after_effect_id uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_scope IS NULL
     OR ((p_after_created_at IS NULL) <> (p_after_effect_id IS NULL)) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  IF NOT v24.host_scope_allowed(p_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY created_at, effect_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT e.created_at, e.effect_id,
             jsonb_build_object(
               'effect_id', e.effect_id,
               'parent_effect_id', e.parent_effect_id,
               'ordinal', e.ordinal,
               'scope_id', e.scope_id,
               'run_id', e.run_id,
               'fiber_id', e.fiber_id,
               'episode_id', e.episode_id,
               'pin_id', e.pin_id,
               'epoch_no', e.epoch_no,
               'generation', e.generation,
               'kind', e.kind,
               'status', e.status,
               'replay_policy', e.replay_policy,
               'attempt_no', e.attempt_no,
               'fence', e.fence,
               'claim_owner', e.claim_owner,
               'cancel_requested', e.cancel_requested,
               'request', e.request,
               'outcome', e.outcome,
               'lease_until', e.lease_until,
               'resource_quiesced_at', e.resource_quiesced_at,
               'created_at', e.created_at,
               'settled_at', e.settled_at) AS item
        FROM v24.effects e
       WHERE e.scope_id = p_scope
         AND e.status IN ('ready', 'claimed')
         AND e.kind IN ('host_prepare', 'host_release', 'inspect_resource',
                        'model_call', 'tool_call')
         AND (p_after_created_at IS NULL
              OR (e.created_at, e.effect_id) > (p_after_created_at, p_after_effect_id))
       ORDER BY e.created_at, e.effect_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object(
        'created_at', v_last -> 'created_at',
        'effect_id', v_last -> 'effect_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_run_effects(p_run uuid,
  p_after_created_at timestamptz DEFAULT NULL,
  p_after_effect_id uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_scope uuid;
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_run IS NULL
     OR ((p_after_created_at IS NULL) <> (p_after_effect_id IS NULL)) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  SELECT r.scope_id INTO v_scope FROM v24.runs r WHERE r.run_id = p_run;
  IF NOT FOUND OR NOT v24.host_scope_allowed(v_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY created_at, effect_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT e.created_at, e.effect_id,
             jsonb_build_object(
               'effect_id', e.effect_id,
               'parent_effect_id', e.parent_effect_id,
               'ordinal', e.ordinal,
               'scope_id', e.scope_id,
               'run_id', e.run_id,
               'fiber_id', e.fiber_id,
               'episode_id', e.episode_id,
               'pin_id', e.pin_id,
               'epoch_no', e.epoch_no,
               'generation', e.generation,
               'kind', e.kind,
               'status', e.status,
               'replay_policy', e.replay_policy,
               'attempt_no', e.attempt_no,
               'fence', e.fence,
               'claim_owner', e.claim_owner,
               'cancel_requested', e.cancel_requested,
               'request', e.request,
               'outcome', e.outcome,
               'lease_until', e.lease_until,
               'resource_quiesced_at', e.resource_quiesced_at,
               'created_at', e.created_at,
               'settled_at', e.settled_at) AS item
        FROM v24.effects e
       WHERE e.run_id = p_run
         AND e.kind IN ('model_call', 'tool_call')
         AND (p_after_created_at IS NULL
              OR (e.created_at, e.effect_id) > (p_after_created_at, p_after_effect_id))
       ORDER BY e.created_at, e.effect_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object(
        'created_at', v_last -> 'created_at',
        'effect_id', v_last -> 'effect_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_effect(p_effect uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  e v24.effects%ROWTYPE;
  v_scope uuid;
  v_item jsonb;
BEGIN
  IF p_effect IS NULL THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  SELECT * INTO e FROM v24.effects x WHERE x.effect_id = p_effect;
  IF NOT FOUND OR e.kind NOT IN ('host_prepare', 'host_release',
                                 'inspect_resource', 'model_call', 'tool_call') THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  v_scope := e.scope_id;
  IF v_scope IS NULL AND e.run_id IS NOT NULL THEN
    SELECT r.scope_id INTO v_scope FROM v24.runs r WHERE r.run_id = e.run_id;
  END IF;
  IF v_scope IS NULL AND e.request ? 'install_id'
     AND (e.request ->> 'install_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
    SELECT i.scope_id INTO v_scope FROM v24.installs i
     WHERE i.install_id = (e.request ->> 'install_id')::uuid;
  END IF;
  IF v_scope IS NULL OR NOT v24.host_scope_allowed(v_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  v_item := jsonb_build_object(
    'effect_id', e.effect_id,
    'parent_effect_id', e.parent_effect_id,
    'ordinal', e.ordinal,
    'scope_id', e.scope_id,
    'run_id', e.run_id,
    'fiber_id', e.fiber_id,
    'episode_id', e.episode_id,
    'pin_id', e.pin_id,
    'epoch_no', e.epoch_no,
    'generation', e.generation,
    'kind', e.kind,
    'status', e.status,
    'replay_policy', e.replay_policy,
    'attempt_no', e.attempt_no,
    'fence', e.fence,
    'claim_owner', e.claim_owner,
    'cancel_requested', e.cancel_requested,
    'request', e.request,
    'outcome', e.outcome,
    'lease_until', e.lease_until,
    'resource_quiesced_at', e.resource_quiesced_at,
    'created_at', e.created_at,
    'settled_at', e.settled_at);
  RETURN jsonb_build_object('v', 1, 'effect', v_item);
END;
$$;

CREATE FUNCTION v24.host_scope_installs(p_scope uuid,
  p_after uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_scope IS NULL THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  IF NOT v24.host_scope_allowed(p_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY install_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT i.install_id,
             jsonb_build_object(
               'install_id', i.install_id,
               'scope_id', i.scope_id,
               'owner_fiber_id', i.owner_fiber_id,
               'owner_episode_id', i.owner_episode_id,
               'identity', i.identity,
               'version', i.version,
               'manifest', i.manifest,
               'manifest_digest', encode(i.manifest_digest, 'hex'),
               'requires', i.requires,
               'provides', i.provides,
               'artifact_digest', encode(i.artifact_digest, 'hex'),
               'adapter_digest', encode(i.adapter_digest, 'hex'),
               'owner_principal', i.owner_principal,
               'state', i.state,
               'created_by_effect', i.created_by_effect,
               'dispose_effect', i.dispose_effect,
               'disposed_at', i.disposed_at) AS item
        FROM v24.installs i
       WHERE i.scope_id = p_scope
         AND (p_after IS NULL OR i.install_id > p_after)
       ORDER BY i.install_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object('install_id', v_last -> 'install_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_install_fibers(p_install uuid,
  p_after uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_scope uuid;
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_install IS NULL THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  SELECT i.scope_id INTO v_scope FROM v24.installs i
   WHERE i.install_id = p_install;
  IF NOT FOUND OR NOT v24.host_scope_allowed(v_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY fiber_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT f.fiber_id,
             jsonb_build_object(
               'fiber_id', f.fiber_id,
               'install_id', f.install_id,
               'scope_id', f.scope_id,
               'owner_fiber_id', f.owner_fiber_id,
               'owner_episode_id', f.owner_episode_id,
               'want_on', f.want_on,
               'control_seq', f.control_seq,
               'current_episode_id', f.current_episode_id,
               'disposed_at', f.disposed_at,
               'failure_seq', f.failure_seq,
               'failure', f.failure,
               'next_contribution_seq', f.next_contribution_seq,
               'created_by_effect', f.created_by_effect) AS item
        FROM v24.fibers f
       WHERE f.install_id = p_install
         AND (p_after IS NULL OR f.fiber_id > p_after)
       ORDER BY f.fiber_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object('fiber_id', v_last -> 'fiber_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_run_pins(p_run uuid,
  p_after uuid DEFAULT NULL, p_limit integer DEFAULT 64)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_limit integer := greatest(least(coalesce(p_limit, 0), 64), 0);
  v_scope uuid;
  v_items jsonb;
  v_last jsonb;
  v_more boolean := false;
BEGIN
  IF p_run IS NULL THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  SELECT r.scope_id INTO v_scope FROM v24.runs r WHERE r.run_id = p_run;
  IF NOT FOUND OR NOT v24.host_scope_allowed(v_scope) THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  IF v_limit = 0 THEN
    RETURN jsonb_build_object('v', 1, 'items', '[]'::jsonb, 'limit', 0,
      'has_more', false, 'next_cursor', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(item ORDER BY pin_id), '[]'::jsonb)
    INTO v_items
    FROM (
      SELECT p.pin_id,
             jsonb_build_object(
               'pin_id', p.pin_id,
               'consumer_type', p.consumer_type,
               'consumer_run_id', p.consumer_run_id,
               'consumer_epoch', p.consumer_epoch,
               'key', p.key,
               'slot_id', p.slot_id,
               'provider_fiber_id', p.provider_fiber_id,
               'provider_episode_id', p.provider_episode_id,
               'provider_install_id', (
                 SELECT f.install_id FROM v24.fibers f
                  WHERE f.fiber_id = p.provider_fiber_id),
               'descriptor', (
                 SELECT s.descriptor FROM v24.slots s
                  WHERE s.slot_id = p.slot_id),
               'descriptor_digest', encode(p.descriptor_digest, 'hex'),
               'created_by_effect', p.created_by_effect,
               'released_by_effect', p.released_by_effect,
               'released_at', p.released_at) AS item
        FROM v24.pins p
       WHERE p.consumer_type = 'run'
         AND p.consumer_run_id = p_run
         AND (p_after IS NULL OR p.pin_id > p_after)
       ORDER BY p.pin_id
       LIMIT v_limit + 1
    ) q;
  IF jsonb_array_length(v_items) > v_limit THEN
    v_more := true;
    v_items := v_items - v_limit;
  END IF;
  IF v_more THEN
    v_last := v_items -> (v_limit - 1);
    RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
      'has_more', true,
      'next_cursor', jsonb_build_object('pin_id', v_last -> 'pin_id'));
  END IF;
  RETURN jsonb_build_object('v', 1, 'items', v_items, 'limit', v_limit,
    'has_more', false, 'next_cursor', NULL);
END;
$$;

CREATE FUNCTION v24.host_request(p_request_key text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_principal uuid;
  r v24.requests%ROWTYPE;
  v_item jsonb;
BEGIN
  IF p_request_key IS NULL OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'invalid_args'));
  END IF;
  v_principal := v24.principal_id(session_user);
  SELECT * INTO r FROM v24.requests x
   WHERE x.principal_id = v_principal AND x.request_key = p_request_key;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('v', 1, 'error',
      jsonb_build_object('code', 'not_found_or_denied'));
  END IF;
  v_item := jsonb_build_object(
    'request_key', r.request_key,
    'kind', r.kind,
    'request_bytes_base64', encode(r.request_bytes, 'base64'),
    'request_digest_hex', encode(r.request_digest, 'hex'),
    'response', r.response,
    'effect_id', r.effect_id,
    'created_at', r.created_at);
  RETURN jsonb_build_object('v', 1, 'request', v_item);
END;
$$;
