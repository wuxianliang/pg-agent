# v24 六动词会话控制落地计划（2026-11-05）

> **核验状态（2026-11-05）**：评审 §5 的五项决策已经两条 Oracle lane 裁决并由协调者合并，见
> [`v24-session-control-decision-record-2026-11-05.md`](../reviews/v24-session-control-decision-record-2026-11-05.md)。
> 本计划已按裁决修订：服务在 `v24/session/`，S0 交付 Python 进程内 API + Chainlit UI，单 owner 线程 + 单执行线程，
> 持久 start 索引 + 两相位 receipt，S0 禁 poll 增量分页，S1 另走 frozen-baseline bump。

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 状态 | **Adopted（2026-11-05）**；五项决策已定稿；S0-M1/M2/M3 已实现并通过 gate；M4 待开工；每个里程碑测试全绿后按路径提交 |
| 目标 | 把 v24 的 run 级六动词升级为 RepoPrompt 式 session 级六动词 |
| 配套 | 决策记录：`docs/reviews/v24-session-control-decision-record-2026-11-05.md`；设计：`docs/designs/v24-session-control-design-verified-2026-11-05.md`；API：`docs/designs/v24-session-control-api-2026-11-05.md` |
| 提交策略 | 每个 S0 里程碑测试全绿、收尾工件更新后，按路径一次提交；S1 需 frozen-baseline bump 独立获批后单独提交 |

> **M1 进展（2026-11-05）**：`SessionStore` v2、迁移/`.v1.bak`/`.prev`、`SessionService.start/poll`、
> start/replay/deferred、cursor 前缀与 import 边界 gate 已落地。M1 三个 gate 全绿：
> `v24/session/test_session_verbs.py`、`v24/ui/test_ui_gate.py`、`v24/ui/test_backend_regressions.py`；
> `v24/ui/test_real_entry.py` 也通过。
>
> **M2 进展（2026-11-05）**：`SessionService.wait/cancel`、七种 wake（`run_started > terminal >
> interaction > epoch > event > timeout > none`）、无 cursor 高水位、per-session `cursors` +
> winner 轮转、`all_terminal`、revision-only 不唤醒、`registration_stale → epoch + event_seq=0`；
> cancel 的活动/终态/starting/deferred/replay 与 `expected_run_id`/`expected_generation` CAS 已落地。
> `wait` 不写 store，`cancel` 写 receipt 但不重写 run。新 gate
> (`v24/session/test_session_verbs.py`) 与 `v24/s7/test_g6.py`、`v24/ui/test_ui_gate.py` 全绿。
> 真实 `AgentRuntime` adapter 与 UI 全量切换按计划留在 M4；当前 app 仍走 `SessionStore` 兼容入口。
> S0 冻结边界 `git diff -- v24/sql v24/load.py v24/host/deepseek.py` 为空。
>
> **M3 进展（2026-11-05）**：`SessionService.steer/respond`、活动/终态/`waiting`/`blocked_unknown`
> 分派、同 key replay、跨重启 replay、`expected_run_id`/`expected_generation` CAS、终态新 run
> `run_no+1` 与历史 system seed、活动 steer `user_turn_no+1`、256 receipt 窗口、respond 精确
> `interaction_id`/`waiting_unsupported` 已落地。M3 三个 gate 全绿：
> `v24/session/test_session_verbs.py`、`v24/ui/test_backend_regressions.py`、`v24/s4/test_g2b.py`。
> `steer(wait=true)` 在写提交后复用 `wait`；`respond` 不增加 `user_turn_no`。
> 真实 `AgentRuntimeBackend` 仍在 M4，S0 real respond 固定 `waiting_unsupported`。

## 0. 完成定义（DoD）

### 0.1 S0（必须）

- 客户端只持 `session_id`，即可完成 `start → poll/wait → steer → respond → cancel` 全生命周期。
- **respond 的 S0 承诺限定为 fake/scripted**；real 模式固定 `waiting_unsupported`，零 run 写。
- 终态 `steer` 在同一会话内开新 run；`waiting` 下 `steer` 被拒绝并提示 `respond`；`blocked_unknown` 下 `steer` 被拒绝。
- 同 `request_key` 重放不重复建会话/run、不重复加 `user_turn_no`；同 key 异 payload `request_conflict`；每 session 保留 256 条 completed receipt。
- 一个会话同时至多一个活动 run；不同会话可独立控制；provider 执行串行，但控制入口不被 provider 阻塞，roster 有界公平推进。
- 进程重启后：running 可重新驱动，waiting 保留 interaction，terminal 不重开；`start` 可从 `start_index`/intent/receipt 恢复。
- `wait` 无已知 waiting-steer 丢失窗口；多会话用 per-session cursor 映射 + winner 轮转。
- 不新增/修改 `v24/sql/**`；`v24/load.py`、`v24/host/deepseek.py` 也不改；按 §6 固定清单跑既有 gate。
- `sessions.json` v1 可迁移到 v2；旧 `/resume <run_id>` 仍可用。
- S0 收口时 `git diff -- v24/sql v24/load.py v24/host/deepseek.py` 为空。

### 0.2 S1（目标，需批准）

- `runs.session_id` 不可变；`UNIQUE (session_id) WHERE session_id IS NOT NULL AND ended_at IS NULL` 生效。
- 迁移以 `sessions.json` 的 conversation/bindings 为单位，不按 scope 合并；spawn 子 run 保持 NULL。
- 迁移后每个旧 conversation 的顶层 run 都能解析到唯一 session；同一 conversation 多活动 run 必须迁移失败并人工处理。
- 六动词合同不变；只替换存储/解析实现。
- 需独立 frozen-baseline bump：三套哈希 + D-UI-6 + `load.py`/`test_g1` 闭集；规格、DDL、加载清单、覆盖矩阵、偏差台账同步更新；全部 v24 gate 全绿。

