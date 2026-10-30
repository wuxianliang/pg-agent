# Investigation: DeepSeek Harness 的设计，以及对 v24 数据库原生 agent 的启发

- 日期：2026-10-29
- 状态：完成（2026-10-29；4 个 explore + context_builder + pair + 2 oracle lanes，承重行号已复核）
- 对象：`/Users/wxl/Projects/deepseek-harness`（DSH，本地 checkout `14fbc07435`）、`/Users/wxl/Projects/pg-agent` v24
- 目的：提取 DSH 在 loop、会话、事件、工具、插件、控制面上的设计裁决，判断哪些应被 v24 吸收，哪些与 v24 的单一权威/唯一 advance 冲突

## Summary

v24 的骨架足以承载 agent loop，但它目前是一个 **PostgreSQL 权威的 effect 准入/结算内核 + 窄 agent loop + host 执行面**；它不是 DSH 那样的 **session-level 会话运行时**，但已经是 **run 级 agent runtime**，并有 `agent.spawn` 的 child run 树（见下方 Addendum）。DSH 最值得迁移的不是 event-sourced log 本身，而是三条不变量：**模型可见事实必须持久、输入必须可 claim/reject、工具定义与 transport 分离**。

v24 的真实缺口有两个。第一，host journal 已经承担了 provider transcript 与 tool-call identity（`v24/host/worker.py:944`、`:1125-1137`、`:1190-1231`），但 DB 没有一条“模型看到过什么”的派生规则；journal 因此从 I/O 证据变成了语义权威。第二，`ToolDescriptor` 只有 wire、没有 definition：参数/输出 schema 不执行、没有 render、没有 replay/approval/sandbox/limits 声明（`v24/sql/48_loop.sql:300-307`、`:1133`、`:1385-1387`）。

修这两个缺口（K1/K4）不需要第 11 张表，也不需要第二套 claim/queue/recovery：把 provider call id、model-facing content/meta 放进现有 effect request/outcome，加一个只读 `derive_model_messages(run_id)`，host 改为读 DB 派生即可。K2/K3/K5/K6 要么是文档/术语修正，要么是 host 责任，要么可以后置；DSH 的 session log、surface、pre-step waterfall、PTC typed SDK 都不应整体搬入。

## Addendum 2026-10-29: “不是会话运行时” 的准确边界

用户的质疑成立：v24 参考了 RepoPrompt，应该能表达“一个 session 派一个 agent，再派子代理一起工作”。上一句需要限定为 **session-level 会话运行时**，不能推广成“不能派子代理”。

### v24 已经有的

- `runs.parent_run_id` / `spawn_key` / `spawn_request_digest`，唯一索引 `u_runs_spawn`，自引用 FK `f_runs_parent`（`v24/sql/10_schema.sql:28-30,60-64`）。
- `agent.spawn` 是 model outcome 的保留 intent；同一 `advance` 原子创建 child run、spawn edge、父 quota 扣减、child 初始 quota、child 首 `model_call`、`run_spawned`/`run_started` events（`v24/sql/48_loop.sql:610-810`、`:1225-1290`）。
- child 是 `runs` 行，不是 fiber/install；`§6.8` 明确“child agent spawn 默认 run_start + parent_run_id + owner_fiber/episode pin，不是 install child fiber”。
- G7-A…H 覆盖创建/回滚、同 key 重放/冲突、预算守恒、ownerless child、无新表、child 首 model 恢复。
- child 的 model 也能再发 `agent.spawn`：没有 depth 列/检查，递归受预算约束。

### 还缺什么（RepoPrompt 式 session → agent → subagents）

1. **没有 session 对象。** `scope` 是生命周期/能力分组，`run` 是一次执行；没有跨 run 的 `session_id` / agent 身份。一个长 run 可以模拟一次 session，但 run 终态后新 run 不自动属于同一 session。
2. **没有 per-run role/model/provider。** spawn args 的闭集只有 `v/spawn_key/input/scope_id/budget/owner_fiber_id/owner_episode_id`（`48_loop.sql:620-623`），没有 role/model/policy；设计 §5.5 `:307` 说“role/policy”，实现只能把它们塞进 opaque `input`，内核不校验也不据此选择 adapter。child 的 model call 仍走 host 的单一 adapter。
3. **没有 parent-child join/await/result。** spawn 返回 `{run_id,spawn_key,child_effect_id}`；spawn 分支不追加 `v_succ`，父 model settlement 返回空 `successors`（`48_loop.sql:1228-1288`），父 run 保持 `running` 但没有 ready effect。child 完成后不会唤醒父，也不会把 `child.result` 送回父；`poll/wait` 都是 per-run，没有 parent wait-on-child。
4. **spawn 只能由 model outcome 触发。** 一个 outcome 最多一个 spawn，且不能与 tools/final/interaction 混用；没有 operator-initiated child start，也没有 parallel multi-spawn batch。控制面可以 `start` 一个顶层 run，但不能直接挂 `parent_run_id`。
5. **没有 session/child transcript。** host journal 是 per-run（D4）；child transcript 不聚合，session 级历史没有统一读取面。
6. **没有 delegation depth / max children 策略。** 只有 budget 约束；递归 spawn 没有显式深度上限。

### 结论

v24 = **run-level agent runtime + durable spawn tree**；不是 RepoPrompt 式的 **session-level orchestration runtime**。要“一个 session 派 agent 再派子代理一起工作”，缺的是 orchestration/session projection，不是 spawn 原语：

- **A. 控制面方案（推荐，先不改内核）**：session = `scope` + root run；控制面维护 session 元数据（session_id、agent profile、child links），poll child runs，收集 `result` 后用 `steer`/`respond` 唤醒父 run；需要稳定 session 身份时，加一个 `root_run_id`/`session_id` 的只读投影，不建第二状态机。
- **B. 内核设计修订（若要原生）**：operator-initiated child start、multi-spawn batch、parent-child join/interaction、spawn 的 role/model 字段、depth/child caps、session transcript。不要借此引入第二 queue/claim/recovery。

### 新发现的文档漂移（未在 W1 修复）

设计 §5.5 `:307` 说 `(parent_run_id,spawn_key)` 唯一绑定 “canonical input bytes、role/policy/scope/budget request”，但 `48_loop.sql:620-623` 的 spawn args 闭集没有 role/policy；只能塞进 opaque `input`。这是一条待核的 documented≠implemented 漂移，建议下一轮事实核查单独处理（要么改文档，要么把 role/policy 提升为显式字段）。

## Symptoms / Questions

- v24 已经是“agent loop + 控制结构”的数据库复合体，但工具/插件/上下文面仍偏薄。
- 用户希望参照 RepoPrompt 与 Pi 从零开发新工具，并实现多语言插件设计；需要知道 DSH 在这条路上做对了什么、踩过什么坑。
- 核心问题：
  1. DSH 的 loop 与持久化边界在哪里？谁是事实权威？
  2. DSH 的 session/event/turn 模型如何支持 replay、resume、steer、cancel、compaction？
  3. DSH 的 tool/plugin 模型如何做到“一切皆插件”？多语言/多运行时如何接入？
  4. DSH 的控制面（inbox/claim/waterfall/queue）与 v24 的 effect/claim/advance 有何同构/冲突？
  5. 哪些 DSH 设计应被 v24 吸收，哪些必须拒绝（避免第二套状态机/第二真相源）？

## Background / Prior Research

> Phase 1.5 四个 explore 的结果汇总。DSH checkout `14fbc07435`；引用均为 `deepseek-harness/…` 或 `v24/…`。

### B1. DSH 的执行/持久化骨架（explore A）

- **执行单位是 turn > step。** 一个 step = 一次 model request + 它请求的 tool calls；一个 turn = 零或多个 step，在第一个输入被 claim 之前打开（`docs/architecture.md` Turn flow；`packages/core/session/src/types.ts:288-303`）。loop 在 `ReactLoopAgent`（`packages/core/agent-loop/src/agent.ts:96`），驱动插件是 `AgentLoop implements AgentFactory`（`agent-loop/src/index.ts:341`）。
- **唯一持久权威是 append-only `SessionEvent` log。** 内存中的 surface / projections / model messages 都是从 log 派生（`packages/core/session/README.md` "Model-visible means logged"；`core/session/src/index.ts:984` `deriveMessages()`）。append 是唯一 mutation：JSON-snapshot + validate + deepFreeze + 连续 seq（`core/session/src/index.ts:798-829`）。
- **模型调用不是一个事件，而是一组 settlement 事件**：`request/header`（config + adapterDefaults + tools）、`request/context`、`assistant/message`（含 embedded timed stream + usage）、`assistant/attempt`（失败/重试/取消的 log-only attempt）、`llm/retry`。工具调用是 `tool/call` + `tool/result`，后者用 `sourceEventSeqs:[callSeq]` 引用前者（`core/session/src/types.ts:342-389`；`agent-loop/src/tool-calls.ts:265-289`）。
- **Replay/resume/fork**：replay 只重放 raw events 作为 seed；model messages/surface/projections 重新派生。resume 先拿 `persistence.open(id,'write')` 的**独占写所有权**（不是 lease/fence），再读 log，把 `interruptedTurnClosers(persisted)` 作为普通 batch append（`agent-loop/src/index.ts:876-905`；`repair.ts:53-101`）。fork = 精确前缀 + `session/end-seed{inherited:true}` + `openTurnClosers({kind:'forked'})`（`core/session/src/fork.ts:23-30`）。
- **持久化是 seam**：`ctx.sessionPersistence` 的 `SessionHandle` 契约；`flush` 是 durability barrier；JSONL backend 用 generation/lease/migration（`packages/session/session-persistence/README.md`）。checkpoint policy 在模型流第一 chunk 前、top-level tool body 前、每个 pre-step flush（`session/session-checkpoint-policy/src/index.ts:31-80`）。
- **"一切皆插件"**：`ctx.llm`、`ctx.tools`、`ctx.sessions`、`ctx.agents`、`ctx.agentLoop`、`ctx.systemPrompt`、`ctx.sessionProjections`、`ctx.sessionPersistence`、`ctx.shell`、`ctx.fs`、`ctx.sandbox` 等服务都可替换；但 durable `SessionEvent` 词汇、JSONL generation/migration、`ToolRuntime` 的 monotonic guard/`tools/result` 不变量、profile/bundle/patch launcher 事实上是 core（`docs/architecture.md:5-13,107-121`）。

### B2. DSH 的控制面/lifecycle（explore B）

