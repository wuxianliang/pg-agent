# v13 设计审查：Context on Postgres（v13-context-on-pg.md 草案 v2）

审查日期：2026-09-20。审查：stepfun。一次有界设计审查——仅评审、不实施、不改设计稿、不运行任何 gate。不复议轮 1/轮 2 已裁结论；只找规范空洞、内部不一致与未入账的成本。

## Context / Scope

- 被审文档：`docs/designs/v13-context-on-pg.md`（草案 v2，487 行，全文已读；SHA-256 见文末静态核验）。
- 交叉参照（均实读，不漫游）：`docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md`（§0–§3 骨架、M4 gate 表、§5 风险表、turn 3–8 修复台账）；`docs/tutorials/v13/chapters/04-decision-plane.md`（decisions/thresholds 全表定义）、`01-log-plane.md`、`05-turn-and-advance.md`；`v12/schema/v12_schema.sql`（表清单核实：jev_batches/jev_questions/jev_decisions/jobs 与教程命名层的缝隙属实）；`AGENTS.md`（仓库约定，含外部 IO 纪律条目）。
- 审查方法：逐节对照「作用力 → 承重件 → gate → 交付排序」的四层一致性；每个 finding 给出可指认的原文位置与可执行的修复建议；凡 DP1 已在计划层打补丁的，注明「计划侧已补、设计侧未改」。

## 已核实成立的关键断言（不重复列入 Findings）

- 两阶段 advance 的核心纪律在计划层已闭环：解析相全程不碰 sessions 行锁（DP1 不变量 1）、resolve 失败审计事件落变更相、G-ctx1-2 改为锁竞争断言为主（turn 3 P1-8 修正后能拦住 1.3–1.6s 持锁判断回归类）。§4.3 的方向被 DP1 正确承接。
- 教程 ch4 的单表 decisions（session 作用域 FK + `UNIQUE(request_hash)` 全局唯一）确实无法承载 §4.3 字面的「内容寻址缓存 + ON CONFLICT DO NOTHING」；DP1 §1.2 新建 v13_core 切片、§3.3 改受限填充 DO UPDATE（WHERE answer IS NULL）是对设计缺口的正确补丁（缺口本体见 F7）。
- §6.1 三 epoch + manifest freeze + 迟到不回写，与 DP1 不变量 7 的 origin 锚定（M4-K8 fixture 覆盖跨 turn straggler 三形态）互相印证，方向一致。
- §6.7 不整合清单边界划得干净：Jev 不裁 cache scope/marker/物理排序/硬预算/protected 硬删除/在线 learned policy；「SQL 短路确定情形、Jev 只裁不确定带」是全文最好的整合姿势。
- §5.4 轮 2 对 tier 单调性的 P0 修正本身正确（跨 turn 永久单调会让一次高压永久锁死 AggressivePrune）；问题只在 §10 gate 清单没跟着改（F8）。
- E(r) 的处理诚实：明写「只是输入成本代理，未覆盖摘要调用、输出与延迟；r 错误翻转的是账单选择，不影响正确性」；OpenRouter 路由不确定时不用猜测的 r 行动。

## Findings（按负载排序，共 15 条：5 P0 / 6 P1 / 4 P2）

### F1（P0）判断点的「版本化默认分支」整段是空话——流量最大的过滤点没有规定缺省动作

- 位置：§6.1（「缺失、超时、review 带一律走版本化默认分支」）；§4.5（过滤管道）。
- 依据：全文为判断点写明默认行为的只有两处——§6.4-4 摘要验收「review/reject/缺失/超时不采用」（fail-closed）、§6.2 触点 5 intent「低置信/CJK/缺失→绑超集」（fail-open）。§4.5 的 per-chunk Score 与存在性 Noul——系统中调用频次最高的判断点——缺失/超时/review 带时装入还是排除，无任何条文。
- 问题：§0 的核心卖点是「机器永远是确定性的」；确定性首先要求每个判断点的缺省动作被写死，而不是由「版本化默认分支」这个词承诺。pg_typesafe 是 pre-alpha（§2.2），它失败最勤的恰是这些点；缺省不定，则每次故障的行为由实现者临场决定。
- 修复建议：§6.1 或 §4.5 增加逐判断点表：判断点 × {缺失, 超时, review 带} → 动作（装入/排除/降级路径），各行进版本化策略载体；§10 增 gate：mock 毒化（超时+缺失+review 三形态）下逐点断言默认分支生效。

### F2（P0）存在性 Noul 的缓存键漏了候选集维度——陈旧「无答案」判定会静默漏掉新证据

