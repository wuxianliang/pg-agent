-- v13 observe (stage 24). Authorized read surface. No new tables.
BEGIN;

DO $observe_baseline$
DECLARE
  v_advance text;
  v_tree text;
BEGIN
  IF to_regprocedure('public.v13_control_authorized(uuid,uuid)') IS NULL
     OR pg_get_function_identity_arguments(
          'public.v13_control_authorized(uuid,uuid)'::regprocedure)
          IS DISTINCT FROM 'p_actor uuid, p_target uuid'
     OR pg_get_function_result(
          'public.v13_control_authorized(uuid,uuid)'::regprocedure)
          IS DISTINCT FROM 'boolean'
     OR to_regprocedure('public.v13_pending_human(uuid)') IS NULL
     OR pg_get_function_result('public.v13_pending_human(uuid)'::regprocedure)
          IS DISTINCT FROM 'boolean'
     OR pg_typeof(public.v13_pending_human(NULL::uuid))
          IS DISTINCT FROM 'boolean'::regtype
     OR to_regprocedure('public.v13_unconsumed_cancel(uuid)') IS NULL
     OR pg_get_function_result('public.v13_unconsumed_cancel(uuid)'::regprocedure)
          IS DISTINCT FROM 'boolean'
     OR pg_typeof(public.v13_unconsumed_cancel(NULL::uuid))
          IS DISTINCT FROM 'boolean'::regtype
     OR to_regprocedure('public.v13_advance(uuid,jsonb)') IS NULL
     OR to_regprocedure('public.v_goal_tree(uuid)') IS NULL
  THEN
    RAISE EXCEPTION 'v13: observe baseline';
  END IF;
  v_advance := pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure);
  IF position('v13_unconsumed_cancel' IN v_advance) = 0 THEN
    RAISE EXCEPTION 'v13: observe baseline';
  END IF;
  v_tree := pg_get_functiondef('public.v_goal_tree(uuid)'::regprocedure);
  IF position(
       'status IN (''completed'', ''failed'', ''cancelled'')' IN v_tree) = 0 THEN
    RAISE EXCEPTION 'v13: observe baseline';
  END IF;
END
$observe_baseline$;

CREATE FUNCTION public.v13_observe(p_actor uuid, p_ids uuid[])
RETURNS TABLE (
  ordinal int,
  session_id uuid,
  parent_session_id uuid,
  status text,
  spawn_kind text,
  is_terminal boolean,
  turn_no int,
  last_event_seq bigint,
  last_event_type text,
  pending_human boolean,
  cancel_pending boolean)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $observe$
DECLARE
  v_id uuid;
  v_i int;
  v_parent uuid;
  v_status text;
  v_spawn text;
  v_turn int;
  v_seq bigint;
  v_type text;
BEGIN
  IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
    RETURN;
  END IF;
  IF EXISTS (
    SELECT 1 FROM unnest(p_ids) AS x(id) WHERE x.id IS NULL
  ) THEN
    RAISE EXCEPTION 'v13: observe id';
  END IF;
  IF (
    SELECT count(*) FROM unnest(p_ids) AS x(id)
  ) <> (
    SELECT count(DISTINCT x.id) FROM unnest(p_ids) AS x(id)
  ) THEN
    RAISE EXCEPTION 'v13: observe duplicate';
  END IF;
  FOREACH v_id IN ARRAY p_ids LOOP
    IF NOT public.v13_control_authorized(p_actor, v_id) THEN
      RETURN;
    END IF;
  END LOOP;
  v_i := 0;
  FOREACH v_id IN ARRAY p_ids LOOP
    v_i := v_i + 1;
    v_parent := NULL;
    v_status := NULL;
    v_spawn := NULL;
    v_turn := NULL;
    v_seq := -1;
    v_type := NULL;
    SELECT s.parent_session_id, s.status, s.spawn_kind, s.turn_no
      INTO v_parent, v_status, v_spawn, v_turn
      FROM public.sessions s
     WHERE s.session_id = v_id;
    SELECT ev.seq, ev.type
      INTO v_seq, v_type
      FROM public.events ev
     WHERE ev.session_id = v_id
     ORDER BY ev.seq DESC
     LIMIT 1;
    IF NOT FOUND THEN
      v_seq := -1;
      v_type := NULL;
    END IF;
    ordinal := v_i;
    session_id := v_id;
    parent_session_id := v_parent;
    status := v_status;
    spawn_kind := v_spawn;
    is_terminal := v_status IN ('completed', 'failed', 'cancelled');
    turn_no := v_turn;
    last_event_seq := v_seq;
    last_event_type := v_type;
    pending_human := public.v13_pending_human(v_id);
    cancel_pending := public.v13_unconsumed_cancel(v_id);
    RETURN NEXT;
  END LOOP;
  RETURN;
END
$observe$;

CREATE FUNCTION public.v13_session_log(
  p_actor uuid,
  p_sid uuid,
  p_after_seq bigint DEFAULT NULL)
RETURNS TABLE (
  seq bigint,
  event_id uuid,
  type text,
  turn_no int,
  payload jsonb,
  payload_hash text,
  source_effect_id uuid,
  at timestamptz)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $slog$
BEGIN
  IF p_after_seq IS NOT NULL AND p_after_seq < -1 THEN
    RAISE EXCEPTION 'v13: session log cursor';
  END IF;
  IF NOT public.v13_control_authorized(p_actor, p_sid) THEN
    RETURN;
  END IF;
  RETURN QUERY
  SELECT e.seq, e.event_id, e.type, e.turn_no, e.payload,
         e.payload_hash, e.source_effect_id, e.at
    FROM public.events e
   WHERE e.session_id = p_sid
     AND (p_after_seq IS NULL OR e.seq > p_after_seq)
   ORDER BY e.seq;
END
$slog$;

REVOKE EXECUTE ON FUNCTION public.v13_observe(uuid, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_session_log(uuid, uuid, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_observe(uuid, uuid[]) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_session_log(uuid, uuid, bigint) TO v13_route;

COMMENT ON FUNCTION public.v13_observe(uuid, uuid[]) IS
  'stage 24: authorized multi-id snapshot; denial is zero rows; no waiter';
COMMENT ON FUNCTION public.v13_session_log(uuid, uuid, bigint) IS
  'stage 24: authorized event log; cursor shape before predicate; denial is zero rows';

COMMIT;
