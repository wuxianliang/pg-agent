-- ============================================================
-- PG-Agent v5 · prompt taxonomy (W2)
--
-- Overlay: allow binding_type=prompt_slot and llm_tool.capability=prompt_mutation.
-- Does not change apply_queue_result().
-- ============================================================

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'plugin_bindings'::regclass AND contype = 'c'
    LOOP
        EXECUTE format('ALTER TABLE plugin_bindings DROP CONSTRAINT %I', r.conname);
    END LOOP;
END $$;

ALTER TABLE plugin_bindings
    ADD CONSTRAINT plugin_bindings_binding_type_check
        CHECK (binding_type IN ('llm_tool', 'queue_handler', 'prompt_slot')),
    ADD CONSTRAINT plugin_bindings_queue_fields_check
        CHECK (
            (binding_type = 'llm_tool'
             AND queue_name IS NULL AND queue_kind IS NULL AND consumer IS NULL)
            OR
            (binding_type = 'queue_handler'
             AND queue_name IS NOT NULL AND queue_kind IS NOT NULL AND consumer IS NOT NULL)
            OR
            (binding_type = 'prompt_slot'
             AND queue_name IS NULL AND queue_kind IS NULL AND consumer IS NULL)
        );

CREATE OR REPLACE FUNCTION refresh_plugins()
RETURNS int
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    r            record;
    v_meta       jsonb;
    v_plugin_obj jsonb;
    v_plugin     text;
    v_tool       jsonb;
    v_qh         jsonb;
    v_name       text;
    v_desc       text;
    v_args       jsonb;
    v_cap        text;
    v_scope      text;
    v_n          int;
    v_i          int;
    v_keys       int;
    v_qname      text;
    v_qkind      text;
    v_consumer   text;
    v_argtype    text;
    v_pkg_meta   jsonb;
    v_packages   jsonb := '{}'::jsonb;
    v_bindings   jsonb := '[]'::jsonb;
    v_slot       jsonb;
    v_ctypes     jsonb;
    v_source     text;
    v_gen        text;
    v_comp       text;
    v_seen_tools text[] := '{}';
    v_seen_qs    text[] := '{}';
    v_seen_slots text[] := '{}';
    v_legal_kind text[] := ARRAY['llm', 'embed', 'sql_heavy', 'human_inbox'];
    v_legal_cap  text[] := ARRAY['read_only', 'temp_view_mutation', 'queue_submit', 'spawn', 'prompt_mutation'];
    v_legal_comp text[] := ARRAY['role', 'task', 'example', 'output_format', 'tools', 'question', 'history'];
    v_legal_src  text[] := ARRAY['stored', 'live'];
    v_legal_gen  text[] := ARRAY['never', 'if_missing'];
    v_legal_scope text[] := ARRAY['current_session', 'run_connection'];
    v_legal_cons text[] := ARRAY['python_worker', 'human'];
    v_count      int;
