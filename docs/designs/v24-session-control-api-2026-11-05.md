# v24 六动词会话 API 合同（v1）

> **裁决状态（2026-11-05）**：五项决策已定稿，见
> [`v24-session-control-decision-record-2026-11-05.md`](../reviews/v24-session-control-decision-record-2026-11-05.md)。
> 本合同按裁决修订：传输限定为 Python 进程内 API + Chainlit UI（MCP/HTTP reserved）；`poll` 禁 event 增量分页；
> `user_turn_no`/`run_no` 持久化；`respond` 在 real 模式固定 `waiting_unsupported`；S1 的 `session_id` 保持 nullable。

| 项 | 值 |
|---|---|
| 日期 | 2026-11-05 |
| 状态 | **Adopted（2026-11-05）**；S0 合同定稿；不规定存储实现 |
| 适用 | S0 宿主门面与 S1 内核锚共用同一合同 |
| 传输 | **S0：Python 进程内 `SessionService` + Chainlit UI adapter**；MCP/HTTP 为 reserved，不在 S0 实现 |
| 版本 | `v: 1`；破坏性变更必须升 `v` |

## 1. 约定

- **ID**：`session_id`、`run_id`、`interaction_id` 均为 UUID 字符串；`request_key` 为 1–256 字符 UTF-8，不允许 NUL。
- **时间**：ISO-8601 UTC，毫秒精度。
- **JSON**：请求/响应均为 UTF-8 JSON object；未知字段在 v1 一律拒绝（`invalid_args`），避免静默拼写错误。
- **读/写**：`poll`、`wait` 是纯读，不产生 effect、不增加 revision、不消费 wake；`start`、`cancel`、`steer`、`respond` 是写，必须带 `request_key`。
- **幂等**：`(principal_id, session_id, public_op, key_hash)` 是会话级幂等作用域；同键同规范字节返回原响应（`disposition=replay`），同键异字节返回 `request_conflict`。`start` 另用 `start_index` 按 `(principal_id, key_hash)` 定位已完成命令；每 session 保留 256 条 completed receipt，超过后同 key 视为新命令，`start_index` 不淘汰。
- **CAS**：可选 `expected_run_id`、`expected_generation`；不匹配返回 `stale_generation` + 当前快照，客户端重新 poll 后重试。
- **检查顺序**：写动词按 replay → 授权 → 状态门（terminal/waiting/closed）→ CAS → 业务。状态门优先于 CAS，避免对终态 cancel/respond 返回 `stale_generation`；`steer` 终态新 run 例外，它用 `expected_run_id` 校验客户端看到的旧 run。
- **不泄露**：错误只返回稳定 code/可读 message；不返回 SQL、堆栈、provider 原文、key、Authorization、DSN。
- **禁止裸用 `turn`**：本文所有计数使用限定名（§4.5）。

## 2. 公共对象

### 2.1 `SessionSnapshot`

