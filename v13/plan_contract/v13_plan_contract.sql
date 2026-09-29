CREATE FUNCTION public.v13_plan_apply_id(p_text text) RETURNS uuid
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
  WITH raw AS (
    SELECT encode(public.digest(convert_to(p_text, 'UTF8'), 'sha256'), 'hex') AS h
  ), bits AS (
    SELECT h,
      lpad(to_hex((('x' || substr(h, 13, 2))::bit(8)::int & 15) | 128), 2, '0') AS b7,
      lpad(to_hex((('x' || substr(h, 17, 2))::bit(8)::int & 63) | 128), 2, '0') AS b9
    FROM raw
  )
  SELECT (
    substr(h2, 1, 8) || '-' || substr(h2, 9, 4) || '-' ||
    substr(h2, 13, 4) || '-' || substr(h2, 17, 4) || '-' ||
    substr(h2, 21, 12)
  )::uuid
  FROM (
    SELECT substr(h, 1, 12) || b7 || substr(h, 15, 2) || b9 || substr(h, 19, 14) AS h2
    FROM bits
  ) s
$$;

CREATE FUNCTION public.v13_plan_map_root(p_session uuid) RETURNS uuid
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_cur uuid;
  v_parent uuid;
  v_seen uuid[] := '{}';
BEGIN
  IF p_session IS NULL THEN
    RAISE EXCEPTION 'v13: plan writer: not_root';
  END IF;
  v_cur := p_session;
  LOOP
    IF v_cur = ANY (v_seen) THEN
      RAISE EXCEPTION 'v13: plan writer: not_root';
    END IF;
    v_seen := v_seen || v_cur;
    SELECT parent_session_id
      INTO v_parent
      FROM public.sessions
     WHERE session_id = v_cur;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'v13: plan writer: not_root';
    END IF;
    EXIT WHEN v_parent IS NULL;
    v_cur := v_parent;
  END LOOP;
  RETURN v_cur;
END
$fn$;

CREATE FUNCTION public.v13_plan_event_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $fn$
BEGIN
  IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: plan payload';
  END IF;
  IF NEW.type = 'plan/committed' THEN
    IF public.v13_json_keys(NEW.payload) IS DISTINCT FROM
       ARRAY['apply_id', 'call_kind', 'canonical', 'plan_id'] THEN
      RAISE EXCEPTION 'v13: plan payload';
    END IF;
  ELSIF NEW.type = 'todo/delta' THEN
    IF public.v13_json_keys(NEW.payload) IS DISTINCT FROM
       ARRAY['apply_id', 'call_kind', 'canonical', 'plan_id', 'todo_id'] THEN
      RAISE EXCEPTION 'v13: plan payload';
    END IF;
    IF jsonb_typeof(NEW.payload->'todo_id') NOT IN ('string', 'null') THEN
      RAISE EXCEPTION 'v13: plan payload';
    END IF;
    IF jsonb_typeof(NEW.payload->'todo_id') = 'string'
       AND NOT public.v13_canonical_uuid(NEW.payload->>'todo_id') THEN
      RAISE EXCEPTION 'v13: plan payload';
    END IF;
  END IF;
  IF jsonb_typeof(NEW.payload->'apply_id') IS DISTINCT FROM 'string'
     OR NOT public.v13_canonical_uuid(NEW.payload->>'apply_id')
     OR jsonb_typeof(NEW.payload->'call_kind') IS DISTINCT FROM 'string'
     OR jsonb_typeof(NEW.payload->'canonical') IS DISTINCT FROM 'object'
     OR jsonb_typeof(NEW.payload->'plan_id') IS DISTINCT FROM 'string'
     OR NOT public.v13_canonical_uuid(NEW.payload->>'plan_id') THEN
    RAISE EXCEPTION 'v13: plan payload';
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_v13_plan_event_guard
  BEFORE INSERT ON public.events
  FOR EACH ROW
  WHEN (NEW.type IN ('plan/committed', 'todo/delta'))
  EXECUTE FUNCTION public.v13_plan_event_guard();

