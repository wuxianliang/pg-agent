-- v13 quota_window (stage 27). Recompute eligibility and missing capabilities. No new tables.
BEGIN;

DO $quota_base$
BEGIN
  IF NOT EXISTS (
       SELECT 1 FROM pg_attribute
        WHERE attrelid = 'public.events'::regclass
          AND attname = 'at' AND NOT attisdropped)
     OR to_regclass('public.ix_events_material_spent_at') IS NOT NULL
     OR EXISTS (
       SELECT 1 FROM public.v13_policies
        WHERE name IN ('quota_window', 'capabilities'))
     OR to_regprocedure('public.v13_quota_eligible(uuid)') IS NOT NULL
     OR to_regprocedure('public.v13_missing_capabilities(uuid)') IS NOT NULL
     OR to_regprocedure('public.v13_material_time_honest()') IS NOT NULL
     OR EXISTS (
       SELECT 1 FROM pg_trigger WHERE tgname = 'trg_material_time_honest')
     OR position('quota_window' IN pg_get_functiondef('public.v13_should_run_gate(uuid)'::regprocedure)) > 0
     OR position('capabilities' IN pg_get_functiondef('public.v13_should_run_gate(uuid)'::regprocedure)) > 0
     OR pg_get_function_identity_arguments('public.v13_should_run_gate(uuid)'::regprocedure)
        IS DISTINCT FROM 'p_sid uuid' THEN
    RAISE EXCEPTION 'v13: quota baseline';
  END IF;
  IF to_regclass('public.tools') IS NULL
     OR NOT EXISTS (
       SELECT 1 FROM pg_attribute
        WHERE attrelid = 'public.tools'::regclass
          AND attname = 'name' AND NOT attisdropped)
     OR NOT EXISTS (
       SELECT 1 FROM pg_attribute
        WHERE attrelid = 'public.tools'::regclass
          AND attname = 'enabled' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'v13: capabilities baseline';
  END IF;
END
$quota_base$;

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'quota_window',
  1,
  '{"schema_version":1,"window_hours":8760,"slot_minutes":0,"allowed":1000000}'::jsonb,
  true);

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'capabilities',
  1,
  '{"schema_version":1,"required":[]}'::jsonb,
  true);

CREATE FUNCTION public.v13_quota_eligible(p_sid uuid) RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_pol jsonb;
  v_hours int;
  v_slot int;
  v_allowed int;
  v_now timestamptz;
  v_count int;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT value INTO v_pol
    FROM public.v13_policies
   WHERE name = 'quota_window' AND active;
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_pol) IS DISTINCT FROM
        ARRAY['allowed', 'schema_version', 'slot_minutes', 'window_hours']
     OR NOT public.v13_json_int_ok(v_pol->'schema_version', 1)
     OR (v_pol->>'schema_version')::int <> 1
     OR NOT public.v13_json_int_ok(v_pol->'window_hours', 87600)
     OR NOT public.v13_json_int_ok(v_pol->'slot_minutes', 5256000)
     OR NOT public.v13_json_int_ok(v_pol->'allowed', 2147483647) THEN
    RAISE EXCEPTION 'v13: quota policy';
  END IF;
  v_hours := (v_pol->>'window_hours')::int;
  v_slot := (v_pol->>'slot_minutes')::int;
  v_allowed := (v_pol->>'allowed')::int;
  IF v_hours < 1 OR v_hours > 87600
     OR v_slot < 0 OR v_slot > 5256000
     OR v_allowed < 0 OR v_allowed > 2147483647
     OR v_slot > v_hours * 60 THEN
    RAISE EXCEPTION 'v13: quota policy';
  END IF;
  v_now := transaction_timestamp();
  SELECT count(*)::int INTO v_count
    FROM public.events
   WHERE session_id = p_sid
     AND type = 'turn/material_spent'
     AND at >= v_now - make_interval(hours => v_hours)
     AND at <= v_now;
  IF v_count >= v_allowed THEN
    RETURN false;
  END IF;
  IF v_slot > 0 AND EXISTS (
    SELECT 1 FROM public.events
     WHERE session_id = p_sid
       AND type = 'turn/material_spent'
       AND at >= v_now - make_interval(mins => v_slot)
       AND at <= v_now) THEN
    RETURN false;
  END IF;
  RETURN true;