### 0.3 非目标

- 不改 `advance` 的单一写口，不建 `turns`/`run_attempts`/`session_status` 表。
- 不实现多用户、多执行器、worktree、模型目录、handoff、会话树。
- 不把 provider 原文写入 DB。
- 不在本计划内做真实 provider gate；真实调用仍只走受控入口。

## 1. 约束

1. **冻结内核**：S0 不碰 `v24/sql/**`、`v24/load.py`；S1 的每处变更都必须作为规格修订，不得以“顺手加列”方式进入。
2. **既有 gate 不破坏**：每个里程碑都跑相关既有 gate；S1 还要跑 DDL 闭集、start 解释器、spawn、recovery。
3. **测试是独立脚本**：`uv run python ...`，退出码 0 = 通过；不引入 pytest 依赖。
4. **不用真实 provider**：S0 gate 全部用 `ScriptedUiAdapter`/FakeLLM；真实 provider 只作手动验收。
5. **不静默截断/不静默丢弃**：`superseded`、`timeout`、`setup_incomplete` 都要在响应/UI 可见。
6. **按路径提交**：不使用 `git add -A`；不提交 `.env`、key、`sessions.json` 等私有数据。
7. **S0 可以写代码**：决策已定稿；M1 只新增 `v24/session/**`、改 `v24/ui/sessions.py`/`app.py` 与测试，不改 `v24/sql/**`、`v24/load.py`、`v24/host/deepseek.py`。
8. **分支/提交例外**：若实现落在 `v24/ui-chainlit` 的已授权里程碑，按 `AGENTS.md` 的本地分支例外，由协调者 review 后逐路径提交；当前在 `main`，按 `AGENTS.md` 的里程碑规则执行。

## 2. 实施策略

```text
S0-M1  SessionStore v2 + start/poll
  │
S0-M2  wait/cancel + cursor + session lock
  │
S0-M3  steer active/terminal + respond + idempotency
  │
S0-M4  recovery + multi-session + UI migration
  │
  ├─ 观察一个版本周期；API 稳定
  ▼
S1-M5  runs.session_id + 部分唯一索引 + 读函数（需规格修订）
  │
S2-M6  v24.sessions 目录（仅在产品需要时）
```

**为什么先 S0**：六动词语义、UI 迁移、幂等/cursor 都能在宿主层验证；S0 的失败可回滚，不会把冻结内核的哈希和迁移风险提前引爆。S1 只替换“session 归属/一个活动 run”的实现，不改客户端合同。

**线程模型（2026-11-05 裁决）**：`session-owner` 单线程拥有 store/runtime/roster/waiter，执行控制与 finish/settle；`session-exec` 单线程（并发 1）只跑 adapter/tool，不碰 DB/journal；调用方 `wait` 线程只做短读+退避。`HostWorker.run_once` 拆为 `prepare/execute/finish`。这不是多 driver，也不是并发 4；provider 执行仍串行，独立的是控制入口与 roster 公平性。

**交付面**：S0 是 Python 进程内 `SessionService` + Chainlit UI adapter；MCP/HTTP 为 reserved。`v24.ui.real` CLI smoke 保持可运行，但不是通用 CLI 合同。

**与调查“只做一件事”的关系**：调查建议若只做一件事，先做只读 `host_run_ledger`（零 schema，四计数）。本计划把 ledger 放在 S1-M5 的第一步，因为 S0 的六动词控制不依赖 `model_round_no`/`tool_round_no` 完整；但若排期只允许一个动作，应优先 ledger，而不是 S0 门面。**不要把它塞进 S0**：S0 的卖点是“不改 `v24/sql/**`、可干净回滚”，一旦并行加 ledger，这个承诺就失效；要做就作为 S1 的独立前置提交。

## 3. 里程碑

### S0-M1：会话注册表 v2 + `start`/`poll`

**目标**

- `SessionStore` 升到 `format_version=2`：`session_id`、`state`、`counters`、`session_revision`、`counter_origin`、`owner_principal_id`、`start_index`、`receipts[]`、`pending_intent`、transcript 摘要；兼容读取 v1 并写 `.v1.bak`/`.prev`。
- 新增 `v24/session/`：`SessionService` 骨架、`start`、`poll`、快照/cursor 组合、owner-thread-checked store 与串行域；不 import Chainlit/`v24.ui`。
- `start` 通过注入的 `SessionBackend` 完成“查 start_index → 写 intent → mint session → scope/install → 当前签名 `v24.start` → bind → 首个 user turn → completed receipt”的可恢复流程；S0 不把 `session_id` 传给内核。M1 gate 用 scripted backend；真实 `AgentRuntime` adapter 与 UI 切换在 M4 一起接。
- `poll` 组合 `SessionStore` + `v24.poll`；`changed` 按 cursor；`include_events=true` 只返回最早 64 条并推进 `event_seq` 到已返回前缀最大 seq。

**文件**

