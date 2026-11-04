# v24 UI-chainlit — 可用 Agent 续作开发计划（M6–M10，2026-11-04）

> 状态：草案，待评审；尚未实施。
> 分支：`v24/ui-chainlit`（本地，不 push）。
> 基线：`a6ba59657c53d3cf1a7e00cc90aad80bf025f617`（M4 repair）。
> M5 状态：INCOMPLETE，当前工作树含未提交的 M5 改动与 3 个证据级 blocker。本计划不消费、不重标、不覆盖 M5 证据。
> 目标：把 v24 UI 从“可演示的 run 控制台”推进到“单用户、本地、可以完成真实编码任务的 agent”。
> 本文只是开发计划，不授权提交、推送、amend、切 main，也不授权修改 SQL；所有提交仍受 `AGENTS.md` 与协调者 review 约束。

---

## 0. 实施前的基线决定（必须先做）

当前 `v24/ui-chainlit` 工作树不是干净基线：M5 的未提交改动与未跟踪文件仍在。M6 若直接叠加，会把 M5 证据、M6 功能和验收记录混在一起，之后无法分离。实施前由协调者三选一：

| 选项 | 做法 | 评价 |
|---|---|---|
| A（推荐） | 先按 M5 的正式流程收尾：复审通过、按路径提交、保持不 push；M6 从该 commit 开始 | 历史最干净，但依赖 M5 复审 |
| B | 把 M5 冻结为历史 checkpoint，另建 worktree，从 `a6ba596` 加上“仅功能、不含证据”的 M5 补丁开始；M6 单独提交 | 可行，但必须逐路径核对补丁，禁止把 M5 证据文件带进来 |
| C | 在当前未提交树上直接做 M6 | 不推荐；M5/M6 无法分离，验收会失真 |

无论选哪个，M6 的第一个动作都是记录 `git status`、HEAD、以及 `v24/ui` 全量源码哈希；M6 的 gate receipt 必须能证明“只改了本计划授权的文件”。**不得**把 M6 的改动混入 M5 的 completion audit，也**不得**用 M6 的通过去替代 M5 的 3 个 blocker：

- `original52_pre_WI1_baseline_proof_lost`
- `WI1_preincident_PGDATA_logical_equality_unproven`
- `full_UI_acceptance_and_formal_M5_review_not_accepted`

这 3 项是证据/复审 blocker，不是功能缺口；M6 不会顺带修好它们。

---

## 1. 执行摘要

v24 的工具层已经接近 Pi：11 个工具、16 路并行工具批次、截断/spill、workspace 栅栏、技能按需加载、durable run/effect/journal。真正阻碍“日常使用”的不是工具数量，而是四件事：

1. **会话记忆是 3,950 字符的文本摘要**，只保留最近 6 个 run，工具结果不进入下一轮上下文；Pi 是完整 transcript + 自动 compaction。
2. **输出上限 512 tokens（含 reasoning），run 预算 24 步/24 次工具/20k tokens/10 分钟**；Pi 使用模型输出上限，没有这种硬步数上限。
3. **`stream:false`**，UI 只有一条静止的“生成中”，取消要等当前 provider call（最长 120 秒）。
4. **模型固定 `deepseek-flash`、供应商固定 DeepSeek、无 MCP/扩展 hook、会话只能靠不透明 token 恢复**。

本计划把这些拆成 5 个里程碑：

| 里程碑 | 主题 | 结果 |
|---|---|---|
| M6 | Limits & Policy v2 | 解锁 8k 输出、128 KiB body、128 步/400k tokens 预算；`finish_length` 不再直接判死 |
| M7 | Session Context v2 | 结构化 transcript、跨 run tool results、自动 compaction、token/context 计量、v1 迁移 |
| M8 | Streaming & Control | token 流、工具进度、真中断、有限重试、steer/follow-up 队列 |
| M9 | Model & Session Product | 模型/供应商选择、会话命名/列表/恢复/导出、real 模式可重启 |
| M10 | Tool UX, MCP & Acceptance | diff、@文件、prompt templates、技能发现、MCP 桥（可选）、浏览器/真实 provider 收尾 |

M6–M9 是“基础可用”范围；M10 是增强与收尾。完成 M9 后应能完成一次 20+ 轮、10+ 次工具调用、触发一次 compaction、重启后恢复、会话中换模型的真实任务。

---

## 2. 现状基线（代码证据）

### 2.1 已经具备的能力

| 能力 | 现状 | 证据 |
|---|---|---|
| 工具 | 11 个：`read write edit bash grep find ls` + `read_file file_search get_file_tree apply_edits` | `v24/ui/catalog.py`、`v24/ui/plugins/` |
| 并行工具 | 一个 model effect 最多 16 个 tool children，batch barrier | `v24/s4/README.md` C20、`v24/sql/48_loop.sql` |
| 工具输出 | 2000 行 / 32 KiB / 4 MiB spill；UI step 与 `model_text` 逐字节一致 | `v24/host/tool_results.py`、`v24/ui/render.py` |
| 技能 | 名称+描述常驻，模型按需读 `SKILL.md` | `v24/ui/catalog.py:159`、`v24/ui/skills/` |
| 单轮控制 | start/steer/cancel/respond、durable effect/journal、resume/replay | `v24/ui/control.py`、`v24/host/worker.py` |
| 会话 | `sessions.json` + `turns.jsonl`，32 会话回收，跨刷新恢复（fake） | `v24/ui/sessions.py`、`v24/ui/app.py` |
| 审计 | render secret 扫描、workspace 栅栏、toolset、SQL 权威 | `v24/ui/render.py`、`v24/ui/env.py`、`v24/s4/` |
| 真实入口 | DeepSeek adapter、preflight、空 scratch、`V24_UI_MODE=real` | `v24/ui/provider.py`、`v24/ui/real.py` |

### 2.2 关键缺口（按“能不能真用”排序）

| 缺口 | 现状 | 后果 |
|---|---|---|
| 会话记忆 | `history_block()` 只取最近 6 个 run；user ≤600、final ≤800 字符；总长 ≤3,950；无 tool 输出 | 2–3 轮后忘记读过/改过什么；长任务必断 |
| 上下文容量 | body 8,000（fake）/16,384（real）字节；run 20,000 tokens | 一个大 grep/read 就可能放不下；无法承载真实仓库 |
| 输出 | 512 tokens（含 reasoning）；`finish_reason=length` 直接 failure | 回答被截断；复杂改动无法一次完成 |
| 预算 | 24 steps / 24 tool calls / 10 min | 真实任务很容易超过 24 次工具 |
| 流式 | `stream:false`；`cl.Step` 只在 settle 后出现 | 看不到进度；取消要等 120 秒 provider call |
| 模型 | `MODEL = "deepseek-flash"` 固定；无 `/model` | 不能用更强/更便宜/本地模型 |
| 会话产品 | `/resume <run_id> <token>`；无名称、列表、export、fork | 会话难找、难分享、重启易丢 |
| 真实重启 | real 模式要求空 scratch；写入后重启 `workspace_not_empty` | 真实会话不能跨进程恢复 |
| 扩展 | 只有 2 个固定 tool artifact；无 hooks、commands、providers、MCP | 每加一个集成都要改代码 |
| 输入 | 纯文本；无 `@file`、图片、粘贴附件 | 编码/截图场景体验差 |
| 并发 | 单 executor；一次 120 秒 provider call 阻塞所有会话 | 多标签/多人不可用；个人 loopback 尚可 |
| 审批 | 无 per-call 审批；只有 workspace 栅栏 + toolset | 本地单用户可接受；Web 暴露前必须补 |

### 2.3 根因：三个契约

1. **run 级，不是 session 级。** 每个用户消息开一个新 run；`v24.start` 的 `messages` 只被 adapter 接受为 `system/user`；跨 run 只能靠 `history_block()`。`v24.host.deepseek._messages()` 对 `start/spawn` 只接受 `system|user`（`v24/host/deepseek.py:271-277`），而 `_history()` 能把本 run 的 assistant/tool 消息重放出来（`v24/host/worker.py:1194-1233`）。所以“完整 transcript 跨 run”在 adapter 合同上被卡住，不是 SQL 表结构卡住。
2. **演示期冻结的 adapter 合同。** `MODEL` 固定、`stream:false`、`MAX_COMPLETION_CAP=512`、`DEFAULT_RUN_BUDGET` 24/24/20k/600k。这些是当前 `v24/ui` 的显式选择，不是 v24 内核的不可变语义。
3. **插件 ABI 只覆盖 tool。** v24 的 v2 artifact 是 out-of-process、manifest 审批、SQL pin 的工具层；它没有 hooks、commands、providers、UI、MCP。Pi 的 extension 是进程内 TypeScript，能拦截 tool_call、compaction、provider、UI；两者不是同一层能力。

### 2.4 与 Pi 的关系

