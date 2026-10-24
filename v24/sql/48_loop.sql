-- S4 W1/W2/W3: native agent loop helpers, model/tool settlement interpreters
-- and the loop applier.  Every function here is INVOKER, carries an explicit
-- search_path and is revoked from every protocol role by 50_permissions.sql.
-- `advance` remains the only privileged terminal writer.  W2 adds the model
-- tool-call branch, tool settlement, the batch barrier and tool claim opening;
-- W3 adds model interaction production (runs.interaction, waiting) and the
-- respond-side blocked_unknown precedence.  pending_steer consumption is W5.

-- Numeric policy lives in exactly one place so gates can assert the contract.
CREATE FUNCTION v24.loop_policy() RETURNS jsonb LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, v24 AS $$
  SELECT jsonb_build_object('v',1,'max_tool_calls',16,'max_successors',16,
                            'max_state_bytes',65536,'reserve_tokens',4096)
$$;

-- F3=A admission reserve.  NULL remaining_tokens means "unlimited" and 0 means
-- "exhausted": both reserve 0, but only NULL admits a later model (C23 addendum B).
CREATE FUNCTION v24.model_reserve(p_remaining bigint) RETURNS bigint
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v24 AS $$
  SELECT CASE WHEN p_remaining IS NULL OR p_remaining <= 0 THEN 0
              ELSE LEAST(p_remaining, (v24.loop_policy()->>'reserve_tokens')::bigint) END
$$;

-- Three digests: policy/schema are version constants, toolset derives from the
-- live run pins.  Settlement independently recomputes and requires equality.
CREATE FUNCTION v24.model_digests(p_run uuid) RETURNS jsonb LANGUAGE sql STABLE
SET search_path = pg_catalog, v24 AS $$
  SELECT jsonb_build_object(
    'policy', encode(sha256(convert_to(v24.canonical_json(v24.loop_policy()),'UTF8')),'hex'),
    'schema', encode(sha256(convert_to(v24.canonical_json(jsonb_build_object(
                'v',1,'name','chat_tool_v1',
                'fields',jsonb_build_array('text','tool_calls','interaction','final','usage'))),'UTF8')),'hex'),
    'toolset', encode(sha256(convert_to(coalesce((
                SELECT jsonb_agg(jsonb_build_object('key',p.key,
                         'descriptor_digest',encode(p.descriptor_digest,'hex')) ORDER BY p.key)
                  FROM v24.pins p WHERE p.consumer_run_id=p_run AND p.released_at IS NULL
                 ),'[]'::jsonb)::text,'UTF8')),'hex'))
$$;

CREATE FUNCTION v24.model_effect_id(p_parent uuid, p_ordinal int) RETURNS uuid
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v24
AS $$ SELECT md5(p_parent::text||':model_call:'||p_ordinal)::uuid $$;

-- C20 identity: a tool effect's id is derived from its source model and ordinal.
CREATE FUNCTION v24.tool_effect_id(p_model uuid, p_ordinal int) RETURNS uuid
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v24
AS $$ SELECT md5(p_model::text||':tool_call:'||p_ordinal)::uuid $$;

CREATE FUNCTION v24.continuation_effect_id(p_model uuid) RETURNS uuid
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v24
AS $$ SELECT md5(p_model::text||':continuation')::uuid $$;

-- C18 single source of truth.  W2 opens tool_call in the same commit that
-- enables tool settlement.
CREATE FUNCTION v24.claimable_kinds() RETURNS text[] LANGUAGE sql IMMUTABLE
SET search_path = pg_catalog, v24
AS $$ SELECT ARRAY['host_prepare','host_release','model_call','tool_call']::text[] $$;

-- C23 seal predicate.  p_close_intent / p_interaction / p_pending_steer are the
-- values the current advance is ABOUT to persist (the interpreter cannot read
-- its own uncommitted writes); p_effect_id counts as already settled.
-- [S4-addendum] p_excluded names effects this same delta archives (steer), and
-- p_from_waiting admits a waiting -> terminal seal (respond).  Defaults keep the
-- model-settlement call sites unchanged.
CREATE FUNCTION v24.loop_sealable(p_run uuid, p_effect_id uuid,
  p_close_intent jsonb, p_interaction jsonb, p_pending_steer jsonb,
  p_excluded uuid[] DEFAULT '{}', p_from_waiting boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog, v24 AS $$
  SELECT (r.status = 'running' OR (p_from_waiting AND r.status = 'waiting'))
     AND p_close_intent IS NOT NULL AND p_close_intent <> 'null'::jsonb
     AND (p_interaction IS NULL OR p_interaction = 'null'::jsonb)
     AND (p_pending_steer IS NULL OR p_pending_steer = 'null'::jsonb)
     AND NOT EXISTS (
           SELECT 1 FROM v24.effects e
            WHERE e.run_id = r.run_id
              AND e.kind IN ('model_call','tool_call')
              AND (p_effect_id IS NULL OR e.effect_id <> p_effect_id)
              AND e.effect_id <> ALL (coalesce(p_excluded,'{}'::uuid[]))
              AND (e.status IN ('ready','claimed')
                   OR (e.status = 'unknown' AND e.resource_quiesced_at IS NULL)))
    FROM v24.runs r WHERE r.run_id = p_run;
$$;

-- C22 settlement-side pin release set.  The applier recomputes this exact value
-- before writing, so the delta cannot under- or over-release pins.
CREATE FUNCTION v24.run_pin_release_set(p_run uuid, p_effect_id uuid,
  p_status text, p_by_effect uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog, v24 AS $$
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'key',jsonb_build_object('pin_id',p.pin_id),
           'set',jsonb_build_object('released_at',now(),
                                    'released_by_effect',p_by_effect))
           ORDER BY p.pin_id),'[]'::jsonb)
    FROM v24.pins p
   WHERE p.consumer_run_id = p_run AND p.released_at IS NULL
     AND p_status IN ('completed','failed','cancelled','blocked_unknown')
     AND NOT EXISTS (
           SELECT 1 FROM v24.effects e
            WHERE e.pin_id = p.pin_id
              AND (p_effect_id IS NULL OR e.effect_id <> p_effect_id)
              AND (e.status IN ('ready','claimed')
                   OR (e.status = 'unknown' AND e.resource_quiesced_at IS NULL)));
$$;

