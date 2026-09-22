BEGIN;

-- =========================================================================
-- DP7 economy (v13_economy.sql): policy rows + pricing catalog + derived
-- economics (R_o percentile / pressure / tier bands / E(r)) + parse spend
-- gate + manifest v2 economics half (11 outer keys / 7-key policy block /
-- 10-key token incl. econ_ver / three-bucket packing / cache-break
-- attribution). Design: docs/designs/v13-context-on-pg.md
-- §5.4/§5.5/§6.2 touchpoint-1 shadow/§9/§10 G-ctx6 (round-2 corrected
-- semantics; the frozen §10 wording "tier only rises across turns" is
-- superseded per user ruling — single-Plan monotonic + cross-turn
-- hysteresis). Plan: docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md
-- §3.1. Contracts: DP1 §1.3 DP7 row, DP2/DP3/DP5/DP6 §1.4 DP7 rows.
-- File order = load order. Error code family: V3007.
-- Implementation discipline: the five OR REPLACE bodies (v13_parse /
-- v13_context_required / v13_assemble_manifest / v13_manifest_validate /
-- v13_refresh_context) are mechanical copies of the LATEST LOADED-STATE
-- text (v13/resolve/v13_resolve.sql for parse; v13/recall/v13_recall.sql
-- for context_required and manifest_validate; v13/filter/v13_filter.sql
-- for assemble_manifest; v13/manifest/v13_manifest.sql for
-- refresh_context) edited only at the [DP7] markers below. Zero
-- bind-operator literals, zero engine-qualified names, zero judgment-IO
-- references (gate A5).
-- =========================================================================

-- === 策略行五行(v13_policies 载体,DP1 §1.3 DP7 行;INSERT 即 active——
--     新 name 无 active 冲突;种子纪律:单完整 JSON 字面量+::jsonb) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('context_tiers', 1, '{
  "bands": [
    {"lo_bp": 0,    "hi_bp": 6000, "tier": "Normal"},
    {"lo_bp": 6000, "hi_bp": 7500, "tier": "TrimSchemas"},
    {"lo_bp": 7500, "hi_bp": 9000, "tier": "CompactHistory"},
    {"lo_bp": 9000, "hi_bp": null, "tier": "AggressivePrune"}
  ],
  "actions_enabled": false,
  "hysteresis": {"cooldown_turns": 2, "max_downgrade_steps": 1},
  "r_o": {"p_steady": 0.75, "p_recovery": 0.95, "min_samples": 20,
          "cold_tokens": 8192, "recovery_turns": 2},
  "note": "0.60/0.75/0.90=shadow seed (design §5.4 round 2: local calibration before actions); r below r*=0.145 means compaction loses money (ContextPipe break-even; er.branch carries it)"
}'::jsonb, true),
('context_budget', 1, '{
  "buckets": {"core": 0.35, "history": 0.55, "retrieval": 0.10},
  "l_eff_tokens": 128000,
  "keep_tail_turns": 2,
  "hard_window_bp": 10000,
  "note": "three buckets ACTIVE at v1 (deterministic packing, no calibration dependency); l_eff_tokens=mock truth; DP8 generation row migrates to single-source via a new version row"
}'::jsonb, true),
('judge_spend_gate', 1, '{
  "session_asks_cap": 512, "day_asks_cap": 8192,
  "scope": "fast_path",
  "seed_note": "generous seed = de-facto shadow (DP6 one-pager worst case 12 asks/turn; the gate only seals the F5 zero-turn spend cliff); over gate = cache-only + gaps to slow path; tighten = new active version"
}'::jsonb, true),
('fastpath_tiers', 1, '{
  "tiers_over_one_batch": [],
  "note": "F5-3: v1 no tier may exceed one fast-path batch; widening = this row + resolve_fast_path v2 in the same batch + reopen the one-pager (README) — missing any one forbids the flip"
}'::jsonb, true),
('render_policy', 1, '{
  "renderer": "canonical", "cache_markers": true,
  "provider_policy": "protocol_only",
  "note": "§5.3 first-version single canonical render; presentation preference not legislated; DP8 consumes — on landing day the version joins prefix_identity material + token (chase-key seam)"
}'::jsonb, true);

-- === 定价目录(§5.4 r 三纪律的载体;运维参考目录,非 usage 真相源——
--     usage 在 effects/judgment_calls,不变量 6) ===
CREATE TABLE v13_pricing (
  provider  text NOT NULL,
  model     text NOT NULL,
  account   text NOT NULL DEFAULT 'default',
  cache_class text NOT NULL DEFAULT 'default',
  fresh_usd_per_mtok  numeric(12,6) NOT NULL CHECK (fresh_usd_per_mtok > 0),
  cached_usd_per_mtok numeric(12,6) NOT NULL CHECK (cached_usd_per_mtok >= 0),
  catalog_version int NOT NULL CHECK (catalog_version >= 1),
  effective_from timestamptz,   -- ops/audit metadata (planned window); the
                                -- currently applicable row is the active
                                -- flag (OQ5: zero clocks in assembly)
  effective_to   timestamptz,
  active    boolean NOT NULL DEFAULT false,
  PRIMARY KEY (provider, model, account, cache_class, catalog_version)
);
CREATE UNIQUE INDEX ux_v13_pricing_one_active
  ON v13_pricing (provider, model, account, cache_class) WHERE active;

