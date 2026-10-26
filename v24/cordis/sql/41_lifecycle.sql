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
   OR NOT v24_cordis.scope_lineage_open(f.scope_id) THEN RETURN false; END IF;
  cur:=f.owner_id;
 END LOOP;
 RETURN true;
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
   OR f.retire_started_at IS NOT NULL OR NOT v24_cordis.fiber_lineage_open(f.id) THEN
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
    AND v24_cordis.fiber_lineage_open(f.id)
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
