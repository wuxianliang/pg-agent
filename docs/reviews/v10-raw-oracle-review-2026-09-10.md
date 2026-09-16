# V10-raw 设计稿 Oracle 复审（轮 1 条件冻结；轮 2 需修订——以轮 2 为准；轮 3 现状裁决——以轮 3 为准）

- **复审时间**：2026-09-10（Oracle chat `v9-设计方案-6BA4EB`，mode: review）
- **对象**：`docs/designs/v10-raw.md`（416 行版；P1 修订后 419 行）
- **上游**：主设计思路审核（同 chat，S1–S6 裁定 + Q1–Q3 答复）→ 导出 `prompt-exports/oracle-plan-2026-09-10-223443-v9-6ba4eb-b0b6.md`

## 总体判定

方案忠实度高——S1 修正案措辞、S2 四条硬理由与"普通表+稳定视图"形态、Q1 三层序列化边界、Q3 阶段–事务归属表（含"Bind 外部部分不存在"）、S4 取舍表（吸收 2 / 模式确认 2 / 拆分 1 / 抛弃 5）、硬规则 1/2、渲染 effect 幂等缓存、两条新不变量候选、§7.2 清理项全表、P0–P3 路线图与 fixture 编号映射——全部落实，无遗漏。18 条不变量编号+语义原样引用；四平面归属与不变量 4/9/12/13/16/17 衔接未发现矛盾。设计稿形态达标（对标 v8.md 叙事密度，未误写为实现规范）。**无 P0。**

## P1（已修订，2026-09-10 落位）

- **P1-1 RecoveryState 载体缺失**：§1.4 重绑表补行（→ session 控制行字段 `ptl_streak`/`recovery_tier_floor` 暂名；stats 跨 session 不适合承载）+ §5.1 点名。落位 v10-raw.md L71 / L273。
- **P1-2 emergent 消费-失败语义未声明**：§2.4 补"消费即删随 assemble 事务提交生效；Execute 失败不恢复已消费项（与 Astra 一致；emergent 是易失提示，丢失降级为无前瞻上下文，不产生语义错误）"。落位 L124。

两条 P1 修订完成后即满足 raw 设计稿标准，可进入 v10-dev 撰写。

## P2（留 v10-dev）

1. **P2-1**：§1.4 "SectionKind 13 种"与 `section_types.rs` 实际 15 kind 不符——改为"13+ 种，以仓库为准"或写 15 并同步修订 digest。
2. **P2-2**：§2.4 "不变量 13 扩展到目录内容"措辞与 §7.1 零修改声明的张力——改为"不变量 13 的 generation 绑定**适用**于目录内容（目录行携带 generation_id）"，从"扩展不变量"改"应用不变量"。
3. **P2-3**：论文 §3.8 churn 计数器与 §5 八条 trace alert 规则未裁定——v10-dev 显式取舍（建议 churn counter 入 stats 字段、alert 规则做 explain_assembly 之上的视图/函数，均 P3）。v10-raw §9 P3 已加防误读注记（L402）。
4. **P2-4**：§4.2 层 2 时点列"Bind 阶段（或其上游…）"改为"渲染 effect 内（产物落表）；Bind 阶段仅消费产物行"，消除"Writer 是否在 Bind 事务内跑"的误读。

## 通过项（简记）

交叉引用 §2.3→§5.2、§2.8→§6、§3.2→§7.2、§4.3→§5.1、§5.5→§7.2、§2.9→§7.1 全部成立；路线图-_fixture 映射 P0{1,2,5,9}/P1{3,4}/P2{6,7}/P3{8} 无悬空；术语全文统一。

## 审核链

- 三源研究：`docs/analysis/v10-sources-digest-2026-09-10.md`（contextpipe 论文+Astra 实现 / poml 论文+TS 实现 / pgAgentOS SQL 盘点，三路并行探针）
- 主设计思路审核：Oracle `v9-设计方案-6BA4EB`（S1 成立+修正案 / S2 修订 / S3 成立+硬规则 / S4 修订 / S5 成立 / S6 成立；Q1 三层序列化 / Q2 普通表 / Q3 阶段–事务归属表）
- 成稿撰写：Claude Opus (1M) max 会话 `落笔 v9-raw 设计稿`（按决策 E 骨架 + §6 写作顺序）
- 本复审：同 Oracle chat，review mode

---

# 第二轮复审（2026-09-11，技术可行性与设计正确性镜头）

- **复审时间**：2026-09-11（Oracle chat `v9-设计方案-6BA4EB`，review mode，轮 2）
- **对象**：`docs/designs/v10-raw.md` P1 修订后 419 行版
- **镜头**：轮 1 查方案忠实度；轮 2 直攻 PG 技术可行性与设计正确性（不做状态机级 MUST/MUST NOT 审）

## 本轮总判定：需修订（撤销轮 1 的技术冻结推断）

方向无需推翻：普通表＋稳定视图、数据库持有决策真相、事务外宿主执行、POML 组件插件、唯一 provider Serialize 权威均可保留。但 11 条 P1 架构边界与错误技术断言须先在 raw 阶段修正。**可并行开展性能 spike 与协议探索，但不应把 419 行版作为已冻结输入进入 v10-dev。**轮 1 的两条 P1 文字修复确已落位，但只关闭原有局部问题。

## Oracle 自我纠正（轮 1 错误技术判断，源自上游方案而非成稿执行）

