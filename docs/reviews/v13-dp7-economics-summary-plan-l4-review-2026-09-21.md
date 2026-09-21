# v13 DP7 计划评审:经济件与摘要验收链(v13-dp7-economics-summary-plan-2026-09-20.md)

评审日期:2026-09-21。评审:L4 代行(独立全新会话;ask_oracle 通道持续故障,按 loop 先例代行)。一次有界计划评审——仅评审、不实施、不改 plan、不运行任何 gate。

## Context / Scope

- 被审文档:`docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md`(1034 行,首写轮,全文已读)。撰写方未跑内部批判,本评审是最先的独立评审。
- 交叉参照(均实读):设计冻结稿 `docs/designs/v13-context-on-pg.md`(487 行;§5.4/§5.5/§6.1–§6.7/§9/§10/§11–§14 重点节全文);stepfun 设计审查 F5/F8/F9(行 50–56/71–76/77–80);上游契约行逐条对照:DP1 §1.3 DP7 行(:57)+机制面(effects 单活跃 :225–226、v13_last_user_seq :250、effect_attempt_cap 种子 :853–854、v13_gap :1587–1592、v13_policy ACL :986、llm enqueue request={route} :2484–2486、v13_route llm 返回 :2132、v13_complete llm 形状校验 :446–451);DP2 §1.4 DP7 行(:66)+judgment_calls DDL(:324–344)+v13_guc_required(:570)+信封 budget/timeout 冻结纪律(不变量 8);DP3 §1.4 DP7 行(:170)+外层十键串(:582–583)+policy 四键(:603–606)+token 七键(:57)+artifacts/inline(:290–292)+sessions.context_active_artifact(:339–342)+replay.prior_artifact_id(:105)+judgment_defaults 种子形状(:452–458);DP5 OQ5 recall_k(:77);DP6 §1.4 DP7 行(:103)+OQ7/OQ10(:94/:101)+OR REPLACE 机械复制纪律与 V3006(:153)。
- 评审方法:rubric 五项 PASS/FAIL+证据;五项重点推演(R_o 桶与排除谓词/hysteresis 可测试性/八步第 6 级×DP1 effect 语义/花费闸层位/预算包原子性);机械猎(percentile_cont 窗口帧/OR REPLACE 锚定完整性/策略种子数字/三值/签名/前向引用/附 B 计数)。

## 已核实成立的关键断言(不重复列入 Findings)

