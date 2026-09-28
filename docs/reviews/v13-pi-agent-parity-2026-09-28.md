# v13 pi-agent parity：四运行时同任务「过程/结果」对照（2026-09-28）

用户原始问题：**pg-agent 与 pi 系框架跑同一个 agent 任务，工作过程和结果一样吗？**

本文是 `v13/pi_parity`（loop `agent_parity` Turn 3）的收官对照报告。同一个脚本化 agent 任务——读
`hello.txt` 与 `fib.py`，回答两文件要点——分别在四个运行时各跑一遍：

| 侧 | 运行时 | 循环形态 | 驱动/入口 |
|---|---|---|---|
| pg | pg-agent v13 seam 环 | `v13_parse`→`v13_advance`→`v13_claim`→效果/事件落库 | `test_pi_parity.py`（pg_typesafe mock 判断） |
| pi | pi harness（TypeScript） | `AgentHarness` lane 循环 | `pi_driver.mjs` |
| pig | PiG agent（Go） | `agent.NewAgent` 循环 | `pig_driver/main.go` |
| piswift | PiSwift coding-agent session（Swift） | `createAgentSession` 会话循环 | `piswift_driver/Sources/piswift_driver/main.swift` |

全程确定性（无真实 LLM）：判断/生成是四侧同构的确定性纯函数（输入=累积上下文内容，输出=固定响应；
`v13/pi_parity/README.md` 任务定义节）。归一化 trace（schema v2）四份已入库
`v13/pi_parity/traces/{pg,pi,pig,piswift}.jsonl`。

---

## 结论（先答问题）

**在本次确定性、单会话的两文件任务上，结果一样；过程不一样。**

- **结果一样**：四侧终答文本逐字节全等；末次生成 digest 均为 `sha256:5cb9996bc1b6b1aa`（= 终答文本
  digest）；工具调用序列均为 read `hello.txt` → read `fib.py`，两文件内容 digest 四侧一致
  （`sha256:43cb4c6532bacb4a` / `sha256:251b6646b62ee66a`；digest 记法一律为内容 utf-8 sha256 的 16-hex 前缀，下同）；三框架侧 provider 在本次脚本化 provider 合同下恰好调用 3 次；
  三框架驱动字节稳定（连跑两遍 trace 文件全等）。终审回归（见文末）全部 exit 0。
- **过程不一样**（结构性差异，后文逐条给证据）：
  1. **步数不同**：pg 19 步 / pi 20 步 / pig 21 步 / piswift 15 步（step 数口径，非 JSONL 行数）；
  2. **相位结构不同**：pg 每拍过 `judge,parse,advance` 三相位；框架侧规范相位序列为
     `[llm,claim,tool,llm,claim,tool,llm,finish]`，其余全是 raw 事件行；
  3. **判断点不对称**：pg 每拍产生独立判断事件（judge 步 ×4）；框架侧判断只发生在 provider 响应
     内部，从不产生独立判断事件；
  4. **claim 语义不同**：pg claim=持久效果租约（effect 行；本轮已验证持久化记录与 claim/effect
     链接，未实测崩溃后的续租/重认领/续跑）；框架 claim=工具分派开始
     （纯事件流标记，无持久化语义，本驱动会话在内存）；
  5. **持久化语义不同**：pg 每步 SQL 事件/效果行、证据可查；pi=MemoryStorage entry；pig=OnMessagePersist
     回调；piswift=SessionManager.inMemory 惰性边界提交；
  6. **原生事件词汇不同**：HarnessEvent vs AgentEvent(channel) vs AgentSessionEvent；
  7. **注入路线不同**：fauxProvider（框架自带）vs 自实现 `ai.Provider`（已档偏差）vs
     registerFauxProvider 注册路由（`Provider` 是 String typealias）。

一句话：**四个运行时对「读两个文件并作答」这个任务给出了同一份答案，但它们组织一次 agent 循环的
方式——判断放在哪、状态落在哪、事件怎么说话——是四种不同的结构。**

---

