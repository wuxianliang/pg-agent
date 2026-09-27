-- v13 attention (stage 28). Rank projection and scheduler hint. No new tables.
BEGIN;

DO $attention_base$
BEGIN
  IF to_regprocedure('public.v13_spawn_budget_snapshot(uuid, integer, uuid)') IS NOT NULL
     OR to_regprocedure('public.v13_attention(uuid, integer)') IS NOT NULL
     OR to_regprocedure('public.v13_scheduler_hint(uuid)') IS NOT NULL
     OR to_regprocedure('public.v_goal_tree(uuid)') IS NULL THEN
    RAISE EXCEPTION 'v13: attention baseline';
  END IF;
  IF position('is_terminal' IN pg_get_function_result('public.v_goal_tree(uuid)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: attention baseline';
  END IF;
END
$attention_base$;

CREATE FUNCTION public.v13_spawn_budget_snapshot(
  p_sid uuid,
  p_requested integer,
  p_root uuid DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
DECLARE
  v_parent uuid;
  v_root uuid;
  v_depth integer := 0;
  v_seen uuid[];
  v_pol jsonb;
  v_max_nt integer;
  v_max_depth integer;
  v_max_fanout integer;
  v_occ integer;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_sid) THEN
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
    v_seen := array_append(v_seen, v_parent);
    v_root := v_parent;
  END LOOP;
  IF p_root IS NOT NULL AND v_root IS DISTINCT FROM p_root THEN
    RAISE EXCEPTION 'v13: spawn root cycle';
  END IF;
  SELECT value INTO v_pol
    FROM public.v13_policies
   WHERE name = 'spawn_budget' AND active;
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_pol) IS DISTINCT FROM
        ARRAY['max_depth', 'max_fanout', 'max_nonterminal']
     OR (v_pol->>'max_nonterminal') !~ '^[1-9][0-9]*$'
     OR (v_pol->>'max_depth') !~ '^[1-9][0-9]*$'
     OR (v_pol->>'max_fanout') !~ '^[1-9][0-9]*$' THEN
    RAISE EXCEPTION 'v13: spawn_budget policy';
  END IF;
  IF (v_pol->>'max_nonterminal')::numeric > 2147483647
     OR (v_pol->>'max_depth')::numeric > 2147483647
     OR (v_pol->>'max_fanout')::numeric > 2147483647 THEN
    RAISE EXCEPTION 'v13: spawn_budget policy';
  END IF;
  v_max_nt := (v_pol->>'max_nonterminal')::integer;
  v_max_depth := (v_pol->>'max_depth')::integer;
  v_max_fanout := (v_pol->>'max_fanout')::integer;
  IF p_requested IS NULL THEN
    RETURN false;
  END IF;
  v_occ := public.v13_spawn_occupancy(v_root);
  IF p_requested > v_max_fanout
     OR v_depth + 1 > v_max_depth
     OR v_occ + p_requested > v_max_nt THEN
    RETURN false;
  END IF;
  RETURN true;
END
$function$;

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
  blocked_by text
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
  END LOOP;
  v_i := 0;
  FOR r IN
    SELECT u.session_id, u.parent_session_id, u.depth, u.status,
           u.spawn_kind, u.turn_no, u.is_terminal, u.blocked_by
      FROM unnest(v_sid, v_parent, v_depth, v_status, v_kind, v_turn, v_term, v_blocked)
        AS u(session_id, parent_session_id, depth, status, spawn_kind, turn_no,
             is_terminal, blocked_by)
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
    RETURN NEXT;
  END LOOP;
  RETURN;
END
$function$;

CREATE FUNCTION public.v13_scheduler_hint(p_sid uuid) RETURNS text
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

REVOKE EXECUTE ON FUNCTION public.v13_spawn_budget_snapshot(uuid, integer, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_attention(uuid, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_scheduler_hint(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_spawn_budget_snapshot(uuid, integer, uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_attention(uuid, integer) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_scheduler_hint(uuid) TO v13_route;

COMMIT;
