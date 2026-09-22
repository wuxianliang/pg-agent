BEGIN;

-- =========================================================================
-- DP7 M2 summary (v13_summary.sql): effect-plane extension (kind
-- context_summary + effect_attempt_cap v2) + summary_accept policy row +
-- summary_fidelity noul template (epoch pre-finalize, explicit) +
-- judgment_defaults summary_accept point + span_digest / checks /
-- envelope / verdict / schedule + single-source material helpers
-- (v13_history_action / v13_history_section_material /
-- v13_summary_section_material / v13_history_belt_guard) + assembly v3
-- (summary section + history shrink + fallback ladder + economics.summary
-- block) + validate v3 (kind=summary, transform words, belt cross-field
-- checks) + refresh v3 (dual-mode belt; oracle resolution
-- docs/reviews/v13-dp7-bdp7-1-oracle-resolution-2026-09-22.md §3.2,
-- diff allow-list §3.2.4 items 1-4 only, IF arm keeps the V3003 tombstone
-- verbatim). Design: docs/designs/v13-context-on-pg.md §6.2 touchpoint 2 /
-- §6.4 / §9 / §10 G-ctx8. Plan:
-- docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md §3.2.
-- File order = load order. Error code family: V3007 (new raises only).
-- =========================================================================

-- === effect kind 扩展(先行——同文件同事务先于 cap 翻版与 enqueue 面,
--     消费清单 #22;词表追加 append-only,既有五值零动;v13_complete 对
--     context_summary 走通用 CAS 分支零语义事件——DP1 #20 机制面) ===
ALTER TABLE effects DROP CONSTRAINT effects_kind_check;
ALTER TABLE effects ADD CONSTRAINT effects_kind_check CHECK (kind IN
  ('judge','tool','llm','context_refresh','human','context_summary'));

-- === effect_attempt_cap v2(全六键;翻版仪式:INSERT inactive→双 UPDATE
--     同事务翻;v1 五值逐键保留,只加 context_summary:2=两轮封顶对齐
--     packs 上限;README 翻新纪律:新版本必含全六键,降 cap 需清场) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('effect_attempt_cap', 2,
 '{"judge":4,"tool":3,"llm":3,"human":2,"context_refresh":3,"context_summary":2}'::jsonb,
 false);
UPDATE v13_policies SET active = false
 WHERE name = 'effect_attempt_cap' AND version = 1;
UPDATE v13_policies SET active = true
 WHERE name = 'effect_attempt_cap' AND version = 2;

-- === summary_accept 策略行(预算包/验收带/检查参数/CJK;OQ8) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('summary_accept', 1, '{
  "packs_reserved": 1,
  "gen_tokens_cap": 2048,
  "accept": {"lo": 0.80},
  "review": {"lo": 0.50, "hi": 0.80},
  "cjk": {"ratio_hi": 0.30, "mode": "reject_only"},
  "checks": {"max_body_bytes": 32768, "cjk_scan_sample_chars": 4096},
  "schedule_cap_day": 8,
  "note": "packs=1 = no regeneration (retry only when pre-allowed; gate fixture flips packs=2); protected-element extraction rule changes = new transform name + new version of this row (DP3 contract #9)"
}'::jsonb, true);

-- === 摘要验收模板 summary_fidelity(noul;epoch='pre-finalize' 显式——
--     列默认是 'pre-bind',B-DP7-2 裁决 §3.4 fixture 纪律;三步仪式
--     draft→内容行→freeze;criteria=accept band 语义题面;projection=
--     最小可见面 {source,summary}(§6.5);answer_schema_version=1(列面
--     int——以 DP2 §3.1 加载态为准机械对齐) ===
INSERT INTO v13_judgment_template_versions (template_name, template_version, state)
VALUES ('summary_fidelity', 1, 'draft');
INSERT INTO judgment_templates (template_name, template_version, kind, epoch,
                                question, criteria, answer_schema_version,
                                projection)
VALUES ('summary_fidelity', 1, 'noul', 'pre-finalize',
        'Does the summary faithfully preserve the load-bearing content of the source span (protected IDs, paths, numbers, tool pairings, decisions)? answer yes/no',
        '{"accept": {"lo": 0.80}, "review": {"lo": 0.50, "hi": 0.80}}'::jsonb,
        1, '["source","summary"]'::jsonb);
UPDATE v13_judgment_template_versions SET state = 'frozen'
 WHERE template_name = 'summary_fidelity' AND template_version = 1;

-- === judgment_defaults 追点 summary_accept(读活动行值+||新点+新版本+
--     翻;变量化 SQL 锚定版本号,防字面量漂移——plan 风险 #6;DP3 校验器
--     零改:points 点形状 {missing,timeout,review} 恰等,fail-closed 三态
--     全 exclude——§6.4-4) ===
DO $dp7def$
DECLARE v_old jsonb; v_new int;
BEGIN
  SELECT value INTO v_old FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  SELECT coalesce(max(version), 0) + 1 INTO v_new
   FROM v13_policies WHERE name = 'judgment_defaults';
  INSERT INTO v13_policies (name, version, value, active)
  VALUES ('judgment_defaults', v_new,
          jsonb_set(v_old, '{points,summary_accept}',
                    '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb),
          false);
  UPDATE v13_policies SET active = false
   WHERE name = 'judgment_defaults' AND active;
  UPDATE v13_policies SET active = true
   WHERE name = 'judgment_defaults' AND version = v_new;
END
$dp7def$;

-- === span_digest 单源(哈希同源纪律;signal 与信封/装配/消费谓词共用;
--     p_span=[content_hash…] 数组——plan §3.2 原文机械复制) ===
CREATE FUNCTION v13_span_digest(p_span jsonb)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest(
    (SELECT string_agg(x #>> '{}', ',' ORDER BY x #>> '{}')
       FROM jsonb_array_elements(p_span) AS x)
  , 'sha256'), 'hex');
$$;

-- === 确定性检查(§6.4-3 五项;零模型成本;参数随 summary_accept.checks
--     版本化;返回 {"pass":bool,"reasons":[…]},reasons 词表封闭
--     empty/not_shorter/protected_missing/structure/over_budget。
--     受保护元素集=span 内 user/llm 消息正文的 uuid/含'/'路径 token/
--     数值字面量(文本面)+ tool/result 配对名(jsonb 结构面) ===
CREATE FUNCTION v13_summary_checks(p_body text, p_span_texts jsonb, p_cap int)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_div int; v_chk jsonb; v_maxb int;
        v_span_b int; v_body_b int; v_se int; v_be int;
        v_reasons text[] := '{}';
        v_text text; v_prot text[] := '{}'; v_tools text[] := '{}';
        v_all text[]; v_missing int := 0; v_tok text;
BEGIN
  SELECT (value->>'est_bytes_per_token')::int INTO v_div
   FROM v13_policies WHERE name = 'assemble_manifest' AND active;
  SELECT value->'checks' INTO v_chk FROM v13_policies
   WHERE name = 'summary_accept' AND active;
  v_maxb := coalesce((v_chk->>'max_body_bytes')::int, 32768);
  -- span 正文=前缀消息 jsonb 数组;段字节=整个 span 的 jsonb 文本字节
  -- (与 history 段材料同一字节口径,est 公式单源)
  v_span_b := octet_length(coalesce(p_span_texts::text, ''));
  v_body_b := octet_length(coalesce(p_body, ''));
  v_se := (v_span_b + v_div - 1) / v_div;
  v_be := (v_body_b + v_div - 1) / v_div;
  -- ① empty:body 空白归一后空串
  IF btrim(coalesce(p_body, '')) = '' THEN
    v_reasons := v_reasons || 'empty'::text;
  END IF;
  -- ② not_shorter:est(body) >= Σest(span) 段字节同公式折算
  IF v_be >= v_se THEN
    v_reasons := v_reasons || 'not_shorter'::text;
  END IF;
  -- ③ protected_missing:抽取集任一缺失(fail-closed 方向)
  SELECT coalesce(string_agg(coalesce(m->'payload'->>'text', ''), E'\n'), '')
    INTO v_text
    FROM jsonb_array_elements(coalesce(p_span_texts, '[]'::jsonb)) m
   WHERE m->>'type' IN ('user/message','llm/message');
  SELECT coalesce(array_agg(DISTINCT m[1]), '{}') INTO v_prot
    FROM regexp_matches(v_text,
      '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', 'g') m;
  SELECT v_prot || coalesce(array_agg(DISTINCT t), '{}') INTO v_prot
    FROM regexp_split_to_table(v_text, '\s+') t
   WHERE position('/' in t) > 0;
  SELECT v_prot || coalesce(array_agg(DISTINCT m[1]), '{}') INTO v_prot
    FROM regexp_matches(v_text, '([0-9]+(\.[0-9]+)?)', 'g') m;
  SELECT coalesce(array_agg(DISTINCT m->'payload'->>'tool'), '{}') INTO v_tools
    FROM jsonb_array_elements(coalesce(p_span_texts, '[]'::jsonb)) m
   WHERE m->>'type' = 'tool/result';
  v_all := v_prot || v_tools;
  FOREACH v_tok IN ARRAY v_all LOOP
    IF v_tok IS NOT NULL AND v_tok <> ''
       AND position(v_tok in coalesce(p_body, '')) = 0 THEN
      v_missing := v_missing + 1;
    END IF;
  END LOOP;
  IF v_missing > 0 THEN
    v_reasons := v_reasons || 'protected_missing'::text;
  END IF;
  -- ④ structure:控制字符(U+0001-U+0008/U+000B/U+000C/U+000E-U+001F,
  --    \n\t 豁免;ARE \xHH 逃逸)或超 max_body_bytes
  IF coalesce(p_body, '') ~ '[\x01-\x08\x0B\x0C\x0E-\x1F]'
     OR v_body_b > v_maxb THEN
    v_reasons := v_reasons || 'structure'::text;
  END IF;
  -- ⑤ over_budget:est(body) > gen_tokens_cap
  IF v_be > p_cap THEN
    v_reasons := v_reasons || 'over_budget'::text;
  END IF;
  RETURN jsonb_build_object('pass', cardinality(v_reasons) = 0,
                            'reasons', to_jsonb(v_reasons));
END $$;

-- === 摘要验收信封(OQ8;plan 十键 + goal_hash/candidates 两键=加载态
--     resolve(文件 10 filter 形态)尾部 remaining 计算无条件消费面——
--     v13_filter_bodies_present/v13_filter_gate_open 经 v13_existence_ref
--     断言 goal_hash 64hex+candidates array,缺即 V3006;P1-5 原则「缺键
--     ⇒resolve 不可执行」对实装载消费面的对齐,偏差记 README;ctx 与
--     groups[].state 同材料同源;budget={batch_questions:1}=resolve 入口
--     V3002 形状面;candidate_set_hash=span_digest 锚,与 signal 同一单源;
--     provider/model=v13_guc_required fail-closed) ===
CREATE FUNCTION v13_summary_envelope(p_sid uuid, p_span_digest text,
                                     p_source text, p_summary text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_provider text; v_model text; v_tmpl jsonb; v_t judgment_templates%ROWTYPE;
BEGIN
  SELECT v13_guc_required('typesafe.provider'),
         v13_guc_required('typesafe.model')
    INTO v_provider, v_model;
  SELECT t.* INTO v_t
   FROM judgment_templates t
   JOIN v13_judgment_template_versions v
     ON v.template_name = t.template_name
    AND v.template_version = t.template_version
  WHERE t.template_name = 'summary_fidelity' AND v.state = 'frozen'
  ORDER BY t.template_version DESC LIMIT 1;
  IF v_t.template_name IS NULL THEN
    RAISE EXCEPTION 'v13: frozen template summary_fidelity missing (seed lost?)'
      USING ERRCODE = 'V3007';
  END IF;
  v_tmpl := jsonb_build_object('version', v_t.template_version,
                               'kind', v_t.kind,
                               'projection', v_t.projection,
                               'answer_schema_version', v_t.answer_schema_version);
  RETURN jsonb_build_object(
    'sid', p_sid,
    'ctx', jsonb_build_object('source', p_source, 'summary', p_summary),
    'needed', jsonb_build_array(jsonb_build_object(
       'signal', 'summary::' || p_span_digest,
       'kind', v_t.kind,
       'question', v_t.question,
       'criteria', v_t.criteria,
       'template_name', 'summary_fidelity')),
    'templates', jsonb_build_object('summary_fidelity', v_tmpl),
    'groups', jsonb_build_array(jsonb_build_object(
       'projection_key', v13_projection_key(v_t.projection),
       'state', jsonb_build_object('source', p_source, 'summary', p_summary))),
    'budget', jsonb_build_object('batch_questions', 1),
    'timeout_ms', NULLIF(current_setting('typesafe.timeout_ms', true), ''),
    'candidate_set_hash', p_span_digest,
    'provider', v_provider, 'model', v_model,
    'goal_hash', v13_goal_hash(p_sid),
    'candidates', '[]'::jsonb);
END $$;

-- === 验收裁决(decision_id 直取——P1-6;材料=存储行;返回 {action,basis};
--     basis 词表封闭 decision_accept/decision_review/decision_reject/
--     default_timeout/default_missing/cjk_reject_only;CJK 拒绝-only 后置门
--     §6.4-7:材料=decisions.context->>'source' 存储半边,占比按 scan 窗口;
--     defaults 点三态与缺省动作不一致 ⇒ V3007 fail-loud) ===
CREATE FUNCTION v13_summary_verdict(p_decision_id uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_row decisions%ROWTYPE; v_pol jsonb; v_jdef jsonb;
        v_p numeric; v_act text; v_basis text;
        v_lo numeric; v_rlo numeric; v_rhi numeric; v_ratio_hi numeric;
        v_mode text; v_sample int; v_samp text; v_cjk int; v_ratio numeric;
BEGIN
  SELECT value INTO v_pol FROM v13_policies
   WHERE name = 'summary_accept' AND active;
  SELECT value INTO v_jdef FROM v13_policies
   WHERE name = 'judgment_defaults' AND active;
  v_lo := coalesce((v_pol->'accept'->>'lo')::numeric, 0.80);
  v_rlo := coalesce((v_pol->'review'->>'lo')::numeric, 0.50);
  v_rhi := coalesce((v_pol->'review'->>'hi')::numeric, 0.80);
  v_ratio_hi := coalesce((v_pol->'cjk'->>'ratio_hi')::numeric, 0.30);
  v_mode := coalesce(v_pol->'cjk'->>'mode', 'reject_only');
  v_sample := coalesce((v_pol->'checks'->>'cjk_scan_sample_chars')::int, 4096);
  SELECT * INTO v_row FROM decisions WHERE decision_id = p_decision_id;
  IF v_row.decision_id IS NULL THEN
    -- missing 态:缺省动作来自 defaults 点(fail-closed)
    IF (v_jdef->'points'->'summary_accept'->>'missing') IS DISTINCT FROM 'exclude' THEN
      RAISE EXCEPTION
        'v13: judgment_defaults.summary_accept.missing disagrees with verdict default (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    RETURN jsonb_build_object('action', 'exclude', 'basis', 'default_missing');
  END IF;
  IF v_row.signal NOT LIKE 'summary::%' THEN
    RAISE EXCEPTION 'v13: verdict on non-summary decision %', v_row.decision_id
      USING ERRCODE = 'V3007';
  END IF;
  IF v_row.answer IS NULL THEN
    IF v_row.status = 'failed' THEN
      IF (v_jdef->'points'->'summary_accept'->>'timeout') IS DISTINCT FROM 'exclude' THEN
        RAISE EXCEPTION
          'v13: judgment_defaults.summary_accept.timeout disagrees with verdict default (V3007)'
          USING ERRCODE = 'V3007';
      END IF;
      RETURN jsonb_build_object('action', 'exclude', 'basis', 'default_timeout');
    END IF;
    RETURN jsonb_build_object('action', 'exclude', 'basis', 'default_missing');
  END IF;
  v_p := (v_row.answer->>'noul')::numeric;
  IF v_p >= v_lo THEN
    v_act := 'include'; v_basis := 'decision_accept';
  ELSIF v_p >= v_rlo THEN
    IF (v_jdef->'points'->'summary_accept'->>'review') IS DISTINCT FROM 'exclude' THEN
      RAISE EXCEPTION
        'v13: judgment_defaults.summary_accept.review disagrees with verdict default (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    v_act := 'exclude'; v_basis := 'decision_review';
  ELSE
    v_act := 'exclude'; v_basis := 'decision_reject';
  END IF;
  -- CJK 拒绝-only 后置门(§6.4-7):accept 信号不单独放行,仅 reject/review
  -- 作为附加拒绝信号生效——两向 fail-closed
  v_samp := left(coalesce(v_row.context->>'source', ''), v_sample);
  v_cjk := length(v_samp) - length(regexp_replace(v_samp, E'[㐀-䶿一-鿿]', '', 'g'));
  v_ratio := v_cjk::numeric / greatest(length(v_samp), 1);
  IF v_act = 'include' AND v_mode = 'reject_only' AND v_ratio > v_ratio_hi THEN
    v_act := 'exclude'; v_basis := 'cjk_reject_only';
  END IF;
  RETURN jsonb_build_object('action', v_act, 'basis', v_basis);
END $$;

-- === 调度(驱动后置;OQ2 步 2;纯 SQL 零 IO;VOLATILE=enqueue 面;
--     守卫链任一不过=no-op RETURN NULL 零事件——失败事实由下一次装配
--     transform trace 承载,§6.4-1) ===
CREATE FUNCTION v13_summary_schedule(p_sid uuid)
RETURNS uuid LANGUAGE plpgsql VOLATILE AS $$
DECLARE v_m jsonb; v_intent jsonb; v_pol jsonb; v_span jsonb; v_id uuid;
        v_cap int; v_today int; v_tv int; v_bv int; v_sv int; v_div int;
        v_cur jsonb; v_found boolean;
BEGIN
  -- ① single-active:存在活跃 effect(任意 kind)即 no-op(不变量 2)
  PERFORM 1 FROM effects
   WHERE session_id = p_sid AND status IN ('ready','claimed');
  IF FOUND THEN RETURN NULL; END IF;
  -- ② intent:active manifest economics.summary.intent 在场
  SELECT a.inline INTO v_m FROM artifacts a
   WHERE a.artifact_id = (SELECT context_active_artifact FROM sessions
                            WHERE session_id = p_sid);
  v_intent := v_m -> 'economics' -> 'summary' -> 'intent';
  IF v_intent IS NULL OR jsonb_typeof(v_intent) IS DISTINCT FROM 'object' THEN
    RETURN NULL;
  END IF;
  v_span := v_intent -> 'target_span';
  IF v_span IS NULL OR jsonb_typeof(v_span) IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_span) = 0 THEN
    RETURN NULL;
  END IF;
  -- ③ 调度闸+花费闸(同点——预算包预留检查的执法点,P1-4;超闸走
  --    drop/spill 同路径:零 effect 零生成零 Jev——§6.4-1)
  SELECT value INTO v_pol FROM v13_policies
   WHERE name = 'summary_accept' AND active;
  IF v_pol IS NULL THEN RETURN NULL; END IF;
  v_cap := (v_pol->>'schedule_cap_day')::int;
  SELECT count(*) INTO v_today FROM effects
   WHERE session_id = p_sid AND kind = 'context_summary'
     AND created_at >= date_trunc('day', now());
  IF v_today >= v_cap THEN RETURN NULL; END IF;
  IF (v13_judge_spend(p_sid)->>'over')::boolean THEN RETURN NULL; END IF;
  -- ④ spans 在场:target_span 逐 hash 仍在本 session 当前 canonical 消息
  --    哈希集内(target_span 粒度=前缀消息级哈希,与消费谓词同一单源;
  --    span 已变则等下一版 intent——J4 断言面)
  SELECT (v13_canonical_state(p_sid) -> 'messages') INTO v_cur;
  SELECT EXISTS (SELECT 1
                   FROM jsonb_array_elements(v_span) h
                  WHERE NOT EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements(coalesce(v_cur, '[]'::jsonb)) m
                     WHERE encode(digest(coalesce(m::text, ''), 'sha256'), 'hex')
                           = h #>> '{}'))
    INTO v_found;
  IF v_found THEN RETURN NULL; END IF;
  -- ⑤ request 只携语义词段(零水位,不变量 2);policies 快照钉版本号
  SELECT version INTO v_tv FROM v13_policies
   WHERE name = 'context_tiers' AND active;
  SELECT version INTO v_bv FROM v13_policies
   WHERE name = 'context_budget' AND active;
  SELECT version INTO v_sv FROM v13_policies
   WHERE name = 'summary_accept' AND active;
  SELECT (value->>'est_bytes_per_token')::int INTO v_div FROM v13_policies
   WHERE name = 'assemble_manifest' AND active;
  v_id := v13_enqueue_effect(p_sid, 'context_summary',
    jsonb_build_object(
      'purpose', 'context_summary',
      'span', v_span,
      'span_digest', v_intent->>'span_digest',
      'packs_reserved', (v_pol->>'packs_reserved')::int,
      'policies', jsonb_build_object('tiers_ver', v_tv, 'budget_ver', v_bv,
                                     'summary_ver', v_sv, 'est_div', v_div)));
  RETURN v_id;
END $$;

-- =========================================================================
-- [DP7-S] 单源材料函数四件(裁决 §3.2.1;新对象非换体;STABLE/只读已锁
-- 行/禁止调用 v13_assemble_manifest 防环/REVOKE PUBLIC;guard 仅 owner)
-- =========================================================================

-- === (a) v13_history_action:封闭词表 full|tail|spill|round_drop|final_trim。
--     决策链与 economy 装配 v2 同公式单写(t_used=全量候选 est 含 pre_skip
--     镜像/pred/recovery/hysteresis 同源);需压缩=actions_on 且(硬窗口
--     或(r 已知且 effective tier>=CompactHistory))——r_unknown 只按硬窗口
--     (OQ5);可消费 adopted 谓词=最新 succeeded context_summary 行
--     (created_at 单调列+effect_id 打破平局,禁 now())+result.adopted=true
--     +request 冻结 span_digest==当前 canonical 前缀 digest(span 一律取
--     request 冻结值,不读 result 副本);ladder 停机判定=动作后 est 重跑
--     三桶(与 (b) 同一算法逐字复制——action 词与 material 字节一致) ===
CREATE FUNCTION v13_history_action(p_sid uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_tiers jsonb; v_cbud jsonb; v_asm jsonb;
  v_actions boolean; v_bands jsonb; v_hyst jsonb; v_keep int;
  v_div int; v_budget int; v_l_eff bigint; v_hard int;
  v_ro bigint; v_r numeric;
  v_ovr jsonb; v_off jsonb;
  v_gb int := 0; v_tb int := 0; v_hb int; v_ge int; v_te int; v_he int;
  v_t_used bigint := 0; v_bp bigint; v_pred bigint; v_delta bigint;
  v_prior jsonb; v_aid uuid; v_recovery boolean; v_floor int;
  v_cand bigint; v_target int; v_held int; v_eff int;
  v_loheld int; v_ct int; v_all_low boolean; v_lowrun boolean := false;
  v_turn int; v_lt record; v_bps bigint[] := '{}';
  v_full jsonb; v_sd text; v_tailb bigint;
  v_ceff effects%ROWTYPE;
  v_mat jsonb; v_upos int[]; v_p int; v_next int;
  v_effb bigint; v_hcap bigint; v_gen record;
BEGIN
  SELECT value INTO v_tiers FROM v13_policies
   WHERE name = 'context_tiers' AND active;
  SELECT value INTO v_cbud FROM v13_policies
   WHERE name = 'context_budget' AND active;
  SELECT value INTO v_asm FROM v13_policies
   WHERE name = 'assemble_manifest' AND active;
  v_actions := (v_tiers->>'actions_enabled')::boolean;
  IF v_actions IS NOT TRUE THEN
    RETURN 'full';
  END IF;
  v_bands := v_tiers->'bands';
  v_hyst := v_tiers->'hysteresis';
  v_keep := coalesce((v_cbud->>'keep_tail_turns')::int, 2);
  v_div := (v_asm->>'est_bytes_per_token')::int;
  v_budget := (v_asm->>'budget_tokens')::int;
  v_l_eff := (v_cbud->>'l_eff_tokens')::bigint;
  v_hard := (v_cbud->>'hard_window_bp')::int;
  v_ovr := v_asm->'priority_overrides';
  v_off := v_asm->'kinds_disabled';
  IF v_div IS NULL OR v_div <= 0 OR v_l_eff IS NULL OR v_l_eff <= 0
     OR v_budget IS NULL OR v_budget < 0 THEN
    RETURN 'full';   -- malformed policies: refresh shape guard owns the loud failure
  END IF;
  -- 全量候选 est(v2 t_used 镜像:pre_skip 段不计)
  SELECT octet_length(coalesce(g.payload::text, '')) INTO v_gb
   FROM v13_goals g WHERE g.session_id = p_sid ORDER BY g.seq DESC LIMIT 1;
  v_gb := coalesce(v_gb, 0);
  v_full := v13_canonical_state(p_sid) -> 'messages';
  v_hb := octet_length(coalesce(v_full::text, ''));
  v_tb := octet_length(coalesce((v13_canonical_state(p_sid) -> 'tools')::text, ''));
  IF NOT ((v_ovr ? 'goal') AND (v_ovr->>'goal')
            IN ('First','Normal','Never','LastResort') IS NOT TRUE)
     AND coalesce(v_ovr->>'goal', 'First') <> 'Never'
     AND NOT (v_off @> to_jsonb('goal'::text)) THEN
    v_t_used := v_t_used + (v_gb + v_div - 1) / v_div;
  END IF;
  IF NOT ((v_ovr ? 'history') AND (v_ovr->>'history')
            IN ('First','Normal','Never','LastResort') IS NOT TRUE)
     AND coalesce(v_ovr->>'history', 'Normal') <> 'Never'
     AND NOT (v_off @> to_jsonb('history'::text)) THEN
    v_t_used := v_t_used + (v_hb + v_div - 1) / v_div;
  END IF;
  IF NOT ((v_ovr ? 'tools') AND (v_ovr->>'tools')
            IN ('First','Normal','Never','LastResort') IS NOT TRUE)
     AND coalesce(v_ovr->>'tools', 'First') <> 'Never'
     AND NOT (v_off @> to_jsonb('tools'::text)) THEN
    v_t_used := v_t_used + (v_tb + v_div - 1) / v_div;
  END IF;
  v_ro := v13_ro_reserve(p_sid);
  v_bp := (v_t_used + v_ro) * 10000 / v_l_eff;
  -- predicted:同 turn 前版 manifest 压力+新增语义事件 est 增量折算
  SELECT s.context_active_artifact INTO v_aid FROM sessions s
   WHERE s.session_id = p_sid;
  SELECT a.inline INTO v_prior FROM artifacts a WHERE a.artifact_id = v_aid;
  SELECT turn_no INTO v_turn FROM sessions WHERE session_id = p_sid;
  v_pred := NULL;
  IF v_prior IS NOT NULL AND v_prior ? 'economics'
     AND (v_prior->>'turn_no')::int = v_turn THEN
    SELECT coalesce(sum(((octet_length(e.payload::text) + v_div - 1) / v_div)), 0)
      INTO v_delta FROM events e
     WHERE e.session_id = p_sid
       AND e.type IN ('user/message','llm/message','tool/result')
       AND e.seq > (v_prior->'required_revision'->>'sem')::bigint;
    v_pred := (((v_prior->'economics'->'pressure'->>'t_used')::bigint + v_delta)
               + v_ro) * 10000 / v_l_eff;
  END IF;
  -- recovery floor(单源=v13_recovery_active,P1-3)
  v_recovery := v13_recovery_active(p_sid);
  v_floor := NULL;
  IF v_recovery THEN
    SELECT (b->>'lo_bp')::int INTO v_floor
     FROM jsonb_array_elements(v_bands) b
     WHERE b->>'tier' = 'CompactHistory' LIMIT 1;
  END IF;
  v_cand := greatest(v_bp, coalesce(v_pred, v_bp), coalesce(v_floor, 0));
  v_target := v13_tier_rank(v13_band_of(v_bands, v_cand));
  -- held rank+跨 turn hysteresis(链上最近 turn 的 raw bp,depth 最小优先)
  v_held := NULL; v_loheld := NULL;
  IF v_prior IS NOT NULL AND v_prior ? 'economics'
     AND (v_prior->'economics'->'tier'->>'effective')
         IN ('Normal','TrimSchemas','CompactHistory','AggressivePrune') THEN
    v_held := v13_tier_rank(v_prior->'economics'->'tier'->>'effective');
    SELECT (b->>'lo_bp')::int INTO v_loheld
     FROM jsonb_array_elements(v_bands) b
     WHERE b->>'tier' = v_prior->'economics'->'tier'->>'effective' LIMIT 1;
  END IF;
  IF v_loheld IS NOT NULL THEN
    v_ct := coalesce((v_hyst->>'cooldown_turns')::int, 0);
    FOR v_lt IN
      WITH RECURSIVE chain AS (
        SELECT a2.inline AS m, 0 AS depth FROM artifacts a2
         WHERE a2.artifact_id = v_aid
        UNION ALL
        SELECT a3.inline, c.depth + 1 FROM chain c JOIN artifacts a3
          ON a3.artifact_id = (c.m->'replay'->>'prior_artifact_id')::uuid
         WHERE c.depth < 16)
      SELECT x.t, x.bp FROM (
        SELECT DISTINCT ON ((c.m->>'turn_no')::int) (c.m->>'turn_no')::int AS t,
               (c.m->'economics'->'pressure'->>'bp')::bigint AS bp
          FROM chain c
         WHERE (c.m->>'turn_no')::int < v_turn AND c.m ? 'economics'
         ORDER BY (c.m->>'turn_no')::int, c.depth) x
      ORDER BY x.t DESC
    LOOP
      v_bps := v_bps || v_lt.bp;
    END LOOP;
    IF v_ct > 0 AND cardinality(v_bps) >= v_ct THEN
      SELECT bool_and(w < v_loheld) INTO v_all_low
        FROM unnest(v_bps[1:v_ct]) w;
      v_lowrun := coalesce(v_all_low, false);
    END IF;
  END IF;
  IF v_held IS NULL OR v_target >= v_held THEN
    v_eff := v_target;
  ELSIF v_lowrun THEN
    v_eff := greatest(v_target,
                      v_held - coalesce((v_hyst->>'max_downgrade_steps')::int, 1));
  ELSE
    v_eff := v_held;
  END IF;
  -- r 单源(generation 五维;缺行 ⇒ r IS NULL ⇒ 仅硬窗口可动作,OQ5)
  SELECT q.value->>'provider' AS provider, q.value->>'model' AS model
    INTO v_gen
   FROM v13_policies q WHERE q.name = 'generation' AND q.active;
  v_r := v13_pricing_r(v_gen.provider, v_gen.model);
  IF NOT (v_bp >= v_hard OR (v_r IS NOT NULL AND v_eff >= 3)) THEN
    RETURN 'full';                       -- 有效 tier 无需压缩(且非硬窗口/E(r) 判定)
  END IF;
  -- 可消费 adopted summary?(与 (c) 同一份谓词)
  v_tailb := CASE WHEN (SELECT count(*) FROM jsonb_array_elements(v_full) e
                          WHERE e->>'type' = 'user/message') >= v_keep
                  THEN (SELECT min((t.e->>'seq')::bigint)
                          FROM (SELECT e FROM jsonb_array_elements(v_full) e
                                 WHERE e->>'type' = 'user/message'
                                 ORDER BY (e->>'seq')::bigint DESC
                                 LIMIT v_keep) t(e))
             END;
  SELECT v13_span_digest(coalesce(jsonb_agg(
           to_jsonb(encode(digest(coalesce(m::text, ''), 'sha256'), 'hex'))
           ORDER BY (m->>'seq')::bigint), '[]'::jsonb))
    INTO v_sd
    FROM jsonb_array_elements(v_full) m
   WHERE v_tailb IS NOT NULL AND (m->>'seq')::bigint < v_tailb;
  SELECT * INTO v_ceff FROM effects
   WHERE session_id = p_sid AND kind = 'context_summary'
     AND status = 'succeeded'
   ORDER BY created_at DESC, effect_id DESC LIMIT 1;
  IF v_ceff.effect_id IS NOT NULL
     AND coalesce((v_ceff.result->>'adopted')::boolean, false)
     AND v_sd IS NOT NULL
     AND v_ceff.request->>'span_digest' IS NOT DISTINCT FROM v_sd THEN
    RETURN 'tail';
  END IF;
  -- ===== 固定梯(装得下就停;停机判定=动作后 est 重跑三桶,与 (b) 逐字
  --       同一算法) =====
  v_effb := greatest(least(v_budget, v_l_eff - v_ro), 0);
  v_hcap := (floor(v_effb * (v_cbud->'buckets'->>'history')::numeric))::bigint;
  v_ge := (v_gb + v_div - 1) / v_div;
  v_te := (v_tb + v_div - 1) / v_div;
  -- spill:tool/result 正文→stub(引用 effect_id,不含原 body)
  SELECT coalesce(jsonb_agg(x ORDER BY (x->>'seq')::bigint), '[]'::jsonb)
    INTO v_mat
    FROM (SELECT CASE WHEN e->>'type' = 'tool/result'
                       THEN e || jsonb_build_object('payload',
                            (e->'payload') - 'result' ||
                            jsonb_build_object(
                              'effect_id',
                              (SELECT ev.source_effect_id FROM events ev
                                WHERE ev.session_id = p_sid
                                  AND ev.seq = (e->>'seq')::bigint),
                              'stub', true))
                       ELSE e END AS x
             FROM jsonb_array_elements(v_full) e) y;
  v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
  IF v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap THEN
    RETURN 'spill';
  END IF;
  -- round_drop:逐个丢最老完整可压缩 round(protected tail 外)直到装得下
  LOOP
    SELECT array_agg(i ORDER BY i) INTO v_upos
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) i
     WHERE (v_mat->i)->>'type' = 'user/message';
    EXIT WHEN v_upos IS NULL OR cardinality(v_upos) <= v_keep;
    v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
    EXIT WHEN v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap;
    v_p := v_upos[1];
    v_next := v_upos[2];
    SELECT coalesce(jsonb_agg(v_mat->j ORDER BY j), '[]'::jsonb) INTO v_mat
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) j
     WHERE j < v_p OR j >= v_next;
  END LOOP;
  v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
  IF v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap THEN
    RETURN 'round_drop';
  END IF;
  -- final_trim:裁掉头部 round 直到装得下(至少保留最后一个 round)
  LOOP
    SELECT array_agg(i ORDER BY i) INTO v_upos
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) i
     WHERE (v_mat->i)->>'type' = 'user/message';
    EXIT WHEN v_upos IS NULL OR cardinality(v_upos) <= 1;
    v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
    EXIT WHEN v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap;
    v_next := v_upos[2];
    SELECT coalesce(jsonb_agg(v_mat->j ORDER BY j), '[]'::jsonb) INTO v_mat
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) j
     WHERE j >= v_next;
  END LOOP;
  RETURN 'final_trim';
END $$;

-- === (b) v13_history_section_material:history 段正文单源。
--     action='full' ⇒ 返回 v13_canonical_state->'messages' 原值(禁
--     jsonb_agg 重建——字节身份);'tail' ⇒ keep_tail_turns 尾段(不足
--     keep ⇒ 全量原值且 action 不得为 tail);回退三级 ⇒ 梯作用后的
--     正文。梯算法与 (a) 逐字同一(单一算法两处复制)。 ===
CREATE FUNCTION v13_history_section_material(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_action text := v13_history_action(p_sid);
  v_cbud jsonb; v_asm jsonb; v_keep int; v_div int; v_budget int;
  v_l_eff bigint; v_ro bigint; v_effb bigint; v_hcap bigint;
  v_gb int := 0; v_tb int; v_ge int; v_te int; v_he int;
  v_full jsonb; v_mat jsonb; v_upos int[]; v_tail_i int; v_p int; v_next int;
BEGIN
  v_full := v13_canonical_state(p_sid) -> 'messages';
  IF v_action = 'full' THEN
    RETURN v_full;                        -- 原值,零重建
  END IF;
  SELECT value INTO v_cbud FROM v13_policies
   WHERE name = 'context_budget' AND active;
  SELECT value INTO v_asm FROM v13_policies
   WHERE name = 'assemble_manifest' AND active;
  v_keep := coalesce((v_cbud->>'keep_tail_turns')::int, 2);
  v_div := (v_asm->>'est_bytes_per_token')::int;
  v_budget := (v_asm->>'budget_tokens')::int;
  v_l_eff := (v_cbud->>'l_eff_tokens')::bigint;
  IF v_action = 'tail' THEN
    SELECT array_agg(i ORDER BY i) INTO v_upos
      FROM generate_series(0, jsonb_array_length(v_full) - 1) i
     WHERE (v_full->i)->>'type' = 'user/message';
    IF v_upos IS NULL OR cardinality(v_upos) < v_keep THEN
      RETURN v_full;                      -- 不足 keep:材料=全量原值
    END IF;
    v_tail_i := v_upos[cardinality(v_upos) - v_keep + 1];
    SELECT coalesce(jsonb_agg(v_full->j ORDER BY j), '[]'::jsonb) INTO v_mat
      FROM generate_series(v_tail_i, jsonb_array_length(v_full) - 1) j;
    RETURN v_mat;
  END IF;
  -- ===== 固定梯(与 (a) 逐字同一算法) =====
  v_ro := v13_ro_reserve(p_sid);
  v_effb := greatest(least(v_budget, v_l_eff - v_ro), 0);
  v_hcap := (floor(v_effb * (v_cbud->'buckets'->>'history')::numeric))::bigint;
  SELECT octet_length(coalesce(g.payload::text, '')) INTO v_gb
   FROM v13_goals g WHERE g.session_id = p_sid ORDER BY g.seq DESC LIMIT 1;
  v_gb := coalesce(v_gb, 0);
  v_tb := octet_length(coalesce((v13_canonical_state(p_sid) -> 'tools')::text, ''));
  v_ge := (v_gb + v_div - 1) / v_div;
  v_te := (v_tb + v_div - 1) / v_div;
  SELECT coalesce(jsonb_agg(x ORDER BY (x->>'seq')::bigint), '[]'::jsonb)
    INTO v_mat
    FROM (SELECT CASE WHEN e->>'type' = 'tool/result'
                       THEN e || jsonb_build_object('payload',
                            (e->'payload') - 'result' ||
                            jsonb_build_object(
                              'effect_id',
                              (SELECT ev.source_effect_id FROM events ev
                                WHERE ev.session_id = p_sid
                                  AND ev.seq = (e->>'seq')::bigint),
                              'stub', true))
                       ELSE e END AS x
             FROM jsonb_array_elements(v_full) e) y;
  v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
  IF v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap THEN
    RETURN v_mat;
  END IF;
  LOOP
    SELECT array_agg(i ORDER BY i) INTO v_upos
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) i
     WHERE (v_mat->i)->>'type' = 'user/message';
    EXIT WHEN v_upos IS NULL OR cardinality(v_upos) <= v_keep;
    v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
    EXIT WHEN v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap;
    v_p := v_upos[1];
    v_next := v_upos[2];
    SELECT coalesce(jsonb_agg(v_mat->j ORDER BY j), '[]'::jsonb) INTO v_mat
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) j
     WHERE j < v_p OR j >= v_next;
  END LOOP;
  v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
  IF v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap THEN
    RETURN v_mat;
  END IF;
  LOOP
    SELECT array_agg(i ORDER BY i) INTO v_upos
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) i
     WHERE (v_mat->i)->>'type' = 'user/message';
    EXIT WHEN v_upos IS NULL OR cardinality(v_upos) <= 1;
    v_he := (octet_length(coalesce(v_mat::text, '')) + v_div - 1) / v_div;
    EXIT WHEN v_ge + v_te + v_he <= v_effb AND v_he <= v_hcap;
    v_next := v_upos[2];
    SELECT coalesce(jsonb_agg(v_mat->j ORDER BY j), '[]'::jsonb) INTO v_mat
      FROM generate_series(0, jsonb_array_length(v_mat) - 1) j
     WHERE j >= v_next;
  END LOOP;
  RETURN v_mat;
END $$;

-- === (c) v13_summary_section_material:不应落 summary 段时 NULL;否则=
--     同一 adopted effect 的 result.rounds 最后一轮 body 文本→to_jsonb
--     (jsonb 字符串;与 history 材料同哈希律)。禁读 rounds[].content_hash
--     (不变量 9)。 ===
CREATE FUNCTION v13_summary_section_material(p_sid uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_action text; v_ceff effects%ROWTYPE;
        v_full jsonb; v_tailb bigint; v_sd text; v_rounds jsonb; v_keep int;
BEGIN
  v_action := v13_history_action(p_sid);
  IF v_action IS DISTINCT FROM 'tail' THEN
    RETURN NULL;
  END IF;
  SELECT coalesce((SELECT (q.value->>'keep_tail_turns')::int FROM v13_policies q
                     WHERE q.name = 'context_budget' AND q.active), 2)
    INTO v_keep;
  SELECT * INTO v_ceff FROM effects
   WHERE session_id = p_sid AND kind = 'context_summary'
     AND status = 'succeeded'
   ORDER BY created_at DESC, effect_id DESC LIMIT 1;
  IF v_ceff.effect_id IS NULL
     OR coalesce((v_ceff.result->>'adopted')::boolean, false) IS NOT TRUE THEN
    RETURN NULL;
  END IF;
  -- span 一律取 request 冻结值(不读 result 副本)
  v_full := v13_canonical_state(p_sid) -> 'messages';
  v_tailb := CASE WHEN (SELECT count(*) FROM jsonb_array_elements(v_full) e
                          WHERE e->>'type' = 'user/message') >= v_keep
                  THEN (SELECT min((t.e->>'seq')::bigint)
                          FROM (SELECT e FROM jsonb_array_elements(v_full) e
                                 WHERE e->>'type' = 'user/message'
                                 ORDER BY (e->>'seq')::bigint DESC
                                 LIMIT v_keep) t(e))
             END;
  SELECT v13_span_digest(coalesce(jsonb_agg(
           to_jsonb(encode(digest(coalesce(m::text, ''), 'sha256'), 'hex'))
           ORDER BY (m->>'seq')::bigint), '[]'::jsonb))
    INTO v_sd
    FROM jsonb_array_elements(v_full) m
   WHERE v_tailb IS NOT NULL AND (m->>'seq')::bigint < v_tailb;
  IF v_sd IS NULL OR v_ceff.request->>'span_digest' IS DISTINCT FROM v_sd THEN
    RETURN NULL;
  END IF;
  v_rounds := v_ceff.result->'rounds';
  IF v_rounds IS NULL OR jsonb_typeof(v_rounds) IS DISTINCT FROM 'array'
     OR jsonb_array_length(v_rounds) = 0 THEN
    RETURN NULL;
  END IF;
  RETURN to_jsonb(v_rounds->(jsonb_array_length(v_rounds) - 1)->>'body');
END $$;

-- === (d) v13_history_belt_guard(owner-only):变形臂进入时 p_mat 哈希已
--     等于段哈希且不等于全文哈希,guard 按 canonical 独立复核(R3 核心:
--     单源函数若 action 与 material 同时把尾段切错一拍,装配与 belt 两边
--     哈希仍相等——guard 对 canonical 重数后缀/重算 span,是 belt 侧的
--     独立信源)。 ===
CREATE FUNCTION v13_history_belt_guard(p_sid uuid, p_full jsonb, p_mat jsonb,
                                       p_manifest jsonb)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE v_action text; v_keep int; v_h text; v_a int; v_b int;
        v_ufull int; v_umt int; v_ceff effects%ROWTYPE; v_sd text; v_tailb bigint;
        v_tr jsonb;
BEGIN
  v_action := v13_history_action(p_sid);
  SELECT coalesce((SELECT (q.value->>'keep_tail_turns')::int
                     FROM v13_policies q
                    WHERE q.name = 'context_budget' AND q.active), 2)
    INTO v_keep;
  IF v_action = 'full' THEN
    -- 规则 1:装配写了非全文哈希而决策说不变形
    RAISE EXCEPTION
      'v13: belt guard: non-full history hash while action=full (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  -- goal 段哈希==v13_goal_hash(两族共用)
  SELECT s->>'content_hash' INTO v_h
    FROM jsonb_array_elements(p_manifest->'sections') s
   WHERE s->>'section_id' = 'goal';
  IF v_h IS DISTINCT FROM v13_goal_hash(p_sid) THEN
    RAISE EXCEPTION 'v13: belt guard: goal hash drift (V3007)'
      USING ERRCODE = 'V3007';
  END IF;
  v_a := jsonb_array_length(coalesce(p_full, '[]'::jsonb));
  v_b := jsonb_array_length(coalesce(p_mat, '[]'::jsonb));
  IF v_action = 'tail' THEN
    -- 规则 2:p_mat 是 p_full 的真后缀(等长尾部逐元素 jsonb 相等且更短)
    IF v_b >= v_a OR EXISTS (SELECT 1 FROM generate_series(0, v_b - 1) i
                               WHERE p_full->(v_a - v_b + i) IS DISTINCT FROM p_mat->i) THEN
      RAISE EXCEPTION 'v13: belt guard: tail is not a true suffix (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    -- 尾部 user/message 计数=least(keep,全文计数)且全文计数>keep
    SELECT count(*) INTO v_ufull FROM jsonb_array_elements(p_full) e
     WHERE e->>'type' = 'user/message';
    SELECT count(*) INTO v_umt FROM jsonb_array_elements(p_mat) e
     WHERE e->>'type' = 'user/message';
    IF v_ufull <= v_keep OR v_umt <> least(v_keep, v_ufull) THEN
      RAISE EXCEPTION 'v13: belt guard: tail turn count mismatch (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    -- manifest 恰一个 applied summary 段(name='summarize');无 compaction 段
    SELECT count(*) INTO v_a FROM jsonb_array_elements(p_manifest->'sections') s
     WHERE s->>'kind' = 'summary' AND (s->'transform'->>'applied')::boolean
       AND s->'transform'->>'name' = 'summarize';
    IF v_a <> 1 THEN
      RAISE EXCEPTION 'v13: belt guard: adopted needs one summarize section (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    PERFORM 1 FROM jsonb_array_elements(p_manifest->'sections') s
     WHERE s->>'kind' = 'compaction';
    IF FOUND THEN
      RAISE EXCEPTION 'v13: belt guard: compaction section under adopted (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    -- v13_summary_section_material 哈希==summary 段 content_hash
    SELECT s->>'content_hash' INTO v_h
      FROM jsonb_array_elements(p_manifest->'sections') s
     WHERE s->>'section_id' = 'summary';
    IF v_h IS DISTINCT FROM encode(digest(coalesce(
          v13_summary_section_material(p_sid)::text, ''), 'sha256'), 'hex') THEN
      RAISE EXCEPTION 'v13: belt guard: summary material hash drift (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    -- canonical 前缀的 v13_span_digest==该 effect request 冻结 span_digest
    v_tailb := CASE WHEN (SELECT count(*) FROM jsonb_array_elements(p_full) e
                            WHERE e->>'type' = 'user/message') >= v_keep
                    THEN (SELECT min((t.e->>'seq')::bigint)
                            FROM (SELECT e FROM jsonb_array_elements(p_full) e
                                   WHERE e->>'type' = 'user/message'
                                   ORDER BY (e->>'seq')::bigint DESC
                                   LIMIT v_keep) t(e))
               END;
    SELECT v13_span_digest(coalesce(jsonb_agg(
             to_jsonb(encode(digest(coalesce(m::text, ''), 'sha256'), 'hex'))
             ORDER BY (m->>'seq')::bigint), '[]'::jsonb))
      INTO v_sd
      FROM jsonb_array_elements(p_full) m
     WHERE v_tailb IS NOT NULL AND (m->>'seq')::bigint < v_tailb;
    SELECT * INTO v_ceff FROM effects
     WHERE session_id = p_sid AND kind = 'context_summary'
       AND status = 'succeeded'
     ORDER BY created_at DESC, effect_id DESC LIMIT 1;
    IF v_ceff.effect_id IS NULL
       OR v_ceff.request->>'span_digest' IS DISTINCT FROM v_sd THEN
      RAISE EXCEPTION 'v13: belt guard: adopted span digest stale (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  ELSE
    -- 规则 3(回退族):manifest 无 summary 段
    PERFORM 1 FROM jsonb_array_elements(p_manifest->'sections') s
     WHERE s->>'kind' = 'summary';
    IF FOUND THEN
      RAISE EXCEPTION 'v13: belt guard: summary section under fallback (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    -- history transform={applied:true,name:'spill'}
    SELECT s->'transform' INTO v_tr FROM jsonb_array_elements(p_manifest->'sections') s
     WHERE s->>'section_id' = 'history' AND s->>'kind' = 'history';
    IF v_tr IS DISTINCT FROM
         jsonb_build_object('applied', true, 'name', 'spill') THEN
      RAISE EXCEPTION 'v13: belt guard: fallback history transform (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
    IF v_action IN ('round_drop', 'final_trim') THEN
      PERFORM 1 FROM jsonb_array_elements(p_manifest->'sections') s
       WHERE s->>'kind' = 'compaction'
         AND s->'transform'->>'reason' = 'compaction_round_drop';
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v13: belt guard: drop without trace section (V3007)'
          USING ERRCODE = 'V3007';
      END IF;
    END IF;
    IF v_action = 'final_trim' THEN
      -- 三级不跳级:final_trim 在场 ⇒ 前缀 round 已全部被丢(p_mat 无
      -- protected tail 之外的元素)+ trim 段在场
      v_tailb := CASE WHEN (SELECT count(*) FROM jsonb_array_elements(p_full) e
                              WHERE e->>'type' = 'user/message') >= v_keep
                      THEN (SELECT min((t.e->>'seq')::bigint)
                              FROM (SELECT e FROM jsonb_array_elements(p_full) e
                                     WHERE e->>'type' = 'user/message'
                                     ORDER BY (e->>'seq')::bigint DESC
                                     LIMIT v_keep) t(e))
                 END;
      IF v_tailb IS NOT NULL AND EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_mat) m
            WHERE (m->>'seq')::bigint < v_tailb) THEN
        RAISE EXCEPTION 'v13: belt guard: final_trim skipped round_drop (V3007)'
          USING ERRCODE = 'V3007';
      END IF;
      PERFORM 1 FROM jsonb_array_elements(p_manifest->'sections') s
       WHERE s->>'kind' = 'compaction'
         AND s->'transform'->>'reason' = 'compaction_final_trim';
      IF NOT FOUND THEN
        RAISE EXCEPTION 'v13: belt guard: final_trim without trace section (V3007)'
          USING ERRCODE = 'V3007';
      END IF;
    ELSE
      PERFORM 1 FROM jsonb_array_elements(p_manifest->'sections') s
       WHERE s->>'kind' = 'compaction'
         AND s->'transform'->>'reason' = 'compaction_final_trim';
      IF FOUND THEN
        RAISE EXCEPTION 'v13: belt guard: trim trace under non-trim action (V3007)'
          USING ERRCODE = 'V3007';
      END IF;
    END IF;
    -- p_mat 中每条非 tool 消息是 p_full 同序相等元素(seq 唯一⇒同序);
    -- tool/result 或与原文相等或为 stub(含 effect_id、不含原 body)
    IF EXISTS (
      SELECT 1 FROM jsonb_array_elements(p_mat) m
       WHERE CASE WHEN m->>'type' <> 'tool/result'
                  THEN NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_full) g
                                    WHERE (g->>'seq')::bigint = (m->>'seq')::bigint
                                      AND g = m)
                  ELSE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_full) g
                                    WHERE (g->>'seq')::bigint = (m->>'seq')::bigint
                                      AND (g = m OR (
                                           (m->'payload') ? 'stub'
                                       AND (m->'payload') ? 'effect_id'
                                       AND NOT (m->'payload') ? 'result'
                                       AND (m->'payload'->>'tool')
                                           IS NOT DISTINCT FROM (g->'payload'->>'tool'))))
             END) THEN
      RAISE EXCEPTION 'v13: belt guard: material not canonical projection (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  END IF;
