# Investigation: v24 / Pi / RepoPrompt-CE 的 session–turn–run 三层设计对标

**Date:** 2026-11-05
**Status:** in progress
**Scope:** `/Users/wxl/Projects/pg-agent/v24`（Python runtime）、`/Users/wxl/Projects/pi`（TS harness）、`/Users/wxl/Projects/repoprompt-ce`（Swift app + MCP control plane）

## Summary

三个项目并不共享一套 session–turn–run 三层模型，而是各自沿不同轴切分：**v24 以 run/effect 为执行主体，turn 只是 effect 结算计数；pi 有两条互不依赖的产品线（coding-agent 的 JSONL 会话树 / durable 的 Conversation–Submission–Task–LiveRun）；RepoPrompt 以持久 AgentSession + transcript turn 为正文，run 只是 runtime ownership token。**

因此可以直接对标的是**职责**（会话容器、可恢复执行工作、用户请求边界、迟到结果围栏），不能直接对标一个通用的 session:turn:run 外键树。本报告给出逐项证据、基数矩阵、四套 turn 口径的分离命名，以及 v24 侧最小落地顺序（会话锚 → 只读 ledger → cancel-late 统一）。

## Symptoms / Questions

用户问题：三个项目对 session / turn / run 三层各是怎么设计的，具体如何一一对应，机制上是否相同，为后续 v24 完全对标留下线索。

需要回答的具体子问题：

1. **身份与层级**：谁是容器、谁是执行单位、谁是记账单位？各自的主键、父子关系、生命周期边界。
2. **权威状态**：每一层的事实权威在哪里（DB / journal / 磁盘 JSON / 内存 / provider transcript），是否有多真相源。
3. **生命周期**：创建、推进、终止、取消、崩溃恢复、resume、fork/分支。
4. **并发与调度**：同一 session 内是否允许并行 run；turn 的串行性由谁保证；跨 session 的 lane/link 如何挂接。
5. **transcript / 消息归属**：消息挂在谁身上，compaction、handoff、子代理结果如何回灌。
6. **控制面动词**：start/poll/wait/cancel/steer/respond 等在各层落到哪个对象。
7. **可对标性结论**：哪些概念可直接一一映射，哪些是同名异义，哪些缺失需要新增。

## Background / Prior Research

本调查不需要外部网络资料；三套代码与规格都在本地 workspace。下列既有文档被用作"先验结论"，其行号已在本次核查中重新对齐（旧行号有漂移，见 Investigator Findings F）。

| 来源 | 提供的先验 | 本次处理 |
|---|---|---|
| `docs/designs/v24-pg-agent-2026-10-22.md:56`、`:203`、`:271` | v24 明确定义 turn = 一次 business effect 执行及唯一 advance 的已提交结算数；**不建 turns 表**；provider 原文归 host journal | 采信为规格权威，并用代码逐条复核（A2、A3） |
| `docs/designs/v20-ce-native-design-5-2026-10-13.md:28-44` | CE 控制身份是 session；无头路径 `runID = sessionID`；`AgentTranscriptTurn` 是正文、`v20_turns` 是控制回执，两者不能并表；steer 只加 epoch 不换 run | 部分采信；本次确认 `runID=sessionID` 只对 DirectHeadless 成立，App 路径已被证伪（C2、F） |
| `docs/investigations/v20-epoch-operation-for-v13-ce-control-2026-10-14.md:57` | CE `agent_run.start` 拒绝调用方 session_id，总是新开会话；resume 认领同一 sessionID | 采信；当前行号已漂移到 `AgentRunMCPToolService.swift:496` 与 `AgentManageMCPToolService.swift:992` |
| `docs/investigations/v14-pi-parity-gap-investigation-2026-09-28.md` | pi 的能力清单：多 turn 回路、JSONL 会话树、42 provider 工厂；v13 侧已有 parity 对照方法 | 采信为背景；本次把"pi 的会话"进一步拆成 coding-agent 与 durable 两条线 |

调查方法：先用 `context_builder` 做跨三仓的广域选材并产出两路独立分析；再由 pair investigator 逐条证实/证伪并补 P0 缺口（turn 递增入口、两套 SQL 的加载关系、CE turn/attempt 基数、parent-child 回灌）；关键行号由本 agent 用 `read_file` 抽查（见 Investigation Log）。

## Investigator Findings

<!-- Pair investigator appends here with file:line refs and evidence. -->

以下为 2026-11-05 对当前工作区的静态代码核查，区分规格、实现和示例扩展；未运行 provider、数据库或 gate，未修改源码。路径前缀 `pg-agent/`、`pi/`、`repoprompt-ce/` 分别指 `/Users/wxl/Projects/` 下同名仓库。旧文档的行号仅用于定位旧结论，下文实现证据均重新读取。

### A. v24 对象模型与 turn 计数

**A1 — 证实，但“只有 runs”应限定为 session/turn/run 这组三个概念。** 冻结内核实际有十张表，`runs` 是执行主体，字段包括 `run_id/scope_id/parent_run_id/spawn_key/status/epoch_no/registration_generation/turn_no/driving_generation`、分列预算、`interaction/pending_steer/result`；没有 session 表或 turns 表。`scope` 是能力/归属作用域，不能直接称 conversation。十表闭集由 fixture 断言，不只是文件名搜索的否定证据。证据：`pg-agent/v24/sql/10_schema.sql:25`、`:62`、`:66`；`pg-agent/v24/s1/setup_db.py:534`、`:540`。

**A2 — turn 的权威定义已写在规格，不是从计数器猜出的模型回合。** turn 是一次 business effect（`model_call` 或 `tool_call`）执行及唯一 advance 的已提交结算序号；模型和每个工具 effect 各算一次，`model → N 个工具 → model` 的正常完整结算计数增量为 `N+2`。不建 turns 表，事实分布在 runs/events/effects；provider 原始 assistant/tool 对话由受信 host journal 保存，DB 保存语义投影与提交顺序。证据：`pg-agent/docs/designs/v24-pg-agent-2026-10-22.md:56`、`:203`、`:271`；journal 按 run 重建原文：`pg-agent/v24/host/worker.py:1194`、`:1204`、`:1214`。

| 当前递增入口 | 代码核实及边界 |
| --- | --- |
| 普通 model settlement | `v_turn := r.turn_no + 1`，不是仅 success 才递增；后续分支处理 success/failure/unknown 和迟到事实。结构非法、返回错误且不提交的候选不算 turn。`pg-agent/v24/sql/48_loop.sql:588`、`:593`、`:601` |
| 普通 tool settlement | 同样先计算 `r.turn_no + 1`；这证实了原来未经核实的第 1411 行。`pg-agent/v24/sql/48_loop.sql:1350`、`:1411`、`:1418` |
| 普通 settlement 的独立验证与落库 | validator 强制提交值等于旧值 +1（revision 也 +1），applier 写入 `runs.turn_no`。`pg-agent/v24/sql/48_loop.sql:1986`、`:1988`、`:2905` |
| recovery 合成 unknown | 正常 unknown wall 将 run 置 `blocked_unknown`，turn/revision +1；cancel-late 分支保留旧 turn/revision，只追加迟到事实。`pg-agent/v24/sql/49_recovery.sql:122`、`:129`、`:149` |
| steer / interaction respond 命令本身 | run 更新集不写 `turn_no`；steer 改 epoch/generation/revision，respond 改 generation/revision，随后准入的 model effect 日后结算才 +1。`pg-agent/v24/sql/40_interpreters.sql:2580`、`:2614`、`:2700`、`:2730` |

**必须限定“cancel-late unknown 不 +1”的适用路径。** 规格第 271 行明确指向 `49_recovery.sql`，该 recovery 分支确实保留计数；普通 tool settlement 的 cancel-late unknown 分支没有把先前计算的 `v_turn` 改回旧值，而且通用 settlement validator 要求 +1。因此不能把 recovery 特例扩写成“所有 cancel 后的 unknown 结算都不 +1”。这是当前代码的入口差异，尚未用 gate 验证是否属于预期差异；本调查不改实现。证据：`pg-agent/docs/designs/v24-pg-agent-2026-10-22.md:271`；`pg-agent/v24/sql/49_recovery.sql:124`；`pg-agent/v24/sql/48_loop.sql:1411`、`:1419`、`:1433`、`:1988`。

**A3 — 冻结 v24 与 Cordis v2 是两套独立实现；当前 host/UI 使用前者。** `host/db.py` 不负责加载 schema，只是显式调用 `v24.host_*`、`v24.advance`、`v24.command_recover` 的 RPC 客户端；`s1/setup_db.py` 导入 `v24.load` 并执行 `load_stage(conn)`；该 loader 的根为 `v24/sql`，加载包含 `48_loop/49_recovery/49_host_reads` 的十二文件清单。不能说 host 自动选择或加载 Cordis。证据：`pg-agent/v24/host/db.py:1`、`:31`、`:52`、`:177`；`pg-agent/v24/s1/setup_db.py:43`、`:653`；`pg-agent/v24/load.py:7`、`:24`、`:71`。

