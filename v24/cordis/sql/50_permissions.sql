-- Same transaction as the DEFINER creation: no publicly executable intermediate state.
DO $$
DECLARE family text; alias text; role_name text;
BEGIN
 family:=v24_cordis.role_family();
 IF family IS NULL THEN RAISE EXCEPTION 'unsafe Cordis role family' USING ERRCODE='42501'; END IF;
 REVOKE ALL ON SCHEMA v24_cordis FROM PUBLIC;
 REVOKE ALL ON ALL TABLES IN SCHEMA v24_cordis FROM PUBLIC;
 REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24_cordis FROM PUBLIC;
 FOREACH alias IN ARRAY ARRAY['admin','service','operator'] LOOP
  role_name:=family||'_'||alias;
  EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA v24_cordis FROM %I',role_name);
  EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24_cordis FROM %I',role_name);
  EXECUTE format('GRANT USAGE ON SCHEMA v24_cordis TO %I',role_name);
  EXECUTE format('GRANT EXECUTE ON FUNCTION v24_cordis.advance(uuid,jsonb) TO %I',role_name);
 END LOOP;
 -- DP6 W1: independent read-only observer family. No advance EXECUTE, no DML, no
 -- table-level SELECT; only the exact raw-fact columns the fair scanner reads.
 role_name:=family||'_observer';
 EXECUTE format('REVOKE ALL ON SCHEMA v24_cordis FROM %I',role_name);
 EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA v24_cordis FROM %I',role_name);
 EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA v24_cordis FROM %I',role_name);
 EXECUTE format('GRANT USAGE ON SCHEMA v24_cordis TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,current_episode_id,failure,retire_started_at,dispose_requested_at,disposed_at) ON v24_cordis.fibers TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,fiber_id,epoch,state,closed_at) ON v24_cordis.episodes TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,parent_id,ordinal,fiber_id,episode_id,run_id,kind,status,input,request_actor,attempt,fence,claim_owner,lease_until,outcome,settled_at) ON v24_cordis.effects TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,scope_id,owner_fiber_id,owner_episode_id,identity,version,artifact_digest,state) ON v24_cordis.installs TO %I',role_name);
 EXECUTE format('GRANT SELECT (principal_id,request_key,request_bytes,request_digest,effect_id,response) ON v24_cordis.requests TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,owner_fiber_id,owner_episode_id,ended_at) ON v24_cordis.runs TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,fiber_id,episode_id,kind,realm,key,inverse,withdrawn_at,released_at) ON v24_cordis.contributions TO %I',role_name);
 EXECUTE format('GRANT SELECT (id,consumer_fiber_id,consumer_episode_id,consumer_run_id,contribution_id,released_at) ON v24_cordis.pins TO %I',role_name);
 IF EXISTS(SELECT 1 FROM pg_proc WHERE pronamespace='v24_cordis'::regnamespace AND prosecdef
   AND oid<>'v24_cordis.advance(uuid,jsonb)'::regprocedure) THEN
  RAISE EXCEPTION 'unexpected DEFINER entry point' USING ERRCODE='42501';
 END IF;
END $$;
