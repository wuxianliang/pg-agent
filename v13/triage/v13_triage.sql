BEGIN;

INSERT INTO v13_policies (name, version, value, active)
VALUES ('triage', 1, '{"duty_cycle":1}'::jsonb, true);

INSERT INTO v13_judgment_template_versions (template_name, template_version)
VALUES ('triage', 1);

INSERT INTO judgment_templates (
  template_name, template_version, kind, question, criteria, answer_schema_version,
  projection, provider, model, writer, wire_version, canon_version)
VALUES (
  'triage', 1, 'choice',
  'Should this root goal be done in this session, split across child sessions, or handed to a person?',
  jsonb_build_object(
    'direct', 'Do the task in this session. Do not spawn.',
    'decompose', 'Split the task across child sessions.',
    'human', 'Hand the task to a person.'),
  1, '["*"]'::jsonb, NULL, NULL, 'v13_resolve', 1, 1);

UPDATE v13_judgment_template_versions
   SET state = 'frozen'
 WHERE template_name = 'triage' AND template_version = 1;

DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'v13_triage_owner') THEN
    CREATE ROLE v13_triage_owner NOLOGIN NOSUPERUSER;
  END IF;
END
$role$;

GRANT USAGE ON SCHEMA public TO v13_triage_owner;
GRANT SELECT, UPDATE ON sessions TO v13_triage_owner;
GRANT INSERT ON events TO v13_triage_owner;
GRANT EXECUTE ON FUNCTION v13_append_event(uuid, uuid, text, jsonb, uuid) TO v13_triage_owner;
GRANT EXECUTE ON FUNCTION v13_json_keys(jsonb), v13_json_int_ok(jsonb, numeric) TO v13_triage_owner;
GRANT EXECUTE ON FUNCTION digest(text, text) TO v13_triage_owner;

CREATE FUNCTION public.v13_triage_duty() RETURNS int
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
DECLARE v jsonb;
BEGIN
  v := v13_policy('triage');
  IF v13_json_keys(v) IS DISTINCT FROM ARRAY['duty_cycle']
     OR (v->>'duty_cycle') NOT IN ('0', '1') THEN
    RAISE EXCEPTION 'v13: triage policy';
  END IF;
  RETURN (v->>'duty_cycle')::int;
END
$fn$;

