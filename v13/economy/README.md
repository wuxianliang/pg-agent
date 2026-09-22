# v13/economy — DP7 M1:经济件(决策与记账平面)

> **状态（2026-09-22）：economy gate 全绿（exit 0，238 PASS），已提交推送。**
> 修复轮记录见下；M2（summary）的 B-DP7-1/B-DP7-2 阻塞仍待解裁。

## 修复轮记录（2026-09-22，接续前轮 C4 红）

### 前轮保留的测试修正（已全绿）

仅改 `test_economy.py`，未改 SQL/上游/计划：

1. `tune_t_used` 经真实 append/canonical 路径与 SAVEPOINT 回滚探测精确长度，
   替代固定假定 JSON 包装为 40 字节；C1 目标仍严格等于 800。
2. C3 每 turn 至多降一档：高压实际为 AggressivePrune，逐轮断言
   CompactHistory → TrimSchemas → Normal，另保留升档即时断言。
3. D1 工具结果携真实 user seq 锚并提供可恢复正文。

### 本修复轮的测试修正（全部为断言语义/fixture 错，SQL 零改）

按 plan §4 逐条裁定，SQL 与 plan 语义全部一致，红全部落在测试层：

4. **C4 fixture 漂移**（首红）：l_eff=1000 时 21 条 "small post-failure"
   消息（history est 517）+p95 R_o(39) 越过 6000bp 带沿→raw=TrimSchemas。
   plan C4 要求「即使该 turn raw 低」→fixture 改 l_eff=4000（带下 2.4×
   余量），断言保持 raw=Normal 强形式未削弱。SQL（recovery_floor/
   v13_recovery_active 单源/p95 切换）零改。
5. **C5 基线错**：断言三段全 verbatim，但 DP3 基线（manifest B2）钉 tools
   =catalog_digest；改为逐段对齐真实 DP3-C1 基线（全部 applied；goal/
   history verbatim，tools catalog_digest），动作层零激活断言保留。
6. **E1 时间戳扫描误报**：裸后缀 "ts" 匹配 buckets/judgments 名词；matcher
   改精确名/下划线后缀（真时间戳键仍可红）。
7. **E4 同 turn 二次 refresh 缺 cycle bump**：enqueue 对同身份 succeeded 行
   幂等返回不重开→claim 空；按 F1 同款补 turn/route 编排事件（×3）。
8. **E6b 超长 user 文本触发 recall 分段器 fail-loud**（v13_query_segments
   >256 字节段 RAISE）：改 DP3-C2 同款缩 budget_tokens=8（core_cap=2<
   goal est），「首段超自身桶 cap 即 skip」断言语义不变。
9. **G1 缺参数元组**（`%s` 未绑定→PG 把 `%s` 解析为列 s）；同轮补齐 G1
   完整驱动链：②先路由 context_refresh→settle→recycle（上游 parse_settle
   同款；resolve 会消耗 provider/model GUC 且 typesafe 库加载后前缀保留，
   新后端才能重设）→重解析（全缓存命中）→单次 advance 达 llm 路由面；
   mock noul=0.1（默认 0.9 会命中 gate_off_topic reject 带→terminal）。
10. **G2/G5 同款驱动链**：G2 在 advance 前补 settle+recycle+重解析；G5 的
    mock 改为「信封作用域」（mock provider 会对未问信号拒收——预答 intent
    被 gap join 排除后，mock 必须同步排除），新增 mock_for_env(env,exclude)。
11. **G3 双插入 sessions**（new_session 已插入，重复 INSERT 撞主键）→删。
12. **H1 翻版 SQL 聚合错**（max(version)+1 与裸 value 无 GROUP BY）→子查询
    形态；settle∥settle 线程改用全新 session（旧 session 的 refresh effect
    已终态→幂等返回无 ready 行→对端 claim 抢空）。
13. **H4 自扫描自噬**：扫描列表字面量本身命中自身→token 运行时拼接
    （检查保持 1:1 可红）。

最后实跑：`uv run python v13/economy/test_economy.py` **exit 0，238 PASS/
0 FAIL**；前序 11 gate 全部复跑 exit 0（185/120/119/117/367/378/298/211/
143/292/94——twophase/envelope 较交接基线 116/366 各 +1，确定性非回归，
其余恰等）。

### B-DP7-1：摘要消费需要的 settle 落行变更未获授权（**M2 阻塞，未解裁**）

冻结 plan §1.1 仅授权七处 OR REPLACE（economy 五处；summary 仅 assemble 与
validate）；§3.1 refresh(c) 明定 complete/blob/lander/指针段零改。与此同时，
§3.2 assemble(iii)、L2/O1 要求采用摘要后 history 收缩为 protected tail，且
summary 正文在下一次 settle 经 `v13_blob_land` 落库。

