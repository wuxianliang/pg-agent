-- W4: pure command interpretation and INVOKER delta application.
CREATE OR REPLACE FUNCTION v24.interpret_command(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  p jsonb := p_outcome->'body'->'payload';
  action text := p->>'action';
  parent v24.scopes%ROWTYPE;
  sid uuid := gen_random_uuid();
  rid uuid;
  path uuid[];
  root uuid;
  response jsonb;
  row jsonb;
  update_row jsonb;
BEGIN
  IF p_outcome->'body'->>'kind' = 'command_install' THEN
    RETURN v24.interpret_install(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' = 'command_start' THEN
    RETURN v24.interpret_start(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' = 'command_cancel' THEN
    RETURN v24.interpret_cancel(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' = 'command_steer' THEN
    RETURN v24.interpret_steer(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' = 'command_respond' THEN
    RETURN v24.interpret_respond(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' = 'command_fiber_control' THEN
    RETURN v24.interpret_fiber_control(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' = 'command_dispose' THEN
    RETURN v24.interpret_dispose(p_effect_id, p_principal, p_outcome, p_closure);
  END IF;
  IF p_outcome->'body'->>'kind' <> 'command_scope_control' THEN
    RAISE EXCEPTION 'v24.interpret_command: no command handler registered (W5)'
      USING ERRCODE = '0A000';
  END IF;
  IF action NOT IN ('create_root','create_child','close') THEN
    RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
  END IF;
  IF action = 'create_root' THEN
    IF NOT pg_has_role(session_user, 'v24_admin', 'USAGE') THEN
      RETURN jsonb_build_object('write', false, 'error', v24.error_v1('unauthorized'));
    END IF;
    IF p ? 'parent_scope_id' OR p ? 'scope_id' THEN
      RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
    END IF;
    root := sid;
    path := ARRAY[sid];
    row := jsonb_build_object('scope_id',sid,'parent_id',NULL,'root_id',root,
      'route_path',to_jsonb(path),'realm_routes',coalesce(p->'realm_routes','{}'::jsonb),
      'default_realm',p->'default_realm','owner_principal',p_principal,
      'created_by_effect',p_effect_id);
  ELSE
    IF NOT (p ? 'parent_scope_id') OR (p->>'parent_scope_id') IS NULL THEN
      RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
    END IF;
    BEGIN rid := (p->>'parent_scope_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN
      RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
    END;
    SELECT * INTO parent FROM v24.scopes WHERE scope_id=rid;
    IF NOT FOUND OR (parent.owner_principal <> p_principal
                     AND NOT pg_has_role(session_user,'v24_admin','USAGE')) THEN
      RETURN jsonb_build_object('write', true, 'error', v24.error_v1('unauthorized'));
    END IF;
    IF action = 'create_child' THEN
      IF parent.close_requested_at IS NOT NULL THEN
        RETURN jsonb_build_object('write', true, 'error', v24.error_v1('scope_closed'));
      END IF;
      root := parent.root_id; path := parent.route_path || sid;
      row := jsonb_build_object('scope_id',sid,'parent_id',parent.scope_id,'root_id',root,
        'route_path',to_jsonb(path),'realm_routes',coalesce(p->'realm_routes','{}'::jsonb),
        'default_realm',p->'default_realm','owner_principal',p_principal,
        'created_by_effect',p_effect_id);
    ELSE
      IF p ? 'realm_routes' OR p ? 'default_realm' THEN
        RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
      END IF;
      IF parent.close_requested_at IS NOT NULL THEN
        response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
          'emitted','[]'::jsonb,'revision',0,'claim',NULL);
        RETURN jsonb_build_object('write', true, 'error', NULL,
          'domain',jsonb_build_object('update',jsonb_build_object('scopes',jsonb_build_array(
            jsonb_build_object('key',jsonb_build_object('scope_id',rid), 'set',jsonb_build_object())))),
          'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),
          'request',jsonb_build_object('response',response),'events','[]'::jsonb,'successors','[]'::jsonb);
      END IF;
      update_row := jsonb_build_object('key',jsonb_build_object('scope_id',rid),
        'set',jsonb_build_object('close_requested_at',to_jsonb(now())));
      response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
        'emitted','[]'::jsonb,'revision',0,'claim',NULL);
      RETURN jsonb_build_object('write',true,'domain',jsonb_build_object('update',jsonb_build_object('scopes',jsonb_build_array(update_row))),
        'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),
        'request',jsonb_build_object('response',response),'events',jsonb_build_array(
          jsonb_build_object('entity_type','scope','entity_id',rid,'event_kind','scope_close_requested',
            'payload',jsonb_build_object('scope_id',rid),'payload_digest',sha256(convert_to((jsonb_build_object('scope_id',rid))::text,'UTF8')))),
        'successors','[]'::jsonb);
    END IF;
  END IF;
  response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',jsonb_build_array(sid),'revision',0,'claim',NULL);
  RETURN jsonb_build_object('write',true,'domain',jsonb_build_object('insert',jsonb_build_object('scopes',jsonb_build_array(row)),'update','{}'::jsonb),
    'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),
    'request',jsonb_build_object('response',response),
    'events',jsonb_build_array(jsonb_build_object('entity_type','scope','entity_id',sid,
      'event_kind','scope_created','payload',row,'payload_digest',sha256(convert_to(row::text,'UTF8')))),
    'successors','[]'::jsonb);
END;
$$;

CREATE OR REPLACE FUNCTION v24.validate_and_apply_delta(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_delta jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, v24 AS $$
DECLARE
  body jsonb := p_outcome->'body';
  kind text := body->>'kind';
  inserts jsonb := coalesce(p_delta->'domain'->'insert','{}'::jsonb);
  updates jsonb := coalesce(p_delta->'domain'->'update','{}'::jsonb);
  rows jsonb;
  r jsonb;
  response jsonb;
  status text;
  outcome jsonb;
  scope_id uuid;
  request_bytes bytea;
  request_digest bytea;
  seq bigint;
  emitted jsonb := '[]'::jsonb;
  ev jsonb;
  succ jsonb;
  new_id uuid;
  start_run v24.runs%ROWTYPE;
  start_pin v24.pins%ROWTYPE;
  start_model uuid;
  start_owner_episode uuid;
  start_payload jsonb := body->'payload';
  cancel_run v24.runs%ROWTYPE;
  cancel_effect v24.effects%ROWTYPE;
  cancel_pin v24.pins%ROWTYPE;
  cancel_expected jsonb;
  cancel_generation bigint;
  steer_run v24.runs%ROWTYPE;
  steer_effect v24.effects%ROWTYPE;
  steer_expected jsonb;
  steer_successors jsonb;
  steer_input jsonb;
  steer_claimed boolean;
  steer_generation bigint;
  steer_model uuid;
  respond_run v24.runs%ROWTYPE;
  respond_generation bigint;
  respond_interaction uuid;
  respond_origin uuid;
  respond_model uuid;
  v_start_digests jsonb;
  v_start_reserve bigint;
  v_steer_refund bigint;
  v_steer_balance bigint;
  v_steer_admit boolean;
  v_steer_sealed boolean;
  v_steer_digests jsonb;
  v_steer_reserve bigint;
  v_steer_set jsonb;
  v_steer_pins jsonb;
  v_steer_excluded uuid[];
  v_respond_admit boolean;
  v_respond_reserve bigint;
  v_respond_digests jsonb;
  v_respond_balance bigint;
  v_respond_sealed boolean;
  v_respond_set jsonb;
  v_respond_pins jsonb;
  v_cancel_refund bigint;
  v_dispose_scope uuid[];
  has_error boolean := p_delta->'error' IS NOT NULL AND p_delta->'error' <> 'null'::jsonb;
BEGIN
  -- W5 mode is inferred from the authenticated outcome class, never the delta.
  -- Leave the W4 scope-command path below unchanged.
  IF kind IN ('model_call','tool_call') THEN
    RETURN v24.validate_and_apply_loop_delta(p_effect_id, p_principal, p_outcome, p_delta, p_closure);
  END IF;
  IF p_outcome->>'class' IN ('success','failure','unknown') OR kind = 'command_install' THEN
    RETURN v24.validate_and_apply_install_delta(p_effect_id, p_principal, p_outcome, p_delta, p_closure);
  END IF;
  IF p_delta->>'write' = 'false' THEN
    RETURN p_delta->'error';
  END IF;
  IF jsonb_typeof(p_delta) IS DISTINCT FROM 'object'
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta) x WHERE x NOT IN ('domain','effect','request','events','successors','settle','error','write'))
     OR jsonb_typeof(inserts) IS DISTINCT FROM 'object'
     OR jsonb_typeof(updates) IS DISTINCT FROM 'object'
     OR jsonb_typeof(coalesce(p_delta->'events','[]'::jsonb)) IS DISTINCT FROM 'array'
     OR jsonb_typeof(coalesce(p_delta->'successors','[]'::jsonb)) IS DISTINCT FROM 'array' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF kind = 'command_scope_control' THEN
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(inserts) x WHERE x <> 'scopes')
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x WHERE x <> 'scopes') THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF kind = 'command_fiber_control' THEN
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(inserts) x
               WHERE x NOT IN ('episodes','slots','pins'))
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x
               WHERE x NOT IN ('episodes','fibers','slots','pins')) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF kind = 'command_dispose' THEN
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(inserts) x)
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x
                  WHERE x NOT IN ('installs','fibers')) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF kind = 'command_start' THEN
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(inserts) x WHERE x NOT IN ('runs','pins'))
       OR updates <> '{}'::jsonb OR p_delta ? 'settle' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF kind = 'command_cancel' THEN
    IF inserts <> '{}'::jsonb
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x
                  WHERE x NOT IN ('runs','effects','pins'))
       OR coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb
       OR p_delta ? 'settle' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF kind = 'command_steer' THEN
    IF inserts <> '{}'::jsonb
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x
                  WHERE x NOT IN ('runs','effects','pins'))
       OR jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) > 1
       OR p_delta ? 'settle' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSIF kind = 'command_respond' THEN
    IF inserts <> '{}'::jsonb
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(updates) x
                  WHERE x NOT IN ('runs','pins'))
       OR jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) > 1
       OR p_delta ? 'settle' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSE
    RAISE EXCEPTION 'v24.validate_and_apply_delta: no footprint for %', kind
      USING ERRCODE = '0A000';
  END IF;
  IF (SELECT coalesce(sum(jsonb_array_length(value)),0) FROM jsonb_each(inserts)) >
       (CASE WHEN kind='command_start' THEN 17 ELSE 16 END)
     OR (SELECT coalesce(sum(jsonb_array_length(value)),0) FROM jsonb_each(updates)) >
       (CASE WHEN kind IN ('command_cancel','command_steer') THEN 512 ELSE 16 END)
     OR jsonb_array_length(coalesce(p_delta->'events','[]'::jsonb)) > 64
     OR jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) > 16 THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(p_delta->'events','[]'::jsonb)) e
             GROUP BY e->>'entity_type', e->>'entity_id', e->>'event_kind' HAVING count(*) > 1)
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) e
             GROUP BY e->>'ordinal' HAVING count(*) > 1) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;

  -- D-S3-2 is narrowly scoped: existing command kinds cannot attach run IDs.
  IF kind NOT IN ('command_start','command_cancel','command_steer','command_respond') AND p_delta->'effect' ? 'run_id' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF kind = 'command_start' THEN
    IF has_error THEN
      IF inserts <> '{}'::jsonb OR coalesce(p_delta->'events','[]'::jsonb) <> '[]'::jsonb
         OR coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb
         OR p_delta ? 'effect' OR p_delta ? 'request'
         OR coalesce(p_delta->'error'->'error'->>'code','') NOT IN
              ('budget_exceeded','scope_closed','provider_unavailable','dependency_unresolved') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSE
      IF jsonb_array_length(coalesce(inserts->'runs','[]'::jsonb)) <> 1
         OR jsonb_array_length(coalesce(inserts->'pins','[]'::jsonb)) <>
            jsonb_array_length(coalesce(start_payload->'input'->'requires','[]'::jsonb))
         OR jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) <> 1
         OR jsonb_array_length(coalesce(p_delta->'events','[]'::jsonb)) <> 2 THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      BEGIN
        SELECT * INTO start_run FROM jsonb_populate_record(NULL::v24.runs,inserts->'runs'->0);
        SELECT f.current_episode_id INTO start_owner_episode FROM v24.fibers f
          WHERE f.fiber_id=(start_payload->>'owner_fiber_id')::uuid;
        start_model := md5(p_effect_id::text || ':model_call:0')::uuid;
        -- start's pins exist only inside this delta at interpretation time, so
        -- derive the toolset digest from the pending pin rows with the same
        -- key/hex ordering as v24.model_digests.
        SELECT coalesce(jsonb_agg(jsonb_build_object('key',pn->>'key',
                 'descriptor_digest',encode((pn->>'descriptor_digest')::bytea,'hex'))
                 ORDER BY pn->>'key'),'[]'::jsonb)
          INTO v_start_digests
          FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) pn;
        v_start_digests := jsonb_build_object(
          'policy',(v24.model_digests(NULL))->>'policy',
          'schema',(v24.model_digests(NULL))->>'schema',
          'toolset',encode(sha256(convert_to(v_start_digests::text,'UTF8')),'hex'));
        v_start_reserve := v24.model_reserve((start_payload->'budget'->>'tokens')::bigint);
        IF start_run.run_id IS NULL
           OR EXISTS (SELECT 1 FROM v24.runs rr WHERE rr.run_id=start_run.run_id)
           OR inserts->'runs'->0 IS DISTINCT FROM jsonb_build_object(
              'run_id',start_run.run_id,'scope_id',(start_payload->>'scope_id')::uuid,
              'owner_fiber_id',(start_payload->>'owner_fiber_id')::uuid,
              'owner_episode_id',start_owner_episode,'status','running',
              'epoch_no',1,'registration_generation',1,'turn_no',0,'driving_generation',1,
              'remaining_steps',(start_payload->'budget'->>'steps')::integer - 1,
              'remaining_tool_calls',(start_payload->'budget'->>'tool_calls')::integer,
              'remaining_tokens',(start_payload->'budget'->>'tokens')::bigint - v_start_reserve,
              'remaining_wall_ms',coalesce((start_payload->'budget'->>'wall_ms')::bigint,86400000),
              'revision',1,'created_at',now(),'updated_at',now())
           OR p_delta->'effect' IS DISTINCT FROM jsonb_build_object('run_id',start_run.run_id)
           OR p_delta->'request' IS DISTINCT FROM jsonb_build_object('response',
              jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
                'emitted',jsonb_build_array(start_run.run_id,start_model),'revision',1,'claim',NULL))
           OR p_delta->'successors' IS DISTINCT FROM jsonb_build_array(jsonb_build_object(
              'effect_id',start_model,'ordinal',0,'kind','model_call','run_id',start_run.run_id,
              'fiber_id',start_run.owner_fiber_id,'episode_id',start_run.owner_episode_id,
              'epoch_no',1,'generation',1,'replay_policy','no_replay',
              'request',jsonb_build_object('run_id',start_run.run_id,'epoch_no',1,'generation',1,
                'input',start_payload->'input','budget',start_payload->'budget',
                'v',1,'cause','start',
                'reserve',jsonb_build_object('tokens',v_start_reserve),
                'digests',v_start_digests)))
           OR p_delta->'events' IS DISTINCT FROM jsonb_build_array(
              jsonb_build_object('entity_type','run','entity_id',start_run.run_id,
                'event_kind','run_started','payload',jsonb_build_object('run_id',start_run.run_id)),
              jsonb_build_object('entity_type','run','entity_id',start_run.run_id,
                'event_kind','model_call_requested','payload',
                jsonb_build_object('run_id',start_run.run_id,'effect_id',start_model))) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) LOOP
          SELECT * INTO start_pin FROM jsonb_populate_record(NULL::v24.pins,r);
          IF start_pin.pin_id IS NULL OR NOT coalesce(p_closure->'slots' ? start_pin.slot_id::text,false)
             OR NOT EXISTS (SELECT 1 FROM v24.resolve(start_run.scope_id,ARRAY[start_pin.key]) rr
                  JOIN v24.slots sl ON sl.slot_id=rr.slot_id
                  WHERE rr.live AND rr.slot_id=start_pin.slot_id
                    AND sl.fiber_id=start_pin.provider_fiber_id
                    AND rr.provider_episode_id=start_pin.provider_episode_id
                    AND rr.descriptor_digest=start_pin.descriptor_digest)
             OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
                  coalesce(start_payload->'input'->'requires','[]'::jsonb)) req
                  WHERE req->>'key'=start_pin.key)
             OR r IS DISTINCT FROM jsonb_build_object('pin_id',start_pin.pin_id,'consumer_type','run',
                  'consumer_run_id',start_run.run_id,'consumer_epoch',1,'key',start_pin.key,
                  'slot_id',start_pin.slot_id,'provider_fiber_id',start_pin.provider_fiber_id,
                  'provider_episode_id',start_pin.provider_episode_id,
                  'descriptor_digest',start_pin.descriptor_digest,'created_by_effect',p_effect_id) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) pn
                   GROUP BY pn->>'key' HAVING count(*)>1) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value
          OR numeric_value_out_of_range OR datetime_field_overflow THEN
        RETURN v24.error_v1('invalid_outcome');
      END;
    END IF;
  END IF;

  IF kind = 'command_cancel' THEN
    IF has_error THEN
      IF updates <> '{}'::jsonb OR coalesce(p_delta->'events','[]'::jsonb) <> '[]'::jsonb
         OR p_delta ? 'effect' OR p_delta ? 'request'
         OR coalesce(p_delta->'error'->'error'->>'code','') NOT IN
              ('already_terminal','stale_generation') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSE
      BEGIN
        SELECT * INTO cancel_run FROM v24.runs rr
          WHERE rr.run_id=(body->'payload'->>'run_id')::uuid;
        cancel_generation := (body->'payload'->>'expected_generation')::bigint;
        SELECT coalesce(sum(coalesce((e.request->'reserve'->>'tokens')::bigint,0)),0)
          INTO v_cancel_refund FROM v24.effects e
         WHERE e.run_id=(body->'payload'->>'run_id')::uuid
           AND e.kind='model_call' AND e.status='ready';
        IF cancel_run.run_id IS NULL
           OR NOT coalesce(p_closure->'runs' ? cancel_run.run_id::text,false)
           OR cancel_run.status IN ('completed','failed','cancelled','blocked_unknown')
           OR cancel_generation IS DISTINCT FROM cancel_run.driving_generation
           OR (v24.run_owner(cancel_run.run_id) IS DISTINCT FROM p_principal
               AND NOT pg_has_role(session_user,'v24_admin','USAGE'))
           OR p_delta->'effect' IS DISTINCT FROM jsonb_build_object('run_id',cancel_run.run_id)
           OR p_delta->'request' IS DISTINCT FROM jsonb_build_object('response',
                jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
                  'emitted','[]'::jsonb,'revision',cancel_run.revision+1,'claim',NULL))
           OR p_delta->'events' IS DISTINCT FROM jsonb_build_array(jsonb_build_object(
                'entity_type','run','entity_id',cancel_run.run_id,'event_kind','run_cancelled',
                'payload',jsonb_build_object('run_id',cancel_run.run_id,
                                           'generation',cancel_generation)))
           OR coalesce(updates->'runs','[]'::jsonb) IS DISTINCT FROM
                jsonb_build_array(jsonb_build_object('key',jsonb_build_object('run_id',cancel_run.run_id),
                  'set',jsonb_build_object('status','cancelled','ended_at',now(),
                    'interaction',NULL,'pending_steer',NULL,
                    'close_intent',jsonb_build_object('kind','cancel','generation',cancel_generation,'at',now()),
                    'remaining_tokens',CASE WHEN cancel_run.remaining_tokens IS NULL THEN NULL
                                            ELSE cancel_run.remaining_tokens + v_cancel_refund END,
                    'driving_generation',cancel_run.driving_generation+1,
                    'revision',cancel_run.revision+1,'updated_at',now()))) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        -- Exact patches enforce column, target, and transition closures before DML.
        SELECT coalesce(jsonb_agg(jsonb_build_object('key',jsonb_build_object('effect_id',e.effect_id),
          'set',CASE WHEN e.status='ready'
             THEN jsonb_build_object('status','cancelled','settled_at',now(),'outcome',NULL)
             ELSE jsonb_build_object('cancel_requested',true) END) ORDER BY e.effect_id),'[]'::jsonb)
          INTO cancel_expected FROM v24.effects e
          WHERE e.run_id=cancel_run.run_id AND e.kind IN ('model_call','tool_call')
            AND e.status IN ('ready','claimed');
        IF coalesce(updates->'effects','[]'::jsonb) IS DISTINCT FROM cancel_expected THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        FOR cancel_effect IN SELECT * FROM v24.effects e
          WHERE e.run_id=cancel_run.run_id AND e.kind IN ('model_call','tool_call')
            AND e.status IN ('ready','claimed') LOOP
          IF NOT coalesce(p_closure->'effects' ? cancel_effect.effect_id::text,false) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END LOOP;
        -- Evaluate pin blockers after the projected ready -> cancelled updates.
        SELECT coalesce(jsonb_agg(jsonb_build_object('key',jsonb_build_object('pin_id',pn.pin_id),
          'set',jsonb_build_object('released_at',now(),'released_by_effect',p_effect_id))
          ORDER BY pn.pin_id),'[]'::jsonb) INTO cancel_expected
          FROM v24.pins pn WHERE pn.consumer_run_id=cancel_run.run_id AND pn.released_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM v24.effects e WHERE e.pin_id=pn.pin_id
            AND (e.status IN ('ready','claimed')
                 OR (e.status='unknown' AND e.resource_quiesced_at IS NULL))
            AND NOT (e.run_id IS NOT DISTINCT FROM cancel_run.run_id
                     AND e.kind IN ('model_call','tool_call') AND e.status='ready'));
        IF coalesce(updates->'pins','[]'::jsonb) IS DISTINCT FROM cancel_expected THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        FOR cancel_pin IN SELECT * FROM v24.pins pn
          WHERE pn.consumer_run_id=cancel_run.run_id AND pn.released_at IS NULL LOOP
          IF NOT coalesce(p_closure->'pins' ? cancel_pin.pin_id::text,false)
             OR EXISTS (SELECT 1 FROM v24.effects e WHERE e.pin_id=cancel_pin.pin_id
                  AND (e.status IN ('ready','claimed')
                       OR (e.status='unknown' AND e.resource_quiesced_at IS NULL))
                  AND NOT coalesce(p_closure->'effects' ? e.effect_id::text,false)) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END LOOP;
      EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value
          OR numeric_value_out_of_range OR datetime_field_overflow THEN
        RETURN v24.error_v1('invalid_outcome');
      END;
    END IF;
  END IF;

  IF kind = 'command_steer' THEN
    IF has_error THEN
      IF updates <> '{}'::jsonb OR coalesce(p_delta->'events','[]'::jsonb) <> '[]'::jsonb
         OR coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb
         OR p_delta ? 'effect' OR p_delta ? 'request'
         OR coalesce(p_delta->'error'->'error'->>'code','') NOT IN
              ('already_terminal','stale_generation') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSE
      BEGIN
        SELECT * INTO steer_run FROM v24.runs rr
          WHERE rr.run_id=(body->'payload'->>'run_id')::uuid;
        steer_generation := (body->'payload'->>'expected_generation')::bigint;
        IF steer_run.run_id IS NULL
           OR NOT coalesce(p_closure->'runs' ? steer_run.run_id::text,false)
           OR steer_run.status IN ('completed','failed','cancelled','blocked_unknown')
           OR (v24.run_owner(steer_run.run_id) IS DISTINCT FROM p_principal
               AND NOT pg_has_role(session_user,'v24_admin','USAGE'))
           OR steer_generation IS DISTINCT FROM steer_run.driving_generation
           OR p_delta->'effect' IS DISTINCT FROM jsonb_build_object('run_id',steer_run.run_id)
           OR p_delta->'request' IS DISTINCT FROM jsonb_build_object('response',
                jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
                  'emitted',coalesce((p_delta->'request'->'response'->'emitted'),'[]'::jsonb),
                  'revision',steer_run.revision+1,'claim',NULL))
           OR p_delta->'events' IS DISTINCT FROM jsonb_build_array(jsonb_build_object(
                'entity_type','run','entity_id',steer_run.run_id,'event_kind','run_steered',
                'payload',jsonb_build_object('run_id',steer_run.run_id,
                  'generation',steer_run.driving_generation+1,
                  'deferred',false))) THEN
          -- The exact response/event checks are completed below once the claim branch
          -- and successor shape have been derived.
          NULL;
        END IF;
        IF steer_run.run_id IS NULL
           OR NOT coalesce(p_closure->'runs' ? steer_run.run_id::text,false)
           OR steer_run.status IN ('completed','failed','cancelled','blocked_unknown')
           OR (v24.run_owner(steer_run.run_id) IS DISTINCT FROM p_principal
               AND NOT pg_has_role(session_user,'v24_admin','USAGE'))
           OR steer_generation IS DISTINCT FROM steer_run.driving_generation THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        SELECT EXISTS (SELECT 1 FROM v24.effects e
          WHERE e.run_id=steer_run.run_id AND e.kind IN ('model_call','tool_call')
            AND e.status='claimed') INTO steer_claimed;
        SELECT coalesce(jsonb_agg(jsonb_build_object('key',jsonb_build_object('effect_id',e.effect_id),
          'set',jsonb_build_object('status','cancelled','settled_at',now(),'outcome',NULL))
          ORDER BY e.effect_id),'[]'::jsonb)
          INTO steer_expected FROM v24.effects e
         WHERE e.run_id=steer_run.run_id AND e.kind IN ('model_call','tool_call')
           AND e.status='ready';
        IF coalesce(updates->'effects','[]'::jsonb) IS DISTINCT FROM steer_expected THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        FOR steer_effect IN SELECT * FROM v24.effects e
          WHERE e.run_id=steer_run.run_id AND e.kind IN ('model_call','tool_call')
            AND e.status='ready' LOOP
          IF NOT coalesce(p_closure->'effects' ? steer_effect.effect_id::text,false) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END LOOP;
        -- [S4-addendum A/B] refund archived ready models, then admit from the
        -- post-refund balance; 0 means exhausted, only NULL is unlimited.
        SELECT coalesce(sum(coalesce((e.request->'reserve'->>'tokens')::bigint,0)),0)
          INTO v_steer_refund
          FROM v24.effects e
         WHERE e.run_id=steer_run.run_id AND e.kind='model_call' AND e.status='ready';
        v_steer_balance := CASE WHEN steer_run.remaining_tokens IS NULL THEN NULL
                                ELSE steer_run.remaining_tokens + v_steer_refund END;
        v_steer_admit := NOT steer_claimed AND steer_run.remaining_steps >= 1
                         AND (v_steer_balance IS NULL OR v_steer_balance > 0)
                         AND steer_run.remaining_wall_ms > 0;
        v_steer_digests := v24.model_digests(steer_run.run_id);
        IF v_steer_admit THEN
          v_steer_reserve := v24.model_reserve(v_steer_balance);
          v_steer_balance := v_steer_balance - v_steer_reserve;
        END IF;
        SELECT coalesce(array_agg(e.effect_id ORDER BY e.effect_id),'{}'::uuid[])
          INTO v_steer_excluded
          FROM v24.effects e
         WHERE e.run_id=steer_run.run_id AND e.kind IN ('model_call','tool_call')
           AND e.status='ready';
        v_steer_sealed := NOT steer_claimed AND NOT v_steer_admit
                          AND v24.loop_sealable(steer_run.run_id,p_effect_id,
                                jsonb_build_object('kind','budget'),NULL,NULL,
                                v_steer_excluded,false);
        steer_model := md5(p_effect_id::text || ':model_call:0')::uuid;
        IF NOT v_steer_admit THEN
          IF coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        ELSE
          IF jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) <> 1
             OR p_delta->'successors'->0 IS DISTINCT FROM jsonb_build_object(
               'effect_id',steer_model,'ordinal',0,'kind','model_call','run_id',steer_run.run_id,
               'fiber_id',steer_run.owner_fiber_id,'episode_id',steer_run.owner_episode_id,
               'epoch_no',steer_run.epoch_no+1,'generation',steer_run.driving_generation+1,
               'replay_policy','replay_safe','request',p_delta->'successors'->0->'request') THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
          IF (p_delta->'successors'->0->'request') IS DISTINCT FROM jsonb_build_object(
              'run_id',steer_run.run_id,'epoch_no',steer_run.epoch_no+1,
              'generation',steer_run.driving_generation+1,
              'input',coalesce((SELECT e.request->'input' FROM v24.effects e
                WHERE e.run_id=steer_run.run_id AND e.kind='model_call'
                ORDER BY e.created_at DESC,e.effect_id DESC LIMIT 1),'{}'::jsonb),
              'instruction',body->'payload'->'instruction','v',1,'cause','steer',
              'reserve',jsonb_build_object('tokens',v_steer_reserve),
              'digests',v_steer_digests) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END IF;
        v_steer_set := jsonb_build_object('epoch_no',steer_run.epoch_no+1,
          'driving_generation',steer_run.driving_generation+1,
          'revision',steer_run.revision+1,'interaction',NULL,
          'status',CASE WHEN v_steer_sealed THEN 'completed' ELSE 'running' END,
          'pending_steer',CASE WHEN steer_claimed THEN
            jsonb_build_object('instruction',body->'payload'->'instruction',
              'generation',steer_run.driving_generation+1,'epoch',steer_run.epoch_no+1)
            ELSE NULL END,
          'remaining_steps',steer_run.remaining_steps -
            CASE WHEN v_steer_admit THEN 1 ELSE 0 END,
          'remaining_tokens',v_steer_balance,
          'updated_at',now());
        IF v_steer_sealed THEN
          v_steer_set := v_steer_set || jsonb_build_object('ended_at',now(),
            'close_intent',jsonb_build_object('kind','budget'),
            'result',jsonb_build_object('v',1,'close_reason','budget_exhausted',
              'final_text',NULL,'turn_no',steer_run.turn_no));
          v_steer_pins := v24.run_pin_release_set(steer_run.run_id,p_effect_id,
                                                 'completed',p_effect_id);
        ELSE
          v_steer_pins := '[]'::jsonb;
        END IF;
        IF coalesce(updates->'runs','[]'::jsonb) IS DISTINCT FROM jsonb_build_array(
            jsonb_build_object('key',jsonb_build_object('run_id',steer_run.run_id),
              'set',v_steer_set))
           OR coalesce(updates->'pins','[]'::jsonb) IS DISTINCT FROM v_steer_pins
           OR p_delta->'events' IS DISTINCT FROM jsonb_build_array(jsonb_build_object(
                'entity_type','run','entity_id',steer_run.run_id,'event_kind','run_steered',
                'payload',jsonb_build_object('run_id',steer_run.run_id,
                  'generation',steer_run.driving_generation+1,'deferred',steer_claimed)))
           OR p_delta->'request' IS DISTINCT FROM jsonb_build_object('response',
                jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
                  'emitted',CASE WHEN v_steer_admit THEN jsonb_build_array(steer_model)
                                 ELSE '[]'::jsonb END,
                  'revision',steer_run.revision+1,'claim',NULL)) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value
          OR numeric_value_out_of_range OR datetime_field_overflow THEN
        RETURN v24.error_v1('invalid_outcome');
      END;
    END IF;
  END IF;

  IF kind = 'command_respond' THEN
    IF has_error THEN
      IF updates <> '{}'::jsonb OR coalesce(p_delta->'events','[]'::jsonb) <> '[]'::jsonb
         OR coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb
         OR p_delta ? 'effect' OR p_delta ? 'request'
         OR coalesce(p_delta->'error'->'error'->>'code','') NOT IN
              ('already_terminal','interaction_mismatch','stale_generation') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    ELSE
      BEGIN
        SELECT * INTO respond_run FROM v24.runs rr
          WHERE rr.run_id=(body->'payload'->>'run_id')::uuid;
        respond_generation := (body->'payload'->>'expected_generation')::bigint;
        respond_interaction := (body->'payload'->>'interaction_id')::uuid;
        IF respond_run.run_id IS NULL
           OR NOT coalesce(p_closure->'runs' ? respond_run.run_id::text,false)
           OR respond_run.status IN ('completed','failed','cancelled','blocked_unknown')
           OR (v24.run_owner(respond_run.run_id) IS DISTINCT FROM p_principal
               AND NOT pg_has_role(session_user,'v24_admin','USAGE'))
           OR respond_run.status IS DISTINCT FROM 'waiting'
           OR respond_run.interaction IS NULL
           OR respond_run.interaction->>'interaction_id' IS DISTINCT FROM respond_interaction::text
           OR respond_generation IS DISTINCT FROM respond_run.driving_generation
           OR p_delta->'effect' IS DISTINCT FROM jsonb_build_object('run_id',respond_run.run_id)
           OR jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) > 1 THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
        respond_model := md5(p_effect_id::text || ':model_call:0')::uuid;
        respond_origin := (respond_run.interaction->>'origin_effect_id')::uuid;
        -- [S4-addendum B] 0 means exhausted; only NULL is unlimited.
        v_respond_balance := respond_run.remaining_tokens;
        v_respond_admit := respond_run.remaining_steps >= 1
                           AND (v_respond_balance IS NULL OR v_respond_balance > 0)
                           AND respond_run.remaining_wall_ms > 0;
        v_respond_digests := v24.model_digests(respond_run.run_id);
        IF v_respond_admit THEN
          v_respond_reserve := v24.model_reserve(v_respond_balance);
          v_respond_balance := v_respond_balance - v_respond_reserve;
        END IF;
        v_respond_sealed := NOT v_respond_admit
                            AND v24.loop_sealable(respond_run.run_id,p_effect_id,
                                  jsonb_build_object('kind','budget'),NULL,NULL,
                                  '{}'::uuid[],true);
        v_respond_set := jsonb_build_object('status',
          CASE WHEN v_respond_sealed THEN 'completed' ELSE 'running' END,
          'interaction',NULL,
          'driving_generation',respond_run.driving_generation+1,
          'revision',respond_run.revision+1,
          'remaining_steps',respond_run.remaining_steps -
            CASE WHEN v_respond_admit THEN 1 ELSE 0 END,
          'remaining_tokens',v_respond_balance,
          'updated_at',now());
        IF v_respond_sealed THEN
          v_respond_set := v_respond_set || jsonb_build_object('ended_at',now(),
            'close_intent',jsonb_build_object('kind','budget'),
            'result',jsonb_build_object('v',1,'close_reason','budget_exhausted',
              'final_text',NULL,'turn_no',respond_run.turn_no));
          v_respond_pins := v24.run_pin_release_set(respond_run.run_id,p_effect_id,
                                                    'completed',p_effect_id);
        ELSE
          v_respond_pins := '[]'::jsonb;
        END IF;
        IF NOT v_respond_admit THEN
          IF coalesce(p_delta->'successors','[]'::jsonb) <> '[]'::jsonb THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        ELSE
          IF p_delta->'successors'->0 IS DISTINCT FROM jsonb_build_object(
               'effect_id',respond_model,'ordinal',0,'kind','model_call',
               'run_id',respond_run.run_id,'fiber_id',respond_run.owner_fiber_id,
               'episode_id',respond_run.owner_episode_id,'epoch_no',respond_run.epoch_no,
               'generation',respond_run.driving_generation+1,'replay_policy','no_replay',
               'request',jsonb_build_object('run_id',respond_run.run_id,
                 'epoch_no',respond_run.epoch_no,'generation',respond_run.driving_generation+1,
                 'response',body->'payload'->'response','origin_effect_id',respond_origin,
                 'v',1,'cause','respond',
                 'reserve',jsonb_build_object('tokens',v_respond_reserve),
                 'digests',v_respond_digests)) THEN
            RETURN v24.error_v1('invalid_outcome');
          END IF;
        END IF;
        IF coalesce(updates->'runs','[]'::jsonb) IS DISTINCT FROM jsonb_build_array(
             jsonb_build_object('key',jsonb_build_object('run_id',respond_run.run_id),
               'set',v_respond_set))
           OR coalesce(updates->'pins','[]'::jsonb) IS DISTINCT FROM v_respond_pins
           OR p_delta->'events' IS DISTINCT FROM jsonb_build_array(jsonb_build_object(
             'entity_type','run','entity_id',respond_run.run_id,
             'event_kind','interaction_responded','payload',jsonb_build_object(
               'run_id',respond_run.run_id,'interaction_id',respond_interaction,
               'generation',respond_run.driving_generation+1)))
           OR p_delta->'request' IS DISTINCT FROM jsonb_build_object('response',
             jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
               'emitted',CASE WHEN v_respond_admit THEN jsonb_build_array(respond_model)
                              ELSE '[]'::jsonb END,
               'revision',respond_run.revision+1,'claim',NULL)) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value
          OR numeric_value_out_of_range OR datetime_field_overflow THEN
        RETURN v24.error_v1('invalid_outcome');
      END;
    END IF;
  END IF;

  -- S2: successor shape, born-settled and attribution are closed contracts.
  IF kind NOT IN ('command_start','command_steer','command_respond') THEN
  FOR succ IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) LOOP
    IF jsonb_typeof(succ) IS DISTINCT FROM 'object'
       OR NOT (succ ?& ARRAY['effect_id','ordinal','kind','request'])
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(succ) k
                  WHERE k NOT IN ('effect_id','ordinal','kind','request','fiber_id','status','outcome'))
       OR coalesce(succ->>'status','ready') NOT IN ('ready','succeeded','failed')
       OR (succ->>'status' IN ('succeeded','failed') AND succ->>'kind' <> 'fiber_reconcile')
       OR (succ->>'status' IN ('succeeded','failed') AND NOT (succ ? 'outcome'))
       OR (succ ? 'fiber_id' AND succ->>'kind' <> 'fiber_reconcile')
       OR (succ->>'kind' = 'fiber_reconcile'
           AND ((succ->>'fiber_id') IS NULL
                OR (succ->>'fiber_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))
       OR (succ->>'effect_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  END LOOP;
  END IF;
  -- settle[] may only target ready fiber_reconcile rows in the locked closure.
  IF p_delta ? 'settle' THEN
    IF jsonb_typeof(p_delta->'settle') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_delta->'settle') > 16 THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    FOR r IN SELECT value FROM jsonb_array_elements(p_delta->'settle') LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR NOT (r ?& ARRAY['effect_id','status','outcome'])
         OR r->>'status' NOT IN ('succeeded','failed')
         OR (r->>'effect_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
         OR NOT EXISTS (SELECT 1 FROM v24.effects e
                         WHERE e.effect_id = (r->>'effect_id')::uuid
                           AND e.kind='fiber_reconcile' AND e.status='ready'
                           AND p_closure->'effects' ? (r->>'effect_id')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_delta->'settle') s
               GROUP BY s->>'effect_id' HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_delta->'settle') s
                  JOIN jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) x
                    ON (x->>'effect_id') = (s->>'effect_id')) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  END IF;
  -- fiber_control attribution: the command effect names its locked fiber/scope.
  IF kind = 'command_fiber_control' THEN
    IF NOT (p_delta ? 'effect') OR jsonb_typeof(p_delta->'effect') IS DISTINCT FROM 'object'
       OR NOT (p_delta->'effect' ?& ARRAY['scope_id','fiber_id'])
       OR (p_delta->'effect'->>'fiber_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR (p_delta->'effect'->>'scope_id') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR (p_delta->'effect'->>'fiber_id') IS DISTINCT FROM (body->'payload'->>'fiber_id')
       OR NOT EXISTS (SELECT 1 FROM v24.fibers f
                       WHERE f.fiber_id = (p_delta->'effect'->>'fiber_id')::uuid
                         AND f.scope_id = (p_delta->'effect'->>'scope_id')::uuid) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  END IF;

  -- Validate all scope rows before the first write.  The interpreter supplies
  -- derived root/path values; callers cannot smuggle a different table in.
  rows := coalesce(inserts->'scopes','[]'::jsonb);
  FOR r IN SELECT value FROM jsonb_array_elements(rows) LOOP
    IF jsonb_typeof(r) IS DISTINCT FROM 'object'
       OR NOT (r ?& ARRAY['scope_id','root_id','route_path','owner_principal','created_by_effect'])
       OR (r->>'created_by_effect')::uuid <> p_effect_id
       OR jsonb_typeof(r->'route_path') IS DISTINCT FROM 'array'
       OR (r->'route_path'->>-1)::uuid <> (r->>'scope_id')::uuid THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'scopes','[]'::jsonb)) LOOP
    IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ? 'key') OR NOT (r ? 'set')
       OR jsonb_typeof(r->'key') IS DISTINCT FROM 'object'
       OR (r->'key'->>'scope_id') IS NULL THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') x WHERE x <> 'close_requested_at') THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  END LOOP;

  IF kind = 'command_dispose' THEN
    -- W1 cascade: the stage may update the payload install plus its owner
    -- descendants (the exact set dispose_stage walks).  The set is recomputed
    -- from committed rows; the table footprint below stays installs|fibers.
    WITH RECURSIVE d(install_id) AS (
      SELECT (body->'payload'->>'install_id')::uuid
      UNION
      SELECT ci.install_id
        FROM d
        JOIN v24.fibers f ON f.install_id = d.install_id
        JOIN v24.installs ci ON ci.owner_fiber_id = f.fiber_id
        JOIN v24.episodes e ON e.episode_id = ci.owner_episode_id
                            AND e.fiber_id = f.fiber_id
       WHERE ci.state <> 'disposed'
    )
    SELECT coalesce(array_agg(d.install_id), '{}'::uuid[])
      INTO v_dispose_scope FROM d;

    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'installs','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR (r->'key'->>'install_id') IS NULL
         OR NOT ((r->'key'->>'install_id')::uuid = ANY(v_dispose_scope))
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('state','dispose_effect','disposed_at'))
         OR (r->'set' ? 'state' AND r->'set'->>'state'
             NOT IN ('dispose_pending','disposed'))
         OR (r->'set' ? 'disposed_at' AND r->'set'->>'state' IS DISTINCT FROM 'disposed') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'fibers','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR (r->'key'->>'fiber_id') IS NULL
         OR NOT EXISTS (SELECT 1 FROM v24.fibers f
                         WHERE f.fiber_id = (r->'key'->>'fiber_id')::uuid
                           AND f.install_id = ANY(v_dispose_scope))
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('disposed_at','want_on')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR NOT (r ?& ARRAY['effect_id','ordinal','kind','request'])
         OR r->>'kind' NOT IN ('host_release','inspect_resource')
         OR jsonb_typeof(r->'request') IS DISTINCT FROM 'object'
         OR (r->'request'->>'install_id') IS NULL
         OR NOT ((r->'request'->>'install_id')::uuid = ANY(v_dispose_scope))
         OR (r->>'effect_id') IS NULL
         OR jsonb_typeof(r->'ordinal') IS DISTINCT FROM 'number'
         OR (r->>'ordinal') !~ '^[0-9]{1,2}$'
         OR (r->>'ordinal')::int NOT BETWEEN 0 AND 15 THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      IF r->>'kind' = 'host_release' THEN
        IF (r->>'effect_id')::uuid IS DISTINCT FROM
             md5(p_effect_id::text || ':host_release:'
                 || (r->'request'->>'install_id') || ':0')::uuid
           OR r->'request' IS DISTINCT FROM jsonb_build_object(
                'install_id', (r->'request'->>'install_id')::uuid,
                'reservation', 'v24:host_release:' || (r->>'effect_id')) THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      ELSE
        -- S5 W2/C25 inspect successor: frozen six-key request, deterministic
        -- identity derived from the command effect + install, and a target
        -- host effect that is genuinely unknown and unquiesced.
        IF NOT (r->'request' ?& ARRAY['v','install_id','target','target_effect_id',
                                      'target_reservation','target_request_digest'])
           OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'request') k
                       WHERE k NOT IN ('v','install_id','target','target_effect_id',
                                       'target_reservation','target_request_digest'))
           OR (r->'request'->>'v') IS DISTINCT FROM '1'
           OR (r->'request'->>'target') NOT IN ('host_prepare','host_release')
           OR (r->>'effect_id')::uuid IS DISTINCT FROM
                md5(p_effect_id::text || ':inspect_resource:'
                    || (r->'request'->>'install_id') || ':0')::uuid
           OR (r->'request'->>'target_request_digest') !~ '^[0-9a-f]{64}$'
           OR (r->'request'->>'target_reservation') NOT LIKE
                'v24:' || (r->'request'->>'target') || ':%'
           OR r->'request' IS DISTINCT FROM jsonb_build_object(
                'v', 1,
                'install_id', (r->'request'->>'install_id')::uuid,
                'target', r->'request'->>'target',
                'target_effect_id', (r->'request'->>'target_effect_id')::uuid,
                'target_reservation', r->'request'->>'target_reservation',
                'target_request_digest', r->'request'->>'target_request_digest')
           OR NOT EXISTS (
                SELECT 1 FROM v24.effects t
                 WHERE t.effect_id = (r->'request'->>'target_effect_id')::uuid
                   AND t.kind = r->'request'->>'target'
                   AND t.status = 'unknown'
                   AND t.resource_quiesced_at IS NULL
                   AND (t.request->>'install_id') = r->'request'->>'install_id'
                   AND (t.request->>'reservation') = r->'request'->>'target_reservation'
                   AND encode(t.request_digest,'hex') =
                       r->'request'->>'target_request_digest') THEN
          RETURN v24.error_v1('invalid_outcome');
        END IF;
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'events','[]'::jsonb)) LOOP
      IF (r->>'entity_type') IS DISTINCT FROM 'install'
         OR (r->>'entity_id') IS NULL
         OR NOT ((r->>'entity_id')::uuid = ANY(v_dispose_scope))
         OR r->>'event_kind' NOT IN ('install_dispose_pending','install_release_requested',
                                     'install_inspect_requested','install_disposed') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
  END IF;

  IF kind = 'command_fiber_control' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'episodes','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN
              ('episode_id','fiber_id','epoch','activation_effect','state','target_seq','opened_at'))
         OR (r->>'fiber_id')::uuid IS DISTINCT FROM (body->'payload'->>'fiber_id')::uuid
         OR (r->>'epoch')::bigint < 1
         OR r->>'state' IS DISTINCT FROM 'active'
         OR coalesce((r->>'target_seq')::bigint,0) <> 0
         OR NOT (coalesce(p_closure->'effects' ? (r->>'activation_effect'), false)
                 OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) sx
                            WHERE sx->>'effect_id' = r->>'activation_effect')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'slots','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN
              ('slot_id','fiber_id','episode_id','realm','key','descriptor','descriptor_digest','contribution_seq'))
         OR (r->>'fiber_id')::uuid IS DISTINCT FROM (body->'payload'->>'fiber_id')::uuid
         OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(inserts->'episodes','[]'::jsonb)) ep
                        WHERE ep->>'episode_id' = r->>'episode_id')
         OR length(r->>'realm') NOT BETWEEN 1 AND 128
         OR length(r->>'key') NOT BETWEEN 1 AND 256
         OR (r->>'contribution_seq')::bigint < 0
         OR jsonb_typeof(r->'descriptor') IS DISTINCT FROM 'object' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN
              ('pin_id','consumer_type','consumer_episode_id','consumer_epoch','key','slot_id',
               'provider_fiber_id','provider_episode_id','descriptor_digest','created_by_effect'))
         OR r->>'consumer_type' IS DISTINCT FROM 'activation'
         OR (r->>'consumer_epoch')::bigint IS DISTINCT FROM (
              SELECT (ep->>'epoch')::bigint
              FROM jsonb_array_elements(coalesce(inserts->'episodes','[]'::jsonb)) ep
              WHERE ep->>'episode_id' = r->>'consumer_episode_id')
         OR NOT EXISTS (SELECT 1 FROM v24.slots sl
                         WHERE sl.slot_id = (r->>'slot_id')::uuid
                           AND sl.fiber_id = (r->>'provider_fiber_id')::uuid
                           AND sl.episode_id = (r->>'provider_episode_id')::uuid
                           AND sl.released_at IS NULL AND sl.withdrawn_at IS NULL)
         OR NOT (coalesce(p_closure->'effects' ? (r->>'created_by_effect'), false)
                 OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) sx
                            WHERE sx->>'effect_id' = r->>'created_by_effect')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'fibers','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR NOT (r ?& ARRAY['key','set'])
         OR (r->'key'->>'fiber_id')::uuid IS DISTINCT FROM (body->'payload'->>'fiber_id')::uuid
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k WHERE k NOT IN
              ('want_on','control_seq','failure_seq','failure','current_episode_id','next_contribution_seq')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'episodes','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR NOT EXISTS (SELECT 1 FROM v24.episodes e
                         WHERE e.episode_id = (r->'key'->>'episode_id')::uuid
                           AND e.fiber_id = (body->'payload'->>'fiber_id')::uuid)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('state','retire_started_at','closed_at'))
         OR (r->'set' ? 'state' AND (r->'set'->>'state') NOT IN ('retiring','closed')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'slots','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR NOT EXISTS (SELECT 1 FROM v24.slots s
                         WHERE s.slot_id = (r->'key'->>'slot_id')::uuid
                           AND s.fiber_id = (body->'payload'->>'fiber_id')::uuid)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('withdrawn_at','released_at')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'pins','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR NOT EXISTS (SELECT 1 FROM v24.pins p
                         JOIN v24.episodes pe ON pe.episode_id = p.consumer_episode_id
                         WHERE p.pin_id = (r->'key'->>'pin_id')::uuid
                           AND pe.fiber_id = (body->'payload'->>'fiber_id')::uuid)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('released_at','released_by_effect')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(updates) k
               WHERE k NOT IN ('episodes','slots','pins','fibers')) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'events','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN
              ('entity_type','entity_id','event_kind','payload','payload_digest'))
         OR r->>'entity_type' NOT IN ('fiber','episode','slot','pin')
         OR coalesce(length(r->>'event_kind'),0) = 0
         OR jsonb_typeof(r->'payload') IS DISTINCT FROM 'object'
         OR (r->>'entity_type'='fiber'
             AND (r->>'entity_id')::uuid IS DISTINCT FROM (body->'payload'->>'fiber_id')::uuid)
         OR (r->>'entity_type'='episode' AND NOT (
              EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(inserts->'episodes','[]'::jsonb)) ep
                      WHERE ep->>'episode_id' = r->>'entity_id')
              OR EXISTS (SELECT 1 FROM v24.episodes e
                          WHERE e.episode_id = (r->>'entity_id')::uuid
                            AND e.fiber_id = (body->'payload'->>'fiber_id')::uuid)))
         OR (r->>'entity_type'='slot' AND NOT (
              EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(inserts->'slots','[]'::jsonb)) sl
                      WHERE sl->>'slot_id' = r->>'entity_id')
              OR EXISTS (SELECT 1 FROM v24.slots s
                          WHERE s.slot_id = (r->>'entity_id')::uuid
                            AND s.fiber_id = (body->'payload'->>'fiber_id')::uuid)))
         OR (r->>'entity_type'='pin' AND NOT (
              EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) pn
                      WHERE pn->>'pin_id' = r->>'entity_id')
              OR EXISTS (SELECT 1 FROM v24.pins pn
                          JOIN v24.episodes pe ON pe.episode_id = pn.consumer_episode_id
                          WHERE pn.pin_id = (r->>'entity_id')::uuid
                            AND pe.fiber_id = (body->'payload'->>'fiber_id')::uuid))) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
  END IF;

  request_bytes := decode(body->>'canonical_bytes','base64');
  request_digest := sha256(request_bytes);
  response := p_delta->'request'->'response';
  IF response IS NULL OR response = 'null'::jsonb THEN
    response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
      'emitted','[]'::jsonb,'revision',0,'claim',NULL);
  END IF;
  IF p_delta ? 'error' AND p_delta->'error' IS NOT NULL AND p_delta->'error' <> 'null'::jsonb THEN
    response := p_delta->'error'; status := 'failed'; outcome := p_outcome;
  ELSE
    status := coalesce(p_delta->'effect'->>'status','succeeded'); outcome := coalesce(p_delta->'effect'->'outcome',p_outcome);
  END IF;

  -- Frozen W4 order: domain rows, effect, request, events, successors.
  FOR r IN SELECT value FROM jsonb_array_elements(rows) LOOP
    INSERT INTO v24.scopes(scope_id,parent_id,root_id,route_path,realm_routes,default_realm,
      owner_principal,created_by_effect)
    VALUES ((r->>'scope_id')::uuid,(r->>'parent_id')::uuid,(r->>'root_id')::uuid,
      ARRAY(SELECT value::uuid FROM jsonb_array_elements_text(r->'route_path')),
      coalesce(r->'realm_routes','{}'::jsonb),r->>'default_realm',
      (r->>'owner_principal')::uuid,(r->>'created_by_effect')::uuid);
    scope_id := (r->>'scope_id')::uuid;
    emitted := emitted || jsonb_build_array(scope_id);
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'scopes','[]'::jsonb)) LOOP
    IF (r->'set') ? 'close_requested_at' THEN
      UPDATE v24.scopes AS s SET close_requested_at = coalesce((r->'set'->>'close_requested_at')::timestamptz, now())
       WHERE s.scope_id=(r->'key'->>'scope_id')::uuid;
      scope_id := (r->'key'->>'scope_id')::uuid;
    END IF;
  END LOOP;
  IF kind = 'command_fiber_control' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'episodes','[]'::jsonb)) LOOP
      INSERT INTO v24.episodes SELECT * FROM jsonb_populate_record(NULL::v24.episodes,r);
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'slots','[]'::jsonb)) LOOP
      INSERT INTO v24.slots SELECT * FROM jsonb_populate_record(NULL::v24.slots,r);
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) LOOP
      INSERT INTO v24.pins(pin_id,consumer_type,consumer_episode_id,consumer_run_id,
        consumer_epoch,key,slot_id,provider_fiber_id,provider_episode_id,
        descriptor_digest,created_by_effect,released_by_effect,released_at)
      SELECT p.pin_id,p.consumer_type,p.consumer_episode_id,p.consumer_run_id,
        p.consumer_epoch,p.key,p.slot_id,p.provider_fiber_id,p.provider_episode_id,
        p.descriptor_digest,p.created_by_effect,p.released_by_effect,p.released_at
      FROM jsonb_populate_record(NULL::v24.pins, r) AS p;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'episodes','[]'::jsonb)) LOOP
      UPDATE v24.episodes AS ex SET
        state = CASE WHEN (r->'set') ? 'state' THEN r->'set'->>'state' ELSE ex.state END,
        retire_started_at = CASE WHEN (r->'set') ? 'retire_started_at'
              THEN (r->'set'->>'retire_started_at')::timestamptz ELSE ex.retire_started_at END,
        closed_at = CASE WHEN (r->'set') ? 'closed_at'
              THEN (r->'set'->>'closed_at')::timestamptz ELSE ex.closed_at END
      WHERE ex.episode_id = (r->'key'->>'episode_id')::uuid;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'slots','[]'::jsonb)) LOOP
      UPDATE v24.slots AS sl SET
        withdrawn_at = CASE WHEN (r->'set') ? 'withdrawn_at'
              THEN (r->'set'->>'withdrawn_at')::timestamptz ELSE sl.withdrawn_at END,
        released_at = CASE WHEN (r->'set') ? 'released_at'
              THEN (r->'set'->>'released_at')::timestamptz ELSE sl.released_at END
      WHERE sl.slot_id = (r->'key'->>'slot_id')::uuid;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'pins','[]'::jsonb)) LOOP
      UPDATE v24.pins AS pn SET
        released_at = CASE WHEN (r->'set') ? 'released_at'
              THEN (r->'set'->>'released_at')::timestamptz ELSE pn.released_at END,
        released_by_effect = CASE WHEN (r->'set') ? 'released_by_effect'
              THEN (r->'set'->>'released_by_effect')::uuid ELSE pn.released_by_effect END
      WHERE pn.pin_id = (r->'key'->>'pin_id')::uuid;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'fibers','[]'::jsonb)) LOOP
      UPDATE v24.fibers AS fx SET
        want_on = CASE WHEN (r->'set') ? 'want_on'
                       THEN ((r->'set')->>'want_on')::boolean ELSE fx.want_on END,
        control_seq = CASE WHEN (r->'set') ? 'control_seq'
                       THEN ((r->'set')->>'control_seq')::bigint ELSE fx.control_seq END,
        current_episode_id = CASE WHEN (r->'set') ? 'current_episode_id'
                       THEN (r->'set'->>'current_episode_id')::uuid ELSE fx.current_episode_id END,
        failure_seq = CASE WHEN (r->'set') ? 'failure_seq'
                       THEN (r->'set'->>'failure_seq')::bigint ELSE fx.failure_seq END,
        failure = CASE WHEN (r->'set') ? 'failure'
                       THEN nullif(r->'set'->'failure','null'::jsonb) ELSE fx.failure END,
        next_contribution_seq = CASE WHEN (r->'set') ? 'next_contribution_seq'
                       THEN (r->'set'->>'next_contribution_seq')::bigint ELSE fx.next_contribution_seq END
      WHERE fx.fiber_id = (r->'key'->>'fiber_id')::uuid;
    END LOOP;
  END IF;

  IF kind = 'command_start' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'runs','[]'::jsonb)) LOOP
      INSERT INTO v24.runs SELECT * FROM jsonb_populate_record(NULL::v24.runs,r);
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(inserts->'pins','[]'::jsonb)) LOOP
      INSERT INTO v24.pins(pin_id,consumer_type,consumer_run_id,consumer_epoch,key,
        slot_id,provider_fiber_id,provider_episode_id,descriptor_digest,created_by_effect)
      SELECT pn.pin_id,pn.consumer_type,pn.consumer_run_id,pn.consumer_epoch,pn.key,
        pn.slot_id,pn.provider_fiber_id,pn.provider_episode_id,pn.descriptor_digest,pn.created_by_effect
      FROM jsonb_populate_record(NULL::v24.pins,r) pn;
    END LOOP;
    -- The two run references were prevalidated against the insert delta;
    -- now check them against the inserted row before persisting either effect.
    IF NOT has_error AND NOT EXISTS (SELECT 1 FROM v24.runs rr
          WHERE rr.run_id=(p_delta->'effect'->>'run_id')::uuid
            AND rr.run_id=(p_delta->'successors'->0->>'run_id')::uuid
            AND rr.scope_id=(body->'payload'->>'scope_id')::uuid
            AND rr.owner_fiber_id IS NOT DISTINCT FROM start_run.owner_fiber_id
            AND rr.owner_episode_id IS NOT DISTINCT FROM start_run.owner_episode_id) THEN
      RAISE EXCEPTION 'v24 start: inserted run attribution mismatch' USING ERRCODE='22023';
    END IF;
  END IF;

  IF kind = 'command_cancel' AND NOT has_error THEN
    UPDATE v24.runs AS rr SET status='cancelled',ended_at=now(),
      interaction=NULL,pending_steer=NULL,
      close_intent=jsonb_build_object('kind','cancel','generation',cancel_generation,'at',now()),
      remaining_tokens=CASE WHEN (updates->'runs'->0->'set'->'remaining_tokens') = 'null'::jsonb
                            THEN NULL
                            ELSE (updates->'runs'->0->'set'->>'remaining_tokens')::bigint END,
      driving_generation=rr.driving_generation+1,revision=rr.revision+1,updated_at=now()
      WHERE rr.run_id=cancel_run.run_id;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'effects','[]'::jsonb)) LOOP
      IF r->'set' ? 'status' THEN
        UPDATE v24.effects AS ef SET status='cancelled',settled_at=now(),outcome=NULL
          WHERE ef.effect_id=(r->'key'->>'effect_id')::uuid AND ef.run_id=cancel_run.run_id
            AND ef.kind IN ('model_call','tool_call') AND ef.status='ready';
      ELSE
        UPDATE v24.effects AS ef SET cancel_requested=true
          WHERE ef.effect_id=(r->'key'->>'effect_id')::uuid AND ef.run_id=cancel_run.run_id
            AND ef.kind IN ('model_call','tool_call') AND ef.status='claimed';
      END IF;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 cancel: effect transition changed' USING ERRCODE='40001';
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'pins','[]'::jsonb)) LOOP
      UPDATE v24.pins AS pn SET released_at=now(),released_by_effect=p_effect_id
        WHERE pn.pin_id=(r->'key'->>'pin_id')::uuid AND pn.consumer_run_id=cancel_run.run_id
          AND pn.released_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM v24.effects e WHERE e.pin_id=pn.pin_id
            AND (e.status IN ('ready','claimed')
                 OR (e.status='unknown' AND e.resource_quiesced_at IS NULL)));
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 cancel: pin remains referenced' USING ERRCODE='40001';
      END IF;
    END LOOP;
    scope_id := cancel_run.scope_id;
  END IF;

  -- W5 steer must archive the ready business effects before inserting its
  -- immediate successor (the run-level unique model_call index enforces this).
  IF kind = 'command_steer' AND NOT has_error THEN
    UPDATE v24.runs AS rr SET
      epoch_no=rr.epoch_no+1,
      driving_generation=rr.driving_generation+1,
      revision=rr.revision+1,
      interaction=NULL,
      status=(updates->'runs'->0->'set'->>'status'),
      pending_steer=CASE WHEN (updates->'runs'->0->'set'->'pending_steer') = 'null'::jsonb
                         THEN NULL ELSE updates->'runs'->0->'set'->'pending_steer' END,
      remaining_steps=(updates->'runs'->0->'set'->>'remaining_steps')::integer,
      remaining_tokens=CASE WHEN (updates->'runs'->0->'set'->'remaining_tokens') = 'null'::jsonb
                            THEN NULL
                            ELSE (updates->'runs'->0->'set'->>'remaining_tokens')::bigint END,
      close_intent=CASE WHEN updates->'runs'->0->'set' ? 'close_intent'
                        THEN updates->'runs'->0->'set'->'close_intent' ELSE rr.close_intent END,
      result=CASE WHEN updates->'runs'->0->'set' ? 'result'
                  THEN updates->'runs'->0->'set'->'result' ELSE rr.result END,
      ended_at=CASE WHEN updates->'runs'->0->'set' ? 'ended_at'
                    THEN (updates->'runs'->0->'set'->>'ended_at')::timestamptz
                    ELSE rr.ended_at END,
      updated_at=now()
      WHERE rr.run_id=steer_run.run_id;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'effects','[]'::jsonb)) LOOP
      UPDATE v24.effects AS ef SET status='cancelled',settled_at=now(),outcome=NULL
        WHERE ef.effect_id=(r->'key'->>'effect_id')::uuid
          AND ef.run_id=steer_run.run_id AND ef.kind IN ('model_call','tool_call')
          AND ef.status='ready';
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 steer: effect transition changed' USING ERRCODE='40001';
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'pins','[]'::jsonb)) LOOP
      UPDATE v24.pins AS pn SET released_at=now(),released_by_effect=p_effect_id
        WHERE pn.pin_id=(r->'key'->>'pin_id')::uuid AND pn.consumer_run_id=steer_run.run_id
          AND pn.released_at IS NULL;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 steer: pin release changed' USING ERRCODE='40001';
      END IF;
    END LOOP;
    scope_id := steer_run.scope_id;
  END IF;

  IF kind = 'command_respond' AND NOT has_error THEN
    UPDATE v24.runs AS rr SET
      status=(updates->'runs'->0->'set'->>'status'),
      interaction=NULL,
      driving_generation=rr.driving_generation+1,
      revision=rr.revision+1,
      remaining_steps=(updates->'runs'->0->'set'->>'remaining_steps')::integer,
      remaining_tokens=CASE WHEN (updates->'runs'->0->'set'->'remaining_tokens') = 'null'::jsonb
                            THEN NULL
                            ELSE (updates->'runs'->0->'set'->>'remaining_tokens')::bigint END,
      close_intent=CASE WHEN updates->'runs'->0->'set' ? 'close_intent'
                        THEN updates->'runs'->0->'set'->'close_intent' ELSE rr.close_intent END,
      result=CASE WHEN updates->'runs'->0->'set' ? 'result'
                  THEN updates->'runs'->0->'set'->'result' ELSE rr.result END,
      ended_at=CASE WHEN updates->'runs'->0->'set' ? 'ended_at'
                    THEN (updates->'runs'->0->'set'->>'ended_at')::timestamptz
                    ELSE rr.ended_at END,
      updated_at=now()
      WHERE rr.run_id=respond_run.run_id;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'pins','[]'::jsonb)) LOOP
      UPDATE v24.pins AS pn SET released_at=now(),released_by_effect=p_effect_id
        WHERE pn.pin_id=(r->'key'->>'pin_id')::uuid AND pn.consumer_run_id=respond_run.run_id
          AND pn.released_at IS NULL;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 respond: pin release changed' USING ERRCODE='40001';
      END IF;
    END LOOP;
    scope_id := respond_run.scope_id;
  END IF;

  IF scope_id IS NULL THEN
    BEGIN scope_id := (body->'payload'->>'scope_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN NULL; END;
  END IF;
  IF kind = 'command_dispose' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'installs','[]'::jsonb)) LOOP
      UPDATE v24.installs AS it SET
        state = CASE WHEN (r->'set') ? 'state' THEN r->'set'->>'state' ELSE it.state END,
        dispose_effect = CASE WHEN (r->'set') ? 'dispose_effect'
              THEN (r->'set'->>'dispose_effect')::uuid ELSE it.dispose_effect END,
        disposed_at = CASE WHEN (r->'set') ? 'disposed_at'
              THEN (r->'set'->>'disposed_at')::timestamptz ELSE it.disposed_at END
      WHERE it.install_id = (r->'key'->>'install_id')::uuid;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'fibers','[]'::jsonb)) LOOP
      UPDATE v24.fibers AS fx SET
        disposed_at = CASE WHEN (r->'set') ? 'disposed_at'
              THEN (r->'set'->>'disposed_at')::timestamptz ELSE fx.disposed_at END,
        want_on = CASE WHEN (r->'set') ? 'want_on'
              THEN (r->'set'->>'want_on')::boolean ELSE fx.want_on END
      WHERE fx.fiber_id = (r->'key'->>'fiber_id')::uuid;
    END LOOP;
  END IF;

  scope_id := coalesce(scope_id,(p_delta->'effect'->>'scope_id')::uuid);
  INSERT INTO v24.effects(effect_id,requester_id,request_key,scope_id,run_id,fiber_id,episode_id,kind,status,request,request_digest,replay_policy,outcome,settled_at)
  VALUES(p_effect_id,p_principal,body->>'request_key',
    scope_id,
    (p_delta->'effect'->>'run_id')::uuid,
    (p_delta->'effect'->>'fiber_id')::uuid,
    (p_delta->'effect'->>'episode_id')::uuid,
    kind,status,p_outcome,request_digest,'replay_safe',outcome,now());
  INSERT INTO v24.requests(principal_id,request_key,kind,request_bytes,request_digest,effect_id,response)
  VALUES(p_principal,body->>'request_key',kind,request_bytes,request_digest,p_effect_id,response);
  FOR ev IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'events','[]'::jsonb)) LOOP
    SELECT coalesce(max(e.seq),0)+1 INTO seq FROM v24.events e
      WHERE entity_type=ev->>'entity_type' AND entity_id=(ev->>'entity_id')::uuid;
    INSERT INTO v24.events(effect_id,seq,entity_type,entity_id,event_kind,payload,payload_digest)
    VALUES(p_effect_id,seq,ev->>'entity_type',(ev->>'entity_id')::uuid,ev->>'event_kind',
      coalesce(ev->'payload','{}'::jsonb),coalesce((ev->>'payload_digest')::bytea,sha256(convert_to((coalesce(ev->'payload','{}'::jsonb))::text,'UTF8'))));
  END LOOP;
  FOR succ IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) LOOP
    new_id := coalesce((succ->>'effect_id')::uuid,gen_random_uuid());
    INSERT INTO v24.effects(effect_id,parent_effect_id,ordinal,requester_id,scope_id,run_id,fiber_id,episode_id,epoch_no,generation,kind,status,request,request_digest,replay_policy,outcome,settled_at)
    VALUES(new_id,p_effect_id,(succ->>'ordinal')::int,p_principal,scope_id,
      (succ->>'run_id')::uuid,(succ->>'fiber_id')::uuid,(succ->>'episode_id')::uuid,
      (succ->>'epoch_no')::bigint,(succ->>'generation')::bigint,
      succ->>'kind',coalesce(succ->>'status','ready'),
      coalesce(succ->'request','{}'::jsonb),sha256(convert_to(coalesce(succ->'request','{}'::jsonb)::text,'UTF8')),
      CASE WHEN kind IN ('command_start','command_steer','command_respond') THEN 'no_replay' ELSE 'replay_safe' END,
      CASE WHEN succ->>'status' IN ('succeeded','failed') THEN succ->'outcome' ELSE NULL END,
      CASE WHEN succ->>'status' IN ('succeeded','failed') THEN now() ELSE NULL END);
    emitted := emitted || jsonb_build_array(new_id);
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'settle','[]'::jsonb)) LOOP
    UPDATE v24.effects AS ef SET status=r->>'status', outcome=r->'outcome', settled_at=now()
      WHERE ef.effect_id=(r->>'effect_id')::uuid
        AND ef.kind='fiber_reconcile' AND ef.status='ready'
        AND r->>'status' IN ('succeeded','failed');
    IF NOT FOUND THEN
      RAISE EXCEPTION 'v24 settle: reconcile effect not ready'
        USING ERRCODE='40001';
    END IF;
  END LOOP;
  RETURN response;