对齐 Pi 不等于把 TUI 搬进浏览器。要对齐的是 **agent 能力合同**：完整上下文、流式、可中断、可换模型、可恢复会话、可扩展工具。Pi 明确不内置 sub-agents / plan mode（README），也没有内置 per-call 审批（安全文档依赖 trust/容器）；这些不是 parity 项。v24 的 durable SQL 权威、effect journal、unknown wall、安装/fiber 生命周期是优势，不应为了“像 Pi”而换成进程内 session。

---

## 3. 目标

### 3.1 用户故事

1. 我在浏览器里让 agent 改一个真实仓库：它读文件、搜索、编辑、跑测试，20+ 轮后仍记得前面的决定和工具结果；上下文接近上限时自动 compaction，不需要我重开。
2. 我能看到 token 逐个出现；能随时停止；失败后能重试；运行中我发的“补充要求”和“下一件事”不会互相覆盖。
3. 我能在会话中换模型；关掉进程再打开，会话、工作区、模型都还在；能把会话导出成 Markdown/JSONL。
4. 我能用技能和 prompt template 定制工作流；后续可以接 MCP server，而不必为每个 server 改 v24 代码。

### 3.2 “基础可用”完成定义（DoD）

- 一次 20+ 轮、10+ 次工具调用的 fake 任务完成；工具结果跨 run 保留；触发至少一次自动 compaction；compaction 后可继续。
- 进程重启后 `/resume` 恢复同一会话、同一工作区、同一模型；fake 必达；real 在 M9 的“非空 scratch resume”例外获批后必达，否则 real resume 明确延后。
- 会话中 `/model` 切换成功；旧模型调用不串线；resume 恢复所选模型。
- 首 token 在本地 fake 下 <2 秒可见；`/cancel` 在 1 秒内发出传输层中断；最终状态以 run projection 为准，不出现重复 final。
- `finish_length` 不再让整轮无提示失败；部分输出可见、可继续。
- 导出 JSONL/Markdown；导出内容不含 API key/Authorization/DSN。
- 所有既有 gate 仍绿；新增 gate 全绿；真实 provider 仅作为 opt-in 手动验收，不作为 gate。

### 3.3 非目标（本计划不做）

- 多用户/SaaS、登录、租户隔离、配额计费；目标部署是**单用户、loopback**。
- TUI、键位、主题；Pi 的终端交互不照搬。
- 子代理、`agent.spawn`、plan mode；Pi 自己也没有内置。
- per-call 工具审批、沙箱容器；P0 用 workspace 栅栏 + toolset + loopback，M10 再评估。
- 后台 bash、PTY、PDF 输入；Pi 也没有后台 bash。
- 50 家 provider、OAuth 登录、virtual models；P0 只做 2 类 provider。
- 图片输入；P2。
- 会话树/tree/fork/clone；P1，先保留 `parent_id` 数据模型。
- 多 executor / 多用户并发；P2。

---

## 4. 设计原则

1. **Session 是上下文单位，run 是回合单位。** 不把 run 当会话；不把完整历史塞进 system prompt 的文本块。
2. **流式是临时的，durable outcome 是权威的。** delta 不写 SQL；最终文本、tool result、usage 只从 effect outcome/journal 落 transcript。
3. **不静默截断。** 任何截断、省略、compaction 都要有 `meta` 标记并在 UI 可见；模型看到的内容与 transcript 记录的内容要能解释。
4. **先 fake，后 real。** 所有新路径必须有 scripted/fake gate；真实 provider 只走受控入口，不作为 gate。
5. **不把秘密写进 transcript/日志。** API key 只从环境变量读；导出前警告；render 层继续做 secret 扫描。
6. **不改表、不改 ACL、不改 `advance`。** 只允许 M6 对 `loop_policy` 做版本化修改；其余 SQL 冻结。任何 SQL 改动都要跑 S1/S4/S9/S13。
7. **旧会话可读、可导出、可关闭，但不假装可继续。** policy/digest 变化后旧会话 readonly；不热迁移活动 run。

---

## 5. 目标架构

```text
Chainlit (app.py)
  ├─ CommandRegistry        /help /new /model /sessions /resume /name /export
  │                         /compact /queue /retry /cancel /close /tools /skills
  ├─ TurnService            queue: steer | follow-up | new turn
  ├─ ContextBuilder         system + summary + transcript seed + token estimate
  ├─ Compactor              trigger, cut point, summary run
  ├─ SessionStore v2        index: name/model/usage/workspace/bindings
  ├─ TranscriptStore        per-conversation append-only JSONL
  ├─ StreamBridge           adapter StreamEvent -> Chainlit Message/Step
  └─ Backend (existing)     AgentRuntime, SessionStore, render, executor
        ├─ ProviderRegistry / AdapterRouter   per-request model selection
        ├─ v24 kernel (mostly unchanged)       run/effect/journal/pins
        └─ HostWorker                          model/tool dispatch, cancel hook
```

### 5.1 组件职责

| 组件 | 职责 | 不做什么 |
|---|---|---|
| `SessionStore` v2 | 会话索引、名称、模型、usage、workspace、bindings、迁移 | 不存消息正文 |
| `TranscriptStore` | 每会话 append-only JSONL；seed 读取；崩溃后 reconcile | 不直接调 provider |
| `ContextBuilder` | system prompt + summary + 最近消息；工具配对校验；token 估算 | 不做 compaction 决策 |
| `Compactor` | 触发条件、cut point、summary run、summary entry | 不在活动 run 上 compaction |
| `ProviderRegistry` | `ModelSpec` 目录、key 可用性、默认模型 | 不存明文 key |
| `AdapterRouter` | 按 `request.input.model` 选 adapter；统一 lease/stream/cancel | 不改 kernel 语义 |
| `StreamBridge` | delta 合并、节流、Chainlit Message/Step 更新、取消事件 | 不写 transcript |
| `TurnService` | 忙时分类 steer/follow-up；空闲时起 run；terminal 后处理队列 | 不直接操作 SQL |
| `CommandRegistry` | 命令解析、帮助、权限/状态提示 | 不绕过 Backend 线程约束 |

### 5.2 一次 turn 的数据流

1. `on_message` 把输入交给 `TurnService.submit(sid, text)`。
2. 若当前 `st.busy`：
   - 普通文本或 `/steer <text>` → `v24.steer`，latest-wins；UI 明确提示“上一条 steer 被覆盖”。
   - `/follow <text>` → 放入 follow-up 队列，等当前 run terminal 后作为新 run 的 user message。
3. 若空闲且没有等待中的 interaction：
   - `ContextBuilder.build(conversation)`：system + summary + transcript 最近消息 + 当前 user。
   - `AgentRuntime.start_run(scope, owner_fiber, messages, model=..., budget=...)`。
   - `Backend.tick()` 驱动 `run_once`；`StreamBridge` 接收 delta；effect settle 后 `render_effect` 上屏。
4. 每个 model/tool effect settle 后：
   - `TranscriptStore.append_effect(...)`：assistant final/tool_calls、tool result、usage、finish_reason。
   - 更新 `last_usage` / `total_cost` / `message_count`。
   - 若是 terminal：`TurnService` 处理 follow-up 队列；必要时触发 compaction；`idle`。
5. 若 `status=waiting` 且有 interaction：fake 路径 `AskUserMessage`；real 路径先显示 `waiting_unsupported`（W13 仍未做），只允许 `/cancel`。
6. 若 terminal 为 failed/blocked_unknown：append `meta` error entry；`/retry` 用最后一条 user 重新起 run，不把失败 assistant 写入 transcript。

### 5.3 Compaction 数据流

1. `ContextBuilder.estimated_context_tokens(conversation) > context_window - completion_cap - framing_margin` 时触发；默认 `context_window=65,536`、`completion_cap=8,192`、`framing_margin=2,048`，即约 55,296 tokens。
2. 只在没有 ready/claimed business effect、没有 pending steer、没有 interaction 时执行；活动 run 先等 terminal。
3. `Compactor` 选 cut point：从最新往回累计 token，达到 `keep_recent_tokens`（默认 20,000）为止；切点只能落在 user/assistant/summary 边界；**不得**把 assistant `tool_calls` 和它的 tool results 切开。
4. 起一个 **summary run**：同一 scope、同一 owner fiber、`requires=[]`、无工具、独立 budget（steps=2, tool_calls=0, tokens=16,384, wall=120s）、`max_output_tokens=2,048`。输入是“上一份 summary + 待摘要消息（工具结果截到 2,000 字符）”，输出是结构化 summary。
5. summary run settle 后，写 `kind=summary` entry，`meta.summary_run_id` 唯一；如果进程在 settle 与写入之间崩溃，启动时按 `summary_run_id` 幂等补齐。
6. 之后 seed = system（含 `<conversation_summary>`）+ summary 之后的消息；原 transcript 不删，只移动 `first_kept_seq`。

> 为什么用 summary run 而不是 UI 直连 provider：summary 也走 effect/journal，durable、可审计、可用 fake adapter 测；不需要新增“UI 直连模型”的旁路。代价是多一个 run，UI 要把它从时间线隐藏。

### 5.4 Streaming / abort / retry

