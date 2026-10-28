-- W3 event closure: p4 producer, five modes, virtual receipts, host receipts.
-- DP5 W3: activation event producer, dispatch progress and listener execution.
-- All helpers are private SECURITY INVOKER; only advance writes.
CREATE FUNCTION v24_cordis.event_policy() RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('listeners',16,'created',16,'cascade',16,'depth',4, 'modes',jsonb_build_array('emit','parallel','serial','bail','waterfall'))
$$;
CREATE FUNCTION v24_cordis.listener_exec(p_exec jsonb,p_params jsonb,p_acc jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT CASE
  WHEN p_exec->>'type'<>'in_db' THEN jsonb_build_object('ok',false,'error',jsonb_build_object('code','invalid_exec'))
  WHEN p_exec->>'op'='const' THEN jsonb_build_object('ok',true,'value',p_exec->'value')
  WHEN p_exec->>'op'='acc' THEN jsonb_build_object('ok',true,'value',p_acc)
  WHEN p_exec->>'op'='append' THEN CASE WHEN jsonb_typeof(p_acc)='array'
   THEN jsonb_build_object('ok',true,'value',p_acc||jsonb_build_array(p_exec->'value'))
   ELSE jsonb_build_object('ok',false,'error',jsonb_build_object('code','invalid_acc')) END
  WHEN p_exec->>'op'='fail' THEN jsonb_build_object('ok',false,'error',jsonb_build_object('code',p_exec->>'code'))
  ELSE jsonb_build_object('ok',false,'error',jsonb_build_object('code','invalid_exec')) END
$$;
CREATE FUNCTION v24_cordis.listener_facts(p_contribution uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('found',true,'contribution_id',c.id,'fiber_id',c.fiber_id, 'episode_id',c.episode_id,'epoch',e.epoch,'seq',c.seq,'descriptor',c.descriptor,
  'descriptor_digest',encode(sha256(convert_to(v24_cordis.canonical_json(c.descriptor),'UTF8')),'hex'),
  'contract_version',c.contract_version,'withdrawn',c.withdrawn_at IS NOT NULL, 'released',c.released_at IS NOT NULL,'episode_closed',e.closed_at IS NOT NULL,
  'episode_state',e.state,'fiber_current',f.current_episode_id,'want_on',f.want_on,
  'fiber_disposed',f.disposed_at IS NOT NULL,'fiber_retire',f.retire_started_at IS NOT NULL,
  'fiber_dispose',f.dispose_requested_at IS NOT NULL,'install_state',i.state,'contracts',i.contracts)
 FROM v24_cordis.contributions c JOIN v24_cordis.episodes e ON e.id=c.episode_id
 JOIN v24_cordis.fibers f ON f.id=c.fiber_id JOIN v24_cordis.installs i ON i.id=f.install_id
 WHERE c.id=p_contribution
$$;
CREATE FUNCTION v24_cordis.listener_contract(p_desc jsonb,p_contracts jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT CASE WHEN p_desc->'exec'->>'type'='in_db' THEN jsonb_build_object('contract_version','in_db_v1',
   'handler_digest',encode(sha256(convert_to(v24_cordis.canonical_json(p_desc->'exec'),'UTF8')),'hex'))
  WHEN p_desc->'exec'->>'type'='host' AND p_contracts ? 'listener_call' THEN
   jsonb_build_object('contract_version',p_contracts->'listener_call'->>'contract_version', 'handler_digest',p_contracts->'listener_call'->>'handler_digest') END
$$;
CREATE FUNCTION v24_cordis.listener_call_input(p_dispatch jsonb,p_item jsonb,p_facts jsonb,p_acc jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('v',1,'dispatch_id',(p_dispatch->>'dispatch_id')::uuid,'event','fiber.activated',
  'mode',p_dispatch->>'mode','ordinal',(p_item->>'ordinal')::int,'listener_id',p_item->>'listener_id',
  'contribution_id',p_item->>'contribution_id','provider_fiber_id',p_item->>'provider_fiber_id',
  'provider_episode_id',p_item->>'provider_episode_id','provider_epoch',(p_item->>'provider_epoch')::int,
  'descriptor',p_facts->'descriptor','descriptor_digest',p_item->>'descriptor_digest', 'params',p_dispatch->'params','acc',p_acc,'contract',
  v24_cordis.listener_contract(p_facts->'descriptor',p_facts->'contracts'))
$$;
CREATE FUNCTION v24_cordis.listener_available(p_facts jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce((p_facts->>'found')::boolean,false) AND NOT (p_facts->>'released')::boolean
  AND NOT (p_facts->>'episode_closed')::boolean AND NOT (p_facts->>'fiber_disposed')::boolean
  AND NOT (p_facts->>'fiber_retire')::boolean AND NOT (p_facts->>'fiber_dispose')::boolean
  AND p_facts->>'install_state'='installed' AND p_facts->>'episode_state'='active'
  AND (p_facts->>'fiber_current')=(p_facts->>'episode_id') AND (p_facts->>'want_on')::boolean
$$;
CREATE FUNCTION v24_cordis.dispatch_fold(p_input jsonb,p_rows jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE snap jsonb:=p_input->'listeners'; mode text:=p_input->>'mode'; n int; i int; m jsonb;
 row jsonb; status text; src text; value jsonb; proj jsonb; first jsonb:='null'::jsonb;
 projections jsonb:='[]'; called jsonb:='[]'; joined int:=0; unknown boolean:=false;
 bailed boolean:=false; next_ord int; prefix boolean:=true; sealed boolean:=false; seq boolean;
BEGIN
 IF mode NOT IN ('emit','parallel','serial','bail','waterfall') OR jsonb_typeof(snap)<>'array' THEN
  RETURN jsonb_build_object('invalid',true); END IF;
 n:=jsonb_array_length(snap); next_ord:=n; seq:=mode IN ('serial','bail','waterfall');
 SELECT coalesce(jsonb_object_agg(r->>'ordinal',r),'{}') INTO m FROM jsonb_array_elements(p_rows) r;
 FOR i IN 0..n-1 LOOP
  row:=m->(i::text);
  IF row IS NULL THEN IF seq THEN next_ord:=i; EXIT; END IF; CONTINUE; END IF;
  status:=row->>'status';
  IF status IN ('ready','claimed') THEN IF seq THEN next_ord:=i; EXIT; END IF; CONTINUE; END IF;
  IF status='unknown' THEN unknown:=true; IF seq THEN next_ord:=i; EXIT; END IF; CONTINUE; END IF;
  joined:=joined+1; src:=row->>'source';
  IF src<>'unavailable' THEN called:=called||jsonb_build_array(row->'listener_id'); END IF;
  IF status='succeeded' THEN value:=row->'outcome'->'body'->'result'->'value';
  ELSE value:='null'::jsonb; END IF;
  proj:=CASE WHEN status='succeeded' THEN value
   ELSE jsonb_build_object('error',row->'outcome'->'body'->'error') END;
  projections:=projections||jsonb_build_array(proj);
  IF mode IN ('serial','bail') AND status='succeeded' AND jsonb_typeof(value)='object'
   AND jsonb_typeof(value->'bail')='boolean' AND value->'bail'='true' THEN
   IF NOT bailed THEN first:=value; END IF; bailed:=true; END IF;
 END LOOP;
 IF seq AND next_ord<n AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_rows) r
  WHERE (r->>'ordinal')::int>next_ord) THEN prefix:=false; END IF;
 sealed:=CASE mode WHEN 'emit' THEN true
  WHEN 'parallel' THEN joined=n AND NOT unknown
  WHEN 'serial' THEN bailed OR (joined=n AND NOT unknown)
  WHEN 'bail' THEN bailed OR (joined=n AND NOT unknown)
  ELSE joined=n AND NOT unknown END;
 RETURN jsonb_build_object('mode',mode,'n',n,'joined',joined,'called',called, 'projections',projections,'unknown',unknown,'bailed',bailed,'next_ordinal',next_ord,
  'prefix_ok',prefix,'sealed',sealed,'acc',CASE mode WHEN 'parallel' THEN projections
   WHEN 'serial' THEN projections WHEN 'bail' THEN first
   WHEN 'waterfall' THEN CASE WHEN joined=0 THEN p_input->'params' ELSE proj END
   ELSE projections END);
END $$;
CREATE FUNCTION v24_cordis.dispatch_progress(p_dispatch_id uuid,p_virtual jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE d v24_cordis.effects%ROWTYPE; rows jsonb; v jsonb;
BEGIN
 SELECT * INTO d FROM v24_cordis.effects WHERE id=p_dispatch_id AND kind='dispatch';
 IF NOT FOUND THEN RETURN jsonb_build_object('invalid',true); END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('ordinal',x.ordinal,'effect_id',x.id, 'listener_id',x.input->>'listener_id','source',CASE
   WHEN x.outcome->'body'->'error'->>'code'='listener_unavailable' THEN 'unavailable'
   WHEN x.input->'descriptor'->'exec'->>'type'='host' THEN 'host' ELSE 'in_db' END, 'status',x.status,'outcome',x.outcome) ORDER BY x.ordinal),'[]')
  INTO rows FROM v24_cordis.effects x WHERE x.parent_id=d.id AND x.kind='listener_call';
 FOR v IN SELECT value FROM jsonb_array_elements(coalesce(p_virtual,'[]')) LOOP
  rows:=coalesce((SELECT jsonb_agg(CASE WHEN (r->>'effect_id')=(v->>'effect_id') THEN r||v ELSE r END
   ORDER BY (r->>'ordinal')::int) FROM jsonb_array_elements(rows) r),'[]');
  IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(rows) r WHERE (r->>'effect_id')=(v->>'effect_id')) THEN
   rows:=rows||jsonb_build_array(v); END IF;
 END LOOP;
 RETURN v24_cordis.dispatch_fold(d.input,rows);
END $$;
CREATE FUNCTION v24_cordis.activation_scope_chain(p_scope uuid) RETURNS uuid[]
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH RECURSIVE a(id,parent_id,depth,path,cycle) AS ( SELECT s.id,s.parent_id,0,ARRAY[s.id],false FROM v24_cordis.scopes s WHERE s.id=p_scope
  UNION ALL
  SELECT s.id,s.parent_id,a.depth+1,a.path||s.id,s.id=ANY(a.path)
   FROM a JOIN v24_cordis.scopes s ON s.id=a.parent_id WHERE NOT a.cycle AND a.depth<512)
 SELECT coalesce(array_agg(id ORDER BY depth),ARRAY[]::uuid[]) FROM a WHERE NOT cycle
$$;
CREATE FUNCTION v24_cordis.activation_candidates(p_fiber uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH src AS (SELECT f.id,f.scope_id,f.current_episode_id,f.want_on,f.disposed_at,f.retire_started_at,
   f.dispose_requested_at FROM v24_cordis.fibers f WHERE f.id=p_fiber)
 SELECT coalesce(jsonb_agg(jsonb_build_object('listener_id',c.descriptor->>'listener_id',
  'contribution_id',c.id,'provider_fiber_id',c.fiber_id,'provider_episode_id',c.episode_id, 'provider_epoch',e.epoch,'descriptor',c.descriptor,
  'descriptor_digest',encode(sha256(convert_to(v24_cordis.canonical_json(c.descriptor),'UTF8')),'hex'),
  'contract_version',c.contract_version,'mode',c.descriptor->>'mode','seq',c.seq, 'filter',c.descriptor->'filter','contracts',i.contracts,'install_id',i.id)
  ORDER BY (c.descriptor->>'priority')::int DESC,c.seq,c.fiber_id,c.episode_id,c.id),'[]')
 FROM src s JOIN v24_cordis.fibers f ON f.scope_id=ANY(v24_cordis.activation_scope_chain(s.scope_id))
 JOIN v24_cordis.episodes e ON e.fiber_id=f.id
 JOIN v24_cordis.contributions c ON c.episode_id=e.id AND c.fiber_id=f.id
 JOIN v24_cordis.installs i ON i.id=f.install_id
 WHERE c.kind='listener' AND c.descriptor->>'event'='fiber.activated'
  AND c.withdrawn_at IS NULL AND c.released_at IS NULL AND e.closed_at IS NULL
  AND i.state='installed' AND s.want_on AND s.disposed_at IS NULL
  AND s.retire_started_at IS NULL AND s.dispose_requested_at IS NULL
  AND (f.id=s.id AND e.id=s.current_episode_id
   OR f.id<>s.id AND e.state='active' AND f.current_episode_id=e.id AND f.want_on
    AND f.retire_started_at IS NULL AND f.dispose_requested_at IS NULL AND f.disposed_at IS NULL
    AND coalesce((v24_cordis.fiber_live_state(f.id,e.id)->>'live')::boolean,false))
$$;
CREATE FUNCTION v24_cordis.activation_candidate_refs(p_fiber uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH src AS (SELECT f.id,f.scope_id,f.current_episode_id FROM v24_cordis.fibers f WHERE f.id=p_fiber),
 cand AS (SELECT value c FROM jsonb_array_elements(v24_cordis.activation_candidates(p_fiber))), refs AS ( SELECT jsonb_build_object('t','scopes','id',s::text) r FROM src
   CROSS JOIN LATERAL unnest(v24_cordis.activation_scope_chain(src.scope_id)) s
  UNION ALL SELECT jsonb_build_object('t','fibers','id',src.id::text) FROM src
  UNION ALL SELECT jsonb_build_object('t','episodes','id',src.current_episode_id::text) FROM src
  UNION ALL SELECT jsonb_build_object('t',v.t,'id',v.id) FROM cand CROSS JOIN LATERAL (VALUES
   ('installs',c->>'install_id'),('fibers',c->>'provider_fiber_id'), ('episodes',c->>'provider_episode_id'),('contributions',c->>'contribution_id')) v(t,id))
 SELECT coalesce(jsonb_agg(DISTINCT r),'[]') FROM refs
$$;
CREATE FUNCTION v24_cordis.activation_event_plan(p_fiber uuid,p_effect uuid,p_actor text) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; start jsonb; cands jsonb;
 params jsonb; modes text[]:=ARRAY['emit','parallel','serial','bail','waterfall']; mode text;
 items jsonb; n int; i int; it jsonb; snap jsonb; dinput jsonb; input jsonb; did uuid; ord int; m int:=0;
 r int; rows jsonb; selected jsonb; exec jsonb; outcome jsonb; acc jsonb; contract jsonb;
 fold jsonb; result jsonb; succ jsonb:='[]'; ops jsonb:='[]'; gops jsonb; created int:=0;
 bail_hit boolean; total int; source text;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'reloading' THEN
  RETURN jsonb_build_object('error','phase'); END IF;
 start:=v24_cordis.run_start_successor(f.id); r:=jsonb_array_length(start);
 params:=jsonb_build_object('fiber_id',f.id,'episode_id',ep.id,'epoch',ep.epoch);
 cands:=v24_cordis.activation_candidates(f.id);
 FOR mode IN SELECT unnest(modes) LOOP
  items:='[]';
  FOR it IN SELECT value FROM jsonb_array_elements(cands) c LOOP
   IF it->>'mode'=mode AND (it->'filter'='null'::jsonb OR
    v24_cordis.check_policy_ok(it->'filter',params)) THEN items:=items||jsonb_build_array(it); END IF;
  END LOOP;
  n:=jsonb_array_length(items);
  IF n=0 THEN CONTINUE; END IF;
  IF n>16 THEN RETURN jsonb_build_object('error','budget'); END IF;
  snap:='[]';
  FOR i IN 0..n-1 LOOP
   it:=items->i;
   snap:=snap||jsonb_build_array(jsonb_build_object('listener_id',it->>'listener_id',
    'contribution_id',it->>'contribution_id','provider_fiber_id',it->>'provider_fiber_id',
    'provider_episode_id',it->>'provider_episode_id','provider_epoch',(it->>'provider_epoch')::int, 'descriptor_digest',it->>'descriptor_digest','ordinal',i));
  END LOOP;
  ord:=r+m; did:=v24_cordis.successor_effect_id(p_actor,p_effect,ord,'dispatch');
  dinput:=jsonb_build_object('v',1,'dispatch_id',did,'event','fiber.activated','mode',mode, 'params',params,'bail',mode IN ('serial','bail'),'listeners',snap);
  IF NOT v24_cordis.valid_body(dinput) THEN RETURN jsonb_build_object('error','input'); END IF;
  rows:='[]'; selected:='[]'; gops:=jsonb_build_array(jsonb_build_object('op','dispatch_open','dispatch_id',did));
  acc:=CASE WHEN mode='waterfall' THEN params ELSE 'null'::jsonb END;
  bail_hit:=false;
  FOR i IN 0..n-1 LOOP
   it:=items->i;
   EXIT WHEN mode NOT IN ('emit','parallel') AND i>0 AND
    (EXISTS(SELECT 1 FROM jsonb_array_elements(rows) x WHERE (x->>'ordinal')::int=i-1 AND x->>'source'='host')
     OR bail_hit);
   contract:=v24_cordis.listener_contract(it->'descriptor',it->'contracts');
   input:=jsonb_build_object('v',1,'dispatch_id',did,'event','fiber.activated','mode',mode,
    'ordinal',i,'listener_id',it->>'listener_id','contribution_id',it->>'contribution_id',
    'provider_fiber_id',it->>'provider_fiber_id','provider_episode_id',it->>'provider_episode_id',
    'provider_epoch',(it->>'provider_epoch')::int,'descriptor',it->'descriptor',
    'descriptor_digest',it->>'descriptor_digest','params',params,'acc',acc,'contract',contract);
   IF NOT v24_cordis.valid_body(input) THEN RETURN jsonb_build_object('error','input'); END IF;
   gops:=gops||jsonb_build_array(jsonb_build_object('op','listener_append','dispatch_id',did, 'ordinal',i,'input',input));
   selected:=selected||jsonb_build_array(i::text); created:=created+1;
   IF it->'descriptor'->'exec'->>'type'='in_db' THEN
    exec:=v24_cordis.listener_exec(it->'descriptor'->'exec',params,acc);
    IF (exec->>'ok')::boolean THEN
     outcome:=jsonb_build_object('v',1,'class','success','claim','null'::jsonb,
      'body',jsonb_build_object('kind','listener_call','result',jsonb_build_object('value',exec->'value')));
     rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',i,'effect_id',
      v24_cordis.successor_effect_id(p_actor,did,i,'listener_call'),'listener_id',it->>'listener_id', 'source','in_db','status','succeeded','outcome',outcome));
     gops:=gops||jsonb_build_array(jsonb_build_object('op','listener_settle', 'effect_id',v24_cordis.successor_effect_id(p_actor,did,i,'listener_call'),
      'source','in_db','outcome',outcome));
     IF mode='waterfall' THEN acc:=exec->'value'; END IF;
     IF mode IN ('serial','bail') AND jsonb_typeof(exec->'value')='object'
      AND jsonb_typeof(exec->'value'->'bail')='boolean' AND exec->'value'->'bail'='true' THEN
      bail_hit:=true; END IF;
    ELSE
     outcome:=jsonb_build_object('v',1,'class','failure','claim','null'::jsonb, 'body',jsonb_build_object('kind','listener_call','error',exec->'error'));
     rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',i,'effect_id',
      v24_cordis.successor_effect_id(p_actor,did,i,'listener_call'),'listener_id',it->>'listener_id', 'source','in_db','status','failed','outcome',outcome));
     gops:=gops||jsonb_build_array(jsonb_build_object('op','listener_settle', 'effect_id',v24_cordis.successor_effect_id(p_actor,did,i,'listener_call'),
      'source','in_db','outcome',outcome));
     IF mode='waterfall' THEN acc:=jsonb_build_object('error',exec->'error'); END IF;
    END IF;
   ELSE
    rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',i,'effect_id',
     v24_cordis.successor_effect_id(p_actor,did,i,'listener_call'),'listener_id',it->>'listener_id', 'source','host','status','ready','outcome','null'::jsonb));
   END IF;
  END LOOP;
  fold:=v24_cordis.dispatch_fold(dinput,rows);
  IF fold ? 'invalid' THEN RETURN jsonb_build_object('error','fold'); END IF;
  result:=CASE WHEN mode='emit' THEN jsonb_build_object('v',1,'mode','emit', 'generated',(SELECT jsonb_agg(x->'listener_id' ORDER BY (x->>'ordinal')::int)
     FROM jsonb_array_elements(snap) x))
   WHEN fold->>'sealed'='true' THEN jsonb_build_object('v',1,'mode',mode,'acc',fold->'acc',
    'joined',(fold->>'joined')::int,'called',fold->'called','bailed',(fold->>'bailed')::boolean) END;
  IF result IS NOT NULL THEN
   gops:=gops||jsonb_build_array(jsonb_build_object('op','dispatch_settle','dispatch_id',did,'result',result));
  END IF;
  ops:=ops||gops; succ:=succ||jsonb_build_array(jsonb_build_object('ordinal',ord,'kind','dispatch','input',dinput));
  m:=m+1;
  total:=r+m+created;
  IF total>16 THEN RETURN jsonb_build_object('error','budget'); END IF;
 END LOOP;
 RETURN jsonb_build_object('successors',start||succ,'ops',ops);