Cordis 的 `v24_cordis.runs` 使用 `id/state jsonb/remaining_steps`，没有 `turn_no`；其 chat_tool reducer 在 state 内递增 `step`。它是有独立 DP 计划及 gate 的 Cordis v2 开发线，不能仅凭目录存在就称默认 runtime，也不能贬称为无实现的概念实验。DP4 文档明确说明自己的 production run_start/settlement，同时要求冻结 `v24/sql` 哈希不变。对本次 host/UI 对标，“正式模型”应写成“当前 host/UI 绑定的冻结 v24 模型”；Cordis 另列。证据：`pg-agent/v24/cordis/sql/16_runs.sql:1`；`pg-agent/v24/cordis/sql/43_loop.sql:132`、`:146`、`:152`；`pg-agent/v24/cordis/dp4/README.md:3`、`:15`。

**A4 — UI session 是 conversation 容器；UI turn 与内核 turn 是两套事实。** `SessionStore` 分别持久化 `sessions.json` 与 `turns.jsonl`。conversation 有 UUID、resume token 的 SHA256、时间、bindings 列表和 active_binding；binding 含 scope/run/realm/workspace/toolset/catalog digest。UI turn 行实际有 `conversation_id/run_id/seq/user_text/created_at`，并非只有 user_text/run_id；没有独立 UUID turn_id。证据：`pg-agent/v24/ui/sessions.py:51`、`:132`、`:147`、`:202`。

conversation 对 run binding 为 `1:0..N`，保存最近 200 个去重 run；conversation 对 UI turn 行也保留最多 200 条。**一个 run 可关联多条 UI turn**：steer 会在当前 run 下追加用户行，history 注释也明确 steer/answer 可复用同一 run。history 按 run_id 合并 user_text，再读取该 run 的 `result.final_text`，并非逐条 UI turn 各配一次 final。UI turn 的 seq 与内核 effect settlement 的 turn_no 不可互换。证据：`pg-agent/v24/ui/sessions.py:159`、`:189`、`:218`、`:222`、`:227`；`pg-agent/v24/ui/app.py:417`、`:421`。

### B. pi 的两套 session 与三层记录

**B1/B3 — 两套 session 不能合并成同一个产品模型。** durable 的 `Session` 是一个 mutation line、事务和 tracked documents 的所有者，`commit/close/observe/snapshot` 是存储运行时接口；它可以管理多条 conversation，不是用户聊天的同义词。durable `HarnessImpl extends SessionImpl`，`ConversationImpl` 是另外的 id 句柄。证据：`pi/packages/durable/src/types.ts:1187`、`:1188`、`:1193`；`pi/packages/durable/src/harness/harness.ts:110`、`:209`。

coding-agent 的产品级会话则是 `SessionHeader {type:'session', id, version, timestamp, cwd, parentSession?}` 加带 `id/parentId` 的 entry 树；当前格式版本为 3。AgentSession 直接使用 agent-core，`message_end` 时将 system/user/assistant/toolResult 写到自身 SessionManager。依赖清单中 coding-agent 不依赖 durable，durable 也不依赖 coding-agent/agent-core；在 coding-agent 全树与 durable/src 的交叉搜索只找到“保持 shell 行为同步”的注释，**未发现 JSONL SessionManager ↔ durable Conversation/Task 的适配或 import 链**。这是当前受检源码范围的否定结论，不是禁止未来出现适配层。证据：`pi/packages/coding-agent/src/core/session-manager.ts:1`、`:41`、`:43`、`:57`；`pi/packages/coding-agent/src/core/agent-session.ts:18`、`:133`、`:1162`、`:1181`；`pi/packages/coding-agent/package.json:43`；`pi/packages/durable/package.json:155`；交叉提及仅为 `pi/packages/coding-agent/src/utils/shell.ts:12`、`:30` 与 `pi/packages/durable/src/env/node.ts:208`。

| durable 记录层 | 身份、归属与事实权威 |
| --- | --- |
| ConversationRecord | `id`；可选 `parent={conversationId,at}` 表达 fork 历史截止点；独立的 `owner={conversationId,taskId}` 表达创建归属、abort/idle 子树。历史祖先与任务所有权不是同一条边。`pi/packages/durable/src/types.ts:424`、`:427` |
| EntryRecord | 不可变事件 `id/conversationId/kind`；`model` 是模型消息、`data` 是应用数据；`head/edits` 控制可见模型上下文，`byTaskId` 可追到产生它的任务。entry 不是 turn，也不是一次调用。`pi/packages/durable/src/types.ts:457`、`:458` |
| SubmissionRecord | 一次准入的 input/write/continue 生命周期，输入可 queued/placed/done/unanswered；`requestId` 是 conversation 内去重键，answer 指向 EntryId。`pi/packages/durable/src/types.ts:495`、`:506`、`:531`；准入行为：`pi/packages/durable/src/harness/submissions.ts:235`、`:270` |
| TaskRecord | 持久状态机：TaskId、conversationId、kind/version/input、可选 owner TaskId、abortRequested、restarts 和 TaskState；终局结果保存在 outcome。它才是可等待、可恢复的执行工作记录。`pi/packages/durable/src/types.ts:686`、`:705`、`:750` |
| DocumentRecord | incarnation ID、kind/key、创建/退役序号，scope 可为 session/conversation/task；conversation 文档另规定 history/fork 策略。不是 transcript entry 的别名。`pi/packages/durable/src/types.ts:767`、`:780` |

**B2 — “没有独立 RunId”证实；“run 不持久化”则不成立。** `LiveRun {taskId,inputs,turns,first?,afterRun?}` 位于 conversation 作用域 `pi.live` 文档中，`history:'latest', fork:'initial'`；它是可持久化的当前 run 控制投影，没有单独 RunRecord 表或稳定 RunId。`taskId` 是当前持有 run 的 generation task，可经 `handOver` 更换；不能把某一个 TaskId 当整个 logical run 的永久 ID。busy 以 `live.run !== undefined` 判定，因此每个 conversation 至多一条当前 LiveRun，但其工具/后台任务可以有多条。证据：`pi/packages/durable/src/harness/live.ts:138`、`:158`、`:194`；`pi/packages/durable/src/harness/submissions.ts:254`；`pi/packages/durable/src/harness/generation.ts:1148`、`:1163`。

**B4 — 两种 turn 不同，并需修正“纯 model request”的措辞。** agent-core 的一轮先发 `turn_start`，执行一次模型响应，然后执行其工具批次并把 toolResults 加回上下文，最后发 `turn_end {message,toolResults}`。所以它以一次模型响应为中心，但包含随后的工具执行，不是工具各占一个 turn；该循环自身没有分配持久 TurnId，外层 coding-agent 会把消息落成 entry。证据：`pi/packages/agent/src/agent-loop.ts:127`、`:220`、`:258`、`:284`、`:305`；消息持久化：`pi/packages/coding-agent/src/core/agent-session.ts:1162`。

`LiveRun.turns` 则只数工具轮：计数在模型 tool calls 转成 tool tasks 的同一次 commit 中 +1，随后返回 waiting/allSettled，**不是等待整批工具完成后才 +1**；无工具的 final answer 不加。startRun 初始化为 0；onYield continuation 会保留 logical run、handover 到下一 generation，并把 turns 重置为 0。重试 phase、单个工具数量与 task 数都不等于此计数。证据：`pi/packages/durable/src/harness/live.ts:143`；`pi/packages/durable/src/harness/generation.ts:1006`、`:1025`、`:1032`、`:858`、`:1149`。

### C. repoprompt-ce 的 session / turn / run-attempt

**C1 — 证实。** `AgentSession: Codable` 当前序列化版本 9，有稳定 `id`、可选 transcript、配置、providerSessionID、父会话与用量等。transcript 是结构化正文权威；新存档的 legacy items 留空后可由 transcript 重建。`AgentTranscriptTurn: Codable` 有 UUID、request anchor、responseSpans、terminalState、时间、retention/summary；它是转录和展示边界，不是一次 provider 调用或一次 attempt。证据：`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentSession.swift:150`、`:157`、`:171`、`:176`、`:201`、`:242`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Models/AgentTranscriptModels.swift:701`。

**C2 — 证实 runtime ownership，但必须区分三种 ID。** `AgentRunOwnership` 的 `attemptID/binding/turnEpoch?` 是 runtime attempt token；binding 含 tab、持久 session、binding generation 与临时 activation generation。`beginRunAttempt` 默认新建 attempt UUID、消费 preparedEpoch，然后委托 lifecycle；它刻意保留已安装的 process runID。它不是磁盘上的 RunRecord。证据：`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentRunLifecycleContracts.swift:4`、`:8`、`:35`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentTabSession.swift:966`、`:990`、`:2094`、`:2105`、`:2113`。

**旧 `runID=sessionID` 只能限定到 DirectHeadless 路径。** 当前 `DirectHeadlessProviderCoordinator` 仍明确 `let runID = sessionID`，以 sessionID 注册 AgentRecord 并开 epoch；旧文档此项的行号 `:206–207` 仍有效。**App 路径不是此别名**：`AgentModeProcessRunIdentity.startFreshProcessRun` 使用独立 UUID，Claude runner 可复用已有 controller 的 process runID，或创建新 UUID。故“一个 CE session 永远恰好一个 run UUID”被当前 App 代码证伪；也不能反过来说整个 CE 从不令两者相等。证据：`repoprompt-ce/Sources/RepoPromptMCPCore/DirectHeadlessProviderCoordinator.swift:206`、`:207`、`:219`、`:236`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeProcessRunIdentity.swift:40`、`:48`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Runners/ClaudeIntegratedAgentModeRunner.swift:115`。

