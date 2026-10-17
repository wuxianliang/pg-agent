-- v13 Stage 40: native CE run control plane.
-- The CE layer owns only its five tables and never replaces Stage 1-39 functions.
BEGIN;

CREATE TABLE public.v13_ce_runs (
  run_id uuid PRIMARY KEY REFERENCES public.sessions(session_id),
  session_id uuid NOT NULL UNIQUE REFERENCES public.sessions(session_id),
  registration_generation bigint NOT NULL DEFAULT 1 CHECK (registration_generation > 0),
  owner_generation bigint NOT NULL DEFAULT 1 CHECK (owner_generation > 0),
  current_epoch_ordinal bigint NOT NULL DEFAULT 1 CHECK (current_epoch_ordinal > 0),
  continuity_generation bigint NOT NULL DEFAULT 1 CHECK (continuity_generation > 0),
  status text NOT NULL CHECK (status IN ('running','waiting_for_input','completed','failed','cancelled','expired')),
  interaction jsonb,
  failure_reason jsonb,
  revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
  driving_operation_id uuid,
  owner_backend_pid integer,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (run_id = session_id),
  CHECK (interaction IS NULL OR
         (COALESCE(jsonb_typeof(interaction) = 'object', false)
          AND (interaction ? 'id')
          AND COALESCE(jsonb_typeof(interaction->'id') = 'string', false)
          AND btrim(COALESCE(interaction->>'id','')) <> ''
          AND (interaction ? 'kind')
          AND COALESCE(jsonb_typeof(interaction->'kind') = 'string', false)
          AND btrim(COALESCE(interaction->>'kind','')) <> ''))
);

CREATE TABLE public.v13_ce_epochs (
  epoch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES public.v13_ce_runs(run_id),
  ordinal bigint NOT NULL CHECK (ordinal > 0),
  continuity_generation bigint NOT NULL CHECK (continuity_generation > 0),
  registration_generation bigint NOT NULL CHECK (registration_generation > 0),
  transition_kind text NOT NULL CHECK (transition_kind IN ('initial','steering','related_follow_up','unrelated')),
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz,
  UNIQUE (run_id, ordinal),
  UNIQUE (run_id, epoch_id)
);
CREATE UNIQUE INDEX v13_ce_one_open_epoch ON public.v13_ce_epochs(run_id) WHERE closed_at IS NULL;

CREATE TABLE public.v13_ce_operations (
  operation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id text NOT NULL UNIQUE,
  run_id uuid NOT NULL REFERENCES public.v13_ce_runs(run_id),
  epoch_id uuid NOT NULL REFERENCES public.v13_ce_epochs(epoch_id),
  verb text NOT NULL CHECK (verb IN ('start','steer','respond','cancel','admit_turn','admit_tool')),
  owner_generation bigint NOT NULL DEFAULT 1 CHECK (owner_generation > 0),
  registration_generation bigint NOT NULL DEFAULT 1 CHECK (registration_generation > 0),
  attempt_seq bigint NOT NULL CHECK (attempt_seq > 0),
  status text NOT NULL CHECK (status IN ('pending','completed','archived','closed')),
  input_message text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  payload_digest text NOT NULL,
  effect_id uuid UNIQUE REFERENCES public.effects(effect_id),
  result jsonb,
  admission_result jsonb,
  publications jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  UNIQUE (run_id, attempt_seq),
  UNIQUE (run_id, epoch_id, operation_id),
  CHECK (octet_length(coalesce(input_message, '')) <= 65536),
  CHECK (octet_length(payload::text) <= 1048576)
);
ALTER TABLE public.v13_ce_operations
  ADD CONSTRAINT v13_ce_operation_epoch_owner_fk
  FOREIGN KEY (run_id, epoch_id) REFERENCES public.v13_ce_epochs(run_id, epoch_id);
ALTER TABLE public.v13_ce_runs
  ADD CONSTRAINT v13_ce_driving_fk
  FOREIGN KEY (driving_operation_id) REFERENCES public.v13_ce_operations(operation_id);

CREATE TABLE public.v13_ce_snapshots (
  run_id uuid PRIMARY KEY REFERENCES public.v13_ce_runs(run_id),
  registration_generation bigint NOT NULL DEFAULT 1,
  epoch_ordinal bigint NOT NULL CHECK (epoch_ordinal > 0),
  revision bigint NOT NULL CHECK (revision > 0),
  status text NOT NULL CHECK (status IN ('running','waiting_for_input','completed','failed','cancelled','expired')),
  interaction jsonb,
  assistant_text text,
  failure_reason jsonb,
  last_operation_id uuid REFERENCES public.v13_ce_operations(operation_id),
  interaction_effect_id uuid REFERENCES public.effects(effect_id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.v13_ce_wakes (
  wake_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES public.v13_ce_runs(run_id),
  registration_generation bigint NOT NULL DEFAULT 1,
  epoch_ordinal bigint NOT NULL CHECK (epoch_ordinal > 0),
  reason text NOT NULL CHECK (reason IN ('snapshot','steering_requested','terminal','cancelled','superseded')),
  steering_message text,
  interaction jsonb,
  origin_run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX v13_ce_ops_scan ON public.v13_ce_operations(run_id, epoch_id, status, attempt_seq);
CREATE INDEX v13_ce_wakes_scan ON public.v13_ce_wakes(run_id, registration_generation, epoch_ordinal, wake_id);

-- The existing sessions trigger intentionally accepts inserts only from this owner.
CREATE FUNCTION public.v13_ce_insert_session(uuid, uuid, bigint)
RETURNS uuid
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  INSERT INTO public.sessions (session_id, parent_session_id, parent_cutoff_seq)
  VALUES ($1, $2, $3)
  RETURNING session_id
$$;
ALTER FUNCTION public.v13_ce_insert_session(uuid, uuid, bigint) OWNER TO v13_spawn_owner;

CREATE FUNCTION public.v13_ce_caller_role()
RETURNS name
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r name := current_setting('role', true);
BEGIN
  IF r IS NULL OR r = '' OR r = 'none' THEN r := session_user; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
    RAISE EXCEPTION 'v13 ce: caller role';
  END IF;
  RETURN r;
END $$;

CREATE FUNCTION public.v13_ce_is_operator()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = public.v13_ce_caller_role() AND rolsuper)
      OR pg_has_role(public.v13_ce_caller_role(), 'v13_route', 'USAGE')
$$;

CREATE FUNCTION public.v13_ce_is_route()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = public.v13_ce_caller_role() AND rolsuper)
      OR pg_has_role(public.v13_ce_caller_role(), 'v13_route', 'USAGE')
$$;

CREATE FUNCTION public.v13_ce_read_ok(p_actor uuid, p_run uuid)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE parent_id uuid;
BEGIN
  IF p_actor IS NULL THEN
    RETURN COALESCE(public.v13_ce_is_operator(),false)
       OR COALESCE(pg_has_role(public.v13_ce_caller_role(), 'v13_recall', 'USAGE'),false);
  END IF;
  SELECT parent_session_id INTO parent_id FROM public.sessions WHERE session_id = p_run;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM public.sessions WHERE session_id = p_actor) THEN
    RETURN false;
  END IF;
  RETURN COALESCE(p_actor = p_run,false)
      OR COALESCE(parent_id = p_actor,false);
END $$;

CREATE FUNCTION public.v13_ce_write_ok(p_actor uuid, p_run uuid)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
BEGIN
  IF NOT COALESCE(public.v13_ce_is_route(),false) THEN RETURN false; END IF;
  IF p_actor IS NULL THEN RETURN COALESCE(public.v13_ce_is_operator(),false); END IF;
  RETURN COALESCE(public.v13_ce_read_ok(p_actor, p_run),false);
END $$;

CREATE FUNCTION public.v13_ce_json_digest(p_verb text, p_actor uuid, p_run uuid, p_payload jsonb)
RETURNS text LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT encode(digest(jsonb_build_object('verb',p_verb,'actor',p_actor,'run',p_run,
                                          'payload',coalesce(p_payload,'{}'::jsonb))::text,'sha256'),'hex')
$$;