| 文件 | 变更 |
|---|---|
| `v24/ui/sessions.py` | VERSION=2；迁移；字段；`append_turn` 改为 session 语义；`.v1.bak`/`.prev`；兼容 v1 |
| `v24/session/__init__.py` | 新增：包入口 |
| `v24/session/store.py` | 新增：owner 线程 store、v2 读写、迁移、receipts/start_index/intent |
| `v24/session/service.py` | 新增：`SessionService.start/poll/snapshot/cursor/replay` |
| `v24/session/wire.py` | 新增：请求/响应形状、canonical digest、cursor 工具 |
| `v24/session/models.py` | 新增：`StartResult` 与 `SessionBackend` 协议 |
| `v24/session/driver.py` | 新增：串行域骨架；M2 补 owner/exec 线程与 prepare/execute/finish |
| `v24/ui/app.py` | `new`/首条消息可先双路径走 `SessionService.start`；M4 全量切换 |
| `v24/session/test_session_verbs.py` | 新增 headless gate：start/poll、迁移、import 检查 |
| `v24/ui/README.md` | 记录新入口/迁移/开关 |

**测试**

- `start` 返回 `session_id/run_id/snapshot`；`poll` 可见 running。
- `start` 同 key 重放同 session/run（`replay`）；`intent` 未完成时同 key 返回同一 `deferred`；异 payload `request_conflict`。
- `start` 带 `session_id` → `invalid_args`。
- v1 `sessions.json` 迁移后旧 conversation 可读；`.v1.bak`/`.prev` 存在；损坏文件整体 fail-closed 且不覆盖原件。
- `poll` 无副作用：revision 不变、无新 effect/request；`include_events=false` 不推进 `event_seq`；`include_events=true` 推进到已返回前缀最大 seq。
- 静态 import 断言：`v24/session/**` 不 import `chainlit`/`v24.ui`。

**Gate**

```bash
uv run python v24/session/test_session_verbs.py
uv run python v24/ui/test_ui_gate.py
uv run python v24/ui/test_backend_regressions.py
```

**验收**

- 新 gate 全绿；既有 UI gate 全绿；`git diff -- v24/sql v24/load.py v24/host/deepseek.py` 为空。
- `sessions.json` 迁移前后可回滚；不删除旧文件；receipt/start_index/attempt 均不写入日志/快照。

**风险**

- v1→v2 字段迁移遗漏；用双读 + 迁移测试覆盖。
- `start` 半途失败留下孤儿 scope；用 `intent` + `host_request` 恢复测试覆盖。
- owner 线程与 UI 旧路径双写；M1 只允许一个入口写 store，开关关闭时旧路径只读。

---

### S0-M2：`wait`/`cancel` + cursor + 会话串行域

**目标**

- `SessionService.wait`：短读 + 条件变量/退避；支持 `run_started/terminal/interaction/epoch/event/timeout/none` 七种（后六种 + run_started 共七种）；`timeout=0` 等价 poll；无 cursor 先取高水位；`include_events=false` 不产生 event 唤醒。
- `SessionService.cancel`：活动 run 调 `v24.cancel`；终态 `already_terminal`；`starting` 先按 `run_request_key` 恢复 run receipt，再取消 run 或清理本地 intent。
- 共享串行域：owner 线程执行 wait 的短读、cancel、driver finish；`wait` 只做毫秒级短读，不在 owner 睡眠；per-run 锁只在无法搬回 owner 的 settle 使用。
- cursor 规范化：`session_id/run_id/run_revision/event_seq/registration_generation/epoch_no/generation/interaction_id/user_turn_no/session_revision`；多会话用 `cursors` 映射。
- `registration_stale` 映射为 `epoch` + 新快照 + `event_seq=0`；`all_terminal` 布尔；revision-only 默认不唤醒。

**文件**

| 文件 | 变更 |
|---|---|
| `v24/session/service.py` | `wait`、`cancel`、`SessionSerialDomain`、cursor 工具、多会话 winner |
| `v24/session/driver.py` | owner 短读 + waiter 通知；driver 让出规则；锁序注释 |
| `v24/ui/app.py` | `/cancel`、`/resume` 的等待路径改走 service（可保留旧路径到 M4） |
| `v24/session/test_session_verbs.py` | wait/cancel/七种 wake/多会话用例 |
| `v24/ui/README.md` | 等待/取消/多会话语义 |

**测试**

- `wait`：`run_started/terminal/interaction/epoch/event/timeout/none` 七种；`timeout=0`；无 cursor 高水位；`include_events=false` 不推进；`registration_stale` → `epoch` + reset；revision-only 不唤醒。
- `wait` 不写：`runs.revision`、`effects`、`requests` 均不变。
- `cancel` 活动 → cancelled；终态 → `already_terminal`；同 key replay；`starting` 先恢复 receipt 再清理。
- `cancel` 与 worker 结算并发：以 run 投影为准，不出现“cancelled 又被 completed”。
- 多会话：两个 session，一个先 terminal；winner 正确；per-session `cursors` 只更新 winner；unknown 逐项 `ok:false`；`all_terminal`。

**Gate**

```bash
uv run python v24/session/test_session_verbs.py
uv run python v24/ui/test_ui_gate.py
uv run python v24/s7/test_g6.py   # 并发/控制世代相关
```

**验收**

- 七种 wake 全部有断言；wait 期间无打开事务（可用连接状态断言/日志）。
- cancel 不删除 session，terminal 后仍可 poll；starting 清理不重复 `v24.start`。

**风险**

- 条件变量与 worker 线程的唤醒丢失；用“短读循环 + 超时”兜底，不依赖单次通知。
- 锁顺序与 `advance` 的 G 锁冲突；固定 `run → DB`，禁止反向；不得跨 provider 持有。
- owner 线程被 wait 阻塞；验收用另一个会话的 start/poll 在 1 秒内返回作断言。

---

### S0-M3：`steer` 活动/终态 + `respond` + 幂等