-- append-only (mirror v13_policies_frozen): the only permitted UPDATE is
-- flipping active; version rows are the audit trail
CREATE FUNCTION v13_pricing_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'UPDATE' OR (NEW.provider,NEW.model,NEW.account,NEW.cache_class,
                           NEW.catalog_version,NEW.fresh_usd_per_mtok,
                           NEW.cached_usd_per_mtok,
                           NEW.effective_from,NEW.effective_to)
                        IS DISTINCT FROM
                           (OLD.provider,OLD.model,OLD.account,OLD.cache_class,
                            OLD.catalog_version,OLD.fresh_usd_per_mtok,
                            OLD.cached_usd_per_mtok,
                            OLD.effective_from,OLD.effective_to) THEN
    RAISE EXCEPTION 'v13: v13_pricing is append-only (new catalog_version rows, not % on %)',
      TG_OP, TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_pricing_frozen
  BEFORE UPDATE OR DELETE ON v13_pricing
  FOR EACH ROW EXECUTE FUNCTION v13_pricing_frozen();

-- === 定价目录种子(P1-2):一行 mock 值——五维与 generation 活动 mock 行同
--     provider/model(DP3 'mock'/'mock-1'),account/cache_class=default;
--     r=cached/fresh=0.25(>r*=0.145 的稳态可压缩 mock 档——loss/r_unknown
--     分支演练用翻版构造,种子不预置);fresh>0/cached>=0 由表 CHECK 执法;
--     catalog_version=1(=economics.er.r_source 记录的来源版本);
--     effective_from/to=规划区间元数据(当前适用行=active 标志——OQ5 零
--     时钟);翻版=新 catalog_version 行 INSERT inactive→双 UPDATE 同事务翻
--     active(README 仪式)。 ===
INSERT INTO v13_pricing (provider, model, account, cache_class,
                         fresh_usd_per_mtok, cached_usd_per_mtok,
                         catalog_version, effective_from, effective_to, active)
VALUES ('mock', 'mock-1', 'default', 'default',
        3.000000, 0.750000, 1, '2026-09-20 00:00:00+00'::timestamptz, NULL, true);

-- r=派生比值,单源(OQ5;零存储冗余——哈希/公式同源纪律)
CREATE FUNCTION v13_pricing_r(p_provider text, p_model text,
                               p_account text DEFAULT 'default',
                               p_cache_class text DEFAULT 'default')
RETURNS numeric LANGUAGE sql STABLE AS $$
  SELECT cached_usd_per_mtok / fresh_usd_per_mtok
   FROM v13_pricing
   WHERE provider = p_provider AND model = p_model
     AND account = p_account AND cache_class = p_cache_class AND active;
$$;

-- === 恢复期判定单源(P1-3;v13_ro_reserve 与装配 recovery_floor 双消费——
--     哈希/公式同源纪律,零复制谓词) ===
-- 窗口=OQ3/OQ4 声明:「最近 recovery_turns(context_tiers.r_o.recovery_turns)
-- 个 user turn 内存在 prompt-too-long 类失败」。窗起点=按 seq 倒数第
-- recovery_turns 个 user/message 边界的 created_at(边界不足 recovery_turns
-- 个⇒全部历史——冷启动 fail-safe 方向:宁可多预留);跨 turn 可见:turn N
-- 失败在 turn N+1(恢复 turn,恰最高危 turn)仍在窗内;码表=
-- prompt_too_long/context_length(随实施期 worker 契约实测钉定;码表外
-- 失败不触发 floor,fail-open 到稳态);error 为 NULL⇒IN 谓词三值 NULL⇒
-- 不计(三值安全)。
CREATE FUNCTION v13_recovery_active(p_sid uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM effects e
     WHERE e.session_id = p_sid AND e.kind = 'llm' AND e.status = 'failed'
       AND e.error->>'code' IN ('prompt_too_long','context_length')
       AND e.created_at >= (
         SELECT coalesce(min(b.created_at), '-infinity'::timestamptz)
           FROM (SELECT ev.at AS created_at
                   FROM events ev
                  WHERE ev.session_id = p_sid AND ev.type = 'user/message'
                    AND ev.seq <= v13_last_user_seq(p_sid)
                  ORDER BY ev.seq DESC
                  LIMIT (SELECT (v13_policy('context_tiers')->'r_o'->>'recovery_turns')::int)) b))
$$;

