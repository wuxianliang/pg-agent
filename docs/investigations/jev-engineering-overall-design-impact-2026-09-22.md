# Investigation: Jev Engineering 思想对 pg-agent 总体设计的影响

## Summary

（待补——调查完成后填写最终结论：文档思想是否暗示总体设计层面的修改，及修改清单。）

## Symptoms（调查问题）

上一轮分析（2026-09-22 forked session「jev-engineering-zh 调研 → 对 pg-agent 设计的启发」）已得出结论：v13 与 Jev Engineering 文档大量**收敛**，外加 5 个**增量级**改动（goal 去重、信任轴路由、重建定价、条件化指令件、三级工具披露）。

本调查追问一层：**文档的思想（而非具体机制）是否暗示 pg-agent 总体设计层面的修改？** 即：

- 平面划分 / 承重件（不变量）是否需要增删或重排？
- 哪些「增量」实际上应该升格为架构级改动？
- 文档中是否有上一轮未识别的架构级主张？
- v13 底座尚未开工（09-21 执行环 M1 已 revert、代码树归零），此时改设计的窗口成本最低——哪些值得趁现在改？

## Background / Prior Research

### 1. 文档本体（上一轮已核实）

- 仓库：`https://github.com/yibie/jev-engineering-zh` —— 2026-09 出版的 12 页工作笔记《Jev Engineering: For Coding Agents》中文全译（含原文 PDF、7 张插图）。
- 作者 Diogo Almeida，TypeSafe 创始人。**TypeSafe 的 Jev 正是 v13 §2.2 `pg_typesafe` 封装的那个 Jev**（choice / score / noul 决策模型）。v13 设计时只知道「Jev = 判断原语」；这份文档补上了原厂 harness 哲学。
- 核心论点：**「如果 LM 没有 KV cache，你会怎么设计 coding agent？」**——六个通病（路由失效、工具挤占、盲目 compaction、子 agent 稀少、重启丢状态、电池之争）全是「只追加对话记录」这一个缓存经济事实的衍生物；出路 = 显式带类型状态 + 每轮按查询组装上下文。

### 2. 收敛点（上一轮映射表，v13 已有机制 ≈ 文档主张）

| Jev 文档主张 | v13 已有机制 |
|---|---|
| 上下文是**被组装的**，不是被累积的 | §0 执行收据：manifest + artifact 固化 |
| 复用缓存 vs 重建应是**显式成本决策** | §5.2 三种回放（exact replay / recompute / fresh fork）+ E(r) + cache-break 逐 section hash diff |
| 可见性阶梯：块只降可见度，**从未删除** | chunks 可重建投影 + artifacts 不可变 + applied/skipped 双分支 |
| 查询感知压缩：知道问题之后才压缩 | manifest 逐 turn 装配；tier 单调性（轮 2 P0 修正） |
| 读写显式区分，只读任务不争锁 | PG MVCC；§4.3 解析相不碰会话锁（G-ctx1） |
| 路由两前提：小专用上下文 + 回程不强迫重读 | fork 前缀身份哈希 + handoff 引用不复制 + G-closeout children 汇总 |
| 权限 = 对允许/不允许的可编程查询 | §6.1 版本化 SQL 策略（更严：Jev 只产证据不裁动作） |
| 状态放具名变量 | fold_state + latches + meta |

**元观察**：文档实际在重新发明数据库概念（带类型可寻址状态 = 行、可见性 = 权限/投影、目标去重 = 唯一索引 + 咨询锁、策略即查询 = SQL policy、共享只读 = MVCC）。pg-agent 论点恰好是「别在应用层仿制数据库，直接用数据库」——外部最强论据，值得进 v13 教程第 15 章论点段。

### 3. 上一轮识别的 5 个增量（本调查要逐个判定：增量 or 架构级）

