BEGIN;

-- =========================================================================
-- DP6 filter (v13_filter.sql): existence-Noul gate + per-chunk Score +
-- cross-session reuse + judgment_defaults.points (F1/F2/F10 legislation).
-- Design: docs/designs/v13-context-on-pg.md §4.5/§4.4(structured layer)/
-- §6.1/§9/§10 G-ctx4. Review: stepfun F1/F2. Contracts: DP1 §1.3 row DP6,
-- DP2 §1.4 row DP6, DP3 §1.4 row DP6, DP4 §1.4 row DP6 ①, DP5 §1.4 ①-⑥.
-- File order = load order. Error code family: V3006.
-- Implementation discipline: the five OR REPLACE bodies are mechanical
-- copies of the upstream loaded-state text (v13/envelope/v13_envelope.sql
-- for judgment_hash/resolve_judgments; v13/recall/v13_recall.sql for
-- judgment_envelope/assemble_manifest; v13/chunks/v13_chunks.sql for
-- chunk_referenced) edited only at the [DP6] markers below.
-- =========================================================================

-- === L1 键材料构建器(哈希同源单源;四面=材料构造/哈希/存储/装配 join) ===

-- 候选集摘要(F2 立法核心):排序去重候选 content_hash 全集的 sha256。
-- p_candidates 为 DP5 三键对象数组 [{content_hash,bm25,spans}]——材料只
-- 取 cand->>'content_hash',bm25/spans 不入(对象全文入料会令语料统计漂移
-- [IDF/avgdl 随 ingest 变]轮换存在性键,违背 F2「候选集维度」;gate D6
-- 防回归)。信封侧(env->'candidates')与装配侧(自身 v13_recall_candidates
-- 产物)同函数同输入——单源(DP5 信封/装配共用 recall 的同款纪律)。
CREATE FUNCTION v13_candidates_digest(p_candidates jsonb) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest((SELECT coalesce(jsonb_agg(h ORDER BY h), '[]'::jsonb)
                          FROM (SELECT DISTINCT cand->>'content_hash' AS h
                                  FROM jsonb_array_elements(p_candidates) cand) d(h))::text,
                 'sha256'), 'hex');
$$;

-- per-chunk 键材料/decisions.context 原物:query 引用(goal_hash)+
-- chunk 引用(DP4 冻结路径 context->'chunk'->>'content_hash' 的构造半边)。
-- 材料=存储三位一体:resolve 落行原物存储,装配按字段等值 join,零哈希重算。
CREATE FUNCTION v13_filter_ref(p_goal_hash text, p_chunk_hash text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_goal_hash IS NULL OR p_goal_hash !~ '^[0-9a-f]{64}$'
     OR p_chunk_hash IS NULL OR p_chunk_hash !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'v13: filter ref requires 64hex goal_hash and chunk_hash'
      USING ERRCODE = 'V3006';
  END IF;
  RETURN jsonb_build_object(
    'query_content_hash', p_goal_hash,
    'chunk', jsonb_build_object('content_hash', p_chunk_hash));
END $$;

-- 存在性键材料(F2:候选集维度):query 引用+候选集摘要。
CREATE FUNCTION v13_existence_ref(p_env jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_env IS NULL OR p_env->>'goal_hash' IS NULL
     OR p_env->>'goal_hash' !~ '^[0-9a-f]{64}$'
     OR p_env->'candidates' IS NULL
     OR jsonb_typeof(p_env->'candidates') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION
      'v13: existence ref requires envelope goal_hash and candidates keys'
      USING ERRCODE = 'V3006';
  END IF;
  RETURN jsonb_build_object(
    'query_content_hash', p_env->>'goal_hash',
    'candidates_digest',  v13_candidates_digest(p_env->'candidates'));
END $$;

-- 行上下文族分发(不变量 2:canonical 路径逐字节不变——分支仅两处)。
CREATE FUNCTION v13_row_context(p_env jsonb, p_signal text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_hash text;
BEGIN
  IF p_signal = 'corpus_exists' THEN
    RETURN v13_existence_ref(p_env);
  END IF;
  IF p_signal LIKE 'chunk::%' THEN
    v_hash := substr(p_signal, 8);
    IF v_hash !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION
        'v13: chunk signal must carry a 64hex content_hash (%)', p_signal
        USING ERRCODE = 'V3006';
    END IF;
    RETURN v13_filter_ref(p_env->>'goal_hash', v_hash);
  END IF;
  RETURN v13_group_state(p_env, p_signal);   -- canonical:DP2 原样转发
END $$;

-- 过滤族模板在岗守卫(信封合并层消费;fail-closed:族缺失即 parse 响亮失败,
-- 不静默过滤关闭——DP2 needed 族守卫的同族纪律)。
CREATE FUNCTION v13_require_filter_templates(p_templates jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF p_templates IS NULL
     OR p_templates->'corpus_exists' IS NULL
     OR p_templates->'corpus_exists'->>'kind' IS DISTINCT FROM 'noul'
     OR p_templates->'corpus_exists'->>'question' IS NULL
     OR p_templates->'chunk_score' IS NULL
     OR p_templates->'chunk_score'->>'kind' IS DISTINCT FROM 'score'
     OR p_templates->'chunk_score'->>'question' IS NULL
     OR p_templates->'chunk_score'->'criteria' IS NULL THEN
    RAISE EXCEPTION
      'v13: frozen filter templates corpus_exists/chunk_score missing or incomplete'
      USING ERRCODE = 'V3006';
  END IF;
END $$;

-- goal 文本哈希钉定读取(OQ10):按 content_hash 取 v13_goals 行的 payload
-- 文本——parse 与 worker 之间 goal 前进时,旧 goal_hash 仍解析出旧文本
-- (content-addressed 确定性,键与载荷不漂移)。空 goal=空串。
CREATE FUNCTION v13_goal_text(p_sid uuid, p_goal_hash text) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT g.payload->>'text' FROM v13_goals g
                    WHERE g.session_id = p_sid
                      AND g.content_hash = p_goal_hash
                    ORDER BY g.seq DESC LIMIT 1), '');
$$;

-- === L2 默认分支/闸门/动作(§6.1+F1+F2 消费面) ===

-- 默认动作读取(F1:版本化缺省的唯一运行期入口):缺点/缺态=V3006 响亮
-- (配置错误,不静默回退——F1 所防的「实现者临场决定」被结构性封死)。
CREATE FUNCTION v13_filter_defaults_action(p_point text, p_state text)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE v_pt jsonb;
BEGIN
  v_pt := v13_policy('judgment_defaults')->'points'->p_point;
  IF v_pt IS NULL OR jsonb_typeof(v_pt) <> 'object' THEN
    RAISE EXCEPTION
      'v13: judgment_defaults missing point % (config error, append a new version)',
      p_point USING ERRCODE = 'V3006';
  END IF;
  IF v_pt->>p_state IS NULL THEN
    RAISE EXCEPTION
      'v13: judgment_defaults point % missing state %', p_point, p_state
      USING ERRCODE = 'V3006';
  END IF;
  RETURN v_pt->>p_state;
END $$;

-- 存在性判定→动作:闸带(<=hi 闸/>=lo 放行/中间=review 带走 defaults)。
-- 策略形状 fail-closed(分步类型先验→显式 cast→域校验,DP4 三律)。
CREATE FUNCTION v13_existence_action(p_answer jsonb) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb; v_hi numeric; v_lo numeric; v_noul numeric;
BEGIN
  v_pol := v13_policy('chunk_filter');
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol->'gate_closed_hi') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'gate_open_lo') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy shape'
      USING ERRCODE = 'V3006';
  END IF;
  v_hi := (v_pol->>'gate_closed_hi')::numeric;
  v_lo := (v_pol->>'gate_open_lo')::numeric;
  IF v_hi < 0 OR v_lo > 1 OR v_hi >= v_lo THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy values'
      USING ERRCODE = 'V3006';
  END IF;
  v_noul := (p_answer->>'noul')::numeric;
  IF v_noul <= v_hi THEN RETURN 'exclude'; END IF;
  IF v_noul >= v_lo THEN RETURN 'include'; END IF;
  RETURN v13_filter_defaults_action('corpus_exists', 'review');
