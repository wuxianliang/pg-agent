-- Canonical teardown module, loaded after 41 and before 50.
-- W2: transitive live, private pin read, P0 control, Divert/Raise/Leave.
-- W3: P6 inverse, pin release, episode close.
-- W4: bounded dispose selector, sealed-subtree admission, single-successor handoff.
CREATE FUNCTION v24_cordis.delta_write_closure_ok(p_delta jsonb,p_closure jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE item jsonb; ref jsonb; pair record; refs jsonb; target uuid; present boolean;
BEGIN
 IF jsonb_typeof(p_closure)<>'array' OR jsonb_array_length(p_closure)>512 THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') LOOP
  refs:='[]'::jsonb;
  IF item ? 'fiber_id' THEN refs:=refs||jsonb_build_array(jsonb_build_object('t','fibers','id',item->'fiber_id')); END IF;
  IF item ? 'episode_id' THEN refs:=refs||jsonb_build_array(jsonb_build_object('t','episodes','id',item->'episode_id')); END IF;
  IF item->>'op' IN ('contributions_withdraw','contribution_inverse') THEN
   SELECT refs||coalesce(jsonb_agg(jsonb_build_object('t','contributions','id',value)),'[]'::jsonb) INTO refs
    FROM jsonb_array_elements(item->'contribution_ids');
  END IF;
  IF item->>'op'='pins_release' THEN
   SELECT refs||coalesce(jsonb_agg(jsonb_build_object('t','pins','id',value)),'[]'::jsonb) INTO refs
    FROM jsonb_array_elements(item->'pin_ids');
  END IF;
  FOR pair IN SELECT * FROM (VALUES
    ('scope_id','scopes'),('install_id','installs'),('parent_id','scopes'),
    ('owner_id','fibers'),('owner_fiber_id','fibers'),('owner_episode_id','episodes'),
    ('run_id','runs'),('effect_id','effects'),
    ('prev_contribution_id','contributions')) pairs(col,t) LOOP
   IF item->>pair.col IS NOT NULL THEN
    refs:=refs||jsonb_build_array(jsonb_build_object('t',pair.t,'id',item->pair.col)); END IF;
  END LOOP;
  IF item->>'op'='episode_begin' THEN
   SELECT refs||coalesce(jsonb_agg(jsonb_build_object('t','contributions','id',value->'contribution_id')),'[]'::jsonb)
    INTO refs FROM jsonb_array_elements(item->'pins');
  END IF;
  IF item->>'op'='run_pin_bind' THEN
   SELECT refs||coalesce(jsonb_agg(jsonb_build_object('t','contributions','id',value->'contribution_id')),'[]'::jsonb)
     ||coalesce(jsonb_agg(jsonb_build_object('t','episodes','id',value->'provider_episode_id')),'[]'::jsonb)
    INTO refs FROM jsonb_array_elements(item->'pins');
  END IF;
  FOR ref IN SELECT value FROM jsonb_array_elements(refs) LOOP
   target:=(ref->>'id')::uuid;
   EXECUTE format('SELECT EXISTS(SELECT 1 FROM v24_cordis.%I WHERE id=$1)',ref->>'t') INTO present USING target;
   IF present AND NOT (p_closure @> jsonb_build_array(ref)) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION v24_cordis.assert_delta_applied(p_delta jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE item jsonb; ok boolean;
BEGIN
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') LOOP
  IF item->>'op' IN ('dispatch_open','listener_append','listener_settle','dispatch_settle') THEN
   CONTINUE; END IF;
  ok:=true;
  CASE item->>'op'
  WHEN 'scope_create' THEN
   SELECT parent_id IS NOT DISTINCT FROM (item->>'parent_id')::uuid
    AND realm_overrides=item->'realm_overrides'
    AND intercept=coalesce(item->'intercept','{}'::jsonb) INTO ok
    FROM v24_cordis.scopes WHERE id=(item->>'id')::uuid;
  WHEN 'install_create' THEN
   SELECT state='installed' AND scope_id=(item->>'scope_id')::uuid
    AND manifest=item->'manifest' AND contracts=item->'contracts'
    AND overlay=item->'overlay' INTO ok
    FROM v24_cordis.installs WHERE id=(item->>'id')::uuid;
  WHEN 'fiber_create' THEN
   SELECT install_id=(item->>'install_id')::uuid AND scope_id=(item->>'scope_id')::uuid
    AND owner_id IS NOT DISTINCT FROM (item->>'owner_id')::uuid AND NOT want_on AND control_seq=0 INTO ok
    FROM v24_cordis.fibers WHERE id=(item->>'id')::uuid;
  WHEN 'episode_begin' THEN
   SELECT e.committed_view=item->'committed_view' AND e.iterator=item->'iterator'
    AND f.current_episode_id=e.id AND e.state='reloading'
    AND v24_cordis.activation_consistent(f.id) IS NULL INTO ok
    FROM v24_cordis.episodes e JOIN v24_cordis.fibers f ON f.id=e.fiber_id
    WHERE e.id=(item->>'id')::uuid;
  WHEN 'install_dispose_request' THEN
   SELECT state='dispose_pending' INTO ok FROM v24_cordis.installs
    WHERE id=(item->>'install_id')::uuid;
  WHEN 'fiber_dispose_request' THEN
   SELECT NOT want_on AND control_seq=(item->>'control_seq')::bigint
    AND dispose_requested_at IS NOT NULL INTO ok
    FROM v24_cordis.fibers WHERE id=(item->>'fiber_id')::uuid;
  WHEN 'fiber_dispose_finish' THEN
   SELECT dispose_requested_at IS NOT NULL AND disposed_at IS NOT NULL INTO ok
    FROM v24_cordis.fibers WHERE id=(item->>'fiber_id')::uuid;
  WHEN 'install_dispose_finish' THEN
   SELECT state='disposed' AND v24_cordis.dispose_block_reason(id) IS NULL
    AND NOT EXISTS(SELECT 1 FROM v24_cordis.fibers f WHERE f.install_id=i.id
     AND f.disposed_at IS NULL) INTO ok
    FROM v24_cordis.installs i WHERE id=(item->>'install_id')::uuid;
  WHEN 'fiber_control' THEN
   SELECT want_on=(item->>'want_on')::boolean AND control_seq=(item->>'control_seq')::bigint INTO ok
    FROM v24_cordis.fibers WHERE id=(item->>'fiber_id')::uuid;
  WHEN 'fiber_retire' THEN
   SELECT retire_started_at IS NOT NULL INTO ok FROM v24_cordis.fibers WHERE id=(item->>'fiber_id')::uuid;
  WHEN 'episode_close_start' THEN
   SELECT e.state='closing' AND e.outcome=item->>'outcome' AND e.closed_at IS NULL
    AND (item->'failure'='null'::jsonb OR f.failure=item->'failure') INTO ok
    FROM v24_cordis.episodes e JOIN v24_cordis.fibers f ON f.current_episode_id=e.id
    WHERE e.id=(item->>'episode_id')::uuid AND f.id=(item->>'fiber_id')::uuid;
  WHEN 'contributions_withdraw' THEN
   SELECT count(*)=jsonb_array_length(item->'contribution_ids') AND coalesce(bool_and(
    withdrawn_at IS NOT NULL AND released_at IS NULL AND fiber_id=(item->>'fiber_id')::uuid
    AND episode_id=(item->>'episode_id')::uuid),true) INTO ok FROM v24_cordis.contributions
    WHERE id IN (SELECT jsonb_array_elements_text(item->'contribution_ids')::uuid);
  WHEN 'contribution_append' THEN
   SELECT descriptor=item->'descriptor' AND inverse=item->'inverse' AND seq=(item->>'seq')::int
    AND fiber_id=(item->>'fiber_id')::uuid AND episode_id=(item->>'episode_id')::uuid
    AND withdrawn_at IS NULL AND released_at IS NULL AND kind=item->>'kind'
    AND realm IS NOT DISTINCT FROM item->>'realm' AND key IS NOT DISTINCT FROM item->>'key'
    AND contract_version=item->>'contract_version'
    AND prev_contribution_id IS NOT DISTINCT FROM (item->>'prev_contribution_id')::uuid
    INTO ok FROM v24_cordis.contributions WHERE id=(item->>'id')::uuid;
  WHEN 'episode_progress' THEN
   SELECT iterator->'next_index'=item->'next_index' AND iterator->'registered_through'=item->'registered_through'
    INTO ok FROM v24_cordis.episodes WHERE id=(item->>'episode_id')::uuid;
  WHEN 'episode_activate' THEN
   SELECT state='active' AND v24_cordis.fiber_live_resolve_ok(fiber_id,id)
    INTO ok FROM v24_cordis.episodes WHERE id=(item->>'episode_id')::uuid;
  WHEN 'contribution_inverse' THEN
   SELECT count(*)=jsonb_array_length(item->'contribution_ids') AND coalesce(bool_and(
    c.released_at IS NOT NULL AND c.withdrawn_at IS NOT NULL
    AND c.fiber_id=(item->>'fiber_id')::uuid AND c.episode_id=(item->>'episode_id')::uuid
    AND (c.prev_contribution_id IS NULL OR EXISTS(
     SELECT 1 FROM v24_cordis.contributions p WHERE p.id=c.prev_contribution_id))),true)
    INTO ok FROM v24_cordis.contributions c
    WHERE c.id IN (SELECT jsonb_array_elements_text(item->'contribution_ids')::uuid);
   IF ok THEN
    SELECT NOT EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL
      AND p.contribution_id IN (SELECT jsonb_array_elements_text(item->'contribution_ids')::uuid)) INTO ok;
   END IF;
  WHEN 'pins_release' THEN
   SELECT count(*)=jsonb_array_length(item->'pin_ids') AND coalesce(bool_and(
    released_at IS NOT NULL AND ((consumer_fiber_id=(item->>'fiber_id')::uuid
      AND consumer_episode_id=(item->>'episode_id')::uuid)
     OR consumer_run_id IN (SELECT id FROM v24_cordis.runs
      WHERE owner_fiber_id=(item->>'fiber_id')::uuid AND owner_episode_id=(item->>'episode_id')::uuid))),true)
    INTO ok FROM v24_cordis.pins
    WHERE id IN (SELECT jsonb_array_elements_text(item->'pin_ids')::uuid);
  WHEN 'run_create' THEN
   SELECT state=item->'state' AND remaining_steps=(item->>'remaining_steps')::int
    AND owner_fiber_id=(item->>'owner_fiber_id')::uuid
    AND owner_episode_id=(item->>'owner_episode_id')::uuid
    AND scope_id=(item->>'scope_id')::uuid AND ended_at IS NULL
    INTO ok FROM v24_cordis.runs WHERE id=(item->>'id')::uuid;
  WHEN 'run_pin_bind' THEN
   SELECT count(*)=jsonb_array_length(item->'pins') AND coalesce(bool_and(
    p.released_at IS NULL AND p.consumer_run_id=(item->>'run_id')::uuid
    AND p.key=x->>'key' AND p.contribution_id=(x->>'contribution_id')::uuid
    AND p.provider_epoch=(x->>'provider_epoch')::int
    AND c.released_at IS NULL AND e.epoch=p.provider_epoch
    AND c.id=p.contribution_id AND e.id=c.episode_id),true)
    INTO ok FROM jsonb_array_elements(item->'pins') x
    JOIN v24_cordis.pins p ON p.id=(x->>'id')::uuid
    JOIN v24_cordis.contributions c ON c.id=p.contribution_id
    JOIN v24_cordis.episodes e ON e.id=c.episode_id;
  WHEN 'run_state' THEN
   SELECT state=item->'state' INTO ok FROM v24_cordis.runs WHERE id=(item->>'run_id')::uuid;
  WHEN 'run_budget' THEN
   SELECT remaining_steps=(item->>'remaining_steps')::int AND remaining_steps>=0
    INTO ok FROM v24_cordis.runs WHERE id=(item->>'run_id')::uuid;
  WHEN 'run_seal' THEN
   SELECT ended_at IS NOT NULL AND result=item->'result'
    AND NOT EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.run_id=r.id
     AND x.id IS DISTINCT FROM (item->>'effect_id')::uuid
     AND (x.kind='host_io' OR x.status IN ('ready','claimed','unknown')))
    INTO ok FROM v24_cordis.runs r WHERE r.id=(item->>'run_id')::uuid;
  WHEN 'episode_close' THEN
   SELECT e.closed_at IS NOT NULL AND e.state='closing'
    AND f.current_episode_id IS NULL AND f.retire_started_at IS NULL
    AND NOT EXISTS(SELECT 1 FROM v24_cordis.contributions c
     WHERE c.fiber_id=f.id AND c.episode_id=e.id AND c.released_at IS NULL)
    AND NOT EXISTS(SELECT 1 FROM v24_cordis.runs r
     WHERE r.owner_fiber_id=f.id AND r.owner_episode_id=e.id AND r.ended_at IS NULL)
    AND NOT EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL AND (
      (p.consumer_fiber_id=f.id AND p.consumer_episode_id=e.id)
      OR p.consumer_run_id IN (SELECT id FROM v24_cordis.runs
        WHERE owner_fiber_id=f.id AND owner_episode_id=e.id)
      OR p.contribution_id IN (SELECT id FROM v24_cordis.contributions
        WHERE fiber_id=f.id AND episode_id=e.id)))
    AND NOT EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.fiber_id=f.id
      AND c.episode_id=e.id AND c.kind='child'
      AND NOT (v24_cordis.json_uuid(c.descriptor->'child_fiber_id') AND EXISTS(
       SELECT 1 FROM v24_cordis.fibers cf WHERE cf.id=(c.descriptor->>'child_fiber_id')::uuid
        AND cf.disposed_at IS NOT NULL)))
    INTO ok FROM v24_cordis.episodes e JOIN v24_cordis.fibers f ON f.id=e.fiber_id
    WHERE e.id=(item->>'episode_id')::uuid AND f.id=(item->>'fiber_id')::uuid;
  ELSE NULL;
  END CASE;
  IF ok IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'domain postcondition failed: %',item->>'op' USING ERRCODE='23514'; END IF;
 END LOOP;
