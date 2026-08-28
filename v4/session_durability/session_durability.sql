-- ============================================================
-- PG-Agent v4 · session durability (W5)
--
-- Default remains temp. run_schema is opt-in via agent_start_session().
-- ============================================================

ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS session_mode text NOT NULL DEFAULT 'temp';

CREATE OR REPLACE FUNCTION _agent_ensure_run_schema()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_schema text;
BEGIN
    IF NEW.session_mode = 'run_schema' THEN
        v_schema := 'agent_run_' || replace(NEW.run_id, '-', '');
        EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_schema);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I.agent_session_kv (k text PRIMARY KEY, v text NOT NULL)',
            v_schema);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS agent_runs_ensure_schema ON agent_runs;
CREATE TRIGGER agent_runs_ensure_schema
AFTER INSERT ON agent_runs
FOR EACH ROW EXECUTE FUNCTION _agent_ensure_run_schema();

CREATE OR REPLACE FUNCTION _wb_run_schema_name(p_run_id text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT 'agent_run_' || replace(p_run_id, '-', '')
$$;

CREATE OR REPLACE FUNCTION _wb_target_nspname()
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_run text;
    v_mode text;
BEGIN
    v_run := agent_current_run_id();
    IF v_run IS NULL THEN
        RETURN 'pg_temp';
    END IF;
    SELECT session_mode INTO v_mode FROM agent_runs WHERE run_id = v_run;
    IF COALESCE(v_mode, 'temp') = 'run_schema' THEN
        RETURN _wb_run_schema_name(v_run);
    END IF;
    RETURN 'pg_temp';
END;
$$;

CREATE OR REPLACE FUNCTION _wb_target_schema_oid()
RETURNS oid
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_name text := _wb_target_nspname();
BEGIN
    IF v_name = 'pg_temp' THEN
        RETURN pg_my_temp_schema();
    END IF;
    RETURN (SELECT n.oid FROM pg_namespace n WHERE n.nspname = v_name);
END;
$$;

CREATE OR REPLACE FUNCTION _wb_temp_view_oid(p_name text)
RETURNS oid
LANGUAGE sql STABLE AS $$
    SELECT c.oid
      FROM pg_class c
     WHERE _wb_target_schema_oid() IS NOT NULL
       AND _wb_target_schema_oid() <> 0
       AND c.relnamespace = _wb_target_schema_oid()
       AND c.relkind = 'v'
       AND c.relname = _wb_normalize_temp_view_name(p_name)
     LIMIT 1
$$;

CREATE OR REPLACE FUNCTION session_set(p_key text, p_val text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_nsp text := _wb_target_nspname();
BEGIN
    IF v_nsp = 'pg_temp' THEN
        CREATE TEMP TABLE IF NOT EXISTS agent_session_kv (
            k text PRIMARY KEY,
            v text NOT NULL
        );
        INSERT INTO agent_session_kv(k, v) VALUES (p_key, p_val)
        ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.agent_session_kv(k, v) VALUES ($1, $2)
             ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v', v_nsp)
            USING p_key, p_val;
    END IF;
    RETURN jsonb_build_object('success', true, 'key', p_key, 'pid', pg_backend_pid(),
                              'session_mode', CASE WHEN v_nsp = 'pg_temp' THEN 'temp' ELSE 'run_schema' END);
END;
$$;

CREATE OR REPLACE FUNCTION session_get(p_key text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_nsp text := _wb_target_nspname();
    v_val text;
BEGIN
    IF v_nsp = 'pg_temp' THEN
        CREATE TEMP TABLE IF NOT EXISTS agent_session_kv (
            k text PRIMARY KEY,
            v text NOT NULL
        );
        SELECT kv.v INTO v_val FROM agent_session_kv kv WHERE kv.k = p_key;
    ELSE
        EXECUTE format('SELECT v FROM %I.agent_session_kv WHERE k = $1', v_nsp)
           INTO v_val USING p_key;
    END IF;
    RETURN jsonb_build_object(
        'success', true, 'key', p_key, 'value', v_val, 'pid', pg_backend_pid(),
        'session_mode', CASE WHEN v_nsp = 'pg_temp' THEN 'temp' ELSE 'run_schema' END);
END;
$$;

CREATE OR REPLACE FUNCTION wb_temp_view_list()
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER AS $$
DECLARE
    v_oid oid := _wb_target_schema_oid();
    v_views jsonb;
    v_mode text := CASE WHEN _wb_target_nspname() = 'pg_temp' THEN 'temp' ELSE 'run_schema' END;
BEGIN
    IF v_oid IS NULL OR v_oid = 0 THEN
        RETURN jsonb_build_object('success', true, 'views', '[]'::jsonb, 'session_mode', v_mode);
    END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'view',         c.relname,
               'column_count', (SELECT count(*) FROM pg_attribute a
                                 WHERE a.attrelid = c.oid
                                   AND a.attnum > 0
                                   AND NOT a.attisdropped),
               'note',         obj_description(c.oid, 'pg_class'),
               'storage',      v_mode
           ) ORDER BY c.relname), '[]'::jsonb)
      INTO v_views
      FROM pg_class c
     WHERE c.relnamespace = v_oid
       AND c.relkind = 'v';
    RETURN jsonb_build_object('success', true, 'views', v_views, 'session_mode', v_mode);
