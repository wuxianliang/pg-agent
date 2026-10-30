# 本地原生 Agent 系统架构调研：RepoPrompt CE、Codex 与 LoopX 的控制模式解剖与融合设计

**调研日期：2026-09-21** ｜ 调研对象：[repoprompt/repoprompt-ce](https://github.com/repoprompt/repoprompt-ce)、[openai/codex](https://github.com/openai/codex)、[huangruiteng/loopx](https://github.com/huangruiteng/loopx)

## TL;DR

三者不是同类竞品，而是同一条控制栈上的三个正交层次：**Codex 是 turn 内的执行引擎**（agent loop + 沙箱 + 审批），**RepoPrompt CE 是 turn 的上下文供给者与会话宿主**（MCP server 倒转为主 agent，CLI harness 变成可插拔 provider），**LoopX 是跨 turn、跨会话的持久控制平面**（durable 状态内核 + 确定性配额裁决）。它们共享同一个架构思想——把"控制"从"执行"中拆出来——只是拆的位置不同。

要合成一个本地原生 agent 系统而不是三套，关键在于认出三者各自只有一样东西是别人没有的：Codex 的**有界 turn 执行语义与沙箱/审批双层模型**、RepoPrompt CE 的**上下文工程与 provider 插件 seam**、LoopX 的**事件账本与确定性调度裁决**。融合方案是：**单一 append-only 事件账本作为唯一状态真相，其上是确定性控制内核，再其上是可替换的 turn 执行器，最外是三个协议出口（原生 UI、MCP 工具面、双向会话协议）**——一份状态、一个时钟、一套裁决，三种能力平面，而不是三个进程各自为政。

---

## 一、Codex：Turn 内执行引擎的控制模式

### 1.1 Agent loop 即全部，但细节全在状态管理

Codex 的控制模式可以用一句话概括：**agent loop 是一个"构造 prompt → 推理 → 执行工具 → 把结果追加回 prompt → 再推理"的 while 循环，退出条件是模型产出 assistant message 而非 tool call**（[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/)）。这个定义本身与 Anthropic、Google 的实现没有本质区别——所有主流 coding CLI 的 canonical loop 都是同一个（[lagindicator](https://lagindicator.com/dev-tools/cli-benchmarks/)）。真正构成 Codex 控制模式特色的，是围绕这个循环的四组工程决策。

第一组是**无状态请求与 append-only prompt**。Codex 不使用 Responses API 的 `previous_response_id`，每个请求都携带完整对话历史，以支持 Zero Data Retention 客户；代价是流量上 O(n²)，因此 **prompt caching 成为硬性约束**——缓存命中要求精确的前缀匹配，所以静态内容（instructions、tools）必须排最前，任何中途变更（切换模型、改沙箱配置、改 approval 模式、改 cwd）都以"追加一条新 developer/user 消息"的方式表达，而不是回改旧消息（[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/)）。第二组是**自动压缩**：token 超过 `auto_compact_limit` 时调用 `/responses/compact`，用包含加密潜状态的 `compaction` item 替换整段历史（[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/)）。第三组是**初始 prompt 的装配顺序**：instructions（模型专属 prompt 文件）→ tools → developer 消息（沙箱权限说明）→ config.toml 的 developer_instructions → 聚合的 AGENTS.md 链（从 git root 到 cwd，默认 32 KiB 上限）→ environment_context → 用户消息（[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/)，[k4nul](https://www.k4nul.com/en/ai/how-token-management-strategies-differ-between-codex-and-claude-code/)）。第四组是**安全双层**：sandbox policy（read-only / workspace-write / danger-full-access）决定"进程技术上能碰什么"，approval policy 决定"什么时候必须停下来问人"，二者正交（[3LS](https://www.threelawssecurity.com/resources/blog/agent-sandboxes-deep-dive/)）；强制执行走 OS 原语——macOS Seatbelt 的 SBPL profile、Linux bubblewrap + seccomp + Landlock、Windows restricted token——且 `.git` 与 `.codex` 目录被强制只读（[danielvaughan](https://codex.danielvaughan.com/2026/05/03/codex-cli-sandbox-internals-seatbelt-bubblewrap-landlock-windows-dacl/)）。值得注意的一个边界：Codex 的沙箱只约束其自带 shell 工具，MCP server 提供的工具不在沙箱内，须各自实施防护（[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/)）。

### 1.2 App Server：把 harness 从 UI 中拆出来

Codex 控制模式的另一半，是它如何把同一个 agent loop 供给 CLI、VS Code 插件、桌面 app、web 四类界面。答案是 **App Server：一个长驻进程 + 双向 JSON-RPC 协议**，内部由 stdio reader、message processor、thread manager 和 per-thread 的 core session 组成；core 既是库也是运行时，托管单条 thread 的 agent loop 与持久化（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)）。协议围绕三个会话原语设计：**Item**（输入输出的原子单元，有 started / delta / completed 生命周期）、**Turn**（一次用户输入触发的工作单元）、**Thread**（可创建、恢复、fork、归档的持久容器，事件历史落盘，客户端可断线重连）（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)，[InfoQ](https://www.infoq.com/news/2026/02/opanai-codex-app-server/)）。

这里有一个对融合设计极重要的历史教训：OpenAI **最初尝试把 Codex 暴露为 MCP server 来驱动 VS Code 插件，但发现 MCP 的工具调用语义无法干净地承载 IDE 所需的流式 diff、审批中断、thread 持久化等富会话语义，于是放弃并自研了 App Server 协议**（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)，[InfoQ](https://www.infoq.com/news/2026/02/opanai-codex-app-server/)）。MCP 出口仍然保留（`codex mcp-server`）供其他 agent 把 Codex 当工具调用，但定位已降级为简单集成路径，官方推荐全保真集成走 App Server（[ccleaks](https://ccleaks.com/news/codex-mcp-server-deprecated-app-server-aug-2026)）。审批流也体现了"双向"的含义：agent 需要批准时由 server 主动向 client 发请求并暂停 turn，直到 client 回复 allow/deny（[InfoQ](https://www.infoq.com/news/2026/02/opanai-codex-app-server/)）。源码层面，`codex-rs` 工作区把这个思想落成 crate 边界：`core`（agent 逻辑、config、auth、exec、sandboxing）是不依赖任何 UI 的内核，`tui`、`exec`、`app-server`、`exec-server` 都只是 core 的不同宿主（[agent-safehouse](https://agent-safehouse.dev/docs/agent-investigations/codex)）。

---

## 二、RepoPrompt CE：上下文工程与宿主编排的控制模式

### 2.1 倒转的 harness：MCP server 是主 agent

RepoPrompt CE 是 RepoPrompt 的开源社区版，一个 Swift 编写的原生 macOS 应用，自我定位是"native macOS context engineering app for AI coding agents, with an MCP CLI"（[GitHub](https://github.com/repoprompt/repoprompt-ce)）。它最有辨识度的设计决策，作者本人概括为一句话：**"inverting traditional harness design, making the MCP server the primary agent so that the underlying CLI harnesses can be swapped out or upgraded seamlessly"**（[RepoPrompt Blog](https://repoprompt.com/blog/repo-prompt-community-edition/)）。传统结构里，CLI agent（Claude Code、Codex 等）是主体，MCP server 只是它调用的工具；RepoPrompt CE 把这个关系倒过来——**app 内置的 `repoprompt-mcp` server 才是常驻的、有状态的"主"角色，各家 CLI agent 被降级为可替换的执行后端**。

这个倒转具体落在两个方向上。向外，`repoprompt-mcp` 作为 MCP server 向任何 MCP 兼容 agent 暴露仓库操作工具集：`context_builder` / `context_builder_wait`（异步上下文策展任务）、`file_search`、`get_file_tree`、`get_code_structure`、`read_file`（行切片）、`apply_edits`、`file_actions`、`manage_worktree`、`oracle_send` 等（[pi-repoprompt-mcp](https://pi.dev/packages/pi-repoprompt-mcp)，[danielraffel](https://danielraffel.me/til/2026/03/24/how-to-install-repoprompt-globally-in-claude-code/)）。向内，app 的 Agent Mode 作为宿主去编排 CLI agent 会话——支持 Claude Code 及 Claude 兼容族（GLM/Zai、Kimi、自定义）、Codex、Gemini、OpenCode、Cursor、Grok Build 等 provider，并能创建 app 托管的 git worktree（配合 `.worktreeinclude` 把 gitignore 的本地配置文件拷入新 worktree）做并行隔离（[GitHub](https://github.com/repoprompt/repoprompt-ce)，[worktrees.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/worktrees.md)）。同时它保留了"上下文车间"的老本行：**Context Builder 是一个三阶段流水线——discovery agent 探索代码库、在 token 预算（默认 60k）内迭代遴选文件与 CodeMap、产出结构化 prompt 交接给下游模型**，CodeMap 用约 1/10 的 token 提供函数/类型签名级的结构理解（[RepoPrompt Blog](https://repoprompt.com/blog/context-over-convenience)，[Ry Walker](https://rywalker.com/research/repo-prompt)）。

### 2.2 Provider 插件 seam：静态组合 + DTO 契约

RepoPrompt CE 控制"哪些 agent 可以被编排"的方式，是一个刻意不做动态加载的插件架构。核心 app 只持有一个 **provider 中立的运行时契约 `NativeAgentRuntimeControlling`**——一个 Actor 协议，方法面包括 `startOrResume`、`sendUserMessage`、`interruptTurn`、`respondToPermissionRequest`、`shutdown` 和一个 `AsyncStream<NativeAgentRuntimeEvent>` 事件流；provider 专属的协议编解码、环境构造、headless 参数拼装等纯逻辑被推进 SwiftPM 包（首个产品是 `RepoPromptClaudeCompatibleProvider`），包本身只依赖 Foundation，**绝不触碰 UserDefaults、Keychain 或权限存储**——秘密与持久化配置在 core 侧读取、消毒成 DTO 后通过闭包传入（[provider-plugins.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/architecture/provider-plugins.md)）。

core 与包之间有两层薄桥：`ClaudeCompatibleProviderRuntimeBridge` 是 core 里唯一 import 包的文件（类型别名 + DTO 双向转换 + 纯 helper 转发），`ClaudeCompatiblePluginBridge` 是 Agent Mode 面向的 facade（provider kind 映射、可用性、runtime config 构造）（[provider-plugins.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/architecture/provider-plugins.md)）。接入新 provider 的配方把 runtime 分成三种形态：**交互式原生 CLI**（实现 `NativeAgentRuntimeControlling`，如 Claude SDK 的 NDJSON 流）、**headless CLI**（一次性进程调用）、**ACP**（Agent Client Protocol，OpenCode/Cursor/Grok Build 走这条路）（[provider-plugins.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/architecture/provider-plugins.md)）。这个"契约在 core、编解码在包、持久化永不下放"的三权分立，是三者中最接近操作系统微内核味道的设计。

---

## 三、LoopX：跨会话控制平面的控制模式

### 3.1 状态内核：控制状态与会话上下文彻底分离

LoopX 的自我定义是"**provider-neutral 的有状态控制平面（control plane）**"：它跑在 Codex、Claude Code、Cursor 等 harness 之上而不替换它们，负责让跨越数天、数次重启、多个 agent 之间交接的长时程工作保持可审查、可重启、可交接（[GitHub](https://github.com/huangruiteng/loopx)）。它的出发点是一个诊断：agent 能在一个会话里完成任务，但长时程工作难在别处——目标会漂移、业主决策会出现、证据会过期、agent 之间要交接、调度器会在没有有用进展时继续烧钱；**聊天记忆加定时器不足以治理这些**（[GitHub](https://github.com/huangruiteng/loopx)）。

LoopX 的答案是六个持久层：Registry（已知 goal 及其 repo/adapter/authority）、Goal state（单个 goal 的活动状态文件）、Run log、Run history（供 agent/heartbeat/UI 消费的紧凑索引）、Status/attention queue（谁该行动的的首屏摘要）、Compute quota（每个 goal 可消耗多少自动算力）（[architecture.md](https://github.com/huangruiteng/loopx/blob/main/docs/architecture.md)）。围绕这些状态，运行时职责被切成四个角色：**Agent**（规划并执行一个有界动作）、**Provider**（调用外部系统并返回观察与回执）、**Capability**（定义调用方结果契约、归一化并校验 provider 输出、提出带类型的状态迁移）、**Kernel**（独占 durable todo/gate/monitor/writeback/quota/恢复/调度）；执行路径是 `Agent → Capability → Provider`，控制路径反向回流 `Provider readback → Capability transition → Kernel`——**agent 永远不直接写入治理它自己的状态**，这是整个设计的题眼（[architecture.md](https://github.com/huangruiteng/loopx/blob/main/docs/architecture.md)，[moclaw](https://moclaw.ai/blog/what-is-loopx)）。协作模型上，注册的 agent 互为 peer，没有持久 leader，claim、lease、任务边界和带类型的 continuation 决定下一个行动者是谁（[GitHub](https://github.com/huangruiteng/loopx)）。

### 3.2 确定性裁决与事件溯源方向

LoopX 控制模式最锋利的一刀，是**把"要不要跑下一轮"的裁决交给纯代码而不是 LLM**：每次唤醒先跑硬编码逻辑裁定本轮应该开工、等待授权还是安静休眠；理由非常务实——在"是否执行"的关键路径上调用模型，既引入成本与延迟，也让调度面临模型漂移与 prompt 注入导致失控的风险（[yage.ai](https://yage.ai/share/loopx-long-horizon-control-plane-en-20260805.html)，[state-interaction-model.md](https://github.com/huangruiteng/loopx/blob/main/docs/state-interaction-model.md)）。这个裁决的入口是一个命令：`loopx quota should-run`，其输出是机器可读的 `interaction_contract`；整个 tick 只有五个命令——`quota should-run` → `todo claim` → `todo update` → `refresh-state` → `quota spend-slot`——其余一切（预设、能力包、dashboard）都架在这五个原语之上（[moclaw](https://moclaw.ai/blog/what-is-loopx)，[explainx](https://explainx.ai/blog/loopx-agent-control-plane-loop-engineering-august-2026)）。裁决流水线本身分阶段：先解析 goal 与 agent 身份（失败即 fail closed），再构造 goal 边界（写权限、authority、spawn 策略），然后归一化 user gate、应用 outcome floor 与 self-repair 规则，最后过 capability gate（[quota 决策内核](https://github.com/huangruiteng/loopx/blob/main/docs/development/control-plane-course/04-quota-decision-kernel.md)）。

与 Codex 把会话历史当状态的做法相对照，LoopX 明确走向**事件溯源**：紧凑 run index 加上 reward/quota overlay 构成 append-only 事件账本，当前状态是事件之上的确定性投影，聊天线程、浏览器筛选、本地工具输出都不是 durable 真相（[state-interaction-model.md](https://github.com/huangruiteng/loopx/blob/main/docs/state-interaction-model.md)）。它还给出了一份清醒的自我边界声明：LoopX 不授予凭据、不批准破坏性/生产动作、不代用户发布、不把未验证的运行当成成功证据（[GitHub](https://github.com/huangruiteng/loopx)）。对宿主集成深度，它定义了三档适配——`in_loop`（worker 在自己循环内调 LoopX API）、`wrapper`（LoopX 包裹 worker 的启动与环境但不动其内部循环）、`passive_posthoc`（只能事后检查 diff/log/artifact 并归约为事件）——并坚持三档共享同一条不变量：**无论 agent loop 是否配合，控制平面都在 loop 之外产出并校验控制上下文**（[state-interaction-model.md](https://github.com/huangruiteng/loopx/blob/main/docs/state-interaction-model.md)）。

---

## 四、三者关系：同一思想的三个正交层次

把三家摆在一起，最准确的关系表述不是"竞品"而是"**栈**"。Codex 的控制对象是**一次 turn 之内**的模型-工具循环；RepoPrompt CE 的控制对象是**一个任务会话**的上下文组装与执行后端选择；LoopX 的控制对象是**一个目标跨无数次 turn 与多个会话**的生命周期。时间尺度从秒级到周级，控制强度（对 agent 行为的约束硬度）则反过来递增：Codex 的约束主要是沙箱与审批（工具粒度），RepoPrompt CE 的约束是 token 预算与上下文边界（信息粒度），LoopX 的约束是 quota、gate、lease（状态迁移粒度）。

![三者关系：三个正交控制层次](images/fig1_三层关系.png)

更深的共性是，**三者都在做同一个架构动作：把控制从执行中拆出来，只是拆的位置不同**。Codex 把 agent loop 从 UI 拆出来（core crate + App Server），于是同一 harness 能驱动四种界面（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)）；RepoPrompt CE 把上下文与编排从 CLI harness 拆出来（MCP server 为主、provider 插件 seam），于是执行后端可以热替换（[RepoPrompt Blog](https://repoprompt.com/blog/repo-prompt-community-edition/)）；LoopX 把 durable 状态从会话上下文拆出来（内核独占账本），于是 agent 会话本身变成可替换的临时工（[architecture.md](https://github.com/huangruiteng/loopx/blob/main/docs/architecture.md)）。实际生态里它们也确实这样嵌套：LoopX 官方集成表把 Codex App、Codex CLI 列为被驱动宿主（[GitHub](https://github.com/huangruiteng/loopx)）；RepoPrompt CE 的 provider 列表里 Codex 是可编排后端之一（[provider-plugins.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/architecture/provider-plugins.md)）；而 Codex 自己又以 ACP agent 身份出现在 Zed/JetBrains 系编辑器里（[robofang ACP 概览](https://github.com/sandraschi/robofang/blob/main/docs/zed/ACP_OVERVIEW.md)）。

| 维度 | Codex | RepoPrompt CE | LoopX |
|---|---|---|---|
| 控制对象 | turn 内的推理-工具循环 | 会话的上下文与执行后端 | 跨会话的目标生命周期 |
| 时间尺度 | 秒–分钟 | 分钟–小时 | 小时–周 |
| 状态真相 | 对话历史（append-only prompt + SQLite 持久化 thread） | app 内工作区/选择状态 + MCP 会话 | append-only 事件账本（`.loopx/`） |
| 核心原语 | Item / Turn / Thread（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)） | context / codemap / worktree / provider session | goal / todo / gate / evidence / quota |
| 关键裁决 | 模型自主（loop 内），人审在工具边界（approval） | 人 + 预算约束在上下文边界 | **纯代码裁决在 turn 边界**（不经 LLM） |
| 安全模型 | sandbox policy × approval policy 正交（[3LS](https://www.threelawssecurity.com/resources/blog/agent-sandboxes-deep-dive/)） | provider 权限文档 + MCP 工具白名单；包不碰秘密 | 写权限边界 + capability gate + fail closed |
| 扩展机制 | MCP 工具、skills、hooks | 静态 SwiftPM provider 包 + DTO 契约 | capability / provider / extension 三层分离 |
| 进程模型 | core 库 + 多宿主（TUI/exec/app-server） | 原生 app + 内嵌 MCP server + conductor 构建守护 | 本地 CLI/内核 + 可选 loopback 协调器（路线图） |
| 对外协议 | App Server（双向 JSON-RPC）、MCP server（降级）、ACP agent | MCP server（主）+ ACP client | CLI + hook/MCP 适配面（v0 契约） |
| 技术栈 | Rust | Swift（macOS 26+） | Python 零依赖 + TypeScript Effect 内核 |
| 明文拒绝 | MCP 承载富 UI 会话（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)） | 动态插件加载 | 自主生产写、凭据授予、代发布（[GitHub](https://github.com/huangruiteng/loopx)） |

## 五、融合设计：一个内核，三个能力平面

### 5.1 先想清楚：三者各有什么是别人没有的

融合的前提不是把三个仓库的代码缝在一起——语言栈（Rust/Swift/Python）和进程模型根本不兼容——而是**把三套设计里各自独占的机制抽出来，在同一份状态真相上重实现一遍**。逐个盘问之后，每个项目只有一块是不可替代的：Codex 不可替代的是**有界 turn 的执行语义**——模型自主循环在 turn 内跑，但 turn 的边界清晰（assistant message 终止），沙箱与审批正交，prompt 装配与缓存纪律严明（[OpenAI](https://openai.com/index/unrolling-the-codex-agent-loop/)）。RepoPrompt CE 不可替代的是**上下文作为一等公民**——CodeMap、文件切片、token 预算内的迭代策展，加上 provider 插件 seam 带来的执行后端可替换性（[provider-plugins.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/architecture/provider-plugins.md)）。LoopX 不可替代的是**跨 turn 的确定性治理**——quota should-run 的纯代码裁决、goal/gate/evidence 的持久账本、fail closed 的边界（[quota 决策内核](https://github.com/huangruiteng/loopx/blob/main/docs/development/control-plane-course/04-quota-decision-kernel.md)）。

反过来说，三者之间大量的"重叠"其实是不必要的三套：三套会话状态（Codex 的 thread、RepoPrompt 的 Agent Mode tab、LoopX 的 goal/todo）、三套权限/审批（Codex approval、RepoPrompt 的 MCP 权限文档、LoopX 的 user gate）、三套调度（Codex turn 循环、RepoPrompt 的 Agent Mode 编排、LoopX 的 heartbeat）。**"合成一个整体"的本质，就是把这三组"三套"各合并成一套**：一份账本同时承载 thread 事件与 goal 事件；一个权限模型同时表达工具审批与人审 gate；一个调度循环同时处理"turn 内下一步调哪个工具"和"跨 turn 要不要唤醒"。

### 5.2 目标架构：四层一单内核

![融合架构：一个本地内核，三个能力平面](images/fig2_融合架构.png)

融合系统的形态是**一个本地长驻进程（daemon）+ 一个原生 UI 壳**，内部分四层。**L0 存储内核**是唯一状态真相：一个 append-only 事件账本（SQLite 起步即可），goal、thread、todo、gate、quota、证据、审批全部作为事件入账；当前状态一律是事件之上的确定性投影，聊天历史只是执行上下文而非控制上下文——这条不变量直接搬 LoopX 的事件溯源契约（[state-interaction-model.md](https://github.com/huangruiteng/loopx/blob/main/docs/state-interaction-model.md)），同时吸收 Codex 的 thread 持久化做法（thread 可恢复、可 fork、可归档）（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)）。在统一账本里，**Codex 的 Thread 降级为 Goal 下的一个投影**：一个 goal 可以挂多个 thread（多次有界执行），thread 的 item 事件与 goal 的 gate/quota 事件进同一个 append-only 流，按 goal_id 分区。

**L1 控制平面**跑两个确定性组件。其一是**裁决器**：每次唤醒先过纯代码的 should-run 判定（身份解析 → 边界构造 → gate 归一化 → capability 过滤），输出带类型的 turn 许可（deliver / wait / ask / repair / quiet），全程不调 LLM——这是 LoopX 最核心的防御性设计，直接继承（[quota 决策内核](https://github.com/huangruiteng/loopx/blob/main/docs/development/control-plane-course/04-quota-decision-kernel.md)）。其二是**上下文策展器**：把 RepoPrompt 的 Context Builder 从"一个 MCP 工具"升级为内核的一等服务——裁决器放行一个 turn 时，策展器在 token 预算内组装该 turn 的初始上下文（相关文件切片 + CodeMap + 近期事件摘要），这正是 Codex 初始 prompt 装配层（AGENTS.md 链 + environment_context）与 RepoPrompt 上下文工程的合流。**调度**也在这里统一：turn 内的"下一步"由执行平面的模型循环决定，turn 之间的"下一轮"由裁决器决定，两者共用一个 quota 账本，避免 LoopX 心跳与实际执行各记各的账。

**L2 执行平面**是可替换的 turn 引擎。内置一个自研的最小 agent loop（模型推理 ⇄ 工具调用，append-only prompt、prefix 缓存纪律、自动压缩——照抄 Codex 的公开工程结论），工具执行走 **sandbox policy × approval policy 正交**双层（macOS 上直接用 Seatbelt，与 Codex 相同原语）（[danielvaughan](https://codex.danielvaughan.com/2026/05/03/codex-cli-sandbox-internals-seatbelt-bubblewrap-landlock-windows-dacl/)）。同时保留 RepoPrompt 的 provider seam：外部 CLI agent（Claude Code、Codex 本体、其他 ACP agent）以 provider 插件形式挂入，契约就是 `NativeAgentRuntimeControlling` 的三个形态——原生 SDK 流、headless 进程、ACP——这样你的系统既能在没有外部 CLI 时独立工作，也能在用户已有订阅时把外部 agent 当执行后端（[provider-plugins.md](https://github.com/repoprompt/repoprompt-ce/blob/main/docs/architecture/provider-plugins.md)）。关键纪律照抄：**持久化与秘密永不下放插件包**，core 读取后消毒成 DTO 传入。

**L3 接口平面**是三个协议出口，各管一件事、互不越界：**原生 UI 壳**（SwiftUI/TUI）订阅内核事件流，渲染看板、diff、审批卡片——它只是投影的消费者，不是状态所有者（LoopX 的 dashboard 原则）；**MCP server 出口**只暴露"工具面"（文件/搜索/codemap/上下文策展结果），供外部 agent 把你当工具用——这是 RepoPrompt 的倒转设计，但要记住 Codex 的教训：**MCP 适合工具供给，不适合富会话控制**（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)）；**会话协议出口**用双向 JSON-RPC（Item/Turn/Thread 三原语 + server 主动发起审批请求），供 IDE、远端 UI、自动化系统完整驱动你的 agent——可以直接对齐 Codex App Server 的消息模型，或以 ACP 兼容换取 Zed/JetBrains 生态的免费入口（[robofang ACP 概览](https://github.com/sandraschi/robofang/blob/main/docs/zed/ACP_OVERVIEW.md)）。

### 5.3 机制合并对照：谁出什么

| 融合系统的机制 | 主要吸收自 | 吸收什么 | 需要改什么 |
|---|---|---|---|
| 事件账本 | LoopX | append-only、投影、幂等写入、隐私分区 | 把 Codex 的 thread/item 事件纳入同一账本，goal_id 分区 |
| 确定性裁决器 | LoopX | quota should-run 五阶段流水线、fail closed | 裁决输出直接对接内置 turn 引擎，而非外部 CLI |
| Turn 引擎 | Codex | 模型⇄工具 while 循环、assistant message 终止态 | 上下文不自己拼，向策展器请求 |
| Prompt 装配与缓存纪律 | Codex | 静态前缀在前、变更以追加消息表达、自动压缩 | 压缩产物（摘要）同时作为事件入账，跨会话可用 |
| 沙箱×审批正交 | Codex | policy 与 enforcement 分离、OS 原语强制 | 审批请求统一路由到 L1 的 user gate，而非 turn 内自决 |
| 上下文策展 | RepoPrompt CE | CodeMap、文件切片、token 预算迭代遴选 | 从 MCP 工具升级为内核服务，预算由 quota 账本统一记账 |
| Provider 插件 seam | RepoPrompt CE | 契约在 core、编解码在包、DTO 桥、三 runtime 形态 | 插件包产出的事件也必须走 L0 账本，不允许旁路 |
| 宿主编排 | RepoPrompt CE | worktree 隔离、`.worktreeinclude`、多根工作区 | worktree 的创建/回收由裁决器按 lease 触发，而非 UI 手动 |
| Peer 协作 | LoopX | claim/lease、无持久 leader、typed continuation | lease 与 Codex 式 thread fork 对齐：fork 即新 lease |
| 协议出口分工 | 三者教训的并集 | MCP=工具、JSON-RPC=会话、ACP=编辑器生态 | 三个出口共享同一会话原语模型，避免协议间语义漂移 |

### 5.4 关键决策点与反模式

融合路上最大的诱惑是**让协议边界渗化**——比如图省事用 MCP 同时承载工具调用和会话控制。Codex 团队已经替你试过这条路并公开了失败结论：MCP 的 request/response 工具语义装不下流式 diff、审批中断、thread 持久化这些富会话语义（[OpenAI](https://openai.com/index/unlocking-the-codex-harness/)）。所以接口平面必须坚持"**MCP 管工具、JSON-RPC/ACP 管会话、UI 只管投影**"的三不混。第二个反模式是**双账本**：LoopX 模式若被原样嫁接到一个已有 thread 存储的系统上，很容易出现"goal 状态说 A、会话历史说 B"的分裂；解法就是 5.2 的单账本——thread 事件与 goal 事件同源，分歧在写入时就被幂等键与 CAS 挡掉（LoopX 的 server 化路线图同样把"per-goal 锁、幂等键、乐观版本检查"列为前置条件）（[architecture.md](https://github.com/huangruiteng/loopx/blob/main/docs/architecture.md)）。

第三个决策点是**裁决器与模型的边界画在哪**。LoopX 的原则值得整体继承：热路径（是否执行、是否放行、是否超支）零 LLM，LLM 只出现在冷路径提案 lane（比如建议新增 todo 或修订 gate），且提案必须经确定性晋升步骤才能入账（[state-interaction-model.md](https://github.com/huangruiteng/loopx/blob/main/docs/state-interaction-model.md)）。第四个决策点是**技术栈**：若目标平台锁定 macOS，Swift 全栈（RepoPrompt 路线）能拿到最好的原生体验和 Seatbelt 集成，代价是跨平台重来；若想要跨平台内核 + 各平台原生壳，Rust 内核（Codex 路线）加薄 UI 是更稳的选择——注意 RepoPrompt 的 provider seam 证明了一件事：**只要契约是 DTO 化的、持久化不下放，宿主语言与插件语言的差异可以被隔离在桥层**。最后，LoopX 的三档适配深度（in_loop / wrapper / passive_posthoc）应当成为你对接一切外部执行体的通用分级：内置引擎走 in_loop，外部 CLI 走 wrapper，不可控的远端 agent 走 passive_posthoc，三档共享同一条"证据校验后才能入账"的不变量（[state-interaction-model.md](https://github.com/huangruiteng/loopx/blob/main/docs/state-interaction-model.md)）。

### 5.5 落地路线建议

建议按"先账本、后裁决、再执行、最后界面"的顺序推进，每一步都保持系统可用。第一步只做 L0：事件账本 + 最小投影（goal/todo/thread 三个投影器），用一个命令行工具把任何手工操作也作为事件写入，先验证幂等与回放。第二步加 L1 裁决器：should-run 判定 + quota 账本，此时还没有自动执行，裁决结果只是"建议人做什么"——这正好对应 LoopX 早期"agent 是黑盒也有价值"的 passive 档。第三步实现 L2 内置 turn 引擎（单模型、shell/文件两类工具、Seatbelt 沙箱、审批走 L1 的 user gate），并同时把上下文策展器接进 prompt 装配。第四步加 provider seam 与第一个外部 CLI 后端，验证"同一 goal 可以在内置引擎与外部 CLI 之间交接"——这是整个融合设计的试金石：**如果同一份事件账本能让两个不同执行体无缝接力一个目标，三套系统就真正合成了一套**。第五步再做原生 UI 与两个协议出口，并把 worktree 编排、peer lease 作为增量能力叠上去。

---

## 结语

Codex、RepoPrompt CE、LoopX 分别证明了三件事：**turn 可以被工程化成可靠的有界执行单元**（Codex），**上下文与会话宿主可以从执行后端中解放出来**（RepoPrompt CE），**跨会话的治理可以交给确定性代码而不是聊天记忆**（LoopX）。你的本地原生 agent 系统不需要三选一，也不应该三拼装——它需要的是承认这三个结论作用于同一台机器上的同一个 agent，然后用**一份事件账本、一个确定性裁决器、一个可替换执行平面、三个各司其职的协议出口**把它们落成单一架构。三者真正的关系，是一张设计图的三个局部；你要做的是把整张图画完。
