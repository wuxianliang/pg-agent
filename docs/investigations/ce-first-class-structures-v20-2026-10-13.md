# Investigation: RepoPrompt-CE 一等数据结构对 v20 的启发

## Summary

CE 的持久身份是 session id，加上 runtime、generation、epoch 和 state。无界面启动时 `runID` 被赋成同一个 UUID。transcript、`providerSessionID`、workflow 模板正文和计划导出文件留在这份 metadata 之外。v20 的 workflow run、step、artifact digest 和宏观任务表是自己的容器。实验 schema 的 `sessions.workflow_run_id` 非空外键把 session 绑死在一个 workflow 实例上，CE 的两份 session 持久结构都没有这个字段。

## Symptoms

- 第二轮实验的 Oracle 选定了设计三：`sessions` 行与 `workflow_runs` 分开。需要用 CE 的真实数据结构检验这个方向，而不是只沿用实验报告。
- 无界面启动路径里，一次 `agent_run` 的 `runID` 取自 `sessionID`，同时仍保留 `parentSessionID` 和独立的 session metadata。v20 若把 session 与 workflow run 合成一个 id，可能对不上这套结构。
- CE 的 workflow 此前被看成提示词，不是 durable 容器。v20 草案把 workflow run 当成会话容器。需要核对 workflow 在 CE 里是不是一等对象。

## Background / Prior Research

### 持久化 AgentSession（explore `94FC1980`，行号待 pair 复核）

`AgentSession` 声明在 `AgentSession.swift:143`，`Codable`，序列化版本 9，结构一直到约 508 行。它是界面会话文档，不是运行时 metadata 那一行。

- 身份：`id: UUID`，以及 name、savedAt、`isMCPOriginated`、agent 配置、`lastRunState`。
- 父子：`parentSessionID`、`createdByOverseerSessionID`，另有监督唤醒目标 session id 集合。
- 正文：`transcript` 是结构化来源；`items` 是旧的工作副本，新持久化把它存空。另有 handoff 暂存和 `selfCompactState`。探索报告称 compact 状态只用于恢复，不是 resume 的权威。
- 提供者句柄：`providerSessionID`、Codex conversation id / rollout path、MCP session key。它们和 CE 的 session id 分开，也和 cleanup handle 分开。
- 工作区：`workspaceID`、`composeTabID`、worktree bindings 和 merge operations。

`AgentSessionMeta` 在 `AgentSessionDataService.swift:25`，是列表投影：id、parent、名称、模型、worktree 摘要。没有 transcript，也没有 provider resume handle。

### session 与 run（explore `FCDFA137`，行号待 pair 复核）

无界面协调器里，session 和 run 是两个对象，启动时共用一个 UUID。

- Session 由 `agentSessionStore.register(sessionID:)` 建立，持久形态是 `DomainAgentSessionDurableMetadata`：sessionID、owning runtime、lastEpochOrdinal、continuityGeneration、state。外层文档是 `DomainAgentSessionMetadataDocument`。
- Run 是协调器内存里的 `AgentRecord`（`DirectHeadlessProviderCoordinator.swift` 约 41–52 行），放在以 sessionID 为键的表里。字段含 registration、epoch、runID、parentSessionID。
- 约 205–206 行：`sessionID` 来自子启动上下文的 runID 或新 UUID，然后 `runID = sessionID`。runID 不是单独生成的。
- `parentSessionID` 取调用方 principal 的 runID，并且只有该 id 仍在活表里才保留。它指向父 session 的同一个 UUID。
- epoch 挂在 sessionID 上，按 activation 递增 ordinal。

这个结论里，`DomainAgentRunSessionStore.swift:217` 和 `DomainAgentSessionModels.swift` 的行号还没在本会话里打开复核。`runID = sessionID` 与 `AgentRecord.parentSessionID` 与先前读过的协调器片段一致。

### workflow、计划文件、WorkspaceContext（explore `9D11002A`，行号待 pair 复核）

这三样都不是带持久 id 的一等控制对象。

