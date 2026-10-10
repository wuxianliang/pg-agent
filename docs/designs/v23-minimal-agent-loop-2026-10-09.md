# v23 minimal agent loop

**日期：2026-10-09**

完整性修订（2026-10-10）：未关闭的 `decide(stop)` 必须经 `cancel` 落成 `stopped`；子 Run 只能由 ParentActor 显式 `start`；`wait` 的调用者含 ParentActor；工具结果只进同一轮回执；在途 `request_id` 不得再调 Worker；外部停止是 Host 直接 `cancel`，不是 `decide` 的输出。

简洁性修订（2026-10-10）：删 `pending_input`、`latest_receipt_revision`、`active_operation_kind`、时间戳、`summary`、`worker_metadata`、`Disposition.reason`。关闭原因只留 `cancelled`、`worker_failed`、`invalid_worker_receipt`、`late_result_after_cancel`。Host 只看三种决定：未关闭的 `stop` 统一调一次 `cancel`。

可靠性修订（2026-10-10）：`running` 先于 `cancel_requested` 返回 `wait`；已设置的 `cancel_requested` 再 `cancel` 零写；T2 失败只允许原 owner 重试同一回执，重启关闭无主 `running` 且不重放；`cancel` 与 T2 锁行串行，先提交者赢；Worker 异常在事务外捕获后只开 T2；`wait` 在事务结束后才 LISTEN；`op_cache` 不淘汰。

---

## 1. 一句话目标，以及明确不继承什么

### 目标

v23 用一条垂直链把三层接通：

```text
Host 读取已提交 Run 快照
  → 纯函数 decide(snapshot, admission) 返回 run_now / wait / stop
  → Host 通过唯一 Control.execute(op) 执行恰好一个动作
  → Control 在事务外调用一次 Worker
  → Control 将 Worker 回执写回同一份 Run 记录
```

第一刀必须完整证明：

```text
start
  → Worker 第一轮
  → 已提交 TurnReceipt
  → decide = run_now
  → steer
  → Worker 第二轮
  → decide = stop
```

### 三个角色

| 角色 | 唯一职责 | 明确禁止 |
|---|---|---|
| **Worker** | 在已提交事务之外执行一次模型请求及有限工具调用，返回一个结构化 `TurnReceipt` | 写 Run、读取或写 PostgreSQL、续跑下一轮、制定长运行策略 |
| **Control** | 唯一的 `execute(op)` 入口；创建 Run、登记一次 Worker 请求、提交回执、处理幂等与版本冲突 | 持有数据库事务等待模型、实现长运行策略、绕过 Worker 直接完成一轮 |
| **Host** | 读取 Control 返回的已提交快照，调用纯 `decide`，再通过 Control 执行一个 op | 直接写 Run、直接调用 Worker、实现第二个调度器或 supervisor |

### 不继承的内容

v23 不继承：

- v13/v15 的代码、模块、SQL 函数或数据库表；
- v8 的 effect/session/step 命令集；
- v15 的 13 个 SQL 文件；
- v13 的 44 段追加式 stage；
- `advance` 或任何第二个推进函数；
- 会写库的 supervisor、goal workflow 或长循环调度器；
- 静态 CE 对照表；
- 字节冻结、负向“禁止调用”作为主要验收方式；
- `replan`、`repair`、`terminal` 等第四种或更多 disposition；
- 将长运行策略塞入 Worker prompt；
- 未来扩展占位、兼容层或迁移适配器。

这是一个**从空目录建立的垂直实现**，不是对旧架构的重构。

---

## 2. `v23/` 文件清单

SQL 尽量集中为一个文件。生产实现与 gate 均位于 `v23/`，不需要 `v13/`、`v15/` 的 import。

```text
v23/
├── README.md
├── v23.sql
├── setup_db.py
├── worker.py
├── control.py
├── disposition.py
├── host.py
└── test_minimal_loop.py
```

| 文件 | 职责 |
|---|---|
| `v23/README.md` | 记录 v23 的三角色、六 op、事务边界、状态机和 gate 命令；不得写成迁移说明 |
| `v23/v23.sql` | 创建唯一持久化表 `v23_runs`、约束、索引、Control 专用数据库角色和通知触发支持；不得创建 events/effects/sessions/steps 表 |
| `v23/setup_db.py` | 删除并重建本 gate 专用数据库，加载唯一的 `v23.sql`，为测试创建 Fake Worker 所需的连接环境 |
| `v23/worker.py` | 定义 Worker 输入、结构化 `TurnReceipt` 校验和 Fake Worker；Worker 不持有数据库连接 |
| `v23/control.py` | 实现唯一 `Control.execute(op)` 入口、短事务、Worker 调用、幂等、版本检查、迟到回执处理和快照读取 |
| `v23/disposition.py` | 实现无副作用的 `decide` 纯函数，只返回 `run_now`、`wait`、`stop` |
| `v23/host.py` | 实现一个 Run 一个驱动协程的 Host 循环；Host 只通过 Control 获取快照和执行 op |
| `v23/test_minimal_loop.py` | 单文件纵向 gate，使用 Fake Worker、Fake 工具和本地 PostgreSQL；不得打开网络套接字 |

### SQL 设计边界

`v23.sql` 只负责：

1. `v23_runs` 表；
2. `CHECK` 约束、唯一约束和必要索引；
3. Control 使用的数据库角色权限；
4. `NOTIFY` 支持所需的最小数据库机制。

不使用：

- PostgreSQL 触发器自动推进 Run；
- SQL 函数模拟 Control；
- `LISTEN`/`NOTIFY` 传递状态内容；
- 事件表、操作表、回执表或历史表；
- 任何第二份 Run 真相。

通知的 payload 只允许包含 `run_id` 和新 `revision`，通知本身不是状态，也不能代替读取快照。

---

## 3. Run、TurnReceipt、Disposition

