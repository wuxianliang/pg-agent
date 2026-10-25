-- S6 W1-W3: the read-only discovery surface for expired claims, the bounded
-- recovery command entry point, its single INVOKER interpreter and the pure
-- unknown-wall projection shared by every settle_unknown action.
CREATE FUNCTION v24.recoverable_effects(p_scope uuid, p_limit integer DEFAULT 16)
RETURNS TABLE(
  effect_id     uuid,
  kind          text,
  replay_policy text,
  attempt_no    bigint,
  fence         bigint,
  claim_owner   text,
  lease_until   timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, v24
AS $$
  -- Claimed rows whose lease is already past, earliest expiry first, then
  -- effect UUID bytes.  Scope authorization uses the real session login,
  -- never a caller argument.  NULL or sub-1 limits yield no rows; a limit
  -- above sixteen is capped at sixteen.
  SELECT e.effect_id, e.kind, e.replay_policy, e.attempt_no, e.fence,
         e.claim_owner, e.lease_until
    FROM v24.effects e
    JOIN v24.scopes  s ON s.scope_id = e.scope_id
   WHERE e.scope_id = p_scope
     AND e.status = 'claimed'
     AND e.lease_until <= now()
     AND e.kind IN ('host_prepare','host_release','inspect_resource',
                    'model_call','tool_call')
     AND e.replay_policy <> 'manual'
     AND (s.owner_principal = v24.principal_id(session_user)
          OR pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE'))
   ORDER BY e.lease_until, e.effect_id
   LIMIT greatest(least(coalesce(p_limit, 0), 16), 0)
$$;

-- S6 W3: the pure no_replay wall projection.  The caller's delta is the only
-- writer; this helper reads one claimed effect, synthesises its unknown receipt
-- with the original claim facts plus recovery provenance, and returns the
-- exact run/pin/install/event convergence S4's normal unknown wall performs.
-- Host kinds stay outside the run wall: only host_prepare's preparing install
-- is projected to prepare_unknown, host_release keeps dispose_pending and
-- inspect_resource never proves quiescence.  Cancel-late preserves the cancel
-- seal byte-for-byte and emits only the late unknown fact.  Manual policy is
-- never handled here.
CREATE FUNCTION v24.unknown_wall_delta(p_effect_id uuid, p_reason text)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  e v24.effects%ROWTYPE;
  r v24.runs%ROWTYPE;
  v_outcome jsonb;
  v_effect jsonb;
  v_effects jsonb := '[]'::jsonb;
  v_runs jsonb := '[]'::jsonb;
  v_pins jsonb := '[]'::jsonb;
  v_installs jsonb := '[]'::jsonb;
  v_events jsonb := '[]'::jsonb;
  v_late boolean := false;
  v_status text;
  v_turn bigint;
  v_revision bigint;
  v_wall bigint;
  v_close jsonb;
  v_result jsonb;
  v_interaction jsonb;
  v_pending jsonb;
  v_ended timestamptz;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id = p_effect_id;
  IF NOT FOUND OR e.status <> 'claimed'
     OR e.kind NOT IN ('model_call','tool_call','host_prepare','host_release',
                       'inspect_resource') THEN
    RETURN jsonb_build_object('error', v24.error_v1('invalid_outcome'));
  END IF;

  v_outcome := jsonb_build_object(
    'v',1,'class','unknown',
    'claim',jsonb_build_object('attempt',e.attempt_no,'fence',e.fence,
                               'owner',e.claim_owner),
    'body',jsonb_build_object('kind',e.kind,
      'result',jsonb_build_object('v',1,'observed','unknown',
        'reason',p_reason,
        'recovery',jsonb_build_object('effect_id',e.effect_id,
          'attempt_no',e.attempt_no,'fence',e.fence))));
  v_effect := jsonb_build_object(
    'key',jsonb_build_object('effect_id',e.effect_id),
    'set',jsonb_build_object('status','unknown','outcome',v_outcome,
                             'settled_at',now(),'claim_owner',NULL,
                             'lease_until',NULL));
  v_events := jsonb_build_array(jsonb_build_object(
    'entity_type','effect','entity_id',e.effect_id,
    'event_kind','effect_recovered_unknown',
    'payload',jsonb_build_object('effect_id',e.effect_id,'kind',e.kind,
      'replay_policy',e.replay_policy,'action','settle_unknown',
      'reason',p_reason,'attempt_no',e.attempt_no,'fence',e.fence,
      'recovery_effect_id',NULL)));

  -- Host effects never rewrite a run.  A preparing install is the one
  -- projection this wall owns; host_release keeps dispose_pending and
  -- inspect_resource writes no install delta at all.
  IF e.kind IN ('host_prepare','host_release','inspect_resource') THEN
    IF e.kind = 'host_prepare'
       AND EXISTS (SELECT 1 FROM v24.installs i
                    WHERE i.install_id = (e.request->>'install_id')::uuid
                      AND i.state = 'preparing') THEN
      v_installs := jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('install_id',(e.request->>'install_id')::uuid),
        'set',jsonb_build_object('state','prepare_unknown')));
    END IF;
    RETURN jsonb_build_object('effects',v_effects || jsonb_build_array(v_effect),
      'runs','[]'::jsonb,'pins','[]'::jsonb,'installs',v_installs,
      'events',v_events);
  END IF;

  SELECT * INTO r FROM v24.runs WHERE run_id = e.run_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', v24.error_v1('invalid_outcome'));
  END IF;
  v_late := r.status = 'cancelled' AND e.cancel_requested;

  IF v_late THEN
    -- The cancel seal wins: status/close_intent/result/interaction/
    -- pending_steer/ended_at/turn_no/revision are copied byte-for-byte.
    -- Only the effect receipt and the late unknown fact are new.
    v_status := r.status;
    v_turn := r.turn_no;
    v_revision := r.revision;
    v_close := r.close_intent;
    v_result := r.result;
    v_interaction := r.interaction;
    v_pending := r.pending_steer;
    v_ended := r.ended_at;
    v_pins := v24.run_pin_release_set(e.run_id,NULL,r.status,p_effect_id);
    v_events := v_events || jsonb_build_array(jsonb_build_object(
      'entity_type','run','entity_id',e.run_id,
      'event_kind',CASE e.kind WHEN 'model_call' THEN 'model_call_unknown'
                              ELSE 'tool_call_unknown' END,
      'payload',jsonb_build_object('run_id',e.run_id,'effect_id',e.effect_id,
        'turn_no',v_turn,'late',true,'reason','outcome_unknown')));
  ELSE
    -- The normal wall is S4's: generic close reason, turn+1, revision+1,
    -- interaction/steer cleared, no budget refund, only elapsed wall time
    -- deducted.  A model effect blocks its own pin; a tool effect passes NULL
    -- so the settling tool effect itself is the pin blocker.
    v_status := 'blocked_unknown';
    v_turn := r.turn_no + 1;
    v_revision := r.revision + 1;
    v_close := jsonb_build_object('kind','unknown','reason','outcome_unknown',
                                  'effect_id',e.effect_id);
    v_result := jsonb_build_object('v',1,'close_reason','unknown','turn_no',v_turn);
    v_interaction := NULL;
    v_pending := NULL;
    v_ended := now();
    v_pins := v24.run_pin_release_set(
      e.run_id,
      CASE e.kind WHEN 'model_call' THEN e.effect_id ELSE NULL END,
      'blocked_unknown', e.effect_id);
    v_events := v_events || jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind',CASE e.kind WHEN 'model_call' THEN 'model_call_unknown'
                                ELSE 'tool_call_unknown' END,
        'payload',jsonb_build_object('run_id',e.run_id,'effect_id',e.effect_id,
          'turn_no',v_turn,'reason','outcome_unknown')),
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','run_blocked_unknown',
        'payload',jsonb_build_object('run_id',e.run_id,
          'reason','outcome_unknown','effect_id',e.effect_id)));
  END IF;

  v_wall := greatest(0, r.remaining_wall_ms -
    coalesce((extract(epoch from (now()-e.created_at))*1000)::bigint,0));
  v_runs := jsonb_build_array(jsonb_build_object(
    'key',jsonb_build_object('run_id',e.run_id),
    'set',jsonb_build_object(
      'status',v_status,
      'turn_no',v_turn,
      'remaining_steps',r.remaining_steps,
      'remaining_tokens',r.remaining_tokens,
      'remaining_tool_calls',r.remaining_tool_calls,
      'remaining_wall_ms',v_wall,
      'interaction',v_interaction,'pending_steer',v_pending,
      'close_intent',v_close,'result',v_result,
      'revision',v_revision,'ended_at',v_ended,'updated_at',now())));

  RETURN jsonb_build_object(
    'effects',v_effects || jsonb_build_array(v_effect),
    'runs',v_runs,'pins',v_pins,'installs',v_installs,
    'events',v_events);