END
$function$;

CREATE FUNCTION public.v13_missing_capabilities(p_sid uuid)
RETURNS TABLE (name text)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
#variable_conflict use_column
DECLARE
  v_pol jsonb;
  v_elem jsonb;
  v_req text;
  v_seen text[] := '{}';
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT value INTO v_pol
    FROM public.v13_policies
   WHERE public.v13_policies.name = 'capabilities' AND active;
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_pol) IS DISTINCT FROM ARRAY['required', 'schema_version']
     OR NOT public.v13_json_int_ok(v_pol->'schema_version', 1)
     OR (v_pol->>'schema_version')::int <> 1
     OR jsonb_typeof(v_pol->'required') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: capabilities policy';
  END IF;
  FOR v_elem IN SELECT value FROM jsonb_array_elements(v_pol->'required') LOOP
    IF jsonb_typeof(v_elem) IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'v13: capabilities policy';
    END IF;
    v_req := v_elem #>> '{}';
    IF v_req IS NULL OR v_req = ''
       OR position('::' IN v_req) > 0
       OR v_req = ANY (v_seen) THEN
      RAISE EXCEPTION 'v13: capabilities policy';
    END IF;
    v_seen := v_seen || v_req;
  END LOOP;
  RETURN QUERY
    SELECT r.req_name
      FROM unnest(v_seen) AS r(req_name)
     WHERE NOT EXISTS (
       SELECT 1 FROM public.tools t
        WHERE t.name = r.req_name AND t.enabled)
     ORDER BY r.req_name;
END
$function$;

CREATE FUNCTION public.v13_material_time_honest() RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_wall timestamptz;
  v_txn timestamptz;
BEGIN
  v_wall := clock_timestamp();
  v_txn := transaction_timestamp();
  IF NOT EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = current_user AND rolsuper)
     AND current_user IS DISTINCT FROM (
       SELECT pg_catalog.pg_get_userbyid(c.relowner)
         FROM pg_catalog.pg_class c
         JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'events')
     AND NOT (NEW.at >= v_wall - interval '60 seconds' AND NEW.at <= v_txn) THEN
    RAISE EXCEPTION 'v13: material time';
  END IF;
  RETURN NEW;
END
$function$;

REVOKE EXECUTE ON FUNCTION public.v13_material_time_honest() FROM PUBLIC;

CREATE TRIGGER trg_material_time_honest
  BEFORE INSERT ON public.events
  FOR EACH ROW
  WHEN (NEW.type = 'turn/material_spent')
  EXECUTE FUNCTION public.v13_material_time_honest();

CREATE INDEX ix_events_material_spent_at
  ON public.events (session_id, at)
  WHERE type = 'turn/material_spent';

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'should_run',
  2,
  '{"schema_version":1,"gates":[{"id":"human_pending","effect":"block"},{"id":"unknown_wall","effect":"block"},{"id":"unconsumed_cancel","effect":"block"},{"id":"duty_cycle","effect":"shadow"},{"id":"quota_window","effect":"block"},{"id":"capabilities","effect":"block"}]}'::jsonb,
  false);

UPDATE public.v13_policies SET active = false
 WHERE name = 'should_run' AND version = 1;

UPDATE public.v13_policies SET active = true
 WHERE name = 'should_run' AND version = 2;

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
       OR v_id NOT IN ('human_pending', 'unknown_wall', 'unconsumed_cancel', 'duty_cycle', 'quota_window', 'capabilities')
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
    END IF;
  END LOOP;
  RETURN NULL;
END
$function$;

REVOKE EXECUTE ON FUNCTION public.v13_quota_eligible(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_missing_capabilities(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_quota_eligible(uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_missing_capabilities(uuid) TO v13_route;

DO $quota_keep$
BEGIN
  IF NOT has_function_privilege('v13_route', 'public.v13_should_run_gate(uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_should_run(uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_advance(uuid,jsonb)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_quota_eligible(uuid)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_missing_capabilities(uuid)', 'EXECUTE')
     OR has_function_privilege('public', 'public.v13_material_time_honest()', 'EXECUTE')
     OR has_function_privilege('v13_route', 'public.v13_material_time_honest()', 'EXECUTE') THEN
    RAISE EXCEPTION 'v13: quota keep grant';
  END IF;
END
$quota_keep$;

COMMIT;