- **公开动词不是 start/poll/wait/respond/compact/spawn。** Agent handle 上是 `send / followup / steer / inject / cancel / whenIdle / runMaintenance`（`core/agent/src/runtime-types.ts:163-243`；实现 `agent-loop/src/agent.ts:154-204`）；`create/resume` 在 factory（`agent-loop/src/index.ts:688,843-926`）；远端 RPC 是 `prompt|cancel|updateQueue`。
- **Steering = durable inbox + pre-step waterfall。** 两个 pending list：`next-turn` / `next-step`。`followup` = `send(...,'next-turn',true)`；`steer` = `send(...,'next-step',true)`；`inject` = `next-step` 但不 wake。每次 mutation append `agent/inbox/spliced`；`claim` 一次 drain 全部 `next-step` + 恰好一个 `next-turn`；`agent/pre-step` waterfall 的 `{kind:'reject'|'enter'}` 是权威（`agent-loop/src/inbox.ts:109-114,198-243`；`agent.ts:267-288,318`）。
- **Cancel 是协作式 signal，不是进程 kill。** `cancel(cause,{keepInbox})` 清 inbox（durable canceled splice），然后 abort phase 的 `AbortController`；in-flight model 写 `assistant/attempt`，已开始的 tool 按 model 顺序 drain，未开始的 tool 得到 synthetic error；turn 以 `turn/end{kind:'aborted'}` 关闭（`agent.ts:175-181,344-398`；`tool-calls.ts:1-13,44-58`）。
- **状态机只有 `idle|running`**；`maintenance` 故意不可观察；没有 `waiting`/`terminal` 状态。durable turn/step 状态由 log 的 `turn/start|end`、`step/start|end` 派生（`core/agent/src/types.ts:78-87`；`core/session/src/types.ts:289-302`）。
- **子 agent**：parent/child link 是 child session header 的 `parentSession/delegationDepth/origin`（`subagent/src/child-agent.ts:135-154`），继承 provider/model、composition/preset、bounded seed prefix；不继承权限扩大（`:171-175`）。
- **Crash recovery 没有 lease/fence/TTL**：fence 是 exclusive write ownership；恢复时 `interruptedTurnClosers` 合成 `tool/result` errors、`step/end`、`turn/end{interrupted}`；outcome-unknown 标 `TOOL_OUTCOME_UNKNOWN` 并明确"verify external state, do not retry blindly"（`repair.ts:15-41`；`session-query/src/cold-read.ts:55`）。
- **Compaction 完全 durable**：`compaction/start|summary|end` + 一条带 `surfaceOp:{op:'replace'}` 的 `user/message`，summary 必须严格小于被替换内容；未匹配的 `compaction/start` 当 crash tail replay（`compaction/src/types.ts:24-82`；`compaction-basic/src/region.ts:418-421,569-583`）。

### B3. DSH 的工具/插件/多运行时（explore C）

- **ToolDefinition**：`{name, description, parameters, output:{schema, render, presentationMeta?}, execute}`；model-visible 只有 `{name,description,parameters}`，`timeoutMs`/`isConcurrencySafe`/presentation 不暴露（`core/tools/src/index.ts:216-296,1291-1305`；`llm/llm/src/types.ts:491-502`）。
- **执行管线**：`tool/call` 先 append → staged scheduler（prepare/dispatch/finalize/finish）→ `tools/pre-execute` waterfall → monotonic `guards` → `tools/execute` waterfall → body → `projectContent` → `tools/post-execute` → `finalizeContent` → `tools/result`（`core/tools/src/index.ts:1501-1548,1609-1693`；`agent-loop/src/tool-calls.ts:17,170-195`）。
- **审批/沙箱**：`tools/pre-execute` 可 allow/deny/cancel/ask；`ctx.tools.guard` 只能 deny、不能 re-allow；`ctx.approval` 服务（fail-closed，无 answerer 即拒绝）；`ctx.sandboxPolicy` 默认 read-only，`ctx.sandbox.confine()` 由 bwrap/Landlock/Seatbelt 实现；escalation 是严格放宽阶梯（`sandbox/src/escalation.ts:30-56`；`sandbox-local/src/index.ts:325`；`shell/bash-sandbox/src/index.ts:187-188`）。
- **结果 envelope**：`ToolExecutionResult = {isError, value?, content, error?, meta?, additionalContexts?, concludesTurn?}`；错误 `ToolFailure{message,info:{name,code,reason?}}`；registry 在 `tools/result` 前做 lossless-JSON + deepFreeze；没有中间 byte cap，只有外层 `run_code` 走 output cap + spill（`core/tools/src/index.ts:490-594,653-660,1679-1693`；`spill/spill-policy/src/index.ts:48-105`）。
- **多运行时**：native tools 同进程；MCP 是 stdio/HTTP 子进程，工具名 `mcp__<server>__<raw>`；PTC 的 `run_code` 生成 TS/Python typed SDK（`ts-types.ts`/`py-types.ts`），Python backend 文档存在但 experimental/private，container isolation 无 shipped backend；subagent 有 `dsh-sdk`/`acp`/`claude-code`/`codex` provider；SDK/ACP 是 JSON-RPC line transport（`mcp-client/src/transport.ts:33-46`；`ptc-runtime/src/index.ts:104-129`；`subagent/subagent/src/index.ts:2`）。
- **"Everything is a plugin" 的边界**：model adapter、tool registry、session log、agent loop 都可替换；但 durable event vocabulary、persistence generation/migration、ToolRuntime 的 guard/result 不变量、launcher 是 core（`docs/architecture.md:5-13,107-121`）。

### B4. pg-agent 已记录的 DSH 结论（explore D）

- **没有正式的 KEEP/DROP/SALVAGE 裁决**；只有设计规则。KEEP：保留官方 headless startup/runner 的插件实现与配置语义、复用 `LlmAdapter`/`composeEntries()`/Loader、memory-only 优于临时 persistence provider、DSH 两平面 ≙ v13 events+视图。DROP：upstream `cli.patch.yml`、`CliMockAdapter`、PTC/auto-retry/fallback/shell/PTY/LSP/browser/MCP/background jobs/HMR、`tools.mode` 固定 native。SALVAGE 为 DB 形态：Cordis 五概念有落点，waterfall 收窄，HMR = version switch + drain（`docs/designs/cordis-plugin-system-2026-10-25.md:660-718`）。
- **v8 pinned host 从未实现**：`v8/compat/pinned_host_manifest.json` 五件套全是 `null+note`，`driver_switch_capability="unsupported"`，reporter 拒绝任何 "passed"（A85；README:54）。J1 没有 `v8/compat/host/`、没有 `test_host_pin.py`、没有 commit；J2–J8 全未建。
- **具体 blocker**：profile 软读缺失 → 静默 no-op → 60s timeout 误诊；agent-default-model 配置路径缺失；第 4 个 `!!js`（`tools.mode`）与"三绑定"规则冲突；GB 级 preparation 生命周期/磁盘所有权未定义；DSH 逻辑 seq 从 0 连续，v8 raw seq 含 audit/observational，不能简单 ±1；resume 的 synthetic closers 只能 match 既有 terminal facts，不能由 host 猜；pre-execute 派发太早（之后还有 ask/guard/cancel）；required-hook 缺失/超时必须 fail closed。
- **已记录的警告**："行为合同是规范；pinned compat 是参考实现，不是自动漂移的真理来源"（`v8-dev.md:20`）；"profile 只替换 persistence/storage provider，不另建 JSONL 真相"；"唯一权威：v8 session_events/控制态决定执行结果…不另建可独立推进的事件日志"；"不能用 Native 的绿来冒充 portable"；"本地源码已定位，不等于已验证 pin"；"无上游侵入默认：DSH 源只读 pin，扩展默认在 pg-agent"。
- **尚未评估、值得 v24 看的**：inbox+claim steering waterfall；pre-step authoritative reject（claimed batch 已移除、open turn 不花 step）；attempt vs message 的失败记录；turn/step lifecycle + bounded rolling tool pool + barriers；三个 checkpoint flush 点作为 budget/coeffect 机制；live-vs-compact stream dedup；`request-error` continue-retry policy；provider-adapter waterfall serialization + extensions。

## Investigator Findings

> 调查日期 2026-10-29。DSH checkout `14fbc07435`；v24 为已实现 S1–S8 + M-R/M-P。引用 `path:line`。**documented** = 规格/文档声明；**implemented** = 源码实际执行路径。本轮只读，不改源码。
>
> 结论先行：v24 与 DSH 不是"同一问题的两种介质"，而是两个不同权威。DSH 的权威是**模型可见事实**；v24 的权威是**执行资格与回执**。v24 能证明"调用发生过、结果是什么"，不能证明"模型看到过什么"；DSH 能证明后者，但执行资格只是会话状态。这个差异决定了下面十条裁决。

### I0. 四处 documented ≠ implemented（先钉住，否则矩阵会引用错误前提）

| # | 文档声明 | 实现 | 后果 |
|---|---|---|---|
| D1 | `turn_no bigint` = "已提交模型步骤数"（`docs/designs/v24-pg-agent-2026-10-22.md:136`） | `turn_no` 在 model settlement 与 **tool settlement** 各加一（`v24/sql/48_loop.sql:588`、`:1411`，分别写回 `:1255`、`:1716`） | `turn_no` 是"已结算 effect 数"，不是模型步数，更不是用户轮次。v24 没有 step 事实。 |
| D2 | "参数只按冻结 JSON schema 校验"（设计稿 `:273`） | 只校验 `{key,args}` 形状、`key` 长度、`args` 为 object（`48_loop.sql:300-307`）；`slots.descriptor` 是不透明 `jsonb`（`v24/sql/10_schema.sql:190`），从不按 schema 校验参数 | 参数 schema 未在准入处执行；模型可发任意 object，只有插件自己会拒绝。 |
| D3 | "tool 若是纯读取且输出确定，可以声明 `replay_safe`"（设计稿 `:576`） | 所有 `tool_call` successor 硬编码 `replay_policy='no_replay'`（`48_loop.sql:1133`） | 任何 host 崩溃/租约过期都把只读工具变 `unknown` 并 `blocked_unknown`（`v24/sql/49_recovery.sql:369-375`），run 终止。 |
| D4 | 唯一权威是十表 + events；设计稿只在 D1 债务里提 "host durable journal" 作为 IO 记录（`:466`） | 模型历史由 host journal 重建（`v24/host/worker.py:944`、`:1190-1231`）；provider `tool_call_id` 也从 journal 取（`worker.py:1125-1137`）；journal 是 fsync 的 append-only JSONL（`v24/host/journal.py:1-15`） | **实现中存在第二真相源**：删掉 journal，DB 无法重建可回放的 provider transcript（缺 provider call id、原始 arguments 字符串、reasoning_content）。 |

D4 是本轮最重要的发现，也是矩阵第 1 行判 ADAPT 而不是 ADOPT 的原因。

### I1. Adoption matrix

