# v13 pi_parity — pg-agent seam 环 vs pi/PiG/PiSwift agent 循环同任务对照

同一个脚本化 agent 任务（读 `hello.txt` 与 `fib.py`，回答两文件要点）在四个运行时各跑一遍，
全程确定性（无真实 LLM），落同一 schema 的归一化 trace（schema v2），最终产出过程+结果对照报告
（Turn 3，`docs/reviews/v13-pi-agent-parity-*.md`）。

- pg 侧：v13 seam 环（`v13_parse`/`v13_advance`/`v13_claim`/`v13_complete` + pg_typesafe mock 判断），库 `agent_v13_pi_parity`。
- pi 侧：`pi_driver.mjs`（Node strip-types + resolve hook）驱动 pi harness 真实 agent 循环 + `fauxProvider`。
- PiG 侧：`pig_driver/`（Go）自带 parityProvider（实现公开 `ai.Provider` 接口）+ `agent.NewAgent` 真实循环。
- PiSwift 侧：`piswift_driver/`（Swift）经 `createAgentSession` + `registerFauxProvider` 注册 faux provider 驱动真实会话循环。

## 任务定义（四侧同构）

1. fixture root 下有两个文件：`hello.txt`（三行问候）、`fib.py`（递归 fib，`fib(10)=55`）。
2. 任务指令：读两个文件，回答两文件要点。
3. 脚本化模型（判断/生成）是**确定性纯函数**，输入为累积上下文的内容（哈希/计数），输出为固定响应：
   - 0 个工具结果在场 → 发 read 工具调用 `hello.txt`；
   - 1 个工具结果在场 → 发 read 工具调用 `fib.py`；
   - 2 个工具结果都在场 → 终答 `final_from_results`：引用两文件内容的 sha256 摘要（前 16 hex）+ 固定要点句。
   - 同内容必得同响应；内容变则摘要变。注意 provider 总调用次数是 **3**（两次工具轮 + 一次终答轮）。
   - 四侧实现：pg=`test_pi_parity.py` 的 `digest`/`final_from_results`/`overrides_for`；pi=`pi_driver.mjs` 的
     `decideResponse`（计 transcript 中 toolResult 消息数）；PiG=`pig_driver/main.go` 的 `decideResponse`
     （计 `ai.ToolResultMessage` 数）；PiSwift=`piswift_driver/main.swift` 的 judgment factory（计 toolResult 消息数）。

## 归一 trace schema v2（四侧一致）

JSONL 文件（`traces/<side>.jsonl`），每行一个 JSON 对象：

- 步骤行：`{"runtime": "...", "seq": <int>, "phase": "judge|parse|advance|claim|tool|llm|finish|raw", "tool": <str|null>, "args": {...}, "result_digest": "sha256:<16hex>|\"\"", "persisted": "sql|file|memory", "evidence": "<非空证据串>", "raw": ["<native 事件名>", ...]（可选）}`
- 末行：`{"runtime": "...", "final": "<终答文本>"}`

`result_digest` 为 `sha256:` + 内容 utf-8 sha256 hex 前 16 位；无内容载荷的相位（claim/raw/finish）为空串。
**llm 是独立显式相位**（oracle P1 裁定）：provider 响应本身即一歩，不折叠进 tool/finish。
无规范相位归宿的框架原生事件**绝不静默丢弃**：折进行内 `raw[]`（跟随某规范步的伴随事件）或独立 `raw` 行
（`args.native` 记事件名）。judge/parse/advance 是 pg 侧独有相位——三框架无对应原生事件，**绝不伪造**。
`evidence` 必填非空；`persisted` 只允许如实标注（pg=`sql`，框架侧=`memory`），禁止无条件写 `sql`。

工件：`traces/pg.jsonl`（19 步）、`traces/pi.jsonl`（20 步）、`traces/pig.jsonl`（21 步）、
`traces/piswift.jsonl`（15 步），各加末行 final。四个 final 文本完全一致；两侧工具步
`result_digest` 与 pg 实算一致；末个 llm 步 digest = final 文本 digest。
**计数约定**：本文一律用 step 数（带 phase 的行）；JSONL 总行数 = step 数 + 1（末行 final），
Turn 3 报告引用时用 step 数。

## 规范相位映射表（oracle P1）