-- === R_o 输出预留分位(§5.4/§5.5;(model,source) 桶 source=effects.kind,
--     附 A #3) ===
CREATE FUNCTION v13_ro_reserve(p_sid uuid)
RETURNS bigint LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb := v13_policy('context_tiers');
        v_recovery boolean; v_pct numeric; v_n bigint;
        v_ro double precision; v_model text;
BEGIN
  -- 恢复期判定(单源=v13_recovery_active——本函数与装配 recovery_floor
  -- 双消费,P1-3;窗口=最近 recovery_turns 个 user turn 边界,跨 turn 可见)
  v_recovery := v13_recovery_active(p_sid);
  v_pct := CASE WHEN v_recovery THEN (v_pol->'r_o'->>'p_recovery')::numeric
                ELSE (v_pol->'r_o'->>'p_steady')::numeric END;
  -- 模型单源:generation 活动行(与 prefix_identity 材料同源,DP3 OQ4)
  SELECT value->>'model' INTO v_model FROM v13_policies
   WHERE name = 'generation' AND active;
  -- 桶=该 model 全局 succeeded 历史样本(分位是跨会话统计,§5.4「该
  -- (model,source) 桶历史 llm effect usage」原文;source=effects.kind——
  -- 附 A #3);**不按 session 过滤**;p_sid 仅用于恢复期判定(参数全用)。
  -- model 谓词读 **result 侧**(P0-1 修):DP1 ④ llm 分支 enqueue 的
  -- request 恒 {route:{action,reason}} 零 model 键——request 侧谓词在
  -- 生产面恒 NULL=恒空桶=永久冷启动;result->>'model' 为 NULL 的行被谓词
  -- 排除(缺失=无样本,不是错样本)。
  SELECT count(*),
         percentile_cont(v_pct) WITHIN GROUP
           (ORDER BY ((result->'usage'->>'completion_tokens')::bigint))
    INTO v_n, v_ro
    FROM effects
   WHERE kind = 'llm' AND status = 'succeeded'
     AND result->>'model' = v_model
     AND result->'usage'->>'completion_tokens' ~ '^[0-9]+$';
  -- §5.5 失败样本排除由 status='succeeded' 谓词结构性保证(failed/unknown
  -- 零进样本;usage/model 缺失/非数值行同样零进样本——worker 契约「llm
  -- result 应携 usage+model;缺失=无样本,不是错样本」)
  IF v_n < (v_pol->'r_o'->>'min_samples')::int THEN
    RETURN (v_pol->'r_o'->>'cold_tokens')::bigint;
      -- 空桶冷启动 fail-safe(OQ3:宁可过度预留,不可预留不足——预留不足的
      -- 失败模式是 prompt-too-long 硬失败,其恢复循环正是 §5.5 点名要防的
      -- 分位毒化面;过度预留的代价只是压力读数偏高、早一档进压缩带)
  END IF;
  RETURN coalesce(v_ro::bigint, (v_pol->'r_o'->>'cold_tokens')::bigint);
END $$;

-- === 花费计数(F5-1;judgment_calls 单源,含 filter 族/摘要验收 ask——
--     DP2/DP6 契约①;计数无 signal 过滤=全 calls) ===
CREATE FUNCTION v13_judge_spend(p_sid uuid)
RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'session_asks', (SELECT count(*) FROM judgment_calls WHERE session_id = p_sid),
    'day_asks',     (SELECT count(*) FROM judgment_calls
                      WHERE session_id = p_sid
                        AND created_at >= date_trunc('day', now())),
    'over', ((SELECT count(*) FROM judgment_calls WHERE session_id = p_sid)
               >= (v13_policy('judge_spend_gate')->>'session_asks_cap')::int
             OR (SELECT count(*) FROM judgment_calls
                  WHERE session_id = p_sid
                    AND created_at >= date_trunc('day', now()))
               >= (v13_policy('judge_spend_gate')->>'day_asks_cap')::int));
$$;
-- 注:本函数读 now()——它属 parse/驱动平面(非装配平面),零时钟纪律不适用
-- (不变量 7 只罩装配与 economy 派生)。日闸作用域=per-session 每日
-- (day_asks 带 session_id 过滤——F5-1 单 session 零 turn 刷花费的攻击面
-- 已覆盖;若意图是账户级日闸=未来 scope 翻版,README 呈报在案)。

-- === econ_ver 单源(token 追动键材料;OQ7)——只罩 assembly 消费的经济学
--     行(context_tiers/context_budget——改变 transform 选择=manifest 内容
--     的行);pricing/spend gate/render_policy/fastpath_tiers 不入 token
--     (逐行论证,plan 不变量 8)。未来经济学行加入 assembly 消费集=改此
--     函数一处+自然追动,键集形状不变。 ===
CREATE FUNCTION v13_econ_ver() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT encode(digest(
    (SELECT string_agg(name || ':' || version::text, ',' ORDER BY name)
       FROM v13_policies
      WHERE name IN ('context_tiers','context_budget') AND active)
  , 'sha256'), 'hex');
$$;

-- === tier 辅助单源(band 路由/档位序;bandm 形状由 refresh 守卫执法:
--     连续递增半开区间⇒band_of 确定性) ===
CREATE FUNCTION v13_band_of(p_bands jsonb, p_bp bigint)
RETURNS text LANGUAGE sql STABLE AS $$
  SELECT b->>'tier'
   FROM jsonb_array_elements(p_bands) b
  WHERE p_bp >= (b->>'lo_bp')::int
    AND (NULLIF(b->>'hi_bp', '')::int IS NULL OR p_bp < NULLIF(b->>'hi_bp', '')::int)
  LIMIT 1;
$$;
CREATE FUNCTION v13_tier_rank(p_tier text) RETURNS int
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE p_tier WHEN 'Normal' THEN 1 WHEN 'TrimSchemas' THEN 2
                     WHEN 'CompactHistory' THEN 3
                     WHEN 'AggressivePrune' THEN 4 ELSE NULL END;
$$;

-- === cache-break 归因(§5.4:一条 SQL,不是启发式) ===
-- 输入:当前 active manifest vs 其链上前驱(manifest.replay.prior_artifact_id);
-- 输出:逐 section content_hash diff+首断点后缀(断点后全部段重计费面);
-- churn(DP3)为输入,归因是消费(单源输入互证,gate F3)。
CREATE FUNCTION v13_cache_breaks(p_sid uuid)
RETURNS TABLE(section_id text, prior_hash text, cur_hash text,
              broke boolean, rebill_suffix boolean)
LANGUAGE sql STABLE AS $$
  WITH cur AS (
    SELECT a.inline AS m FROM artifacts a
     WHERE a.artifact_id = (SELECT context_active_artifact FROM sessions WHERE session_id = p_sid)
  ), pri AS (
    SELECT a.inline AS m FROM artifacts a, cur
     WHERE a.artifact_id = (cur.m->'replay'->>'prior_artifact_id')::uuid
  ), sec AS (
    SELECT s->>'section_id' AS section_id, s->>'content_hash' AS ch,
           (x.prio) AS prank
      FROM cur, jsonb_array_elements(cur.m->'sections') AS s,
           LATERAL (SELECT CASE s->>'priority' WHEN 'First' THEN 1 WHEN 'Normal' THEN 2
                        WHEN 'Never' THEN 3 WHEN 'LastResort' THEN 4 END AS prio) x
  ), pri_sec AS (
    SELECT p->>'section_id' AS section_id, p->>'content_hash' AS ch
      FROM pri, jsonb_array_elements(pri.m->'sections') AS p
  ), d AS (
    SELECT sec.section_id, COALESCE(pri_sec.ch, '') AS prior_hash, sec.ch AS cur_hash,
           sec.prank,
           (pri_sec.ch IS DISTINCT FROM sec.ch) AS broke
             -- 无前版段=新段(hash '')⇒broke=true(新增即断)
      FROM sec LEFT JOIN pri_sec USING (section_id)
  ), ranked AS (
    SELECT d.*, row_number() OVER (ORDER BY prank, section_id) AS rn FROM d
  ), first_break AS (
    SELECT min(rn) AS rn FROM ranked WHERE broke
  )
  SELECT r.section_id, NULLIF(r.prior_hash,''), r.cur_hash, r.broke,
         (r.rn > COALESCE(first_break.rn, 2147483647)) AS rebill_suffix
    FROM ranked r CROSS JOIN first_break
   ORDER BY r.prank, r.section_id;
$$;

-- === 换体一:v13_context_required +econ_ver(OQ1 追动键缝扩集) ===
-- 复制源=SQL_LOAD_ORDER 最新前驱加载态(文件 8 v13_recall.sql 九键体:
-- DP3 七键+DP4 corpus+DP5 recall_ver;经 9/10/11 号零改动——非 DP3 §3.2
-- 原文,turn 33 终检 P1 修正);唯一增量=顶层 jsonb_build_object 追加一键:
--   'econ_ver', v13_econ_ver()
-- 既有九键表达式逐字不动;键集 9→10⇒全域恰一次 refresh(OQ1 语义,预期内);
-- DP8 在其 14 号文件恢复十一键全谱。
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
  SELECT version INTO v_gen_ver FROM v13_policies
   WHERE name = 'generation' AND active;
  IF v_gen_ver IS NULL THEN
    RAISE EXCEPTION 'v13: no active generation policy (seed lost?)';
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
    'econ_ver', v13_econ_ver())                       -- [DP7] 唯一增量
  INTO v_tok;
  RETURN v_tok;