- **OQ2 摘要链拓扑成立且是本 plan 最强的部分**:三重硬约束全部真实(单活跃 DP1:225 逐字核过;settle 零外部 IO=DP3 不变量 1;`v13_complete` 对非 llm/tool/judge kind 零语义事件=DP1 #20/#26 机制面),跨平面三段(settle 记 intent→静默期 schedule+prepare→下一 settle 消费)绕开全部三约束;被拒替代两则(寄生 kind='llm'/settle 体内同步生成)的否决理由与上游机制逐条对得上。验收 decision 落地→token.dec 追动→refresh 自然可达,零新触发机制,与 DP3 token 语义吻合。
- **G-ctx6 绕行合法**:F8 冲突实存(设计 §10 :400 原文 vs §5.4 轮 2 修正 :211–214 逐字对照);轮 2 P0 修正原文核实;plan 头注+§4 取代表+风险 10 三重标注,gate 按修正语义重写(C 组三断言:单 Plan 单调/跨 turn hysteresis/负向 fixture「永久锁死不可构造」)——正是 stepfun F8 修复建议的 plan 内落地形态。
- **覆盖面完整**:§2 映射表逐行对得上——§5.4 全条目(tier 带/压力公式/R_o 分位/E(r) 三纪律/r* 0.145 注释/cache-break 归因)、§5.5(失败样本不进分位)、触点 1 shadow-first(hint 记录面+硬类保护+goal_hash 引用 DP3 OQ2 零改)、触点 2 全链、§6.4 八步逐条(J/K/L/M/O/N/O6)、§6.7 不整合(§7 全表+不变量 5/7)、§9 策略行(context_budget 三桶/tier 带/E(r) r/render_policy;filter 批上限归 DP6 已落)、F5①③、教程 §13 零改动指针义务、§12 台账。
- **上游契约消费清单 30 条逐条对照上游 §1.3/§1.4 原文,转述无失实**(除 P1-1 的种子数值——那是本 plan 写错,不是转述错)。附 A 12 项分歧的裁决与呈报姿势(tiers 载体/L_eff 载体/source=kind/active 标志代 now()/pricing 不入 token/三桶 ACTIVE 分层论证/F9 转呈/触点 1 归属 #9 呈报)均可辩护;#9 的呈报(建议控制器改 DP8 brief 消费本 plan 契约,防双实现)是本轮汇报主项,姿势妥当。
- **OQ5 的 active 标志选择论证成立**:装配零时钟(不变量 6/DP3 确定性)与 now() 选行结构性不兼容,区间元数据+翻版仪式是保持 exact replay/recompute 可推演性的唯一形态;pricing 不入 token 的论证(r 只翻账单不翻正确性=设计原文)与 context_tiers/context_budget 必追动形成正确对照。
- **OQ7 多段化规则**(kind 唯一时=kind/多段一律 kind:8hex,无例外分支)兑现 DP6 OQ7 移交且为 chunk sections 预留纯数据落地;DP3 骨架三 kind 各一段⇒前缀库零漂移的推演成立;§1.4 落地动作清单含 span_assembly 入 token 的必做项(漏=语料 freshness miss)。
- 机械面:11 外层键字典序串正确(economics 首位);econ_ver 材料 string_agg ORDER BY name 确定性;span_digest 按值聚合=set 语义,与「hash 序」表述一致;est 公式零第二实现;V3007 无占用(DP6=V3006 核实);12 号文件零前向引用 13 号对象;新函数 11 个签名全树唯一;ACL 形态(pricing_r 默认参四参写法/双登录分派 schedule·checks→route、envelope·verdict→resolve)与 DP1 角色面吻合;一里程碑一提交/按路径 add 与 AGENTS.md 对齐。

## Findings(1 P0 / 6 P1 / 8 P2)

### P0-1 R_o 桶的 model 谓词在生产 llm effect 行上结构性恒空——分位机制全员死谓词,G-ctx6 第二断言生产面不可实现,而 B1/B2 fixture 绿

- 位置:§3.1 `v13_ro_reserve` 草案桶查询(plan ≈336–344)`AND request->>'model' = v_model`;OQ3 桶定义(plan ≈158);附 A #3(source=effects.kind 载体化)。
- 问题:DP1 advance ④ llm 分支 enqueue 的 request=`jsonb_build_object('route', v_route)`(DP1:2484–2486),而 `v13_route` 的 llm 返回=`{action:'llm',reason:'generation_needed'}`(DP1:2132)——**request 内无 model 键,route 对象也无**;DP3 契约 #3 明文「④ llm 分支 request 仍为 {route}」,DP4–DP6 未动 advance,本 plan 自身零改动 enqueue。故全部生产 llm effect 行 `request->>'model' IS NULL` ⇒ `NULL = v_model` 恒 NULL ⇒ 桶查询恒零行 ⇒ `v_n=0` ⇒ **R_o 永久冷启动 8192**,(model,source) 桶的 model 半边死断言,G-ctx6「R_o 分位数计算正确」在生产面不可实现。B1/B2/B4 fixture 手插行自带 request->model ⇒ gate 全绿地放行死谓词——fixture/生产形状分叉的经典死法;B5 若走真实 enqueue 路径会红,但 plan 未钉死该构造口径。附 A #3 的 source 载体化结论随之不成立(as drafted)。
- 修法(推荐前者):①谓词改读 result 侧——`result->>'model' = v_model`,并把 worker 契约注记扩为「llm result 应携 **usage+model**;缺失=无样本,不是错样本」(DP1 v13_complete llm 形状校验只要求 text 非空 :446–451,result 增键零 DP1 改动;§5.5「usage 已在 events/effects」本就是 worker 契约面);B1/B5 fixture 构造口径同步为 result.model。②降级:v1 不过滤 model(桶=全体 succeeded llm),分歧记附 A,DP8 generation 身份落地日再收窄。任一修法须同步 B 组 gate 文本。

### P1-1 effect_attempt_cap v2 种子与 DP1 v1 原值不符——声称「逐键保留」实改两键

- 位置:§3.2 cap v2 INSERT(plan ≈585–590)`'{"judge":3,"tool":3,"llm":3,"human":5,"context_refresh":3,"context_summary":2}'`;I2 断言「五值=v1 原值(逐键相等断言)」;附 B。
- 问题:DP1 v1 种子=`{"judge":4,"tool":3,"llm":3,"human":2,"context_refresh":3}`(DP1:853–854)。本 plan 写 judge 3(实为 4)、human 5(实为 2)——两键被改却声称原值保留;I2 首跑即红,或断言本身失实。human 2→5 还顺带放宽了 human 重试上限(行为变更走私)。
- 修法:v2=`{"judge":4,"tool":3,"llm":3,"human":2,"context_refresh":3,"context_summary":2}`;附 B 计数行同步。

### P1-2 v13_pricing 种子 INSERT 语句缺失——附 B 计数 7、枚举 6、SQL 0

- 位置:§3.1 v13_pricing 建表与 v13_pricing_r 之间(plan ≈247–290 无 INSERT);A3「种子一行(mock 值,五维 default)」、D1「种子行匹配 generation 五维⇒er.r 在场」、D5、§0「定价目录 v1 种子=mock 值」。
- 问题:附 B 称「种子 INSERT 7」但枚举(策略五行组 1+cap 1+summary_accept 1+模板两表 2+defaults 1)=6,§3.1 SQL 实含 6——**定价目录种子行整条缺失**。A3/D1/D5 三个 gate 断言依赖该行存在(er.r 非 null 的唯一构造路径);无种子则 economy 库常态=branch 'r_unknown',D1 不可构造。
- 修法:§3.1 补 `INSERT INTO v13_pricing (provider, model, ...) VALUES (与 generation mock 行同 provider/model, fresh>0, cached≥0, catalog_version=1, active=true)`;附 B 计数与枚举对齐为 7。

### P1-3 恢复窗谓词与 recovery_turns=2 声明语义不符(方向性少预留)+ recovery 布尔进装配 recovery_floor 的通路未定义

- 位置:§3.1 `v13_ro_reserve` 的 v_recovery 查询与「简化口径」注记(plan ≈314–330);OQ3/OQ4 声明(plan ≈152/≈180);B4/C4。
- 问题:(a) 草案谓词锚「最后一个 user/message created_at 之后的失败」=只覆盖**本 turn**;OQ3/OQ4 与 context_tiers.r_o.recovery_turns=2 声明「最近 2 个 user turn 内存在失败⇒p95+floor」。turn N 发生 prompt-too-long、turn N+1(恰是恢复 turn)时谓词已不可见——**在最高危 turn 按稳态 p75 少预留**,方向与本 plan 自己的「宁可过度预留,不可预留不足」教义相反;recovery_turns 策略键成为无消费方的死配置(违反「参数全用」自检精神)。(b) OQ4 的 tier recovery_floor 在装配体内计算,但恢复判定的声明单源在 v13_ro_reserve 体内(返回 bigint)——**装配如何获知该布尔全程未定义**;复制谓词则违反哈希/公式同源纪律(C2 的 basis='recovery_floor' 断言面悬空)。
- 修法:抽单源 helper(如 `v13_recovery_active(sid) boolean`,或 `v13_ro_state(sid)→{recovery,p,ro}`)由 v13_ro_reserve 与装配 recovery_floor 双消费;窗口实现为「第 recovery_turns 个最后 user/message 边界之后的失败」(或等价 turn_no 回溯);B4/C4 fixture 对齐跨 turn 语义(turn N 失败⇒turn N+1 floor+p95;recovery_turns 干净轮后衰减)。

### P1-4 v13_summary_schedule 守卫链缺花费闸——J2/J3/§6.4-1 的「预留失败零调用」执法点在草案中不存在

- 位置:§3.2 `v13_summary_schedule` 守卫枚举 ①–⑤(plan ≈755–790:仅 single-active/intent/cap_day/spans/request 形状);OQ2 步 2 散文(「intent 在场+**花费**/调度闸过」)、OQ8(「预留=schedule 时点判定(花费/调度闸+策略在场)」)、J2(「花费闸超→NULL」)、J3。
- 问题:散文与 gate 都断言花费闸参与 schedule 判定,草案守卫链却没有 `v13_judge_spend` 检查——实施者按 SQL 草案直写则 J2 红且 §6.4-1「预留失败直接 drop/spill,生成与 Jev 都不调」的执法点缺位。
- 修法:守卫链增一条 `v13_judge_spend(p_sid)->>'over' ⇒ RETURN NULL`(或并入③调度闸同点);J2/J3 断言面随守卫成立。

### P1-5 v13_summary_envelope 缺 v13_resolve_judgments 的必需键(至少 candidate_set_hash)——「resolve 消费六键」的断言与 DP2 实况不符

- 位置:§3.2 信封草案与「信封键集=本函数专用面(resolve 消费 needed/ctx/provider/model/budget/timeout 六键…)」断言(plan ≈695–725);OQ2 步 3。
- 问题:DP2 `judgment_calls.candidate_set_hash **NOT NULL**`(「信封批次锚,审计回连 parse/worker 轮」,DP2:327)——resolve 每次ask 落一行必从信封取该键;DP1 effect 信封七键亦含 candidate_set_hash(worker 契约 #2)。本信封七键(sid/ctx/needed/budget/timeout_ms/provider/model)喂 `v13_resolve_judgments(env,1)` 会在 judgment_calls INSERT 处 NOT NULL 违反(或更早 fail-closed)。「六键足够」是失实断言;DP2 resolve 的完整消费键集(templates/groups/projection 分组面)也未逐键对齐。
- 修法:信封补键——candidate_set_hash=span_digest 是自然锚(与 signal 同源);按 DP2 §3.6 resolve 实际消费键集逐键对齐后重写键集断言;gate L1 增「验收 ask 落 judgment_calls 行携该锚」断言;附 A 记载体化。

### P1-6 v13_summary_verdict 签名无法重建 ctx 材料——缺 source 半边,裁决路径按草案不可执行

- 位置:§3.2 `v13_summary_verdict(p_sid, p_span_digest, p_body)`(plan ≈730–750)——裁决=request_hash/`decisions.context` 等值 join(DP6 不变量 6 同构:材料=存储)。
- 问题:ctx 材料={source(span 全文), summary} 双半边;签名只携 p_body(摘要),source 无法重建 ⇒ request_hash 算不出、context 等值 join 构造不出,函数按草案不可执行(签名在「列/约束/签名/关键语句到位」的草案级承诺面内,不应缺参)。
- 修法(二选一):①签名扩为 `(p_sid, p_span_digest, p_source, p_body)`;②更干净——改从 `effects.result->rounds[].decision_id` 直取(OQ2 步 3 已把 decision_id 冻进 context_summary 的 result,零材料重建),CJK 门材料改读 decisions.context。附 B 签名机械项下补对齐记录。

## P2(实施期处置;不阻断)

1. **§1.1「六处 OR REPLACE」计数漂移**:§3/附 B 实为 7 处语句(5 函数:12 号五件+13 号 assemble/validate 再跳)。授权按引用 §3 生效,无实质越界;改「七处(五函数)」防后续按封闭清单对账失配。
2. **日闸作用域读法呈报**:`v13_judge_spend` 的 day_asks 带 `WHERE session_id=p_sid`——per-session-每日。F5①「per-session/每日」两读;键名(session_asks_cap/day_asks_cap)支持现读法且 F5 攻击面(单 session 零 turn 刷花费)被覆盖,但若意图是账户级日闸需去 session 过滤。README 明示选择即可。
3. **「GRANT SELECT ON v13_policies——DP1 已授」注记未核实**:DP1 ACL 块只见 `v13_policy(text)` EXECUTE 授 resolve/route(:986–987),表级 SELECT 未见;本文件自授无妨,注释改「本文件自授」防误导(gate A5 口径同步)。
4. **budget 键语义对齐**:信封 budget=packs_reserved(1)喂 DP2 resolve 的 budget 消费(批问数上限口径?)——单位语义需实施期与 DP2 §3.6 对齐,防 1 被解读为批大小导致的意外分批。
5. **信封 question/criteria 子查询占位**(`/* frozen latest 等价形态 */ true`):已有实施期对齐注记;建议直接引 DP2 模板 latest 视图名,消掉占位。
6. **effective_budget 无下限守护**:`least(budget_tokens, l_eff−R_o)` 理论可负(小 l_eff×大 cold_tokens)⇒ 全 skip 空清单;种子数字(128000−8192)下不可达,建议 clamp≥0 或形状守卫加 l_eff>cold_tokens 约束。
7. **v13_ro_reserve 直读 v13_policies 取 generation.model**:绕过 `v13_policy()` 单源;行缺失时静默走冷启动(方向安全但配置错误不响亮)。建议改 `v13_policy('generation')->>'model'`(fail-closed)或注释声明该差异。
8. **effects fixture 构造口径纪律**:B 组若全走手插行会重演 P0-1 的形状分叉;建议 gate 纪律明文「R_o/恢复类 fixture 至少一半经真实 enqueue/complete 路径构造」(与 P0-1 修法联动,独立成立)。

## Rubric 裁定(逐项)

| # | Rubric | 裁定 | 证据要点 |
|---|---|---|---|
| 1 | 可开工(SQL 完整;OQ 八项可辩护) | **FAIL** | OQ1–OQ8 全部裁决且论证可辩护(双 stage 四依据/拓扑三约束/冷启动方向/载体化/闸层位/多段化/验收面);但 SQL 不完整:P0-1 死谓词+P1-1 种子值错+P1-2 缺种子语句+P1-4 缺守卫+P1-5 缺键+P1-6 缺参。修后 PASS。 |
| 2 | 覆盖 §5.4 全部+§5.5+触点 1+2+§6.4 八步+G-ctx6 绕行+G-ctx8+F5+教程+不做 | **PASS** | §2 映射逐行核过(见「已核实成立」);八步 J/K/L/M/O/N/O6 逐条有 gate;G-ctx6 绕行=stepfun F8 建议的落地形态;§7 不做全表含 §6.7 永久拒绝项。 |
| 3 | gate 可执行不弱化 | **有条件 PASS** | hysteresis C3(cooldown/至多一档/升档即时,artifact 链 fixture 可控)、E(r) D1–D5、八步 O 组(不可跳级负向 fixture)、冷启动 B3(方向断言)、Jev 口径 O6(零新增行≠零成本)全可构造。例外随 P0-1/P1-3/P1-4 修:B1/B5 构造口径、B4/C4 跨 turn 语义、J2 守卫。 |
| 4 | 不越界 | **PASS** | 触点 4/6/3 台账(§7 前三行);render 本体/latch 不抢(render_policy 行=§9 明文策略行,DP8 消费缝+落地日追动键义务在 §1.4);manifest v2+多段化=DP6 OQ7 明文移交(义务);触点 1 归属分歧附 A #9 呈报妥当且建议控制器改 DP8 brief;F9 附 A #8 转呈。 |
| 5 | 承接 | **PASS** | est 公式零改(机械复制注记)/summary est 同源;post-execute 零生产者维持;spans 缝=OQ7 多段化+落地动作清单(span_assembly 入 token 必做项在档);DP6 trace(transform 全程)/final_action(L5)/一页账 v3;五 OR REPLACE 同签名(H3 pg_get_function_identity_arguments);V3007 无占用;消费清单 30 条对照无失实转述。 |

## 重点推演结论(控制器指定五项)

1. **R_o 分位桶与排除谓词(①)**:排除谓词本身精确——status='succeeded' + completion_tokens `~ '^[0-9]+$'` 双守卫:failed/unknown 排除、succeed-但-usage-缺失排除且**不计入样本数**(count 与分位同 WHERE,口径一致),「缺失=无样本不是错样本」成立。但桶的 model 半边是死谓词(P0-1),恢复窗半边与声明语义不符(P1-3)。
2. **hysteresis(②)**:可测试——载体=context_tiers.hysteresis 两键+artifact 链派生(prior manifest 经 context_active_artifact→replay.prior_artifact_id 回溯,turn_no 归属,零时钟零新表);C3 fixture 经 refresh cycle 控 raw 压力可构造 cooldown 内零降级/满窗降一档/升档即时;basis 词表含 prior_held。成立。
3. **八步第 6 级×DP1 effect 语义(③)**:相容——spill 是 manifest 段内容变换(tool/result 正文→stub 引 effect_id),effects 行 append-only 且「被引用即保留」(DP3 §7 缝,plan 已引用);transform={applied,name:'spill'} 继承 DP3 审计结构;goal/tools 硬类保护 gate O5;「clear」并入 spill(存根即保留可恢复性)可辩护。成立。
4. **花费闸层位(④)**:parse 换体前置分支正确——不动 advance/resolve;remaining=缺口计数与 DP1 v13_gap 同源谓词核过(answer 非空且 status∈answered/cached 非缺口,:1587–1592);缓存命中两路零重问;缺口经 advance ③ 原路径转 judge effect 慢路;慢路不闸的立法(turn_budget 结构性限流)成立。唯一缺口在 schedule 侧守卫(P1-4)。
5. **预算包原子性(⑤)**:guard-then-enqueue 单函数单事务,生成只发生在 effect claim 后的 worker 面⇒「预留失败不调任何东西」结构性成立(修 P1-4 后 J3 可断言);并发下软闸可能超射 1–2 ask——经济闸非正确性闸,可接受(README 注记即可)。

## 机械猎记录

percentile_cont:ordered-set aggregate 无窗口帧,形态正确;p 为 numeric→float8 隐式 cast 合法;零行 NULL→cold 分支收口 ✓。OR REPLACE 增量锚定:五换体逐处「机械复制+唯一增量」注记在案;§1.1 计数漂移(P2-1)。策略种子数字:attempt_cap 两键错(P1-1)、pricing 种子缺(P1-2);bands 6000/7500/9000、min_samples 20、cold 8192、p75/p95、cooldown 2、buckets 0.35/0.55/0.10、l_eff 128000、闸 512/8192、accept 0.80/review 0.50–0.80、cjk 0.30、packs 1、schedule_cap 8 与设计/OQ 一致;recall_k 四参引 DP5:77 原文核实一致。三值:defaults 三态 {missing,timeout,review}×exclude 与 DP3 校验器(键集恰等+动作词表四值,:456–458)吻合 ✓。签名:11 新函数全树唯一;verdict 缺参(P1-6);pricing_r 默认参+ACL 四参写法正确 ✓。前向引用:12 号零引用 13 号对象(H4 另有断言);上游引用≤前缀(guc_required/judgment_templates/enqueue/last_user_seq 均核实在 1–5 号)✓。附 B 计数:46 语句(21+25)逐条复核吻合、ACL 9(5+4)吻合、函数 11/表 1/触发器 1/索引 1 吻合;种子 INSERT 7 vs 实际 6(P1-2)。十一键字典序串正确;span_digest/econ_ver 材料确定性 ✓。

## 裁定与出口

**verdict:FAIL(1 P0 / 6 P1 / 8 P2)。** 按验收线(无 P0/P1)不通过,退回修订。全部修法为局部修正——一处谓词载体+一处种子值+一条 INSERT+一处守卫+一个信封键+一个签名参+恢复窗单源抽取——不动 OQ1–OQ8 裁决拓扑、不动双 stage 切分、不动 §1.4 对 DP8/实施期发布的契约面(render_policy 缝/economics 块形状/多段化规则均不受影响)。修版经控制器 diff 级复核(P0-1 与 P1-3 涉及 B/C 组 gate 文本联动)后即可开工,无需全量重审。

**是否可进 DP8:否。** 交付排序第 5 步以第 4 步交付为前置,DP7 修版未过验收线前 DP8 不启动。修复面不触及 DP8 将消费的契约,DP8 的 brief 修订(附 A #9 触点 1 归属呈报)可并行筹备。

## 静态核验

- 被审文档基线:`docs/plans/v13-dp7-economics-summary-plan-2026-09-20.md` 1034 行,全文已读(3 段)。本评审未改动该文件。
- 交叉参照实读:设计稿 §5–§6/§9/§10/§12–§14 重点节全文;stepfun 评审 F5/F8/F9 节;DP1 §1.3 DP7 行+effects/enqueue/complete/parse-gap/policies 种子与 ACL 节选;DP2 §1.4 DP7 行+judgment_calls DDL+guc_required;DP3 §1.4 DP7 行+token/manifest/defaults/artifacts 节选;DP5 OQ5;DP6 §1.4+OQ7/OQ10+§3 纪律。引用行号均来自上述实读;plan 内位置以节+≈行号标注。
- 未运行任何 DDL、gate 或 runtime 探针;未加载任何数据库。
