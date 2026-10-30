# v20 Runtime Charter（初稿）

日期：2026-10-12  
状态：总体设计讨论稿，尚未实现、尚未冻结、尚未作为开发合同。

## 1. 设计目标

v20 是一个运行在 PostgreSQL 之上的长期 agent development system：

```text
微观：agent loop —— 一次 turn、一次工具调用、一次回执
中观：agent workflow —— 多步任务、上下文装配、子 agent、review、handoff
宏观：agent governance —— 长期运行、资格、调度、注意力、配额、停复、恢复
```

v20 保留 v13 的 agent core：

- PostgreSQL 作为 durable control truth；
- session/run、event、effect/tool invocation；
- parse/decision/advance 的线性推进思想；
- authorization、fence、lease、stale、replay、complete；
- 外部 IO 不进入数据库事务；
- 控制动词由数据库事实和策略约束；
- 高层语义优先表达为只读投影和纯函数。

v20 同时吸收：

- v23 的 `Control → Worker → Host` 单入口结构；
- LoopX 的长期运行、资格与执行分离、attention/quota/projection 思路；
- RepoPrompt CE 的 AgentRun、WorkspaceContext、MCP tool registry、epoch/generation、context artifact 思路；
- v13 tool-port 的多语言 line-JSON adapter ABI。

v20 不继续扩展 v13 的 stage 目录，不把 v20 作为 v13 stage 45，也不 runtime import v13。

## 2. 总体架构

```text
                    ┌──────────────────────────┐
                    │       Macro Governance    │
                    │  scheduler / attention    │
                    │  quota / fairness / stop │
                    └────────────┬─────────────┘
                                 │ pure policy / admission
                    ┌────────────▼─────────────┐
                    │      Meso Workflow        │
                    │ workflow / steps / child  │
                    │ context / review / handoff│
                    └────────────┬─────────────┘
                                 │ step admission
                    ┌────────────▼─────────────┐
                    │       Micro Loop          │
                    │ Worker turn / tool call   │
                    │ receipt / disposition     │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │       v20 Kernel          │
                    │ Control / durable truth   │
                    │ CAS / fence / recovery    │
                    └────────────┬─────────────┘
                                 │ Tool Gateway
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
   WorkspaceContext          DuckDB State Space       RAG State Space
   Swift/Python adapter      Python/SQL adapter        Python/service adapter
```

核心原则：

> 三层控制语义可以扩展，但 durable state transition、idempotency、fence、recovery 只能由 Kernel 负责。

宏观层、中观层、微观层不是三个独立 scheduler，也不是三个可以直接写库的插件。

## 3. 三层控制模型

### 3.1 微观：Agent Loop

微观层负责一次有限 turn：

```text
admit turn
  → build WorkerRequest
  → DB-free Worker execution
  → zero or more bounded tool calls
  → validate TurnReceipt
  → commit receipt/state
  → pure disposition
```

微观层的核心 DTO：

```text
WorkerRequest  → TurnReceipt
ToolRequest    → ToolResult
Snapshot       → Disposition
```

微观层允许的 disposition 初期固定为：

```text
run_now
wait
needs_input
stop
failed
```

不得把 workflow 或 governance 的全部语义塞进微观 disposition。

### 3.2 中观：Agent Workflow

中观层把多个微观 turn 组合成一个有界 workflow：

```text
workflow start
  → context snapshot
  → agent step
  → tool step
  → child agent step
  → review / approval
  → handoff / next step
  → workflow complete
```

Workflow plugin 只返回纯计划或动作建议：

```json
{
  "workflow_id": "...",
  "workflow_revision": 4,
  "decision": "run_now",
  "actions": [
    {
      "kind": "admit_turn",
      "step_id": "..."
    }
  ]
}
```

Workflow plugin 不得：

- 直接写 PostgreSQL；
- 直接推进 Run；
- 自己调用 Worker；
- 自己创建第二个 scheduler；
- 自己决定最终 durable status；
- 把 WorkspaceContext、DuckDB 或 RAG 的内部状态当作 v20 Run 真相。

