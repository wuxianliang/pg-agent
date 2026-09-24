-- v13_mgraph_assembly.sql — Stage 16(B2 装配接线,W1:身份与校验升版)
--
-- 计划:docs/plans/v13-mgraph-assembly-wiring-plan-2026-09-24.md
-- 裁决:Stage 16 尾追加(§1.2);OQ-A=A4/AF1、OQ-B=B-T1+B-E2、OQ-C=C2 窄、
--       OQ-D=D1 七键、OQ-E=E4、OQ-F=F1(§1.5)。
--
-- 本文件两个 OR REPLACE 闭集之外的事实:
--   * v13/mgraph/v13_mgraph.sql 的 OR REPLACE 闭集维持
--     {v13_mgraph_envelope, v13_requeue_stale}(F7 原文不改,mgraph 两文件字节不动);
--   * 本文件的换体名闭集恰为 {v13_context_required, v13_prefix_identity,
--     v13_assemble_manifest, v13_manifest_validate, v13_refresh_context}
--     (即:重定义声明仅此五名,W2 就地编辑,W2 后仍仅此五名);
--   * 本文件零表结构变更;禁止撤销并重建这五个函数
--     (签名不变,原位重定义保留 ACL);
--   * 复制源 = periphery(14 号)文件正文加载态;periphery 源文件里的
--     manifest_version 3 / 十一键是 ≤14 号库墓碑,不在 periphery 文件里改。
--
-- W1 增量:version 字面量 3->4、mgraph_ver 第十二键、validate 词表与十二键、
-- refresh 锁名单+advisory、GRANT。
-- W2 增量(已就地编辑,仍只有一份同名定义):turn_query/provenance/
-- section_plan(+status/material 包装)五个新函数;assemble sec_src 第六支、
-- bkind memory 臂(cls+fcls 平行)、final_sec memory_inject、sections 过滤;
-- validate memory_graph 交叉检查;refresh memory belt(正向复核)与
-- degraded 审计;新函数 ACL。
--
-- 运维第一条:16 文件库里 pg_get_functiondef 才是装配活体;再改 periphery
-- 只影响 ≤14 号库。

BEGIN;


