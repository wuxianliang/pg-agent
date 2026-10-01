DO $seed$
DECLARE
  v_have jsonb;
  v_active boolean;
  v_want jsonb := $policy${
    "notify_on_human_pending": true,
    "notify_on_user_gate": true,
    "schema_version": 1
  }$policy$::jsonb;
BEGIN
  SELECT value, active
    INTO v_have, v_active
    FROM public.v13_policies
   WHERE name = 'notify_policy'
     AND version = 1;
  IF NOT FOUND THEN
    INSERT INTO public.v13_policies (name, version, value, active)
    VALUES ('notify_policy', 1, v_want, true);
  ELSIF v_have IS DISTINCT FROM v_want THEN
    RAISE EXCEPTION 'v13: notify policy: drift';
  END IF;
END
$seed$;

CREATE OR REPLACE FUNCTION public.v13_unpaid_harness_turn(p_sid uuid)
RETURNS TABLE (effect_id uuid)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $fn$
  SELECT e.effect_id
    FROM public.effects e
   WHERE e.session_id = public.v13_plan_map_root(p_sid)
     AND e.effect_id = public.v13_harness_predecessor(public.v13_plan_map_root(p_sid))
     AND e.kind = 'tool'
     AND public.v13_is_harness_tool(e.tool_name, e.kind)
     AND e.origin_user_seq = public.v13_last_user_seq(public.v13_plan_map_root(p_sid))
     AND public.v13_harness_request_ok(e.request)
     AND e.status = 'succeeded'
     AND (
       e.result->>'result_kind' = 'finish'
       OR (e.result->>'result_kind' = 'progress' AND NOT EXISTS (
             SELECT 1 FROM public.events
              WHERE source_effect_id = e.effect_id
                AND type IN ('repair/required', 'replan/required'))))
     AND NOT EXISTS (
           SELECT 1 FROM public.events
            WHERE source_effect_id = e.effect_id
              AND type = 'turn/material_spent')
$fn$;