1. **goal 去重进 spawn 准入**（文档 §VI.B）：派发前注册子目标并与历史/在飞去重。§6.1 快照复核已有 `goal_hash`，G-spawn-fanout 只有同 tool_call id 重放幂等，无跨 tool_call 目标级去重。
2. **信任轴路由**（§IX）：按数据敏感度（公开/应用代码/密钥/专有）× provider allowlist 做策略行。对 RP 原生化 v2 的「oracle 面 = llm effect × provider 目录行」即插即用。
3. **上下文重建定价**（§II.A）：文档算术（纯前沿 25Y+5Z vs 路由 3X+20Y+8Z ≈ 4.15 vs 6.19）——按 token 定价不按上下文重建定价的路由必亏。v13 的 R_o 只覆盖输出侧；可补确定性 X/Y/Z 成本 SQL 函数进路由收据。
4. **条件化指令件**（§VIII）：指令附着激活条件（路径/glob/主题），条件成立即重载、免疫压缩。v13 现无此机制（latches 是冻结值、emergent 是 TTL 短命件，都不是它）。
5. **三级工具披露**（§VII）：廉价全局地图 → 选中才倾倒 schema → 用完即弃。v13 逐 turn manifest 天然满足第三级。

### 4. 上一轮认定 v13 领先文档的三点（无需改）

- **证据/动作分离**：v13 §6.7 裁定 Jev 只产不可变证据、动作授权独占版本化 SQL——文档没有的注入防线。
- **可行性工程**：v12 实测库内判断持锁 1.3–1.6s；v13 的 SQL 短路 + per-chunk 判断缓存 + `_many` 批处理 + advisory lock 付款去重是让 Jev 哲学**经济上成立**的那层。
- **缓存两面性**：文档单方面逃缓存；v13 同时逃（装配式）和用（前缀身份、E(r)、latch 护前缀）。

### 5. 清醒剂

文档自述「独立汇编的设计笔记」，多处「工作假设/猜测」；数字（fastcontext 56.2%、token 份额、标价）会漂。**结构可学，数字不立法**。

### 6. 项目现状（memory 摘要）

- v13 上下文平面：2026-09-19 v2 成稿，轮 1+轮 2 均已裁（tier 单调性等 P0 修正并入）；~~09-21 执行环 M1 已 revert、代码树归零~~ **【已核实过时】09-21 21:09 revert 后，实现自 09-22 00:05 重启并连夜推进：DP1 schema → DP2 resolve → DP3 loop/twophase → DP4 manifest/chunks → DP5 recall/characterize → DP6 filter/memory（git a9dabc9）→ DP7 economy（v13_economy.sql 已落 v13_pricing 等）；DP1–DP6 各有 L4 复审 PASS（docs/reviews/v13-dp*-impl-l4-review-2026-09-22.md），DP7/DP8 计划已 L4。**因此「改设计零成本」不成立——改动需按三档定价：台账/errata/教程文本（便宜）、DP8 后置项与未实现平面（中）、已实现 stage 的 schema/gate 变更（贵）。
- RP 原生化仿制：2026-09-21 go→v2；七条 I-file 不变量、五点裁决两层收据表、动态三表后置；主体依赖 v13 底座。
- Agent 控制平面对照：R2 终裁 D1-D3 + A15–A21 修订已交付放行（四值信封 / sql spawn / **goal-override**）；gpt 少数意见存档。
- v13.1 workbench 平面（AGENTS.md 处理相关）、v6.1 代码/文件工作台（sitting_duck + duck_block_utils + tigerfs，双平面）。

<!-- Phase 1.5 explore 结果追加于此 -->

### 7. Phase 1.5 — explore「文档完整架构骨架」（2026-09-22）

来源：README.md 全译 12 章 + assets/original-text.txt（英文原文摘录）。

#### 7a. 六症状精确化

| # | 名称 | 缓存经济根源 |
|---|---|---|
| 1 | 路由失效 | 混合路由比纯前沿贵：每次交接都要在对方模型重处理全上下文，前沿侧的 KV 命中丢失 |
| 2 | 工具挤占上下文 | 全部 schema 常驻 system message，与是否使用无关 |
| 3 | 盲目 Compaction | 不知道下一查询前压缩，必然丢掉后续需要的东西 |
| 4 | 子 agent 稀少 | 状态传递太贵太易错，模型倾向不 spawn |
| 5 | 重启丢好状态 | append-only 使选择性再水化不可能：全重放或全丢弃 |
| 6 | **电池之争** | 「电池」= 上下文窗口预算的隐喻；每个内建能力（技能/工具/系统提示/指令）**永久占用**部分窗口 → 易用性 vs 可用容量的零和 |

#### 7b. 上一轮**遗漏**的架构级主张（本调查重点输入）

