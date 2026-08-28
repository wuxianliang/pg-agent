-- ============================================================
-- PG-Agent v4 · plugin taxonomy (W1)
--
-- Single COMMENT taxonomy, plugin registry, queue bindings, and
-- generic queue-message apply. Queue-kind behaviour lives in the
-- registered handler, never in apply_queue_result().
-- ============================================================

CREATE TABLE IF NOT EXISTS plugin_packages (
    plugin_name  text PRIMARY KEY,
    metadata     jsonb NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plugin_bindings (
    binding_name text NOT NULL,
    binding_type text NOT NULL CHECK (binding_type IN ('llm_tool', 'queue_handler')),
    plugin_name  text NOT NULL REFERENCES plugin_packages(plugin_name),
    fn           regprocedure NOT NULL,
    queue_name   text,
    queue_kind   text,
    consumer     text,
    metadata     jsonb NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (binding_type, binding_name),
    CHECK (
        (binding_type = 'llm_tool'
         AND queue_name IS NULL AND queue_kind IS NULL AND consumer IS NULL)
        OR
        (binding_type = 'queue_handler'
         AND queue_name IS NOT NULL AND queue_kind IS NOT NULL AND consumer IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS plugin_bindings_queue_name_uidx
    ON plugin_bindings (queue_name)
    WHERE binding_type = 'queue_handler';

CREATE TABLE IF NOT EXISTS processed_queue_messages (
    queue_name  text NOT NULL,
    msg_id      bigint NOT NULL,
    run_id      text,
    result_hash text,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (queue_name, msg_id)
);

CREATE OR REPLACE FUNCTION agent_current_run_id()
RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('pg_agent.current_run_id', true), '')
$$;

CREATE OR REPLACE FUNCTION apply_llm_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_raw text;
BEGIN
    IF p_result IS NULL THEN
        RAISE EXCEPTION 'apply_llm_result: result is null';
    END IF;
    v_raw := p_result->>'raw';
    IF v_raw IS NULL OR trim(v_raw) = '' THEN
        -- Allow a JSON object that *is* the model payload (thought/action/...).
        IF p_result ? 'thought' OR p_result ? 'final_answer' OR p_result ? 'action' THEN
            v_raw := p_result::text;
        ELSE
            RAISE EXCEPTION 'apply_llm_result: missing raw text';
        END IF;
    END IF;
    RETURN apply_llm_response(p_run_id, v_raw);
END;
$$;

COMMENT ON FUNCTION apply_llm_result(text, jsonb) IS $v4$
{"plugin":{"name":"plugin_llm"},"queue_handler":{"queue_name":"llm_requests","queue_kind":"llm","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v4$;

CREATE OR REPLACE FUNCTION apply_queue_result(
    p_queue_name text,
    p_msg_id bigint,
    p_run_id text,
    p_result jsonb
)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_fn      regprocedure;
    v_nsp     text;
    v_proname text;
    v_n       int;
    v_prev    text;
    v_out     jsonb;
    v_status  text;
    v_used    int;
    v_answer  text;
    v_err     text;
BEGIN
    IF p_queue_name IS NULL OR trim(p_queue_name) = '' THEN
        RAISE EXCEPTION 'apply_queue_result: queue_name required';
    END IF;
    IF p_msg_id IS NULL THEN
        RAISE EXCEPTION 'apply_queue_result: msg_id required';
    END IF;

    SELECT fn INTO v_fn
      FROM plugin_bindings
     WHERE binding_type = 'queue_handler'
       AND queue_name = p_queue_name;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'apply_queue_result: unknown queue or missing handler: %', p_queue_name;
    END IF;

    INSERT INTO processed_queue_messages (queue_name, msg_id, run_id, result_hash)
    VALUES (
        p_queue_name,
        p_msg_id,
        p_run_id,
        md5(COALESCE(p_result::text, ''))
    )
    ON CONFLICT (queue_name, msg_id) DO NOTHING;
    GET DIAGNOSTICS v_n = ROW_COUNT;

    IF v_n = 0 THEN
        SELECT status, steps_used, answer, error
          INTO v_status, v_used, v_answer, v_err
          FROM run_state(p_run_id);
        RETURN jsonb_build_object(
            'done', COALESCE(v_status IN ('SUCCESS', 'ERROR'), false),
            'ok', COALESCE(v_status = 'SUCCESS', false),
            'answer', v_answer,
            'run_id', p_run_id,
            'replayed', true,
            'error', v_err
        );
    END IF;

    SELECT n.nspname, p.proname INTO v_nsp, v_proname
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE p.oid = v_fn;

    v_prev := current_setting('pg_agent.current_run_id', true);
    PERFORM set_config('pg_agent.current_run_id', COALESCE(p_run_id, ''), true);
    BEGIN
        -- Resolve by argument types; do not interpolate the regprocedure signature.
        EXECUTE format('SELECT %I.%I($1::text, $2::jsonb)', v_nsp, v_proname)
           INTO v_out
          USING p_run_id, p_result;
        PERFORM set_config('pg_agent.current_run_id', COALESCE(v_prev, ''), true);
    EXCEPTION WHEN OTHERS THEN
        PERFORM set_config('pg_agent.current_run_id', COALESCE(v_prev, ''), true);
        RAISE;
    END;

    IF v_out IS NULL THEN
        RAISE EXCEPTION 'apply_queue_result: handler % returned null', v_fn;
    END IF;
    RETURN v_out;
END;
$$;

CREATE OR REPLACE FUNCTION list_queue_bindings()
RETURNS TABLE(
    binding_name text,
    plugin_name text,
    fn regprocedure,
    queue_name text,
    queue_kind text,
    consumer text,
    metadata jsonb
)
LANGUAGE sql STABLE AS $$
    SELECT binding_name, plugin_name, fn, queue_name, queue_kind, consumer, metadata
      FROM plugin_bindings
     WHERE binding_type = 'queue_handler'
     ORDER BY queue_name, binding_name
$$;

CREATE OR REPLACE FUNCTION render_plugin_tools()
RETURNS text
LANGUAGE sql STABLE AS $$
    WITH live AS (
        SELECT b.binding_name, b.plugin_name, b.metadata,
               pg_get_function_arguments(b.fn::oid) AS call_args,
               b.metadata->'llm_tool'->>'capability' AS cap,
               COALESCE(b.metadata->'llm_tool'->>'session_scope', 'run_connection') AS scope
          FROM plugin_bindings b
          JOIN pg_proc p ON p.oid = b.fn::oid
         WHERE b.binding_type = 'llm_tool'
    )
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM live) THEN
        E'\n=== Plugin tools ===\n'
        || E'（未安装 llm_tool：不要猜测或调用 wb_* 工具名。内建工具仍是 execute_sql。）\n'
        || E'协议：严格使用 thought/action/action_input/final_answer；不是 v2 的 code 协议。\n'
        || E'observation 外层 success=true 不等于嵌套工具 success。工具作用域是 worker 粘住的 run 连接。'
    ELSE
        E'\n=== Plugin tools（SELECT-callable；v3 action 协议）===\n'
        || (SELECT string_agg(
                 format('- %s(%s) RETURNS jsonb  [%s|%s|%s]  %s',
                        binding_name, call_args, cap, scope, plugin_name,
                        metadata->'llm_tool'->>'description'),
                 E'\n'
                 ORDER BY (cap NOT IN ('read_only')), plugin_name, binding_name)
               FROM live)
        || E'\n调用规则：'
        || '①协议是 thought/action/action_input/final_answer，用 action=execute_sql 包一条 SELECT 调用工具；'
        || '②不要使用 v2 的 code 协议；'
        || '③exec_sql_readonly 的 observation 外层为 {success,data,row_count}——必须检查嵌套对象的 success/Type/Problem，外层 success=true 可能包着嵌套错误；'
        || '④工具只作用于 worker 为该 run_id 粘住的连接（TEMP VIEW / session KV 对其它连接不可见）；'
        || '⑤session_scope=run_connection 表示当前 run 的 sticky backend，不是调用方连接。'
    END
$$;

-- refresh_plugins: validate all candidates, then TRUNCATE+INSERT in one transaction.
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
    v_seen_tools text[] := '{}';
    v_seen_qs    text[] := '{}';
    v_legal_kind text[] := ARRAY['llm', 'embed', 'sql_heavy', 'human_inbox'];
    v_legal_cap  text[] := ARRAY['read_only', 'temp_view_mutation', 'queue_submit', 'spawn'];
    v_legal_scope text[] := ARRAY['current_session', 'run_connection'];
    v_legal_cons text[] := ARRAY['python_worker', 'human'];
    v_count      int;
BEGIN
    FOR r IN
        SELECT p.oid AS poid, p.proname, p.prokind, p.pronargs,
               p.proargnames, p.proargtypes, p.prorettype,
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
            IF r.cmt ~ '"plugin"' OR r.cmt ~ 'llm_tool' OR r.cmt ~ 'queue_handler' THEN
                RAISE EXCEPTION 'refresh_plugins: %() COMMENT 不是合法 JSON', r.proname;
            END IF;
        END;
        IF v_meta IS NULL OR jsonb_typeof(v_meta) <> 'object' THEN
            CONTINUE;
        END IF;
        IF NOT (v_meta ? 'plugin') THEN
            IF v_meta ? 'llm_tool' OR v_meta ? 'queue_handler' THEN
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
