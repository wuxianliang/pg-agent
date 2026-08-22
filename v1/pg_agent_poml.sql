-- ============================================================
-- PG-Agent · POML 渲染层
-- 依赖：pg_agent_functional.sql（exec_sql_readonly / handlers / emit_step）
--
-- 结构：
--   P1 模板引擎    —— {{var}} / <for> / <if>，纯文本展开（IMMUTABLE）
--   P2 Writer 注册 —— 组件渲染函数，注释即注册（复用元编程模式）
--   P3 内置组件    —— role/task/table/tools/list 等
--   P4 集成        —— prompt_templates 表 + agent_run 接入 POML
--
-- 口诀：模板展开是文本变换，XML 树就是 IR，Writer 递归即序列化。
-- ============================================================

-- ============================================================
-- P1. 模板引擎（渲染前对原文做纯文本展开，不碰 xml 类型）
-- ============================================================

-- {{path.to.key}} 变量替换
CREATE OR REPLACE FUNCTION poml_expand_vars(p_src text, p_params jsonb)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    m text[];
    v text;
BEGIN
    WHILE true LOOP
        m := regexp_match(p_src, '\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}');
        IF m IS NULL THEN RETURN p_src; END IF;
        v := p_params #>> string_to_array(m[1], '.');
        p_src := replace(p_src, m[0], COALESCE(v, ''));
    END LOOP;
END;
$$;

-- <for items="arr" item="x">...</for> 循环展开（可无嵌套）
CREATE OR REPLACE FUNCTION poml_expand_for(p_src text, p_params jsonb)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    m      text[];
    item   jsonb;
    body   text;
    result text;
