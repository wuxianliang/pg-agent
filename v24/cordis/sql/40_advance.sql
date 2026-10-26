-- DP1 protocol kernel. All helpers are private INVOKER functions.
CREATE FUNCTION v24_cordis.principal_id(p_login name) RETURNS uuid
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp AS $$ SELECT md5(p_login::text)::uuid $$;
CREATE FUNCTION v24_cordis.canonical_json(p_payload jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp AS $$ SELECT p_payload::text $$;
CREATE FUNCTION v24_cordis.effect_id_for(p_principal uuid,p_request_key text,p_kind text) RETURNS uuid
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT substr(encode(sha256(convert_to(p_principal::text||':'||p_kind||':'||p_request_key,'UTF8')),'hex'),1,32)::uuid
$$;
CREATE FUNCTION v24_cordis.error_v1(p_code text,p_detail jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF p_code IS NULL OR p_code<>ALL(ARRAY['invalid_args','unauthorized','not_found_or_denied',
 'request_conflict','effect_id_conflict','receipt_conflict','stale_generation','registration_stale',
 'already_terminal','owner_closing','install_not_ready','interaction_mismatch','provider_unavailable',
 'scope_closed','dependency_unresolved','provide_conflict','install_identity_conflict','budget_exceeded',
 'invalid_outcome','stale_claim','cleanup_cycle','retry_with_closure','blocked_unknown','spawn_key_conflict']) THEN
  RAISE EXCEPTION 'unknown v1 error code' USING ERRCODE='22023';
 END IF;
 RETURN jsonb_build_object('v',1,'error',jsonb_build_object('code',p_code,'detail',p_detail));
END $$;
CREATE FUNCTION v24_cordis.exact_keys(p_value jsonb,p_keys text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_typeof(p_value)='object' AND p_value ?& p_keys AND p_value-p_keys='{}'::jsonb
$$;
CREATE FUNCTION v24_cordis.role_family() RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE owner_name text; owner_oid oid; r record; suffix text; family text;
BEGIN
 SELECT n.nspowner,pr.rolname INTO owner_oid,owner_name FROM pg_namespace n
 JOIN pg_roles pr ON pr.oid=n.nspowner WHERE n.nspname='v24_cordis';
 IF owner_name IS NULL OR owner_name!~'^v24_cordis_[0-9]+_[0-9a-f]{12}_owner$' THEN RETURN NULL; END IF;
 family:=left(owner_name,length(owner_name)-6);
 IF EXISTS(SELECT 1 FROM pg_proc p WHERE p.pronamespace='v24_cordis'::regnamespace AND p.proowner<>owner_oid) THEN RETURN NULL; END IF;
 FOREACH suffix IN ARRAY ARRAY['owner','admin','service','operator'] LOOP
  SELECT * INTO r FROM pg_roles WHERE rolname=family||'_'||suffix;
  IF NOT FOUND OR r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
    OR r.rolreplication OR r.rolbypassrls OR r.rolinherit
    OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) THEN RETURN NULL; END IF;
 END LOOP;
 RETURN family;
END $$;
CREATE FUNCTION v24_cordis.role_allowed(p_login name,p_class text,p_kind text,p_action text) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE family text:=v24_cordis.role_family(); r record; alias text;
BEGIN
 IF family IS NULL THEN RETURN false; END IF;
 SELECT * INTO r FROM pg_roles WHERE rolname=p_login;
 IF NOT FOUND OR NOT r.rolcanlogin OR NOT r.rolinherit OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
   OR r.rolreplication OR r.rolbypassrls THEN RETURN false; END IF;
 IF (SELECT count(*) FROM pg_auth_members WHERE member=r.oid)<>1 THEN RETURN false; END IF;
 FOREACH alias IN ARRAY ARRAY['admin','service','operator'] LOOP
  IF pg_has_role(p_login,(family||'_'||alias)::name,'USAGE') THEN
   RETURN (p_class='command' AND p_kind IN ('command_install','command_reconcile','command_dispose') AND p_action='admit_and_apply')
      OR (alias='service' AND p_class IN ('claim','success','failure','unknown') AND p_kind='host_io' AND p_action=p_class);
  END IF;
 END LOOP;
 RETURN false;
END $$;
CREATE FUNCTION v24_cordis.valid_body(p_body jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE ok boolean;
BEGIN
 IF p_body IS NULL OR jsonb_typeof(p_body)<>'object' OR octet_length(p_body::text)>1048576 THEN RETURN false; END IF;
 WITH RECURSIVE walk(value,depth) AS (
  SELECT p_body,1
  UNION ALL
  SELECT child.value,w.depth+1
   FROM walk w
   CROSS JOIN LATERAL (
    SELECT e.value FROM jsonb_each(CASE WHEN jsonb_typeof(w.value)='object' THEN w.value ELSE '{}'::jsonb END) e
    UNION ALL
    SELECT a.value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.value)='array' THEN w.value ELSE '[]'::jsonb END) a
   ) child
 ) SELECT coalesce(bool_and(depth<=32),false)
    AND coalesce(sum(CASE WHEN jsonb_typeof(value)='object'
       THEN (SELECT count(*) FROM jsonb_object_keys(value)) ELSE 0 END),0)<=200
   INTO ok FROM walk;
 RETURN coalesce(ok,false);
END $$;
-- Forward references define the DP1 footprint. No lifecycle reverse cleanup traversal exists yet.
CREATE FUNCTION v24_cordis.target_refs(p_table text,p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE rowdata jsonb; result jsonb:='[]'; ref record;
BEGIN
 IF p_table<>ALL(ARRAY['scopes','runs','effects','installs','fibers','episodes','contributions','pins']) THEN
  RAISE EXCEPTION 'invalid typed target' USING ERRCODE='22023';
 END IF;
 EXECUTE format('SELECT to_jsonb(t) FROM v24_cordis.%I t WHERE id=$1',p_table) INTO rowdata USING p_id;
 IF rowdata IS NULL THEN RETURN NULL; END IF;
 FOR ref IN SELECT * FROM (VALUES
  ('scopes','parent_id','scopes'),
  ('runs','owner_fiber_id','fibers'),('runs','owner_episode_id','episodes'),('runs','scope_id','scopes'),('runs','parent_run_id','runs'),
  ('effects','parent_id','effects'),('effects','fiber_id','fibers'),('effects','episode_id','episodes'),('effects','run_id','runs'),
  ('installs','scope_id','scopes'),('installs','owner_fiber_id','fibers'),('installs','owner_episode_id','episodes'),
  ('fibers','install_id','installs'),('fibers','owner_id','fibers'),('fibers','owner_episode_id','episodes'),('fibers','scope_id','scopes'),('fibers','current_episode_id','episodes'),
  ('episodes','fiber_id','fibers'),
  ('contributions','fiber_id','fibers'),('contributions','episode_id','episodes'),('contributions','prev_contribution_id','contributions'),
  ('pins','consumer_fiber_id','fibers'),('pins','consumer_episode_id','episodes'),('pins','consumer_run_id','runs'),('pins','contribution_id','contributions')
 ) AS refs(src,col,dst) WHERE src=p_table LOOP
  IF rowdata->>ref.col IS NOT NULL THEN
   result:=result||jsonb_build_array(jsonb_build_object('t',ref.dst,'id',rowdata->>ref.col));
  END IF;
 END LOOP;
 RETURN result;
END $$;
CREATE FUNCTION v24_cordis.discover_closure(p_seed jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE targets jsonb:='[]'; todo jsonb:=p_seed; item jsonb; refs jsonb; i int:=0;
BEGIN
 -- Admission stops at the 513th distinct target, before dereferencing it.
 WHILE i<jsonb_array_length(todo) LOOP
  item:=todo->i; i:=i+1;
  IF targets @> jsonb_build_array(item) THEN CONTINUE; END IF;
  IF jsonb_array_length(targets)=512 THEN RETURN NULL; END IF;
  targets:=targets||jsonb_build_array(item);
  refs:=v24_cordis.target_refs(item->>'t',(item->>'id')::uuid);
  IF refs IS NULL THEN RETURN NULL; END IF;
  todo:=todo||refs;
 END LOOP;
 RETURN (SELECT coalesce(jsonb_agg(x ORDER BY x->>'t',x->>'id'),'[]') FROM jsonb_array_elements(targets) x);
END $$;
CREATE FUNCTION v24_cordis.lock_closure(p_targets jsonb) RETURNS boolean
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE target record; parent uuid; seen uuid[]; depth int; ordered jsonb:='[]'; item jsonb; got uuid;
BEGIN
 FOR item IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
  depth:=0;
  IF item->>'t'='scopes' THEN
   parent:=(item->>'id')::uuid; seen:=ARRAY[]::uuid[];
   WHILE parent IS NOT NULL LOOP
    IF parent=ANY(seen) OR cardinality(seen)>=512 THEN RETURN false; END IF;
    seen:=array_append(seen,parent); depth:=depth+1;
    SELECT s.parent_id INTO parent FROM v24_cordis.scopes s WHERE s.id=parent;
    IF NOT FOUND THEN RETURN false; END IF;
   END LOOP;
  END IF;
  ordered:=ordered||jsonb_build_array(item||jsonb_build_object('depth',depth));
 END LOOP;
 FOR target IN SELECT x->>'t' AS t,(x->>'id')::uuid AS id FROM jsonb_array_elements(ordered) x
  ORDER BY array_position(ARRAY['scopes','runs','effects','installs','fibers','episodes','contributions','pins'],x->>'t'),
           (x->>'depth')::int,(x->>'id')::uuid LOOP
  EXECUTE format('SELECT id FROM v24_cordis.%I WHERE id=$1 FOR UPDATE',target.t) INTO got USING target.id;
  IF got IS NULL THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION v24_cordis.barrier_ready(p_effect_id uuid,p_closure jsonb) RETURNS boolean
LANGUAGE sql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$ SELECT true $$;
CREATE FUNCTION v24_cordis.interpret_command(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN RAISE EXCEPTION 'DP1 lifecycle command is not implemented' USING ERRCODE='0A000'; END $$;
CREATE FUNCTION v24_cordis.interpret_settlement(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN RAISE EXCEPTION 'DP1 lifecycle settlement is not implemented' USING ERRCODE='0A000'; END $$;
CREATE FUNCTION v24_cordis.validate_delta(p_delta jsonb,p_class text,p_structure_only boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE item jsonb; ordinals int[]:=ARRAY[]::int[]; ordinal int; status text;
BEGIN
 IF NOT coalesce(v24_cordis.exact_keys(p_delta,ARRAY['domain','receipt','events','successors']),false)
  OR jsonb_typeof(p_delta->'domain')<>'array' OR jsonb_typeof(p_delta->'events')<>'array'
  OR jsonb_typeof(p_delta->'successors')<>'array'
  OR NOT coalesce(v24_cordis.exact_keys(p_delta->'receipt',ARRAY['status']),false) THEN
  RETURN v24_cordis.error_v1('invalid_outcome');
 END IF;
 status:=CASE p_class WHEN 'command' THEN 'succeeded' WHEN 'success' THEN 'succeeded' WHEN 'failure' THEN 'failed' WHEN 'unknown' THEN 'unknown' END;
 IF status IS NULL OR p_delta->'receipt'->>'status' IS DISTINCT FROM status
   OR jsonb_array_length(p_delta->'events')>1 OR jsonb_array_length(p_delta->'successors')>16 THEN
  RETURN v24_cordis.error_v1('invalid_outcome');
 END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'events') LOOP
  IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['entity_type','entity_id','event_kind','payload']),false)
    OR jsonb_typeof(item->'entity_type')<>'string' OR jsonb_typeof(item->'event_kind')<>'string'
    OR jsonb_typeof(item->'payload')<>'object' OR coalesce(item->>'entity_id','')!~'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'successors') LOOP
  IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['ordinal','kind','input']),false)
    OR jsonb_typeof(item->'ordinal')<>'number' OR item->>'ordinal'!~'^[0-9]+$'
    OR length(item->>'ordinal')>2 OR jsonb_typeof(item->'input')<>'object'
    OR jsonb_typeof(item->'kind')<>'string'
    OR item->>'kind'<>ALL(ARRAY['dispatch','listener_call','model_call','tool_call','run_start','host_io']) THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
  ordinal:=(item->>'ordinal')::int;
  IF ordinal>15 OR ordinal=ANY(ordinals) THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  ordinals:=array_append(ordinals,ordinal);
 END LOOP;
 -- Structure-only probe validates inverse descriptors; it never permits applying rows.
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') LOOP
  IF jsonb_typeof(item)<>'object' OR NOT item ? 'inverse'
   OR jsonb_typeof(item->'inverse')<>'object'
   OR coalesce(item->'inverse'->>'op','')<>ALL(ARRAY['delete_row','restore_prev','release_reservation','dispose_child','unknown'])
   OR (item->'inverse'->>'op'='unknown' AND (NOT item->'inverse' ? 'debt' OR item->'inverse'->'debt'='null')) THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
 END LOOP;
 IF NOT p_structure_only AND (p_delta->'domain'<>'[]'::jsonb OR p_delta->'successors'<>'[]'::jsonb) THEN
  RETURN v24_cordis.error_v1('invalid_outcome','{"reason":"dp1_empty_domain_only"}');
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.validate_and_apply_delta(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_delta jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE err jsonb; response jsonb; body jsonb:=p_outcome->'body'; item jsonb; bytes bytea; sequence bigint;
BEGIN
 err:=v24_cordis.validate_delta(p_delta,p_outcome->>'class');
 IF err IS NOT NULL THEN RETURN err; END IF;
 response:=jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,'claim',NULL);
 IF p_outcome->>'class'='command' THEN
  bytes:=convert_to(v24_cordis.canonical_json(body->'payload'),'UTF8');
  INSERT INTO v24_cordis.effects(id,kind,status,input,request_actor,outcome,settled_at)
   VALUES(p_effect_id,body->>'kind','succeeded',body->'payload',session_user,p_outcome-'receipt_key',clock_timestamp());
  INSERT INTO v24_cordis.requests(principal_id,request_key,kind,request_bytes,request_digest,effect_id,response)
   VALUES(p_principal,body->>'request_key',body->>'kind',bytes,sha256(bytes),p_effect_id,response);
 ELSE
  UPDATE v24_cordis.effects SET status=p_delta->'receipt'->>'status',outcome=p_outcome-'receipt_key',
   claim_owner=NULL,lease_until=NULL,settled_at=clock_timestamp() WHERE id=p_effect_id;
 END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'events') LOOP
  SELECT coalesce(max(seq),-1)+1 INTO sequence FROM v24_cordis.events
   WHERE entity_type=item->>'entity_type' AND entity_id=(item->>'entity_id')::uuid;
  INSERT INTO v24_cordis.events(event_id,effect_id,seq,entity_type,entity_id,event_kind,payload)
   VALUES(gen_random_uuid(),p_effect_id,sequence,item->>'entity_type',(item->>'entity_id')::uuid,item->>'event_kind',item->'payload');
 END LOOP;
 RETURN response;