**C3 — start 新建 session 证实；不能据此推断不能 resume。** 当前 App `agent_run.start` 对非空、经 normalizedString 解析的 session_id 明确报错；这是语义上的“拒绝指定已有目标”，不是声称原始 JSON 出现空值字段也一定命中同一判断。已有会话可走 `agent_manage.resume_session`，或 `agent_run.steer(session_id)` 重建控制 context 并继续。resume_session 会 hydrate/授权/配置并绑定原 session；已有匹配 control 注册则复用，整个函数本身不发送新用户任务。证据：`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:496`、`:1543`；`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentManageMCPToolService.swift:992`、`:1026`、`:1089`、`:1174`。

**C4 — turnID 就是 transcript turn UUID；该交叉引用不是唯一一处。** 用量定义中的 runID/turnID 都可空；正常用量和 compact 的零成本边界都写 `runID: session.runID`、`turnID: session.transcript.turns.last?.id`。此外 responseSpan 也可留 process runID：`retainProcessRunID` 定位指定 transcript turn 的最后一个 span 并写 runID；因此并非只有 usage 才能关联 run 与 turn，更不是到持久 RunRecord 的外键。证据：`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentSession.swift:39`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Usage/Claude/ClaudeContextUsageEstimator.swift:193`、`:259`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeProcessRunIdentity.swift:13`、`:24`、`:33`。

**C5 — turn 的创建/关闭由正文分组决定，不能按 attempt 数推算。** 当前投影器按 sequenceIndex 排序 items；每遇 `.user` 先 flush 上一 turn，再以 `item.id` 建 request turn；没有 user 的孤立活动可建 request=nil 的 turn。活动被追加到当前 response span，尾 turn 是否关闭取决于 terminalState.isActive；finalizeTurn 写 terminalState/completedAt。模型结构允许多 spans，但该分组代码不会因为 retry/cancel/attemptID 自动增加 span。证据：`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Transcript/AgentTranscriptServices.swift:3048`、`:3073`、`:3093`、`:3118`、`:3164`、`:3169`、`:4677`。

| 行为 | 对 attempt / transcript 的实际影响 |
| --- | --- |
| Claude resume fallback / 应用重试 | 记录 retrying，明确沿用同一个 canonical attempt 和 process identity；重试本身不插 user anchor，不能推成新 transcript turn 或必有新 span。`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Claude/ClaudeAgentModeCoordinator.swift:855`、`:876` |
| cancel | 捕获 active ownership；没有时可为取消建立 ownership，然后以 expectedRunID + ownership 提交 cancelled。取消本身不是追加用户请求的入口。`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeRunService.swift:1522`、`:1543` |
| 接受普通输入 / steer | 共享输入路径明确在接受 steer 后追加 `.user` item，其 id 变成新的 transcript turn anchor；active Claude native steer 仍可使用原 runID/ownership，故同一 attempt 可跨多个 transcript turns。`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentModeViewModel.swift:20454`、`:20457`、`:20467`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeRunService.swift:1242` |
| ask_user respond | 不追加 `.user` item，结果经 ask_user tool_result 展示并恢复 continuation，因此不能把每次 respond 计成新 transcript turn。`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentModeViewModel.swift:24303` |

**旧“steer 只加 epoch 不换 run”已不适合作统一描述。** App MCP active steer 直接 dispatch，没有在该入口开新 epoch；inactive steer 明确用 `.steering` transition 开新 epoch，随后执行会建立 attempt，process runID 是否复用由 runner 决定。epoch 自身的 ordinal 单调推进，只有 `.unrelated` 递增 continuityGeneration；它是控制围栏而不是 transcript turn 序号。证据：`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:1564`、`:1579`、`:1583`；`repoprompt-ce/Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift:360`、`:370`、`:374`、`:384`。

### D. 基数矩阵（session:turn:run 及相邻对象）

下表的 N 为跨生命周期累计，`0..1` 特别标明同时存活的投影；计数值不是实体行数。

| 实现/层 | 容器 → 相邻对象 | turn 与执行对象的关系 | 证据 |
| --- | --- | --- | --- |
| v24 冻结 DB | scope `1:N` runs；run `0..1` parent、`0..N` children；同 parent/spawn_key 唯一 | run `1:N` business effects；每次首次有效 settlement 推进一个 turn_no（另见 recovery 特例），无 TurnId/turn 表 | `pg-agent/v24/sql/10_schema.sql:25`、`:62`、`:66`、`:73`；`pg-agent/v24/sql/48_loop.sql:1988` |
| v24 UI | conversation `1:0..N` run bindings，单个 active_binding；conversation `1:N` 用户行 | run `1:N` UI 用户行，和 DB turn_no 无固定倍数；每 run 可有很多 model/tool settlements | `pg-agent/v24/ui/sessions.py:136`、`:159`、`:202`、`:222` |
| pi coding-agent | JSONL session `1:N` entries，entry `0..1` parent，整体可成树 | 一个 agent-core loop 有 N 个模型响应中心的 turn；一个 turn 内可有 N 个 toolResults，落盘的是 messages/entries | `pi/packages/coding-agent/src/core/session-manager.ts:43`、`:57`；`pi/packages/agent/src/agent-loop.ts:284`、`:305` |
| pi durable | 存储 Session `1:N` conversations；conversation `1:N` entries/submissions/tasks/docs | conversation 同时 `0..1` LiveRun；一个 logical run 可横跨 N 个 generation tasks，inputs 可含 N 个 submissions；turns 数工具批次，可重置 | `pi/packages/durable/src/types.ts:427`、`:458`、`:495`、`:705`；`pi/packages/durable/src/harness/live.ts:138`；`pi/packages/durable/src/harness/generation.ts:860`、`:1163` |
| CE 持久正文 | AgentSession `1:0..1` transcript；transcript `1:N` turns；turn `1:0..N` spans；span 内活动序列 | turn 不是 attempt；一次 active steer 可在同 attempt 下加 turn，retry 可留同 turn；usage 与 span 可记录 process runID | `repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentSession.swift:176`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Models/AgentTranscriptModels.swift:701`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Transcript/AgentTranscriptServices.swift:3118` |
| CE App 执行 | TabSession 同时 `0..1` active ownership；持久 session 跨时间可有 N 个 attempts / process runs | process runID 可跨 attempts 复用；turn↔attempt 不存在可强制的一一映射，也无持久 attempt→turn 外键 | `repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentTabSession.swift:990`、`:2094`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Runners/ClaudeIntegratedAgentModeRunner.swift:115` |
| CE DirectHeadless 控制 | AgentRecord keyed by sessionID，控制 runID 是同值 UUID | 该路径的别名不约束 App process runID，也不等于 transcript turn | `repoprompt-ce/Sources/RepoPromptMCPCore/DirectHeadlessProviderCoordinator.swift:206`、`:207`、`:236`、`:257` |

可直接对标的是“conversation 容器”“可恢复的执行工作”“用户输入转录边界”和“迟到结果围栏”等职责，不能直接对齐一个通用 session:turn:run 三层外键树。尤其 v24 turn_no、pi LiveRun.turns、CE transcript turn 分别是 effect 结算数、工具批次数、正文请求分组。证据为本节各行及 A2/B4/C5 的创建、递增代码。

### E. 控制面与 resume / parent-child 回灌

**六动词作用对象及幂等/围栏。** pi 没有与 `agent_run` 同名同签名的完整六动词面，下表列的是最接近的实现入口，不能视为协议兼容。

| 动词 | v24 冻结内核 | pi（分别注明产品线） | CE App MCP |
| --- | --- | --- | --- |
| start | scope/owner/input/budget 准入新 run；写命令以 principal/request_key replay | durable `Conversation.submit(input)` 在 idle 时 startRun；coding-agent prompt 启动内存 loop，在现有 JSONL session 落消息 | `agent_run.start` 新建 session，拒绝有效 session_id；不是对既有 session 的 resume |
| poll | `run_id + after_revision`，纯读 | durable snapshot/watch/entries 或读取 Submission/Task；没有独立 RunId 的 poll | session_id 或 session_ids；经 executeWait(forcePoll:true) 读控制快照 |
| wait | run_id + registration_generation + epoch + event cursor；wait_check 只读 | durable Submission.wait / waitForTask / Conversation.waitForIdle，目标分别是 submission/task/conversation | session_id；内部 wait cursor 绑定 registration/epoch，过期、superseded 与 terminal 分开 |
| cancel | run_id + expected driving_generation + request_key；撤销后继发布资格，保留在途事实结算 | durable Conversation.abort / abortTask / queued Submission.abort，目标不同；coding-agent abort 当前 agent loop | session_id 寻址当前运行，内部捕获 ownership + expectedRunID；不是删除持久 session |
| steer | run_id + expected generation + instruction + request_key；同 run，新 epoch/generation，可能 pending_steer | durable `submit(input, whenBusy:'steer')` 到 inbox，边界加入当前 run；coding-agent steer 队列到下一模型轮 | session_id；active dispatch / inactive 开 steering epoch；managed lane 另走授权和幂等账本 |
| respond | run_id + interaction_id + expected generation + request_key，消费当前 interaction | durable 无这套统一 interaction RPC；应用可用提交/工具机制构造，不能冒充存在同签名 respond | session_id + interaction_id + payload，解析当前 pending interaction，随后 continuation |