- **§IV Harness 即工具路由器**：模型输出**纯文本意图**，harness 用 Jev 选工具 + 构造参数；模型不持有 schema。错误参数类型成为校验错误而非静默失败。——这是**回路形状级**主张（工具选择移出前沿模型），比 §VII 三级披露更激进。
- **§IV 可编程权限（内容分级）**：高风险动作触发更深检查（读脚本内容而非只匹配命令名）——按内容而非命令名。
- **§III Token 份额**：读文件 30-40% + 搜索 10-18% + 命令输出 10-20% ≈ **2/3**；写代码仅 4-10%。「最大效率收益来自更聪明的检索，而非更好的模型或 diff 格式」。fastcontext：读/搜 = 56.2% 工具轮、46.5% 主 agent token。
- **§X 后台处理面**：并行 HTML 页更新、后台 eval 生成、ELI5 技能、agent 维护的部署进度页、镜像线上流量到候选模型自动生成 eval。共性 = **后台只读的代码库状态函数**。**「共享检索：与变更相关的非平凡工作做一次，被每个只读后台任务共享。鉴于检索占主导，共享它是最大单项节省」**。
- **§X「理解（而非生成）是新瓶颈」**：效率前沿已转移。
- **§VIII 技能 = 行为载体而非仅指令**：结构化技能携带行为改变（类似 hooks 但更强），按触发条件 attach/detach。
- **§VIII 递归方向**：更多 agent 状态放具名变量——「状态活在具名变量里的世界远比『状态是窗口里恰好剩的』干净」。
- **§VI 子 agent 回程 = 被评分的块**：非原始日志重读，而是 harness 可留/摘要/丢弃的分级块。
- **§XI 电池候选清单**：headroom（压缩+事实保留分类器）、rtk（工具输出压缩）、ast-grep（手册载一次生成 N 查询）、ast-outline（层级择子树）、fastcontext（仓库探索子 agent）、fff（内存索引频排搜索）——每个带「原生角度」。
- **§I 工作假设 4**：「有些能力只能原生做，因为它们需要控制逐轮上下文装配」——直接验证 pg-agent 全部论点。
- **重启**：可寻址状态下干净启动按需只加载相关块。
- **文档并未自认在重新发明数据库**——元观察是 pg-agent 自己的贡献（教程第 15 章论点段）。

#### 7c. 每轮回路形状（文档版）

1. 问 Jev：复用缓存还是重建？（成本感知决策，noul+阈值）
2. 问 Jev：构造最小充分上下文（choice 选块 + score 相关度）
3. 组装上下文交给模型
4. 模型回纯文本意图
5. harness 经 Jev 选工具 + 构造参数
6. 执行，结果存为被评分的块
7. 子 agent：小相关上下文进出，回程被评分的块
8. 后台任务：共享一次检索，只读，追加结果

#### 7d. 文档自述局限（清醒剂补充）

工作笔记非生产系统；无持久层设计（状态活在 harness 内存）；可见性阶梯评分函数无实现；Jev 本体被假设存在；无多用户/多会话隔离；**未讨论 Jev 自己幻觉 score/choice 时怎么办**；未讨论「Jev 说复用缓存但缓存已陈旧」的失效模式；§XI 清单是点子非评估过的实现。

## Investigator Findings

（pair investigator，2026-09-22。三值裁定 = 已覆盖 / 台账增量 / 架构级改动。）

### 0. 方法、编号勘误与两份新事实

- **方法**：三个 explore 子代理窄侦察（contextpipe.md 八层、v13_economy.sql+DP7 计划、DP8 计划+v13.1 平面）+ 自读八份核心文档（v13 设计全文、ch06/ch13/ch15、R2 终裁、RP-native v2、v13-rag-subagent 草案、errata 全文）。探针承重结论已抽查复核：DP8 计划 :409-438（v13_goal_hash 换体）、:1098-1117（§7 明确不做）、v13_economy.sql 交接/重建/换路由成本 0 命中（file_search 亲验）。
- **编号勘误（对任务提示）**：「A22 起 / B16 起」中 B16 已过时——B16–B18 已被 R2 §6 文档 bug 清单占用（R2:269-270，B18 = goal/direct 双事件作废改单一 goal/override），B15 已注册 errata §10。**下一个可用号：A22（修订）/ B19（文档 bug）/ E7（对冻结稿正文的真 erratum）**。
- **新事实一（goal 已半实体化）**：`v13_goals` 已是 append-only 一等行——`v13/manifest/v13_manifest.sql:3-17` 建表（PK (session_id,seq)、FK events、content_hash=sha256(payload) 自证 CHECK），:20-30 触发器族（append-only 守卫 + events type='user/message' 自动投影），:47-49 v13_goal_hash；DP8 计划 :409-438 还要把它换体成前缀感知（fork 子沿 parent_cutoff_seq 链回走）。
- **新事实二（H3/H5b 已有承载件）**：`docs/designs/v13-rag-subagent.md`（2026-09-22 13:55 草案 v1，待轮 1 裁决）:84 已直接引用本调查前轮结论（「检索占主导…共享检索是最大单项节省」「子 agent 回程=被评分的块」），:141 被评分块形状 `{chunk_hash, score, span, decision_id}`，:145 §3.6 零改动名单——RAG 能力子代理草案就是 Jev §X 主张的现行消化处。

