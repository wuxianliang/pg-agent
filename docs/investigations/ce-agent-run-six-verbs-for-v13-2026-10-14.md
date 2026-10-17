# CE `agent_run` 六动词语义调查 — 为 v13 原生移植

- 日期：2026-10-14
- 调查对象：`/Users/wxl/Projects/repoprompt-ce`（Swift 包，RepoPrompt CE）
- 目的：把 `agent_run` 的六个操作（start / poll / wait / cancel / steer / respond）的控制语义精确记录下来，作为在 v13 agent-loop 之上用 PL/pgSQL 原生实现这六个动词的规约来源。
- 上游报告：`docs/investigations/v20-epoch-operation-for-v13-ce-control-2026-10-14.md`（epoch/operation 身份模型）
- 本报告为只读调查，未修改 repoprompt-ce 任何文件。

路径缩写：

- `RunSvc` = `Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift`
- `ManageSvc` = `Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentManageMCPToolService.swift`
- `Store` = `Sources/RepoPromptDomainRuntime/DomainAgentRunSessionStore.swift`
- `Models` = `Sources/RepoPromptDomainRuntime/DomainAgentSessionModels.swift`
- `Headless` = `Sources/RepoPromptMCPCore/DirectHeadlessProviderCoordinator.swift`
- `VM` = `Sources/RepoPrompt/Features/AgentMode/ViewModels/AgentModeViewModel.swift`
- `RunService` = `Sources/RepoPrompt/Features/AgentMode/Runtime/AgentModeRunService.swift`

## 0. 架构分层

MCP 工具层（`RunSvc`/`ManageSvc`，MainActor）→ 视图模型控制面（`VM` 的 `mcp*` 方法）→ 会话存根 actor（`Store`，进程内唯一权威，app 侧经静态适配器转发）→ provider 运行时（app 的 `RunService`/terminal commit barrier，或无头的 `Headless` coordinator）。app 与 headless 共用同一个 `Store`，epoch/wait 语义完全一致。

dispatch 入口：`RunSvc.swift:417-443`（op 缺省 `"wait"`；worktree 参数只允许 op=start）。

## 1. start

- `message` 必填非空（`RunSvc.swift:446`）；调用方传 `session_id` 一律拒绝（`:455-458`）。
- `workflow_id`/`workflow_name` 互斥；`model_id` 缺省走全局 pair 角色（headless 缺省 `codexExec`）；worktree 参数仅 start 允许。
- 身份：headless 路径 `sessionID = child runID ?? UUID()` 且 **`runID = sessionID`**（`Headless.swift:206-207`）；app 路径 sessionID 是会话级持久 ID，runID 是每轮 provider run ID，**二者不等**（`VM.swift:7292-7298`）。
- 顺序严格：先 `register`，后 `beginEpoch(initial)`（`Headless.swift:219-232`；默认参数 `expectedCurrentEpoch: nil, transitionKind: .initial`）。beginEpoch 失败则 rollback + cleanup。
- snapshot 首发布：headless 在 beginEpoch 成功后立即发布 `.running` 快照，然后才启动 provider task（`Headless.swift:249-286`）。
- `detach` 缺省 false；`detach=true`、快照已非 running、或 `timeout<=0` → 立即返回；否则进入与 wait 相同的阻塞（`RunSvc.swift:1025-1037`）。timeout 缺省 120s（全局设置可覆盖）。
- 返回装饰后的 snapshot（字段见 §2）。

## 2. poll

- `poll` = `executeWait(forcePoll: true)`，timeout 强制 0，纯读（`RunSvc.swift:430-431, 1066-1072`）。
- 读取顺序：store 终态快照优先 → live provider → 无 registration 时合成 `.expired` 快照（`Models.swift:633-660`）→ live 快照 → store 非终态 → expired（`RunSvc.swift:2978-3005`）。
- **不改任何状态**；没有 since/cursor 入参，游标由 store 内部 waiter 管理，客户端不可见。
- `session_ids` 数组走 `executePollMany`，返回分组结果。
- snapshot 字段（`Models.swift:567-627`）：`session_id`、`status`、`transcript_item_count`、`updated_at`，可选 `run_id`、`status_text`、`assistant_text`、`interaction`(+`interaction_id`)、`failure_reason`、`session{...}`、`agent{...}`、worktree 信息。

## 3. wait

