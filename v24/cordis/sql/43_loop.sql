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
  'key',p.key,'descriptor_digest',e.value->>'descriptor_digest') ORDER BY p.key),'[]'::jsonb))
 FROM v24_cordis.runs r
 JOIN v24_cordis.episodes ep ON ep.id=r.owner_episode_id
 JOIN v24_cordis.pins p ON p.consumer_run_id=r.id AND p.released_at IS NULL
 JOIN v24_cordis.contributions c ON c.id=p.contribution_id
 CROSS JOIN LATERAL v24_cordis.descriptor_effective(r.scope_id,
  coalesce(v24_cordis.service_realm(r.scope_id,p.key),'root'),p.key,
  c.descriptor,c.contract_version) x(eff)
 CROSS JOIN LATERAL jsonb_each(ep.committed_view) e
 WHERE r.id=p_run AND e.key=p.key AND c.released_at IS NULL
  AND c.contract_version=e.value->>'contract_version'
  AND x.eff->>'available'='true'
  AND x.eff->>'descriptor_digest'=e.value->>'descriptor_digest'
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
  'descriptor_digest',e.value->>'descriptor_digest',
  'capability',x.eff->'descriptor'->>'capability','contract_version',c.contract_version,
  'contract',i.contracts->(x.eff->'descriptor'->>'capability')) ORDER BY e.key),'[]'::jsonb)
 FROM v24_cordis.episodes ep
 JOIN v24_cordis.fibers cf ON cf.id=ep.fiber_id
 CROSS JOIN LATERAL jsonb_each(ep.committed_view) e
 JOIN v24_cordis.contributions c ON c.id=(e.value->>'contribution_id')::uuid
 JOIN v24_cordis.episodes pe ON pe.id=c.episode_id
 JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id
 JOIN v24_cordis.installs i ON i.id=pf.install_id
 CROSS JOIN LATERAL v24_cordis.descriptor_effective(cf.scope_id,
  coalesce(v24_cordis.service_realm(cf.scope_id,e.key),'root'),e.key,
  c.descriptor,c.contract_version) x(eff)
 WHERE ep.id=p_episode AND ep.closed_at IS NULL
  AND c.released_at IS NULL AND c.contract_version=e.value->>'contract_version'
  AND x.eff->>'available'='true'
  AND x.eff->>'descriptor_digest'=e.value->>'descriptor_digest'
  AND x.eff->'descriptor'->>'capability' IN ('model_call','tool_call')
  AND i.contracts ? (x.eff->'descriptor'->>'capability')
$$;
CREATE FUNCTION v24_cordis.run_bindings_valid(p_bindings jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_array_length(p_bindings) BETWEEN 1 AND 32
  AND (SELECT count(*) FROM jsonb_array_elements(p_bindings) b WHERE b->>'capability'='model_call')=1
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_bindings) b WHERE b->'contract' IS NULL
   OR b->>'capability' NOT IN ('model_call','tool_call')),false)
$$;
CREATE FUNCTION v24_cordis.run_binding_desc(p_run uuid,p_pin uuid,p_key text) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE r v24_cordis.runs%ROWTYPE; c v24_cordis.contributions%ROWTYPE; frozen text; frozen_cv text; eff jsonb;
BEGIN
 SELECT * INTO r FROM v24_cordis.runs WHERE id=p_run;
 IF NOT FOUND THEN RETURN jsonb_build_object('available',false,'reason','run'); END IF;
 SELECT ct.* INTO c FROM v24_cordis.pins p JOIN v24_cordis.contributions ct
  ON ct.id=p.contribution_id
  WHERE p.id=p_pin AND p.consumer_run_id=p_run AND p.key=p_key AND ct.key=p_key
   AND p.released_at IS NULL AND ct.released_at IS NULL;
 IF NOT FOUND THEN RETURN jsonb_build_object('available',false,'reason','pin'); END IF;
 SELECT e.value->>'descriptor_digest',e.value->>'contract_version' INTO frozen,frozen_cv
  FROM v24_cordis.episodes ep CROSS JOIN LATERAL jsonb_each(ep.committed_view) e
  WHERE ep.id=r.owner_episode_id AND e.key=p_key;
 IF frozen IS NULL THEN RETURN jsonb_build_object('available',false,'reason','view'); END IF;
 eff:=v24_cordis.descriptor_effective(r.scope_id,
  coalesce(v24_cordis.service_realm(r.scope_id,p_key),'root'),p_key,
  c.descriptor,c.contract_version);
 IF NOT coalesce((eff->>'available')::boolean,false)
  OR c.contract_version IS DISTINCT FROM frozen_cv
  OR eff->>'descriptor_digest' IS DISTINCT FROM frozen THEN
  RETURN jsonb_build_object('available',false,'reason','effective'); END IF;
 RETURN jsonb_build_object('available',true,'descriptor',eff->'descriptor',
  'descriptor_digest',frozen,'contract_version',c.contract_version,
  'capability',eff->'descriptor'->>'capability');