1. **§1.2“四条硬理由”不成立**：information_schema 与大量 PG 系统视图本身就是 SQL 视图，并非统一由 C 实现；扩展可提供自己的目录式视图。结论（普通表＋稳定视图）保留，理由须改为：不占用核心保留命名空间、避免内核耦合、底层表管版本与授权、视图提供稳定接口（→ P1-11）。
2. **§5.4 `send_message()`“非原子”批评错误**：它是 PL/pgSQL 函数，各条 DML 在调用者事务内，并非三次独立提交；真实缺陷是并发编号分配（`MAX(turn_number)+1`）缺串行化/幂等协议。需同步更正 digest（→ P2-4）。

## P1 清单（应改：raw 阶段先定架构边界）

| # | 落点 | 问题 | 修复方向 |
|---|---|---|---|
| P1-1 | §1.2/§2.2/§2.4/§2.5 | `plan_assembly` 等自行读表却被标 IMMUTABLE——对可变表读取不成立（常量折叠/缓存风险），非 VOLATILE 函数也不能做 spill INSERT 等写入；且同事务≠同快照（READ COMMITTED 每语句新快照） | 拆三层：STABLE 读取层取一致输入快照 → 仅接收值参数的 IMMUTABLE 计算核 → VOLATILE 控制入口做状态变更与 seal；输入值/版本入 assembly manifest |
| P1-2 | §2.4/§2.6/§2.9/§8-2 | EXPLAIN-only 声称跑完整管道无副作用，但正常管道冻结 latch、删 emergent、写 spill；候选不变量 1 要求与 decision seal 同事务，EXPLAIN-only 无 seal——规则冲突未定义 | 定义 execution/inspection 双模式共享纯计算核；inspection 只模拟状态变更；“与 seal 同事务”仅约束 execution 模式。同时给出 Bind 禁外部 I/O 可判定边界（库表/TOAST=内部；网络/live workspace/外部工具/宿主 handler=禁止；禁经 foreign table/dblink 藏外部调用） |
| P1-3 | §2.2/§3.2/§4.3 | 前置 `recall`/`poml_render` 无法接入 v8 ledger：effect 须属 step 的密封 batch/slot，初始 decision batch 只有一个 LLM slot——decision seal 之前/会话创建之前的准备工作无 batch 归属，形成依赖环 | 在账本中明确 preparation 工作的归属/密封/完成边界，仅输入备齐后进 decision seal；列为 v10 协议增量，不得宣称“仅新增 kind 零改动接入”。“不在热路径”仅对缓存命中的慢变模板成立，`<query-result>` 动态数据路径不能靠该假设省略 |
| P1-4 | §1.4/§2.5/§3.1/§5.1 | PTL 后 tier 升级如何生效未闭环：v8 retry 复用原 effect_id/request_hash（请求不可变），重装改变 payload 即破坏合同；原 step 终态后聚合规则也不允许直接新建决策 | PTL 重装定义为有明确失败收束/继续条件的新 step/新 effect，显式列出对 v8 失败聚合的版本化修订；裁定前不宣称“自动升级重试已兼容” |
| P1-5 | §5.2 | session 创建时冻结 `catalog_generation` 违背 v8 按 step 绑定 generation 的规定（新 assemble 绑新 active generation、旧 step 保留旧代），且与本稿 §1.2 第 3 条自相矛盾 | session 创建只冻结 persona 内容版本与有效参数；generation 继续在每个新 step/effect 创建时绑定 |
| P1-6 | §4.4/§4.5 | 硬规则 2（注册键加 generation 前缀）不能解决 poml 全局 alias 注册：Registry 按全局 alias 判重查找（base.tsx:848–938），前缀名不使文档 `<schema>` 自动按代分派，保留公共 alias 又在预加载时冲突 | 优先按 generation 隔离的 Node 渲染进程（每环境用原公共标签名，旧代保留至引用释放）；若同进程共存须另行证明 generation-aware 解析层。修订轮 1 硬规则 2 |
| P1-7 | §4.3/§4.6/§6/§8/§9 | 渲染缓存键 `(doc_hash, data_hash, presentation)` 缺实现身份：升级 `<schema>` 实现后源文档与数据不变，仍命中旧产物——修复已发布而 prompt 不变 | 引入 `render_profile_digest`（实现 digest+POML/Writer 版本+渲染配置+依赖闭包）入缓存身份，Bind 核验产物 provenance，跨代共享仅限相同渲染身份 |
| P1-8 | §1.3/§2.4/§8-4 | spill 定位 projection 可清理，但缺失时发 placeholder——同一权威输入产出两种 prompt，违反 v8“缓存命中与否不得改变合同结果” | spill 明确不可变源引用与保留规则：可重建则确定性重建同字节；不可重建按持久 artifact 管理；fail-open 仅限 manifest 声明的可选来源。已 seal 请求重试必须复用冻结 payload |
| P1-9 | §2.7/§5.4/§9 | ForkPrefix 只存 section 字节+sha256 不足以共享：父前缀可能含子会话不可见工具/不同 persona/provider 配置；provider 实际缓存前缀≠section 字节 | 仅对经子会话授权+persona/工具面+provider 缓存身份校验后兼容的 canonical wire prefix 启用共享，否则退回普通装配并记原因；cache probe 是观测不是命中保证 |
| P1-10 | §1.3/§2.6/§6/§7.2/§8-1 | “plan/trace 确定性”未与 v8 semantic observable_trace 划界：ANALYZE 含实际 cache usage/耗时等观测值，按整条 trace 比较会把合法观测差异判为 portable 失败 | 命名为独立的 assembly conformance：只比较完整冻结输入导出的 request+canonical decision trace；耗时/usage/身份按 observational/audit 留存 |
| P1-11 | §1.2/§10 | “四条硬理由”中“系统视图由 C 实现、扩展无法注册”属技术错误（见上文自我纠正 1） | 保留结论、重写理由 |