| 规范相位 | pg（seam 环） | pi（HarnessEvent） | PiG（AgentEvent） | PiSwift（AgentSessionEvent） |
|---|---|---|---|---|
| judge | `v13_parse` 判定路由（每轮 1 次） | —（无原生对应，不伪造） | — | — |
| parse | `v13_parse` | — | — | — |
| advance | `v13_advance` | — | — | — |
| claim | `v13_claim`（工具认领） | `tool_start`（含 toolCallId） | `ToolExecutionStartEvent` | `.toolExecutionStart` |
| tool | 工具效果行（event/effect id） | `tool_end`（含结果内容） | `ToolExecutionEndEvent` | `.toolExecutionEnd` |
| llm | llm 轮 `v13_claim`→效果行（1 次终答） | `message_end`（assistant 消息完结） | `MessageEndEvent`（assistant） | `.agent(.messageEnd(assistant))` |
| finish | 环收尾 | `run_end`（TerminalStatus） | `AgentEndEvent` | `.agent(.agentEnd)` |
| raw | —（pg 每步均有 SQL 证据） | lane_created/run_start/entry_added/turn_start/turn_end/usage/message_start/message_update… | AgentStartEvent/TurnStartEvent/TurnEndEvent/TimingEvent/message_start/message_end(user,toolResult)… | agent_start/turn_start/turn_end/非 message 的 entryAppended/message_start/message_update… |

基数与顺序规则：

- 框架侧规范（非 raw）序列恒为 `llm,claim,tool,llm,claim,tool,llm,finish`（两工具轮 + 终答轮），
  raw 行只允许插在其间，不得改变规范子序列。
- pg 侧规范序列恒为 `judge,parse,advance,claim,tool` ×2 + `judge,parse,advance,claim,llm` + `judge,parse,advance,finish`
  （GOLDEN_SEQUENCE，gate 冻结断言；终拍 llm 效果同样先经 claim 认领——claim kind=llm）。
- llm 步的 digest = 该次 provider 响应文本的 digest；pg 侧唯一 llm 步 digest = final 文本 digest（终答即唯一生成）。

## 持久化证据链（oracle P2）

证据是**内容绑定**的，不是只证顺序：持久层消息必须与事件流步同载荷（assistant 比对
文本 digest + stopReason + toolCalls；toolResult 比对 toolCallId + 结果 digest），任一不匹配
驱动即退出 5 且**不写 trace**（绝无 ok:true 降级）。终答一律取自持久层最终 assistant 消息，
并与事件流、确定性合同（final_from_results）三方互验。

- **pg**：`persisted="sql"`，每步 `evidence` 携带实查数据库得到的行级证据，实际语法：
  judge→`judgment_call:<hex>`（缓存命中时 `judgment_cache:+N`）、parse→`judgment_cache:+11`、
  advance→`event:<n>/turn/route`、claim→`effect:<hex>`、tool→`event:<n>/tool/result`、
  llm→`event:<n>/llm/message+effect:<hex>`、finish→`event:<n>/turn/end+session:completed`。
  工具行断言至 effects 表内容。绝无无条件写 `sql`。
- **pi**：`persisted="memory"`，`MemoryStorage` 会话 entry 序号——llm/tool 步
  `session_entry:#N/<kind> (MemoryStorage)`。entry_added 在 message_end/tool_end 之后才触发，
  故采用 run 后按序配对（assistant 序数 ↔ llm 步；toolResult 按 toolCallId）+ 内容比对。
- **PiG**：`persisted="memory"`，`OnMessagePersist`（每条新消息恰一次）——
  `persist:#N/assistant|toolResult (OnMessagePersist)`；持久日志捕获每条消息载荷供内容比对，
  终答取自其中最终 assistant 消息。
- **PiSwift**：`persisted="memory"`，证据序号一律以运行后 `sessionManager.getEntries()`
  全量列表为准（真会话位置；`entryAppended` 事件仅作旁证——事件序数是观察序而非会话序，
  且内存会话在边界还会补提交）。终答取自 getEntries 最终 assistant entry。

## 三框架驱动（Turn 2 交付）

### pi（TypeScript，`/Users/wxl/Projects/pi`，只读）

- 运行：`node --experimental-strip-types pi_driver.mjs`（cwd=本 stage；`pi_resolve_hook.mjs` 把裸说明符
  解析到 pi checkout 的 `packages/agent/dist`；`package.json`/`package-lock.json` 提供 `marked` 依赖）。
- 接线：`AgentHarness.create({session, models, model, activeToolNames:["read"], tools, toolContext:{env}, retry:{enabled:false}, toolExecution:"sequential"})`
  → `harness.lane(name, ctx).prompt(text)`；provider 用 `fauxProvider()` + `setResponses([decide×3])`；
  read 工具用 harness 自带 `src/harness/tools/read.ts`（经 `activeToolNames` 限面）。
- 事件面：HarnessEvent 全词表监听；伴随事件折入 `raw[]`，无归宿者成 raw 行。
- 驱动内合同：provider 恰好调用 3 次（计数包装 decideResponse，不满足退出 5）；
  运行前删除旧 trace，trace 必须由本次运行重建。
- 字节稳定：`MemoryStorage({now:()=>100})` 定时钟、固定 toolCallId（call-0/call-1）、序数证据、
  **相邻重复折叠** message_update 流式帧（帧数是传输层伪影，事件类型保留）。

