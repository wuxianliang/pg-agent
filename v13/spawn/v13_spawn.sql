-- v13 control plane stage 18. Self-contained transaction. Prefix files untouched.
BEGIN;

DO $probe$
BEGIN
  IF position('children require stage 18' IN pg_get_functiondef('v13_closeout(uuid,text,text,boolean)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: closeout live body missing children require stage 18';
  END IF;
  IF position('children_terminal requires stage 18' IN pg_get_functiondef('v13_complete(uuid,integer,bigint,text,jsonb)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: complete live body missing children_terminal requires stage 18';
  END IF;
  IF position('children_terminal requires stage 18' IN pg_get_functiondef('v13_wake_is_satisfied_v1(uuid,uuid,jsonb)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: wake live body missing children_terminal requires stage 18';
  END IF;
  IF to_regprocedure('v13_fork(uuid,bigint,text,jsonb)') IS NULL THEN
    RAISE EXCEPTION 'v13: fork signature missing';
  END IF;
  IF to_regprocedure('public.digest(bytea,text)') IS NULL THEN
    RAISE EXCEPTION 'v13: digest missing from public';
  END IF;
END
$probe$;

INSERT INTO v13_policies (name, version, value, active) VALUES
  ('spawn_budget', 1, '{"max_nonterminal":8,"max_depth":4,"max_fanout":8}'::jsonb, true);

CREATE FUNCTION public.v13_is_spawn_tool(p_name text, p_kind text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT p_name = 'spawn_subsession' AND p_kind = 'sql'
$fn$;

CREATE FUNCTION public.v13_advisory_class(p_name text) RETURNS int
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
  IF p_name = 'spawn_budget' THEN
    RETURN 13001;
  END IF;
  RAISE EXCEPTION 'v13: advisory class %', p_name;
END
$fn$;

CREATE FUNCTION public.v13_named_sql_writer(p_handler text) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT CASE
    WHEN p_handler IN ('v13_spawn_subsession', 'public.v13_spawn_subsession') THEN
      '{"mutating":false,"write_targets":["artifacts","events","latches","sessions"]}'::jsonb
    ELSE NULL
  END
$fn$;

CREATE FUNCTION public.v13_spawn_request(p_children jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT jsonb_build_object(
    'tool', 'spawn_subsession',
    'params', jsonb_build_object('children', p_children))
$fn$;

CREATE FUNCTION public.v13_spawn_children(p_children jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE
  v_out jsonb := '[]'::jsonb;
  v_elem jsonb;
  v_id text;
  v_task text;
  v_seen text[] := '{}';
BEGIN
  IF p_children IS NULL OR jsonb_typeof(p_children) <> 'array'
     OR jsonb_array_length(p_children) < 1 THEN
    RAISE EXCEPTION 'v13: spawn args';
  END IF;
  FOR v_elem IN SELECT value FROM jsonb_array_elements(p_children) LOOP
    IF jsonb_typeof(v_elem) <> 'object'
       OR v13_json_keys(v_elem) IS DISTINCT FROM ARRAY['task', 'tool_call_id']
       OR jsonb_typeof(v_elem->'tool_call_id') <> 'string'
       OR jsonb_typeof(v_elem->'task') <> 'string' THEN
      RAISE EXCEPTION 'v13: spawn args';
    END IF;
    v_id := v_elem->>'tool_call_id';
    v_task := v_elem->>'task';
    IF char_length(v_id) < 1 OR char_length(v_id) > 128
       OR v_id !~ '^[A-Za-z0-9_./:-]+$'
       OR char_length(v_task) < 1 OR char_length(v_task) > 1024
       OR v_id = ANY(v_seen) THEN
      RAISE EXCEPTION 'v13: spawn args';
    END IF;
    v_seen := v_seen || v_id;
    v_out := v_out || jsonb_build_array(jsonb_build_object(
      'tool_call_id', v_id, 'task', v_task));
  END LOOP;
  RETURN v_out;
END
$fn$;

CREATE FUNCTION public.v13_llm_tool_calls(p_calls jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE
  v_out jsonb := '[]'::jsonb;
  v_elem jsonb;
  v_id text;
  v_task text;
  v_seen text[] := '{}';
BEGIN
  IF p_calls IS NULL OR jsonb_typeof(p_calls) <> 'array' THEN
    RAISE EXCEPTION 'v13: tool_calls shape';
  END IF;
  FOR v_elem IN SELECT value FROM jsonb_array_elements(p_calls) LOOP
    IF jsonb_typeof(v_elem) <> 'object'
       OR v13_json_keys(v_elem) IS DISTINCT FROM ARRAY['args', 'id', 'name']
       OR v_elem->>'name' IS DISTINCT FROM 'spawn_subsession'
       OR jsonb_typeof(v_elem->'args') <> 'object'
       OR v13_json_keys(v_elem->'args') IS DISTINCT FROM ARRAY['task']
       OR jsonb_typeof(v_elem->'id') <> 'string'
       OR jsonb_typeof(v_elem->'args'->'task') <> 'string' THEN
      RAISE EXCEPTION 'v13: tool_calls shape';
    END IF;
    v_id := v_elem->>'id';
    v_task := v_elem->'args'->>'task';
    IF char_length(v_id) < 1 OR char_length(v_id) > 128
       OR v_id !~ '^[A-Za-z0-9_./:-]+$'
       OR char_length(v_task) < 1 OR char_length(v_task) > 1024
       OR v_id = ANY(v_seen) THEN
      RAISE EXCEPTION 'v13: tool_calls shape';
    END IF;
    v_seen := v_seen || v_id;
    v_out := v_out || jsonb_build_array(jsonb_build_object(
      'schema_version', 1,
      'id', v_id,
      'name', 'spawn_subsession',
      'args', jsonb_build_object('task', v_task)));
  END LOOP;
  RETURN v_out;
END
$fn$;

CREATE FUNCTION public.v13_direct_children_open(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM sessions
     WHERE parent_session_id = p_sid
       AND status NOT IN ('completed', 'failed', 'cancelled'))
$fn$;

CREATE FUNCTION public.v13_park_open_children(p_sid uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE AS $fn$
DECLARE v_st text;
BEGIN
  IF NOT v13_direct_children_open(p_sid) THEN
    RETURN false;
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF v_st IS DISTINCT FROM 'blocked_unknown' THEN
    UPDATE sessions SET status = 'waiting'
     WHERE session_id = p_sid AND status IN ('ready', 'waiting');
  END IF;
  RETURN true;
END
$fn$;

CREATE FUNCTION public.v13_spawn_occupancy(p_root uuid) RETURNS int
LANGUAGE plpgsql STABLE AS $fn$
DECLARE v_n int; v_cyc boolean; v_deep boolean;
BEGIN
  SELECT count(*) FILTER (
           WHERE NOT t.cyc AND s.status NOT IN ('completed', 'failed', 'cancelled')),
         coalesce(bool_or(t.cyc), false),
         coalesce(bool_or(t.d > 64), false)
    INTO v_n, v_cyc, v_deep
    FROM (
      WITH RECURSIVE tree AS (
        SELECT session_id, 1 AS d, ARRAY[session_id] AS path, false AS cyc
          FROM sessions WHERE parent_session_id = p_root
        UNION ALL
        SELECT c.session_id, t.d + 1, t.path || c.session_id,
               c.session_id = ANY(t.path)
          FROM sessions c
          JOIN tree t ON c.parent_session_id = t.session_id
         WHERE NOT t.cyc AND t.d < 65
      )
      SELECT * FROM tree
    ) t
    JOIN sessions s ON s.session_id = t.session_id;
  IF coalesce(v_cyc, false) OR coalesce(v_deep, false) THEN
    RAISE EXCEPTION 'v13: spawn root cycle';
  END IF;
  RETURN coalesce(v_n, 0);
END
$fn$;

CREATE FUNCTION public.v13_insert_nudge(p_sid uuid, p_reason text, p_fp text) RETURNS int
LANGUAGE plpgsql VOLATILE AS $fn$
DECLARE v_constraint text;
BEGIN
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'recover/nudge',
    jsonb_build_object('schema_version', 1, 'reason', p_reason, 'fingerprint', p_fp));
  RETURN 1;
EXCEPTION WHEN unique_violation THEN
  GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
  IF v_constraint IS DISTINCT FROM 'ux_events_recover_nudge' THEN
    RAISE;
  END IF;
  RETURN 0;
END
$fn$;

CREATE UNIQUE INDEX ux_events_child_created
  ON events (session_id, (payload->>'tool_call_id'))
  WHERE type = 'child-created';
CREATE UNIQUE INDEX ux_events_tool_call
  ON events (session_id, (payload->>'id'))
  WHERE type = 'tool/call';
CREATE UNIQUE INDEX ux_events_recover_nudge
  ON events (session_id, (payload->>'reason'), (payload->>'fingerprint'))
  WHERE type = 'recover/nudge';

CREATE FUNCTION public.v13_spawn_event_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE v_keys text[];
BEGIN
  v_keys := v13_json_keys(NEW.payload);
  IF NEW.type = 'spawn/task' THEN
    IF NEW.source_effect_id IS NOT NULL
       OR v_keys IS DISTINCT FROM ARRAY['schema_version', 'task', 'tool_call_id']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR (NEW.payload->>'tool_call_id') !~ '^[A-Za-z0-9_./:-]+$'
       OR char_length(NEW.payload->>'tool_call_id') > 128
       OR char_length(NEW.payload->>'task') < 1
       OR char_length(NEW.payload->>'task') > 1024 THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
  ELSIF NEW.type = 'child-created' THEN
    IF NEW.source_effect_id IS NULL
       OR v_keys IS DISTINCT FROM ARRAY['child_session_id', 'cutoff', 'reservation', 'schema_version', 'spawn_kind', 'tool_call_id']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR NEW.payload->>'spawn_kind' IS DISTINCT FROM 'fresh_fork'
       OR (NEW.payload->>'cutoff') !~ '^[0-9]+$'
       OR NOT v13_canonical_uuid(NEW.payload->>'child_session_id')
       OR (NEW.payload->>'tool_call_id') !~ '^[A-Za-z0-9_./:-]+$'
       OR v13_json_keys(NEW.payload->'reservation') IS DISTINCT FROM
          ARRAY['max_nonterminal', 'nonterminal_before', 'parent_depth', 'requested']
       OR NOT v13_json_int_ok(NEW.payload->'reservation'->'max_nonterminal', 2147483647)
       OR NOT v13_json_int_ok(NEW.payload->'reservation'->'nonterminal_before', 2147483647)
       OR NOT v13_json_int_ok(NEW.payload->'reservation'->'parent_depth', 64)
       OR NOT v13_json_int_ok(NEW.payload->'reservation'->'requested', 2147483647) THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
  ELSIF NEW.type = 'tool/call' THEN
    IF NEW.source_effect_id IS NULL
       OR v_keys IS DISTINCT FROM ARRAY['args', 'id', 'name', 'schema_version']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR NEW.payload->>'name' IS DISTINCT FROM 'spawn_subsession'
       OR v13_json_keys(NEW.payload->'args') IS DISTINCT FROM ARRAY['task']
       OR (NEW.payload->>'id') !~ '^[A-Za-z0-9_./:-]+$'
       OR char_length(NEW.payload->>'id') > 128
       OR char_length(NEW.payload->'args'->>'task') < 1
       OR char_length(NEW.payload->'args'->>'task') > 1024 THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
  ELSIF NEW.type = 'recover/nudge' THEN
    IF NEW.source_effect_id IS NOT NULL
       OR v_keys IS DISTINCT FROM ARRAY['fingerprint', 'reason', 'schema_version']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR NEW.payload->>'reason' NOT IN ('children_terminal', 'repair', 'replan')
       OR coalesce(NEW.payload->>'fingerprint', '') = '' THEN
      RAISE EXCEPTION 'v13: event payload %', NEW.type;
    END IF;
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_v13_spawn_event_guard
  BEFORE INSERT ON events
  FOR EACH ROW
  WHEN (NEW.type IN ('spawn/task', 'child-created', 'tool/call', 'recover/nudge'))
  EXECUTE FUNCTION public.v13_spawn_event_guard();

DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_spawn_owner') THEN
    CREATE ROLE v13_spawn_owner NOLOGIN NOSUPERUSER;
  END IF;
END
$role$;

CREATE FUNCTION public.v13_open_session(p_spec jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE v_name text := 'default'; v_ver int := 1; v_sid uuid; k text;
BEGIN
  IF p_spec IS NULL OR jsonb_typeof(p_spec) <> 'object' THEN
    RAISE EXCEPTION 'v13: open session args';
  END IF;
  FOR k IN SELECT jsonb_object_keys(p_spec) LOOP
    IF k NOT IN ('route_policy_name', 'version') THEN
      RAISE EXCEPTION 'v13: open session args';
    END IF;
  END LOOP;
  IF p_spec ? 'route_policy_name' THEN
    IF jsonb_typeof(p_spec->'route_policy_name') <> 'string'
       OR p_spec->>'route_policy_name' = '' THEN
      RAISE EXCEPTION 'v13: open session args';
    END IF;
    v_name := p_spec->>'route_policy_name';
  END IF;
  IF p_spec ? 'version' THEN
    IF jsonb_typeof(p_spec->'version') <> 'number'
       OR (p_spec->>'version') !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'v13: open session args';
    END IF;
    v_ver := (p_spec->>'version')::int;
  END IF;
  INSERT INTO sessions (status, turn_no, next_seq, route_policy_name, route_policy_version)
  VALUES ('ready', 0, 0, v_name, v_ver)
  RETURNING session_id INTO v_sid;
  RETURN v_sid;
END
$fn$;

CREATE FUNCTION public.v13_spawn_subsession(p_sid uuid, p_spec jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE
  v_children jsonb; v_requested int; v_pol jsonb;
  v_max_nt int; v_max_depth int; v_max_fanout int;
  v_st text; v_next bigint; v_cutoff bigint;
  v_root uuid; v_parent uuid; v_depth int := 0; v_seen uuid[] := ARRAY[p_sid];
  v_before int; v_after int; v_have int;
  v_elem jsonb; v_id text; v_task text; v_child uuid;
  v_res jsonb; v_out jsonb := '[]'::jsonb; v_eid uuid; v_req jsonb;
  v_stored_task text; v_stored_child text; v_stored_res jsonb;
BEGIN
  IF p_spec IS NULL OR jsonb_typeof(p_spec) <> 'object'
     OR v13_json_keys(p_spec) IS DISTINCT FROM ARRAY['children', 'schema_version']
     OR NOT v13_json_int_ok(p_spec->'schema_version', 1)
     OR (p_spec->'schema_version')::text::numeric <> 1
     OR jsonb_typeof(p_spec->'children') <> 'array' THEN
    RAISE EXCEPTION 'v13: spawn args';
  END IF;
  v_children := v13_spawn_children(p_spec->'children');
  v_requested := jsonb_array_length(v_children);
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT status, next_seq INTO v_st, v_next FROM sessions WHERE session_id = p_sid;
  IF v_st NOT IN ('ready', 'waiting') THEN
    RAISE EXCEPTION 'v13: spawn parent status';
  END IF;
  IF v_next < 1 THEN
    RAISE EXCEPTION 'v13: spawn requires prefix';
  END IF;
  v_cutoff := v_next - 1;
  SELECT count(*) INTO v_have
    FROM jsonb_array_elements(v_children) elem
   WHERE EXISTS (
     SELECT 1 FROM events ev
      WHERE ev.session_id = p_sid AND ev.type = 'child-created'
        AND ev.payload->>'tool_call_id' = elem->>'tool_call_id');
  IF v_have > 0 AND v_have < v_requested THEN
    RAISE EXCEPTION 'v13: spawn ledger';
  END IF;
  IF v_have = v_requested THEN
    FOR v_elem IN SELECT value FROM jsonb_array_elements(v_children) LOOP
      SELECT ev.payload->>'child_session_id', ev.payload->'reservation'
        INTO v_stored_child, v_res
        FROM events ev
       WHERE ev.session_id = p_sid AND ev.type = 'child-created'
         AND ev.payload->>'tool_call_id' = v_elem->>'tool_call_id';
      IF v_stored_child IS NULL OR v_res IS NULL THEN
        RAISE EXCEPTION 'v13: spawn ledger';
      END IF;
      IF v_stored_res IS NULL THEN
        v_stored_res := v_res;
      ELSIF v_stored_res IS DISTINCT FROM v_res THEN
        RAISE EXCEPTION 'v13: spawn ledger';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM sessions WHERE session_id = v_stored_child::uuid) THEN
        RAISE EXCEPTION 'v13: spawn ledger';
      END IF;
      SELECT payload->>'task' INTO v_stored_task
        FROM events
       WHERE session_id = v_stored_child::uuid AND type = 'spawn/task'
         AND payload->>'tool_call_id' = v_elem->>'tool_call_id';
      IF v_stored_task IS DISTINCT FROM v_elem->>'task' THEN
        RAISE EXCEPTION 'v13: spawn mismatch';
      END IF;
      v_out := v_out || jsonb_build_array(jsonb_build_object(
        'tool_call_id', v_elem->>'tool_call_id',
        'session_id', v_stored_child,
        'task', v_elem->>'task'));
    END LOOP;
    RETURN jsonb_build_object(
      'replay_kind', 'replay',
      'parent_session_id', p_sid,
      'children', v_out,
      'reservation', v_stored_res);
  END IF;
  v_root := p_sid;
  LOOP
    SELECT parent_session_id INTO v_parent FROM sessions WHERE session_id = v_root;
    EXIT WHEN v_parent IS NULL;
    v_depth := v_depth + 1;
    IF v_depth > 64 OR v_parent = ANY(v_seen) THEN
      RAISE EXCEPTION 'v13: spawn root cycle';
    END IF;
    v_seen := v_seen || v_parent;
    v_root := v_parent;
  END LOOP;
  v_pol := v13_policy('spawn_budget');
  IF v13_json_keys(v_pol) IS DISTINCT FROM ARRAY['max_depth', 'max_fanout', 'max_nonterminal']
     OR (v_pol->>'max_nonterminal') !~ '^[1-9][0-9]*$'
     OR (v_pol->>'max_depth') !~ '^[1-9][0-9]*$'
     OR (v_pol->>'max_fanout') !~ '^[1-9][0-9]*$' THEN
    RAISE EXCEPTION 'v13: spawn_budget policy';
  END IF;
  v_max_nt := (v_pol->>'max_nonterminal')::int;
  v_max_depth := (v_pol->>'max_depth')::int;
  v_max_fanout := (v_pol->>'max_fanout')::int;
  IF v_requested > v_max_fanout THEN
    RAISE EXCEPTION 'v13: spawn budget fanout';
  END IF;
  IF v_depth + 1 > v_max_depth THEN
    RAISE EXCEPTION 'v13: spawn budget depth';
  END IF;
  PERFORM pg_advisory_xact_lock(v13_advisory_class('spawn_budget'), hashtext(v_root::text));
  v_before := v13_spawn_occupancy(v_root);
  IF v_before + v_requested > v_max_nt THEN
    RAISE EXCEPTION 'v13: spawn budget cap';
  END IF;
  v_res := jsonb_build_object(
    'nonterminal_before', v_before,
    'requested', v_requested,
    'max_nonterminal', v_max_nt,
    'parent_depth', v_depth);
  v_req := v13_spawn_request(v_children);
  v_eid := v13_effect_id(p_sid, 'tool', v_req);
  FOR v_elem IN SELECT value FROM jsonb_array_elements(v_children) LOOP
    v_id := v_elem->>'tool_call_id';
    v_task := v_elem->>'task';
    v_child := v13_fork(p_sid, v_cutoff, 'fresh_fork', NULL);
    UPDATE sessions SET status = 'ready'
     WHERE session_id = v_child AND status IS DISTINCT FROM 'ready';
    PERFORM v13_append_event(v_child, gen_random_uuid(), 'spawn/task',
      jsonb_build_object('schema_version', 1, 'tool_call_id', v_id, 'task', v_task));
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'child-created',
      jsonb_build_object(
        'schema_version', 1,
        'tool_call_id', v_id,
        'child_session_id', v_child,
        'spawn_kind', 'fresh_fork',
        'cutoff', v_cutoff,
        'reservation', v_res),
      v_eid);
    v_out := v_out || jsonb_build_array(jsonb_build_object(
      'tool_call_id', v_id, 'session_id', v_child, 'task', v_task));
  END LOOP;
  v_after := v13_spawn_occupancy(v_root);
  IF v_after > v_max_nt THEN
    RAISE EXCEPTION 'v13: spawn budget cap';
  END IF;
  RETURN jsonb_build_object(
    'replay_kind', 'created',
    'parent_session_id', p_sid,
    'children', v_out,
    'reservation', v_res);
END
$fn$;

CREATE FUNCTION public.v_goal_tree(p_root uuid)
RETURNS TABLE (session_id uuid, parent_session_id uuid, depth int, status text,
               spawn_kind text, turn_no int, is_terminal boolean)
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
DECLARE
  v_ids uuid[] := ARRAY[p_root];
  v_depth int[] := ARRAY[0];
  v_i int := 1;
  v_child uuid;
  v_d int;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM sessions s WHERE s.session_id = p_root) THEN
    RAISE EXCEPTION 'v13: unknown session';
  END IF;
  WHILE v_i <= coalesce(array_length(v_ids, 1), 0) LOOP
    FOR v_child IN
      SELECT s.session_id FROM sessions s
       WHERE s.parent_session_id = v_ids[v_i]
       ORDER BY s.session_id
    LOOP
      IF v_child = ANY(v_ids) THEN
        RAISE EXCEPTION 'v13: goal tree cycle';
      END IF;
      v_d := v_depth[v_i] + 1;
      IF v_d > 64 THEN
        RAISE EXCEPTION 'v13: goal tree depth';
      END IF;
      v_ids := v_ids || v_child;
      v_depth := v_depth || v_d;
    END LOOP;
    v_i := v_i + 1;
  END LOOP;
  RETURN QUERY
  SELECT s.session_id, s.parent_session_id, d.depth, s.status, s.spawn_kind, s.turn_no,
         s.status IN ('completed', 'failed', 'cancelled')
    FROM unnest(v_ids, v_depth) AS d(session_id, depth)
    JOIN sessions s ON s.session_id = d.session_id
   ORDER BY d.depth, s.session_id;
END
$fn$;

CREATE FUNCTION public.v13_recover_idle() RETURNS jsonb
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
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
$fn$;

ALTER FUNCTION public.v13_fork(uuid, bigint, text, jsonb) OWNER TO v13_spawn_owner;
ALTER FUNCTION public.v13_open_session(jsonb) OWNER TO v13_spawn_owner;
ALTER FUNCTION public.v13_spawn_subsession(uuid, jsonb) OWNER TO v13_spawn_owner;

CREATE FUNCTION public.v13_sessions_insert_owner() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
  IF current_user IS DISTINCT FROM 'v13_spawn_owner' THEN
    RAISE EXCEPTION 'v13: sessions insert owner';
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_v13_sessions_insert_owner
  BEFORE INSERT ON sessions
  FOR EACH ROW EXECUTE FUNCTION public.v13_sessions_insert_owner();

GRANT EXECUTE ON FUNCTION v13_sessions_insert_owner() TO PUBLIC;

-- REPLACEMENTS

CREATE OR REPLACE FUNCTION public.v13_closeout(p_sid uuid, p_outcome text, p_reason text, p_attempts_exhausted boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_st text; v_n int; v_seal jsonb; v_type text; v_escape boolean;
  v_end jsonb; v_hash text; v_receipt jsonb; v_ous bigint;
  v_hashes jsonb; v_repair jsonb; v_replan jsonb; v_material jsonb;
  v_children jsonb;
  v_wake jsonb; v_appr jsonb; v_owed boolean; v_pred uuid; v_prow effects;
BEGIN
  IF p_outcome NOT IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: closeout outcome %', p_outcome;
  END IF;
  IF p_reason IS NULL OR p_reason !~ '^[A-Za-z0-9_./:-]+$' OR length(p_reason) > 128 THEN
    RAISE EXCEPTION 'v13: closeout precondition reason';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  v_type := 'session/' || v_st;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    SELECT count(*) INTO v_n FROM events WHERE session_id = p_sid AND type = v_type;
    IF v_n = 0 THEN
      RAISE EXCEPTION 'v13: closeout missing seal';
    ELSIF v_n > 1 THEN
      RAISE EXCEPTION 'v13: closeout duplicate seal';
    END IF;
    IF p_outcome IS DISTINCT FROM v_st THEN
      RAISE EXCEPTION 'v13: closeout outcome conflict';
    END IF;
    SELECT payload INTO v_seal FROM events WHERE session_id = p_sid AND type = v_type;
    RETURN v_seal;
  END IF;
  IF EXISTS (
    SELECT 1 FROM sessions
     WHERE parent_session_id = p_sid
       AND status NOT IN ('completed', 'failed', 'cancelled')) THEN
    RAISE EXCEPTION 'v13: closeout precondition children_open';
  END IF;
  IF EXISTS (
    SELECT 1 FROM effects
     WHERE session_id = p_sid AND status IN ('ready', 'claimed') AND kind <> 'human') THEN
    RAISE EXCEPTION 'v13: closeout precondition active';
  END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid AND status = 'unknown') THEN
    RAISE EXCEPTION 'v13: closeout precondition unknown';
  END IF;
  IF v13_pending_human(p_sid) THEN
    RAISE EXCEPTION 'v13: closeout precondition pending human';
  END IF;
  IF v_st = 'blocked_unknown' THEN
    RAISE EXCEPTION 'v13: closeout precondition blocked_unknown';
  END IF;
  v_ous := v13_last_user_seq(p_sid);
  IF p_outcome IN ('completed', 'failed') AND v_ous < 0 THEN
    RAISE EXCEPTION 'v13: closeout precondition origin_user_seq';
  END IF;
  SELECT coalesce(jsonb_agg(h ORDER BY h), '[]'::jsonb) INTO v_hashes
    FROM (
      SELECT DISTINCT a.content_hash AS h
        FROM artifacts a
        JOIN effects e ON e.effect_id = a.produced_by
       WHERE e.session_id = p_sid AND e.status = 'succeeded'
         AND a.content_hash ~ '^[0-9a-f]{64}$') q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_repair
    FROM (
      SELECT DISTINCT ev.source_effect_id::text AS id
        FROM events ev
       WHERE ev.session_id = p_sid AND ev.type = 'repair/required'
         AND ev.source_effect_id IS NOT NULL) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_replan
    FROM (
      SELECT DISTINCT ev.source_effect_id::text AS id
        FROM events ev
       WHERE ev.session_id = p_sid AND ev.type = 'replan/required'
         AND ev.source_effect_id IS NOT NULL) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_material
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND v13_harness_request_ok(e.request)
         AND (e.result->>'result_kind' = 'finish'
              OR (e.result->>'result_kind' = 'progress' AND NOT EXISTS (
                    SELECT 1 FROM events ev
                     WHERE ev.source_effect_id = e.effect_id
                       AND ev.type IN ('repair/required', 'replan/required'))))
         AND NOT EXISTS (
           SELECT 1 FROM events ev
            WHERE ev.source_effect_id = e.effect_id AND ev.type = 'turn/material_spent')) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_wake
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND e.result->>'result_kind' = 'wait'
         AND e.result->>'wait_reason' IN ('evidence', 'quota')
         AND NOT EXISTS (
           SELECT 1 FROM events ev
            WHERE ev.source_effect_id = e.effect_id AND ev.type = 'wake/satisfied')) q;
  SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb) INTO v_appr
    FROM (
      SELECT e.effect_id::text AS id
        FROM effects e
       WHERE e.session_id = p_sid AND e.status = 'succeeded' AND e.kind = 'tool'
         AND v13_is_harness_tool(e.tool_name, e.kind)
         AND e.result->>'result_kind' = 'wait'
         AND e.result->>'wait_reason' = 'approval'
         AND NOT EXISTS (
           SELECT 1 FROM effects h
            WHERE h.session_id = e.session_id AND h.kind = 'human'
              AND h.status = 'succeeded'
              AND h.request->>'interaction_ref' = e.result->>'interaction_id')) q;
  v_owed := false;
  v_pred := v13_harness_predecessor(p_sid);
  IF v_pred IS NOT NULL THEN
    SELECT * INTO v_prow FROM effects WHERE effect_id = v_pred;
    IF v_prow.status = 'succeeded' AND (
         (v_prow.result->>'result_kind' = 'progress' AND EXISTS (
            SELECT 1 FROM events ev
             WHERE ev.source_effect_id = v_pred
               AND ev.type IN ('repair/required', 'replan/required')))
         OR (v_prow.result->>'result_kind' = 'wait'
             AND v_prow.result->>'wait_reason' = 'approval'
             AND EXISTS (
               SELECT 1 FROM effects h
                WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
                  AND h.request->>'interaction_ref' = v_prow.result->>'interaction_id'))
         OR (v_prow.result->>'result_kind' = 'wait'
             AND v_prow.result->>'wait_reason' IN ('evidence', 'quota')
             AND EXISTS (
               SELECT 1 FROM events ev
                WHERE ev.source_effect_id = v_pred AND ev.type = 'wake/satisfied')))
       AND NOT EXISTS (
         SELECT 1 FROM effects n
          WHERE n.session_id = p_sid AND n.kind = 'tool'
            AND v13_is_harness_tool(n.tool_name, n.kind)
            AND n.request->>'logical_turn_id' = v_prow.request->>'logical_turn_id'
            AND (n.request->>'continuation_index')::int
                = (v_prow.request->>'continuation_index')::int + 1) THEN
      v_owed := true;
    END IF;
  END IF;
  v_escape := p_outcome = 'cancelled'
    OR (p_outcome = 'failed' AND p_reason IN (
         'budget_exhausted', 'resolve_budget', 'judge_attempts', 'context_refresh',
         'harness_attempts', 'approval_exhausted'));
  IF NOT v_escape THEN
    IF v_material <> '[]'::jsonb THEN
      RAISE EXCEPTION 'v13: closeout unpaid material';
    ELSIF v_wake <> '[]'::jsonb THEN
      RAISE EXCEPTION 'v13: closeout wake pending';
    ELSIF v_appr <> '[]'::jsonb THEN
      RAISE EXCEPTION 'v13: closeout approval pending';
    ELSIF v_owed THEN
      RAISE EXCEPTION 'v13: closeout continuation owed';
    END IF;
  END IF;
  v_end := jsonb_build_object('delivered', p_outcome = 'completed', 'reason', p_reason);
  IF p_attempts_exhausted THEN
    v_end := v_end || jsonb_build_object('attempts_exhausted', true);
  END IF;
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end', v_end);
  v_hash := v13_state_hash(p_sid);
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'session_id', session_id, 'status', status) ORDER BY session_id), '[]'::jsonb)
    INTO v_children
    FROM sessions
   WHERE parent_session_id = p_sid;
  v_receipt := jsonb_build_object(
    'schema_version', 1,
    'origin_user_seq', v_ous,
    'spent', jsonb_build_object(
      'turn_no', (SELECT turn_no FROM sessions WHERE session_id = p_sid),
      'cycle_no', v13_cycle_no(p_sid),
      'max_cycles', (v13_policy('turn_budget')->>'max_cycles')::int,
      'material_count', (SELECT count(*) FROM events
                          WHERE session_id = p_sid AND type = 'turn/material_spent')),
    'produced_hashes', v_hashes,
    'children', v_children,
    'unconsumed', jsonb_build_object(
      'repair_effect_ids', v_repair,
      'replan_effect_ids', v_replan,
      'material_effect_ids', v_material,
      'wake_pending_effect_ids', v_wake,
      'approval_pending_effect_ids', v_appr),
    'state_hash', v_hash,
    'turn_end_reason', p_reason);
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'session/' || p_outcome, v_receipt);
  UPDATE sessions SET status = p_outcome WHERE session_id = p_sid;
  RETURN v_receipt;
END $function$;

CREATE OR REPLACE FUNCTION public.v13_wake_is_satisfied_v1(p_sid uuid, p_effect uuid, p_wake jsonb)
 RETURNS boolean
 LANGUAGE plpgsql
AS $function$
DECLARE v_kind text; v_tail bigint; v_at timestamptz; v_id text; v_n int; v_st text; v_parent uuid;
BEGIN
  IF p_wake IS NULL OR jsonb_typeof(p_wake) <> 'object' THEN
    RAISE EXCEPTION 'v13: harness_result schema';
  END IF;
  v_kind := p_wake->>'kind';
  IF v_kind = 'children_terminal' THEN
    IF jsonb_typeof(p_wake->'child_session_ids') <> 'array'
       OR jsonb_array_length(p_wake->'child_session_ids') < 1 THEN
      RAISE EXCEPTION 'v13: children_terminal child';
    END IF;
    SELECT count(*), count(DISTINCT x) INTO v_n, v_tail
      FROM jsonb_array_elements_text(p_wake->'child_session_ids') x;
    IF v_n IS DISTINCT FROM v_tail THEN
      RAISE EXCEPTION 'v13: children_terminal duplicate';
    END IF;
    FOR v_id IN SELECT x FROM jsonb_array_elements_text(p_wake->'child_session_ids') x LOOP
      IF NOT v13_canonical_uuid(v_id) THEN
        RAISE EXCEPTION 'v13: children_terminal child';
      END IF;
      SELECT status, parent_session_id INTO v_st, v_parent
        FROM sessions WHERE session_id = v_id::uuid;
      IF NOT FOUND OR v_parent IS DISTINCT FROM p_sid THEN
        RAISE EXCEPTION 'v13: children_terminal child';
      END IF;
      IF v_st NOT IN ('completed', 'failed', 'cancelled') THEN
        RETURN false;
      END IF;
    END LOOP;
    RETURN true;
  ELSIF v_kind = 'event' THEN
    IF NOT EXISTS (
      SELECT 1 FROM events
       WHERE session_id = p_sid AND source_effect_id = p_effect AND type = 'effect_done') THEN
      RAISE EXCEPTION 'v13: effect_done missing';
    END IF;
    SELECT max(seq) INTO v_tail FROM events
     WHERE session_id = p_sid AND source_effect_id = p_effect
       AND type IN ('effect_done', 'tool/result', 'llm/message', 'repair/required', 'replan/required');
    IF v_tail IS NULL THEN
      RAISE EXCEPTION 'v13: effect_done missing';
    END IF;
    RETURN EXISTS (
      SELECT 1 FROM events
       WHERE session_id = p_sid AND type = p_wake->>'event_type' AND seq > v_tail);
  ELSIF v_kind = 'not_before' THEN
    v_at := (p_wake->>'at')::timestamptz;
    RETURN clock_timestamp() >= v_at;
  ELSIF v_kind = 'artifact' THEN
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'artifacts' AND column_name = 'content_hash')
       OR NOT EXISTS (
      SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'artifacts' AND column_name = 'produced_by') THEN
      RAISE EXCEPTION 'v13: artifact wake requires content_hash';
    END IF;
    RETURN EXISTS (
      SELECT 1 FROM artifacts a
      JOIN effects e ON e.effect_id = a.produced_by
       WHERE a.content_hash = p_wake->>'content_hash' AND e.status = 'succeeded');
  ELSE
    RAISE EXCEPTION 'v13: harness_result schema';
  END IF;
END $function$;

CREATE OR REPLACE FUNCTION public.v13_complete(p_effect uuid, p_attempt integer, p_fence bigint, p_status text, p_result jsonb DEFAULT NULL::jsonb)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_sid uuid; v_row effects; v_outcome text; v_err jsonb; v_human jsonb;
  v_resp boolean := false; v_ans boolean := false; v_skip boolean := false;
  v_n int := 0; k text; v_t text; v_calls jsonb;
BEGIN
  IF p_status NOT IN ('succeeded', 'failed', 'unknown') THEN
    RAISE EXCEPTION 'v13: bad outcome %', p_status;
  END IF;
  IF p_attempt IS NULL OR p_fence IS NULL THEN
    RAISE EXCEPTION 'v13: complete requires non-NULL (attempt,fence) tokens (effect %)', p_effect;
  END IF;
  SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF v_row.attempt_no IS DISTINCT FROM p_attempt OR v_row.fence IS DISTINCT FROM p_fence THEN
    RETURN 'stale';
  END IF;
  IF v_row.status IN ('succeeded', 'failed', 'unknown', 'cancelled') THEN
    RETURN 'replay';
  END IF;
  IF v_row.status <> 'claimed' THEN
    RETURN 'stale';
  END IF;
  IF v_row.kind = 'human' AND p_status = 'succeeded' AND v_row.request ? 'interaction_ref' THEN
    IF p_result IS NULL OR jsonb_typeof(p_result) <> 'object' THEN
      RAISE EXCEPTION 'v13: human channel';
    END IF;
    FOR k IN SELECT jsonb_object_keys(p_result) LOOP
      IF k NOT IN ('schema_version', 'interaction_ref', 'response', 'answers', 'skip') THEN
        RAISE EXCEPTION 'v13: human channel unknown key %', k;
      END IF;
    END LOOP;
    IF NOT v13_json_int_ok(p_result->'schema_version', 1)
       OR (p_result->'schema_version')::text::numeric <> 1 THEN
      RAISE EXCEPTION 'v13: human channel schema_version';
    END IF;
    IF jsonb_typeof(p_result->'interaction_ref') IS DISTINCT FROM 'string'
       OR p_result->>'interaction_ref' IS DISTINCT FROM v_row.request->>'interaction_ref' THEN
      RAISE EXCEPTION 'v13: human interaction_ref mismatch (submitted=%, current=%)',
        p_result->>'interaction_ref', v_row.request->>'interaction_ref';
    END IF;
    IF p_result ? 'response' THEN
      v_t := jsonb_typeof(p_result->'response');
      IF v_t IN ('array', 'object', 'null')
         OR (v_t = 'string' AND btrim(p_result->>'response') = '') THEN
        RAISE EXCEPTION 'v13: human channel illegal response';
      END IF;
    END IF;
    IF p_result ? 'answers' THEN
      IF jsonb_typeof(p_result->'answers') IS DISTINCT FROM 'object'
         OR p_result->'answers' = '{}'::jsonb THEN
        RAISE EXCEPTION 'v13: human channel illegal answers';
      END IF;
    END IF;
    IF p_result ? 'skip' AND jsonb_typeof(p_result->'skip') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: human channel illegal skip';
    END IF;
    v_resp := p_result ? 'response' AND jsonb_typeof(p_result->'response') IN ('string', 'number', 'boolean')
              AND (jsonb_typeof(p_result->'response') <> 'string' OR btrim(p_result->>'response') <> '');
    v_ans := p_result ? 'answers' AND jsonb_typeof(p_result->'answers') = 'object'
             AND p_result->'answers' <> '{}'::jsonb;
    v_skip := p_result ? 'skip' AND p_result->'skip' = 'true'::jsonb;
    v_n := v_resp::int + v_ans::int + v_skip::int;
    IF v_n <> 1 THEN
      RAISE EXCEPTION 'v13: human channel one-of';
    END IF;
    v_human := jsonb_build_object(
      'schema_version', 1,
      'interaction_ref', v_row.request->>'interaction_ref',
      'skip', CASE WHEN v_skip THEN 'true'::jsonb ELSE 'null'::jsonb END,
      'response', CASE WHEN v_resp THEN p_result->'response' ELSE 'null'::jsonb END,
      'answers', CASE WHEN v_ans THEN p_result->'answers' ELSE 'null'::jsonb END,
      'origin_user_seq', v_row.origin_user_seq);
  END IF;
  IF v_row.kind = 'tool' AND v13_is_harness_tool(v_row.tool_name, v_row.kind) THEN
    IF NOT v13_harness_request_ok(v_row.request) THEN
      RAISE EXCEPTION 'v13: logical_turn_id required';
    END IF;
    IF p_status = 'succeeded' THEN
      PERFORM v13_validate_harness_result_v1(p_result);
    END IF;
  ELSIF v_row.request ? 'logical_turn_id' OR v_row.request ? 'continuation_index'
        OR (p_status = 'succeeded' AND v_row.kind <> 'tool' AND p_result ? 'result_kind') THEN
    RAISE EXCEPTION 'v13: logical_turn_id required';
  END IF;
  v_outcome := p_status; v_err := NULL;
  IF p_status = 'succeeded' AND v_row.kind = 'llm'
     AND (coalesce(jsonb_typeof(p_result->'text'), 'null') <> 'string'
          OR coalesce(btrim(p_result->>'text'), '') = '') THEN
    v_outcome := 'failed';
    v_err := jsonb_build_object('code', 'llm_result_shape');
  END IF;
  IF v_row.kind = 'llm' AND p_status = 'succeeded' AND p_result ? 'tool_calls' THEN
    v_calls := v13_llm_tool_calls(p_result->'tool_calls');
  END IF;
  UPDATE effects SET status = v_outcome, result = p_result, error = v_err
   WHERE effect_id = p_effect;
  PERFORM v13_append_event(v_sid, gen_random_uuid(), 'effect_done',
    jsonb_build_object('effect_id', p_effect, 'status', v_outcome), p_effect);
  IF v_outcome = 'succeeded' AND v_row.kind = 'tool' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'tool/result',
      jsonb_build_object('tool', v_row.tool_name, 'result', p_result,
                         'origin_user_seq', v_row.origin_user_seq), p_effect);
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'llm' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'llm/message',
      p_result || jsonb_build_object('origin_user_seq', v_row.origin_user_seq), p_effect);
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'llm' AND v_calls IS NOT NULL THEN
    FOR v_n IN 0..jsonb_array_length(v_calls) - 1 LOOP
      PERFORM v13_append_event(v_sid, gen_random_uuid(), 'tool/call', v_calls->v_n, p_effect);
    END LOOP;
  END IF;
  IF v_outcome = 'succeeded' AND v_row.kind = 'tool'
     AND v13_is_harness_tool(v_row.tool_name, v_row.kind) AND p_result ? 'signals' THEN
    IF p_result->'signals' @> '["repair/required"]'::jsonb THEN
      PERFORM v13_append_event(v_sid, gen_random_uuid(), 'repair/required',
        jsonb_build_object('schema_version', 1), p_effect);
    END IF;
    IF p_result->'signals' @> '["replan/required"]'::jsonb THEN
      PERFORM v13_append_event(v_sid, gen_random_uuid(), 'replan/required',
        jsonb_build_object('schema_version', 1), p_effect);
    END IF;
  END IF;
  IF v_human IS NOT NULL AND v_outcome = 'succeeded' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'human/responded', v_human, p_effect);
  END IF;
  IF v_outcome = 'failed' AND v_row.kind = 'judge' THEN
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('effect_id', p_effect, 'path', 'worker',
                         'origin_user_seq', v_row.origin_user_seq));
  END IF;
  IF v_outcome = 'unknown' THEN
    PERFORM v13_raise_unknown_wall(v_sid);
  END IF;
  RETURN 'accepted';
