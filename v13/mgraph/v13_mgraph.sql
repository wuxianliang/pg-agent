BEGIN;

-- =========================================================================
-- DP9 M1 mgraph dark library (v13_mgraph.sql): memory_nodes/memory_links
-- two-table graph (OQ1=A: indexed one-hop JOIN face; no graph extension in
-- runtime) + per-session v13_mgraph_meta (watermark/rel_cursor semantics)
-- + memory_consolidations queue (single-row-per-key, status closed set) +
-- mgraph policy row v1 (§3.2 seed; reader fail-closed) + six mem_* template
-- families (question bytes = QUESTION_SNAPSHOT.md combination-rule v1) +
-- judgment_defaults six new mem_ points (OQ11 tri-state) + defaults reader
-- + progress reader + envelope constructor v13_mgraph_envelope (12-key set
-- aligned with the summary envelope; batch_questions = question count).
-- Design: docs/designs/v13-context-on-pg.md v2 §4.4/§6.1/§6.5/§8.
-- Plan: docs/plans/v13-dp9-memory-graph-plan-2026-09-23.md (§1.2/§1.3/§3).
-- M1 = dark library only: zero behavior functions (build/route/walk/consolidate
-- land in M2-M4). File order = load order. Error code family: V3009.
-- Zero DEFINER (§1.2-2). No graph extension DDL in this file (OQ1).
-- =========================================================================