### H1a goal 去重 —— 台账增量（spawn 准入一条 SELECT）；不是 goal 一等实体化，但有一个真实窗口期

- **文档主张**：Jev §VI.B 跨 tool_call 目标级去重——派发前注册子目标，与历史、在飞去重。
- **v13 现状**：
  - goal 已一等实体化：v13_goals 行（v13/manifest/v13_manifest.sql:3-30，见 §0 新事实一）；goal_hash 参与快照复核（v13 设计 :279「解析事务记录…goal_hash、candidate_set_hash；变更事务拿锁后复核」）；A20 单一 goal/override 事件 intent∈{direct,decompose}（R2:187；errata §9 A20 行）。
  - 幂等只到 tool_call 粒度：G-spawn-fanout「同 source tool_call id 重放返回同一 child」（v13 设计 :532；R2:138）——跨 tool_call 目标级去重不存在（DP8 计划关键词检索零命中，:1098-1117 后置清单亦无此项）。
  - **关键时机事实：`v13_spawn_subsession` 尚未实现**（v13/ 全树 62 文件 0 命中）——A17 spawn 档位还是纸面合同（v13 设计 :427；R2 §2），DP8 只交付 v13_fork + validate-spawn（DP8 计划 :478-577），不含 spawn_subsession。
- **裁定与理由**：**台账增量**。「goal 一等实体化」半边已存在（v13_goals 行 + goal_hash + override 事件），缺的只是 A17 准入合同里的一条确定性 SELECT：在飞去重=同 parent/root 下非终态子会话 goal_hash 相等 → 拒/并回执；历史去重=终态子会话 goal_hash 相等且其后无新事件（水位谓词，快照复核同款机制）→ 拒。注意历史去重必须带新鲜度谓词——「再跑一次测试」是合法重复目标，无脑去重会吞掉合法工作；在飞去重则无条件安全。**窗口期判断**：spawn 准入函数未实现，现在把去重写进 A17 合同=便宜档（设计文+R2 计划文本）；实现后再补=贵档（改已实现承重函数+gate+回归）。
- **若需改**：v13 设计 §6.8(iv)（:427）spawn 档位段加一句准入去重条文（在飞硬拒、历史带水位新鲜度）；§10 G-spawn-fanout（:532）扩一条断言；ch14 同发。errata 注册 **A22**。成本：**便宜**（纯文本，实现随 A17 原子切片走，零 schema 增量）。

### H1b 缓存经济学（交接重处理成本）—— 台账增量；既不是架构级一等服务，也不必现在补函数

- **文档主张**：Jev §II.A 交接重处理成本算术（纯前沿 25Y+5Z vs 路由 3X+20Y+8Z）——按 token 定价不按上下文重建定价的路由必亏。
- **v13 现状**：
  - 定价目录已五维：v13_pricing（provider/model/account/cache_class × catalog_version，fresh/cached usd_per_mtok，append-only 翻版仪式；v13_economy.sql:66-80）；单源 r=cached/fresh（:121-129）。
  - E(r) 已进 manifest：e_base=稳定前缀×r+变更段×fresh（:689-731），r*=0.145 硬编码分支（:712-731），er.branch 五值；R_o=percentile_cont over completion_tokens（输出侧，:159-198）。
  - **最接近「重建成本」的既有件**：v13_cache_breaks（:255）逐 section content_hash diff + **rebill_suffix（首断点后缀重计费）**——同模型内前缀重建成本已在计；缺的只是跨模型交接对比函数（target provider fresh 全前缀重算 vs current cached 续跑）。交接/重建/换路由字样 0 命中（亲验）。
  - **但 v13 首版没有模型级路由决策点**：v_routes 路由的是动作（llm/human/sql），generation 是单策略行（DP8 才接真值，DP8 计划 :1113）；模型级多 provider 路由=RP-native v2 oracle 面（llm effect × provider 目录行）的事，属 post-v13。