CREATE FUNCTION public.v13_plan_prelude(p_spec jsonb) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
BEGIN
  IF p_spec IS NULL
     OR jsonb_typeof(p_spec) IS DISTINCT FROM 'object'
     OR NOT (p_spec ? 'version')
     OR jsonb_typeof(p_spec->'version') IS DISTINCT FROM 'number'
     OR (p_spec->>'version') !~ '^[1-9][0-9]*$' THEN
    RAISE EXCEPTION 'v13: plan prelude: version_required';
  END IF;
  BEGIN
    RETURN jsonb_build_object('version', (p_spec->>'version')::int);
  EXCEPTION
    WHEN numeric_value_out_of_range THEN
      RAISE EXCEPTION 'v13: plan prelude: version_required';
  END;
END
$fn$;

CREATE FUNCTION public.v13_plan_admit(p_actor uuid, p_session uuid) RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_status text;
BEGIN
  IF p_session IS NULL THEN
    RETURN false;
  END IF;
  SELECT status
    INTO v_status
    FROM public.sessions
   WHERE session_id = p_session;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RETURN false;
  END IF;
  IF public.v13_goal_lifecycle(p_session) = 'stopped' THEN
    RETURN false;
  END IF;
  IF p_actor IS NULL THEN
    RETURN public.v13_control_operator();
  END IF;
  RETURN public.v13_control_authorized(p_actor, p_session);
END
$fn$;

CREATE FUNCTION public.v13_plan_commit_entry(p_spec jsonb) RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_ver int;
BEGIN
  IF p_spec IS NULL
     OR jsonb_typeof(p_spec) IS DISTINCT FROM 'object'
     OR NOT (p_spec ? 'version')
     OR jsonb_typeof(p_spec->'version') IS DISTINCT FROM 'number'
     OR (p_spec->>'version') !~ '^[1-9][0-9]*$' THEN
    RAISE EXCEPTION 'v13: plan commit entry: version_required';
  END IF;
  BEGIN
    v_ver := (p_spec->>'version')::int;
  EXCEPTION
    WHEN numeric_value_out_of_range THEN
      RAISE EXCEPTION 'v13: plan commit entry: version_required';
  END;
  RETURN public.v13_open_session(p_spec);
END
$fn$;

CREATE FUNCTION public.v13_plan_todo_fold(p_root uuid)
RETURNS TABLE (
  todo_id uuid,
  todo_text text,
  text_hash text,
  task_class text,
  status text,
  due text,
  effect_id text,
  child_session_id text,
  quarantine jsonb
)
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_ev record;
  v_todo jsonb;
  v_can jsonb;
  v_state jsonb := '{}'::jsonb;
  v_id text;
  v_row jsonb;
  v_bind jsonb;
  v_key text;
BEGIN
  IF p_root IS NULL THEN
    RETURN;
  END IF;
  FOR v_ev IN
    SELECT e.seq, e.type, e.payload
      FROM public.events e
     WHERE e.session_id = p_root
       AND e.type IN ('plan/committed', 'todo/delta')
     ORDER BY e.seq
  LOOP
    v_can := v_ev.payload->'canonical';
    IF v_ev.type = 'plan/committed' THEN
      FOR v_todo IN SELECT value FROM jsonb_array_elements(v_can->'todos') LOOP
        IF v_todo->>'verb' = 'add_new' AND NOT (v_state ? (v_todo->>'todo_id')) THEN
          v_state := v_state || jsonb_build_object(
            v_todo->>'todo_id',
            jsonb_build_object(
              'text', v_todo->'text',
              'text_hash', v_todo->'text_hash',
              'task_class', v_todo->'task_class',
              'status', v_todo->'status',
              'due', CASE
                WHEN v_todo->'due' IS NULL THEN 'null'::jsonb
                ELSE v_todo->'due'
              END,
              'effect_id', 'null'::jsonb,
              'child_session_id', 'null'::jsonb,
              'quarantine', 'null'::jsonb));
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
      v_bind := v_can->'binding';
      IF jsonb_typeof(v_bind) = 'object' THEN
        IF v_bind ? 'clear_binding' THEN
          v_row := jsonb_set(v_row, '{effect_id}', 'null'::jsonb);
          v_row := jsonb_set(v_row, '{child_session_id}', 'null'::jsonb);
        ELSE
          IF jsonb_typeof(v_bind->'effect_id') = 'string' THEN
            v_row := jsonb_set(v_row, '{effect_id}', v_bind->'effect_id');
          END IF;
          IF jsonb_typeof(v_bind->'child_session_id') = 'string' THEN
            v_row := jsonb_set(v_row, '{child_session_id}', v_bind->'child_session_id');
          END IF;
        END IF;
      END IF;
      IF jsonb_typeof(v_can->'quarantine') = 'object' THEN
        v_row := jsonb_set(v_row, '{quarantine}', v_can->'quarantine');
      END IF;
      v_state := jsonb_set(v_state, ARRAY[v_id], v_row);
    END IF;
  END LOOP;
  FOR v_key IN SELECT jsonb_object_keys(v_state) LOOP
    v_row := v_state->v_key;
    todo_id := v_key::uuid;
    todo_text := v_row->>'text';
    text_hash := v_row->>'text_hash';
    task_class := v_row->>'task_class';
    status := v_row->>'status';
    due := CASE
      WHEN jsonb_typeof(v_row->'due') = 'string' THEN v_row->>'due'
      ELSE NULL
    END;
    effect_id := CASE
      WHEN jsonb_typeof(v_row->'effect_id') = 'string' THEN v_row->>'effect_id'
      ELSE NULL
    END;
    child_session_id := CASE
      WHEN jsonb_typeof(v_row->'child_session_id') = 'string' THEN v_row->>'child_session_id'
      ELSE NULL
    END;
    quarantine := CASE
      WHEN jsonb_typeof(v_row->'quarantine') = 'object' THEN v_row->'quarantine'
      ELSE NULL
    END;
    RETURN NEXT;
  END LOOP;
  RETURN;
