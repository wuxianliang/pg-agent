-- Cordis v2 DP4 run loop: run_start production/settlement (W1).
CREATE FUNCTION v24_cordis.run_policy() RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('v',1,'max_steps',64,'max_state_bytes',65536,
  'max_tool_calls',16,'max_successors',16,'max_run_pins',32)
$$;
CREATE FUNCTION v24_cordis.chat_tool_schema() RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('v',1,'name','chat_tool_v1',
  'fields',jsonb_build_array('text','tool_calls','interaction','final','usage'))
$$;
CREATE FUNCTION v24_cordis.run_state_valid(p_state jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(v24_cordis.exact_keys(p_state,ARRAY['v','origin','step','phase','batch','final'])
  AND p_state->'v'='1'::jsonb AND v24_cordis.json_uuid(p_state->'origin')
  AND v24_cordis.json_int(p_state->'step',0,64)
  AND p_state->>'phase' IN ('model','tools','sealed')
  AND jsonb_typeof(p_state->'final')='boolean'
  AND jsonb_typeof(p_state->'batch')='array' AND jsonb_array_length(p_state->'batch')<=16
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_state->'batch') x
   WHERE NOT coalesce(v24_cordis.exact_keys(x,ARRAY['ordinal','key','call_id']),false)
    OR NOT v24_cordis.json_int(x->'ordinal',0,15)
    OR NOT v24_cordis.json_text(x->'key') OR NOT v24_cordis.json_text(x->'call_id'))
  AND (SELECT count(DISTINCT x->>'ordinal') FROM jsonb_array_elements(p_state->'batch') x)
    =jsonb_array_length(p_state->'batch')
  AND (SELECT count(DISTINCT x->>'key') FROM jsonb_array_elements(p_state->'batch') x)
    =jsonb_array_length(p_state->'batch')
  AND (SELECT count(DISTINCT x->>'call_id') FROM jsonb_array_elements(p_state->'batch') x)
    =jsonb_array_length(p_state->'batch')
  AND octet_length(p_state::text)<=(v24_cordis.run_policy()->>'max_state_bytes')::int
  AND (p_state->>'phase'<>'model' OR p_state->'batch'='[]'::jsonb)
  AND (p_state->>'phase'<>'sealed' OR p_state->'batch'='[]'::jsonb)
  AND (p_state->'final'<>'true'::jsonb OR p_state->>'phase'='sealed'),false)
$$;
CREATE FUNCTION v24_cordis.run_digests_of(p_pins jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object(
  'policy',encode(sha256(convert_to(v24_cordis.run_policy()::text,'UTF8')),'hex'),
  'schema',encode(sha256(convert_to(v24_cordis.chat_tool_schema()::text,'UTF8')),'hex'),
  'toolset',encode(sha256(convert_to((SELECT coalesce(jsonb_agg(jsonb_build_object(
    'key',x->>'key','descriptor_digest',x->>'descriptor_digest') ORDER BY x->>'key'),'[]'::jsonb)
   FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_pins)='array' THEN p_pins ELSE '[]'::jsonb END) x)::text,'UTF8')),'hex'))
