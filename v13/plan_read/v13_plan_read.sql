CREATE FUNCTION public.v13_plan_inventory(p_session uuid) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_row record;
  v_items jsonb := '[]'::jsonb;
  v_examined int := 0;
  v_omitted int := 0;
  v_text text;
BEGIN
  FOR v_row IN
    SELECT f.todo_id,
           f.todo_text,
           f.text_hash,
           f.task_class,
           f.status,
           f.due,
           f.effect_id,
           f.child_session_id,
           f.quarantine
      FROM (SELECT public.v13_plan_current(p_session) AS cur) s
      JOIN LATERAL pg_catalog.jsonb_array_elements(s.cur->'canonical'->'todos') elem
        ON s.cur IS NOT NULL
      JOIN public.v13_plan_todo_fold(public.v13_plan_map_root(p_session)) f
        ON f.todo_id = (elem->>'todo_id')::uuid
     ORDER BY (s.cur->>'seq')::bigint, f.todo_id
  LOOP
    IF v_examined < 32 THEN
      v_text := pg_catalog.left(v_row.todo_text, 1024);
      v_items := v_items || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'todo_id', v_row.todo_id::text,
        'text', v_text,
        'text_hash', v_row.text_hash,
        'task_class', v_row.task_class,
        'status', v_row.status,
        'due', CASE
          WHEN v_row.due IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.due)
        END,
        'effect_id', CASE
          WHEN v_row.effect_id IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.effect_id)
        END,
        'child_session_id', CASE
          WHEN v_row.child_session_id IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.child_session_id)
        END,
        'quarantine', CASE
          WHEN v_row.quarantine IS NULL THEN 'null'::jsonb
          ELSE v_row.quarantine
        END));
      v_examined := v_examined + 1;
    ELSE
      v_omitted := 1;
      EXIT;
    END IF;
  END LOOP;
  RETURN pg_catalog.jsonb_build_object(
    'schema_version', 1,
    'rows_examined', v_examined,
    'rows_returned', v_examined,
    'omitted_count', v_omitted,
    'omitted_complete', v_omitted = 0,
    'items', v_items);
END
$fn$;

CREATE FUNCTION public.v13_plan_horizon(p_session uuid) RETURNS jsonb
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $fn$
DECLARE
  v_root uuid;
  v_cur jsonb;
  v_row record;
  v_items jsonb := '[]'::jsonb;
  v_relations jsonb := '[]'::jsonb;
  v_gaps jsonb := '[]'::jsonb;
  v_item_examined int := 0;
  v_item_omitted int := 0;
  v_rel_examined int := 0;
  v_rel_omitted int := 0;
  v_gap_examined int := 0;
  v_gap_omitted int := 0;
  v_text text;
