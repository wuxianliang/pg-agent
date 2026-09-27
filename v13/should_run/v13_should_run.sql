-- v13 should_run (stage 26). Projection gate for new effects. No new tables.
BEGIN;

DO $should_run_base$
BEGIN
  IF to_regprocedure('public.v13_should_run(uuid)') IS NOT NULL
     OR to_regprocedure('public.v13_should_run_gate(uuid)') IS NOT NULL
     OR to_regprocedure('public.v13_policy_share()') IS NOT NULL
     OR to_regprocedure('public.v13_sessions_parent_immutable()') IS NOT NULL
     OR EXISTS (
       SELECT 1 FROM pg_trigger WHERE tgname = 'trg_sessions_parent_immutable')
     OR EXISTS (
       SELECT 1 FROM public.v13_policies WHERE name = 'should_run')
     OR NOT EXISTS (
       SELECT 1 FROM public.v13_policies WHERE name = 'triage' AND active) THEN
    RAISE EXCEPTION 'v13: should_run baseline';
  END IF;
  IF position('v13_triage_prework' IN pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)) = 0
     OR position('v13_bind_worktree_from_prepare' IN pg_get_functiondef('public.v13_advance(uuid,jsonb)'::regprocedure)) = 0
     OR position('duty_cycle' IN pg_get_functiondef('public.v13_triage_prework(uuid)'::regprocedure)) = 0 THEN
    RAISE EXCEPTION 'v13: should_run baseline';
  END IF;
END
$should_run_base$;

CREATE FUNCTION public.v13_policy_share() RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $function$
DECLARE
  v_names text[];
  v_versions integer[];
  v_snap text;
  v_again text;
  v_name text;
  v_version integer;
BEGIN
  LOOP
    SELECT coalesce(array_agg(p.name ORDER BY p.name), '{}'::text[]),
           coalesce(array_agg(p.version ORDER BY p.name), '{}'::integer[]),
           coalesce(string_agg(p.name || ':' || p.version::text, ',' ORDER BY p.name), '')
      INTO v_names, v_versions, v_snap
      FROM public.v13_policies AS p
     WHERE p.active
       AND p.name IN ('capabilities', 'quota_window', 'should_run', 'spawn_budget', 'triage');
    FOR v_name, v_version IN
      SELECT u.name, u.version
        FROM unnest(v_names, v_versions) AS u(name, version)
       ORDER BY name
    LOOP
      PERFORM 1
        FROM public.v13_policies AS locked
       WHERE locked.name = v_name
         AND locked.version = v_version
       ORDER BY name
         FOR SHARE OF locked;
    END LOOP;
    SELECT coalesce(string_agg(p.name || ':' || p.version::text, ',' ORDER BY p.name), '')
      INTO v_again
      FROM public.v13_policies AS p
     WHERE p.active
       AND p.name IN ('capabilities', 'quota_window', 'should_run', 'spawn_budget', 'triage');
    IF v_again IS NOT DISTINCT FROM v_snap THEN
      RETURN;
    END IF;
  END LOOP;
END
$function$;

ALTER FUNCTION public.v13_policy_share() OWNER TO v13_spawn_owner;
REVOKE EXECUTE ON FUNCTION public.v13_policy_share() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_policy_share() TO v13_route;

DO $should_run_share$
DECLARE
  v_src text;
  v_lock text;
  v_from int;
  v_at int;
BEGIN
  IF NOT EXISTS (
    SELECT 1
      FROM pg_proc p
      JOIN pg_roles r ON r.oid = p.proowner
     WHERE p.oid = 'public.v13_policy_share()'::regprocedure
       AND p.prosecdef
       AND r.rolname = 'v13_spawn_owner'
       AND p.provolatile = 'v'
       AND p.proconfig::text LIKE '%search_path=pg_catalog, public, pg_temp%'
  ) THEN
    RAISE EXCEPTION 'v13: should_run policy_share attr';
  END IF;
  IF NOT has_function_privilege('v13_route', 'public.v13_policy_share()', 'EXECUTE')
     OR has_function_privilege('public', 'public.v13_policy_share()', 'EXECUTE') THEN
    RAISE EXCEPTION 'v13: should_run policy_share acl';
  END IF;
  SELECT prosrc INTO v_src FROM pg_proc WHERE oid = 'public.v13_policy_share()'::regprocedure;
  v_from := position('PERFORM 1' IN v_src);
  v_at := position('FOR SHARE OF locked' IN v_src);
  IF v_from > 0 AND v_at > v_from THEN
    v_lock := substring(v_src FROM v_from FOR (v_at - v_from));
  END IF;
  IF v_src IS NULL
     OR position('LOOP' IN v_src) = 0
     OR position('ORDER BY name' IN v_src) = 0
     OR position('AND active' IN v_src) > 0
     OR v_lock IS NULL
     OR position('active' IN v_lock) > 0
     OR position('capabilities' IN v_src) = 0
     OR position('quota_window' IN v_src) = 0
     OR position('should_run' IN v_src) = 0
     OR position('spawn_budget' IN v_src) = 0
     OR position('triage' IN v_src) = 0 THEN
    RAISE EXCEPTION 'v13: should_run policy_share body';
  END IF;
