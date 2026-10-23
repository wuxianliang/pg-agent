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
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
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
BEGIN
  -- W5 mode is inferred from the authenticated outcome class, never the delta.
  -- Leave the W4 scope-command path below unchanged.
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
  ELSE
    RAISE EXCEPTION 'v24.validate_and_apply_delta: no footprint for %', kind
      USING ERRCODE = '0A000';
  END IF;
  IF (SELECT coalesce(sum(jsonb_array_length(value)),0) FROM jsonb_each(inserts)) > 16
     OR (SELECT coalesce(sum(jsonb_array_length(value)),0) FROM jsonb_each(updates)) > 16
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

  -- S2: successor shape, born-settled and attribution are closed contracts.
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
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'installs','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR (r->'key'->>'install_id')::uuid IS DISTINCT FROM (body->'payload'->>'install_id')::uuid
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('state','dispose_effect'))
         OR (r->'set' ? 'state' AND r->'set'->>'state' IS DISTINCT FROM 'dispose_pending') THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'fibers','[]'::jsonb)) LOOP
      IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR NOT (r ?& ARRAY['key','set'])
         OR NOT EXISTS (SELECT 1 FROM v24.fibers f
                         WHERE f.fiber_id = (r->'key'->>'fiber_id')::uuid
                           AND f.install_id = (body->'payload'->>'install_id')::uuid)
         OR EXISTS (SELECT 1 FROM jsonb_object_keys(r->'set') k
                    WHERE k NOT IN ('disposed_at','want_on')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'successors','[]'::jsonb)) LOOP
      IF r->>'kind' IS DISTINCT FROM 'host_release'
         OR (r->>'effect_id')::uuid IS DISTINCT FROM
            md5(p_effect_id::text || ':host_release:0')::uuid
         OR r->'ordinal' IS DISTINCT FROM '0'::jsonb
         OR r->'request' IS DISTINCT FROM jsonb_build_object(
              'install_id', (body->'payload'->>'install_id')::uuid,
              'reservation', 'v24:host_release:' || (r->>'effect_id')) THEN
        RETURN v24.error_v1('invalid_outcome');
      END IF;
    END LOOP;
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(p_delta->'events','[]'::jsonb)) LOOP
      IF (r->>'entity_type') IS DISTINCT FROM 'install'
         OR (r->>'entity_id')::uuid IS DISTINCT FROM (body->'payload'->>'install_id')::uuid
         OR r->>'event_kind' NOT IN ('install_dispose_pending','install_release_requested') THEN
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

  IF scope_id IS NULL THEN
    BEGIN scope_id := (body->'payload'->>'scope_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN NULL; END;
  END IF;
  IF kind = 'command_dispose' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(coalesce(updates->'installs','[]'::jsonb)) LOOP
      UPDATE v24.installs AS it SET
        state = CASE WHEN (r->'set') ? 'state' THEN r->'set'->>'state' ELSE it.state END,
        dispose_effect = CASE WHEN (r->'set') ? 'dispose_effect'
              THEN (r->'set'->>'dispose_effect')::uuid ELSE it.dispose_effect END
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

  INSERT INTO v24.effects(effect_id,requester_id,request_key,scope_id,fiber_id,episode_id,kind,status,request,request_digest,replay_policy,outcome,settled_at)
  VALUES(p_effect_id,p_principal,body->>'request_key',
    coalesce(scope_id,(p_delta->'effect'->>'scope_id')::uuid),
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
    INSERT INTO v24.effects(effect_id,parent_effect_id,ordinal,requester_id,scope_id,fiber_id,kind,status,request,request_digest,replay_policy,outcome,settled_at)
    VALUES(new_id,p_effect_id,(succ->>'ordinal')::int,p_principal,scope_id,
      (succ->>'fiber_id')::uuid,succ->>'kind',coalesce(succ->>'status','ready'),
      coalesce(succ->'request','{}'::jsonb),sha256(convert_to(coalesce(succ->'request','{}'::jsonb)::text,'UTF8')),'replay_safe',
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

-- W6: leaf dispose. The command only persists the intent and, once every
-- obligation is clear, tombstones the install's own fibers and emits one
-- host_release.  inspect convergence for preparing/prepare_unknown stays S5.
CREATE OR REPLACE FUNCTION v24.interpret_dispose(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  v_p jsonb := p_outcome->'body'->'payload';
  v_i v24.installs%ROWTYPE;
  v_iid uuid := (v_p->>'install_id')::uuid;
  v_rel uuid := md5(p_effect_id::text || ':host_release:0')::uuid;
  v_existing uuid;
  v_set jsonb := '{}'::jsonb;
  v_fiber_updates jsonb := '[]'::jsonb;
  v_events jsonb := '[]'::jsonb;
  v_succ jsonb := '[]'::jsonb;
  v_blocked boolean := false;
  v_response jsonb;
  v_rec record;
BEGIN
  SELECT * INTO v_i FROM v24.installs AS it WHERE it.install_id = v_iid;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('invalid_args'));
  END IF;
  IF v_i.state = 'disposed' THEN
    RETURN jsonb_build_object('write',true,'error',v24.error_v1('already_terminal'),
      'effect', jsonb_build_object('scope_id', v_i.scope_id));
  END IF;

  IF v_i.state <> 'dispose_pending' THEN
    v_set := jsonb_build_object('state','dispose_pending','dispose_effect',p_effect_id);
    v_events := v_events || jsonb_build_array(jsonb_build_object(
      'entity_type','install','entity_id',v_i.install_id,
      'event_kind','install_dispose_pending',
      'payload', jsonb_build_object('install_id',v_i.install_id)));
  END IF;

  -- preparing/prepare_unknown cannot cross the owner barrier without an
  -- inspect on the same reservation; S2 only persists the intent.
  IF v_i.state IN ('preparing','prepare_unknown') THEN
    v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
      'emitted','[]'::jsonb,'revision',0,'claim',NULL);
    RETURN jsonb_build_object('write',true,
      'effect', jsonb_build_object('scope_id', v_i.scope_id),
      'domain', jsonb_build_object('update', jsonb_build_object(
        'installs', CASE WHEN v_set = '{}'::jsonb THEN '[]'::jsonb
                         ELSE jsonb_build_array(jsonb_build_object(
                           'key', jsonb_build_object('install_id', v_i.install_id),
                           'set', v_set)) END,
        'fibers', '[]'::jsonb)),
      'request', jsonb_build_object('response', v_response),
      'events', v_events, 'successors', '[]'::jsonb);
  END IF;

  v_blocked := EXISTS (
      SELECT 1 FROM v24.fibers AS f
      WHERE f.install_id = v_iid
        AND (f.current_episode_id IS NOT NULL
             OR EXISTS (SELECT 1 FROM v24.episodes AS e
                         WHERE e.fiber_id = f.fiber_id AND e.state <> 'closed')))
    OR EXISTS (
      SELECT 1 FROM v24.fibers AS f
      JOIN v24.slots AS s ON s.fiber_id = f.fiber_id
      WHERE f.install_id = v_iid AND s.released_at IS NULL)
    OR EXISTS (
      SELECT 1 FROM v24.installs AS ci
      WHERE ci.owner_fiber_id IN (SELECT f.fiber_id FROM v24.fibers AS f
                                   WHERE f.install_id = v_iid)
        AND ci.state <> 'disposed')
    OR EXISTS (
      SELECT 1 FROM v24.effects AS he
      WHERE (he.request->>'install_id') = v_iid::text
        AND he.status IN ('ready','claimed'));

  IF v_blocked THEN
    v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
      'emitted','[]'::jsonb,'revision',0,'claim',NULL);
    RETURN jsonb_build_object('write',true,
      'effect', jsonb_build_object('scope_id', v_i.scope_id),
      'domain', jsonb_build_object('update', jsonb_build_object(
        'installs', CASE WHEN v_set = '{}'::jsonb THEN '[]'::jsonb
                         ELSE jsonb_build_array(jsonb_build_object(
                           'key', jsonb_build_object('install_id', v_i.install_id),
                           'set', v_set)) END,
        'fibers', '[]'::jsonb)),
      'request', jsonb_build_object('response', v_response),
      'events', v_events, 'successors', '[]'::jsonb);
  END IF;

  SELECT he.effect_id INTO v_existing FROM v24.effects AS he
    WHERE (he.request->>'install_id') = v_iid::text
      AND he.kind = 'host_release' AND he.status IN ('ready','claimed')
    ORDER BY he.created_at LIMIT 1;

  IF v_existing IS NULL THEN
    FOR v_rec IN SELECT f.fiber_id FROM v24.fibers AS f
                  WHERE f.install_id = v_iid AND f.disposed_at IS NULL LOOP
      v_fiber_updates := v_fiber_updates || jsonb_build_array(jsonb_build_object(
        'key', jsonb_build_object('fiber_id', v_rec.fiber_id),
        'set', jsonb_build_object('disposed_at', now(), 'want_on', false)));
    END LOOP;
    v_succ := jsonb_build_array(jsonb_build_object(
      'effect_id', v_rel, 'ordinal', 0, 'kind', 'host_release',
      'request', jsonb_build_object('install_id', v_i.install_id,
        'reservation', 'v24:host_release:' || v_rel::text)));
    v_events := v_events || jsonb_build_array(jsonb_build_object(
      'entity_type','install','entity_id',v_i.install_id,
      'event_kind','install_release_requested',
      'payload', jsonb_build_object('install_id',v_i.install_id,
        'release_effect_id', v_rel)));
  END IF;

  v_response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted', CASE WHEN v_existing IS NULL THEN jsonb_build_array(v_rel)
                    ELSE jsonb_build_array(v_existing) END,
    'revision',0,'claim',NULL);
  RETURN jsonb_build_object('write',true,
    'effect', jsonb_build_object('scope_id', v_i.scope_id),
    'domain', jsonb_build_object('update', jsonb_build_object(
      'installs', CASE WHEN v_set = '{}'::jsonb THEN '[]'::jsonb
                       ELSE jsonb_build_array(jsonb_build_object(
                         'key', jsonb_build_object('install_id', v_i.install_id),
                         'set', v_set)) END,
      'fibers', v_fiber_updates)),
    'request', jsonb_build_object('response', v_response),
    'events', v_events, 'successors', v_succ);
END;
$$;

CREATE OR REPLACE FUNCTION v24.interpret_settlement(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  i v24.installs%ROWTYPE;
  target text;
  ev jsonb := '[]'::jsonb;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id=p_effect_id;
  IF e.kind = 'host_prepare' THEN
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
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
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
  has_error boolean := p_delta->'error' IS NOT NULL AND p_delta->'error' <> 'null'::jsonb;
BEGIN
  IF p_delta->>'write' = 'false' THEN RETURN p_delta->'error'; END IF;
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