END $$;
CREATE FUNCTION v24_cordis.command_barrier(p_effect_id uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE kind text:=p_outcome->'body'->>'kind'; payload jsonb:=p_outcome->'body'->'payload';
 f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; plan jsonb;
BEGIN
 -- NULL means the command may proceed. Only a closing P6 advance or a dispose refresh
 -- has a DB barrier here.
 IF kind='command_dispose' AND jsonb_typeof(payload)='object'
  AND v24_cordis.json_uuid(payload->'install_id') THEN
  plan:=v24_cordis.dispose_plan((payload->>'install_id')::uuid);
  IF plan->>'kind'='deferred' THEN RETURN jsonb_build_object('disposition','deferred'); END IF;
  IF plan->>'kind'='blocked_unknown' THEN RETURN jsonb_build_object('disposition','blocked_unknown'); END IF;
  IF plan->>'kind'='unsupported' THEN RETURN jsonb_build_object('disposition','unsupported'); END IF;
  RETURN NULL;
 END IF;
 IF kind IS DISTINCT FROM 'command_reconcile' OR jsonb_typeof(payload)<>'object'
  OR payload->>'action' IS DISTINCT FROM 'advance' OR NOT v24_cordis.json_uuid(payload->'fiber_id') THEN
  RETURN NULL; END IF;
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=(payload->>'fiber_id')::uuid;
 IF NOT FOUND OR f.current_episode_id IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'closing' THEN RETURN NULL; END IF;
 plan:=v24_cordis.p6_plan(p_effect_id,f.id);
 IF plan->>'kind'='deferred' THEN RETURN jsonb_build_object('disposition','deferred'); END IF;
 IF plan->>'kind'='blocked_unknown' THEN RETURN jsonb_build_object('disposition','blocked_unknown'); END IF;
 IF plan->>'kind'='unsupported' THEN RETURN jsonb_build_object('disposition','unsupported'); END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.lifecycle_step(p_effect_id uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 -- Selector tag only. advance and interpret_command do not call this function.
 RETURN jsonb_build_object('tag','idle');
END $$;
CREATE FUNCTION v24_cordis.failure_v1(p_control bigint,p_episode uuid,p_phase text,p_code text,p_reason text,p_key text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF p_control IS NULL OR p_control<0 OR p_episode IS NULL OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 128 THEN
  RAISE EXCEPTION 'failure v1 is not exact' USING ERRCODE='22023'; END IF;
 IF NOT coalesce(((p_phase='p2' AND p_code='provide_conflict' AND p_reason='address_conflict')
   OR (p_phase='p2' AND p_code='registration_stale' AND p_reason='contract_drift')
   OR (p_phase='p3' AND p_code='registration_stale' AND p_reason='contract_drift')
   OR (p_phase='p3' AND p_code='provider_unavailable' AND p_reason='check_failed')
   OR (p_phase='p4' AND p_code='registration_stale' AND p_reason='totality_failed')),false) THEN
  RAISE EXCEPTION 'failure v1 is not exact' USING ERRCODE='22023'; END IF;
 RETURN jsonb_build_object('v',1,'control_seq',to_jsonb(p_control),'episode_id',to_jsonb(p_episode),
  'phase',p_phase,'code',p_code,'reason',p_reason,'key',p_key);
END $$;
CREATE FUNCTION v24_cordis.failure_v1_valid(p_failure jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF NOT coalesce(v24_cordis.exact_keys(p_failure,ARRAY['v','control_seq','episode_id','phase','code','reason','key']),false)
  OR p_failure->'v' IS DISTINCT FROM '1'::jsonb
  OR NOT v24_cordis.json_int(p_failure->'control_seq',0,9223372036854775807)
  OR NOT v24_cordis.json_uuid(p_failure->'episode_id')
  OR NOT v24_cordis.json_text(p_failure->'phase')
  OR NOT v24_cordis.json_text(p_failure->'code')
  OR NOT v24_cordis.json_text(p_failure->'reason')
  OR NOT v24_cordis.json_text(p_failure->'key') THEN RETURN false; END IF;
 RETURN (p_failure->>'phase',p_failure->>'code',p_failure->>'reason') IN (
  ('p2','provide_conflict','address_conflict'),('p2','registration_stale','contract_drift'),
  ('p3','registration_stale','contract_drift'),('p3','provider_unavailable','check_failed'),
  ('p4','registration_stale','totality_failed'));
END $$;
CREATE FUNCTION v24_cordis.scope_live_fault(p_scope uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE node uuid:=p_scope; seen uuid[]:=ARRAY[]::uuid[]; s v24_cordis.scopes%ROWTYPE;
BEGIN
 WHILE node IS NOT NULL LOOP
  IF node=ANY(seen) THEN RETURN 'cycle'; END IF;
  IF cardinality(seen)=512 THEN RETURN 'closure_overflow'; END IF;
  seen:=array_append(seen,node);
  SELECT * INTO s FROM v24_cordis.scopes WHERE id=node;
  IF NOT FOUND OR s.closed_at IS NOT NULL THEN RETURN 'scope'; END IF;
  IF NOT v24_cordis.scope_intercept_valid(s.intercept) THEN RETURN 'intercept'; END IF;
  node:=s.parent_id;
 END LOOP;
 IF cardinality(seen)=0 THEN RETURN 'scope'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.live_node_fault(p_fiber uuid,p_episode uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; e v24_cordis.episodes%ROWTYPE; i v24_cordis.installs%ROWTYPE;
 o v24_cordis.fibers%ROWTYPE; oe v24_cordis.episodes%ROWTYPE; fault text;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND THEN RETURN 'missing'; END IF;
 SELECT * INTO e FROM v24_cordis.episodes WHERE id=p_episode AND fiber_id=f.id;
 IF NOT FOUND OR e.closed_at IS NOT NULL OR e.state<>'active' OR f.current_episode_id IS DISTINCT FROM e.id THEN
  RETURN 'not_active'; END IF;
 IF NOT f.want_on THEN RETURN 'want_off'; END IF;
 IF NOT v24_cordis.json_int(e.iterator->'control_seq',0,9223372036854775807)
  OR (e.iterator->>'control_seq')::bigint IS DISTINCT FROM f.control_seq THEN RETURN 'control_drift'; END IF;
 IF f.retire_started_at IS NOT NULL THEN RETURN 'retire'; END IF;
 IF f.dispose_requested_at IS NOT NULL OR f.disposed_at IS NOT NULL THEN RETURN 'dispose'; END IF;
 SELECT * INTO i FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND OR i.state<>'installed' THEN RETURN 'install'; END IF;
 fault:=v24_cordis.lineage_fault(f.owner_id);
 IF fault IS NOT NULL THEN RETURN fault; END IF;
 IF v24_cordis.dispose_ancestor_sealed(f.owner_id) THEN RETURN 'lineage'; END IF;
 IF v24_cordis.install_overlay_valid(i.manifest,i.overlay,i.contracts) IS NOT NULL THEN RETURN 'overlay'; END IF;
 fault:=v24_cordis.scope_live_fault(f.scope_id);
 IF fault IS NOT NULL THEN RETURN fault; END IF;
 IF v24_cordis.activation_total(f.id) IS NOT NULL THEN RETURN 'totality'; END IF;
 IF jsonb_typeof(f.failure)='object' AND v24_cordis.json_int(f.failure->'control_seq',0,9223372036854775807)
  AND (f.failure->>'control_seq')::bigint=f.control_seq THEN RETURN 'failure'; END IF;
 IF f.owner_id IS NOT NULL THEN
  SELECT * INTO o FROM v24_cordis.fibers WHERE id=f.owner_id;
  SELECT * INTO oe FROM v24_cordis.episodes WHERE id=f.owner_episode_id AND fiber_id=o.id;
  IF NOT FOUND OR oe.closed_at IS NOT NULL OR oe.state<>'active' OR o.current_episode_id IS DISTINCT FROM oe.id
   OR NOT o.want_on OR o.retire_started_at IS NOT NULL OR o.dispose_requested_at IS NOT NULL
   OR o.disposed_at IS NOT NULL THEN RETURN 'lineage'; END IF;
  IF jsonb_typeof(o.failure)='object' AND v24_cordis.json_int(o.failure->'control_seq',0,9223372036854775807)
   AND (o.failure->>'control_seq')::bigint=o.control_seq THEN RETURN 'failure'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.fiber_live_state(p_fiber uuid,p_episode uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE sf uuid[]:=ARRAY[p_fiber]; se uuid[]:=ARRAY[p_episode]; st int[]:=ARRAY[0];
 gray jsonb:='{}'::jsonb; seen jsonb:='{}'::jsonb; node uuid; ep uuid; stage int; token text;
 n int:=0; fault text; pin record; view jsonb; digest text; have int; want int; eff jsonb;
BEGIN
 IF p_fiber IS NULL OR p_episode IS NULL THEN
  RETURN jsonb_build_object('live',false,'reason','missing','visited_count',0,'closure_overflow',false,'cycle',false);
 END IF;
 WHILE coalesce(cardinality(sf),0)>0 LOOP
  node:=sf[cardinality(sf)]; ep:=se[cardinality(se)]; stage:=st[cardinality(st)];
  sf:=sf[1:cardinality(sf)-1]; se:=se[1:cardinality(se)-1]; st:=st[1:cardinality(st)-1];
  token:=node::text||'/'||ep::text;
  IF stage=1 THEN gray:=gray-token; CONTINUE; END IF;
  IF gray ? token THEN
   RETURN jsonb_build_object('live',false,'reason','cycle','visited_count',n,'closure_overflow',false,'cycle',true);
  END IF;
  IF seen ? token THEN CONTINUE; END IF;
  n:=n+1;
  IF n>512 THEN
   RETURN jsonb_build_object('live',false,'reason','closure_overflow','visited_count',n,'closure_overflow',true,'cycle',false);
  END IF;
  seen:=seen||jsonb_build_object(token,true); gray:=gray||jsonb_build_object(token,true);
  sf:=array_append(sf,node); se:=array_append(se,ep); st:=array_append(st,1);
  fault:=v24_cordis.live_node_fault(node,ep);
  IF fault IS NOT NULL THEN
   RETURN jsonb_build_object('live',false,'reason',fault,'visited_count',n,'closure_overflow',fault='closure_overflow','cycle',fault='cycle');
  END IF;
  SELECT e.committed_view INTO view FROM v24_cordis.episodes e WHERE e.id=ep AND e.fiber_id=node;
  SELECT count(*) INTO have FROM v24_cordis.pins p
   WHERE p.consumer_fiber_id=node AND p.consumer_episode_id=ep AND p.released_at IS NULL;
  SELECT count(*) INTO want FROM jsonb_object_keys(coalesce(view,'{}'::jsonb));
  IF jsonb_typeof(view)<>'object' OR want<>(SELECT jsonb_array_length(i.manifest->'requires')
    FROM v24_cordis.fibers f JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=node)
    OR have<>want OR EXISTS(
     SELECT 1 FROM v24_cordis.fibers f JOIN v24_cordis.installs i ON i.id=f.install_id
      CROSS JOIN LATERAL jsonb_array_elements(i.manifest->'requires') r(value)
      WHERE f.id=node AND (v24_cordis.require_key(r.value) IS NULL
       OR NOT (view ? v24_cordis.require_key(r.value)))) THEN
   RETURN jsonb_build_object('live',false,'reason','pin_mismatch','visited_count',n,'closure_overflow',false,'cycle',false);
  END IF;
  FOR pin IN
   SELECT p.key,p.provider_epoch,c.id AS contribution_id,c.fiber_id,c.episode_id,c.kind,
    c.withdrawn_at,c.released_at,c.descriptor,c.contract_version,e.epoch,c.key AS contribution_key,c.realm,
    (SELECT scope_id FROM v24_cordis.fibers WHERE id=node) AS consumer_scope
    FROM v24_cordis.pins p JOIN v24_cordis.contributions c ON c.id=p.contribution_id
    JOIN v24_cordis.episodes e ON e.id=c.episode_id AND e.fiber_id=c.fiber_id
    WHERE p.consumer_fiber_id=node AND p.consumer_episode_id=ep AND p.released_at IS NULL
  LOOP
   IF pin.kind<>'service' OR pin.contribution_key IS DISTINCT FROM pin.key
    OR pin.realm IS DISTINCT FROM v24_cordis.service_realm(pin.consumer_scope,pin.key)
    OR pin.withdrawn_at IS NOT NULL OR pin.released_at IS NOT NULL
    OR pin.epoch IS DISTINCT FROM pin.provider_epoch OR NOT (view ? pin.key) THEN
    RETURN jsonb_build_object('live',false,'reason',CASE WHEN pin.withdrawn_at IS NOT NULL THEN 'pin_withdrawn' ELSE 'pin_mismatch' END,
     'visited_count',n,'closure_overflow',false,'cycle',false); END IF;
   eff:=v24_cordis.descriptor_effective(pin.consumer_scope,pin.realm,pin.key,
    pin.descriptor,pin.contract_version);
   digest:=eff->>'descriptor_digest';
   IF NOT coalesce((eff->>'available')::boolean,false)
    OR pin.contribution_id::text IS DISTINCT FROM view->pin.key->>'contribution_id'
    OR pin.provider_epoch IS DISTINCT FROM (view->pin.key->>'provider_epoch')::int
    OR pin.contract_version IS DISTINCT FROM view->pin.key->>'contract_version'
    OR digest IS DISTINCT FROM view->pin.key->>'descriptor_digest'
    OR pin.fiber_id::text IS DISTINCT FROM view->pin.key->>'provider_fiber_id'
    OR pin.episode_id::text IS DISTINCT FROM view->pin.key->>'provider_episode_id' THEN
    RETURN jsonb_build_object('live',false,'reason','pin_mismatch','visited_count',n,'closure_overflow',false,'cycle',false);
   END IF;
   IF NOT v24_cordis.check_policy_ok(coalesce((SELECT i.manifest->'check'->pin.key FROM v24_cordis.fibers f
     JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=node),'null'::jsonb),
     eff->'descriptor') THEN
    RETURN jsonb_build_object('live',false,'reason','check_failed','visited_count',n,'closure_overflow',false,'cycle',false);
   END IF;
   sf:=array_append(sf,pin.fiber_id); se:=array_append(se,pin.episode_id); st:=array_append(st,0);
  END LOOP;
  -- Owned fibers depend on their frozen owner activation as well as their direct pins.
  SELECT f.owner_id,f.owner_episode_id INTO pin FROM v24_cordis.fibers f
   WHERE f.id=node AND f.owner_id IS NOT NULL;
  IF FOUND THEN sf:=array_append(sf,pin.owner_id); se:=array_append(se,pin.owner_episode_id); st:=array_append(st,0); END IF;
 END LOOP;
 RETURN jsonb_build_object('live',true,'reason','ok','visited_count',n,'closure_overflow',false,'cycle',false);
END $$;
CREATE FUNCTION v24_cordis.fiber_live_resolve_ok(p_fiber uuid,p_episode uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE state jsonb;
BEGIN
 state:=v24_cordis.fiber_live_state(p_fiber,p_episode);
 IF coalesce((state->>'closure_overflow')::boolean,false) OR coalesce((state->>'cycle')::boolean,false) THEN
  RAISE EXCEPTION 'provider closure requires retry' USING ERRCODE='P0401';
 END IF;
 RETURN coalesce((state->>'live')::boolean,false);
END $$;
CREATE FUNCTION v24_cordis.pin_readable(p_pin uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM v24_cordis.pins p
  JOIN v24_cordis.contributions c ON c.id=p.contribution_id
  JOIN v24_cordis.episodes e ON e.id=c.episode_id AND e.fiber_id=c.fiber_id
  WHERE p.id=p_pin AND p.released_at IS NULL AND c.released_at IS NULL AND e.epoch=p.provider_epoch
    AND c.id=p.contribution_id AND e.id=c.episode_id AND e.fiber_id=c.fiber_id)
$$;
CREATE FUNCTION v24_cordis.reconcile_slot_open(p_fiber uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM v24_cordis.effects WHERE fiber_id=p_fiber AND kind='command_reconcile'
  AND status IN ('ready','claimed'))
$$;
CREATE FUNCTION v24_cordis.withdraw_ids(p_fiber uuid,p_episode uuid) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_agg(id ORDER BY id::text),'[]'::jsonb) FROM v24_cordis.contributions
  WHERE fiber_id=p_fiber AND episode_id=p_episode AND kind IN ('service','cell','listener')
   AND withdrawn_at IS NULL AND released_at IS NULL
$$;
CREATE FUNCTION v24_cordis.closing_delta(p_fiber uuid,p_branch jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE domain jsonb:='[]'::jsonb; failure jsonb; ids jsonb:=coalesce(p_branch->'withdraw_ids','[]'::jsonb);
BEGIN
 IF coalesce((p_branch->>'retire')::boolean,false) THEN
  domain:=domain||jsonb_build_array(jsonb_build_object('op','fiber_retire','fiber_id',to_jsonb(p_fiber),
   'episode_id',p_branch->'episode_id'));
 END IF;
 failure:=CASE WHEN p_branch->>'outcome'='error' THEN p_branch->'failure' ELSE 'null'::jsonb END;
 domain:=domain||jsonb_build_array(jsonb_build_object('op','episode_close_start','fiber_id',to_jsonb(p_fiber),
  'episode_id',p_branch->'episode_id','outcome',p_branch->'outcome','failure',failure));
 IF jsonb_array_length(ids)>0 THEN
  domain:=domain||jsonb_build_array(jsonb_build_object('op','contributions_withdraw','fiber_id',to_jsonb(p_fiber),
   'episode_id',p_branch->'episode_id','contribution_ids',ids));
 END IF;
 RETURN jsonb_build_object('domain',domain,'receipt',jsonb_build_object('status','succeeded'),
  'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(p_fiber),
   'event_kind','episode_closing','payload',jsonb_build_object(
    'episode_id',p_branch->'episode_id','epoch',p_branch->'epoch','control_seq',p_branch->'control_seq',
    'outcome',p_branch->'outcome','reason',to_jsonb(p_branch->>'reason'),'failure',failure,'withdrawn_ids',ids))),
  'successors','[]'::jsonb);
END $$;
CREATE FUNCTION v24_cordis.p0_delta(p_fiber uuid,p_branch jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE domain jsonb:='[]'::jsonb; mode text:=p_branch->>'mode'; seq bigint;
BEGIN
 IF mode IN ('noop','schedule') OR p_branch->>'kind'='active_noop' THEN
  IF mode='schedule' THEN
   RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','succeeded'),
    'events','[]'::jsonb,'successors',v24_cordis.reconcile_successor(p_fiber,(p_branch->>'control_seq')::bigint));
  END IF;
  RETURN v24_cordis.empty_success();
 END IF;
 seq:=(p_branch->>'control_seq')::bigint;
 domain:=jsonb_build_array(jsonb_build_object('op','fiber_control','fiber_id',to_jsonb(p_fiber),
  'want_on',p_branch->'want_on','control_seq',to_jsonb(seq)));
 IF coalesce((p_branch->>'retire')::boolean,false) THEN
  domain:=domain||jsonb_build_array(jsonb_build_object('op','fiber_retire','fiber_id',to_jsonb(p_fiber),
   'episode_id',p_branch->'episode_id'));
 END IF;
 RETURN jsonb_build_object('domain',domain,'receipt',jsonb_build_object('status','succeeded'),
  'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(p_fiber),
   'event_kind','fiber_target_requested','payload',jsonb_build_object('want_on',p_branch->'want_on','control_seq',to_jsonb(seq)))),
  'successors',CASE WHEN coalesce((p_branch->>'coalesce')::boolean,false) THEN '[]'::jsonb
   ELSE v24_cordis.reconcile_successor(p_fiber,seq) END);
END $$;
CREATE FUNCTION v24_cordis.branch_error(p_code text,p_reason text,p_key text DEFAULT NULL) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('kind','error','code',p_code,'reason',p_reason,
  'detail',CASE WHEN p_key IS NULL THEN jsonb_build_object('reason',p_reason)
   ELSE jsonb_build_object('reason',p_reason,'key',p_key) END)
$$;
CREATE FUNCTION v24_cordis.branch_raise(p_ep v24_cordis.episodes,p_phase text,p_code text,p_reason text,p_key text,p_retire boolean) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('kind','raise','outcome','error','reason','failure','phase',p_phase,
  'failure_code',p_code,'failure_reason',p_reason,'key',p_key,'episode_id',to_jsonb(p_ep.id),
  'epoch',to_jsonb(p_ep.epoch),'control_seq',to_jsonb((p_ep.iterator->>'control_seq')::bigint),
  'retire',p_retire,'withdraw_ids','[]'::jsonb,
  'failure',v24_cordis.failure_v1((p_ep.iterator->>'control_seq')::bigint,p_ep.id,p_phase,p_code,p_reason,p_key))
$$;
CREATE FUNCTION v24_cordis.branch_divert(p_ep v24_cordis.episodes,p_reason text,p_retire boolean) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('kind','divert','outcome','divert','reason',p_reason,'episode_id',to_jsonb(p_ep.id),
  'epoch',to_jsonb(p_ep.epoch),'control_seq',to_jsonb((p_ep.iterator->>'control_seq')::bigint),
  'retire',p_retire,'withdraw_ids','[]'::jsonb,'failure','null'::jsonb)
$$;
CREATE FUNCTION v24_cordis.ensure_emission_missing(p_fiber uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT EXISTS (
  SELECT 1
  FROM (
   SELECT p.id FROM v24_cordis.effects p
    WHERE p.kind='command_reconcile' AND p.status='succeeded' AND p.fiber_id=p_fiber
   UNION
   SELECT p.id FROM v24_cordis.effects p
    JOIN v24_cordis.events ev ON ev.effect_id=p.id
    WHERE p.kind='command_dispose' AND p.status='succeeded'
     AND v24_cordis.json_uuid(p.input->'install_id')
     AND ev.entity_type='install' AND ev.entity_id=(p.input->>'install_id')::uuid
     AND ev.event_kind='install_dispose_progress'
     AND ev.payload->>'phase' IN ('fiber_requested','work_scheduled')
     AND ev.payload->>'fiber_id'=p_fiber::text
     AND ev.payload->'scheduled_targets' @> jsonb_build_array(p_fiber::text)
     AND v24_cordis.fiber_in_install_subtree(p_fiber,(p.input->>'install_id')::uuid)
  ) par
  LEFT JOIN v24_cordis.requests rq ON rq.effect_id=par.id
  WHERE rq.effect_id IS NULL
     OR rq.response->>'v' IS DISTINCT FROM '1'
     OR rq.response->>'disposition' IS DISTINCT FROM 'committed'
     OR rq.response->>'effect_id' IS DISTINCT FROM par.id::text
     OR jsonb_typeof(rq.response->'emitted') IS DISTINCT FROM 'array'
     OR EXISTS (
      SELECT 1 FROM jsonb_array_elements(
       CASE WHEN jsonb_typeof(rq.response->'emitted')='array'
        THEN rq.response->'emitted' ELSE '[]'::jsonb END) x(value)
      WHERE NOT v24_cordis.json_uuid(x.value)
         OR NOT EXISTS (SELECT 1 FROM v24_cordis.effects child
          WHERE child.id=CASE WHEN v24_cordis.json_uuid(x.value)
           THEN (x.value#>>'{}')::uuid END))
 )
$$;
CREATE FUNCTION v24_cordis.ensure_branch(p_fiber uuid,p_expected bigint) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 ep v24_cordis.episodes%ROWTYPE; built jsonb; slot boolean; failed boolean;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND THEN RETURN v24_cordis.branch_error('not_found_or_denied','reconcile_fiber',NULL); END IF;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','install_missing'); END IF;
 IF f.current_episode_id IS NOT NULL THEN
  SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
  IF NOT FOUND OR ep.closed_at IS NOT NULL THEN
   RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
 ELSIF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift');
 ELSIF f.retire_started_at IS NOT NULL THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
 IF v24_cordis.ensure_emission_missing(f.id) THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','missing_reconcile_successor'); END IF;
 slot:=v24_cordis.reconcile_slot_open(f.id);
 IF inst.state='disposed' AND f.disposed_at IS NULL THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
 IF (f.disposed_at IS NOT NULL OR inst.state='disposed')
  AND (f.current_episode_id IS NOT NULL OR slot) THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
 IF f.current_episode_id IS NOT NULL AND ep.state='reloading' AND NOT slot THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','missing_reconcile_successor'); END IF;
 IF f.current_episode_id IS NOT NULL AND ep.state='closing' AND NOT slot
  AND EXISTS(SELECT 1 FROM v24_cordis.events ev WHERE ev.entity_type='fiber' AND ev.entity_id=f.id
   AND ev.event_kind IN ('contributions_released','pins_released')
   AND ev.payload->>'episode_id'=ep.id::text) THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','missing_reconcile_successor'); END IF;
 IF p_expected IS DISTINCT FROM f.control_seq THEN
  RETURN v24_cordis.branch_error('stale_generation','reconcile_generation',NULL); END IF;
 IF slot THEN RETURN v24_cordis.branch_error('stale_generation','ensure_slot_present',NULL); END IF;
 IF f.disposed_at IS NOT NULL OR inst.state='disposed' THEN
  RETURN v24_cordis.branch_error('stale_generation','ensure_no_work',NULL); END IF;
 built:=v24_cordis.reconcile_branch(f.id,'advance',p_expected);
 IF built->>'kind'='error' THEN
  IF built->>'sqlstate'='0A000' THEN RETURN built; END IF;
  IF built->>'code' IN ('already_terminal','owner_closing') THEN
   RETURN v24_cordis.branch_error('stale_generation','ensure_no_work',NULL); END IF;
  RETURN built;
 END IF;
 IF built->>'kind' IN ('active_noop','idle_noop') THEN
  RETURN v24_cordis.branch_error('stale_generation','ensure_no_work',NULL); END IF;
 IF built->>'kind'='p1' THEN
  failed:=jsonb_typeof(f.failure)='object'
   AND v24_cordis.json_int(f.failure->'control_seq',0,9223372036854775807)
   AND (f.failure->>'control_seq')::bigint=f.control_seq;
  IF failed THEN RETURN v24_cordis.branch_error('stale_generation','ensure_failure_suppressed',NULL); END IF;
 ELSIF built->>'kind' NOT IN ('leave','p6') THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','ensure_branch'); END IF;
 RETURN jsonb_build_object('kind','p0','mode','schedule','control_seq',to_jsonb(f.control_seq));
END $$;
CREATE FUNCTION v24_cordis.reconcile_branch(p_fiber uuid,p_action text,p_expected bigint) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 err jsonb; item jsonb; bind jsonb; row record; live jsonb; ids jsonb; k text; v_realm text; plan jsonb; v_kind text;
 v_i int; v_next int; v_len int; seen text[]:=ARRAY[]::text[]; retire boolean; slot boolean;
BEGIN
 IF p_action NOT IN ('on','off','retry','advance','ensure') THEN
  RETURN v24_cordis.branch_error('invalid_args','reconcile_action',NULL); END IF;
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND THEN RETURN v24_cordis.branch_error('not_found_or_denied','reconcile_fiber',NULL); END IF;
 IF p_action='ensure' THEN RETURN v24_cordis.ensure_branch(f.id,p_expected); END IF;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF p_action IN ('on','off','retry') AND p_expected IS DISTINCT FROM f.control_seq THEN
  RETURN v24_cordis.branch_error('stale_generation','reconcile_generation',NULL); END IF;
 IF p_action IN ('on','off','retry') AND (f.disposed_at IS NOT NULL OR inst.state='disposed') THEN
  RETURN v24_cordis.branch_error('already_terminal','reconcile_terminal',NULL); END IF;
 IF p_action IN ('on','off','retry') AND (f.dispose_requested_at IS NOT NULL OR inst.state='dispose_pending') THEN
  RETURN v24_cordis.branch_error('owner_closing','reconcile_dispose',NULL); END IF;
 slot:=v24_cordis.reconcile_slot_open(f.id);
 IF f.current_episode_id IS NOT NULL THEN
  SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 END IF;
 retire:=f.current_episode_id IS NOT NULL AND f.retire_started_at IS NULL;
 IF p_action='on' THEN
  IF f.want_on THEN RETURN jsonb_build_object('kind','p0','mode','noop'); END IF;
  err:=v24_cordis.activation_admission(f.id,true);
  IF err IS NOT NULL THEN
   IF err->>'code'='0A000' THEN RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason',err->>'reason'); END IF;
   RETURN v24_cordis.branch_error(err->>'code',err->>'reason',NULL); END IF;
  IF f.control_seq=9223372036854775807 THEN RETURN v24_cordis.branch_error('budget_exceeded','control_seq',NULL); END IF;
  RETURN jsonb_build_object('kind','p0','mode','on','want_on',true,'control_seq',to_jsonb(f.control_seq+1),
   'coalesce',slot,'retire',false);
 END IF;
 IF p_action='off' THEN
  IF f.want_on THEN
   IF f.control_seq=9223372036854775807 THEN RETURN v24_cordis.branch_error('budget_exceeded','control_seq',NULL); END IF;
   RETURN jsonb_build_object('kind','p0','mode','off','want_on',false,'control_seq',to_jsonb(f.control_seq+1),
    'coalesce',slot,'retire',retire,'episode_id',to_jsonb(f.current_episode_id));
  END IF;
  IF NOT slot AND f.current_episode_id IS NOT NULL AND ep.closed_at IS NULL THEN
   RETURN jsonb_build_object('kind','p0','mode','schedule','control_seq',to_jsonb(f.control_seq));
  END IF;
  RETURN jsonb_build_object('kind','p0','mode','noop');
 END IF;
 IF p_action='retry' THEN
  err:=v24_cordis.activation_admission(f.id,true);
  IF err IS NOT NULL THEN
   IF err->>'code'='0A000' THEN RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason',err->>'reason'); END IF;
   RETURN v24_cordis.branch_error(err->>'code',err->>'reason',NULL); END IF;
  IF NOT f.want_on OR NOT (
    (jsonb_typeof(f.failure)='object' AND v24_cordis.json_int(f.failure->'control_seq',0,9223372036854775807)
     AND (f.failure->>'control_seq')::bigint=f.control_seq)
    OR (f.current_episode_id IS NOT NULL AND ep.state='closing')) THEN
   RETURN v24_cordis.branch_error('stale_generation','retry_generation',NULL); END IF;
  IF f.control_seq=9223372036854775807 THEN RETURN v24_cordis.branch_error('budget_exceeded','control_seq',NULL); END IF;
  RETURN jsonb_build_object('kind','p0','mode','retry','want_on',true,'control_seq',to_jsonb(f.control_seq+1),
   'coalesce',slot,'retire',retire AND ep.state IS DISTINCT FROM 'closing','episode_id',to_jsonb(f.current_episode_id));
 END IF;
 IF f.current_episode_id IS NOT NULL AND (NOT FOUND OR ep.closed_at IS NOT NULL) THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
 IF f.current_episode_id IS NOT NULL AND ep.state='closing' THEN
  RETURN jsonb_build_object('kind','p6'); END IF;
 IF f.current_episode_id IS NULL THEN
  IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
   RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
  IF f.disposed_at IS NOT NULL OR inst.state='disposed' THEN
   RETURN v24_cordis.branch_error('already_terminal','reconcile_terminal',NULL); END IF;
  -- Settle an obsolete NULL-fence slot without letting its frozen input begin a new generation.
  IF p_expected IS DISTINCT FROM f.control_seq OR NOT f.want_on THEN
   RETURN jsonb_build_object('kind','idle_noop'); END IF;
  err:=v24_cordis.activation_admission(f.id);
  IF err IS NOT NULL THEN
   IF err->>'code'='0A000' THEN RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason',err->>'reason'); END IF;
   RETURN v24_cordis.branch_error(err->>'code',err->>'reason',NULL); END IF;
  IF NOT v24_cordis.manifest_shape_valid(inst.manifest,inst.contracts) THEN
   RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','manifest_drift'); END IF;
  IF jsonb_typeof(inst.manifest->'requires')<>'array' THEN
   RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','requires_shape'); END IF;
  FOR v_i IN 0..jsonb_array_length(inst.manifest->'requires')-1 LOOP
   k:=v24_cordis.require_key(inst.manifest->'requires'->v_i);
   IF k IS NULL OR length(k) NOT BETWEEN 1 AND 128 THEN
    RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','require_key'); END IF;
   BEGIN
    SELECT * INTO row FROM v24_cordis.resolve(f.scope_id,ARRAY[k]);
   EXCEPTION WHEN SQLSTATE 'P0401' THEN
    RETURN v24_cordis.branch_error('retry_with_closure','provider_closure',NULL);
   END;
   IF NOT FOUND OR NOT row.available THEN
    RETURN v24_cordis.branch_error('dependency_unresolved','dependency_missing',k); END IF;
   IF NOT v24_cordis.check_policy_ok(coalesce(inst.manifest->'check'->k,'null'::jsonb),row.descriptor) THEN
    RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','check_failed'); END IF;
  END LOOP;
  RETURN jsonb_build_object('kind','p1');
 END IF;
 IF ep.state='active' THEN
  live:=v24_cordis.fiber_live_state(f.id,ep.id);
  IF coalesce((live->>'closure_overflow')::boolean,false) OR coalesce((live->>'cycle')::boolean,false) THEN
   RETURN v24_cordis.branch_error('retry_with_closure','provider_closure',NULL); END IF;
  IF coalesce((live->>'live')::boolean,false) THEN RETURN jsonb_build_object('kind','active_noop'); END IF;
  ids:=v24_cordis.withdraw_ids(f.id,ep.id);
  IF jsonb_array_length(ids)>256 THEN RETURN v24_cordis.branch_error('retry_with_closure','withdraw_budget',NULL); END IF;
  RETURN jsonb_build_object('kind','leave','outcome','retire','reason',CASE
    WHEN NOT f.want_on THEN 'target_drift'
    WHEN f.retire_started_at IS NOT NULL THEN 'control_drift'
    WHEN f.dispose_requested_at IS NOT NULL OR f.disposed_at IS NOT NULL THEN 'dispose'
    WHEN live->>'reason'='failure' THEN 'failure' ELSE 'dependency_lost' END,
   'episode_id',to_jsonb(ep.id),'epoch',to_jsonb(ep.epoch),
   'control_seq',to_jsonb((ep.iterator->>'control_seq')::bigint),'retire',f.retire_started_at IS NULL,
   'withdraw_ids',ids,'failure','null'::jsonb);
 END IF;
 IF ep.state<>'reloading' THEN RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','phase_drift'); END IF;
 IF jsonb_typeof(ep.iterator)<>'object' OR NOT v24_cordis.json_int(ep.iterator->'control_seq',0,9223372036854775807) THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','iterator_drift'); END IF;
 IF NOT f.want_on THEN RETURN v24_cordis.branch_divert(ep,'target_drift',retire); END IF;
 IF p_expected IS DISTINCT FROM f.control_seq
  OR (ep.iterator->>'control_seq')::bigint IS DISTINCT FROM f.control_seq THEN
  RETURN v24_cordis.branch_divert(ep,'control_drift',retire); END IF;
 err:=v24_cordis.activation_admission(f.id);
 IF err IS NOT NULL THEN
  IF err->>'code'='retry_with_closure' THEN RETURN v24_cordis.branch_error('retry_with_closure','provider_closure'); END IF;
  RETURN v24_cordis.branch_divert(ep,CASE WHEN err->>'reason' LIKE '%dispose%' OR f.dispose_requested_at IS NOT NULL
   THEN 'dispose' ELSE 'control_drift' END,retire); END IF;
 IF jsonb_typeof(ep.committed_view)<>'object' OR jsonb_typeof(inst.manifest->'requires')<>'array'
  OR (SELECT count(*) FROM jsonb_object_keys(ep.committed_view))<>jsonb_array_length(inst.manifest->'requires')
  OR (SELECT count(*) FROM v24_cordis.pins WHERE consumer_fiber_id=f.id AND consumer_episode_id=ep.id
    AND released_at IS NULL)<>jsonb_array_length(inst.manifest->'requires') THEN
  RETURN v24_cordis.branch_divert(ep,'target_drift',retire); END IF;
 IF jsonb_typeof(inst.manifest->'requires')='array' AND jsonb_typeof(ep.committed_view)='object' THEN
  FOR v_i IN 0..jsonb_array_length(inst.manifest->'requires')-1 LOOP
   k:=v24_cordis.require_key(inst.manifest->'requires'->v_i);
   bind:=ep.committed_view->k;
   IF k IS NULL OR bind IS NULL THEN RETURN v24_cordis.branch_divert(ep,'target_drift',retire); END IF;
   BEGIN
    SELECT * INTO row FROM v24_cordis.resolve(f.scope_id,ARRAY[k]);
   EXCEPTION WHEN SQLSTATE 'P0401' THEN
    RETURN v24_cordis.branch_error('retry_with_closure','provider_closure',NULL);
   END;
   IF NOT FOUND OR NOT row.available
    OR row.contribution_id IS DISTINCT FROM (bind->>'contribution_id')::uuid
    OR row.provider_fiber_id IS DISTINCT FROM (bind->>'provider_fiber_id')::uuid
    OR row.provider_episode_id IS DISTINCT FROM (bind->>'provider_episode_id')::uuid
    OR row.provider_epoch IS DISTINCT FROM (bind->>'provider_epoch')::int
    OR row.descriptor_digest IS DISTINCT FROM bind->>'descriptor_digest'
    OR row.contract_version IS DISTINCT FROM bind->>'contract_version' THEN
    RETURN v24_cordis.branch_divert(ep,'target_drift',retire); END IF;
   IF NOT EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.consumer_fiber_id=f.id
     AND p.consumer_episode_id=ep.id AND p.key=k AND p.released_at IS NULL
     AND p.contribution_id=row.contribution_id AND p.provider_epoch=row.provider_epoch) THEN
    RETURN v24_cordis.branch_divert(ep,'target_drift',retire); END IF;
   IF NOT v24_cordis.check_policy_ok(coalesce(inst.manifest->'check'->k,'null'::jsonb),row.descriptor) THEN
    RETURN v24_cordis.branch_raise(ep,'p3','provider_unavailable','check_failed',k,retire); END IF;
   IF jsonb_typeof(inst.manifest->'requires'->v_i)='object'
    AND inst.manifest->'requires'->v_i->>'contract_version' IS NOT NULL
    AND inst.manifest->'requires'->v_i->>'contract_version' IS DISTINCT FROM row.contract_version THEN
    RETURN v24_cordis.branch_raise(ep,'p3','registration_stale','contract_drift',k,retire); END IF;
  END LOOP;
 END IF;
 plan:=v24_cordis.registration_plan(inst);
 IF plan IS NULL THEN
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','manifest_drift'); END IF;
 v_next:=(ep.iterator->>'next_index')::int; v_len:=jsonb_array_length(plan);
 IF v_next<v_len THEN
  FOR v_i IN 0..least(32,v_len-v_next)-1 LOOP
   item:=plan->(v_next+v_i); k:=item->>'key'; v_kind:=item->>'kind';
   IF v_kind='service' THEN
    v_realm:=v24_cordis.service_realm(f.scope_id,k);
    IF k IS NULL OR length(k) NOT BETWEEN 1 AND 128 OR v_realm IS NULL THEN
     RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','realm_unavailable'); END IF;
    IF (v_realm||'/'||k)=ANY(seen) OR EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.kind='service'
     AND c.realm=v_realm AND c.key=k AND c.released_at IS NULL) THEN
     RETURN v24_cordis.branch_raise(ep,'p2','provide_conflict','address_conflict',k,retire); END IF;
    seen:=array_append(seen,v_realm||'/'||k);
    IF NOT coalesce(v24_cordis.contracts_valid(inst.contracts),false)
     OR item->'descriptor' IS NULL OR inst.contracts->(item->'descriptor'->>'capability')->>'contract_version'
     IS DISTINCT FROM item->>'contract_version' THEN
     RETURN v24_cordis.branch_raise(ep,'p2','registration_stale','contract_drift',k,retire); END IF;
   ELSIF NOT v24_cordis.contracts_valid(inst.contracts)
    OR NOT v24_cordis.listener_desc_valid(item->'descriptor',inst.contracts,item->>'contract_version') THEN
    RETURN v24_cordis.branch_raise(ep,'p2','registration_stale','contract_drift',k,retire); END IF;
  END LOOP;
  RETURN jsonb_build_object('kind','p2');
 END IF;
 IF v24_cordis.activation_total(f.id) IS NOT NULL THEN
  FOR v_i IN 0..v_len-1 LOOP
   item:=plan->v_i; k:=item->>'key'; v_kind:=item->>'kind';
   IF NOT EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.fiber_id=f.id AND c.episode_id=ep.id
    AND c.seq=v_i AND c.kind=v_kind AND c.withdrawn_at IS NULL AND c.released_at IS NULL
    AND c.key IS NOT DISTINCT FROM CASE WHEN v_kind='service' THEN k END
    AND c.realm IS NOT DISTINCT FROM CASE WHEN v_kind='service'
     THEN v24_cordis.service_realm(f.scope_id,k) END
    AND c.descriptor IS NOT DISTINCT FROM item->'descriptor'
    AND c.contract_version IS NOT DISTINCT FROM item->>'contract_version'
    AND c.prev_contribution_id IS NULL AND c.inverse='{"op":"delete_row"}'::jsonb) THEN
    IF k IS NULL OR length(k) NOT BETWEEN 1 AND 128 THEN
     RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','totality'); END IF;
    RETURN v24_cordis.branch_raise(ep,'p4','registration_stale','totality_failed',k,retire); END IF;
  END LOOP;
  RETURN jsonb_build_object('kind','error','sqlstate','0A000','reason','totality'); END IF;
 RETURN jsonb_build_object('kind','p4');
END $$;
CREATE FUNCTION v24_cordis.run_pin_release_delta(p_run uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE r v24_cordis.runs%ROWTYPE; pins jsonb;
BEGIN
 -- Trusted terminal run facts only: caller proves owner/episode alignment.
 SELECT * INTO r FROM v24_cordis.runs WHERE id=p_run;
 IF NOT FOUND OR r.ended_at IS NULL THEN RETURN '[]'::jsonb; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.run_id=p_run
  AND (x.kind='host_io' OR x.status IN ('ready','claimed','unknown'))) THEN
  RETURN '[]'::jsonb; END IF;
 SELECT coalesce(jsonb_agg(id ORDER BY key,id),'[]'::jsonb) INTO pins FROM (
  SELECT id,key FROM v24_cordis.pins WHERE consumer_run_id=p_run AND released_at IS NULL
  ORDER BY key,id LIMIT 32) q;
 RETURN pins;
END $$;
CREATE FUNCTION v24_cordis.p6_plan(p_effect_id uuid,p_fiber uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE;
 batch jsonb:='[]'::jsonb; batch_ids uuid[]; n_contrib int; run_pins jsonb:='[]'::jsonb;
 act_pins jsonb:='[]'::jsonb; item jsonb; rv record; remaining int;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND OR f.current_episode_id IS NULL THEN RETURN jsonb_build_object('kind','none'); END IF;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'closing' THEN
  RETURN jsonb_build_object('kind','none'); END IF;
 IF ep.outcome IS NULL THEN RETURN jsonb_build_object('kind','unsupported','reason','closing_outcome'); END IF;
 SELECT coalesce(jsonb_agg(id ORDER BY seq DESC),'[]'::jsonb) INTO batch FROM (
  SELECT id,seq FROM v24_cordis.contributions WHERE fiber_id=f.id AND episode_id=ep.id
   AND released_at IS NULL ORDER BY seq DESC LIMIT 32) q;
 batch_ids:=ARRAY(SELECT jsonb_array_elements_text(batch)::uuid);
 SELECT count(*) INTO n_contrib FROM v24_cordis.contributions
  WHERE fiber_id=f.id AND episode_id=ep.id AND released_at IS NULL;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.kind='host_io' AND (x.fiber_id=f.id
   OR x.run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=f.id))) THEN
  RETURN jsonb_build_object('kind','unsupported','reason','host_io'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.id IS DISTINCT FROM p_effect_id
   AND x.status='unknown' AND (x.fiber_id=f.id
   OR x.run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=f.id)))
  OR EXISTS(SELECT 1 FROM v24_cordis.effects x JOIN v24_cordis.effects p ON p.id=x.parent_id
   WHERE x.kind='listener_call' AND x.status='unknown' AND p.kind='dispatch'
    AND p.fiber_id=f.id AND p.episode_id=ep.id AND p.input->>'mode'<>'emit') THEN
  RETURN jsonb_build_object('kind','blocked_unknown','reason','effect'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.id=ANY(batch_ids)
   AND NOT ((c.inverse->>'op'='delete_row' AND c.kind IN ('service','listener'))
    OR (c.inverse->>'op'='dispose_child' AND c.kind='child')
    OR c.inverse->>'op'='unknown')) THEN
  RETURN jsonb_build_object('kind','unsupported','reason','inverse'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions c
   WHERE c.id=ANY(batch_ids) AND c.inverse->>'op'='unknown') THEN
  RETURN jsonb_build_object('kind','blocked_unknown','reason','inverse'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.id IS DISTINCT FROM p_effect_id
   AND x.status IN ('ready','claimed') AND (x.fiber_id=f.id
   OR x.run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=f.id))) THEN
  RETURN jsonb_build_object('kind','deferred','reason','effect'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.runs r WHERE r.owner_fiber_id=f.id AND r.ended_at IS NULL) THEN
  RETURN jsonb_build_object('kind','deferred','reason','run'); END IF;
 FOR rv IN SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=f.id
  AND owner_episode_id=ep.id AND ended_at IS NOT NULL ORDER BY id LOOP
  FOR item IN SELECT value FROM jsonb_array_elements(v24_cordis.run_pin_release_delta(rv.id)) LOOP
   run_pins:=run_pins||jsonb_build_array(item);
   EXIT WHEN jsonb_array_length(run_pins)>=32;
  END LOOP;
  EXIT WHEN jsonb_array_length(run_pins)>=32;
 END LOOP;
 IF n_contrib>0 THEN
  IF jsonb_array_length(run_pins)>0 THEN
   RETURN jsonb_build_object('kind','pins_release','run_pin_ids',run_pins,
    'activation_pin_ids','[]'::jsonb); END IF;
  IF EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.fiber_id=f.id
    AND c.episode_id=ep.id AND c.kind='child'
    AND NOT (v24_cordis.json_uuid(c.descriptor->'child_fiber_id') AND EXISTS(
     SELECT 1 FROM v24_cordis.fibers cf WHERE cf.id=(c.descriptor->>'child_fiber_id')::uuid
      AND cf.disposed_at IS NOT NULL))) THEN
   RETURN jsonb_build_object('kind','deferred','reason','child'); END IF;
  IF EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL
    AND p.contribution_id=ANY(batch_ids)) THEN
   RETURN jsonb_build_object('kind','deferred','reason','pin'); END IF;
  RETURN jsonb_build_object('kind','inverse','contribution_ids',batch);
 END IF;
 SELECT coalesce(jsonb_agg(id ORDER BY key,id),'[]'::jsonb) INTO act_pins FROM (
  SELECT id,key FROM v24_cordis.pins WHERE consumer_fiber_id=f.id
   AND consumer_episode_id=ep.id AND released_at IS NULL ORDER BY key,id LIMIT 32) q;
 remaining:=32-jsonb_array_length(run_pins);
 IF jsonb_array_length(act_pins)>0 AND remaining<jsonb_array_length(act_pins) THEN
  SELECT coalesce(jsonb_agg(value ORDER BY ord),'[]'::jsonb) INTO act_pins
   FROM (SELECT value,ord FROM jsonb_array_elements(act_pins) WITH ORDINALITY x(value,ord)
    WHERE ord<=remaining ORDER BY ord) q;
 END IF;
 IF jsonb_array_length(run_pins)>0 OR jsonb_array_length(act_pins)>0 THEN
  RETURN jsonb_build_object('kind','pins_release','run_pin_ids',run_pins,
   'activation_pin_ids',act_pins); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL
  AND p.contribution_id IN (SELECT id FROM v24_cordis.contributions
   WHERE fiber_id=f.id AND episode_id=ep.id)) THEN
  RETURN jsonb_build_object('kind','deferred','reason','pin'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.fiber_id=f.id AND c.episode_id=ep.id
  AND c.kind='child' AND NOT (v24_cordis.json_uuid(c.descriptor->'child_fiber_id') AND EXISTS(
   SELECT 1 FROM v24_cordis.fibers cf WHERE cf.id=(c.descriptor->>'child_fiber_id')::uuid
    AND cf.disposed_at IS NOT NULL))) THEN
  RETURN jsonb_build_object('kind','deferred','reason','child'); END IF;
 RETURN jsonb_build_object('kind','close');