## 版本与入口证据（都是真实框架循环）

三框架仓库只读、以本地 checkout 驱动（`git -C <repo> rev-parse HEAD`，2026-09-28 终审回归时实取）：

| 侧 | 入口 API（驱动行号） | checkout HEAD | 版本常量 |
|---|---|---|---|
| pi | `AgentHarness.create`（`pi_driver.mjs:249`）→ `harness.lane(name, ctx).prompt(text)` | `2b0a123de`（2026-09-26） | `0.87.1`（pi_ports gate EVID 针，见 trilingual 报告框架入口表） |
| pig | `agent.NewAgent(AgentOptions{…})` + `a.Send(ctx, text)`（`pig_driver/main.go`） | `ecfcc83`（2026-09-27） | `0.2.0+0.87.1`（`coding/pigversion/pigversion.go:7-17`） |
| piswift | `createAgentSession(CreateAgentSessionOptions…)`（`main.swift:233`）+ `session.prompt(text)` | `bfccb32`（2026-09-23） | `0.87.1`（`Sources/PiSwiftCodingAgent/Config.swift:6`） |

- 「真实循环」的证据是接线方式本身：三侧都没有 mock 框架的循环代码，只替换了 provider 与（必要的）
  工具面，循环、事件流、会话管理全部走框架原生路径（各驱动头注释列明框架面：
  `pi_driver.mjs:5-11`、`pig_driver/main.go:1-33`、`main.swift:1-35`）。
- 版本口径的诚实说明：三框架是活跃 checkout，本文所有结论的版本证据=「2026-09-28 终审回归在这些
  HEAD 上 143 PASS 0 SKIP 全绿」（回归记录见文末）；版本常量沿 trilingual 报告
  （`docs/reviews/v13-pi-ports-trilingual-2026-09-28.md`）的 EVID 钉法。

---

## 结果等价面

### 1. 工具调用序列与内容 digest（四侧一致）

| 项 | 值 | trace 证据（side:seq） |
|---|---|---|
| 第 1 次工具调用 | read `hello.txt` | pg:3-4、pi:6-7、pig:3-4、piswift:3-4 |
| 第 2 次工具调用 | read `fib.py` | pg:8-9、pi:12-13、pig:10-11、piswift:8-9 |
| `hello.txt` 内容 digest | `sha256:43cb4c6532bacb4a` | 四侧 tool 步 `result_digest` 全同 |
| `fib.py` 内容 digest | `sha256:251b6646b62ee66a` | 四侧 tool 步 `result_digest` 全同 |

gate 断言：框架侧「工具序列=[hello.txt,fib.py] 且 digest 与 pg 实算一致」（PI-/PIG-/PISWIFT- 组）、
llm 合同「toolUse read hello.txt → toolUse read fib.py → stop 终答」、callId 联动（claim 行携
`call-0`/`call-1` 与 llm 步 toolCalls 对应）——严格模式 143 PASS 中全部在场（log 断言名：
`PI-seq`/`PIG-seq`/`PISWIFT-seq` 等）。

### 2. 终答文本全等 + digest 三方互验

四份 trace 末行 final 逐字节相同：

> `hello.txt sha256:43cb4c6532bacb4a is a three-line greeting file; fib.py sha256:251b6646b62ee66a defines recursive fib(n) with fib(10)=55; both files were read.`

- pg 唯一 llm 步 digest = `sha256:5cb9996bc1b6b1aa` = 终答文本 digest（pg:14，断言 `P-trace` 的
  「llm digest=final digest」）；
- 三框架末个 llm 步 digest 同为 `sha256:5cb9996bc1b6b1aa`（pi:16、pig:16、piswift:12），且终答
  一律**取自持久层最终 assistant 消息**（pi=MemoryStorage tip entry #5；pig=OnMessagePersist 最终
  assistant；piswift=`getEntries()` 最终 assistant entry），与事件流、确定性合同（`final_from_results`）
  三方互验——任一不匹配驱动退出 5 且不写 trace（`pi_driver.mjs:347`、`pig_driver/main.go:541-542`、
  `main.swift:504` 附近的 `final_mismatch` 分支）。