END $$;

-- 闸门开否(OQ6:missing/timeout/review 全 fail-open 不闸;已答确信无→闸)。
CREATE FUNCTION v13_filter_gate_open(p_env jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
DECLARE v_ans jsonb;
BEGIN
  SELECT d.answer INTO v_ans FROM decisions d
   WHERE d.session_id = (p_env->>'sid')::uuid
     AND d.signal = 'corpus_exists'
     AND d.context = v13_existence_ref(p_env)
     AND d.answer IS NOT NULL AND d.status IN ('answered','cached')
   LIMIT 1;
  IF v_ans IS NULL THEN
    RETURN v13_filter_defaults_action('corpus_exists', 'missing') <> 'exclude';
  END IF;
  RETURN v13_existence_action(v_ans) <> 'exclude';
END $$;

-- 可填 per-chunk 缺口计数(remaining 的闸感知口径):signal 可解析且体在
-- (content-addressed 查找,ix_chunks_content_hash 背书)。体缺行=不可填
-- (parse→resolve 窗口内重摄取已杀无引用行;下一信封自然收敛)。
CREATE FUNCTION v13_filter_fillable(p_env jsonb) RETURNS int
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN (SELECT count(*) FROM jsonb_array_elements(v13_gap(p_env)) g
           WHERE g.value->>'signal' LIKE 'chunk::%'
             AND EXISTS (SELECT 1 FROM chunks c
                          WHERE c.content_hash = substr(g.value->>'signal', 8)));
END $$;

-- 全集体在场守卫(存在性键-态绑定):存在性键覆盖冻结候选全集,其 state
-- 就必须以全集体为载荷——任一候选体缺(parse→resolve 窗口内 chunks 行被
-- 删:手动 DELETE/gc delete 皆 DP4 合法路径)→ resolve filter 面本 pass
-- 整体跳过:存在性不问不缓存不消费(全集键下问出的是缺体「无答案」,会
-- 经缓存回流封死同体重摄取后的新证据——F2 死法侧门)、过滤行剔出
-- remaining;下一信封自然收敛。空候选集恒过(信封 B3 已不产存在性行,
-- 双保险)。查找语义与存在性 state 构造同款(chunks 按 content_hash)。
CREATE FUNCTION v13_filter_bodies_present(p_env jsonb) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_env->'candidates') cand
                      WHERE NOT EXISTS (SELECT 1 FROM chunks c
                                         WHERE c.content_hash =
                                               cand->>'content_hash'));
$$;

-- 单候选终局动作(F1 trace 的芯;装配 judgments/未来 sections 共用):
-- 已答→score 带(conf 低=review 带→defaults.review;score>=include_lo→
-- include;否则 exclude);行在未答(status failed/open)=timeout 态;
-- 无行→闸证据优先(存在性已答确信无→exclude),再→defaults.missing。
-- basis 词表:{decision,decision_review,default_timeout,gate_closed,
-- default_missing}——F1 三态的可观测区分面。
CREATE FUNCTION v13_chunk_filter_action(p_sid uuid, p_goal_hash text,
                                        p_candidates_digest text,
                                        p_chunk_hash text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE d record; v_pol jsonb; v_score numeric; v_conf numeric;
        v_lo numeric; v_conf_lo numeric; v_ans jsonb;
BEGIN
  v_pol := v13_policy('chunk_filter');
  IF v_pol IS NULL
     OR jsonb_typeof(v_pol->'score_include_lo') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'score_conf_lo') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'gate_closed_hi') IS DISTINCT FROM 'number'
     OR jsonb_typeof(v_pol->'gate_open_lo') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy shape'
      USING ERRCODE = 'V3006';
  END IF;
  v_lo := (v_pol->>'score_include_lo')::numeric;
  v_conf_lo := (v_pol->>'score_conf_lo')::numeric;
  IF v_lo < 0 OR v_lo > 3 OR v_conf_lo < 0 OR v_conf_lo > 1 THEN
    RAISE EXCEPTION 'v13: invalid chunk_filter policy values'
      USING ERRCODE = 'V3006';
  END IF;
  SELECT * INTO d FROM decisions
   WHERE session_id = p_sid AND signal = 'chunk::' || p_chunk_hash
     AND context = v13_filter_ref(p_goal_hash, p_chunk_hash)
   LIMIT 1;
  IF FOUND AND d.answer IS NOT NULL THEN
    v_conf  := (d.answer->>'confidence')::numeric;
    v_score := (d.answer->>'score')::numeric;
    IF v_conf < v_conf_lo THEN
      RETURN jsonb_build_object('decision_id', d.decision_id,
        'action', v13_filter_defaults_action('chunk_score', 'review'),
        'basis', 'decision_review');
    ELSIF v_score >= v_lo THEN
      RETURN jsonb_build_object('decision_id', d.decision_id,
        'action', 'include', 'basis', 'decision');
    ELSE
      RETURN jsonb_build_object('decision_id', d.decision_id,
        'action', 'exclude', 'basis', 'decision');
    END IF;
  ELSIF FOUND THEN
    RETURN jsonb_build_object('decision_id', NULL::uuid,
      'action', v13_filter_defaults_action('chunk_score', 'timeout'),
      'basis', 'default_timeout');
  END IF;
  SELECT a.answer INTO v_ans FROM decisions a
   WHERE a.session_id = p_sid AND a.signal = 'corpus_exists'
     AND a.context = jsonb_build_object('query_content_hash', p_goal_hash,
                                        'candidates_digest', p_candidates_digest)
     AND a.answer IS NOT NULL AND a.status IN ('answered','cached')
   LIMIT 1;
  IF v_ans IS NOT NULL AND v13_existence_action(v_ans) = 'exclude' THEN
    RETURN jsonb_build_object('decision_id', NULL::uuid,
      'action', 'exclude', 'basis', 'gate_closed');
  END IF;
  RETURN jsonb_build_object('decision_id', NULL::uuid,
    'action', v13_filter_defaults_action('chunk_score', 'missing'),
    'basis', 'default_missing');
END $$;

-- 候选级过滤 trace(DP3 契约「默认动作的 trace 载体=你的候选级消费段设计」
-- 的落点;F1 毒化 gate 的断言面;DP7 sections/运维的输入)。
CREATE FUNCTION v13_filter_trace(p_sid uuid)
RETURNS TABLE(content_hash text, decision_id uuid, action text, basis text)
LANGUAGE plpgsql STABLE AS $$
DECLARE v_gh text; v_dig text; v_cands jsonb; r record; v_a jsonb;
BEGIN
  v_cands := v13_recall_candidates(p_sid)->'candidates';
  v_gh := v13_goal_hash(p_sid);
  v_dig := v13_candidates_digest(v_cands);
  FOR r IN SELECT cand->>'content_hash' AS h
             FROM jsonb_array_elements(v_cands) cand LOOP
    v_a := v13_chunk_filter_action(p_sid, v_gh, v_dig, r.h);
    content_hash := r.h;
    decision_id  := (v_a->>'decision_id')::uuid;
    action       := v_a->>'action';
    basis        := v_a->>'basis';
    RETURN NEXT;
  END LOOP;
END $$;

-- === L3 过滤族 ask 宏(存在性批与 per-chunk 批共用;α/β/calls/cache/
--     γ'/落行与 DP2 §3.6 逐字同款;行序=signal 升序=hash 升序——不变量 7
--     的落行循环半边,与 consult/fbatch 两处合成三处 ORDER BY) ===
CREATE FUNCTION v13_filter_ask(p_env jsonb, p_state jsonb, p_rows jsonb,
                               p_label text) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_sid uuid := (p_env->>'sid')::uuid;
  v_payload jsonb; v_resp jsonb; v_usage jsonb; v_t0 timestamptz;
  v_hash text; v_canon jsonb; v_valid boolean; v_call uuid;
  v_tmpl jsonb; v_asked int := 0; v_landed int := 0; v_rejects int := 0;
  r record;
