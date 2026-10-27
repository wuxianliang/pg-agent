-- DP2 W2: install declaration/admission, owner ledger, check policy and resolver.
-- Every helper is private SECURITY INVOKER; only advance writes. 50_permissions revokes all.
CREATE FUNCTION v24_cordis.json_bool(p_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_value)='boolean',false)
$$;
CREATE FUNCTION v24_cordis.json_key(p_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT CASE WHEN jsonb_typeof(p_value)='string'
  THEN length(p_value#>>'{}') BETWEEN 1 AND 256 ELSE false END
$$;
CREATE FUNCTION v24_cordis.json_text_map(p_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_value)='object' AND NOT EXISTS(
  SELECT 1 FROM jsonb_each(p_value) e
   WHERE jsonb_typeof(e.value)<>'string' OR length(e.value#>>'{}') NOT BETWEEN 1 AND 128),false)
$$;
CREATE FUNCTION v24_cordis.check_policy_valid(p_policy jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(p_policy='null'::jsonb OR (
  v24_cordis.exact_keys(p_policy,ARRAY['v','op','path','value'])
  AND p_policy->'v'='1'::jsonb AND p_policy->>'op'='equals'
  AND jsonb_typeof(p_policy->'path')='array'
  AND jsonb_array_length(p_policy->'path') BETWEEN 1 AND 8
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_policy->'path') x
   WHERE jsonb_typeof(x)<>'string' OR length(x#>>'{}') NOT BETWEEN 1 AND 128)),false)
$$;
CREATE FUNCTION v24_cordis.check_policy_ok(p_policy jsonb,p_descriptor jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE v jsonb:=p_descriptor; part text;
BEGIN
 IF p_policy='null'::jsonb THEN RETURN true; END IF;
 IF NOT coalesce(v24_cordis.check_policy_valid(p_policy),false) OR jsonb_typeof(p_descriptor)<>'object' THEN
  RETURN false;
 END IF;
 FOR part IN SELECT value FROM jsonb_array_elements_text(p_policy->'path') LOOP
  IF jsonb_typeof(v)<>'object' OR NOT (v ? part) THEN RETURN false; END IF;
  v:=v->part;
 END LOOP;
 RETURN v=p_policy->'value';
END $$;
CREATE FUNCTION v24_cordis.contracts_valid(p_contracts jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_contracts)='object' AND NOT EXISTS(
  SELECT 1 FROM jsonb_each(p_contracts) c
   WHERE length(c.key) NOT BETWEEN 1 AND 128
    OR NOT coalesce(v24_cordis.exact_keys(c.value,ARRAY['contract_version','handler_digest','replay']),false)
    OR NOT v24_cordis.json_text(c.value->'contract_version')
    OR NOT v24_cordis.json_hex64(c.value->'handler_digest')
    OR NOT coalesce(v24_cordis.exact_keys(c.value->'replay',ARRAY['repeat','concurrent']),false)
    OR NOT v24_cordis.json_bool(c.value->'replay'->'repeat')
    OR NOT v24_cordis.json_bool(c.value->'replay'->'concurrent')),false)
$$;
CREATE FUNCTION v24_cordis.manifest_shape_valid(p_manifest jsonb,p_contracts jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE item jsonb; key text; seen text[]:=ARRAY[]::text[];
BEGIN
 IF NOT coalesce(v24_cordis.exact_keys(p_manifest,ARRAY['requires','provides','priority','check']),false)
  OR jsonb_typeof(p_manifest->'requires')<>'array'
  OR jsonb_typeof(p_manifest->'provides')<>'array'
  OR jsonb_array_length(p_manifest->'requires')>256
  OR jsonb_array_length(p_manifest->'provides')>256
  OR NOT v24_cordis.json_int(p_manifest->'priority',-2147483648,2147483647)
  OR jsonb_typeof(p_manifest->'check')<>'object'
  OR NOT coalesce(v24_cordis.contracts_valid(p_contracts),false) THEN RETURN false; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_manifest->'requires') LOOP
  IF NOT v24_cordis.json_key(item) OR (item#>>'{}')=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,item#>>'{}');
 END LOOP;
 seen:=ARRAY[]::text[];
 FOR item IN SELECT value FROM jsonb_array_elements(p_manifest->'provides') LOOP
  IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['key','descriptor','contract_version']),false)
   OR NOT v24_cordis.json_key(item->'key') OR NOT v24_cordis.json_text(item->'contract_version')
   OR jsonb_typeof(item->'descriptor')<>'object'
   OR NOT v24_cordis.json_text(item->'descriptor'->'capability')
   OR (item->>'key')=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,item->>'key');
  IF NOT (p_contracts ? (item->'descriptor'->>'capability'))
   OR p_contracts->(item->'descriptor'->>'capability')->>'contract_version' IS DISTINCT FROM item->>'contract_version' THEN
   RETURN false;
  END IF;
 END LOOP;
 FOR key IN SELECT jsonb_object_keys(p_manifest->'check') LOOP
  IF NOT (p_manifest->'requires' @> jsonb_build_array(key))
   OR NOT coalesce(v24_cordis.check_policy_valid(p_manifest->'check'->key),false) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION v24_cordis.scope_shape_valid(p_scope jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(
  jsonb_typeof(p_scope)='object'
  AND jsonb_typeof(p_scope->'mode')='string'
  AND v24_cordis.json_uuid(p_scope->'id')
  AND CASE p_scope->>'mode'
   WHEN 'existing' THEN v24_cordis.exact_keys(p_scope,ARRAY['mode','id'])
   WHEN 'root' THEN v24_cordis.exact_keys(p_scope,ARRAY['mode','id','realm_overrides'])
    AND v24_cordis.json_text_map(p_scope->'realm_overrides')
   WHEN 'child' THEN v24_cordis.exact_keys(p_scope,ARRAY['mode','id','parent_id','realm_overrides'])
    AND v24_cordis.json_uuid(p_scope->'parent_id')
    AND v24_cordis.json_text_map(p_scope->'realm_overrides')
   ELSE false END,false)
$$;
CREATE FUNCTION v24_cordis.owner_shape_valid(p_owner jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(p_owner='null'::jsonb OR (
  v24_cordis.exact_keys(p_owner,ARRAY['fiber_id','episode_id'])
  AND v24_cordis.json_uuid(p_owner->'fiber_id')
  AND v24_cordis.json_uuid(p_owner->'episode_id')),false)
$$;
CREATE FUNCTION v24_cordis.install_payload_valid(p_payload jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(
  v24_cordis.exact_keys(p_payload,ARRAY['install_id','fiber_id','scope','owner','identity','version',
   'manifest','artifact_digest','contracts','policy_ref','overlay'])
  AND v24_cordis.json_uuid(p_payload->'install_id')
  AND v24_cordis.json_uuid(p_payload->'fiber_id')
  AND v24_cordis.scope_shape_valid(p_payload->'scope')
  AND v24_cordis.owner_shape_valid(p_payload->'owner')
  AND v24_cordis.json_text(p_payload->'identity')
  AND v24_cordis.json_text(p_payload->'version')
  AND jsonb_typeof(p_payload->'manifest')='object'
  AND v24_cordis.json_hex64(p_payload->'artifact_digest')
  AND jsonb_typeof(p_payload->'contracts')='object'
  AND (p_payload->'policy_ref'='null'::jsonb OR p_payload->'policy_ref'='"chat_tool"'::jsonb)
  AND jsonb_typeof(p_payload->'overlay')='object'
  AND v24_cordis.manifest_shape_valid(p_payload->'manifest',p_payload->'contracts'),false)
$$;
CREATE FUNCTION v24_cordis.scope_lineage_open(p_scope uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH RECURSIVE a(id,parent_id,closed_at,depth,path,cycle) AS (
  SELECT s.id,s.parent_id,s.closed_at,0,ARRAY[s.id],false FROM v24_cordis.scopes s WHERE s.id=p_scope
  UNION ALL
  SELECT s.id,s.parent_id,s.closed_at,a.depth+1,a.path||s.id,s.id=ANY(a.path)
   FROM a JOIN v24_cordis.scopes s ON s.id=a.parent_id
   WHERE NOT a.cycle AND a.depth<512)
 SELECT coalesce(count(*)>0 AND NOT bool_or(cycle OR closed_at IS NOT NULL)
  AND max(depth)<512,false) FROM a
$$;
CREATE FUNCTION v24_cordis.fiber_lineage_open(p_fiber uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE cur uuid:=p_fiber; seen uuid[]:=ARRAY[]::uuid[]; f v24_cordis.fibers%ROWTYPE; i int:=0;
BEGIN
 WHILE cur IS NOT NULL LOOP
  i:=i+1;
  IF i>512 OR cur=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,cur);
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=cur;
  IF NOT FOUND OR f.dispose_requested_at IS NOT NULL OR f.disposed_at IS NOT NULL
   OR f.retire_started_at IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM v24_cordis.installs WHERE id=f.install_id AND state='installed')
   OR NOT v24_cordis.scope_lineage_open(f.scope_id) THEN RETURN false; END IF;
  cur:=f.owner_id;
 END LOOP;
 RETURN true;
END $$;
CREATE FUNCTION v24_cordis.dispose_ancestor_sealed(p_fiber uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE cur uuid:=p_fiber; seen uuid[]:=ARRAY[]::uuid[]; f v24_cordis.fibers%ROWTYPE; i int:=0;
BEGIN
 -- Fail closed on malformed/cyclic lineage: the whole owner chain must stay open.
 WHILE cur IS NOT NULL LOOP
  i:=i+1;
  IF i>512 OR cur=ANY(seen) THEN RETURN true; END IF;
  seen:=array_append(seen,cur);
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=cur;
  IF NOT FOUND OR f.dispose_requested_at IS NOT NULL OR f.disposed_at IS NOT NULL THEN RETURN true; END IF;
  IF EXISTS(SELECT 1 FROM v24_cordis.installs WHERE id=f.install_id
   AND state IN ('dispose_pending','disposed')) THEN RETURN true; END IF;
  cur:=f.owner_id;
 END LOOP;
 RETURN false;
END $$;
CREATE FUNCTION v24_cordis.lineage_fault(p_fiber uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE cur uuid:=p_fiber; seen uuid[]:=ARRAY[]::uuid[]; f v24_cordis.fibers%ROWTYPE; i int:=0;
BEGIN
 -- Distinguish graph faults from an ordinary sealed lineage fact.
 WHILE cur IS NOT NULL LOOP
  i:=i+1;
  IF cur=ANY(seen) THEN RETURN 'cycle'; END IF;
  IF i>512 THEN RETURN 'closure_overflow'; END IF;
  seen:=array_append(seen,cur);
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=cur;
  IF NOT FOUND THEN RETURN NULL; END IF;
  cur:=f.owner_id;
 END LOOP;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.fiber_in_install_subtree(p_fiber uuid,p_install uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE cur uuid:=p_fiber; seen uuid[]:=ARRAY[]::uuid[]; f v24_cordis.fibers%ROWTYPE; i int:=0;
BEGIN
 WHILE cur IS NOT NULL LOOP
  i:=i+1;
  IF i>512 OR cur=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,cur);
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=cur;
  IF NOT FOUND THEN RETURN false; END IF;
  IF f.install_id=p_install THEN RETURN true; END IF;
  cur:=f.owner_id;
 END LOOP;
 RETURN false;
END $$;
CREATE FUNCTION v24_cordis.install_admission(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE v_scope jsonb:=p_payload->'scope'; v_owner jsonb:=p_payload->'owner';
 v_mode text; v_scope_id uuid; v_install uuid; v_fiber uuid; v_parent uuid;
 s v24_cordis.scopes%ROWTYPE; f v24_cordis.fibers%ROWTYPE; e v24_cordis.episodes%ROWTYPE;
 inst v24_cordis.installs%ROWTYPE; v_seq bigint;
BEGIN
 IF NOT coalesce(v24_cordis.install_payload_valid(p_payload),false) THEN
  RETURN jsonb_build_object('code','invalid_args','reason','install_payload');
 END IF;
 IF p_payload->'overlay'<>'{}'::jsonb THEN
  RETURN jsonb_build_object('code','0A000','reason','install_overlay');
 END IF;
 v_mode:=v_scope->>'mode'; v_scope_id:=(v_scope->>'id')::uuid;
 v_install:=(p_payload->>'install_id')::uuid; v_fiber:=(p_payload->>'fiber_id')::uuid;
 IF v_mode='existing' THEN
  SELECT * INTO s FROM v24_cordis.scopes WHERE id=v_scope_id;
  IF NOT FOUND THEN RETURN jsonb_build_object('code','not_found_or_denied','reason','install_scope'); END IF;
  IF NOT v24_cordis.scope_lineage_open(v_scope_id) THEN
   RETURN jsonb_build_object('code','scope_closed','reason','install_scope');
  END IF;
  IF s.intercept<>'{}'::jsonb THEN
   RETURN jsonb_build_object('code','0A000','reason','install_intercept');
  END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM v24_cordis.scopes WHERE id=v_scope_id) THEN
   RETURN jsonb_build_object('code','invalid_args','reason','scope_id');
  END IF;
  IF v_mode='child' THEN
   v_parent:=(v_scope->>'parent_id')::uuid;
   SELECT * INTO s FROM v24_cordis.scopes WHERE id=v_parent;
   IF NOT FOUND THEN RETURN jsonb_build_object('code','not_found_or_denied','reason','install_parent'); END IF;
   IF NOT v24_cordis.scope_lineage_open(v_parent) THEN
    RETURN jsonb_build_object('code','scope_closed','reason','install_parent');
   END IF;
   IF s.intercept<>'{}'::jsonb THEN
    RETURN jsonb_build_object('code','0A000','reason','install_intercept');
   END IF;
  END IF;
 END IF;
 IF v_owner='null'::jsonb AND v_mode='child' THEN
  RETURN jsonb_build_object('code','invalid_args','reason','install_scope_mode');
 END IF;
 IF v_owner<>'null'::jsonb AND v_mode='root' THEN
  RETURN jsonb_build_object('code','invalid_args','reason','install_scope_mode');
 END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.installs WHERE id=v_install) THEN
  RETURN jsonb_build_object('code','invalid_args','reason','install_id');
 END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.fibers WHERE id=v_fiber) THEN
  RETURN jsonb_build_object('code','invalid_args','reason','fiber_id');
 END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.installs WHERE scope_id=v_scope_id
  AND identity=p_payload->>'identity' AND version=p_payload->>'version') THEN
  RETURN jsonb_build_object('code','install_identity_conflict','reason','install_address');
 END IF;
 IF v_owner='null'::jsonb THEN
  IF EXISTS(SELECT 1 FROM v24_cordis.fibers WHERE owner_id IS NULL) THEN
   RETURN jsonb_build_object('code','invalid_args','reason','unique_root');
  END IF;
 ELSE
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=(v_owner->>'fiber_id')::uuid;
  IF NOT FOUND THEN RETURN jsonb_build_object('code','not_found_or_denied','reason','install_owner'); END IF;
  SELECT * INTO e FROM v24_cordis.episodes
   WHERE id=(v_owner->>'episode_id')::uuid AND fiber_id=f.id;
  IF NOT FOUND OR e.closed_at IS NOT NULL OR e.state<>'active'
   OR f.current_episode_id IS DISTINCT FROM e.id THEN
   RETURN jsonb_build_object('code','owner_closing','reason','install_owner');
  END IF;
  IF NOT f.want_on OR f.dispose_requested_at IS NOT NULL OR f.disposed_at IS NOT NULL
   OR f.retire_started_at IS NOT NULL THEN
   RETURN jsonb_build_object('code','owner_closing','reason','install_owner');
  END IF;
  IF jsonb_typeof(f.failure)='object'
   AND v24_cordis.json_int(f.failure->'control_seq',0,9223372036854775807)
   AND (f.failure->>'control_seq')::bigint=f.control_seq THEN
   RETURN jsonb_build_object('code','owner_closing','reason','install_owner_failure');
  END IF;
  SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
  IF NOT FOUND OR inst.state<>'installed' THEN
   RETURN jsonb_build_object('code','owner_closing','reason','install_owner_install');
  END IF;
  IF jsonb_typeof(e.iterator)<>'object'
   OR NOT coalesce(v24_cordis.exact_keys(e.iterator,
     ARRAY['v','next_index','registered_through','control_seq']),false)
   OR e.iterator->'v' IS DISTINCT FROM '1'::jsonb
   OR NOT v24_cordis.json_int(e.iterator->'next_index',0,2147483647)
   OR NOT v24_cordis.json_int(e.iterator->'registered_through',-1,2147483647)
   OR NOT v24_cordis.json_int(e.iterator->'control_seq',0,9223372036854775807) THEN
   RETURN jsonb_build_object('code','invalid_args','reason','install_owner_iterator');
  END IF;
  SELECT coalesce(max(seq),-1)::bigint+1 INTO v_seq FROM v24_cordis.contributions
   WHERE fiber_id=f.id AND episode_id=e.id;
  IF v_seq>2147483647 THEN
   RETURN jsonb_build_object('code','budget_exceeded','reason','install_owner_seq');
  END IF;
  BEGIN
   IF NOT v24_cordis.fiber_live_resolve_ok(f.id,e.id) THEN
    RETURN jsonb_build_object('code','owner_closing','reason','install_owner_live'); END IF;
  EXCEPTION WHEN SQLSTATE 'P0401' THEN
   RETURN jsonb_build_object('code','retry_with_closure','reason','provider_closure');
  END;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.install_delta(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE v_scope jsonb:=p_payload->'scope'; v_owner jsonb:=p_payload->'owner';
 v_scope_id uuid:=(v_scope->>'id')::uuid; v_install uuid:=(p_payload->>'install_id')::uuid;
 v_fiber uuid:=(p_payload->>'fiber_id')::uuid; v_owner_fiber uuid; v_owner_ep uuid;
 v_ep v24_cordis.episodes%ROWTYPE; v_seq bigint; v_next int; v_child uuid; v_created boolean;
 v_domain jsonb:='[]'; v_event jsonb;
BEGIN
 v_created:=v_scope->>'mode'<>'existing';
 IF v_created THEN
  v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','scope_create','id',v_scope_id,
   'parent_id',CASE WHEN v_scope->>'mode'='child' THEN v_scope->'parent_id' ELSE 'null'::jsonb END,
   'realm_overrides',v_scope->'realm_overrides'));
 END IF;
 IF v_owner<>'null'::jsonb THEN
  v_owner_fiber:=(v_owner->>'fiber_id')::uuid; v_owner_ep:=(v_owner->>'episode_id')::uuid;
 ELSE
  v_owner_fiber:=NULL; v_owner_ep:=NULL;
 END IF;
 v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','install_create',
  'id',v_install,'scope_id',v_scope_id,
  'owner_fiber_id',CASE WHEN v_owner='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(v_owner_fiber) END,
  'owner_episode_id',CASE WHEN v_owner='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(v_owner_ep) END,
  'identity',p_payload->>'identity','version',p_payload->>'version',
  'manifest',p_payload->'manifest','artifact_digest',p_payload->>'artifact_digest',
  'contracts',p_payload->'contracts','policy_ref',p_payload->'policy_ref','overlay',p_payload->'overlay'));
 v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','fiber_create',
  'id',v_fiber,'install_id',v_install,
  'owner_id',CASE WHEN v_owner='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(v_owner_fiber) END,
  'owner_episode_id',CASE WHEN v_owner='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(v_owner_ep) END,
  'scope_id',v_scope_id));
 IF v_owner<>'null'::jsonb THEN
  SELECT * INTO v_ep FROM v24_cordis.episodes WHERE id=v_owner_ep AND fiber_id=v_owner_fiber;
  v_next:=(v_ep.iterator->>'next_index')::int;
  SELECT coalesce(max(seq),-1)::bigint+1 INTO v_seq FROM v24_cordis.contributions
   WHERE fiber_id=v_owner_fiber AND episode_id=v_owner_ep;
  v_child:=gen_random_uuid();
  v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','contribution_append',
   'id',v_child,'fiber_id',v_owner_fiber,'episode_id',v_owner_ep,'seq',v_seq,'kind','child',
   'realm','null'::jsonb,'key','null'::jsonb,
   'descriptor',jsonb_build_object('child_fiber_id',to_jsonb(v_fiber)),
   'prev_contribution_id','null'::jsonb,'inverse',jsonb_build_object('op','dispose_child'),
   'contract_version','1'));
  v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','episode_progress',
   'episode_id',v_owner_ep,'next_index',v_next,'registered_through',v_seq));
 ELSE
  v_child:=NULL;
 END IF;
 v_event:=jsonb_build_object('entity_type','install','entity_id',to_jsonb(v_install),
  'event_kind','install_created','payload',jsonb_build_object('scope_id',to_jsonb(v_scope_id),
   'scope_created',v_created,'fiber_id',to_jsonb(v_fiber),
   'owner_fiber_id',CASE WHEN v_owner='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(v_owner_fiber) END,
   'owner_episode_id',CASE WHEN v_owner='null'::jsonb THEN 'null'::jsonb ELSE to_jsonb(v_owner_ep) END,
   'child_contribution_id',CASE WHEN v_child IS NULL THEN 'null'::jsonb ELSE to_jsonb(v_child) END));
 RETURN jsonb_build_object('domain',v_domain,'receipt',jsonb_build_object('status','succeeded'),
  'events',jsonb_build_array(v_event),'successors','[]'::jsonb);