$$;
CREATE FUNCTION v24_cordis.run_digests(p_run uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT v24_cordis.run_digests_of(coalesce(jsonb_agg(jsonb_build_object(
  'key',p.key,'descriptor_digest',encode(sha256(convert_to(c.descriptor::text,'UTF8')),'hex'))
  ORDER BY p.key),'[]'::jsonb))
 FROM v24_cordis.pins p JOIN v24_cordis.contributions c ON c.id=p.contribution_id
 WHERE p.consumer_run_id=p_run AND p.released_at IS NULL
$$;
CREATE FUNCTION v24_cordis.run_id_for(p_effect uuid) RETURNS uuid
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT substr(encode(sha256(convert_to('run:'||p_effect::text,'UTF8')),'hex'),1,32)::uuid
$$;
CREATE FUNCTION v24_cordis.run_pin_id_for(p_run uuid,p_key text) RETURNS uuid
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT substr(encode(sha256(convert_to('run-pin:'||p_run::text||':'||p_key,'UTF8')),'hex'),1,32)::uuid
$$;
CREATE FUNCTION v24_cordis.run_start_receipt_valid(p_class text,p_body jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(CASE p_class
  WHEN 'success' THEN v24_cordis.exact_keys(p_body,ARRAY['v','request','steps'])
   AND p_body->'v'='1'::jsonb AND jsonb_typeof(p_body->'request')='object'
   AND v24_cordis.json_int(p_body->'steps',1,(v24_cordis.run_policy()->>'max_steps')::int)
  WHEN 'failure' THEN v24_cordis.exact_keys(p_body,ARRAY['v','error'])
   AND p_body->'v'='1'::jsonb
   AND coalesce(v24_cordis.exact_keys(p_body->'error',ARRAY['code']),false)
   AND v24_cordis.json_text(p_body->'error'->'code')
  ELSE false END,false)
$$;
CREATE FUNCTION v24_cordis.run_bindings(p_episode uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_agg(jsonb_build_object(
  'key',e.key,'contribution_id',c.id,'provider_fiber_id',c.fiber_id,
  'provider_episode_id',c.episode_id,'provider_epoch',pe.epoch,
  'descriptor_digest',encode(sha256(convert_to(c.descriptor::text,'UTF8')),'hex'),
  'capability',c.descriptor->>'capability','contract_version',c.contract_version,
  'contract',i.contracts->(c.descriptor->>'capability')) ORDER BY e.key),'[]'::jsonb)
 FROM v24_cordis.episodes ep CROSS JOIN LATERAL jsonb_each(ep.committed_view) e
 JOIN v24_cordis.contributions c ON c.id=(e.value->>'contribution_id')::uuid
 JOIN v24_cordis.episodes pe ON pe.id=c.episode_id
 JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id
 JOIN v24_cordis.installs i ON i.id=pf.install_id
 WHERE ep.id=p_episode AND ep.closed_at IS NULL
  AND c.descriptor->>'capability' IN ('model_call','tool_call')
  AND c.contract_version=e.value->>'contract_version'
  AND c.released_at IS NULL AND i.contracts ? (c.descriptor->>'capability')
$$;
CREATE FUNCTION v24_cordis.claim_contract(p_eff v24_cordis.effects) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE c jsonb;
BEGIN
 IF p_eff.kind IN ('host_io','run_start') THEN
  SELECT i.contracts->p_eff.kind INTO c FROM v24_cordis.fibers f
   JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=p_eff.fiber_id;
  RETURN c;
 END IF;
 IF p_eff.kind IN ('model_call','tool_call') THEN
  IF p_eff.run_id IS NULL OR NOT v24_cordis.json_uuid(p_eff.input->'pin_id') THEN RETURN NULL; END IF;
  SELECT i.contracts->(c2.descriptor->>'capability') INTO c FROM v24_cordis.pins p
   JOIN v24_cordis.contributions c2 ON c2.id=p.contribution_id
   JOIN v24_cordis.fibers f ON f.id=c2.fiber_id
   JOIN v24_cordis.installs i ON i.id=f.install_id
   WHERE p.id=(p_eff.input->>'pin_id')::uuid AND p.consumer_run_id=p_eff.run_id
    AND c2.descriptor->>'capability'=p_eff.kind;
  RETURN c;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.run_start_successor(p_fiber uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE;
 inst v24_cordis.installs%ROWTYPE; bindings jsonb; n int; nm int; c jsonb;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND THEN RETURN '[]'::jsonb; END IF;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND OR inst.policy_ref IS DISTINCT FROM 'chat_tool' THEN RETURN '[]'::jsonb; END IF;
 c:=inst.contracts->'run_start';
 IF NOT coalesce(v24_cordis.exact_keys(c,ARRAY['contract_version','handler_digest','replay']),false)
  OR NOT v24_cordis.json_text(c->'contract_version') OR NOT v24_cordis.json_hex64(c->'handler_digest')
  OR NOT coalesce(v24_cordis.exact_keys(c->'replay',ARRAY['repeat','concurrent']),false) THEN RETURN '[]'::jsonb; END IF;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND f.id=p_fiber;
 IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'reloading' THEN RETURN '[]'::jsonb; END IF;
 IF v24_cordis.activation_total(f.id) IS NOT NULL THEN RETURN '[]'::jsonb; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.runs WHERE owner_fiber_id=f.id AND ended_at IS NULL)
  OR EXISTS(SELECT 1 FROM v24_cordis.effects WHERE fiber_id=f.id
   AND kind IN ('run_start','model_call','tool_call') AND status IN ('ready','claimed')) THEN
  RETURN '[]'::jsonb; END IF;
 bindings:=v24_cordis.run_bindings(ep.id);
 SELECT count(*),count(*) FILTER (WHERE b->>'capability'='model_call') INTO n,nm
  FROM jsonb_array_elements(bindings) b;
 IF n<1 OR n>32 OR nm<>1
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) b
   WHERE b->'contract' IS NULL OR b->>'capability' NOT IN ('model_call','tool_call')) THEN
  RETURN '[]'::jsonb; END IF;
 RETURN jsonb_build_array(jsonb_build_object('ordinal',0,'kind','run_start','input',
  jsonb_build_object('v',1,'fiber_id',f.id,'episode_id',ep.id,
   'contract',jsonb_build_object('contract_version',c->>'contract_version',
    'handler_digest',c->>'handler_digest'))));