END $$;
CREATE FUNCTION v24_cordis.p6_delta(p_effect_id uuid,p_fiber uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE plan jsonb; f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE;
 ids jsonb; run_ids jsonb; act_ids jsonb; seq_from bigint; seq_through bigint;
BEGIN
 plan:=v24_cordis.p6_plan(p_effect_id,p_fiber);
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 IF plan->>'kind'='inverse' THEN
  ids:=plan->'contribution_ids';
  SELECT max(seq),min(seq) INTO seq_from,seq_through FROM v24_cordis.contributions
   WHERE id IN (SELECT jsonb_array_elements_text(ids)::uuid);
  IF seq_from IS NULL THEN RETURN NULL; END IF;
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','contribution_inverse',
    'fiber_id',to_jsonb(f.id),'episode_id',to_jsonb(ep.id),'contribution_ids',ids)),
   'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),
    'event_kind','contributions_released','payload',jsonb_build_object('episode_id',to_jsonb(ep.id),
     'contribution_ids',ids,'seq_from',to_jsonb(seq_from),'seq_through',to_jsonb(seq_through)))),
   'successors',v24_cordis.reconcile_successor(f.id,f.control_seq));
 ELSIF plan->>'kind'='pins_release' THEN
  run_ids:=plan->'run_pin_ids'; act_ids:=plan->'activation_pin_ids';
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','pins_release',
    'fiber_id',to_jsonb(f.id),'episode_id',to_jsonb(ep.id),'pin_ids',run_ids||act_ids)),
   'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),
    'event_kind','pins_released','payload',jsonb_build_object('episode_id',to_jsonb(ep.id),
     'activation_pin_ids',act_ids,'run_pin_ids',run_ids))),
   'successors',v24_cordis.reconcile_successor(f.id,f.control_seq));
 ELSIF plan->>'kind'='close' THEN
  IF ep.id IS NULL OR ep.outcome IS NULL
   OR NOT v24_cordis.json_int(ep.iterator->'control_seq',0,9223372036854775807) THEN
   RETURN NULL; END IF;
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','episode_close',
    'fiber_id',to_jsonb(f.id),'episode_id',to_jsonb(ep.id))),
   'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),
    'event_kind','episode_closed','payload',jsonb_build_object('episode_id',to_jsonb(ep.id),
     'epoch',to_jsonb(ep.epoch),'outcome',to_jsonb(ep.outcome),
     'control_seq',to_jsonb((ep.iterator->>'control_seq')::bigint)))),
   'successors','[]'::jsonb);
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.dispose_subtree(p_install uuid)
RETURNS TABLE(id uuid,install_id uuid,depth int)
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH RECURSIVE t(id,install_id,depth) AS (
  SELECT f.id,f.install_id,0 FROM v24_cordis.fibers f WHERE f.install_id=p_install
  UNION ALL
  SELECT c.id,c.install_id,t.depth+1 FROM v24_cordis.fibers c JOIN t ON c.owner_id=t.id
 ) SELECT * FROM t