END $$;
CREATE FUNCTION v24_cordis.activation_successors(p_fiber uuid,p_effect uuid,p_actor text) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT v24_cordis.activation_event_plan(p_fiber,p_effect,p_actor)->'successors'
$$;
CREATE FUNCTION v24_cordis.listener_call_readable(p_input jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE d v24_cordis.effects%ROWTYPE; snap jsonb; item jsonb; facts jsonb; contract jsonb;
BEGIN
 IF NOT coalesce(v24_cordis.exact_keys(p_input,ARRAY['v','dispatch_id','event','mode','ordinal',
  'listener_id','contribution_id','provider_fiber_id','provider_episode_id','provider_epoch', 'descriptor','descriptor_digest','params','acc','contract']),false)
  OR p_input->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(p_input->'dispatch_id')
  OR NOT v24_cordis.json_int(p_input->'ordinal',0,15)
  OR NOT v24_cordis.json_uuid(p_input->'contribution_id')
  OR NOT v24_cordis.json_hex64(p_input->'descriptor_digest')
  OR jsonb_typeof(p_input->'params')<>'object'
  OR NOT coalesce(v24_cordis.exact_keys(p_input->'contract',ARRAY['contract_version','handler_digest']),false)
  OR NOT v24_cordis.json_text(p_input->'contract'->'contract_version')
  OR NOT v24_cordis.json_hex64(p_input->'contract'->'handler_digest') THEN
  RETURN jsonb_build_object('ok',false,'reason','input'); END IF;
 SELECT * INTO d FROM v24_cordis.effects WHERE id=(p_input->>'dispatch_id')::uuid AND kind='dispatch';
 IF NOT FOUND OR jsonb_typeof(d.input->'listeners')<>'array' THEN
  RETURN jsonb_build_object('ok',false,'reason','dispatch'); END IF;
 snap:=d.input->'listeners'; item:=snap->(p_input->>'ordinal')::int;
 IF item IS NULL OR item->>'listener_id' IS DISTINCT FROM p_input->>'listener_id'
  OR item->>'contribution_id' IS DISTINCT FROM p_input->>'contribution_id'
  OR item->>'provider_fiber_id' IS DISTINCT FROM p_input->>'provider_fiber_id'
  OR item->>'provider_episode_id' IS DISTINCT FROM p_input->>'provider_episode_id'
  OR (item->>'provider_epoch')::int IS DISTINCT FROM (p_input->>'provider_epoch')::int
  OR item->>'descriptor_digest' IS DISTINCT FROM p_input->>'descriptor_digest'
  OR d.input->>'mode' IS DISTINCT FROM p_input->>'mode'
  OR d.input->'params' IS DISTINCT FROM p_input->'params' THEN
  RETURN jsonb_build_object('ok',false,'reason','snapshot'); END IF;
 facts:=v24_cordis.listener_facts((p_input->>'contribution_id')::uuid);
 IF facts IS NULL OR (facts->>'fiber_id') IS DISTINCT FROM p_input->>'provider_fiber_id'
  OR (facts->>'episode_id') IS DISTINCT FROM p_input->>'provider_episode_id'
  OR (facts->>'epoch')::int IS DISTINCT FROM (p_input->>'provider_epoch')::int
  OR facts->>'descriptor_digest' IS DISTINCT FROM p_input->>'descriptor_digest'
  OR facts->'descriptor' IS DISTINCT FROM p_input->'descriptor'
  OR facts->>'contract_version' IS DISTINCT FROM p_input->'contract'->>'contract_version'
  OR (facts->>'released')::boolean OR (facts->>'episode_closed')::boolean
  OR (facts->>'fiber_disposed')::boolean OR facts->>'install_state'<>'installed' THEN
  RETURN jsonb_build_object('ok',false,'reason','provider'); END IF;
 contract:=v24_cordis.listener_contract(facts->'descriptor',facts->'contracts');
 IF contract IS DISTINCT FROM p_input->'contract' THEN
  RETURN jsonb_build_object('ok',false,'reason','contract'); END IF;
 RETURN jsonb_build_object('ok',true,'facts',facts);
END $$;
CREATE FUNCTION v24_cordis.event_delta(p_effect_id uuid,p_outcome jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE eff v24_cordis.effects%ROWTYPE; d v24_cordis.effects%ROWTYPE; snap jsonb; item jsonb;
 mode text; cls text:=p_outcome->>'class'; rstatus text; body jsonb:=p_outcome->'body'; read jsonb; facts jsonb;
 rows jsonb; fold jsonb; ops jsonb:='[]'; ev jsonb:='[]'; input jsonb; contract jsonb; exec jsonb;
 outcome jsonb; acc jsonb; next int; n int; i int; created int:=0; result jsonb; src text; cstatus text;
 status text; err jsonb; payload jsonb;
BEGIN
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 IF NOT FOUND OR eff.kind<>'listener_call' OR eff.parent_id IS NULL THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_call')); END IF;
 SELECT * INTO d FROM v24_cordis.effects WHERE id=eff.parent_id AND kind='dispatch';
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispatch')); END IF;
 read:=v24_cordis.listener_call_readable(eff.input);
 IF NOT coalesce((read->>'ok')::boolean,false) THEN
  RETURN v24_cordis.error_v1('dependency_unresolved',jsonb_build_object('reason','listener_provider')); END IF;
 IF cls='unknown' THEN
  IF NOT coalesce(v24_cordis.exact_keys(body,ARRAY['kind']),false) OR body->>'kind'<>'listener_call' THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_body')); END IF;
  RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','unknown'), 'events','[]'::jsonb,'successors','[]'::jsonb);
 ELSIF cls='success' THEN
  IF NOT coalesce(v24_cordis.exact_keys(body,ARRAY['kind','result']),false) OR body->>'kind'<>'listener_call'
   OR NOT coalesce(v24_cordis.exact_keys(body->'result',ARRAY['value']),false) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_body')); END IF;
 ELSIF cls='failure' THEN
  IF NOT coalesce(v24_cordis.exact_keys(body,ARRAY['kind','error']),false) OR body->>'kind'<>'listener_call'
   OR NOT v24_cordis.json_text(body->'error'->'code')
   OR NOT (v24_cordis.exact_keys(body->'error',ARRAY['code'])
    OR v24_cordis.exact_keys(body->'error',ARRAY['code','detail']))
   OR (body->'error' ? 'detail' AND jsonb_typeof(body->'error'->'detail')<>'object') THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_body')); END IF;
 ELSE RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_class')); END IF;
 mode:=d.input->>'mode'; snap:=d.input->'listeners';
 IF mode NOT IN ('emit','parallel','serial','bail','waterfall') OR jsonb_typeof(snap)<>'array' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispatch_mode')); END IF;
 n:=jsonb_array_length(snap);
 SELECT coalesce(jsonb_agg(jsonb_build_object('ordinal',x.ordinal,'effect_id',x.id, 'listener_id',x.input->>'listener_id','source',CASE
   WHEN x.outcome->'body'->'error'->>'code'='listener_unavailable' THEN 'unavailable'
   WHEN x.input->'descriptor'->'exec'->>'type'='host' THEN 'host' ELSE 'in_db' END, 'status',x.status,'outcome',x.outcome) ORDER BY x.ordinal),'[]')
  INTO rows FROM v24_cordis.effects x WHERE x.parent_id=d.id AND x.kind='listener_call';
 rstatus:=CASE cls WHEN 'success' THEN 'succeeded' ELSE 'failed' END;
 SELECT coalesce(jsonb_agg(CASE WHEN (r->>'effect_id')=eff.id::text
  THEN r||jsonb_build_object('status',rstatus,'outcome',p_outcome-'receipt_key') ELSE r END
  ORDER BY (r->>'ordinal')::int),'[]') INTO rows FROM jsonb_array_elements(rows) r;
 fold:=v24_cordis.dispatch_fold(d.input,rows);
 IF fold ? 'invalid' OR fold->>'prefix_ok'<>'true' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_prefix')); END IF;
 IF mode<>'emit' AND (fold->>'unknown'='true' OR fold->>'sealed'='true') THEN
  next:=n;
 ELSIF mode='emit' THEN
  next:=n;
 ELSE
  next:=(fold->>'next_ordinal')::int;
  IF mode NOT IN ('serial','bail','waterfall') THEN next:=n; END IF;
  IF next<=eff.ordinal THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_next')); END IF;
  acc:=CASE WHEN mode='waterfall' THEN fold->'acc' ELSE 'null'::jsonb END;
  WHILE next<n LOOP
   item:=snap->next;
   facts:=v24_cordis.listener_facts((item->>'contribution_id')::uuid);
   IF facts IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_facts')); END IF;
   IF NOT coalesce(v24_cordis.listener_available(facts),false)
    OR facts->>'descriptor_digest' IS DISTINCT FROM item->>'descriptor_digest'
    OR (facts->>'fiber_id') IS DISTINCT FROM item->>'provider_fiber_id'
    OR (facts->>'episode_id') IS DISTINCT FROM item->>'provider_episode_id' THEN
    src:='unavailable';
    input:=v24_cordis.listener_call_input(d.input,item,facts,CASE WHEN mode='waterfall' THEN acc ELSE 'null'::jsonb END);
    IF NOT v24_cordis.valid_body(input) THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_input')); END IF;
    outcome:=jsonb_build_object('v',1,'class','failure','claim','null'::jsonb,
     'body',jsonb_build_object('kind','listener_call','error',jsonb_build_object('code','listener_unavailable')));
    ops:=ops||jsonb_build_array(jsonb_build_object('op','listener_append','dispatch_id',d.id,
      'ordinal',next,'input',input),jsonb_build_object('op','listener_settle','effect_id', v24_cordis.successor_effect_id(eff.request_actor,d.id,next,'listener_call'),
      'source','unavailable','outcome',outcome));
    rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',next,'effect_id', v24_cordis.successor_effect_id(eff.request_actor,d.id,next,'listener_call'),
      'listener_id',item->>'listener_id','source','unavailable','status','failed','outcome',outcome));
    created:=created+1;
    IF mode='waterfall' THEN acc:=jsonb_build_object('error',outcome->'body'->'error'); END IF;
   ELSE
    input:=v24_cordis.listener_call_input(d.input,item,facts,CASE WHEN mode='waterfall' THEN acc ELSE 'null'::jsonb END);
    IF NOT v24_cordis.valid_body(input) THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_input')); END IF;
    ops:=ops||jsonb_build_array(jsonb_build_object('op','listener_append','dispatch_id',d.id, 'ordinal',next,'input',input));
    created:=created+1;
    IF facts->'descriptor'->'exec'->>'type'='host' THEN
     rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',next,'effect_id',
      v24_cordis.successor_effect_id(eff.request_actor,d.id,next,'listener_call'),
      'listener_id',item->>'listener_id','source','host','status','ready','outcome','null'::jsonb));
     next:=n; EXIT;
    END IF;
    exec:=v24_cordis.listener_exec(facts->'descriptor'->'exec',d.input->'params',acc);
    IF (exec->>'ok')::boolean THEN
     outcome:=jsonb_build_object('v',1,'class','success','claim','null'::jsonb,
      'body',jsonb_build_object('kind','listener_call','result',jsonb_build_object('value',exec->'value')));
     cstatus:='succeeded';
    ELSE
     outcome:=jsonb_build_object('v',1,'class','failure','claim','null'::jsonb,
      'body',jsonb_build_object('kind','listener_call','error',exec->'error'));
     cstatus:='failed';
    END IF;
    ops:=ops||jsonb_build_array(jsonb_build_object('op','listener_settle','effect_id',
      v24_cordis.successor_effect_id(eff.request_actor,d.id,next,'listener_call'),
      'source','in_db','outcome',outcome));
    rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',next,'effect_id',
      v24_cordis.successor_effect_id(eff.request_actor,d.id,next,'listener_call'),
      'listener_id',item->>'listener_id','source','in_db','status',cstatus,'outcome',outcome));
    IF mode='waterfall' THEN acc:=CASE WHEN cstatus='succeeded' THEN exec->'value'
      ELSE jsonb_build_object('error',exec->'error') END; END IF;
    IF mode IN ('serial','bail') AND cstatus='succeeded' AND jsonb_typeof(exec->'value')='object'
     AND jsonb_typeof(exec->'value'->'bail')='boolean' AND exec->'value'->'bail'='true' THEN
     EXIT; END IF;
   END IF;
   fold:=v24_cordis.dispatch_fold(d.input,rows);
   IF fold->>'sealed'='true' OR fold->>'unknown'='true' THEN EXIT; END IF;
   next:=(fold->>'next_ordinal')::int;
  END LOOP;
 END IF;
 IF created>16 THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_budget')); END IF;
 fold:=v24_cordis.dispatch_fold(d.input,rows);
 IF mode<>'emit' AND fold->>'sealed'='true' THEN
  result:=jsonb_build_object('v',1,'mode',mode,'acc',fold->'acc',
   'joined',(fold->>'joined')::int,'called',fold->'called','bailed',(fold->>'bailed')::boolean);
  ops:=ops||jsonb_build_array(jsonb_build_object('op','dispatch_settle','dispatch_id',d.id,'result',result));
 END IF;
 IF cls IN ('success','failure') THEN
  payload:=jsonb_build_object('dispatch_id',d.id,'effect_id',eff.id,'ordinal',eff.ordinal,
   'mode',mode,'joined',(fold->>'joined')::int,'sealed',(fold->>'sealed')::boolean,
   'bailed',(fold->>'bailed')::boolean);
  ev:=jsonb_build_array(jsonb_build_object('entity_type','effect','entity_id',d.id,
   'event_kind','dispatch_progress','payload',payload));
 END IF;
 RETURN jsonb_build_object('domain',ops,'receipt',jsonb_build_object('status',rstatus),
  'events',ev,'successors','[]'::jsonb);