END $$;
CREATE FUNCTION v24_cordis.run_delta(p_effect_id uuid,p_outcome jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE eff v24_cordis.effects%ROWTYPE; f v24_cordis.fibers%ROWTYPE;
 ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 bindings jsonb; b jsonb; model jsonb; runid uuid; steps int; ev jsonb; live boolean:=false;
 pins jsonb; contract jsonb; state jsonb; reason text; status text;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('not_found_or_denied'); END IF;
 IF eff.kind<>'run_start' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_settlement_unimplemented'));
 END IF;
 IF p_outcome->>'class'='unknown' THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF NOT v24_cordis.run_start_receipt_valid(p_outcome->>'class',p_outcome->'body')
  OR NOT coalesce(v24_cordis.exact_keys(eff.input,ARRAY['v','fiber_id','episode_id','contract']),false)
  OR NOT v24_cordis.json_uuid(eff.input->'fiber_id') OR NOT v24_cordis.json_uuid(eff.input->'episode_id')
  OR eff.fiber_id IS DISTINCT FROM (eff.input->>'fiber_id')::uuid
  OR eff.episode_id IS DISTINCT FROM (eff.input->>'episode_id')::uuid
  OR NOT coalesce(v24_cordis.exact_keys(eff.input->'contract',ARRAY['contract_version','handler_digest']),false)
  OR NOT v24_cordis.json_text(eff.input->'contract'->'contract_version')
  OR NOT v24_cordis.json_hex64(eff.input->'contract'->'handler_digest') THEN
  RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 status:=CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded' ELSE 'failed' END;
 IF p_outcome->>'class'='failure' THEN
  ev:=jsonb_build_object('entity_type','run','entity_id',to_jsonb(eff.id),'event_kind','run_refused',
   'payload',jsonb_build_object('run_id','null'::jsonb,'effect_id',to_jsonb(eff.id),'reason','start_failed'));
  RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status',status),
   'events',jsonb_build_array(ev),'successors','[]'::jsonb);
 END IF;
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=eff.fiber_id;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=eff.episode_id AND fiber_id=eff.fiber_id;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND OR inst.policy_ref IS DISTINCT FROM 'chat_tool' THEN
  RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF f.current_episode_id=eff.episode_id AND ep.state='active' AND ep.closed_at IS NULL THEN
  BEGIN live:=v24_cordis.fiber_live_resolve_ok(f.id,ep.id);
  EXCEPTION WHEN SQLSTATE 'P0401' THEN RETURN v24_cordis.error_v1('retry_with_closure'); END;
 END IF;
 IF NOT live THEN reason:='owner_closing';
 ELSE
  bindings:=v24_cordis.run_bindings(ep.id);
  IF jsonb_array_length(bindings)<1 OR jsonb_array_length(bindings)>32
   OR (SELECT count(*) FROM jsonb_array_elements(bindings) x WHERE x->>'capability'='model_call')<>1
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) x
    WHERE x->'contract' IS NULL OR x->>'capability' NOT IN ('model_call','tool_call')) THEN
   RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) x
   WHERE x->'contract'->'replay'->'repeat' IS DISTINCT FROM 'true'::jsonb
    OR x->'contract'->'replay'->'concurrent' IS DISTINCT FROM 'true'::jsonb) THEN
   reason:='replay_right_missing';
  END IF;
 END IF;
 IF reason IS NOT NULL THEN
  ev:=jsonb_build_object('entity_type','run','entity_id',to_jsonb(eff.id),'event_kind','run_refused',
   'payload',jsonb_build_object('run_id','null'::jsonb,'effect_id',to_jsonb(eff.id),'reason',reason));
  RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(ev),'successors','[]'::jsonb);
 END IF;
 SELECT x INTO model FROM jsonb_array_elements(bindings) x WHERE x->>'capability'='model_call' LIMIT 1;
 runid:=v24_cordis.run_id_for(eff.id); steps:=(p_outcome->'body'->>'steps')::int;
 SELECT jsonb_agg(jsonb_build_object('id',v24_cordis.run_pin_id_for(runid,x->>'key'),
   'key',x->>'key','contribution_id',x->'contribution_id',
   'provider_episode_id',x->'provider_episode_id','provider_epoch',x->'provider_epoch')
   ORDER BY x->>'key') INTO pins FROM jsonb_array_elements(bindings) x;
 state:=jsonb_build_object('v',1,'origin',eff.id,'step',0,'phase','model',
  'batch','[]'::jsonb,'final',false);
 contract:=jsonb_build_object('contract_version',model->'contract'->>'contract_version',
  'handler_digest',model->'contract'->>'handler_digest');
 ev:=jsonb_build_object('entity_type','run','entity_id',to_jsonb(runid),'event_kind','run_progress',
  'payload',jsonb_build_object('run_id',to_jsonb(runid),'effect_id',to_jsonb(eff.id),
   'effect_kind','run_start','step',0,'remaining_steps',steps,'phase','model',
   'sealed',false,'reason','null'::jsonb));
 RETURN jsonb_build_object('domain',jsonb_build_array(
   jsonb_build_object('op','run_create','id',to_jsonb(runid),'owner_fiber_id',to_jsonb(f.id),
    'owner_episode_id',to_jsonb(ep.id),'scope_id',to_jsonb(f.scope_id),'state',state,
    'remaining_steps',steps),
   jsonb_build_object('op','run_pin_bind','run_id',to_jsonb(runid),'pins',pins)),
  'receipt',jsonb_build_object('status','succeeded'),
  'events',jsonb_build_array(ev),
  'successors',jsonb_build_array(jsonb_build_object('ordinal',0,'kind','model_call',
   'input',jsonb_build_object('v',1,'run_id',to_jsonb(runid),
    'pin_id',v24_cordis.run_pin_id_for(runid,model->>'key'),'key',model->>'key',
    'digests',v24_cordis.run_digests_of(bindings),'contract',contract))));
