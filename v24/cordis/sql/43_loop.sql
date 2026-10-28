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
  AND (SELECT count(*)=count(DISTINCT x->>'ordinal') AND count(*)=count(DISTINCT x->>'key')
   AND count(*)=count(DISTINCT x->>'call_id') FROM jsonb_array_elements(p_state->'batch') x)
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
CREATE FUNCTION v24_cordis.model_receipt_valid(p_class text,p_body jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp
BEGIN ATOMIC
 SELECT coalesce(CASE p_class
  WHEN 'success' THEN v24_cordis.exact_keys(p_body,ARRAY['kind','result'])
   AND p_body->>'kind'='model_call'
   AND coalesce(v24_cordis.exact_keys(p_body->'result',ARRAY['text','tool_calls','interaction','final','usage']),false)
   AND jsonb_typeof(p_body->'result'->'text')='string'
   AND jsonb_typeof(p_body->'result'->'interaction')='null'
   AND jsonb_typeof(p_body->'result'->'final')='boolean'
   AND jsonb_typeof(p_body->'result'->'tool_calls')='array'
   AND jsonb_array_length(p_body->'result'->'tool_calls')<=16
   AND (p_body->'result'->'final'<>'true'::jsonb OR jsonb_array_length(p_body->'result'->'tool_calls')=0)
   AND (p_body->'result'->'usage'='null'::jsonb OR (jsonb_typeof(p_body->'result'->'usage')='object'
    AND NOT EXISTS(SELECT 1 FROM jsonb_each(p_body->'result'->'usage') u
     WHERE jsonb_typeof(u.value)<>'number' OR (u.value#>>'{}')!~'^(0|[1-9][0-9]*)$')))
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_body->'result'->'tool_calls') x
    WHERE NOT coalesce(v24_cordis.exact_keys(x,ARRAY['call_id','key','args']),false)
     OR NOT v24_cordis.json_text(x->'call_id') OR NOT v24_cordis.json_text(x->'key')
     OR jsonb_typeof(x->'args')<>'object')
   AND (SELECT count(*)=count(DISTINCT x->>'key') AND count(*)=count(DISTINCT x->>'call_id')
    FROM jsonb_array_elements(p_body->'result'->'tool_calls') x)
  WHEN 'failure' THEN v24_cordis.exact_keys(p_body,ARRAY['kind','error'])
   AND p_body->>'kind'='model_call' AND jsonb_typeof(p_body->'error')='object'
   AND ((p_body->'error') ? 'code') AND ((p_body->'error')-ARRAY['code','detail']='{}'::jsonb)
   AND v24_cordis.json_text(p_body->'error'->'code')
   AND (NOT ((p_body->'error') ? 'detail') OR jsonb_typeof(p_body->'error'->'detail')='object')
  ELSE false END,false);
END;
CREATE FUNCTION v24_cordis.tool_receipt_valid(p_class text,p_body jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp
BEGIN ATOMIC
 SELECT coalesce(v24_cordis.exact_keys(p_body,ARRAY['kind','result'])
  AND p_body->>'kind'='tool_call'
  AND coalesce(v24_cordis.exact_keys(p_body->'result',ARRAY['status','output','usage']),false)
  AND p_body->'result'->>'status'=CASE p_class WHEN 'success' THEN 'ok' WHEN 'failure' THEN 'error' END
  AND jsonb_typeof(p_body->'result'->'output')='object'
  AND (p_body->'result'->'usage'='null'::jsonb
   OR (v24_cordis.exact_keys(p_body->'result'->'usage',ARRAY['wall_ms'])
    AND v24_cordis.json_int(p_body->'result'->'usage'->'wall_ms',0,9223372036854775807))),false);
END;
CREATE FUNCTION v24_cordis.reduce_chat_tool(p_state jsonb,p_fact jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp
BEGIN ATOMIC
 WITH b AS (
  SELECT (p_state->>'step')::int AS step,
   (p_fact->>'remaining_steps')::int AS r,
   coalesce((p_fact->>'live_siblings')::int,0) AS live,
   coalesce((p_fact->>'unknown_in_run')::boolean,false) AS unknown_run,
   p_fact->>'effect_kind' AS kind, p_fact->>'class' AS cls,
   p_fact->'receipt'->'result' AS res,
   CASE WHEN jsonb_typeof(p_fact->'receipt'->'result'->'tool_calls')='array'
    THEN p_fact->'receipt'->'result'->'tool_calls' ELSE '[]'::jsonb END AS tc,
   coalesce(p_fact->'receipt'->'result'->'final','false'::jsonb)='true'::jsonb AS final,
   CASE WHEN jsonb_typeof(p_fact->'tools')='array' THEN p_fact->'tools' ELSE '[]'::jsonb END AS tools
 ), v AS (
  SELECT b.*, jsonb_array_length(tc) AS n,
   NOT (cls='success' AND (NOT CASE kind
    WHEN 'model_call' THEN v24_cordis.model_receipt_valid(cls,p_fact->'receipt')
    WHEN 'tool_call' THEN v24_cordis.tool_receipt_valid(cls,p_fact->'receipt')
    ELSE false END
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(tc) x
     WHERE NOT EXISTS(SELECT 1 FROM jsonb_array_elements(tools) t WHERE t->>'key'=x->>'key')))) AS valid
  FROM b
 )
 SELECT CASE
  WHEN kind='model_call' AND cls='failure' THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','sealed','batch','[]'::jsonb,'final',false),
    'intents',jsonb_build_array(jsonb_build_object('type','close_run','reason','model_failed','text','','dropped_tool_calls',0)))
  WHEN kind='model_call' AND cls='success' AND NOT valid THEN '{"invalid":true}'::jsonb
  WHEN kind='model_call' AND cls='success' AND final THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','sealed','batch','[]'::jsonb,'final',true),
    'intents',jsonb_build_array(jsonb_build_object('type','close_run','reason','final','text',coalesce(res->>'text',''),'dropped_tool_calls',0)))
  WHEN kind='model_call' AND cls='success' AND r=0 THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','sealed','batch','[]'::jsonb,'final',false),
    'intents',jsonb_build_array(jsonb_build_object('type','close_run','reason','budget_exhausted','text','','dropped_tool_calls',n)))
  WHEN kind='model_call' AND cls='success' AND n=0 THEN '{"invalid":true}'::jsonb
  WHEN kind='model_call' AND cls='success' AND n>r THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','sealed','batch','[]'::jsonb,'final',false),
    'intents',jsonb_build_array(jsonb_build_object('type','close_run','reason','budget_exhausted','text','','dropped_tool_calls',n)))
  WHEN kind='model_call' AND cls='success' THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','tools','batch',
     (SELECT jsonb_agg(jsonb_build_object('ordinal',ord-1,'key',x->>'key','call_id',x->>'call_id') ORDER BY ord)
      FROM jsonb_array_elements(tc) WITH ORDINALITY t(x,ord))),
    'intents',(SELECT jsonb_agg(jsonb_build_object('type','emit_tool','ordinal',ord-1,
      'key',x->>'key','call_id',x->>'call_id','args',x->'args') ORDER BY ord)
      FROM jsonb_array_elements(tc) WITH ORDINALITY t(x,ord)))
  WHEN kind='tool_call' AND cls IN ('success','failure') AND live>0 THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','tools'),'intents','[]'::jsonb)
  WHEN kind='tool_call' AND cls IN ('success','failure') AND unknown_run THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','tools'),'intents','[]'::jsonb)
  WHEN kind='tool_call' AND cls IN ('success','failure') AND r=0 THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','sealed','batch','[]'::jsonb,'final',false),
    'intents',jsonb_build_array(jsonb_build_object('type','close_run','reason','budget_exhausted','text','','dropped_tool_calls',0)))
  WHEN kind='tool_call' AND cls IN ('success','failure') THEN
   jsonb_build_object('v',1,'state',p_state||jsonb_build_object('step',step+1,'phase','model','batch','[]'::jsonb),
    'intents',jsonb_build_array(jsonb_build_object('type','emit_model')))
  ELSE '{"invalid":true}'::jsonb
 END
 FROM v;
