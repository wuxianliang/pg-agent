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

-- C18 single source of truth.  S5 W2 opens inspect_resource in the same commit
-- that registers its claim shape, settlement interpreter and applier branch.
CREATE FUNCTION v24.claimable_kinds() RETURNS text[] LANGUAGE sql IMMUTABLE
SECURITY INVOKER SET search_path = pg_catalog, v24
AS $$ SELECT ARRAY['host_prepare','host_release','model_call','tool_call','inspect_resource']::text[] $$;

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

-- C21 deterministic steer-consumption identity.  This deliberately owns its own
-- namespace: model_effect_id() keys on a command effect and
-- continuation_effect_id() keys on a model effect, while this one keys on the
-- run plus the pending steer's epoch/generation and an instruction digest.  The
-- same pending value always yields the same id, and two different pending
-- steers cannot collide with either existing namespace or with each other.
CREATE FUNCTION v24.steer_model_effect_id(p_run uuid, p_epoch bigint,
  p_generation bigint, p_instruction text) RETURNS uuid
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v24 AS $$
  SELECT md5(p_run::text||':steer_model:'||p_epoch::text||':'||p_generation::text
             ||':'||md5(coalesce(p_instruction,'')))::uuid
$$;

-- C21 consumption predicate: conditions 1, 2, 3 and 5.  Condition 4
-- (class <> unknown) belongs to the caller, which already routes unknown to the
-- blocked_unknown wall.  The predicate runs before any DML, so the settling
-- effect still has status ready/claimed in the table; p_effect_id makes it
-- count as settled.  Old generation is strict less-than: no effect can be
-- newer than the run, but only genuinely inherited work may consume a steer.
CREATE FUNCTION v24.steer_consumable(p_run uuid, p_effect_id uuid,
  p_epoch bigint, p_generation bigint) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, v24 AS $$
  SELECT coalesce((
    SELECT r.pending_steer IS NOT NULL
       AND r.status NOT IN ('completed','failed','cancelled','blocked_unknown')
       AND (p_epoch < r.epoch_no OR p_generation < r.driving_generation)
       AND NOT EXISTS (
             SELECT 1 FROM v24.effects e
              WHERE e.run_id = r.run_id
                AND e.kind IN ('model_call','tool_call')
                AND e.effect_id <> p_effect_id
                AND (e.epoch_no < r.epoch_no
                     OR e.generation < r.driving_generation)
                AND e.status IN ('ready','claimed'))
      FROM v24.runs r WHERE r.run_id = p_run), false)
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
  v_consume boolean := false;
  v_pending_epoch bigint;
  v_pending_gen bigint;
  v_pending_instruction text;
  v_steer_id uuid;
  v_steer_admit boolean := false;
  v_steer_sealed boolean := false;
  v_steer_reserve bigint;
  -- S8 W1: the reserved model-outcome intent.  v_spawn holds the validated
  -- args object; the child rows are built before any DML and emitted through
  -- domain.insert, never through successors[] (a child is a different run).
  v_spawn jsonb := NULL;
  v_spawn_count int := 0;
  v_spawn_key text;
  v_spawn_scope uuid;
  v_spawn_digest bytea;
  v_child_id uuid;
  v_child_effect_id uuid;
  v_child_steps int;
  v_child_tokens bigint;
  v_child_reserve bigint;
  v_child_tool_calls int;
  v_child_wall bigint;
  v_child_digests jsonb;
  v_child_request jsonb;
  v_child_run jsonb;
  v_child_effect jsonb;
  -- S8 W2: optional owner run pin and the same-key replay split.  The pin is
  -- the child run's capability binding and lives only in v24.pins; the owner
  -- episode also lands on the child run columns and on the child first model
  -- effect, whose effects.pin_id stays NULL.
  v_spawn_owner_fiber uuid;
  v_spawn_owner_episode uuid;
  v_spawn_owner_epoch bigint;
  v_spawn_fiber v24.fibers%ROWTYPE;
  v_spawn_episode v24.episodes%ROWTYPE;
  v_spawn_install v24.installs%ROWTYPE;
  v_spawn_activation v24.pins%ROWTYPE;
  v_spawn_act_count int := 0;
  v_spawn_pin jsonb;
  v_spawn_pin_id uuid;
  v_spawn_pins jsonb := '[]'::jsonb;
  v_spawn_replay boolean := false;
  v_spawn_child v24.runs%ROWTYPE;
  v_ins_runs jsonb := '[]'::jsonb;
  v_ins_effects jsonb := '[]'::jsonb;
  v_domain jsonb;
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
    -- S8 W1 spawn admission: a reserved intent on any non-running parent is
    -- already_terminal.  Non-spawn settlements keep the frozen blocked_unknown
    -- precedence (G2b-V/blocked).
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(
          CASE WHEN jsonb_typeof(v_res->'tool_calls') = 'array'
               THEN v_res->'tool_calls' ELSE '[]'::jsonb END) x
          WHERE jsonb_typeof(x) = 'object' AND x->>'key' = 'agent.spawn') THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('already_terminal'));
    END IF;
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
      IF jsonb_typeof(v_res->'tool_calls') IS DISTINCT FROM 'array' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      -- S8/R7: `agent.spawn` is a reserved intent, not a tool.  Split it out
      -- before max_tool_calls counting so it neither consumes the tool budget
      -- nor reaches the C22 pin-membership arm below.  v1 admits exactly one
      -- spawn per outcome and never mixes it with ordinary tools.
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
        IF v_item->>'key' = 'agent.spawn' THEN
          v_spawn_count := v_spawn_count + 1;
          IF v_spawn_count > 1 THEN
            RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
          END IF;
          v_spawn := v_item->'args';
        ELSE
          v_n_tools := v_n_tools + 1;
        END IF;
      END LOOP;
      IF v_spawn_count > 0 AND jsonb_array_length(v_res->'tool_calls') <> 1 THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      IF v_n_tools > (v24.loop_policy()->>'max_tool_calls')::int THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
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
  -- C19: an interaction is never published together with a tool batch or with
  -- the reserved spawn intent.  Spawn never shares an outcome with final either.
  IF v_n_tools > 0 AND v_ix IS NOT NULL AND v_ix <> 'null'::jsonb THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
  END IF;
  IF v_spawn IS NOT NULL
     AND (v_ix IS NOT NULL AND v_ix <> 'null'::jsonb
          OR v_res->'final' IS NOT NULL AND v_res->'final' <> 'null'::jsonb) THEN
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
        WHEN 'spawn' THEN ARRAY['input','spawn_key','parent_run_id']
        ELSE ARRAY[]::text[] END;
    IF v_cause IS NULL OR v_cause NOT IN ('start','steer','respond','continuation','spawn')
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
    IF v_cause IN ('start','steer','continuation','spawn')
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
    IF NOT FOUND
       OR (v_cause <> 'spawn' AND parent.run_id IS DISTINCT FROM e.run_id) THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF v_cause = 'spawn' THEN
      -- S8/R7: the child first model keeps the settling parent run's model
      -- effect as parent_effect_id even though its run_id is the child.
      IF parent.kind <> 'model_call'
         OR jsonb_typeof(e.request->'spawn_key') IS DISTINCT FROM 'string'
         OR (e.request->>'spawn_key') !~ '^[A-Za-z0-9._:-]{1,128}$'
         OR jsonb_typeof(e.request->'parent_run_id') IS DISTINCT FROM 'string'
         OR (e.request->>'parent_run_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
         OR parent.run_id IS DISTINCT FROM (e.request->>'parent_run_id')::uuid
         OR e.effect_id IS DISTINCT FROM
            md5(e.run_id::text||':model_call:0')::uuid
         OR NOT EXISTS (
              SELECT 1 FROM v24.runs cr
               WHERE cr.run_id = e.run_id
                 AND cr.parent_run_id = parent.run_id
                 AND cr.scope_id = e.scope_id
                 AND cr.spawn_key = e.request->>'spawn_key') THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
    ELSIF v_cause = 'continuation' THEN
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
    ELSIF v_cause = 'steer' AND parent.kind IN ('model_call','tool_call') THEN
      -- C21: a consumed pending steer is a steer-shaped request whose parent is
      -- the last old-generation settlement, not a command_steer.  Its identity
      -- is the C21 deterministic steer id (not the command model_call id).
      IF e.effect_id IS DISTINCT FROM v24.steer_model_effect_id(e.run_id,
           (e.request->>'epoch_no')::bigint,
           (e.request->>'generation')::bigint,
           e.request->>'instruction') THEN
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
      -- R7: the reserved spawn intent has no pin and is not a tool; the pin
      -- membership arm must never turn its absence into a semantic unknown.
      CONTINUE WHEN v_item->>'key' = 'agent.spawn';
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

  -- S8 W1 spawn admission.  Everything here is before any DML: a malformed,
  -- terminal, duplicate or over-budget spawn leaves the model effect claimed
  -- and the ten tables untouched.  The child rows are built as delta inserts
  -- and only reach the applier after the parent settlement succeeds.
  IF v_spawn IS NOT NULL THEN
    IF r.status <> 'running' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('already_terminal'));
    END IF;
    -- Spawn is a trusted success-side intent.  Unknown/semantic/late
    -- settlements publish no successor business, so they cannot mint a child.
    IF v_class <> 'success' OR v_semantic OR v_late THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    BEGIN
      IF jsonb_typeof(v_spawn) IS DISTINCT FROM 'object'
         OR NOT (v_spawn ?& ARRAY['v','spawn_key','input','scope_id','budget'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_spawn) k
                     WHERE k NOT IN ('v','spawn_key','input','scope_id','budget',
                                     'owner_fiber_id','owner_episode_id'))
         OR (v_spawn ? 'owner_fiber_id') IS DISTINCT FROM (v_spawn ? 'owner_episode_id')
         OR jsonb_typeof(v_spawn->'v') IS DISTINCT FROM 'number'
         OR (v_spawn->>'v') IS DISTINCT FROM '1'
         OR jsonb_typeof(v_spawn->'spawn_key') IS DISTINCT FROM 'string'
         OR (v_spawn->>'spawn_key') !~ '^[A-Za-z0-9._:-]{1,128}$'
         OR jsonb_typeof(v_spawn->'input') IS DISTINCT FROM 'object'
         OR jsonb_typeof(v_spawn->'scope_id') IS DISTINCT FROM 'string'
         OR jsonb_typeof(v_spawn->'budget') IS DISTINCT FROM 'object'
         OR NOT (v_spawn->'budget' ?& ARRAY['steps','tokens','tool_calls','wall_ms'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_spawn->'budget') k
                     WHERE k NOT IN ('steps','tokens','tool_calls','wall_ms'))
         OR jsonb_typeof(v_spawn->'budget'->'steps') IS DISTINCT FROM 'number'
         OR (v_spawn->'budget'->>'steps') !~ '^[0-9]+$'
         OR jsonb_typeof(v_spawn->'budget'->'tool_calls') IS DISTINCT FROM 'number'
         OR (v_spawn->'budget'->>'tool_calls') !~ '^[0-9]+$'
         OR jsonb_typeof(v_spawn->'budget'->'wall_ms') IS DISTINCT FROM 'number'
         OR (v_spawn->'budget'->>'wall_ms') !~ '^[0-9]+$'
         OR jsonb_typeof(v_spawn->'budget'->'tokens') NOT IN ('number','null')
         OR (jsonb_typeof(v_spawn->'budget'->'tokens') = 'number'
             AND (v_spawn->'budget'->>'tokens') !~ '^[0-9]+$') THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      v_spawn_key := v_spawn->>'spawn_key';
      v_spawn_scope := (v_spawn->>'scope_id')::uuid;
      v_child_steps := (v_spawn->'budget'->>'steps')::int;
      v_child_tool_calls := (v_spawn->'budget'->>'tool_calls')::int;
      v_child_wall := (v_spawn->'budget'->>'wall_ms')::bigint;
      IF v_child_steps < 1 OR v_child_tool_calls < 1 OR v_child_wall < 1 THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      IF jsonb_typeof(v_spawn->'budget'->'tokens') = 'null' THEN
        IF r.remaining_tokens IS NOT NULL THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
        v_child_tokens := NULL;
      ELSE
        v_child_tokens := (v_spawn->'budget'->>'tokens')::bigint;
        IF v_child_tokens < 1 THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
        END IF;
      END IF;
      IF v_spawn_scope IS DISTINCT FROM r.scope_id THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      -- §4.3 step 4: (parent_run_id,spawn_key) is the spawn identity.  Same
      -- canonical args bytes replay the existing child (no new child, quota,
      -- effect or event); different bytes are the 24th error code.  Both run
      -- before any DML, so a conflict leaves the model effect claimed.
      v_spawn_digest := sha256(convert_to(v24.canonical_json(v_spawn),'UTF8'));
      SELECT * INTO v_spawn_child FROM v24.runs cr
       WHERE cr.parent_run_id = r.run_id AND cr.spawn_key = v_spawn_key;
      IF FOUND THEN
        IF v_spawn_child.spawn_request_digest IS DISTINCT FROM v_spawn_digest THEN
          RETURN jsonb_build_object('write',false,
            'error',v24.error_v1('spawn_key_conflict'));
        END IF;
        v_spawn_replay := true;
        v_child_id := v_spawn_child.run_id;
        v_child_effect_id := md5(v_child_id::text||':model_call:0')::uuid;
        v_spawn_key := v_spawn_child.spawn_key;
      ELSE
        -- Oracle Q6=A / D-S8-9 / D-S8-10: the child grant must fit the parent's
        -- post-settlement balances.  Tokens are checked against the C19 refunded
        -- v_tokens, wall against the elapsed-adjusted v_wall; both then deduct
        -- the full child grant.  Nothing changes on failure.
        IF v_child_steps > v_steps
           OR v_child_tool_calls > v_tool_calls
           OR v_child_wall > v_wall
           OR (v_tokens IS NOT NULL
               AND (v_child_tokens IS NULL OR v_child_tokens > v_tokens)) THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('budget_exceeded'));
        END IF;
        -- §4.6 owner pair.  Both-or-none was checked with the args; a full pair
        -- must name a live fiber/episode whose single live activation pin lends
        -- the child run pin its provider tuple and descriptor.
        IF v_spawn ? 'owner_fiber_id' THEN
          IF jsonb_typeof(v_spawn->'owner_fiber_id') IS DISTINCT FROM 'string'
             OR jsonb_typeof(v_spawn->'owner_episode_id') IS DISTINCT FROM 'string' THEN
            RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
          END IF;
          v_spawn_owner_fiber := (v_spawn->>'owner_fiber_id')::uuid;
          v_spawn_owner_episode := (v_spawn->>'owner_episode_id')::uuid;
          SELECT * INTO v_spawn_fiber FROM v24.fibers f
           WHERE f.fiber_id = v_spawn_owner_fiber;
          IF NOT FOUND OR v_spawn_fiber.scope_id IS DISTINCT FROM r.scope_id
             OR v_spawn_fiber.disposed_at IS NOT NULL
             OR NOT v_spawn_fiber.want_on
             OR v_spawn_fiber.current_episode_id IS DISTINCT FROM v_spawn_owner_episode THEN
            RETURN jsonb_build_object('write',false,
              'error',v24.error_v1('provider_unavailable'));
          END IF;
          SELECT * INTO v_spawn_episode FROM v24.episodes ep
           WHERE ep.episode_id = v_spawn_owner_episode;
          IF NOT FOUND
             OR v_spawn_episode.fiber_id IS DISTINCT FROM v_spawn_owner_fiber
             OR v_spawn_episode.state IS DISTINCT FROM 'active' THEN
            RETURN jsonb_build_object('write',false,
              'error',v24.error_v1('provider_unavailable'));
          END IF;
          SELECT * INTO v_spawn_install FROM v24.installs it
           WHERE it.install_id = v_spawn_fiber.install_id;
          IF NOT FOUND OR v_spawn_install.state IS DISTINCT FROM 'installed' THEN
            RETURN jsonb_build_object('write',false,
              'error',v24.error_v1('provider_unavailable'));
          END IF;
          v_spawn_owner_epoch := v_spawn_episode.epoch;
          SELECT count(*) INTO v_spawn_act_count FROM v24.pins p
           WHERE p.consumer_type = 'activation'
             AND p.consumer_episode_id = v_spawn_owner_episode
             AND p.consumer_epoch = v_spawn_owner_epoch
             AND p.released_at IS NULL;
          IF v_spawn_act_count <> 1 THEN
            RETURN jsonb_build_object('write',false,
              'error',v24.error_v1('dependency_unresolved'));
          END IF;
          SELECT * INTO v_spawn_activation FROM v24.pins p
           WHERE p.consumer_type = 'activation'
             AND p.consumer_episode_id = v_spawn_owner_episode
             AND p.consumer_epoch = v_spawn_owner_epoch
             AND p.released_at IS NULL;
          v_spawn_pin_id := gen_random_uuid();
          v_spawn_pin := jsonb_build_object(
            'pin_id',v_spawn_pin_id,'consumer_type','run',
            'consumer_run_id',md5(r.run_id::text||':spawn:'||v_spawn_key)::uuid,
            'consumer_epoch',v_spawn_owner_epoch,'key','run',
            'slot_id',v_spawn_activation.slot_id,
            'provider_fiber_id',v_spawn_activation.provider_fiber_id,
            'provider_episode_id',v_spawn_activation.provider_episode_id,
            'descriptor_digest',v_spawn_activation.descriptor_digest,
            'created_by_effect',p_effect_id);
          v_spawn_pins := jsonb_build_array(v_spawn_pin);
        ELSE
          v_spawn_pin_id := NULL;
        END IF;
        -- D-S8-9: the first model reserves against the grant, and the child run
        -- starts with grant minus that reservation (0 when the grant is fully
        -- reserved; NULL stays NULL).  A successful settlement then refunds only
        -- reserve - usage, yielding grant - usage.
        v_child_reserve := coalesce(v24.model_reserve(v_child_tokens),0);
        v_child_id := md5(r.run_id::text||':spawn:'||v_spawn_key)::uuid;
        v_child_effect_id := md5(v_child_id::text||':model_call:0')::uuid;
        -- §4.5/D-S8-11: the child request digests must equal what settlement
        -- recomputes from the prospective pin.  model_digests(child) cannot see
        -- an uninserted pin, so the toolset digest is built from the pending pin
        -- rows with the same key/hex ordering (start does the same in S3).
        v_child_digests := jsonb_build_object(
          'policy',(v24.model_digests(NULL))->>'policy',
          'schema',(v24.model_digests(NULL))->>'schema',
          'toolset',encode(sha256(convert_to((
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                     'key',pn->>'key',
                     'descriptor_digest',
                     encode((pn->>'descriptor_digest')::bytea,'hex'))
                   ORDER BY pn->>'key'),'[]'::jsonb)::text
              FROM jsonb_array_elements(v_spawn_pins) pn),'UTF8')),'hex'));
        v_child_request := jsonb_build_object(
          'v',1,'cause','spawn','run_id',v_child_id,'epoch_no',0,'generation',0,
          'input',v_spawn->'input',
          'reserve',jsonb_build_object('tokens',v_child_reserve),
          'digests',v_child_digests,
          'spawn_key',v_spawn_key,'parent_run_id',r.run_id);
        v_child_run := jsonb_build_object(
          'run_id',v_child_id,'scope_id',r.scope_id,'parent_run_id',r.run_id,
          'spawn_key',v_spawn_key,'spawn_request_digest',v_spawn_digest,
          'owner_fiber_id',v_spawn_owner_fiber,
          'owner_episode_id',v_spawn_owner_episode,'status','running',
          'epoch_no',0,'registration_generation',1,'turn_no',0,'driving_generation',0,
          'remaining_steps',v_child_steps,
          'remaining_tokens',CASE WHEN v_child_tokens IS NULL THEN NULL
                                  ELSE v_child_tokens - v_child_reserve END,
          'remaining_tool_calls',v_child_tool_calls,'remaining_wall_ms',v_child_wall,
          'revision',0,'created_at',now(),'updated_at',now());
        v_child_effect := jsonb_build_object(
          'effect_id',v_child_effect_id,'parent_effect_id',p_effect_id,'ordinal',0,
          'requester_id',p_principal,'scope_id',r.scope_id,'run_id',v_child_id,
          'fiber_id',v_spawn_owner_fiber,'episode_id',v_spawn_owner_episode,
          -- A model_call never binds effects.pin_id: only tool_call effects use
          -- a pin.  The owner run pin lives solely in v_spawn_pins/pins, so the
          -- child first model stays claimable through the ordinary public path.
          'pin_id',NULL,
          'epoch_no',0,'generation',0,'kind','model_call','status','ready',
          'request',v_child_request,
          'request_digest',sha256(convert_to(v24.canonical_json(v_child_request),'UTF8')),
          'replay_policy','no_replay');
        v_ins_runs := jsonb_build_array(v_child_run);
        v_ins_effects := jsonb_build_array(v_child_effect);
      END IF;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
        OR invalid_parameter_value OR datetime_field_overflow THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END;
  END IF;

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
    -- C21: an older generation normally contributes facts and cost only.  When
    -- this settlement is the last live old-generation business effect and a
    -- pending steer is waiting, the same delta consumes it into exactly one
    -- cause='steer' model and never publishes the old inherited successor.
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
    v_consume := v24.steer_consumable(e.run_id,p_effect_id,e.epoch_no,e.generation);
    IF v_consume THEN
      v_pending_epoch := (r.pending_steer->>'epoch')::bigint;
      v_pending_gen := greatest(r.driving_generation,
                                (r.pending_steer->>'generation')::bigint);
      v_pending_instruction := r.pending_steer->>'instruction';
      -- Latest wins: the pending value is cleared whether or not a model fits.
      v_pending := NULL;
      v_steer_admit := v_steps >= 1 AND v_wall > 0
                       AND (v_tokens IS NULL OR v_tokens > 0);
      IF v_steer_admit THEN
        v_steer_reserve := v24.model_reserve(v_tokens);
        v_steps := v_steps - 1;
        v_tokens := CASE WHEN v_tokens IS NULL THEN NULL
                         ELSE v_tokens - v_steer_reserve END;
        -- The settling model is the run's latest model input; a respond-shaped
        -- model has none, so inherit the most recent model input like C17's
        -- continuation rule.
        v_input := coalesce(e.request->'input',
          (SELECT x.request->'input' FROM v24.effects x
            WHERE x.run_id = e.run_id AND x.kind = 'model_call'
              AND x.effect_id <> p_effect_id AND x.request ? 'input'
            ORDER BY x.created_at DESC, x.effect_id DESC LIMIT 1),
          '{}'::jsonb);
        v_steer_id := v24.steer_model_effect_id(e.run_id,v_pending_epoch,
                                                v_pending_gen,v_pending_instruction);
        v_succ := jsonb_build_array(jsonb_build_object(
          'effect_id',v_steer_id,'parent_effect_id',p_effect_id,
          'ordinal',0,'kind','model_call',
          'run_id',r.run_id,'fiber_id',r.owner_fiber_id,'episode_id',r.owner_episode_id,
          'epoch_no',v_pending_epoch,'generation',v_pending_gen,'pin_id',NULL,
          'replay_policy','no_replay',
          'request',jsonb_build_object(
            'v',1,'cause','steer','run_id',r.run_id,'epoch_no',v_pending_epoch,
            'generation',v_pending_gen,'input',v_input,
            'reserve',jsonb_build_object('tokens',v_steer_reserve),
            'digests',v_digests,'instruction',v_pending_instruction)));
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','run','entity_id',e.run_id,
          'event_kind','pending_steer_consumed','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,'model_effect_id',v_steer_id,
            'epoch',v_pending_epoch,'generation',v_pending_gen)));
      ELSE
        -- C23 addendum B: never admit a reserve-0 steer.  Seal when the run is
        -- sealable; otherwise record the clear and publish nothing.
        v_steer_sealed := v24.loop_sealable(e.run_id,p_effect_id,
          jsonb_build_object('kind','budget'),NULL,NULL);
        IF v_steer_sealed THEN
          SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
           WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
           ORDER BY e2.created_at, e2.effect_id LIMIT 1;
          IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
            v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
              'tool_calls',v_tool_calls,'wall_ms',v_wall);
          END IF;
          v_status := 'completed';
          v_close := jsonb_build_object('kind','budget');
          v_result := jsonb_build_object('v',1,'close_reason','budget_exhausted',
            'final_text',NULL,'turn_no',v_turn,'budget',v_budget);
          v_interaction := NULL; v_ended := now();
          v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
          v_events := v_events || jsonb_build_array(
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','budget_exhausted','payload',jsonb_build_object(
                'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)),
            jsonb_build_object('entity_type','run','entity_id',e.run_id,
              'event_kind','run_completed','payload',jsonb_build_object(
                'run_id',e.run_id,'close_reason','budget_exhausted','turn_no',v_turn)));
        END IF;
      END IF;
    END IF;
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
    ELSIF v_spawn IS NOT NULL THEN
      -- S8 W1: the reserved intent settles this model normally and keeps the
      -- parent live.  The spawn-specific quota deduction and the parent/child
      -- events are appended after the class branch, once v_tokens carries the
      -- ordinary C19 refund.
      v_status := 'running';
      v_close := NULL; v_result := NULL;
      v_interaction := NULL; v_pending := r.pending_steer; v_ended := NULL;
      v_events := jsonb_build_array(
        jsonb_build_object('entity_type','run','entity_id',e.run_id,
          'event_kind','model_call_settled','payload',jsonb_build_object(
            'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',false)));
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

  -- S8 W1: fold the spawn into the same parent update (one revision bump) and
  -- append the parent/child events.  Steps/tool_calls conserve exactly; wall
  -- conserves on the elapsed-adjusted v_wall (before - elapsed = after +
  -- child_wall); tokens deduct the full grant from the C19-refunded v_tokens.
  -- A NULL parent token balance stays NULL.
  IF v_spawn IS NOT NULL AND NOT v_spawn_replay THEN
    v_steps := v_steps - v_child_steps;
    v_tokens := CASE WHEN v_tokens IS NULL THEN NULL
                     ELSE v_tokens - v_child_tokens END;
    v_tool_calls := v_tool_calls - v_child_tool_calls;
    v_wall := greatest(0, v_wall - v_child_wall);
    v_events := v_events || jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind','run_spawned','payload',jsonb_build_object(
          'child_run_id',v_child_id,'spawn_key',v_spawn_key,
          'child_effect_id',v_child_effect_id,
          'spawn_request_digest',encode(v_spawn_digest,'hex'))),
      jsonb_build_object('entity_type','run','entity_id',v_child_id,
        'event_kind','run_started','payload',jsonb_build_object(
          'run_id',v_child_id,'parent_run_id',e.run_id,'spawn_key',v_spawn_key)));
  END IF;

  v_domain := jsonb_build_object('update',jsonb_build_object(
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
    'pins',v_pins));
  IF v_spawn IS NOT NULL AND NOT v_spawn_replay THEN
    -- The child first model must ride inserts.effects: a successor would be
    -- forced to keep the settling parent's run_id, but a child is a new run.
    -- The optional owner run pin is a separate inserts.pins row; the child
    -- first model carries effects.pin_id NULL and never references that pin.
    v_domain := v_domain || jsonb_build_object('insert',jsonb_build_object(
      'runs',v_ins_runs,'effects',v_ins_effects,'pins',v_spawn_pins));
  END IF;

  -- §4.7: the optional `spawned` handle is the only member outside the six-key
  -- envelope.  A same-key replay carries the existing child and replayed=true;
  -- the applier re-derives that flag from the stored child row rather than
  -- trusting the echo.
  RETURN jsonb_build_object(
    'write',true,
    'domain',v_domain,
    'effect',jsonb_build_object('status',v_effect_status,
      'outcome',p_outcome,'resource_quiesced',v_quiesced),
    'events',v_events,
    'successors',v_succ)
    || CASE WHEN v_spawn IS NOT NULL THEN jsonb_build_object('spawn',
         jsonb_build_object('run_id',v_child_id,'spawn_key',v_spawn_key,
           'child_effect_id',v_child_effect_id,'replayed',v_spawn_replay))
       ELSE '{}'::jsonb END;
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
  v_pending_epoch bigint;
  v_pending_gen bigint;
  v_pending_instruction text;
  v_steer_id uuid;
  v_steer_admit boolean := false;
  v_steer_sealed boolean := false;
  v_steer_reserve bigint;
  v_consume_events jsonb := '[]'::jsonb;
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
              OR e.generation IS DISTINCT FROM r.driving_generation
              OR e.epoch_no IS DISTINCT FROM r.epoch_no;
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
      ELSIF v24.steer_consumable(e.run_id,p_effect_id,e.epoch_no,e.generation) THEN
        -- C21: the closing old-generation settlement consumes the pending steer
        -- in place of the batch's inherited continuation.  Exactly one
        -- cause='steer' model is published and the pending value is cleared;
        -- latest wins, so only the last steer write is read.
        v_pending_epoch := (r.pending_steer->>'epoch')::bigint;
        v_pending_gen := greatest(r.driving_generation,
                                  (r.pending_steer->>'generation')::bigint);
        v_pending_instruction := r.pending_steer->>'instruction';
        v_pending := NULL;
        v_steer_admit := v_steps >= 1 AND v_wall > 0
                         AND (v_tokens IS NULL OR v_tokens > 0);
        IF v_steer_admit THEN
          v_steer_reserve := v24.model_reserve(v_tokens);
          v_steps := v_steps - 1;
          v_tokens := CASE WHEN v_tokens IS NULL THEN NULL
                           ELSE v_tokens - v_steer_reserve END;
          v_digests := v24.model_digests(e.run_id);
          -- start/steer/continuation carry input; a respond model does not, so
          -- take the most recent model input on the run (C21 reducer input).
          SELECT x.request->'input' INTO v_input FROM v24.effects x
           WHERE x.run_id = e.run_id AND x.kind = 'model_call'
             AND x.request ? 'input'
           ORDER BY x.created_at DESC, x.effect_id DESC LIMIT 1;
          v_input := coalesce(v_input,'{}'::jsonb);
          v_steer_id := v24.steer_model_effect_id(e.run_id,v_pending_epoch,
                                                  v_pending_gen,v_pending_instruction);
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id',v_steer_id,'parent_effect_id',p_effect_id,
            'ordinal',0,'kind','model_call',
            'run_id',r.run_id,'fiber_id',r.owner_fiber_id,'episode_id',r.owner_episode_id,
            'epoch_no',v_pending_epoch,'generation',v_pending_gen,'pin_id',NULL,
            'replay_policy','no_replay',
            'request',jsonb_build_object(
              'v',1,'cause','steer','run_id',r.run_id,'epoch_no',v_pending_epoch,
              'generation',v_pending_gen,'input',v_input,
              'reserve',jsonb_build_object('tokens',v_steer_reserve),
              'digests',v_digests,'instruction',v_pending_instruction)));
          v_consume_events := jsonb_build_array(jsonb_build_object(
            'entity_type','run','entity_id',e.run_id,
            'event_kind','pending_steer_consumed','payload',jsonb_build_object(
              'run_id',e.run_id,'effect_id',p_effect_id,'model_effect_id',v_steer_id,
              'epoch',v_pending_epoch,'generation',v_pending_gen)));
        ELSE
          -- C23 addendum B: never admit a reserve-0 steer; seal if possible.
          v_steer_sealed := v24.loop_sealable(e.run_id,p_effect_id,
            jsonb_build_object('kind','budget'),NULL,NULL);
          IF v_steer_sealed THEN
            SELECT e2.request->'budget' INTO v_budget FROM v24.effects e2
             WHERE e2.run_id = e.run_id AND e2.kind = 'model_call' AND e2.request ? 'budget'
             ORDER BY e2.created_at, e2.effect_id LIMIT 1;
            IF v_budget IS NULL OR jsonb_typeof(v_budget) IS DISTINCT FROM 'object' THEN
              v_budget := jsonb_build_object('steps',v_steps,'tokens',coalesce(v_tokens,0),
                'tool_calls',v_tool_calls,'wall_ms',v_wall);
            END IF;
            v_seal_kind := 'budget';
            v_status := 'completed';
            v_close := jsonb_build_object('kind','budget');
            v_run_result := jsonb_build_object('v',1,'close_reason','budget_exhausted',
              'final_text',NULL,'turn_no',v_turn,'budget',v_budget);
            v_interaction := NULL; v_ended := now();
            v_pins := v24.run_pin_release_set(e.run_id,p_effect_id,v_status,p_effect_id);
            v_consume_events := jsonb_build_array(
              jsonb_build_object('entity_type','run','entity_id',e.run_id,
                'event_kind','budget_exhausted','payload',jsonb_build_object(
                  'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn)),
              jsonb_build_object('entity_type','run','entity_id',e.run_id,
                'event_kind','run_completed','payload',jsonb_build_object(
                  'run_id',e.run_id,'close_reason','budget_exhausted','turn_no',v_turn)));
          END IF;
        END IF;
      END IF;
    END IF;

    v_events := jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',e.run_id,
        'event_kind',v_fact_event,'payload',jsonb_build_object(
          'run_id',e.run_id,'effect_id',p_effect_id,'turn_no',v_turn,'late',v_late)))
      || v_consume_events;
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
-- {write,domain,effect,events,successors,spawn} and every check finishes before
-- the first write.  DML order: run -> pin -> effect -> events -> successors ->
-- pin releases.  A spawned child's run pin is a separate pins row inserted
-- with the child run; the child first model leaves effects.pin_id NULL.
CREATE FUNCTION v24.validate_and_apply_loop_delta(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_delta jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  r v24.runs%ROWTYPE;
  upd jsonb;
  ins jsonb;
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
  -- S8 W1 spawn footprint state.  v_spawn is true iff domain.insert exists.
  v_spawn boolean := false;
  v_child v24.runs%ROWTYPE;
  v_child_effect v24.effects%ROWTYPE;
  v_child_id uuid;
  v_child_effect_id uuid;
  v_child_req jsonb;
  v_child_args jsonb;
  v_child_reserve bigint;
  v_child_grant bigint;
  v_post_tokens bigint;
  v_wall_before bigint;
  v_elapsed bigint;
  -- S8 W2 spawn state: a same-key replay carries `spawn` without an insert;
  -- the optional owner pin rides inserts.pins and is validated against the
  -- owner fiber/episode and its single live activation pin.
  v_spawn_replay boolean := false;
  v_spawn_echo jsonb;
  v_spawn_args jsonb;
  v_spawn_digest bytea;
  v_spawn_pin jsonb;
  v_pin v24.pins%ROWTYPE;
  v_owner_fiber v24.fibers%ROWTYPE;
  v_owner_episode v24.episodes%ROWTYPE;
  v_owner_install v24.installs%ROWTYPE;
  v_activation v24.pins%ROWTYPE;
  v_act_count int := 0;
  v_child_digests jsonb;
  v_spawned jsonb := '[]'::jsonb;
  v_response jsonb;
  v_succ_kind text;
  v_succ_parent uuid;
  v_succ_ord int;
  v_tool_n int := 0;
  v_model_n int := 0;
  v_model_src uuid;
  v_max_ord int;
  v_batch_calc text;
  v_succ_pin v24.pins%ROWTYPE;
  v_consumable boolean := false;
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
              WHERE k NOT IN ('write','domain','effect','events','successors',
                              'spawn')) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (p_delta ?& ARRAY['write','domain','effect','events','successors']) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_typeof(p_delta->'domain') IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF NOT (p_delta->'domain' ? 'update')
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta->'domain') k
                 WHERE k NOT IN ('update','insert')) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  upd := p_delta->'domain'->'update';
  IF jsonb_typeof(upd) IS DISTINCT FROM 'object' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  v_spawn := p_delta->'domain' ? 'insert';
  -- A spawn delta always carries the `spawn` handle echo (fresh replayed=false,
  -- same-key replay replayed=true).  Replay has no insert; the applier is the
  -- authority and re-derives the child from the run/outcome below.
  v_spawn_replay := (p_delta ? 'spawn') AND NOT v_spawn;
  ins := coalesce(p_delta->'domain'->'insert','{}'::jsonb);
  IF v_spawn THEN
    -- W2 spawn footprint: exactly one child run, exactly one child first model
    -- effect and at most one owner run pin; the handle echo is mandatory.  The
    -- ordinary no-spawn path still carries only domain.update and is
    -- byte-for-byte unchanged.
    IF jsonb_typeof(ins) IS DISTINCT FROM 'object'
       OR NOT (p_delta ? 'spawn')
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(ins) k
                   WHERE k NOT IN ('runs','effects','pins'))
       OR jsonb_typeof(coalesce(ins->'runs','[]'::jsonb)) IS DISTINCT FROM 'array'
       OR jsonb_array_length(coalesce(ins->'runs','[]'::jsonb)) <> 1
       OR jsonb_typeof(coalesce(ins->'effects','[]'::jsonb)) IS DISTINCT FROM 'array'
       OR jsonb_array_length(coalesce(ins->'effects','[]'::jsonb)) <> 1
       OR jsonb_typeof(coalesce(ins->'pins','[]'::jsonb)) IS DISTINCT FROM 'array'
       OR jsonb_array_length(coalesce(ins->'pins','[]'::jsonb)) > 1 THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
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
  -- C21: a steer successor may only appear when this settlement is the last
  -- old-generation business effect of a still-live run that carries the
  -- pending value.  Evaluated before any DML, exactly like the interpreter.
  v_consumable := v24.steer_consumable(e.run_id,p_effect_id,e.epoch_no,e.generation);

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
         AND NOT v_cancel_late
         -- C21: an inherited old-generation failure records its fact while the
         -- same delta consumes the pending steer; the run stays live.
         AND NOT (v_consumable AND set_r->'pending_steer' = 'null'::jsonb) THEN
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

  -- S8 W2 same-key replay.  A replay delta carries only the parent update and
  -- the `spawn` handle; no child/quota/effect/event writes are permitted.  The
  -- applier re-derives the existing child from the outcome args and requires
  -- the echo to match that row, so the interpreter flag is never trusted.
  IF v_spawn_replay THEN
    IF e.kind <> 'model_call'
       OR p_delta->'domain' ? 'insert'
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(p_delta->'events') = 'array'
                 THEN p_delta->'events' ELSE '[]'::jsonb END) x
            WHERE x->>'event_kind' IN ('run_spawned','run_started')) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    v_spawn_echo := p_delta->'spawn';
    IF jsonb_typeof(v_spawn_echo) IS DISTINCT FROM 'object'
       OR NOT (v_spawn_echo ?& ARRAY['run_id','spawn_key','child_effect_id',
                                     'replayed'])
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_spawn_echo) k
                   WHERE k NOT IN ('run_id','spawn_key','child_effect_id',
                                   'replayed'))
       OR v_spawn_echo->'replayed' IS DISTINCT FROM 'true'::jsonb
       OR jsonb_typeof(v_spawn_echo->'run_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_spawn_echo->'spawn_key') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_spawn_echo->'child_effect_id') IS DISTINCT FROM 'string' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    SELECT value->'args' INTO v_spawn_args
      FROM jsonb_array_elements(CASE
             WHEN jsonb_typeof(p_outcome->'body'->'result'->'tool_calls') = 'array'
             THEN p_outcome->'body'->'result'->'tool_calls'
             ELSE '[]'::jsonb END) value
     WHERE value->>'key' = 'agent.spawn';
    IF v_spawn_args IS NULL OR jsonb_typeof(v_spawn_args) IS DISTINCT FROM 'object' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    v_spawn_digest := sha256(convert_to(v24.canonical_json(v_spawn_args),'UTF8'));
    SELECT * INTO v_child FROM v24.runs cr
     WHERE cr.run_id = (v_spawn_echo->>'run_id')::uuid;
    IF NOT FOUND
       OR v_child.parent_run_id IS DISTINCT FROM e.run_id
       OR v_child.scope_id IS DISTINCT FROM r.scope_id
       OR v_child.spawn_key IS DISTINCT FROM v_spawn_echo->>'spawn_key'
       OR v_child.spawn_request_digest IS DISTINCT FROM v_spawn_digest
       OR v_child.run_id IS DISTINCT FROM
          md5(e.run_id::text||':spawn:'||v_child.spawn_key)::uuid
       OR (v_spawn_echo->>'child_effect_id')::uuid IS DISTINCT FROM
          md5(v_child.run_id::text||':model_call:0')::uuid
       OR NOT EXISTS (SELECT 1 FROM v24.effects ex
                       WHERE ex.effect_id = (v_spawn_echo->>'child_effect_id')::uuid
                         AND ex.run_id = v_child.run_id
                         AND ex.kind = 'model_call' AND ex.ordinal = 0) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    v_child_id := v_child.run_id;
    v_child_effect_id := (v_spawn_echo->>'child_effect_id')::uuid;
  END IF;
  -- A spawn outcome without the handle echo would silently settle as an
  -- ordinary model turn; that is not a legal delta.
  IF NOT (v_spawn OR v_spawn_replay)
     AND EXISTS (SELECT 1 FROM jsonb_array_elements(CASE
           WHEN jsonb_typeof(p_outcome->'body'->'result'->'tool_calls') = 'array'
           THEN p_outcome->'body'->'result'->'tool_calls'
           ELSE '[]'::jsonb END) x
           WHERE x->>'key' = 'agent.spawn') THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;

  -- S8 W1 spawn footprint.  Exactly one child run and one child first model
  -- effect, with deterministic identities, parent linkage, C17-compatible
  -- request and conserved quota.  Any deviation is W0 before the first write.
  IF v_spawn THEN
    BEGIN
      IF e.kind <> 'model_call' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF jsonb_typeof(ins->'runs'->0) IS DISTINCT FROM 'object'
         OR NOT (ins->'runs'->0 ?& ARRAY[
              'run_id','scope_id','parent_run_id','spawn_key','spawn_request_digest',
              'owner_fiber_id','owner_episode_id','status','epoch_no',
              'registration_generation','turn_no','driving_generation',
              'remaining_steps','remaining_tokens','remaining_tool_calls',
              'remaining_wall_ms','revision','created_at','updated_at'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(ins->'runs'->0) k
                     WHERE k <> ALL (ARRAY[
              'run_id','scope_id','parent_run_id','spawn_key','spawn_request_digest',
              'owner_fiber_id','owner_episode_id','status','epoch_no',
              'registration_generation','turn_no','driving_generation',
              'remaining_steps','remaining_tokens','remaining_tool_calls',
              'remaining_wall_ms','revision','created_at','updated_at'])) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      v_child := jsonb_populate_record(NULL::v24.runs, ins->'runs'->0);
      -- D-S8-9/D-S8-10: the parent balance this spawn is admitted against is
      -- the same post-refund / post-elapsed value the interpreter used.
      v_elapsed := coalesce((extract(epoch from (now()-e.created_at))*1000)::bigint,0);
      v_wall_before := greatest(0, r.remaining_wall_ms - v_elapsed);
      v_post_tokens := CASE WHEN r.remaining_tokens IS NULL THEN NULL
        ELSE greatest(0, r.remaining_tokens
          + (e.request->'reserve'->>'tokens')::bigint
          - coalesce((p_outcome->'body'->'result'->'usage'->>'tokens')::bigint,0))
        END;
      IF ins->'runs'->0 IS DISTINCT FROM jsonb_build_object(
            'run_id',v_child.run_id,'scope_id',v_child.scope_id,
            'parent_run_id',v_child.parent_run_id,'spawn_key',v_child.spawn_key,
            'spawn_request_digest',v_child.spawn_request_digest,
            'owner_fiber_id',v_child.owner_fiber_id,
            'owner_episode_id',v_child.owner_episode_id,
            'status',v_child.status,'epoch_no',v_child.epoch_no,
            'registration_generation',v_child.registration_generation,
            'turn_no',v_child.turn_no,
            'driving_generation',v_child.driving_generation,
            'remaining_steps',v_child.remaining_steps,
            'remaining_tokens',v_child.remaining_tokens,
            'remaining_tool_calls',v_child.remaining_tool_calls,
            'remaining_wall_ms',v_child.remaining_wall_ms,
            'revision',v_child.revision,'created_at',v_child.created_at,
            'updated_at',v_child.updated_at)
         OR v_child.run_id IS NULL
         OR v_child.scope_id IS DISTINCT FROM r.scope_id
         OR v_child.parent_run_id IS DISTINCT FROM r.run_id
         OR v_child.spawn_key IS NULL
         OR v_child.spawn_key !~ '^[A-Za-z0-9._:-]{1,128}$'
         OR v_child.spawn_request_digest IS NULL
         OR (v_child.owner_fiber_id IS NULL) <> (v_child.owner_episode_id IS NULL)
         OR v_child.status IS DISTINCT FROM 'running'
         OR v_child.epoch_no IS DISTINCT FROM 0
         OR v_child.registration_generation IS DISTINCT FROM 1
         OR v_child.turn_no IS DISTINCT FROM 0
         OR v_child.driving_generation IS DISTINCT FROM 0
         OR v_child.revision IS DISTINCT FROM 0
         OR v_child.created_at IS DISTINCT FROM now()
         OR v_child.updated_at IS DISTINCT FROM now()
         OR v_child.remaining_steps IS NULL OR v_child.remaining_steps < 1
         OR v_child.remaining_tool_calls IS NULL OR v_child.remaining_tool_calls < 1
         OR v_child.remaining_wall_ms IS NULL OR v_child.remaining_wall_ms < 1
         OR (v_child.remaining_tokens IS NOT NULL AND v_child.remaining_tokens < 0)
         OR v_child.run_id IS DISTINCT FROM
            md5(r.run_id::text||':spawn:'||v_child.spawn_key)::uuid
         OR v_child.remaining_steps > r.remaining_steps
         OR v_child.remaining_tool_calls > r.remaining_tool_calls
         OR v_child.remaining_wall_ms > v_wall_before
         OR EXISTS (SELECT 1 FROM v24.runs cr
                     WHERE cr.run_id = v_child.run_id
                        OR (cr.parent_run_id = r.run_id
                            AND cr.spawn_key = v_child.spawn_key))
         OR (set_r->>'remaining_steps')::int IS DISTINCT FROM
            r.remaining_steps - v_child.remaining_steps
         OR (set_r->>'remaining_tool_calls')::int IS DISTINCT FROM
            r.remaining_tool_calls - v_child.remaining_tool_calls
         OR (set_r->>'remaining_wall_ms')::bigint IS DISTINCT FROM
            greatest(0, v_wall_before - v_child.remaining_wall_ms)
         OR v_status IS DISTINCT FROM 'running' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;

      -- §4.6 owner pair: the applier re-verifies the live fiber/episode and
      -- requires exactly one live activation pin to lend the child run pin its
      -- provider tuple.  A pair without a pin (or an ownerless run with a pin)
      -- is structurally invalid.
      IF v_child.owner_fiber_id IS NOT NULL THEN
        SELECT * INTO v_owner_fiber FROM v24.fibers f
         WHERE f.fiber_id = v_child.owner_fiber_id;
        SELECT * INTO v_owner_episode FROM v24.episodes ep
         WHERE ep.episode_id = v_child.owner_episode_id;
        SELECT * INTO v_owner_install FROM v24.installs it
         WHERE it.install_id = v_owner_fiber.install_id;
        SELECT count(*) INTO v_act_count FROM v24.pins p
         WHERE p.consumer_type = 'activation'
           AND p.consumer_episode_id = v_child.owner_episode_id
           AND p.consumer_epoch = v_owner_episode.epoch
           AND p.released_at IS NULL;
        IF v_owner_fiber.fiber_id IS NULL
           OR v_owner_fiber.scope_id IS DISTINCT FROM r.scope_id
           OR v_owner_fiber.disposed_at IS NOT NULL
           OR NOT v_owner_fiber.want_on
           OR v_owner_fiber.current_episode_id IS DISTINCT FROM v_child.owner_episode_id
           OR v_owner_episode.episode_id IS NULL
           OR v_owner_episode.fiber_id IS DISTINCT FROM v_child.owner_fiber_id
           OR v_owner_episode.state IS DISTINCT FROM 'active'
           OR v_owner_install.install_id IS NULL
           OR v_owner_install.state IS DISTINCT FROM 'installed'
           OR v_act_count <> 1
           OR jsonb_array_length(coalesce(ins->'pins','[]'::jsonb)) <> 1 THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        SELECT * INTO v_activation FROM v24.pins p
         WHERE p.consumer_type = 'activation'
           AND p.consumer_episode_id = v_child.owner_episode_id
           AND p.consumer_epoch = v_owner_episode.epoch
           AND p.released_at IS NULL;
      ELSIF jsonb_array_length(coalesce(ins->'pins','[]'::jsonb)) <> 0 THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;

      IF jsonb_typeof(ins->'effects'->0) IS DISTINCT FROM 'object'
         OR NOT (ins->'effects'->0 ?& ARRAY[
              'effect_id','parent_effect_id','ordinal','requester_id','scope_id',
              'run_id','fiber_id','episode_id','pin_id','epoch_no','generation',
              'kind','status','request','request_digest','replay_policy'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(ins->'effects'->0) k
                     WHERE k <> ALL (ARRAY[
              'effect_id','parent_effect_id','ordinal','requester_id','scope_id',
              'run_id','fiber_id','episode_id','pin_id','epoch_no','generation',
              'kind','status','request','request_digest','replay_policy'])) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      v_child_effect := jsonb_populate_record(NULL::v24.effects,
                                              ins->'effects'->0);
      v_child_req := v_child_effect.request;
      IF jsonb_typeof(v_child_req) = 'object'
         AND jsonb_typeof(v_child_req->'reserve') = 'object'
         AND jsonb_typeof(v_child_req->'reserve'->'tokens') = 'number'
         AND (v_child_req->'reserve'->>'tokens') ~ '^[0-9]+$' THEN
        v_child_reserve := (v_child_req->'reserve'->>'tokens')::bigint;
      ELSE
        v_child_reserve := NULL;
      END IF;
      IF v_child.remaining_tokens IS NULL OR v_child_reserve IS NULL THEN
        v_child_grant := NULL;
      ELSE
        v_child_grant := v_child.remaining_tokens + v_child_reserve;
      END IF;
      -- The optional run pin must be exactly the §4.6 row: consumer run, the
      -- owner episode epoch, key='run', provider tuple/digest from the single
      -- live activation pin, created_by the settling parent effect.
      IF jsonb_array_length(coalesce(ins->'pins','[]'::jsonb)) = 1 THEN
        IF jsonb_typeof(ins->'pins'->0) IS DISTINCT FROM 'object'
           OR NOT (ins->'pins'->0 ?& ARRAY[
                'pin_id','consumer_type','consumer_run_id','consumer_epoch',
                'key','slot_id','provider_fiber_id','provider_episode_id',
                'descriptor_digest','created_by_effect'])
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(ins->'pins'->0) k
                       WHERE k NOT IN (
                'pin_id','consumer_type','consumer_run_id','consumer_epoch',
                'key','slot_id','provider_fiber_id','provider_episode_id',
                'descriptor_digest','created_by_effect')) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        v_pin := jsonb_populate_record(NULL::v24.pins, ins->'pins'->0);
        IF v_pin.pin_id IS NULL
           OR v_pin.consumer_type IS DISTINCT FROM 'run'
           OR v_pin.consumer_episode_id IS NOT NULL
           OR v_pin.consumer_run_id IS DISTINCT FROM v_child.run_id
           OR v_pin.consumer_epoch IS DISTINCT FROM v_owner_episode.epoch
           OR v_pin.key IS DISTINCT FROM 'run'
           OR v_pin.released_at IS NOT NULL
           OR v_pin.released_by_effect IS NOT NULL
           OR ins->'pins'->0 IS DISTINCT FROM jsonb_build_object(
                'pin_id',v_pin.pin_id,'consumer_type','run',
                'consumer_run_id',v_child.run_id,
                'consumer_epoch',v_owner_episode.epoch,'key','run',
                'slot_id',v_activation.slot_id,
                'provider_fiber_id',v_activation.provider_fiber_id,
                'provider_episode_id',v_activation.provider_episode_id,
                'descriptor_digest',v_activation.descriptor_digest,
                'created_by_effect',p_effect_id) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      END IF;
      -- D-S8-11: the request toolset digest must equal what settlement
      -- recomputes from these pins; model_digests cannot see uninserted rows.
      v_child_digests := jsonb_build_object(
        'policy',(v24.model_digests(NULL))->>'policy',
        'schema',(v24.model_digests(NULL))->>'schema',
        'toolset',encode(sha256(convert_to((
          SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'key',pn->>'key',
                   'descriptor_digest',
                   encode((pn->>'descriptor_digest')::bytea,'hex'))
                 ORDER BY pn->>'key'),'[]'::jsonb)::text
            FROM jsonb_array_elements(coalesce(ins->'pins','[]'::jsonb)) pn),
          'UTF8')),'hex'));
      IF jsonb_typeof(v_child_req) IS DISTINCT FROM 'object'
         OR NOT (v_child_req ?& ARRAY[
              'v','cause','run_id','epoch_no','generation','input','reserve',
              'digests','spawn_key','parent_run_id'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_child_req) k
                     WHERE k <> ALL (ARRAY[
              'v','cause','run_id','epoch_no','generation','input','reserve',
              'digests','spawn_key','parent_run_id']))
         OR ins->'effects'->0 IS DISTINCT FROM jsonb_build_object(
            'effect_id',v_child_effect.effect_id,
            'parent_effect_id',v_child_effect.parent_effect_id,
            'ordinal',v_child_effect.ordinal,
            'requester_id',v_child_effect.requester_id,
            'scope_id',v_child_effect.scope_id,
            'run_id',v_child_effect.run_id,
            'fiber_id',v_child_effect.fiber_id,
            'episode_id',v_child_effect.episode_id,
            'pin_id',v_child_effect.pin_id,
            'epoch_no',v_child_effect.epoch_no,
            'generation',v_child_effect.generation,
            'kind',v_child_effect.kind,'status',v_child_effect.status,
            'request',v_child_req,
            'request_digest',v_child_effect.request_digest,
            'replay_policy',v_child_effect.replay_policy)
         OR v_child_effect.effect_id IS NULL
         OR v_child_effect.effect_id IS DISTINCT FROM
            md5(v_child.run_id::text||':model_call:0')::uuid
         OR v_child_effect.parent_effect_id IS DISTINCT FROM p_effect_id
         OR v_child_effect.ordinal IS DISTINCT FROM 0
         OR v_child_effect.requester_id IS DISTINCT FROM p_principal
         OR v_child_effect.scope_id IS DISTINCT FROM v_child.scope_id
         OR v_child_effect.run_id IS DISTINCT FROM v_child.run_id
         OR v_child_effect.fiber_id IS DISTINCT FROM v_child.owner_fiber_id
         OR v_child_effect.episode_id IS DISTINCT FROM v_child.owner_episode_id
         OR v_child_effect.pin_id IS NOT NULL
         OR v_child_effect.epoch_no IS DISTINCT FROM 0
         OR v_child_effect.generation IS DISTINCT FROM 0
         OR v_child_effect.kind IS DISTINCT FROM 'model_call'
         OR v_child_effect.status IS DISTINCT FROM 'ready'
         OR v_child_effect.replay_policy IS DISTINCT FROM 'no_replay'
         OR v_child_effect.request_digest IS DISTINCT FROM
            sha256(convert_to(v24.canonical_json(v_child_req),'UTF8'))
         OR v_child_req->>'v' IS DISTINCT FROM '1'
         OR v_child_req->>'cause' IS DISTINCT FROM 'spawn'
         OR v_child_req->>'run_id' IS DISTINCT FROM v_child.run_id::text
         OR v_child_req->>'epoch_no' IS DISTINCT FROM '0'
         OR v_child_req->>'generation' IS DISTINCT FROM '0'
         OR jsonb_typeof(v_child_req->'input') IS DISTINCT FROM 'object'
         OR jsonb_typeof(v_child_req->'reserve') IS DISTINCT FROM 'object'
         OR (SELECT count(*) FROM jsonb_object_keys(v_child_req->'reserve')) <> 1
         OR NOT (v_child_req->'reserve' ? 'tokens')
         OR jsonb_typeof(v_child_req->'reserve'->'tokens') IS DISTINCT FROM 'number'
         OR (v_child_req->'reserve'->>'tokens') !~ '^[0-9]+$'
         OR v_child_reserve IS NULL
         OR (v_child.remaining_tokens IS NULL AND v_child_reserve <> 0)
         OR (v_child.remaining_tokens IS NOT NULL AND (
              v_child_grant < 1
              OR v_child_reserve IS DISTINCT FROM v24.model_reserve(v_child_grant)))
         OR (v_post_tokens IS NULL AND set_r->'remaining_tokens' <> 'null'::jsonb)
         OR (v_post_tokens IS NOT NULL AND (
              v_child_grant IS NULL OR v_child_grant > v_post_tokens
              OR set_r->'remaining_tokens' = 'null'::jsonb
              OR (set_r->>'remaining_tokens')::bigint IS DISTINCT FROM
                 v_post_tokens - v_child_grant))
         OR v_child_req->'digests' IS DISTINCT FROM v_child_digests
         OR v_child_req->>'spawn_key' IS DISTINCT FROM v_child.spawn_key
         OR v_child_req->>'parent_run_id' IS DISTINCT FROM r.run_id::text
         OR EXISTS (SELECT 1 FROM v24.effects ex
                     WHERE ex.effect_id = v_child_effect.effect_id
                        OR (ex.parent_effect_id = p_effect_id
                            AND ex.ordinal = v_child_effect.ordinal)) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      -- The spawn digest covers exactly the args canonical bytes.  Rebuild the
      -- args from the child row + request input and require the stored digest.
      v_child_args := jsonb_build_object(
        'v',1,'spawn_key',v_child.spawn_key,'input',v_child_req->'input',
        'scope_id',v_child.scope_id,
        'budget',jsonb_build_object(
          'steps',v_child.remaining_steps,
          'tokens',v_child_grant,
          'tool_calls',v_child.remaining_tool_calls,
          'wall_ms',v_child.remaining_wall_ms));
      -- The spawn digest covers the optional owner pair as well; omitting it
      -- would make every owned child fail the reconstructed-args check.
      IF v_child.owner_fiber_id IS NOT NULL THEN
        v_child_args := v_child_args || jsonb_build_object(
          'owner_fiber_id',v_child.owner_fiber_id,
          'owner_episode_id',v_child.owner_episode_id);
      END IF;
      IF v_child.spawn_request_digest IS DISTINCT FROM
         sha256(convert_to(v24.canonical_json(v_child_args),'UTF8')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      v_child_id := v_child.run_id;
      v_child_effect_id := v_child_effect.effect_id;
      -- The fresh handle echo must describe exactly the validated rows; a
      -- replay flag here is a lie (a replay never carries an insert).
      IF jsonb_typeof(p_delta->'spawn') IS DISTINCT FROM 'object'
         OR NOT (p_delta->'spawn' ?& ARRAY[
              'run_id','spawn_key','child_effect_id','replayed'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta->'spawn') k
                     WHERE k NOT IN ('run_id','spawn_key','child_effect_id',
                                     'replayed'))
         OR p_delta->'spawn'->'replayed' IS DISTINCT FROM 'false'::jsonb
         OR p_delta->'spawn'->>'run_id' IS DISTINCT FROM v_child_id::text
         OR p_delta->'spawn'->>'spawn_key' IS DISTINCT FROM v_child.spawn_key
         OR p_delta->'spawn'->>'child_effect_id' IS DISTINCT FROM
            v_child_effect_id::text THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
        OR invalid_parameter_value OR datetime_field_overflow THEN
      RETURN v24.error_v1('invalid_outcome');
    END;
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
         OR ev->>'event_kind' IS NULL
         OR jsonb_typeof(ev->'payload') IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF v_spawn THEN
        -- Only the settled parent and the newly inserted child may own events;
        -- run_spawned/run_started join the closed set only on this path.
        IF (ev->>'entity_id')::uuid NOT IN (e.run_id,v_child_id)
           OR ev->>'event_kind' <> ALL (
                v_event_kinds || ARRAY['run_spawned','run_started']) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      ELSE
        IF (ev->>'entity_id')::uuid IS DISTINCT FROM e.run_id
           OR ev->>'event_kind' <> ALL (v_event_kinds) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      END IF;
    END LOOP;
    IF v_spawn THEN
      -- Exactly the two spawn events plus the ordinary settlement event, with
      -- frozen payloads; arbitrary cross-run events remain rejected.
      IF jsonb_array_length(v_events) <> 3
         OR NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_events) x
               WHERE x->>'event_kind' = 'run_spawned'
                 AND (x->>'entity_id')::uuid = e.run_id
                 AND x->'payload' IS NOT DISTINCT FROM jsonb_build_object(
                       'child_run_id',v_child_id,
                       'spawn_key',v_child.spawn_key,
                       'child_effect_id',v_child_effect_id,
                       'spawn_request_digest',
                       encode(v_child.spawn_request_digest,'hex')))
         OR NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_events) x
               WHERE x->>'event_kind' = 'run_started'
                 AND (x->>'entity_id')::uuid = v_child_id
                 AND x->'payload' IS NOT DISTINCT FROM jsonb_build_object(
                       'run_id',v_child_id,
                       'parent_run_id',e.run_id,
                       'spawn_key',v_child.spawn_key))
         OR NOT EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_events) x
               WHERE x->>'event_kind' = 'model_call_settled'
                 AND (x->>'entity_id')::uuid = e.run_id) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END IF;
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
  -- A spawn settlement publishes no successors: the child first model rides
  -- inserts.effects, never successors[].
  IF v_spawn AND jsonb_array_length(v_succs) > 0 THEN
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
        IF v_succ_req->>'cause' = 'steer' THEN
          -- C21: the only steer successor is the one this run's pending value
          -- entitles, with a deterministic identity in its own namespace.  The
          -- same delta must clear pending_steer and announce the consumption.
          IF v_succ_parent IS DISTINCT FROM p_effect_id
             OR NOT v_consumable
             OR jsonb_typeof(r.pending_steer) IS DISTINCT FROM 'object'
             OR set_r->'pending_steer' <> 'null'::jsonb THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          IF NOT (v_succ_req ?& ARRAY['v','cause','run_id','epoch_no','generation',
                                      'input','reserve','digests','instruction'])
             OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_succ_req) k
                         WHERE k NOT IN ('v','cause','run_id','epoch_no','generation',
                                         'input','reserve','digests','instruction')) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          IF v_succ_req->>'v' IS DISTINCT FROM '1'
             OR v_succ_req->>'run_id' IS DISTINCT FROM e.run_id::text
             OR jsonb_typeof(v_succ_req->'epoch_no') IS DISTINCT FROM 'number'
             OR jsonb_typeof(v_succ_req->'generation') IS DISTINCT FROM 'number'
             OR (v_succ_req->>'epoch_no')::bigint IS DISTINCT FROM
                (r.pending_steer->>'epoch')::bigint
             OR (v_succ_req->>'generation')::bigint IS DISTINCT FROM
                greatest(r.driving_generation,
                         (r.pending_steer->>'generation')::bigint)
             OR (succ->>'epoch_no')::bigint IS DISTINCT FROM
                (v_succ_req->>'epoch_no')::bigint
             OR (succ->>'generation')::bigint IS DISTINCT FROM
                (v_succ_req->>'generation')::bigint
             OR jsonb_typeof(v_succ_req->'input') IS DISTINCT FROM 'object'
             OR jsonb_typeof(v_succ_req->'instruction') IS DISTINCT FROM 'string'
             OR v_succ_req->>'instruction' IS DISTINCT FROM
                r.pending_steer->>'instruction'
             OR jsonb_typeof(v_succ_req->'reserve') IS DISTINCT FROM 'object'
             OR (SELECT count(*) FROM jsonb_object_keys(v_succ_req->'reserve')) <> 1
             OR NOT (v_succ_req->'reserve' ? 'tokens')
             OR jsonb_typeof(v_succ_req->'reserve'->'tokens') IS DISTINCT FROM 'number'
             OR (v_succ_req->'reserve'->>'tokens') IS NULL
             OR (v_succ_req->'reserve'->>'tokens') !~ '^[0-9]+$'
             OR (v_succ_req->'reserve'->>'tokens')::bigint >
                (v24.loop_policy()->>'reserve_tokens')::bigint
             OR jsonb_typeof(v_succ_req->'digests') IS DISTINCT FROM 'object'
             OR v_succ_req->'digests' IS DISTINCT FROM v24.model_digests(e.run_id) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          IF (succ->>'effect_id')::uuid IS DISTINCT FROM
             v24.steer_model_effect_id(e.run_id,
               (r.pending_steer->>'epoch')::bigint,
               greatest(r.driving_generation,
                        (r.pending_steer->>'generation')::bigint),
               r.pending_steer->>'instruction') THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_events) x
                          WHERE x->>'event_kind' = 'pending_steer_consumed') THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        ELSE
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

  -- Frozen DML order: child run -> child run pin -> child first model ->
  -- parent run -> parent effect -> events -> successors -> pin releases.  The
  -- spawned child inserts precede the parent update because effects.run_id is a
  -- non-deferred FK.
  IF v_spawn THEN
    INSERT INTO v24.runs SELECT * FROM jsonb_populate_record(
      NULL::v24.runs,ins->'runs'->0);
    -- Optional owner run pin after the child run (its consumer FK) and before
    -- the child effect; the child first model leaves effects.pin_id NULL, so
    -- the run pin is an independent pins row.
    IF jsonb_array_length(coalesce(ins->'pins','[]'::jsonb)) = 1 THEN
      INSERT INTO v24.pins(pin_id,consumer_type,consumer_episode_id,
        consumer_run_id,consumer_epoch,key,slot_id,provider_fiber_id,
        provider_episode_id,descriptor_digest,created_by_effect)
      SELECT p.pin_id,p.consumer_type,p.consumer_episode_id,p.consumer_run_id,
        p.consumer_epoch,p.key,p.slot_id,p.provider_fiber_id,
        p.provider_episode_id,p.descriptor_digest,p.created_by_effect
      FROM jsonb_populate_record(NULL::v24.pins,ins->'pins'->0) AS p;
    END IF;
    INSERT INTO v24.effects(effect_id,parent_effect_id,ordinal,requester_id,scope_id,
      run_id,fiber_id,episode_id,pin_id,epoch_no,generation,kind,status,request,
      request_digest,replay_policy)
    SELECT effect_id,parent_effect_id,ordinal,requester_id,scope_id,run_id,
      fiber_id,episode_id,pin_id,epoch_no,generation,kind,status,request,
      request_digest,replay_policy
    FROM jsonb_populate_record(NULL::v24.effects,ins->'effects'->0);
  END IF;

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
    VALUES (p_effect_id,v_seq,'run',(ev->>'entity_id')::uuid,ev->>'event_kind',
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

  v_response := jsonb_build_object('v',1,'disposition','committed',
    'effect_id',p_effect_id,'emitted',v_emitted,'revision',v_revision,'claim',NULL);
  IF v_spawn OR v_spawn_replay THEN
    -- Optional member outside the frozen six-key envelope, only for a spawn
    -- settlement.  A same-key replay reuses the stored child handle.
    v_spawned := jsonb_build_array(jsonb_build_object(
      'run_id',v_child_id,'spawn_key',v_child.spawn_key,
      'child_effect_id',v_child_effect_id,'replayed',v_spawn_replay));
    v_response := v_response || jsonb_build_object('spawned',v_spawned);
  END IF;
  RETURN v_response;
END;
$$;