### 3.3 宏观：Agent Governance

宏观层负责长期运行性质，而不是具体工具执行：

- should-run；
- attention；
- quota eligibility；
- fairness；
- starvation prevention；
- stop/resume；
- owner lease/fence；
- orphan recovery；
- bounded unattended policy；
- notification/wakeup hint。

宏观层优先实现为：

```text
read-only projection + pure decision + Control admission
```

而不是：

```text
another supervisor + another advance + another durable ledger
```

宏观层可以有不同 policy plugin，但所有 policy 的最终 mutation 仍进入 Kernel 的统一 Control。

## 4. 极简 Durable Kernel

v20 Kernel 是整个系统唯一的 durable mutation owner。

### 4.1 唯一公共入口

```text
Control.execute(op, actor, request) -> committed response + snapshot
```

初期公共操作闭集：

```text
start
poll
wait
steer
respond
cancel
spawn
handoff
```

内部操作可以包括：

```text
admit_turn
accept_turn_receipt
admit_tool
accept_tool_result
recover_owner
```

但它们仍由同一个 Control 实现，不形成第二入口体系。

### 4.2 Kernel 负责的不可插件化部分

以下内容必须固定在 Kernel：

- run/session identity；
- operation idempotency；
- revision CAS；
- authorization；
- owner generation/fence；
- turn admission；
- tool admission；
- receipt validation；
- state transition；
- cancel race；
- late result discard；
- orphan recovery；
- notification；
- durable event/audit；
- snapshot publication。

插件不得直接写这些表或状态。

### 4.3 建议的最小 durable 对象

v20 不追求“只有一张表”，而追求**只有一种事实来源和一种写入入口**。

建议最小对象：

```text
v20_runs
v20_operations
v20_turns
v20_tool_invocations
v20_events
v20_workflow_runs
v20_workflow_steps
v20_artifacts
```

这些对象可以在实现阶段进一步合并，但不能产生第二状态源。

职责：

- `v20_runs`：当前 run snapshot；
- `v20_operations`：外部 op、request_id、幂等收据；
- `v20_turns`：Worker 回合和 receipt；
- `v20_tool_invocations`：工具 admission、lease、result；
- `v20_events`：append-only 审计和控制事件；
- `v20_workflow_runs/steps`：中观工作流实例；
- `v20_artifacts`：context、tool output、review evidence 的内容寻址引用。

### 4.4 事务边界

所有执行遵循：

```text
T1 admission commit
  → DB-free Worker / Tool / Context IO
  → T2 receipt/result commit
  → best-effort notification
```

禁止：

```text
数据库事务持有期间调用 Swift/Python 工具
数据库事务持有期间调用 provider
数据库事务持有期间等待 Host/Event
Tool plugin 直接 COMMIT
```

## 5. 工具与临时状态空间

工具是控制体系与外部临时状态空间之间的桥。

```text
Control
  → Tool Gateway
  → Tool Adapter
  → Temporary State Space
```

临时状态空间不是 v20 durable Run truth。它可以是：

- WorkspaceContext；
- 本地工作区文件；
- DuckDB；
- RAG index；
- git/worktree；
- 外部 artifact store；
- future memory/search backend。

### 5.1 Tool Adapter Contract

```text
ToolRequest → ToolResult
```

ToolRequest 至少包含：

```text
contract_version
invocation_id
run_id
turn_id
tool_name
tool_version
workspace_binding
request
request_digest
deadline
```

ToolResult 至少包含：

```text
contract_version
invocation_id
status
result
error
result_digest
observed_revision / artifact_refs
```

Tool Adapter 必须是语言无关的外部协议实现。Swift、Python、Go、Rust 都可以实现同一协议。

### 5.2 Tool Plugin 的边界

Tool Plugin 可以：

- 访问自己的临时状态空间；
- 调用本地进程或服务；
- 返回 bounded result；
- 自己维护临时缓存；
- 报告外部 revision/digest；
- 提供 tool-specific error。

Tool Plugin 不可以：