- **裁定与理由**：**台账增量**。交接成本不该升格为架构级一等服务：原料（定价目录×manifest est_tokens）全已在库，触发时是一条确定性 SQL 函数+路由收据一字段的事，零 schema；现在建则违反「臆断不立法」（§5.3 同款先例——没有决策点的成本函数是无消费者的代码）。已覆盖大半的判断也成立：rebill_suffix 计同模型重建、E(r) 计压缩前后输入成本，Jev 算术的 v13 对应物只差「换模型」一格。
- **若需改**：v13 设计 §12 YAGNI（:573）加一行——「交接/换路由成本函数；触发=RP-native oracle 面多 provider 路由落地（或首个真实换模型决策）；形态=确定性 SQL 函数入路由收据，原料 v13_pricing×manifest est_tokens」。RP-native v2 oracle 面章节可挂一句指针。成本：**便宜**（台账文本）；触发后实现也便宜（纯函数）。

### H1c 条件化指令件 —— 台账增量（装配策略谓词）；不是新上下文源类别

- **文档主张**：Jev §VIII 指令附着激活条件（路径/glob/主题），条件成立即重载、免疫压缩。
- **v13 现状**：
  - **ContextPipe 八层里也没有此层**（探针 T89 + 引文核对）：latch=首触发冻结值（contextpipe.md:233，cache-scope 资格类）；emergent=TTL 一轮+hash 去重+cap（:239-241）——两者都无路径/glob 条件附着语义；八层中「项目规则」住 Per-session 层、「技能目录」住 Per-agent 层（:215-217 Table 1），即上游论文自己就是把指令当归层数据、不是条件机制。条件附着是 Jev 特有主张。
  - v13 侧：latch=首触发冻结（设计 §5.1）、emergent P2 延后——上一轮归因「latches 冻结值/emergent TTL 都不是它」正确。
  - **AGENTS.md 处理确在 RP-native v2 不在 v13.1**（本次核实归因）：白皮书名集含 AGENTS.md（repoprompt-native…v2.md:119，corpus_bootstrap names_prior ≤10 冻结）；v13.1-workbench-plane.md 全文 AGENTS.md/指令/instruction 零命中（探针 T91）。
  - 「免疫压缩」的既有语义：manifest priority [Never/First/Normal/LastResort]（设计 §5.2）+ protected sections 硬删除禁令（§6.7 :359 不整合清单内——保护语义存在且判断面不得覆盖）。
  - 逐 turn manifest 装配=按查询条件化是构造性的（设计 §0/§5.2）。
- **裁定与理由**：**台账增量**，且形态是**装配策略谓词而非第九层 ContextSource**。理由：(1) Jev 的两类激活条件在 v13 各有确定性表达——路径/glob 型=文件语料成员+装配期确定性谓词（ws/路径前缀匹配，纯 SQL）；主题型=recall 按查询命中（装配本就查询驱动）。(2) 免疫压缩=priority=First/protected 既有语义。(3) 新增源类别违反 §5.1「目录：生命周期即视图——多数层映射既有表」的立法姿态，三读法也问不出哪个读法需要它。(4) 真实触发在 RP-native 文件面之后（多项目/多目录指令需求）。
- **若需改**：v13 设计 §12 YAGNI 加一行（触发=文件面落地后真实多目录指令需求；形态=策略行+装配确定性谓词，非新 ContextSource）；RP-native v2 §6 放行条件区挂一句。成本：**便宜**。

### H2 harness 即工具路由器 —— 部分吸收；剩余应显式拒绝并记录理由

- **文档主张**：Jev §IV 模型输出纯文本意图、不持 schema；harness 用 Jev 选工具+构造参数；错误参数类型成为校验错误而非静默失败。
- **v13 现状**：
  - **选择半边已吸收**：「SQL join 预筛 + Jev 终选」（ch06:75，工具-任务匹配从全目录 Choice 降为 consumes/produces join+终选）。
  - **校验收益已用更强机制兑现**：input_schema 严格校验 fail-closed（ch06:117「input_schema 不符的 effect.request 在创建时被拒」）+ pg_jsonschema——Jev §IV 的收益（类型错误=校验错误非静默失败）不经过「harness 构造参数」就已成立。
  - v13 模型持 schema：工具 schema 是前缀身份成员（设计 :249「system blocks+tool schemas+model+latches」）；电池之争用 TrimSchemas 压力档处理（设计 :227）。
  - 判断面无生成能力（设计 §1 作用力 5「概率无恒等式；Jev 数学弱、CJK 判断劣化、无生成能力」）。