CREATE FUNCTION public.v13_ce_request_replay(p_request text, p_digest text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT CASE
    WHEN payload_digest IS DISTINCT FROM p_digest
      THEN jsonb_build_object('schema_version',1,'ok',false,'reason','request_id_conflict')
    ELSE coalesce(admission_result,
                  result,
                  jsonb_build_object('schema_version',1,'ok',true,'operation_id',operation_id))
  END
  FROM public.v13_ce_operations WHERE request_id = p_request
$$;

CREATE FUNCTION public.v13_ce_wake(p_run uuid, p_epoch bigint, p_reason text,
                                   p_message text DEFAULT NULL, p_interaction jsonb DEFAULT NULL,
                                   p_origin uuid DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE w bigint;
        rev bigint;
BEGIN
  INSERT INTO public.v13_ce_wakes(run_id, registration_generation, epoch_ordinal, reason,
                                  steering_message, interaction, origin_run_id)
  SELECT p_run, registration_generation, p_epoch, p_reason, p_message, p_interaction, p_origin
  FROM public.v13_ce_runs WHERE run_id = p_run
  RETURNING wake_id INTO w;
  IF w IS NOT NULL THEN
    SELECT revision INTO rev FROM public.v13_ce_runs WHERE run_id=p_run;
    PERFORM pg_notify('v13_ce_run_changed', p_run::text || '|' || coalesce(rev,0)::text);
  END IF;
  RETURN w;
END $$;

CREATE FUNCTION public.v13_ce_next_attempt(p_run uuid)
RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$ SELECT coalesce(max(attempt_seq),0) + 1 FROM public.v13_ce_operations WHERE run_id = $1 $$;

CREATE FUNCTION public.v13_ce_unknown(p_run uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$ SELECT EXISTS (SELECT 1 FROM public.effects WHERE session_id = $1 AND status = 'unknown') $$;

CREATE FUNCTION public.v13_ce_tool_schema(p_tool text)
RETURNS json LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT CASE $1
    WHEN 'spawn_subsession' THEN
      '{"$schema":"http://json-schema.org/draft-07/schema#","type":"object",'
      '"additionalProperties":false,"required":["task"],'
      '"properties":{"task":{"type":"string","minLength":1,"maxLength":1024}}}'::json
    ELSE NULL::json
  END
$$;

CREATE FUNCTION public.v13_ce_tool_check(p_tool text, p_params jsonb)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE schema_doc json;
BEGIN
  IF p_tool IS NULL OR btrim(p_tool)='' THEN RETURN 'invalid_args'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.tools WHERE name=p_tool AND enabled) THEN
    RETURN 'invalid_tool';
  END IF;
  schema_doc:=public.v13_ce_tool_schema(p_tool);
  IF schema_doc IS NULL THEN RETURN 'invalid_tool'; END IF;
  IF p_params IS NULL OR jsonb_typeof(p_params)<>'object'
     OR NOT coalesce(jsonb_matches_schema(schema_doc,p_params),false) THEN
    RETURN 'invalid_tool_args';
  END IF;
  RETURN NULL;
END $$;

CREATE FUNCTION public.v13_ce_claim_bound_effect(p_run uuid, p_effect uuid, p_worker text, p_lease_ms integer)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE e public.effects;
BEGIN
  IF p_worker IS NULL OR btrim(p_worker)='' OR p_lease_ms IS NULL OR p_lease_ms<1 THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_args');
  END IF;
  PERFORM 1 FROM public.sessions WHERE session_id=p_run FOR UPDATE;
  PERFORM 1 FROM public.v13_ce_runs WHERE run_id=p_run FOR UPDATE;
  SELECT * INTO e FROM public.effects WHERE effect_id=p_effect AND session_id=p_run FOR UPDATE;
  IF NOT FOUND OR e.status<>'ready' OR NOT public.v13_attempt_ok(e.kind,e.attempt_no)
     OR (e.op_seq IS NOT NULL AND e.op_seq IS DISTINCT FROM
         (SELECT min(x.op_seq) FROM public.effects x WHERE x.session_id=e.session_id
            AND x.mutation_scope=e.mutation_scope AND x.status<>'succeeded'))
     OR (public.v13_requires_worktree(e.tool_name)
         AND NOT EXISTS (SELECT 1 FROM public.latches l WHERE l.session_id=e.session_id AND l.name='worktree')) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','not_claimable');
  END IF;
  UPDATE public.effects SET status='claimed',attempt_no=attempt_no+1,fence=fence+1,
      lease_owner=p_worker,lease_until=clock_timestamp()+make_interval(secs=>p_lease_ms/1000.0)
    WHERE effect_id=e.effect_id;
  SELECT * INTO e FROM public.effects WHERE effect_id=p_effect;
  RETURN jsonb_build_object('schema_version',1,'ok',true,'effect_id',e.effect_id,
      'attempt_no',e.attempt_no,'fence',e.fence,'request',e.request,
      'idempotency_key',e.idempotency_key);
END $$;

CREATE FUNCTION public.v13_ce_promote_next_effect(p_run uuid)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r public.v13_ce_runs; o public.v13_ce_operations; e uuid; req jsonb; kind text; tool_name text; check_reason text;
BEGIN
  PERFORM 1 FROM public.sessions WHERE session_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND OR r.status <> 'running' OR public.v13_ce_unknown(p_run) THEN RETURN NULL; END IF;
  PERFORM 1 FROM public.v13_ce_epochs
   WHERE run_id=p_run AND ordinal=r.current_epoch_ordinal AND closed_at IS NULL FOR UPDATE;
  IF EXISTS (SELECT 1 FROM public.effects WHERE session_id=p_run AND status IN ('ready','claimed','unknown')) THEN RETURN NULL; END IF;
  LOOP
    SELECT * INTO o
    FROM public.v13_ce_operations
    WHERE run_id=p_run AND epoch_id=(SELECT epoch_id FROM public.v13_ce_epochs
                                    WHERE run_id=p_run AND ordinal=r.current_epoch_ordinal)
      AND status='pending' AND effect_id IS NULL
    ORDER BY attempt_seq FOR UPDATE SKIP LOCKED LIMIT 1;
    IF NOT FOUND THEN RETURN NULL; END IF;
    kind := CASE WHEN o.verb='admit_tool' THEN 'tool' ELSE 'llm' END;
    tool_name := CASE WHEN kind='tool' THEN o.payload->>'tool' ELSE NULL END;
    IF o.verb='admit_tool' THEN
      PERFORM 1 FROM public.tools WHERE name=tool_name FOR SHARE;
      check_reason:=public.v13_ce_tool_check(tool_name,o.payload->'params');
      IF check_reason IS NOT NULL THEN
        UPDATE public.v13_ce_operations
           SET status='archived',completed_at=now(),
               result=jsonb_build_object('schema_version',1,'ok',false,
                                         'reason','invalid_tool_at_promotion','detail',check_reason)
         WHERE operation_id=o.operation_id;
        CONTINUE;
      END IF;
    END IF;
    req := coalesce(o.payload,'{}'::jsonb) || jsonb_build_object('operation_id',o.operation_id);
    e := public.v13_enqueue_effect(p_run, kind, req, tool_name);
    UPDATE public.v13_ce_operations SET effect_id=e WHERE operation_id=o.operation_id;
    RETURN e;
  END LOOP;
END $$;

CREATE FUNCTION public.v13_ce_followup(p_run uuid, p_epoch uuid, p_parent uuid, p_payload jsonb)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE oid uuid := gen_random_uuid(); rid text := 'ce:' || p_parent::text || ':followup'; n bigint;
BEGIN
  n := public.v13_ce_next_attempt(p_run);
  INSERT INTO public.v13_ce_operations(operation_id,request_id,run_id,epoch_id,verb,attempt_seq,status,
                                       payload,payload_digest,admission_result)
  VALUES (oid,rid,p_run,p_epoch,'admit_turn',n,'pending',
          coalesce(p_payload,'{}'::jsonb) || jsonb_build_object('operation_id',oid),
          public.v13_ce_json_digest('admit_turn',NULL,p_run,coalesce(p_payload,'{}'::jsonb)),
          jsonb_build_object('schema_version',1,'ok',true,'queued',true,'operation_id',oid,
                             'request_id',rid,'epoch_ordinal',(SELECT ordinal FROM public.v13_ce_epochs WHERE epoch_id=p_epoch)))
  ON CONFLICT (request_id) DO NOTHING;
  SELECT operation_id INTO oid FROM public.v13_ce_operations WHERE request_id=rid;
  UPDATE public.v13_ce_runs SET driving_operation_id=oid WHERE run_id=p_run;
  RETURN oid;
END $$;

CREATE FUNCTION public.v13_ce_run_start(p_actor uuid, p_message text, p_request_id text,
                                        p_parent_session uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE sid uuid := gen_random_uuid(); eid uuid := gen_random_uuid(); oid uuid := gen_random_uuid();
        eff uuid; n bigint; next_seq bigint; old public.v13_ce_operations; d text; start_result jsonb;
BEGIN
  IF p_request_id IS NULL OR btrim(p_request_id)='' OR octet_length(p_request_id)>512
     OR p_message IS NULL OR btrim(p_message)='' OR octet_length(p_message)>65536 THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_args');
  END IF;
  IF p_parent_session IS NULL THEN
    IF p_actor IS NOT NULL OR NOT public.v13_ce_is_operator() THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized');
    END IF;
  ELSE
    IF NOT public.v13_ce_write_ok(p_actor,p_parent_session) THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized');
    END IF;
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('v13-ce-request:'||p_request_id,0));
  d := public.v13_ce_json_digest('start',p_actor,p_parent_session,jsonb_build_object('message',p_message));
  SELECT * INTO old FROM public.v13_ce_operations WHERE request_id=p_request_id;
  IF FOUND THEN RETURN public.v13_ce_request_replay(p_request_id,d); END IF;
  IF p_parent_session IS NOT NULL THEN
    SELECT s.next_seq INTO next_seq FROM public.sessions AS s WHERE s.session_id=p_parent_session FOR UPDATE;
    IF NOT FOUND THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized'); END IF;
    IF next_seq < 1 THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','parent_prefix_empty'); END IF;
    IF public.v13_ce_insert_session(sid,p_parent_session,next_seq-1) IS DISTINCT FROM sid THEN
      RAISE EXCEPTION 'v13 ce: session insert identity';
    END IF;
  ELSE
    IF public.v13_ce_insert_session(sid,NULL,NULL) IS DISTINCT FROM sid THEN
      RAISE EXCEPTION 'v13 ce: session insert identity';
    END IF;
  END IF;
  INSERT INTO public.v13_ce_runs(run_id,session_id,status,owner_backend_pid)
  VALUES(sid,sid,'running',pg_backend_pid());
  INSERT INTO public.v13_ce_epochs(epoch_id,run_id,ordinal,continuity_generation,registration_generation,transition_kind)
  VALUES(eid,sid,1,1,1,'initial');
  n := 1;
  INSERT INTO public.v13_ce_operations(operation_id,request_id,run_id,epoch_id,verb,attempt_seq,status,
                                       input_message,payload,payload_digest)
  VALUES(oid,p_request_id,sid,eid,'start',n,'pending',p_message,
         jsonb_build_object('operation_id',oid,'message',p_message),d);
  PERFORM public.v13_append_event(sid,gen_random_uuid(),'user/message',jsonb_build_object('message',p_message));
  eff := public.v13_enqueue_effect(sid,'llm',jsonb_build_object('operation_id',oid,'message',p_message));
  UPDATE public.v13_ce_operations SET effect_id=eff WHERE operation_id=oid;
  UPDATE public.v13_ce_runs SET driving_operation_id=oid WHERE run_id=sid;
  INSERT INTO public.v13_ce_snapshots(run_id,registration_generation,epoch_ordinal,revision,status,last_operation_id)
  VALUES(sid,1,1,1,'running',oid);
  PERFORM public.v13_ce_wake(sid,1,'snapshot');
  start_result := jsonb_build_object('schema_version',1,'ok',true,'run_id',sid,'session_id',sid,
                               'operation_id',oid,'effect_id',eff,'registration_generation',1,
                               'epoch_ordinal',1,'continuity_generation',1,'revision',1,'status','running');
  UPDATE public.v13_ce_operations SET admission_result=start_result WHERE operation_id=oid;
  RETURN start_result;
END $$;

CREATE FUNCTION public.v13_ce_run_poll(p_actor uuid, p_run_id uuid, p_registration bigint DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  WITH x AS (
    SELECT r.*, s.interaction AS snap_interaction, s.assistant_text, s.failure_reason AS snap_failure,
           s.last_operation_id, s.updated_at AS snap_updated
    FROM public.v13_ce_runs r JOIN public.v13_ce_snapshots s USING(run_id)
    WHERE r.run_id=$2 AND ($3 IS NULL OR r.registration_generation=$3)
  )
  SELECT CASE WHEN NOT COALESCE(public.v13_ce_read_ok($1,$2),false) OR NOT EXISTS (SELECT 1 FROM x)
    THEN jsonb_build_object('schema_version',1,'ok',true,'reason','expired')
    ELSE (SELECT jsonb_build_object('schema_version',1,'ok',true,'run_id',run_id,'session_id',session_id,
      'registration_generation',registration_generation,'epoch_ordinal',current_epoch_ordinal,
      'continuity_generation',continuity_generation,'revision',revision,'status',status,
      'interaction',snap_interaction,'assistant_text',assistant_text,'failure_reason',coalesce(snap_failure,failure_reason),
      'last_operation_id',last_operation_id,'updated_at',snap_updated) FROM x)
  END
$$;

CREATE FUNCTION public.v13_ce_run_wait_check(p_actor uuid, p_run_id uuid, p_registration bigint,
                                             p_epoch bigint, p_after_wake_id bigint DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r public.v13_ce_runs; s public.v13_ce_snapshots; w public.v13_ce_wakes; rec jsonb;
        requested_continuity bigint;
BEGIN
  IF p_registration IS NULL OR p_epoch IS NULL OR p_after_wake_id IS NULL
     OR p_registration<=0 OR p_epoch<=0 OR p_after_wake_id<0 THEN
    RETURN jsonb_build_object('schema_version',1,'reason','invalid_wait_args','snapshot',NULL,
      'registration_generation',NULL,'epoch_ordinal',NULL,'continuity_generation',NULL,'interaction',NULL,'wake_id',NULL);
  END IF;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=p_run_id;
  IF NOT FOUND OR NOT COALESCE(public.v13_ce_read_ok(p_actor,p_run_id),false) OR r.registration_generation<>p_registration THEN
    RETURN jsonb_build_object('schema_version',1,'reason','expired','snapshot',NULL,
      'registration_generation',NULL,'epoch_ordinal',NULL,'continuity_generation',NULL,'interaction',NULL,'wake_id',NULL);
  END IF;
  IF p_epoch > r.current_epoch_ordinal THEN
    RETURN jsonb_build_object('schema_version',1,'reason','invalid_wait_args','snapshot',NULL,
      'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
      'continuity_generation',r.continuity_generation,'interaction',NULL,'wake_id',NULL);
  END IF;
  SELECT * INTO s FROM public.v13_ce_snapshots WHERE run_id=p_run_id;
  SELECT continuity_generation INTO requested_continuity
    FROM public.v13_ce_epochs WHERE run_id=p_run_id AND ordinal=p_epoch;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('schema_version',1,'reason','invalid_wait_args','snapshot',NULL,
      'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
      'continuity_generation',r.continuity_generation,'interaction',NULL,'wake_id',NULL);
  END IF;
  IF requested_continuity IS DISTINCT FROM r.continuity_generation THEN
    RETURN jsonb_build_object('schema_version',1,'reason','superseded','snapshot',to_jsonb(s),
      'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
      'continuity_generation',r.continuity_generation,'interaction',s.interaction,'wake_id',NULL);
  END IF;
  SELECT * INTO w FROM public.v13_ce_wakes
   WHERE run_id=p_run_id AND registration_generation=p_registration AND epoch_ordinal>=p_epoch
     AND wake_id>p_after_wake_id AND reason='steering_requested'
   ORDER BY wake_id LIMIT 1;
  IF FOUND THEN
    rec := to_jsonb(s) || jsonb_build_object(
      'steering_message',CASE WHEN p_actor IS NOT NULL AND w.origin_run_id IS NOT NULL
                                   AND w.origin_run_id=p_actor
                              THEN NULL::text ELSE w.steering_message END);
    RETURN jsonb_build_object('schema_version',1,'reason','interrupted_by_steering','snapshot',rec,
      'registration_generation',r.registration_generation,'epoch_ordinal',w.epoch_ordinal,
      'continuity_generation',r.continuity_generation,'interaction',s.interaction,'wake_id',w.wake_id);
  END IF;
  IF s.interaction IS NOT NULL OR s.status IN ('waiting_for_input','completed','failed','cancelled','expired') THEN
    RETURN jsonb_build_object('schema_version',1,'reason','actionable','snapshot',to_jsonb(s),
      'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
      'continuity_generation',r.continuity_generation,'interaction',s.interaction,'wake_id',NULL);
  END IF;
  IF r.current_epoch_ordinal > p_epoch THEN
    RETURN jsonb_build_object('schema_version',1,'reason','epoch_advanced','snapshot',to_jsonb(s),
      'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
      'continuity_generation',r.continuity_generation,'interaction',s.interaction,'wake_id',NULL);
  END IF;
  RETURN jsonb_build_object('schema_version',1,'reason','waiting','snapshot',to_jsonb(s),
    'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
    'continuity_generation',r.continuity_generation,'interaction',s.interaction,'wake_id',NULL);
END $$;

CREATE FUNCTION public.v13_ce_run_cancel(p_actor uuid, p_run_id uuid, p_request_id text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r public.v13_ce_runs; ep uuid; oid uuid:=gen_random_uuid(); n bigint; d text; out jsonb; old public.v13_ce_operations;
        seal jsonb; hashes jsonb; repairs jsonb; replans jsonb; materials jsonb; wakes jsonb; approvals jsonb; children jsonb;
BEGIN
  IF p_request_id IS NULL OR btrim(p_request_id)='' OR NOT public.v13_ce_write_ok(p_actor,p_run_id) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason',CASE WHEN p_request_id IS NULL THEN 'invalid_args' ELSE 'unauthorized' END);
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('v13-ce-request:'||p_request_id,0));
  d:=public.v13_ce_json_digest('cancel',p_actor,p_run_id,'{}'::jsonb);
  SELECT * INTO old FROM public.v13_ce_operations WHERE request_id=p_request_id;
  IF FOUND THEN RETURN public.v13_ce_request_replay(p_request_id,d); END IF;
  PERFORM 1 FROM public.sessions WHERE session_id=p_run_id FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=p_run_id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','expired'); END IF;
  IF r.status='cancelled' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','already_terminal'); END IF;
  IF r.status IN ('completed','failed','expired') THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','already_terminal'); END IF;
  SELECT epoch_id INTO ep FROM public.v13_ce_epochs WHERE run_id=p_run_id AND closed_at IS NULL FOR UPDATE;
  n:=public.v13_ce_next_attempt(p_run_id);
  INSERT INTO public.v13_ce_operations(operation_id,request_id,run_id,epoch_id,verb,attempt_seq,status,payload,payload_digest)
  VALUES(oid,p_request_id,p_run_id,ep,'cancel',n,'completed',
         jsonb_build_object('actor',p_actor,'request_id',p_request_id),d);
  PERFORM public.v13_append_event(p_run_id,gen_random_uuid(),'cancel/requested',jsonb_build_object('schema_version',1,'scope','session'));
  PERFORM public.v13_append_event(p_run_id,gen_random_uuid(),'ce/cancel_requested',jsonb_build_object(
    'schema_version',1,'actor',p_actor,'request_id',p_request_id,'operation_id',oid));
  UPDATE public.effects SET status='cancelled',fence=fence+1,lease_owner=NULL,lease_until=NULL,error=NULL
   WHERE session_id=p_run_id AND status='ready';
  UPDATE public.v13_ce_operations SET status='closed',completed_at=now()
   WHERE run_id=p_run_id AND status='pending' AND operation_id<>oid;
  UPDATE public.v13_ce_epochs SET closed_at=now() WHERE run_id=p_run_id AND closed_at IS NULL;

  -- Seal the cancellation in the frozen control-plane format.  The existing
  -- closeout helper is used when its strict active-effect/child preconditions
  -- hold; a claimed effect or child run remains independently accountable,
  -- so construct the same guarded seal without cancelling that work.
  IF NOT EXISTS (SELECT 1 FROM public.sessions WHERE parent_session_id=p_run_id)
     AND NOT EXISTS (SELECT 1 FROM public.effects WHERE session_id=p_run_id
                     AND status IN ('ready','claimed') AND kind<>'human')
     AND NOT EXISTS (SELECT 1 FROM public.effects WHERE session_id=p_run_id AND status='unknown')
     AND NOT public.v13_pending_human(p_run_id)
     AND NOT EXISTS (SELECT 1 FROM public.sessions WHERE session_id=p_run_id AND status='blocked_unknown') THEN
    PERFORM public.v13_closeout(p_run_id,'cancelled','cancel',false);
  ELSE
    SELECT coalesce(jsonb_agg(h ORDER BY h),'[]'::jsonb) INTO hashes
      FROM (SELECT DISTINCT a.content_hash AS h FROM public.artifacts a
            JOIN public.effects x ON x.effect_id=a.produced_by
            WHERE x.session_id=p_run_id AND x.status='succeeded'
              AND a.content_hash ~ '^[0-9a-f]{64}$') q;
    SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) INTO repairs
      FROM (SELECT DISTINCT ev.source_effect_id::text AS x FROM public.events ev
            WHERE ev.session_id=p_run_id AND ev.type='repair/required' AND ev.source_effect_id IS NOT NULL) q;
    SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) INTO replans
      FROM (SELECT DISTINCT ev.source_effect_id::text AS x FROM public.events ev
            WHERE ev.session_id=p_run_id AND ev.type='replan/required' AND ev.source_effect_id IS NOT NULL) q;
    SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) INTO materials
      FROM (SELECT x.effect_id::text AS x FROM public.effects x
            WHERE x.session_id=p_run_id AND x.status='succeeded' AND x.kind='tool'
              AND v13_is_harness_tool(x.tool_name,x.kind)
              AND v13_harness_request_ok(x.request)
              AND (x.result->>'result_kind'='finish'
                   OR (x.result->>'result_kind'='progress' AND NOT EXISTS
                       (SELECT 1 FROM public.events ev WHERE ev.source_effect_id=x.effect_id
                        AND ev.type IN ('repair/required','replan/required'))))
              AND NOT EXISTS (SELECT 1 FROM public.events ev WHERE ev.source_effect_id=x.effect_id
                              AND ev.type='turn/material_spent')) q;
    SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) INTO wakes
      FROM (SELECT x.effect_id::text AS x FROM public.effects x
            WHERE x.session_id=p_run_id AND x.status='succeeded' AND x.kind='tool'
              AND v13_is_harness_tool(x.tool_name,x.kind)
              AND x.result->>'result_kind'='wait'
              AND x.result->>'wait_reason' IN ('evidence','quota')
              AND NOT EXISTS (SELECT 1 FROM public.events ev WHERE ev.source_effect_id=x.effect_id
                              AND ev.type='wake/satisfied')) q;
    SELECT coalesce(jsonb_agg(x ORDER BY x),'[]'::jsonb) INTO approvals
      FROM (SELECT x.effect_id::text AS x FROM public.effects x
            WHERE x.session_id=p_run_id AND x.status='succeeded' AND x.kind='tool'
              AND v13_is_harness_tool(x.tool_name,x.kind)
              AND x.result->>'result_kind'='wait' AND x.result->>'wait_reason'='approval'
              AND NOT EXISTS (SELECT 1 FROM public.effects h WHERE h.session_id=p_run_id
                              AND h.kind='human' AND h.status='succeeded'
                              AND h.request->>'interaction_ref'=x.result->>'interaction_id')) q;
    SELECT coalesce(jsonb_agg(jsonb_build_object('session_id',session_id,'status',status)
                              ORDER BY session_id),'[]'::jsonb) INTO children
      FROM public.sessions WHERE parent_session_id=p_run_id;
    PERFORM public.v13_append_event(p_run_id,gen_random_uuid(),'turn/end',
      jsonb_build_object('delivered',false,'reason','cancel'));
    seal:=jsonb_build_object(
      'schema_version',1,'origin_user_seq',public.v13_last_user_seq(p_run_id),
      'spent',jsonb_build_object('turn_no',(SELECT turn_no FROM public.sessions WHERE session_id=p_run_id),
        'cycle_no',public.v13_cycle_no(p_run_id),
        'max_cycles',(public.v13_policy('turn_budget')->>'max_cycles')::int,
        'material_count',(SELECT count(*) FROM public.events WHERE session_id=p_run_id
                          AND type='turn/material_spent')),
      'produced_hashes',coalesce(hashes,'[]'::jsonb),'children',coalesce(children,'[]'::jsonb),
      'unconsumed',jsonb_build_object('repair_effect_ids',coalesce(repairs,'[]'::jsonb),
        'replan_effect_ids',coalesce(replans,'[]'::jsonb),
        'material_effect_ids',coalesce(materials,'[]'::jsonb),
        'wake_pending_effect_ids',coalesce(wakes,'[]'::jsonb),
        'approval_pending_effect_ids',coalesce(approvals,'[]'::jsonb)),
      'state_hash',public.v13_state_hash(p_run_id),'turn_end_reason','cancel');
    PERFORM public.v13_append_event(p_run_id,gen_random_uuid(),'session/cancelled',seal);
  END IF;
  UPDATE public.sessions SET status='cancelled' WHERE session_id=p_run_id;
  UPDATE public.v13_ce_runs SET status='cancelled',interaction=NULL,driving_operation_id=NULL,revision=revision+1,updated_at=now()
   WHERE run_id=p_run_id;
  UPDATE public.v13_ce_snapshots SET status='cancelled',interaction=NULL,interaction_effect_id=NULL,
      revision=revision+1,updated_at=now(),last_operation_id=oid WHERE run_id=p_run_id;
  out:=jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run_id,'operation_id',oid,'status','cancelled');
  UPDATE public.v13_ce_operations SET admission_result=out,result=out,completed_at=now() WHERE operation_id=oid;
  PERFORM public.v13_ce_wake(p_run_id,r.current_epoch_ordinal,'cancelled');
  RETURN out;