END;
$$;

CREATE OR REPLACE FUNCTION wb_brief_query(p_view text, p_limit int DEFAULT 20)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER AS $$
DECLARE
    v_name  text;
    v_lim   int;
    v_oid   oid;
    v_data  jsonb;
    v_n     int;
    v_trunc boolean;
    v_nsp   text := _wb_target_nspname();
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 VIEW 名: %s', COALESCE(p_view, 'NULL')));
    END IF;
    v_lim := COALESCE(p_limit, 20);
    IF v_lim < 1 OR v_lim > 50 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('p_limit 超出范围: %s', v_lim));
    END IF;
    v_oid := _wb_temp_view_oid(v_name);
    IF v_oid IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('当前 run 作用域不存在名为 %s 的 VIEW', v_name));
    END IF;
    BEGIN
        EXECUTE format(
            'SELECT COALESCE(jsonb_agg(to_jsonb(t)), ''[]''::jsonb)
               FROM (SELECT * FROM %I.%I LIMIT %s) t',
            v_nsp, v_name, v_lim + 1)
           INTO v_data;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300));
    END;
    v_n := jsonb_array_length(v_data);
    v_trunc := v_n > v_lim;
    IF v_trunc THEN
        v_data := v_data - (v_n - 1);
        v_n := v_lim;
    END IF;
    RETURN jsonb_build_object(
        'success', true, 'view', v_name, 'session_mode',
        CASE WHEN v_nsp = 'pg_temp' THEN 'temp' ELSE 'run_schema' END,
        'columns', _wb_temp_view_columns(v_oid),
        'data', v_data, 'row_count', v_n, 'truncated', v_trunc);
END;
$$;

CREATE OR REPLACE FUNCTION wb_temp_view_create(
    p_view       text,
    p_select_sql text,
    p_replace    boolean DEFAULT true
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_name    text;
    v_err     jsonb;
    v_sql     text;
    v_relkind "char";
    v_isview  boolean;
    v_cols    jsonb;
    v_nsp     text := _wb_target_nspname();
    v_oid     oid := _wb_target_schema_oid();
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 VIEW 名: %s', COALESCE(p_view, 'NULL')));
    END IF;
    v_err := _wb_validate_select_sql(p_select_sql, 16000);
    IF v_err IS NOT NULL THEN
        RETURN v_err;
    END IF;
    v_sql := trim(p_select_sql);

    SELECT c.relkind INTO v_relkind
      FROM pg_class c
     WHERE v_oid IS NOT NULL AND v_oid <> 0
       AND c.relnamespace = v_oid
       AND c.relname = v_name;
    IF v_relkind IS NOT NULL AND v_relkind <> 'v' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('同名对象 %s relkind=%s 不是视图', v_name, v_relkind));
    END IF;
    v_isview := COALESCE(v_relkind = 'v', false);
    IF v_isview AND NOT COALESCE(p_replace, true) THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('已存在 VIEW %s 且 p_replace=false', v_name));
    END IF;

    BEGIN
        IF v_nsp = 'pg_temp' THEN
            IF v_isview THEN
                EXECUTE format('CREATE OR REPLACE TEMP VIEW %I AS %s', v_name, v_sql);
            ELSE
                EXECUTE format('CREATE TEMP VIEW %I AS %s', v_name, v_sql);
            END IF;
        ELSE
            IF v_isview THEN
                EXECUTE format('CREATE OR REPLACE VIEW %I.%I AS %s', v_nsp, v_name, v_sql);
            ELSE
                EXECUTE format('CREATE VIEW %I.%I AS %s', v_nsp, v_name, v_sql);
            END IF;
        END IF;
        v_cols := _wb_temp_view_columns(_wb_temp_view_oid(v_name));
    EXCEPTION
      WHEN invalid_table_definition THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300));
      WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', left(SQLERRM, 300));
    END;

    RETURN jsonb_build_object(
        'success', true, 'view', v_name, 'replaced', v_isview, 'columns', v_cols,
        'session_mode', CASE WHEN v_nsp = 'pg_temp' THEN 'temp' ELSE 'run_schema' END);
END;
$$;