END $$;
CREATE FUNCTION v24_cordis.validate_event_domain(p_effect_id uuid,p_principal uuid,p_outcome jsonb,
 p_delta jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE eff v24_cordis.effects%ROWTYPE; d v24_cordis.effects%ROWTYPE; expect jsonb; cls text;
 read jsonb; fold jsonb; rows jsonb; ops jsonb; item jsonb; created int:=0; v_input jsonb;
 exec jsonb; outcome jsonb; payload jsonb; result jsonb; status text; n int;
BEGIN
 expect:=v24_cordis.event_delta(p_effect_id,p_outcome);
 IF expect ? 'error' THEN RETURN expect; END IF;
 IF p_delta IS DISTINCT FROM expect THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_delta')); END IF;
 SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
 SELECT * INTO d FROM v24_cordis.effects WHERE id=eff.parent_id AND kind='dispatch';
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispatch')); END IF;
 read:=v24_cordis.listener_call_readable(eff.input);
 IF NOT coalesce((read->>'ok')::boolean,false) THEN
  RETURN v24_cordis.error_v1('dependency_unresolved',jsonb_build_object('reason','listener_provider')); END IF;
 cls:=p_outcome->>'class';
 IF cls='unknown' THEN RETURN NULL; END IF;
 status:=CASE cls WHEN 'success' THEN 'succeeded' ELSE 'failed' END; n:=jsonb_array_length(d.input->'listeners');
 SELECT coalesce(jsonb_agg(jsonb_build_object('ordinal',x.ordinal,'effect_id',x.id,
  'listener_id',x.input->>'listener_id','source',CASE
   WHEN x.outcome->'body'->'error'->>'code'='listener_unavailable' THEN 'unavailable'
   WHEN x.input->'descriptor'->'exec'->>'type'='host' THEN 'host' ELSE 'in_db' END,
  'status',x.status,'outcome',x.outcome) ORDER BY x.ordinal),'[]')
  INTO rows FROM v24_cordis.effects x WHERE x.parent_id=d.id AND x.kind='listener_call';
 SELECT coalesce(jsonb_agg(CASE WHEN (r->>'effect_id')=eff.id::text
  THEN r||jsonb_build_object('status',status,'outcome',p_outcome-'receipt_key') ELSE r END
  ORDER BY (r->>'ordinal')::int),'[]') INTO rows FROM jsonb_array_elements(rows) r;
 fold:=v24_cordis.dispatch_fold(d.input,rows);
 IF fold ? 'invalid' OR fold->>'prefix_ok'<>'true' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_prefix')); END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') LOOP
  IF item->>'op'='listener_append' THEN
   created:=created+1; v_input:=item->'input';
   IF created>16 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','dispatch_id','ordinal','input']),false)
    OR item->>'dispatch_id' IS DISTINCT FROM d.id::text
    OR NOT v24_cordis.json_int(item->'ordinal',0,n-1) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_append')); END IF;
   IF NOT coalesce((v24_cordis.listener_call_readable(v_input)->>'ok')::boolean,false)
    AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_delta->'domain') z
     WHERE z->>'op'='listener_settle' AND z->>'source'='unavailable'
      AND (z->>'effect_id')=v24_cordis.successor_effect_id(eff.request_actor,d.id,
       (item->>'ordinal')::int,'listener_call')::text
      AND z->'outcome'->'body'->'error'->>'code'='listener_unavailable') THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_input')); END IF;
   IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.id=v24_cordis.successor_effect_id(
     eff.request_actor,d.id,(item->>'ordinal')::int,'listener_call') AND (x.parent_id<>d.id
     OR x.ordinal<>(item->>'ordinal')::int OR x.kind<>'listener_call' OR x.input<>v_input
     OR x.run_id IS NOT NULL)) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_row')); END IF;
   rows:=rows||jsonb_build_array(jsonb_build_object('ordinal',(item->>'ordinal')::int,
    'effect_id',v24_cordis.successor_effect_id(eff.request_actor,d.id,(item->>'ordinal')::int,'listener_call'),
    'listener_id',v_input->>'listener_id','source',CASE WHEN v_input->'descriptor'->'exec'->>'type'='host'
     THEN 'host' ELSE 'in_db' END,'status','ready','outcome','null'::jsonb,'input',v_input));
   fold:=v24_cordis.dispatch_fold(d.input,rows);
  ELSIF item->>'op'='listener_settle' THEN
   outcome:=item->'outcome';
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','effect_id','source','outcome']),false)
    OR item->>'source' NOT IN ('in_db','unavailable') OR NOT v24_cordis.json_uuid(item->'effect_id')
    OR jsonb_typeof(outcome)<>'object' OR NOT coalesce(v24_cordis.exact_keys(outcome,
      ARRAY['v','class','claim','body']),false) OR outcome->'claim'<>'null'::jsonb
    OR outcome->'body'->>'kind'<>'listener_call' THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_settle')); END IF;
   SELECT r->'input' INTO v_input FROM jsonb_array_elements(rows) r
    WHERE (r->>'effect_id')=(item->>'effect_id');
   IF v_input IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome',
    jsonb_build_object('reason','listener_settle_row')); END IF;
   IF item->>'source'='in_db' THEN
    exec:=v24_cordis.listener_exec(v_input->'descriptor'->'exec',v_input->'params',v_input->'acc');
    IF (exec->>'ok')::boolean THEN
     IF outcome->>'class'<>'success' OR outcome->'body'->'result'->'value' IS DISTINCT FROM exec->'value' THEN
      RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_exec')); END IF;
    ELSIF outcome->>'class'<>'failure' OR outcome->'body'->'error' IS DISTINCT FROM exec->'error' THEN
     RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_exec')); END IF;
   ELSIF outcome->>'class'<>'failure' OR outcome->'body'->'error'->>'code'<>'listener_unavailable'
    OR coalesce((v24_cordis.listener_call_readable(v_input)->>'ok')::boolean,false) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','listener_unavailable')); END IF;
   SELECT coalesce(jsonb_agg(CASE WHEN (r->>'effect_id')=(item->>'effect_id')
    THEN r||jsonb_build_object('status',CASE WHEN outcome->>'class'='success' THEN 'succeeded' ELSE 'failed' END,
     'outcome',outcome,'source',CASE WHEN item->>'source'='unavailable' THEN 'unavailable' ELSE r->>'source' END)
    ELSE r END ORDER BY (r->>'ordinal')::int),'[]') INTO rows FROM jsonb_array_elements(rows) r;
   fold:=v24_cordis.dispatch_fold(d.input,rows);
  ELSIF item->>'op'='dispatch_settle' THEN
   result:=item->'result';
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','dispatch_id','result']),false)
    OR item->>'dispatch_id' IS DISTINCT FROM d.id::text OR jsonb_typeof(result)<>'object'
    OR result->>'mode' IS DISTINCT FROM d.input->>'mode'
    OR (result->>'joined')::int<>(fold->>'joined')::int
    OR result->'acc' IS DISTINCT FROM fold->'acc' OR result->'called' IS DISTINCT FROM fold->'called'
    OR (result->>'bailed')::boolean<>(fold->>'bailed')::boolean THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispatch_result')); END IF;
  ELSE
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_write_set')); END IF;
 END LOOP;
 IF cls IN ('success','failure') THEN
  payload:=jsonb_build_object('dispatch_id',d.id,'effect_id',eff.id,'ordinal',eff.ordinal,
   'mode',d.input->>'mode','joined',(fold->>'joined')::int,'sealed',(fold->>'sealed')::boolean,
   'bailed',(fold->>'bailed')::boolean);
  IF jsonb_array_length(p_delta->'events')<>1 OR p_delta->'events'->0->>'entity_type'<>'effect'
   OR (p_delta->'events'->0->>'entity_id')::uuid<>d.id
   OR p_delta->'events'->0->>'event_kind'<>'dispatch_progress'
   OR p_delta->'events'->0->'payload' IS DISTINCT FROM payload THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispatch_event')); END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.validate_activation_event(p_effect_id uuid,p_fiber uuid,p_delta jsonb,
 p_actor text) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE plan jsonb; ops jsonb; item jsonb; actual jsonb:='[]'; input jsonb; facts jsonb;
 exec jsonb; created int:=0;
