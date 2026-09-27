-- v13 govern (stage 29). Goal stop/resume and spawn-batch skip. No new tables.
BEGIN;

DO $govern_base$
DECLARE
  v_src text;
  v_listed text;
BEGIN
  IF to_regprocedure('public.v13_control_operator()') IS NULL
     OR to_regprocedure('public.v13_state_hash(uuid)') IS NULL THEN
    RAISE EXCEPTION 'v13: goal baseline';
  END IF;
  SELECT prosrc INTO v_src
    FROM pg_proc
   WHERE oid = 'public.v13_state_hash(uuid)'::regprocedure;
  IF position('session/completed' IN v_src) = 0
     OR position('session/failed' IN v_src) = 0
     OR position('session/cancelled' IN v_src) = 0
     OR position('goal/stopped' IN v_src) > 0
     OR position('goal/resumed' IN v_src) > 0
     OR position('control/handoff' IN v_src) > 0 THEN
    RAISE EXCEPTION 'v13: goal baseline';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.events
     WHERE type IN ('goal/stopped', 'goal/resumed')) THEN
    SELECT string_agg(session_id::text || ':' || seq::text, ',' ORDER BY session_id, seq)
      INTO v_listed
      FROM public.events
     WHERE type IN ('goal/stopped', 'goal/resumed');
    RAISE EXCEPTION 'v13: goal baseline %', v_listed;
  END IF;
END
$govern_base$;

CREATE FUNCTION public.v13_goal_fingerprint(p_sid uuid) RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_turn integer;
  v_name text;
  v_ver integer;
  v_probe jsonb;
  v_max text;
  v_effects jsonb;
  v_events jsonb;
  v_input jsonb;
BEGIN
  SELECT turn_no, route_policy_name, route_policy_version
    INTO v_turn, v_name, v_ver
    FROM public.sessions
   WHERE session_id = p_sid;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  v_probe := public.v13_probe(p_sid);
  SELECT coalesce(max(seq)::text, '-1') INTO v_max
    FROM public.events
   WHERE session_id = p_sid
     AND type NOT IN (
       'session/completed', 'session/failed', 'session/cancelled',
       'goal/stopped', 'goal/resumed', 'control/handoff',
       'wake/satisfied', 'turn/material_spent');
  SELECT coalesce(jsonb_agg(row_j ORDER BY eid), '[]'::jsonb) INTO v_effects
    FROM (
      SELECT effect_id::text AS eid,
             jsonb_build_array(effect_id::text, kind, status, attempt_no::text, fence::text,
                               coalesce(tool_name, ''), request_hash, origin_user_seq::text) AS row_j
        FROM public.effects
       WHERE session_id = p_sid) s;
  SELECT coalesce(jsonb_agg(row_j ORDER BY seq), '[]'::jsonb) INTO v_events
    FROM (
      SELECT seq,
             jsonb_build_array(seq::text, type, payload_hash, coalesce(source_effect_id::text, '')) AS row_j
        FROM public.events
       WHERE session_id = p_sid
         AND type NOT IN (
           'session/completed', 'session/failed', 'session/cancelled',
           'goal/stopped', 'goal/resumed', 'control/handoff',
           'wake/satisfied', 'turn/material_spent')) s;
  v_input := jsonb_build_array(
    'v1',
    jsonb_build_array(p_sid::text, v_turn::text, coalesce(v_name, ''), v_ver::text,
                      coalesce(v_probe->>'goal_hash', ''),
                      coalesce(v_probe->>'tools_revision', ''),
                      coalesce(v_probe->>'candidate_generation_revision', ''),
                      v_max),
    v_effects, v_events);
  RETURN pg_catalog.encode(public.digest(v_input::text, 'sha256'), 'hex');
END
$function$;

CREATE FUNCTION public.v13_goal_fold(p_sid uuid)
RETURNS TABLE(state text, stop_fp text)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_type text;
  v_fp text;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT e.type, e.payload->>'fingerprint'
    INTO v_type, v_fp
    FROM public.events e
   WHERE e.session_id = p_sid
     AND e.type IN ('goal/stopped', 'goal/resumed')
   ORDER BY seq DESC
   LIMIT 1;
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'running'::text, NULL::text;
    RETURN;
  END IF;
  IF v_type = 'goal/stopped' THEN
    RETURN QUERY SELECT 'stopped'::text, v_fp;
  ELSE
    RETURN QUERY SELECT 'running'::text, v_fp;
  END IF;
  RETURN;
END
$function$;

CREATE FUNCTION public.v13_goal_lifecycle(p_sid uuid) RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $function$
  SELECT state FROM public.v13_goal_fold(p_sid)
$function$;

CREATE FUNCTION public.v13_goal_event_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_status text;
  v_next bigint;
  v_turn integer;
  v_state text;
  v_stop_fp text;
  v_fp text;
  v_payload_fp text;