END;
$$;

-- S3 W4: seal publication authority without claiming resource quiescence.
CREATE FUNCTION v24.interpret_cancel(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  p jsonb := p_outcome->'body'->'payload';
  current_run v24.runs%ROWTYPE;
  expected_generation bigint;
  effect_updates jsonb;
  pin_updates jsonb;
  cancel_refund bigint;
BEGIN
  IF NOT (p ?& ARRAY['run_id','expected_generation'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p) k WHERE k NOT IN ('run_id','expected_generation'))
     OR jsonb_typeof(p->'run_id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p->'expected_generation') IS DISTINCT FROM 'number'
     OR (p->>'expected_generation') !~ '^[0-9]+$'
     OR (p->>'expected_generation')::numeric > 9223372036854775807 THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  expected_generation := (p->>'expected_generation')::bigint;
  SELECT * INTO current_run FROM v24.runs rr WHERE rr.run_id=(p->>'run_id')::uuid;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  IF v24.run_owner(current_run.run_id) IS DISTINCT FROM p_principal
     AND NOT pg_has_role(session_user,'v24_admin','USAGE') THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('unauthorized'));
  END IF;
  -- Terminal precedence is intentional: a fresh key never revives a sealed run.
  IF current_run.status IN ('completed','failed','cancelled','blocked_unknown') THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('already_terminal'));
  END IF;
  IF expected_generation IS DISTINCT FROM current_run.driving_generation THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('stale_generation'));
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('key',jsonb_build_object('effect_id',e.effect_id),
    'set',CASE WHEN e.status='ready'
       THEN jsonb_build_object('status','cancelled','settled_at',now(),'outcome',NULL)
       ELSE jsonb_build_object('cancel_requested',true) END) ORDER BY e.effect_id),'[]'::jsonb)
    INTO effect_updates FROM v24.effects e
    WHERE e.run_id=current_run.run_id AND e.kind IN ('model_call','tool_call')
      AND e.status IN ('ready','claimed');
  -- [S4-addendum A] ready model reserves return to the run in this same delta.
  SELECT coalesce(sum(coalesce((e.request->'reserve'->>'tokens')::bigint,0)),0)
    INTO cancel_refund FROM v24.effects e
    WHERE e.run_id=current_run.run_id AND e.kind='model_call' AND e.status='ready';
  -- Ignore exactly the ready business effects cancelled by this same delta.
  SELECT coalesce(jsonb_agg(jsonb_build_object('key',jsonb_build_object('pin_id',pn.pin_id),
    'set',jsonb_build_object('released_at',now(),'released_by_effect',p_effect_id))
    ORDER BY pn.pin_id),'[]'::jsonb) INTO pin_updates
    FROM v24.pins pn WHERE pn.consumer_run_id=current_run.run_id AND pn.released_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM v24.effects e WHERE e.pin_id=pn.pin_id
      AND (e.status IN ('ready','claimed')
           OR (e.status='unknown' AND e.resource_quiesced_at IS NULL))
      AND NOT (e.run_id IS NOT DISTINCT FROM current_run.run_id
               AND e.kind IN ('model_call','tool_call') AND e.status='ready'));
  RETURN jsonb_build_object('domain',jsonb_build_object('update',jsonb_build_object(
    'runs',jsonb_build_array(jsonb_build_object('key',jsonb_build_object('run_id',current_run.run_id),
      'set',jsonb_build_object('status','cancelled','ended_at',now(),
        'interaction',NULL,'pending_steer',NULL,
        'close_intent',jsonb_build_object('kind','cancel','generation',expected_generation,'at',now()),
        'remaining_tokens',CASE WHEN current_run.remaining_tokens IS NULL THEN NULL
                                ELSE current_run.remaining_tokens + cancel_refund END,
        'driving_generation',current_run.driving_generation+1,
        'revision',current_run.revision+1,'updated_at',now()))),
    'effects',effect_updates,'pins',pin_updates)),
    'effect',jsonb_build_object('run_id',current_run.run_id),
    'request',jsonb_build_object('response',jsonb_build_object('v',1,'disposition','committed',
      'effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',current_run.revision+1,'claim',NULL)),
    'events',jsonb_build_array(jsonb_build_object('entity_type','run','entity_id',current_run.run_id,
      'event_kind','run_cancelled','payload',jsonb_build_object('run_id',current_run.run_id,
        'generation',expected_generation))),
    'successors','[]'::jsonb);
