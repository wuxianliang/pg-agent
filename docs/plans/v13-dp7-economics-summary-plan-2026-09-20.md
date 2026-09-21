# DP7 · v13 经济件与摘要验收链 — 实施计划

> 状态:修订 1(2026-09-21,loop turn 30)——按 L4 评审 `docs/reviews/v13-dp7-economics-summary-plan-l4-review-2026-09-21.md`(1 P0/6 P1/8 P2)修复:P0-1 R_o 桶 model 谓词改读 result 侧+worker 契约扩 usage+model;P1-1 effect_attempt_cap v2 种子值对齐 DP1 v1(judge:4/human:2);P1-2 补 v13_pricing 种子 INSERT;P1-3 恢复窗单源函数 v13_recovery_active(跨 turn 窗口+装配通道写明);P1-4 schedule 守卫链补花费闸;P1-5 信封扩为十键对齐 DP2 resolve 消费面(+candidate_set_hash);P1-6 verdict 改 decision_id 直取;P2:OR REPLACE 计数对齐/日闸作用域呈报/fixture 构造口径纪律。OQ1–OQ8 裁决拓扑、双 stage 切分、§1.4 契约面零动(与 L4 出口裁定一致)。首写稿 2026-09-21(loop turn 29)。
> 撰写注记:本轮 context_builder 通道 ACP 故障(MCPToolExecutionCancelledError,与 DP2/DP3/DP6 轮同型),按 loop 既定先例**代行撰写**,全部上游契约/机制面经一手勘探核实在案(见「基座与缝」节 file:line 级引用)。
> 评审输入:`docs/designs/v13-context-on-pg.md`(冻结)§5.4/§5.5/§6.2 触点 1+2/§6.4/§6.7/§9/§10/§12/§13/§14;stepfun 评审 F5(①③归本 plan,F9 归 DP8);DP1 §1.3 / DP2 §1.4 / DP3 §1.4 / DP5 §1.4 / DP6 §1.4 对 DP7 行。
> **G-ctx6 按用户既定默认绕行**:设计 §10 G-ctx6 原措辞「tier 只升不降跨 turn 成立」与 §5.4 轮 2 P0 修正直接冲突(stepfun F8);轮 1 后用户裁决「不修冻结稿,plan 内绕行」——本 plan 全部 gate 按 §5.4/§14 已裁语义(单 Plan 内单调+跨 turn hysteresis/cooldown 受控降级)书写,并逐处标注「G-ctx6 原措辞被轮 2 裁决取代」。

## 0. 执行索引

| 项 | 内容 |
|---|---|
| **Goal** | 把设计 §5.4 经济(tier 阈值带/压力派生/R_o 分位/E(r)/cache-break 归因)、§5.5 反馈统计、§6.2 触点 1(压缩优先级 shadow-first)与触点 2(摘要验收,P1 首版留)、§6.4 摘要验收回退链八步、§9 经济切片(context_budget 三桶/tier 带/E(r) 的 r/render_policy 版本化/解析相花费闸)落成 **两个 stage**:`v13/economy/`(SQL_LOAD_ORDER 第 12 位)与 `v13/summary/`(第 13 位),以 **G-ctx6(轮 2 修正语义)+G-ctx8 摘要段**收口 |
| **Done when** | 两 stage gate 全绿(`uv run python v13/economy/test_economy.py` 与 `uv run python v13/summary/test_summary.py` 退出码 0);提交前该 stage 及之前**全部** stage 的 gate 都跑(AGENTS.md 前置条件 1;各 stage 在自己前缀库复跑,结构性互不扰动——见不变量 12);收尾工件(v13/load.py 追加两行+STAGE_THROUGH 两键、两 stage README、一页账 v3)完成;一里程碑一提交 |
| **Key files** | `v13/economy/v13_economy.sql`(全新增,第 12 位纯末尾追加)+`v13/economy/{setup_db.py,test_economy.py,README.md}`;`v13/summary/v13_summary.sql`(全新增,第 13 位)+`v13/summary/{setup_db.py,test_summary.py,README.md}`;`v13/load.py` 仅追加两行路径与 `STAGE_THROUGH["economy"]=12`、`STAGE_THROUGH["summary"]=13`,零改动既有行 |
| **Dependencies** | DP1–DP6 全部已验收 plan(十一 stage 前缀库);DP3 契约面(manifest/token/settle)是直接地基;无外部前置(定价目录 v1 种子=mock 值,实价运维期录 入,README 仪式) |
| **Size** | 2 里程碑(economy 先、summary 后,各一次提交)。economy=策略行族+派生函数+parse 闸+装配/校验器/token 三件 OR REPLACE 增量;summary=effect 平面扩展+验收模板+schedule/prepare/consume+装配/校验器再跳。量级≈DP6 两 stage 之和的 0.8(无索引/无 stannum 面) |

---

## 基座与缝(勘探摘要,实施者直接消费;与 §1.2 消费清单互证)

### 上游契约(已验收 plan 的 §1.3/§1.4 契约表,逐条 file:line 可回查)