| DSH mechanism | DSH evidence (file:line) | v24 equivalent / gap (file:line) | verdict (ADOPT / ADAPT / REJECT) | minimal v24 change |
|---|---|---|---|---|
| 1. 事件溯源 session log；模型可见消息从 log 派生，"model-visible means logged" | `packages/core/session/src/index.ts:984`（`deriveMessages`）；`packages/core/session/README.md:100`；`docs/architecture.md:124` | 无消息派生函数；`worker.py:944` 从 host journal 重建，`worker.py:1125-1137` 从 journal 取 provider call id；`effects.request` 只存 `{key,args,descriptor_digest,batch_digest}`（`48_loop.sql:1134-1138`），模型 outcome 的 `tool_calls` 只有 `{key,args}`（`v24/host/deepseek.py:526-527`） | **ADAPT** | 加只读 `v24.derive_model_messages(run)`；把 provider call id、assistant 文本、tool content 落进 effect outcome；journal 降级为 IO receipt，不再是历史来源 |
| 2. turn &gt; step 边界 + `turnBoundary` 投影 | `agent-loop/src/agent.ts:298-398`（turn 开/关）、`:331`/`:358`（step）；`agent-loop/src/index.ts:57-95`（turnBoundary **投影**，非表）；`core/session/src/types.ts:288-303` | 只有 `turn_no` 计数器（D1）；无 step id、无 turn 开闭事实、无"claim 了输入但零 step"的表示；`runs` 无 input 列表（`10_schema.sql:30-58`） | **ADAPT** | 不建表：`effects.request.step_no` + `effects.request.turn_no`；turn 开/闭写 run entity 的 `turn/opened`、`turn/closed` events，由投影折叠；是否要"用户轮"取决于第 3 条 |
| 3. durable inbox + claim + 权威 pre-step waterfall | `agent-loop/src/inbox.ts:109-114`（claim 一次 drain 全部 next-step + 恰好 1 个 next-turn）、`:167-243`（每次 mutation 写 splice 事件）；`agent.ts:271-288`（claim 后 waterfall）、`:319-322`（reject 关闭 turn 且不花 step）；`agent.ts:154-173`（send/steer/inject） | `runs.pending_steer` 单槽 jsonb（`10_schema.sql:43`）；`steer` 写 `{instruction,generation,epoch}` 且 **latest wins**（`40_interpreters.sql:920-923`；消费处 `48_loop.sql:905`、`:1610-1616`）；无 batch、无 reject、无 inject-without-wake、无 per-message 身份 | **ADOPT**（表示改为 events 投影） | `input/queued`、`input/claimed`、`input/cancelled` 事件 + 投影；claim 与 `model_call` successor 同一 advance；不建表、不建第二队列/claim |
| 4. 协作式 `AbortController` + synthetic tool results | `agent.ts:175-181`；`tool-calls.ts:238-243`（abort 后 drain + 为未启动调用写 synthetic）、`:249-260`；`repair.ts:166-194`（`TOOL_NOT_STARTED`/`TOOL_OUTCOME_UNKNOWN`） | `command_cancel` 只写 DB：ready→`cancelled`（**outcome 为 NULL，无回执**）、claimed→`cancel_requested`（`40_interpreters.sql:757-766`）；host worker 从不读 `cancel_requested`（`worker.py` 全文无此字段） | **ADAPT** | host 在 IO 循环/进程读循环里响应取消并杀进程组；ready→`cancelled` 的 outcome 保持 NULL（`10_schema.sql:103`），由 K1 派生层解释为 `cancelled_before_dispatch`；claimed 仍走 late/unknown |
| 5. `assistant/attempt`：settled failure 留在 log、不进模型历史 | `core/session/src/types.ts:356-362`；`agent.ts:484-492`；`core/session/README.md:100` | model failure 直接 seal run（`48_loop.sql:970-986`）；无 retry；失败 effect 的 outcome 就是它的 receipt | **ADAPT**（只加派生规则） | 规则："failed/superseded model effect 永不产生模型消息"；若加 retry，则**每次 attempt 一个 model_call effect_id**，不新增事件类型 |
| 6. 工具管线：`tool/call` 先落、pre-execute/guards/execute/post-execute、canonical output schema、独立 render | `core/tools/src/index.ts:224-237`（ToolDefinition）、`:214-221`（output）、`:1497-1547`（pre+ask+guard）、`:1649-1692`（post+finalize）、`:573-597`（envelope）；`tool-calls.ts:263-289` | `tool/call` 前置于执行已由 `tool_call` effect 满足（`48_loop.sql:1128-1139`）；但无 output schema、无 render、无 guard/post、descriptor 不透明（D2） | **ADOPT**（definition）/ **REJECT**（SQL 内 waterfall） | `ToolDescriptor v2`：`parameters`、`output.schema`、`render`（digest+version）、`approval`、`sandbox`、`replay_policy`、`limits`；在 model settlement 冻结、claim 前 host 复验 |
| 7. `ctx.approval`（fail-closed）+ monotonic guards + `ctx.sandbox` | `core/tools/src/index.ts:1725-1772`（无 answerer 即拒）、`:725-738`（guard 只能 deny）；`sandbox/sandbox/src/escalation.ts:30-56`；`sandbox/sandbox-local/src/index.ts:325`；`shell/bash-sandbox/src/index.ts:100` | 无 tool-level approval；只有 DB role ACL（`50_permissions.sql`）与 approved registry 固定 argv/cwd/env（`v24/host/registry.py:1-20`） | **ADAPT** | descriptor 声明 `approval`/`sandbox`；host 执行前拦截并在 receipt 里写 `approval_required`/`sandbox_denied`；内核只存 run 级 grant 列，不引入 waiting 状态 |
| 8. lossless JSON value + `render` + `presentationMeta` + spill | `core/tools/src/index.ts:214-221`、`:653-660`（只查 lossless，无 byte cap）；`spill/spill-policy/src/index.ts:48`；`ptc-runtime/ptc-runtime-node/src/config.ts:35`（64 MiB 外层上限）、`bootstrap.ts:191-192`（overflow 是错误不是截断） | `output` 必须是 object（`48_loop.sql:1385-1387`）；模型看到 `canonical_json(output)`（`worker.py:1066-1071`）；单行 64 KiB（`v24/host/line_json.py:1-30`，`process_io.py:19`）；inline 进 `effects.outcome` | **ADOPT** | receipt 增 `content`（render 结果，ContentBlock 形状）+ `meta`；render 身份进 descriptor digest；超限内容存 spill ref，不再用 64 KiB 截断 |
| 9. PTC typed SDK / MCP / subagent providers | `mcp/mcp-client/src/transport.ts:33-46`（stdio/HTTP）；`mcp/mcp-client/src/tools.ts:250-268`（MCP→ToolDefinition，render 在 v24 侧）；`ptc-runtime/README.md:45`（Python backend experimental/private）；`subagent/subagent-dsh-sdk/README.md:95`（JSON-RPC 是序列化边界） | line-JSON 一调用一进程，`prepare/invoke/release/inspect` 四操作（`line_json.py:1-30`），无 streaming、无 cancel、无跨调用状态 | **ADAPT** | 分离 **definition**（语言中立描述符）与 **transport**（line-JSON one-shot 或 JSON-RPC 长活）；长活进程 per install/episode，带 `cancel` notification |
| 10. compaction 与 fork/resume | `compaction/compaction/src/types.ts:24-82`（`compaction/{start,summary,end}` + surfaceOp replace）；`core/session/src/fork.ts:23-30`；`core/session/src/repair.ts:53-98` | 无 compaction、无 fork、无 session resume；`worker.py:701` 的 "resume" 只是 journal 里 prepared effect 的重放 | **ADAPT**（compaction）/ **REJECT**（surface 机制） | compaction 写成 `command_compact` effect + `surface/replace` event + 摘要 receipt，准入时校验"摘要严格小于被替换内容"；fork 暂不做 |

### I2. 逐项分析

#### I2.1 事件溯源 log vs effect ledger：哪些不变量可迁移，第二真相源在哪里

可迁移的是三条不变量，不是介质：

1. **每个模型可见输入在请求发出前已有持久事实。** DSH 在 `step/start` 后按序 append `system/message`、`user/message`（`agent.ts:422-440`），再由 `deriveMessages()` 冻结请求（`agent.ts:688-702`），checkpoint policy 在 adapter 首 chunk 前 flush（`session-checkpoint-policy/src/index.ts:66-74`）。v24 的 `model_call.request` 确实在 claim 前冻结，但只冻结了 `input`/`instruction`/`budget`，没有冻结"本步实际承认了哪几条消息"。
2. **请求是派生的，不是 host 现拼的。** DSH 的 `deriveMessages` 只读 surface（`session/index.ts:984-1005`）。v24 的 `worker.py:944` 读 journal。
3. **失败不伪造历史。** DSH 的 `assistant/attempt` 不产生 surface 消息（`session/types.ts:352-362`）。v24 靠 journal 里 `assistant_message=None` 偶然达到同样效果，没有 DB 规则保证。

不可迁移的是"append 是唯一 mutation"。v24 是行更新 + events 同事务，这没有问题；问题不在介质，而在**没有一条"模型可见 = 已记录"的规则**。

**第二真相源的确切位置**（三处，全部在 host）：

- `worker.py:944` → `_history(run_id)`：模型 transcript 来自 journal 的 `effect_prepared.seed_messages` / `appended_messages`、`dispatch_finished.assistant_message`、`dispatch_finished.tool_message`（`worker.py:1190-1231`）。
- `worker.py:1125-1137` → `_parent_tool_call`：tool effect 与 provider `tool_call_id` 的映射来自 journal 的 `dispatch_finished.assistant_message.tool_calls[ordinal]`；DB 里没有这个 id。
- `worker.py:701` 附近 → `_resume_prepared`：已 prepared 未 dispatch 的 effect 靠 journal 判断是否要重放。

journal 是 fsync + append-only + 单写者（`journal.py:1-15`），并且 deviation ledger 明确写"journal 必须与十表分离"（`docs/reviews/v24-deviation-ledger-2026-10-23.md:417`）。它实际上已经是一套事件日志，只是没有被称为日志。**这是设计级缺口，不是实现 bug**：十表模型里没有地方放 provider call id 和 rendered content，所以 host 只能另存。

#### I2.2 turn/step 边界 vs effect 定义的 turn：v24 失去了什么；能否不建第 11 张表

v24 设计稿 `:269` 把 turn 定义为"一次 effect 执行及唯一 advance"，所以 `model→tool→model` 至少三个 turn。这在内部自洽，但和 `:136` 的"turn_no = 已提交模型步骤数"冲突，实现选了前者（`48_loop.sql:588`、`:1411`）。

v24 因此失去六样东西：

1. **用户轮次不可表达。** 没有"claim 了输入 → 0..n 个 step → 关闭"的事实。reject/空输入这种"开 turn 但不花 step"（DSH `agent.ts:319-329`）无法表示。
2. **turn 级预算/统计不可表达。** `remaining_steps` 是 run 级；按 turn 归属成本需要 group by，而 `turn_no` 是 effect 计数。
3. **turn 级 cancel 不可表达。** v24 `cancel` 直接把 run 置 `cancelled`（`40_interpreters.sql:745-753`）；DSH `cancel` 只 abort 当前 turn，agent 回 idle，inbox 可保留（`agent.ts:175-181`）。"停止这次回答、保留对话"在 v24 里做不到。
4. **steer 天然破坏性。** DSH steer 只是往 next-step 追加（`agent.ts:167-169`），当前 step 正常结束。v24 steer 必须归档所有 ready effect（`40_interpreters.sql:849-857`）并 bump generation（`:916-917`），因为没有一个"step 边界"可以等。
5. **terminal hook 缺失。** DSH 在自然停止且有 next-step 时跑 `agent/turn-stopping`（`agent.ts:361-364`）。v24 没有任何"本 turn 将结束"的串行点。
6. **`turn_no` 语义漂移。** 所有按 `turn_no` 分组的读面（poll、host read、审计）都在按 effect 计数分组。