END $$;

-- === 换体二:v13_parse 前置花费闸(OQ6;唯一增量=入口后置一分支) ===
-- 机械复制 DP1 §3.4 加载态原文(v13_resolve.sql);增量仅 [DP7] 标注段:
-- 过闸⇒跳过 resolve 调用(零新增 ask),信封/快照构造逐字保留,remaining
-- 改由 v13_gap 信封缺口计数单源求值(已答行非缺口——缓存命中在 advance ③
-- 缺口 join 处自然消费);返回结构与未过闸一致——advance ③ 看到
-- remaining>0 即建 judge effect 交慢路(原路径,零改动)。未过闸路径与
-- DP1 行为逐字节等价(gate G1 回归断言)。
CREATE OR REPLACE FUNCTION v13_parse(p_sid uuid) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_env jsonb; v_snap jsonb; v_max int; v_cap int; v_failures int; v_res jsonb;
  v_remaining int;                                          -- [DP7]
BEGIN
  v_env := v13_judgment_envelope(p_sid);       -- 一次性物化(P0-2)
  v_snap := v13_snap_of(v_env);
  -- 防重试风暴(§4.3「事件计数防重试风暴」):自最近 user/message 以来的
  -- resolve/failed 事件数达 cap → 放弃分支,零新增 Jev 调用(「放弃零 Jev
  -- 调用」的预算形态;已发出的调用可能已计费——措辞纪律照 §6.4 第 8 条)
  v_failures := (SELECT count(*) FROM events
                  WHERE session_id = p_sid AND type = 'resolve/failed'
                    AND (payload->>'origin_user_seq')::bigint
                        = v13_last_user_seq(p_sid));
  v_cap := (v13_policy('resolve_retry')->>'cap')::int;
  IF v_failures >= v_cap THEN
    RETURN jsonb_build_object('snap', v_snap, 'envelope', v_env,
               'abandon', true, 'asked_batches', 0, 'asked_questions', 0,
               'remaining', v_snap->'gap_count', 'failed', false);
  END IF;
  -- [DP7] F5-1 解析相花费闸(仅快路;OQ6):超闸只走缓存、缺口转慢路。
  -- 判定单源=v13_judge_spend(计数含 filter 族与摘要验收 ask);
  -- remaining=v13_gap 同源缺口计数(与 resolve 内部同一谓词——DP1 §3.2
  -- 单一事实源);零新增 judgment_calls 行(「零新增调用≠零成本」措辞纪律)。
  IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
    v_remaining := jsonb_array_length(v13_gap(v_env));
    RETURN jsonb_build_object('snap', v_snap, 'envelope', v_env,
               'abandon', false, 'asked_batches', 0, 'asked_questions', 0,
               'remaining', v_remaining, 'failed', false);
  END IF;
  -- 快路上限=策略行,单位是批(§4.3:默认 ≤1 批 ≤32 问)
  v_max := (v13_policy('resolve_fast_path')->>'max_batches')::int;
  v_res := v13_resolve_judgments(v_env, v_max);
  RETURN jsonb_build_object('snap', v_snap, 'envelope', v_env,
             'abandon', false,
             'asked_questions', v_res->'asked_questions',
             'asked_batches',   v_res->'asked_batches',
             'remaining',       v_res->'remaining',
             'failed',          v_res->'failed');