END;
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
CREATE FUNCTION v24_cordis.run_bindings_valid(p_bindings jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_array_length(p_bindings) BETWEEN 1 AND 32
  AND (SELECT count(*) FROM jsonb_array_elements(p_bindings) b WHERE b->>'capability'='model_call')=1
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_bindings) b WHERE b->'contract' IS NULL
   OR b->>'capability' NOT IN ('model_call','tool_call')),false)
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
DECLARE f v24_cordis.fibers%ROWTYPE; bindings jsonb; c jsonb; policy text;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers fb WHERE fb.id=p_fiber
  AND EXISTS(SELECT 1 FROM v24_cordis.episodes e WHERE e.id=fb.current_episode_id
   AND e.fiber_id=fb.id AND e.closed_at IS NULL AND e.state='reloading');
 IF NOT FOUND THEN RETURN '[]'::jsonb; END IF;
 SELECT i.contracts->'run_start',i.policy_ref INTO c,policy FROM v24_cordis.installs i WHERE i.id=f.install_id;
 IF NOT FOUND OR policy IS DISTINCT FROM 'chat_tool' THEN RETURN '[]'::jsonb; END IF;
 IF NOT coalesce(v24_cordis.contracts_valid(jsonb_build_object('run_start',c)),false)
  THEN RETURN '[]'::jsonb; END IF;
 IF v24_cordis.activation_total(f.id) IS NOT NULL THEN RETURN '[]'::jsonb; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.runs WHERE owner_fiber_id=f.id AND ended_at IS NULL)
  OR EXISTS(SELECT 1 FROM v24_cordis.effects WHERE fiber_id=f.id
   AND kind IN ('run_start','model_call','tool_call') AND status IN ('ready','claimed')) THEN
  RETURN '[]'::jsonb; END IF;
 bindings:=v24_cordis.run_bindings(f.current_episode_id);
 IF NOT v24_cordis.run_bindings_valid(bindings) THEN RETURN '[]'::jsonb; END IF;
 RETURN jsonb_build_array(jsonb_build_object('ordinal',0,'kind','run_start','input',
  jsonb_build_object('v',1,'fiber_id',f.id,'episode_id',f.current_episode_id,
   'contract',jsonb_build_object('contract_version',c->>'contract_version',
    'handler_digest',c->>'handler_digest'))));