-- === §3.1 memory_nodes(OQ4:PK (session_id,content_hash),无 corpus 列,
--     无指向 chunks 主键/seq 的 FK;episodic 正文=策展正文复制,consolidation
--     正文=生成产物;行不可变——UPDATE 触发器拒绝(V3009),DELETE 留给
--     owner 重建平面(零授权面) ===
CREATE TABLE memory_nodes (
  session_id        uuid NOT NULL REFERENCES sessions (session_id),
  content_hash      text NOT NULL,
  body              text NOT NULL CHECK (octet_length(body) > 0),
  origin            text NOT NULL CHECK (origin IN ('episodic','consolidation')),
  source_hashes     text[] NOT NULL,
  source_at         timestamptz,
  builder_version   int  NOT NULL CHECK (builder_version >= 1),
  consolidation_key text,
  PRIMARY KEY (session_id, content_hash),
  CONSTRAINT v13_mn_hash_selfcheck
    CHECK (content_hash = v13_body_hash(body)),
  CONSTRAINT v13_mn_source_hashes_shape
    CHECK (cardinality(source_hashes) >= 1),
  CONSTRAINT v13_mn_episodic_source_at
    CHECK (origin <> 'episodic' OR source_at IS NOT NULL),
  CONSTRAINT v13_mn_consolidation_shape
    CHECK (origin <> 'consolidation'
           OR (cardinality(source_hashes) >= 2
               AND consolidation_key IS NOT NULL))
);
-- 记忆语料索引(OQ7=A:候选发现走 stannum TINQL;stannum 默认配置单索引纪律,
-- memory 先例同款;本文件 `==>` 出现次数=0——候选函数 M2 才落)
CREATE INDEX ix_memory_nodes_stannum ON memory_nodes USING stannum (body);
-- 合并节点 consolidation_key 唯一(§3.1:同 key 至多一个合并产物)
CREATE UNIQUE INDEX ux_memory_nodes_consolidation_key
  ON memory_nodes (session_id, consolidation_key)
  WHERE consolidation_key IS NOT NULL;

-- 行守卫：INSERT 时校验 source_hashes 全部元素 64hex（CHECK 子查询不可用，
-- 触发器承载）；UPDATE 拒绝（行不可变，V3009）
CREATE FUNCTION v13_mgraph_nodes_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION
      'v13: memory_nodes rows are immutable (% on % %/%)',
      TG_OP, TG_TABLE_NAME, OLD.session_id, LEFT(OLD.content_hash, 12)
      USING ERRCODE = 'V3009';
  END IF;
  IF EXISTS (SELECT 1 FROM unnest(NEW.source_hashes) h
              WHERE h !~ '^[0-9a-f]{64}$') THEN
    RAISE EXCEPTION 'v13: memory_nodes source_hashes entries must be 64hex'
      USING ERRCODE = 'V3009';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_memory_nodes_guard
  BEFORE INSERT OR UPDATE ON memory_nodes
  FOR EACH ROW EXECUTE FUNCTION v13_mgraph_nodes_guard();

-- === §3.1 memory_links(Jev 边只插不改写:阈值变了=新策略版本重放 raw
--     answer,旧边留待 episodic 重建;rel 九值闭集;jev 边必须携带本 session
--     的 decision(OQ11:不放宽);两端悬空由校验器查(M2 落地) ===
CREATE TABLE memory_links (
  session_id     uuid NOT NULL REFERENCES sessions (session_id),
  src_hash       text NOT NULL CHECK (src_hash ~ '^[0-9a-f]{64}$'),
  dst_hash       text NOT NULL CHECK (dst_hash ~ '^[0-9a-f]{64}$'),
  rel            text NOT NULL CHECK (rel IN
                 ('semantic','causes','caused_by','entity','temporal',
                  'proximity','contradicts','redundant_with','related_to')),
  origin         text NOT NULL CHECK (origin IN
                 ('jev','temporal','proximity','consolidation')),
  decision_id    uuid,
  structural     numeric,
  policy_version int  NOT NULL CHECK (policy_version >= 1),
  PRIMARY KEY (session_id, src_hash, dst_hash, rel, origin),
  CONSTRAINT v13_ml_jev_needs_decision
    CHECK (origin <> 'jev' OR decision_id IS NOT NULL)
);

-- 一跳 JOIN 的两向 btree(OQ1 机制:桶→rel 过滤经 rels[] 入参承载;
-- 邻居函数 M2 落地,索引先行)
CREATE INDEX ix_memory_links_src
  ON memory_links (session_id, src_hash, rel);
CREATE INDEX ix_memory_links_dst
  ON memory_links (session_id, dst_hash, rel);

CREATE FUNCTION v13_mgraph_links_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION
    'v13: memory_links rows are immutable (% on % %->% %)',
    TG_OP, TG_TABLE_NAME, LEFT(OLD.src_hash, 12), LEFT(OLD.dst_hash, 12), OLD.rel
    USING ERRCODE = 'V3009';
END $$;
CREATE TRIGGER trg_memory_links_immutable
  BEFORE UPDATE ON memory_links
  FOR EACH ROW EXECUTE FUNCTION v13_mgraph_links_immutable();

-- === §3.1 v13_mgraph_meta(每会话至多一行,build 首写;初值语义:
--     watermark=-1(尚未覆盖任何 transcript 行)、rel_cursor=NULL(从未发
--     问)、generation=0、nodes_since_consolidate=0——M1 暗库零行,读取器
--     v13_mgraph_progress 对无行会话返回同一组初值) ===
CREATE TABLE v13_mgraph_meta (
  session_id             uuid PRIMARY KEY REFERENCES sessions (session_id),
  generation             bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
  transcript_watermark   bigint NOT NULL DEFAULT -1,
  rel_cursor             text CHECK (rel_cursor IS NULL
                                    OR rel_cursor ~ '^[0-9a-f]{64}$'),
  nodes_since_consolidate int NOT NULL DEFAULT 0
                            CHECK (nodes_since_consolidate >= 0)
);

-- === §3.1 memory_consolidations(固化队列表:同 key 至多一行——重试语义
--     由 effect attempt 承载;status 闭集 queued|generating|adopted|rejected,
--     「rejected 可审计」的载体;M4 消费,M1 仅暗库在位) ===
CREATE TABLE memory_consolidations (
  session_id        uuid NOT NULL REFERENCES sessions (session_id),
  consolidation_key text NOT NULL CHECK (consolidation_key ~ '^[0-9a-f]{64}$'),
  status            text NOT NULL CHECK (status IN
                    ('queued','generating','adopted','rejected')),
  effect_id         uuid,
  body_hash         text CHECK (body_hash IS NULL
                                 OR body_hash ~ '^[0-9a-f]{64}$'),
  decided_at        timestamptz,
  PRIMARY KEY (session_id, consolidation_key)
);

-- === §3.2 mgraph 策略行 v1 种子(OQ9 裁决后逐键;consolidate_max_body_bytes
--     来源=v13 本地护栏(对齐 summary_accept.checks.max_body_bytes 量级),
--     非 Jev-Mem 默认值;三帽单位同为 ask 批数:maximum_jev_calls(一次
--     read walk)/write_max_batches(每 tick)/write_max_asks(每次 build),
--     共同下游=judge_spend;write/read 默认双 false=部署暗) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('mgraph', 1, '{
  "relation_threshold": 0.60, "candidate_top_k": 10,
  "total_graph_budget": 20, "probability_exponent": 1.5,
  "graph_activation_threshold": 0.15, "beam_width": 5, "maximum_depth": 5,
  "maximum_nodes": 30, "maximum_edges": 200, "maximum_jev_calls": 10,
  "max_latency_ms": 15000,
  "transition_weights": [0.25, 0.35, 0.15, 0.15, 0.10],
  "transition_recency_coef": 0.10,
  "evidence_sufficient_min": 0.85, "missing_stop_hi": 0.40,
  "contradiction_stop_hi": 0.40, "continue_min": 0.40,
  "consolidation_threshold": 0.85, "consolidation_choice_min": 0.85,
  "consolidation_priority": ["contradiction", "redundant", "link"],
  "lexical_coef": 2, "entity_coef": 2, "keyword_coef": 1,
  "candidate_recency_coef": 0.25, "candidate_recency_halflife_s": 86400,
  "keyword_cap": 15, "write_enabled": false, "read_enabled": false,
  "admission_enabled": false, "routing_mode": "deterministic",
  "routing_shadow": false, "write_max_batches": 8,
  "consolidate_mode": "manual", "consolidation_interval": 0,
  "deterministic_floor": 1, "inject_top_k": 5,
  "entity_stopwords": [],
  "consolidate_max_body_bytes": 32768,
  "write_max_asks": 64
}'::jsonb, true);

-- === §3.2 形状校验器+策略读取器 v13_mgraph_policy()(fail-closed:无活动
--     行/键集漂移/类型域违例/权重和≠1/priority 非三值排列 → V3009;
--     「保留但响亮」键执法:admission_enabled=true 或 consolidate_mode 非
--     manual(=v1 无实现即配置错误)→ V3009;函数体零动作阈字面量,0/1
--     域界与数组形状常数除外;M2+ 的 build/route/run_round 只经本读取器
--     取值) ===
CREATE FUNCTION v13_mgraph_policy() RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v        jsonb;
  v_keys   text;
  v_bools  text[] := ARRAY['write_enabled','read_enabled','admission_enabled',
                           'routing_shadow'];
  v_unit   text[] := ARRAY['relation_threshold','graph_activation_threshold',
                           'evidence_sufficient_min','missing_stop_hi',
                           'contradiction_stop_hi','continue_min',
                           'consolidation_threshold','consolidation_choice_min',
                           'transition_recency_coef','candidate_recency_coef'];
  v_posnum text[] := ARRAY['probability_exponent'];
  v_nnnnum text[] := ARRAY['lexical_coef','entity_coef','keyword_coef'];
  v_posint text[] := ARRAY['candidate_top_k','total_graph_budget','beam_width',
                           'maximum_depth','maximum_nodes','maximum_edges',
                           'maximum_jev_calls','max_latency_ms','keyword_cap',
                           'candidate_recency_halflife_s','write_max_batches',
                           'deterministic_floor','inject_top_k',
                           'consolidate_max_body_bytes','write_max_asks'];
  v_nznint text[] := ARRAY['consolidation_interval'];
  k        text;
BEGIN
  SELECT value INTO v FROM v13_policies WHERE name = 'mgraph' AND active;
  IF v IS NULL THEN
    RAISE EXCEPTION 'v13: no active mgraph policy row (seed lost?)'
      USING ERRCODE = 'V3009';
  END IF;
  SELECT string_agg(ok, ',' ORDER BY ok) INTO v_keys
    FROM jsonb_object_keys(v) ok;
  IF v_keys IS DISTINCT FROM
     'admission_enabled,beam_width,candidate_recency_coef,candidate_recency_halflife_s,candidate_top_k,consolidate_max_body_bytes,consolidate_mode,consolidation_choice_min,consolidation_interval,consolidation_priority,consolidation_threshold,continue_min,contradiction_stop_hi,deterministic_floor,entity_coef,entity_stopwords,evidence_sufficient_min,graph_activation_threshold,inject_top_k,keyword_cap,keyword_coef,lexical_coef,max_latency_ms,maximum_depth,maximum_edges,maximum_jev_calls,maximum_nodes,missing_stop_hi,probability_exponent,read_enabled,relation_threshold,routing_mode,routing_shadow,total_graph_budget,transition_recency_coef,transition_weights,write_enabled,write_max_asks,write_max_batches' THEN
    RAISE EXCEPTION 'v13: mgraph policy key set mismatch (%)', v_keys
      USING ERRCODE = 'V3009';
  END IF;
  FOREACH k IN ARRAY v_bools LOOP
    IF jsonb_typeof(v->k) IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be boolean', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY (v_unit || v_posnum || v_nnnnum) LOOP
    IF jsonb_typeof(v->k) IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be number', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY v_unit LOOP
    IF (v->>k)::numeric < 0 OR (v->>k)::numeric > 1 THEN
      RAISE EXCEPTION 'v13: mgraph policy key % outside [0,1]', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY v_posnum LOOP
    IF (v->>k)::numeric <= 0 THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be positive', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY v_nnnnum LOOP
    IF (v->>k)::numeric < 0 THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be >= 0', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY (v_posint || v_nznint) LOOP
    IF (v->>k) !~ '^[0-9]+$' THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be an integer', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY v_posint LOOP
    IF (v->>k)::int < 1 THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be >= 1', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  FOREACH k IN ARRAY v_nznint LOOP
    IF (v->>k)::int < 0 THEN
      RAISE EXCEPTION 'v13: mgraph policy key % must be >= 0', k
        USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  IF v->>'routing_mode' NOT IN ('deterministic','jev') THEN
    RAISE EXCEPTION 'v13: mgraph policy routing_mode closed set violated (%)',
      v->>'routing_mode' USING ERRCODE = 'V3009';
  END IF;
  IF jsonb_typeof(v->'entity_stopwords') IS DISTINCT FROM 'array'
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(v->'entity_stopwords') e
                 WHERE jsonb_typeof(e) IS DISTINCT FROM 'string') THEN
    RAISE EXCEPTION 'v13: mgraph policy entity_stopwords must be string array'
      USING ERRCODE = 'V3009';
  END IF;
  IF jsonb_typeof(v->'transition_weights') IS DISTINCT FROM 'array'
     OR (SELECT count(*) FROM jsonb_array_elements(v->'transition_weights')) <> 5
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(v->'transition_weights') e
                 WHERE jsonb_typeof(e) IS DISTINCT FROM 'number'
                    OR (e#>>'{}')::numeric < 0)
     OR (SELECT sum((e#>>'{}')::numeric)
           FROM jsonb_array_elements(v->'transition_weights') e) <> 1 THEN
    RAISE EXCEPTION
      'v13: mgraph policy transition_weights must be 5 non-negative numbers summing to 1'
      USING ERRCODE = 'V3009';
  END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(v->'consolidation_priority') e) <> 3
     OR (SELECT string_agg(e#>>'{}', ',' ORDER BY e#>>'{}')
           FROM jsonb_array_elements(v->'consolidation_priority') e)
        IS DISTINCT FROM 'contradiction,link,redundant' THEN
    RAISE EXCEPTION
      'v13: mgraph policy consolidation_priority must be a permutation of contradiction/redundant/link'
      USING ERRCODE = 'V3009';
  END IF;
  -- 「保留但响亮」键:v1 无实现的配置即配置错误,读取时炸(fail-closed)
  IF (v->>'admission_enabled')::boolean THEN
    RAISE EXCEPTION
      'v13: mgraph admission_enabled=true has no implementation (OQ5: config error)'
      USING ERRCODE = 'V3009';
  END IF;
  IF v->>'consolidate_mode' IS DISTINCT FROM 'manual' THEN
    RAISE EXCEPTION
      'v13: mgraph consolidate_mode % has no implementation (v1 manual only)',
      v->>'consolidate_mode' USING ERRCODE = 'V3009';
  END IF;
  RETURN v;
END $$;

-- === 六族 mem_* 模板注册(§3.3;题面=QUESTION_SNAPSHOT.md 组合规则 v1 的
--     组合串,闸门文本全等;draft→内容行→freeze 仪式照 summary/filter 先例;
--     epoch='pre-finalize' 显式(列默认 pre-bind);writer/wire/canon=v13_resolve/1/1;
--     投影禁 ["*"];criteria:noul 族 NULL(上游 true/false 文本已并入 question),
--     choice 族(仅 mem_cons_representation)保留闭集对象 ===
INSERT INTO v13_judgment_template_versions (template_name, template_version) VALUES ('mem_type_episodic', 1), ('mem_type_semantic', 1), ('mem_type_procedural', 1), ('mem_type_preference', 1), ('mem_rel_semantic', 1), ('mem_rel_causes', 1), ('mem_rel_caused_by', 1), ('mem_rel_entity', 1), ('mem_cons_redundant', 1), ('mem_cons_contradiction', 1), ('mem_cons_obsolete', 1), ('mem_cons_link', 1), ('mem_cons_representation', 1), ('mem_routing_semantic', 1), ('mem_routing_temporal', 1), ('mem_routing_causal', 1), ('mem_routing_entity', 1), ('mem_routing_multi_hop_need', 1), ('mem_routing_recency_importance', 1), ('mem_stop_sufficient', 1), ('mem_stop_continue', 1), ('mem_stop_missing', 1), ('mem_stop_contradiction', 1), ('mem_trav_relevance', 1), ('mem_trav_relation_usefulness', 1), ('mem_trav_new_information', 1), ('mem_trav_supports', 1), ('mem_cons_fidelity', 1);

INSERT INTO judgment_templates (template_name, template_version, kind, epoch,
                                question, criteria, answer_schema_version,
                                projection, writer, wire_version, canon_version)
VALUES
('mem_type_episodic', 1, 'noul', 'pre-finalize',
 'Does `observation` describe a particular experience or event involving a participant? TRUE if: A specific past, current or planned event, even if its exact time is unstated. FALSE if: Only a general fact, procedure or preference with no particular event.',
 NULL, 1, '["body"]'::jsonb, 'v13_resolve', 1, 1),
('mem_type_semantic', 1, 'noul', 'pre-finalize',
 'Does `observation` state a fact about a person, entity or the world that remains useful beyond this conversational turn? TRUE if: An attributable fact or relationship, even when it also appears in an episodic account. FALSE if: Only a transient conversational acknowledgement or a question with no asserted fact.',
 NULL, 1, '["body"]'::jsonb, 'v13_resolve', 1, 1),
('mem_type_procedural', 1, 'noul', 'pre-finalize',
 'Does `observation` describe how to carry out a task? TRUE if: An instruction, ordered step, method or actionable rule for performing a task. FALSE if: Merely mentions doing a task without describing how.',
 NULL, 1, '["body"]'::jsonb, 'v13_resolve', 1, 1),
('mem_type_preference', 1, 'noul', 'pre-finalize',
 'Does `observation` express a participant''s preference, aversion or habitual choice? TRUE if: An attributable like, dislike, preferred option or habitual choice. FALSE if: An isolated action alone, another person''s unattributed preference, or no preference evidence.',
 NULL, 1, '["body"]'::jsonb, 'v13_resolve', 1, 1),
('mem_rel_semantic', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Would a semantic link between these observations help retrieve a shared specific topic or fact? TRUE if: A specific shared topic, fact or event makes the connection useful. FALSE if: Only generic conversational vocabulary or no meaningful semantic connection.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_rel_causes', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Does the event in `new_memory.content` cause, enable or explain the candidate event? TRUE if: The supplied accounts support this direction of causal influence. FALSE if: Only similarity, chronology, a shared entity, or insufficient causal evidence.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_rel_caused_by', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Does the candidate event cause, enable or explain the event in `new_memory.content`? TRUE if: The supplied accounts support this direction of causal influence. FALSE if: Only similarity, chronology, a shared entity, or insufficient causal evidence.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_rel_entity', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Using `new_memory.entities` and `candidates[0].entities`, do any names or aliases refer to the same real-world entity? TRUE if: Context supports a shared identity despite differing names or aliases. FALSE if: Distinct entities or insufficient evidence to resolve the alias; similar names alone are insufficient.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_cons_redundant', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Do these observations repeat the same fact with no additional recallable detail? TRUE if: One is a duplicate or paraphrase without a new detail or time-specific update. FALSE if: They provide different details or describe distinct occurrences.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_cons_contradiction', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Do these accounts assert incompatible facts about the same subject at the same time? TRUE if: Claims cannot both hold at the stated time and context. FALSE if: Compatible claims, uncertainty, or a change over time that explains the difference.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_cons_obsolete', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Does the new memory explicitly replace the candidate''s previously valid fact with an updated fact? TRUE if: An explicit update supersedes the earlier fact for current-state questions. FALSE if: No explicit replacement; mere recency or a separate event is insufficient.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_cons_link', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Would following a link between these observations help answer a future recall question? TRUE if: The connection supplies related, corroborating, correcting or contrasting evidence. FALSE if: There is no specific connection useful for recall.',
 NULL, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_cons_representation', 1, 'choice', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Which representation best fits the relationship between these two observations? Judge from the supplied accounts; do not assume answers to other questions.',
 '{"keep_separate": "Contradictory accounts, unique details that a combined representation would lose, or distinct facts/events without a supported general pattern.", "merge": "Compatible accounts of the same fact or event can be combined without losing unique details.", "promote": "Distinct repeated episodes explicitly support a stable general pattern suitable for semantic abstraction; prefer this over merge for repeated events.", "uncertain": "Insufficient evidence to choose a safe combined or separate representation."}'::jsonb, 1, '["left","right"]'::jsonb, 'v13_resolve', 1, 1),
('mem_routing_semantic', 1, 'noul', 'pre-finalize',
 'Would finding topically or semantically related memories help answer `query`? TRUE if: Recall of related facts is useful. FALSE if: No related-memory lookup is needed.',
 NULL, 1, '["query"]'::jsonb, 'v13_resolve', 1, 1),
('mem_routing_temporal', 1, 'noul', 'pre-finalize',
 'Does answering `query` require event dates, durations, ordering or changes over time? TRUE if: A time relation is needed to answer correctly. FALSE if: Dates or ordering are incidental to the answer.',
 NULL, 1, '["query"]'::jsonb, 'v13_resolve', 1, 1),
('mem_routing_causal', 1, 'noul', 'pre-finalize',
 'Does answering `query` require explaining a cause, motivation, enabling condition or effect? TRUE if: Causal or explanatory evidence is needed. FALSE if: Only factual association or chronology is requested.',
 NULL, 1, '["query"]'::jsonb, 'v13_resolve', 1, 1),
('mem_routing_entity', 1, 'noul', 'pre-finalize',
 'Would connecting mentions of the same person, place, object or organization help answer `query`? TRUE if: Combining entity-specific facts or aliases is useful. FALSE if: Entity identity is irrelevant to the answer.',
 NULL, 1, '["query"]'::jsonb, 'v13_resolve', 1, 1),
('mem_routing_multi_hop_need', 1, 'noul', 'pre-finalize',
 'Does `query` require combining at least two distinct pieces of remembered evidence? TRUE if: The question asks for a comparison, aggregation or chained inference. FALSE if: One direct remembered fact suffices.',
 NULL, 1, '["query"]'::jsonb, 'v13_resolve', 1, 1),
('mem_routing_recency_importance', 1, 'noul', 'pre-finalize',
 'Does `query` require the latest applicable fact rather than a historical fact? TRUE if: Current state, latest update or recent status is requested. FALSE if: Historical or timeless facts answer the question.',
 NULL, 1, '["query"]'::jsonb, 'v13_resolve', 1, 1),
('mem_stop_sufficient', 1, 'noul', 'pre-finalize',
 'Does `evidence` contain support for every factual part of an answer to `query`? TRUE if: A grounded answer can be given from these memories without inventing missing facts. FALSE if: Any required fact or reasoning link is unsupported; related topics alone are insufficient.',
 NULL, 1, '["query","evidence"]'::jsonb, 'v13_resolve', 1, 1),
('mem_stop_continue', 1, 'noul', 'pre-finalize',
 'Given `query` and `evidence`, is another retrieval round likely to fill a specific gap or resolve a conflict? TRUE if: An identifiable missing fact or conflict could benefit from more memory retrieval. FALSE if: No identifiable retrieval need remains or more memories are unlikely to help.',
 NULL, 1, '["query","evidence"]'::jsonb, 'v13_resolve', 1, 1),
('mem_stop_missing', 1, 'noul', 'pre-finalize',
 'Is at least one fact required by `query` absent from `evidence`? TRUE if: A required detail, date, identity, count or linking fact is not supported. FALSE if: All required facts have explicit support in the supplied evidence.',
 NULL, 1, '["query","evidence"]'::jsonb, 'v13_resolve', 1, 1),
('mem_stop_contradiction', 1, 'noul', 'pre-finalize',
 'Does `evidence` contain conflicting claims relevant to `query` that the supplied time/context cannot reconcile? TRUE if: A conflict still affects which answer is correct. FALSE if: Claims agree, differ only by explained temporal updates, or do not affect the answer.',
 NULL, 1, '["query","evidence"]'::jsonb, 'v13_resolve', 1, 1),
('mem_trav_relevance', 1, 'noul', 'pre-finalize',
 'Does `candidates[0].content` contain a fact needed to answer `query`? TRUE if: Direct answer evidence or a necessary intermediate fact. FALSE if: Only topic overlap or unrelated content.',
 NULL, 1, '["query","candidate","path"]'::jsonb, 'v13_resolve', 1, 1),
('mem_trav_relation_usefulness', 1, 'noul', 'pre-finalize',
 'Does the stated graph relation of `candidates[0]` connect `evidence` to information useful for `query`? TRUE if: The relation and its direction support an answer-relevant connection. FALSE if: A graph edge exists but has no demonstrated usefulness for this question.',
 NULL, 1, '["query","candidate","path"]'::jsonb, 'v13_resolve', 1, 1),
('mem_trav_new_information', 1, 'noul', 'pre-finalize',
 'Does `candidates[0].content` add an answer-relevant detail absent from `evidence`? TRUE if: A distinct relevant detail or missing reasoning link. FALSE if: Only duplicated evidence or irrelevant new details.',
 NULL, 1, '["query","candidate","path"]'::jsonb, 'v13_resolve', 1, 1),
('mem_trav_supports', 1, 'noul', 'pre-finalize',
 'Does `candidates[0].content` independently corroborate a claim in `evidence` relevant to `query`? TRUE if: Provides compatible corroborating evidence for a specific claim. FALSE if: No specific corroboration, or contradicts that claim.',
 NULL, 1, '["query","candidate","path"]'::jsonb, 'v13_resolve', 1, 1),
('mem_cons_fidelity', 1, 'noul', 'pre-finalize',
 'Does the consolidated memory faithfully preserve the load-bearing content of both source memories (protected IDs, paths, numbers, tool pairings, decisions)? answer yes/no',
 NULL, 1, '["source","summary"]'::jsonb, 'v13_resolve', 1, 1);

UPDATE v13_judgment_template_versions SET state = 'frozen'
 WHERE template_name IN ('mem_type_episodic', 'mem_type_semantic', 'mem_type_procedural', 'mem_type_preference', 'mem_rel_semantic', 'mem_rel_causes', 'mem_rel_caused_by', 'mem_rel_entity', 'mem_cons_redundant', 'mem_cons_contradiction', 'mem_cons_obsolete', 'mem_cons_link', 'mem_cons_representation', 'mem_routing_semantic', 'mem_routing_temporal', 'mem_routing_causal', 'mem_routing_entity', 'mem_routing_multi_hop_need', 'mem_routing_recency_importance', 'mem_stop_sufficient', 'mem_stop_continue', 'mem_stop_missing', 'mem_stop_contradiction', 'mem_trav_relevance', 'mem_trav_relation_usefulness', 'mem_trav_new_information', 'mem_trav_supports', 'mem_cons_fidelity') AND template_version = 1;

-- === §3.2 judgment_defaults 追点(OQ11 三态:mem_relation/mem_type/mem_cons/
--     mem_stopping/mem_routing 三态全 exclude;mem_traversal 三态全 degrade;
--     既有 chunk_score/corpus_exists/summary_accept 三 point 原样保留,翻后
--     共九 point;翻版 DO 块照 summary `$dp7def$` 形态:读活动行→新版本
--     inactive→双 UPDATE 翻 active;jdef v3→v4 ⇒ 全域恰一次装配 refresh
--     (不变量 14 已知代价,README 运维纪律) ===
DO $dp9def$
DECLARE v_old jsonb; v_new int;
BEGIN
  SELECT value INTO v_old FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  SELECT coalesce(max(version), 0) + 1 INTO v_new
   FROM v13_policies WHERE name = 'judgment_defaults';
  INSERT INTO v13_policies (name, version, value, active)
  VALUES ('judgment_defaults', v_new,
          jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set(jsonb_set(v_old,
            '{points,mem_relation}',
            '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb),
            '{points,mem_type}',
            '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb),
            '{points,mem_cons}',
            '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb),
            '{points,mem_traversal}',
            '{"missing":"degrade","timeout":"degrade","review":"degrade"}'::jsonb),
            '{points,mem_stopping}',
            '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb),
            '{points,mem_routing}',
            '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb),
          false);
  UPDATE v13_policies SET active = false
   WHERE name = 'judgment_defaults' AND active;
  UPDATE v13_policies SET active = true
   WHERE name = 'judgment_defaults' AND version = v_new;
END
$dp9def$;

-- === §3.2 defaults 读取器(缺 point/缺态 → V3009;只读 mem_ 前缀 point——
--     mgraph 自己的缺省面;动作须在 actions 词表内,belt) ===
CREATE FUNCTION v13_mgraph_defaults_action(p_point text, p_state text)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE v jsonb; v_pt jsonb; v_act text;
BEGIN
  SELECT value INTO v FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  IF v IS NULL THEN
    RAISE EXCEPTION 'v13: no active judgment_defaults policy (seed lost?)'
      USING ERRCODE = 'V3009';
  END IF;
  IF p_point IS NULL OR left(coalesce(p_point, ''), 4) <> 'mem_' THEN
    RAISE EXCEPTION 'v13: mgraph defaults reader serves mem_ points only (%)',
      coalesce(p_point, 'NULL') USING ERRCODE = 'V3009';
  END IF;
  v_pt := v->'points'->p_point;
  IF v_pt IS NULL OR jsonb_typeof(v_pt) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: judgment_defaults point % missing', p_point
      USING ERRCODE = 'V3009';
  END IF;
  IF p_state IS NULL OR v_pt->>p_state IS NULL THEN
    RAISE EXCEPTION 'v13: judgment_defaults point % has no state %',
      p_point, coalesce(p_state, 'NULL') USING ERRCODE = 'V3009';
  END IF;
  v_act := v_pt->>p_state;
  IF NOT (v->'actions') ? v_act THEN
    RAISE EXCEPTION 'v13: judgment_defaults point % state % action % off vocabulary',
      p_point, p_state, v_act USING ERRCODE = 'V3009';
  END IF;
  RETURN v_act;
END $$;

-- === 进度读取器(v13_mgraph_meta 初值语义的读面:无行会话返回
--     {generation:0,watermark:-1,rel_cursor:null,nodes_since_consolidate:0};
--     M2 build 落行后读实值;A8 依赖) ===
CREATE FUNCTION v13_mgraph_progress(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE m v13_mgraph_meta%ROWTYPE;
BEGIN
  SELECT * INTO m FROM v13_mgraph_meta WHERE session_id = p_sid;
  RETURN jsonb_build_object(
    'generation', coalesce(m.generation, 0),
    'watermark', coalesce(m.transcript_watermark, -1),
    'rel_cursor', m.rel_cursor,
    'nodes_since_consolidate', coalesce(m.nodes_since_consolidate, 0));
END $$;

-- === §3.3 信封构造器 v13_mgraph_envelope(键集对齐活体 summary 信封十二键:
--     sid,ctx,needed,templates,groups,budget,timeout_ms,candidate_set_hash,
--     provider,model,goal_hash,candidates;groups 恰一元素——一信封=一 state,
--     全部问题须共享同一 projection(不变量 7);batch_questions=问题数(同
--     state 上限 32,不照抄摘要信封的 1);candidates 恒 [];goal_hash 恒带
--     (filter 代活体必读);candidate_set_hash=本批 signal 集合+state 的
--     sha256——与文档召回 csh 同列异义(运维注记,不改列);provider/model
--     经 GUC fail-closed。题面/模板体零重述:needed 行直取冻结模板行) ===
CREATE FUNCTION v13_mgraph_envelope(p_sid uuid, p_state jsonb, p_questions jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_provider text; v_model text;
  v_n int; v_q jsonb; v_t judgment_templates%ROWTYPE;
  v_needed jsonb := '[]'::jsonb;
  v_templates jsonb := '{}'::jsonb;
  v_signals text[] := '{}';
  v_pkey text; v_proj jsonb;
BEGIN
  IF p_state IS NULL OR jsonb_typeof(p_state) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: mgraph envelope state must be a jsonb object'
      USING ERRCODE = 'V3009';
  END IF;
  IF p_questions IS NULL OR jsonb_typeof(p_questions) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: mgraph envelope questions must be a jsonb array'
      USING ERRCODE = 'V3009';
  END IF;
  v_n := jsonb_array_length(p_questions);
  IF v_n < 1 OR v_n > 32 THEN
    RAISE EXCEPTION 'v13: mgraph envelope needs 1..32 questions (one state per envelope)'
      USING ERRCODE = 'V3009';
  END IF;
  SELECT v13_guc_required('typesafe.provider'),
         v13_guc_required('typesafe.model')
    INTO v_provider, v_model;
  FOR v_q IN SELECT value FROM jsonb_array_elements(p_questions) LOOP
    IF jsonb_typeof(v_q) IS DISTINCT FROM 'object'
       OR v_q->>'signal' IS NULL OR btrim(v_q->>'signal') = ''
       OR v_q->>'template_name' IS NULL THEN
      RAISE EXCEPTION 'v13: mgraph envelope question entries need signal+template_name'
        USING ERRCODE = 'V3009';
    END IF;
    IF left(v_q->>'signal', 4) <> 'mem_' THEN
      RAISE EXCEPTION 'v13: mgraph envelope signals must carry the mem_ prefix (%)',
        v_q->>'signal' USING ERRCODE = 'V3009';
    END IF;
    IF v_q->>'signal' = ANY(v_signals) THEN
      RAISE EXCEPTION 'v13: mgraph envelope duplicate signal (%)', v_q->>'signal'
        USING ERRCODE = 'V3009';
    END IF;
    SELECT t.* INTO v_t
      FROM judgment_templates t
      JOIN v13_judgment_template_versions w
        ON w.template_name = t.template_name
       AND w.template_version = t.template_version
     WHERE t.template_name = v_q->>'template_name' AND w.state = 'frozen'
     ORDER BY t.template_version DESC LIMIT 1;
    IF v_t.template_name IS NULL THEN
      RAISE EXCEPTION 'v13: frozen template % missing (seed lost?)',
        v_q->>'template_name' USING ERRCODE = 'V3009';
    END IF;
    v_proj := v_t.projection;
    IF v_pkey IS NULL THEN
      v_pkey := v13_projection_key(v_proj);
      IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(v_proj) p
                  WHERE NOT p_state ? p) THEN
        RAISE EXCEPTION
          'v13: mgraph envelope state misses a projection path (%)', v_pkey
          USING ERRCODE = 'V3009';
      END IF;
    ELSIF v13_projection_key(v_proj) IS DISTINCT FROM v_pkey THEN
      RAISE EXCEPTION
        'v13: mgraph envelope questions must share one projection (one state per envelope)'
        USING ERRCODE = 'V3009';
    END IF;
    v_needed := v_needed || (
      CASE WHEN v_t.criteria IS NULL THEN
        jsonb_build_object('signal', v_q->>'signal', 'kind', v_t.kind,
                           'question', v_t.question,
                           'template_name', v_t.template_name)
      ELSE
        jsonb_build_object('signal', v_q->>'signal', 'kind', v_t.kind,
                           'question', v_t.question,
                           'criteria', v_t.criteria,
                           'template_name', v_t.template_name)
      END);
    v_templates := v_templates || jsonb_build_object(v_t.template_name,
      jsonb_build_object('version', v_t.template_version, 'kind', v_t.kind,
                         'projection', v_t.projection,
                         'answer_schema_version', v_t.answer_schema_version));
    v_signals := v_signals || ARRAY[v_q->>'signal'];
  END LOOP;
  RETURN jsonb_build_object(
    'sid', p_sid,
    'ctx', p_state,
    'needed', v_needed,
    'templates', v_templates,
    'groups', jsonb_build_array(jsonb_build_object(
       'projection_key', v_pkey, 'state', p_state)),
    'budget', jsonb_build_object('batch_questions', v_n),
    'timeout_ms', NULLIF(current_setting('typesafe.timeout_ms', true), ''),
    'candidate_set_hash',
      encode(digest(jsonb_build_object(
        'signals', (SELECT jsonb_agg(s ORDER BY s) FROM unnest(v_signals) s),
        'state', p_state)::text, 'sha256'), 'hex'),
    'provider', v_provider, 'model', v_model,
    'goal_hash', v13_goal_hash(p_sid),
    'candidates', '[]'::jsonb);
END $$;

-- === §4 ACL(M1 面;M2-M4 各自追加其函数面;列举式 REVOKE,零 DEFINER) ===
REVOKE ALL ON memory_nodes, memory_links, v13_mgraph_meta,
                memory_consolidations FROM PUBLIC;
GRANT SELECT ON memory_nodes, memory_links, v13_mgraph_meta,
                 memory_consolidations
  TO v13_recall, v13_resolve, v13_route;      -- recall=SELECT 图(+meta/queue 读)
GRANT INSERT ON memory_nodes, memory_links TO v13_resolve;  -- resolve=INSERT 节点/边
GRANT UPDATE ON memory_consolidations TO v13_resolve;       -- settle 面(M4)
GRANT INSERT, UPDATE ON memory_consolidations TO v13_route; -- 队列写入面(M4)
-- 函数面
REVOKE EXECUTE ON FUNCTION
  v13_mgraph_nodes_guard(), v13_mgraph_links_immutable(),
  v13_mgraph_policy(), v13_mgraph_defaults_action(text,text),
  v13_mgraph_progress(uuid), v13_mgraph_envelope(uuid,jsonb,jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_policy(), v13_mgraph_progress(uuid)
TO v13_recall, v13_resolve, v13_route;       -- 策略读/进度读:三角色
GRANT EXECUTE ON FUNCTION v13_mgraph_defaults_action(text,text)
TO v13_resolve;                              -- 缺省动作消费在 resolve 侧
GRANT EXECUTE ON FUNCTION v13_mgraph_envelope(uuid,jsonb,jsonb)
TO v13_resolve;                              -- 发问在 resolve 侧
-- rebuild/verify/DELETE/表 DML 其余面:仅 owner(不 GRANT);触发器函数
-- REVOKE 后仅属主可挂。

COMMIT;
