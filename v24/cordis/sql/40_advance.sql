-- Cordis protocol kernel. All helpers are private INVOKER functions; only advance is DEFINER.
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
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp
BEGIN ATOMIC
 SELECT jsonb_typeof(p_value)='object' AND p_value ?& p_keys AND p_value-p_keys='{}'::jsonb;
END;
CREATE FUNCTION v24_cordis.json_uuid(p_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_value)='string' AND (p_value#>>'{}') ~
  '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',false)
$$;
CREATE FUNCTION v24_cordis.json_int(p_value jsonb,p_lo bigint,p_hi bigint) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp
BEGIN ATOMIC
 SELECT CASE WHEN jsonb_typeof(p_value)='number'
  AND (p_value#>>'{}') ~ '^-?(0|[1-9][0-9]*)$' AND length(p_value#>>'{}')<=20
  THEN (p_value#>>'{}')::numeric BETWEEN p_lo AND p_hi ELSE false END;
END;
CREATE FUNCTION v24_cordis.json_text(p_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp
BEGIN ATOMIC
 SELECT CASE WHEN jsonb_typeof(p_value)='string'
  THEN length(p_value#>>'{}') BETWEEN 1 AND 128 ELSE false END;
END;
CREATE FUNCTION v24_cordis.json_hex64(p_value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_value)='string' AND (p_value#>>'{}') ~ '^[0-9a-f]{64}$',false)
$$;
CREATE FUNCTION v24_cordis.json_array_valid(p_value jsonb,p_kind text,p_max int) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_value)='array' AND jsonb_array_length(p_value)<=p_max
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_value) e WHERE NOT CASE p_kind
   WHEN 'uuid' THEN v24_cordis.json_uuid(e.value) ELSE v24_cordis.json_text(e.value) END),false)
$$;
CREATE FUNCTION v24_cordis.json_uuid_set(p_value jsonb,p_max int) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_value)='array' AND jsonb_array_length(p_value) BETWEEN 1 AND p_max
  AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_value) e WHERE NOT v24_cordis.json_uuid(e.value))
  AND (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(p_value))=jsonb_array_length(p_value),false)