- 位置：§4.5（「先一个存在性 Noul 闸住整批花费……再逐 chunk Score」）。
- 依据：per-chunk 缓存键逐字段写明（hash(问题, chunk.content_hash, query.content_hash) + provider/model + rubric/answer schema 版本）；存在性判断的缓存键全文未定义。其答案是 (查询 × 整个候选集) 的函数，而候选集随重摄取/重建变化（§4.2：重摄取 delete+insert 同事务）。
- 问题：若键只含 query（最自然的省略），重摄取新增能回答的文档后会复用陈旧的「语料无答案」判定，整批 per-chunk 调用被闸掉——新证据静默消失、不报错，与作用力 2 批判的「不报错，只静默漏召」同一种死法，且发生在设计自己新建的机制里。
- 修复建议：§4.5 明文：存在性判断键 = hash(query.content_hash, 排序后候选 content_hash 全集) + 模板/model/版本；与 DP1 信封已携带的 candidate_set_hash 对齐（§1.3/§3.2）。

### F3（P0）chunks 表缺 span 装配必需的偏移基列，且无「被引用内容不可 GC」规则——exact replay 在 chunker 变迁后整体断裂

- 位置：§4.7（「装配单元是被标出的跨度 (doc, offsets) 进 manifest」）；§4.2（可重建投影、truncate+重灌、重摄取 delete by source_hash、外部只记 hash）；§9（chunks 列清单）；§5.2（三种回放之 exact replay）。
- 依据：§9 的 chunks(source_hash, chunk_no, body, content_hash, corpus, chunker_version, analyzer_version) 没有任何 offset/位置基列；stannum highlight 返回的是索引列（chunk body）内偏移，没有 chunk→doc 偏移基准，(doc, offsets) 在现有 schema 上不可表达。同时 §4.2 允许 truncate+重灌与重摄取删行，而 manifest/decisions「只记 hash」——hash 指向的行被删后证据不可回取。
- 问题：chunker_version 一旦升版（§4.6 bigram 路径正是预期中的升版），旧 chunks 全部换 hash，历史 manifest 的跨度引用变死行，§5.2 的 exact replay（读旧 manifest/context）对全部历史 turn 失效——§0「manifest 负责证明当时发现了什么」的审计承诺只对「chunker 未变过的窗口」成立。GC 规则缺失使这成为必然而非意外。
- 修复建议：① chunks 增 chunk_offset（doc 内字节基偏移）列，span 身份定义为 (chunk content_hash, 起, 止)；② 立保留规则：被任何 manifest/decision 引用的 chunk 行不可删除，GC 只清无引用行（引用检查一条 SQL 可表达）；③ §10 增 gate：chunker bump + 重灌后，历史 manifest 逐字节回放成立。

### F4（P0）Jev 层零刻画 gate 却是首交付承重依赖；与 stannum 的待遇不对称

- 位置：§4.8（stannum 刻画 stage +「承重件……不依赖 stannum 一根毫毛」）；§11 交付排序第 1 步（过滤管道列为承重件）；§2.2（pg_typesafe pre-alpha）。
- 依据：stannum（dev software）有完整刻画 gate（绑定矩阵、fold 压测、REINDEX 演练、tokenizer canary）与 runbook；pg_typesafe（pre-alpha）没有任何对应物，而首版第 1 步就把质量与成本承重在它上面（过滤器、判断信封、两相的解析付款）。失败面的规定散落且残缺：超时分类学只在 DP1 计划层存在（turn 5–7 三轮才收敛出 57014/statement_timeout 探针），mock-在线一致性只有 G-ctx1-5 一条，「Jev 整体不可用时过滤器退化成什么」无条文，CJK 劣化只在 §6.4-7 给摘要留了一句。
- 问题：§4.8 的可替换性纪律只保护了 stannum 一侧。承重件对 pg_typesafe 是深依赖（无它则过滤、摘要验收、意图门控全空），却是全文唯一没有刻画 stage、没有 runbook、没有退化策略的底座——风险清单与依赖方向相反。
- 修复建议：把 §4.8 形态镜像到 pg_typesafe，新增刻画 stage：超时/取消/错误码分类矩阵、timeout 与 statement_timeout 可交付性前置探针（收编 DP1 turn 7 #45 雏形）、mock 与在线应答一致性 fixture、CJK 问答劣化校准、Jev-down 退化策略（过滤器 SQL-only 形态 + 摘要验收仅走确定性检查、暂停压缩 tier）；写进 §8 runbook。

### F5（P0）解析相无预算闸、k 无上界——交互延迟与账单各有一个未被分析的悬崖