-- C19 model settlement.  Every structural check precedes the first DML and
-- failures return {write:false,error} so the caller's transaction stays clean.
CREATE FUNCTION v24.interpret_model_settlement(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  r v24.runs%ROWTYPE;
  parent v24.effects%ROWTYPE;
  v_model_parent v24.effects%ROWTYPE;
  v_class text := p_outcome->>'class';
  v_res jsonb := p_outcome->'body'->'result';
  v_item jsonb;
  v_usage jsonb;
  v_usage_tokens bigint;
  v_reserve bigint := 0;
  v_refund bigint;
  v_turn bigint;
  v_steps int;
  v_tool_calls int;
  v_wall bigint;
  v_tokens bigint;
  v_late boolean := false;
  v_cancel_late boolean := false;
  v_sealed boolean := false;
  v_semantic boolean := false;
  v_admit boolean := false;
  v_cause text;
  v_req_keys text[];
  v_status text;
  v_effect_status text;
  v_quiesced boolean := true;
  v_close jsonb;
  v_result jsonb;
  v_interaction jsonb := NULL;
  v_ix jsonb := NULL;
  v_pending jsonb;
  v_ended timestamptz;
  v_events jsonb := '[]'::jsonb;
  v_succ jsonb := '[]'::jsonb;
  v_pins jsonb := '[]'::jsonb;
  v_digests jsonb;
  v_new_model uuid;
  v_batch text;
  v_input jsonb;
  v_final_text text;
  v_budget jsonb;
  v_reserve_next bigint;
  v_n_tools int := 0;
  v_i int;
  v_pin_id uuid;
  v_pin_digest text;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id = p_effect_id;
  IF NOT FOUND OR e.kind <> 'model_call' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  SELECT * INTO r FROM v24.runs WHERE run_id = e.run_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF r.status = 'blocked_unknown' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('blocked_unknown'));
  ELSIF r.status IN ('completed','failed') THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('already_terminal'));
  ELSIF r.status = 'cancelled'
        AND NOT (e.status = 'claimed' AND e.cancel_requested) THEN
    -- Only the claim cancel already revoked may still report its fact/cost
    -- (C19/G2b-O).  Anything else on a cancelled run stays terminal.
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('already_terminal'));
  END IF;
  v_cancel_late := r.status = 'cancelled';

  -- C19.0 structural class, first: receipt and result shape, never any DML.
  IF (p_outcome->>'v') IS DISTINCT FROM '1'
     OR v_class IS NULL OR v_class NOT IN ('success','failure','unknown')
     OR jsonb_typeof(p_outcome->'body') IS DISTINCT FROM 'object'
     OR (p_outcome->'body'->>'kind') IS DISTINCT FROM 'model_call' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF jsonb_typeof(v_res) IS DISTINCT FROM 'object' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_object_keys(v_res) k
              WHERE k NOT IN ('text','tool_calls','interaction','final','usage')) THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF v_res ? 'text' AND jsonb_typeof(v_res->'text') NOT IN ('string','null') THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  BEGIN
    IF v_res ? 'tool_calls' AND v_res->'tool_calls' <> 'null'::jsonb THEN
      IF jsonb_typeof(v_res->'tool_calls') IS DISTINCT FROM 'array'
         OR jsonb_array_length(v_res->'tool_calls') >
            (v24.loop_policy()->>'max_tool_calls')::int THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      FOR v_item IN SELECT value FROM jsonb_array_elements(v_res->'tool_calls') LOOP
        IF jsonb_typeof(v_item) IS DISTINCT FROM 'object' THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
        IF NOT (v_item ?& ARRAY['key','args'])
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_item) k
                       WHERE k NOT IN ('key','args'))
           OR jsonb_typeof(v_item->'key') IS DISTINCT FROM 'string'
           OR length(v_item->>'key') NOT BETWEEN 1 AND 256
           OR jsonb_typeof(v_item->'args') IS DISTINCT FROM 'object' THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
      END LOOP;
    END IF;
    v_ix := v_res->'interaction';
    IF v_ix IS NOT NULL AND v_ix <> 'null'::jsonb THEN
      -- C19.1: the host supplies exactly the two digests and the payload.  The
      -- digests are frozen as lowercase hex; S3's seeded bytea-style form is
      -- also accepted and preserved byte-for-byte (respond only reads the two
      -- ids, so the representation is audit data, not control data).
      IF jsonb_typeof(v_ix) IS DISTINCT FROM 'object'
         OR NOT (v_ix ?& ARRAY['schema_digest','prompt_digest','payload'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_ix) k
                     WHERE k NOT IN ('schema_digest','prompt_digest','payload'))
         OR jsonb_typeof(v_ix->'schema_digest') IS DISTINCT FROM 'string'
         OR jsonb_typeof(v_ix->'prompt_digest') IS DISTINCT FROM 'string'
         OR NOT (
              (length(v_ix->>'schema_digest') = 64
               AND (v_ix->>'schema_digest') ~ '^[0-9a-f]{64}$')
              OR (length(v_ix->>'schema_digest') = 66
                  AND left(v_ix->>'schema_digest',2) = chr(92)||'x'
                  AND right(v_ix->>'schema_digest',64) ~ '^[0-9a-f]{64}$'))
         OR NOT (
              (length(v_ix->>'prompt_digest') = 64
               AND (v_ix->>'prompt_digest') ~ '^[0-9a-f]{64}$')
              OR (length(v_ix->>'prompt_digest') = 66
                  AND left(v_ix->>'prompt_digest',2) = chr(92)||'x'
                  AND right(v_ix->>'prompt_digest',64) ~ '^[0-9a-f]{64}$'))
         OR jsonb_typeof(v_ix->'payload') IS DISTINCT FROM 'object' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
    END IF;
    IF v_res ? 'final' AND v_res->'final' <> 'null'::jsonb THEN
      IF jsonb_typeof(v_res->'final') IS DISTINCT FROM 'object' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      IF NOT (v_res->'final' ? 'text')
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_res->'final') k WHERE k <> 'text')
         OR jsonb_typeof(v_res->'final'->'text') NOT IN ('string','null') THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
    END IF;
    v_usage := v_res->'usage';
    IF v_usage IS NOT NULL AND v_usage <> 'null'::jsonb THEN
      IF jsonb_typeof(v_usage) IS DISTINCT FROM 'object' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      IF NOT (v_usage ?& ARRAY['tokens','wall_ms'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_usage) k
                     WHERE k NOT IN ('tokens','wall_ms'))
         OR jsonb_typeof(v_usage->'tokens') IS DISTINCT FROM 'number'
         OR (v_usage->>'tokens') !~ '^[0-9]+$'
         OR jsonb_typeof(v_usage->'wall_ms') IS DISTINCT FROM 'number'
         OR (v_usage->>'wall_ms') !~ '^[0-9]+$' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      v_usage_tokens := (v_usage->>'tokens')::bigint;
    END IF;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
      OR invalid_parameter_value THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END;
  -- C19 mutual exclusions.
  IF (CASE WHEN jsonb_typeof(v_res->'tool_calls') = 'array'
           THEN jsonb_array_length(v_res->'tool_calls') ELSE 0 END) > 0
     AND v_res->'final' IS NOT NULL AND v_res->'final' <> 'null'::jsonb THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  v_n_tools := CASE WHEN jsonb_typeof(v_res->'tool_calls') = 'array'
                    THEN jsonb_array_length(v_res->'tool_calls') ELSE 0 END;
  -- C19: an interaction is never published together with a tool batch.
  IF v_n_tools > 0 AND v_ix IS NOT NULL AND v_ix <> 'null'::jsonb THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;

  -- C17 request envelope: key closure, deterministic identity, allocation and
  -- digests.  A claim-time gate performed the same check; settlement repeats it
  -- because the digest recomputation below must never trust row contents.
  IF jsonb_typeof(e.request) IS DISTINCT FROM 'object' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF jsonb_typeof(e.request->'reserve') IS DISTINCT FROM 'object'
     OR jsonb_typeof(e.request->'digests') IS DISTINCT FROM 'object' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  v_cause := e.request->>'cause';
  BEGIN
    v_req_keys := ARRAY['v','cause','run_id','epoch_no','generation','reserve','digests'] ||
      CASE v_cause
        WHEN 'start' THEN ARRAY['input','budget']
        WHEN 'steer' THEN ARRAY['input','instruction']
        WHEN 'respond' THEN ARRAY['response','origin_effect_id']
        WHEN 'continuation' THEN ARRAY['input','batch_digest','state']
        ELSE ARRAY[]::text[] END;
    IF v_cause IS NULL OR v_cause NOT IN ('start','steer','respond','continuation')
       OR (e.request->>'v') IS DISTINCT FROM '1'
       OR NOT (e.request ?& v_req_keys)
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(e.request) k WHERE k <> ALL(v_req_keys))
       OR jsonb_typeof(e.request->'run_id') IS DISTINCT FROM 'string'
       OR e.request->>'run_id' IS DISTINCT FROM e.run_id::text
       OR jsonb_typeof(e.request->'epoch_no') IS DISTINCT FROM 'number'
       OR jsonb_typeof(e.request->'generation') IS DISTINCT FROM 'number'
       OR (e.request->>'epoch_no') !~ '^[0-9]+$'
       OR (e.request->>'generation') !~ '^[0-9]+$'
       OR (e.request->>'epoch_no')::bigint IS DISTINCT FROM e.epoch_no
       OR (e.request->>'generation')::bigint IS DISTINCT FROM e.generation
       OR e.pin_id IS NOT NULL
       OR jsonb_typeof(e.request->'reserve') IS DISTINCT FROM 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(e.request->'reserve')) <> 1
       OR NOT (e.request->'reserve' ? 'tokens')
       OR jsonb_typeof(e.request->'reserve'->'tokens') IS DISTINCT FROM 'number'
       OR (e.request->'reserve'->>'tokens') IS NULL
       OR (e.request->'reserve'->>'tokens') !~ '^[0-9]+$'
       OR (e.request->'reserve'->>'tokens')::bigint >
          (v24.loop_policy()->>'reserve_tokens')::bigint
       OR jsonb_typeof(e.request->'digests') IS DISTINCT FROM 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(e.request->'digests')) <> 3
       OR NOT (e.request->'digests' ?& ARRAY['policy','schema','toolset'])
       OR (e.request->'digests'->>'policy') IS NULL
       OR (e.request->'digests'->>'policy') !~ '^[0-9a-f]{64}$'
       OR (e.request->'digests'->>'schema') IS NULL
       OR (e.request->'digests'->>'schema') !~ '^[0-9a-f]{64}$'
       OR (e.request->'digests'->>'toolset') IS NULL
       OR (e.request->'digests'->>'toolset') !~ '^[0-9a-f]{64}$' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause IN ('start','steer','continuation')
       AND jsonb_typeof(e.request->'input') IS DISTINCT FROM 'object' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause = 'start' AND jsonb_typeof(e.request->'budget') IS DISTINCT FROM 'object' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause = 'steer' AND (jsonb_typeof(e.request->'instruction') IS DISTINCT FROM 'string'
        OR length(e.request->>'instruction') NOT BETWEEN 1 AND 8192) THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause = 'respond' AND (jsonb_typeof(e.request->'response') IS DISTINCT FROM 'object'
        OR jsonb_typeof(e.request->'origin_effect_id') IS DISTINCT FROM 'string'
        OR (e.request->>'origin_effect_id') IS NULL
        OR (e.request->>'origin_effect_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$') THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause = 'continuation' AND (
        jsonb_typeof(e.request->'state') IS DISTINCT FROM 'object'
        OR octet_length(v24.canonical_json(e.request->'state')) >
           (v24.loop_policy()->>'max_state_bytes')::int
        OR jsonb_typeof(e.request->'batch_digest') IS DISTINCT FROM 'string'
        OR (e.request->>'batch_digest') IS NULL
        OR (e.request->>'batch_digest') !~ '^[0-9a-f]{64}$') THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF e.parent_effect_id IS NULL OR e.ordinal IS DISTINCT FROM 0 THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    SELECT * INTO parent FROM v24.effects p WHERE p.effect_id = e.parent_effect_id;
    IF NOT FOUND OR parent.run_id IS DISTINCT FROM e.run_id THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause = 'continuation' THEN
      IF parent.kind = 'model_call' THEN
        IF e.effect_id IS DISTINCT FROM
           md5(e.parent_effect_id::text||':continuation')::uuid THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
      ELSIF parent.kind = 'tool_call' THEN
        -- C20: a tool-batch continuation's parent is the max-ordinal tool; its
        -- deterministic identity derives from the model batch parent.
        SELECT * INTO v_model_parent FROM v24.effects p
         WHERE p.effect_id = parent.parent_effect_id;
        IF NOT FOUND
           OR parent.parent_effect_id IS NULL
           OR v_model_parent.kind <> 'model_call'
           OR v_model_parent.run_id IS DISTINCT FROM e.run_id
           OR e.effect_id IS DISTINCT FROM
              md5(parent.parent_effect_id::text||':continuation')::uuid THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
      ELSE
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
    ELSE
      IF parent.kind <> 'command_'||v_cause
         OR e.effect_id IS DISTINCT FROM md5(e.parent_effect_id::text||':model_call:0')::uuid THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
    END IF;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
      OR invalid_parameter_value THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END;

  -- F1: independently recompute the three digests.  A cancelled run is the one
  -- exception: cancel may already have released pins, so the pin-derived
  -- toolset digest is no longer comparable; policy/schema are version constants
  -- and are still required to match byte for byte.
  v_digests := v24.model_digests(e.run_id);
  IF v_cancel_late THEN
    IF (e.request->'digests'->>'policy') IS DISTINCT FROM (v_digests->>'policy')
       OR (e.request->'digests'->>'schema') IS DISTINCT FROM (v_digests->>'schema') THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
  ELSIF e.request->'digests' IS DISTINCT FROM v_digests THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;

  v_reserve := (e.request->'reserve'->>'tokens')::bigint;

  -- C19.0 semantic class: the host executed, but the receipt proves the result
  -- cannot be trusted.  Never an error return; settle as unknown with the
  -- original receipt preserved as the first outcome.  A cancel-late settlement
  -- skips the pin-membership arm: cancel itself may have released the pins the
  -- host legitimately used, and the late delta publishes no successor anyway.
  IF NOT v_cancel_late AND v_res ? 'tool_calls' AND v_res->'tool_calls' <> 'null'::jsonb THEN
    FOR v_item IN SELECT value FROM jsonb_array_elements(v_res->'tool_calls') LOOP
      IF NOT EXISTS (SELECT 1 FROM v24.pins p
                      WHERE p.consumer_run_id = e.run_id AND p.released_at IS NULL
                        AND p.key = v_item->>'key') THEN
        v_semantic := true;
      END IF;
    END LOOP;
  END IF;
  IF v_reserve > 0 AND coalesce(v_usage_tokens,0) > v_reserve THEN
    v_semantic := true;
  END IF;

  -- W2 admits a structurally valid tool batch only through the dedicated
  -- branch below; semantic violations already became unknown above.
  v_turn := r.turn_no + 1;
  v_steps := r.remaining_steps;
  v_tool_calls := r.remaining_tool_calls;
  v_wall := greatest(0, r.remaining_wall_ms -
    coalesce((extract(epoch from (now()-e.created_at))*1000)::bigint,0));
  IF v_class IN ('success','failure') AND NOT v_semantic THEN
    v_refund := v_reserve - coalesce(v_usage_tokens,0);
    v_tokens := CASE WHEN r.remaining_tokens IS NULL THEN NULL
                     ELSE greatest(0, r.remaining_tokens + v_refund) END;
  ELSE
    -- unknown and semantic settlements never refund (uncertain consumption).
    v_tokens := r.remaining_tokens;
  END IF;

  v_late := e.generation IS DISTINCT FROM r.driving_generation
            OR e.epoch_no IS DISTINCT FROM r.epoch_no;

  IF v_cancel_late THEN
    -- G2b-O order 2: cancel won the race.  The original token still reports the
    -- external fact and pays its cost, but it cannot rewrite the cancel seal or
    -- publish any successor.  unknown stays unknown on the effect without
    -- re-sealing a cancelled run as blocked_unknown (cancel is authoritative).
    v_status := r.status;
    v_close := r.close_intent;
    v_result := r.result;
    v_interaction := r.interaction;
    v_pending := r.pending_steer;
    v_ended := r.ended_at;
    v_effect_status := CASE WHEN v_class = 'unknown' OR v_semantic THEN 'unknown'
                            WHEN v_class = 'failure' THEN 'failed'
                            ELSE 'succeeded' END;
    v_quiesced := NOT (v_class = 'unknown' OR v_semantic);
    IF v_quiesced THEN
      v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,r.status,p_effect_id);
    ELSE
      v_pins := v24.run_pin_release_set(e.run_id,NULL,r.status,p_effect_id);
    END IF;
    v_events := jsonb_build_array(jsonb_build_object(
      'entity_type','run','entity_id',e.run_id,
      'event_kind',CASE WHEN v_class = 'unknown' OR v_semantic
                        THEN 'model_call_unknown'
                        WHEN v_class = 'failure' THEN 'model_call_failed'
                        ELSE 'model_call_settled' END,
      'payload',jsonb_build_object(
        'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',true,
        'reason',CASE WHEN v_semantic THEN 'semantic_violation'
                      WHEN v_class = 'unknown' THEN 'outcome_unknown'
                      ELSE NULL END)));
  ELSIF v_class = 'unknown' THEN
    v_status := 'blocked_unknown';
    v_effect_status := 'unknown';
    v_quiesced := false;
    v_close := jsonb_build_object('kind','unknown','reason','outcome_unknown',
                                  'effect_id',p_effect_id);
    v_result := jsonb_build_object('v',1,'close_reason','unknown','turn_no',v_turn);
    v_interaction := NULL; v_pending := NULL; v_ended := now();
    v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','model_call_unknown','payload',jsonb_build_object(
          'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,
          'reason','outcome_unknown')),
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','run_blocked_unknown','payload',jsonb_build_object(
          'run_id',e.run_id,'reason','outcome_unknown','effect_id',p_effect_id)));
  ELSIF v_semantic THEN
    v_status := 'blocked_unknown';
    v_effect_status := 'unknown';
    v_quiesced := false;
    v_close := jsonb_build_object('kind','unknown','reason','semantic_violation',
                                  'effect_id',p_effect_id);
    v_result := jsonb_build_object('v',1,'close_reason','unknown','turn_no',v_turn);
    v_interaction := NULL; v_pending := NULL; v_ended := now();
    v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','model_call_unknown','payload',jsonb_build_object(
          'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,
          'reason','semantic_violation')),
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','run_blocked_unknown','payload',jsonb_build_object(
          'run_id',e.run_id,'reason','semantic_violation','effect_id',p_effect_id)));
  ELSIF v_late THEN
    -- C21: only facts and cost survive a settlement from an older generation.
    v_effect_status := CASE WHEN v_class = 'failure' THEN 'failed' ELSE 'succeeded' END;
    v_quiesced := true;
    v_status := r.status;
    v_close := r.close_intent; v_result := r.result;
    v_interaction := r.interaction; v_pending := r.pending_steer;
    v_ended := r.ended_at;
    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind',CASE WHEN v_class = 'failure' THEN 'model_call_failed'
                          ELSE 'model_call_settled' END,
        'payload',jsonb_build_object(
          'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',true)));
  ELSIF v_class = 'failure' THEN
    v_status := 'failed';
    v_effect_status := 'failed';
    v_quiesced := true;
    v_close := jsonb_build_object('kind','abort','reason','provider_failure',
                                  'effect_id',p_effect_id);
    v_result := jsonb_build_object('v',1,'close_reason','provider_failure',
                                   'turn_no',v_turn);
    v_interaction := NULL; v_pending := NULL; v_ended := now();
    v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','model_call_failed','payload',jsonb_build_object(
          'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)),
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','run_failed','payload',jsonb_build_object(
          'run_id',e.run_id,'close_reason','provider_failure','turn_no',v_turn)));
  ELSE
    v_effect_status := 'succeeded';
    v_quiesced := true;
    IF v_res ? 'final' AND v_res->'final' <> 'null'::jsonb THEN
      v_final_text := v_res->'final'->>'text';
      v_close := jsonb_build_object('kind','final');
      v_sealed := v24.loop_sealable(e.run_id,p_effect_id,v_close,NULL,r.pending_steer);
      IF v_sealed THEN
        SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
         WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
         ORDER BY e2.created_at, e2.effect_id LIMIT 1;
        IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
          v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
            'tool_calls',v_tool_calls,'wall_ms',v_wall);
        END IF;
        v_status := 'completed';
        v_result := jsonb_build_object('v',1,'close_reason','final',
          'final_text',v_final_text,'turn_no',v_turn,'budget',v_budget);
        v_interaction := NULL; v_pending := NULL; v_ended := now();
        v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
        v_events := jsonb_build_array(
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','model_call_settled','payload',jsonb_build_object(
              'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)),
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','run_completed','payload',jsonb_build_object(
              'run_id',e.run_id,'close_reason','final','turn_no',v_turn)));
      ELSE
        -- G2b-M: a ready/claimed business effect blocks the seal.  Only the
        -- minimal close intent is frozen; the batch-closing settlement reads
        -- final_text from this model's stored first outcome.
        v_close := jsonb_build_object('kind','final');
        v_status := r.status;
        v_result := r.result;
        v_interaction := r.interaction; v_pending := r.pending_steer;
        v_ended := r.ended_at;
        v_events := jsonb_build_array(
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','model_call_settled','payload',jsonb_build_object(
              'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)));
      END IF;
    ELSIF v_ix IS NOT NULL AND v_ix <> 'null'::jsonb THEN
      -- C19.1: one interaction per model outcome.  The ids are the source model
      -- effect id, generation is the run's driving generation, and the two host
      -- digests plus payload are copied byte-for-byte.  A waiting run has no
      -- pending steer and no successor; the respond command produces the next
      -- model effect under its own generation CAS.
      v_interaction := jsonb_build_object(
        'interaction_id', p_effect_id,
        'origin_effect_id', p_effect_id,
        'generation', r.driving_generation,
        'schema_digest', v_ix->'schema_digest',
        'prompt_digest', v_ix->'prompt_digest',
        'created_at', now());
      v_status := 'waiting';
      v_close := NULL; v_result := NULL;
      v_pending := NULL; v_ended := NULL;
      v_events := jsonb_build_array(
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','model_call_settled','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)),
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','interaction_created','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,
            'interaction_id',p_effect_id,'generation',r.driving_generation)));
    ELSIF v_n_tools > 0 THEN
      -- C20/F3=A: a structurally valid batch reserves one tool_call per item.
      IF v_n_tools > r.remaining_tool_calls THEN
        -- Budget exhausted: the model effect still succeeds and no tool is
        -- admitted; this is a seal, never an error (C23 tool_calls rule).
        v_close := jsonb_build_object('kind','budget');
        v_sealed := v24.loop_sealable(e.run_id,p_effect_id,v_close,NULL,r.pending_steer);
        IF v_sealed THEN
          SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
           WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
           ORDER BY e2.created_at, e2.effect_id LIMIT 1;
          IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
            v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
              'tool_calls',v_tool_calls,'wall_ms',v_wall);
          END IF;
          v_status := 'completed';
          v_result := jsonb_build_object('v',1,'close_reason','budget_exhausted',
            'final_text',NULL,'turn_no',v_turn,'budget',v_budget);
          v_interaction := NULL; v_pending := NULL; v_ended := now();
          v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
          v_events := jsonb_build_array(
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','model_call_settled','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)),
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','budget_exhausted','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)),
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','run_completed','payload',jsonb_build_object(
                'run_id',e.run_id,'close_reason','budget_exhausted','turn_no',v_turn)));
        ELSE
          v_status := r.status;
          v_result := r.result;
          v_interaction := r.interaction; v_pending := r.pending_steer;
          v_ended := r.ended_at;
          v_events := jsonb_build_array(
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','model_call_settled','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)));
        END IF;
      ELSE
        v_tool_calls := v_tool_calls - v_n_tools;
        v_status := r.status;
        v_close := r.close_intent; v_result := r.result;
        v_interaction := r.interaction; v_pending := r.pending_steer;
        v_ended := r.ended_at;
        -- batch_digest = sha256(tool ids ordered by ordinal), C20.
        SELECT encode(sha256(convert_to(string_agg(
                 v24.tool_effect_id(p_effect_id,g)::text, ',' ORDER BY g),'UTF8')),'hex')
          INTO v_batch FROM generate_series(0,v_n_tools-1) g;
        FOR v_i IN 0..v_n_tools-1 LOOP
          v_item := v_res->'tool_calls'->v_i;
          -- C22: every tool binds exactly one live run pin by key; the pin
          -- descriptor digest is frozen into the request.
          SELECT p.pin_id, encode(p.descriptor_digest,'hex')
            INTO v_pin_id, v_pin_digest
            FROM v24.pins p
           WHERE p.consumer_run_id = e.run_id AND p.released_at IS NULL
             AND p.key = v_item->>'key'
           ORDER BY p.pin_id LIMIT 1;
          IF v_pin_id IS NULL OR v_pin_digest IS NULL THEN
            RETURN jsonb_build_object('write',false,
              'error',v24.error_v1('invalid_outcome'));
          END IF;
          v_succ := v_succ || jsonb_build_array(jsonb_build_object(
            'effect_id',v24.tool_effect_id(p_effect_id,v_i),
            'parent_effect_id',p_effect_id,'ordinal',v_i,'kind','tool_call',
            'run_id',r.run_id,'fiber_id',r.owner_fiber_id,'episode_id',r.owner_episode_id,
            'epoch_no',r.epoch_no,'generation',r.driving_generation,
            'pin_id',v_pin_id,'replay_policy','no_replay',
            'request',jsonb_build_object(
              'v',1,'run_id',r.run_id,'epoch_no',r.epoch_no,
              'generation',r.driving_generation,'ordinal',v_i,
              'key',v_item->>'key','args',v_item->'args',
              'descriptor_digest',v_pin_digest,'batch_digest',v_batch)));
        END LOOP;
        v_events := jsonb_build_array(
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','model_call_settled','payload',jsonb_build_object(
              'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)),
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','tool_batch_admitted','payload',jsonb_build_object(
              'run_id',e.run_id,'effect_id',p_effect_id,'tool_calls',v_n_tools,
              'batch_digest',v_batch)));
      END IF;
    ELSE
      -- Plain non-final text.  W1 continues from the settling model itself; the
      -- tool-batch max-ordinal parent rule belongs to W2 tool settlement.
      v_admit := v_steps >= 1 AND v_wall > 0
                 AND (v_tokens IS NULL OR v_tokens > 0);
      IF v_admit THEN
        v_reserve_next := v24.model_reserve(v_tokens);
        v_steps := v_steps - 1;
        v_tokens := CASE WHEN v_tokens IS NULL THEN NULL
                         ELSE v_tokens - v_reserve_next END;
        v_status := r.status;
        v_close := NULL; v_result := NULL;
        v_interaction := r.interaction; v_pending := r.pending_steer;
        v_ended := r.ended_at;
        v_new_model := v24.continuation_effect_id(p_effect_id);
        v_batch := encode(sha256(convert_to('','UTF8')),'hex');
        -- start/steer/continuation carry input; respond carries no input, so
        -- inherit the most recent model input (C21's reducer input rule).
        v_input := coalesce(e.request->'input',
          (SELECT x.request->'input' FROM v24.effects x
            WHERE x.run_id = e.run_id AND x.kind = 'model_call'
              AND x.effect_id <> p_effect_id AND x.request ? 'input'
            ORDER BY x.created_at DESC, x.effect_id DESC LIMIT 1),
          '{}'::jsonb);
        v_succ := jsonb_build_array(jsonb_build_object(
          'effect_id',v_new_model,'parent_effect_id',p_effect_id,
          'ordinal',0,'kind','model_call',
          'run_id',r.run_id,'fiber_id',r.owner_fiber_id,'episode_id',r.owner_episode_id,
          'epoch_no',r.epoch_no,'generation',r.driving_generation,'pin_id',NULL,
          'replay_policy','no_replay',
          'request',jsonb_build_object(
            'v',1,'cause','continuation','run_id',r.run_id,'epoch_no',r.epoch_no,
            'generation',r.driving_generation,'input',v_input,
            'reserve',jsonb_build_object('tokens',v_reserve_next),
            'digests',v_digests,'batch_digest',v_batch,'state','{}'::jsonb)));
        v_events := jsonb_build_array(
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','model_call_settled','payload',jsonb_build_object(
              'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)));
      ELSE
        v_close := jsonb_build_object('kind','budget');
        v_sealed := v24.loop_sealable(e.run_id,p_effect_id,v_close,NULL,r.pending_steer);
        IF v_sealed THEN
          SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
           WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
           ORDER BY e2.created_at, e2.effect_id LIMIT 1;
          IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
            v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
              'tool_calls',v_tool_calls,'wall_ms',v_wall);
          END IF;
          v_status := 'completed';
          v_result := jsonb_build_object('v',1,'close_reason','budget_exhausted',
            'final_text',NULL,'turn_no',v_turn,'budget',v_budget);
          v_interaction := NULL; v_pending := NULL; v_ended := now();
          v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
          v_events := jsonb_build_array(
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','model_call_settled','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)),
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','budget_exhausted','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)),
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','run_completed','payload',jsonb_build_object(
                'run_id',e.run_id,'close_reason','budget_exhausted','turn_no',v_turn)));
        ELSE
          v_status := r.status;
          v_result := r.result;
          v_interaction := r.interaction; v_pending := r.pending_steer;
          v_ended := r.ended_at;
          v_events := jsonb_build_array(
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','model_call_settled','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)));
        END IF;
      END IF;
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'write',true,
    'domain',jsonb_build_object('update',jsonb_build_object(
      'runs',jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('run_id',e.run_id),
        'set',jsonb_build_object(
          'status',v_status,
          'turn_no',v_turn,
          'remaining_steps',v_steps,
          'remaining_tokens',v_tokens,
          'remaining_tool_calls',v_tool_calls,
          'remaining_wall_ms',v_wall,
          'interaction',v_interaction,
          'pending_steer',v_pending,
          'close_intent',v_close,
          'result',v_result,
          'revision',r.revision + 1,
          'ended_at',v_ended,
          'updated_at',now()))),
      'pins',v_pins)),
    'effect',jsonb_build_object('status',v_effect_status,
      'outcome',p_outcome,'resource_quiesced',v_quiesced),
    'events',v_events,
    'successors',v_succ);