END $function$;

CREATE OR REPLACE FUNCTION public.v13_advance(p_sid uuid, p_snap jsonb)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_now jsonb; v_route jsonb; v_cycles int; v_max int;
  v_effect uuid; v_est text; v_res jsonb; v_handler text; v_req jsonb; v_err jsonb;
  v_pred uuid; v_prow effects; v_sig text[]; v_ev text[]; v_cand boolean;
  v_cap_new boolean; v_cont boolean; v_idx bigint; v_st text;
  v_calls jsonb; v_sreq jsonb;
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
  IF jsonb_array_length(v_calls) > 0 THEN
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
      v_cap_new := EXISTS (
        SELECT 1 FROM effects h
        JOIN events ev ON ev.source_effect_id = h.effect_id AND ev.type = 'human/responded'
         WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
           AND h.origin_user_seq = v13_last_user_seq(p_sid)
           AND h.request->>'interaction_kind' IN ('material_cap', 'repair_cap', 'replan_cap')
           AND ev.seq > coalesce((SELECT max(seq) FROM events
                                   WHERE source_effect_id = v_pred AND type = 'effect_done'), -1));
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
  v_route := v13_route(p_sid, p_snap->'envelope');
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

CREATE OR REPLACE FUNCTION public.v13_needed_judgments(p_sid uuid)
 RETURNS TABLE(signal text, kind text, question text, criteria jsonb, template_name text)
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  r_tool record; r_param record;
  v_tools jsonb; v_sigs text[] := '{}';
  v_tmpl jsonb; v_t jsonb;
