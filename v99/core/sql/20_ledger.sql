-- W2 ledger primitives. All helpers are private unless 40 explicitly grants them.
-- W3 owns request advisory locks/replay, CE authorization, complete receipt shape
-- validation, operation completion/successors and the enclosing atomic T2.
-- Private helpers return {schema_version,ok,...}; W3 MUST roll back its mutation
-- subtransaction if any later helper returns ok=false. Unknown SQL errors escape.

CREATE FUNCTION v99_core.v99_core_error(p_reason text)
RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, v99_core AS $$
    SELECT jsonb_build_object('schema_version',1,'ok',false,'reason',p_reason)
$$;
-- The only recoverable business-rejection SQLSTATE used by W2/W3 helpers.
CREATE FUNCTION v99_core.v99_core_business_reason(p_reason text)
RETURNS boolean LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,v99_core AS $$
    SELECT COALESCE(p_reason=ANY(ARRAY['invalid_args','unauthorized','expired','request_id_conflict','already_terminal','run_not_running','stale_epoch','use_respond','interaction_mismatch','interaction_pending','invalid_response','invalid_receipt','invalid_tool','invalid_tool_args','unknown_wall','driver_required','driver_expired','not_claimable','stale_claim','receipt_conflict','receipt_request_mismatch','pending_work','revision_conflict','archived_stale','closeout_blocked']),false)