- 位置：§4.6（「精确 count(*) 让 k 随候选规模自适应放宽」）；§4.5（per-chunk Score 对 k 线性）；§4.3（快路上限=策略行，默认 ≤1 批 ≤32 问）；§2.2（v12 G7 实测 1.3–1.6s；_many 32/批、4 并发）；§5.4（经济件全是 token 账）。
- 依据：k 自适应放宽意味着候选越多问得越多；快路只付 1 批，其余 ⌈k/32⌉−1 批全部转 judge effect 走 worker 慢路，turn 等待若干个 effect 往返（claim/lease/renew/complete）。按实测每轮 1.3–1.6s：k=128 约一个往返；k≈2000 即十几轮、数十秒级。同时 §4.3 的判断付款发生在解析事务，先于变更事务的预算扣减；§6.1 弃批重解析 = 解析相 Jev 花费净损失、不计入任何 turn 预算。
- 问题：「双速」在设计中只被描述为省钱去重机制，从未被当作延迟机制分析。全文没有 turn 延迟预算/SLO，没有 (k, tier) → 延迟的账，没有解析相花费闸——用户连发消息可以零 turn 落地地持续刷判断花费。作用力 8 花整节算 token 经济，判断调用的经济（次数×延迟×重试）无一处入账。
- 修复建议：① 解析相加 per-session/每日判断花费闸（策略行），超闸只走缓存、缺口转慢路；② §5.4 或新增小节给出 (k, tier) → 往返数 → 延迟的一页账与首版 k 硬上限；③ 明文哪些 tier 允许快路超 1 批。

### F6（P1）两阶段的触发拓扑未定（parse 内联还是异步）——作用力 3 只解了一半

- 位置：§1 作用力 3（「这不是延迟问题，是干预面停摆」）；§4.3（两相定义）；§6.2 触点 6（预取 P2）。
- 依据：两相把判断 IO 移出了会话锁，但若 parse 内联在 turn 同步路径，判断延迟仍在用户可见路径上（接 F5）；若异步化，则需要新的 turn 状态与队列消息——循环形状的改变。设计对「谁触发 parse、advance 是否依赖 parse 产物、parse 在飞时 turn 处于什么状态」全文沉默。DP1 只能按「调用者 parse+advance 成对」（README 运维注记）自行立法。
- 问题：作用力 3 把问题定性为「干预面停摆」，两相确实解了锁停摆；但交互系统的真实约束是端到端延迟。拓扑是设计层该裁的事，现在是实现层替设计层裁了。
- 修复建议：§4.3 补一段拓扑裁决：首版 parse 内联成对调用（延迟上界承接 F5 的账）；异步 parse + 判断预取记入 §12 台账并写明触发条件（turn p95 延迟实测超标）。

### F7（P1）三层规范源、权威关系倒置；对 §5 而言「冻结」是名义上的

- 位置：文首（「教程是讲解、本文是设计」「实现规范冻结后以冻结稿为准」）；§5 头（「待 Oracle 复核」）；§9（「既有骨架不动」）；DP1 §1.2 与教程 ch4。
- 依据：核心 schema 的实际裁决形状（单表 decisions、UNIQUE(request_hash) 为全部缓存机制）躺在教程 ch4、标着「Oracle 裁决形状」，§9 却当「既有骨架不动」一笔带过；§4.5 的跨 session 缓存与该形状（session 作用域 + 全局唯一）冲突，DP1 只能宣布「DP6 再立法」。§5 头部仍标「待 Oracle 复核」，DP1 却引用整份设计为「设计输入（冻结，禁改）」——§5 的冻结是名义上的，复核若改写 §5，DP1 前提即漂移。另：§8「库内 IO 例外有且仅有 pg_typesafe 纯判断」是对 AGENTS.md「外部 IO 一律不进数据库事务」的规范演进，但例外至今只存在于 v12 M7 提交信息与 DP1 引用中，仓库约定文件未同步。
- 问题：§8 元原则 (c) 禁第二真相源，规范栈现在有三层（tutorial / design / frozen plan）且最承重的 schema 裁决在最低层；「冻结」语义对未复核章节失效，后续 DP 的「设计输入（冻结，禁改）」引用会失去锚点。
- 修复建议：① §9 收编 ch1/ch2/ch4 表形状（或指针+冻结规则），声明唯一定义处、教程降为讲解；② §5 的「待复核」要么完成复核、要么明文声明该节为非冻结区且可被后续 DP 修订；③ v12 M7 例外回写 AGENTS.md 的 IO 纪律条目；④ DP1 的「分歧点清单」升格为常设工件——每个 DP 强制维护 design↔plan 分歧表。