## P2 清单（留 v10-dev，保留设计位）

| # | 落点 | 问题 | 处置 |
|---|---|---|---|
| P2-1 | §2.2/§2.4 | 同桶 stats 行锁串行化同 (model, query_source) 完成事务（非全 workspace），无吞吐评估 | v10-dev 评估并发；必要时分片桶或 completion 原子记录+异步版本化快照 |
| P2-2 | §1.3/§2.2/§2.3 | fold 冷缓存路径无增量 projection 衔接说明 | 明确带 cutoff/fold 版本/依赖 manifest 的可重建 projection，正常路径只折增量 |
| P2-3 | §2.2/§3.1 | 大 payload 落库非 PG 固有限制，但 claim/heartbeat 反复解 TOAST 有成本 | 按测量选内联/分离 artifact；request_hash 覆盖 canonical 内容而非存储字节 |
| P2-4 | §5.4 + digest §三 | `send_message()` 非原子批评错误（见自我纠正 2），同步更正 digest | 改为“并发编号分配缺串行化/幂等协议” |
| P2-5 | §1.4/§2.4/§4.2 + §5.4 | 轮 1 三条文字遗留（SectionKind 实为 15 种；“扩展不变量 13”改“应用”；§4.2 Writer 时点改“渲染 effect 内执行落表，Bind 仅消费”）＋ §5.4 把 RLS/角色矩阵归于不变量 16 不准确（16 只区分 workspace_id/handle；应引 §2/§2.1 与不变量 12/17） | 一句话级，v10-dev 顺手修 |

## 专项核验通过项

- **A4 locus=ts 成立**：v8 本就有 sql|ts|python|swift|compat 五 locus（v8.md §2.4），非新增第三类；仅需明确 locus 属插件实现路由、非 effect kind、不允许在控制事务内跑 TS。未解决问题是 P1-3 账本归属。
- **C1 轮 1 修复落位**：RecoveryState 行/emergent 消费-失败语义/§9 P3 注记均落位；assemble 中段 crash 的 DELETE 回滚无新原子性问题；assemble 提交后 crash 从持久化 effect 恢复、payload 已冻结。注：pg-agent 已对 emergent 消费-失败作出自身裁定，不宜再引用为“与 Astra 一致”的完整证明。

## 进入 v10-dev 的结论

可并行开展性能 spike（P2-1/2/3）与协议探索（P1-3/P1-4）；先在 raw 中确定纯计算/状态应用边界、preparation 与 PTL 协议归属、正确世代隔离（P1-5/6/7）以及 spill/ForkPrefix/比较合同（P1-8/9/10），再进入 v10-dev 实现规范撰写。

## 轮 2 审核链

- 同 Oracle chat `v9-设计方案-6BA4EB`（review mode，轮 2）
- 导出：`prompt-exports/oracle-review-2026-09-11-074559-v9-6ba4eb-1adb.md`

---

# 第三轮复审（2026-09-16，现状裁决与开发计划完备性镜头）

- **复审时间**：2026-09-16（Oracle chat `new-chat-D11B11`；review mode 因 docs 未入 git 拉不到 diff 上下文而失败，改 chat mode 执行，审核纪律不变）
- **对象**：`docs/designs/v10-raw.md`（419 行版，即轮 2 审核对象——自轮 2 后未修订）
- **时间点背景**：v8-dev 已冻结（L4 终裁 0 P0/0 P1，遗留 F-03/04/07/08 + F-09/10 nit + R11 两条）；v9 context_early 规格已冻结（09-15）并在实现（独立轨道、v6 代码线）；今日 2026-09-16
- **镜头**：轮 2 遗留状态裁决（含对轮 2 自身断言的复核）、冻结版 v8-dev 对账、v9 共存边界、路线图作为开发计划的完备性

## 本轮总裁决

**当前 419 行版不能作为已审定输入进入正式的 v10-dev 撰写。**可以继续协议草案、性能 spike 和目录骨架工作，但不能在实现规范中把未闭合边界写成既定事实。

主会话现状判断基本确认但需三处校正：

1. 轮 2 的 11 条 P1 均未关闭、5 条 P2 均未关闭；但"未关闭"不等于轮 2 的全部诊断和处方必须原封不动维持。
2. 预核验中的 `send_message()` 属于轮 2 P2-4，不是第 12 条 P1；轮 2 P2-1/2/3 分别是 stats、fold、大 payload 的性能与存储问题，不能与轮 1 的文字遗留重新编号混用。
3. 本轮修订轮 2 的若干处方：`STABLE` 读取层不是必选方案、也不能承担实时授权锁定；不能把新增 preparation step/batch 当作冻结 v8 已支持的挂载点；每 generation 一个 Node 进程只是候选实现、不是 v8 既有要求；"系统视图由 C 实现"的事实纠正维持但降为 P2。

此外，冻结版 v8 已经实质改变了部分旧遗留的解释：**不存在持久化的 planned 无-effect step；F-03/F-04/F-07 的核心规范已写入正文；F-08 必须区分命令清单、receipt 合同与 effect kind。**当前 raw 仍按旧摘要规划，不能仅在原路线图上加几项测试后直接推进。

## P0

未发现有充分证据支持的 P0。当前缺陷主要表现为架构合同未闭合、继承关系错误和实施依赖缺失，适合按 P1 阻塞计划准出处理。