**目标**

- `steer` 活动：`v24.steer`；返回 `queued/superseded`；`user_turn_no+1`；receipt 的 `resolved_variant=steer_active`。
- `steer` 终态：同 session 调当前签名 `v24.start`；`run_no+1`、`user_turn_no+1`、`started=true`；seed 先注入 system 历史块；`resolved_variant=steer_new_run`。
- `steer` waiting：owner 内预检+写互斥；`interaction_pending` 零 run 写（只写 rejected receipt）；`blocked_unknown` 同样拒绝。
- `respond`：精确 interaction；scalar→object 归一化；不增加 `user_turn_no`；real 固定 `waiting_unsupported`。
- 幂等：receipt 先查 `(principal, session, op, key_hash)`，再按 `run_request_key` 查 `host_request`；同 key 不产生第二个 run；deferred 冻结。

**文件**

| 文件 | 变更 |
|---|---|
| `v24/session/service.py` | `steer`、`respond`、key 派生、replay、256 receipt 窗口 |
| `v24/session/driver.py` | owner 串行域；`prepare/execute/finish` 接入；waiting-steer barrier 钩子 |
| `v24/ui/app.py` | 普通文本/`/steer`/AskUser 回答改走 service（可双路径到 M4） |
| `v24/session/seed.py`（可选） | 会话历史 → messages 的 seed 构造 |
| `v24/session/test_session_verbs.py` | steer/respond/幂等/waiting race 用例 |
| `v24/ui/README.md` | 终态续接/等待输入/real 能力边界 |

**测试**

- 活动 steer：同 `run_id`，`epoch_no`/`driving_generation` 增加；`pending_steer` 出现；旧 pending 被标记 `superseded`。
- 终态 steer：新 `run_id`、同 session、`run_no+1`；新 run 的 seed 含上轮 final。
- 终态 steer 同 key 重放：只产生一个 run；状态变化后重试仍按首次 `resolved_variant`，不改成活动路径。
- waiting steer：`interaction_pending`，`runs.interaction` 不变；barrier 在“预检后、内核写前”插入 interaction settle，验证两者都不会清除已提交 interaction。
- `blocked_unknown` steer：拒绝，零 run 写。
- respond：正确 id 成功；错误 id `interaction_mismatch` 零写；`user_turn_no` 不变；real 返回 `waiting_unsupported` 且零 run 写。
- respond 后 run 回到 running；wait 能看到下一事件。

**Gate**

```bash
uv run python v24/session/test_session_verbs.py
uv run python v24/ui/test_backend_regressions.py
uv run python v24/s4/test_g2b.py   # loop/steer/respond 回归
```

**验收**

- 终态 steer 是“同 session 新 run”，不是“run 级 already_terminal 透传”。
- 同 key 重放不增加 `run_no`/`user_turn_no`；每次写动词的同 key 异 payload、跨状态/重启 replay 都有断言。
- `blocked_unknown` 不被自动续跑；real respond 不假装可用。

**风险**

- 终态与活动竞态：owner 内重读；同 key 只允许一个结果。
- seed 过长/工具配对断裂：先只注入 system 历史块；M7 再做完整 transcript seed。
- `pending_steer` 单槽覆盖：必须返回 `superseded`，UI 显式提示。
- adapter 生命周期 / finished 未 settle：M3 只接 fake/scripted，M4 再覆盖真实恢复路径。

---

### S0-M4：恢复 + 多会话 + UI 迁移收口

**目标**

- 启动恢复：重建 service/store/adapter/journal/driver（不是只重开 `AgentRuntime`）；按 `state`/run 状态重新 `rehydrate`/`drive`/投影 interaction；覆盖 dispatch_started、finished 未 settle、live/expired lease、unknown 不重放、detached 多 session 推进；terminal 不重开。
- 多会话 `poll(session_ids)`；`wait(session_ids)` 返回首个 interesting，per-session `cursors` 映射 + winner 轮转 + `all_terminal`。
- UI 全量迁移：`/new`、普通文本、`/cancel`、AskUser、`/resume`、`/close` 都走 `SessionService` 或管理面。
- 特性开关 `V24_SESSION_API`；默认关闭，测试通过后开；开关只控制入口，不改变 v2 格式。
- 旧 `/resume <run_id>` 解析 run→session；保留一个版本周期。
- 回滚脚本：归档 v2 增量 → 恢复 `.v1.bak` → 校验 v1 可加载。

**文件**

| 文件 | 变更 |
|---|---|
| `v24/session/service.py` | 恢复、多会话、管理面方法 |
| `v24/session/driver.py` | 重建 owner/exec、roster 恢复、finished 未 settle 处理 |
| `v24/session/rollback.py` | 新增：归档 + 恢复 `.v1.bak` + 校验 |
| `v24/ui/session_backend.py` | 新增：`AgentRuntimeBackend`，实现 scope/install/start/poll |
| `v24/ui/app.py` | 全量切换/双路径；启动恢复 |
| `v24/ui/sessions.py` | transcript 迁移/兼容；关闭状态；`.prev` |
| `v24/session/test_session_verbs.py` | 恢复/多会话/迁移/回滚用例 |
| `v24/ui/README.md` | 开关、迁移、回滚、数据丢失窗口 |

**测试**