BEGIN
  IF NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  PERFORM 1
     FROM public.sessions
    WHERE session_id = NEW.session_id
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', NEW.session_id;
  END IF;
  SELECT status, next_seq, turn_no
    INTO v_status, v_next, v_turn
    FROM public.sessions
   WHERE session_id = NEW.session_id;
  SELECT state, stop_fp
    INTO v_state, v_stop_fp
    FROM public.v13_goal_fold(NEW.session_id);
  IF (NEW.seq::numeric + 1) IS DISTINCT FROM v_next::numeric
     OR NEW.turn_no IS DISTINCT FROM v_turn THEN
    RAISE EXCEPTION 'v13: goal seq';
  END IF;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.effects
     WHERE session_id = NEW.session_id
       AND status IN ('ready', 'claimed', 'unknown')) THEN
    RAISE EXCEPTION 'v13: goal busy';
  END IF;
  IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: goal payload';
  END IF;
  IF NEW.source_effect_id IS NOT NULL THEN
    RAISE EXCEPTION 'v13: goal source';
  END IF;
  IF public.v13_json_keys(NEW.payload) IS DISTINCT FROM
     ARRAY['fingerprint', 'reason', 'schema_version'] THEN
    RAISE EXCEPTION 'v13: goal payload';
  END IF;
  IF NOT public.v13_json_int_ok(NEW.payload->'schema_version', 1)
     OR NEW.payload->'schema_version' IS DISTINCT FROM '1'::jsonb THEN
    RAISE EXCEPTION 'v13: goal payload';
  END IF;
  IF jsonb_typeof(NEW.payload->'reason') IS DISTINCT FROM 'string'
     OR jsonb_typeof(NEW.payload->'fingerprint') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: goal payload';
  END IF;
  IF (NEW.payload->>'fingerprint') !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: goal payload';
  END IF;
  IF char_length(NEW.payload->>'reason') < 1
     OR char_length(NEW.payload->>'reason') > 256 THEN
    RAISE EXCEPTION 'v13: goal payload';
  END IF;
  IF NEW.type = 'goal/resumed' AND v_state IS DISTINCT FROM 'stopped' THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  IF NEW.type = 'goal/stopped' AND v_state = 'stopped' THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  v_fp := public.v13_goal_fingerprint(NEW.session_id);
  v_payload_fp := NEW.payload->>'fingerprint';
  IF NEW.type = 'goal/stopped' THEN
    IF v_fp IS DISTINCT FROM v_payload_fp THEN
      RAISE EXCEPTION 'v13: goal fingerprint';
    END IF;
  ELSIF v_state = 'stopped' AND NEW.type = 'goal/resumed' THEN
    IF v_fp IS DISTINCT FROM v_payload_fp
       OR v_payload_fp IS DISTINCT FROM v_stop_fp THEN
      RAISE EXCEPTION 'v13: goal fingerprint';
    END IF;
  END IF;
  RETURN NEW;
END
$function$;

CREATE TRIGGER trg_v13_goal_event_guard
  BEFORE INSERT ON public.events
  FOR EACH ROW
  WHEN (NEW.type IN ('goal/stopped', 'goal/resumed'))
  EXECUTE FUNCTION public.v13_goal_event_guard();

CREATE INDEX ix_events_goal_lifecycle
  ON public.events (session_id, seq DESC)
  WHERE type IN ('goal/stopped', 'goal/resumed');

CREATE FUNCTION public.v13_goal_stop(p_sid uuid, p_reason text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_status text;
  v_state text;
  v_stop_fp text;
  v_fp text;
  v_payload jsonb;
BEGIN
  IF NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  PERFORM 1
     FROM public.sessions
    WHERE session_id = p_sid
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  IF NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  SELECT state, stop_fp
    INTO v_state, v_stop_fp
    FROM public.v13_goal_fold(p_sid);
  SELECT status INTO v_status
    FROM public.sessions
   WHERE session_id = p_sid;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.effects
     WHERE session_id = p_sid
       AND status IN ('ready', 'claimed', 'unknown')) THEN
    RAISE EXCEPTION 'v13: goal busy';
  END IF;
  IF v_state = 'stopped' THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  v_fp := public.v13_goal_fingerprint(p_sid);
  v_payload := jsonb_build_object(
    'schema_version', 1,
    'fingerprint', v_fp,
    'reason', p_reason);
  PERFORM public.v13_append_event(
    p_sid, pg_catalog.gen_random_uuid(), 'goal/stopped', v_payload, NULL);
  RETURN v_payload;
END
$function$;

CREATE FUNCTION public.v13_goal_resume(p_sid uuid, p_reason text) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_status text;
  v_state text;
  v_stop_fp text;
  v_fp text;
  v_payload jsonb;
BEGIN
  IF NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  PERFORM 1
     FROM public.sessions
    WHERE session_id = p_sid
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  IF NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  SELECT state, stop_fp
    INTO v_state, v_stop_fp
    FROM public.v13_goal_fold(p_sid);
  SELECT status INTO v_status
    FROM public.sessions
   WHERE session_id = p_sid;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.effects
     WHERE session_id = p_sid
       AND status IN ('ready', 'claimed', 'unknown')) THEN
    RAISE EXCEPTION 'v13: goal busy';
  END IF;
  IF v_state IS DISTINCT FROM 'stopped' THEN
    RAISE EXCEPTION 'v13: goal lifecycle';
  END IF;
  v_fp := public.v13_goal_fingerprint(p_sid);
  IF v_fp IS DISTINCT FROM v_stop_fp THEN
    RAISE EXCEPTION 'v13: goal fingerprint';
  END IF;
  v_payload := jsonb_build_object(
    'schema_version', 1,
    'fingerprint', v_fp,
    'reason', p_reason);
  PERFORM public.v13_append_event(
    p_sid, pg_catalog.gen_random_uuid(), 'goal/resumed', v_payload, NULL);
  RETURN v_payload;
END
$function$;

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'should_run',
  3,
  '{"schema_version":1,"gates":[{"id":"human_pending","effect":"block"},{"id":"unknown_wall","effect":"block"},{"id":"unconsumed_cancel","effect":"block"},{"id":"duty_cycle","effect":"shadow"},{"id":"quota_window","effect":"block"},{"id":"capabilities","effect":"block"},{"id":"goal_stopped","effect":"block"}]}'::jsonb,
  false);

UPDATE public.v13_policies SET active = false
 WHERE name = 'should_run' AND version = 2;

UPDATE public.v13_policies SET active = true
 WHERE name = 'should_run' AND version = 3;