BEGIN
  v_payload := jsonb_build_object('state', p_state, 'questions',
    (SELECT jsonb_object_agg(q->>'signal',
                    v13_question_wire(q->>'kind', q->>'question', q->'criteria'))
       FROM jsonb_array_elements(p_rows) q));
         -- 同一 builder(DP2 不变量 2):题面同出 v13_question_wire;
         -- state=批态原物(chunk 投影,经 v13_project_state 于调用侧执法)
  IF p_env->>'timeout_ms' IS NOT NULL THEN
    EXECUTE format('SET LOCAL typesafe.timeout_ms = %L', p_env->>'timeout_ms');
  END IF;
  v_t0 := clock_timestamp();

  -- (α) ask 边界【DP2 §3.6 α 分类门逐字;engine fact:本仓 pg_typesafe
  --     HTTP 等待不可被 statement_timeout 中断,已声明分类的取消按
  --     DP1 turn 7 #45(b) 家族裁决经 V3001 β 路径兑现(README 台账)】
  BEGIN
    v_resp := typesafe_ask(v_payload->'state', v_payload->'questions');
  EXCEPTION
    WHEN query_canceled THEN
      IF coalesce(current_setting('statement_timeout', true), '0')
           IN ('0', '0ms') THEN
        RAISE;
      END IF;
      INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                  projection_key, payload, payload_hash,
                                  provider, model, question_count,
                                  timeout_ms, latency_ms, status, error)
      VALUES (v_sid, p_env->>'candidate_set_hash', p_label, v_payload,
              encode(digest(v_payload::text, 'sha256'), 'hex'),
              p_env->>'provider', p_env->>'model',
              jsonb_array_length(p_rows), NULLIF(p_env->>'timeout_ms', '')::int,
              (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
              'failed_timeout', SQLSTATE);
      RETURN jsonb_build_object('asked', 0, 'landed', 0, 'rejects', 0,
                                'failed', true);
    WHEN OTHERS THEN
      RAISE;
  END;
  v_usage := v_resp->'usage';

  -- (β) 校验先行【DP2 §3.6 β 逐字:只捕 V3001;malformed 拒收整批】
  BEGIN
    IF jsonb_typeof(v_resp->'answers') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'v13: response needs an answers object'
        USING ERRCODE = 'V3001';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_object_keys(v_resp->'answers') k
                WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_rows) q
                                   WHERE q->>'signal' = k)) THEN
      RAISE EXCEPTION 'v13: response contains unknown answer signals'
        USING ERRCODE = 'V3001';
    END IF;
    FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                    q->'criteria' AS criteria
               FROM jsonb_array_elements(p_rows) q LOOP
      PERFORM v13_validate_answer(r.kind, v_resp->'answers'->r.signal,
                                  r.criteria);
    END LOOP;
  EXCEPTION WHEN SQLSTATE 'V3001' THEN
    INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                projection_key, payload, payload_hash,
                                provider, model, question_count, timeout_ms,
                                usage, latency_ms, status, error)
    VALUES (v_sid, p_env->>'candidate_set_hash', p_label, v_payload,
            encode(digest(v_payload::text, 'sha256'), 'hex'),
            p_env->>'provider', p_env->>'model',
            jsonb_array_length(p_rows), NULLIF(p_env->>'timeout_ms', '')::int,
            v_usage,
            (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
            'failed_validation', 'V3001: ' || SQLERRM);
    RETURN jsonb_build_object('asked', 0, 'landed', 0, 'rejects', 0,
                              'failed', true);
  END;

  -- 成功调用落行
  INSERT INTO judgment_calls (call_id, session_id, candidate_set_hash,
                              projection_key, payload, payload_hash,
                              provider, model, question_count, timeout_ms,
                              usage, latency_ms, status)
  VALUES (gen_random_uuid(), v_sid, p_env->>'candidate_set_hash', p_label,
          v_payload, encode(digest(v_payload::text, 'sha256'), 'hex'),
          p_env->>'provider', p_env->>'model',
          jsonb_array_length(p_rows), NULLIF(p_env->>'timeout_ms', '')::int,
          v_usage,
          (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
          'succeeded')
  RETURNING call_id INTO v_call;

  -- canonical upsert + read-back + (γ') 复校 + decisions 落行
  -- (DP2 §3.6 步 5 逐字;context=v13_row_context 族分发——过滤行=ref 原物;
  -- 落行循环按 signal 升序=不变量 7 的批写锁纪律)
  FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                  q->>'question' AS question, q->'criteria' AS criteria,
                  q->>'template_name' AS tname
             FROM jsonb_array_elements(p_rows) q
            ORDER BY q->>'signal' LOOP
    v_hash := v13_judgment_hash(p_env, r.signal, r.kind, r.question,
                                r.criteria);
    v_tmpl := p_env->'templates'->r.tname;
    INSERT INTO judgment_cache (request_hash, signal, kind, answer,
                                provider, model, template_name,
                                template_version, answer_schema_version,
                                call_id)
    VALUES (v_hash, r.signal, r.kind, v_resp->'answers'->r.signal,
            p_env->>'provider', p_env->>'model', r.tname,
            (v_tmpl->>'version')::int,
            (v_tmpl->>'answer_schema_version')::int, v_call)
    ON CONFLICT (request_hash) DO NOTHING;
    SELECT c.answer INTO v_canon FROM judgment_cache c
     WHERE c.request_hash = v_hash;
    v_valid := true;
    BEGIN
      PERFORM v13_validate_answer(r.kind, v_canon, r.criteria);
    EXCEPTION WHEN SQLSTATE 'V3001' THEN
      v_valid := false;
    END;
    IF NOT v_valid THEN
      v_rejects := v_rejects + 1;
      v_asked := v_asked + 1;
      CONTINUE;
    END IF;
    INSERT INTO decisions (session_id, signal, kind, question, criteria,
                           context, answer, provider, model, request_hash,
                           status, answered_at, template_name,
                           template_version, answer_schema_version,
                           reused_from, call_id)
    VALUES (v_sid, r.signal, r.kind, r.question, r.criteria,
            v13_row_context(p_env, r.signal),
            v_canon, p_env->>'provider', p_env->>'model', v_hash,
            'answered', now(), r.tname, (v_tmpl->>'version')::int,
            (v_tmpl->>'answer_schema_version')::int, NULL, v_call)
    ON CONFLICT (session_id, request_hash) DO UPDATE
      SET answer = EXCLUDED.answer
      WHERE decisions.answer IS NULL;
    v_asked := v_asked + 1;
    v_landed := v_landed + 1;
  END LOOP;
  RETURN jsonb_build_object('asked', v_asked, 'landed', v_landed,
                            'rejects', v_rejects, 'failed', false);
END $$;

-- === L4 墓碑一:v13_judgment_hash OR REPLACE(DP2 §3.5 体;唯一增量=
--     v13_group_state 改经 v13_row_context——canonical 信号逐字节不变,
--     分支仅 corpus_exists/chunk::% 两处,不变量 2) ===
CREATE OR REPLACE FUNCTION v13_judgment_hash(p_env jsonb, p_signal text,
                            p_kind text, p_question text, p_criteria jsonb)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE v_item jsonb;
BEGIN
  SELECT n INTO v_item
    FROM jsonb_array_elements(p_env->'needed') n
   WHERE n->>'signal' = p_signal;
  IF v_item IS NULL THEN
    RAISE EXCEPTION 'v13: signal % is absent from envelope', p_signal
      USING ERRCODE = 'V3002';
  END IF;
  IF v_item->>'kind' IS DISTINCT FROM p_kind
     OR v_item->>'question' IS DISTINCT FROM p_question
     OR v_item->'criteria' IS DISTINCT FROM p_criteria THEN
    RAISE EXCEPTION 'v13: hash arguments drift from frozen envelope for %',
      p_signal USING ERRCODE = 'V3002';
  END IF;
  RETURN v13_request_hash(p_signal, p_kind, p_question, p_criteria,
         v13_row_context(p_env, p_signal),
         p_env->>'provider', p_env->>'model');
END $$;

-- === L5 墓碑二:v13_judgment_envelope OR REPLACE(DP5 §3.1 L6 二十键体的
--     DP6 形态;实施纪律:自 v13/recall/v13_recall.sql 加载态原文机械复制,
--     仅四处 [DP6] 增量:①rc/tmpl CTE 前移;②fg 守卫;③frows 过滤行合并
--     进 needed;④groups 过滤 canonical 行。20 键集零增删,csh 公式不变
--     (needed 内容自然扩入)。 ===
CREATE OR REPLACE FUNCTION v13_judgment_envelope(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH runtime AS MATERIALIZED (
    SELECT v13_guc_required('typesafe.provider') AS provider,
           v13_guc_required('typesafe.model') AS model),
  ctx AS MATERIALIZED (
    SELECT v13_canonical_state(p_sid) AS c),
  rc AS MATERIALIZED (                       -- 【DP6①】自 wm/pol 前移
    SELECT v13_recall_candidates(p_sid) AS r),
  tmpl AS MATERIALIZED (
    SELECT coalesce(jsonb_object_agg(t.template_name, jsonb_build_object(
             'version', t.template_version, 'kind', t.kind,
             'question', t.question, 'criteria', t.criteria,
             'projection', t.projection,
             'answer_schema_version', t.answer_schema_version)), '{}'::jsonb) AS t
      FROM v13_template_latest t),
  fg AS MATERIALIZED (                       -- 【DP6②】过滤族模板在岗守卫
    SELECT v13_require_filter_templates((SELECT t FROM tmpl)) AS g),
  frows AS MATERIALIZED (                    -- 【DP6③】过滤行(消费 rc 冻结
    SELECT coalesce(jsonb_agg(f ORDER BY f->>'signal'), '[]'::jsonb) AS f -- 候选;DISTINCT ON
      FROM ((SELECT jsonb_build_object(           -- content_hash 去重=跨源
                     'signal', 'corpus_exists',   -- 同文一行,判断缓存语义)
                     'kind', (SELECT t FROM tmpl)->'corpus_exists'->>'kind',
                     'question',
                       (SELECT t FROM tmpl)->'corpus_exists'->>'question',
                     'criteria',
                       (SELECT t FROM tmpl)->'corpus_exists'->'criteria',
                     'template_name', 'corpus_exists') AS f
              FROM fg
             WHERE jsonb_array_length(
                     coalesce((SELECT r FROM rc)->'candidates',
                              '[]'::jsonb)) > 0)
            UNION ALL
            (SELECT DISTINCT ON (cand->>'content_hash')
                    jsonb_build_object(
                     'signal', 'chunk::' || (cand->>'content_hash'),
                     'kind', (SELECT t FROM tmpl)->'chunk_score'->>'kind',
                     'question',
                       (SELECT t FROM tmpl)->'chunk_score'->>'question',
                     'criteria',
                       (SELECT t FROM tmpl)->'chunk_score'->'criteria',
                     'template_name', 'chunk_score') AS f
               FROM fg,
                    jsonb_array_elements(
                      coalesce((SELECT r FROM rc)->'candidates',
                               '[]'::jsonb)) cand
              ORDER BY cand->>'content_hash')) s),
  needed AS MATERIALIZED (                   -- 【DP6③】基族 ∪ 过滤行(signal
    SELECT coalesce(jsonb_agg(               -- 升序聚合;CASE 省 criteria 键
             CASE WHEN x.criteria IS NULL THEN   -- 形态与 DP2/DP5 同构)
               jsonb_build_object('signal', x.signal, 'kind', x.kind,
                                  'question', x.question,
                                  'template_name', x.template_name)
             ELSE
               jsonb_build_object('signal', x.signal, 'kind', x.kind,
                                  'question', x.question, 'criteria', x.criteria,
                                  'template_name', x.template_name)
             END ORDER BY x.signal), '[]'::jsonb) AS n
      FROM (SELECT signal, kind, question, criteria, template_name
              FROM v13_needed_judgments(p_sid)
             UNION ALL
            SELECT f->>'signal', f->>'kind', f->>'question',
                   NULLIF(f->'criteria', 'null'::jsonb),
                   f->>'template_name'
              FROM jsonb_array_elements((SELECT f FROM frows)) f) x),
  groups AS MATERIALIZED (                   -- 【DP6④】仅 canonical 行(过滤
    SELECT coalesce(jsonb_agg(jsonb_build_object('projection_key', s.pkey, -- 族的组态
                                                 'state', s.state)      -- 在 resolve 侧构建,
                              ORDER BY s.pkey), '[]'::jsonb) AS g        -- 信封不携体)
      FROM (SELECT DISTINCT
              v13_projection_key(
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS pkey,
              v13_project_state(
                (SELECT c FROM ctx),
                (SELECT t FROM tmpl) -> (nr.value->>'template_name')
                -> 'projection') AS state
              FROM jsonb_array_elements((SELECT n FROM needed)) nr
             WHERE (nr.value->>'template_name')
                   NOT IN ('chunk_score','corpus_exists')) s),
  wm AS MATERIALIZED (
    SELECT (SELECT next_seq FROM sessions WHERE session_id = p_sid) AS sv,
           coalesce((SELECT max(seq) FROM events
                      WHERE session_id = p_sid), -1) AS mes),
  pol AS MATERIALIZED (
    SELECT route_policy_name AS rpn, route_policy_version AS rpv
      FROM sessions WHERE session_id = p_sid)
  SELECT jsonb_build_object(
    'sid', p_sid,
    'ctx', (SELECT c FROM ctx),
    'needed', (SELECT n FROM needed),
    'templates', (SELECT t FROM tmpl),
    'groups', (SELECT g FROM groups),
    'timeout_ms', NULLIF(current_setting('typesafe.timeout_ms', true), ''),
    'budget', v13_policy('resolve_fast_path'),
    'candidate_set_hash',
      encode(digest(jsonb_build_object(
        'needed', (SELECT n FROM needed),
        'recall', (SELECT r FROM rc))::text, 'sha256'), 'hex'),
    'goal_hash', v13_goal_hash(p_sid),
    'provider', (SELECT provider FROM runtime),
    'model',    (SELECT model FROM runtime),
    'route_policy_name',     (SELECT rpn FROM pol),
    'route_policy_version',  (SELECT rpv FROM pol),
    'tools_revision', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'tools_catalog',  v13_tools_catalog_frozen(),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta WHERE singleton),
    'session_version', (SELECT sv FROM wm),
    'max_event_seq',   (SELECT mes FROM wm),
    'needed_count', jsonb_array_length((SELECT n FROM needed)),
    'candidates', (SELECT r->'candidates' FROM rc));
$$;

-- === L6 墓碑三:v13_resolve_judgments OR REPLACE(DP2 §3.6 体的 DP6 形态;
--     canonical 半边逐字保留[组选择/批选择加 NOT IN 腰带],filter 半边新增。
--     实施纪律:自 v13/envelope/v13_envelope.sql 加载态原文机械复制+增量。
--     worker 契约零改动:慢路仍是 claim→resolve(env,1)→renew→complete。 ===
CREATE OR REPLACE FUNCTION v13_resolve_judgments(p_env jsonb,
                                                 p_max_batches int DEFAULT 1)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_sid    uuid := (p_env->>'sid')::uuid;
  v_bs     int;
  v_asked  int := 0; v_batches int := 0; v_hits int := 0;
  v_rejects int := 0;
  v_landed int := 0;
  v_failed boolean := false;
  v_rem    int;
  v_gap    jsonb; v_pkey text; v_state jsonb;
  v_batch  jsonb; v_payload jsonb; v_resp jsonb; v_usage jsonb;
  v_hash   text; v_canon jsonb; v_valid boolean; v_call uuid;
  v_tname  text; v_tmpl jsonb; v_res jsonb;
  v_t0     timestamptz; v_err text; r record;
  v_goal   text; v_fstate jsonb; v_frows jsonb; v_label text;
BEGIN
  IF p_max_batches IS NULL OR p_max_batches < 1 THEN
    RAISE EXCEPTION 'v13: p_max_batches must be >= 1 (unbounded = caller loop)';
  END IF;
  v_bs := (p_env->'budget'->>'batch_questions')::int;
  IF v_bs IS NULL OR v_bs < 1 THEN
    RAISE EXCEPTION
      'v13: envelope budget.batch_questions missing or invalid (%)', v_bs
      USING ERRCODE = 'V3002';
  END IF;

  IF jsonb_array_length(v13_gap(p_env)) > 0 THEN
    PERFORM pg_advisory_xact_lock(
      v13_lock_key(v_sid, p_env->>'candidate_set_hash'));
  END IF;

  LOOP
    v_gap := v13_gap(p_env);
    EXIT WHEN jsonb_array_length(v_gap) = 0 OR v_batches >= p_max_batches;

    -- (1) canonical consult(DP2 逐字;context 经 v13_row_context 族分发
    --     ——过滤行缓存命中=reused_from 跨 session 复用半边,G-ctx4-3)
    FOR r IN SELECT g.value AS q FROM jsonb_array_elements(v_gap) g
              ORDER BY g.value->>'signal' LOOP
      v_hash := v13_judgment_hash(p_env, r.q->>'signal', r.q->>'kind',
                                  r.q->>'question', r.q->'criteria');
      v_canon := NULL; v_valid := false;
      SELECT c.answer INTO v_canon FROM judgment_cache c
       WHERE c.request_hash = v_hash;
      IF FOUND THEN
        BEGIN
          PERFORM v13_validate_answer(r.q->>'kind', v_canon, r.q->'criteria');
          v_valid := true;
        EXCEPTION WHEN SQLSTATE 'V3001' THEN
          v_valid := false;
        END;
      END IF;
      IF v_valid THEN
        v_tname := r.q->>'template_name';
        v_tmpl := p_env->'templates'->v_tname;
        INSERT INTO decisions (session_id, signal, kind, question, criteria,
                               context, answer, provider, model, request_hash,
                               status, answered_at, template_name,
                               template_version, answer_schema_version,
                               reused_from, call_id)
        VALUES (v_sid, r.q->>'signal', r.q->>'kind', r.q->>'question',
                r.q->'criteria', v13_row_context(p_env, r.q->>'signal'),
                v_canon, p_env->>'provider', p_env->>'model', v_hash,
                'cached', now(), v_tname, (v_tmpl->>'version')::int,
                (v_tmpl->>'answer_schema_version')::int, v_hash, NULL)
        ON CONFLICT (session_id, request_hash) DO UPDATE
          SET answer = EXCLUDED.answer
          WHERE decisions.answer IS NULL;
        v_hits := v_hits + 1;
      END IF;
    END LOOP;

    v_gap := v13_gap(p_env);
    EXIT WHEN jsonb_array_length(v_gap) = 0 OR v_batches >= p_max_batches;

    -- (2) canonical 组选择(DP2+腰带:仅 canonical 行——过滤族组态不进信封
    --     groups,其 projection pkey 与 canonical 族无碰撞但显式排除防依赖)
    SELECT min(v13_projection_key(
             p_env->'templates'->(g.value->>'template_name')->'projection'))
      INTO v_pkey
      FROM jsonb_array_elements(v_gap) g
     WHERE (g.value->>'template_name')
           NOT IN ('chunk_score','corpus_exists');

    IF v_pkey IS NOT NULL THEN
      -- (3)-(8) canonical 批(DP2 §3.6 逐字;批选择加同款 NOT IN 腰带)
      SELECT gg->'state' INTO v_state
        FROM jsonb_array_elements(p_env->'groups') gg
       WHERE gg->>'projection_key' = v_pkey;
      IF v_state IS NULL THEN
        RAISE EXCEPTION 'v13: group state % missing from envelope', v_pkey
          USING ERRCODE = 'V3002';
      END IF;
      SELECT jsonb_agg(q ORDER BY q->>'signal') INTO v_batch
        FROM (SELECT g.value AS q FROM jsonb_array_elements(v_gap) g
               WHERE (g.value->>'template_name')
                     NOT IN ('chunk_score','corpus_exists')
                 AND v13_projection_key(
                       p_env->'templates'->(g.value->>'template_name')
                       -> 'projection') = v_pkey
               ORDER BY g.value->>'signal' LIMIT v_bs) s;
      v_payload := jsonb_build_object('state', v_state, 'questions',
        (SELECT jsonb_object_agg(q->>'signal',
                      v13_question_wire(q->>'kind', q->>'question',
                                        q->'criteria'))
           FROM jsonb_array_elements(v_batch) q));
      IF p_env->>'timeout_ms' IS NOT NULL THEN
        EXECUTE format('SET LOCAL typesafe.timeout_ms = %L', p_env->>'timeout_ms');
      END IF;
      v_t0 := clock_timestamp();
      BEGIN
        v_resp := typesafe_ask(v_payload->'state', v_payload->'questions');
      EXCEPTION
        WHEN query_canceled THEN
          IF coalesce(current_setting('statement_timeout', true), '0')
               IN ('0', '0ms') THEN
            RAISE;
          END IF;
          INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                      projection_key, payload, payload_hash,
                                      provider, model, question_count,
                                      timeout_ms, latency_ms, status, error)
          VALUES (v_sid, p_env->>'candidate_set_hash', v_pkey, v_payload,
                  encode(digest(v_payload::text, 'sha256'), 'hex'),
                  p_env->>'provider', p_env->>'model',
                  jsonb_array_length(v_batch),
                  NULLIF(p_env->>'timeout_ms', '')::int,
                  (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
                  'failed_timeout', SQLSTATE);
          v_failed := true; EXIT;
        WHEN OTHERS THEN
          RAISE;
      END;
      v_usage := v_resp->'usage';
      BEGIN
        IF jsonb_typeof(v_resp->'answers') IS DISTINCT FROM 'object' THEN
          RAISE EXCEPTION 'v13: response needs an answers object'
            USING ERRCODE = 'V3001';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(v_resp->'answers') k
                    WHERE NOT EXISTS (SELECT 1
                                        FROM jsonb_array_elements(v_batch) q
                                       WHERE q->>'signal' = k)) THEN
          RAISE EXCEPTION 'v13: response contains unknown answer signals'
            USING ERRCODE = 'V3001';
        END IF;
        FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                        q->'criteria' AS criteria
                   FROM jsonb_array_elements(v_batch) q LOOP
          PERFORM v13_validate_answer(r.kind, v_resp->'answers'->r.signal,
                                      r.criteria);
        END LOOP;
      EXCEPTION WHEN SQLSTATE 'V3001' THEN
        GET STACKED DIAGNOSTICS v_err = MESSAGE_TEXT;
        INSERT INTO judgment_calls (session_id, candidate_set_hash,
                                    projection_key, payload, payload_hash,
                                    provider, model, question_count, timeout_ms,
                                    usage, latency_ms, status, error)
        VALUES (v_sid, p_env->>'candidate_set_hash', v_pkey, v_payload,
                encode(digest(v_payload::text, 'sha256'), 'hex'),
                p_env->>'provider', p_env->>'model',
                jsonb_array_length(v_batch), NULLIF(p_env->>'timeout_ms', '')::int,
                v_usage,
                (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
                'failed_validation', 'V3001: ' || v_err);
        v_failed := true; EXIT;
      END;
      INSERT INTO judgment_calls (call_id, session_id, candidate_set_hash,
                                  projection_key, payload, payload_hash,
                                  provider, model, question_count, timeout_ms,
                                  usage, latency_ms, status)
      VALUES (gen_random_uuid(), v_sid, p_env->>'candidate_set_hash', v_pkey,
              v_payload, encode(digest(v_payload::text, 'sha256'), 'hex'),
              p_env->>'provider', p_env->>'model',
              jsonb_array_length(v_batch), NULLIF(p_env->>'timeout_ms', '')::int,
              v_usage,
              (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int,
              'succeeded')
      RETURNING call_id INTO v_call;
      v_landed := 0;
      FOR r IN SELECT q->>'signal' AS signal, q->>'kind' AS kind,
                      q->>'question' AS question, q->'criteria' AS criteria,
                      q->>'template_name' AS tname
                 FROM jsonb_array_elements(v_batch) q LOOP
        v_hash := v13_judgment_hash(p_env, r.signal, r.kind, r.question,
                                    r.criteria);
        v_tmpl := p_env->'templates'->r.tname;
        INSERT INTO judgment_cache (request_hash, signal, kind, answer,
                                    provider, model, template_name,
                                    template_version, answer_schema_version,
                                    call_id)
        VALUES (v_hash, r.signal, r.kind, v_resp->'answers'->r.signal,
                p_env->>'provider', p_env->>'model', r.tname,
                (v_tmpl->>'version')::int,
                (v_tmpl->>'answer_schema_version')::int, v_call)
        ON CONFLICT (request_hash) DO NOTHING;
        SELECT c.answer INTO v_canon FROM judgment_cache c
         WHERE c.request_hash = v_hash;
        v_valid := true;
        BEGIN
          PERFORM v13_validate_answer(r.kind, v_canon, r.criteria);
        EXCEPTION WHEN SQLSTATE 'V3001' THEN
          v_valid := false;
        END;
        IF NOT v_valid THEN
          v_rejects := v_rejects + 1;
          v_asked := v_asked + 1;
          CONTINUE;
        END IF;
        INSERT INTO decisions (session_id, signal, kind, question, criteria,
                               context, answer, provider, model, request_hash,
                               status, answered_at, template_name,
                               template_version, answer_schema_version,
                               reused_from, call_id)
        VALUES (v_sid, r.signal, r.kind, r.question, r.criteria, v_state,
                v_canon, p_env->>'provider', p_env->>'model', v_hash,
                'answered', now(), r.tname, (v_tmpl->>'version')::int,
                (v_tmpl->>'answer_schema_version')::int, NULL, v_call)
        ON CONFLICT (session_id, request_hash) DO UPDATE
          SET answer = EXCLUDED.answer
          WHERE decisions.answer IS NULL;
        v_asked := v_asked + 1;
        v_landed := v_landed + 1;
      END LOOP;
      v_batches := v_batches + 1;
      IF v_landed = 0 THEN
        v_failed := true; EXIT;      -- no-progress(DP2 步(8) 逐字)
      END IF;
    ELSE
      -- (9) DP6 filter 面:存在性先行 → 闸 → per-chunk 批(OQ3/OQ4)
      -- 【体缺守卫(键-态绑定)】候选全集体在场(v13_filter_bodies_present,
      -- 与存在性 state 构造同款查找):任一体缺 → 本 pass 整个 filter 面
      -- 跳过——存在性不问(全集键下缺体问出的「无答案」会经缓存回流,
      -- 封死同体重摄取后的新证据)、per-chunk 不问(不变量 4 存在性严格
      -- 先行不破)、过滤行剔出 remaining(不问不缓存不消费;下一信封
      -- 自然收敛,防 worker/advance ③ 空转)。
      IF NOT v13_filter_bodies_present(p_env) THEN
        EXIT;   -- 体缺守卫:filter 面本 pass 不可填
      END IF;
      IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_gap) g
                      WHERE g.value->>'signal' = 'corpus_exists')
         AND (NOT v13_filter_gate_open(p_env)
              OR v13_filter_fillable(p_env) = 0) THEN
        EXIT;   -- 闸关或无可填 chunk 行:per-chunk 不可填,零 ask 终止(防
      END IF;    -- worker 空转;remaining 同口径,advance ③ 不再建 judge effect)
      v_goal := v13_goal_text(v_sid, p_env->>'goal_hash');
      LOOP
        EXIT WHEN v_batches >= p_max_batches;
        v_gap := v13_gap(p_env);
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(v_gap) g
                    WHERE g.value->>'signal' = 'corpus_exists') THEN
          -- 存在性批:1 问;state=查询全文+全候选体(排序去重)
          v_fstate := (SELECT v13_project_state(
                         jsonb_build_object(
                           'query', v_goal,
                           'chunks', coalesce(jsonb_agg(
                             jsonb_build_object('content_hash', x.h,
                                                'body', x.b)
                               ORDER BY x.h), '[]'::jsonb)),
                         p_env->'templates'->'corpus_exists'->'projection')
                        FROM (SELECT DISTINCT cand->>'content_hash' AS h,
                                     (SELECT c.body FROM chunks c
                                       WHERE c.content_hash =
                                             cand->>'content_hash'
                                       ORDER BY c.source_hash, c.chunk_no
                                       LIMIT 1) AS b
                                FROM jsonb_array_elements(
                                       p_env->'candidates') cand) x
                       WHERE x.b IS NOT NULL);
          -- 键-态 belt:态体基数必须等于冻结候选去重基数(右值为信封冻结
          -- 数据的纯计算,零活表读)——READ COMMITTED 下守卫与 state 构造
          -- 是两条语句级快照,竞态窗内体缺时 WHERE b IS NOT NULL 退化为静默
          -- 丢行(即 P1-2 死法);belt 拦下,视同守卫:退出过滤循环,外层
          -- 守卫以新快照复拦后整体终止,本 pass 不问不缓存。
          IF jsonb_array_length(coalesce(v_fstate->'chunks', '[]'::jsonb))
             <> (SELECT count(DISTINCT cand->>'content_hash')
                   FROM jsonb_array_elements(p_env->'candidates') cand) THEN
            EXIT;  -- 态缺体(竞态 belt):filter 面本 pass 不可填
          END IF;
          v_frows := (SELECT coalesce(jsonb_agg(
                        g.value ORDER BY g.value->>'signal'), '[]'::jsonb)
                        FROM jsonb_array_elements(v_gap) g
                       WHERE g.value->>'signal' = 'corpus_exists');
          v_label := 'corpus_exists';
        ELSIF v13_filter_gate_open(p_env) THEN
          -- per-chunk 批:≤v_bs 行(signal 升序=hash 升序,不变量 7)
          v_frows := (SELECT coalesce(jsonb_agg(
                        s.value ORDER BY s.value->>'signal'), '[]'::jsonb)
                        FROM (SELECT g.value
                                FROM jsonb_array_elements(v_gap) g
                               WHERE g.value->>'signal' LIKE 'chunk::%'
                                 AND EXISTS (SELECT 1 FROM chunks c
                                              WHERE c.content_hash =
                                                    substr(g.value->>'signal',
                                                           8))
                               ORDER BY g.value->>'signal'
                               LIMIT v_bs) s);
          EXIT WHEN jsonb_array_length(v_frows) = 0;
          v_fstate := (SELECT v13_project_state(
                         jsonb_build_object('query', v_goal, 'chunks', c.ch),
                         p_env->'templates'->'chunk_score'->'projection')
                        FROM (SELECT coalesce(jsonb_agg(
                                 jsonb_build_object(
                                   'content_hash',
                                     substr(q->>'signal', 8),
                                   'body',
                                     (SELECT c2.body FROM chunks c2
                                       WHERE c2.content_hash =
                                             substr(q->>'signal', 8)
                                       ORDER BY c2.source_hash, c2.chunk_no
                                       LIMIT 1))
                                   ORDER BY q->>'signal'), '[]'::jsonb) AS ch
                                FROM jsonb_array_elements(v_frows) q) c);
          v_label := 'chunk_score';
        ELSE
          EXIT;                      -- 闸关:per-chunk 不可填
        END IF;

        v_res := v13_filter_ask(p_env, v_fstate, v_frows, v_label);
        v_asked   := v_asked   + coalesce((v_res->>'asked')::int, 0);
        v_rejects := v_rejects + coalesce((v_res->>'rejects')::int, 0);
        v_landed  := coalesce((v_res->>'landed')::int, 0);
        v_batches := v_batches + 1;
        IF (v_res->>'failed')::boolean OR v_landed = 0 THEN
          v_failed := true; EXIT;    -- α/β 族或 no-progress(DP2 同款)
        END IF;
      END LOOP;
    END IF;
  END LOOP;

  -- remaining(闸感知+体缺感知口径):canonical 行 +(守卫过时)存在性缺口
  -- +(闸开时)可填 chunk 行;守卫不过→存在性缺口与全部过滤行剔出
  -- (本 pass 不可填,不问不缓存不消费;下一信封自然收敛,防 worker/
  -- advance ③ 空转)
  v_rem := (SELECT count(*) FROM jsonb_array_elements(v13_gap(p_env)) g
             WHERE g.value->>'signal' NOT LIKE 'chunk::%'
               AND g.value->>'signal' <> 'corpus_exists');
  IF v13_filter_bodies_present(p_env) THEN
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v13_gap(p_env)) g
                WHERE g.value->>'signal' = 'corpus_exists') THEN
      v_rem := v_rem + 1;
    END IF;
    IF v13_filter_gate_open(p_env) THEN
      v_rem := v_rem + v13_filter_fillable(p_env);
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'asked_questions', v_asked, 'asked_batches', v_batches,
    'cache_hits', v_hits, 'readback_rejects', v_rejects,
    'remaining', v_rem, 'failed', v_failed,
    'gate_open', v13_filter_gate_open(p_env));
END $$;

-- === L7 墓碑四:v13_assemble_manifest OR REPLACE(DP3 §3.4+DP5 L7 体的
--     DP6 形态;实施纪律:自 v13/recall/v13_recall.sql 加载态原文机械复制,
--     仅按 [DP6] 标注的三处增量编辑:①rc2/fc 两 CTE;②qside candidates 的
--     decision_id 填充;③jud 消费集+final_action 真值。其余 CTE 逐字不动。 ===
CREATE OR REPLACE FUNCTION v13_assemble_manifest(p_sid uuid,
                                                  p_policy_version int DEFAULT NULL)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
WITH pol AS MATERIALIZED (
  SELECT p.version,
         (p.value->>'budget_tokens')::int        AS budget,
         (p.value->>'est_bytes_per_token')::int  AS divisor,
         p.value->'priority_overrides'           AS prio_ovr,
         p.value->'kinds_disabled'               AS kinds_off,
         (SELECT q.version FROM v13_policies q
           WHERE q.name = 'judgment_defaults' AND q.active) AS jdef_ver
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
), pri AS MATERIALIZED (
  SELECT s.context_active_artifact AS aid, a.inline AS m
  FROM sessions s LEFT JOIN artifacts a ON a.artifact_id = s.context_active_artifact
  WHERE s.session_id = p_sid
), pri_sec AS MATERIALIZED (
  SELECT ps->>'section_id' AS section_id, ps->>'content_hash' AS content_hash,
         (ps->>'churn')::int AS churn
  FROM pri, jsonb_array_elements(
         CASE WHEN jsonb_typeof(pri.m->'sections') = 'array'
              THEN pri.m->'sections' ELSE '[]'::jsonb END) ps
), sec_src AS MATERIALIZED (
  SELECT 'goal'::text AS section_id, 'goal'::text AS kind,
         'Session'::text AS cache_scope, 'First'::text AS def_prio,
         v13_goal_hash(p_sid) AS content_hash,
         octet_length(coalesce((SELECT g.payload::text FROM v13_goals g
                           WHERE g.session_id = p_sid
                        ORDER BY g.seq DESC LIMIT 1), '')) AS bytes,
         coalesce((SELECT max(seq) FROM v13_goals
                    WHERE session_id = p_sid), -1) AS gseq,
         NULL::jsonb AS mat
  UNION ALL
  SELECT 'history','history','Session','Normal',
         encode(digest(coalesce((cs.c -> 'messages')::text, ''), 'sha256'),
                'hex'),
         octet_length(coalesce((cs.c -> 'messages')::text, '')),
         NULL::bigint, cs.c -> 'messages'
  FROM cs
  UNION ALL
  SELECT 'tools','tools','Global','First',
         encode(digest(coalesce((cs.c -> 'tools')::text, ''), 'sha256'), 'hex'),
         octet_length(coalesce((cs.c -> 'tools')::text, '')),
         NULL::bigint, cs.c -> 'tools'
  FROM cs
), cls AS MATERIALIZED (
  SELECT r.*,
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
  FROM sec_src r, pol
), packed AS MATERIALIZED (
  SELECT c.section_id,
         sum(c.est_tokens) OVER (ORDER BY c.prank, c.section_id
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
                     WHEN o.run_incl > pol.budget THEN
                       jsonb_build_object('applied', false,
                                          'reason', 'budget')
                     ELSE
                       jsonb_build_object('applied', true, 'name',
                         CASE o.section_id WHEN 'goal'   THEN 'verbatim'
                                           WHEN 'history' THEN 'verbatim'
                                           ELSE 'catalog_digest' END)
                   END
  ) AS section, o.prank, o.section_id
  FROM ordered o, pol
), goal_addr AS MATERIALIZED (
  SELECT coalesce((SELECT jsonb_build_object('kind','goal','seq',g.seq,
                              'content_hash',g.content_hash)
                     FROM v13_goals g WHERE g.session_id = p_sid
                 ORDER BY g.seq DESC LIMIT 1),
                  'null'::jsonb) AS a
), rc2 AS MATERIALIZED (                     -- 【DP6①】候选/digest 单源物化
  SELECT v13_recall_candidates(p_sid)->'candidates' AS cands
), fc AS MATERIALIZED (                      -- 【DP6①】goal_hash/digest 单点
  SELECT v13_goal_hash(p_sid) AS gh,
         v13_candidates_digest(v13_recall_candidates(p_sid)
                               ->'candidates') AS dig
), qside AS MATERIALIZED (                   -- 【DP6②】decision_id 填充:
  SELECT jsonb_build_object(                 -- 上下文等值 join(零哈希重算/
    'query_artifact_id', (SELECT a FROM goal_addr), -- 零 GUC/零信封依赖,
    'candidates', (SELECT coalesce(jsonb_agg(     -- 不变量 6)
                     c || jsonb_build_object('decision_id',
                       (SELECT d.decision_id FROM decisions d
                         WHERE d.session_id = p_sid
                           AND d.signal = 'chunk::' || (c->>'content_hash')
                           AND d.context =
                                 v13_filter_ref(fc.gh, c->>'content_hash')
                           AND d.answer IS NOT NULL
                           AND d.status IN ('answered','cached')
                         LIMIT 1))
                       ORDER BY (c->>'bm25')::numeric DESC,
                                c->>'content_hash' ASC), '[]'::jsonb)
                     FROM jsonb_array_elements((SELECT cands FROM rc2)) c, fc)
  ) AS q
), jud AS MATERIALIZED (                     -- 【DP6③】消费集=候选 decision_id
  SELECT coalesce(jsonb_agg("row" ORDER BY "row"->>'decision_id'), -- ∪存在性行;
             '[]'::jsonb) AS j               -- final_action 真值(DP3 词表内)
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
                         'candidates_digest',  fc.dig)))) s
), mode AS MATERIALIZED (
  SELECT CASE
           WHEN pri.m IS NULL THEN 'fresh'
           WHEN (pri.m->>'prefix_identity')
                IS DISTINCT FROM (SELECT pid FROM ident) THEN 'fresh'
           ELSE 'recompute'
         END AS m
  FROM pri
)
SELECT jsonb_build_object(
  'manifest_version', 1,
  'session_id', p_sid,
  'turn_no',   (SELECT turn_no FROM sessions WHERE session_id = p_sid),
  'prefix_identity', (SELECT pid FROM ident),
  'policy',    jsonb_build_object(
                 'assemble_version',   (SELECT version FROM pol),
                 'budget_tokens',      (SELECT budget FROM pol),
                 'est_bytes_per_token',(SELECT divisor FROM pol),
                 'judgment_defaults_version', (SELECT jdef_ver FROM pol)),
  'required_revision', (SELECT t FROM tok),
  'sections',  (SELECT coalesce(jsonb_agg(section ORDER BY prank, section_id),
                             '[]'::jsonb)
                  FROM final_sec),
  'query_side',(SELECT q FROM qside),
  'judgments', (SELECT j FROM jud),
  'replay',    jsonb_build_object('mode', (SELECT m FROM mode),
                                  'prior_artifact_id', (SELECT aid FROM pri)));
