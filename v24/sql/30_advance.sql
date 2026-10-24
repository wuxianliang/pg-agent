-- W3: admission prefix, complete claim protocol, settlement prefix.
-- W4/W5 implement validate_and_apply_delta; W4/W6 implement the interpreters.
-- These seams raise SQLSTATE 0A000, never a new protocol error/receipt.
CREATE FUNCTION v24.canonical_json(p_payload jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog, v24 AS $$ SELECT p_payload::text $$;

CREATE FUNCTION v24.principal_id(p_role name) RETURNS uuid
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog, v24 AS $$ SELECT md5(p_role::text)::uuid $$;

CREATE FUNCTION v24.effect_id_for(p_principal uuid, p_request_key text, p_kind text)
RETURNS uuid LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog, v24 AS $$
  SELECT substr(encode(sha256(convert_to(
    p_principal::text || ':' || p_kind || ':' || p_request_key, 'UTF8')), 'hex'), 1, 32)::uuid
$$;

CREATE FUNCTION v24.error_v1(p_code text, p_detail jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE
SET search_path = pg_catalog, v24 AS $$
BEGIN
  IF p_code IS NULL OR p_code <> ALL (ARRAY[
    'invalid_args','unauthorized','not_found_or_denied','request_conflict',
    'effect_id_conflict','receipt_conflict','stale_generation','registration_stale',
    'already_terminal','owner_closing','install_not_ready','interaction_mismatch',
    'provider_unavailable','scope_closed','dependency_unresolved','provide_conflict',
    'install_identity_conflict','budget_exceeded','invalid_outcome','stale_claim',
    'cleanup_cycle','retry_with_closure','blocked_unknown']) THEN
    RAISE EXCEPTION 'invalid_args: error code is outside the v1 closed set'
      USING ERRCODE = '22023';
  END IF;
  RETURN jsonb_build_object('v', 1, 'error',
    jsonb_build_object('code', p_code, 'detail', p_detail));
END;
$$;

-- Three distinct rows; the authenticated LOGIN, never current_user or a GUC.
CREATE FUNCTION v24.role_allowed(p_login name, p_class text, p_kind text, p_action text)
RETURNS boolean LANGUAGE sql STABLE
SET search_path = pg_catalog, v24 AS $$
  SELECT CASE
    WHEN p_class = 'command' AND p_kind = 'command_scope_control'
         AND p_action = 'create_root' THEN pg_has_role(p_login, 'v24_admin', 'USAGE')
    WHEN p_class = 'command' THEN
      pg_has_role(p_login, 'v24_admin', 'USAGE') OR
      pg_has_role(p_login, 'v24_service', 'USAGE') OR
      pg_has_role(p_login, 'v24_operator', 'USAGE')
    WHEN p_class IN ('claim','success','failure','unknown') THEN
      pg_has_role(p_login, 'v24_service', 'USAGE')
    ELSE false END
$$;

CREATE FUNCTION v24.interpret_command(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  RAISE EXCEPTION 'v24.interpret_command: no command handler registered (W4/W5)'
    USING ERRCODE = '0A000';
END;
$$;

CREATE FUNCTION v24.interpret_settlement(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  RAISE EXCEPTION 'v24.interpret_settlement: no settlement handler registered (W5/W6)'
    USING ERRCODE = '0A000';
END;
$$;

-- Step 11/12 seam: validate the entire delta BEFORE any application, then
-- apply domain -> effect/receipt -> request -> events -> successors atomically.
-- This is not an alternative write entry: INVOKER and no table privileges.
CREATE FUNCTION v24.validate_and_apply_delta(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_delta jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
BEGIN
  RAISE EXCEPTION 'v24.validate_and_apply_delta: delta application not implemented (W4/W5)'
    USING ERRCODE = '0A000';
END;
$$;

CREATE FUNCTION v24.advance(p_effect_id uuid, p_outcome jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, v24 AS $$
DECLARE
  v_class text;
  v_body jsonb;
  v_token jsonb;
  v_principal uuid;
  v_bytes bytea;
  v_digest bytea;
  v_receipt_digest bytea;
  v_request v24.requests%ROWTYPE;
  v_effect v24.effects%ROWTYPE;
  v_closure jsonb;
  v_delta jsonb;
  v_depth integer;
  v_keys bigint;
  v_executable boolean;
  v_claim jsonb := NULL;
  v_disposition text := 'committed';
  v_ref text;
  v_req jsonb;
  v_cause text;
  v_parent v24.effects%ROWTYPE;
  v_model_parent v24.effects%ROWTYPE;
  v_req_keys text[];
  v_pin v24.pins%ROWTYPE;
  v_install v24.installs%ROWTYPE;
  v_target v24.effects%ROWTYPE;
  v_batch text;
BEGIN
  -- 1 / A: all untrusted shapes are checked before authentication or locks.
  IF p_effect_id IS NULL OR jsonb_typeof(p_outcome) IS DISTINCT FROM 'object'
     OR p_outcome->'v' IS DISTINCT FROM '1'::jsonb
     OR jsonb_typeof(p_outcome->'class') IS DISTINCT FROM 'string'
     OR (p_outcome->>'class') <> ALL (ARRAY['command','claim','success','failure','unknown'])
     OR jsonb_typeof(p_outcome->'body') IS DISTINCT FROM 'object'
     OR (p_outcome ? 'receipt_key' AND
         jsonb_typeof(p_outcome->'receipt_key') IS DISTINCT FROM 'string') THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  v_class := p_outcome->>'class';
  v_body := p_outcome->'body';
  v_token := p_outcome->'claim';
  IF octet_length(v_body::text) > 1048576 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;
  -- Count all body keys, including nested objects; root container depth is 1.
  WITH RECURSIVE nodes(value, depth) AS (
    SELECT v_body, 1
    UNION ALL
    SELECT child.value, n.depth + 1 FROM nodes n
    CROSS JOIN LATERAL (
      SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(n.value)='object'
                                      THEN n.value ELSE '{}'::jsonb END)
      UNION ALL
      SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(n.value)='array'
                                                 THEN n.value ELSE '[]'::jsonb END)
    ) child
  )
  SELECT max(depth), sum(CASE WHEN jsonb_typeof(value)='object' THEN
    (SELECT count(*) FROM jsonb_object_keys(value)) ELSE 0 END),
    bool_or(jsonb_typeof(value)='object' AND value ?| ARRAY['successors','intents'])
  INTO v_depth, v_keys, v_executable FROM nodes;
  IF v_depth > 32 OR v_keys > 200 OR (v_class='unknown' AND v_executable) THEN
    RETURN v24.error_v1('invalid_args');
  END IF;

  IF v_class IN ('command','claim') THEN
    IF v_token IS DISTINCT FROM 'null'::jsonb THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
  ELSE
    IF jsonb_typeof(v_token) IS DISTINCT FROM 'object'
       OR NOT (v_token ?& ARRAY['attempt','fence','owner'])
       OR (SELECT count(*) FROM jsonb_object_keys(v_token)) <> 3
       OR jsonb_typeof(v_token->'attempt') IS DISTINCT FROM 'number'
       OR jsonb_typeof(v_token->'fence') IS DISTINCT FROM 'number'
       OR jsonb_typeof(v_token->'owner') IS DISTINCT FROM 'string'
       OR length(v_token->>'owner') NOT BETWEEN 1 AND 63 THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    IF (v_token->>'attempt') !~ '^[0-9]+$' OR (v_token->>'fence') !~ '^[0-9]+$'
       OR (v_token->>'attempt')::numeric > 9223372036854775807
       OR (v_token->>'fence')::numeric > 9223372036854775807 THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
  END IF;

  IF v_class = 'claim' THEN
    IF NOT (v_body ? 'lease_ms') OR (SELECT count(*) FROM jsonb_object_keys(v_body)) <> 1
       OR jsonb_typeof(v_body->'lease_ms') IS DISTINCT FROM 'number' THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    IF (v_body->>'lease_ms') !~ '^[0-9]+$'
       OR (v_body->>'lease_ms')::numeric NOT BETWEEN 1 AND 300000 THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
  ELSIF v_class = 'command' THEN
    IF NOT (v_body ?& ARRAY['op','kind','request_key','canonical_bytes','payload'])
       OR v_body->>'op' IS DISTINCT FROM 'admit_and_apply'
       OR jsonb_typeof(v_body->'kind') IS DISTINCT FROM 'string'
       OR (v_body->>'kind') <> ALL (ARRAY[
         'command_start','command_cancel','command_steer','command_respond',
         'command_install','command_fiber_control','command_dispose','command_scope_control',
         'command_recover'])
       OR jsonb_typeof(v_body->'request_key') IS DISTINCT FROM 'string'
       OR length(v_body->>'request_key') NOT BETWEEN 1 AND 512
       OR jsonb_typeof(v_body->'canonical_bytes') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_body->'payload') IS DISTINCT FROM 'object' THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    BEGIN
      v_bytes := decode(v_body->>'canonical_bytes', 'base64');
    EXCEPTION WHEN invalid_parameter_value THEN
      RETURN v24.error_v1('invalid_args');
    END;
    IF v_bytes IS DISTINCT FROM convert_to(v24.canonical_json(v_body->'payload'), 'UTF8') THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    -- S2 child admission: a nonexistent owner is W0 invalid_args, not a closure
    -- failure. This read happens before closure discovery; fibers are never
    -- deleted, so it cannot race a removal.
    IF v_body->>'kind' = 'command_install'
       AND v_body->'payload'->>'owner_fiber_id' IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM v24.fibers
                        WHERE fiber_id = (v_body->'payload'->>'owner_fiber_id')::uuid) THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    IF v_body->>'kind' = 'command_fiber_control' THEN
      IF jsonb_typeof(v_body->'payload'->'fiber_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(v_body->'payload'->'action') IS DISTINCT FROM 'string'
         OR (v_body->'payload'->>'action') NOT IN ('on','off','retry')
         OR jsonb_typeof(v_body->'payload'->'expected_control_seq') IS DISTINCT FROM 'number'
         OR (v_body->'payload'->>'expected_control_seq') !~ '^[0-9]{1,18}$'
         OR (v_body->'payload'->>'expected_control_seq')::numeric > 9223372036854775807 THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
    END IF;
    -- These are reference fields, not caller-provided closure/lock instructions.
    FOR v_ref IN SELECT value #>> '{}' FROM jsonb_each(v_body->'payload')
      WHERE key = ANY (ARRAY['scope_id','parent_scope_id','run_id','install_id',
                            'fiber_id','owner_fiber_id','episode_id','slot_id','pin_id'])
        AND value <> 'null'::jsonb
    LOOP
      BEGIN
        PERFORM v_ref::uuid;
      EXCEPTION WHEN invalid_text_representation THEN
        RETURN v24.error_v1('invalid_args');
      END;
    END LOOP;
    v_digest := sha256(v_bytes);
  END IF;

  -- 2 / B: SECURITY DEFINER must not change the identity source.
  v_principal := v24.principal_id(session_user);
  IF NOT v24.role_allowed(session_user, v_class, v_body->>'kind',
                         v_body->'payload'->>'action') THEN
    RETURN v24.error_v1('unauthorized');
  END IF;

  -- 3 / C: FIRST explicit lock, before even reading a v24 table.
  PERFORM pg_advisory_xact_lock(24, 1);

  -- 4..7 / D command / C0..C3. Request is the sole pre-closure row lock.
  IF v_class = 'command' THEN
    IF p_effect_id <> v24.effect_id_for(v_principal, v_body->>'request_key', v_body->>'kind') THEN
      RETURN v24.error_v1('effect_id_conflict');
    END IF;
    SELECT * INTO v_request FROM v24.requests
      WHERE principal_id = v_principal AND request_key = v_body->>'request_key'
      FOR UPDATE;
    IF FOUND THEN
      IF v_request.request_bytes IS DISTINCT FROM v_bytes
         OR v_request.request_digest IS DISTINCT FROM v_digest THEN
        RETURN v24.error_v1('request_conflict');
      END IF;
      RETURN v_request.response;
    END IF;
  ELSE
    -- 8: plain MVCC read under G, NOT an effect row lock ahead of scope/run.
    -- Priorities come from §4.13.4: terminal receipt BEFORE current token.
    SELECT * INTO v_effect FROM v24.effects WHERE effect_id = p_effect_id;
    IF NOT FOUND THEN
      RETURN v24.error_v1('effect_id_conflict');
    END IF;
    IF v_class <> 'claim' THEN
      -- receipt_key is transport metadata, excluded on BOTH sides of matching.
      v_receipt_digest := sha256(convert_to(v24.canonical_json(p_outcome - 'receipt_key'), 'UTF8'));
      IF v_effect.status IN ('succeeded','failed','unknown') THEN
        IF v_receipt_digest = sha256(convert_to(
             v24.canonical_json(v_effect.outcome - 'receipt_key'), 'UTF8')) THEN
          RETURN jsonb_build_object('v',1,'disposition','replay','effect_id',p_effect_id,
                                   'emitted','[]'::jsonb,'revision',0,'claim',NULL);
        END IF;
        RETURN v24.error_v1('receipt_conflict');
      ELSIF v_effect.status = 'cancelled' THEN
        RETURN v24.error_v1('receipt_conflict');
      END IF;
      IF v_effect.status <> 'claimed'
         OR v_effect.attempt_no <> (v_token->>'attempt')::bigint
         OR v_effect.fence <> (v_token->>'fence')::bigint
         OR v_effect.claim_owner IS DISTINCT FROM v_token->>'owner' THEN
        RETURN v24.error_v1('stale_claim');
      END IF;
    END IF;
  END IF;

  -- Start's absent targets have protocol errors, rather than being nonexistent
  -- closure members. These reads run under G, after exact request replay.
  IF v_class='command' AND v_body->>'kind'='command_start' THEN
    IF v_body->'payload'->>'scope_id' IS NULL THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM v24.scopes s
                    WHERE s.scope_id=(v_body->'payload'->>'scope_id')::uuid) THEN
      RETURN v24.error_v1('unauthorized');
    END IF;
    IF v_body->'payload'->>'owner_fiber_id' IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM v24.fibers f
                        WHERE f.fiber_id=(v_body->'payload'->>'owner_fiber_id')::uuid) THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
  END IF;

  -- A missing run-control target is W0, not an unresolved closure reference.
  IF v_class='command' AND v_body->>'kind' IN ('command_cancel','command_steer','command_respond')
     AND NOT EXISTS (SELECT 1 FROM v24.runs r
                     WHERE r.run_id=(v_body->'payload'->>'run_id')::uuid) THEN
    RETURN v24.error_v1('invalid_args');
  END IF;

  -- 9 / E1 / K0/S1: discover the transitive ownership/reference closure WITHOUT
  -- locking. UNION deduplicates cycles. New/missing references fail closed before
  -- ANY domain DML; never repair a closure by adding locks after this pass.
  WITH RECURSIVE closure(entity_type, entity_id) AS (
    SELECT 'effects'::text, p_effect_id
    UNION
    SELECT refs.entity_type, refs.entity_id
    FROM closure c CROSS JOIN LATERAL (
      SELECT r.* FROM v24.effects e CROSS JOIN LATERAL (VALUES
        ('scopes',e.scope_id), ('runs',e.run_id), ('fibers',e.fiber_id),
        ('episodes',e.episode_id), ('pins',e.pin_id),
        ('installs',(e.request->>'install_id')::uuid)
      ) r(entity_type,entity_id) WHERE c.entity_type='effects' AND e.effect_id=c.entity_id
      UNION ALL
      SELECT r.* FROM v24.scopes s CROSS JOIN LATERAL (VALUES
        ('scopes',s.parent_id), ('scopes',s.root_id)
      ) r(entity_type,entity_id) WHERE c.entity_type='scopes' AND s.scope_id=c.entity_id
      UNION ALL
      -- S5 W3 close: the target scope's child scopes, runs and installs are part
      -- of the write set.  Only the target scope expands (the parent/root hops
      -- above must not pull in the whole tree).
      SELECT 'scopes', ch.scope_id FROM v24.scopes s
        JOIN v24.scopes ch ON ch.parent_id = s.scope_id
       WHERE c.entity_type='scopes' AND s.scope_id=c.entity_id
         AND s.scope_id=(v_body->'payload'->>'parent_scope_id')::uuid
         AND v_class='command' AND v_body->>'kind'='command_scope_control'
         AND v_body->'payload'->>'action'='close'
      UNION ALL
      SELECT 'runs', r.run_id FROM v24.scopes s
        JOIN v24.runs r ON r.scope_id = s.scope_id
       WHERE c.entity_type='scopes' AND s.scope_id=c.entity_id
         AND s.scope_id=(v_body->'payload'->>'parent_scope_id')::uuid
         AND v_class='command' AND v_body->>'kind'='command_scope_control'
         AND v_body->'payload'->>'action'='close'
      UNION ALL
      SELECT 'installs', i.install_id FROM v24.scopes s
        JOIN v24.installs i ON i.scope_id = s.scope_id
       WHERE c.entity_type='scopes' AND s.scope_id=c.entity_id
         AND s.scope_id=(v_body->'payload'->>'parent_scope_id')::uuid
         AND v_class='command' AND v_body->>'kind'='command_scope_control'
         AND v_body->'payload'->>'action'='close'
      UNION ALL
      SELECT r.* FROM v24.runs x CROSS JOIN LATERAL (VALUES
        ('scopes',x.scope_id), ('runs',x.parent_run_id),
        ('fibers',x.owner_fiber_id), ('episodes',x.owner_episode_id)
      ) r(entity_type,entity_id) WHERE c.entity_type='runs' AND x.run_id=c.entity_id
      UNION ALL
      -- Run control touches business effects; only cancel releases run pins.
      SELECT 'effects', e.effect_id FROM v24.effects e
        WHERE c.entity_type='runs' AND e.run_id=c.entity_id
          AND c.entity_id=(v_body->'payload'->>'run_id')::uuid
          AND e.kind IN ('model_call','tool_call') AND e.status IN ('ready','claimed')
          AND v_class='command' AND v_body->>'kind' IN ('command_cancel','command_steer')
      UNION ALL
      SELECT 'pins', p.pin_id FROM v24.pins p
        WHERE c.entity_type='runs' AND p.consumer_run_id=c.entity_id
          AND c.entity_id=(v_body->'payload'->>'run_id')::uuid AND p.released_at IS NULL
          AND v_class='command' AND v_body->>'kind'='command_cancel'
      UNION ALL
      SELECT 'effects', e.effect_id FROM v24.effects e
        WHERE c.entity_type='pins' AND e.pin_id=c.entity_id
          AND EXISTS (SELECT 1 FROM v24.pins p WHERE p.pin_id=c.entity_id
                      AND p.consumer_run_id=(v_body->'payload'->>'run_id')::uuid
                      AND p.released_at IS NULL)
          AND (e.status IN ('ready','claimed')
               OR (e.status='unknown' AND e.resource_quiesced_at IS NULL))
          AND v_class='command' AND v_body->>'kind'='command_cancel'
      UNION ALL
      SELECT r.* FROM v24.installs x CROSS JOIN LATERAL (VALUES
        ('scopes',x.scope_id), ('fibers',x.owner_fiber_id), ('episodes',x.owner_episode_id)
      ) r(entity_type,entity_id) WHERE c.entity_type='installs' AND x.install_id=c.entity_id
      UNION ALL
      SELECT 'fibers', f.fiber_id FROM v24.installs x
        JOIN v24.fibers f ON f.install_id = x.install_id
        WHERE c.entity_type='installs' AND x.install_id=c.entity_id
      UNION ALL
      SELECT 'installs', ci.install_id FROM v24.installs x
        JOIN v24.installs ci ON ci.owner_fiber_id = x.owner_fiber_id
         AND ci.owner_episode_id = x.owner_episode_id
        WHERE c.entity_type='installs' AND x.install_id=c.entity_id
          AND x.owner_fiber_id IS NOT NULL AND ci.install_id <> x.install_id
      UNION ALL
      -- S5 W3 close: correct owner-descendant edge for the close closure.  The
      -- pre-existing sibling edge above is a W1 behaviour and is not reused.
      SELECT 'installs', ci.install_id FROM v24.fibers f
        JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
        JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                            AND e.fiber_id = f.fiber_id
       WHERE c.entity_type='installs' AND f.install_id=c.entity_id
         AND ci.install_id <> c.entity_id
         AND v_class='command' AND v_body->>'kind'='command_scope_control'
         AND v_body->'payload'->>'action'='close'
      UNION ALL
      SELECT 'effects', e.effect_id FROM v24.installs x
        JOIN v24.effects e ON (e.request->>'install_id') = x.install_id::text
        WHERE c.entity_type='installs' AND x.install_id=c.entity_id
      UNION ALL
      SELECT r.* FROM v24.fibers x CROSS JOIN LATERAL (VALUES
        ('scopes',x.scope_id), ('installs',x.install_id), ('fibers',x.owner_fiber_id),
        ('episodes',x.owner_episode_id), ('episodes',x.current_episode_id)
      ) r(entity_type,entity_id) WHERE c.entity_type='fibers' AND x.fiber_id=c.entity_id
      UNION ALL
      SELECT 'effects', e.effect_id FROM v24.fibers x
        JOIN v24.effects e ON e.fiber_id = x.fiber_id
        WHERE c.entity_type='fibers' AND x.fiber_id=c.entity_id
          AND e.kind='fiber_reconcile'
      UNION ALL
      -- S5 W3 close: retire touches every episode of the scope fiber, not only
      -- the owner/current pointers.
      SELECT 'episodes', e.episode_id FROM v24.episodes e
       WHERE c.entity_type='fibers' AND e.fiber_id=c.entity_id
         AND v_class='command' AND v_body->>'kind'='command_scope_control'
         AND v_body->'payload'->>'action'='close'
      UNION ALL
      -- Activation closure: resolve hard requirements without locking yet; the
      -- interpreter re-resolves and returns retry_with_closure on drift.
      SELECT 'slots', rr.slot_id
      FROM v24.fibers x
      JOIN v24.installs i ON i.install_id = x.install_id
      CROSS JOIN LATERAL v24.resolve(
        x.scope_id,
        ARRAY(SELECT value->>'key' FROM jsonb_array_elements(i.requires))
      ) rr
      WHERE c.entity_type='fibers' AND x.fiber_id=c.entity_id
        AND v_class='command' AND v_body->>'kind'='command_fiber_control'
        AND v_body->'payload'->>'action'='on' AND rr.live
      UNION ALL
      -- Run pins use the same pre-lock resolve discovery as activation pins.
      -- Clamp malformed arrays here; interpret_start owns W0 shape validation.
      SELECT 'slots', rr.slot_id
      FROM v24.resolve((v_body->'payload'->>'scope_id')::uuid,
        ARRAY(SELECT value->>'key' FROM jsonb_array_elements(
          CASE WHEN jsonb_typeof(v_body->'payload'->'input'->'requires')='array'
               THEN v_body->'payload'->'input'->'requires' ELSE '[]'::jsonb END)
          WITH ORDINALITY req(value,ord) WHERE ord<=16)) rr
      WHERE v_class='command' AND v_body->>'kind'='command_start'
        AND c.entity_type='effects' AND c.entity_id=p_effect_id AND rr.live
      UNION ALL
      SELECT 'fibers', x.fiber_id FROM v24.episodes x
        WHERE c.entity_type='episodes' AND x.episode_id=c.entity_id
      UNION ALL
      SELECT 'slots', s.slot_id FROM v24.episodes x
        JOIN v24.slots s ON s.episode_id = x.episode_id
        WHERE c.entity_type='episodes' AND x.episode_id=c.entity_id
      UNION ALL
      SELECT 'pins', p.pin_id FROM v24.episodes x
        JOIN v24.pins p ON p.consumer_episode_id = x.episode_id
        WHERE c.entity_type='episodes' AND x.episode_id=c.entity_id
      UNION ALL
      -- S5 W3 close: provider pins of the closure episodes are also blocked by
      -- the barrier and must be in the lock set.
      SELECT 'pins', p.pin_id FROM v24.episodes x
        JOIN v24.pins p ON p.provider_episode_id = x.episode_id
        WHERE c.entity_type='episodes' AND x.episode_id=c.entity_id
          AND v_class='command' AND v_body->>'kind'='command_scope_control'
          AND v_body->'payload'->>'action'='close'
      UNION ALL
      -- S5 W3 close: all pins that reference a closure slot, and all run pins of
      -- the target scope's runs.
      SELECT 'pins', p.pin_id FROM v24.slots x
        JOIN v24.pins p ON p.slot_id = x.slot_id
        WHERE c.entity_type='slots' AND x.slot_id=c.entity_id
          AND v_class='command' AND v_body->>'kind'='command_scope_control'
          AND v_body->'payload'->>'action'='close'
      UNION ALL
      SELECT 'pins', p.pin_id FROM v24.runs x
        JOIN v24.pins p ON p.consumer_run_id = x.run_id
        WHERE c.entity_type='runs' AND x.run_id=c.entity_id
          AND v_class='command' AND v_body->>'kind'='command_scope_control'
          AND v_body->'payload'->>'action'='close'
      UNION ALL
      SELECT r.* FROM v24.slots x CROSS JOIN LATERAL (VALUES
        ('fibers',x.fiber_id), ('episodes',x.episode_id)
      ) r(entity_type,entity_id) WHERE c.entity_type='slots' AND x.slot_id=c.entity_id
      UNION ALL
      SELECT r.* FROM v24.pins x CROSS JOIN LATERAL (VALUES
        ('slots',x.slot_id), ('fibers',x.provider_fiber_id), ('episodes',x.provider_episode_id),
        ('episodes',x.consumer_episode_id), ('runs',x.consumer_run_id)
      ) r(entity_type,entity_id) WHERE c.entity_type='pins' AND x.pin_id=c.entity_id
      UNION ALL
      -- Command targets seed the same graph; not caller-supplied lock vectors.
      SELECT r.entity_type, (v_body->'payload'->>r.key)::uuid
      FROM (VALUES ('scopes','scope_id'), ('scopes','parent_scope_id'),
        ('runs','run_id'), ('installs','install_id'), ('fibers','fiber_id'),
        ('fibers','owner_fiber_id'), ('episodes','episode_id'),
        ('slots','slot_id'), ('pins','pin_id')) r(entity_type,key)
      WHERE v_class='command' AND c.entity_type='effects' AND c.entity_id=p_effect_id
      UNION ALL
      -- S6: the frozen recovery hint is a lock seed, never a lock instruction
      -- supplied by the caller as SQL.  Only effect ids; the rest of the
      -- closure expands from the effect rows.
      SELECT 'effects'::text, cand.value::uuid
        FROM jsonb_array_elements_text(
               coalesce(v_body->'candidates','[]'::jsonb)) AS cand(value)
       WHERE v_class = 'command'
         AND v_body->>'kind' = 'command_recover'
         AND c.entity_type = 'effects' AND c.entity_id = p_effect_id
      UNION ALL
      -- S6 W3: the unknown wall releases the candidate run's live pins in the
      -- same delta.  Seed them from the candidate effect row, never from caller
      -- input; the pin seed expands provider slot/episode closure normally.
      SELECT 'pins', p.pin_id
        FROM v24.effects e
        JOIN v24.pins p ON p.consumer_run_id = e.run_id
       WHERE v_class='command' AND v_body->>'kind'='command_recover'
         AND c.entity_type='effects' AND e.effect_id=c.entity_id
    ) refs WHERE refs.entity_id IS NOT NULL
  ), grouped AS (
    SELECT entity_type, jsonb_agg(entity_id ORDER BY entity_id) AS ids
      FROM closure GROUP BY entity_type
  ) SELECT jsonb_object_agg(entity_type, ids) INTO v_closure FROM grouped;

  IF (SELECT coalesce(sum(jsonb_array_length(c.value)), 0)
        FROM jsonb_each(v_closure) c) > 512 THEN
    -- Bounded closure: no unbounded subtree traversal (design §2.5).
    RETURN v24.error_v1('retry_with_closure');
  END IF;

  IF EXISTS (
    SELECT 1 FROM jsonb_each(v_closure) c
    CROSS JOIN LATERAL jsonb_array_elements_text(c.value) id
    WHERE NOT (c.key='effects' AND v_class='command' AND id.value::uuid=p_effect_id)
      AND NOT CASE c.key
        WHEN 'scopes' THEN EXISTS (SELECT 1 FROM v24.scopes WHERE scope_id=id.value::uuid)
        WHEN 'runs' THEN EXISTS (SELECT 1 FROM v24.runs WHERE run_id=id.value::uuid)
        WHEN 'effects' THEN EXISTS (SELECT 1 FROM v24.effects WHERE effect_id=id.value::uuid)
        WHEN 'installs' THEN EXISTS (SELECT 1 FROM v24.installs WHERE install_id=id.value::uuid)
        WHEN 'fibers' THEN EXISTS (SELECT 1 FROM v24.fibers WHERE fiber_id=id.value::uuid)
        WHEN 'episodes' THEN EXISTS (SELECT 1 FROM v24.episodes WHERE episode_id=id.value::uuid)
        WHEN 'slots' THEN EXISTS (SELECT 1 FROM v24.slots WHERE slot_id=id.value::uuid)
        WHEN 'pins' THEN EXISTS (SELECT 1 FROM v24.pins WHERE pin_id=id.value::uuid)
        ELSE false END
  ) THEN
    RETURN v24.error_v1('retry_with_closure');
  END IF;

  -- One and only ordered lock pass: scope depth then UUID; all others UUID.
  PERFORM scope_id FROM v24.scopes
    WHERE v_closure->'scopes' ? scope_id::text
    ORDER BY cardinality(route_path), scope_id FOR UPDATE;
  PERFORM run_id FROM v24.runs WHERE v_closure->'runs' ? run_id::text
    ORDER BY run_id FOR UPDATE;
  PERFORM effect_id FROM v24.effects WHERE v_closure->'effects' ? effect_id::text
    ORDER BY effect_id FOR UPDATE;
  PERFORM install_id FROM v24.installs WHERE v_closure->'installs' ? install_id::text
    ORDER BY install_id FOR UPDATE;
  PERFORM fiber_id FROM v24.fibers WHERE v_closure->'fibers' ? fiber_id::text
    ORDER BY fiber_id FOR UPDATE;
  PERFORM episode_id FROM v24.episodes WHERE v_closure->'episodes' ? episode_id::text
    ORDER BY episode_id FOR UPDATE;
  PERFORM slot_id FROM v24.slots WHERE v_closure->'slots' ? slot_id::text
    ORDER BY slot_id FOR UPDATE;
  PERFORM pin_id FROM v24.pins WHERE v_closure->'pins' ? pin_id::text
    ORDER BY pin_id FOR UPDATE;

  -- 10 / E2..E4: only claim has a W3 writer. No IO anywhere in this function.
  IF v_class = 'command' THEN
    -- C4.1 collision check occurs on the effect already covered by the pass.
    IF EXISTS (SELECT 1 FROM v24.effects WHERE effect_id=p_effect_id) THEN
      RETURN v24.error_v1('effect_id_conflict');
    END IF;
    v_delta := v24.interpret_command(p_effect_id, v_principal, p_outcome, v_closure);
  ELSIF v_class = 'claim' THEN
    SELECT * INTO v_effect FROM v24.effects WHERE effect_id=p_effect_id;
    -- C18: the allowlist has exactly one source of truth. Every kind admitted
    -- here must have a registered settlement path (W1: model_call).
    IF v_effect.kind <> ALL (v24.claimable_kinds()) OR
       v_effect.status IN ('succeeded','failed','unknown','cancelled') THEN
      RETURN v24.error_v1('invalid_args');
    END IF;
    -- C18 condition 2: reject a structurally invalid request BEFORE the host
    -- executes it.  No row is touched on this path.
    IF v_effect.kind = 'model_call' THEN
      v_req := v_effect.request;
      IF jsonb_typeof(v_req) IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      v_cause := v_req->>'cause';
      IF v_cause IS NULL OR v_cause NOT IN ('start','steer','respond','continuation') THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      v_req_keys := ARRAY['v','cause','run_id','epoch_no','generation','reserve','digests'] ||
        CASE v_cause
          WHEN 'start' THEN ARRAY['input','budget']
          WHEN 'steer' THEN ARRAY['input','instruction']
          WHEN 'respond' THEN ARRAY['response','origin_effect_id']
          WHEN 'continuation' THEN ARRAY['input','batch_digest','state']
        END;
      IF NOT (v_req ?& v_req_keys)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_req) k
                     WHERE k <> ALL(v_req_keys)) THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      IF jsonb_typeof(v_req->'reserve') IS DISTINCT FROM 'object'
         OR jsonb_typeof(v_req->'digests') IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      BEGIN
        IF (v_req->>'v') IS DISTINCT FROM '1'
           OR jsonb_typeof(v_req->'run_id') IS DISTINCT FROM 'string'
           OR v_req->>'run_id' IS DISTINCT FROM v_effect.run_id::text
           OR jsonb_typeof(v_req->'epoch_no') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_req->'generation') IS DISTINCT FROM 'number'
           OR (v_req->>'epoch_no') !~ '^[0-9]+$'
           OR (v_req->>'generation') !~ '^[0-9]+$'
           OR (v_req->>'epoch_no')::bigint IS DISTINCT FROM v_effect.epoch_no
           OR (v_req->>'generation')::bigint IS DISTINCT FROM v_effect.generation
           OR v_effect.pin_id IS NOT NULL
           OR v_effect.ordinal IS DISTINCT FROM 0
           OR v_effect.parent_effect_id IS NULL
           OR jsonb_typeof(v_req->'reserve') IS DISTINCT FROM 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(v_req->'reserve')) <> 1
           OR NOT (v_req->'reserve' ? 'tokens')
           OR jsonb_typeof(v_req->'reserve'->'tokens') IS DISTINCT FROM 'number'
           OR (v_req->'reserve'->>'tokens') IS NULL
           OR (v_req->'reserve'->>'tokens') !~ '^[0-9]+$'
           OR (v_req->'reserve'->>'tokens')::bigint >
              (v24.loop_policy()->>'reserve_tokens')::bigint
           OR jsonb_typeof(v_req->'digests') IS DISTINCT FROM 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(v_req->'digests')) <> 3
           OR NOT (v_req->'digests' ?& ARRAY['policy','schema','toolset'])
           OR (v_req->'digests'->>'policy') IS NULL
           OR (v_req->'digests'->>'policy') !~ '^[0-9a-f]{64}$'
           OR (v_req->'digests'->>'schema') IS NULL
           OR (v_req->'digests'->>'schema') !~ '^[0-9a-f]{64}$'
           OR (v_req->'digests'->>'toolset') IS NULL
           OR (v_req->'digests'->>'toolset') !~ '^[0-9a-f]{64}$' THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        IF v_cause IN ('start','steer','continuation')
           AND jsonb_typeof(v_req->'input') IS DISTINCT FROM 'object' THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        IF v_cause = 'start'
           AND jsonb_typeof(v_req->'budget') IS DISTINCT FROM 'object' THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        IF v_cause = 'steer' AND (jsonb_typeof(v_req->'instruction') IS DISTINCT FROM 'string'
            OR length(v_req->>'instruction') NOT BETWEEN 1 AND 8192) THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        IF v_cause = 'respond' AND (jsonb_typeof(v_req->'response') IS DISTINCT FROM 'object'
            OR jsonb_typeof(v_req->'origin_effect_id') IS DISTINCT FROM 'string'
            OR (v_req->>'origin_effect_id') IS NULL
            OR (v_req->>'origin_effect_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        IF v_cause = 'continuation' AND (
            jsonb_typeof(v_req->'state') IS DISTINCT FROM 'object'
            OR octet_length(v24.canonical_json(v_req->'state')) >
               (v24.loop_policy()->>'max_state_bytes')::int
            OR jsonb_typeof(v_req->'batch_digest') IS DISTINCT FROM 'string'
            OR (v_req->>'batch_digest') IS NULL
            OR (v_req->>'batch_digest') !~ '^[0-9a-f]{64}$') THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
      EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
          OR invalid_parameter_value THEN
        RETURN v24.error_v1('invalid_args');
      END;
      -- Cause must agree with the parent effect kind and the deterministic id.
      SELECT * INTO v_parent FROM v24.effects p WHERE p.effect_id=v_effect.parent_effect_id;
      IF NOT FOUND OR v_parent.run_id IS DISTINCT FROM v_effect.run_id THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      IF v_cause = 'continuation' THEN
        IF v_parent.kind = 'model_call' THEN
          IF v_effect.effect_id <>
             md5(v_effect.parent_effect_id::text||':continuation')::uuid THEN
            RETURN v24.error_v1('invalid_args');
          END IF;
        ELSIF v_parent.kind = 'tool_call' THEN
          -- C20: a tool-batch continuation's parent is the max-ordinal tool,
          -- but its deterministic identity derives from the model batch parent.
          SELECT * INTO v_model_parent FROM v24.effects p
           WHERE p.effect_id = v_parent.parent_effect_id;
          IF NOT FOUND
             OR v_parent.parent_effect_id IS NULL
             OR v_model_parent.kind <> 'model_call'
             OR v_model_parent.run_id IS DISTINCT FROM v_effect.run_id
             OR v_effect.effect_id <>
                md5(v_parent.parent_effect_id::text||':continuation')::uuid THEN
            RETURN v24.error_v1('invalid_args');
          END IF;
        ELSE
          RETURN v24.error_v1('invalid_args');
        END IF;
      ELSIF v_cause = 'steer'
            AND v_parent.kind IN ('model_call','tool_call') THEN
        -- C21: a consumed pending steer is a steer-shaped request whose parent
        -- is the last old-generation settlement, not a command_steer.  Its
        -- deterministic id is the steer namespace, never command:model_call:0.
        IF v_effect.effect_id <> v24.steer_model_effect_id(v_effect.run_id,
             (v_req->>'epoch_no')::bigint,
             (v_req->>'generation')::bigint,
             v_req->>'instruction') THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
      ELSE
        IF v_parent.kind <> 'command_'||v_cause
           OR v_effect.effect_id <>
              md5(v_effect.parent_effect_id::text||':model_call:0')::uuid THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
      END IF;
    ELSIF v_effect.kind = 'tool_call' THEN
      -- C18 condition 2 for tools: request closure, deterministic id, parent
      -- model, live pin binding and the C20 batch digest all before execution.
      v_req := v_effect.request;
      IF jsonb_typeof(v_req) IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      v_req_keys := ARRAY['v','run_id','epoch_no','generation','ordinal',
                          'key','args','descriptor_digest','batch_digest'];
      IF NOT (v_req ?& v_req_keys)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_req) k
                     WHERE k <> ALL(v_req_keys)) THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      IF v_effect.pin_id IS NULL
         OR v_effect.parent_effect_id IS NULL
         OR v_effect.ordinal IS NULL THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      BEGIN
        IF (v_req->>'v') IS DISTINCT FROM '1'
           OR jsonb_typeof(v_req->'run_id') IS DISTINCT FROM 'string'
           OR v_req->>'run_id' IS DISTINCT FROM v_effect.run_id::text
           OR jsonb_typeof(v_req->'epoch_no') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_req->'generation') IS DISTINCT FROM 'number'
           OR (v_req->>'epoch_no') !~ '^[0-9]+$'
           OR (v_req->>'generation') !~ '^[0-9]+$'
           OR (v_req->>'epoch_no')::bigint IS DISTINCT FROM v_effect.epoch_no
           OR (v_req->>'generation')::bigint IS DISTINCT FROM v_effect.generation
           OR jsonb_typeof(v_req->'ordinal') IS DISTINCT FROM 'number'
           OR (v_req->>'ordinal') !~ '^[0-9]+$'
           OR (v_req->>'ordinal')::int IS DISTINCT FROM v_effect.ordinal
           OR v_effect.ordinal NOT BETWEEN 0 AND 15
           OR jsonb_typeof(v_req->'key') IS DISTINCT FROM 'string'
           OR length(v_req->>'key') NOT BETWEEN 1 AND 256
           OR jsonb_typeof(v_req->'args') IS DISTINCT FROM 'object'
           OR jsonb_typeof(v_req->'descriptor_digest') IS DISTINCT FROM 'string'
           OR (v_req->>'descriptor_digest') !~ '^([0-9a-f]{2})+$'
           OR length(v_req->>'descriptor_digest') > 256
           OR jsonb_typeof(v_req->'batch_digest') IS DISTINCT FROM 'string'
           OR (v_req->>'batch_digest') !~ '^[0-9a-f]{64}$' THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
      EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
          OR invalid_parameter_value THEN
        RETURN v24.error_v1('invalid_args');
      END;
      SELECT * INTO v_parent FROM v24.effects p
       WHERE p.effect_id = v_effect.parent_effect_id;
      IF NOT FOUND OR v_parent.kind <> 'model_call'
         OR v_parent.run_id IS DISTINCT FROM v_effect.run_id
         OR v_effect.effect_id <>
            v24.tool_effect_id(v_effect.parent_effect_id,v_effect.ordinal) THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      SELECT * INTO v_pin FROM v24.pins p WHERE p.pin_id = v_effect.pin_id;
      IF NOT FOUND
         OR v_pin.consumer_run_id IS DISTINCT FROM v_effect.run_id
         OR v_pin.released_at IS NOT NULL
         OR v_pin.key IS DISTINCT FROM v_req->>'key'
         OR v_pin.descriptor_digest IS DISTINCT FROM
            decode(v_req->>'descriptor_digest','hex') THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      SELECT encode(sha256(convert_to(
               coalesce(string_agg(t.effect_id::text, ',' ORDER BY t.ordinal),''),
               'UTF8')),'hex')
        INTO v_batch FROM v24.effects t
       WHERE t.parent_effect_id = v_effect.parent_effect_id AND t.kind = 'tool_call';
      IF v_batch IS DISTINCT FROM v_req->>'batch_digest' THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
    ELSIF v_effect.kind = 'inspect_resource' THEN
      -- S5 W2/C25: the frozen inspect request is checked before the host runs.
      -- The six keys are exactly the controller's target_* shape; a request-less
      -- or hand-written effect can never reach the inspect host.
      v_req := v_effect.request;
      IF jsonb_typeof(v_req) IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      v_req_keys := ARRAY['v','install_id','target','target_effect_id',
                          'target_reservation','target_request_digest'];
      IF NOT (v_req ?& v_req_keys)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_req) k
                     WHERE k <> ALL(v_req_keys)) THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      IF v_effect.parent_effect_id IS NULL
         OR v_effect.pin_id IS NOT NULL
         OR v_effect.ordinal IS DISTINCT FROM 0
         OR jsonb_typeof(v_req->'v') IS DISTINCT FROM 'number'
         OR (v_req->>'v') IS DISTINCT FROM '1'
         OR jsonb_typeof(v_req->'install_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(v_req->'target') IS DISTINCT FROM 'string'
         OR (v_req->>'target') NOT IN ('host_prepare','host_release')
         OR jsonb_typeof(v_req->'target_effect_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(v_req->'target_reservation') IS DISTINCT FROM 'string'
         OR jsonb_typeof(v_req->'target_request_digest') IS DISTINCT FROM 'string'
         OR (v_req->>'target_request_digest') !~ '^[0-9a-f]{64}$' THEN
        RETURN v24.error_v1('invalid_args');
      END IF;
      BEGIN
        SELECT * INTO v_install FROM v24.installs i
         WHERE i.install_id = (v_req->>'install_id')::uuid;
        IF NOT FOUND OR v_install.scope_id IS DISTINCT FROM v_effect.scope_id THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        SELECT * INTO v_target FROM v24.effects t
         WHERE t.effect_id = (v_req->>'target_effect_id')::uuid;
        IF NOT FOUND
           OR v_target.kind IS DISTINCT FROM v_req->>'target'
           OR v_target.status IS DISTINCT FROM 'unknown'
           OR v_target.resource_quiesced_at IS NOT NULL
           OR (v_target.request->>'install_id') IS DISTINCT FROM v_req->>'install_id'
           OR (v_target.request->>'reservation') IS DISTINCT FROM v_req->>'target_reservation'
           OR (v_req->>'target_reservation') NOT LIKE
                'v24:' || (v_req->>'target') || ':%'
           OR encode(v_target.request_digest,'hex') IS DISTINCT FROM
                v_req->>'target_request_digest' THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
        SELECT * INTO v_parent FROM v24.effects p
         WHERE p.effect_id = v_effect.parent_effect_id;
        IF NOT FOUND
           OR v_parent.kind NOT IN ('command_dispose','command_scope_control',
                                    'command_fiber_control')
           OR v_effect.effect_id <> md5(v_effect.parent_effect_id::text
                || ':inspect_resource:' || (v_req->>'install_id') || ':0')::uuid THEN
          RETURN v24.error_v1('invalid_args');
        END IF;
      EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
          OR invalid_parameter_value THEN
        RETURN v24.error_v1('invalid_args');
      END;
    END IF;
    -- D-S4-1: an expired business lease is not a second attempt. host kinds
    -- keep their S3 re-claim semantics.
    IF v_effect.status='claimed' AND v_effect.lease_until > now() THEN
      v_disposition := 'deferred';
    ELSIF v_effect.status='claimed' AND v_effect.kind IN ('model_call','tool_call') THEN
      RETURN v24.error_v1('stale_claim');
    ELSE
      UPDATE v24.effects SET status='claimed', attempt_no=attempt_no+1, fence=fence+1,
        claim_owner=session_user::text,
        lease_until=now() + (v_body->>'lease_ms')::integer * interval '1 millisecond'
      WHERE effect_id=p_effect_id RETURNING * INTO v_effect;
      v_claim := jsonb_build_object('attempt',v_effect.attempt_no,
        'fence',v_effect.fence,'owner',session_user::text);
    END IF;
    RETURN jsonb_build_object('v',1,'disposition',v_disposition,'effect_id',p_effect_id,
                             'emitted','[]'::jsonb,'revision',0,'claim',v_claim);
  ELSE
    v_delta := v24.interpret_settlement(p_effect_id, v_principal, p_outcome, v_closure);
  END IF;
  -- 11 then 12: no partial application; caller owns COMMIT (functions cannot).
  RETURN v24.validate_and_apply_delta(p_effect_id, v_principal, p_outcome, v_delta, v_closure);
  -- F: unanticipated SQL errors propagate and roll the transaction back.
END;
$$;