END $$;

CREATE FUNCTION public.v13_ce_run_steer(p_actor uuid, p_run_id uuid, p_message text, p_request_id text,
                                        p_expected_epoch bigint)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r public.v13_ce_runs; ep uuid; oid uuid:=gen_random_uuid(); n bigint; d text; out jsonb; old public.v13_ce_operations;
        h public.effects; hres jsonb; heffect uuid; hstatus text; follow uuid; claim jsonb; channel text;
        wake_epoch bigint;
BEGIN
  IF p_request_id IS NULL OR btrim(p_request_id)='' OR p_message IS NULL OR btrim(p_message)='' OR octet_length(p_message)>65536
     OR p_expected_epoch IS NULL OR p_expected_epoch < 1 THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_args');
  END IF;
  IF NOT public.v13_ce_write_ok(p_actor,p_run_id) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized'); END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('v13-ce-request:'||p_request_id,0));
  d:=public.v13_ce_json_digest('steer',p_actor,p_run_id,jsonb_build_object('message',p_message,'epoch',p_expected_epoch));
  SELECT * INTO old FROM public.v13_ce_operations WHERE request_id=p_request_id;
  IF FOUND THEN RETURN public.v13_ce_request_replay(p_request_id,d); END IF;
  PERFORM 1 FROM public.sessions WHERE session_id=p_run_id FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=p_run_id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','expired'); END IF;
  wake_epoch:=r.current_epoch_ordinal;
  IF r.current_epoch_ordinal IS DISTINCT FROM p_expected_epoch THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','stale_epoch'); END IF;
  IF public.v13_ce_unknown(p_run_id) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unknown_wall'); END IF;
  IF r.interaction IS NOT NULL AND lower(coalesce(r.interaction->>'kind','')) NOT IN ('instruction','ce_instruction') THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','use_respond');
  END IF;
  IF r.status IN ('completed','failed','cancelled','expired') THEN
    UPDATE public.v13_ce_epochs SET closed_at=now() WHERE run_id=p_run_id AND closed_at IS NULL;
    INSERT INTO public.v13_ce_epochs(run_id,ordinal,continuity_generation,registration_generation,transition_kind)
    VALUES(p_run_id,r.current_epoch_ordinal+1,r.continuity_generation,r.registration_generation,'steering') RETURNING epoch_id INTO ep;
    UPDATE public.v13_ce_operations SET status='closed',completed_at=now() WHERE run_id=p_run_id AND status='pending';
    UPDATE public.effects SET status='cancelled',fence=fence+1,lease_owner=NULL,lease_until=NULL,error=NULL
     WHERE session_id=p_run_id AND status='ready';
    UPDATE public.v13_ce_runs SET current_epoch_ordinal=r.current_epoch_ordinal+1,status='running',interaction=NULL,
      failure_reason=NULL,driving_operation_id=NULL WHERE run_id=p_run_id;
    r.current_epoch_ordinal:=r.current_epoch_ordinal+1;
  ELSE
    SELECT epoch_id INTO ep FROM public.v13_ce_epochs WHERE run_id=p_run_id AND ordinal=r.current_epoch_ordinal AND closed_at IS NULL FOR UPDATE;
  END IF;
  IF r.interaction IS NOT NULL THEN
    channel:=lower(coalesce(r.interaction->>'channel','human'));
    IF channel='human' THEN
      SELECT * INTO h FROM public.effects WHERE effect_id=(SELECT interaction_effect_id FROM public.v13_ce_snapshots WHERE run_id=p_run_id)
        FOR UPDATE;
      IF NOT FOUND OR h.kind<>'human' OR h.status<>'ready' OR h.request->>'interaction_ref' IS DISTINCT FROM r.interaction->>'id' THEN
        RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_pending');
      END IF;
      claim:=public.v13_ce_claim_bound_effect(p_run_id,h.effect_id,'ce-instruction',60000);
      IF claim->>'ok' <> 'true' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_pending'); END IF;
      hres:=jsonb_build_object('schema_version',1,'interaction_ref',h.request->>'interaction_ref','response',p_message);
      hstatus:=public.v13_complete(NULL::uuid,h.effect_id,(claim->>'attempt_no')::integer,(claim->>'fence')::bigint,'succeeded',hres);
    ELSIF channel='ce' THEN
      hres:=jsonb_build_object('schema_version',1,'interaction_ref',r.interaction->>'id','response',p_message);
      hstatus:='accepted';
    ELSE
      RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_pending');
    END IF;
  END IF;
  n:=public.v13_ce_next_attempt(p_run_id);
  INSERT INTO public.v13_ce_operations(operation_id,request_id,run_id,epoch_id,verb,attempt_seq,status,input_message,payload,payload_digest)
  VALUES(oid,p_request_id,p_run_id,ep,'steer',n,'pending',p_message,
         jsonb_build_object('operation_id',oid,'message',p_message),d);
  PERFORM public.v13_append_event(p_run_id,gen_random_uuid(),'user/message',jsonb_build_object('message',p_message));
  IF r.interaction IS NOT NULL THEN
    UPDATE public.v13_ce_operations SET status='completed',effect_id=NULL,result=jsonb_build_object('outcome',hstatus,'payload',hres),completed_at=now()
      WHERE operation_id=oid;
    follow:=public.v13_ce_followup(p_run_id,ep,oid,jsonb_build_object('message',p_message,'source','instruction'));
  END IF;
  UPDATE public.v13_ce_runs SET status='running',interaction=NULL,failure_reason=NULL,
      driving_operation_id=CASE WHEN follow IS NULL THEN oid ELSE follow END,
      revision=revision+1,updated_at=now() WHERE run_id=p_run_id;
  UPDATE public.v13_ce_snapshots SET epoch_ordinal=r.current_epoch_ordinal,status='running',interaction=NULL,interaction_effect_id=NULL,
      assistant_text=CASE WHEN r.status IN ('completed','failed','cancelled','expired') THEN NULL ELSE assistant_text END,
      failure_reason=NULL,revision=revision+1,updated_at=now(),last_operation_id=oid WHERE run_id=p_run_id;
  UPDATE public.sessions SET status='ready' WHERE session_id=p_run_id;
  PERFORM public.v13_ce_promote_next_effect(p_run_id);
  PERFORM public.v13_ce_wake(p_run_id,wake_epoch,'steering_requested',p_message,NULL,p_actor);
  out:=jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run_id,'operation_id',oid,
      'epoch_ordinal',r.current_epoch_ordinal,'queued',true);
  UPDATE public.v13_ce_operations SET admission_result=out WHERE operation_id=oid AND admission_result IS NULL;
  RETURN out;
