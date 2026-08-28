-- ============================================================
-- PG-Agent v4 · plugin_brief_query（只读：预览 sticky run 连接上的 TEMP VIEW）
--
-- 依赖（必须先加载）：pg_agent_workbench_core.sql（_wb_* 助手）
-- 加载位置：pg_agent_data_analysis.sql 之后，是第一个 plugin_*.sql。
-- 安装协议：加载本文件后执行 SELECT refresh_plugins()。
--
-- 职责：在当前后端 pg_my_temp_schema() 内解析普通 TEMP VIEW（relkind='v'），
--       返回列结构 + 前 p_limit 行（1..50，默认 20，显式 NULL 同默认）。
--       多取 1 行作为截断探测行 → truncated。
-- 边界：STABLE / SECURITY INVOKER / capability=read_only；
--       不改任何表、workbench_tools、rlm_vars 或 run 状态；不走 jobs。
-- ============================================================

CREATE OR REPLACE FUNCTION wb_brief_query(p_view text, p_limit int DEFAULT 20)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER AS $$
DECLARE
    v_name     text;
    v_lim      int;
    v_oid      oid;
    v_data     jsonb;
    v_n        int;
    v_trunc    boolean;
BEGIN
    -- ① 名称规范化：仅接受未加引号、不带 schema 的 ASCII 标识符（≤63 字节）
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 TEMP VIEW 名: %s（只接受未加引号、不带 schema 的简单标识符）',
                              COALESCE(p_view, 'NULL')),
            'Solution', '传入简单标识符如 sales_view；不要带 pg_temp. 前缀、点号或引号。');
    END IF;

    -- ② 行数上限：显式 NULL 与省略同效（回落默认 20），要求 1..50
    v_lim := COALESCE(p_limit, 20);
    IF v_lim < 1 OR v_lim > 50 THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('p_limit 超出范围: %s（要求 1..50）', v_lim),
            'Solution', '省略 p_limit（默认 20）或传入 1..50 之间的整数。');
    END IF;

    -- ③ 仅在当前会话 temp 命名空间内解析普通视图
    v_oid := _wb_temp_view_oid(v_name);
    IF v_oid IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Resolution',
            'Problem', format('当前会话不存在名为 %s 的 TEMP VIEW（temp 表/永久视图/其他会话视图均不匹配）',
                              v_name),
            'Solution', '先用 wb_temp_view_list() 查看本会话 TEMP VIEW，或用 wb_temp_view_create() 创建。');
    END IF;

    -- ④ 取 p_limit+1 行（探测行判截断），整块失败无部分结果
    BEGIN
        EXECUTE format(
            'SELECT COALESCE(jsonb_agg(to_jsonb(t)), ''[]''::jsonb)
               FROM (SELECT * FROM pg_temp.%I LIMIT %s) t',
            v_name, v_lim + 1)
           INTO v_data;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', left(SQLERRM, 300),
            'Solution', '视图定义可能引用了已失效的对象；先用 wb_temp_view_columns() 检查结构。');
    END;

    v_n := jsonb_array_length(v_data);
    v_trunc := v_n > v_lim;
    IF v_trunc THEN
        v_data := v_data - (v_n - 1);  -- 丢弃最后的截断探测行
        v_n := v_lim;
    END IF;

    RETURN jsonb_build_object(
        'success', true,
        'view', v_name,
        'columns', _wb_temp_view_columns(v_oid),
        'data', v_data,
        'row_count', v_n,
        'truncated', v_trunc);
END;
$$;

COMMENT ON FUNCTION wb_brief_query(text, int) IS $wb$
{"plugin":{"name":"plugin_brief_query"},"llm_tool":{"name":"wb_brief_query","description":"只读预览当前 sticky run 连接上某个 TEMP VIEW：返回列结构加前 1..50 行（默认 20），truncated 标记是否截断；只解析本连接普通 TEMP VIEW","args":{"p_view":"text","p_limit":"integer"},"returns":"jsonb","session_scope":"run_connection","capability":"read_only"}}
$wb$;