## 轮 2 遗留逐项裁决

- **R2-P1-1（纯计算/输入冻结/状态应用混淆）——修订**：问题维持，三层方案不能照搬为强制函数分类。冻结 v8 `§3.3` 已规定 fold/recall/catalog/grant/policy 绑定同一 manifest hash——manifest 不是 v10 新发明；`§2.1` 授权线性化点要求实时授权及锁/CAS；`§2` 事务隔离级别前提强制 READ COMMITTED 重扫描协议。修复：保留三类职责但不强制对应三个固定 volatility 层；需要行锁/实时重验/CAS 的 capability/control 路径不能塞进 STABLE 读取函数；扩展既有 assemble manifest 冻结确定性计算消费的值；明确冻结计算输入不冻结授权有效性（seal/dispatch 仍执行当前授权门）；raw 只定职责与时序，函数签名留 v10-dev。
- **R2-P1-2（EXPLAIN-only 副作用合同）——维持并补充**：Bind 表格称"全部是数据库读取"但同条目含 emergent 消费；正常路径还冻结 latch、写 spill、写 plan/trace；EXPLAIN-only 不创建 step 却复用绑定 (session_id, step_id, …) 的审计产物模型；渲染产物缺失时 inspection 行为未定义。冻结 v8 `§3.3` 明确 inspect 只读、`§3.1.2` 规定写命令 receipt 合同。修复：execution/inspection 共享计算核、不共享写入行为；inspection 若完全只读则 plan/trace 作为返回值，若要持久化审计则明示为有审计写入的独立操作；为无 step 的 inspection 定义独立身份；缺已物化输入时返回明确的不完整/需准备结果；保留 I/O 边界（本地表/TOAST 可读，foreign table/dblink/live workspace/宿主 handler 禁止）。
- **R2-P1-3（preparation 缺合法归属）——修订**：账本问题维持；收紧可选方案合法性。冻结 v8 `§3.1`/`§3.1.2`/`§3.2.2`：logical step 是一次模型决策及后续工具批次，effect_submit→create_effect 不提供无 step 创建通道，已 seal batch 不能加成员——"session 级 preparation batch""已有 step 的专用 preparation slot"都不是现成接入方案，采用即协议增量。修复：分类 DB-local 已授权读取（可进 Bind 不必新增 effect）与事务外检索/TS 渲染（必须有合法持久化执行归属）；raw 选定方向——首版只消费预先发布已完成物化的 artifact，或显式扩展 v8 preparation 协议；若扩展至少列出对单活跃 step/seal/取消/unknown/driver switch/generation drain 的影响；删除"零改动接入"暗示；动态 `<query-result>` 不能以"不在热路径"规避。
- **R2-P1-4（PTL 后重装）——修订**：冲突维持；轮 2 的"新 step/new effect"只解决身份问题一半。`§3.2.1` 规则 4 及末段：terminal failure 即时派生 session failed，不存在失败后再新建 step 的跨 step 窗口。修复：区分 seal 前本地预算重算与 provider 已返回 PTL 后的恢复；最短范围缩减方案是首版只支持 seal 前升级、provider PTL 按既有失败合同处理、自动跨调用恢复明确延期；unknown 不能靠 PTL 计数推断为已知失败。
- **R2-P1-5（session 永久冻结 catalog generation）——维持**：`§0` 不变量 13 + `§4` 明确"新 assemble 绑新 generation、旧 step 保留旧代" + `§6` Conformance 8 有对应断言。修复：session 固定 persona 内容版本和有效参数；每个新 step/effect 固定实现 generation。
- **R2-P1-6（generation 前缀不是 alias 隔离证明）——修订**：问题维持；撤销将进程隔离当成唯一或既有方案的推断。`§4` 要求 digest readiness 与 generation 绑定，但不规定一代一个 OS 进程；实际登记键是 (generation_id, identity, plugin_version, handler_name)，不是 raw 转述的 implementation_version；同一不可变 implementation 可由多个 generation 共享。修复：raw 规定必须证明的结果——解析和执行不跨渲染身份污染、native/compat 同样受约束；候选包括独立进程、独立 registry 实例、经验证的 generation-aware resolver，由小型协议验证决定；compat 不得成为旁路。
- **R2-P1-7（渲染缓存身份缺实现及依赖闭包）——维持**：引入渲染 profile/实现依赖摘要及 provenance 校验，贯穿缓存、产物、比较输入和 fixtures；跨 generation 复用依据相同渲染身份。
- **R2-P1-8（spill fail-open 改变请求）——修订**：问题维持；"optional 即可 fail-open"需加冻结条件。可重建源必须重建同字节；不可重建按持久 artifact 保留；optional 只意味着允许在一次新的装配决策中选择降级，选择本身进冻结 manifest/decision trace；同一已冻结 manifest 的重放不能因 artifact 今天丢失就换 placeholder；已 seal 请求只复用冻结 payload。
- **R2-P1-9（ForkPrefix 字节完整性 ≠ 共享资格）——维持并区分内容复用与 provider 缓存复用**：`§3.3` 稳定 parent_through_seq、`§2.2` 第 4 条 grant 仅按 delegable 不可变 slice 条件复制。修复：明确共享的是不可变内容 artifact 还是 provider canonical wire prefix（后者必须在 Serialize 层验证）；校验前缀实际依赖的授权、内容及渲染/provider profile；不兼容则普通装配并记录原因；补负向 fixture；cache probe 仅为观测。
- **R2-P1-10（assembly 决策比较与运行观测未分离）——维持并补 portable identity 排除规则**：独立定义 assembly conformance（完整冻结输入 → canonical request + canonical decision trace）；原始 plan/trace 行不直接充当 portable 比较对象；usage/latency/cache 命中及执行身份留 observational/audit 面；stats 中历史观测值比较时必须冻结为输入；输入还应覆盖 tokenizer/计算规则/profile 版本。
- **R2-P1-11——修订为 P2**：事实纠正维持，但结论（普通表＋稳定视图）本身正确，错误理由不决定运行架构。