$$;
CREATE FUNCTION v24_cordis.event_payload_valid(p_kind text,p_payload jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(CASE
  WHEN p_payload IS NULL OR jsonb_typeof(p_payload)<>'object' THEN false
  WHEN p_kind='install_created' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['scope_id','scope_created','fiber_id','owner_fiber_id','owner_episode_id','child_contribution_id']),false)
   AND v24_cordis.json_uuid(p_payload->'scope_id') AND jsonb_typeof(p_payload->'scope_created')='boolean' AND v24_cordis.json_uuid(p_payload->'fiber_id')
   AND (p_payload->'owner_fiber_id'='null'::jsonb OR v24_cordis.json_uuid(p_payload->'owner_fiber_id'))
   AND (p_payload->'owner_episode_id'='null'::jsonb OR v24_cordis.json_uuid(p_payload->'owner_episode_id'))
   AND (p_payload->'child_contribution_id'='null'::jsonb OR v24_cordis.json_uuid(p_payload->'child_contribution_id'))
  WHEN p_kind='fiber_target_requested' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['want_on','control_seq']),false)
   AND jsonb_typeof(p_payload->'want_on')='boolean'
   AND v24_cordis.json_int(p_payload->'control_seq',0,9223372036854775807)
  WHEN p_kind='episode_begun' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','epoch','control_seq','require_keys','pin_ids']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id') AND v24_cordis.json_int(p_payload->'epoch',1,2147483647)
   AND v24_cordis.json_int(p_payload->'control_seq',0,9223372036854775807)
   AND v24_cordis.json_array_valid(p_payload->'require_keys','text',256) AND v24_cordis.json_array_valid(p_payload->'pin_ids','uuid',256)
  WHEN p_kind='contributions_appended' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','contribution_ids','seq_from','seq_through','next_index']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id')
   AND v24_cordis.json_array_valid(p_payload->'contribution_ids','uuid',32)
   AND v24_cordis.json_int(p_payload->'seq_from',0,9223372036854775807) AND v24_cordis.json_int(p_payload->'seq_through',0,9223372036854775807)
   AND v24_cordis.json_int(p_payload->'next_index',0,2147483647)
  WHEN p_kind='episode_activated' THEN coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','epoch']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id') AND v24_cordis.json_int(p_payload->'epoch',1,2147483647)
  WHEN p_kind='episode_closing' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','epoch','control_seq','outcome','reason','failure','withdrawn_ids']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id') AND v24_cordis.json_int(p_payload->'epoch',1,2147483647)
   AND v24_cordis.json_int(p_payload->'control_seq',0,9223372036854775807)
   AND p_payload->>'outcome' IN ('divert','error','retire')
   AND p_payload->>'reason' IN ('control_drift','target_drift','dependency_lost','dispose','failure')
   AND (p_payload->'failure'='null'::jsonb OR (jsonb_typeof(p_payload->'failure')='object'
    AND v24_cordis.exact_keys(p_payload->'failure',ARRAY['v','control_seq','episode_id','phase','code','reason','key'])))
   AND v24_cordis.json_array_valid(p_payload->'withdrawn_ids','uuid',256)
  WHEN p_kind='contributions_released' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','contribution_ids','seq_from','seq_through']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id')
   AND v24_cordis.json_uuid_set(p_payload->'contribution_ids',32)
   AND v24_cordis.json_int(p_payload->'seq_from',0,9223372036854775807)
   AND v24_cordis.json_int(p_payload->'seq_through',0,9223372036854775807)
  WHEN p_kind='pins_released' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','activation_pin_ids','run_pin_ids']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id')
   AND jsonb_typeof(p_payload->'activation_pin_ids')='array'
   AND jsonb_typeof(p_payload->'run_pin_ids')='array'
   AND jsonb_array_length(p_payload->'activation_pin_ids')
     +jsonb_array_length(p_payload->'run_pin_ids') BETWEEN 1 AND 32
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'activation_pin_ids') e
    WHERE NOT v24_cordis.json_uuid(e.value))
   AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'run_pin_ids') e
    WHERE NOT v24_cordis.json_uuid(e.value))
  WHEN p_kind='episode_closed' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['episode_id','epoch','outcome','control_seq']),false)
   AND v24_cordis.json_uuid(p_payload->'episode_id')
   AND v24_cordis.json_int(p_payload->'epoch',1,2147483647)
   AND p_payload->>'outcome' IN ('divert','error','retire')
   AND v24_cordis.json_int(p_payload->'control_seq',0,9223372036854775807)
  WHEN p_kind='install_dispose_progress' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['phase','fiber_id','child_install_id','scheduled_targets']),false)
   AND p_payload->>'phase' IN ('requested','fiber_requested','fiber_disposed','work_scheduled','completed')
   AND (p_payload->'fiber_id'='null'::jsonb OR v24_cordis.json_uuid(p_payload->'fiber_id'))
   AND (p_payload->'child_install_id'='null'::jsonb OR v24_cordis.json_uuid(p_payload->'child_install_id'))
   AND (p_payload->'scheduled_targets'='null'::jsonb
    OR (jsonb_typeof(p_payload->'scheduled_targets')='array'
     AND jsonb_array_length(p_payload->'scheduled_targets')<=1
     AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_payload->'scheduled_targets') e
      WHERE NOT v24_cordis.json_uuid(e.value))))
  WHEN p_kind='run_progress' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['run_id','effect_id','effect_kind','step',
    'remaining_steps','phase','sealed','reason']),false)
   AND v24_cordis.json_uuid(p_payload->'run_id') AND v24_cordis.json_uuid(p_payload->'effect_id')
   AND p_payload->>'effect_kind' IN ('run_start','model_call','tool_call')
   AND v24_cordis.json_int(p_payload->'step',0,64)
   AND v24_cordis.json_int(p_payload->'remaining_steps',0,64)
   AND p_payload->>'phase' IN ('model','tools','sealed')
   AND jsonb_typeof(p_payload->'sealed')='boolean'
   AND (p_payload->'reason'='null'::jsonb OR p_payload->>'reason' IN ('final','budget_exhausted','model_failed'))
  WHEN p_kind='run_refused' THEN
   coalesce(v24_cordis.exact_keys(p_payload,ARRAY['run_id','effect_id','reason']),false)
   AND p_payload->'run_id'='null'::jsonb AND v24_cordis.json_uuid(p_payload->'effect_id')
   AND p_payload->>'reason' IN ('owner_closing','start_failed','replay_right_missing')
  WHEN p_kind='receipt' THEN jsonb_typeof(p_payload)='object'
  ELSE false END,false)
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
      OR (alias='service' AND p_class IN ('claim','success','failure','unknown')
       AND p_kind IN ('host_io','run_start','model_call','tool_call') AND p_action=p_class);
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
CREATE FUNCTION v24_cordis.target_refs(p_table text,p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE rowdata jsonb; result jsonb:='[]'; ref record;
BEGIN
 IF p_table<>ALL(ARRAY['scopes','runs','effects','installs','fibers','episodes','contributions','pins']) THEN
  RAISE EXCEPTION 'invalid typed target' USING ERRCODE='22023';
 END IF;
 EXECUTE format('SELECT to_jsonb(t) FROM v24_cordis.%I t WHERE id=$1',p_table) INTO rowdata USING p_id;
 IF rowdata IS NULL THEN RETURN NULL; END IF;
 IF p_table='effects' AND rowdata->>'status' IN ('succeeded','failed','unknown','cancelled') THEN
  RETURN '[]'::jsonb; END IF;
 FOR ref IN SELECT * FROM (VALUES
  ('scopes','parent_id','scopes'),
  ('runs','owner_fiber_id','fibers'),('runs','owner_episode_id','episodes'),('runs','scope_id','scopes'),('runs','parent_run_id','runs'),
  ('effects','parent_id','effects'),('effects','fiber_id','fibers'),('effects','episode_id','episodes'),('effects','run_id','runs'),
  ('installs','scope_id','scopes'),('installs','owner_fiber_id','fibers'),('installs','owner_episode_id','episodes'),
  ('fibers','install_id','installs'),('fibers','owner_id','fibers'),('fibers','owner_episode_id','episodes'),('fibers','scope_id','scopes'),('fibers','current_episode_id','episodes'),
  ('episodes','fiber_id','fibers'),
  ('contributions','fiber_id','fibers'),('contributions','episode_id','episodes'),
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
-- DP2 reserved continuation identity (plan 3.5). The child ID uses the existing effect_id_for ABI.
CREATE FUNCTION v24_cordis.successor_request_key(p_parent uuid,p_ordinal int) RETURNS text
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT 'cordis/reconcile/'||p_parent::text||'/'||p_ordinal::text
$$;
CREATE FUNCTION v24_cordis.successor_effect_id(p_actor text,p_parent uuid,p_ordinal int,
 p_kind text DEFAULT 'command_reconcile') RETURNS uuid
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT v24_cordis.effect_id_for(v24_cordis.principal_id(p_actor::name),
   v24_cordis.successor_request_key(p_parent,p_ordinal),p_kind)
$$;
CREATE FUNCTION v24_cordis.reconcile_payload_valid(p_payload jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
 SELECT coalesce(v24_cordis.exact_keys(p_payload,ARRAY['fiber_id','action','expected_control_seq'])
  AND v24_cordis.json_uuid(p_payload->'fiber_id')
  AND jsonb_typeof(p_payload->'action')='string'
  AND p_payload->>'action' IN ('on','advance','off','retry')
  AND v24_cordis.json_int(p_payload->'expected_control_seq',0,9223372036854775807),false)
$$;
CREATE FUNCTION v24_cordis.command_seed(p_kind text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE result jsonb:='[]'; item jsonb; iid uuid; fibs jsonb:='[]';
BEGIN
 IF p_kind='command_install' THEN
  RETURN v24_cordis.install_command_seed(p_payload);
 ELSIF p_kind='command_reconcile' THEN
  RETURN v24_cordis.reconcile_command_seed(p_payload);
 ELSIF p_kind='command_dispose' THEN
  RETURN v24_cordis.dispose_command_seed(p_payload);
 ELSE RETURN NULL;
 END IF;
 IF jsonb_array_length(result)>512 THEN RETURN NULL; END IF;
 RETURN (SELECT coalesce(jsonb_agg(x ORDER BY x->>'t',x->>'id'),'[]')
   FROM (SELECT DISTINCT value x FROM jsonb_array_elements(result)) s);
END $$;
CREATE FUNCTION v24_cordis.command_closure(p_kind text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE seed jsonb;
BEGIN
 seed:=v24_cordis.command_seed(p_kind,p_payload);
 IF seed IS NULL THEN RETURN NULL; END IF;
 RETURN v24_cordis.discover_closure(seed);
END $$;
CREATE FUNCTION v24_cordis.continuation_state(p_effect_id uuid,p_principal uuid,p_body jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE e v24_cordis.effects%ROWTYPE; par v24_cordis.effects%ROWTYPE; f v24_cordis.fibers%ROWTYPE;
 ep v24_cordis.episodes%ROWTYPE; k text; m text[]; pid uuid; ord int;
BEGIN
 k:=p_body->>'request_key';
 m:=regexp_match(k,'^cordis/reconcile/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/([0-9]{1,2})$');
 IF m IS NULL THEN RETURN jsonb_build_object('code','invalid_args','reason','reserved_key_shape'); END IF;
 pid:=m[1]::uuid; ord:=m[2]::int;
 IF k<>v24_cordis.successor_request_key(pid,ord) OR ord NOT BETWEEN 0 AND 15 THEN
  RETURN jsonb_build_object('code','invalid_args','reason','reserved_key_shape');
 END IF;
 SELECT * INTO e FROM v24_cordis.effects WHERE id=p_effect_id FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('code','not_found_or_denied','reason','continuation_absent'); END IF;
 IF e.kind<>'command_reconcile' OR e.status<>'ready' OR e.parent_id IS DISTINCT FROM pid
  OR e.ordinal IS DISTINCT FROM ord OR e.request_actor IS DISTINCT FROM session_user
  OR e.attempt<>0 OR e.fence<>0 OR e.outcome IS NOT NULL OR e.settled_at IS NOT NULL
  OR e.claim_owner IS NOT NULL OR e.lease_until IS NOT NULL OR e.input IS DISTINCT FROM p_body->'payload'
  OR p_principal IS DISTINCT FROM v24_cordis.principal_id(e.request_actor) THEN
  RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_identity');
 END IF;
 SELECT * INTO par FROM v24_cordis.effects WHERE id=pid;
 IF NOT FOUND OR par.status<>'succeeded' OR par.request_actor IS DISTINCT FROM e.request_actor THEN
  RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_parent');
 END IF;
 IF par.kind='command_reconcile' THEN
  IF par.fiber_id IS DISTINCT FROM e.fiber_id THEN
   RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_parent'); END IF;
 ELSIF par.kind='command_dispose' THEN
  -- A dispose parent may only have its own ordinal-0 successor, inside its sealed
  -- owner subtree, and the parent receipt must name this exact effect.
  IF ord<>0 OR NOT v24_cordis.json_uuid(par.input->'install_id')
   OR NOT v24_cordis.fiber_in_install_subtree(e.fiber_id,(par.input->>'install_id')::uuid)
   OR NOT EXISTS(SELECT 1 FROM v24_cordis.installs WHERE id=(par.input->>'install_id')::uuid
     AND state IN ('dispose_pending','disposed'))
   OR NOT EXISTS(SELECT 1 FROM v24_cordis.requests rq WHERE rq.effect_id=pid
     AND rq.response->'emitted' @> jsonb_build_array(e.id::text)) THEN
   RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_parent'); END IF;
 ELSE
  RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_parent');
 END IF;
 SELECT * INTO f FROM v24_cordis.fibers WHERE id=e.fiber_id;
 IF NOT FOUND OR e.input->>'fiber_id' IS DISTINCT FROM f.id::text THEN
  RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_binding');
 END IF;
 IF e.episode_id IS NULL THEN
  IF f.current_episode_id IS NOT NULL THEN RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_binding'); END IF;
 ELSE
  SELECT * INTO ep FROM v24_cordis.episodes WHERE id=e.episode_id AND fiber_id=f.id;
  IF NOT FOUND OR ep.closed_at IS NOT NULL OR f.current_episode_id IS DISTINCT FROM ep.id THEN
   RETURN jsonb_build_object('code','effect_id_conflict','reason','continuation_binding'); END IF;
 END IF;
 -- Identity stayed above. control_seq, want_on and legal active/closing are not identity failures.
 IF (e.input->>'expected_control_seq')::bigint<>f.control_seq THEN
  RETURN jsonb_build_object('class','control','reason','generation');
 END IF;
 IF NOT f.want_on THEN
  RETURN jsonb_build_object('class','control','reason','target');
 END IF;
 IF f.current_episode_id IS NULL THEN
  IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
   RETURN jsonb_build_object('class','control','reason','phase'); END IF;
 ELSIF ep.state<>'reloading' THEN
  RETURN jsonb_build_object('class','control','reason','phase');
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.command_control(p_kind text,p_barrier jsonb,p_delta jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE disposition text;
BEGIN
 IF p_barrier IS NULL THEN
  RETURN jsonb_build_object('kind','ready','step',to_jsonb(p_kind),'barrier','null'::jsonb,'context',p_delta);
 END IF;
 IF NOT coalesce(v24_cordis.exact_keys(p_barrier,ARRAY['disposition']),false)
  OR p_barrier->>'disposition' NOT IN ('deferred','blocked_unknown','unsupported') THEN
  RAISE EXCEPTION 'command barrier result' USING ERRCODE='0A000';
 END IF;
 disposition:=p_barrier->>'disposition';
 RETURN jsonb_build_object('kind',disposition,'step','null'::jsonb,'barrier',p_barrier,'context','null'::jsonb);
END $$;
CREATE FUNCTION v24_cordis.interpret_command(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE kind text; payload jsonb; delta jsonb; barrier jsonb;
BEGIN
 kind:=p_outcome->'body'->>'kind'; payload:=p_outcome->'body'->'payload';
 IF kind='command_reconcile' THEN
  IF NOT coalesce(v24_cordis.reconcile_payload_valid(payload),false) THEN
   RETURN v24_cordis.error_v1('invalid_args',jsonb_build_object('reason','reconcile_payload'));
  END IF;
  delta:=v24_cordis.interpret_reconcile(p_effect_id,p_principal,p_outcome,p_closure);
 ELSIF kind='command_install' THEN
  delta:=v24_cordis.interpret_install(p_effect_id,p_principal,p_outcome,p_closure);
 ELSIF kind='command_dispose' THEN
  IF NOT coalesce(v24_cordis.exact_keys(payload,ARRAY['install_id']) AND v24_cordis.json_uuid(payload->'install_id'),false) THEN
   RETURN v24_cordis.error_v1('invalid_args',jsonb_build_object('reason','dispose_payload'));
  END IF;
  delta:=v24_cordis.interpret_dispose(p_effect_id,p_principal,p_outcome,p_closure);
 ELSE
  RETURN v24_cordis.error_v1('invalid_args',jsonb_build_object('reason','command_body'));
 END IF;
 IF delta IS NULL OR jsonb_typeof(delta)<>'object' OR delta ? 'error' THEN RETURN delta; END IF;
 barrier:=v24_cordis.command_barrier(p_effect_id,p_outcome,p_closure);
 RETURN v24_cordis.command_control(kind,barrier,delta);
END $$;
CREATE FUNCTION v24_cordis.interpret_settlement(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_closure jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE k text;
BEGIN
 SELECT kind INTO k FROM v24_cordis.effects WHERE id=p_effect_id;
 IF k IN ('run_start','model_call','tool_call') THEN
  RETURN v24_cordis.run_delta(p_effect_id,p_outcome);
 END IF;
 RAISE EXCEPTION 'DP1 lifecycle settlement is not implemented' USING ERRCODE='0A000';
END $$;
CREATE FUNCTION v24_cordis.validate_delta(p_delta jsonb,p_class text,p_structure_only boolean DEFAULT false,
 p_kind text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE item jsonb; sub jsonb; op text; ordinal int; ordinals int[]:=ARRAY[]::int[]; status text;
 n_scope int:=0; n_install int:=0; n_fiber int:=0; n_begin int:=0; n_service int:=0; n_child int:=0;
 n_progress int:=0; n_control int:=0; n_activate int:=0; n_dispose int:=0; n_retire int:=0;
 n_close_start int:=0; n_withdraw int:=0; n_inverse int:=0; n_pin_release int:=0; n_close_ep int:=0;
 i int;
BEGIN
 IF NOT coalesce(v24_cordis.exact_keys(p_delta,ARRAY['domain','receipt','events','successors']),false)
  OR jsonb_typeof(p_delta->'domain')<>'array' OR jsonb_typeof(p_delta->'events')<>'array'
  OR jsonb_typeof(p_delta->'successors')<>'array' OR NOT coalesce(v24_cordis.exact_keys(p_delta->'receipt',ARRAY['status']),false) THEN
  RETURN v24_cordis.error_v1('invalid_outcome');
 END IF;
 status:=CASE p_class WHEN 'command' THEN 'succeeded' WHEN 'success' THEN 'succeeded' WHEN 'failure' THEN 'failed' WHEN 'unknown' THEN 'unknown' END;
 IF status IS NULL OR p_delta->'receipt'->>'status' IS DISTINCT FROM status
  OR jsonb_array_length(p_delta->'events')>1 OR jsonb_array_length(p_delta->'successors')>16
  OR jsonb_array_length(p_delta->'domain')>512 THEN
  RETURN v24_cordis.error_v1('invalid_outcome');
 END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'events') LOOP
  IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['entity_type','entity_id','event_kind','payload']),false)
   OR jsonb_typeof(item->'entity_type')<>'string' OR jsonb_typeof(item->'event_kind')<>'string'
   OR NOT v24_cordis.json_uuid(item->'entity_id') OR NOT v24_cordis.event_payload_valid(item->>'event_kind',item->'payload') THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'successors') LOOP
  IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['ordinal','kind','input']),false)
   OR NOT v24_cordis.json_int(item->'ordinal',0,15) OR jsonb_typeof(item->'kind')<>'string'
   OR jsonb_typeof(item->'input')<>'object'
   OR item->>'kind'<>ALL(ARRAY['dispatch','listener_call','model_call','tool_call','run_start','host_io','command_reconcile']) THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
  ordinal:=(item->>'ordinal')::int;
  IF ordinal=ANY(ordinals) THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  ordinals:=array_append(ordinals,ordinal);
  IF item->>'kind'='command_reconcile' THEN
   IF ordinal<>0 OR NOT coalesce(v24_cordis.exact_keys(item->'input',ARRAY['fiber_id','action','expected_control_seq']),false)
    OR NOT v24_cordis.json_uuid(item->'input'->'fiber_id')
    OR item->'input'->>'action' IS DISTINCT FROM 'advance'
    OR NOT v24_cordis.json_int(item->'input'->'expected_control_seq',0,9223372036854775807) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF item->>'kind'='run_start' THEN
   IF ordinal<>0 OR NOT coalesce(v24_cordis.exact_keys(item->'input',ARRAY['v','fiber_id','episode_id','contract']),false)
    OR item->'input'->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(item->'input'->'fiber_id')
    OR NOT v24_cordis.json_uuid(item->'input'->'episode_id')
    OR NOT coalesce(v24_cordis.exact_keys(item->'input'->'contract',ARRAY['contract_version','handler_digest']),false)
    OR NOT v24_cordis.json_text(item->'input'->'contract'->'contract_version')
    OR NOT v24_cordis.json_hex64(item->'input'->'contract'->'handler_digest') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF item->>'kind'='model_call' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item->'input',ARRAY['v','run_id','pin_id','key','digests','contract']),false)
    OR item->'input'->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(item->'input'->'run_id')
    OR NOT v24_cordis.json_uuid(item->'input'->'pin_id') OR NOT v24_cordis.json_text(item->'input'->'key')
    OR NOT coalesce(v24_cordis.exact_keys(item->'input'->'digests',ARRAY['policy','schema','toolset']),false)
    OR NOT v24_cordis.json_hex64(item->'input'->'digests'->'policy')
    OR NOT v24_cordis.json_hex64(item->'input'->'digests'->'schema')
    OR NOT v24_cordis.json_hex64(item->'input'->'digests'->'toolset')
    OR NOT coalesce(v24_cordis.exact_keys(item->'input'->'contract',ARRAY['contract_version','handler_digest']),false)
    OR NOT v24_cordis.json_text(item->'input'->'contract'->'contract_version')
    OR NOT v24_cordis.json_hex64(item->'input'->'contract'->'handler_digest') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF item->>'kind'='tool_call' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item->'input',ARRAY['v','run_id','pin_id','key',
     'descriptor_digest','call_id','args','contract']),false)
    OR item->'input'->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(item->'input'->'run_id')
    OR NOT v24_cordis.json_uuid(item->'input'->'pin_id') OR NOT v24_cordis.json_text(item->'input'->'key')
    OR NOT v24_cordis.json_hex64(item->'input'->'descriptor_digest')
    OR NOT v24_cordis.json_text(item->'input'->'call_id')
    OR jsonb_typeof(item->'input'->'args')<>'object'
    OR NOT coalesce(v24_cordis.exact_keys(item->'input'->'contract',ARRAY['contract_version','handler_digest']),false)
    OR NOT v24_cordis.json_text(item->'input'->'contract'->'contract_version')
    OR NOT v24_cordis.json_hex64(item->'input'->'contract'->'handler_digest') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  END IF;
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') LOOP
  IF jsonb_typeof(item)<>'object' OR jsonb_typeof(item->'op')<>'string' THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
  op:=item->>'op';
  IF op='scope_create' THEN
   n_scope:=n_scope+1;
   IF n_scope>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','id','parent_id','realm_overrides']),false)
    OR NOT v24_cordis.json_uuid(item->'id')
    OR NOT (item->'parent_id'='null'::jsonb OR v24_cordis.json_uuid(item->'parent_id'))
    OR jsonb_typeof(item->'realm_overrides')<>'object' THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   IF EXISTS(SELECT 1 FROM jsonb_each(item->'realm_overrides') e
     WHERE jsonb_typeof(e.value)<>'string' OR length(e.value#>>'{}') NOT BETWEEN 1 AND 128) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='install_create' THEN
   n_install:=n_install+1;
   IF n_install>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','id','scope_id','owner_fiber_id',
     'owner_episode_id','identity','version','manifest','artifact_digest','contracts','policy_ref','overlay']),false)
    OR NOT v24_cordis.json_uuid(item->'id') OR NOT v24_cordis.json_uuid(item->'scope_id')
    OR NOT ((item->'owner_fiber_id'='null'::jsonb AND item->'owner_episode_id'='null'::jsonb)
         OR (v24_cordis.json_uuid(item->'owner_fiber_id') AND v24_cordis.json_uuid(item->'owner_episode_id')))
    OR NOT v24_cordis.json_text(item->'identity') OR NOT v24_cordis.json_text(item->'version')
    OR jsonb_typeof(item->'manifest')<>'object' OR NOT v24_cordis.json_hex64(item->'artifact_digest')
    OR jsonb_typeof(item->'contracts')<>'object' OR jsonb_typeof(item->'overlay')<>'object'
    OR item->'overlay'<>'{}'::jsonb
    OR NOT (item->'policy_ref'='null'::jsonb
         OR (jsonb_typeof(item->'policy_ref')='string' AND length(item->'policy_ref'#>>'{}') BETWEEN 1 AND 128)) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='fiber_create' THEN
   n_fiber:=n_fiber+1;
   IF n_fiber>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','id','install_id','owner_id',
     'owner_episode_id','scope_id']),false)
    OR NOT v24_cordis.json_uuid(item->'id') OR NOT v24_cordis.json_uuid(item->'install_id')
    OR NOT v24_cordis.json_uuid(item->'scope_id')
    OR NOT ((item->'owner_id'='null'::jsonb AND item->'owner_episode_id'='null'::jsonb)
         OR (v24_cordis.json_uuid(item->'owner_id') AND v24_cordis.json_uuid(item->'owner_episode_id'))) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='fiber_control' THEN
   n_control:=n_control+1;
   IF n_control>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','want_on','control_seq']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR jsonb_typeof(item->'want_on')<>'boolean'
    OR NOT v24_cordis.json_int(item->'control_seq',0,9223372036854775807) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='episode_begin' THEN
   n_begin:=n_begin+1;
   IF n_begin>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','id','fiber_id','epoch',
     'committed_view','iterator','pins']),false)
    OR NOT v24_cordis.json_uuid(item->'id') OR NOT v24_cordis.json_uuid(item->'fiber_id')
    OR NOT v24_cordis.json_int(item->'epoch',1,2147483647)
    OR jsonb_typeof(item->'committed_view')<>'object' OR jsonb_typeof(item->'iterator')<>'object'
    OR jsonb_typeof(item->'pins')<>'array' OR jsonb_array_length(item->'pins')>256 THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   IF NOT coalesce(v24_cordis.exact_keys(item->'iterator',ARRAY['v','next_index','registered_through','control_seq']),false)
    OR item->'iterator'->'v' IS DISTINCT FROM '1'::jsonb
    OR NOT v24_cordis.json_int(item->'iterator'->'next_index',0,2147483647)
    OR NOT v24_cordis.json_int(item->'iterator'->'registered_through',-1,2147483647)
    OR NOT v24_cordis.json_int(item->'iterator'->'control_seq',0,9223372036854775807) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   IF EXISTS(SELECT 1 FROM jsonb_each(item->'committed_view') e WHERE
     NOT coalesce(v24_cordis.exact_keys(e.value,ARRAY['contribution_id','provider_fiber_id',
       'provider_episode_id','provider_epoch','descriptor_digest','contract_version']),false)
     OR NOT v24_cordis.json_uuid(e.value->'contribution_id')
     OR NOT v24_cordis.json_uuid(e.value->'provider_fiber_id')
     OR NOT v24_cordis.json_uuid(e.value->'provider_episode_id')
     OR NOT v24_cordis.json_int(e.value->'provider_epoch',0,2147483647)
     OR NOT v24_cordis.json_hex64(e.value->'descriptor_digest')
     OR NOT v24_cordis.json_text(e.value->'contract_version')
     OR length(e.key) NOT BETWEEN 1 AND 128) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   FOR i IN 0..jsonb_array_length(item->'pins')-1 LOOP
    sub:=item->'pins'->i;
    IF NOT coalesce(v24_cordis.exact_keys(sub,ARRAY['id','key','contribution_id',
      'provider_episode_id','provider_epoch']),false)
     OR NOT v24_cordis.json_uuid(sub->'id') OR NOT v24_cordis.json_text(sub->'key')
     OR NOT v24_cordis.json_uuid(sub->'contribution_id')
     OR NOT v24_cordis.json_uuid(sub->'provider_episode_id')
     OR NOT v24_cordis.json_int(sub->'provider_epoch',0,2147483647)
     OR NOT (item->'committed_view' ? (sub->>'key'))
     OR EXISTS(SELECT 1 FROM jsonb_array_elements(item->'pins') p
       WHERE p->>'key'=sub->>'key' AND p<>sub) THEN
     RETURN v24_cordis.error_v1('invalid_outcome');
    END IF;
   END LOOP;
   IF (SELECT count(*) FROM jsonb_object_keys(item->'committed_view'))
      <> jsonb_array_length(item->'pins') THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  ELSIF op='contribution_append' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','id','fiber_id','episode_id','seq','kind',
     'realm','key','descriptor','prev_contribution_id','inverse','contract_version']),false)
    OR NOT v24_cordis.json_uuid(item->'id') OR NOT v24_cordis.json_uuid(item->'fiber_id')
    OR NOT v24_cordis.json_uuid(item->'episode_id') OR NOT v24_cordis.json_int(item->'seq',0,2147483647)
    OR jsonb_typeof(item->'kind')<>'string' OR item->>'kind' NOT IN ('service','child')
    OR jsonb_typeof(item->'descriptor')<>'object'
    OR NOT (item->'prev_contribution_id'='null'::jsonb OR v24_cordis.json_uuid(item->'prev_contribution_id'))
    OR jsonb_typeof(item->'inverse')<>'object' OR NOT v24_cordis.json_text(item->'contract_version') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   IF (SELECT count(*) FROM jsonb_array_elements(p_delta->'domain') d
     WHERE d->>'op'='contribution_append' AND d->>'id'=item->>'id')<>1 THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   IF item->>'kind'='service' THEN
    n_service:=n_service+1;
    IF n_service>32 OR NOT v24_cordis.json_text(item->'realm') OR NOT v24_cordis.json_text(item->'key')
     OR item->'prev_contribution_id'<>'null'::jsonb
     OR NOT coalesce(v24_cordis.exact_keys(item->'inverse',ARRAY['op']),false)
     OR item->'inverse'->>'op' IS DISTINCT FROM 'delete_row' THEN
     RETURN v24_cordis.error_v1('invalid_outcome');
    END IF;
   ELSE
    n_child:=n_child+1;
    IF n_child>1 OR item->'realm'<>'null'::jsonb OR item->'key'<>'null'::jsonb
     OR item->'prev_contribution_id'<>'null'::jsonb
     OR NOT coalesce(v24_cordis.exact_keys(item->'inverse',ARRAY['op']),false)
     OR item->'inverse'->>'op' IS DISTINCT FROM 'dispose_child'
     OR NOT coalesce(v24_cordis.exact_keys(item->'descriptor',ARRAY['child_fiber_id']),false)
     OR NOT v24_cordis.json_uuid(item->'descriptor'->'child_fiber_id') THEN
     RETURN v24_cordis.error_v1('invalid_outcome');
    END IF;
   END IF;
  ELSIF op='fiber_retire' THEN
   n_retire:=n_retire+1;
   IF n_retire>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','episode_id']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR NOT v24_cordis.json_uuid(item->'episode_id') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='episode_close_start' THEN
   n_close_start:=n_close_start+1;
   IF n_close_start>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','episode_id','outcome','failure']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR NOT v24_cordis.json_uuid(item->'episode_id')
    OR NOT v24_cordis.json_text(item->'outcome') OR item->>'outcome' NOT IN ('divert','error','retire')
    OR (item->>'outcome'='error' AND NOT v24_cordis.failure_v1_valid(item->'failure'))
    OR (item->>'outcome'<>'error' AND item->'failure'<>'null'::jsonb) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='contributions_withdraw' THEN
   n_withdraw:=n_withdraw+1;
   IF n_withdraw>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','episode_id','contribution_ids']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR NOT v24_cordis.json_uuid(item->'episode_id')
    OR NOT v24_cordis.json_array_valid(item->'contribution_ids','uuid',256)
    OR jsonb_array_length(item->'contribution_ids')=0 THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='contribution_inverse' THEN
   n_inverse:=n_inverse+1;
   IF n_inverse>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','episode_id','contribution_ids']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR NOT v24_cordis.json_uuid(item->'episode_id')
    OR NOT coalesce(v24_cordis.json_uuid_set(item->'contribution_ids',32),false) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='pins_release' THEN
   n_pin_release:=n_pin_release+1;
   IF n_pin_release>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','episode_id','pin_ids']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR NOT v24_cordis.json_uuid(item->'episode_id')
    OR NOT coalesce(v24_cordis.json_uuid_set(item->'pin_ids',32),false) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='episode_close' THEN
   n_close_ep:=n_close_ep+1;
   IF n_close_ep>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','fiber_id','episode_id']),false)
    OR NOT v24_cordis.json_uuid(item->'fiber_id') OR NOT v24_cordis.json_uuid(item->'episode_id') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='episode_progress' THEN
   n_progress:=n_progress+1;
   IF n_progress>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','episode_id','next_index','registered_through']),false)
    OR NOT v24_cordis.json_uuid(item->'episode_id')
    OR NOT v24_cordis.json_int(item->'next_index',0,2147483647)
    OR NOT v24_cordis.json_int(item->'registered_through',-1,2147483647) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='episode_activate' THEN
   n_activate:=n_activate+1;
   IF n_activate>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','episode_id']),false)
    OR NOT v24_cordis.json_uuid(item->'episode_id') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='run_create' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','id','owner_fiber_id','owner_episode_id',
     'scope_id','state','remaining_steps']),false)
    OR NOT v24_cordis.json_uuid(item->'id') OR NOT v24_cordis.json_uuid(item->'owner_fiber_id')
    OR NOT v24_cordis.json_uuid(item->'owner_episode_id') OR NOT v24_cordis.json_uuid(item->'scope_id')
    OR NOT v24_cordis.run_state_valid(item->'state')
    OR NOT v24_cordis.json_int(item->'remaining_steps',1,64) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='run_pin_bind' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','run_id','pins']),false)
    OR NOT v24_cordis.json_uuid(item->'run_id') OR jsonb_typeof(item->'pins')<>'array'
    OR jsonb_array_length(item->'pins') NOT BETWEEN 1 AND 32
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(item->'pins') p
     WHERE NOT coalesce(v24_cordis.exact_keys(p,ARRAY['id','key','contribution_id',
      'provider_episode_id','provider_epoch']),false)
      OR NOT v24_cordis.json_uuid(p->'id') OR NOT v24_cordis.json_text(p->'key')
      OR NOT v24_cordis.json_uuid(p->'contribution_id')
      OR NOT v24_cordis.json_uuid(p->'provider_episode_id')
      OR NOT v24_cordis.json_int(p->'provider_epoch',0,2147483647)) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='run_state' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','run_id','state']),false)
    OR NOT v24_cordis.json_uuid(item->'run_id') OR NOT v24_cordis.run_state_valid(item->'state') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='run_budget' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','run_id','remaining_steps']),false)
    OR NOT v24_cordis.json_uuid(item->'run_id')
    OR NOT v24_cordis.json_int(item->'remaining_steps',0,64) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='run_seal' THEN
   IF NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','run_id','effect_id','result']),false)
    OR NOT v24_cordis.json_uuid(item->'run_id') OR NOT v24_cordis.json_uuid(item->'effect_id')
    OR NOT coalesce(v24_cordis.exact_keys(item->'result',ARRAY['v','reason','output','dropped_tool_calls']),false)
    OR item->'result'->'v'<>'1'::jsonb
    OR item->'result'->>'reason' NOT IN ('final','budget_exhausted','model_failed')
    OR jsonb_typeof(item->'result'->'output')<>'object'
    OR NOT v24_cordis.json_int(item->'result'->'dropped_tool_calls',0,16) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='install_dispose_request' THEN
   n_dispose:=n_dispose+1;
   IF n_dispose>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','install_id']),false)
    OR NOT v24_cordis.json_uuid(item->'install_id') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='fiber_dispose_request' THEN
   n_dispose:=n_dispose+1;
   IF n_dispose>1 OR NOT coalesce(v24_cordis.exact_keys(item,
     ARRAY['op','install_id','fiber_id','want_on','control_seq']),false)
    OR NOT v24_cordis.json_uuid(item->'install_id') OR NOT v24_cordis.json_uuid(item->'fiber_id')
    OR item->'want_on' IS DISTINCT FROM 'false'::jsonb
    OR NOT v24_cordis.json_int(item->'control_seq',0,9223372036854775807) THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='fiber_dispose_finish' THEN
   n_dispose:=n_dispose+1;
   IF n_dispose>1 OR NOT coalesce(v24_cordis.exact_keys(item,
     ARRAY['op','install_id','fiber_id']),false)
    OR NOT v24_cordis.json_uuid(item->'install_id') OR NOT v24_cordis.json_uuid(item->'fiber_id') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSIF op='install_dispose_finish' THEN
   n_dispose:=n_dispose+1;
   IF n_dispose>1 OR NOT coalesce(v24_cordis.exact_keys(item,ARRAY['op','install_id']),false)
    OR NOT v24_cordis.json_uuid(item->'install_id') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
  ELSE
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
 END LOOP;
 IF n_service>0 AND n_child>0 THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 IF NOT p_structure_only AND p_class<>'command'
  AND coalesce(p_kind,'') NOT IN ('run_start','model_call','tool_call')
  AND (p_delta->'domain'<>'[]'::jsonb OR p_delta->'successors'<>'[]'::jsonb) THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','settlement_has_no_domain'));
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.validate_domain(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_delta jsonb,p_closure jsonb,p_address_conflict text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE v_kind text; v_payload jsonb; v_action text; v_branch text; v_domain jsonb:=p_delta->'domain'; v_req_key text; v_dag jsonb; v_dag_ids uuid[];
 v_fiber uuid; f v24_cordis.fibers%ROWTYPE; ep v24_cordis.episodes%ROWTYPE; inst v24_cordis.installs%ROWTYPE; v_item jsonb; v_op text; v_allowed text[]; v_i int; v_n int; v_seq bigint; v_old_next int; v_old_reg int;
 v_provides jsonb; v_requires jsonb; v_prov jsonb; v_scope jsonb; v_install jsonb; v_fiberc jsonb; v_begin jsonb; v_control jsonb; v_activate jsonb;
 v_plan jsonb; v_progress jsonb; v_retire jsonb; v_close_start jsonb; v_withdraw jsonb; v_ev jsonb; v_pin jsonb; v_bind jsonb; v_scope_id uuid; v_install_id uuid; v_fiber_id uuid; v_episode_id uuid; v_epoch int; v_count int;
 v_contrib_ids jsonb:='[]'; v_pin_ids jsonb:='[]'; v_require_keys jsonb:='[]'; v_first bigint; v_last bigint; v_ctl bigint; v_maxbig bigint;
 v_prov_epoch int; v_prov_fiber uuid; v_prov_ep uuid; v_prov_cv text; v_prov_digest text; v_expected jsonb;
 v_resolved record;
BEGIN
 IF p_principal IS DISTINCT FROM v24_cordis.principal_id(session_user) THEN
  RETURN v24_cordis.error_v1('unauthorized');
 END IF;
 IF NOT v24_cordis.delta_write_closure_ok(p_delta,p_closure) THEN
  RETURN v24_cordis.error_v1('retry_with_closure',jsonb_build_object('reason','write_target'));
 END IF;
 FOR v_item IN SELECT value FROM jsonb_array_elements(p_delta->'successors') LOOP
  IF v_item->>'kind'='command_reconcile' THEN
   IF v_item->>'ordinal'<>'0'
    OR NOT coalesce(v24_cordis.exact_keys(v_item->'input',ARRAY['fiber_id','action','expected_control_seq']),false)
    OR v_item->'input'->>'action' IS DISTINCT FROM 'advance' OR NOT v24_cordis.json_uuid(v_item->'input'->'fiber_id')
    OR NOT v24_cordis.json_int(v_item->'input'->'expected_control_seq',0,9223372036854775807) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','successor_kind'));
   END IF;
  ELSIF v_item->>'kind'='run_start' THEN
   IF v_item->>'ordinal'<>'0'
    OR NOT coalesce(v24_cordis.exact_keys(v_item->'input',ARRAY['v','fiber_id','episode_id','contract']),false)
    OR v_item->'input'->'v'<>'1'::jsonb OR NOT v24_cordis.json_uuid(v_item->'input'->'fiber_id')
    OR NOT v24_cordis.json_uuid(v_item->'input'->'episode_id')
    OR NOT coalesce(v24_cordis.exact_keys(v_item->'input'->'contract',
      ARRAY['contract_version','handler_digest']),false)
    OR NOT v24_cordis.json_text(v_item->'input'->'contract'->'contract_version')
    OR NOT v24_cordis.json_hex64(v_item->'input'->'contract'->'handler_digest') THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','successor_kind'));
   END IF;
  ELSE
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','successor_kind'));
  END IF;
 END LOOP;
 v_kind:=p_outcome->'body'->>'kind'; v_payload:=p_outcome->'body'->'payload';
 IF v_kind='command_install' THEN
  v_branch:='install';
 ELSIF v_kind='command_dispose' THEN
  v_branch:='dispose';
  IF NOT coalesce(v24_cordis.exact_keys(v_payload,ARRAY['install_id']),false) OR NOT v24_cordis.json_uuid(v_payload->'install_id') THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  SELECT * INTO inst FROM v24_cordis.installs WHERE id=(v_payload->>'install_id')::uuid;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
 ELSIF v_kind='command_reconcile' THEN
  IF NOT coalesce(v24_cordis.reconcile_payload_valid(v_payload),false) THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  v_action:=v_payload->>'action';
  v_fiber:=(v_payload->>'fiber_id')::uuid;
  SELECT * INTO f FROM v24_cordis.fibers WHERE id=v_fiber;
  IF NOT FOUND THEN RETURN v24_cordis.error_v1('invalid_outcome'); END IF;
  SELECT value INTO v_close_start FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='episode_close_start' LIMIT 1;
  SELECT value INTO v_withdraw FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='contributions_withdraw' LIMIT 1;
  v_expected:=v24_cordis.reconcile_branch(v_fiber,v_action,(v_payload->>'expected_control_seq')::bigint);
  IF p_address_conflict IS NOT NULL THEN
   SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
   IF v_action<>'advance' OR v_expected->>'kind'<>'p2' OR NOT EXISTS(
    SELECT 1 FROM v24_cordis.installs i CROSS JOIN LATERAL jsonb_array_elements(i.manifest->'provides')
     WITH ORDINALITY q(value,ord) WHERE i.id=f.install_id AND q.value->>'key'=p_address_conflict
     AND q.ord BETWEEN (ep.iterator->>'next_index')::int+1 AND (ep.iterator->>'next_index')::int+32) THEN
    RAISE EXCEPTION 'invalid after-write conflict evidence' USING ERRCODE='23514';
   END IF;
   v_expected:=v24_cordis.branch_raise(ep,'p2','provide_conflict','address_conflict',p_address_conflict,
    f.retire_started_at IS NULL);
  END IF;
  IF v_expected->>'kind' IN ('error') THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','selector_rejected'));
  END IF;
  IF v_expected->>'kind' IN ('divert','raise','leave') THEN
   v_branch:='teardown';
  ELSIF v_expected->>'kind' IN ('active_noop','idle_noop') THEN
   v_branch:='noop';
  ELSIF v_expected->>'kind'='p0' THEN
   v_branch:='p0';
  ELSIF v_expected->>'kind'='p1' THEN
   v_branch:='p1';
  ELSIF v_expected->>'kind'='p2' THEN
   v_branch:='p2';
  ELSIF v_expected->>'kind'='p4' THEN
   v_branch:='p4';
  ELSIF v_expected->>'kind'='p6' THEN
   v_branch:='p6';
  END IF;
  IF v_branch IN ('teardown','noop','p6') THEN
   NULL;
  ELSIF v_branch='p1' THEN
   IF EXISTS(SELECT 1 FROM v24_cordis.episodes WHERE fiber_id=f.id AND closed_at IS NULL) THEN
    RAISE EXCEPTION 'continuation phase drift' USING ERRCODE='0A000';
   END IF;
  ELSIF v_branch IN ('p2','p4') THEN
   SELECT * INTO ep FROM v24_cordis.episodes WHERE id=f.current_episode_id AND fiber_id=f.id;
   IF NOT FOUND OR ep.closed_at IS NOT NULL OR ep.state<>'reloading' THEN
    RAISE EXCEPTION 'continuation phase drift' USING ERRCODE='0A000';
   END IF;
   SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
   IF NOT FOUND OR jsonb_typeof(inst.manifest->'provides')<>'array' THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   v_provides:=inst.manifest->'provides';
   v_old_next:=(ep.iterator->>'next_index')::int;
  END IF;
 ELSE
  RETURN v24_cordis.error_v1('invalid_outcome');
 END IF;
 IF v_branch<>'p4' AND EXISTS(SELECT 1 FROM jsonb_array_elements(p_delta->'successors') x
  WHERE x->>'kind'<>'command_reconcile') THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','successor_kind'));
 END IF;
 IF v_branch IS NULL THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','branch_missing'));
 END IF;
 v_allowed:=CASE v_branch
  WHEN 'install' THEN ARRAY['scope_create','install_create','fiber_create','contribution_append','episode_progress']
  WHEN 'p0' THEN ARRAY['fiber_control','fiber_retire']
  WHEN 'p1' THEN ARRAY['episode_begin']
  WHEN 'p2' THEN ARRAY['contribution_append','episode_progress']
  WHEN 'p4' THEN ARRAY['episode_activate']
  WHEN 'dispose' THEN ARRAY['install_dispose_request','fiber_dispose_request',
   'fiber_dispose_finish','install_dispose_finish']
  WHEN 'teardown' THEN ARRAY['fiber_retire','episode_close_start','contributions_withdraw']
  WHEN 'p6' THEN ARRAY['contribution_inverse','pins_release','episode_close']
  ELSE ARRAY[]::text[] END;
 FOR v_item IN SELECT value FROM jsonb_array_elements(v_domain) LOOP
  IF NOT (v_item->>'op'=ANY(v_allowed)) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','branch_write_set'));
  END IF;
 END LOOP;
 SELECT value INTO v_scope FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='scope_create' LIMIT 1;
 SELECT value INTO v_install FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='install_create' LIMIT 1;
 SELECT value INTO v_fiberc FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='fiber_create' LIMIT 1;
 SELECT value INTO v_begin FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='episode_begin' LIMIT 1;
 SELECT value INTO v_control FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='fiber_control' LIMIT 1;
 SELECT value INTO v_activate FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='episode_activate' LIMIT 1;
 SELECT value INTO v_progress FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='episode_progress' LIMIT 1;
 SELECT value INTO v_retire FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='fiber_retire' LIMIT 1;
 SELECT value INTO v_close_start FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='episode_close_start' LIMIT 1;
 SELECT value INTO v_withdraw FROM jsonb_array_elements(v_domain) x WHERE x.value->>'op'='contributions_withdraw' LIMIT 1;
 -- Event contract: a domain change has exactly one event. A successor-only dispose schedule
 -- has exactly one work_scheduled event. Other no-op/schedule/replay states have none.
 IF jsonb_array_length(v_domain)>0 AND jsonb_array_length(p_delta->'events')=0 THEN
  RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_cardinality'));
 END IF;
 IF jsonb_array_length(v_domain)=0 AND jsonb_array_length(p_delta->'events')>0 THEN
  IF v_branch<>'dispose' OR p_delta->'events'->0->>'event_kind' IS DISTINCT FROM 'install_dispose_progress'
   OR p_delta->'events'->0->'payload'->>'phase' IS DISTINCT FROM 'work_scheduled'
   OR jsonb_array_length(p_delta->'successors')<>1 THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_cardinality'));
  END IF;
 END IF;
 v_ev:=p_delta->'events'->0;
 IF v_branch='install' THEN
  RETURN v24_cordis.validate_install_domain(p_outcome,p_delta,p_closure);
 ELSIF v_branch='teardown' THEN
  IF p_delta IS DISTINCT FROM v24_cordis.closing_delta(f.id,v_expected) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','teardown_diagnosis'));
  END IF;
  RETURN NULL;
 ELSIF v_branch='p0' THEN
  IF p_delta IS DISTINCT FROM v24_cordis.p0_delta(f.id,v_expected) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p0_diagnosis'));
  END IF;
  RETURN NULL;
 ELSIF v_branch='noop' THEN
  IF p_delta IS DISTINCT FROM v24_cordis.empty_success() THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','active_noop'));
  END IF;
  RETURN NULL;
 ELSIF v_branch='p1' THEN
  IF f.want_on IS NOT TRUE THEN RAISE EXCEPTION 'continuation target drift' USING ERRCODE='0A000'; END IF;
  IF v_begin IS NULL OR (v_begin->>'fiber_id')::uuid<>f.id THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_context'));
  END IF;
  SELECT coalesce(max(epoch),0)::bigint+1 INTO v_maxbig FROM v24_cordis.episodes WHERE fiber_id=f.id;
  IF v_maxbig>2147483647 THEN RETURN v24_cordis.error_v1('budget_exceeded'); END IF;
  v_epoch:=(v_begin->>'epoch')::int;
  IF v_epoch<>v_maxbig THEN RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_epoch')); END IF;
  IF v_begin->'iterator'->'next_index' IS DISTINCT FROM '0'::jsonb
   OR v_begin->'iterator'->'registered_through' IS DISTINCT FROM '-1'::jsonb
   OR (v_begin->'iterator'->>'control_seq')::bigint<>f.control_seq THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_iterator'));
  END IF;
  SELECT * INTO inst FROM v24_cordis.installs WHERE id=f.install_id;
  IF NOT FOUND OR jsonb_typeof(inst.manifest->'requires')<>'array' THEN
   RETURN v24_cordis.error_v1('invalid_outcome');
  END IF;
  v_requires:=inst.manifest->'requires';
  IF jsonb_array_length(v_begin->'pins')<>jsonb_array_length(v_requires) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_pins'));
  END IF;
  FOR v_i IN 0..jsonb_array_length(v_requires)-1 LOOP
   v_pin:=v_begin->'pins'->v_i;
   v_req_key:=v24_cordis.require_key(v_requires->v_i);
   IF v_pin->>'key' IS DISTINCT FROM v_req_key
    OR v_req_key IS NULL OR NOT (v_begin->'committed_view' ? v_req_key) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_pins'));
   END IF;
   v_bind:=v_begin->'committed_view'->(v_pin->>'key');
   -- Recompute the selected target independently; a real but unrelated ledger row is not a binding.
   SELECT * INTO v_resolved FROM v24_cordis.resolve(f.scope_id,ARRAY[v_req_key]);
   IF NOT FOUND OR NOT v_resolved.available
    OR (v_pin->>'contribution_id')::uuid IS DISTINCT FROM v_resolved.contribution_id
    OR NOT v24_cordis.check_policy_ok(coalesce(inst.manifest->'check'->v_req_key,'null'::jsonb),v_resolved.descriptor) THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_target'));
   END IF;
   SELECT e.epoch,c.fiber_id,c.episode_id,c.contract_version,
     encode(sha256(convert_to(v24_cordis.canonical_json(c.descriptor),'UTF8')),'hex')
    INTO v_prov_epoch,v_prov_fiber,v_prov_ep,v_prov_cv,v_prov_digest
    FROM v24_cordis.contributions c JOIN v24_cordis.episodes e ON e.id=c.episode_id
    WHERE c.id=(v_pin->>'contribution_id')::uuid;
   IF NOT FOUND OR (v_pin->>'provider_episode_id')::uuid<>v_prov_ep
    OR (v_pin->>'provider_epoch')::int<>v_prov_epoch
    OR (v_bind->>'contribution_id')::uuid<>((v_pin->>'contribution_id')::uuid)
    OR (v_bind->>'provider_fiber_id')::uuid<>v_prov_fiber
    OR (v_bind->>'provider_episode_id')::uuid<>v_prov_ep
    OR (v_bind->>'provider_epoch')::int<>v_prov_epoch
    OR v_bind->>'descriptor_digest'<>v_prov_digest
    OR v_bind->>'contract_version'<>v_prov_cv THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_binding'));
   END IF;
   v_pin_ids:=v_pin_ids||jsonb_build_array(v_pin->'id');
   v_require_keys:=v_require_keys||jsonb_build_array(to_jsonb(v_req_key));
  END LOOP;
  SELECT coalesce(array_agg((e.value->>'provider_fiber_id')::uuid),ARRAY[]::uuid[]) INTO v_dag_ids
   FROM jsonb_each(coalesce(v_begin->'committed_view','{}'::jsonb)) e;
  v_dag:=v24_cordis.activation_dag(f.id,v_dag_ids);
  IF v_dag IS NOT NULL THEN
   RETURN v24_cordis.error_v1(v_dag->>'code',jsonb_build_object('reason',v_dag->>'reason'));
  END IF;
  IF v_ev IS NULL OR v_ev->>'entity_type' IS DISTINCT FROM 'fiber' OR (v_ev->>'entity_id')::uuid IS DISTINCT FROM f.id
   OR v_ev->>'event_kind' IS DISTINCT FROM 'episode_begun'
   OR NOT coalesce(v24_cordis.exact_keys(v_ev->'payload',ARRAY['episode_id','epoch','control_seq','require_keys','pin_ids']),false)
   OR (v_ev->'payload'->>'episode_id')::uuid IS DISTINCT FROM (v_begin->>'id')::uuid
   OR (v_ev->'payload'->>'epoch')::int IS DISTINCT FROM v_epoch
   OR (v_ev->'payload'->>'control_seq')::bigint IS DISTINCT FROM f.control_seq
   OR v_ev->'payload'->'require_keys' IS DISTINCT FROM v_require_keys
   OR v_ev->'payload'->'pin_ids' IS DISTINCT FROM v_pin_ids THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_shape'));
  END IF;
  IF jsonb_array_length(p_delta->'successors')<>1
   OR (p_delta->'successors'->0->'input'->>'fiber_id')::uuid<>f.id
   OR (p_delta->'successors'->0->'input'->>'expected_control_seq')::bigint<>f.control_seq THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p1_successor'));
  END IF;
 ELSIF v_branch='p2' THEN
  v_old_next:=(ep.iterator->>'next_index')::int; v_old_reg:=(ep.iterator->>'registered_through')::int;
  v_count:=0;
  FOR v_item IN SELECT value FROM jsonb_array_elements(v_domain) WITH ORDINALITY x(value,ord)
   WHERE x.value->>'op'='contribution_append' ORDER BY ord LOOP
   v_count:=v_count+1;
   IF (v_item->>'fiber_id')::uuid<>f.id OR (v_item->>'episode_id')::uuid<>ep.id
    OR v_item->>'kind'<>'service' THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p2_context'));
   END IF;
   v_seq:=v_old_reg+v_count;
   IF (v_item->>'seq')::bigint<>v_seq OR v_seq>2147483647 THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p2_seq'));
   END IF;
   v_prov:=v_provides->(v_old_next+v_count-1);
   IF v_prov IS NULL OR v_item->>'key' IS DISTINCT FROM v_prov->>'key'
    OR v_item->'descriptor' IS DISTINCT FROM v_prov->'descriptor'
    OR v_item->>'contract_version' IS DISTINCT FROM v_prov->>'contract_version'
    OR v_item->>'realm' IS DISTINCT FROM v24_cordis.service_realm(f.scope_id,v_item->>'key') THEN
    RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p2_provide'));
   END IF;
   v_contrib_ids:=v_contrib_ids||jsonb_build_array(v_item->'id');
   IF v_count=1 THEN v_first:=v_seq; END IF;
   v_last:=v_seq;
  END LOOP;
  IF v_count=0 OR v_old_next+v_count>jsonb_array_length(v_provides) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p2_batch'));
  END IF;
  IF v_progress IS NULL OR (v_progress->>'episode_id')::uuid<>ep.id
   OR (v_progress->>'next_index')::int<>v_old_next+v_count
   OR (v_progress->>'registered_through')::int<>v_old_reg+v_count THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p2_progress'));
  END IF;
  IF v_ev IS NULL OR v_ev->>'entity_type' IS DISTINCT FROM 'fiber' OR (v_ev->>'entity_id')::uuid IS DISTINCT FROM f.id
   OR v_ev->>'event_kind' IS DISTINCT FROM 'contributions_appended'
   OR NOT coalesce(v24_cordis.exact_keys(v_ev->'payload',ARRAY['episode_id','contribution_ids','seq_from','seq_through','next_index']),false)
   OR (v_ev->'payload'->>'episode_id')::uuid IS DISTINCT FROM ep.id
   OR v_ev->'payload'->'contribution_ids' IS DISTINCT FROM v_contrib_ids
   OR (v_ev->'payload'->>'seq_from')::bigint IS DISTINCT FROM v_first
   OR (v_ev->'payload'->>'seq_through')::bigint IS DISTINCT FROM v_last
   OR (v_ev->'payload'->>'next_index')::int IS DISTINCT FROM v_old_next+v_count THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_shape'));
  END IF;
  IF jsonb_array_length(p_delta->'successors')<>1
   OR (p_delta->'successors'->0->'input'->>'fiber_id')::uuid<>f.id
   OR (p_delta->'successors'->0->'input'->>'expected_control_seq')::bigint<>f.control_seq THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p2_successor'));
  END IF;
 ELSIF v_branch='p4' THEN
  IF v_activate IS NULL OR (v_activate->>'episode_id')::uuid<>ep.id THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p4_context'));
  END IF;
  IF (ep.iterator->>'next_index')::int<jsonb_array_length(inst.manifest->'provides') THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p4_totality'));
  END IF;
  IF v_ev IS NULL OR v_ev->>'entity_type' IS DISTINCT FROM 'fiber' OR (v_ev->>'entity_id')::uuid IS DISTINCT FROM f.id
   OR v_ev->>'event_kind' IS DISTINCT FROM 'episode_activated'
   OR NOT coalesce(v24_cordis.exact_keys(v_ev->'payload',ARRAY['episode_id','epoch']),false)
   OR (v_ev->'payload'->>'episode_id')::uuid IS DISTINCT FROM ep.id
   OR (v_ev->'payload'->>'epoch')::int IS DISTINCT FROM ep.epoch THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','event_shape'));
  END IF;
  IF p_delta->'successors' IS DISTINCT FROM v24_cordis.run_start_successor(f.id) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p4_successor'));
  END IF;
 ELSIF v_branch='p6' THEN
  IF p_delta IS DISTINCT FROM v24_cordis.p6_delta(p_effect_id,f.id) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','p6_diagnosis'));
  END IF;
  RETURN NULL;
 ELSIF v_branch='dispose' THEN
  v_plan:=v24_cordis.dispose_plan(inst.id);
  IF v_plan->>'kind' NOT IN ('request','fiber_request','fiber_control','schedule',
    'fiber_finish','child_install_finish','install_finish','wait_slot') THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispose_state'));
  END IF;
  IF p_delta IS DISTINCT FROM v24_cordis.dispose_delta(inst.id) THEN
   RETURN v24_cordis.error_v1('invalid_outcome',jsonb_build_object('reason','dispose_diagnosis'));
  END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION v24_cordis.validate_and_apply_delta(p_effect_id uuid,p_principal uuid,p_outcome jsonb,p_delta jsonb,p_closure jsonb,p_address_conflict text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE err jsonb; response jsonb; body jsonb:=p_outcome->'body'; item jsonb; v_pinrow jsonb;
 bytes bytea; sequence bigint; v_op text; v_actor text; v_cont boolean; v_emitted jsonb:='[]';
 v_sid uuid; v_ord int; v_fiber uuid; v_ep uuid; v_new_fiber uuid; v_new_ep uuid;
 v_constraint text; v_conflict_key text; v_branch jsonb; v_failure_ep v24_cordis.episodes%ROWTYPE;
 v_cid uuid; v_ok boolean; v_kind text; v_run v24_cordis.runs%ROWTYPE;
BEGIN
 SELECT EXISTS(SELECT 1 FROM v24_cordis.effects WHERE id=p_effect_id) INTO v_cont;
 IF v_cont THEN
  SELECT request_actor,kind INTO v_actor,v_kind FROM v24_cordis.effects WHERE id=p_effect_id;
 ELSE
  v_actor:=session_user;
 END IF;
 err:=v24_cordis.validate_delta(p_delta,p_outcome->>'class',false,v_kind);
 IF err IS NOT NULL THEN RETURN err; END IF;
 IF v_kind IN ('run_start','model_call','tool_call') THEN
  err:=v24_cordis.validate_run_domain(p_effect_id,p_principal,p_outcome,p_delta);
  IF err IS NOT NULL THEN RETURN err; END IF;
 ELSIF p_outcome->>'class'='command' THEN
  err:=v24_cordis.validate_domain(p_effect_id,p_principal,p_outcome,p_delta,p_closure,p_address_conflict);
  IF err IS NOT NULL THEN RETURN err; END IF;
 END IF;
 IF NOT v_cont AND p_outcome->>'class'='command' THEN
  SELECT (x->>'fiber')::uuid,(x->>'episode')::uuid INTO v_new_fiber,v_new_ep
   FROM (SELECT v24_cordis.command_binding(body) x) q;
 END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'successors') x
  ORDER BY (x.value->>'ordinal')::int LOOP
  v_sid:=v24_cordis.successor_effect_id(v_actor,p_effect_id,(item->>'ordinal')::int,item->>'kind');
  v_emitted:=v_emitted||jsonb_build_array(v_sid::text);
 END LOOP;
 response:=jsonb_build_object('v',1,'disposition','committed','effect_id',p_effect_id,
  'emitted',v_emitted,'revision',0,'claim',NULL);
 IF p_delta->'events'->0->>'event_kind'='run_refused' THEN
  response:=response||jsonb_build_object('reason',p_delta->'events'->0->'payload'->>'reason');
 END IF;
 -- Domain rows follow FK order: scope, install, fiber, episode+pins+current, contributions, iterator,
 -- target control, activation, dispose tombstone. No effect/request row exists before this point.
 BEGIN
 FOREACH v_op IN ARRAY ARRAY['scope_create','install_create','fiber_create','episode_begin',
  'run_create','run_pin_bind','run_state','run_budget',
  'contribution_append','episode_progress','fiber_control','fiber_retire','episode_close_start',
  'contributions_withdraw','contribution_inverse','run_seal','pins_release','episode_close',
  'episode_activate','install_dispose_request','fiber_dispose_request','fiber_dispose_finish',
  'install_dispose_finish'] LOOP
  FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'domain') WITH ORDINALITY x(value,ord)
   WHERE x.value->>'op'=v_op ORDER BY ord LOOP
   IF v_op='scope_create' THEN
    INSERT INTO v24_cordis.scopes(id,parent_id,realm_overrides,intercept)
     VALUES((item->>'id')::uuid,
      CASE WHEN item->'parent_id'='null'::jsonb THEN NULL ELSE (item->>'parent_id')::uuid END,
      item->'realm_overrides','{}'::jsonb);
   ELSIF v_op='install_create' THEN
    INSERT INTO v24_cordis.installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,
      manifest,artifact_digest,contracts,policy_ref,overlay,state)
     VALUES((item->>'id')::uuid,(item->>'scope_id')::uuid,
      CASE WHEN item->'owner_fiber_id'='null'::jsonb THEN NULL ELSE (item->>'owner_fiber_id')::uuid END,
      CASE WHEN item->'owner_episode_id'='null'::jsonb THEN NULL ELSE (item->>'owner_episode_id')::uuid END,
      item->>'identity',item->>'version',item->'manifest',item->>'artifact_digest',
      item->'contracts',CASE WHEN item->'policy_ref'='null'::jsonb THEN NULL ELSE item->>'policy_ref' END,
      item->'overlay','installed');
   ELSIF v_op='fiber_create' THEN
    INSERT INTO v24_cordis.fibers(id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq)
     VALUES((item->>'id')::uuid,(item->>'install_id')::uuid,
      CASE WHEN item->'owner_id'='null'::jsonb THEN NULL ELSE (item->>'owner_id')::uuid END,
      CASE WHEN item->'owner_episode_id'='null'::jsonb THEN NULL ELSE (item->>'owner_episode_id')::uuid END,
      (item->>'scope_id')::uuid,false,0);
   ELSIF v_op='episode_begin' THEN
    v_ep:=(item->>'id')::uuid; v_fiber:=(item->>'fiber_id')::uuid;
    INSERT INTO v24_cordis.episodes(id,fiber_id,epoch,state,committed_view,iterator)
     VALUES(v_ep,v_fiber,(item->>'epoch')::int,'reloading',item->'committed_view',item->'iterator');
    FOR v_pinrow IN SELECT value FROM jsonb_array_elements(item->'pins') LOOP
     INSERT INTO v24_cordis.pins(id,consumer_fiber_id,consumer_episode_id,key,contribution_id,provider_epoch)
      VALUES((v_pinrow->>'id')::uuid,v_fiber,v_ep,v_pinrow->>'key',(v_pinrow->>'contribution_id')::uuid,
       (v_pinrow->>'provider_epoch')::int);
    END LOOP;
    UPDATE v24_cordis.fibers SET current_episode_id=v_ep WHERE id=v_fiber;
   ELSIF v_op='run_create' THEN
    INSERT INTO v24_cordis.runs(id,owner_fiber_id,owner_episode_id,scope_id,state,remaining_steps)
     VALUES((item->>'id')::uuid,(item->>'owner_fiber_id')::uuid,(item->>'owner_episode_id')::uuid,
      (item->>'scope_id')::uuid,item->'state',(item->>'remaining_steps')::int);
   ELSIF v_op='run_pin_bind' THEN
    INSERT INTO v24_cordis.pins(id,consumer_run_id,key,contribution_id,provider_epoch)
     SELECT (p->>'id')::uuid,(item->>'run_id')::uuid,p->>'key',(p->>'contribution_id')::uuid,
      (p->>'provider_epoch')::int FROM jsonb_array_elements(item->'pins') p;
   ELSIF v_op='run_state' THEN
    UPDATE v24_cordis.runs SET state=item->'state' WHERE id=(item->>'run_id')::uuid;
   ELSIF v_op='run_budget' THEN
    UPDATE v24_cordis.runs SET remaining_steps=(item->>'remaining_steps')::int
     WHERE id=(item->>'run_id')::uuid
      AND remaining_steps=(item->>'remaining_steps')::int+1;
   ELSIF v_op='run_seal' THEN
    UPDATE v24_cordis.runs SET ended_at=clock_timestamp(),result=item->'result'
     WHERE id=(item->>'run_id')::uuid AND ended_at IS NULL;
   ELSIF v_op='contribution_append' THEN
    v_conflict_key:=item->>'key';
    INSERT INTO v24_cordis.contributions(id,fiber_id,episode_id,seq,kind,realm,key,descriptor,
      prev_contribution_id,inverse,contract_version)
     VALUES((item->>'id')::uuid,(item->>'fiber_id')::uuid,(item->>'episode_id')::uuid,
      (item->>'seq')::int,item->>'kind',
      CASE WHEN item->'realm'='null'::jsonb THEN NULL ELSE item->>'realm' END,
      CASE WHEN item->'key'='null'::jsonb THEN NULL ELSE item->>'key' END,
      item->'descriptor',
      CASE WHEN item->'prev_contribution_id'='null'::jsonb THEN NULL ELSE (item->>'prev_contribution_id')::uuid END,
      item->'inverse',item->>'contract_version');
   ELSIF v_op='episode_progress' THEN
    UPDATE v24_cordis.episodes SET iterator=iterator||jsonb_build_object(
      'next_index',(item->>'next_index')::int,'registered_through',(item->>'registered_through')::int)
     WHERE id=(item->>'episode_id')::uuid;
   ELSIF v_op='fiber_control' THEN
    UPDATE v24_cordis.fibers SET want_on=(item->'want_on')::boolean,
     control_seq=(item->>'control_seq')::bigint WHERE id=(item->>'fiber_id')::uuid;
   ELSIF v_op='fiber_retire' THEN
    UPDATE v24_cordis.fibers SET retire_started_at=coalesce(retire_started_at,clock_timestamp())
     WHERE id=(item->>'fiber_id')::uuid;
   ELSIF v_op='episode_close_start' THEN
    UPDATE v24_cordis.episodes SET state='closing',outcome=item->>'outcome'
     WHERE id=(item->>'episode_id')::uuid;
    IF item->'failure'<>'null'::jsonb THEN
     UPDATE v24_cordis.fibers SET failure=item->'failure' WHERE id=(item->>'fiber_id')::uuid;
    END IF;
   ELSIF v_op='contributions_withdraw' THEN
    UPDATE v24_cordis.contributions SET withdrawn_at=clock_timestamp()
     WHERE id IN (SELECT jsonb_array_elements_text(item->'contribution_ids')::uuid);
   ELSIF v_op='contribution_inverse' THEN
    FOR v_cid IN SELECT jsonb_array_elements_text(item->'contribution_ids')::uuid LOOP
     IF EXISTS(SELECT 1 FROM v24_cordis.contributions c WHERE c.id=v_cid AND c.kind='child'
      AND NOT (v24_cordis.json_uuid(c.descriptor->'child_fiber_id') AND EXISTS(
       SELECT 1 FROM v24_cordis.fibers cf WHERE cf.id=(c.descriptor->>'child_fiber_id')::uuid
        AND cf.disposed_at IS NOT NULL))) THEN
      RAISE EXCEPTION 'child is not tombstoned' USING ERRCODE='23514'; END IF;
     UPDATE v24_cordis.contributions SET withdrawn_at=coalesce(withdrawn_at,clock_timestamp()),
      released_at=clock_timestamp() WHERE id=v_cid;
     SELECT released_at IS NOT NULL AND withdrawn_at IS NOT NULL INTO v_ok
      FROM v24_cordis.contributions WHERE id=v_cid;
     IF v_ok IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'inverse postcondition' USING ERRCODE='23514'; END IF;
     IF EXISTS(SELECT 1 FROM v24_cordis.pins WHERE contribution_id=v_cid AND released_at IS NULL) THEN
      RAISE EXCEPTION 'inverse leaves live pin' USING ERRCODE='23514'; END IF;
    END LOOP;
   ELSIF v_op='pins_release' THEN
    FOR v_cid IN SELECT jsonb_array_elements_text(item->'pin_ids')::uuid LOOP
     IF NOT EXISTS(SELECT 1 FROM v24_cordis.pins p WHERE p.id=v_cid AND p.released_at IS NULL
      AND ((p.consumer_fiber_id=(item->>'fiber_id')::uuid
        AND p.consumer_episode_id=(item->>'episode_id')::uuid)
       OR (p.consumer_run_id IN (SELECT id FROM v24_cordis.runs
         WHERE owner_fiber_id=(item->>'fiber_id')::uuid
          AND owner_episode_id=(item->>'episode_id')::uuid AND ended_at IS NOT NULL)
        AND NOT EXISTS(SELECT 1 FROM v24_cordis.effects x WHERE x.id IS DISTINCT FROM p_effect_id
         AND x.run_id=p.consumer_run_id
         AND (x.kind='host_io' OR x.status IN ('ready','claimed','unknown')))))) THEN
      RAISE EXCEPTION 'pin release target' USING ERRCODE='23514'; END IF;
     UPDATE v24_cordis.pins SET released_at=clock_timestamp() WHERE id=v_cid;
     SELECT released_at IS NOT NULL INTO v_ok FROM v24_cordis.pins WHERE id=v_cid;
     IF v_ok IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'pin release postcondition' USING ERRCODE='23514'; END IF;
    END LOOP;
   ELSIF v_op='episode_close' THEN
    UPDATE v24_cordis.episodes SET closed_at=clock_timestamp()
     WHERE id=(item->>'episode_id')::uuid AND state='closing' AND closed_at IS NULL;
    UPDATE v24_cordis.fibers SET current_episode_id=NULL,retire_started_at=NULL
     WHERE id=(item->>'fiber_id')::uuid;
   ELSIF v_op='episode_activate' THEN
    UPDATE v24_cordis.episodes SET state='active' WHERE id=(item->>'episode_id')::uuid;
   ELSIF v_op='install_dispose_request' THEN
    UPDATE v24_cordis.installs SET state='dispose_pending'
     WHERE id=(item->>'install_id')::uuid AND state='installed';
   ELSIF v_op='fiber_dispose_request' THEN
    UPDATE v24_cordis.fibers SET want_on=false,control_seq=(item->>'control_seq')::bigint,
     dispose_requested_at=coalesce(dispose_requested_at,clock_timestamp())
     WHERE id=(item->>'fiber_id')::uuid;
   ELSIF v_op='fiber_dispose_finish' THEN
    UPDATE v24_cordis.fibers SET dispose_requested_at=coalesce(dispose_requested_at,clock_timestamp()),
     disposed_at=clock_timestamp()
     WHERE id=(item->>'fiber_id')::uuid AND disposed_at IS NULL;
   ELSIF v_op='install_dispose_finish' THEN
    UPDATE v24_cordis.installs SET state='disposed' WHERE id=(item->>'install_id')::uuid;
   END IF;
  END LOOP;
 END LOOP;
 PERFORM v24_cordis.assert_delta_applied(p_delta);
 EXCEPTION WHEN unique_violation THEN
  GET STACKED DIAGNOSTICS v_constraint=CONSTRAINT_NAME;
  IF v_constraint IS DISTINCT FROM 'contributions_service_addr' OR v_op<>'contribution_append'
   OR item->>'kind'<>'service' OR p_address_conflict IS NOT NULL
   OR p_outcome->'body'->>'kind'<>'command_reconcile' THEN RAISE; END IF;
  -- This subtransaction contains domain DML only. Its failed batch and iterator
  -- have rolled back before the same advance validates and commits Raise.
  v_fiber:=(p_outcome->'body'->'payload'->>'fiber_id')::uuid;
  SELECT e.* INTO v_failure_ep FROM v24_cordis.episodes e JOIN v24_cordis.fibers f
   ON f.current_episode_id=e.id WHERE f.id=v_fiber;
  v_branch:=v24_cordis.branch_raise(v_failure_ep,'p2','provide_conflict','address_conflict',v_conflict_key,
   (SELECT retire_started_at IS NULL FROM v24_cordis.fibers WHERE id=v_fiber));
  RETURN v24_cordis.validate_and_apply_delta(p_effect_id,p_principal,p_outcome,
   v24_cordis.closing_delta(v_fiber,v_branch),p_closure,v_conflict_key);
 END;
 IF p_outcome->>'class'='command' THEN
  IF v_cont THEN
   UPDATE v24_cordis.effects SET status='succeeded',outcome=p_outcome-'receipt_key',
    claim_owner=NULL,lease_until=NULL,settled_at=clock_timestamp() WHERE id=p_effect_id;
  ELSE
   INSERT INTO v24_cordis.effects(id,kind,status,fiber_id,episode_id,input,request_actor,outcome,settled_at)
    VALUES(p_effect_id,body->>'kind','succeeded',v_new_fiber,v_new_ep,body->'payload',session_user,
     p_outcome-'receipt_key',clock_timestamp());
  END IF;
  bytes:=convert_to(v24_cordis.canonical_json(body->'payload'),'UTF8');
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
   VALUES(gen_random_uuid(),p_effect_id,sequence,item->>'entity_type',(item->>'entity_id')::uuid,
    item->>'event_kind',item->'payload');
 END LOOP;
 FOR item IN SELECT value FROM jsonb_array_elements(p_delta->'successors') x
  ORDER BY (x.value->>'ordinal')::int LOOP
  v_ord:=(item->>'ordinal')::int;
  IF item->>'kind'='command_reconcile' THEN
   v_fiber:=(item->'input'->>'fiber_id')::uuid;
   SELECT current_episode_id INTO v_ep FROM v24_cordis.fibers WHERE id=v_fiber;
   INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,kind,status,input,request_actor)
    VALUES(v24_cordis.successor_effect_id(v_actor,p_effect_id,v_ord,'command_reconcile'),
     p_effect_id,v_ord,v_fiber,v_ep,'command_reconcile','ready',item->'input',v_actor);
  ELSIF item->>'kind'='run_start' THEN
   v_fiber:=(item->'input'->>'fiber_id')::uuid; v_ep:=(item->'input'->>'episode_id')::uuid;
   INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,kind,status,input,request_actor)
    VALUES(v24_cordis.successor_effect_id(v_actor,p_effect_id,v_ord,'run_start'),
     p_effect_id,v_ord,v_fiber,v_ep,'run_start','ready',item->'input',v_actor);
  ELSIF item->>'kind' IN ('model_call','tool_call') THEN
   SELECT * INTO v_run FROM v24_cordis.runs WHERE id=(item->'input'->>'run_id')::uuid;
   IF NOT FOUND THEN RAISE EXCEPTION 'run successor target' USING ERRCODE='23514'; END IF;
   INSERT INTO v24_cordis.effects(id,parent_id,ordinal,fiber_id,episode_id,run_id,kind,status,input,request_actor)
    VALUES(v24_cordis.successor_effect_id(v_actor,p_effect_id,v_ord,item->>'kind'),
     p_effect_id,v_ord,v_run.owner_fiber_id,v_run.owner_episode_id,v_run.id,
     item->>'kind','ready',item->'input',v_actor);
  ELSE
   RAISE EXCEPTION 'unsupported lifecycle successor kind' USING ERRCODE='0A000';
  END IF;
 END LOOP;
 RETURN response;