- `AgentWorkflowDefinition` 在 `AgentWorkflow.swift:122`。`id` 是算出来的。`template` 注释写明运行时才有，不持久化。自定义 workflow 落在 Application Support 的 markdown 文件上，定义本身不是数据库行。
- `WorkflowPrompt+Orchestrate.swift` 约 104–112 行：计划用 `export_response` 写成文件，子 agent 的 brief 里带路径，再用 `read_file` 读。计划是会话旁边的文件。
- 没有名为 `WorkspaceContext` 的类型。最近的是 `ContextBuilderWorkspaceContext`（无 id，按一次 run 冻结）、`WorkspaceContextRootSnapshot`（按查找冻结）、`PromptContextDTO`（工具返回的当次上下文）。它们是视图，不是会话存储。

## Investigator Findings

核对日期 2026-10-13。CE 行号来自直接打开的源文件；三条 explore 只作线索，下面每一条引用都在本会话里读过。`context_builder` 没有返回 chat，也没有 Oracle 初判。

### 行号校正

- `AgentSession` 仍在 `AgentSession.swift:143`。`id` 在 `:148`，`items` 在 `:161`，`transcript` 在 `:164`，`providerSessionID` 在 `:189`，`parentSessionID` 在 `:230`。序列化版本 9 在 `:145`。
- `AgentRecord` 在 `DirectHeadlessProviderCoordinator.swift:41`–`:52`。`sessionID` 取值在 `:206`，`runID = sessionID` 在 `:207`。Background 写的「约 205–206」早了一行。`parentSessionID` 的计算在 `:211`–`:212`，写入 record 在 `:243`。
- `DomainAgentRunSessionStore.swift` 全文没有 `runID`。Background 标成未复核的 `:217` 不是 run 赋值点。`DomainAgentSessionRegistration` 在 `:3`–`:7`，`DomainAgentSessionDurableMetadata` 在 `:42`–`:51`，`DomainAgentSessionMetadataDocument` 在 `:99`–`:106`。
- `DomainAgentSessionModels.swift` 本会话没有打开，不引用它的行号。epoch 挂在 session 上的证据是协调器 `:219` 的 `register(sessionID:)`，以及 durable metadata `:47` 的 `lastEpochOrdinal`。
- `AgentWorkflowDefinition` 在 `AgentWorkflow.swift:122`，`template` 在 `:140`–`:141`。计划导出说明在 `WorkflowPrompt+Orchestrate.swift:104`–`:113`。这三处与 Background 一致。

### CE 对象各自是什么

`AgentSession`（`AgentSession.swift:142`–`:143`）是带聊天正文的界面会话文档，`Codable`，当前序列化版本 9（`:145`）。

| 字段 | 行 | 类别 |
|---|---|---|
| `id: UUID` | `:148` | 持久 session 身份 |
| `parentSessionID: UUID?` | `:230` | 持久父子链接。注释 `:229` 写的是子会话的父 session |
| `createdByOverseerSessionID` | `:233` | 创建来源，仍是 session id |
| `providerSessionID: String?` | `:189` | 提供者恢复句柄。注释 `:187`–`:188` 写明用于 `--resume`，不重放历史 |
| `providerCleanupHandle` | `:193` | 清理元数据。注释 `:191`–`:192` 写明和可恢复性分开 |
| `codexConversationID` / `codexRolloutPath` / `codexMcpSessionKey` | `:218`、`:219`、`:227` | Codex / MCP 句柄 |
| `transcript` | `:164` | 正文来源。注释 `:163` |
| `items` | `:161` | 旧工作副本。注释 `:159`–`:160`：新持久化把它存空，需要时从 transcript 重建 |
| `workspaceID` | `:150` | 会话文档上的工作区字段，不是单独的 context 对象 |

`AgentSessionMeta`（`AgentSessionDataService.swift:25`–`:39`）是列表投影：id、parent、名称、模型、worktree 摘要、`itemCount`。没有 transcript，也没有 provider resume handle。

运行时另有一份更瘦的持久文档。`DomainAgentSessionDurableMetadata`（`DomainAgentRunSessionStore.swift:42`–`:51`）只存 `sessionID`、owning runtime、generation、`lastEpochOrdinal`、`continuityGeneration`、`state`、`resumable`、`updatedAt`。外层是 `DomainAgentSessionMetadataDocument`（`:99`–`:106`）：version、profile、revision、sessions 数组。这里没有 transcript，没有 `providerSessionID`，没有 parent，没有 workflow id，也没有 run id。`DomainAgentSessionRegistration`（`:3`–`:7`）是内存注册：runtime、`sessionID`、generation。

