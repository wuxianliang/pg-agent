-- context freshness 缝(DP3 替换点,§1.3):DP1 恒新鲜——仅存在性+调用点被 gate 断言
CREATE FUNCTION v13_context_fresh(p_sid uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$ SELECT true $$;
COMMENT ON FUNCTION v13_context_fresh(uuid) IS
  'DP3 seam: required_revision vs active_revision (design §5.2/§6.1).';

-- 步 0 廉价探针(turn 8,#56+turn 9,#59):七键六行读(cgr 与 revision 同行),
-- 锁内复核专用——
-- 旧步 0 调 v13_snapshot(重聚合 20 条语义事件+needed 全推导+目录 pg_proc
-- 全验+gap 扫描)耗时随基数增长,重引入设计要消除的阻塞面(不变量 3/
-- G-ctx1-2)。goal_hash 的「最近 user/message」读由 M1 部分索引
-- ix_events_last_user 支撑(O(log n));max(seq) 走 events PK 反向扫描;
-- sessions/v13_tools_meta 各一次 PK 读。比对语义见 advance 步 0 注。
CREATE FUNCTION v13_probe(p_sid uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'session_version', s.next_seq,
    'max_event_seq', coalesce((SELECT max(seq) FROM events
                                WHERE session_id = p_sid), -1),
    'goal_hash', encode(digest(coalesce(
        (SELECT payload::text FROM events
          WHERE session_id = p_sid AND type = 'user/message'
          ORDER BY seq DESC LIMIT 1), ''), 'sha256'), 'hex'),
    'route_policy_name',     s.route_policy_name,
    'route_policy_version',  s.route_policy_version,
    'tools_revision', (SELECT revision FROM v13_tools_meta WHERE singleton),
    'candidate_generation_revision',
      (SELECT candidate_generation_revision FROM v13_tools_meta
        WHERE singleton))    -- 与 revision 同行读取,零额外行访(turn 9,#59)
  FROM sessions s WHERE s.session_id = p_sid;
$$;

-- 信封限定证据读取(turn 3,#9):按当前信封算出的精确 request_hash 取行,
-- 弃「裸 answered_at 最新」——并列 answered_at 截断无终裁、多 ctx 世代并存
-- 时可能读到旧世代(顺带消解 P2 tiebreak 项)。信封 needed 行含 kind/
-- question/criteria,哈希唯一确定行;行缺失(未答/非本世代)→ NULL。
CREATE FUNCTION v13_env_decision(p_env jsonb, p_signal text) RETURNS decisions
LANGUAGE sql STABLE AS $$
  SELECT d.*
    FROM jsonb_array_elements(p_env->'needed') g
    JOIN decisions d
      ON d.session_id = (p_env->>'sid')::uuid
     AND d.signal = g->>'signal'
     AND d.request_hash = v13_judgment_hash(p_env, p_signal, g->>'kind',
                                            g->>'question', g->'criteria')
   WHERE g->>'signal' = p_signal      -- turn 4,P0-1(控制器机械核实):参数
     AND d.answer IS NOT NULL AND d.status IN ('answered','cached')
   LIMIT 1;   -- 必须参与过滤——无此时 JOIN 遍历 needed 全集 LIMIT 1 会任意
              -- 取到其他 signal 的已答行。needed 内 signal 唯一(M2-13 gate)
              -- + (session_id,hash) 唯一 → 至多一行
$$;

CREATE FUNCTION v13_env_answer(p_env jsonb, p_signal text) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT (v13_env_decision(p_env, p_signal)).answer;
$$;

-- 带命中检查:命中判定限定在当前信封的那一行 decision_id 上
CREATE FUNCTION v13_env_hit(p_env jsonb, p_signal text, p_action text)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM v_routes v
                  WHERE v.session_id = (p_env->>'sid')::uuid
                    AND v.signal = p_signal AND v.action = p_action
                    AND v.decision_id =
                        (v13_env_decision(p_env, p_signal)).decision_id);
$$;

-- 确定性路由 = v12_route_turn 血统(v12/turn/v12_turn.sql:156-209)。
-- 决策表(完整分支+优先级,自上而下首中即出;turn 3 增 P0/P4 前置/P4d):
--   P0 当前 turn 的最新机器语义事件(origin 锚=last_user_seq 的
--      llm/message、tool/result 两类中最大 seq 者;turn 4,#25 锚定)是
--      llm/message——worker 已把生成结果落进投影(v13_complete 语义半边)
--      → {action:'finish', reason:'answered'}
--   P1 gate_off_topic 信封行命中 reject 带(noul ≥0.75,种子值)
--        → {action:'reject', reason:'injection_veto'}
--   P2 intent 无信封行,或其 confidence 未命中 pass 带(<0.75)
--        → {action:'human', reason:'low_intent_confidence'}
--          (含 no_threshold:带行缺失/低置信统一兜底,ch4.4)
--   P3 intent.choice = 'human_escalate'
--        → {action:'human', reason:'model_escalated'}
--   P4 intent.choice ∈ {sql_answer, tool_action} 且 gate_action 信封行命中
--      pass 带(turn 3 接线:act 判据——此前 gate_action 每轮付费而路由零
--      消费;未命中走 P5 解释路径)且 tool 信封行命中 pass 带、
--      choice ∉ {NULL,'none'}:
--      P4a tools.kind='sql'(且 enabled)       → {action:'sql',
--            reason:'in_db_handler', tool:<name>, params:resolve_tool_params}
--      P4b tools.kind='tool' 且 risk 信封行命中 reject 带(≥2.25)
--                                          → {action:'human', reason:'risk_veto'}
--      P4c tools.kind='tool' 其余          → {action:'tool',
--            reason:'side_effect_tool', tool:<name>, params:resolve_tool_params}
--      P4d 目录无此 tool 或 enabled=false → {action:'human',
--            reason:'tool_unavailable'}(fail-closed,turn 3)
--   P5 兜底                            → {action:'llm', reason:'generation_needed'}
-- 输入输出示例(P4a,种子目录,无 stated 参数):
--   {"action":"sql","reason":"in_db_handler",
--    "tool":"session_stats","params":{}}
-- 【v12_route_turn 血统移植落差(显式记录,turn 3,#1)】v12_route_turn 无
-- finish 分支(v12 的 turn 终结在驱动层,不在路由面);v13 教程 ch5.2 要求
-- 路由面给出终结(ch5.5 时序末步=route→finish→terminal),turn 2 修复漏补
-- → P1–P5 出口词表无 finish,llm 作答后 intent 四选一必再走 llm →
-- 三轮烧光预算落 human、M3-6/K2 不可达。P0 即补齐:证据=当前 turn 语义
-- 事件(零新增判断),与 ch5.5 「llm settle→事件→route=finish→terminal」逐
-- 字对齐。turn 4(#25)补锚:证据事件必须 origin=当前 last_user_seq——
-- turn A 迟到完成的 llm/message(seq 压过 turn B 锚)不触发 finish,旧回
-- 答不得终结新 turn(K8 gate;旧回答事件仍入日志,自 turn C 起沉淀为
-- 可见历史,不变量 7)。
-- 【总量性硬规定(评审修正)】v13_route 是全函数:任何输入都返回一个非空
-- action;NULL 返回是实现 bug,advance 的 CASE ELSE 兜 fail-closed 异常是
-- 背板而非依赖。
CREATE FUNCTION v13_route(p_sid uuid, p_env jsonb) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_intent jsonb; v_tool text; v_kind text; v_params jsonb;
  v_ltype text; v_lseq bigint;
BEGIN
  v_intent := v13_env_answer(p_env, 'intent');
  v_tool   := (v13_env_answer(p_env, 'tool')->>'choice');
  -- 当前 turn 的最新机器语义事件(turn 4,#25 origin 锚定):tool/result 与
  -- llm/message 只认 origin_user_seq=当前 last_user_seq 的行——turn A 迟到
  -- 完成的 llm/message(seq 压过 turn B 锚)不参与判定。user/message 不入
  -- 扫描:新 user message 即新锚,旧机器事件 origin 自然失配(旧扫描靠
  -- 「最新是 user」挡,锚定后结构性不需要)。
  SELECT e.type, e.seq INTO v_ltype, v_lseq
    FROM events e
   WHERE e.session_id = p_sid
     AND e.type IN ('llm/message','tool/result')
     AND (e.payload->>'origin_user_seq')::bigint = v13_last_user_seq(p_sid)
   ORDER BY e.seq DESC LIMIT 1;

  IF v_ltype = 'llm/message' AND v_lseq > v13_last_user_seq(p_sid) THEN
    RETURN jsonb_build_object('action','finish','reason','answered');
  ELSIF v13_env_hit(p_env, 'gate_off_topic', 'reject') THEN
    RETURN jsonb_build_object('action','reject','reason','injection_veto');
  ELSIF v_intent IS NULL OR NOT v13_env_hit(p_env, 'intent', 'pass') THEN
    RETURN jsonb_build_object('action','human','reason','low_intent_confidence');
  ELSIF v_intent->>'choice' = 'human_escalate' THEN
    RETURN jsonb_build_object('action','human','reason','model_escalated');
  ELSIF v_intent->>'choice' IN ('sql_answer','tool_action')
        AND v13_env_hit(p_env, 'gate_action', 'pass')
        AND v13_env_hit(p_env, 'tool', 'pass')
        AND v_tool IS NOT NULL AND v_tool <> 'none' THEN
    SELECT t->>'kind' INTO v_kind
      FROM jsonb_array_elements(p_env->'tools_catalog') t
     WHERE t->>'name' = v_tool AND (t->>'enabled')::boolean;
      -- 目录读取走信封冻结面(turn 5,#38):kind 一律取 tools_catalog(与
      -- 判断授权同一快照)——活表直查是 TOCTOU 面(并发改 kind 后旧判断
      -- 授权新工具);无此行(未收录/disabled)→ v_kind NULL → P4d 兜底
    v_params := v13_resolve_tool_params(p_env, v_tool);
    IF v_kind IS NULL THEN
      RETURN jsonb_build_object('action','human','reason','tool_unavailable');
    ELSIF v_kind = 'sql' THEN
      RETURN jsonb_build_object('action','sql','reason','in_db_handler',
                                'tool', v_tool, 'params', v_params);
    ELSIF v_kind = 'tool' AND v13_env_hit(p_env, 'risk', 'reject') THEN
      RETURN jsonb_build_object('action','human','reason','risk_veto');
    ELSE
      RETURN jsonb_build_object('action','tool','reason','side_effect_tool',
                                'tool', v_tool, 'params', v_params);
    END IF;
  ELSE
    RETURN jsonb_build_object('action','llm','reason','generation_needed');
  END IF;
END $$;

-- 参数闭环(v12_resolve_tool_params 移植,v12/turn/v12_turn.sql:230-256):
-- 某 param 仅当其 stated:: Noul 信封行命中 pass 带才收 param:: 的 choice;
-- 否则省略,工具自身默认值生效(绝不猜值)。证据同样信封限定(turn 3,#9)。
-- param_spec 亦读信封冻结目录(turn 5,#38)——与路由同一 TOCTOU 面。
CREATE FUNCTION v13_resolve_tool_params(p_env jsonb, p_tool text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE v_spec jsonb; v_params jsonb := '{}'; r record;
BEGIN
  SELECT t->'param_spec' INTO v_spec
    FROM jsonb_array_elements(p_env->'tools_catalog') t
   WHERE t->>'name' = p_tool;
  FOR r IN SELECT key, value FROM jsonb_each(v_spec) LOOP
    IF v13_env_hit(p_env, 'stated::' || p_tool || '::' || r.key, 'pass') THEN
      v_params := v_params || jsonb_build_object(r.key,
        v13_env_answer(p_env, 'param::' || p_tool || '::' || r.key)->>'choice');
    END IF;
  END LOOP;
  RETURN v_params;
END $$;

-- 唤醒(v12_send_work 血统;消息 {"kind":"effect","id":uuid},仅唤醒可丢)
CREATE FUNCTION v13_send_work(p_effect uuid) RETURNS bigint
LANGUAGE sql VOLATILE AS $$
  SELECT pgmq.send('v13_work', jsonb_build_object('kind','effect','id',p_effect));
$$;
REVOKE EXECUTE ON FUNCTION v13_send_work(uuid) FROM PUBLIC;  -- turn 3,#6:
GRANT  EXECUTE ON FUNCTION v13_send_work(uuid) TO v13_route; -- M3 stage 授权

-- 变更事务(§4.3):FOR UPDATE 会话行,毫秒级,锁内零外部 IO(不变量 3)。
-- 返回:progressed | waiting | terminal | stale(水位弃批)。
-- 入参 p_snap = v13_parse 的出口信封(§3.4 契约;三出口同 schema,本函数
-- 统一读 p_snap->'snap' 与顶层标志位)。
CREATE FUNCTION v13_advance(p_sid uuid, p_snap jsonb) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  v_now jsonb; v_route jsonb; v_cycles int; v_max int;
  v_effect uuid; v_est text; v_res jsonb; v_handler text; v_req jsonb;
  v_err jsonb;
BEGIN
  -- 入口三重 sid 校验(turn 4,P0-3,先于任何锁/写):snap.sid =
  -- envelope.sid = p_sid 完全相等,不一致或缺键 RAISE——跨 session 快照进
  -- advance 是调用面 bug,必须响亮失败,不是普通 'stale'(弃批语义只属于
  -- 「同 session 快照过期」;锁下复核原本只比四元组,sid 键在 snap 里却无人
  -- 消费,异 session 快照会以「货币」姿态进建账)。gate M3-17。
  IF p_snap IS NULL
     OR (p_snap->'snap'->>'sid') IS DISTINCT FROM p_sid::text
     OR (p_snap->'envelope'->>'sid') IS DISTINCT FROM p_sid::text THEN
    RAISE EXCEPTION 'v13: advance/snapshot session mismatch (p=%, snap=%, env=%)',
      p_sid, p_snap->'snap'->>'sid', p_snap->'envelope'->>'sid';
  END IF;

  PERFORM 1 FROM sessions WHERE session_id = p_sid FOR UPDATE;   -- 会话锁,仅变更相
  IF NOT FOUND THEN RAISE EXCEPTION 'v13: unknown session %', p_sid; END IF;

  -- 步 0(§6.1 快照复核 + turn 4 #29 + turn 5 #38 + turn 8 #56 探针化 +
  -- turn 9 #59 第七键):
  -- 锁下**廉价探针七键**比对(session_version/max_event_seq/goal_hash/
  -- route_policy_name/version/tools_revision/candidate_generation_revision),
  -- 不一致 → 弃批重解析。
  -- 探针化(turn 8,#56):旧实现锁内调全量 v13_snapshot——重聚合历史事件+
  -- needed 全推导+目录 pg_proc 全验,耗时随基数增长,重引入设计要消除的
  -- 阻塞面;昂贵面(envelope/candidate/gap)只在 parse(锁外,§3.2/§3.4)。
  -- candidate_set_hash/needed_count 不再直接比对(无漏报论证,turn 9,#59
  -- 补全):两者是 needed 集的派生,needed=f(tools 行集,v13_needed_judgments
  -- 函数体)——tools 任何列变更经行级 AFTER 触发器(§3.1)、handler 函数体
  -- 漂移经 DDL event trigger(turn 8,#54)必 bump revision;**needed_judgments
  -- 函数体的 CREATE/ALTER/DROP 经同一 event trigger 第二分支必 bump
  -- candidate_generation_revision**(第八轮前论证缺此面:OR REPLACE 换推导
  -- 逻辑不触 tools 行,六键全不变而 csh 已变——假阴性)⟹ csh 变化必伴随
  -- 七键之一变化;DP5 引入语料依赖后语料版本必须同构并入(§1.3 硬契约)。
  -- 反向(revision/cgr 变而 csh 不变,如 handler-only 变因)→ 保守弃批——
  -- 重解析因判断投影不含目录 handler 面,零 ask、一轮收敛。parse 与 advance 之间切换路由策略(带行
  -- 不可变,换的是 sessions 指针)或变更工具目录(含 handler/param_spec
  -- 这类不进判断哈希的列)同样弃批,不得按旧判断消费旧带/新目录。注:
  -- resolve 落行(decisions)不动七键;并发编排事件(effect_done 等)会推
  -- max_event_seq → 保守 stale(同上,零 ask 收敛,风险表记)。
  v_now := v13_probe(p_sid);
  IF (v_now->>'session_version', v_now->>'max_event_seq',
      v_now->>'goal_hash',       v_now->>'route_policy_name',
      v_now->>'route_policy_version', v_now->>'tools_revision',
      v_now->>'candidate_generation_revision')
     IS DISTINCT FROM
     (p_snap->'snap'->>'session_version', p_snap->'snap'->>'max_event_seq',
      p_snap->'snap'->>'goal_hash',       p_snap->'snap'->>'route_policy_name',
      p_snap->'snap'->>'route_policy_version',
      p_snap->'snap'->>'tools_revision',
      p_snap->'snap'->>'candidate_generation_revision')
  THEN
    RETURN 'stale';                       -- 调用者重新 parse(「弃批重解析」)
  END IF;

  -- ① 终态 / 未决 effect:直接返回(单活跃索引是并发背板,行为检查在前;
  -- turn 3 排序修正:① 先于 failed 审计/abandon——终态 session 不再落审计
  -- 事件、不建 escalation effect)
  IF (SELECT status FROM sessions WHERE session_id = p_sid)
       IN ('completed','failed','cancelled') THEN RETURN 'terminal'; END IF;
  IF EXISTS (SELECT 1 FROM effects WHERE session_id = p_sid
              AND status IN ('ready','claimed','unknown')) THEN
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';          -- unknown 也阻塞:墙,等 ch12 显式 resolve(§3.6 #8)
  END IF;

  -- 失败审计事件落点(变更相,锁下毫秒级;解析相零事件写入的对称半边)。
  -- 返回 'progressed'(turn 3,#15):旧版返 'waiting' 且无 effect/wake →
  -- 两套推进机制(队列/驱动)都不触发,session 静默停摆;现在当前驱动
  -- 立刻重 parse,重试由 resolve_retry 计数封顶至 abandon(M4-K6)。
  IF coalesce((p_snap->>'failed')::boolean, false) THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'resolve/failed',
      jsonb_build_object('remaining', p_snap->'snap'->>'gap_count',
        'origin_user_seq', v13_last_user_seq(p_sid)));
        -- 锚=锁下当前 last_user_seq(turn 4,#25):步 0 已证快照货币,
        -- 本事件必属当前 turn;parse 侧计数按锚过滤(§3.4)
    RETURN 'progressed';       -- 不建 effect、不 wake、不改 status
  END IF;

  IF coalesce((p_snap->>'abandon')::boolean, false) THEN
    -- 放弃分支优先于预算检查(否则 resolve_budget 原因被 budget_exhausted
    -- 掩盖);零新增 Jev 调用已在上游(parse)发生
    v_effect := v13_enqueue_effect(p_sid, 'human',
                  jsonb_build_object('reason','resolve_budget'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est = 'succeeded' THEN
      -- succeeded 重放停摆修复(turn 3,#5):escalation 已被结算——终结
      -- turn 而非重发 wake 空等(旧版:enqueue 返旧 succeeded id + wake →
      -- 无人 claim → 永久 waiting)。delivered=false 映射同 reject(§3.6 #4)
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
        jsonb_build_object('delivered', false, 'reason', 'resolve_budget'));
      UPDATE sessions SET status='failed' WHERE session_id = p_sid;
      RETURN 'terminal';
    ELSIF v_est IN ('failed','cancelled') THEN
      -- escalation 尝试耗尽(turn 7,#49,cursor 第六轮):human worker 持续
      -- 失败至 attempt 上限,enqueue 拒重挂(行留终态)——终结 session 而
      -- 非无限重试(failed→ready 重挂不增 cycle 的死循环面);事件链可审计
      -- (cap 条 effect_done + 本条 turn/end,attempts_exhausted 标记)
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
        jsonb_build_object('delivered', false, 'reason', 'resolve_budget',
                           'attempts_exhausted', true));
      UPDATE sessions SET status='failed' WHERE session_id = p_sid;
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;

  -- ② context gate(DP3 缝;DP1 恒真 → 死分支,gate 断言缝存在)。
  --    request 只携语义词段(turn 3,#3:context_refresh 同 judge——水位是
  --    步 0 消费品,worker 不需要;DP3 接管时自定语义字段)
  IF NOT v13_context_fresh(p_sid) THEN
    v_effect := v13_enqueue_effect(p_sid, 'context_refresh',
                  jsonb_build_object('goal_hash', p_snap->'snap'->>'goal_hash'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est IN ('failed','cancelled') THEN
      -- attempt 封顶终结(turn 7,#49;DP1 stub 下死分支,DP3 接管时语义已定)
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
        jsonb_build_object('delivered', false, 'reason', 'context_refresh',
                           'attempts_exhausted', true));
      UPDATE sessions SET status='failed' WHERE session_id = p_sid;
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;

  -- ⑤ 预算(检查与工作创建同事务,先于 ③④ 的任何建账):
  v_cycles := v13_cycle_no(p_sid);        -- 单一序数源(与 effect 身份共用,§3.1)
  v_max := (v13_policy('turn_budget')->>'max_cycles')::int;
  IF v_cycles >= v_max THEN
    -- 预算耗尽 → 强制 human(零新增 Jev 调用:parse 的 abandon 分支 + 此处零 ask)
    v_effect := v13_enqueue_effect(p_sid, 'human',
                  jsonb_build_object('reason','budget_exhausted'));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est = 'succeeded' THEN
      -- 同 #5:escalation 已结算 → 终结 turn,不空等(重放停摆面)
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
        jsonb_build_object('delivered', false, 'reason', 'budget_exhausted'));
      UPDATE sessions SET status='failed' WHERE session_id = p_sid;
      RETURN 'terminal';
    ELSIF v_est IN ('failed','cancelled') THEN
      -- 同 abandon 分支的 attempt 封顶终结(turn 7,#49)
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
        jsonb_build_object('delivered', false, 'reason', 'budget_exhausted',
                           'attempts_exhausted', true));
      UPDATE sessions SET status='failed' WHERE session_id = p_sid;
      RETURN 'terminal';
    END IF;
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  END IF;

  -- ③ 决策:缺口仍在(超过快路批上限)→ judge effect 交 worker 慢路。
  -- request=**语义信封**(turn 3,#3:v13_effect_envelope 剔水位——编排事件
  -- 不再改 request 哈希,「同逻辑判断重试同 ID、fence+1 重挂」对 judge
  -- 真实可达);worker 消费信封不按 sid 重读(P0-2)。succeeded 重放
  -- (竞态:parse 后 worker 已填完)→ 不等待,续走 ④(turn 3,#5 的
  -- 「调用方遇 succeeded replay 继续推进」;tool/llm 分支结构性不可达同 ID
  -- 重放——④ 先落 turn/route、cycle 已进身份,不设检查)。
  IF (p_snap->>'remaining')::int > 0 THEN
    v_effect := v13_enqueue_effect(p_sid, 'judge',
                  jsonb_build_object('envelope',
                                    v13_effect_envelope(p_snap->'envelope')));
    SELECT status INTO v_est FROM effects WHERE effect_id = v_effect;
    IF v_est IN ('failed','cancelled') THEN
      -- judge attempt 封顶终结(turn 7,#49;常态由 resolve_retry abandon 先至
      -- ——cap 4>retry 2,本分支是 belt):判断工作单元尝试耗尽 → 终结
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
        jsonb_build_object('delivered', false, 'reason', 'judge_attempts',
                           'attempts_exhausted', true));
      UPDATE sessions SET status='failed' WHERE session_id = p_sid;
      RETURN 'terminal';
    ELSIF v_est <> 'succeeded' THEN
      PERFORM v13_send_work(v_effect);
      UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
      RETURN 'waiting';
    END IF;
  END IF;

  -- ④ 路由:读已落行的 decisions(缓存命中已在解析相发生;本相零 typesafe_ask);
  -- 证据=当前信封(v13_route 第二参,turn 3,#9)
  v_route := v13_route(p_sid, p_snap->'envelope');
  PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/route', v_route);

  CASE v_route->>'action'
  WHEN 'sql' THEN
    -- 快路:同事务直接执行只读函数 + effect 终态化(零队列往返,教程 ch5.4)
    -- handler 取自信封冻结目录(turn 5,#38,与路由同一 TOCTOU 面):并发
    -- 已改 handler 时本事务仍按 parse 授权面执行,变更经步 0 tools_revision
    -- 于下一次 advance 弃批生效
    SELECT t->>'handler' INTO v_handler
      FROM jsonb_array_elements(p_snap->'envelope'->'tools_catalog') t
     WHERE t->>'name' = v_route->>'tool' AND t->>'kind' = 'sql'
       AND (t->>'enabled')::boolean;
    v_req := jsonb_build_object('tool', v_route->>'tool',
                                'params', coalesce(v_route->'params','{}'));
      -- request 形状统一 {tool,params}(turn 4,P2/§3.6 #31):与 enqueue
      -- 的 tool 路径同形;handler 由目录派生(执行时 SELECT),不入
      -- request——handler 改名不改逻辑身份
    v_err := NULL;
    -- 统一 handler 契约 (session_id uuid, params jsonb) + EXECUTE USING
    -- (turn 3,#14:旧 %L::jsonb 单参调用与种子 handler (uuid) 签名不匹配;
    -- USING 传参,真实种子 handler 直跑,M3-4)。handler 取自信封冻结目录
    -- 且已是校验过的 schema-qualified 名(turn 7,#50:精确签名/(i,s)波动度/
    -- route 执行权限在冻结路径校验,免搜索路径劫持)——EXECUTE 用 %s 直拼
    -- 可信标识(旧 %I 单标识符引号不适配 schema.name 形态)。
    -- 异常出口(turn 4,#31;turn 10,#63 加显式 query_canceled 分支):EXECUTE
    -- 自带 BEGIN…EXCEPTION——handler 是目录注册的用户代码,其运行期错误按
    -- failed tool effect 落账(身份同推导、error 列写 SQLSTATE/SQLERRM),
    -- 不抛穿变更事务:turn/route 随事务提交、cycle 消耗、后续 advance 重路由
    -- 以 turn_budget 封顶(与 llm 形状降级 #26 同一自愈模型,M3-15)。块只
    -- 罩 EXECUTE——INSERT/append 的本地缺陷不在此捕获,原样上抛(与
    -- §3.3 #30 同纪律)。**显式 WHEN query_canceled 分支(引擎实测,PG18.4):
    -- plpgsql 的 WHEN OTHERS 不匹配 query_canceled(57014),但显式命名的
    -- WHEN query_canceled 分支可以捕获**(statement_timeout 超限的 57014 在
    -- 显式分支内被捕获、SQLSTATE/SQLERRM 可读;仅 OTHERS 时原样穿透)——
    -- 因此 handler EXECUTE 内已声明分类的超时与 55P03 同路:failed
    -- effect+自愈;分支体首句复用 α 分类门(turn 11,字面一致)——未声明
    -- statement_timeout 的取消(pg_cancel_backend/客户端取消)RAISE 原码
    -- 上抛(整条 advance 异常终止+回滚,与 M3-15 形态三同路);显式列出
    -- 分支是引擎语义的必要形式(OTHERS 不匹配 57014),分类门是与 α 的
    -- 一致性要求,非冗余。
    -- 时间护栏(turn 9,#60+turn 10,#63 结局分流;原 turn 8,#54 函数内护栏
    -- 移除):provolatile 仅是声明、STABLE wrapper 仍可阻塞(LOCK/长扫描;
    -- 经扩展 C 函数的写不可静态证)——设计接受面(教程 sql 快路本就在变更相
    -- 内;**不把 handler 移出会话锁**——那与设计 §4.3/ch5 快路语义冲突,
    -- 残余风险入 §5 风险表)。**护栏执法点=驱动(调用层),非 SQL 函数内**:
    -- SET LOCAL statement_timeout/lock_timeout 只作用于顶层语句,函数体内
    -- set_config 对嵌套 handler 语句不生效——turn 8 的「函数内 SET LOCAL 罩
    -- EXECUTE」名不副实,已删(移动=增+删:护栏四句+两暂存变量)。驱动契约
    -- (README 运维纪律第六条):调用 advance 的连接在调用前设
    -- lock_timeout≈250ms/statement_timeout≈5s(建议起点,数据可调;对齐
    -- 轮 7 #45「超时归因归调用层」已裁原则)。**超时结局按触发点分流
    -- (turn 10,#63;分类门 turn 11)**:handler EXECUTE 内(唯一捕获块)——
    -- statement_timeout 超限(57014,连接已声明分类)→ 上方显式
    -- query_canceled 分支经 α 同款分类门吸收 → failed effect
    -- (error->>'sqlstate'='57014')+RETURN 'progressed' 自愈(turn_budget
    -- 封顶);未声明分类的 57014(pg_cancel_backend/客户端取消)→ 分类门
    -- RAISE 原码上抛 → 整条 advance 异常终止+回滚+零事件零 effect(无超时
    -- 声明的取消不被吸收,取消处理归调用方;与 M3-15 形态三同路);
    -- lock_timeout 超限(55P03)→ WHEN OTHERS → failed effect+自愈
    -- (与 handler 运行期错误同路,M3-15 形态一;EXECUTE 内超时形态=形态二)。
    -- advance 其余位置(步 0 探针/会话锁 FOR UPDATE 等待/INSERT/append 等
    -- 无捕获块的位置)——任一超时(57014 或 55P03)→ 整条 advance 异常终止
    -- +事务回滚(零 effect 零事件),驱动重试(M3-15 形态三)。
    BEGIN
      EXECUTE format('SELECT %s($1, $2)', v_handler)
         INTO v_res USING p_sid, coalesce(v_route->'params', '{}'::jsonb);
    EXCEPTION
      WHEN query_canceled THEN            -- 57014:EXECUTE 内超时→显式分支
        IF coalesce(current_setting('statement_timeout', true), '0')
             IN ('0', '0ms') THEN         -- α 同款分类门(turn 11,字面一致)
          RAISE;                          -- 未声明超时分类(pg_cancel_backend
        END IF;                           -- /客户端取消)原 SQLSTATE 上抛
        v_res := NULL;                    -- (OTHERS 不匹配 57014,引擎实测)
        v_err := jsonb_build_object('sqlstate', SQLSTATE,
                                    'message', SQLERRM);
      WHEN OTHERS THEN
        v_res := NULL;
        v_err := jsonb_build_object('sqlstate', SQLSTATE, 'message', SQLERRM);
    END;
    v_effect := v13_effect_id(p_sid, 'tool', v_req);
    INSERT INTO effects (effect_id, session_id, kind, tool_name, request,
                         request_hash, idempotency_key, status, result, error,
                         origin_user_seq)
    VALUES (v_effect, p_sid, 'tool',
            v_route->>'tool', v_req,
            encode(digest(v_req::text,'sha256'),'hex'),
            'v13:' || v_effect::text,
            CASE WHEN v_err IS NULL THEN 'succeeded' ELSE 'failed' END,
            CASE WHEN v_err IS NULL THEN v_res END,
            v_err,
            v13_last_user_seq(p_sid));
            -- 身份=turn+cycle+request 哈希(§3.1,P0-3);hash 覆盖完整
            -- request;idempotency_key 同 enqueue 规范(#13);origin 锚与
            -- enqueue 同源求值(会话锁下)
    IF v_err IS NULL THEN
      PERFORM v13_append_event(p_sid, gen_random_uuid(), 'tool/result',
        jsonb_build_object('tool', v_route->>'tool', 'result', v_res,
                           'origin_user_seq', v13_last_user_seq(p_sid)),
        v_effect);              -- provenance:tool/result ← effect(P2);
                                -- 锚随 payload(不变量 7);失败路径零语义
                                -- 事件
    END IF;
    RETURN 'progressed';
  WHEN 'tool' THEN
    -- 排队路径冻结 handler+tools_revision(turn 6,#42;turn 7,#50 补:冻结值
    -- 为信封冻结路径校验过的 schema-qualified 名——缺失/歧义/VOLATILE/签名
    -- 不符/route 不可执行在 parse 时即 RAISE):sql 快路在信封冻结
    -- 目录上取 handler 同事务执行;排队 tool effect 的执行在后的 worker,
    -- 若只留 {tool,params} 则被迫查活目录——建 effect 后 handler 变更,
    -- 探针弃批也护不住在飞行的这一单(步 0 只守 parse→advance 窗口)。
    -- request 携带创建时授权面的 handler 与 tools_revision,worker 只按
    -- request 分派、零活表依赖(handler 变更 → 重 parse 后新 request 新
    -- effect ID;在飞旧 effect 按其冻结 handler 执行=授权时点语义)。
    SELECT t->>'handler' INTO v_handler
      FROM jsonb_array_elements(p_snap->'envelope'->'tools_catalog') t
     WHERE t->>'name' = v_route->>'tool' AND (t->>'enabled')::boolean;
    v_effect := v13_enqueue_effect(p_sid, 'tool',
      jsonb_build_object('tool', v_route->>'tool',
                         'params', coalesce(v_route->'params','{}'),
                         'handler', v_handler,
                         'tools_revision',
                         p_snap->'envelope'->'tools_revision'),
      v_route->>'tool');
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'llm' THEN
    v_effect := v13_enqueue_effect(p_sid, 'llm',
      jsonb_build_object('route', v_route));
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'human' THEN
    v_effect := v13_enqueue_effect(p_sid, 'human',
      jsonb_build_object('reason', v_route->>'reason'));
    PERFORM v13_send_work(v_effect);
    UPDATE sessions SET status='waiting' WHERE session_id = p_sid;
    RETURN 'waiting';
  WHEN 'finish' THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
      jsonb_build_object('delivered', true, 'reason', v_route->>'reason'));
    UPDATE sessions SET status='completed' WHERE session_id = p_sid;
    RETURN 'terminal';
  WHEN 'reject' THEN
    PERFORM v13_append_event(p_sid, gen_random_uuid(), 'turn/end',
      jsonb_build_object('delivered', false, 'reason', v_route->>'reason'));
    UPDATE sessions SET status='failed' WHERE session_id = p_sid;  -- §3.6 #4 映射
    RETURN 'terminal';
  ELSE
    -- 兜底 fail-closed(评审修正):v13_route 总量性被破坏时的背板——
    -- 拒绝静默继续,回整个变更事务
    RAISE EXCEPTION 'v13: route returned no action for %', p_sid;
  END CASE;
END $$;

-- === route 族 ACL 全量块(turn 5,P1-5/#37):M3 advance.sql 尾部落,
--      与 §3.1 矩阵逐一对应 ===
REVOKE EXECUTE ON FUNCTION
  v13_context_fresh(uuid), v13_env_decision(jsonb,text),
  v13_env_answer(jsonb,text), v13_env_hit(jsonb,text,text),
  v13_route(uuid,jsonb), v13_resolve_tool_params(jsonb,text),
  v13_probe(uuid), v13_advance(uuid,jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_context_fresh(uuid), v13_env_decision(jsonb,text),
  v13_env_answer(jsonb,text), v13_env_hit(jsonb,text,text),
  v13_route(uuid,jsonb), v13_resolve_tool_params(jsonb,text),
  v13_probe(uuid), v13_advance(uuid,jsonb)
TO v13_route;      -- 持锁变更链:只授 route(resolve/recall 零建账面);probe
                   -- 仅 advance 步 0 消费(turn 8,#56)