END;
$$;

-- S3 W5: steer advances the run epoch and either continues immediately or defers
-- behind an already claimed business effect.
CREATE FUNCTION v24.interpret_steer(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  p jsonb := p_outcome->'body'->'payload';
  current_run v24.runs%ROWTYPE;
  expected_generation bigint;
  ready_updates jsonb;
  has_claimed boolean;
  model_id uuid := md5(p_effect_id::text || ':model_call:0')::uuid;
  prior_input jsonb;
  next_epoch bigint;
  next_generation bigint;
  response jsonb;
  refund bigint;
  balance bigint;
  admit boolean;
  sealed boolean;
  reserve_next bigint;
  digests jsonb;
  close_intent jsonb;
  result jsonb;
  pin_updates jsonb;
  run_set jsonb;
  excluded_ids uuid[];
BEGIN
  IF jsonb_typeof(p) IS DISTINCT FROM 'object'
     OR NOT (p ?& ARRAY['run_id','expected_generation','instruction'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p) k
                WHERE k NOT IN ('run_id','expected_generation','instruction'))
     OR jsonb_typeof(p->'run_id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p->'expected_generation') IS DISTINCT FROM 'number'
     OR (p->>'expected_generation') !~ '^[0-9]+$'
     OR (p->>'expected_generation')::numeric > 9223372036854775807
     OR jsonb_typeof(p->'instruction') IS DISTINCT FROM 'string'
     OR length(p->>'instruction') NOT BETWEEN 1 AND 8192 THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    expected_generation := (p->>'expected_generation')::bigint;
    SELECT * INTO current_run FROM v24.runs WHERE run_id=(p->>'run_id')::uuid;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  IF v24.run_owner(current_run.run_id) IS DISTINCT FROM p_principal
     AND NOT pg_has_role(session_user,'v24_admin','USAGE') THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('unauthorized'));
  END IF;
  -- D-S4-3: blocked_unknown is a W0 wall with its own code, never
  -- already_terminal.  completed/failed/cancelled keep their S3 W1 receipt.
  IF current_run.status = 'blocked_unknown' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('blocked_unknown'));
  ELSIF current_run.status IN ('completed','failed','cancelled') THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('already_terminal'));
  END IF;
  IF expected_generation IS DISTINCT FROM current_run.driving_generation THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('stale_generation'));
  END IF;

  SELECT coalesce(jsonb_agg(jsonb_build_object(
      'key',jsonb_build_object('effect_id',e.effect_id),
      'set',jsonb_build_object('status','cancelled','settled_at',now(),'outcome',NULL))
      ORDER BY e.effect_id),'[]'::jsonb)
    INTO ready_updates
    FROM v24.effects e
   WHERE e.run_id=current_run.run_id AND e.kind IN ('model_call','tool_call')
     AND e.status='ready';
  SELECT EXISTS (SELECT 1 FROM v24.effects e
    WHERE e.run_id=current_run.run_id AND e.kind IN ('model_call','tool_call')
      AND e.status='claimed') INTO has_claimed;
  -- [S4-addendum A] A ready model removed without execution refunds its full
  -- reserve in the same delta.
  SELECT coalesce(sum(coalesce((e.request->'reserve'->>'tokens')::bigint,0)),0)
    INTO refund
    FROM v24.effects e
   WHERE e.run_id=current_run.run_id AND e.kind='model_call' AND e.status='ready';
  balance := CASE WHEN current_run.remaining_tokens IS NULL THEN NULL
                  ELSE current_run.remaining_tokens + refund END;
  SELECT coalesce(e.request->'input','{}'::jsonb) INTO prior_input
    FROM v24.effects e
   WHERE e.run_id=current_run.run_id AND e.kind='model_call'
   ORDER BY e.created_at DESC,e.effect_id DESC LIMIT 1;
  next_epoch := current_run.epoch_no + 1;
  next_generation := current_run.driving_generation + 1;
  -- [S4-addendum B] 0 is exhausted, not unlimited.
  admit := NOT has_claimed AND current_run.remaining_steps >= 1
           AND (balance IS NULL OR balance > 0)
           AND current_run.remaining_wall_ms > 0;
  -- Effects this delta archives must not block its own budget seal.
  SELECT coalesce(array_agg(e.effect_id ORDER BY e.effect_id),'{}'::uuid[])
    INTO excluded_ids
    FROM v24.effects e
   WHERE e.run_id=current_run.run_id AND e.kind IN ('model_call','tool_call')
     AND e.status='ready';
  digests := v24.model_digests(current_run.run_id);
  IF admit THEN
    reserve_next := v24.model_reserve(balance);
    balance := balance - reserve_next;
  END IF;
  sealed := NOT has_claimed AND NOT admit
            AND v24.loop_sealable(current_run.run_id,p_effect_id,
                  jsonb_build_object('kind','budget'),NULL,NULL,
                  excluded_ids,false);
  run_set := jsonb_build_object('epoch_no',next_epoch,
    'driving_generation',next_generation,'revision',current_run.revision+1,
    'interaction',NULL,
    'status',CASE WHEN sealed THEN 'completed' ELSE 'running' END,
    'pending_steer',CASE WHEN has_claimed THEN
      jsonb_build_object('instruction',p->>'instruction','generation',next_generation,'epoch',next_epoch)
      ELSE NULL END,
    'remaining_steps',current_run.remaining_steps - CASE WHEN admit THEN 1 ELSE 0 END,
    'remaining_tokens',balance,
    'updated_at',now());
  IF sealed THEN
    close_intent := jsonb_build_object('kind','budget');
    result := jsonb_build_object('v',1,'close_reason','budget_exhausted',
      'final_text',NULL,'turn_no',current_run.turn_no);
    run_set := run_set || jsonb_build_object('ended_at',now(),
      'close_intent',close_intent,'result',result);
    pin_updates := v24.run_pin_release_set(current_run.run_id,p_effect_id,
                                           'completed',p_effect_id);
  ELSE
    pin_updates := '[]'::jsonb;
  END IF;
  response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',CASE WHEN admit THEN jsonb_build_array(model_id) ELSE '[]'::jsonb END,
    'revision',current_run.revision+1,'claim',NULL);
  RETURN jsonb_build_object(
    'domain',jsonb_build_object('update',jsonb_build_object(
      'runs',jsonb_build_array(jsonb_build_object('key',jsonb_build_object('run_id',current_run.run_id),
        'set',run_set)),
      'effects',ready_updates,'pins',pin_updates)),
    'effect',jsonb_build_object('run_id',current_run.run_id),
    'request',jsonb_build_object('response',response),
    'events',jsonb_build_array(jsonb_build_object('entity_type','run','entity_id',current_run.run_id,
      'event_kind','run_steered','payload',jsonb_build_object('run_id',current_run.run_id,
        'generation',next_generation,'deferred',has_claimed))),
    'successors',CASE WHEN admit THEN jsonb_build_array(
      jsonb_build_object('effect_id',model_id,'ordinal',0,'kind','model_call',
        'run_id',current_run.run_id,'fiber_id',current_run.owner_fiber_id,
        'episode_id',current_run.owner_episode_id,'epoch_no',next_epoch,
        'generation',next_generation,'replay_policy','replay_safe',
        'request',jsonb_build_object('run_id',current_run.run_id,'epoch_no',next_epoch,
          'generation',next_generation,'input',coalesce(prior_input,'{}'::jsonb),
          'instruction',p->>'instruction','v',1,'cause','steer',
          'reserve',jsonb_build_object('tokens',reserve_next),
          'digests',digests))) ELSE '[]'::jsonb END);