CREATE OR REPLACE FUNCTION public.v13_harness_settle(
  p_actor uuid,
  p_root uuid,
  p_effect_id uuid,
  p_snap jsonb
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_n integer;
  v_cand uuid;
  v_stored jsonb;
  v_life text;
  v_probe jsonb;
  v_adv jsonb;
  v_word text;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: harness settle: canonical';
  END IF;
  v_root := public.v13_plan_map_root(p_root);
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: harness settle: canonical';
  END IF;
  SELECT count(*) INTO v_n
    FROM public.sessions
   WHERE parent_session_id IS NULL;
  IF v_n > 1 THEN
    RAISE EXCEPTION 'v13: harness settle: not_single_tree';
  END IF;
  IF p_actor IS NULL THEN
    IF NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: harness settle: auth';
    END IF;
  ELSIF NOT public.v13_control_authorized(p_actor, v_root) THEN
    RAISE EXCEPTION 'v13: harness settle: auth';
  END IF;
  IF p_effect_id IS NULL OR p_snap IS NULL OR jsonb_typeof(p_snap) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: harness settle: canonical';
  END IF;
  v_cand := public.v13_harness_predecessor(v_root);
  IF v_cand IS DISTINCT FROM p_effect_id THEN
    RAISE EXCEPTION 'v13: harness settle: canonical';
  END IF;
  SELECT e.result
    INTO v_stored
    FROM public.effects e
   WHERE e.effect_id = p_effect_id
     AND e.session_id = v_root
     AND e.kind = 'tool'
     AND public.v13_is_harness_tool(e.tool_name, e.kind)
     AND e.origin_user_seq = public.v13_last_user_seq(v_root)
     AND public.v13_harness_request_ok(e.request)
     AND e.status = 'succeeded'
     AND (
       e.result->>'result_kind' = 'finish'
       OR (e.result->>'result_kind' = 'progress' AND NOT EXISTS (
             SELECT 1 FROM public.events
              WHERE source_effect_id = e.effect_id
                AND type IN ('repair/required', 'replan/required'))))
     AND NOT EXISTS (
           SELECT 1 FROM public.events
            WHERE source_effect_id = e.effect_id
              AND type = 'turn/material_spent')
     FOR UPDATE;
  IF NOT FOUND OR v_stored IS DISTINCT FROM p_snap THEN
    RAISE EXCEPTION 'v13: harness settle: canonical';
  END IF;
  v_life := public.v13_goal_lifecycle(v_root);
  IF v_life = 'stopped'
     AND v_stored->'failed' IS NOT NULL
     AND jsonb_typeof(v_stored->'failed') IS DISTINCT FROM 'null' THEN
    RETURN 'skipped_failed';
  END IF;
  UPDATE public.sessions
     SET context_active_revision = public.v13_context_required(session_id)
   WHERE session_id = v_root;
  SELECT public.v13_probe(v_root) INTO v_probe;
  v_adv := jsonb_build_object(
    'snap', v_probe || jsonb_build_object('sid', v_root::text),
    'envelope', jsonb_build_object('sid', v_root::text),
    'remaining', 0,
    'abandon', false);
  SELECT public.v13_advance(v_root, v_adv) INTO v_word;
  RETURN v_word;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_interaction_offer(
  p_actor uuid,
  p_root uuid,
  p_apply_id uuid,
  p_offer jsonb
) RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_n integer;
  v_keys text[];
  v_eid uuid;
  v_old jsonb;
  v_status text;
  v_opt jsonb;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  v_root := public.v13_plan_map_root(p_root);
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  SELECT count(*) INTO v_n
    FROM public.sessions
   WHERE parent_session_id IS NULL;
  IF v_n > 1 THEN
    RAISE EXCEPTION 'v13: interaction offer: not_single_tree';
  END IF;
  IF p_actor IS NULL THEN
    IF NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: interaction offer: auth';
    END IF;
  ELSIF NOT public.v13_control_authorized(p_actor, v_root) THEN
    RAISE EXCEPTION 'v13: interaction offer: auth';
  END IF;
  IF p_apply_id IS NULL
     OR p_offer IS NULL
     OR jsonb_typeof(p_offer) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  v_keys := public.v13_json_keys(p_offer);
  IF v_keys IS DISTINCT FROM ARRAY[
       'apply_id', 'deadline', 'interaction_ref', 'offer_kind',
       'options', 'schema_version', 'source_effect_id'] THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  IF NOT public.v13_json_int_ok(p_offer->'schema_version', 1)
     OR p_offer->'schema_version' IS DISTINCT FROM '1'::jsonb THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  IF jsonb_typeof(p_offer->'apply_id') IS DISTINCT FROM 'string'
     OR NOT public.v13_canonical_uuid(p_offer->>'apply_id')
     OR (p_offer->>'apply_id') IS DISTINCT FROM p_apply_id::text THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  IF jsonb_typeof(p_offer->'interaction_ref') IS DISTINCT FROM 'string'
     OR coalesce(btrim(p_offer->>'interaction_ref'), '') = '' THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  IF (p_offer->>'offer_kind') IS DISTINCT FROM 'approval'
     AND (p_offer->>'offer_kind') IS DISTINCT FROM 'question' THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  IF jsonb_typeof(p_offer->'source_effect_id') IS DISTINCT FROM 'string'
     OR NOT public.v13_canonical_uuid(p_offer->>'source_effect_id') THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  IF jsonb_typeof(p_offer->'options') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_offer->'options') > 4 THEN
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  FOR v_opt IN SELECT value FROM jsonb_array_elements(p_offer->'options') LOOP
    IF jsonb_typeof(v_opt) IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'v13: interaction offer: canonical';
    END IF;
  END LOOP;
  IF jsonb_typeof(p_offer->'deadline') = 'null' THEN
    NULL;
  ELSIF jsonb_typeof(p_offer->'deadline') = 'string' THEN
    BEGIN
      PERFORM (p_offer->>'deadline')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
      RAISE EXCEPTION 'v13: interaction offer: canonical';
    END;
  ELSE
    RAISE EXCEPTION 'v13: interaction offer: canonical';
  END IF;
  SELECT e.event_id, e.payload
    INTO v_eid, v_old
    FROM public.events e
   WHERE e.session_id = v_root
     AND e.type = 'interaction/offered'
     AND e.payload->>'interaction_ref' = p_offer->>'interaction_ref'
   ORDER BY e.seq
   LIMIT 1;
  IF v_eid IS NOT NULL THEN
    IF v_old IS NOT DISTINCT FROM p_offer THEN
      RETURN v_eid;
    END IF;
    RAISE EXCEPTION 'v13: interaction offer: replay_conflict';
  END IF;
  IF public.v13_goal_lifecycle(v_root) = 'stopped' THEN
    RAISE EXCEPTION 'v13: interaction offer: stopped';
  END IF;
  SELECT status INTO v_status
    FROM public.sessions
   WHERE session_id = v_root;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: interaction offer: terminal';
  END IF;
  v_eid := p_apply_id;
  PERFORM public.v13_append_event(
    v_root, v_eid, 'interaction/offered', p_offer,
    (p_offer->>'source_effect_id')::uuid);
  RETURN v_eid;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_observe_fold(p_actor uuid, p_root uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_ids uuid[] := '{}';
  v_n integer := 0;
  v_omitted integer := 0;
  v_sid uuid;
  v_life text;
  v_status text;
  v_pending boolean;
  v_open integer;
BEGIN
  v_root := public.v13_plan_map_root(p_root);
  IF NOT public.v13_control_authorized(p_actor, v_root) THEN
    RAISE EXCEPTION 'v13: observe fold: auth';
  END IF;
  FOR v_sid IN
    WITH RECURSIVE tree AS (
      SELECT s.session_id
        FROM public.sessions s
       WHERE s.session_id = v_root
      UNION ALL
      SELECT c.session_id
        FROM public.sessions c
        JOIN tree t ON c.parent_session_id = t.session_id
    )
    SELECT session_id FROM tree ORDER BY session_id
  LOOP
    v_n := v_n + 1;
    IF v_n <= 4 THEN
      v_ids := v_ids || v_sid;
    ELSE
      v_omitted := 1;
      EXIT;
    END IF;
  END LOOP;
  IF cardinality(v_ids) > 0 THEN
    PERFORM 1 FROM public.v13_observe(p_actor, v_ids);
  END IF;
  v_life := public.v13_goal_lifecycle(v_root);
  SELECT status INTO v_status FROM public.sessions WHERE session_id = v_root;
  SELECT EXISTS (
    SELECT 1 FROM public.effects e
     WHERE e.session_id IN (
             WITH RECURSIVE tree AS (
               SELECT s.session_id FROM public.sessions s WHERE s.session_id = v_root
               UNION ALL
               SELECT c.session_id FROM public.sessions c
                 JOIN tree t ON c.parent_session_id = t.session_id
             )
             SELECT session_id FROM tree)
       AND e.kind = 'human'
       AND e.status IN ('ready', 'claimed', 'unknown'))
    INTO v_pending;
  SELECT count(*)::integer INTO v_open FROM public.v13_obligation_open(v_root);
  RETURN jsonb_build_object(
    'schema_version', 1,
    'root_session_id', v_root,
    'lifecycle_stopped', (v_life = 'stopped'),
    'session_status', v_status,
    'pending_human', v_pending,
    'obligation_open_count', v_open,
    'omitted_count', v_omitted,
    'omitted_complete', (v_omitted = 0));
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_goal_ambiguous_hold(p_root uuid)
RETURNS TABLE (effect_id uuid, tool_name text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $fn$
  SELECT e.effect_id, e.tool_name
    FROM public.effects e
   WHERE e.kind = 'tool'
     AND e.lease_owner = 'v13_workspace_opener'
     AND e.status = 'claimed'
     AND public.v13_plan_map_root(e.session_id) = public.v13_plan_map_root(p_root)
$fn$;

CREATE OR REPLACE FUNCTION public.v13_notify_project(p_root uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_hint text;
  v_life text;
  v_pol jsonb;
  v_active boolean;
  v_gate boolean := false;
  v_human boolean := false;
  v_hold boolean;
BEGIN
  v_root := public.v13_plan_map_root(p_root);
  v_hint := public.v13_scheduler_hint(v_root);
  v_life := public.v13_goal_lifecycle(v_root);
  IF v_life = 'stopped' OR v_hint = 'dont_notify' THEN
    RETURN jsonb_build_object('deliver', false, 'reason', 'stopped_dont_notify');
  END IF;
  SELECT EXISTS (SELECT 1 FROM public.v13_goal_ambiguous_hold(v_root))
    INTO v_hold;
  IF v_hold THEN
    RETURN jsonb_build_object('deliver', false, 'reason', 'ambiguous_hold');
  END IF;
  SELECT value, active
    INTO v_pol, v_active
    FROM public.v13_policies
   WHERE name = 'notify_policy'
     AND version = 1;
  IF v_active IS DISTINCT FROM true OR v_pol IS NULL THEN
    RETURN jsonb_build_object('deliver', false, 'reason', 'no_notice_fact');
  END IF;
  SELECT EXISTS (
    SELECT 1 FROM public.v13_plan_todo_fold(v_root) f
     WHERE f.task_class = 'user_gate'
       AND f.status NOT IN ('done', 'dropped'))
    INTO v_gate;
  SELECT EXISTS (
    SELECT 1 FROM public.effects e
     WHERE public.v13_plan_map_root(e.session_id) = v_root
       AND e.kind = 'human'
       AND e.status IN ('ready', 'claimed', 'unknown'))
    INTO v_human;
  IF (v_gate AND v_pol->'notify_on_user_gate' = 'true'::jsonb)
     OR (v_human AND v_pol->'notify_on_human_pending' = 'true'::jsonb) THEN
    RETURN jsonb_build_object('deliver', true, 'reason', 'eligible');
  END IF;
  RETURN jsonb_build_object('deliver', false, 'reason', 'no_notice_fact');
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_goal_lease_once(
  p_actor uuid,
  p_session uuid,
  p_effect_id uuid
) RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_n integer;
  v_status text;
  v_row public.effects;
  v_eff_root uuid;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: goal lease: canonical';
  END IF;
  v_root := public.v13_plan_map_root(p_session);
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: goal lease: canonical';
  END IF;
  SELECT count(*) INTO v_n
    FROM public.sessions
   WHERE parent_session_id IS NULL;
  IF v_n > 1 THEN
    RAISE EXCEPTION 'v13: goal lease: not_single_tree';
  END IF;
  IF p_actor IS NULL THEN
    IF NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: goal lease: auth';
    END IF;
  ELSIF NOT public.v13_control_authorized(p_actor, v_root) THEN
    RAISE EXCEPTION 'v13: goal lease: auth';
  END IF;
  IF public.v13_goal_lifecycle(v_root) = 'stopped' THEN
    RAISE EXCEPTION 'v13: goal lease: stopped';
  END IF;
  SELECT status INTO v_status FROM public.sessions WHERE session_id = v_root;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: goal lease: terminal';
  END IF;
  SELECT * INTO v_row
    FROM public.effects
   WHERE effect_id = p_effect_id
     FOR UPDATE;
  IF NOT FOUND OR v_row.status IS DISTINCT FROM 'claimed' THEN
    RAISE EXCEPTION 'v13: goal lease: not_claimed';
  END IF;
  v_eff_root := public.v13_plan_map_root(v_row.session_id);
  IF v_eff_root IS DISTINCT FROM v_root THEN
    RAISE EXCEPTION 'v13: goal lease: not_claimed';
  END IF;
  IF v_row.lease_owner IS NOT DISTINCT FROM 'v13_workspace_opener'
     OR v_row.lease_until IS NULL
     OR v_row.lease_until = 'infinity'::timestamptz THEN
    RETURN 'infinite_unchanged';
  END IF;
  UPDATE public.effects
     SET lease_until = greatest(
           lease_until,
           clock_timestamp() + make_interval(secs => 60))
   WHERE effect_id = p_effect_id
     AND status = 'claimed';
  RETURN 'extended';
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_evidence_check(
  p_root uuid,
  p_todo_id uuid,
  p_refs jsonb
) RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_class text;
  v_n integer;
  v_elem jsonb;
  v_aid uuid;
  v_prod uuid;
  v_st text;
  v_sid uuid;
BEGIN
  v_root := public.v13_plan_map_root(p_root);
  IF p_refs IS NULL OR jsonb_typeof(p_refs) = 'null' THEN
    RETURN 'ok';
  END IF;
  SELECT f.task_class INTO v_class
    FROM public.v13_plan_todo_fold(v_root) f
   WHERE f.todo_id = p_todo_id;
  IF v_class IS NULL THEN
    RAISE EXCEPTION 'v13: evidence: canonical';
  END IF;
  IF v_class IN ('continuous_monitor', 'user_gate', 'user_action', 'blocker') THEN
    RAISE EXCEPTION 'v13: evidence: wrong_class';
  END IF;
  IF v_class IS DISTINCT FROM 'advancement_task' THEN
    RAISE EXCEPTION 'v13: evidence: wrong_class';
  END IF;
  IF jsonb_typeof(p_refs) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: evidence: bad_ref';
  END IF;
  v_n := jsonb_array_length(p_refs);
  IF v_n < 1 OR v_n > 4 THEN
    RAISE EXCEPTION 'v13: evidence: bad_ref';
  END IF;
  FOR v_elem IN SELECT value FROM jsonb_array_elements(p_refs) LOOP
    IF jsonb_typeof(v_elem) IS DISTINCT FROM 'string'
       OR NOT public.v13_canonical_uuid(v_elem #>> '{}') THEN
      RAISE EXCEPTION 'v13: evidence: bad_ref';
    END IF;
    v_aid := (v_elem #>> '{}')::uuid;
    SELECT a.produced_by, x.status, x.session_id
      INTO v_prod, v_st, v_sid
      FROM public.artifacts a
      JOIN public.effects x ON x.effect_id = a.produced_by
     WHERE a.artifact_id = v_aid;
    IF v_prod IS NULL OR v_st IS DISTINCT FROM 'succeeded'
       OR public.v13_plan_map_root(v_sid) IS DISTINCT FROM v_root THEN
      RAISE EXCEPTION 'v13: evidence: bad_ref';
    END IF;
  END LOOP;
  RETURN 'ok';
END
$fn$;

REVOKE ALL ON FUNCTION public.v13_unpaid_harness_turn(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_harness_settle(uuid, uuid, uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_interaction_offer(uuid, uuid, uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_observe_fold(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_notify_project(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_goal_ambiguous_hold(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_goal_lease_once(uuid, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_evidence_check(uuid, uuid, jsonb) FROM PUBLIC;