CREATE OR REPLACE FUNCTION public.v13_should_run_gate(p_sid uuid) RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_pol jsonb;
  v_elem jsonb;
  v_id text;
  v_effect text;
  v_seen text[] := '{}';
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT value INTO v_pol
    FROM public.v13_policies
   WHERE name = 'should_run' AND active;
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_pol) IS DISTINCT FROM ARRAY['gates', 'schema_version']
     OR v_pol->'schema_version' IS DISTINCT FROM '1'::jsonb
     OR jsonb_typeof(v_pol->'gates') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: should_run policy';
  END IF;
  FOR v_elem IN SELECT value FROM jsonb_array_elements(v_pol->'gates') LOOP
    IF jsonb_typeof(v_elem) IS DISTINCT FROM 'object'
       OR public.v13_json_keys(v_elem) IS DISTINCT FROM ARRAY['effect', 'id']
       OR jsonb_typeof(v_elem->'id') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_elem->'effect') IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'v13: should_run policy';
    END IF;
    v_id := v_elem->>'id';
    v_effect := v_elem->>'effect';
    IF v_id IS NULL OR v_id = ''
       OR v_id = ANY (v_seen)
       OR v_id NOT IN ('human_pending', 'unknown_wall', 'unconsumed_cancel', 'duty_cycle', 'quota_window', 'capabilities', 'goal_stopped')
       OR v_effect NOT IN ('block', 'shadow') THEN
      RAISE EXCEPTION 'v13: should_run gate';
    END IF;
    v_seen := v_seen || v_id;
  END LOOP;
  FOR v_elem IN SELECT value FROM jsonb_array_elements(v_pol->'gates') LOOP
    v_id := v_elem->>'id';
    v_effect := v_elem->>'effect';
    IF v_id = 'human_pending' AND public.v13_pending_human(p_sid) THEN
      IF v_effect = 'block' THEN
        RETURN v_id;
      END IF;
    ELSIF v_id = 'unknown_wall'
          AND (EXISTS (
                 SELECT 1 FROM public.sessions
                  WHERE session_id = p_sid AND status = 'blocked_unknown')
               OR EXISTS (
                 SELECT 1 FROM public.effects
                  WHERE session_id = p_sid AND status = 'unknown')) THEN
      IF v_effect = 'block' THEN
        RETURN v_id;
      END IF;
    ELSIF v_id = 'unconsumed_cancel' AND public.v13_unconsumed_cancel(p_sid) THEN
      IF v_effect = 'block' THEN
        RETURN v_id;
      END IF;
    ELSIF v_id = 'duty_cycle' AND public.v13_triage_duty() = 0 THEN
      IF v_effect = 'block' THEN
        RETURN v_id;
      END IF;
    ELSIF v_id = 'quota_window' AND NOT public.v13_quota_eligible(p_sid) THEN
      IF v_effect = 'block' THEN
        RETURN v_id;
      END IF;
    ELSIF v_id = 'capabilities' AND EXISTS (
            SELECT 1 FROM public.v13_missing_capabilities(p_sid)) THEN
      IF v_effect = 'block' THEN
        RETURN v_id;
      END IF;
    ELSIF v_id = 'goal_stopped' THEN
      IF EXISTS (
           SELECT 1 FROM public.sessions
            WHERE session_id = p_sid
              AND status NOT IN ('completed', 'failed', 'cancelled')) THEN
        IF public.v13_goal_lifecycle(p_sid) = 'stopped' AND v_effect = 'block' THEN
          RETURN v_id;
        END IF;
      END IF;
    END IF;
  END LOOP;
  RETURN NULL;
END
$function$;

CREATE OR REPLACE FUNCTION public.v13_recover_idle()
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_sid uuid; v_fp text; v_nudged int := 0; v_pending uuid[] := '{}'; v_st text;
BEGIN
  FOR v_sid IN
    SELECT s.session_id
      FROM sessions s
     WHERE s.status IN ('ready', 'waiting')
       AND NOT EXISTS (
         SELECT 1 FROM effects e
          WHERE e.session_id = s.session_id
            AND e.status IN ('ready', 'claimed', 'unknown'))
     ORDER BY s.session_id
     FOR UPDATE OF s SKIP LOCKED
  LOOP
    SELECT status INTO v_st FROM sessions WHERE session_id = v_sid;
    IF v_st NOT IN ('ready', 'waiting')
       OR EXISTS (
         SELECT 1 FROM effects e
          WHERE e.session_id = v_sid
            AND e.status IN ('ready', 'claimed', 'unknown')) THEN
      CONTINUE;
    END IF;
    IF v13_triage_hold_blocks_recover(v_sid) THEN
      CONTINUE;
    END IF;
    IF public.v13_goal_lifecycle(v_sid) = 'stopped' THEN
      CONTINUE;
    END IF;
    IF EXISTS (SELECT 1 FROM sessions c WHERE c.parent_session_id = v_sid)
       AND NOT v13_direct_children_open(v_sid) THEN
      SELECT encode(digest((
        SELECT jsonb_agg(jsonb_build_array(c.session_id::text, c.status) ORDER BY c.session_id)
          FROM sessions c WHERE c.parent_session_id = v_sid)::text, 'sha256'), 'hex')
        INTO v_fp;
      v_nudged := v_nudged + v13_insert_nudge(v_sid, 'children_terminal', v_fp);
    END IF;
    IF EXISTS (SELECT 1 FROM events WHERE session_id = v_sid AND type = 'repair/required') THEN
      SELECT jsonb_agg(seq ORDER BY seq)::text INTO v_fp
        FROM events WHERE session_id = v_sid AND type = 'repair/required';
      v_nudged := v_nudged + v13_insert_nudge(v_sid, 'repair', v_fp);
    END IF;
    IF EXISTS (SELECT 1 FROM events WHERE session_id = v_sid AND type = 'replan/required') THEN
      SELECT jsonb_agg(seq ORDER BY seq)::text INTO v_fp
        FROM events WHERE session_id = v_sid AND type = 'replan/required';
      v_nudged := v_nudged + v13_insert_nudge(v_sid, 'replan', v_fp);
    END IF;
    IF (EXISTS (SELECT 1 FROM sessions c WHERE c.parent_session_id = v_sid)
        AND NOT v13_direct_children_open(v_sid))
       OR EXISTS (SELECT 1 FROM events WHERE session_id = v_sid AND type = 'repair/required')
       OR EXISTS (SELECT 1 FROM events WHERE session_id = v_sid AND type = 'replan/required') THEN
      v_pending := v_pending || v_sid;
    END IF;
  END LOOP;
  RETURN jsonb_build_object(
    'pending', coalesce((SELECT jsonb_agg(x ORDER BY x) FROM unnest(v_pending) x), '[]'::jsonb),
    'nudged', v_nudged);
END
$function$;