v24 控制证据：`pg-agent/docs/designs/v24-pg-agent-2026-10-22.md:217`、`:223`；`pg-agent/v24/sql/47_verbs.sql:35`、`:73`、`:97`、`:147`、`:173`。pi 控制证据：`pi/packages/durable/src/harness/harness.ts:127`、`:171`、`:176`、`:181`；`pi/packages/durable/src/harness/submissions.ts:235`、`:270`、`:294`；coding-agent：`pi/packages/coding-agent/src/core/agent-session.ts:1924`、`:2296`、`:2519`。CE 控制证据：`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:455`、`:496`、`:1322`、`:1509`、`:1819`、`:1833`、`:1861`。

- **v24 幂等与围栏是不同层。** `(principal_id,request_key)` 比较规范请求字节/digest，命中返回原 response，异参数冲突；effect settlement 先比较已提交 receipt，未结算才校验 attempt/fence/owner；run driving_generation/epoch 决定可否发布后继。不能用 run_id 单独替代这些键。证据：`pg-agent/v24/sql/30_advance.sql:247`、`:254`、`:269`、`:284`；`pg-agent/v24/sql/48_loop.sql:601`。
- **pi 的 requestId 不等同 v24 的完整 payload digest 冲突检查。** durable admission 命中 conversation/requestId 时只检查 submission type，再返回已有 id/status；当前这段不比较新的 content。nested tool 的 key 则另外比较 tool name/arguments。任务提交围栏重新检查 invocation 未结束、task 仍 running、未被 durable abort mark 撤销。证据：`pi/packages/durable/src/harness/submissions.ts:235`；`pi/packages/durable/src/harness/tool.ts:902`；`pi/packages/durable/src/harness/scheduler.ts:2353`。
- **CE 的控制寻址不是围栏本身。** epoch 包含 runtime/session/activation/registration generation；beginEpoch 检查 expectedCurrentEpoch；App attempt 还检查 persistent binding 与 current ownership。普通六动词入口没有统一的 v24 request journal；`idempotency_key` 出现在 managed-lane 转发及其单独账本，不应推广到普通 start/steer/respond。证据：`repoprompt-ce/Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift:350`、`:374`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentTabSession.swift:2147`；`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:440`、`:471`、`:1799`、`:1833`。

**resume 至少有“重接执行”和“发新输入继续对话”两种含义。**

| 实现 | 恢复现有工作 | 继续对话 |
| --- | --- | --- |
| v24 | UI `/resume` 找回原 conversation binding，复用原 run_id；检查 profile/catalog/workspace/toolset，running 则再驱动、waiting 则投影交互、terminal 只展示，不重开终局 run。journal 按原 run 重建 provider 上下文，未确认结算可重送同 outcome/token。 | 在同 conversation 中对 terminal 后发送新任务走 start_run，产生新 run 并注入有限历史；active steer/respond 留在旧 run。证据：`pg-agent/v24/ui/app.py:544`、`:569`、`:579`、`:601`、`:404`；`pg-agent/v24/host/worker.py:1282` |
| pi durable | scheduler.open 把幸存 running task 改 pending、保留 TaskId/checkpoint 并增 restarts；resume 只是幂等地启用调度，不无条件 startRun，原 LiveRun 可继续。 | idle `continue` submission 明确调用 startRun，创建新 generation、turns=0；onYield continuation 则只 handOver 并重置 turns，是同 logical run。证据：`pi/packages/durable/src/harness/scheduler.ts:378`、`:401`、`:423`；`pi/packages/durable/src/harness/submissions.ts:270`；`pi/packages/durable/src/harness/generation.ts:858`、`:1148` |
| CE | resume_session hydrate 原 session、复用现有 control registration 或认领可恢复 session；claimResumableSession 从持久 lastEpochOrdinal+1 继续，保留 continuityGeneration。恢复控制 context 本身不等于启动 provider。 | 后续新输入建立新的 attempt；是否创建新 process run UUID 取决于 runner/controller 复用，providerSessionID/原生 thread ID 是另一层恢复身份；active steer 可留在同 attempt。证据：`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentManageMCPToolService.swift:1089`；`repoprompt-ce/Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift:288`、`:301`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentSession.swift:201`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentTabSession.swift:2094` |

pi coding-agent 的 resume 也应单列：`switchSession` 打开原 JSONL、teardown 当前 runtime，再用同一 SessionManager 创建新 runtime，并发布 reason='resume' 的 session_start；它不是恢复 durable Task/LiveRun。之后 prompt/continue 是新一次内存 loop 调用，不能套用 durable 的稳定任务恢复语义。证据：`pi/packages/coding-agent/src/core/agent-session-runtime.ts:196`、`:210`、`:212`、`:214`；`pi/packages/coding-agent/src/core/agent-session.ts:1924`。

**parent-child 结果回灌不能从 parent 边自动推出来。**

1. **v24 spawn：原子创建边和 child 首个 effect，返回句柄；未发现默认 child final → parent 下一模型的回灌。** spawn 与 parent settlement 同事务，写父/子事件、预算转移及 child rows，返回 run_id/spawn_key/child_effect_id。host 构建下一模型请求只读当前 run 的 journal；child 的 result 不会因为 parent_run_id 自动进入这个 history。UI 的历史注入是另一机制：按同 conversation 旧 run 的 final_text 构建 system prompt，并非 spawn join。证据：`pg-agent/v24/sql/48_loop.sql:1228`、`:1268`、`:1288`；`pg-agent/v24/host/worker.py:944`、`:1204`；`pg-agent/v24/ui/sessions.py:227`；`pg-agent/v24/ui/app.py:401`。
2. **pi nested tools：有明确调用返回，但不是自动 transcript 合并。** child tool task 归 caller task 所有，key 重放校验 tool/args；nested 结果写 caller 的 `NestedCallDoc`，调用端 waitForTask 后读回。模型直接发出的 tool 则另写 ToolResult entry。证据：`pi/packages/durable/src/harness/tool.ts:507`、`:528`、`:814`、`:829`、`:902`、`:924`。
3. **pi conversation fork/ownership：默认是历史继承与生命周期归属，不是结果 join；示例扩展显式实现回灌。** foreground subagent 示例创建 owned conversation，submit+wait，读取 answer EntryId 的模型文本，再把文本作为父工具输出；background 示例有独立 durable Reporter task，读取子 answer 后向父 conversation submit followUp，并用 requestId 去重。故“pi 完全没有自动回灌机制”过强：内核不因边自动回灌，示例扩展确实实现了自动投递。证据：`pi/packages/durable/src/types.ts:427`；`pi/packages/durable/src/harness/harness.ts:167`；`pi/packages/durable/test/examples/21-subagent-foreground.ts:33`、`:53`、`:67`、`:73`；`pi/packages/durable/test/examples/22-subagent-background.ts:100`、`:107`、`:115`。
4. **CE child 结果可以经工具回执返回；session link 是独立的持续投递机制。** `agent_run.wait` 返回 triggeringSnapshot；有 assistant preview 时序列化为有上限的 `assistant_text`，由调用工具的 parent 接收，而非复制整个 child transcript。oversight link 则有观察者本地 passive queue，样本包含 status/waitingOn/latestVisibleAssistantPreview；prompt claim 按 endpoint、资格和 membership fence 渲染要投递的批次，Auto-wake 的 admission 与 delivery 分属不同组件。不能把 parentSessionID、组织树、delegation scope 与已授权 observer link 当成同一条边，也不能宣称只要有 parent 指针就必定自动唤醒/注入全部结果。证据：`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:1894`；`repoprompt-ce/Sources/RepoPromptDomainRuntime/DomainAgentSessionModels.swift:643`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/SessionLinks/AgentSessionLinkPassiveStatusNotices.swift:4`、`:46`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/SessionLinks/AgentModeViewModel+SessionLinkPrompt.swift:704`、`:753`、`:840`；`repoprompt-ce/docs/architecture/agent-session-oversight-auto-wake.md:138`。
5. **CE handoff 是另一方向的一次性上下文前置。** pendingHandoff 保存在 session，发送时只有尚未 staged 的 payload 才前置，之后置 staged；periodic Auto-wake 不走这条前置。它是把已有上下文交给目标/恢复后的 provider，不是子代理完成结果自动向父合并。证据：`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentSession.swift:270`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentModeViewModel.swift:21982`、`:21997`。

### F. 与既有分析的出入（明确列出被证伪的说法）