- **裁定与理由**：**部分吸收 + 显式拒绝剩余**。拒绝理由三条：(a) 构造参数需要生成，Jev 做不了——harness 构造参数=把生成成本挪到路由器且每 turn 抽换 schema 集会击穿前缀身份（工具 schema 在 prefix identity 材料内，按 turn 换=每 turn cache-break，恰是 Jev 自己 §II 反对的事）；(b) 电池之争已有 TrimSchemas 档+目录 description 列（给判断平面看的一句话，ch06 §6.2）表达；(c) 校验收益已由 input_schema 兑现。v13 保持「模型发结构化 tool_call、确定性合同校验、SQL 预筛+判断面终选」的现行回路形状。
- **若需改**：v13 设计 §6.7 不整合清单（:359）加一行：「判断面构造工具参数 / 按 turn 抽换 schema 集（前缀身份成员；类型校验已由 input_schema 兑现）」+ 上述理由句。可随 A22 同批注册（或独立 A23）。成本：**便宜**。

### H3 后台只读任务面 + 共享一次检索 —— 已覆盖（既有构件组合；承载件=v13-rag-subagent 草案）

- **文档主张**：Jev §X 后台只读的代码库状态函数族；「共享检索：与变更相关的非平凡工作做一次，被每个只读后台任务共享…最大单项节省」。
- **v13 现状**：
  - **承载件已存在**：v13-rag-subagent.md:84 直接引用本结论、:141 回程被评分块、:145 零改动名单（不动召回/chunks/两阶段/过滤/三层记忆/四值信封/effect 纪律）；三档入口（rag.recall 纯 SQL / rag.ask 工具行 / spawn 深检索）全部复用既有平面（A17 spawn + handoff + 四值 result_kind）。
  - 共享检索在 v13 近乎构造性：召回是函数不是视图（设计 §4.1）、chunks 是共享全局投影、判断缓存 per-chunk content_hash 跨 session 复用（设计 §4.5 reused_from）——「做一次被共享」由行+函数自然成立，不需要「共享检索服务」这个新件。
  - 后台只读面=既有构件：队列即唤醒（ch03）、effect worker（ch08）、T2 离线批量投影（设计 §7「duck worker 批量分析/重嵌入(RSI)——退出在线检索，只做离线」）。
- **裁定与理由**：**已覆盖，非新平面**。「后台只读任务」= effect worker 上只读工具+spawn 档+handoff 被评分块回程的组合，三读法在既有原语上闭合。唯一要守的线：rag-subagent 裁决通过时 G-rag 族 gate 挂进 v13 gate 族须守住其自我承诺的零新 primitive（草案 §3.6）。
- **若需改**：不改 v13 设计正文。v13-rag-subagent.md 轮 1 裁决时补两件：(1) :84 「jev 调查结论(2026-09-22)」改为带本报告路径的引用；(2) 明示该草案即 Jev §X 主张的登记处。成本：**便宜**（草案文本）。

### H4 检索占 2/3 token → §11 交付排序 —— 已覆盖（无需重排）

- **文档主张**：Jev §III 读+搜+命令输出 ≈ 2/3 token；「最大效率收益来自更聪明的检索」。
- **v13 现状**：§11 交付排序（:555）里检索已占承重件位——过滤管道在步骤 1（存在性 Noul+per-chunk Score）、T0 recall+chunks 在步骤 3（先于步骤 4 经济学）；token 侧「更聪明检索」三件已在承重件层：召回三禁（§4.1 P0）、过滤管道（§4.5，少装）、跨度装配解放 chunk 尺寸（§4.7，装更小）。DP5（recall/characterize）、DP6（filter/memory）已落地。
- **裁定与理由**：**已覆盖，无需重排**。三层理由：(1) v13 对「检索占主导」的响应不是排得更早而是纪律更硬——三禁/过滤/跨度都在 P0/P1 承重件层，比 Jev 建议的优先级更高；(2) 剩余检索增量（T1 混合/bigram/reranker）全部台账触发且触发条件=本地证据（固定评估集/kohaku fixture），把 Jev 的 fastcontext 外部数字当触发条件会违反「臆断不立法」（§5.3 先例）——报告清醒剂「结构可学，数字不立法」恰好适用；(3) DP1–DP7 已按原序实现，可重排空间只剩 DP8+post-v13，而那里没有检索件可提前（T1/T2 本就后置）。
- **若需改**：无必改项。可选：设计 §7 检索分层处加一句外部佐证引注（Jev §III token 份额作为分层存在的外部证据）——注释性，成本低价值低，可不做。