- `DeepSeekAdapter.build()` 对支持流式的模型设置 `stream:true`；`send(prepared, on_event)` 解析 SSE：
  - `delta.content` → `text`
  - `delta.reasoning_content` → `reasoning`
  - `delta.tool_calls[]` → `tool_start` / `tool_args`（按 index 聚合）
  - `finish_reason` / `usage` → `done`
- 重建与非流式相同的 provider JSON（`choices[0].message` + `usage`）后复用 `interpret()`；这样 settlement mapping 不变。
- `HostWorker` 增加可选 `stream_sink`；在 executor 线程调用；`Backend` 用 `loop.call_soon_threadsafe` 投递到 UI 队列。
- **取消走旁路**：`/cancel` 在 asyncio 线程直接设置该 run 的 `threading.Event`，并调用 `adapter.cancel(run_id)` 关闭 transport；随后再入队 `v24.cancel`。这样不会因为单 executor 正卡在 provider call 而无法取消。最终状态仍以 run projection 为准；如果 cancel-late，UI 显示 cancelled，不显示 provider failure。
- **重试**：adapter 对 408/429/5xx 做有限指数退避；只在**首个 token 之前**自动重试。已出现 partial text 后不自动重试，避免 UI 重复；由用户 `/retry`。工具调用不自动重试。
- **Steer vs follow-up**：普通文本/`/steer` 是 steer；`/follow` 是 follow-up。两者都显示队列；abort 后 follow-up 保留，steer 按 latest-wins 提示。

### 5.5 并发与部署

- 目标部署是单用户 loopback；保留单 executor，所有会话串行。UI 必须显示“另一会话正在运行/排队”，不能让用户误以为卡死。
- 多用户、多 executor、每会话独立 `AgentRuntime` 不在本计划；若未来要做，需要另写计划（连接池、锁、迁移、隔离）。
- 真实 provider 入口仍受 `AGENTS.md` 的四类受控入口约束；M6–M10 不新增第五类。

---

## 6. 数据模型与契约

### 6.1 `SessionRecord` v2（`sessions.json`）

```json
{
  "format_version": 2,
  "active_conversation_id": "uuid|null",
  "conversations": [
    {
      "conversation_id": "uuid",
      "name": "fix-parser",
      "created_at": "ISO-8601",
      "updated_at": "ISO-8601",
      "workspace_root": "/abs/path",
      "toolset": "read|write|exec",
      "model": "deepseek/deepseek-chat",
      "thinking": "off|low|medium|high",
      "realm": "ui-xxxxxxxx",
      "scope_id": "uuid",
      "bindings": [{"scope_id": "uuid", "run_id": "uuid", "realm": "ui-xxxxxxxx"}],
      "message_count": 42,
      "last_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": null},
      "total_cost": null,
      "policy_digest": "sha256",
      "catalog_digest": "sha256",
      "limits_digest": "sha256",
      "limits_profile": "usable|legacy",
      "setup_incomplete": false,
      "migrated_from_v1": false,
      "archived": false
    }
  ]
}
```

- 保留旧字段 `resume_token_hash` 的读取兼容；新会话不再把 token 作为主要恢复方式，但 `/resume <run_id> <token>` 仍可用。
- 所有写入仍走 `atomic_json`（0600、fsync、rename）。
- `bindings` 继续保留 200 条上限；`archived` 只影响列表，不删 scope。

### 6.2 `TranscriptEntry`（`data/transcripts/<conversation_id>.jsonl`）

```json
{
  "v": 1,
  "entry_id": "uuid",
  "conversation_id": "uuid",
  "seq": 1,
  "parent_id": "uuid|null",
  "kind": "user|assistant|tool|summary|meta",
  "role": "user|assistant|tool|system",
  "content": "text",
  "reasoning": "text|null",
  "tool_calls": [
    {"id": "call_...", "type": "function",
     "function": {"name": "read", "arguments": "{\"path\":\"...\"}"}}
  ],
  "tool_call_id": "call_...|null",
  "run_id": "uuid|null",
  "effect_id": "uuid|null",
  "created_at": "ISO-8601",
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": null},
  "meta": {
    "model": "deepseek/deepseek-chat",
    "finish_reason": "stop|tool_calls|length",
    "truncated": false,
    "compacted": false
  }
}
```

约束：

- `entry_id` 全局唯一；重复 append 幂等（reconcile 用 `effect_id` + `kind` 去重）。
- `seq` 每会话单调；崩溃后从文件尾部恢复 `max(seq)+1`；不允许空洞依赖。
- assistant 的 `tool_calls` 必须与紧随其后的 tool entries 一一配对；任何截断都不得只删 tool，必须整批保留或整批替换为同 id 的占位。
- `tool_calls.function.arguments` 保持 provider 原样字符串，不在存储时重排。
- 单条 entry 上限 64 KiB；单会话 10,000 条或 8 MiB，先剪最旧的 tool 输出，再 compaction；剪枝必须写 `meta.compacted=true`。被剪的 tool 必须保留同 `tool_call_id` 的占位 entry（content 说明 omitted），不能直接删除，否则 assistant `tool_calls` 与 tool results 的配对会断裂。
- 文件权限 0600，目录 0700；不写日志；导出前提示可能含敏感内容。

### 6.3 `SummaryEntry`

```json
{
  "kind": "summary",
  "role": "system",
  "content": "structured summary ...",
  "meta": {
    "summary_run_id": "uuid",
    "first_kept_seq": 123,
    "tokens_before": 48000,
    "tokens_after": 21000,
    "model": "deepseek/deepseek-chat",
    "created_at": "ISO-8601"
  }
}
```

- summary 的 `content` 是下一次 seed 的 system 附加段，放在 `<conversation_summary>` 中。
- 只保留最新一份 summary；旧 summary 留在文件里作为历史，但 seed 只用最新。
- summary run 不显示在用户时间线；只显示一条 `context · compacted (48k → 21k)` 的 run step。

### 6.4 `ModelSpec`

```json
{
  "id": "deepseek/deepseek-chat",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com",
  "api_key_env": "DEEPSEEK_API_KEY",
  "context_window": 65536,
  "max_output_tokens": 8192,
  "supports_tools": true,
  "supports_stream": true,
  "supports_images": false,
  "thinking": ["off", "low", "medium", "high"],
  "pricing_revision": "existing"
}
```

- 文件：`v24/ui/models.json`（tracked，无 secret）；可用 `V24_UI_MODELS` 指向私有机密配置（0600，repo 外）。
- key 解析顺序：环境变量（`api_key_env`）→ 无。P0 不把 key 写进 `sessions.json`/transcript。
- 默认模型：`deepseek/deepseek-chat`；保留 `deepseek-flash` 作为 legacy 兼容项，但不作为新会话默认。
- `AdapterRouter` 读取 `start` payload 的 `input.model`；未知模型返回 `model_unknown`，不落到默认模型。

### 6.5 Seed messages 契约

`ContextBuilder.build_seed(conversation)` 返回：

```python
[
  {"role": "system", "content": system_prompt},          # 只一条
  # 可选：summary 已拼进 system 的 <conversation_summary>，不再单独发 system
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "...", "tool_calls": [...]},
  {"role": "tool", "tool_call_id": "call_...", "content": "..."},
  {"role": "assistant", "content": "..."},
  {"role": "user", "content": "current prompt"},
]
```

校验规则（adapter 与 ContextBuilder 共用）：

- `system` 只能出现在开头，最多一条。
- `assistant.tool_calls` 的每个 `id` 必须唯一；其后必须紧跟同数量的 `tool` messages，`tool_call_id` 集合完全相等。
- `tool` 不得出现在没有前置 assistant `tool_calls` 的位置。
- `content` 可为空字符串，但不得为 `None`；`tool_calls` 里的 `arguments` 必须是合法 JSON 字符串。
- `images`/多模态 part 暂不支持；P2 再扩展。
- 当前 user 必须恰好最后一条；retry 时不要重复追加同一条 user。

### 6.6 Adapter 契约 v2

```python
class ProviderAdapter(Protocol):
    model: ModelSpec
    timeout_s: float

    def preflight(self) -> dict | None: ...
    def build(self, effect: dict, history: list[dict], pins: list[dict]) -> PreparedCall: ...
    def send(self, prepared: PreparedCall, on_event: Callable[[StreamEvent], None] | None = None
             ) -> tuple[int, bytes, int]: ...
    def interpret(self, prepared: PreparedCall, status: int, raw: bytes, wall_ms: int) -> dict: ...
    def cancel(self, run_id: str, effect_id: str) -> None: ...
    def lease_ms(self, timeout_s: float) -> int: ...
```

- `PreparedCall` 增加 `model_id`、`stream: bool`、`cancel_event: threading.Event`。
- `send` 在 `stream=false` 时行为不变；`on_event=None` 时忽略 delta。
- `interpret` 继续返回现有 outcome 结构；流式路径先重建非流式 raw，再复用。
- `AdapterRouter` 实现同一 Protocol，按 `effect.request.input.model` 委托；`lease_ms` 取被选 adapter 的值。
- `DeepSeekAdapter` 的 `_messages()` 对 `start/spawn` 接受 `system|user|assistant|tool`，并复用 `_validate_history()` 做配对校验；`stream` 字段由 `ModelSpec.supports_stream` 决定。
- `tool_choice` 仍不发送；`parallel_tool_calls` 仍不发送；`OPENAI_API_URI` 仍不读。