无界面协调器里的 `AgentRecord`（`DirectHeadlessProviderCoordinator.swift:41`–`:48`）是内存对象。`:206` 取子启动上下文的 `runID`，否则新 UUID，赋给 `sessionID`。`:207` 再把 `runID` 设成这个 `sessionID`。`:211`–`:212` 把调用方 principal 的 `runID` 当作父 id，并且只有该 id 仍在以 sessionID 为键的活表里才保留（`:257` 写入 `agents[sessionID]`）。因此这条路径上的 runID 不是单独生成、也不是单独落盘的对象；父指针是父 session 的同一个 UUID。

`AgentWorkflowDefinition.template`（`AgentWorkflow.swift:140`–`:141`）注释写明 runtime-only，不持久化。`CodingKeys`（`:255`–`:257`）没有 `template`。`id` 是计算属性（`:145`–`:150`）：内建用 canonical id，自定义用 `custom-<uuid>`。自定义 workflow 由 `AgentWorkflowStore` 从 Application Support 的目录加载（`:120`），不是数据库行。模板正文留在提示词文件里，定义本身不是控制行。

计划交接是导出文件路径。`WorkflowPrompt+Orchestrate.swift:106` 要求 `export_response:true` 把计划写成文件，`:112`–`:113` 把 `oracle_export_path` 放进子 agent 的 message，子 agent 用 `read_file` 打开。这段没有 digest，也没有计划对象的持久 id。

仓库里没有名为 `WorkspaceContext` 的类型声明。相近的三个都没有自己的持久 id：

- `ContextBuilderWorkspaceContext`（`ContextBuilderWorkspaceContext.swift:4`）带着父会话的 `parentAgentSessionID`（`:5`），`tabID` 来自冻结的 tab（`:17`–`:18`）。
- `WorkspaceContextRootSnapshot`（`WorkspaceRootSeedModels.swift:29`）按一次查找冻结。`lifetimeID` 在每个 root 上（`:32`），是撤销句柄，不是 snapshot 主键。
- `PromptContextDTO`（`ToolResultDTOs.swift:2662`–`:2727`）是 `workspace_context` 的当次载荷，字段里没有 id。

### 对到 v20 的已有对象

章程把 run/session identity 放进内核（`docs/designs/v20-runtime-charter-draft-2026-10-12.md:218`），最小 durable 对象是 `v20_runs`、`v20_operations`、`v20_turns`、`v20_tool_invocations`、`v20_events`、`v20_workflow_runs`、`v20_workflow_steps`、`v20_artifacts`（`:242`–`:250`）。章程没有 `v20_sessions` 表。`:30` 把 CE 的 AgentRun、WorkspaceContext、epoch/generation、context artifact 列为要吸收的思路。

实验 schema `v20/experiments/ce_facades_r2/schema.sql` 里，和 CE 对得上的只有身份这一层：