**能否不建第 11 张表？能，但要先有事实。** DSH 自己的 turn 边界就是投影不是表：`turnBoundaryProjectionDefinition` 折叠 `turn/start|end`、`step/start|end`（`agent-loop/src/index.ts:57-95`）。v24 完全可以照做——`events` 已在同一事务里（设计稿 `:201` 明确拒绝双账本），折叠 run entity 的 turn/step 事件即可。**但投影只能折叠已存在的事实**：v24 现在没有 turn 开、step 开、输入 claim 这三类事实。所以答案是：

- 只要 **effect-turn**：不需要新事实，也不需要投影，`effects` 本身就是。
- 要 **DSH 式 input-turn**：必须先写"输入被 claim"这一条事实（见 I2.3），然后 turn/step 边界可以是纯投影，**零新表**。

#### I2.3 durable inbox vs `pending_steer`：`pending_steer` 表达不了什么

`pending_steer` 是 `runs` 上一列 jsonb（`10_schema.sql:43`），写入形状固定 `{instruction, generation, epoch}`（`40_interpreters.sql:920-923`），消费时"latest wins"（`48_loop.sql:905`、`:1610-1616`）。它表达不了：

- **多消息批次。** 只有一个 `instruction` 字符串，没有数组、没有 message id、没有 per-message 状态。DSH 的 `claim` 一次 drain 全部 `next-step` 再加恰好一个 `next-turn`（`inbox.ts:109-114`），并且每条消息有 `id`、插入位置、`outcome`（`inbox.ts:227-233`）。
- **reject。** `agent/pre-step` 的 `{kind:'reject'}` 是权威决定，claimed batch 已被移除、open turn 不花 step（`agent.ts:271-288`、`:319-322`）。v24 的 steer 是 command：要么立刻 admit 一个 model（`40_interpreters.sql:873-895`），要么因 claimed effect 而 defer；没有"拒绝并关 turn"的第三条路。
- **inject-without-wake。** DSH `inject` = `send(...,'next-step',false)`（`agent.ts:171-173`），durable 但不唤醒 driver，等下一次 wake 一起被 claim。v24 的 steer 一定 bump `epoch_no` 和 `driving_generation`（`:916-917`），一定改对话代次；没有"静默追加、下次再唤醒"。
- **ordering / 不丢失。** 这是最严重的：**两次 steer 在同一个 claimed model 期间到达时，第一条会被覆盖，但它的 command receipt 已经 `committed`**（`40_interpreters.sql:920-923` 直接覆盖 `pending_steer`）。也就是说 v24 可以对一条 steer 回成功，然后永远不投递它。DSH 的 inbox 不会：插入与 claim 都是 durable splice，被取消的消息也会写 `outcome:'canceled'`（`inbox.ts:226-237`）。

另外两点不对称：

- v24 `cancel` 把 `pending_steer` 清空（`40_interpreters.sql:748`），同样不写"这条 steer 被丢弃"的事实；DSH 清 inbox 时对每条消息发 `agent/inbox/discarded`（`inbox.ts:236-238`）。
- v24 `steer` 会取消所有 ready effect（`40_interpreters.sql:849-857`），DSH steer 不取消任何东西。

**裁决：ADOPT 语义，ADAPT 表示。** 最小实现是把 pending 输入做成 run entity 上的 `input/queued`、`input/claimed`、`input/cancelled` 事件，由一个投影折叠出 pending 列表；claim 与 `model_call` successor 在同一个 advance 里提交，输入批次冻进 `model_call.request.input`。这样：不建表、不建第二队列、不建第二 claim——eligibility 仍然只在 `effects`；inbox 只是"尚未成为 effect 的输入"，不执行任何东西，重启后从 events 重建。

#### I2.4 cancel：协作式 AbortController + synthetic tool errors vs `cancel_requested`/no-replay/unknown

v24 的现状（`40_interpreters.sql:757-786`）：

- ready 的 model/tool effect → `cancelled`，`settled_at=now()`，**`outcome=NULL`**。
- claimed 的 → `cancel_requested=true`，fence 不变。
- run → `cancelled`，`driving_generation+1`，pin 按 blocker 集合释放。
- 迟到的 success/failure/unknown 仍可结算事实与成本，但 `v_late` 使其不发布 successor（`48_loop.sql:1479-1481`、`:1499`）。

这三条**作为事实合同是对的**，和 DSH 的 `turn/end{aborted}` + late attempt 语义同构。缺的是投递与收尾：

1. **没有投递。** host 在 `run_process`/HTTP 里阻塞，从不查 `cancel_requested`（`v24/host/worker.py` 全文无该字段）。所以"in-flight 工具取消"目前完全不存在；cancel 只阻止后续。
2. **ready→cancelled 没有回执。** 一个已经发给模型、但从未执行的 tool call，在 DB 里是 terminal 且 `outcome=NULL`。一旦将来做 DB 派生 transcript，这就是一个永远配不上 `tool/result` 的 dangling call——正是 DSH 用 synthetic result 填的坑（`tool-calls.ts:249-260`；崩溃路径 `repair.ts:166-194`，错误码 `TOOL_NOT_STARTED`/`TOOL_OUTCOME_UNKNOWN`）。
3. **cancel 是 run 级不是 turn 级**（见 I2.2 第 3 点）。

**v24 应采纳的 in-flight 取消**（最小、不建第二状态机）：

- host 侧：把 `cancel_requested` 作为 IO 边界的检查点——每读取一块 stdout/stderr、每次 socket read 前后查一次 DB（或 LISTEN 一个可丢通知），命中则杀进程组并按 `unknown{reason:'cancelled'}` 或 `failure{code:'aborted'}` 结算。DSH 的契约是"tool 必须转发 `exec.signal`，且只在自有工作静默后 settle"（`tools/index.ts:229-237`、`:261-266`），v24 应把它写进插件 ABI，而不是只写在文档里。
- 内核侧：**不要**给 `cancelled` 写 outcome（`10_schema.sql:103` 的 `c_effects_outcome` 要求 `cancelled` 的 outcome 为 NULL）。ready→`cancelled` 的 tool 由 K1 的 `derive_model_messages` 解释为 synthetic `TOOL_NOT_STARTED`/`cancelled_before_dispatch`；这只是派生，不是新状态。
- 明确不做：cancel 队列、cancel 状态机、为 cancel 单独建表。`cancel_requested` + `driving_generation` 已经够。

#### I2.5 `assistant/attempt` vs receipt/unknown

DSH 的 attempt 是**log-only 的 settlement**：一次失败/重试/取消的 model 请求写 `assistant/attempt`，带完整 timed stream，但不进 surface、不进模型历史（`session/types.ts:352-362`；`agent-loop/src/index.ts` 的 turnBoundary 之外，`deriveMessages` 只处理 surface 事件）。重试发生在同一个 step 内（`agent.ts:509-527` 的 `agent/request-error` waterfall 返回 `retry`），所以一个 step 可以有多条 attempt。

v24 的 receipt 身份是 `effect_id` + outcome digest，一个 effect 一个最终 outcome（设计稿 `:70`、`:112`、`:564`）。因此：

- **一个 attempt = 一个 model_call effect** → 兼容。每次重试插入新的 `model_call`，`request.cause='retry'`、`request.attempt_of=<前一个 effect_id>`，前一个是 `failed` 终态 receipt。模型历史派生规则排除 `failed` effect 即可，不需要新事件类型。
- **一个 effect 内多次 attempt**（复用 `attempt_no`）→ **不兼容**。`attempt_no` 会变，但 `outcome` 只有一个；失败 attempt 的 stream/usage 只能塞进 `events` 或新列，那就出现了第二个记录"模型做过什么"的地方。

所以答案是：**attempt 作为投影规则是兼容的，作为新事件类型是不兼容的。** v24 现在没有 retry，所以最诚实的做法是**先不发明 attempt**：`failed` 的 model effect 本身就是 attempt，只要写死"failed/superseded model effect 不产生模型消息"，就等价于 DSH 的"attempt 不进历史"。等真的加 retry 时，再按"一 attempt 一 effect"落地。

#### I2.6 工具管线：哪些部分对 v24 多语言 ABI 是必需的

DSH 的十段管线（`docs/tool-execution-pipeline.md:9-61`）里，对 v24 **必需**的只有五段，其余是宿主策略：

| 段 | 是否必需 | 理由 |
|---|---|---|
| `tool/call` 执行前落盘 | 必需，**v24 已有** | `tool_call` effect 在 model settlement 的同一 advance 插入，并冻结 `pin_id`/`descriptor_digest`/`batch_digest`（`48_loop.sql:1128-1139`）。effect 行比 DSH 的 log 事件更强。 |
| 按冻结 schema 校验参数 | 必需，**v24 缺**（D2） | 现在只查 `args` 是 object（`:300-307`）。多语言插件不能各自实现一套 JSON Schema 校验，否则同一份 descriptor 在不同语言里语义不同。 |
| canonical output schema | 必需，**v24 缺** | `output` 只要求 object（`:1385-1387`）。没有 output schema，就没有"这个工具的输出形状是合同"这回事，插件升级会静默破坏模型提示。 |
| 独立 render | 必需，**v24 缺** | 模型看到 `canonical_json(output)`（`worker.py:1066-1071`）。JSON 不是好的模型内容：RepoPrompt 的卡片、Pi 的 diff/图片都需要文本+结构化分离。 |
| 结构化错误 `{name,code,reason}` + `isError` | 必需，部分有 | v24 有 `{status:error, output:{code,message}}`，但没有 `reason`（面向用户）与 `code`（面向策略）的分层，也没有"错误不进模型内容"的规则。 |
| `tools/pre-execute` waterfall | 不必需 | 这是宿主策略扩展点，放进 SQL 就是把策略树焊进内核（设计稿 `:30` 明确禁止）。 |
| monotonic guards | 不必需，但要有等价物 | v24 的等价物是 descriptor 的静态声明 + host registry 的五字段匹配（`registry.py:1-20`），比可编程 guard 弱但不会形成第二裁决面。 |
| `tools/post-execute` | 不必需 | 同上；post 改写结果会破坏 receipt 的"第一次结果不可覆盖"。 |
| `projectContent`/`finalizeContent` | 不必需 | 属于 presentation，放 host。 |
| `additionalContexts` | 不必需 | v24 没有"工具向下一请求注入 user 消息"的通道；这是 inbox 的另一种用法，等 I2.3 落地后再说。 |