END $$;
CREATE FUNCTION v24_cordis.advance(p_effect_id uuid,p_outcome jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v24_cordis,pg_temp AS $$
DECLARE cls text; body jsonb; token jsonb; kind text; principal uuid; bytes bytea; canonical bytea;
 req v24_cordis.requests%ROWTYPE; eff v24_cordis.effects%ROWTYPE; closure jsonb; seed jsonb;
 delta jsonb; contract jsonb; binding jsonb; reclaim boolean; error_code text; lease int; allowed boolean;
 reserved boolean; cont boolean; action text; state jsonb; preflight jsonb;
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
  -- Request replay always wins; a continuation is never re-interpreted after its first response.
  SELECT * INTO req FROM v24_cordis.requests WHERE principal_id=principal AND request_key=body->>'request_key' FOR UPDATE;
  IF FOUND THEN
   IF req.kind=kind AND req.effect_id=p_effect_id AND req.request_bytes=bytes AND req.request_digest=sha256(bytes) THEN RETURN req.response; END IF;
   RETURN v24_cordis.error_v1('request_conflict');
  END IF;
  reserved:=(body->>'request_key') LIKE 'cordis/reconcile/%';
  IF kind='command_reconcile' AND body->'payload' ? 'action' THEN
   action:=body->'payload'->>'action';
  END IF;
  IF kind='command_reconcile' AND NOT coalesce(v24_cordis.reconcile_payload_valid(body->'payload'),false) THEN
   RETURN v24_cordis.error_v1('invalid_args',jsonb_build_object('reason','reconcile_payload'));
  END IF;
  IF kind='command_install' THEN
   preflight:=v24_cordis.install_preflight(body->'payload');
   IF preflight IS NOT NULL THEN RETURN v24_cordis.error_v1(preflight->>'code',jsonb_build_object('reason',preflight->>'reason')); END IF;
  END IF;
  IF reserved<>((kind='command_reconcile') AND action='advance') THEN
   RETURN v24_cordis.error_v1('invalid_args',jsonb_build_object('reason','reserved_key_pairing'));
  END IF;
  IF kind='command_reconcile' AND action IN ('on','off','retry') THEN
   preflight:=v24_cordis.reconcile_preflight(body->'payload');
   IF preflight IS NOT NULL THEN RETURN v24_cordis.error_v1(preflight->>'code',jsonb_build_object('reason',preflight->>'reason')); END IF;
  END IF;
  IF kind='command_dispose' AND v24_cordis.exact_keys(body->'payload',ARRAY['install_id'])
   AND v24_cordis.json_uuid(body->'payload'->'install_id') THEN
   preflight:=v24_cordis.dispose_preflight(body->'payload');
   IF preflight IS NOT NULL THEN RETURN v24_cordis.error_v1(preflight->>'code',jsonb_build_object('reason',preflight->>'reason')); END IF;
  END IF;
  IF reserved THEN
   cont:=true;
   state:=v24_cordis.continuation_state(p_effect_id,principal,body);
   IF state->>'class'='control' THEN state:=NULL; END IF;
   IF state IS NOT NULL THEN
    IF state->>'code'='0A000' THEN RAISE EXCEPTION '%',state->>'reason' USING ERRCODE='0A000'; END IF;
    RETURN v24_cordis.error_v1(state->>'code',jsonb_build_object('reason',state->>'reason'));
   END IF;
   seed:=v24_cordis.command_seed(kind,body->'payload')
     ||jsonb_build_array(jsonb_build_object('t','effects','id',p_effect_id::text));
   IF seed IS NULL THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
  ELSE
   cont:=false;
   IF EXISTS(SELECT 1 FROM v24_cordis.effects WHERE id=p_effect_id) THEN RETURN v24_cordis.error_v1('effect_id_conflict'); END IF;
   seed:=v24_cordis.command_seed(kind,body->'payload');
   IF seed IS NULL THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
  END IF;
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
  IF cls='claim' AND eff.run_id IS NOT NULL AND EXISTS(
   SELECT 1 FROM v24_cordis.effects x WHERE x.run_id=eff.run_id AND x.status='unknown') THEN
   RETURN v24_cordis.error_v1('blocked_unknown');
  END IF;
  seed:=v24_cordis.settlement_seed(p_effect_id);
 END IF;
 closure:=CASE WHEN cls='command' AND NOT cont THEN v24_cordis.command_closure(kind,body->'payload') ELSE v24_cordis.discover_closure(seed) END;
 IF closure IS NULL THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 IF NOT v24_cordis.lock_closure(closure) THEN RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 IF cls<>'command' THEN
  IF v24_cordis.discover_closure(v24_cordis.settlement_seed(p_effect_id)) IS DISTINCT FROM closure THEN
   RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 ELSIF v24_cordis.discover_closure(seed) IS DISTINCT FROM closure THEN
  RETURN v24_cordis.error_v1('retry_with_closure');
 END IF;
 IF cls='command' AND cont THEN
  -- Re-verify the frozen generation/binding after all locks; drift is closure drift, not a new error class.
  state:=v24_cordis.continuation_state(p_effect_id,principal,body);
  IF state IS NOT NULL AND state->>'class' IS DISTINCT FROM 'control' THEN
   RETURN v24_cordis.error_v1('retry_with_closure'); END IF;
 END IF;
 IF cls='claim' THEN
  SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
  IF eff.status='claimed' AND eff.lease_until>clock_timestamp() THEN
   RETURN v24_cordis.error_v1('stale_claim','{"reason":"claim_busy"}');
  END IF;
  reclaim:=eff.status='claimed'; error_code:=CASE WHEN reclaim THEN 'blocked_unknown' ELSE 'invalid_args' END;
  contract:=v24_cordis.claim_contract(eff);
  binding:=eff.input->'contract';
  allowed:=coalesce(jsonb_typeof(contract)='object' AND jsonb_typeof(contract->'contract_version')='string'
   AND length(contract->>'contract_version')>0 AND jsonb_typeof(contract->'handler_digest')='string'
   AND contract->>'handler_digest'~'^[0-9a-f]{64}$'
   AND v24_cordis.exact_keys(binding,ARRAY['contract_version','handler_digest'])
   AND binding->'contract_version'=contract->'contract_version' AND jsonb_typeof(binding->'handler_digest')='string'
   AND binding->'handler_digest'=contract->'handler_digest',false);
  IF NOT allowed THEN
   IF eff.kind IN ('run_start','model_call','tool_call') THEN
    RETURN v24_cordis.error_v1('invalid_outcome');
   END IF;
   RETURN v24_cordis.error_v1(error_code);
  END IF;
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
   'claim',jsonb_build_object('attempt',eff.attempt,'fence',eff.fence,'owner',eff.claim_owner),
   'input',eff.input);
 ELSIF cls<>'command' THEN
  SELECT * INTO eff FROM v24_cordis.effects WHERE id=p_effect_id;
  IF eff.status<>'claimed' OR eff.attempt<>(token->>'attempt')::bigint OR eff.fence<>(token->>'fence')::bigint
    OR eff.claim_owner IS DISTINCT FROM token->>'owner' THEN RETURN v24_cordis.error_v1('stale_claim'); END IF;
  delta:=v24_cordis.interpret_settlement(p_effect_id,principal,p_outcome,closure);
 ELSE
  delta:=v24_cordis.interpret_command(p_effect_id,principal,p_outcome,closure);
 END IF;
 IF delta IS NULL OR jsonb_typeof(delta)<>'object' THEN
  RAISE EXCEPTION 'interpreter returned no delta' USING ERRCODE='0A000';
 END IF;
 IF delta ? 'error' THEN RETURN delta; END IF;
 IF delta ? 'kind' THEN
  IF NOT coalesce(v24_cordis.exact_keys(delta,ARRAY['kind','step','barrier','context']),false) THEN
   RAISE EXCEPTION 'command control result' USING ERRCODE='0A000';
  END IF;
  IF delta->>'kind'='ready' THEN
   delta:=delta->'context';
   IF delta IS NULL OR jsonb_typeof(delta)<>'object' THEN
    RAISE EXCEPTION 'interpreter returned no delta' USING ERRCODE='0A000';
   END IF;
   IF delta ? 'error' THEN RETURN delta; END IF;
  ELSIF delta->>'kind'='deferred' THEN
   RETURN jsonb_build_object('v',1,'disposition','deferred','effect_id',p_effect_id,'emitted','[]'::jsonb,'revision',0,'claim',NULL);
  ELSIF delta->>'kind'='blocked_unknown' THEN
   RETURN v24_cordis.error_v1('blocked_unknown');
  ELSIF delta->>'kind'='unsupported' THEN
   RAISE EXCEPTION 'unsupported command obligation' USING ERRCODE='0A000';
  ELSE
   RAISE EXCEPTION 'command control result' USING ERRCODE='0A000';
  END IF;
 END IF;
 RETURN v24_cordis.validate_and_apply_delta(p_effect_id,principal,p_outcome,delta,closure);
END $$;