$$;
CREATE FUNCTION v99_core.v99_core_require(p_result jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog,v99_core AS $$
BEGIN
    IF p_result->'ok' = 'true'::jsonb THEN RETURN p_result; END IF;
    IF v99_core.v99_core_business_reason(p_result->>'reason') THEN
        RAISE EXCEPTION USING ERRCODE='V9901',MESSAGE='v99_core_business_rejection',DETAIL=p_result->>'reason';
    END IF;
    RAISE EXCEPTION 'unregistered helper rejection: %',p_result;
END $$;
CREATE FUNCTION v99_core.v99_core_digest(p_value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path = pg_catalog, v99_core AS $$
    SELECT encode(v99_core.digest(convert_to(p_value::text,'UTF8'),'sha256'),'hex')
$$;
CREATE FUNCTION v99_core.v99_core_caller_role()
RETURNS name LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE caller text := current_setting('role',true);
BEGIN
    IF caller IS NULL OR caller IN ('','none') THEN caller := session_user; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=caller) THEN RETURN NULL; END IF;
    RETURN caller::name;
END $$;
CREATE FUNCTION v99_core.v99_core_has_role(p_group text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
    SELECT COALESCE(pg_has_role(v99_core.v99_core_caller_role(),p_group,'USAGE'),false)
$$;
-- Lock order shared by every existing-row writer: run -> epoch -> operations
-- (attempt_seq) -> effects (effect_id) -> meta SHARE -> pins/events/projections.
CREATE FUNCTION v99_core.v99_core_lock_run(p_run uuid)
RETURNS v99_core.core_runs LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs;
BEGIN
    SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run FOR UPDATE;
    IF FOUND THEN
        PERFORM 1 FROM v99_core.core_epochs WHERE run_id=p_run AND ordinal=r.current_epoch_ordinal FOR UPDATE;
    END IF;
    RETURN r;
END $$;
-- T2/control callers that may mutate more than one admission prelock the whole
-- existing workset before target CAS/meta. Reentering helpers only reacquires
-- locks already held; successor inserts need no existing-row lock. W3 calls
-- this immediately after the request lock, before locking an individual item.
CREATE FUNCTION v99_core.v99_core_lock_work(p_run uuid)
RETURNS v99_core.core_runs LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs;
BEGIN
    r := v99_core.v99_core_lock_run(p_run);
    IF r.run_id IS NOT NULL THEN
        PERFORM 1 FROM v99_core.core_operations WHERE run_id=p_run ORDER BY attempt_seq FOR UPDATE;
        PERFORM 1 FROM v99_core.core_effects WHERE run_id=p_run ORDER BY effect_id FOR UPDATE;
    END IF;
    RETURN r;
END $$;
CREATE FUNCTION v99_core.v99_core_driver_error(p_run uuid,p_driver text,p_driver_fence bigint)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs;
BEGIN
    SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run;
    IF NOT FOUND THEN RETURN 'expired'; END IF;
    IF p_driver IS NULL OR btrim(p_driver)='' OR r.driver_owner IS DISTINCT FROM p_driver THEN RETURN 'driver_required'; END IF;
    IF p_driver_fence IS DISTINCT FROM r.driver_fence THEN RETURN 'stale_claim'; END IF;
    IF r.driver_lease_until IS NULL OR r.driver_lease_until <= clock_timestamp() THEN RETURN 'driver_expired'; END IF;
    RETURN NULL;
END $$;

CREATE FUNCTION v99_core.v99_core_append_event(p_run uuid,p_type text,p_payload jsonb,
    p_effect uuid DEFAULT NULL,p_epoch bigint DEFAULT NULL,p_turn bigint DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE n bigint;
BEGIN
    PERFORM v99_core.v99_core_lock_run(p_run);
    SELECT COALESCE(max(seq),0)+1 INTO n FROM v99_core.core_events WHERE run_id=p_run;
    INSERT INTO v99_core.core_events(run_id,seq,event_id,type,payload,payload_hash,source_effect_id,epoch_ordinal,turn_ordinal)
    VALUES(p_run,n,gen_random_uuid(),p_type,p_payload,v99_core.v99_core_digest(p_payload),p_effect,p_epoch,p_turn);
    RETURN n;
END $$;
CREATE FUNCTION v99_core.v99_core_wake(p_run uuid,p_reason text,p_message text DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; n bigint;
BEGIN
    r := v99_core.v99_core_lock_run(p_run);
    INSERT INTO v99_core.core_wakes(run_id,registration_generation,epoch_ordinal,reason,steering_message,interaction)
    VALUES(p_run,r.registration_generation,r.current_epoch_ordinal,p_reason,p_message,r.interaction) RETURNING wake_id INTO n;
    PERFORM pg_notify('v99_core_run_changed',p_run::text || '|' || r.revision::text);
    RETURN n;
END $$;
-- Private projection writer: W3 controls authorization and publication eligibility.
-- Initial=true is only for start (revision=1, no existing snapshot). Every other
-- actual publication increments revision once, appends one event and one wake.
CREATE FUNCTION v99_core.v99_core_write_snapshot(p_run uuid,p_operation uuid,p_status text,
    p_text text,p_interaction jsonb,p_failure jsonb,p_human_effect uuid,
    p_wake_reason text DEFAULT 'snapshot',p_message text DEFAULT NULL,p_initial boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs;
BEGIN
    r := v99_core.v99_core_lock_run(p_run);
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    IF r.status='cancelled' OR (r.status IN ('completed','failed') AND p_status<>'running') THEN
        RETURN v99_core.v99_core_error('already_terminal');
    END IF;
    IF r.status='blocked_unknown' AND p_status<>'cancelled' THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF NOT v99_core.v99_core_valid_interaction(p_interaction)
       OR p_status IS NULL OR p_status NOT IN ('running','waiting_for_input','completed','failed','cancelled','blocked_unknown')
       OR (p_status='waiting_for_input') <> (p_interaction IS NOT NULL)
       OR (p_interaction IS NULL AND p_human_effect IS NOT NULL)
       OR (p_interaction IS NOT NULL AND ((p_interaction->>'channel'='human') <> (p_human_effect IS NOT NULL)))
       OR p_wake_reason IS NULL OR p_wake_reason NOT IN ('snapshot','steering_requested','terminal','cancelled')
       OR p_initial IS NULL THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    IF p_operation IS NOT NULL AND NOT EXISTS(SELECT 1 FROM v99_core.core_operations o JOIN v99_core.core_epochs ep ON ep.epoch_id=o.epoch_id
        WHERE o.run_id=p_run AND o.operation_id=p_operation AND ep.ordinal=r.current_epoch_ordinal) THEN
        RETURN v99_core.v99_core_error('stale_epoch');
    END IF;
    IF p_initial AND (r.revision<>1 OR EXISTS(SELECT 1 FROM v99_core.core_snapshots WHERE run_id=p_run)) THEN
        RETURN v99_core.v99_core_error('revision_conflict');
    END IF;
    UPDATE v99_core.core_runs SET status=p_status,interaction=p_interaction,failure_reason=p_failure,
        revision=revision+CASE WHEN p_initial THEN 0 ELSE 1 END,updated_at=clock_timestamp()
        WHERE run_id=p_run RETURNING * INTO r;
    INSERT INTO v99_core.core_snapshots(run_id,registration_generation,epoch_ordinal,turn_ordinal,revision,status,
        interaction,assistant_text,failure_reason,last_operation_id,interaction_effect_id,updated_at)
    VALUES(p_run,r.registration_generation,r.current_epoch_ordinal,r.turn_ordinal,r.revision,p_status,
        p_interaction,p_text,p_failure,p_operation,p_human_effect,r.updated_at)
    ON CONFLICT(run_id) DO UPDATE SET registration_generation=EXCLUDED.registration_generation,
        epoch_ordinal=EXCLUDED.epoch_ordinal,turn_ordinal=EXCLUDED.turn_ordinal,revision=EXCLUDED.revision,
        status=EXCLUDED.status,interaction=EXCLUDED.interaction,assistant_text=EXCLUDED.assistant_text,
        failure_reason=EXCLUDED.failure_reason,last_operation_id=EXCLUDED.last_operation_id,
        interaction_effect_id=EXCLUDED.interaction_effect_id,updated_at=EXCLUDED.updated_at;
    PERFORM v99_core.v99_core_append_event(p_run,'run/snapshot',jsonb_build_object('schema_version',1,'status',p_status,'revision',r.revision),NULL,r.current_epoch_ordinal,r.turn_ordinal);
    PERFORM v99_core.v99_core_wake(p_run,p_wake_reason,p_message);
    RETURN jsonb_build_object('schema_version',1,'ok',true,'revision',r.revision,'status',r.status);
END $$;

-- W3 inserts the admission before enqueue, under the same run lock. request is
-- the exact Fake input (human: the closed interaction object), digest is derived.
CREATE FUNCTION v99_core.v99_core_enqueue_effect(p_run uuid,p_operation uuid,p_kind text,
    p_request jsonb,p_key text,p_tool text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; o v99_core.core_operations; e v99_core.core_effects; ep bigint; n uuid;
BEGIN
    r := v99_core.v99_core_lock_run(p_run);
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF r.status NOT IN ('running','waiting_for_input') THEN RETURN v99_core.v99_core_error('run_not_running'); END IF;
    IF p_kind IS NULL OR p_kind NOT IN ('llm','tool','human') OR p_request IS NULL OR p_key IS NULL OR btrim(p_key)='' THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    SELECT * INTO o FROM v99_core.core_operations WHERE run_id=p_run AND operation_id=p_operation FOR UPDATE;
    IF NOT FOUND THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    SELECT ordinal INTO ep FROM v99_core.core_epochs WHERE epoch_id=o.epoch_id;
    IF ep<>r.current_epoch_ordinal THEN RETURN v99_core.v99_core_error('stale_epoch'); END IF;
    IF NOT ((p_kind='llm' AND o.verb='admit_turn' AND o.status='pending')
         OR (p_kind='tool' AND o.verb='admit_tool' AND o.status='pending' AND p_tool IS NOT NULL)
         OR (p_kind='human' AND o.verb='admit_turn' AND o.status='completed' AND v99_core.v99_core_valid_interaction(p_request) AND p_request->>'channel'='human')) THEN
        RETURN v99_core.v99_core_error('not_claimable');
    END IF;
    SELECT * INTO e FROM v99_core.core_effects WHERE run_id=p_run AND idempotency_key=p_key;
    IF FOUND THEN
        IF e.operation_id<>p_operation OR e.kind<>p_kind OR e.request<>p_request OR e.tool_name IS DISTINCT FROM p_tool THEN RETURN v99_core.v99_core_error('request_id_conflict'); END IF;
        RETURN jsonb_build_object('schema_version',1,'ok',true,'effect_id',e.effect_id);
    END IF;
    IF EXISTS(SELECT 1 FROM v99_core.core_effects WHERE operation_id=p_operation AND (kind='human')=(p_kind='human')) THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    n := gen_random_uuid();
    INSERT INTO v99_core.core_effects(effect_id,run_id,operation_id,kind,tool_name,request,request_digest,idempotency_key,epoch_ordinal,turn_ordinal)
    VALUES(n,p_run,p_operation,p_kind,p_tool,p_request,v99_core.v99_core_digest(p_request),p_key,ep,o.turn_ordinal);
    RETURN jsonb_build_object('schema_version',1,'ok',true,'effect_id',n);
END $$;

CREATE FUNCTION v99_core.v99_core_driver_acquire(p_run uuid,p_driver text,p_lease_ms integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; t timestamptz;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL OR p_driver IS NULL OR btrim(p_driver)='' OR p_lease_ms IS NULL OR p_lease_ms NOT BETWEEN 1 AND 60000 THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    r := v99_core.v99_core_lock_run(p_run);
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    t := clock_timestamp();
    IF r.driver_lease_until>t AND r.driver_owner IS DISTINCT FROM p_driver THEN RETURN v99_core.v99_core_error('driver_required'); END IF;
    UPDATE v99_core.core_runs SET driver_owner=p_driver,driver_lease_until=t+make_interval(secs=>p_lease_ms/1000.0),
        driver_fence=driver_fence+CASE WHEN driver_owner=p_driver AND driver_lease_until>t THEN 0 ELSE 1 END
        WHERE run_id=p_run RETURNING * INTO r;
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'driver_owner',r.driver_owner,
        'driver_lease_until',r.driver_lease_until,'driver_fence',r.driver_fence);
END $$;

CREATE FUNCTION v99_core.v99_core_claim_effect(p_run uuid,p_operation uuid,p_driver text,p_driver_fence bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; o v99_core.core_operations; e v99_core.core_effects; head uuid; why text; cat bigint;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL OR p_operation IS NULL THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    r := v99_core.v99_core_lock_run(p_run);
    why := v99_core.v99_core_driver_error(p_run,p_driver,p_driver_fence);
    IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF r.status<>'running' THEN RETURN v99_core.v99_core_error('run_not_running'); END IF;
    IF EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='claimed') THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    SELECT op.operation_id INTO head FROM v99_core.core_operations op JOIN v99_core.core_epochs ep ON ep.epoch_id=op.epoch_id
        WHERE op.run_id=p_run AND ep.ordinal=r.current_epoch_ordinal AND op.status='pending' AND op.verb IN ('admit_turn','admit_tool') ORDER BY op.attempt_seq LIMIT 1;
    IF head IS DISTINCT FROM p_operation THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    SELECT * INTO o FROM v99_core.core_operations WHERE operation_id=head FOR UPDATE;
    SELECT * INTO e FROM v99_core.core_effects WHERE operation_id=head AND kind IN ('llm','tool') FOR UPDATE;
    IF NOT FOUND OR e.status<>'ready' OR e.epoch_ordinal<>r.current_epoch_ordinal OR e.cancel_requested THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    SELECT catalog_revision INTO STRICT cat FROM v99_core.core_meta WHERE singleton FOR SHARE;
    -- Recheck the clock after potentially waiting for the catalog lock.
    why := v99_core.v99_core_driver_error(p_run,p_driver,p_driver_fence);
    IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    UPDATE v99_core.core_effects SET status='claimed',attempt_no=attempt_no+1,fence=fence+1,claim_driver_fence=p_driver_fence WHERE effect_id=e.effect_id RETURNING * INTO e;
    INSERT INTO v99_core.core_effect_pins(effect_id,attempt_no,fence,driver_fence,context_revision,catalog_revision,request_digest,claimed_at)
        VALUES(e.effect_id,e.attempt_no,e.fence,p_driver_fence,r.context_revision,cat,e.request_digest,clock_timestamp());
    PERFORM v99_core.v99_core_append_event(p_run,'effect/claimed',jsonb_build_object('schema_version',1,'attempt_no',e.attempt_no,'fence',e.fence,'driver_fence',p_driver_fence),e.effect_id,e.epoch_ordinal,e.turn_ordinal);
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'operation_id',head,'effect_id',e.effect_id,'kind',e.kind,
        'request',e.request,'idempotency_key',e.idempotency_key,'attempt_no',e.attempt_no,'fence',e.fence,
        'driver_fence',p_driver_fence,'context_revision',r.context_revision,'catalog_revision',cat,'request_digest',e.request_digest);
END $$;

-- Private transition; caller has already locked run/epoch/operation/effect.
-- The enclosing reported/recovery path publishes blocked_unknown exactly once.
CREATE FUNCTION v99_core.v99_core_mark_unknown(p_effect uuid,p_error jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE e v99_core.core_effects;
BEGIN
    UPDATE v99_core.core_effects SET status='unknown',fence=fence+1,error=p_error WHERE effect_id=p_effect AND status='claimed' RETURNING * INTO e;
    IF NOT FOUND THEN RAISE EXCEPTION 'mark_unknown requires a locked claimed effect'; END IF;
    UPDATE v99_core.core_operations SET status='archived',archive_reason='unknown',completed_at=clock_timestamp() WHERE operation_id=e.operation_id AND status='pending';
    PERFORM v99_core.v99_core_append_event(e.run_id,'effect/unknown',jsonb_build_object('schema_version',1,'error',p_error,'cancel_requested',e.cancel_requested),e.effect_id,e.epoch_ordinal,e.turn_ordinal);
END $$;

-- Ledger-only CAS, NOT a host T2 entry. W3 validates receipt shape before calling.
-- It does not complete successful/failed operations or generate successors.
-- Unknown does archive its admission and publish the unknown wall here.
CREATE FUNCTION v99_core.v99_core_settle_effect(p_run uuid,p_operation uuid,p_effect uuid,
    p_driver text,p_driver_fence bigint,p_attempt integer,p_fence bigint,p_context bigint,p_catalog bigint,
    p_status text,p_result jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; o v99_core.core_operations; e v99_core.core_effects;
    pin v99_core.core_effect_pins; why text; cat bigint; out_json jsonb;
BEGIN
    IF p_status IS NULL OR p_status NOT IN ('succeeded','failed','unknown') OR p_result IS NULL THEN RETURN v99_core.v99_core_error('invalid_receipt'); END IF;
    r := v99_core.v99_core_lock_work(p_run);
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    SELECT * INTO o FROM v99_core.core_operations WHERE run_id=p_run AND operation_id=p_operation FOR UPDATE;
    SELECT * INTO e FROM v99_core.core_effects WHERE run_id=p_run AND effect_id=p_effect FOR UPDATE;
    IF e.effect_id IS NULL OR o.operation_id IS NULL OR e.operation_id<>p_operation THEN
        PERFORM v99_core.v99_core_append_event(p_run,'receipt/mismatch',jsonb_build_object('schema_version',1,'operation_id',p_operation,'effect_id',p_effect),NULL,r.current_epoch_ordinal,r.turn_ordinal);
        RETURN v99_core.v99_core_error('receipt_request_mismatch');
    END IF;
    IF r.status='cancelled' AND (e.status='unknown' OR (e.status='claimed' AND e.cancel_requested)) THEN
        PERFORM v99_core.v99_core_append_event(p_run,'receipt/late',jsonb_build_object('schema_version',1,'operation_id',p_operation,'status',e.status),e.effect_id,e.epoch_ordinal,e.turn_ordinal);
        RETURN v99_core.v99_core_error(CASE WHEN e.status='unknown' THEN 'unknown_wall' ELSE 'stale_claim' END);
    END IF;
    IF r.status='blocked_unknown' OR e.status='unknown' THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF e.kind<>'human' THEN
        why := v99_core.v99_core_driver_error(p_run,p_driver,p_driver_fence);
        IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    ELSIF p_driver IS NOT NULL OR p_driver_fence IS NOT NULL OR p_status<>'succeeded' THEN RETURN v99_core.v99_core_error('invalid_receipt');
    END IF;
    IF e.status<>'claimed' OR e.cancel_requested OR e.attempt_no IS DISTINCT FROM p_attempt OR e.fence IS DISTINCT FROM p_fence
       OR e.claim_driver_fence IS DISTINCT FROM p_driver_fence OR e.epoch_ordinal<>r.current_epoch_ordinal THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
    SELECT catalog_revision INTO STRICT cat FROM v99_core.core_meta WHERE singleton FOR SHARE;
    IF e.kind<>'human' THEN
        why := v99_core.v99_core_driver_error(p_run,p_driver,p_driver_fence);
        IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    END IF;
    SELECT * INTO pin FROM v99_core.core_effect_pins WHERE effect_id=p_effect AND attempt_no=p_attempt AND fence=p_fence;
    IF pin.effect_id IS NULL OR pin.driver_fence IS DISTINCT FROM p_driver_fence
       OR pin.context_revision IS DISTINCT FROM p_context OR pin.catalog_revision IS DISTINCT FROM p_catalog
       OR r.context_revision IS DISTINCT FROM p_context OR cat IS DISTINCT FROM p_catalog
       OR pin.request_digest IS DISTINCT FROM e.request_digest OR e.request_digest IS DISTINCT FROM v99_core.v99_core_digest(e.request) THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
    IF p_status='unknown' THEN
        PERFORM v99_core.v99_core_mark_unknown(p_effect,p_result->'error');
        out_json := v99_core.v99_core_write_snapshot(p_run,p_operation,'blocked_unknown',NULL,NULL,p_result->'error',NULL);
        PERFORM v99_core.v99_core_require(out_json);
    ELSE
        UPDATE v99_core.core_effects SET status=p_status,result=CASE WHEN p_status='succeeded' THEN p_result END,
            error=CASE WHEN p_status='failed' THEN p_result->'error' END WHERE effect_id=p_effect AND status='claimed' AND attempt_no=p_attempt AND fence=p_fence;
        IF NOT FOUND THEN RETURN v99_core.v99_core_error('stale_claim'); END IF;
        PERFORM v99_core.v99_core_append_event(p_run,'effect/done',jsonb_build_object('schema_version',1,'status',p_status,'result',p_result),p_effect,e.epoch_ordinal,e.turn_ordinal);
    END IF;
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'operation_id',p_operation,'effect_id',p_effect,
        'disposition',CASE WHEN p_status='unknown' THEN 'unknown' ELSE 'accepted' END);
END $$;

-- Operator-authorized W3 calls this in its control transaction, with the exact
-- current interaction UUID. No driver acquisition/renewal/impersonation occurs.
-- W3 supplies response validation and creates the control/admission/publication.
CREATE FUNCTION v99_core.v99_core_settle_human(p_run uuid,p_interaction uuid,p_response jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; e v99_core.core_effects; eid uuid; cat bigint; out_json jsonb;
BEGIN
    r := v99_core.v99_core_lock_work(p_run);
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    IF r.status='blocked_unknown' THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
    IF r.status<>'waiting_for_input' OR r.interaction IS NULL OR r.interaction->>'channel'<>'human'
       OR (r.interaction->>'id')::uuid IS DISTINCT FROM p_interaction THEN RETURN v99_core.v99_core_error('interaction_mismatch'); END IF;
    SELECT interaction_effect_id INTO eid FROM v99_core.core_snapshots WHERE run_id=p_run;
    PERFORM 1 FROM v99_core.core_operations WHERE operation_id=(SELECT operation_id FROM v99_core.core_effects WHERE effect_id=eid) FOR UPDATE;
    SELECT * INTO e FROM v99_core.core_effects WHERE run_id=p_run AND effect_id=eid FOR UPDATE;
    IF e.effect_id IS NULL OR e.kind<>'human' OR e.status<>'ready' OR e.request<>r.interaction
        OR e.request_digest<>v99_core.v99_core_digest(e.request) OR p_response IS NULL
        OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='claimed') THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    SELECT catalog_revision INTO STRICT cat FROM v99_core.core_meta WHERE singleton FOR SHARE;
    UPDATE v99_core.core_effects SET status='claimed',attempt_no=attempt_no+1,fence=fence+1,claim_driver_fence=NULL WHERE effect_id=eid RETURNING * INTO e;
    INSERT INTO v99_core.core_effect_pins(effect_id,attempt_no,fence,driver_fence,context_revision,catalog_revision,request_digest,claimed_at)
        VALUES(eid,e.attempt_no,e.fence,NULL,r.context_revision,cat,e.request_digest,clock_timestamp());
    PERFORM v99_core.v99_core_append_event(p_run,'effect/claimed',jsonb_build_object('schema_version',1,'attempt_no',e.attempt_no,'fence',e.fence,'driver_fence',NULL,'settlement_channel','operator_response','caller_role',v99_core.v99_core_caller_role()),eid,e.epoch_ordinal,e.turn_ordinal);
    out_json := v99_core.v99_core_settle_effect(p_run,e.operation_id,eid,NULL,NULL,e.attempt_no,e.fence,r.context_revision,cat,'succeeded',p_response);
    PERFORM v99_core.v99_core_require(out_json);
    UPDATE v99_core.core_runs SET interaction=NULL WHERE run_id=p_run;
    PERFORM v99_core.v99_core_append_event(p_run,'human/responded',jsonb_build_object('schema_version',1,'interaction_id',p_interaction,'response',p_response,'settlement_channel','operator_response','caller_role',v99_core.v99_core_caller_role()),eid,e.epoch_ordinal,e.turn_ordinal);
    RETURN out_json;
END $$;

CREATE FUNCTION v99_core.v99_core_recover_unknown(p_run uuid,p_driver text,p_driver_fence bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; why text; e v99_core.core_effects; ids jsonb := '[]'; out_json jsonb;
BEGIN
    IF NOT v99_core.v99_core_has_role('v99_core_service') THEN RETURN v99_core.v99_core_error('unauthorized'); END IF;
    IF p_run IS NULL THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    r := v99_core.v99_core_lock_work(p_run);
    why := v99_core.v99_core_driver_error(p_run,p_driver,p_driver_fence);
    IF why IS NOT NULL THEN RETURN v99_core.v99_core_error(why); END IF;
    PERFORM 1 FROM v99_core.core_operations o WHERE o.run_id=p_run AND EXISTS(SELECT 1 FROM v99_core.core_effects eff WHERE eff.operation_id=o.operation_id AND eff.status='claimed' AND eff.claim_driver_fence IS DISTINCT FROM r.driver_fence) ORDER BY o.attempt_seq FOR UPDATE;
    FOR e IN SELECT * FROM v99_core.core_effects WHERE run_id=p_run AND status='claimed' AND claim_driver_fence IS DISTINCT FROM r.driver_fence ORDER BY effect_id FOR UPDATE LOOP
        PERFORM v99_core.v99_core_mark_unknown(e.effect_id,jsonb_build_object('code','driver_takeover','message','Result unavailable after driver takeover'));
        ids := ids || jsonb_build_array(e.effect_id);
    END LOOP;
    IF jsonb_array_length(ids)>0 AND r.status<>'cancelled' THEN
        out_json := v99_core.v99_core_write_snapshot(p_run,r.driving_operation_id,'blocked_unknown',NULL,NULL,
            jsonb_build_object('code','driver_takeover','message','Result unavailable after driver takeover'),NULL);
        PERFORM v99_core.v99_core_require(out_json);
    END IF;
    SELECT * INTO r FROM v99_core.core_runs WHERE run_id=p_run;
    RETURN jsonb_build_object('schema_version',1,'ok',true,'run_id',p_run,'driver_fence',p_driver_fence,'unknown_effect_ids',ids,'status',r.status,'revision',r.revision);
END $$;

-- The ONLY terminal seal writer. W3 completes the current admission before
-- normal closeout; cancel inserts its completed control operation beforehand.
CREATE FUNCTION v99_core.v99_core_closeout(p_run uuid,p_status text,p_operation uuid,
    p_text text DEFAULT NULL,p_failure jsonb DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, v99_core AS $$
DECLARE r v99_core.core_runs; cancelled jsonb := '[]'; claimed jsonb := '[]'; unknowns jsonb := '[]'; seal jsonb; out_json jsonb;
BEGIN
    IF p_status IS NULL OR p_status NOT IN ('completed','failed','cancelled') THEN RETURN v99_core.v99_core_error('invalid_args'); END IF;
    r := v99_core.v99_core_lock_work(p_run);
    IF r.run_id IS NULL THEN RETURN v99_core.v99_core_error('expired'); END IF;
    IF r.status IN ('completed','failed','cancelled') THEN RETURN v99_core.v99_core_error('already_terminal'); END IF;
    IF p_status<>'cancelled' THEN
        IF r.status='blocked_unknown' OR EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown') THEN RETURN v99_core.v99_core_error('unknown_wall'); END IF;
        IF r.interaction IS NOT NULL THEN RETURN v99_core.v99_core_error('closeout_blocked'); END IF;
        IF EXISTS(SELECT 1 FROM v99_core.core_effects WHERE run_id=p_run AND status IN ('ready','claimed'))
           OR EXISTS(SELECT 1 FROM v99_core.core_operations WHERE run_id=p_run AND status='pending') THEN RETURN v99_core.v99_core_error('pending_work'); END IF;
    END IF;
    IF NOT EXISTS(SELECT 1 FROM v99_core.core_operations o JOIN v99_core.core_epochs ep ON ep.epoch_id=o.epoch_id
        WHERE o.run_id=p_run AND o.operation_id=p_operation AND ep.ordinal=r.current_epoch_ordinal AND o.status='completed'
          AND ((p_status='cancelled' AND o.verb='cancel') OR (p_status<>'cancelled' AND o.verb IN ('admit_turn','admit_tool')))) THEN RETURN v99_core.v99_core_error('not_claimable'); END IF;
    IF p_status='cancelled' THEN
        SELECT COALESCE(jsonb_agg(effect_id ORDER BY effect_id),'[]') INTO cancelled FROM v99_core.core_effects WHERE run_id=p_run AND status='ready';
        SELECT COALESCE(jsonb_agg(effect_id ORDER BY effect_id),'[]') INTO claimed FROM v99_core.core_effects WHERE run_id=p_run AND status='claimed';
        SELECT COALESCE(jsonb_agg(effect_id ORDER BY effect_id),'[]') INTO unknowns FROM v99_core.core_effects WHERE run_id=p_run AND status='unknown';
        PERFORM v99_core.v99_core_append_event(p_run,'run/cancel_requested',jsonb_build_object('schema_version',1,'operation_id',p_operation),NULL,r.current_epoch_ordinal,r.turn_ordinal);
        UPDATE v99_core.core_effects SET status='cancelled' WHERE run_id=p_run AND status='ready';
        UPDATE v99_core.core_effects SET cancel_requested=true,fence=fence+1 WHERE run_id=p_run AND status='claimed';
        UPDATE v99_core.core_operations SET status='closed',completed_at=clock_timestamp() WHERE run_id=p_run AND status='pending';
    END IF;
    seal := jsonb_build_object('schema_version',1,'run_id',p_run,'epoch_ordinal',r.current_epoch_ordinal,'status',p_status,
        'cancelled_effect_ids',cancelled,'unsettled_claim_ids',claimed,'unknown_effect_ids',unknowns);
    UPDATE v99_core.core_epochs SET closed_at=clock_timestamp() WHERE run_id=p_run AND ordinal=r.current_epoch_ordinal;
    PERFORM v99_core.v99_core_append_event(p_run,'run/closed',seal,NULL,r.current_epoch_ordinal,r.turn_ordinal);
    out_json := v99_core.v99_core_write_snapshot(p_run,p_operation,p_status,p_text,NULL,p_failure,NULL,
        CASE WHEN p_status='cancelled' THEN 'cancelled' ELSE 'terminal' END);
    PERFORM v99_core.v99_core_require(out_json);
    RETURN (seal-'epoch_ordinal') || jsonb_build_object('ok',true,'revision',(out_json->'revision'));
END $$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v99_core FROM PUBLIC;