| 原说法或待核问题 | 裁定与修正 | 当前证据 |
| --- | --- | --- |
| A1：内核只有 runs，无 session/turn 表 | 证实 session/turn/run 这一组中的表结构；不是说整个内核只一张表 | `pg-agent/v24/sql/10_schema.sql:25`；`pg-agent/v24/s1/setup_db.py:534` |
| A2：计数语义待核实 | 已解决：规格定义为 model/tool effect 各自结算步数，代码吻合；model 次数/工具批次数这两种候选解释排除，steer/respond 命令不加 | `pg-agent/docs/designs/v24-pg-agent-2026-10-22.md:271`；`pg-agent/v24/sql/48_loop.sql:1411`；`pg-agent/v24/sql/40_interpreters.sql:2700` |
| “cancel-late unknown 一律不加 turn” | 必须收窄到 recovery 合成 unknown；普通 settlement 不适用该泛化 | `pg-agent/v24/sql/49_recovery.sql:129`；`pg-agent/v24/sql/48_loop.sql:1411`、`:1419`、`:1988` |
| A3：默认运行时是哪套 SQL 待核实 | 已解决：host/loader 绑定冻结 v24；Cordis v2 是独立实现，其 state.step 不能直接替代当前 host/UI 模型 | `pg-agent/v24/load.py:8`；`pg-agent/v24/host/db.py:52`；`pg-agent/v24/cordis/sql/16_runs.sql:8` |
| A4：conversation:run=1:N，turn 行只是 user_text+run_id | 基数方向证实；字段描述需补全 conversation_id/seq/created_at，且 run:UI turn=1:N，不能从简述推出 1:1 | `pg-agent/v24/ui/sessions.py:202`、`:221`；`pg-agent/v24/ui/app.py:417` |
| B1/B3：durable Session 非对话、coding-agent JSONL 的类型关系未证实 | 前者证实；后者核查未发现适配/import。不能合并两条产品链 | `pi/packages/coding-agent/package.json:43`；`pi/packages/coding-agent/src/core/agent-session.ts:1181`；`pi/packages/durable/src/types.ts:1188` |
| B2：run 非独立表、LiveRun 挂 pi.live、无稳定 RunId | 证实；补充 LiveRun 是持久文档的当前控制块、taskId 可 handover。“不是表”不能被误读为“只是内存” | `pi/packages/durable/src/harness/live.ts:138`、`:194`；`pi/packages/durable/src/harness/generation.ts:1163` |
| B4：agent-core turn 就是纯 model request；LiveRun.turns 是同一个量 | 前者需包含响应后的工具批次；后者只计工具轮，且在工具准入时加，onYield 可重置 | `pi/packages/agent/src/agent-loop.ts:284`、`:305`；`pi/packages/durable/src/harness/generation.ts:1027`、`:860` |
| C2/C4：无持久 run 对象；usage 可能是唯一显式 run→turn 关联 | 独立持久 RunRecord 未见，ownership 的 runtime 性质证实；“唯一关联”被证伪，run UUID 也可留在 response span | `repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeProcessRunIdentity.swift:13`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Usage/Claude/ClaudeContextUsageEstimator.swift:259` |
| C3：start 是否拒绝 session_id、是否有 resume 路径待核实 | start 的非空目标拒绝仍成立；同时存在 resume_session 和 steer 复用/重建旧 session 控制 context 的路径 | `repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:496`；`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentManageMCPToolService.swift:992` |
| C5：retry/cancel/steer 的 turn/span 基数待核实 | 正文 user anchor 决定 turn；retry 可同 attempt，steer 可新 user turn，respond 不插 user；两种“一律新 turn/一律加 span”的概括均无依据 | `repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/Transcript/AgentTranscriptServices.swift:3118`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentModeViewModel.swift:20457`、`:24303` |
| 2026-10 旧 CE 结论：runID=sessionID | DirectHeadless 当前仍成立；推广到 App process runID 则被证伪。旧文档已提醒 span/usage 是另一种 runID，本次进一步定位 App 分配入口 | `pg-agent/docs/designs/v20-ce-native-design-5-2026-10-13.md:28`、`:34`；`repoprompt-ce/Sources/RepoPromptMCPCore/DirectHeadlessProviderCoordinator.swift:206`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeProcessRunIdentity.swift:40` |
| 2026-10 旧 CE 结论：steer 只加 epoch 不换 run、一个 session 一个 run | 当前须区分 backend、active/inactive、process/attempt；App active 入口不统一开 epoch，inactive 开 epoch，process ID 可复用或新建 | `pg-agent/docs/investigations/v20-epoch-operation-for-v13-ce-control-2026-10-14.md:57`；`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:1564`、`:1579` |

旧证据位置漂移也已确认：start 拒绝从旧 `AgentRunMCPToolService.swift:455` 移到当前 `:496`；AgentTranscriptTurn 从旧 `:437` 移到当前 `:701`；beginRunAttempt 当前为 `AgentTabSession.swift:2094`。DirectHeadless `:206–207`、claimResumableSession `:288` 及其 ordinal 恢复 `:301` 仍可对应。旧文档中的 `v20_runs/v20_turns` 是 pg-agent 的拟建/实现控制结构，**不能当成 CE 当前 Swift 持久表**；“transcript turn 与控制回执两套”这一职责区分仍应保留。证据：`pg-agent/docs/designs/v20-ce-native-design-5-2026-10-13.md:32`、`:44`；`repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Models/AgentTranscriptModels.swift:701`；`repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift:496`。


## Investigation Log

### Phase 1 — Triage
**Hypothesis:** 三个项目都实现了 session/turn/run，只是命名或实现介质不同，应该能建立一张一一对应的三层表。
**Findings:** 初步扫描即发现三者不在同一层轴上：v24 的 SQL 只有 `runs`（带 `turn_no`），没有 session/turn 表；pi 的 `durable` 有 `Session`（存储事务）与 `Conversation/Entry/Submission/Task` 记录层，而 `coding-agent` 的 session 是 JSONL 文件；RepoPrompt 的 `AgentTabSession`/`AgentSession`/`AgentTranscriptTurn` 与 runtime 的 `AgentRunOwnership` 分属不同寿命。
**Evidence:** `v24/sql/10_schema.sql:25`；`pi/packages/durable/src/types.ts:1188`；`pi/packages/coding-agent/src/core/session-manager.ts:41`；`repoprompt-ce/.../AgentTranscriptModels.swift:701`。
**Conclusion:** 原假设需修正为"职责可对标、对象不可直接对齐"；进入 Phase 2/3 做跨仓选材与逐条核实。

### Phase 2 — 广域选材（context_builder）
**Hypothesis:** 让选材代理跨三仓找出所有"容器 / 记账 / 执行"候选，再用两路独立分析交叉验证。
**Findings:** 产出覆盖 v24 冻结内核、host journal、UI session、Cordis v2；pi durable 类型表、LiveRun、generation 相位机、coding-agent JSONL；RP AgentSession、transcript、ownership、MCP 六动词。两路分析在"v24 turn = effect 结算数""pi 两套 session""RP transcript turn ≠ run"上一致。
**Evidence:** 选区与 `## Investigator Findings` A–F。
**Conclusion:** 方向确认；剩余 P0 缺口交给 pair 核实。

### Phase 3 — Pair 核实
**Hypothesis:** 需要证伪或补证六件事：v24 turn 的全部递增入口、冻结 v24 与 Cordis 的加载关系、UI turn 的基数、pi 两条产品线是否有适配层、pi 两种 turn 的边界、RP turn/attempt/process-run 的基数与 resume 路径。
**Findings:** 六项全部有结论；额外发现 v24 普通 tool settlement 的 cancel-late 路径与规格文字不一致，以及 RP `runID=sessionID` 只对 DirectHeadless 成立、App 使用独立 process UUID。pi 的 parent/owner 边不自动合并结果，但仓库示例显式实现了前台/后台回灌。
**Evidence:** 见 `## Investigator Findings` A–F 与下方抽查。
**Conclusion:** 事实基线足够；进入 Phase 4 做设计综合。

### Phase 4 — 抽查（本 agent 直接读码）
对 pair 的承重结论做了独立抽查，全部命中：

| 抽查点 | 实际内容 | 结论 |
|---|---|---|
| `v24/sql/48_loop.sql:1411` | `v_turn := r.turn_no + 1`（tool settlement 入口） | 证实 |
| `v24/sql/48_loop.sql:1986-1990` | validator 强制 `turn_no = r.turn_no + 1`、`revision + 1` | 证实 |
| `v24/sql/48_loop.sql:2904-2906` | applier 无条件 `turn_no = v_turn` | 证实；cancel-late 的 tool 路径确实会把计数 +1 |
| `v24/sql/49_recovery.sql:122-129` | recovery 的 cancel-late 明确 `v_turn := r.turn_no` | 证实；与上一条构成入口差异 |
| `pi/.../live.ts:138-146` | `LiveRun.turns` 注释为 tool rounds，onYield 重置 | 证实 |
| `pi/.../generation.ts:1025-1027` | 工具准入同一次 commit 里 `live.run.turns += 1` | 证实 |
| `pi/.../generation.ts:858-860` | continuation 时 `live.run.turns = 0`，同一 logical run handOver | 证实 |
| `repoprompt-ce/.../AgentTranscriptServices.swift:3117-3125` | 遇 `.user` 先 flush 上一 turn，再以 `item.id` 建新 turn | 证实 |
| `repoprompt-ce/.../AgentModeProcessRunIdentity.swift:40-48` | `startFreshProcessRun` 用新 UUID；`ensureProcessRunID` 可复用 | 证实 |
| `repoprompt-ce/.../AgentRunMCPToolService.swift:495-498` | `agent_run.start` 拒绝显式 session_id | 证实 |

### Phase 5 — 设计综合（oracle）
**Hypothesis:** 在"不加第二套状态机、不把 provider 原文搬进 DB、不建 turns 表"的约束下，v24 可以用 projection 同时表达 Pi 与 RP 的会话/轮次语义。
**Findings:** 两路 oracle 在"保留 run/effect、Turn 与 RunAttempt 都不建表、增加 conversation 锚、四种计数分离、parent-child 显式投递"上一致。分歧集中在两处：(a) 会话锚用独立 `conversation_id` 还是 `conversation_root_run_id`；(b) cancel-late 的结算计数应当"不推进"还是"所有首次 receipt 都推进"。见 `## Root Cause / Mechanism Map` §8 的取舍表。
**Evidence:** Oracle 两路回答（本报告 §8 已按证据合并，冲突单列）。
**Conclusion:** 可以给出可执行的最小落地顺序；两处分歧需要用户/架构拍板，不在本调查中擅自定案。