END $$;

-- === 换体三:v13_assemble_manifest v2(economy 半边;两参签名不动) ===
-- 复制加载态最新前驱(文件 10 v13_filter.sql,DP6 形态——含 DP5 L7
-- candidates 换源/goal echo 退役/decision_id 键与 DP6 墓碑四 decision_id
-- 填充、judgments final_action 真值·消费集∪存在性行、rc2·fc 单源过滤
-- trace 增量;DP3 §3.4 原文非复制源,turn 33 终检 P1 修正)+以下 [DP7]
-- 增量(注释处逐条锚定,plan §3.1 换体三 (a)–(h)):
--   (a) 策略读扩:context_tiers/context_budget/generation 五维/pricing;
--   (b) est 表达式零改(DP3 原文;消费清单 #4);
--   (c) 装箱改三桶(effective_budget=least(budget,l_eff−R_o);桶
--       core={goal,tools}/history={history}/retrieval={其余未来 kind});
--   (d) economics 块(pressure/tier raw+effective+basis/er/buckets/
--       compact_hint——OQ3/OQ4/OQ5 公式全量落内);
--   (e) policy 块 4→7 键(+tiers/budget/pricing_version);
--   (f) required_revision 零编辑(换体一后自动 10 键含 econ_ver);
--   (g) manifest_version 1→2;其余九外层键表达式零改;
--   (h) 装配确定性:零时钟(pricing 经 active 标志)/零随机/锁内同版。
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
         (SELECT (q.value->>'provider') FROM v13_policies q
           WHERE q.name = 'generation' AND q.active) AS gen_provider,
         (SELECT (q.value->>'model') FROM v13_policies q
           WHERE q.name = 'generation' AND q.active) AS gen_model
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
), chain AS (                            -- [DP7](d) artifact 链(hysteresis
  SELECT a.inline AS m, 0 AS depth       -- 派生面;深度上限 16=cooldown 窗
    FROM artifacts a                     -- 的宽松上界,超出=保守 hold)
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
  FROM sec_src r, pol
), econ0 AS MATERIALIZED (                -- [DP7](a)(c) 经济派生输入单点
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
), packed AS MATERIALIZED (               -- [DP7](c) 三桶装箱(骨架逐字:
  SELECT c.section_id, c.bkind,           -- Never/disabled 先 skip 不进装箱)
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
), press AS MATERIALIZED (                -- [DP7](d) 压力(纯 int 基点算术)
  SELECT (SELECT coalesce(sum(est_tokens), 0) FROM cls
           WHERE pre_skip IS NULL) AS t_used,
         econ0.ro, econ0.l_eff,
         (((SELECT coalesce(sum(est_tokens), 0) FROM cls
             WHERE pre_skip IS NULL) + econ0.ro) * 10000 / econ0.l_eff)::bigint AS bp,
         econ0.hard_bp
  FROM econ0
), dlt AS MATERIALIZED (                  -- [DP7](d) predicted 增量:本 turn
  SELECT coalesce(sum(((octet_length(e.payload::text) + pol.divisor - 1)  -- 新增语义事件
                       / pol.divisor)), 0)::bigint AS delta_est            -- est 同公式
    FROM pri, pol, events e                                              -- 折算
   WHERE pri.m IS NOT NULL
     AND e.session_id = p_sid
     AND e.type IN ('user/message','llm/message','tool/result')
     AND e.seq > (pri.m->'required_revision'->>'sem')::bigint
), pred AS MATERIALIZED (                 -- [DP7](d) 上一版 manifest 压力经
  SELECT CASE                            -- 增量折算(首版/跨 Plan 无 prior
           WHEN pri.m IS NULL             -- ⇒raw——防同 turn 重装配降级)
                OR pri.m->'economics' IS NULL
                OR (pri.m->>'turn_no')::int IS DISTINCT FROM
                   (SELECT turn_no FROM sessions WHERE session_id = p_sid)
             THEN NULL
             ELSE ((((pri.m->'economics'->'pressure'->>'t_used')::bigint
                      + dlt.delta_est) + press.ro) * 10000 / press.l_eff)::bigint
         END AS bp
    FROM pri, dlt, press
), rec AS MATERIALIZED (                  -- [DP7](d) 恢复 floor 单源消费
  SELECT v13_recovery_active(p_sid) AS active,
         (SELECT (b->>'lo_bp')::int
            FROM econ0, jsonb_array_elements(econ0.bands) b
           WHERE b->>'tier' = 'CompactHistory' LIMIT 1) AS floor_bp
  FROM econ0
), cand AS MATERIALIZED (                 -- pressure 域取 max 再映 tier
  SELECT greatest(press.bp,
                  coalesce(pred.bp, press.bp),
                  CASE WHEN rec.active THEN coalesce(rec.floor_bp, 0)
                       ELSE 0 END) AS bp
    FROM press, pred, rec
), inputs AS MATERIALIZED (               -- [DP7](d) tier 三输入+目标档
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
), lowturns AS MATERIALIZED (             -- 每 turn 取链上最新 manifest 的
  SELECT turn, bp FROM (                  -- raw bp(同 turn 多 manifest 时
    SELECT DISTINCT ON ((c.m->>'turn_no')::int)  -- 取链上最近一版=depth 最小)
           (c.m->>'turn_no')::int AS turn,
           (c.m->'economics'->'pressure'->>'bp')::bigint AS bp
      FROM chain c
     WHERE (c.m->>'turn_no')::int <
           (SELECT turn_no FROM sessions WHERE session_id = p_sid)
       AND c.m->'economics' IS NOT NULL
     ORDER BY (c.m->>'turn_no')::int, c.depth
  ) x ORDER BY turn DESC
), loheld AS MATERIALIZED (             -- [DP7](d) held 档 band 下界
  SELECT (SELECT (b->>'lo_bp')::int       -- (held tier 无前驱/词表外=lo NULL)
            FROM econ0, jsonb_array_elements(econ0.bands) b
           WHERE b->>'tier' = (SELECT pri.m->'economics'->'tier'->>'effective'
                                 FROM pri
                                WHERE pri.m->'economics'->'tier'->>'effective'
                                      IN ('Normal','TrimSchemas',
                                          'CompactHistory','AggressivePrune'))
           LIMIT 1) AS lo_bp
  FROM econ0
), lowrun AS MATERIALIZED (              -- [DP7](d) 降级许可:held 档
  SELECT EXISTS (                        -- band 下界连续 cooldown_turns 个
    SELECT 1                            -- 前驱 turn 均低于(不足数=不许可)
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
), effcalc AS MATERIALIZED (              -- [DP7](d) OQ4:单 Plan 单调+跨
  SELECT CASE                            -- turn hysteresis(G-ctx6 原措辞被
           WHEN inputs.held_rank IS NULL  -- 轮 2 裁决取代)
                OR inputs.target_rank >= inputs.held_rank
             THEN inputs.target_rank      -- 升档无冷却/首版
           WHEN lowrun.ok                 -- 降级许可满足:每时至多
             THEN greatest(inputs.target_rank,               -- max_downgrade_steps
                           inputs.held_rank
                           - coalesce((pol.hyst->>'max_downgrade_steps')::int, 1))
           ELSE inputs.held_rank          -- cooldown 未满:held(prior_held)
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
), sp AS MATERIALIZED (                  -- [DP7](d) spill 代理输入:
  SELECT octet_length(coalesce((cs.c -> 'messages')::text, '')) AS hist_bytes,
         coalesce((SELECT sum(greatest(octet_length((m->'payload')::text) - 64, 0))
                     FROM jsonb_array_elements(cs.c -> 'messages') m
                    WHERE m->>'type' = 'tool/result'), 0) AS spill_saved
  FROM cs
), erc2 AS MATERIALIZED (                -- [DP7](d) e_base/e_nonhist 首轮代理
  SELECT (SELECT floor(coalesce(sum(     -- (base=稳定前缀按 cached/新变段按
              CASE WHEN NOT o.prior_missing  -- fresh;comp=非 history 段同基线+
                AND o.content_hash IS NOT DISTINCT FROM o.prior_hash  -- spill 后
                   THEN o.est_tokens ELSE 0 END), 0) * econ0.r  -- history 按 fresh
           + coalesce(sum(
              CASE WHEN o.prior_missing
                     OR o.content_hash IS DISTINCT FROM o.prior_hash
                   THEN o.est_tokens ELSE 0 END), 0))
            FROM ordered o) AS e_base,
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
            FROM ordered o) AS e_nonhist,
         sp.hist_bytes, sp.spill_saved, econ0.divisor
  FROM econ0, sp
), erc AS MATERIALIZED (                  -- [DP7](d) E(r) 三纪律(OQ5)
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
                THEN 'loss'               -- r<r*=0.145 压缩亏钱(ContextPipe
              WHEN floor(erc2.e_nonhist
                        + ((greatest(erc2.hist_bytes - erc2.spill_saved, 0)
                            + erc2.divisor - 1) / erc2.divisor))
                   < erc2.e_base
                THEN 'adopt'
              ELSE 'loss' END AS branch,
         (press.bp >= econ0.hard_bp) AS hard_window
  FROM econ0, press, erc2
), hint AS MATERIALIZED (                 -- [DP7](d) 触点 1 shadow-first:
  SELECT CASE WHEN effcalc.eff_rank >= 3  -- 仅 effective tier 跨入
             THEN jsonb_build_object(     -- CompactHistory+ 时记录;
               'order', (SELECT coalesce(jsonb_agg(q.section_id
                              ORDER BY q.ch DESC, q.est DESC, q.section_id),
                             '[]'::jsonb)  -- 同可压缩类(history)确定性序
                          FROM (SELECT o.section_id,          -- (churn DESC,
                                       CASE WHEN o.prior_missing THEN 0
                                            WHEN o.content_hash
                                                 IS DISTINCT FROM o.prior_hash
                                            THEN o.prior_churn + 1
                                            ELSE 0 END AS ch,
                                       o.est_tokens AS est
                                  FROM ordered o
                                 WHERE o.kind = 'history'
                                   AND o.pre_skip IS NULL) q),
               'basis', 'churn:est:id')   -- goal/tools 硬类永不入 hint
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
                     THEN                                -- [DP7](c) 桶内
                       jsonb_build_object('applied', false,  -- 超桶 cap 即
                                          'reason', 'budget')  -- skip
                     ELSE
                       jsonb_build_object('applied', true, 'name',
                         CASE o.section_id WHEN 'goal'   THEN 'verbatim'
                                           WHEN 'history' THEN 'verbatim'
                                           ELSE 'catalog_digest' END)
                   END
  ) AS section, o.prank, o.section_id
  FROM ordered o, econ0
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
                           ORDER BY d.answered_at DESC, d.decision_id
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
  'manifest_version', 2,
  'session_id', p_sid,
  'turn_no',   (SELECT turn_no FROM sessions WHERE session_id = p_sid),
  'prefix_identity', (SELECT pid FROM ident),
  'policy',    jsonb_build_object(                 -- [DP7](e) 4→7 键
                 'assemble_version',   (SELECT version FROM pol),
                 'budget_tokens',      (SELECT budget FROM pol),
                 'est_bytes_per_token',(SELECT divisor FROM pol),
                 'judgment_defaults_version', (SELECT jdef_ver FROM pol),
                 'tiers_version',      (SELECT tiers_ver FROM pol),
                 'budget_version',     (SELECT budget_ver FROM pol),
                 'pricing_version',    coalesce((SELECT catalog_version::text
                                                  FROM econ0), 'none')),
  'required_revision', (SELECT t FROM tok),
  'economics', jsonb_build_object(                 -- [DP7](d) 键集封闭
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
                 'compact_hint', (SELECT h FROM hint)),
  'sections',  (SELECT coalesce(jsonb_agg(section ORDER BY prank, section_id),
                             '[]'::jsonb)
                  FROM final_sec),
  'query_side',(SELECT q FROM qside),
  'judgments', (SELECT j FROM jud),
  'replay',    jsonb_build_object('mode', (SELECT m FROM mode),
                                  'prior_artifact_id', (SELECT aid FROM pri)));
$$;

-- === 换体四:v13_manifest_validate v2(economy 半边) ===
-- 机械复制加载态最新前驱(文件 8 v13_recall.sql,DP5 版)原文+增量(注释
-- 锚定,plan §3.1 换体四 (a)–(e));复制体的既有 RAISE 与 V 码逐字保留
-- (V3003);新增层 RAISE 统一 V3007:
--   (a) manifest_version 断言 =2;
--   (b) 顶层键集 10→11(+economics);
--   (c) policy 块 4→7 键;required_revision 10 键恰等(基九键+econ_ver);
--   (d) economics 块封闭新层(pressure 4 键全 int>=0/tier 3 键词表封闭/
--       er 6 键/buckets 4 键 int>=0/compact_hint null 或 2 键;int 检查
--       jsonb_typeof+::int 双卫);
--   (e) section_id 多段化规则(单 kind 单段=kind;同 kind 多段一律
--       kind:8hex——规则无例外分支,校验器可执法);transform/candidate/
--       judgments 层零改(name/reason 词表本文件不扩)。
CREATE OR REPLACE FUNCTION v13_manifest_validate(p_manifest jsonb) RETURNS void
LANGUAGE plpgsql STABLE AS $$
DECLARE s jsonb; j jsonb; c jsonb; e jsonb; n int;
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
  -- [DP7](d) economics 块七层封闭的新层(键集恰等/词表封闭/int 双卫)
  e := p_manifest->'economics';
  IF jsonb_typeof(e) IS DISTINCT FROM 'object'
     OR (SELECT string_agg(k, ',' ORDER BY k) FROM jsonb_object_keys(e) k)
        IS DISTINCT FROM 'buckets,compact_hint,er,pressure,tier' THEN
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
       OR (s->>'kind') IN ('goal','history','tools') IS NOT TRUE
       OR s->>'content_hash' IS NULL
       OR s->>'content_hash' !~ '^[0-9a-f]{64}$'
       OR (s->>'churn')::int IS NULL OR (s->>'churn')::int < 0
       OR (s->>'est_tokens')::int IS NULL OR (s->>'est_tokens')::int < 0 THEN
      RAISE EXCEPTION 'v13: section vocabulary/hash violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
    -- [DP7](e) section_id 多段化规则:该 kind 在本 manifest 内唯一⇒
    -- section_id=kind;同 kind 多段⇒全部段一律 kind:left(content_hash,8)
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
                     IN ('verbatim','catalog_digest') IS NOT TRUE
             ELSE (SELECT string_agg(k, ',' ORDER BY k)
                     FROM jsonb_object_keys(s->'transform') k)
                  IS DISTINCT FROM 'applied,reason'
                  OR (s->'transform'->>'reason')
                     IN ('budget','priority_never','disabled','invalid_override')
                     IS NOT TRUE
        END) IS TRUE THEN
      RAISE EXCEPTION 'v13: section transform shape violation for % (V3003)',
        s->>'section_id' USING ERRCODE = 'V3003';
    END IF;
  END LOOP;
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

-- === 换体五:v13_refresh_context(锁集与守卫扩集;顺序骨架逐字保留) ===
-- 机械复制 DP3 §3.5 加载态原文(v13_manifest.sql)+增量(注释锚定,plan
-- §3.1 换体五 (a)–(c));复制体的既有 RAISE 与 V 码逐字保留;新守卫
-- RAISE 统一 V3007:
--   (a) 第四层锁集扩五名策略行+v13_pricing active 行殿后(dim 序);
--   (b) 策略形状守卫扩(context_tiers/context_budget=装配输入锁面;
--       judge_spend_gate/fastpath_tiers/render_policy=配置错误前置,
--       fail-loud 同点检查、不在锁面);
--   (c) validate 调用零改(换体四自动生效);complete/blob/lander/指针
--       段零改。
CREATE OR REPLACE FUNCTION v13_refresh_context(p_effect uuid, p_attempt int, p_fence bigint)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE v_row effects; v_sid uuid; v_manifest jsonb; v_art uuid; v_out text;
        v_budget int; v_div int; v_inline_max bigint;
        v_ovr jsonb; v_off jsonb;
        v_hist jsonb; v_tools jsonb; v_hh text; v_th text; v_mh text;
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
                  'context_tiers','context_budget')          -- [DP7](a)
     AND active
   ORDER BY name FOR UPDATE;
  PERFORM 1 FROM public.v13_pricing                          -- [DP7](a)
   WHERE active ORDER BY provider, model, account, cache_class FOR UPDATE;

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

  v_hist  := public.v13_canonical_state(v_sid) -> 'messages';
  v_tools := public.v13_canonical_state(v_sid) -> 'tools';
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'history';
  v_hh := public.v13_blob_land(p_effect, v_hist);
  IF v_hh IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: history blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
  END IF;
  SELECT s->>'content_hash' INTO v_mh
    FROM jsonb_array_elements(v_manifest->'sections') s
   WHERE s->>'section_id' = 'tools';
  v_th := public.v13_blob_land(p_effect, v_tools);
  IF v_th IS DISTINCT FROM v_mh THEN
    RAISE EXCEPTION 'v13: tools blob hash drift vs manifest section'
      USING ERRCODE = 'V3003';
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

