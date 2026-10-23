-- v24 S2 capability plane.
--
-- W1: the read-only resolver.  B.3 freezes the six-column shape; the live
-- predicate is the one frozen in the S2 plan (slot not withdrawn/released,
-- provider episode active, provider fiber not disposed, provider scope not
-- closing).  Routing is leaf-first along route_path and never falls back
-- across realms.  The function writes nothing.

CREATE FUNCTION v24.resolve(p_scope_id uuid, p_keys text[])
RETURNS TABLE(key text, slot_id uuid, provider_episode_id uuid,
              descriptor jsonb, descriptor_digest bytea, live boolean)
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
BEGIN
  IF coalesce(cardinality(p_keys), 0) > 256 THEN
    RAISE EXCEPTION 'v24.resolve: at most 256 keys'
      USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  WITH input AS (
    SELECT k.key, k.ord
    FROM unnest(p_keys) WITH ORDINALITY AS k(key, ord)
  ),
  ancestors AS (
    SELECT u.ord, s.scope_id, s.realm_routes, s.default_realm
    FROM v24.scopes root
    CROSS JOIN LATERAL unnest(root.route_path) WITH ORDINALITY AS u(scope_id, ord)
    JOIN v24.scopes s ON s.scope_id = u.scope_id
    WHERE root.scope_id = p_scope_id
  ),
  routed AS (
    SELECT i.ord, i.key,
           (SELECT a.realm_routes ->> i.key FROM ancestors a
             WHERE a.realm_routes ? i.key
             ORDER BY a.ord DESC LIMIT 1) AS explicit_realm,
           (SELECT a.default_realm FROM ancestors a
             WHERE a.default_realm IS NOT NULL
             ORDER BY a.ord DESC LIMIT 1) AS default_realm
    FROM input i
  ),
  target AS (
    SELECT r.ord, r.key, coalesce(r.explicit_realm, r.default_realm) AS realm
    FROM routed r
  ),
  hit AS (
    SELECT t.ord, s.slot_id, s.episode_id, s.descriptor, s.descriptor_digest
    FROM target t
    JOIN v24.slots s ON s.realm = t.realm AND s.key = t.key
    JOIN v24.episodes e ON e.episode_id = s.episode_id
    JOIN v24.fibers f ON f.fiber_id = s.fiber_id
    JOIN v24.scopes sc ON sc.scope_id = f.scope_id
    WHERE s.released_at IS NULL
      AND s.withdrawn_at IS NULL
      AND e.state = 'active'
      AND f.disposed_at IS NULL
      AND sc.close_requested_at IS NULL
  )
  SELECT t.key, h.slot_id, h.episode_id, h.descriptor, h.descriptor_digest,
         (h.slot_id IS NOT NULL) AS live
  FROM target t
  LEFT JOIN hit h ON h.ord = t.ord
  ORDER BY t.ord;
END;
$$;

-- W2: at most one unsettled reconcile per fiber.  A deferred reconcile stays
-- ready and is settled by a later advance; a second one would be a second
-- lifecycle queue.
CREATE UNIQUE INDEX u_effects_reconcile ON v24.effects (fiber_id)
  WHERE kind = 'fiber_reconcile' AND status IN ('ready', 'claimed');

-- check_policy v1 is a closed data predicate over the resolved slot descriptor.
-- No code execution, no table access.
CREATE FUNCTION v24.check_policy_valid(p_policy jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, v24
AS $$
  SELECT CASE
    WHEN p_policy IS NULL OR p_policy = 'null'::jsonb THEN true
    WHEN jsonb_typeof(p_policy) IS DISTINCT FROM 'object' THEN false
    WHEN EXISTS (SELECT 1 FROM jsonb_object_keys(p_policy) k
                 WHERE k NOT IN ('v','op','path','value')) THEN false
    WHEN NOT (p_policy ?& ARRAY['v','op','path','value']) THEN false
    WHEN p_policy->'v' IS DISTINCT FROM '1'::jsonb THEN false
    WHEN p_policy->>'op' IS DISTINCT FROM 'equals' THEN false
    WHEN jsonb_typeof(p_policy->'path') IS DISTINCT FROM 'array' THEN false
    WHEN jsonb_array_length(p_policy->'path') NOT BETWEEN 1 AND 8 THEN false
    WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(p_policy->'path') e
                 WHERE jsonb_typeof(e) IS DISTINCT FROM 'string'
                   OR length(e #>> '{}') NOT BETWEEN 1 AND 128) THEN false
  END;
$$;

CREATE FUNCTION v24.check_policy_ok(p_policy jsonb, p_descriptor jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_cur jsonb := p_descriptor;
  v_part text;
  v_i integer;
BEGIN
  IF p_policy IS NULL OR p_policy = 'null'::jsonb THEN RETURN true; END IF;
  IF NOT v24.check_policy_valid(p_policy) THEN RETURN false; END IF;
  FOR v_i IN 0 .. jsonb_array_length(p_policy->'path') - 1 LOOP
    v_part := p_policy->'path'->>v_i;
    IF jsonb_typeof(v_cur) IS DISTINCT FROM 'object' OR NOT (v_cur ? v_part) THEN
      RETURN false;
    END IF;
    v_cur := v_cur->v_part;
  END LOOP;
  RETURN v_cur = p_policy->'value';
END;
$$;

-- A no-op command still records its effect/request receipt; no domain rows change.
CREATE FUNCTION v24.capability_noop(p_effect_id uuid, p_scope_id uuid, p_fiber_id uuid)
RETURNS jsonb LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, v24
AS $$
  SELECT jsonb_build_object(
    'write', true,
    'effect', jsonb_build_object('scope_id', p_scope_id, 'fiber_id', p_fiber_id),
    'request', jsonb_build_object('response', jsonb_build_object(
      'v',1,'disposition','committed','effect_id',p_effect_id,
      'emitted','[]'::jsonb,'revision',0,'claim',NULL)));
$$;

-- W4 lifecycle wrapper: construct the command outcome and delegate to advance.
CREATE FUNCTION v24.fiber_control(p_fiber_id uuid, p_action text,
  p_expected_control_seq bigint, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_fiber_id IS NULL OR p_action IS NULL
     OR p_action NOT IN ('on','off','retry')
     OR p_expected_control_seq IS NULL OR p_expected_control_seq < 0
     OR p_request_key IS NULL OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  payload := jsonb_build_object('fiber_id', p_fiber_id, 'action', p_action,
                                'expected_control_seq', p_expected_control_seq);
  RETURN v24.advance(
    v24.effect_id_for(v24.principal_id(session_user), p_request_key,
                      'command_fiber_control'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object(
      'op','admit_and_apply','kind','command_fiber_control','request_key',p_request_key,
      'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;

-- W6 leaf dispose entry point.
CREATE FUNCTION v24.dispose(p_install_id uuid, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_install_id IS NULL OR p_request_key IS NULL
     OR length(p_request_key) NOT BETWEEN 1 AND 512 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  payload := jsonb_build_object('install_id', p_install_id);
  RETURN v24.advance(
    v24.effect_id_for(v24.principal_id(session_user), p_request_key, 'command_dispose'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object(
      'op','admit_and_apply','kind','command_dispose','request_key',p_request_key,
      'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;