- 终态一致：四侧 finish 均 status=completed（pg:18 `session:completed`；pi:19、pig:20、piswift:14
  `status:"completed"`；断言 `P-final` 与三侧 finish/final 组）。

### 3. provider 恰好 3 次

三框架侧 provider 调用计数合同：两次工具轮 + 一次终答轮 = 3（`pi_driver.mjs` 计数包装 decideResponse、
`pig_driver/main.go:478` `provider.requests()!=3` 即退出 5、piswift `providerCalls`）。gate 断言
（`PI-run`/`PIG-run`/`PISWIFT-run` 组）要求 driver 自报 `providerCalls==3`。

诚实注脚：pg 侧没有「provider」这个面——等价的信息处理被分解为 **4 次判断调用**（judge 步 pg:0/5/10/15）
**+ 1 次生成**（llm 步 pg:14，`model:"fake"`）。「恰 3 次」是框架侧合同；pg 侧对应物是 5 次 mock 调用、
且判断面在终拍之后还再过一拍（pg:15-17 判定收尾）。这本身是过程差异（见判断点不对称条），不是结果差异。

### 4. 字节稳定

三框架驱动各连跑两遍、trace 文件逐字节全等（`assert_byte_stable`，`test_pi_parity.py:981-985`；
断言 `PI-byte-stable`/`PIG-byte-stable`/`PISWIFT-byte-stable`）。字节稳定是工程出来的：pi 固定时钟
`MemoryStorage({now:()=>100})`+固定 toolCallId+相邻重复折叠 message_update；pig TimingEvent 只记
`Kind`（剔 Duration）+固定 toolCallId；piswift CryptoKit SHA256+固定 toolCallId+NSLock Recorder。
pg 侧无字节稳定断言——其 evidence 盐值（`judgment_call:<hex>`/`effect:<hex>`）逐运行变化，但相位
结构由 GOLDEN_SEQUENCE 冻结（`P-trace-golden`），内容 digest 逐次一致。

---

## 过程差异面

### 1. 步数与相位结构

**口径**：本文 step 数 = trace 中带 `phase` 的行数；JSONL 总行数 = step 数 + 1（末行 final）。
框架侧 step = 8 个规范相位步 + raw 事件行；pg 侧 step = 全部规范相位步（无 raw——每步都有 SQL 证据归宿）。

| 侧 | step 数 | 规范相位构成 | raw 行数 |
|---|---|---|---|
| pg | **19** | `judge,parse,advance,claim,tool` ×2 + `judge,parse,advance,claim,llm` + `judge,parse,advance,finish`（judge×4/parse×4/advance×4/claim×3/tool×2/llm×1/finish×1） | 0 |
| pi | **20** | `llm,claim,tool` ×2 + `llm,finish`（llm×3/claim×2/tool×2/finish×1） | 12 |
| pig | **21** | 同上骨架 | 13 |
| piswift | **15** | 同上骨架 | 7 |

- pg 规范序列由 gate 冻结：`GOLDEN_SEQUENCE`（`test_pi_parity.py:66-73`，断言 `P-trace-golden`:729）。
- 三框架规范子序列由 gate 冻结：`FRAMEWORK_TOOL_SEQUENCE = [llm,claim,tool,llm,claim,tool,llm,finish]`
  （`test_pi_parity.py:772`，断言 `{tag}-canonical`:912）；raw 行只允许插在其间，不得改变规范子序列。
- 步数差异的来源**全部在 raw 粒度**（12/13/7）与 pg 的判断面展开（每拍 4 步 vs 框架每轮 1 个 llm 步），
  不在任务语义。pi 20 vs pig 21 vs piswift 15 的差异是各框架事件词汇粒度不同（见第 6 条）。