$$;

-- === L8 墓碑五:v13_chunk_referenced OR REPLACE(DP4 §3.1 体的等值换载:
--     decisions 半边 ->>'…'=' 改 containment——语义逐字节等价(行内 chunk
--     恒为恰一键对象,由 v13_filter_ref 构造半边钉死),jsonb_path_ops GIN
--     可吃;artifacts 半边逐字不动。DP4 契约「届时补该路径的 GIN 索引」
--     的使能半边,附 A #6。) ===
CREATE OR REPLACE FUNCTION v13_chunk_referenced(p_hash text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM artifacts a
                  WHERE a.kind = 'context'
                    AND a.inline->'query_side'->'candidates'
                        @> jsonb_build_array(
                             jsonb_build_object('content_hash', p_hash)))
      OR EXISTS (SELECT 1 FROM decisions d
                  WHERE d.context->'chunk'
                        @> jsonb_build_object('content_hash', p_hash));
$$;

-- === L9 索引(§1.1 形态⑥:纯追加,零 DDL/约束改动) ===
-- 体按哈希查找的读路径索引(过滤面热路径;k≤64 次/resolve;DP4 建表时
-- content_hash 无索引——非唯一,跨源同文双行合法)
CREATE INDEX ix_chunks_content_hash ON chunks (content_hash);
-- DP4 契约「届时补该路径的 GIN 索引」:decisions.context->'chunk' 子对象
-- 的 containment 探测(v13_chunk_referenced 消费面背书)
CREATE INDEX ix_decisions_chunk_ref ON decisions
  USING gin ((context->'chunk')) WHERE context->'chunk' IS NOT NULL;