## 本轮新增 P1

- **R3-P1-1 冻结基线对账过时，尤其 R11 已不存在原来的问题域**（§3.3、§7.2）：冻结 v8 已明确无 effect 的持久化 planned step 不存在（`§3.1`、`§3.1.1` begin_switch guard (iv)、`§3.1.2` 初始 decision seal、`§3.2.1` 规则 4/5）；若 preparation 新增可持久化前置工作，其 switch/drain 屏障必须重新论证。§7.2 还把若干已写入冻结规范的规则描述成规范仍缺失。修复：将历史遗留清单改成"历史问题 → 当前冻结条款 → 剩余文档/实现验收 → v10 触碰范围"；R11 改为现有合同的回归检查（"不得重新引入"回归断言；规则 4 精确继承：混合关闭 not_retry_eligible → FAILED_TERMINAL，全 budget-exhausted 是另一 code）。
- **R3-P1-2 Feedback 不能无条件挂在 complete_effect 事务上**（§2.2、§2.4、§8-9、§9 P0）：冻结 v8 的 completion 含非终局 stream observation、拒绝/receipt replay、quiescing 下经 reconcile、unknown 经 repair（`§3.1.2` complete_effect 命令表与 pending observation 排除段、`§3.2.2` grammar (0)(iii) 受限 observation 写集）；新增 recall/poml_render 也走 completion，不能因此进入 LLM usage 样本。修复：raw 明确 Feedback 触发谓词、样本身份和重复抑制；observation/拒绝/receipt replay/旧 attempt 不触发 usage/EMA/emergent 更新；fixture 9 补 observation、重复 completion、repair/reconcile、非 LLM effect 对照。
- **R3-P1-3 §9 是功能分期，尚不是依赖与验收闭合的开发计划**（§8、§9）：F-08 不是唯一前置依赖（manifest/授权、preparation、PTL、generation/render identity 都约束前面交付）；F-03 放 P3 易被解读为 P0 catalog/Bind 可先不满足冻结授权合同；F-04 和 fixture 8 放 P3 晚于依赖 canonical bytes 和完整预算分配的管道实现；P0 未声明是 schema-only/固定输入适配器/完整管道；prompt 装配 compat 门闩放 P2 但 P0 fixture 1 已要求双运行时执行；未列轮 2 的三个性能 spike、两个协议探索和 raw 准出门；**v8 规格冻结 ≠ 可运行 v8 基线已就绪**——计划必须说明接入哪个已验证基线或把其建设列作依赖。修复：用"前置合同/实现依赖/阶段交付/验收工件"补齐路线图；§9 增加 raw → 复审 → v10-dev 的明确准出条件。

## P2（遗留、降级与边界）

- **R2-P2-1/2/3 维持**：stats 同桶并发、fold 冷路径增量 projection、大 payload 存储与读放大——三个 spike 落位（不预判 heartbeat 必然解 TOAST）。
- **R2-P2-4 维持事实纠正**：撤销 send_message "非原子"批评，改并发编号/幂等缺口，同步修 digest 防回流。
- **R2-P2-5 维持**：13/15 kind、"扩展→应用"不变量 13、Writer 时点、RLS 错引不变量 16（应引 §2/§2.1 与不变量 12/17）。
- **R2-P1-11 降为 P2**（见上）。
- **R3-P2-1 新增**：v10 缺自身与 v9 的共存边界声明；命名检查证据精度需更新（v9 spec §8 只写"对照 v1–v7"，不能进一步证明成"W1 已自动验收完整 v1–v9 命名无冲突"；raw 应补核查范围/清单引用）。
- **轮 1 P2-3（churn/alert）维持延期**：v10-dev 待裁定清单写明采纳/延期与验收产物即可。

## 冻结版 v8 对账结果（要点）

- **18 条不变量编号未变，但旧简写不再充分**：不变量 2 需继承 attempt 权威/派生快照括注；3 需继承 job lease 跳过与 FORCE_JOB_TAKEOVER 限制；4 宿主 handler 本身受限（Writer 时点需改）；7 preparation/PTL 必须明确继承；8 preparation 可恢复进度必须来自持久化账本；11 optional spill 降级不适用于授权失败；12 RLS 不等于全部能力授权、新增控制函数写权限需设计；16 §5.4 归因错误；17 括注含 slice 撤销/租户一致/membership，snapshot 不豁免 seal/dispatch 实时门；18 不只是"有 hash 即可"。
- **§3.1 引用方向准确但旧中间态描述失效**：不存在可持久化的无 LLM slot step。**§3.2** "新增 kind"不自动获得 batch/slot/首个 attempt 合法创建路径。**§3.3** 稳定历史继承不自动授权父 prompt 前缀。**§4** 实际用 plugin_version，共享 implementation 的成员模型不能简化为每代独立实现实体。**§5.2** prompt 门闩不能替代 dispatch 门闩——prompt bytes 出自数据库只证明装配来源，不证明 host 已在外部执行前落盘 dispatch；v10 fixtures 必须继承 passed/failed/blocked 口径。**receipt 对账命令不对账新增名字**：只读格式化函数不当然新增 receipt，effect kind 不是命令。
- **F 项与 R11 集合一致、现状说明不一致**：F-03/F-04/F-07 的核心规范已写入冻结正文（§2.1 授权传播、§1.3 唯一 JCS profile + §6 Conformance 10、§2.2 状态迁移表），v10 记账应改为"继承并验证适用路径/增加自身 vectors/保留交叉引用"；F-08 分两步（入口清单现在做，最终 receipt 覆盖在命令定型后收口）。