END
$fn$;

CREATE FUNCTION public.v13_plan_link_edges(p_root uuid)
RETURNS TABLE (carrier uuid, on_kind text, target uuid, seq bigint)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
  SELECT (e.payload->'canonical'->>'todo_id')::uuid,
         e.payload->'canonical'->'link'->>'on',
         (e.payload->'canonical'->'link'->>'id')::uuid,
         e.seq
    FROM public.events e
   WHERE e.session_id = p_root
     AND e.type = 'todo/delta'
     AND e.payload->>'call_kind' = 'todo_delta'
     AND jsonb_typeof(e.payload->'canonical'->'link') = 'object'
   ORDER BY e.seq
$$;

CREATE FUNCTION public.v13_plan_current(p_session uuid) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_plan_id text;
  v_seq bigint;
  v_apply text;
  v_canonical jsonb;
BEGIN
  v_root := public.v13_plan_map_root(p_session);
  SELECT e.payload->>'plan_id',
         e.seq,
         e.payload->>'apply_id',
         e.payload->'canonical'
    INTO v_plan_id, v_seq, v_apply, v_canonical
    FROM public.events e
   WHERE e.session_id = v_root
     AND e.type = 'plan/committed'
     AND NOT EXISTS (
       SELECT 1
         FROM public.events u
        WHERE u.session_id = v_root
          AND u.type = 'user/message'
          AND u.seq > (e.payload->'canonical'->>'based_on_seq')::bigint)
   ORDER BY e.seq DESC, (e.payload->>'plan_id')::uuid DESC
   LIMIT 1;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  RETURN jsonb_build_object(
    'plan_id', v_plan_id,
    'seq', v_seq,
    'apply_id', v_apply,
    'canonical', v_canonical);
END
$fn$;

CREATE FUNCTION public.v13_plan_due_text_ok(p_due jsonb) RETURNS boolean
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_text text;
BEGIN
  IF p_due IS NULL OR jsonb_typeof(p_due) = 'null' THEN
    RETURN true;
  END IF;
  IF jsonb_typeof(p_due) IS DISTINCT FROM 'string' THEN
    RETURN false;
  END IF;
  v_text := p_due#>>'{}';
  IF v_text IS NULL OR v_text = '' THEN
    RETURN false;
  END IF;
  PERFORM v_text::timestamptz;
  RETURN true;
EXCEPTION
  WHEN OTHERS THEN
    RETURN false;
END
$fn$;

CREATE FUNCTION public.v13_plan_check_commit(
  p_root uuid,
  p_canonical jsonb,
  p_max_seq bigint
) RETURNS void
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_todo jsonb;
  v_prev uuid;
  v_id uuid;
  v_text text;
  v_hash text;
  v_class text;
  v_status text;
  v_verb text;
  v_fold record;
  v_due text;