- 阻塞机制：`Store.waitUntilInteresting(cursor:timeoutSeconds:)`（`Store.swift:629-724`），continuation 挂在会话 record 上。
- `WaitDisposition` 七值（`Store.swift:150-158`）：`snapshotReady` / `noteworthySnapshot(NoteworthyWake)` / `epochAdvanced(epoch, transitionKind)` / `terminalPublicationRejected(epoch, reason)` / `timedOut` / `expired` / `cancelled`。
- `WakeReason` 两值：`instruction_delivered`、`steering_requested`。`NoteworthyWake` 携带 snapshot + reason + `steeringMessage` + `steeringOriginRunID`。
- interesting 判定（纯函数）：`isActionableForMCPWait` = `interaction != nil || status == .waitingForInput || status.isTerminal`（`Models.swift:559-561`）；`isStartupPendingForMCPWait`（running + 无 runID + 固定文案）**不是** actionable，超时时映射为 `wait_result: "startup_pending"`。
- 入队前快速路径：epoch 已变 → `epochAdvanced`；快照已 actionable → 立即 `snapshotReady`；**timeout ≤ 0 → `timedOut`（这就是 0=poll）**。
- 唤醒源：快照变 actionable；显式 `wakeCurrentWaiters`（steering 打断）；`beginEpoch` 成功唤醒旧 epoch waiter；`publishTerminal`；每 waiter 的 timeout task；cleanup/expire → `expired`/`cancelled`。无 waiter 时 noteworthy wake 挂账（`pendingNoteworthyWake`），下一个 wait 立即取走。
- 工具层循环：`.epochAdvanced` 且 kind ≠ `.unrelated` → 换 cursor 继续等；kind == `.unrelated` → 返回 `wait_result: "superseded"`。
- steering 打断：返回 `wait.result: "interrupted_by_steering"` + `wait.steering_message` + `_meta.wake_reason: "steering_requested"`；打断者是 wait 调用方自己的父 run 时按 `steeringOriginRunID` 抑制 `steering_message`。
- 多 `session_ids`：`executeWaitAny`，先完成者胜，按优先级仲裁（publication_rejected < steering_interrupted < actionable < superseded < expired < timed_out < cancelled）。

## 4. cancel

- 前提（`RunSvc.swift:1244-1286`）：快照 `.expired` → 报错附恢复提示；已 terminal → 报错；会话须 MCP 控制且 `runState.isActive || mcpFollowUpRunPending`（允许取消排队等启动的 run）。
- 执行：startup-pending 先清 pending 标志，然后 `cancelAgentRun(completion: .terminalPublished)`——**等到终态快照发布才返回**。
- **不动 epoch、不动 registration**。终态经 commit barrier 发布（`.cancelled`），走 `Store.publishTerminal(successorKind: nil)` → epoch 留原位、启动 300s expiry TTL、durable metadata 置 `.terminal`（`Store.swift:524-531`）。
- 已排队 steer 的去向：`cancelRun` 清空全部队列（pendingInstructions / Claude / ACP steering 全 removeAll），挂起的 question/approval interaction 一并取消（`RunService.swift:1380-1417`）。对 MCP 调用方而言**队列即被丢弃**。
- 与 `agent_manage.stop_session` 的差别：stop_session 面向会话而非 run，要求 live session，活跃则同样 cancel，但返回会话摘要 + `stop_requested`（`ManageSvc.swift:1120-1163`），不检查 MCP 控制柄。

## 5. steer

入口 `RunSvc.swift:1288-1470`，`message` 必填。两条路径：

**A. run 活跃（同 activation）**：直接 dispatch 注入，**不开新 epoch**（`:1343-1357`）。
- 若当前挂着非 instruction 的 pending interaction（approval/elicitation 等）→ 拒绝，提示用 respond（`VM.swift:11426-11432`）。
- 按 provider 路由投递：Claude → queuedClaudeInterrupt；ACP → queuedACPInterrupt；Codex → dispatchedCodexTurn（带 ack）；其它 → queuedFollowUp。
- 被接受后**唤醒等待者**：`wakeCurrentWaiters(.steeringRequested, steeringMessage:)`。

**B. run 已结束 / 控制柄过期（reactivation）**：找回会话、hydrate、重建控制上下文（`requireInactiveRunState: true`）；若会话 run 活跃但不归此 MCP 柄控制 → 拒绝。**开新 epoch，kind = `.steering`**（`RunSvc.swift:1358-1404`），失败时清 pending 标志。
- epoch 实际 begin：`beginEpoch(expectedCurrentEpoch: context.currentEpoch, transitionKind: .steering)`（`VM.swift:7066-7071`）。

**expectedCurrentEpoch CAS**（`Store.beginEpoch`，350-398）：registration 过期 → `.rejected("stale_activation")`；`currentEpoch != expected` → `.stale(currentEpoch:)`，app 对 `.stale` 直接放弃，对 `.rejected` 尝试 `registerIfMissing` 恢复重试一次。

