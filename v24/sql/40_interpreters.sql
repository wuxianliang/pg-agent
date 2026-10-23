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
  k text;
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
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_delta) x WHERE x NOT IN ('domain','effect','request','events','successors','error','write'))
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
  IF scope_id IS NULL THEN
    BEGIN scope_id := (body->'payload'->>'scope_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN NULL; END;
  END IF;
  INSERT INTO v24.effects(effect_id,requester_id,request_key,scope_id,kind,status,request,request_digest,replay_policy,outcome,settled_at)
  VALUES(p_effect_id,p_principal,body->>'request_key',scope_id,kind,status,p_outcome,request_digest,'replay_safe',outcome,now());
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
    INSERT INTO v24.effects(effect_id,parent_effect_id,ordinal,requester_id,scope_id,kind,status,request,request_digest,replay_policy)
    VALUES(new_id,p_effect_id,(succ->>'ordinal')::int,p_principal,scope_id,succ->>'kind','ready',
      coalesce(succ->'request','{}'::jsonb),sha256(convert_to(coalesce(succ->'request','{}'::jsonb)::text,'UTF8')),'replay_safe');
    emitted := emitted || jsonb_build_array(new_id);
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
  r jsonb;
  response jsonb;
  successors jsonb := '[]'::jsonb;
BEGIN
  -- Child admission is deliberately absent in S1, always W0.
  IF p->>'owner_fiber_id' IS NOT NULL
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
  install_state := CASE WHEN jsonb_array_length(parsed_manifest->'provides') > 0 OR octet_length(artifact) > 0
                        THEN 'preparing' ELSE 'installed' END;
  r := jsonb_build_object('install_id',iid,'scope_id',s.scope_id,'owner_fiber_id',NULL,'owner_episode_id',NULL,
    'identity',parsed_manifest->>'identity','version',parsed_manifest->>'version','manifest',parsed_manifest,
    'manifest_digest',sha256(manifest_bytes),'requires',parsed_manifest->'requires','provides',parsed_manifest->'provides',
    'artifact_digest',artifact,'adapter_digest',adapter,'owner_principal',p_principal,
    'state',install_state,'created_by_effect',p_effect_id);
  IF install_state = 'preparing' THEN
    successors := jsonb_build_array(jsonb_build_object('effect_id',hid,'ordinal',0,'kind','host_prepare',
      'request',jsonb_build_object('install_id',iid,'reservation','v24:host_prepare:' || hid::text)));
  END IF;
  response := jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
    'emitted',jsonb_build_array(iid) || CASE WHEN install_state='preparing' THEN jsonb_build_array(hid) ELSE '[]'::jsonb END,
    'revision',0,'claim',NULL);
  RETURN jsonb_build_object('write',true,'domain',jsonb_build_object('insert',jsonb_build_object('installs',jsonb_build_array(r))),
    'effect',jsonb_build_object('status','succeeded','outcome',p_outcome),'request',jsonb_build_object('response',response),
    'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',iid,
      'event_kind','install_admitted','payload',jsonb_build_object('state',install_state))), 'successors',successors);
END;
$$;

CREATE OR REPLACE FUNCTION v24.interpret_settlement(p_effect_id uuid, p_principal uuid,
  p_outcome jsonb, p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path = pg_catalog, v24 AS $$
DECLARE
  e v24.effects%ROWTYPE;
  i v24.installs%ROWTYPE;
  target text;
BEGIN
  SELECT * INTO e FROM v24.effects WHERE effect_id=p_effect_id;
  IF e.kind IS DISTINCT FROM 'host_prepare' THEN
    RAISE EXCEPTION 'v24.interpret_settlement: no settlement handler for %', e.kind USING ERRCODE='0A000';
  END IF;
  SELECT * INTO i FROM v24.installs WHERE install_id=(e.request->>'install_id')::uuid;
  IF NOT FOUND OR i.state <> 'preparing' THEN
    RETURN jsonb_build_object('write',false,'error',v24.error_v1('receipt_conflict'));
  END IF;
  target := CASE p_outcome->>'class' WHEN 'success' THEN 'installed'
            WHEN 'failure' THEN 'prepare_failed' WHEN 'unknown' THEN 'prepare_unknown' END;
  RETURN jsonb_build_object('write',true,
    'domain',jsonb_build_object('update',jsonb_build_object('installs',jsonb_build_array(
      jsonb_build_object('key',jsonb_build_object('install_id',i.install_id),'set',jsonb_build_object('state',target))))),
    'effect',jsonb_build_object('status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded'
      WHEN 'failure' THEN 'failed' ELSE 'unknown' END,'outcome',p_outcome),
    'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',i.install_id,
      'event_kind','host_prepare_settled','payload',jsonb_build_object('state',target))), 'successors','[]'::jsonb);
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
  e v24.effects%ROWTYPE;
  i v24.installs%ROWTYPE;
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
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(ins) k WHERE k <> 'installs')
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(upd) k WHERE k <> 'installs') THEN
    RETURN v24.error_v1('invalid_outcome');
  END IF;
  IF jsonb_typeof(coalesce(ins->'installs','[]'::jsonb)) IS DISTINCT FROM 'array'
     OR jsonb_typeof(coalesce(upd->'installs','[]'::jsonb)) IS DISTINCT FROM 'array' THEN
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
    IF e.kind IS DISTINCT FROM 'host_prepare' THEN
      RAISE EXCEPTION 'v24.validate_and_apply_delta: no footprint for %',e.kind USING ERRCODE='0A000';
    END IF;
    sid := e.scope_id;
    SELECT * INTO i FROM v24.installs WHERE install_id=(e.request->>'install_id')::uuid;
    IF i.state IS DISTINCT FROM 'preparing' THEN RETURN v24.error_v1('receipt_conflict'); END IF;
    target := CASE p_outcome->>'class' WHEN 'success' THEN 'installed' WHEN 'failure' THEN 'prepare_failed' ELSE 'prepare_unknown' END;
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
      IF i.install_id IS NULL OR i.scope_id IS DISTINCT FROM sid OR i.owner_fiber_id IS NOT NULL OR i.owner_episode_id IS NOT NULL
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
  IF settling THEN
    UPDATE v24.installs SET state=target WHERE install_id=i.install_id AND state='preparing';
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