- 进程重启（重建 service/store/adapter/journal/driver）：running 重新驱动；waiting 保留 interaction；terminal 不重开；finished 未 settle 不重复 final；unknown 不重放。
- 多会话 poll/wait：两个会话，一个先 terminal，winner 正确；per-session `cursors` 只更新 winner；未知 session 逐项 `ok:false`；`all_terminal`。
- 旧 `/resume <run_id>` 仍能恢复；新路径只认 `session_id`。
- `sessions.json` 损坏 → 整体 fail-closed，保留原件并给诊断；不声称“单会话损坏不影响其他会话”。
- 回滚：归档 v2 增量 -> 恢复 `.v1.bak` -> v1 可加载；归档不覆盖；升级期间新建 session/turn 对旧 UI 不可见。
- 不把 key/DSN/prompt 原文写入快照/错误/日志（扫描断言）。

**Gate**

```bash
uv run python v24/session/test_session_verbs.py
uv run python v24/ui/test_ui_gate.py
uv run python v24/ui/test_backend_regressions.py
uv run python v24/ui/test_audit_m5.py
uv run python v24/ui/test_artifact_regressions.py
```

**验收**

- 开关关闭时旧行为不变；开启时新行为全绿；开关不双写两套状态。
- 回滚：归档 + `.v1.bak`，不是“关闭开关 + 旧代码读 v1 字段”。
- 不新增 SQL 文件；`git diff -- v24/sql v24/load.py v24/host/deepseek.py` 为空。

**风险**

- 双路径状态不一致；开关只影响入口，不双写两套状态。
- 恢复时重复驱动/重复 final；以 run 投影/idempotent settle 为准；finished 未 settle 是重点。
- 多会话等待饥饿；S0 只保证“第一个 interesting + winner 轮转”，不承诺全局公平。

---

### S1-M5：Kernel session anchor（需 frozen-baseline bump 独立批准）

**前置**

- S0 已稳定一个版本周期；API 合同未变。
- 独立批准件明确：`runs.session_id` 的语义、授权、迁移、`start` 解释器改动、三套 FROZEN 哈希、D-UI-6 路径、`load.py`/`test_g1` 闭集、migration executor。
- 协调者/用户拍板 `cancel-late` 计数规则；`s14/test_g12.py` 目前不存在，先决定新建或并入既有 gate。

**目标**

- 先补调查第 1 步的只读 `v24.host_run_ledger(run_id)`（四计数 + `late` + `generation`，零 schema），用它给会话快照的 `model_round_no`/`tool_round_no` 提供权威；再加会话锚。
- `runs.session_id uuid NULL` 不可变；`i_runs_session`；`u_runs_session_active ... WHERE ended_at IS NULL`。
- `v24.start` 接受可选 `session_id`（**S1-only**；S0 已按当前签名实现，不得提前改）；首个 run 创建成员关系；后续 run 校验同 scope/principal。
- 新增只读：`v24.host_session_runs`、`v24.host_session_snapshot`；可选 `v24.poll_session`/`v24.wait_session_check`。
- 宿主 `SessionService` 的 resolve/one-active 改为 DB 兜底；`sessions.json` 仍存元数据。
- 迁移以 `sessions.json` 的 conversation/bindings 为单位（不按 scope）：同一 run 被两个 conversation 绑定则失败；spawn 子 run 保持 NULL；每个 conversation 多活动 run 则失败并人工处理。

**文件**

| 文件 | 变更 |
|---|---|
| `v24/sql/10_schema.sql` | `runs.session_id` + 索引/约束 |
| `v24/sql/40_interpreters.sql` | `command_start` 的 run delta/JSON 相等校验纳入 session_id |
| `v24/sql/47_verbs.sql` | `v24.start` 可选 session_id；新增会话读函数 |
| `v24/sql/49_host_reads.sql` | `host_session_runs`/`host_session_snapshot` |
| `v24/load.py` | 若新增 SQL 文件，追加 `SQL_LOAD_ORDER` |
| `v24/s1/test_ddl.py` | 闭集/索引断言 |
| `v24/s14/test_g12.py` | 拟新增 S1 gate；当前不存在 |
| `v24/cordis/dp4/test_closeout.py` | FROZEN 12 文件哈希 |
| `v24/cordis/dp5/test_boundaries.py` | FROZEN + D-UI-6 六路径 |
| `v24/cordis/dp6/test_boundaries.py` | FROZEN + D-UI-6 六路径 |
| `v24/ui/d_ui_6_acl.py` | `50_permissions.sql` digest / 替换表 |
| `docs/designs/v24-pg-agent-2026-10-22.md` | 规格修订 |
| `docs/reviews/*` | 覆盖矩阵/偏差台账 |

**测试**

- 同 session 第二个未终态 run 被 DB 拒绝。
- 迁移前每个 conversation 的 run 都能解析到 session；同一 conversation 多活动 run 迁移失败并报告；spawn 子 run 保持 NULL。
- `v24.start` 带不存在 session 时创建；带存在但 scope/principal 不符时 `not_found_or_denied`。
- 会话读函数分页/授权/游标。
- S0 六动词 gate 在 S1 上全部仍绿（合同不变）。

**Gate**

```bash
uv run python v24/s14/test_g12.py          # 拟新增；不存在则先并入既有 gate
uv run python v24/cordis/dp4/test_closeout.py
uv run python v24/cordis/dp5/test_boundaries.py
uv run python v24/cordis/dp6/test_boundaries.py
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s6/test_g5.py
uv run python v24/s7/test_g6.py
uv run python v24/s8/test_g7.py
uv run python v24/s9/test_g8.py
uv run python v24/session/test_session_verbs.py
```

**验收**

