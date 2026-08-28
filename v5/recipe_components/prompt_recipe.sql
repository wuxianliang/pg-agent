-- ============================================================
-- PG-Agent v5 · recipe components (W3)
--
-- Relational recipes/slots/parts, XML compile, four prompt-slot
-- retrievers, seeded agent_system, run pinning.
-- ============================================================

CREATE TABLE IF NOT EXISTS prompt_recipes (
    recipe_name     text NOT NULL,
    version         integer NOT NULL CHECK (version > 0),
    source_xml      xml NOT NULL,
    format_version  integer NOT NULL DEFAULT 1,
    active          boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (recipe_name, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS prompt_recipes_one_active
    ON prompt_recipes (recipe_name) WHERE active;

CREATE TABLE IF NOT EXISTS prompt_slots (
    recipe_name        text NOT NULL,
    recipe_version     integer NOT NULL,
    position           integer NOT NULL CHECK (position > 0),
    slot_key           text NOT NULL,
    component_type     text NOT NULL
        CHECK (component_type IN (
            'role','task','example','output_format','tools','question','history')),
    retriever_name     text NOT NULL,
    required           boolean NOT NULL,
    generation_policy  text NOT NULL CHECK (generation_policy IN ('never','if_missing')),
    config             jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (recipe_name, recipe_version, position),
    UNIQUE (recipe_name, recipe_version, slot_key),
    FOREIGN KEY (recipe_name, recipe_version)
        REFERENCES prompt_recipes (recipe_name, version) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prompt_parts (
    recipe_name          text NOT NULL,
    recipe_version       integer NOT NULL,
    slot_key             text NOT NULL,
    component_type       text NOT NULL,
    value_kind           text NOT NULL CHECK (value_kind IN ('text','messages')),
    value                jsonb NOT NULL,
    source               text NOT NULL CHECK (source IN ('seeded','generated')),
    generator_request_id text,
    content_hash         text NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (recipe_name, recipe_version, slot_key),
    FOREIGN KEY (recipe_name, recipe_version)
        REFERENCES prompt_recipes (recipe_name, version) ON DELETE CASCADE
);

ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS prompt_recipe_name text;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS prompt_recipe_version integer;

CREATE OR REPLACE FUNCTION prompt_xml_tag(p_node xml)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT lower(COALESCE((regexp_match(btrim(p_node::text), '^<([A-Za-z0-9_-]+)'))[1], ''))
$$;

CREATE OR REPLACE FUNCTION prompt_xml_text(p_node xml)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT btrim(regexp_replace(p_node::text, '<[^>]+>', '', 'g'))
$$;

CREATE OR REPLACE FUNCTION prompt_xml_attr(p_node xml, p_name text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT (regexp_match(
        COALESCE((regexp_match(btrim(p_node::text), '^<[^>]+>'))[1], ''),
        p_name || '="([^"]*)"'
    ))[1]
$$;

CREATE OR REPLACE FUNCTION prompt_xml_attributes_valid(p_node xml)
RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_open text;
    v_m    text;
BEGIN
    v_open := COALESCE((regexp_match(btrim(p_node::text), '^<[^>]+>'))[1], '');
    FOR v_m IN SELECT (regexp_matches(v_open, '([A-Za-z0-9_-]+)=', 'g'))[1]
    LOOP
        IF v_m NOT IN ('required', 'generate', 'hint', 'slot') THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION prompt_part_hash(p_value jsonb)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(convert_to(p_value::text, 'UTF8')), 'hex')
$$;

CREATE OR REPLACE FUNCTION compile_prompt_recipe(
    p_recipe_name text,
    p_version integer,
    p_source xml,
    p_activate boolean DEFAULT false
) RETURNS integer
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_src     text;
    v_root    text;
    v_nodes   xml[];
    v_n       int;
    v_i       int;
    v_node    xml;
    v_tag     text;
    v_comp    text;
    v_key     text;
    v_req     boolean;
    v_gen     text;
    v_hint    text;
    v_retr    text;
    v_pos     int;
    v_text    text;
    v_live    boolean;
    v_cfg     jsonb;
    v_kind    text;
    v_val     jsonb;
    v_child   xml;
    v_msgs    jsonb;
    v_role    text;
    v_seen    text[] := '{}';
    v_ex_n    int := 0;
BEGIN
    IF p_recipe_name IS NULL OR p_recipe_name !~ '^[a-z][a-z0-9_]*$' THEN
        RAISE EXCEPTION 'compile_prompt_recipe: illegal recipe_name';
    END IF;
    IF p_version IS NULL OR p_version < 1 THEN
        RAISE EXCEPTION 'compile_prompt_recipe: version must be >= 1';
    END IF;
    IF EXISTS (
        SELECT 1 FROM prompt_recipes
         WHERE recipe_name = p_recipe_name AND version = p_version
    ) THEN
        RAISE EXCEPTION 'compile_prompt_recipe: version % of % already exists',
            p_version, p_recipe_name;
    END IF;

    v_src := p_source::text;
    IF v_src IS NULL OR length(v_src) > 262144 THEN
        RAISE EXCEPTION 'compile_prompt_recipe: source too large';
    END IF;
    IF v_src ~ '\{\{' OR v_src ~ '\$\{' OR v_src ~ '<include' OR v_src ~ '<let'
       OR v_src ~ '<for' OR v_src ~ '<if' OR v_src ~ 'src=' OR v_src ~ '<script' THEN
        RAISE EXCEPTION 'compile_prompt_recipe: unsupported JS/file construct';
    END IF;

    v_root := lower(btrim(COALESCE(
        (xpath('local-name(/*)', p_source))[1]::text, '')));
    IF v_root IN ('poml', '"poml"') THEN
        v_root := 'poml';
    END IF;
    IF v_root <> 'poml' THEN
        RAISE EXCEPTION 'compile_prompt_recipe: root must be <poml> (got %)', v_root;
    END IF;

    v_nodes := xpath('/poml/*', p_source);
    v_n := COALESCE(array_length(v_nodes, 1), 0);
    IF v_n = 0 THEN
        RAISE EXCEPTION 'compile_prompt_recipe: no components';
    END IF;
    IF v_n > 32 THEN
        RAISE EXCEPTION 'compile_prompt_recipe: more than 32 slots';
    END IF;

    INSERT INTO prompt_recipes (recipe_name, version, source_xml, format_version, active)
    VALUES (p_recipe_name, p_version, p_source, 1, false);

    FOR v_i IN 1..v_n LOOP
        v_node := v_nodes[v_i];
        v_tag := prompt_xml_tag(v_node);
        IF NOT prompt_xml_attributes_valid(v_node) THEN
            RAISE EXCEPTION 'compile_prompt_recipe: unsupported attribute on <%s>', v_tag;
        END IF;
        v_comp := CASE v_tag
            WHEN 'role' THEN 'role'
            WHEN 'task' THEN 'task'
            WHEN 'example' THEN 'example'
            WHEN 'output-format' THEN 'output_format'
            WHEN 'tools' THEN 'tools'
            WHEN 'question' THEN 'question'
            WHEN 'history' THEN 'history'
            ELSE NULL
        END;
        IF v_comp IS NULL THEN
            RAISE EXCEPTION 'compile_prompt_recipe: unknown tag <%s>', v_tag;
        END IF;
        IF v_comp <> 'example' AND v_comp = ANY (v_seen) THEN
            RAISE EXCEPTION 'compile_prompt_recipe: duplicate singleton %', v_comp;
        END IF;
        v_seen := array_append(v_seen, v_comp);

        v_live := v_comp IN ('tools','question','history');
        v_hint := prompt_xml_attr(v_node, 'hint');
        IF v_hint IS NOT NULL AND length(v_hint) > 500 THEN
            RAISE EXCEPTION 'compile_prompt_recipe: hint too long';
        END IF;
        v_gen := COALESCE(prompt_xml_attr(v_node, 'generate'),
                          CASE WHEN v_live THEN 'never' ELSE 'never' END);
        IF v_gen NOT IN ('never','if_missing') THEN
            RAISE EXCEPTION 'compile_prompt_recipe: illegal generate=';
        END IF;
        IF v_live AND v_gen <> 'never' THEN
            RAISE EXCEPTION 'compile_prompt_recipe: live component cannot generate';
        END IF;
        v_req := COALESCE(prompt_xml_attr(v_node, 'required'),
                          CASE WHEN v_comp = 'example' THEN 'false' ELSE 'true' END)::boolean;

        IF v_comp = 'example' THEN
            v_ex_n := v_ex_n + 1;
            v_key := COALESCE(prompt_xml_attr(v_node, 'slot'), 'example_' || v_ex_n);
        ELSE
            v_key := replace(v_comp, '-', '_');
        END IF;
        IF v_key !~ '^[A-Za-z_][A-Za-z0-9_]*$' OR length(v_key) > 64 THEN
            RAISE EXCEPTION 'compile_prompt_recipe: illegal slot_key %', v_key;
        END IF;

        v_retr := CASE v_comp
            WHEN 'tools' THEN 'prompt_live_tools'
            WHEN 'question' THEN 'prompt_live_question'
            WHEN 'history' THEN 'prompt_live_history'
            ELSE 'prompt_stored_part'
        END;
        IF NOT EXISTS (
            SELECT 1 FROM plugin_bindings
             WHERE binding_type = 'prompt_slot' AND binding_name = v_retr
        ) THEN
            RAISE EXCEPTION 'compile_prompt_recipe: missing retriever %', v_retr;
        END IF;

        v_pos := 10 * v_i;
        v_cfg := jsonb_build_object('slot_key', v_key);
        IF v_hint IS NOT NULL THEN
            v_cfg := v_cfg || jsonb_build_object('hint', v_hint);
        END IF;

        INSERT INTO prompt_slots (
            recipe_name, recipe_version, position, slot_key, component_type,
            retriever_name, required, generation_policy, config
        ) VALUES (
            p_recipe_name, p_version, v_pos, v_key, v_comp,
            v_retr, v_req, v_gen, v_cfg
        );

        IF v_live THEN
            CONTINUE;
        END IF;

        IF v_comp = 'example' THEN
            v_msgs := '[]'::jsonb;
            FOREACH v_child IN ARRAY COALESCE(
                xpath('/example/*', xmlparse(document v_node::text)),
                ARRAY[]::xml[]
            ) LOOP
                v_role := prompt_xml_tag(v_child);
                IF v_role NOT IN ('user','assistant') THEN
                    RAISE EXCEPTION 'compile_prompt_recipe: invalid example child <%s>', v_role;
                END IF;
                v_text := prompt_xml_text(v_child);
                IF v_text IS NULL OR v_text = '' OR length(v_text) > 8000 THEN
                    RAISE EXCEPTION 'compile_prompt_recipe: invalid example message';
                END IF;
                v_msgs := v_msgs || jsonb_build_array(
                    jsonb_build_object('role', v_role, 'content', v_text)
                );
            END LOOP;
            IF jsonb_array_length(v_msgs) = 0 THEN
                IF v_req AND v_gen = 'never' THEN
                    RAISE EXCEPTION 'compile_prompt_recipe: empty required example';
                END IF;
                CONTINUE;
            END IF;
            v_kind := 'messages';
            v_val := v_msgs;
        ELSE
            v_text := prompt_xml_text(v_node);
            IF v_text IS NULL OR v_text = '' THEN
                IF v_req AND v_gen = 'never' THEN
                    RAISE EXCEPTION 'compile_prompt_recipe: empty required static text for %', v_comp;
                END IF;
                CONTINUE;
            END IF;
            IF length(v_text) > 8000 THEN
                RAISE EXCEPTION 'compile_prompt_recipe: part text too long';
            END IF;
            v_kind := 'text';
            v_val := to_jsonb(v_text);
        END IF;

        INSERT INTO prompt_parts (
            recipe_name, recipe_version, slot_key, component_type,
            value_kind, value, source, content_hash
        ) VALUES (
            p_recipe_name, p_version, v_key, v_comp,
            v_kind, v_val, 'seeded', prompt_part_hash(v_val)
        );
    END LOOP;

    IF p_activate THEN
        UPDATE prompt_recipes SET active = false
         WHERE recipe_name = p_recipe_name AND active;
        UPDATE prompt_recipes SET active = true
         WHERE recipe_name = p_recipe_name AND version = p_version;
    END IF;
    RETURN p_version;
END;
$$;

CREATE OR REPLACE FUNCTION prompt_stored_part(p_run_id text, p_config jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_name text;
    v_ver  int;
    v_key  text;
    v_row  prompt_parts%ROWTYPE;
    v_msgs jsonb;
BEGIN
    SELECT prompt_recipe_name, prompt_recipe_version INTO v_name, v_ver
      FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'PROMPT_ASSEMBLY_ERROR',
            'Phase', 'Recipe', 'Problem', 'unknown run');
    END IF;
    IF p_config ? 'recipe_name' THEN
        v_name := p_config->>'recipe_name';
    END IF;
    IF p_config ? 'recipe_version' THEN
        v_ver := (p_config->>'recipe_version')::int;
    END IF;
    v_key := p_config->>'slot_key';
    IF v_key IS NULL OR v_key = '' THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'PROMPT_ASSEMBLY_ERROR',
            'Phase', 'Validation', 'Problem', 'slot_key required');
    END IF;
    SELECT * INTO v_row FROM prompt_parts
     WHERE recipe_name = v_name AND recipe_version = v_ver AND slot_key = v_key;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'PROMPT_PART_MISSING',
            'Phase', 'Resolution', 'slot_key', v_key,
            'component', p_config->>'component');
    END IF;
    IF v_row.value_kind = 'text' THEN
        v_msgs := jsonb_build_array(jsonb_build_object(
            'role', 'system', 'content', v_row.value #>> '{}'
        ));
    ELSE
        v_msgs := v_row.value;
    END IF;
    RETURN jsonb_build_object(
        'success', true, 'messages', v_msgs,
        'source', 'stored', 'component', v_row.component_type
    );
END;
$$;

COMMENT ON FUNCTION prompt_stored_part(text, jsonb) IS $v5$
{"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"prompt_stored_part","description":"Retrieve a stored role, task, example, or output-format part","component_types":["role","task","example","output_format"],"source":"stored","generation":"if_missing","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
$v5$;

CREATE OR REPLACE FUNCTION prompt_live_tools(p_run_id text, p_config jsonb)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object(
        'success', true,
        'messages', jsonb_build_array(jsonb_build_object(
            'role', 'system', 'content', render_plugin_tools()
        )),
        'source', 'live',
        'component', 'tools'
    )
$$;

COMMENT ON FUNCTION prompt_live_tools(text, jsonb) IS $v5$
{"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"prompt_live_tools","description":"Live plugin tool catalog","component_types":["tools"],"source":"live","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
$v5$;

CREATE OR REPLACE FUNCTION prompt_live_question(p_run_id text, p_config jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_q text;
BEGIN
    SELECT question INTO v_q FROM agent_runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object(
            'success', false, 'Type', 'PROMPT_ASSEMBLY_ERROR',
            'Phase', 'Recipe', 'Problem', 'unknown run');
    END IF;
    RETURN jsonb_build_object(
        'success', true,
        'messages', jsonb_build_array(jsonb_build_object('role','user','content', v_q)),
        'source', 'live',
        'component', 'question'
    );
END;
$$;

COMMENT ON FUNCTION prompt_live_question(text, jsonb) IS $v5$
{"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"prompt_live_question","description":"Current user question","component_types":["question"],"source":"live","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
$v5$;

CREATE OR REPLACE FUNCTION prompt_live_history(p_run_id text, p_config jsonb)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_steps jsonb;
    v_all   jsonb;
    v_hist  jsonb;
BEGIN
    SELECT COALESCE(jsonb_agg(jsonb_build_object('seq',seq,'kind',kind,'payload',payload)
                              ORDER BY seq), '[]'::jsonb)
      INTO v_steps
      FROM agent_steps WHERE run_id = p_run_id;
    v_all := fold_messages('', '', v_steps);
    SELECT COALESCE(jsonb_agg(e.elem ORDER BY e.ord), '[]'::jsonb)
      INTO v_hist
      FROM jsonb_array_elements(v_all) WITH ORDINALITY AS e(elem, ord)
     WHERE e.ord > 2;
    RETURN jsonb_build_object(
        'success', true,
        'messages', COALESCE(v_hist, '[]'::jsonb),
        'source', 'live',
        'component', 'history'
    );
END;
$$;

COMMENT ON FUNCTION prompt_live_history(text, jsonb) IS $v5$
{"plugin":{"name":"plugin_prompt_components"},"prompt_slot":{"name":"prompt_live_history","description":"Folded llm/tool history without system or question","component_types":["history"],"source":"live","generation":"never","args":{"p_run_id":"text","p_config":"jsonb"},"returns":"jsonb"}}
$v5$;

CREATE OR REPLACE FUNCTION prompt_pin_run()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_name text;
    v_ver  int;
BEGIN
    IF NEW.prompt_recipe_name IS NULL THEN
        IF NEW.parent_run_id IS NOT NULL THEN
            SELECT prompt_recipe_name, prompt_recipe_version
              INTO NEW.prompt_recipe_name, NEW.prompt_recipe_version
              FROM agent_runs WHERE run_id = NEW.parent_run_id;
            IF NEW.prompt_recipe_name IS NULL THEN
                RAISE EXCEPTION 'prompt_pin_run: parent has no pinned recipe';
            END IF;
        ELSE
            SELECT recipe_name, version INTO v_name, v_ver
              FROM prompt_recipes
             WHERE recipe_name = 'agent_system' AND active
             LIMIT 1;
            IF v_name IS NULL THEN
                RAISE EXCEPTION 'prompt_pin_run: no active agent_system recipe';
            END IF;
            NEW.prompt_recipe_name := v_name;
            NEW.prompt_recipe_version := v_ver;
        END IF;
    ELSE
        IF NEW.prompt_recipe_version IS NULL THEN
            RAISE EXCEPTION 'prompt_pin_run: recipe version required';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM prompt_recipes
             WHERE recipe_name = NEW.prompt_recipe_name
               AND version = NEW.prompt_recipe_version
        ) THEN
            RAISE EXCEPTION 'prompt_pin_run: unknown recipe % v%',
                NEW.prompt_recipe_name, NEW.prompt_recipe_version;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prompt_pin_run ON agent_runs;
CREATE TRIGGER trg_prompt_pin_run
    BEFORE INSERT ON agent_runs
    FOR EACH ROW
    EXECUTE PROCEDURE prompt_pin_run();

SELECT refresh_plugins();

SELECT compile_prompt_recipe(
    'agent_system',
    1,
    xmlparse(document $poml$
<poml>
  <role generate="if_missing">你是运行在 PostgreSQL 内部的 AI 数据 Agent。唯一工具是 execute_sql。Workbench 函数必须包在 SELECT execute_sql 里调用。</role>
  <task generate="if_missing">规则：
1. 需要数据必须先 execute_sql，禁止编造。
2. 一次一条 SQL，不要分号结尾。
3. 查询最多返回有界行数。
4. 写操作禁止（只读模式）；禁止 DDL。
5. 信息足够后填 final_answer 并将 action 设为 null。
6. 同一数据库会话可跨轮次保留键值：SELECT session_set('k','v')；SELECT session_get('k')。
7. 已列出的 workbench 函数在 SELECT 中调用。
8. observation 外层 success=true 不等于嵌套工具 success。</task>
  <example generate="if_missing">
    <user>South 2025-02 revenue?</user>
    <assistant>{"thought":"查表","action":"execute_sql","action_input":"SELECT revenue FROM demo_sales WHERE segment='South' AND month='2025-02'","final_answer":null}</assistant>
  </example>
  <output-format generate="if_missing">严格按此 JSON 回复（不要输出其他文字）：
{"thought":"...","action":"execute_sql 或 null","action_input":"SQL","final_answer":"答案"}</output-format>
  <tools/>
  <question/>
  <history/>
</poml>
$poml$),
    true
);

ALTER TABLE agent_runs
    ALTER COLUMN prompt_recipe_name SET NOT NULL,
    ALTER COLUMN prompt_recipe_version SET NOT NULL;