END;
$$;

-- S3 W6: interaction matching precedes CAS, so a second key observes consumption.
CREATE FUNCTION v24.interpret_respond(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  p jsonb := p_outcome->'body'->'payload';
  current_run v24.runs%ROWTYPE;
  expected_generation bigint;
  interaction_id uuid;
  origin_id uuid;
  model_id uuid := md5(p_effect_id::text || ':model_call:0')::uuid;
  next_generation bigint;
  admit boolean;
  sealed boolean;
  reserve_next bigint;
  digests jsonb;
  balance bigint;
  run_set jsonb;
BEGIN
  IF jsonb_typeof(p) IS DISTINCT FROM 'object'
     OR NOT (p ?& ARRAY['run_id','interaction_id','response','expected_generation'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p) k
                WHERE k NOT IN ('run_id','interaction_id','response','expected_generation'))
     OR jsonb_typeof(p->'run_id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p->'interaction_id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p->'response') IS DISTINCT FROM 'object'
     OR jsonb_typeof(p->'expected_generation') IS DISTINCT FROM 'number'
     OR (p->>'expected_generation') !~ '^[0-9]+$'
     OR (p->>'expected_generation')::numeric > 9223372036854775807 THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    expected_generation := (p->>'expected_generation')::bigint;
    interaction_id := (p->>'interaction_id')::uuid;
    SELECT * INTO current_run FROM v24.runs WHERE run_id=(p->>'run_id')::uuid;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  IF v24.run_owner(current_run.run_id) IS DISTINCT FROM p_principal
     AND NOT pg_has_role(session_user,'v24_admin','USAGE') THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('unauthorized'));
  END IF;
  -- D-S4-3: a blocked_unknown run answers with its own W0 code before the
  -- interaction/CAS checks; completed/failed/cancelled keep already_terminal.
  IF current_run.status = 'blocked_unknown' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('blocked_unknown'));
  ELSIF current_run.status IN ('completed','failed','cancelled') THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('already_terminal'));
  END IF;
  IF current_run.status IS DISTINCT FROM 'waiting' OR current_run.interaction IS NULL
     OR current_run.interaction->>'interaction_id' IS DISTINCT FROM interaction_id::text THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('interaction_mismatch'));
  END IF;
  IF expected_generation IS DISTINCT FROM current_run.driving_generation THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('stale_generation'));
  END IF;
  origin_id := (current_run.interaction->>'origin_effect_id')::uuid;
  next_generation := current_run.driving_generation+1;
  balance := current_run.remaining_tokens;
  -- [S4-addendum B] a 0 balance is exhausted; never admit reserve=0 there.
  admit := current_run.remaining_steps >= 1
           AND (balance IS NULL OR balance > 0)
           AND current_run.remaining_wall_ms > 0;
  digests := v24.model_digests(current_run.run_id);
  IF admit THEN
    reserve_next := v24.model_reserve(balance);
    balance := balance - reserve_next;
  END IF;
  sealed := NOT admit
            AND v24.loop_sealable(current_run.run_id,p_effect_id,
                  jsonb_build_object('kind','budget'),NULL,NULL,'{}'::uuid[],true);
  run_set := jsonb_build_object('status',
    CASE WHEN sealed THEN 'completed' ELSE 'running' END,
    'interaction',NULL,
    'driving_generation',next_generation,
    'revision',current_run.revision+1,
    'remaining_steps',current_run.remaining_steps - CASE WHEN admit THEN 1 ELSE 0 END,
    'remaining_tokens',balance,
    'updated_at',now());
  IF sealed THEN
    run_set := run_set || jsonb_build_object('ended_at',now(),
      'close_intent',jsonb_build_object('kind','budget'),
      'result',jsonb_build_object('v',1,'close_reason','budget_exhausted',
        'final_text',NULL,'turn_no',current_run.turn_no));
  END IF;
  RETURN jsonb_build_object(
    'domain',jsonb_build_object('update',jsonb_build_object('runs',jsonb_build_array(
      jsonb_build_object('key',jsonb_build_object('run_id',current_run.run_id),
        'set',run_set)),
      'pins',CASE WHEN sealed THEN v24.run_pin_release_set(
        current_run.run_id,p_effect_id,'completed',p_effect_id) ELSE '[]'::jsonb END)),
    'effect',jsonb_build_object('run_id',current_run.run_id),
    'request',jsonb_build_object('response',jsonb_build_object('v',1,'disposition','committed',
      'effect_id',p_effect_id,
      'emitted',CASE WHEN admit THEN jsonb_build_array(model_id) ELSE '[]'::jsonb END,
      'revision',current_run.revision+1,'claim',NULL)),
    'events',jsonb_build_array(jsonb_build_object('entity_type','run','entity_id',current_run.run_id,
      'event_kind','interaction_responded','payload',jsonb_build_object('run_id',current_run.run_id,
        'interaction_id',interaction_id,'generation',next_generation))),
    'successors',CASE WHEN admit THEN jsonb_build_array(jsonb_build_object('effect_id',model_id,'ordinal',0,
      'kind','model_call','run_id',current_run.run_id,'fiber_id',current_run.owner_fiber_id,
      'episode_id',current_run.owner_episode_id,'epoch_no',current_run.epoch_no,
      'generation',next_generation,'replay_policy','no_replay',
      'request',jsonb_build_object('run_id',current_run.run_id,'epoch_no',current_run.epoch_no,
        'generation',next_generation,'response',p->'response','origin_effect_id',origin_id,
        'v',1,'cause','respond',
        'reserve',jsonb_build_object('tokens',reserve_next),
        'digests',digests))) ELSE '[]'::jsonb END);