### PiG（Go，`/Users/wxl/Projects/PiG`，只读，绝不修改）

- 构建：`GOWORK=off GOTOOLCHAIN=auto go build -o read_pig .`（cwd=`pig_driver/`，timeout 300s）。
- 接线：`agent.NewAgent(AgentOptions{Model, Tools, EventCh, ToolExecution: ToolModeSequential, OnMessagePersist})`，
  `a.Send(ctx, text)`；事件经**无缓冲** channel + 消费 goroutine（close-after-Send + join）录制。
- 诚实偏差（两条，均有明确理由）：① scripted 先例（`scriptedProvider`/`toolCallsThenText`）住在
  `_test.go` 里，外部包**无法导入**，故驱动自带 `parityProvider` 实现公开 `ai.Provider` 接口
  （`ai/types.go:552`，语义同 doneStream）；② PiG 不随库提供可导入的 read 工具，故驱动内置
  read 工具，围栏 = Abs+EvalSymlinks+Rel 包含检查 + regular file（裸 `filepath.Join` 不拒 `../`，
  也不拒符号链接逃逸）。判断函数仍与 pg 同构（计 toolResult 消息数）。
- 驱动内合同：provider 恰好调用 3 次（parityProvider.request 计数，不满足退出 5）；
  运行前删除旧 trace，trace 必须由本次运行重建；终答取自 OnMessagePersist 最终 assistant 消息。
- 字节稳定：TimingEvent raw 行只记 `Kind`（Duration 剔除）；固定 toolCallId；序数证据。

### PiSwift（Swift，`/Users/wxl/Projects/PiSwift`，只读）

- 构建：`swift build -c release --product piswift_driver --build-path <repo根>/.piswift-build-parity`
  （本 stage 专属增量缓存，timeout 600s；`--show-bin-path` 定位产物。**不与 pi_ports 共享**
  `.piswift-build/`：SwiftPM 不支持两个不同 package 共用一个 --build-path，共享会互相覆盖
  build description 击穿 pi_ports 冻结 gate——首跑冷构建 ~3 分钟，之后秒级增量。）
- 接线（**全部公开 API，冒烟已实证，无降级**）：`PiSwiftAI.registerFauxProvider()` +
  `FauxProviderRegistration{setResponses([.factory(...)])}` + `getModel()`；Model 经
  `CreateAgentSessionOptions.model`（SDK.swift:504）传入；`AuthStorage(<tmp>/auth.json).setRuntimeApiKey(model.provider, key)`
  过凭据门（默认会打真 `~/.pi/agent/auth.json`，必须显式给临时存储）；`toolNames:["read"]` 白名单；
  `offline:true`；`SessionManager.inMemory(cwd)`；`session.prompt(text)` + `subscribe` 录
  `AgentSessionEvent`。注意 PiSwift 的 `Provider` 是 `typealias Provider = String`（Model 携带的是
  provider **名**而非实例），所以注入走 faux-provider 注册路由而非直塞实例。
- fail-closed 合同：`CreateAgentSessionResult.modelFallbackMessage` 非空 → 硬失败退出 5（faux-only
  合同不许模型降级）；证据序号一律取运行后 `sessionManager.getEntries()`（事件序数仅旁证）；
  count/toolCallId 不匹配 → 退出 5 且不写 trace；provider 恰好调用 3 次；运行前删除旧 trace。
- 字节稳定：CryptoKit SHA256、固定 toolCallId、`Recorder`（NSLock 保护）、序数证据。

## gate 语义

`UV_FROZEN=1 uv run python v13/pi_parity/test_pi_parity.py`

- 退出码 0 = 无失败；断言失败退出 1。
- 工具链缺失（node/pi checkout/node_modules、go/PiG checkout、swift/PiSwift checkout）时相应侧跳过，
  打印 `[SKIP] not_run/toolchain_absent planes=...`（绝不伪造 PASS），**不**改变退出码。
  原因：read_tools 的 E4 会扫描全部 `v13/test_*.py` 且零容忍非零退出（单测 600s 超时），
  若顶层用「有跳过则退出 2」语义会击穿零回归检查——跳过信号只存在于打印输出。
- **严格模式 `PI_PARITY_REQUIRE_ALL=1`**：任一平面缺席 → 退出 1（终审回归用此模式跑，
  保证四侧全实证而非静默跳过）。
  （**已记录假设**：E4 串行逐个执行 v13 test_*.py；本 gate 含 go/swift 构建时总时长仍在 E4 单测
  600s 预算内，因为共享增量缓存下构建是秒级。）
- pg 侧断言组（P- 前缀）：guard、setup/catalog/budget/override、环行走（routes=[tool,tool,llm,finish]、
  claim 参数序、tool/result 与 effects 内容、终答与终态）、trace 断言（GOLDEN_SEQUENCE、llm digest
  =final digest、evidence 非空、persisted=sql、seq 连续）、清理。