```json
{
  "v": 1,
  "session_id": "8f0c2d9e-4b1a-4c3d-9e2f-1a2b3c4d5e6f",
  "name": "fix-parser",
  "state": "active",
  "status": "running",
  "active": true,
  "terminal": false,
  "workspace_root": "/Users/me/project",
  "toolset": "exec",
  "model": "deepseek/deepseek-chat",
  "created_at": "2026-11-05T08:00:00.000Z",
  "updated_at": "2026-11-05T08:00:12.345Z",
  "run_no": 2,
  "user_turn_no": 3,
  "current_run": { "run_id": "…", "status": "running", "…": "…" },
  "last_run": { "run_id": "…", "status": "cancelled", "…": "…" },
  "interaction": null,
  "pending_steer": null,
  "counters": {
    "runs": 2,
    "effect_settlement_no": 5,
    "model_round_no": 3,
    "tool_round_no": 2,
    "user_turn_no": 3
  },
  "cursor": {
    "session_id": "…",
    "run_id": "…",
    "run_revision": 12,
    "event_seq": 34,
    "registration_generation": 1,
    "epoch_no": 2,
    "generation": 3,
    "interaction_id": null,
    "user_turn_no": 3,
    "session_revision": 7
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | enum | 宿主管理生命周期：`starting / active / closed`；`setup_incomplete` 时 `state=starting`。执行状态看 `status`，不要把 `state` 当 run 状态 |
| `status` | enum | 公开派生状态：`starting / running / waiting_for_input / completed / failed / cancelled / blocked_unknown / idle / closed` |
| `active` | bool | `status in (running, waiting_for_input)` |
| `terminal` | bool | `status in (completed, failed, cancelled, blocked_unknown, closed)` |
| `run_no` | int | 会话内 run 数（含当前） |
| `user_turn_no` | int | 用户请求边界数（start + steer；respond 不计） |
| `current_run` | object/null | 当前/最后 run 的 `RunView`；无 run 为 null |
| `last_run` | object/null | 与 `current_run` 相同或最近一个终态 run；用于 UI 展示 |
| `interaction` | object/null | 等待输入时顶层便利字段；与 `current_run.interaction` 一致 |
| `pending_steer` | object/null | 当前单槽 steer；`{instruction, epoch, generation}`（`epoch` 是 run 的 epoch 号；`created_at` 若需要由宿主补充） |
| `counters` | object | 见 §4.5；`model_round_no`/`tool_round_no` 在 S0 可为 null |
| `cursor` | object | 客户端读位置；见 §2.4 |

### 2.2 `RunView`

只暴露控制需要的字段，避免把内部实现全量泄漏：

```json
{
  "run_id": "…",
  "status": "running",
  "epoch_no": 2,
  "registration_generation": 1,
  "turn_no": 5,
  "driving_generation": 3,
  "revision": 12,
  "created_at": "…",
  "updated_at": "…",
  "ended_at": null,
  "remaining_steps": 18,
  "remaining_tokens": 15320,
  "remaining_tool_calls": 12,
  "remaining_wall_ms": 540000,
  "interaction": null,
  "pending_steer": { "instruction": "also update tests", "epoch": 2, "generation": 3 },
  "close_intent": null,
  "result": null
}
```

- `status` 保留 v24 原值（`running|waiting|completed|failed|cancelled|blocked_unknown`）。
- `result` 只在终态返回；`final_text` 在 `result.final_text`。
- 不返回 `owner_fiber_id`/`owner_episode_id` 等内部句柄，除非管理员视图。

### 2.3 `InteractionView`

```json
{
  "interaction_id": "b3e1…",
  "origin_effect_id": "b3e1…",
  "generation": 2,
  "schema_digest": "hex64",
  "prompt_digest": "hex64",
  "created_at": "…",
  "payload": { "prompt": "Continue?", "options": ["accept", "decline"] }
}
```

- `interaction_id` 等于产生它的 model effect id；客户端必须原样回传。
- `payload` 是渲染所需的最小投影，**不在 `runs.interaction` 中**；S0 由 host journal/模型 outcome 投影，取不到则省略。不包含 provider 原始 reasoning/tool 字节。

### 2.4 `Cursor`

```json
{
  "session_id": "…",
  "run_id": "…",
  "run_revision": 12,
  "event_seq": 34,
  "registration_generation": 1,
  "epoch_no": 2,
  "generation": 3,
  "interaction_id": null,
  "user_turn_no": 3,
  "session_revision": 7
}
```

- `session_id` 标识 cursor 属于哪个会话；多会话 `wait` 用它区分 winner。cursor 的 `session_id` 与请求不匹配时，视为无 cursor（`changed=true`），不报错。
- `run_id` 变化表示换 run（`wait` → `run_started`）。
- `run_revision` 变化表示 run 投影变化（`wait` → `event`）。
- `event_seq` 是当前 run 的 `v24.events.seq` 游标；不是全局 offset。
- `registration_generation` 失配 → `registration_stale`。
- `epoch_no`/`generation` 变化 → `wait` 的 `epoch`（`steer`/`respond` 后）；`epoch` 是内核的 `epoch_no`，`generation` 是 `driving_generation`。
- `interaction_id` 是“已上报给客户端的当前交互”；`wait` 只有在当前 interaction_id 与它不同才再次以 `interaction` 唤醒，避免同一交互反复唤醒。
- `user_turn_no` 只用于展示/对账，不驱动 wake。
- `session_revision` 观察纯宿主变化（`starting→active/closed`、计数/绑定、receipt 阶段）；它不替代 run 级 `run_revision`。
- 多会话 `wait` 使用 `cursors: {session_id: Cursor}` 的 per-session 映射；缺项视为无 cursor（先取高水位），响应返回完整 `cursors` 并只更新 winner。
- `event_seq` 始终是非负整数，禁止 `null`；换 run 或 `registration_stale` 重置为 0。

### 2.5 `Budget`

```json
{ "steps": 24, "tool_calls": 24, "tokens": 20000, "wall_ms": 600000 }
```

- 整个 `budget` 省略时由宿主 limits 填充；出现时必须是 object。
- 出现 `budget` 时 `steps`/`tool_calls` 必填（冻结解释器要求），`steps`/`wall_ms` ≥ 1，`tool_calls` ≥ 0；`wall_ms` 省略取 600000。
- `tokens` 是**可选**字段：省略表示不限（内核 `remaining_tokens=NULL`）；出现 `null` 返回 `invalid_args`。
- 上限：`steps` 256、`tool_calls` 1024、`tokens` 1e12、`wall_ms` 86400000；超限 `budget_exceeded`。

## 3. 公共信封

### 3.1 成功（写）

```json
{
  "v": 1,
  "op": "steer",
  "ok": true,
  "disposition": "committed",
  "session_id": "…",
  "run_id": "…",
  "started": false,
  "queued": true,
  "superseded": false,
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" },
  "error": null
}
```

### 3.2 成功（读）

```json
{
  "v": 1,
  "op": "poll",
  "ok": true,
  "disposition": "read",
  "session_id": "…",
  "run_id": "…",
  "changed": true,
  "wake": { "ready": false, "reason": "none" },
  "snapshot": { "…": "…" },
  "events": [],
  "cursor": { "…": "…" },
  "error": null
}
```

### 3.3 失败

```json
{
  "v": 1,
  "op": "steer",
  "ok": false,
  "disposition": "rejected",
  "session_id": "…",
  "run_id": "…",
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" },
  "error": {
    "code": "interaction_pending",
    "message": "Session is waiting for input; use respond with the current interaction_id.",
    "retryable": false,
    "details": { "interaction_id": "…" }
  }
}
```

- 失败时 `snapshot` 尽量返回；`session_id` 未知时可为 null。
- `retryable=true` 仅表示“可重新 poll 后重试”，不表示自动重试安全。
- `disposition`：`committed | replay | deferred | rejected | read`。

## 4. 数据语义

### 4.1 会话状态

| 公开 `status` | 来源 | 可执行动词 |
|---|---|---|
| `starting` | 会话记录 `setup_incomplete` 或首个 run 未准入 | `poll`、`wait`、`cancel`（清理） |
| `running` | 当前 run `running` | `poll`、`wait`、`cancel`、`steer` |
| `waiting_for_input` | 当前 run `waiting` | `poll`、`wait`、`cancel`、`respond` |
| `completed` | 最后 run `completed` | `poll`、`wait`、`steer`（新 run） |
| `failed` | 最后 run `failed` | 同上 |
| `cancelled` | 最后 run `cancelled` | 同上 |
| `blocked_unknown` | 最后 run `blocked_unknown` | `poll`、`wait`（`steer` 拒绝） |
| `idle` | 会话存在但无 run | `poll`、`wait`、`steer`（开新 run） |
| `closed` | 管理面关闭 | 只读 |

### 4.2 状态转换

| 起点 | 动词 | 终点 | 备注 |
|---|---|---|---|
| 无 | `start` | `starting` → `running` | 失败留在 `starting` |
| `running` | `steer` | `running` | 同 run，epoch/generation +1 |
| `running` | `cancel` | `cancelled` | run 终态 |
| `running` | 自然结算 | `completed/failed/blocked_unknown` | 不是六动词产生 |
| `waiting_for_input` | `respond` | `running` | 消费 interaction |
| `waiting_for_input` | `cancel` | `cancelled` | 清 interaction |
| `completed/failed/cancelled` | `steer` | `running` | 新 run，`run_no + 1` |
| `blocked_unknown` | `steer` | 拒绝 | 保持 `blocked_unknown` |
| 任意活动 | `start` | 拒绝 | `start` 不续接 |
| 任意 | 管理 `close` | `closed` | 先 cancel 活动 run |

### 4.3 `user_turn_no`

- `start` 成功：+1。
- `steer` 成功（无论同 run 还是新 run）：+1。
- `respond` 成功：不变。
- `cancel`/`poll`/`wait`：不变。
- 失败/拒绝：不变。
- 重放：不重复 +1。

### 4.4 `run_no`

- `start` 成功：1。
- 终态 `steer` 新 run：+1。
- 同 run `steer`：不变。
- 重放：不变。

### 4.5 `counters`

| 字段 | 来源 | 说明 |
|---|---|---|
| `runs` | 会话内 run 数 | 含终态 |
| `effect_settlement_no` | 当前 run `turn_no` | model/tool 各 +1；不是 UI 轮数 |
| `model_round_no` | 派生 | S0 可为 null；S1 由 ledger 计算 |
| `tool_round_no` | 派生 | 工具批次数；S0 可为 null |
| `user_turn_no` | 宿主计数器 | start + steer |

## 5. 动词

### 5.1 `start`

**用途**：新建会话并启动首个 run。永远不续接已有会话。

**请求**

```json
{
  "op": "start",
  "message": "read the parser and fix the failing test",
  "session_name": "fix-parser",
  "model": "deepseek/deepseek-chat",
  "budget": { "steps": 24, "tool_calls": 24, "tokens": 20000, "wall_ms": 600000 },
  "toolset": "exec",
  "workspace_root": "/Users/me/project",
  "request_key": "client-7f3a",
  "detach": true,
  "timeout_ms": 0
}
```

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `message` | 是 | 1–65536 UTF-8 | 首个 user 消息 |
| `session_name` | 否 | 1–120 | 缺省取 message 前 40 字 |
| `model` | 否 | 必须等于宿主模型 | S0 不支持 per-session 模型；不匹配 `catalog_changed` |
| `budget` | 否 | §2.5 | 缺省宿主 limits |
| `toolset` | 否 | 必须等于宿主 toolset | S0 不支持动态安装；不匹配 `invalid_args` |
| `workspace_root` | 否 | 绝对路径，且与宿主 workspace 匹配 | 不匹配 `workspace_mismatch` |
| `request_key` | 是 | 1–256 | 幂等键 |
| `detach` | 否 | bool，默认 true | true：准入后立即返回；false：等到首个 interesting 或 timeout |
| `timeout_ms` | 否 | 0–600000，默认 0 | 仅 `detach=false` 生效 |

**响应**

```json
{
  "v": 1,
  "op": "start",
  "ok": true,
  "disposition": "committed",
  "session_id": "8f0c…",
  "run_id": "1a2b…",
  "started": true,
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" },
  "error": null
}
```

**规则**

- 请求中出现 `session_id` → `invalid_args`，message 指引用 `steer`。
- **会话身份由宿主分配**：`start` 先在 `start_index` 写 `(principal, key_hash) → session_id/run_key/intent`，再调当前签名的 `v24.start`（S0 不把 `session_id` 传进内核）。同 key 重试命中索引，不分配第二个 session。
- 同 `request_key` 同 payload：返回原 `session_id/run_id`，`disposition=replay`。若 `intent` 已存在但尚未产生 `run_id`，返回同一 `session_id` + `starting` 快照，`disposition=deferred`（首次响应冻结，后续重放同一 deferred，不得第二次变成 committed）。
- 同 key 异 payload：`request_conflict`，并保留首次收到的 normalized request/digest 供审计。
- 创建失败：`ok=false`、`disposition="deferred"`，返回 `session_id`（若已分配）+ `starting` 快照 + `error`；`run_id` 可为 null；`intent` 保留，同 key 按 `run_request_key` 查 `host_request` 后继续/重试，不得另建 session。
- 成功后一次原子 replace 写 bind/counter/turn/receipt `completed` 与 `start_index.phase=completed`；receipt 保留 256 条 completed，`start_index` 不淘汰。
- 首个 user turn 以 `(run_id, user_turn_no)` 去重；重试 bind 后补写时不能重复追加。
- **默认不等待**：`detach=true` 时只完成准入；客户端用 `wait`。`detach=false` 时响应复用 `wait` 的 `wake` 字段；`detach=true` 时省略 `wake`。
- `detach=false` 时最多等到 `timeout_ms`；超时返回当前快照，不取消 run。即使超时，也必须返回已创建的 `session_id`/`run_id`，不能让客户端失去句柄；`wake.reason="timeout"`、`ready=false`。
- `model`/`toolset`/`workspace_root` 只做宿主匹配校验；不实现 per-session 动态切换。

**错误**：`invalid_args`、`request_conflict`、`scope_closed`、`provider_unavailable`、`dependency_unresolved`、`budget_exceeded`、`catalog_changed`、`workspace_mismatch`、`not_found_or_denied`。

### 5.2 `poll`

**用途**：立即读取会话快照。纯读。

**请求**

```json
{
  "op": "poll",
  "session_id": "8f0c…",
  "cursor": { "session_id": "…", "run_id": "1a2b…", "run_revision": 12, "event_seq": 34, "registration_generation": 1, "epoch_no": 2, "generation": 3, "interaction_id": null },
  "include_events": true
}
```

或：

```json
{ "op": "poll", "session_ids": ["…", "…"], "include_events": false }
```

| 字段 | 必填 | 约束 |
|---|---|---|
| `session_id` | 二选一 | UUID |
| `session_ids` | 二选一 | 1–32 个 UUID；与 `session_id` 互斥 |
| `cursor` | 否 | 单会话时用于 `changed`；多会话时忽略 |
| `include_events` | 否 | bool，默认 false；**S0 不做增量分页**：true 时返回当前 run 的最早 64 条；不按 `cursor.event_seq` 取窗口 |

**响应（单会话）**

```json
{
  "v": 1,
  "op": "poll",
  "ok": true,
  "disposition": "read",
  "session_id": "…",
  "run_id": "…",
  "changed": true,
  "snapshot": { "…": "…" },
  "events": [
    { "seq": 35, "event_kind": "tool_call_settled", "payload": { "…": "…" }, "created_at": "…" }
  ],
  "cursor": { "…": "…" }
}
```

**响应（多会话）**

```json
{
  "v": 1,
  "op": "poll",
  "ok": true,
  "disposition": "read",
  "sessions": [
    { "session_id": "…", "ok": true, "snapshot": { "…": "…" } },
    { "session_id": "…", "ok": false, "error": { "code": "not_found_or_denied" } }
  ]
}
```

**规则**

- 纯读：无 revision、无 effect、无 request journal、无锁写。
- 未知/无权：单会话 `not_found_or_denied`；多会话逐项 `ok:false`，不泄露存在性。
- `changed` = `cursor.session_id` 不匹配 / `cursor.run_id` / `cursor.run_revision` / `cursor.session_revision` 与当前不同；无 cursor 时 `changed=true`。`event_seq` 不是唯一判据。
- `include_events` 只返回当前 run 的事件；不返回历史 run。**S0 禁止按 `event_seq` 做增量分页**：`include_events=true` 只返回当前 run 的最早 64 条；`v24.poll` 没有 `after_event_seq`，不把 `wait_check` 伪装成 poll 分页。
- `include_events=true` 且返回成功时，cursor 的 `event_seq = max(in.event_seq, 返回前缀的最大 seq)`；`include_events=false` 时 cursor 不变；换 run 时重置为 0。返回的事件可能少于 64 条；客户端不得把“没有更多”解释为“没有历史”。
- 需要从上次位置继续的客户端使用 `wait`；`wait` 只推进到实际返回的最后一条，不越过未返回事件。
- 多会话 `poll` 每项返回各自的 `cursor`；顶层不回写单会话 cursor。
- `session_ids` 顺序保持输入顺序；未知项 `ok:false`，不改变其他项。

**错误**：`invalid_args`、`not_found_or_denied`。

### 5.3 `wait`

**用途**：阻塞到会话出现“有意义”的变化，或超时。纯读。

**请求**

```json
{
  "op": "wait",
  "session_id": "8f0c…",
  "cursor": { "session_id": "…", "run_id": "1a2b…", "run_revision": 12, "event_seq": 34, "registration_generation": 1, "epoch_no": 2, "generation": 3, "interaction_id": null, "session_revision": 7 },
  "timeout_ms": 120000,
  "include_events": true
}
```

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `session_id` / `session_ids` | 二选一 | 同 poll | 多会话返回第一个 interesting |
| `cursor` / `cursors` | 否 | §2.4 | 单会话用 `cursor`；多会话用 `cursors: {session_id: Cursor}`；缺项先取高水位 |
| `timeout_ms` | 否 | 0–600000，默认 120000 | 0 = poll；超时不是错误 |
| `include_events` | 否 | bool，默认 false | true 时返回事件；false 不产生 event 唤醒，也不推进 `event_seq` |

**响应**

```json
{
  "v": 1,
  "op": "wait",
  "ok": true,
  "disposition": "read",
  "session_id": "…",
  "run_id": "…",
  "wake": { "ready": true, "reason": "interaction" },
  "interaction_id": "b3e1…",
  "snapshot": { "…": "…" },
  "events": [],
  "cursor": { "…": "…" }
}
```

**`wake.reason`**

| reason | 条件 | `ready` |
|---|---|---|
| `terminal` | 当前 run 终态（或 `idle`/`closed`）且 cursor.run_id 相同 | true |
| `interaction` | 当前 run `waiting`，且 `interaction_id` 与 `cursor.interaction_id` 不同 | true |
| `run_started` | 当前 run_id ≠ cursor.run_id | true |
| `epoch` | 同 run，`epoch_no`/`driving_generation` 变化 | true |
| `event` | 同 run，`event_seq` 前进（只到实际返回的最后一条） | true |
| `timeout` | 超时 | false |
| `none` | `timeout_ms=0` 且无变化 | false |

**优先级**：`run_started > terminal > interaction > epoch > event > timeout > none`。

**多会话响应**

```json
{
  "v": 1,
  "op": "wait",
  "ok": true,
  "disposition": "read",
  "winner_session_id": "…",
  "pending_session_ids": ["…"],
  "all_terminal": false,
  "wake": { "ready": true, "reason": "run_started" },
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" },
  "cursors": { "…": { "…": "…" } }
}
```

- 多会话只返回一个 winner；其余放 `pending_session_ids`。只更新 winner 的 cursor；完整 `cursors` 映射随响应返回。
- 按 principal 轮转 winner，避免 sticky terminal 饿死其他 session；v1 只承诺“第一个 interesting”，不承诺全局公平。
- 全部终态时 `all_terminal=true`，仍返回一个 winner 快照；`all_terminal` 不新增 wake reason。

**规则**

- 不持事务/会话锁等待：短读 → COMMIT/释放锁 → 睡眠/条件变量/`LISTEN` → 短读。
- 不消费 wake/event；不同 waiter 可各看到一次。
- 无 cursor 的 `wait` 先分页调用 `wait_check` 取当前高水位，再从高水位开始等（等价于“从现在开始”，不是从 0 重放）。
- `run_started` 优先于同 run 判断：只要当前 run_id 与 cursor.run_id 不同就返回 `run_started`，即使新 run 已经终态；同 run 的下一次 `wait` 再报 `terminal`。
- `event_seq` 只推进到实际返回的最后一条事件；`include_events=false` 不产生 event 唤醒，也不推进 `event_seq`。
- `registration_generation` 失配：映射为 `wake.reason=epoch` + 新快照 + `event_seq=0` 的重置 cursor；不新增第八种 wake，也不报 not found。
- revision-only（`run_revision` / `session_revision` 前进但 `event_seq` 未变）：默认不唤醒；正超时到期返回快照并带 `changed=true`，避免忙等。
- 不消费 wake/event；不同 waiter 可各看到一次。
- `timeout` 不是错误；`ok=true`，`wake.ready=false`。
- unknown session：单会话整请求 `not_found_or_denied`；多会话逐项 `ok:false`。
- 不允许 `timeout_ms > 600000` 或负数。

**错误**：`invalid_args`、`not_found_or_denied`、`registration_stale`。

### 5.4 `cancel`

**用途**：取消当前活动 run；不删除会话。

**请求**

```json
{
  "op": "cancel",
  "session_id": "8f0c…",
  "expected_run_id": "1a2b…",
  "expected_generation": 3,
  "request_key": "client-cancel-1"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `session_id` | 是 | |
| `expected_run_id` | 否 | CAS；不匹配 `stale_generation` |
| `expected_generation` | 否 | 当前 run `driving_generation`；不匹配 `stale_generation` |
| `request_key` | 是 | 幂等键 |

**响应**

```json
{
  "v": 1,
  "op": "cancel",
  "ok": true,
  "disposition": "committed",
  "session_id": "…",
  "run_id": "…",
  "already_terminal": false,
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" }
}
```

**规则**

- 活动 run：`v24.cancel`；成功 `already_terminal=false`。
- 无活动 run（终态/idle）：`ok=false, disposition="rejected", already_terminal=true, error.code="already_terminal"`，并返回当前快照；客户端可据此对账，不应重试。
- `closed`：`session_closed`，不把已关闭会话重新打开。
- 同 key 重放：返回原响应（可能仍是 `committed`），不因当前已终态而改写。
- `starting/setup_incomplete`：执行清理；返回 `cancelled`/`closed`。
- `blocked_unknown`：`already_terminal`；不 seal。
- 不改变会话历史、不删除 scope（除非 `starting` 清理）、不重开 run。

**错误**：`invalid_args`、`not_found_or_denied`、`request_conflict`、`stale_generation`、`already_terminal`、`setup_incomplete`、`session_closed`、`catalog_changed`。

### 5.5 `steer`

**用途**：向会话追加用户指令；活动时投递到当前 run，终态时在同一会话开新 run。**不用于等待输入。**

**请求**

```json
{
  "op": "steer",
  "session_id": "8f0c…",
  "message": "also update the tests",
  "expected_run_id": "1a2b…",
  "expected_generation": 3,
  "request_key": "client-steer-1",
  "wait": false,
  "timeout_ms": 0
}
```

| 字段 | 必填 | 约束 | 说明 |
|---|---|---|---|
| `session_id` | 是 | UUID | |
| `message` | 是 | 1–8192 UTF-8 | 用户指令；与 `v24.steer` 内核限制一致 |
| `expected_run_id` | 否 | UUID | CAS；不匹配 `stale_generation` |
| `expected_generation` | 否 | 非负整数 | CAS；不匹配 `stale_generation` |
| `request_key` | 是 | 1–256 | 幂等键 |
| `wait` | 否 | bool，默认 false | true：等到首个 interesting 或 timeout |
| `timeout_ms` | 否 | 0–600000 | 仅 wait=true |
| `queue` | 否 | bool，默认 false | v1 只接受 false/省略；true → `invalid_args`（P1 再做宿主队列） |

**响应（活动 run）**

```json
{
  "v": 1,
  "op": "steer",
  "ok": true,
  "disposition": "committed",
  "session_id": "…",
  "run_id": "1a2b…",
  "started": false,
  "queued": true,
  "superseded": false,
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" }
}
```

**响应（终态新 run）**

```json
{
  "v": 1,
  "op": "steer",
  "ok": true,
  "disposition": "committed",
  "session_id": "…",
  "run_id": "9c8d…",
  "started": true,
  "queued": false,
  "superseded": false,
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" }
}
```

**分派规则**

| 当前状态 | 行为 | 响应 |
|---|---|---|
| `running` | `v24.steer` | `started=false`；`queued=true` 若尚未送达模型；`superseded=true` 若覆盖旧 pending |
| `waiting_for_input` | 拒绝 | `interaction_pending`，`details.interaction_id` |
| `completed/failed/cancelled` | 同 session `v24.start` | `started=true`，新 `run_id`，`run_no+1` |
| `blocked_unknown` | 拒绝 | `blocked_unknown` |
| `starting` | 拒绝 | `setup_incomplete` 或 `session_busy` |
| `idle` | 同 session `v24.start` | `started=true` |
| `closed` | 拒绝 | `session_closed` |

**规则**

- `user_turn_no` 成功 +1（无论同 run 或新 run）；重放不 +1。
- 新 run 的 seed 由宿主 `ContextBuilder` 生成；S0 先注入 system 历史块，M7 再做完整 transcript seed。
- `pending_steer` 单槽：新 steer 会覆盖旧 pending；必须返回 `superseded=true`，并在 UI 显式提示“上一条未送达”。
- 终态新 run 不能复制旧 run 的 `run_id`/effect；只继承会话历史。新 run 的预算取会话默认策略，**不继承**旧 run 的剩余额度；v1 的 `steer` 没有 `budget` 字段，预算不足返回 `budget_exceeded`。
- `expected_run_id` 用于防止“以为在 A run，实际切到 B run”；终态分派时如果 `expected_run_id` 指向旧 run 且当前已是新 run，返回 `stale_generation`，客户端重新 poll 后再决定。终态分派时 `expected_generation` 校验旧 run；新 run 的 `driving_generation` 从 0 开始。
- 重放：先用 `v24.host_request` 查派生 key；活动 key 与终态 key 都要查（见 §7）。
- 预检、内核写、driver settle 都在 owner 串行域；`waiting_for_input` 拒绝是零 run 写（只写一条 `rejected` receipt，run/effect/request 不变）。
- 幂等：receipt 的 `resolved_variant` 首次分派后固定为 `steer_active` 或 `steer_new_run`；重试不得按当前状态改派，否则同 key 会随状态漂移。
- `wait=true` 时，`steer` 成功后等待首个 interesting；超时返回当前快照，不取消新 run。

**错误**：`invalid_args`、`not_found_or_denied`、`request_conflict`、`interaction_pending`、`blocked_unknown`、`setup_incomplete`、`session_busy`、`session_closed`、`stale_generation`、`budget_exceeded`、`catalog_changed`。

### 5.6 `respond`

**用途**：回答当前等待中的交互。只消费精确 `interaction_id`。

**请求**

```json
{
  "op": "respond",
  "session_id": "8f0c…",
  "interaction_id": "b3e1…",
  "response": "accept",
  "answers": null,
  "content": null,
  "meta": null,
  "amendment": null,
  "expected_generation": 3,
  "request_key": "client-respond-1"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `session_id` | 是 | |
| `interaction_id` | 是 | 来自快照/`wait` |
| `response` | 否 | scalar string；与 `answers`/`content` 至少一个 |
| `answers` | 否 | object，按 question id |
| `content` | 否 | object，结构化 elicitation 内容 |
| `meta` | 否 | object |
| `amendment` | 否 | string，`accept_with_amendment` |
| `expected_generation` | 否 | 当前 `driving_generation`；传入则严格 CAS，不匹配 `stale_generation` |
| `request_key` | 是 | 幂等键 |

**响应**

```json
{
  "v": 1,
  "op": "respond",
  "ok": true,
  "disposition": "committed",
  "session_id": "…",
  "run_id": "…",
  "consumed_interaction_id": "b3e1…",
  "snapshot": { "…": "…" },
  "cursor": { "…": "…" }
}
```

**规则**

- 当前 run 必须 `waiting`；`runs.interaction.interaction_id` 必须精确等于请求值。
- `response` scalar 归一化为 `{"text": "<value>"}`；`answers`/`content`/`meta` 组装为内核 response 对象；至少一个非空。优先级：`amendment` → `{"action":"accept_with_amendment","amendment":...}`；否则 `answers` → `{"answers":...}`；否则 `content`/`meta` → `{"action": response 或 "accept","content":...,"meta":...}`；否则 scalar → `{"text":...}`。
- `expected_generation` 可选：不传时门面读当前 `driving_generation`（best-effort）；传入时严格比较，不匹配返回 `stale_generation` + 当前快照，内核仍必须收到 generation。
- **S0 real 模式固定 `waiting_unsupported`**：不构造 adapter、不打开 DB、零 run 写；成功 respond 分支只用 Fake/Scripted。S0 gate 不得暗示 real 全生命周期成功。
- `blocked_unknown` → `already_terminal` + `details.status="blocked_unknown"`；`completed/failed/cancelled` → `already_terminal`。不要伪造 `write=true`。
- 不匹配：`interaction_mismatch`，零写，返回当前快照。
- 无交互：`not_waiting`。
- 终态：`already_terminal`。
- **不增加** `user_turn_no`；只追加 `responded` 事实/转录 meta。
- 成功后 run 回到 `running`；客户端继续 `wait/poll`。
- 幂等：同 key 重放；不同 key 对已消费 id → `interaction_mismatch`。

**错误**：`invalid_args`、`not_found_or_denied`、`request_conflict`、`interaction_mismatch`、`not_waiting`、`already_terminal`、`invalid_response`、`stale_generation`、`setup_incomplete`、`session_closed`、`waiting_unsupported`。

## 6. 错误码总表

| code | 动词 | 含义 | retryable |
|---|---|---|---|
| `invalid_args` | 全部 | 形状/约束错误 | false |
| `not_found_or_denied` | 全部 | 未知或无权 | false |
| `request_conflict` | 写 | 同 key 异 payload | false |
| `already_terminal` | cancel/respond | 无活动 run 或已终态（v24-local） | false |
| `interaction_pending` | steer | 等待输入，应 respond（v24-local） | false |
| `interaction_mismatch` | respond | id 不匹配/已消费 | false |
| `not_waiting` | respond | 当前无 interaction（v24-local） | false |
| `blocked_unknown` | steer/respond | unknown wall；steer 拒绝，respond 映射 already_terminal | false |
| `waiting_unsupported` | respond | S0 real 模式固定拒绝；零 run 写 | false |
| `stale_generation` | cancel/steer/respond | CAS 不匹配 | true（先 poll） |
| `registration_stale` | wait | run 注册代变化 | true（先 poll） |
| `scope_closed` | start | 目标 scope 已关闭 | false |
| `setup_incomplete` | start/cancel/steer/respond | 安装未完成 | true（修复后） |
| `session_busy` | steer | 会话正在 setup/切换 | true（先 poll） |
| `session_closed` | 写 | 会话已关闭 | false |
| `budget_exceeded` | start/steer | 预算不足 | false |
| `provider_unavailable` | start | fiber/episode 不可用 | false |
| `dependency_unresolved` | start | 插件依赖未解析 | false |
| `catalog_changed` | start/steer | 工具/配置摘要变化 | false |
| `workspace_mismatch` | start | workspace 与宿主不符 | false |
| `invalid_response` | respond | 不支持的响应形状 | false |
| `timeout` | wait | **不是错误**；`wake.reason=timeout` | — |

## 7. 幂等与 key 派生

### 7.1 派生规则

```text
client_key = 1..256 chars
run_key(op) = "s:" + session_id + ":" + op + ":" + sha256_hex(client_key)[:32]
```

- `op` 使用 run 级 kind：`start`、`cancel`、`steer`、`respond`；终态 `steer` 开新 run 用 **`steer_new_run`**（内部名，不对客户端暴露），避免与首个 `start` 的 key 碰撞。
- 长度上限 512；`s:` + 36 + `:` + 5 + `:` + 32 ≈ 78。
- 同一客户端 `request_key` 在不同 session 下产生不同 run key；不同 session 可复用客户端 key。
- `session_id` 在 `start` intent 写入前分配；run key 用它派生。若进程在写 intent 前失败，则没有 session/run，重试重新分配；不存在“先用临时 UUID 再换”的路径。
- 幂等作用域是 `(principal, session, public_op, key_hash)`；`start` 另用 `start_index` 按 `(principal, key_hash)` 定位。每 session 保留 256 条 completed receipt；超过后同 key 视为新命令，`start_index` 不淘汰。

### 7.2 重放查找顺序

写动词执行前：

1. 计算候选 run key（`steer` 同时算 `steer_active` 和 `steer_new_run` 两个）。
2. 先查本 session 的 receipt（`(principal, session, public_op, key_hash)`），按 `resolved_variant` 固定分派；`start` 先查 `start_index`。
3. 对候选 key 调用 `v24.host_request(run_key)`，用于崩溃恢复。
4. 命中且 `request_bytes` 与本次规范字节一致：返回原响应（`disposition=replay`），不执行业务。
5. 命中但字节不同：`request_conflict`。
6. 未命中：在 owner 串行域内重新读状态，写 `intent`，执行 CAS/业务。

> `host_request` 只按 `(principal, request_key)` 查（`v24/sql/49_host_reads.sql:550`），不校验 kind；因此候选 key 必须唯一对应一种 kind。`steer` 的活动/终态两条路径使用不同 key（`steer_active` vs `steer_new_run`），不能复用同一个。

### 7.3 会话级命令的原子性

- `start`：在 owner 串行域内按 `(principal_id, key_hash)` 查 `start_index` 与 receipt；未命中才分配 `session_id` 并写 `intent`（含 run key、normalized request/digest、`owner_epoch`），然后创建 scope/调 `v24.start`/bind。查/写意图与幂等判定不能被拆到不同锁；安装或 provider 启动不得在锁内。同 key 的第二个请求看到 `intent` 返回同一 `deferred`。
- 终态 `steer`：owner 内读当前 run，若 terminal，调 `v24.start`（同 session，派生 `steer_new_run` key），成功后 bind 新 run；`resolved_variant` 首次分派后固定，不按当前状态改派。
- 活动 `steer`：调 `v24.steer`；同 key 重放由 receipt + request journal 保证。
- `cancel`/`respond`：依赖 run 级 request journal；会话层附加 receipt 与 CAS。
- 成功后一次原子 replace 写 bind/counter/turn/receipt；失败保留 `intent`，恢复时先 `host_request`。

### 7.4 规范字节

建议规范 JSON 至少包含：

```json
{
  "op": "steer",
  "session_id": "…",
  "message": "…",
  "expected_run_id": "…|null",
  "expected_generation": 3,
  "request_key": "client-…"
}
```

- 字段顺序按 canonical JSON 排序；UTF-8；不包含传输元数据（timeout/detach 不参与 digest，除非它改变语义）。
- 使用 RFC 8785 JSON Canonicalization Scheme；保存 normalized request 与完整 SHA-256 digest（不截断），用于 receipt 比较。
- 与 v24 `canonical_json` 保持同规则（`v24/host/canonical.py`）。

## 8. 与 run 级 v24 的映射

| 会话动词 | 内部调用 | 说明 |
|---|---|---|
| `start` | `v24.start(scope, fiber, {messages}, budget, run_key)` | 会话先分配/绑定；S0 不传 session_id（`v24.start(session_id)` 是 S1-only） |
| `poll` | `v24.poll(run_id, after_revision)` + `host_run_effects` | 组合快照 |
| `wait` | `v24.wait_check(run_id, registration_generation, epoch, after_event_seq)` | 宿主循环/退避 |
| `cancel` | `v24.cancel(run_id, driving_generation, run_key)` | CAS |
| `steer` 活动 | `v24.steer(run_id, driving_generation, message, run_key)` | 同 run |
| `steer` 终态 | `v24.start(scope, fiber, seed, budget, run_key)` | 新 run，同 session |
| `respond` | `v24.respond(run_id, interaction_id, response_obj, driving_generation, run_key)` | 精确交互 |

**错误映射**

| 内部错误 | 会话错误 |
|---|---|
| `already_terminal`（steer 活动路径） | 转为终态 `steer` 新 run 路径；不直接透传 |
| `already_terminal`（cancel/respond） | `already_terminal` |
| `request_conflict` | `request_conflict` |
| `stale_claim`/`stale_generation` | `stale_generation` |
| `not_found_or_denied` | `not_found_or_denied` |
| `interaction_mismatch` | `interaction_mismatch` |
| `blocked_unknown` | steer 拒绝；respond 映射 `already_terminal` + `details.status` |
| `waiting_unsupported` | real respond 固定能力错误；零 run 写 |

## 9. 与 RepoPrompt 的字段级对照

| RepoPrompt 字段/行为 | v24 合同 | 备注 |
|---|---|---|
| `op` | `op` | 同名六值 |
| `session_id` | `session_id` | 稳定 |
| `session_ids`（poll/wait） | `session_ids` | S0-M4 循环；S1 单次读 |
| `message`（start/steer） | `message` | start 1–65536；steer 1–8192 |
| `interaction_id` | `interaction_id` | 精确 |
| `response` scalar | `response` scalar | 归一化为 `{text}` |
| `answers`/`content`/`meta` | 同名字段 | 组装为内核对象 |
| `timeout` | `timeout_ms` | 单位不同：ms |
| `detach` | `detach` | start 用 |
| `wait`/`timeout_seconds`（steer） | `wait`/`timeout_ms` | 语义同 |
| `wait.wake_reason` | `wake.reason` | 值映射见下 |
| `snapshot.status` | `snapshot.status` | `waiting` → `waiting_for_input` |
| `session_name` | `session_name` | start |
| `model_id`/`worktree*` | 不在 v1 | 宿主配置/后续 |
| `agent_manage` | 管理面 | 不在六动词 |

**wake reason 映射**

| RepoPrompt | v24 |
|---|---|
| `terminal` | `terminal` |
| `interaction` / `waiting_for_input` | `interaction` |
| `steering_requested` | `epoch`（P1 可细分 `steering`） |
| `event`/`snapshot` | `event` |
| `timeout` | `timeout` |
| `superseded` | `run_started` 或 `stale_generation`（按场景） |

## 10. 预留传输绑定（不在 S0 实现）

> **S0 不实现 MCP server。** 本节只冻结未来绑定的形状，避免以后改名；它不是本版本的验收项，也不构成 Python/CLI 之外的兼容承诺。S0 的交付面是 Python 进程内 `SessionService` + Chainlit UI adapter。

工具名（future）：`agent_run`（与 RepoPrompt 对齐）或 `agent_session`（避免与未来 run 工具冲突）。建议 v24 用 `agent_session`，在描述中注明“session-addressed six verbs”。

```json
{
  "name": "agent_session",
  "description": "Start, poll, wait for, cancel, steer, or respond to a v24 agent session. start always creates a new session; use steer to continue.",
  "inputSchema": {
    "type": "object",
    "required": ["op"],
    "properties": {
      "op": { "enum": ["start", "poll", "wait", "cancel", "steer", "respond"] },
      "session_id": { "type": "string" },
      "session_ids": { "type": "array", "items": { "type": "string" } },
      "session_name": { "type": "string" },
      "message": { "type": "string" },
      "model": { "type": "string" },
      "toolset": { "type": "string" },
      "workspace_root": { "type": "string" },
      "budget": { "type": "object" },
      "interaction_id": { "type": "string" },
      "response": { "type": "string" },
      "answers": { "type": "object" },
      "content": { "type": "object" },
      "meta": { "type": "object" },
      "amendment": { "type": "string" },
      "request_key": { "type": "string" },
      "expected_run_id": { "type": "string" },
      "expected_generation": { "type": "integer" },
      "cursor": { "type": "object" },
      "timeout_ms": { "type": "integer" },
      "detach": { "type": "boolean" },
      "wait": { "type": "boolean" },
      "queue": { "type": "boolean" },
      "include_events": { "type": "boolean" }
    }
  }
}
```

传输层只做：

- 参数形状校验（不重复业务校验）；
- 把 `principal/workspace` 从认证上下文注入；
- 把 `SessionService` 的响应映射为 MCP content；
- 不把 `scope_id`、SQL、provider 原文暴露给模型。

## 11. 完整生命周期示例

```text
1. start
   req: {op:start, message:"fix parser", request_key:"k1"}
   res: {ok:true, session_id:S1, run_id:R1, disposition:"committed"}

2. poll
   req: {op:poll, session_id:S1}
   res: {status:"running", current_run:{run_id:R1,status:"running"}}

3. steer (active)
   req: {op:steer, session_id:S1, message:"also tests", request_key:"k2"}
   res: {run_id:R1, started:false, queued:true, user_turn_no:2}

4. wait (interaction)
   req: {op:wait, session_id:S1, cursor:{run_id:R1,run_revision:12}, timeout_ms:120000}
   res: {wake:{ready:true,reason:"interaction"}, interaction_id:I1}

5. respond
   req: {op:respond, session_id:S1, interaction_id:I1, response:"accept", request_key:"k3"}
   res: {run_id:R1, consumed_interaction_id:I1, user_turn_no:2}

6. wait (terminal)
   req: {op:wait, session_id:S1, cursor:{run_id:R1,run_revision:20}, timeout_ms:120000}
   res: {wake:{ready:true,reason:"terminal"}, status:"completed"}

7. steer (terminal → new run)
   req: {op:steer, session_id:S1, message:"next task", request_key:"k4"}
   res: {run_id:R2, started:true, run_no:2, user_turn_no:3}

8. cancel (active)
   req: {op:cancel, session_id:S1, request_key:"k5"}
   res: {run_id:R2, status:"cancelled", already_terminal:false}
```

## 12. 测试向量（合同级）

| # | 场景 | 期望 |
|---|---|---|
| 1 | `start` 带 `session_id` | `invalid_args`，提示 `steer` |
| 2 | `start` 同 key 重放 | 同 `session_id/run_id`，`disposition=replay` |
| 3 | `start` 同 key 异 message | `request_conflict` |
| 4 | `poll` 无 cursor | `changed=true`，快照完整 |
| 5 | `poll` 同 cursor | `changed=false`，无副作用 |
| 6 | `wait` 终态 | `wake.reason=terminal` |
| 7 | `wait` waiting | `wake.reason=interaction`，`interaction_id` 顶层 |
| 8 | `wait` 另一客户端开新 run | `wake.reason=run_started`，新 `run_id` |
| 9 | `wait` timeout=0 无变化 | `wake.ready=false, reason=none` |
| 10 | `cancel` 活动 | `cancelled`，`already_terminal=false` |
| 11 | `cancel` 终态 | `already_terminal=true`，快照保留 |
| 12 | `cancel` 同 key 重放 | 原响应，`replay` |
| 13 | `steer` 活动 | 同 `run_id`，`epoch_no+1`，`user_turn_no+1` |
| 14 | `steer` 覆盖 pending | `superseded=true` |
| 15 | `steer` waiting | `interaction_pending`，零写 |
| 16 | `steer` 终态 | 新 `run_id`，同 `session_id`，`run_no+1` |
| 17 | `steer` blocked_unknown | `blocked_unknown`，零写 |
| 18 | `steer` 终态同 key 重放 | 不产生第二个 run |
| 19 | `respond` 精确 id | 成功，`user_turn_no` 不变 |
| 20 | `respond` 错误 id | `interaction_mismatch`，零写 |
| 21 | `respond` 已消费 id 新 key | `interaction_mismatch` |
| 22 | `respond` 无交互 | `not_waiting` |
| 23 | 其他 principal | `not_found_or_denied` |
| 24 | `wait` registration 失配 | `wake.reason=epoch` + 新快照 + `event_seq=0`；不是 not found |
| 25 | `steer` expected_generation 旧值 | `stale_generation` + 快照 |
| 26 | 同 client key 先 `start` 后终态 `steer` | 两次都 committed，两个 run（`start` vs `steer_new_run` 命名空间不同），不是 replay |
| 27 | `poll` cursor 属于另一个 session | 视为无 cursor，`changed=true`，不报错 |
| 28 | `poll` >64 条事件 | **不跳不重**：每次只回最早 64 条；cursor 推进到已返回前缀最大 seq；下一次 poll 仍从最早开始（S0 能力边界，文档显式） |
| 29 | `poll` `include_events=false` | `cursor.event_seq` 不变，不产生 event 唤醒 |
| 30 | `wait` 无 cursor | 先取高水位，不从 0 重放 |
| 31 | `wait` R2 在下一次 wait 前已终态 | 先报 `run_started`；同 run 的下一次 wait 再报 `terminal` |
| 32 | `wait` revision-only | 默认不唤醒；正超时返回快照 + `changed=true` |
| 33 | `wait` `registration_stale` | `wake.reason=epoch` + 新快照 + `event_seq=0`，不是 not found |
| 34 | 多会话 `wait` | winner + `pending_session_ids` + 完整 `cursors`；按 principal 轮转；`all_terminal` 布尔 |
| 35 | `start` 同 key 在 committed 后重启重放 | 从 `start_index`/receipt 返回原 envelope，不新建 session/run |
| 36 | `start` deferred 后同 key 重试 | 返回同一 deferred，不变成 committed |
| 37 | `steer` 同 key 状态变化后重试 | `resolved_variant` 固定，不按当前状态改派；不产生第二个 run |
| 38 | 两个客户端争同一 terminal steer | 仅一个宿主完成记录；另一个 replay/conflict，不产生第三个 run |
| 39 | v1 迁移 legacy counter | `run_no=len(bindings)`、`user_turn_no=len(turns)`、`counter_origin=legacy_approx`；不声称精确 |
| 40 | 回滚 | 归档 v2 增量 -> 恢复 `.v1.bak` -> 旧代码可加载；归档不覆盖 |

## 13. 已定与未决

**已定（2026-11-05 裁决）**

1. `cancel` 对终态：`ok=false + already_terminal`（§5.4）；若传输层希望把 no-op 映射成成功，必须在传输层显式转换并保留快照，不能改内核合同。
2. `steer` 的 `queue`：v1 不支持，收到 `true` 即 `invalid_args`，避免“接受但未实现”。
3. `model_round_no`/`tool_round_no` 在 S0：允许返回 `null`，S1 由只读 ledger 补齐；不得用 0 冒充“没有工具轮”。
4. `respond` real 模式：固定 `waiting_unsupported`；成功分支只限 fake/scripted。
5. `poll` event 分页：S0 禁止；`event_seq` 只推进到已返回前缀/最后返回事件。
6. 多会话 `wait`：per-session `cursors` + winner 轮转 + `all_terminal` 布尔。
7. `registration_stale`：映射为 `epoch` + 新快照 + `event_seq=0`，不是 not found，也不新增 wake。
8. v2 回滚：`.v1.bak` + `.prev` + 回滚前归档；整体 fail-closed。

**仍需治理（不阻塞 S0）**

1. S1 的 frozen-baseline bump：三套 hash + D-UI-6 路径 + `load.py`/test 闭集，独立批准后另提交。
2. `s14/test_g12.py` 尚未存在；S1 批准件决定新建或并入既有 gate。
3. cancel-late 统一计数规则、model/tool ledger 最终算法延后到 S1。