END;
$$;

-- S3 W2: start only interprets local data and the locked capability snapshot.
CREATE FUNCTION v24.interpret_start(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  p jsonb := p_outcome->'body'->'payload';
  inp jsonb := p->'input';
  budget jsonb := p->'budget';
  reqs jsonb := coalesce(inp->'requires','[]'::jsonb);
  sc v24.scopes%ROWTYPE;
  f v24.fibers%ROWTYPE;
  ep v24.episodes%ROWTYPE;
  it v24.installs%ROWTYPE;
  item jsonb;
  b record;
  resolved record;
  run_id uuid := gen_random_uuid();
  model_id uuid := md5(p_effect_id::text || ':model_call:0')::uuid;
  pins jsonb := '[]'::jsonb;
  run_row jsonb;
  response jsonb;
  digests jsonb;
  fail_code text;
BEGIN
  IF NOT (p ?& ARRAY['scope_id','owner_fiber_id','input','budget'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p) k
                WHERE k NOT IN ('scope_id','owner_fiber_id','input','budget'))
     OR jsonb_typeof(p->'scope_id') IS DISTINCT FROM 'string'
     OR (p->'owner_fiber_id' <> 'null'::jsonb
         AND jsonb_typeof(p->'owner_fiber_id') IS DISTINCT FROM 'string')
     OR jsonb_typeof(inp) IS DISTINCT FROM 'object'
     OR jsonb_typeof(budget) IS DISTINCT FROM 'object'
     OR jsonb_typeof(reqs) IS DISTINCT FROM 'array' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  IF jsonb_array_length(reqs) > 16 THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(reqs) LOOP
    IF jsonb_typeof(item) IS DISTINCT FROM 'object'
       OR NOT (item ? 'key')
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(item) k WHERE k <> 'key')
       OR jsonb_typeof(item->'key') IS DISTINCT FROM 'string'
       OR length(item->>'key') NOT BETWEEN 1 AND 256 THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(reqs) r
             GROUP BY r->>'key' HAVING count(*)>1)
     OR ((p->>'owner_fiber_id') IS NULL AND jsonb_array_length(reqs)>0)
     OR NOT (budget ?& ARRAY['steps','tool_calls'])
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(budget) k
                WHERE k NOT IN ('steps','tool_calls','tokens','wall_ms')) THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  FOR b IN SELECT key,value FROM jsonb_each(budget) LOOP
    -- Numeric comparison happens only after syntax validation, and before
    -- bounded casts: arbitrarily large positive integers are W1 cap failures.
    IF jsonb_typeof(b.value) IS DISTINCT FROM 'number'
       OR (b.value #>> '{}') !~ '^[0-9]+$' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
    END IF;
    IF b.key IN ('steps','wall_ms') AND (b.value #>> '{}')::numeric < 1 THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
    END IF;
  END LOOP;
  IF (budget->>'steps')::numeric > 256
     OR (budget->>'tool_calls')::numeric > 1024
     OR (budget->>'tokens')::numeric > 1000000000000
     OR (budget->>'wall_ms')::numeric > 86400000 THEN
    fail_code := 'budget_exceeded';
  END IF;
  SELECT * INTO sc FROM v24.scopes s WHERE s.scope_id=(p->>'scope_id')::uuid;
  IF NOT FOUND OR (sc.owner_principal IS DISTINCT FROM p_principal
                  AND NOT pg_has_role(session_user,'v24_admin','USAGE')) THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('unauthorized'));
  END IF;
  IF fail_code IS NULL AND sc.close_requested_at IS NOT NULL THEN
    fail_code := 'scope_closed';
  END IF;
  IF p->>'owner_fiber_id' IS NOT NULL THEN
    SELECT * INTO f FROM v24.fibers fx WHERE fx.fiber_id=(p->>'owner_fiber_id')::uuid;
    IF NOT FOUND OR f.scope_id IS DISTINCT FROM sc.scope_id THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
    END IF;
    SELECT * INTO ep FROM v24.episodes e WHERE e.episode_id=f.current_episode_id;
    SELECT * INTO it FROM v24.installs i WHERE i.install_id=f.install_id;
    IF fail_code IS NULL AND (f.disposed_at IS NOT NULL OR NOT f.want_on
       OR ep.episode_id IS NULL OR ep.fiber_id IS DISTINCT FROM f.fiber_id
       OR ep.state IS DISTINCT FROM 'active' OR it.state IS DISTINCT FROM 'installed') THEN
      fail_code := 'provider_unavailable';
    END IF;
  END IF;
  IF fail_code IS NULL THEN
    FOR resolved IN SELECT * FROM v24.resolve(sc.scope_id,
       ARRAY(SELECT value->>'key' FROM jsonb_array_elements(reqs))) LOOP
      IF resolved.live IS DISTINCT FROM true THEN
        fail_code := 'dependency_unresolved';
        EXIT;
      END IF;
      IF NOT coalesce(p_closure->'slots' ? resolved.slot_id::text,false) THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('retry_with_closure'));
      END IF;
      pins := pins || jsonb_build_array(jsonb_build_object('pin_id',gen_random_uuid(),
        'consumer_type','run','consumer_run_id',run_id,'consumer_epoch',1,
        'key',resolved.key,'slot_id',resolved.slot_id,
        'provider_fiber_id',(SELECT s.fiber_id FROM v24.slots s WHERE s.slot_id=resolved.slot_id),
        'provider_episode_id',resolved.provider_episode_id,
        'descriptor_digest',resolved.descriptor_digest,'created_by_effect',p_effect_id));
    END LOOP;
  END IF;
  IF fail_code IS NOT NULL THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1(fail_code));
  END IF;
  -- wall_ms is optional but the frozen DDL requires a value: absent means
  -- the deployment ceiling. Keep the original budget in the model request.
  -- start's pins exist only in this delta, so the toolset digest is derived
  -- from the pending pin rows with the same key/hex ordering as model_digests.
  SELECT coalesce(jsonb_agg(jsonb_build_object('key',pn->>'key',
           'descriptor_digest',encode((pn->>'descriptor_digest')::bytea,'hex'))
           ORDER BY pn->>'key'),'[]'::jsonb)
    INTO digests
    FROM jsonb_array_elements(pins) pn;
  digests := jsonb_build_object(
    'policy',(v24.model_digests(NULL))->>'policy',
    'schema',(v24.model_digests(NULL))->>'schema',
    'toolset',encode(sha256(convert_to(digests::text,'UTF8')),'hex'));
  run_row := jsonb_build_object('run_id',run_id,'scope_id',sc.scope_id,
    'owner_fiber_id',f.fiber_id,'owner_episode_id',ep.episode_id,'status','running',
    'epoch_no',1,'registration_generation',1,'turn_no',0,'driving_generation',1,
    'remaining_steps',(budget->>'steps')::integer - 1,
    'remaining_tool_calls',(budget->>'tool_calls')::integer,
    'remaining_tokens',(budget->>'tokens')::bigint -
      v24.model_reserve((budget->>'tokens')::bigint),
    'remaining_wall_ms',coalesce((budget->>'wall_ms')::bigint,86400000),
    'revision',1,'created_at',now(),'updated_at',now());
  response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',jsonb_build_array(run_id,model_id),'revision',1,'claim',NULL);
  RETURN jsonb_build_object('write',true,
    'domain',jsonb_build_object('insert',jsonb_build_object('runs',jsonb_build_array(run_row),'pins',pins)),
    'effect',jsonb_build_object('run_id',run_id),
    'request',jsonb_build_object('response',response),
    'events',jsonb_build_array(
      jsonb_build_object('entity_type','run','entity_id',run_id,'event_kind','run_started',
        'payload',jsonb_build_object('run_id',run_id)),
      jsonb_build_object('entity_type','run','entity_id',run_id,'event_kind','model_call_requested',
        'payload',jsonb_build_object('run_id',run_id,'effect_id',model_id))),
    'successors',jsonb_build_array(jsonb_build_object('effect_id',model_id,'ordinal',0,
      'kind','model_call','run_id',run_id,'fiber_id',f.fiber_id,'episode_id',ep.episode_id,
      'epoch_no',1,'generation',1,'replay_policy','no_replay',
      'request',jsonb_build_object('run_id',run_id,'epoch_no',1,'generation',1,'input',inp,
        'budget',budget,'v',1,'cause','start',
        'reserve',jsonb_build_object('tokens',
          v24.model_reserve((budget->>'tokens')::bigint)),
        'digests',digests))));
END;
$$;

-- W5 wire format: manifest_bytes is base64 of the original UTF-8 bytes;
-- artifact_digest is PostgreSQL bytea hex (\\x...). Hash the original manifest
-- bytes, not its JSONB reserialization. Empty artifact bytes mean declaration
-- only; any provides or nonempty artifact requires host preparation.
CREATE FUNCTION v24.interpret_install(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  p jsonb := p_outcome->'body'->'payload';
  s v24.scopes%ROWTYPE;
  existing v24.installs%ROWTYPE;
  manifest_bytes bytea;
  artifact bytea;
  adapter bytea;
  parsed_manifest jsonb;
  iid uuid := gen_random_uuid();
  hid uuid := md5(p_effect_id::text || ':host_prepare:0')::uuid;
  install_state text;
  f v24.fibers%ROWTYPE;
  oe v24.episodes%ROWTYPE;
  v_owner_fid uuid;
  v_owner_eid uuid;
  v_cycle uuid[];
  fiber_row jsonb;
  r jsonb;
  response jsonb;
  successors jsonb := '[]'::jsonb;
BEGIN
  -- S2 child admission: owner is optional; JSON null means "root install".
  IF coalesce(jsonb_typeof(p->'owner_fiber_id'),'null') NOT IN ('null','string')
     OR jsonb_typeof(p->'scope_id') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p->'manifest_bytes') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p->'artifact_digest') IS DISTINCT FROM 'string' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  BEGIN
    manifest_bytes := decode(p->>'manifest_bytes','base64');
    parsed_manifest := convert_from(manifest_bytes,'UTF8')::jsonb;
    artifact := (p->>'artifact_digest')::bytea;
    IF jsonb_typeof(parsed_manifest) IS DISTINCT FROM 'object'
       OR NOT (parsed_manifest ?& ARRAY['identity','version','requires','provides','adapter_digest'])
       OR jsonb_typeof(parsed_manifest->'identity') IS DISTINCT FROM 'string'
       OR jsonb_typeof(parsed_manifest->'version') IS DISTINCT FROM 'string'
       OR length(parsed_manifest->>'identity') NOT BETWEEN 1 AND 256
       OR length(parsed_manifest->>'version') NOT BETWEEN 1 AND 64
       OR jsonb_typeof(parsed_manifest->'requires') IS DISTINCT FROM 'array'
       OR jsonb_typeof(parsed_manifest->'provides') IS DISTINCT FROM 'array'
       OR jsonb_typeof(parsed_manifest->'adapter_digest') IS DISTINCT FROM 'string'
       OR (parsed_manifest->>'adapter_digest') !~ '^\\x([0-9a-fA-F]{2})*$'
       OR (p->>'artifact_digest') !~ '^\\x([0-9a-fA-F]{2})*$' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
    END IF;
    adapter := (parsed_manifest->>'adapter_digest')::bytea;
  EXCEPTION WHEN invalid_parameter_value OR invalid_text_representation OR character_not_in_repertoire OR untranslatable_character THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END;
  -- S2: requires/provides are closed shapes; check_policy is the v1 predicate.
  IF EXISTS (
       SELECT 1 FROM jsonb_array_elements(parsed_manifest->'requires') rq
       WHERE jsonb_typeof(rq) IS DISTINCT FROM 'object'
          OR jsonb_typeof(rq->'key') IS DISTINCT FROM 'string'
          OR length(rq->>'key') NOT BETWEEN 1 AND 256
          OR (rq ? 'check_policy' AND NOT v24.check_policy_valid(rq->'check_policy')))
     OR (SELECT count(DISTINCT value->>'key')
           FROM jsonb_array_elements(parsed_manifest->'requires'))
        <> jsonb_array_length(parsed_manifest->'requires')
     OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(parsed_manifest->'provides') pv
       WHERE jsonb_typeof(pv) IS DISTINCT FROM 'object'
          OR jsonb_typeof(pv->'realm') IS DISTINCT FROM 'string'
          OR jsonb_typeof(pv->'key') IS DISTINCT FROM 'string'
          OR length(pv->>'realm') NOT BETWEEN 1 AND 128
          OR length(pv->>'key') NOT BETWEEN 1 AND 256
          OR (pv ? 'descriptor' AND jsonb_typeof(pv->'descriptor') IS DISTINCT FROM 'object'))
     OR (SELECT count(DISTINCT (value->>'realm') || chr(1) || (value->>'key'))
           FROM jsonb_array_elements(parsed_manifest->'provides'))
        <> jsonb_array_length(parsed_manifest->'provides') THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  SELECT * INTO s FROM v24.scopes WHERE scope_id=(p->>'scope_id')::uuid;
  IF NOT FOUND OR (s.owner_principal <> p_principal AND NOT pg_has_role(session_user,'v24_admin','USAGE')) THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('unauthorized'));
  END IF;
  IF s.close_requested_at IS NOT NULL THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('scope_closed'));
  END IF;
  SELECT * INTO existing FROM v24.installs WHERE scope_id=s.scope_id
    AND identity=parsed_manifest->>'identity' AND version=parsed_manifest->>'version';
  IF FOUND THEN
    IF existing.manifest_digest IS DISTINCT FROM sha256(manifest_bytes)
       OR existing.artifact_digest IS DISTINCT FROM artifact THEN
      RETURN jsonb_build_object('write',true,'error',v24.error_v1('install_identity_conflict'));
    END IF;
    response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
      'emitted',jsonb_build_array(existing.install_id),'revision',0,'claim',NULL);
    RETURN jsonb_build_object('write',true,'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),
      'request',jsonb_build_object('response',response));
  END IF;
  -- S2 child admission: owner must be live, accepting children, on an active
  -- current episode. owner_episode_id is derived, never caller-supplied.
  IF p ? 'owner_fiber_id' AND p->>'owner_fiber_id' IS NOT NULL THEN
    v_owner_fid := (p->>'owner_fiber_id')::uuid;
    SELECT * INTO f FROM v24.fibers AS fx WHERE fx.fiber_id = v_owner_fid;
    IF NOT FOUND THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
    END IF;
    IF f.disposed_at IS NOT NULL THEN
      RETURN jsonb_build_object('write',true,'error',v24.error_v1('already_terminal'));
    END IF;
    IF NOT f.want_on THEN
      RETURN jsonb_build_object('write',true,'error',v24.error_v1('owner_closing'));
    END IF;
    IF f.current_episode_id IS NULL THEN
      RETURN jsonb_build_object('write',true,'error',v24.error_v1('install_not_ready'));
    END IF;
    SELECT * INTO oe FROM v24.episodes WHERE episode_id = f.current_episode_id;
    IF NOT FOUND OR oe.fiber_id IS DISTINCT FROM f.fiber_id OR oe.state <> 'active' THEN
      RETURN jsonb_build_object('write',true,'error',v24.error_v1('install_not_ready'));
    END IF;
    v_owner_eid := f.current_episode_id;

    -- S5 W1 defensive admission check (D-S5-9/F5-A): the public path cannot
    -- construct an owner/dependency cycle, but a seeded or externally repaired
    -- graph must not accept another child into one.  The owner install's whole
    -- cleanup neighbourhood is checked after owner liveness and before any row
    -- is built or returned; an error delta is a failed command receipt only.
    v_cycle := v24.cleanup_cycle(f.install_id);
    IF cardinality(v_cycle) > 0 THEN
      RETURN jsonb_build_object('write',true,'error',v24.error_v1('cleanup_cycle',
        jsonb_build_object('path', to_jsonb(v_cycle), 'install_id', f.install_id)));
    END IF;
  END IF;
  install_state := CASE WHEN jsonb_array_length(parsed_manifest->'provides') > 0 OR octet_length(artifact) > 0
                        THEN 'preparing' ELSE 'installed' END;
  r := jsonb_build_object('install_id',iid,'scope_id',s.scope_id,
    'owner_fiber_id',v_owner_fid,'owner_episode_id',v_owner_eid,
    'identity',parsed_manifest->>'identity','version',parsed_manifest->>'version','manifest',parsed_manifest,
    'manifest_digest',sha256(manifest_bytes),'requires',parsed_manifest->'requires','provides',parsed_manifest->'provides',
    'artifact_digest',artifact,'adapter_digest',adapter,'owner_principal',p_principal,
    'state',install_state,'created_by_effect',p_effect_id);
  fiber_row := jsonb_build_object(
    'fiber_id', md5(iid::text || ':fiber')::uuid,
    'install_id', iid, 'scope_id', s.scope_id,
    'owner_fiber_id', v_owner_fid, 'owner_episode_id', v_owner_eid,
    'want_on', false, 'control_seq', 0, 'current_episode_id', NULL,
    'next_contribution_seq', 0, 'created_by_effect', p_effect_id);
  IF install_state = 'preparing' THEN
    successors := jsonb_build_array(jsonb_build_object('effect_id',hid,'ordinal',0,'kind','host_prepare',
      'request',jsonb_build_object('install_id',iid,'reservation','v24:host_prepare:' || hid::text)));
  END IF;
  response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',jsonb_build_array(iid) || CASE WHEN install_state='preparing' THEN jsonb_build_array(hid) ELSE '[]'::jsonb END,
    'revision',0,'claim',NULL);
  RETURN jsonb_build_object('write',true,
    'domain',jsonb_build_object('insert',jsonb_build_object(
      'installs',jsonb_build_array(r),'fibers',jsonb_build_array(fiber_row))),
    'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),'request',jsonb_build_object('response',response),
    'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',iid,
      'event_kind','install_admitted','payload',jsonb_build_object('state',install_state))), 'successors',successors);
