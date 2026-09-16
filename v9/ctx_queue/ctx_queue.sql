-- v9 W3 overlay: adds ctx_heavy; queue bridge + apply.
-- This file is a v9 overlay: v4/v5/v6 files are loaded read-only and never modified.
-- refresh_plugins() below is a verbatim copy of the function in
-- v6/queue_bridge/duck_queue.sql with exactly one functional delta:
-- v_legal_kind gains 'ctx_heavy'. Every W1-of-v6-style validation rule
-- (plugin/llm_tool/queue_handler/prompt_slot checks, TRUNCATE + reinsert)
-- survives intact.
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
    v_legal_kind text[] := ARRAY['llm', 'embed', 'sql_heavy', 'human_inbox', 'duck_heavy', 'ctx_heavy'];
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

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'ctx_heavy_requests') THEN
        PERFORM pgmq.create('ctx_heavy_requests');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pgmq.meta WHERE queue_name = 'ctx_heavy_requests_dlq') THEN
        PERFORM pgmq.create('ctx_heavy_requests_dlq');
    END IF;
END $$;

CREATE OR REPLACE FUNCTION apply_ctx_result(p_run_id text, p_result jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_request  text := p_result->>'request_id';
    v_op       ctx_operations%ROWTYPE;
    v_pack     text;
    v_task_run text;
    v_gen      integer;
    v_repo     text;
    v_base_from text;
    v_built    text;
    v_dirty_slices   text[] := '{}';
    v_rebuilt_slices text[] := '{}';
    v_pending  boolean;
    v_kind     text;
    v_s        jsonb;
    v_deps     jsonb;
    v_i        integer;
    v_estatus  text;
    v_seq      bigint;
    v_etask    text;
    v_erepo    text;
    v_req      text;
    v_msg      bigint;
BEGIN
    IF v_request IS NULL OR trim(v_request) = '' THEN
        RAISE EXCEPTION 'ctx result missing request_id';
    END IF;
    SELECT * INTO v_op FROM ctx_operations WHERE request_id=v_request FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown ctx operation: %', v_request;
    END IF;
    v_pack := v_op.pack_id;

    -- identity: pack run anchor and op_seq must both match the result
    SELECT task_run_id INTO v_task_run FROM context_packs WHERE pack_id=v_pack;
    IF v_task_run IS NOT DISTINCT FROM p_run_id
       AND COALESCE((p_result->>'op_seq')::bigint, v_op.op_seq) = v_op.op_seq THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'ctx operation identity conflict';
    END IF;

    IF v_op.status IN ('SUCCEEDED','FAILED','DLQ') THEN
        RETURN jsonb_build_object('done', false, 'ok', true, 'replayed', true,
                                  'run_id', p_run_id, 'request_id', v_request);
    END IF;

    -- ordering gate: this op must directly follow the last completed op
    PERFORM 1 FROM context_packs
     WHERE pack_id=v_pack AND last_completed_op_seq = v_op.op_seq - 1
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ctx operation out of order: %', v_op.op_seq;
    END IF;
    IF v_op.status NOT IN ('QUEUED','RUNNING') THEN
        RETURN jsonb_build_object('done', false, 'ok', true, 'replayed', true,
                                  'run_id', p_run_id, 'request_id', v_request);
    END IF;

    IF COALESCE((p_result->>'success')::boolean, false) THEN
        v_built := p_result->>'base_commit';
        IF v_built IS NULL OR trim(v_built) = '' THEN
            RAISE EXCEPTION 'ctx result missing base_commit';
        END IF;

        SELECT generation, repo_path, base_commit INTO v_gen, v_repo, v_base_from
          FROM context_packs WHERE pack_id=v_pack;
        SELECT array_agg(slice_id ORDER BY slice_id) INTO v_dirty_slices
          FROM context_slices WHERE pack_id=v_pack AND stale;
        v_dirty_slices := COALESCE(v_dirty_slices, '{}'::text[]);

        FOR v_s IN SELECT * FROM jsonb_array_elements(COALESCE(p_result->'slices', '[]'::jsonb)) LOOP
            INSERT INTO context_slices(pack_id, slice_id, seq, kind, dep_uri, title, body,
                                       content_hash, generation, stale, updated_at)
            VALUES(v_pack, v_s->>'slice_id', (v_s->>'seq')::int, COALESCE(v_s->>'kind','source_excerpt'),
                   v_s->>'dep_uri', v_s->>'title', v_s->>'body', v_s->>'content_hash',
                   v_gen + 1, false, now())
            ON CONFLICT (pack_id, slice_id) DO UPDATE SET
              seq=EXCLUDED.seq, kind=EXCLUDED.kind, dep_uri=EXCLUDED.dep_uri,
              title=EXCLUDED.title, body=EXCLUDED.body, content_hash=EXCLUDED.content_hash,
              generation=EXCLUDED.generation, stale=false, updated_at=now();

            DELETE FROM slice_dependencies WHERE pack_id=v_pack AND slice_id=v_s->>'slice_id';
            v_deps := v_s->'deps';
            IF v_deps IS NULL OR jsonb_typeof(v_deps) <> 'array' THEN
                v_deps := jsonb_build_array(v_s->>'dep_uri');
            END IF;
            FOR v_i IN 0..jsonb_array_length(v_deps)-1 LOOP
                INSERT INTO slice_dependencies(pack_id, slice_id, dep_uri, built_at_commit)
                VALUES(v_pack, v_s->>'slice_id', v_deps->>v_i, v_built)
                ON CONFLICT (pack_id, slice_id, dep_uri) DO NOTHING;
            END LOOP;
            v_rebuilt_slices := array_append(v_rebuilt_slices, v_s->>'slice_id');
        END LOOP;

        -- build is a full replace: drop slices absent from the payload
        IF v_op.op_kind = 'build' THEN
            DELETE FROM context_slices
             WHERE pack_id=v_pack AND NOT (slice_id = ANY (v_rebuilt_slices));
        END IF;

        UPDATE context_packs SET
          base_commit = v_built,
          generation  = generation + 1,
          last_completed_op_seq = v_op.op_seq,
          token_count = (p_result->>'token_count')::int,
          worker_id   = p_result->>'worker_id',
          last_error  = NULL,
          updated_at  = now(),
          status      = CASE WHEN EXISTS (
                SELECT 1 FROM repo_heads h WHERE h.repo_path = context_packs.repo_path
                  AND h.head_commit <> v_built)
              THEN 'STALE' ELSE 'FRESH' END
        WHERE pack_id = v_pack;

        -- tail consumption: pending_refresh with no in-flight op enqueues the
        -- next refresh now. Inlined copy of _ctx_enqueue_op's six steps because
        -- ctx_queue.sql loads before ctx_lifecycle.sql defines the helper (and
        -- ctx_current_head), so this file stays self-contained.
        SELECT pending_refresh INTO v_pending FROM context_packs WHERE pack_id=v_pack;
        -- request_id <> v_request: the op being applied right now is still QUEUED
        -- at this point (it is marked SUCCEEDED further below), so it must not
        -- count as in-flight or the tail would never fire.
        IF v_pending AND NOT EXISTS (
            SELECT 1 FROM ctx_operations
             WHERE pack_id=v_pack AND status IN ('QUEUED','RUNNING')
               AND request_id <> v_request) THEN
            SELECT status, next_op_seq, task_run_id, repo_path
              INTO v_estatus, v_seq, v_etask, v_erepo
              FROM context_packs WHERE pack_id=v_pack FOR UPDATE;
            IF FOUND AND v_estatus NOT IN ('RETIRED','FAILED') THEN
                UPDATE context_packs SET
                  next_op_seq = next_op_seq + 1,
                  status = CASE WHEN status='FRESH' THEN 'REFRESHING'
                                WHEN status='BUILDING' THEN 'BUILDING'
                                ELSE status END,
                  pending_refresh = false,
                  updated_at = now()
                WHERE pack_id=v_pack;
                v_req := gen_random_uuid()::text;
                INSERT INTO ctx_operations(request_id, pack_id, op_kind, op_seq, status,
                                           built_at_commit)
                VALUES(v_req, v_pack, 'refresh', v_seq, 'QUEUED',
                       COALESCE((SELECT head_commit FROM repo_heads
                                  WHERE repo_path=v_erepo), 'INIT'));
                v_msg := pgmq.send('ctx_heavy_requests', jsonb_build_object(
                    'request_id', v_req, 'pack_id', v_pack, 'task_run_id', v_etask,
                    'op_kind', 'refresh', 'op_seq', v_seq, 'repo_path', v_erepo,
                    'trigger', 'pending_refresh'));
            END IF;
        END IF;

        v_kind := COALESCE(p_result->>'trigger_kind', v_op.op_kind);
        IF v_kind NOT IN ('build','run_completed','git_hook','manual','start_gate') THEN
            v_kind := 'manual';
        END IF;
        INSERT INTO context_refresh_log(pack_id, trigger_kind, trigger_ref, dirty_slices,
                                        rebuilt_slices, base_from, base_to)
        VALUES(v_pack, v_kind, v_request, v_dirty_slices, v_rebuilt_slices,
               v_base_from, v_built);

        UPDATE ctx_operations SET status='SUCCEEDED', result_summary=p_result,
               worker_id=p_result->>'worker_id', finished_at=now()
         WHERE request_id=v_request;

        RETURN jsonb_build_object('done', false, 'ok', true,
                                  'request_id', v_request, 'pack_id', v_pack,
                                  'generation', v_gen + 1);
    ELSE
        UPDATE ctx_operations SET status='FAILED',
               error=COALESCE(p_result->'error', p_result), finished_at=now()
         WHERE request_id=v_request;
        UPDATE context_packs SET status='FAILED',
               last_completed_op_seq=v_op.op_seq,
               last_error=COALESCE(p_result->'error', p_result), updated_at=now()
         WHERE pack_id=v_pack;
        RETURN jsonb_build_object('done', true, 'ok', false, 'run_id', p_run_id,
                                  'request_id', v_request, 'error', 'ctx_op_failed');
    END IF;
END;
$$;

COMMENT ON FUNCTION apply_ctx_result(text, jsonb) IS $v9$
{"plugin":{"name":"plugin_ctx_queue"},"queue_handler":{"queue_name":"ctx_heavy_requests","queue_kind":"ctx_heavy","consumer":"python_worker","args":{"p_run_id":"text","p_result":"jsonb"},"returns":"jsonb"}}
$v9$;
