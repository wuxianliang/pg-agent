-- v13 control plane stage 19. Self-contained transaction. Prefix files untouched.
BEGIN;

DO $probe$
BEGIN
  IF position('tool_calls' IN pg_get_functiondef('v13_complete(uuid,integer,bigint,text,jsonb)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: complete live body missing tool_calls';
  END IF;
  IF to_regprocedure('v13_fork(uuid,bigint,text,jsonb)') IS NULL THEN
    RAISE EXCEPTION 'v13: fork signature missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'artifacts'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) ~* 'kind'
       AND pg_get_constraintdef(oid) !~* 'content_hash') THEN
    RAISE EXCEPTION 'v13: artifacts.kind check requires adjudication';
  END IF;
END
$probe$;

CREATE FUNCTION v13_cancel_pending(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM sessions s
     WHERE s.session_id = p_sid
       AND s.status NOT IN ('completed', 'failed', 'cancelled')
       AND EXISTS (
         SELECT 1 FROM events c
          WHERE c.session_id = p_sid AND c.type = 'cancel/requested'
            AND c.seq > coalesce((
                  SELECT max(seq) FROM events
                   WHERE session_id = p_sid AND type = 'session/cancelled'), -1)))
$fn$;

CREATE FUNCTION v13_interruptible(p_name text) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT CASE p_name
    WHEN 'fanout_required' THEN 'required'
    WHEN 'fanout_best_effort' THEN 'best_effort'
    ELSE 'unsupported'
  END
$fn$;

CREATE FUNCTION v13_requires_worktree(p_name text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT coalesce(p_name IN ('worktree_merge', 'worktree_release'), false)
$fn$;

CREATE FUNCTION v13_latch_identity_excluded(p_name text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT p_name = 'worktree'
$fn$;

CREATE FUNCTION v13_worktree_request_ok(p_tool text, p_request jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT v13_json_keys(p_request) = ARRAY['handler', 'params', 'tool', 'tools_revision']
     AND p_request->>'tool' = p_tool
     AND p_tool IN ('worktree_prepare', 'worktree_merge', 'worktree_release')
     AND p_request->>'handler' = 'worker:' || p_tool
     AND jsonb_typeof(p_request->'params') = 'object'
     AND v13_json_keys(p_request->'params') = ARRAY['binding_artifact_id']
     AND v13_canonical_uuid(p_request->'params'->>'binding_artifact_id')
     AND v13_json_int_ok(p_request->'tools_revision', 9223372036854775807)
$fn$;

CREATE FUNCTION v13_worktree_inline_ok(p jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT v13_json_keys(p) = ARRAY['base_ref', 'root_path', 'schema_version']
     AND v13_json_int_ok(p->'schema_version', 1)
     AND (p->'schema_version')::text::numeric = 1
     AND jsonb_typeof(p->'root_path') = 'string'
     AND length(p->>'root_path') BETWEEN 1 AND 1024
     AND jsonb_typeof(p->'base_ref') = 'string'
     AND length(p->>'base_ref') BETWEEN 1 AND 256
$fn$;

CREATE FUNCTION v13_worktree_latch_ok(p jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT v13_json_keys(p) = ARRAY['binding_artifact_id', 'schema_version', 'state']
     AND v13_json_int_ok(p->'schema_version', 1)
     AND (p->'schema_version')::text::numeric = 1
     AND v13_canonical_uuid(p->>'binding_artifact_id')
     AND p->>'state' IN ('prepared', 'released')
$fn$;

CREATE FUNCTION v13_worktree_latch_guard() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
  IF NEW.name = 'worktree' AND NOT v13_worktree_latch_ok(NEW.value) THEN
    RAISE EXCEPTION 'v13: worktree latch';
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_worktree_latch
  BEFORE INSERT ON latches
  FOR EACH ROW EXECUTE FUNCTION v13_worktree_latch_guard();

CREATE FUNCTION v13_bind_worktree_from_prepare(p_sid uuid) RETURNS void
LANGUAGE plpgsql AS $fn$
DECLARE
  v_eid uuid; v_req jsonb; v_res jsonb; v_bid uuid; v_inline jsonb;
BEGIN
  IF EXISTS (SELECT 1 FROM latches WHERE session_id = p_sid AND name = 'worktree') THEN
    RETURN;
  END IF;
  SELECT e.source_effect_id INTO v_eid
    FROM events e
   WHERE e.session_id = p_sid
     AND e.type = 'tool/result'
     AND e.payload->>'tool' = 'worktree_prepare'
   ORDER BY e.seq
   LIMIT 1;
  IF v_eid IS NULL THEN
    RETURN;
  END IF;
  SELECT request, result INTO v_req, v_res
    FROM effects
   WHERE effect_id = v_eid AND status = 'succeeded';
  IF v_req IS NULL OR NOT v13_worktree_request_ok('worktree_prepare', v_req)
     OR NOT v13_worktree_inline_ok(v_res) THEN
    RAISE EXCEPTION 'v13: worktree prepare effect';
  END IF;
  v_bid := (v_req->'params'->>'binding_artifact_id')::uuid;
  v_inline := jsonb_build_object(
    'schema_version', 1,
    'root_path', v_res->>'root_path',
    'base_ref', v_res->>'base_ref');
  IF NOT EXISTS (SELECT 1 FROM artifacts WHERE artifact_id = v_bid) THEN
    INSERT INTO artifacts (artifact_id, content_hash, kind, inline, size, produced_by)
    VALUES (
      v_bid,
      encode(digest(v_inline::text, 'sha256'), 'hex'),
      'worktree_binding',
      v_inline,
      octet_length(v_inline::text),
      v_eid);
  ELSIF NOT EXISTS (
    SELECT 1 FROM artifacts
     WHERE artifact_id = v_bid AND kind = 'worktree_binding' AND produced_by = v_eid) THEN
    RAISE EXCEPTION 'v13: worktree binding identity';
  END IF;
  PERFORM v13_latch_fire(p_sid, 'worktree', jsonb_build_object(
    'schema_version', 1,
    'binding_artifact_id', v_req->'params'->>'binding_artifact_id',
    'state', 'prepared'));
END
$fn$;

CREATE OR REPLACE FUNCTION v13_cancel(p_sid uuid) RETURNS text
LANGUAGE plpgsql VOLATILE AS $fn$
DECLARE
  r record;
  v_st text;
  v_extra int;
BEGIN
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
$fn$;


CREATE OR REPLACE FUNCTION public.v13_latch_digest(p_sid uuid)
 RETURNS text
 LANGUAGE sql
 STABLE
AS $function$
  SELECT coalesce(encode(digest(
    (SELECT jsonb_agg(jsonb_build_object('name', name, 'value', value) ORDER BY name)
       FROM latches
      WHERE session_id = p_sid
        AND NOT v13_latch_identity_excluded(name))::text, 'sha256'), 'hex'),
    '-none-')
$function$;

CREATE OR REPLACE FUNCTION public.v13_claim(p_worker text, p_lease_ms integer DEFAULT 60000)
 RETURNS jsonb
 LANGUAGE sql
AS $function$
  UPDATE effects e SET status='claimed', attempt_no=attempt_no+1,
         fence=fence+1, lease_owner=p_worker,
         lease_until=clock_timestamp()
                     + make_interval(secs => p_lease_ms/1000.0)
                     -- make_interval 无 ms 命名参(turn 3,#16):毫秒换算秒
  WHERE effect_id = (
    SELECT effect_id FROM effects
     WHERE status='ready'
       AND v13_attempt_ok(kind, attempt_no)  -- cap belt(turn 8,#55+turn 9,#58):
                                             -- claim 是 attempt_no 唯一递增点
                                             -- (claim 次数单一语义;requeue
                                             -- 回收只推 fence 不动 attempt)。
                                             -- ready 行按构造恒 attempt<cap
                                             -- (enqueue 创建/重挂与 requeue
                                             -- (a1) 均已过同一判定),claim 后
                                             -- ≤cap;死在第 cap 次 claim 上的
                                             -- 行由 requeue (a1') 兜底转终态
                                             -- ——「ready-但-永不可领」结构性
                                             -- 不可达(策略翻新降 cap 的存量
                                             -- 行为=运维事故面,README 翻新纪律)
       AND (op_seq IS NULL OR op_seq = (
            SELECT min(op_seq) FROM effects
             WHERE session_id=e.session_id AND mutation_scope=e.mutation_scope
               AND status <> 'succeeded'))
       AND NOT (
         v13_requires_worktree(tool_name)
         AND NOT EXISTS (
           SELECT 1 FROM latches l
            WHERE l.session_id = e.session_id AND l.name = 'worktree'))
     ORDER BY created_at
     FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING jsonb_build_object('effect_id', effect_id, 'attempt_no', attempt_no,
                               'fence', fence, 'kind', kind, 'request', request);
$function$;

CREATE OR REPLACE FUNCTION public.v13_complete(p_effect uuid, p_attempt integer, p_fence bigint, p_status text, p_result jsonb DEFAULT NULL::jsonb)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_sid uuid; v_row effects; v_outcome text; v_err jsonb; v_human jsonb;
  v_resp boolean := false; v_ans boolean := false; v_skip boolean := false;
  v_n int := 0; k text; v_t text; v_calls jsonb; v_tier text;
BEGIN
  IF p_status NOT IN ('succeeded', 'failed', 'unknown', 'cancelled') THEN
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

CREATE OR REPLACE FUNCTION public.v13_fork(p_parent uuid, p_cutoff bigint, p_kind text, p_overrides jsonb DEFAULT NULL::jsonb)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pgcrypto'
AS $function$
DECLARE v_parent sessions%ROWTYPE; v_child uuid; v_art uuid; v_man jsonb;
        v_prior uuid; v_child_ident text; v_art_ident text; v_gen jsonb;
BEGIN
  IF (p_kind IN ('exact_replay','recompute','fresh_fork')) IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: fork kind must be exact_replay|recompute|fresh_fork'
      USING ERRCODE = 'V3008';
  END IF;
  IF p_overrides IS NOT NULL AND p_kind IS DISTINCT FROM 'fresh_fork' THEN
    -- validate-spawn 面 1:身份声称类 spawn 携 overrides=「clamp 却声称复用」(ch14.3)
    RAISE EXCEPTION 'v13: spawn overrides require fresh_fork (kind=%)', p_kind
      USING ERRCODE = 'V3008';
  END IF;
  SELECT * INTO v_parent FROM sessions WHERE session_id = p_parent FOR UPDATE;
  IF v_parent.session_id IS NULL THEN
    RAISE EXCEPTION 'v13: fork parent % not found', p_parent USING ERRCODE = 'V3008';
  END IF;
  IF p_cutoff IS NULL OR p_cutoff < 0 OR p_cutoff >= v_parent.next_seq THEN
    RAISE EXCEPTION 'v13: fork cutoff % out of bounds [0,%]',
      p_cutoff, v_parent.next_seq - 1 USING ERRCODE = 'V3008';
  END IF;

  -- 继承 artifact 链回走:最新 required_revision.sem ≤ cutoff 者(fresh 跳过)
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    v_art := v_parent.context_active_artifact;
    WHILE v_art IS NOT NULL LOOP
      SELECT inline INTO v_man FROM artifacts WHERE artifact_id = v_art;
      IF v_man IS NULL THEN
        RAISE EXCEPTION 'v13: artifact chain broken at %', v_art
          USING ERRCODE = 'V3008';                    -- 数据缺损响亮
      END IF;
      EXIT WHEN (v_man->'required_revision'->>'sem')::bigint <= p_cutoff;
      v_prior := NULLIF(v_man->'replay'->>'prior_artifact_id', '')::uuid;
      v_art := v_prior;
    END LOOP;
    IF v_art IS NULL THEN
      RAISE EXCEPTION 'v13: no context artifact covers cutoff % (align to a settle point)',
        p_cutoff USING ERRCODE = 'V3008';
    END IF;
    v_art_ident := v_man->>'prefix_identity';         -- 声称锚=artifact 冻结身份
  END IF;

  -- 子行(parent 两列+spawn_kind+route_policy 继承)
  INSERT INTO sessions (status, route_policy_name, route_policy_version,
                        parent_session_id, parent_cutoff_seq, spawn_kind)
  VALUES (v_parent.status, v_parent.route_policy_name, v_parent.route_policy_version,
          p_parent, p_cutoff, p_kind)
  RETURNING session_id INTO v_child;

  -- latch 复制(非 fresh 全量,fired_at 保真;fresh 零复制+overrides 落自己的
  -- generation latch;父此刻生效值为基底)
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    INSERT INTO latches (session_id, name, value, fired_at)
    SELECT v_child, name, value, fired_at
      FROM latches
     WHERE session_id = p_parent
       AND NOT v13_latch_identity_excluded(name);
  ELSE
    v_gen := v13_generation_effective(p_parent);
    IF p_overrides IS NOT NULL THEN
      IF jsonb_typeof(p_overrides) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'v13: overrides must be an object' USING ERRCODE = 'V3008';
      END IF;
      v_gen := v_gen || p_overrides;                  -- clamp/换档的关系化形态(进身份值)
    END IF;
    -- [机械自检#3] fresh 分支 generation_version belt 显式 RAISE 最终化
    IF NOT (v_gen ? 'generation_version') THEN
      RAISE EXCEPTION 'v13: generation effective value missing generation_version'
        USING ERRCODE = 'V3008';
    END IF;
    INSERT INTO latches (session_id, name, value)
    VALUES (v_child, 'generation', v_gen);
  END IF;

  -- validate-spawn 面 2:身份声称类——子此刻身份 vs artifact 冻结身份
  v_child_ident := v13_prefix_identity(v_child);
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    IF v_child_ident IS DISTINCT FROM v_art_ident THEN
      RAISE EXCEPTION
        'v13: validate-spawn rejected: identity drift for % fork (child=%, artifact=%)',
        p_kind, v_child_ident, v_art_ident USING ERRCODE = 'V3008';
    END IF;
  END IF;
  -- (L4 P1-2:fresh 分支无身份检查——fresh 必携 generation latch(fork SQL 无条件落);
  --   无 overrides 且 cutoff 对齐 settle 点时子身份可与父 artifact 身份相等,
  --   同身份=同前缀缓存命中,无害;设计只要求拒「破坏缓存身份的 fork」。)

  -- 继承指针+forked 事件(payload=身份对账的行级审计面)
  IF p_kind IS DISTINCT FROM 'fresh_fork' THEN
    UPDATE sessions
       SET context_active_artifact = v_art,
           context_active_revision = v_man->'required_revision'
     WHERE session_id = v_child;
  END IF;
  PERFORM v13_append_event(v_child, gen_random_uuid(), 'forked',
    jsonb_build_object('kind', p_kind, 'parent_session_id', p_parent,
      'cutoff', p_cutoff, 'artifact_id', v_art,
      'parent_identity', v_art_ident, 'child_identity', v_child_ident,
      'overrides', p_overrides), NULL);
  RETURN v_child;
END $function$;

REVOKE ALL ON FUNCTION
  v13_cancel_pending(uuid),
  v13_interruptible(text),
  v13_requires_worktree(text),
  v13_latch_identity_excluded(text),
  v13_worktree_request_ok(text, jsonb),
  v13_worktree_inline_ok(jsonb),
  v13_worktree_latch_ok(jsonb),
  v13_worktree_latch_guard(),
  v13_bind_worktree_from_prepare(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_cancel_pending(uuid),
  v13_interruptible(text),
  v13_requires_worktree(text),
  v13_latch_identity_excluded(text),
  v13_worktree_request_ok(text, jsonb),
  v13_worktree_inline_ok(jsonb),
  v13_worktree_latch_ok(jsonb),
  v13_worktree_latch_guard(),
  v13_bind_worktree_from_prepare(uuid)
TO v13_route;
GRANT EXECUTE ON FUNCTION
  v13_cancel_pending(uuid),
  v13_interruptible(text),
  v13_requires_worktree(text)
TO v13_worker;
GRANT EXECUTE ON FUNCTION
  v13_latch_identity_excluded(text),
  v13_worktree_latch_ok(jsonb),
  v13_worktree_latch_guard(),
  v13_interruptible(text),
  v13_requires_worktree(text)
TO v13_spawn_owner;

INSERT INTO tools (name, description, kind, handler, param_spec, enabled) VALUES
  ('worktree_prepare', 'Prepare a worktree binding. Filesystem stays outside the transaction.',
   'tool', 'worker:worktree_prepare', '{}'::jsonb, true),
  ('worktree_merge', 'Merge a prepared worktree binding. Filesystem stays outside the transaction.',
   'tool', 'worker:worktree_merge', '{}'::jsonb, true),
  ('worktree_release', 'Release a prepared worktree binding. Filesystem stays outside the transaction.',
   'tool', 'worker:worktree_release', '{}'::jsonb, true);

COMMIT;