CREATE OR REPLACE FUNCTION public.v13_scheduler_hint(p_sid uuid) RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_st text;
  v_requested integer;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT status INTO v_st
    FROM public.sessions
   WHERE session_id = p_sid;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN 'dont_notify';
  END IF;
  IF public.v13_unconsumed_cancel(p_sid) THEN
    IF EXISTS (
      SELECT 1 FROM public.effects
       WHERE session_id = p_sid
         AND status IN ('claimed', 'unknown')) THEN
      RETURN 'wait';
    END IF;
    RETURN 'run_now';
  END IF;
  IF public.v13_goal_lifecycle(p_sid) = 'stopped' THEN
    RETURN 'dont_notify';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.effects
     WHERE session_id = p_sid
       AND status IN ('ready', 'claimed', 'unknown')) THEN
    RETURN 'wait';
  ELSIF public.v13_pending_human(p_sid) THEN
    RETURN 'wait';
  ELSIF public.v13_triage_duty() = 0 THEN
    RETURN 'wait';
  ELSIF NOT public.v13_should_run(p_sid) THEN
    RETURN 'wait';
  END IF;
  SELECT count(*)::integer INTO v_requested
    FROM public.events AS e
   WHERE e.session_id = p_sid
     AND e.type = 'tool/call'
     AND e.seq > public.v13_last_user_seq(p_sid)
     AND NOT EXISTS (
       SELECT 1 FROM public.events AS c
        WHERE c.session_id = p_sid
          AND c.type = 'child-created'
          AND c.payload->>'tool_call_id' = e.payload->>'id');
  IF v_requested > 0
     AND NOT public.v13_spawn_budget_snapshot(p_sid, v_requested) THEN
    RETURN 'wait';
  END IF;
  RETURN 'run_now';
END
$function$;


DROP FUNCTION public.v13_attention(uuid, integer);