**wait/timeout_seconds**：`wait` 缺省 false；给了 `timeout_seconds` 即隐含 wait=true；wait=false 却给 timeout → 返回 warning。

**transitionKind 结论**：MCP steer 开新轮一律 `.steering`；`.relatedFollowUp` 是 run 内部排队 follow-up 在 terminal commit 时产生；`.unrelated` 是无 intent 也无 followUpPending 的裸 start。

## 6. respond

入口 `RunSvc.swift:1598-1627`：
- `interaction_id` 必填且必须是 UUID；校验 = **与当前 pending interaction 精确比对**：无 pending → 报错；id 不匹配 → 报错并提示先 poll/wait（`VM.swift:11603-11610`）。目的是防止 agent 自己回答自己的 ask_user。
- 按 pending interaction 的 `kind` 路由：`.instruction` → 走 instruction dispatch（不启动新 run）；`.question` → answers（可 skip）；`.mcpElicitation` → accept（可带 content/meta）/ decline / cancel；`.userInput` → answers 数组（不可 skip）；`.approval` → worktreeMerge review / permissions（accept / accept_for_session / decline / cancel）/ 通用 approval（含 `accept_with_amendment`）；`.hookApproval` → Codex hook 决策。
- **respond 不开新 epoch**：只清掉 pending interaction，run 在同一 epoch 内继续；状态变化以同 epoch cursor 重发快照。返回当前快照 + delivery。

## 7. epoch 模型

`DomainAgentRunTurnEpoch` 字段（`Models.swift:11-43`）：`runtimeID`/`runtimeGeneration`（运行时实例身份+代）、`sessionID`、`activationID`（一次 MCP 控制激活）、`registrationGeneration`、`id`（epoch UUID）、`ordinal`（会话内单调序号）、`continuityGeneration`、`transitionKind`。

四种 transitionKind 产生路径：
- `initial`：会话首个 epoch。
- `relatedFollowUp`：run 内排队 follow-up 在 terminal commit 时作为 successor kind；或 `mcpFollowUpRunPending` 的裸 start。
- `steering`：MCP steer 的 scoped transition intent。
- `unrelated`：无 intent、无 followUpPending 的裸 start；或 staged intent 的 expectedCurrentEpoch 已不匹配。

`continuityGeneration` **仅在 unrelated 时 +1**（`Store.swift:370-372`；publishTerminal successor 493-495）。waiter 跨 epoch 时用它判断"同一会话延续 vs 新话题"：continuity 不同 → 视为 unrelated → 工具层返回 superseded（`Store.swift:850-859`）。

`lastEpochOrdinal` 持久化；resume 时 `nextEpochOrdinal = lastEpochOrdinal + 1`，跨进程重启不回退（`Store.swift:301, 1066`）。

`EpochBeginResult`：
- `accepted(epoch)`：CAS 通过；ordinal 递增、唤醒旧 epoch waiter。
- `stale(currentEpoch:)`：expectedCurrentEpoch 不匹配 → 调用方放弃。
- `rejected(reason)`：registration 失效（stale_activation）→ 调用方可恢复重试一次。

## 8. snapshot 生命周期

Status 六值（`Models.swift:78-94`）：`running` / `waiting_for_input` / `completed` / `failed` / `cancelled` / `expired`；后四者 terminal。
- run 内任何 pending interaction → `waiting_for_input`。
- `followUpRunPending` / `pendingSupersedingTurnCompletions` 会把终态**掩盖**回 `.running`（`VM.swift:7239-7244`）。
- `expired` 不由 run 产生，是控制柄失效时的**合成**快照。
- 合并规则保证终态不被非终态覆盖（`Store.swift:881-896`）。

terminal publication envelope = `{epoch, snapshot}` + 调用侧 `commitID` 与 `successorKind`。`Store.publishTerminal`（420-532）是唯一"恰好一次"终态权威：
- 身份不符 → rejected；同 commitID 重复 → 幂等 accepted；不同 commitID → rejected 并给 waiter 报 `terminalPublicationRejected`。
- epoch 已不是 current → **终态快照只写进该 epoch 自己的归档槽，返回 `.stale`，不动 current**（481-486）。
- `successorKind != nil` → 原子地创建 successor epoch 并切 current、唤醒 `epochAdvanced`。
- `successorKind == nil` → 发布终态、唤醒 `snapshotReady`、启动 300s expiry、metadata 置 terminal。

interaction 表示：snapshot 内嵌 `Interaction{id, kind, responseType, title, prompt, context, options, fields, details}`，kind ∈ instruction / question / user_input / approval / hook_approval / mcp_elicitation。

## 9. wait cursor