-- ===== [B2] §3.1 新函数:token 第十二键单源(OQ-C=C2 窄 digest) =====
--   mgraph_ver = sha256({generation, policy_version}) 的 64hex;材料钉死两键,
--   无 meta 行时 generation=0(v13_mgraph_progress 既有语义);无活动 mgraph
--   策略行 V3009。不读 now()、不读 walk、不聚合 body(DP7 不变量 7 确定性;
--   禁止把 frontier 哈希放进 token——C2' 自激论证,§1.4)。
CREATE FUNCTION v13_mgraph_asm_ver(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_gen bigint; v_ver int;
BEGIN
  v_gen := (v13_mgraph_progress(p_sid)->>'generation')::bigint;
  SELECT version INTO v_ver FROM v13_policies
   WHERE name = 'mgraph' AND active;
  IF v_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active mgraph policy row (seed lost?)'
      USING ERRCODE = 'V3009';
  END IF;
  RETURN encode(digest(jsonb_build_object(
    'generation', v_gen, 'policy_version', v_ver)::text, 'sha256'), 'hex');
END $$;

-- ===== [B2] §3.1 新函数(W2):查询串 / provenance / 段计划单一分支表 =====
--   全部 STABLE、非 SECURITY DEFINER、零 typesafe_ask(§1.3 #11);不调
--   run_round、不写表(材料函数零副作用)。

-- 最新 user/message 的 btrim 文本;无行返回 ''(不 RAISE)。走 events
-- (ix_events_last_user),不读 canonical——历史压缩窗口裁掉问题本身后
-- walk 仍有锚(§2)。walk/材料只许经此函数取查询串(W3 工人契约)。
CREATE FUNCTION v13_mgraph_turn_query(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce(
    (SELECT btrim(coalesce(e.payload->>'text', ''))
       FROM events e
      WHERE e.session_id = p_sid AND e.type = 'user/message'
      ORDER BY e.seq DESC LIMIT 1), '')
$$;

-- provenance 闭集七键(§1.4 OQ-D=D1 读时两跳):content_hash ->
-- transcript_chunks(session_id,seq_from) -> events.type。同文折叠口径:
-- 双方同文=mixed+conflict(不挑赢家,不称 hash collision);意外 type=
-- unknown+conflict(不 RAISE);consolidation 不展开亲本说话人;无界 seq
-- 数组不进 material(blob 会被 render 整段送进 wire——七键替全量 seqs)。
CREATE FUNCTION v13_mgraph_provenance(p_sid uuid, p_hash text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE n memory_nodes%ROWTYPE;
        v_types text[]; v_seqs bigint[];
        v_speaker text; v_conflict boolean;
BEGIN
  IF p_hash IS NULL OR p_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: mgraph provenance hash must be 64 hex'
      USING ERRCODE = 'V3009';
  END IF;
  SELECT * INTO n FROM memory_nodes
   WHERE session_id = p_sid AND content_hash = p_hash;
  IF NOT FOUND THEN
    RETURN jsonb_build_object(
      'origin', NULL, 'speaker', 'unknown', 'conflict', false,
      'seq_count', 0, 'seq_first', NULL, 'seq_last', NULL,
      'source_hashes', '[]'::jsonb);
  END IF;
  IF n.origin = 'consolidation' THEN
    RETURN jsonb_build_object(
      'origin', 'consolidation', 'speaker', 'consolidation',
      'conflict', false, 'seq_count', 0, 'seq_first', NULL,
      'seq_last', NULL,
      'source_hashes', (SELECT jsonb_agg(h ORDER BY h)
                          FROM (SELECT DISTINCT unnest(n.source_hashes) h) s));
  END IF;
  SELECT coalesce(array_agg(e.type ORDER BY e.seq), ARRAY[]::text[]),
         coalesce(array_agg(c.seq_from ORDER BY c.seq_from), ARRAY[]::bigint[])
    INTO v_types, v_seqs
    FROM transcript_chunks c
    JOIN events e
      ON e.session_id = c.session_id AND e.seq = c.seq_from
   WHERE c.session_id = p_sid AND c.content_hash = p_hash;
  IF cardinality(v_types) = 0 THEN
    v_speaker := 'unknown'; v_conflict := false;      -- episodic 却无投影行
  ELSIF EXISTS (SELECT 1 FROM unnest(v_types) t
                 WHERE t NOT IN ('user/message','llm/message')) THEN
    v_speaker := 'unknown'; v_conflict := true;       -- 意外事件型,不 RAISE
  ELSIF 'user/message' = ANY(v_types) AND 'llm/message' = ANY(v_types) THEN
    v_speaker := 'mixed'; v_conflict := true;         -- 同文折叠,不可分辨
  ELSIF 'user/message' = ANY(v_types) THEN
    v_speaker := 'user'; v_conflict := false;
  ELSE
    v_speaker := 'llm'; v_conflict := false;
  END IF;
  RETURN jsonb_build_object(
    'origin', n.origin, 'speaker', v_speaker, 'conflict', v_conflict,
    'seq_count', cardinality(v_seqs),
    'seq_first', CASE WHEN cardinality(v_seqs) = 0 THEN NULL
                      ELSE to_jsonb(v_seqs[1]) END,
    'seq_last', CASE WHEN cardinality(v_seqs) = 0 THEN NULL
                     ELSE to_jsonb(v_seqs[cardinality(v_seqs)]) END,
    'source_hashes', (SELECT jsonb_agg(h ORDER BY h)
                        FROM (SELECT DISTINCT unnest(n.source_hashes) h) s));
END $$;

-- 段计划单一分支表:{status, material};material 仅 status='emit' 时为
-- 对象,否则 JSON null。判定顺序锁死(§3.1):empty_query -> disabled ->
-- degraded(不读 walk)-> no_walk -> no_rows -> emit。status/material
-- 两包装函数只是它的包装,禁止两套条件写岔。
CREATE FUNCTION v13_mgraph_section_plan(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_q text; v_qh text; v_pol jsonb;
        v_gen bigint; v_pver int; v_rows jsonb; v_out jsonb;
BEGIN
  v_q := v13_mgraph_turn_query(p_sid);
  IF v_q = '' THEN
    RETURN jsonb_build_object('status', 'empty_query', 'material', NULL);
  END IF;
  v_pol := v13_mgraph_policy();
  IF NOT (v_pol->>'read_enabled')::boolean THEN
    RETURN jsonb_build_object('status', 'disabled', 'material', NULL);
  END IF;
  IF (v13_transcript_freshness(p_sid)->>'degraded')::boolean THEN
    RETURN jsonb_build_object('status', 'degraded', 'material', NULL);
  END IF;
  v_qh := v13_body_hash(v_q);
  v_gen := (v13_mgraph_progress(p_sid)->>'generation')::bigint;
  SELECT version INTO v_pver FROM v13_policies
   WHERE name = 'mgraph' AND active;
  IF v_pver IS NULL THEN
    RAISE EXCEPTION 'v13: no active mgraph policy row (seed lost?)'
      USING ERRCODE = 'V3009';
  END IF;
  PERFORM 1 FROM memory_walks w
   WHERE w.session_id = p_sid
     AND w.query_hash = v_qh
     AND w.mgraph_generation = v_gen
     AND w.policy_version = v_pver
     AND w.status = 'stopped';
  IF NOT FOUND THEN
    RETURN jsonb_build_object('status', 'no_walk', 'material', NULL);
  END IF;
  v_rows := v13_mgraph_evidence(p_sid, v_qh) -> 'rows';
  IF jsonb_array_length(coalesce(v_rows, '[]'::jsonb)) = 0 THEN
    RETURN jsonb_build_object('status', 'no_rows', 'material', NULL);
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
           'content_hash', r->>'content_hash',
           'score', r->'score',
           'body', r->>'body',
           'provenance', v13_mgraph_provenance(p_sid, r->>'content_hash'))
           ORDER BY (r->>'score')::numeric DESC, r->>'content_hash' ASC),
         '[]'::jsonb)
    INTO v_out
    FROM jsonb_array_elements(v_rows) r;
  RETURN jsonb_build_object(
    'status', 'emit',
    'material', jsonb_build_object(
      'query_hash', v_qh, 'generation', v_gen,
      'policy_version', v_pver, 'rows', v_out));
END $$;

CREATE FUNCTION v13_mgraph_section_status(p_sid uuid) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT (v13_mgraph_section_plan(p_sid) ->> 'status')
$$;

CREATE FUNCTION v13_mgraph_section_material(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN jsonb_typeof(p.plan->'material') = 'object'
              THEN p.plan->'material' ELSE NULL END
    FROM v13_mgraph_section_plan(p_sid) AS p(plan)
$$;


-- ===== [B2] 换体一:v13_context_required 十二键全谱(W1) =====
--   墓碑:十一键体唯一存活于 ≤15 号文件库;十二键全谱唯一存活于 ≥16 号库。
--   复制源=14 号 periphery 加载态(非 manifest 七键旧体);逐字复制+唯一
--   增量=[B2] mgraph_ver 第十二键(经 v13_mgraph_asm_ver 单源)。
CREATE OR REPLACE FUNCTION v13_context_required(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_asm_ver int; v_jdef_ver int; v_gen_ver int; v_corpus bigint;
        v_rk_ver int; v_tok jsonb;
BEGIN
  SELECT version INTO v_asm_ver FROM v13_policies
   WHERE name = 'assemble_manifest' AND active;
  IF v_asm_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active assemble_manifest policy (seed lost?)';
  END IF;
  SELECT version INTO v_jdef_ver FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  IF v_jdef_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active judgment_defaults policy (seed lost?)';
  END IF;
  -- [DP8] gen_ver 改经单源(latch 优先,OQ2 冻结语义)
  v_gen_ver := (v13_generation_effective(p_sid)->>'generation_version')::int;
  IF v_gen_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no effective generation identity (seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  SELECT generation INTO v_corpus FROM v13_chunks_meta WHERE singleton;
  IF v_corpus IS NULL THEN
    RAISE EXCEPTION 'v13: chunks meta row lost (seed dropped?)';
  END IF;
  SELECT version INTO v_rk_ver FROM v13_policies
   WHERE name = 'recall_k' AND active;
  IF v_rk_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active recall_k policy (seed lost?)';
  END IF;
  SELECT jsonb_build_object(
    'sem',      coalesce((SELECT max(seq) FROM events
                           WHERE session_id = p_sid
                             AND type IN ('user/message','llm/message',
                                          'tool/result')), -1),
    'dec',      (SELECT count(*) FROM decisions
                  WHERE session_id = p_sid AND answer IS NOT NULL),
    'goal',     v13_goal_hash(p_sid),
    'tools_rev',(SELECT revision FROM v13_tools_meta WHERE singleton),
    'asm_ver',  v_asm_ver,
    'jdef_ver', v_jdef_ver,
    'gen_ver',  v_gen_ver,
    'corpus',   v_corpus,
    'recall_ver', v_rk_ver,
    'econ_ver', v13_econ_ver(),                            -- [DP7]
    'ident_ver', v13_ident_ver(p_sid),                     -- [DP8] 第十一键(OQ1)
    'mgraph_ver', v13_mgraph_asm_ver(p_sid))               -- [B2] 第十二键(OQ-C=C2 窄 digest)
  INTO v_tok;
  RETURN v_tok;
END $$;

-- ===== [B2] 换体二:v13_prefix_identity(manifest_version 字面量 3->4;W1) =====
--   九键名不变;缺 render_policy 仍 V3008;DP8 的 generation_effective 材料写法
--   逐字保留。身份升版后果(子会话 fork/v3-v4 身份不一致拒绝)见计划 §6。
CREATE OR REPLACE FUNCTION v13_prefix_identity(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_mat jsonb; v_gen jsonb; v_trev int; v_rver int;
BEGIN
  v_gen := v13_generation_effective(p_sid);
  IF v_gen IS NULL OR v_gen->>'provider' IS NULL
     OR v_gen->>'model' IS NULL
     OR v_gen->>'system_blocks_digest' IS NULL THEN
    RAISE EXCEPTION 'v13: no effective generation identity (seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  SELECT revision INTO v_trev FROM v13_tools_meta WHERE singleton;
  IF v_trev IS NULL THEN
    RAISE EXCEPTION 'v13: v13_tools_meta singleton row missing'
      USING ERRCODE = 'V3008';                           -- DP3 P1-9 同姿势
  END IF;
  SELECT version INTO v_rver FROM v13_policies
   WHERE name = 'render_policy' AND active;
  IF v_rver IS NULL THEN
    RAISE EXCEPTION 'v13: no active render_policy (seed lost?)'
      USING ERRCODE = 'V3008';
  END IF;
  SELECT jsonb_build_object(
    'provider',  v_gen->>'provider',
    'model',     v_gen->>'model',
    'system_blocks_digest', v_gen->>'system_blocks_digest',
    'tools_rev', v_trev,
    'tools_digest', encode(digest(
      coalesce((v13_canonical_state(p_sid) -> 'tools')::text, ''),
      'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'latch_digest', v13_latch_digest(p_sid),
    'render_policy_version', v_rver,
    'manifest_version', 4)
  INTO v_mat;
  RETURN encode(digest(v_mat::text, 'sha256'), 'hex');
END $$;

-- ===== [B2] 换体三:v13_assemble_manifest v5(manifest v4;W1) =====
--   墓碑:v4(manifest_version=3)唯一存活于 ≤14 号库;本函数是 v5。
--   W1 逐字复制 periphery 活体(46 CTE)+ 唯一增量:fin 内 manifest_version
--   字面量 3->4(§3.3 增量清单闭集;sec_src 第六支/bkind memory 臂/
--   memory_inject transform/sections 过滤属 W2,届时就地编辑本复制体)。
--   tok 继续调用 v13_context_required,十二键自动进入 required_revision。
CREATE OR REPLACE FUNCTION v13_assemble_manifest(p_sid uuid,
                                                  p_policy_version int DEFAULT NULL)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
WITH RECURSIVE pol AS MATERIALIZED (
  SELECT p.version,
         (p.value->>'budget_tokens')::int        AS budget,
         (p.value->>'est_bytes_per_token')::int  AS divisor,
         p.value->'priority_overrides'           AS prio_ovr,
         p.value->'kinds_disabled'               AS kinds_off,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'judgment_defaults' AND q.active) AS jdef_ver,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'context_tiers' AND q.active) AS tiers_ver,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'context_budget' AND q.active) AS budget_ver,
         (SELECT q.value->'bands' FROM v13_policies q
           WHERE q.name = 'context_tiers' AND q.active) AS bands,
         (SELECT (q.value->>'actions_enabled')::boolean FROM v13_policies q
           WHERE q.name = 'context_tiers' AND q.active) AS actions_on,
         (SELECT q.value->'hysteresis' FROM v13_policies q
           WHERE q.name = 'context_tiers' AND q.active) AS hyst,
         (SELECT (q.value->>'l_eff_tokens')::bigint FROM v13_policies q
           WHERE q.name = 'context_budget' AND q.active) AS l_eff,
         (SELECT q.value->'buckets' FROM v13_policies q
           WHERE q.name = 'context_budget' AND q.active) AS bucket_ratios,
         (SELECT (q.value->>'keep_tail_turns')::int FROM v13_policies q
           WHERE q.name = 'context_budget' AND q.active) AS keep_tail,
         (SELECT (q.value->>'hard_window_bp')::int FROM v13_policies q
           WHERE q.name = 'context_budget' AND q.active) AS hard_bp,
         (SELECT q.value->>'provider' FROM v13_policies q
           WHERE q.name = 'generation' AND q.active) AS gen_provider,
         (SELECT q.value->>'model' FROM v13_policies q
           WHERE q.name = 'generation' AND q.active) AS gen_model,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'summary_accept' AND q.active) AS summary_ver,
         (SELECT (q.value->>'packs_reserved')::int FROM v13_policies q
           WHERE q.name = 'summary_accept' AND q.active) AS packs
  FROM v13_policies p
  WHERE p.name = 'assemble_manifest'
    AND p.version = coalesce(p_policy_version,
        (SELECT q.version FROM v13_policies q
          WHERE q.name = 'assemble_manifest' AND q.active))
), tok AS MATERIALIZED (
  SELECT v13_context_required(p_sid) AS t
), ident AS MATERIALIZED (
  SELECT v13_prefix_identity(p_sid) AS pid
), cs AS MATERIALIZED (
  SELECT v13_canonical_state(p_sid) AS c
), sact AS MATERIALIZED (               -- [DP7-S] 动作词单源
  SELECT public.v13_history_action(p_sid) AS action
), keepc AS MATERIALIZED (              -- [DP7-S] keep 尾边界(apply/guard 同一边界计数)
  SELECT pol.keep_tail AS keep,
         CASE WHEN (SELECT count(*) FROM jsonb_array_elements(cs.c->'messages') e
                     WHERE e->>'type' = 'user/message') >= pol.keep_tail
              THEN (SELECT min((t.e->>'seq')::bigint)
                      FROM (SELECT e FROM jsonb_array_elements(cs.c->'messages') e
                             WHERE e->>'type' = 'user/message'
                             ORDER BY (e->>'seq')::bigint DESC
                             LIMIT pol.keep_tail) t(e))
         END AS tail_seq
  FROM pol, cs
), pfx AS MATERIALIZED (                -- [DP7-S] protected tail 外前缀(消息级哈希序)
  SELECT coalesce(jsonb_agg(
           to_jsonb(encode(digest(coalesce(m::text, ''), 'sha256'), 'hex'))
           ORDER BY (m->>'seq')::bigint), '[]'::jsonb) AS hashes
   FROM cs, keepc, jsonb_array_elements(cs.c->'messages') m
  WHERE keepc.tail_seq IS NOT NULL AND (m->>'seq')::bigint < keepc.tail_seq
), adopt AS MATERIALIZED (              -- [DP7-S] 最新 succeeded context_summary 行
                                    -- (恒一行;零行时 NULL 列——下游 CASE 安全)
  SELECT e.effect_id, e.request, e.result
   FROM (SELECT 1) z
   LEFT JOIN effects e
     ON e.effect_id = (SELECT e2.effect_id FROM effects e2
                        WHERE e2.session_id = p_sid
                          AND e2.kind = 'context_summary'
                          AND e2.status = 'succeeded'
                        ORDER BY e2.created_at DESC, e2.effect_id DESC LIMIT 1)
), pri AS MATERIALIZED (
  SELECT s.context_active_artifact AS aid, a.inline AS m
  FROM sessions s LEFT JOIN artifacts a ON a.artifact_id = s.context_active_artifact
  WHERE s.session_id = p_sid
), chain AS (                            -- artifact 链(hysteresis 派生面)
  SELECT a.inline AS m, 0 AS depth
    FROM artifacts a
   WHERE a.artifact_id = (SELECT context_active_artifact
                            FROM sessions WHERE session_id = p_sid)
  UNION ALL
  SELECT a2.inline AS m, c.depth + 1
    FROM chain c JOIN artifacts a2
      ON a2.artifact_id = (c.m->'replay'->>'prior_artifact_id')::uuid
   WHERE c.depth < 16
), pri_sec AS MATERIALIZED (
  SELECT ps->>'section_id' AS section_id, ps->>'content_hash' AS content_hash,
         (ps->>'churn')::int AS churn
  FROM pri, jsonb_array_elements(
         CASE WHEN jsonb_typeof(pri.m->'sections') = 'array'
              THEN pri.m->'sections' ELSE '[]'::jsonb END) ps
), rmsg AS MATERIALIZED (               -- [DP7-S] 保留材料(动作后 history 正文)
  SELECT public.v13_history_section_material(p_sid) AS m
), dropped AS (                         -- [DP7-S] 全量-保留差集(按 seq)
  SELECT f AS elem, (f->>'seq')::bigint AS seq, keepc.tail_seq
   FROM cs, keepc, sact, jsonb_array_elements(cs.c->'messages') f
  WHERE sact.action IN ('round_drop','final_trim')
    AND NOT EXISTS (SELECT 1 FROM rmsg, jsonb_array_elements(rmsg.m) r(e)
                     WHERE (r.e->>'seq')::bigint = (f->>'seq')::bigint)
), drops AS MATERIALIZED (              -- [DP7-S] 差集分段:前缀逐 round+尾整段(trim)
  SELECT CASE WHEN bool_and(coalesce(g.is_tail, false))
              THEN 'compaction_final_trim' ELSE 'compaction_round_drop' END AS reason,
         jsonb_agg(g.elem ORDER BY (g.elem->>'seq')::bigint) AS content,
         min((g.elem->>'seq')::bigint) AS first_seq
   FROM (SELECT d.elem, d.seq,
                coalesce(d.tail_seq IS NULL OR d.seq >= d.tail_seq, false) AS is_tail,
                (SELECT count(*) FROM cs, jsonb_array_elements(cs.c->'messages') u
                  WHERE (u->>'seq')::bigint <= d.seq
                    AND u->>'type' = 'user/message') AS round_no
           FROM dropped d) g
  GROUP BY g.is_tail, CASE WHEN g.is_tail THEN 0 ELSE g.round_no END
), sec_src AS MATERIALIZED (
  SELECT 'goal'::text AS section_id, 'goal'::text AS kind,
         'Session'::text AS cache_scope, 'First'::text AS def_prio,
         v13_goal_hash(p_sid) AS content_hash,
         octet_length(coalesce((SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                        ORDER BY g.seq DESC LIMIT 1), '')) AS bytes,
         coalesce((SELECT max(seq) FROM v13_goals
                    WHERE session_id = p_sid), -1) AS gseq,
         NULL::jsonb AS mat, NULL::text AS pre_reason
  UNION ALL
  SELECT 'history','history','Session','Normal',
         encode(digest(coalesce(hm.mat::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce(hm.mat::text, '')),
         NULL::bigint, hm.mat, NULL
  FROM (SELECT CASE WHEN sact.action = 'full'      -- [DP7-S] 单源材料;full 臂
                     THEN cs.c -> 'messages'       -- =economy 原表达式(字节身份)
                     ELSE public.v13_history_section_material(p_sid) END AS mat
          FROM cs, sact) hm
  UNION ALL
  SELECT 'tools','tools','Global','First',
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'), 'hex'),
         octet_length(coalesce((cs.c -> 'tools')::text, '')),
         NULL::bigint, cs.c -> 'tools', NULL
  FROM cs
  UNION ALL
  SELECT 'summary','summary','Session','Normal',  -- [DP7-S]
         encode(digest(coalesce(sm.mat::text, ''), 'sha256'), 'hex'),
         octet_length(coalesce(sm.mat::text, '')),
         NULL::bigint, sm.mat, NULL
  FROM (SELECT public.v13_summary_section_material(p_sid) AS mat) sm
  WHERE sm.mat IS NOT NULL
  UNION ALL
  SELECT CASE WHEN dc.n > 1                            -- [DP7-S] 多段化规则
              THEN 'compaction:' || left(encode(digest(
                     coalesce(ds.content::text, ''), 'sha256'), 'hex'), 8)
              ELSE 'compaction' END,
         'compaction','None','Normal',
         encode(digest(coalesce(ds.content::text, ''), 'sha256'), 'hex'),
         octet_length(coalesce(ds.content::text, '')),
         NULL::bigint, ds.content, ds.reason
  FROM drops ds, (SELECT count(*) AS n FROM drops) dc, sact
  WHERE sact.action IN ('round_drop','final_trim')
  UNION ALL
  SELECT 'memory_graph','memory_graph','Session','LastResort',  -- [B2] §3.2
         encode(digest(coalesce(smm.mat::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce(smm.mat::text, '')),
         NULL::bigint, smm.mat, NULL
  FROM (SELECT v13_mgraph_section_material(p_sid) AS mat) smm
  WHERE smm.mat IS NOT NULL
), sec_full AS MATERIALIZED (           -- [DP7-S] v2 sec_src 原文(全量材料;决策基面)
  SELECT 'goal'::text AS section_id, 'goal'::text AS kind,
         'Session'::text AS cache_scope, 'First'::text AS def_prio,
         v13_goal_hash(p_sid) AS content_hash,
         octet_length(coalesce((SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                        ORDER BY g.seq DESC LIMIT 1), '')) AS bytes,
         coalesce((SELECT max(seq) FROM v13_goals
                    WHERE session_id = p_sid), -1) AS gseq,
         NULL::jsonb AS mat, NULL::text AS pre_reason
  UNION ALL
  SELECT 'history','history','Session','Normal',
         encode(digest(coalesce((cs.c -> 'messages')::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce((cs.c -> 'messages')::text, '')),
         NULL::bigint, cs.c -> 'messages', NULL
  FROM cs
  UNION ALL
  SELECT 'tools','tools','Global','First',
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'), 'hex'),
         octet_length(coalesce((cs.c -> 'tools')::text, '')),
         NULL::bigint, cs.c -> 'tools', NULL
  FROM cs
), cls AS MATERIALIZED (
  SELECT r.*,
         CASE r.kind WHEN 'goal' THEN 'core' WHEN 'tools' THEN 'core'
                     WHEN 'history' THEN 'history'
                     WHEN 'memory_graph' THEN 'retrieval'   -- [B2]
                     ELSE 'retrieval' END AS bkind,
         CASE WHEN (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS TRUE
              THEN pol.prio_ovr ->> r.kind
              ELSE r.def_prio END AS eff_priority,
         ((r.bytes + pol.divisor - 1) / pol.divisor)::int AS est_tokens,
         CASE coalesce(pol.prio_ovr ->> r.kind, r.def_prio)
           WHEN 'First'      THEN 1
           WHEN 'Normal'     THEN 2
           WHEN 'Never'      THEN 3
           WHEN 'LastResort' THEN 4
         END AS prank,
         CASE WHEN r.kind = 'compaction' THEN r.pre_reason    -- [DP7-S] 回退
              WHEN (pol.prio_ovr -> r.kind) IS NOT NULL      -- 段=恒 skipped
               AND (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS NOT TRUE
              THEN 'invalid_override'
              WHEN coalesce(pol.prio_ovr ->> r.kind, r.def_prio) = 'Never'
              THEN 'priority_never'
              WHEN pol.kinds_off @> to_jsonb(r.kind)
              THEN 'disabled'
              ELSE NULL END AS pre_skip,
         CASE WHEN r.section_id = 'goal'
              THEN jsonb_build_object('kind','goal','seq', r.gseq)
              ELSE jsonb_build_object('kind','blob','content_hash',
                encode(digest(coalesce(r.mat::text, ''), 'sha256'), 'hex'))
         END AS payload_ref
  FROM sec_src r, pol
), fcls AS MATERIALIZED (               -- [DP7-S] v2 cls 原文(全量基面)
  SELECT r.*,
         CASE r.kind WHEN 'goal' THEN 'core' WHEN 'tools' THEN 'core'
                     WHEN 'history' THEN 'history'
                     WHEN 'memory_graph' THEN 'retrieval'   -- [B2]
                     ELSE 'retrieval' END AS bkind,
         CASE WHEN (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS TRUE
              THEN pol.prio_ovr ->> r.kind
              ELSE r.def_prio END AS eff_priority,
         ((r.bytes + pol.divisor - 1) / pol.divisor)::int AS est_tokens,
         CASE coalesce(pol.prio_ovr ->> r.kind, r.def_prio)
           WHEN 'First'      THEN 1
           WHEN 'Normal'     THEN 2
           WHEN 'Never'      THEN 3
           WHEN 'LastResort' THEN 4
         END AS prank,
         CASE WHEN (pol.prio_ovr -> r.kind) IS NOT NULL
               AND (pol.prio_ovr ->> r.kind)
                   IN ('First','Normal','Never','LastResort') IS NOT TRUE
              THEN 'invalid_override'
              WHEN coalesce(pol.prio_ovr ->> r.kind, r.def_prio) = 'Never'
              THEN 'priority_never'
              WHEN pol.kinds_off @> to_jsonb(r.kind)
              THEN 'disabled'
              ELSE NULL END AS pre_skip,
         CASE WHEN r.section_id = 'goal'
              THEN jsonb_build_object('kind','goal','seq', r.gseq)
              ELSE jsonb_build_object('kind','blob','content_hash',
                encode(digest(coalesce(r.mat::text, ''), 'sha256'), 'hex'))
         END AS payload_ref
  FROM sec_full r, pol
), packed AS MATERIALIZED (
  SELECT c.section_id, c.bkind,
         sum(c.est_tokens) OVER (PARTITION BY c.bkind
                   ORDER BY c.prank, c.section_id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_incl
  FROM cls c
  WHERE c.pre_skip IS NULL
), ordered AS MATERIALIZED (
  SELECT c.*,
         (p.section_id IS NULL) AS prior_missing,
         coalesce(p.content_hash, '') AS prior_hash,
         coalesce(p.churn, 0)          AS prior_churn,
         k.run_incl
  FROM cls c
       LEFT JOIN packed k ON k.section_id = c.section_id
       LEFT JOIN pri_sec p ON p.section_id = c.section_id
), ford AS MATERIALIZED (               -- [DP7-S] 全量基面 ordered(er/hint 消费)
  SELECT c.*,
         (p.section_id IS NULL) AS prior_missing,
         coalesce(p.content_hash, '') AS prior_hash,
         coalesce(p.churn, 0)          AS prior_churn
  FROM fcls c
       LEFT JOIN pri_sec p ON p.section_id = c.section_id
), econ0 AS MATERIALIZED (
  SELECT pol.divisor, pol.l_eff, pol.hard_bp, pol.bands, pol.hyst,
         pol.actions_on, pol.gen_provider, pol.gen_model,
         v13_ro_reserve(p_sid) AS ro,
         v13_pricing_r(pol.gen_provider, pol.gen_model) AS r,
         (SELECT pr.catalog_version FROM v13_pricing pr
           WHERE pr.provider = pol.gen_provider
             AND pr.model = pol.gen_model
             AND pr.account = 'default' AND pr.cache_class = 'default'
             AND pr.active LIMIT 1) AS catalog_version,
         greatest(least(pol.budget,
                        pol.l_eff - v13_ro_reserve(p_sid)), 0)::bigint
           AS effective_budget,
         (floor(greatest(least(pol.budget,
                        pol.l_eff - v13_ro_reserve(p_sid)), 0)
                * (pol.bucket_ratios->>'core')::numeric))::bigint AS core_cap,
         (floor(greatest(least(pol.budget,
                        pol.l_eff - v13_ro_reserve(p_sid)), 0)
                * (pol.bucket_ratios->>'history')::numeric))::bigint AS history_cap,
         (floor(greatest(least(pol.budget,
                        pol.l_eff - v13_ro_reserve(p_sid)), 0)
                * (pol.bucket_ratios->>'retrieval')::numeric))::bigint AS retrieval_cap
  FROM pol
), press AS MATERIALIZED (              -- [DP7-S] 压力=决策基面(全量候选;值恒=v2)
  SELECT (SELECT coalesce(sum(est_tokens), 0) FROM fcls
           WHERE pre_skip IS NULL) AS t_used,
         econ0.ro, econ0.l_eff,
         (((SELECT coalesce(sum(est_tokens), 0) FROM fcls
             WHERE pre_skip IS NULL) + econ0.ro) * 10000 / econ0.l_eff)::bigint AS bp,
         econ0.hard_bp
  FROM econ0
), dlt AS MATERIALIZED (
  SELECT coalesce(sum(((octet_length(e.payload::text) + pol.divisor - 1)
                       / pol.divisor)), 0)::bigint AS delta_est
    FROM pri, pol, events e
   WHERE pri.m IS NOT NULL
     AND e.session_id = p_sid
     AND e.type IN ('user/message','llm/message','tool/result')
     AND e.seq > (pri.m->'required_revision'->>'sem')::bigint
), pred AS MATERIALIZED (
  SELECT CASE
           WHEN pri.m IS NULL
                OR pri.m->'economics' IS NULL
                OR (pri.m->>'turn_no')::int IS DISTINCT FROM
                   (SELECT turn_no FROM sessions WHERE session_id = p_sid)
             THEN NULL
             ELSE ((((pri.m->'economics'->'pressure'->>'t_used')::bigint
                      + dlt.delta_est) + press.ro) * 10000 / press.l_eff)::bigint
         END AS bp
    FROM pri, dlt, press
), rec AS MATERIALIZED (
  SELECT v13_recovery_active(p_sid) AS active,
         (SELECT (b->>'lo_bp')::int
            FROM econ0, jsonb_array_elements(econ0.bands) b
           WHERE b->>'tier' = 'CompactHistory' LIMIT 1) AS floor_bp
  FROM econ0
), cand AS MATERIALIZED (
  SELECT greatest(press.bp,
                  coalesce(pred.bp, press.bp),
                  CASE WHEN rec.active THEN coalesce(rec.floor_bp, 0)
                       ELSE 0 END) AS bp
    FROM press, pred, rec
), inputs AS MATERIALIZED (
  SELECT press.bp AS raw_bp, pred.bp AS pred_bp,
         CASE WHEN rec.active THEN rec.floor_bp ELSE NULL END AS floor_bp,
         cand.bp AS cand_bp,
         v13_band_of(econ0.bands, press.bp) AS raw_tier,
         v13_tier_rank(v13_band_of(econ0.bands, cand.bp)) AS target_rank,
         (SELECT v13_tier_rank(pri.m->'economics'->'tier'->>'effective')
            FROM pri
           WHERE pri.m->'economics'->'tier'->>'effective'
                 IN ('Normal','TrimSchemas','CompactHistory',
                     'AggressivePrune')) AS held_rank
  FROM press, pred, rec, cand, econ0
), lowturns AS MATERIALIZED (
  SELECT turn, bp FROM (
    SELECT DISTINCT ON ((c.m->>'turn_no')::int)
           (c.m->>'turn_no')::int AS turn,
           (c.m->'economics'->'pressure'->>'bp')::bigint AS bp
      FROM chain c
     WHERE (c.m->>'turn_no')::int <
           (SELECT turn_no FROM sessions WHERE session_id = p_sid)
       AND c.m->'economics' IS NOT NULL
     ORDER BY (c.m->>'turn_no')::int, c.depth
  ) x ORDER BY turn DESC
), loheld AS MATERIALIZED (
  SELECT (SELECT (b->>'lo_bp')::int
            FROM econ0, jsonb_array_elements(econ0.bands) b
           WHERE b->>'tier' = (SELECT pri.m->'economics'->'tier'->>'effective'
                                 FROM pri
                                WHERE pri.m->'economics'->'tier'->>'effective'
                                      IN ('Normal','TrimSchemas',
                                          'CompactHistory','AggressivePrune'))
           LIMIT 1) AS lo_bp
  FROM econ0
), lowrun AS MATERIALIZED (
  SELECT EXISTS (
    SELECT 1
    WHERE loheld.lo_bp IS NOT NULL
      AND (SELECT count(*) FROM (
             SELECT lt.bp FROM lowturns lt
              ORDER BY lt.turn DESC
              LIMIT coalesce((pol.hyst->>'cooldown_turns')::int, 0)) w)
            = coalesce((pol.hyst->>'cooldown_turns')::int, 0)
      AND coalesce((SELECT bool_and(w.bp < loheld.lo_bp)
                      FROM (SELECT lt.bp FROM lowturns lt
                             ORDER BY lt.turn DESC
                             LIMIT coalesce((pol.hyst->>'cooldown_turns')::int, 0)) w),
                   false)
  ) AS ok
  FROM pol, loheld
), effcalc AS MATERIALIZED (
  SELECT CASE
           WHEN inputs.held_rank IS NULL
                OR inputs.target_rank >= inputs.held_rank
             THEN inputs.target_rank
           WHEN lowrun.ok
             THEN greatest(inputs.target_rank,
                           inputs.held_rank
                           - coalesce((pol.hyst->>'max_downgrade_steps')::int, 1))
           ELSE inputs.held_rank
         END AS eff_rank,
         CASE
           WHEN inputs.held_rank IS NOT NULL
                AND inputs.target_rank < inputs.held_rank
                AND NOT lowrun.ok
             THEN 'prior_held'
           WHEN inputs.floor_bp IS NOT NULL
                AND inputs.floor_bp >= greatest(inputs.raw_bp,
                                                coalesce(inputs.pred_bp,
                                                         inputs.raw_bp))
             THEN 'recovery_floor'
           WHEN inputs.pred_bp IS NOT NULL
                AND inputs.pred_bp > inputs.raw_bp
             THEN 'predicted'
           ELSE 'raw'
         END AS basis
  FROM inputs, lowrun, pol
), sp AS MATERIALIZED (
  SELECT octet_length(coalesce((cs.c -> 'messages')::text, '')) AS hist_bytes,
         coalesce((SELECT sum(greatest(octet_length((m->'payload')::text) - 64, 0))
                     FROM jsonb_array_elements(cs.c->'messages') m
                    WHERE m->>'type' = 'tool/result'), 0) AS spill_saved
  FROM cs
), erc2 AS MATERIALIZED (
  SELECT (SELECT floor(coalesce(sum(
              CASE WHEN NOT o.prior_missing
                AND o.content_hash IS NOT DISTINCT FROM o.prior_hash
                   THEN o.est_tokens ELSE 0 END), 0) * econ0.r
           + coalesce(sum(
              CASE WHEN o.prior_missing
                     OR o.content_hash IS DISTINCT FROM o.prior_hash
                   THEN o.est_tokens ELSE 0 END), 0))
            FROM ford o) AS e_base,
         (SELECT floor(coalesce(sum(
              CASE WHEN o.kind IS DISTINCT FROM 'history'
                AND NOT o.prior_missing
                AND o.content_hash IS NOT DISTINCT FROM o.prior_hash
                   THEN o.est_tokens ELSE 0 END), 0) * econ0.r
           + coalesce(sum(
              CASE WHEN o.kind IS DISTINCT FROM 'history'
                AND (o.prior_missing
                     OR o.content_hash IS DISTINCT FROM o.prior_hash)
                   THEN o.est_tokens ELSE 0 END), 0))
            FROM ford o) AS e_nonhist,
         sp.hist_bytes, sp.spill_saved, econ0.divisor
  FROM econ0, sp
), erc AS MATERIALIZED (
  SELECT econ0.r, econ0.catalog_version,
         econ0.gen_provider, econ0.gen_model,
         erc2.e_base,
         floor(erc2.e_nonhist
               + ((greatest(erc2.hist_bytes - erc2.spill_saved, 0)
                   + erc2.divisor - 1) / erc2.divisor)) AS e_comp,
         CASE WHEN econ0.r IS NULL THEN 'r_unknown'
              WHEN press.bp >= econ0.hard_bp THEN 'hard_window'
              WHEN NOT econ0.actions_on THEN 'actions_off'
              WHEN econ0.r < 0.145
                THEN 'loss'
              WHEN floor(erc2.e_nonhist
                        + ((greatest(erc2.hist_bytes - erc2.spill_saved, 0)
                            + erc2.divisor - 1) / erc2.divisor))
                   < erc2.e_base
                THEN 'adopt'
              ELSE 'loss' END AS branch,
         (press.bp >= econ0.hard_bp) AS hard_window
  FROM econ0, press, erc2
), hint AS MATERIALIZED (
  SELECT CASE WHEN effcalc.eff_rank >= 3
             THEN jsonb_build_object(
               'order', (SELECT coalesce(jsonb_agg(q.section_id
                              ORDER BY q.ch DESC, q.est DESC, q.section_id),
                             '[]'::jsonb)
                          FROM (SELECT o.section_id,
                                       CASE WHEN o.prior_missing THEN 0
                                            WHEN o.content_hash
                                                 IS DISTINCT FROM o.prior_hash
                                            THEN o.prior_churn + 1
                                            ELSE 0 END AS ch,
                                       o.est_tokens AS est
                                  FROM ford o
                                 WHERE o.kind = 'history'
                                   AND o.pre_skip IS NULL) q),
               'basis', 'churn:est:id')
           ELSE NULL END AS h
  FROM effcalc
), final_sec AS MATERIALIZED (
  SELECT jsonb_build_object(
    'section_id',  o.section_id,
    'kind',        o.kind,
    'cache_scope', o.cache_scope,
    'priority',    o.eff_priority,
    'content_hash',o.content_hash,
    'est_tokens',  o.est_tokens,
    'payload_ref', o.payload_ref,
    'churn',       CASE WHEN o.prior_missing THEN 0
                        WHEN o.content_hash IS DISTINCT FROM o.prior_hash
                        THEN o.prior_churn + 1 ELSE 0 END,
    'transform',   CASE
                     WHEN o.pre_skip IS NOT NULL THEN
                       jsonb_build_object('applied', false,
                                          'reason', o.pre_skip)
                     WHEN o.run_incl >
                          CASE o.bkind WHEN 'core' THEN econ0.core_cap
                                       WHEN 'history' THEN econ0.history_cap
                                       ELSE econ0.retrieval_cap END
                     THEN
                       jsonb_build_object('applied', false,
                                          'reason', 'budget')
                     ELSE
                       jsonb_build_object('applied', true, 'name',
                         CASE o.section_id WHEN 'goal'   THEN 'verbatim'
                                           WHEN 'summary' THEN 'summarize'
                                           WHEN 'memory_graph' THEN
                                             'memory_inject'      -- [B2]
                                           WHEN 'history' THEN
                                             CASE WHEN sact.action IN
                                                      ('spill','round_drop',
                                                       'final_trim')
                                                  THEN 'spill'
                                                  ELSE 'verbatim' END
                                           ELSE 'catalog_digest' END)
                   END
  ) AS section, o.prank, o.section_id
  FROM ordered o, econ0, sact
), goal_addr AS MATERIALIZED (
  SELECT coalesce((SELECT jsonb_build_object('kind','goal','seq',g.seq,
                              'content_hash',g.content_hash)
                     FROM v13_goals g WHERE g.session_id = p_sid
                 ORDER BY g.seq DESC LIMIT 1),
                  'null'::jsonb) AS a
), rc2 AS MATERIALIZED (
  SELECT v13_recall_candidates(p_sid)->'candidates' AS cands
), fc AS MATERIALIZED (
  SELECT v13_goal_hash(p_sid) AS gh,
         v13_candidates_digest(v13_recall_candidates(p_sid)
                               ->'candidates') AS dig
), qside AS MATERIALIZED (
  SELECT jsonb_build_object(
    'query_artifact_id', (SELECT a FROM goal_addr),
    'candidates', (SELECT coalesce(jsonb_agg(
                     c || jsonb_build_object('decision_id',
                       (SELECT d.decision_id FROM decisions d
                         WHERE d.session_id = p_sid
                           AND d.signal = 'chunk::' || (c->>'content_hash')
                           AND d.context =
                                 v13_filter_ref(fc.gh, c->>'content_hash')
                           AND d.answer IS NOT NULL
                            AND d.status IN ('answered','cached')
                           ORDER BY d.answered_at DESC, d.decision_id
                        LIMIT 1))
                       ORDER BY (c->>'bm25')::numeric DESC,
                                c->>'content_hash' ASC), '[]'::jsonb)
                     FROM jsonb_array_elements((SELECT cands FROM rc2)) c, fc)
  ) AS q
), cdec AS MATERIALIZED (               -- [DP7-S] 采纳 round 的 decision 行(恒一行)
  SELECT d.decision_id, d.epoch, d.request_hash, d.template_name,
         d.template_version, d.answer
   FROM (SELECT 1) z
   LEFT JOIN decisions d
     ON d.session_id = p_sid
    AND d.answer IS NOT NULL
    AND d.decision_id::text =
        (SELECT CASE WHEN jsonb_typeof(ad.result->'rounds') = 'array'
                      AND jsonb_array_length(ad.result->'rounds') > 0
                     THEN ad.result->'rounds'->(jsonb_array_length(ad.result->'rounds') - 1)
                          ->>'decision_id'
                     ELSE '' END
           FROM adopt ad)
), jud AS MATERIALIZED (
  SELECT coalesce(jsonb_agg("row" ORDER BY "row"->>'decision_id'),
             '[]'::jsonb) AS j
  FROM (SELECT jsonb_build_object(
             'decision_id',    d.decision_id,
             'epoch',          d.epoch,
             'request_hash',   d.request_hash,
             'template_name',  d.template_name,
             'template_version', d.template_version,
             'raw_verdict',    d.answer,
             'final_action',   CASE
               WHEN d.signal = 'corpus_exists'
                 THEN v13_existence_action(d.answer)
               ELSE (v13_chunk_filter_action(p_sid, fc.gh, fc.dig,
                        d.context->'chunk'->>'content_hash'))->>'action'
             END) AS "row"
          FROM decisions d, fc
         WHERE d.answer IS NOT NULL
           AND d.status IN ('answered','cached')
           AND ( d.decision_id::text IN (
                  SELECT cand->>'decision_id'
                    FROM qside,
                         jsonb_array_elements(qside.q->'candidates') cand
                   WHERE cand->>'decision_id' IS NOT NULL)
              OR ( d.signal = 'corpus_exists'
                   AND d.context = jsonb_build_object(
                         'query_content_hash', fc.gh,
                         'candidates_digest',  fc.dig)))
        UNION ALL
        SELECT jsonb_build_object(                    -- [DP7-S] L5:采纳 summary
             'decision_id',    cd.decision_id,        -- decision 进消费集
             'epoch',          cd.epoch,
             'request_hash',   cd.request_hash,
             'template_name',  cd.template_name,
             'template_version', cd.template_version,
             'raw_verdict',    cd.answer,
             'final_action',   'include') AS "row"
          FROM cdec cd, sact
         WHERE sact.action = 'tail') s
), rdseq AS MATERIALIZED (              -- [DP7-S] drop_rounds 步参数(锚 seq)
  SELECT coalesce(jsonb_agg(d.first_seq ORDER BY d.first_seq), '[]'::jsonb) AS seqarr
   FROM drops d
  WHERE d.reason = 'compaction_round_drop'
), sbasis AS MATERIALIZED (             -- [DP7-S] not-consumed basis(词表封闭;
                                         -- 未消费但有解释时在场——O2 的
                                         -- span_stale 在 action='full'(IF 臂)
                                         -- 下亦可观测)
  SELECT CASE
    WHEN NOT pol.actions_on THEN 'none'
    WHEN NOT (press.bp >= econ0.hard_bp
              OR (econ0.r IS NOT NULL AND effcalc.eff_rank >= 3)) THEN
      CASE WHEN adopt.effect_id IS NOT NULL
            AND coalesce((adopt.result->>'adopted')::boolean, false)
            AND adopt.request->>'span_digest' IS DISTINCT FROM
                v13_span_digest(pfx.hashes)
           THEN 'span_stale' ELSE 'none' END
    WHEN pol.summary_ver IS NULL THEN 'no_budget'
    WHEN (SELECT count(*) FROM judgment_calls WHERE session_id = p_sid)
         >= coalesce((SELECT (q.value->>'session_asks_cap')::int
                        FROM v13_policies q
                       WHERE q.name = 'judge_spend_gate' AND q.active),
                     2147483647)
      THEN 'no_budget'
    WHEN NOT EXISTS (SELECT 1 FROM effects e
                      WHERE e.session_id = p_sid
                        AND e.kind = 'context_summary')
      THEN 'no_effect'
    WHEN NOT EXISTS (SELECT 1 FROM effects e
                      WHERE e.session_id = p_sid
                        AND e.kind = 'context_summary'
                        AND e.status = 'succeeded')
      THEN 'checks_failed'
    WHEN adopt.effect_id IS NOT NULL
         AND coalesce((adopt.result->>'adopted')::boolean, false)
         AND adopt.request->>'span_digest' IS DISTINCT FROM
             v13_span_digest(pfx.hashes)
      THEN 'span_stale'
    WHEN adopt.effect_id IS NOT NULL
      THEN CASE WHEN adopt.result->>'basis' IN
                    ('rejected','cjk','checks_failed','no_effect',
                     'no_budget','span_stale')
                THEN adopt.result->>'basis' ELSE 'rejected' END
    ELSE 'none'
  END AS basis
  FROM pol, press, econ0, effcalc, pfx, adopt
), summary_calc AS MATERIALIZED (       -- [DP7-S] economics.summary 三件
  SELECT CASE WHEN pol.actions_on
              AND pol.summary_ver IS NOT NULL
              AND pol.packs IS NOT NULL
              AND (press.bp >= econ0.hard_bp
                   OR (econ0.r IS NOT NULL AND effcalc.eff_rank >= 3))
              AND pfx.hashes IS NOT NULL
              AND jsonb_array_length(pfx.hashes) > 0
         THEN jsonb_build_object(
                'target_span', pfx.hashes,
                'span_digest', v13_span_digest(pfx.hashes),
                'packs', pol.packs,
                'pack_ok', pol.summary_ver IS NOT NULL
                           AND (SELECT count(*) FROM judgment_calls
                                  WHERE session_id = p_sid)
                               < coalesce((SELECT (q.value->>'session_asks_cap')::int
                                             FROM v13_policies q
                                            WHERE q.name = 'judge_spend_gate'
                                              AND q.active), 2147483647))
         END AS intent,
         CASE WHEN sact.action = 'tail' AND adopt.effect_id IS NOT NULL
                   AND cdec.decision_id IS NOT NULL
         THEN jsonb_build_object(
                'effect_id', adopt.effect_id,
                'decision_id', cdec.decision_id,
                'span_digest', adopt.request->>'span_digest',
                'rounds', adopt.result->'rounds')
         END AS consumed,
         CASE WHEN sact.action = 'tail' THEN NULL
              WHEN sbasis.basis = 'none' AND sact.action = 'full' THEN NULL
              ELSE jsonb_build_object(
                'steps', CASE sact.action
                   WHEN 'full' THEN '[]'::jsonb
                   WHEN 'spill' THEN jsonb_build_array(
                          jsonb_build_object('op', 'spill'))
                   WHEN 'round_drop' THEN jsonb_build_array(
                          jsonb_build_object('op', 'spill'),
                          jsonb_build_object('op', 'drop_rounds',
                                             'rounds', rdseq.seqarr))
                   ELSE jsonb_build_array(
                          jsonb_build_object('op', 'spill'),
                          jsonb_build_object('op', 'drop_rounds',
                                             'rounds', rdseq.seqarr),
                          jsonb_build_object('op', 'final_trim')) END,
                'basis', sbasis.basis)
         END AS fallback
  FROM pol, press, econ0, effcalc, pfx, sact, adopt, cdec, sbasis, rdseq
), mode AS MATERIALIZED (
  SELECT CASE
           WHEN pri.m IS NULL THEN 'fresh'
           WHEN (pri.m->>'prefix_identity')
                IS DISTINCT FROM (SELECT pid FROM ident) THEN 'fresh'
           ELSE 'recompute'
         END AS m
  FROM pri
)
, fin AS (
SELECT jsonb_build_object(
  'manifest_version', 4,
  'session_id', p_sid,
  'turn_no',   (SELECT turn_no FROM sessions WHERE session_id = p_sid),
  'prefix_identity', (SELECT pid FROM ident),
  'policy',    jsonb_build_object(
                 'assemble_version',   (SELECT version FROM pol),
                 'budget_tokens',      (SELECT budget FROM pol),
                 'est_bytes_per_token',(SELECT divisor FROM pol),
                 'judgment_defaults_version', (SELECT jdef_ver FROM pol),
                 'tiers_version',      (SELECT tiers_ver FROM pol),
                 'budget_version',     (SELECT budget_ver FROM pol),
                 'pricing_version',    coalesce((SELECT catalog_version::text
                                                  FROM econ0), 'none')),
  'required_revision', (SELECT t FROM tok),
  'economics', jsonb_build_object(
                 'pressure', jsonb_build_object(
                   't_used', (SELECT t_used FROM press),
                   'r_o',    (SELECT ro FROM press),
                   'l_eff',  (SELECT l_eff FROM press),
                   'bp',     (SELECT bp FROM press)),
                 'tier', jsonb_build_object(
                   'raw',       (SELECT raw_tier FROM inputs),
                   'effective', CASE (SELECT eff_rank FROM effcalc)
                     WHEN 1 THEN 'Normal' WHEN 2 THEN 'TrimSchemas'
                     WHEN 3 THEN 'CompactHistory' WHEN 4 THEN 'AggressivePrune' END,
                   'basis',     (SELECT basis FROM effcalc)),
                 'er', jsonb_build_object(
                   'branch',   (SELECT branch FROM erc),
                   'r',        (SELECT r FROM erc),
                   'r_source', jsonb_build_object(
                     'provider',       (SELECT gen_provider FROM erc),
                     'model',          (SELECT gen_model FROM erc),
                     'account',        'default',
                     'cache_class',    'default',
                     'catalog_version', (SELECT catalog_version FROM erc)),
                   'e_base', (SELECT e_base FROM erc),
                   'e_comp', (SELECT e_comp FROM erc),
                   'hard_window', (SELECT hard_window FROM erc)),
                 'buckets', jsonb_build_object(
                   'core_cap',        (SELECT core_cap FROM econ0),
                   'history_cap',     (SELECT history_cap FROM econ0),
                   'retrieval_cap',   (SELECT retrieval_cap FROM econ0),
                   'effective_budget',(SELECT effective_budget FROM econ0)),
                 'compact_hint', (SELECT h FROM hint),
                 'summary', (SELECT jsonb_build_object(
                                 'intent',   sm.intent,
                                 'consumed', sm.consumed,
                                 'fallback', sm.fallback)
                               FROM summary_calc sm)),
  'sections',  (SELECT coalesce(jsonb_agg(section ORDER BY prank, section_id),
                             '[]'::jsonb)
                  FROM final_sec
                 WHERE NOT (section->>'section_id' = 'memory_graph'  -- [B2]
                            AND (section->'transform'->>'applied')::boolean
                                IS DISTINCT FROM true)),
  'query_side',(SELECT q FROM qside),
  'judgments', (SELECT j FROM jud),
  'replay',    jsonb_build_object('mode', (SELECT m FROM mode),
                                  'prior_artifact_id', (SELECT aid FROM pri))
) AS manifest)
SELECT fin.manifest || jsonb_build_object(
  'render', v13_render_receipt(p_sid, fin.manifest))
FROM fin;
$$;

-- ===== [B2] 换体四:v13_manifest_validate v5(W1) =====
--   墓碑:v4 断言 version 3,唯一存活于 ≤14 号库。
--   W1 增量(§3.4 闭集):version 断言 4;required_revision 十二键串+
--   mgraph_ver 64hex;kind 词表 +'memory_graph';applied transform 名
--   +'memory_inject'(仍是原 V3003 RAISE)。外层 12 键串/section 9 键串不改;
--   不要求该 kind 必须出现;W1 尚不产出段。
CREATE OR REPLACE FUNCTION v13_manifest_validate(p_manifest jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb; j jsonb; c jsonb; e jsonb; n int; m int; sb jsonb;
        v_ops text; v_cons boolean; v_fb boolean; v_dupt text; r jsonb;
BEGIN
  IF p_manifest IS NULL OR jsonb_typeof(p_manifest) IS DISTINCT FROM 'object'
  THEN
    RAISE EXCEPTION 'v13: manifest must be a jsonb object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest) k)
     IS DISTINCT FROM
     'economics,judgments,manifest_version,policy,prefix_identity,query_side,'
     'render,replay,required_revision,sections,session_id,turn_no' THEN
    RAISE EXCEPTION 'v13: manifest top-level key set mismatch (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (p_manifest->>'manifest_version')::int IS DISTINCT FROM 4
     OR p_manifest->>'session_id' IS NULL
     OR p_manifest->>'session_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     OR (p_manifest->>'turn_no')::int IS NULL
     OR (p_manifest->>'turn_no')::int < 0
     OR p_manifest->>'prefix_identity' IS NULL
     OR p_manifest->>'prefix_identity' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: manifest anchor/identity shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'policy') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.policy must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest->'policy') k)
     IS DISTINCT FROM
     'assemble_version,budget_tokens,budget_version,est_bytes_per_token,'
     'judgment_defaults_version,pricing_version,tiers_version'
     OR (p_manifest->'policy'->>'assemble_version')::int IS NULL
     OR (p_manifest->'policy'->>'assemble_version')::int < 1
     OR (p_manifest->'policy'->>'judgment_defaults_version')::int IS NULL
     OR (p_manifest->'policy'->>'judgment_defaults_version')::int < 1
     OR (p_manifest->'policy'->>'tiers_version')::int IS NULL
     OR (p_manifest->'policy'->>'tiers_version')::int < 1
     OR (p_manifest->'policy'->>'budget_version')::int IS NULL
     OR (p_manifest->'policy'->>'budget_version')::int < 1
     OR p_manifest->'policy'->>'pricing_version' IS NULL
     OR length(btrim(p_manifest->'policy'->>'pricing_version')) = 0
     OR (p_manifest->'policy'->>'budget_tokens')::int IS NULL
     OR (p_manifest->'policy'->>'budget_tokens')::int < 0
     OR (p_manifest->'policy'->>'est_bytes_per_token')::int IS NULL
     OR (p_manifest->'policy'->>'est_bytes_per_token')::int <= 0 THEN
    RAISE EXCEPTION 'v13: manifest.policy shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'required_revision') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.required_revision must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'required_revision') k)
     IS DISTINCT FROM
     'asm_ver,corpus,dec,econ_ver,gen_ver,goal,ident_ver,jdef_ver,mgraph_ver,'
     'recall_ver,sem,tools_rev'
     OR (p_manifest->'required_revision'->>'sem')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'sem')::bigint < -1
     OR (p_manifest->'required_revision'->>'dec')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'dec')::bigint < 0
     OR p_manifest->'required_revision'->>'goal' IS NULL
     OR p_manifest->'required_revision'->>'goal' !~ '^[0-9a-f]{64}$'
     OR (p_manifest->'required_revision'->>'tools_rev')::int IS NULL
     OR (p_manifest->'required_revision'->>'tools_rev')::int < 0
     OR (p_manifest->'required_revision'->>'asm_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'asm_ver')::int < 1
     OR (p_manifest->'required_revision'->>'jdef_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'jdef_ver')::int < 1
     OR (p_manifest->'required_revision'->>'gen_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'gen_ver')::int < 1
     OR (p_manifest->'required_revision'->>'corpus')::bigint IS NULL
     OR (p_manifest->'required_revision'->>'corpus')::bigint < 0
     OR (p_manifest->'required_revision'->>'recall_ver')::int IS NULL
     OR (p_manifest->'required_revision'->>'recall_ver')::int < 1
     OR p_manifest->'required_revision'->>'econ_ver' IS NULL
     OR p_manifest->'required_revision'->>'econ_ver' !~ '^[0-9a-f]{64}$'
     OR p_manifest->'required_revision'->>'ident_ver' IS NULL
     OR p_manifest->'required_revision'->>'ident_ver' !~ '^[0-9a-f]{64}$'
     OR p_manifest->'required_revision'->>'mgraph_ver' IS NULL
     OR p_manifest->'required_revision'->>'mgraph_ver' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: manifest.required_revision shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  -- [DP8] 换体六(c):render 块层(4 键恰等;null 枚举穿透封死)
  r := p_manifest->'render';
  IF jsonb_typeof(r) IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(r) k)
        IS DISTINCT FROM
        'render_policy_version,renderer,stable_prefix_est_tokens,wire_digest'
     OR r->>'renderer' IS DISTINCT FROM 'canonical'
     OR (r->>'render_policy_version')::int IS NULL
     OR (r->>'render_policy_version')::int < 1
     OR r->>'wire_digest' IS NULL
     OR r->>'wire_digest' !~ '^[0-9a-f]{64}$'
     OR (r->>'stable_prefix_est_tokens')::int IS NULL
     OR (r->>'stable_prefix_est_tokens')::int < 0 THEN
    RAISE EXCEPTION 'v13: manifest.render shape violation'
      USING ERRCODE = 'V3008';
  END IF;
  e := p_manifest->'economics';
  IF jsonb_typeof(e) IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(e) k)
        IS DISTINCT FROM 'buckets,compact_hint,er,pressure,summary,tier' THEN
    RAISE EXCEPTION 'v13: manifest.economics key set mismatch (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF jsonb_typeof(e->'pressure') IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k)
          FROM jsonb_object_keys(e->'pressure') k)
        IS DISTINCT FROM 'bp,l_eff,r_o,t_used'
     OR EXISTS (SELECT 1 FROM jsonb_each(e->'pressure') p
                 WHERE jsonb_typeof(p.value) IS DISTINCT FROM 'number'
                    OR (p.value #>> '{}')::bigint IS NULL
                    OR (p.value #>> '{}')::bigint < 0) THEN
    RAISE EXCEPTION 'v13: economics.pressure shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF jsonb_typeof(e->'tier') IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(e->'tier') k)
        IS DISTINCT FROM 'basis,effective,raw'
     OR (e->'tier'->>'raw')
        IN ('Normal','TrimSchemas','CompactHistory','AggressivePrune') IS NOT TRUE
     OR (e->'tier'->>'effective')
        IN ('Normal','TrimSchemas','CompactHistory','AggressivePrune') IS NOT TRUE
     OR (e->'tier'->>'basis')
        IN ('raw','predicted','recovery_floor','prior_held') IS NOT TRUE THEN
    RAISE EXCEPTION 'v13: economics.tier shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF jsonb_typeof(e->'er') IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(e->'er') k)
        IS DISTINCT FROM 'branch,e_base,e_comp,hard_window,r,r_source'
     OR (e->'er'->>'branch')
        IN ('adopt','loss','r_unknown','hard_window','actions_off') IS NOT TRUE
     OR (e->'er'->'r' IS NOT NULL
         AND (jsonb_typeof(e->'er'->'r') IS DISTINCT FROM 'number'
              OR (e->'er'->>'r')::numeric < 0))
     OR jsonb_typeof(e->'er'->'e_base') IS DISTINCT FROM 'number'
     OR (e->'er'->>'e_base')::bigint IS NULL
     OR (e->'er'->>'e_base')::bigint < 0
     OR jsonb_typeof(e->'er'->'e_comp') IS DISTINCT FROM 'number'
     OR (e->'er'->>'e_comp')::bigint IS NULL
     OR (e->'er'->>'e_comp')::bigint < 0
     OR jsonb_typeof(e->'er'->'hard_window') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(e->'er'->'r_source') IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k)
          FROM jsonb_object_keys(e->'er'->'r_source') k)
        IS DISTINCT FROM 'account,cache_class,catalog_version,model,provider'
     OR e->'er'->'r_source'->>'provider' IS NULL
     OR e->'er'->'r_source'->>'model' IS NULL
     OR (e->'er'->'r_source'->'catalog_version' IS NOT NULL
         AND ((e->'er'->'r_source'->>'catalog_version')::int IS NULL
              OR (e->'er'->'r_source'->>'catalog_version')::int < 1)) THEN
    RAISE EXCEPTION 'v13: economics.er shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF jsonb_typeof(e->'buckets') IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k)
          FROM jsonb_object_keys(e->'buckets') k)
        IS DISTINCT FROM 'core_cap,effective_budget,history_cap,retrieval_cap'
     OR EXISTS (SELECT 1 FROM jsonb_each(e->'buckets') p
                 WHERE jsonb_typeof(p.value) IS DISTINCT FROM 'number'
                    OR (p.value #>> '{}')::bigint IS NULL
                    OR (p.value #>> '{}')::bigint < 0) THEN
    RAISE EXCEPTION 'v13: economics.buckets shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF e->'compact_hint' IS NOT NULL
     AND jsonb_typeof(e->'compact_hint') IS DISTINCT FROM 'null'
     AND (jsonb_typeof(e->'compact_hint') IS DISTINCT FROM 'object'
          OR (SELECT string_agg(k, ',' ORDER BY k)
               FROM jsonb_object_keys(e->'compact_hint') k)
             IS DISTINCT FROM 'basis,order'
          OR jsonb_typeof(e->'compact_hint'->'order')
             IS DISTINCT FROM 'array'
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                       e->'compact_hint'->'order') o
                      WHERE jsonb_typeof(o) IS DISTINCT FROM 'string')) THEN
    RAISE EXCEPTION 'v13: economics.compact_hint shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  -- [DP7-S] economics.summary 子块键集执法(键集封闭;int 双卫;词表封闭)
  sb := e->'summary';
  IF jsonb_typeof(sb) IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(sb) k)
        IS DISTINCT FROM 'consumed,fallback,intent' THEN
    RAISE EXCEPTION 'v13: economics.summary key set mismatch (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF sb->'intent' IS NOT NULL AND jsonb_typeof(sb->'intent') IS DISTINCT FROM 'null'
     AND (jsonb_typeof(sb->'intent') IS DISTINCT FROM 'object'
          OR (SELECT string_agg(k, ',' ORDER BY k)
               FROM jsonb_object_keys(sb->'intent') k)
             IS DISTINCT FROM 'pack_ok,packs,span_digest,target_span'
          OR jsonb_typeof(sb->'intent'->'target_span') IS DISTINCT FROM 'array'
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(sb->'intent'->'target_span') h
                      WHERE jsonb_typeof(h) IS DISTINCT FROM 'string'
                         OR h #>> '{}' !~ '^[0-9a-f]{64}$')
          OR sb->'intent'->>'span_digest' IS NULL
          OR sb->'intent'->>'span_digest' !~ '^[0-9a-f]{64}$'
          OR jsonb_typeof(sb->'intent'->'packs') IS DISTINCT FROM 'number'
          OR (sb->'intent'->>'packs')::int IS NULL
          OR (sb->'intent'->>'packs')::int < 1
          OR jsonb_typeof(sb->'intent'->'pack_ok') IS DISTINCT FROM 'boolean') THEN
    RAISE EXCEPTION 'v13: economics.summary.intent shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  v_cons := sb->'consumed' IS NOT NULL
            AND jsonb_typeof(sb->'consumed') IS DISTINCT FROM 'null';
  IF v_cons
     AND (jsonb_typeof(sb->'consumed') IS DISTINCT FROM 'object'
          OR (SELECT string_agg(k, ',' ORDER BY k)
               FROM jsonb_object_keys(sb->'consumed') k)
             IS DISTINCT FROM 'decision_id,effect_id,rounds,span_digest'
          OR sb->'consumed'->>'effect_id' IS NULL
          OR sb->'consumed'->>'effect_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          OR sb->'consumed'->>'decision_id' IS NULL
          OR sb->'consumed'->>'decision_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          OR sb->'consumed'->>'span_digest' IS NULL
          OR sb->'consumed'->>'span_digest' !~ '^[0-9a-f]{64}$'
          OR jsonb_typeof(sb->'consumed'->'rounds') IS DISTINCT FROM 'array') THEN
    RAISE EXCEPTION 'v13: economics.summary.consumed shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  v_fb := sb->'fallback' IS NOT NULL
          AND jsonb_typeof(sb->'fallback') IS DISTINCT FROM 'null';
  IF v_fb
     AND (jsonb_typeof(sb->'fallback') IS DISTINCT FROM 'object'
          OR (SELECT string_agg(k, ',' ORDER BY k)
               FROM jsonb_object_keys(sb->'fallback') k)
             IS DISTINCT FROM 'basis,steps'
          OR (sb->'fallback'->>'basis')
             IN ('none','no_budget','no_effect','checks_failed','rejected',
                 'cjk','span_stale') IS NOT TRUE
          OR jsonb_typeof(sb->'fallback'->'steps') IS DISTINCT FROM 'array') THEN
    RAISE EXCEPTION 'v13: economics.summary.fallback shape violation (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF v_fb THEN
    SELECT string_agg(x->>'op', ',' ORDER BY o.ord) INTO v_ops
      FROM (SELECT row_number() OVER () AS ord, x
              FROM jsonb_array_elements(sb->'fallback'->'steps') x) o;
    IF coalesce(v_ops, '') NOT IN
         ('', 'spill', 'spill,drop_rounds', 'spill,drop_rounds,final_trim') THEN
      RAISE EXCEPTION 'v13: fallback steps recipe closure violation (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(sb->'fallback'->'steps') x
                WHERE (x->>'op') = 'drop_rounds'
                  AND (jsonb_typeof(x->'rounds') IS DISTINCT FROM 'array'
                       OR EXISTS (SELECT 1 FROM jsonb_array_elements(x->'rounds') rr
                                   WHERE jsonb_typeof(rr) IS DISTINCT FROM 'number'
                                      OR (rr #>> '{}')::bigint IS NULL
                                      OR (rr #>> '{}')::bigint < 0))) THEN
      RAISE EXCEPTION 'v13: fallback drop_rounds parameter domain violation (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  END IF;
  IF v_cons AND v_fb THEN
    RAISE EXCEPTION 'v13: consumed and fallback are mutually exclusive (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF jsonb_typeof(p_manifest->'replay') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.replay must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'replay') k)
     IS DISTINCT FROM 'mode,prior_artifact_id'
     OR (p_manifest->'replay'->>'mode') IN ('fresh','recompute') IS NOT TRUE
  THEN
    RAISE EXCEPTION 'v13: manifest.replay shape violation (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF jsonb_typeof(p_manifest->'sections') IS DISTINCT FROM 'array'
     OR jsonb_array_length(p_manifest->'sections') = 0 THEN
    RAISE EXCEPTION 'v13: manifest.sections must be a non-empty array (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR s IN SELECT jsonb_array_elements(p_manifest->'sections') LOOP
    IF jsonb_typeof(s) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section must be an object (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(s) k)
       IS DISTINCT FROM
       'cache_scope,churn,content_hash,est_tokens,kind,payload_ref,'
       'priority,section_id,transform' THEN
      RAISE EXCEPTION 'v13: section key set mismatch for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (s->>'cache_scope') IN ('Global','Session','None') IS NOT TRUE
       OR (s->>'priority') IN ('Never','First','Normal','LastResort') IS NOT TRUE
       OR s->>'section_id' IS NULL OR length(btrim(s->>'section_id')) = 0
       OR (s->>'kind') IN ('goal','history','tools','summary','compaction',
                            'memory_graph') IS NOT TRUE
       OR s->>'content_hash' IS NULL
       OR s->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR (s->>'churn')::int IS NULL OR (s->>'churn')::int < 0
       OR (s->>'est_tokens')::int IS NULL OR (s->>'est_tokens')::int < 0 THEN
      RAISE EXCEPTION 'v13: section vocabulary/hash violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    SELECT count(*) INTO n
      FROM jsonb_array_elements(p_manifest->'sections') x
     WHERE x->>'kind' = s->>'kind';
    IF (n = 1 AND s->>'section_id' IS DISTINCT FROM s->>'kind')
       OR (n > 1 AND s->>'section_id' IS DISTINCT FROM
                      s->>'kind' || ':' || left(s->>'content_hash', 8)) THEN
      RAISE EXCEPTION
        'v13: section_id multi-part rule violation for % (V3007)',
        s->>'section_id' USING ERRCODE = 'V3007';
    END IF;
    IF jsonb_typeof(s->'payload_ref') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section payload_ref must be an object for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (s->'payload_ref'->>'kind') IN ('goal','blob') IS NOT TRUE
       OR (CASE WHEN s->'payload_ref'->>'kind' = 'goal'
                THEN (s->'payload_ref'->>'seq')::int IS NULL
                     OR (s->'payload_ref'->>'seq')::int < -1
                ELSE s->'payload_ref'->>'content_hash' IS NULL
                     OR (s->'payload_ref'->>'content_hash') !~ '^[0-9a-f]{64}$'
           END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section payload_ref shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    -- [DP7-S] P0-4① 跨字段执法:payload_ref.kind='blob' ⇒ 恒等段 content_hash
    IF s->'payload_ref'->>'kind' = 'blob'
       AND s->'payload_ref'->>'content_hash' IS DISTINCT FROM s->>'content_hash' THEN
      RAISE EXCEPTION
        'v13: section payload_ref cross-hash drift for % (V3007)',
        s->>'section_id' USING ERRCODE = 'V3007';
    END IF;
    IF jsonb_typeof(s->'transform') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: section transform must be an object for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF jsonb_typeof(s->'transform'->'applied') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: section transform.applied must be boolean for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    IF (CASE WHEN (s->'transform'->>'applied')::boolean
             THEN (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,name'
                  OR (s->'transform'->>'name')
                     IN ('verbatim','catalog_digest','summarize','spill',
                         'memory_inject') IS NOT TRUE
             ELSE (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,reason'
                  OR (s->'transform'->>'reason')
                     IN ('budget','priority_never','disabled','invalid_override',
                         'summary_unavailable','summary_rejected',
                         'compaction_round_drop','compaction_final_trim')
                     IS NOT TRUE
        END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section transform shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    -- [B2] memory_graph 交叉检查(cache_scope/payload_ref/applied 名;
    --      priority 不锁死——overrides 合法;新 RAISE=V3009,§3.4⑥)
    IF s->>'kind' = 'memory_graph'
       AND (  s->>'cache_scope' IS DISTINCT FROM 'Session'
              OR s->'payload_ref'->>'kind' IS DISTINCT FROM 'blob'
              OR (   (s->'transform'->>'applied')::boolean
                 AND s->'transform'->>'name' IS DISTINCT FROM
                     'memory_inject')) THEN
      RAISE EXCEPTION
        'v13: memory_graph section cross-field violation for % (V3009)',
        s->>'section_id' USING ERRCODE = 'V3009';
    END IF;
  END LOOP;
  -- [DP7-S] section_id 全局唯一(V3007)
  SELECT t.sid INTO v_dupt
    FROM (SELECT x->>'section_id' AS sid
            FROM jsonb_array_elements(p_manifest->'sections') x) t
  GROUP BY t.sid HAVING count(*) > 1 LIMIT 1;
  IF v_dupt IS NOT NULL THEN
    RAISE EXCEPTION 'v13: duplicate section_id % (V3007)', v_dupt
      USING ERRCODE = 'V3007';
  END IF;
  -- [DP7-S] consumed 与 summary 段双向一致+adopted/回退形态执法
  SELECT count(*) INTO n FROM jsonb_array_elements(p_manifest->'sections') x
   WHERE x->>'kind' = 'summary';
  IF v_cons THEN
    IF n <> 1 THEN
      RAISE EXCEPTION 'v13: consumed requires exactly one summary section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    SELECT count(*) INTO m FROM jsonb_array_elements(p_manifest->'sections') x
     WHERE x->>'kind' = 'summary'
       AND (x->'transform'->>'applied')::boolean
       AND x->'transform'->>'name' = 'summarize';
    IF m <> 1 THEN
      RAISE EXCEPTION 'v13: summary section must be applied summarize (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    SELECT count(*) INTO m FROM jsonb_array_elements(p_manifest->'sections') x
     WHERE x->>'kind' = 'history'
       AND (x->'transform'->>'applied')::boolean
       AND x->'transform'->>'name' = 'verbatim';
    IF m <> 1 THEN
      RAISE EXCEPTION
        'v13: adopted shape needs one applied verbatim history section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    SELECT count(*) INTO m FROM jsonb_array_elements(p_manifest->'sections') x
     WHERE x->>'kind' = 'compaction';
    IF m <> 0 THEN
      RAISE EXCEPTION 'v13: adopted shape forbids compaction sections (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  ELSE
    IF n <> 0 THEN
      RAISE EXCEPTION
        'v13: summary section without consumed (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  END IF;
  IF v_fb AND n <> 0 THEN
    RAISE EXCEPTION 'v13: fallback and summary section are mutually exclusive (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  IF jsonb_typeof(p_manifest->'query_side') IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'v13: manifest.query_side must be an object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k)
       FROM jsonb_object_keys(p_manifest->'query_side') k)
     IS DISTINCT FROM 'candidates,query_artifact_id'
     OR jsonb_typeof(p_manifest->'query_side'->'candidates')
        IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: query_side field family missing (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR c IN SELECT jsonb_array_elements(
             p_manifest->'query_side'->'candidates') LOOP
    IF jsonb_typeof(c) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: candidate must be an object (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(c) k)
       IS DISTINCT FROM 'bm25,content_hash,decision_id,spans'
       OR c->>'content_hash' IS NULL
       OR c->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(c->'spans') IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION 'v13: candidate shape violation (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
  IF jsonb_typeof(p_manifest->'judgments') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: manifest.judgments must be an array (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  FOR j IN SELECT jsonb_array_elements(p_manifest->'judgments') LOOP
    IF jsonb_typeof(j) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: judgment row must be an object (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
    IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(j) k)
       IS DISTINCT FROM
       'decision_id,epoch,final_action,raw_verdict,request_hash,'
       'template_name,template_version'
       OR j->>'decision_id' IS NULL
       OR j->>'request_hash' IS NULL
       OR j->>'request_hash' !~ '^[0-9a-f]{64}$'
       OR (j->>'epoch') IN ('pre-bind','pre-finalize','post-execute') IS NOT TRUE
       OR j->>'raw_verdict' IS NULL
       OR (j->>'final_action')
          IN ('recorded','include','exclude','degrade','fail') IS NOT TRUE
       OR NOT (  (  j->>'template_name' IS NULL
                  AND j->>'template_version' IS NULL )
              OR (  j->>'template_name' IS NOT NULL
                  AND (j->>'template_version')::int IS NOT NULL
                  AND (j->>'template_version')::int >= 1 ) ) THEN
      RAISE EXCEPTION 'v13: judgment row shape violation (V3003)'
        USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
END $$;

-- ===== [B2] 换体五:v13_refresh_context v5(W1) =====
--   唯一仍 SECURITY DEFINER 的函数(逐字复制 periphery)+W1 增量(§3.6 闭集):
--   (a) 策略行锁名单七名+1='mgraph'(八名,ORDER BY name;summary_accept 留在名单);
--   (b) generation latch 之后、assemble 之前:pg_advisory_xact_lock
--       (v13_lock_key(sid,'mgraph-build'))——mgraph freeze 锁,锁序最末。
--   W2 增量(memory belt/degraded audit)届时就地编辑本复制体。
CREATE OR REPLACE FUNCTION v13_refresh_context(p_effect uuid, p_attempt int, p_fence bigint)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_row effects; v_sid uuid; v_manifest jsonb; v_art uuid; v_out text;
        v_budget int; v_div int; v_inline_max bigint;
        v_ovr jsonb; v_off jsonb;
        v_full jsonb; v_tools jsonb; v_hh text; v_th text; v_mh text;
        v_mat jsonb; v_sh text; v_smat jsonb;
        v_tiers jsonb; v_cbud jsonb; v_gate jsonb; v_ft jsonb; v_rp jsonb;
        v_g2 jsonb; v_lat jsonb; v_cp jsonb;                       -- [DP8]
        v_sf jsonb; v_sw jsonb; v_ig jsonb;                        -- [DP8]
        v_mem jsonb;                                               -- [B2]
        v_b jsonb; v_i int; v_lo int; v_hi int; v_prev_hi int; v_sum numeric;
BEGIN
  SELECT * INTO v_row FROM public.effects WHERE effect_id = p_effect;
  IF v_row.effect_id IS NULL THEN
    RAISE EXCEPTION 'v13: unknown effect %', p_effect;
  END IF;
  IF v_row.kind IS DISTINCT FROM 'context_refresh' THEN
    RAISE EXCEPTION 'v13: refresh settle on non-context_refresh effect %', p_effect;
  END IF;
  v_sid := v_row.session_id;

  IF v_row.status IS NOT DISTINCT FROM 'claimed'
     AND (v_row.attempt_no IS DISTINCT FROM p_attempt
          OR v_row.fence IS DISTINCT FROM p_fence) THEN
    RETURN 'stale';
  END IF;

  PERFORM 1 FROM public.sessions WHERE session_id = v_sid FOR UPDATE;
  PERFORM 1 FROM public.v13_tools_meta WHERE singleton FOR UPDATE;
  PERFORM 1 FROM public.v13_policies
   -- [B2] 八名:DP8 七名 + 'mgraph'(mgraph 策略行进装配输入;同缝扩展、
   -- 不准删已有名——periphery README 偏差 #2 纪律)
   WHERE name IN ('assemble_manifest','generation','judgment_defaults',
                  'context_tiers','context_budget','render_policy',
                  'summary_accept','mgraph')
     AND active
   ORDER BY name FOR UPDATE;
  PERFORM 1 FROM public.v13_pricing                          -- [DP7](a)
   WHERE active ORDER BY provider, model, account, cache_class FOR UPDATE;
  PERFORM 1 FROM public.effects                                    -- [DP7-S]
   WHERE session_id = v_sid AND kind = 'context_summary'
     AND status = 'succeeded'
   ORDER BY effect_id FOR SHARE;

  SELECT (value->>'budget_tokens')::int,
         (value->>'est_bytes_per_token')::int,
         (value->>'inline_max_bytes')::bigint,
         value->'priority_overrides',
         value->'kinds_disabled'
    INTO v_budget, v_div, v_inline_max, v_ovr, v_off
   FROM public.v13_policies WHERE name = 'assemble_manifest' AND active;
  IF v_div IS NULL OR v_div <= 0 OR v_budget IS NULL OR v_budget < 0
     OR v_inline_max IS NULL OR v_inline_max <= 0
     OR jsonb_typeof(v_ovr) IS DISTINCT FROM 'object'
     OR (SELECT bool_or((o.value #>> '{}')
             IN ('Never','First','Normal','LastResort') IS NOT TRUE)
           FROM jsonb_each(v_ovr) o) IS TRUE
     OR jsonb_typeof(v_off) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'v13: assemble_manifest policy shape invalid'
      USING ERRCODE = 'V3003';
  END IF;
  PERFORM public.v13_judgment_defaults_check(
    (SELECT value FROM public.v13_policies
      WHERE name = 'judgment_defaults' AND active));

  -- [DP7](b) 经济学行形状守卫(装配前 RAISE V3007;malformed 值的转型
  -- 失败同归 V3007——fail-loud,不静默)
  BEGIN
    SELECT value INTO v_tiers FROM public.v13_policies
     WHERE name = 'context_tiers' AND active;
    IF v_tiers IS NULL
       OR jsonb_typeof(v_tiers->'bands') IS DISTINCT FROM 'array'
       OR jsonb_array_length(coalesce(v_tiers->'bands', '[]'::jsonb)) <> 4
       OR jsonb_typeof(v_tiers->'hysteresis') IS DISTINCT FROM 'object'
       OR (v_tiers->'hysteresis'->>'cooldown_turns')::int IS NULL
       OR (v_tiers->'hysteresis'->>'cooldown_turns')::int < 1
       OR (v_tiers->'hysteresis'->>'max_downgrade_steps')::int IS NULL
       OR (v_tiers->'hysteresis'->>'max_downgrade_steps')::int < 1
       OR jsonb_typeof(v_tiers->'actions_enabled') IS DISTINCT FROM 'boolean'
       OR jsonb_typeof(v_tiers->'r_o') IS DISTINCT FROM 'object'
       OR jsonb_typeof(v_tiers->'r_o'->'p_steady') IS DISTINCT FROM 'number'
       OR (v_tiers->'r_o'->>'p_steady')::numeric <= 0
       OR (v_tiers->'r_o'->>'p_steady')::numeric > 1
       OR jsonb_typeof(v_tiers->'r_o'->'p_recovery') IS DISTINCT FROM 'number'
       OR (v_tiers->'r_o'->>'p_recovery')::numeric <= 0
       OR (v_tiers->'r_o'->>'p_recovery')::numeric > 1
       OR (v_tiers->'r_o'->>'min_samples')::int IS NULL
       OR (v_tiers->'r_o'->>'min_samples')::int < 1
       OR (v_tiers->'r_o'->>'cold_tokens')::int IS NULL
       OR (v_tiers->'r_o'->>'cold_tokens')::int <= 0
       OR (v_tiers->'r_o'->>'recovery_turns')::int IS NULL
       OR (v_tiers->'r_o'->>'recovery_turns')::int < 1 THEN
      RAISE EXCEPTION 'v13: context_tiers policy shape invalid (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    v_prev_hi := 0;
    FOR v_i IN 1 .. 4 LOOP
      v_b := v_tiers->'bands'->(v_i - 1);
      IF v_b IS NULL
         OR jsonb_typeof(v_b->'lo_bp') IS DISTINCT FROM 'number'
         OR jsonb_typeof(v_b->'tier') IS DISTINCT FROM 'string'
         OR (v_b->>'tier') NOT IN
              ('Normal','TrimSchemas','CompactHistory','AggressivePrune')
         OR (SELECT count(DISTINCT x->>'tier')
              FROM jsonb_array_elements(v_tiers->'bands') x) <> 4
         OR (v_b->>'lo_bp')::int IS DISTINCT FROM v_prev_hi
         OR (v_b->>'lo_bp')::int < 0
         OR (v_i < 4 AND (NULLIF(v_b->>'hi_bp', '')::int IS NULL
                          OR NULLIF(v_b->>'hi_bp', '')::int <= (v_b->>'lo_bp')::int))
         OR (v_i = 4 AND NULLIF(v_b->>'hi_bp', '')::int IS NOT NULL) THEN
        RAISE EXCEPTION 'v13: context_tiers bands shape invalid (V3007)'
          USING ERRCODE = 'V3007';
      END IF;
      v_prev_hi := NULLIF(v_b->>'hi_bp', '')::int;
    END LOOP;

    SELECT value INTO v_cbud FROM public.v13_policies
     WHERE name = 'context_budget' AND active;
    v_sum := coalesce((v_cbud->'buckets'->>'core')::numeric, 0)
           + coalesce((v_cbud->'buckets'->>'history')::numeric, 0)
           + coalesce((v_cbud->'buckets'->>'retrieval')::numeric, 0);
    IF v_cbud IS NULL
       OR jsonb_typeof(v_cbud->'buckets') IS DISTINCT FROM 'object'
       OR jsonb_typeof(v_cbud->'buckets'->'core') IS DISTINCT FROM 'number'
       OR (v_cbud->'buckets'->>'core')::numeric <= 0
       OR jsonb_typeof(v_cbud->'buckets'->'history') IS DISTINCT FROM 'number'
       OR (v_cbud->'buckets'->>'history')::numeric <= 0
       OR jsonb_typeof(v_cbud->'buckets'->'retrieval') IS DISTINCT FROM 'number'
       OR (v_cbud->'buckets'->>'retrieval')::numeric <= 0
       OR v_sum > 1.0
       OR (v_cbud->>'l_eff_tokens')::int IS NULL
       OR (v_cbud->>'l_eff_tokens')::int <= 0
       OR (v_cbud->>'keep_tail_turns')::int IS NULL
       OR (v_cbud->>'keep_tail_turns')::int < 1
       OR (v_cbud->>'hard_window_bp')::int IS NULL
       OR (v_cbud->>'hard_window_bp')::int <= 0 THEN
      RAISE EXCEPTION 'v13: context_budget policy shape invalid (V3007)'
        USING ERRCODE = 'V3007';
    END IF;

    -- [DP7](b) 非装配输入行(不入锁面)的配置错误前置检查:fail-loud
    SELECT value INTO v_gate FROM public.v13_policies
     WHERE name = 'judge_spend_gate' AND active;
    IF v_gate IS NULL
       OR (v_gate->>'session_asks_cap')::int IS NULL
       OR (v_gate->>'session_asks_cap')::int < 1
       OR (v_gate->>'day_asks_cap')::int IS NULL
       OR (v_gate->>'day_asks_cap')::int < 1
       OR (v_gate->>'scope') IN ('fast_path','slow_path') IS NOT TRUE THEN
      RAISE EXCEPTION 'v13: judge_spend_gate policy shape invalid (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    SELECT value INTO v_ft FROM public.v13_policies
     WHERE name = 'fastpath_tiers' AND active;
    IF v_ft IS NULL
       OR jsonb_typeof(v_ft->'tiers_over_one_batch') IS DISTINCT FROM 'array'
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                     v_ft->'tiers_over_one_batch') x
                   WHERE (x#>> '{}') NOT IN
                     ('Normal','TrimSchemas','CompactHistory',
                      'AggressivePrune')) THEN
      RAISE EXCEPTION 'v13: fastpath_tiers policy shape invalid (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    SELECT value INTO v_rp FROM public.v13_policies
     WHERE name = 'render_policy' AND active;
    IF v_rp IS NULL OR v_rp->>'renderer' IS DISTINCT FROM 'canonical'
       OR jsonb_typeof(v_rp->'cache_markers') IS DISTINCT FROM 'boolean'
       OR v_rp->>'provider_policy' IS DISTINCT FROM 'protocol_only' THEN
      RAISE EXCEPTION 'v13: render_policy policy shape invalid (V3007)'
        USING ERRCODE = 'V3007';
    END IF;

    -- [DP8] 换体七(a):外围策略行形状守卫(同点 fail-loud;新 RAISE 一律 V3008)
    SELECT value INTO v_g2 FROM public.v13_policies
     WHERE name = 'generation' AND active;
    IF v_g2 IS NULL
       OR length(btrim(v_g2->>'provider')) = 0
       OR length(btrim(v_g2->>'model')) = 0
       OR jsonb_typeof(v_g2->'system_blocks') IS DISTINCT FROM 'array'
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_g2->'system_blocks') x
                   WHERE jsonb_typeof(x) IS DISTINCT FROM 'object'
                      OR x->>'content_hash' IS NULL
                      OR x->>'content_hash' !~ '^[0-9a-f]{64}$')
       OR v_g2->>'system_blocks_digest' IS NULL
       OR (v_g2->>'system_blocks_digest' IS DISTINCT FROM '-none-'
           AND v_g2->>'system_blocks_digest' !~ '^[0-9a-f]{64}$') THEN
      RAISE EXCEPTION 'v13: generation policy v2 shape invalid'
        USING ERRCODE = 'V3008';
    END IF;
    IF v_g2->>'system_blocks_digest' IS DISTINCT FROM '-none-' THEN
      IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_g2->'system_blocks') o(h)
                  LEFT JOIN public.artifacts b
                    ON b.content_hash = o.h->>'content_hash'
                   AND b.kind = 'system_block'
                 WHERE b.content_hash IS NULL)
         OR v_g2->>'system_blocks_digest' IS DISTINCT FROM (
              SELECT coalesce(encode(digest(jsonb_agg(b.inline ORDER BY o.ord)::text,
                                     'sha256'), 'hex'), '-none-')
                FROM jsonb_array_elements(v_g2->'system_blocks')
                     WITH ORDINALITY o(h, ord)
                LEFT JOIN public.artifacts b
                  ON b.content_hash = o.h->>'content_hash'
                 AND b.kind = 'system_block') THEN
        RAISE EXCEPTION 'v13: generation system_blocks_digest mismatch (V3008)'
          USING ERRCODE = 'V3008';
      END IF;
    END IF;
    SELECT value INTO v_lat FROM public.v13_policies
     WHERE name = 'latches' AND active;
    IF v_lat IS NULL OR (v_lat->>'max_per_session')::int IS NULL
       OR (v_lat->>'max_per_session')::int < 1 THEN
      RAISE EXCEPTION 'v13: latches policy shape invalid'
        USING ERRCODE = 'V3008';
    END IF;
    SELECT value INTO v_cp FROM public.v13_policies
     WHERE name = 'cache_probe' AND active;
    IF v_cp IS NULL
       OR (v_cp->>'tolerance_ratio')::numeric IS NULL
       OR (v_cp->>'tolerance_ratio')::numeric <= 0
       OR (v_cp->>'tolerance_ratio')::numeric > 1
       OR (v_cp->>'min_tokens')::int IS NULL
       OR (v_cp->>'min_tokens')::int < 0 THEN
      RAISE EXCEPTION 'v13: cache_probe policy shape invalid'
        USING ERRCODE = 'V3008';
    END IF;
    SELECT value INTO v_sf FROM public.v13_policies
     WHERE name = 'shadow_flip' AND active;
    IF v_sf IS NULL OR (v_sf->>'min_zero_diff_turns')::int IS NULL
       OR (v_sf->>'min_zero_diff_turns')::int < 1 THEN
      RAISE EXCEPTION 'v13: shadow_flip policy shape invalid'
        USING ERRCODE = 'V3008';
    END IF;
    SELECT value INTO v_sw FROM public.v13_policies
     WHERE name = 'shadow_watch' AND active;
    IF v_sw IS NULL OR jsonb_typeof(v_sw->'targets') IS DISTINCT FROM 'array'
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(v_sw->'targets') x
                   WHERE jsonb_typeof(x) IS DISTINCT FROM 'string') THEN
      RAISE EXCEPTION 'v13: shadow_watch policy shape invalid'
        USING ERRCODE = 'V3008';
    END IF;
    SELECT value INTO v_ig FROM public.v13_policies
     WHERE name = 'intent_gate' AND active;
    IF v_ig IS NULL
       OR jsonb_typeof(v_ig->'actions_enabled') IS DISTINCT FROM 'boolean' THEN
      RAISE EXCEPTION 'v13: intent_gate policy shape invalid'
        USING ERRCODE = 'V3008';
    END IF;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
              OR invalid_parameter_value THEN
    RAISE EXCEPTION 'v13: economics policy rows malformed (V3007)'
      USING ERRCODE = 'V3007';
  END;

  -- [DP8] 换体七(b):generation latch 内联首发(fire-or-adopt;settle 已持
  --       sessions 行锁=admission 锁;随后 generation_effective 读到
  --       latch——首次装配即首触发冻结,OQ2 时点语义)
  INSERT INTO public.latches (session_id, name, value)
  SELECT v_sid, 'generation',
         jsonb_set(value, '{generation_version}', to_jsonb(version), true)
    FROM public.v13_policies
   WHERE name = 'generation' AND active
   ON CONFLICT (session_id, name) DO NOTHING;

  -- [B2] mgraph freeze 锁:与 build 的会话级 pg_advisory_lock、run_round
  -- 的 pg_advisory_xact_lock 同一 v13_lock_key(sid,'mgraph-build'),
  -- 互相排斥;锁序最末(sessions -> tools_meta -> 策略行 -> pricing
  -- -> context_summary FOR SHARE -> 此处);持有区间=assemble+belt 的
  -- CPU 时间,零 HTTP、零外部 IO(DP7 不变量 1)。
  PERFORM pg_advisory_xact_lock(public.v13_lock_key(v_sid, 'mgraph-build'));
  v_manifest := public.v13_assemble_manifest(v_sid, NULL);
  PERFORM public.v13_manifest_validate(v_manifest);

  IF octet_length(v_manifest::text) > v_inline_max THEN
    RAISE EXCEPTION 'v13: manifest exceeds inline_max_bytes (route to ref: DP4+)'
      USING ERRCODE = 'V3003';
  END IF;

  v_out := public.v13_complete(p_effect, p_attempt, p_fence, 'succeeded',
              jsonb_build_object(
                'required_revision', v_manifest->'required_revision',
                'sections', jsonb_array_length(v_manifest->'sections')));
  IF v_out IS DISTINCT FROM 'accepted' THEN
    RETURN v_out;
  END IF;

  v_full  := public.v13_canonical_state(v_sid) -> 'messages';
  v_tools := public.v13_canonical_state(v_sid) -> 'tools';
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'history';

  IF encode(digest(coalesce(v_full::text, ''), 'sha256'), 'hex')
     IS NOT DISTINCT FROM v_mh THEN
    -- ===== [DP7-S] 允许清单 #3:IF 臂=economy 加载态原文四行逐字(V3003
    --       墓碑纪律;v_hist→v_full 仅换绑定名,含 V3003 文案逐字) =====
    v_hh := public.v13_blob_land(p_effect, v_full);
    IF v_hh IS DISTINCT FROM v_mh THEN
      RAISE EXCEPTION 'v13: history blob hash drift vs manifest section'
        USING ERRCODE = 'V3003';
    END IF;
  ELSE
    v_mat := public.v13_history_section_material(v_sid);
    IF encode(digest(coalesce(v_mat::text, ''), 'sha256'), 'hex')
       IS DISTINCT FROM v_mh THEN
      RAISE EXCEPTION 'v13: history blob hash drift vs manifest section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    PERFORM public.v13_history_belt_guard(v_sid, v_full, v_mat, v_manifest);
    v_hh := public.v13_blob_land(p_effect, v_mat);
    IF v_hh IS DISTINCT FROM v_mh THEN
      RAISE EXCEPTION 'v13: history blob land drift vs manifest section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  END IF;
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'tools';
  v_th := public.v13_blob_land(p_effect, v_tools);
  IF v_th IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: tools blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;

  -- ===== [DP7-S] 允许清单 #4:summary belt(tools belt 后、artifact_land 前;
  --       不变量 9:重算材料恒等才落行,零信 effect 自报哈希) =====
  SELECT s->>'content_hash' INTO v_sh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'summary';
  v_smat := public.v13_summary_section_material(v_sid);

  IF NOT FOUND THEN
    IF v_smat IS NOT NULL THEN
      RAISE EXCEPTION 'v13: summary material without summary section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  ELSE
    IF v_smat IS NULL
       OR encode(digest(coalesce(v_smat::text, ''), 'sha256'), 'hex')
          IS DISTINCT FROM v_sh THEN
      RAISE EXCEPTION 'v13: summary blob hash drift vs manifest section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    IF public.v13_blob_land(p_effect, v_smat) IS DISTINCT FROM v_sh THEN
      RAISE EXCEPTION 'v13: summary blob land drift vs manifest section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  END IF;

  -- ===== [B2] memory belt(§3.6③;summary belt 后、artifact_land 前;
  --       只做正向复核——预算滤掉发生在 packing 之后,材料函数此时仍返回
  --       非 NULL;「有材料却没段就 RAISE」会在 kinds_disabled/retrieval
  --       装不下时误报。无段:不 land、不因材料非 NULL 而 RAISE) =====
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'memory_graph';
  IF FOUND THEN
    v_mem := public.v13_mgraph_section_material(v_sid);
    IF v_mem IS NULL
       OR encode(digest(coalesce(v_mem::text, ''), 'sha256'), 'hex')
          IS DISTINCT FROM v_mh THEN
      RAISE EXCEPTION 'v13: memory blob hash drift vs manifest section (V3009)'
        USING ERRCODE = 'V3009';
    END IF;
    IF public.v13_blob_land(p_effect, v_mem) IS DISTINCT FROM v_mh THEN
      RAISE EXCEPTION 'v13: memory blob land drift vs manifest section (V3009)'
        USING ERRCODE = 'V3009';
    END IF;
  END IF;

  v_art := public.v13_artifact_land(p_effect, 'context', v_manifest);
  UPDATE public.effects SET result = coalesce(result,'{}'::jsonb) ||
           jsonb_build_object('context_artifact_id', v_art)
   WHERE effect_id = p_effect;
  UPDATE public.sessions
     SET context_active_revision = v_manifest->'required_revision',
         context_active_artifact = v_art
   WHERE session_id = v_sid;
  PERFORM public.v13_shadow_observe(v_sid);   -- [DP8] 换体七(d):settle 尾观察
  -- [B2] degraded 审计(§3.6④):仅 status=degraded 落一条
  --      audit/memory_degraded(消费契约:degraded 时记忆不得当可靠召回面,
  --      当前 turn 消息永远直读);审计型不进策展词表、不推 sem/dec——
  --      不自激(检验在 J6)。
  IF public.v13_mgraph_section_status(v_sid) = 'degraded' THEN
    PERFORM public.v13_append_event(v_sid, gen_random_uuid(),
             'audit/memory_degraded',
             jsonb_build_object('basis', 'degraded'));
  END IF;
  RETURN 'accepted';
END $$;


-- ===== [B2] ACL(§1.7;REVOKE PUBLIC 后按调用角色授权;重复 GRANT 保持,
--       不先探测「是不是已经有」) =====
REVOKE EXECUTE ON FUNCTION
  v13_mgraph_asm_ver(uuid),
  v13_mgraph_turn_query(uuid),
  v13_mgraph_provenance(uuid,text),
  v13_mgraph_section_plan(uuid),
  v13_mgraph_section_material(uuid),
  v13_mgraph_section_status(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_asm_ver(uuid),
  v13_mgraph_turn_query(uuid),
  v13_mgraph_provenance(uuid,text),
  v13_mgraph_section_plan(uuid),
  v13_mgraph_section_material(uuid),
  v13_mgraph_section_status(uuid)
TO v13_route, v13_resolve, v13_recall;
-- route 手直调 assemble(INVOKER)会读 evidence/材料面:补 route(原
-- mgraph 只授 recall/resolve);progress/policy/body_hash/freshness 显式
-- 三角色(memory_nodes SELECT 已由 mgraph M1 授三角色,重复 GRANT 保持)
GRANT EXECUTE ON FUNCTION v13_mgraph_evidence(uuid,text)
TO v13_route;
GRANT EXECUTE ON FUNCTION
  v13_mgraph_policy(), v13_mgraph_progress(uuid),
  v13_body_hash(text), v13_transcript_freshness(uuid)
TO v13_route, v13_resolve, v13_recall;
GRANT SELECT ON memory_nodes TO v13_route, v13_resolve, v13_recall;
-- run_round/next_action 维持仅 resolve;v13_lock_key 不授予 route(只由
-- DEFINER refresh 以属主调用)——J9 负向断言。

COMMIT;