CREATE FUNCTION public.v13_attention(p_root uuid, p_max_rows integer DEFAULT 512)
RETURNS TABLE (
  attention_rank bigint,
  session_id uuid,
  parent_session_id uuid,
  depth integer,
  status text,
  spawn_kind text,
  turn_no integer,
  is_terminal boolean,
  should_run boolean,
  blocked_by text,
  lifecycle text
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_n integer := 0;
  v_i integer;
  v_sid uuid[] := '{}';
  v_parent uuid[] := '{}';
  v_depth integer[] := '{}';
  v_status text[] := '{}';
  v_kind text[] := '{}';
  v_turn integer[] := '{}';
  v_term boolean[] := '{}';
  v_blocked text[] := '{}';
  v_life text[] := '{}';
  r record;
BEGIN
  IF p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 1024 THEN
    RAISE EXCEPTION 'v13: attention limit';
  END IF;
  FOR r IN
    SELECT t.session_id, t.parent_session_id, t.depth, t.status,
           t.spawn_kind, t.turn_no, t.is_terminal
      FROM public.v_goal_tree(p_root) AS t
  LOOP
    v_n := v_n + 1;
    v_sid := array_append(v_sid, r.session_id);
    v_parent := array_append(v_parent, r.parent_session_id);
    v_depth := array_append(v_depth, r.depth);
    v_status := array_append(v_status, r.status);
    v_kind := array_append(v_kind, r.spawn_kind);
    v_turn := array_append(v_turn, r.turn_no);
    v_term := array_append(v_term, r.is_terminal);
  END LOOP;
  IF v_n > p_max_rows THEN
    RAISE EXCEPTION 'v13: attention limit';
  END IF;
  FOR v_i IN 1..v_n LOOP
    v_blocked := array_append(v_blocked, public.v13_should_run_gate(v_sid[v_i]));
    v_life := array_append(v_life, public.v13_goal_lifecycle(v_sid[v_i]));
  END LOOP;
  v_i := 0;
  FOR r IN
    SELECT u.session_id, u.parent_session_id, u.depth, u.status,
           u.spawn_kind, u.turn_no, u.is_terminal, u.blocked_by, u.lifecycle
      FROM unnest(v_sid, v_parent, v_depth, v_status, v_kind, v_turn, v_term, v_blocked, v_life)
        AS u(session_id, parent_session_id, depth, status, spawn_kind, turn_no,
             is_terminal, blocked_by, lifecycle)
     ORDER BY u.is_terminal ASC,
              CASE u.blocked_by
                WHEN 'human_pending' THEN 1
                WHEN 'unknown_wall' THEN 2
                WHEN 'goal_stopped' THEN 3
                WHEN 'unconsumed_cancel' THEN 4
                WHEN 'quota_window' THEN 5
                WHEN 'capabilities' THEN 6
                WHEN 'duty_cycle' THEN 7
                ELSE 8
              END ASC,
              u.depth ASC,
              u.session_id ASC
  LOOP
    v_i := v_i + 1;
    attention_rank := v_i;
    session_id := r.session_id;
    parent_session_id := r.parent_session_id;
    depth := r.depth;
    status := r.status;
    spawn_kind := r.spawn_kind;
    turn_no := r.turn_no;
    is_terminal := r.is_terminal;
    blocked_by := r.blocked_by;
    should_run := r.blocked_by IS NULL;
    lifecycle := r.lifecycle;
    RETURN NEXT;
  END LOOP;
  RETURN;
END
$function$;

CREATE FUNCTION public.v13_spawn_batch_allowed(p_sid uuid, p_requested integer)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $function$
DECLARE
  v_parent uuid;
  v_root uuid;
  v_depth integer := 0;
  v_seen uuid[];
BEGIN
  PERFORM 1
     FROM public.sessions
    WHERE session_id = p_sid
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  v_root := p_sid;
  v_seen := ARRAY[p_sid];
  LOOP
    SELECT parent_session_id INTO v_parent
      FROM public.sessions
     WHERE session_id = v_root;
    EXIT WHEN v_parent IS NULL;
    v_depth := v_depth + 1;
    IF v_depth > 64 OR v_parent = ANY (v_seen) THEN
      RAISE EXCEPTION 'v13: spawn root cycle';
    END IF;
    v_seen := pg_catalog.array_append(v_seen, v_parent);
    v_root := v_parent;
  END LOOP;
  PERFORM public.v13_policy_share();
  PERFORM pg_catalog.pg_advisory_xact_lock(
    public.v13_advisory_class('spawn_budget'),
    pg_catalog.hashtext(v_root::text));
  RETURN public.v13_spawn_budget_snapshot(p_sid, p_requested, v_root);
END
$function$;

ALTER FUNCTION public.v13_spawn_batch_allowed(uuid, integer) OWNER TO v13_spawn_owner;

CREATE OR REPLACE FUNCTION public.v13_advance(p_sid uuid, p_snap jsonb)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_now jsonb; v_route jsonb; v_cycles int; v_max int;
  v_effect uuid; v_est text; v_res jsonb; v_handler text; v_req jsonb; v_err jsonb;
  v_pred uuid; v_prow effects; v_sig text[]; v_ev text[]; v_cand boolean;
  v_cap_new boolean; v_cont boolean; v_idx bigint; v_st text;
  v_calls jsonb; v_sreq jsonb; v_triage text;
BEGIN
  IF p_snap IS NULL
     OR (p_snap->'snap'->>'sid') IS DISTINCT FROM p_sid::text
     OR (p_snap->'envelope'->>'sid') IS DISTINCT FROM p_sid::text THEN
    RAISE EXCEPTION 'v13: advance/snapshot session mismatch (p=%, snap=%, env=%)',
      p_sid, p_snap->'snap'->>'sid', p_snap->'envelope'->>'sid';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  v_now := v13_probe(p_sid);
  IF (v_now->>'session_version', v_now->>'max_event_seq', v_now->>'goal_hash',
      v_now->>'route_policy_name', v_now->>'route_policy_version',
      v_now->>'tools_revision', v_now->>'candidate_generation_revision')
     IS DISTINCT FROM
     (p_snap->'snap'->>'session_version', p_snap->'snap'->>'max_event_seq',
      p_snap->'snap'->>'goal_hash', p_snap->'snap'->>'route_policy_name',
      p_snap->'snap'->>'route_policy_version', p_snap->'snap'->>'tools_revision',
      p_snap->'snap'->>'candidate_generation_revision') THEN
    RETURN 'stale';
  END IF;
  PERFORM v13_bind_worktree_from_prepare(p_sid);
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN 'terminal';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'unknown')
     OR v_st = 'blocked_unknown' THEN
    IF v_st NOT IN ('blocked_unknown', 'completed', 'failed', 'cancelled') THEN
      RAISE EXCEPTION 'v13: unknown wall drift';
    END IF;
    IF v13_unconsumed_cancel(p_sid) THEN
      UPDATE effects SET status = 'cancelled', fence = fence + 1, error = NULL,
             lease_owner = NULL, lease_until = NULL
       WHERE session_id = p_sid AND status = 'ready';
    END IF;
    RETURN 'waiting';
  END IF;
  IF v13_unconsumed_cancel(p_sid) THEN
    UPDATE effects SET status = 'cancelled', fence = fence + 1, error = NULL,
           lease_owner = NULL, lease_until = NULL
     WHERE session_id = p_sid AND status = 'ready';
    IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'claimed') THEN
      UPDATE sessions SET status = 'waiting'
       WHERE session_id = p_sid AND status IN ('ready', 'waiting');
      RETURN 'waiting';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed', 'unknown')) THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'cancelled', 'cancel', false);
      RETURN 'terminal';
    END IF;
    RETURN 'waiting';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status IN ('ready', 'claimed')) THEN
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'tool_call_id', e.payload->>'id',
           'task', e.payload->'args'->>'task') ORDER BY e.seq), '[]'::jsonb)
    INTO v_calls
    FROM events e
   WHERE e.session_id = p_sid
     AND e.type = 'tool/call'
     AND e.seq > v13_last_user_seq(p_sid)
     AND NOT EXISTS (
       SELECT 1 FROM events c
        WHERE c.session_id = p_sid AND c.type = 'child-created'
          AND c.payload->>'tool_call_id' = e.payload->>'id');
  PERFORM v13_triage_block_explore_spawn(p_sid);
  PERFORM public.v13_policy_share();
  IF jsonb_array_length(v_calls) > 0 THEN
    IF NOT public.v13_should_run(p_sid) THEN
      UPDATE public.sessions SET status = 'waiting'
       WHERE session_id = p_sid AND status IN ('ready', 'waiting');
      RETURN 'waiting';
    ELSIF NOT public.v13_spawn_batch_allowed(p_sid, jsonb_array_length(v_calls)) THEN
      UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid AND status IN ('ready','waiting');
      RETURN 'waiting';
    END IF;
    v_calls := v13_spawn_children(v_calls);
    v_sreq := v13_spawn_request(v_calls);
    v_effect := v13_effect_id(p_sid, 'tool', v_sreq);
    v_res := v13_spawn_subsession(p_sid, jsonb_build_object(
      'schema_version', 1, 'children', v_calls));
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route',
      jsonb_build_object('action', 'sql', 'reason', 'spawn_fanout',
                         'tool', 'spawn_subsession', 'params', '{}'::jsonb));
    INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash,
                         idempotency_key, status, result, error, origin_user_seq)
    VALUES (v_effect, p_sid, 'tool', 'spawn_subsession', v_sreq,
            encode(digest(v_sreq::text, 'sha256'), 'hex'),
            'v13:' || v_effect::text,
            'succeeded', v_res, NULL, v13_last_user_seq(p_sid));
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'tool/result',
      jsonb_build_object('tool', 'spawn_subsession', 'result', v_res,
                         'origin_user_seq', v13_last_user_seq(p_sid)), v_effect);
    RETURN 'progressed';
  END IF;
  v_pred := v13_harness_predecessor(p_sid);
  IF v_pred IS NOT NULL THEN
    PERFORM v13_harness_tail_gap(p_sid, v_pred);
    SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
    IF v_prow.status IN ('unknown', 'ready', 'claimed') THEN
      RAISE EXCEPTION 'v13: harness predecessor active';
    END IF;
    IF v_prow.status = 'succeeded' THEN
      SELECT coalesce(array_agg(x ORDER BY x), '{}') INTO v_sig
        FROM jsonb_array_elements_text(
          CASE WHEN v_prow.result ? 'signals' THEN v_prow.result->'signals' ELSE '[]'::jsonb END) x;
      SELECT coalesce(array_agg(type ORDER BY type), '{}') INTO v_ev
        FROM events
       WHERE source_effect_id = v_pred AND type IN ('repair/required', 'replan/required');
      IF v_sig IS DISTINCT FROM v_ev THEN
        RAISE EXCEPTION 'v13: signals ledger';
      END IF;
      v_cand := v_prow.result->>'result_kind' = 'finish'
        OR (v_prow.result->>'result_kind' = 'progress' AND NOT EXISTS (
              SELECT 1 FROM events WHERE source_effect_id = v_pred
                AND type IN ('repair/required', 'replan/required')));
      IF v_cand THEN
        IF EXISTS (
          SELECT 1 FROM events ev
          JOIN effects src ON src.effect_id = ev.source_effect_id
           WHERE ev.session_id = p_sid AND ev.type = 'turn/material_spent'
             AND src.request->>'logical_turn_id' = v_prow.request->>'logical_turn_id'
             AND ev.source_effect_id IS DISTINCT FROM v_pred) THEN
          RAISE EXCEPTION 'v13: material ledger';
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM events WHERE source_effect_id = v_pred AND type = 'turn/material_spent') THEN
          PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/material_spent',
            jsonb_build_object('schema_version', 1, 'effect_id', v_pred::text), v_pred);
        END IF;
      END IF;
      IF v_prow.result->>'result_kind' = 'finish' THEN
        IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'completed', 'harness_finish', false);
        RETURN 'terminal';
      ELSIF v_prow.result->>'result_kind' = 'reject' THEN
        IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'harness_reject', false);
        RETURN 'terminal';
      END IF;
      IF v_prow.result->>'result_kind' = 'wait'
         AND v_prow.result->>'wait_reason' IN ('evidence', 'quota')
         AND NOT EXISTS (
           SELECT 1 FROM events WHERE source_effect_id = v_pred AND type = 'wake/satisfied') THEN
        IF NOT v13_wake_is_satisfied_v1(p_sid, v_pred, v_prow.result->'wake') THEN
          UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
          RETURN 'waiting';
        END IF;
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'wake/satisfied',
          jsonb_build_object('effect_id', v_pred::text, 'wake_kind', v_prow.result->'wake'->>'kind'),
          v_pred);
      END IF;
      IF v_prow.result->>'result_kind' = 'wait' AND v_prow.result->>'wait_reason' = 'approval'
         AND NOT EXISTS (
           SELECT 1 FROM effects h
            WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
              AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id') THEN
        IF NOT public.v13_should_run(p_sid) THEN
          UPDATE public.sessions SET status = 'waiting'
           WHERE session_id = p_sid AND status IN ('ready', 'waiting');
          RETURN 'waiting';
        END IF;
        IF EXISTS (
          SELECT 1 FROM effects h
           WHERE h.session_id = p_sid AND h.kind = 'human'
             AND h.status IN ('ready', 'claimed', 'unknown')) THEN
          RAISE EXCEPTION 'v13: approval human exists';
        END IF;
        IF v13_cycle_no(p_sid) >= (v13_policy('turn_budget')->>'max_cycles')::int THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
          RETURN 'terminal';
        END IF;
        v_effect := v13_enqueue_effect(p_sid, 'human',
          jsonb_build_object('schema_version', 1,
                             'interaction_ref', v_prow.result->>'interaction_id'));
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'approval_exhausted', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
      v_cap_new := v13_cap_human_answered(p_sid, v_pred);
      v_cont := false;
      IF NOT v_cap_new THEN
        IF v_prow.result->>'result_kind' = 'progress' AND EXISTS (
             SELECT 1 FROM events WHERE source_effect_id = v_pred
               AND type IN ('repair/required', 'replan/required')) THEN
          v_cont := true;
        ELSIF v_prow.result->>'result_kind' = 'wait' AND (
              (v_prow.result->>'wait_reason' = 'approval' AND EXISTS (
                 SELECT 1 FROM effects h
                  WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
                    AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id'))
              OR (v_prow.result->>'wait_reason' IN ('evidence', 'quota') AND EXISTS (
                 SELECT 1 FROM events WHERE source_effect_id = v_pred AND type = 'wake/satisfied'))) THEN
          v_cont := true;
        END IF;
      END IF;
      IF v_cont THEN
        IF NOT public.v13_should_run(p_sid) THEN
          UPDATE public.sessions SET status = 'waiting'
           WHERE session_id = p_sid AND status IN ('ready', 'waiting');
          RETURN 'waiting';
        END IF;
        IF v13_cycle_no(p_sid) >= (v13_policy('turn_budget')->>'max_cycles')::int THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
          RETURN 'terminal';
        END IF;
        v_idx := (v_prow.request->>'continuation_index')::bigint;
        IF v_idx >= 2147483647 THEN
          RAISE EXCEPTION 'v13: continuation_index overflow';
        END IF;
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route',
          jsonb_build_object('action', 'tool', 'reason', 'harness_continuation',
                             'tool', 'harness_turn', 'params', '{}'::jsonb));
        v_req := jsonb_build_object(
          'tool', 'harness_turn',
          'params', '{}'::jsonb,
          'handler', v_prow.request->'handler',
          'tools_revision', v_prow.request->'tools_revision',
          'logical_turn_id', v_prow.request->'logical_turn_id',
          'continuation_index', v_idx + 1);
        v_effect := v13_enqueue_effect(p_sid, 'tool', v_req, 'harness_turn');
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'harness_attempts', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
    END IF;
  END IF;
  IF public.v13_triage_duty()<>0
     AND NOT public.v13_should_run(p_sid)
     AND p_snap->>'failed' IS NOT NULL THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('remaining', p_snap->'snap'->>'gap_count',
                         'origin_user_seq', v13_last_user_seq(p_sid)));
  END IF;
  v_triage := v13_triage_prework(p_sid);
  IF v_triage IS NOT NULL THEN
    RETURN v_triage;
  END IF;
  IF coalesce((p_snap->>'failed')::boolean, false) THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('remaining', p_snap->'snap'->>'gap_count',
                         'origin_user_seq', v13_last_user_seq(p_sid)));
    RETURN 'progressed';
  END IF;
  IF coalesce((p_snap->>'abandon')::boolean, false) THEN
    v_effect := v13_enqueue_effect(p_sid, 'human', jsonb_build_object('reason', 'resolve_budget'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est = 'succeeded' THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'resolve_budget', false);
      RETURN 'terminal';
    ELSIF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'resolve_budget', true);
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  IF NOT v13_context_fresh(p_sid) THEN
    v_effect := v13_enqueue_effect(p_sid, 'context_refresh',
      jsonb_build_object('goal_hash', p_snap->'snap'->>'goal_hash'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'context_refresh', true);
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  v_cycles := v13_cycle_no(p_sid);
  v_max := (v13_policy('turn_budget')->>'max_cycles')::int;
  IF v_cycles >= v_max THEN
    v_effect := v13_enqueue_effect(p_sid, 'human', jsonb_build_object('reason', 'budget_exhausted'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est = 'succeeded' THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', false);
      RETURN 'terminal';
    ELSIF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'budget_exhausted', true);
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;
  IF (p_snap->>'remaining')::int > 0 THEN
    v_effect := v13_enqueue_effect(p_sid, 'judge',
      jsonb_build_object('envelope', v13_effect_envelope(p_snap->'envelope')));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est IN ('failed', 'cancelled') THEN
      IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'judge_attempts', true);
      RETURN 'terminal';
    ELSIF v_est <> 'succeeded' THEN
      PERFORM v13_send_work(v_effect);
      UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
      RETURN 'waiting';
    END IF;
  END IF;
  v_triage := v13_triage_steer(p_sid);
  IF v_triage IS NOT NULL THEN
    RETURN v_triage;
  END IF;
  v_route := v13_route(p_sid, p_snap->'envelope');
  v_route := v13_triage_after_route(p_sid, v_route);
  IF v_route->>'action' = 'sql' AND v13_is_harness_tool(v_route->>'tool', 'tool') THEN
    RAISE EXCEPTION 'v13: harness_turn kind';
  END IF;
  IF v_route->>'action' = 'sql' AND v13_is_spawn_tool(v_route->>'tool', 'sql') THEN
    RAISE EXCEPTION 'v13: spawn batch-dispatched';
  END IF;
  IF v_route->>'action' = 'tool' AND v13_is_harness_tool(v_route->>'tool', 'tool') THEN
    v_pred := v13_harness_predecessor(p_sid);
    IF v_pred IS NOT NULL THEN
      SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
      IF v_prow.status IN ('failed', 'cancelled') THEN
        PERFORM v13_harness_tail_gap(p_sid, v_pred);
        v_effect := v13_enqueue_effect(p_sid, 'tool', v_prow.request, v_prow.tool_name);
        PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
        SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
        IF v_est IN ('failed', 'cancelled') THEN
          IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'harness_attempts', true);
          RETURN 'terminal';
        END IF;
        PERFORM v13_send_work(v_effect);
        UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
    END IF;
  END IF;
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
  CASE v_route->>'action'
  WHEN 'sql' THEN
    IF v13_is_harness_tool(v_route->>'tool', 'tool') THEN
      RAISE EXCEPTION 'v13: harness_turn kind';
    END IF;
    IF v13_is_spawn_tool(v_route->>'tool', 'sql') THEN
      RAISE EXCEPTION 'v13: spawn batch-dispatched';
    END IF;
    SELECT t->>'handler' INTO v_handler
      FROM jsonb_array_elements(p_snap->'envelope'->'tools_catalog') t
     WHERE t->>'name' = v_route->>'tool' AND t->>'kind' = 'sql'
       AND (t->>'enabled')::boolean;
    v_req := jsonb_build_object('tool', v_route->>'tool',
                                'params', coalesce(v_route->'params', '{}'::jsonb));
    v_err := NULL;
    BEGIN
      EXECUTE format('SELECT %s($1, $2)', v_handler)
         INTO v_res USING p_sid, coalesce(v_route->'params', '{}'::jsonb);
    EXCEPTION
      WHEN query_canceled THEN
        IF coalesce(current_setting('statement_timeout', true), '0') IN ('0', '0ms') THEN
          RAISE;
        END IF;
        v_res := NULL;
        v_err := jsonb_build_object('sqlstate', SQLSTATE, 'message', SQLERRM);
      WHEN OTHERS THEN
        v_res := NULL;
        v_err := jsonb_build_object('sqlstate', SQLSTATE, 'message', SQLERRM);
    END;
    v_effect := v13_effect_id(p_sid, 'tool', v_req);
    INSERT INTO effects (effect_id, session_id, kind, tool_name, request, request_hash,
                         idempotency_key, status, result, error, origin_user_seq)
    VALUES (v_effect, p_sid, 'tool', v_route->>'tool', v_req,
            encode(digest(v_req::text, 'sha256'), 'hex'),
            'v13:' || v_effect::text,
            CASE WHEN v_err IS NULL THEN 'succeeded' ELSE 'failed' END,
            CASE WHEN v_err IS NULL THEN v_res END, v_err, v13_last_user_seq(p_sid));
    IF v_err IS NULL THEN
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'tool/result',
        jsonb_build_object('tool', v_route->>'tool', 'result', v_res,
                           'origin_user_seq', v13_last_user_seq(p_sid)), v_effect);
    END IF;
    RETURN 'progressed';
  WHEN 'tool' THEN
    SELECT t->>'handler' INTO v_handler
      FROM jsonb_array_elements(p_snap->'envelope'->'tools_catalog') t
     WHERE t->>'name' = v_route->>'tool' AND (t->>'enabled')::boolean;
    IF v13_is_harness_tool(v_route->>'tool', 'tool') THEN
      v_pred := v13_harness_predecessor(p_sid);
      IF v_pred IS NOT NULL THEN
        SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
        IF v_prow.status = 'succeeded'
           AND v_prow.result->>'result_kind' IN ('finish', 'reject') THEN
          RAISE EXCEPTION 'v13: harness finish/reject does not continue';
        END IF;
      END IF;
      PERFORM v13_harness_tail_gap(p_sid, v_pred);
      v_req := jsonb_build_object(
        'tool', 'harness_turn',
        'params', '{}'::jsonb,
        'handler', v_handler,
        'tools_revision', p_snap->'envelope'->'tools_revision',
        'logical_turn_id', gen_random_uuid()::text,
        'continuation_index', 0);
      v_effect := v13_enqueue_effect(p_sid, 'tool', v_req, v_route->>'tool');
    ELSE
      v_effect := v13_enqueue_effect(p_sid, 'tool',
        jsonb_build_object('tool', v_route->>'tool',
                           'params', coalesce(v_route->'params', '{}'::jsonb),
                           'handler', v_handler,
                           'tools_revision', p_snap->'envelope'->'tools_revision'),
        v_route->>'tool');
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'llm' THEN
    v_effect := v13_enqueue_effect(p_sid, 'llm', jsonb_build_object('route', v_route));
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'human' THEN
    v_effect := v13_enqueue_effect(p_sid, 'human',
      jsonb_build_object('reason', v_route->>'reason'));
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'finish' THEN
    IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'completed', coalesce(v_route->>'reason', 'answered'), false);
    RETURN 'terminal';
  WHEN 'reject' THEN
    IF v13_park_open_children(p_sid) THEN RETURN 'waiting'; END IF;
    PERFORM v13_closeout(p_sid, 'failed', coalesce(v_route->>'reason', 'injection_veto'), false);
    RETURN 'terminal';
  ELSE
    RAISE EXCEPTION 'v13: route returned no action for %', p_sid;
  END CASE;