END $$;

CREATE FUNCTION public.v13_ce_run_respond(p_actor uuid, p_run_id uuid, p_interaction_id text,
                                          p_response jsonb, p_request_id text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r public.v13_ce_runs; ep uuid; oid uuid:=gen_random_uuid(); n bigint; d text; out jsonb; old public.v13_ce_operations;
        h public.effects; hres jsonb; hstatus text; follow uuid; claim jsonb; k text; count_one int:=0;
BEGIN
  IF p_request_id IS NULL OR btrim(p_request_id)='' OR p_interaction_id IS NULL OR p_response IS NULL
     OR jsonb_typeof(p_response)<>'object' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_args'); END IF;
  IF NOT p_response ? 'schema_version' OR jsonb_typeof(p_response->'schema_version')<>'number'
     OR (p_response->>'schema_version')::numeric <> 1
     OR p_interaction_id !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_args');
  END IF;
  FOR k IN SELECT jsonb_object_keys(p_response) LOOP
    IF k NOT IN ('schema_version','response','answers','skip') THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unsupported_response'); END IF;
  END LOOP;
  IF p_response ? 'response' THEN count_one:=count_one+1; END IF;
  IF p_response ? 'answers' THEN count_one:=count_one+1; END IF;
  IF p_response ? 'skip' THEN count_one:=count_one+1; END IF;
  IF count_one<>1
     OR ((p_response ? 'response') AND NOT COALESCE(
           jsonb_typeof(p_response->'response') IN ('string','number','boolean')
           AND (jsonb_typeof(p_response->'response') <> 'string'
                OR btrim(p_response->>'response') <> ''), false))
     OR ((p_response ? 'answers') AND NOT COALESCE(
           jsonb_typeof(p_response->'answers') = 'object'
           AND p_response->'answers' <> '{}'::jsonb, false))
     OR ((p_response ? 'skip') AND p_response->'skip' IS DISTINCT FROM 'true'::jsonb) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unsupported_response');
  END IF;
  IF NOT public.v13_ce_write_ok(p_actor,p_run_id) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized'); END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('v13-ce-request:'||p_request_id,0));
  d:=public.v13_ce_json_digest('respond',p_actor,p_run_id,jsonb_build_object('interaction_id',p_interaction_id,'response',p_response));
  SELECT * INTO old FROM public.v13_ce_operations WHERE request_id=p_request_id;
  IF FOUND THEN RETURN public.v13_ce_request_replay(p_request_id,d); END IF;
  PERFORM 1 FROM public.sessions WHERE session_id=p_run_id FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=p_run_id FOR UPDATE;
  IF NOT FOUND OR r.interaction->>'id' IS DISTINCT FROM p_interaction_id THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_mismatch');
  END IF;
  IF public.v13_ce_unknown(p_run_id) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unknown_wall'); END IF;
  SELECT epoch_id INTO ep FROM public.v13_ce_epochs WHERE run_id=p_run_id AND ordinal=r.current_epoch_ordinal AND closed_at IS NULL FOR UPDATE;
  SELECT * INTO h FROM public.effects WHERE effect_id=(SELECT interaction_effect_id FROM public.v13_ce_snapshots WHERE run_id=p_run_id)
    FOR UPDATE;
  IF r.interaction->>'channel' IS NULL OR lower(r.interaction->>'channel')='human' THEN
    IF NOT FOUND OR h.kind<>'human' OR h.status<>'ready' OR h.request->>'interaction_ref' IS DISTINCT FROM p_interaction_id THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_pending'); END IF;
    claim:=public.v13_ce_claim_bound_effect(p_run_id,h.effect_id,'ce-respond',60000);
    IF claim->>'ok' <> 'true' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_pending'); END IF;
    hres:=jsonb_build_object('schema_version',1,'interaction_ref',p_interaction_id) || p_response - 'schema_version';
    hstatus:=public.v13_complete(NULL::uuid,h.effect_id,(claim->>'attempt_no')::integer,(claim->>'fence')::bigint,'succeeded',hres);
  END IF;
  n:=public.v13_ce_next_attempt(p_run_id);
  INSERT INTO public.v13_ce_operations(operation_id,request_id,run_id,epoch_id,verb,attempt_seq,status,payload,payload_digest,effect_id,result,completed_at)
  VALUES(oid,p_request_id,p_run_id,ep,'respond',n,'completed',p_response,d,
         CASE WHEN r.interaction->>'channel' IS NULL OR lower(r.interaction->>'channel')='human' THEN h.effect_id ELSE NULL END,
         CASE WHEN r.interaction->>'channel' IS NULL OR lower(r.interaction->>'channel')='human'
              THEN jsonb_build_object('outcome',hstatus,'payload',hres)
              ELSE jsonb_build_object('outcome','accepted','payload',p_response) END,
         now());
  UPDATE public.v13_ce_runs SET interaction=NULL,status='running',revision=revision+1,updated_at=now() WHERE run_id=p_run_id;
  UPDATE public.sessions SET status='ready' WHERE session_id=p_run_id;
  UPDATE public.v13_ce_snapshots SET interaction=NULL,interaction_effect_id=NULL,status='running',revision=revision+1,
      updated_at=now(),last_operation_id=oid WHERE run_id=p_run_id;
  follow:=public.v13_ce_followup(p_run_id,ep,oid,jsonb_build_object('source','respond','response',p_response));
  PERFORM public.v13_ce_promote_next_effect(p_run_id);
  PERFORM public.v13_ce_wake(p_run_id,r.current_epoch_ordinal,'snapshot');
  out:=jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run_id,'operation_id',oid,'queued',true,
                          'status','running','followup_operation_id',follow);
  UPDATE public.v13_ce_operations SET admission_result=out WHERE operation_id=oid;
  RETURN out;