END $$;
CREATE FUNCTION v24_cordis.interpret_install(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE err jsonb; payload jsonb:=p_outcome->'body'->'payload';
BEGIN
 err:=v24_cordis.install_admission(payload);
 IF err IS NOT NULL THEN
  IF err->>'code'='0A000' THEN RAISE EXCEPTION '%',err->>'reason' USING ERRCODE='0A000'; END IF;
  RETURN v24_cordis.error_v1(err->>'code',jsonb_build_object('reason',err->>'reason'));
 END IF;
 RETURN v24_cordis.install_delta(payload);
END $$;
CREATE FUNCTION v24_cordis.validate_install_domain(p_outcome jsonb,p_delta jsonb,p_closure jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE payload jsonb:=p_outcome->'body'->'payload'; v_scope jsonb:=payload->'scope';
 v_owner jsonb:=payload->'owner'; err jsonb; v_scope_id uuid:=(v_scope->>'id')::uuid;
 v_install uuid:=(payload->>'install_id')::uuid; v_fiber uuid:=(payload->>'fiber_id')::uuid;
 v_created boolean:=v_scope->>'mode'<>'existing'; v_ops text[]; v_item jsonb; v_cnt int;
 v_child uuid; v_seq bigint; v_next int; v_owner_fiber uuid; v_owner_ep uuid;
BEGIN
 err:=v24_cordis.install_admission(payload);
 IF err IS NOT NULL THEN
  IF err->>'code'='0A000' THEN RAISE EXCEPTION '%',err->>'reason' USING ERRCODE='0A000'; END IF;
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_admission'));
 END IF;
 IF v_owner<>'null'::jsonb THEN
  v_owner_fiber:=(v_owner->>'fiber_id')::uuid; v_owner_ep:=(v_owner->>'episode_id')::uuid;
 END IF;
 v_ops:=ARRAY(SELECT x->>'op' FROM jsonb_array_elements(p_delta->'domain') x);
 IF v_created THEN
  IF (SELECT count(*) FROM unnest(v_ops) o WHERE o='scope_create')<>1 THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_scope'));
  END IF;
  SELECT value INTO v_item FROM jsonb_array_elements(p_delta->'domain') x
   WHERE x.value->>'op'='scope_create' LIMIT 1;
  IF (v_item->>'id')::uuid<>v_scope_id
   OR v_item->'parent_id' IS DISTINCT FROM (CASE WHEN v_scope->>'mode'='child'
     THEN v_scope->'parent_id' ELSE 'null'::jsonb END)
   OR v_item->'realm_overrides' IS DISTINCT FROM v_scope->'realm_overrides' THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_scope'));
  END IF;
 ELSE
  IF (SELECT count(*) FROM unnest(v_ops) o WHERE o='scope_create')<>0 THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_scope'));
  END IF;
 END IF;
 IF (SELECT count(*) FROM unnest(v_ops) o WHERE o='install_create')<>1
  OR (SELECT count(*) FROM unnest(v_ops) o WHERE o='fiber_create')<>1 THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_rows'));
 END IF;
 SELECT value INTO v_item FROM jsonb_array_elements(p_delta->'domain') x
  WHERE x.value->>'op'='install_create' LIMIT 1;
 IF (v_item->>'id')::uuid<>v_install OR (v_item->>'scope_id')::uuid<>v_scope_id
  OR v_item->'owner_fiber_id' IS DISTINCT FROM (CASE WHEN v_owner='null'::jsonb
    THEN 'null'::jsonb ELSE to_jsonb(v_owner_fiber) END)
  OR v_item->'owner_episode_id' IS DISTINCT FROM (CASE WHEN v_owner='null'::jsonb
    THEN 'null'::jsonb ELSE to_jsonb(v_owner_ep) END)
  OR v_item->>'identity' IS DISTINCT FROM payload->>'identity'
  OR v_item->>'version' IS DISTINCT FROM payload->>'version'
  OR v_item->'manifest' IS DISTINCT FROM payload->'manifest'
  OR v_item->>'artifact_digest' IS DISTINCT FROM payload->>'artifact_digest'
  OR v_item->'contracts' IS DISTINCT FROM payload->'contracts'
  OR v_item->'policy_ref' IS DISTINCT FROM payload->'policy_ref'
  OR v_item->'overlay' IS DISTINCT FROM payload->'overlay' THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_rows'));
 END IF;
 SELECT value INTO v_item FROM jsonb_array_elements(p_delta->'domain') x
  WHERE x.value->>'op'='fiber_create' LIMIT 1;
 IF (v_item->>'id')::uuid<>v_fiber OR (v_item->>'install_id')::uuid<>v_install
  OR (v_item->>'scope_id')::uuid<>v_scope_id
  OR v_item->'owner_id' IS DISTINCT FROM (CASE WHEN v_owner='null'::jsonb
    THEN 'null'::jsonb ELSE to_jsonb(v_owner_fiber) END)
  OR v_item->'owner_episode_id' IS DISTINCT FROM (CASE WHEN v_owner='null'::jsonb
    THEN 'null'::jsonb ELSE to_jsonb(v_owner_ep) END) THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_rows'));
 END IF;
 v_child:=NULL;
 IF v_owner='null'::jsonb THEN
  IF (SELECT count(*) FROM unnest(v_ops) o WHERE o IN ('contribution_append','episode_progress'))<>0 THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_ledger'));
  END IF;
 ELSE
  IF (SELECT count(*) FROM unnest(v_ops) o WHERE o='contribution_append')<>1
   OR (SELECT count(*) FROM unnest(v_ops) o WHERE o='episode_progress')<>1 THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_ledger'));
  END IF;
  SELECT value INTO v_item FROM jsonb_array_elements(p_delta->'domain') x
   WHERE x.value->>'op'='contribution_append' LIMIT 1;
  v_child:=(v_item->>'id')::uuid;
  IF EXISTS(SELECT 1 FROM v24_cordis.contributions WHERE id=v_child) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_ledger'));
  END IF;
  SELECT coalesce(max(seq),-1)::bigint+1 INTO v_seq FROM v24_cordis.contributions
   WHERE fiber_id=(v_owner->>'fiber_id')::uuid AND episode_id=(v_owner->>'episode_id')::uuid;
  SELECT (iterator->>'next_index')::int INTO v_next FROM v24_cordis.episodes
   WHERE id=(v_owner->>'episode_id')::uuid;
  IF (v_item->>'fiber_id')::uuid<>(v_owner->>'fiber_id')::uuid
   OR (v_item->>'episode_id')::uuid<>(v_owner->>'episode_id')::uuid
   OR (v_item->>'seq')::bigint<>v_seq OR v_item->>'kind'<>'child'
   OR v_item->'realm'<>'null'::jsonb OR v_item->'key'<>'null'::jsonb
   OR v_item->'descriptor' IS DISTINCT FROM jsonb_build_object('child_fiber_id',to_jsonb(v_fiber))
   OR v_item->'prev_contribution_id'<>'null'::jsonb
   OR v_item->'inverse' IS DISTINCT FROM jsonb_build_object('op','dispose_child')
   OR v_item->>'contract_version'<>'1' THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_ledger'));
  END IF;
  SELECT value INTO v_item FROM jsonb_array_elements(p_delta->'domain') x
   WHERE x.value->>'op'='episode_progress' LIMIT 1;
  IF (v_item->>'episode_id')::uuid<>(v_owner->>'episode_id')::uuid
   OR (v_item->>'next_index')::int<>v_next OR (v_item->>'registered_through')::bigint<>v_seq THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_ledger'));
  END IF;
 END IF;
 IF jsonb_array_length(p_delta->'events')<>1 THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_cardinality'));
 END IF;
 v_item:=p_delta->'events'->0;
 IF v_item->>'entity_type'<>'install' OR (v_item->>'entity_id')::uuid<>v_install
  OR v_item->>'event_kind'<>'install_created'
  OR v_item->'payload'->'scope_id' IS DISTINCT FROM to_jsonb(v_scope_id)
  OR v_item->'payload'->'scope_created' IS DISTINCT FROM to_jsonb(v_created)
  OR v_item->'payload'->'fiber_id' IS DISTINCT FROM to_jsonb(v_fiber)
  OR v_item->'payload'->'owner_fiber_id' IS DISTINCT FROM (CASE WHEN v_owner='null'::jsonb
    THEN 'null'::jsonb ELSE to_jsonb(v_owner_fiber) END)
  OR v_item->'payload'->'owner_episode_id' IS DISTINCT FROM (CASE WHEN v_owner='null'::jsonb
    THEN 'null'::jsonb ELSE to_jsonb(v_owner_ep) END)
  OR v_item->'payload'->'child_contribution_id' IS DISTINCT FROM (CASE WHEN v_child IS NULL
    THEN 'null'::jsonb ELSE to_jsonb(v_child) END) THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_shape'));
 END IF;
 IF p_delta->'successors'<>'[]'::jsonb THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','install_successor'));
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.install_command_seed(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE result jsonb:='[]'; item jsonb; v_scope jsonb:=p_payload->'scope'; v_owner jsonb:=p_payload->'owner';
 v_scope_id uuid; v_owner_ep uuid;
BEGIN
 IF jsonb_typeof(p_payload)<>'object' OR jsonb_typeof(v_scope)<>'object' THEN RETURN '[]'; END IF;
 IF v24_cordis.json_uuid(v_scope->'id') THEN
  v_scope_id:=(v_scope->>'id')::uuid;
  IF v_scope->>'mode'='existing' THEN
   result:=result||jsonb_build_array(jsonb_build_object('t','scopes','id',v_scope_id::text));
  ELSIF v_scope->>'mode'='child' AND v24_cordis.json_uuid(v_scope->'parent_id') THEN
   result:=result||jsonb_build_array(jsonb_build_object('t','scopes','id',v_scope->>'parent_id'));
  END IF;
  IF v24_cordis.json_text(p_payload->'identity') AND v24_cordis.json_text(p_payload->'version') THEN
   FOR item IN SELECT jsonb_build_object('t','installs','id',i.id)
    FROM v24_cordis.installs i WHERE i.scope_id=v_scope_id
     AND i.identity=p_payload->>'identity' AND i.version=p_payload->>'version' LOOP
    result:=result||jsonb_build_array(item);
   END LOOP;
  END IF;
 END IF;
 IF jsonb_typeof(v_owner)='object' THEN
  IF v24_cordis.json_uuid(v_owner->'fiber_id') THEN
   result:=result||jsonb_build_array(jsonb_build_object('t','fibers','id',v_owner->>'fiber_id'));
  END IF;
  IF v24_cordis.json_uuid(v_owner->'episode_id') THEN
   v_owner_ep:=(v_owner->>'episode_id')::uuid;
   result:=result||jsonb_build_array(jsonb_build_object('t','episodes','id',v_owner_ep::text));
   FOR item IN SELECT jsonb_build_object('t','contributions','id',c.id)
    FROM v24_cordis.contributions c WHERE c.episode_id=v_owner_ep LOOP
    result:=result||jsonb_build_array(item);
   END LOOP;
  END IF;
 ELSE
  FOR item IN SELECT jsonb_build_object('t','fibers','id',f.id)
   FROM v24_cordis.fibers f WHERE f.owner_id IS NULL LOOP
   result:=result||jsonb_build_array(item);
  END LOOP;
 END IF;
 RETURN (SELECT coalesce(jsonb_agg(x ORDER BY x->>'t',x->>'id'),'[]')
  FROM (SELECT DISTINCT value x FROM jsonb_array_elements(result)) s);
END $$;
CREATE FUNCTION v24_cordis.resolve(p_scope uuid,p_keys text[])
RETURNS TABLE(pkey text,contribution_id uuid,provider_fiber_id uuid,provider_episode_id uuid,
 provider_epoch int,descriptor jsonb,descriptor_digest text,contract_version text,available boolean)
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE scopes jsonb; bad boolean; v_key text; v_realm text; v_row record; v_i int;
BEGIN
 IF p_keys IS NULL OR cardinality(p_keys)>256 OR array_position(p_keys,NULL) IS NOT NULL THEN RETURN; END IF;
 IF v24_cordis.scope_live_fault(p_scope) IN ('cycle','closure_overflow') THEN
  RAISE EXCEPTION 'scope closure requires retry' USING ERRCODE='P0401'; END IF;
 WITH RECURSIVE a(id,parent_id,closed_at,realm_overrides,depth,path,cycle) AS (
  SELECT s.id,s.parent_id,s.closed_at,s.realm_overrides,0,ARRAY[s.id],false
   FROM v24_cordis.scopes s WHERE s.id=p_scope
  UNION ALL
  SELECT s.id,s.parent_id,s.closed_at,s.realm_overrides,a.depth+1,a.path||s.id,s.id=ANY(a.path)
   FROM a JOIN v24_cordis.scopes s ON s.id=a.parent_id
   WHERE NOT a.cycle AND a.depth<512)
 SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'overrides',realm_overrides) ORDER BY depth),'[]'::jsonb),
  coalesce(bool_or(cycle OR closed_at IS NOT NULL) OR max(depth)>=512,false)
  INTO scopes,bad FROM a;
 IF scopes='[]'::jsonb OR bad THEN
  FOR v_key IN SELECT unnest(p_keys) LOOP
   pkey:=v_key; contribution_id:=NULL; provider_fiber_id:=NULL; provider_episode_id:=NULL;
   provider_epoch:=NULL; descriptor:=NULL; descriptor_digest:=NULL; contract_version:=NULL;
   available:=false; RETURN NEXT;
  END LOOP;
  RETURN;
 END IF;
 FOR v_i IN 1..cardinality(p_keys) LOOP
  v_key:=p_keys[v_i]; v_realm:=NULL;
  SELECT realm INTO v_realm FROM (
   SELECT e.value#>>'{}' AS realm FROM jsonb_array_elements(scopes) WITH ORDINALITY s(x,ord)
    CROSS JOIN LATERAL jsonb_each(CASE WHEN jsonb_typeof(x->'overrides')='object'
      THEN x->'overrides' ELSE '{}'::jsonb END) e
    WHERE e.key=v_key AND jsonb_typeof(e.value)='string'
     AND length(e.value#>>'{}') BETWEEN 1 AND 128
    ORDER BY ord LIMIT 1) q;
  v_realm:=coalesce(v_realm,'root');
  SELECT c.id,c.fiber_id,c.episode_id,e.epoch,c.descriptor,
   encode(sha256(convert_to(v24_cordis.canonical_json(c.descriptor),'UTF8')),'hex') AS digest,
   c.contract_version INTO v_row
   FROM v24_cordis.contributions c JOIN v24_cordis.episodes e ON e.id=c.episode_id
   JOIN v24_cordis.fibers f ON f.id=c.fiber_id
   JOIN v24_cordis.installs i ON i.id=f.install_id
   WHERE c.kind='service' AND c.realm=v_realm AND c.key=v_key
    AND c.withdrawn_at IS NULL AND c.released_at IS NULL
    AND e.closed_at IS NULL AND e.state='active' AND f.current_episode_id=e.id
    AND f.want_on AND f.dispose_requested_at IS NULL AND f.disposed_at IS NULL
    AND f.retire_started_at IS NULL AND i.state='installed'
    AND v24_cordis.fiber_live_resolve_ok(f.id,e.id)
    AND NOT (jsonb_typeof(f.failure)='object' AND v24_cordis.json_int(f.failure->'control_seq',0,9223372036854775807)
      AND (f.failure->>'control_seq')::bigint=f.control_seq)
   LIMIT 1;
  pkey:=v_key;
  IF FOUND THEN
   contribution_id:=v_row.id; provider_fiber_id:=v_row.fiber_id;
   provider_episode_id:=v_row.episode_id; provider_epoch:=v_row.epoch;
   descriptor:=v_row.descriptor; descriptor_digest:=v_row.digest;
   contract_version:=v_row.contract_version; available:=true;
  ELSE
   contribution_id:=NULL; provider_fiber_id:=NULL; provider_episode_id:=NULL;
   provider_epoch:=NULL; descriptor:=NULL; descriptor_digest:=NULL;
   contract_version:=NULL; available:=false;
  END IF;
  RETURN NEXT;
 END LOOP;
END $$;
CREATE FUNCTION v24_cordis.install_preflight(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE ref text;
BEGIN
 IF NOT coalesce(v24_cordis.install_payload_valid(p_payload),false) THEN
  RETURN jsonb_build_object('code','invalid_args','reason','install_payload');
 END IF;
 ref:=v24_cordis.install_references(p_payload);
 IF ref IS NOT NULL THEN
  RETURN jsonb_build_object('code','not_found_or_denied','reason',ref);
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.command_binding(p_body jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT CASE p_body->>'kind'
  WHEN 'command_install' THEN CASE WHEN p_body->'payload'->'owner'='null'::jsonb
   THEN jsonb_build_object('fiber',p_body->'payload'->>'fiber_id','episode',NULL)
   ELSE jsonb_build_object('fiber',p_body->'payload'->'owner'->>'fiber_id',
    'episode',p_body->'payload'->'owner'->>'episode_id') END
  WHEN 'command_reconcile' THEN jsonb_build_object('fiber',p_body->'payload'->>'fiber_id','episode',NULL)
  ELSE jsonb_build_object('fiber',NULL,'episode',NULL) END
$$;
CREATE FUNCTION v24_cordis.install_references(p_payload jsonb) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE s jsonb:=p_payload->'scope'; o jsonb:=p_payload->'owner';
BEGIN
 IF s->>'mode'='existing' AND NOT EXISTS(SELECT 1 FROM v24_cordis.scopes WHERE id=(s->>'id')::uuid) THEN RETURN 'install_scope'; END IF;
 IF s->>'mode'='child' AND NOT EXISTS(SELECT 1 FROM v24_cordis.scopes WHERE id=(s->>'parent_id')::uuid) THEN RETURN 'install_parent'; END IF;
 IF jsonb_typeof(o)='object' THEN
  IF NOT EXISTS(SELECT 1 FROM v24_cordis.fibers f JOIN v24_cordis.episodes e ON e.fiber_id=f.id
   WHERE f.id=(o->>'fiber_id')::uuid AND e.id=(o->>'episode_id')::uuid) THEN RETURN 'install_owner'; END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.require_key(p_item jsonb) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT CASE WHEN jsonb_typeof(p_item)='string' THEN p_item#>>'{}'
  WHEN jsonb_typeof(p_item)='object' THEN p_item->>'key' END
$$;
CREATE FUNCTION v24_cordis.activation_fail(p_reason text) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('code','0A000','reason',p_reason)
$$;
CREATE FUNCTION v24_cordis.activation_bubble(p_err jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF p_err IS NULL THEN RETURN NULL; END IF;
 IF p_err->>'code'='0A000' THEN RAISE EXCEPTION '%',p_err->>'reason' USING ERRCODE='0A000'; END IF;
 RETURN v24_cordis.error_v1(p_err->>'code',jsonb_build_object('reason',p_err->>'reason'));
END $$;
CREATE FUNCTION v24_cordis.scope_intercepted(p_scope uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 WITH RECURSIVE a(id,parent_id,intercept,depth,path,cycle) AS (
  SELECT s.id,s.parent_id,s.intercept,0,ARRAY[s.id],false FROM v24_cordis.scopes s WHERE s.id=p_scope
  UNION ALL
  SELECT s.id,s.parent_id,s.intercept,a.depth+1,a.path||s.id,s.id=ANY(a.path)
   FROM a JOIN v24_cordis.scopes s ON s.id=a.parent_id WHERE NOT a.cycle AND a.depth<512)
 SELECT coalesce(bool_or(intercept<>'{}'::jsonb),false) FROM a
$$;
CREATE FUNCTION v24_cordis.service_realm(p_scope uuid,p_key text) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE v_n int; v_bad boolean; v_realm text;
BEGIN
 IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 128 THEN RETURN NULL; END IF;
 WITH RECURSIVE a(id,parent_id,realm_overrides,intercept,closed_at,depth,path,cycle) AS (
  SELECT s.id,s.parent_id,s.realm_overrides,s.intercept,s.closed_at,0,ARRAY[s.id],false
   FROM v24_cordis.scopes s WHERE s.id=p_scope
  UNION ALL
  SELECT s.id,s.parent_id,s.realm_overrides,s.intercept,s.closed_at,a.depth+1,a.path||s.id,s.id=ANY(a.path)
   FROM a JOIN v24_cordis.scopes s ON s.id=a.parent_id WHERE NOT a.cycle AND a.depth<512)
 SELECT count(*), coalesce(bool_or(cycle OR depth>=512 OR intercept<>'{}'::jsonb OR closed_at IS NOT NULL),true),
  (SELECT e.value#>>'{}' FROM a x CROSS JOIN LATERAL jsonb_each(CASE WHEN jsonb_typeof(x.realm_overrides)='object'
    THEN x.realm_overrides ELSE '{}'::jsonb END) e
   WHERE e.key=p_key AND jsonb_typeof(e.value)='string' AND length(e.value#>>'{}') BETWEEN 1 AND 128
   ORDER BY x.depth LIMIT 1)
  INTO v_n,v_bad,v_realm FROM a;
 IF v_n=0 OR v_bad THEN RETURN NULL; END IF;
 RETURN coalesce(v_realm,'root');
END $$;
CREATE FUNCTION v24_cordis.reconcile_successor(p_fiber uuid,p_seq bigint) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_array(jsonb_build_object('ordinal',0,'kind','command_reconcile','input',
  jsonb_build_object('fiber_id',to_jsonb(p_fiber),'action','advance','expected_control_seq',to_jsonb(p_seq))))
$$;
CREATE FUNCTION v24_cordis.empty_success() RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT jsonb_build_object('domain','[]'::jsonb,'receipt',jsonb_build_object('status','succeeded'),
  'events','[]'::jsonb,'successors','[]'::jsonb)
$$;
CREATE FUNCTION v24_cordis.activation_admission(p_fiber uuid,p_control boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 o v24_cordis.fibers%ROWTYPE; oe v24_cordis.episodes%ROWTYPE; oi v24_cordis.installs%ROWTYPE;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND THEN RETURN jsonb_build_object('code','not_found_or_denied','reason','reconcile_fiber'); END IF;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND OR inst.state<>'installed' THEN
  RETURN jsonb_build_object('code','install_not_ready','reason','reconcile_install'); END IF;
 IF inst.overlay<>'{}'::jsonb THEN RETURN v24_cordis.activation_fail('install_overlay'); END IF;
 IF v24_cordis.scope_live_fault(f.scope_id) IN ('cycle','closure_overflow') THEN
  RETURN jsonb_build_object('code','retry_with_closure','reason','provider_closure'); END IF;
 IF NOT v24_cordis.scope_lineage_open(f.scope_id) THEN
  RETURN jsonb_build_object('code','scope_closed','reason','reconcile_scope'); END IF;
 IF v24_cordis.scope_intercepted(f.scope_id) THEN RETURN v24_cordis.activation_fail('install_intercept'); END IF;
 IF v24_cordis.lineage_fault(f.id) IS NOT NULL THEN
  RETURN jsonb_build_object('code','retry_with_closure','reason','provider_closure'); END IF;
 IF f.dispose_requested_at IS NOT NULL OR f.disposed_at IS NOT NULL
  OR v24_cordis.dispose_ancestor_sealed(f.id)
  OR (NOT p_control AND f.retire_started_at IS NOT NULL) THEN
  RETURN jsonb_build_object('code','owner_closing','reason','fiber_closed'); END IF;
 IF f.owner_id IS NOT NULL THEN
  SELECT * INTO o FROM v24_cordis.fibers WHERE id=f.owner_id;
  SELECT * INTO oe FROM v24_cordis.episodes WHERE id=f.owner_episode_id AND fiber_id=o.id;
  IF NOT FOUND OR oe.closed_at IS NOT NULL OR oe.state<>'active' OR o.current_episode_id IS DISTINCT FROM oe.id
   OR NOT o.want_on OR o.dispose_requested_at IS NOT NULL OR o.disposed_at IS NOT NULL
   OR o.retire_started_at IS NOT NULL THEN
   RETURN jsonb_build_object('code','owner_closing','reason','reconcile_owner'); END IF;
  IF jsonb_typeof(o.failure)='object' AND v24_cordis.json_int(o.failure->'control_seq',0,9223372036854775807)
   AND (o.failure->>'control_seq')::bigint=o.control_seq THEN
   RETURN jsonb_build_object('code','owner_closing','reason','reconcile_owner_failure'); END IF;
  SELECT * INTO oi FROM v24_cordis.installs WHERE id=o.install_id;
  IF NOT FOUND OR oi.state<>'installed' THEN
   RETURN jsonb_build_object('code','owner_closing','reason','reconcile_owner_install'); END IF;
  IF oi.overlay<>'{}'::jsonb THEN RETURN v24_cordis.activation_fail('owner_overlay'); END IF;
  BEGIN
   IF NOT v24_cordis.fiber_live_resolve_ok(o.id,oe.id) THEN
    RETURN jsonb_build_object('code','owner_closing','reason','reconcile_owner_live'); END IF;
  EXCEPTION WHEN SQLSTATE 'P0401' THEN
   RETURN jsonb_build_object('code','retry_with_closure','reason','provider_closure');
  END;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.activation_dag(p_consumer uuid,p_providers uuid[]) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE seen uuid[]:=ARRAY[p_consumer]; q uuid[]:=ARRAY[]::uuid[]; idx int:=1; node uuid; parent uuid; n int:=1;
BEGIN
 p_providers:=coalesce(p_providers,ARRAY[]::uuid[]);
 SELECT coalesce(array_agg(x),ARRAY[]::uuid[]) INTO q FROM (
  SELECT f.owner_id AS x FROM v24_cordis.fibers f WHERE f.id=p_consumer AND f.owner_id IS NOT NULL AND f.disposed_at IS NULL
  UNION SELECT c.fiber_id FROM v24_cordis.pins p JOIN v24_cordis.contributions c ON c.id=p.contribution_id
   JOIN v24_cordis.fibers cf ON cf.id=p.consumer_fiber_id AND cf.disposed_at IS NULL
   JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id AND pf.disposed_at IS NULL
   WHERE p.consumer_fiber_id=p_consumer AND p.released_at IS NULL
  UNION SELECT c.fiber_id FROM v24_cordis.pins p JOIN v24_cordis.runs r ON r.id=p.consumer_run_id
   JOIN v24_cordis.contributions c ON c.id=p.contribution_id
   JOIN v24_cordis.fibers rf ON rf.id=r.owner_fiber_id AND rf.disposed_at IS NULL
   JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id AND pf.disposed_at IS NULL
   WHERE r.owner_fiber_id=p_consumer AND p.released_at IS NULL
  UNION SELECT unnest(p_providers)) s WHERE x IS NOT NULL;
 WHILE idx<=coalesce(cardinality(q),0) LOOP
  node:=q[idx]; idx:=idx+1;
  IF node IS NULL THEN CONTINUE; END IF;
  IF node=p_consumer THEN RETURN jsonb_build_object('code','cleanup_cycle','reason','activation_cycle'); END IF;
  IF node=ANY(seen) THEN CONTINUE; END IF;
  n:=n+1;
  IF n>512 THEN RETURN jsonb_build_object('code','retry_with_closure','reason','activation_dag'); END IF;
  seen:=array_append(seen,node);
  FOR parent IN
   SELECT f.owner_id FROM v24_cordis.fibers f WHERE f.id=node AND f.owner_id IS NOT NULL AND f.disposed_at IS NULL
   UNION SELECT c.fiber_id FROM v24_cordis.pins p JOIN v24_cordis.contributions c ON c.id=p.contribution_id
    JOIN v24_cordis.fibers cf ON cf.id=p.consumer_fiber_id AND cf.disposed_at IS NULL
    JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id AND pf.disposed_at IS NULL
    WHERE p.consumer_fiber_id=node AND p.released_at IS NULL
   UNION SELECT c.fiber_id FROM v24_cordis.pins p JOIN v24_cordis.runs r ON r.id=p.consumer_run_id
    JOIN v24_cordis.contributions c ON c.id=p.contribution_id
    JOIN v24_cordis.fibers rf ON rf.id=r.owner_fiber_id AND rf.disposed_at IS NULL
    JOIN v24_cordis.fibers pf ON pf.id=c.fiber_id AND pf.disposed_at IS NULL
    WHERE r.owner_fiber_id=node AND p.released_at IS NULL
  LOOP
   q:=q||ARRAY[parent];
  END LOOP;
 END LOOP;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.provider_closure_ok(p_fiber uuid,p_episode uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE state jsonb;
BEGIN
 state:=v24_cordis.fiber_live_state(p_fiber,p_episode);
 IF coalesce((state->>'closure_overflow')::boolean,false) OR coalesce((state->>'cycle')::boolean,false) THEN
  RETURN jsonb_build_object('code','retry_with_closure','reason','provider_closure');
 END IF;
 IF NOT coalesce((state->>'live')::boolean,false) THEN RETURN v24_cordis.activation_fail('provider_closure'); END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.activation_bindings(p_fiber uuid,p_scope uuid,p_requires jsonb,p_check jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE v_i int; v_key text; v_row record; v_view jsonb:='{}'::jsonb; v_pins jsonb:='[]'::jsonb;
 v_keys jsonb:='[]'::jsonb; v_pin_ids jsonb:='[]'::jsonb; v_providers uuid[]:=ARRAY[]::uuid[];
 v_pin uuid; v_overlay jsonb; v_pscope uuid; v_err jsonb; v_policy jsonb;
BEGIN
 IF jsonb_typeof(p_requires)<>'array' THEN RETURN v24_cordis.activation_fail('requires_shape'); END IF;
 FOR v_i IN 0..jsonb_array_length(p_requires)-1 LOOP
  v_key:=v24_cordis.require_key(p_requires->v_i);
  IF v_key IS NULL OR length(v_key) NOT BETWEEN 1 AND 128 THEN RETURN v24_cordis.activation_fail('require_key'); END IF;
  SELECT * INTO v_row FROM v24_cordis.resolve(p_scope,ARRAY[v_key]);
  IF NOT FOUND OR NOT v_row.available THEN RETURN v24_cordis.activation_fail('dependency_missing'); END IF;
  v_policy:=coalesce(p_check->v_key,'null'::jsonb);
  IF NOT v24_cordis.check_policy_ok(v_policy,v_row.descriptor) THEN RETURN v24_cordis.activation_fail('check_failed'); END IF;
  SELECT i.overlay,f.scope_id INTO v_overlay,v_pscope FROM v24_cordis.fibers f
   JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=v_row.provider_fiber_id;
  IF v_overlay<>'{}'::jsonb THEN RETURN v24_cordis.activation_fail('provider_overlay'); END IF;
  IF v24_cordis.scope_intercepted(v_pscope) THEN RETURN v24_cordis.activation_fail('provider_intercept'); END IF;
  v_err:=v24_cordis.provider_closure_ok(v_row.provider_fiber_id,v_row.provider_episode_id);
  IF v_err IS NOT NULL THEN RETURN v_err; END IF;
  v_pin:=gen_random_uuid();
  v_view:=v_view||jsonb_build_object(v_key,jsonb_build_object(
   'contribution_id',to_jsonb(v_row.contribution_id),'provider_fiber_id',to_jsonb(v_row.provider_fiber_id),
   'provider_episode_id',to_jsonb(v_row.provider_episode_id),'provider_epoch',to_jsonb(v_row.provider_epoch),
   'descriptor_digest',to_jsonb(v_row.descriptor_digest),'contract_version',to_jsonb(v_row.contract_version)));
  v_pins:=v_pins||jsonb_build_array(jsonb_build_object('id',to_jsonb(v_pin),'key',to_jsonb(v_key),
   'contribution_id',to_jsonb(v_row.contribution_id),'provider_episode_id',to_jsonb(v_row.provider_episode_id),
   'provider_epoch',to_jsonb(v_row.provider_epoch)));
  v_keys:=v_keys||jsonb_build_array(to_jsonb(v_key));
  v_pin_ids:=v_pin_ids||jsonb_build_array(to_jsonb(v_pin));
  v_providers:=v_providers||ARRAY[v_row.provider_fiber_id];
 END LOOP;
 v_err:=v24_cordis.activation_dag(p_fiber,v_providers);
 IF v_err IS NOT NULL THEN RETURN v_err; END IF;
 RETURN jsonb_build_object('view',v_view,'pins',v_pins,'keys',v_keys,'pin_ids',v_pin_ids);
END $$;
CREATE FUNCTION v24_cordis.activation_consistent(p_fiber uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 v_key text; v_i int; v_row record; v_bind jsonb; v_pin v24_cordis.pins%ROWTYPE; v_n int; v_err jsonb;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 IF NOT FOUND OR NOT f.want_on OR f.current_episode_id IS NULL THEN RETURN v24_cordis.activation_fail('phase_drift'); END IF;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'reloading' THEN RETURN v24_cordis.activation_fail('phase_drift'); END IF;
 IF jsonb_typeof(ep.iterator)<>'object' OR NOT v24_cordis.exact_keys(ep.iterator,ARRAY['v','next_index','registered_through','control_seq'])
  OR ep.iterator->'v' IS DISTINCT FROM '1'::jsonb
  OR NOT v24_cordis.json_int(ep.iterator->'next_index',0,2147483647)
  OR NOT v24_cordis.json_int(ep.iterator->'registered_through',-1,2147483647)
  OR NOT v24_cordis.json_int(ep.iterator->'control_seq',0,9223372036854775807)
  OR (ep.iterator->>'control_seq')::bigint<>f.control_seq THEN
  RETURN v24_cordis.activation_fail('iterator_drift'); END IF;
 v_err:=v24_cordis.activation_admission(f.id);
 IF v_err IS NOT NULL THEN RETURN v24_cordis.activation_fail(coalesce(v_err->>'reason','admission_drift')); END IF;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF jsonb_typeof(inst.manifest->'requires')<>'array' OR jsonb_typeof(ep.committed_view)<>'object'
  OR (SELECT count(*) FROM jsonb_object_keys(ep.committed_view))<>jsonb_array_length(inst.manifest->'requires') THEN
  RETURN v24_cordis.activation_fail('view_drift'); END IF;
 FOR v_i IN 0..jsonb_array_length(inst.manifest->'requires')-1 LOOP
  v_key:=v24_cordis.require_key(inst.manifest->'requires'->v_i);
  IF v_key IS NULL OR NOT (ep.committed_view ? v_key) THEN RETURN v24_cordis.activation_fail('view_drift'); END IF;
  v_bind:=ep.committed_view->v_key;
  SELECT * INTO v_row FROM v24_cordis.resolve(f.scope_id,ARRAY[v_key]);
  IF NOT FOUND OR NOT v_row.available
   OR v_row.contribution_id IS DISTINCT FROM (v_bind->>'contribution_id')::uuid
   OR v_row.provider_fiber_id IS DISTINCT FROM (v_bind->>'provider_fiber_id')::uuid
   OR v_row.provider_episode_id IS DISTINCT FROM (v_bind->>'provider_episode_id')::uuid
   OR v_row.provider_epoch IS DISTINCT FROM (v_bind->>'provider_epoch')::int
   OR v_row.descriptor_digest IS DISTINCT FROM v_bind->>'descriptor_digest'
   OR v_row.contract_version IS DISTINCT FROM v_bind->>'contract_version'
   OR NOT v24_cordis.check_policy_ok(coalesce(inst.manifest->'check'->v_key,'null'::jsonb),v_row.descriptor) THEN
   RETURN v24_cordis.activation_fail('binding_drift'); END IF;
  SELECT * INTO v_pin FROM v24_cordis.pins WHERE consumer_fiber_id=f.id AND consumer_episode_id=ep.id
   AND key=v_key AND released_at IS NULL;
  IF NOT FOUND OR v_pin.contribution_id IS DISTINCT FROM v_row.contribution_id
   OR v_pin.provider_epoch IS DISTINCT FROM v_row.provider_epoch THEN
   RETURN v24_cordis.activation_fail('pin_drift'); END IF;
  v_err:=v24_cordis.provider_closure_ok(v_row.provider_fiber_id,v_row.provider_episode_id);
  IF v_err IS NOT NULL THEN RETURN v_err; END IF;
 END LOOP;
 SELECT count(*) INTO v_n FROM v24_cordis.pins WHERE consumer_fiber_id=f.id AND consumer_episode_id=ep.id AND released_at IS NULL;
 IF v_n<>jsonb_array_length(inst.manifest->'requires') THEN RETURN v24_cordis.activation_fail('pin_drift'); END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.activation_total(p_fiber uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 c v24_cordis.contributions%ROWTYPE; item jsonb; realm text; v_i int; v_n int;
BEGIN
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=p_fiber;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF NOT FOUND OR jsonb_typeof(inst.manifest->'provides')<>'array' THEN RETURN v24_cordis.activation_fail('totality'); END IF;
 IF NOT coalesce(v24_cordis.contracts_valid(inst.contracts),false) THEN RETURN v24_cordis.activation_fail('totality'); END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions WHERE fiber_id=f.id AND episode_id=ep.id AND kind='service'
  AND (withdrawn_at IS NOT NULL OR released_at IS NOT NULL)) THEN RETURN v24_cordis.activation_fail('totality'); END IF;
 SELECT count(*) INTO v_n FROM v24_cordis.contributions WHERE fiber_id=f.id AND episode_id=ep.id AND kind='service'
  AND withdrawn_at IS NULL AND released_at IS NULL;
 IF v_n<>jsonb_array_length(inst.manifest->'provides') THEN RETURN v24_cordis.activation_fail('totality'); END IF;
 FOR v_i IN 0..v_n-1 LOOP
  item:=inst.manifest->'provides'->v_i;
  realm:=v24_cordis.service_realm(f.scope_id,item->>'key');
  SELECT * INTO c FROM v24_cordis.contributions WHERE fiber_id=f.id AND episode_id=ep.id AND seq=v_i AND kind='service'
   AND withdrawn_at IS NULL AND released_at IS NULL;
  IF item->'descriptor'->>'capability' IS NULL
   OR inst.contracts->(item->'descriptor'->>'capability')->>'contract_version' IS DISTINCT FROM item->>'contract_version'
   OR NOT FOUND OR c.key IS DISTINCT FROM item->>'key' OR c.descriptor IS DISTINCT FROM item->'descriptor'
   OR c.contract_version IS DISTINCT FROM item->>'contract_version' OR c.realm IS DISTINCT FROM realm
   OR c.prev_contribution_id IS NOT NULL OR c.inverse IS DISTINCT FROM '{"op":"delete_row"}'::jsonb THEN
   RETURN v24_cordis.activation_fail('totality'); END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.interpret_reconcile(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE payload jsonb:=p_outcome->'body'->'payload'; action text:=payload->>'action';
 f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE;
 err jsonb; built jsonb; v_epoch bigint; v_episode uuid; v_next int; v_len int; v_batch int; v_i int;
 v_reg bigint; v_seq int; item jsonb; v_key text; v_realm text; seen text[]:=ARRAY[]::text[];
 v_domain jsonb:='[]'::jsonb; v_ids jsonb:='[]'::jsonb; v_first int; v_last int; cid uuid;
BEGIN
 IF action NOT IN ('on','off','retry','advance') THEN RETURN v24_cordis.error_v1('invalid_args',jsonb_build_object('reason','reconcile_action')); END IF;
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=(payload->>'fiber_id')::uuid;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('not_found_or_denied',jsonb_build_object('reason','reconcile_fiber')); END IF;
 IF action IN ('on','off','retry') THEN
  built:=v24_cordis.reconcile_branch(f.id,action,(payload->>'expected_control_seq')::bigint);
  IF built->>'kind'='error' THEN
   IF built->>'sqlstate'='0A000' THEN RAISE EXCEPTION '%',built->>'reason' USING ERRCODE='0A000'; END IF;
   RETURN v24_cordis.error_v1(built->>'code',built->'detail');
  END IF;
  RETURN v24_cordis.p0_delta(f.id,built);
 END IF;
 IF action='advance' AND f.current_episode_id IS NOT NULL THEN
  SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
  IF FOUND AND ep.state='active' THEN
   built:=v24_cordis.reconcile_branch(f.id,action,(payload->>'expected_control_seq')::bigint);
   IF built->>'kind'='error' THEN
    IF built->>'sqlstate'='0A000' THEN RAISE EXCEPTION '%',built->>'reason' USING ERRCODE='0A000'; END IF;
    RETURN v24_cordis.error_v1(built->>'code',built->'detail');
   END IF;
   IF built->>'kind' IN ('active_noop','idle_noop') THEN RETURN v24_cordis.empty_success(); END IF;
   IF built->>'kind'='leave' THEN RETURN v24_cordis.closing_delta(f.id,built); END IF;
  END IF;
  IF ep.id IS NOT NULL AND ep.closed_at IS NULL AND ep.state='closing' THEN
   -- P6 selects exactly one branch; deferred/blocked/unsupported are classified by the barrier.
   built:=v24_cordis.p6_plan(p_effect_id,f.id);
   IF built->>'kind'='blocked_unknown' THEN
    RETURN v24_cordis.error_v1('blocked_unknown',jsonb_build_object('reason',built->>'reason'));
   ELSIF built->>'kind'='unsupported' THEN
    RAISE EXCEPTION '%',built->>'reason' USING ERRCODE='0A000';
   ELSIF built->>'kind' IN ('inverse','pins_release','close') THEN
    RETURN v24_cordis.p6_delta(p_effect_id,f.id);
   ELSE
    RETURN v24_cordis.empty_success();
   END IF;
  END IF;
 END IF;
 built:=v24_cordis.reconcile_branch(f.id,action,(payload->>'expected_control_seq')::bigint);
 IF built->>'kind'='error' THEN
  IF built->>'sqlstate'='0A000' THEN RAISE EXCEPTION '%',built->>'reason' USING ERRCODE='0A000'; END IF;
  RETURN v24_cordis.error_v1(built->>'code',built->'detail');
 END IF;
 IF built->>'kind' IN ('divert','raise','leave') THEN RETURN v24_cordis.closing_delta(f.id,built); END IF;
 IF built->>'kind' IN ('active_noop','idle_noop') THEN RETURN v24_cordis.empty_success(); END IF;
 err:=v24_cordis.activation_admission(f.id);
 IF action='advance' AND err IS NOT NULL THEN RAISE EXCEPTION '%',err->>'reason' USING ERRCODE='0A000'; END IF;
 err:=v24_cordis.activation_bubble(err);
 IF err IS NOT NULL THEN RETURN err; END IF;
 IF action='on' THEN
  IF f.want_on THEN RETURN v24_cordis.empty_success(); END IF;
  IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
   RAISE EXCEPTION 'target_drift' USING ERRCODE='0A000'; END IF;
  IF f.control_seq=9223372036854775807 THEN
   RETURN v24_cordis.error_v1('budget_exceeded',jsonb_build_object('reason','control_seq')); END IF;
  IF EXISTS(SELECT 1 FROM v24_cordis.effects WHERE fiber_id=f.id AND kind='command_reconcile' AND status IN ('ready','claimed')) THEN
   RAISE EXCEPTION 'reconcile_slot' USING ERRCODE='0A000'; END IF;
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','fiber_control','fiber_id',to_jsonb(f.id),
    'want_on',true,'control_seq',to_jsonb(f.control_seq+1))),
   'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),
    'event_kind','fiber_target_requested','payload',jsonb_build_object('want_on',true,'control_seq',to_jsonb(f.control_seq+1)))),
   'successors',v24_cordis.reconcile_successor(f.id,f.control_seq+1));
 END IF;

 SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
 IF f.current_episode_id IS NULL THEN
  IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
   RAISE EXCEPTION 'phase_drift' USING ERRCODE='0A000'; END IF;
  IF NOT v24_cordis.manifest_shape_valid(inst.manifest,inst.contracts) THEN
   RAISE EXCEPTION 'manifest_drift' USING ERRCODE='0A000'; END IF;
  built:=v24_cordis.activation_bindings(f.id,f.scope_id,inst.manifest->'requires',inst.manifest->'check');
  err:=v24_cordis.activation_bubble(CASE WHEN built ? 'code' THEN built END);
  IF err IS NOT NULL THEN RETURN err; END IF;
  SELECT coalesce(max(epoch),0)::bigint+1 INTO v_epoch FROM v24_cordis.episodes WHERE fiber_id=f.id;
  IF v_epoch>2147483647 THEN RETURN v24_cordis.error_v1('budget_exceeded',jsonb_build_object('reason','episode_epoch')); END IF;
  v_episode:=gen_random_uuid();
  RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','episode_begin','id',to_jsonb(v_episode),
    'fiber_id',to_jsonb(f.id),'epoch',to_jsonb(v_epoch),'committed_view',built->'view','pins',built->'pins',
    'iterator',jsonb_build_object('v',1,'next_index',0,'registered_through',-1,'control_seq',to_jsonb(f.control_seq)))),
   'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),'event_kind','episode_begun',
    'payload',jsonb_build_object('episode_id',to_jsonb(v_episode),'epoch',to_jsonb(v_epoch),'control_seq',to_jsonb(f.control_seq),
     'require_keys',built->'keys','pin_ids',built->'pin_ids'))),
   'successors',v24_cordis.reconcile_successor(f.id,f.control_seq));
 END IF;
 SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
 IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'reloading' THEN RAISE EXCEPTION 'phase_drift' USING ERRCODE='0A000'; END IF;
 err:=v24_cordis.activation_bubble(v24_cordis.activation_consistent(f.id));
 IF err IS NOT NULL THEN RETURN err; END IF;
 IF jsonb_typeof(inst.manifest->'provides')<>'array' THEN RAISE EXCEPTION 'provides_shape' USING ERRCODE='0A000'; END IF;
 v_next:=(ep.iterator->>'next_index')::int; v_len:=jsonb_array_length(inst.manifest->'provides');
 v_reg:=(ep.iterator->>'registered_through')::bigint;
 IF v_next<v_len THEN
  v_batch:=least(32,v_len-v_next);
  IF v_reg+v_batch>2147483647 THEN RETURN v24_cordis.error_v1('budget_exceeded',jsonb_build_object('reason','contribution_seq')); END IF;
  FOR v_i IN 0..v_batch-1 LOOP
   item:=inst.manifest->'provides'->(v_next+v_i); v_key:=item->>'key'; v_realm:=v24_cordis.service_realm(f.scope_id,v_key);
   IF v_realm IS NULL OR v_key IS NULL OR length(v_key) NOT BETWEEN 1 AND 128 THEN RAISE EXCEPTION 'realm_unavailable' USING ERRCODE='0A000'; END IF;
   IF (v_realm||'/'||v_key)=ANY(seen) OR EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.kind='service'
    AND c.realm=v_realm AND c.key=v_key AND c.released_at IS NULL) THEN
    RAISE EXCEPTION 'address_conflict' USING ERRCODE='0A000'; END IF;
   seen:=array_append(seen,v_realm||'/'||v_key);
   IF item->'descriptor' IS NULL OR inst.contracts->(item->'descriptor'->>'capability')->>'contract_version'
    IS DISTINCT FROM item->>'contract_version' THEN RAISE EXCEPTION 'contract_drift' USING ERRCODE='0A000'; END IF;
   v_seq:=(v_reg+1+v_i)::int; cid:=gen_random_uuid();
   IF v_i=0 THEN v_first:=v_seq; END IF; v_last:=v_seq;
   v_ids:=v_ids||jsonb_build_array(to_jsonb(cid));
   v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','contribution_append','id',to_jsonb(cid),
    'fiber_id',to_jsonb(f.id),'episode_id',to_jsonb(ep.id),'seq',to_jsonb(v_seq),'kind','service',
    'realm',to_jsonb(v_realm),'key',to_jsonb(v_key),'descriptor',item->'descriptor','prev_contribution_id','null'::jsonb,
    'inverse',jsonb_build_object('op','delete_row'),'contract_version',to_jsonb(item->>'contract_version')));
  END LOOP;
  v_domain:=v_domain||jsonb_build_array(jsonb_build_object('op','episode_progress','episode_id',to_jsonb(ep.id),
   'next_index',to_jsonb(v_next+v_batch),'registered_through',to_jsonb(v_reg+v_batch)));
  RETURN jsonb_build_object('domain',v_domain,'receipt',jsonb_build_object('status','succeeded'),
   'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),
    'event_kind','contributions_appended','payload',jsonb_build_object('episode_id',to_jsonb(ep.id),
     'contribution_ids',v_ids,'seq_from',to_jsonb(v_first),'seq_through',to_jsonb(v_last),'next_index',to_jsonb(v_next+v_batch)))),
   'successors',v24_cordis.reconcile_successor(f.id,f.control_seq));
 END IF;
 err:=v24_cordis.activation_bubble(v24_cordis.activation_total(f.id));
 IF err IS NOT NULL THEN RETURN err; END IF;
 RETURN jsonb_build_object('domain',jsonb_build_array(jsonb_build_object('op','episode_activate','episode_id',to_jsonb(ep.id))),
  'receipt',jsonb_build_object('status','succeeded'),
  'events',jsonb_build_array(jsonb_build_object('entity_type','fiber','entity_id',to_jsonb(f.id),
   'event_kind','episode_activated','payload',jsonb_build_object('episode_id',to_jsonb(ep.id),'epoch',to_jsonb(ep.epoch)))),
  'successors','[]'::jsonb);
