# v13 pi_parity — pg-agent seam 环 vs pi/PiG/PiSwift agent 循环同任务对照

同一个脚本化 agent 任务（读 `hello.txt` 与 `fib.py`，回答两文件要点）在四个运行时各跑一遍，
全程确定性（无真实 LLM），落同一 schema 的归一化 trace，最终产出过程+结果对照报告
（Turn 3，`docs/reviews/v13-pi-agent-parity-*.md`）。

- pg 侧：v13 seam 环（`v13_parse`/`v13_advance`/`v13_claim`/`v13_complete` + pg_typesafe mock 判断），库 `agent_v13_pi_parity`。
- pi / PiG / PiSwift 侧：各自框架的 agent 循环 + 框架自带 scripted/fake provider（Turn 2 接线，探查结论见下文）。

## 任务定义（四侧同构）

1. fixture root 下有两个文件：`hello.txt`（三行问候）、`fib.py`（递归 fib，`fib(10)=55`）。
2. 任务指令：读两个文件，回答两文件要点。
3. 脚本化模型（判断/生成）是**确定性纯函数**，输入为累积上下文的内容（哈希/计数），输出为固定响应：
   - 第 1 轮（尚无工具结果）→ 发出两次 read 工具调用：`hello.txt` 然后 `fib.py`；
   - 第 2 轮（两个工具结果都在场）→ 终答 `final_from_results`：引用两文件内容的 sha256 摘要（前 16 hex）+ 固定要点句。
   - 同内容必得同响应；内容变则摘要变。pg 侧实现见 `test_pi_parity.py` 的 `digest`/`final_from_results`/`overrides_for`，Turn 2 各框架侧按同形移植。

## 归一 trace schema（四侧一致）

JSONL 文件（`traces/<side>.jsonl`），每行一个 JSON 对象：

- 步骤行：`{"runtime": "...", "seq": <int>, "phase": "parse|advance|claim|tool|judge|finish", "tool": <str|null>, "args": {...}, "result_digest": "...", "persisted": "sql|file|memory"}`
- 末行：`{"runtime": "...", "final": "<终答文本>"}`

`result_digest` 为 `sha256:` + 内容 utf-8 sha256 hex 前 16 位。聚合视图（`{"runtime", "steps", "final"}`）即全部步骤行 + 末行。
pg 侧工件：`traces/pg.jsonl`（18 步：每轮 judge→parse→advance→claim→tool，llm 轮，finish；末行 final）。

## gate 语义

`UV_FROZEN=1 uv run python v13/pi_parity/test_pi_parity.py`

- 退出码 0 = 无失败；断言失败退出 1。
- 未接线侧打印诚实 `[SKIP]` 行（绝不伪造 PASS），**不**改变退出码。
  原因：read_tools 的 E4 会扫描全部 `v13/test_*.py` 且零容忍非零退出（单测 600s 超时），
  若顶层用「有跳过则退出 2」语义会击穿零回归检查——跳过信号只存在于打印输出。
- pg 侧断言组（P- 前缀）：guard（不动冻结面）、setup/catalog/budget/override、环行走
  （routes=[tool,tool,llm,finish]、claim 参数序、tool/result 与 effects 内容、终答与终态）、
  trace 文件断言（schema、双 tool 步、摘要与 fixture 实算一致、相位全覆盖、seq 连续）、清理。

## 三框架脚本化驱动探查结论（Turn 1，只读探查）

### pi（TypeScript，`/Users/wxl/Projects/pi`）

- 入口：`packages/agent` 的 harness 运行时——`Lane`（`src/harness/runtime/lane.ts`）+
  `Drive`（`src/harness/runtime/types.ts`）+ `AgentHarness`（`src/harness/agent-harness.ts`）；
  会话存储用 `MemoryStorage`/`StorageBackedSession`（`src/harness/session/`）。