END;
$$;

-- S6 W2: one request/receipt for the whole sweep.  SECURITY INVOKER, no table
-- writes, no advisory lock and exactly one advance call; advance owns
-- authorization, epoch, replay and the G lock.  The candidate array is a
-- frozen hint only: it never enters canonical_bytes, so a lost-response retry
-- with a newly discovered (possibly empty) hint still replays the first
-- response byte-for-byte.
CREATE FUNCTION v24.command_recover(
  p_scope uuid,
  p_request_key text,
  p_limit integer DEFAULT 16
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_candidates jsonb;
  v_payload    jsonb;
  v_effect_id  uuid;
BEGIN
  -- Local shape only.  Authorization, epoch, and replay are advance's job.
  IF p_scope IS NULL
     OR p_request_key IS NULL
     OR length(p_request_key) NOT BETWEEN 1 AND 512
     OR p_limit IS NULL OR p_limit < 1 OR p_limit > 16 THEN
    RETURN v24.error_v1('invalid_args');
  END IF;

  -- Advisory pre-read: the frozen hint.  It is deliberately NOT part of
  -- canonical_bytes (see CC-2); the interpreter re-discovers under G.
  SELECT coalesce(jsonb_agg(to_jsonb(r.effect_id) ORDER BY r.effect_id), '[]'::jsonb)
    INTO v_candidates
    FROM v24.recoverable_effects(p_scope, p_limit) AS r;

  v_payload := jsonb_build_object('v', 1, 'scope_id', p_scope, 'limit', p_limit);
  v_effect_id := v24.effect_id_for(
    v24.principal_id(session_user), p_request_key, 'command_recover');

  RETURN v24.advance(
    v_effect_id,
    jsonb_build_object(
      'v', 1, 'class', 'command', 'claim', NULL,
      'body', jsonb_build_object(
        'op', 'admit_and_apply',
        'kind', 'command_recover',
        'request_key', p_request_key,
        'payload', v_payload,
        'candidates', v_candidates,
        'canonical_bytes',
          encode(convert_to(v24.canonical_json(v_payload), 'UTF8'), 'base64'))));
END;
$$;

-- S6 W2/W3: the only recovery interpreter.  It reads under advance's G lock and
-- returns one delta; it never updates a table itself.  replay_safe effects are
-- returned to ready for a later ordinary claim.  The no_replay and cancel-late
-- branches delegate the whole unknown wall to v24.unknown_wall_delta, so the
-- effect receipt, run seal, pin release set, install projection and events all
-- land in this one delta.
CREATE FUNCTION v24.interpret_recover(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog, v24
AS $$
DECLARE
  v_body     jsonb := p_outcome->'body';
  v_payload  jsonb := v_body->'payload';
  v_scope    v24.scopes%ROWTYPE;
  v_limit    int;
  v_cand     uuid[];
  v_e        v24.effects%ROWTYPE;
  v_action   text;
  v_reason   text;
  v_effects  jsonb := '[]'::jsonb;
  v_runs     jsonb := '[]'::jsonb;
  v_pins     jsonb := '[]'::jsonb;
  v_installs jsonb := '[]'::jsonb;
  v_events   jsonb := '[]'::jsonb;
  v_applied  jsonb := '[]'::jsonb;
  v_skipped  jsonb := '[]'::jsonb;
  v_sub      jsonb;
  v_manual   int := 0;
  v_more     boolean := false;
  v_rows     int := 0;
  v_response jsonb;
BEGIN
  -- 1. Shape/admission: payload is exactly {v,scope_id,limit}; candidates is
  -- the at-most-limit UUID hint, deduplicated and in UUID byte order.
  IF v_body->>'kind' IS DISTINCT FROM 'command_recover'
     OR jsonb_typeof(v_payload) IS DISTINCT FROM 'object'
     OR NOT (v_payload ?& ARRAY['v','scope_id','limit'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_payload) k
                 WHERE k NOT IN ('v','scope_id','limit'))
     OR (v_payload->>'v') IS DISTINCT FROM '1' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    v_limit := (v_payload->>'limit')::int;
    SELECT * INTO v_scope FROM v24.scopes
      WHERE scope_id = (v_payload->>'scope_id')::uuid FOR UPDATE;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  -- 2. Scope authorization under G, before any target-row write.
  IF NOT FOUND OR (v_scope.owner_principal IS DISTINCT FROM p_principal
                   AND NOT pg_catalog.pg_has_role(session_user,'v24_admin','USAGE')) THEN
    RETURN jsonb_build_object('write',false,'error',
      v24.error_v1('not_found_or_denied'));
  END IF;
  IF v_limit IS NULL OR v_limit NOT BETWEEN 1 AND 16
     OR jsonb_typeof(v_body->'candidates') IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_body->'candidates') > v_limit THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    v_cand := ARRAY(SELECT value::uuid
                      FROM jsonb_array_elements_text(v_body->'candidates') value);
  EXCEPTION WHEN invalid_text_representation THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  IF cardinality(v_cand) <> (SELECT count(DISTINCT x) FROM unnest(v_cand) x)
     OR v_cand <> (SELECT array_agg(x ORDER BY x) FROM unnest(v_cand) x) THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;

  -- 3. G-time rediscovery.  The hint bounds the read, but the authoritative
  -- set is this re-read in (lease_until, effect_id) order; rows the hint
  -- missed only surface through has_more.
  FOR v_e IN
    SELECT e.* FROM v24.effects e
     WHERE e.effect_id = ANY(v_cand) AND e.scope_id = v_scope.scope_id
     ORDER BY e.lease_until, e.effect_id
     FOR UPDATE
  LOOP
    IF v_e.status <> 'claimed' OR v_e.lease_until > now() THEN
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','not_claimed'));
      CONTINUE;
    END IF;
    IF v_e.replay_policy = 'manual' THEN
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','manual'));
      CONTINUE;
    END IF;
    IF v_e.kind NOT IN ('host_prepare','host_release','inspect_resource',
                        'model_call','tool_call') THEN
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','kind_unsupported'));
      CONTINUE;
    END IF;

    -- 4. Classify from persisted columns only, never from the caller's hint.
    v_action := NULL; v_reason := NULL;
    IF v_e.cancel_requested THEN
      -- Cancel won the race.  W3 settles the effect unknown but the helper
      -- copies the cancel seal back unchanged and emits only the late fact.
      v_action := 'settle_unknown'; v_reason := 'cancel_late';
    ELSIF v_e.replay_policy = 'replay_safe' AND v_e.kind = 'host_prepare' THEN
      IF EXISTS (SELECT 1 FROM v24.installs i
                  WHERE i.install_id = (v_e.request->>'install_id')::uuid
                    AND i.state = 'preparing') THEN
        v_action := 'reset_ready'; v_reason := 'lease_expired';
      ELSE
        v_action := 'settle_unknown'; v_reason := 'install_not_preparing';
      END IF;
    ELSIF v_e.replay_policy = 'replay_safe' AND v_e.kind = 'host_release' THEN
      IF EXISTS (SELECT 1 FROM v24.installs i
                  WHERE i.install_id = (v_e.request->>'install_id')::uuid
                    AND i.state = 'dispose_pending') THEN
        v_action := 'reset_ready'; v_reason := 'lease_expired';
      ELSE
        v_action := 'settle_unknown'; v_reason := 'state_mismatch';
      END IF;
    ELSIF v_e.replay_policy = 'replay_safe' AND v_e.kind = 'inspect_resource' THEN
      v_action := 'reset_ready'; v_reason := 'lease_expired';
    ELSIF v_e.replay_policy = 'no_replay'
          AND v_e.kind IN ('model_call','tool_call') THEN
      v_action := 'settle_unknown'; v_reason := 'lease_expired';
    ELSE
      v_skipped := v_skipped || jsonb_build_array(jsonb_build_object(
        'effect_id',v_e.effect_id,'reason','kind_unsupported'));
      CONTINUE;
    END IF;

    -- 5. Apply in the delta.  Reset clears only the two claim columns and
    -- preserves attempt/fence: the next ordinary claim is the sole bump.
    IF v_action = 'reset_ready' THEN
      v_effects := v_effects || jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('effect_id',v_e.effect_id),
        'set',jsonb_build_object('status','ready',
                                 'claim_owner',NULL,'lease_until',NULL)));
      v_events := v_events || jsonb_build_array(jsonb_build_object(
        'entity_type','effect','entity_id',v_e.effect_id,
        'event_kind','effect_recovered_replay',
        'payload',jsonb_build_object(
          'effect_id',v_e.effect_id,'kind',v_e.kind,
          'replay_policy',v_e.replay_policy,'action','reset_ready',
          'reason',v_reason,'attempt_no',v_e.attempt_no,'fence',v_e.fence,
          'claim_owner',v_e.claim_owner,'recovery_effect_id',p_effect_id,
          'recovery_request_key',v_body->>'request_key')));
    ELSE
      -- S6 W3: one pure projection owns effect receipt, run wall, pins,
      -- install projection and per-action/per-run events.
      v_sub := v24.unknown_wall_delta(v_e.effect_id, v_reason);
      IF v_sub ? 'error' THEN
        RETURN jsonb_build_object('write',false,'error',v_sub->'error');
      END IF;
      v_effects := v_effects || coalesce(v_sub->'effects','[]'::jsonb);
      v_runs := v_runs || coalesce(v_sub->'runs','[]'::jsonb);
      v_pins := v_pins || coalesce(v_sub->'pins','[]'::jsonb);
      v_installs := v_installs || coalesce(v_sub->'installs','[]'::jsonb);
      v_events := v_events || coalesce(v_sub->'events','[]'::jsonb);
    END IF;
    v_applied := v_applied || jsonb_build_array(jsonb_build_object(
      'effect_id',v_e.effect_id,'kind',v_e.kind,
      'replay_policy',v_e.replay_policy,'action',v_action,'reason',v_reason,
      'attempt_no',v_e.attempt_no,'fence',v_e.fence,
      'run_id',v_e.run_id,
      'install_id',(v_e.request->>'install_id')::uuid));
    v_rows := v_rows + 1;
    IF v_rows >= 16 THEN EXIT; END IF;
  END LOOP;

  -- 6. manual is counted, never applied: discovery excludes it, so it neither
  -- consumes the 16-row bound nor keeps has_more permanently true.
  SELECT count(*) INTO v_manual FROM v24.effects e
   WHERE e.scope_id = v_scope.scope_id AND e.status = 'claimed'
     AND e.lease_until <= now() AND e.replay_policy = 'manual'
     AND e.kind IN ('host_prepare','host_release','inspect_resource',
                    'model_call','tool_call');
  SELECT EXISTS (
    SELECT 1 FROM v24.effects e
     WHERE e.scope_id = v_scope.scope_id AND e.status = 'claimed'
       AND e.lease_until <= now() AND e.replay_policy <> 'manual'
       AND e.kind IN ('host_prepare','host_release','inspect_resource',
                      'model_call','tool_call')
       AND e.effect_id <> ALL (coalesce(
             ARRAY(SELECT (a->>'effect_id')::uuid
                     FROM jsonb_array_elements(v_applied) a), '{}'::uuid[])))
    INTO v_more;

  -- The applier rejects duplicate (entity_type,entity_id,event_kind); keep the
  -- first occurrence in deterministic (lease_until,effect_id) order.
  SELECT coalesce(jsonb_agg(ev ORDER BY ord),'[]'::jsonb) INTO v_events
    FROM (SELECT DISTINCT ON (e->>'entity_type',e->>'entity_id',e->>'event_kind')
                 e AS ev, ord
            FROM jsonb_array_elements(v_events) WITH ORDINALITY t(e,ord)
           ORDER BY e->>'entity_type',e->>'entity_id',e->>'event_kind',ord) d;

  v_response := jsonb_build_object(
    'v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted','[]'::jsonb,'revision',0,'claim',NULL,
    'recovery',jsonb_build_object(
      'scope_id',v_scope.scope_id,'limit',v_limit,
      'candidates',v_body->'candidates',
      'applied',v_applied,'skipped',v_skipped,
      'manual_debt',v_manual,'has_more',v_more));

  RETURN jsonb_build_object(
    'write',true,
    'domain',jsonb_build_object('update',jsonb_build_object(
      'effects',v_effects,'runs',v_runs,'pins',v_pins,'installs',v_installs)),
    'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),
    'request',jsonb_build_object('response',v_response),
    'events',v_events,
    'successors','[]'::jsonb);
END;
$$;