- 一个可观察的分解差：框架侧工具轮的 llm 步 text 为空（决策全在 toolCalls 里），digest=
  `sha256:e3b0c44298fc1c14`（空串 sha256 前 16 hex；pi:4/10、pig:2/9、piswift:2/7）；pg 侧工具轮
  **没有** llm 步——工具决策走判断面（judge 步 intent=`tool_action`），pg 唯一 llm 步就是终答生成。

### 2. 判断点不对称

- **pg：判断是独立、持久、每拍都在的平面。** judge 步 ×4（pg:0/5/10/15），args 携带完整判断面输出
  （`intent`=`tool_action`/`llm_generate`、`risk`=`score`、`gate_action`/`gate_off_topic`=`noul`、
  声明参数 vs 实参对），evidence 为 `judgment_call:<hex>`（实查 DB 的判断调用行）。判断面由 pg_typesafe
  mock 经 `v13_parse` 驱动——**判断本身是循环的一等公民**，每个动作（两次工具、一次生成、一次收尾）
  之前都过判断。终拍之后还有一拍判断（pg:15）审定收尾。
- **框架：判断溶解在 provider 响应里。** 三框架 trace 中 judge 相位数为 0（schema 允许 judge，但框架
  无对应原生事件，**绝不伪造**——README 相位映射表）。脚本化判断函数决定 provider 返回什么
  （toolCall 或终答），框架循环只是执行响应——判断从不产生独立事件，也就不可独立观察、不可独立
  持久化、不可在恢复时单独重放。这是 pg 判断面（judgment as a plane）与框架「判断=模型内部」的
  根本结构差。

### 3. claim 语义差

| 侧 | claim 是什么 | 证据 | 恢复语义 |
|---|---|---|---|
| pg | **持久效果租约**：`v13_claim` 认领一个 effect 行（工具 claim 带 `handler:"worker:read_file"`；终答生成同样先经 claim，pg:13 `kind:"llm"`） | claim 步 evidence=`effect:<hex>`（实查 effects 表）；工具行断言至 effects 表内容 | effect/event 行在 SQL；本轮已验证持久化记录与 claim/effect 链接，**未实测**崩溃后的续租/重认领/续跑 |
| pi/pig/piswift | **工具分派开始**：事件流标记工具即将执行（pi `tool_start`、pig `ToolExecutionStartEvent`、piswift `.toolExecutionStart`） | claim 步 evidence=`memory: dispatch tool_call:call-N`（无持久化载荷） | 无持久语义；本驱动会话在内存（各框架接入持久 backend 的恢复边界未测） |

pg 侧「生成也要先认领」（pg:13 claim kind=llm → pg:14 llm 效果）意味着 **tool 与 llm 两类效果都有
租约链（finish 拍无 claim）**；框架侧 claim 只伴随工具调用，生成步（llm）没有认领前奏。

### 4. 持久化语义

| 侧 | 持久化点 | trace 证据形态 | 证据可查性 |
|---|---|---|---|
| pg | **每步 SQL 事件/效果行**（19 步全部 `persisted:"sql"`） | judge→`judgment_call:<hex>`/`judgment_cache:+11`、advance→`event:<n>/turn/route`、claim→`effect:<hex>`、tool→`event:<n>/tool/result`、llm→`event:<n>/llm/message+effect:<hex>`、finish→`event:<n>/turn/end+session:completed` | 直接查库；evidence 串逐相位给出可定位行 |
| pi | `MemoryStorage` 会话 entry | `session_entry:#N/<kind> (MemoryStorage)`（assistant #1/#3/#5、toolResult #2/#4）；`entry_added` 在 `message_end` 之后才触发，故驱动 run 后按序配对+内容比对 | 进程内；会话文件形态存在（StorageBackedSession）但本驱动用内存 storage |
| pig | `OnMessagePersist` 回调（每条新消息恰一次） | `persist:#N/assistant\|toolResult (OnMessagePersist)`（#1-#5）；finish 行自报 6 messages persisted——序数 #0 是 **user 任务消息**（ordinal 从 0 起，`main.go:341`；配对只取 assistant/toolResult，user 消息不绑定任何规范步，故无 evidence 行），即 6 = user 1 + agent 侧 5（assistant×3+toolResult×2） | 回调是接持久层的钩子位；本驱动只记日志（agent 内存态） |
| piswift | `SessionManager.inMemory` 惰性边界提交 | `session_entry:#N/<kind> (SessionManager.inMemory)`；**证据序数一律以运行后 `getEntries()` 全量列表为准**（`main.swift:383`），`entryAppended` 事件序数仅旁证（观察序≠会话序，内存会话边界还会补提交） | 进程内；换持久 backend 需另接 SessionManager 实现 |