### 3.1 `v23_runs`：唯一 durable Run 记录

每个 Run 对应 `v23_runs` 中恰好一行。父 Run 和子 Run 也是同一张表中的两行，通过 `parent_run_id` 建立关系。

建议字段如下：

| 字段 | 类型 | durable | 说明 |
|---|---|---:|---|
| `run_id` | `uuid` | 是 | 主键；由调用方在 `start` 前生成，用于 start 幂等 |
| `parent_run_id` | `uuid NULL` | 是 | 父 Run；顶层 Run 为 NULL；只能在创建时写入 |
| `status` | `text` | 是 | `ready`、`running`、`waiting_input`、`completed`、`stopped` |
| `revision` | `bigint` | 是 | 单调递增的 Run 版本；每次 durable 变更加一 |
| `turn_budget` | `integer` | 是 | 允许的 Worker 回合上限；创建后不可修改 |
| `turns_used` | `integer` | 是 | 已提交 Worker 回合数 |
| `latest_receipt` | `jsonb NULL` | 是 | 最近一次被 Control 接受的 `TurnReceipt`；`needs_input` 的 `input_request` 只在这里 |
| `active_operation_id` | `uuid NULL` | 是 | 当前正在等待 Worker 返回的 Control 操作 |
| `active_base_revision` | `bigint NULL` | 是 | Worker admission 时的 revision |
| `active_input_digest` | `text NULL` | 是 | 本次 Worker 输入的 SHA-256 摘要 |
| `cancel_requested` | `boolean` | 是 | 是否已经收到取消请求 |
| `op_cache` | `jsonb` | 是 | 本 Run 生命周期内全部已完成 mutating `request_id` 的收据，不淘汰 |
| `close_reason` | `text NULL` | 是 | 只在 `stopped` 时非空，见下文 |

`op_cache` 是 Run 行内部的 JSONB，不是第二张表。已完成的 `start`、`steer`、`respond` 的 `request_id` 保留到 Run 关闭后的整个生命周期，不得淘汰。重复请求始终返回同一收据，不能因携带最新 `expected_revision` 而再次调用 Worker。

### 3.2 Run 状态

#### `ready`

Run 当前没有 Worker 在途，可以根据最新 progress 决定是否续跑。

- `latest_receipt.outcome` 通常为 `progress`；
- `active_operation_id` 必须为 NULL；
- 可以接受 `steer` 的 Host continuation；
- 也可以接受带新指令的 parent `steer`。

#### `running`

Control 已经在一个已提交 admission 之后调用 Worker。

- `active_operation_id` 非 NULL；
- 不允许第二个 Worker；
- 其他 mutating op 只能返回 busy 或设置 `cancel_requested`；
- `poll`/`wait` 可以观察到该状态。

#### `waiting_input`

最近一次 Worker 明确要求输入。

- `latest_receipt.outcome` 为 `needs_input`，且 `latest_receipt.input_request` 非空；
- 只能通过 `respond` 进入下一轮 Worker；
- `steer` 不得绕过该输入请求；
- `decide` 必须返回 `wait`。

#### `completed`

Worker 返回 `completed`，Run 已完成工作。

- 不再接受 `steer` 或 `respond`；
- `decide` 返回 `stop`；
- `cancel` 对已完成 Run 只返回幂等的已关闭结果，不改变完成事实。

#### `stopped`

Run 被取消、预算耗尽、Worker 失败或收到 Host 的停止动作。

- 不再接受 Worker；
- 后续 `steer`/`respond` 均拒绝；
- `decide` 返回 `stop`；
- 迟到 Worker 回执不得重新打开 Run。

### 3.3 关闭原因

`close_reason` 只允许以下闭集：

```text
cancelled
worker_failed
invalid_worker_receipt
late_result_after_cancel
```

`cancelled` 覆盖用户取消、父 Run 取消、预算耗尽和 Host 外部停止。这些来源对后续效应没有区别：都是一次 `cancel` 落成 `stopped`。调用者身份仍由 actor 校验，不写进 `close_reason`。

`completed` 不写入 `close_reason`，因为 `completed` 本身是一个独立的正常状态，不应被伪装成 `stopped`。

如果 Worker 在 Control 已经收到取消请求后返回：

- Run 状态变为 `stopped`；
- `close_reason = late_result_after_cancel`；
- Worker 回执不进入 `latest_receipt`；
- `turns_used` 不增加；
- 不产生新的 Worker 调用。

### 3.4 `TurnReceipt`

`TurnReceipt` 是 Worker 的输出 DTO。Worker 只返回它；只有 Control 校验通过后，才将它写入 `v23_runs.latest_receipt`。

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | 整数 | 固定为 `1` |
| `turn_id` | uuid | 当前 Worker 回合身份 |
| `run_id` | uuid | 必须匹配目标 Run |
| `base_revision` | bigint | 必须匹配 admission 时的 revision |
| `input_kind` | enum | `initial`、`parent_instruction`、`host_continue`、`parent_response` |
| `input_digest` | string | Control 计算并传给 Worker 的输入摘要 |
| `outcome` | enum | `progress`、`needs_input`、`completed`、`failed` |
| `result` | jsonb | outcome 对应的结构化结果，有界大小 |
| `input_request` | object/null | 仅 `needs_input` 时存在；这是唯一的输入请求 |
| `tool_calls` | array | 本轮有限工具调用记录，最多 8 个 |

#### outcome 约束

- `progress`：
  - `input_request` 必须为 NULL；
  - Run 进入 `ready`；
  - 是否继续由 Host 的 `decide` 决定；
  - Worker 不得返回“下一轮必须执行”的字段。
- `needs_input`：
  - `input_request` 必须存在；
  - Run 进入 `waiting_input`；
  - `input_request.interaction_id` 必须为规范 UUID；
  - 后续只能由 `respond` 消费。
