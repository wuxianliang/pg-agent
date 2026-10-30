# v14 对标 pi 差距调查（v14-pi-parity-gap-investigation-2026-09-28）

> 目标：为 v14（功能对标 pi 的 coding agent）定差距。回答三个问题：**运行时还需不需要进一步开发？工具上还要开发什么？一般 harness 还要开发什么？**
>
> 调查方式：两轮 in-tab Context Builder + Oracle 盘点（一轮盘 pi 功能面，一轮盘 pg-agent 现状），素材为两份 oracle 导出（gitignored `prompt-exports/`，见附录）。承重结论已抽查核验：`v13/load.py`（29 stage）、`v13/read_tools/README.md`（4 口岸 + options 闭合）、`pi/packages/coding-agent/src/core/tools/index.ts`（`ToolName` 8 件）、`.gitignore`（demo 树不入库）。

---

## 0. 结论摘要

**pg-agent 已经有一个相当完整的 Postgres-native agent 控制面，但还不是 coding agent 产品。** 距离 pi 最大的缺口不在数据库状态机，而在用户可直接使用的执行层与产品层。

三个问题的一句话答案：

| 问题 | 答案 |
|---|---|
| 运行时还要不要开发？ | **不要重做，要接线。** 循环/状态机/恢复/取消/spawn/fork/quota 全部已交付有 gate（v13 stage 1–29）；缺的是 tracked driver、用户会话入口、生成 provider 接口三件产品接线件 |
| 工具要开发什么？ | **缺口最大的一桶。** 现有 4 个只读口岸且 options 闭合到夹具；edit/write/bash/grep/find/ls 全部空白，工作区自由路径 read 也没有。这是 v14 的第一刀 |
| 一般 harness 要开发什么？ | 非交互 CLI（print/json）、会话 resume/fork 产品语义、系统提示组装与项目说明文件消费、工具前拒绝钩子、单库加载故事；TUI/skills/扩展/多 provider 可分期 |

---

## 1. 对标口径

- **对标层 = `pi/packages/coding-agent` + 它调用的 `packages/agent` 的 `Agent`/`agent-loop` + `packages/ai`。** 版本 0.87.1，入口 `pi` CLI。
- **不算对标面**：`packages/agent/src/harness/**`（pico3 重构中，自述未投产）；示例扩展（subagent、permission-gate 是示例不是内置）；npm 发行/主题/50 键位/自更新/分享渠道等运营件。
- **不必一次做齐**：42 个 provider 工厂、8 家 OAuth——一个 OpenAI 兼容端点 + 2~3 家原生协议即可覆盖对标，其余是 catalog 劳动。
- pi 生产路径**没有内置 subagent 工具**（在 `examples/extensions/subagent/`）；pg-agent 的 spawn 是库内原语，**已强于该示例**。

## 2. pi 功能面速览（参照物）

| 域 | 已交付 | 位置 |
|---|---|---|
| 内置工具 | read/bash/edit/write 默认开；grep/find/ls/powershell 默认可选关 | `coding-agent/src/core/tools/` |
| Agent 回路 | 多 turn、流式、tool 批执行（顺序/并行）、steering、follow-up、abort、terminate | `agent/src/agent-loop.ts`、`agent.ts`；编排在 `core/agent-session.ts`（约 4000 行） |
| 压缩 | 阈值自动压缩、`/compact`、overflow/length 一次恢复、分支摘要、context_edit | `core/compaction/` |
| 会话 | JSONL 树、resume/fork/clone/tree、导出 | `core/session-manager.ts` |
| Provider | 42 工厂、catalog、api_key/oauth、`models.json` 兼容端点 | `packages/ai`，包装在 `core/model-runtime.ts` |
| 扩展生态 | ExtensionAPI（约 30 事件）、skills、prompt templates、packages、context files | `core/extensions/`、`core/skills.ts` |
| 交互面 | TUI/print/JSONL/RPC/SDK；24 个内置 slash 命令 | `src/cli/`、`src/modes/`、`core/sdk.ts` |
| 安全 | project trust 闸**项目资源加载**；工具按进程 OS 权限直接执行（无逐工具审批） | `core/trust-manager.ts` |