## v9 共存裁决

- **"无关联"写在 v9 spec §0，不在 v10-raw**——v10 需补自身边界表（基线/主对象/核心职责/generation 域/gate 语义/执行协议六维对照：v9 是预建-标脏-刷新-新鲜度诊断，v10 是选择-绑定-优化-序列化-反馈；ctx_gate 返回建议 ≠ 已执行刷新或屏障，不能当现成的 v10 freshness barrier）。
- **吸收经验不搬权威表**：依赖 manifest/内容摘要/provenance、精确失效而非无差别刷新、inspection 显示 source_version/stale/drift/needs_preparation、"准备过程中源变化/迟到产物/未受影响来源不变"测试。两条红线：freshness 与 authorization 正交；新鲜度变化不改写已 seal 请求。
- **排序**：v10 无需等 v9 W1–W9 全落地，两轨并行；正式 v10 P0 实现受自身准出与 v8 接入基线约束；只有明确决定消费 v9 pack 时才加单向 adapter 与集成 gate，不应默认进 P0 范围。

## 路线图与 fixture 裁决

- 编号映射（P0{1,2,5,9}/P1{3,4}/P2{6,7}/P3{8}）无悬空，但覆盖和时序有缺口：fixture 2 写集不清、4 正在固定错误的无条件 fail-open、6/7 缺 render profile、9 缺 completion 分流和重复抑制、8 应在预算计算核可执行即运行而非 P3 首跑；persona 参数物化、ForkPrefix、preparation、PTL、generation 切换、alias 隔离、真实 compat prompt 门闩缺验收归属。
- **最短依赖图**：冻结 v8 对账 + 入口/对象清单（manifest/实时授权/双模式；preparation 与 PTL 协议裁定；render identity 与 alias 隔离方案）→ raw 修订 + 轮 4 复审 → v10-dev → v8 runtime 接入门 → P0 → P1 → P2 → P3。并行支线：stats/fold/payload 三 spike + POML resolver 隔离小验证。阶段调整无需推翻 P0–P3：P0 明确最小 source 集或固定输入 adapter、落 manifest/计算核/双模式/seal 接口、授权与 canonical 基础验收、fixture 1/2/5/9 + 首版 8；P3 不能才首次补安全和 canonical 合同。

## 从当前状态到 v10-dev 的最短修订路径

**A. 必须改在 raw（9 条）**：① 纯计算/状态应用/输入冻结边界 + 引用既有 manifest + 保留实时授权门；② execution/inspection 定义（写集、身份、缺输入行为）；③ preparation 归属方向裁定 + 删零改动承诺；④ PTL 自动恢复范围裁定或明确延期；⑤ generation 绑定改正 + render identity 与 alias 隔离义务；⑥ spill/ForkPrefix/assembly 比较面合同缺口关闭；⑦ Feedback 触发、去重、多入口关系；⑧ F/R11 当前状态更新 + 事实错误修正；⑨ v9 边界、v8 接入依赖、阶段验收与 raw 准出门写入。

**B. 可下放 v10-dev**：DDL/FK/索引/RLS/函数签名；已选 preparation/PTL 方向的完整状态转移、receipt、crash 边界；manifest/trace 字段 schema 与 portable 投影；worker 路由/readiness/回收细则；spill 重建清理策略；各 fixture 完整输入输出与 capability 分派；churn/alert 取舍。

**C. 转 spike/协议探索**：stats 并发 digest spike（stats 实现方案冻结前）；fold 冷热路径 spike（projection 冻结前）；大 payload spike（ledger 存储接入前）；preparation 协议探索与 PTL 协议探索（**raw 准出前需方向裁定**）；POML 隔离验证（raw 需定方案或明确验证门）。

**D. 需要轮 4 复审**：本轮修订会改变实质架构边界，不是编辑性修复。轮 4 准出条件：轮 2 各项逐一有可追踪处置；冻结 v8 的 manifest/授权/step/seal/终态/generation/receipt/capability 矩阵未被错误简化；preparation/PTL/Feedback 无未定义归属或入口分流；正文、§8、§9 对同一行为只有一份答案；剩余 P2 有明确承接阶段。**轮 4 通过后即可正式进入 v10-dev；无需等待 v9 全部实现，也无需先完成全部性能 spike。**

## 轮 3 审核链

- 上下文选区：v10-raw.md / 本审核文件 / v8-dev.md（871 行冻结版）/ v9-context-early-spec-2026-09-15.md / v10-sources-digest-2026-09-10.md（manage_selection 全文 5 件）
- 主会话预核验（11 条 P1 未落修的逐条锚点）已并入 Oracle 复核
- Oracle chat `new-chat-D11B11`（chat mode；review mode 因 docs 未入 git 无法生成 diff 上下文而失败）

---

# 第四轮复审（2026-09-16，轮 3 修订版定点验收 + 全镜头）