END $$;

CREATE FUNCTION public.v13_ce_admit_operation(p_actor uuid, p_run_id uuid, p_epoch bigint, p_verb text,
                                              p_payload jsonb, p_request_id text, p_driving_operation uuid)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE r public.v13_ce_runs; e public.v13_ce_epochs; oid uuid:=gen_random_uuid(); n bigint; d text; in_payload jsonb; out jsonb; old public.v13_ce_operations; eff uuid;
        tool_reason text; k text; op_status text;
BEGIN
  IF p_request_id IS NULL OR btrim(p_request_id)='' OR p_verb NOT IN ('admit_turn','admit_tool')
     OR p_payload IS NULL OR jsonb_typeof(p_payload)<>'object'
     OR (p_payload IS NOT NULL AND octet_length(p_payload::text)>1048576) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_args');
  END IF;
  IF NOT public.v13_ce_write_ok(p_actor,p_run_id) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','unauthorized'); END IF;
  in_payload:=p_payload || jsonb_build_object('epoch',p_epoch,'driving_operation_id',p_driving_operation);
  d:=public.v13_ce_json_digest(p_verb,p_actor,p_run_id,in_payload);
  PERFORM pg_advisory_xact_lock(hashtextextended('v13-ce-request:'||p_request_id,0));
  SELECT * INTO old FROM public.v13_ce_operations WHERE request_id=p_request_id;
  IF FOUND THEN RETURN public.v13_ce_request_replay(p_request_id,d); END IF;
  PERFORM 1 FROM public.sessions WHERE session_id=p_run_id FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=p_run_id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','expired'); END IF;
  SELECT * INTO e FROM public.v13_ce_epochs WHERE run_id=p_run_id AND ordinal=p_epoch AND closed_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','stale_epoch'); END IF;
  IF r.status<>'running' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','run_not_running'); END IF;
  IF r.driving_operation_id IS DISTINCT FROM p_driving_operation THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','stale_driving'); END IF;
  IF public.v13_ce_unknown(p_run_id) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','unknown_wall'); END IF;
  IF p_verb='admit_turn' THEN
    FOR k IN SELECT jsonb_object_keys(p_payload) LOOP
      IF k <> 'after_operation_id' THEN
        RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_args');
      END IF;
    END LOOP;
    IF p_payload ? 'after_operation_id'
       AND (jsonb_typeof(p_payload->'after_operation_id')<>'string'
            OR p_payload->>'after_operation_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_args');
    END IF;
  ELSIF p_verb='admit_tool' THEN
    FOR k IN SELECT jsonb_object_keys(p_payload) LOOP
      IF k NOT IN ('tool','params','source_operation_id','tool_call_index','tool_call_id') THEN
        RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_args');
      END IF;
    END LOOP;
    IF NOT (p_payload ? 'tool') OR jsonb_typeof(p_payload->'tool')<>'string' OR btrim(p_payload->>'tool')=''
       OR NOT (p_payload ? 'params') OR jsonb_typeof(p_payload->'params')<>'object'
       OR NOT (p_payload ? 'source_operation_id')
       OR NOT (p_payload ? 'tool_call_index') THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_args');
    END IF;
    IF jsonb_typeof(p_payload->'source_operation_id')<>'string'
       OR p_payload->>'source_operation_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR NOT public.v13_json_int_ok(p_payload->'tool_call_index',9223372036854775807::numeric)
       OR ((p_payload ? 'tool_call_id') AND
           (jsonb_typeof(p_payload->'tool_call_id')<>'string'
            OR btrim(p_payload->>'tool_call_id')=''
            OR char_length(p_payload->>'tool_call_id')>128
            OR p_payload->>'tool_call_id' !~ '^[A-Za-z0-9_./:-]+$')) THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_args');
    END IF;
    IF (p_payload->>'source_operation_id')::uuid IS DISTINCT FROM p_driving_operation THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason','invalid_tool_source');
    END IF;
    tool_reason:=public.v13_ce_tool_check(p_payload->>'tool',p_payload->'params');
    IF tool_reason IS NOT NULL THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'disposition','rejected','reason',tool_reason);
    END IF;
  END IF;
  n:=public.v13_ce_next_attempt(p_run_id);
  INSERT INTO public.v13_ce_operations(operation_id,request_id,run_id,epoch_id,verb,attempt_seq,status,payload,payload_digest,admission_result)
  VALUES(oid,p_request_id,p_run_id,e.epoch_id,p_verb,n,'pending',p_payload || jsonb_build_object('operation_id',oid),d,NULL);
  IF p_verb='admit_turn' THEN
    UPDATE public.v13_ce_runs SET driving_operation_id=oid WHERE run_id=p_run_id;
  END IF;
  eff:=public.v13_ce_promote_next_effect(p_run_id);
  SELECT effect_id,status INTO eff,op_status FROM public.v13_ce_operations WHERE operation_id=oid;
  out:=jsonb_build_object('schema_version',1,'ok',true,'queued',eff IS NULL,'run_id',p_run_id,
      'operation_id',oid,'request_id',p_request_id,'epoch_ordinal',p_epoch,'effect_id',eff,
      'attempt_no',NULL,'fence',NULL,'status',op_status);
  UPDATE public.v13_ce_operations SET admission_result=out WHERE operation_id=oid;
  RETURN out;