工具层关键细节（v14 规格参照）：edit 的 `oldText` 必须在**原文件**中唯一且互不重叠；bash 有超时与尾部截断并落 `fullOutputPath`；大输出截断（2000 行/50KiB）；文件变更经 `withFileMutationQueue` 串行化；`--tools` 白名单/黑名单/全关。

## 3. pg-agent 现状（成熟度：① 已交付有 gate / ② 有方案或原语未接线 / ③ 纯空白）

| 域 | 现状 | 成熟度 |
|---|---|---|
| 回路状态机 | `v13_advance` 五步（终态/新鲜度/预算/判断/路由）、effect enqueue/claim/complete、fence/lease、恢复与幂等、unknown 墙、cancel、spawn/fork/goal tree、quota、should_run、attention、govern——stage 1–29 共 85 项矩阵覆盖，30 脚本全绿 | ① |
| 判断面 | Jev/TypeSafe 判断（缓存、信封、模板、路由、预算），OpenRouter `/api/alpha/decisions` 实测打通 | ① |
| 上下文面 | manifest/chunks/recall/characterize/filter/memory/economy/summary/mgraph(+assembly)：freeze、召回、经济压力、summary effect、belt 守卫、exact replay | ①（数据库链） |
| 会话持久化 | PG 行即真相：sessions/events（append-only 无洞 seq）/effects/decisions/artifacts；fork 走 parent/cutoff/provenance | ① |
| 工具口岸 | 4 个只读口岸：`read_pi`（对照 Pi 0.80.3 截断语义）、`read_file_swift`、`read_file_py`、`read_duck`（DuckDB AST 渲染）；退出码闭集、realpath 围栏、完整单帧、TP-INV/TP-WIRE/TP-FS/TP-HUB 合同 | ①（但 options 闭合到 `hello.txt`/`crlf.txt`/`fib.py` 夹具） |
| Provider | DeepSeek 生成适配器活在 `v8/loop/runtime.py` + demo shim；判断一条 Jev 路径；gate 全走 Fake | ①单点 / ③接口 |
| 驱动器 | parse→advance→claim→IO→complete 回路设计在 `docs/plans/v13-minimal-agent-loop-demo-2026-09-23.md` 与 B2 计划，落在 gitignored demo 树 | ② |
| 交互面 | v6 Streamlit workbench（①）；v13 Chainlit/PostgREST demo（② gitignored）；无 CLI/TUI/print/JSON/RPC/SDK/slash | ③（产品层） |
| 安全 | 双登录角色、NOLOGIN 平面、SECURITY DEFINER 窄函数、actor/亲缘 ACL（stage 23）、v8 RLS 线、unknown 墙、工具协议围栏、外部 IO 事务隔离 | ①（SQL 合同）/②（driver 传 actor） |

## 4. 差距分析

### 4.1 运行时：需要开发，但都是「接线」不是「重做」

**不需要**：再造 agent 循环或第二套 `v13_agent_run(op)`——这是路线图红线（`docs/plans/v13-layered-control-roadmap-2026-09-26.md`）；把 PG 行换成 JSONL 第二真相；v8 P0C 真实 DSH host（C2–C6）作为前置——已裁与控制动词正交。

**需要开发（按序）**：

| 项 | 内容 | 现状 |
|---|---|---|
| R1 tracked driver/hub | 仓库内可安装、面向用户的驱动器：`parse → advance → claim → 外部 IO → complete → 再 parse` 循环包装 | ②（demo 有、仓库无） |
| R2 用户 ingress | 稳定的会话开启/消息追加命令。`v13_open_session` + `v13_append_event` 原语已够，缺的是产品函数而不是新表 | 原语① / 产品③ |
| R3 生成 provider 接口 | 至少 DeepSeek 迁到统一接口；v13 建目录；凭据只留进程外、缺 key 在开口前拒绝（禁止 key 进 effect.request） | ①单点脚本 / ③接口 |
| R4 steering/abort 产品语义 | 当前 turn steering 队列、follow-up 队列、abort 后队列还给编辑器。SQL 侧 cancel/goal stop 已 ①，产品行为未接 | ② |
| R5 compaction 自动接线 | driver 在新用户消息前/工具结果后触发（已有 summary/economy 内核）；**已知坑：B2 demo 生成提示不消费 manifest**，接线时必须让模型看到 manifest 与自己的编辑 | 内核① / 接线② |
| R6 overflow 一次恢复 | provider 报超窗时压缩并重试一轮，避免死循环；**不变量：tool result 不与 tool call 拆开** | ③ |