- 写 `v20_runs`；
- 修改 Control revision；
- 创建第二个 turn；
- 自己重试整个 agent；
- 自己改变 workflow step 状态；
- 在数据库事务中运行外部 IO。

### 5.3 WorkspaceContext

WorkspaceContext 作为 **Context Plugin + Read/Mutation Tool**，不作为 Worker 内部实现。

它提供：

```text
snapshot
export
list_presets
select_preset
```

但 read 和 mutation 必须在 v20 中拆开建模：

```text
context_snapshot   —— 只读，返回冻结 snapshot/artifact
context_export     —— mutation，生成 artifact
context_select     —— mutation，改变 context revision
```

WorkspaceContext 的输出应成为：

```text
ContextArtifact {
  artifact_id
  content_hash
  workspace_id
  context_revision
  manifest
}
```

Worker 只接收 artifact reference 或 bounded materialized context，不直接接触 WorkspaceContext authority。

### 5.4 DuckDB State Space

DuckDB 适合：

- 临时结构化查询；
- 文件/CSV/Parquet 分析；
- 中间结果；
- 数据探索；
- bounded artifact generation。

不适合成为 v20 Run 的第二状态源。

必须通过 DuckDB Adapter：

```text
v20 ToolRequest
  → DuckDB adapter
  → query/materialize
  → bounded result/artifact
  → Control accepts result
```

DuckDB 的 database identity、schema revision、query digest、artifact digest 必须进入 ToolResult，而不是散落在 Host 内存。

### 5.5 RAG State Space

RAG 系统同样是外部 state space：

```text
query/context artifact
  → retrieval adapter
  → evidence bundle
  → artifact hash
  → Worker context
```

RAG 不直接决定：

- Run 是否完成；
- Workflow 是否前进；
- Tool 是否成功；
- 是否继续调用 provider。

它提供证据和 artifact，最终决定仍由 Worker/Workflow policy/Control 分层负责。

## 6. 多语言 Harness ABI

v20 采用两个稳定协议，而不是一种万能协议。

### 6.1 Tool ABI

初期采用 v13 tool-port 的 line-JSON 思路：

```text
one request frame
one result frame
closed exit/error codes
bounded output
no DB access
```

协议版本必须显式：

```text
v20-tool-1
```

### 6.2 Worker ABI

采用 v23 的：

```text
WorkerRequest → TurnReceipt
```

跨进程传输可以使用 line-JSON 或 length-prefixed JSON，但规范数据必须统一：

- canonical JSON bytes；
- SHA-256 digest；
- UUID/revision；
- input kind；
- contract version；
- outcome enum；
- tool call bounds；
- receipt bounds；
- NUL/surrogate/number/depth 限制。

Swift/Python/Go 不共享 fence 代码，只共享：

- protocol；
- canonical vectors；
- error vectors；
- limit vectors；
- lifecycle semantics。

### 6.3 不统一 ACP 和 Tool ABI

ACP、MCP Tool、Tool Adapter、Worker Turn 是不同层：

```text
ACP：agent/provider/session transport
MCP：tool/control surface
Tool ABI：单次外部工具调用
Worker ABI：单次 agent turn
```

v20 不把它们强行合并成一个万能 plugin protocol。

## 7. 插件模型：收紧内核，开放能力

### 7.1 允许插件化的部分

```text
WorkerPlugin
ToolAdapterPlugin
ContextPlugin
WorkflowPolicyPlugin
GovernancePolicyPlugin
ProviderPlugin
```

每个插件必须提供 manifest：

```text
plugin_name
plugin_version
contract_version
capabilities
input_schema
output_schema
limits
health
```

### 7.2 不允许插件化的部分

```text
Durable state owner
Control.execute
Revision CAS
Operation idempotency
Fence/recovery
Run status transition
Tool invocation admission
Receipt finalization
```

“插件”表示可替换能力，不表示可独立拥有控制事实。

### 7.3 插件生命周期

插件可以：

```text
register
health_check
prepare
execute
close
```

不能：

```text
start_scheduler
write_run_state
create_unbounded_loop
silently retry turn
mutate another plugin's state
```