### 6.7 Limits / Policy v2

| 旋钮 | 旧值 | 新值 | 位置 |
|---|---|---|---|
| `completion_cap` | 512 | **8,192** | `v24/ui/catalog.py`、`v24/host/deepseek.py` |
| `loop_policy.v` | 1 | **2** | `v24/sql/48_loop.sql` |
| `body_byte_ceiling` | 8,000 / 16,384 | **131,072** | `v24/ui/catalog.py` |
| `loop_policy.reserve_tokens` | 4,096 | **65,536** | `v24/sql/48_loop.sql`（唯一允许的 SQL 改动） |
| `run_budget.tokens` | 20,000 | **400,000** | `v24/ui/catalog.py` |
| `run_budget.steps` | 24 | **128** | 同上 |
| `run_budget.tool_calls` | 24 | **128** | 同上 |
| `run_budget.wall_ms` | 600,000 | **3,600,000** | 同上 |
| `max_rounds_per_turn` | 64 | **256** | `v24/ui/control.py` |
| `DEFAULT_PROVIDER_TIMEOUT_S` | 120 | **239** | `v24/ui/catalog.py` |
| `MAX_SAFE_ARGS_BYTES` | 128 | **128（先保持，M6 重测后再改）** | `v24/ui/catalog.py` |
| `context_window` | 未定义 | **65,536** | `ModelSpec` |
| compaction reserve | 未定义 | **16,384** | `Compactor` |
| keep recent | 未定义 | **20,000** | `Compactor` |
| summary output | 未定义 | **2,048** | summary run |
| transcript cap | 未定义 | **8 MiB / 10,000 entries** | `TranscriptStore` |

说明：

- `run_budget` 是安全上限，不是目标用量；128 步时 tokens 通常先绑定。默认 400k 适合 20–30 次模型调用的编码任务；更长任务按 `/session` 调高，仍受 SQL `steps<=256` 限制。
- `reserve_tokens` 是**单次 model call 的 token 预留**，不是 run 总预算；`run_budget.tokens` 是 run 累计。`v24.model_reserve` 仍取 `min(remaining, reserve)`。
- `available = reserve - estimate`；`max_tokens = min(cap, available)`；`available < 1` 直接 `reserve_insufficient`，不再走“ceiling 非空就强行 cap”的旧 fallback。旧 fallback 是 512 时代的补丁，在 8k 输出下会掩盖真实超限。
- `body_byte_ceiling` 与 token reserve 是两把尺：bytes 管 admission，tokens 管 provider 预算；两者都要测，不能用一个推另一个。
- `finish_length`：若 `content` 非空，映射为 success + `final.text`（部分输出），`meta.truncated=true`；若同时带 `tool_calls`，**不执行**这些被截断的调用，只保留文本；若 content 为空，仍为 failure `finish_length`。UI 明确显示“输出达到上限，已保留部分内容；可继续或重试”。
- `max_output_tokens` 仍由 `start` payload 传入；adapter 的 `MAX_COMPLETION_CAP` 只作为上限，不作为默认。

**Policy cutover**：`loop_policy` 参与 `v24.model_digests()` 的 policy 哈希。改为 65,536 后，所有旧 run 的 model request digest 不再匹配。处理方式：

1. 部署 M6 前，等待所有活动 run terminal；不能等待的用 `/close` 收敛。
2. 旧会话在 `sessions.json` 中保留 `policy_digest`；加载时与当前不匹配 → `readonly=true`，`/resume` 只 replay/export，不允许新 run。
3. 新会话写新 `policy_digest`；不热迁移、不重写旧 effect。
4. 若团队拒绝改 SQL：走 **Plan B**——`reserve_tokens` 保持 4,096、`completion_cap` 最多 4,096、body 最多 16 KiB；不做 `finish_length` 部分输出（或只做 UI 提示）。Plan B 仍比 512 好，但上下文/输出会明显受限，不能宣称对齐 Pi。

### 6.8 错误/状态分类

沿用 v24 的 effect/run 闭集，不新增 SQL 状态。UI 映射新增：

| 场景 | 内部 | UI 文案/行为 |
|---|---|---|
| body 超限 | `body_too_large` | “请求超过上下文容量；先 /compact 或减少附件” |
| token 预留不足 | `reserve_insufficient` | “本轮预算不足；/compact 或调低 keep recent” |
| 模型未知 | `model_unknown` | “模型未配置；/model 查看可用列表” |
| key 缺失 | `credentials_absent` | “凭证缺失；设置环境变量或 /login（P1）” |
| 输出截断 | `finish_length` + partial | 显示部分输出，meta.truncated，可 /retry |
| 流中断 | `stream_error` | 保留已显示文本，标 “未完成”，不写 assistant final |
| 用户取消 | `cancelled` | 以 run projection 为准；不显示 provider failure |
| compaction 失败 | `compact_failed` | 保留原上下文；提示 /compact 手动重试 |

### 6.9 迁移

- `SessionStore` 读到 `format_version=1`：内存升级为 v2；为每个 conversation 创建 `transcripts/<id>.jsonl`，把 `turns.jsonl` 的 user + 已知 final 写成 user/assistant entries；`migrated_from_v1=true`。
- 迁移是幂等的：transcript 已存在则跳过；`turns.jsonl` 不删，作为 legacy 只读。
- `sessions.json` 损坏：沿用 quarantine；如果 transcript 存在但索引缺失，扫描 `transcripts/*.jsonl` 的 header 重建最小索引（conversation_id/name/created_at），标 `recovered=true`。
- 旧 `resume_token_hash` 保留；新会话可写 `null`。
- 迁移测试必须覆盖：v1→v2、重复迁移、半写文件、损坏 JSON、transcript 缺尾行、索引缺失。

---

## 7. 里程碑

### M6 — Limits & Policy v2（先行，解锁空间）

**目标**：把“512 tokens / 16 KiB / 24 步”的演示上限换成可用的预算，并让 `finish_length` 不再无提示失败。

**工作项**

1. `v24/ui/catalog.py`：
   - 新增 `USABLE_UI_LIMITS`（`completion_cap=8192`、`body_byte_ceiling=131072`、`timeout=239`、`budget=128/128/400000/3600000`）。
   - `UiLimits` 校验上限改为 8,192 / 131,072；保留 `LEGACY_UI_LIMITS` 供旧 gate/旧会话。
   - `limits_contract()` 与 `build_system_prompt()` 按 profile 渲染；删掉 “stream:false / finish_length ends the run” 的旧文案，改成流式与部分输出文案。
2. `v24/host/deepseek.py`：
   - `MAX_COMPLETION_CAP=8192`；`DEFAULT_COMPLETION_CAP` 保留 256 作为未指定时的保守值。
   - `build()` 计算 `available = tokens - estimate`；`<1` 直接 `reserve_insufficient`；去掉旧 fallback。
   - `interpret()` 的 `finish_length` 分支按 §6.7 处理。
   - `PreparedCall` 增加 `model_id`/`stream`/`cancel_event`（M8 使用）。
3. `v24/sql/48_loop.sql`：只改 `loop_policy` 的 `v` 为 2、`reserve_tokens` 为 65,536；`max_tool_calls`/`max_state_bytes` 不动。
4. `v24/ui/control.py`：`max_rounds_per_turn=256`；`start_run` 支持 `model`/`thinking`/`requires` 参数（为 M7/M9 预留）。
5. `v24/ui/app.py` / `v24/ui/sessions.py`：`SessionStore` 增加可选 `policy_digest` 与 `limits_profile`（v1 兼容，M7 再升 v2）；`Backend` 选择 `USABLE_UI_LIMITS`（新会话）或 `LEGACY_UI_LIMITS`（旧会话/显式 profile）；启动时写/打印 policy digest；旧 profile 或无字段且 digest 不匹配的会话标记 readonly。
6. `v24/ui/real.py`、`v24/ui/provider.py`：真实入口使用新 limits；不改变 credential/preflight/empty-scratch 顺序。

**测试**

- 新增 `v24/ui/test_limits_v2.py`：profile 校验、8192/131072 边界、8193/131073 拒绝、`available` 计算、`reserve_insufficient`、`finish_length` partial/empty/tool_calls、旧 profile 的 512/8000 保持。
- `v24/s4/test_g2b.py`：policy 变更后的 reserve/digest/turn/budget 断言。
- `v24/s1/test_g1.py`、`v24/s9/test_g8.py`：加载/生命周期不回归。
- `v24/s13/test_*.py`：13 个契约/向量门；只更新明确断言旧 limits/`finish_length`/policy 的 fixture，并在矩阵记录语义变化；不放宽无关断言。
- `v24/ui/test_ui_gate.py`：在 M6 期间显式 `V24_UI_LIMITS_PROFILE=legacy`，保留原 512/8000 语义；M7/M8 的 usable gate 另跑。`run_m4_checks.py` 必须在子进程中显式设置同一 profile，避免 M4 receipt 被新 limits 改写。

