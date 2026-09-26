-- v13 seam (stage 21, Phase A). D11 cap exemption + D12 worktree/released.
-- closeout / advance / state_hash are not replaced (preflight).
BEGIN;

DO $install$
DECLARE
  r record;
  v_ok boolean;
BEGIN
  FOR r IN
    SELECT e.session_id, e.payload->>'binding_artifact_id' AS binding
      FROM events e
     WHERE e.type = 'worktree/released'
     GROUP BY e.session_id, e.payload->>'binding_artifact_id'
    HAVING count(*) > 1
  LOOP
    RAISE EXCEPTION
      'v13: seam install worktree/released session % binding % source %',
      r.session_id, r.binding, NULL::uuid;
  END LOOP;
  FOR r IN
    SELECT e.session_id,
           e.payload->>'binding_artifact_id' AS binding,
           e.source_effect_id
      FROM events e
     WHERE e.type = 'worktree/released'
  LOOP
    SELECT
      v13_json_keys(e.payload) = ARRAY['binding_artifact_id', 'schema_version']
      AND jsonb_typeof(e.payload->'schema_version') = 'number'
      AND v13_json_int_ok(e.payload->'schema_version', 1)
      AND (e.payload->'schema_version')::text::numeric = 1
      AND v13_canonical_uuid(e.payload->>'binding_artifact_id')
      AND e.source_effect_id IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM effects x
         WHERE x.effect_id = e.source_effect_id
           AND x.session_id = e.session_id
           AND x.kind = 'tool'
           AND x.tool_name = 'worktree_release'
           AND x.status = 'succeeded'
           AND x.request->'params'->>'binding_artifact_id'
               = e.payload->>'binding_artifact_id')
      AND EXISTS (
        SELECT 1 FROM latches l
         WHERE l.session_id = e.session_id
           AND l.name = 'worktree'
           AND l.value->>'binding_artifact_id'
               = e.payload->>'binding_artifact_id')
      INTO v_ok
      FROM events e
     WHERE e.session_id = r.session_id
       AND e.type = 'worktree/released'
       AND e.source_effect_id IS NOT DISTINCT FROM r.source_effect_id
       AND e.payload->>'binding_artifact_id' IS NOT DISTINCT FROM r.binding;
    IF NOT coalesce(v_ok, false) THEN
      RAISE EXCEPTION
        'v13: seam install worktree/released session % binding % source %',
        r.session_id, r.binding, r.source_effect_id;
    END IF;
  END LOOP;

  FOR r IN
    SELECT l.session_id, l.value->>'binding_artifact_id' AS binding
      FROM latches l
     WHERE l.name = 'worktree'
       AND l.value->>'state' = 'released'
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM events e
      JOIN effects x ON x.effect_id = e.source_effect_id
      JOIN latches l ON l.session_id = e.session_id AND l.name = 'worktree'
     WHERE e.session_id = r.session_id
       AND e.type = 'worktree/released'
       AND e.payload->>'binding_artifact_id' = r.binding
       AND v13_json_keys(e.payload) = ARRAY['binding_artifact_id', 'schema_version']
       AND jsonb_typeof(e.payload->'schema_version') = 'number'
       AND v13_json_int_ok(e.payload->'schema_version', 1)
       AND (e.payload->'schema_version')::text::numeric = 1
       AND v13_canonical_uuid(e.payload->>'binding_artifact_id')
       AND x.session_id = e.session_id
       AND x.kind = 'tool'
       AND x.tool_name = 'worktree_release'
       AND x.status = 'succeeded'
       AND x.request->'params'->>'binding_artifact_id' = e.payload->>'binding_artifact_id'
       AND l.value->>'binding_artifact_id' = e.payload->>'binding_artifact_id') THEN
      RAISE EXCEPTION
        'v13: seam install released latch session % binding %',
        r.session_id, r.binding;
    END IF;
  END LOOP;
END
$install$;