-- === L10 种子(版本父表机制,DP2 §3.8 先例;cgr 断言一律相对比较) ===
INSERT INTO v13_judgment_template_versions (template_name, template_version)
VALUES ('corpus_exists', 1), ('chunk_score', 1);

INSERT INTO judgment_templates (template_name, template_version, kind,
                                question, criteria, answer_schema_version,
                                projection, provider, model, writer,
                                wire_version, canon_version, epoch) VALUES
('corpus_exists', 1, 'noul',
 'Given `state.query` (the user request) and `state.chunks` (the retrieved passages), does the corpus contain information that can answer the request?',
 NULL, 1, '["query","chunks"]'::jsonb, NULL, NULL, 'v13_resolve', 1, 1,
 'pre-finalize'),
('chunk_score', 1, 'score',
 'Given `state.query` (the user request), rate how relevant the passage in `state.chunks` keyed by this question signal is to answering the request.',
 jsonb_build_array(
   'Not relevant: unrelated to the request.',
   'Marginally relevant: touches the topic but does not help answer.',
   'Relevant: supports a partial answer.',
   'Directly relevant: contains content that directly answers the request.'),
 1, '["query","chunks"]'::jsonb, NULL, NULL, 'v13_resolve', 1, 1,
 'pre-finalize');

UPDATE v13_judgment_template_versions SET state='frozen'
 WHERE template_name IN ('corpus_exists','chunk_score')
   AND template_version = 1;
   -- freeze 触发器检查内容行在场(✓ 均已插)+行级 cgr ×2