如果插件需要长期运行，它必须由 Kernel 创建一个明确的 operation/invocation，并接受 lease/fence/recovery 规则。

## 8. 长期运行模型

### 8.1 Host owner

一个 `(database_identity, workspace_id)` 同时只有一个 active runtime generation。

旧 owner 丢失 fence 后：

- 永久失效；
- 不透明重连；
- 不自动重放 Worker；
- 在途外部调用进入 unknown/lost 分支；
- 新 owner 在 Control 中执行 fail-closed recovery。

### 8.2 Wait/notify

```text
short read
→ commit
→ LISTEN/Event/bounded poll
→ reread snapshot
```

通知只传：

```text
run_id
revision
```

通知不是状态，丢通知也必须能通过 polling 收敛。

### 8.3 Macro policy

宏观 policy 只能返回：

```text
run_now
wait
pause
needs_input
stop
```

不直接写状态。Host 读取 policy 后回到 `Control.execute`。

## 9. 宏观规划与方向层

### 9.1 为什么宏观层不能只有 governance

当前 LoopX 已经提供了若干重要能力：

- 高层 goal 注册；
- planning packet；
- Todo 持久化；
- P0/P1/P2 优先级；
- typed task relations；
- capability route；
- attention projection；
- quota/readiness/cadence policy。

但当前 LoopX **没有完整实现**以下闭环：

```text
高层目标
  → 调查项目/代码/外部证据
  → 形成结构化 WBS
  → 建立依赖和验收条件
  → 决定任务顺序
  → 为子任务选择 workflow / agent / tool
  → 持久化 admitted plan
  → 长期运行按 plan frontier 推进
  → 根据证据和失败重新规划
```

现状更接近：

```text
模型负责思考和拆解
  → LoopX 提供 planning packet
  → LoopX 持久化模型写入的 Todo
  → LoopX 做优先级、资格和 attention 投影
  → 外部 host 负责真正执行
```

这还不足以保证长期运行始终朝正确方向推进。没有宏观规划层时，Host 很容易从战略目标直接掉入某个局部工具或细节分支。

### 9.2 v20 新增 Macro Planner / Advisor

v20 在宏观治理之上增加一个明确的 **Macro Planner / Advisor** 角色，但它不是第四个 scheduler，也不是第二个 durable writer。

它的职责是：

1. 接收高层目标；
2. 调用只读调查工具和 Context Plugin；
3. 读取项目源码、设计、测试、现状、历史和外部证据；
4. 生成结构化 `PlanProposal`；
5. 按证据确定任务分解、依赖、顺序和风险；
6. 为每个子任务建议 workflow、agent profile 和 tool capabilities；
7. 将 proposal 提交给 Control 做 schema、policy、scope 和 revision 校验；
8. 只有被 admitted 的 plan 才能生成 workflow frontier。

推荐数据流：

```text
Goal
  → Macro Planner investigation
  → ContextArtifact / EvidenceBundle
  → PlanProposal
  → human/policy admission
  → PlanRevision
  → WorkflowSteps / frontier
  → Host selects next admitted step
```

### 9.3 PlanProposal

`PlanProposal` 是模型输出，不是立即生效的控制状态。它至少包含：

```text
proposal_id
base_goal_revision
project_revision / workspace_revision
objective
scope
assumptions
investigation_refs[]
plan_tasks[]
plan_edges[]
recommended_order[]
workflow_route per task
agent_profile per task
tool_capabilities per task
acceptance_checks per task
risks[]
open_questions[]
confidence
```

每个 task 至少包含：

```text
task_id
summary
kind
preconditions
dependencies
workflow_route
required_capabilities
expected_artifacts
acceptance_checks
risk
status
```

`PlanProposal` 必须引用调查证据，不能只依赖模型自由文本。没有证据的任务可以进入 `open_questions`，不能直接成为高优先级可执行 task。

### 9.4 计划持久化与最小状态

v20 不复制 LoopX 的所有文件层，也不让 Macro Planner 直接写数据库。建议最小持久化形态：

```text
v20_plan_revisions
v20_plan_tasks
v20_plan_edges
v20_plan_artifacts
```