CREATE FUNCTION v13_cap_answer_anchor(p_sid uuid, p_effect uuid)
RETURNS TABLE(anchor_seq bigint, cap_class text)
LANGUAGE sql
STABLE
AS $fn$
  WITH pred AS (
    SELECT e.origin_user_seq,
           (SELECT max(ev.seq) FROM events ev
             WHERE ev.session_id = e.session_id
               AND ev.source_effect_id = e.effect_id
               AND ev.type = 'effect_done') AS done_seq
      FROM effects e
     WHERE e.effect_id = p_effect
       AND e.session_id = p_sid
  ),
  hits AS (
    SELECT ev.seq AS anchor_seq,
           CASE h.request->>'interaction_kind'
             WHEN 'repair_cap' THEN 'repair'
             WHEN 'replan_cap' THEN 'replan'
             WHEN 'material_cap' THEN 'material'
           END AS cap_class
      FROM effects h
      JOIN events ev
        ON ev.session_id = h.session_id
       AND ev.source_effect_id = h.effect_id
       AND ev.type = 'human/responded'
      JOIN pred p ON true
     WHERE h.session_id = p_sid
       AND h.kind = 'human'
       AND h.status = 'succeeded'
       AND h.origin_user_seq = p.origin_user_seq
       AND h.request->>'interaction_kind' IN ('material_cap', 'repair_cap', 'replan_cap')
       AND p.done_seq IS NOT NULL
       AND ev.seq > p.done_seq
    UNION ALL
    SELECT (SELECT max(ev.seq) FROM events ev
             WHERE ev.session_id = h.session_id
               AND ev.source_effect_id = h.effect_id
               AND ev.type = 'effect_done') AS anchor_seq,
           CASE h.request->>'reason'
             WHEN 'repair_cap' THEN 'repair'
             WHEN 'replan_cap' THEN 'replan'
           END AS cap_class
      FROM effects h
      JOIN pred p ON true
     WHERE h.session_id = p_sid
       AND h.kind = 'human'
       AND h.status = 'succeeded'
       AND h.origin_user_seq = p.origin_user_seq
       AND h.request->>'reason' IN ('repair_cap', 'replan_cap')
       AND NOT (h.request ? 'interaction_kind')
       AND p.done_seq IS NOT NULL
       AND (SELECT max(ev.seq) FROM events ev
             WHERE ev.session_id = h.session_id
               AND ev.source_effect_id = h.effect_id
               AND ev.type = 'effect_done') > p.done_seq
  ),
  ranked AS (
    SELECT cap_class, anchor_seq,
           count(*) OVER (PARTITION BY cap_class, anchor_seq) AS tie_n,
           min(anchor_seq) OVER (PARTITION BY cap_class) AS min_seq
      FROM hits
     WHERE anchor_seq IS NOT NULL
       AND cap_class IS NOT NULL
  )
  SELECT anchor_seq, cap_class
    FROM ranked
   WHERE anchor_seq = min_seq
     AND tie_n = 1;
$fn$;