**验收**

- `uv run python v24/ui/test_limits_v2.py` exit 0。
- `uv run python v24/s4/test_g2b.py`、`v24/s1/test_g1.py`、`v24/s9/test_g8.py` exit 0。
- `uv run python v24/ui/run_m4_checks.py --log-dir /tmp/v24-m6-m4` exit 0。
- 旧会话加载后 `readonly=true`；新会话 `policy_digest` 为新值；没有跨 digest 的 resume。
- 8,192-token 输出、131,072-byte body 在 fake 下完成一轮；超过边界被明确拒绝。

**回滚**：恢复 `loop_policy`、`UiLimits`、adapter 常量；旧会话仍可读。由于 policy digest 变化，回滚后新会话会再次 readonly；这是可接受的显式代价。

---

### M7 — Session Context v2 + Compaction

**目标**：把 3,950 字符的 `history_block()` 换成结构化 transcript；工具结果跨 run 保留；上下文接近上限时自动摘要。

**工作项**

1. `v24/ui/transcript.py`（新）：
   - `TranscriptStore(data_dir, conversation_id)`：append、iter、latest_summary、reconcile、cap/prune。
   - `append_effect(run_id, effect, model, usage)`：把 model success/failure/unknown 映射为 assistant/tool/meta entries；不写未 settle 的 delta。
   - `reconcile(run_ids)`：启动/恢复时按 `effect_id` 幂等补齐；对 terminal run 的 history 与 transcript 做一致性检查。
   - 文件头 `{"v":1,"conversation_id":...}`；每行一个 entry；fsync；0600/0700。
2. `v24/ui/context.py`（新）：
   - `build_seed(conversation, user_text)`：system（含 skills/limits/summary）+ transcript 最近消息 + 当前 user。
   - `estimate_tokens(entries)`：优先用 usage；fallback 用 `ceil(chars/3)`，CJK 用 `ceil(chars/2)`，工具 schema 另加固定估计；校准 fixture。
   - `should_compact(usage, spec)`；`find_cut(entries, keep_tokens)`：只切 user/assistant/summary 边界，整批 tool 保留。
3. `v24/ui/compaction.py`（新）：
   - `compact(conversation)`：起 summary run（§5.3），写 summary entry，更新 `first_kept_seq`，发 `context · compacted` step。
   - `summary_run_id` 幂等；失败不破坏原上下文；`/compact [instructions]` 可手动触发。
   - summary prompt 模板：保留目标、约束、已改文件、未完成事项、关键工具结论；工具结果截到 2,000 字符；不编造。
4. `v24/ui/sessions.py`：
   - v2 schema（§6.1）；`name`、`model`、`last_usage`、`total_cost`、`limits_profile`、`policy_digest`。
   - 保留 v1 读取/迁移；`history_block` 标记 deprecated，仅 legacy profile 使用。v2 新会话不再追加 `turns.jsonl`；该文件只服务 v1 迁移/回放，不能作为 seed 来源。
   - `bind`/`new_conversation` 写入新字段；`find_by_token` 保留。
5. `v24/ui/app.py`：
   - `ThreadState` 增加 `transcript`、`last_usage`、`queue_followups`、`compacting`。
   - `tick()` 在 terminal 后 append transcript、更新 usage、尝试 compaction、处理 follow-up。
   - `resume` 从 transcript 重建时间线；对缺失 effect 做 reconcile；只读会话不允许新消息。
6. `v24/ui/control.py`：
   - `start_run(..., model=None, thinking=None, requires=None)`；新增 `start_summary_run(...)`，`requires=[]`。
   - `append_transcript` 不在 control 层做，留给 app/transcript，避免 control 依赖 UI 存储。
7. `v24/ui/real.py`/`env.py`：
   - transcript 目录在 `data_dir` 下；`--status` 报告 transcript 数量和大小；`--reset` 清空（需 `--yes`）。
   - 不改现有 DB/lock/journal 顺序。

**测试**

- `v24/ui/test_transcript.py`：append/iter/reconcile、幂等、崩溃尾部、损坏行、cap/prune、tool 配对、权限。
- `v24/ui/test_context.py`：seed 顺序、summary 拼接、当前 user 唯一、tool 配对、`find_cut` 不切断 batch、CJK/ASCII token 估计、`should_compact`。
- `v24/ui/test_compaction.py`：fake summary run、幂等、失败保留、`/compact`、summary 不显示在时间线、compaction 后继续 10 轮。
- `v24/ui/test_sessions_v2.py`：v1→v2 迁移、重复迁移、索引缺失重建、旧 token 仍可 `/resume`、readonly。
- 扩展 `v24/ui/test_ui_gate.py`：20 轮 + 10 工具 + 一次 compaction 的端到端 fake；最后一行更新为新的 steps/effects 统计。
- `v24/ui/test_backend_regressions.py`：线程归属、单 executor、无第三条连接、secret 扫描不回归。

**验收**

- 20 轮 fake 任务后，seed 含最近完整 tool 结果；`/resume` 跨进程重建同样的 seed。
- 触发一次自动 compaction；summary 写入 transcript；compaction 后继续 5 轮不丢最近文件/决策。
- 没有 assistant `tool_calls` 与 tool results 被切开；没有重复 `effect_id`。
- `turns.jsonl` 仍保留，旧会话可读；新会话不再写 `history_block`。
- `v24/ui/test_ui_gate.py`、`test_backend_regressions.py`、`test_artifact_regressions.py` exit 0。

**回滚**：保留 M7 新文件但关闭 `V24_UI_CONTEXT_V2=0`，回退到 legacy `history_block`；transcript 文件不删，作为迁移证据。M6 的 limits 保留。

---

### M8 — Streaming, Abort, Retry, Queue

**目标**：让“生成中”变成可见的流；让停止真的停止；让失败可重试；让 steer/follow-up 不互相覆盖。

**工作项**

1. `v24/host/deepseek.py` / 新 `v24/host/stream.py`：
   - SSE parser：`data:` 行、`[DONE]`、多行 data、UTF-8 分片、错误帧、usage-only 帧。
   - `send(prepared, on_event)`；聚合 text/reasoning/tool_calls/index；重建非流式 raw。
   - 流式请求带 `stream_options={"include_usage": true}`；provider 不支持时在 preflight 标记 `usage_unavailable`，不发送该字段。若最终仍无 usage，按 `unknown` 处理，UI 显示 usage unavailable，**不伪造 0**。
   - `cancel_event` 检查；关闭 socket；返回 `aborted` 标记。
   - 有限重试：408/429/5xx，`Retry-After` 优先，指数退避，最多 3 次；只在首个 token 前。
2. `v24/host/worker.py`：
   - `HostWorker(..., stream_sink=None)`；`_execute_model` 把 `on_event` 传给 adapter；sink 异常不得影响 settlement。
   - `adapter.cancel(run_id, effect_id)` 接口；worker 在 claim 时注册 `(run_id, effect_id, cancel_event)`。
   - 保持 `assert_all_idle()` 在 provider IO 前；stream sink 不碰 DB。
3. `v24/ui/app.py`：
   - `StreamBridge`：按 model effect 建一个 `cl.Message`，delta 用 `stream_token`；节流 50ms；final 用 `update`；错误/取消用 `is_error`。
   - `UiEvent` 新增 `delta`/`thinking`/`tool_update`/`usage`/`queue`；`consume()` 处理。
   - `/cancel` 旁路：asyncio 线程设置 `threading.Event` + `adapter.cancel`，再入队 `v24.cancel`；显示 “stopping…”。
   - `/retry`：仅 terminal failed/blocked_unknown；用最后 user 起新 run；不复制失败 assistant。
   - `/follow <text>`：follow-up 队列；`/queue` 查看；abort 保留；latest-wins 只作用于 steer。队列是内存态，进程重启丢失，UI 要明确提示；失败 terminal 也执行 follow-up，用户可 `/queue` 清除。
4. `v24/ui/catalog.py`：
   - `build_system_prompt` 去掉 `stream:false`；说明流式、partial、retry 的语义。
   - `limits_contract` 渲染新的 profile。
5. Chainlit 兼容性 spike（先做）：
   - 验证 2.12 的 `Message.stream_token`/`update`、`Step.update`、`on_stop` 与自定义取消的交互；若 `Step.update` 不可靠，P0 只流 assistant 文本，工具 step 仍 settle 后一次性出现。

**测试**

- `v24/ui/test_stream.py`：SSE 解析（text/reasoning/tool_calls/usage/[DONE]/坏帧/分片）、重建 raw 与 non-stream 等价、首 token 前重试、首 token 后不重试、abort、无重复 final。
- `v24/ui/test_queue.py`：steer latest-wins、follow-up terminal 后执行、abort 保留 follow-up、`/queue`、busy 分类。
- 扩展 `test_ui_gate.py`：fake 流式 20 轮；断言 delta 顺序、final 只出现一次、transcript 只有 settle 后的 entry。
- `v24/ui/test_backend_regressions.py`：流式 sink 不产生 DB 事务、线程归属不变、secret 扫描不回归。
- Browser spike receipt（人工或 Playwright 可选）：首 token 可见、停止、恢复、无重复。