END;
$$;

-- C19 tool settlement.  Structural failures are W0 and precede every DML; the
-- C20 batch barrier runs after the effect has been admitted to settle, in the
-- exact order fixed by the plan (siblings -> replay -> late -> model -> admit).
CREATE FUNCTION v24.interpret_tool_settlement(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  r v24.runs%ROWTYPE;
  parent v24.effects%ROWTYPE;
  v_class text := p_outcome->>'class';
  v_res jsonb := p_outcome->'body'->'result';
  v_status text;
  v_result text;
  v_usage jsonb;
  v_effect_status text;
  v_quiesced boolean := true;
  v_close jsonb;
  v_run_result jsonb;
  v_interaction jsonb;
  v_pending jsonb;
  v_ended timestamptz;
  v_turn bigint;
  v_wall bigint;
  v_steps int;
  v_tokens bigint;
  v_tool_calls int;
  v_late boolean := false;
  v_sibling boolean := false;
  v_cancel_late boolean := false;
  v_sealed boolean := false;
  v_seal_kind text;
  v_admit boolean := false;
  v_model uuid;
  v_max_ord int;
  v_cont uuid;
  v_reserve bigint;
  v_batch text;
  v_input jsonb;
  v_digests jsonb;
  v_events jsonb := '[]'::jsonb;
  v_succ jsonb := '[]'::jsonb;
  v_pins jsonb := '[]'::jsonb;
  v_budget jsonb;
  v_fact_event text;
  v_final_text text;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id = p_effect_id;
  IF NOT FOUND OR e.kind <> 'tool_call' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  SELECT * INTO r FROM v24.runs WHERE run_id = e.run_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  -- A run already at the unknown wall accepts no further business settlement.
  IF r.status = 'blocked_unknown' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('blocked_unknown'));
  END IF;
  -- Oracle CC3E40: a claim that cancel already revoked may still report its
  -- alternative fact (including unknown) without rewriting the cancel seal.
  v_cancel_late := r.status = 'cancelled' AND e.status = 'claimed'
                   AND e.cancel_requested;

  -- C19.0 structural class: receipt, result closure and class/status pairing,
  -- all before any DML.  The tool result schema is exactly
  -- {status: ok|error, output: object, usage: {wall_ms} | null}.
  IF (p_outcome->>'v') IS DISTINCT FROM '1'
     OR v_class IS NULL OR v_class NOT IN ('success','failure','unknown')
     OR jsonb_typeof(p_outcome->'body') IS DISTINCT FROM 'object'
     OR (p_outcome->'body'->>'kind') IS DISTINCT FROM 'tool_call' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF jsonb_typeof(v_res) IS DISTINCT FROM 'object' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF NOT (v_res ?& ARRAY['status','output'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_res) k
                 WHERE k NOT IN ('status','output','usage')) THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  v_result := v_res->>'status';
  IF v_result IS NULL OR v_result NOT IN ('ok','error')
     OR jsonb_typeof(v_res->'output') IS DISTINCT FROM 'object' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF v_class = 'success' AND v_result IS DISTINCT FROM 'ok' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF v_class = 'failure' AND v_result IS DISTINCT FROM 'error' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  v_usage := v_res->'usage';
  IF v_usage IS NOT NULL AND v_usage <> 'null'::jsonb THEN
    IF jsonb_typeof(v_usage) IS DISTINCT FROM 'object'
       OR NOT (v_usage ? 'wall_ms')
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_usage) k WHERE k <> 'wall_ms')
       OR jsonb_typeof(v_usage->'wall_ms') IS DISTINCT FROM 'number'
       OR (v_usage->>'wall_ms') !~ '^[0-9]+$' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    BEGIN
      PERFORM (v_usage->>'wall_ms')::bigint;
    EXCEPTION WHEN numeric_value_out_of_range THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END;
  END IF;

  v_turn := r.turn_no + 1;
  v_wall := greatest(0, r.remaining_wall_ms -
    coalesce((extract(epoch from (now()-e.created_at))*1000)::bigint,0));
  v_steps := r.remaining_steps;
  v_tokens := r.remaining_tokens;
  v_tool_calls := r.remaining_tool_calls;

  IF v_class = 'unknown' THEN
    IF v_cancel_late THEN
      -- Oracle CC3E40: preserve the cancel seal byte-for-byte and publish only
      -- the settlement fact.  The settling unknown effect still blocks its own
      -- pin (resource not quiesced); no run_blocked_unknown / batch event.
      v_status := r.status;
      v_close := r.close_intent;
      v_run_result := r.result;
      v_interaction := r.interaction; v_pending := r.pending_steer;
      v_ended := r.ended_at;
      v_effect_status := 'unknown';
      v_quiesced := false;
      v_pins := v24.run_pin_release_set(e.run_id,NULL,r.status,p_effect_id);
      v_events := jsonb_build_array(
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','tool_call_unknown','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,
            'late',true,'reason','outcome_unknown')));
    ELSE
      -- C19 unknown wall: keep the original receipt, never quiesce this pin.
      v_status := 'blocked_unknown';
      v_effect_status := 'unknown';
      v_quiesced := false;
      v_close := jsonb_build_object('kind','unknown','reason','outcome_unknown',
                                    'effect_id',p_effect_id);
      v_run_result := jsonb_build_object('v',1,'close_reason','unknown','turn_no',v_turn);
      v_interaction := NULL; v_pending := NULL; v_ended := now();
      -- Keep the settling unknown effect as a pin blocker (resource not quiesced).
      v_pins := v24.run_pin_release_set(e.run_id,NULL,'blocked_unknown',p_effect_id);
      v_events := jsonb_build_array(
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','tool_call_unknown','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,
            'reason','outcome_unknown')),
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','run_blocked_unknown','payload',jsonb_build_object(
            'run_id',e.run_id,'reason','outcome_unknown','effect_id',p_effect_id)));
    END IF;
  ELSE
    v_effect_status := CASE WHEN v_class = 'failure' THEN 'failed' ELSE 'succeeded' END;
    v_quiesced := true;
    v_fact_event := CASE WHEN v_class = 'failure'
                         THEN 'tool_call_failed' ELSE 'tool_call_settled' END;
    -- Default late-preserving run values; a normal settlement overwrites only
    -- the columns it actually advances.
    v_status := r.status;
    v_close := r.close_intent; v_run_result := r.result;
    v_interaction := r.interaction; v_pending := r.pending_steer;
    v_ended := r.ended_at;

    IF e.parent_effect_id IS NULL OR e.ordinal IS NULL THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    SELECT * INTO parent FROM v24.effects p WHERE p.effect_id = e.parent_effect_id;
    IF NOT FOUND OR parent.kind <> 'model_call'
       OR parent.run_id IS DISTINCT FROM e.run_id THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;

    -- C20 step 3's late fact (terminal run or old generation) also decides
    -- whether this settlement may release terminal-run pins (C22).
    v_late := r.status IN ('completed','failed','cancelled','blocked_unknown')
              OR e.generation IS DISTINCT FROM r.driving_generation;
    IF v_late AND r.status IN ('completed','failed','cancelled') THEN
      v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,r.status,p_effect_id);
    END IF;

    -- C20 step 1: a live sibling means this batch is not closed.
    SELECT EXISTS (SELECT 1 FROM v24.effects x
                    WHERE x.parent_effect_id = e.parent_effect_id
                      AND x.kind = 'tool_call'
                      AND x.effect_id <> p_effect_id
                      AND x.status IN ('ready','claimed')) INTO v_sibling;
    IF NOT v_sibling THEN
      -- C20 step 2: the unique continuation was already published.
      IF EXISTS (SELECT 1 FROM v24.effects x
                  WHERE x.effect_id = v24.continuation_effect_id(e.parent_effect_id)) THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      -- C20 step 3: a terminal run or an old generation observes only facts.
      IF NOT v_late THEN
        -- G2b-M: the model already froze a final close_intent but could not seal
        -- because this batch was still live.  The closing settlement materialises
        -- that frozen result instead of admitting a continuation, even when
        -- steps/tokens would still allow one.
        IF coalesce(r.close_intent->>'kind','') = 'final' THEN
          v_close := r.close_intent;
          v_sealed := v24.loop_sealable(e.run_id,p_effect_id,v_close,NULL,r.pending_steer);
          IF v_sealed THEN
            -- The frozen final text is the final-settling model's FIRST outcome
            -- receipt, which this terminal writer never rewrites.
            SELECT e2.outcome->'body'->'result'->'final'->>'text'
              INTO v_final_text
              FROM v24.effects e2
             WHERE e2.run_id = e.run_id AND e2.kind = 'model_call'
               AND e2.status = 'succeeded'
               AND e2.outcome->'body'->'result' ? 'final'
               AND e2.outcome->'body'->'result'->'final' <> 'null'::jsonb
             ORDER BY e2.settled_at DESC NULLS LAST, e2.effect_id DESC
             LIMIT 1;
            SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
             WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
             ORDER BY e2.created_at, e2.effect_id LIMIT 1;
            IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
              v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
                'tool_calls',v_tool_calls,'wall_ms',v_wall);
            END IF;
            v_seal_kind := 'final';
            v_status := 'completed';
            v_run_result := jsonb_build_object('v',1,'close_reason','final',
              'final_text',v_final_text,'turn_no',v_turn,'budget',v_budget);
            v_interaction := NULL; v_pending := NULL; v_ended := now();
            v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
          ELSE
            v_status := r.status;
            v_run_result := r.result;
            v_interaction := r.interaction; v_pending := r.pending_steer;
            v_ended := r.ended_at;
          END IF;
        ELSE
        -- C20 step 4: never race the partial unique model_call index.
        IF EXISTS (SELECT 1 FROM v24.effects x
                    WHERE x.run_id = e.run_id AND x.kind = 'model_call'
                      AND x.status IN ('ready','claimed')) THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
        -- C20 step 5: admission guards, then exactly one continuation.
        v_admit := v_steps >= 1 AND v_wall > 0
                   AND (v_tokens IS NULL OR v_tokens > 0);
        IF v_admit THEN
          v_reserve := v24.model_reserve(v_tokens);
          v_steps := v_steps - 1;
          v_tokens := CASE WHEN v_tokens IS NULL THEN NULL
                           ELSE v_tokens - v_reserve END;
          SELECT max(t.ordinal) INTO v_max_ord FROM v24.effects t
           WHERE t.parent_effect_id = e.parent_effect_id AND t.kind = 'tool_call';
          v_model := e.parent_effect_id;
          v_cont := v24.continuation_effect_id(v_model);
          SELECT encode(sha256(convert_to(
                   coalesce(string_agg(t.effect_id::text, ',' ORDER BY t.ordinal),''),
                   'UTF8')),'hex')
            INTO v_batch FROM v24.effects t
           WHERE t.parent_effect_id = v_model AND t.kind = 'tool_call';
          v_digests := v24.model_digests(e.run_id);
          -- start/steer/continuation/respond model requests may omit input;
          -- inherit the most recent model input like W1's plain continuation.
          v_input := coalesce(parent.request->'input',
            (SELECT x.request->'input' FROM v24.effects x
              WHERE x.run_id = e.run_id AND x.kind = 'model_call'
                AND x.effect_id <> v_model AND x.request ? 'input'
              ORDER BY x.created_at DESC, x.effect_id DESC LIMIT 1),
            '{}'::jsonb);
          v_status := r.status;
          v_close := NULL; v_run_result := NULL;
          v_interaction := r.interaction; v_pending := r.pending_steer;
          v_ended := r.ended_at;
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id',v_cont,
            'parent_effect_id',v24.tool_effect_id(v_model,v_max_ord),
            'ordinal',0,'kind','model_call',
            'run_id',r.run_id,'fiber_id',r.owner_fiber_id,'episode_id',r.owner_episode_id,
            'epoch_no',r.epoch_no,'generation',r.driving_generation,'pin_id',NULL,
            'replay_policy','no_replay',
            'request',jsonb_build_object(
              'v',1,'cause','continuation','run_id',r.run_id,'epoch_no',r.epoch_no,
              'generation',r.driving_generation,'input',v_input,
              'reserve',jsonb_build_object('tokens',v_reserve),
              'digests',v_digests,'batch_digest',v_batch,'state','{}'::jsonb)));
        ELSE
          v_close := jsonb_build_object('kind','budget');
          v_sealed := v24.loop_sealable(e.run_id,p_effect_id,v_close,NULL,r.pending_steer);
          IF v_sealed THEN
            SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
             WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
             ORDER BY e2.created_at, e2.effect_id LIMIT 1;
            IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
              v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
                'tool_calls',v_tool_calls,'wall_ms',v_wall);
            END IF;
            v_seal_kind := 'budget';
            v_status := 'completed';
            v_run_result := jsonb_build_object('v',1,'close_reason','budget_exhausted',
              'final_text',NULL,'turn_no',v_turn,'budget',v_budget);
            v_interaction := NULL; v_pending := NULL; v_ended := now();
            v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
          END IF;
        END IF;
        END IF;
      END IF;
    END IF;

    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind',v_fact_event,'payload',jsonb_build_object(
          'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',v_late)));
    IF NOT v_sibling AND NOT v_late THEN
      v_events := v_events || jsonb_build_array(
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','tool_batch_completed','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)));
      IF v_sealed THEN
        IF v_seal_kind = 'budget' THEN
          v_events := v_events || jsonb_build_array(
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','budget_exhausted','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)));
        END IF;
        v_events := v_events || jsonb_build_array(
          jsonb_build_object('entity_type','run','entity_id',e.run_id,
            'event_kind','run_completed','payload',jsonb_build_object(
              'run_id',e.run_id,
              'close_reason',CASE WHEN v_seal_kind = 'final'
                                  THEN 'final' ELSE 'budget_exhausted' END,
              'turn_no',v_turn)));
      END IF;
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'write',true,
    'domain',jsonb_build_object('update',jsonb_build_object(
      'runs',jsonb_build_array(jsonb_build_object(
        'key',jsonb_build_object('run_id',e.run_id),
        'set',jsonb_build_object(
          'status',v_status,
          'turn_no',v_turn,
          'remaining_steps',v_steps,
          'remaining_tokens',v_tokens,
          'remaining_tool_calls',v_tool_calls,
          'remaining_wall_ms',v_wall,
          'interaction',v_interaction,
          'pending_steer',v_pending,
          'close_intent',v_close,
          'result',v_run_result,
          'revision',r.revision + 1,
          'ended_at',v_ended,
          'updated_at',now()))),
      'pins',v_pins)),
    'effect',jsonb_build_object('status',v_effect_status,
      'outcome',p_outcome,'resource_quiesced',v_quiesced),
    'events',v_events,
    'successors',v_succ);