序数空间的细节差也可见一斑：pi 的 agent 消息从 entry #1 起；piswift 的会话预置 system/用户条目，
assistant 落在 #4/#6/#8（finish 时共 9 entries）——「会话里第几条」在两框架不是同一含义。

诚实注脚：pg 侧 `judgment_call:<hex>`/`effect:<hex>` 的盐值逐运行变化（本工作区实查：同一 gate 两次
运行仅这些 hex 变化，相位/参数/digest 逐字节同）；本文一律只引 digest 与 evidence **语法**，不引盐值。

### 5. 原生事件词汇

- **pi = HarnessEvent**：`lane_created`/`run_start`/`entry_added`/`turn_start`/`turn_end`/`usage`/
  `message_start`/`message_update`/`message_end`/`tool_start`/`tool_end`/`run_end`；流式帧
  （message_update）是传输层伪影，驱动做相邻重复折叠。
- **pig = AgentEvent（channel）**：`agent.AgentStartEvent`/`TurnStartEvent`/`TurnEndEvent`/
  `TimingEvent`（带 kind：tool/turn/session_end）/`MessageEndEvent`/`ToolExecutionStart(End)Event`/
  `AgentEndEvent`；TimingEvent 携 Duration（驱动剔除以保字节稳定）。
- **piswift = AgentSessionEvent**：`agent_start`/`turn_start`/`turn_end`/`entryAppended`/
  `message_*`/`agentEnd`（经 `subscribe` 录制）。
- 归一规则：无规范相位归宿的原生事件折进行内 `raw[]` 或独立 raw 行（`args.native` 记事件名），
  **绝不静默丢弃**；raw 行数差异（12/13/7）即三框架事件粒度差异的直接读数。

### 6. 注入路线（脚本化 provider 怎么进去）

| 侧 | 路线 | 证据/偏差档 |
|---|---|---|
| pi | 框架自带 `fauxProvider()` + `setResponses([×3])`（`pi_driver.mjs:37/101/112`，来自 `@earendil-works/pi-ai`）；read 工具用 harness 自带 `src/harness/tools/read.ts`（`activeToolNames:["read"]` 限面） | 无偏差 |
| pig | **自实现 `parityProvider`** 实现公开 `ai.Provider` 接口（`pig_driver/main.go:69/100`；接口在 `ai/types.go:552`）——PiG 的 scripted 先例（`scriptedProvider`/`toolCallsThenText`）住在 `_test.go`，外部包无法导入；**read 工具驱动内置**（PiG 不随库提供可导入 read 工具），围栏=Abs+EvalSymlinks+Rel 包含检查+regular file | 两条已档偏差（README「诚实偏差」节） |
| piswift | `registerFauxProvider()` 注册路由 + `FauxProviderRegistration.setResponses`（`main.swift:219-220`）；**发现 `Provider` 是 `typealias Provider = String`**——Model 携带 provider 名而非实例，注入只能走注册路由，不能直塞实例；Model 经 `CreateAgentSessionOptions.model`（入口 `createAgentSession`，`Sources/PiSwiftCodingAgent/Core/SDK.swift:504`）传入；`AuthStorage(<tmp>)` 过凭据门；`offline:true`+`toolNames:["read"]` | 无降级；`modelFallbackMessage` 非空即硬失败（fail-closed） |
| pg | 判断面注入：pg_typesafe mock 经参数覆盖（`overrides_for`）+ 运行时工具行 INSERT/UPDATE（仅活在 `agent_v13_pi_parity` 库，gate 结束 DELETE 并断言 revision 回退） | README「注意事项」节 |