END $$;

-- === 换体:OR REPLACE assemble v3(已授权再跳;消费增量——summary 段+
--     history 收缩+回退链动作层+economics.summary 块)。机械复制 economy
--     加载态 v2 体裁,增量以 [DP7-S] 标注:sec_src 走单源材料函数(CASE
--     full=economy 原表达式);压力/tier/er/hint 改读全量候选基面
--     (fcls/ford——值与 v2 恒等:决策记录=压缩前事实);装箱/段产额读
--     动作后基面(cls/ordered);jud 消费集+采纳 summary decision。 ===
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
SELECT jsonb_build_object(
  'manifest_version', 2,
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
                  FROM final_sec),
  'query_side',(SELECT q FROM qside),
  'judgments', (SELECT j FROM jud),
  'replay',    jsonb_build_object('mode', (SELECT m FROM mode),
                                  'prior_artifact_id', (SELECT aid FROM pri)));
$$;

-- === 换体:OR REPLACE validate v3(已授权再跳;economy v2 原文+增量:
--     kind 词表+summary/compaction;transform name +{summarize,spill};
--     reason +{summary_unavailable,summary_rejected,compaction_round_drop,
--     compaction_final_trim};economics 键集 +summary;summary 子块键集执法;
--     belt 层:payload_ref 跨字段恒等/section_id 全局唯一/consumed⇔summary
--     段双向一致/adopted 形状/回退 recipe 闭集。不新增「history 哈希必须
--     等于 canonical 全文」类断言——合法尾段不得被拒) ===
CREATE OR REPLACE FUNCTION v13_manifest_validate(p_manifest jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb; j jsonb; c jsonb; e jsonb; n int; m int; sb jsonb;
        v_ops text; v_cons boolean; v_fb boolean; v_dupt text;
BEGIN
  IF p_manifest IS NULL OR jsonb_typeof(p_manifest) IS DISTINCT FROM 'object'
  THEN
    RAISE EXCEPTION 'v13: manifest must be a jsonb object (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(p_manifest) k)
     IS DISTINCT FROM
     'economics,judgments,manifest_version,policy,prefix_identity,query_side,'
     'replay,required_revision,sections,session_id,turn_no' THEN
    RAISE EXCEPTION 'v13: manifest top-level key set mismatch (V3003)'
      USING ERRCODE = 'V3003';
  END IF;
  IF (p_manifest->>'manifest_version')::int IS DISTINCT FROM 2
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
     'asm_ver,corpus,dec,econ_ver,gen_ver,goal,jdef_ver,recall_ver,sem,tools_rev'
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
     OR p_manifest->'required_revision'->>'econ_ver' !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'v13: manifest.required_revision shape violation (V3003)'
      USING ERRCODE = 'V3003';
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
       OR (s->>'kind') IN ('goal','history','tools','summary','compaction')
          IS NOT TRUE
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
                     IN ('verbatim','catalog_digest','summarize','spill')
                     IS NOT TRUE
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

-- === 换体:OR REPLACE refresh v3(裁决授权的第 8 处换体,文件 13 内第 3 处;
--     复制源=economy 加载态;diff 允许清单 §3.2.4 恰四项:[DP7-S] 标注——
--     ①锁集 name IN 增 'summary_accept';②(可选)adopted context_summary
--     行 FOR SHARE(pricing 锁后、形状守卫前,零行合法);③history belt IF
--     包裹(IF 臂=economy 原文四行逐字含 V3003;ELSE=单源材料+guard+
--     V3007;调度条件用哈希相等而非读 action——未变形含 actions off ⇒
--     全文哈希==段哈希 ⇒ 走 IF 臂 ⇒ v1 生产与文件 12 字节同路径);
--     ④tools belt 后 summary belt。其余(e入口校验/锁序骨架/形状守卫
--     全文/装配-校验-inline 调用序/complete CAS/tools belt 全文/
--     artifact_land/result 补挂/sessions 指针/返回值)economy 加载态
--     逐字) ===
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
   WHERE name IN ('assemble_manifest','generation','judgment_defaults',
                  'context_tiers','context_budget','summary_accept')
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
    IF v_rp IS NULL OR jsonb_typeof(v_rp->'renderer') IS DISTINCT FROM 'string'
       OR length(btrim(v_rp->>'renderer')) = 0 THEN
      RAISE EXCEPTION 'v13: render_policy policy shape invalid (V3007)'
        USING ERRCODE = 'V3007';
    END IF;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range
              OR invalid_parameter_value THEN
    RAISE EXCEPTION 'v13: economics policy rows malformed (V3007)'
      USING ERRCODE = 'V3007';
  END;

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

  v_art := public.v13_artifact_land(p_effect, 'context', v_manifest);
  UPDATE public.effects SET result = coalesce(result,'{}'::jsonb) ||
           jsonb_build_object('context_artifact_id', v_art)
   WHERE effect_id = p_effect;
  UPDATE public.sessions
     SET context_active_revision = v_manifest->'required_revision',
         context_active_artifact = v_art
   WHERE session_id = v_sid;
  RETURN 'accepted';
END $$;

-- === ACL 全量块(文件真末尾;不变量 12;四新 helper 逐件 REVOKE PUBLIC;
--     (a)(b)(c) 授予与 v13_assemble_manifest 相同的只读角色;(d) 仅
--     owner——refresh DEFINER 体内调用时即 owner,不授 route;helper 一律
--     SECURITY INVOKER,不做第二套 DEFINER 入口) ===
REVOKE EXECUTE ON FUNCTION
  v13_span_digest(jsonb),
  v13_summary_checks(text,jsonb,int),
  v13_summary_envelope(uuid,text,text,text),
  v13_summary_verdict(uuid),
  v13_summary_schedule(uuid),
  v13_history_action(uuid),
  v13_history_section_material(uuid),
  v13_summary_section_material(uuid),
  v13_history_belt_guard(uuid,jsonb,jsonb,jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_span_digest(jsonb),
  v13_history_action(uuid), v13_history_section_material(uuid),
  v13_summary_section_material(uuid)
TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION v13_summary_checks(text,jsonb,int),
  v13_summary_schedule(uuid)
TO v13_route;
GRANT EXECUTE ON FUNCTION v13_summary_envelope(uuid,text,text,text),
  v13_summary_verdict(uuid)
TO v13_resolve;
-- OR REPLACE 三件(assemble/validate/refresh)ACL 经 OID 保留,不重授。

COMMIT;