END;
$$;

-- W4: fiber_control command interpretation. Reconcile is one bounded stage:
-- activation (on/retry toward on) or a deferred deactivation seam (W5).
CREATE OR REPLACE FUNCTION v24.interpret_fiber_control(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  v_p jsonb := p_outcome->'body'->'payload';
  v_f v24.fibers%ROWTYPE;
  v_i v24.installs%ROWTYPE;
  v_ep v24.episodes%ROWTYPE;
  v_scope v24.scopes%ROWTYPE;
  v_reco v24.effects%ROWTYPE;
  v_action text := v_p->>'action';
  v_target_on boolean;
  v_new_ep uuid := gen_random_uuid();
  v_epoch bigint;
  v_next_control bigint;
  v_reco_id uuid;
  v_slot_rows jsonb := '[]'::jsonb;
  v_pin_rows jsonb := '[]'::jsonb;
  v_episode_rows jsonb := '[]'::jsonb;
  v_events jsonb := '[]'::jsonb;
  v_succ jsonb := '[]'::jsonb;
  v_settle jsonb := '[]'::jsonb;
  v_ep_updates jsonb := '[]'::jsonb;
  v_slot_updates jsonb := '[]'::jsonb;
  v_pin_updates jsonb := '[]'::jsonb;
  v_barrier boolean := false;
  v_fiber_set jsonb;
  v_response jsonb;
  v_fail_code text;
  v_failure jsonb;
  v_rs record;
  v_slot_count int := 0;
  v_desc jsonb;
BEGIN
  SELECT * INTO v_f FROM v24.fibers AS fx WHERE fx.fiber_id = (v_p->>'fiber_id')::uuid;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
  END IF;
  IF (v_p->>'expected_control_seq')::bigint IS DISTINCT FROM v_f.control_seq THEN
    RETURN jsonb_build_object('write', true, 'error', v24.error_v1('stale_generation'),
      'effect', jsonb_build_object('scope_id', v_f.scope_id, 'fiber_id', v_f.fiber_id));
  END IF;
  IF v_action NOT IN ('on','off','retry') THEN
    RETURN jsonb_build_object('write', false, 'error', v24.error_v1('invalid_args'));
  END IF;

  SELECT * INTO v_reco FROM v24.effects AS ex
    WHERE ex.fiber_id = v_f.fiber_id AND ex.kind = 'fiber_reconcile' AND ex.status = 'ready'
    ORDER BY ex.created_at LIMIT 1;
  v_target_on := CASE v_action WHEN 'on' THEN true WHEN 'off' THEN false ELSE v_f.want_on END;

  IF v_action = 'retry' AND v_f.failure_seq IS NULL THEN
    RETURN v24.capability_noop(p_effect_id, v_f.scope_id, v_f.fiber_id);
  END IF;
  IF v_action = 'on' AND v_f.want_on AND v_f.current_episode_id IS NOT NULL THEN
    SELECT * INTO v_ep FROM v24.episodes AS ep WHERE ep.episode_id = v_f.current_episode_id;
    IF v_ep.state = 'active' AND v_reco.effect_id IS NULL THEN
      RETURN v24.capability_noop(p_effect_id, v_f.scope_id, v_f.fiber_id);
    END IF;
  END IF;
  IF v_action = 'off' AND NOT v_f.want_on AND v_f.current_episode_id IS NULL
     AND v_reco.effect_id IS NULL THEN
    RETURN v24.capability_noop(p_effect_id, v_f.scope_id, v_f.fiber_id);
  END IF;

  -- An intent flip during cleanup only changes want_on/control_seq; the ready
  -- reconcile keeps draining the old direction.
  IF v_reco.effect_id IS NOT NULL AND v_target_on IS DISTINCT FROM v_f.want_on THEN
    v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
      'emitted','[]'::jsonb,'revision',0,'claim',NULL);
    RETURN jsonb_build_object('write', true,
      'effect', jsonb_build_object('scope_id', v_f.scope_id, 'fiber_id', v_f.fiber_id),
      'domain', jsonb_build_object('update', jsonb_build_object('fibers', jsonb_build_array(
        jsonb_build_object('key', jsonb_build_object('fiber_id', v_f.fiber_id),
          'set', jsonb_build_object('want_on', v_target_on,
            'control_seq', v_f.control_seq + 1))))),
      'request', jsonb_build_object('response', v_response));
  END IF;

  v_next_control := v_f.control_seq + 1;
  v_reco_id := coalesce(v_reco.effect_id, md5(p_effect_id::text || ':fiber_reconcile:0')::uuid);
  v_epoch := coalesce((SELECT max(ep.epoch) FROM v24.episodes AS ep
                        WHERE ep.fiber_id = v_f.fiber_id), 0) + 1;

  IF v_target_on THEN
    IF v_f.current_episode_id IS NOT NULL THEN
      SELECT * INTO v_ep FROM v24.episodes AS ep WHERE ep.episode_id = v_f.current_episode_id;
      IF v_ep.state = 'active' THEN
        -- Already active: record the intent and finish any pending reconcile.
        v_fiber_set := jsonb_build_object('want_on', true, 'control_seq', v_next_control,
          'failure_seq', NULL, 'failure', NULL);
        IF v_reco.effect_id IS NOT NULL THEN
          v_settle := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco.effect_id, 'status', 'succeeded',
            'outcome', jsonb_build_object('v',1,'stage','activate','result','active',
              'episode_id', v_f.current_episode_id)));
        END IF;
        v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
          'emitted', jsonb_build_array(v_f.current_episode_id),'revision',0,'claim',NULL);
      ELSE
        -- Retiring/blocked generation: activation waits for W5's drain.
        v_fiber_set := jsonb_build_object('want_on', true, 'control_seq', v_next_control,
          'failure_seq', NULL, 'failure', NULL);
        IF v_reco.effect_id IS NULL THEN
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco_id, 'ordinal', 0, 'kind', 'fiber_reconcile',
            'fiber_id', v_f.fiber_id,
            'request', jsonb_build_object('fiber_id', v_f.fiber_id,
              'control_seq', v_next_control, 'action', v_action, 'stage', 'activate')));
        END IF;
        v_response := jsonb_build_object('v',1,'disposition','deferred','effect_id',p_effect_id,
          'emitted','[]'::jsonb,'revision',0,'claim',NULL);
      END IF;
    ELSE
      SELECT * INTO v_i FROM v24.installs AS it WHERE it.install_id = v_f.install_id;
      SELECT * INTO v_scope FROM v24.scopes AS sc WHERE sc.scope_id = v_f.scope_id;
      IF v_i.state IS DISTINCT FROM 'installed' THEN
        v_fail_code := 'install_not_ready';
      ELSIF v_scope.close_requested_at IS NOT NULL THEN
        v_fail_code := 'scope_closed';
      END IF;

      IF v_fail_code IS NULL THEN
        FOR v_rs IN
          SELECT req.value AS item, r.slot_id, r.provider_episode_id,
                 r.descriptor, r.descriptor_digest, r.live
          FROM jsonb_array_elements(v_i.requires) AS req
          LEFT JOIN LATERAL v24.resolve(v_f.scope_id, ARRAY[req.value->>'key']) AS r ON true
        LOOP
          IF v_rs.live IS DISTINCT FROM true
             OR NOT v24.check_policy_ok(v_rs.item->'check_policy', v_rs.descriptor) THEN
            v_fail_code := 'dependency_unresolved';
            EXIT;
          END IF;
          v_pin_rows := v_pin_rows || jsonb_build_array(jsonb_build_object(
            'pin_id', gen_random_uuid(),
            'consumer_type', 'activation',
            'consumer_episode_id', v_new_ep,
            'consumer_epoch', v_epoch,
            'key', v_rs.item->>'key',
            'slot_id', v_rs.slot_id,
            'provider_fiber_id', (SELECT sl.fiber_id FROM v24.slots AS sl
                                   WHERE sl.slot_id = v_rs.slot_id),
            'provider_episode_id', v_rs.provider_episode_id,
            'descriptor_digest', v_rs.descriptor_digest,
            'created_by_effect', v_reco_id));
        END LOOP;
      END IF;

      IF v_fail_code IS NULL THEN
        FOR v_rs IN SELECT pv.value AS item FROM jsonb_array_elements(v_i.provides) AS pv LOOP
          IF EXISTS (SELECT 1 FROM v24.slots AS sl
                      WHERE sl.realm = v_rs.item->>'realm'
                        AND sl.key = v_rs.item->>'key'
                        AND sl.released_at IS NULL) THEN
            v_fail_code := 'provide_conflict';
            EXIT;
          END IF;
        END LOOP;
      END IF;

      IF v_fail_code IS NULL THEN
        v_episode_rows := jsonb_build_array(jsonb_build_object(
          'episode_id', v_new_ep, 'fiber_id', v_f.fiber_id, 'epoch', v_epoch,
          'activation_effect', v_reco_id, 'state', 'active', 'target_seq', 0,
          'opened_at', now()));
        FOR v_rs IN SELECT pv.value AS item FROM jsonb_array_elements(v_i.provides) AS pv LOOP
          v_desc := coalesce(v_rs.item->'descriptor','{}'::jsonb);
          v_slot_rows := v_slot_rows || jsonb_build_array(jsonb_build_object(
            'slot_id', gen_random_uuid(),
            'fiber_id', v_f.fiber_id,
            'episode_id', v_new_ep,
            'realm', v_rs.item->>'realm',
            'key', v_rs.item->>'key',
            'descriptor', v_desc,
            'descriptor_digest', sha256(convert_to(v24.canonical_json(v_desc),'UTF8')),
            'contribution_seq', v_f.next_contribution_seq + v_slot_count));
          v_slot_count := v_slot_count + 1;
        END LOOP;
        v_fiber_set := jsonb_build_object(
          'current_episode_id', v_new_ep, 'want_on', true,
          'control_seq', v_next_control, 'failure_seq', NULL, 'failure', NULL,
          'next_contribution_seq', v_f.next_contribution_seq + v_slot_count);
        IF v_reco.effect_id IS NOT NULL THEN
          v_settle := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco.effect_id, 'status', 'succeeded',
            'outcome', jsonb_build_object('v',1,'stage','activate','result','active',
              'episode_id', v_new_ep)));
        ELSE
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco_id, 'ordinal', 0, 'kind', 'fiber_reconcile',
            'fiber_id', v_f.fiber_id,
            'request', jsonb_build_object('fiber_id', v_f.fiber_id,
              'control_seq', v_next_control, 'action', v_action, 'stage', 'activate'),
            'status', 'succeeded',
            'outcome', jsonb_build_object('v',1,'stage','activate','result','active',
              'episode_id', v_new_ep)));
        END IF;
        v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
          'emitted', jsonb_build_array(v_new_ep),'revision',0,'claim',NULL);
        v_events := v_events
          || jsonb_build_array(jsonb_build_object('entity_type','fiber',
               'entity_id', v_f.fiber_id, 'event_kind','fiber_activated',
               'payload', jsonb_build_object('fiber_id', v_f.fiber_id,
                 'episode_id', v_new_ep)))
          || jsonb_build_array(jsonb_build_object('entity_type','episode',
               'entity_id', v_new_ep, 'event_kind','episode_opened',
               'payload', jsonb_build_object('episode_id', v_new_ep, 'epoch', v_epoch)));
        FOR v_rs IN SELECT value AS item FROM jsonb_array_elements(v_slot_rows) LOOP
          v_events := v_events || jsonb_build_array(jsonb_build_object(
            'entity_type','slot','entity_id',(v_rs.item->>'slot_id')::uuid,
            'event_kind','slot_contributed',
            'payload', jsonb_build_object('slot_id',v_rs.item->>'slot_id',
              'realm',v_rs.item->>'realm','key',v_rs.item->>'key')));
        END LOOP;
        FOR v_rs IN SELECT value AS item FROM jsonb_array_elements(v_pin_rows) LOOP
          v_events := v_events || jsonb_build_array(jsonb_build_object(
            'entity_type','pin','entity_id',(v_rs.item->>'pin_id')::uuid,
            'event_kind','pin_created',
            'payload', jsonb_build_object('pin_id',v_rs.item->>'pin_id',
              'key',v_rs.item->>'key','slot_id',v_rs.item->>'slot_id')));
        END LOOP;
      ELSE
        v_failure := v24.error_v1(v_fail_code);
        v_fiber_set := jsonb_build_object(
          'want_on', true, 'control_seq', v_next_control,
          'failure_seq', v_next_control,
          'failure', jsonb_build_object('code', v_fail_code, 'detail', '{}'::jsonb));
        IF v_reco.effect_id IS NOT NULL THEN
          v_settle := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco.effect_id, 'status', 'failed',
            'outcome', jsonb_build_object('v',1,'stage','activate','result','failed',
              'code', v_fail_code)));
        ELSE
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco_id, 'ordinal', 0, 'kind', 'fiber_reconcile',
            'fiber_id', v_f.fiber_id,
            'request', jsonb_build_object('fiber_id', v_f.fiber_id,
              'control_seq', v_next_control, 'action', v_action, 'stage', 'activate'),
            'status', 'failed',
            'outcome', jsonb_build_object('v',1,'stage','activate','result','failed',
              'code', v_fail_code)));
        END IF;
      END IF;
    END IF;
  ELSE
    -- off: stage A retires + withdraws; stage B releases pins/slots, closes
    -- the episode and clears the current pointer.  A barrier stops after A.
    IF v_f.current_episode_id IS NULL THEN
      v_fiber_set := jsonb_build_object('want_on', false, 'control_seq', v_next_control,
        'failure_seq', NULL, 'failure', NULL);
      IF v_reco.effect_id IS NOT NULL THEN
        v_settle := jsonb_build_array(jsonb_build_object(
          'effect_id', v_reco.effect_id, 'status', 'succeeded',
          'outcome', jsonb_build_object('v',1,'stage','deactivate','result','inactive')));
      END IF;
      v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
        'emitted','[]'::jsonb,'revision',0,'claim',NULL);
    ELSE
      SELECT * INTO v_ep FROM v24.episodes AS ep WHERE ep.episode_id = v_f.current_episode_id;
      IF v_ep.state = 'active' THEN
        v_ep_updates := v_ep_updates || jsonb_build_array(jsonb_build_object(
          'key', jsonb_build_object('episode_id', v_ep.episode_id),
          'set', jsonb_build_object('state','retiring','retire_started_at', now())));
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','episode','entity_id',v_ep.episode_id,
          'event_kind','episode_retire_started',
          'payload', jsonb_build_object('episode_id',v_ep.episode_id)));
      END IF;
      FOR v_rs IN SELECT sl.slot_id FROM v24.slots AS sl
                   WHERE sl.episode_id = v_ep.episode_id
                     AND sl.withdrawn_at IS NULL AND sl.released_at IS NULL LOOP
        v_slot_updates := v_slot_updates || jsonb_build_array(jsonb_build_object(
          'key', jsonb_build_object('slot_id', v_rs.slot_id),
          'set', jsonb_build_object('withdrawn_at', now())));
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','slot','entity_id',v_rs.slot_id,
          'event_kind','slot_withdrawn',
          'payload', jsonb_build_object('slot_id',v_rs.slot_id)));
      END LOOP;

      SELECT (EXISTS (
                SELECT 1 FROM v24.pins AS p
                 WHERE p.provider_episode_id = v_ep.episode_id AND p.released_at IS NULL)
              OR EXISTS (
                SELECT 1 FROM v24.installs AS ci
                 WHERE ci.owner_fiber_id = v_f.fiber_id
                   AND ci.owner_episode_id = v_ep.episode_id
                   AND ci.state <> 'disposed')
              OR EXISTS (
                SELECT 1 FROM v24.effects AS he
                 WHERE he.kind IN ('host_prepare','host_release')
                   AND (he.request->>'install_id') = v_f.install_id::text
                   AND he.status IN ('ready','claimed')))
        INTO v_barrier;

      IF v_barrier THEN
        v_fiber_set := jsonb_build_object('want_on', false, 'control_seq', v_next_control,
          'failure_seq', NULL, 'failure', NULL);
        IF v_reco.effect_id IS NULL THEN
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco_id, 'ordinal', 0, 'kind', 'fiber_reconcile',
            'fiber_id', v_f.fiber_id,
            'request', jsonb_build_object('fiber_id', v_f.fiber_id,
              'control_seq', v_next_control, 'action', v_action, 'stage', 'deactivate')));
        END IF;
        v_response := jsonb_build_object('v',1,'disposition','deferred','effect_id',p_effect_id,
          'emitted','[]'::jsonb,'revision',0,'claim',NULL);
      ELSE
        FOR v_rs IN SELECT p.pin_id FROM v24.pins AS p
                     WHERE p.consumer_episode_id = v_ep.episode_id
                       AND p.released_at IS NULL LOOP
          v_pin_updates := v_pin_updates || jsonb_build_array(jsonb_build_object(
            'key', jsonb_build_object('pin_id', v_rs.pin_id),
            'set', jsonb_build_object('released_at', now(),
                                      'released_by_effect', v_reco_id)));
          v_events := v_events || jsonb_build_array(jsonb_build_object(
            'entity_type','pin','entity_id',v_rs.pin_id,
            'event_kind','pin_released',
            'payload', jsonb_build_object('pin_id',v_rs.pin_id)));
        END LOOP;
        FOR v_rs IN SELECT sl.slot_id FROM v24.slots AS sl
                     WHERE sl.episode_id = v_ep.episode_id AND sl.released_at IS NULL LOOP
          v_slot_updates := v_slot_updates || jsonb_build_array(jsonb_build_object(
            'key', jsonb_build_object('slot_id', v_rs.slot_id),
            'set', jsonb_build_object('released_at', now())));
          v_events := v_events || jsonb_build_array(jsonb_build_object(
            'entity_type','slot','entity_id',v_rs.slot_id,
            'event_kind','slot_released',
            'payload', jsonb_build_object('slot_id',v_rs.slot_id)));
        END LOOP;
        v_ep_updates := v_ep_updates || jsonb_build_array(jsonb_build_object(
          'key', jsonb_build_object('episode_id', v_ep.episode_id),
          'set', jsonb_build_object('state','closed','closed_at', now())));
        v_events := v_events || jsonb_build_array(jsonb_build_object(
          'entity_type','episode','entity_id',v_ep.episode_id,
          'event_kind','episode_closed',
          'payload', jsonb_build_object('episode_id',v_ep.episode_id)));
        v_fiber_set := jsonb_build_object('want_on', false, 'control_seq', v_next_control,
          'current_episode_id', NULL, 'failure_seq', NULL, 'failure', NULL);
        IF v_reco.effect_id IS NOT NULL THEN
          v_settle := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco.effect_id, 'status', 'succeeded',
            'outcome', jsonb_build_object('v',1,'stage','deactivate','result','closed',
              'episode_id', v_ep.episode_id)));
        ELSE
          v_succ := jsonb_build_array(jsonb_build_object(
            'effect_id', v_reco_id, 'ordinal', 0, 'kind', 'fiber_reconcile',
            'fiber_id', v_f.fiber_id,
            'request', jsonb_build_object('fiber_id', v_f.fiber_id,
              'control_seq', v_next_control, 'action', v_action, 'stage', 'deactivate'),
            'status','succeeded',
            'outcome', jsonb_build_object('v',1,'stage','deactivate','result','closed',
              'episode_id', v_ep.episode_id)));
        END IF;
        v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
          'emitted','[]'::jsonb,'revision',0,'claim',NULL);
      END IF;
    END IF;
  END IF;

  IF v_failure IS NOT NULL THEN
    RETURN jsonb_build_object('write', true, 'error', v_failure,
      'effect', jsonb_build_object('scope_id', v_f.scope_id, 'fiber_id', v_f.fiber_id),
      'domain', jsonb_build_object('update', jsonb_build_object('fibers', jsonb_build_array(
        jsonb_build_object('key', jsonb_build_object('fiber_id', v_f.fiber_id),
          'set', v_fiber_set)))),
      'successors', v_succ, 'settle', v_settle);
  END IF;

  RETURN jsonb_build_object('write', true,
    'effect', jsonb_build_object('scope_id', v_f.scope_id, 'fiber_id', v_f.fiber_id),
    'domain', jsonb_build_object(
      'insert', jsonb_build_object('episodes', v_episode_rows,
                                   'slots', v_slot_rows,
                                   'pins', v_pin_rows),
      'update', jsonb_build_object(
        'episodes', v_ep_updates, 'slots', v_slot_updates, 'pins', v_pin_updates,
        'fibers', jsonb_build_array(
          jsonb_build_object('key', jsonb_build_object('fiber_id', v_f.fiber_id),
            'set', v_fiber_set)))),
    'request', jsonb_build_object('response', v_response),
    'events', v_events, 'successors', v_succ, 'settle', v_settle);