### F8（P1）§10 G-ctx6 与 §5.4 轮 2 修正直接冲突——gate 清单没跟着 P0 修正回头改

- 位置：§10 G-ctx6（「tier 只升不降跨 turn 成立」）vs §5.4（「轮 2 P0 修正：只升不降仅在单次 Plan 内成立……跨 turn 用 hysteresis/cooldown 受控降级」）。
- 依据与问题：逐字对照即冲突。照 G-ctx6 写断言，会断言一个设计自己已否决并说明危害（「一次高压永久锁死 AggressivePrune」）的单调性。gate 清单是实现与评审的准绳，准绳与正文矛盾时，实现者要么写出错误断言、要么临场猜该信哪边。
- 修复建议：G-ctx6 改写为两条：单 Plan 内单调成立 + 跨 turn hysteresis/cooldown 行为符合策略行；并以此为引子全文复查 §10 其余条目是否还有未随正文修订的陈旧断言。

### F9（P1）优先级标签自相矛盾：latch 的「进核心」与交付位置、pg_cron tick 的「进」与「YAGNI」

- 位置：§5.1/§14（「latch 为 P1 进核心（保护 prefix identity）」）vs §11（latch 排在第 5 步，位于经济学件与摘要验收之后）；§8（pg_cron「P1 进（扫地僧）：tick/投影构建/verify_index 夜跑」）vs §12（「pg_cron tick | 触发条件：扫描恢复的空转成本实测超标」）。
- 依据与问题：latch 保护 prefix identity 即保护 provider 前缀缓存——按设计自己的缓存经济学（作用力 4/8），它是每 turn 生效的正确性/成本件，却排在第 5 步交付；「进核心」与「第 5 步」两说并存。pg_cron 更直接：§8 说 tick P1 就进，§12 说等实测超标才做——同一物件两处相反裁决。
- 修复建议：交付排序与 P 标签合并成一张表（物件 × P 级 × 交付步 × 触发条件），消掉散文两说；latch 建议提前到第 1 步（DP8 已声明其无耦合、成本极低）。

### F10（P1）记忆栈水印的新鲜度语义未定——投影滞后时最新几轮从召回中消失还是直读 events，两说后果相反

- 位置：§4.4（「新鲜度=水印谓词（投影 max(seq) vs events max(seq))」）；gate 只有「p99 events INSERT 延迟有/无投影构建对比断言」。
- 依据与问题：水印谓词只定义了滞后如何度量，没定义滞后如何行动：fail-closed（召回只覆盖已投影区间⇒投影滞后时最新 turn 静默不可召回）还是直读 events（出现第二读取路径，破坏「投影可重建」的单源纪律）。记忆栈的价值恰在「最近说过什么」，而逐字层是 tick 批量构建、滞后是常态；当前 turn 消息有 intent 门控「不得排除当前消息」保护，上一 turn（最常被引用）没有任何保护。
- 修复建议：明文 fail-closed + 滞后上界（水印差 ≤ 策略行阈值，超界召回降级并落审计事件）；当前 turn 消息永远直读不投影；gate 增「投影滞后 N 轮时上一 turn 可召回性」断言。

### F11（P1）manifest 有空位字段、artifact 存储经济未算——「固化实际交给模型的内容」每 turn 把 token 经济翻一遍

- 位置：§5.2（section 元组含「churn 计数」与「payload_ref」）；§0（「artifact 负责固化实际交给模型的内容」）。
- 依据与问题：「churn 计数」列了但全文无定义、无消费点——死列。payload_ref 与内联 payload 未决：若按 §0 承诺逐 turn 固化全部 section payload，durable 写入≈每 turn 一份完整上下文拷贝；§5.2/§9 对 artifact 去重（section 已有 content_hash，天然可内容寻址）、体积预算、保留窗口全部沉默。一个以 token 经济为卖点的平面，自身是最大的未入账 token 消耗者。
- 修复建议：① churn 计数给出定义与消费点（建议喂 §5.4 的 cache-break 归因），否则从 §5.2 删除；② 明文 payload 存储=内容寻址 blob（artifacts 平面）+ manifest 只存引用，去重免费获得；③ artifact 体积 gate（单 turn artifact 字节上界断言）与保留窗口策略行。

### F12（P2）「已付款未落行」的重复付费未入已知成本台账