END $$;
CREATE FUNCTION v24_cordis.run_delta(p_effect_id uuid,p_outcome jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE eff v24_cordis.effects%ROWTYPE; r v24_cordis.runs%ROWTYPE; i v24_cordis.installs%ROWTYPE;
 fact jsonb; red jsonb; intents jsonb; newstate jsonb; result jsonb; succs jsonb:='[]'::jsonb; it jsonb;
 body jsonb:=p_outcome->'body'; newr int; tools jsonb; ev jsonb; tpin v24_cordis.pins%ROWTYPE;
 cc v24_cordis.contributions%ROWTYPE; live int; f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE;
 inst v24_cordis.installs%ROWTYPE; bindings jsonb; b jsonb; model jsonb; runid uuid; steps int; pins jsonb;
 contract jsonb; state jsonb; reason text; status text; live_ok boolean:=false;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('not_found_or_denied'); END IF;
 IF eff.kind IN ('model_call','tool_call') THEN
  IF eff.run_id IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  SELECT * INTO r FROM v24_cordis.runs WHERE id=eff.run_id;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  IF r.ended_at IS NOT NULL OR r.result IS NOT NULL THEN RETURN v24_cordis.error_v1('already_terminal'); END IF;
  IF p_outcome->>'class'='unknown' THEN
   RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','unknown'),
    'events','[]'::jsonb,'successors','[]'::jsonb);
  END IF;
  IF p_outcome->>'class' NOT IN ('success','failure') THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  IF eff.kind='tool_call' AND (r.state->>'phase'<>'tools'
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(r.state->'batch') bs
    WHERE bs->>'ordinal'=eff.ordinal::text AND bs->>'key'=eff.input->>'key'
     AND bs->>'call_id'=eff.input->>'call_id')) THEN
   RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  IF NOT coalesce(CASE eff.kind
   WHEN 'model_call' THEN v24_cordis.exact_keys(eff.input,
    ARRAY['v','run_id','pin_id','key','digests','contract'])
   ELSE v24_cordis.exact_keys(eff.input,
    ARRAY['v','run_id','pin_id','key','descriptor_digest','call_id','args','contract']) END,false)
   OR eff.input->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(eff.input->'run_id')
   OR (eff.input->>'run_id')::uuid<>r.id OR NOT v24_cordis.json_uuid(eff.input->'pin_id')
   OR NOT v24_cordis.json_text(eff.input->'key')
   OR (eff.kind='tool_call' AND (NOT v24_cordis.json_hex64(eff.input->'descriptor_digest')
    OR NOT v24_cordis.json_text(eff.input->'call_id') OR jsonb_typeof(eff.input->'args')<>'object'))
   OR NOT coalesce(v24_cordis.exact_keys(eff.input->'contract',
    ARRAY['contract_version','handler_digest']),false)
   OR NOT v24_cordis.run_state_valid(r.state) THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  SELECT * INTO tpin FROM v24_cordis.pins WHERE id=(eff.input->>'pin_id')::uuid
   AND consumer_run_id=r.id AND key=eff.input->>'key';
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  IF tpin.released_at IS NOT NULL OR NOT v24_cordis.pin_readable(tpin.id) THEN
   RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
  IF eff.kind='model_call' THEN
   IF eff.input->'digests' IS DISTINCT FROM v24_cordis.run_digests(r.id) THEN
    RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
   IF NOT v24_cordis.model_receipt_valid(p_outcome->>'class',body) THEN
    RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
   live:=0;
  ELSE
   SELECT * INTO cc FROM v24_cordis.contributions WHERE id=tpin.contribution_id;
   IF NOT FOUND OR cc.released_at IS NOT NULL OR cc.descriptor->>'capability'<>'tool_call'
    OR encode(sha256(convert_to(cc.descriptor::text,'UTF8')),'hex')<>eff.input->>'descriptor_digest' THEN
    RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
   IF NOT v24_cordis.tool_receipt_valid(p_outcome->>'class',body) THEN
    RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
   SELECT count(*) INTO live FROM v24_cordis.effects x WHERE x.parent_id=eff.parent_id
    AND x.kind='tool_call' AND x.status IN ('ready','claimed') AND x.id<>eff.id;
  END IF;
  IF r.remaining_steps<1 THEN RETURN v24_cordis.error_v1('budget_exceeded'); END IF;
  newr:=r.remaining_steps-1;
  SELECT coalesce(jsonb_agg(jsonb_build_object('key',p.key,'pin_id',p.id) ORDER BY p.key),'[]'::jsonb)
   INTO tools FROM v24_cordis.pins p JOIN v24_cordis.contributions mc
    ON mc.id=p.contribution_id WHERE p.consumer_run_id=r.id AND p.released_at IS NULL
     AND mc.descriptor->>'capability'='tool_call';
  fact:=jsonb_build_object('v',1,'effect_kind',eff.kind,'class',p_outcome->>'class',
   'receipt',body,'remaining_steps',newr,'tools',tools,'live_siblings',live,
   'unknown_in_run',EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.run_id=r.id AND x.status='unknown'));
  red:=v24_cordis.reduce_chat_tool(r.state,fact);
  IF red ? 'invalid' THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  newstate:=red->'state'; intents:=red->'intents';
  IF intents @> '[{"type":"close_run"}]'::jsonb THEN
   it:=intents->0;
   result:=jsonb_build_object('v',1,'reason',it->>'reason',
    'output',CASE it->>'reason' WHEN 'final' THEN body->'result'
     WHEN 'model_failed' THEN body->'error' ELSE '{}'::jsonb END,
    'dropped_tool_calls',(it->>'dropped_tool_calls')::int);
   ev:=jsonb_build_object('entity_type','run','entity_id',to_jsonb(r.id),'event_kind','run_progress',
    'payload',jsonb_build_object('run_id',to_jsonb(r.id),'effect_id',to_jsonb(eff.id),
     'effect_kind',eff.kind,'step',(newstate->>'step')::int,'remaining_steps',newr,
     'phase',newstate->>'phase','sealed',true,'reason',it->>'reason'));
   RETURN jsonb_build_object('domain',jsonb_build_array(
     jsonb_build_object('op','run_state','run_id',to_jsonb(r.id),'state',newstate),
     jsonb_build_object('op','run_budget','run_id',to_jsonb(r.id),'remaining_steps',newr),
     jsonb_build_object('op','run_seal','run_id',to_jsonb(r.id),'effect_id',to_jsonb(eff.id),'result',result),
     jsonb_build_object('op','pins_release','fiber_id',to_jsonb(r.owner_fiber_id),
      'episode_id',to_jsonb(r.owner_episode_id),
      'pin_ids',(SELECT coalesce(jsonb_agg(p.id ORDER BY p.key,p.id),'[]'::jsonb)
       FROM v24_cordis.pins p WHERE p.consumer_run_id=r.id AND p.released_at IS NULL))),
    'receipt',jsonb_build_object('status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded' ELSE 'failed' END),
    'events',jsonb_build_array(ev),'successors','[]'::jsonb);
  END IF;
  FOR it IN SELECT value FROM jsonb_array_elements(intents) LOOP
   IF it->>'type'='emit_tool' THEN
    SELECT p.* INTO tpin FROM v24_cordis.pins p JOIN v24_cordis.contributions mc
     ON mc.id=p.contribution_id WHERE p.consumer_run_id=r.id AND p.key=it->>'key'
      AND p.released_at IS NULL AND mc.released_at IS NULL AND mc.descriptor->>'capability'='tool_call';
    IF NOT FOUND THEN RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
    SELECT * INTO cc FROM v24_cordis.contributions WHERE id=tpin.contribution_id;
    SELECT * INTO i FROM v24_cordis.installs
     WHERE id=(SELECT install_id FROM v24_cordis.fibers WHERE id=cc.fiber_id);
    IF NOT FOUND OR i.contracts->'tool_call' IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
    succs:=succs||jsonb_build_array(jsonb_build_object('ordinal',(it->>'ordinal')::int,'kind','tool_call',
     'input',jsonb_build_object('v',1,'run_id',to_jsonb(r.id),'pin_id',to_jsonb(tpin.id),'key',tpin.key,
      'descriptor_digest',encode(sha256(convert_to(cc.descriptor::text,'UTF8')),'hex'),
      'call_id',it->>'call_id','args',it->'args',
      'contract',jsonb_build_object('contract_version',i.contracts->'tool_call'->>'contract_version',
       'handler_digest',i.contracts->'tool_call'->>'handler_digest'))));
   ELSIF it->>'type'='emit_model' THEN
    SELECT p.* INTO tpin FROM v24_cordis.pins p JOIN v24_cordis.contributions mc
     ON mc.id=p.contribution_id WHERE p.consumer_run_id=r.id AND p.released_at IS NULL
      AND mc.released_at IS NULL AND mc.descriptor->>'capability'='model_call' AND v24_cordis.pin_readable(p.id);
    IF NOT FOUND THEN RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
    SELECT * INTO cc FROM v24_cordis.contributions WHERE id=tpin.contribution_id;
    SELECT * INTO i FROM v24_cordis.installs WHERE id=(SELECT install_id FROM v24_cordis.fibers
     WHERE id=cc.fiber_id);
    contract:=i.contracts->'model_call';
    IF contract IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
    succs:=jsonb_build_array(jsonb_build_object('ordinal',0,'kind','model_call','input',
     jsonb_build_object('v',1,'run_id',to_jsonb(r.id),'pin_id',to_jsonb(tpin.id),'key',tpin.key,
      'digests',v24_cordis.run_digests(r.id),'contract',jsonb_build_object(
       'contract_version',contract->>'contract_version','handler_digest',contract->>'handler_digest'))));
   END IF;
  END LOOP;
  ev:=jsonb_build_object('entity_type','run','entity_id',to_jsonb(r.id),'event_kind','run_progress',
   'payload',jsonb_build_object('run_id',to_jsonb(r.id),'effect_id',to_jsonb(eff.id),
    'effect_kind',eff.kind,'step',(newstate->>'step')::int,'remaining_steps',newr,
    'phase',newstate->>'phase','sealed',false,'reason','null'::jsonb));
  RETURN jsonb_build_object('domain',jsonb_build_array(
    jsonb_build_object('op','run_state','run_id',to_jsonb(r.id),'state',newstate),
    jsonb_build_object('op','run_budget','run_id',to_jsonb(r.id),'remaining_steps',newr)),
   'receipt',jsonb_build_object('status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded' ELSE 'failed' END),
   'events',jsonb_build_array(ev),'successors',succs);
 END IF;
 IF eff.kind<>'run_start' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_settlement_unimplemented'));
 END IF;
 IF NOT coalesce(CASE p_outcome->>'class'
  WHEN 'success' THEN v24_cordis.exact_keys(p_outcome->'body',ARRAY['v','request','steps'])
   AND p_outcome->'body'->'v'='1'::jsonb AND jsonb_typeof(p_outcome->'body'->'request')='object'
   AND v24_cordis.json_int(p_outcome->'body'->'steps',1,(v24_cordis.run_policy()->>'max_steps')::int)
  WHEN 'failure' THEN v24_cordis.exact_keys(p_outcome->'body',ARRAY['v','error'])
   AND p_outcome->'body'->'v'='1'::jsonb
   AND coalesce(v24_cordis.exact_keys(p_outcome->'body'->'error',ARRAY['code']),false)
   AND v24_cordis.json_text(p_outcome->'body'->'error'->'code')
  ELSE false END,false)
  OR NOT coalesce(v24_cordis.exact_keys(eff.input,ARRAY['v','fiber_id','episode_id','contract']),false)
  OR NOT v24_cordis.json_uuid(eff.input->'fiber_id') OR NOT v24_cordis.json_uuid(eff.input->'episode_id')
  OR eff.fiber_id IS DISTINCT FROM (eff.input->>'fiber_id')::uuid
  OR eff.episode_id IS DISTINCT FROM (eff.input->>'episode_id')::uuid THEN
  RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF p_outcome->>'class'='failure' THEN
  ev:=jsonb_build_object('entity_type','run','entity_id',to_jsonb(eff.id),'event_kind','run_refused',
   'payload',jsonb_build_object('run_id','null'::jsonb,'effect_id',to_jsonb(eff.id),'reason','start_failed'));
  RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','failed'),
   'events',jsonb_build_array(ev),'successors','[]'::jsonb);
 END IF;
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=eff.fiber_id;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=eff.episode_id AND fiber_id=eff.fiber_id;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND OR inst.policy_ref IS DISTINCT FROM 'chat_tool' THEN
  RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF f.current_episode_id=eff.episode_id AND ep.state='active' AND ep.closed_at IS NULL THEN
  BEGIN live_ok:=v24_cordis.fiber_live_resolve_ok(f.id,ep.id);
  EXCEPTION WHEN SQLSTATE 'P0401' THEN RETURN v24_cordis.error_v1('retry_with_closure'); END;
 END IF;
 IF NOT live_ok THEN reason:='owner_closing';
 ELSE
  bindings:=v24_cordis.run_bindings(ep.id);
  IF NOT v24_cordis.run_bindings_valid(bindings)
   THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
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
DECLARE eff v24_cordis.effects%ROWTYPE; r v24_cordis.runs%ROWTYPE; expect jsonb; d jsonb;
 f v24_cordis.fibers%ROWTYPE; bindings jsonb; model jsonb; runid uuid; reason text;
 live_ok boolean; n_seal int;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 expect:=v24_cordis.run_delta(p_effect_id,p_outcome);
 IF expect IS NULL OR expect ? 'error' OR p_delta IS DISTINCT FROM expect THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_delta')); END IF;
 d:=p_delta->'domain';
 IF eff.kind='run_start' THEN
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=eff.fiber_id;
  IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM v24_cordis.installs i
   WHERE i.id=f.install_id AND i.policy_ref='chat_tool') THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_delta')); END IF;
  runid:=v24_cordis.run_id_for(eff.id);
  IF p_outcome->>'class'='success' THEN
   bindings:=v24_cordis.run_bindings(eff.episode_id);
   live_ok:=f.current_episode_id=eff.episode_id AND EXISTS(SELECT 1 FROM v24_cordis.episodes e
   WHERE e.id=eff.episode_id AND e.fiber_id=eff.fiber_id AND e.state='active' AND e.closed_at IS NULL)
    AND v24_cordis.fiber_live_resolve_ok(f.id,eff.episode_id);
  END IF;
  IF d<>'[]'::jsonb THEN
   SELECT b INTO model FROM jsonb_array_elements(bindings) b WHERE b->>'capability'='model_call';
   IF p_outcome->>'class'<>'success' OR jsonb_array_length(d)<>2
    OR NOT coalesce(v24_cordis.json_int(p_outcome->'body'->'steps',1,64),false)
    OR NOT live_ok OR NOT v24_cordis.run_bindings_valid(bindings)
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->'contract'->'replay'
     IS DISTINCT FROM '{"repeat":true,"concurrent":true}'::jsonb)
    OR d->0->'id' IS DISTINCT FROM to_jsonb(runid) OR d->1->'run_id' IS DISTINCT FROM to_jsonb(runid)
    OR d->0->'owner_fiber_id' IS DISTINCT FROM to_jsonb(eff.fiber_id)
    OR d->0->'owner_episode_id' IS DISTINCT FROM to_jsonb(eff.episode_id)
    OR d->0->'scope_id' IS DISTINCT FROM to_jsonb(f.scope_id)
    OR d->0->'state' IS DISTINCT FROM jsonb_build_object('v',1,'origin',to_jsonb(eff.id),
     'step',0,'phase','model','batch','[]'::jsonb,'final',false)
    OR d->0->'remaining_steps' IS DISTINCT FROM to_jsonb((p_outcome->'body'->>'steps')::int)
    OR d->1->'pins' IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_object('id',
      v24_cordis.run_pin_id_for(runid,b->>'key'),'key',b->>'key','contribution_id',
      b->'contribution_id','provider_episode_id',b->'provider_episode_id','provider_epoch',
      b->'provider_epoch') ORDER BY b->>'key') FROM jsonb_array_elements(bindings) b)
    OR p_delta->'successors' IS DISTINCT FROM jsonb_build_array(jsonb_build_object('ordinal',0,
      'kind','model_call','input',jsonb_build_object('v',1,'run_id',to_jsonb(runid),
      'pin_id',v24_cordis.run_pin_id_for(runid,model->>'key'),'key',model->>'key',
      'digests',v24_cordis.run_digests_of(bindings),'contract',jsonb_build_object(
      'contract_version',model->'contract'->>'contract_version',
      'handler_digest',model->'contract'->>'handler_digest')))) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_delta')); END IF;
  ELSE
   IF p_outcome->>'class'<>'success' THEN reason:='start_failed';
   ELSE
    reason:=CASE WHEN NOT live_ok THEN 'owner_closing'
     WHEN NOT v24_cordis.run_bindings_valid(bindings) THEN NULL
     WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->'contract'->'replay'
      IS DISTINCT FROM '{"repeat":true,"concurrent":true}'::jsonb) THEN 'replay_right_missing' END;
   END IF;
   IF reason IS NULL OR p_delta IS DISTINCT FROM jsonb_build_object('domain','[]'::jsonb,
    'receipt',jsonb_build_object('status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded'
     ELSE 'failed' END),'events',jsonb_build_array(jsonb_build_object('entity_type','run',
     'entity_id',to_jsonb(eff.id),'event_kind','run_refused','payload',jsonb_build_object(
     'run_id','null'::jsonb,'effect_id',to_jsonb(eff.id),'reason',reason))),
    'successors','[]'::jsonb) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_refusal')); END IF;
  END IF;
 ELSIF eff.kind IN ('model_call','tool_call') AND p_outcome->>'class'<>'unknown' THEN
  SELECT * INTO r FROM v24_cordis.runs WHERE id=eff.run_id;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_state')); END IF;
  n_seal:=jsonb_array_length(d)-2;
  IF n_seal NOT IN (0,2)
   OR d->0->'run_id' IS DISTINCT FROM to_jsonb(r.id) OR d->1->'run_id' IS DISTINCT FROM to_jsonb(r.id)
   OR d->1->'remaining_steps' IS DISTINCT FROM to_jsonb(r.remaining_steps-1)
   OR d->0->'state'->'step' IS DISTINCT FROM to_jsonb((r.state->>'step')::int+1)
   OR ((d->0->'state'->>'phase')='sealed') IS DISTINCT FROM (n_seal=2) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_state_delta')); END IF;
  IF n_seal=2 THEN
   IF d->2->'run_id' IS DISTINCT FROM to_jsonb(r.id)
    OR d->2->'effect_id' IS DISTINCT FROM to_jsonb(p_effect_id)
    OR d->3->'fiber_id' IS DISTINCT FROM to_jsonb(r.owner_fiber_id)
    OR d->3->'episode_id' IS DISTINCT FROM to_jsonb(r.owner_episode_id)
    OR d->3->'pin_ids' IS DISTINCT FROM (SELECT coalesce(jsonb_agg(to_jsonb(p.id) ORDER BY p.key,p.id),
     '[]'::jsonb) FROM v24_cordis.pins p WHERE p.consumer_run_id=r.id AND p.released_at IS NULL)
    OR p_delta->'successors'<>'[]'::jsonb THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_seal_delta')); END IF;
  END IF;
  IF jsonb_array_length(p_delta->'successors')>16
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_delta->'successors') x WHERE
    x->'input'->'run_id' IS DISTINCT FROM to_jsonb(r.id)
    OR x->>'kind'<>CASE eff.kind WHEN 'model_call' THEN 'tool_call' ELSE 'model_call' END
    OR NOT EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.id=(x->'input'->>'pin_id')::uuid
     AND p.consumer_run_id=r.id AND p.key=x->'input'->>'key' AND p.released_at IS NULL
     AND (eff.kind='model_call' OR EXISTS(SELECT 1 FROM v24_cordis.contributions mc
      WHERE mc.id=p.contribution_id AND mc.descriptor->>'capability'='model_call')))
    OR (eff.kind='model_call' AND NOT (d->0->'state'->'batch' @> jsonb_build_array(
     jsonb_build_object('ordinal',(x->>'ordinal')::int,'key',x->'input'->>'key',
     'call_id',x->'input'->>'call_id'))))
    OR (eff.kind='tool_call' AND x->'input'->'digests' IS DISTINCT FROM v24_cordis.run_digests(r.id))) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_successor')); END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.settlement_seed(p_effect_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH eff AS (SELECT * FROM v24_cordis.effects WHERE id=p_effect_id),
 rb AS (SELECT b FROM eff CROSS JOIN LATERAL jsonb_array_elements(
   CASE WHEN eff.kind='run_start' THEN v24_cordis.run_bindings(eff.episode_id)
    ELSE '[]'::jsonb END) b),
 rp AS (SELECT p.id AS pin,c.id AS contrib,c.episode_id AS ep FROM eff
   JOIN v24_cordis.pins p ON p.consumer_run_id=eff.run_id AND p.released_at IS NULL
   JOIN v24_cordis.contributions c ON c.id=p.contribution_id
   WHERE eff.kind IN ('model_call','tool_call') AND eff.run_id IS NOT NULL), seed AS (
  SELECT 'effects'::text AS t,p_effect_id::text AS id
  UNION ALL SELECT 'contributions',b->>'contribution_id' FROM rb
  UNION ALL SELECT 'fibers',b->>'provider_fiber_id' FROM rb
  UNION ALL SELECT 'episodes',b->>'provider_episode_id' FROM rb
  UNION ALL SELECT 'runs',eff.run_id::text FROM eff
   WHERE eff.kind IN ('model_call','tool_call') AND eff.run_id IS NOT NULL
  UNION ALL SELECT 'pins',pin::text FROM rp
  UNION ALL SELECT 'contributions',contrib::text FROM rp
  UNION ALL SELECT 'episodes',ep::text FROM rp
 )
 SELECT coalesce(jsonb_agg(jsonb_build_object('t',t,'id',id) ORDER BY t,id),'[]'::jsonb)
 FROM (SELECT DISTINCT t,id FROM seed) q
$$;