- 注入：`@earendil-works/pi-ai` 导出 `fauxProvider`/`fauxAssistantMessage`/`fauxToolCall`/`createModels`——
  faux provider 伪造流式响应，测试以 per-call 脚本数组喂响应（`FixtureOptions.calls`），
  经 `models.setProvider(faux.provider)` + `LaneConfiguration{model:{provider,modelId}, activeToolNames}` 选模与限工具。
- 粒度：`HarnessEvent[]` 事件流（watch/onEmit 回调）+ 会话 entry（assistant / `ToolResultMessage`）。
- read 工具：harness 自带 `src/harness/tools/read.ts`；`activeToolNames` 可限定工具面。
- 示例：`packages/agent/test/harness/runtime/drive-tools.test.ts:151`（calls→activeToolNames 映射、工具轮驱动）。
- 运行：vitest 套件（仓用 bun）；精确命令 Turn 2 验证（gap）。

### PiG（Go，`/Users/wxl/Projects/PiG`）

- 入口：`agent` 包 `NewAgent(AgentOptions{Model, Tools, EventCh, ToolExecution, FinishTurn})`。
- 注入：`agent/upstream_helpers_test.go` —— `scriptedProvider{respond func(call int, req) *ai.AssistantMessageEventStream}`
  （:27）、`scriptedModel(p) *ai.Model`（:64，Provider 接口在 `ai/types.go:552`）、
  `toolCallsThenText(calls ...ai.ToolCall)`（:75，首轮工具调用、后续文本——正是两轮任务形状）。
- 粒度：`AgentEvent` channel（EventCh）逐事件。
- read 工具：工具经 `Tools []AgentTool` 显式注册（pi_ports pig_port 用 `coding.NewSession` 拿成套工具）。
- 示例：`agent/agent_loop_upstream_test.go:26`（纯文本应答）、`:96`（toolCallsThenText 工具轮）。
- 运行：PiG 根 `go test ./agent -run <TestName>`（gap：具体测试名 Turn 2 定）。

### PiSwift（Swift，`/Users/wxl/Projects/PiSwift`）

- 入口：`createAgentSession(CreateAgentSessionOptions) async -> CreateAgentSessionResult`
  （`Sources/PiSwiftCodingAgent/Core/SDK.swift:504`；Options :31、Result :132）。
- 注入：PiSwiftAI 层有 provider 协议面 + mock provider 测试先例（`Tests/PiSwiftAITests/PiSwiftAITests.swift`）；
  接线到 `createAgentSession` 的注入点 Turn 2 验证（gap）。
- 粒度 / read 工具 / 运行：Turn 2 验证（gap：事件粒度、默认工具面、`swift test --filter` 命令）。
- 本地消费先例：`v13/pi_ports/piswift_port/Package.swift` 以本地路径依赖作者机 checkout。

找不到脚本化路径的情形：本轮未遇到——三家都有 fake/scripted provider 先例；PiSwift 的会话级注入点是唯一未实证环节。

## 轮次规划

- Turn 1（本文件现状）：pg 侧行走通 + trace 落盘 + 三框架探查。
- Turn 2：三框架侧接线（各自 harness + scripted provider 跑同任务）、同形判断函数移植、
  四侧 trace 断言（工具调用序列与文件内容一致、终答非空、工件落盘）。
- Turn 3：对照报告（turn/cycle 结构、工具调用序列、持久化点、判断点位置、崩溃恢复、预算/终止、trace 形态、终答一致性）+ 全量回归。

## 注意事项

- E4 单测 600s 超时：pi_parity gate 必须保持秒级（当前 ~10s，含建库）。
- 外部 IO 不进数据库事务（v8 不变量 4 沿用）；测试为独立脚本（`uv run python`，退出码 0 = 通过）。
- 本 stage 不进 `SQL_LOAD_ORDER`；工具行是运行时 INSERT/DELETE，仅活在 `agent_v13_pi_parity`。