- CE 的 `AgentSession.id` 与 `DomainAgentSessionDurableMetadata.sessionID` 对应 schema 的 `sessions.session_id`（`:103`）以及 `events.session_id`（`:49`，索引 `:56`）。`events.session_id` 是审计列，指向这个身份，不是会话文档。
- CE durable metadata 上的 runtime、generation、epoch ordinal、state，对应章程 `:218`–`:222` 的 identity、owner generation/fence、revision。schema 的 `runs.owner_generation`（`:22`）和 `workflow_runs.revision`（`:9`）是 v20 自己的存放处；CE 把这些数记在 session metadata 上。
- 无界面路径的 `runID` 与 `sessionID` 是同一个 UUID。schema 的 `runs`（`:16`–`:24`）是另一张表，带 `parent_run_id`、`workflow_run_id`、owner fence。它可以承载 v20 的 turn/owner 生命周期。CE 没有把它做成第二份 durable 身份。
- `parentSessionID` 是父 session UUID。schema 里靠近它的列是 `runs.parent_run_id`（`:20`）。CE 的 durable metadata 不存 parent；parent 在界面会话文档和内存 `AgentRecord` 上。
- `AgentWorkflowDefinition` 对应提示词模板，不对应 `workflow_runs`（schema `:7`–`:13`，章程 `:248`、`:262`）。workflow run 是一次中观实例。
- 计划文件路径对应 artifact 的地址。schema `artifacts` 用 `digest` 作主键，并有 `path`（`:36`–`:41`）。章程的 `v20_artifacts`（`:250`、`:263`）和 `v20_plan_artifacts`（`:734`、`:742`）同样是 hash 引用。digest 是 v20 的内容地址；CE 这段交接文本只给出文件路径。
- step 的引用权威在 v20。schema `workflow_steps` 的 `input_artifact_refs` 与 `output_artifact_refs`（`:31`–`:32`）记录一步用了哪些 artifact。章程 `:135` 的 `step_id` 由 workflow plugin 提议，再经 Control 准入。CE 没有 durable step 行；计划文件只是交接清单。

`sessions.workflow_run_id`（schema `:104`）是这张实验表上的非空外键，一份 session 指向一个 workflow。CE 的 `AgentSession` 和 `DomainAgentSessionDurableMetadata` 都没有这个字段。该外键是实验 schema 的形状，不是 CE 推出来的结构。`session_aliases`（`:88`–`:97`）和 `external_ids`（`:109`–`:113`）同样只存在于这轮实验。

### 留在内核写入器之外的 CE 字段

内核写入器保留 session id，以及 durable metadata 里的 runtime、generation、epoch ordinal、continuity、state、revision。下列内容留在外面：

- `transcript`（`AgentSession.swift:164`）和 `items`（`:161`）。
- `providerSessionID`（`:189`）、`providerCleanupHandle`（`:193`）、`codexConversationID`（`:218`）、`codexRolloutPath`（`:219`）、`codexMcpSessionKey`（`:227`）。
- workflow 模板正文（`AgentWorkflow.swift:140`–`:141`，且不在 `:255`–`:257` 的 `CodingKeys` 里）。
- 计划导出文件的正文（`WorkflowPrompt+Orchestrate.swift:104`–`:113`）。跨边界的是路径；v20 若要 durable 引用，用 artifact 的 digest 和 path。
- `PromptContextDTO` 和 workspace snapshot 的载荷。章程 `:361`–`:394` 已把 WorkspaceContext 定为插件，输出 `ContextArtifact` 的 hash 与 manifest。Worker 拿 artifact 引用。

### pg-agent 有、CE 没有的容器

这些是 v20 自己的容器，CE 没有同名的 durable 对象：

- `workflow_runs` 与 `workflow_steps`（schema `:7`–`:34`；章程 `:248`–`:249`）。CE 的 workflow 是模板文件。
- `artifacts`（schema `:36`–`:42`；章程 `:250`）。CE 的计划交接和 context 载荷都不是内容寻址行。
- `events` 上并列的 `run_id`、`workflow_run_id`、`session_id`（schema `:47`–`:49`；章程 `:247`）。CE 的会话持久化是会话文档加 metadata 文档，不是这张追加事件表。
- `operations` 与 `turns`（schema `:60`–`:72`；章程 `:244`–`:245`）。
- `macro_tasks` 与 `macro_workflows`（schema `:74`–`:85`）。章程侧的对应草案是 `v20_plan_revisions`、`v20_plan_tasks`、`v20_plan_edges`、`v20_plan_artifacts`（`:730`–`:734`）。CE 用一份导出文件充当计划，没有这些表。
- 章程里的 `v20_tool_invocations`（`:246`）。这份 schema 没有这张表，CE 的 session metadata 里也没有。

### 假设

- session 身份与 workflow run 分开：CE 是这样。session id 不指向 workflow run。无界面 runID 只是同一个 session UUID 的内存别名。
- transcript 与 `providerSessionID` 留在内核之外：二者都在 `AgentSession` 上，不在 `DomainAgentSessionDurableMetadata` 上。
- workflow definition 是提示词模板：`template` 不进 `CodingKeys`，自定义正文在 Application Support 的文件里。
- plan handoff 是导出文件加 digest：CE 侧核实到的是导出文件路径。digest 属于 v20 的 artifact，不是这段 CE 文本里的字段。
- workflow step refs 仍是引用权威：这是 v20 的 `workflow_steps` artifact refs。CE 没有 step 表可以替换它。