- 框架侧断言组（PI-/PIG-/PISWIFT- 前缀）：driver ok + providerCalls==3、trace 文件/schema/runtime
  匹配、seq 连续、相位词表合法、规范子序列 = `llm,claim,tool,llm,claim,tool,llm,finish`、llm 合同
  （toolUse read hello.txt → toolUse read fib.py → stop 终答）、callId 联动（claim 行携 call-0/call-1
  与 llm toolCalls 对应）、工具序列=[hello.txt,fib.py] 且 digest 与 pg 一致、末 llm digest=final digest、
  finish status=completed、final 与 pg 全等、evidence 非空且无 pending/降级串、persisted=memory、
  **字节稳定**（驱动跑两遍比对 trace 文件全等；驱动调用前删除旧 trace，文件必须由本次运行重建）。

## guard（防破坏冻结面）

`run_guard()` 三查（沿 pi_ports G2 模式，但基线是**稳定基线**而非 HEAD^）：

1. `git diff --name-only 4436cd8 HEAD -- v13 v8 pyproject.toml uv.lock` —— 自
   `PI_PARITY_BASE=4436cd8`（pi_parity 首提交的前一提交）到 HEAD 的**全部**提交不得触碰
   冻结面（`HEAD^..HEAD` 在后续轮次提交后就护不住本轮了）。
2. 工作区脏文件同 pathspec 检查（改动中也不许动冻结面）。
3. 未跟踪文件同 pathspec 检查。

冻结面前缀：`v13/read_tools/`、`v13/pi_ports/`、`v8/`（v8 一直在 README 里声明为冻结，
现已一并入 pathspec）。任一命中即拒绝运行。

## 轮次规划

- Turn 1（已交付）：pg 侧行走通 + trace 落盘 + 三框架只读探查。
- Turn 2（本文件现状）：三框架侧接线交付（pi_driver.mjs / pig_driver/ / piswift_driver/）、
  同构判断函数移植、四侧 trace 断言升级（工具序列+摘要等价、终答一致、evidence 链、字节稳定）。
- Turn 3：对照报告（turn/cycle 结构、工具调用序列、持久化点、判断点位置、崩溃恢复、预算/终止、trace 形态、终答一致性）+ 全量回归。

## 注意事项（诚实清单）

- E4 单测 600s 超时：pi_parity gate 必须保持快（`.piswift-build-parity` 增量缓存下 swift 构建
  秒级、冷缓存首次 ~3 分钟在构建 600s 预算内；pig 构建 ~10 秒）——但 E4 **单测**预算 600s 内
  本 gate 若遇冷构建会被构建耗时吃掉大半；已记录风险：冷缓存下 E4 单测 600s 对本 gate 是紧的
  （实测全 gate 含冷构建 ~4 分钟量级），如击穿需把构建挪到 gate 外或放宽该单测预算。
- E4 **串行执行假设**：E4 逐个跑 `v13/test_*.py`，故本 gate 与 pi_ports gate 各自串行使用
  各自的 swift 构建目录（`.piswift-build-parity/` vs `.piswift-build/`），互不争锁；若 E4 未来改
  并行，需先复核共享构建目录问题。
- pg 侧 runtime UPDATE `spawn_subsession`：工具行是运行时 INSERT（catalog 工具面之外的
  `spawn_subsession` 参数覆盖用 UPDATE 注入 mock 判定），仅活在 `agent_v13_pi_parity` 库，
  gate 结束删除本轮 INSERT 的工具行并断言 revision 回退（P-cleanup）；**恢复语义 = DB 重建**：
  setup_db 每次运行 DROP/CREATE 自有库，不依赖 gate 内清理也不改任何 SQL 文件。
- 库名约定：`agent_v13_pi_parity`（`v13_setup.db_name` 风格：`agent_<version>_<stage>`），
  setup DROP/CREATE 自有库，**不**进 `SQL_LOAD_ORDER`。
- 缓存命中去重分支（judge 对已见内容的 memo 命中）在当前固定任务下**未被执行**——
  两次工具轮内容各异、终答轮上下文唯一，缓存永不命中；该分支存在但本 gate 不覆盖。
- 框架仓库一律只读：pi/PiG/PiSwift 的源码零修改（PiG 明令禁止修改；另两家同为外部 checkout）。
- 外部 IO 不进数据库事务（v8 不变量 4 沿用）；测试为独立脚本（`uv run python`，退出码 0 = 通过）。
- `.gitignore` 追加：本 stage 的 `node_modules/`、`pig_driver/read_pig` 二进制、
  `piswift_driver/.build/`、`traces/*.tmp`（驱动不产 tmp，防御性）。