$$;
CREATE FUNCTION v24_cordis.dispose_block_kind(p_reason text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT CASE
  WHEN p_reason='host_io' THEN jsonb_build_object('kind','unsupported','reason','host_io')
  WHEN p_reason='unknown' THEN jsonb_build_object('kind','blocked_unknown','reason','effect')
  WHEN p_reason IN ('run','pin','live_effect','child_install','child_fiber')
   THEN jsonb_build_object('kind','deferred','reason',p_reason)
  ELSE jsonb_build_object('kind','deferred','reason',p_reason) END
$$;
CREATE FUNCTION v24_cordis.dispose_fiber_next(p_install uuid,p_fiber uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; child uuid;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND OR f.disposed_at IS NOT NULL THEN RETURN jsonb_build_object('kind','none'); END IF;
 child:=CASE WHEN f.install_id<>p_install THEN f.install_id ELSE NULL END;
 IF v24_cordis.reconcile_slot_open(f.id) THEN
  RETURN jsonb_build_object('kind','wait_slot','fiber_id',f.id,'child_install_id',child); END IF;
 IF f.current_episode_id IS NOT NULL THEN
  SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
  IF NOT FOUND OR ep.closed_at IS NOT NULL THEN
   RETURN jsonb_build_object('kind','unsupported','reason','episode'); END IF;
  IF f.want_on THEN
   IF f.control_seq=9223372036854775807 THEN
    RETURN jsonb_build_object('kind','budget','reason','control_seq'); END IF;
   RETURN jsonb_build_object('kind','fiber_request','fiber_id',f.id,'child_install_id',child,
    'control_seq',f.control_seq+1);
  END IF;
  RETURN jsonb_build_object('kind','schedule','fiber_id',f.id,'child_install_id',child,
   'control_seq',f.control_seq);
 END IF;
 IF f.want_on THEN
  IF f.control_seq=9223372036854775807 THEN
   RETURN jsonb_build_object('kind','budget','reason','control_seq'); END IF;
  RETURN jsonb_build_object('kind','fiber_control','fiber_id',f.id,'child_install_id',child,
   'control_seq',f.control_seq+1);
 END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
  RETURN jsonb_build_object('kind','unsupported','reason','episode'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions WHERE fiber_id=f.id AND released_at IS NULL) THEN
  RETURN jsonb_build_object('kind','unsupported','reason','contribution'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL AND (p.consumer_fiber_id=f.id
  OR p.contribution_id IN (SELECT id FROM v24_cordis.contributions WHERE fiber_id=f.id))) THEN
  RETURN jsonb_build_object('kind','deferred','reason','pin'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.runs WHERE owner_fiber_id=f.id AND ended_at IS NULL) THEN
  RETURN jsonb_build_object('kind','deferred','reason','run'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects WHERE fiber_id=f.id AND status IN ('ready','claimed')) THEN
  RETURN jsonb_build_object('kind','deferred','reason','effect'); END IF;
 RETURN jsonb_build_object('kind','fiber_finish','fiber_id',f.id,'child_install_id',child);
END $$;
CREATE FUNCTION v24_cordis.dispose_plan(p_install uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE inst v24_cordis.installs%ROWTYPE; rec record; reason text; first_block jsonb;
BEGIN
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=p_install;
 IF NOT FOUND THEN RETURN jsonb_build_object('kind','missing'); END IF;
 IF inst.state='disposed' THEN RETURN jsonb_build_object('kind','terminal'); END IF;
 IF inst.state='installed' THEN RETURN jsonb_build_object('kind','request'); END IF;
 IF inst.state<>'dispose_pending' THEN
  RETURN jsonb_build_object('kind','unsupported','reason','state'); END IF;
 -- Conservatively block the whole sealed subtree on non-disposable external IO or unknown runs.
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.kind='host_io' AND (
  x.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))
  OR x.episode_id IN (SELECT e.id FROM v24_cordis.episodes e
   WHERE e.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install)))
  OR x.run_id IN (SELECT r.id FROM v24_cordis.runs r
   WHERE r.owner_fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))))) THEN
  RETURN jsonb_build_object('kind','unsupported','reason','host_io'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.kind<>'host_io' AND x.status='unknown' AND (
  x.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))
  OR x.episode_id IN (SELECT e.id FROM v24_cordis.episodes e
   WHERE e.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install)))
  OR x.run_id IN (SELECT r.id FROM v24_cordis.runs r
   WHERE r.owner_fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))))) THEN
  RETURN jsonb_build_object('kind','blocked_unknown','reason','effect'); END IF;
 -- An unverifiable external inverse is the same terminal debt for the sealed subtree:
 -- no tombstone can be honest while it is unreleased, so block before any progress
 -- write instead of re-scheduling a successor that P6 must reject forever.
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.released_at IS NULL
  AND c.inverse->>'op'='unknown'
  AND c.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))) THEN
  RETURN jsonb_build_object('kind','blocked_unknown','reason','inverse'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.status IN ('ready','claimed')
  AND x.kind<>'command_reconcile' AND (
  x.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))
  OR x.episode_id IN (SELECT e.id FROM v24_cordis.episodes e
   WHERE e.fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install)))
  OR x.run_id IN (SELECT r.id FROM v24_cordis.runs r
   WHERE r.owner_fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))))) THEN
  RETURN jsonb_build_object('kind','deferred','reason','effect'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.runs r WHERE r.ended_at IS NULL
  AND r.owner_fiber_id IN (SELECT id FROM v24_cordis.dispose_subtree(p_install))) THEN
  RETURN jsonb_build_object('kind','deferred','reason','run'); END IF;
 FOR rec IN
  SELECT t.id FROM v24_cordis.dispose_subtree(p_install) t
  JOIN v24_cordis.fibers f ON f.id=t.id
  WHERE f.disposed_at IS NULL AND t.depth>0 ORDER BY t.depth DESC,t.id LOOP
  RETURN v24_cordis.dispose_fiber_next(p_install,rec.id);
 END LOOP;
 FOR rec IN
  SELECT i.id FROM (SELECT install_id,max(depth) AS depth
   FROM v24_cordis.dispose_subtree(p_install)
   WHERE install_id<>p_install GROUP BY install_id) t
  JOIN v24_cordis.installs i ON i.id=t.install_id
  WHERE i.state<>'disposed'
   AND NOT EXISTS(SELECT 1 FROM v24_cordis.fibers f WHERE f.install_id=i.id AND f.disposed_at IS NULL)
  ORDER BY t.depth DESC,i.id LOOP
  reason:=v24_cordis.dispose_block_reason(rec.id);
  IF reason IS NULL THEN
   RETURN jsonb_build_object('kind','child_install_finish','install_id',rec.id);
  ELSIF first_block IS NULL THEN
   first_block:=v24_cordis.dispose_block_kind(reason);
  END IF;
 END LOOP;
 IF first_block IS NOT NULL THEN RETURN first_block; END IF;
 FOR rec IN
  SELECT t.id FROM v24_cordis.dispose_subtree(p_install) t
  JOIN v24_cordis.fibers f ON f.id=t.id
  WHERE f.disposed_at IS NULL AND t.depth=0 ORDER BY t.id LOOP
  RETURN v24_cordis.dispose_fiber_next(p_install,rec.id);
 END LOOP;
 reason:=v24_cordis.dispose_block_reason(p_install);
 IF reason IS NULL THEN RETURN jsonb_build_object('kind','install_finish'); END IF;
 RETURN v24_cordis.dispose_block_kind(reason);