## Investigation Log

### Phase 2 - context_builder 从本会话调用

**Hypothesis:** 本会话可以直接跑 context_builder，让 Oracle 先对照 v20 对象做一次初判。

**Findings:** 两次调用都返回 MCP `-32001` Request timed out。超时后约两分钟内，工作区 `Chats/` 没有新的 ChatSession 文件，也没有新的 agent 会话。失败没有留下可恢复的 chat_id。

**Evidence:** 工具结果原文是 `MCP error -32001: Request timed out`。最近的聊天文件仍是 15:01 的 `ChatSession-6DA9B677-...json`。

**Conclusion:** 同一调用不再重试。后续由 pair 在自己的会话里调用 context_builder，避免和本会话的 MCP 等待绑在一起。


### Phase 1 - 问题界定

**Hypothesis:** CE 的一等对象至少包括持久化的 `AgentSession` 和运行时的 session registration / durable metadata。run、workflow、WorkspaceContext、导出文件不是同一个对象。

**Findings:** 待外部调查和 pair 核对。

**Evidence:** 已知入口：

- `/Users/wxl/Projects/repoprompt-ce/Sources/RepoPrompt/Features/AgentMode/Runtime/AgentSession.swift` 约 143 行起，`AgentSession`，含 `id` 与 `parentSessionID`
- `/Users/wxl/Projects/repoprompt-ce/Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift` 约 3–106 行，`DomainAgentSessionRegistration`、`DomainAgentSessionDurableMetadata`、metadata 文档
- `/Users/wxl/Projects/repoprompt-ce/Sources/RepoPromptMCPCore/DirectHeadlessProviderCoordinator.swift` 约 41–52 行与 206–219 行，`AgentRecord`，`runID = sessionID`

**Conclusion:** 已由 Investigator Findings 和后面的源码抽查收束。

### Phase 3 - 本会话放弃 context_builder

**Hypothesis:** 本会话直接调用 `context_builder`（`response_type: question`）会得到 chat_id 和一次对象映射初判。

**Findings:** 调用返回 `emptyProcessedContent`，没有 chat_id，没有 Oracle 文本。用户随后说明从 agent 会话调用会卡住：已超过六分钟，没有新的 ChatSession 文件。按该指示停止等待，不再调用 `context_builder` 或 `ask_oracle`。

**Evidence:** 工具结果原文是 `Failed to call context_builder: Error: emptyProcessedContent`。因此没有可摘录的 Oracle 初判。

**Conclusion:** 映射以本会话读到的 CE 与 v20 源码为准，见 Investigator Findings。

### Phase 4 - 抽查行号并请 Oracle 综合

**Hypothesis:** pair 的对象对照成立，Oracle 能据此说明 v20 该保留哪一层身份。

**Findings:** 抽查与 pair 的行号一致，一处收窄：`CodingKeys` 是 `AgentWorkflow.swift:255`–`:257`。`AgentSession.id` 在 `:148`，`parentSessionID` 在 `:230`，`transcript` 在 `:164`，`providerSessionID` 在 `:189`。`runID = sessionID` 在 `DirectHeadlessProviderCoordinator.swift:207`，`parentSessionID` 写入 `AgentRecord` 在 `:243`。`DomainAgentSessionDurableMetadata` 在 `DomainAgentRunSessionStore.swift:42`–`:51`，字段里没有 workflow id、parent、runID、transcript。`sessions.workflow_run_id` 在 `schema.sql:104`，非空，引用 `workflow_runs`。章程 `:218` 把 run/session identity 列为一条内核职责，`:242`–`:250` 的最小对象里没有 `v20_sessions`。

**Evidence:** Oracle 聊天 `untitled-chat-951CEA`。它的结论与抽查一致：内核保留 session id 和生命周期计数；`sessions.workflow_run_id` 非空多绑了生命期和 1:1 基数；workflow run、step、artifact digest、event、turn、macro 是 v20 自己的容器。