**给 v24 的 ABI 结论**：必需的是一个**语言中立的 ToolDefinition 描述符**，不是一套 SQL 管线。描述符至少含 `key`、`description`、`parameters`（JSON Schema）、`output.schema`、`render`（id + version + digest）、`approval`、`sandbox`、`replay_policy`、`limits`（timeout/输出字节）。内核只做三件事：冻结描述符 digest 到 pin、在 model settlement 校验 args 与 output schema、把 render 结果存成 receipt 的一部分。其余全部在 host/插件侧。

#### I2.7 approval/sandbox：不变成第二状态机的最小机制

DSH 的做法是三层：`tools/pre-execute` 可 `ask` → `ctx.approval.request()`（无 answerer 即 deny，`tools/index.ts:1739-1772`）→ 通过后仍要过 monotonic guards（只能 deny，`:725-738`）；sandbox 是 `ctx.sandboxPolicy` 解析 + `ctx.sandbox.confine(argv, policy, signal)`（`sandbox-local/src/index.ts:325`），escalation 是严格放宽阶梯（`sandbox/escalation.ts:30-56`）。

v24 现在两层都没有：只有 DB role ACL（`50_permissions.sql`）和 registry 固定 argv/cwd/env（`registry.py:1-20`）。**不要**把 approval 做成内核 waiting 状态——那会引入 `waiting_for_approval` + 一个 pending 表 + 一套超时/撤销，正是"第二状态机"。

最小机制（三层，全在既有结构内）：

1. **声明**：descriptor 增 `approval: 'never'|'once'|'always'` 与 `sandbox: {mode, required}`，随 descriptor digest 冻结到 pin。
2. **执行前拦截**：host 在创建进程前读 descriptor；若 `approval != 'never'` 且 run 没有对应 grant，**不执行**，直接按普通 `failure` 结算，`code='approval_required'`（或 `sandbox_denied`）。这不需要新状态：tool effect 仍然 `ready→claimed→failed`，只是失败原因是策略。
3. **grant**：`start` 的 `p_budget`/policy 里带 `grants: {key: {...}}`，落在 `runs` 的一个 jsonb 列（十表内加列，不是加表）。想更细就再发一个 `command_grant`，只写该列；仍然是一个 effect、一个 receipt。

如果一定要**交互式** per-call approval，唯一不新增状态机的路径是复用 `runs.interaction` + `respond`：把 `interaction_id = source_model_effect_id` 放宽为 `interaction_id = source_effect_id`（设计稿 `:259`），tool effect 也能成为 interaction 的 origin。代价是 `respond` 的授权与 generation 规则要重写一遍，而且 claimed tool effect 在等待期间必须回到 ready（当前只有 `command_recover` 会做 reset，`49_recovery.sql:380-384`），这会**新开一条 unclaim 路径**。所以：v24 应该先做 1–3，交互式 approval 留到有真实需求时再评估。

#### I2.8 工具输出：v24 应该标准化什么

DSH：`output.schema` 强制每个成功值都是 lossless JSON（任意 JSON 值，不限于 object），`render(args,value)->ContentBlock[]` 是纯函数，`presentationMeta` 另存，registry 不做 byte cap（`tools/index.ts:214-221`、`:653-660`），只有外层 `run_code` 有 64 MiB 的 overflow 错误（`ptc-runtime-node/src/config.ts:35`、`bootstrap.ts:191-192`），spill 按 token 预算把大结果换成引用（`spill-policy/src/index.ts:48`）。

v24：`output` 必须 object（`48_loop.sql:1385-1387`）；模型看 `canonical_json(output)`（`worker.py:1066-1071`）；stdout 单行 64 KiB（`line_json.py:1-30`、`process_io.py:19`）；结果 inline 在 `effects.outcome` jsonb 里，没有 spill。

**应标准化为四件事**：

1. `output` 允许任意 JSON 值（数组/字符串/数字/null），由 `output.schema` 约束；object-only 是 Pi/RepoPrompt 迁移的第一道墙。
2. receipt 里存 **rendered content**（text/image block 数组）+ 可选 `meta`，而不是只存原始 `output`。这是让 DB 能派生模型历史的先决条件（I2.1），也是"UI 卡片可重放"的唯一办法。
3. render 的身份（id + version + digest）进 descriptor digest；render 在 host 执行，结果由 advance 接收。render 抛错 = 结构性 `invalid_outcome`，不是"静默回退到 JSON"。
4. 内容超限用 **spill ref**（`{kind:'spill', ref, bytes, count}`）替换，不用 64 KiB 截断；64 KiB 只能作为 transport frame 上限并显式报 `output_too_large`，不能静默切。

#### I2.9 多运行时：v24 正确的多语言插件 ABI

DSH 的关键设计不是"支持了几种运行时"，而是**把 definition 和 transport 分开**：MCP 客户端把远端工具包装成 `ToolDefinition`，`render` 写在 v24 侧（`mcp-client/src/tools.ts:250-268`）；PTC 的 `run_code` 是一个普通工具，内部再 dispatch 到同一 registry；subagent 是另一个 provider 注册表（`subagent/subagent/src/index.ts:1-40`），JSON-RPC 只是序列化边界（`subagent-dsh-sdk/README.md:95`）。所以所有工具共享同一套 pre/guard/post/output 合同，运行时差异被收敛在 provider 里。

v24 的 line-JSON 是**wire 协议**，不是 ABI：`prepare|invoke|release|inspect` 四操作、一次调用一个进程、stdout 单行（`line_json.py:1-30`）。它能表达"调用一个函数"，不能表达"一个有状态的工具会话"（RepoPrompt 的 workspace/context builder、Pi 的 LSP/终端会话），也不能表达 streaming 和取消。

**正确 ABI 分两层**：

- **Definition 层（语言中立，进 DB）**：上面 I2.6 的 `ToolDescriptor v2`，JSON 编码，digest 冻结在 pin 上。任何语言只要能输出这份 JSON 并实现 `invoke`，就是一等公民。
- **Transport 层（可替换，不进 DB）**：
  - `one-shot line-JSON`：保留给无状态、短、纯函数工具（现有 `line_json.py` 即可）。
  - `persistent JSON-RPC over stdio`：per install/episode 一个长活子进程，方法 `describe/invoke/cancel`，`invoke` 带 `call_id` 并允许 `notify` 流式 chunk。这才是 RepoPrompt/Pi 的落点。
  - `MCP`：作为**一个 provider**（把 MCP server 的工具转成 `ToolDescriptor`），不是 ABI 本身。用户明确不要 MCP，所以它只能是可选适配器。

**明确拒绝**：为每种语言生成 typed SDK（DSH 的 PTC 做法）。那是客户端便利，不是 ABI；它把"语言支持"变成"代码生成器支持"，对从零实现工具没有帮助。v24 要的是"任何语言输出一份 descriptor + 实现三个 RPC 方法"。

#### I2.10 compaction 与 fork/resume：借什么、不借什么

DSH 的 compaction 是完全 durable 的：`compaction/start|summary|end` 三个 log-only 事件，`summary` 必须严格小于被替换内容，真正的替换是紧跟其后的一条带 `surfaceOp:{op:'replace'}` 的 `user/message`（`compaction/compaction/src/types.ts:24-82`；`compaction/compaction-basic/src/region.ts:418-421`）。fork 是"精确前缀 + `session/end-seed{inherited:true}` + `openTurnClosers({kind:'forked'})`"（`core/session/src/fork.ts:23-30`），closer 会为未闭合的 tool call 补 synthetic result（`repair.ts:53-98`）。

**应借**：

- compaction 是**事实**，不是内存优化：一个 `command_compact` effect，同事务写 `compaction` 事件、摘要 receipt、以及一条"替换范围"事实；准入时校验"摘要字节 < 被替换范围字节"。
- fork/resume 的**切割事实**：如果将来做 fork，必须先有一条"从 seq/effect N 切分"的不可变事实，再补 synthetic closers。不能直接复制行。

**不能借**：

- surface node / position seq / `contentGeneration` / projection cache。v24 没有 surface，引入它就是引入第二真相源（DSH 的 surface 是从 log 派生的，v24 的等价物应该是 SQL 视图/函数）。
- 在 compaction 里改写 `effects.outcome`。DSH 从不改历史事件；v24 也不能覆盖 receipt（设计稿 `:564`）。compaction 只能"遮蔽"（写替换事件），不能删。
- 现在就做 fork。前提是 I2.1 的 DB 派生 transcript 先成立；否则 fork 出来的 run 没有可信历史，只能靠复制 journal，那是把第二真相源也复制一份。

### I3. 直接回答：一个想迁移 Pi 与 RepoPrompt 工具的 v24，自己缺什么

按"改设计 / 改宿主 / 改规格"分级。**K = kernel-level（设计修订），H = host-level，S = spec-level（措辞/闭集/合同）。**

#### K. 内核级缺口（必须先改设计，否则工具迁移只能堆在 host 里）

| ID | 缺口 | 证据 | 最小修法 |
|---|---|---|---|
| **K1** | **没有"模型可见 = 已记录"规则，也没有 DB 派生 transcript 的函数。** 十表里没有 provider call id、assistant 原文、tool rendered content 的位置 | `worker.py:944`、`:1125-1137`、`:1190-1231`；`48_loop.sql:1134-1138`；`journal.py:1-15` | 加 `v24.derive_model_messages(run_id)`（STABLE 只读）；在 `tool_call.request` 增 `provider_call_id`，在 model/tool `outcome` 增 `content`/`meta`；host journal 只保留 IO receipt 与 reservation，不再参与历史重建 |
| **K2** | **没有 step 事实，`turn_no` 语义错误**；无法表达"claim 输入但零 step"、turn 级 cancel/hook | `48_loop.sql:588`、`:1411`；`10_schema.sql:43-58`；设计稿 `:136` vs `:269` | `effects.request.step_no`（同一 model 的 tool 共享）；turn 开/闭用 run entity events；`turn_no` 改名为 `effect_no` 或明确"effect-defined turn" |
| **K3** | **没有 durable 输入准入**；`pending_steer` 单槽、latest-wins、可静默丢输入 | `10_schema.sql:43`；`40_interpreters.sql:920-923`；`48_loop.sql:905`、`:1610-1616` | `input/{queued,claimed,cancelled}` 事件 + 投影；claim 与 `model_call` 同一 advance；一批多消息；reject 只关 turn 不建 model |
| **K4** | **工具 ABI 只有 wire，没有 definition**：无 parameters/output schema 执行、无 render、无 approval/sandbox/replay 声明、descriptor 不透明 | `48_loop.sql:300-307`、`:1133`、`:1385-1387`；`10_schema.sql:190`；`line_json.py:1-30` | `ToolDescriptor v2` + 在 model settlement 校验 args/output schema + render 结果入 receipt + `replay_policy` 由 descriptor 决定 |
| **K5** | **取消不能到达 in-flight 工具**；ready→`cancelled` 无回执（dangling call） | `40_interpreters.sql:757-766`；`worker.py` 无 `cancel_requested` | host IO 循环响应取消并杀进程组；ready→`cancelled` 的 outcome 保持 NULL，由 K1 派生层生成 synthetic `cancelled_before_dispatch` |
| **K6** | **compaction/fork/resume 全缺**；`worker.py` 的 "resume" 只是 journal 重放 | `worker.py:701`；设计稿无 compaction/fork 章节 | 等 K1/K2 完成后，compaction 作为 command effect + 替换事件；fork 暂不做 |