实际 `v13_refresh_context`（本文件同目录 SQL:1425–1444；上游
`v13/manifest/v13_manifest.sql`:800–819）固定重读完整 canonical messages，
用 `v13_blob_land(p_effect,v_hist)` 落全量 history，再与 manifest 的 history
hash 比较。不等即 V3003；它只处理 history/tools，零 summary blob 落点。
`v13_artifact_land` 也不会递归落 manifest 中的 payload_ref。

**PG 实机探针已完成，退出 0（即成功观察到预期的拒收）**：

- 在 economy 前缀库事务中建立四个真实 user/assistant round。
- 从 `pg_get_functiondef` 取当前 assembler，仅临时把 history 候选正文改为
  `jsonb_path_query_array(cs.c -> 'messages', '$[last-1 to last]')`；保持现有
  refresh/validate/lander 不变，模拟 summary 被授权换体中的 history 收缩。
- `v13_manifest_validate` 通过，history est **308 → 77**，content_hash 改变。
- 真实 enqueue → claim → `v13_refresh_context` 返回异常：
  `V3003: v13: history blob hash drift vs manifest section`。
- 回滚到 SAVEPOINT 后逐字核验 assembler 定义恢复，再回滚全部 fixture；
  零探针持久改动，零上游文件编辑。

不能通过保留原 hash、移除 history、worker 越权落库、装配读路径写库或绕过
哈希 belt 来“通过”O1。解阻需要用户明确授权 summary 阶段再次换体 refresh，
在既有锁/CAS/落行事务内写入与 manifest 完全同源的 tail 与 summary 正文。
该修法会增加第八处换体；**当前没有实施，也没有修改冻结 plan**。

### B-DP7-2：M1 与 K2 的 decision 数量矛盾（**M2 阻塞，未解裁**）

K2/§6.4-3：round1 确定性检查失败必须零 Jev/零新增 judgment_calls；该轮因此
不会产生验收 decision。M1 同时要求“round1 检查失败 → round2 重生成”后
**恰两条 decision**。正常可达数量是 0+1=1，不是 2。

需裁决分开两场景：确定性失败后重生成测 0+1；首轮确定性检查通过但语义验收
拒绝后重生成测 1+1，并保留同材料缓存负向对照。未经授权不得自行更改 M1。

Oracle 聚焦核验（chat `new-chat-F7280F`）确认两项冲突；本记录不是完整实现
评审或父循环 L4 验收。A–H 已全过（本修复轮）；I–P 未交付。B-DP7-1/B-DP7-2
解裁前不开 M2 实现，更不开 dp8。

第 12 位 SQL 文件(`v13/load.py` 纯末尾追加)。tier 带/R_o 分位/E(r)/花费闸的
立法与记账;manifest v2 的 economics 半边。设计:§5.4/§5.5/§6.2 触点 1/
§9/§10 G-ctx6(轮 2 修正语义——单 Plan 单调+跨 turn hysteresis;§10 原措辞
被用户裁决取代)。全部纯 SQL 派生,零外部 IO,零 stannum 依赖,零 judgment-IO
引用(gate A5 归一化扫描)。

## 机制

- **tier**:压力 `bp = ((T_used + R_o) * 10000) / L_eff`(纯 int 基点算术);
  T_used=装配候选 Σest_tokens(pre_skip 段不计);bands 半开区间 [lo_bp,hi_bp)
  载体=v13_policies 行 `context_tiers`(四档 Normal/TrimSchemas/CompactHistory/
  AggressivePrune)。单 Plan(同 origin user turn)内 effective=max(raw,
  predicted,recovery_floor)(pressure 域取 max 再映 tier);跨 turn 降级需
  held 档 band 下界连续 `cooldown_turns` 个前驱 turn 均低于,且每时至多
  `max_downgrade_steps` 档;升档无冷却。tier.basis∈{raw,predicted,
  recovery_floor,prior_held} 全程可观测。状态从 artifact 链派生
  (`sessions.context_active_artifact`→`replay.prior_artifact_id`,链深上限 16,
  超出=保守 hold),零新状态表、零时钟、零随机。