- `completed`：
  - `input_request` 必须为 NULL；
  - Run 进入 `completed`；
  - Host 的 `decide` 返回 `stop`。
- `failed`：
  - `input_request` 必须为 NULL；
  - Run 进入 `stopped`；
  - `close_reason = worker_failed`；
  - 不产生 `repair` 或 `replan` 决定。

Worker 不返回 `cancelled`。取消是 Control 对 Run 生命周期的写入，不属于 Worker 的业务判断。

工具边界：所有模型与工具调用只能由当前这一轮的 Worker 在 admission 事务提交之后、commit 事务开始之前执行。每个工具的输入、输出或结构化失败必须写入本轮返回的同一个 `TurnReceipt.tool_calls`，最终模型结果写入同一个 `TurnReceipt`，由 Control 在一次 commit 事务中整体校验并持久化。工具不得直接调用 Control、创建 Run、调用 Worker、触发下一个 op 或启动第二个续跑。

### 3.5 `Disposition`

`Disposition` 是纯函数的返回值，只存在于内存中，不写入 Run。

字段：

```text
schema_version: 1
run_id: uuid
observed_revision: bigint
decision: run_now | wait | stop
```

`Disposition` 不包含：

- Worker prompt；
- 工具调用；
- scheduler hint；
- replan/repair/terminal；
- 可被 Control 当成授权的隐藏字段；
- 下一步具体 op。

`run_now` 只表示 Host 可以基于该快照执行一次续跑 op。它不代表纯函数自己调用 Worker。

### 3.6 durable 与参数的边界

#### durable

- Run 身份和 parent 关系；
- status、revision；
- turns_used、turn_budget；
- 最新已接受回执；
- waiting input；
- 当前 Control 操作身份；
- cancel 请求；
- 幂等收据；
- close reason。

#### 仅请求参数

- `expected_revision`；
- `request_id`；
- `instruction`；
- `response`；
- `continuation=true`；
- `timeout_seconds`；
- Host 提供给 `decide` 的 `execution_accepted`；
- Worker 的本轮输入，不作为独立状态表保存。

#### 仅内存数据

- `Disposition`；
- Worker Python 对象；
- Host 协程；
- 通知；
- 数据库连接；
- `LISTEN` 等待句柄。

---

## 4. 六个 op 的完整合同

唯一入口：

```text
Control.execute(
    op: string | null,
    actor: ActorContext,
    request: object
) -> ControlResponse
```

- `op` 缺省或为 NULL：按 `wait` 处理；
- `op` 必须是 `start`、`poll`、`wait`、`cancel`、`steer`、`respond` 之一；
- 未知 op 直接拒绝，不执行数据库写入；
- 六个 op 不增加任何别名。

在途幂等：对 `start`、`steer`、`respond`，相同 `request_id` 且请求摘要相同的在途重试必须绑定到原 `active_operation_id`，等待或返回该同一操作最终提交的结果，不得再次调用 Worker。相同 `request_id` 搭配不同请求摘要立即拒绝且零写。操作提交后从 `op_cache` 返回完全相同的已提交响应。迟到 Worker 结果只能由原 Control finalizer 处理，不能由重试请求重新提交。

### 4.1 `start`

#### 调用者

- Host 只创建顶层 Run（`parent_run_id` 为 NULL）。
- 非空 `parent_run_id` 的 `start` 只能由 `ParentActor(parent_run_id)` 提交。Host 不得读取 Worker 回执后自行推导 child instruction、决定是否创建 child，或冒充 ParentActor。Host 只能转发已经由 ParentActor 明确给出的 `start` 请求。Worker 的 `summary`、`result` 只是数据，不是创建 child 的授权。

#### 必需请求

```text
run_id
parent_run_id: uuid | null
instruction: non-empty string
turn_budget: positive integer
request_id: uuid
```

`expected_revision` 对 `start` 必须为 NULL，因为新 Run 没有旧版本。

#### 前置状态

- `run_id` 不存在，或是相同 `run_id` 的幂等重放；
- `turn_budget > 0`；
- 顶层 Run 的 `parent_run_id` 为 NULL；
- 子 Run 的 `parent_run_id` 必须等于 `actor.parent_run_id`；
- 父 Run 必须存在且不是 `stopped` 或 `completed`；
- `instruction` 不允许为空；
- `request_id` 不能与已有不同请求内容复用。

#### 写入

第一段短事务：

1. `INSERT v23_runs`；
2. `status = running`；
3. `revision = 1`；
4. `active_operation_id = request_id`；
5. `active_base_revision = 1`；
6. 保存 `active_input_digest`；
7. 提交。

事务提交后，Control 才调用一次 Worker。

第二段短事务：

- 校验 `active_operation_id`；
- 校验 Worker 回执；
- 写入 `latest_receipt`；
- `turns_used = 1`；
- 清除 active 字段；
- 根据 outcome 设置 `ready`、`waiting_input`、`completed` 或 `stopped`；
- `revision += 1`；
- 写入 `op_cache`；
- 提交；
- 事务提交后发通知。

#### 返回

返回：

```text
{
  schema_version: 1,
  operation: "start",
  outcome: "committed",
  snapshot: RunSnapshot
}
```

`start` 必须等到本轮 Worker 完成并且第二段事务提交后才返回。

#### 拒绝

- run_id 已存在但请求内容不同：`idempotency_conflict`；
- parent 不存在或无权创建子 Run：统一返回 `not_found_or_unauthorized`；
- 预算非法：`invalid_request`；
- Worker 失败：先 durable 写入失败状态，再向调用方抛 `WorkerError`；
- Worker 回执非法：先关闭 Run，再抛 `WorkerContractError`。

### 4.2 `poll`

#### 调用者

Host 或具有 parent 关系的调用者。

#### 前置状态

只要求目标 Run 存在且 actor 有观察权限。