BEGIN
  v_cur := public.v13_plan_current(p_session);
  IF v_cur IS NULL THEN
    RETURN pg_catalog.jsonb_build_object(
      'schema_version', 1,
      'items', pg_catalog.jsonb_build_object(
        'rows_examined', 0, 'rows_returned', 0,
        'omitted_count', 0, 'omitted_complete', true, 'rows', '[]'::jsonb),
      'relations', pg_catalog.jsonb_build_object(
        'rows_examined', 0, 'rows_returned', 0,
        'omitted_count', 0, 'omitted_complete', true, 'rows', '[]'::jsonb),
      'gaps', pg_catalog.jsonb_build_object(
        'rows_examined', 0, 'rows_returned', 0,
        'omitted_count', 0, 'omitted_complete', true, 'rows', '[]'::jsonb));
  END IF;
  v_root := public.v13_plan_map_root(p_session);
  FOR v_row IN
    SELECT f.todo_id, f.todo_text, f.text_hash, f.task_class, f.status, f.due
      FROM pg_catalog.jsonb_array_elements(v_cur->'canonical'->'todos') elem
      JOIN public.v13_plan_todo_fold(v_root) f
        ON f.todo_id = (elem->>'todo_id')::uuid
     WHERE f.status NOT IN ('done', 'dropped')
     ORDER BY (v_cur->>'seq')::bigint, f.todo_id
  LOOP
    IF v_item_examined < 4 THEN
      v_text := pg_catalog.left(v_row.todo_text, 1024);
      v_items := v_items || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'todo_id', v_row.todo_id::text,
        'text', v_text,
        'text_hash', v_row.text_hash,
        'task_class', v_row.task_class,
        'status', v_row.status,
        'due', CASE
          WHEN v_row.due IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.due)
        END));
      v_item_examined := v_item_examined + 1;
    ELSE
      v_item_omitted := 1;
      EXIT;
    END IF;
  END LOOP;
  FOR v_row IN
    SELECT e.carrier, e.on_kind, e.target, e.seq
      FROM public.v13_plan_link_edges(v_root) e
     WHERE e.on_kind IN ('successor', 'resume')
       AND e.carrier IN (
         SELECT (elem->>'todo_id')::uuid
           FROM pg_catalog.jsonb_array_elements(v_cur->'canonical'->'todos') elem)
     ORDER BY e.seq, e.carrier, e.target
  LOOP
    IF v_rel_examined < 4 THEN
      v_relations := v_relations || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'carrier', v_row.carrier::text,
        'on', v_row.on_kind,
        'target', v_row.target::text,
        'seq', v_row.seq));
      v_rel_examined := v_rel_examined + 1;
    ELSE
      v_rel_omitted := 1;
      EXIT;
    END IF;
  END LOOP;
  FOR v_row IN
    SELECT g.kind, g.seq, g.sort_id, g.todo_id, g.carrier, g.on_kind, g.target
      FROM (
        SELECT 'blocker'::text AS kind,
               (v_cur->>'seq')::bigint AS seq,
               f.todo_id AS sort_id,
               f.todo_id,
               NULL::uuid AS carrier,
               NULL::text AS on_kind,
               NULL::uuid AS target
          FROM pg_catalog.jsonb_array_elements(v_cur->'canonical'->'todos') elem
          JOIN public.v13_plan_todo_fold(v_root) f
            ON f.todo_id = (elem->>'todo_id')::uuid
         WHERE f.task_class = 'blocker'
           AND f.status NOT IN ('done', 'dropped')
        UNION ALL
        SELECT 'edge'::text,
               e.seq,
               e.target,
               NULL::uuid,
               e.carrier,
               e.on_kind,
               e.target
          FROM public.v13_plan_link_edges(v_root) e
         WHERE e.on_kind IN ('successor', 'resume')
           AND e.carrier IN (
             SELECT (elem->>'todo_id')::uuid
               FROM pg_catalog.jsonb_array_elements(v_cur->'canonical'->'todos') elem)
           AND e.target NOT IN (
             SELECT (elem->>'todo_id')::uuid
               FROM pg_catalog.jsonb_array_elements(v_cur->'canonical'->'todos') elem)
      ) g
     ORDER BY g.seq, g.sort_id
  LOOP
    IF v_gap_examined < 1 THEN
      v_gaps := v_gaps || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'kind', v_row.kind,
        'todo_id', CASE
          WHEN v_row.todo_id IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.todo_id::text)
        END,
        'carrier', CASE
          WHEN v_row.carrier IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.carrier::text)
        END,
        'on', CASE
          WHEN v_row.on_kind IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.on_kind)
        END,
        'target', CASE
          WHEN v_row.target IS NULL THEN 'null'::jsonb
          ELSE pg_catalog.to_jsonb(v_row.target::text)
        END,
        'seq', v_row.seq));
      v_gap_examined := v_gap_examined + 1;
    ELSE
      v_gap_omitted := 1;
      EXIT;
    END IF;
  END LOOP;
  RETURN pg_catalog.jsonb_build_object(
    'schema_version', 1,
    'items', pg_catalog.jsonb_build_object(
      'rows_examined', v_item_examined,
      'rows_returned', v_item_examined,
      'omitted_count', v_item_omitted,
      'omitted_complete', v_item_omitted = 0,
      'rows', v_items),
    'relations', pg_catalog.jsonb_build_object(
      'rows_examined', v_rel_examined,
      'rows_returned', v_rel_examined,
      'omitted_count', v_rel_omitted,
      'omitted_complete', v_rel_omitted = 0,
      'rows', v_relations),
    'gaps', pg_catalog.jsonb_build_object(
      'rows_examined', v_gap_examined,
      'rows_returned', v_gap_examined,
      'omitted_count', v_gap_omitted,
      'omitted_complete', v_gap_omitted = 0,
      'rows', v_gaps));
END
$fn$;