END;
$$;

-- S5 W1: dispose delegates to the shared bounded stage.  The interpreter is a
-- thin mapper: no table reads beyond the root row, no inserts, no second
-- semantics.  A stage error is a failed command receipt (write:true + error,
-- like install_identity_conflict); domain updates are discarded wholesale.
CREATE OR REPLACE FUNCTION v24.interpret_dispose(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, v24 AS $$
DECLARE
  v_p jsonb := p_outcome->'body'->'payload';
  v_i v24.installs%ROWTYPE;
  v_iid uuid := (v_p->>'install_id')::uuid;
  v_stage jsonb;
  v_emitted jsonb := '[]'::jsonb;
  v_release jsonb;
  v_response jsonb;
BEGIN
  SELECT * INTO v_i FROM v24.installs AS it WHERE it.install_id = v_iid;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  IF v_i.state = 'disposed' THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('already_terminal'),
      'effect', jsonb_build_object('scope_id', v_i.scope_id));
  END IF;

  -- W1 uses the 'command' mode; W3's close phase will pass 'close' directly to
  -- the same helper.  The helper rejects 'close' as invalid_args until then.
  v_stage := v24.dispose_stage(v_iid, p_effect_id, 'command');
  IF v_stage ? 'error' THEN
    -- No domain/successors/events: the applier writes only the failed command
    -- effect and its request receipt, so the whole stage delta is discarded.
    RETURN jsonb_build_object('write',true,'error',v_stage->'error',
      'effect', jsonb_build_object('scope_id', v_i.scope_id));
  END IF;

  -- Successors are emitted in the stage's deterministic children-first order;
  -- reused ready|claimed releases/inspects appear with the same id and no new
  -- effect.
  FOR v_release IN SELECT value FROM jsonb_array_elements(
                      coalesce(v_stage->'releases','[]'::jsonb)) LOOP
    v_emitted := v_emitted || jsonb_build_array(v_release->'effect_id');
  END LOOP;
  FOR v_release IN SELECT value FROM jsonb_array_elements(
                      coalesce(v_stage->'inspects','[]'::jsonb)) LOOP
    v_emitted := v_emitted || jsonb_build_array(v_release->'effect_id');
  END LOOP;

  v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',v_emitted,'revision',0,'claim',NULL);
  RETURN jsonb_build_object('write',true,
    'effect', jsonb_build_object('scope_id', v_i.scope_id),
    'domain', jsonb_build_object('update', jsonb_build_object(
      'installs', coalesce(v_stage->'installs','[]'::jsonb),
      'fibers', coalesce(v_stage->'fibers','[]'::jsonb))),
    'request', jsonb_build_object('response', v_response),
    'events', coalesce(v_stage->'events','[]'::jsonb),
    'successors', coalesce(v_stage->'successors','[]'::jsonb));
END;
$$;

CREATE OR REPLACE FUNCTION v24.interpret_settlement(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  i v24.installs%ROWTYPE;
  t v24.effects%ROWTYPE;
  target text;
  ev jsonb := '[]'::jsonb;
  v_req jsonb;
  v_result jsonb;
  v_obs text;
  v_status text;
  v_install_set jsonb := '{}'::jsonb;
  v_events jsonb := '[]'::jsonb;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id=p_effect_id;
  IF e.kind = 'model_call' THEN
    RETURN v24.interpret_model_settlement(p_effect_id,p_principal,p_outcome,p_closure);
  ELSIF e.kind = 'tool_call' THEN
    RETURN v24.interpret_tool_settlement(p_effect_id,p_principal,p_outcome,p_closure);
  ELSIF e.kind = 'inspect_resource' THEN
    -- Structural boundary (G1-J2): a request-less or malformed inspect effect
    -- has no supported settlement path and must raise the W0 guard exactly like
    -- any other unregistered settlement handler.
    IF jsonb_typeof(e.request) IS DISTINCT FROM 'object'
       OR NOT (e.request ?& ARRAY['v','install_id','target','target_effect_id',
                                  'target_reservation','target_request_digest'])
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(e.request) k
                   WHERE k NOT IN ('v','install_id','target','target_effect_id',
                                   'target_reservation','target_request_digest'))
       OR jsonb_typeof(e.request->'v') IS DISTINCT FROM 'number'
       OR (e.request->>'v') IS DISTINCT FROM '1'
       OR jsonb_typeof(e.request->'install_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(e.request->'target') IS DISTINCT FROM 'string'
       OR (e.request->>'target') NOT IN ('host_prepare','host_release')
       OR jsonb_typeof(e.request->'target_effect_id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(e.request->'target_reservation') IS DISTINCT FROM 'string'
       OR (e.request->>'target_reservation') NOT LIKE
            'v24:' || (e.request->>'target') || ':%'
       OR jsonb_typeof(e.request->'target_request_digest') IS DISTINCT FROM 'string'
       OR (e.request->>'target_request_digest') !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_outcome->'body') IS DISTINCT FROM 'object'
       OR p_outcome->'body'->>'kind' IS DISTINCT FROM 'inspect_resource' THEN
      RAISE EXCEPTION 'v24.interpret_settlement: unsupported inspect_resource settlement'
        USING ERRCODE = '0A000';
    END IF;
    v_req := e.request;
    v_result := p_outcome->'body'->'result';
    IF jsonb_typeof(v_result) IS DISTINCT FROM 'object'
       OR (v_result->>'v') IS DISTINCT FROM '1' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    IF p_outcome->>'class' = 'success' THEN
      IF NOT (v_result ?& ARRAY['v','observed','target_effect_id','target_reservation'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_result) k
                     WHERE k NOT IN ('v','observed','target_effect_id','target_reservation'))
         OR (v_result->>'observed') NOT IN ('known','absent')
         OR (v_result->>'target_effect_id') IS DISTINCT FROM v_req->>'target_effect_id'
         OR (v_result->>'target_reservation') IS DISTINCT FROM v_req->>'target_reservation' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      v_obs := v_result->>'observed';
    ELSIF p_outcome->>'class' = 'failure' THEN
      IF NOT (v_result ?& ARRAY['v','observed'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_result) k
                     WHERE k NOT IN ('v','observed','reason'))
         OR (v_result ? 'reason' AND v_result->>'reason' IS DISTINCT FROM 'inspect_failed')
         OR (v_result->>'observed') IS DISTINCT FROM 'unknown' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      v_obs := 'unknown';
    ELSIF p_outcome->>'class' = 'unknown' THEN
      IF NOT (v_result ?& ARRAY['v','observed'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(v_result) k
                     WHERE k NOT IN ('v','observed'))
         OR (v_result->>'observed') IS DISTINCT FROM 'unknown' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      v_obs := 'unknown';
    ELSE
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END IF;
    BEGIN
      SELECT * INTO i FROM v24.installs
       WHERE install_id=(v_req->>'install_id')::uuid;
      IF NOT FOUND OR i.scope_id IS DISTINCT FROM e.scope_id THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
      SELECT * INTO t FROM v24.effects
       WHERE effect_id=(v_req->>'target_effect_id')::uuid;
      IF NOT FOUND
         OR t.kind IS DISTINCT FROM v_req->>'target'
         OR t.status IS DISTINCT FROM 'unknown'
         OR t.resource_quiesced_at IS NOT NULL
         OR (t.request->>'install_id') IS DISTINCT FROM v_req->>'install_id'
         OR (t.request->>'reservation') IS DISTINCT FROM v_req->>'target_reservation'
         OR encode(t.request_digest,'hex') IS DISTINCT FROM v_req->>'target_request_digest' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
      END IF;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
        OR invalid_parameter_value THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_outcome'));
    END;
    v_status := CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded'
                WHEN 'failure' THEN 'failed' ELSE 'unknown' END;
    -- C25 matrix: only the install transition belongs here.  Settlement emits
    -- no successors; a later command key drives the next dispose stage.
    IF v_req->>'target' = 'host_prepare' THEN
      IF p_outcome->>'class' = 'success' AND v_obs = 'known' THEN
        IF i.state NOT IN ('preparing','prepare_unknown') THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('receipt_conflict'));
        END IF;
        v_install_set := jsonb_build_object('state','installed');
      ELSIF p_outcome->>'class' = 'success' AND v_obs = 'absent' THEN
        IF i.state NOT IN ('preparing','prepare_unknown') THEN
          RETURN jsonb_build_object('write',false,'error',v24.error_v1('receipt_conflict'));
        END IF;
        v_install_set := jsonb_build_object('state','prepare_failed');
      END IF;
    ELSE
      IF i.state IS DISTINCT FROM 'dispose_pending' THEN
        RETURN jsonb_build_object('write',false,'error',v24.error_v1('receipt_conflict'));
      END IF;
      IF p_outcome->>'class' = 'success' AND v_obs = 'known' THEN
        v_install_set := jsonb_build_object('state','disposed',
                                            'disposed_at',now());
      END IF;
    END IF;
    v_events := jsonb_build_array(jsonb_build_object(
      'entity_type','install','entity_id',i.install_id,
      'event_kind','install_inspect_' || v_obs,
      'payload',jsonb_build_object('install_id',i.install_id,
        'target_effect_id',t.effect_id,'observed',v_obs)));
    IF v_install_set ? 'disposed_at' THEN
      v_events := v_events || jsonb_build_array(jsonb_build_object(
        'entity_type','install','entity_id',i.install_id,
        'event_kind','install_disposed',
        'payload',jsonb_build_object('state','disposed')));
    END IF;
    RETURN jsonb_build_object('write',true,
      'domain',jsonb_build_object('update',jsonb_build_object(
        'installs',CASE WHEN v_install_set = '{}'::jsonb THEN '[]'::jsonb
                        ELSE jsonb_build_array(jsonb_build_object(
                          'key',jsonb_build_object('install_id',i.install_id),
                          'set',v_install_set)) END,
        'effects',CASE WHEN p_outcome->>'class' = 'success'
                       THEN jsonb_build_array(jsonb_build_object(
                         'key',jsonb_build_object('effect_id',t.effect_id),
                         'set',jsonb_build_object('resource_quiesced_at',now())))
                       ELSE '[]'::jsonb END)),
      'effect',jsonb_build_object('status',v_status,'outcome',p_outcome),
      'events',v_events, 'successors','[]'::jsonb);
  ELSIF e.kind = 'host_prepare' THEN
    SELECT * INTO i FROM v24.installs WHERE install_id=(e.request->>'install_id')::uuid;
    IF NOT FOUND OR i.state <> 'preparing' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('receipt_conflict'));
    END IF;
    target := CASE p_outcome->>'class' WHEN 'success' THEN 'installed'
              WHEN 'failure' THEN 'prepare_failed' WHEN 'unknown' THEN 'prepare_unknown' END;
    ev := jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',i.install_id,
      'event_kind','host_prepare_settled','payload',jsonb_build_object('state',target)));
  ELSIF e.kind = 'host_release' THEN
    SELECT * INTO i FROM v24.installs WHERE install_id=(e.request->>'install_id')::uuid;
    IF NOT FOUND OR i.state <> 'dispose_pending' THEN
      RETURN jsonb_build_object('write',false,'error',v24.error_v1('receipt_conflict'));
    END IF;
    IF p_outcome->>'class' = 'success' THEN
      target := 'disposed';
      ev := jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',i.install_id,
        'event_kind','install_disposed','payload',jsonb_build_object('state','disposed')));
    ELSE
      -- Failure/unknown keeps dispose_pending; inspect convergence is S5.
      target := 'dispose_pending';
    END IF;
  ELSE
    RAISE EXCEPTION 'v24.interpret_settlement: no settlement handler for %', e.kind
      USING ERRCODE = '0A000';
  END IF;
  RETURN jsonb_build_object('write',true,
    'domain',jsonb_build_object('update',jsonb_build_object('installs',jsonb_build_array(
      jsonb_build_object('key',jsonb_build_object('install_id',i.install_id),
        'set',jsonb_build_object('state',target))))),
    'effect',jsonb_build_object('status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded'
      WHEN 'failure' THEN 'failed' ELSE 'unknown' END,'outcome',p_outcome),
    'events',ev, 'successors','[]'::jsonb);
END;
$$;