#### H. 宿主级缺口（不改内核也能做，但不做就迁不动 Pi/RepoPrompt）

| ID | 缺口 | 证据 | 最小修法 |
|---|---|---|---|
| **H1** | 一调用一进程、无状态、无 streaming、无 cancel、5 s 默认超时 | `line_json.py:1-30`；`registry.py:30-32` | 长活 JSON-RPC per install/episode；`invoke` 带 `call_id`；`cancel` notification；one-shot 保留给纯函数工具 |
| **H2** | host journal 承担了 transcript 与 provider id 两个职责，却没有被声明为权威 | `worker.py:1125-1137`、`:1190-1231` | 要么在 K1 落地后删掉这两个用途，要么在规格里显式承认它是第二 store（不推荐） |
| **H3** | 没有 approval/sandbox/redaction/输出裁剪的策略链 | `registry.py:1-20`；`50_permissions.sql` 只有 role ACL | 进程创建前的 host policy 链：descriptor → approval → sandbox → argv 冻结；决策写进 receipt |
| **H4** | 没有 renderer；模型看原始 JSON | `worker.py:1066-1071` | 按 descriptor 的 render 生成 content blocks；RepoPrompt 卡片走 `meta` |
| **H5** | 只读工具也被标 `no_replay`，崩溃即 `blocked_unknown` | `48_loop.sql:1133`；`49_recovery.sql:369-375` | descriptor 声明 `replay_safe`；只有声明过的 kind 才允许 reset_ready |

#### S. 规格级缺口（措辞/闭集/合同，不改就会在实现里继续分叉）

| ID | 缺口 | 证据 | 最小修法 |
|---|---|---|---|
| **S1** | `turn_no` = "已提交模型步骤数" 与 §5.1 的 effect-turn 定义冲突，实现选后者 | 设计稿 `:136`、`:269`；`48_loop.sql:588`、`:1411` | 二者取一，改措辞；若保留 effect-turn，删掉"模型步骤数" |
| **S2** | "参数只按冻结 JSON schema 校验" 没有实现 | 设计稿 `:273`；`48_loop.sql:300-307` | 要么实现，要么降级为"host 校验"并写进 ABI |
| **S3** | 允许工具 `replay_safe`，实现硬编码 `no_replay` | 设计稿 `:576`；`48_loop.sql:1133` | 与 S2 同样处理：descriptor 决定，或删掉这段 |
| **S4** | `interaction_id = source_model_effect_id` 堵死了"tool approval 复用 interaction" | 设计稿 `:259`；`48_loop.sql:1035-1040` | 若要交互式 approval，放宽为 `source_effect_id`；否则明确"approval 不是 interaction" |
| **S5** | 错误码闭集（24 个）没有 `approval_required`、`sandbox_denied`、`tool_output_invalid`、`cancelled_before_dispatch` | 设计稿 `:554`、`:762-770` | 扩闭集需一次 spec revision + G1-A 矩阵同步；或把这些放进 tool result 的 `output.code`，不进顶层错误码 |
| **S6** | 没有规定"tool result 的模型可见形状"，只规定了 `output` 是 object | `48_loop.sql:1385-1387`；`worker.py:1066-1071` | 明确 `content`（rendered）+ `output`（canonical）+ `meta`（presentation）三元组，以及各自是否进模型历史 |
| **S7** | `effects.outcome` 同时承担 receipt 与（隐含的）模型输入来源，但规格没写后者 | 设计稿 `:112`、`:564`；`48_loop.sql:1729-1730`（effect outcome 写回） | 明确 outcome 是 receipt，不是 transcript；transcript 由 K1 的派生函数从 receipt + content 生成 |

### I4. 明确拒绝（会制造第二 claim/queue/recovery 或第二真相源）

1. **新建 `messages` / `turns` / `inbox` / `attempts` 表。** 违反设计稿 `:120`、`:201`、`:203` 的十表约束；而且这些表会立刻变成"哪个才是模型看到的"的第二真相源。用 events 投影 + receipt 字段。
2. **把 DSH 的 append-only log 搬进来做双账本。** v24 旧稿的双账本已被 §1.3/§3.3 否决；DSH 自己也证明代价（compaction 三个事件 + surface generation + projection cache）。v24 已经有 events 在同一事务里，够了。
3. **把 MCP 当插件 ABI。** 用户目标是从零实现工具；MCP 只能是一个 provider。把 MCP 当 ABI 会把"工具定义"外包给协议，永远做不出 RepoPrompt 的卡片和 Pi 的 diff。
4. **DB 侧 approval 状态机**（`waiting_for_approval` + pending 表 + 超时）。见 I2.7：用 run 级 grant + host 拦截 + 普通 failure receipt。
5. **把 `tools/pre-execute`/`post-execute` waterfall 写进 SQL。** 设计稿 `:30` 明确禁止把策略树焊进 advance；这些是 host 扩展点。
6. **为 v24 发明 `assistant/attempt` 事件类型。** receipt 身份会分裂；要么"一 attempt 一 effect"，要么不做。
7. **生成式 typed SDK（PTC 风格）作为多语言方案。** 它把语言支持变成代码生成器支持，和"从零实现工具"的目标正交。
8. **在 K1 之前做 fork/resume。** 复制 journal 只是把第二真相源复制一份。

### I5. 最小改动序列（建议）

1. **先定权威（K1 + S7）**：写 `derive_model_messages(run)` 的规格与只读实现；把 `provider_call_id`、`content`、`meta` 放进 effect request/outcome；把 `worker.py` 的 `_history`/`_parent_tool_call` 改成"读 DB，journal 只做 IO receipt 校验"。这一步做完，D4 消失。
2. **再定边界（K2 + K3 + S1）**：`step_no` + `input/*` events + 投影；`turn_no` 措辞修正；claim 与 model_call 同 advance。这一步做完，reject/inject/ordering/多消息全部可用，且零新表。
3. **再定 ABI（K4 + K5 + S2/S3/S5/S6）**：`ToolDescriptor v2`（parameters/output/render/approval/sandbox/replay/limits）+ 参数与输出 schema 执行 + cancel 由 host 投递、派生层补 synthetic result（不写 outcome）+ `replay_policy` 由 descriptor 决定。
4. **再定宿主（H1–H5）**：长活 JSON-RPC、policy 链、renderer、只读工具 replay_safe。
5. **最后才谈 compaction/fork（K6 + I2.10）**：在 1–4 完成后，compaction 作为 command effect + 替换事件；fork 作为"切割事实 + synthetic closers"。

一句话总结：**v24 缺的不是工具，也不是插件运行时；它缺的是"模型看到过什么"这一层事实。** 在这一层补上之前，任何 Pi/RepoPrompt 工具的迁移都会把更多真相推进 host journal，multilingual plugin 只会变成 multilingual journal。

## Oracle Reconciliation

两个 oracle lane 都完成：Lane 1 `gpt-6.1-sol-xhigh`（chat `new-chat-A76198`），Lane 2 `kimi-code-plan-cn/k3.1-pro`（chat `new-chat-oracle-2-AEA9BC`）。按证据逐项裁决（每条只给一个 disposition）：

| # | 材料主张 | 来源 lane | 复核证据 | 处置 |
|---|---|---|---|---|
| O1 | host journal 已承担 transcript 与 provider call id，是语义权威；这是设计级缺口 | 1, 2 | `worker.py:944`、`:1125-1137`、`:1190-1231`；`journal.py:1-15` | **accepted**（更准确的说法是“权威边界欠规格”，不是违反十表） |
| O2 | DB 已存 model text/tool_calls/tool output/usage；缺 provider call id、rendered content、派生规则 | 1, 2 | `48_loop.sql:281-320`、`:1385-1405`；`48_loop.sql:1134-1138` | **accepted** |
| O3 | K1（模型可见事实派生）是 P0 | 1, 2 | `worker.py:1190-1231`；无 `derive_model_messages` | **accepted** |
| O4 | K4（ToolDescriptor v2）是 P0，必须先于 Pi/RepoPrompt 工具迁移 | 1, 2 | `48_loop.sql:300-307`、`:1133`、`:1385-1387`；`10_schema.sql:190` | **accepted** |
| O5 | K5 的“为 ready→cancelled 的工具写 synthetic failure receipt” | 1 | `10_schema.sql:103`：`cancelled` 必须 `outcome IS NULL` | **rejected**（会违反 `c_effects_outcome`；改用派生 synthetic result，不写 outcome） |
| O6 | host 必须观察 `cancel_requested` 并在 IO 边界杀进程组，静默后才 settle | 1, 2 | `40_interpreters.sql:757-766`；`worker.py` 无 `cancel_requested` | **accepted** |
| O7 | K3（durable input inbox）是工具迁移的前置 | 1（P1 conditional）, 2（not prerequisite） | `10_schema.sql:43`；`40_interpreters.sql:920-923` | **accepted as conditional**：不是工具 ABI 的前置；只有需要 per-message 语义时才做 |
| O8 | K2（step/turn facts）是内核 blocker | 1（P2/spec）, 2（not required） | `48_loop.sql:588`、`:1411`；设计稿 `:136` vs `:269` | **rejected as blocker**：只需修 `turn_no` 措辞；DSH 式 input-turn 后置 |
| O9 | K6（compaction/fork）可以后置 | 1, 2 | 设计稿无 compaction/fork；`worker.py:701` 只是 journal 重放 | **accepted**（defer） |
| O10 | `pending_steer` latest-wins 是规格明文；只有把它当“逐条消息投递”时才是缺陷 | 1, 2 | `40_interpreters.sql:920-923`；`48_loop.sql:905`、`:1610-1616`；G2b-P | **accepted**：现有实现符合规格；批评只在 per-message 契约下成立 |
| O11 | DSH inbox 买到多消息、reject、inject-without-wake、per-message discard | 1, 2 | `inbox.ts:109-114`、`:226-237`；`agent.ts:154-173`、`:271-322` | **accepted**（但非工具 ABI 前置） |
| O12 | 工具 ABI 必须把 definition 与 transport 分开 | 1, 2 | `line_json.py:1-30`；`registry.py`；DSH `mcp-client/src/tools.ts:250-268` | **accepted** |
| O13 | render 应是 host-owned renderer identity，不是存进 SQL 的任意回调 | 1, 2 | `worker.py:1066-1071`；`48_loop.sql:1385-1387` | **accepted** |
| O14 | PTC typed SDK 或 MCP 作为多语言 ABI | 1, 2 | PTC 只是 provider；MCP 是 provider | **rejected** |
| O15 | 把 DSH event-sourced log 作为第二账本搬入 | 1, 2 | 设计稿 `:201`、`:203`；十表约束 | **rejected** |
| O16 | 完整 DSH turn/step lifecycle + surface | 1, 2 | `agent-loop/src/index.ts:57-95` 是投影 | **rejected/deferred**：只借投影思路，不建 surface |
| O17 | DB 侧 approval waiting 状态机 | 1, 2 | `48_loop.sql:1035-1040` interaction 只由 model 产生 | **rejected**：用 run-level grant + host 拦截 + 普通 failure |
| O18 | v24 是 effect kernel，不是完整 harness | 1, 2 | `30_advance.sql`；`worker.py`；十表 | **accepted** |
| O19 | provider call id：存进 effect，还是由 `(parent_effect_id, ordinal)` 确定性派生 | 1（存）, 2（可派生） | `48_loop.sql:1134-1138`；`deepseek.py:526-527` | **unresolved**（两种都可；需在 ABI 设计时定） |
| O20 | 持久 JSON-RPC 对 stateful 工具是否必需 | 1（one-shot 够用）, 2（H1 必需） | `line_json.py:1-30`；RepoPrompt/Pi 的 stateful 工具需求 | **accepted as conditional**：one-shot 给纯函数工具，persistent 给 stateful/streaming/cancel |

