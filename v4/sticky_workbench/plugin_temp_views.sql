-- ============================================================
-- PG-Agent v4 · plugin_temp_views（sticky run 连接上的 TEMP VIEW 生命周期）
--
-- 依赖（必须先加载）：pg_agent_workbench_core.sql（_wb_* 助手）
-- 加载位置：plugin_brief_query.sql 之后（声明顺序 = 增量顺序）。
-- 安装协议：加载本文件后执行 SELECT refresh_plugins()。
--
-- 文件内顺序（增量开发顺序，也是渲染时 read_only 在前的语义）：
--   只读半边：wb_temp_view_list / wb_temp_view_columns
--   变更半边：wb_temp_view_create / wb_temp_view_drop
--
-- 边界：只操作当前后端 pg_my_temp_schema() 里的对象；
--       名称一律走 _wb_normalize_temp_view_name（未限定名，pg_my_temp_schema() only）；
--       CREATE/DROP 均不带 CASCADE；不动 workbench_tools / 永久对象 / run 状态；
--       不走 jobs。全部 SECURITY INVOKER。
--
-- 内层 SQL 校验器（_wb_validate_select_sql）独立于 exec_sql_readonly 的外层黑名单：
--   SELECT 函数内部可执行动态 SQL，因此必须自行校验 p_select_sql。
--   不做 EXPLAIN 计划遍历——CREATE VIEW 本身已拒绝 DML CTE / SELECT INTO，
--   且无 ANALYZE 的 EXPLAIN 仍可能执行 IMMUTABLE 函数。
-- ============================================================

-- ------------------------------------------------------------
-- 只读：列出当前会话全部 TEMP VIEW（按名排序，含列数与备注，不读行）
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION wb_temp_view_list()
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER AS $$
    SELECT jsonb_build_object(
        'success', true,
        'views', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'view',         c.relname,
                       'column_count', (SELECT count(*) FROM pg_attribute a
                                         WHERE a.attrelid = c.oid
                                           AND a.attnum > 0
                                           AND NOT a.attisdropped),
                       'note',         obj_description(c.oid, 'pg_class'))
                   ORDER BY c.relname)
              FROM pg_class c
             WHERE pg_my_temp_schema() <> 0
               AND c.relnamespace = pg_my_temp_schema()
               AND c.relkind = 'v'
        ), '[]'::jsonb))
$$;

COMMENT ON FUNCTION wb_temp_view_list() IS $wb$
{"plugin":{"name":"plugin_temp_views"},"llm_tool":{"name":"wb_temp_view_list","description":"只读列出当前 sticky run 连接全部 TEMP VIEW（按名排序，含列数与备注 note）；temp 表、永久对象、其他连接的视图不会出现","args":{},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
$wb$;

-- ------------------------------------------------------------
-- 只读：返回当前会话某个 TEMP VIEW 的有序列结构（不读任何行）
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION wb_temp_view_columns(p_view text)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER AS $$
DECLARE
    v_name text;
    v_oid  oid;
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 TEMP VIEW 名: %s（只接受未加引号、不带 schema 的简单标识符）',
                              COALESCE(p_view, 'NULL')),
            'Solution', '传入简单标识符如 sales_view；不要带 pg_temp. 前缀、点号或引号。');
    END IF;

    v_oid := _wb_temp_view_oid(v_name);
    IF v_oid IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('当前会话不存在名为 %s 的 TEMP VIEW', v_name),
            'Solution', '先用 wb_temp_view_list() 查看本会话 TEMP VIEW，或用 wb_temp_view_create() 创建。');
    END IF;

    RETURN jsonb_build_object(
        'success', true,
        'view', v_name,
        'columns', _wb_temp_view_columns(v_oid));
END;
$$;