-- INVOKER application helper: only advance is a privileged terminal writer.
-- Settlement is inferred from outcome.class, reads kind/scope from the existing
-- effect, never inserts requests, and persists the exact incoming receipt for S2.
CREATE FUNCTION v24.validate_and_apply_install_delta(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_delta jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, v24 AS $$
DECLARE
  settling boolean := p_outcome->>'class' IN ('success','failure','unknown');
  body jsonb := p_outcome->'body';
  ins jsonb := coalesce(p_delta->'domain'->'insert','{}'::jsonb);
  upd jsonb := coalesce(p_delta->'domain'->'update','{}'::jsonb);
  events jsonb := coalesce(p_delta->'events','[]'::jsonb);
  successors jsonb := coalesce(p_delta->'successors','[]'::jsonb);
  fiber_rows jsonb := coalesce(ins->'fibers','[]'::jsonb);
  e v24.effects%ROWTYPE;
  i v24.installs%ROWTYPE;
  f v24.fibers%ROWTYPE;
  r jsonb;
  response jsonb;
  target text;
  effect_status text;
  sid uuid;
  raw bytea;
  seq bigint;
  insp_req jsonb;
  insp_result jsonb;
  insp_target v24.effects%ROWTYPE;
  insp_install v24.installs%ROWTYPE;
  insp_obs text;
  insp_status text;
  insp_install_set jsonb := '{}'::jsonb;
  insp_installs jsonb;
  insp_effects jsonb;
  insp_events jsonb;
  has_error boolean := p_delta->'error' IS NOT NULL AND p_delta->'error' <> 'null'::jsonb;
BEGIN
  IF p_delta->>'write' = 'false' THEN RETURN p_delta->'error'; END IF;
  -- S5 W2/C25 inspect settlement.  This branch deliberately lives inside the
  -- allowlisted install applier: S1's catalog gate pins the functions permitted
  -- to write v24.effects, and this commit may not edit that gate.  It applies
  -- only the matrix transition plus the inspected effect's quiescence marker;
  -- it emits no successors and leaves the inspect effect's own
  -- resource_quiesced_at NULL (unlike the generic host receipt rule).
  SELECT * INTO e FROM v24.effects WHERE effect_id=p_effect_id;
  IF e.kind = 'inspect_resource' THEN
    IF jsonb_typeof(p_delta) IS DISTINCT FROM 'object'
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta) k
                   WHERE k NOT IN ('domain','effect','events','successors','error','write'))
       OR p_delta ? 'error'
       OR jsonb_typeof(coalesce(p_delta->'domain','{}'::jsonb)) IS DISTINCT FROM 'object'
       OR coalesce(p_delta->'domain'->'insert','{}'::jsonb) <> '{}'::jsonb
       OR jsonb_typeof(coalesce(p_delta->'domain'->'update','{}'::jsonb)) IS DISTINCT FROM 'object'
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(
                    coalesce(p_delta->'domain'->'update','{}'::jsonb)) k
                   WHERE k NOT IN ('installs','effects'))
       OR jsonb_typeof(coalesce(p_delta->'events','[]'::jsonb)) IS DISTINCT FROM 'array'
       OR jsonb_typeof(coalesce(p_delta->'successors','[]'::jsonb)) IS DISTINCT FROM 'array'
       OR jsonb_array_length(coalesce(p_delta->'successors','[]'::jsonb)) <> 0
       OR jsonb_array_length(coalesce(p_delta->'events','[]'::jsonb)) > 64
       OR jsonb_typeof(p_outcome->'body') IS DISTINCT FROM 'object'
       OR p_outcome->'body'->>'kind' IS DISTINCT FROM 'inspect_resource' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    insp_req := e.request;
    IF jsonb_typeof(insp_req) IS DISTINCT FROM 'object'
       OR NOT (insp_req ?& ARRAY['v','install_id','target','target_effect_id',
                                  'target_reservation','target_request_digest'])
       OR EXISTS (SELECT 1 FROM jsonb_object_keys(insp_req) k
                   WHERE k NOT IN ('v','install_id','target','target_effect_id',
                                   'target_reservation','target_request_digest'))
       OR (insp_req->>'v') IS DISTINCT FROM '1'
       OR (insp_req->>'target') NOT IN ('host_prepare','host_release')
       OR (insp_req->>'target_request_digest') !~ '^[0-9a-f]{64}$' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    insp_result := p_outcome->'body'->'result';
    IF jsonb_typeof(insp_result) IS DISTINCT FROM 'object'
       OR (insp_result->>'v') IS DISTINCT FROM '1' THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF p_outcome->>'class' = 'success' THEN
      IF NOT (insp_result ?& ARRAY['v','observed','target_effect_id','target_reservation'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(insp_result) k
                     WHERE k NOT IN ('v','observed','target_effect_id','target_reservation'))
         OR (insp_result->>'observed') NOT IN ('known','absent')
         OR (insp_result->>'target_effect_id') IS DISTINCT FROM insp_req->>'target_effect_id'
         OR (insp_result->>'target_reservation') IS DISTINCT FROM insp_req->>'target_reservation' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      insp_obs := insp_result->>'observed';
      insp_status := 'succeeded';
    ELSIF p_outcome->>'class' = 'failure' THEN
      IF NOT (insp_result ?& ARRAY['v','observed'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(insp_result) k
                     WHERE k NOT IN ('v','observed','reason'))
         OR (insp_result ? 'reason' AND insp_result->>'reason' IS DISTINCT FROM 'inspect_failed')
         OR (insp_result->>'observed') IS DISTINCT FROM 'unknown' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      insp_obs := 'unknown';
      insp_status := 'failed';
    ELSIF p_outcome->>'class' = 'unknown' THEN
      IF NOT (insp_result ?& ARRAY['v','observed'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(insp_result) k
                     WHERE k NOT IN ('v','observed'))
         OR (insp_result->>'observed') IS DISTINCT FROM 'unknown' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      insp_obs := 'unknown';
      insp_status := 'unknown';
    ELSE
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    BEGIN
      SELECT * INTO insp_install FROM v24.installs
       WHERE install_id=(insp_req->>'install_id')::uuid;
      IF NOT FOUND OR insp_install.scope_id IS DISTINCT FROM e.scope_id THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      SELECT * INTO insp_target FROM v24.effects
       WHERE effect_id=(insp_req->>'target_effect_id')::uuid;
      IF NOT FOUND
         OR insp_target.kind IS DISTINCT FROM insp_req->>'target'
         OR insp_target.status IS DISTINCT FROM 'unknown'
         OR insp_target.resource_quiesced_at IS NOT NULL
         OR (insp_target.request->>'install_id') IS DISTINCT FROM insp_req->>'install_id'
         OR (insp_target.request->>'reservation') IS DISTINCT FROM insp_req->>'target_reservation'
         OR encode(insp_target.request_digest,'hex') IS DISTINCT FROM
              insp_req->>'target_request_digest' THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
        OR invalid_parameter_value THEN
      RETURN v24.error_v1('invalid_outcome');
    END;
    IF insp_req->>'target' = 'host_prepare' THEN
      IF p_outcome->>'class' = 'success' AND insp_obs = 'known' THEN
        IF insp_install.state NOT IN ('preparing','prepare_unknown') THEN
          RETURN v24.error_v1('receipt_conflict');
        END IF;
        insp_install_set := jsonb_build_object('state','installed');
      ELSIF p_outcome->>'class' = 'success' AND insp_obs = 'absent' THEN
        IF insp_install.state NOT IN ('preparing','prepare_unknown') THEN
          RETURN v24.error_v1('receipt_conflict');
        END IF;
        insp_install_set := jsonb_build_object('state','prepare_failed');
      END IF;
    ELSE
      IF insp_install.state IS DISTINCT FROM 'dispose_pending' THEN
        RETURN v24.error_v1('receipt_conflict');
      END IF;
      IF p_outcome->>'class' = 'success' AND insp_obs = 'known' THEN
        insp_install_set := jsonb_build_object('state','disposed',
                                               'disposed_at',now());
      END IF;
    END IF;
    insp_installs := CASE WHEN insp_install_set = '{}'::jsonb THEN '[]'::jsonb
                          ELSE jsonb_build_array(jsonb_build_object(
                            'key',jsonb_build_object('install_id',insp_install.install_id),
                            'set',insp_install_set)) END;
    insp_effects := CASE WHEN p_outcome->>'class' = 'success'
                         THEN jsonb_build_array(jsonb_build_object(
                           'key',jsonb_build_object('effect_id',insp_target.effect_id),
                           'set',jsonb_build_object('resource_quiesced_at',now())))
                         ELSE '[]'::jsonb END;
    insp_events := jsonb_build_array(jsonb_build_object(
      'entity_type','install','entity_id',insp_install.install_id,
      'event_kind','install_inspect_' || insp_obs,
      'payload',jsonb_build_object('install_id',insp_install.install_id,
        'target_effect_id',insp_target.effect_id,'observed',insp_obs)));
    IF insp_install_set ? 'disposed_at' THEN
      insp_events := insp_events || jsonb_build_array(jsonb_build_object(
        'entity_type','install','entity_id',insp_install.install_id,
        'event_kind','install_disposed',
        'payload',jsonb_build_object('state','disposed')));
    END IF;
    IF upd->'installs' IS DISTINCT FROM insp_installs
       OR upd->'effects' IS DISTINCT FROM insp_effects
       OR p_delta->'events' IS DISTINCT FROM insp_events
       OR p_delta->'effect' IS DISTINCT FROM jsonb_build_object(
            'status',insp_status,'outcome',p_outcome)
       OR NOT coalesce(p_closure->'effects' ? p_effect_id::text,false)
       OR NOT coalesce(p_closure->'effects' ? insp_target.effect_id::text,false)
       OR NOT coalesce(p_closure->'installs' ? insp_install.install_id::text,false) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
    IF insp_install_set ? 'state' THEN
      UPDATE v24.installs AS it
         SET state = insp_install_set->>'state',
             disposed_at = CASE WHEN insp_install_set ? 'disposed_at'
                                THEN now() ELSE it.disposed_at END
       WHERE it.install_id = insp_install.install_id
         AND it.state = insp_install.state;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 inspect: install changed during settlement'
          USING ERRCODE='40001';
      END IF;
    END IF;
    IF p_outcome->>'class' = 'success' THEN
      UPDATE v24.effects AS ef SET resource_quiesced_at = now()
       WHERE ef.effect_id = insp_target.effect_id
         AND ef.status = 'unknown' AND ef.resource_quiesced_at IS NULL;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v24 inspect: target quiescence changed'
          USING ERRCODE='40001';
      END IF;
    END IF;
    UPDATE v24.effects AS ef SET status = insp_status, outcome = p_outcome,
      settled_at = now(), claim_owner = NULL, lease_until = NULL,
      resource_quiesced_at = NULL
     WHERE ef.effect_id = p_effect_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'v24 inspect: effect changed during settlement'
        USING ERRCODE='40001';
    END IF;
    FOR r IN SELECT value FROM jsonb_array_elements(insp_events) LOOP
      SELECT coalesce(max(ev.seq),0)+1 INTO seq FROM v24.events ev
       WHERE ev.entity_type='install' AND ev.entity_id=(r->>'entity_id')::uuid;
      INSERT INTO v24.events(effect_id,seq,entity_type,entity_id,event_kind,
        payload,payload_digest)
      VALUES(p_effect_id,seq,'install',(r->>'entity_id')::uuid,r->>'event_kind',
        r->'payload',sha256(convert_to((r->'payload')::text,'UTF8')));
    END LOOP;
    RETURN jsonb_build_object('v',1,'disposition','committed',
      'effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,'claim',NULL);
  END IF;
  IF jsonb_typeof(p_delta) IS DISTINCT FROM 'object'
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta) k WHERE k NOT IN ('domain','effect','request','events','successors','error','write'))
     OR jsonb_typeof(ins) IS DISTINCT FROM 'object' OR jsonb_typeof(upd) IS DISTINCT FROM 'object'
     OR jsonb_typeof(events) IS DISTINCT FROM 'array' OR jsonb_typeof(successors) IS DISTINCT FROM 'array'
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(ins) k WHERE k NOT IN ('installs','fibers'))
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(upd) k WHERE k <> 'installs') THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_typeof(coalesce(ins->'installs','[]'::jsonb)) IS DISTINCT FROM 'array'
     OR jsonb_typeof(fiber_rows) IS DISTINCT FROM 'array'
     OR jsonb_typeof(coalesce(upd->'installs','[]'::jsonb)) IS DISTINCT FROM 'array' THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_array_length(coalesce(ins->'installs','[]'::jsonb)) > 1
     OR jsonb_array_length(fiber_rows) <> jsonb_array_length(coalesce(ins->'installs','[]'::jsonb)) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_array_length(coalesce(ins->'installs','[]'::jsonb)) + jsonb_array_length(coalesce(upd->'installs','[]'::jsonb)) > 16
     OR jsonb_array_length(events) > 64 OR jsonb_array_length(successors) > 16
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(events) ev GROUP BY ev->>'entity_type',ev->>'entity_id',ev->>'event_kind' HAVING count(*)>1)
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(successors) su GROUP BY su->>'ordinal' HAVING count(*)>1)
     OR (p_outcome->>'class'='unknown' AND jsonb_array_length(successors)>0) THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF settling THEN
    SELECT * INTO e FROM v24.effects WHERE effect_id=p_effect_id;
    IF e.kind NOT IN ('host_prepare','host_release') THEN
      RAISE EXCEPTION 'v24.validate_and_apply_delta: no footprint for %',e.kind USING ERRCODE='0A000';
    END IF;
    sid := e.scope_id;
    SELECT * INTO i FROM v24.installs WHERE install_id=(e.request->>'install_id')::uuid;
    IF e.kind = 'host_prepare' THEN
      IF i.state IS DISTINCT FROM 'preparing' THEN RETURN v24.error_v1('receipt_conflict'); END IF;
      target := CASE p_outcome->>'class' WHEN 'success' THEN 'installed' WHEN 'failure' THEN 'prepare_failed' ELSE 'prepare_unknown' END;
    ELSE
      IF i.state IS DISTINCT FROM 'dispose_pending' THEN RETURN v24.error_v1('receipt_conflict'); END IF;
      target := CASE p_outcome->>'class' WHEN 'success' THEN 'disposed' ELSE 'dispose_pending' END;
    END IF;
    effect_status := CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded' WHEN 'failure' THEN 'failed' ELSE 'unknown' END;
    IF has_error OR p_delta ? 'request' OR ins <> '{}'::jsonb
       OR upd IS DISTINCT FROM jsonb_build_object('installs',jsonb_build_array(jsonb_build_object(
            'key',jsonb_build_object('install_id',i.install_id),'set',jsonb_build_object('state',target))))
       OR p_delta->'effect' IS DISTINCT FROM jsonb_build_object('status',effect_status,'outcome',p_outcome)
       OR jsonb_array_length(successors)<>0
       OR NOT coalesce(p_closure->'installs' ? i.install_id::text,false) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  ELSE
    sid := (body->'payload'->>'scope_id')::uuid;
    effect_status := CASE WHEN has_error THEN 'failed' ELSE 'succeeded' END;
    IF upd <> '{}'::jsonb OR jsonb_array_length(coalesce(ins->'installs','[]'::jsonb)) > 1
       OR jsonb_array_length(successors)>1
       OR (has_error AND (ins <> '{}'::jsonb OR successors <> '[]'::jsonb OR events <> '[]'::jsonb))
       OR (NOT has_error AND p_delta->'effect' IS DISTINCT FROM jsonb_build_object('status','succeeded','outcome',p_outcome)) THEN
      RETURN v24.error_v1('invalid_outcome');
    END IF;
  END IF;
  -- Preflight every typed row/field before DML. Bad casts are delta rejection;
  -- actual DML/trigger/constraint errors below propagate and roll back (W2).
  BEGIN
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(ins->'installs','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR NOT (r ?& ARRAY['install_id','scope_id','identity','version','manifest','manifest_digest','requires','provides','artifact_digest','adapter_digest','owner_principal','state','created_by_effect'])
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN ('install_id','scope_id','owner_fiber_id','owner_episode_id','identity','version','manifest','manifest_digest','requires','provides','artifact_digest','adapter_digest','owner_principal','state','created_by_effect')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      SELECT * INTO i FROM jsonb_populate_record(NULL::v24.installs,r);
      IF i.install_id IS NULL OR i.scope_id IS DISTINCT FROM sid
         OR (i.owner_fiber_id IS NULL) <> (i.owner_episode_id IS NULL)
         OR (i.owner_fiber_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM v24.fibers f0
              JOIN v24.episodes e0 ON e0.episode_id = f0.current_episode_id
              WHERE f0.fiber_id = i.owner_fiber_id
                AND f0.current_episode_id = i.owner_episode_id
                AND e0.fiber_id = f0.fiber_id
                AND f0.want_on AND f0.disposed_at IS NULL AND e0.state = 'active'))
         OR i.owner_principal IS DISTINCT FROM p_principal OR i.created_by_effect IS DISTINCT FROM p_effect_id
         OR i.identity IS NULL OR length(i.identity) NOT BETWEEN 1 AND 256
         OR i.version IS NULL OR length(i.version) NOT BETWEEN 1 AND 64
         OR jsonb_typeof(i.manifest) IS DISTINCT FROM 'object'
         OR jsonb_typeof(i.requires) IS DISTINCT FROM 'array' OR jsonb_typeof(i.provides) IS DISTINCT FROM 'array'
         OR i.manifest_digest IS NULL OR i.artifact_digest IS NULL OR i.adapter_digest IS NULL
         OR i.state IS NULL OR i.state NOT IN ('preparing','installed') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    -- Exactly one inactive fiber per new install; deterministic identity.
    FOR r IN SELECT value FROM jsonb_array_elements(fiber_rows) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN
              ('fiber_id','install_id','scope_id','owner_fiber_id','owner_episode_id',
               'want_on','control_seq','current_episode_id','next_contribution_seq','created_by_effect')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
      SELECT * INTO f FROM jsonb_populate_record(NULL::v24.fibers,r);
      IF f.fiber_id IS DISTINCT FROM md5(i.install_id::text || ':fiber')::uuid
         OR f.install_id IS DISTINCT FROM i.install_id
         OR f.scope_id IS DISTINCT FROM sid
         OR f.owner_fiber_id IS DISTINCT FROM i.owner_fiber_id
         OR f.owner_episode_id IS DISTINCT FROM i.owner_episode_id
         OR f.want_on IS DISTINCT FROM false
         OR f.control_seq <> 0 OR f.next_contribution_seq <> 0
         OR f.current_episode_id IS NOT NULL
         OR f.disposed_at IS NOT NULL OR f.failure IS NOT NULL OR f.failure_seq IS NOT NULL
         OR f.created_by_effect IS DISTINCT FROM p_effect_id THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(events) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN ('entity_type','entity_id','event_kind','payload','payload_digest'))
         OR r->>'entity_type' IS DISTINCT FROM 'install' OR (r->>'entity_id')::uuid IS DISTINCT FROM i.install_id
         OR coalesce(length(r->>'event_kind'),0)=0 OR jsonb_typeof(r->'payload') IS DISTINCT FROM 'object'
         OR (r ? 'payload_digest' AND (r->>'payload_digest')::bytea IS DISTINCT FROM sha256(convert_to((r->'payload')::text,'UTF8'))) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(successors) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object'
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r) k WHERE k NOT IN ('effect_id','ordinal','kind','request'))
         OR (r->>'effect_id')::uuid IS DISTINCT FROM md5(p_effect_id::text || ':host_prepare:0')::uuid
         OR r->'ordinal' IS DISTINCT FROM '0'::jsonb OR r->>'kind' IS DISTINCT FROM 'host_prepare'
         OR i.state IS DISTINCT FROM 'preparing'
         OR r->'request' IS DISTINCT FROM jsonb_build_object('install_id',i.install_id,'reservation','v24:host_prepare:' || (r->>'effect_id')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
  EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR numeric_value_out_of_range OR datetime_field_overflow THEN
    RETURN v24.error_v1('invalid_outcome');
  END;
  response := CASE WHEN has_error THEN p_delta->'error' ELSE p_delta->'request'->'response' END;
  IF response IS NULL THEN
    response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,'claim',NULL);
  END IF;
  -- domain -> existing/new effect -> command request only -> events -> successors.
  FOR r IN SELECT value FROM jsonb_array_elements(coalesce(ins->'installs','[]'::jsonb)) LOOP
    INSERT INTO v24.installs SELECT * FROM jsonb_populate_record(NULL::v24.installs,r);
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(fiber_rows) LOOP
    INSERT INTO v24.fibers SELECT * FROM jsonb_populate_record(NULL::v24.fibers,r);
  END LOOP;
  IF settling THEN
    UPDATE v24.installs SET state=target,
      disposed_at = CASE WHEN target = 'disposed' THEN now() ELSE disposed_at END
    WHERE install_id=i.install_id AND state=i.state;
    UPDATE v24.effects SET status=effect_status,outcome=p_outcome,settled_at=now(),claim_owner=NULL,lease_until=NULL,
      resource_quiesced_at=CASE WHEN p_outcome->>'class' IN ('success','failure') THEN now() ELSE NULL END
      WHERE effect_id=p_effect_id;
  ELSE
    raw := decode(body->>'canonical_bytes','base64');
    INSERT INTO v24.effects(effect_id,requester_id,request_key,scope_id,kind,status,request,request_digest,replay_policy,outcome,settled_at)
      VALUES(p_effect_id,p_principal,body->>'request_key',sid,'command_install',effect_status,p_outcome,sha256(raw),'replay_safe',p_outcome,now());
    INSERT INTO v24.requests(principal_id,request_key,kind,request_bytes,request_digest,effect_id,response)
      VALUES(p_principal,body->>'request_key','command_install',raw,sha256(raw),p_effect_id,response);
  END IF;
  FOR r IN SELECT value FROM jsonb_array_elements(events) LOOP
    SELECT coalesce(max(ev.seq),0)+1 INTO seq FROM v24.events ev WHERE entity_type='install' AND entity_id=(r->>'entity_id')::uuid;
    INSERT INTO v24.events(effect_id,seq,entity_type,entity_id,event_kind,payload,payload_digest)
      VALUES(p_effect_id,seq,'install',(r->>'entity_id')::uuid,r->>'event_kind',r->'payload',sha256(convert_to((r->'payload')::text,'UTF8')));
  END LOOP;
  FOR r IN SELECT value FROM jsonb_array_elements(successors) LOOP
    INSERT INTO v24.effects(effect_id,parent_effect_id,ordinal,requester_id,scope_id,kind,status,request,request_digest,replay_policy)
      VALUES((r->>'effect_id')::uuid,p_effect_id,(r->>'ordinal')::int,p_principal,sid,r->>'kind','ready',r->'request',sha256(convert_to((r->'request')::text,'UTF8')),'replay_safe');
  END LOOP;
  RETURN response;
END;
$$;

-- W6 closes W4's missing wrapper: construct only; advance owns all writes/locks.
CREATE FUNCTION v24.scope_control(p_action text, p_parent_scope_id uuid,
  p_realm_routes jsonb, p_default_realm text, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, v24 AS $$
DECLARE
  payload jsonb := jsonb_build_object('action',p_action);
BEGIN
  IF p_parent_scope_id IS NOT NULL THEN
    payload := payload || jsonb_build_object('parent_scope_id',p_parent_scope_id);
  END IF;
  -- close accepts no routing fields; non-null inputs still reach validation.
  IF p_action <> 'close' OR p_realm_routes IS NOT NULL THEN
    payload := payload || jsonb_build_object('realm_routes',coalesce(p_realm_routes,'{}'::jsonb));
  END IF;
  IF p_action <> 'close' OR p_default_realm IS NOT NULL THEN
    payload := payload || jsonb_build_object('default_realm',p_default_realm);
  END IF;
  RETURN v24.advance(v24.effect_id_for(v24.principal_id(session_user),p_request_key,'command_scope_control'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object('op','admit_and_apply',
      'kind','command_scope_control','request_key',p_request_key,'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;

CREATE FUNCTION v24.install(p_scope_id uuid, p_owner_fiber_id uuid,
  p_manifest_bytes bytea, p_artifact_digest bytea, p_request_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, v24 AS $$
DECLARE
  payload jsonb := jsonb_build_object('scope_id',p_scope_id,'owner_fiber_id',p_owner_fiber_id,
    'manifest_bytes',encode(p_manifest_bytes,'base64'),'artifact_digest',p_artifact_digest);
BEGIN
  RETURN v24.advance(v24.effect_id_for(v24.principal_id(session_user),p_request_key,'command_install'),
    jsonb_build_object('v',1,'class','command','claim',NULL,'body',jsonb_build_object('op','admit_and_apply',
      'kind','command_install','request_key',p_request_key,'payload',payload,
      'canonical_bytes',encode(convert_to(v24.canonical_json(payload),'UTF8'),'base64'))));
END;
$$;