END $$;
CREATE FUNCTION v24_cordis.validate_run_domain(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_delta jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE eff v24_cordis.effects%ROWTYPE; expect jsonb; n int;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 expect:=v24_cordis.run_delta(p_effect_id,p_outcome);
 IF expect IS NULL OR expect ? 'error' OR p_delta IS DISTINCT FROM expect THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_delta')); END IF;
 IF eff.kind='run_start' AND p_delta->'domain'<>'[]'::jsonb THEN
  SELECT count(*) INTO n FROM jsonb_array_elements(p_delta->'domain') x
   WHERE x->>'op' IN ('run_create','run_pin_bind');
  IF n<>2 OR jsonb_array_length(p_delta->'domain')<>2
   OR (p_delta->'domain'->0->>'op') IS DISTINCT FROM 'run_create'
   OR (p_delta->'domain'->1->>'op') IS DISTINCT FROM 'run_pin_bind'
   OR (p_delta->'domain'->0->'id')::text IS DISTINCT FROM to_jsonb(v24_cordis.run_id_for(p_effect_id))::text
   OR jsonb_array_length(p_delta->'successors')<>1
   OR p_delta->'successors'->0->>'kind' IS DISTINCT FROM 'model_call' THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_delta')); END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.settlement_seed(p_effect_id uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE eff v24_cordis.effects%ROWTYPE; result jsonb; b jsonb;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 result:=jsonb_build_array(jsonb_build_object('t','effects','id',p_effect_id::text));
 IF NOT FOUND OR eff.kind NOT IN ('run_start','model_call','tool_call') THEN RETURN result; END IF;
 IF eff.kind='run_start' THEN
  FOR b IN SELECT value FROM jsonb_array_elements(v24_cordis.run_bindings(eff.episode_id)) LOOP
   result:=result||jsonb_build_array(
    jsonb_build_object('t','contributions','id',b->>'contribution_id'),
    jsonb_build_object('t','fibers','id',b->>'provider_fiber_id'),
    jsonb_build_object('t','episodes','id',b->>'provider_episode_id'));
  END LOOP;
 ELSE
  IF eff.run_id IS NULL THEN RETURN result; END IF;
  result:=result||jsonb_build_array(jsonb_build_object('t','runs','id',eff.run_id::text));
  FOR b IN SELECT jsonb_build_object('t','pins','id',p.id::text) FROM v24_cordis.pins p
   WHERE p.consumer_run_id=eff.run_id AND p.released_at IS NULL LOOP
   result:=result||jsonb_build_array(b);
  END LOOP;
  FOR b IN SELECT jsonb_build_object('t','contributions','id',c.id::text) FROM v24_cordis.pins p
   JOIN v24_cordis.contributions c ON c.id=p.contribution_id
   WHERE p.consumer_run_id=eff.run_id AND p.released_at IS NULL LOOP
   result:=result||jsonb_build_array(b);
  END LOOP;
  FOR b IN SELECT jsonb_build_object('t','episodes','id',c.episode_id::text) FROM v24_cordis.pins p
   JOIN v24_cordis.contributions c ON c.id=p.contribution_id
   WHERE p.consumer_run_id=eff.run_id AND p.released_at IS NULL LOOP
   result:=result||jsonb_build_array(b);
  END LOOP;
 END IF;
 RETURN (SELECT coalesce(jsonb_agg(x ORDER BY x->>'t',x->>'id'),'[]'::jsonb)
  FROM (SELECT DISTINCT value x FROM jsonb_array_elements(result)) q);
END $$;