BEGIN
 plan:=v24_cordis.activation_event_plan(p_fiber,p_effect_id,p_actor);
 IF plan ? 'error' THEN RETURN v24_cordis.error_v1('invalid_outcome',
  jsonb_build_object('reason',plan->>'error')); END IF;
 IF p_delta->'successors' IS DISTINCT FROM plan->'successors' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','activation_successors')); END IF;
 ops:=plan->'ops';
 SELECT coalesce(jsonb_agg(x.value ORDER BY x.ord),'[]') INTO actual
  FROM jsonb_array_elements(p_delta->'domain') WITH ORDINALITY x(value,ord)
  WHERE x.value->>'op' IN ('dispatch_open','listener_append','listener_settle','dispatch_settle');
 IF actual IS DISTINCT FROM ops THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','activation_ops')); END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(ops) LOOP
  IF item->>'op'='listener_append' THEN
   created:=created+1; input:=item->'input';
   facts:=v24_cordis.listener_facts((input->>'contribution_id')::uuid);
   IF facts IS NULL OR NOT (coalesce(v24_cordis.listener_available(facts),false)
    OR ((facts->>'fiber_id')=p_fiber::text
     AND (facts->>'episode_id')=(p_delta->'events'->0->'payload'->>'episode_id')
     AND facts->>'episode_state'='reloading'))
    OR facts->'descriptor' IS DISTINCT FROM input->'descriptor'
    OR facts->>'descriptor_digest' IS DISTINCT FROM input->>'descriptor_digest'
    OR v24_cordis.listener_contract(facts->'descriptor',facts->'contracts')
     IS DISTINCT FROM input->'contract' THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','activation_input')); END IF;
  ELSIF item->>'op'='listener_settle' THEN
   IF item->>'source'='in_db' THEN
    SELECT x->'input' INTO input FROM jsonb_array_elements(ops) x
     WHERE x->>'op'='listener_append' AND v24_cordis.successor_effect_id(p_actor,
      (x->'input'->>'dispatch_id')::uuid,(x->>'ordinal')::int,'listener_call')=(item->>'effect_id')::uuid;
    IF input IS NULL THEN RETURN v24_cordis.error_v1('invalid_outcome',
     jsonb_build_object('reason','activation_settle')); END IF;
    exec:=v24_cordis.listener_exec(input->'descriptor'->'exec',input->'params',input->'acc');
    IF ((exec->>'ok')::boolean AND (item->'outcome'->>'class'<>'success'
      OR item->'outcome'->'body'->'result'->'value' IS DISTINCT FROM exec->'value'))
     OR (NOT (exec->>'ok')::boolean AND (item->'outcome'->>'class'<>'failure'
      OR item->'outcome'->'body'->'error' IS DISTINCT FROM exec->'error')) THEN
     RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','activation_exec')); END IF;
   ELSIF item->'outcome'->'body'->'error'->>'code'<>'listener_unavailable' THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','activation_unavailable')); END IF;
  ELSIF item->>'op'='dispatch_settle' AND NOT coalesce(v24_cordis.exact_keys(item,
    ARRAY['op','dispatch_id','result']),false) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','activation_settle')); END IF;
 END LOOP;
 IF created>16 THEN RETURN v24_cordis.error_v1('invalid_outcome',
  jsonb_build_object('reason','activation_budget')); END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.event_apply_postconditions(p_delta jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE item jsonb; d v24_cordis.effects%ROWTYPE; x v24_cordis.effects%ROWTYPE;
BEGIN
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') LOOP
  IF item->>'op' NOT IN ('dispatch_open','listener_append','listener_settle','dispatch_settle') THEN
   CONTINUE; END IF;
  IF item->>'op'='dispatch_open' THEN
   SELECT * INTO d FROM v24_cordis.effects WHERE id=(item->>'dispatch_id')::uuid AND kind='dispatch';
   IF NOT FOUND THEN RAISE EXCEPTION 'dispatch open postcondition' USING ERRCODE='23514'; END IF;
  ELSIF item->>'op'='listener_append' THEN
   SELECT * INTO x FROM v24_cordis.effects WHERE id=v24_cordis.successor_effect_id(
    (SELECT request_actor FROM v24_cordis.effects WHERE id=(item->>'dispatch_id')::uuid),
    (item->>'dispatch_id')::uuid,(item->>'ordinal')::int,'listener_call');
   IF NOT FOUND OR x.parent_id<>(item->>'dispatch_id')::uuid OR x.ordinal<>(item->>'ordinal')::int
    OR x.kind<>'listener_call' OR x.input IS DISTINCT FROM item->'input'
    OR x.run_id IS NOT NULL OR x.fiber_id IS NULL OR x.episode_id IS NULL THEN
    RAISE EXCEPTION 'listener append postcondition' USING ERRCODE='23514'; END IF;
  ELSIF item->>'op'='listener_settle' THEN
   SELECT * INTO x FROM v24_cordis.effects WHERE id=(item->>'effect_id')::uuid;
   IF NOT FOUND OR x.kind<>'listener_call' OR x.status NOT IN ('succeeded','failed')
    OR x.outcome IS DISTINCT FROM item->'outcome' OR x.attempt<>0 OR x.fence<>0
    OR x.claim_owner IS NOT NULL OR x.lease_until IS NOT NULL OR x.settled_at IS NULL THEN
    RAISE EXCEPTION 'listener settle postcondition' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO d FROM v24_cordis.effects WHERE id=(item->>'dispatch_id')::uuid AND kind='dispatch';
   IF NOT FOUND OR d.status<>'succeeded' OR d.outcome IS DISTINCT FROM jsonb_build_object(
    'v',1,'class','success','claim','null'::jsonb,'body',jsonb_build_object('kind','dispatch',
     'result',item->'result')) OR d.attempt<>0 OR d.fence<>0 OR d.claim_owner IS NOT NULL
    OR d.settled_at IS NULL THEN
    RAISE EXCEPTION 'dispatch settle postcondition' USING ERRCODE='23514'; END IF;
  END IF;
 END LOOP;
END $$;