- DB 可回答会话成员/活动 run；宿主不再依赖“恰好一个 scope”假设。
- 规格/DDL 闭集/哈希门禁全部更新；Cordis DP4 的冻结哈希范围明确。
- 迁移可回滚（删除列/索引前先备份；或保留列只停用读写）。
- S1 的 spec/DDL/哈希门禁与 D-UI-6 同一批准件覆盖；不得拆成“顺手加列”。

**风险**

- 解释器精确 JSON 相等校验漏改导致 start 全红；用现有 start 向量逐条回归。
- 部分唯一索引在迁移时冲突；先修数据，不静默跳过。
- `session_id` 授权漏洞；所有读/写都检查 principal/scope。

---

### S2-M6：Session catalog（可选，暂不启动）

- `v24.sessions` 表：`session_id/principal_id/scope_id/name/created_at/closed_at/archived/metadata`；**不存 status/active_run_id**。
- 会话列表/搜索/归档/导出；多用户/多主机。
- 只有出现明确产品需求时才启动；启动前另写规格修订。

## 4. 测试矩阵（S0 核心）

| # | 场景 | 操作 | 期望 | Gate |
|---|---|---|---|---|
| 1 | 新建会话 | `start` | `session_id/run_id`；snapshot running | M1 |
| 2 | 重放 start | 同 key 同 payload | 同 session/run；`replay` | M1 |
| 3 | start 冲突 | 同 key 异 payload | `request_conflict` | M1 |
| 4 | start 带 session_id | `start(session_id=…)` | `invalid_args` | M1 |
| 5 | poll 纯读 | poll 两次 | 第二次 `changed=false`；无新 effect | M1 |
| 6 | wait terminal | wait 终态 | `wake.reason=terminal` | M2 |
| 7 | wait interaction | wait waiting | `wake.reason=interaction`；顶层 id | M2 |
| 8 | wait run_started | 另一客户端 steer 终态 | 新 run_id；`run_started` | M2/M3 |
| 9 | wait timeout | timeout=0 | `ready=false, reason=none` | M2 |
| 10 | cancel 活动 | cancel | cancelled | M2 |
| 11 | cancel 终态 | 再 cancel | `already_terminal` | M2 |
| 12 | cancel 重放 | 同 key | 原响应 | M2 |
| 13 | steer 活动 | steer | 同 run；epoch+1；user_turn+1 | M3 |
| 14 | steer 覆盖 | 连续两次 steer | `superseded=true` | M3 |
| 15 | steer waiting | steer | `interaction_pending` 零写 | M3 |
| 16 | steer 终态 | steer | 新 run；run_no+1 | M3 |
| 17 | steer blocked | steer | `blocked_unknown` 零写 | M3 |
| 18 | steer 重放 | 同 key | 不新增 run | M3 |
| 19 | respond 正确 | respond | 成功；user_turn 不变 | M3 |
| 20 | respond 错误 id | respond | `interaction_mismatch` | M3 |
| 21 | respond 已消费 | 新 key 再答 | `interaction_mismatch` | M3 |
| 22 | 授权 | 其他 principal | `not_found_or_denied` | M1/M4 |
| 23 | 重启 running | 重开 runtime | 重新驱动，不重复 final | M4 |
| 24 | 重启 waiting | 重开 runtime | interaction 保留 | M4 |
| 25 | 重启 terminal | 重开 runtime | 不重开 | M4 |
| 26 | 旧 resume | `/resume <run_id>` | 解析到 session | M4 |
| 27 | 多会话 poll | 两个 session | 各自快照 | M4 |
| 28 | 多会话 wait | 一个先 terminal | winner 正确 | M4 |
| 29 | 同 key start 后终态 steer | 复用 client key | 两个 run，均 committed | M3 |
| 30 | cursor 跨 session | 用 A 的 cursor poll B | `changed=true`，不报错 | M1 |
| 31 | poll >64 事件 | 连续 poll | 只回最早 64 条；cursor 推至已返回前缀最大 seq；不跳不重 | M1 |
| 32 | poll include_events=false | 两次 poll | `event_seq` 不变；不产生 event 唤醒 | M1/M2 |
| 33 | wait 无 cursor | 直接 wait | 先取高水位；不从 0 重放 | M2 |
| 34 | R2 已终态的 run_started | R1 终态 → steer 出 R2 → R2 终态 → wait | 先报 `run_started`；同 run 下一次报 `terminal` | M2/M3 |
| 35 | revision-only | run_revision 变化、event_seq 不变 | 默认不唤醒；正超时带 `changed=true` | M2 |
| 36 | registration_stale | 重注册后旧 cursor | `wake.reason=epoch` + 新快照 + `event_seq=0` | M2 |
| 37 | 多会话 wait 映射 | 两个 session + 各自 cursor | winner + `pending_session_ids` + 完整 `cursors`；只更新 winner | M4 |
| 38 | 启动同 key 重启重放 | committed 后重建 service | 从 start_index/receipt 返回原 envelope；不新建 | M4 |
| 39 | deferred 冻结 | intent 后同 key 重试 | 同一 deferred；不第二次变 committed | M1/M4 |
| 40 | 回滚 | 归档 v2 增量 → 恢复 `.v1.bak` | 旧代码可加载；归档完整；新数据不可见 | M4 |

## 5. 文件影响

### 5.1 S0 新增