END $$;

CREATE FUNCTION public.v13_ce_claim_effect(p_actor uuid, p_operation_id uuid, p_worker text, p_lease_ms integer)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE o public.v13_ce_operations; r public.v13_ce_runs; e public.effects; sid uuid; ep public.v13_ce_epochs;
        op_epoch uuid; op_effect uuid;
BEGIN
  IF p_worker IS NULL OR btrim(p_worker)='' OR p_lease_ms IS NULL OR p_lease_ms<1 OR NOT public.v13_ce_is_route() THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized');
  END IF;
  SELECT run_id,epoch_id,effect_id INTO sid,op_epoch,op_effect
    FROM public.v13_ce_operations WHERE operation_id=p_operation_id;
  IF sid IS NULL OR NOT public.v13_ce_write_ok(p_actor,sid) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized'); END IF;
  PERFORM 1 FROM public.sessions WHERE session_id=sid FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=sid FOR UPDATE;
  SELECT * INTO ep FROM public.v13_ce_epochs WHERE epoch_id=op_epoch FOR UPDATE;
  SELECT * INTO o FROM public.v13_ce_operations WHERE operation_id=p_operation_id FOR UPDATE;
  IF NOT FOUND OR o.effect_id IS NULL OR o.status<>'pending' OR r.status<>'running' OR ep.closed_at IS NOT NULL THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','not_claimable');
  END IF;
  SELECT * INTO e FROM public.effects WHERE effect_id=o.effect_id FOR UPDATE;
  IF NOT FOUND OR e.kind='human' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','not_claimable'); END IF;
  IF public.v13_ce_claim_bound_effect(sid,e.effect_id,p_worker,p_lease_ms)->>'ok' <> 'true' THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','not_claimable');
  END IF;
  SELECT * INTO e FROM public.effects WHERE effect_id=o.effect_id;
  RETURN jsonb_build_object('schema_version',1,'ok',true,'operation_id',o.operation_id,'effect_id',e.effect_id,
      'attempt_no',e.attempt_no,'fence',e.fence,'request',e.request,'idempotency_key',e.idempotency_key,
      'receipt_id','ce:'||o.operation_id::text||':receipt');
END $$;

CREATE FUNCTION public.v13_ce_accept_receipt(p_actor uuid, p_operation_id uuid, p_request_id text,
                                             p_status text, p_result jsonb)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE o public.v13_ce_operations; r public.v13_ce_runs; ep public.v13_ce_epochs; e public.effects; sid uuid;
        op_epoch uuid; expected text; rd text; outcome text; complete_outcome text; eff_outcome text; resp jsonb;
        settlement_result jsonb; settled boolean:=false;