#### 写入

无。不得更新 `updated_at`、revision、访问时间或 hint。

#### 返回

立即返回当前已提交 `RunSnapshot`。

#### 特性

- 不调用 Worker；
- 不调用 `decide`；
- 不推进 Run；
- 未授权与不存在使用相同错误，避免泄漏 Run 是否存在；
- 只原样返回结构化快照，不从回执推导下一步。

### 4.3 `wait`

#### 调用者

Host，或对目标 Run 具有读取权限的 `ParentActor`。

#### 请求

```text
run_id
since_revision: bigint | null
timeout_seconds: finite number in [0, 3600]
```

缺省 `op` 也进入此路径。`since_revision = NULL` 时立即返回当前已提交快照，不等待任何下一版本。

#### 前置状态

actor 必须可观察目标 Run。非法 `run_id`、无权 actor、非有限或超范围 `timeout_seconds`、非法 `since_revision` 必须拒绝且零写。

#### 行为

1. 先做一次短读事务，然后 COMMIT 或 ROLLBACK；
2. 如果当前 revision 已大于 `since_revision`，立即返回；
3. 如果目标已经是 `waiting_input`、`completed` 或 `stopped`，立即返回；
4. 只有事务已经结束后才 LISTEN。监听、等待和超时期间不得持有数据库事务，不得 `idle in transaction`；
5. 通知到达后结束等待；
6. 结束后重新开启短读事务，再读一次完整快照；
7. 超时也必须重新读取快照，不得返回旧缓存；
8. 通知 payload 只用于唤醒，不用于构造返回状态。

#### 写入

无。

#### 返回

```text
{
  schema_version: 1,
  operation: "wait",
  wait_result: "changed" | "timed_out" | "already_interesting",
  snapshot: RunSnapshot
}
```

`wait` 不调用 `decide`，也不调用 Worker。它不是 scheduler，不会在等待期间续跑 Run。

### 4.4 `cancel`

#### 调用者

- Host；
- 对子 Run 有 parent 权限的 parent actor。

#### 请求

```text
run_id
expected_revision: bigint
request_id: uuid
```

`cancel` 不接受关闭来源。预算耗尽、外部停止、用户取消、父 Run 取消都是同一次 `cancel`。

#### 前置状态

- `expected_revision` 必须与当前 revision 一致；
- request_id 的重复调用按幂等规则处理；
- `completed` 或 `stopped` 允许幂等返回；
- `running`、`ready`、`waiting_input` 可以取消。

#### 写入

- `ready` 或 `waiting_input`：
  - `status = stopped`；
  - `close_reason = cancelled`；
  - `revision += 1`；
  - 写入 op cache。
- `running` 且 `cancel_requested` 已为真：零写，不增加 revision，返回当前快照。
- `running` 且 `cancel_requested` 仍为假：
  - 只这一次把 `cancel_requested` 设为真；
  - `revision += 1`；
  - 保留 `active_operation_id`；
  - 不伪造 Worker 回执；
  - 由原 T2 finalizer 收尾。
- `completed`：
  - 不改状态；
  - 返回 `already_closed`。
- `stopped`：
  - 返回已有状态。

#### 返回

```text
cancel_requested
cancelled
already_closed
```

`cancel` 不保证中断已经发出的模型请求。它保证的是：

1. 取消请求先 durable；
2. 取消后的 Worker 回执不得重新打开 Run；
3. 迟到回执不得增加 `turns_used`；
4. 迟到回执不得变成新的 progress。

### 4.5 `steer`

#### 两种合法形态

##### parent 指令形态

parent 必须带新指令：

```text
{
  run_id,
  expected_revision,
  request_id,
  parent_instruction: non-empty string
}
```

调用者必须是目标 Run 的 parent。

##### Host 续跑形态

Host 使用无新输入标记：

```text
{
  run_id,
  expected_revision,
  request_id,
  continuation: true
}
```

该形态不得同时出现 `parent_instruction`。

#### 前置状态

- Run 必须为 `ready`；
- `waiting_input` 不得通过 `steer` 绕过；
- `completed`/`stopped` 拒绝；
- `running` 由版本和 active operation 保护；
- 预算不得已耗尽；
- parent 指令必须通过 parent-child 关系校验；
- Host continuation 不附带新指令。

#### 写入与 Worker 调用

第一段短事务：

- 锁定 Run；
- 检查 `expected_revision`；
- 设置 `status = running`；
- 设置 active operation 字段；
- `revision += 1`；
- 提交。

事务外调用一次 Worker：

- `parent_instruction` 作为本轮输入；
- `continuation=true` 时输入为无新输入标记；
- Control 不能在此处注入新的长运行策略；
- Worker 最多执行有限工具调用。

第二段短事务与 `start` 相同，接受并写回回执。

#### 返回

`steer` 必须等待到本轮 Worker 完成并返回已提交快照。

#### 拒绝

- Run 处于 `waiting_input`：`waiting_input_requires_respond`；
- 不带 parent_instruction 且没有 `continuation=true`：`missing_steer_input`；
- parent 不是目标 parent：`not_found_or_unauthorized`；
- revision 不符：`revision_conflict`；
- Worker 迟到或取消：返回 `late_result_discarded`，不产生 progress。

### 4.6 `respond`

#### 调用者

- 子 Run 的 parent actor；
- 顶层 Run 的 Host owner。

#### 请求

```text
{
  run_id,
  expected_revision,
  request_id,
  interaction_id,
  response: structured JSON value
}
```

#### 前置状态

- Run 必须为 `waiting_input`；
- `interaction_id` 必须与 `latest_receipt.input_request.interaction_id` 完全相等；
- 只能回答当前 waiting input；
- 不能使用 `steer` 代答；
- 迟到回答在 waiting input 已被取消或消费后拒绝。

#### 写入与 Worker 调用