`WaitCursor = {registration, epoch?}`。唤醒按 cursor 精确匹配（「同 registration + 同 epoch」的 waiter 才被某事件唤醒）；epoch 更替时唤醒所有落后游标的 waiter 并附 transitionKind，由调用方决定追游标还是放弃（unrelated → superseded）。

## 10. resume（agent_manage.resume_session）

`Store.claimResumableSession`（288-312）：已在内存 → alreadyActive；要求 metadata.resumable 且**持久化基线 state ≠ active（防双活）**；成功则 `nextEpochOrdinal = lastEpochOrdinal + 1`、**continuity 跨 resume 保持**；先落盘，失败回滚。claim 失败退回裸 register（替换旧 registration 并 expire 旧 waiter）。
`resume_session` 复用已有控制注册而不重新 register，只重配模型参数；返回会话摘要而非 run 快照。

## 11. 迟到/过期回执（stale epoch 防护）

三层防护：
1. 快照摄入：`cursor.epoch == record.currentEpoch` 否则丢弃记 `stale_epoch`，不改任何状态（`Store.swift:582-590`）。
2. 终态发布：epoch 已被取代 → 只写归档槽返回 `.stale`；commitID 幂等拒绝冲突提交。
3. provider 侧：superseded turn 的迟到 terminal 由 `pendingSupersedingTurnCompletions` 计数吸收（到达时把 runState 压回 running，掩码 15s 后自清）；terminal commit barrier 提交前重校验 expectedRunID/ownership。

## 12. 对 v13 移植最关键的语义不变量清单

1. **run 身份 = 控制柄身份，且分层**：registration(runtimeID, runtimeGeneration, sessionID, generation) 是一切操作的门票。headless 里 runID==sessionID；v13 移植建议让会话行主键兼任 run 句柄，另加单调 registration_generation 防句柄复用。
2. **epoch CAS**：`beginEpoch(expectedCurrentEpoch)` 是唯一开轮入口；mismatch → stale（放弃或换游标）；registration 失效 → rejected（可恢复重试一次）。ordinal 单调（重启后从 lastEpochOrdinal+1 续）。
3. **stale 回执只归档、不改当前**：迟到 snapshot 丢弃；迟到 terminal 写进自己 epoch 的归档槽返回 stale；当前 epoch/快照绝不被旧回执覆盖；终态只可被更新的终态替换。
4. **终态恰好一次**：terminal envelope + commitID 幂等；successor 创建与 current 切换在同一原子步骤内完成。
5. **interesting 判定纯函数化**：`interaction != nil || waitingForInput || isTerminal`；startup-pending 不是 interesting。可直接落成 SQL 视图/CHECK。
6. **waiter 按 cursor 精确匹配**：epoch 前进时唤醒落后游标的 waiter 并附 transitionKind；调用方决定追游标（related/steering）或放弃（unrelated → superseded）。
7. **continuityGeneration 只在 unrelated 时 bump**；resume 必须恢复它，不能清零。
8. **start 永远新建会话**（拒绝 caller 给的 session_id）；**继续已有会话只能走 steer**；steer 在活跃 run 上是同 epoch 注入 + 唤醒打断（附 steering_message），在非活跃 run 上是新 epoch(kind=steering)。
9. **respond 不开 epoch**：interaction_id 必须与当前 pending 精确匹配（一次性、不可重放）。
10. **cancel 清队不迁 epoch**：丢弃全部已排队 steer/follow-up、取消挂起 interaction，发布 `.cancelled`；终态快照保留 TTL（CE 用 300s）供迟到 poll，之后句柄 expire（合成 expired 快照 + 恢复提示）。
11. **唤醒打断是一等语义**：等待者被 steer 打断时拿到打断消息本身（自己 steer 自己按 originRunID 抑制），并被指示重新 wait；无 waiter 时 wake 挂账一次性投递。
12. **durable metadata 与执行态分离**：(lastEpochOrdinal, continuityGeneration, state, resumable) 持久化且 CAS 落盘；resume 需持久化基线非 active，防双活。与 Postgres 行级 CAS（`UPDATE ... WHERE state <> 'active'`）天然对应。

## 13. 注意点 / 未覆盖

- headless 模式 agent_run 只支持 start/poll/wait/cancel 四 op；steer/respond 是 app 路径专属。**v13 要全六 op，语义应以 app 路径为准**。
- app 路径 snapshot 的 runID 是每轮 provider run ID 而非 session ID；移植时必须明确选一个（上游 v20 alpha 选了 runID==sessionID）。
- 授权层 `AgentSessionTargetOperationGuard`（每个 target-bearing op 的 caller 校验）未深入展开；v13 侧可对应 ACL stage（`v13/acl/v13_acl.sql`）的 kinship/授权检查。