| 文件 | 作用 |
|---|---|
| `v24/session/__init__.py` | 包入口 |
| `v24/session/service.py` | 六动词门面、snapshot/cursor、replay |
| `v24/session/store.py` | v2 store、迁移、start_index/receipts/intent、owner 所有权 |
| `v24/session/driver.py` | 串行域（M1）；M2 扩展 owner/exec、roster、prepare/execute/finish |
| `v24/session/wire.py` | 请求/响应形状、RFC 8785 digest、cursor 工具 |
| `v24/session/models.py` | `StartResult` 与 `SessionBackend` 协议 |
| `v24/session/seed.py` | 会话历史 seed（可选，M3） |
| `v24/session/rollback.py` | 归档 + `.v1.bak` 回滚（M4） |
| `v24/session/test_session_verbs.py` | S0 headless gate |
| `docs/reviews/v24-session-control-decision-record-2026-11-05.md` | 五项裁决 |
| `docs/designs/v24-session-control-design-verified-2026-11-05.md` | 核验版设计（已修订） |
| `docs/designs/v24-session-control-api-2026-11-05.md` | API 合同（已修订） |
| `docs/plans/v24-session-control-plan-2026-11-05.md` | 本计划（已修订） |

### 5.2 S0 修改

| 文件 | 变更 |
|---|---|
| `v24/ui/sessions.py` | v2、迁移、session 字段、`.v1.bak`/`.prev`、transcript 摘要 |
| `v24/ui/app.py` | 入口切换、恢复、开关；M4 全量 |
| `v24/ui/README.md` | 新入口/迁移/回滚/数据丢失窗口 |
| `v24/ui/test_ui_gate.py` | 必要时增加兼容断言（不改语义） |

### 5.3 明确不改（S0）

- `v24/sql/**` 全部；
- `v24/load.py`；
- `v24/host/deepseek.py`；
- `v24/host/worker.py` 的 run/effect 结算（S0 只在 service 侧包 prepare/execute/finish，不改 worker 的 run/effect 语义）；
- `v24/s3`/`v24/s4` 的内核测试；
- `advance`/`runs`/`effects` 的权威。

### 5.4 S1 修改（另批）

- `v24/sql/10_schema.sql`、`40_interpreters.sql`、`47_verbs.sql`、`49_host_reads.sql`、`50_permissions.sql`；
- `v24/load.py`（若新增文件）；
- `v24/s1/test_ddl.py`、`v24/s1/test_g1.py`；
- `v24/cordis/dp4/test_closeout.py`、`dp5/test_boundaries.py`、`dp6/test_boundaries.py`；
- `v24/ui/d_ui_6_acl.py`；
- `v24/s14/test_g12.py`（拟新增或并入既有 gate）；
- 规格/审查文档。

## 6. 回归 gate 清单

每个 S0 里程碑至少跑：

```bash
uv run python v24/session/test_session_verbs.py
uv run python v24/ui/test_ui_gate.py
uv run python v24/ui/test_backend_regressions.py
```

M2/M3 追加：

```bash
uv run python v24/s7/test_g6.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
```

M4 追加：

```bash
uv run python v24/ui/test_audit_m5.py
uv run python v24/ui/test_artifact_regressions.py
uv run python v24/s10/test_g9.py
uv run python v24/s11/test_g10.py
uv run python v24/s12/test_g11.py
uv run python v24/cordis/dp4/test_closeout.py
uv run python v24/cordis/dp5/test_boundaries.py
uv run python v24/cordis/dp6/test_boundaries.py
```

S0 收口 diff：

```bash
git diff -- v24/sql v24/load.py v24/host/deepseek.py
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
```

S1（批准后，另批）：

```bash
uv run python v24/s14/test_g12.py          # 拟新增；不存在则先并入既有 gate
uv run python v24/cordis/dp4/test_closeout.py
uv run python v24/cordis/dp5/test_boundaries.py
uv run python v24/cordis/dp6/test_boundaries.py
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s6/test_g5.py
uv run python v24/s7/test_g6.py
uv run python v24/s8/test_g7.py
uv run python v24/s9/test_g8.py
uv run python v24/session/test_session_verbs.py
```

> `test_session_verbs.py` 为本次新增；`test_g12.py` 尚不存在。实施时不得用“跳过/降低断言”方式过 gate。

## 7. 迁移与回滚

### 7.1 `sessions.json` v1 → v2

1. 读取 v1；校验 UUID/token hash/bindings；
2. 为每个 conversation 分配 `session_id`（可等于旧 `conversation_id`，减少 UI 变化）；
3. 迁移 `turns.jsonl` 的 `conversation_id` → `session_id`，保留 `seq` 仅作历史排序；
4. 计算 `run_no = len(bindings)`、`user_turn_no = len(turns for conversation)`，写 `counter_origin=legacy_approx`；
5. 写 v2；`sessions.json`/`turns.jsonl` 写 `.v1.bak`（0600）；每次原子替换保留 `.prev`；
6. 失败整体 fail-closed：quarantine 新产物，不覆盖原文件，不自动建空 store；
7. 迁移后校验：session_id 唯一；每个 session 至多一个活动 run；`start_index`/receipts 结构可读。

### 7.2 回滚

- **不是**“关闭 `V24_SESSION_API` 让旧代码读 v1 字段”；v1 `SessionStore.load()` 对 `format_version != 1` 直接 quarantine。
- 回滚脚本 `v24/session/rollback.py`：停准入/关 service → 归档 v2 sessions/turns/transcript/journal（0700/0600）→ 恢复 `.v1.bak` → 校验 v1 可加载 → 不覆盖归档、不做自动双向合并。
- 明确承认数据可见性窗口：升级期间新建的 session/turn 在回滚后只存在于归档，旧 UI 不可见；DB 中已提交 run 不受影响。
- S1 回滚：保留 `session_id` 列但停用读写，或按迁移脚本反向删除；不删除已有 session 元数据；frozen gate 回滚到批准基线。