INSERT INTO v13_policies (name, version, value, active) VALUES
('chunk_filter', 1,
 '{"gate_closed_hi":0.30,"gate_open_lo":0.40,"score_include_lo":2,"score_conf_lo":0.50}'::jsonb,
 true);
   -- 闸带/评分带(OQ6;v1 与 chunk_score v1 四级 rubric 配套:翻版=两行同批)

-- judgment_defaults v2:填 F1 两点(OQ6 方向;DP3 契约「DP6 填值」)。
-- 翻 active 顺序=turn 10 #64 纪律:先 INSERT inactive→双 UPDATE 翻;
-- jdef_ver 1→2 ⇒ 全域恰一次 refresh(DP3 OQ1 既判语义,gate 断言)。
INSERT INTO v13_policies (name, version, value, active) VALUES
('judgment_defaults', 2,
 '{"points":{"chunk_score":{"missing":"include","timeout":"include","review":"degrade"},"corpus_exists":{"missing":"include","timeout":"include","review":"include"}},"actions":["include","exclude","degrade","fail"]}'::jsonb,
 false);
UPDATE v13_policies SET active=false
 WHERE name='judgment_defaults' AND version=1;
UPDATE v13_policies SET active=true
 WHERE name='judgment_defaults' AND version=2;

-- === L11 ACL 全量块(文件真末尾;不变量 10) ===
REVOKE EXECUTE ON FUNCTION
  v13_candidates_digest(jsonb),
  v13_filter_ref(text,text), v13_existence_ref(jsonb),
  v13_row_context(jsonb,text), v13_require_filter_templates(jsonb),
  v13_goal_text(uuid,text), v13_filter_defaults_action(text,text),
  v13_existence_action(jsonb), v13_filter_gate_open(jsonb),
  v13_filter_fillable(jsonb), v13_filter_bodies_present(jsonb),
  v13_chunk_filter_action(uuid,text,text,text),
  v13_filter_trace(uuid), v13_filter_ask(jsonb,jsonb,jsonb,text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_candidates_digest(jsonb),
  v13_filter_ref(text,text), v13_existence_ref(jsonb),
  v13_row_context(jsonb,text), v13_require_filter_templates(jsonb),
  v13_goal_text(uuid,text),
  v13_chunk_filter_action(uuid,text,text,text),
  v13_filter_trace(uuid)
TO v13_recall, v13_resolve, v13_route;
             -- 纯读/审计/装配链三角色(trace=审计面;chunk_filter_action=
             -- 装配 jud CTE 与 trace 共用;row_context 在 judgment_hash
             -- 链上——三角色既有 judgment_hash 消费面同款)
GRANT EXECUTE ON FUNCTION
  v13_filter_defaults_action(text,text), v13_existence_action(jsonb),
  v13_filter_gate_open(jsonb), v13_filter_fillable(jsonb),
  v13_filter_bodies_present(jsonb),
  v13_filter_ask(jsonb,jsonb,jsonb,text)
TO v13_resolve;
             -- resolve 内部件(ask 宏含 typesafe_ask 调用链——与 DP2
             -- typesafe ACL 只授 resolve 同界)
GRANT EXECUTE ON FUNCTION v13_existence_action(jsonb) TO v13_route;
             -- existence_action 亦被装配消费:assemble_manifest 三角色
             -- EXECUTE、体内链随 invoker——route 侧补授(计划 L11 注记);
             -- trace 链同理(trace 三角色→chunk_filter_action→本函数),
             -- H1 矩阵结构性要求三角色
GRANT EXECUTE ON FUNCTION v13_existence_action(jsonb) TO v13_recall;
             -- defaults_action 同链:trace→chunk_filter_action/existence_action
             -- 的 review/default 分支消费 defaults_action——三角色闭包
             -- (resolve 已有;recall/route 补授)
GRANT EXECUTE ON FUNCTION v13_filter_defaults_action(text,text)
TO v13_recall, v13_route;
-- OR REPLACE 五件 ACL 经 OID 保留,不重授(judgment_hash/resolve=三角色/
-- resolve 既有面;envelope/assemble=三角色;chunk_referenced=DP4 既有面)。
-- OR REPLACE 五件 ACL 经 OID 保留,不重授(judgment_hash/resolve=三角色/
-- resolve 既有面;envelope/assemble=三角色;chunk_referenced=DP4 既有面)。

COMMIT;