**保留不改**：PG 行即真相、fence/lease、unknown 墙、spawn 席位、should_run/quota/attention、判断与生成分离、记忆图（质量债另计）。

### 4.2 工具：v14 的第一刀，缺口最大

pi 参照 8 件：`read | bash | powershell | edit | write | grep | find | ls`。pg-agent 实际只有 read 类（且闭合）。

| 项 | 要点 | 现状 |
|---|---|---|
| 工作区 read | 放开 `param_spec.options` 闭合为自由相对路径，保持 realpath 围栏与截断语义；**须 bump `v13/tool-port-contract-1`** | ①夹具读 / ③工作区读 |
| edit | `oldText` 原文件唯一匹配、重叠拒绝、返回 diff/patch/firstChangedLine | ③ |
| write | 创建/覆盖、mkdir 父目录 | ③ |
| bash | 有界超时、尾部截断+完整输出可再读、取消信号；**外部 IO 在 claim 已提交、complete 未开之间执行，不进事务**（不变量 4） | ③ |
| grep / find / ls | 正则/字面量、glob、列目录；可后于 bash/edit，仍属工具里程碑 | ③ |
| 大输出截断 | 行数与字节上限，告诉模型剩余内容在哪（pi：2000 行/50KiB） | ③ |
| 文件变更互斥 | 同一文件读-改-写不并发交错（pi `withFileMutationQueue` 等价） | ③ |
| 工具开关 | 白名单/黑名单/关内置/全关 | ③ |
| 权限闸接线 | 写/执行工具走现有 `human|reject` 路由（`risk_veto`、低置信、`tool_unavailable` 已是出口）。**不要抄 pi「进程 OS 权限即执行」** | 出口① / 接新工具③ |
| powershell / 图片 read / mermaid | 平台与体验项，可选 | ③ |

配套纪律：新口岸行为变更必须 bump 合同版本；新 stage 只许末尾追加 `SQL_LOAD_ORDER`；效果=写工具落地后若仍不吃 manifest，模型看不到自己的编辑（见 R5）。

**容易误判的四种「工具」**（不能混为一谈）：v13 `kind='tool'` 口岸（真工具目录行）、v8 tools seal（调用账本）、v6 `wb_duck_*`（分析工作台）、v5 named tools（prompt assembly）。后三者都不是 pi coding tool。

### 4.3 一般 harness

**必须**：

| 项 | 说明 | 现状 |
|---|---|---|
| 非交互 CLI | print（一 prompt 进、最终文本出、退出码）+ json 事件流两种模式，够脚本与子进程用 | ③ |
| 会话产品语义 | `--continue`/`--resume`、`/fork` 等入口。**PG 行仍是权威**，做 projection/export，不换 JSONL | 底层① / 入口③ |
| 系统提示组装 | 基础提示 + 工具说明 + cwd + 可追加片段；工具集变化模型要看得见；消费 `AGENTS.md`/`CLAUDE.md` 项目说明文件（沿目录生效） | ③ |
| 单库加载故事 | 现在三条栈并存：读工具停在 seam、控制面在 govern、demo 停在 envelope/mgraph_assembly。v14 须声明哪个前缀是产品库 | 待裁 |
| 会话导出 | handoff 四键信封是控制收据不是导出；缺 JSONL/Markdown 级正文导出（hash 已有） | ①合同 / ③产品 |

**可选（分期）**：最小 CLI slash 集（`/resume` 的 SQL 版、`/compact` 触发已有 summary schedule）；第二三家 OpenAI 兼容端；thinking 等级；流式 token（demo 明确不做，v8 G9a/G9b 可参考）；spawn 暴露成用户可见子代理（缺 markdown agent 定义与产品开关）；skills + prompt templates（v5 slot 能撑一段）；薄扩展（注册 tool handler + 阻断一次 tool_call 的最小事件子集）；TUI（选择器、diff 渲染、footer 用量）；会话树 UI；cache warming；遥测。