- **DP1 §1.3 DP7 行**(v13-dp1…md:57):`v13_policies` 表载体共享——(name,version) 主键+at-most-one active(`ux_v13_policies_one_active` 部分唯一)+`v13_policies_frozen` 触发器(唯一许可 UPDATE=翻 active)+读侧单源 `v13_policy(name)`(无 active 行 fail-closed);DP1 播 resolve_fast_path/turn_budget/resolve_retry/effect_attempt_cap 四行,DP7 追加 tier 带/E(r)/context_budget,同表追加版本行。DDL 在 DP1 §3.1(约 :798–830)。
- **DP1 机制面**:effects.kind CHECK `('judge','tool','llm','context_refresh','human')`(DP1:196);**`ux_v13_effects_single_active ON effects(session_id) WHERE status IN ('ready','claimed')`——任意 kind 每 session 至多一个活跃 effect**(DP1:225);`v13_effect_id(sid,last_user_seq,cycle_no,kind,request_hash)`(DP1:272,同逻辑动作同 ID/新逻辑动作必新 ID);`v13_enqueue_effect` 对 effect_attempt_cap 缺 kind 键即 RAISE(DP1:319,#61);`v13_attempt_ok` 三点共用(enqueue/requeue/claim,turn 8 #55);advance 五步执行序 ①→[failed 审计/abandon]→②→⑤→③→④(创建)(DP1 §2 映射行);**parse+advance 成对调用契约**(DP1 §3.6 #15);effect request 只携语义词段、水位族被剔(不变量 6);origin_user_seq 锚定(不变量 7);**`v13_complete` 对非 llm/tool/judge 的 kind 只做 CAS 终态化、零语义事件**(DP1 §3.6 #20;context_refresh 即此形态)——context_summary 复用同一结构性通道;claim/complete/renew/requeue EXECUTE 归 v13_route(DP1:1002);`v13_resolve_login` 可 EXECUTE v13_resolve_judgments、route 不可(DP2 E1);双登录 v13_resolve_login/v13_route_login 单成员 NOINHERIT(DP1 §3.3)。
- **DP2 §1.4 DP7 行**(v13-dp2…md:66):判断成本核算读 `judgment_calls`(每次 typesafe_ask 一行,usage/latency/payload 在档,含成功/超时/校验拒收三态),不得从 decisions 派生(decisions 无 usage 列,设计使然)。judgment_calls append-only 触发器+`(session_id)` 索引在案(DP2 §3.2:324–354)。信封 `budget` 键=v13_policy('resolve_fast_path') 快照、`timeout_ms` 键=GUC 冻结值,两键随 effect request 携带且被 `v13_effect_id` 哈希豁免(`#-` 先删后哈希,DP2 §3.5)——**行为参数冻结值不进身份**。
- **DP3 §1.4 DP7 行**(v13-dp3…md:170):est_tokens 公式版本随 assemble_manifest 策略行(换公式=新版本行,recompute 语义自动成立);tier/E(r)/R_o 消费 sections[].est_tokens 与 judgment_calls.usage;post-execute epoch 生产者归触点 4(P2 弱标签纪律);摘要段 kind='summary' 新增 section kind+§6.4 回退链逐步落 transform.applied/skipped(DP3 transform 结构即其审计载体);judgment_defaults.points 填摘要验收点(§6.4-4 fail-closed;settle 已接线校验器——非法 active 行 refresh 即 V3003,P1-5);**真窗口=新 transform 名+新策略版本行(首版 verbatim,O2 P1-1)**。
- **DP3 机制面**:token 七键(sem/dec/goal/tools_rev/asm_ver/jdef_ver/gen_ver)+追动键缝纪律(「进 manifest 输入的策略版本必须在 token 有键,漏键=freshness miss;键集增删⇒旧 active token 全失配⇒全域恰一次 refresh」)(OQ1);manifest 外层 10 键/section 9 键/manifest_version=1,骨架三 kind(goal/history/tools),**DP4–DP7 增 kind 只加行不改结构**;transform 两分支键集精确恰等({applied,name}|{applied,reason}),name∈{verbatim,catalog_digest},reason∈{budget,priority_never,disabled,invalid_override};churn=对上一版 manifest 按 section_id 对齐的变动计数(**cache-break 归因与波动率排序(DP7)的输入**,OQ4);est 公式 `((octet_length(段规范字节)+est_bytes_per_token-1)/est_bytes_per_token)` 纯 int 算术;装箱=全序(prank First=1/Normal=2/Never=3/LastResort=4, section_id)连续前缀+run_incl>budget 即 skip+首段可 skip+Never/disabled 先标 skip 不进装箱;`v13_assemble_manifest(p_sid,p_policy_version DEFAULT NULL)` 两参签名(NULL=活动版本可 settle;钉版本=recompute 只读不落库);`v13_manifest_validate` V3003 七层键集封闭(词表/64hex/null 穿透全封);`v13_refresh_context(p_effect,p_attempt,p_fence)` SECURITY DEFINER 窄入口,顺序=入口校验→fence belt→**三层行锁(sessions→tools_meta→三族策略活动行 name 序)**→策略形状守卫→装配→validate→inline 超限→complete CAS→blob 冻结→artifact 落行→result 补挂→sessions 指针(§3.5:1120–1199);落行器 v13_artifact_land/v13_blob_land 零运行角色 EXECUTE,唯一可达=refresh 体内;全库锁序 sessions→tools_meta→策略活动行→effects(OQ3);epoch=decisions.epoch 列+模板属性+trg_decisions_epoch 回填+UPDATE 全拒(OQ7);`v13_judgment_defaults_check`(points 键集恰 {missing,timeout,review}/动作词表恰 {include,exclude,degrade,fail});judgments 行七键只收被消费且 complete 的 decisions(final_action∈{recorded,include,exclude,degrade,fail});mode 判定 identity 基(OQ5)。
- **DP5 §1.4 DP7 行**(v13-dp5…md:110):recall_k{`{"k_base":8,"widen_ratio":0.05,"k_max":64,"timeout_ms":800}`}(OQ5,:77)与一页账(§4 末表,:1256)是经济件输入;**F5①(解析相 per-session/每日判断花费闸)与 F5③(哪些 tier 允许快路超 1 批)由 DP7 立法**——DP5 只立 k 硬上限与延迟账,不越权;k_max 放宽=新版本行+重开一页账;判断成本核算读 judgment_calls;召回零判断调用(费用账自 DP6 per-chunk 起)。
- **DP6 §1.4 DP7 行**(v13-dp6…md:103):①judgment_calls 现含存在性批/per-chunk 批(逐 ask 一行,payload 体积在档),花费闸消费 calls 计数(含 filter 族);②chunk_filter 策略行与 judgment_defaults points 是经济件输入,翻版=新行,chunk_filter 版本不入 token——DP7 的 sections/tier 若消费 action 排序,按 DP3 追动键缝并入;③chunk sections 输入面已就绪,**manifest_version 2+校验器多段化是 DP7 的范围(DP6 OQ7 裁决移交)**,sections 落地那天 span_assembly 版本入 token;④memory reader 消费缝(v13_transcript_recall/freshness 签名冻结;记忆段进 manifest 时按 degraded 契约落审计事件);⑤judgment_defaults 摘要验收点由 DP7 填;k_max 放宽=DP7 重开一页账;⑥一页账(DP6 §4 末表,:1836,**存在性+1 形态:k=0→1 ask;k=8/32→3 asks;k=64→4 asks;全命中恒零;闸关=2 asks;mock 单价 9 问 $0.000042;1.3–1.6s/批**)是经济件输入基线。
- **DP6 OQ7**(:94):chunk sections 不做,缝发布 DP7+;多 chunk 段需 manifest_version 2+校验器重做+全序键设计。**DP6 OQ5**:memory degraded 消费契约已发布(消费侧落审计事件并降级)。**DP6 不变量 2**:signal 命名空间保留——`corpus_exists` 与 `chunk::` 前缀为过滤族保留名,未来模板族不得启用同名。
- **DP6 工程纪律**(:153):OR REPLACE 大体(envelope/resolve/assemble)从上游 stage 文件**加载态原文机械复制**(比计划文本更权威),仅按标注增量编辑;新 RAISE 统一 V3006(DP1–5=V3001–V3005 顺延)→**本 plan=V3007**;stage setup_db DROP-CREATE 自己的库并 `files_through(<stage>)` 前缀加载——上游 gate 在各自前缀库复跑,后位换体结构性不影响。

### 设计稿要点(冻结原文语义,docs/designs/v13-context-on-pg.md)

§5.4/§5.5/§6.2 触点 1+2/§6.4 八步/§6.7/§9/§10/§12/§13/§14 的 normative 内容逐条进 §2 输入映射表,此处不重复;三处易错 emphasis:**(a)** tier 阶梯=「thresholds 路由带:context_pressure BETWEEN lo AND hi → tier(Normal/TrimSchemas/CompactHistory/AggressivePrune)」;**(b)** 轮 2 P0 修正原文「只升不降仅在单次 Plan 内成立(同一 Plan 取 max(raw,predicted,recovery floor));跨 turn 永久单调会让一次高压永久锁死 AggressivePrune——跨 turn 用 hysteresis/cooldown 受控降级;0.60/0.75/0.90 只作 shadow seed,本地校准后才动作」;**(c)** r 三纪律——带生效区间定价目录/manifest 记 r 来源版本/OpenRouter 路由不确定时不得用猜测 r 决定压缩(只按硬窗口与安全策略行动),r<r*≈0.145 压缩亏钱写进默认策略注释,E(r) 只是输入成本代理(未覆盖摘要调用、输出与延迟;r 错误翻转的是账单选择,不影响正确性)。

### stepfun 评审(reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md)

- **F5(P0,:50)**:①解析相加 per-session/每日判断花费闸(策略行),超闸只走缓存、缺口转慢路——DP7 立法;②(k,tier)→往返→延迟一页账+首版 k 硬上限——DP5 已落;③明文哪些 tier 允许快路超 1 批——DP7 立法。判断付款发生在解析事务、先于变更事务预算扣减;弃批重解析=判断花费净损失;用户连发消息可零 turn 落地持续刷判断花费。
- **F9(P1,:77)**:latch「进核心(P1)」与交付排序第 5 步矛盾——**归 DP8 呈报,非本 plan 范围**(本 plan 仅在附 A #8 记转呈)。

---

## 1. 定位与边界

### 1.1 本 DP 在 v13 版图中的位置

DP7 是设计 §11 交付排序第 4 条「五件套经济学件(tier 带/分位/E(r))与**摘要验收链(触点 2)**」的整块落地,也是「§5 五件套」的最后一块:目录(DP3)/清单(DP3)/渲染(策略行本 plan 落,render 本体归 DP8)/经济(本 plan)/反馈(本 plan 统计半边)。上游十一 stage(schaa/resolve/loop/twophase/envelope/manifest/chunks/recall/characterize/filter/memory)全部为前缀基座,本 plan 交付两个新 stage:

- **`v13/economy/`(第 12 位)**——**决策与记账平面**,纯 SQL 零外部 IO:策略行族(context_tiers/context_budget/judge_spend_gate/fastpath_tiers/render_policy)+定价目录 v13_pricing+派生函数(R_o 分位/压力/tier/锁序内经济快照)+解析相花费闸(parse 换体)+manifest_version 2 的 economics 半边(装配/校验器/token 三件 OR REPLACE 增量:11 外层键/7 键 policy 块/8 键 token/三桶装箱/cache-break 归因)。
- **`v13/summary/`(第 13 位)**——**执行与消费平面**:effects.kind 扩 `context_summary`+effect_attempt_cap v2(全六键)+摘要验收模板(summary_fidelity,noul,epoch='pre-finalize')+judgment_defaults.points 填 summary_accept(fail-closed)+schedule/prepare/consume 三件函数+装配/校验器第二跳(kind=summary+回退链动作层,actions_enabled 门控)。

两 stage 切分依据见 OQ1(正交性/gate 剖面/一里程碑一提交/brief 明文授权裁量)。**economy 先、summary 后**:summary 的装配消费增量构建在 economy 的 manifest v2 之上(文件 13 OR REPLACE 文件 12 产出的函数体——机械复制+增量,DP6 对 DP3 的同款纪律)。

**硬边界**:零改动 v12 既有文件;对既有 v13 对象的变更只限 §3 标注的授权清单(七处 OR REPLACE 换体(五函数:12 号五件+13 号 assemble/validate 再跳,P2-1 计数对齐)/一处 ADD CONSTRAINT 换约束/v13_policies 与 judgment 模板与 defaults 的版本行追加);`v13_advance`/`v13_complete`/`v13_enqueue_effect`/resolve 族语义/envelope 键集零改动;设计稿/教程正文/上游 plan 零改动。

### 1.2 上游契约消费清单(逐条,来源:DP1 §1.3 / DP2 §1.4 / DP3 §1.4 / DP5 §1.4 / DP6 §1.4 对 DP7 行 + 机制面勘探)

| # | 契约(来源) | 本 plan 落点 |
|---|---|---|
| 1 | `v13_policies` 载体共享:追加版本行+at-most-one active+读侧单源 `v13_policy()`(DP1 §1.3 DP7 行) | §3.1 五行新种(context_tiers/context_budget/judge_spend_gate/fastpath_tiers/render_policy,INSERT 即 active)+§3.2 effect_attempt_cap v2(全六键翻版)与 judgment_defaults 追点翻版——全部经既有载体与翻版仪式,零新策略机制 |
| 2 | 判断成本核算读 judgment_calls,不得从 decisions 派生(DP2 §1.4) | §3.1 `v13_judge_spend`(花费闸计数源:session/day asks,含 filter 族与摘要验收 ask)+§4 G 组断言口径 |
| 3 | 信封 budget/timeout 冻结随 effect 携带且哈希豁免(DP2 §3.5) | 摘要验收信封沿用同纪律(§3.2 v13_summary_envelope 冻结 budget/timeout 两键;judge effect 身份不受策略翻新影响——本 plan 零新增豁免路径) |
| 4 | est_tokens 公式版本随 assemble_manifest 策略行;换公式=新版本行(DP3 §1.4) | 本 plan **零改 est 公式**(机械复制 DP3 装配体的 est CTE);summary 段 est 用同一公式(附 A #9) |
| 5 | tier/E(r)/R_o 消费 sections[].est_tokens 与 judgment_calls.usage(DP3 §1.4) | §3.1 压力 T_used=装箱候选 Σest_tokens;R_o 读 effects.result 的 usage+**model**(§5.5「usage 已在 events/effects」的 effect 半边;model 谓词读 result 侧——生产 llm effect request 恒 {route}(DP1:2484–2486)零 model 键,读 request 侧=生产面恒空桶(P0-1);worker 契约=result 携 usage+model,缺失样本=冷启动路径,OQ3/附 A #3) |
| 6 | post-execute epoch 生产者归触点 4(P2 弱标签纪律 §6.3 全文)(DP3 §1.4) | 本 plan 零 post-execute 生产者(DP3 结构性零生产者维持);§7 明确不做 |
| 7 | 摘要段 kind='summary'+回退链逐步落 transform.applied/skipped(DP3 transform 结构即审计载体)(DP3 §1.4) | §3.2 装配 v3:kind='summary' 段+四新 reason+两新 name,两分支键集恰等纪律逐字继承 |
| 8 | judgment_defaults.points 填摘要验收点(fail-closed;settle 已接线校验器)(DP3 §1.4) | §3.2 defaults 追点 `summary_accept` {missing:'exclude',timeout:'exclude',review:'exclude'}(§6.4-4:review/reject/缺失/超时一律不采用);消费臂=v13_summary_verdict 的 basis 字段 |
| 9 | 真窗口=新 transform 名+新策略版本行(首版 verbatim)(DP3 §1.4) | §3.2 检查规则/受保护元素抽取规则变更=新 transform 名(summarize_v2/spill_v2)+summary_accept 新版本行,README 流程 |
| 10 | recall_k 四参数与一页账是经济件输入(DP5 §1.4①) | §3.1 花费闸种子值以 DP6 一页账为基线校准(附 G 组/README);一页账 v3 在 economy README 落地(§4 末) |
| 11 | F5①/F5③ 由本 plan 立法(DP5 §1.4①) | OQ6:judge_spend_gate 行+parse 换体前置闸;fastpath_tiers 行 v1 空集+放宽流程立法(README) |
| 12 | k_max 放宽=新版本行+重开一页账(DP5 §1.4②/DP6 §1.4⑤) | §3.1/README:本 plan 不放宽 k_max;流程文本进两 README(触发条件与责任人动作) |
| 13 | 花费闸消费 calls 计数含 filter 族(DP6 §1.4①) | `v13_judge_spend` 计数无 signal 过滤(全 calls);存在性批/per-chunk 批天然在档 |
| 14 | chunk_filter 版本不入 token;若 sections/tier 消费 action 排序,按 DP3 追动键缝并入(DP6 §1.4②) | 本 plan 的 tier 不消费 chunk_filter action 排序(回退链只按结构类/round 位置,§6.2 触点 1 硬类语义)→**零新追动键**;论证记 §1.5 不变量 8 |
| 15 | manifest_version 2+校验器多段化是本 plan 范围(DP6 §1.4③/OQ7 移交) | OQ7:manifest v2(11 外层键+economics 块+7 键 policy+8 键 token+section_id 多段化规则 kind[:8hex]);chunk sections 本体仍不做(缝保持休眠,多段化后纯数据落地) |
| 16 | sections 落地那天 span_assembly 版本入 token(DP5 契约⑤经 DP6 转发) | 本 plan 不落 chunk sections → span_assembly 键保持休眠;缝在 §1.4 发布给实施期(落地动作清单已写明:token 键集+refresh) |
| 17 | memory reader 消费缝:记忆段进 manifest 时按 degraded 契约落审计事件(DP6 §1.4④/OQ5) | 本 plan 不落记忆段(非所指派 §);消费契约引用进 §1.4 发布(实施期落记忆段时:degraded=true→审计事件+降级,economy 块记 retrieval 桶降级原因) |
| 18 | 一页账(DP6 §4 末表)是输入基线(DP6 §1.4⑥) | 一页账 v3=DP6 表+摘要 prepare 行+超闸行为行(§4 末/economy README) |
| 19 | `v13_complete` 对非 llm/tool/judge kind 零语义事件(DP1 §3.6 #20,机制面) | OQ2 拓扑的地基:context_summary 完成零 llm/message/tool/result——语义消息窗/canonical_state/transcript 策展零污染(gate P 断言) |
| 20 | single-active 任意 kind 每 session 至多一个活跃 effect(DP1:225,机制面) | OQ2:schedule 只在零活跃 effect 时 enqueue(函数内守卫);prepare 在 turn 静默期运行;新消息先到则 turn 等待(有界,一页账延迟行,README) |
| 21 | effect request 只携语义词段;水位族被剔(DP1 不变量 6,机制面) | context_summary request={purpose,span(有序 content_hash 集),span_digest,packs_reserved,policies 快照}——零水位字段 |
| 22 | effect_attempt_cap 新 kind 键缺失=enqueue 即 RAISE(DP1 #61,机制面) | §3.2 effect_attempt_cap v2 在 kind 扩展**同文件同事务**先行翻版(全六键)——加载序内零「kind 已扩而 cap 无键」窗口 |
| 23 | token 追动键缝:进 manifest 输入的策略版本必须有键;键集增删⇒全域恰一次 refresh(DP3 OQ1) | OQ7:token 追动新键 econ_ver(十键体,turn 34 修订)只罩 assembly 消费的经济学行(context_tiers/context_budget);pricing/spend gate/render_policy 不入 token(逐行论证,不变量 8) |
| 24 | assemble 两参签名;钉版本=recompute 只读(DP3 OQ5,机制面) | 装配 v2/v3 保持两参签名(NULL=活动版本);economics 块内策略版本快照使 recompute 语义自动成立 |
| 25 | settle 三层行锁+策略形状守卫+validate+complete CAS 顺序;全库锁序 sessions→tools_meta→策略活动行→effects(DP3 OQ3/§3.5) | refresh 换体:锁集扩 context_tiers/context_budget(name 序并入)+v13_pricing active 行(dim 序殿后,第四层与 effects 之间);守卫扩经济学行形状;顺序骨架逐字保留 |
| 26 | epoch=模板属性非调用方属性;post-execute 行必引用声明该 epoch 的模板(DP3 OQ7) | summary_fidelity 模板行声明 epoch='pre-finalize'(经 trg_decisions_epoch 自动落行,§6.1「候选/摘要验收等动作承重判断」的原文归类) |
| 27 | signal 命名空间:corpus_exists/chunk:: 为过滤族保留(DP6 不变量 2) | 摘要验收 signal=`summary::<span_digest>`(64hex)——新保留前缀,零碰撞;命名空间纪律注记进 README |
| 28 | 模板经版本父表 draft→内容行→freeze;策略 jsonb 种子单完整字面量+::jsonb(DP2/DP6 纪律) | §3.2 summary_fidelity 种子走模板三步仪式;§3.1/§3.2 全部策略种子单字面量+::jsonb |
| 29 | 上游 gate 前缀库复跑不受后位换体影响(结构性)(DP5 不变量 10/DP6 工程纪律) | 不变量 12;提交前全量复跑义务(AGENTS.md)照做——两新 stage 的 setup_db 用 files_through 前缀 |
| 30 | G-ctx9/F9 等 gate 复测面(DP3 F 组/stepfun F9) | F9(latch 交付位置)归 DP8 呈报(附 A #8);G-ctx9 面本 plan 零触碰(freeze/水位/canary 语义不动) |

### 1.3 Open Questions 裁决(本节为最终权威)

**OQ1 裁决:双 stage——`v13/economy/`(第 12 位)与 `v13/summary/`(第 13 位)。**
依据与 DP6 OQ1 同构:(a) **正交**——economy 是纯 SQL 派生+策略行+记账(零外部 IO、零新 effect 面);summary 是 effect 平面扩展+判断模板+生成 IO 的执行链(唯一新增外部 IO 面)——两者的失败半径与评审剖面不同;(b) **gate 剖面**——G-ctx6 三断言+花费闸在 economy,G-ctx8 摘要段+回退链在 summary;gate 断言对象严格 ≤各自文件号(gate 加载边界教训);(c) **一里程碑一提交**(AGENTS.md);(d) brief 明文授权「摘要链若分 stage 你裁决并写明」。次序:economy 先(summary 的装配消费增量构建在 economy 的 manifest v2 与 economics 块之上);第 13 位前缀加载即得全 12 号文件。

**OQ2 裁决(本 plan 核心拓扑):摘要链=跨平面三段「settle 记 intent→静默期 schedule+prepare→下一次 settle 消费」,context_summary 为新 effect kind。**

三重硬约束决定拓扑(全部上游冻结,不可绕):
- **single-active**(DP1:225):任意 kind 每 session 至多一个活跃 effect——turn 的 llm effect ready/claimed 期间不可建任何新 effect ⇒ 摘要生成不能插入 turn 关键路径;
- **settle 零外部 IO**(DP3 不变量 1):装配/落行器平面纯本地 SQL ⇒ 摘要生成(LLM)与验收(Noul)都不能在 settle 体内;
- **语义事件窗零污染**(DP1 不变量 7/DP6 OQ8):生成结果的语义事件进 canonical 窗/transcript 策展会把摘要文本回流进被摘要的历史(自反)——摘要完成不得产 llm/message 或 tool/result。

拓扑(时序):
1. **settle k(turn N)**:装配 v2/v3 计算 economics 块——pressure/tier/E(r)/buckets/compact_hint/summary_intent(target span+所需预算包);manifest 冻结即 intent 固化。零 IO。
2. **turn 静默期(llm effect 终态、零活跃 effect)**:驱动调 `v13_summary_schedule(sid)`(纯 SQL,route 登录):intent 在场+花费/调度闸过+span 仍在 active manifest sections ⇒ `v13_enqueue_effect(sid,'context_summary',request)`(request 冻结 packs 与策略快照);任一不过⇒ no-op RETURN NULL(零事件零噪声——失败事实由下一次装配的 transform trace 承载,§6.4-1「预留失败直接 drop/spill」的可观测面)。
3. **prepare worker(双连接,与 parse/advance 成对同构)**:route 连接 claim→读 span 正文(artifacts blob 按 content_hash 回取)→**外部 LLM 生成(库外)**→`v13_summary_checks`(确定性检查,零模型成本,§6.4-3 五项)——失败且无预留包⇒complete('failed');通过⇒resolve 连接调 `v13_resolve_judgments(v13_summary_envelope(...),1)`(纯判断 IO,查缓存或一次 fidelity Noul)→同连接按 (session_id,signal,context 等值 {source,summary}) 单查本轮 decision_id→`v13_summary_verdict(p_decision_id)` 得 {action,basis}(P1-6:decision_id 直取,零材料重建;同材料⇒同 request_hash⇒等值命中唯一)→route 连接 complete('succeeded',result={rounds:[{body,content_hash,checks,decision_id,verdict}],adopted})或 complete('failed')。**`v13_complete` 对非 llm/tool/judge kind 零语义事件**(DP1 #20)——污染面结构性不存在。
4. **下一次 settle(turn N+1)**:装配消费——存在 adopted 且 span_hash 全部仍在本候选集⇒land summary blob(v13_blob_land,内容寻址)+summary 段(kind='summary',transform={applied,name:'summarize'})+history 收缩为 protected tail;否则按回退链(§6.4-6 固定梯)落 transform trace。验收 decision 落地即 token.dec 追动⇒freshness miss⇒refresh 自然可达(零新触发机制)。

被拒替代两则记档:(i) 摘要生成寄生 kind='llm'——`v13_complete` llm 分支必产 llm/message 语义事件(污染)+llm 结果形状校验(#26)误伤摘要形态;(ii) settle 体内同步生成——直接违反零 IO 与「生成 IO 永远在 worker」(§2.2 已裁不变量)。

**OQ3 裁决:pressure 公式与 R_o 空桶冷启动 fail-safe。**
- 公式(**纯 int 算术,基点制,零 numeric 往返——类型算子层纪律**):`pressure_bp = ((T_used + R_o) * 10000) / L_eff`(整除下取)。T_used=本 Plan 装配候选 Σest_tokens(Never/disabled pre_skip 段不计——与装箱候选集同源);R_o=输出预留(tokens);L_eff=有效窗(tokens)。bands 用基点整数(0.60→6000/0.75→7500/0.90→9000)。
- R_o:`percentile_cont(p) WITHIN GROUP (ORDER BY (result->'usage'->>'completion_tokens')::bigint)` over effects 桶 `result->>'model' = <generation 活动 provider/model> AND kind='llm' AND status='succeeded' AND result->'usage'->>'completion_tokens' ~ '^[0-9]+$'`——**model 谓词读 result 侧(P0-1 修)**:DP1 ④ llm 分支 enqueue 的 request 恒 `{route:{action,reason}}`(DP1:2484–2486)零 model 键,读 request 侧在生产面恒 NULL=恒空桶=永久冷启动 8192;worker 契约=llm result 携 usage+model(DP1 v13_complete llm 形状校验只要求 text 非空,DP1:446–451——result 增键零上游改动;裁量呈报附 A #3)。**(model,source) 桶的 source 载体化=effects.kind**(设计未定义 source 的落点;llm 生成效应按平面分桶:'llm'=turn 生成/'context_summary'=摘要生成,附 A #3);p_steady=0.75/p_recovery=0.95(策略键)。
- **失败样本排除(§5.5 原文)**:status 谓词只有 succeeded——failed/unknown(含 prompt too long 恢复循环的失败 turn)零进样本;usage 缺失/非数值的行同样零进样本(worker 契约记「llm result 应携 usage+model;缺失=无样本,不是错样本」)。
- **空桶冷启动 fail-safe(重点)**:桶内样本数 < `min_samples`(v1=20)⇒ R_o=策略行 `cold_tokens`(v1=8192)。**方向论证:宁可过度预留,不可预留不足**——预留不足的失败模式是 prompt-too-long 硬失败,其恢复循环正是 §5.5 点名要防的分位毒化面(失败样本不进分位⇒恢复期样本恒薄⇒冷启动态自我延续);过度预留的代价只是压力读数偏高、早一档进压缩带(graceful 降级,装箱硬窗口仍由 DP3 预算执法)。同理 recovery 期(最近 `recovery_turns` v1=2 个 user turn 内存在 prompt-too-long 类失败)用 p95+floor tier(OQ4)——**窗口跨 turn 可见:turn N 失败在 turn N+1(恢复 turn,恰是最高危 turn)仍在窗内,不少预留;判定单源=`v13_recovery_active(sid)`(ro_reserve 与装配 recovery_floor 双消费,P1-3)**。冷启动值与 min_samples 均为策略键——本地校准=翻版,零代码。

**OQ4 裁决:tier 单调/hysteresis 的操作化语义与状态载体(轮 2 P0 修正的载体化;G-ctx6 原措辞被取代)。**
- **单 Plan=同 origin user turn 内的装配序列**(turn_budget max_cycles=3 ⇒ 同 turn 至多三版 manifest)。三输入取 max(**pressure 域取 max 再映 tier**,等价于 tier 域单调):
  - `raw`:本 Plan 装配候选实际压力(OQ3 公式);
  - `predicted`:上一版 manifest economics 压力经本 turn 新增语义事件 est 增量的预测值(prior_bp + Δest 同公式折算;首版无 prior⇒raw)——防止同 turn 重装配因装箱/候选差异而降级;
  `recovery_floor`:最近 recovery_turns 个 user turn 内存在 prompt-too-long 类失败(llm effect error code 族)⇒floor=CompactHistory 档+p95 R_o(否则无 floor)。**装配获知恢复布尔的通道=单源函数 `v13_recovery_active(sid)`**(P1-3:窗口=「按 seq 倒数第 recovery_turns 个 user/message 边界之后的失败」,与 OQ3 声明同口径;v13_ro_reserve 内部同源消费——零复制谓词,哈希/公式同源纪律;C2 basis='recovery_floor'/C4 断言的单源)。
  effective=max 三者;economics 块逐项记录(tier.raw/tier.effective/tier.basis∈{raw,predicted,recovery_floor,prior_held}——可观测,G-ctx6-1 断言面)。
- **跨 turn hysteresis 受控降级**:降级仅在 `raw` 连续 <目标档 band 下界已满 `cooldown_turns`(v1=2)且**每 turn 至多降一档**时允许;升档无冷却(压力即时反映)。「一次高压永久锁死 AggressivePrune」由此封死(轮 2 P0 原文的危害论证)。
- **状态载体=artifact 链派生,零新状态表**:prior manifest 经 sessions.context_active_artifact→inline→economics,链上前驱经 manifest.replay.prior_artifact_id;同 turn 归属用 turn_no 比较。确定性:零时钟零随机,同输入同结论(D4 同族断言)。
- **shadow seed(轮 2 原文)**:bands v1 值 6000/7500/9000 仅 shadow——策略键 `actions_enabled:false`:tier/economics 全量记录与断言,**回退链/摘要/TrimSchemas/AggressivePrune 动作层零激活**(生产生产行为与 DP3 装箱一致);本地校准后翻版 true 才动作。gate 用翻版 fixture 演练动作层。
- tier 载体=v13_policies 行 `context_tiers`(设计「thresholds 路由带」的载体落地——DP1 §1.3 契约明定 v13_policies 为经济件载体;thresholds 表归 route intent 带且挂 draft 父表机制,不混用。附 A #1)。band 形状:半开区间 [lo_bp,hi_bp),hi_bp=NULL=开区间上限(BETWEEN 语义的区间带同构,DP1 thresholds [lo,hi) 同形制)。

**OQ5 裁决:E(r) 与定价目录——active 标志选择+区间元数据,装配零时钟。**
- 新表 `v13_pricing(provider,model,account,cache_class,fresh_usd_per_mtok,cached_usd_per_mtok,catalog_version,effective_from,effective_to,active)`:PK=五维+catalog_version;每维度键 at-most-one active(部分唯一);append-only 触发器(镜像 v13_policies_frozen);CHECK(cached≥0 AND fresh>0)。**r=派生比值**(cached_usd_per_mtok/fresh_usd_per_mtok,单源函数 `v13_pricing_r`,零存储冗余)。
- **「带生效区间」的承载=版本行+区间元数据+翻版仪式,不用 now() 选择**(附 A #4):装配是确定性平面(零时钟,DP3 不变量 6)——now() 选行会破「同输入两调字节相等」与 exact replay/recompute 的可推演性;effective_from/to 是运维与审计元数据(规划区间),当前适用行=active 标志(与全部策略行同一翻版仪式);区间重叠的行不得同时 active(部分唯一结构性保证)。r 来源版本=消费行的 catalog_version(economics 块记录五维+version)。
- **三纪律**(§5.4 原文逐条):r 缺失(维度键无 active 行)⇒`er.branch='r_unknown'`——**不用猜测 r 决定压缩**:摘要动作仅硬窗口(pressure_bp≥10000)触发,economics 块记录决策依据;r<r*(0.145)⇒`er.branch='loss'`(压缩亏钱,ContextPipe 实测盈亏平衡点写进默认策略注释——策略行 note 键);E(r)=fresh+r·cached 只作输入成本代理(未覆盖摘要调用、输出与延迟;er 块记录 e_base/e_comp 与 branch∈{adopt,loss,r_unknown,hard_window,actions_off}——G-ctx6-4 可观测断言面)。fresh/cached 拆分估算=确定性代理:base=稳定前缀(churn=0 段)按 cached、新变段按 fresh;comp=摘要段+受 spill 影响段按 fresh、稳定尾按 cached——首轮代理口径,校准=翻版。
- **pricing 不入 token**(不变量 8 论证):r 只影响账单选择(设计原文「r 错误翻转的是账单选择,不影响正确性」),pricing 翻版不改变任何 manifest 内容身份——旧 manifest 继续新鲜是正确行为(下次自然装配用新 r);与 context_tiers/context_budget(改变 transform 选择=manifest 内容)必须追动形成对照。

**OQ6 裁决:花费闸(F5①)挂在 parse 换体的前置分支;F5③ 立法=v1 空集+流程文本。**
- **闸行**:`judge_spend_gate {session_asks_cap:512, day_asks_cap:8192, scope:'fast_path'}`。计数源=judgment_calls(session 聚合/当日聚合——judgment_calls.created_at 在档;含 filter 族与摘要验收 ask,DP6 契约①)。种子值论证:DP6 一页账最坏 4 asks/turn×turn_budget 3 cycles≈12/turn,512/8192≈40+ turn/170+ turn×12——**充裕种子=事实 shadow**(正常流量远不及闸,闸只封 F5 的「零 turn 落地刷花费」悬崖),收紧=本地校准后翻版(README 流程)。
- **执法面=parse 换体前置分支**(不动 advance/resolve/envelope):`v13_parse` OR REPLACE(机械复制 DP1 §3.4 原文+以下唯一增量):入口后置闸检查 `v13_judge_spend(sid).over`——**过闸⇒跳过 resolve 调用,信封/快照构造逐字保留,remaining 改由 v13_gap 信封缺口计数单源求值**(缓存命中在 advance ③ 缺口 join 处自然消费——已答行非缺口);缺口转 judge effect 交慢路。字面兑现 F5①「超闸只走缓存、缺口转慢路」。未过闸⇒行为与 DP1 逐字节等价(回归断言)。
- **慢路 v1 不设闸**(README 立法):慢路 ask 由 turn 推进驱动(effect claim 随 turn cycle),速率受 turn_budget 结构性限流——F5 的悬崖是快路同步付款,不是慢路异步付款;慢路闸=未来版本键(scope 扩 'slow_path',触发条件=实测慢路费用成账单大头)。
- **F5③**:`fastpath_tiers {tiers_over_one_batch:[]}`——v1 **无任何 tier 允许快路超 1 批**(DP5 一页账的延迟账面不翻)。放宽流程立法(README):翻 tiers_over_one_batch⇒须同批 resolve_fast_path v2(advance 内上限读点的协调)⇒重开一页账(F5② 表)⇒评审;缺一即不允许翻。tier 条件化不进 advance(advance 冻结)——advance 内快路上限仍读 resolve_fast_path.max_batches,fastpath_tiers 是其翻版前置条件表(README 契约)。

**OQ7 裁决:manifest_version 2+校验器多段化(DP6 OQ7 移交的兑现)。**
- 外层 11 键(DP3 10 键+`economics`);`policy` 块 7 键(+tiers_version/budget_version/pricing_version);`required_revision` 10 键(加载态基九键+`econ_ver`);`manifest_version=2`(validate 对装配产物断言 IS DISTINCT FROM 2 拒收——v1 产物只在 DP3 前缀库存在,exempt replay 不走 validate)。
- **econ_ver=sha256 over string_agg(name||':'||version, ',' ORDER BY name) of v13_policies WHERE name IN ('context_tiers','context_budget') AND active**(单源函数 v13_econ_ver;未来经济学行加入 assembly 消费集=改此函数一处+自然追动,键集形状不变——OQ1 追动键缝的扩集友好形态)。
- **section_id 多段化规则**:section_id = kind(该 kind 在本 manifest 内唯一时)| `kind || ':' || left(content_hash,8)`(同 kind 多段时,全部段一律带后缀——规则无例外分支,校验器可执法)。DP3 骨架三 kind 各一段⇒section_id=kind 不变(前缀库零漂移);未来 chunk sections(同 kind 多段)纯数据落地,无需再 bump manifest_version(DP6 OQ7「独立工作包」的缝就此结构性预留)。全序键 (prank, section_id) 不变。
- kind 词表分两跳:economy 文件 validate v2 词表仍 {goal,history,tools}(不前向引用 13 号对象);summary 文件 validate v3 +summary。transform:name +{summarize,spill}、reason +{summary_unavailable,summary_rejected,compaction_round_drop,compaction_final_trim}(均 13 号文件落,两分支键集恰等纪律逐字继承)。
- economics 块 schema(键集封闭,validate v2 执法;summary 子块在 v3 扩):`{pressure:{t_used,r_o,l_eff,bp},tier:{raw,effective,basis},er:{branch,r,r_source:{provider,model,account,cache_class,catalog_version},e_base,e_comp}|null,buckets:{core_cap,history_cap,retrieval_cap,effective_budget},compact_hint:{order:[section_id…],basis}|null}`——数值全 int/r 为 numeric(10,6)/词表封闭(branch/basis 同上)。

**OQ8 裁决:摘要验收判断面。**
- 模板 `summary_fidelity`(kind='noul',epoch='pre-finalize',经版本父表 draft→内容行→freeze;trg_decisions_epoch 自动落行)。**signal=`summary::<span_digest>`**(span_digest=有序 span content_hash 集 sha256,单源函数;新保留前缀,不撞 corpus_exists/chunk::——命名空间纪律)。
- 信封 `v13_summary_envelope(p_sid,p_span_digest,p_source,p_summary)`:**十键=DP2 resolve 实际消费键集逐键对齐(P1-5 修)**——sid/ctx/needed/templates/groups/budget/timeout_ms/candidate_set_hash/provider/model(DP2 §3.6 实读:judgment_calls.candidate_set_hash NOT NULL(锚=span_digest,与 signal 同源);budget 形状={batch_questions:1} 单问单批(resolve 入口 V3002 形状校验面——packs_reserved 是 request/schedule 面的键,不冒充 resolve 的 budget,单位歧义就此收口);templates/groups=summary_fidelity 钉 frozen 版本的物化(哈希/分组/落行消费面));ctx={source:<span 全文>,summary:<摘要全文>}=groups[].state 同源同材料(Noul 需文本对读;ctx 全文进哈希材料,同摘要重验⇒同哈希⇒缓存命中零调用,§6.4-4「查缓存或调一次」的缓存半边);needed=[单 noul 问](携 template_name——resolve 的模板消费键;criteria=accept band 语义);provider/model=v13_guc_required fail-closed 读取(DP2 同款);timeout_ms=GUC 冻结值(DP2 同款)。
- **judgment_defaults.points 填 `summary_accept` {missing:'exclude',timeout:'exclude',review:'exclude'}**(三态全 fail-closed→不采用→回退链;动作词表四值内,DP3 校验器天然过);final_action:accept band 采納='include'/reject='exclude';review/missing/timeout 不进 judgments(DP3 谓词),trace 载体=装配 transform+economics。
- **CJK 拒绝-only(§6.4-7)**:材料(span 全文)CJK 字符占比> `cjk.ratio_hi`(v1=0.30)⇒`cjk_mode='reject_only'`:accept band 信号**不单独放行**(仍不采用),仅 reject/review 信号作为附加拒绝依据生效——直到专门 CJK fixture 校准(数据动作:summary_accept 翻版改 mode,gate 断言两向)。Jev 数学弱+CJK 判断劣化是作用力 5 的原文依据。
- **预算包与重试(§6.4-1/5)**:summary_accept 行 `{packs_reserved:1(v1;gate fixture=2),gen_tokens_cap:2048,accept:{lo:0.80},review:{lo:0.50,hi:0.80},cjk:{ratio_hi:0.30,mode:'reject_only'},checks:{…参数},schedule_cap_day:8}`。「完整预算包」=一次生成调用+一次验收 Noul(含其 timeout);**预留=schedule 时点判定**(花费/调度闸+策略在场)——request 冻结 packs 形状;**重生成=新 LLM 调用非重问**(§6.4-5 原文「不能只重问相同摘要」):round 2 用新生成文本⇒新 ctx⇒新 request_hash⇒新 decision(gate M 断言)。

### 1.4 本 plan 对 DP8 与实施期发布的契约

| 消费方 | 契约 | 形态 |
|---|---|---|
| DP8(latch/render/fork) | **render_policy 行已立**(v1 canonical,§5.3 首版单一 render):DP8 落 canonical render 函数时消费本行;**render 落地日 render_policy 版本必须并入 prefix_identity 材料+token 追动键**(OQ1 追动键缝:render 改 wire 字节=身份材料;漏键=freshness miss——与 latch 同缝,DP3 §1.4 DP8 行同族);present偏好不立法(臼断不立法,§5.3) | 策略行+缝注记 |
| DP8(latch) | manifest v2 economics 块与 latch 零耦合(latch 进 prefix_identity 不进 economics);tier 不消费 latch | 语义说明 |
| 实施期(chunk sections 落地日,DP6 OQ7 缝) | section_id 多段化规则已立法(OQ7):同 kind 多段一律 kind:8hex;落地动作=①kind 词表扩(validate vN)②span_assembly 版本入 token 键集(DP5 契约⑤/DP6 契约③转发——**落地日必做,漏=语料变化不触发 refresh 的 freshness miss**)③新策略版本行 | 规则+动作清单 |
| 实施期(记忆段落地日,DP6 ④缝) | v13_transcript_freshness degraded=true 时:记忆段不得作为可靠召回面——落审计事件+降级(economics.buckets.retrieval 记降级原因);当前 turn 消息永远直读(DP6 OQ5 已结构性满足) | 消费契约引用 |
| 实施期(tier 本地校准) | 校准流程:跑语料/会话 fixture→观察 economics.pressure.bp 分布→定 bands→翻 context_tiers 新版本行(actions_enabled=true 同批)——零代码;README 载流程与责任人 | 流程文本 |
| 实施期(定价目录运维) | v13_pricing 录入/翻版仪式(INSERT 新 catalog_version→双 UPDATE 翻 active;区间元数据同行);维护流程自动化是 §14 遗留开放项(手动仪式+README) | 流程文本 |
| 实施期(k_max 放宽) | 流程=recall_k 新版本行+重开一页账(F5② 表)+fastpath_tiers 联判(DP5 契约②/DP6 契约⑤)——本 plan 不放宽,README 载流程 | 流程文本 |
| 后续(慢路花费闸) | judge_spend_gate 扩 scope:'slow_path' 键的触发条件=实测慢路费用成账单大头(台账);v1 只闸快路 | 台账项 |
| 后续(CJK 摘要校准) | 专门 CJK fixture(kohaku 类)校准后 summary_accept 翻版 cjk.mode='calibrated'——Jev 方可单独放行;校准 fixture 设计记台账 | 台账项 |

### 1.5 不变量(全 plan 有效,违反即设计背离)

1. **DP1–DP6 全部不变量原样继承**(两相分离/锁内零外部 IO/纯判断 IO 例外唯一/双登录/αβ 语义/行为参数冻结消费/token 与 manifest 同语句快照/冻结即不可变/manifest 只消费内容寻址身份/装配确定性/行自证/重摄取同事务/外部只记 hash/锁协议/退役源过滤/三禁/cgr 无漏报/单 stannum 索引/per-chunk 身份四面同源/存在性键含候选集/batch 写锁纪律/信封单语句单快照/记忆 fail-closed)。本 plan 新读写:economy 全部纯 SQL 派生(零外部 IO);summary 唯一新增外部 IO=kind='context_summary' effect 的生成调用(worker 平面,库外);验收 Noul=纯判断 IO 经 resolve 族(例外唯一纪律);**settle 体内零外部 IO 维持**(schedule 不在 settle 体内,是驱动后置纯 SQL);`v13_advance`/`v13_complete`/`v13_enqueue_effect`/resolve 族语义/envelope 键集零改动。
2. **single-active 不破**:v13_summary_schedule 内置守卫——存在活跃 effect(任意 kind)即 no-op RETURN NULL;prepare 在 turn 静默期运行;新消息先到则 turn 推进等待 prepare(有界:≤packs×(1 gen+1 Noul),一页账 v3 延迟行;取消/抢先=台账)。effect request 只携语义词段(OQ2 形态,零水位)。
3. **语义事件窗零污染**:context_summary 的 complete 走 DP1 v13_complete 对非 llm/tool/judge kind 的通用分支——零 llm/message/tool/result 语义事件(结构性);canonical_state 语义窗/transcript 策展零新行(gate P 断言);审计面=effect 行+result+judgment_calls+装配 trace。
4. **摘要链 fail-closed(§6.4 全八步)**:预算包预留失败/确定性检查失败/验收 review·reject·缺失·超时/CJK 未校准——一律不采用+回退链+applied/skipped trace;**放弃分支零「新增」Jev 调用≠绝对零成本**(已超时/失败的调用可能已计费——§6.4-8 措辞纪律,gate 断言口径=「零新增 judgment_calls 行」而非「零成本」);检查先行(失败不调 Jev);重生成非重问。
5. **tier 语义(轮 2 P0;G-ctx6 原措辞被取代)**:单 Plan 内 max(raw,predicted,recovery_floor) 单调;跨 turn hysteresis(cooldown_turns+每时至多降一档)受控降级;bands shadow seed(actions_enabled=false 时动作层零激活,纯记录);升档无冷却;状态从 artifact 链派生零新真相表。
6. **manifest v2 只经 settle 落行**(artifacts 纪律/pointer 守卫不动);economics 块=审计快照——派生自 decisions/effects/策略行/artifact 链,零第二真相源(§8 元原则 (c));v13_pricing 是运维参考目录(镜像 tools/policies frozen+翻版仪式),不是 usage 真相源(usage 在 effects/judgment_calls)。
7. **确定性**:economy 派生函数与装配 v2/v3 零时钟/零随机/零活策略读(pricing 经 active 标志非 now()——OQ5);同输入两调字节相等(D4 同族);pressure/tier/er 全 int 基点或封闭词表;predicted/recovery/hysteresis 全部从不可变 artifact 链与 effect 行派生。
8. **token/锁序**:token 十键(最新前驱基九键+econ_ver;turn 34 修订);econ_ver 只罩 assembly 消费的经济学行(context_tiers/context_budget——改变 transform 选择=manifest 内容的行);**pricing/spend gate/render_policy/fastpath_tiers 不入 token**:pricing 只影响账单选择(OQ5 论文),spend gate 是 parse 平面参数(不进 manifest),render_policy 在 DP8 消费日前零 manifest 输入,fastpath_tiers 是 resolve_fast_path 翻版前置条件表(零运行期消费);settle 锁序第四层扩集=策略活动行 name 序并入 context_tiers/context_budget,**v13_pricing active 行殿后(dim 序:provider,model,account,cache_class)**,全库序=sessions→tools_meta→策略活动行(含新)→v13_pricing active→effects;翻版操作(ops)同序取锁(README)。
9. **哈希/公式同源**:span_digest/summary content_hash/econ_ver/v13_pricing_r/v13_recovery_active 各单源函数(恢复判定=v13_ro_reserve 与装配 recovery_floor 双消费,零复制谓词——P1-3);est 公式唯一(DP3 原文机械复制,零第二实现);summary blob belt=settle 消费前对 effect.result 携带正文重算 content_hash 恒等才落行(零信 effect 自报哈希);v13_judge_spend 是花费计数唯一点;token 的 econ_ver 与 settle 锁内读同一 v13_econ_ver(单语句快照内同版)。
10. **文档顺序=加载顺序**;economy=第 12/summary=第 13 纯末尾追加;gate 断言对象 economy ≤12 号、summary ≤13 号;OR REPLACE 大体(v13_parse/v13_assemble_manifest/v13_manifest_validate/v13_context_required/v13_refresh_context)从上游 stage 文件**加载态原文机械复制**+本 plan 标注增量(移动=增+删:每处换体在文件内不得残留旧定义——DP1 42723 教训);新 RAISE 统一 `USING ERRCODE='V3007'`(DP1–6=V3001–V3006 顺延,已核无占用);复制体的既有 RAISE 与 V 码逐字保留(墓碑纪律优先)。
11. **种子纪律**:jsonb 单完整字面量+显式 ::jsonb;策略翻 active 经 INSERT inactive→双 UPDATE 翻(同事务);effect_attempt_cap v2 与 effects kind 扩展同文件同事务先行(消费清单 #22);模板经版本父表 draft→内容行→freeze;judgment_defaults 追点=读活动行值+||新点+新版本行+翻(零改校验器);ACL 全量块在文件真末尾。
12. **双登录与 ACL**:schedule/claim/complete=route 手(EXECUTE 归 v13_route);验收 resolve 调用=resolve 登录连接(prepare worker 双连接:route 主+resolve 副,与 parse/advance 成对同构);新函数逐件 REVOKE PUBLIC+最小授权;上游 gate 前缀库结构性隔离(files_through)+提交前全量复跑(AGENTS.md);一里程碑一提交,按路径 add,禁 `git add -A`。
13. **新写 SQL 自检(实施期机械执行,turn 3 教训)**:参数全用、列存在、类型算子层显式(int 基点算术零 numeric 往返/百分位 p 用 numeric 字面量/digest() 一律 encode hex/jsonb 键存在用 ?/值比较用 ->> 后 IS DISTINCT FROM/枚举判断 IN(...) IS NOT TRUE)、块末分号、纸面加载模拟(逐语句终结符/同签名唯一/前向引用零违例/块配平)——附 B 记数字。

---

## 2. 输入 § 映射

| 设计原文(冻结) | 本 plan 落点 |
|---|---|
| §5.4 tier 阶梯=thresholds 路由带:context_pressure BETWEEN lo AND hi→tier(Normal/TrimSchemas/CompactHistory/AggressivePrune) | OQ4:context_tiers 行 bands=[{lo_bp:0,hi_bp:6000,tier:'Normal'},{6000,7500,'TrimSchemas'},{7500,9000,'CompactHistory'},{9000,NULL,'AggressivePrune'}](半开区间,DP1 thresholds [lo,hi) 同形制);载体=v13_policies(附 A #1);economics.tier 双值(raw/effective)+basis |
| §5.4 压力是 fold_state 的 derived:T_used=Σest_tokens、L_eff 来自 meta、R_o=percentile_cont over 该 (model,source) 桶历史 llm effect usage,p75 稳态/p95 恢复 | OQ3:T_used=装配候选 Σest_tokens(与装箱候选集同源);R_o=v13_ro_reserve(percentile_cont+status 谓词+(model,kind) 桶——model 谓词读 result 侧,附 A #3);p75/p95 策略键;L_eff=context_budget.l_eff_tokens(「meta」的版本化载体落地,附 A #2;DP8 generation 填真后迁 single-source 缝,§1.4) |
| §5.4 轮 2 P0:只升不降仅单 Plan 内(max(raw,predicted,recovery floor));跨 turn hysteresis/cooldown;0.60/0.75/0.90 只作 shadow seed | OQ4 全节;G-ctx6 三断言重写(C 组)+取代注记 |
| §5.4 压缩前算 E(r)=fresh+r·cached;r 来自带生效区间 provider/model/account/cache-class 定价目录(manifest 记 r 来源版本) | OQ5:v13_pricing 表+active 选择+区间元数据;economics.er.r_source 五维+catalog_version;E(r) 双分支估算 e_base/e_comp |
| §5.4 OpenRouter 路由不确定时不用猜测 r 决定压缩——只按硬窗口与安全策略行动 | OQ5:er.branch='r_unknown'→摘要仅 pressure_bp≥10000 硬窗口触发;gate D3 |
| §5.4 r<r*≈0.145 压缩亏钱(ContextPipe 实测,写进默认策略注释) | context_tiers 行 note 键原文载入;er.branch='loss' 分支;gate D4 |
| §5.4 E(r) 只是输入成本代理(未覆盖摘要调用/输出/延迟;r 错误翻转账单不翻正确性) | economy README 注记+OQ5 口径;pricing 不入 token 的论证基砂(不变量 8) |
| §5.4 cache-break 归因=逐 section content_hash 对上一 turn manifest diff——一条 SQL,不是启发式 | `v13_cache_breaks(p_sid)`(单条 SQL:active manifest vs 其 prior_artifact 逐 section_id 对齐 diff+首断点后缀重计费面标记);churn(DP3)为输入;gate F 组 |
| §5.5 usage 已在 events/effects;失败 turn 只写失败记录不进分位样本(effect status 谓词) | v13_ro_reserve 的 status='succeeded' 谓词+usage 数值防御;gate B2/B3(失败样本排除/毒化防御) |
| §6.2 触点 1(P1 shadow-first):静态 priority 保留硬类(保护级/可恢复性/结构约束);另加 semantic_compact_hint 仅在同可压缩类内且压力跨 tier 时参与候选顺序;goal_hash 必须是版本化目标 artifact | economics.compact_hint 块:同可压缩类(history)内确定性序(churn DESC,est_tokens DESC,section_id——波动率排序的 SQL 载体,churn 是 DP3 备好输入);**仅当 effective tier 跨入 CompactHistory+ 时记录;v1 零排序影响**(sections 序仍 (prank,section_id));flip=未来策略版本;硬类保护:goal/tools 段永不入 hint/永不受回退梯(gate O5);goal_hash=版本化 v13_goals 行(DP3 OQ2 已落,引用零改) |
| §6.2 触点 2(P1 首版留):SQL 选目标/LLM 生成/确定性检查先行/Jev 只验语义保真,不过阈值绝不采用 | OQ2 拓扑+OQ8 验收面+§3.2 全链;G-ctx8 摘要段(I–P 组) |
| §6.4-1 SQL 先判本轮允许 summary+预留「生成+验收」完整预算包(失败直接 drop/spill,生成与 Jev 都不调) | v13_summary_schedule(intent/花费/调度闸/spans 在场→enqueue 或 no-op)+装配回退链;gate J/O1 |
| §6.4-2 生成摘要 artifact | prepare worker 外部 LLM 生成;正文暂存 effect.result,**settle 日经 v13_blob_land 落 context_section blob**(内容寻址;附 A #12:不新增 artifacts 直写面,lander 零运行角色纪律不动) |
| §6.4-3 零模型成本检查先行(非空/确实缩短/受保护 ID·路径·数字·工具配对仍在/结构合法/未超预算——失败不调 Jev) | `v13_summary_checks`(五项确定性规则,参数随 summary_accept.checks 版本化);gate K 逐项 fail→complete('failed')零 judgment_calls 断言 |
| §6.4-4 通过后查缓存或调一次 fidelity Noul(accept band 采用;review/reject/缺失/超时不采用) | v13_summary_envelope+v13_resolve_judgments(env,1)+v13_summary_verdict(带判定+defaults 点消费);OQ8;gate L |
| §6.4-5 仅当预先允许第二个完整预算包时重生成一次并重验(不能只重问相同摘要) | packs_reserved 策略键(v1=1);round 2=新生成文本→新 ctx→新 request_hash→新 decision;gate M |
| §6.4-6 仍失败按固定链:spill/clear 可恢复工具结果→drop oldest 完整可压缩 round→策略允许的最终裁剪;全部 applied/skipped trace | 装配 v3 动作层(§3.2):阶梯三级=①name:'spill'(history 内 tool/result 体→stub 引用)→②reason:'compaction_round_drop'(最老完整可压缩 round)→③reason:'compaction_final_trim';逐步 trace;触发条件=effective tier 需压缩且无可用 adopted summary;gate O |
| §6.4-7 CJK 摘要专门 fixture 校准前 Jev 不单独放行只可附加拒绝信号 | OQ8 cjk_mode='reject_only'(材料 CJK 占比>ratio_hi);gate N 两向断言 |
| §6.4-8 放弃分支零「新增」Jev 调用≠绝对零成本 | 不变量 4 措辞纪律+gate 断言口径(零新增 judgment_calls 行);README 措辞属文 |
| §6.7 不整合清单:tier/压力/预留分位=SQL 地盘;摘要生成=LLM 地盘;section 排序=缓存正确性来源;Jev 决定 tier/cache scope/marker、覆盖结构校验、在线 learned policy 均拒 | 不变量 5/7 的法源:hint/tier/er/装箱全确定性 SQL;生成只在 worker;compact_hint 不改序(v1);零 learned policy(§7) |
| §9 策略行:context_budget 三桶配比 | context_budget 行 {buckets:{core:0.35,history:0.55,retrieval:0.10},l_eff_tokens,keep_tail_turns};**三桶 v1 ACTIVE**(确定性装箱策略,无校准依赖——与 tier shadow 纪律的区分论证 OQ4);桶内 run_incl 装箱+桶间不挪用;effective_budget=min(budget_tokens, l_eff−R_o);gate E5/E6 |
| §9 tier 阈值带 / E(r) 的 r / render_policy(版本化) / 解析相花费闸 | OQ4/OQ5/OQ6;render_policy 行 v1 canonical(DP8 消费缝 §1.4) |
| §10 G-ctx6(tier 只升不降跨 turn 成立;R_o 分位数计算正确;E(r) 分支可观测) | **按轮 2 修正语义重写**(单 Plan 单调+跨 turn hysteresis;取代注记在 §4 G-ctx6 原文映射)+C/B/D 组 |
| §10 G-ctx8 摘要段(摘要验收不过→drop 回退链) | O 组全断言 |
| §13 第 10 章(装配清单 schema)/第 13 章 | §6(正文零改动;两 README 指针) |
| §12 YAGNI 台账(效用遥测/预取排序/在线 triage 等) | §7(台账为源+缝休珊清单) |
| §14 轮 2 裁决 2/5/7/8(载体化的法源) | OQ4/OQ8/OQ5 全节;首版只承诺摘要验收(+复用 intent 软门控——软门控归 DP8 触点 5,本 plan 零触碰) |
| stepfun F5①/③ | OQ6 全节 |
| stepfun F9 | 归 DP8 呈报(附 A #8);本 plan 零动作 |

---

## 3. 表/函数 DDL 与 SQL 草案

两文件均以 BEGIN/COMMIT 包裹(DP2–DP6 形制,含 ALTER/OR REPLACE,单事务原子装载);文件内顺序=加载顺序;草案级完整度(列/约束/签名/关键语句到位,实施者可直接开写);注释标注纪律出处。实施纪律:五个 OR REPLACE 大体(v13_parse/v13_context_required/v13_assemble_manifest/v13_manifest_validate/v13_refresh_context)从上游 stage 文件**加载态原文机械复制**(比计划文本更权威),仅按本节标注的增量编辑;复制体的既有 RAISE 与 V 码逐字保留(不变量 10 例外)。

### 3.1 文件一 `v13/economy/v13_economy.sql`(第 12 位;经济件决策与记账平面;零外部 IO)

```sql
BEGIN;

-- === 策略行五行(v13_policies 载体,DP1 §1.3 DP7 行;INSERT 即 active——新 name 无 active 冲突;
--     种子纪律:单完整 JSON 字面量+::jsonb) ===
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
  "note": "0.60/0.75/0.90=shadow seed(设计 §5.4 轮 2:本地校准后才动作);r<r*=0.145 时压缩亏钱(ContextPipe 实测盈亏平衡点,压缩决策须看 er.branch)"
}'::jsonb, true),
('context_budget', 1, '{
  "buckets": {"core": 0.35, "history": 0.55, "retrieval": 0.10},
  "l_eff_tokens": 128000,
  "keep_tail_turns": 2,
  "hard_window_bp": 10000,
  "note": "三桶 v1 ACTIVE(确定性装箱,无校准依赖);l_eff_tokens=mock 真值,DP8 generation 行填真后经新版本行迁 single-source(§1.4 缝)"
}'::jsonb, true),
('judge_spend_gate', 1, '{
  "session_asks_cap": 512, "day_asks_cap": 8192,
  "scope": "fast_path",
  "seed_note": "充裕种子=事实 shadow(DP6 一页账最坏 12 asks/turn,闸只封 F5①零 turn 落地刷花费悬崖);超闸只走缓存、缺口转慢路;收紧=本地校准后翻版"
}'::jsonb, true),
('fastpath_tiers', 1, '{
  "tiers_over_one_batch": [],
  "note": "F5③:v1 无任何 tier 允许快路超 1 批;放宽流程=本表翻版∧resolve_fast_path v2 同批∧重开一页账(README)——缺一即不允许翻"
}'::jsonb, true),
('render_policy', 1, '{
  "renderer": "canonical", "cache_markers": true,
  "provider_policy": "protocol_only",
  "note": "§5.3 首版单一 canonical render;呈现偏好不立法;DP8 消费——落地日版本并入 prefix_identity+token(追动键缝)"
}'::jsonb, true);

-- === 定价目录(§5.4 r 三纪律的载体;运维参考目录,非 usage 真相源——不变量 6) ===
CREATE TABLE v13_pricing (
  provider  text NOT NULL,
  model     text NOT NULL,
  account   text NOT NULL DEFAULT 'default',
  cache_class text NOT NULL DEFAULT 'default',
  fresh_usd_per_mtok  numeric(12,6) NOT NULL CHECK (fresh_usd_per_mtok > 0),
  cached_usd_per_mtok numeric(12,6) NOT NULL CHECK (cached_usd_per_mtok >= 0),
  catalog_version int NOT NULL CHECK (catalog_version >= 1),
  effective_from timestamptz,          -- 运维/审计元数据(规划区间);当前适用=active 标志(OQ5:零时钟)
  effective_to   timestamptz,
  active    boolean NOT NULL DEFAULT false,
  PRIMARY KEY (provider, model, account, cache_class, catalog_version)
);
CREATE UNIQUE INDEX ux_v13_pricing_one_active
  ON v13_pricing (provider, model, account, cache_class) WHERE active;
-- append-only(镜像 v13_policies_frozen):唯一许可 UPDATE=翻 active;版本行是审计轨迹
CREATE FUNCTION v13_pricing_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'UPDATE' OR (NEW.provider,NEW.model,NEW.account,NEW.cache_class,NEW.catalog_version,
                           NEW.fresh_usd_per_mtok,NEW.cached_usd_per_mtok,
                           NEW.effective_from,NEW.effective_to)
                        IS DISTINCT FROM
                           (OLD.provider,OLD.model,OLD.account,OLD.cache_class,OLD.catalog_version,
                            OLD.fresh_usd_per_mtok,OLD.cached_usd_per_mtok,
                            OLD.effective_from,OLD.effective_to) THEN
    RAISE EXCEPTION 'v13: v13_pricing is append-only (new catalog_version rows, not % on %)',
      TG_OP, TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_v13_pricing_frozen
  BEFORE UPDATE OR DELETE ON v13_pricing
  FOR EACH ROW EXECUTE FUNCTION v13_pricing_frozen();

-- === 定价目录种子(P1-2 补:一行 mock 值——附 B 计数 7 的缺项;A3/D1/D5 的构造基线;
--     §0「定价目录 v1 种子=mock 值」的 SQL 面) ===
-- 五维与 generation 活动 mock 行同 provider/model(DP3:445–448 'mock'/'mock-1';
-- account/cache_class=default);r=cached/fresh=0.25(>r*=0.145 的稳态可压缩 mock 档
-- ——loss/r_unknown 分支演练用翻版构造,种子不预置);fresh>0/cached≥0 由表 CHECK 执法;
-- catalog_version=1(=economics.er.r_source 记录的来源版本);effective_from/to=规划区间
-- 元数据(运维审计;当前适用行=active 标志——OQ5 零时钟);翻版=新 catalog_version 行
-- INSERT inactive→双 UPDATE 同事务翻 active(README 仪式)。
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

-- === 恢复期判定单源(P1-3;v13_ro_reserve 与装配 recovery_floor 双消费——哈希/公式同源纪律) ===
-- 窗口=OQ3/OQ4 声明:「最近 recovery_turns(context_tiers.r_o.recovery_turns)个 user turn
-- 内存在 prompt-too-long 类失败」。窗起点=按 seq 倒数第 recovery_turns 个 user/message 边界的
-- created_at(边界不足 recovery_turns 个⇒全部历史——冷启动 fail-safe 方向:宁可多预留);
-- 跨 turn 可见:turn N 失败在 turn N+1(恢复 turn,恰最高危)仍在窗内;
-- 码表=prompt_too_long/context_length(随实施期 worker 契约实测钉定;码表外失败不触发
-- floor,fail-open 到稳态);error 为 NULL⇒IN 谓词三值 NULL⇒不计(三值安全)。
CREATE FUNCTION v13_recovery_active(p_sid uuid)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM effects e
     WHERE e.session_id = p_sid AND e.kind = 'llm' AND e.status = 'failed'
       AND e.error->>'code' IN ('prompt_too_long','context_length')
       AND e.created_at >= (
         SELECT coalesce(min(b.created_at), '-infinity'::timestamptz)
           FROM (SELECT ev.created_at AS created_at
                   FROM events ev
                  WHERE ev.session_id = p_sid AND ev.type = 'user/message'
                    AND ev.seq <= v13_last_user_seq(p_sid)
                  ORDER BY ev.seq DESC
                  LIMIT (SELECT (v13_policy('context_tiers')->'r_o'->>'recovery_turns')::int)) b))
$$;

-- === R_o 输出预留分位(§5.4/§5.5;(model,source) 桶 source=effects.kind,附 A #3) ===
CREATE FUNCTION v13_ro_reserve(p_sid uuid)
RETURNS bigint LANGUAGE plpgsql STABLE AS $$
DECLARE v_pol jsonb := v13_policy('context_tiers');
        v_recovery boolean; v_pct numeric; v_n bigint; v_ro double precision; v_model text;
BEGIN
  -- 恢复期判定(单源=v13_recovery_active——本函数与装配 recovery_floor 双消费,P1-3;
  -- 窗口=最近 recovery_turns 个 user turn 边界,跨 turn 可见,B4 两向执法)
  v_recovery := v13_recovery_active(p_sid);
  v_pct := CASE WHEN v_recovery THEN (v_pol->'r_o'->>'p_recovery')::numeric
                ELSE (v_pol->'r_o'->>'p_steady')::numeric END;
  -- 模型单源:generation 活动行(与 prefix_identity 材料同源,DP3 OQ4)
  SELECT value->>'model' INTO v_model FROM v13_policies
   WHERE name = 'generation' AND active;
  -- 桶=该 model 全局 succeeded 历史样本(分位是跨会话统计,§5.4「该 (model,source) 桶
  -- 历史 llm effect usage」原文;source=effects.kind——附 A #3);**不按 session 过滤**;
  -- p_sid 仅用于恢复期判定(参数全用)。
  -- model 谓词读 **result 侧**(P0-1 修):DP1 ④ llm 分支 enqueue 的 request 恒
  -- {route:{action,reason}}(DP1:2484–2486)零 model 键——request 侧谓词在生产面恒
  -- NULL=恒空桶=永久冷启动;result->>'model' 为 NULL 的行被谓词排除(缺失=无样本)。
  SELECT count(*),
         percentile_cont(v_pct) WITHIN GROUP
           (ORDER BY ((result->'usage'->>'completion_tokens')::bigint))
    INTO v_n, v_ro
    FROM effects
   WHERE kind = 'llm' AND status = 'succeeded'
     AND result->>'model' = v_model   -- P0-1:谓词读 result 侧(生产 request={route} 零 model 键)
     AND result->'usage'->>'completion_tokens' ~ '^[0-9]+$';
  -- §5.5 失败样本排除由 status='succeeded' 谓词结构性保证(failed/unknown 零进样本;
  -- usage/model 缺失/非数值行同样零进样本——worker 契约记「llm result 应携 usage+model;缺失=无样本,不是错样本」;B5 经真实 enqueue/complete 路径执法)
  IF v_n < (v_pol->'r_o'->>'min_samples')::int THEN
    RETURN (v_pol->'r_o'->>'cold_tokens')::bigint;   -- 空桶冷启动 fail-safe(OQ3:宁可过度预留)
  END IF;
  RETURN coalesce(v_ro::bigint, (v_pol->'r_o'->>'cold_tokens')::bigint);
END $$;

-- === 花费计数(F5①;judgment_calls 单源,含 filter 族/摘要验收 ask——DP2/DP6 契约) ===
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
-- 注:本函数读 now()——它属 parse/驱动平面(非装配平面),零时钟纪律不适用(不变量 7 只罩装配与 economy 派生)。

-- === econ_ver 单源(token 追动键材料;OQ7) ===
CREATE FUNCTION v13_econ_ver() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT encode(digest(
    (SELECT string_agg(name || ':' || version::text, ',' ORDER BY name)
       FROM v13_policies
      WHERE name IN ('context_tiers','context_budget') AND active)
  , 'sha256'), 'hex');
$$;

-- === cache-break 归因(§5.4:一条 SQL,不是启发式) ===
-- 输入:当前 active manifest vs 其链上前驱(manifest.replay.prior_artifact_id);
-- 输出:逐 section content_hash diff+首断点后缀(断点后全部段重计费面)
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
  ),
  sec AS (
    SELECT s->>'section_id' AS section_id, s->>'content_hash' AS ch,
           (x.prio) AS prank
      FROM cur, jsonb_array_elements(cur.m->'sections') AS s,
           LATERAL (SELECT CASE s->>'priority' WHEN 'First' THEN 1 WHEN 'Normal' THEN 2
                        WHEN 'Never' THEN 3 WHEN 'LastResort' THEN 4 END AS prio) x
  ),
  pri_sec AS (
    SELECT p->>'section_id' AS section_id, p->>'content_hash' AS ch
      FROM pri, jsonb_array_elements(pri.m->'sections') AS p
  ),
  d AS (
    SELECT sec.section_id, COALESCE(pri_sec.ch, '') AS prior_hash, sec.ch AS cur_hash,
           sec.prank,
           (pri_sec.ch IS DISTINCT FROM sec.ch) AS broke  -- 无前版段=新段(hash '')⇒broke=true(新增即断)
      FROM sec LEFT JOIN pri_sec USING (section_id)
  ),
  ranked AS (
    SELECT d.*, row_number() OVER (ORDER BY prank, section_id) AS rn FROM d
  ),
  first_break AS (
    SELECT min(rn) AS rn FROM ranked WHERE broke
  )
  SELECT r.section_id, NULLIF(r.prior_hash,''), r.cur_hash, r.broke,
         (r.rn > COALESCE(first_break.rn, 2147483647)) AS rebill_suffix
    FROM ranked r CROSS JOIN first_break
   ORDER BY r.prank, r.section_id;
$$;

-- === 换体一:v13_context_required +econ_ver(OQ1 追动键缝扩集) ===
-- 复制源=SQL_LOAD_ORDER 最新前驱加载态(文件 8,DP5 九键体:DP3 七键+DP4 corpus+DP5 recall_ver;经 9/10/11 号零改动——非 DP3 §3.2 原文,turn 33 终检 P1 修正);唯一增量=顶层 jsonb_build_object 追加一键:
--   'econ_ver', v13_econ_ver()
-- 既有九键表达式逐字不动;单条 SELECT 语句/单快照纪律不变;键集 9→10⇒全域恰一次 refresh(OQ1 语义,预期内);DP8 已在其 14 号恢复十一键全谱——本文件实施时以 SQL_LOAD_ORDER 最新前驱为准。

-- === 换体二:v13_parse 前置花费闸(OQ6;唯一增量=入口后置一分支) ===
-- 机械复制 DP1 §3.4 加载态原文;增量(仅此一段,其余逐字不动):
--   IF (v13_judge_spend(p_sid)->>'over')::boolean THEN
--     -- F5①:超闸只走缓存、缺口转慢路——跳过 resolve 调用(零新增 ask);
--     -- 信封/快照构造保留;remaining 改由缺口计数单源求值(与 resolve 内部同一
--     -- LEFT JOIN 形态:needed × (answer 非空且 status∈answered/cached 的非缺口谓词,DP1 §3.2 v13_gap 同源);
--     -- 返回结构与未过闸一致——advance ③ 看到 remaining>0 即建 judge effect 交慢路(原路径,零改动)
--     v_remaining := <缺口计数(单源 SQL,注释标 v13_gap 同源)>;
--   ELSE
--     <原 resolve 调用段逐字保留>
--   END IF;
-- 未过闸路径与 DP1 行为逐字节等价(gate G1 回归断言)。

-- === 换体三:v13_assemble_manifest v2(economy 半边;两参签名不动) ===
-- 复制加载态最新前驱(文件 10,DP6 形态——含 DP5 L7 candidates 换源/goal echo 退役/decision_id 键与 DP6 墓碑四 decision_id 填充、judgments final_action 真值·消费集∪存在性行、rc2·fc 单源过滤 trace 增量;DP3 §3.4 原文非复制源,turn 33 终检 P1 修正——DP5/DP6 增量存续由此获文本保障)+以下增量(注释处逐条锚定):
-- (a) 策略读扩:active context_tiers/context_budget 行(单读,与 asm 行同锁内——refresh 侧保证);
--     pricing=generation 五维查 v13_pricing_r(缺行⇒ r IS NULL)。
-- (b) est CTE 零改(DP3 原文;消费清单 #4)。
-- (c) 装箱改三桶(Never/disabled 先标 skip 不进装箱的骨架逐字保留):
--     effective_budget = least(budget_tokens, l_eff_tokens - v13_ro_reserve(p_sid));
--     (恢复期 p95/稳态 p75 由 v13_ro_reserve 内部从 p_sid 判定——单源,零调用方分支)
--     段归类:core={goal,tools}/history={history}/retrieval={其余未来 kind 的默认类};
--     桶 cap=floor(effective_budget*ratio);逐桶全序 (prank,section_id) run_incl 超桶 cap 即
--     skip(reason='budget');Σapplied≤effective_budget(ch10 第五断言保持,gate E6)。
-- (d) economics 块计算(OQ3/OQ4/OQ5 公式全量落内;economics 块 schema 见 OQ7):
--     pressure/tier(raw+effective+basis)/er(branch+r_source+e_base/e_comp)/buckets/compact_hint;
--     recovery_floor 的恢复布尔=同点调 v13_recovery_active(p_sid)(与 v13_ro_reserve 同一
--     单源,零复制谓词——P1-3;effective=max(raw,predicted,recovery_floor) 在此落,C2/C4 断言面);
--     compact_hint 仅 effective tier∈{CompactHistory,AggressivePrune} 时非 null(OQ 触点 1)。
-- (e) policy 块 4→7 键(+tiers_version/budget_version/pricing_version——pricing_version=
--     消费行 catalog_version 集合的 string_agg,无消费行='none')。
-- (f) required_revision 零编辑——tok CTE 单源调 v13_context_required,换体一落地后自动 9→10 键(含 econ_ver)。
-- (g) manifest_version 1→2;其余九外层键表达式零改;sections/query_side/judgments/
--     replay 块零改(本文件不产 summary 段/新 transform——13 号文件的事)。
-- (h) 装配确定性注记:零时钟(pricing 经 active 标志)/零随机/零活策略读(锁内同版)。

-- === 换体四:v13_manifest_validate v2(economy 半边) ===
-- 机械复制 DP3 §3.3 原文+增量:
-- (a) manifest_version 断言 =2(IS DISTINCT FROM 2 拒收);
-- (b) 顶层键集 10→11(+economics;string_agg 字典序串='economics,judgments,manifest_version,
--     policy,prefix_identity,query_side,replay,required_revision,sections,session_id,turn_no'
--     ——实施时逐串复核,DP3 P0-3 教训);
-- (c) policy 块 4→7 键;required_revision 10 键恰等(加载态基九键+econ_ver,64hex);
-- (d) economics 块七层封闭的新层:键集恰等(pressure 4 键全 int≥0/tier 3 键词表封闭/
--     er 6 键 r IS NULL 或 numeric(0,1] 或 ≥0……分支词表封闭/buckets 4 键 int≥0/
--     compact_hint null 或 2 键);全部 int 检查用 jsonb_typeof+::int 双卫(焙劣输入拒收);
-- (e) transform/candidate/judgments 层零改(name/reason 词表本文件不扩)。

-- === 换体五:v13_refresh_context(锁集与守卫扩集;顺序骨架逐字保留) ===
-- 机械复制 DP3 §3.5 原文+增量:
-- (a) 三层行锁第四层集扩:策略活动行 name IN 集合扩为五名
--     ('assemble_manifest','generation','judgment_defaults','context_tiers','context_budget')
--     ORDER BY name FOR UPDATE(全库锁序不变量 8);其后新增:
--     PERFORM 1 FROM v13_pricing WHERE active ORDER BY provider,model,account,cache_class FOR UPDATE;
-- (b) 策略形状守卫扩(装配前 RAISE V3007):context_tiers 形状(bands 非空四档名恰等/区间
--     连续且递增/hysteresis 两键/r_o 五键数值域)/context_budget 形状(buckets 三键和≤1.0 且
--     各>0/l_eff_tokens>0/keep_tail_turns≥1);judge_spend_gate/fastpath_tiers/render_policy 不在
--     锁内守卫面(非装配输入——但形状检查同点做,fail-loud,注释标注「守卫面=装配输入+配置错误前置」)。
-- (c) validate 调用零改(换体四自动生效);complete/blob/lander/指针段零改。

-- === ACL 全量块(文件真末尾) ===
REVOKE EXECUTE ON FUNCTION
  v13_pricing_r(text,text,text,text),
  v13_ro_reserve(uuid),
  v13_recovery_active(uuid),
  v13_judge_spend(uuid),
  v13_econ_ver(),
  v13_cache_breaks(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
  v13_pricing_r(text,text,text,text), v13_econ_ver()
TO v13_recall, v13_resolve, v13_route;   -- 读面三角色(审计/装配同源读)
GRANT EXECUTE ON FUNCTION v13_ro_reserve(uuid),
  v13_recovery_active(uuid),
  v13_judge_spend(uuid), v13_cache_breaks(uuid)
TO v13_route, v13_resolve;               -- parse 闸/驱动面+装配 recovery_floor 面(单源双消费)               -- parse 闸(resolve 面)与驱动(route 面)消费
GRANT SELECT ON v13_pricing TO v13_recall, v13_resolve, v13_route;
GRANT SELECT ON v13_policies TO v13_recall, v13_resolve, v13_route;  -- DP1 已授,存在性断言(gate A5)
-- OR REPLACE 五件 ACL 保留断言(has_function_privilege 与 DP1/DP3 授权一致,gate H3)

COMMIT;
```

### 3.2 文件二 `v13/summary/v13_summary.sql`(第 13 位;摘要链执行与消费平面)

```sql
BEGIN;

-- === effect kind 扩展(先行——同文件同事务先于 cap 翻版与 enqueue 面,消费清单 #22) ===
-- DP1 内联 CHECK 未命名⇒PG 默认名 effects_kind_check(实施期以 pg_constraint 实查名为准;
-- 若名异,以实查名执行 DROP,本处为名义引用)。
ALTER TABLE effects DROP CONSTRAINT effects_kind_check;
ALTER TABLE effects ADD CONSTRAINT effects_kind_check CHECK (kind IN
  ('judge','tool','llm','context_refresh','human','context_summary'));
-- 词表追加是 append-only 语义(既有五值零动;v13_complete 对 context_summary 走通用
-- CAS 分支零语义事件——DP1 #20 机制面,gate P 断言)。

-- === effect_attempt_cap v2(全六键;翻版仪式:INSERT inactive→双 UPDATE 同事务翻) ===
-- 值=v1 原值逐键保留(P1-1 修:DP1:853–854 v1 原文 {"judge":4,"tool":3,"llm":3,"human":2,
-- "context_refresh":3} 逐字——首写稿误写 judge:3/human:5 属「声称保留实改两键+顺带放宽
-- human 重试上限」的行为变更走私,已回正;v2 只加 summary 键)+新键 context_summary(2=两轮封顶对齐 packs 上限);
-- README 翻新纪律:新版本必含全六键;降 cap 需清场(DP1 M1-9 同族)。
INSERT INTO v13_policies (name, version, value, active) VALUES
('effect_attempt_cap', 2, '{"judge":4,"tool":3,"llm":3,"human":2,"context_refresh":3,"context_summary":2}'::jsonb, false);
UPDATE v13_policies SET active = false WHERE name = 'effect_attempt_cap' AND version = 1;
UPDATE v13_policies SET active = true  WHERE name = 'effect_attempt_cap' AND version = 2;

-- === summary_accept 策略行(预算包/验收带/检查参数/CJK;OQ8/OQ9) ===
INSERT INTO v13_policies (name, version, value, active) VALUES
('summary_accept', 1, '{
  "packs_reserved": 1,
  "gen_tokens_cap": 2048,
  "accept": {"lo": 0.80},
  "review": {"lo": 0.50, "hi": 0.80},
  "cjk": {"ratio_hi": 0.30, "mode": "reject_only"},
  "checks": {"max_body_bytes": 32768, "cjk_scan_sample_chars": 4096},
  "schedule_cap_day": 8,
  "note": "packs=1=无重生成(§6.4-5 预先允许才重试,gate fixture 翻 packs=2 演练);受保护元素抽取规则变更=新 transform 名+本行新版本(DP3 契约 #9)"
}'::jsonb, true);

-- === 摘要验收模板 summary_fidelity(noul;epoch='pre-finalize'——§6.1 原文归类「候选/摘要验收等动作承重判断」) ===
-- 走 DP2 版本父表三步仪式(draft→内容行→freeze);criteria=accept band 语义题面;
-- answer schema=noul 单值;projection 声明最小可见面(ctx 仅 source/summary 两键,§6.5 最小可见性)。
INSERT INTO v13_judgment_template_versions (template_name, template_version, state)
VALUES ('summary_fidelity', 1, 'draft');
INSERT INTO judgment_templates (template_name, template_version, kind, epoch, question, criteria, answer_schema_version)
VALUES ('summary_fidelity', 1, 'noul', 'pre-finalize',
        'Does the summary faithfully preserve the load-bearing content of the source span (protected IDs, paths, numbers, tool pairings, decisions)? answer yes/no',
        '{"accept": {"lo": 0.80}, "review": {"lo": 0.50, "hi": 0.80}}'::jsonb, 'noul_v1');
UPDATE v13_judgment_template_versions SET state = 'frozen'
 WHERE template_name = 'summary_fidelity' AND template_version = 1;
-- (列名/父表形状以 DP2 §3.1 加载态为准机械对齐——本块以仪式为准,列面实施期对齐;
--  projection 列(最小可见面 {source,summary} 声明)必在种子行内——信封 templates/groups
--  消费面依赖它,P1-5)

-- === judgment_defaults 追点 summary_accept(读活动行值+||新点+新版本+翻;DP3 校验器零改) ===
INSERT INTO v13_policies (name, version, value, active)
SELECT 'judgment_defaults', (SELECT max(version)+1 FROM v13_policies WHERE name='judgment_defaults'),
       jsonb_set(value, '{points,summary_accept}',
         '{"missing":"exclude","timeout":"exclude","review":"exclude"}'::jsonb), false
  FROM v13_policies WHERE name='judgment_defaults' AND active;
UPDATE v13_policies SET active=false WHERE name='judgment_defaults'
  AND version=(SELECT max(version)-1 FROM v13_policies WHERE name='judgment_defaults');
UPDATE v13_policies SET active=true  WHERE name='judgment_defaults'
  AND version=(SELECT max(version) FROM v13_policies WHERE name='judgment_defaults');
-- 注:两段 UPDATE 的版本号錨定用实查 max(本块伪码形态,实施期以变量化 SQL 落实,
-- 避免字面量漂移);翻版同事务⇒token.jdef_ver 追动⇒全域一次 refresh(预期内,OQ1)。

-- === span_digest 单源(哈希同源纪律;signal 与信封/装配共用) ===
CREATE FUNCTION v13_span_digest(p_span jsonb)  -- p_span=[content_hash…有序] 数组
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(digest(
    (SELECT string_agg(x #>> '{}', ',' ORDER BY x #>> '{}')
       FROM jsonb_array_elements(p_span) AS x)
  , 'sha256'), 'hex');
$$;

-- === 确定性检查(§6.4-3 五项;零模型成本;参数随 summary_accept.checks 版本化) ===
CREATE FUNCTION v13_summary_checks(p_body text, p_span_texts jsonb, p_cap int)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
-- 返回 {"pass":bool,"reasons":[…]}——reasons 词表封闭:
--   empty/not_shorter/protected_missing/structure/over_budget
-- 五项(全部确定性;受保护元素=从 span 正则抽取的必在集):
--   ①empty:body 空白归一后空串;
--   ②not_shorter:est(body) ≥ Σest(span) 段字节同公式折算(est 公式单源——DP3 原文
--     复制进本函数注释,除数取活动 assemble 行 est_bytes_per_token);
--   ③protected_missing:抽取集任一缺失——uuid 正则 '[0-9a-f]{8}-…{12}'、含 '/' 的路径
--     token、数值字面量、工具配对名(span 中 '"tool":"<name>"' 形态的全部 name);
--   ④structure:控制字符(U+0000–U+001F 除 \n\t)或 max_body_bytes 超限;
--   ⑤over_budget:est(body)>p_cap。
$$;
-- (函数体草案级——五项规则与词表已冻结,实现体实施期按本注释展开;返回形状进 gate K 断言)

-- === 摘要验收信封(OQ8;十键=DP2 resolve 实际消费键集逐键对齐——P1-5 修) ===
CREATE FUNCTION v13_summary_envelope(p_sid uuid, p_span_digest text,
                                     p_source text, p_summary text)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE v_provider text; v_model text; v_tmpl jsonb;
        -- summary_accept 行不在本函数读活策略:在场/形状由 schedule 守卫与 refresh 形状
        -- 守卫执法;budget/timeout=行为参数冻结值随信封携带(DP2 纪律),值域见下
BEGIN
  SELECT (v13_guc_required('typesafe.provider')), (v13_guc_required('typesafe.model'))
    INTO v_provider, v_model;  -- DP2 OQ fail-closed 读取(缓存键永不记 NULL 身份)
  SELECT to_jsonb(t.*) INTO v_tmpl FROM judgment_templates t
   WHERE template_name='summary_fidelity'
     AND template_version=(SELECT max(template_version) FROM judgment_templates
                   WHERE template_name='summary_fidelity' AND /* frozen latest 等价形态 */ true);
  RETURN jsonb_build_object(
    'sid', p_sid,
    'ctx', jsonb_build_object('source', p_source, 'summary', p_summary),
    'needed', jsonb_build_array(jsonb_build_object(
       'signal', 'summary::' || p_span_digest,
       'kind', 'noul',
       'template_name', 'summary_fidelity',   -- resolve 的模板消费键(templates 查找)
       'question', v_tmpl->>'question',
       'criteria', v_tmpl->'criteria')),
    'templates', jsonb_build_object('summary_fidelity', v_tmpl),
       -- 含 version/answer_schema_version/projection——resolve 的哈希/分组/decisions 落行
       -- 消费面(列面以 DP2 §3.1 加载态机械对齐,见模板种子块注记)
    'groups', jsonb_build_array(jsonb_build_object(
       'projection_key', v13_projection_key(v_tmpl->'projection'),
       'state', jsonb_build_object('source', p_source, 'summary', p_summary))),
       -- 与 ctx 同材料同源(投影=最小可见面恰两键⇒state=ctx)
    'candidate_set_hash', p_span_digest,
       -- judgment_calls.candidate_set_hash NOT NULL(DP2:327)——锚=span_digest,与
       -- signal 同一单源;round 间共享锚=审计回连面,轮区分靠 payload_hash/request_hash
    'budget', jsonb_build_object('batch_questions', 1),
       -- 单问单批的冻结形状(resolve 入口 (budget->>'batch_questions')::int 的 V3002
       -- 校验面);packs_reserved 是 request/schedule 面的键,不冒充 resolve 的 budget
    'timeout_ms', current_setting('typesafe.timeout_ms'),
    'provider', v_provider, 'model', v_model);
END $$;
-- 注:模板经行单源读取(钉 frozen 最新版——直调形态与 DP2 模板视图同源,实施期对齐
-- DP2 latest 视图名);信封键集=本函数专用面,**resolve 消费十键逐键对齐 DP2 §3.6 实读**
-- (sid/ctx/needed/templates/groups/budget/timeout_ms/candidate_set_hash/provider/model);
-- 首写稿「六键足够」为失实断言已删(P1-5):缺 candidate_set_hash⇒judgment_calls INSERT
-- 处 NOT NULL 违反,缺 budget.batch_questions⇒入口 V3002,缺 templates/groups⇒哈希与
-- 分组面不可执行;DP2 19 键信封的其余键(goal_hash/route_policy_*/tools_* 等)非 resolve
-- 消费面,专用面不携(最小集原则)。

-- === 验收裁决(带判定+defaults 点消费+CJK 拒绝-only;返回 {action,basis}) ===
-- 签名裁定(P1-6 修,取 L4 ② decision_id 直取——免扩参免重建):
--   ctx 材料={source,summary} 双半边,首写稿签名只携 p_body⇒request_hash 算不出、
--   context 等值 join 构造不出。改经 decision_id 直取 decisions 行(材料=存储):
--   · prepare 面(worker,resolve 连接,resolve 返回后/complete 前):按 (session_id,
--     signal='summary::'||span_digest,context 等值 {source,summary}) 单查取本轮
--     decision_id——材料在手(刚构造信封的两半);context 列=groups[].state 物化恰形
--     {source,summary},同材料⇒同 request_hash⇒(session_id,request_hash) 唯一命中;
--   · 消费/replay 面:decision_id 已冻在 effect.result→rounds[](OQ2 步 3),装配与
--     exact replay 经同一函数从 rounds[].decision_id 重推导(P5)。
--   拒替代(L4 ① 扩 source 参):签名 4 参携 span 全文,且裁决 lookup 材料取自调用方
--   输入而非存储行——弱于「材料=存储」纪律(DP6 不变量 6 同构);decision_id 路线两
--   调用面共用一函数,签名最小(参数全用:decisions 行内携 session_id/signal/context)。
CREATE FUNCTION v13_summary_verdict(p_decision_id uuid)
RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
-- decisions 行 PK 直取(signal 前缀 'summary::' 断言——非本面行⇒V3007 fail-loud):
-- 判定序(action∈{include,exclude};basis 词表封闭):
--   行在场且 answer 非空:answer 的 p∈accept 带→include/'decision_accept';
--     p∈review 带→exclude/'decision_review';低于→exclude/'decision_reject';
--   行在场 status='failed'(timeout 态)→exclude/'default_timeout';
--   行不存在(missing 态:prepare 面单查零行/毒化零行)→exclude/'default_missing';
--   **CJK 拒绝-only 后置门**(§6.4-7):材料=decisions.context->>'source'(存储半边),
--     CJK 占比>cjk.ratio_hi 且 mode='reject_only'⇒任何非 exclude 结论改写为
--     exclude/'cjk_reject_only'(accept 信号不单独放行,仅 reject/review 作为拒绝
--     信号生效——两向都 fail-closed);
--   defaults 点消费:jdef 活动行 points.summary_accept 三态动作与上表恒一致
--     (exclude)——不一致⇒V3007 fail-loud(配置错误响亮,非静默)。
$$;

-- === 调度(驱动后置;OQ2 步 2;纯 SQL 零 IO) ===
CREATE FUNCTION v13_summary_schedule(p_sid uuid)
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE v_m jsonb; v_intent jsonb; v_pol jsonb := v13_policy('summary_accept');
        v_span jsonb; v_id uuid;
BEGIN
  -- 守卫链(任一不过=no-op RETURN NULL,零事件——失败事实由下一次装配 transform trace 承载):
  -- ①single-active:EXISTS(SELECT 1 FROM effects WHERE session_id=p_sid
  --    AND status IN ('ready','claimed'))⇒NULL;
  -- ②intent:active manifest economics.summary_intent 在场(读 sessions.context_active_
  --    artifact→inline->'economics'->'summary';intent 形态=13 号装配 v3 落:{target_span:
  --    [content_hash…],span_digest,packs})⇒不在场⇒NULL;
  -- ③调度闸+花费闸(同点——预算包预留检查的执法点,P1-4 修;OQ2 步 2/OQ8 预留面):
  --    当日已调度数(同 session kind='context_summary' 且 created_at 当日)≥schedule_cap_day,
  --    或 (v13_judge_spend(p_sid)->>'over')::boolean(judge_spend 计数含验收 ask——J2 口径)
  --    ⇒NULL(超闸走 drop/spill 同路径:零 effect 零生成零 Jev——§6.4-1;J2/J3 断言面);
  -- ④spans 在场:target_span 全部 content_hash 仍在 active manifest sections
  --    (逐 hash 存在性)⇒失配⇒NULL(span 已变,等下一版 intent);
  -- ⑤request 只携语义词段:jsonb_build_object('purpose','context_summary',
  --    'span',v_span,'span_digest',…,'packs_reserved',…,'policies',
  --    {tiers_ver,budget_ver,summary_ver,est_div})——零水位(不变量 2);
  -- 通过⇒v_id:=v13_enqueue_effect(p_sid,'context_summary',request);
  --  (enqueue 内部 effect_attempt_cap 六键检查已在 cap v2 同事务前置——零「不可领」行面)
  RETURN v_id;
END $$;

-- === 装配 v3(消费增量,构建在 12 号装配 v2 之上——机械复制 v2 加载态+以下增量) ===
-- (i)   消费判定:取本 session 最新 kind='context_summary' 且 status='succeeded' 的 effect
--       行,result->'adopted'=true 且 result->>'span_digest' 的 span 全部 hash 仍在当前候选
--       history 段正文集内⇒可用;belt:result 正文重算 content_hash 恒等才消费(不变量 9)。
--       不可用形态(零 effect/failed/adopted=false/span 失配)⇒basis 词表
--       {none,no_budget,no_effect,checks_failed,rejected,cjk,span_stale}。
-- (ii)  summary_intent 计算进 economics 块(12 号 v2 的 economics 增一键 summary):
--       effective tier∈{CompactHistory,AggressivePrune} 且 actions_enabled 且 E(r)/硬窗口
--       判定「应压缩」⇒intent={target_span(protected tail 外的可压缩 history 段 hash序),
--       span_digest=v13_span_digest(target_span),packs=summary_accept.packs_reserved};
--       预算包可用性(调度闸/策略在场)也记入(intent.pack_ok)——§6.4-1 的预留面。
-- (iii) 动作层(actions_enabled=false 恒零激活——生产 v1 行为=DP3 装箱+零改;true 时):
--       有可用 adopted summary⇒summary 段(kind='summary',cache_scope='Session',priority=
--       'Normal',payload_ref={kind:'blob',content_hash}(settle 日 v13_blob_land 落),transform=
--       {applied:true,name:'summarize'},est=同公式)+history 收缩为 keep_tail_turns 尾段
--       (transform='verbatim',content_hash 变⇒churn+1);被替旧轮零 skipped 行(不是段——
--       是段内内容的替换;审计=economics.summary+前版 manifest 保全);
--       无可用 summary 且需压缩⇒回退链三级逐步(§6.4-6):
--         ①spill:history 段内 tool/result 正文→stub(引用 effect_id),transform=
--         {applied:true,name:'spill'},段 content_hash 变(churn+1,cache-break 经济学在
--         economics.er 记录);
--         ②不足⇒drop oldest 完整可压缩 round:被丢内容以独立段形态标
--         {applied:false,reason:'compaction_round_drop'}(round=user/assistant 对);
--         ③仍不足⇒最终裁剪:{applied:false,reason:'compaction_final_trim'};
--         逐步后重跑三桶装箱;goal/tools 段(硬类保护)永不受梯(gate O5);
--       compact_hint(触点 1 shadow)在 12 号 v2 已记录,本文件零排序影响维持。
-- (iv)  economics 块扩 summary 子块:{intent|null,consumed:{effect_id,decision_id,rounds}|
--       null,fallback:{steps:[…],basis}}——键集封闭;validate v3 同步扩。

-- === validate v3(机械复制 v2 原文+增量) ===
-- kind 词表 +summary;transform.name +{summarize,spill};reason +{summary_unavailable,
-- summary_rejected,compaction_round_drop,compaction_final_trim};economics.summary
-- 子块键集执法;section_id 多段化规则执法(kind 或 kind:8hex——v2 已立法,本文件词表扩后
-- 同规则零改);其余七层零改。

-- === ACL 全量块(文件真末尾) ===
REVOKE EXECUTE ON FUNCTION
  v13_span_digest(jsonb),
  v13_summary_checks(text,jsonb,int),
  v13_summary_envelope(uuid,text,text,text),
  v13_summary_verdict(uuid),
  v13_summary_schedule(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v13_span_digest(jsonb) TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION v13_summary_checks(text,jsonb,int),
  v13_summary_schedule(uuid)
TO v13_route;                              -- prepare worker(route 连接)与驱动
GRANT EXECUTE ON FUNCTION v13_summary_envelope(uuid,text,text,text),
  v13_summary_verdict(uuid)
TO v13_resolve;                            -- 验收面(resolve 登录连接)
-- typesafe_ask 的 REVOKE PUBLIC+GRANT v13_resolve 归 DP1 M2(零改);验收经 v13_resolve_
-- judgments 体内调用——resolve 登录零新增 typesafe 直调面。

COMMIT;
```

### 3.3 stage 四件与 load.py

- `v13/economy/`:SQL=§3.1 全文;`setup_db.py`(DROP-CREATE 库 `agent_v13_economy`;`files_through('economy')` 加载十二文件;超级用户连接,角色/策略/事件触发器前置同 DP2–DP6 仪式;**无 stannum 前置**——economy 零 stannum 依赖(第 12 位前缀含 9–11 号,但本 stage 断言面零 `==>`/零 stannum 限定名,gate A5 同型扫描);`test_economy.py`(§4 A–H 组);`README.md`(机制+运维纪律+一页账 v3,§4 末清单)。
- `v13/summary/`:SQL=§3.2 全文;`setup_db.py`(DROP-CREATE 库 `agent_v13_summary`;`files_through('summary')` 加载十三文件;前置同上);`test_summary.py`(§4 I–P 组);`README.md`(驱动契约+验收纪律+回退链+worker 契约,§4 末清单)。
- `v13/load.py`:SQL_LOAD_ORDER 追加 `'economy/v13_economy.sql'`(第 12)与 `'summary/v13_summary.sql'`(第 13);`STAGE_THROUGH["economy"]=12`、`STAGE_THROUGH["summary"]=13`。零改动既有行。

---

## 4. 里程碑与 gate

> **fixture 构造口径纪律(P0-1 教训,全组适用)**:effects/judgment 面 fixture 一律从**生产真实侧**构造——R_o/恢复类至少一半经真实 enqueue/complete 路径(生产 llm request 形状={route} 零 model 键;model/usage 只在 result 侧),禁止手捏 request->model 之类生产不可达键形(首写稿 B1/B2 手插行自带 model 键掩盖死谓词的复发面);手插行仅用于失败态/边界态注入,且键形须与生产 complete 产物逐键对齐。

### G-ctx6 原文映射(§10 逐条,**按轮 2 修正语义重写——原措辞被取代**)

| §10 原文 | 本 plan 断言语义 | 取代注记 |
|---|---|---|
| 「tier 只升不降跨 turn 成立」 | **被取代**。断言改为:(a) 单 Plan(同 origin user turn 装配序列)内 tier.effective=max(raw,predicted,recovery_floor) 单调不降;(b) 跨 turn 仅在 raw 连续 cooldown_turns 低于目标档下界且每时至多降一档时允许降级——升档无冷却、降档有冷却;「一次高压永久锁死 AggressivePrune」负向 fixture 不可构造(降级路径在) | **G-ctx6 原措辞与 §5.4 轮 2 P0 修正直接冲突(stepfun F8 逐字对照);轮 1 后用户裁决不修冻结稿、plan 内绕行——本表即绕行载体** |
| 「R_o 分位数计算正确」 | percentile_cont 对照手算 SQL 逐桶相等;(model,kind) 桶正确(model 谓词=result 侧——P0-1 修,生产 request 恒 {route} 零 model 键);失败样本(status≠succeeded)排除;usage/model 缺失行排除;空桶冷启动返回 cold_tokens;恢复窗=跨 turn(最近 recovery_turns 个边界,P1-3) | 原文保留,无冲突 |
| 「E(r) 分支可观测」 | economics.er.branch 词表封闭{adopt,loss,r_unknown,hard_window,actions_off}逐分支可构造可断言;r_source 五维+catalog_version 在场;r 缺失时零压缩决策(仅硬窗口) | 原文保留,无冲突 |

### G-ctx8 摘要段原文映射

| §10 原文 | 断言做法 |
|---|---|
| 「摘要验收不过→drop 回退链」 | O 组全链:预留失败零调用/检查失败零 Jev/验收不采用→回退链 transform trace 逐步/回退链三级顺序固定/goal·tools 永不受梯/放弃分支零新增 Jev 调用 | 崩溃段其余子句(解析相 kill 幂等)归 DP1 M4 已落,零重测 |

### A 组 · 策略行/定价目录/加载与形状(economy)

| # | 断言 | 对应 |
|---|---|---|
| A1 | 加载:十二文件前缀库装载退出 0;五行新策略(context_tiers/context_budget/judge_spend_gate/fastpath_tiers/render_policy)各 v1 active=true;jsonb 单字面量+::jsonb(源码扫描零 text||text 进 jsonb) | 消费清单 #1/种子纪律 |
| A2 | 翻版仪式:追加 context_tiers v2(bands 同值+actions_enabled=true)→双 UPDATE 翻 active→旧行留档不可改(v13_policies_frozen 拒 UPDATE value);测毕双回滚 | 消费清单 #1 |
| A3 | v13_pricing:种子一行(mock 值,五维=与 generation mock 行同 provider/model 'mock'/'mock-1'+default/default——§3.1 INSERT,P1-2 补);append-only 触发器拒 UPDATE 单价列/拒 DELETE;翻 active 双行仪式可过;部分唯一拒绝同维双 active;v13_pricing_r 返回 cached/fresh 数值(0≤r≤1 断言) | OQ5 |
| A4 | 策略形状守卫(settle 面):context_tiers 非法形状(bands 缺档/区间断离/r_o 缺键)翻 active→refresh 前 RAISE V3007;context_budget 非法(桶和>1.0/l_eff=0)同型;测毕还原 | OQ5/换体五 (b) |
| A5 | 源码扫描:第 12 号文件零 `==>`/零 `stannum.` 限定名(归一化口径=DP5 §4 同款);零 typesafe_ask 引用 | 承重件不依赖 stannum 同型 |
| A6 | ACL:五新函数+两新表 REVOKE PUBLIC 逐件断言(has_function_privilege);三角色授权面与 §3.1 块一致;OR REPLACE 五件 ACL 保留断言 | 不变量 11/12 |

### B 组 · R_o 分位与冷启动(§5.4/§5.5;G-ctx6 第二断言)

| # | 断言 | 对应 |
|---|---|---|
| B1 | percentile 正确性:灌 40 条 succeeded llm effect(**result 侧携 model=generation 行值**+usage.completion_tokens=1..40;request 保持生产形状 {route}——P0-1 fixture 口径)→v13_ro_reserve 对照手算 percentile_cont(0.75) 逐值相等;模型过滤:异 model 行(result.model 异值)不入桶 | OQ3 |
| B2 | 失败样本排除:同桶插入 status='failed' 行(result 侧同 model,completion=10^9)→分位不变(§5.5 谓词);usage/model 缺失行同理 | §5.5/G-ctx6-2 |
| B3 | 冷启动 fail-safe:样本数 19(<min_samples=20)→返回 cold_tokens=8192;样本 20→分位值;**方向断言**:冷启动值>灌入样本实际 p75(过度预留方向) | OQ3 重点 |
| B4 | 恢复期(跨 turn 窗口,P1-3):turn N 插入 prompt_too_long 失败 effect→**turn N+1(恢复 turn)v13_ro_reserve 仍切 p95**(窗口=最近 recovery_turns 个 user turn 边界,turn N 失败在 N+1 可见——v13_recovery_active 单源断言);连续 recovery_turns 个干净 turn 边界后→回稳态 p75(两向) | OQ4 |
| B5 | usage+model 记录面(**经真实 enqueue/complete 路径构造**——P0-1 执法面):llm effect 走生产 enqueue(request={route} 零 model 键)+complete(result 携 usage+model)→进样本;result 不携 usage/model 的不进(零错样本)——worker 契约「result 携 usage+model」的行为面 | §5.5 |

### C 组 · tier 单调与 hysteresis(G-ctx6-1;轮 2 修正语义)

| # | 断言 | 对应 |
|---|---|---|
| C1 | band 路由:压力 bp 跨四档 fixture(手造 est/budget 驱动 T_used)→tier.raw 逐档正确;半开区间边界(bp=6000 属 TrimSchemas 非 Normal) | §5.4 |
| C2 | 单 Plan 单调:同 turn 多版装配(cycle>1)fixture——后版 raw 压力低(装箱后)但 predicted 持高⇒effective 不降;tier.basis 记录起效输入{raw,predicted,recovery_floor,prior_held}逐项可构造 | 轮 2 P0 |
| C3 | 跨 turn hysteresis:高压一档后连续 cooldown_turns+1 版 raw 低⇒降一档且仅一档;cooldown 内零降级;升档即时 | 轮 2 P0 |
| C4 | 恢复 floor(跨 turn,P1-3):prompt_too_long 后**下一 turn**的装配 effective≥CompactHistory 档(即使该 turn raw 低——恢复布尔=v13_recovery_active 单源,窗口覆盖恢复 turn);recovery_turns 干净轮后 floor 消退且可正常降级 | OQ4 |
| C5 | shadow seed:actions_enabled=false 时装配产物 transform 零 spill/round_drop/final_trim/summarize(与 DP3 C1 基线字节对齐的 sections——动作层零激活);economics 全量在场 | 轮 2 P0/shadow |
| C6 | compact_hint(触点 1):effective tier 跨入 CompactHistory(fixture 翻 actions)⇒hint.order 非空且为同可压缩类(history)确定性序(churn DESC,est DESC,section_id);Normal 档⇒hint=null;**sections 实际序不变**(shadow——与未开 actions 的序逐字节相等) | §6.2 触点 1 |

### D 组 · E(r) 与 r 三纪律(G-ctx6-3)

| # | 断言 | 对应 |
|---|---|---|
| D1 | r 在场:v13_pricing 种子行匹配 generation 五维⇒er.r=r 值、r_source 五维+catalog_version 在 manifest;branch=adopt(e_comp<e_base fixture)或 loss(可构造价差) | §5.4/OQ5 |
| D2 | r 缺失:删除 pricing active 行⇒er.r IS NULL、branch='r_unknown'、**零压缩决策**(summary_intent 仅硬窗口 bp≥10000 可构造) | §5.4 原文 |
| D3 | r<r*(0.145):定价行 r=0.10⇒branch='loss';策略行 note 载入盈亏平衡注记(README 同文) | §5.4/ContextPipe |
| D4 | 分支词表封闭:五分支{adopt,loss,r_unknown,hard_window,actions_off}逐分支可构造且互斥;economics 块零未知键 | G-ctx6-3 |
| D5 | 定价翻版不追动:pricing 翻 active(r 变)→**token 不变、② 仍新鲜**(不入 token 的行为面——与 context_tiers 翻版追动对照) | OQ5/不变量 8 |

### E 组 · manifest v2 形状与三桶(§5.2 延展/OQ7)

| # | 断言 | 对应 |
|---|---|---|
| E1 | 外层 11 键恰等(+economics);manifest_version=2;policy 块 7 键(+tiers/budget/pricing_version);required_revision 10 键(+econ_ver,64hex);零时间戳键 | OQ7 |
| E2 | economics 块五子块键集恰等(pressure 4 键全 int≥0/tier 3 键/er 6 键/buckets 4 键/compact_hint null 或 2 键);字典序键串逐串复核在档(DP3 P0-3 同型) | OQ7/换体四 |
| E3 | validate v2 正向/负向:合法产物过;economics 多一键/少一键/int 位字符串/er.branch 词表外/tier.basis 词表外→V3007(挂 USING ERRCODE 断言);manifest_version=1 产物拒收(v2 域) | OQ7 |
| E4 | token 追动键 econ_ver(第十键)=sha256(两行 name:version 串)对照手算相等;context_tiers 翻 v2 翻 active→② 不新鲜→refresh 恰一次(功能面,DP6 F6 同型);context_budget 同 | OQ1 缝/OQ7 |
| E5 | 三桶装箱:fixture 使 history 超桶 cap 而 total 未超⇒history 尾段 skip(reason='budget')而 core 段在场;桶间不挪用(core 剩余不补 history);Never/disabled 先 skip 骨架零回归(DP3 C3/C4 复测) | §9 三桶 |
| E6 | 硬窗与预算:effective_budget=min(budget_tokens,l_eff−R_o) 断言(R_o 用 fixture 灌样控制);Σapplied est≤effective_budget(ch10 第五断言保持);自身超限必 skip/首段可 skip 零回归(DP3 C2 复测) | OQ3/装箱 |
| E7 | section_id 多段化:手工构造同 kind 两段(kind:8hex 形)过 validate v2;裸同名双段拒;单 kind 单段时 section_id=kind(DP3 骨架零漂移) | OQ7/DP6 OQ7 移交 |

### F 组 · cache-break 归因(§5.4)

| # | 断言 | 对应 |
|---|---|---|
| F1 | 基线:两次 refresh 同状态→v13_cache_breaks 全段 broke=false、rebill_suffix 全 false | §5.4 |
| F2 | 单段变更:两版间 append llm/message→history 段 broke=true 且仅 history;goal/tools broke=false;rebill_suffix:序在 history 后的同桶段 true、前 false(首断点后缀重计费面) | §5.4 |
| F3 | 与 churn 对照:同 fixture 下 manifest 段 churn 与归因 broke 逐段一致(单源输入互证——churn(DP3)是输入,归因是消费) | §5.4/DP3 OQ4 |
| F4 | 新段:手工构造前版无该 section_id 的段(多段化形态)→broke=true(新增即断) | OQ7 联动 |

### G 组 · 解析相花费闸(F5①;OQ6)

| # | 断言 | 对应 |
|---|---|---|
| G1 | 未过闸零扰动:闸远未及(fixture 少量 calls)→parse→advance 全链行为与 DP1 M4 基线等价(mock 计数/事件数/effect 形态逐项相等——回归面) | OQ6 |
| G2 | 超闸转慢路:灌 judgment_calls 至 session_asks_cap→新 turn parse→**零新增 judgment_calls 行**(resolve 未调)、缓存命中行照常消费(预置已答 decision 的 signal 零重问)、缺口以 judge effect 交慢路(advance ③ 原路径) | F5① 原文 |
| G3 | 日闸:跨日边界 fixture(created_at 控制)→日计数重置、session 计数持续 | F5① |
| G4 | 计数口径:v13_judge_spend 计数含 filter 族 ask(DP6 面预置)+摘要验收 ask(13 号库联测断言在 P 组,此处留接口注释) | 消费清单 #13 |
| G5 | 慢路不闸:超闸状态下慢路 worker resolve 照常 ask(F5① 只闸快路——断言慢路可推进 turn) | OQ6 立法 |

### H 组 · 锁序/回归/加载边界(economy 收口)

| # | 断言 | 对应 |
|---|---|---|
| H1 | settle∥翻版:连接 A refresh 期间连接 B 翻 context_tiers v2→B 阻塞于策略行锁至 A 提交,A 的 manifest 记旧版(DP3 F6(iii) 同型扩面);settle∥settle 零 40P01(DP3 F6(i) 复测) | 换体五 (a) |
| H2 | settle∥pricing 翻版:同型(A 阻塞 B 至提交;A 的 r_source=旧 catalog_version) | OQ5/不变量 8 |
| H3 | OR REPLACE 五件 ACL 保留+签名未变(pg_get_function_identity_arguments 对照 DP1/DP3 记录);上游 gate 抽样复测(DP1 M4-K 系列/DP3 B1/C2/D4/F1 各一)在本前缀库绿 | 不变量 10/12 |
| H4 | 加载边界:economy gate 断言对象≤12 号文件(grep 断言脚本内引用面);第 12 号文件内零前向引用 13 号对象(summary_accept 行等) | gate 加载边界教训 |

### I 组 · kind 扩展与 enqueue(summary)

| # | 断言 | 对应 |
|---|---|---|
| I1 | 加载:十三文件前缀库退出 0;effects.kind CHECK 六值;context_summary 行可 INSERT(手插合法载体)而第七值拒 | 换体清单 |
| I2 | effect_attempt_cap v2:六键恰等且 active;judge/tool/llm/human/context_refresh 五值=v1 原值(逐键相等断言);enqueue('context_summary') 缺键面零(cap v2 同事务前置——手插先行拒的负向在 I1 前置库断言) | 消费清单 #22 |
| I3 | enqueue 幂等:同 sid 同 request 两次 enqueue→同 effect_id 同行;request 变(span 变)→新 ID;request 零水位字段(键集断言) | DP1 机制/OQ2 |
| I4 | single-active:活跃 effect 在场时 v13_summary_schedule→NULL 零行;静默期→enqueue 成功 | OQ2/不变量 2 |

### J 组 · 调度与预算包预留(§6.4-1)

| # | 断言 | 对应 |
|---|---|---|
| J1 | intent 在场:fixture(actions 开+tier CompactHistory)→settle 后 economics.summary.intent={target_span,span_digest,packs} 可读;Normal 档⇒intent=null | §6.4-1/OQ2 (ii) |
| J2 | 调度过闸:静默期 schedule→effect 建立且 request 冻结 packs/policies 快照;当日 schedule_cap_day 耗尽→NULL;花费闸超→NULL(judge_spend 含验收 ask 口径) | §6.4-1/OQ6 |
| J3 | 预留失败零调用:pack 不可用(cap 耗尽/策略缺)→schedule=NULL 且**零 effect 零 judgment_calls 新增**(§6.4-1「生成与 Jev 都不调」)——下一次装配 transform trace 记 basis | §6.4-1 |
| J4 | span 在场守卫:active manifest 段 hash 集不含 intent.span 任一⇒NULL(等下一版 intent) | OQ2 (2)④ |

### K 组 · 生成后确定性检查(§6.4-2/3)

| # | 断言 | 对应 |
|---|---|---|
| K1 | prepare 全链(mock LLM):claim→生成(mock 文本)→checks 过→complete('succeeded',result 含 rounds/adopted)——零语义事件(events 语义族计数零增,gate P 前置) | OQ2 (3) |
| K2 | 五项检查逐项 fail:构造 ①空文本 ②不缩短(摘要长于 span) ③受保护元素丢(uuid/路径/数字/工具名四子集逐个) ④控制字符/超长 ⑤超 gen_tokens_cap→各自 reasons 命中且**complete('failed') 且零 judgment_calls 行**(失败不调 Jev) | §6.4-3 |
| K3 | est 同源:summary est 与 DP3 公式手算相等(零第二实现);「确实缩短」断言 est(summary)<Σest(span) | 消费清单 #4 |
| K4 | pack 纪律:packs=1 时检查失败即终结(无重试);effect_attempt_cap context_summary=2 的 claim 轮次语义(v13_attempt_ok 共用面) | OQ8/#22 |

### L 组 · 验收判定(§6.4-4;OQ8)

| # | 断言 | 对应 |
|---|---|---|
| L1 | 信封形态(**十键——P1-5 修**):键集恰等 resolve 消费面(sid/ctx/needed/templates/groups/budget/timeout_ms/candidate_set_hash/provider/model,逐键对齐 DP2 §3.6);ctx 恰 source/summary 两键=最小可见性且=groups[].state 同源;needed 单问携 template_name;budget={batch_questions:1}(resolve V3002 形状过);candidate_set_hash=span_digest;provider/model fail-closed:GUC 缺→V3002;signal='summary::'||64hex(零 corpus_exists/chunk:: 碰撞);**验收 ask 落 judgment_calls 行携 candidate_set_hash=span_digest 锚**断言 | OQ8/§6.5 |
| L2 | accept 采用(P1-6 口径):mock verdict p=0.9→decision 落行(epoch='pre-finalize'断言)→worker 按 (signal,context 等值) 单查取 decision_id→verdict(p_decision_id) action='include'/basis='decision_accept'→complete result rounds[].decision_id 冻结→下一 settle summary 段在场(transform summarize) | §6.4-4 |
| L3 | 不采用四态(经 decision_id 直取面——P1-6):reject(p=0.2)/review(p=0.6)/missing(单查零行——verdict 对不存在 id 返 default_missing)/timeout(预置 failed 行)→action='exclude' 逐态 basis 可区分;**缺省动作来自 defaults 点**(points.summary_accept 三态 exclude——jdef 追点后校验器绿) | §6.4-4/消费清单 #8 |
| L4 | 缓存半边:同 ctx(materials 不变)二次验收→judgment_calls 零新增(命中);同 span 新摘要文本→新 request_hash 新行(重验独立) | §6.4-4 |
| L5 | final_action 词面:accept→judgments 消费集(若 summary 段进 sections 则 decision 进 judgments.final_action='include');不采用态零进 judgments(DP3 谓词) | DP3 契约 #7 |

### M 组 · 重生成非重问(§6.4-5)

| # | 断言 | 对应 |
|---|---|---|
| M1 | packs=2 fixture(summary_accept v2 翻 active):round1 检查失败→round2 **新生成文本**(mock 注入不同文本)→新 ctx→新 request_hash→新 decision 行(行数恰 2);**不得只重问**(同摘要重验→命中缓存零新行的负向对照) | §6.4-5 原文 |
| M2 | 预算包守恒:两 round 后无第三 round(packs=2 封顶);全部失败→complete('failed')/adopted=false | §6.4-1/5 |

### N 组 · CJK 拒绝-only(§6.4-7)

| # | 断言 | 对应 |
|---|---|---|
| N1 | CJK 材料识别:span 全文 CJK 占比>0.30 fixture(中文语料)→cjk 门激活 | OQ8 |
| N2 | 拒绝-only 两向(材料=decisions.context->>'source' 存储半边——P1-6):①CJK 材料+accept band 信号(p=0.9)→**仍不采用**(basis='cjk_reject_only');②CJK 材料+reject 信号→不采用(附加拒绝信号生效);③非 CJK 材料+accept→采用(门不激活) | §6.4-7 原文 |
| N3 | mode='calibrated' 翻版(数据动作预留):翻 cjk.mode→①行为翻转(accept 可采);校准 fixture 未落地前生产 mode 恒 reject_only(README 纪律) | OQ8/台账 |

### O 组 · 消费与回退链(G-ctx8 摘要段;§6.4-6/8)

| # | 断言 | 对应 |
|---|---|---|
| O1 | 采用消费:adopted=true→下一 settle summary 段在场(kind/priority/cache_scope/payload_ref blob/est/transform={applied,name:'summarize'});history 收缩为 keep_tail 尾;blob land 内容寻址(重 settle 零新行);**est(summary)<est(被替 span)** 且总 est 下降 | §6.4-2 消费半边 |
| O2 | span 失配不消费:adopted 但 span hash 已不在候选(history 已变)→summary 段不进场、basis='span_stale'、回退链接管 | OQ2 (4) |
| O3 | 回退链三级顺序:验收不过(reject/review/missing/timeout/CJK)且需压缩→①spill 在场(history 段 transform name='spill',est 降)→不足②oldest round 段 reason='compaction_round_drop'→不足③reason='compaction_final_trim';**三级严格按序**(不可跳级的负向 fixture:①能装下则零②);逐步 applied/skipped trace 完整 | §6.4-6/G-ctx8 |
| O4 | 预留失败路径:J3 场景(零 effect)→装配记 reason='summary_unavailable' 与 fallback trace——「预留失败直接 drop/spill」的装配半边 | §6.4-1/G-ctx8 |
| O5 | 硬类保护:回退链与 hint 全程零触及 goal/tools 段(字节不变断言);goal_hash=版本化 v13_goals 行(引用 DP3 A 组,零改) | §6.2 触点 1/DP3 OQ2 |
| O6 | 放弃分支零新增 Jev:全部失败路径(judgment_calls 计数前后相等——超闸/检查失败/验收拒绝后的装配期);**措辞纪律**:README 与 gate 注释写「零新增调用≠零成本」(已超时/失败调用可能已计费) | §6.4-8 |
| O7 | validate v3:summary 段/四新 reason/两新 name/economics.summary 子块全部正向过、负向拒(V3007);多段化规则下 history:8hex 双段可构造(chunk sections 缝的结构性验证) | OQ7/DP6 OQ7 |

### P 组 · 拓扑纪律与回归(summary 收口)

| # | 断言 | 对应 |
|---|---|---|
| P1 | 语义窗零污染:context_summary complete('succeeded')后 events 语义族(user/message、llm/message、tool/result)计数零增;canonical_state/transcript 策展零新行 | 不变量 3 |
| P2 | freshness 追动:验收 decision 落地→token.dec 变→② 不新鲜→refresh 消费之(无需新触发机制);zero-decision 场景零追动 | OQ2 (4) |
| P3 | prepare 在静默期:turn llm effect claimed 期间 schedule→NULL(I4 已断);新消息先到→advance ① 等待语义(驱动契约 README,延迟上界=一页账 v3 行)——行为面断言等待后照常推进 | OQ2/不变量 2 |
| P4 | 双登录:schedule/checks EXECUTE 归 route(verdict/envelope 归 resolve)——SET ROLE 负向断言两向;worker 双连接形态(README 契约) | 不变量 12 |
| P5 | 上游回归子集(DP3/DP6 等价物在 13 号库复测):settle 幂等 replay/迟到 decision 不回写/exact replay 旧 verdict 含 summary 验收行/确定性双跑字节等/DP6 F7 同族 | DP6 F7 同型 |
| P6 | 加载边界:summary gate 断言对象≤13 号;全部 gate 收口清单在 README(两 stage 各自 test_*.py 退出 0) | gate 加载边界 |

### 4.1 逐文件影响与实施顺序

| 文件 | 动作 | 前置 |
|---|---|---|
| `v13/economy/v13_economy.sql` | 新增(§3.1) | DP1–6 十一文件已存在 |
| `v13/economy/{setup_db.py,test_economy.py,README.md}` | 新增 | SQL 注册后 |
| `v13/summary/v13_summary.sql` | 新增(§3.2) | economy 文件加载绿(A–H 组绿) |
| `v13/summary/{setup_db.py,test_summary.py,README.md}` | 新增 | 同上 |
| `v13/load.py` | SQL_LOAD_ORDER 追加两行+STAGE_THROUGH 两键 | 两 SQL 就位 |

实施序(两里程碑):
**M1(economy)**=策略行→定价表→派生函数(ro_reserve/judge_spend/econ_ver/cache_breaks/pricing_r)→换体一(context_required)→换体二(parse 闸)→换体三/四(assemble v2/validate v2)→换体五(refresh)→ACL→setup/test(A–H 绿)→README+一页账 v3→提交;
**M2(summary)**=kind 扩展+cap v2→summary_accept→模板三步→defaults 追点→span_digest→checks→envelope→verdict→schedule→装配/validate v3→ACL→setup/test(I–P 绿)→README→提交。
每里程碑提交前:该 stage 及之前全部 stage gate 复跑(AGENTS.md);按路径 add,禁 `git add -A`。

**F5② 一页账 v3(economy README/gate A5 同源载体)**:

| 面目 | 调用数 | 快路 | 慢路轮(effect 往返) | 量级 |
|---|---|---|---|---|
| 判断面(DP6 表原样) | k=64 最坏 4 asks | 1 批 | 3 轮 | ≈4×1.3–1.6s |
| 摘要 prepare(每 pack) | 1 gen+1 Noul | 0 | 1–2 轮(effect 往返) | gen 数秒级+Noul ≈1.3–1.6s |
| 验收缓存命中 | 0 新增 | — | — | 零(同 materials 重验) |
| 超闸快路(F5①) | 0 新增 | 0 | 缺口全转慢路 | 快路零延迟增量 |
| 重生成(packs=2) | +1 gen+1 Noul | 0 | +1 轮 | 两 pack 最坏 ≈2×(gen+Noul) |

结论:摘要 prepare 在静默期运行不进 turn 关键路径;若用户消息先到,turn 等待上界=上表单 pack 行(P3);mock 单价=v12 G7 量级(9 问 $0.000042)。

**收尾工件(AGENTS.md,两里程碑各一次)**:SQL 追加进 v13/load.py(第 12/13 位);两 stage README;一里程碑一提交(`v13: <祈使句摘要>`,按路径 add,禁 `git add -A`)。`v13/economy/README.md` 必记:①tier/压力/R_o 公式与冷启动 fail-safe 方向(OQ3/4);②bands shadow seed 与本地校准流程(actions_enabled 翻版仪式);③E(r) 三纪律与定价目录运维仪式(录入/翻版/区间元数据);④三桶配比与 effective_budget 口径;⑤花费闸两上限与收紧流程、慢路不闸的立法依据;日闸作用域=per-session 每日(v13_judge_spend 的 day_asks 带 session_id 过滤——F5① 单 session 零 turn 刷花费的攻击面已覆盖;若意图是账户级日闸=未来 scope 翻版,本读法呈报在档,P2-2);⑥fastpath_tiers 放宽流程(三前提缺一不可);⑦k_max 放宽流程(DP5/DP6 契约转发);⑧cache-break 归因用法(v13_cache_breaks);⑨一页账 v3 表;⑩措辞纪律「放弃分支零新增 Jev 调用≠零成本」。`v13/summary/README.md` 必记:①驱动契约(turn 静默期调 schedule;prepare worker 双连接 route 主/resolve 副;新消息先到则等待——上界一页账行);②回退链三级顺序与硬类保护;③验收带/缓存/CJK 拒绝-only 与校准翻版路径;④预算包/packs/attempt cap 三层关系;⑤transform 词表扩展纪律(新名+新版本行,DP3 契约);⑥signal 命名空间 summary:: 保留声明;⑦worker 契约:llm result 应携 usage+model(缺=无样本不是错样本;P0-1——生产 request={route} 零 model 键,分位桶谓词读 result 侧);prepare 取 decision_id 的单查口径(signal+context 等值,P1-6);mock 仅测试;⑧与 DP8 的 render_policy/latch 缝(§1.4)。

---

## 5. 风险与回退

| # | 风险 | 缓解 | 回退 |
|---|---|---|---|
| 1 | **五个 OR REPLACE 换体破坏上游行为**(parse/assemble/validate/context_required/refresh——DP1/DP3 面) | 机械复制加载态原文+仅标注增量;G1(闸零扰动)/C5(actions off 字节对齐)/H3(上游 gate 抽样复测)三重回归面 | 前缀库结构性隔离:12 号文件卸载=删除文件+load.py 两行,上游世界零残段;两 stage 均纯末尾追加 |
| 2 | **prepare 延迟进 turn 关键路径**(用户消息先到,single-active 等待) | 静默期调度优先;一页账 v3 延迟行;attempt cap=2 封顶重试 | 台账:取消/抢先(新消息到达时取消 prepare)=触发条件「静默期 prepare 实测常被起呸」;v1 等待语义(有界) |
| 3 | **冷启动 R_o 过大→常年早压缩**(economics 偏保守动作) | actions_enabled=false shadow:生产 v1 动作层零激活,冷启动只影响记录面;校准后一次翻版 | cold_tokens/min_samples 均策略键,实测偏高即翻版下调 |
| 4 | **摘要验收信封 ctx 体积大**(span 全文+摘要全文进 ask 材料) | 单问单批;缓存命中率间接受 span_digest 粒度保护(同 span 重验零成本);payload 体积在 judgment_calls 在档(可观测) | 检查参数 max_body_bytes 上限拒收超长 span(span 超限=basis='no_budget' 不调度——§6.4-1 预留面) |
| 5 | **定价目录失准**(r 错) | 三纪律:r 错只翻转账单不翻正确性(OQ5 原文);branch 可观测;r_unknown 不动作 | 翻版仪式;审计=manifest r_source 逐版可查 |
| 6 | **defaults 追点版本号錨定错**(max+1 伪码漂移) | 实施期变量化 SQL+gate L3 前后校验器双断言 | 还原:翻回前版(旧版本行留档) |
| 7 | **语义窗污染回归**(context_summary 误走 llm 分支) | 结构性:DP1 complete 对非 llm/tool/judge 零语义事件;P1 计数断言 | 若 DP1 机制漂移(未来版本),P1 红即拦 |
| 8 | **hysteresis 链派生性能**(每装配回溯 artifact 链) | 链深=cooldown 窗口(浅);settle 本在锁内毫秒级面;索引=artifacts 主键链读 | 超预期→链长上限策略键(台账) |
| 9 | **gate fixture 依赖翻版操作多**(C2–C6/E4/N3 翻策略) | 每组测毕还原(双回滚)纪律逐处写入;A2 演练仪式 | fixture 未还原→后续组红即暴露 |
| 10 | **G-ctx6 语义被误按原文断言**(评审/实施期拿 §10 原文对峙) | §4 取代注记表+plan 头注双重标注;README 同文 | 用户推翻绕行默认→重开 gate 面(附 A #6 呈报在档) |

## 6. 教程映射(§13;正文零改动)

| 章 | 映射 | 落点 |
|---|---|---|
| ch10(装配清单 schema) | economics 块/三桶/summary 段 kind/transform 词表扩展/est 同源——讲解进两 stage README,教程正文零改动(§13 只记指针义务) | v13/economy/README+§4 E/O 组;v13/summary/README |
| ch13(后台平面) | 摘要 prepare 驱动契约**不是 tick 对象**(由 effect/驱动事件驱动,cron 零新增);一页账 v3/花费闸运维注记 | 两 README;DP6 ch13 映射(扫地僧非节拍器)与本条同源零冲突 |
| 边界 | 本 plan 不改任何教程正文;§13 映射=README 指针义务(与 DP3–DP6 同型) | — |

## 7. 明确不做(§12 台账为源;P2/台账项一律不承诺为首版交付)

| 项 | 依据/触发条件 |
|---|---|
| 效用遥测(触点 4,P2 弱标签实验) | §6.2/§6.3/§12:未经反事实评估不得驱动线上策略;post-execute 生产者零存在(DP3 契约 #6 维持) |
| 预取排序(触点 6) | §6.2/§12:ch13 长目标树落地且下一查询可预测才有收益 |
| Emergent 表+在线 triage(触点 3) | §6.2 轮 2 已砍在线路径;确定性 admission 归未来 producer |
| 分片哈希启用 | §12/DP2:全量哈希下缓存损失实测超标才启用(执法机械 DP2 已落) |
| 语义决策缓存/T1 vectorchord/bigram/boost 反馈环 | §12 台账原文;触发条件逐条在档 |
| chunk 段级装配(DP6 OQ7 缝) | 非本 plan 所指派 §;多段化已结构性就绪(OQ7),落地=纯数据动作(动作清单 §1.4) |
| 记忆段进 manifest(DP6 ④缝) | 同上;degraded 消费契约已引用(§1.4) |
| render 函数本体与呈现偏好 | §5.3 首版单一 canonical;render_policy 行已立(本 plan),本体+identity/token 追动归 DP8 |
| latch/latch 交付位置矛盾(F9) | F9 归 DP8 呈报(附 A #8);本 plan 零触碰 |
| semantic_compact_hint flip | shadow-first(§6.2 触点 1 裁决);flip=未来策略版本(校准证据门槛) |
| tier actions 激活/本地校准 | shadow seed(轮 2 P0);校准流程已立(§1.4),激活=数据动作 |
| CJK 摘要校准 fixture | §6.4-7:校准前 reject_only;fixture 设计记台账(触发=生产 CJK 语料占比实测) |
| 定价目录维护自动化 | §14 遗留开放项:手动翻版仪式+README |
| 慢路花费闸 | v1 只闸快路(OQ6 立法);触发=慢路费用成账单大头(台账) |
| 摘要 prepare 取消/抢先 | v1 等待语义(有界);触发=静默期 prepare 常被起呸(台账) |
| k_max 放宽 | 流程已立法(三前提),不预放宽(DP5/DP6 契约) |
| GC/保留窗口 | DP3 §7 已留缝(被引用即保留);本 plan 零新增保留面 |
| 在线 learned policy/Jev 决定 tier·cache scope·marker/Jev 覆盖结构校验 | §6.7 拒绝清单原文——永久不做非台账 |

---

## 附 A:与设计稿/上游裁决的分歧点清单(供父 loop 复核)

| # | 分歧 | 本 plan 裁决 | 呈报 |
|---|---|---|---|
| 1 | §5.4「tier 阶梯=thresholds 路由带」——载在 thresholds 表还是 v13_policies | **v13_policies 行 context_tiers**(bands 形状沿用 [lo,hi) 半开区间同构):DP1 §1.3 DP7 行明定 v13_policies 为经济件版本化载体;thresholds 表挂 route 意图带的 draft 父表机制(¥1 §3.1:546–637),混用会把 tier 翻版耦合进路由策略父表机制 | 载体系,非语义分歧 |
| 2 | §5.4「L_eff 来自 meta」——仓库无 meta 表(DP1 M1 未建,仅 v13_tools_meta singleton) | context_budget 行 `l_eff_tokens`(版本化+可追动);DP8 generation 行填真后经新版本行迁 single-source(§1.4 缝) | 载体系;「meta」读作模型元数据面 |
| 3 | §5.4「(model,source) 桶」——source 未定义载体;model 半边的谓词侧(修订 1 呈报,P0-1) | source=effects.kind(llm=turn 生成/context_summary=摘要生成——生成平面天然分桶);**model 谓词读 result 侧**(result->>'model'):DP1 ④ llm 分支 enqueue 的 request 恒 {route:{action,reason}}(DP1:2484–2486)零 model 键——request 侧谓词在生产面恒 NULL=恒空桶=永久冷启动;配套 worker 契约单侧扩记「llm result 携 usage+model」(DP1 v13_complete llm 形状校验只要求 text 非空 DP1:446–451——result 增键零上游改动) | 载体化立法+裁量呈报(worker 契约单侧扩记,DP1 零改) |
| 4 | §5.4「带生效区间的定价目录」——now() 选行 vs 装配零时钟 | active 标志选择+区间元数据+翻版仪式;区间不做运行期选择(确定性优先,exact replay/recompute 可推演) | 载体化;设计未明说选择机制 |
| 5 | pricing 不入 token | r 只影响账单选择(设计原文「r 错误翻转的是账单选择,不影响正确性」);追动键缝纪律的适用域=manifest 内容输入 | 论证型,零语义损失 |
| 6 | §10 G-ctx6 原措辞 vs §5.4 轮 2 修正(stepfun F8) | **用户既定默认(轮 1 后裁决):不修冻结稿,plan 内绕行**——gate 按修正语义写+双重取代注记 | 用户可推翻;推翻则重开 gate 面 |
| 7 | 三桶 v1 ACTIVE 而 tier 动作 v1 shadow | 三桶是确定性装箱策略(无校准依赖,不改「是否压缩」只改「装多少」);tier 阈值是校准依赖的动作门(轮 2 点名 shadow)——纪律分层非不一致 | 论证型 |
| 8 | stepfun F9(latch 交付位置矛盾) | 归 DP8 呈报(分解表 DP8 范围);本 plan 零动作 | 转呈 |
| 9 | 触点 1 归属重叠:loop 分解表 DP8 行含触点 1,本 brief 给 DP7 | 本 plan 按 turn-29 brief 落 shadow-first 机制(hint 记录面+硬类保护);**建议控制器把 DP8 brief 改为消费本 plan §1.4/触点 1 契约**(flip 门槛与候选顺序参与语义),避免双实现 | 呈控制器(本轮汇报主项之一) |
| 10 | 预算包语义:「预留」的载体 | 预留=schedule 时点判定(花费/调度闸+策略在场)+request 冻结 packs 形状;不建新预算表(turn_budget cycles 不动,经济面闸在 judge_spend_gate/summary_accept) | 载体化 |
| 11 | §6.4-2「生成摘要 artifact」的落库路径 | 摘要正文暂存 effect.result,settle 日经 v13_blob_land 落 context_section blob——不新增 artifacts 直写面(lander 零运行角色纪律不动);「artifact」语义=内容寻址 blob+manifest 段 | 载体化;与 DP3 P0-3 同源 |
| 12 | est 公式零改 | 摘要段 est 用 DP3 同公式(零新 tokenizer);换公式=DP3 契约新版本行 | 零分歧,确认项 |
| 13 | DP2 judgment_calls.candidate_set_hash NOT NULL(DP2:327)——摘要信封的锚载体与 budget 单位(修订 1,P1-5/P2-4) | 锚=span_digest(与 signal 同一单源函数产物;round 间共享锚=审计回连面,轮区分靠 payload_hash/request_hash);信封十键=resolve 实际消费键集逐键对齐(DP2 §3.6 实读);budget={batch_questions:1}(resolve V3002 形状面)——packs_reserved 留在 request/schedule 面,两键单位歧义就此收口 | 载体化+单位裁定 |
| 14 | summary_verdict 裁决的 decision 定位:材料重建 vs decision_id 直取(L4 P1-6 二选一,修订 1) | **decision_id 直取**:签名 (p_decision_id);prepare 面=worker 按 (signal,context 等值) 单查取 id(材料在手),消费/replay 面=effect.result→rounds[].decision_id(OQ2 步 3 已冻结)——两调用面同一函数;拒扩 source 参理由=4 参携 span 全文且 lookup 材料取自调用方输入,弱于「材料=存储」纪律(DP6 不变量 6 同构) | 签名裁定;fixture 已同步(L2/L3/N2) |

## 附 B:全教训自检(turn 1–28,机械执行记录)

| 教训 | 本 plan 执行 |
|---|---|
| **纸面加载模拟记数字**(turn 8/9/DP2 勘误型) | 本稿(修订 1)§3 草案对象:**两文件合计 48 条顶层语句(economy 23/summary 25——修订 1 增=定价种子 INSERT+恢复单源函数),ACL 块 9 条(5+4),新建函数 12 个(v13_pricing_frozen/pricing_r/recovery_active/ro_reserve/judge_spend/econ_ver/cache_breaks+span_digest/summary_checks/summary_envelope/summary_verdict/summary_schedule),OR REPLACE 7 处(12 号:context_required/parse/assemble/validate/refresh;13 号:assemble/validate 再跳——§1.1 计数已对齐 P2-1),表 1(v13_pricing),触发器 1,索引 1,种子 INSERT 7(策略五行组 1+cap 1+summary_accept 1+模板两表 2+defaults 1+定价目录 1——P1-2 补齐后计数与枚举吻合)+翻版 UPDATE 6**。实施期以脚本机械复核计数为准(V0(c) 同族纪律),本处枚举供对照;草案级函数体(v13_summary_checks/verdict/schedule)实施期展开后重数 |
| **同签名唯一定义**(turn 9 #57/42723) | 两文件内同名 CREATE 各恰一处;assemble/validate 跨文件两跳为 OR REPLACE 替换链(非双定义——DP6 对 DP3 同款);无参数变体无重载;修订 1 签名变更对齐:v13_summary_verdict (uuid,text,text)→(uuid)(P1-6 decision_id 直取)——§3.2 ACL 块/§4 L 组/附 A #14 已同步 |
| **前向引用**(turn 8) | 12 号文件零引用 13 号对象(summary_accept/summary_* 函数/kind=summary 段均 13 号);两文件对上游对象引用全部≤各自前缀(guc_required/judgment_templates/enqueue_effect/last_user_seq=DP1/DP2 已载);ACL 块真末尾且引用签名全部先建 |
| **类型算子层**(turn 7/8) | pressure 基点制纯 int 乘除零 numeric 往返;percentile 百分位参数 numeric 字面量、返回 double precision 显式声明+::bigint 收口;digest() 产物一律 encode(...,'hex');regex 守卫(`~ '^[0-9]+$'`)先于 ::bigint;string_agg ORDER BY 字典序(键串断言载体);jsonb 键存在 `?`、值比较 ->> 后 IS DISTINCT FROM;枚举判断 IN(...) IS NOT TRUE;jsonb 种子单完整字面量+::jsonb;块末分号逐条(种子 INSERT 末元组带 `;`——DP1 #57 同型面) |
| **移动=增+删**(turn 8) | 零移动场景(全部新文件);OR REPLACE 语义本身=替换非复制;如实施期调整段落,同签名旧体必删 |
| **gate 加载边界**(turn 6/9) | economy gate 断言对象≤12 号、summary ≤13 号(H4/P6 断言面含 grep 脚本引用检查);上游 gate 前缀库结构性复跑(不变量 12) |
| **哈希同源**(turn 4/DP6) | span_digest/econ_ver/pricing_r/ro_reserve/recovery_active 各单源函数(恢复判定=ro_reserve 与装配 recovery_floor 同源消费——P1-3);est 公式唯一(DP3 原文复制);验收裁决经 decision_id 直取 decisions 行(材料=存储,零哈希重算——P1-6;prepare 面取 id 的 context 等值单查在 worker 侧,材料在手零重算,DP6 不变量 6 同构);信封 candidate_set_hash=span_digest 与 signal 同一单源、四面同源(signal/锚/rounds[].span_digest/intent.span_digest——P1-5);token.econ_ver 与 settle 锁内同一 v13_econ_ver |
| **新写 SQL 自检**(turn 3) | 参数全用(ro_reserve 的 p_sid 用于恢复期判定+注释显式声明不按 session 过滤);列存在(judgment_calls.created_at/effects.error 等以加载态实查为准——实施期逐列核对清单进 README);每函数块配平/终结符逐条(实施期) |
| **引擎争议实机实证可选**(turn 10/12) | 本 plan 零新增争议引擎面(无 event trigger/无 WHEN OTHERS 吸收/无超时分类);percentile_cont 返回 double precision(big input)与 partial unique index 为文档化标准行为;**如实记「无可实证清单」**;若实施期对 ALTER DROP/ADD CONSTRAINT 的依赖面(视图/FK 无依赖 CHECK)有疑,沿 DP1 本地探针库仪式实证 |
| **种子纪律**(turn 10 #64) | 翻 active 一律 INSERT inactive→双 UPDATE 同事务;策略值变更=新版本行不 UPDATE value;测毕双回滚写入 gate |
| **gate 可执行性**(DP2 A8/B3/B5 教训) | 全部 gate 先在计划内自问「fixture 可构造吗」:C2 同 turn 多版装配=cycle>1 驱动;D1 价差 fixture=定价行控制;L 四态=mock/预置行/毒化;M packs=2=策略翻版——无「需手摥不可达状态」的断言;**fixture 构造口径纪律**(§4 头注,P0-1 教训):R_o/恢复类至少一半经真实 enqueue/complete 路径,手插行键形与生产 complete 产物逐键对齐 |
| **措辞纪律**(§6.4-8) | O6 断言口径=零新增 judgment_calls 行;README 同文「零新增≠零成本」 |

---

## References

- 设计稿:`docs/designs/v13-context-on-pg.md`(冻结禁改;§5.4/§5.5/§6.2 触点 1+2/§6.4/§6.7/§9/§10/§12/§13/§14)
- DP1:`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`(§1.3 DP7 行/§3.1 v13_policies+effects DDL/§3.4 parse/§3.5 advance·complete/§3.6 台账)
- DP2:`docs/plans/v13-dp2-judgment-envelope-plan-2026-09-20.md`(§1.4 DP7 行/§3.2 judgment_calls/§3.4 信封 19 键+budget 冻结/§3.5 effect_id 豁免)
- DP3:`docs/plans/v13-dp3-manifest-skeleton-plan-2026-09-20.md`(§1.4 DP7 行/§1.3 OQ1–OQ7/§3.2–§3.5 装配·校验·refresh/§4 B–F 组)
- DP4:`docs/plans/v13-dp4-chunks-projection-plan-2026-09-20.md`(哈希载体化/content_hash 同源——跨平面一致性的上游)
- DP5:`docs/plans/v13-dp5-stannum-recall-plan-2026-09-20.md`(§1.4 DP7 行/OQ5 k 策略/§4 末一页账/J 组)
- DP6:`docs/plans/v13-dp6-filter-memory-plan-2026-09-20.md`(§1.4 DP7 行/OQ5 degraded 契约/OQ7 manifest v2 移交/§3.1 装配换体先例/§4 末一页账更新/F 组)
- stepfun 评审:`docs/reviews/v13-context-on-pg-design-review-by-stepfun-2026-09-20.md`(F5/F8/F9)
- L4 评审:`docs/reviews/v13-dp7-economics-summary-plan-l4-review-2026-09-21.md`(1 P0/6 P1/8 P2——修订 1 的修复输入;出口裁定=局部修正,零全量重审)
- loop memory:`prompt-exports/loop-orchestrate-v13-deep-plans-runs.md`(分解表 DP7 行/turn 1–28 全部教训/用户裁决记录)