**Conclusion:** 见下面的结论。本调查不改章程，也不改实验代码。

## Root Cause

这是对象对照。CE 有两份和 session 有关的持久结构，外加一份内存 run：

- `AgentSession`（`AgentSession.swift:143`）是带正文的会话文档。身份是 `id`（`:148`）。`parentSessionID`（`:230`）记父子。`transcript`（`:164`）是正文。`providerSessionID`（`:189`）是提供者的 `--resume` 句柄。
- `DomainAgentSessionDurableMetadata`（`DomainAgentRunSessionStore.swift:42`–`:51`）只记 `sessionID`、owning runtime、registration generation、`lastEpochOrdinal`、`continuityGeneration`、`state`、`resumable`、`updatedAt`。外层文档带 `revision`（`:99`–`:105`）。
- 无界面 `AgentRecord`（`DirectHeadlessProviderCoordinator.swift:41`–`:48`）在内存里。`:206`–`:207` 令 `runID` 等于 `sessionID`。`:243` 把 `parentSessionID` 放在这条 record 上。`agents` 以 `sessionID` 为键（`:257`）。

`AgentWorkflowDefinition.template`（`AgentWorkflow.swift:140`–`:141`）不进入 `CodingKeys`（`:255`–`:257`）。自定义 workflow 的说明在同文件 `:120`：从 Application Support 的目录加载。计划交接是 `oracle_export_path`（`WorkflowPrompt+Orchestrate.swift:106`–`:113`），这段文本里没有 digest。仓库里没有名为 `WorkspaceContext` 且自带持久主键的类型。

v20 章程把 run/session identity 收成一条内核职责（`docs/designs/v20-runtime-charter-draft-2026-10-12.md:218`），最小对象是 runs、operations、turns、tool invocations、events、workflow runs、workflow steps、artifacts（`:242`–`:250`）。实验表 `sessions`（`v20/experiments/ce_facades_r2/schema.sql:102`–`:105`）另加了指向一个 workflow run 的非空外键。CE 的两份 session 持久结构都没有这个字段。

## Recommendations

1. 内核身份沿用 durable metadata 那一层：session id，加上 generation、epoch ordinal、continuity、state、revision。章程 `:218` 已经把这件事收进 Kernel。无界面路径里的 `runID` 是这个 id 的别名；`runs` 表继续承载 turn 和 owner fence（`schema.sql:16`–`:24`，章程 `:257`）。
2. `transcript`、`items`、`providerSessionID`、cleanup handle、Codex conversation id 留在写入器之外。它们在 `AgentSession.swift:161`–`:227`，不在 `DomainAgentSessionDurableMetadata` 上。
3. `parentSessionID` 在 CE 里写在会话文档和内存 record 上。v20 若要父子链，用已有的 `runs.parent_run_id`（`schema.sql:20`）表达 spawn，不必把整份 `AgentSession` 抄进内核。
4. `sessions.workflow_run_id`（`schema.sql:104`）若进入正式 schema，应允许 session 在没有 workflow 实例时存在。CE 的 session 不依附某一个 workflow run。
5. workflow run、workflow step 的 artifact refs（`schema.sql:26`–`:32`）、artifact 的 digest（`:36`–`:41`）、events、operations、turns、macro 表保持为 v20 容器。计划正文留在事务外的文件里；durable 层记 digest 和 path。章程 `:361`–`:380` 已把 WorkspaceContext 定为插件，输出带 hash 的 artifact。

## Preventive Measures

- 新增 session 列时，先看它出现在 `DomainAgentSessionDurableMetadata` 上，还是只出现在 `AgentSession` 上。只在后者出现的字段留在会话文档或 artifact 里。
- 把 CE 的 workflow 名接到 `v20_workflow_runs` 时，记住 CE 那边是模板文件（`AgentWorkflow.swift:140`–`:141`），实例、step 和 digest 来自章程 `:248`–`:250`。
- `cleanup` 继续只改状态、追加事件。CE 的 `providerCleanupHandle`（`AgentSession.swift:191`–`:193`）和 session 可恢复性是分开的，不能拿它当删除事件的理由。
