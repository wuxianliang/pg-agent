CREATE OR REPLACE FUNCTION public.v13_frontier_gap_compose(
  p_root uuid,
  p_before_seq bigint,
  p_watermark boolean
) RETURNS TABLE (
  frontier jsonb,
  frontier_hash text,
  omitted_count integer,
  omitted_complete boolean
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_cur jsonb;
  v_plan_id text;
  v_canonical jsonb;
  v_ev record;
  v_todo jsonb;
  v_can jsonb;
  v_state jsonb := '{}'::jsonb;
  v_id text;
  v_row jsonb;
  v_bind jsonb;
  v_key text;
  v_link jsonb;
  v_members jsonb := '[]'::jsonb;
  v_gaps jsonb := '[]'::jsonb;
  v_member jsonb;
  v_gap jsonb;
  v_target text;
  v_member_ids uuid[] := '{}';
  v_frontier jsonb;
  v_n integer;
BEGIN
  IF p_watermark AND p_before_seq IS NULL THEN
    v_cur := public.v13_plan_current(p_root);
    IF v_cur IS NULL THEN
      v_plan_id := NULL;
      v_canonical := NULL;
    ELSE
      v_plan_id := v_cur->>'plan_id';
      v_canonical := v_cur->'canonical';
    END IF;
  ELSIF p_watermark THEN
    SELECT e.payload->>'plan_id', e.payload->'canonical'
      INTO v_plan_id, v_canonical
      FROM public.events e
     WHERE e.session_id = p_root
       AND e.type = 'plan/committed'
       AND e.seq < p_before_seq
       AND NOT EXISTS (
         SELECT 1
           FROM public.events u
          WHERE u.session_id = p_root
            AND u.type = 'user/message'
            AND u.seq > (e.payload->'canonical'->>'based_on_seq')::bigint
            AND u.seq < p_before_seq)
     ORDER BY e.seq DESC, (e.payload->>'plan_id')::uuid DESC
     LIMIT 1;
  ELSE
    SELECT e.payload->>'plan_id', e.payload->'canonical'
      INTO v_plan_id, v_canonical
      FROM public.events e
     WHERE e.session_id = p_root
       AND e.type = 'plan/committed'
       AND (p_before_seq IS NULL OR e.seq < p_before_seq)
     ORDER BY e.seq DESC, (e.payload->>'plan_id')::uuid DESC
     LIMIT 1;
  END IF;

  FOR v_ev IN
    SELECT e.seq, e.type, e.payload
      FROM public.events e
     WHERE e.session_id = p_root
       AND e.type IN ('plan/committed', 'todo/delta')
       AND (p_before_seq IS NULL OR e.seq < p_before_seq)
     ORDER BY e.seq
  LOOP
    v_can := v_ev.payload->'canonical';
    IF v_ev.type = 'plan/committed' THEN
      FOR v_todo IN SELECT value FROM jsonb_array_elements(v_can->'todos') LOOP
        IF v_todo->>'verb' = 'add_new' AND NOT (v_state ? (v_todo->>'todo_id')) THEN
          v_state := v_state || jsonb_build_object(
            v_todo->>'todo_id',
            jsonb_build_object(
              'text_hash', v_todo->'text_hash',
              'task_class', v_todo->'task_class',
              'status', v_todo->'status',
              'due', CASE
                WHEN v_todo->'due' IS NULL THEN 'null'::jsonb
                ELSE v_todo->'due'
              END,
              'link_on', 'null'::jsonb,
              'link_id', 'null'::jsonb));
        END IF;
      END LOOP;
    ELSIF v_ev.type = 'todo/delta'
          AND v_ev.payload->>'call_kind' = 'todo_delta' THEN
      v_id := v_can->>'todo_id';
      IF v_id IS NULL OR NOT (v_state ? v_id) THEN
        CONTINUE;
      END IF;
      v_row := v_state->v_id;
      IF v_can->>'status_from' IS DISTINCT FROM v_can->>'status_to' THEN
        v_row := jsonb_set(v_row, '{status}', to_jsonb(v_can->>'status_to'));
      END IF;
      IF jsonb_typeof(v_can->'due') = 'string' THEN
        v_row := jsonb_set(v_row, '{due}', v_can->'due');
      END IF;
      IF jsonb_typeof(v_can->'link') = 'object' THEN
        v_row := jsonb_set(v_row, '{link_on}', v_can->'link'->'on');
        v_row := jsonb_set(v_row, '{link_id}', v_can->'link'->'id');
      END IF;
      v_bind := v_can->'binding';
      IF jsonb_typeof(v_bind) = 'object' THEN
        NULL;
      END IF;
      v_state := jsonb_set(v_state, ARRAY[v_id], v_row);
    END IF;
  END LOOP;

  IF v_canonical IS NULL OR jsonb_typeof(v_canonical->'todos') IS DISTINCT FROM 'array' THEN
    v_frontier := jsonb_build_object(
      'schema_version', 1,
      'plan_id', 'null'::jsonb,
      'members', '[]'::jsonb,
      'gaps', '[]'::jsonb);
    frontier := v_frontier;
    frontier_hash := encode(digest(convert_to(v_frontier::text, 'UTF8'), 'sha256'), 'hex');
    omitted_count := 0;
    omitted_complete := true;
    RETURN NEXT;
    RETURN;
  END IF;

  SELECT coalesce(array_agg((elem->>'todo_id')::uuid), '{}'::uuid[])
    INTO v_member_ids
    FROM jsonb_array_elements(v_canonical->'todos') elem
   WHERE public.v13_canonical_uuid(elem->>'todo_id');

  FOR v_todo IN SELECT value FROM jsonb_array_elements(v_canonical->'todos') LOOP
    v_id := v_todo->>'todo_id';
    v_row := v_state->v_id;
    IF v_row IS NULL THEN
      CONTINUE;
    END IF;
    v_member := jsonb_build_object(
      'todo_id', v_id,
      'task_class', v_row->>'task_class',
      'status', v_row->>'status',
      'text_hash', v_row->>'text_hash',
      'due', CASE
        WHEN jsonb_typeof(v_row->'due') = 'string' THEN v_row->'due'
        ELSE 'null'::jsonb
      END,
      'link_on', CASE
        WHEN jsonb_typeof(v_row->'link_on') = 'string' THEN v_row->'link_on'
        ELSE 'null'::jsonb
      END,
      'link_id', CASE
        WHEN jsonb_typeof(v_row->'link_id') = 'string' THEN v_row->'link_id'
        ELSE 'null'::jsonb
      END);
    v_members := v_members || jsonb_build_array(v_member);
    v_target := CASE
      WHEN jsonb_typeof(v_row->'link_id') = 'string' THEN v_row->>'link_id'
      ELSE NULL
    END;
    IF v_target IS NOT NULL
       AND public.v13_canonical_uuid(v_target)
       AND NOT (v_target::uuid = ANY (v_member_ids)) THEN
      v_gap := jsonb_build_object(
        'gap_kind', 'dangling_link',
        'subject_todo_id', v_id,
        'object_todo_id', v_target);
      v_gaps := v_gaps || jsonb_build_array(v_gap);
    END IF;
  END LOOP;

  SELECT coalesce(jsonb_agg(elem ORDER BY (elem->>'todo_id')::uuid), '[]'::jsonb)
    INTO v_members
    FROM jsonb_array_elements(v_members) elem;
  SELECT coalesce(
           jsonb_agg(elem ORDER BY (elem->>'subject_todo_id')::uuid,
                     (elem->>'object_todo_id')::uuid NULLS LAST),
           '[]'::jsonb)
    INTO v_gaps
    FROM jsonb_array_elements(v_gaps) elem;

  v_frontier := jsonb_build_object(
    'schema_version', 1,
    'plan_id', CASE
      WHEN v_plan_id IS NULL THEN 'null'::jsonb
      ELSE to_jsonb(v_plan_id)
    END,
    'members', v_members,
    'gaps', v_gaps);
  v_n := jsonb_array_length(v_frontier->'gaps');
  frontier := v_frontier;
  frontier_hash := encode(digest(convert_to(v_frontier::text, 'UTF8'), 'sha256'), 'hex');
  IF v_n > 32 THEN
    omitted_count := 1;
    omitted_complete := false;
  ELSE
    omitted_count := 0;
    omitted_complete := true;
  END IF;
  RETURN NEXT;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_frontier_project(p_root uuid, p_before_seq bigint)
RETURNS TABLE (
  frontier jsonb,
  frontier_hash text,
  has_obligation boolean[],
  omitted_count integer,
  omitted_complete boolean
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_comp record;
  v_prefix jsonb;
  v_has boolean[] := '{}';
  v_g jsonb;
  v_open boolean;
  v_sub uuid;
  v_obj uuid;
BEGIN
  v_root := public.v13_plan_map_root(p_root);
  SELECT c.frontier, c.frontier_hash, c.omitted_count, c.omitted_complete
    INTO v_comp
    FROM public.v13_frontier_gap_compose(v_root, p_before_seq, true) c;
  SELECT coalesce(jsonb_agg(elem ORDER BY ord), '[]'::jsonb)
    INTO v_prefix
    FROM jsonb_array_elements(v_comp.frontier->'gaps') WITH ORDINALITY AS t(elem, ord)
   WHERE ord <= 32;
  FOR v_g IN
    SELECT value FROM jsonb_array_elements(v_prefix)
  LOOP
    v_sub := (v_g->>'subject_todo_id')::uuid;
    IF jsonb_typeof(v_g->'object_todo_id') = 'string' THEN
      v_obj := (v_g->>'object_todo_id')::uuid;
    ELSE
      v_obj := NULL;
    END IF;
    SELECT EXISTS (
      SELECT 1
        FROM public.v13_obligation_open(v_root) o
       WHERE o.gap_kind = v_g->>'gap_kind'
         AND o.subject_todo_id = v_sub
         AND o.object_todo_id IS NOT DISTINCT FROM v_obj)
      INTO v_open;
    v_has := v_has || v_open;
  END LOOP;
  frontier := jsonb_set(v_comp.frontier, '{gaps}', v_prefix);
  frontier_hash := v_comp.frontier_hash;
  has_obligation := v_has;
  omitted_count := v_comp.omitted_count;
  omitted_complete := v_comp.omitted_complete;
  RETURN NEXT;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_obligation_open(p_root uuid)
RETURNS TABLE (
  gap_kind text,
  subject_todo_id uuid,
  object_todo_id uuid,
  event_id uuid,
  source_effect_id uuid
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_ev record;
  v_comp record;
  v_now record;
  v_g jsonb;
  v_hits integer;
  v_kind text;
  v_sub uuid;
  v_obj uuid;
  v_nat text;
  v_cur boolean;
BEGIN
  v_root := public.v13_plan_map_root(p_root);
  SELECT c.frontier INTO v_now
    FROM public.v13_frontier_gap_compose(v_root, NULL, false) c;
  FOR v_ev IN
    SELECT e.event_id, e.seq, e.source_effect_id, e.payload
      FROM public.events e
     WHERE e.session_id = v_root
       AND e.type = 'replan/required'
       AND public.v13_json_keys(e.payload) = ARRAY['schema_version']
       AND e.payload->'schema_version' = '1'::jsonb
       AND e.source_effect_id IS NOT NULL
       AND NOT EXISTS (
         SELECT 1 FROM public.effects x WHERE x.effect_id = e.source_effect_id)
     ORDER BY e.seq
  LOOP
    SELECT c.frontier INTO v_comp
      FROM public.v13_frontier_gap_compose(v_root, v_ev.seq, false) c;
    v_hits := 0;
    v_kind := NULL;
    v_sub := NULL;
    v_obj := NULL;
    FOR v_g IN SELECT value FROM jsonb_array_elements(v_comp.frontier->'gaps') LOOP
      v_nat := 'replan:' || v_root::text || ':' || (v_g->>'gap_kind') || ':'
               || (v_g->>'subject_todo_id') || ':'
               || coalesce(v_g->>'object_todo_id', '');
      IF public.v13_plan_apply_id(v_nat) = v_ev.source_effect_id THEN
        v_hits := v_hits + 1;
        v_kind := v_g->>'gap_kind';
        v_sub := (v_g->>'subject_todo_id')::uuid;
        IF jsonb_typeof(v_g->'object_todo_id') = 'string' THEN
          v_obj := (v_g->>'object_todo_id')::uuid;
        ELSE
          v_obj := NULL;
        END IF;
      END IF;
    END LOOP;
    IF v_hits IS DISTINCT FROM 1 THEN
      CONTINUE;
    END IF;
    SELECT EXISTS (
      SELECT 1
        FROM jsonb_array_elements(v_now.frontier->'gaps') g
       WHERE g.value->>'gap_kind' = v_kind
         AND (g.value->>'subject_todo_id')::uuid = v_sub
         AND (
           (v_obj IS NULL
            AND jsonb_typeof(g.value->'object_todo_id') IS DISTINCT FROM 'string')
           OR (v_obj IS NOT NULL
               AND jsonb_typeof(g.value->'object_todo_id') = 'string'
               AND (g.value->>'object_todo_id')::uuid = v_obj)))
      INTO v_cur;
    IF v_cur THEN
      gap_kind := v_kind;
      subject_todo_id := v_sub;
      object_todo_id := v_obj;
      event_id := v_ev.event_id;
      source_effect_id := v_ev.source_effect_id;
      RETURN NEXT;
    END IF;
  END LOOP;
END
$fn$;

CREATE OR REPLACE FUNCTION public.v13_replan_gap_insert(
  p_actor uuid,
  p_root uuid,
  p_gap_kind text,
  p_subject uuid,
  p_object uuid,
  p_expected_hash text
) RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_n integer;
  v_status text;
  v_nat text;
  v_source uuid;
  v_eid uuid;
  v_comp record;
  v_found boolean;
BEGIN
  IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
    RAISE EXCEPTION 'v13: replan gap: canonical';
  END IF;
  v_root := public.v13_plan_map_root(p_root);
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: replan gap: canonical';
  END IF;
  SELECT count(*) INTO v_n
    FROM public.sessions
   WHERE parent_session_id IS NULL;
  IF v_n > 1 THEN
    RAISE EXCEPTION 'v13: replan gap: not_single_tree';
  END IF;
  IF p_actor IS NULL THEN
    IF NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: replan gap: auth';
    END IF;
  ELSIF NOT public.v13_control_authorized(p_actor, v_root) THEN
    RAISE EXCEPTION 'v13: replan gap: auth';
  END IF;
  IF p_gap_kind IS DISTINCT FROM 'dangling_link'
     OR p_subject IS NULL THEN
    RAISE EXCEPTION 'v13: replan gap: canonical';
  END IF;
  v_nat := 'replan:' || v_root::text || ':' || p_gap_kind || ':'
           || p_subject::text || ':'
           || CASE WHEN p_object IS NULL THEN '' ELSE p_object::text END;
  v_source := public.v13_plan_apply_id(v_nat);
  IF EXISTS (SELECT 1 FROM public.effects WHERE effect_id = v_source) THEN
    RAISE EXCEPTION 'v13: replan gap: canonical';
  END IF;
  SELECT e.event_id INTO v_eid
    FROM public.events e
   WHERE e.session_id = v_root
     AND e.type = 'replan/required'
     AND e.source_effect_id = v_source
   ORDER BY e.seq
   LIMIT 1;
  IF v_eid IS NOT NULL THEN
    RETURN v_eid;
  END IF;
  IF public.v13_goal_lifecycle(v_root) = 'stopped' THEN
    RAISE EXCEPTION 'v13: replan gap: stopped';
  END IF;
  SELECT status INTO v_status
    FROM public.sessions
   WHERE session_id = v_root;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: replan gap: terminal';
  END IF;
  SELECT c.frontier, c.frontier_hash, c.omitted_count, c.omitted_complete
    INTO v_comp
    FROM public.v13_frontier_gap_compose(v_root, NULL, true) c;
  IF NOT v_comp.omitted_complete THEN
    RAISE EXCEPTION 'v13: replan gap: cap';
  END IF;
  SELECT EXISTS (
    SELECT 1
      FROM jsonb_array_elements(v_comp.frontier->'gaps') g
     WHERE g.value->>'gap_kind' = p_gap_kind
       AND (g.value->>'subject_todo_id')::uuid = p_subject
       AND (
         (p_object IS NULL AND jsonb_typeof(g.value->'object_todo_id') IS DISTINCT FROM 'string')
         OR (p_object IS NOT NULL
             AND jsonb_typeof(g.value->'object_todo_id') = 'string'
             AND (g.value->>'object_todo_id')::uuid = p_object)))
    INTO v_found;
  IF NOT v_found THEN
    RAISE EXCEPTION 'v13: replan gap: no_gap';
  END IF;
  IF p_expected_hash IS DISTINCT FROM v_comp.frontier_hash THEN
    RAISE EXCEPTION 'v13: replan gap: stale';
  END IF;
  v_eid := pg_catalog.gen_random_uuid();
  PERFORM public.v13_append_event(
    v_root, v_eid, 'replan/required',
    jsonb_build_object('schema_version', 1),
    v_source);
  RETURN v_eid;
END
$fn$;

REVOKE ALL ON FUNCTION public.v13_frontier_gap_compose(uuid, bigint, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_frontier_project(uuid, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_obligation_open(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v13_replan_gap_insert(uuid, uuid, text, uuid, uuid, text) FROM PUBLIC;