END $$;
CREATE FUNCTION v24_cordis.dispose_delta(p_install uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE plan jsonb; fid uuid; child uuid; seq bigint;
BEGIN
 plan:=v24_cordis.dispose_plan(p_install);
 IF plan->>'kind'='request' THEN
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','install_dispose_request',
    'install_id',to_jsonb(p_install))),'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',to_jsonb(p_install),
    'event_kind','install_dispose_progress','payload',jsonb_build_object('phase','requested',
     'fiber_id','null'::jsonb,'child_install_id','null'::jsonb,'scheduled_targets','null'::jsonb))),
   'successors','[]'::jsonb);
 ELSIF plan->>'kind' IN ('fiber_request','fiber_control','schedule','fiber_finish') THEN
  fid:=(plan->>'fiber_id')::uuid;
  child:=CASE WHEN plan->'child_install_id'='null'::jsonb THEN NULL
   ELSE (plan->>'child_install_id')::uuid END;
  IF plan->>'kind' IN ('fiber_request','fiber_control') THEN
   seq:=(plan->>'control_seq')::bigint;
   RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','fiber_dispose_request',
     'install_id',to_jsonb(p_install),'fiber_id',to_jsonb(fid),'want_on',false,'control_seq',to_jsonb(seq))),
    'receipt',jsonb_build_object('status','succeeded'),
    'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',to_jsonb(p_install),
     'event_kind','install_dispose_progress','payload',jsonb_build_object('phase','fiber_requested',
      'fiber_id',to_jsonb(fid),'child_install_id',to_jsonb(child),'scheduled_targets',
      CASE WHEN plan->>'kind'='fiber_control' THEN 'null'::jsonb
       ELSE jsonb_build_array(fid) END))),
    'successors',CASE WHEN plan->>'kind'='fiber_control' THEN '[]'::jsonb
     ELSE v24_cordis.reconcile_successor(fid,seq) END);
  ELSIF plan->>'kind'='schedule' THEN
   seq:=(plan->>'control_seq')::bigint;
   RETURN jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','succeeded'),
    'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',to_jsonb(p_install),
     'event_kind','install_dispose_progress','payload',jsonb_build_object('phase','work_scheduled',
      'fiber_id',to_jsonb(fid),'child_install_id',to_jsonb(child),'scheduled_targets',jsonb_build_array(fid)))),
    'successors',v24_cordis.reconcile_successor(fid,seq));
  END IF;
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','fiber_dispose_finish',
    'install_id',to_jsonb(p_install),'fiber_id',to_jsonb(fid))),
   'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',to_jsonb(p_install),
    'event_kind','install_dispose_progress','payload',jsonb_build_object('phase','fiber_disposed',
     'fiber_id',to_jsonb(fid),'child_install_id',to_jsonb(child),'scheduled_targets','null'::jsonb))),
   'successors','[]'::jsonb);
 ELSIF plan->>'kind'='child_install_finish' THEN
  child:=(plan->>'install_id')::uuid;
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','install_dispose_finish',
    'install_id',to_jsonb(child))),'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',to_jsonb(p_install),
    'event_kind','install_dispose_progress','payload',jsonb_build_object('phase','completed',
     'fiber_id','null'::jsonb,'child_install_id',to_jsonb(child),'scheduled_targets','null'::jsonb))),
   'successors','[]'::jsonb);
 ELSIF plan->>'kind'='install_finish' THEN
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','install_dispose_finish',
    'install_id',to_jsonb(p_install))),'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','install','entity_id',to_jsonb(p_install),
    'event_kind','install_dispose_progress','payload',jsonb_build_object('phase','completed',
     'fiber_id','null'::jsonb,'child_install_id','null'::jsonb,'scheduled_targets','null'::jsonb))),
   'successors','[]'::jsonb);
 END IF;
 RETURN v24_cordis.empty_success();
END $$;
