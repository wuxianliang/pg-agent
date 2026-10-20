-- W3 CE lifecycle. accept_receipt is the sole worker T2 entry.
-- V9901 is reserved for an explicitly registered business rejection; all other
-- SQL errors (including P0001) escape. Mutation blocks catch only this code.
CREATE FUNCTION v99_core.v99_core_keys(p_value jsonb,p_keys text[])
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
    SELECT CASE WHEN jsonb_typeof(p_value)='object' THEN
        p_value ?& p_keys AND NOT EXISTS(SELECT 1 FROM jsonb_object_keys(p_value) k WHERE NOT k=ANY(p_keys)) ELSE false END
$$;
CREATE FUNCTION v99_core.v99_core_uuid(p_value text)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
    SELECT COALESCE(p_value ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',false)
$$;
CREATE FUNCTION v99_core.v99_core_positive(p_value jsonb,p_max numeric)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
BEGIN
    IF jsonb_typeof(p_value) IS DISTINCT FROM 'number' OR NOT (p_value #>> '{}') ~ '^[0-9]+$' THEN RETURN false; END IF;
    RETURN (p_value #>> '{}')::numeric BETWEEN 1 AND p_max;
END $$;
CREATE FUNCTION v99_core.v99_core_request_id(p_id text)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
    SELECT COALESCE(octet_length(p_id) BETWEEN 1 AND 512 AND btrim(p_id)<>'' AND p_id NOT LIKE 'ce:%',false)
$$;
CREATE FUNCTION v99_core.v99_core_valid_error(p_value jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
    SELECT COALESCE(v99_core.v99_core_keys(p_value,ARRAY['code','message'])
        AND jsonb_typeof(p_value->'code')='string' AND btrim(p_value->>'code')<>''
        AND jsonb_typeof(p_value->'message')='string' AND btrim(p_value->>'message')<>'',false)
$$;
CREATE FUNCTION v99_core.v99_core_valid_response(p_value jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
BEGIN
    IF jsonb_typeof(p_value) IS DISTINCT FROM 'object' OR p_value->'schema_version' IS DISTINCT FROM '1'::jsonb THEN RETURN false; END IF;
    IF v99_core.v99_core_keys(p_value,ARRAY['schema_version','response']) THEN
        RETURN COALESCE(jsonb_typeof(p_value->'response') IN ('number','boolean') OR
            (jsonb_typeof(p_value->'response')='string' AND btrim(p_value->>'response')<>''),false);
    ELSIF v99_core.v99_core_keys(p_value,ARRAY['schema_version','answers']) THEN
        RETURN jsonb_typeof(p_value->'answers')='object' AND p_value->'answers'<>'{}'::jsonb;
    ELSIF v99_core.v99_core_keys(p_value,ARRAY['schema_version','skip']) THEN
        RETURN p_value->'skip'='true'::jsonb;
    END IF;
    RETURN false;
END $$;
-- Static envelope validation is safe before UUID/integer casts.
CREATE FUNCTION v99_core.v99_core_valid_receipt(p_value jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
BEGIN
    IF NOT COALESCE(v99_core.v99_core_keys(p_value,ARRAY['schema_version','status','effect_id','attempt_no','fence','context_revision','catalog_revision','effect_result']),false) THEN RETURN false; END IF;
    RETURN COALESCE(p_value->'schema_version'='1'::jsonb AND octet_length(p_value::text)<=1048576
        AND p_value->>'status' IN ('succeeded','failed','unknown')
        AND jsonb_typeof(p_value->'effect_id')='string' AND v99_core.v99_core_uuid(p_value->>'effect_id')
        AND v99_core.v99_core_positive(p_value->'attempt_no',2147483647)
        AND v99_core.v99_core_positive(p_value->'fence',9223372036854775807)
        AND v99_core.v99_core_positive(p_value->'context_revision',9223372036854775807)
        AND v99_core.v99_core_positive(p_value->'catalog_revision',9223372036854775807)
        AND jsonb_typeof(p_value->'effect_result')='object',false);
END $$;
-- Caller already holds meta SHARE. No tool IO occurs in SQL.
CREATE FUNCTION v99_core.v99_core_tool_error(p_name text,p_args jsonb)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
BEGIN
    IF p_name IS DISTINCT FROM 'spawn_subsession' OR NOT EXISTS(SELECT 1 FROM v99_core.core_tools WHERE name=p_name AND enabled) THEN RETURN 'invalid_tool'; END IF;
    IF NOT COALESCE(v99_core.v99_core_keys(p_args,ARRAY['task']) AND jsonb_typeof(p_args->'task')='string'
        AND length(p_args->>'task') BETWEEN 1 AND 1024,false) THEN RETURN 'invalid_tool_args'; END IF;
    RETURN NULL;
END $$;
CREATE FUNCTION v99_core.v99_core_result_error(p_kind text,p_request jsonb,p_receipt jsonb)
RETURNS text LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE x jsonb:=p_receipt->'effect_result'; item jsonb; ids text[]:='{}'; why text; s text;
BEGIN
    IF p_kind NOT IN ('llm','tool') OR p_kind IS NULL OR jsonb_typeof(x) IS DISTINCT FROM 'object' THEN RETURN 'invalid_receipt'; END IF;
    IF p_receipt->>'status' IN ('failed','unknown') THEN
        IF NOT COALESCE(v99_core.v99_core_keys(x,ARRAY['schema_version','error']) AND x->'schema_version'='1'::jsonb
            AND v99_core.v99_core_valid_error(x->'error'),false) THEN RETURN 'invalid_receipt'; END IF;
        RETURN NULL;
    END IF;
    IF p_kind='tool' THEN
        why:=v99_core.v99_core_tool_error(p_request->>'tool',p_request->'params');
        IF why IS NOT NULL THEN RETURN why; END IF;
        IF NOT COALESCE(v99_core.v99_core_keys(x,ARRAY['schema_version','adapter','simulated','task']) AND x->'schema_version'='1'::jsonb
            AND x->'adapter'='"ce-fake-spawn"'::jsonb AND x->'simulated'='true'::jsonb AND x->'task'=p_request->'params'->'task',false) THEN RETURN 'invalid_receipt'; END IF;
        RETURN NULL;
    END IF;
    IF x->'schema_version' IS DISTINCT FROM '1'::jsonb OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k
        WHERE NOT k=ANY(ARRAY['schema_version','text','tool_calls','ce_status','interaction','failure_reason'])) THEN RETURN 'invalid_receipt'; END IF;
    IF x ? 'text' AND (jsonb_typeof(x->'text') IS DISTINCT FROM 'string' OR btrim(x->>'text')='') THEN RETURN 'invalid_receipt'; END IF;
    IF x ? 'tool_calls' THEN
        IF jsonb_typeof(x->'tool_calls') IS DISTINCT FROM 'array' THEN RETURN 'invalid_receipt'; END IF;
        IF jsonb_array_length(x->'tool_calls')=0 OR x ? 'interaction' OR x ? 'failure_reason'
            OR (x ? 'ce_status' AND x->'ce_status' IS DISTINCT FROM '"running"'::jsonb) THEN RETURN 'invalid_receipt'; END IF;
        -- Validate every shape before checking tool names/params.
        FOR item IN SELECT value FROM jsonb_array_elements(x->'tool_calls') LOOP
            IF NOT COALESCE(v99_core.v99_core_keys(item,ARRAY['id','name','args'])
                AND jsonb_typeof(item->'id')='string' AND btrim(item->>'id')<>''
                AND jsonb_typeof(item->'name')='string' AND jsonb_typeof(item->'args')='object',false) THEN RETURN 'invalid_receipt'; END IF;
            IF item->>'id'=ANY(ids) THEN RETURN 'invalid_receipt'; END IF;
            ids:=array_append(ids,item->>'id');
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(x->'tool_calls') LOOP
            why:=v99_core.v99_core_tool_error(item->>'name',item->'args');
            IF why IS NOT NULL THEN RETURN why; END IF;
        END LOOP;
    ELSE
        IF NOT x ? 'text' OR jsonb_typeof(x->'ce_status') IS DISTINCT FROM 'string' THEN RETURN 'invalid_receipt'; END IF;
        s:=x->>'ce_status';
        IF s NOT IN ('running','waiting_for_input','completed','failed') THEN RETURN 'invalid_receipt'; END IF;
        IF s='waiting_for_input' THEN
            IF NOT x ? 'interaction' OR x->'interaction'='null'::jsonb OR NOT v99_core.v99_core_valid_interaction(x->'interaction') THEN RETURN 'invalid_receipt'; END IF;
        ELSIF x ? 'interaction' THEN RETURN 'invalid_receipt'; END IF;
        IF s='failed' THEN
            IF NOT COALESCE(v99_core.v99_core_valid_error(x->'failure_reason'),false) THEN RETURN 'invalid_receipt'; END IF;
        ELSIF x ? 'failure_reason' THEN RETURN 'invalid_receipt'; END IF;
    END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION v99_core.v99_core_replay(p_id text,p_kind text,p_digest text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE j v99_core.core_requests;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('v99-core-request:'||p_id,0));
    SELECT * INTO j FROM v99_core.core_requests WHERE request_id=p_id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    IF j.kind<>p_kind OR j.request_digest<>p_digest THEN
        RETURN v99_core.v99_core_error(CASE WHEN p_kind='receipt' THEN 'receipt_conflict' ELSE 'request_id_conflict' END);
    END IF;
    RETURN j.response;
END $$;
CREATE FUNCTION v99_core.v99_core_journal(p_id text,p_kind text,p_digest text,p_run uuid,p_response jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
BEGIN
    INSERT INTO v99_core.core_requests(request_id,kind,request_digest,run_id,response) VALUES(p_id,p_kind,p_digest,p_run,p_response);
    RETURN p_response;
END $$;
-- All callers hold lock_work. Existing rows are never locked after meta here.
CREATE FUNCTION v99_core.v99_core_add_operation(p_run uuid,p_id text,p_verb text,p_turn bigint,p_payload jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE n uuid:=gen_random_uuid();
BEGIN
    IF p_payload IS NULL OR octet_length(p_payload::text)>1048576 THEN
        PERFORM v99_core.v99_core_require(v99_core.v99_core_error('invalid_args'));
    END IF;
    INSERT INTO v99_core.core_operations(operation_id,request_id,run_id,epoch_id,verb,turn_ordinal,attempt_seq,status,payload,payload_digest,completed_at)
    SELECT n,p_id,r.run_id,ep.epoch_id,p_verb,p_turn,
        (SELECT coalesce(max(attempt_seq),0)+1 FROM v99_core.core_operations WHERE run_id=p_run),
        CASE WHEN p_verb IN ('admit_turn','admit_tool') THEN 'pending' ELSE 'completed' END,p_payload,v99_core.v99_core_digest(p_payload),
        CASE WHEN p_verb NOT IN ('admit_turn','admit_tool') THEN clock_timestamp() END
    FROM v99_core.core_runs r JOIN v99_core.core_epochs ep ON ep.run_id=r.run_id AND ep.ordinal=r.current_epoch_ordinal WHERE r.run_id=p_run;
    RETURN n;
END $$;
CREATE FUNCTION v99_core.v99_core_admit_turn(p_run uuid,p_key text,p_payload jsonb,p_initial boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE r v99_core.core_runs; op uuid; out_json jsonb;
BEGIN
    UPDATE v99_core.core_runs SET turn_ordinal=turn_ordinal+CASE WHEN p_initial THEN 0 ELSE 1 END WHERE run_id=p_run RETURNING * INTO r;
    op:=v99_core.v99_core_add_operation(p_run,p_key,'admit_turn',r.turn_ordinal,p_payload);
    out_json:=v99_core.v99_core_require(v99_core.v99_core_enqueue_effect(p_run,op,'llm',p_payload,p_key));
    UPDATE v99_core.core_runs SET driving_operation_id=op WHERE run_id=p_run;
    RETURN jsonb_build_object('schema_version',1,'ok',true,'execution_operation_id',op,'effect_id',out_json->'effect_id');
END $$;
CREATE FUNCTION v99_core.v99_core_snapshot_projection(p_run uuid,p_message text DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
    SELECT jsonb_build_object('run_id',s.run_id,'registration_generation',s.registration_generation,'epoch_ordinal',s.epoch_ordinal,
        'turn_ordinal',s.turn_ordinal,'revision',s.revision,'status',s.status,'interaction',s.interaction,
        'assistant_text',s.assistant_text,'failure_reason',s.failure_reason,'last_operation_id',s.last_operation_id,
        'interaction_effect_id',s.interaction_effect_id,'updated_at',s.updated_at,'steering_message',p_message)
    FROM v99_core.core_snapshots s WHERE run_id=p_run
$$;

CREATE FUNCTION v99_core.v99_core_start(p_actor uuid,p_message text,p_request text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE digest text; req jsonb; replay jsonb; run uuid; epoch uuid:=gen_random_uuid(); control uuid; admitted jsonb; out_json jsonb; response jsonb; reject_reason text;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_operator') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_actor IS NOT NULL THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_message IS NULL OR btrim(p_message)='' OR octet_length(p_message)>1000000 OR NOT v99_core.v99_core_request_id(p_request) THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    req:=jsonb_build_object('schema_version',1,'verb','start','actor',p_actor,'message',p_message,'request_id',p_request);
    digest:=v99_core.v99_core_digest(req); replay:=v99_core.v99_core_replay(p_request,'start',digest);
    IF replay IS NOT NULL THEN RETURN replay; END IF;
    BEGIN
        run:=gen_random_uuid();
        INSERT INTO v99_core.core_runs(run_id,status) VALUES(run,'running');
        INSERT INTO v99_core.core_epochs(epoch_id,run_id,ordinal,continuity_generation,registration_generation,transition_kind)
            VALUES(epoch,run,1,1,1,'initial');
        control:=v99_core.v99_core_add_operation(run,p_request,'start',1,jsonb_build_object('message',p_message));
        PERFORM v99_core.v99_core_append_event(run,'user/message',jsonb_build_object('schema_version',1,'text',p_message),NULL,1,1);
        admitted:=v99_core.v99_core_admit_turn(run,'ce:'||control::text||':next_turn',jsonb_build_object('messages',jsonb_build_array(jsonb_build_object('role','user','content',p_message))),true);
        out_json:=v99_core.v99_core_require(v99_core.v99_core_write_snapshot(run,control,'running',NULL,NULL,NULL,NULL,'snapshot',NULL,true));
        response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',run,'operation_id',control,
            'execution_operation_id',(admitted->>'execution_operation_id')::uuid,'effect_id',(admitted->>'effect_id')::uuid,
            'registration_generation',1,'epoch_ordinal',1,'continuity_generation',1,'revision',1,'status','running');
        PERFORM v99_core.v99_core_journal(p_request,'start',digest,run,response);
        RETURN response;
    EXCEPTION WHEN SQLSTATE 'V9901' THEN
        GET STACKED DIAGNOSTICS reject_reason = PG_EXCEPTION_DETAIL;
        IF SQLERRM<>'v99_core_business_rejection' OR NOT v99_core.v99_core_business_reason(reject_reason) THEN RAISE; END IF;
        RETURN v99_core.v99_core_error(reject_reason);
    END;
END $$;
CREATE FUNCTION v99_core.v99_core_poll(p_actor uuid,p_run uuid,p_registration bigint DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE r v99_core.core_runs; allowed boolean;
BEGIN
    allowed:=v99_core.v99_core_has_role('v99_core_operator') OR v99_core.v99_core_has_role('v99_core_reader');
    IF NOT allowed OR p_run IS NULL OR (p_actor IS NOT NULL AND p_actor<>p_run) OR p_registration IS NOT NULL AND p_registration<1 THEN
        RETURN jsonb_build_object('schema_version',1,'ok',true,'reason','expired'); END IF;
    SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run;
    IF NOT FOUND OR (p_registration IS NOT NULL AND p_registration<>r.registration_generation) THEN RETURN jsonb_build_object('schema_version',1,'ok',true,'reason','expired'); END IF;
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',r.run_id,'registration_generation',r.registration_generation,
        'epoch_ordinal',r.current_epoch_ordinal,'continuity_generation',r.continuity_generation,'revision',r.revision,'status',r.status,
        'snapshot',v99_core.v99_core_snapshot_projection(p_run));
END $$;
CREATE FUNCTION v99_core.v99_core_wait_check(p_actor uuid,p_run uuid,p_registration bigint,p_epoch bigint,p_after bigint DEFAULT 0)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE r v99_core.core_runs; s v99_core.core_snapshots; w v99_core.core_wakes; maxwake bigint:=0; reason text:='waiting'; message text;
BEGIN
    IF p_run IS NULL OR p_registration IS NULL OR p_registration<1 OR p_epoch IS NULL OR p_epoch<1 OR p_after IS NULL OR p_after<0 THEN reason:='invalid_wait_args';
    ELSIF NOT (v99_core.v99_core_has_role('v99_core_operator') OR v99_core.v99_core_has_role('v99_core_reader')) OR (p_actor IS NOT NULL AND p_actor<>p_run) THEN reason:='expired';
    ELSE
        SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run;
        IF NOT FOUND OR r.registration_generation<>p_registration THEN reason:='expired';
        ELSIF p_epoch>r.current_epoch_ordinal THEN reason:='invalid_wait_args';
        ELSE
            SELECT * INTO s FROM v99_core.core_snapshots WHERE run_id=p_run;
            SELECT GREATEST(COALESCE(max(wake_id),0),p_after) INTO maxwake FROM v99_core.core_wakes WHERE run_id=p_run AND registration_generation=p_registration;
            SELECT cw.* INTO w FROM v99_core.core_wakes cw WHERE cw.run_id=p_run AND cw.registration_generation=p_registration AND cw.wake_id>p_after AND cw.reason='steering_requested' ORDER BY cw.wake_id LIMIT 1;
            IF FOUND THEN reason:='interrupted_by_steering'; message:=w.steering_message; maxwake:=w.wake_id;
            ELSIF s.interaction IS NOT NULL OR s.status IN ('completed','failed','cancelled','blocked_unknown') THEN reason:='actionable';
            ELSIF p_epoch<r.current_epoch_ordinal THEN reason:='epoch_advanced'; END IF;
        END IF;
    END IF;
    RETURN jsonb_build_object('schema_version',1,'reason',reason,'snapshot',CASE WHEN s.run_id IS NULL THEN NULL ELSE v99_core.v99_core_snapshot_projection(p_run,message) END,
        'registration_generation',r.registration_generation,'epoch_ordinal',r.current_epoch_ordinal,'continuity_generation',r.continuity_generation,
        'interaction',s.interaction,'wake_id',CASE WHEN reason IN ('expired','invalid_wait_args') THEN NULL ELSE maxwake END);
END $$;
CREATE FUNCTION v99_core.v99_core_insert_user(p_run uuid,p_epoch bigint,p_turn bigint,p_text text,p_effect uuid DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
BEGIN PERFORM v99_core.v99_core_append_event(p_run,'user/message',jsonb_build_object('schema_version',1,'text',p_text),p_effect,p_epoch,p_turn); END $$;

CREATE FUNCTION v99_core.v99_core_cancel(p_actor uuid,p_run uuid,p_request text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE digest text; replay jsonb; req jsonb; r v99_core.core_runs; op uuid; result jsonb; response jsonb; reject_reason text;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_operator') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_actor IS NOT NULL AND p_actor IS DISTINCT FROM p_run THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL OR NOT v99_core.v99_core_request_id(p_request) THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    req:=jsonb_build_object('schema_version',1,'verb','cancel','actor',p_actor,'run_id',p_run,'request_id',p_request); digest:=v99_core.v99_core_digest(req);
    replay:=v99_core.v99_core_replay(p_request,'cancel',digest); IF replay IS NOT NULL THEN RETURN replay; END IF;
    BEGIN
        r:=v99_core.v99_core_lock_work(p_run); IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
        IF r.status IN ('completed','failed','cancelled') THEN RETURN v99_core.v99_core_error('already_terminal'); END IF;
        op:=v99_core.v99_core_add_operation(p_run,p_request,'cancel',r.turn_ordinal,'{}');
        result:=v99_core.v99_core_require(v99_core.v99_core_closeout(p_run,'cancelled',op));
        response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'operation_id',op,'revision',result->'revision','status','cancelled',
            'cancelled_effect_ids',result->'cancelled_effect_ids','unsettled_claim_ids',result->'unsettled_claim_ids','unknown_effect_ids',result->'unknown_effect_ids');
        PERFORM v99_core.v99_core_journal(p_request,'cancel',digest,p_run,response); RETURN response;
    EXCEPTION WHEN SQLSTATE 'V9901' THEN
        GET STACKED DIAGNOSTICS reject_reason = PG_EXCEPTION_DETAIL;
        IF SQLERRM<>'v99_core_business_rejection' OR NOT v99_core.v99_core_business_reason(reject_reason) THEN RAISE; END IF;
        RETURN v99_core.v99_core_error(reject_reason);
    END;
END $$;
CREATE FUNCTION v99_core.v99_core_control_publish(p_run uuid,p_operation uuid,p_status text,p_text text,p_interaction jsonb,p_failure jsonb,p_human uuid,p_reason text,p_message text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE o jsonb;
BEGIN
    IF p_status IN ('completed','failed','cancelled') THEN
        o:=v99_core.v99_core_closeout(p_run,p_status,p_operation,p_text,p_failure);
    ELSE
        o:=v99_core.v99_core_write_snapshot(p_run,p_operation,p_status,p_text,p_interaction,p_failure,p_human,p_reason,p_message);
    END IF;
    RETURN v99_core.v99_core_require(o);
END $$;
CREATE FUNCTION v99_core.v99_core_steer(p_actor uuid,p_run uuid,p_message text,p_request text,p_expected bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE req jsonb; digest text; replay jsonb; r v99_core.core_runs; epoch uuid; op uuid; admitted jsonb; interaction_id uuid; human_effect uuid; next_turn bigint; response jsonb; old_status text; reject_reason text;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_operator') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_actor IS NOT NULL AND p_actor IS DISTINCT FROM p_run THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL OR p_message IS NULL OR btrim(p_message)='' OR octet_length(p_message)>1000000 OR NOT v99_core.v99_core_request_id(p_request) OR p_expected IS NULL OR p_expected<1 THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    req:=jsonb_build_object('schema_version',1,'verb','steer','actor',p_actor,'run_id',p_run,'message',p_message,'expected_epoch',p_expected,'request_id',p_request);
    digest:=v99_core.v99_core_digest(req); replay:=v99_core.v99_core_replay(p_request,'steer',digest); IF replay IS NOT NULL THEN RETURN replay; END IF;
    BEGIN
        r:=v99_core.v99_core_lock_work(p_run); IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
        IF r.status='cancelled' THEN RETURN v99_core.v99_core_error('already_terminal'); END IF;
        IF r.current_epoch_ordinal<>p_expected THEN RETURN v99_core.v99_core_error('stale_epoch'); END IF;
        IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
        IF r.interaction IS NOT NULL AND r.interaction->>'kind'<>'instruction' THEN RETURN v99_core.v99_core_error('use_respond'); END IF;
        old_status:=r.status; next_turn:=r.turn_ordinal+1;
        IF old_status IN ('completed','failed') THEN
            UPDATE v99_core.core_epochs SET closed_at=COALESCE(closed_at,clock_timestamp()) WHERE run_id=p_run AND ordinal=r.current_epoch_ordinal;
            epoch:=gen_random_uuid();
            INSERT INTO v99_core.core_epochs(epoch_id,run_id,ordinal,continuity_generation,registration_generation,transition_kind) VALUES(epoch,p_run,r.current_epoch_ordinal+1,1,1,'steering');
            UPDATE v99_core.core_runs SET current_epoch_ordinal=current_epoch_ordinal+1,status='running',failure_reason=NULL,interaction=NULL WHERE run_id=p_run;
        END IF;
        IF r.interaction IS NOT NULL THEN
            interaction_id:=(r.interaction->>'id')::uuid;
            IF r.interaction->>'channel'='human' THEN
                human_effect:=(SELECT interaction_effect_id FROM v99_core.core_snapshots WHERE run_id=p_run);
                PERFORM v99_core.v99_core_require(v99_core.v99_core_settle_human(p_run,interaction_id,jsonb_build_object('schema_version',1,'response',p_message)));
            ELSE
                UPDATE v99_core.core_runs SET interaction=NULL WHERE run_id=p_run;
                PERFORM v99_core.v99_core_append_event(p_run,'human/responded',jsonb_build_object('schema_version',1,'interaction_id',interaction_id,'response',p_message,'settlement_channel','operator_instruction_steer','caller_role',v99_core.v99_core_caller_role()),NULL,r.current_epoch_ordinal,r.turn_ordinal);
            END IF;
        END IF;
        op:=v99_core.v99_core_add_operation(p_run,p_request,'steer',next_turn,jsonb_build_object('message',p_message));
        PERFORM v99_core.v99_core_insert_user(p_run,(SELECT current_epoch_ordinal FROM v99_core.core_runs WHERE run_id=p_run),next_turn,p_message);
        admitted:=v99_core.v99_core_admit_turn(p_run,'ce:'||op::text||':next_turn',jsonb_build_object('messages',jsonb_build_array(jsonb_build_object('role','user','content',p_message))),false);
        UPDATE v99_core.core_runs SET driving_operation_id=(admitted->>'execution_operation_id')::uuid WHERE run_id=p_run;
        response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'operation_id',op,'execution_operation_id',(admitted->>'execution_operation_id')::uuid,
            'epoch_ordinal',(SELECT current_epoch_ordinal FROM v99_core.core_runs WHERE run_id=p_run),'revision',r.revision+1,'status','running','queued',(old_status IN ('running','waiting_for_input')));
        PERFORM v99_core.v99_core_append_event(p_run,'run/steering_requested',jsonb_build_object('schema_version',1,'operation_id',op,'message',p_message),NULL,
            (SELECT current_epoch_ordinal FROM v99_core.core_runs WHERE run_id=p_run),next_turn);
        PERFORM v99_core.v99_core_require(v99_core.v99_core_control_publish(p_run,op,'running',NULL,NULL,NULL,NULL,'steering_requested',p_message));
        PERFORM v99_core.v99_core_journal(p_request,'steer',digest,p_run,response); RETURN response;
    EXCEPTION WHEN SQLSTATE 'V9901' THEN
        GET STACKED DIAGNOSTICS reject_reason = PG_EXCEPTION_DETAIL;
        IF SQLERRM<>'v99_core_business_rejection' OR NOT v99_core.v99_core_business_reason(reject_reason) THEN RAISE; END IF;
        RETURN v99_core.v99_core_error(reject_reason);
    END;
END $$;
CREATE FUNCTION v99_core.v99_core_respond(p_actor uuid,p_run uuid,p_interaction text,p_response jsonb,p_request text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE req jsonb; digest text; replay jsonb; r v99_core.core_runs; iid uuid; op uuid; admitted jsonb; human_effect uuid; response jsonb; next_turn bigint; reject_reason text;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_operator') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_actor IS NOT NULL AND p_actor IS DISTINCT FROM p_run THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL OR NOT v99_core.v99_core_request_id(p_request) THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    IF NOT v99_core.v99_core_uuid(p_interaction) THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    IF NOT v99_core.v99_core_valid_response(p_response) OR octet_length(jsonb_build_object('interaction_id',p_interaction,'response',p_response)::text)>1048576
        OR octet_length(jsonb_build_object('messages',jsonb_build_array(jsonb_build_object('role','user','content',p_response)))::text)>1048576 THEN RETURN v99_core.v99_core_error('invalid_response'); END IF;
    req:=jsonb_build_object('schema_version',1,'verb','respond','actor',p_actor,'run_id',p_run,'interaction_id',p_interaction,'response',p_response,'request_id',p_request);
    digest:=v99_core.v99_core_digest(req); replay:=v99_core.v99_core_replay(p_request,'respond',digest); IF replay IS NOT NULL THEN RETURN replay; END IF;
    BEGIN
        r:=v99_core.v99_core_lock_work(p_run); IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
        IF r.status='cancelled' OR r.status IN ('completed','failed') THEN RETURN v99_core.v99_core_error('already_terminal'); END IF;
        IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
        iid:=p_interaction::uuid;
        IF r.status<>'waiting_for_input' OR r.interaction IS NULL OR (r.interaction->>'id')::uuid<>iid THEN RETURN v99_core.v99_core_error('interaction_mismatch'); END IF;
        human_effect:=(SELECT interaction_effect_id FROM v99_core.core_snapshots WHERE run_id=p_run);
        IF r.interaction->>'channel'='human' THEN
            PERFORM v99_core.v99_core_require(v99_core.v99_core_settle_human(p_run,iid,p_response));
        ELSE
            UPDATE v99_core.core_runs SET interaction=NULL WHERE run_id=p_run;
            PERFORM v99_core.v99_core_append_event(p_run,'human/responded',jsonb_build_object('schema_version',1,'interaction_id',iid,'response',p_response,'settlement_channel','ce_response','caller_role',v99_core.v99_core_caller_role()),NULL,r.current_epoch_ordinal,r.turn_ordinal);
        END IF;
        next_turn:=r.turn_ordinal+1;
        op:=v99_core.v99_core_add_operation(p_run,p_request,'respond',next_turn,jsonb_build_object('interaction_id',iid,'response',p_response));
        admitted:=v99_core.v99_core_admit_turn(p_run,'ce:'||op::text||':next_turn',jsonb_build_object('messages',jsonb_build_array(jsonb_build_object('role','user','content',p_response))),false);
        UPDATE v99_core.core_runs SET driving_operation_id=(admitted->>'execution_operation_id')::uuid WHERE run_id=p_run;
        response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'operation_id',op,'execution_operation_id',(admitted->>'execution_operation_id')::uuid,
            'epoch_ordinal',r.current_epoch_ordinal,'revision',r.revision+1,'status','running');
        PERFORM v99_core.v99_core_require(v99_core.v99_core_control_publish(p_run,op,'running',NULL,NULL,NULL,NULL,'snapshot'));
        PERFORM v99_core.v99_core_journal(p_request,'respond',digest,p_run,response); RETURN response;
    EXCEPTION WHEN SQLSTATE 'V9901' THEN
        GET STACKED DIAGNOSTICS reject_reason = PG_EXCEPTION_DETAIL;
        IF SQLERRM<>'v99_core_business_rejection' OR NOT v99_core.v99_core_business_reason(reject_reason) THEN RAISE; END IF;
        RETURN v99_core.v99_core_error(reject_reason);
    END;
END $$;

CREATE FUNCTION v99_core.v99_core_discover(p_run uuid,p_driver text,p_fence bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE r v99_core.core_runs; why text; op uuid; e v99_core.core_effects; next_json jsonb;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run;
    IF NOT FOUND THEN RETURN v99_core.v99_core_error('expired'); END IF;
    why:=v99_core.v99_core_driver_error(p_run,p_driver,p_fence); IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF r.status<>'running' THEN RETURN v99_core.v99_core_error('run_not_running'); END IF;
    SELECT o.operation_id INTO op FROM v99_core.core_operations o JOIN v99_core.core_epochs ep ON ep.epoch_id=o.epoch_id
        WHERE o.run_id=p_run AND ep.ordinal=r.current_epoch_ordinal AND o.status='pending' AND o.verb IN ('admit_turn','admit_tool') ORDER BY o.attempt_seq LIMIT 1;
    IF op IS NOT NULL THEN
        SELECT * INTO e FROM v99_core.core_effects WHERE operation_id=op AND kind IN ('llm','tool');
        IF e.effect_id IS NOT NULL AND e.status='ready' THEN
            next_json:=jsonb_build_object('operation_id',op,'effect_id',e.effect_id,'kind',e.kind,'turn_ordinal',e.turn_ordinal,
                'attempt_seq',(SELECT attempt_seq FROM v99_core.core_operations WHERE operation_id=op));
        END IF;
    END IF;
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'driver_fence',p_fence,'revision',r.revision,'next',next_json);
END $$;
CREATE FUNCTION v99_core.v99_core_worker_history(p_run uuid,p_driver text,p_fence bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE r v99_core.core_runs; why text; cat bigint; rows jsonb;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run;
    IF NOT FOUND THEN RETURN v99_core.v99_core_error('expired'); END IF;
    why:=v99_core.v99_core_driver_error(p_run,p_driver,p_fence); IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    IF r.status='blocked_unknown' THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    SELECT catalog_revision INTO STRICT cat FROM v99_core.core_meta WHERE singleton;
    SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'type',type,'payload',payload,'epoch_ordinal',epoch_ordinal,'turn_ordinal',turn_ordinal) ORDER BY seq),'[]'::jsonb)
        INTO rows FROM v99_core.core_events WHERE run_id=p_run AND type=ANY(ARRAY['user/message','llm/message','tool/call','tool/result','human/responded']);
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'epoch_ordinal',r.current_epoch_ordinal,
        'context_revision',r.context_revision,'catalog_revision',cat,'events',rows);
END $$;

-- Private service publication. Host code cannot call this in the final ACL;
-- accept_receipt verifies the settlement and passes the revision read under lock.
CREATE FUNCTION v99_core.v99_core_publish_snapshot(p_operation uuid,p_request text,p_driver text,p_fence bigint,p_expected bigint,p_snapshot jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE o v99_core.core_operations; r v99_core.core_runs; why text; effect v99_core.core_effects; pin v99_core.core_effect_pins;
    cat bigint; human uuid; out_json jsonb; p_status text; p_interaction jsonb; p_failure jsonb; p_text text;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_operation IS NULL OR p_request IS DISTINCT FROM ('ce:'||p_operation::text||':publish:receipt') OR p_expected IS NULL OR p_expected<1
        OR NOT v99_core.v99_core_keys(p_snapshot,ARRAY['schema_version','status','assistant_text','interaction','failure_reason'])
        OR p_snapshot->'schema_version'<>'1'::jsonb OR jsonb_typeof(p_snapshot->'status')<>'string'
        OR p_snapshot->>'status' NOT IN ('running','waiting_for_input','completed','failed')
        OR NOT (p_snapshot ? 'assistant_text' AND p_snapshot ? 'interaction' AND p_snapshot ? 'failure_reason')
        OR (p_snapshot->'assistant_text'<>'null'::jsonb AND jsonb_typeof(p_snapshot->'assistant_text')<>'string')
        OR NOT COALESCE(v99_core.v99_core_valid_interaction(NULLIF(p_snapshot->'interaction','null'::jsonb)),false)
        OR (p_snapshot->'failure_reason'<>'null'::jsonb AND NOT COALESCE(v99_core.v99_core_valid_error(p_snapshot->'failure_reason'),false))
        OR ((p_snapshot->>'status'='waiting_for_input')<>(p_snapshot->'interaction'<>'null'::jsonb))
        OR (p_snapshot->>'status'='failed')<>(p_snapshot->'failure_reason'<>'null'::jsonb)
        OR (p_snapshot->>'status' IN ('completed','failed') AND p_snapshot->'interaction'<>'null'::jsonb)
        THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    SELECT run_id INTO r.run_id FROM v99_core.core_operations WHERE operation_id=p_operation;
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    r:=v99_core.v99_core_lock_work(r.run_id);
    SELECT * INTO o FROM v99_core.core_operations WHERE operation_id=p_operation;
    SELECT * INTO effect FROM v99_core.core_effects WHERE operation_id=p_operation AND kind IN ('llm','tool');
    IF effect.effect_id IS NULL OR effect.status NOT IN ('succeeded','failed') THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
    SELECT catalog_revision INTO STRICT cat FROM v99_core.core_meta WHERE singleton FOR SHARE;
    why:=v99_core.v99_core_driver_error(r.run_id,p_driver,p_fence); IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    IF r.revision<>p_expected THEN RETURN v99_core.v99_core_error('revision_conflict'); END IF;
    SELECT * INTO pin FROM v99_core.core_effect_pins WHERE effect_id=effect.effect_id AND attempt_no=effect.attempt_no AND fence=effect.fence;
    IF pin.effect_id IS NULL OR pin.driver_fence IS DISTINCT FROM p_fence OR pin.context_revision<>r.context_revision OR pin.catalog_revision<>cat
       OR pin.request_digest<>effect.request_digest OR effect.request_digest<>v99_core.v99_core_digest(effect.request) THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
    IF o.status<>'completed' THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    IF effect.epoch_ordinal<>r.current_epoch_ordinal OR effect.claim_driver_fence IS DISTINCT FROM p_fence THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
    IF r.interaction IS NOT NULL THEN RETURN v99_core.v99_core_error(CASE WHEN p_snapshot->>'status' IN ('completed','failed') THEN 'closeout_blocked' ELSE 'interaction_pending' END); END IF;
    p_status:=p_snapshot->>'status'; p_text:=p_snapshot->>'assistant_text'; p_interaction:=NULLIF(p_snapshot->'interaction','null'::jsonb); p_failure:=NULLIF(p_snapshot->'failure_reason','null'::jsonb);
    IF r.status IN ('cancelled','completed','failed') THEN RETURN v99_core.v99_core_error('already_terminal'); END IF;
    IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=r.run_id AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF p_status='waiting_for_input' THEN
        IF r.interaction IS NOT NULL OR EXISTS(SELECT 1 FROM v99_core.core_operations WHERE run_id=r.run_id AND status='pending') THEN RETURN v99_core.v99_core_error('pending_work'); END IF;
        IF p_interaction->>'channel'='human' THEN
            SELECT effect_id INTO human FROM v99_core.core_effects WHERE operation_id=p_operation AND kind='human' AND request=p_interaction AND status='ready';
            IF human IS NULL THEN RETURN v99_core.v99_core_error('interaction_pending'); END IF;
        END IF;
        IF EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=r.run_id AND status IN ('ready','claimed') AND effect_id IS DISTINCT FROM human) THEN RETURN v99_core.v99_core_error('pending_work'); END IF;
    ELSIF p_interaction IS NOT NULL THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    IF p_status IN ('completed','failed') AND (EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=r.run_id AND status IN ('ready','claimed','unknown'))
        OR EXISTS(SELECT 1 FROM v99_core.core_operations WHERE run_id=r.run_id AND status='pending') OR r.interaction IS NOT NULL) THEN
        RETURN v99_core.v99_core_error(CASE WHEN r.interaction IS NOT NULL THEN 'closeout_blocked' ELSE 'pending_work' END);
    END IF;
    IF p_status IN ('completed','failed') THEN
        out_json:=v99_core.v99_core_closeout(r.run_id,p_status,p_operation,p_text,p_failure);
    ELSE
        out_json:=v99_core.v99_core_write_snapshot(r.run_id,p_operation,p_status,p_text,p_interaction,p_failure,human);
    END IF;
    RETURN out_json;
END $$;

CREATE FUNCTION v99_core.v99_core_accept_receipt(p_operation uuid,p_receipt_id text,p_driver text,p_driver_fence bigint,p_receipt jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,v99_core AS $$
DECLARE digest text; replay jsonb; req jsonb; run uuid; r v99_core.core_runs; o v99_core.core_operations; e v99_core.core_effects; why text;
    cat bigint; result_error text; result jsonb; root_op uuid; current_chain boolean; pending_tools integer; next_op uuid; admitted jsonb;
    status_text text; assistant text; interaction jsonb; failure jsonb; human uuid; response jsonb; i integer; call_item jsonb; tool_payload jsonb;
    newop uuid; publication jsonb; reason text;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_operation IS NULL OR p_receipt_id IS NULL
       OR NOT v99_core.v99_core_valid_receipt(p_receipt) OR p_receipt_id<>'ce:'||p_operation::text||':receipt' THEN RETURN v99_core.v99_core_error('invalid_receipt'); END IF;
    req:=jsonb_build_object('schema_version',1,'verb','receipt','operation_id',p_operation,'receipt_id',p_receipt_id,'driver',p_driver,'driver_fence',p_driver_fence,'receipt',p_receipt);
    digest:=v99_core.v99_core_digest(req);
    PERFORM pg_advisory_xact_lock(hashtextextended('v99-core-request:'||p_receipt_id,0));
    SELECT j.response INTO replay FROM v99_core.core_requests j WHERE j.request_id=p_receipt_id;
    IF FOUND THEN
        IF (SELECT request_digest FROM v99_core.core_requests WHERE request_id=p_receipt_id)<>digest OR
           (SELECT kind FROM v99_core.core_requests WHERE request_id=p_receipt_id)<>'receipt' THEN RETURN v99_core.v99_core_error('receipt_conflict'); END IF;
        RETURN replay;
    END IF;
    SELECT run_id INTO run FROM v99_core.core_operations WHERE operation_id=p_operation;
    IF run IS NULL THEN RETURN v99_core.v99_core_error('receipt_request_mismatch'); END IF;
    BEGIN
        r:=v99_core.v99_core_lock_work(run);
        SELECT * INTO o FROM v99_core.core_operations WHERE operation_id=p_operation;
        SELECT * INTO e FROM v99_core.core_effects WHERE run_id=run AND effect_id=(p_receipt->>'effect_id')::uuid;
        IF e.kind='human' THEN RETURN v99_core.v99_core_error('invalid_receipt'); END IF;
        IF o.operation_id IS NULL OR e.effect_id IS NULL OR e.operation_id<>p_operation OR o.verb NOT IN ('admit_turn','admit_tool') THEN
            PERFORM v99_core.v99_core_append_event(run,'receipt/mismatch',jsonb_build_object('schema_version',1,'operation_id',p_operation,'effect_id',p_receipt->>'effect_id'),NULL,r.current_epoch_ordinal,r.turn_ordinal);
            RETURN v99_core.v99_core_error('receipt_request_mismatch');
        END IF;
        IF r.status='cancelled' AND (e.status='unknown' OR (e.status='claimed' AND e.cancel_requested)) THEN
            PERFORM v99_core.v99_core_append_event(run,'receipt/late',jsonb_build_object('schema_version',1,'operation_id',p_operation,'status',e.status),e.effect_id,e.epoch_ordinal,e.turn_ordinal);
            RETURN v99_core.v99_core_error(CASE WHEN e.status='unknown' THEN 'unknown_wall' ELSE 'stale_claim' END);
        END IF;
        -- Replay above intentionally precedes lease, terminal, pin and catalog checks.
        why:=v99_core.v99_core_driver_error(run,p_driver,p_driver_fence); IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
        IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
        IF e.epoch_ordinal<>r.current_epoch_ordinal OR e.status<>'claimed' OR e.cancel_requested
            OR e.attempt_no<>(p_receipt->>'attempt_no')::integer OR e.fence<>(p_receipt->>'fence')::bigint
            OR e.claim_driver_fence IS DISTINCT FROM p_driver_fence THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
        SELECT catalog_revision INTO STRICT cat FROM v99_core.core_meta WHERE singleton FOR SHARE;
        result_error:=v99_core.v99_core_result_error(e.kind,e.request,p_receipt);
        IF result_error IS NOT NULL THEN RETURN v99_core.v99_core_error(result_error); END IF;
        result:=v99_core.v99_core_settle_effect(run,p_operation,e.effect_id,p_driver,p_driver_fence,
            (p_receipt->>'attempt_no')::integer,(p_receipt->>'fence')::bigint,(p_receipt->>'context_revision')::bigint,
            (p_receipt->>'catalog_revision')::bigint,p_receipt->>'status',p_receipt->'effect_result');
        IF NOT COALESCE((result->>'ok')::boolean,false) THEN
            -- The W2 helper's expected rejection must unwind its mutation block.
            PERFORM v99_core.v99_core_require(result);
        END IF;
        IF p_receipt->>'status'='unknown' THEN
            response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',run,'operation_id',p_operation,'effect_id',e.effect_id,'disposition','unknown',
                'revision',(SELECT revision FROM v99_core.core_runs WHERE run_id=run),'status','blocked_unknown');
            PERFORM v99_core.v99_core_journal(p_receipt_id,'receipt',digest,run,response); RETURN response;
        END IF;
        SELECT * INTO r FROM v99_core.core_runs WHERE run_id=run;
        root_op:=CASE WHEN e.kind='tool' THEN (o.payload->>'source_operation_id')::uuid ELSE p_operation END;
        current_chain:=r.driving_operation_id=root_op;
        IF p_receipt->>'status'='succeeded' AND e.kind='llm' THEN
            assistant:=p_receipt->'effect_result'->>'text';
            IF assistant IS NOT NULL THEN PERFORM v99_core.v99_core_append_event(run,'llm/message',jsonb_build_object('schema_version',1,'text',assistant),e.effect_id,e.epoch_ordinal,e.turn_ordinal); END IF;
            IF p_receipt->'effect_result' ? 'tool_calls' AND current_chain THEN
                FOR i IN 0..jsonb_array_length(p_receipt->'effect_result'->'tool_calls')-1 LOOP
                    call_item:=p_receipt->'effect_result'->'tool_calls'->i;
                    tool_payload:=jsonb_build_object('source_operation_id',p_operation,'tool_call_index',i,'tool',call_item->>'name','params',call_item->'args');
                    newop:=v99_core.v99_core_add_operation(run,'ce:'||p_operation::text||':tool:'||i,'admit_tool',e.turn_ordinal,tool_payload);
                    admitted:=v99_core.v99_core_require(v99_core.v99_core_enqueue_effect(run,newop,'tool',jsonb_build_object('tool',call_item->>'name','params',call_item->'args'),'ce:'||p_operation::text||':tool:'||i,call_item->>'name'));
                    PERFORM v99_core.v99_core_append_event(run,'tool/call',jsonb_build_object('schema_version',1,'id',call_item->>'id','name',call_item->>'name','args',call_item->'args'),(admitted->>'effect_id')::uuid,e.epoch_ordinal,e.turn_ordinal);
                END LOOP;
                UPDATE v99_core.core_operations SET status=CASE WHEN current_chain THEN 'completed' ELSE 'archived' END,
                    archive_reason=CASE WHEN current_chain THEN NULL ELSE 'archived_stale' END,result=p_receipt->'effect_result',completed_at=clock_timestamp() WHERE operation_id=p_operation;
                IF current_chain THEN
                    UPDATE v99_core.core_runs SET status='running' WHERE run_id=run;
                    publication:=jsonb_build_object('schema_version',1,'status','running','assistant_text',assistant,'interaction',NULL,'failure_reason',NULL);
                    PERFORM v99_core.v99_core_require(v99_core.v99_core_publish_snapshot(p_operation,'ce:'||p_operation::text||':publish:receipt',p_driver,p_driver_fence,r.revision,publication));
                END IF;
            ELSE
                status_text:=p_receipt->'effect_result'->>'ce_status'; interaction:=p_receipt->'effect_result'->'interaction'; failure:=p_receipt->'effect_result'->'failure_reason';
                UPDATE v99_core.core_operations SET status=CASE WHEN current_chain THEN 'completed' ELSE 'archived' END,
                    archive_reason=CASE WHEN current_chain THEN NULL ELSE 'archived_stale' END,result=p_receipt->'effect_result',completed_at=clock_timestamp() WHERE operation_id=p_operation;
                IF current_chain AND status_text='waiting_for_input' AND interaction->>'channel'='human' THEN
                    human:=gen_random_uuid();
                    admitted:=v99_core.v99_core_enqueue_effect(run,p_operation,'human',interaction,'ce:'||p_operation::text||':human');
                    PERFORM v99_core.v99_core_require(admitted); human:=(admitted->>'effect_id')::uuid;
                END IF;
                IF NOT current_chain THEN
                    response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',run,'operation_id',p_operation,'effect_id',e.effect_id,'disposition','archived_stale',
                        'revision',r.revision,'status',r.status);
                ELSIF status_text IN ('completed','failed') THEN
                    IF status_text='failed' THEN
                        UPDATE v99_core.core_effects SET status='cancelled' WHERE run_id=run AND status='ready';
                        UPDATE v99_core.core_operations SET status='archived',archive_reason='upstream_failed',completed_at=clock_timestamp() WHERE run_id=run AND status='pending';
                    END IF;
                    publication:=jsonb_build_object('schema_version',1,'status',status_text,'assistant_text',assistant,'interaction',NULL,'failure_reason',failure);
                ELSIF status_text='running' THEN
                    UPDATE v99_core.core_runs SET turn_ordinal=turn_ordinal+1 WHERE run_id=run;
                    next_op:=v99_core.v99_core_add_operation(run,'ce:'||p_operation::text||':next_turn','admit_turn',r.turn_ordinal+1,jsonb_build_object('continuation_from',p_operation,'text',assistant));
                    admitted:=v99_core.v99_core_require(v99_core.v99_core_enqueue_effect(run,next_op,'llm',jsonb_build_object('continuation_from',p_operation,'text',assistant),'ce:'||p_operation::text||':next_turn'));
                    UPDATE v99_core.core_runs SET driving_operation_id=next_op,status='running' WHERE run_id=run;
                    publication:=jsonb_build_object('schema_version',1,'status','running','assistant_text',assistant,'interaction',NULL,'failure_reason',NULL);
                ELSE
                    publication:=jsonb_build_object('schema_version',1,'status','waiting_for_input','assistant_text',assistant,'interaction',interaction,'failure_reason',NULL);
                END IF;
                IF current_chain THEN PERFORM v99_core.v99_core_require(v99_core.v99_core_publish_snapshot(p_operation,'ce:'||p_operation::text||':publish:receipt',p_driver,p_driver_fence,r.revision,publication)); END IF;
            END IF;
        ELSIF p_receipt->>'status'='failed' THEN
            IF e.kind='tool' THEN
                PERFORM v99_core.v99_core_append_event(run,'tool/result',jsonb_build_object('schema_version',1,'result',p_receipt->'effect_result'),e.effect_id,e.epoch_ordinal,e.turn_ordinal);
            END IF;
            UPDATE v99_core.core_operations SET status=CASE WHEN current_chain THEN 'completed' ELSE 'archived' END,
                archive_reason=CASE WHEN current_chain THEN NULL ELSE 'archived_stale' END,result=p_receipt->'effect_result',completed_at=clock_timestamp() WHERE operation_id=p_operation;
            IF current_chain THEN
                UPDATE v99_core.core_effects SET status='cancelled' WHERE run_id=run AND status='ready';
                UPDATE v99_core.core_operations SET status='archived',archive_reason='upstream_failed',completed_at=clock_timestamp() WHERE run_id=run AND status='pending';
                publication:=jsonb_build_object('schema_version',1,'status','failed','assistant_text',NULL,'interaction',NULL,'failure_reason',p_receipt->'effect_result'->'error');
                PERFORM v99_core.v99_core_require(v99_core.v99_core_publish_snapshot(p_operation,'ce:'||p_operation::text||':publish:receipt',p_driver,p_driver_fence,r.revision,publication));
            END IF;
        ELSIF e.kind='tool' THEN
            PERFORM v99_core.v99_core_append_event(run,'tool/result',jsonb_build_object('schema_version',1,'result',p_receipt->'effect_result'),e.effect_id,e.epoch_ordinal,e.turn_ordinal);
            UPDATE v99_core.core_operations SET status=CASE WHEN current_chain THEN 'completed' ELSE 'archived' END,
                archive_reason=CASE WHEN current_chain THEN NULL ELSE 'archived_stale' END,result=p_receipt->'effect_result',completed_at=clock_timestamp() WHERE operation_id=p_operation;
            IF current_chain THEN
                SELECT count(*) INTO pending_tools FROM v99_core.core_operations WHERE run_id=run AND verb='admit_tool' AND status='pending' AND payload->>'source_operation_id'=root_op::text;
                IF pending_tools=0 THEN
                    UPDATE v99_core.core_runs SET turn_ordinal=turn_ordinal+1 WHERE run_id=run;
                    next_op:=v99_core.v99_core_add_operation(run,'ce:'||root_op::text||':next_turn','admit_turn',r.turn_ordinal+1,jsonb_build_object('continuation_from',root_op));
                    admitted:=v99_core.v99_core_require(v99_core.v99_core_enqueue_effect(run,next_op,'llm',jsonb_build_object('continuation_from',root_op),'ce:'||root_op::text||':next_turn'));
                    UPDATE v99_core.core_runs SET driving_operation_id=next_op,status='running' WHERE run_id=run;
                    publication:=jsonb_build_object('schema_version',1,'status','running','assistant_text',NULL,'interaction',NULL,'failure_reason',NULL);
                    PERFORM v99_core.v99_core_require(v99_core.v99_core_publish_snapshot(p_operation,'ce:'||p_operation::text||':publish:receipt',p_driver,p_driver_fence,r.revision,publication));
                ELSE
                    UPDATE v99_core.core_runs SET status='running' WHERE run_id=run;
                    publication:=jsonb_build_object('schema_version',1,'status','running','assistant_text',NULL,'interaction',NULL,'failure_reason',NULL);
                    PERFORM v99_core.v99_core_require(v99_core.v99_core_publish_snapshot(p_operation,'ce:'||p_operation::text||':publish:receipt',p_driver,p_driver_fence,r.revision,publication));
                END IF;
            END IF;
        END IF;
        IF response IS NULL THEN
            SELECT * INTO r FROM v99_core.core_runs WHERE run_id=run;
            response:=jsonb_build_object('schema_version',1,'ok',true,'run_id',run,'operation_id',p_operation,'effect_id',e.effect_id,
                'disposition',CASE WHEN current_chain THEN 'accepted' ELSE 'archived_stale' END,'revision',r.revision,'status',r.status);
        END IF;
        PERFORM v99_core.v99_core_journal(p_receipt_id,'receipt',digest,run,response);
        RETURN response;
    EXCEPTION WHEN SQLSTATE 'V9901' THEN
        GET STACKED DIAGNOSTICS reason = PG_EXCEPTION_DETAIL;
        IF SQLERRM<>'v99_core_business_rejection' OR NOT v99_core.v99_core_business_reason(reason) THEN RAISE; END IF;
        RETURN v99_core.v99_core_error(reason);
    END;
END $$;


REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v99_core FROM PUBLIC;
