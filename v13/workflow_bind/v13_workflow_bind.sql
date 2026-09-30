-- C1 policy row and C2 contract row are the same v13_policies row.
-- name=workflow_template version=1 active.
-- C1: layers.assertion / assembly / judgment / workflow, four non-empty texts.
-- C2: labels, allowed_tools, parent_tools, chain.
-- Subset delivery is not this row. Phase B delivers the tool subset.
-- A label stays in this row. It does not open explore and does not touch the tools catalog.
-- C3: one workflow/pointer per child session, written only by v13_child_pointer.
-- Production caller is v13/real_chain/chain.py, not this directory.

INSERT INTO public.v13_policies (name, version, value, active) VALUES (
  'workflow_template',
  1,
  $policy${
    "schema_version": 1,
    "layers": {
      "assertion": "Bound facts are the task text on the selected todo and the pointer fields parent_session_id, root_session_id, todo_id, and up_to_seq. Do not invent a parent transcript. Do not treat a label as permission to widen tools.",
      "assembly": "Keep assertion, assembly, judgment, and workflow as four separate segments. Do not join them into one prompt line. Use the inventory, the horizon, and the single pointer. Do not copy parent events into the child.",
      "judgment": "This layer is prose. It does not execute a gate and it does not select rows from any other template table.",
      "workflow": "Run one advancement task, one child, one bounded read, then archive on the root after the excerpt is stored. A label does not open an explore session. Leave tool flags as loaded. The child does not write plan events."
    },
    "labels": ["read_only"],
    "allowed_tools": ["read_pi", "read_file_swift", "read_file_py", "read_duck"],
    "parent_tools": ["spawn_subsession"],
    "chain": "first_real_chain"
  }$policy$::jsonb,
  true
);

CREATE FUNCTION public.v13_workflow_resolve(p_name text, p_version int)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_value jsonb;
  v_active boolean;
  v_layers jsonb;
BEGIN
  SELECT value, active
    INTO v_value, v_active
    FROM public.v13_policies
   WHERE name = p_name
     AND version = p_version;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: workflow resolve: missing';
  END IF;
  IF v_active IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'v13: workflow resolve: inactive';
  END IF;
  IF jsonb_typeof(v_value) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_value) IS DISTINCT FROM
        ARRAY['allowed_tools', 'chain', 'labels', 'layers', 'parent_tools', 'schema_version']
     OR jsonb_typeof(v_value->'schema_version') IS DISTINCT FROM 'number'
     OR (v_value->>'schema_version') IS DISTINCT FROM '1'
     OR jsonb_typeof(v_value->'layers') IS DISTINCT FROM 'object'
     OR public.v13_json_keys(v_value->'layers') IS DISTINCT FROM
        ARRAY['assembly', 'assertion', 'judgment', 'workflow']
     OR jsonb_typeof(v_value->'labels') IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_value->'labels') > 1
     OR EXISTS (
          SELECT 1
            FROM jsonb_array_elements_text(v_value->'labels') AS lab
           WHERE lab IS DISTINCT FROM 'read_only')
     OR jsonb_typeof(v_value->'allowed_tools') IS DISTINCT FROM 'array'
     OR v_value->'allowed_tools' IS DISTINCT FROM
        '["read_pi","read_file_swift","read_file_py","read_duck"]'::jsonb
     OR jsonb_typeof(v_value->'parent_tools') IS DISTINCT FROM 'array'
     OR v_value->'parent_tools' IS DISTINCT FROM '["spawn_subsession"]'::jsonb
     OR jsonb_typeof(v_value->'chain') IS DISTINCT FROM 'string'
     OR v_value->>'chain' IS DISTINCT FROM 'first_real_chain'
     OR jsonb_typeof(v_value->'layers'->'assertion') IS DISTINCT FROM 'string'
     OR coalesce(btrim(v_value->'layers'->>'assertion'), '') = ''
     OR jsonb_typeof(v_value->'layers'->'assembly') IS DISTINCT FROM 'string'
     OR coalesce(btrim(v_value->'layers'->>'assembly'), '') = ''
     OR jsonb_typeof(v_value->'layers'->'judgment') IS DISTINCT FROM 'string'
     OR coalesce(btrim(v_value->'layers'->>'judgment'), '') = ''
     OR jsonb_typeof(v_value->'layers'->'workflow') IS DISTINCT FROM 'string'
     OR coalesce(btrim(v_value->'layers'->>'workflow'), '') = '' THEN
    RAISE EXCEPTION 'v13: workflow resolve: canonical';
  END IF;
  v_layers := v_value->'layers';
  RETURN jsonb_build_object(
    'assertion', v_layers->>'assertion',
    'assembly', v_layers->>'assembly',
    'judgment', v_layers->>'judgment',
    'workflow', v_layers->>'workflow');