**不需要**：pico3/harness 复刻、chord/durable/CBOR protocol（不能证明在主路径）、40 provider 全家桶、npm workspaces/`pi install`/主题/50 键位、逐工具审批弹窗（pi 也没有；pg-agent 用路由 human/reject）、LoopX 26 表/outbox/leases、quota 账本表（`quota/spent`、`quota/voided`）、pi 示例级 subagent。

## 5. 建议 v14 范围切分与建设顺序

- **P0（产品闭环）**：bump 口岸合同 → 工作区 read + edit/write/bash（截断/互斥/超时）→ 生成 provider 接口（DeepSeek 先迁）→ tracked driver → 会话入口 + print 模式 → human|reject 接到新工具 → 单库加载声明 + gate。
- **P1（可恢复长会话）**：compaction 自动接线（含 manifest 消费修复）+ overflow 一次恢复 + usage 统计 + steering/abort 产品语义 + grep/find/ls。
- **P2（可扩展）**：最小扩展钩子 + skills + prompt 模板 + slash 命令集 + 会话导出。
- **P3（pi 式工作流与生态）**：会话树/fork 入口、JSON 流完整化、子代理产品开关、多 provider、TUI 完整度。

## 6. 已裁残留与风险（不阻塞开工，影响生产接线）

| 残留 | 状态 |
|---|---|
| F28 actor：驱动器未在 agent 路径传 actor | 合同① / 生产② |
| R4 第四务真 worker：假 worker ① / 实跑 gitignored，不得写成已关闭 | ② |
| PC-5 hint/cron、L32 UI 停复：仅投影，禁止写成已调度/已可停复 | ①投影 |
| 读工具环与 stage 22–29 不在同一加载前缀 | 集成缝（即 §4.3 单库问题） |
| P0C 数字澄清：compat 当前 9 passed/11 blocked/9 partial/1 not_run，三结论均 False；**脚本绿 ≠ P0C 完成** | ② |
| economy(M1) 与 summary(M2) README 历史不一致 | 文档清理项 |
| D4–D6、D7–D16：**没有一条仍标「未裁决挡 v14 开工」**（D6 形状已冻结为台账 C2 两键；D7–D16 全部 R4/R5/R8 已裁） | 已闭合 |

## 7. 开放问题（需拍板）

1. **单库前缀**：v14 产品库选哪个加载前缀/如何合并三条栈？
2. **TUI vs CLI**：建议 print/json 先行、TUI 后置——是否同意？
3. **v6.1/sitting_duck 工作台与 v14 工具口岸的关系**：可能重叠，建议先定工具口岸再决定是否做工作台。
4. **subagent 产品化时机**：spawn 已强于 pi 示例，缺的是 agent 定义格式与产品开关。
5. **流式 token 是否进 v14**（现 demo 明确不做）。

---

## 附录：素材与证据

- pi 功能面盘点：`prompt-exports/oracle-question-2026-09-28-123137-v14-pi-c92457-c795.md`（1838 行，双 lane，含 §11 对标必须/可选/不需要全表；gitignored 本地素材）
- pg-agent 现状盘点：`prompt-exports/oracle-question-2026-09-28-125622-v14-pi-25eb21-1600.md`（1473 行；Oracle 1 完整含 §9 v14 清单，Oracle 2 尾部被 watchdog 截断但与 Oracle 1 §9 重叠；gitignored 本地素材）
- 关键核验：`v13/load.py`（STAGE_THROUGH 29 stage，末项 govern）、`v13/read_tools/README.md`（口岸合同 `v13/tool-port-contract-1`、options 闭合）、`pi/packages/coding-agent/src/core/tools/index.ts:95`（ToolName 8 件）、`.gitignore`（`prompt-exports/`、demo 树、`/memory`）
- 调查过程注记：agent_run 委派两次因 OpenCode ACP 通道证书故障（`unknown certificate verification error`）失败，改用 in-tab Context Builder Oracle 路径完成；结论经上述四处抽查与仓库文件一致。