## Root Cause / Mechanism Map

### 1. 为什么"三层"这个提法本身会误导

三个项目都在用 session / turn / run 三个词，但它们切分的**轴**不同：

| 项目 | 容器轴 | 记账轴 | 执行轴 | 一句话 |
|---|---|---|---|---|
| pg-agent v24（冻结内核） | **没有内核 session**；UI conversation 是宿主文件，内核不感知 | **effect settlement**（`runs.turn_no` 是计数器，不是对象） | **run**（唯一带预算、控制世代和终态的执行对象） | run-centric：run 是主语，turn 是它的结算序号 |
| pi / coding-agent | **JSONL session 文件**（id/parentId entry 树） | **entry**（不可变消息/状态节点） | **内存 agent loop**（`agentLoop` 纯函数，无持久身份） | file-centric：会话就是那棵树，loop 不落身份 |
| pi / durable | **Conversation**（存储 Session 管理多条） | **Entry / Submission**（输入生命周期）+ **Task**（工作状态机） | **generation task**；logical run 是 `pi.live` 文档里的 `LiveRun` | task-centric：工作可跨 generation 交接，run 没有稳定 ID |
| RepoPrompt CE | **AgentSession**（持久 JSON + transcript） | **AgentTranscriptTurn**（用户请求 anchor + response spans） | **run attempt**（runtime ownership token，不落盘） | transcript-centric：正文与执行身份分开 |

证据：`v24/sql/10_schema.sql:25`、`v24/sql/48_loop.sql:588`；`pi/packages/coding-agent/src/core/session-manager.ts:41-57`；`pi/packages/agent/src/agent-loop.ts:127`；`pi/packages/durable/src/types.ts:1188`、`harness/live.ts:138`；`repoprompt-ce/.../AgentSession.swift:150`、`AgentTranscriptModels.swift:701`、`AgentRunLifecycleContracts.swift:4`。

> 结论：不存在一个三家共有的"session 层 / turn 层 / run 层"。存在的是**四种职责**：会话容器、输入接纳、执行工作、事实结算。三个项目把这些职责分配到不同对象上，而且常常一个对象承担多项。

### 2. 对象对照总表（按职责，不按名字）

| 职责 | v24 | pi coding-agent | pi durable | RepoPrompt CE |
|---|---|---|---|---|
| 会话容器（跨多次执行） | **UI conversation**：`sessions.json` 的 `conversation_id` + bindings；内核无此对象 | **Session 文件**：`SessionHeader.id`，`parentSession` 指父文件 | **ConversationRecord**：`id`，`parent{conversationId,at}`，`owner{conversationId,taskId}` | **AgentSession**：`id`，`parentSessionID`，`organizationalParentID` |
| 一次用户输入 / 请求边界 | **UI turn 行**：`conversation_id,run_id,seq,user_text`；内核用 command effect（start/steer）承载 | **message entry**（user）+ `prompt()` 调用 | **SubmissionRecord(type=input)**：queued→placed→done/unanswered | **AgentTranscriptTurn.request**（`AgentTranscriptRequestAnchor`） |
| 当前执行工作 | **runs**：`run_id`，status，预算，interaction，pending_steer，result | **内存 loop**（无持久对象） | **TaskRecord**（`pi.generation`）+ **LiveRun**（`pi.live.run`，无稳定 RunId） | **AgentRunOwnership**（runtime attempt）+ process runID（可复用） |
| 不可变事实 / 记账单位 | **effects**（model_call/tool_call，确定性 id）+ **events**（append-only） | **entry**（JSONL 追加） | **EntryRecord** + **Task checkpoint/outcome** | **response span / activity**（transcript 内） |
| 结算序号 | `runs.turn_no`（model 与每个 tool 各 +1） | 无 | `LiveRun.turns`（工具轮，可重置） | `AgentTranscript.turns[]` 序号（请求分组） |
| 当前态投影 | runs 行 + `v24.poll(run_id, after_revision)` | 内存 messages + `SessionContext` | `pi.live` 文档 | `DomainAgentRunSnapshot`（不落盘） |
| 幂等 / 围栏 | `(principal,request_key)` + `effect.attempt/fence` + `(epoch,generation)` | 无（单进程） | `requestId` + task invocation 检查 + abort mark | binding generation + ownership + `expectedRunID`；无统一 request journal |

关键证据：
- v24 无 session/turn 表：`v24/sql/10_schema.sql:25`（`runs` 定义）、`:62`（无 session 表）；UI 侧：`v24/ui/sessions.py:132-160`。
- pi durable 的 `Session` 是存储事务：`pi/packages/durable/src/types.ts:1188`（`commit/mintId/snapshot`）。
- pi 两套 session 无 import 关系：`pi/packages/coding-agent/package.json:43` 不依赖 durable；`agent-session.ts:1181` 用 SessionManager 落 entry。
- RP transcript turn：`repoprompt-ce/.../AgentTranscriptModels.swift:701`；ownership：`AgentRunLifecycleContracts.swift:4-40`。

### 3. 四种 turn 口径必须分开命名

这是本次调查最重要的结论。三家说的 "turn" 至少是四个不同的量：

| 口径 | 定义 | 谁在用 | 递增/重置规则 | 证据 |
|---|---|---|---|---|
| **`effect_settlement_no`** | run 内**首次提交**的 business effect（model_call 或 tool_call）结算数 | v24（`runs.turn_no`） | model 一次 +1，每个 tool 各 +1；`model → N 工具 → model` = **N+2**；cancel-late 有入口差异 | `v24/sql/48_loop.sql:588`、`:1411`、`:1988`；`docs/designs/v24-pg-agent-2026-10-22.md:271` |
| **`model_round_no`** | 以一次模型响应为中心的轮次（含其后的工具批次） | pi agent-core（`turn_start/turn_end`） | 每个模型请求 +1；`turn_end` 在工具批次之后 | `pi/packages/agent/src/agent-loop.ts:127`、`:284-305` |
| **`tool_round_no`** | 已准入的工具批次数 | pi durable（`LiveRun.turns`） | 工具 calls 转 tool tasks 的**同一次 commit** +1；final answer 不加；onYield continuation 清零 | `pi/packages/durable/src/harness/live.ts:143`；`generation.ts:1025-1027`、`:858-860` |
| **`user_turn_no`** | 已提交的用户请求边界 | RP `AgentTranscriptTurn`；v24 UI turn 行 | 每个 user anchor +1；steer 产生新 anchor；respond 不产生；retry/cancel 不产生 | `repoprompt-ce/.../AgentTranscriptServices.swift:3117-3125`；`v24/ui/app.py:415-421` |

同一段执行 `model → tool A、tool B → model final` 的正确读数是：

```text
effect_settlement_no = 4   （model + tool A + tool B + model）
model_round_no       = 2
tool_round_no        = 1
user_turn_no         = 1
```

四个数不能通过改名或除法互相转换。v24 规格已经明确 `turn_no` 是第一个口径；把 `turn_no` 直接当 `maxTurns` 或 sidebar 的"轮数"会分别导致提前截断和统计膨胀。

### 4. 基数矩阵（跨生命周期累计）

| 关系 | 基数 | 强制方式 | 证据 |
|---|---|---|---|
| conversation : run | `1 : N`，同时至多 1 个非终态 | v24 **当前无约束**（UI 只保留 active_binding）；pi/RP 天然 0..1 active | `v24/ui/sessions.py:159`；`pi/.../live.ts:194`；`repoprompt-ce/.../AgentTabSession.swift:990` |
| run : business effect | `1 : N` | `effects.run_id` + 每 run 至多一个在飞 model_call | `v24/sql/10_schema.sql:66`、`:110` |
| run : user turn | `1 : N`（start + 若干 steer） | 仅 UI 记账；DB 无 user turn 对象 | `v24/ui/sessions.py:202`；`v24/ui/app.py:417` |
| user turn : model round | `1 : N` | 无强制（派生） | 由 effect 的 generation 归属推导 |
| model effect : tool batch | `1 : 0..1` | `tool_effect_id(parent, ordinal)`，ordinal ≤ 15 | `v24/sql/48_loop.sql:780-800` |
| business effect : settlement | `1 : 0..1` | `effects.status` 终态 + receipt 唯一 | `v24/sql/48_loop.sql:1986-1990` |
| parent run : child run | `1 : N`；(parent, spawn_key) 唯一 | `u_runs_spawn` | `v24/sql/10_schema.sql:73` |
| RP AgentSession : transcript turn | `1 : 0..N`（同时 0..1 transcript） | 无 DB；JSON 内数组 | `AgentSession.swift:176`；`AgentTranscriptModels.swift:826` |
| RP transcript turn : response span | `1 : 0..N` | 投影器按 `.user` 分组 | `AgentTranscriptServices.swift:3117` |
| RP session : run attempt | `1 : N`；同时 0..1 active | runtime ownership + binding 四重围栏 | `AgentTabSession.swift:2094-2147` |
| pi Conversation : Entry/Submission | `1 : N` | store 外键/索引 | `pi/.../types.ts:427`、`:458`、`:506` |
| pi Conversation : LiveRun | `1 : 0..1`（同时） | `live.run !== undefined` 即 busy | `pi/.../live.ts:194` |
| pi logical run : generation task | `1 : N`（handOver） | `live.run.taskId` 指向当前 task | `generation.ts:1148-1163` |