三条框架路线互不相同、且没有一条是「塞一个 Provider 实例进循环」的同一形状——这本身是三框架
provider 抽象差异的实证（pi=实例工厂、pig=接口实例、piswift=名字注册表）。

### 7. 崩溃恢复与预算/终止（证据等级：结构性论述，未插桩实测）

- **崩溃恢复**：本轮**没有**做中途杀进程续跑实验（loop 计划曾列为可实测项，Turn 2/3 未排入）。
  结构性结论：pg 的全部循环状态（判断调用、事件、效果、会话终态）在 SQL 行里，`persisted:"sql"`
  ×19 步即证据——恢复语义是「从库重放/对账续跑」（本 gate 自身的恢复口径=setup 每轮 DROP/CREATE
  重建库，不依赖跨进程续跑）；三框架会话均内存态（MemoryStorage/inMemory/回调未接后端），进程崩溃
  即失会话，恢复依赖各自换持久 backend（pi StorageBackedSession 可换 storage、PiSwift SessionManager
  可换实现）。此段为源码结构论述，**非实测**。
- **预算/终止**：本轮任务规模未触发任何预算上限路径（pg 环 routes=[tool,tool,llm,finish] 在
  turn budget 内走完；pi 驱动显式 `retry:{enabled:false}`）。可比较的只有终止状态字面：四侧终态
  均 completed（见结果等价面第 2 条）。预算触发路径（超限、重试、降级）的行为差异**本轮无数据**，
  不下结论。

---

## 口径与边界

1. **确定性脚本化判断**：无真实 LLM。判断/生成是纯函数（同内容必同响应），「结果一样」证明的是
   四个运行时在**同一确定性决策序列**下执行等价，不证明真实模型下终答会一致。
2. **任务规模小**：两文件读+终答，单会话单 lane。长程任务（多轮、compaction、并发 lane、预算触发）
   的过程差异只会更大，不外推。
3. **step 计数口径**：见过程差异面第 1 条的映射表；引本文数字时一律用 step 数（19/20/21/15），
   JSONL 行数是 step+1。
4. **digest 引用口径**：只引内容 digest（稳定）与 evidence 语法；evidence 盐值逐运行变化，不引值。
5. **口岸层（工具语义）另文**：read 工具的 CRLF/trailer/51200 帽/offset 越界/围栏/错误闭集等三语言
   差异见 `docs/reviews/v13-pi-ports-trilingual-2026-09-28.md`（pi_ports loop 交付）。本文是
   **循环层**对照，两文互补不重复。
6. **框架仓库只读**：pi/PiG/PiSwift 源码零修改；PiG 明令禁止修改。
7. **恢复/预算两维**：结构性论述，未插桩（见过程差异面第 7 条）。

---

## 终审回归记录（2026-09-28，本报告提交前实跑）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `PI_PARITY_REQUIRE_ALL=1 UV_FROZEN=1 uv run python v13/pi_parity/test_pi_parity.py` | **exit 0；143 PASS 0 SKIP**（严格模式，四侧全实证） |
| 2 | `UV_FROZEN=1 uv run python v13/pi_ports/test_pi_ports.py` | **exit 0；302 PASS 0 SKIP** |
| 3 | `UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py --contract` | **exit 0；237 PASS 0 SKIP** |
| 4 | `UV_FROZEN=1 uv run python v13/read_tools/test_read_tools.py`（无旗标，ring + E4 串行全量） | **exit 0；E4 32 个子测全部退出码 0**（含 pi_parity/pi_ports 作为子测复跑，均 → 0），全程零 SKIP，末断言 `[PASS] E4` |

基线对齐：#2/#3 与 loop 台账 Turn 0 基线（pi_ports 302 / read_tools contract 237）逐数一致；
#1 与 Turn 2 交付态（143 PASS 0 SKIP）逐数一致。零回归。