BEGIN
  IF public.v13_json_keys(p_canonical) IS DISTINCT FROM
     ARRAY['based_on_seq', 'call_kind', 'schema_version', 'supersedes', 'todos']
     OR jsonb_typeof(p_canonical->'schema_version') IS DISTINCT FROM 'number'
     OR (p_canonical->'schema_version')::text IS DISTINCT FROM '1'
     OR p_canonical->>'call_kind' IS DISTINCT FROM 'plan_commit'
     OR jsonb_typeof(p_canonical->'based_on_seq') IS DISTINCT FROM 'number'
     OR (p_canonical->>'based_on_seq') !~ '^[0-9]+$'
     OR jsonb_typeof(p_canonical->'todos') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_canonical->'todos') < 1 THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  IF jsonb_typeof(p_canonical->'supersedes') = 'string' THEN
    IF NOT public.v13_canonical_uuid(p_canonical->>'supersedes') THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
  ELSIF jsonb_typeof(p_canonical->'supersedes') IS DISTINCT FROM 'null' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  BEGIN
    IF p_max_seq IS NULL
       OR (p_canonical->>'based_on_seq')::bigint IS DISTINCT FROM p_max_seq THEN
      RAISE EXCEPTION 'v13: plan writer: waterline';
    END IF;
  EXCEPTION
    WHEN numeric_value_out_of_range THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
  END;
  IF jsonb_typeof(p_canonical->'supersedes') = 'string'
     AND NOT EXISTS (
       SELECT 1
         FROM public.events e
        WHERE e.session_id = p_root
          AND e.type = 'plan/committed'
          AND e.payload->>'plan_id' = p_canonical->>'supersedes') THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  v_prev := NULL;
  FOR v_todo IN SELECT value FROM jsonb_array_elements(p_canonical->'todos') LOOP
    IF jsonb_typeof(v_todo) IS DISTINCT FROM 'object'
       OR public.v13_json_keys(v_todo) IS DISTINCT FROM
          ARRAY['due', 'status', 'task_class', 'text', 'text_hash', 'todo_id', 'verb']
       OR jsonb_typeof(v_todo->'todo_id') IS DISTINCT FROM 'string'
       OR NOT public.v13_canonical_uuid(v_todo->>'todo_id')
       OR jsonb_typeof(v_todo->'text') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_todo->'text_hash') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_todo->'task_class') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_todo->'status') IS DISTINCT FROM 'string'
       OR jsonb_typeof(v_todo->'verb') IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    IF jsonb_typeof(v_todo->'due') = 'string' THEN
      IF NOT public.v13_plan_due_text_ok(v_todo->'due') THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
      END IF;
    ELSIF jsonb_typeof(v_todo->'due') IS DISTINCT FROM 'null' THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    BEGIN
      v_id := (v_todo->>'todo_id')::uuid;
    EXCEPTION
      WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
    END;
    IF v_prev IS NOT NULL AND NOT (v_prev < v_id) THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    v_prev := v_id;
    v_text := v_todo->>'text';
    IF v_text = '' OR char_length(v_text) > 1024 THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    v_hash := encode(public.digest(convert_to(v_text, 'UTF8'), 'sha256'), 'hex');
    IF v_todo->>'text_hash' IS DISTINCT FROM v_hash THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    v_class := v_todo->>'task_class';
    v_status := v_todo->>'status';
    v_verb := v_todo->>'verb';
    IF v_class NOT IN (
         'advancement_task', 'continuous_monitor', 'user_gate', 'user_action', 'blocker')
       OR v_status NOT IN (
         'pending', 'runnable', 'waiting', 'blocked', 'done', 'dropped')
       OR v_verb NOT IN ('add_new', 'reuse') THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    SELECT *
      INTO v_fold
      FROM public.v13_plan_todo_fold(p_root) f
     WHERE f.todo_id = v_id;
    IF v_verb = 'add_new' THEN
      IF FOUND THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
      END IF;
      IF v_class = 'advancement_task' AND v_status NOT IN ('pending', 'runnable') THEN
        RAISE EXCEPTION 'v13: plan writer: bad_initial';
      END IF;
      IF v_class IN ('user_gate', 'user_action', 'blocker')
         AND v_status NOT IN ('pending', 'runnable', 'blocked') THEN
        RAISE EXCEPTION 'v13: plan writer: bad_initial';
      END IF;
      IF v_class = 'continuous_monitor' THEN
        IF v_status IS DISTINCT FROM 'waiting' THEN
          RAISE EXCEPTION 'v13: plan writer: bad_initial';
        END IF;
        IF jsonb_typeof(v_todo->'due') IS DISTINCT FROM 'string' THEN
          RAISE EXCEPTION 'v13: plan writer: empty_due';
        END IF;
      END IF;
    ELSE
      IF NOT FOUND OR v_fold.text_hash IS DISTINCT FROM v_hash THEN
        RAISE EXCEPTION 'v13: plan writer: reuse_hash';
      END IF;
      v_due := CASE
        WHEN jsonb_typeof(v_todo->'due') = 'string' THEN v_todo->>'due'
        ELSE NULL
      END;
      IF v_fold.task_class IS DISTINCT FROM v_class
         OR v_fold.status IS DISTINCT FROM v_status
         OR v_fold.due IS DISTINCT FROM v_due THEN
        RAISE EXCEPTION 'v13: plan writer: transition';
      END IF;
    END IF;
  END LOOP;
  RETURN;
