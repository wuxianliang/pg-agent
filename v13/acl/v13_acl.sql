-- v13 acl (stage 23). Overload bodies; kinship predicate. No new tables.
BEGIN;

DO $acl_baseline$
DECLARE
  v_cancel text;
  v_complete text;
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_attribute
     WHERE attrelid = 'public.sessions'::regclass
       AND attname = 'parent_session_id'
       AND atttypid = 'uuid'::regtype
       AND NOT attisdropped
  ) THEN
    RAISE EXCEPTION 'v13: acl baseline';
  END IF;
  IF (
    SELECT count(*)
      FROM pg_proc
     WHERE pronamespace = 'public'::regnamespace
       AND proname = 'v13_cancel'
  ) <> 1
     OR to_regprocedure('public.v13_cancel(uuid)') IS NULL
     OR to_regprocedure('public.v13_cancel(uuid,uuid)') IS NOT NULL
  THEN
    RAISE EXCEPTION 'v13: acl baseline';
  END IF;
  IF (
    SELECT count(*)
      FROM pg_proc
     WHERE pronamespace = 'public'::regnamespace
       AND proname = 'v13_complete'
  ) <> 1
     OR to_regprocedure('public.v13_complete(uuid,integer,bigint,text,jsonb)') IS NULL
     OR to_regprocedure('public.v13_complete(uuid,uuid,integer,bigint,text,jsonb)') IS NOT NULL
  THEN
    RAISE EXCEPTION 'v13: acl baseline';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM pg_proc
     WHERE proname IN (
       'v13_control_authorized', 'v13_control_operator', 'v13_observe',
       'v13_session_log', 'v13_extract_handoff', 'v13_transcript_hash',
       'v13_handoff_emit')
  ) THEN
    RAISE EXCEPTION 'v13: acl baseline';
  END IF;
  IF pg_has_role('v13_worker', 'v13_route', 'USAGE') THEN
    RAISE EXCEPTION 'v13: acl baseline';
  END IF;
  v_cancel := pg_get_functiondef('public.v13_cancel(uuid)'::regprocedure);
  v_complete := pg_get_functiondef('public.v13_complete(uuid,integer,bigint,text,jsonb)'::regprocedure);
  IF position('v13: unknown session' IN v_cancel) = 0
     OR position('v13: goal tree cycle' IN v_cancel) = 0
     OR position('v13: goal tree depth' IN v_cancel) = 0
     OR position('v13: cancel tree changed' IN v_cancel) = 0
     OR position('RETURN ''replay''' IN v_cancel) = 0
     OR position('v13: unknown effect' IN v_complete) = 0
     OR position('v13: human channel one-of' IN v_complete) = 0
     OR position('v13: human interaction_ref mismatch' IN v_complete) = 0
     OR position('v13: cancel not pending' IN v_complete) = 0
     OR position('v13_record_worktree_released' IN v_complete) = 0
     OR position('EXCEPTION WHEN' IN v_cancel) > 0
     OR position('EXCEPTION WHEN' IN v_complete) > 0
  THEN
    RAISE EXCEPTION 'v13: acl baseline';
  END IF;
END
$acl_baseline$;

CREATE FUNCTION public.v13_control_operator()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $acl_op$
BEGIN
  RETURN EXISTS (
    SELECT 1
      FROM pg_roles
     WHERE rolname = current_user
       AND rolsuper
  ) OR pg_has_role(current_user, 'v13_route', 'USAGE');
END
$acl_op$;

CREATE FUNCTION public.v13_control_authorized(p_actor uuid, p_target uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $acl_auth$
DECLARE
  v_parent uuid;
BEGIN
  SELECT parent_session_id
    INTO v_parent
    FROM public.sessions
   WHERE session_id = p_target;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF p_actor IS NULL THEN
    RETURN public.v13_control_operator();
  END IF;
  IF p_actor = p_target THEN
    RETURN false;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.sessions WHERE session_id = p_actor
  ) THEN
    RETURN false;
  END IF;
  RETURN v_parent IS NOT DISTINCT FROM p_actor;
END
$acl_auth$;

CREATE FUNCTION public.v13_cancel(p_actor uuid, p_sid uuid)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $acl_cancel2$
DECLARE
  r record;
  v_st text;
  v_extra int;
  v_actor uuid;