BEGIN
    WHILE true LOOP
        m := regexp_match(p_src,
            '<for\s+items="([^"]+)"\s+item="([^"]+)"\s*>([\s\S]*?)</for>');
        IF m IS NULL THEN RETURN p_src; END IF;
        result := '';
        FOR item IN
            SELECT value FROM jsonb_array_elements(
                COALESCE(p_params #> string_to_array(m[1], '.'), '[]'::jsonb))
        LOOP
            body := replace(m[3], '{{' || m[2] || '}}',
                            CASE jsonb_typeof(item) WHEN 'object' THEN '' ELSE item #>> '{}' END);
            -- {{item.field}} 形式
            body := poml_expand_vars(body, jsonb_build_object(m[2], item));
            result := result || body;
        END LOOP;
        p_src := replace(p_src, m[0], result);
    END LOOP;
END;
$$;

-- <if cond="{{flag}}">...</if> 条件展开（变量展开后判断真值）
CREATE OR REPLACE FUNCTION poml_expand_if(p_src text)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    m text[];
BEGIN
    WHILE true LOOP
        m := regexp_match(p_src, '<if\s+cond="([^"]*)"\s*>([\s\S]*?)</if>');
        IF m IS NULL THEN RETURN p_src; END IF;
        p_src := replace(p_src, m[0],
            -- 语义：cond 展开后非空且不是显式假值即为真（适合 {{context}} 这类存在性判断）
            CASE WHEN trim(m[1]) <> ''
                  AND lower(trim(m[1])) NOT IN ('false','0','no','null')
                 THEN m[2] ELSE '' END);
    END LOOP;
END;
$$;

-- 模板展开总入口（顺序：变量 → for → 再变量 → if）
CREATE OR REPLACE FUNCTION poml_expand_template(p_src text, p_params jsonb DEFAULT '{}')
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT poml_expand_if(poml_expand_vars(poml_expand_for(poml_expand_vars(p_src, p_params), p_params), p_params));
$$;

-- ============================================================
-- P2. Writer 注册表（注释即注册，同 handlers 的元编程）
--     约定：所有 writer 签名为 (node xml, style jsonb) RETURNS text
-- ============================================================
CREATE TABLE IF NOT EXISTS poml_writers (
    tag text PRIMARY KEY,
    fn  regproc NOT NULL
);

CREATE OR REPLACE FUNCTION refresh_poml_writers()
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
    TRUNCATE poml_writers;
    INSERT INTO poml_writers (tag, fn)
    SELECT obj_description(p.oid, 'pg_proc')::jsonb ->> 'poml_writer',
           p.oid::regproc
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND obj_description(p.oid, 'pg_proc') ~ '^\s*\{'
       AND obj_description(p.oid, 'pg_proc')::jsonb ? 'poml_writer';
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

-- ---------- 三个 XML 辅助纯函数 ----------
CREATE OR REPLACE FUNCTION poml_tag(node xml) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT (xpath('name(/*)', node))[1]::text $$;

CREATE OR REPLACE FUNCTION poml_attr(node xml, p_name text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT (xpath('/*/@' || p_name, node))[1]::text $$;

-- 全部后代文本（容器组件取内容用）
CREATE OR REPLACE FUNCTION poml_text(node xml) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(array_to_string(ARRAY(
        SELECT unnest(xpath('/*//text()', node))::text), ''), '')
$$;

-- ---------- 递归渲染核心 ----------
-- 渲染子节点：文本节点 + 子元素按层拼接（简化：元素内文本先于子元素整体取，
-- 容器语义下足够；行内混排由 <b>/<p> 这类叶子 writer 用 poml_text 处理）
CREATE OR REPLACE FUNCTION poml_write_children(node xml, style jsonb DEFAULT '{}')
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    child xml;
    out   text := '';
    kids  xml[] := xpath('/*/*', node);
BEGIN
    IF array_length(kids, 1) IS NULL THEN
        RETURN trim(poml_text(node));
    END IF;
    FOREACH child IN ARRAY kids LOOP
        out := out || poml_write(child, style);
    END LOOP;
    RETURN out;
END;
$$;

CREATE OR REPLACE FUNCTION poml_write(node xml, style jsonb DEFAULT '{}')
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_tag text := poml_tag(node);
    v_fn  regproc;
    v_out text;
BEGIN
    SELECT fn INTO v_fn FROM poml_writers WHERE tag = v_tag;
    IF FOUND THEN
        EXECUTE format('SELECT %s($1,$2)', v_fn) INTO v_out USING node, style;
        RETURN v_out;
    END IF;
    -- 未注册标签按容器处理（POML 的宽容语义）
    RETURN poml_write_children(node, style);
END;
$$;

-- ---------- 渲染总入口 ----------
CREATE OR REPLACE FUNCTION poml_render(p_source text,
                                       p_params jsonb DEFAULT '{}',
                                       p_style  jsonb DEFAULT '{}')
RETURNS text
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN trim(poml_write(
        xmlparse(CONTENT poml_expand_template(p_source, p_params)),
        p_style)) || E'\n';
END;
$$;

-- ============================================================
-- P3. 内置组件（每个 10 行，注册靠注释）
-- ============================================================

CREATE OR REPLACE FUNCTION w_poml(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT poml_write_children(node, style) $$;
COMMENT ON FUNCTION w_poml(xml, jsonb) IS '{"poml_writer":"poml"}';

CREATE OR REPLACE FUNCTION w_role(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT E'**Role:** ' || poml_write_children(node, style) || E'\n\n' $$;
COMMENT ON FUNCTION w_role(xml, jsonb) IS '{"poml_writer":"role"}';

CREATE OR REPLACE FUNCTION w_task(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT E'**Task:** ' || poml_write_children(node, style) || E'\n\n' $$;
COMMENT ON FUNCTION w_task(xml, jsonb) IS '{"poml_writer":"task"}';

CREATE OR REPLACE FUNCTION w_output_format(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT E'**Output Format:** ' || poml_write_children(node, style) || E'\n\n' $$;
COMMENT ON FUNCTION w_output_format(xml, jsonb) IS '{"poml_writer":"output-format"}';

CREATE OR REPLACE FUNCTION w_example(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT E'**Example:**\n' || poml_write_children(node, style) || E'\n\n' $$;
COMMENT ON FUNCTION w_example(xml, jsonb) IS '{"poml_writer":"example"}';

CREATE OR REPLACE FUNCTION w_b(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT '**' || trim(poml_text(node)) || '**' $$;
COMMENT ON FUNCTION w_b(xml, jsonb) IS '{"poml_writer":"b"}';

CREATE OR REPLACE FUNCTION w_p(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT trim(poml_text(node)) || E'\n\n' $$;
COMMENT ON FUNCTION w_p(xml, jsonb) IS '{"poml_writer":"p"}';

CREATE OR REPLACE FUNCTION w_list(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT poml_write_children(node, style) || E'\n' $$;
COMMENT ON FUNCTION w_list(xml, jsonb) IS '{"poml_writer":"list"}';

CREATE OR REPLACE FUNCTION w_item(node xml, style jsonb) RETURNS text
LANGUAGE sql STABLE AS $$ SELECT '- ' || trim(poml_text(node)) || E'\n' $$;
COMMENT ON FUNCTION w_item(xml, jsonb) IS '{"poml_writer":"item"}';

-- ---------- 杀手锏：数据组件，SQL 直接进 prompt ----------
-- <table query="SELECT ..." limit="20"/> → Markdown 表格
CREATE OR REPLACE FUNCTION w_table(node xml, style jsonb) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_q   text := poml_attr(node, 'query');
    v_lim int  := COALESCE(poml_attr(node, 'limit')::int, 20);
    v_res jsonb;
    v_cols text[];
    v_row  jsonb;
    out    text := E'\n';
BEGIN
    v_res := exec_sql_readonly(v_q, v_lim);
    IF NOT (v_res->>'success')::boolean THEN
        RETURN E'\n[查询失败: ' || (v_res->>'error') || E']\n\n';
    END IF;
    IF jsonb_array_length(v_res->'data') = 0 THEN
        RETURN E'\n[空结果集]\n\n';
    END IF;

    v_cols := ARRAY(SELECT jsonb_object_keys(v_res->'data'->0));
    out := out || '| ' || array_to_string(v_cols, ' | ') || E' |\n'
                || '|' || repeat('---|', array_length(v_cols,1)) || E'\n';
    FOR v_row IN SELECT value FROM jsonb_array_elements(v_res->'data') LOOP
        out := out || '| ' || (
            SELECT string_agg(COALESCE(v_row->>c, '∅'), ' | ')
            FROM unnest(v_cols) c) || E' |\n';
    END LOOP;
    RETURN out || E'\n';
END;
$$;
COMMENT ON FUNCTION w_table(xml, jsonb) IS '{"poml_writer":"table"}';

-- ---------- <tools/>：扫描 handlers 注释里的 llm_tool，自动生成工具清单 ----------
CREATE OR REPLACE FUNCTION w_tools(node xml, style jsonb) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    out text := E'**可用工具:**\n';
    r record;
BEGIN
    FOR r IN
        SELECT obj_description(p.oid,'pg_proc')::jsonb -> 'llm_tool' AS tool
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND obj_description(p.oid,'pg_proc') ~ '^\s*\{'
           AND obj_description(p.oid,'pg_proc')::jsonb ? 'llm_tool'
    LOOP
        out := out || format(E'- `%s`: %s\n',
            r.tool->>'name', r.tool->>'description');
    END LOOP;
    RETURN out || E'\n';
END;
$$;
COMMENT ON FUNCTION w_tools(xml, jsonb) IS '{"poml_writer":"tools"}';

SELECT refresh_poml_writers();

-- ============================================================
-- P4. 集成：prompt 模板入库 + agent_run 换引擎
-- ============================================================

-- 模板表：prompt 从此是数据，带版本，可审计可切换
CREATE TABLE IF NOT EXISTS prompt_templates (
    template_name text NOT NULL,
    version       int  NOT NULL DEFAULT 1,
    source        text NOT NULL,          -- POML 源文本
    params        jsonb DEFAULT '{}',     -- 默认参数
    created_at    timestamptz DEFAULT now(),
    PRIMARY KEY (template_name, version)
);

CREATE OR REPLACE FUNCTION render_template(p_name text, p_params jsonb DEFAULT '{}')
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE t record;
BEGIN
    SELECT source, params INTO t FROM prompt_templates
     WHERE template_name = p_name
     ORDER BY version DESC LIMIT 1;
    IF NOT FOUND THEN RAISE EXCEPTION '模板 % 不存在', p_name; END IF;
    RETURN poml_render(t.source, t.params || p_params);   -- 调用方参数覆盖默认
END;
$$;

-- 内置模板：pg-agent 的 system prompt（替代旧的手写 format()）
INSERT INTO prompt_templates (template_name, version, source) VALUES
('agent_system', 1, $p$
<poml>
  <role>你是运行在 PostgreSQL 内部的 AI 数据 Agent。</role>
  <task>回答用户问题。需要数据时必须调用工具获取，禁止编造。</task>
  <tools/>
  <list>
    <item>严格按 JSON 回复：{"thought":"思考","action":"execute_sql 或 null","action_input":"SQL","final_answer":"答案"}</item>
    <item>一次一条 SQL，不要分号结尾，最多返回 {{max_rows}} 行</item>
    <item>信息足够后填 final_answer 并将 action 设为 null</item>
  </list>
  <if cond="{{context}}">**数据库上下文:**
{{context}}</if>
  <output-format>仅输出上述 JSON，不要任何其他文字</output-format>
</poml>$p$)
ON CONFLICT DO NOTHING;

-- ---------- 主循环重构：循环与 prompt 来源解耦 ----------
-- agent_loop 不再关心 system prompt 怎么来，只负责编排
CREATE OR REPLACE FUNCTION agent_loop(p_run_id text, p_system text, p_max_steps int)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_dec    llm_decision;
    v_raw    text;
    v_msgs   jsonb;
    v_steps  jsonb;
    v_used   int := 0;
    v_obs    jsonb;
    v_q      text;
BEGIN
    SELECT question INTO v_q FROM agent_runs WHERE run_id = p_run_id;

    WHILE v_used < p_max_steps LOOP
        SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                                  ORDER BY seq), '[]'::jsonb)
          INTO v_steps FROM agent_steps WHERE run_id = p_run_id;
        v_msgs := fold_messages(p_system, v_q, v_steps);

        v_raw := sql_retry('http_call_llm(jsonb)'::regproc, v_msgs, 2) ->> 'raw';

        BEGIN
            v_dec := parse_llm_output(v_raw);
        EXCEPTION WHEN OTHERS THEN
            PERFORM emit_step(p_run_id, 'error',
                    jsonb_build_object('message','LLM 返回非法 JSON: '||left(v_raw,300)));
            RETURN '失败：LLM 返回非法 JSON，run_id=' || p_run_id;
        END;
        PERFORM emit_step(p_run_id, 'llm', jsonb_build_object('raw', v_raw, 'thought', v_dec.thought));
        v_used := v_used + 1;

        IF v_dec.final_answer IS NOT NULL AND v_dec.action IS NULL THEN
            PERFORM emit_step(p_run_id, 'final', jsonb_build_object('answer', v_dec.final_answer));
            RETURN v_dec.final_answer;
        END IF;

        IF v_dec.action = 'execute_sql' THEN
            v_obs := exec_sql_readonly(v_dec.sql, 50);
        ELSE
            v_obs := jsonb_build_object('success',false,'error','未知 action: '||COALESCE(v_dec.action,'null'));
        END IF;
        PERFORM emit_step(p_run_id, 'tool', jsonb_build_object('sql', v_dec.sql, 'observation', v_obs::text));
    END LOOP;

    PERFORM emit_step(p_run_id, 'error', jsonb_build_object('message','达到最大步数'));
    RETURN '达到最大步数，run_id=' || p_run_id;
END;
$$;

-- 新入口：用 POML 模板渲染 system prompt
CREATE OR REPLACE FUNCTION agent_run_poml(
    p_question  text,
    p_template  text DEFAULT 'agent_system',
    p_params    jsonb DEFAULT '{}',
    p_max_steps int  DEFAULT 10
)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id text := gen_random_uuid()::text;
    v_system text;
BEGIN
    INSERT INTO agent_runs (run_id, question, max_steps)
    VALUES (v_run_id, p_question, p_max_steps);

    v_system := render_template(p_template,
                 jsonb_build_object('max_rows', '50') || p_params);

    RETURN agent_loop(v_run_id, v_system, p_max_steps);
END;
$$;

-- 旧入口保持兼容：改走 agent_loop（行为不变）
CREATE OR REPLACE FUNCTION agent_run(p_question text, p_max_steps int DEFAULT 10)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_run_id text := gen_random_uuid()::text;
BEGIN
    INSERT INTO agent_runs (run_id, question, max_steps)
    VALUES (v_run_id, p_question, p_max_steps);
    RETURN agent_loop(v_run_id, make_system_prompt(50), p_max_steps);
END;
$$;

-- ============================================================
-- 使用示例
-- ============================================================
-- SET openai.api_uri='http://127.0.0.1:11434/v1/'; SET openai.model='qwen2.5';
--
-- -- 纯渲染，不跑 agent（先检查 prompt 长什么样）：
-- SELECT poml_render($p$
-- <poml>
--   <role>你是数据分析助手</role>
--   <task>总结下表特征</task>
--   <table query="SELECT * FROM agent_runs LIMIT 5"/>
--   <output-format>三行要点</output-format>
-- </poml>$p$);
--
-- -- 跑 agent（prompt 来自模板表，带版本）：
-- SELECT agent_run_poml('agent_steps 表有多少行？');
--
-- -- 换模板 = 插一行数据，不改任何函数：
-- INSERT INTO prompt_templates (template_name, version, source)
-- VALUES ('agent_system', 2, '<poml>...</poml>');
--
-- -- 给工具加 LLM 描述（<tools/> 组件自动收进 prompt）：
-- COMMENT ON FUNCTION h_sample_table(jobs) IS
--   '{"job_handler":"sample_table",
--     "llm_tool":{"name":"sample_table","description":"抓取指定表的3行样本"}}';