第一段短事务：

- 锁定 Run；
- 校验 revision 和 interaction_id；
- 设置 `status = running`；
- 设置 active operation；
- `revision += 1`；
- 提交。

事务外调用一次 Worker，输入类型为 `parent_response`。

第二段短事务：

- 校验回执；
- 写入 latest receipt；
- 增加 `turns_used`；
- 根据 outcome 设置下一状态；
- 写入幂等收据；
- 提交并通知。

#### 返回

等待这一轮 Worker 完成并返回已提交快照。

#### 拒绝

- 当前不是 `waiting_input`：`not_waiting_input`；
- interaction_id 不匹配：`interaction_conflict`；
- response 结构不符合 `latest_receipt.input_request` 声明：`invalid_response`；
- revision 不符：`revision_conflict`。

---

## 5. `decide` 的输入、校验、三条输出与优先级

实现位置：`v23/disposition.py`。

签名形状：

```text
decide(
    snapshot: RunSnapshot,
    execution_accepted: bool
) -> Disposition
```

`execution_accepted` 是本次 Host 判断是否接纳继续执行的**非 durable 参数**。它不是 Worker 的 prompt，不写 Run，也不由 Control 解释为长运行策略。

### 5.1 输入校验

纯函数必须先校验：

1. `snapshot.schema_version == 1`；
2. `run_id` 是规范 UUID；
3. `revision >= 0`；
4. `turn_budget` 是正整数；
5. `0 <= turns_used <= turn_budget`；
6. `status` 属于五个 Run 状态；
7. `status == waiting_input` 时 `latest_receipt.input_request` 必须存在；
8. `status != waiting_input` 时不得把 `input_request` 当作待回答；
9. `status == running` 时必须存在 active operation；
10. `status != running` 时不得存在 active operation；
11. `latest_receipt` 的 `run_id` 与快照一致；
12. 有回执时，其 `base_revision` 必须小于当前 `revision`；
13. `execution_accepted` 必须是真正的布尔值，整数 `0/1` 不接受；
14. `latest_receipt.outcome` 与 Run 状态不能矛盾；
15. `turns_used` 不得超过 `turn_budget`。

任何校验失败都抛出 `ValueError`。不得返回第四种 disposition，也不得把非法输入降级成 `wait`。

### 5.2 三条输出

#### `stop`

表示 Host 不得再发起下一轮 Worker。

触发条件：

- `status == completed`；
- `status == stopped`；
- `latest_receipt.outcome == failed`；
- `turns_used >= turn_budget`；
- 已设置 `cancel_requested` 且当前没有可安全继续的状态。

#### `wait`

表示 Host 暂时不执行 Worker，但可以通过 `wait` 获取后续已提交变化。

触发条件：

- `status == running`；
- `status == waiting_input`；
- 当前执行未被 `execution_accepted` 接纳；
- 其他不满足续跑条件但尚未关闭的状态。

#### `run_now`

表示 Host 可以发起**恰好一次**续跑：

- Run 为 `ready`；
- `latest_receipt.outcome == progress` 或允许首次续跑；
- `turns_used < turn_budget`；
- `execution_accepted is True`；
- 没有 cancel 请求；
- 没有 active operation。

### 5.3 优先级

优先级固定为：

```text
非法输入
  > 已停止/已完成
  > running
  > cancel_requested
  > waiting_input
  > failed receipt
  > budget exhausted
  > execution not accepted
  > ready + progress + accepted
```

对应伪代码：

```text
validate(snapshot, execution_accepted)

if status in {completed, stopped}:
    return stop

if status == running:
    return wait

if cancel_requested:
    return stop

if status == waiting_input:
    return wait

if latest_receipt.outcome == failed:
    return stop

if turns_used >= turn_budget:
    return stop

if execution_accepted is false:
    return wait

return run_now
```

纯函数不看墙上时钟、不睡眠、不访问数据库、不调用 Worker、不提交通知、不写 Run。

---

## 6. Host 循环伪代码与事务边界

### 6.1 一个 Run 一个 Host 驱动协程

Host 进程内必须为每个 Run 建立唯一驱动协程：

```text
host_driver(run_id):
    ensure no second host coroutine exists for run_id

    snapshot = Control.execute("start", ...)
    loop:
        decision = decide(snapshot, execution_accepted=supplied_admission)

        if decision == run_now:
            snapshot = Control.execute(
                "steer",
                expected_revision=snapshot.revision,
                continuation=true
            )
            continue

        if decision == wait:
            wait_result = Control.execute(
                "wait",
                since_revision=snapshot.revision,
                timeout_seconds=bounded_timeout
            )
            snapshot = wait_result.snapshot
            continue

        if decision == stop:
            if snapshot.status in {completed, stopped}:
                return snapshot
            return Control.execute(
                "cancel",
                run_id=run_id,
                expected_revision=snapshot.revision
            ).snapshot
```

Host 不直接读取数据库表。它通过 Control 获得 `RunSnapshot`，因此所有可观察状态都来自已提交数据。

### 6.2 Start、续跑和等待的边界

#### Admission 事务

```text
BEGIN
SELECT v23_runs ... FOR UPDATE
检查 actor、状态、expected_revision、幂等
更新 active_operation 和 status=running
revision += 1
COMMIT
```

事务结束后才能调用 Worker。

#### Worker 区间

```text
Worker.run(worker_request)
```

这个区间：

- 不持有 PostgreSQL 事务；
- 不允许 Control 的数据库连接处于未提交状态；
- 只执行一轮模型请求；
- 工具调用数量和总输出大小受 Worker contract 限制；
- 返回后不自动再次调用自己。

#### Commit 事务

```text
BEGIN
SELECT v23_runs ... FOR UPDATE
校验 active_operation_id
校验 TurnReceipt
处理 cancel_requested / 迟到结果
更新 latest_receipt、status、turns_used、revision
写入 op_cache
COMMIT
NOTIFY v23_run_changed
```