END $$;
CREATE FUNCTION v24_cordis.claim_execution(p_eff v24_cordis.effects) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE b jsonb; overlay jsonb; rule jsonb; r v24_cordis.runs%ROWTYPE; k text;
BEGIN
 IF p_eff.kind='listener_call' THEN
  IF p_eff.parent_id IS NULL OR p_eff.input->'descriptor'->'exec'->>'type'<>'host'
   OR NOT EXISTS(SELECT 1 FROM v24_cordis.effects d WHERE d.id=p_eff.parent_id
    AND d.kind='dispatch' AND (d.input->'listeners'->(p_eff.ordinal))->>'contribution_id'
     =p_eff.input->>'contribution_id') THEN RETURN jsonb_build_object('invalid',true); END IF;
  RETURN jsonb_build_object('execution',jsonb_build_object('descriptor',p_eff.input->'descriptor',
   'descriptor_digest',p_eff.input->>'descriptor_digest'));
 END IF;
 IF p_eff.kind NOT IN ('model_call','tool_call') OR p_eff.run_id IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO r FROM v24_cordis.runs WHERE id=p_eff.run_id;
 IF NOT FOUND THEN RETURN jsonb_build_object('invalid',true); END IF;
 k:=p_eff.input->>'key';
 SELECT i.overlay INTO overlay FROM v24_cordis.pins p
  JOIN v24_cordis.contributions c ON c.id=p.contribution_id
  JOIN v24_cordis.fibers f ON f.id=c.fiber_id
  JOIN v24_cordis.installs i ON i.id=f.install_id
  WHERE p.id=(p_eff.input->>'pin_id')::uuid AND p.consumer_run_id=p_eff.run_id;
 IF NOT FOUND THEN RETURN jsonb_build_object('invalid',true); END IF;
 rule:=v24_cordis.intercept_for(r.scope_id,
  coalesce(v24_cordis.service_realm(r.scope_id,k),'root'),k);
 IF (jsonb_typeof(overlay->'services')='object' AND overlay->'services' ? k)
  OR rule->>'action' IN ('replace','reject','invalid') THEN
  b:=v24_cordis.run_binding_desc(p_eff.run_id,(p_eff.input->>'pin_id')::uuid,k);
  IF NOT coalesce((b->>'available')::boolean,false) THEN
   RETURN jsonb_build_object('dependency',true); END IF;
  IF b->>'capability' IS DISTINCT FROM p_eff.kind THEN
   RETURN jsonb_build_object('invalid',true); END IF;
  RETURN jsonb_build_object('execution',jsonb_build_object('descriptor',b->'descriptor',
   'descriptor_digest',b->'descriptor_digest'));
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.run_progress(p_run uuid,p_eff uuid,p_kind text,p_step int,p_budget int,
 p_phase text,p_sealed boolean,p_reason text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('entity_type','run','entity_id',to_jsonb(p_run),'event_kind','run_progress',
  'payload',jsonb_build_object('run_id',to_jsonb(p_run),'effect_id',to_jsonb(p_eff),
   'effect_kind',p_kind,'step',p_step,'remaining_steps',p_budget,'phase',p_phase,
   'sealed',p_sealed,'reason',CASE WHEN p_reason IS NULL THEN 'null'::jsonb ELSE to_jsonb(p_reason) END))
$$;
CREATE FUNCTION v24_cordis.run_seal_result(p_body jsonb,p_intent jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('v',1,'reason',p_intent->>'reason',
  'output',CASE p_intent->>'reason' WHEN 'final' THEN p_body->'result'
   WHEN 'model_failed' THEN p_body->'error' ELSE '{}'::jsonb END,
  'dropped_tool_calls',(p_intent->>'dropped_tool_calls')::int)
$$;
-- P2: the only legal model/tool unknown body is exactly {kind}, kind=effect kind.
CREATE FUNCTION v24_cordis.unknown_body_valid(p_kind text,p_body jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(v24_cordis.exact_keys(p_body,ARRAY['kind']),false)
  AND p_body->>'kind' IS NOT DISTINCT FROM p_kind
$$;
CREATE FUNCTION v24_cordis.unknown_delta() RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','unknown'),
  'events','[]'::jsonb,'successors','[]'::jsonb)
$$;
CREATE FUNCTION v24_cordis.run_refused(p_eff uuid,p_reason text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('entity_type','run','entity_id',to_jsonb(p_eff),'event_kind','run_refused',
  'payload',jsonb_build_object('run_id','null'::jsonb,'effect_id',to_jsonb(p_eff),'reason',p_reason))
$$;
-- Canonical projections shared by run_delta and validate_run_domain. The
-- validator calls these directly from DB/receipt/reducer facts and never
-- trusts the submitted delta or asks run_delta for its expected values.
CREATE FUNCTION v24_cordis.run_successor_binding(p_run uuid,p_key text,p_cap text) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE pin_id uuid; pin_key text; pin_contrib uuid; pin_desc jsonb; contract jsonb; b jsonb;
BEGIN
 SELECT p.id,p.key,p.contribution_id,mc.descriptor
  INTO pin_id,pin_key,pin_contrib,pin_desc
  FROM v24_cordis.pins p JOIN v24_cordis.contributions mc ON mc.id=p.contribution_id
  WHERE p.consumer_run_id=p_run AND p.released_at IS NULL AND mc.released_at IS NULL
   AND mc.descriptor->>'capability'=p_cap
   AND (p_key IS NULL OR p.key=p_key)
   AND (p_cap<>'model_call' OR v24_cordis.pin_readable(p.id));
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
 SELECT i.contracts->p_cap INTO contract
  FROM v24_cordis.contributions cc JOIN v24_cordis.fibers f ON f.id=cc.fiber_id
  JOIN v24_cordis.installs i ON i.id=f.install_id WHERE cc.id=pin_contrib;
 IF contract IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 b:=v24_cordis.run_binding_desc(p_run,pin_id,pin_key);
 IF NOT coalesce((b->>'available')::boolean,false)
  OR b->>'capability' IS DISTINCT FROM p_cap THEN
  RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
 RETURN jsonb_build_object('pin_id',to_jsonb(pin_id),'key',pin_key,
  'descriptor_digest',b->>'descriptor_digest',
  'contract',jsonb_build_object('contract_version',contract->>'contract_version',
   'handler_digest',contract->>'handler_digest'));
END $$;
CREATE FUNCTION v24_cordis.run_successors(p_eff v24_cordis.effects,p_intents jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE it jsonb; out jsonb:='[]'::jsonb; b jsonb;
BEGIN
 FOR it IN SELECT value FROM jsonb_array_elements(p_intents) LOOP
  IF it->>'type' NOT IN ('emit_tool','emit_model') THEN CONTINUE; END IF;
  b:=v24_cordis.run_successor_binding(p_eff.run_id,
   CASE WHEN it->>'type'='emit_tool' THEN it->>'key' END,
   CASE WHEN it->>'type'='emit_tool' THEN 'tool_call' ELSE 'model_call' END);
  IF b ? 'error' THEN RETURN b; END IF;
  IF it->>'type'='emit_tool' THEN
   out:=out||jsonb_build_array(jsonb_build_object('ordinal',(it->>'ordinal')::int,'kind','tool_call',
    'input',jsonb_build_object('v',1,'run_id',to_jsonb(p_eff.run_id),'pin_id',b->'pin_id',
     'key',b->>'key','descriptor_digest',b->>'descriptor_digest','call_id',it->>'call_id',
     'args',it->'args','contract',b->'contract')));
  ELSE
   out:=jsonb_build_array(jsonb_build_object('ordinal',0,'kind','model_call','input',
    jsonb_build_object('v',1,'run_id',to_jsonb(p_eff.run_id),'pin_id',b->'pin_id',
     'key',b->>'key','digests',v24_cordis.run_digests(p_eff.run_id),'contract',b->'contract')));
  END IF;
 END LOOP;
 RETURN out;
END $$;
CREATE FUNCTION v24_cordis.run_settle_facts(p_eff v24_cordis.effects,p_r v24_cordis.runs,p_outcome jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE body jsonb:=p_outcome->'body'; pin_id uuid; pin_key text; pin_contrib uuid; pin_released timestamptz;
 newr int; live int:=0; fact jsonb; red jsonb; desc_ jsonb; b jsonb;
BEGIN
 IF p_outcome->>'class' NOT IN ('success','failure') THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF p_eff.kind='tool_call' AND (p_r.state->>'phase'<>'tools' OR NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(p_r.state->'batch') bs WHERE bs->>'ordinal'=p_eff.ordinal::text
   AND bs->>'key'=p_eff.input->>'key' AND bs->>'call_id'=p_eff.input->>'call_id')) THEN
  RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF NOT coalesce(CASE p_eff.kind
  WHEN 'model_call' THEN v24_cordis.exact_keys(p_eff.input,
   ARRAY['v','run_id','pin_id','key','digests','contract'])
  ELSE v24_cordis.exact_keys(p_eff.input,
   ARRAY['v','run_id','pin_id','key','descriptor_digest','call_id','args','contract']) END,false)
  OR p_eff.input->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(p_eff.input->'run_id')
  OR (p_eff.input->>'run_id')::uuid<>p_r.id OR NOT v24_cordis.json_uuid(p_eff.input->'pin_id')
  OR NOT v24_cordis.json_text(p_eff.input->'key')
  OR (p_eff.kind='tool_call' AND (NOT v24_cordis.json_hex64(p_eff.input->'descriptor_digest')
   OR NOT v24_cordis.json_text(p_eff.input->'call_id') OR jsonb_typeof(p_eff.input->'args')<>'object'))
  OR NOT coalesce(v24_cordis.exact_keys(p_eff.input->'contract',
   ARRAY['contract_version','handler_digest']),false)
  OR NOT v24_cordis.run_state_valid(p_r.state) THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 SELECT p.id,p.key,p.contribution_id,p.released_at,mc.descriptor
  INTO pin_id,pin_key,pin_contrib,pin_released,desc_
  FROM v24_cordis.pins p JOIN v24_cordis.contributions mc ON mc.id=p.contribution_id
  WHERE p.id=(p_eff.input->>'pin_id')::uuid AND p.consumer_run_id=p_r.id AND p.key=p_eff.input->>'key';
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF pin_released IS NOT NULL OR NOT v24_cordis.pin_readable(pin_id) THEN
  RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
 IF p_eff.kind='model_call' THEN
  IF p_eff.input->'digests' IS DISTINCT FROM v24_cordis.run_digests(p_r.id)
   OR NOT v24_cordis.model_receipt_valid(p_outcome->>'class',body) THEN
   RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 ELSE
  b:=v24_cordis.run_binding_desc(p_r.id,pin_id,p_eff.input->>'key');
  IF desc_->>'capability'<>'tool_call'
   OR NOT coalesce((b->>'available')::boolean,false)
   OR b->>'descriptor_digest'<>p_eff.input->>'descriptor_digest' THEN
   RETURN v24_cordis.error_v1('dependency_unresolved'); END IF;
  IF NOT v24_cordis.tool_receipt_valid(p_outcome->>'class',body) THEN
   RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  SELECT count(*) INTO live FROM v24_cordis.effects x WHERE x.parent_id=p_eff.parent_id
   AND x.kind='tool_call' AND x.status IN ('ready','claimed') AND x.id<>p_eff.id;
 END IF;
 IF p_r.remaining_steps<1 THEN RETURN v24_cordis.error_v1('budget_exceeded'); END IF;
 newr:=p_r.remaining_steps-1;
 fact:=jsonb_build_object('v',1,'effect_kind',p_eff.kind,'class',p_outcome->>'class',
  'receipt',body,'remaining_steps',newr,'tools',(SELECT coalesce(jsonb_agg(jsonb_build_object(
   'key',p.key,'pin_id',p.id) ORDER BY p.key),'[]'::jsonb) FROM v24_cordis.pins p
    JOIN v24_cordis.contributions mc ON mc.id=p.contribution_id WHERE p.consumer_run_id=p_r.id
     AND p.released_at IS NULL AND mc.descriptor->>'capability'='tool_call'),'live_siblings',live,
  'unknown_in_run',EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.run_id=p_r.id AND x.status='unknown'));
 red:=v24_cordis.reduce_chat_tool(p_r.state,fact);
 IF red ? 'invalid' THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 RETURN jsonb_build_object('newr',newr,'state',red->'state','intents',red->'intents',
  'status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded' ELSE 'failed' END);
END $$;

CREATE FUNCTION v24_cordis.claim_contract(p_eff v24_cordis.effects) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE c jsonb;
BEGIN
 IF p_eff.kind IN ('host_io','run_start') THEN
  SELECT i.contracts->p_eff.kind INTO c FROM v24_cordis.fibers f
   JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=p_eff.fiber_id;
  RETURN c;
 END IF;
 IF p_eff.kind='listener_call' AND p_eff.parent_id IS NOT NULL
  AND p_eff.input->'descriptor'->'exec'->>'type'='host'
  AND v24_cordis.json_uuid(p_eff.input->'provider_fiber_id') THEN
  SELECT i.contracts->'listener_call' INTO c FROM v24_cordis.effects d
   JOIN v24_cordis.effects p ON p.id=d.parent_id AND p.kind='dispatch'
   JOIN v24_cordis.fibers f ON f.id=(d.input->>'provider_fiber_id')::uuid
   JOIN v24_cordis.installs i ON i.id=f.install_id
   WHERE d.id=p_eff.id AND d.input->'contract'->>'contract_version'
     =i.contracts->'listener_call'->>'contract_version'
    AND d.input->'contract'->>'handler_digest'=i.contracts->'listener_call'->>'handler_digest';
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
 fact jsonb; newstate jsonb; result jsonb; succs jsonb:='[]'::jsonb; it jsonb;
 body jsonb:=p_outcome->'body'; newr int; ev jsonb;
 f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 bindings jsonb; model jsonb; runid uuid; steps int; pins jsonb; contract jsonb; state jsonb;
 reason text; live_ok boolean:=false;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('not_found_or_denied'); END IF;
 IF eff.kind IN ('model_call','tool_call') THEN
  IF eff.run_id IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  SELECT * INTO r FROM v24_cordis.runs WHERE id=eff.run_id;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  IF r.ended_at IS NOT NULL OR r.result IS NOT NULL THEN RETURN v24_cordis.error_v1('already_terminal'); END IF;
  IF p_outcome->>'class'='unknown' THEN
   IF v24_cordis.unknown_body_valid(eff.kind,body) IS NOT TRUE THEN
    RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
   RETURN v24_cordis.unknown_delta();
  END IF;
  fact:=v24_cordis.run_settle_facts(eff,r,p_outcome);
  IF fact ? 'error' THEN RETURN fact; END IF;
  newr:=(fact->>'newr')::int; newstate:=fact->'state';
  IF fact->'intents' @> '[{"type":"close_run"}]'::jsonb THEN
   it:=fact->'intents'->0; result:=v24_cordis.run_seal_result(body,it);
   RETURN jsonb_build_object('domain',jsonb_build_array(
     jsonb_build_object('op','run_state','run_id',to_jsonb(r.id),'state',newstate),
     jsonb_build_object('op','run_budget','run_id',to_jsonb(r.id),'remaining_steps',newr),
     jsonb_build_object('op','run_seal','run_id',to_jsonb(r.id),'effect_id',to_jsonb(eff.id),'result',result),
     jsonb_build_object('op','pins_release','fiber_id',to_jsonb(r.owner_fiber_id),
      'episode_id',to_jsonb(r.owner_episode_id),
      'pin_ids',(SELECT coalesce(jsonb_agg(p.id ORDER BY p.key,p.id),'[]'::jsonb)
       FROM v24_cordis.pins p WHERE p.consumer_run_id=r.id AND p.released_at IS NULL))),
    'receipt',jsonb_build_object('status',fact->>'status'),
    'events',jsonb_build_array(v24_cordis.run_progress(r.id,eff.id,eff.kind,(newstate->>'step')::int,
     newr,newstate->>'phase',true,it->>'reason')),'successors','[]'::jsonb);
  END IF;
  succs:=v24_cordis.run_successors(eff,fact->'intents');
  IF succs ? 'error' THEN RETURN succs; END IF;
  RETURN jsonb_build_object('domain',jsonb_build_array(
    jsonb_build_object('op','run_state','run_id',to_jsonb(r.id),'state',newstate),
    jsonb_build_object('op','run_budget','run_id',to_jsonb(r.id),'remaining_steps',newr)),
   'receipt',jsonb_build_object('status',fact->>'status'),
   'events',jsonb_build_array(v24_cordis.run_progress(r.id,eff.id,eff.kind,(newstate->>'step')::int,
    newr,newstate->>'phase',false,NULL)),'successors',succs);
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
  RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','failed'),
   'events',jsonb_build_array(v24_cordis.run_refused(eff.id,'start_failed')),'successors','[]'::jsonb);
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
  RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(v24_cordis.run_refused(eff.id,reason)),'successors','[]'::jsonb);
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
 ev:=v24_cordis.run_progress(runid,eff.id,'run_start',0,steps,'model',false,NULL);
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
DECLARE eff v24_cordis.effects%ROWTYPE; r v24_cordis.runs%ROWTYPE; expect jsonb;
 f v24_cordis.fibers%ROWTYPE; bindings jsonb; model jsonb; runid uuid; reason text;
 live_ok boolean; n_seal int; fact jsonb; newstate jsonb; intents jsonb; newr int; pins jsonb; state jsonb;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 expect:=v24_cordis.run_delta(p_effect_id,p_outcome);
 IF expect IS NULL OR expect ? 'error' OR p_delta IS DISTINCT FROM expect THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_delta')); END IF;
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
  IF p_delta->'domain'<>'[]'::jsonb THEN
   SELECT b INTO model FROM jsonb_array_elements(bindings) b WHERE b->>'capability'='model_call';
   IF NOT coalesce(v24_cordis.json_int(p_outcome->'body'->'steps',1,64),false)
    OR live_ok IS NOT TRUE OR NOT v24_cordis.run_bindings_valid(bindings)
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->'contract'->'replay'
     IS DISTINCT FROM '{"repeat":true,"concurrent":true}'::jsonb) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_delta')); END IF;
   state:=jsonb_build_object('v',1,'origin',eff.id,'step',0,'phase','model','batch','[]'::jsonb,'final',false);
   pins:=(SELECT jsonb_agg(jsonb_build_object('id',v24_cordis.run_pin_id_for(runid,b->>'key'),
     'key',b->>'key','contribution_id',b->'contribution_id','provider_episode_id',
     b->'provider_episode_id','provider_epoch',b->'provider_epoch') ORDER BY b->>'key')
    FROM jsonb_array_elements(bindings) b);
   IF p_delta IS DISTINCT FROM jsonb_build_object('domain',jsonb_build_array(
     jsonb_build_object('op','run_create','id',to_jsonb(runid),'owner_fiber_id',to_jsonb(eff.fiber_id),
      'owner_episode_id',to_jsonb(eff.episode_id),'scope_id',to_jsonb(f.scope_id),'state',state,
      'remaining_steps',(p_outcome->'body'->>'steps')::int),
     jsonb_build_object('op','run_pin_bind','run_id',to_jsonb(runid),'pins',pins)),
    'receipt',jsonb_build_object('status','succeeded'),
    'events',jsonb_build_array(v24_cordis.run_progress(runid,eff.id,'run_start',0,
     (p_outcome->'body'->>'steps')::int,'model',false,NULL)),
    'successors',jsonb_build_array(jsonb_build_object('ordinal',0,'kind','model_call','input',
     jsonb_build_object('v',1,'run_id',to_jsonb(runid),'pin_id',v24_cordis.run_pin_id_for(runid,model->>'key'),
      'key',model->>'key','digests',v24_cordis.run_digests_of(bindings),'contract',jsonb_build_object(
       'contract_version',model->'contract'->>'contract_version',
       'handler_digest',model->'contract'->>'handler_digest'))))) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_delta')); END IF;
  ELSE
   reason:=CASE WHEN p_outcome->>'class'<>'success' THEN 'start_failed'
    WHEN NOT live_ok THEN 'owner_closing'
    WHEN NOT v24_cordis.run_bindings_valid(bindings) THEN NULL
    WHEN EXISTS(SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->'contract'->'replay'
     IS DISTINCT FROM '{"repeat":true,"concurrent":true}'::jsonb) THEN 'replay_right_missing' END;
   IF reason IS NULL OR p_delta IS DISTINCT FROM jsonb_build_object('domain','[]'::jsonb,
    'receipt',jsonb_build_object('status',CASE p_outcome->>'class' WHEN 'success' THEN 'succeeded'
     ELSE 'failed' END),'events',jsonb_build_array(v24_cordis.run_refused(eff.id,reason)),
    'successors','[]'::jsonb) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_start_refusal')); END IF;
  END IF;
 ELSIF eff.kind IN ('model_call','tool_call') THEN
  SELECT * INTO r FROM v24_cordis.runs WHERE id=eff.run_id;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_state')); END IF;
  IF p_outcome->>'class'='unknown' THEN
   IF v24_cordis.unknown_body_valid(eff.kind,p_outcome->'body') IS NOT TRUE
    OR p_delta IS DISTINCT FROM v24_cordis.unknown_delta() THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_unknown')); END IF;
  ELSE
   fact:=v24_cordis.run_settle_facts(eff,r,p_outcome);
   IF fact ? 'error' THEN RETURN v24_cordis.error_v1('invalid_outcome',
    jsonb_build_object('reason','run_facts')); END IF;
   newstate:=fact->'state'; intents:=fact->'intents'; newr:=(fact->>'newr')::int;
   n_seal:=CASE WHEN intents @> '[{"type":"close_run"}]'::jsonb THEN 2 ELSE 0 END;
   expect:=jsonb_build_object('domain',jsonb_build_array(
     jsonb_build_object('op','run_state','run_id',to_jsonb(r.id),'state',newstate),
     jsonb_build_object('op','run_budget','run_id',to_jsonb(r.id),'remaining_steps',newr))
    || CASE WHEN n_seal=2 THEN jsonb_build_array(
     jsonb_build_object('op','run_seal','run_id',to_jsonb(r.id),'effect_id',to_jsonb(p_effect_id),
      'result',v24_cordis.run_seal_result(p_outcome->'body',intents->0)),
     jsonb_build_object('op','pins_release','fiber_id',to_jsonb(r.owner_fiber_id),
      'episode_id',to_jsonb(r.owner_episode_id),'pin_ids',(SELECT coalesce(jsonb_agg(p.id ORDER BY p.key,p.id),
       '[]'::jsonb) FROM v24_cordis.pins p WHERE p.consumer_run_id=r.id AND p.released_at IS NULL)))
     ELSE '[]'::jsonb END,
    'receipt',jsonb_build_object('status',fact->>'status'),
    'events',jsonb_build_array(v24_cordis.run_progress(r.id,eff.id,eff.kind,(newstate->>'step')::int,
     newr,newstate->>'phase',n_seal=2,CASE WHEN n_seal=2 THEN intents->0->>'reason' END)),
    'successors',v24_cordis.run_successors(eff,intents));
   IF p_delta IS DISTINCT FROM expect THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','run_state_delta')); END IF;
  END IF;
 END IF; RETURN NULL;
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
   WHERE eff.kind IN ('model_call','tool_call') AND eff.run_id IS NOT NULL),
 lc AS (SELECT d.id AS disp,jsonb_array_elements(d.input->'listeners') AS item
   FROM eff JOIN v24_cordis.effects d ON d.id=eff.parent_id AND d.kind='dispatch'
   WHERE eff.kind='listener_call'), seed AS (
  SELECT 'effects'::text AS t,p_effect_id::text AS id
  UNION ALL SELECT 'effects',eff.parent_id::text FROM eff WHERE eff.kind='listener_call'
  UNION ALL SELECT 'effects',x.id::text FROM eff JOIN v24_cordis.effects x
   ON x.parent_id=eff.parent_id AND x.kind='listener_call' WHERE eff.kind='listener_call'
  UNION ALL SELECT 'contributions',item->>'contribution_id' FROM lc
  UNION ALL SELECT 'fibers',item->>'provider_fiber_id' FROM lc
  UNION ALL SELECT 'episodes',item->>'provider_episode_id' FROM lc
  UNION ALL SELECT 'pins',p.id::text FROM lc JOIN v24_cordis.pins p
   ON p.consumer_fiber_id=(item->>'provider_fiber_id')::uuid
    AND p.consumer_episode_id=(item->>'provider_episode_id')::uuid AND p.released_at IS NULL
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