BEGIN
  v_actor := p_actor;
  IF v_actor IS NOT NULL THEN
    IF NOT public.v13_control_authorized(v_actor, p_sid) THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
  ELSIF NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  CREATE TEMP TABLE IF NOT EXISTS v13_fanout_cancel_tree (
    session_id uuid PRIMARY KEY,
    depth int NOT NULL,
    status text NOT NULL,
    path uuid[] NOT NULL
  ) ON COMMIT DROP;
  DELETE FROM v13_fanout_cancel_tree;
  INSERT INTO v13_fanout_cancel_tree (session_id, depth, status, path)
  WITH RECURSIVE tree AS (
    SELECT session_id, status, 0 AS depth, ARRAY[session_id] AS path
      FROM sessions WHERE session_id = p_sid
    UNION ALL
    SELECT s.session_id, s.status, t.depth + 1, t.path || s.session_id
      FROM sessions s
      JOIN tree t ON s.parent_session_id = t.session_id
     WHERE t.depth < 64
       AND NOT s.session_id = ANY (t.path)
  )
  SELECT session_id, depth, status, path FROM tree;
  IF EXISTS (
    SELECT 1
      FROM v13_fanout_cancel_tree t
      JOIN sessions s ON s.parent_session_id = t.session_id
     WHERE s.session_id = ANY (t.path)
  ) THEN
    RAISE EXCEPTION 'v13: goal tree cycle';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM v13_fanout_cancel_tree t
      JOIN sessions s ON s.parent_session_id = t.session_id
     WHERE t.depth = 64
       AND NOT EXISTS (
         SELECT 1 FROM v13_fanout_cancel_tree c WHERE c.session_id = s.session_id)
  ) THEN
    RAISE EXCEPTION 'v13: goal tree depth';
  END IF;
  FOR r IN
    SELECT s.session_id
      FROM sessions s
      JOIN v13_fanout_cancel_tree t ON t.session_id = s.session_id
     ORDER BY s.session_id
     FOR UPDATE OF s
  LOOP
  END LOOP;
  SELECT count(*) INTO v_extra
    FROM sessions s
    JOIN v13_fanout_cancel_tree t ON s.parent_session_id = t.session_id
   WHERE NOT EXISTS (
     SELECT 1 FROM v13_fanout_cancel_tree c WHERE c.session_id = s.session_id);
  IF v_extra > 0 THEN
    RAISE EXCEPTION 'v13: cancel tree changed';
  END IF;
  IF v_actor IS NOT NULL AND NOT public.v13_control_authorized(v_actor, p_sid) THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = p_sid;
  IF v_st IN ('completed', 'failed', 'cancelled') THEN
    RETURN 'replay';
  END IF;
  UPDATE v13_fanout_cancel_tree t
     SET status = s.status
    FROM sessions s
   WHERE s.session_id = t.session_id;
  FOR r IN
    SELECT e.effect_id
      FROM effects e
      JOIN v13_fanout_cancel_tree t ON t.session_id = e.session_id
     WHERE t.status NOT IN ('completed', 'failed', 'cancelled')
     ORDER BY e.effect_id
     FOR UPDATE OF e
  LOOP
  END LOOP;
  FOR r IN
    SELECT session_id
      FROM v13_fanout_cancel_tree
     WHERE status NOT IN ('completed', 'failed', 'cancelled')
     ORDER BY depth, session_id
  LOOP
    IF NOT v13_unconsumed_cancel(r.session_id) THEN
      PERFORM v13_append_event(r.session_id, gen_random_uuid(), 'cancel/requested',
        jsonb_build_object('schema_version', 1, 'scope', 'session'));
    END IF;
    UPDATE effects
       SET status = 'cancelled', fence = fence + 1, error = NULL,
           lease_owner = NULL, lease_until = NULL
     WHERE session_id = r.session_id AND status = 'ready';
  END LOOP;
  RETURN 'accepted';
END
$acl_cancel2$;

CREATE OR REPLACE FUNCTION public.v13_cancel(p_sid uuid)
RETURNS text
LANGUAGE plpgsql
AS $acl_cancel1$
BEGIN
  RETURN v13_cancel(NULL::uuid, p_sid);
END
$acl_cancel1$;

CREATE FUNCTION public.v13_complete(
  p_actor uuid,
  p_effect uuid,
  p_attempt integer,
  p_fence bigint,
  p_status text,
  p_result jsonb DEFAULT NULL::jsonb)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $acl_complete6$
DECLARE
  v_sid uuid; v_kind text; v_row effects; v_outcome text; v_err jsonb; v_human jsonb;
  v_resp boolean := false; v_ans boolean := false; v_skip boolean := false;
  v_n int := 0; k text; v_t text; v_calls jsonb; v_tier text;