END $$;
CREATE FUNCTION v24_cordis.reconcile_preflight(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM v24_cordis.fibers WHERE id=(p_payload->>'fiber_id')::uuid) THEN
  RETURN jsonb_build_object('code','not_found_or_denied','reason','reconcile_fiber');
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.reconcile_command_seed(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE result jsonb:='[]'::jsonb; fid uuid; n int; k text; v_realm text; scope uuid;
 reqs jsonb; provs jsonb; v_have boolean:=false; r record; item jsonb; sub jsonb;
BEGIN
 IF NOT v24_cordis.reconcile_payload_valid(p_payload) THEN RETURN '[]'::jsonb; END IF;
 fid:=(p_payload->>'fiber_id')::uuid;
 result:=result||jsonb_build_array(jsonb_build_object('t','fibers','id',fid::text));
 FOR item IN
  SELECT jsonb_build_object('t','episodes','id',e.id) FROM v24_cordis.episodes e
   JOIN v24_cordis.fibers f ON f.current_episode_id=e.id WHERE f.id=fid
  UNION ALL SELECT jsonb_build_object('t','contributions','id',c.id) FROM v24_cordis.contributions c
   JOIN v24_cordis.fibers f ON f.current_episode_id=c.episode_id
   WHERE f.id=fid AND c.fiber_id=fid AND c.released_at IS NULL
    AND p_payload->>'action'='advance'
  UNION ALL SELECT jsonb_build_object('t','runs','id',rr.id) FROM v24_cordis.runs rr
   JOIN v24_cordis.fibers f ON f.id=rr.owner_fiber_id
   WHERE f.id=fid AND rr.owner_episode_id=f.current_episode_id
    AND p_payload->>'action'='advance'
  UNION ALL SELECT jsonb_build_object('t','pins','id',pp.id) FROM v24_cordis.pins pp
   JOIN v24_cordis.runs rr ON rr.id=pp.consumer_run_id
   JOIN v24_cordis.fibers f ON f.id=rr.owner_fiber_id
   WHERE f.id=fid AND rr.owner_episode_id=f.current_episode_id AND pp.released_at IS NULL
    AND p_payload->>'action'='advance'
  UNION ALL SELECT jsonb_build_object('t','effects','id',x.id) FROM v24_cordis.effects x
   WHERE x.fiber_id=fid AND x.kind='command_reconcile' AND x.status IN ('ready','claimed')
  UNION ALL SELECT jsonb_build_object('t','pins','id',p.id) FROM v24_cordis.pins p
   JOIN v24_cordis.fibers f ON f.current_episode_id=p.consumer_episode_id
   WHERE f.id=fid AND p.consumer_fiber_id=fid AND p.released_at IS NULL
 LOOP
  result:=result||jsonb_build_array(item);
  IF jsonb_array_length(result)>512 THEN RETURN NULL; END IF;
 END LOOP;
 SELECT f.scope_id,i.manifest->'requires',i.manifest->'provides' INTO scope,reqs,provs
  FROM v24_cordis.fibers f JOIN v24_cordis.installs i ON i.id=f.install_id WHERE f.id=fid;
 v_have:=FOUND;
 IF v_have AND jsonb_typeof(reqs)='array' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(reqs) LOOP
   k:=v24_cordis.require_key(item);
   IF k IS NULL THEN CONTINUE; END IF;
   FOR r IN SELECT * FROM v24_cordis.resolve(scope,ARRAY[k]) LOOP
    IF r.available THEN
     result:=result||jsonb_build_array(jsonb_build_object('t','contributions','id',r.contribution_id),
      jsonb_build_object('t','fibers','id',r.provider_fiber_id),jsonb_build_object('t','episodes','id',r.provider_episode_id));
     FOR sub IN SELECT jsonb_build_object('t','pins','id',p.id) FROM v24_cordis.pins p
      WHERE p.consumer_fiber_id=r.provider_fiber_id AND p.consumer_episode_id=r.provider_episode_id AND p.released_at IS NULL
      UNION ALL SELECT jsonb_build_object('t','contributions','id',c.id) FROM v24_cordis.pins p
       JOIN v24_cordis.contributions c ON c.id=p.contribution_id
       WHERE p.consumer_fiber_id=r.provider_fiber_id AND p.consumer_episode_id=r.provider_episode_id AND p.released_at IS NULL
     LOOP
      result:=result||jsonb_build_array(sub);
      IF jsonb_array_length(result)>512 THEN RETURN NULL; END IF;
     END LOOP;
    END IF;
   END LOOP;
   IF jsonb_array_length(result)>512 THEN RETURN NULL; END IF;
  END LOOP;
 END IF;
 IF v_have AND jsonb_typeof(provs)='array' THEN
  FOR item IN SELECT value FROM jsonb_array_elements(provs) LOOP
   v_realm:=v24_cordis.service_realm(scope,item->>'key');
   IF v_realm IS NULL THEN CONTINUE; END IF;
   FOR r IN SELECT c.id FROM v24_cordis.contributions c WHERE c.kind='service' AND c.realm=v_realm
    AND c.key=item->>'key' AND c.released_at IS NULL LOOP
    result:=result||jsonb_build_array(jsonb_build_object('t','contributions','id',r.id));
    IF jsonb_array_length(result)>512 THEN RETURN NULL; END IF;
   END LOOP;
  END LOOP;
 END IF;
 SELECT count(*) INTO n FROM (SELECT DISTINCT value FROM jsonb_array_elements(result)) s;
 IF n>512 THEN RETURN NULL; END IF;
 RETURN (SELECT coalesce(jsonb_agg(x ORDER BY x->>'t',x->>'id'),'[]'::jsonb)
  FROM (SELECT DISTINCT value x FROM jsonb_array_elements(result)) s);
EXCEPTION WHEN SQLSTATE 'P0401' THEN RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.dispose_command_seed(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE result jsonb:='[]'::jsonb; iid uuid; plan jsonb; fid uuid; n int;
BEGIN
 IF NOT v24_cordis.json_uuid(p_payload->'install_id') THEN RETURN '[]'::jsonb; END IF;
 iid:=(p_payload->>'install_id')::uuid;
 result:=result||jsonb_build_array(jsonb_build_object('t','installs','id',iid::text));
 plan:=v24_cordis.dispose_plan(iid);
 -- Only the object this step can write is locked. History, pins, runs, effects and
 -- contribution proof sets are read under G; released/settled history never inflates closure.
 IF plan->>'kind' IN ('fiber_request','fiber_control','schedule','fiber_finish','wait_slot') THEN
  fid:=(plan->>'fiber_id')::uuid;
  result:=result||jsonb_build_array(jsonb_build_object('t','fibers','id',fid::text));
 ELSIF plan->>'kind'='child_install_finish' THEN
  result:=result||jsonb_build_array(jsonb_build_object('t','installs','id',plan->>'install_id'));
 END IF;
 SELECT count(*) INTO n FROM (SELECT DISTINCT value FROM jsonb_array_elements(result)) s;
 IF n>512 THEN RETURN NULL; END IF;
 RETURN (SELECT coalesce(jsonb_agg(x ORDER BY x->>'t',x->>'id'),'[]'::jsonb)
  FROM (SELECT DISTINCT value x FROM jsonb_array_elements(result)) s);
END $$;
CREATE FUNCTION v24_cordis.dispose_preflight(p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM v24_cordis.installs WHERE id=(p_payload->>'install_id')::uuid) THEN
  RETURN jsonb_build_object('code','not_found_or_denied','reason','dispose_install');
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.dispose_block_reason(p_install uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE fids uuid[];
BEGIN
 SELECT coalesce(array_agg(id),ARRAY[]::uuid[]) INTO fids FROM v24_cordis.fibers WHERE install_id=p_install;
 IF EXISTS(SELECT 1 FROM v24_cordis.fibers WHERE id=ANY(fids) AND want_on) THEN RETURN 'want_on'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=ANY(fids) AND closed_at IS NULL) THEN RETURN 'open_episode'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.contributions WHERE fiber_id=ANY(fids) AND released_at IS NULL) THEN RETURN 'contribution'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.released_at IS NULL AND (
   p.consumer_fiber_id=ANY(fids)
   OR p.contribution_id IN (SELECT id FROM v24_cordis.contributions WHERE fiber_id=ANY(fids))
   OR p.consumer_run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=ANY(fids)))) THEN
  RETURN 'pin'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.runs WHERE owner_fiber_id=ANY(fids) AND ended_at IS NULL) THEN RETURN 'run'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.fibers c WHERE c.owner_id=ANY(fids) AND c.install_id<>p_install
  AND c.disposed_at IS NULL) THEN RETURN 'child_fiber'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.installs i WHERE i.owner_fiber_id=ANY(fids) AND i.id<>p_install
  AND i.state<>'disposed') THEN RETURN 'child_install'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.status IN ('ready','claimed') AND (
   x.fiber_id=ANY(fids)
   OR x.episode_id IN (SELECT id FROM v24_cordis.episodes WHERE fiber_id=ANY(fids))
   OR x.run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=ANY(fids)))) THEN
  RETURN 'live_effect'; END IF;
 IF EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.kind='host_io' AND (
   x.fiber_id=ANY(fids)
   OR x.episode_id IN (SELECT id FROM v24_cordis.episodes WHERE fiber_id=ANY(fids))
   OR x.run_id IN (SELECT id FROM v24_cordis.runs WHERE owner_fiber_id=ANY(fids)))) THEN
  RETURN 'host_io'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.interpret_dispose(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE inst v24_cordis.installs%ROWTYPE; payload jsonb:=p_outcome->'body'->'payload'; plan jsonb;
BEGIN
 SELECT * INTO inst FROM v24_cordis.installs WHERE id=(payload->>'install_id')::uuid;
 IF NOT FOUND THEN RETURN v24_cordis.error_v1('not_found_or_denied',jsonb_build_object('reason','dispose_install')); END IF;
 IF inst.state='disposed' THEN RETURN v24_cordis.error_v1('already_terminal',jsonb_build_object('reason','dispose_terminal')); END IF;
 IF inst.state NOT IN ('installed','dispose_pending') THEN RAISE EXCEPTION 'install_state' USING ERRCODE='0A000'; END IF;
 plan:=v24_cordis.dispose_plan(inst.id);
 IF plan->>'kind'='missing' THEN RETURN v24_cordis.error_v1('not_found_or_denied',jsonb_build_object('reason','dispose_install')); END IF;
 IF plan->>'kind'='terminal' THEN RETURN v24_cordis.error_v1('already_terminal',jsonb_build_object('reason','dispose_terminal')); END IF;
 IF plan->>'kind'='unsupported' THEN RAISE EXCEPTION '%',plan->>'reason' USING ERRCODE='0A000'; END IF;
 IF plan->>'kind'='budget' THEN RETURN v24_cordis.error_v1('budget_exceeded',jsonb_build_object('reason',plan->>'reason')); END IF;
 IF plan->>'kind'='blocked_unknown' THEN RETURN v24_cordis.error_v1('blocked_unknown',jsonb_build_object('reason',plan->>'reason')); END IF;
 IF plan->>'kind'='deferred' THEN RETURN v24_cordis.empty_success(); END IF;
 RETURN v24_cordis.dispose_delta(inst.id);
END $$;








