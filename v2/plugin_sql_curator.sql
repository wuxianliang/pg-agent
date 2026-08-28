-- ============================================================
-- PG-Agent v2 · plugin_sql_curator（策展 TEMP VIEW：定义 + 会话内备注）
--
-- 依赖（必须先加载）：pg_agent_workbench_core.sql（_wb_* 助手）、
--           plugin_temp_views.sql（wb_temp_view_create / _wb_validate_select_sql）
-- 加载位置：plugin_temp_views.sql 之后（声明顺序 = 增量顺序）。
-- 安装协议：加载本文件后执行 SELECT refresh_workbench_tools()，
--           期望累计注册 6 个工具（brief + list/columns/create/drop + curate）。
--
-- 职责：高层“带文档的视图定义”操作——委托 wb_temp_view_create 完成创建与
--       SQL 校验（不复制校验器），只额外做三件事：
--   ① 更严的 p_select_sql 上限：8000 字符（生命周期函数是 16000）
--   ② p_note 校验：≤1000 字符、不含 NUL；在触碰视图之前先拒绝（§3.11）
--   ③ 备注落为视图 COMMENT（会话级，wb_temp_view_list 的 note 即 obj_description）
--
-- 语义：无 p_replace 开关，恒为受控替换。省略/传 NULL/纯空白 p_note
--       一律“清除备注”——重复 curate 不带 p_note 是一次全量重述
--       （替换视图 + 清掉旧文档），没有“省略保留旧备注”模式。
--
-- 原子性：create 调用 + COMMENT ON VIEW 包在同一子事务（BEGIN…EXCEPTION，
--       即隐式 SAVEPOINT）里。create 返回 success=false jsonb → 原样透传
--       （无 DDL 发生）。create 成功而备注应用失败 → 整块回滚：被替换的
--       视图恢复原定义原备注，函数返回结构化 WORKBENCH_ERROR。
--       注意：wb_temp_view_create 会把 DDL 错误吞成 jsonb 返回，那不是
--       事务性撤销——回滚只能靠本函数持有的子事务边界。
--
-- 边界：VOLATILE / SECURITY INVOKER / capability=temp_view_mutation；
--       只操作当前会话 pg_temp；不物化行、不读外部文件；不走 jobs。
-- ============================================================

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
BEGIN
    -- ① 名称规范化：与其他插件同一标识符策略（未限定名，pg_my_temp_schema() only）
    v_name := _wb_normalize_temp_view_name(p_view);
    IF v_name IS NULL THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
            'Problem', format('非法 TEMP VIEW 名: %s（只接受未加引号、不带 schema 的简单标识符）',
                              COALESCE(p_view, 'NULL')),
            'Solution', '传入简单标识符如 sales_summary；不要带 pg_temp. 前缀、点号或引号。');
    END IF;

    -- ② 备注校验先于任何 DDL（§3.11：太长/含 NUL 时视图必须保持原样）
    --    NULL 或纯空白 → 清除备注（v_note 保持 NULL）
    v_note := NULL;
    IF p_note IS NOT NULL THEN
        IF position('\x00'::bytea IN convert_to(p_note, 'UTF8')) > 0 THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
                'Problem', 'p_note 含 NUL 字符',
                'Solution', '移除 NUL 字符后重试。');
        END IF;
        IF length(p_note) > 1000 THEN
            RETURN jsonb_build_object(
                'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Validation',
                'Problem', format('p_note 超长: %s 字符（上限 1000）', length(p_note)),
                'Solution', '精简备注后重试。');
        END IF;
        v_note := NULLIF(regexp_replace(p_note, '^\s*$', ''), '');   -- 纯空白（任意空白符）按“清除”处理
    END IF;

    -- ③ 更严的 8000 字符上限：复用共享校验器（不复制 SELECT 校验逻辑）
    v_err := _wb_validate_select_sql(p_select_sql, 8000);
    IF v_err IS NOT NULL THEN
        RETURN v_err;
    END IF;

    -- ④ 原子块：create 成功的 DDL 与备注同边界；备注失败则连替换一起回滚
    BEGIN
        v_res := wb_temp_view_create(v_name, p_select_sql, true);
        IF COALESCE((v_res->>'success')::boolean, false) THEN
            IF v_note IS NULL THEN
                EXECUTE format('COMMENT ON VIEW pg_temp.%I IS NULL', v_name);
            ELSE
                EXECUTE format('COMMENT ON VIEW pg_temp.%I IS %L', v_name, v_note);
            END IF;
            v_cols     := v_res->'columns';
            v_replaced := COALESCE((v_res->>'replaced')::boolean, false);
        ELSE
            -- create 自己的结构化错误（其内部子事务已回滚，无 DDL 发生）
            RETURN v_res;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        -- create 已成功、备注应用失败：子事务整体回滚，被替换的视图恢复原状
        RETURN jsonb_build_object(
            'success', false, 'Type', 'WORKBENCH_ERROR', 'Phase', 'Execution',
            'Problem', format('备注应用失败，视图变更已整体回滚: %s', left(SQLERRM, 200)),
            'Solution', '重试 wb_sql_curate；若持续失败，用 wb_temp_view_list() 核对视图现状。');
    END;

    RETURN jsonb_build_object(
        'success', true,
        'view', v_name,
        'replaced', v_replaced,
        'note', v_note,
        'columns', v_cols);
END;
$$;

COMMENT ON FUNCTION wb_sql_curate(text, text, text) IS $wb$
{"workbench_plugin":"plugin_sql_curator","llm_tool":{"name":"wb_sql_curate","description":"在当前会话定义/替换一个带备注的策展 TEMP VIEW：委托 wb_temp_view_create 校验并创建（p_select_sql 单条 SELECT/WITH，上限 8000 字符，比生命周期工具更严）；p_note ≤1000 字符存为视图备注（wb_temp_view_list 的 note 可见）；省略/NULL/纯空白 p_note 表示替换视图并清除旧备注","args":{"p_view":"text","p_select_sql":"text","p_note":"text"},"returns":"jsonb","session_scope":"current_session","capability":"temp_view_mutation"}}
$wb$;