其中：

- `v20_plan_revisions`：目标、基线 revision、proposal hash、admission 状态；
- `v20_plan_tasks`：可执行 task 和当前状态；
- `v20_plan_edges`：`depends_on`、`unblocks`、`routes_via` 等有限关系；
- `v20_plan_artifacts`：调查证据、context pack、acceptance evidence 的 hash 引用。

这些对象仍只能由 `Control.execute(plan_*)` 写入。Macro Planner 是 producer，Control 是唯一 authorizer/writer。

计划状态建议为：

```text
draft
proposed
needs_review
admitted
active
blocked
superseded
completed
cancelled
```

`draft/proposed` 不会驱动 Host。只有 `admitted/active` 的 plan task 才能进入 workflow frontier。

### 9.5 宏观顺序和 workflow 选择

宏观层不能只返回一个“推荐下一步”字符串。它必须输出有限、可解释的选择结果：

```text
selected_task_id
why_now
blocked_by[]
workflow_route
agent_profile
allowed_capabilities
expected_evidence
next_replan_condition
```

但最终选择仍由纯函数和 Control admission 复核：

```text
PlanProjection
  → GovernancePolicy
  → MacroDecision
  → Control.admit_workflow_step
```

LoopX 的 P0/P1/P2、attention、quota、fairness 可以作为 `GovernancePolicy` 的输入，但不能替代计划图本身。

推荐的 selection 优先级：

1. 已被 admitted 且无未满足依赖的 task；
2. 能解除最多后续任务阻塞的 task；
3. 当前 evidence freshness 足够的 task；
4. 风险、资源和 quota 允许的 task；
5. 最后才按 P0/P1/P2 和 planner order tie-break。

这能避免长期运行盯住一个低价值细节分支，而忽略尚未完成的关键前置任务。

### 9.6 调查和重新规划

宏观 Planner 需要两个不同模式：

```text
investigate
execute
```

`investigate` 只读：

- `get_file_tree`；
- `file_search`；
- `get_code_structure`；
- `read_file`；
- WorkspaceContext snapshot；
- DuckDB/RAG 查询；
- git history/diff；
- external research adapter。

`execute` 才能产生 workflow step，但仍不能绕过 Control。

触发 replan 的条件包括：

- 项目 revision 变化；
- 关键假设被工具证据否定；
- task 失败达到重试边界；
- workflow capability 不可用；
- 依赖图出现新阻塞；
- acceptance check 失败；
- context artifact 过期。

replan 不应每个 turn 都调用。它应是一个有预算的宏观 operation，并输出新的 `PlanProposal` / `PlanRevision`，保留旧计划和证据链。

### 9.7 MAAD 对 v20 的启发：宏观阶段应是有产出的规划工作流

MAAD 的核心价值不在于“有四个 agent”，而在于它把宏观设计过程组织成一条可检查的 artifact pipeline：

```text
Analyst
  → structured requirements
Modeler
  → external knowledge + architecture models
Designer
  → contracts / deployment / traceability
Evaluator
  → consistency / quality / mismatch / trade-offs
```

MAAD 项目公开描述的目标是：把 SRS 转换成多视角架构蓝图，并通过 RAG、分层记忆、四类角色 agent 和 evaluator 形成迭代闭环；其仓库主要提供 replication package、requirements dataset、generated artifacts 和对比结果，而不是一个可直接嵌入 v20 的长期运行 control runtime（依据 MAAD 仓库 README、仓库结构和论文摘要）。

v20 应借鉴的是这条**宏观产物链**，而不是复制 MAAD 的运行时：

```text
GoalContract
  → AnalystArtifact
  → Investigation / EvidenceBundle
  → ArchitectureOptions / ModelArtifact
  → PlanProposal
  → EvaluatorReport
  → admitted PlanRevision
  → Workflow frontier
```

四个角色在 v20 中不必是四个永久进程，可以是 Macro Planning Workflow 中的四个有界步骤：