通知必须在 COMMIT 之后发出，且只用于唤醒等待者。等待者被唤醒后必须重新读取快照。

### 6.5 失败合同

- `running` 且 `cancel_requested` 时，Host 不得再调 `cancel`，必须 `wait` 到原 active operation 收尾。只有第一次把 `cancel_requested` 设为真的 `cancel` 可以改 revision。
- T2 提交失败时，只有持有该 `active_operation_id` 的原 Control 调用可以用同一份 `TurnReceipt` 重试 T2。任何新调用不得因此再调 Worker。进程重启时，Control 在重新服务前把没有存活本地 owner 的 `running` Run 在短事务中关闭为 `stopped/cancelled`，不重放 Worker。
- `cancel` 与 T2 锁定同一行并串行提交。T2 先提交则回执按当时状态接受，随后 `cancel` 只做该状态允许的转换。`cancel` 先提交则随后的 T2 丢弃回执并提交 `stopped`，不增加 `turns_used`，不写 `latest_receipt`，不重新打开。
- `start`、`steer`、`respond` 的 Worker 或工具异常都在事务外捕获。Control 只开新的 T2，提交 `failed` 回执并把 Run 置为 `stopped/worker_failed`。异常路径不得再调 Worker，也不得在等待模型或工具时持有事务。

### 6.3 通知与等待

通知不是队列，不是事件日志，也不是回执：

- 允许通知丢失；
- 允许多个 revision 合并为一个通知；
- payload 不携带业务状态；
- `wait` 到超时必须重读；
- 不使用通知推断“Worker 已完成”；
- 不用 `NOTIFY` 驱动下一轮 Worker。

### 6.4 取消与迟到结果

如果 Worker 已经在运行：

```text
cancel:
    Control admission tx:
        cancel_requested = true
        revision += 1
        commit

late Worker result:
    Control commit tx:
        if cancel_requested:
            status = stopped
            close_reason = late_result_after_cancel
            discard receipt
            turns_used unchanged
            commit
```

取消不会把未完成的模型调用伪装成已取消回执，也不会盲目重新执行。

---

## 7. 完整协调流程

以下流程使用两个 Run：

- `P`：parent Run；
- `C`：child Run，`C.parent_run_id = P.run_id`。

整个流程中，Host 是唯一驱动者；parent 不直接写 child，所有动作都经 Control。

### 7.1 Parent start

```text
Host
  → Control.execute(start, run_id=P, instruction=parent_task)
      → admission tx
      → Worker(P) 一轮
      → commit receipt(P)
  ← P snapshot: ready, receipt=progress
```

此时：

- P 已有一条已提交 progress；
- Worker 没有续跑；
- Control 没有生成子 Run；
- Host 不得读取 P 的回执后自行决定创建 C。

### 7.2 Child 第一轮

只有 `ParentActor(P)` 明确提交 `start`。Host 只转发该请求，不冒充 ParentActor，也不从 Worker 回执推导 child instruction：

```text
Host
  → Control.execute(
        start,
        run_id=C,
        parent_run_id=P,
        instruction=child_task
    )
      → admission tx
      → Worker(C) 第一轮
      → commit receipt(C)
  ← C snapshot
```

若 Worker(C) 返回 `progress`：

```text
C.status = ready
```

Host 对 C 调用：

```text
decide(C.snapshot, execution_accepted=true)
→ run_now
```

随后 Host 使用无新输入标记续跑：

```text
Host
  → Control.execute(
        steer,
        run_id=C,
        expected_revision=C.revision,
        continuation=true
    )
      → Worker(C) 下一轮
      → commit receipt(C)
```

### 7.3 Child needs_input

若 C 第一轮或续跑返回：

```text
TurnReceipt.outcome = needs_input
```

Control 写入：

```text
C.status = waiting_input
C.latest_receipt.input_request = {
    interaction_id,
    prompt,
    options
}
```

此时：

```text
decide(C.snapshot, execution_accepted=true)
→ wait
```

Host 不得用 `steer` 绕过输入请求，也不得让 parent wait 自动替 C 回答。

### 7.4 Parent respond

Parent 通过 Control 回答：

```text
Host / parent actor
  → Control.execute(
        respond,
        run_id=C,
        expected_revision=C.revision,
        interaction_id=C.latest_receipt.input_request.interaction_id,
        response=answer
    )
      → admission tx
      → Worker(C)，input_kind=parent_response
      → commit receipt(C)
  ← C snapshot
```

`respond` 只接受 `waiting_input`。如果 C 在回应前被取消、完成或 revision 已改变，回答拒绝，不产生新 Worker。

### 7.5 Host 再续跑

假设响应后的 Worker 返回 `progress`：

```text
C.status = ready
C.latest_receipt.outcome = progress
```

Host 再次运行：

```text
decide(C.snapshot, execution_accepted=true)
→ run_now

Control.execute(
    steer,
    expected_revision=C.revision,
    continuation=true
)
→ Worker(C)
→ commit completed receipt
```

此时：

```text
C.status = completed
```

### 7.6 Completed → stop

Host 重新读取或使用 Control 返回的已提交快照：

```text
decide(C.snapshot, execution_accepted=true)
→ stop
```

若快照已是 `completed` 或 `stopped`，Host 只结束该 Run 的驱动协程，不再调用 Worker，也不把 `completed` 改成 `stopped`。

若 `decide` 返回 `stop` 但快照仍未关闭，Host 必须以该快照的 `revision` 调用恰好一次 `Control.execute(cancel, expected_revision=revision)`，并只有收到已提交的 `stopped` 快照后才能结束驱动。`close_reason` 为 `cancelled`。预算耗尽与外部停止不分成两种 durable 原因。

