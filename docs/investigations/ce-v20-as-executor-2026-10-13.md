# Investigation: CE 把 v20 当作执行者

## Summary

可以。接缝是章程已经分开的两层：v20 的 `Control.execute` 做 turn 的 durable 执行，CE 的 Swift 工具面做 Tool Adapter 和 Context Plugin。把 v20 注册成 CE 现有的 provider 可执行文件，会让 CE 的 session/epoch 和 v20 的 Kernel 同时写控制事实。

## 两边现在谁在执行

无界面路径在 `DirectHeadlessProviderCoordinator.startAgent`（`DirectHeadlessProviderCoordinator.swift:188`）。它自己分配 `sessionID`，`:207` 令 `runID = sessionID`，`:219` 向 `agentSessionStore.register`，`:222` 开 epoch，然后 `:268` 调用 `runProviderOnce`。`runProviderOnce`（`:137`）用 `ProviderDescriptor.executable` 启动进程。目录里目前只有 `codexExec`（`:102`–`:114`），参数是 `codex exec --json`（`:117`–`:123`）。一次进程读入整段 message，返回一段 assistant 文本（`:177`）。

界面路径是 `ACPIntegratedAgentModeRunner`。工具调用经 `AgentToolTrackingController` 回到 Swift（`ACPIntegratedAgentModeRunner.swift:1807`–`:1812`），写入会话正文。章程把这条传输叫做 ACP，并规定它和 Worker ABI 分开（`v20-runtime-charter-draft-2026-10-12.md:491`–`:502`）。

v20 的执行者是 `Control.execute`（章程 `:186`）。公共动词是 start、poll、wait、steer、respond、cancel、spawn、handoff（`:192`–`:199`）。一次 turn 是 admit → `WorkerRequest` → 事务外 Worker → `TurnReceipt` → disposition（`:80`–`:87`）。工具走另一份契约 `v20-tool-1`（`:306`–`:339`、`:459`）。Swift 可以实现这份契约，不共享 fence 代码（`:483`–`:488`，决策 4，`:1195`）。

## 哪条接缝是现成的

章程的插件清单里，Worker、Tool Adapter、Context、Provider 都可替换，durable 写入不可替换（`:508`–`:541`）。路线是 M2 做 Swift Tool Adapter（`:1103`–`:1108`），M3/M5 再接 WorkspaceContext 和 `read_file` 等 RepoPrompt 工具（`:1111`–`:1160`），M7 才把 child agent、handoff、context_builder 放进同一个 Kernel（`:1174`–`:1180`）。决策 6 写明第一条跨语言测试用 Swift stub，不直接接完整 CE（`:1211`）。

CE 侧已经有按能力切开的后端。`DomainAgentCapabilityBackend`（`MCPDomainStandaloneCapabilityProvider.swift:94`–`:107`）的 `run` / `manage` 就是 agent_run 和 agent_manage。工作区读写在 `DomainWorkspaceCapabilityBackend` 和 `DomainFilesystemMutationBackend`（`:65`–`:78`）。这些方法今天由 CE 自己实现。它们的形状正好是 v20 Tool Adapter 的调用方和被调用方，不是 provider 进程槽。

因此现成的组合是：

- v20 Kernel 受理 turn、工具、receipt 和恢复。
- CE 的 `run` / `manage` 变成上述公共动词的客户端，不再并行 `register` + `beginEpoch`。
- CE 的读文件、改文件、workspace snapshot 实现 `v20-tool-1`，在事务外执行，把 digest 交回 Kernel。
- `AgentSession` 继续保存界面正文。`providerSessionID` 仍是模型恢复句柄，不进 Kernel。
- 模型进程留在 Worker 后面的 ProviderPlugin。ACP runner 负责展示和工具跟踪，不再另开一份 epoch。

## 哪条接缝会变成两套执行者

`ProviderDescriptor` 只暴露一个可执行文件（`:25`–`:28`）。`startAgent` 在启动该文件之前已经写了 session、epoch 和 cancellation handler（`:219`–`:288`）。若把 v20 放进这个槽：

- CE 仍持有 `DomainAgentSessionDurableMetadata` 的 generation 和 epoch。
- v20 仍持有 revision、owner fence 和 turn admission。
- 一次 `codex exec` 式调用只交换一段文本，装不下 v20 的多轮工具、CAS 和 wait/notify。

上一份调查已经核对：CE 的 durable metadata 没有 workflow id。实验 schema 的 `sessions.workflow_run_id` 非空外键不是这条接缝的前提。session 文档也不该因为要调用 v20 而被整份写入 Kernel。

## Recommendations

1. 执行者固定为 `Control.execute`。CE 的 agent 后端调用 start/poll/wait/steer/cancel/spawn/handoff。
2. 第一份 Swift 代码按 M2 做 Tool Adapter stub，再按 M5 接 CE 已有的读文件和搜索。完整 CE 进程不是第一条 ABI 测试。
3. `AgentSession` 的 id 可以与 v20 session id 相同。正文、`providerSessionID` 和 workflow 模板留在 CE。generation、epoch、revision 只留在 Kernel 一份。
4. 不把 v20 注册为 `codexExec` 那种 `executable`。