- **R_o**:`v13_ro_reserve` = percentile_cont(p) over effects 桶 `kind='llm'
  AND status='succeeded' AND result->>'model'=<generation 活动 model> AND
  usage 数值防御`——**model 谓词读 result 侧**(P0-1:生产 llm request 恒
  {route} 零 model 键,读 request 侧=恒空桶=永久冷启动);桶按 model 全局
  (分位是跨会话统计),不按 session 过滤。失败样本排除=status 谓词结构性
  保证;usage/model 缺失=无样本不是错样本。**空桶冷启动 fail-safe**:样本数
  <min_samples(20)⇒返回 cold_tokens(8192)——宁可过度预留,不可预留不足
  (预留不足的失败模式是 prompt-too-long 硬失败,其恢复循环正是 §5.5 点名
  要防的分位毒化面)。恢复期(最近 recovery_turns=2 个 user turn 边界内存在
  prompt_too_long/context_length 失败)切 p95,判定单源
  `v13_recovery_active`(ro_reserve 与装配 recovery_floor 双消费,零复制谓词)。
- **E(r) 三纪律**:`v13_pricing` 目录(PK 五维+catalog_version;每维度键
  at-most-one active;append-only 触发器镜像 v13_policies_frozen;r=派生比值
  `v13_pricing_r`,零存储冗余)。**装配零时钟**:当前适用行=active 标志,
  effective_from/to 仅运维/审计元数据(区间选择会破 exact replay 可推演性)。
  er.branch∈{adopt,loss,r_unknown,hard_window,actions_off} 判定序:r 缺失→
  r_unknown(**不用猜测 r 决定压缩**,仅 hard window 可动作);bp≥hard_window_bp
  →hard_window;actions_enabled=false→actions_off;r<0.145(r*,ContextPipe
  实测盈亏平衡点,载于策略行 note)→loss;e_comp<e_base→adopt。E(r) 只是
  输入成本代理(未覆盖摘要调用、输出与延迟;r 错误翻转的是账单选择,不影响
  正确性)——**pricing 不入 token**(翻版不追动,gate D5)。
- **三桶装箱(v1 ACTIVE)**:effective_budget=least(budget_tokens,
  l_eff_tokens−R_o);桶 core={goal,tools}/history={history}/retrieval={其余
  未来 kind 默认类};桶 cap=floor(effective_budget×ratio);桶内全序
  (prank,section_id) run_incl 超桶 cap 即 skip(reason='budget');桶间不挪用;
  Σapplied≤effective_budget(ch10 第五断言保持)。三桶是确定性装箱策略(无
  校准依赖,不改「是否压缩」只改「装多少」),与 tier shadow 分层论证(OQ4)。
- **花费闸(F5-1)**:`judge_spend_gate {session_asks_cap:512, day_asks_cap:
  8192, scope:'fast_path'}`;计数单源 `v13_judge_spend`(judgment_calls 全
  calls,含 filter 族/摘要验收 ask,无 signal 过滤);执法面=v13_parse 换体
  前置分支:过闸⇒跳过 resolve(零新增 ask)、remaining 改由 v13_gap 同源缺口
  计数(缓存命中自然消费——已答行非缺口)、缺口转 judge effect 交慢路;
  未过闸与 DP1 行为逐字节等价(gate G1)。**慢路不闸**(OQ6 立法):慢路 ask
  由 turn 推进驱动,速率受 turn_budget 结构性限流;F5 的悬崖是快路同步付款。
  日闸作用域=per-session 每日(day_asks 带 session_id 过滤——单 session 零
  turn 刷花费攻击面已覆盖;账户级日闸=未来 scope 翻版,呈报在案)。
- **F5-3**:`fastpath_tiers {tiers_over_one_batch:[]}`——v1 无任何 tier 允许
  快路超 1 批。放宽流程(三前提缺一不可):本表翻版 ∧ resolve_fast_path v2
  同批(advance 内上限读点协调)∧ 重开一页账(F5-2 表)+评审。
- **k_max 放宽流程**(DP5/DP6 契约转发):recall_k 新版本行+重开一页账+
  fastpath_tiers 联判。本 plan 不放宽。
- **cache-break 归因**:`v13_cache_breaks(sid)` 一条 SQL——active manifest vs
  其 prior_artifact 逐 section content_hash diff+首断点后缀重计费面标记;
  新段即断(prior 无该 section_id⇒broke=true)。churn(DP3)是输入,归因是
  消费(F3 单源互证)。
- **token 追动键 econ_ver**(第十键)=sha256(context_tiers/context_budget
  active 行 name:version 串);**只罩 assembly 消费的经济学行**(pricing/
  spend gate/render_policy/fastpath_tiers 不入 token,逐行论证见 plan 不变量
  8);键集增删⇒全域恰一次 refresh(OQ1)。