END;
$$;

-- S4 loop delta applier.  W2 accepts deterministic tool_call successors from a
-- model settlement and at most one deterministic model_call continuation from a
-- model or tool settlement; the delta key closure is exactly
-- {write,domain,effect,events,successors} and every check finishes before the
-- first write.  DML order: run -> effect -> events -> successors -> pins.
CREATE FUNCTION v24.validate_and_apply_loop_delta(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_delta jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  r v24.runs%ROWTYPE;
  upd jsonb;
  set_r jsonb;
  pins jsonb;
  ev jsonb;
  succ jsonb;
  v_status text;
  v_turn bigint;
  v_revision bigint;
  v_cancel_late boolean := false;
  v_expected_pins jsonb;
  v_succ_req jsonb;
  v_new_id uuid;
  v_seq bigint;
  v_emitted jsonb := '[]'::jsonb;
  v_events jsonb;
  v_succs jsonb;
  v_effect_status text;
  v_quiesced boolean;
  v_succ_kind text;
  v_succ_parent uuid;
  v_succ_ord int;
  v_tool_n int := 0;
  v_model_n int := 0;
  v_model_src uuid;
  v_max_ord int;
  v_batch_calc text;
  v_succ_pin v24.pins%ROWTYPE;
  v_event_kinds text[] := ARRAY[
    'model_call_requested','model_call_settled','model_call_failed','model_call_unknown',
    'tool_call_settled','tool_call_failed','tool_call_unknown','tool_batch_admitted',
    'tool_batch_completed','interaction_created','interaction_responded',
    'pending_steer_consumed','run_completed','run_failed','run_blocked_unknown',
    'budget_exhausted','run_pin_released','run_steered','run_cancelled'];
  v_run_keys text[] := ARRAY[
    'status','turn_no','remaining_steps','remaining_tokens','remaining_tool_calls',
    'remaining_wall_ms','interaction','pending_steer','close_intent','result',
    'revision','ended_at','updated_at'];
BEGIN
  IF p_delta->>'write' = 'false' THEN
    RETURN p_delta->'error';
  END IF;
  IF jsonb_typeof(p_delta) IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta) k
              WHERE k NOT IN ('write','domain','effect','events','successors')) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (p_delta ?& ARRAY['write','domain','effect','events','successors']) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_typeof(p_delta->'domain') IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (p_delta->'domain' ? 'update')
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta->'domain') k WHERE k <> 'update') THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  upd := p_delta->'domain'->'update';
  IF jsonb_typeof(upd) IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_object_keys(upd) k
              WHERE k NOT IN ('runs','pins')) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_typeof(coalesce(upd->'runs','[]'::jsonb)) IS DISTINCT FROM 'array'
     OR jsonb_array_length(coalesce(upd->'runs','[]'::jsonb)) <> 1
     OR jsonb_typeof(coalesce(upd->'pins','[]'::jsonb)) IS DISTINCT FROM 'array' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;

  SELECT * INTO e FROM v24.effects WHERE effect_id = p_effect_id;
  IF NOT FOUND OR e.kind NOT IN ('model_call','tool_call') THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  SELECT * INTO r FROM v24.runs WHERE run_id = e.run_id;
  -- A tool may settle late on a sealed run (cancel leaves claimed tools alive).
  -- A model may do so only when cancel revoked its claim: that narrow case writes
  -- fact/cost while preserving the cancel seal (G2b-O order 2); every other
  -- terminal model delta, including completed/failed/blocked_unknown rewrites,
  -- stays invalid.
  IF NOT FOUND
     OR (r.status IN ('completed','failed','cancelled','blocked_unknown')
         AND NOT (e.kind = 'tool_call'
                  OR (r.status = 'cancelled' AND e.kind = 'model_call'
                      AND e.status = 'claimed' AND e.cancel_requested))) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  v_cancel_late := r.status = 'cancelled' AND e.kind IN ('model_call','tool_call')
                   AND e.status = 'claimed' AND e.cancel_requested;

  -- Effect receipt matches the incoming class exactly.
  IF jsonb_typeof(p_delta->'effect') IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (p_delta->'effect' ?& ARRAY['status','outcome','resource_quiesced'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta->'effect') k
                 WHERE k NOT IN ('status','outcome','resource_quiesced')) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  v_effect_status := p_delta->'effect'->>'status';
  IF v_effect_status IS NULL OR v_effect_status NOT IN ('succeeded','failed','unknown') THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_typeof(p_delta->'effect'->'resource_quiesced') IS DISTINCT FROM 'boolean' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  v_quiesced := p_delta->'effect'->'resource_quiesced' = 'true'::jsonb;
  IF p_delta->'effect'->'outcome' IS DISTINCT FROM p_outcome THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF p_outcome->>'class' = 'success' THEN
    IF v_effect_status = 'succeeded' AND NOT v_quiesced THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF v_effect_status = 'unknown' AND v_quiesced THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF p_outcome->>'class' = 'failure' THEN
    IF v_effect_status <> 'failed' OR NOT v_quiesced THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF p_outcome->>'class' = 'unknown' THEN
    IF v_effect_status <> 'unknown' OR v_quiesced THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSE
    RETURN v24.error_v1('invalid_outcome');
  END IF;

  -- Exactly one run row, exactly the frozen 13-column set.
  IF jsonb_typeof(upd->'runs'->0) IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (upd->'runs'->0 ?& ARRAY['key','set'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(upd->'runs'->0) k
                 WHERE k NOT IN ('key','set'))
     OR jsonb_typeof(upd->'runs'->0->'key') IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (upd->'runs'->0->'key' ? 'run_id')
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(upd->'runs'->0->'key') k
                 WHERE k <> 'run_id')
     OR upd->'runs'->0->'key'->>'run_id' IS DISTINCT FROM e.run_id::text THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  set_r := upd->'runs'->0->'set';
  IF jsonb_typeof(set_r) IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (set_r ?& v_run_keys)
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(set_r) k WHERE k <> ALL(v_run_keys)) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;

  BEGIN
    v_status := set_r->>'status';
    IF v_status IS NULL OR v_status NOT IN
         ('running','waiting','completed','failed','blocked_unknown','cancelled') THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    -- A cancel-late settlement (model or tool) may only preserve the cancel
    -- seal: the completed/failed/blocked_unknown terminal writers stay refused.
    IF v_cancel_late AND v_status IS DISTINCT FROM 'cancelled' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF jsonb_typeof(set_r->'turn_no') IS DISTINCT FROM 'number'
       OR jsonb_typeof(set_r->'revision') IS DISTINCT FROM 'number'
       OR jsonb_typeof(set_r->'remaining_steps') IS DISTINCT FROM 'number'
       OR jsonb_typeof(set_r->'remaining_tool_calls') IS DISTINCT FROM 'number'
       OR jsonb_typeof(set_r->'remaining_wall_ms') IS DISTINCT FROM 'number'
       OR jsonb_typeof(set_r->'remaining_tokens') NOT IN ('number','null') THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    v_turn := (set_r->>'turn_no')::bigint;
    v_revision := (set_r->>'revision')::bigint;
    IF v_turn IS DISTINCT FROM r.turn_no + 1
       OR v_revision IS DISTINCT FROM r.revision + 1 THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF (set_r->>'remaining_steps')::int > r.remaining_steps
       OR (set_r->>'remaining_steps')::int < 0
       OR (set_r->>'remaining_tool_calls')::int > r.remaining_tool_calls
       OR (set_r->>'remaining_tool_calls')::int < 0
       OR (set_r->>'remaining_wall_ms')::bigint > r.remaining_wall_ms
       OR (set_r->>'remaining_wall_ms')::bigint < 0 THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF r.remaining_tokens IS NULL AND set_r->'remaining_tokens' <> 'null'::jsonb THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF r.remaining_tokens IS NOT NULL
       AND (set_r->'remaining_tokens' = 'null'::jsonb
            OR (set_r->>'remaining_tokens')::bigint < 0) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    -- Terminal shape is exclusive: ended_at is non-null iff the run is terminal.
    IF v_status IN ('completed','failed','blocked_unknown','cancelled') THEN
      IF set_r->'ended_at' = 'null'::jsonb THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF set_r->'pending_steer' <> 'null'::jsonb
         OR set_r->'interaction' <> 'null'::jsonb THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSE
      IF set_r->'ended_at' <> 'null'::jsonb THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
    IF v_status = 'waiting' THEN
      IF set_r->'interaction' IS NULL OR set_r->'interaction' = 'null'::jsonb THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSIF set_r->'interaction' <> 'null'::jsonb THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF v_status IN ('completed','failed') THEN
      IF v_status = r.status THEN
        -- A late tool settlement must preserve the existing seal byte for byte.
        IF set_r->'close_intent' IS DISTINCT FROM
              coalesce(r.close_intent,'null'::jsonb)
           OR set_r->'result' IS DISTINCT FROM coalesce(r.result,'null'::jsonb) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      ELSE
        IF NOT v24.loop_sealable(e.run_id,p_effect_id,set_r->'close_intent',
                                 set_r->'interaction',set_r->'pending_steer') THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        IF v_status = 'completed' THEN
          IF set_r->'close_intent'->>'kind' IS NULL
             OR set_r->'close_intent'->>'kind' NOT IN ('final','budget') THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          IF set_r->'result'->>'close_reason' IS DISTINCT FROM
             (CASE WHEN set_r->'close_intent'->>'kind' = 'final'
                   THEN 'final' ELSE 'budget_exhausted' END) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        ELSE
          IF set_r->'close_intent'->>'kind' IS DISTINCT FROM 'abort'
             OR set_r->'result'->>'close_reason' IS DISTINCT FROM 'provider_failure' THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END IF;
      END IF;
    ELSIF v_status = 'blocked_unknown' THEN
      IF set_r->'close_intent'->>'kind' IS DISTINCT FROM 'unknown'
         OR set_r->'result'->>'close_reason' IS DISTINCT FROM 'unknown' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSIF v_status = 'cancelled' THEN
      -- Cancel is the only cancelled writer; a settlement may only preserve it.
      IF r.status IS DISTINCT FROM 'cancelled'
         OR set_r->'close_intent' IS DISTINCT FROM
            coalesce(r.close_intent,'null'::jsonb)
         OR set_r->'result' IS DISTINCT FROM coalesce(r.result,'null'::jsonb) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSE
      -- running: the seal writer is the only result writer, so result stays null.
      IF set_r->'result' <> 'null'::jsonb THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
    -- Effect status and run state must agree.  A tool failure never fails the
    -- run; a late tool settlement preserves whatever terminal state it found.
    -- A cancel-late settlement preserves the cancelled seal for every class, so
    -- its fact status is exempt from the run-state coupling below.
    IF v_effect_status = 'unknown' AND v_status <> 'blocked_unknown'
       AND NOT v_cancel_late THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF v_effect_status = 'failed' THEN
      IF e.kind = 'model_call' AND v_status <> 'failed'
         AND NOT v_cancel_late THEN
        RETURN v24.error_v1('invalid_outcome');
      ELSIF e.kind = 'tool_call'
            AND v_status NOT IN ('running','waiting','completed','failed','cancelled') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
    IF v_effect_status = 'succeeded' THEN
      IF e.kind = 'model_call'
         AND v_status NOT IN ('running','waiting','completed')
         AND NOT v_cancel_late THEN
        RETURN v24.error_v1('invalid_outcome');
      ELSIF e.kind = 'tool_call'
            AND v_status NOT IN ('running','waiting','completed','failed','cancelled') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
      OR invalid_parameter_value THEN
    RETURN v24.error_v1('invalid_outcome');
  END;

  -- C22: the supplied pin set must be exactly the recomputed release set.  An
  -- unquiesced unknown effect still blocks its own pin, so it is not excluded.
  IF v_effect_status = 'unknown' AND NOT v_quiesced THEN
    v_expected_pins := v24.run_pin_release_set(e.run_id,NULL,v_status,p_effect_id);
  ELSE
    v_expected_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
  END IF;
  pins := coalesce(upd->'pins','[]'::jsonb);
  IF pins IS DISTINCT FROM v_expected_pins THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;

  -- Events: run-only, closed kind set, unique kind, object payload.
  v_events := coalesce(p_delta->'events','[]'::jsonb);
  IF jsonb_typeof(v_events) IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_events) > 8 THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_events) x
              GROUP BY x->>'event_kind' HAVING count(*) > 1) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  BEGIN
    FOR ev IN SELECT value FROM jsonb_array_elements(v_events) LOOP
      IF jsonb_typeof(ev) IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF NOT (ev ?& ARRAY['entity_type','entity_id','event_kind','payload'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(ev) k
                     WHERE k NOT IN ('entity_type','entity_id','event_kind',
                                     'payload','payload_digest'))
         OR ev->>'entity_type' IS DISTINCT FROM 'run'
         OR ev->>'entity_id' IS NULL
         OR (ev->>'entity_id')::uuid IS DISTINCT FROM e.run_id
         OR ev->>'event_kind' IS NULL
         OR ev->>'event_kind' <> ALL (v_event_kinds)
         OR jsonb_typeof(ev->'payload') IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
  EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN
    RETURN v24.error_v1('invalid_outcome');
  END;

  -- Successors: deterministic tool_call effects from a model settlement, or
  -- exactly one deterministic model_call continuation from either settlement.
  v_succs := coalesce(p_delta->'successors','[]'::jsonb);
  IF jsonb_typeof(v_succs) IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_succs) > 16 THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  -- Cancel-late settlements record facts/cost only: no successor may be
  -- published under the old token (G2b-O order 2).
  IF v_cancel_late AND jsonb_array_length(v_succs) > 0 THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  BEGIN
    SELECT count(*) FILTER (WHERE x->>'kind' = 'tool_call'),
           count(*) FILTER (WHERE x->>'kind' = 'model_call')
      INTO v_tool_n, v_model_n
      FROM jsonb_array_elements(v_succs) x;
    IF v_tool_n + v_model_n <> jsonb_array_length(v_succs)
       OR v_model_n > 1
       OR (v_tool_n > 0 AND v_model_n > 0)
       OR (v_tool_n > 0 AND e.kind <> 'model_call') THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF v_tool_n > 0 THEN
      -- The batch is exactly this model's successor set, ordinal 0..N-1.
      SELECT encode(sha256(convert_to(string_agg(
               v24.tool_effect_id(p_effect_id,g)::text, ',' ORDER BY g),'UTF8')),'hex')
        INTO v_batch_calc FROM generate_series(0,v_tool_n-1) g;
    END IF;
    FOR succ IN SELECT value FROM jsonb_array_elements(v_succs) LOOP
      IF jsonb_typeof(succ) IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF NOT (succ ?& ARRAY['effect_id','parent_effect_id','ordinal','kind','run_id',
                            'epoch_no','generation','pin_id','request'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(succ) k
                     WHERE k NOT IN ('effect_id','parent_effect_id','ordinal','kind',
                                     'run_id','fiber_id','episode_id','epoch_no',
                                     'generation','pin_id','replay_policy','request')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      v_succ_kind := succ->>'kind';
      IF v_succ_kind IS NULL OR v_succ_kind NOT IN ('tool_call','model_call')
         OR jsonb_typeof(succ->'parent_effect_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(succ->'effect_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(succ->'ordinal') IS DISTINCT FROM 'number'
         OR (succ->>'ordinal') !~ '^[0-9]+$'
         OR (succ->>'ordinal')::int > 15
         OR jsonb_typeof(succ->'run_id') IS DISTINCT FROM 'string'
         OR (succ->>'run_id') IS DISTINCT FROM e.run_id::text
         OR jsonb_typeof(succ->'epoch_no') IS DISTINCT FROM 'number'
         OR jsonb_typeof(succ->'generation') IS DISTINCT FROM 'number'
         OR (succ->>'epoch_no')::bigint IS DISTINCT FROM r.epoch_no
         OR (succ->>'generation')::bigint IS DISTINCT FROM r.driving_generation
         OR (succ ? 'fiber_id'
             AND (succ->>'fiber_id')::uuid IS DISTINCT FROM r.owner_fiber_id)
         OR (succ ? 'episode_id'
             AND (succ->>'episode_id')::uuid IS DISTINCT FROM r.owner_episode_id)
         OR (succ ? 'replay_policy'
             AND succ->>'replay_policy' IS DISTINCT FROM 'no_replay') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      v_succ_parent := (succ->>'parent_effect_id')::uuid;
      v_succ_ord := (succ->>'ordinal')::int;
      v_succ_req := succ->'request';
      IF jsonb_typeof(v_succ_req) IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF v_succ_kind = 'tool_call' THEN
        -- C20: tool children of the settling model, ordinal in 0..15, and the
        -- effect id is derived from (parent, ordinal).
        IF v_succ_parent IS DISTINCT FROM p_effect_id
           OR (succ->>'effect_id')::uuid IS DISTINCT FROM
              v24.tool_effect_id(p_effect_id,v_succ_ord)
           OR jsonb_typeof(succ->'pin_id') IS DISTINCT FROM 'string' THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        IF NOT (v_succ_req ?& ARRAY['v','run_id','epoch_no','generation','ordinal',
                                    'key','args','descriptor_digest','batch_digest'])
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_succ_req) k
                       WHERE k NOT IN ('v','run_id','epoch_no','generation','ordinal',
                                       'key','args','descriptor_digest','batch_digest')) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        IF v_succ_req->>'v' IS DISTINCT FROM '1'
           OR v_succ_req->>'run_id' IS DISTINCT FROM e.run_id::text
           OR jsonb_typeof(v_succ_req->'epoch_no') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_succ_req->'generation') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_succ_req->'ordinal') IS DISTINCT FROM 'number'
           OR (v_succ_req->>'epoch_no')::bigint IS DISTINCT FROM r.epoch_no
           OR (v_succ_req->>'generation')::bigint IS DISTINCT FROM r.driving_generation
           OR (v_succ_req->>'ordinal')::int IS DISTINCT FROM v_succ_ord
           OR jsonb_typeof(v_succ_req->'key') IS DISTINCT FROM 'string'
           OR length(v_succ_req->>'key') NOT BETWEEN 1 AND 256
           OR jsonb_typeof(v_succ_req->'args') IS DISTINCT FROM 'object'
           OR jsonb_typeof(v_succ_req->'descriptor_digest') IS DISTINCT FROM 'string'
           OR (v_succ_req->>'descriptor_digest') !~ '^([0-9a-f]{2})+$'
           OR length(v_succ_req->>'descriptor_digest') > 256
           OR jsonb_typeof(v_succ_req->'batch_digest') IS DISTINCT FROM 'string'
           OR (v_succ_req->>'batch_digest') !~ '^[0-9a-f]{64}$'
           OR (v_succ_req->>'batch_digest') IS DISTINCT FROM v_batch_calc THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        -- C22 pin binding: same run, key, live, descriptor digest equal.
        SELECT * INTO v_succ_pin FROM v24.pins p
         WHERE p.pin_id = (succ->>'pin_id')::uuid;
        IF NOT FOUND
           OR v_succ_pin.consumer_run_id IS DISTINCT FROM e.run_id
           OR v_succ_pin.released_at IS NOT NULL
           OR v_succ_pin.key IS DISTINCT FROM v_succ_req->>'key'
           OR encode(v_succ_pin.descriptor_digest,'hex') IS DISTINCT FROM
              v_succ_req->>'descriptor_digest' THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      ELSE
        -- The single continuation: parent identity and deterministic id depend
        -- on the settlement kind (model plain text vs tool-batch closure).
        IF v_succ_ord <> 0 OR succ->'pin_id' <> 'null'::jsonb THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        IF e.kind = 'model_call' THEN
          IF v_succ_parent IS DISTINCT FROM p_effect_id THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          v_model_src := p_effect_id;
        ELSE
          SELECT max(t.ordinal) INTO v_max_ord FROM v24.effects t
           WHERE t.parent_effect_id = e.parent_effect_id AND t.kind = 'tool_call';
          IF v_max_ord IS NULL
             OR v_succ_parent IS DISTINCT FROM
                v24.tool_effect_id(e.parent_effect_id,v_max_ord) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          v_model_src := e.parent_effect_id;
        END IF;
        IF (succ->>'effect_id')::uuid IS DISTINCT FROM
           v24.continuation_effect_id(v_model_src) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        SELECT encode(sha256(convert_to(
                 coalesce(string_agg(t.effect_id::text, ',' ORDER BY t.ordinal),''),
                 'UTF8')),'hex')
          INTO v_batch_calc FROM v24.effects t
         WHERE t.parent_effect_id = v_model_src AND t.kind = 'tool_call';
        IF NOT (v_succ_req ?& ARRAY['v','cause','run_id','epoch_no','generation',
                                    'input','reserve','digests','batch_digest','state'])
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_succ_req) k
                       WHERE k NOT IN ('v','cause','run_id','epoch_no','generation',
                                       'input','reserve','digests','batch_digest','state')) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        IF v_succ_req->>'v' IS DISTINCT FROM '1'
           OR v_succ_req->>'cause' IS DISTINCT FROM 'continuation'
           OR v_succ_req->>'run_id' IS DISTINCT FROM e.run_id::text
           OR jsonb_typeof(v_succ_req->'epoch_no') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_succ_req->'generation') IS DISTINCT FROM 'number'
           OR (v_succ_req->>'epoch_no')::bigint IS DISTINCT FROM r.epoch_no
           OR (v_succ_req->>'generation')::bigint IS DISTINCT FROM r.driving_generation
           OR jsonb_typeof(v_succ_req->'input') IS DISTINCT FROM 'object'
           OR jsonb_typeof(v_succ_req->'reserve') IS DISTINCT FROM 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(v_succ_req->'reserve')) <> 1
           OR NOT (v_succ_req->'reserve' ? 'tokens')
           OR jsonb_typeof(v_succ_req->'reserve'->'tokens') IS DISTINCT FROM 'number'
           OR (v_succ_req->'reserve'->>'tokens') IS NULL
           OR (v_succ_req->'reserve'->>'tokens') !~ '^[0-9]+$'
           OR (v_succ_req->'reserve'->>'tokens')::bigint >
              (v24.loop_policy()->>'reserve_tokens')::bigint
           OR jsonb_typeof(v_succ_req->'digests') IS DISTINCT FROM 'object'
           OR v_succ_req->'digests' IS DISTINCT FROM v24.model_digests(e.run_id)
           OR jsonb_typeof(v_succ_req->'batch_digest') IS DISTINCT FROM 'string'
           OR (v_succ_req->>'batch_digest') IS NULL
           OR (v_succ_req->>'batch_digest') !~ '^[0-9a-f]{64}$'
           OR (v_succ_req->>'batch_digest') IS DISTINCT FROM v_batch_calc
           OR jsonb_typeof(v_succ_req->'state') IS DISTINCT FROM 'object'
           OR octet_length(v24.canonical_json(v_succ_req->'state')) >
              (v24.loop_policy()->>'max_state_bytes')::int THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      END IF;
    END LOOP;
    IF v_tool_n > 0 THEN
      -- Tool ordinals are contiguous 0..N-1 (no partial batch, C20 R3).
      IF (SELECT min((x->>'ordinal')::int) FROM jsonb_array_elements(v_succs) x) <> 0
         OR (SELECT max((x->>'ordinal')::int) FROM jsonb_array_elements(v_succs) x)
            <> v_tool_n - 1
         OR (SELECT count(DISTINCT (x->>'ordinal')::int)
               FROM jsonb_array_elements(v_succs) x) <> v_tool_n THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_succs) x
                GROUP BY x->>'effect_id' HAVING count(*) > 1) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_succs) x
                GROUP BY x->>'parent_effect_id', x->>'ordinal' HAVING count(*) > 1) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    -- No successor may collide with an existing (parent_effect_id, ordinal).
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_succs) x
                JOIN v24.effects ex
                  ON ex.parent_effect_id = (x->>'parent_effect_id')::uuid
                 AND ex.ordinal = (x->>'ordinal')::int) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF v_model_n = 1 THEN
      -- The partial unique index must never be reached through this path.
      IF EXISTS (SELECT 1 FROM v24.effects x WHERE x.run_id = e.run_id
                  AND x.effect_id <> p_effect_id
                  AND x.kind = 'model_call' AND x.status IN ('ready','claimed')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      -- The deterministic continuation identity is already taken.
      IF EXISTS (SELECT 1 FROM v24.effects x
                  WHERE x.effect_id = (v_succs->0->>'effect_id')::uuid) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
      OR invalid_parameter_value THEN
    RETURN v24.error_v1('invalid_outcome');
  END;

  -- Frozen DML order: run -> effect -> events -> successors -> pins.
  UPDATE v24.runs SET
    status = v_status,
    turn_no = v_turn,
    remaining_steps = (set_r->>'remaining_steps')::int,
    remaining_tokens = CASE WHEN set_r->'remaining_tokens' = 'null'::jsonb
                            THEN NULL ELSE (set_r->>'remaining_tokens')::bigint END,
    remaining_tool_calls = (set_r->>'remaining_tool_calls')::int,
    remaining_wall_ms = (set_r->>'remaining_wall_ms')::bigint,
    interaction = CASE WHEN set_r->'interaction' = 'null'::jsonb
                       THEN NULL ELSE set_r->'interaction' END,
    pending_steer = CASE WHEN set_r->'pending_steer' = 'null'::jsonb
                         THEN NULL ELSE set_r->'pending_steer' END,
    close_intent = CASE WHEN set_r->'close_intent' = 'null'::jsonb
                        THEN NULL ELSE set_r->'close_intent' END,
    result = CASE WHEN set_r->'result' = 'null'::jsonb
                  THEN NULL ELSE set_r->'result' END,
    revision = v_revision,
    ended_at = CASE WHEN set_r->'ended_at' = 'null'::jsonb
                    THEN NULL ELSE (set_r->>'ended_at')::timestamptz END,
    updated_at = (set_r->>'updated_at')::timestamptz
  WHERE run_id = e.run_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v24 loop: run changed during settlement' USING ERRCODE='40001';
  END IF;

  UPDATE v24.effects SET status = v_effect_status,
    outcome = p_delta->'effect'->'outcome',
    settled_at = now(),
    claim_owner = NULL,
    lease_until = NULL,
    resource_quiesced_at = CASE WHEN v_quiesced THEN now() ELSE NULL END
  WHERE effect_id = p_effect_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v24 loop: effect changed during settlement' USING ERRCODE='40001';
  END IF;

  FOR ev IN SELECT value FROM jsonb_array_elements(v_events) LOOP
    SELECT coalesce(max(x.seq),0)+1 INTO v_seq FROM v24.events x
     WHERE x.entity_type = ev->>'entity_type'
       AND x.entity_id = (ev->>'entity_id')::uuid;
    INSERT INTO v24.events(effect_id,seq,entity_type,entity_id,event_kind,payload,payload_digest)
    VALUES (p_effect_id,v_seq,'run',e.run_id,ev->>'event_kind',
      coalesce(ev->'payload','{}'::jsonb),
      coalesce((ev->>'payload_digest')::bytea,
               sha256(convert_to(v24.canonical_json(coalesce(ev->'payload','{}'::jsonb)),'UTF8'))));
  END LOOP;

  FOR succ IN SELECT value FROM jsonb_array_elements(v_succs) LOOP
    v_new_id := (succ->>'effect_id')::uuid;
    INSERT INTO v24.effects(effect_id,parent_effect_id,ordinal,requester_id,scope_id,run_id,
      fiber_id,episode_id,pin_id,epoch_no,generation,kind,status,request,request_digest,
      replay_policy,outcome,settled_at)
    VALUES (v_new_id,(succ->>'parent_effect_id')::uuid,(succ->>'ordinal')::int,
      p_principal,e.scope_id,e.run_id,
      coalesce((succ->>'fiber_id')::uuid,r.owner_fiber_id),
      coalesce((succ->>'episode_id')::uuid,r.owner_episode_id),
      (succ->>'pin_id')::uuid,(succ->>'epoch_no')::bigint,
      (succ->>'generation')::bigint,
      succ->>'kind','ready',succ->'request',
      sha256(convert_to(v24.canonical_json(succ->'request'),'UTF8')),
      'no_replay',NULL,NULL);
    v_emitted := v_emitted || jsonb_build_array(v_new_id);
  END LOOP;

  FOR ev IN SELECT value FROM jsonb_array_elements(v_expected_pins) LOOP
    UPDATE v24.pins SET released_at = (ev->'set'->>'released_at')::timestamptz,
      released_by_effect = p_effect_id
    WHERE pin_id = (ev->'key'->>'pin_id')::uuid
      AND consumer_run_id = e.run_id AND released_at IS NULL;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'v24 loop: pin release changed' USING ERRCODE='40001';
    END IF;
  END LOOP;

  RETURN jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',v_emitted,'revision',v_revision,'claim',NULL);
END;
$$;