END $$;
CREATE FUNCTION v24_cordis.advance(p_effect_id uuid,p_outcome jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE cls text; body jsonb; token jsonb; kind text; principal uuid; bytes bytea; canonical bytea;
 req v24_cordis.requests%ROWTYPE; eff v24_cordis.effects%ROWTYPE; closure jsonb; seed jsonb;
 delta jsonb; contract jsonb; binding jsonb; reclaim boolean; error_code text; lease int; allowed boolean;
BEGIN
 -- No business relation reads or explicit locks before all pure preflight checks.
 IF p_effect_id IS NULL OR p_outcome IS NULL OR jsonb_typeof(p_outcome)<>'object'
  OR NOT p_outcome ?& ARRAY['v','class','claim','body']
  OR p_outcome-ARRAY['v','class','claim','body','receipt_key']<>'{}'::jsonb
  OR p_outcome->'v'<>'1'::jsonb OR jsonb_typeof(p_outcome->'class')<>'string'
  OR (p_outcome ? 'receipt_key' AND jsonb_typeof(p_outcome->'receipt_key')<>'string')
  OR NOT v24_cordis.valid_body(p_outcome->'body') THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
 cls:=p_outcome->>'class'; body:=p_outcome->'body'; token:=p_outcome->'claim';
 IF cls NOT IN ('command','claim','success','failure','unknown') THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
 IF cls IN ('command','claim') THEN
  IF token<>'null'::jsonb THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
 ELSE
  IF NOT coalesce(v24_cordis.exact_keys(token,ARRAY['attempt','fence','owner']),false)
   OR jsonb_typeof(token->'owner')<>'string' OR length(token->>'owner') NOT BETWEEN 1 AND 63
   OR jsonb_typeof(token->'attempt')<>'number' OR jsonb_typeof(token->'fence')<>'number'
   OR token->>'attempt'!~'^[0-9]+$' OR token->>'fence'!~'^[0-9]+$'
   OR length(token->>'attempt')>19 OR length(token->>'fence')>19 THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
  IF (token->>'attempt')::numeric>9223372036854775807 OR (token->>'fence')::numeric>9223372036854775807 THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
 END IF;
 IF cls='unknown' AND body ?| ARRAY['successors','intents'] THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
 IF cls='command' THEN
  IF NOT coalesce(v24_cordis.exact_keys(body,ARRAY['op','kind','request_key','canonical_bytes','payload']),false)
   OR body->>'op' IS DISTINCT FROM 'admit_and_apply' OR jsonb_typeof(body->'kind')<>'string'
   OR body->>'kind' NOT IN ('command_install','command_reconcile','command_dispose')
   OR jsonb_typeof(body->'request_key')<>'string' OR length(body->>'request_key') NOT BETWEEN 1 AND 512
   OR jsonb_typeof(body->'canonical_bytes')<>'string' OR jsonb_typeof(body->'payload')<>'object' THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
  canonical:=convert_to(v24_cordis.canonical_json(body->'payload'),'UTF8');
  BEGIN bytes:=decode(body->>'canonical_bytes','base64');
  EXCEPTION WHEN invalid_parameter_value OR invalid_text_representation THEN RETURN v24_cordis.error_v1('invalid_args'); END;
  IF bytes<>canonical THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
  kind:=body->>'kind';
 ELSIF cls='claim' THEN
  IF NOT coalesce(v24_cordis.exact_keys(body,ARRAY['lease_ms']),false)
   OR jsonb_typeof(body->'lease_ms')<>'number' OR body->>'lease_ms'!~'^[0-9]+$'
   OR length(body->>'lease_ms')>6 THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
  lease:=(body->>'lease_ms')::int;
  IF lease NOT BETWEEN 1 AND 300000 THEN RETURN v24_cordis.error_v1('invalid_args'); END IF;
 END IF;
 PERFORM pg_advisory_xact_lock(24,1);
 principal:=v24_cordis.principal_id(session_user);
 -- Authenticate the class before touching target rows; recheck actual kind after effect lock.
 IF NOT v24_cordis.role_allowed(session_user,cls,coalesce(kind,'host_io'),CASE WHEN cls='command' THEN 'admit_and_apply' ELSE cls END) THEN
  RETURN v24_cordis.error_v1('unauthorized');
 END IF;
 IF cls='command' THEN
  IF p_effect_id<>v24_cordis.effect_id_for(principal,body->>'request_key',kind) THEN RETURN v24_cordis.error_v1('effect_id_conflict'); END IF;
  SELECT * INTO req FROM v24_cordis.requests WHERE principal_id=principal AND request_key=body->>'request_key' FOR UPDATE;
  IF FOUND THEN
   IF req.kind=kind AND req.effect_id=p_effect_id AND req.request_bytes=bytes AND req.request_digest=sha256(bytes) THEN RETURN req.response; END IF;
   RETURN v24_cordis.error_v1('request_conflict');
  END IF;
  IF EXISTS(SELECT 1 FROM v24_cordis.effects WHERE id=p_effect_id) THEN RETURN v24_cordis.error_v1('effect_id_conflict'); END IF;
  seed:='[]';
 ELSE
  SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id FOR UPDATE;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('not_found_or_denied'); END IF;
  kind:=eff.kind;
  IF NOT v24_cordis.role_allowed(session_user,cls,kind,cls) THEN RETURN v24_cordis.error_v1('unauthorized'); END IF;
  IF eff.status IN ('succeeded','failed','unknown','cancelled') THEN
   IF cls<>'claim' AND eff.outcome IS NOT NULL AND eff.outcome-'receipt_key'=p_outcome-'receipt_key' THEN
    RETURN jsonb_build_object('v',1,'disposition','replay','effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,'claim',NULL);
   END IF;
   RETURN v24_cordis.error_v1('receipt_conflict');
  END IF;
  seed:=jsonb_build_array(jsonb_build_object('t','effects','id',p_effect_id));
 END IF;
 closure:=v24_cordis.discover_closure(seed);
 IF closure IS NULL THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 IF NOT v24_cordis.lock_closure(closure) THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 IF v24_cordis.discover_closure(seed) IS DISTINCT FROM closure THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 IF cls='claim' THEN
  SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
  IF eff.status='claimed' AND eff.lease_until>clock_timestamp() THEN
   RETURN v24_cordis.error_v1('stale_claim','{"reason":"claim_busy"}');
  END IF;
  reclaim:=eff.status='claimed'; error_code:=CASE WHEN reclaim THEN 'blocked_unknown' ELSE 'invalid_args' END;
  SELECT i.contracts->'host_io' INTO contract FROM v24_cordis.fibers f JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=eff.fiber_id;
  binding:=eff.input->'contract';
  allowed:=coalesce(jsonb_typeof(contract)='object' AND jsonb_typeof(contract->'contract_version')='string'
   AND length(contract->>'contract_version')>0 AND jsonb_typeof(contract->'handler_digest')='string'
   AND contract->>'handler_digest'~'^[0-9a-f]{64}$'
   AND v24_cordis.exact_keys(binding,ARRAY['contract_version','handler_digest'])
   AND binding->'contract_version'=contract->'contract_version' AND jsonb_typeof(binding->'handler_digest')='string'
   AND binding->'handler_digest'=contract->'handler_digest',false);
  IF NOT allowed THEN RETURN v24_cordis.error_v1(error_code); END IF;
  IF reclaim AND (contract->'replay'->'repeat' IS DISTINCT FROM 'true'::jsonb OR contract->'replay'->'concurrent' IS DISTINCT FROM 'true'::jsonb) THEN
   RETURN v24_cordis.error_v1('blocked_unknown');
  END IF;
  IF NOT v24_cordis.barrier_ready(p_effect_id,closure) THEN
   RETURN jsonb_build_object('v',1,'disposition','deferred','effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,'claim',NULL);
  END IF;
  IF eff.attempt=9223372036854775807 OR eff.fence=9223372036854775807 THEN RETURN v24_cordis.error_v1('budget_exceeded'); END IF;
  UPDATE v24_cordis.effects SET status='claimed',attempt=attempt+1,fence=fence+1,claim_owner=session_user,
   lease_until=clock_timestamp()+lease*interval '1 millisecond' WHERE id=p_effect_id RETURNING * INTO eff;
  RETURN jsonb_build_object('v',1,'disposition','claimed','effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,
   'claim',jsonb_build_object('attempt',eff.attempt,'fence',eff.fence,'owner',eff.claim_owner));
 ELSIF cls<>'command' THEN
  SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
  IF eff.status<>'claimed' OR eff.attempt<>(token->>'attempt')::bigint OR eff.fence<>(token->>'fence')::bigint
    OR eff.claim_owner IS DISTINCT FROM token->>'owner' THEN RETURN v24_cordis.error_v1('stale_claim'); END IF;
  delta:=v24_cordis.interpret_settlement(p_effect_id,principal,p_outcome,closure);
 ELSE
  delta:=v24_cordis.interpret_command(p_effect_id,principal,p_outcome,closure);
 END IF;
 RETURN v24_cordis.validate_and_apply_delta(p_effect_id,principal,p_outcome,delta,closure);
END $$;