END
$should_run_share$;

CREATE FUNCTION public.v13_should_run_gate(p_sid uuid) RETURNS text
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
       OR v_id NOT IN ('human_pending', 'unknown_wall', 'unconsumed_cancel', 'duty_cycle')
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
    END IF;
  END LOOP;
  RETURN NULL;
END
$function$;

CREATE FUNCTION public.v13_should_run(p_sid uuid) RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
BEGIN
  RETURN public.v13_should_run_gate(p_sid) IS NULL;
END
$function$;

INSERT INTO public.v13_policies (name, version, value, active)
VALUES (
  'should_run',
  1,
  '{"schema_version":1,"gates":[{"id":"human_pending","effect":"block"},{"id":"unknown_wall","effect":"block"},{"id":"unconsumed_cancel","effect":"block"},{"id":"duty_cycle","effect":"shadow"}]}'::jsonb,
  true);

CREATE OR REPLACE FUNCTION public.v13_triage_prework(p_sid uuid)
 RETURNS text
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE v_dec text; v_reason text;
BEGIN
  v_dec := v13_triage_decide(v13_triage_project(p_sid));
  IF v_dec = 'reject' THEN
    IF v13_park_open_children(p_sid) THEN
      RETURN 'waiting';
    END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'triage_reject', false);
    RETURN 'terminal';
  END IF;
  IF v13_triage_duty() = 0 THEN
    IF NOT EXISTS (
      SELECT 1 FROM events
       WHERE session_id = p_sid AND type = 'triage/hold'
         AND seq > v13_last_user_seq(p_sid)) THEN
      PERFORM v13_triage_emit(p_sid, 'triage/hold', jsonb_build_object(
        'schema_version', 1, 'reason', 'duty_cycle'));
    END IF;
    UPDATE sessions SET status = 'waiting'
     WHERE session_id = p_sid AND status IN ('ready', 'waiting');
    RETURN 'waiting';
  END IF;
  IF NOT public.v13_should_run(p_sid) THEN
    UPDATE public.sessions SET status = 'waiting'
     WHERE session_id = p_sid AND status IN ('ready', 'waiting');
    RETURN 'waiting';
  END IF;
  IF v_dec = 'human' THEN
    RETURN v13_triage_enqueue_human(p_sid, 'triage_hard_gate');
  END IF;
  IF v_dec = 'decompose' THEN
    RETURN v13_triage_enqueue_llm(p_sid, 'triage_decompose');
  END IF;
  v_reason := v13_triage_fold_reason(p_sid);
  IF v_reason IS NOT NULL THEN
    RETURN v13_triage_enqueue_human(p_sid, v_reason);
  END IF;
  RETURN NULL;
END
$function$;

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

DO $should_run_keep$
BEGIN
  IF NOT has_function_privilege('v13_route', 'public.v13_advance(uuid,jsonb)', 'EXECUTE')
     OR NOT has_function_privilege('v13_route', 'public.v13_triage_prework(uuid)', 'EXECUTE') THEN
    RAISE EXCEPTION 'v13: should_run keep grant';
  END IF;
END
$should_run_keep$;

REVOKE EXECUTE ON FUNCTION public.v13_should_run(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.v13_should_run_gate(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_should_run(uuid) TO v13_route;
GRANT EXECUTE ON FUNCTION public.v13_should_run_gate(uuid) TO v13_route;

COMMIT;