### 5. 事实权威：没有一家是"单文件说了算"

| 事实领域 | v24 | pi coding-agent | pi durable | RepoPrompt CE |
|---|---|---|---|---|
| 执行状态 | **DB**（runs/effects/events） | 内存；进程亡则丢 | **store**（Task/Submission/Document） | **runtime**（ownership/snapshot）+ provider 回调 |
| 会话成员/历史 | **UI 文件**（sessions.json/turns.jsonl） | **JSONL 文件** | **Conversation/Entry** | **AgentSession JSON**（transcript 为正文权威） |
| provider 原文 | **host journal**（DB 不拥有） | JSONL entries（本身即原文） | EntryRecord（已提交消息） | transcript items + provider 原生 session |
| 列表/统计 | UI 元数据 | 文件扫描 | store 查询 | **独立 metadata index**（从 turns 派生计数） |
| 外部工作是否已发出 | **journal 的 dispatch 阶段**与 DB 结算分离 | 不适用 | task checkpoint | provider runtime 事件 |

v24 的规格原文是"DB 不拥有 provider 对话原文；跨 turn 的 assistant/tool 消息由受信 host journal 承载"（`docs/designs/v24-pg-agent-2026-10-22.md:56`）。pi coding-agent 的 JSONL 与 durable store 是**两条独立产品线**，没有适配层（`package.json:43`；交叉搜索只找到 shell 行为注释）。RepoPrompt 的 session JSON、metadata index、transcript 三者也不是同一事务（`AgentSessionDiskWriter.swift:31-156` 只保证单文件原子替换）。

### 6. 生命周期与控制面落层

| 操作 | v24 | pi | RepoPrompt |
|---|---|---|---|
| start | 新 **run**（run_id 稳定） | durable：新 LiveRun / 新 generation task；coding-agent：新内存 loop | 新 **session**（`agent_run.start` 拒绝 session_id），内部再建 attempt |
| poll/wait | `run_id + after_revision` / `registration_generation` | submission/task/conversation 三种等待对象 | `session_id` → 当前 snapshot |
| cancel | `run_id + driving_generation`；撤销后继，保留在途结算 | abort task / abort submission / abort loop | `session_id` → ownership + expectedRunID |
| steer | 同 run，新 epoch/generation，`pending_steer` 单槽 | durable：inbox（可多条）；coding-agent：下一轮 steering 队列 | active：直接 dispatch；inactive：开 `.steering` epoch |
| respond | `run_id + interaction_id + generation` | 无统一 respond 协议 | `session_id + interaction_id` |
| resume（重接执行） | 复用原 run_id + journal 重放 | scheduler 把 running task 改 pending，保留 TaskId/checkpoint | hydrate 原 session，认领可恢复 epoch |
| resume（继续对话） | 新 run，注入有限历史 | 新 run（`continue` submission） | 新 attempt（process runID 可复用） |
| fork | spawn 子 run（独立预算，不复制历史） | Conversation.parent（历史截止点） | parentSessionID / 新 session |
| compaction | 无内核对象 | JSONL compaction/context_edit entry；durable compaction task | transcript retention/summary + compaction frontier |
| 子代理结果回灌 | **无自动机制**；spawn 只建边 | 内核不合并；示例扩展显式回灌 | 工具回执 / oversight link / handoff 三种机制 |

证据：`v24/sql/47_verbs.sql:35-173`；`v24/ui/control.py:160-232`；`pi/.../harness.ts:127-181`；`pi/.../scheduler.ts:378-423`；`repoprompt-ce/.../AgentRunMCPToolService.swift:455-496`、`:1322-1372`、`:1509-1584`、`:1819-1870`；`AgentManageMCPToolService.swift:992-1174`。

### 7. 对标结论：哪些能对齐，哪些不能

**可直接对齐（职责级）**

1. **会话容器**：v24 的 conversation ↔ pi Conversation ↔ RP AgentSession。都可承载跨多次执行的成员关系；都应有稳定 id。
2. **用户请求边界**：v24 的 command_start/command_steer ↔ pi Submission(input)/user entry ↔ RP `AgentTranscriptTurn.request`。都以"用户输入"为分界，respond 不分界。
3. **执行工作**：v24 run ↔ pi LiveRun/GenerationTask ↔ RP run attempt。都以"一次可恢复的执行"为单位，都可被 cancel/steer。
4. **不可变事实**：v24 effect/event ↔ pi Entry/Task checkpoint ↔ RP span/activity。都强调"已提交事实不可改写，迟到事实只记账"。

**同名异义（不能直接映射）**

| 词 | 歧义 |
|---|---|
| session | v24 = UI 缓存；pi = 存储事务 / JSONL 文件 / Conversation；RP = 持久会话 |
| turn | effect 结算数 / 模型轮 / 工具轮 / 用户请求边界 |
| run | 稳定 DB 行 / 文档内控制块 / runtime ownership token / provider process |
| attempt | effect claim 重试 / 控制世代 / RP attemptID / RP retrying |
| parent | spawn 谱系 / fork 历史 / 任务所有权 / 组织树 / 授权投递 |

**当前缺失（v24 侧）**

1. **没有跨 run 的会话身份**：conversation 只活在 `sessions.json`，DB 无法回答"哪些 run 属于同一会话""当前是否已有活跃 run"。
2. **没有用户请求边界的持久对象**：UI turn 行是缓存，command payload 里有文本但没有统一的 anchor 语义。
3. **没有把四种计数分开命名**：`turn_no` 一个词承担了"结算数"和"轮数"的直觉。
4. **cancel-late 的计数规则在两个入口不一致**：recovery 保留，普通 tool settlement 推进。
5. **没有显式的子代理结果投递**：spawn 只建边，parent 不会自动拿到 child 的 final。

### 8. 给后续设计的线索：v24 的最小对标合同

在"不建第二套状态机、不把 provider 原文搬进 DB、不建 turns 表"的约束下，建议把合同写成下面五条。

#### 8.1 对象：保留两个权威，增加一个分组，拒绝两张表

| 候选 | 结论 | 理由 |
|---|---|---|
| run / effect / event / request | 保留为唯一权威执行对象 | 已经是单一 advance 的产物；换掉会引入第二状态机 |
| Conversation | **增加为"分组身份"**，不做独立状态机 | 解决跨 run 归属；关闭/归档/重命名仍可由宿主或后续表承担 |
| Turn | **只做 projection**，不建表 | 四种口径都能从 effects/events 派生；建表会和 effect 争权威 |
| RunAttempt | **只做 runtime token**，不建表 | 已有 `effect.attempt/fence` 与 `(epoch,generation)` 两种不同 attempt，合并会破坏围栏 |

会话分组有两个可选实现，必须二选一：

| 方案 | 形状 | 优点 | 代价 |
|---|---|---|---|
| A. `runs.conversation_id uuid NULL`（不可变） | host 铸造；DB 存成员关系；`UNIQUE (conversation_id) WHERE ended_at IS NULL` | 与 pi/RP 的 session id 语义最接近；实现直接 | 多一个 id 命名空间；客户端可传任意 id（但仍在 scope 授权内） |
| B. `runs.conversation_root_run_id uuid NULL`（指向首个 run） | 首个 run 自指；后续 run 沿用 | 不新增 id 命名空间；成员关系可验证 | conversation id 永远等于某个 run id，容易与 DirectHeadless 的 `runID=sessionID` 混淆 |

> 建议 A。理由：`runID=sessionID` 只在"一个会话恰好一个 run"时成立，而 v24 的会话是 1:N；用 run id 当会话 id 会把"历史根 run"误读成"当前 run"。A 的额外 id 命名空间是显式成本，但语义干净。

#### 8.2 计数：四个名字，一个只读派生函数

```text
effect_settlement_no = runs.turn_no                     -- 保留，但对外必须带限定名
model_round_no       = count(model_call settlement)     -- 每个 model effect +1
tool_round_no        = count(tool_batch_admitted)        -- 每个工具批次 +1
user_turn_no         = count(command_start/command_steer) -- respond 不计
```

实现成一个只读函数（风格同 `v24/sql/49_host_reads.sql`），每个 business effect 一行，带 `late` 标记与 `generation` 归属。**不要**把这个函数的结果写回 runs，也不要用它替代 effect 的结算事实。

#### 8.3 生命周期：resume 分两种，fork 只记溯源

| 场景 | 落层 | 规则 |
|---|---|---|
| resume 执行 | 原 run + journal | 复用 run_id；running 则重新驱动，waiting 则投影 interaction；不重开终态 run |
| 继续对话 | 新 run（同 conversation） | 终态后新输入才允许；带有限历史；`UNIQUE (conversation_id) WHERE ended_at IS NULL` 保证串行 |
| fork | 新 conversation 的首个 run | 在 start payload 记 `fork_of {conversation_id, run_id, at_step_no}`；seed 由 host 从 journal 截取；内核不感知 |
| compaction（展示） | turn 投影 | 只影响显示，不改 provider 上下文 |
| compaction（模型上下文） | 普通 run（独立） | summary 作为该 run 的 final；下一 run 的 payload 引用它的 run_id；不新增 effect kind |
| steer | 原 run | 新 epoch/generation；`pending_steer` 单槽；产生新的 user turn anchor |
| cancel-late | 原 effect 结算 | 不复活业务状态；计数规则见 8.5 |
| 子代理前台结果 | 父的 tool effect | host adapter 读取 `child.result` 作为 tool outcome；幂等键由 child run_id 派生 |
| 子代理后台结果 | 父的 steer 或新 run | 显式投递；`request_key` 由 child run_id 派生；父已终态则新 run |

