BEGIN;

-- =========================================================================
-- DP9 M1 mgraph dark library (v13_mgraph.sql): memory_nodes/memory_links
-- two-table graph (OQ1=A: indexed one-hop JOIN face; no graph extension in
-- runtime) + per-session v13_mgraph_meta (watermark/rel_cursor semantics)
-- + memory_consolidations queue (single-row-per-key, status closed set) +
-- mgraph policy row v2 (V1 候选发现唤醒就地升版:anchor 两键+top_k 10→5;
-- reader fail-closed) + six mem_* template
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
-- memory 先例同款;本文件 `==>` 源码计数=恰 1——M2 候选函数 EXECUTE 串;
-- 注释出现不计入,门 A7/组 D 按去注释源码断言)
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
-- 邻居函数 M3 落地,索引先行)
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

-- === §3.2 mgraph 策略行 v2 种子(V1 候选发现唤醒:candidate_top_k 10→5
--     (OQ18)+anchor_ngram_n/anchor_max_terms 两键(OQ15;39→41 键,就地
--     升版+读取器同批——v1/v2 键集不兼容,旧读取器读 v2 JSON 即 V3009,
--     回退=恢复 v1 SQL 重建 stage,不能只翻 active 标记);OQ9 裁决后逐键;
--     consolidate_max_body_bytes
--     来源=v13 本地护栏(对齐 summary_accept.checks.max_body_bytes 量级),
--     非 Jev-Mem 默认值;三帽单位同为 ask 批数:maximum_jev_calls(一次
--     read walk)/write_max_batches(每 tick)/write_max_asks(每次 build),
--     共同下游=judge_spend;write/read 默认双 false=部署暗) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('mgraph', 2, '{
  "relation_threshold": 0.60, "candidate_top_k": 5,
  "anchor_ngram_n": 3, "anchor_max_terms": 48,
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
  v_posint text[] := ARRAY['candidate_top_k','anchor_max_terms','total_graph_budget','beam_width',
                           'maximum_depth','maximum_nodes','maximum_edges',
                           'maximum_jev_calls','keyword_cap',
                           'candidate_recency_halflife_s','write_max_batches',
                           'deterministic_floor','inject_top_k',
                           'consolidate_max_body_bytes','write_max_asks'];
  -- max_latency_ms 允许 0(E7:0 = 第一轮提交后即 latency 停);其余计数仍 ≥1
  v_nznint text[] := ARRAY['anchor_ngram_n','consolidation_interval','max_latency_ms'];
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
     'admission_enabled,anchor_max_terms,anchor_ngram_n,beam_width,candidate_recency_coef,candidate_recency_halflife_s,candidate_top_k,consolidate_max_body_bytes,consolidate_mode,consolidation_choice_min,consolidation_interval,consolidation_priority,consolidation_threshold,continue_min,contradiction_stop_hi,deterministic_floor,entity_coef,entity_stopwords,evidence_sufficient_min,graph_activation_threshold,inject_top_k,keyword_cap,keyword_coef,lexical_coef,max_latency_ms,maximum_depth,maximum_edges,maximum_jev_calls,maximum_nodes,missing_stop_hi,probability_exponent,read_enabled,relation_threshold,routing_mode,routing_shadow,total_graph_budget,transition_recency_coef,transition_weights,write_enabled,write_max_asks,write_max_batches' THEN
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
INSERT INTO v13_judgment_template_versions (template_name, template_version) VALUES ('mem_type_episodic', 1), ('mem_type_semantic', 1), ('mem_type_procedural', 1), ('mem_type_preference', 1), ('mem_rel_semantic', 1), ('mem_rel_causes', 1), ('mem_rel_caused_by', 1), ('mem_rel_entity', 1), ('mem_rel_contradicts', 1), ('mem_cons_redundant', 1), ('mem_cons_contradiction', 1), ('mem_cons_obsolete', 1), ('mem_cons_link', 1), ('mem_cons_representation', 1), ('mem_routing_semantic', 1), ('mem_routing_temporal', 1), ('mem_routing_causal', 1), ('mem_routing_entity', 1), ('mem_routing_multi_hop_need', 1), ('mem_routing_recency_importance', 1), ('mem_stop_sufficient', 1), ('mem_stop_continue', 1), ('mem_stop_missing', 1), ('mem_stop_contradiction', 1), ('mem_trav_relevance', 1), ('mem_trav_relation_usefulness', 1), ('mem_trav_new_information', 1), ('mem_trav_supports', 1), ('mem_cons_fidelity', 1);

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
('mem_rel_contradicts', 1, 'noul', 'pre-finalize',
 'Compare `new_memory.content` with `candidates[0].content`. Do these two observations make claims that cannot both be true at the same time? TRUE if: The two accounts assert mutually exclusive facts, quantities or outcomes. FALSE if: The accounts are consistent, unrelated, or one merely elaborates the other.',
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
 WHERE template_name IN ('mem_type_episodic', 'mem_type_semantic', 'mem_type_procedural', 'mem_type_preference', 'mem_rel_semantic', 'mem_rel_causes', 'mem_rel_caused_by', 'mem_rel_entity', 'mem_rel_contradicts', 'mem_cons_redundant', 'mem_cons_contradiction', 'mem_cons_obsolete', 'mem_cons_link', 'mem_cons_representation', 'mem_routing_semantic', 'mem_routing_temporal', 'mem_routing_causal', 'mem_routing_entity', 'mem_routing_multi_hop_need', 'mem_routing_recency_importance', 'mem_stop_sufficient', 'mem_stop_continue', 'mem_stop_missing', 'mem_stop_contradiction', 'mem_trav_relevance', 'mem_trav_relation_usefulness', 'mem_trav_new_information', 'mem_trav_supports', 'mem_cons_fidelity') AND template_version = 1;

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

BEGIN;

-- =========================================================================
-- DP9 M2 write & rebuild (v13_mgraph.sql M2 segment): episodic projection
-- build + deterministic structure edges (temporal reconnect + proximity on
-- lexical activation) + relation-judgment edges (apply over threshold, no
-- mirroring) + idempotent rebuild (endpoint-based deletion, watermark/cursor
-- reset, then build). Plan §3.4 write path 1-9 / §3.5 rebuild / §5 D-gates.
-- Discipline carried from M1: error family V3009; zero DEFINER; no session
-- row locks (advisory only); judgment IO only via v13_resolve_judgments;
-- source scan five tokens stay at zero; the stannum bind operator appears
-- exactly once in source (candidates EXECUTE string; comments excluded from
-- the count, memory precedent). Write stays default-off (OQ2); nothing in
-- this segment flips the seed row.
-- =========================================================================

-- === §3.4/OQ10 实体抽取:英文段 ^[A-Z][a-z]+$ 减 entity_stopwords;
--     CJK 段不贡献不 RAISE(锚定 ASCII 字符类天然不匹配多字节段);
--     停用词表=策略行(可先 [],多抽不假抽)。段面函数供锚项复用
--     (V1 起 anchor 面经 v13_mgraph_anchor_terms 去重保序,body 面仍
--     全段——两面同源分段器、重复度口径不同) ===
CREATE FUNCTION v13_mgraph_entities_of(p_segs text[]) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE v_stop text[];
BEGIN
  IF p_segs IS NULL THEN RETURN ARRAY[]::text[]; END IF;
  v_stop := coalesce(ARRAY(SELECT jsonb_array_elements_text(
                             v13_mgraph_policy()->'entity_stopwords')),
                     ARRAY[]::text[]);
  RETURN coalesce(ARRAY(
    SELECT DISTINCT s FROM unnest(p_segs) s
     WHERE s ~ '^[A-Z][a-z]+$' AND s <> ALL(v_stop)
     ORDER BY s), ARRAY[]::text[]);
END $$;

CREATE FUNCTION v13_mgraph_entities(p_body text) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF p_body IS NULL OR p_body = '' THEN RETURN ARRAY[]::text[]; END IF;
  RETURN v13_mgraph_entities_of(
    ARRAY(SELECT jsonb_array_elements_text(v13_query_segments(p_body))));
END $$;

-- === §3.4/OQ7 关键词面:latin 段([A-Za-z0-9]+)频次顶 keyword_cap,
--     并列 token 升序终裁;CJK 段不贡献;不移植年正则 ===
CREATE FUNCTION v13_mgraph_keywords_of(p_segs text[]) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE v_cap int;
BEGIN
  IF p_segs IS NULL THEN RETURN ARRAY[]::text[]; END IF;
  v_cap := (v13_mgraph_policy()->>'keyword_cap')::int;
  RETURN coalesce(ARRAY(
    SELECT t FROM (SELECT t, count(*) AS c
                     FROM unnest(p_segs) t
                    WHERE t ~ '^[A-Za-z0-9]+$'
                    GROUP BY t
                    ORDER BY c DESC, t ASC
                    LIMIT v_cap) x), ARRAY[]::text[]);
END $$;

-- === Jaccard(集合交并比;空并集=0——不伪造相似度) ===
CREATE FUNCTION v13_mgraph_jaccard(p_a text[], p_b text[]) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
  WITH u AS (
    SELECT DISTINCT e FROM (
      SELECT unnest(coalesce(p_a, ARRAY[]::text[])) AS e
      UNION ALL
      SELECT unnest(coalesce(p_b, ARRAY[]::text[])) AS e) s)
  SELECT CASE WHEN (SELECT count(*) FROM u) = 0 THEN 0
              ELSE (SELECT count(DISTINCT k) FROM unnest(coalesce(p_a, ARRAY[]::text[])) k
                     WHERE k = ANY(coalesce(p_b, ARRAY[]::text[])))::numeric
                   / (SELECT count(*) FROM u)::numeric END;
$$;

-- === OQ7 候选发现 T0(签名三参;p_tinql 必须来自 v13_mgraph_anchor_tinql
--     ——入口 v13_mgraph_anchor_guard 本地文法守卫(引号短语 OR 闭集,
--     v2 R2 修订:OQ7 原 recall 守卫面正式 supersede)把用户文本挡在
--     EXECUTE 串之外,设计 §4.1
--     三禁;本文件去注释源码的绑定算符计数=恰 1,即本函数 EXECUTE 串;
--     池=本会话全部 episodic(consolidation 不作候选锚——只经遍历可达);
--     谓词驱动 stannum 索引扫描,禁裸表扫描后算分;插完全批再计分由
--     调用点(build ⑤ 全部插入后才进入 ⑦)保证;
--     score = lexical_coef*lexical_norm + entity_coef*entity_jaccard
--           + keyword_coef*keyword_jaccard + candidate_recency_coef*recency,
--     lexical_norm = bm25/max(bm25)(池内归一化),
--     recency = 1/(1+Δsource_at 秒/halflife)(halflife 键已是秒);
--     并列 score DESC, content_hash ASC 终裁) ===
CREATE FUNCTION v13_mgraph_candidates(p_sid uuid, p_tinql text, p_k int)
RETURNS TABLE(content_hash text, score numeric, lexical_norm numeric)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol  jsonb;
  v_lc numeric; v_ec numeric; v_kc numeric; v_rc numeric;
  v_hl  numeric; v_cap int;
  v_terms text[]; v_aent text[]; v_akw text[];
  v_hashes text[] := ARRAY[]::text[];
  v_bodies text[] := ARRAY[]::text[];
  v_ats  timestamptz[] := ARRAY[]::timestamptz[];
  v_bm25 numeric[] := ARRAY[]::numeric[];
  v_norms numeric[]; v_scores numeric[];
  v_n int := 0; v_i int; v_max numeric; r record;
BEGIN
  IF p_tinql IS NULL OR p_k IS NULL OR p_k < 1 OR p_k > 1024 THEN
    RAISE EXCEPTION 'v13: v13_mgraph_candidates args out of bounds'
      USING ERRCODE = 'V3009';
  END IF;
  IF p_tinql = '' THEN RETURN; END IF;
  v_terms := ARRAY(SELECT jsonb_array_elements_text(v13_mgraph_anchor_guard(p_tinql)));
  v_pol := v13_mgraph_policy();
  v_lc := (v_pol->>'lexical_coef')::numeric;
  v_ec := (v_pol->>'entity_coef')::numeric;
  v_kc := (v_pol->>'keyword_coef')::numeric;
  v_rc := (v_pol->>'candidate_recency_coef')::numeric;
  v_hl := (v_pol->>'candidate_recency_halflife_s')::numeric;
  v_aent := v13_mgraph_entities_of(v_terms);
  v_akw  := v13_mgraph_keywords_of(v_terms);
  FOR r IN EXECUTE
       'SELECT n.content_hash AS h, n.body AS b, n.source_at AS at, '
    || 'stannum.full_score(n.ctid)::numeric AS s '
    || 'FROM memory_nodes n '
    || 'WHERE n.session_id = $1 AND n.origin = ''episodic'' AND n.body ==> $2 '
    || 'ORDER BY n.content_hash ASC'
    USING p_sid, p_tinql
  LOOP
    v_n := v_n + 1;
    v_hashes[v_n] := r.h; v_bodies[v_n] := r.b;
    v_ats[v_n] := r.at;  v_bm25[v_n] := r.s;
  END LOOP;
  IF v_n = 0 THEN RETURN; END IF;
  SELECT max(s) INTO v_max FROM unnest(v_bm25) s;
  v_norms := ARRAY[]::numeric[]; v_scores := ARRAY[]::numeric[];
  FOR v_i IN 1 .. v_n LOOP
    v_norms[v_i] := CASE WHEN v_max > 0 THEN v_bm25[v_i] / v_max ELSE 0 END;
    v_scores[v_i] :=
        v_lc * v_norms[v_i]
      + v_ec * v13_mgraph_jaccard(v_aent, v13_mgraph_entities(v_bodies[v_i]))
      + v_kc * v13_mgraph_jaccard(v_akw,
          v13_mgraph_keywords_of(ARRAY(SELECT jsonb_array_elements_text(
            v13_query_segments(v_bodies[v_i])))))
      + v_rc * (1::numeric / (1::numeric
          + extract(epoch FROM (now() - v_ats[v_i]))::numeric / v_hl));
  END LOOP;
  RETURN QUERY
  SELECT u.h, u.s, u.ln
  FROM unnest(v_hashes, v_scores, v_norms) WITH ORDINALITY AS u(h, s, ln, ord)
  ORDER BY u.s DESC, u.h ASC
  LIMIT p_k;
END $$;

-- === §3.4⑦ 关系信封问题集(每 pair 一封;基础三问 semantic/causes/
--     caused_by;entity 问仅当双方实体集非空且无交集——OQ10;v2 V2 B3:
--     第四问 mem_rel_contradicts 仅在 canonical 方向(p_src<p_dst,
--     content_hash 字典序)入封,signal=mem_rel::<小>::<大>::contradicts
--     (OQ17 P1-3)——request_hash 携带 pair ctx(正反 ctx 不同),双向
--     都入封会以不同哈希重复问同一 signal(双份 ask+同 signal 双行,
--     违 D5 唯一性与「同一无序 pair 恰一套 signal 一条边」);不扩签名;
--     state 由调用方组装,本函数是 entity 闸的单一事实源,亦供 gate 直测 ===
CREATE FUNCTION v13_mgraph_pair_questions(p_src text, p_dst text,
                                          p_left_body text, p_right_body text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_le text[]; v_re text[];
  v_pre text;
BEGIN
  IF p_src IS NULL OR p_src !~ '^[0-9a-f]{64}$'
     OR p_dst IS NULL OR p_dst !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: pair question endpoints must be 64hex content hashes'
      USING ERRCODE = 'V3009';
  END IF;
  IF p_left_body IS NULL OR p_right_body IS NULL
     OR octet_length(p_left_body) = 0 OR octet_length(p_right_body) = 0 THEN
    RAISE EXCEPTION 'v13: pair question bodies must be non-empty'
      USING ERRCODE = 'V3009';
  END IF;
  v_le := v13_mgraph_entities(p_left_body);
  v_re := v13_mgraph_entities(p_right_body);
  v_pre := 'mem_rel::' || p_src || '::' || p_dst || '::';
  RETURN jsonb_build_array(
    jsonb_build_object('signal', v_pre || 'semantic',
                       'template_name', 'mem_rel_semantic'),
    jsonb_build_object('signal', v_pre || 'causes',
                       'template_name', 'mem_rel_causes'),
    jsonb_build_object('signal', v_pre || 'caused_by',
                       'template_name', 'mem_rel_caused_by'))
  || CASE WHEN cardinality(v_le) > 0 AND cardinality(v_re) > 0
             AND NOT EXISTS (SELECT 1 FROM unnest(v_le) e WHERE e = ANY(v_re))
          THEN jsonb_build_array(
                 jsonb_build_object('signal', v_pre || 'entity',
                                    'template_name', 'mem_rel_entity'))
          ELSE '[]'::jsonb END
  || CASE WHEN p_src < p_dst THEN
       jsonb_build_array(
         jsonb_build_object(
           'signal', 'mem_rel::' || p_src || '::' || p_dst
                     || '::contradicts',
           'template_name', 'mem_rel_contradicts'))
     ELSE '[]'::jsonb END;
END $$;

-- === §3.4⑧ apply_relations:扫本会话已答 mem_rel:: 行,各 rel 独立过
--     relation_threshold 才插边,ON CONFLICT DO NOTHING,不镜像反向;
--     v2 V2 B3:允许关系闭集扩 contradicts(Oracle P0-2——算法不变仅扩
--     闭集;canonical signal 端点已由 pair_questions 保证 (小,大) hash 序,
--     边方向=signal 端点序);决不重试:迟到 decision 只允许随后的 apply
--     补插从未写过的边,不 UPDATE 旧边(行不可变) ===
CREATE FUNCTION v13_mgraph_apply_relations(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_thr numeric; v_pver int; v_ins int := 0;
  v_parts text[]; r record;
BEGIN
  v_thr := (v13_mgraph_policy()->>'relation_threshold')::numeric;
  SELECT version INTO v_pver FROM v13_policies
   WHERE name = 'mgraph' AND active;
  FOR r IN SELECT d.decision_id, d.signal, d.answer
             FROM decisions d
            WHERE d.session_id = p_sid
              AND d.answer IS NOT NULL
              AND d.status IN ('answered','cached')
              AND left(d.signal, 9) = 'mem_rel::'
            ORDER BY d.signal
  LOOP
    v_parts := string_to_array(r.signal, '::');
    IF array_length(v_parts, 1) <> 4
       OR v_parts[2] !~ '^[0-9a-f]{64}$'
       OR v_parts[3] !~ '^[0-9a-f]{64}$'
       OR v_parts[4] NOT IN ('semantic','causes','caused_by','entity',
                             'contradicts') THEN
      RAISE EXCEPTION 'v13: malformed mem_rel signal (%)', r.signal
        USING ERRCODE = 'V3009';
    END IF;
    IF jsonb_typeof(r.answer->'noul') IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'v13: mem_rel decision answer lacks numeric noul (%)',
        r.signal USING ERRCODE = 'V3009';
    END IF;
    IF (r.answer->>'noul')::numeric >= v_thr THEN
      INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,
                                origin, decision_id, structural,
                                policy_version)
      VALUES (p_sid, v_parts[2], v_parts[3], v_parts[4], 'jev',
              r.decision_id, NULL, v_pver)
      ON CONFLICT DO NOTHING;
      IF FOUND THEN v_ins := v_ins + 1; END IF;
    END IF;
  END LOOP;
  RETURN jsonb_build_object('jev_edges', v_ins);
END $$;

-- === §3.4 写路径 v13_mgraph_build(sid, limit):①write_enabled 假→
--     skipped:disabled 零写;②admission_enabled 真→V3009(策略读取器
--     「保留但响亮」执法,在取策略时即炸);③freshness.degraded→
--     skipped:degraded 零写;④整次 build 会话级咨询锁
--     pg_advisory_lock(v13_lock_key(sid,'mgraph-build'))(结束释放;
--     与读环每轮的 xact 同 key 跨级互斥);⑤watermark 后 transcript 行
--     插 episodic 节点 ON CONFLICT DO NOTHING(seq 升序→同文折叠保留
--     source_at 最早者;source_at=events.at 回查,不变量 8);⑥先 DELETE
--     本会话 origin='temporal' 边再按 source_at ASC,content_hash ASC
--     全量重连;⑦发问从 rel_cursor 之后按插入序(首现 seq 升序)推进:
--     每节点类型信封(四 Noul 一 state)→resolve→只记录,然后
--     v13_mgraph_anchor_tinql(body)→candidates 取对(锚自身除外),每 pair 一封
--     关系信封,lexical_norm≥graph_activation_threshold 插 proximity 边
--     (structural=lexical_norm);帽(spend.over/write_max_batches/
--     write_max_asks,计数=judgment_calls 行增量=每封发出即+1 含失败批)
--     任一用尽→停在断点;resolve failed→停(节点不标记完成);
--     ⑧apply_relations(幂等,零 ask);⑨收尾一律先把 rel_cursor 推到
--     「类型+关系问全部落账」的末节点再把 watermark 推到其首现 seq,
--     两列同批提交(帽尽=断点,全部完成=本次末节点);generation 仅在
--     图内容有净变化时 +1 ===
CREATE FUNCTION v13_mgraph_build(p_sid uuid, p_limit int DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_pol jsonb; v_pver int; v_wmb int; v_wma int;
  v_act numeric; v_topk int;
  v_provider text; v_model text;
  v_meta v13_mgraph_meta%ROWTYPE;
  v_wm0 bigint; v_floor bigint;
  v_asks int := 0; v_failed boolean := false; v_stop text; v_skipped text;
  v_nodes int := 0; v_tdel int := 0; v_tins int := 0;
  v_pins int := 0; v_jins int := 0;
  v_c0 bigint; v_c1 bigint; v_res jsonb; v_env jsonb;
  v_state jsonb; v_questions jsonb; v_tinql text; v_rbody text;
  v_node record; v_cand record;
  v_last_hash text; v_last_seq bigint;
  v_cursor_new text; v_wm_new bigint; v_done_floor bigint;
  v_pending int; v_changed boolean; v_ret jsonb; v_jret jsonb;
BEGIN
  v_pol := v13_mgraph_policy();                       -- ② loud keys fire here
  IF NOT (v_pol->>'write_enabled')::boolean THEN      -- ①
    RETURN jsonb_build_object('status','skipped','skipped','disabled',
                              'failed', false, 'asks', 0);
  END IF;
  IF (v13_transcript_freshness(p_sid)->>'degraded')::boolean THEN  -- ③
    RETURN jsonb_build_object('status','skipped','skipped','degraded',
                              'failed', false, 'asks', 0);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: mgraph build on unknown session (%)', p_sid
      USING ERRCODE = 'V3009';
  END IF;
  IF p_limit IS NOT NULL AND p_limit < 1 THEN
    RAISE EXCEPTION 'v13: mgraph build limit must be >= 1 or NULL (unbounded)'
      USING ERRCODE = 'V3009';
  END IF;
  v_pver := (SELECT version FROM v13_policies WHERE name = 'mgraph' AND active);
  v_wmb := (v_pol->>'write_max_batches')::int;
  v_wma := (v_pol->>'write_max_asks')::int;
  v_act := (v_pol->>'graph_activation_threshold')::numeric;
  v_topk := (v_pol->>'candidate_top_k')::int;
  -- provider/model 一次捕获(首次 ask 后占位符被清除,后续信封一律显式传参;
  -- 已花费的连接在此响亮失败 V3002,驱动每 tick 用新连接——README 运维注记)
  v_provider := v13_guc_required('typesafe.provider');
  v_model := v13_guc_required('typesafe.model');

  PERFORM pg_advisory_lock(v13_lock_key(p_sid, 'mgraph-build'));  -- ④
  BEGIN
    -- 锁后重读状态(并发第二连接在此之后只见已提交前缀)
    SELECT * INTO v_meta FROM v13_mgraph_meta WHERE session_id = p_sid;
    v_wm0 := coalesce(v_meta.transcript_watermark, -1);
    v_floor := -1;
    IF v_meta.rel_cursor IS NOT NULL THEN
      SELECT coalesce(min(t.seq_from), -1) INTO v_floor
        FROM transcript_chunks t
       WHERE t.session_id = p_sid AND t.content_hash = v_meta.rel_cursor;
    END IF;

    -- ⑤ episodic 投影插入(seq 升序→折叠保最早 source_at)
    INSERT INTO memory_nodes (session_id, content_hash, body, origin,
                              source_hashes, source_at, builder_version)
    SELECT t.session_id, t.content_hash, t.body, 'episodic',
           ARRAY[t.content_hash], e.at, v_pver
      FROM transcript_chunks t
      JOIN events e ON e.session_id = t.session_id AND e.seq = t.seq_from
     WHERE t.session_id = p_sid AND t.seq_from > v_wm0
     ORDER BY t.seq_from
     LIMIT p_limit
    ON CONFLICT (session_id, content_hash) DO NOTHING;
    GET DIAGNOSTICS v_nodes = ROW_COUNT;

    -- ⑥ temporal 全量重连(先 DELETE 后重连:新节点落在两旧节点之间时
    --    旧跨接边必须消失)
    DELETE FROM memory_links
     WHERE session_id = p_sid AND origin = 'temporal';
    GET DIAGNOSTICS v_tdel = ROW_COUNT;
    WITH ord AS (
      SELECT content_hash,
             row_number() OVER (ORDER BY source_at ASC, content_hash ASC) AS rn
        FROM memory_nodes
       WHERE session_id = p_sid AND origin = 'episodic'),
    lnk AS (
      SELECT a.content_hash AS src, b.content_hash AS dst
        FROM ord a JOIN ord b ON b.rn = a.rn + 1)
    INSERT INTO memory_links (session_id, src_hash, dst_hash, rel, origin,
                              decision_id, structural, policy_version)
    SELECT p_sid, src, dst, 'temporal', 'temporal', NULL, NULL, v_pver
      FROM lnk
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_tins = ROW_COUNT;

    -- ⑦ 发问循环(类型→关系;锚=本节点 tinql,候选对=池内其余节点)
    <<nodes>> FOR v_node IN
      SELECT f.content_hash, f.body, f.first_seq
        FROM (SELECT n.content_hash, n.body,
                     min(t.seq_from) AS first_seq
                FROM memory_nodes n
                JOIN transcript_chunks t
                  ON t.session_id = n.session_id
                 AND t.content_hash = n.content_hash
               WHERE n.session_id = p_sid AND n.origin = 'episodic'
               GROUP BY n.content_hash, n.body) f
       WHERE f.first_seq > v_floor
       ORDER BY f.first_seq ASC, f.content_hash ASC
    LOOP
      -- (a) 类型信封:四 Noul 一 state
      IF v_stop IS NULL THEN
        IF (v13_judge_spend(p_sid)->>'over')::boolean THEN v_stop := 'spend';
        ELSIF v_asks >= v_wmb THEN v_stop := 'batches';
        ELSIF v_asks >= v_wma THEN v_stop := 'asks';
        END IF;
      END IF;
      EXIT nodes WHEN v_stop IS NOT NULL;
      v_state := jsonb_build_object('body', v_node.body);
      v_questions := jsonb_build_array(
        jsonb_build_object('signal',
          'mem_type::' || v_node.content_hash || '::episodic',
          'template_name', 'mem_type_episodic'),
        jsonb_build_object('signal',
          'mem_type::' || v_node.content_hash || '::semantic',
          'template_name', 'mem_type_semantic'),
        jsonb_build_object('signal',
          'mem_type::' || v_node.content_hash || '::procedural',
          'template_name', 'mem_type_procedural'),
        jsonb_build_object('signal',
          'mem_type::' || v_node.content_hash || '::preference',
          'template_name', 'mem_type_preference'));
      v_env := v13_mgraph_envelope(p_sid, v_state, v_questions, v_provider, v_model);
      SELECT count(*) INTO v_c0 FROM judgment_calls WHERE session_id = p_sid;
      SELECT v13_resolve_judgments(v_env, 1) INTO v_res;
      SELECT count(*) INTO v_c1 FROM judgment_calls WHERE session_id = p_sid;
      v_asks := v_asks + (v_c1 - v_c0)::int;
      IF coalesce(v_res->>'failed', 'false')::boolean THEN
        v_failed := true; v_stop := 'failed'; EXIT nodes;
      END IF;

      -- (b) 候选对:proximity 结构边 + 每 pair 一封关系信封
      v_tinql := v13_mgraph_anchor_tinql(v_node.body);
      FOR v_cand IN SELECT * FROM v13_mgraph_candidates(p_sid, v_tinql, v_topk)
      LOOP
        IF v_cand.content_hash = v_node.content_hash THEN CONTINUE; END IF;
        IF v_cand.lexical_norm >= v_act THEN
          INSERT INTO memory_links (session_id, src_hash, dst_hash, rel,
                                    origin, decision_id, structural,
                                    policy_version)
          VALUES (p_sid, v_node.content_hash, v_cand.content_hash,
                  'proximity', 'proximity', NULL, v_cand.lexical_norm, v_pver)
          ON CONFLICT DO NOTHING;
          IF FOUND THEN v_pins := v_pins + 1; END IF;
        END IF;
        SELECT body INTO v_rbody FROM memory_nodes
         WHERE session_id = p_sid AND content_hash = v_cand.content_hash;
        v_questions := v13_mgraph_pair_questions(
                         v_node.content_hash, v_cand.content_hash,
                         v_node.body, v_rbody);
        v_state := jsonb_build_object(
          'left',  jsonb_build_object('content', v_node.body,
                      'entities', to_jsonb(v13_mgraph_entities(v_node.body))),
          'right', jsonb_build_object('content', v_rbody,
                      'entities', to_jsonb(v13_mgraph_entities(v_rbody))));
        IF v_stop IS NULL THEN
          IF (v13_judge_spend(p_sid)->>'over')::boolean THEN v_stop := 'spend';
          ELSIF v_asks >= v_wmb THEN v_stop := 'batches';
          ELSIF v_asks >= v_wma THEN v_stop := 'asks';
          END IF;
        END IF;
        EXIT nodes WHEN v_stop IS NOT NULL;
        v_env := v13_mgraph_envelope(p_sid, v_state, v_questions,
                                      v_provider, v_model);
        SELECT count(*) INTO v_c0 FROM judgment_calls WHERE session_id = p_sid;
        SELECT v13_resolve_judgments(v_env, 1) INTO v_res;
        SELECT count(*) INTO v_c1 FROM judgment_calls WHERE session_id = p_sid;
        v_asks := v_asks + (v_c1 - v_c0)::int;
        IF coalesce(v_res->>'failed', 'false')::boolean THEN
          v_failed := true; v_stop := 'failed'; EXIT nodes;
        END IF;
      END LOOP;
      v_last_hash := v_node.content_hash; v_last_seq := v_node.first_seq;
                                       -- 类型+关系问全部落账
    END LOOP nodes;

    -- ⑧ apply(幂等,零 ask)
    v_jret := v13_mgraph_apply_relations(p_sid);
    v_jins := (v_jret->>'jev_edges')::int;

    -- ⑨ 收尾:先推 cursor 再推 watermark,两列同批
    v_cursor_new := v_meta.rel_cursor;
    v_wm_new := v_wm0;
    IF v_last_hash IS NOT NULL THEN
      v_cursor_new := v_last_hash;
      v_wm_new := v_last_seq;
    END IF;
    v_done_floor := -1;
    IF v_cursor_new IS NOT NULL THEN
      SELECT coalesce(min(t.seq_from), -1) INTO v_done_floor
        FROM transcript_chunks t
       WHERE t.session_id = p_sid AND t.content_hash = v_cursor_new;
    END IF;
    SELECT count(*) INTO v_pending
      FROM (SELECT n.content_hash, min(t.seq_from) AS fs
              FROM memory_nodes n
              JOIN transcript_chunks t
                ON t.session_id = n.session_id
               AND t.content_hash = n.content_hash
             WHERE n.session_id = p_sid AND n.origin = 'episodic'
             GROUP BY n.content_hash) f
     WHERE f.fs > v_done_floor;
    v_changed := (v_nodes + v_pins + v_jins) > 0 OR (v_tins <> v_tdel);
    INSERT INTO v13_mgraph_meta (session_id, generation,
                                 transcript_watermark, rel_cursor,
                                 nodes_since_consolidate)
    VALUES (p_sid, CASE WHEN v_changed THEN 1 ELSE 0 END,
            v_wm_new, v_cursor_new, 0)
    ON CONFLICT (session_id) DO UPDATE SET
      generation = v13_mgraph_meta.generation
                   + CASE WHEN v_changed THEN 1 ELSE 0 END,
      transcript_watermark = EXCLUDED.transcript_watermark,
      rel_cursor = EXCLUDED.rel_cursor;

    IF v_stop = 'spend' AND v_asks = 0 THEN v_skipped := 'spend'; END IF;
    v_ret := jsonb_build_object(
      'status', CASE WHEN v_skipped IS NOT NULL THEN 'skipped'
                     WHEN v_stop IS NOT NULL THEN 'stopped' ELSE 'ok' END,
      'skipped', v_skipped,
      'stop_reason', v_stop,
      'failed', v_failed,
      'nodes_inserted', v_nodes,
      'temporal_deleted', v_tdel, 'temporal_edges', v_tins,
      'proximity_edges', v_pins, 'jev_edges', v_jins,
      'asks', v_asks, 'pending_nodes', v_pending,
      'rel_cursor', v_cursor_new, 'watermark', v_wm_new);
  EXCEPTION WHEN OTHERS THEN
    PERFORM pg_advisory_unlock(v13_lock_key(p_sid, 'mgraph-build'));
    RAISE;
  END;
  PERFORM pg_advisory_unlock(v13_lock_key(p_sid, 'mgraph-build'));
  RETURN v_ret;
END $$;

-- === §3.5 rebuild:DELETE 全部 episodic 节点 + 两端都不是 consolidation
--     节点的边(按端点判定——不变量 6 的完整实现)→ watermark=-1 且
--     rel_cursor=NULL 两列一起复位 →build(无界 limit);write 关/degraded
--     时拒绝(fail-closed:build 会 skip 而图已删——计划未言明,取拒绝);
--     与 build 同 key 会话级咨询锁(可重入栈式);固化节点及其关联边
--     不在删除面 ===
CREATE FUNCTION v13_mgraph_rebuild(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_pol jsonb; v_nd int := 0; v_ld int := 0; v_ret jsonb;
BEGIN
  v_pol := v13_mgraph_policy();
  IF NOT (v_pol->>'write_enabled')::boolean THEN
    RAISE EXCEPTION
      'v13: rebuild requires write_enabled (build would skip leaving the graph deleted)'
      USING ERRCODE = 'V3009';
  END IF;
  IF (v13_transcript_freshness(p_sid)->>'degraded')::boolean THEN
    RAISE EXCEPTION 'v13: rebuild refused while transcript freshness degraded'
      USING ERRCODE = 'V3009';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM sessions WHERE session_id = p_sid) THEN
    RAISE EXCEPTION 'v13: mgraph rebuild on unknown session (%)', p_sid
      USING ERRCODE = 'V3009';
  END IF;
  PERFORM pg_advisory_lock(v13_lock_key(p_sid, 'mgraph-build'));
  BEGIN
    DELETE FROM memory_links l
     WHERE l.session_id = p_sid
       AND NOT EXISTS (SELECT 1 FROM memory_nodes c
                        WHERE c.session_id = l.session_id
                          AND c.content_hash = l.src_hash
                          AND c.origin = 'consolidation')
       AND NOT EXISTS (SELECT 1 FROM memory_nodes c
                        WHERE c.session_id = l.session_id
                          AND c.content_hash = l.dst_hash
                          AND c.origin = 'consolidation');
    GET DIAGNOSTICS v_ld = ROW_COUNT;
    DELETE FROM memory_nodes
     WHERE session_id = p_sid AND origin = 'episodic';
    GET DIAGNOSTICS v_nd = ROW_COUNT;
    UPDATE v13_mgraph_meta
       SET transcript_watermark = -1, rel_cursor = NULL
     WHERE session_id = p_sid;
    v_ret := v13_mgraph_build(p_sid, NULL);
  EXCEPTION WHEN OTHERS THEN
    PERFORM pg_advisory_unlock(v13_lock_key(p_sid, 'mgraph-build'));
    RAISE;
  END;
  PERFORM pg_advisory_unlock(v13_lock_key(p_sid, 'mgraph-build'));
  RETURN jsonb_build_object('nodes_deleted', v_nd, 'links_deleted', v_ld,
                            'build', v_ret);
END $$;

-- === §4 ACL(M2 面;列举式 REVOKE,零 DEFINER;rebuild/DELETE 仍仅 owner) ===
REVOKE EXECUTE ON FUNCTION
  v13_mgraph_entities_of(text[]), v13_mgraph_entities(text),
  v13_mgraph_keywords_of(text[]), v13_mgraph_jaccard(text[],text[]),
  v13_mgraph_candidates(uuid,text,int),
  v13_mgraph_pair_questions(text,text,text,text),
  v13_mgraph_apply_relations(uuid), v13_mgraph_build(uuid,int),
  v13_mgraph_rebuild(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_entities_of(text[]), v13_mgraph_entities(text),
  v13_mgraph_keywords_of(text[]), v13_mgraph_jaccard(text[],text[]),
  v13_mgraph_candidates(uuid,text,int),
  v13_mgraph_pair_questions(text,text,text,text),
  v13_mgraph_apply_relations(uuid), v13_mgraph_build(uuid,int)
TO v13_resolve;                              -- 写路径驱动面(resolve_login)
-- 读环调用方缺位：anchors 与 transition_score 只授 v13_resolve。candidates 对 v13_recall 的预授已撤；将来以该角色执行的调用方出现时，与整条 INVOKER 授权闭包同一提交再授。
REVOKE EXECUTE ON FUNCTION v13_mgraph_candidates(uuid,text,int)
FROM v13_recall;
-- v13_mgraph_rebuild:owner only(§3.5 owner 平面)
GRANT INSERT, UPDATE ON v13_mgraph_meta TO v13_resolve;  -- build 终态 upsert 面

COMMIT;

BEGIN;

-- =========================================================================
-- DP9 M2 addendum: envelope constructor provider/model passthrough.
-- typesafe.provider is a placeholder GUC that is PURGED when the typesafe
-- extension library loads (the connection's first judgment IO) and cannot
-- be re-set afterward (reserved prefix) — a connection that has asked can
-- never construct another envelope via the GUC-reading path. Build loops
-- envelope→resolve→envelope, so it must capture provider/model ONCE at start
-- and pass them explicitly to every construction (same-file CREATE OR
-- REPLACE + a wider-signature overload; the 3-arg M1 face stays callable
-- and its ACL survives the body swap). Drivers should run one build tick
-- per fresh connection (README ops note); the capture fails loud (V3002)
-- on a spent connection instead of silently re-keying the cache.
-- =========================================================================

CREATE FUNCTION v13_mgraph_envelope(p_sid uuid, p_state jsonb, p_questions jsonb,
                                    p_provider text, p_model text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_provider text; v_model text;
  v_n int; v_q jsonb; v_t judgment_templates%ROWTYPE;
  v_needed jsonb := '[]'::jsonb;
  v_templates jsonb := '{}'::jsonb;
  v_signals text[] := '{}';
  v_pkey text; v_proj jsonb; v_timeout text;
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
  -- typesafe.timeout_ms 的扩展默认值是时长串(30s)。judgment_calls.timeout_ms
  -- 是 int;非数字就不写入信封,避免把整批 ask 打成 22P02。
  v_timeout := nullif(btrim(current_setting('typesafe.timeout_ms', true)), '');
  IF v_timeout IS NOT NULL AND v_timeout !~ '^[0-9]+$' THEN
    v_timeout := NULL;
  END IF;
  IF coalesce(btrim(p_provider), '') <> '' THEN
    v_provider := btrim(p_provider);
  ELSE
    v_provider := v13_guc_required('typesafe.provider');
  END IF;
  IF coalesce(btrim(p_model), '') <> '' THEN
    v_model := btrim(p_model);
  ELSE
    v_model := v13_guc_required('typesafe.model');
  END IF;
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
    'timeout_ms', v_timeout,
    'candidate_set_hash',
      encode(digest(jsonb_build_object(
        'signals', (SELECT jsonb_agg(s ORDER BY s) FROM unnest(v_signals) s),
        'state', p_state)::text, 'sha256'), 'hex'),
    'provider', v_provider, 'model', v_model,
    'goal_hash', v13_goal_hash(p_sid),
    'candidates', '[]'::jsonb);
END $$;

-- 3 参 M1 面保持可调(OR REPLACE 换体不改签名,ACL 经 OID 保留)
CREATE OR REPLACE FUNCTION v13_mgraph_envelope(p_sid uuid, p_state jsonb,
                                               p_questions jsonb)
RETURNS jsonb LANGUAGE sql STABLE AS
  $$ SELECT v13_mgraph_envelope($1, $2, $3, NULL, NULL) $$;

REVOKE EXECUTE ON FUNCTION
  v13_mgraph_envelope(uuid,jsonb,jsonb,text,text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_envelope(uuid,jsonb,jsonb,text,text)
TO v13_resolve;                              -- build 内部显式传参面

COMMIT;

BEGIN;

-- =========================================================================
-- DP9 M3 read loop B1 (v13_mgraph.sql M3 segment): deterministic route,
-- Hamilton allocate, one-step run_round, should_stop, evidence export.
-- Plan §1.3 OQ1/OQ2/OQ3/OQ8/OQ11, §3.1 walks/rounds, §3.4 read path, §5 E.
-- Zero effect, zero resolve/failed, zero session row lock. Judgment IO only
-- via v13_resolve_judgments. One envelope per run_round call (mock GUC is
-- one batch shape — same stepping discipline as write_max_batches).
-- Error family V3009. No new bind operator. No DEFINER.
-- =========================================================================

-- === §3.1 memory_walks / memory_rounds (M1 未建,本里程碑补)
--     walk 唯一 (session, query_hash, generation, policy_version);
--     status open|stopped;stopped 不因迟到信号重开。
--     round PK (walk_id, round):重放已存在轮次不再扩展。 ===
CREATE TABLE memory_walks (
  walk_id            uuid PRIMARY KEY,
  session_id         uuid NOT NULL REFERENCES sessions (session_id),
  query_hash         text NOT NULL CHECK (query_hash ~ '^[0-9a-f]{64}$'),
  mgraph_generation  bigint NOT NULL CHECK (mgraph_generation >= 0),
  policy_version     int NOT NULL CHECK (policy_version >= 1),
  frontier           jsonb NOT NULL DEFAULT '[]'::jsonb,
  budgets            jsonb NOT NULL DEFAULT '{}'::jsonb,
  calls_used         int NOT NULL DEFAULT 0 CHECK (calls_used >= 0),
  nodes_used         int NOT NULL DEFAULT 0 CHECK (nodes_used >= 0),
  edges_used         int NOT NULL DEFAULT 0 CHECK (edges_used >= 0),
  depth              int NOT NULL DEFAULT 0 CHECK (depth >= 0),
  stop_reason        text,
  status             text NOT NULL CHECK (status IN ('open','stopped')),
  UNIQUE (session_id, query_hash, mgraph_generation, policy_version)
);

CREATE TABLE memory_rounds (
  walk_id      uuid NOT NULL REFERENCES memory_walks (walk_id),
  round        int NOT NULL CHECK (round >= 1),
  frontier_in  jsonb,
  frontier_out jsonb NOT NULL,
  basis        jsonb,
  asks         int NOT NULL DEFAULT 0 CHECK (asks >= 0),
  PRIMARY KEY (walk_id, round)
);

-- 确定性 walk 身份:同一 (sid,qhash,gen,policy) 永远同一 uuid,
-- 信号 mem_trav/mem_stop 在驱动发问前就可计算。
CREATE FUNCTION v13_mgraph_walk_id(p_sid uuid, p_qhash text,
                                   p_gen bigint, p_pver int)
RETURNS uuid LANGUAGE sql IMMUTABLE AS $$
  SELECT md5(p_sid::text || ':' || p_qhash || ':' || p_gen::text
             || ':' || p_pver::text)::uuid;
$$;

-- 桶→rel(唯一映射;recency 与 temporal 同边集,调用方按 source_at 重排)
CREATE FUNCTION v13_mgraph_bucket_rels(p_bucket text)
RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE p_bucket
    WHEN 'semantic' THEN ARRAY['semantic','related_to','redundant_with','contradicts']
    WHEN 'temporal' THEN ARRAY['temporal']
    WHEN 'causal'   THEN ARRAY['causes','caused_by']
    WHEN 'entity'   THEN ARRAY['entity']
    WHEN 'recency'  THEN ARRAY['temporal']
    WHEN 'multi_hop' THEN ARRAY['semantic','causes','caused_by','entity','temporal',
                                'proximity','contradicts','redundant_with','related_to']
    ELSE NULL END;
$$;

-- OQ1 唯一存储端口:出边,structural DESC NULLS LAST, dst_hash ASC。
-- p_limit NULL = 不截断(recency 调用方重排后再截)。
CREATE FUNCTION v13_mgraph_neighbors(p_sid uuid, p_hash text,
                                     p_rels text[], p_limit int)
RETURNS TABLE(dst_hash text, rel text, structural numeric,
              source_at timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT l.dst_hash, l.rel, l.structural, n.source_at
    FROM memory_links l
    JOIN memory_nodes n
      ON n.session_id = l.session_id AND n.content_hash = l.dst_hash
   WHERE l.session_id = p_sid
     AND l.src_hash = p_hash
     AND (p_rels IS NULL OR l.rel = ANY (p_rels))
   ORDER BY l.structural DESC NULLS LAST, l.dst_hash ASC
   LIMIT p_limit;
$$;

-- 调试用变长展开(热路径禁止调用;深度缺省读 maximum_depth)
CREATE FUNCTION v13_mgraph_structural_reach(p_sid uuid, p_hash text,
                                            p_depth int)
RETURNS TABLE(content_hash text, depth int)
LANGUAGE sql STABLE AS $$
  WITH RECURSIVE lim AS (
    SELECT coalesce(p_depth,
                    (v13_mgraph_policy()->>'maximum_depth')::int) AS d
  ), w AS (
    SELECT p_hash AS content_hash, 0 AS depth
    UNION ALL
    SELECT l.dst_hash, w.depth + 1
      FROM w
      JOIN memory_links l
        ON l.session_id = p_sid AND l.src_hash = w.content_hash
     WHERE w.depth < (SELECT d FROM lim)
  )
  SELECT DISTINCT w.content_hash, w.depth
    FROM w WHERE w.depth > 0
   ORDER BY 2, 1;
$$;

-- OQ3 确定性路由。主意图互斥:why > when > 大写实体 > semantic,
-- 被点名桶权重 = deterministic_floor+1,其余 = floor(全向量六键)。
-- multi_hop/recency 仅查询点名时升到同一高度。CJK 段 → superset,
-- 六桶都停在 floor(零 ask,ask 发生在 run_round 之外的本函数也不发问)。
-- routing_mode=jev 时 mode=jev,权重不作为分配输入(run_round 改读 Noul)。
CREATE FUNCTION v13_mgraph_route(p_query text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_floor numeric; v_raised numeric; v_q text;
  v_mode text; v_primary text := NULL; v_cjk boolean := false;
  v_ch text; v_cp int; v_i int;
  v_names text[] := ARRAY['causal','entity','multi_hop','recency',
                          'semantic','temporal'];
  v_w numeric[] := ARRAY[0,0,0,0,0,0]::numeric[];
  v_weights jsonb := '{}'::jsonb;
BEGIN
  v_pol := v13_mgraph_policy();
  v_floor := (v_pol->>'deterministic_floor')::numeric;
  v_raised := v_floor + 1;
  v_q := coalesce(p_query, '');
  FOR v_ch IN SELECT x FROM unnest(regexp_split_to_array(v_q, '')) AS t(x)
  LOOP
    IF v_ch IS NULL OR v_ch = '' THEN CONTINUE; END IF;
    v_cp := ascii(v_ch);
    IF (v_cp BETWEEN 12352 AND 12543)
       OR (v_cp BETWEEN 13312 AND 19903)
       OR (v_cp BETWEEN 19968 AND 40959)
       OR (v_cp BETWEEN 44032 AND 55215)
       OR (v_cp BETWEEN 63744 AND 64255) THEN
      v_cjk := true; EXIT;
    END IF;
  END LOOP;
  IF v_pol->>'routing_mode' = 'jev' THEN
    v_mode := 'jev';
  ELSIF v_cjk THEN
    v_mode := 'superset';
  ELSE
    v_mode := 'deterministic';
  END IF;
  FOR v_i IN 1..6 LOOP v_w[v_i] := v_floor; END LOOP;
  IF v_mode = 'deterministic' THEN
    IF position('why' IN lower(v_q)) > 0 THEN v_primary := 'causal';
    ELSIF position('when' IN lower(v_q)) > 0 THEN v_primary := 'temporal';
    ELSIF cardinality(v13_mgraph_entities(v_q)) > 0 THEN v_primary := 'entity';
    ELSE v_primary := 'semantic';
    END IF;
    FOR v_i IN 1..6 LOOP
      IF v_names[v_i] = v_primary THEN v_w[v_i] := v_raised; END IF;
    END LOOP;
    IF position('multi_hop' IN lower(v_q)) > 0
       OR position('multi-hop' IN lower(v_q)) > 0 THEN
      v_w[3] := v_raised;
    END IF;
    IF position('recency' IN lower(v_q)) > 0 THEN
      v_w[4] := v_raised;
    END IF;
  END IF;
  FOR v_i IN 1..6 LOOP
    v_weights := v_weights
      || jsonb_build_object(v_names[v_i], to_jsonb(v_w[v_i]));
  END LOOP;
  RETURN jsonb_build_object('mode', v_mode, 'weights', v_weights);
END $$;

-- Hamilton 最大余数。桶序(余数并列终裁)= causal,entity,multi_hop,
-- recency,semantic,temporal。全 0 → 六桶权重改 1 再分配。
-- 权重>0 且 floor 后为 0 的桶向当前最大且 ≥2 的桶借 1(并列名字升序);
-- 借不到 V3009。jev 激活阈由调用方在传入前归零,本函数不读阈值。
CREATE FUNCTION v13_mgraph_allocate(p_weights jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_b int; v_e numeric; v_sum numeric := 0;
  v_names text[] := ARRAY['causal','entity','multi_hop','recency',
                          'semantic','temporal'];
  v_w numeric[]; v_we numeric[]; v_quota numeric[];
  v_base int[]; v_rem numeric[]; v_ord int[];
  v_i int; v_j int; v_left int; v_active int := 0;
  v_tmp int; v_best int; v_out jsonb := '{}'::jsonb;
BEGIN
  IF p_weights IS NULL OR jsonb_typeof(p_weights) IS DISTINCT FROM 'object'
     OR (SELECT count(*) FROM jsonb_object_keys(p_weights)) <> 6 THEN
    RAISE EXCEPTION 'v13: mgraph allocate weights must be the six-bucket object'
      USING ERRCODE = 'V3009';
  END IF;
  v_pol := v13_mgraph_policy();
  v_b := (v_pol->>'total_graph_budget')::int;
  v_e := (v_pol->>'probability_exponent')::numeric;
  FOR v_i IN 1..6 LOOP
    IF NOT p_weights ? v_names[v_i]
       OR jsonb_typeof(p_weights->v_names[v_i]) IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'v13: mgraph allocate missing numeric weight %',
        v_names[v_i] USING ERRCODE = 'V3009';
    END IF;
    v_w[v_i] := (p_weights->>v_names[v_i])::numeric;
    IF v_w[v_i] < 0 THEN
      RAISE EXCEPTION 'v13: mgraph allocate weight % is negative', v_names[v_i]
        USING ERRCODE = 'V3009';
    END IF;
    IF v_w[v_i] > 0 THEN v_active := v_active + 1; END IF;
  END LOOP;
  IF v_active = 0 THEN
    FOR v_i IN 1..6 LOOP v_w[v_i] := 1; END LOOP;
  END IF;
  FOR v_i IN 1..6 LOOP
    v_we[v_i] := power(v_w[v_i], v_e);
    v_sum := v_sum + v_we[v_i];
  END LOOP;
  IF v_sum = 0 THEN
    RAISE EXCEPTION 'v13: mgraph allocate weight mass is zero'
      USING ERRCODE = 'V3009';
  END IF;
  v_left := v_b;
  FOR v_i IN 1..6 LOOP
    v_quota[v_i] := (v_b::numeric * v_we[v_i]) / v_sum;
    v_base[v_i] := floor(v_quota[v_i])::int;
    v_rem[v_i] := v_quota[v_i] - v_base[v_i];
    v_left := v_left - v_base[v_i];
    v_ord[v_i] := v_i;
  END LOOP;
  FOR v_i IN 1..5 LOOP
    FOR v_j IN 1..(6 - v_i) LOOP
      IF v_rem[v_ord[v_j]] < v_rem[v_ord[v_j + 1]]
         OR (v_rem[v_ord[v_j]] = v_rem[v_ord[v_j + 1]]
             AND v_names[v_ord[v_j]] > v_names[v_ord[v_j + 1]]) THEN
        v_tmp := v_ord[v_j];
        v_ord[v_j] := v_ord[v_j + 1];
        v_ord[v_j + 1] := v_tmp;
      END IF;
    END LOOP;
  END LOOP;
  FOR v_j IN 1..v_left LOOP
    v_base[v_ord[v_j]] := v_base[v_ord[v_j]] + 1;
  END LOOP;
  FOR v_i IN 1..6 LOOP
    IF v_w[v_i] > 0 AND v_base[v_i] = 0 THEN
      v_best := NULL;
      FOR v_j IN 1..6 LOOP
        IF v_base[v_j] >= 2 AND (v_best IS NULL
            OR v_base[v_j] > v_base[v_best]
            OR (v_base[v_j] = v_base[v_best]
                AND v_names[v_j] < v_names[v_best])) THEN
          v_best := v_j;
        END IF;
      END LOOP;
      IF v_best IS NULL THEN
        RAISE EXCEPTION
          'v13: mgraph allocate cannot fund every active bucket (budget %)',
          v_b USING ERRCODE = 'V3009';
      END IF;
      v_base[v_best] := v_base[v_best] - 1;
      v_base[v_i] := 1;
    END IF;
  END LOOP;
  FOR v_i IN 1..6 LOOP
    v_out := v_out || jsonb_build_object(v_names[v_i], to_jsonb(v_base[v_i]));
  END LOOP;
  RETURN v_out;
END $$;

CREATE FUNCTION v13_mgraph_primary_bucket(p_weights jsonb)
RETURNS text LANGUAGE sql STABLE AS $$
  SELECT e.k FROM jsonb_each(p_weights) AS e(k, v)
   ORDER BY (e.v #>> '{}')::numeric DESC, e.k ASC
   LIMIT 1;
$$;

-- 信号三态:已答 Noul / 该信号出现在 failed_timeout 调用里 / 无 call 行。
-- 不伪造概率。failed_validation 等其它失败落在 default_missing(无 Noul)。
CREATE FUNCTION v13_mgraph_signal_class(p_sid uuid, p_signal text)
RETURNS text LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM decisions d
       WHERE d.session_id = p_sid AND d.signal = p_signal
         AND d.answer IS NOT NULL
         AND d.status IN ('answered','cached')
         AND jsonb_typeof(d.answer->'noul') = 'number')
    THEN 'noul'
    WHEN EXISTS (
      SELECT 1 FROM judgment_calls c
       WHERE c.session_id = p_sid AND c.status = 'failed_timeout'
         AND position(p_signal IN c.payload::text) > 0)
    THEN 'default_timeout'
    ELSE 'default_missing' END;
$$;

CREATE FUNCTION v13_mgraph_component(p_sid uuid, p_signal text)
RETURNS numeric LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN v13_mgraph_signal_class(p_sid, p_signal) = 'noul'
    THEN (SELECT (d.answer->>'noul')::numeric FROM decisions d
           WHERE d.session_id = p_sid AND d.signal = p_signal
             AND d.answer IS NOT NULL
             AND d.status IN ('answered','cached')
           ORDER BY d.answered_at DESC NULLS LAST LIMIT 1)
    ELSE NULL END;
$$;

CREATE FUNCTION v13_mgraph_anchors(p_sid uuid, p_query text, p_bucket text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb; v_k int; v_beam int; v_tinql text;
BEGIN
  v_pol := v13_mgraph_policy();
  v_k := (v_pol->>'candidate_top_k')::int;
  v_beam := (v_pol->>'beam_width')::int;
  v_tinql := v13_mgraph_anchor_tinql(p_query);
  IF v_tinql IS NULL OR v_tinql = '' THEN RETURN '[]'::jsonb; END IF;
  RETURN coalesce((
    SELECT jsonb_agg(jsonb_build_object(
             'content_hash', c.content_hash,
             'bucket', p_bucket,
             'structural', NULL)
             ORDER BY c.score DESC, c.content_hash ASC)
      FROM (
        SELECT content_hash, score
          FROM v13_mgraph_candidates(p_sid, v_tinql, v_k)
         ORDER BY score DESC, content_hash ASC
         LIMIT v_beam) c
  ), '[]'::jsonb);
END $$;

CREATE FUNCTION v13_mgraph_trav_questions(p_walk uuid, p_hash text, p_round int)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_build_array(
    jsonb_build_object('signal',
      'mem_trav::' || p_walk::text || '::' || p_hash || '::relevance',
      'template_name', 'mem_trav_relevance'),
    jsonb_build_object('signal',
      'mem_trav::' || p_walk::text || '::' || p_hash || '::relation_usefulness',
      'template_name', 'mem_trav_relation_usefulness'),
    jsonb_build_object('signal',
      'mem_trav::' || p_walk::text || '::' || p_hash || '::new_information',
      'template_name', 'mem_trav_new_information'),
    jsonb_build_object('signal',
      'mem_trav::' || p_walk::text || '::' || p_hash || '::supports',
      'template_name', 'mem_trav_supports'));
$$;

CREATE FUNCTION v13_mgraph_stop_questions(p_walk uuid, p_round int)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_build_array(
    jsonb_build_object('signal',
      'mem_stop::' || p_walk::text || '::' || p_round::text || '::sufficient',
      'template_name', 'mem_stop_sufficient'),
    jsonb_build_object('signal',
      'mem_stop::' || p_walk::text || '::' || p_round::text || '::missing',
      'template_name', 'mem_stop_missing'),
    jsonb_build_object('signal',
      'mem_stop::' || p_walk::text || '::' || p_round::text || '::contradiction',
      'template_name', 'mem_stop_contradiction'),
    jsonb_build_object('signal',
      'mem_stop::' || p_walk::text || '::' || p_round::text || '::continue',
      'template_name', 'mem_stop_continue'));
$$;

CREATE FUNCTION v13_mgraph_route_questions(p_qhash text, p_gen bigint)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
  SELECT jsonb_build_array(
    jsonb_build_object('signal',
      'mem_route::' || p_qhash || '::semantic@' || p_gen::text,
      'template_name', 'mem_routing_semantic'),
    jsonb_build_object('signal',
      'mem_route::' || p_qhash || '::temporal@' || p_gen::text,
      'template_name', 'mem_routing_temporal'),
    jsonb_build_object('signal',
      'mem_route::' || p_qhash || '::causal@' || p_gen::text,
      'template_name', 'mem_routing_causal'),
    jsonb_build_object('signal',
      'mem_route::' || p_qhash || '::entity@' || p_gen::text,
      'template_name', 'mem_routing_entity'),
    jsonb_build_object('signal',
      'mem_route::' || p_qhash || '::multi_hop@' || p_gen::text,
      'template_name', 'mem_routing_multi_hop_need'),
    jsonb_build_object('signal',
      'mem_route::' || p_qhash || '::recency@' || p_gen::text,
      'template_name', 'mem_routing_recency_importance'));
$$;

CREATE FUNCTION v13_mgraph_trav_state(p_sid uuid, p_query text, p_node jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_body text; v_hash text;
BEGIN
  v_hash := p_node->>'content_hash';
  SELECT body INTO v_body FROM memory_nodes
   WHERE session_id = p_sid AND content_hash = v_hash;
  IF v_body IS NULL THEN
    RAISE EXCEPTION 'v13: mgraph traversal node % is not in the graph', v_hash
      USING ERRCODE = 'V3009';
  END IF;
  RETURN jsonb_build_object(
    'query', p_query,
    'candidate', jsonb_build_object('content', v_body, 'content_hash', v_hash),
    'path', CASE WHEN p_node ? 'from_hash'
            THEN jsonb_build_array(jsonb_build_object(
                   'from', p_node->>'from_hash', 'bucket', p_node->>'bucket'))
            ELSE '[]'::jsonb END);
END $$;

CREATE FUNCTION v13_mgraph_stop_state(p_sid uuid, p_query text, p_scored jsonb)
RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'query', p_query,
    'evidence', coalesce((
      SELECT jsonb_agg(jsonb_build_object(
               'content_hash', n.content_hash, 'body', n.body)
               ORDER BY n.content_hash)
        FROM jsonb_array_elements(coalesce(p_scored, '[]'::jsonb)) s
        JOIN memory_nodes n
          ON n.session_id = p_sid AND n.content_hash = s->>'content_hash'
    ), '[]'::jsonb));
$$;

-- 过渡分(§3.4 单式)。Jev 分量缺失则丢掉该 λ 并重归一;全缺则分子只剩
-- 词法项(词法 0 即分数 0)。structural NULL 在 supports 存在时按 0 参加
-- 平均(边上没有结构分,不是伪 Noul)。recency 与候选发现同一秒制 halflife。
CREATE FUNCTION v13_mgraph_transition_score(
  p_sid uuid, p_query text, p_walk uuid, p_hash text,
  p_bucket text, p_structural numeric, p_weights jsonb)
RETURNS numeric LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_l numeric[]; v_num numeric := 0; v_den numeric := 0;
  v_lex numeric := 0; v_rel numeric; v_use numeric; v_nov numeric; v_sup numeric;
  v_need numeric; v_r numeric; v_rec numeric; v_coef numeric; v_hl numeric;
  v_at timestamptz; v_score numeric; v_pre text; v_tinql text;
BEGIN
  v_pol := v13_mgraph_policy();
  SELECT array_agg((e #>> '{}')::numeric ORDER BY ord) INTO v_l
    FROM jsonb_array_elements(v_pol->'transition_weights')
         WITH ORDINALITY AS t(e, ord);
  v_pre := 'mem_trav::' || p_walk::text || '::' || p_hash || '::';
  v_tinql := v13_mgraph_anchor_tinql(p_query);
  IF v_tinql IS NOT NULL AND v_tinql <> '' THEN
    SELECT coalesce(max(c.lexical_norm), 0) INTO v_lex
      FROM v13_mgraph_candidates(p_sid, v_tinql, 1024) c
     WHERE c.content_hash = p_hash;
  END IF;
  v_lex := coalesce(v_lex, 0);
  v_rel := v13_mgraph_component(p_sid, v_pre || 'relevance');
  v_use := v13_mgraph_component(p_sid, v_pre || 'relation_usefulness');
  v_nov := v13_mgraph_component(p_sid, v_pre || 'new_information');
  v_sup := v13_mgraph_component(p_sid, v_pre || 'supports');
  v_need := coalesce((p_weights->>p_bucket)::numeric, 0);
  v_r := coalesce((p_weights->>'recency')::numeric, 0);
  v_coef := (v_pol->>'transition_recency_coef')::numeric;
  v_hl := (v_pol->>'candidate_recency_halflife_s')::numeric;
  SELECT source_at INTO v_at FROM memory_nodes
   WHERE session_id = p_sid AND content_hash = p_hash;
  IF v_at IS NULL OR v_hl <= 0 THEN v_rec := 0;
  ELSE v_rec := 1 / (1 + extract(epoch FROM (now() - v_at)) / v_hl);
  END IF;
  v_num := v_l[1] * v_lex; v_den := v_l[1];
  IF v_rel IS NOT NULL THEN
    v_num := v_num + v_l[2] * v_rel; v_den := v_den + v_l[2];
  END IF;
  IF v_use IS NOT NULL THEN
    v_num := v_num + v_l[3] * v_need * v_use; v_den := v_den + v_l[3];
  END IF;
  IF v_nov IS NOT NULL THEN
    v_num := v_num + v_l[4] * v_nov; v_den := v_den + v_l[4];
  END IF;
  IF v_sup IS NOT NULL THEN
    v_num := v_num + v_l[5] * (coalesce(p_structural, 0) + v_sup) / 2;
    v_den := v_den + v_l[5];
  END IF;
  IF v_den = 0 THEN v_score := 0; ELSE v_score := v_num / v_den; END IF;
  RETURN (v_score + v_coef * v_r * v_rec) / (1 + v_coef * v_r);
END $$;

-- 停止四条排序。四条 Noul 缺任一则不进 ①②(OQ11);硬顶照常。
-- latency 不在本函数(由 run_round 在收轮时写)。
CREATE FUNCTION v13_mgraph_should_stop(p_walk uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_w memory_walks%ROWTYPE; v_pol jsonb; v_round int;
  v_pref text; v_cls text; v_all boolean := true;
  v_suf numeric; v_mis numeric; v_con numeric; v_go numeric;
  v_aspect text;
BEGIN
  SELECT * INTO v_w FROM memory_walks WHERE walk_id = p_walk;
  IF v_w.walk_id IS NULL THEN
    RAISE EXCEPTION 'v13: mgraph should_stop on unknown walk %', p_walk
      USING ERRCODE = 'V3009';
  END IF;
  v_pol := v13_mgraph_policy();
  v_round := coalesce((v_w.budgets->>'round_no')::int, 1);
  v_pref := 'mem_stop::' || p_walk::text || '::' || v_round::text || '::';
  FOR v_aspect IN
    SELECT unnest(ARRAY['sufficient','missing','contradiction','continue'])
  LOOP
    v_cls := v13_mgraph_signal_class(v_w.session_id, v_pref || v_aspect);
    IF v_cls IS DISTINCT FROM 'noul' THEN v_all := false; END IF;
  END LOOP;
  IF v_all THEN
    v_suf := v13_mgraph_component(v_w.session_id, v_pref || 'sufficient');
    v_mis := v13_mgraph_component(v_w.session_id, v_pref || 'missing');
    v_con := v13_mgraph_component(v_w.session_id, v_pref || 'contradiction');
    v_go  := v13_mgraph_component(v_w.session_id, v_pref || 'continue');
    IF v_suf >= (v_pol->>'evidence_sufficient_min')::numeric
       AND v_mis < (v_pol->>'missing_stop_hi')::numeric
       AND v_con < (v_pol->>'contradiction_stop_hi')::numeric THEN
      RETURN jsonb_build_object('stop', true, 'reason', 'evidence');
    ELSIF v_go < (v_pol->>'continue_min')::numeric THEN
      RETURN jsonb_build_object('stop', true, 'reason', 'continue');
    END IF;
  END IF;
  IF v_w.nodes_used >= (v_pol->>'maximum_nodes')::int THEN
    RETURN jsonb_build_object('stop', true, 'reason', 'nodes');
  ELSIF v_w.edges_used >= (v_pol->>'maximum_edges')::int THEN
    RETURN jsonb_build_object('stop', true, 'reason', 'edges');
  ELSIF v_w.depth >= (v_pol->>'maximum_depth')::int THEN
    RETURN jsonb_build_object('stop', true, 'reason', 'depth');
  ELSIF v_w.calls_used >= (v_pol->>'maximum_jev_calls')::int THEN
    RETURN jsonb_build_object('stop', true, 'reason', 'calls');
  END IF;
  RETURN jsonb_build_object('stop', false, 'reason', 'go');
END $$;

-- 下一步(纯读)。run_round 只执行这里给出的一个动作,从而一轮一封。
CREATE FUNCTION v13_mgraph_next_action(p_sid uuid, p_query text, p_elapsed_ms int)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_q text; v_qhash text; v_gen bigint; v_pver int; v_wid uuid;
  v_w memory_walks%ROWTYPE; v_b jsonb; v_route jsonb; v_weights jsonb;
  v_quota jsonb; v_anchors jsonb; v_primary text; v_round int;
  v_head jsonb; v_qs jsonb; v_cls text; v_aspect text;
  v_any_to boolean := false; v_any_miss boolean := false; v_all_noul boolean := true;
  v_names text[] := ARRAY['causal','entity','multi_hop','recency','semantic','temporal'];
  v_i int; v_act jsonb;
BEGIN
  v_q := btrim(coalesce(p_query, ''));
  IF v_q = '' THEN
    RETURN jsonb_build_object('action','skip','skipped','empty');
  END IF;
  v_pol := v13_mgraph_policy();
  IF NOT (v_pol->>'read_enabled')::boolean THEN
    RETURN jsonb_build_object('action','skip','skipped','disabled');
  END IF;
  IF (v13_transcript_freshness(p_sid)->>'degraded')::boolean THEN
    RETURN jsonb_build_object('action','skip','skipped','degraded');
  END IF;
  IF p_elapsed_ms IS NULL OR p_elapsed_ms < 0 THEN
    RAISE EXCEPTION 'v13: mgraph elapsed_ms must be >= 0'
      USING ERRCODE = 'V3009';
  END IF;
  v_qhash := v13_body_hash(v_q);
  v_gen := (v13_mgraph_progress(p_sid)->>'generation')::bigint;
  SELECT version INTO v_pver FROM v13_policies WHERE name = 'mgraph' AND active;
  v_wid := v13_mgraph_walk_id(p_sid, v_qhash, v_gen, v_pver);
  SELECT * INTO v_w FROM memory_walks WHERE walk_id = v_wid;

  IF v_w.walk_id IS NULL THEN
    IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
      RETURN jsonb_build_object('action','stop_spend');
    END IF;
    v_route := v13_mgraph_route(v_q);
    IF v_route->>'mode' = 'jev' THEN
      RETURN jsonb_build_object(
        'action','ask','kind','route','round_no', 1,
        'questions', v13_mgraph_route_questions(v_qhash, v_gen),
        'state', jsonb_build_object('query', v_q),
        'phase', 'route');
    END IF;
    v_weights := v_route->'weights';
    v_quota := v13_mgraph_allocate(v_weights);
    v_primary := v13_mgraph_primary_bucket(v_weights);
    v_anchors := v13_mgraph_anchors(p_sid, v_q, v_primary);
    IF jsonb_array_length(v_anchors) = 0 THEN
      RETURN jsonb_build_object(
        'action','ask','kind','stop','round_no', 1,
        'questions', v13_mgraph_stop_questions(v_wid, 1),
        'state', v13_mgraph_stop_state(p_sid, v_q, '[]'::jsonb),
        'weights', v_weights, 'quota', v_quota, 'phase', 'stop');
    END IF;
    RETURN jsonb_build_object(
      'action','ask','kind','trav','round_no', 1,
      'node', v_anchors->0,
      'questions', v13_mgraph_trav_questions(v_wid, v_anchors->0->>'content_hash', 1),
      'state', v13_mgraph_trav_state(p_sid, v_q, v_anchors->0),
      'set_pending', v_anchors,
      'weights', v_weights, 'quota', v_quota, 'phase', 'traverse');
  END IF;

  v_b := v_w.budgets;
  IF v_w.status = 'stopped' THEN
    IF (v_pol->>'routing_shadow')::boolean
       AND coalesce((v_b->>'shadow_done')::boolean, false) = false
       AND NOT (v13_judge_spend(p_sid)->>'over')::boolean THEN
      v_any_miss := false;
      FOR v_i IN 1..6 LOOP
        IF v13_mgraph_signal_class(p_sid,
             'mem_route::' || v_qhash || '::' || v_names[v_i] || '@' || v_gen::text)
           = 'default_missing' THEN
          v_any_miss := true;
        END IF;
      END LOOP;
      IF v_any_miss THEN
        RETURN jsonb_build_object(
          'action','ask','kind','shadow',
          'questions', v13_mgraph_route_questions(v_qhash, v_gen),
          'state', jsonb_build_object('query', v_q));
      END IF;
      RETURN jsonb_build_object('action','mark_shadow');
    END IF;
    RETURN jsonb_build_object('action','done');
  END IF;

  IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
    RETURN jsonb_build_object('action','stop_spend');
  END IF;
  IF EXISTS (SELECT 1 FROM memory_rounds r WHERE r.walk_id = v_wid)
     AND p_elapsed_ms >= (v_pol->>'max_latency_ms')::int THEN
    RETURN jsonb_build_object('action','stop_latency');
  END IF;

  v_round := coalesce((v_b->>'round_no')::int, 1);

  IF coalesce(v_b->>'phase', 'seed') = 'route' THEN
    IF coalesce((v_b->>'route_attempted')::boolean, false) THEN
      v_act := jsonb_build_object('action','bind');
    ELSE
      v_act := jsonb_build_object(
        'action','ask','kind','route','round_no', v_round,
        'questions', v13_mgraph_route_questions(v_qhash, v_gen),
        'state', jsonb_build_object('query', v_q));
    END IF;
  ELSIF coalesce(v_b->>'phase', 'seed') = 'seed'
        OR (v_b->>'phase' = 'traverse'
            AND jsonb_array_length(coalesce(v_b->'pending','[]'::jsonb)) = 0
            AND jsonb_array_length(coalesce(v_b->'scored','[]'::jsonb)) = 0
            AND NOT coalesce((v_b->>'stop_attempted')::boolean, false)) THEN
    v_weights := v_b->'weights';
    v_primary := v13_mgraph_primary_bucket(v_weights);
    v_anchors := v13_mgraph_anchors(p_sid, v_q, v_primary);
    IF jsonb_array_length(v_anchors) = 0 THEN
      v_act := jsonb_build_object(
        'action','ask','kind','stop','round_no', v_round,
        'questions', v13_mgraph_stop_questions(v_wid, v_round),
        'state', v13_mgraph_stop_state(p_sid, v_q, coalesce(v_b->'scored','[]'::jsonb)));
    ELSE
      v_act := jsonb_build_object(
        'action','ask','kind','trav','round_no', v_round,
        'node', v_anchors->0,
        'questions', v13_mgraph_trav_questions(
                       v_wid, v_anchors->0->>'content_hash', v_round),
        'state', v13_mgraph_trav_state(p_sid, v_q, v_anchors->0),
        'set_pending', v_anchors);
    END IF;
  ELSIF v_b->>'phase' = 'traverse' THEN
    IF jsonb_array_length(coalesce(v_b->'pending','[]'::jsonb)) = 0 THEN
      v_act := jsonb_build_object('action','to_stop');
    ELSE
      v_head := v_b->'pending'->0;
      v_qs := v13_mgraph_trav_questions(v_wid, v_head->>'content_hash', v_round);
      v_any_to := false; v_any_miss := false; v_all_noul := true;
      FOR v_aspect IN SELECT q->>'signal' FROM jsonb_array_elements(v_qs) q LOOP
        v_cls := v13_mgraph_signal_class(p_sid, v_aspect);
        IF v_cls = 'default_timeout' THEN v_any_to := true; END IF;
        IF v_cls = 'default_missing' THEN v_any_miss := true; END IF;
        IF v_cls IS DISTINCT FROM 'noul' THEN v_all_noul := false; END IF;
      END LOOP;
      IF v_all_noul OR v_any_to THEN
        -- 已答,或已有超时调用(同节点未覆盖的信号记 default_missing,不再补问)
        v_act := jsonb_build_object('action','score','node', v_head);
      ELSE
        v_act := jsonb_build_object(
          'action','ask','kind','trav','round_no', v_round,
          'node', v_head, 'questions', v_qs,
          'state', v13_mgraph_trav_state(p_sid, v_q, v_head));
      END IF;
    END IF;
  ELSIF v_b->>'phase' = 'stop' THEN
    v_qs := v13_mgraph_stop_questions(v_wid, v_round);
    v_any_miss := false;
    FOR v_aspect IN SELECT q->>'signal' FROM jsonb_array_elements(v_qs) q LOOP
      IF v13_mgraph_signal_class(p_sid, v_aspect) = 'default_missing'
         AND NOT coalesce((v_b->>'stop_attempted')::boolean, false) THEN
        v_any_miss := true;
      END IF;
    END LOOP;
    IF v_any_miss THEN
      v_act := jsonb_build_object(
        'action','ask','kind','stop','round_no', v_round,
        'questions', v_qs,
        'state', v13_mgraph_stop_state(p_sid, v_q, coalesce(v_b->'scored','[]'::jsonb)));
    ELSE
      v_act := jsonb_build_object('action','close');
    END IF;
  ELSIF v_b->>'phase' = 'expand' THEN
    v_act := jsonb_build_object('action','expand');
  ELSE
    RAISE EXCEPTION 'v13: mgraph walk % phase % is unknown',
      v_wid, v_b->>'phase' USING ERRCODE = 'V3009';
  END IF;

  -- 帽尽只拦截下一次发问;收轮(close)仍走 should_stop,使 ①② 优先于 calls
  IF v_act->>'action' = 'ask'
     AND v_w.walk_id IS NOT NULL
     AND v_w.calls_used >= (v_pol->>'maximum_jev_calls')::int THEN
    RETURN jsonb_build_object('action','close');
  END IF;
  RETURN v_act;
END $$;

-- 读环一步。p_query 标识 walk(计划正文把 elapsed 标成延迟写入点;
-- 查询文本是 walk 身份的另一半,见偏差台账)。provider/model 在本 walk
-- 第一次发问前捕获,其后读 budgets,避开占位符 GUC 被清除的坑。
CREATE FUNCTION v13_mgraph_capture_pm(p_sid uuid)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_p text; v_m text;
BEGIN
  v_p := nullif(btrim(current_setting('typesafe.provider', true)), '');
  v_m := nullif(btrim(current_setting('typesafe.model', true)), '');
  IF v_p IS NULL OR v_m IS NULL THEN
    SELECT c.provider, c.model INTO v_p, v_m
      FROM judgment_calls c
     WHERE c.session_id = p_sid
       AND c.provider IS NOT NULL AND c.model IS NOT NULL
     ORDER BY c.created_at DESC LIMIT 1;
  END IF;
  IF v_p IS NULL OR v_m IS NULL THEN
    v_p := v13_guc_required('typesafe.provider');
    v_m := v13_guc_required('typesafe.model');
  END IF;
  RETURN jsonb_build_object('provider', v_p, 'model', v_m);
END $$;

CREATE FUNCTION v13_mgraph_run_round(p_sid uuid, p_query text, p_elapsed_ms int)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_act jsonb; v_q text; v_qhash text; v_gen bigint; v_pver int; v_wid uuid;
  v_w memory_walks%ROWTYPE; v_b jsonb; v_pol jsonb; v_pm jsonb;
  v_env jsonb; v_res jsonb; v_c0 bigint; v_c1 bigint; v_delta int := 0;
  v_failed boolean := false; v_node jsonb; v_score numeric; v_hash text;
  v_qs jsonb; v_basis jsonb; v_pending jsonb; v_scored jsonb; v_visited jsonb;
  v_sig text; v_cid uuid; v_names text[]; v_i int; v_thr numeric; v_val numeric;
  v_all0 boolean; v_weights jsonb; v_key text; v_cls text;
  v_beam jsonb; v_ss jsonb; v_round int; v_asks int; v_edges int;
  v_frontier jsonb; v_quota jsonb; v_bucket text; v_left int; v_hash2 text;
  v_fr jsonb; v_rel text; v_st numeric; v_nb jsonb; v_seen boolean;
  rec record;
BEGIN
  v_act := v13_mgraph_next_action(p_sid, p_query, p_elapsed_ms);
  IF v_act->>'action' = 'skip' THEN
    RETURN jsonb_build_object('status','skipped','skipped', v_act->>'skipped',
                              'asks', 0, 'failed', false, 'calls_used', 0,
                              'frontier', '[]'::jsonb);
  END IF;

  PERFORM pg_advisory_xact_lock(v13_lock_key(p_sid, 'mgraph-build'));
  v_act := v13_mgraph_next_action(p_sid, p_query, p_elapsed_ms);
  v_q := btrim(p_query);
  v_qhash := v13_body_hash(v_q);
  v_gen := (v13_mgraph_progress(p_sid)->>'generation')::bigint;
  SELECT version INTO v_pver FROM v13_policies WHERE name = 'mgraph' AND active;
  v_wid := v13_mgraph_walk_id(p_sid, v_qhash, v_gen, v_pver);
  v_pol := v13_mgraph_policy();
  SELECT * INTO v_w FROM memory_walks WHERE walk_id = v_wid;

  IF v_act->>'action' = 'skip' THEN
    RETURN jsonb_build_object('status','skipped','skipped', v_act->>'skipped',
                              'asks', 0, 'failed', false, 'walk_id', v_wid);
  ELSIF v_act->>'action' = 'done' THEN
    RETURN jsonb_build_object(
      'action','done','status', v_w.status, 'stop_reason', v_w.stop_reason,
      'asks', 0, 'failed', false, 'calls_used', v_w.calls_used,
      'frontier', v_w.frontier, 'walk_id', v_wid,
      'phase', v_w.budgets->>'phase');
  ELSIF v_act->>'action' IN ('stop_spend','stop_latency') THEN
    IF v_w.walk_id IS NULL THEN
      INSERT INTO memory_walks (walk_id, session_id, query_hash,
        mgraph_generation, policy_version, frontier, budgets,
        calls_used, nodes_used, edges_used, depth, stop_reason, status)
      VALUES (v_wid, p_sid, v_qhash, v_gen, v_pver, '[]'::jsonb, '{}'::jsonb,
              0, 0, 0, 0,
              CASE v_act->>'action' WHEN 'stop_spend' THEN 'spend'
                                    ELSE 'latency' END,
              'stopped');
    ELSE
      UPDATE memory_walks SET status = 'stopped',
             stop_reason = CASE v_act->>'action'
                             WHEN 'stop_spend' THEN 'spend' ELSE 'latency' END
       WHERE walk_id = v_wid AND status = 'open';
    END IF;
    SELECT * INTO v_w FROM memory_walks WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action', v_act->>'action', 'status', v_w.status,
      'stop_reason', v_w.stop_reason, 'asks', 0, 'failed', false,
      'calls_used', v_w.calls_used, 'frontier', v_w.frontier, 'walk_id', v_wid);
  END IF;

  -- 确保 walk 在(ask 的 init / 其它动作都要求行已在)
  IF v_w.walk_id IS NULL THEN
    v_pm := v13_mgraph_capture_pm(p_sid);
    v_b := jsonb_build_object(
      'phase', coalesce(v_act->>'phase', 'traverse'),
      'round_no', coalesce((v_act->>'round_no')::int, 1),
      'weights', v_act->'weights',
      'quota', v_act->'quota',
      'pending', coalesce(v_act->'set_pending', '[]'::jsonb),
      'scored', '[]'::jsonb,
      'visited', '[]'::jsonb,
      'basis', '{}'::jsonb,
      'provider', v_pm->>'provider',
      'model', v_pm->>'model',
      'shadow_done', false,
      'route_attempted', false,
      'stop_attempted', false,
      'round_asks', 0,
      'round_edges', 0,
      'counted_calls', '[]'::jsonb);
    INSERT INTO memory_walks (walk_id, session_id, query_hash,
      mgraph_generation, policy_version, frontier, budgets,
      calls_used, nodes_used, edges_used, depth, stop_reason, status)
    VALUES (v_wid, p_sid, v_qhash, v_gen, v_pver, '[]'::jsonb, v_b,
            0, 0, 0, 0, NULL, 'open');
    SELECT * INTO v_w FROM memory_walks WHERE walk_id = v_wid;
  END IF;
  v_b := v_w.budgets;

  IF v_act ? 'set_pending' THEN
    v_b := jsonb_set(v_b, '{pending}', v_act->'set_pending');
    v_b := jsonb_set(v_b, '{phase}', '"traverse"');
    IF v_act ? 'weights' THEN
      v_b := jsonb_set(v_b, '{weights}', v_act->'weights');
      v_b := jsonb_set(v_b, '{quota}', v_act->'quota');
    END IF;
  END IF;

  IF v_act->>'action' = 'mark_shadow' THEN
    v_b := jsonb_set(v_b, '{shadow_done}', 'true'::jsonb);
    UPDATE memory_walks SET budgets = v_b WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','mark_shadow','status', v_w.status, 'stop_reason', v_w.stop_reason,
      'asks', 0, 'failed', false, 'calls_used', v_w.calls_used,
      'frontier', v_w.frontier, 'walk_id', v_wid);
  ELSIF v_act->>'action' = 'bind' THEN
    v_names := ARRAY['causal','entity','multi_hop','recency','semantic','temporal'];
    v_thr := (v_pol->>'graph_activation_threshold')::numeric;
    v_weights := '{}'::jsonb; v_all0 := true;
    FOR v_i IN 1..6 LOOP
      v_key := 'mem_route::' || v_qhash || '::' || v_names[v_i] || '@' || v_gen::text;
      v_cls := v13_mgraph_signal_class(p_sid, v_key);
      v_val := 0;
      IF v_cls = 'noul' THEN
        v_val := coalesce(v13_mgraph_component(p_sid, v_key), 0);
        IF v_val < v_thr THEN v_val := 0; END IF;
      END IF;
      IF v_val > 0 THEN v_all0 := false; END IF;
      v_weights := v_weights || jsonb_build_object(v_names[v_i], to_jsonb(v_val));
    END LOOP;
    IF v_all0 THEN
      v_weights := '{}'::jsonb;
      FOR v_i IN 1..6 LOOP
        v_weights := v_weights || jsonb_build_object(v_names[v_i], to_jsonb(0));
      END LOOP;
    END IF;
    v_b := jsonb_set(v_b, '{weights}', v_weights);
    v_b := jsonb_set(v_b, '{quota}', v13_mgraph_allocate(v_weights));
    v_b := jsonb_set(v_b, '{phase}', '"seed"');
    UPDATE memory_walks SET budgets = v_b WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','bind','status','open','asks',0,'failed',false,
      'calls_used', v_w.calls_used, 'frontier', v_w.frontier,
      'walk_id', v_wid, 'phase','seed', 'weights', v_weights);
  ELSIF v_act->>'action' = 'to_stop' THEN
    v_b := jsonb_set(v_b, '{phase}', '"stop"');
    UPDATE memory_walks SET budgets = v_b WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','to_stop','status','open','asks',0,'failed',false,
      'calls_used', v_w.calls_used, 'frontier', v_w.frontier,
      'walk_id', v_wid, 'phase','stop');
  ELSIF v_act->>'action' = 'score' THEN
    v_node := v_act->'node';
    v_hash := v_node->>'content_hash';
    v_qs := v13_mgraph_trav_questions(
              v_wid, v_hash, coalesce((v_b->>'round_no')::int, 1));
    v_basis := coalesce(v_b->'basis', '{}'::jsonb);
    FOR v_sig IN SELECT q->>'signal' FROM jsonb_array_elements(v_qs) q LOOP
      v_basis := v_basis || jsonb_build_object(
        v_sig, v13_mgraph_signal_class(p_sid, v_sig));
    END LOOP;
    -- 失败批只计一次(同一 call_id 覆盖多条 signal)
    SELECT c.call_id INTO v_cid
      FROM judgment_calls c
     WHERE c.session_id = p_sid AND c.status = 'failed_timeout'
       AND position(v_qs->0->>'signal' IN c.payload::text) > 0
     ORDER BY c.created_at DESC LIMIT 1;
    IF v_cid IS NOT NULL AND NOT coalesce(v_b->'counted_calls', '[]'::jsonb)
         @> jsonb_build_array(v_cid::text) THEN
      v_w.calls_used := v_w.calls_used + 1;
      v_b := jsonb_set(v_b, '{counted_calls}',
              coalesce(v_b->'counted_calls','[]'::jsonb)
              || jsonb_build_array(v_cid::text));
    END IF;
    v_score := v13_mgraph_transition_score(
      p_sid, v_q, v_wid, v_hash, v_node->>'bucket',
      NULLIF(v_node->>'structural','')::numeric, v_b->'weights');
    v_scored := coalesce(v_b->'scored','[]'::jsonb) || jsonb_build_array(
      jsonb_build_object('content_hash', v_hash, 'score', to_jsonb(v_score),
                         'bucket', v_node->>'bucket'));
    v_visited := coalesce(v_b->'visited','[]'::jsonb)
                 || jsonb_build_array(v_hash);
    v_pending := coalesce((
      SELECT jsonb_agg(e ORDER BY i)
        FROM jsonb_array_elements(coalesce(v_b->'pending','[]'::jsonb))
             WITH ORDINALITY AS t(e, i)
       WHERE i > 1), '[]'::jsonb);
    v_b := jsonb_set(v_b, '{basis}', v_basis);
    v_b := jsonb_set(v_b, '{scored}', v_scored);
    v_b := jsonb_set(v_b, '{visited}', v_visited);
    v_b := jsonb_set(v_b, '{pending}', v_pending);
    UPDATE memory_walks SET budgets = v_b, calls_used = v_w.calls_used
     WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','score','status','open','asks',0,'failed',false,
      'calls_used', v_w.calls_used, 'frontier', v_w.frontier,
      'walk_id', v_wid, 'phase', v_b->>'phase', 'scored_hash', v_hash);
  ELSIF v_act->>'action' = 'expand' THEN
    v_quota := v_b->'quota';
    v_visited := coalesce(v_b->'visited','[]'::jsonb);
    v_pending := '[]'::jsonb;
    v_edges := 0;
    v_names := ARRAY['causal','entity','multi_hop','recency','semantic','temporal'];
    FOR v_i IN 1..6 LOOP
      v_bucket := v_names[v_i];
      v_left := coalesce((v_quota->>v_bucket)::int, 0);
      IF v_left <= 0 THEN CONTINUE; END IF;
      FOR v_fr IN SELECT e FROM jsonb_array_elements(
                    coalesce(v_w.frontier,'[]'::jsonb)) e LOOP
        EXIT WHEN v_left <= 0;
        IF v_bucket = 'recency' THEN
          FOR rec IN
            SELECT n.dst_hash, n.rel, n.structural
              FROM v13_mgraph_neighbors(p_sid, v_fr->>'content_hash',
                     v13_mgraph_bucket_rels(v_bucket), NULL) n
             ORDER BY n.source_at DESC NULLS LAST, n.dst_hash ASC
          LOOP
            EXIT WHEN v_left <= 0;
            IF EXISTS (
              SELECT 1 FROM jsonb_array_elements_text(v_visited) h
               WHERE h = rec.dst_hash)
               OR EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_pending) p
               WHERE p->>'content_hash' = rec.dst_hash) THEN
              CONTINUE;
            END IF;
            v_pending := v_pending || jsonb_build_array(jsonb_build_object(
              'content_hash', rec.dst_hash, 'bucket', v_bucket,
              'structural', to_jsonb(rec.structural),
              'from_hash', v_fr->>'content_hash'));
            v_left := v_left - 1;
            v_edges := v_edges + 1;
            v_quota := jsonb_set(v_quota, ARRAY[v_bucket], to_jsonb(v_left));
          END LOOP;
        ELSE
          FOR rec IN
            SELECT n.dst_hash, n.rel, n.structural
              FROM v13_mgraph_neighbors(p_sid, v_fr->>'content_hash',
                     v13_mgraph_bucket_rels(v_bucket), v_left) n
          LOOP
            IF EXISTS (
              SELECT 1 FROM jsonb_array_elements_text(v_visited) h
               WHERE h = rec.dst_hash)
               OR EXISTS (
              SELECT 1 FROM jsonb_array_elements(v_pending) p
               WHERE p->>'content_hash' = rec.dst_hash) THEN
              CONTINUE;
            END IF;
            v_pending := v_pending || jsonb_build_array(jsonb_build_object(
              'content_hash', rec.dst_hash, 'bucket', v_bucket,
              'structural', to_jsonb(rec.structural),
              'from_hash', v_fr->>'content_hash'));
            v_left := v_left - 1;
            v_edges := v_edges + 1;
            v_quota := jsonb_set(v_quota, ARRAY[v_bucket], to_jsonb(v_left));
            EXIT WHEN v_left <= 0;
          END LOOP;
        END IF;
      END LOOP;
    END LOOP;
    IF jsonb_array_length(v_pending) = 0 THEN
      UPDATE memory_walks
         SET status = 'stopped', stop_reason = 'depth', budgets = v_b
       WHERE walk_id = v_wid;
      RETURN jsonb_build_object(
        'action','expand','status','stopped','stop_reason','depth',
        'asks',0,'failed',false,'calls_used', v_w.calls_used,
        'frontier', v_w.frontier, 'walk_id', v_wid);
    END IF;
    v_b := jsonb_set(v_b, '{pending}', v_pending);
    v_b := jsonb_set(v_b, '{quota}', v_quota);
    v_b := jsonb_set(v_b, '{phase}', '"traverse"');
    v_b := jsonb_set(v_b, '{round_edges}', to_jsonb(
             coalesce((v_b->>'round_edges')::int, 0) + v_edges));
    v_b := jsonb_set(v_b, '{scored}', '[]'::jsonb);
    v_b := jsonb_set(v_b, '{basis}', '{}'::jsonb);
    v_b := jsonb_set(v_b, '{stop_attempted}', 'false'::jsonb);
    UPDATE memory_walks SET budgets = v_b WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','expand','status','open','asks',0,'failed',false,
      'calls_used', v_w.calls_used, 'frontier', v_w.frontier,
      'walk_id', v_wid, 'phase','traverse',
      'pending', jsonb_array_length(v_pending));
  ELSIF v_act->>'action' = 'close' OR v_act->>'action' = 'to_stop' THEN
    NULL; -- close handled below; to_stop already returned
  END IF;

  IF v_act->>'action' = 'ask' THEN
    IF v_b->>'provider' IS NULL OR v_b->>'model' IS NULL THEN
      v_pm := v13_mgraph_capture_pm(p_sid);
      v_b := jsonb_set(v_b, '{provider}', to_jsonb(v_pm->>'provider'));
      v_b := jsonb_set(v_b, '{model}', to_jsonb(v_pm->>'model'));
    END IF;
    v_env := v13_mgraph_envelope(p_sid, v_act->'state', v_act->'questions',
                                 v_b->>'provider', v_b->>'model');
    SELECT count(*) INTO v_c0 FROM judgment_calls WHERE session_id = p_sid;
    v_res := v13_resolve_judgments(v_env, 1);
    SELECT count(*) INTO v_c1 FROM judgment_calls WHERE session_id = p_sid;
    v_delta := (v_c1 - v_c0)::int;
    v_failed := coalesce((v_res->>'failed')::boolean, false);
    IF v_act->>'kind' IS DISTINCT FROM 'shadow' THEN
      v_w.calls_used := v_w.calls_used + v_delta;
      v_b := jsonb_set(v_b, '{round_asks}', to_jsonb(
               coalesce((v_b->>'round_asks')::int, 0) + v_delta));
    END IF;
    v_basis := coalesce(v_b->'basis', '{}'::jsonb);
    FOR v_sig IN SELECT q->>'signal' FROM jsonb_array_elements(v_act->'questions') q
    LOOP
      v_basis := v_basis || jsonb_build_object(
        v_sig, v13_mgraph_signal_class(p_sid, v_sig));
    END LOOP;
    v_b := jsonb_set(v_b, '{basis}', v_basis);
    IF v_act->>'kind' = 'route' THEN
      v_b := jsonb_set(v_b, '{route_attempted}', 'true'::jsonb);
      v_b := jsonb_set(v_b, '{phase}', '"route"');
    ELSIF v_act->>'kind' = 'shadow' THEN
      v_b := jsonb_set(v_b, '{shadow_done}', 'true'::jsonb);
    ELSIF v_act->>'kind' = 'stop' THEN
      v_b := jsonb_set(v_b, '{stop_attempted}', 'true'::jsonb);
      v_b := jsonb_set(v_b, '{phase}', '"stop"');
    ELSIF v_act->>'kind' = 'trav' THEN
      v_node := v_act->'node';
      v_hash := v_node->>'content_hash';
      v_score := v13_mgraph_transition_score(
        p_sid, v_q, v_wid, v_hash, v_node->>'bucket',
        NULLIF(v_node->>'structural','')::numeric, v_b->'weights');
      v_b := jsonb_set(v_b, '{scored}',
        coalesce(v_b->'scored','[]'::jsonb) || jsonb_build_array(
          jsonb_build_object('content_hash', v_hash, 'score', to_jsonb(v_score),
                             'bucket', v_node->>'bucket')));
      v_b := jsonb_set(v_b, '{visited}',
        coalesce(v_b->'visited','[]'::jsonb) || jsonb_build_array(v_hash));
      v_pending := coalesce((
        SELECT jsonb_agg(e ORDER BY i)
          FROM jsonb_array_elements(coalesce(v_b->'pending','[]'::jsonb))
               WITH ORDINALITY AS t(e, i)
         WHERE e->>'content_hash' IS DISTINCT FROM v_hash), '[]'::jsonb);
      v_b := jsonb_set(v_b, '{pending}', v_pending);
      v_b := jsonb_set(v_b, '{phase}', '"traverse"');
    END IF;
    UPDATE memory_walks SET budgets = v_b, calls_used = v_w.calls_used
     WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','ask','kind', v_act->>'kind','status','open',
      'asks', v_delta, 'failed', v_failed, 'calls_used', v_w.calls_used,
      'frontier', v_w.frontier, 'walk_id', v_wid, 'phase', v_b->>'phase');
  END IF;

  IF v_act->>'action' = 'close' THEN
    v_round := coalesce((v_b->>'round_no')::int, 1);
    v_asks := coalesce((v_b->>'round_asks')::int, 0);
    v_edges := coalesce((v_b->>'round_edges')::int, 0);
    v_frontier := coalesce(v_w.frontier, '[]'::jsonb);
    v_scored := coalesce(v_b->'scored', '[]'::jsonb);
    SELECT coalesce(jsonb_agg(elem ORDER BY (elem->>'score')::numeric DESC,
                                       elem->>'content_hash' ASC), '[]'::jsonb)
      INTO v_beam
      FROM (
        SELECT elem FROM (
          SELECT DISTINCT ON (elem->>'content_hash') elem
            FROM (
              SELECT e AS elem, 0 AS src
                FROM jsonb_array_elements(v_scored) e
              UNION ALL
              SELECT e, 1 FROM jsonb_array_elements(v_frontier) e
            ) u
           ORDER BY elem->>'content_hash', src
        ) d
        ORDER BY (elem->>'score')::numeric DESC, elem->>'content_hash' ASC
        LIMIT (v_pol->>'beam_width')::int
      ) z;
    v_w.nodes_used := (
      SELECT count(DISTINCT h) FROM (
        SELECT jsonb_array_elements_text(coalesce(v_b->'visited','[]'::jsonb)) AS h
        UNION
        SELECT f->>'content_hash' FROM jsonb_array_elements(v_beam) f
      ) s);
    v_w.edges_used := v_w.edges_used + v_edges;
    v_w.depth := v_w.depth + 1;
    UPDATE memory_walks
       SET frontier = v_beam, nodes_used = v_w.nodes_used,
           edges_used = v_w.edges_used, depth = v_w.depth, budgets = v_b,
           calls_used = v_w.calls_used
     WHERE walk_id = v_wid;
    INSERT INTO memory_rounds (walk_id, round, frontier_in, frontier_out, basis, asks)
    VALUES (v_wid, v_round, v_frontier, v_beam, v_b->'basis', v_asks)
    ON CONFLICT (walk_id, round) DO NOTHING;
    v_ss := v13_mgraph_should_stop(v_wid);
    IF (v_ss->>'stop')::boolean THEN
      UPDATE memory_walks SET status = 'stopped', stop_reason = v_ss->>'reason'
       WHERE walk_id = v_wid;
    ELSIF p_elapsed_ms >= (v_pol->>'max_latency_ms')::int THEN
      UPDATE memory_walks SET status = 'stopped', stop_reason = 'latency'
       WHERE walk_id = v_wid;
    ELSE
      v_b := jsonb_set(v_b, '{phase}', '"expand"');
      v_b := jsonb_set(v_b, '{round_no}', to_jsonb(v_round + 1));
      v_b := jsonb_set(v_b, '{scored}', '[]'::jsonb);
      v_b := jsonb_set(v_b, '{pending}', '[]'::jsonb);
      v_b := jsonb_set(v_b, '{basis}', '{}'::jsonb);
      v_b := jsonb_set(v_b, '{round_asks}', '0'::jsonb);
      v_b := jsonb_set(v_b, '{round_edges}', '0'::jsonb);
      v_b := jsonb_set(v_b, '{stop_attempted}', 'false'::jsonb);
      UPDATE memory_walks SET budgets = v_b, frontier = v_beam
       WHERE walk_id = v_wid;
    END IF;
    SELECT * INTO v_w FROM memory_walks WHERE walk_id = v_wid;
    RETURN jsonb_build_object(
      'action','close','status', v_w.status, 'stop_reason', v_w.stop_reason,
      'asks', 0, 'failed', false, 'calls_used', v_w.calls_used,
      'frontier', v_w.frontier, 'walk_id', v_wid, 'phase', v_w.budgets->>'phase',
      'round', v_round);
  END IF;

  RAISE EXCEPTION 'v13: mgraph run_round unhandled action %', v_act->>'action'
    USING ERRCODE = 'V3009';
END $$;

-- OQ8 evidence 出口。只读已停 walk 的 frontier,零 ask。
-- 定位键 = 当前 generation + 活动 policy_version + query_hash。
CREATE FUNCTION v13_mgraph_evidence(p_sid uuid, p_query_hash text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_k int; v_gen bigint; v_pver int; v_rows jsonb;
BEGIN
  IF p_query_hash IS NULL OR p_query_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: mgraph evidence query_hash must be 64 hex'
      USING ERRCODE = 'V3009';
  END IF;
  v_pol := v13_mgraph_policy();
  IF NOT (v_pol->>'read_enabled')::boolean THEN
    RETURN jsonb_build_object('rows', '[]'::jsonb, 'skipped', 'disabled',
                              'asks', 0);
  END IF;
  IF (v13_transcript_freshness(p_sid)->>'degraded')::boolean THEN
    RETURN jsonb_build_object('rows', '[]'::jsonb, 'skipped', 'degraded',
                              'asks', 0);
  END IF;
  v_k := (v_pol->>'inject_top_k')::int;
  v_gen := (v13_mgraph_progress(p_sid)->>'generation')::bigint;
  SELECT version INTO v_pver FROM v13_policies WHERE name = 'mgraph' AND active;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'content_hash', x.content_hash, 'score', x.score, 'body', n.body)
           ORDER BY x.score DESC, x.content_hash ASC), '[]'::jsonb)
    INTO v_rows
    FROM (
      SELECT f->>'content_hash' AS content_hash,
             (f->>'score')::numeric AS score
        FROM memory_walks w
        CROSS JOIN LATERAL jsonb_array_elements(w.frontier) AS f
       WHERE w.session_id = p_sid
         AND w.query_hash = p_query_hash
         AND w.mgraph_generation = v_gen
         AND w.policy_version = v_pver
         AND w.status = 'stopped'
       ORDER BY (f->>'score')::numeric DESC, f->>'content_hash' ASC
       LIMIT v_k
    ) x
    JOIN memory_nodes n
      ON n.session_id = p_sid AND n.content_hash = x.content_hash;
  RETURN jsonb_build_object('rows', coalesce(v_rows, '[]'::jsonb),
                            'skipped', NULL, 'asks', 0);
END $$;

-- === §4 ACL(M3 面) ===
REVOKE ALL ON memory_walks, memory_rounds FROM PUBLIC;
GRANT SELECT ON memory_walks, memory_rounds
  TO v13_recall, v13_resolve, v13_route;
GRANT INSERT, UPDATE ON memory_walks TO v13_resolve;
GRANT INSERT ON memory_rounds TO v13_resolve;

REVOKE EXECUTE ON FUNCTION
  v13_mgraph_walk_id(uuid,text,bigint,int),
  v13_mgraph_bucket_rels(text),
  v13_mgraph_neighbors(uuid,text,text[],int),
  v13_mgraph_structural_reach(uuid,text,int),
  v13_mgraph_route(text),
  v13_mgraph_allocate(jsonb),
  v13_mgraph_primary_bucket(jsonb),
  v13_mgraph_signal_class(uuid,text),
  v13_mgraph_component(uuid,text),
  v13_mgraph_anchors(uuid,text,text),
  v13_mgraph_trav_questions(uuid,text,int),
  v13_mgraph_stop_questions(uuid,int),
  v13_mgraph_route_questions(text,bigint),
  v13_mgraph_trav_state(uuid,text,jsonb),
  v13_mgraph_stop_state(uuid,text,jsonb),
  v13_mgraph_transition_score(uuid,text,uuid,text,text,numeric,jsonb),
  v13_mgraph_should_stop(uuid),
  v13_mgraph_next_action(uuid,text,int),
  v13_mgraph_capture_pm(uuid),
  v13_mgraph_run_round(uuid,text,int),
  v13_mgraph_evidence(uuid,text)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
  v13_mgraph_neighbors(uuid,text,text[],int),
  v13_mgraph_structural_reach(uuid,text,int),
  v13_mgraph_route(text),
  v13_mgraph_allocate(jsonb),
  v13_mgraph_evidence(uuid,text),
  v13_mgraph_primary_bucket(jsonb)
TO v13_recall, v13_resolve;

GRANT EXECUTE ON FUNCTION
  v13_mgraph_walk_id(uuid,text,bigint,int),
  v13_mgraph_bucket_rels(text),
  v13_mgraph_signal_class(uuid,text),
  v13_mgraph_component(uuid,text),
  v13_mgraph_anchors(uuid,text,text),
  v13_mgraph_trav_questions(uuid,text,int),
  v13_mgraph_stop_questions(uuid,int),
  v13_mgraph_route_questions(text,bigint),
  v13_mgraph_trav_state(uuid,text,jsonb),
  v13_mgraph_stop_state(uuid,text,jsonb),
  v13_mgraph_transition_score(uuid,text,uuid,text,text,numeric,jsonb),
  v13_mgraph_should_stop(uuid),
  v13_mgraph_next_action(uuid,text,int),
  v13_mgraph_capture_pm(uuid),
  v13_mgraph_run_round(uuid,text,int)
TO v13_resolve;

COMMIT;

BEGIN;

-- =========================================================================
-- DP9 M4 consolidation (v13_mgraph.sql M4 segment, plan §3.4 固化①-⑥ /
-- §3.1 memory_consolidations / §5 F-gates): five-question pair
-- consolidation + generation upgrade on the NEW effect kind
-- mgraph_consolidate (OQ6: never kind=llm — v13_complete writes
-- llm/message unconditionally for llm and route P0 would finish the turn
-- on it; never context_summary — that is another pipeline eating the
-- summary day-cap) + fidelity gate + consolidation nodes (first
-- remote-plane artifacts; retrieval object = node content_hash, reachable
-- only via traversal, never a candidate anchor — F9).
-- Roles (Oracle review P1-4): route only enqueues/completes; resolve only
-- asks questions, inserts nodes, settles (reads effects.result, updates
-- the queue). kind CHECK + cap v3 + narrow requeue + the whole chain load
-- in ONE transaction: no state exists where the CHECK admits the kind but
-- the cap lacks the key or the requeue walls it (F8; 禁先扩 CHECK 后补
-- cap). v13_complete is NOT touched (generic CAS branch: effect_done
-- only — zero llm/message, zero turn/end, zero resolve/failed, route
-- cannot finish on it — F2). Error family V3009; zero DEFINER; source
-- scan five tokens stay zero; the stannum bind operator count stays 1.
-- =========================================================================

-- === effect kind 第七值(词表 append-only,旧六值零动,仪式照
--     summary:25-28) ===
ALTER TABLE effects DROP CONSTRAINT effects_kind_check;
ALTER TABLE effects ADD CONSTRAINT effects_kind_check CHECK (kind IN
  ('judge','tool','llm','context_refresh','human','context_summary',
   'mgraph_consolidate'));

-- === effect_attempt_cap v3(七键齐全;仪式照 summary:31-40:INSERT
--     inactive→双 UPDATE 同事务翻;v2 六键逐字保留;本键 cap=2=两轮
--     封顶,与 context_summary 同量级;README 翻新纪律:新版本必含全
--     七键,降 cap 需清场) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('effect_attempt_cap', 3,
 '{"judge":4,"tool":3,"llm":3,"human":2,"context_refresh":3,'
 '"context_summary":2,"mgraph_consolidate":2}'::jsonb,
 false);
UPDATE v13_policies SET active = false
 WHERE name = 'effect_attempt_cap' AND active;
UPDATE v13_policies SET active = true
 WHERE name = 'effect_attempt_cap' AND version = 3;

-- === 窄 v13_requeue_stale(活体 OR REPLACE——§1.2-1 允许的唯一触碰点;
--     替换基底=periphery 库 pg_get_functiondef 导出的活体定义,与
--     twophase:33 加载源逐字一致,非 recall 文本)。仅 mgraph_consolidate
--     加入 judge 待遇:cap 内回收 ready(只 fence+1,attempt_no 不动)、
--     超 cap 转 failed+lease_exhausted+唤醒;cap 判定按行 kind 调
--     v13_attempt_ok(kind, attempt_no)(core:196 共用谓词,不硬编码
--     'judge'——F8);其余 kind(tool/llm/human/context_refresh/
--     context_summary)走 (a2) unknown 墙,行为字节不变 ===
CREATE OR REPLACE FUNCTION v13_requeue_stale() RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_j int; v_u int; v_w int := 0; v_k int; v_f int; r record; v_id uuid;
  v_ids uuid[];
BEGIN
  UPDATE effects
     SET status='ready', fence=fence+1,            -- attempt_no 不动(turn 9,#58)
         lease_owner=NULL, lease_until=NULL
   WHERE status='claimed' AND kind IN ('judge','mgraph_consolidate')
     AND lease_until < clock_timestamp()
     AND v13_attempt_ok(kind, attempt_no);  -- 共用 cap(turn 8,#55;按行 kind 判定,M4/F8)
  GET DIAGNOSTICS v_j = ROW_COUNT;                   -- (a1) judge+mgraph_consolidate 回收重放数
  WITH capped AS (
    UPDATE effects
       SET status='failed', fence=fence+1,         -- attempt_no 不动(turn 9,#58)
           lease_owner=NULL, lease_until=NULL,
           error=jsonb_build_object('code','lease_exhausted')
     WHERE status='claimed' AND kind IN ('judge','mgraph_consolidate')
       AND lease_until < clock_timestamp()
       AND NOT v13_attempt_ok(kind, attempt_no)  -- 超 cap:可结算终态(按行 kind,M4)
    RETURNING effect_id)
  SELECT coalesce(array_agg(effect_id), '{}'::uuid[]) INTO v_ids FROM capped;
  v_f := coalesce(array_length(v_ids, 1), 0);        -- (a1') lease 耗竭终态数
  UPDATE effects
     SET status='unknown', fence=fence+1,           -- attempt_no 不动(turn 9,#58)
         lease_owner=NULL, lease_until=NULL
   WHERE status='claimed' AND kind NOT IN ('judge','mgraph_consolidate')
     AND lease_until < clock_timestamp();
  GET DIAGNOSTICS v_u = ROW_COUNT;                   -- (a2) 转墙数(其余 kind 行为不变)
  FOR r IN SELECT effect_id FROM effects WHERE status='ready' LOOP
    PERFORM v13_send_work(r.effect_id);              -- 唤醒重建(可丢消息的地基)
    v_w := v_w + 1;
  END LOOP;
  FOREACH v_id IN ARRAY v_ids LOOP
    PERFORM v13_send_work(v_id);                     -- 唤醒 settle(turn 8,#55)
  END LOOP;
  SELECT count(*) INTO v_k FROM effects WHERE status='unknown';
  RETURN jsonb_build_object('reclaimed_ready', v_j, 'walled_unknown', v_u,
                            'lease_exhausted', v_f,
                            'woken_ready', v_w, 'walls_total', v_k);
END $$;
-- ACL 经 OR REPLACE 原样保留(REVOKE PUBLIC + GRANT v13_route,twophase 尾)

-- === §1.5 pair_digest(v13_body_hash(src||'>'||dst),输入已是哈希,稳定) ===
CREATE FUNCTION v13_mgraph_pair_digest(p_src text, p_dst text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT v13_body_hash(p_src || '>' || p_dst);
$$;

-- === §3.4 固化① 选对枚举(v2 V2 B2 对源=proximity-derived,OQ17 裁决):
--     同会话 origin='proximity' 的边、两端均 episodic → 按
--     (source_at ASC, content_hash ASC) 规范化为无序对 (early,late) →
--     去重 → digest=v13_mgraph_pair_digest(early,late)(v1 相邻对方向
--     一致 ⇒ digest 字节级不变,决策缓存不失效;时间相邻但零词法激活的
--     对不再进对源——语义收窄已裁)。「未被 consolidation_key 覆盖」的
--     排除仅 status='adopted'(§3.1:rejected 允许重入队),由调用方按
--     队列行判定。诚实语义:这是由已落库的激活 proximity 对
--     (lexical_norm≥graph_activation_threshold 才插边)衍生的固化候选,
--     不是所有历史关系封的审计池(README 机制 20;覆盖低于阈值的已问对
--     须另建关系候选审计表) ===
CREATE FUNCTION v13_mgraph_cons_pairs(p_sid uuid)
RETURNS TABLE(src text, dst text, src_body text, dst_body text,
              consolidation_key text)
LANGUAGE sql STABLE AS $$
  WITH ends AS (
    SELECT content_hash, body, source_at
      FROM memory_nodes
     WHERE session_id = p_sid AND origin = 'episodic'),
  linked AS (
    SELECT a.content_hash AS ah, a.body AS ab, a.source_at AS at_,
           b.content_hash AS bh, b.body AS bb, b.source_at AS bt
      FROM memory_links l
      JOIN ends a ON a.content_hash = l.src_hash
      JOIN ends b ON b.content_hash = l.dst_hash
     WHERE l.session_id = p_sid
       AND l.origin = 'proximity'
       AND l.src_hash <> l.dst_hash),
  canon AS (
    SELECT DISTINCT
           CASE WHEN (l.at_, l.ah) < (l.bt, l.bh)
                THEN l.ah ELSE l.bh END AS eh,
           CASE WHEN (l.at_, l.ah) < (l.bt, l.bh)
                THEN l.ab ELSE l.bb END AS eb,
           CASE WHEN (l.at_, l.ah) < (l.bt, l.bh)
                THEN l.bh ELSE l.ah END AS lh,
           CASE WHEN (l.at_, l.ah) < (l.bt, l.bh)
                THEN l.bb ELSE l.ab END AS lb
      FROM linked l)
  SELECT c.eh AS src, c.lh AS dst, c.eb AS src_body, c.lb AS dst_body,
         v13_mgraph_pair_digest(c.eh, c.lh) AS consolidation_key
    FROM canon c
   ORDER BY c.eh, c.lh;
$$;

-- === §3.4 固化② 五问集(每对一封;同一 left/right state,representation
--     与四 Noul 同投影 ["left","right"] 可同批——不变量 7/§1.3-OQ6;
--     obsolete 在列=证据可落库,子型/门控不读它) ===
CREATE FUNCTION v13_mgraph_cons_questions(p_src text, p_dst text,
                                          p_left_body text, p_right_body text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_key text;
BEGIN
  IF p_src IS NULL OR p_src !~ '^[0-9a-f]{64}$'
     OR p_dst IS NULL OR p_dst !~ '^[0-9a-f]{64}$'
     OR p_left_body IS NULL OR octet_length(p_left_body) = 0
     OR p_right_body IS NULL OR octet_length(p_right_body) = 0 THEN
    RAISE EXCEPTION
      'v13: cons question inputs must be 64hex hashes + non-empty bodies'
      USING ERRCODE = 'V3009';
  END IF;
  v_key := v13_mgraph_pair_digest(p_src, p_dst);
  RETURN jsonb_build_array(
    jsonb_build_object('signal', 'mem_cons::' || v_key || '::redundant',
                       'template_name', 'mem_cons_redundant'),
    jsonb_build_object('signal', 'mem_cons::' || v_key || '::contradiction',
                       'template_name', 'mem_cons_contradiction'),
    jsonb_build_object('signal', 'mem_cons::' || v_key || '::obsolete',
                       'template_name', 'mem_cons_obsolete'),
    jsonb_build_object('signal', 'mem_cons::' || v_key || '::link',
                       'template_name', 'mem_cons_link'),
    jsonb_build_object('signal', 'mem_cons::' || v_key || '::representation',
                       'template_name', 'mem_cons_representation'));
END $$;

-- === §3.4 固化③ 子型(apply 只读 decisions):consolidation_priority 序
--     首个 noul≥relation_threshold 的方面;无过阈者退 link(合并产物
--     至少 related_to)。obsolete 不进判定(只作证据,P1-5;不进
--     priority 数组) ===
CREATE FUNCTION v13_mgraph_cons_subtype(p_sid uuid, p_key text)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_thr numeric; v_prio text[]; v_asp text;
BEGIN
  v_pol := v13_mgraph_policy();
  v_thr := (v_pol->>'relation_threshold')::numeric;
  v_prio := ARRAY(SELECT jsonb_array_elements_text(v_pol->'consolidation_priority'));
  FOREACH v_asp IN ARRAY v_prio LOOP
    IF v13_mgraph_signal_class(p_sid, 'mem_cons::' || p_key || '::' || v_asp)
         = 'noul'
       AND coalesce(v13_mgraph_component(
             p_sid, 'mem_cons::' || p_key || '::' || v_asp), 0) >= v_thr THEN
      RETURN v_asp;
    END IF;
  END LOOP;
  RETURN 'link';
END $$;

-- === §3.4 固化③ 生成门:choice∈{merge,promote} ∧ 所选概率≥
--     consolidation_choice_min ∧ contradiction<consolidation_threshold
--     (矛盾过阈即使 choice=merge 也不入队,OQ6);任一判断缺失=exclude
--     (OQ11 mem_cons 三态),不伪造概率 ===
CREATE FUNCTION v13_mgraph_cons_gate(p_sid uuid, p_key text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_rep jsonb; v_choice text; v_contra numeric;
BEGIN
  v_pol := v13_mgraph_policy();
  SELECT d.answer INTO v_rep
    FROM decisions d
   WHERE d.session_id = p_sid
     AND d.signal = 'mem_cons::' || p_key || '::representation'
     AND d.answer IS NOT NULL AND d.status IN ('answered','cached')
   ORDER BY d.answered_at DESC NULLS LAST LIMIT 1;
  IF v_rep IS NULL OR jsonb_typeof(v_rep->'choice') IS DISTINCT FROM 'string'
  THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'representation_missing');
  END IF;
  v_choice := v_rep->>'choice';
  IF v_choice NOT IN ('merge','promote') THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'choice_' || v_choice);
  END IF;
  IF jsonb_typeof(v_rep->'probabilities'->v_choice) IS DISTINCT FROM 'number'
     OR (v_rep->'probabilities'->>v_choice)::numeric
        < (v_pol->>'consolidation_choice_min')::numeric THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'choice_prob');
  END IF;
  v_contra := v13_mgraph_component(p_sid, 'mem_cons::' || p_key || '::contradiction');
  IF v_contra IS NULL THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'contradiction_missing');
  END IF;
  IF v_contra >= (v_pol->>'consolidation_threshold')::numeric THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'contradiction');
  END IF;
  RETURN jsonb_build_object('allowed', true, 'reason', NULL,
                            'subtype', v13_mgraph_cons_subtype(p_sid, p_key));
END $$;

-- === §3.4 固化①②③ resolve 侧驱动:选对+每对五问一封+apply 只读
--     decisions(③ 的 gate 报告在返回值里;队列写入不在此面——
--     memory_consolidations INSERT 是 route 侧 enqueue 的事,M1 ACL 预授)。
--     每调用至多一封真实 ask(GUC mock 单批形状限制,一步一封=偏差
--     台账 #17/#19 同族;缓存命中的对零 ask 连续处理),judge_spend
--     over→零 ask 跳过(§3.5);resolve failed→failed 停(零队列副作用) ===
CREATE FUNCTION v13_mgraph_consolidate(p_sid uuid, p_limit int DEFAULT 10)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_pm jsonb; v_elig jsonb := '[]'::jsonb;
  v_seen int := 0; v_asks int := 0; v_c0 bigint; v_c1 bigint;
  v_stop text; v_failed boolean := false;
  v_state jsonb; v_qs jsonb; v_env jsonb; v_res jsonb; v_gate jsonb;
  v_pver int; r record;
BEGIN
  IF p_limit IS NULL OR p_limit < 1 THEN
    RAISE EXCEPTION 'v13: mgraph consolidate limit must be >= 1'
      USING ERRCODE = 'V3009';
  END IF;
  IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
    RETURN jsonb_build_object('status','skipped','skipped','spend',
                              'failed', false, 'asks', 0, 'pairs', 0,
                              'eligible', '[]'::jsonb);
  END IF;
  SELECT version INTO v_pver FROM v13_policies
   WHERE name = 'mgraph' AND active;
  v_pm := v13_mgraph_capture_pm(p_sid);
  <<pairs>> FOR r IN
    SELECT p.src, p.dst, p.src_body, p.dst_body, p.consolidation_key
      FROM v13_mgraph_cons_pairs(p_sid) p
  LOOP
    CONTINUE pairs WHEN EXISTS (
      SELECT 1 FROM memory_consolidations q
       WHERE q.session_id = p_sid
         AND q.consolidation_key = r.consolidation_key
         AND q.status = 'adopted');
    v_seen := v_seen + 1;
    v_state := jsonb_build_object(
      'left',  jsonb_build_object('content', r.src_body),
      'right', jsonb_build_object('content', r.dst_body));
    v_qs := v13_mgraph_cons_questions(r.src, r.dst, r.src_body, r.dst_body);
    v_env := v13_mgraph_envelope(p_sid, v_state, v_qs,
                                 v_pm->>'provider', v_pm->>'model');
    SELECT count(*) INTO v_c0 FROM judgment_calls WHERE session_id = p_sid;
    SELECT v13_resolve_judgments(v_env, 1) INTO v_res;
    SELECT count(*) INTO v_c1 FROM judgment_calls WHERE session_id = p_sid;
    v_asks := v_asks + (v_c1 - v_c0)::int;
    IF coalesce(v_res->>'failed', 'false')::boolean THEN
      v_failed := true; v_stop := 'failed'; EXIT pairs;
    END IF;
    v_gate := v13_mgraph_cons_gate(p_sid, r.consolidation_key);
    IF (v_gate->>'allowed')::boolean THEN
      v_elig := v_elig || jsonb_build_array(jsonb_build_object(
        'consolidation_key', r.consolidation_key,
        'src', r.src, 'dst', r.dst,
        'subtype', v_gate->>'subtype'));
    END IF;
    EXIT pairs WHEN v_seen >= least(p_limit, 512);
    IF (v_c1 - v_c0) > 0 THEN
      v_stop := 'step'; EXIT pairs;      -- 一步一封:真实 ask 后收步
    END IF;
    IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
      v_stop := 'spend'; EXIT pairs;
    END IF;
  END LOOP pairs;
  RETURN jsonb_build_object(
    'status', CASE WHEN v_failed THEN 'failed'
                  WHEN v_stop IS NOT NULL THEN 'stopped' ELSE 'ok' END,
    'stop_reason', v_stop, 'failed', v_failed,
    'pairs', v_seen, 'asks', v_asks, 'policy_version', v_pver,
    'eligible', v_elig);
END $$;

-- === §3.4 固化④ route 侧入队(队列写入面):入口先做失败收敛 sweep
--     (generating 行的 effect 已死——行丢失/failed/cancelled/unknown
--     →rejected;不建第四态,§3.1),再过单活跃闸(会话已有
--     ready|claimed|unknown→NULL,闸面与 advance ① 一致,强于摘要闸的
--     ready|claimed——README 运维注记③),再按 consolidation_priority
--     并列序(key 升序终裁)选最高优先 eligible 对:队列行 INSERT
--     (queued;rejected→queued 翻回=显式重入队)→v13_enqueue_effect
--     (幂等唯一权威=queue PK;effect_id 用其返回值,不自行推导;cap
--     七键缺键 fail-loud)→行转 generating ===
CREATE FUNCTION v13_mgraph_consolidate_enqueue(p_sid uuid)
RETURNS uuid LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_pver int; v_prio text[]; r record;
  v_rank int; v_best_rank int; v_best_key text;
  v_best_left text; v_best_right text;
  v_gate jsonb; v_id uuid; v_st text;
BEGIN
  UPDATE memory_consolidations q
     SET status = 'rejected', decided_at = now()
   WHERE q.session_id = p_sid AND q.status = 'generating'
     AND NOT EXISTS (
       SELECT 1 FROM effects e
        WHERE e.effect_id = q.effect_id
          AND e.status IN ('ready','claimed','succeeded'));
  IF EXISTS (SELECT 1 FROM effects
              WHERE session_id = p_sid
                AND status IN ('ready','claimed','unknown')) THEN
    RETURN NULL;
  END IF;
  SELECT version INTO v_pver FROM v13_policies
   WHERE name = 'mgraph' AND active;
  v_prio := ARRAY(SELECT jsonb_array_elements_text(
                     v13_mgraph_policy()->'consolidation_priority'));
  v_best_rank := NULL;
  FOR r IN
    SELECT p.src, p.dst, p.consolidation_key
      FROM v13_mgraph_cons_pairs(p_sid) p
  LOOP
    CONTINUE WHEN EXISTS (
      SELECT 1 FROM memory_consolidations q
       WHERE q.session_id = p_sid
         AND q.consolidation_key = r.consolidation_key
         AND q.status = 'adopted');
    v_gate := v13_mgraph_cons_gate(p_sid, r.consolidation_key);
    CONTINUE WHEN NOT (v_gate->>'allowed')::boolean;
    v_rank := array_position(v_prio, v_gate->>'subtype');
    IF v_best_rank IS NULL OR v_rank < v_best_rank
       OR (v_rank = v_best_rank AND r.consolidation_key < v_best_key) THEN
      v_best_rank := v_rank; v_best_key := r.consolidation_key;
      v_best_left := r.src; v_best_right := r.dst;
    END IF;
  END LOOP;
  IF v_best_key IS NULL THEN RETURN NULL; END IF;
  INSERT INTO memory_consolidations (session_id, consolidation_key, status)
  VALUES (p_sid, v_best_key, 'queued')
  ON CONFLICT (session_id, consolidation_key) DO UPDATE
     SET status = 'queued', decided_at = NULL
   WHERE memory_consolidations.status = 'rejected';
  v_id := v13_enqueue_effect(p_sid, 'mgraph_consolidate',
    jsonb_build_object(
      'purpose', 'mgraph_consolidate',
      'left_hash', v_best_left, 'right_hash', v_best_right,
      'consolidation_key', v_best_key, 'policy_version', v_pver));
  SELECT status INTO v_st FROM effects WHERE effect_id = v_id;
  IF v_st IN ('ready','claimed') THEN
    UPDATE memory_consolidations
       SET status = 'generating', effect_id = v_id, decided_at = NULL
     WHERE session_id = p_sid AND consolidation_key = v_best_key;
    RETURN v_id;
  ELSIF v_st = 'succeeded' THEN
    RETURN NULL;            -- complete 已落、settle 待跑:不重复 enqueue(queue PK 幂等)
  END IF;
  UPDATE memory_consolidations          -- 重挂被 cap 拒(行终态):收敛 rejected(§3.1)
     SET status = 'rejected', decided_at = now()
   WHERE session_id = p_sid AND consolidation_key = v_best_key;
  RETURN NULL;
END $$;

-- === §3.4 固化⑤⑥ resolve 侧结算:读 effect.result→确定性检查(非空、
--     字节≤consolidate_max_body_bytes、两枚亲本哈希仍在;任一失败→行
--     rejected+body_hash 回填,零 fidelity ask——§6.4 确定性检查失败不
--     调 Jev)→fidelity 信封(投影 ["source","summary"])→include 才插
--     consolidation 节点+固化边(src=left_hash,dst=新 content_hash,
--     rel=子型映射 contradiction→contradicts、redundant→redundant_with、
--     link→related_to,origin='consolidation';原文节点与既有边不
--     DELETE)+行 adopted;非 include→rejected(rejected 不重问同一正文
--     ——重试必须新正文,由 effect attempt 承载);幂等:adopted/
--     rejected 行二次 settle 零 ask;探测 effect 非 succeeded 即
--     rejected(§3.1)。图变更段持 mgraph-build 同 key 事务级咨询锁 ===
CREATE FUNCTION v13_mgraph_consolidate_settle(p_effect uuid)
RETURNS jsonb LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  v_eff effects%ROWTYPE; v_sid uuid; v_key text; v_left text; v_right text;
  v_row memory_consolidations%ROWTYPE; v_pol jsonb; v_pver int;
  v_text text; v_hash text; v_lb text; v_rb text;
  v_lat timestamptz; v_rat timestamptz; v_reason text;
  v_state jsonb; v_qs jsonb; v_env jsonb; v_res jsonb; v_pm jsonb;
  v_asks int := 0; v_c0 bigint; v_c1 bigint; v_fid numeric;
  v_rel text; v_asp text;
BEGIN
  SELECT * INTO v_eff FROM effects WHERE effect_id = p_effect;
  IF v_eff.effect_id IS NULL THEN
    RAISE EXCEPTION 'v13: mgraph settle on unknown effect %', p_effect
      USING ERRCODE = 'V3009';
  END IF;
  IF v_eff.kind <> 'mgraph_consolidate' THEN
    RAISE EXCEPTION 'v13: mgraph settle on non-consolidation effect %', p_effect
      USING ERRCODE = 'V3009';
  END IF;
  v_sid := v_eff.session_id;
  SELECT * INTO v_row FROM memory_consolidations
   WHERE session_id = v_sid AND effect_id = p_effect;
  IF v_row.consolidation_key IS NULL THEN
    RETURN jsonb_build_object('status','orphan','asks',0);
  END IF;
  v_key := v_row.consolidation_key;
  IF v_row.status IN ('adopted','rejected') THEN
    RETURN jsonb_build_object('status', v_row.status, 'asks', 0,
                              'consolidation_key', v_key);
  END IF;
  IF v_eff.status <> 'succeeded' THEN
    UPDATE memory_consolidations
       SET status = 'rejected', decided_at = now()
     WHERE session_id = v_sid AND consolidation_key = v_key;
    RETURN jsonb_build_object('status','rejected','asks',0,'reason',
                              'effect_' || v_eff.status,
                              'consolidation_key', v_key);
  END IF;
  v_pol := v13_mgraph_policy();
  SELECT version INTO v_pver FROM v13_policies
   WHERE name = 'mgraph' AND active;
  v_left := v_eff.request->>'left_hash';
  v_right := v_eff.request->>'right_hash';
  v_text := NULL;
  IF jsonb_typeof(v_eff.result) = 'object'
     AND jsonb_typeof(v_eff.result->'text') = 'string' THEN
    v_text := v_eff.result->>'text';
  END IF;
  -- 图变更与亲本读取同锁(build 同 key:读写不并发,已提交前缀自洽)
  PERFORM pg_advisory_xact_lock(v13_lock_key(v_sid, 'mgraph-build'));
  v_reason := NULL;
  IF v_text IS NULL OR btrim(v_text) = '' THEN
    v_reason := 'empty_text';
  ELSIF octet_length(v_text)
          > (v_pol->>'consolidate_max_body_bytes')::int THEN
    v_reason := 'over_budget';
  ELSIF (SELECT count(DISTINCT content_hash) FROM memory_nodes
          WHERE session_id = v_sid
            AND content_hash IN (v_left, v_right)) <> 2 THEN
    v_reason := 'parent_gone';
  END IF;
  IF v_reason IS NOT NULL THEN
    UPDATE memory_consolidations
       SET status = 'rejected', decided_at = now(),
           body_hash = coalesce(
             CASE WHEN v_text IS NOT NULL AND btrim(v_text) <> ''
                  THEN v13_body_hash(v_text) END, body_hash)
     WHERE session_id = v_sid AND consolidation_key = v_key;
    RETURN jsonb_build_object('status','rejected','asks',0,'reason', v_reason,
                              'consolidation_key', v_key);
  END IF;
  IF (v13_judge_spend(v_sid)->>'over')::boolean THEN
    RETURN jsonb_build_object('status','skipped','skipped','spend','asks',0,
                              'consolidation_key', v_key);
  END IF;
  SELECT body, source_at INTO v_lb, v_lat FROM memory_nodes
   WHERE session_id = v_sid AND content_hash = v_left;
  SELECT body, source_at INTO v_rb, v_rat FROM memory_nodes
   WHERE session_id = v_sid AND content_hash = v_right;
  v_state := jsonb_build_object('source', v_lb || E'\n' || v_rb,
                                'summary', v_text);
  v_qs := jsonb_build_array(jsonb_build_object(
           'signal', 'mem_cons::' || v_key || '::fidelity',
           'template_name', 'mem_cons_fidelity'));
  v_pm := v13_mgraph_capture_pm(v_sid);
  v_env := v13_mgraph_envelope(v_sid, v_state, v_qs,
                               v_pm->>'provider', v_pm->>'model');
  SELECT count(*) INTO v_c0 FROM judgment_calls WHERE session_id = v_sid;
  SELECT v13_resolve_judgments(v_env, 1) INTO v_res;
  SELECT count(*) INTO v_c1 FROM judgment_calls WHERE session_id = v_sid;
  v_asks := (v_c1 - v_c0)::int;
  IF coalesce(v_res->>'failed', 'false')::boolean THEN
    UPDATE memory_consolidations
       SET status = 'rejected', decided_at = now(),
           body_hash = coalesce(v13_body_hash(v_text), body_hash)
     WHERE session_id = v_sid AND consolidation_key = v_key;
    RETURN jsonb_build_object('status','rejected','asks',v_asks,
                              'reason','fidelity_failed',
                              'consolidation_key', v_key);
  END IF;
  v_fid := v13_mgraph_component(v_sid, 'mem_cons::' || v_key || '::fidelity');
  IF v_fid IS NULL
     OR v_fid < (v_pol->>'consolidation_choice_min')::numeric THEN
    UPDATE memory_consolidations
       SET status = 'rejected', decided_at = now(),
           body_hash = coalesce(v13_body_hash(v_text), body_hash)
     WHERE session_id = v_sid AND consolidation_key = v_key;
    RETURN jsonb_build_object('status','rejected','asks',v_asks,
                              'reason','fidelity_exclude',
                              'consolidation_key', v_key);
  END IF;
  v_hash := v13_body_hash(v_text);
  v_asp := v13_mgraph_cons_subtype(v_sid, v_key);
  v_rel := CASE v_asp WHEN 'contradiction' THEN 'contradicts'
                      WHEN 'redundant'  THEN 'redundant_with'
                      ELSE 'related_to' END;
  INSERT INTO memory_nodes (session_id, content_hash, body, origin,
                            source_hashes, source_at, builder_version,
                            consolidation_key)
  VALUES (v_sid, v_hash, v_text, 'consolidation', ARRAY[v_left, v_right],
          GREATEST(v_lat, v_rat), v_pver, v_key)
  ON CONFLICT (session_id, content_hash) DO NOTHING;
  INSERT INTO memory_links (session_id, src_hash, dst_hash, rel, origin,
                            decision_id, structural, policy_version)
  VALUES (v_sid, v_left, v_hash, v_rel, 'consolidation', NULL, NULL, v_pver)
  ON CONFLICT DO NOTHING;
  UPDATE memory_consolidations
     SET status = 'adopted', decided_at = now(), body_hash = v_hash
   WHERE session_id = v_sid AND consolidation_key = v_key;
  RETURN jsonb_build_object('status','adopted','asks',v_asks,
                            'consolidation_key', v_key,
                            'node_hash', v_hash, 'edge_rel', v_rel);
END $$;

-- === §4 ACL(M4 面;settle 面补齐:resolve 读 effects.result;
--     enqueue 的 ③ apply 再读面:route 读 decisions——偏差台账;
--     队列写入面=M1 预授的 route INSERT/UPDATE) ===
GRANT SELECT ON effects TO v13_resolve;
GRANT SELECT ON decisions TO v13_route;
REVOKE EXECUTE ON FUNCTION
  v13_mgraph_pair_digest(text,text),
  v13_mgraph_cons_pairs(uuid),
  v13_mgraph_cons_questions(text,text,text,text),
  v13_mgraph_cons_subtype(uuid,text),
  v13_mgraph_cons_gate(uuid,text),
  v13_mgraph_consolidate(uuid,int),
  v13_mgraph_consolidate_enqueue(uuid),
  v13_mgraph_consolidate_settle(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_pair_digest(text,text),
  v13_mgraph_cons_pairs(uuid),
  v13_mgraph_cons_questions(text,text,text,text),
  v13_mgraph_cons_subtype(uuid,text),
  v13_mgraph_cons_gate(uuid,text)
TO v13_resolve, v13_route;                     -- 选对/五问/apply 共享只读面
GRANT EXECUTE ON FUNCTION v13_mgraph_consolidate(uuid,int)
TO v13_resolve;
GRANT EXECUTE ON FUNCTION v13_mgraph_consolidate_enqueue(uuid)
TO v13_route;
GRANT EXECUTE ON FUNCTION v13_mgraph_consolidate_settle(uuid)
TO v13_resolve;

COMMIT;

BEGIN;

-- =========================================================================
-- mgraph v2 V1 候选发现唤醒(v2 计划 docs/plans/v13-dp9-mgraph-v2-plan-
-- 2026-09-24.md §3.1;OQ15=2 A5/OQ16=1):本地锚编译器三函数。recall 三
-- 函数(v13_query_segments/v13_build_tinql/v13_tinql_terms)字节不变,
-- OR/n-gram 文法留在 mgraph 自有文件(新树只追加纪律;R2 修订 OQ7 的
-- 守卫面与锚源正式切换)。三函数均 STABLE:经 v13_mgraph_policy() 读
-- 活动策略,禁 IMMUTABLE(P1-1——策略翻版必须能改变锚形态,IMMUTABLE
-- 声明可能让 planner/预编译计划缓存旧策略结果);零 IO、不访问图、
-- 零 `==>`、零第二动态绑定点(G6 执法)。错误码 V3005(文法域,沿
-- recall 守卫族)。机制:latin 段整项+CJK 段按字符切 n-gram
-- (anchor_ngram_n;0=关=全段 OR 语义退化,P2-2);边界钉死(P1-2):
-- 段字符长=n 恰一项、<n 零项、>n 滑窗 L−n+1 项;去重保序;超
-- anchor_max_terms 保序截断;空 body→空项→空 tinql→candidates 空集
-- 零 ask。确定性口径:同一 body+同一活动策略快照→相同 terms→相同
-- tinql→相同谓词输入(非跨策略版本全局不可变)。
-- =========================================================================

-- === 亚子句锚项:latin 段整项 + CJK 段按字符 n-gram;返回去重保序项集 ===
CREATE FUNCTION v13_mgraph_anchor_terms(p_body text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol  jsonb; v_n int; v_max int;
  v_segs text[]; v_seg text;
  v_len  int; v_i int; v_gram text;
  v_terms text[] := '{}';
BEGIN
  IF p_body IS NULL OR p_body = '' THEN RETURN '[]'::jsonb; END IF;
  v_pol := v13_mgraph_policy();
  v_n := (v_pol->>'anchor_ngram_n')::int;
  v_max := (v_pol->>'anchor_max_terms')::int;
  v_segs := ARRAY(SELECT jsonb_array_elements_text(v13_query_segments(p_body)));
  FOREACH v_seg IN ARRAY v_segs LOOP
    EXIT WHEN cardinality(v_terms) >= v_max;
    IF v_n = 0 OR v_seg ~ '^[A-Za-z0-9]+$' THEN
      -- latin 段整项(n-gram 不切);n=0 时 CJK 段也整项(A2 全段 OR 退化)
      IF NOT (v_seg = ANY(v_terms)) THEN
        v_terms := v_terms || v_seg;
      END IF;
    ELSE
      -- CJK 段按字符切 n-gram:长度=n 恰一项(P1-2 边界钉死),<n 零项
      v_len := char_length(v_seg);
      IF v_len >= v_n THEN
        FOR v_i IN 1 .. v_len - v_n + 1 LOOP
          EXIT WHEN cardinality(v_terms) >= v_max;
          v_gram := substring(v_seg FROM v_i FOR v_n);
          IF NOT (v_gram = ANY(v_terms)) THEN
            v_terms := v_terms || v_gram;
          END IF;
        END LOOP;
      END IF;
    END IF;
  END LOOP;
  RETURN (SELECT coalesce(jsonb_agg(t ORDER BY ord), '[]'::jsonb)
            FROM unnest(v_terms) WITH ORDINALITY AS u(t, ord));
END $$;

-- === OR 形 tinql:引号短语以 ' OR ' 连接;空项集返回空串 ===
CREATE FUNCTION v13_mgraph_anchor_tinql(p_body text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(string_agg('"' || t || '"', ' OR '), '')
    FROM jsonb_array_elements_text(v13_mgraph_anchor_terms(p_body)) AS t
$$;

-- === 本地文法守卫:引号段 OR 闭集;段 ≤256B(UTF-8 字节)/词项 ≤
--     anchor_max_terms;AND 形/裸词/内嵌引号/通配/正则/fuzzy/发射域外
--     字符 → V3005 fail-closed(不降级为裸表扫描);返回规范化项集
--     (candidates 的 entity/关键词子项复用)。字符白名单=v13_query_
--     segments 发射域(latin [A-Za-z0-9] ∪ CJK 五区间,同一权威码点
--     表内联——route 同款先例;空白/操作符一律拒) ===
CREATE FUNCTION v13_mgraph_anchor_guard(p_tinql text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_pol jsonb; v_max int;
  v_parts text[]; v_n int; v_i int; v_j int;
  v_inner text; v_ch text; v_cp int;
  v_terms text[] := '{}';
BEGIN
  IF p_tinql IS NULL THEN
    RAISE EXCEPTION 'v13: mgraph anchor tinql must not be NULL'
      USING ERRCODE = 'V3005';
  END IF;
  IF p_tinql = '' THEN RETURN '[]'::jsonb; END IF;
  v_pol := v13_mgraph_policy();
  v_max := (v_pol->>'anchor_max_terms')::int;
  v_parts := string_to_array(p_tinql, ' OR ');
  v_n := array_length(v_parts, 1);
  IF v_n > v_max THEN
    RAISE EXCEPTION 'v13: mgraph anchor tinql exceeds max terms (%)', v_max
      USING ERRCODE = 'V3005';
  END IF;
  FOR v_i IN 1 .. v_n LOOP
    v_inner := v_parts[v_i];
    IF length(v_inner) < 2
       OR left(v_inner, 1) <> '"'
       OR right(v_inner, 1) <> '"'
       OR position('"' in substring(v_inner FROM 2 FOR length(v_inner) - 2)) > 0
    THEN
      RAISE EXCEPTION
        'v13: mgraph anchor tinql not in emitted grammar (quoted phrases joined by OR)'
        USING ERRCODE = 'V3005';
    END IF;
    v_inner := substring(v_inner FROM 2 FOR length(v_inner) - 2);
    IF octet_length(v_inner) = 0 OR octet_length(v_inner) > 256 THEN
      RAISE EXCEPTION 'v13: mgraph anchor tinql segment out of bounds'
        USING ERRCODE = 'V3005';
    END IF;
    FOR v_j IN 1 .. char_length(v_inner) LOOP
      v_ch := substring(v_inner FROM v_j FOR 1);
      v_cp := ascii(v_ch);
      IF v_ch !~ '[A-Za-z0-9]'
         AND NOT (v_cp BETWEEN 12352 AND 12543)
         AND NOT (v_cp BETWEEN 13312 AND 19903)
         AND NOT (v_cp BETWEEN 19968 AND 40959)
         AND NOT (v_cp BETWEEN 44032 AND 55215)
         AND NOT (v_cp BETWEEN 63744 AND 64255)
      THEN
        RAISE EXCEPTION
          'v13: mgraph anchor tinql segment outside emitted character domain'
          USING ERRCODE = 'V3005';
      END IF;
    END LOOP;
    IF NOT (v_inner = ANY(v_terms)) THEN
      v_terms := v_terms || v_inner;
    END IF;
  END LOOP;
  RETURN (SELECT coalesce(jsonb_agg(t ORDER BY ord), '[]'::jsonb)
            FROM unnest(v_terms) WITH ORDINALITY AS u(t, ord));
END $$;

-- === §4 ACL(V1 面;列举式 REVOKE,零 DEFINER):三函数被 candidates/
--     build/anchors/transition_score 以 invoker 权限调起,授权面照
--     candidates 镜像(resolve=写驱动、recall=读锚复用、route=读环) ===
REVOKE EXECUTE ON FUNCTION
  v13_mgraph_anchor_terms(text), v13_mgraph_anchor_tinql(text),
  v13_mgraph_anchor_guard(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_anchor_terms(text), v13_mgraph_anchor_tinql(text),
  v13_mgraph_anchor_guard(text)
TO v13_resolve, v13_recall, v13_route;

-- === 图索引校验器(v13_verify_memory 同族接口;仅 ix_memory_nodes_stannum;
--     手动可调+gate;不挂 cron;ShareLock 同步执行,取消或回滚即释放;
--     不授 recall/resolve/route) ===
CREATE FUNCTION v13_verify_mgraph(p_raise boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
  v_mn_bad bigint;
  v_checks jsonb;
  v_all_ok boolean;
BEGIN
  SELECT count(*) INTO v_mn_bad
    FROM stannum.verify_index('ix_memory_nodes_stannum'::regclass, true)
   WHERE severity IN ('error','warning');
  v_checks := jsonb_build_array(
    jsonb_build_object('name','memory_nodes_verify_index','ok', v_mn_bad = 0,
      'detail', jsonb_build_object('findings', v_mn_bad)));
  v_all_ok := NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_checks) c
                           WHERE NOT (c->>'ok')::boolean);
  IF p_raise AND NOT v_all_ok THEN
    RAISE EXCEPTION 'v13: verify_mgraph failed: %', v_checks
      USING ERRCODE = 'V3009';
  END IF;
  RETURN jsonb_build_object('version', 1, 'checks', v_checks,
                            'all_ok', v_all_ok);
END $$;

REVOKE EXECUTE ON FUNCTION v13_verify_mgraph(boolean) FROM PUBLIC;

COMMIT;