- **manifest v2**:外层 11 键(+economics);policy 块 7 键(+tiers/budget/
  pricing_version);required_revision 10 键(+econ_ver);section_id 多段化
  规则(单 kind 单段=kind;同 kind 多段一律 kind:8hex——chunk sections 缝的
  结构性预留,DP6 OQ7 兑现);validate v2 economics 层键集封闭执法。
- **锁序**(refresh v2):sessions→tools_meta→策略活动行(五名,name 序)→
  **v13_pricing active 行殿后**(provider,model,account,cache_class 序)→
  effects;策略形状守卫扩 context_tiers/context_budget(锁面=装配输入)+
  judge_spend_gate/fastpath_tiers/render_policy(同点 fail-loud 配置前置)。

## 运维纪律

- **tier 本地校准流程**:跑语料/会话 fixture→观察 economics.pressure.bp
  分布→定 bands→翻 context_tiers 新版本行(actions_enabled=true 同批)——
  零代码。0.60/0.75/0.90 只是 shadow seed(轮 2 P0 原文);actions_enabled=
  false 时动作层零激活,经济面全量记录(C5/C6)。
- **定价目录运维仪式**:录入=新 catalog_version 行 INSERT inactive→双
  UPDATE 同事务翻 active;区间元数据同行;维护自动化=§14 遗留开放项(手动
  仪式)。
- **花费闸收紧**:本地校准后翻 judge_spend_gate 新版本行(种子 512/8192 是
  事实 shadow——DP6 一页账最坏 12 asks/turn)。
- **翻版纪律**:全部策略翻版=INSERT inactive→双 UPDATE 同事务翻 active
  (v13_policies_frozen 拒 value 改写/DELETE);refresh 前形状守卫 V3007。
- **措辞纪律**:放弃分支零新增 Jev 调用≠零成本(已超时/失败调用可能已计费;
  gate 断言口径=零新增 judgment_calls 行)。

## F5-2 一页账 v3

| 面目 | 调用数 | 快路 | 慢路轮(effect 往返) | 量级 |
|---|---|---|---|---|
| 判断面(DP6 表原样) | k=64 最坏 4 asks | 1 批 | 3 轮 | ≈4×1.3–1.6s |
| 摘要 prepare(每 pack) | 1 gen+1 Noul | 0 | 1–2 轮 | gen 数秒级+Noul ≈1.3–1.6s |
| 验收缓存命中 | 0 新增 | — | — | 零(同 materials 重验) |
| 超闸快路(F5-1) | 0 新增 | 0 | 缺口全转慢路 | 快路零延迟增量 |
| 重生成(packs=2) | +1 gen+1 Noul | 0 | +1 轮 | 两 pack 最坏 ≈2×(gen+Noul) |

结论:摘要 prepare 在静默期运行不进 turn 关键路径;若用户消息先到,turn
等待上界=单 pack 行;mock 单价=v12 G7 量级(9 问 $0.000042)。

## 偏差台账(与 plan §3.1 草案的实现级偏差,语义零偏离)

1. **er 块第 6 键 `hard_window`**(plan OQ7 列 5 键/E2 记 6 键内部不一致;
   取 6 键——OQ5「economics 块记录决策依据」为法源,布尔:bp≥hard_window_bp)。
2. **新增两个单源辅助函数** `v13_band_of(jsonb,bigint)`/`v13_tier_rank(text)`
   (附B 计数 12 个新函数→实际 9+2;tier 路由/档位序的单源载体,validate
   与装配共用同套词表)。
3. **r*=0.145 为 SQL 常量**(策略行 note 载注;plan 种子未设结构化键——
   校准后翻版时应升为策略键,本版照种子字面)。
4. **e_base/e_comp 首轮代理口径**:e_base=Σ稳定段(churn=0 且 hash 同前版)
   est×r+Σ新变段 est;e_comp=非 history 段同基线+spill 后 history(history 内
   tool/result 正文按 64 字节 stub 折算)按 fresh——「首轮代理口径,校准=
   翻版」(plan OQ5 原文授权)。
5. **A5 扫描归一化口径**:零 `==>`/零 `stannum.`/零 judgment-IO 函数名
   均按剥注释后的规范化源码计数(DP5 §4 同款)。
6. **v13_recovery_active 读 events.at 列**(events 表时间列名为 at 非
   created_at;plan 草案笔误修正,窗口语义不变)。
7. **manifest 骨架三 kind 的 est CTE 零改**;v2 对 file section 的经济面消费
   纪律(A8:注册时写入 est、缺估计不当 0、禁止锁内现估)由 DP3/DP4 已载
   装配面承接——本 stage 经济函数零文件 section 处理(chunk sections 未落地)。

## gate

`uv run python v13/economy/test_economy.py`(退出码 0=通过;A–H 八组)。