CREATE OR REPLACE FUNCTION wb_temp_view_drop(p_view text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_name text;
    v_oid  oid;
    v_nsp  text := _wb_target_nspname();
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 VIEW 名: %s', COALESCE(p_view, 'NULL')));
    END IF;
    v_oid := _wb_temp_view_oid(v_name);
    IF v_oid IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('不存在 VIEW %s', v_name));
    END IF;
    BEGIN
        EXECUTE format('DROP VIEW %I.%I', v_nsp, v_name);
    EXCEPTION
      WHEN dependent_objects_still_exist THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300),
            'Solution', '先 DROP 依赖视图；不带 CASCADE。');
      WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300));
    END;
    RETURN jsonb_build_object('success', true, 'view', v_name, 'dropped', true);
END;
$$;

CREATE OR REPLACE FUNCTION wb_sql_curate(
    p_view       text,
    p_select_sql text,
    p_note       text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_name     text;
    v_note     text;
    v_err      jsonb;
    v_res      jsonb;
    v_cols     jsonb;
    v_replaced boolean;
    v_nsp      text := _wb_target_nspname();
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 VIEW 名: %s', COALESCE(p_view, 'NULL')));
    END IF;
    v_note := NULL;
    IF p_note IS NOT NULL THEN
        IF position('\x00'::bytea IN convert_to(p_note, 'UTF8')) > 0 THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
                'Problem', 'p_note 含 NUL');
        END IF;
        IF length(p_note) > 1000 THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
                'Problem', 'p_note 超长');
        END IF;
        v_note := NULLIF(regexp_replace(p_note, '^\s*$', ''), '');
    END IF;
    v_err := _wb_validate_select_sql(p_select_sql, 8000);
    IF v_err IS NOT NULL THEN
        RETURN v_err;
    END IF;
    BEGIN
        v_res := wb_temp_view_create(v_name, p_select_sql, true);
        IF COALESCE((v_res->>'success')::boolean, false) THEN
            IF v_note IS NULL THEN
                EXECUTE format('COMMENT ON VIEW %I.%I IS NULL', v_nsp, v_name);
            ELSE
                EXECUTE format('COMMENT ON VIEW %I.%I IS %L', v_nsp, v_name, v_note);
            END IF;
            v_cols := v_res->'columns';
            v_replaced := COALESCE((v_res->>'replaced')::boolean, false);
        ELSE
            RETURN v_res;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', format('备注应用失败，已回滚: %s', left(SQLERRM, 200)));
    END;
    RETURN jsonb_build_object(
        'success', true, 'view', v_name, 'replaced', v_replaced,
        'note', v_note, 'columns', v_cols,
        'session_mode', CASE WHEN v_nsp = 'pg_temp' THEN 'temp' ELSE 'run_schema' END);
END;
$$;

CREATE OR REPLACE FUNCTION agent_start_session(
    p_question text,
    p_max_steps integer DEFAULT 10,
    p_session_mode text DEFAULT 'temp'
)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id text := gen_random_uuid()::text;
    v_schema text;
BEGIN
    IF COALESCE(p_session_mode, '') NOT IN ('temp', 'run_schema') THEN
        RAISE EXCEPTION 'invalid session_mode: %', p_session_mode;
    END IF;
    INSERT INTO agent_runs (run_id, question, max_steps, session_mode)
    VALUES (v_run_id, p_question, p_max_steps, p_session_mode);
    IF p_session_mode = 'run_schema' THEN
        v_schema := _wb_run_schema_name(v_run_id);
        EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_schema);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I.agent_session_kv (k text PRIMARY KEY, v text NOT NULL)',
            v_schema);
    END IF;
    PERFORM enqueue_llm_request(v_run_id);
    RETURN v_run_id;
END;
$$;

CREATE OR REPLACE FUNCTION cleanup_run_session(p_run_id text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_status text;
    v_mode   text;
    v_schema text;
    v_exists boolean;
BEGIN
    SELECT session_mode INTO v_mode FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('success', false, 'Problem', 'unknown run_id');
    END IF;
    SELECT status INTO v_status FROM run_state(p_run_id);
    IF COALESCE(v_status, 'RUNNING') NOT IN ('SUCCESS', 'ERROR') THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'SESSION_ERROR', 'Phase', 'Validation',
            'Problem', format('run %s is not terminal (%s)', p_run_id, v_status));
    END IF;
    IF COALESCE(v_mode, 'temp') <> 'run_schema' THEN
        RETURN jsonb_build_object('success', true, 'cleaned', false, 'mode', 'temp', 'idempotent', true);
    END IF;
    v_schema := _wb_run_schema_name(p_run_id);
    SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = v_schema) INTO v_exists;
    IF v_exists THEN
        EXECUTE format('DROP SCHEMA %I CASCADE', v_schema);
    END IF;
    RETURN jsonb_build_object(
        'success', true, 'cleaned', v_exists, 'mode', 'run_schema',
        'schema', v_schema, 'idempotent', true);
END;
$$;