COMMENT ON FUNCTION wb_temp_view_columns(text) IS $wb$
{"plugin":{"name":"plugin_temp_views"},"llm_tool":{"name":"wb_temp_view_columns","description":"只读返回当前 sticky run 连接某个 TEMP VIEW 的有序列结构（ordinal/name/type），不读取任何行数据","args":{"p_view":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
$wb$;

-- ------------------------------------------------------------
-- 内层校验器：保守的单条 SELECT/WITH 卫生层（非完备沙箱）
-- 返回 NULL = 通过；返回结构化 jsonb = 拒绝（Phase=Validation）。
-- 规则（§3.6）：
--   1) 拒绝 NULL/空/含 NUL/超长（默认上限 16000 字符）
--   2) 拒绝任何分号（含字符串字面量内）——保守地保证单条语句
--   3) 拒绝注释标记 -- /* */ ——防词法关键字隐藏（接受安全误报）
--   4) 首 token 必须恰为 SELECT 或 WITH
--   5) 拒绝独立出现的工具/DML 词（词边界匹配）
-- 允许的 SELECT 仍可调用有副作用的用户函数（SECURITY INVOKER，
-- 本插件不是权限升级边界）。
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION _wb_validate_select_sql(p_sql text, p_max_len int DEFAULT 16000)
RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_low  text;
    v_tok  text;
    v_first text;
    v_forbidden text[] := ARRAY[
        'create','alter','drop','truncate','insert','update','delete','merge',
        'grant','revoke','copy','execute','call','do','vacuum','analyze',
        'reindex','cluster','discard','lock','set','reset','load','listen',
        'notify','unlisten','into','for'];
BEGIN
    IF p_sql IS NULL OR trim(p_sql) = '' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', 'p_select_sql 为空',
            'Solution', '提供一条以 SELECT 或 WITH 开头的单条只读查询。');
    END IF;
    IF position('\x00'::bytea IN convert_to(p_sql, 'UTF8')) > 0 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', 'p_select_sql 含 NUL 字符',
            'Solution', '移除 NUL 字符后重试。');
    END IF;
    IF length(p_sql) > p_max_len THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('p_select_sql 超长: %s 字符（上限 %s）', length(p_sql), p_max_len),
            'Solution', '精简查询；必要时先建中间视图再引用。');
    END IF;
    IF position(';' IN p_sql) > 0 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', 'p_select_sql 含分号（包括字符串字面量内，保守拒绝以保证单条语句）',
            'Solution', '只提供一条 SELECT/WITH，去掉所有分号。');
    END IF;
    IF p_sql LIKE '%--%' OR p_sql LIKE '%/*%' OR p_sql LIKE '%*/%' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', 'p_select_sql 含 SQL 注释标记（-- 或 /* */）',
            'Solution', '移除全部注释后重试。');
    END IF;
    v_first := lower(substring(trim(p_sql) FROM '^[A-Za-z_][A-Za-z0-9_]*'));
    IF v_first IS NULL OR v_first NOT IN ('select', 'with') THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('p_select_sql 首 token 必须是 SELECT 或 WITH，实际: %s',
                              COALESCE(v_first, '（非标识符开头）')),
            'Solution', '改写为一条以 SELECT 或 WITH 开头的查询。');
    END IF;
    v_low := lower(p_sql);
    FOREACH v_tok IN ARRAY v_forbidden LOOP
        IF v_low ~ ('\m' || v_tok || '\M') THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
                'Problem', format('p_select_sql 含禁止的独立关键字: %s', upper(v_tok)),
                'Solution', 'p_select_sql 只能是一条只读 SELECT/WITH；去掉 DML/工具语句及 INTO/FOR 子句。');
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$;