BEGIN
  SELECT coalesce(jsonb_object_agg(t.template_name, jsonb_build_object(
           'kind', t.kind, 'question', t.question, 'criteria', t.criteria,
           'answer_schema_version', t.answer_schema_version,
           'provider', t.provider, 'model', t.model,
           'wire_version', t.wire_version, 'canon_version', t.canon_version)),
           '{}'::jsonb)
    INTO v_tmpl FROM v13_template_latest t;

  v_t := v_tmpl->'intent';
  IF v_t IS NULL OR v_t->>'question' IS NULL THEN
    RAISE EXCEPTION 'v13: frozen template "intent" missing or incomplete'
      USING ERRCODE = 'V3002';
  END IF;
  IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
     OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
    RAISE EXCEPTION
      'v13: template "intent" uses declarations unsupported in DP2'
      USING ERRCODE = 'V3002';
  END IF;
  signal := 'intent'; kind := v_t->>'kind';
  question := v_t->>'question';
  criteria := NULLIF(v_t->'criteria', 'null'::jsonb);
  template_name := 'intent';
  v_sigs := v_sigs || signal; RETURN NEXT;

  v_t := v_tmpl->'gate_action';
  IF v_t IS NULL OR v_t->>'question' IS NULL THEN
    RAISE EXCEPTION 'v13: frozen template "gate_action" missing or incomplete'
      USING ERRCODE = 'V3002';
  END IF;
  IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
     OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
    RAISE EXCEPTION
      'v13: template "gate_action" uses declarations unsupported in DP2'
      USING ERRCODE = 'V3002';
  END IF;
  signal := 'gate_action'; kind := v_t->>'kind';
  question := v_t->>'question';
  criteria := NULLIF(v_t->'criteria', 'null'::jsonb);
  template_name := 'gate_action';
  v_sigs := v_sigs || signal; RETURN NEXT;

  v_t := v_tmpl->'gate_off_topic';
  IF v_t IS NULL OR v_t->>'question' IS NULL THEN
    RAISE EXCEPTION
      'v13: frozen template "gate_off_topic" missing or incomplete'
      USING ERRCODE = 'V3002';
  END IF;
  IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
     OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
    RAISE EXCEPTION
      'v13: template "gate_off_topic" uses declarations unsupported in DP2'
      USING ERRCODE = 'V3002';
  END IF;
  signal := 'gate_off_topic'; kind := v_t->>'kind';
  question := v_t->>'question';
  criteria := NULLIF(v_t->'criteria', 'null'::jsonb);
  template_name := 'gate_off_topic';
  v_sigs := v_sigs || signal; RETURN NEXT;

  v_t := v_tmpl->'risk';
  IF v_t IS NULL OR v_t->>'question' IS NULL THEN
    RAISE EXCEPTION 'v13: frozen template "risk" missing or incomplete'
      USING ERRCODE = 'V3002';
  END IF;
  IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
     OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
    RAISE EXCEPTION
      'v13: template "risk" uses declarations unsupported in DP2'
      USING ERRCODE = 'V3002';
  END IF;
  signal := 'risk'; kind := v_t->>'kind';
  question := v_t->>'question';
  criteria := NULLIF(v_t->'criteria', 'null'::jsonb);
  template_name := 'risk';
  v_sigs := v_sigs || signal; RETURN NEXT;

  v_tools := (SELECT coalesce(jsonb_agg(jsonb_build_object(
                'name', t.name, 'description', t.description,
                'spec', t.param_spec) ORDER BY t.name), '[]')
                FROM (SELECT name, description, param_spec FROM tools
                       WHERE enabled AND tools.kind IN ('sql','tool')
                         AND NOT v13_is_spawn_tool(name, kind)) t);
  IF jsonb_array_length(v_tools) > 0 THEN
    v_t := v_tmpl->'tool';
    IF v_t IS NULL OR v_t->>'question' IS NULL THEN
      RAISE EXCEPTION 'v13: frozen template "tool" missing or incomplete'
        USING ERRCODE = 'V3002';
    END IF;
    IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
       OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
      RAISE EXCEPTION
        'v13: template "tool" uses declarations unsupported in DP2'
        USING ERRCODE = 'V3002';
    END IF;
    signal := 'tool'; kind := v_t->>'kind';
    question := v_t->>'question';
    criteria := (SELECT jsonb_object_agg(t->>'name', t->>'description')
                   || '{"none": "No registered tool fits the request."}'::jsonb
                  FROM jsonb_array_elements(v_tools) t);
    template_name := 'tool';
    v_sigs := v_sigs || signal; RETURN NEXT;
  END IF;

  FOR r_tool IN SELECT t->>'name' AS name, t->'spec' AS spec
                  FROM jsonb_array_elements(v_tools) t LOOP
    FOR r_param IN SELECT key AS pkey, value AS spec
                    FROM jsonb_each(r_tool.spec) LOOP
      v_t := v_tmpl->'param';
      IF v_t IS NULL THEN
        RAISE EXCEPTION 'v13: frozen template "param" missing'
          USING ERRCODE = 'V3002';
      END IF;
      IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
         OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
        RAISE EXCEPTION
          'v13: template "param" uses declarations unsupported in DP2'
          USING ERRCODE = 'V3002';
      END IF;
      signal := 'param::'  || r_tool.name || '::' || r_param.pkey;
      kind := v_t->>'kind';
      question := r_param.spec->>'question';
      criteria := r_param.spec->'options';
      template_name := 'param';
      v_sigs := v_sigs || signal; RETURN NEXT;
      v_t := v_tmpl->'stated';
      IF v_t IS NULL THEN
        RAISE EXCEPTION 'v13: frozen template "stated" missing'
          USING ERRCODE = 'V3002';
      END IF;
      IF (v_t->>'wire_version')::int <> 1 OR (v_t->>'canon_version')::int <> 1
         OR v_t->>'provider' IS NOT NULL OR v_t->>'model' IS NOT NULL THEN
        RAISE EXCEPTION
          'v13: template "stated" uses declarations unsupported in DP2'
          USING ERRCODE = 'V3002';
      END IF;
      signal := 'stated::' || r_tool.name || '::' || r_param.pkey;
      kind := v_t->>'kind';
      question := r_param.spec->>'stated';
      criteria := NULL;
      template_name := 'stated';
      v_sigs := v_sigs || signal; RETURN NEXT;
    END LOOP;
  END LOOP;

  PERFORM 1 FROM unnest(v_sigs) s GROUP BY s HAVING count(*) > 1;
  IF FOUND THEN
    RAISE EXCEPTION 'v13: needed signal collision (tools catalog violates syntax guard?)';
  END IF;