- 位置：§1 作用力 7（承认外部 IO 与事务无原子性）；G-ctx8（只断言回滚后幂等重推，不断言零重付）；§6.4-8（「放弃分支零新增调用≠绝对零成本」只覆盖摘要弃分支一侧）。
- 依据与问题：解析相 ask 成功、提交前被杀 ⇒ 花费已发生、行未落 ⇒ 重推重付。这是可接受的决策（作用力 7 已声明），但 §6.4 只为摘要一侧做了措辞纪律，解析相一侧的同一事实没有落点；「判断可缓存⇒廉价」的经济叙事隐含花费被缓存封顶，崩溃重付是封顶外的洞。
- 修复建议：§6.4-8 或新增「已知成本台账」补一条：解析相 kill-after-IO 重付为已接受成本，量级=单批判断价×崩溃频率；收编 DP1 K1 措辞（「已计费，不做总量零成本承诺」）。

### F13（P2）latch「INSERT once」的并发首触发冲突策略未定

- 位置：§5.1（「INSERT once；UPDATE/DELETE 被触发器拒」；latch 参与前缀身份哈希）。
- 依据与问题：两个并发首触发竞争同一 latch 名：一个 INSERT 成功，另一个吃唯一冲突——读从现有值（adopt）还是失败当前 turn，未规定。latch 进前缀身份哈希意味着失败路径直接炸 fork/缓存身份；first-trigger-wins 的 adopt 语义不写明，「一次性 DDL 的关系形态」不算闭环。
- 修复建议：§5.1 补一句：冲突即 ON CONFLICT DO NOTHING + 回读采用现有值；gate：并发首触发恰一行、双连接读到同值。

### F14（P2）advisory 锁跨 IO 持有的同 set 头阻塞未在设计层记账

- 位置：§4.3（解析相 `pg_advisory_xact_lock(hash(查询×候选集))` 后做 typesafe_ask）；对照 DP1 §5 风险表（「长解析持 advisory 锁：只阻塞同 set 解析，不碰 events/会话锁——正是设计目标」）。
- 依据与问题：计划的结论正确但只答了「不阻塞什么」，没答「阻塞同 set 多久」：完全相同 (查询×候选集) 的并发解析在锁上头阻塞，等待≈单次判断时延（1.3–1.6s 量级）×前序批数。热查询场景这笔延迟无条文、无队列上限（typesafe.timeout_ms 只是单次上限）。
- 修复建议：§4.3 记一笔：同 set 并发解析串行化为已接受代价（去重收益换头阻塞），量级与上界写明；热查询成为真实负载时的出路（慢路 handoff 优先于锁等待）挂 §12。

### F15（P2）§14 遗留开放项漏掉的全部是真正的阻断项

- 位置：§14（「遗留开放项（非阻断）：stannum tokenize() 是否存在；r 定价目录的维护流程；效用遥测反事实评估的 fixture 设计」）。
- 依据与问题：三项确实非阻断；但按本审查，真正阻断级的开放项一个没进：判断点默认分支（F1）、span 身份与保留（F3）、解析相预算（F5）、拓扑（F6）。「非阻断」的标注会给后续 DP「设计已收敛」的错觉。
- 修复建议：§14 开放项表加「阻断性」列，F1/F3/F5/F6 以 P0 身份入表并指认编号。

## 建议的修订动作（设计稿 v3 入口，按性价比排序）

全部是几行话到一小节的量：

1. §4.5：存在性 Noul 缓存键补候选集维度（F2）+ 过滤点默认分支表（F1）——两处都是防「静默漏」的条文。
2. §4.7/§9：chunks 补 chunk_offset 列 + 被引用内容保留规则 + 回放 gate（F3）。
3. 新增 pg_typesafe 刻画 stage 与 runbook（镜像 §4.8 形态）（F4）。
4. §5.4 或新小节：判断调用经济——解析相花费闸 + (k, tier)→延迟账 + 首版 k 上限（F5）。
5. §10 gate 清单随 §5.4 修正回头改：G-ctx6 重写（F8），补 F3/F10/F13 的新 gate。
6. 交付排序合并表消 P 标签两说（F9）；§9 收编教程表形状、§5 复核状态落地、AGENTS.md 回写 IO 例外（F7）。

## 静态核验

- 被审文档基线：`docs/designs/v13-context-on-pg.md` 487 行，SHA-256 `783d5d42e1e29697f4a5a5dbcf4d00d187d576417d5a4a9b54c4902748b30b0b`。本审查未改动该文件。
- 本文件为新增（创建前已核实不存在）。未运行任何 DDL、gate 或 runtime 探针。
- 引用核验方式：全部条文引用逐字对照设计稿原文；计划层佐证（DP1 turn 台账、§5 风险表、M4 gate 表、§1.3 接口契约）来自 `docs/plans/v13-dp1-two-phase-advance-plan-2026-09-20.md` 对应章节实读；教程 ch4 表定义实读；`v12/schema/v12_schema.sql` 表清单以 grep 核实。