-- ------------------------------------------------------------
-- 变更：创建/替换当前会话的 TEMP VIEW（VOLATILE，temp_view_mutation）
-- 不用 CASCADE；不更新 workbench_tools 或任何永久表；
-- 视图生命周期归连接所有，agent run 结束不自动清理。
-- ------------------------------------------------------------
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
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 TEMP VIEW 名: %s（只接受未加引号、不带 schema 的简单标识符）',
                              COALESCE(p_view, 'NULL')),
            'Solution', '传入简单标识符如 sales_view；不要带 pg_temp. 前缀、点号或引号。');
    END IF;

    -- token 卫生层在 DDL 之前；DML CTE / SELECT INTO 由 CREATE VIEW 自身兜底拒绝
    v_err := _wb_validate_select_sql(p_select_sql, 16000);
    IF v_err IS NOT NULL THEN
        RETURN v_err;
    END IF;
    v_sql := trim(p_select_sql);

    -- 预检当前会话 temp 命名空间内的同名对象（不碰永久 schema）
    SELECT c.relkind INTO v_relkind
      FROM pg_class c
     WHERE pg_my_temp_schema() <> 0
       AND c.relnamespace = pg_my_temp_schema()
       AND c.relname = v_name;
    IF v_relkind IS NOT NULL AND v_relkind <> 'v' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('当前会话已存在同名 temp 对象 %s（relkind=%s，不是视图），拒绝替换',
                              v_name, v_relkind),
            'Solution', '换一个视图名，或先手动清理该 temp 表。');
    END IF;
    v_isview := COALESCE(v_relkind = 'v', false);
    IF v_isview AND NOT COALESCE(p_replace, true) THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('当前会话已存在 TEMP VIEW %s 且 p_replace=false', v_name),
            'Solution', '换一个视图名，或显式传 p_replace=true 覆盖，或先 wb_temp_view_drop()。');
    END IF;

    -- 单一异常边界：DDL 失败时子事务回滚，原视图保持不变
    BEGIN
        IF v_isview THEN
            EXECUTE format('CREATE OR REPLACE TEMP VIEW %I AS %s', v_name, v_sql);
        ELSE
            EXECUTE format('CREATE TEMP VIEW %I AS %s', v_name, v_sql);
        END IF;
        v_cols := _wb_temp_view_columns(_wb_temp_view_oid(v_name));
    EXCEPTION
      WHEN invalid_table_definition THEN
        -- 42P16：CREATE OR REPLACE 改列名/改类型不兼容；原视图保留
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300),
            'Solution', '替换必须保持原列名/顺序/类型（只能在末尾追加列）；或先 DROP 依赖它的视图再重建。');
      WHEN OTHERS THEN
        -- CREATE VIEW 自身的定义校验错误（语法/不存在/视图不允许的语句等）
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', left(SQLERRM, 300),
            'Solution', 'CREATE VIEW 校验失败：改用一条合法的 SELECT/WITH（无 DML、无 INTO、无多语句）。');
    END;

    RETURN jsonb_build_object(
        'success', true,
        'view', v_name,
        'replaced', v_isview,
        'columns', v_cols);
END;
$$;

COMMENT ON FUNCTION wb_temp_view_create(text, text, boolean) IS $wb$
{"plugin":{"name":"plugin_temp_views"},"llm_tool":{"name":"wb_temp_view_create","description":"在当前 sticky run 连接创建或替换一个 TEMP VIEW：p_select_sql 必须是单条 SELECT/WITH（禁分号/注释/DML/INTO/FOR）；p_replace=false 时拒绝覆盖既有视图","args":{"p_view":"text","p_select_sql":"text","p_replace":"boolean"},"returns":"jsonb","session_scope":"run_connection","capability":"temp_view_mutation"}}
$wb$;

-- ------------------------------------------------------------
-- 变更：删除当前会话的一个 TEMP VIEW（受限 DROP，不带 CASCADE）
-- 重复 drop 不是静默成功——缺视图按 Resolution 错误返回，
-- 让模型能区分“本来就干净”与“本次操作失败”。
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION wb_temp_view_drop(p_view text)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_name text;
    v_oid  oid;
BEGIN
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 TEMP VIEW 名: %s（只接受未加引号、不带 schema 的简单标识符）',
                              COALESCE(p_view, 'NULL')),
            'Solution', '传入简单标识符如 sales_view；不要带 pg_temp. 前缀、点号或引号。');
    END IF;

    v_oid := _wb_temp_view_oid(v_name);
    IF v_oid IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('当前会话不存在名为 %s 的 TEMP VIEW（重复删除也按错误返回）', v_name),
            'Solution', '先用 wb_temp_view_list() 核对本会话 TEMP VIEW；不存在即已是干净状态。');
    END IF;

    BEGIN
        EXECUTE format('DROP VIEW pg_temp.%I', v_name);
    EXCEPTION
      WHEN dependent_objects_still_exist THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300),
            'Solution', '有视图依赖它：先 DROP 依赖视图再重试；本工具不带 CASCADE。');
      WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300),
            'Solution', '受限 DROP 失败：先核对依赖（pg_depend / wb_temp_view_list）再重试。');
    END;

    RETURN jsonb_build_object(
        'success', true,
        'view', v_name,
        'dropped', true);
END;
$$;

COMMENT ON FUNCTION wb_temp_view_drop(text) IS $wb$
{"plugin":{"name":"plugin_temp_views"},"llm_tool":{"name":"wb_temp_view_drop","description":"删除当前 sticky run 连接的一个 TEMP VIEW（受限 DROP，不带 CASCADE）：依赖它的对象会阻止删除并返回结构化错误；视图不存在按 Resolution 错误返回而非静默成功","args":{"p_view":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"temp_view_mutation"}}
$wb$;