-- === ACL 全量块(文件真末尾;不变量 12) ===
REVOKE EXECUTE ON FUNCTION
  v13_pricing_frozen(),
  v13_pricing_r(text,text,text,text),
  v13_ro_reserve(uuid),
  v13_recovery_active(uuid),
  v13_judge_spend(uuid),
  v13_econ_ver(),
  v13_cache_breaks(uuid),
  v13_band_of(jsonb,bigint),
  v13_tier_rank(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_pricing_r(text,text,text,text), v13_econ_ver(),
  v13_band_of(jsonb,bigint), v13_tier_rank(text)
TO v13_recall, v13_resolve, v13_route;   -- 读面三角色(审计/装配同源读)
GRANT EXECUTE ON FUNCTION v13_ro_reserve(uuid),
  v13_recovery_active(uuid),
  v13_judge_spend(uuid), v13_cache_breaks(uuid)
TO v13_route, v13_resolve;               -- parse 闸/驱动面+装配 recovery_floor 面
                                         -- (单源双消费);cache_breaks=审计面
GRANT SELECT ON v13_pricing TO v13_recall, v13_resolve, v13_route;
-- GRANT SELECT ON v13_policies 归 DP1(三角色已有,gate A5 存在性断言);
-- OR REPLACE 五件 ACL 经 OID 保留,不重授(gate H3)。

COMMIT;