END $function$;

CREATE OR REPLACE FUNCTION public.v13_tools_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE k text; v_n int;
BEGIN
  IF NEW.name IS NULL OR NEW.name = '' OR NEW.name LIKE '%::%' THEN
    RAISE EXCEPTION
      'v13: tool name must be non-empty and contain no "::" (signal identity): %',
      NEW.name;
  END IF;
  IF jsonb_typeof(NEW.param_spec) = 'object' THEN
    FOR k IN SELECT jsonb_object_keys(NEW.param_spec) LOOP
      IF k = '' OR k LIKE '%::%' THEN
        RAISE EXCEPTION
          'v13: tool % param key must be non-empty and contain no "::" : %',
          NEW.name, k;
      END IF;
    END LOOP;
  END IF;
  IF NEW.kind = 'sql' AND NEW.enabled THEN   -- 只校验 enabled 行(turn 8,#53)
    SELECT count(*) INTO v_n FROM pg_proc p
     WHERE p.proname = NEW.handler
       AND oidvectortypes(p.proargtypes) = 'uuid, jsonb';
    IF v_n = 0 THEN
      RAISE EXCEPTION
        'v13: sql tool % handler % not found (signature (uuid,jsonb)->jsonb)',
        NEW.name, NEW.handler;
    ELSIF v_n > 1 THEN
      RAISE EXCEPTION
        'v13: sql tool % handler % ambiguous across schemas (%)',
        NEW.name, NEW.handler, v_n;
    END IF;
    IF EXISTS (
      SELECT 1 FROM pg_proc p
       WHERE p.proname = NEW.handler
         AND oidvectortypes(p.proargtypes) = 'uuid, jsonb'
         AND p.provolatile = 'v') THEN
      IF v13_named_sql_writer(NEW.handler) IS NULL OR NOT v13_spawn_writer_ok(NEW.handler) THEN
        RAISE EXCEPTION 'v13: sql writer closed (% config %)', NEW.handler,
          (SELECT p.proconfig FROM pg_proc p
            WHERE p.proname = NEW.handler
              AND oidvectortypes(p.proargtypes) = 'uuid, jsonb');
      END IF;
    ELSIF NOT EXISTS (
      SELECT 1 FROM pg_proc p
       WHERE p.proname = NEW.handler
         AND oidvectortypes(p.proargtypes) = 'uuid, jsonb'
         AND p.provolatile IN ('i','s')
         AND p.prorettype = 'jsonb'::regtype
         AND has_function_privilege('v13_route', p.oid, 'EXECUTE')) THEN
      RAISE EXCEPTION
        'v13: sql tool % handler % must be IMMUTABLE/STABLE, return jsonb, and be executable by v13_route',
        NEW.name, NEW.handler;
    END IF;
  END IF;
  RETURN NEW;
END $function$;

CREATE FUNCTION public.v13_spawn_writer_ok(p_handler text) RETURNS boolean
LANGUAGE sql STABLE AS $fn$
  SELECT EXISTS (
    SELECT 1
      FROM pg_proc p
      JOIN pg_roles r ON r.oid = p.proowner
     WHERE p.proname = CASE
             WHEN p_handler LIKE 'public.%' THEN split_part(p_handler, '.', 2)
             ELSE p_handler END
       AND oidvectortypes(p.proargtypes) = 'uuid, jsonb'
       AND p.prorettype = 'jsonb'::regtype
       AND p.provolatile = 'v'
       AND p.prosecdef
       AND r.rolname = 'v13_spawn_owner'
       AND cardinality(p.proconfig) = 1
       AND replace(p.proconfig[1], ' ', '') = 'search_path=pg_catalog,public'
       AND p.proacl IS NOT NULL
       AND NOT EXISTS (
         SELECT 1 FROM aclexplode(p.proacl) a
          WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE')
       AND has_function_privilege('v13_route', p.oid, 'EXECUTE')
       AND position('dblink' in lower(p.prosrc)) = 0
       AND position('pg_net' in lower(p.prosrc)) = 0
       AND position('copy program' in lower(p.prosrc)) = 0
       AND position('lo_import' in lower(p.prosrc)) = 0
       AND position('lo_export' in lower(p.prosrc)) = 0
       AND position('pg_read_file' in lower(p.prosrc)) = 0
       AND position('pg_write_file' in lower(p.prosrc)) = 0
       AND v13_named_sql_writer(p_handler) =
           '{"mutating":false,"write_targets":["artifacts","events","latches","sessions"]}'::jsonb)
$fn$;

REVOKE EXECUTE ON FUNCTION
  v13_is_spawn_tool(text, text),
  v13_advisory_class(text),
  v13_named_sql_writer(text),
  v13_spawn_request(jsonb),
  v13_spawn_children(jsonb),
  v13_llm_tool_calls(jsonb),
  v13_direct_children_open(uuid),
  v13_park_open_children(uuid),
  v13_spawn_occupancy(uuid),
  v13_insert_nudge(uuid, text, text),
  v13_spawn_event_guard(),
  v13_open_session(jsonb),
  v13_spawn_subsession(uuid, jsonb),
  v_goal_tree(uuid),
  v13_recover_idle(),
  v13_fork(uuid, bigint, text, jsonb),
  v13_spawn_writer_ok(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_is_spawn_tool(text, text),
  v13_spawn_request(jsonb),
  v13_spawn_children(jsonb),
  v13_llm_tool_calls(jsonb),
  v13_direct_children_open(uuid),
  v13_park_open_children(uuid),
  v13_open_session(jsonb),
  v13_spawn_subsession(uuid, jsonb),
  v13_recover_idle(),
  v13_insert_nudge(uuid, text, text),
  v_goal_tree(uuid)
TO v13_route;
GRANT EXECUTE ON FUNCTION v_goal_tree(uuid) TO v13_recall, v13_resolve;

GRANT USAGE ON SCHEMA public TO v13_spawn_owner;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO v13_spawn_owner;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO v13_spawn_owner;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO v13_spawn_owner;
GRANT EXECUTE ON FUNCTION
  public.v13_spawn_children(jsonb),
  public.v13_spawn_occupancy(uuid),
  public.v13_spawn_request(jsonb),
  public.v13_advisory_class(text),
  public.v13_llm_tool_calls(jsonb),
  public.v13_json_keys(jsonb),
  public.v13_json_int_ok(jsonb, numeric),
  public.v13_policy(text),
  public.v13_effect_id(uuid, text, jsonb),
  public.v13_append_event(uuid, uuid, text, jsonb, uuid),
  public.v13_generation_effective(uuid),
  public.v13_prefix_identity(uuid),
  public.v13_insert_nudge(uuid, text, text),
  public.v13_direct_children_open(uuid),
  public.v13_named_sql_writer(text),
  public.v13_spawn_writer_ok(text)
TO v13_spawn_owner;
REVOKE INSERT ON sessions FROM PUBLIC, v13_route, v13_resolve, v13_recall,
  v13_route_login, v13_resolve_login, v13_worker;

INSERT INTO tools (name, description, kind, handler, param_spec, enabled) VALUES (
  'spawn_subsession',
  'Spawn a batch of fresh child sessions.',
  'sql', 'v13_spawn_subsession', '{}'::jsonb, true);

DO $self$
DECLARE v_sid uuid; v_msg text;
BEGIN
  EXECUTE 'SET LOCAL ROLE v13_spawn_owner';
  v_sid := v13_open_session('{}'::jsonb);
  IF v_sid IS NULL THEN
    RAISE EXCEPTION 'v13: open_session self-check';
  END IF;
  EXECUTE 'RESET ROLE';
  DELETE FROM sessions WHERE session_id = v_sid;
  EXECUTE 'SET LOCAL ROLE v13_route';
  BEGIN
    INSERT INTO sessions (session_id) VALUES (gen_random_uuid());
    RAISE EXCEPTION 'v13: route insert self-check succeeded';
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
    IF v_msg LIKE '%self-check succeeded%' THEN
      RAISE;
    END IF;
  END;
  EXECUTE 'RESET ROLE';
END
$self$;

COMMIT;