### H5（三项同法裁定）

**H5a 技能=行为载体（非仅指令）—— 显式拒绝进底座，记台账**。v13 无技能平面；最近物是 ContextPipe Per-agent 层「技能目录」（contextpipe.md:216，v13 未映射此层，§5.1 只新增 latch/emergent）。「结构化技能携带行为改变」在 v13 的等价分解=工具行（能力）+策略行（参数）+指令 artifact（提示）+effect（行为后果），四件都已是行且版本化；「attach 时执行行为」若真出现=外部 IO=effect 纪律问题，不是新平面。改：v13 设计 §12 YAGNI 加一行（触发=工作台面真实技能系统需求）。成本：便宜。

**H5b 子 agent 回程=被评分的块 —— 已覆盖**。handoff 信封=artifacts 载荷+稳定 delivery_id 幂等、transcript 存 manifest/hash 引用不复制正文（设计 §6.8(iii)；R1 共识 4）；closeout 收据 children 汇总（A16，设计 §10 G-closeout）；被评分块形状已被 RAG 草案显式化（v13-rag-subagent.md:141，manifest 候选行的投影）；留/摘要/丢弃三分=manifest applied + 摘要验收链（§6.4）+ skipped。无需改。

**H5c 内容分级权限（高风险读内容非名字）—— 已覆盖**。库内侧按内容执法：G-sql-write-closed「prosrc 含 IO 通道(dblink/pg_net/COPY PROGRAM)→红」（设计 §10；ch06 §6.4）——扫函数体不匹配名字；文件侧按内容执法：I-file-3 注册即出境=秘密扫描+类型/大小/deny glob 同一道门、fail-closed、路径树执法（repoprompt-native…v2.md:33）+ G-file-secret（密钥正文 blocked 无 chunks 无路径）。外部命令面（shell 内容检查）不在 v13 底座范围，真出现=allowlist+input_schema+effect 审计既有机制组合。无需改。

### 元观察 → ch15 论点段 —— 教程文本增量（便宜档，确定要写）

- **v13 现状**：ch15 §15.8「回到 vN 对照（终章）」（:159）是十二轮内部实验映射表+一句话收束（:180）；§15.9 内在合理性（:186）。**外部佐证论点段不存在**——§15.8 全是内部历史，无任何外部系统对照；Jev Engineering 零引用。
- **裁定与理由**：**纯文本增量**，也是本次全部候选中唯一确定要写进文档的新论据。放法：§15.8 映射表后、「一句话收束」(:180) 前加一段「外部佐证」——TypeSafe Jev Engineering（2026-09 工作笔记；pg_typesafe 封装的同一 Jev 的原厂 harness 哲学）独立汇编出同一组数据库概念：带类型可寻址状态=行、可见性阶梯=权限/投影、目标去重=唯一索引+咨询锁、策略即查询=SQL policy、共享只读=MVCC、每轮装配=manifest——「如果 LM 没有 KV cache 你会怎么设计」的答案他们在应用层重新发明了数据库；v13 的差别只是让这些概念生在库里。配一行清醒剂（文档自述工作假设/数字会漂/结构可学数字不立法），并与本调查的显式拒绝条目（H2/H5a）呼应——同一文档的激进主张为何在 v13 被拒。§15.9 推导段可加一句呼应（可选）。
- **若需改**：仅 ch15 一处（+可选 §15.9 一句）。成本：**便宜**。注意保持「教程是讲解、设计文是权威」分工——论点段只引不立法规。

### 总体设计修改清单草稿（按价值/成本排序）

**结论总述：Jev Engineering 文档不暗示 v13 任何平面级/承重件级增删——九项候选全部落在「已覆盖（5）/台账增量（3）/显式拒绝记理由（1）」三档，无一项构成架构级改动。** 文档最大的架构级贡献是确认性的（外部独立汇编殊途同归），而非修正性的。逐项清单：