END
$fn$;

CREATE FUNCTION public.v13_plan_check_delta(
  p_root uuid,
  p_canonical jsonb,
  p_now timestamptz
) RETURNS void
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_fold record;
  v_todo uuid;
  v_from text;
  v_to text;
  v_class text;
  v_bind jsonb;
  v_link jsonb;
  v_q jsonb;
  v_due text;
  v_target uuid;
  v_node uuid;
  v_next uuid;
  v_queue uuid[] := '{}';
  v_seen uuid[] := '{}';
  v_unresolved boolean;
  v_reenable boolean;
BEGIN
  IF public.v13_json_keys(p_canonical) IS DISTINCT FROM
     ARRAY['binding', 'call_kind', 'due', 'link', 'quarantine', 'schema_version',
           'status_from', 'status_to', 'text_hash', 'todo_id', 'verb']
     OR jsonb_typeof(p_canonical->'schema_version') IS DISTINCT FROM 'number'
     OR (p_canonical->'schema_version')::text IS DISTINCT FROM '1'
     OR p_canonical->>'call_kind' IS DISTINCT FROM 'todo_delta'
     OR p_canonical->>'verb' NOT IN ('update', 'link_successor')
     OR jsonb_typeof(p_canonical->'todo_id') IS DISTINCT FROM 'string'
     OR NOT public.v13_canonical_uuid(p_canonical->>'todo_id')
     OR jsonb_typeof(p_canonical->'status_from') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_canonical->'status_to') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_canonical->'text_hash') IS DISTINCT FROM 'string'
     OR p_canonical->>'status_from' NOT IN (
          'pending', 'runnable', 'waiting', 'blocked', 'done', 'dropped')
     OR p_canonical->>'status_to' NOT IN (
          'pending', 'runnable', 'waiting', 'blocked', 'done', 'dropped') THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  IF jsonb_typeof(p_canonical->'due') = 'string' THEN
    IF NOT public.v13_plan_due_text_ok(p_canonical->'due') THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
  ELSIF jsonb_typeof(p_canonical->'due') IS DISTINCT FROM 'null' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  v_bind := p_canonical->'binding';
  IF jsonb_typeof(v_bind) = 'object' THEN
    IF public.v13_json_keys(v_bind) = ARRAY['clear_binding'] THEN
      IF v_bind->'clear_binding' IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
      END IF;
    ELSIF public.v13_json_keys(v_bind) = ARRAY['child_session_id', 'effect_id'] THEN
      IF jsonb_typeof(v_bind->'effect_id') = 'string' THEN
        IF NOT public.v13_canonical_uuid(v_bind->>'effect_id') THEN
          RAISE EXCEPTION 'v13: plan writer: canonical';
        END IF;
      ELSIF jsonb_typeof(v_bind->'effect_id') IS DISTINCT FROM 'null' THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
      END IF;
      IF jsonb_typeof(v_bind->'child_session_id') = 'string' THEN
        IF NOT public.v13_canonical_uuid(v_bind->>'child_session_id') THEN
          RAISE EXCEPTION 'v13: plan writer: canonical';
        END IF;
      ELSIF jsonb_typeof(v_bind->'child_session_id') IS DISTINCT FROM 'null' THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
      END IF;
    ELSE
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
  ELSIF jsonb_typeof(v_bind) IS DISTINCT FROM 'null' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  v_link := p_canonical->'link';
  IF jsonb_typeof(v_link) = 'object' THEN
    IF public.v13_json_keys(v_link) IS DISTINCT FROM ARRAY['id', 'on']
       OR jsonb_typeof(v_link->'on') IS DISTINCT FROM 'string'
       OR v_link->>'on' NOT IN ('successor', 'resume')
       OR jsonb_typeof(v_link->'id') IS DISTINCT FROM 'string'
       OR NOT public.v13_canonical_uuid(v_link->>'id') THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
  ELSIF jsonb_typeof(v_link) IS DISTINCT FROM 'null' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  IF p_canonical->>'verb' = 'link_successor'
     AND jsonb_typeof(v_link) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  v_q := p_canonical->'quarantine';
  IF jsonb_typeof(v_q) = 'object' THEN
    IF public.v13_json_keys(v_q) IS DISTINCT FROM ARRAY['cleared', 'effect_id']
       OR jsonb_typeof(v_q->'effect_id') IS DISTINCT FROM 'string'
       OR NOT public.v13_canonical_uuid(v_q->>'effect_id')
       OR jsonb_typeof(v_q->'cleared') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
  ELSIF jsonb_typeof(v_q) IS DISTINCT FROM 'null' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  BEGIN
    v_todo := (p_canonical->>'todo_id')::uuid;
  EXCEPTION
    WHEN invalid_text_representation THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
  END;
  SELECT *
    INTO v_fold
    FROM public.v13_plan_todo_fold(p_root) f
   WHERE f.todo_id = v_todo;
  IF NOT FOUND OR v_fold.text_hash IS DISTINCT FROM p_canonical->>'text_hash' THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  v_from := p_canonical->>'status_from';
  v_to := p_canonical->>'status_to';
  v_class := v_fold.task_class;
  IF v_from IS DISTINCT FROM v_fold.status THEN
    RAISE EXCEPTION 'v13: plan writer: transition';
  END IF;
  v_unresolved := v_fold.quarantine IS NOT NULL
    AND jsonb_typeof(v_fold.quarantine) = 'object'
    AND v_fold.quarantine->'cleared' IS DISTINCT FROM 'true'::jsonb;
  v_reenable := p_canonical->>'verb' = 'update'
    AND v_from = 'blocked'
    AND v_to = 'runnable'
    AND jsonb_typeof(v_q) = 'object'
    AND v_q->'cleared' = 'true'::jsonb
    AND v_unresolved
    AND v_q->>'effect_id' = v_fold.quarantine->>'effect_id'
    AND jsonb_typeof(v_bind) = 'object'
    AND public.v13_json_keys(v_bind) = ARRAY['clear_binding']
    AND v_bind->'clear_binding' = 'true'::jsonb;
  IF v_from = v_to THEN
    IF v_from IN ('done', 'dropped') THEN
      RAISE EXCEPTION 'v13: plan writer: transition';
    END IF;
    IF jsonb_typeof(v_bind) IS DISTINCT FROM 'object'
       AND jsonb_typeof(v_link) IS DISTINCT FROM 'object'
       AND jsonb_typeof(v_q) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: plan writer: transition';
    END IF;
  ELSIF NOT (
    (v_from = 'pending' AND v_to IN ('runnable', 'dropped'))
    OR (v_from = 'runnable' AND v_to IN ('waiting', 'blocked', 'done', 'dropped'))
    OR (v_from = 'waiting' AND v_to IN ('runnable', 'blocked', 'dropped'))
    OR (v_from = 'blocked' AND v_to IN ('runnable', 'dropped'))
  ) THEN
    RAISE EXCEPTION 'v13: plan writer: transition';
  END IF;
  IF v_from = 'waiting' AND v_to = 'runnable' THEN
    IF v_class IS DISTINCT FROM 'continuous_monitor' THEN
      RAISE EXCEPTION 'v13: plan writer: transition';
    END IF;
    IF v_fold.due IS NULL OR v_fold.due = '' THEN
      RAISE EXCEPTION 'v13: plan writer: empty_due';
    END IF;
    IF p_now IS NULL OR v_fold.due::timestamptz > p_now THEN
      RAISE EXCEPTION 'v13: plan writer: transition';
    END IF;
    IF jsonb_typeof(p_canonical->'due') = 'string'
       AND (p_canonical->'due'#>>'{}') IS DISTINCT FROM v_fold.due THEN
      RAISE EXCEPTION 'v13: plan writer: transition';
    END IF;
  END IF;
  IF v_class = 'continuous_monitor'
     AND v_from = 'runnable'
     AND v_to = 'waiting'
     AND jsonb_typeof(p_canonical->'due') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'v13: plan writer: empty_due';
  END IF;
  IF jsonb_typeof(v_bind) = 'object'
     AND public.v13_json_keys(v_bind) = ARRAY['child_session_id', 'effect_id']
     AND v_fold.effect_id IS NULL
     AND v_fold.child_session_id IS NULL
     AND NOT (v_from = 'runnable' AND v_to = 'runnable') THEN
    RAISE EXCEPTION 'v13: plan writer: transition';
  END IF;
  IF jsonb_typeof(v_q) = 'object' AND v_q->'cleared' = 'false'::jsonb THEN
    IF NOT (
      (v_from = 'pending' AND v_to = 'pending')
      OR (v_from = 'blocked' AND v_to = 'blocked')
      OR (v_from = 'runnable' AND v_to = 'blocked')
    ) THEN
      RAISE EXCEPTION 'v13: plan writer: transition';
    END IF;
  END IF;
  IF jsonb_typeof(v_q) = 'object' AND v_q->'cleared' = 'true'::jsonb AND NOT v_reenable THEN
    RAISE EXCEPTION 'v13: plan writer: transition';
  END IF;
  IF v_unresolved AND v_to = 'runnable' AND NOT v_reenable THEN
    RAISE EXCEPTION 'v13: plan writer: transition';
  END IF;
  IF jsonb_typeof(v_link) = 'object' THEN
    BEGIN
      v_target := (v_link->>'id')::uuid;
    EXCEPTION
      WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'v13: plan writer: canonical';
    END;
    IF v_target = v_todo THEN
      RAISE EXCEPTION 'v13: plan writer: cycle';
    END IF;
    IF NOT EXISTS (
      SELECT 1
        FROM public.v13_plan_todo_fold(p_root) f
       WHERE f.todo_id = v_target) THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    v_queue := ARRAY[v_target];
    v_seen := ARRAY[v_target];
    WHILE coalesce(array_length(v_queue, 1), 0) > 0 LOOP
      v_node := v_queue[1];
      SELECT coalesce(array_agg(x ORDER BY ord), '{}'::uuid[])
        INTO v_queue
        FROM unnest(v_queue) WITH ORDINALITY AS t(x, ord)
       WHERE ord > 1;
      FOR v_next IN
        SELECT e.target
          FROM public.v13_plan_link_edges(p_root) e
         WHERE e.carrier = v_node
         ORDER BY e.seq
      LOOP
        IF v_next = v_todo THEN
          RAISE EXCEPTION 'v13: plan writer: cycle';
        END IF;
        IF NOT v_next = ANY (v_seen) THEN
          v_seen := v_seen || v_next;
          v_queue := v_queue || v_next;
        END IF;
      END LOOP;
    END LOOP;
  END IF;
  RETURN;
END
$fn$;

CREATE FUNCTION public.v13_plan_writer(
  p_actor uuid,
  p_session uuid,
  p_apply_id uuid,
  p_call_kind text,
  p_canonical jsonb,
  p_now timestamptz
) RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_status text;
  v_life text;
  v_max bigint;
  v_plan_id text;
  v_stored jsonb;
  v_ids jsonb;
  v_payload jsonb;
  v_n int;
BEGIN
  IF p_apply_id IS NULL
     OR p_call_kind IS NULL
     OR p_canonical IS NULL
     OR jsonb_typeof(p_canonical) IS DISTINCT FROM 'object'
     OR p_call_kind IS DISTINCT FROM p_canonical->>'call_kind'
     OR p_call_kind NOT IN ('plan_commit', 'todo_delta') THEN
    RAISE EXCEPTION 'v13: plan writer: canonical';
  END IF;
  v_root := public.v13_plan_map_root(p_session);
  PERFORM 1
     FROM public.sessions
    WHERE session_id = v_root
      FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: plan writer: not_root';
  END IF;
  IF p_actor IS NULL THEN
    IF NOT public.v13_control_operator() THEN
      RAISE EXCEPTION 'v13: plan writer: auth';
    END IF;
  ELSIF NOT public.v13_control_authorized(p_actor, v_root) THEN
    RAISE EXCEPTION 'v13: plan writer: auth';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM public.events
     WHERE session_id = v_root
       AND type IN ('plan/committed', 'todo/delta')
       AND payload->>'apply_id' = p_apply_id::text
       AND (
         payload->>'call_kind' IS DISTINCT FROM p_call_kind
         OR payload->'canonical' IS DISTINCT FROM p_canonical)) THEN
    RAISE EXCEPTION 'v13: plan writer: replay_conflict';
  END IF;
  IF EXISTS (
    SELECT 1
      FROM public.events
     WHERE session_id = v_root
       AND type IN ('plan/committed', 'todo/delta')
       AND payload->>'apply_id' = p_apply_id::text) THEN
    SELECT e.payload->>'plan_id', e.payload->'canonical'
      INTO v_plan_id, v_stored
      FROM public.events e
     WHERE e.session_id = v_root
       AND e.type IN ('plan/committed', 'todo/delta')
       AND e.payload->>'apply_id' = p_apply_id::text
     ORDER BY e.seq
     LIMIT 1;
    IF p_call_kind = 'plan_commit' THEN
      SELECT coalesce(jsonb_agg(elem->>'todo_id' ORDER BY ordinality), '[]'::jsonb)
        INTO v_ids
        FROM jsonb_array_elements(v_stored->'todos') WITH ORDINALITY AS t(elem, ordinality);
    ELSE
      v_ids := jsonb_build_array(v_stored->>'todo_id');
    END IF;
    RETURN jsonb_build_object(
      'plan_id', v_plan_id,
      'todo_ids', v_ids,
      'replayed', true);
  END IF;
  SELECT status INTO v_status
    FROM public.sessions
   WHERE session_id = v_root;
  v_life := public.v13_goal_lifecycle(v_root);
  IF v_life = 'stopped' THEN
    RAISE EXCEPTION 'v13: plan writer: stopped';
  END IF;
  IF v_status IN ('completed', 'failed', 'cancelled') THEN
    RAISE EXCEPTION 'v13: plan writer: terminal';
  END IF;
  IF p_call_kind = 'plan_commit' THEN
    SELECT max(seq) INTO v_max
      FROM public.events
     WHERE session_id = v_root;
    PERFORM public.v13_plan_check_commit(v_root, p_canonical, v_max);
    v_plan_id := pg_catalog.gen_random_uuid()::text;
    v_payload := jsonb_build_object(
      'apply_id', p_apply_id::text,
      'call_kind', p_call_kind,
      'canonical', p_canonical,
      'plan_id', v_plan_id);
    PERFORM public.v13_append_event(
      v_root, pg_catalog.gen_random_uuid(), 'plan/committed', v_payload, NULL);
    v_n := jsonb_array_length(p_canonical->'todos');
    IF v_n = 1 THEN
      v_payload := v_payload || jsonb_build_object(
        'todo_id', p_canonical->'todos'->0->'todo_id');
    ELSE
      v_payload := v_payload || jsonb_build_object('todo_id', 'null'::jsonb);
    END IF;
    PERFORM public.v13_append_event(
      v_root, pg_catalog.gen_random_uuid(), 'todo/delta', v_payload, NULL);
    SELECT coalesce(jsonb_agg(elem->>'todo_id' ORDER BY ordinality), '[]'::jsonb)
      INTO v_ids
      FROM jsonb_array_elements(p_canonical->'todos') WITH ORDINALITY AS t(elem, ordinality);
  ELSE
    PERFORM public.v13_plan_check_delta(v_root, p_canonical, p_now);
    SELECT e.payload->>'plan_id'
      INTO v_plan_id
      FROM public.events e
     WHERE e.session_id = v_root
       AND e.type = 'plan/committed'
       AND EXISTS (
         SELECT 1
           FROM jsonb_array_elements(e.payload->'canonical'->'todos') elem
          WHERE elem->>'todo_id' = p_canonical->>'todo_id')
     ORDER BY e.seq DESC
     LIMIT 1;
    IF v_plan_id IS NULL OR NOT public.v13_canonical_uuid(v_plan_id) THEN
      RAISE EXCEPTION 'v13: plan writer: canonical';
    END IF;
    v_payload := jsonb_build_object(
      'apply_id', p_apply_id::text,
      'call_kind', p_call_kind,
      'canonical', p_canonical,
      'plan_id', v_plan_id,
      'todo_id', to_jsonb(p_canonical->>'todo_id'));
    PERFORM public.v13_append_event(
      v_root, pg_catalog.gen_random_uuid(), 'todo/delta', v_payload, NULL);
    v_ids := jsonb_build_array(p_canonical->>'todo_id');
  END IF;
  RETURN jsonb_build_object(
    'plan_id', v_plan_id,
    'todo_ids', v_ids,
    'replayed', false);
END
$fn$;