BEGIN
  IF p_status NOT IN ('succeeded', 'failed', 'unknown', 'cancelled') THEN
    RAISE EXCEPTION 'v13: bad outcome %', p_status;
  END IF;
  IF p_attempt IS NULL OR p_fence IS NULL THEN
    RAISE EXCEPTION 'v13: complete requires non-NULL (attempt,fence) tokens (effect %)', p_effect;
  END IF;
  SELECT session_id, kind INTO v_sid, v_kind FROM effects WHERE effect_id = p_effect;
  IF p_actor IS NOT NULL THEN
    IF NOT FOUND OR v_kind IS DISTINCT FROM 'human' THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
    IF NOT public.v13_control_authorized(p_actor, v_sid) THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
  ELSIF NOT FOUND THEN
    IF public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: unknown effect %', p_effect;
    END IF;
    RAISE EXCEPTION 'v13: session not found';
  ELSIF v_kind = 'human' AND NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF NOT FOUND THEN
    IF p_actor IS NOT NULL OR NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF p_actor IS NOT NULL THEN
    IF v_row.kind IS DISTINCT FROM 'human'
       OR NOT public.v13_control_authorized(p_actor, v_row.session_id) THEN
      RAISE EXCEPTION 'v13: session not found';
    END IF;
  ELSIF v_row.kind = 'human' AND NOT public.v13_control_operator() THEN
    RAISE EXCEPTION 'v13: session not found';
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
  IF p_status = 'cancelled' THEN
    v_tier := v13_interruptible(v_row.tool_name);
    IF v_row.kind = 'tool' AND v_tier = 'required' THEN
      RAISE EXCEPTION 'v13: mutating interrupt settles unknown';
    END IF;
    IF v_tier = 'unsupported' THEN
      RAISE EXCEPTION 'v13: interruptible unsupported';
    END IF;
    IF NOT v13_unconsumed_cancel(v_sid) THEN
      RAISE EXCEPTION 'v13: cancel not pending';
    END IF;
    IF NOT (v_tier = 'best_effort' OR (v_tier = 'required' AND v_row.kind = 'llm')) THEN
      RAISE EXCEPTION 'v13: bad outcome cancelled';
    END IF;
    UPDATE effects
       SET status = 'cancelled', result = NULL, error = NULL
     WHERE effect_id = p_effect;
    PERFORM v13_append_event(v_sid, gen_random_uuid(), 'effect_done',
      jsonb_build_object('effect_id', p_effect, 'status', 'cancelled'), p_effect);
    RETURN 'accepted';
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
  IF p_status = 'succeeded'
     AND v_row.tool_name IN ('worktree_prepare', 'worktree_merge', 'worktree_release') THEN
    IF NOT v13_worktree_request_ok(v_row.tool_name, v_row.request) THEN
      RAISE EXCEPTION 'v13: worktree request';
    END IF;
    IF v_row.tool_name = 'worktree_prepare' AND NOT v13_worktree_inline_ok(p_result) THEN
      RAISE EXCEPTION 'v13: worktree inline';
    END IF;
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
  IF v_outcome = 'succeeded'
     AND v_row.kind = 'tool'
     AND v_row.tool_name = 'worktree_release' THEN
    PERFORM v13_record_worktree_released(v_sid, p_effect);
  END IF;
  RETURN 'accepted';
END $acl_complete6$;

CREATE OR REPLACE FUNCTION public.v13_complete(
  p_effect uuid,
  p_attempt integer,
  p_fence bigint,
  p_status text,
  p_result jsonb DEFAULT NULL::jsonb)
RETURNS text
LANGUAGE plpgsql
AS $acl_complete5$
BEGIN
  RETURN v13_complete(NULL::uuid, p_effect, p_attempt, p_fence, p_status, p_result);
END
$acl_complete5$;

REVOKE EXECUTE ON FUNCTION public.v13_control_operator() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_control_authorized(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_cancel(uuid, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_complete(uuid, uuid, integer, bigint, text, jsonb) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.v13_control_operator() TO v13_route, v13_spawn_owner;
GRANT EXECUTE ON FUNCTION public.v13_control_authorized(uuid, uuid) TO v13_route, v13_spawn_owner;
GRANT EXECUTE ON FUNCTION public.v13_cancel(uuid, uuid) TO v13_route, v13_spawn_owner;
GRANT EXECUTE ON FUNCTION public.v13_complete(uuid, uuid, integer, bigint, text, jsonb) TO v13_route, v13_spawn_owner;

COMMENT ON FUNCTION public.v13_control_operator() IS
  'stage 23: rolsuper or USAGE of v13_route; does not read sessions';
COMMENT ON FUNCTION public.v13_control_authorized(uuid, uuid) IS
  'stage 23: admin band or direct parent; status-neutral; returns boolean only';
COMMENT ON FUNCTION public.v13_cancel(uuid, uuid) IS
  'stage 23: cancel body; null actor is admin, non-null actor is kinship only';
COMMENT ON FUNCTION public.v13_cancel(uuid) IS
  'stage 23: delegates to v13_cancel(NULL, p_sid)';
COMMENT ON FUNCTION public.v13_complete(uuid, uuid, integer, bigint, text, jsonb) IS
  'stage 23: complete body; non-null actor admits human kinship only';
COMMENT ON FUNCTION public.v13_complete(uuid, integer, bigint, text, jsonb) IS
  'stage 23: delegates to v13_complete(NULL, ...)';

COMMIT;