外部停止也不由 `decide` 产生。Host 直接调用同一次 `cancel`，不得只结束协程。其后重读快照再调 `decide`，结果只能是对已提交关闭状态的 `stop`。

因此：

- `stop` 是纯函数输出，不是第七个 op；
- 未关闭的 `stop` 必须经 `cancel` 落成 `stopped/cancelled`；
- `completed` 不通过 `cancel` 改成 `stopped`。

### 7.7 Parent 的 wait 不是调度器

当 Parent 想等待 Child：

```text
Control.execute(
    wait,
    run_id=C,
    since_revision=C.revision
)
```

只做以下事情：

- 等通知；
- 重新读取 C 快照；
- 把快照返回给 Parent Host。

它绝不：

- 调用 Worker；
- 调用 `decide`；
- 自动调用 `steer`；
- 自动调用 `respond`；
- 为 Child 选择下一轮；
- 修改 Parent 或 Child Run。

---

## 8. 纵向 gate 断言表

Gate 命令：

```bash
uv run python v23/test_minimal_loop.py
```

退出码 `0` 才算通过。`setup_db.py` 必须删除并重建自己的测试库。整个 gate 只使用 Fake，不开网络套接字。

| 断言 | 必须证明的行为 |
|---|---|
| `v23_unknown_op_rejected` | 未知 op 直接拒绝；没有 SQL 写入；缺省 op 等于 `wait` |
| `v23_start_worker_outside_tx` | admission 已提交后才调用 Worker；Worker 调用期间数据库事务为空闲 |
| `v23_start_receipt_committed` | `start → Worker → commit` 后，poll 能读到对应 receipt、status 和 revision |
| `v23_vertical_run_steer_stop` | 同一个 Run 完成 `start → progress → decide(run_now) → steer → completed → decide(stop)` |
| `v23_worker_called_once_per_op` | 每个 `start`/`steer`/`respond` 最多调用一次 Worker；Worker 不会自续跑 |
| `v23_progress_three_dispositions` | 同一份 progress 在 `execution_accepted=true`、`false`、预算耗尽三种输入下分别得到 `run_now`、`wait`、`stop` |
| `v23_wait_is_read_only` | wait 不修改 revision、turns_used、status 或 op cache |
| `v23_wait_notification_only_wakes` | 通知 payload 不被当成状态；通知后必须重新查询快照 |
| `v23_wait_timeout_rereads` | 超时返回最新已提交快照，而不是等待开始时的旧快照 |
| `v23_respond_only_waiting_input` | `respond` 对 ready/running/completed/stopped 均拒绝 |
| `v23_respond_interaction_exact_match` | interaction_id 不匹配时零写；正确匹配才启动 Worker |
| `v23_parent_child_authority` | 只有 parent Run 能操作 child 的 parent instruction 和 respond；兄弟或无关 Run 被拒绝 |
| `v23_host_continuation_has_no_input` | Host continuation 不携带新指令；parent steer 缺指令则拒绝 |
| `v23_expected_revision_conflict` | revision 不匹配时零写、不调用 Worker |
| `v23_two_consumers_same_revision` | 两个消费者同时使用同一 revision 时只有一个 admission 成功；另一个得到 `revision_conflict` 或 `busy`；Worker 只调用一次 |
| `v23_idempotent_mutation` | 相同 request_id、相同请求内容重复调用只返回缓存结果，不重复调用 Worker |
| `v23_idempotency_conflict` | 相同 request_id 搭配不同请求内容被拒绝，不改 Run |
| `v23_cancel_running` | running Run 的 cancel 只写 cancel 请求，不伪造 Worker 回执 |
| `v23_late_worker_result_discarded` | cancel 后迟到回执不增加 turns_used、不更新 latest_receipt、不重新打开 Run |
| `v23_cancel_ready_and_waiting` | ready/waiting_input 可通过 cancel 关闭；关闭后 steer/respond 均拒绝 |
| `v23_completed_is_not_reopened` | completed Run 的 steer/respond 不会重新 Worker；decide 返回 stop |
| `v23_budget_stop` | `turns_used == turn_budget` 时纯函数返回 stop，Host 不得再调用 steer |
| `v23_invalid_receipt_closes_safely` | 非法 Worker 回执不能写入 latest_receipt；Run 进入 `stopped/invalid_worker_receipt` |
| `v23_parent_wait_does_not_schedule` | parent wait 只读 child 快照，不触发 child Worker |
| `v23_single_run_coroutine` | Host 对同一 run_id 只允许一个驱动协程；第二个驱动在 Host 层被拒绝，数据库层仍由 revision 兜底 |
| `v23_only_one_data_table` | v23 数据库只存在 `v23_runs`，不创建 session/effect/step/event/history 表 |
| `v23_no_v13_v15_imports` | v23 源码不 import v13/v15 |
| `v23_no_static_control_map` | v23 不生成静态 CE 映射表，不用 JSON 对照表冒充运行时 |
| `v23_no_socket` | 测试源码和执行期间不使用 `socket`、HTTP client、真实 provider 或外部网络 |
| `v23_fake_tools_bounded` | Fake Worker 的工具调用数量、单项大小和总结果大小有界 |
| `v23_load_is_single_sql` | setup_db 只加载一个 v23 SQL 文件；不追加 v13/v15 loader |

### Gate 不得使用的验收方式

以下不能作为主要 gate：

- “某个旧文件没有改”；
- AST 负向扫描“不得调用某个旧模块”；
- 静态 JSON 表中存在某个签名；
- 只测试 SQL 函数而不经过 `Control.execute`；
- 只测试 Worker 输出而不证明回执已经 durable；
- 只测试 `decide` 而不证明它的结果能驱动同一个 Control；
- 只测试 parent 或 child 单独通过，而不测试两者的真实调用边。

第一刀的绿必须来自正向纵向调用链。

---

## 9. 非目标