BEGIN
    FOR r IN
        SELECT p.oid AS poid, p.proname, p.prokind, p.pronargs,
               p.proargnames, p.proargtypes, p.prorettype, p.provolatile,
               obj_description(p.oid, 'pg_proc') AS cmt
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND obj_description(p.oid, 'pg_proc') ~ '^\s*\{'
    LOOP
        v_meta := NULL;
        BEGIN
            v_meta := r.cmt::jsonb;
        EXCEPTION WHEN OTHERS THEN
            IF r.cmt ~ '"plugin"' OR r.cmt ~ 'llm_tool' OR r.cmt ~ 'queue_handler' OR r.cmt ~ 'prompt_slot' THEN
                RAISE EXCEPTION 'refresh_plugins: %() COMMENT 不是合法 JSON', r.proname;
            END IF;
        END;
        IF v_meta IS NULL OR jsonb_typeof(v_meta) <> 'object' THEN
            CONTINUE;
        END IF;
        IF NOT (v_meta ? 'plugin') THEN
            IF v_meta ? 'llm_tool' OR v_meta ? 'queue_handler' OR v_meta ? 'prompt_slot' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 缺少 plugin', r.proname;
            END IF;
            CONTINUE;
        END IF;

        IF v_meta ? 'job_handler' THEN
            RAISE EXCEPTION 'refresh_plugins: %() 混入了 job_handler（与 v4 plugin 互斥）', r.proname;
        END IF;
        IF v_meta ? 'workbench_plugin' THEN
            RAISE EXCEPTION 'refresh_plugins: %() 使用了 v2 workbench_plugin；v4 必须用 plugin', r.proname;
        END IF;

        v_plugin_obj := v_meta->'plugin';
        IF jsonb_typeof(v_plugin_obj) <> 'object' THEN
            RAISE EXCEPTION 'refresh_plugins: %() 的 plugin 必须是对象', r.proname;
        END IF;
        v_plugin := v_plugin_obj->>'name';
        IF v_plugin IS NULL OR v_plugin !~ '^plugin_[a-z][a-z0-9_]*$' THEN
            RAISE EXCEPTION 'refresh_plugins: %() 的 plugin.name 非法: %', r.proname, COALESCE(v_plugin, 'NULL');
        END IF;

        IF r.prokind <> 'f' THEN
            RAISE EXCEPTION 'refresh_plugins: %() 必须是普通函数（prokind=f）', r.proname;
        END IF;
        IF r.prorettype <> 'jsonb'::regtype THEN
            RAISE EXCEPTION 'refresh_plugins: %() 必须返回 jsonb', r.proname;
        END IF;

        IF v_packages ? v_plugin THEN
            v_pkg_meta := v_packages->v_plugin;
            IF v_pkg_meta <> v_plugin_obj THEN
                RAISE EXCEPTION 'refresh_plugins: plugin % 的 metadata 不一致', v_plugin;
            END IF;
        ELSE
            v_packages := v_packages || jsonb_build_object(v_plugin, v_plugin_obj);
        END IF;

        -- optional llm_tool
        IF v_meta ? 'llm_tool' THEN
            v_tool := v_meta->'llm_tool';
            IF v_tool IS NULL OR jsonb_typeof(v_tool) <> 'object' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool 必须是对象', r.proname;
            END IF;
            v_name := v_tool->>'name';
            IF v_name IS NULL OR v_name <> r.proname THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool.name 必须等于函数名，实际: %',
                    r.proname, COALESCE(v_name, 'NULL');
            END IF;
            v_desc := v_tool->>'description';
            IF v_desc IS NULL OR trim(v_desc) = '' OR v_desc ~ '[[:cntrl:]]' OR length(v_desc) > 500 THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool.description 必须是非空单行且不超过 500 字符', r.proname;
            END IF;
            v_args := v_tool->'args';
            IF v_args IS NULL OR jsonb_typeof(v_args) <> 'object' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool.args 必须是对象', r.proname;
            END IF;
            SELECT count(*) INTO v_keys FROM jsonb_object_keys(v_args);
            v_n := COALESCE(r.pronargs, 0);
            IF v_keys <> v_n THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 args 元数据键数（%）与函数参数数（%）不一致',
                    r.proname, v_keys, v_n;
            END IF;
            IF v_n > 0 THEN
                IF r.proargnames IS NULL OR array_length(r.proargnames, 1) <> v_n THEN
                    RAISE EXCEPTION 'refresh_plugins: %() 存在未命名参数，无法与 args 元数据对齐', r.proname;
                END IF;
                FOR v_i IN 1..v_n LOOP
                    v_argtype := ((string_to_array(r.proargtypes::text, ' ')::oid[])[v_i]::regtype)::text;
                    IF lower(COALESCE(v_args->>r.proargnames[v_i], '')) <> v_argtype THEN
                        RAISE EXCEPTION 'refresh_plugins: %() 参数 % 的 args 元数据类型不匹配',
                            r.proname, r.proargnames[v_i];
                    END IF;
                END LOOP;
            END IF;
            IF COALESCE(v_tool->>'returns', '') <> 'jsonb' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool.returns 必须是 jsonb', r.proname;
            END IF;
            v_scope := v_tool->>'session_scope';
            IF COALESCE(v_scope, '') <> ALL (v_legal_scope) THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool.session_scope 非法: %',
                    r.proname, COALESCE(v_scope, 'NULL');
            END IF;
            v_cap := v_tool->>'capability';
            IF COALESCE(v_cap, '') <> ALL (v_legal_cap) THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 llm_tool.capability 非法: %',
                    r.proname, COALESCE(v_cap, 'NULL');
            END IF;
            IF v_name = ANY (v_seen_tools) THEN
                RAISE EXCEPTION 'refresh_plugins: 重复 tool_name: %', v_name;
            END IF;
            v_seen_tools := array_append(v_seen_tools, v_name);
            v_bindings := v_bindings || jsonb_build_array(jsonb_build_object(
                'binding_name', v_name,
                'binding_type', 'llm_tool',
                'plugin_name', v_plugin,
                'fn', r.poid::regprocedure::text,
                'queue_name', NULL,
                'queue_kind', NULL,
                'consumer', NULL,
                'metadata', v_meta
            ));
        END IF;

        -- optional queue_handler
        IF v_meta ? 'queue_handler' THEN
            v_qh := v_meta->'queue_handler';
            IF v_qh IS NULL OR jsonb_typeof(v_qh) <> 'object' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 queue_handler 必须是对象', r.proname;
            END IF;
            v_qname := v_qh->>'queue_name';
            IF v_qname IS NULL OR v_qname !~ '^[a-z][a-z0-9_]*$' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 queue_name 非法: %',
                    r.proname, COALESCE(v_qname, 'NULL');
            END IF;
            v_qkind := v_qh->>'queue_kind';
            IF COALESCE(v_qkind, '') <> ALL (v_legal_kind) THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 queue_kind 非法: %',
                    r.proname, COALESCE(v_qkind, 'NULL');
            END IF;
            v_consumer := v_qh->>'consumer';
            IF COALESCE(v_consumer, '') <> ALL (v_legal_cons) THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 consumer 非法: %',
                    r.proname, COALESCE(v_consumer, 'NULL');
            END IF;
            IF r.pronargs <> 2 THEN
                RAISE EXCEPTION 'refresh_plugins: %() queue_handler 必须是 (text, jsonb) -> jsonb', r.proname;
            END IF;
            v_args := v_qh->'args';
            IF v_args IS NULL OR jsonb_typeof(v_args) <> 'object' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 queue_handler.args 必须是对象', r.proname;
            END IF;
            SELECT count(*) INTO v_keys FROM jsonb_object_keys(v_args);
            IF v_keys <> 2 THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 queue_handler.args 必须恰好两个键', r.proname;
            END IF;
            IF r.proargnames IS NULL OR array_length(r.proargnames, 1) <> 2 THEN
                RAISE EXCEPTION 'refresh_plugins: %() queue_handler 存在未命名参数', r.proname;
            END IF;
            FOR v_i IN 1..2 LOOP
                v_argtype := ((string_to_array(r.proargtypes::text, ' ')::oid[])[v_i]::regtype)::text;
                IF lower(COALESCE(v_args->>r.proargnames[v_i], '')) <> v_argtype THEN
                    RAISE EXCEPTION 'refresh_plugins: %() queue_handler 参数 % 类型不匹配',
                        r.proname, r.proargnames[v_i];
                END IF;
            END LOOP;
            IF ((string_to_array(r.proargtypes::text, ' ')::oid[])[1]::regtype)::text <> 'text'
               OR ((string_to_array(r.proargtypes::text, ' ')::oid[])[2]::regtype)::text <> 'jsonb' THEN
                RAISE EXCEPTION 'refresh_plugins: %() queue_handler 签名必须是 (text, jsonb)', r.proname;
            END IF;
            IF COALESCE(v_qh->>'returns', '') <> 'jsonb' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 queue_handler.returns 必须是 jsonb', r.proname;
            END IF;
            IF v_qname = ANY (v_seen_qs) THEN
                RAISE EXCEPTION 'refresh_plugins: 重复 queue_name: %', v_qname;
            END IF;
            v_seen_qs := array_append(v_seen_qs, v_qname);
            v_bindings := v_bindings || jsonb_build_array(jsonb_build_object(
                'binding_name', r.proname,
                'binding_type', 'queue_handler',
                'plugin_name', v_plugin,
                'fn', r.poid::regprocedure::text,
                'queue_name', v_qname,
                'queue_kind', v_qkind,
                'consumer', v_consumer,
                'metadata', v_meta
            ));
        END IF;

        -- optional prompt_slot
        IF v_meta ? 'prompt_slot' THEN
            IF v_meta ? 'llm_tool' OR v_meta ? 'queue_handler' THEN
                RAISE EXCEPTION 'refresh_plugins: %() prompt_slot 不能同时声明 llm_tool 或 queue_handler', r.proname;
            END IF;
            v_slot := v_meta->'prompt_slot';
            IF v_slot IS NULL OR jsonb_typeof(v_slot) <> 'object' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot 必须是对象', r.proname;
            END IF;
            v_name := v_slot->>'name';
            IF v_name IS NULL OR v_name <> r.proname THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot.name 必须等于函数名，实际: %',
                    r.proname, COALESCE(v_name, 'NULL');
            END IF;
            IF r.provolatile NOT IN ('s', 'i') THEN
                RAISE EXCEPTION 'refresh_plugins: %() prompt_slot 必须是 STABLE 或 IMMUTABLE', r.proname;
            END IF;
            IF r.pronargs <> 2 THEN
                RAISE EXCEPTION 'refresh_plugins: %() prompt_slot 必须是 (text, jsonb) -> jsonb', r.proname;
            END IF;
            IF r.proargnames IS NULL OR array_length(r.proargnames, 1) <> 2
               OR r.proargnames[1] <> 'p_run_id' OR r.proargnames[2] <> 'p_config' THEN
                RAISE EXCEPTION 'refresh_plugins: %() prompt_slot 参数名必须是 p_run_id, p_config', r.proname;
            END IF;
            IF ((string_to_array(r.proargtypes::text, ' ')::oid[])[1]::regtype)::text <> 'text'
               OR ((string_to_array(r.proargtypes::text, ' ')::oid[])[2]::regtype)::text <> 'jsonb' THEN
                RAISE EXCEPTION 'refresh_plugins: %() prompt_slot 签名必须是 (text, jsonb)', r.proname;
            END IF;
            v_args := v_slot->'args';
            IF v_args IS NULL OR jsonb_typeof(v_args) <> 'object' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot.args 必须是对象', r.proname;
            END IF;
            SELECT count(*) INTO v_keys FROM jsonb_object_keys(v_args);
            IF v_keys <> 2 THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot.args 必须恰好两个键', r.proname;
            END IF;
            FOR v_i IN 1..2 LOOP
                v_argtype := ((string_to_array(r.proargtypes::text, ' ')::oid[])[v_i]::regtype)::text;
                IF lower(COALESCE(v_args->>r.proargnames[v_i], '')) <> v_argtype THEN
                    RAISE EXCEPTION 'refresh_plugins: %() prompt_slot 参数 % 类型不匹配',
                        r.proname, r.proargnames[v_i];
                END IF;
            END LOOP;
            IF COALESCE(v_slot->>'returns', '') <> 'jsonb' THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot.returns 必须是 jsonb', r.proname;
            END IF;
            v_ctypes := v_slot->'component_types';
            IF v_ctypes IS NULL OR jsonb_typeof(v_ctypes) <> 'array' OR jsonb_array_length(v_ctypes) < 1 THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 component_types 必须是非空数组', r.proname;
            END IF;
            FOR v_i IN 0..jsonb_array_length(v_ctypes)-1 LOOP
                v_comp := v_ctypes->>v_i;
                IF COALESCE(v_comp, '') <> ALL (v_legal_comp) THEN
                    RAISE EXCEPTION 'refresh_plugins: %() component_types 非法: %', r.proname, COALESCE(v_comp, 'NULL');
                END IF;
            END LOOP;
            v_source := v_slot->>'source';
            IF COALESCE(v_source, '') <> ALL (v_legal_src) THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot.source 非法: %', r.proname, COALESCE(v_source, 'NULL');
            END IF;
            v_gen := v_slot->>'generation';
            IF COALESCE(v_gen, '') <> ALL (v_legal_gen) THEN
                RAISE EXCEPTION 'refresh_plugins: %() 的 prompt_slot.generation 非法: %', r.proname, COALESCE(v_gen, 'NULL');
            END IF;
            IF v_source = 'live' AND v_gen <> 'never' THEN
                RAISE EXCEPTION 'refresh_plugins: %() source=live 要求 generation=never', r.proname;
            END IF;
            IF v_name = ANY (v_seen_slots) THEN
                RAISE EXCEPTION 'refresh_plugins: 重复 prompt_slot name: %', v_name;
            END IF;
            v_seen_slots := array_append(v_seen_slots, v_name);
            v_bindings := v_bindings || jsonb_build_array(jsonb_build_object(
                'binding_name', v_name,
                'binding_type', 'prompt_slot',
                'plugin_name', v_plugin,
                'fn', r.poid::regprocedure::text,
                'queue_name', NULL,
                'queue_kind', NULL,
                'consumer', NULL,
                'metadata', v_meta
            ));
        END IF;

    END LOOP;

    -- validate-all succeeded; replace registry in this transaction
    TRUNCATE TABLE plugin_bindings, plugin_packages;

    INSERT INTO plugin_packages (plugin_name, metadata, refreshed_at)
    SELECT key, value, now()
      FROM jsonb_each(v_packages);

    INSERT INTO plugin_bindings (
        binding_name, binding_type, plugin_name, fn,
        queue_name, queue_kind, consumer, metadata, refreshed_at
    )
    SELECT
        e->>'binding_name',
        e->>'binding_type',
        e->>'plugin_name',
        (e->>'fn')::regprocedure,
        NULLIF(e->>'queue_name', ''),
        NULLIF(e->>'queue_kind', ''),
        NULLIF(e->>'consumer', ''),
        e->'metadata',
        now()
      FROM jsonb_array_elements(v_bindings) e;

    SELECT count(*) INTO v_count FROM plugin_bindings;
    RETURN v_count;
END;
$$;