#### 8.4 命名纪律

在任何对外文档、API、UI 里，禁止裸用 `turn`：

- `effect_settlement_no`（v24 内核）
- `model_round_no`（pi agent-core 兼容）
- `tool_round_no`（pi durable 兼容）
- `user_turn_no`（RP / 产品语义）

这是"完全对标"的最低成本动作：不改一行代码，先让三套语义不再互相冒充。

#### 8.5 cancel-late：必须先定一条规则

当前事实：

- recovery 合成 unknown：`v_turn := r.turn_no`（不推进），`status/result/ended_at` 全保留（`v24/sql/49_recovery.sql:122-129`）。
- 普通 tool settlement 的 cancel-late 分支：`v_turn := r.turn_no + 1` 已计算且未回退；applier 无条件写 `turn_no = v_turn`（`v24/sql/48_loop.sql:1411`、`:2904-2906`）；validator 又强制 +1（`:1986-1990`）。

两种修法：

| 修法 | 规则 | 影响 |
|---|---|---|
| 保守（对齐规格文字） | late 事实不推进 `turn_no`/`revision`；只写 receipt 与 late 事件 | 需要同时改 validator/applier 和 recovery，补 gate；`turn_no` 不再是"所有首次结算数" |
| 统一向上（对齐"结算数"定义） | 任何首次提交的 business receipt 都 +1，包括 recovery 合成 unknown；`result.turn_no` 作为封口快照 | 只改 recovery 与规格文字；`turn_no` 语义一致；但封口后计数仍会变，需要在文档里说明 |

> 建议"统一向上"，因为列名和 validator 都已经按"结算数"实现；但这与当前规格第 271 行的文字冲突，必须作为协议修订显式记录，不能在 projection 里悄悄抹平。

### 9. 最小落地顺序（每步都可验收）

| 步 | 改动 | 验收判据 | 风险 |
|---|---|---|---|
| 1 | 只读函数 `v24.host_run_ledger(run_id)`：每 effect 一行，输出四种计数 + `late` + `generation` | 对一段 `model → 2 tools → model` 的录制，得到 `4/2/1/1`；`max(effect_settlement_no) == runs.turn_no` | 零 schema 变更；只读 |
| 2 | `runs.conversation_id uuid NULL` 不可变 + 部分唯一索引；start/spawn 准入与闭包检查 | 同会话连续两个终态任务：不同 run_id、同 conversation_id；spawn child 默认新 conversation；请求重放不多建对象 | 改 `v24/sql` 会动冻结哈希，需先确认 Cordis DP4 gate 的哈希覆盖范围 |
| 3 | 统一 cancel-late 规则 + 一条 gate 向量；实现显式结果投递 adapter（前台 tool / 后台 steer） | late 行 `late=true`；业务状态不变；child 结果只消费一次；父终态时转入新 run | 需要协议修订与新 gate |

如果只能做一件事：**先做第 1 步**。它不改 schema、不动冻结哈希，却能立刻回答"Pi 的哪个行为、RP 的哪个行为现在可以等价表达"，并为第 2、3 步提供回归基线。

### 10. 需要先用 spike 验证的假设

| # | 假设 | 可能被打脸的地方 |
|---|---|---|
| 1 | 工具批次进行中 steer，在途 tool 结果仍进入下一次 model 上下文 | steer 抬高 generation 后，在途 tool 结算被标 `late` 只记账；但 host 按 run 重放 journal 时可能仍把它们放进上下文，导致 DB 投影与 provider 上下文不一致 |
| 2 | 每个带工具的 model 结算恰好产生一条 `tool_batch_admitted`，且 payload 带 turn_no | spawn 混合工具、预算刚好耗尽、部分准入等路径可能缺事件或字段，导致 `tool_round_no` 无法派生 |
| 3 | model failure 走 effect claim 重试，不会让 run 直接失败 | 若 failure 直接结算为 run failed，RP"同一 attempt 内 retry"就只能映射成新 run，user turn 会被拆成两段 |

## Recommendations

### 0. 先拍板两件事（阻塞后续所有设计）

| 决策 | 选项 | 建议 | 影响面 |
|---|---|---|---|
| 会话分组怎么落 | A. `runs.conversation_id uuid NULL`（host 铸造，DB 存成员）<br>B. `runs.conversation_root_run_id uuid NULL`（指向首个 run） | **A** | 决定了 UI `sessions.json` 能否降级为缓存、`agent_run` 能否用 session_id 唯一解析到 run |
| cancel-late 计数 | 保守（late 不推进）<br>统一向上（所有首次 receipt +1） | **统一向上**，并改规格文字 | 决定了 `turn_no` 是"结算数"还是"业务推进数"；与当前规格 §5.1 的文字冲突，必须显式修订 |

Oracle 两路在这两点上不一致（lane 1 倾向 A + 保守，lane 2 倾向 B + 统一向上）。本报告的建议按"列名与 validator 已经实现的语义"选择 A + 统一向上，但**不代替架构拍板**。

### 1. 写一页 ADR：session / turn / run 语义合同

必须包含五条：

1. **会话是分组，不是执行**：conversation 只回答"哪些 run 属于同一会话""当前是否已有活跃 run"；不承载预算、状态机、关闭语义。
2. **run 是唯一执行主体**：预算、控制世代、interaction、终态都只在 runs/effects；conversation 的 status/result 必须派生，不能存。
3. **turn 是四个派生量，不是一个对象**：`effect_settlement_no` / `model_round_no` / `tool_round_no` / `user_turn_no`，对外必须带限定名。
4. **parent 边不等于投递**：`parent_run_id` 只表达 spawn 谱系；结果回灌必须走显式 tool outcome 或显式 steer，并带由 child run_id 派生的幂等键。
5. **provider 原文不进 DB**：journal 是原文权威，DB 只存语义投影与提交顺序；compaction 的"少显示"与"换上下文"必须分开描述。

### 2. 实现顺序（与 §9 一致）

| 顺序 | 交付 | 为什么先做 |
|---|---|---|
| 1 | `v24.host_run_ledger(run_id)` 只读函数 | 零 schema 变更，先把四种计数固化成可回归的事实 |
| 2 | conversation 锚（方案 A）+ 部分唯一索引 | 补上 DB 无法回答的跨 run 归属；这是唯一必须动的结构 |
| 3 | cancel-late 统一 + 结果投递 adapter | 把两个已知不一致点收敛，并用 gate 锁住 |

### 3. 明确不做的事

- **不建 `turns` 表**。四种计数都能从 effects/events 派生；建表会让 turn 与 effect 争权威，并迫使每个 effect 结算写两处。
- **不建 `run_attempts` 表**。`effect.attempt/fence` 与 `(epoch,generation)` 是两种不同围栏，合并会同时破坏 claim 重试和晚到结果拒绝。
- **不让 `run_id = conversation_id`**。这只在"一个会话一个 run"时成立；v24 的会话是 1:N，别名会让终态后的新输入无处安放。
- **不用 `scope` 冒充 conversation**。`close_scope` 会级联关闭该 scope 下所有 run/install；scope 是隔离根，不是对话边界。
- **不从 `parent_run_id` 自动回灌结果**。会绕过父 run 的预算预留和幂等键；三家实现都没有这样做。

### 4. 对标验收：一个脚本任务，四个读数

用 `v13/pi_parity` 那套"同一脚本、四运行时、确定性 trace"的方法，固定一个任务：

```text
user: 读三个文件并总结
model → tool(read a) + tool(read b) + tool(read c) → model final
```

期望读数：

| 读数 | v24 | pi agent-core | pi durable | RP |
|---|---|---|---|---|
| effect 结算数 | 5 | — | — | — |
| model rounds | 2 | 2 | 2 | — |
| tool rounds | 1 | — | 1 | — |
| user turns | 1 | 1 | 1 | 1 |

这张表就是"完全对标"的最小验收面：不是让四家的数字相等，而是让每个数字都有明确归属、能互相解释。

## Preventive Measures

1. **命名纪律进 lint/评审**：v24 新增文档与 API 禁止裸用 `turn`；必须写四种限定名之一。可以在 `docs/` 加一个 grep 检查（`\bturn\b` 不在白名单即告警），成本极低。
2. **语义漂移表**：本次已发现旧文档行号漂移（RP `AgentTranscriptTurn` 从 `:437` 到 `:701`，start 拒绝从 `:455` 到 `:496`）。建议在 `docs/reviews/` 维护一张"跨仓关键类型/行号"表，每次大改后重新对齐，避免下一轮调查把旧行号当证据。
3. **parent 边与投递边分离的评审规则**：任何新代码若从 `parent_run_id` / `parentSessionID` / `Conversation.owner` 直接推导"结果会到达"，必须出示投递函数与幂等键；否则视为把谱系边误当消息边。
4. **cancel-late 的 gate 向量**：至少覆盖 recovery 合成 unknown、tool 在 cancel 后晚到 success、tool 在 cancel 后晚到 unknown 三种路径，断言业务状态不变且计数规则一致。
5. **两套 SQL 的边界声明**：`v24/sql`（冻结内核）与 `v24/cordis/sql`（Cordis v2）必须在 README/计划里写清"谁是当前 host/UI 的运行时"，否则下一次调查仍会问"到底加载哪套"。