| MAAD 角色 | v20 对应 | 主要产出 |
|---|---|---|
| Analyst | Goal/Requirements Normalizer | FR/NFR/ASR、约束、非目标、待确认问题 |
| Modeler | Repository/Architecture Investigator | RepoPrompt ContextArtifact、代码证据、架构候选、依赖图 |
| Designer | Plan/Workflow Designer | PlanProposal、任务顺序、workflow/agent/tool route、验收条件 |
| Evaluator | Plan Consistency Evaluator | 覆盖率、依赖一致性、风险、缺口、是否允许 admit |

以“参考 RepoPrompt CE 为 pg-agent v20 增加 harness”为例，宏观工作流应先产出：

1. **AnalystArtifact**：把目标拆成多语言 ABI、WorkspaceContext、工具执行、AgentRun、长期运行、恢复、权限等需求，并区分必须项与后期项。
2. **InvestigationBundle**：使用 `get_file_tree`、`file_search`、`get_code_structure`、`read_file`、git 和 WorkspaceContext，读取 pg-agent、v13/v23、repoprompt-ce 的真实实现证据。
3. **ArchitectureOptions**：比较“全插件化”和“统一 Kernel + plugins”，列出状态 owner、事务边界、恢复、幂等、跨语言 ABI 的差异。
4. **PlanProposal**：形成 M0 ABI、M1 Kernel、M2 Swift/Python adapter、M3 WorkspaceContext、M4 read tools、M5 write/process tools、M6 workflow/child agent、M7 macro governance 的任务图。
5. **EvaluatorReport**：检查是否产生第二状态源、第二 scheduler、第二推进者、未消费 producer、无 acceptance check 的 task，以及是否把局部 gate 误写成产品能力。

### 9.8 MAAD 不应直接成为 v20 Kernel

MAAD 适合成为 v20 的 `MacroPlanningWorkflowPlugin`，不适合成为：

- PostgreSQL durable state owner；
- 第二个 scheduler；
- 第二个 `Control.execute`；
- 直接写 `v20_runs` / `v20_workflow_steps` 的 agent 群；
- 只输出 Todo 文本、不保存证据和追溯关系的 planner。

其输出必须通过 v20 Control admission：

```text
MacroPlanningWorkflow
  → PlanProposal + EvidenceBundle + EvaluationReport
  → Control.plan_propose()
  → human/policy review
  → Control.plan_admit()
  → active workflow frontier
```

MAAD 的分层记忆可以映射为 v20 artifact 层：

```text
working memory
  → 当前 GoalContract / PlanProposal / context snapshot

episodic memory
  → investigation history / tool results / prior plan revisions

semantic memory
  → reusable architecture patterns / tool contracts / repository facts
```

但三类记忆都不能替代 v20 的 Run/Workflow durable truth；它们必须通过 artifact hash、revision 和 provenance 引用进入控制链。

### 9.9 宏观方向的强制执行边界

宏观规划不是一次性的文档生成。对于非平凡目标，v20 Host 必须满足：

```text
没有 admitted PlanRevision
  → 不得直接进入细节执行 workflow

已有 admitted PlanRevision
  → 只能从 active frontier 选择 task

task 执行失败、证据推翻假设或项目 revision 变化
  → 进入 bounded replan

replan 未通过 review/policy admission
  → 保持 waiting / needs_review，不自动发散到细节分支
```

这样 LoopX/MAAD 的宏观层才能真正承担方向控制，而不是只在细节执行之后生成一个 attention queue。

### 9.10 v20 与当前 LoopX 的关系

v20 不应假设 LoopX 已经提供完整 Macro Planner。当前 LoopX 可以被复用为：

- goal/todo 数据模型参考；
- P0/P1/P2 priority；
- typed task relation；
- attention projection；
- quota/readiness/cadence policy；
- capability lifecycle；
- evidence/ledger 思路。

但 v20 需要补齐：

- RepoPrompt 风格代码调查；
- `ContextArtifact` / frozen context pack；
- 目标到 WBS 的结构化 PlanProposal；
- 依赖图的 admitted frontier；
- 子任务到 workflow/agent/tool 的明确路由；
- 长期运行中的 replan consumer；
- plan revision 与 workflow step 的 Control 接线。

