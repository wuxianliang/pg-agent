-- ============================================================
-- PG-Agent v4 · workbench core (W2)
--
-- TEMP VIEW resolvers scoped to the current backend's
-- pg_my_temp_schema(). Prompt overlay concatenates
-- make_system_prompt() + render_plugin_tools().
-- ============================================================

CREATE OR REPLACE FUNCTION _wb_normalize_temp_view_name(p_name text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_name IS NULL THEN NULL
        WHEN trim(p_name) ~ '^[A-Za-z_][A-Za-z0-9_]*$'
             AND octet_length(trim(p_name)) <= 63
        THEN trim(p_name)
    END
$$;

CREATE OR REPLACE FUNCTION _wb_temp_view_oid(p_name text)
RETURNS oid
LANGUAGE sql STABLE AS $$
    -- pg_my_temp_schema()=0 means this backend has never created temp objects.
    SELECT c.oid
      FROM pg_class c
     WHERE pg_my_temp_schema() <> 0
       AND c.relnamespace = pg_my_temp_schema()
       AND c.relkind = 'v'
       AND c.relname = _wb_normalize_temp_view_name(p_name)
     LIMIT 1
$$;

CREATE OR REPLACE FUNCTION _wb_temp_view_columns(p_relid oid)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'ordinal', a.attnum,
               'name',    a.attname,
               'type',    format_type(a.atttypid, a.atttypmod)
           ) ORDER BY a.attnum), '[]'::jsonb)
      FROM pg_attribute a
     WHERE a.attrelid = p_relid
       AND a.attnum > 0
       AND NOT a.attisdropped
$$;

CREATE OR REPLACE FUNCTION prepare_llm_request(p_run_id text)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_run    agent_runs;
    v_steps  jsonb;
    v_msgs   jsonb;
    v_system text;
    v_used   int;
BEGIN
    SELECT * INTO v_run FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run_id: %', p_run_id;
    END IF;

    SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                              ORDER BY seq), '[]'::jsonb),
           count(*) FILTER (WHERE kind='llm')
      INTO v_steps, v_used
      FROM agent_steps WHERE run_id = p_run_id;

    v_system := make_system_prompt(COALESCE(v_run.max_rows, 50))
                || render_plugin_tools();
    v_msgs := fold_messages(v_system, v_run.question, v_steps);

    RETURN jsonb_build_object(
        'run_id',   p_run_id,
        'question', v_run.question,
        'step',     v_used + 1,
        'max_steps', v_run.max_steps,
        'messages', v_msgs,
        'model',    current_setting('openai.model', true),
        'api_uri',  current_setting('openai.api_uri', true)
    );
END;
$$;