### 7.3 数据修复

- 启动时扫描“一个 session 多个活动 run”：S0 冻结该 session 控制并报不变量错误，不自动挑一个；S1 由 DB 约束阻止。
- 孤儿 run（无 session 绑定）：挂到 `legacy-<scope>` 会话或只读展示；不删除。
- 同一 run 被两个 conversation 绑定：迁移失败并人工处理，不静默取一个。

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| S0 宿主串行域不能防跨进程绕过 | 中 | 同会话多活动 run | 所有入口只走 owner service；启动扫描；S1 DB 约束 |
| 终态 steer 重试开两个 run | 中 | 重复执行/计费 | 稳定 key + receipt + `host_request` + owner 串行域 + 重放测试 |
| `wait` 丢唤醒 | 中 | 客户端卡住/超时 | 短读循环 + 超时兜底；不依赖单次 notify |
| seed 与 adapter 合同不符 | 高 | 新 run 丢历史 | 先 system 历史块；M7 完整 seed；gate 覆盖 |
| `pending_steer` 覆盖 | 高 | 用户指令丢失 | 返回 `superseded` + UI 提示；P1 队列 |
| 迁移损坏 sessions | 低 | 会话丢失 | 备份 + quarantine + 原子写 |
| owner 线程被 provider 阻塞 | 中 | 控制入口排队 | `prepare/execute/finish` 拆分；adapter 在 exec；barrier 下另一会话 1 秒内返回 |
| receipt/start_index 损坏 | 低 | 幂等丢失/重复 run | 原子 replace + `.prev` + 恢复扫描；账本 0600 |
| waiting steer 仍有丢失窗口 | 中 | interaction 被清 | owner 串行域；barrier 覆盖预检/内核写/reconcile |
| 回滚数据不可见 | 中 | 升级后新会话旧 UI 丢失 | 回滚前归档 + 数据 owner 书面确认；不自动合并 |
| S1 解释器漏改 | 中 | start 全红 | 逐条 start 向量回归；先加列再改解释器 |
| 授权漏洞 | 低 | 越权 | 统一 `not_found_or_denied`；principal/scope 检查；负例 gate |

## 9. 已定与仍需治理

以下已在 2026-11-05 五项裁决中定稿（详见决策记录）：

| # | 事项 | 定稿 |
|---|---|---|
| 1 | S0→S1 还是直接 S1 | S0→S1；S1 独立 frozen-baseline bump |
| 2 | `steer` 单槽/队列 | v1 单槽 + `superseded`；P1 队列 |
| 3 | session 元数据归属 | S0 宿主 store；S2 才考虑入 DB |
| 4 | `cancel-late` 计数 | 延到 S1；S0 不声称四计数完整 |
| 5 | `cancel` 终态返回形状 | `ok=false + already_terminal` |
| 6 | `start` 默认等待 | `detach` 默认 true；传输层可组合 wait |
| 7 | 公开名 | `session_id`，不是 `conversation_id` |

仍需治理（不阻塞 S0-M1）：

- S1 的 frozen-baseline bump 批准件（三套 hash、D-UI-6、权限闭集、迁移执行与回滚）；
- `s14/test_g12.py` 新建或并入既有 gate；
- 回滚后 v2 增量的数据 owner 书面确认。

## 10. 明确不做

- 不建 `turns`/`run_attempts`/`session_status`/`session_events` 表。
- 不让 `session_id = run_id`。
- 不用 `scope_id` 当公开 `session_id`。
- 不从 `parent_run_id` 自动回灌子代理结果。
- 不把 provider 原文写 DB。
- 不在六动词里加 `list/close/export`。
- 不在 S0 改冻结 SQL；S1 不走“顺手改”。
- 不用真实 provider 作为 gate。

## 附录 A：S0 gate 骨架（建议）

```python
# v24/session/test_session_verbs.py
"""S0 six-verb session gate. Run: uv run python v24/session/test_session_verbs.py"""

def main():
    # 1. build env/runtime with ScriptedUiAdapter; assert no chainlit/v24.ui import
    # 2. start -> assert session_id/run_id/snapshot; v1 migration + .v1.bak/.prev
    # 3. poll -> assert no side effects; event_seq prefix advance; include_events=false
    # 4. wait -> seven wakes; no-cursor high-water; registration_stale -> epoch; revision-only
    # 5. steer active -> same run + epoch; waiting barrier -> interaction preserved
    # 6. steer terminal -> new run + same session; deferred/receipt/replay/conflict
    # 7. respond -> interaction consumed + user_turn unchanged; real waiting_unsupported
    # 8. cancel -> cancelled + already_terminal; starting recovery
    # 9. multi-session cursor map/winner/all_terminal; restart recovery; rollback archive
    return 0
```

约束：

- 不打开真实网络套接字；
- 不使用真实 provider key；
- 每个断言失败打印可定位的 `case`/`expected`/`actual`；
- 退出码 0 仅在全部用例通过时返回。

## 附录 B：与 M6–M10 计划的关系

- `docs/plans/v24-ui-usable-agent-m6-m10-2026-11-04.md` 的 `SessionStore v2`、`TranscriptStore`、`TurnService` 与本计划同向。
- 本计划的 `SessionService` 是 `TurnService` 的控制面骨架；M7 的 transcript seed 填充 §7.5 的 seed 合同。
- 本计划不替代 M6–M10 的 limits/model/streaming/compaction；只定义会话控制层。
- 若两者冲突，以本计划的六动词合同为准；M6–M10 的 UI 细节可调整。