LoopX 的 planning packet 目前更接近“要求模型规划并返回 Todo”，不是一个自动完成调查、分解和 workflow selection 的宏观执行器。v20 应将其升级为明确的 `Macro Planner / Advisor` 协议，而不是让 Host 自由选择细节工具。

## 10. 一条 v20 端到端目标链

M1 必须证明：

```text
start
  → Control admission
  → Worker turn 1
  → TurnReceipt committed
  → decide(run_now)
  → Worker requests workspace_context snapshot
  → Context Plugin returns frozen artifact
  → Worker requests read_file
  → Swift/Python Tool Adapter returns result
  → ToolResult committed
  → Worker turn 2 sees tool result + context artifact
  → Worker completed
  → wait observes completed
  → owner restart/recovery preserves final state
```

这条链中：

- Worker 不读数据库；
- Tool Adapter 不改 Run；
- Context Plugin 不调度 turn；
- Host 不直接调用 Tool；
- Control 是唯一 durable mutation owner；
- Swift/Python 只在 ABI 层替换；
- 结果必须真正进入下一轮 Worker 输入。

如果这条链不能通过，v20 不继续增加新的 workflow 或宏观 policy。

## 11. 开发纪律

### 10.1 不再复制 v13 的阶段扩张

v20 不采用“每个概念一个 stage、每个 stage 一个独立 green gate”的无限追加模式。

每个 milestone 必须有：

```text
local safety gate
composition gate
product-scope statement
consumer proof
```

没有 consumer 的 producer 只能标记为 partial，不得关闭整体 milestone。

### 10.2 不冻结集成接缝

冻结：

- DTO；
- transaction boundary；
- owner/fence；
- state transition；
- digest；
- error taxonomy；
- ABI version。

不冻结：

- adapter 文件布局；
- Host 内部模块；
- Workflow implementation；
- Tool adapter implementation；
- 必要的 vertical wiring。

### 10.3 所有 stop 必须可解锁

每个阻塞必须记录：

```text
decision_id
conflict
owner
allowed options
chosen option
required evidence
verification command
```

不得以新增平行计划替代未解决的决策。

### 10.4 Fake / composition / product 三种状态分开

矩阵至少分开：

```text
fake_local
composition
real_provider
product_deployment
```

Fake 通过永远不自动转换为 product ready。

### 10.5 版本化 ABI

任何 Tool ABI、Worker ABI、Context ABI 行为变化必须：

- bump contract version；
- 新增 golden vectors；
- 保留旧版本兼容窗口或明确停止；
- 不复用已发布错误码和语义。

### 10.6 不在事务里做外部 IO

该纪律适用于：

- provider；
- Swift/Python tool；
- DuckDB；
- RAG；
- WorkspaceContext 外部文件读取；
- process execution；
- ACP/MCP 子进程。

## 12. M0–M7 初步路线

### M0：Runtime Charter + ABI

交付：

- 本设计转为正式 charter；
- Worker ABI；
- Tool ABI；
- Context ABI；
- canonical vectors；
- state machine；
- owner/fence/recovery contract。

不实现完整工具。

### M1：Kernel vertical loop

```text
start → Worker → receipt → decide → steer → Worker → completed → wait
```

Fake Worker，单一 PostgreSQL 数据库，完整 recovery gate。

### M2：Cross-language adapter

至少实现：

- Python reference Tool Adapter；
- Swift reference Tool Adapter；
- 同一组 request/result golden vectors。

### M3：WorkspaceContext + Investigation Surface

接入：

- snapshot；
- frozen context artifact；
- export；
- preset selection；
- context revision/CAS；
- `get_file_tree`；
- `file_search`；
- `get_code_structure`；
- `read_file`。

这一阶段必须先证明“调查结果能进入 ContextArtifact”，再证明 Worker 能使用该 artifact；不要求完整 workflow。

### M4：Macro Planner / Advisor

实现：

- 高层 Goal intake；
- investigation mode；
- PlanProposal；
- task/dependency graph；
- workflow/agent/tool route；
- plan admission；
- active frontier；
- replan trigger；
- human approval boundary。