v23 明确不交付以下行为：

1. 不实现 `replan`、`repair`、`terminal`；
2. 不添加第四个 disposition；
3. 不添加第七个 op；
4. 不实现后台 scheduler、cron、常驻 supervisor 或自动 tick；
5. 不让 `wait` 触发任何 Worker；
6. 不让 parent wait 代替 parent respond；
7. 不允许 Worker 写 Run 或自行续跑；
8. 不允许 Host 直接写 PostgreSQL；
9. 不允许 Host 直接调用 Worker；
10. 不建立事件日志、effect 表、session 表、step 表、Run 历史表；
11. 不实现多 Run 全局公平调度；
12. 不实现真实 provider、真实工作区工具或真实网络；
13. 不承诺取消能够杀死已经发出的模型请求；
14. 不在取消后重放或盲目重执行迟到 Worker；
15. 不把 Worker 回执里的自然语言当作 Control 决策依据；
16. 不把长运行策略写入 Worker prompt；
17. 不把 `execution_accepted` 持久化成第二套 scheduler 状态；
18. 不通过静态映射表声称与 RepoPrompt-CE 运行时兼容；
19. 不迁移 v13/v15 的任何函数、表、权限模型或测试夹具；
20. 不将 parent-child 关系扩展为工作流引擎；子 Run 只能由显式 `start` 创建，Control 不自动编排 DAG。

---

## 10. 实现顺序：同一刀，不拆成可独立关闭的 stage

v23 必须作为一个整体实现和验收，不拆成“先 SQL、后 Worker、再 Host”的多个可独立关闭里程碑。原因是单独绿色的 SQL 或 Worker 无法证明用户要求的协调边已经存在。

### 步骤 1：建立文件与单表 schema

同时创建：

- `v23/v23.sql`
- `v23/setup_db.py`
- `v23/README.md`

实现唯一 `v23_runs` 表及其约束：

- 五个 Run status；
- 四个 close reason 约束；
- revision、budget、active operation 和 op cache；
- parent 自引用；
- Control 写权限；
- Worker 无数据库权限。

此时不宣称 v23 已可运行，只完成最小数据承载面。

### 步骤 2：实现 Worker DTO 与 Fake Worker

在 `worker.py` 中定义：

- `WorkerRequest`；
- `TurnReceipt`；
- receipt schema validator；
- 有界 Fake Worker；
- 可按测试脚本返回 `progress`、`needs_input`、`completed`、`failed`。

Worker 接口必须是一次调用一次返回：

```text
worker.run(request) -> TurnReceipt
```

不得在 Worker 内部循环调用自身，不得打开数据库连接。

### 步骤 3：实现 Control 的唯一 execute(op)

在 `control.py` 中一次性实现六个 op：

1. 缺省 wait；
2. 未知 op 拒绝；
3. poll；
4. wait；
5. start；
6. steer；
7. respond；
8. cancel。

其中 `start`、`steer`、`respond` 必须完整实现：

```text
admission 短事务
→ 事务外 Worker
→ commit 短事务
→ 返回已提交快照
```

同一步完成：

- expected_revision；
- request_id 幂等；
- 两个消费者竞争；
- active operation；
- cancel_requested；
- 迟到回执；
- parent 权限；
- interaction_id；
- 通知。

不能先交一个没有幂等或没有迟到结果处理的半套 Control。

### 步骤 4：实现纯 disposition

在 `disposition.py` 中实现 `decide`，只允许：

```text
run_now
wait
stop
```

同时完成：

- 严格输入校验；
- 固定优先级；
- progress 在预算、接纳与状态不同组合下的三种结果；
- 非法输入抛错。

不得在纯函数中读取数据库、睡眠或调用 Control。

### 步骤 5：实现 Host 单 Run 驱动协程

在 `host.py` 中连接：

```text
Control snapshot
→ decide
→ exactly one Control effect
```

要求：

- `start` 只执行一轮 Worker；
- `run_now` 只触发一次 `steer(continuation=true)`；
- `wait` 只等通知并重新读取；
- `stop` 直接结束循环；
- 每个 Run 只有一个 Host 驱动协程；
- Host 不拥有任何 SQL 写入代码；
- Host 不直接持有 Worker 实例。

### 步骤 6：实现完整 parent-child 场景

在同一个 `test_minimal_loop.py` 中完成唯一纵向场景：

```text
parent start
  → child start
  → child progress
  → decide(run_now)
  → child steer(continuation)
  → child needs_input
  → parent respond
  → child progress
  → child steer(continuation)
  → child completed
  → decide(stop)
```

测试必须从 `Control.execute` 入口开始，不能直接调用内部 SQL 或 Fake Worker 来替代 Control。

### 步骤 7：加入并发、取消、迟到和通知 gate

同一测试文件继续加入：

- 两个消费者争夺同一 revision；
- request_id 重放；
- 同 request_id 异参数；
- running cancel；
- cancel 后迟到 Worker；
- waiting_input 的迟到 respond；
- wait 通知丢失或合并；
- wait 超时重新读取；
- completed 不可重新打开。

这些场景与纵向链必须在同一次 gate 中通过。

### 步骤 8：运行唯一 gate 并收尾

执行：

```bash
uv run python v23/test_minimal_loop.py
```

只有以下全部成立，v23 才算完成：

- 纵向 start → receipt → decide → steer → receipt → stop 通过；
- parent-child needs_input/respond 通过；
- 所有事务边界通过；
- 迟到结果和竞争 revision 通过；
- 未知 op 与缺省 wait 通过；
- gate 无套接字；
- v23 数据库只有一份 Run 表；
- v23 没有 v13/v15 import；
- 没有第二 advance、静态对照表或会写库 supervisor。

这一步是 v23 的唯一完成门，不允许先提交一个只证明 schema、Worker 或纯函数的独立“阶段成果”。