END $function$;

REVOKE EXECUTE ON FUNCTION public.v13_goal_fingerprint(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_goal_fold(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_goal_lifecycle(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_goal_stop(uuid, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_goal_resume(uuid, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_goal_event_guard() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_attention(uuid, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_scheduler_hint(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_spawn_batch_allowed(uuid, integer) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.v13_goal_fingerprint(uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_goal_fold(uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_goal_lifecycle(uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_goal_stop(uuid, text) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_goal_resume(uuid, text) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_attention(uuid, integer) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_scheduler_hint(uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_spawn_batch_allowed(uuid, integer) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_spawn_budget_snapshot(uuid, integer, uuid) TO v13_spawn_owner;

DO $govern_keep$
DECLARE
  v_src text;
  v_cfg text[];
  v_owner text;
  v_def boolean;
  v_idx text;
  v_pol jsonb;
BEGIN
  SELECT p.prosecdef, pg_catalog.pg_get_userbyid(p.proowner), p.proconfig, p.prosrc
    INTO v_def, v_owner, v_cfg, v_src
    FROM pg_proc p
   WHERE p.oid = 'public.v13_spawn_batch_allowed(uuid, integer)'::regprocedure;
  IF v_def IS NOT TRUE OR v_owner IS DISTINCT FROM 'v13_spawn_owner' THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  IF v_cfg IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, pg_temp']::text[] THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  IF (length(v_src) - length(replace(v_src, 'v13_policy_share(', '')))
       / length('v13_policy_share(') <> 1
     OR position('FOR SHARE' IN v_src) > 0
     OR position('v13_policies' IN v_src) > 0
     OR v_src ~ '(^|[^[:alnum:]_.])hashtext[[:space:]]*\('
     OR v_src ~ '(^|[^[:alnum:]_.])pg_advisory_xact_lock[[:space:]]*\('
     OR v_src ~ '(^|[^[:alnum:]_.])v13_advisory_class[[:space:]]*\('
     OR v_src ~ '(^|[^[:alnum:]_.])v13_spawn_budget_snapshot[[:space:]]*\('
     OR v_src ~ '(^|[^[:alnum:]_.])sessions\M' THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  IF NOT has_function_privilege('v13_route', 'public.v13_spawn_batch_allowed(uuid, integer)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_spawn_budget_snapshot(uuid, integer, uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_spawn_owner', 'public.v13_spawn_budget_snapshot(uuid, integer, uuid)', 'EXECUTE')
     OR has_function_privilege('v13_worker', 'public.v13_spawn_batch_allowed(uuid, integer)', 'EXECUTE')
     OR has_function_privilege('v13_worker', 'public.v13_spawn_budget_snapshot(uuid, integer, uuid)', 'EXECUTE')
     OR has_function_privilege('public', 'public.v13_spawn_batch_allowed(uuid, integer)', 'EXECUTE')
     OR has_function_privilege('public', 'public.v13_spawn_budget_snapshot(uuid, integer, uuid)', 'EXECUTE')
     OR has_function_privilege('v13_recall', 'public.v13_spawn_batch_allowed(uuid, integer)', 'EXECUTE')
     OR has_function_privilege('v13_recall', 'public.v13_spawn_budget_snapshot(uuid, integer, uuid)', 'EXECUTE')
     OR has_function_privilege('v13_resolve', 'public.v13_spawn_batch_allowed(uuid, integer)', 'EXECUTE')
     OR has_function_privilege('v13_resolve', 'public.v13_spawn_budget_snapshot(uuid, integer, uuid)', 'EXECUTE')
     OR has_function_privilege('v13_route', 'public.v13_advisory_class(text)', 'EXECUTE')
     OR has_function_privilege('public', 'public.v13_goal_event_guard()', 'EXECUTE')
     OR has_function_privilege('v13_route', 'public.v13_goal_event_guard()', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_goal_fold(uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_goal_fingerprint(uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_goal_lifecycle(uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_goal_stop(uuid, text)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_goal_resume(uuid, text)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_attention(uuid, integer)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_scheduler_hint(uuid)', 'EXECUTE') THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  SELECT value INTO v_pol
    FROM public.v13_policies
   WHERE name = 'should_run' AND active;
  IF v_pol::text NOT LIKE '%goal_stopped%' THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  SELECT pg_get_indexdef(c.oid) INTO v_idx
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relname = 'ix_events_goal_lifecycle';
  IF v_idx IS NULL
     OR position('UNIQUE' IN v_idx) > 0
     OR position('seq DESC' IN v_idx) = 0
     OR position('goal/stopped' IN v_idx) = 0
     OR position('goal/resumed' IN v_idx) = 0 THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  IF (SELECT count(*) FROM pg_class WHERE relname = 'ix_events_goal_lifecycle') <> 1 THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
  IF position('v13_spawn_batch_allowed' IN (
       SELECT prosrc FROM pg_proc
        WHERE oid = 'public.v13_advance(uuid, jsonb)'::regprocedure)) = 0
     OR position('v13: spawn budget cap' IN (
       SELECT prosrc FROM pg_proc
        WHERE oid = 'public.v13_spawn_subsession(uuid, jsonb)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: govern install';
  END IF;
END
$govern_keep$;

COMMIT;