**验收**

- fake 下首个 delta <2s 可见；`/cancel` 在 1s 内发出 transport abort；run projection 最终为 cancelled，UI 不显示 provider failure。
- 流式 final 与 non-stream final 逐字节一致；transcript 不出现 partial assistant entry。
- 重试只在首 token 前；重试次数和原因可见；不重试工具调用。
- 既有 gate 全绿；`AGENTS.md` 的“real UI stop/steer 在一次 provider 调用期间可能排队”限制仍然记录，不宣称 W13 完成。

**回滚**：`V24_UI_STREAM=0` 回退到 non-stream；保留 SSE parser 与测试；transcript/queue 不回滚。

---

### M9 — Model / Provider + Session Product

**目标**：会话中可选模型；会话可命名、列出、恢复、导出；real 模式可重启（需先获批非空 scratch 例外）。

**工作项**

1. `v24/ui/models.py`（新）/`provider.py`：
   - `ModelSpec` 目录（§6.4）；默认 `deepseek/deepseek-chat`，保留 `deepseek-flash` legacy。
   - `AdapterRouter`：按 `input.model` 选 `DeepSeekAdapter` / `OpenAICompatibleAdapter`；未知模型 `model_unknown`；key 缺失 `credentials_absent`。
   - `OpenAICompatibleAdapter`：同一 wire shape，base_url/model 可配；不读 `OPENAI_API_URI`；`tool_choice`/`parallel_tool_calls` 仍不发。
   - `DeepSeekAdapter.interpret` 的 model 校验与 pricing 改为 `prepared.model`/`prepared.model_id`，不再用模块常量 `MODEL`；未知/不一致仍 `model_mismatch`。
   - 每会话 `model`/`thinking` 写入 sessions.json；`/model` 只在 idle/terminal 切换，busy 时拒绝并提示 `/cancel` 或 `/follow`；resume 恢复；旧 run 的 model 记录在 transcript meta。
2. `v24/ui/sessions.py` / `app.py`：
   - `/sessions` 列表：短 id、名称、模型、消息数、token/cost、更新时间、是否可恢复。
   - `/resume <n|id>`：不强制 token；按列表序号或 id；校验 policy/catalog/limits profile；不可恢复时明确 `policy_changed`/`catalog_changed`。
   - `/name <text>`；`/export [jsonl|md]`：写 `data/exports/`，0600，`cl.File` 下载；路径/文件名清洗；提示可能含敏感内容。
   - `/session`：当前会话统计、context 使用、模型、workspace、最近 compaction。
   - 32 会话上限保留；达到上限只回收 terminal 且非活动的 transcript；不删活跃。
3. `v24/ui/real.py` / `env.py`：
   - real 新会话仍要求空/不存在目录；**resume** 允许非空目录，但要求 `.v24-session.json` marker（`{v:1, conversation_id}`，0600）匹配；marker 缺失/不匹配 → `workspace_unbound`/`workspace_mismatch`；拒绝 symlink/`..`/data-root 重叠。
   - 这项改动触及 `AGENTS.md` 中 real UI “目录为空”的安全约束，必须先由协调者更新约定/完成安全评审；未获批前 real resume 不做，只保留 fake resume。
   - `--status` 报告 marker、transcript、policy profile；`--reset` 仍显式 `--yes`。
4. `v24/ui/catalog.py`：
   - `limits_contract`/system prompt 按模型 `max_output_tokens`/`context_window` 渲染；不再写死 512/8000。
   - `MAX_SAFE_ARGS_BYTES` 在 M6 重测后回填；未测则保持 128 并显示 “unmeasured”。
5. 会话成本：
   - 从 effect usage 累计 `prompt/completion/total/cost`；footer/`/session` 展示；无 pricing 时显示 tokens only。
   - 不做计费/配额；只做可见性。

**测试**

- `v24/ui/test_models.py`：目录解析、router 选择、未知模型、key 缺失、per-session model、resume 恢复、adapter 不串线。
- `v24/ui/test_sessions_v2.py`：`/sessions`、`/resume` 序号/id、`/name`、`/export` 内容与权限、32 上限、readonly。
- `v24/ui/test_real_entry.py`：real 新会话空 scratch、resume marker、marker mismatch/symlink、credential/preflight 顺序、无 key 不建目录/不建库。
- `v24/ui/test_ui_gate.py`：fake 下 model switch + resume + export 的端到端。
- 真实 opt-in（非 gate）：`python -m v24.ui.real --real-provider-smoke` 短场景；多轮/compaction/model switch 场景在 M9 后手动跑。

**验收**

- `/model` 切换后新 run 使用新模型；旧 run 不被改写；resume 恢复新模型。
- 进程重启后 real 会话 `/resume` 成功（在 M9 的“非空 scratch resume”例外获批后；未获批时以 fake resume 验收，real 保持空 scratch）。新会话仍拒绝非空 scratch。
- `/export` 生成 JSONL/Markdown，0600，内容与 transcript 一致；不含 key/Authorization/DSN。
- 既有 gate 全绿；M5 的 3 个 blocker 不被声称解决。

**回滚**：`V24_UI_MODEL` 固定回默认；sessions v2 字段保留；real marker 逻辑可关闭（回到空 scratch），但会牺牲 real resume。

---

### M10 — Tool UX, MCP, Hardening（P1；MCP 可选）

**目标**：补齐日常编码体验；把“能跑”变成“好用”；决定 MCP/扩展是否进入下一版。

**工作项**

1. **Diff 渲染**：
   - `edit`/`apply_edits`：从 args 的 old/new 生成 unified diff，UI 折叠展示；`write` 显示路径 + 字节数 + 前 N 行。
   - 可选：artifact 增加 `meta.diff`（受 4 KiB meta 限制，长 diff 截断）；需要 W9 renderer/golden 变更，放到 M10 后段。
2. **@文件**：
   - 解析 user text 中的 `@path`（支持引号）；校验 workspace 栅栏；在 prompt 追加 `<mentioned_files>` 绝对路径列表，不直接塞内容；模型用 read/read_file 读取。
   - 不做 Chainlit 自定义 autocomplete（P2）。
3. **Prompt templates / skills**：
   - `v24/ui/prompts/*.md` + `/prompt <name> [args]`；模板展开后作为 user message。
   - `V24_SKILLS_ROOT` 支持多个根（`:` 分隔）；`/skill:<name>` 显示/注入 SKILL.md；`disable-model-invocation` 只影响自动提示。
   - 不引入 Pi 的 packages/npm；只做本地文件。
4. **MCP 桥（可选，需单独立项）**：
   - 现实约束：v24 的模型只能看到 SQL pin 的 v2 artifact 工具；MCP 不能像 Pi 那样动态注册。可行方案是“每 server 生成一个 v2 artifact”，把 MCP tool 映射成 artifact key；每 server ≤16 个工具，超出用 tool search/分页；不支持 resources/prompts。
   - 若不做生成式 artifact，则不做 MCP；不要用“一个 mcp_call 万能工具”假装 parity。
   - MCP 配置：仓库内只放 `v24/ui/mcp.example.json`；实际 `~/.config/v24/mcp.json` 或 `V24_UI_MCP_CONFIG` 指向的文件（0600，repo 外）；stdio/HTTP；env/header 插值；不自动信任项目配置；工具执行剥离 provider key/PG*。
5. **可选审批**：
   - P0 不做 per-call 审批；若 M10 要加，必须先有 host 层 `before_tool_call` hook（dispatcher/worker），不能用 UI 事后拦截。
   - 本地单用户默认 `V24_UI_TOOLSET=read`；write/exec 显式开启；README 写明“不要暴露到非 loopback”。
6. **收尾**：
   - 浏览器验收：流式、停止、resume、model switch、export、compaction、错误提示。
   - real opt-in：短、多轮、compaction、model switch 四个场景；保留 journal/evidence；不作为 gate。
   - 更新 `v24/ui/README.md`、conformance matrix、deviation ledger；记录 M5 仍 INCOMPLETE。
   - 重新测量 `MAX_SAFE_ARGS_BYTES`、body ceiling、CJK/ASCII token 估计；把实测值回填，不猜。

**测试**

- `v24/ui/test_tool_ux.py`：diff 生成、@path 栅栏、模板展开、技能多根、MCP artifact（若做）。
- `v24/ui/test_ui_gate.py`：diff/mention/prompt 的端到端。
- `v24/ui/test_real_entry.py`：审批/工具集/secret 剥离（若做）。
- 浏览器 receipt；真实 provider 手动 receipt。
- 全量：`v24/ui/run_m4_checks.py`、`v24/s4/test_g2b.py`、`v24/s1/test_g1.py`、`v24/s9/test_g8.py`、13 个 S13。