- **复审时间**：2026-09-16（Oracle chat `new-chat-D11B11` 轮 4；Loop Orchestrate turn 1 的冻结检查）
- **对象**：`docs/designs/v10-raw.md` 轮 3 修订版（419→456 行，Orchestrate 会话 `0BCF649D` 执行）
- **总裁决**：**0 P0 / 1 P1 / 4 P2**——原 13 条 P1（R2-P1-1..10、R3-P1-1..3）全部关闭；preparation/PTL 的首版范围收缩被认定为有效修复而非改名保留。尚未准出。

## 轮 2/3 P1 逐条裁决（摘要）

R2-P1-1 关闭（L88–99、130–136、153：三职责分离 + 既有 manifest + 实时授权门）；R2-P1-2 关闭（L155–161 等：双模式共享计算核不共享写集、inspection 独立身份/缺输入行为/零持久写集）；R2-P1-3 关闭·收窄范围（L101–103、190–192、229–233、437：首版只消费预发布完整 artifact，发布为独立对象管理命令与独立幂等域）；R2-P1-4 关闭·收窄范围（L70、147–149、407、437：仅 seal 前升级，terminal failure 后无原 session 自动新建 step 窗口）；R2-P1-5 关闭（L298–308、401）；R2-P1-6 关闭·验证门保留（L250–256、269–271、402、438）；R2-P1-7 关闭（L231–233、348、402–403）；R2-P1-8 关闭（L55、134、400）；R2-P1-9 关闭（L163–167、407、426）；R2-P1-10 关闭（L344–350、397）；R3-P1-1 关闭（raw 四列对账 L194–198、362–378；digest 残留降 P2-3）；R3-P1-2 关闭（L99、105–107、405：合格 LLM 成功终局谓词 + 采样 profile 冻结 + effect 去重，排除 observation/replay/旧 attempt/失败 unknown/repair/reconcile/终态 drain/非 LLM）；R3-P1-3 关闭（L397–407、411–439）。R2-P1-11、R2-P2-4 关闭；R2-P2-5 raw 基本关闭（digest kind 数量未同步）；R2-P2-1/2/3 已落 spike 计划位（L434–436）非技术关闭；R3-P2-1 关闭（L336–340、380–393）；churn/alert 显式延期有承接（L439）。

## 新发现

- **R4-P1-1（唯一阻塞）emergent 的"下一 turn"与冻结 v8 turn/step 生命周期不一致**（§2.2 L105–107、§2.4 L132、§8 L399/405、§9.2 L425–426）：冻结 v8 的 turn 不是一次 LLM 调用——§3.1 logical step 定义、§3.2.1 聚合规则 6（final_tools=true 后 turn 未关、同 turn 下一 decision step）、§3.2.1 末段 + §3.1.1 finish_session（decision_only 关闭后 completed、terminal 不允许新工作）。按 raw 字面："下一 turn"在 session 内不可达（同 turn 下一 decision step 不满足；turn 真正关闭时 session 又正常收束）。修复方向：① emergent 生命周期 = 生产 effect 完成后同 session 下一次符合条件的新 decision step 的 execution assemble（明确≠v8 下一 turn）；② 消费资格以逻辑装配 occurrence/目标 step 关系表达，produced_seq 仅溯源，物理事件 seq 不隐式等同装配轮次；③ 明确 inspection 不消费、assemble 回滚不消费、已 seal effect retry 不重新装配不再次消费、关闭 turn/cancel/terminal 后无后继装配项的丢弃/失效；④ "统计采样一次"与"是否存在可投递 emergent"分离（关闭 decision 计入统计但不承诺消费）；⑤ fixture 3/9 补 decision→tools→同 turn 下一 decision、decision_only 关闭、retry/inspection/回滚、观测事件插入不改资格。
- **R4-P2-1**：needs_preparation 控制入口返回/重发约定（§2.2 L101、§3.2 L188–192、§8 L407）——可恢复前置输入不足而非自动 INFRA_ASSEMBLY_FAILED；不新增 session 等待态；参照 v8 §3.1.2 同 command ID 返历史 receipt、§4-4 NO_ACTIVE_GENERATION"保持控制态+显式 yield"模式；新执行请求命令身份与调用方责任由 v10-dev 定型。
- **R4-P2-2**：发布幂等 fixture 拆两组（§3.2 L191、§8-7 L403、§9.2 L425/427）——P0 基础组（同 publication ID 同内容重放/异内容冲突/授权与跨 workspace 隔离/发布与 receipt 原子性/响应丢失）；P2 渲染扩展组（render profile/依赖闭包/alias readiness/同渲染身份异产物冲突）。
- **R4-P2-3**：digest §一/§四 仍保留已撤销的当前状态断言（13 种 kind、F-03/F-04 缺失描述、R11 planned step 存续）——加历史标记或同步现状。
- **R4-P2-4**：§2.5 L151"稳定 id 破并列"应明确为冻结的逻辑 section/source identity 或规范键，不得依赖物理行 ID/locale/无序查询；补物理 ID 扰动用例。

## v8 对账 / v9 共存 / 路线图

- v8 对账九面无回归（不变量 2/3/4/9/12/17、step/seal/ledger、PTL/retry/终态、fork/workspace、generation/readiness、dispatch 门、receipt、F/R11）。raw §6 身份映射是新增 assembly 比较面设计，不反向改写 v8 normalize——v10-dev 应分别给投影 schema。
- v9 共存要求已满足（§7.4 L380–393：两基线/两类对象/两个身份域/gate 语义/队列不借用/吸收清单）；两轨并行维持。
- 路线图 fixture 映射 P0{1,2,5,9,首版8} / P1{3,4,5扩展,C} / P2{6,7,D扩展} / P3{全集回归}，无悬空；剩余受 R4-P1-1 影响。