CREATE OR REPLACE FUNCTION public.v13_cap_human_answered(p_sid uuid, p_pred uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE
 SET search_path TO 'pg_catalog', 'public'
AS $function$
  SELECT EXISTS (SELECT 1 FROM v13_cap_answer_anchor(p_sid, p_pred));
$function$;

CREATE FUNCTION v13_tail_gap_cap_exempt(p_sid uuid, p_effect uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $fn$
  SELECT coalesce((
    SELECT e.result->>'result_kind' = 'progress'
       AND EXISTS (
         SELECT 1
           FROM v13_cap_answer_anchor(p_sid, p_effect) a
          WHERE a.cap_class IN ('repair', 'replan')
            AND (
              (a.cap_class = 'repair' AND EXISTS (
                 SELECT 1 FROM events sig
                  WHERE sig.session_id = p_sid
                    AND sig.source_effect_id = e.effect_id
                    AND sig.type = 'repair/required'))
              OR (a.cap_class = 'replan' AND EXISTS (
                 SELECT 1 FROM events sig
                  WHERE sig.session_id = p_sid
                    AND sig.source_effect_id = e.effect_id
                    AND sig.type = 'replan/required')))
            AND NOT EXISTS (
              SELECT 1 FROM effects o
               WHERE o.session_id = p_sid
                 AND o.origin_user_seq = e.origin_user_seq
                 AND o.effect_id IS DISTINCT FROM e.effect_id
                 AND o.kind = 'tool'
                 AND v13_is_harness_tool(o.tool_name, o.kind)
                 AND o.status = 'succeeded'
                 AND (SELECT max(ev.seq) FROM events ev
                       WHERE ev.session_id = o.session_id
                         AND ev.source_effect_id = o.effect_id
                         AND ev.type = 'effect_done')
                     > (SELECT max(ev.seq) FROM events ev
                         WHERE ev.session_id = e.session_id
                           AND ev.source_effect_id = e.effect_id
                           AND ev.type = 'effect_done')
                 AND (SELECT max(ev.seq) FROM events ev
                       WHERE ev.session_id = o.session_id
                         AND ev.source_effect_id = o.effect_id
                         AND ev.type = 'effect_done')
                     < a.anchor_seq)
            AND EXISTS (
              SELECT 1 FROM effects n
               WHERE n.session_id = p_sid
                 AND n.origin_user_seq = e.origin_user_seq
                 AND n.kind = 'tool'
                 AND v13_is_harness_tool(n.tool_name, n.kind)
                 AND v13_json_int_ok(n.request->'continuation_index', 2147483647)
                 AND (n.request->>'continuation_index')::int = 0
                 AND n.request->'logical_turn_id'
                     IS DISTINCT FROM e.request->'logical_turn_id'
                 AND EXISTS (
                   SELECT 1 FROM events ev
                    WHERE ev.session_id = n.session_id
                      AND ev.source_effect_id = n.effect_id
                      AND ev.seq > a.anchor_seq)))
      FROM effects e
     WHERE e.effect_id = p_effect
       AND e.session_id = p_sid
  ), false);
$fn$;

CREATE OR REPLACE FUNCTION public.v13_harness_tail_gap(p_sid uuid, p_keep uuid)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF EXISTS (
    SELECT 1 FROM effects e
     WHERE e.session_id = p_sid
       AND e.kind = 'tool'
       AND v13_is_harness_tool(e.tool_name, e.kind)
       AND e.origin_user_seq = v13_last_user_seq(p_sid)
       AND e.status = 'succeeded'
       AND e.effect_id IS DISTINCT FROM p_keep
       AND (
         (e.result->>'result_kind' = 'progress' AND EXISTS (
            SELECT 1 FROM events ev
             WHERE ev.source_effect_id = e.effect_id
               AND ev.type IN ('repair/required', 'replan/required')))
         OR e.result->>'result_kind' = 'wait')
       AND NOT EXISTS (
         SELECT 1 FROM effects n
          WHERE n.session_id = e.session_id
            AND n.kind = 'tool'
            AND v13_is_harness_tool(n.tool_name, n.kind)
            AND n.request->>'logical_turn_id' = e.request->>'logical_turn_id'
            AND v13_json_int_ok(n.request->'continuation_index', 2147483647)
            AND v13_json_int_ok(e.request->'continuation_index', 2147483647)
            AND (n.request->>'continuation_index')::int
                = (e.request->>'continuation_index')::int + 1)
       AND NOT v13_tail_gap_cap_exempt(p_sid, e.effect_id)) THEN
    RAISE EXCEPTION 'v13: harness tail gap';
  END IF;
END $function$;



CREATE FUNCTION v13_record_worktree_released(p_sid uuid, p_effect uuid)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_row effects;
  v_bind text;
  v_latch text;
BEGIN
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect;
  IF NOT FOUND
     OR v_row.session_id IS DISTINCT FROM p_sid
     OR v_row.kind IS DISTINCT FROM 'tool'
     OR v_row.tool_name IS DISTINCT FROM 'worktree_release'
     OR v_row.status IS DISTINCT FROM 'succeeded' THEN
    RETURN;
  END IF;
  v_bind := v_row.request->'params'->>'binding_artifact_id';
  SELECT value->>'binding_artifact_id' INTO v_latch
    FROM latches
   WHERE session_id = p_sid AND name = 'worktree';
  IF v_latch IS NULL OR v_bind IS DISTINCT FROM v_latch THEN
    RETURN;
  END IF;
  PERFORM 1 FROM latches
   WHERE session_id = p_sid AND name = 'worktree'
   FOR UPDATE;
  IF EXISTS (
    SELECT 1 FROM events
     WHERE session_id = p_sid
       AND type = 'worktree/released'
       AND payload->>'binding_artifact_id' = v_latch) THEN
    RETURN;
  END IF;
  PERFORM v13_append_event(
    p_sid, gen_random_uuid(), 'worktree/released',
    jsonb_build_object('schema_version', 1, 'binding_artifact_id', v_latch),
    p_effect);
END
$fn$;

CREATE UNIQUE INDEX ux_events_worktree_released
  ON events (session_id, (payload->>'binding_artifact_id'))
  WHERE type = 'worktree/released';

CREATE FUNCTION v13_seam_event_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_keys text[];
  v_bind text;
  v_req text;
  v_latch text;
  v_exist uuid;
BEGIN
  v_keys := v13_json_keys(NEW.payload);
  v_bind := NEW.payload->>'binding_artifact_id';
  IF v_keys IS DISTINCT FROM ARRAY['binding_artifact_id', 'schema_version']
     OR jsonb_typeof(NEW.payload->'schema_version') IS DISTINCT FROM 'number'
     OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
     OR (NEW.payload->'schema_version')::text::numeric <> 1
     OR NOT v13_canonical_uuid(v_bind)
     OR NEW.source_effect_id IS NULL THEN
    RAISE EXCEPTION 'v13: worktree released';
  END IF;
  SELECT e.request->'params'->>'binding_artifact_id'
    INTO v_req
    FROM effects e
   WHERE e.effect_id = NEW.source_effect_id
     AND e.session_id = NEW.session_id
     AND e.kind = 'tool'
     AND e.tool_name = 'worktree_release'
     AND e.status = 'succeeded';
  IF NOT FOUND OR v_req IS DISTINCT FROM v_bind THEN
    RAISE EXCEPTION 'v13: worktree released';
  END IF;
  SELECT value->>'binding_artifact_id' INTO v_latch
    FROM latches
   WHERE session_id = NEW.session_id AND name = 'worktree';
  IF v_latch IS DISTINCT FROM v_bind THEN
    RAISE EXCEPTION 'v13: worktree released';
  END IF;
  SELECT source_effect_id INTO v_exist
    FROM events
   WHERE session_id = NEW.session_id
     AND type = 'worktree/released'
     AND payload->>'binding_artifact_id' = v_bind
   LIMIT 1;
  IF v_exist IS NOT NULL AND v_exist IS DISTINCT FROM NEW.source_effect_id THEN
    RAISE EXCEPTION 'v13: worktree released';
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_v13_seam_event_guard
  BEFORE INSERT ON events
  FOR EACH ROW
  WHEN (NEW.type = 'worktree/released')
  EXECUTE FUNCTION v13_seam_event_guard();

CREATE FUNCTION v13_worktree_state(p_sid uuid) RETURNS text
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_bind text;
  v_n int;
BEGIN
  SELECT value->>'binding_artifact_id' INTO v_bind
    FROM latches
   WHERE session_id = p_sid AND name = 'worktree';
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  SELECT count(*) INTO v_n
    FROM events
   WHERE session_id = p_sid
     AND type = 'worktree/released'
     AND payload->>'binding_artifact_id' = v_bind;
  IF v_n = 0 THEN
    RETURN 'prepared';
  ELSIF v_n = 1 THEN
    RETURN 'released';
  END IF;
  RAISE EXCEPTION 'v13: worktree state ambiguous';
END
$fn$;

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
  IF v_outcome = 'succeeded'
     AND v_row.kind = 'tool'
     AND v_row.tool_name = 'worktree_release' THEN
    PERFORM v13_record_worktree_released(v_sid, p_effect);
  END IF;
  RETURN 'accepted';
END $function$;


CREATE OR REPLACE FUNCTION public.v13_resolve_unknown(p_effect uuid, p_resolution text, p_evidence jsonb)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_sid uuid; v_row effects; v_hash text; v_obs text; v_keys text[]; v_st text;
BEGIN
  IF p_resolution NOT IN ('confirmed', 'not_happened', 'rolled_back') THEN
    RAISE EXCEPTION 'v13: resolve resolution %', p_resolution;
  END IF;
  IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN
    RAISE EXCEPTION 'v13: resolve evidence';
  END IF;
  v_keys := v13_json_keys(p_evidence);
  v_obs := p_evidence->>'observation';
  IF p_resolution = 'confirmed' THEN
    IF v_keys IS DISTINCT FROM ARRAY['observation', 'payload_hash']
       OR v_obs IS DISTINCT FROM 'committed' THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
  ELSIF p_resolution = 'not_happened' THEN
    IF v_keys IS DISTINCT FROM ARRAY['observation'] OR v_obs IS DISTINCT FROM 'absent' THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
  ELSE
    IF v_keys IS DISTINCT FROM ARRAY['compensation_ref', 'observation']
       OR v_obs IS DISTINCT FROM 'rolled_back'
       OR coalesce(p_evidence->>'compensation_ref', '') !~ '^[A-Za-z0-9_./:-]+$'
       OR length(coalesce(p_evidence->>'compensation_ref', '')) NOT BETWEEN 1 AND 256 THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
  END IF;
  SELECT session_id INTO v_sid FROM effects WHERE effect_id = p_effect;
  IF v_sid IS NULL THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  PERFORM 1 FROM sessions WHERE session_id = v_sid FOR UPDATE;
  SELECT * INTO v_row FROM effects WHERE effect_id = p_effect FOR UPDATE;
  IF v_row.status IS DISTINCT FROM 'unknown' THEN
    RAISE EXCEPTION 'v13: resolve unknown required';
  END IF;
  v_hash := encode(digest(p_evidence::text, 'sha256'), 'hex');
  IF p_resolution = 'confirmed' THEN
    IF v_row.result IS NULL
       OR p_evidence->>'payload_hash' IS DISTINCT FROM encode(digest(v_row.result::text, 'sha256'), 'hex') THEN
      RAISE EXCEPTION 'v13: resolve evidence';
    END IF;
    UPDATE effects SET status = 'succeeded', error = NULL WHERE effect_id = p_effect;
    PERFORM v13_record_worktree_released(v_sid, p_effect);
  ELSE
    UPDATE effects SET status = 'failed',
           error = jsonb_build_object('code', 'unknown_resolved',
                                      'resolution', p_resolution,
                                      'evidence_hash', v_hash)
     WHERE effect_id = p_effect;
  END IF;
  PERFORM v13_append_event(v_sid, gen_random_uuid(), 'unknown_resolved',
    jsonb_build_object('schema_version', 1, 'effect_id', p_effect::text,
                       'resolution', p_resolution, 'evidence_hash', v_hash),
    p_effect);
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = v_sid AND status = 'unknown') THEN
    RETURN 'accepted';
  END IF;
  SELECT status INTO v_st FROM sessions WHERE session_id = v_sid;
  IF v_st = 'blocked_unknown' THEN
    IF v13_pending_human(v_sid) THEN
      UPDATE sessions SET status = 'waiting' WHERE session_id = v_sid;
    ELSE
      UPDATE sessions SET status = 'ready' WHERE session_id = v_sid;
    END IF;
  END IF;
  RETURN 'accepted';
END $function$;


REVOKE EXECUTE ON FUNCTION
  v13_cap_answer_anchor(uuid, uuid),
  v13_tail_gap_cap_exempt(uuid, uuid),
  v13_record_worktree_released(uuid, uuid),
  v13_worktree_state(uuid),
  v13_seam_event_guard()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_cap_answer_anchor(uuid, uuid),
  v13_tail_gap_cap_exempt(uuid, uuid),
  v13_worktree_state(uuid)
TO v13_route;
GRANT EXECUTE ON FUNCTION v13_record_worktree_released(uuid, uuid)
  TO v13_route, v13_spawn_owner;
GRANT EXECUTE ON FUNCTION v13_seam_event_guard()
  TO v13_route, v13_spawn_owner;

COMMIT;