**验收**

- 编辑结果有可读 diff；`@file` 不越界；模板/技能命令可用。
- 若 MCP 做：至少一个 stdio server 的 1 个工具可被模型调用；失败有明确错误；不泄露 key。
- 全量 gate 绿；文档与实测值一致。

**回滚**：MCP 独立 feature flag `V24_UI_MCP=0`；diff/mention/template 可单独关闭。

---

## 8. 文件影响

### 8.1 新增

| 文件 | 用途 | 里程碑 |
|---|---|---|
| `v24/ui/transcript.py` | append-only transcript、reconcile、cap | M7 |
| `v24/ui/context.py` | seed 构建、token 估算、cut point | M7 |
| `v24/ui/compaction.py` | 触发、summary run、summary entry | M7 |
| `v24/ui/models.py` | ModelSpec、ProviderRegistry、AdapterRouter | M9 |
| `v24/host/openai_compat.py` | OpenAI-compatible adapter（DeepSeek 之外的 provider） | M9 |
| `v24/host/stream.py` | SSE parser、StreamEvent、流式聚合 | M8 |
| `v24/ui/commands.py` | 命令解析/帮助 | M9 |
| `v24/ui/models.json` | 可跟踪的模型目录（只放 `api_key_env` 名称） | M9 |
| `v24/ui/test_limits_v2.py` | M6 gate | M6 |
| `v24/ui/test_transcript.py` | M7 gate | M7 |
| `v24/ui/test_context.py` | M7 gate | M7 |
| `v24/ui/test_compaction.py` | M7 gate | M7 |
| `v24/ui/test_stream.py` | M8 gate | M8 |
| `v24/ui/test_queue.py` | M8 gate | M8 |
| `v24/ui/test_models.py` | M9 gate | M9 |
| `v24/ui/test_sessions_v2.py` | M7/M9 gate | M9 |
| `v24/ui/test_tool_ux.py` | M10 gate | M10 |
| `v24/ui/mcp.example.json` | MCP 配置模板（无 secret） | M10（若做） |
| `v24/ui/run_usable_checks.py` | 新 gate runner | M9 |
| `docs/reviews/v24-ui-usable-conformance-2026-11-04.md` | 新矩阵 | M6–M10 |
| `docs/reviews/v24-ui-usable-deviation-ledger-2026-11-04.md` | 新偏差台账 | M6–M10 |

### 8.2 修改

| 文件 | 改动 | 里程碑 |
|---|---|---|
| `v24/ui/catalog.py` | limits profile、system prompt、contract 文案 | M6/M7/M9 |
| `v24/ui/app.py` | TurnService、StreamBridge、commands、queue、resume | M7/M8/M9 |
| `v24/ui/sessions.py` | v2 schema、name/model/usage、迁移、policy_digest | M6/M7/M9 |
| `v24/ui/control.py` | `start_run` 参数、summary run、rounds | M6/M7 |
| `v24/ui/provider.py` | router/factory、key 解析 | M9 |
| `v24/ui/real.py` | real profile、resume marker、status | M6/M9 |
| `v24/ui/env.py` | transcript/exports 路径、status | M7/M9 |
| `v24/host/deepseek.py` | 8k cap/length（M6）、seed 角色（M7）、流式（M8） | M6/M7/M8 |
| `v24/host/worker.py` | stream sink、cancel hook、router lease | M8/M9 |
| `v24/sql/48_loop.sql` | 仅 `loop_policy` 的 `v`/`reserve_tokens` | M6 |
| `v24/ui/README.md` | 状态、limits、命令、部署边界 | M6–M10 |
| `v24/ui/test_ui_gate.py` | 端到端 fake 扩展 | M6–M10 |
| `v24/ui/test_backend_regressions.py` | 线程/事务/secret 回归 | M6–M10 |
| `v24/ui/test_real_entry.py` | real marker/profile | M6/M9 |

### 8.3 明确不改

- `v24/sql/10_schema.sql`、`20_triggers.sql`、`30_advance.sql`、`40_interpreters.sql`、`45_capability.sql`、`47_verbs.sql`、`49_host_reads.sql`、`50_permissions.sql`；十张表/列/索引/ACL 不动。
- `v24/s1`/`v24/s9` 的运行时文件（除非 gate 需要最小测试适配）。
- `v24/ui/plugins/*`（M10 的 diff meta 例外，且需 W9 契约变更）。
- `v24/s13` 的 golden/contracts，除明确断言 policy 的 fixture。
- `pi/**`、`repoprompt-ce/**`、`demo_v13/**`、根 `server.py`、`pyproject.toml`。

---

## 9. 测试与验收

### 9.1 新 gate

按里程碑独立可跑，退出码 0 = 通过，禁止网络：

```bash
uv run python v24/ui/test_limits_v2.py
uv run python v24/ui/test_transcript.py
uv run python v24/ui/test_context.py
uv run python v24/ui/test_compaction.py
uv run python v24/ui/test_stream.py
uv run python v24/ui/test_queue.py
uv run python v24/ui/test_models.py
uv run python v24/ui/test_sessions_v2.py
uv run python v24/ui/test_tool_ux.py
uv run python v24/ui/run_usable_checks.py --log-dir /tmp/v24-usable-checks
```

`run_usable_checks.py` 要像 `run_m4_checks.py` 一样：

- 用私有 `PGDATA`/临时目录；不初始化/重置持久状态。
- 清除 `PG*`/`DEEPSEEK_*`/`OPENAI_*`/`V24_*` 环境。
- 记录每条命令的 exit、日志 SHA256、last line；任何 `[SKIP]` 视为失败。
- 不调用真实 provider；不打开非 Unix socket。

### 9.2 既有 gate（每个里程碑都跑）

```bash
uv run python v24/ui/test_ui_gate.py
uv run python v24/ui/test_backend_regressions.py
uv run python v24/ui/test_artifact_regressions.py
uv run python v24/ui/test_real_entry.py
uv run python v24/ui/run_m4_checks.py --log-dir /tmp/v24-m4-checks
uv run python v24/s4/test_g2b.py
uv run python v24/s1/test_g1.py
uv run python v24/s9/test_g8.py
```

M6 因为动了 `loop_policy`，必须额外跑 S4/S1/S9；S13 的 13 个命令由 `run_m4_checks.py` 覆盖。

### 9.3 真实 provider（opt-in，不是 gate）

沿用 `AGENTS.md` 的受控入口：

```bash
V24_UI_MODE=real DEEPSEEK_API_KEY=... V24_UI_WORKSPACE_ROOT=/abs/scratch \
  uv run python -m v24.ui.real --real-provider-smoke
```

M9 后增加手动场景（仍不进入 gate）：

- short：1 轮 final。
- multi：3 轮 + 1 次工具。
- compact：构造接近阈值的 transcript，触发 summary。
- switch：同一会话 `/model` 后继续。
- resume：进程重启后 `/resume`。

每个场景记录：key 不落盘、journal 保留、失败不重放、成功/失败都保留私有 evidence（0700/0600）。

### 9.4 浏览器清单

- 首 token 可见；不刷新页面；工具 step 顺序正确。
- `/cancel` 1 秒内显示 stopping，最终 cancelled；不出现重复 final。
- `/resume` 恢复历史、模型、workspace；旧会话 readonly 提示正确。
- `/export` 下载成功；文件 0600；不含 key/Authorization/DSN。
- compaction step 可见；compaction 后可继续 5 轮。
- 两个标签页：第二个明确显示“排队/被占用”，不假装并行。

### 9.5 容量与测量（M6/M10 两次）

- `MAX_SAFE_ARGS_BYTES`：先保持 128；M6 用 8k 输出重新跑多目标/多语言 probe；M10 回填。
- body ceiling：ASCII/CJK/工具 JSON 三种样本；记录 131,072 的接受/拒绝边界。
- token 估算：用 provider usage 校准 `chars/3` vs `chars/2`；记录误差，不用单一数字宣称保证。
- `finish_length` 率：8k 输出下按工具/语言分类记录；不用平均值掩盖长尾。
- 成本：按 pricing 记录 per-session；无 pricing 时只显示 tokens。

---