**净结论：**

1. K1/K4 是 P0；K1 用“补现有 effect receipt + 只读派生”解决，不建 messages/turns 表。
2. K5 拆成 host 投递（观察 `cancel_requested`、杀进程组）与派生 synthetic result（`cancelled` + `outcome=NULL` 解释为 `cancelled_before_dispatch`）；不要给 `cancelled` 写 outcome。
3. K3 是条件项，K2 是文档项，K6 后置；三者都不是 Pi/RepoPrompt 工具 ABI 的前置。
4. 多语言 ABI = 冻结的 ToolDescriptor v2 + 可替换 transport（one-shot line-JSON 或 persistent JSON-RPC），不是 MCP、不是 PTC typed SDK、不是 DSH session log。

## Investigation Log

### Phase 1 - 初始评估
**Hypothesis:** DSH 与 v24 解决的是同一个“durable agent runtime”问题的两种介质：DSH 以事件/会话日志为中心，v24 以 Postgres effect/advance 为中心。可比较的维度是 loop 边界、事实权威、恢复、工具/插件、控制面。
**Findings:** 先读 DSH 的 `docs/agent-lifecycle.md`、`docs/architecture.md`、`packages/core/{agent-loop,session,agent,tools}`、`packages/session/**`、`packages/llm/**`；再对照 v24 的 `docs/designs/v24-pg-agent-2026-10-22.md`、`v24/sql/30_advance.sql`、`v24/sql/48_loop.sql`、`v24/host/*`。
**Evidence:** 初始假设被后续 explore 修正：DSH 的权威不是“执行资格”，而是“模型可见事实”；v24 的权威是“执行资格与回执”。两者不是同一权威的两种介质。
**Conclusion:** 需要把“模型可见事实”作为独立比较维度。

### Phase 1.5 - 外部事实（4 个 explore）
**Hypothesis:** DSH 的 loop/session、lifecycle、tool/plugin、以及 pg-agent 既有 DSH 结论，可以分四路独立核实。
**Findings:**
- Explore A（`C90D549B…`）：DSH 是 turn > step、append-only `SessionEvent`、surface/deriveMessages、persistence flush barrier、resume/fork 用 synthetic closers。
- Explore B（`22063AC0…`）：Agent 动词是 `send/followup/steer/inject/cancel/whenIdle/runMaintenance`；inbox splice/claim；cancel 是 AbortController；状态只有 idle/running；crash recovery 无 lease/fence。
- Explore C（`C9AD39CE…`）：`ToolDefinition` = `{name,description,parameters,output.schema,execute}`；执行管线 pre/guard/execute/post/result；approval + sandbox；多运行时靠 PTC/MCP/subagent provider。
- Explore D（`DB226DC1…`）：pg-agent 的 v8 pinned-host 从未实现，五件套全 null；已有警告“pinned compat 是参考实现，不是真理来源”。
**Evidence:** 写入 `## Background / Prior Research` B1–B4，含 file:line。
**Conclusion:** 四路事实足够进入上下文构建；没有发现 DSH 已被 v24 正式吸收的记录。

### Phase 2 - 上下文构建
**Hypothesis:** v24 侧的权威边界、tool effect、descriptor/pin、host journal 是核心证据面。
**Findings:** `context_builder` 选了 31 个文件（DSH docs/core/session/tools + v24 design/sql/host/s11），并给出第一版评估：DSH 是 event-sourced session，v24 是 effect ledger；关键差异是“model-visible facts”与“execution eligibility”。
**Evidence:** 选择集 131,560 tokens；后续手工加入 `tool-calls.ts`、`repair.ts`、`session-checkpoint-policy`、`v24/49_recovery.sql`、`v24/host/journal.py` 及关键 slice。
**Conclusion:** 需要 pair 做主线对照，oracle 做裁决。

### Phase 3 - Pair 主线调查
**Hypothesis:** v24 的 host journal 已经承担 transcript，构成第二真相源；ToolDescriptor 缺 definition 是多语言工具的前置缺口。
**Findings:** pair 写入 `## Investigator Findings`，给出 I0 四处 documented≠implemented、I1 十条 adoption matrix、I2 逐项分析、I3 K/H/S 分级、I4 拒绝清单、I5 最小序列。核心裁决：K1/K4 是内核级前置；K2/K3/K5/K6 需要分层。
**Evidence:** `worker.py:944/1125-1137/1190-1231`；`48_loop.sql:300-307/1133/1385-1405`；`10_schema.sql:103`；`40_interpreters.sql:757-766/920-923`；`49_recovery.sql:369-375`。
**Conclusion:** 方向成立，但 K5 的 synthetic receipt 写法需要修正；K3 的“静默丢输入”需要区分规格 latest-wins 与实现 bug。

### Phase 4 - Oracle 两 lane 与复核
**Hypothesis:** 两个独立 oracle 能检验 pair 的过度断言，并给出优先级。
**Findings:** 两个 lane 都完成（`new-chat-A76198` / `new-chat-oracle-2-AEA9BC`）。共识：D4 是权威边界欠规格；K1/K4 P0；K5 是 host 投递 + 派生收尾；K3 条件项；K2 文档项；K6 后置；不要把 DSH session log/surface/PTC/MCP 整体搬入。分歧：Lane 1 主张 K5 写 synthetic failure receipt；Lane 2 指出 `c_effects_outcome` 禁止 `cancelled` 带 outcome。复核确认 Lane 2 正确。
**Evidence:** `10_schema.sql:103`；`40_interpreters.sql:757-766`；`48_loop.sql:588/1411`；`docs/designs/v24-pg-agent-2026-10-22.md:136/269/576`。
**Conclusion:** 采纳 Lane 2 的 K5 修正；其余按 `## Oracle Reconciliation` 表处置。

### Phase 5 - 最终证据复核
**Hypothesis:** 报告中的承重句必须能在源码里逐行对上。
**Findings:**
- `turn_no` 在 model settlement 与 tool settlement 各 +1（`48_loop.sql:588`、`:1411`，写回 `:1255`、`:1716`），文档 `:136` 的“模型步骤数”不成立。
- `tool_calls` 只校验 `{key,args}` 形状（`48_loop.sql:300-307`）；`slots.descriptor` 不透明（`10_schema.sql:190`）。
- tool successor 硬编码 `no_replay`（`48_loop.sql:1133`）；`cancelled` 必须 `outcome IS NULL`（`10_schema.sql:103`）。
- `pending_steer` 是单槽、latest-wins（`40_interpreters.sql:920-923`；`48_loop.sql:905`、`:1610-1616`）；G2b-P 明确测试 latest-wins。
- host 全文无 `cancel_requested`；`_history`/`_parent_tool_call` 读 journal（`worker.py:944`、`:1125-1137`、`:1190-1231`）。
**Evidence:** 上述行号均已实读。
**Conclusion:** 报告结论成立；pair 的 K5 synthetic receipt 被替换为“派生 synthetic result + host 投递”；K3 的“静默丢输入”降级为“规格 latest-wins 的可审计性缺口”，不是实现 bug。

## Root Cause

这不是一个实现 bug，而是两个“权威边界”设计缺口，加一组文档/实现漂移。

### RC1. 模型可见事实没有 DB 派生规则（D4）

v24 的规格把 DB 定为“执行资格与回执”的权威，把 host journal 定为 IO 证据（设计稿 `:466`）。这在“只证明调用发生过”时成立；但当前 host 用 journal 重建 **下一条 provider 请求**：

- `worker.py:944` 调 `_history(run_id)`，后者只读 journal 的 `effect_prepared.seed_messages` / `appended_messages` / `dispatch_finished.assistant_message` / `tool_message`（`worker.py:1190-1231`）。
- `worker.py:1125-1137` 从 journal 的 `assistant_message.tool_calls[ordinal]` 取 provider `tool_call_id`。
- journal 是 fsync + append-only + 单写者（`journal.py:1-15`）。

因此 journal 不只是“IO 证据”，它决定了模型下一轮看到什么。DB 的 `effects.request` 只存 `{key,args,descriptor_digest,batch_digest}`（`48_loop.sql:1134-1138`），model outcome 的 `tool_calls` 只有 `{key,args}`（`deepseek.py:526-527`），tool outcome 只有 `{status,output,usage}`（`48_loop.sql:1385-1405`）。删掉 journal，DB 无法重建 provider transcript。**这是“模型可见事实”缺少权威归属，不是十表约束的错。**

### RC2. Tool ABI 只有 wire，没有 definition（D2/D3）

v24 的 `tool_call` effect 已经做到“执行前落盘、pin 冻结 descriptor、receipt 唯一”，这比 DSH 的 log 事件更强。但 descriptor 是不透明 `jsonb`（`10_schema.sql:190`），参数只校验 `args` 是 object（`48_loop.sql:300-307`），输出只校验 `output` 是 object（`:1385-1387`），没有 output schema、render、approval/sandbox/replay/limits 声明。结果是：

- 同一份 descriptor 在不同语言插件里语义可能不同；
- 工具升级会静默改变模型提示；
- 只读工具也被硬编码 `no_replay`（`:1133`），崩溃即 `blocked_unknown`（`49_recovery.sql:369-375`）；
- `line_json.py` 的 `prepare|invoke|release|inspect` 是进程 wire，不是可跨语言实现和验收的 ABI。

### RC3. 文档/实现漂移（S1–S7）

- `turn_no` 文档写“已提交模型步骤数”（设计稿 `:136`），实现按 model/tool 每次 settlement 加一（`48_loop.sql:588`、`:1411`）。实际语义是“已结算 effect 数”。
- 文档写“参数只按冻结 JSON schema 校验”（`:273`），实现没有 schema 执行。
- 文档允许只读工具 `replay_safe`（`:576`），实现硬编码 `no_replay`。
- `interaction_id = source_model_effect_id`（`:259`，`48_loop.sql:1035-1040`），使 tool effect 不能成为 interaction origin。
- 24 个错误码没有 `approval_required`/`sandbox_denied`/`cancelled_before_dispatch`。
- 规格没有规定 tool result 的模型可见形状；模型看到 `canonical_json(output)`（`worker.py:1066-1071`）。

