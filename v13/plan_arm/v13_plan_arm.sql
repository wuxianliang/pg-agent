CREATE FUNCTION public.v13_selected_todo(p_session uuid)
RETURNS TABLE (
  todo_id uuid,
  todo_text text,
  text_hash text,
  task_class text,
  status text,
  due text,
  dispatch text,
  effect_id text,
  child_session_id text
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_cur jsonb;
  v_row record;
  v_est text;
  v_cst text;
  v_excluded boolean;
  v_dispatch text;
BEGIN
  v_root := public.v13_plan_map_root(p_session);
  v_cur := public.v13_plan_current(p_session);
  IF v_cur IS NULL THEN
    RETURN;
  END IF;
  FOR v_row IN
    SELECT f.todo_id, f.todo_text, f.text_hash, f.task_class, f.status, f.due,
           f.effect_id, f.child_session_id, f.quarantine
      FROM pg_catalog.jsonb_array_elements(v_cur->'canonical'->'todos') elem
      JOIN public.v13_plan_todo_fold(v_root) f
        ON f.todo_id = (elem->>'todo_id')::uuid
     ORDER BY (v_cur->>'seq')::bigint, f.todo_id
  LOOP
    v_excluded := false;
    v_est := NULL;
    v_cst := NULL;
    IF v_row.effect_id IS NOT NULL THEN
      SELECT e.status INTO v_est
        FROM public.effects e
       WHERE e.effect_id = v_row.effect_id::uuid;
      IF v_est IS NULL OR v_est NOT IN ('succeeded', 'failed', 'cancelled') THEN
        v_excluded := true;
      ELSIF v_row.status = 'runnable' THEN
        v_excluded := true;
      ELSIF v_est = 'succeeded' AND v_row.status NOT IN ('done', 'waiting') THEN
        v_excluded := true;
      ELSIF v_est IN ('failed', 'cancelled')
            AND NOT (
              v_row.quarantine IS NOT NULL
              AND v_row.quarantine->'cleared' IS DISTINCT FROM 'true'::jsonb
              AND v_row.quarantine->>'effect_id' = v_row.effect_id) THEN
        v_excluded := true;
      END IF;
    END IF;
    IF v_row.child_session_id IS NOT NULL THEN
      SELECT s.status INTO v_cst
        FROM public.sessions s
       WHERE s.session_id = v_row.child_session_id::uuid;
      IF v_cst IS NULL OR v_cst NOT IN ('completed', 'failed', 'cancelled') THEN
        v_excluded := true;
      ELSIF v_cst IN ('completed', 'failed', 'cancelled')
            AND v_row.status NOT IN ('done', 'waiting') THEN
        v_excluded := true;
      END IF;
    END IF;
    IF v_row.quarantine IS NOT NULL
       AND v_row.quarantine->'cleared' IS DISTINCT FROM 'true'::jsonb THEN
      v_excluded := true;
    END IF;
    IF EXISTS (
      SELECT 1
        FROM public.v13_plan_link_edges(v_root) e
        JOIN public.v13_plan_todo_fold(v_root) c ON c.todo_id = e.carrier
       WHERE e.target = v_row.todo_id
         AND c.status IS DISTINCT FROM 'done') THEN
      v_excluded := true;
    END IF;
    IF v_excluded THEN
      CONTINUE;
    END IF;
    IF v_row.task_class IN ('advancement_task', 'continuous_monitor')
       AND v_row.status = 'runnable' THEN
      v_dispatch := 'provider';
    ELSIF v_row.task_class IN ('user_gate', 'user_action', 'blocker')
          AND v_row.status IN ('pending', 'runnable', 'blocked') THEN
      v_dispatch := 'operator';
    ELSE
      CONTINUE;
    END IF;
    todo_id := v_row.todo_id;
    todo_text := v_row.todo_text;
    text_hash := v_row.text_hash;
    task_class := v_row.task_class;
    status := v_row.status;
    due := v_row.due;
    dispatch := v_dispatch;
    effect_id := v_row.effect_id;
    child_session_id := v_row.child_session_id;
    RETURN NEXT;
    RETURN;
  END LOOP;
  RETURN;
END
$fn$;

CREATE FUNCTION public.v13_plan_gate(p_session uuid) RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
  SELECT public.v13_plan_current(p_session) IS NOT NULL
     AND EXISTS (SELECT 1 FROM public.v13_selected_todo(p_session));
$$;

CREATE FUNCTION public.v13_plan_advance_prefix(p_sid uuid) RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_stopped boolean;
  v_ptr_n int;
  v_read_n int;
  v_req jsonb;
  v_effect uuid;
  v_child uuid;
  v_todo text;
  v_read uuid;
  v_fold record;
  v_apply uuid;
  v_can jsonb;
  v_row record;
  v_harness_archived boolean := false;
  v_sel record;
BEGIN
  v_root := public.v13_plan_map_root(p_sid);
  v_stopped := public.v13_goal_lifecycle(v_root) = 'stopped';
  IF v_root IS DISTINCT FROM p_sid THEN
    IF public.v13_should_run(p_sid) THEN
      SELECT count(*) INTO v_ptr_n
        FROM public.events
       WHERE session_id = p_sid AND type = 'workflow/pointer';
      SELECT count(*) INTO v_read_n
        FROM public.effects
       WHERE session_id = p_sid AND tool_name = 'read_file_py';
      IF v_ptr_n = 1 AND v_read_n = 0 THEN
        v_req := pg_catalog.jsonb_build_object(
          'schema_version', 1, 'tool', 'read_file_py');
        v_effect := public.v13_enqueue_effect(p_sid, 'tool', v_req, 'read_file_py');
        PERFORM public.v13_send_work(v_effect);
        UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid;
        RETURN 'waiting';
      END IF;
    END IF;
    RETURN NULL;
  END IF;
  IF v_stopped THEN
    RETURN NULL;
  END IF;
  SELECT e.session_id, e.payload->>'todo_id', f.effect_id
    INTO v_child, v_todo, v_read
    FROM public.events e
    JOIN public.sessions s ON s.session_id = e.session_id
    JOIN public.effects f
      ON f.session_id = e.session_id
     AND f.tool_name = 'read_file_py'
     AND f.status = 'succeeded'
     AND f.result IS NOT NULL
    JOIN public.v13_plan_todo_fold(v_root) g
      ON g.todo_id = (e.payload->>'todo_id')::uuid
     AND g.status = 'runnable'
     AND g.task_class = 'advancement_task'
   WHERE e.type = 'workflow/pointer'
     AND s.parent_session_id = v_root
   ORDER BY e.seq
   LIMIT 1;
  IF v_child IS NOT NULL THEN
    SELECT * INTO v_fold
      FROM public.v13_plan_todo_fold(v_root) g
     WHERE g.todo_id = v_todo::uuid;
    IF FOUND AND v_fold.status = 'runnable'
       AND v_fold.task_class = 'advancement_task' THEN
      v_apply := public.v13_plan_apply_id(
        'archive:' || v_root::text || ':' || v_todo || ':' || v_read::text || ':done:');
      v_can := pg_catalog.jsonb_build_object(
        'schema_version', 1,
        'call_kind', 'todo_delta',
        'verb', 'update',
        'todo_id', v_todo,
        'status_from', 'runnable',
        'status_to', 'done',
        'binding', 'null'::jsonb,
        'due', 'null'::jsonb,
        'quarantine', 'null'::jsonb,
        'text_hash', v_fold.text_hash,
        'link', 'null'::jsonb);
      PERFORM public.v13_plan_writer(
        NULL::uuid, v_root, v_apply, 'todo_delta', v_can, NULL::timestamptz);
      RETURN 'waiting';
    END IF;
  END IF;
  v_harness_archived := false;
  FOR v_row IN
    SELECT e.effect_id,
           e.status AS effect_status,
           e.kind AS effect_kind,
           e.tool_name,
           e.result->>'result_kind' AS result_kind,
           f.todo_id,
           f.status AS todo_status,
           f.task_class,
           f.text_hash,
           f.quarantine
      FROM public.v13_plan_todo_fold(v_root) f
      JOIN public.effects e ON e.effect_id = f.effect_id::uuid
     WHERE f.effect_id IS NOT NULL
  LOOP
    IF v_row.task_class = 'advancement_task'
       AND v_row.todo_status = 'runnable'
       AND v_row.effect_status = 'succeeded'
       AND v_row.result_kind IN ('progress', 'finish')
       AND v_row.effect_kind = 'tool'
       AND v_row.tool_name = 'harness_turn' THEN
      v_apply := public.v13_plan_apply_id(
        'archive:' || v_root::text || ':' || v_row.todo_id::text || ':'
        || v_row.effect_id::text || ':done:');
      v_can := pg_catalog.jsonb_build_object(
        'schema_version', 1,
        'call_kind', 'todo_delta',
        'verb', 'update',
        'todo_id', v_row.todo_id::text,
        'status_from', 'runnable',
        'status_to', 'done',
        'binding', 'null'::jsonb,
        'due', 'null'::jsonb,
        'quarantine', 'null'::jsonb,
        'text_hash', v_row.text_hash,
        'link', 'null'::jsonb);
      PERFORM public.v13_plan_writer(
        NULL::uuid, v_root, v_apply, 'todo_delta', v_can, NULL::timestamptz);
      v_harness_archived := true;
    ELSIF v_row.effect_status IN ('failed', 'cancelled')
          AND v_row.todo_status NOT IN ('done', 'dropped')
          AND v_row.todo_status IN ('runnable', 'pending', 'blocked')
          AND NOT (
            v_row.quarantine IS NOT NULL
            AND v_row.quarantine->'cleared' IS DISTINCT FROM 'true'::jsonb
            AND v_row.quarantine->>'effect_id' = v_row.effect_id::text) THEN
      v_apply := public.v13_plan_apply_id(
        'quarantine:' || v_root::text || ':' || v_row.todo_id::text || ':'
        || v_row.effect_id::text);
      v_can := pg_catalog.jsonb_build_object(
        'schema_version', 1,
        'call_kind', 'todo_delta',
        'verb', 'update',
        'todo_id', v_row.todo_id::text,
        'status_from', v_row.todo_status,
        'status_to', CASE
          WHEN v_row.todo_status = 'runnable' THEN 'blocked'
          ELSE v_row.todo_status
        END,
        'binding', 'null'::jsonb,
        'due', 'null'::jsonb,
        'quarantine', pg_catalog.jsonb_build_object(
          'cleared', false, 'effect_id', v_row.effect_id::text),
        'text_hash', v_row.text_hash,
        'link', 'null'::jsonb);
      PERFORM public.v13_plan_writer(
        NULL::uuid, v_root, v_apply, 'todo_delta', v_can, NULL::timestamptz);
    END IF;
  END LOOP;
  IF v_harness_archived THEN
    RETURN NULL;
  END IF;
  IF EXISTS (
    SELECT 1
      FROM public.v13_plan_todo_fold(v_root) f
      JOIN public.effects e ON e.effect_id = f.effect_id::uuid
     WHERE f.effect_id IS NOT NULL
       AND e.status NOT IN ('succeeded', 'failed', 'cancelled')) THEN
    RETURN 'waiting';
  END IF;
  IF NOT public.v13_plan_gate(v_root) OR NOT public.v13_should_run(p_sid) THEN
    RETURN NULL;
  END IF;
  SELECT * INTO v_sel FROM public.v13_selected_todo(v_root);
  IF NOT FOUND OR v_sel.dispatch = 'none' THEN
    RETURN NULL;
  END IF;
  IF v_sel.dispatch = 'provider' THEN
    v_effect := public.v13_enqueue_effect(
      p_sid, 'llm',
      pg_catalog.jsonb_build_object(
        'route', pg_catalog.jsonb_build_object('action', 'llm', 'reason', 'selected_todo'),
        'todo_id', v_sel.todo_id::text));
  ELSIF v_sel.dispatch = 'operator' THEN
    v_effect := public.v13_enqueue_effect(
      p_sid, 'human',
      pg_catalog.jsonb_build_object('reason', 'selected_todo', 'todo_id', v_sel.todo_id::text));
  ELSE
    RETURN NULL;
  END IF;
  v_apply := public.v13_plan_apply_id(
    'bind:' || v_root::text || ':' || v_sel.todo_id::text || ':' || v_effect::text);
  v_can := pg_catalog.jsonb_build_object(
    'schema_version', 1,
    'call_kind', 'todo_delta',
    'verb', 'update',
    'todo_id', v_sel.todo_id::text,
    'status_from', v_sel.status,
    'status_to', v_sel.status,
    'binding', pg_catalog.jsonb_build_object(
      'child_session_id', NULL, 'effect_id', v_effect::text),
    'due', 'null'::jsonb,
    'quarantine', 'null'::jsonb,
    'text_hash', v_sel.text_hash,
    'link', 'null'::jsonb);
  PERFORM public.v13_plan_writer(
    NULL::uuid, v_root, v_apply, 'todo_delta', v_can, NULL::timestamptz);
  PERFORM public.v13_send_work(v_effect);
  UPDATE public.sessions SET status = 'waiting' WHERE session_id = p_sid;
  RETURN 'waiting';
END
$fn$;

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
  v_plan_word text;
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
  v_plan_word := public.v13_plan_advance_prefix(p_sid);
  IF v_plan_word IS NOT NULL THEN
    RETURN v_plan_word;
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