BEGIN
  SELECT run_id INTO sid FROM public.v13_ce_operations WHERE operation_id=p_operation_id;
  IF sid IS NULL OR NOT public.v13_ce_write_ok(p_actor,sid) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized'); END IF;
  expected:='ce:'||p_operation_id::text||':receipt';
  IF p_request_id IS DISTINCT FROM expected THEN
    PERFORM 1 FROM public.sessions WHERE session_id=sid FOR UPDATE;
    PERFORM public.v13_append_event(sid,gen_random_uuid(),'ce/receipt_request_mismatch',jsonb_build_object(
      'operation_id',p_operation_id,'request_id',p_request_id,'actor',p_actor));
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','receipt_request_mismatch','expected_request_id',expected);
  END IF;
  IF p_status IS NULL OR p_status NOT IN ('succeeded','failed','unknown')
     OR p_result IS NULL OR jsonb_typeof(p_result)<>'object'
     OR octet_length(p_result::text)>1048576
     OR public.v13_json_keys(p_result) IS DISTINCT FROM ARRAY['attempt_no','effect_id','effect_result','fence']
     OR jsonb_typeof(p_result->'effect_id')<>'string'
     OR p_result->>'effect_id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
     OR NOT public.v13_json_int_ok(p_result->'attempt_no',2147483647)
     OR NOT public.v13_json_int_ok(p_result->'fence',9223372036854775807::numeric)
     OR jsonb_typeof(p_result->'effect_result')<>'object'
     OR octet_length((p_result->'effect_result')::text)>1048576 THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_receipt');
  END IF;
  rd:=encode(digest(jsonb_build_object('status',p_status,'payload',p_result)::text,'sha256'),'hex');
  PERFORM 1 FROM public.sessions WHERE session_id=sid FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=sid FOR UPDATE;
  SELECT epoch_id INTO op_epoch FROM public.v13_ce_operations WHERE operation_id=p_operation_id;
  SELECT * INTO ep FROM public.v13_ce_epochs WHERE epoch_id=op_epoch FOR UPDATE;
  SELECT * INTO o FROM public.v13_ce_operations WHERE operation_id=p_operation_id FOR UPDATE;
  IF NOT FOUND OR ep.epoch_id IS NULL THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_receipt');
  END IF;
  SELECT * INTO e FROM public.effects WHERE effect_id=o.effect_id FOR UPDATE;
  IF o.result IS NOT NULL AND o.result->>'receipt_id'=p_request_id THEN
    IF o.result->>'receipt_digest'=rd THEN
      RETURN (o.result->'response') || jsonb_build_object(
        'replayed',true,
        'replay_of_receipt_id',o.result->>'receipt_id',
        'replay_of_receipt_digest',o.result->>'receipt_digest',
        'original_outcome',o.result->>'outcome');
    END IF;
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','receipt_conflict');
  END IF;
  IF o.effect_id IS NULL OR e.effect_id IS NULL THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_receipt');
  END IF;
  IF e.kind='human' OR p_result->>'effect_id' IS NULL
     OR p_result->>'effect_id' IS DISTINCT FROM e.effect_id::text
     OR p_result->>'attempt_no' IS NULL OR (p_result->>'attempt_no') !~ '^[0-9]{1,9}$'
     OR p_result->>'fence' IS NULL OR (p_result->>'fence') !~ '^[0-9]{1,18}$' THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_receipt');
  END IF;
  IF (p_result->>'attempt_no')::integer IS DISTINCT FROM e.attempt_no
     OR (p_result->>'fence')::bigint IS DISTINCT FROM e.fence THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'outcome','stale_claim',
      'operation_id',o.operation_id,'effect_id',o.effect_id,'revision',r.revision);
  END IF;
  IF e.status='claimed'
     AND (p_result->>'effect_id')=e.effect_id::text THEN
    BEGIN
      complete_outcome:=public.v13_complete(NULL::uuid,e.effect_id,e.attempt_no,e.fence,p_status,p_result->'effect_result');
      settled:=complete_outcome IN ('accepted','replay');
    EXCEPTION WHEN SQLSTATE 'P0001' THEN
      IF SQLERRM LIKE 'v13: logical_turn_id required'
         OR SQLERRM LIKE 'v13: human channel%'
         OR SQLERRM LIKE 'v13: complete requires non-NULL%'
         OR SQLERRM LIKE 'v13: bad outcome %'
         OR SQLERRM LIKE 'v13: tool_calls shape%'
         OR SQLERRM LIKE 'v13: unknown effect %' THEN
        complete_outcome:='bridge_rejected';
        settled:=false;
      ELSE
        RAISE;
      END IF;
    END;
    SELECT status INTO eff_outcome FROM public.effects WHERE effect_id=e.effect_id;
    outcome:=CASE WHEN complete_outcome='accepted' THEN 'accepted'
                  WHEN complete_outcome='replay' THEN 'replay'
                  WHEN complete_outcome='stale' THEN 'stale_claim'
                  WHEN complete_outcome='bridge_rejected' THEN 'bridge_rejected'
                  ELSE coalesce(complete_outcome,'stale_claim') END;
  ELSE
    outcome:=CASE WHEN e.status='unknown' THEN 'unknown_wall'
                  WHEN e.status IN ('succeeded','failed','cancelled') THEN 'replay'
                  ELSE 'stale_claim' END;
    eff_outcome:=e.status;
  END IF;
  IF outcome='stale_claim' THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'outcome','stale_claim','operation_id',o.operation_id,
      'effect_id',o.effect_id,'revision',r.revision);
  END IF;
  IF o.status='pending' THEN
    IF outcome='bridge_rejected' THEN
      UPDATE public.v13_ce_operations SET status='archived',completed_at=now() WHERE operation_id=o.operation_id;
      o.status:='archived';
    ELSIF ep.closed_at IS NOT NULL
       OR o.owner_generation<>r.owner_generation
       OR o.registration_generation<>r.registration_generation
       OR (o.verb IN ('start','steer','admit_turn','respond')
       AND r.driving_operation_id IS DISTINCT FROM o.operation_id) THEN
      UPDATE public.v13_ce_operations SET status='archived',completed_at=now() WHERE operation_id=o.operation_id;
      o.status:='archived';
    ELSIF settled AND outcome IN ('accepted','replay') THEN
      UPDATE public.v13_ce_operations SET status='completed',completed_at=now() WHERE operation_id=o.operation_id;
      o.status:='completed';
    END IF;
  END IF;
  resp:=jsonb_build_object('schema_version',1,'ok',settled AND outcome IN ('accepted','replay') AND o.status NOT IN ('closed','archived'),'outcome',
      CASE WHEN o.status IN ('closed','archived') AND outcome IN ('accepted','replay') THEN 'archived_stale' ELSE outcome END,
      'operation_id',o.operation_id,'effect_id',o.effect_id,'effect_outcome',eff_outcome,
      'revision',(SELECT revision FROM public.v13_ce_runs WHERE run_id=sid),
      'receipt_id',p_request_id,'receipt_digest',rd,'replayed',false);
  UPDATE public.v13_ce_operations SET result=jsonb_build_object('receipt_id',p_request_id,'receipt_digest',rd,
      'outcome',outcome,'payload',p_result,'response',resp) WHERE operation_id=o.operation_id;
  IF outcome='bridge_rejected' THEN
    PERFORM public.v13_append_event(sid,gen_random_uuid(),'ce/receipt_bridge_rejected',
      jsonb_build_object('operation_id',o.operation_id,'effect_id',o.effect_id,'status',p_status));
  END IF;
  IF settled AND outcome IN ('accepted','replay') AND r.status='running' THEN PERFORM public.v13_ce_promote_next_effect(sid); END IF;
  RETURN resp;
END $$;

CREATE FUNCTION public.v13_ce_publish_snapshot(p_actor uuid, p_operation_id uuid, p_request_id text,
                                               p_expected_revision bigint, p_snapshot jsonb)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE o public.v13_ce_operations; r public.v13_ce_runs; ep public.v13_ce_epochs; e public.effects; sid uuid;
        op_epoch uuid; st text; new_rev bigint; pub jsonb; pd text; existing jsonb; pub_interaction jsonb; he uuid; hreq jsonb;