END
$fn$;

DO $seed$
BEGIN
  PERFORM public.v13_workflow_resolve('workflow_template', 1);
END
$seed$;

CREATE FUNCTION public.v13_workflow_pointer_guard() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $fn$
BEGIN
  IF NEW.source_effect_id IS NOT NULL
     OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
     OR public.v13_json_keys(NEW.payload) IS DISTINCT FROM
        ARRAY['parent_session_id', 'root_session_id', 'schema_version', 'todo_id', 'up_to_seq']
     OR NOT public.v13_json_int_ok(NEW.payload->'schema_version', 1)
     OR (NEW.payload->>'schema_version') IS DISTINCT FROM '1'
     OR NOT public.v13_canonical_uuid(NEW.payload->>'parent_session_id')
     OR NOT public.v13_canonical_uuid(NEW.payload->>'root_session_id')
     OR NOT public.v13_canonical_uuid(NEW.payload->>'todo_id')
     OR NOT public.v13_json_int_ok(NEW.payload->'up_to_seq', 9223372036854775807) THEN
    RAISE EXCEPTION 'v13: workflow pointer: payload';
  END IF;
  RETURN NEW;
END
$fn$;

CREATE TRIGGER trg_v13_workflow_pointer_guard
  BEFORE INSERT ON public.events
  FOR EACH ROW
  WHEN (NEW.type = 'workflow/pointer')
  EXECUTE FUNCTION public.v13_workflow_pointer_guard();

CREATE UNIQUE INDEX ux_events_workflow_pointer
  ON public.events (session_id)
  WHERE type = 'workflow/pointer';

CREATE FUNCTION public.v13_child_pointer(
  p_child uuid,
  p_parent uuid,
  p_root uuid,
  p_todo uuid,
  p_up_to_seq bigint)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_parent uuid;
  v_status text;
  v_root uuid;
  v_payload jsonb;
  v_event uuid;
  v_stored jsonb;
  v_life text;
BEGIN
  IF p_child IS NULL OR p_parent IS NULL OR p_root IS NULL
     OR p_todo IS NULL OR p_up_to_seq IS NULL OR p_up_to_seq < 0 THEN
    RAISE EXCEPTION 'v13: workflow pointer: payload';
  END IF;
  SELECT parent_session_id, status
    INTO v_parent, v_status
    FROM public.sessions
   WHERE session_id = p_child
     FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'v13: workflow pointer: missing';
  END IF;
  IF v_parent IS NULL OR v_parent IS DISTINCT FROM p_parent THEN
    RAISE EXCEPTION 'v13: workflow pointer: not_child';
  END IF;
  v_root := public.v13_plan_map_root(p_child);
  IF v_root IS DISTINCT FROM p_root THEN
    RAISE EXCEPTION 'v13: workflow pointer: not_child';
  END IF;
  v_payload := jsonb_build_object(
    'schema_version', 1,
    'parent_session_id', p_parent::text,
    'root_session_id', p_root::text,
    'todo_id', p_todo::text,
    'up_to_seq', p_up_to_seq);
  SELECT event_id, payload
    INTO v_event, v_stored
    FROM public.events
   WHERE session_id = p_child
     AND type = 'workflow/pointer';
  IF FOUND THEN
    IF v_stored IS DISTINCT FROM v_payload THEN
      RAISE EXCEPTION 'v13: workflow pointer: replay_conflict';
    END IF;
  ELSE
    v_life := public.v13_goal_lifecycle(p_child);
    IF v_life = 'stopped' THEN
      RAISE EXCEPTION 'v13: workflow pointer: stopped';
    END IF;
    IF v_status IN ('completed', 'failed', 'cancelled') THEN
      RAISE EXCEPTION 'v13: workflow pointer: terminal';
    END IF;
    v_event := pg_catalog.gen_random_uuid();
  END IF;
  BEGIN
    PERFORM public.v13_append_event(
      p_child, v_event, 'workflow/pointer', v_payload);
  EXCEPTION
    WHEN unique_violation THEN
      SELECT event_id, payload
        INTO v_event, v_stored
        FROM public.events
       WHERE session_id = p_child
         AND type = 'workflow/pointer';
      IF FOUND AND v_stored = v_payload THEN
        RETURN v_event;
      END IF;
      RAISE EXCEPTION 'v13: workflow pointer: replay_conflict';
  END;
  RETURN v_event;
END
$fn$;