**A. 趁 DP8/A17 实现前改（窗口期，全部便宜档文本）：**

| # | 项 | 改哪 | 成本 | 理由（为何是现在） |
|---|---|---|---|--- |
| 1 | **goal 去重写进 A17 spawn 准入合同**（在飞硬拒+历史带水位新鲜度） | v13 设计 §6.8(iv):427 加条文、§10 G-spawn-fanout:532 扩断言、ch14 同发；errata **A22** | 便宜（文本）；实现随 A17 切片零 schema | v13_spawn_subsession 未实现（62 文件 0 命中）——现在写=文本成本；实现后补=改承重函数+gate |
| 2 | **H2 显式拒绝进 §6.7 不整合清单**（判断面构造参数/按 turn 抽换 schema 集+三理由） | v13 设计 §6.7:359 加一行；随 A22 同批或独立 A23 | 便宜 | 防止后续被该文档反复动摇；拒绝理由（前缀身份/无生成能力/校验已兑现）现在书面化最完整 |
| 3 | **元观察进 ch15 §15.8 论点段**（外部佐证段+清醒剂一句） | ch15:159-180 区间插入 | 便宜 | 纯教程文本，无依赖 |

**B. 记 YAGNI 台账（v13 设计 §12:573 加行，触发后才建）：**

| # | 项 | 触发条件 | 形态 |
|---|---|---|---|
| 4 | 交接/换路由成本函数（H1b） | RP-native oracle 面多 provider 路由落地 / 首个真实换模型决策 | 确定性 SQL 函数入路由收据；原料 v13_pricing×manifest est_tokens，零 schema |
| 5 | 条件化指令件=装配策略谓词（H1c） | RP-native 文件面落地后真实多项目/多目录指令需求 | 策略行+装配期确定性谓词（路径/glob 型）；主题型=recall 既有；免疫压缩=priority=First/protected；**不新增第九层 ContextSource** |
| 6 | 技能=行为载体（H5a） | 工作台面（v13.1/RP-native）出现真实技能系统需求 | 分解为工具行+策略行+指令 artifact+effect，不建技能平面 |

**C. 已覆盖、不动（登记防止重开）：**

| # | 项 | 既有覆盖件（file:line） |
|---|---|---|
| 7 | H3 后台只读+共享检索 | v13-rag-subagent.md:84/141/145（草案承载，裁决时补出处指针+登记为 Jev §X 消化处）；设计 §4.1/§4.5/§7 |
| 8 | H4 检索优先级/交付排序 | 设计 §4.1 三禁、§4.5 过滤、§4.7 跨度、§11 步骤 1/3；DP5/DP6 已落地 |
| 9 | H5b 回程被评分块 | 设计 §6.8(iii) handoff、§10 G-closeout(A16)、v13-rag-subagent.md:141 |
| 10 | H5c 内容分级权限 | 设计 §10 G-sql-write-closed（prosrc 扫描）、RP v2 I-file-3（:33）+G-file-secret |
| 11 | 三级工具披露（上轮增量 5 的复核） | 逐 turn manifest+TrimSchemas 档（设计 :227）+目录 description（ch06 §6.2）；第二级（选中才倒 schema）=TrimSchemas 的反应式等价，不另建 |

**D. 显式拒绝并记录理由（即上表 #2，单列以防丢失）：** 判断面构造工具参数/模型不持 schema（Jev §IV 激进半边）——拒绝理由三条见 H2；顺带把「信任轴路由」（上轮增量 2）留在 RP-native v2 oracle 面语境（provider 目录行+策略），不进 v13 底座。

**对报告 Summary/结论的建议措辞（供主调查人采撷）**：Jev Engineering 是 v13 论点的外部最强确认——原厂 Jev 作者在没有数据库底座的前提下独立推导出「状态入行、装配按查询、判断与生成分离」的全部形状，并在应用层重新发明了索引/锁/策略查询/MVCC；v13 无需为此改任何平面，需要做的只有三件便宜事（A17 准入去重条文、§6.7 显式拒绝一行、ch15 论点段）加三条台账。

## Investigation Log

（分阶段记录）

## Root Cause → 总体设计结论

（待补）

## Recommendations

（待补）

## Preventive Measures

（待补）