CREATE FUNCTION public.v13_triage_tree_null(p jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $fn$
  SELECT (p->'ancestor_depth' IS NULL OR jsonb_typeof(p->'ancestor_depth') = 'null')
      OR (p->'n_nonterminal_children' IS NULL OR jsonb_typeof(p->'n_nonterminal_children') = 'null')
      OR (p->'remaining_turns' IS NULL OR jsonb_typeof(p->'remaining_turns') = 'null')
      OR (p->'quota_remaining' IS NULL OR jsonb_typeof(p->'quota_remaining') = 'null')
      OR (p->'subtree_reserved' IS NULL OR jsonb_typeof(p->'subtree_reserved') = 'null');
$fn$;

CREATE FUNCTION public.v13_triage_hard(p jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $fn$
BEGIN
  IF p->'ancestor_depth' IS NOT NULL
     AND jsonb_typeof(p->'ancestor_depth') = 'number'
     AND p->'max_depth' IS NOT NULL
     AND jsonb_typeof(p->'max_depth') = 'number'
     AND (p->>'ancestor_depth')::numeric >= (p->>'max_depth')::numeric THEN
    RETURN true;
  END IF;
  IF p->'remaining_turns' IS NOT NULL
     AND jsonb_typeof(p->'remaining_turns') = 'number'
     AND (p->>'remaining_turns')::numeric < 1 THEN
    RETURN true;
  END IF;
  RETURN false;
END
$fn$;

CREATE FUNCTION public.v13_triage_decide(p jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE v_over text;
BEGIN
  IF p IS NULL OR jsonb_typeof(p) <> 'object' THEN
    RAISE EXCEPTION 'v13: triage proj';
  END IF;
  IF jsonb_typeof(p->'fold_empty') = 'boolean' AND (p->>'fold_empty')::boolean THEN
    RETURN 'reject';
  END IF;
  v_over := p->>'user_intent_override';
  IF v_over IS NOT NULL AND v_over NOT IN ('direct', 'decompose') THEN
    RAISE EXCEPTION 'v13: triage proj';
  END IF;
  IF v_over = 'direct' THEN
    RETURN 'direct';
  END IF;
  IF v_over = 'decompose' THEN
    IF v13_triage_tree_null(p) THEN
      RETURN 'none';
    END IF;
    IF v13_triage_hard(p) THEN
      RETURN 'human';
    END IF;
    RETURN 'decompose';
  END IF;
  IF NOT v13_triage_tree_null(p)
     AND jsonb_typeof(p->'ancestor_depth') = 'number'
     AND (p->>'ancestor_depth')::numeric >= 1 THEN
    RETURN 'direct';
  END IF;
  RETURN 'none';
END
$fn$;

CREATE FUNCTION public.v13_triage_project(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
DECLARE
  v_root uuid; v_parent uuid; v_guard int := 0;
  v_depth int; v_occ int; v_max_nt int; v_max_depth int; v_rem int;
  v_kids int; v_est int; v_bytes int; v_div int;
  v_over text; v_hash text; v_empty boolean; v_pol jsonb;
BEGIN
  PERFORM 1 FROM sessions WHERE session_id = p_sid;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: unknown session %', p_sid;
  END IF;
  v_root := p_sid;
  LOOP
    SELECT parent_session_id INTO v_parent FROM sessions WHERE session_id = v_root;
    EXIT WHEN v_parent IS NULL;
    v_guard := v_guard + 1;
    IF v_guard > 64 THEN
      RAISE EXCEPTION 'v13: goal tree depth cap';
    END IF;
    v_root := v_parent;
  END LOOP;
  SELECT t.depth INTO v_depth FROM v_goal_tree(v_root) t WHERE t.session_id = p_sid;
  v_occ := v13_spawn_occupancy(v_root);
  v_pol := v13_policy('spawn_budget');
  IF v13_json_keys(v_pol) IS DISTINCT FROM ARRAY['max_depth', 'max_fanout', 'max_nonterminal'] THEN
    RAISE EXCEPTION 'v13: spawn_budget policy';
  END IF;
  v_max_nt := (v_pol->>'max_nonterminal')::int;
  v_max_depth := (v_pol->>'max_depth')::int;
  v_rem := v_max_nt - v_occ;
  SELECT count(*)::int INTO v_kids FROM sessions
   WHERE parent_session_id = p_sid
     AND status NOT IN ('completed', 'failed', 'cancelled');
  SELECT payload->>'intent' INTO v_over FROM events
   WHERE session_id = p_sid AND type = 'goal/override'
   ORDER BY seq DESC LIMIT 1;
  SELECT payload->>'evidence_hash' INTO v_hash FROM events
   WHERE session_id = p_sid AND type = 'explore/completed'
   ORDER BY seq DESC LIMIT 1;
  v_empty := NOT EXISTS (
    SELECT 1 FROM events
     WHERE session_id = p_sid AND type = 'user/message'
       AND coalesce(btrim(payload->>'text'), '') <> '');
  IF NOT EXISTS (SELECT 1 FROM v13_goals WHERE session_id = p_sid) THEN
    v_est := 0;
  ELSE
    SELECT octet_length(coalesce(g.payload->>'text', '')) INTO v_bytes
      FROM v13_goals g WHERE g.session_id = p_sid
     ORDER BY g.seq DESC LIMIT 1;
    v_div := (v13_policy('assemble_manifest')->>'est_bytes_per_token')::int;
    IF v_div IS NULL OR v_div <= 0 THEN
      RAISE EXCEPTION 'v13: triage est divisor';
    END IF;
    v_est := (coalesce(v_bytes, 0) + v_div - 1) / v_div;
  END IF;
  RETURN jsonb_build_object(
    'task_content_hash', v13_goal_hash(p_sid),
    'task_est_tokens', v_est,
    'user_intent_override', to_jsonb(v_over),
    'has_mutating_hint', false,
    'policy_version', (SELECT route_policy_version FROM sessions WHERE session_id = p_sid),
    'explore_evidence_hash', to_jsonb(v_hash),
    'ancestor_depth', v_depth,
    'n_nonterminal_children', v_kids,
    'remaining_turns', v_rem,
    'quota_remaining', v_rem,
    'subtree_reserved', v_occ,
    'max_depth', v_max_depth,
    'fold_empty', v_empty);
END
$fn$;

CREATE FUNCTION public.v13_triage_emit(p_sid uuid, p_type text, p_payload jsonb)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF p_type NOT IN ('goal/override', 'triage/hold', 'explore/completed') THEN
    RAISE EXCEPTION 'v13: triage emit';
  END IF;
  RETURN v13_append_event(p_sid, gen_random_uuid(), p_type, p_payload);
END
$fn$;

ALTER FUNCTION public.v13_triage_emit(uuid, text, jsonb) OWNER TO v13_triage_owner;

CREATE FUNCTION public.v13_triage_event_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
DECLARE v_keys text[];
BEGIN
  IF current_user IS DISTINCT FROM 'v13_triage_owner' THEN
    RAISE EXCEPTION 'v13: triage writer';
  END IF;
  v_keys := v13_json_keys(NEW.payload);
  IF NEW.type = 'goal/override' THEN
    IF NEW.source_effect_id IS NOT NULL
       OR v_keys IS DISTINCT FROM ARRAY['intent', 'reason', 'schema_version', 'source_principal']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR (NEW.payload->>'schema_version')::int <> 1
       OR NEW.payload->>'intent' NOT IN ('direct', 'decompose')
       OR NEW.payload->>'source_principal' NOT IN ('user', 'operator')
       OR jsonb_typeof(NEW.payload->'reason') <> 'string'
       OR char_length(NEW.payload->>'reason') > 256 THEN
      RAISE EXCEPTION 'v13: event payload goal/override';
    END IF;
  ELSIF NEW.type = 'triage/hold' THEN
    IF NEW.source_effect_id IS NOT NULL
       OR v_keys IS DISTINCT FROM ARRAY['reason', 'schema_version']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR (NEW.payload->>'schema_version')::int <> 1
       OR NEW.payload->>'reason' IS DISTINCT FROM 'duty_cycle' THEN
      RAISE EXCEPTION 'v13: event payload triage/hold';
    END IF;
  ELSIF NEW.type = 'explore/completed' THEN
    IF NEW.source_effect_id IS NOT NULL
       OR v_keys IS DISTINCT FROM ARRAY['evidence_hash', 'schema_version']
       OR NOT v13_json_int_ok(NEW.payload->'schema_version', 1)
       OR (NEW.payload->>'schema_version')::int <> 1
       OR NEW.payload->>'evidence_hash' !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'v13: event payload explore/completed';
    END IF;
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_v13_triage_event_guard
  BEFORE INSERT ON events
  FOR EACH ROW
  WHEN (NEW.type IN ('goal/override', 'triage/hold', 'explore/completed'))
  EXECUTE FUNCTION public.v13_triage_event_guard();

CREATE FUNCTION public.v13_submit_override(p_sid uuid, p_payload jsonb) RETURNS bigint
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
DECLARE v jsonb;
BEGIN
  IF p_payload IS NULL OR jsonb_typeof(p_payload) <> 'object' THEN
    RAISE EXCEPTION 'v13: override args';
  END IF;
  v := p_payload;
  IF NOT (v ? 'reason') THEN
    v := v || jsonb_build_object('reason', '');
  END IF;
  IF v13_json_keys(v) IS DISTINCT FROM ARRAY['intent', 'reason', 'schema_version', 'source_principal']
     OR NOT v13_json_int_ok(v->'schema_version', 1)
     OR (v->>'schema_version')::int <> 1
     OR v->>'intent' NOT IN ('direct', 'decompose')
     OR v->>'source_principal' NOT IN ('user', 'operator')
     OR jsonb_typeof(v->'reason') <> 'string'
     OR char_length(v->>'reason') > 256 THEN
    RAISE EXCEPTION 'v13: override args';
  END IF;
  RETURN v13_triage_emit(p_sid, 'goal/override', v);
END
$fn$;

CREATE FUNCTION public.v13_triage_note_explore(p_sid uuid, p_result jsonb) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
DECLARE v_hash text;
BEGIN
  v_hash := encode(digest(coalesce(p_result, 'null'::jsonb)::text, 'sha256'), 'hex');
  PERFORM v13_triage_emit(p_sid, 'explore/completed', jsonb_build_object(
    'schema_version', 1, 'evidence_hash', v_hash));
  RETURN v_hash;
END
$fn$;

CREATE FUNCTION public.v13_triage_band(p_name text, p_ver int, p_signal text, p_value numeric)
RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $fn$
  SELECT t.action FROM thresholds t
   WHERE t.policy_name = p_name AND t.policy_version = p_ver
     AND t.signal = p_signal
     AND p_value >= t.lo AND p_value < t.hi
   ORDER BY t.band_no
   LIMIT 1;
$fn$;

CREATE FUNCTION public.v13_triage_enqueue_human(p_sid uuid, p_reason text) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
DECLARE v_effect uuid; v_route jsonb;
BEGIN
  v_route := jsonb_build_object('action', 'human', 'reason', p_reason);
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
  v_effect := v13_enqueue_effect(p_sid, 'human', jsonb_build_object('reason', p_reason));
  PERFORM v13_send_work(v_effect);
  UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
  RETURN 'waiting';
END
$fn$;

CREATE FUNCTION public.v13_triage_enqueue_llm(p_sid uuid, p_reason text) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
DECLARE v_effect uuid; v_route jsonb;
BEGIN
  v_route := jsonb_build_object('action', 'llm', 'reason', p_reason);
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);
  v_effect := v13_enqueue_effect(p_sid, 'llm', jsonb_build_object('route', v_route));
  PERFORM v13_send_work(v_effect);
  UPDATE sessions SET status = 'waiting' WHERE session_id = p_sid;
  RETURN 'waiting';
END
$fn$;

CREATE FUNCTION public.v13_triage_fold_reason(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
DECLARE
  v_name text; v_ver int; v_count int; v_action text;
BEGIN
  SELECT route_policy_name, route_policy_version INTO v_name, v_ver
    FROM sessions WHERE session_id = p_sid;
  IF (SELECT count(*) FROM events WHERE session_id = p_sid AND type = 'repair/required') > 0
     AND NOT EXISTS (
       SELECT 1 FROM effects
        WHERE session_id = p_sid AND kind = 'human'
          AND origin_user_seq = v13_last_user_seq(p_sid)
          AND request = jsonb_build_object('reason', 'repair_cap')) THEN
    v_count := (SELECT count(*) FROM events WHERE session_id = p_sid AND type = 'repair/required');
    v_action := v13_triage_band(v_name, v_ver, 'harness.repair_count', v_count);
    IF v_action IS NULL OR v_action = 'reject' THEN
      RETURN 'repair_cap';
    END IF;
  END IF;
  IF (SELECT count(*) FROM events WHERE session_id = p_sid AND type = 'replan/required') > 0
     AND NOT EXISTS (
       SELECT 1 FROM effects
        WHERE session_id = p_sid AND kind = 'human'
          AND origin_user_seq = v13_last_user_seq(p_sid)
          AND request = jsonb_build_object('reason', 'replan_cap')) THEN
    v_count := (SELECT count(*) FROM events WHERE session_id = p_sid AND type = 'replan/required');
    v_action := v13_triage_band(v_name, v_ver, 'harness.replan_count', v_count);
    IF v_action IS NULL OR v_action = 'reject' THEN
      RETURN 'replan_cap';
    END IF;
  END IF;
  RETURN NULL;
END
$fn$;

CREATE FUNCTION public.v13_triage_prework(p_sid uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
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
$fn$;

CREATE FUNCTION public.v13_triage_mark_explore(p_sid uuid) RETURNS void
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
DECLARE v_result jsonb;
BEGIN
  IF EXISTS (
    SELECT 1 FROM events
     WHERE session_id = p_sid AND type = 'explore/completed'
       AND seq > v13_last_user_seq(p_sid)) THEN
    RETURN;
  END IF;
  SELECT e.result INTO v_result
    FROM effects e
   WHERE e.session_id = p_sid AND e.kind = 'llm' AND e.status = 'succeeded'
     AND e.origin_user_seq = v13_last_user_seq(p_sid)
     AND e.request->'route'->>'reason' = 'explore'
   ORDER BY e.created_at DESC
   LIMIT 1;
  IF NOT FOUND THEN
    RETURN;
  END IF;
  PERFORM v13_triage_note_explore(p_sid, v_result);
END
$fn$;

CREATE FUNCTION public.v13_triage_steer(p_sid uuid) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $fn$
DECLARE
  v_dec text; v_ans jsonb; v_choice text; v_name text; v_ver int;
  v_conf numeric; v_nbands int; v_act text; v_explored boolean;
BEGIN
  PERFORM v13_triage_mark_explore(p_sid);
  v_dec := v13_triage_decide(v13_triage_project(p_sid));
  IF v_dec = 'direct' THEN
    RETURN NULL;
  END IF;
  IF v_dec = 'reject' THEN
    IF v13_park_open_children(p_sid) THEN
      RETURN 'waiting';
    END IF;
    PERFORM v13_closeout(p_sid, 'failed', 'triage_reject', false);
    RETURN 'terminal';
  END IF;
  IF v_dec = 'human' THEN
    RETURN v13_triage_enqueue_human(p_sid, 'triage_hard_gate');
  END IF;
  IF v_dec = 'decompose' THEN
    RETURN v13_triage_enqueue_llm(p_sid, 'triage_decompose');
  END IF;
  IF (SELECT parent_session_id FROM sessions WHERE session_id = p_sid) IS NOT NULL THEN
    RETURN NULL;
  END IF;
  SELECT d.answer INTO v_ans FROM decisions d
   WHERE d.session_id = p_sid AND d.signal = 'triage'
     AND d.status IN ('answered', 'cached') AND d.answer IS NOT NULL
   ORDER BY d.answered_at DESC NULLS LAST
   LIMIT 1;
  IF v_ans IS NULL THEN
    RETURN v13_triage_enqueue_human(p_sid, 'triage_fail_closed');
  END IF;
  v_choice := v_ans->>'choice';
  IF v_choice NOT IN ('direct', 'decompose', 'human') THEN
    RETURN v13_triage_enqueue_human(p_sid, 'triage_fail_closed');
  END IF;
  SELECT route_policy_name, route_policy_version INTO v_name, v_ver
    FROM sessions WHERE session_id = p_sid;
  v_conf := v13_signal('choice', v_ans);
  SELECT count(*)::int INTO v_nbands FROM thresholds
   WHERE policy_name = v_name AND policy_version = v_ver AND signal = 'triage';
  v_act := v13_triage_band(v_name, v_ver, 'triage', v_conf);
  v_explored := EXISTS (
    SELECT 1 FROM events
     WHERE session_id = p_sid AND type = 'explore/completed'
       AND seq > v13_last_user_seq(p_sid));
  IF v_nbands > 0 AND v_act IS NULL THEN
    IF NOT v_explored THEN
      RETURN v13_triage_enqueue_llm(p_sid, 'explore');
    END IF;
    RETURN v13_triage_enqueue_human(p_sid, 'triage_review');
  END IF;
  IF v_act = 'pass' THEN
    IF v_choice = 'human' THEN
      RETURN v13_triage_enqueue_human(p_sid, 'triage_choice');
    ELSIF v_choice = 'decompose' THEN
      IF v13_triage_hard(v13_triage_project(p_sid)) THEN
        RETURN v13_triage_enqueue_human(p_sid, 'triage_hard_gate');
      END IF;
      RETURN v13_triage_enqueue_llm(p_sid, 'triage_decompose');
    END IF;
    RETURN NULL;
  END IF;
  RETURN v13_triage_enqueue_human(p_sid, 'triage_fail_closed');
END
$fn$;

CREATE FUNCTION public.v13_triage_after_route(p_sid uuid, p_route jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
DECLARE v_dec text; v_choice text;
BEGIN
  v_dec := v13_triage_decide(v13_triage_project(p_sid));
  IF v_dec = 'none' THEN
    SELECT d.answer->>'choice' INTO v_choice FROM decisions d
     WHERE d.session_id = p_sid AND d.signal = 'triage'
       AND d.status IN ('answered', 'cached') AND d.answer IS NOT NULL
     ORDER BY d.answered_at DESC NULLS LAST
     LIMIT 1;
    IF v_choice = 'direct' THEN
      v_dec := 'direct';
    END IF;
  END IF;
  IF v_dec = 'direct'
     AND p_route->>'action' = 'sql'
     AND p_route->>'tool' = 'spawn_subsession' THEN
    RETURN jsonb_build_object('action', 'human', 'reason', 'triage_direct');
  END IF;
  RETURN p_route;
END
$fn$;

CREATE FUNCTION public.v13_triage_block_explore_spawn(p_sid uuid) RETURNS void
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $fn$
BEGIN
  IF EXISTS (
    SELECT 1 FROM events tc
    JOIN effects ef ON ef.effect_id = tc.source_effect_id
     WHERE tc.session_id = p_sid AND tc.type = 'tool/call'
       AND tc.seq > v13_last_user_seq(p_sid)
       AND ef.request->'route'->>'reason' = 'explore'
       AND NOT EXISTS (
         SELECT 1 FROM events c
          WHERE c.session_id = p_sid AND c.type = 'child-created'
            AND c.payload->>'tool_call_id' = tc.payload->>'id')) THEN
    RAISE EXCEPTION 'v13: explore spawn';
  END IF;
END
$fn$;

CREATE FUNCTION public.v13_cap_human_answered(p_sid uuid, p_pred uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $fn$
  SELECT EXISTS (
    SELECT 1 FROM effects h
    JOIN events ev ON ev.source_effect_id = h.effect_id AND ev.type = 'human/responded'
     WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
       AND h.origin_user_seq = v13_last_user_seq(p_sid)
       AND h.request->>'interaction_kind' IN ('material_cap', 'repair_cap', 'replan_cap')
       AND ev.seq > coalesce((SELECT max(seq) FROM events
                               WHERE source_effect_id = p_pred AND type = 'effect_done'), -1)
  ) OR EXISTS (
    SELECT 1 FROM effects h
     WHERE h.session_id = p_sid AND h.kind = 'human' AND h.status = 'succeeded'
       AND h.origin_user_seq = v13_last_user_seq(p_sid)
       AND h.request->>'reason' IN ('repair_cap', 'replan_cap')
       AND NOT (h.request ? 'interaction_kind')
  );
$fn$;

CREATE FUNCTION public.v13_triage_hold_blocks_recover(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $fn$
  SELECT v13_triage_duty() = 0
     AND coalesce((SELECT max(seq) FROM events
                    WHERE session_id = p_sid AND type = 'triage/hold'), -1)
         > v13_last_user_seq(p_sid);
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
                         AND NOT v13_is_spawn_tool(tools.name, tools.kind)) t);
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

  IF (SELECT parent_session_id FROM sessions WHERE session_id = p_sid) IS NULL
     AND NOT EXISTS (
       SELECT 1 FROM events
        WHERE session_id = p_sid AND type = 'goal/override') THEN
    signal := 'triage';
    kind := 'choice';
    question := 'Should this root goal be done in this session, split across child sessions, or handed to a person?';
    criteria := jsonb_build_object(
      'direct', 'Do the task in this session. Do not spawn.',
      'decompose', 'Split the task across child sessions.',
      'human', 'Hand the task to a person.')
      || jsonb_build_object(
           'explore_evidence_hash',
           coalesce(v13_triage_project(p_sid)->'explore_evidence_hash', 'null'::jsonb));
    template_name := 'triage';
    v_sigs := v_sigs || signal;
    RETURN NEXT;
  END IF;

  PERFORM 1 FROM unnest(v_sigs) s GROUP BY s HAVING count(*) > 1;
  IF FOUND THEN
    RAISE EXCEPTION 'v13: needed signal collision (tools catalog violates syntax guard?)';
  END IF;
END $function$;


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



REVOKE ALL ON FUNCTION
  v13_triage_duty(),
  v13_triage_tree_null(jsonb),
  v13_triage_hard(jsonb),
  v13_triage_decide(jsonb),
  v13_triage_project(uuid),
  v13_triage_emit(uuid, text, jsonb),
  v13_triage_event_guard(),
  v13_submit_override(uuid, jsonb),
  v13_triage_note_explore(uuid, jsonb),
  v13_triage_band(text, int, text, numeric),
  v13_triage_enqueue_human(uuid, text),
  v13_triage_enqueue_llm(uuid, text),
  v13_triage_fold_reason(uuid),
  v13_triage_prework(uuid),
  v13_triage_mark_explore(uuid),
  v13_triage_steer(uuid),
  v13_triage_after_route(uuid, jsonb),
  v13_triage_block_explore_spawn(uuid),
  v13_cap_human_answered(uuid, uuid),
  v13_triage_hold_blocks_recover(uuid)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
  v13_triage_duty(),
  v13_triage_tree_null(jsonb),
  v13_triage_hard(jsonb),
  v13_triage_decide(jsonb),
  v13_triage_project(uuid),
  v13_triage_emit(uuid, text, jsonb),
  v13_submit_override(uuid, jsonb),
  v13_triage_note_explore(uuid, jsonb),
  v13_triage_band(text, int, text, numeric),
  v13_triage_enqueue_human(uuid, text),
  v13_triage_enqueue_llm(uuid, text),
  v13_triage_fold_reason(uuid),
  v13_triage_prework(uuid),
  v13_triage_mark_explore(uuid),
  v13_triage_steer(uuid),
  v13_triage_after_route(uuid, jsonb),
  v13_triage_block_explore_spawn(uuid),
  v13_cap_human_answered(uuid, uuid),
  v13_triage_hold_blocks_recover(uuid)
TO v13_route;

COMMIT;