M4 的纵向 gate 必须证明：

```text
用户目标
  → 调查工具
  → 证据 artifact
  → PlanProposal
  → admitted PlanRevision
  → selected workflow task
```

不能只断言模型返回了一段 Todo 文本。

### M5：RepoPrompt read/write tools

```text
get_file_tree
file_search
get_code_structure
read_file
```

### M6：Write/process tools

```text
apply_edits
file_actions
git
exec_command
```

单独处理路径、进程、超时、取消、hash 和 unknown outcome。

### M7：Workflow + Macro governance

加入：

- child agent；
- handoff；
- context_builder；
- review；
- fairness；
- attention；
- quota；
- long-run soak；
- product roles；
- authorized provider tier；
- macro replan loop。

## 13. 当前明确决策

1. v20 独立于 v13，不做 v13 stage 45。
2. v20 采用统一 Kernel，不采用 durable-state-per-plugin。
3. Worker、Tool、Context、Workflow、Governance Policy 采用插件/adapter 形式。
4. Swift/Python/其他语言通过版本化 ABI 接入，不共享语言特定 fence 实现。
5. WorkspaceContext 是 Context Plugin + Tool/Mutation surface，不是 Worker 内部状态，也不是普通一次性 read tool。
6. DuckDB、RAG、WorkspaceContext 都是临时状态空间；其结果必须以 artifact/digest 形式进入 v20 控制链。
7. Kernel 是唯一 durable mutation owner。
8. M1 先证明一条包含真实 Tool round-trip 的纵向链，再扩展完整 RepoPrompt 工具面。
9. 如果没有 composition gate，就不增加新的工具、workflow 或宏观 policy。
10. v20 必须有 Macro Planner / Advisor；没有“目标 → 调查 → PlanProposal → admitted plan → workflow frontier”的 gate，不能声称长期运行具有正确战略方向。
11. LoopX 的当前 planning packet、Todo、priority、attention、cadence 是可复用的政策和投影基础，但不等于完整自动分解器、workflow selector 或执行 host。

## 14. 待讨论问题

1. v20 是否第一阶段只支持一个 active runtime owner per database/workspace？
2. WorkspaceContext artifact 是否永久进入 `v20_artifacts`，还是只保留引用和 digest？
3. DuckDB/RAG 是本地 adapter、独立进程，还是后期 service adapter？
4. `context_builder` 是一个 Context Plugin，还是一个标准 child Workflow？初稿倾向：两者都有，但底层使用同一 Control/Worker kernel。
5. provider Worker ABI 是否直接采用 v23 DTO 命名，还是升级为 `v20-worker-1` 独立版本？
6. v20 第一条真实跨语言测试是否使用 Swift stub adapter，而不是直接接完整 RepoPrompt CE？
7. Macro Planner 的 PlanProposal 是否必须 human approve，还是允许某些低风险 plan route 自动 admit？初稿建议：默认 human approve，只有白名单 workflow 可自动 admit。
8. 是否把 LoopX 的 P0/P1/P2 作为 v20 plan task 的第一版 priority 字段，还是先使用 v20 自己的 risk/critical-path 优先级？
9. 长期运行是否允许 replan 自动生成新 PlanRevision，还是必须先进入 `needs_review`？初稿建议：默认 needs_review，策略白名单例外。

---

**初稿结论：**

> v20 应该是一个“有层次的统一控制内核”：微观由 Agent Loop、中观由 Workflow、宏观由 **Macro Planner + Governance Policy** 共同承担。Macro Planner 负责调查、分解、排序、选择 workflow/agent/tool 并形成可审核的 PlanProposal；Governance Policy 负责资格、attention、quota、fairness、停复和长期运行约束。三层都通过同一个 Control Kernel 改变 durable 状态。工具是连接控制体系与 WorkspaceContext、DuckDB、RAG 等临时状态空间的语言无关边界。插件化用于扩展执行能力和策略，不用于分裂 durable truth、幂等、推进权和恢复权。