## 10. 迁移、回滚与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Policy digest cutover | 旧 run 不能继续；旧会话 readonly | 部署前 drain；旧会话 export/close；不热迁移；README/矩阵写明 |
| `reserve=65,536` 与 body 字节不匹配 | CJK 大 body 可能 `reserve_insufficient` | 双尺测量；compaction 触发按 min(context, reserve)；测试 CJK |
| Transcript 膨胀 | 磁盘/加载变慢 | 8 MiB/10k 条上限；先剪旧 tool；compaction；32 会话 |
| 流式与 Chainlit 2.12 不兼容 | UI 重复/卡住 | 先 spike；`V24_UI_STREAM=0` 回退；只承诺 assistant 文本流 |
| 取消旁路绕过 executor | 线程安全/状态错乱 | 只设置 Event + `adapter.cancel`；不碰 DB；kernel cancel 仍走队列 |
| Compaction 切断 tool 配对 | provider 400 / 上下文错乱 | `find_cut` 整批保留；seed 校验；fixture 覆盖 |
| Summary 质量差 | 后续任务忘事 | 结构化模板；保留最近 20k；`/compact` 可带 instructions；不删原 transcript |
| M5 工作树污染 | 验收不可分离 | 基线决定 A/B/C；M6 前记录哈希；按路径提交 |
| 单 executor 阻塞 | 多标签页卡 | 明确单用户；UI 排队提示；P2 另立多 executor 计划 |
| real 非空 resume 违反现行 AGENTS 约束 | 安全/合规风险 | M9 前先更新 AGENTS + 安全评审；未批则不做，只保留 fake resume |
| 秘密进入 transcript | 导出泄露 | key 只读 env；render secret 扫描；导出警告；文件 0600 |
| SQL policy 测试漂移 | S4/S1/S9 红 | 只改 `loop_policy`；跑全套；不放宽断言 |
| `finish_length` 部分输出被误当完整 | 用户误判 | `meta.truncated=true`；UI 明确提示；不执行截断 tool calls |

回滚顺序：M10 → M9 → M8 → M7 → M6。M7 回滚保留 transcript 文件；M6 回滚恢复 policy/limits。任何回滚都要重跑对应 gate，不能只改常量。

---

## 11. 交付与文档

- 每个里程碑：全 gate 绿 → 更新 `v24/ui/README.md`、新的 conformance matrix/deviation ledger → 按路径 `git add` → 本地 milestone commit。**不 push、不 amend、不改 main。**
- 提交信息沿用 `<版本>: <祈使句摘要>`，例如 `v24: add session transcript and compaction`。
- 不把 M5 的证据文件、prompt-exports、`.uidata`、journal、transcript 提交进 Git；它们应在 `.gitignore` 或仓库外。
- 每个里程碑的 receipt 记录：HEAD、source map、命令、exit、日志 SHA256、last line、真实 provider 是否使用（应为否）。
- 若用户当前明确要求“不暂存、不提交”，以用户指令优先；计划不授权提交。

---

## 12. 开放问题（需协调者拍板）

| 问题 | 选项 | 建议默认 |
|---|---|---|
| 是否接受 `loop_policy` v2 cutover | 接受 / Plan B（4k cap、无 SQL） | 接受 v2；否则“基础可用”打折 |
| 64k 还是 128k context | 64k 先上线 / 128k 一步到位 | 64k；128k 作为 ModelSpec 扩展 |
| Summary 用 run 还是 UI 直连 | summary run / 直连 | summary run；durable、可测 |
| 模型清单 | 仅 DeepSeek / DeepSeek+OpenAI-compatible / 加本地 | 前两者；本地 P2 |
| MCP 是否进 M10 | 生成式 artifact / 不做 / 万能 mcp_call | 生成式 artifact 或不做；不假装 parity |
| 是否做 per-call 审批 | 不做 / host hook + UI | P0 不做；Web 暴露前必须做 |
| 是否保留 `/resume` token | 保留兼容 / 只 id | 保留兼容，但列表/id 为主 |
| real 非空 resume | 先改 AGENTS + 安全评审 / 不做 | 先评审；未批不做 |
| 多用户/多 executor | 本计划不做 / 另立计划 | 本计划不做 |
| 图片输入 | P2 / 进 M10 | P2 |

---

## 附录 A：Pi 功能对齐矩阵（简版）

| 能力 | Pi | v24 现在 | 本计划 |
|---|---|---|---|
| 工具 | 7 内置 | 11（7+4） | 保持 |
| 并行工具 | 默认 parallel | 16 batch barrier | 保持 |
| 截断/spill | 50KB/2000 行 + temp | 32KB/2000 行 + spill | 保持 |
| 技能 | 发现 + progressive + `/skill:` | 2 个固定 + 按需读 | M10 多根/命令 |
| 上下文 | 完整 transcript | 3,950 字符摘要 | **M7** |
| Compaction | 自动/手动 + branch summary | 无 | **M7**（branch 后续） |
| 流式 | token/thinking/live tools | `stream:false` | **M8** |
| 中断/重试 | Esc/自动重试 | 排队取消/无重试 | **M8** |
| 队列 | steer + follow-up | steer latest-wins | **M8** |
| 模型 | 多 provider + `/model` | 固定 DeepSeek | **M9** |
| 会话 | 列表/命名/tree/fork/export | token resume | **M9**（tree/fork 后续） |
| 输入 | @file/image/!bash | 纯文本 | **M10**（图片后续） |
| 扩展 | TS hooks/MCP/packages | tool ABI only | M10 评估 |
| MCP | stdio/HTTP/OAuth | 无 | M10 可选 |
| 模式 | TUI/print/JSON/RPC/SDK | Web only | 不做 |
| 子代理/plan | 无内置 | 无 | 不做 |
| 审批 | 无内置（extension/容器） | 无（栅栏/toolset） | P2 评估 |

## 附录 B：建议命令集

| 命令 | 行为 | 里程碑 |
|---|---|---|
| `/help` | 命令/快捷键/限制 | M9 |
| `/new` | 新会话（新 scope/realm） | 现有 |
| `/sessions` | 列表：序号、名称、模型、消息数、token、更新时间 | M9 |
| `/resume <n|id>` | 恢复；不强制 token | M9 |
| `/name <text>` | 命名 | M9 |
| `/model [id]` | 查看/切换当前会话模型 | M9 |
| `/thinking [level]` | 查看/切换（若 provider 支持） | M9/P1 |
| `/compact [instructions]` | 手动 compaction | M7 |
| `/queue` | 查看 steer/follow-up 队列 | M8 |
| `/follow <text>` | 当前 run 结束后执行 | M8 |
| `/steer <text>` | 下一轮边界注入 | 现有 |
| `/retry` | 重试最后一条 user | M8 |
| `/cancel` | 中断当前 run | 现有（M8 真中断） |
| `/close` | 关闭 scope、释放资源 | 现有 |
| `/export [jsonl|md]` | 下载会话 | M9 |
| `/session` | 当前统计/context/cost | M9 |
| `/tools` `/skills` | 当前工具/技能 | 现有 |
| `/skill:<name>` | 注入/查看技能 | M10 |
| `/prompt <name> [args]` | 展开 prompt template | M10 |
| `/mcp` | MCP 列表/启停（若做） | M10 |

## 附录 C：配置

| 变量 | 作用 | 默认 |
|---|---|---|
| `V24_UI_MODE` | `fake|real` | `fake` |
| `V24_UI_WORKSPACE_ROOT` | 工作区绝对路径 | `.uidata/workspace`（fake） |
| `V24_UI_TOOLSET` | `read|write|exec` | real=`read`；fake 有 workspace 时 `read`，否则 `exec` |
| `V24_SKILLS_ROOT` | 技能根；M10 支持多根 | 无 |
| `V24_UI_LIMITS_PROFILE` | `usable|legacy` | `usable`（新会话）；旧会话按记录 |
| `V24_UI_MODEL` | 默认模型 id | `deepseek/deepseek-chat` |
| `V24_UI_MODELS` | models.json 路径 | `v24/ui/models.json` |
| `V24_UI_STREAM` | `1|0` | `1`（M8 后） |
| `V24_UI_CONTEXT_V2` | `1|0` | `1`（M7 后） |
| `V24_UI_MCP` | `1|0`（若做） | `0` |
| `V24_UI_MCP_CONFIG` | 实际 MCP 配置路径（0600，repo 外） | 无 |
| `DEEPSEEK_API_KEY` | provider key | 无（缺失 → `credentials_absent`） |
| `OPENAI_API_KEY` | 兼容回退 | 无 |

不新增明文 key 文件；`models.json` 只放 `api_key_env` 名称。

## 附录 D：参考

- `docs/plans/v24-chainlit-agent-runtime-2026-11-01.md`：现有 M1–M5 计划、W10–W13 残留、§1.2 非目标。
- `v24/ui/README.md`：当前 M5 状态、limits、部署边界。
- `docs/reviews/v24-ui-conformance-matrix-2026-11-01.md`、`docs/reviews/v24-ui-deviation-ledger-2026-11-01.md`：现有证据/偏差格式。
- `v24/s4/README.md`：C17–C23（model/tool/budget/steer/interaction）。
- `v24/host/deepseek.py`：当前 adapter 合同、`_messages()`、`finish_length`。
- `v24/host/worker.py`：`_history()`、model/tool dispatch、lease。
- `v24/ui/sessions.py`：`history_block()`、`SessionStore`。
- Pi docs：`packages/coding-agent/docs/usage.md`、`sessions.md`、`compaction.md`、`extensions.md`、`mcp.md`、`models.md`、`cli.md`。
- Pi core：`packages/agent/src/agent-loop.ts`、`packages/coding-agent/src/core/session-manager.ts`、`core/compaction/compaction.ts`。

---

## 修订记录

- 2026-11-04：初稿。基于 `a6ba596`、当前 M5 工作树、Pi 当前文档与源码；未实施、未提交。