BEGIN
  IF p_request_id IS NULL OR btrim(p_request_id)='' OR p_expected_revision IS NULL OR p_expected_revision<1
     OR p_snapshot IS NULL OR jsonb_typeof(p_snapshot)<>'object' OR octet_length(p_snapshot::text)>1048576 THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_args');
  END IF;
  sid:=(SELECT run_id FROM public.v13_ce_operations WHERE operation_id=p_operation_id);
  IF sid IS NULL OR NOT public.v13_ce_write_ok(p_actor,sid) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized'); END IF;
  pd:=encode(digest(jsonb_build_object('expected_revision',p_expected_revision,'snapshot',p_snapshot)::text,'sha256'),'hex');
  PERFORM 1 FROM public.sessions WHERE session_id=sid FOR UPDATE;
  SELECT * INTO r FROM public.v13_ce_runs WHERE run_id=sid FOR UPDATE;
  SELECT epoch_id INTO op_epoch FROM public.v13_ce_operations WHERE operation_id=p_operation_id;
  SELECT * INTO ep FROM public.v13_ce_epochs WHERE epoch_id=op_epoch FOR UPDATE;
  SELECT * INTO o FROM public.v13_ce_operations WHERE operation_id=p_operation_id FOR UPDATE;
  IF NOT FOUND THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','expired'); END IF;
  IF o.owner_generation<>r.owner_generation OR o.registration_generation<>r.registration_generation THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','expired');
  END IF;
  existing:=o.publications->p_request_id;
  IF existing IS NOT NULL THEN
    IF existing->>'digest'=pd THEN RETURN existing->'response'; END IF;
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','request_id_conflict');
  END IF;
  IF o.status NOT IN ('completed','pending') THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','archived_stale'); END IF;
  SELECT * INTO ep FROM public.v13_ce_epochs WHERE epoch_id=o.epoch_id FOR UPDATE;
  IF r.interaction IS NOT NULL THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','interaction_pending'); END IF;
  IF r.revision<>p_expected_revision THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','revision_conflict'); END IF;
  IF r.current_epoch_ordinal<>(SELECT ordinal FROM public.v13_ce_epochs WHERE epoch_id=o.epoch_id)
     OR r.driving_operation_id IS DISTINCT FROM o.operation_id THEN
    IF o.status='pending' THEN UPDATE public.v13_ce_operations SET status='archived',completed_at=now() WHERE operation_id=o.operation_id; END IF;
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','archived_stale');
  END IF;
  IF r.status<>'running' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','run_not_running'); END IF;
  IF o.status<>'completed' OR (o.effect_id IS NOT NULL AND NOT EXISTS
      (SELECT 1 FROM public.effects x WHERE x.effect_id=o.effect_id AND x.status IN ('succeeded','failed','cancelled'))) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','pending_work');
  END IF;
  IF o.effect_id IS NOT NULL THEN
    SELECT * INTO e FROM public.effects WHERE effect_id=o.effect_id FOR UPDATE;
    IF e.status IN ('ready','claimed') THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','pending_work'); END IF;
    IF e.status='unknown' THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unknown_wall'); END IF;
  END IF;
  st:=p_snapshot->>'status';
  IF st NOT IN ('running','waiting_for_input','completed','failed') THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_snapshot'); END IF;
  IF st IN ('waiting_for_input','completed','failed') AND EXISTS
      (SELECT 1 FROM public.v13_ce_operations x WHERE x.run_id=sid AND x.status='pending' AND x.operation_id<>o.operation_id) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','pending_work');
  END IF;
  new_rev:=r.revision+1;
  IF st='waiting_for_input' THEN
    pub_interaction:=p_snapshot->'interaction';
    IF pub_interaction IS NULL
       OR NOT COALESCE(jsonb_typeof(pub_interaction) = 'object', false)
       OR NOT (pub_interaction ? 'id')
       OR NOT COALESCE(jsonb_typeof(pub_interaction->'id') = 'string', false)
       OR btrim(COALESCE(pub_interaction->>'id','')) = ''
       OR NOT (pub_interaction ? 'kind')
       OR NOT COALESCE(jsonb_typeof(pub_interaction->'kind') = 'string', false)
       OR btrim(COALESCE(pub_interaction->>'kind','')) = '' THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_interaction');
    END IF;
    IF lower(coalesce(pub_interaction->>'channel','human')) NOT IN ('human','ce') THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_interaction');
    END IF;
    IF pub_interaction->>'id' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
      RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','invalid_interaction');
    END IF;
    IF public.v13_ce_unknown(sid) THEN RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unknown_wall'); END IF;
    IF lower(coalesce(pub_interaction->>'channel','human'))='human' THEN
      hreq:=jsonb_build_object('schema_version',1,'interaction_ref',pub_interaction->>'id','operation_id',o.operation_id);
      he:=public.v13_enqueue_effect(sid,'human',hreq,NULL);
    END IF;
    UPDATE public.v13_ce_runs SET status='waiting_for_input',interaction=pub_interaction,revision=new_rev,updated_at=now(),failure_reason=NULL WHERE run_id=sid;
    UPDATE public.sessions SET status='waiting' WHERE session_id=sid;
    UPDATE public.v13_ce_snapshots SET epoch_ordinal=r.current_epoch_ordinal,status='waiting_for_input',interaction=pub_interaction,
      interaction_effect_id=he,assistant_text=p_snapshot->>'assistant_text',failure_reason=NULL,revision=new_rev,updated_at=now(),last_operation_id=o.operation_id WHERE run_id=sid;
  ELSIF st='running' THEN
    UPDATE public.v13_ce_runs SET status='running',revision=new_rev,updated_at=now(),failure_reason=NULL WHERE run_id=sid;
    UPDATE public.sessions SET status='ready' WHERE session_id=sid;
    UPDATE public.v13_ce_snapshots SET epoch_ordinal=r.current_epoch_ordinal,status='running',interaction=NULL,interaction_effect_id=NULL,
      assistant_text=p_snapshot->>'assistant_text',failure_reason=NULL,revision=new_rev,updated_at=now(),last_operation_id=o.operation_id WHERE run_id=sid;
  ELSE
    UPDATE public.v13_ce_runs SET status=st,interaction=NULL,revision=new_rev,updated_at=now(),failure_reason=p_snapshot->'failure_reason' WHERE run_id=sid;
    UPDATE public.sessions SET status=st WHERE session_id=sid;
    UPDATE public.v13_ce_epochs SET closed_at=now() WHERE epoch_id=o.epoch_id AND closed_at IS NULL;
    UPDATE public.v13_ce_snapshots SET epoch_ordinal=r.current_epoch_ordinal,status=st,interaction=NULL,interaction_effect_id=NULL,
      assistant_text=p_snapshot->>'assistant_text',failure_reason=p_snapshot->'failure_reason',revision=new_rev,updated_at=now(),last_operation_id=o.operation_id WHERE run_id=sid;
  END IF;
  pub:=jsonb_build_object('schema_version',1,'ok',true,'run_id',sid,'operation_id',o.operation_id,'status',st,'revision',new_rev);
  UPDATE public.v13_ce_operations SET publications=publications || jsonb_build_object(p_request_id,
    jsonb_build_object('digest',pd,'expected_revision',p_expected_revision,'response',pub,'snapshot',p_snapshot)) WHERE operation_id=o.operation_id;
  PERFORM public.v13_ce_wake(sid,r.current_epoch_ordinal,CASE WHEN st IN ('completed','failed') THEN 'terminal' ELSE 'snapshot' END,
                             NULL,CASE WHEN st='waiting_for_input' THEN pub_interaction ELSE NULL END,NULL);
  RETURN pub;
END $$;

CREATE FUNCTION public.v13_ce_discover_work(p_actor uuid, p_run_id uuid)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT CASE WHEN NOT public.v13_ce_write_ok($1,$2) OR NOT EXISTS (SELECT 1 FROM public.v13_ce_runs WHERE run_id=$2)
    THEN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized')
    ELSE (SELECT jsonb_build_object('schema_version',1,'ok',true,'run_id',r.run_id,
      'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,
      'continuity_generation',r.continuity_generation,'revision',r.revision,'status',r.status,
      'current_driving_operation_id',r.driving_operation_id,
      'operations',coalesce((SELECT jsonb_agg(jsonb_build_object('operation_id',o.operation_id,'request_id',o.request_id,
        'verb',o.verb,'attempt_seq',o.attempt_seq,'effect_id',o.effect_id,'effect_status',e.status,
        'queued',o.effect_id IS NULL) ORDER BY o.attempt_seq)
        FROM public.v13_ce_operations o LEFT JOIN public.effects e ON e.effect_id=o.effect_id
        WHERE o.run_id=r.run_id AND o.epoch_id=(SELECT epoch_id FROM public.v13_ce_epochs WHERE run_id=r.run_id AND ordinal=r.current_epoch_ordinal)
          AND o.status='pending'),'[]'::jsonb)) FROM public.v13_ce_runs r WHERE r.run_id=$2)
  END
$$;

CREATE FUNCTION public.v13_ce_requeue_stale()
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE recovery jsonb;
BEGIN
  IF NOT COALESCE(public.v13_ce_is_route(),false) THEN
    RETURN jsonb_build_object('schema_version',1,'ok',false,'reason','unauthorized');
  END IF;
  recovery:=public.v13_requeue_stale();
  RETURN jsonb_build_object('schema_version',1,'ok',true,'recovery',recovery);
END $$;

REVOKE ALL ON public.v13_ce_runs, public.v13_ce_epochs, public.v13_ce_operations,
  public.v13_ce_snapshots, public.v13_ce_wakes FROM PUBLIC, v13_worker, v13_recall, v13_route, v13_resolve;
REVOKE ALL ON SEQUENCE public.v13_ce_wakes_wake_id_seq FROM PUBLIC, v13_worker, v13_recall, v13_route, v13_resolve;
REVOKE ALL ON FUNCTION public.v13_ce_insert_session(uuid,uuid,bigint), public.v13_ce_caller_role(),
  public.v13_ce_is_operator(), public.v13_ce_is_route(), public.v13_ce_read_ok(uuid,uuid),
  public.v13_ce_write_ok(uuid,uuid), public.v13_ce_json_digest(text,uuid,uuid,jsonb),
  public.v13_ce_request_replay(text,text), public.v13_ce_wake(uuid,bigint,text,text,jsonb,uuid),
  public.v13_ce_next_attempt(uuid), public.v13_ce_unknown(uuid), public.v13_ce_tool_schema(text),
  public.v13_ce_tool_check(text,jsonb),
  public.v13_ce_claim_bound_effect(uuid,uuid,text,integer), public.v13_ce_promote_next_effect(uuid), public.v13_ce_followup(uuid,uuid,uuid,jsonb),
  public.v13_ce_requeue_stale()
  FROM PUBLIC, v13_worker, v13_recall, v13_route, v13_resolve;
REVOKE ALL ON FUNCTION public.v13_ce_run_start(uuid,text,text,uuid),
  public.v13_ce_run_poll(uuid,uuid,bigint), public.v13_ce_run_wait_check(uuid,uuid,bigint,bigint,bigint),
  public.v13_ce_run_cancel(uuid,uuid,text), public.v13_ce_run_steer(uuid,uuid,text,text,bigint),
  public.v13_ce_run_respond(uuid,uuid,text,jsonb,text),
  public.v13_ce_admit_operation(uuid,uuid,bigint,text,jsonb,text,uuid),
  public.v13_ce_claim_effect(uuid,uuid,text,integer), public.v13_ce_accept_receipt(uuid,uuid,text,text,jsonb),
  public.v13_ce_publish_snapshot(uuid,uuid,text,bigint,jsonb), public.v13_ce_discover_work(uuid,uuid)
  FROM PUBLIC, v13_worker, v13_recall, v13_route, v13_resolve;
GRANT EXECUTE ON FUNCTION public.v13_ce_run_start(uuid,text,text,uuid),
  public.v13_ce_run_cancel(uuid,uuid,text), public.v13_ce_run_steer(uuid,uuid,text,text,bigint),
  public.v13_ce_run_respond(uuid,uuid,text,jsonb,text), public.v13_ce_admit_operation(uuid,uuid,bigint,text,jsonb,text,uuid),
  public.v13_ce_claim_effect(uuid,uuid,text,integer), public.v13_ce_accept_receipt(uuid,uuid,text,text,jsonb),
  public.v13_ce_publish_snapshot(uuid,uuid,text,bigint,jsonb), public.v13_ce_discover_work(uuid,uuid),
  public.v13_ce_requeue_stale() TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_ce_run_poll(uuid,uuid,bigint),
  public.v13_ce_run_wait_check(uuid,uuid,bigint,bigint,bigint) TO v13_route, v13_recall;

COMMIT;