## 结论

需要轮 5 定点复审（emergent 生命周期一致性 + 已关条目防回归，不重开 preparation/PTL 范围裁定）。修正后无需等 v9 实现完成、无需先跑三个 spike，轮 5 达 0 P0/0 P1 即可进入 v10-dev。

---

# 第五轮复审（2026-09-16，emergent 生命周期定点 + 防回归）——**raw 准出**

- **复审时间**：2026-09-16（Oracle chat `new-chat-D11B11` 轮 5；Loop Orchestrate turn 2 的冻结检查）
- **对象**：`docs/designs/v10-raw.md` 轮 4 修订版（456→468 行，Orchestrate 会话 `B8BAC893` 执行）
- **总裁决**：**0 P0 / 0 P1 / 1 P2——raw 达到准出标准，可进入正式 v10-dev 撰写。**

## R4-P1-1 五点逐项裁决

全部**关闭**：① 生命周期 = 同 session 下一次符合条件的新 decision step 的 execution assemble，显式≠v8"下一 turn"，含 decision→tools→同 turn 下一 decision 映射（L136/289/438、fixture L409）；② consumer_relation 逻辑资格（生产 effect/step × 逻辑装配 occurrence × 目标 step），目标绑定与初始 seal 原子提交，occurrence 按成功提交的新 decision 装配计，禁止 produced_seq+1 与物理 seq 窗口（L136–137）；③ inspection/装配回滚不消费、sealed retry 不重装配不再次消费、关闭 turn/cancel/terminal 后逻辑失效不跨 turn/session 转投（L137–138、165–167、409）；④ 采样与投递分离——合格 decision_only 关闭 decision 仍计样补 ANALYZE，候选当次丢弃（L107–111、417）；⑤ fixture 3/9 分工覆盖全部分支（L409、417）。

与冻结 v8 的对账：正常路径（S1 LLM 成功→Feedback 计样→tools seal→S1 succeeded→session ready turn 未关→S2 execution assemble 消费）完整落入 §3.1/§3.1.2/§3.2.1 规则 6 既有状态机；关闭分支（decision_only→计样不留候选→finish_session→completed）与 §3.1.1 一致，未把 turn 关闭误写成 completion 直置 completed。

## 轮 4 四条 P2 处置

全部**关闭**：P2-1 needs_preparation（L103/198/419，与 §3.1.2 receipt 首占/重放、§4-4 拒绝后显式 yield 模式一致；授权前置门通过后的可归属请求才记父命令 receipt，未强塞 command receipt 命名空间）；P2-2 发布幂等 7-P0/7-P2 拆组（L199/413–415/437–439）；P2-3 digest 历史标记（L9/§四）；P2-4 tie-break 逻辑身份/规范键 + §6 禁"先按物理 ID 排序再从输出删 ID"伪确定性（L157/358/407）。

## 十三项已关 P1 防回归

全部**维持关闭**（逐项锚点核验：R2-P1-1 L88–99/134–142/159；R2-P1-2 L163–167/183/408；R2-P1-3 L101–105/196–200/237 范围未扩大；R2-P1-4 L70/153–155/449 范围未扩大；R2-P1-5 L306–316/411；R2-P1-6 L258–264/277–279/450；R2-P1-7 L239–241/356/412–415；R2-P1-8 L55/140/410；R2-P1-9 L171–173/419；R2-P1-10 L352–360/407；R3-P1-1 L204–206/374–384 + digest；R3-P1-2 L99/107–111/417；R3-P1-3 L425–451）。附加检查：18 条不变量与候选地位无语义回退；不变量 2/3/9/12/17/18 锚点保留；v9 共存（§7.4 L392–403）与命名证据（L346–348）未回归。

## 新发现

- **R5-P2-1（非阻塞）**：fixture 9 含 P1 消费联验但 P0 阶段整体列绿（§8-9 L417、§9.2 L437–438）——v10-dev 验收表定稿时拆 9-P0（Feedback 资格/去重/候选生产原子性/关闭不留候选/排除入口负向）与 9-P1（与 fixture 3 联验真实消费/回滚/retry/窗口结束/终止失效）；若 P0 已落库候选，生产端去重/cap 约束随写入口交付。

## 准出结论

raw 已达 0 P0 / 0 P1。进入 v10-dev 后落实（不提前塞回 raw）：consumer_relation 存储/occurrence 分配/消费原子性；Feedback 样本/去重/cap/共享桶约束与锁序；needs_preparation 父命令归属/稳定编码/重发流程；发布命令权限/receipt/冲突/crash 合同；fixture 9 P0/P1 拆分与全部 fixture 精确输入输出。三 spike（stats/fold/payload）仍是带阻塞时点的后续工作；正式 P0 接入须过 §9.1 v8 runtime 接入门。不为 R5-P2-1 再安排 raw 阻塞复审；若恢复自动 preparation、跨调用 PTL 重装或改变已选生命周期，再对相应架构增量单独复审。

## 轮 5 审核链

- Loop Orchestrate：控制器（本会话）→ turn 2 Orchestrate `B8BAC893` → 本轮冻结检查
- 循环记忆：`prompt-exports/loop-orchestrate-v10-raw-p1-runs.md`（turn 0–2 全记录）
- Oracle chat `new-chat-D11B11`（chat mode，轮 3/4/5 同链）
