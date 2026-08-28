-- ============================================================
-- PG-Agent v2 · workbench core（插件注册表 + 会话内 TEMP VIEW 解析）
--
-- 依赖（必须先加载）：pg_agent_functional.sql, pg_agent_rlm.sql
-- 加载位置：rlm 之后、data_analysis 与所有 plugin_*.sql 之前。
--
-- 职责：
--   1) workbench_tools 持久注册表：来自函数 COMMENT 的 workbench 元数据
--   2) refresh_workbench_tools()：catalog 扫描 → 全量校验 → TRUNCATE 后重建
--      （候选全部校验通过后才 TRUNCATE；函数内任何异常整体回滚，旧注册表保留）
--   3) render_workbench_tools()：渲染 prompt 工具清单；空注册表返回稳定文案
--   4) _wb_* 助手：TEMP VIEW 名称规范化 / 仅在 pg_my_temp_schema() 内解析
--      （pg_my_temp_schema()=0 表示本会话从未建过 temp 对象，视为无 TEMP VIEW）
--
-- 边界：workbench 工具不走 jobs / worker() / job_handler；
--       注释同时声明 job_handler 与 workbench_plugin 时 refresh 直接失败。
-- ============================================================

-- ------------------------------------------------------------
-- 注册表（部署态，非 per-run 状态；不含 run_id / 行数据 / 秘密）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workbench_tools (
    tool_name    text         PRIMARY KEY,  -- = 函数 proname，库内全局唯一（禁止重载）
    plugin_name  text         NOT NULL,     -- 所属 plugin_*.sql 标识
    fn           regprocedure NOT NULL,     -- 完整签名（含参数类型，非 regproc）
    metadata     jsonb        NOT NULL,     -- 校验通过的完整 JSON 注释
    refreshed_at timestamptz  NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- TEMP VIEW 名称/解析助手（所有 plugin 共用同一标识符策略）
-- 外部调用方只能传未限定名：不走 pg_temp.foo，不做第二条解析/授权路径
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION _wb_normalize_temp_view_name(p_name text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    -- 仅接受去空白后匹配 [A-Za-z_][A-Za-z0-9_]* 且 ≤63 字节的未加引号标识符；否则 NULL
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
    -- 仅解析 pg_my_temp_schema() 中的普通视图（relkind='v'）；
    -- 不解析 public 永久视图 / temp 表 / 物化视图 / 外表 / 其他 schema
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

-- ------------------------------------------------------------
-- refresh_workbench_tools()：扫描 public 函数 COMMENT 并原子重建注册表
--
-- 元数据契约：
--   {"workbench_plugin":"plugin_<slug>",
--    "llm_tool":{"name":"<proname>","description":"单行 ≤500 字符",
--                "args":{"p_x":"<PG 类型名>", ...},"returns":"jsonb",
--                "session_scope":"current_session",
--                "capability":"read_only|temp_view_mutation"}}
-- 校验失败（含 job_handler 互斥、重复 tool_name、类型/签名不符）→ 整体异常回滚。
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION refresh_workbench_tools()
RETURNS int
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    r        record;
    v_rows   workbench_tools[] := '{}';
    v_rec    workbench_tools%ROWTYPE;
    v_meta   jsonb;
    v_plugin text;
    v_tool   jsonb;
    v_name   text;
    v_desc   text;
    v_args   jsonb;
    v_cap    text;
    v_n      int;
    v_i      int;
    v_keys   int;
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
        -- 解析 JSON；疑似 workbench 注释但非法 => 失败（其他注释跳过）
        v_meta := NULL;
        BEGIN
            v_meta := r.cmt::jsonb;
        EXCEPTION WHEN OTHERS THEN
            IF r.cmt ~ 'workbench_plugin' THEN
                RAISE EXCEPTION 'refresh_workbench_tools: %() 的 COMMENT 不是合法 JSON', r.proname;
            END IF;
        END;
        IF v_meta IS NULL OR jsonb_typeof(v_meta) <> 'object'
           OR NOT (v_meta ? 'workbench_plugin') THEN
            CONTINUE;  -- 非工作台函数（如 job_handler 注释、普通注释）
        END IF;

        -- 与队列注册表互斥：同一注释不允许两种解释
        IF v_meta ? 'job_handler' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 COMMENT 同时声明 job_handler 与 workbench_plugin（互斥）', r.proname;
        END IF;

        v_plugin := v_meta->>'workbench_plugin';
        IF v_plugin IS NULL OR v_plugin !~ '^plugin_[a-z][a-z0-9_]*$' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 workbench_plugin 非法: %', r.proname, COALESCE(v_plugin, 'NULL');
        END IF;

        IF r.prokind <> 'f' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 必须是普通函数（prokind=f），不能是过程/聚合/窗口函数', r.proname;
        END IF;
        IF r.prorettype <> 'jsonb'::regtype THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 必须返回 jsonb', r.proname;
        END IF;

        v_tool := v_meta->'llm_tool';
        IF v_tool IS NULL OR jsonb_typeof(v_tool) <> 'object' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 缺少 llm_tool 对象', r.proname;
        END IF;

        v_name := v_tool->>'name';
        IF v_name IS NULL OR v_name <> r.proname THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 llm_tool.name 必须等于函数名，实际: %', r.proname, COALESCE(v_name, 'NULL');
        END IF;

        v_desc := v_tool->>'description';
        IF v_desc IS NULL OR trim(v_desc) = '' OR v_desc ~ '[[:cntrl:]]'
           OR length(v_desc) > 500 THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 llm_tool.description 必须是非空单行且不超过 500 字符', r.proname;
        END IF;

        v_args := v_tool->'args';
        IF v_args IS NULL OR jsonb_typeof(v_args) <> 'object' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 llm_tool.args 必须是对象', r.proname;
        END IF;
        SELECT count(*) INTO v_keys FROM jsonb_object_keys(v_args);
        v_n := COALESCE(r.pronargs, 0);
        IF v_keys <> v_n THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 args 元数据键数（%）与函数参数数（%）不一致', r.proname, v_keys, v_n;
        END IF;
        IF v_n > 0 THEN
            IF r.proargnames IS NULL OR array_length(r.proargnames, 1) <> v_n THEN
                RAISE EXCEPTION 'refresh_workbench_tools: %() 存在未命名参数，无法与 args 元数据对齐', r.proname;
            END IF;
            FOR v_i IN 1..v_n LOOP
                IF lower(COALESCE(v_args->>r.proargnames[v_i], '')) <>
                   -- 注意：oidvector::oid[] 是 0 起始数组；经 text 归一为 1 起始
                   ((string_to_array(r.proargtypes::text, ' ')::oid[])[v_i]::regtype)::text THEN
                    RAISE EXCEPTION 'refresh_workbench_tools: %() 参数 % 的 args 元数据类型不匹配', r.proname, r.proargnames[v_i];
                END IF;
            END LOOP;
        END IF;

        IF COALESCE(v_tool->>'returns', '') <> 'jsonb' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 llm_tool.returns 必须是 jsonb', r.proname;
        END IF;
        IF COALESCE(v_tool->>'session_scope', '') <> 'current_session' THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 llm_tool.session_scope 必须是 current_session', r.proname;
        END IF;
        v_cap := v_tool->>'capability';
        IF COALESCE(v_cap, '') NOT IN ('read_only', 'temp_view_mutation') THEN
            RAISE EXCEPTION 'refresh_workbench_tools: %() 的 llm_tool.capability 非法: %', r.proname, COALESCE(v_cap, 'NULL');
        END IF;

        IF EXISTS (SELECT 1 FROM unnest(v_rows) u WHERE (u).tool_name = v_name) THEN
            RAISE EXCEPTION 'refresh_workbench_tools: 重复 tool_name: %（禁止同名重载）', v_name;
        END IF;

        v_rec.tool_name    := v_name;
        v_rec.plugin_name  := v_plugin;
        v_rec.fn           := r.poid::regprocedure;
        v_rec.metadata     := v_meta;
        v_rec.refreshed_at := now();
        v_rows := array_append(v_rows, v_rec);
    END LOOP;

    -- 候选全部通过校验后才重建：TRUNCATE+INSERT 同事务，任何异常整体回滚旧注册表
    TRUNCATE workbench_tools;
    INSERT INTO workbench_tools (tool_name, plugin_name, fn, metadata, refreshed_at)
    SELECT (u).tool_name, (u).plugin_name, (u).fn, (u).metadata, (u).refreshed_at
      FROM unnest(v_rows) u;
    RETURN COALESCE(cardinality(v_rows), 0);
END;
$$;

-- ------------------------------------------------------------
-- render_workbench_tools()：渲染 prompt 工具清单（STABLE，只读，不调用工具）
-- 顺序：read_only 在前、temp_view_mutation 在后，再按 plugin_name、tool_name。
-- fn 已解析不到 pg_proc 的过期行直接省略（部署侧需重新 refresh 清理）。
-- 空注册表：返回稳定的“未安装”文案，而不是空字符串。
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION render_workbench_tools()
RETURNS text
LANGUAGE sql STABLE AS $$
    WITH live AS (
        SELECT w.tool_name, w.plugin_name, w.metadata,
               pg_get_function_arguments(w.fn::oid) AS call_args,
               w.metadata->'llm_tool'->>'capability' AS cap
          FROM workbench_tools w
          JOIN pg_proc p ON p.oid = w.fn::oid
    )
    SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM live) THEN
        E'\n=== Workbench tools ===\n（未安装任何 workbench 工具：不要猜测或调用 wb_* 工具名。）'
    ELSE
        E'\n=== Workbench tools（当前会话 SQL 工具；每条都用一条 SELECT 调用）===\n'
        || (SELECT string_agg(
                 format('- %s(%s) RETURNS jsonb  [%s|%s]  %s',
                        tool_name, call_args, cap, plugin_name,
                        metadata->'llm_tool'->>'description'),
                 E'\n'
                 ORDER BY (cap <> 'read_only'), plugin_name, tool_name)
               FROM live)
        || E'\n调用规则：'
        || '①工具都是当前会话内的 SQL 函数，用一条 SELECT 调用；'
        || '②exec_sql_readonly 包裹该 SELECT，observation 外层为 {success,data:[{<函数名>:<工具jsonb>}],row_count}——必须检查嵌套对象的 success/Type/Problem，外层 success=true 可能包着嵌套错误；'
        || '③工具只作用于当前 PostgreSQL 会话；'
        || '④read_only 工具不改变任何状态，temp_view_mutation 工具只能改动当前会话 pg_temp；'
        || '⑤任意 CREATE/DROP/ALTER/DML/多语句 SQL 仍被禁止。'
    END
$$;