### 不是根因的东西

十表、单 `advance`、effect-defined turn、`no_replay` 工具、unknown wall、取消不谎称停止——这些都是刻意的安全选择，不应为了“像 DSH”而推翻。问题只在：**哪些事实必须由 DB 拥有、哪些可以留在 host**，以及**工具定义是否足以跨语言**。

## Recommendations

### P0-1. K1：补“模型可见事实”的 DB 归属，不建新表

1. **在现有 JSON 字段里补语义回执。**
   - `model_call.outcome` 增一个可选 `assistant` 对象：`{content, reasoning_content, tool_calls:[{provider_id, provider_name, arguments, key, args}]}`。闭集校验（只允许这些 key），由 `advance` 接收。
   - `tool_call.outcome` 的 `output` 采用约定：`{value:<any>, content:[<content blocks>], meta:{...}}`。`output` 仍是 object，不需要改 `c_effects_outcome`；`value` 是 canonical 结果，`content` 是模型可见渲染，`meta` 是 UI/回放数据。
   - 现有 `text`/`tool_calls`/`interaction`/`final`/`usage` 保留为模型语义；`assistant` 只为 transcript 派生服务。
2. **加只读 `v24.derive_model_messages(run_id)`**：按 `(parent_effect_id, ordinal)` 把 model/tool settlement 折叠成 provider messages；`failed`/`superseded` model effect 不产生消息；`cancelled` 且 `outcome IS NULL` 的 ready tool 产生 synthetic `TOOL_NOT_STARTED`/`cancelled_before_dispatch`（只在派生里，不写回）。
3. **host 改读 DB**：`worker.py:_history` 与 `_parent_tool_call` 改为调 `derive_model_messages`；journal 只保留 `effect_prepared`/`dispatch_started`/`dispatch_finished` 的原始 IO 证据与 reservation，不再参与历史重建。
4. **provider call id 的处理**：优先把 raw provider id 存进 `assistant.tool_calls[].provider_id`；同时允许 `(parent_effect_id, ordinal)` 确定性派生作为 fallback。这是 O19 的未决项，实现时二选一，不要两套并存。
5. **验收**：删掉 journal，仅用 DB 跑同一 run 的下一步，provider request 字节必须与有 journal 时一致；崩溃后恢复也必须一致。

### P0-2. K4：ToolDescriptor v2 + 可执行的 schema/limit 合同

descriptor 增字段（全部在现有 `slots.descriptor` JSONB 内，不加列）：

```json
{
  "v": 2,
  "tool": {
    "description": "...",
    "parameters": { "type": "object", "...": "..." },
    "output_schema": { "type": "object", "...": "..." },
    "render": { "id": "rp.tool.read.v1", "version": 1, "digest": "sha256:..." },
    "annotations": {
      "read_only": true,
      "replay_class": "read_only|idempotent|mutating|external",
      "approval": "never|once|always",
      "sandbox": { "mode": "read-only|workspace-write|danger-full-access", "required": true }
    },
    "limits": { "timeout_ms": 30000, "max_output_bytes": 262144 }
  }
}
```

- **DESCRIPTOR digest 冻结在 pin**；host 派发前与 pin 比对（现有 `registry.py:match_pin` 已做，扩到 v2）。
- **参数校验**：在 model settlement 生成 tool effect 前，用 `v24.schema_ok` 的封闭子集（type/required/additionalProperties/enum/min/max）校验；不支持完整 JSON Schema，避免在 PL/pgSQL 里写通用验证器。校验失败按已知 `failure`（`output.code=invalid_tool_arguments`），不是 unknown。
- **输出校验**：在 tool settlement 校验 `output.value` 符合 `output_schema`；失败按 `failure`，保留 receipt。
- **render**：不是 SQL 回调；descriptor 只存 renderer id/version/digest，host 执行，返回 `output.content`；DB 只校验 content 的闭集形状。
- **limits**：timeout 由 host 执行并映射到 lease；`max_output_bytes` 超限返回 `output.code=output_too_large`，不用 64 KiB 静默截断。
- **replay_class**：`read_only` 的 tool effect 可写 `replay_policy='replay_safe'`；`mutating`/`external` 保持 `no_replay`。这需要改 `48_loop.sql` 的 successor 构造与 `49_recovery.sql` 的 recovery 分支，但不加状态机。

### P1-1. K5：取消分两层，不要给 `cancelled` 写 outcome

- **host 投递**：在 dispatch 前、每次有界 IO 等待前后、进程退出时检查 `cancel_requested`；命中则杀进程组，等资源静默后再 settle `unknown` 或 `failure`。`cancel_requested` 不撤销 live claim，符合现有设计。
- **派生收尾**：ready→`cancelled` 且 `outcome IS NULL` 的 tool effect，由 `derive_model_messages` 解释为 synthetic `TOOL_NOT_STARTED`/`cancelled_before_dispatch`。**不要**给 `cancelled` 写 outcome：`10_schema.sql:103` 的 `c_effects_outcome` 明确要求 `cancelled` 的 outcome 为 NULL，pair 的 I2.4 synthetic receipt 写法会违反约束。
- **不做**：cancel 队列、cancel 状态机、为了 cancel 新增表。run 级 cancel 保持不变；“停止本次回答、保留会话”如果要做，属于 K2/K3 的 input-turn 语义，单独设计。

### P1-2. H1/H4：stateful 工具走 persistent transport，render 在 host

- **one-shot line-JSON** 保留给无状态、短、纯函数工具（现有 `line_json.py` 即可）。
- **persistent JSON-RPC over stdio** 用于 workspace context、codemap、LSP、终端等有状态工具：per install/episode 一个长活子进程，方法 `describe/invoke/cancel/release/inspect`，`invoke` 带 `call_id`，允许 `notify` 流式 chunk；最终 settlement 仍只走 `advance`，stream 不是第二结算通道。
- **renderer**：host 按 descriptor 的 render id/version 生成 content blocks；RepoPrompt 卡片走 `meta`，Pi 的 diff/图片走 `content`。

### P2. 条件项/后置项

- **K3（durable input inbox）**：只在需要 per-message steer/inject/reject 时做。用 run entity 的 `input/queued|claimed|cancelled` events + 投影；claim 与 `model_call` 同一 advance；不建 inbox 表、不建第二队列。不做的话，把 `pending_steer` 明文写成“coalescing register”，并在 `steer` 被覆盖时写 `steer_superseded` 事件（可选，仍不加表）。
- **K2（step/turn）**：先修 `turn_no` 文档，改成“已结算 effect 数”或重命名为 `effect_no`；`effects.request.step_no` 与 input-turn 事件等 K3 需求明确后再加。DSH 的 `turnBoundary` 只作为投影思路，不建 surface。
- **K6（compaction/fork）**：等 K1/K4 完成后。compaction 作为 `command_compact` effect + 不可变替换事件；fork 需要先有“切割事实 + synthetic closers”，不要在 K1 之前做。

### 规格修正（S1–S7）

| ID | 修正 |
|---|---|
| S1 | `turn_no` 文档改为“已结算 effect 数”，或重命名；不要同时保留“模型步骤数”措辞 |
| S2 | “参数按冻结 JSON schema 校验”要么实现封闭子集，要么降级为“host 校验 + DB 校验 schema digest”；不能保持现状 |
| S3 | `replay_class` 由 descriptor 决定；只读工具允许 `replay_safe`，其余 `no_replay` |
| S4 | 明确“approval 不是 interaction”；交互式 approval 暂不做，避免 unclaim 路径 |
| S5 | `approval_required`/`sandbox_denied`/`cancelled_before_dispatch`/`output_too_large` 放 `output.code`，不扩 24 个顶层错误码 |
| S6 | 明确 `output.value`（canonical）、`output.content`（模型可见）、`output.meta`（展示）三元组及各自是否进模型历史 |
| S7 | 明确 `effects.outcome` 是 receipt，不是 transcript；transcript 由 K1 的派生函数生成 |

### W1 文档对齐记录（2026-10-29；doc-only resolved）

以下注记只记录文档收口，不改写本调查原有结论或历史建议：

- **S1 — doc-only resolved**：`turn_no` 文案已对齐为已提交业务 settlement 计数；model/tool settlement 各加一，cancel-late 不增。
- **S2 — doc-only resolved**：参数与 tool result 的 descriptor schema 断言已降级为 `{key,args}` 与 `{status,output,usage}` 形状校验；DB/host 不执行 descriptor JSON Schema。
- **S3 — doc-only resolved**：v1 tool successor 已记录为一律 `no_replay`；可被 claim 的 `replay_safe` 恢复闭集收紧为 `host_prepare`/`host_release`/`inspect_resource`，command effect 不进入 claim/recovery。
- **S7 — doc-only resolved**：`effects.outcome` 明确为 receipt；host journal 是 provider transcript 与后续 model 请求的唯一持久对话来源，DB 仅保留语义投影。未实施 `derive_model_messages` 或新增 outcome 字段。

### 明确不做

1. 不建 `messages`/`turns`/`inbox`/`attempts` 表；不把 DSH 的 event-sourced log 作为第二账本。
2. 不把 `tools/pre-execute`/`post-execute` waterfall 写进 SQL；不做 DB 侧 approval waiting 状态。
3. 不把 MCP 或 PTC typed SDK 当多语言 ABI；它们只能是 provider/便利层。
4. 不在 K1 之前做 fork/resume/compaction；不覆盖 `effects.outcome` 的历史 receipt。

## Preventive Measures

1. **“删 journal”回归**：每个 tool/loop gate 增加一个变体，删掉 host journal 后用 DB 派生 transcript，断言 provider request 字节一致。这是防止 D4 复发的唯一硬门。
2. **跨语言 descriptor 向量**：Swift/TS/Go/Python 各自生成同一 descriptor 的 canonical JSON 与 digest，和 Python `pg_jsonb_text` 参考实现逐字节比对；任何语言不一致就拒绝。
3. **documented-vs-implemented 清单**：每个“规格说会校验/会重放/会取消”的句子配一个 gate；没有 gate 的规格句必须在台账标 `documented only`。
4. **模型请求来源规则**：任何进入 provider request 的字段，必须要么由 `derive_model_messages` 从 DB 派生，要么在 effect `request/outcome` 里带 digest 并声明为外部证据；禁止 host 私有变量静默进入。
5. **取消/崩溃对抗**：K1 落地后补“dispatch 前取消”“IO 中取消”“dispatch 后崩溃”三组用例；`cancelled` 的 outcome 必须保持 NULL，派生层负责 synthetic result。
6. **新表禁令**：任何“需要新表”的提案，先证明现有 effects/events + JSON 字段无法表达；证明不了就不加。
