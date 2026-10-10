# v23 minimal agent loop：开发计划

**日期：2026-10-10 · 状态：W1–W7 实现及技术验收完成；M1 完整运行时 gate 已实跑退出 0，50/50 标签、382 个 labeled subcases。最终收尾交付保留外部提前提交 `1e3d5a4`，追加 closeout commit 并正常推送；提交/推送成功与否以实际 git 结果及交付报告为准，不在提交前伪写成功。**

本计划对应设计稿 2026-10-10 修订版；只有一个交付里程碑 M1。下文 W0–W7/Step 1–8 是内部工作包，不是可独立关闭或提前提交的 stage。Oracle 生成的计划正文作为保真基线，决策由本文显式裁定；源码与用户约束优先于 Oracle 的错误引用或判断。

收尾说明：§2、§4 的「当前基线」和旧源码行号描述的是计划建立时的历史草案，不是最终未完成状态；完整实际证据以 §11.1 与 `docs/reviews/v23-conformance-matrix-2026-10-10.md` 的测试函数映射为准。原计划要求的一 M1 一提交顺序没有发生：外部 `1e3d5a4` 提前提交，用户明确授权保留不变并追加最终收尾；详见偏差台账。Oracle 全面审查没有返回完成结论，不能据超时制造批准；独立 peer review 的 P1/P2 修正已经核对并由完整 gate 验证，用户要求不再发起审查循环。

## 1. Summary

本计划把当前 `v23/` 草案收敛到 `docs/designs/v23-minimal-agent-loop-2026-10-09.md` 的 2026-10-10 合同，并以唯一正向完成门 `uv run python v23/test_minimal_loop.py` 验收。方案采用**针对 v23 的垂直修正**，不重构 v13/v15，也不引入第二个 scheduler、事件表、历史表、真实 provider 或额外 disposition/op。目标链路是：Host 读取已提交 `RunSnapshot`，纯函数 `decide` 返回 `run_now`/`wait`/`stop`，Host 通过唯一 `Control.execute` 执行一个 op，Control 在 admission 事务提交后调用一次 Worker，再在 T2 事务中校验并 durable 写回同一轮 `TurnReceipt`。计划建立时的源码只能视为待核验基线；只有完整 parent-child、needs-input/respond、并发、幂等、取消竞态、owner 丢失、通知等待、事务状态和 FakeTool 运行时证明全部通过，v23 才算完成。本次收尾已实际跑过全部 50 标签及 382 子场景，结果与收尾工件见 §11.1。

## 2. Current-state analysis

### 2.1 权威边界与完成标准

权威设计是：

- `docs/designs/v23-minimal-agent-loop-2026-10-09.md:1-1397`
- 本文 §2 记录当前工作区证据；初始骨架已整合进正文，不再作为独立权威引用。
- 仓库通用约束是 `AGENTS.md:1-78`

设计稿明确 v23 是从空边界建立的独立实现，不继承 v13/v15 的表、SQL 函数、supervisor、长循环或兼容层。唯一持久化表是 `v23_runs`，唯一入口是 `Control.execute(op, actor, request)`，唯一 gate 是：

```bash
uv run python v23/test_minimal_loop.py
```

当前文件已存在，但计划文件明确说明它们没有验收证据，因此不能把“源码存在”或局部测试通过视为完成。

### 2.2 当前职责与调用链

当前目标架构已经基本成形：

```text
Host.drive
  → Control.execute("start")
  → admission transaction
  → Worker.run
  → commit/finalize transaction
  → committed RunSnapshot
  → decide(snapshot, execution_accepted)
  → Control.execute("steer" | "wait" | "cancel")
```

各组件当前职责如下：

| 组件 | 当前位置 | 已有职责 | 计划处理 |
|---|---|---|---|
| SQL durable state | `v23/v23.sql:1-50` | 创建 `v23_runs`、角色、基础 CHECK、索引 | 明确 SQL/Python 不变量边界，补齐可表达的结构约束 |
| DB reset | `v23/setup_db.py:1-53` | 删除并重建独立数据库，加载一个 `v23.sql` | 保持单 SQL、Unix socket、最小权限和 gate 隔离 |
| Worker DTO/Fake | `v23/worker.py:1-196` | `WorkerRequest`、`TurnReceipt`、大小限制、FakeWorker | 严格 DTO-only、实际 FakeTool handler、同轮工具回执 |
| Control | `v23/control.py:1-494` | 六 op 分派、T1/Worker/T2、owner map、取消、等待 | 修正幂等、owner 丢失、恢复、T2 重试和锁竞态 |
| Disposition | `v23/disposition.py:1-100` | 三态决定和大部分输入校验 | 对齐完整快照不变量及固定优先级 |
| Host | `v23/host.py:1-62` | 单 Run active set、start/decide/steer/wait/cancel | 补齐外部 stop、线程安全唯一 driver、取消后等待 |
| Gate | `v23/test_minimal_loop.py:1-232` | 部分纵向、幂等、迟到回执、非法回执测试 | 添加设计稿 §8 的全部运行时证明 |

### 2.3 当前可保留的实现事实

以下当前形状符合目标，不应被替换成更复杂的架构：

1. `v23_runs` 是唯一 durable 表，父子 Run 通过 `parent_run_id` 自引用。
2. `Control._mutate` 已有 admission → Worker → finalize 的基本分段，见 `v23/control.py:256-418`。
3. Worker 调用位于事务外，符合 `AGENTS.md:73-78` 的外部 IO 约束。
4. `Control._finalize` 已使用同一 `TurnReceipt` 对象进行校验，见 `v23/control.py:385-418`；这应被正式固化为 DTO-only 合同，而不是改成宽松 mapping 转换。
5. `wait` 已尝试采用“读事务结束后 LISTEN，再重读”的结构，见 `v23/control.py:457-494` 当前 `_wait` 实现。
6. `decide` 已采用闭集三态和 `running` 优先于 `cancel_requested` 的基本顺序，见 `v23/disposition.py:77-100`。
7. `Host.drive` 已经只通过 Control 观察和执行，见 `v23/host.py:17-52`。
8. `worker.py` 已有工具数量、单项大小、总大小和 result 大小常量，见 `v23/worker.py:9-13`。
9. `setup_db.py` 已限制本地 Unix-domain PostgreSQL 连接，见 `v23/setup_db.py:17-27`。

### 2.4 必须修正的当前差异

#### A. `cancel` 的幂等与零写

当前 `v23/control.py:420-455` 在重复 `cancel_requested` 时返回 `cancel_requested`，但不缓存收据；这使不同 retry 路径的可观察语义不够明确。

目标裁定：

- 锁行后先校验 actor 权限，再查 `op_cache`；同 request_id 的 `done/recovered` 收据匹配 operation/actor/request_digest 后原样重放，绝不校验新的 `expected_revision`，也绝不写库。不能在授权前用 cache 泄漏 Run 是否存在。
- 第一次使 Run 进入 `cancel_requested` 或 `stopped` 的 cancel 请求写入 `op_cache`。
- `running + cancel_requested=true` 的新 `request_id` cancel 必须：
  - 要求 `expected_revision` 等于当前 revision；
  - 零写；
  - 不增加 revision；
  - 不新增 `op_cache` 条目；
  - 返回当前快照。
- `completed`/`stopped` 的 no-op cancel 不改变状态、revision 或 `turns_used`；不新增 cache 条目。相同 request 重复时仍返回当前已关闭结果，但不会通过 cache 制造额外写入。
- `expected_revision` 不匹配永远优先于普通状态判断，但低于同 `request_id` 的 cache 命中。
- 已 admission 或实际改变状态、因而被 op_cache 保留的 request_id 不得跨 op/actor/语义复用；复用返回 `idempotency_conflict`。零写 no-op cancel 的新 ID 不登记，不承诺为其保存永久收据或跨未来状态冻结观察结果。

这样同时满足：

1. 已接受的 cancel 请求可稳定重放；
2. 已设置 `cancel_requested` 后的重复 cancel 真正零写；
3. 不因 no-op cancel 无限增长 `op_cache`；
4. revision CAS 仍然保护并发调用。

#### B. 在途 owner 消失与进程重启

当前 `v23/control.py:52-63` 使用进程内 `_owners`，`_recover_orphans` 在初始化时关闭没有本地 owner 的 `running` Run；但当前重复在途请求在 owner 缺失时可能返回 `busy`，见 `v23/control.py:279-283`。

目标裁定：

- `_owners` 仍是唯一 live owner registry，不持久化，不扩展为第二状态表。
- 相同 request ID 且 owner 仍在本进程：
  - 不再次调用 Worker；
  - 等待原 owner 的 `done`；
  - 返回原 owner 的最终 response 或同一错误。
- 相同 request ID 但 owner 已确定消失：不重新调用 Worker；由持有 fence 的 runtime 锁定该行，关闭为 `stopped/cancelled`、设置 cancel_requested、清除 active 字段、revision 加一，latest_receipt/turns_used 保持不变。
- recovery 与 pending→recovered 在同一事务提交。`recovered` 保存原 operation、actor/request/input 摘要及 admission_revision；response 固定为 `{schema_version:1, operation:<原op>, outcome:"recovered_orphan", error_code:"owner_lost", snapshot:<关闭后的快照>}`。精确重试返回同一 recovered response，不能伪造正常 committed 回执或在多种 closed/orphan 错误中任选。
- 同进程多个 Control 共用健康 runtime，不重复 recovery；新的 runtime 仅在取得 fence 后执行启动 recovery。
- 进程重启不重放模型请求，也不尝试从 `WorkerRequest` 恢复 Worker。
- 不增加 `active_operation_kind`；该字段已经被设计稿明确删除。恢复路径不依赖知道原 op 类型。

原因是：没有 durable 的“Worker 已经执行到哪一步”事实时，重放会产生重复外部效应；关闭而不重放是唯一安全的 fail-closed 行为。

#### C. Worker 输出是否允许 mapping

目标裁定：**Worker 公共接口严格返回 `TurnReceipt` DTO，不允许 Control 把 mapping 转换成 DTO。**

接口保持：

```text
Worker.run(request: WorkerRequest) -> TurnReceipt
```

允许 Worker 抛出异常；Control 在事务外捕获异常，并在 T2 中构造一个绑定当前 admission 的 `failed` `TurnReceipt`。但若 Worker 正常返回的是 dict、JSON object 或其他类型，必须视为 `invalid_worker_receipt`，不能自动转换。

理由：

- 避免 Control 代替 Worker 猜测 schema；
- 保证所有被 durable 接受的回执都经过相同 validator；
- 让 Fake Worker 和未来真实 Worker 使用同一 DTO 边界；
- 保留 `WorkerContractError` 作为错误合同，而不是兼容层。

#### D. FakeTool 当前没有实际执行

当前 `FakeTool` 仅定义 `name` 和 `handler`，而 `FakeWorker.run` 只读取计划中的 `tool_calls` 数据，见 `v23/worker.py:127-179`。它没有调用 handler。

目标裁定：

- FakeWorker 的 plan 只描述本轮要调用的工具名称和输入。
- Worker 在一次 `run` 中按顺序查找并执行 handler。
- 每个工具调用形成一个同一 `TurnReceipt.tool_calls` 元素，至少包含：
  - 工具名；
  - 输入；
  - 成功输出，或结构化失败；
3. 顺序调用
- handler 正常返回的有界 `{ok:false,...}` 才是结构化业务失败，可作为本轮 tool_calls 数据；未知工具、handler raise、输入/输出无法 JSON 序列化、输出超限和其它运行时异常必须中止本轮 Worker，通过 `WorkerExecutionError` 携带已执行的有界 tool_calls 交给 Control；Control 在事务外捕获后于 T2 合成 `failed` receipt 并落 `stopped/worker_failed`，不得继续为 `completed`。
- 工具调用总数最多 8；单个 canonical JSON 调用记录最多 4096 bytes；完整 canonical JSON `tool_calls` 数组（含括号/分隔符）最多 32768 bytes。9 次计划在任何 handler 执行前失败；不静默裁剪调用计划。
- 工具输出超过界限时，不把完整输出写入回执；写入有界错误对象。
- `TurnReceipt.result` 仍是本轮最终模型结果；工具记录和最终结果一起由 T2 校验、一起 durable 写入。
- FakeTool handler 不持有数据库连接，不创建 Run，不触发下一次 Worker。

这保留“工具属于当前一轮回执”的设计边界，同时让 `v23_fake_tools_bounded` 成为真实行为测试，而不是常量字符串检查。

#### E. SQL CHECK 与 Python validator 的分工

目标裁定如下。

**SQL 强制的内容：**

- `run_id` 主键；
- `parent_run_id` 外键；
- 五个闭集 status；
- `revision >= 0`；
- `turn_budget > 0`；
- `0 <= turns_used <= turn_budget`；
- `close_reason` 四值闭集；
- `status = stopped` 与 `close_reason IS NOT NULL` 的双向关系；
- `status = running` 与 `active_operation_id IS NOT NULL` 的双向关系；
- active 三元组为空或完整；
- active base revision 合法；
- active input digest 为 64 位小写 hex；
- `op_cache` 是 object；
- `waiting_input` 至少对应 needs_input receipt和object input_request；JSON缺key/NULL的CHECK须用显式IS TRUE或COALESCE(...,false)拒绝，不能让SQL三值逻辑把未知当合法。
- parent 不能等于自身；
- 必要索引与权限。

**Python/DTO validator 强制的内容：**

- UUID 是否规范字符串；
- request 字段、缺失字段和额外字段；
- `TurnReceipt` identity、base revision、input kind、input digest；
- outcome 与 input_request 的完整关系；
- interaction ID 的规范性；
- tool call 数量、结构和 byte bounds；
- result JSON 可序列化与大小；
- receipt outcome 与 Run status 的全量一致性；
- `turns_used`、budget、active operation、cancel 状态的组合；
- response schema/options；
- actor 与 parent-child 权限；
- `expected_revision`；
- op_cache digest 冲突。

不把所有 JSON 业务一致性塞进 SQL CHECK，避免 SQL 成为第二份 Worker/Control 状态机；但 Control 角色是唯一正常写入者，所有实际写入必须经过 Python validator 和状态转换。

#### F. `wait` 的 race、通知与事务状态

当前 `_wait` 已有雏形，但 gate 没有真实证明。目标流程固定为：

1. 短读事务读取快照并提交/结束连接。
2. since_revision=NULL先返回already_interesting；否则revision>since返回changed；否则waiting_input/completed/stopped返回already_interesting。此顺序和设计§4.3一致，全部立即返回。
3. 仅在事务结束后用独立 autocommit 连接执行 `LISTEN v23_run_changed`。
4. LISTEN 生效后立即重新读取快照，关闭 read/LISTEN race。
5. 等待期间不持有数据库事务，不出现 `idle in transaction`。
6. 收到通知只作为唤醒，不解析 payload 推导业务状态。
7. 通知到达后重新读取完整快照。
8. 超时后也重新读取完整快照。
9. 丢失通知、重复通知、合并通知都必须得到同一最终快照语义。

gate 必须实际验证：

- Worker 执行时 Control 的数据库连接处于 `TRANSACTION_STATUS_IDLE` 或已经关闭；
- wait 阻塞期间 listener 不在事务中；
- T1/T2 事务均在 Worker 前后结束；
- 通知 payload 不包含也不被当作业务状态。

这沿用 `v8/closeout/v8_closeout.sql:116-142` 的“NOTIFY 只是 wake hint，重新查询才是事实来源”原则，但不引入 v8 的 wait registration 表或扫描器。

- recovery 收据固定为 `recovered_orphan/owner_lost`，精确 request_id 重试原样返回该收据；

## 2.5 Critique 与 Oracle 裁决后的绑定合同

本节是对前述草稿歧义的最终绑定；后续设计、工作项和 gate 以本节为准。它不修改权威设计稿 §5.3 的三态优先级，也不把 Oracle 建议未经核验地当成第四种 disposition 或第七个 op。

### 2.5.1 两种 digest 与 pending/done/recovered 操作收据

`request_digest` 与 `active_input_digest` 永久分离：

- `request_digest` 用于 `request_id` 幂等，包含 operation、actor 身份和语义请求字段，排除 `expected_revision`、timeout 等重试瞬时字段。
- `active_input_digest` 只表示真正交给 Worker 的 canonical input（`input_kind`、instruction/response、continuation），并由 `TurnReceipt.input_digest` 精确回显。
- 不新增 durable 列或第二表；op_cache 内条目以 request_id 为键，统一字段为 `state`、`operation`、`actor_digest`、`request_digest`、`input_digest`、`admission_revision`、`response`、`error_code`。pending 的 response/error_code 为 NULL；done/recovered 保存不可变的已提交收据。cancel 没有 Worker，input_digest/admission_revision 为 NULL，实际写入时直接创建 done。pending/done/recovered 全部留在同一 Run JSONB 且不淘汰，RunSnapshot 排除整个 op_cache，避免递归缓存。
- T1 与 pending 同事务提交；T2 与最终 Run 状态原子替换为 done；recovery 与关闭状态原子替换为 recovered，收据采用 recovery 关闭快照而非 running。完成后的 cache 快照是历史操作收据，不随后续 revision 改写；poll/wait 才返回当前真相。Host 对任何重试得到的缓存收据须 poll 后再 decide，不能把首次 cancel 的历史 running 快照当作当前状态。
- 相同 request_id 的判断顺序固定为：先授权且读取该 request_id 的 cache；命中 `done/recovered` 时原样返回，不重新检查新的 expected_revision；只有 `pending` 才继续校验 active_operation_id，并由原 owner 等待/提交。operation、actor 或 request_digest 任一不匹配都返回 `idempotency_conflict`，零写、零 Worker。

### 2.5.2 Active Control fencing 与恢复

v23 的最小运行范围是：**同一个 gate 数据库同一时间只有一个 active Control runtime/进程**。规范数据库身份 `db_identity` 由本地 PostgreSQL Unix endpoint（规范化 host 路径、port）和 database 组成，并以连接后的 current_database() 核对；不按原始 DSN 字符串区分。进程内 Control 实例共享 runtime/owner registry；角色或连接配置不兼容时拒绝复用。session connection 初始化时只获取一次固定的 session-level `pg_try_advisory_lock`；拿不到锁立即报 `control_runtime_busy`，不能持进程锁无限等待，不能 recovery 或接纳 op。

fence connection 一旦断开、错误或无法确认仍由本进程持有，Control runtime 永久 fail-closed：停止接受新 op，禁止旧 owner 继续提交 T2，也禁止透明重建连接；旧 Worker 的外部调用不重放。所有 mutating T1/T2/recovery 必须复用持有 session-level advisory lock 的同一 fenced connection；Worker 区间不持数据库事务，但 runtime mutex 已释放，其他只读/取消路径可按合同运行。新 runtime 只有按规范数据库身份取得 advisory fence 后才能 recovery `running` 行。拿到锁只表示旧 fence session 已释放，不宣称旧 Python 进程已死；因此旧 runtime 失联后的 owner 不得迁移到新 runtime。

owner registry 是内存资源，不是第二真相；owner 绑定 runtime generation，不能转移 receipt 到新 generation。锁序固定为 runtime mutex → owner registry 短临界区 → SQL 行锁；Worker、join owner、LISTEN/Event 等待和 post-commit notify 均不持这些锁。健康 runtime 内确认 owner 已消失，或新 runtime 取得 fence 后，才能把 pending 恢复为唯一 recovered：status=stopped、close_reason=cancelled、cancel_requested=true、revision 加一，active 清空，turns_used/latest_receipt 保持不变。以首次关闭快照保存原 request 的 recovered_orphan/owner_lost 收据，重复读取不再写库；旧 owner 的迟到回执不能重新打开 Run。

### 2.5.3 工具异常、DTO 边界与可达上限

Worker 公共接口严格为 `Worker.run(WorkerRequest) -> TurnReceipt`；Control 不把 mapping 自动转换为 DTO。FakeTool handler 正常返回的有界 `{ok:false,...}` 是业务结果，可写入当前回合的 `tool_calls`；handler raise、输出不可序列化、输出超限、调用计划预验证失败或其它运行时异常必须通过一个带有已执行工具记录的 `WorkerExecutionError` 离开 Worker，Control 在事务外捕获后于 T2 生成 `failed` receipt，最终 `stopped/worker_failed`，不得继续为 `completed`。

工具计划在执行任何 handler 前完整预验证：9 个调用直接失败且零 handler 执行；每个调用记录上限 4096 bytes；canonical JSON 序列化后的完整 `tool_calls` 数组（含 framing）受 32768 bytes 总限额约束。测试必须用真实 FakeTool 输出构造恰好边界和 aggregate 超限，不能用不可达的“8×4096 逐项求和超总量”伪造场景。

### 2.5.4 wait/park、Host 唯一性与稳定 request_id

公共 `wait` 合同保持设计稿：`waiting_input`、`completed`、`stopped` 立即返回，`wait` 不调度。Host 不新增 `Control.park_until_change` 或其它第二入口：在 `waiting_input` 或 `execution_accepted=false` 下，先清除共享本地 Event，再通过 `execute("poll")` 重新读取快照；若仍需停车，只在正的、有限的 `idle_interval` 内调用 `Event.wait`。醒来或超时后再通过 `execute("poll")`/`execute("wait")` 读取完整快照并重新 decide，不能从 Event/通知推导状态。Parent respond、external stop 和 execution_accepted 改变 signal 共享 Event；未 signal 的外部 mutation 由有界超时后的 poll 发现。停车不持 DB 连接、不写 durable state、不调用 Worker。

同一进程内所有 Host 实例共享 `(db_identity, run_id)` driver registry/Event；sync/async 入口共用，stop/respond 不占 driver 名额。每个待完成语义操作一个 request_id：同一操作跨 poll/redecide、revision conflict 和确认丢失复用；已成功消费的一次 continuation 完成后，即使下一轮仍是 continuation，也必须生成新 ID，不能把两轮误当幂等重放。详见 §3.8.5。

### 2.5.5 decide 优先级、budget 与 stopped-null receipt

严格保留设计稿 §5.3 的优先级：`completed/stopped > running > cancel_requested > waiting_input > failed receipt > budget exhausted > execution not accepted > ready continuation`。因此 `waiting_input` 且 `turns_used == turn_budget` 仍由 `decide` 返回 `wait`；这是设计合同，不采纳将 budget 提前的替代排序。为避免错误的无界 respond，`respond` admission 仍检查 `turns_used < turn_budget`，超预算返回 `budget_exhausted`、零写、零 Worker；该 waiting Run 的退出由 parent/Host 的外部 `cancel` 完成，并由 park 唤醒机制避免 busy-spin。

`stopped` 不等于一定有 receipt：`invalid_worker_receipt`、`cancelled`、`late_result_after_cancel` 在首轮或未接受回执时允许 `turns_used=0` 且 `latest_receipt=NULL`；只有 `worker_failed` 需要 durable failed receipt，`completed`、`waiting_input` 或 `turns_used>0` 仍必须满足对应 receipt 约束。`decide` 对上述合法 stopped-null 快照返回 `stop`。

### 2.5.6 权限与 gate 真实性

`setup_db.py` 以 admin 负责 DROP/CREATE、加载和角色配置；行为测试的 Control DSN 必须显式使用 `v23_control`，不能用默认 superuser。数据库必须 `REVOKE CONNECT ... FROM PUBLIC`，只向 `v23_control` 授予 CONNECT；`v23_worker` 保持 NOLOGIN、显式撤销 CONNECT，并通过 admin/SET ROLE 探针证明不能 CRUD。静态 source checks 只能补充单表/单 SQL/旧 import 边界，不能替代 Control 入口、事务状态、通知、锁竞争、恢复和 FakeTool 的运行时证明。

### 2.5.7 注入与 ack-loss gate 机制

所有新 gate 都使用确定性 Event/Barrier 或测试子类钩子，钩子只由测试注入，不成为公共 op：首次 read 后/LISTEN 前暂停、LISTEN 成功后暂停、T1 commit 前/确认后、Worker 进入/返回、T2 commit 前/确认后。生产没有第二推进入口。每个线程/子进程的异常必须传回主测试；所有 Event 等待、join 和子进程退出均有有限 deadline，超时即红，不能靠固定 sleep 假设交错。

- read/LISTEN race：在首次短读完成后暂停 waiter，另一个 Control.execute mutation 提交，再允许 LISTEN；LISTEN 后重读必须立即发现 revision 变化。
- lost/merged/伪造通知：测试替换 post-commit notifier；屏蔽后实际 mutation 仍提交，在 waiter 已进入等待的 barrier 后触发变化；timeout 返回的快照必须比首次 read 新。合并测试用多个已提交 revision 加一次通知；同库其它 run_id 或伪造高 revision 不得构造目标状态。
- T2 提交前确定 rollback 与提交后 ack-loss 分开：rollback 用 SQLSTATE serialization/deadlock 注入并保留健康 fence；ack-loss 在真实 conn.commit 完成后抛测试异常。二者均记录 Worker 次数、revision、receipt、cache；只有 rollback 路径能重做同一 T2，ack-loss 只能读 done。
- T1 分开覆盖：确定 rollback → 同 ID 可重新 admission；admission 已确认后调用方丢确认 → 原 owner 继续、重试 join；原 Control 不知 COMMIT 是否成功且 Worker 尚未调用 → 观察 pending 后 fail-closed recovery，绝不补执行 Worker。
- 重启：独立子进程取得 fence、真实 T1 后以阻塞 FakeWorker 保持 pending，再终止/退出该进程；新进程通过同一 Control 入口初始化取得 fence并恢复。单独构造 fresh_control() 不等于重启。两进程争 fence时失败者不得 recovery；连接死亡/旧 owner 迟到另设测试。
- 事务边界：以 v23_control 的 conn.get_transaction_status、application_name/backend PID 和 admin pg_stat_activity 探针核对 T1/T2 及 listener。阻塞 Worker 时本操作不持事务/锁，但 cancel 的独立短事务可以提交；不能把其它合法 Control 事务也误判为 Worker 持有事务。
- Host parking：测试 park 注入本地计时/等待探针，断言无变化窗口内调用次数有界、没有 hot loop；分别测试 respond/stop/admission signal 和绕过 Host 的 mutation 无 signal，均由 wake或有限超时 poll 发现。

## 3. Design

## 3.1 总体架构与范围

本次采用**v23 内部的 targeted correction**，不是跨版本 refactor。

原因：

- v23 的模块边界已经与设计稿一致；
- 现有问题集中在合同闭合、竞态和 gate 覆盖；
- 引入 v13/v15 会破坏独立单表和无旧版本 import 的要求；
- 引入第二 scheduler、事件表或恢复队列会改变 v23 的核心证明目标。

目标数据流：

```text
Host
  └─ Control.execute(op)
       ├─ T1 admission transaction
       ├─ COMMIT
       ├─ Worker.run(WorkerRequest)           # no DB transaction
       ├─ T2 finalization transaction
       ├─ COMMIT
       └─ post-commit NOTIFY(run_id, revision)
```

所有 durable 状态只存在 `v23_runs`。`Disposition`、Worker 对象、Host 协程、通知、数据库连接和 owner registry 都是内存或瞬时资源。

---

## 3.2 Durable Run 模型与状态机

### 3.2.1 `v23_runs` 字段

文件：`v23/v23.sql:13-50`

目标字段保持如下：

| 字段 | 类型 | 约束/含义 |
|---|---|---|
| `run_id` | uuid | 主键；start 前由调用方生成 |
| `parent_run_id` | uuid nullable | 顶层为 NULL；子 Run 指向父 Run |
| `status` | text | `ready`、`running`、`waiting_input`、`completed`、`stopped` |
| `revision` | bigint | 每次 durable 状态变化递增 |
| `turn_budget` | integer | 创建后不可修改，必须大于 0 |
| `turns_used` | integer | 已接受 Worker 回合数 |
| `latest_receipt` | jsonb nullable | 最近接受的 TurnReceipt；非法回执不写入 |
| `active_operation_id` | uuid nullable | 当前在途操作 |
| `active_base_revision` | bigint nullable | 当前 Worker admission revision |
| `active_input_digest` | text nullable | 当前 Worker 输入摘要 |
| `cancel_requested` | boolean | durable 取消标记 |
| `op_cache` | jsonb | 本 Run 生命周期内保留的 mutating 请求收据 |
| `close_reason` | text nullable | 仅 stopped 时非空 |

`RunSnapshot` 继续排除 op_cache；只包含 schema_version=1 和表中其它字段的深拷贝、规范 UUID 文本。Control 校验 pending/done/recovered 结构及对应 operation/actor/request/input 摘要，禁止递归嵌入 cache。parent_run_id/turn_budget 创建后不可改；Control role 的 UPDATE 列授权禁止修改 run_id/parent_run_id/turn_budget。

### 3.2.2 状态不变量

| 状态 | 必须满足 |
|---|---|
| `ready` | 无 active operation；通常 latest outcome 为 `progress`；可接受 Host continuation 或 parent instruction |
| `running` | active operation 三元组完整；不得接受第二个 Worker；可被 poll/wait 观察 |
| `waiting_input` | latest outcome 为 `needs_input`；input_request 非空；只能 respond 或 cancel |
| `completed` | latest outcome 为 `completed`；不再接受 Worker；cancel 不得改变完成事实 |
| `stopped` | close_reason 非空；不再接受 Worker；迟到结果不得 reopen |

### 3.2.3 状态转换

```text
start admission:
    nonexistent → running

start/steer/respond T2:
    running + progress      → ready
    running + needs_input   → waiting_input
    running + completed     → completed
    running + failed        → stopped/worker_failed
    invalid receipt         → stopped/invalid_worker_receipt
    cancel_requested        → stopped/late_result_after_cancel

cancel:
    ready/waiting_input     → stopped/cancelled
    running                 → running + cancel_requested=true
    running + late T2       → stopped/late_result_after_cancel
    completed               → completed
    stopped                 → stopped
```

`cancel_requested=true` 后，`decide` 不能把 Run 送入 `run_now`。由于 `running` 优先级高于 `cancel_requested`，运行中的取消请求先通过 `wait` 等待原 T2 收尾；不重复发起 cancel。

---

## 3.3 Control API 与六个 op

文件：`v23/control.py:1-494`

保留唯一接口：

```text
Control.execute(
    op: str | None,
    actor: HostActor | ParentActor,
    request: Mapping[str, Any]
) -> Mapping[str, Any]
```

- `op is None` 等同于 `wait`；
- 合法 op 只有 `start`、`poll`、`wait`、`cancel`、`steer`、`respond`；
- 未知 op 直接 `ControlError("unknown_op")`，零 SQL 写入；
- 所有 operation response 都带 `schema_version=1`、`operation` 和必要 snapshot。

### 3.3.1 请求摘要与输入摘要

Control 必须区分两种 digest：

1. **request digest**
   - 用于同一 `request_id` 的 idempotency；
   - 包含 operation、actor 身份和语义请求字段；
   - 排除 `expected_revision`；
   - 不包含 transient timeout；
   - 同 request ID 搭配不同语义请求立即冲突。

2. **input digest**
   - 用于 `active_input_digest` 和 WorkerRequest；
   - 只描述本轮 Worker 输入：
     - `input_kind`
     - instruction 或 response
     - continuation 标记
   - 不包含 request ID、expected revision 或 actor；
   - receipt 必须精确匹配。

这样 retry 可以携带新的 expected revision 进行 cache replay，但不能改变 Worker 输入。

canonical digest 使用 UTF-8 JSON、sort_keys、紧凑 separators、ensure_ascii=false、allow_nan=false；actor_digest 对 HostActor/ParentActor及parent_run_id使用明确枚举而非对象repr。request_id在Run内作为cache键，operation/actor/语义字段参与request摘要；start expected_revision缺省和显式NULL先归一化。input摘要固定包含input_kind、instruction/response、continuation，不包含request_id、actor、expected_revision或生成的turn_id。

同request_id的pending/done/recovered必须保留到Run生命周期结束之后，不淘汰；cache命中仍先授权，不能把已知UUID变为访问授权。`done.error_code`在worker_failed/invalid_worker_receipt时分别重建WorkerError/WorkerContractError并附原response，首次调用与重放的code/response相同，不能只比较错误文案。recovered.error_code=owner_lost则返回确定的恢复response。

### 3.3.2 `start`

请求：

```text
run_id
parent_run_id: uuid | null
instruction: non-empty string
turn_budget: positive integer
request_id: uuid
expected_revision: absent or null
```

调用者：

- 顶层 Run：`HostActor`；
- 子 Run：`ParentActor(parent_run_id)`；
- Host 不得从 Worker receipt 自己推导 child instruction。

T1：

1. 对 `run_id` 使用事务级 advisory lock，序列化不存在行的 start 竞争。
2. 行已存在时先校验观察/该操作权限，再查 request_id cache。匹配 `done/recovered` 重放；匹配 pending 只能 join 原 owner 或 recovery，不再次 Worker。
3. 若 run_id 已存在但该 start request_id 不属于匹配的 cache/admission，返回 idempotency_conflict。
4. 校验 parent authority 和 parent 当前不是 completed/stopped。
5. 插入 `status=running`、`revision=1`、`active_operation_id=request_id`、`active_base_revision=1`、真正 input digest 的 `active_input_digest`；同一 INSERT/T1 写入该 request_id 的 pending cache。
6. 在确认 T1 commit 成功后才允许调用 Worker；T1 commit acknowledgement 未确认时，不得“补调用”。

Worker：

- 事务外调用一次；
- `input_kind=initial`；
- 不允许 Worker 自己循环。

T2：

- 锁定同一 Run 行；
- 先在 actor 授权后读 op_cache，只有 pending 才验证原 generation owner/active operation；
- 先处理 `cancel_requested`；
- 再校验 TurnReceipt；
- 接受或关闭；
- `turns_used` 只在合法非迟到回执时加一；
- 清除 active 字段；
- `revision += 1`；
- 写入本 operation 的 op_cache；
- 提交后通知。

### 3.3.3 `poll`

请求：

```text
run_id
```

行为：

- 只读；
- 不更新 revision、访问时间、hint 或 op_cache；
- 不调用 decide、Worker 或通知；
- 未授权和不存在统一返回 `not_found_or_unauthorized`。

### 3.3.4 `wait`

请求：

```text
run_id
since_revision: bigint | null
timeout_seconds: finite number in [0, 3600]
```

允许的默认值：

- 缺省 `since_revision` 视为 `NULL`；
- 缺省 `timeout_seconds` 视为 `0`；
- 其他额外字段拒绝。

返回：

```text
{
  schema_version: 1,
  operation: "wait",
  wait_result: "changed" | "timed_out" | "already_interesting",
  snapshot: RunSnapshot
}
```

`wait` 永远不启动 Worker，不调用 decide，不推进 Run。

### 3.3.5 `cancel`

请求：

```text
run_id
expected_revision: bigint
request_id: uuid
```

执行顺序：

1. 锁定 Run 行。
2. 校验 actor。
3. 若 request ID 已 cache，原样返回；不检查新 expected revision。
4. 校验 expected revision。
5. 根据状态执行：
   - `ready`/`waiting_input`：设置 stopped/cancelled、revision+1、写 cache；
   - `running && cancel_requested=false`：设置 `cancel_requested=true`、revision+1、保留 active、写本 cancel cache；
   - `running && cancel_requested=true`：零写，不写 cache，返回当前快照；
   - `completed`/`stopped`：零写，返回 already_closed。
6. 只有真实状态变化才 post-commit notify。

取消不保证杀死已发出的模型请求，只保证：

- cancel 请求先 durable；
- T2 不会 reopen；
- 迟到回执不写 latest receipt；
- 迟到回执不增加 turns_used；
- 迟到回执不再次调用 Worker。

### 3.3.6 `steer`

两种互斥请求形态。

Host continuation：

```text
run_id
expected_revision
request_id
continuation: true
```

Parent instruction：

```text
run_id
expected_revision
request_id
parent_instruction: non-empty string
```

禁止：

- continuation 与 parent_instruction 同时出现；
- parent actor 缺 parent_instruction；
- Host 携带新 instruction；
- waiting_input 通过 steer 绕过 respond。

T1：

- 只能从 `ready` 进入 `running`；
- revision 先加一；
- active 字段写入；
- 提交后 Worker 执行一次。

T2 与 start 相同，包含 invalid receipt、worker exception、cancel race 和 op_cache。

### 3.3.7 `respond`

请求：

```text
run_id
expected_revision
request_id
interaction_id
response: arbitrary finite JSON value
```

调用者：

- 顶层 Run：HostActor；
- 子 Run：目标 Run 的 ParentActor。

T1 前置检查：

- status 必须为 `waiting_input`；
- interaction ID 必须与 latest receipt 完全相等；
- response 必须符合 input_request 声明的 options/response_schema；
- 不接受 stale response；
- 不接受 steer 代答；
- T1必须检查turns_used < turn_budget；否则budget_exhausted零写、零Worker。

Worker 的 `input_kind=parent_response`。T2 继续沿用同一 receipt validator 和状态转换。

---

## 3.4 Worker 与 TurnReceipt

文件：`v23/worker.py:1-196`

### 3.4.1 WorkerRequest

目标字段：

```text
run_id: UUID
turn_id: UUID
base_revision: int
input_kind: initial | parent_instruction | host_continue | parent_response
input_digest: canonical SHA-256 hex
instruction: string | null
response: JSON value | null
continuation: bool
```

WorkerRequest 是一次性输入 DTO，不写数据库，不持有 Control 引用，不包含下一轮策略。

### 3.4.2 TurnReceipt

目标字段：

```text
schema_version: 1
turn_id: UUID
run_id: UUID
base_revision: bigint
input_kind: enum
input_digest: string
outcome: progress | needs_input | completed | failed
result: bounded JSON value
input_request: object | null
tool_calls: tuple[object, ...]
```

验证要求：

- receipt 必须是 `TurnReceipt` 实例；
- 所有 identity 和 admission 字段必须精确匹配；
- outcome 必须属于闭集；
- `needs_input` 必须有 object input_request；
- 其他 outcome 的 input_request 必须为 null；
- interaction ID 必须是规范 UUID；
- result 必须是finite JSON且canonical UTF-8字节数不超过 `MAX_RESULT_BYTES=65536`；
- tool_calls 必须是 tuple，数量和字节上限均满足。
- schema_version/base_revision用真正int检查，拒绝bool、字符串和浮点强转；TurnReceipt UUID身份必须等于WorkerRequest，本轮input_kind/digest也必须精确相等。
- input_request须为object或NULL，needs_input时interaction_id为规范UUID，options为finite JSON array；支持的response_schema只声明type及required，不偷偷承诺完整JSON Schema实现。不支持的schema声明在receipt校验中拒绝，respond拒绝不匹配的值。
- Input_request不留无界prompt/options：沿用MAX_RESULT_BYTES=65536约束它的canonical JSON大小；工具4096/32768、result65536以及有限DTO字段共同给出整份receipt的有限上界。巨型输入指令/工具名不得造成无界错误记录。

### 3.4.3 FakeTool 执行算法

FakeWorker 一次 `run` 的内部流程：

1. 记录一次 WorkerRequest；从 plan 获取本轮工具描述，不调用自身下一轮。
2. 在执行任何 handler 前全量预验证：数量最多 8、工具存在、输入为 finite JSON、所需 envelope 可放入单项上限。9 次、未知工具或无效输入通过 WorkerExecutionError 中止，handler 次数为零。
3. 顺序调用各 handler 一次，记录 `{call_id, name, input, output, error}`；call_id 为本轮有界序号。正常业务失败保留为 output 数据，不等同 Python 异常。
4. 每项使用 UTF-8 canonical JSON（sort_keys、紧凑 separators、ensure_ascii=false、allow_nan=false）计量单项；完整数组计量总量。handler raise/不可序列化/超限时停止后续 handler，不返回 completed。
5. WorkerExecutionError 的 tool_calls保留已校验的前序记录，当前失败项替换为≤512 bytes的固定错误记录（序号、受限工具名、输入摘要/字节数、固定code，不含超限raw output/traceback/凭据）。最多7个前序项，每项4096，使替代失败标记能在32768总限内；再次序列化核对。9-call预验证失败不伪造未执行的tool_calls，用failed result说明计划非法；已执行工具的记录不得静默丢失。
6. Control 在事务外捕获该异常，用同一 WorkerRequest 的 turn_id/run_id/base_revision/input_kind/input_digest 合成 `failed` DTO；工具记录与 failed result 在一次 T2 整体提交。无异常才生成 plan 的最终 result 并返回唯一 TurnReceipt。

handler 正常返回的有界 `{ok:false,...}` 是业务失败数据，仍可随本轮合法 receipt 写入；handler raise、不可序列化、输出超限、未知工具或其它运行时异常不得被吞成 completed。FakeWorker 必须让这些异常以 `WorkerExecutionError` 离开 Worker，Control 在事务外捕获后于新的 T2 合成 failed receipt，落 `stopped/worker_failed`。FakeTool 只用于 gate，未来真实 provider 不在本计划范围内。

---

### 3.4.4 独立 peer review 后的 storage-safe 边界补充

最终 Worker 与 Control 的 canonical JSON 共用 `storage_safe_json`。在既有有限 JSON、UTF-8 byte bounds 和 DTO 不变量之外，decoded NUL 与 surrogate code points（含 object keys）被拒绝；限制 jsonb numeric 范围、depth≤128 与 traversal/serialized bytes。交付前修正过度 hardening：合法 newline/tab/CR 及其它 C0/C1 字符不能因「控制字符」而被拒绝，在非空多行 instruction/parent_instruction 与 arbitrary finite JSON keys/text 中原样保留。storage/traversal 边界显式披露，不做静默 coercion 或新增业务状态。literal backslash `\\x00`/`\\u0000` 文本仍合法，真实 U+0000 不合法。

Control T2 在存储前统一校验；首轮和已有 receipt 的 NUL/surrogate/数值或遍历超限正常返回均以 `invalid_worker_receipt` durable 关闭，保留历史 receipt/turns 并缓存同型错误收据；执行异常 marker 的工具名也先安全替换、bounded，再由 failed DTO durable 提交。证据在单 gate 的 `test_storage_safe_receipts`/`test_receipts_and_tools`，gate37–40；`test_json_text_controls` 经 Control 正向验证 newline/tab/CR/其它合法控制字符的 instruction、parent_instruction、respond、result keys/text/tool fields 持久化与精确 cache replay（gate1/3/18/19/20/24/39）；独立 peer P2 的正向 parent_instruction steer 由 `test_api_vertical_and_authority` 覆盖 gate4/19/24/25。该输入限制与 finding 处置已同步 README/偏差台账。

## 3.5 T1/T2 事务与恢复

文件：`v23/control.py:256-418`（当前基线；实现后仍需逐段复核）

### T1 admission

所有 mutating T1/T2/recovery 事务必须通过按规范数据库身份共享、持有 session-level advisory fence 的同一 runtime connection，并由进程内 mutex 串行；读事务、LISTEN 和 post-commit notify 可使用独立连接。锁序固定为 runtime mutex → owner registry 短临界区 → SQL 行锁；等待 owner、执行 Worker、等待通知必须释放这些锁。runtime connection 失联后不透明重连，旧 owner 只能停止并交由新 runtime recovery。

```text
BEGIN
SELECT v23_runs ... FOR UPDATE
校验 actor、状态、revision、幂等、预算、输入
校验/写 op_cache[request_id] = pending（operation、actor_digest、request_digest、input_digest、admission_revision）
写 active operation/status=running
revision += 1（steer/respond）
COMMIT
```

start 的新行从 revision 1 开始；steer/respond 在当前 revision 上加一。

T1 结束后：

- 连接必须提交或关闭；
- Worker区间本操作不持PostgreSQL事务/锁；不得把其它合法cancel短事务误判为Worker持有事务；
- Worker 不能通过 Control 连接访问数据库。

### Worker interval

```text
receipt = worker.run(worker_request)
```

允许：

- 有限模型模拟；
- 有限 FakeTool 调用；
- Worker 抛异常。

禁止：

- 数据库写入；
- Control.execute；
- 创建 Run；
- 自行调用下一轮 Worker；
- 依据自然语言结果决定 scheduler 行为。

### T2 finalizer

```text
BEGIN
SELECT v23_runs ... FOR UPDATE
授权后检查 op_cache[request_id]；done/recovered 直接重放
仅 pending 才确认 active_operation_id 与原 runtime 世代 owner 相符
若 cancel_requested:
    丢弃 receipt，stopped/late_result_after_cancel
否则:
    验证 TurnReceipt
    合法则写 receipt/status/turns_used
    非法则 stopped/invalid_worker_receipt
清除 active 字段
revision += 1
将原 operation 的 pending 原子替换为 done（含最终 response/error_code）
COMMIT
NOTIFY(run_id, revision)
```

优先级：

1. 授权后done/recovered优先重放；只有pending才检查active/原owner，行不存在或不匹配不得覆写；
   接受合法failed receipt也增加turns_used一次；invalid/late/recovery不增加，并保留上一份已接受latest_receipt（首轮为NULL），不能把“非法回执不写”误实现为删除历史合法回执。
2. `cancel_requested=true`：迟到回执优先落成 `late_result_after_cancel`，即使 receipt 本身非法；
3. Worker 异常：生成失败 receipt，落成 `worker_failed`；
4. Worker 返回非 DTO或 validator 失败：`invalid_worker_receipt`；
5. 合法回执按 outcome 转换。

### T2 重试与 COMMIT 不确定性

只有原 runtime generation 的 live owner 持有同一份 TurnReceipt 时可以重试 T2；不得再次调用 Worker/工具。先结束残留事务，再按 runtime mutex → owner registry → SQL 行锁顺序进入短事务；对外授权必须在 cache 之前。

1. done/recovered 命中时校验摘要并按 error_code 重放收据；不再检查 active、expected_revision或写 revision。
2. pending 命中时必须同时匹配 operation/actor/request/input 摘要、active_operation_id、active_base_revision和原 owner generation。健康 fence 下确定未提交的 serialization/deadlock 可以用同一 receipt 重做 T2。
3. 连接健康且 T2 commit 已成功、只是测试/应用响应丢失：查 done 返回，不得误抛 active_operation_conflict。post-commit notify 失败也不能重新 mutation。
4. fenced session 实际死亡：该 runtime 永久 control_runtime_lost，不能透明重连/拿新 generation 提交旧 receipt。独立读连接可观察 done；若仍 pending，则新 runtime 取得 fence后 recovery 为 recovered。原请求之后经 Control.execute 精确重试只读这些收据。
5. pending 与 active 不匹配而且无 done/recovered 是违反内部不变量，返回 active_operation_conflict，零写、不调用 Worker；不能用异常回执覆盖其它 operation。
6. 确定 T1 rollback/新行不存在才允许同 ID 重新 admission。T1 commit 未确认、Worker 未执行且观察为 pending 时，原 Control 不能“补执行”：在健康 fence 内以同一恢复规则关闭，或连接死亡后交新 runtime。admission 已确认、仅调用方响应丢失时，live owner 保持运行，重试只能 join。

恢复与正常 T2 都按单行 FOR UPDATE 串行。恢复不清空其它已完成 cache。取消优先于回执错误：cancel 先提交后，failed/非法/正常的迟到结果都丢弃且 turns_used 不增加。

## 3.6 `_owners` 生命周期与 owner 恢复

当前 `_Owner` 在 `v23/control.py:52-58`，模块 registry 在 `:62-63`。目标 owner/runtime 仍为内存资源，不是第二 durable truth。

```text
runtime_key = db_identity(local_cluster_endpoint, database)
owner_key = (db_identity, run_id, request_id)
owner = request_digest + WorkerRequest + runtime_generation + done + response/error
```

advisory fence key固定为二元整数 `(23, 23001)`，在目标数据库中使用，和start的每run事务级hash锁分开；每runtime仅获取一次，不在每op重复获取session锁。runtime保存creator PID；fork后不得复用继承的libpq session/registry，gate重启和fence竞争一律使用spawn/subprocess独立解释器及Unix PostgreSQL连接。

启动流程：规范数据库身份/控制角色配置 → 连接并一次pg_try_advisory_lock → false则control_runtime_busy并关闭候选connection → true则持同一session恢复无主pending → 事务结束/IDLE → 发布runtime共享。每个写事务显式BEGIN/COMMIT或ROLLBACK，不能让连接上下文包装LISTEN/Worker或误以为autocommit保证with conn不启动事务。runtime有close/context manager：停新admission，锁外有限等待owner；deadline后fail-closed并关闭fence session，不迁移receipt、不杀外部请求、不重放。正常完成先使owner事件收敛再release；强制session close留下pending供下一runtime恢复。启动/关闭是资源生命周期而非第七业务op；gate finally必须释放runtime/子进程后才能DROP库。

owner 生命周期：

1. runtime mutex保护 T1、内存 owner 预登记和提交确认。预登记本身不调用Worker；T1 rollback则移除；提交确认后发布live owner，释放所有锁。
2. 调用一次Worker。fenced connection在本操作的Worker区间无打开事务；cancel可能短暂复用该连接开自己的事务，不能锁住Worker或因await owner阻塞cancel。
3. 原 generation owner执行T2，提交done与response/error_code。若session失联，不迁移receipt，仅停止旧generation等待新runtime恢复。
4. 在锁内发布done/event并移除live owner；任何join都在DB事务/registry锁之外，已完成cache仍durable保留。

同一进程多个Control复用runtime，不重复恢复；健康runtime在锁下发现确定缺失owner的pending才可局部recovery。不得只清空registry就让第二实例误关活调用。子进程重启测试必须有真边界。

recovery 的唯一结果是 stopped/cancelled、cancel_requested=true、revision+1、active三元组NULL、turns_used/latest_receipt保持不变、pending→recovered。recovered response固定operation=原op、outcome=recovered_orphan、error_code=owner_lost、snapshot=关闭快照。它是失败关闭收据而非伪造成功；后续授权的精确重试返回相同response，零写、零Worker。

## 3.7 `decide` 纯函数

文件：`v23/disposition.py:1-100`

保持当前返回的 mapping 形状，不新增 Disposition 类，减少调用方变化：

```text
{
  schema_version: 1,
  run_id: canonical uuid,
  observed_revision: bigint,
  decision: run_now | wait | stop
}
```

签名保持：

```text
decide(snapshot: Mapping[str, Any], execution_accepted: bool) -> dict[str, Any]
```

### 校验顺序

必须 fail closed：

1. snapshot 是 Mapping；
2. execution_accepted 是严格 bool；
3. schema_version 为 1；
4. run_id 是 canonical UUID；
5. revision 非负；
6. turn_budget 为正整数；
7. turns_used 在 `[0, turn_budget]`；
8. status 属于五值；
9. cancel_requested 是 bool；
10. running 必须有 active operation；
11. 非 running 不得有 active operation；
12. active base revision、input digest 结构合法；
13. receipt 若存在则 run_id、base_revision、outcome 合法；
14. receipt base revision 小于当前 revision；
15. receipt outcome 与 status 一致；
16. waiting_input 必须有 input_request；
17. stopped 的 close_reason 必须属于闭集；
18. 非 stopped 不得有 close_reason；
19. `waiting_input`、`completed` 和 `turns_used>0` 必须有与状态一致的 receipt；`stopped` 且 `turns_used=0` 在 `cancelled`、`invalid_worker_receipt`、`late_result_after_cancel` 下允许 `latest_receipt=NULL`；`worker_failed` 必须有 failed receipt；
20. 不接受 failed receipt 与非 `stopped/worker_failed` 的组合。

### 固定优先级

```text
invalid input
  > completed/stopped
  > running
  > cancel_requested
  > waiting_input
  > failed receipt
  > budget exhausted
  > execution not accepted
  > ready continuation
```

对应结果：

| 条件 | decision |
|---|---|
| completed/stopped | stop |
| running | wait |
| cancel_requested 且不在 running | stop |
| waiting_input | wait |
| failed receipt | stop |
| turns_used >= budget | stop |
| execution_accepted is False | wait |
| ready 且可续跑 | run_now |

纯函数不得读取数据库、睡眠、调用 Worker、发通知、修改 snapshot 或执行 Control。

---

## 3.8 Host driver 与 stop 语义

文件：`v23/host.py:1-62`

### 3.8.1 单 Run 唯一 driver

同一进程内所有 Host 实例共享 `(db_identity, run_id)` 级 driver registry、锁和本地 wake event；不能只依赖当前 `Host` 实例的 `_active`。`drive` 与 `drive_async` 共用该 registry；外部 `stop`/`respond` 不占 driver 名额。跨进程唯一性仍由 Control 的 revision/fence 边界兜底，不在 Host 层新增 durable scheduler。

`drive_async` 继续使用 `asyncio.to_thread`，但 registry 的检查、登记、清理必须在线程安全锁内完成。第二个同一 `run_id` driver 必须抛 `HostBusyError`，不触发 Control、Worker 或数据库写入。

### 3.8.2 正常驱动与本地停车

保留同步 drive 与 asyncio.to_thread 封装，不另造异步数据库框架或后台scheduler。顶层start完成一次Worker后才进入驱动；child由ParentActor显式start，Host可对已经存在的child通过poll接续drive，不能用HostActor重做child start。两种启动形态共用driver registry，接续不是第七Control op。

- run_now：携带观察revision与该轮稳定request_id，通过execute(steer, continuation=true)执行一次。成功的一轮结束后才生成下一轮ID。
- running：调用execute(wait,since_revision,timeout_seconds)等待原operation变化；cancel_requested也不再次cancel。
- waiting_input或执行未接纳：先clear本地Event，再execute(poll)，重读execution_accepted并decide；若仍wait则Event.wait(idle_interval)，醒后poll/redecide。idle_interval取0.05秒默认，必须严格正、finite且≤1秒；timeout_seconds与它不同，public wait仍允许0。
- completed/stopped：直接结束并释放driver名额，不能cancel completed。
- 未关闭stop：一次语义cancel后poll/redecide；仍running则wait，不生成第二次cancel写入。

Host Event不是状态：clear前变化被随后的poll发现，poll后的signal保留；未signal的其它Control调用被有限timeout发现。停车不持runtime mutex/DB连接/driver registry锁，不读取SQL、不访问Worker。

Host.stop、转发ParentActor respond/steer和execution_accepted setter在finally signal该Run共享Event（即使调用方异常而提交可能成功）；重新判断总以Control快照为准。Host转发只保留原actor及明确请求，不读取receipt自动编排child、不冒充parent。

### 3.8.3 未关闭 stop 的处理

如果 `decide` 返回 `stop` 而 snapshot 仍为 `ready` 或 `waiting_input`：

1. Host 使用观察到的 revision 调用一次 cancel；
2. 不直接结束 driver；
3. 必须得到 durable `stopped/cancelled` snapshot；
4. 再次读取并确认 `decide` 为 stop；
5. 才能返回。

如果 snapshot 已为 `completed`，Host 直接返回，不调用 cancel，不把 completed 改成 stopped。

### 3.8.4 外部停止

Host.stop(run_id, request_id) 只通过execute(poll/cancel/wait)操作：先poll当前快照；未关闭且尚无cancel_requested时，以观察revision执行一次cancel；revision_conflict则poll后用相同cancel ID重试。completed/stopped零写返回；running+cancel_requested转wait直到已提交关闭，不再cancel。stop的请求/外部停止意图仅在内存中，在finally signal本地Event；其输出不来自decide，也不只停止协程。

若重放cancel cache得到的是历史running快照，必须poll而不是返回历史状态；原op_cache收据不可改写。若T2先完成，外部stop以新的已读revision处理ready/completed，不能用过期revision无条件写。

### 3.8.5 request_id、版本冲突与错误重放

- 每个尚未完成的语义请求保存完整请求及一个request_id；不同operation/parent指令/interaction/response改变是新请求，不能复用旧ID。每个成功Worker回合之后的下一次continuation也是新ID。
- 传输/调用方确认丢失时先以同ID精确重试以join原owner或重放done/recovered；即使poll看到running或waiting，也不能改ID再启动一轮。得到收据之后必须poll确认当前快照再decide。
- 明确revision_conflict且尚未admit：poll/redecide。若ready/run_now仍符合该续跑，复用未消费ID、只更新expected_revision；若状态改变为wait/closed，则放弃该未admit续跑。已被cache记录的ID永远只重放，不能因最新revision再调Worker。
- respond确认丢失先同ID重放；明确interaction_conflict/not_waiting_input则拒绝原回答，不生成新interaction或由Host猜答案。respond的budget_exhausted是零写拒绝，不绕过预算。
- done.error_code为worker_failed或invalid_worker_receipt时，首次与cache重放分别抛WorkerError/WorkerContractError，均附同一response与code；错误文案不保存traceback/凭据。recovered.error_code=owner_lost返回recovered response，不随机抛另一种关闭异常。
- Host drive捕获durable WorkerError/ContractError后poll已关闭Run并通过decide结束（如要向上抛也须先释放registry）；不repair/replan/retry Worker。纯非法snapshot ValueError传播为硬失败，不降级wait。

## 3.9 Parent-child 数据流

### Parent start

```text
HostActor
  → Control.execute(start, parent)
  → Worker(parent, input_kind=initial)
  → parent progress receipt
```

Host 不从 receipt/result 生成 child。

### Child start

```text
ParentActor(parent_id)
  → Control.execute(start, child, parent_run_id=parent_id)
  → Worker(child, initial)
  → child snapshot
```

Control 验证：

- parent 存在；
- actor.parent_run_id 等于请求 parent_run_id；
- parent 不是 completed/stopped。

### Child continuation

Host 读取 child snapshot：

```text
decide(child, True) == run_now
  → Control.execute(steer, continuation=true)
  → Worker(child, host_continue)
```

### Child needs_input

```text
Worker → needs_input receipt
Control → waiting_input + input_request
decide → wait
```

Host 不得用 steer 绕过 input request。

### Parent respond

```text
ParentActor(parent_id)
  → Control.execute(respond, child, interaction_id, response)
  → Worker(child, parent_response)
  → next snapshot
```

interaction ID 必须精确匹配；错误 ID 零写、不调用 Worker。

---

## 3.10 README、setup 与权限

### README

文件：`v23/README.md:1-17`

必须同步记录：

- 三角色职责及禁止事项；
- 六个 op；
- 缺省 op 为 wait；
- 三种 disposition；
- 单表边界；
- T1/Worker/T2 事务边界；
- cancel/late receipt；
- owner recovery；
- wait 的 LISTEN/read 语义；
- Fake-only gate 命令。

### setup_db

文件：`v23/setup_db.py:1-53`

保持：

- 只重建 `agent_v23_minimal_loop`；
- 只加载 `v23.sql` 一次；
- 只接受本地 Unix-domain DSN；
- 不加载 v13/v15 SQL；
- 不调用真实 provider；
- 不创建 events/effects/sessions/steps/history 表。

应补充运行时权限 gate：

- `v23_control` 可以按设计 SELECT/INSERT/指定 UPDATE；
- `v23_worker` 不能连接 gate DB；
- mutating Control 连接是持 fence 的 `v23_control` runtime connection，不能由默认 superuser 或第二业务连接替代；
- Worker Python 对象不使用数据库连接。

---

## 4. File-by-file impact

### `v23/v23.sql`

**当前基线：** `v23/v23.sql:1-50`

**修改内容：**

- 保留唯一 `v23_runs`；
- 保留五状态、四 close reason、revision、budget、turns、active 三元组、cancel、op_cache；
- 明确 SQL CHECK 只覆盖可表达的不变量；
- 补充必要 JSON object/receipt 基础结构检查，但不把完整 outcome 状态机复制进 SQL；
- 在 `op_cache` 条目中支持 `pending/done/recovered` 三态的最小结构，并保证 pending 不出现在 RunSnapshot；
- 使 `v23_control` 成为行为测试实际使用的 LOGIN 角色：撤销数据库 PUBLIC CONNECT，只授予 `v23_control` CONNECT；`v23_worker` 保持 NOLOGIN 且显式撤销 CONNECT；
- 保留 parent 自引用和索引；
- 保留 Control/Worker 角色与权限；
- 撤销数据库 CONNECT from PUBLIC，仅授予 v23_control；Worker NOLOGIN 且无 CONNECT/表 CRUD；
- v23_control 的 UPDATE 列授权不含 run_id、parent_run_id、turn_budget；Control 行为 gate 不能使用 superuser。
- 不增加通知表、操作表、receipt 表或历史表。

**依赖：**

- 必须先确定 `Control._write` 的状态字段；
- 必须与 Python validator 的字段名完全一致。

**Size：** M

---

### `v23/setup_db.py`

**当前基线：** `v23/setup_db.py:1-53`

**修改内容：**

- 保持 DROP/CREATE 独立测试库；
- 保持唯一 `v23.sql` loader；
- 保持 Unix socket 校验；
- 确认 Control 行为连接显式使用 `v23_control`，而不是默认 superuser；
- 增加 admin/SET ROLE 探针，验证 PUBLIC 无 CONNECT、`v23_worker` 无法登录/连接/CRUD，且 `v23_control` 能完成真实六 op；
- 不引入旧版本 loader。

**依赖：**

- `v23.sql` 权限设计先落定。

**Size：** S

---

### `v23/worker.py`

**当前基线：** `v23/worker.py:1-196`，尤其 `FakeWorker.run` 在 `v23/worker.py:127-179`

**修改内容：**

- 固化 Worker 只返回 `TurnReceipt` 的合同；
- 不接受 Control 的 mapping 转换；
- 强化 DTO validator 的类型、identity、outcome、input_request 和 size 检查；
- 设计并执行 FakeTool plan；
- 将实际 handler output/error 放入同一 `tool_calls` tuple；
- 对 handler 正常返回的业务失败记录 bounded structured failure；对 handler raise、不可序列化、超限、未知工具或运行时异常返回 `WorkerExecutionError`，由 Control 合成 failed receipt；
- 维持最多 8 个工具调用、单项/总量/result 上限；
- 保证 Worker 不创建连接、不调用 Control、不自续跑。

**依赖：**

- Control 的 `WorkerRequest` 和 T2 failure 优先级；
- gate 的 FakeTool 场景。

**Size：** M

---

### `v23/control.py`

**当前基线：** `v23/control.py:1-494`；`_mutate` 为 `:256-383`，`_finalize` 为 `:385-418`，`_cancel` 为 `:420-455`，`_wait` 为 `:457-494`。当前 `_finalize` 先检查 active、未先重放 done cache；COMMIT 成功但 ack 丢失后现行重试会误抛 active_operation_conflict，必须修正。

**修改内容：**

- 保持唯一 `execute` 分派；
- 完善 request shape、default wait、额外字段拒绝；
- 分离 request digest 与 input digest；
- 完善 start/steer/respond 的 T1 → Worker → T2；
- 实现 cancel 的 cache/zero-write/expected_revision 合同；
- 保证同 request 的在途 retry 绑定原 owner；
- owner 缺失时按 pending→recovered 关闭 orphan，不重放 Worker；
- T1 在同一事务写 pending，T2 原子替换 done；T2 commit ack 丢失先读 done/recovered，不能因 active 清空而报 active_operation_conflict；
- T2 只允许原 owner 使用同一 receipt 重试；
- 处理 T2 commit 已成功但客户端未确认的 cache replay；
- 明确 pending/done/recovered cache 数据形状、error_code 稳定重放与历史快照不可作当前真相；
- 按规范 db_identity 共享 runtime，所有 mutation 使用持 fence session；Control construction/close资源生命周期与业务 execute 六op分离；
- 严格 DTO-only；
- 完善 Worker exception、invalid receipt、late receipt 的关闭原因和 response；
- 保持 T2 与 cancel 对同一行 `FOR UPDATE`；
- 保持通知只在 commit 后发出；
- 完成 wait 的 read/LISTEN/read、超时重读和 listener 事务隔离；
- 以backend PID与事务probe证明本操作Worker区间无事务；wait/listener/notify等待均IDLE或连接已关闭；
- fenced runtime 失联后 fail-closed，旧 owner 不得透明重建 fence 或继续提交 T2；
- 不添加第二张表、不添加 active operation kind、不添加 scheduler。
- Host 停车只使用进程级 `(db_identity, run_id)` registry 里的 Event/timer；不新增 Control.park_until_change 或其它公共入口。
- fenced runtime 按规范数据库身份共享；持 fence 的 session connection 同时承担 mutation/recovery，失联后永久 fail-closed。

**依赖：**

- 依赖 SQL 字段和权限；
- 依赖 Worker DTO；
- 依赖 disposition snapshot 字段；
- 是本计划最大工作项。

**Size：** XL

---

### `v23/disposition.py`

**当前基线：** `v23/disposition.py:1-100`

**修改内容：**

- 保持 `decide(snapshot, execution_accepted)` 签名和 mapping 返回形状；
- 补齐 active base/input digest、receipt identity、status/outcome 等校验；
- 修正非法组合的 fail-closed 行为；
- 保持 `running` 在 `cancel_requested` 之前；
- 不新增第四种 disposition；
- 不访问 Control、数据库或时间。

**依赖：**

- 依赖最终 RunSnapshot 字段；
- 依赖 Control 状态转换。

**Size：** M

### `v23/host.py`

**当前基线：** `v23/host.py:1-62`

**修改内容：**

- 保持 Host 不直接持有 Worker、不直接写 DB；
- 为进程级 `(db_identity, run_id)` driver registry、wake event 和 `_active` 增加线程安全；
- 保持一个 Run 一个 driver，跨 Host 实例也拒绝重复 driver；
- 增加直接 `stop/cancel` 入口；
- 外部停止不经 decide；
- 未关闭 stop 必须通过一次 cancel 落成 stopped；
- running + cancel_requested 通过 wait 等待，不重复 cancel；
- completed 永远不转 stopped；
- 保持 `drive_async` 只包装同步 driver，不形成第二调度器。

**依赖：**

- 依赖 Control cancel/wait 合同；
- 依赖 disposition 优先级。

**Size：** M

### `v23/test_minimal_loop.py`

**当前基线：** `v23/test_minimal_loop.py:1-232`

**修改内容：**

- 保持独立脚本、Fake-only、退出码 gate；
- 删除仅用于静态扫描的主导性验证方式；
- 保留单表、单 SQL、无旧版本 import 等边界检查作为辅助；
- 增加真实运行时：
  - Worker 外部事务；
  - T1/T2 transaction status；
  - NOTIFY/LISTEN race；
  - 丢失/合并通知；
  - 超时重读；
  - 两消费者 revision 竞争；
  - owner-only T2 retry；
  - orphan recovery；
  - cancel/T2 两种提交顺序；
  - cancel zero-write；
  - FakeTool handler；
  - Host 唯一 driver；
  - parent-child authority；
  - needs_input/respond；
  - invalid receipt；
  - no network/no socket；
  - worker role 权限；
  - 单表/单 SQL。

**依赖：**

- 所有运行时代码完成后才能形成最终 gate；
- 测试不得直接用 SQL 函数替代 Control.execute。

**Size：** XL

### `v23/README.md`

**当前基线：** `v23/README.md:1-17`

**修改内容：**

- 同步最终角色、状态机、六 op、三 disposition；
- 记录取消、迟到回执、owner recovery、wait；
- 明确 Fake-only gate 和完成门；
- 不写迁移说明，不宣称当前草案已完成。

**依赖：**

- 最终行为合同先冻结。

**Size：** S

### 不修改的文件

以下文件只作为参考，不应被实现改动：

- `AGENTS.md:1-78`
- `v12/queue_worker.py:105-149`
- `v13/loop_driver/controller.py:1-108`
- `v13/fair_driver/driver.py:1-44`
- `v13/control/test_control.py:603-644`
- `v8/closeout/v8_closeout.sql:116-142`
- v13/v15 的任何生产代码、SQL、loader 或测试

## 5. Error handling and edge cases

### 5.1 请求错误

以下错误必须零写、零 Worker：

- 未知 op；
- 缺少必需字段；
- 多余字段；
- 非 canonical UUID；
- 非有限 timeout；
- timeout 超出 `[0, 3600]`；
- 非正 turn budget；
- 空 instruction；
- start 携带非 null expected revision；
- steer 两种输入同时出现或都缺失；
- respond 缺 response；
- invalid interaction ID；
- 非法 actor。

### 5.2 权限错误

- 不存在 Run 与无权访问统一 `not_found_or_unauthorized`；
- ParentActor 只能操作 `parent_run_id` 等于自身的 child；
- 非 parent 不得提供 parent instruction；
- 非 parent 不得 respond child；
- Host 只能创建顶层 Run；
- Parent Run completed/stopped 后不得创建 child。

### 5.3 Worker 错误

| 情况 | durable 结果 | 调用方结果 |
|---|---|---|
| Worker 抛异常 | 写 failed receipt，`stopped/worker_failed`，turns+1 | T2 提交后抛 `WorkerError` |
| Worker 返回非 TurnReceipt | 不写 latest receipt，`stopped/invalid_worker_receipt` | T2 提交后抛 `WorkerContractError` |
| receipt identity 不匹配 | 同上 | 同上 |
| receipt 超限 | 同上 | 同上 |
| cancel 先提交后 Worker 返回 | 丢弃 receipt，`stopped/late_result_after_cancel`，turns 不变 | 返回 late-result response |
| T2确定rollback且fence健康 | 原owner用同receipt重试T2 | 不再调用Worker |
| T2提交成功但ack丢失 | done cache已原子持久化，零写重放 | 返回原response/同型错误，不再调用Worker |
| fenced session死亡 | 旧generation fail-closed；新runtime恢复pending或读done | 旧owner不得重新T2，精确请求只读done/recovered |
| owner 丢失 | pending→recovered，`stopped/cancelled`，revision+1、turns/receipt不变，写唯一 recovered response，不重放 | exact retry 返回 recovered，不调用 Worker |

### 5.4 边界状态

- `ready` 且 `turns_used == turn_budget`：decide 返回 stop，Host 通过 cancel 关闭；`running` 先返回 wait；`waiting_input` 也先返回 wait，不能偷偷重排设计优先级；respond 超预算零写拒绝，等待输入的关闭依赖显式 external cancel。
- `waiting_input`：只允许 respond 或 cancel。
- `completed`：任何 steer/respond 拒绝；cancel 不改变完成状态。
- `stopped`：任何 Worker op 拒绝；合法 stopped-null 快照的 decide 返回 stop。
- `since_revision=NULL`：wait 立即返回，不监听。
- timeout 为 0：执行一次读取，必要时返回 timed_out；仍需返回最新快照。
- 通知丢失：Host 本地停车超时后 poll；Control wait 超时也必须重读，均收敛到最新状态。
- 通知重复或合并：payload 不参与状态构造，重新读取即可。
- 空工具列表：合法，receipt.tool_calls 为空 tuple。
- handler 正常返回的有界业务失败是 tool_calls 数据；handler raise、不可序列化、超限或运行时异常必须生成 failed receipt，落 `stopped/worker_failed`，不允许吞成 completed。
- `respond` 在 admission 时检查 `turns_used < turn_budget`；预算耗尽零写、零 Worker。`decide` 仍按设计优先级让 waiting_input 先于 budget exhaustion 返回 wait，外部 cancel 是关闭出口。

## 6. Risks and migration

### 6.1 数据迁移

不提供旧 v23 草案数据迁移。

理由：

- 当前 v23 尚未验收；
- 设计稿规定从独立空目录/独立测试库开始；
- `setup_db.py` 会删除并重建自己的 gate 数据库；
- v13/v15 数据库和表不受影响。

正式实现不得在已有 v13/v15 schema 上执行，也不得增加兼容适配器。

### 6.2 回滚风险

T1 已提交而 Worker 尚未返回时，进程可能崩溃。恢复策略不是重放，而是关闭无主 Run。这样会牺牲未完成本轮的业务进度，但避免重复模型/工具副作用。

T2 commit 成功而调用方连接丢失时，后续相同 request ID 必须从 `op_cache` 返回，不得再次调用 Worker。

cancel 与 T2 的最终状态取决于同一行锁的先后提交：

- T2 先提交：receipt 被接受；cancel 之后按新状态处理，可能关闭 ready 或保留 completed。
- cancel 先提交：T2 看到 `cancel_requested`，丢弃迟到 receipt。
- expected_revision 过期时，调用方得到 revision conflict，不允许绕过 CAS。

### 6.3 本地 owner registry 的边界

`_owners` 只表示当前 Python 进程中的 live owner，不能作为 durable truth。没有本地 owner 不足以关闭另一个 active 进程的 Run：先用规范数据库身份取得 session fence，再 recovery。fenced connection 同时承担所有 mutation，失联的旧 runtime 不能透明重连或迁移 receipt；旧 Worker 可能仍在运行，但没有 durable 写权。新 runtime 关闭无主 pending 为 recovered，不重放外部模型/工具。

## 7. Implementation order

以下是实现顺序，不代表可以提前宣称某个局部阶段完成。唯一完成门仍是最终 gate；所有步骤完成后必须整体运行 `uv run python v23/test_minimal_loop.py`。

### Step 1 — 冻结合同与状态字段

**Goal**

把 cancel、owner recovery、DTO-only、FakeTool、SQL/Python validator、wait race、Host stop 的裁定落实为实现约束。

**Done when**

- 所有六个 op 的请求/响应、状态转换、错误码、revision 规则明确；
- 没有新增 disposition、op、表或 active operation kind；
- request digest 与 input digest的用途和pending/done/recovered字段、错误重放已按§2.5/§3裁定；
- cancel cache与zero-write边界固定，未cache的no-op request不承诺永久记忆；
- local Event parking替代第二Control入口，session fence/mutation同连接、丢失后failclosed且旧generation不迁移。

**Key files**

- `docs/designs/v23-minimal-agent-loop-2026-10-09.md:1-1397`
- 本文 §2–§3 的裁决与合同
- `v23/README.md:1-17`

**Dependencies**

- 无。

**Size**

S

### Step 2 — 收敛单表 schema、角色和 setup

**Goal**

建立只承载 Run 真相的 SQL 层，并保证 gate 数据库与旧版本隔离。

**Done when**

- 只存在 `v23_runs`；
- 所有 SQL CHECK 与权限符合本计划分工；
- 实際Control DSN以v23_control可执行需要的SELECT/INSERT/限定UPDATE；
- PUBLIC无CONNECT；Worker NOLOGIN/不可CONNECT且SET ROLE后无CRUD；
- identity/parent/budget不可由Control UPDATE；
- setup 只加载一个 `v23.sql`；
- `uv run python v23/setup_db.py` 可重复执行。

**Key files**

- `v23/v23.sql:1-50`
- `v23/setup_db.py:1-53`

**Dependencies**

- Step 1。

**Size**

M

### Step 3 — 固化 Worker DTO 和实际 FakeTool

**Goal**

让 Worker 成为严格的一次调用一次 DTO 返回边界。

**Done when**

- `Worker.run` 只接受/返回定义好的 DTO；
- mapping 不会被 Control 自动转换；
- FakeTool handler 实际执行；
- 成功结果和结构化失败都进入同一 `TurnReceipt.tool_calls`；
- 工具数量和字节上限被运行时执行，而不只是常量存在；
- Worker 无数据库连接、不自续跑。

**Key files**

- `v23/worker.py:1-196`

**Dependencies**

- Step 1；
- Step 2 的 JSON/字段边界。

**Size**

M

### Step 4 — 实现 Control 六 op 的完整 T1/Worker/T2 链

**Goal**

完成唯一 lifecycle entry，覆盖幂等、并发、取消、迟到和恢复。

**Done when**

- `start/poll/wait/cancel/steer/respond` 全部从 `Control.execute` 进入；
- start/steer/respond 都是 T1 commit → 一次 Worker → T2 commit；
- T2 不在 Worker 期间持有事务；
- cancel 的 cache、zero-write、expected revision 行为固定；
- T2 与 cancel 使用同一行锁；
- owner retry 不重复 Worker；
- owner缺失和真子进程重启pending→recovered，revision+1一次、turns/receipt不变；
- healthy/fence-dead、T1/T2 ack丢失的路径全部按§3.5收敛，旧generation不能写；
- invalid receipt、worker exception、late receipt 均安全关闭；
- 通知只在 commit 后发出。

**Key files**

- `v23/control.py:1-494`

**Dependencies**

- Step 2、Step 3；
- Step 1 的合同。

**Size**

XL

### Step 5 — 完成纯 `decide`

**Goal**

让 Host 的 scheduler 判断成为严格、无副作用、fail-closed 的纯函数。

**Done when**

- 所有快照组合校验完整；
- 固定优先级与设计稿一致；
- running先于cancel_requested；waiting_input先于budget，exhausted respond admission拒绝；
- stopped/used=0/NULL三种合法关闭组合返回stop；worker_failed缺failed receipt及completed缺receipt抛ValueError；
- 非法输入抛 ValueError；
- 函数不访问 DB、不调用 Worker、不产生通知。

**Key files**

- `v23/disposition.py:1-100`

**Dependencies**

- Step 4 的最终 snapshot 字段。

**Size**

M

### Step 6 — 完成 Host 唯一 driver 和外部 stop

**Goal**

把 `Control snapshot → decide → exactly one Control op` 连接成可证明的单 Run driver。

**Done when**

- 同一 run_id 的第二 driver 被 Host 层拒绝；
- run_now 只触发一个 continuation steer；
- wait 不调 Worker；
- 未关闭 stop 必须经过一次 cancel；
- 外部 stop 直接 cancel，不调用 decide；
- completed 不被改成 stopped；
- running + cancel_requested 只 wait，不重复 cancel；
- sync/async与不同Host实例共享唯一driver保护，异常finally释放；
- Event清除→poll→重新decide→有界停车避免lost wake，3类signal/无signal变化均发现；
- 每个尚未完成语义请求复用request_id，已完成下一轮必新ID；cache重放后poll当前快照。

**Key files**

- `v23/host.py:1-62`

**Dependencies**

- Step 4、Step 5。

**Size**

M

### Step 7 — 构建完整运行时 gate

**Goal**

通过 Control 入口正向证明所有设计稿 §8 适用断言。

**Done when**

- 所有 gate 断言见下节均通过；
- 测试不通过直接 SQL 绕过 Control 证明行为；
- source checks 只作为边界辅助，不作为主要完成证据；
- 没有网络 socket、真实 provider 或旧版本 import；
- gate 退出码为 0。

**Key files**

- `v23/test_minimal_loop.py:1-232`
- 依赖所有 v23 实现文件。

**Dependencies**

- Step 2–6。

**Size**

XL

### Step 8 — 同步 README 并运行唯一完成门

**Goal**

使说明文档与已验证行为一致，并形成最终完成证据。

**Done when**

- README 描述与实际状态机、op、事务和恢复语义一致；
- 执行唯一命令成功；
- 不把未运行的测试写成通过；
- git 状态和测试输出可追溯。

**Key files**

- `v23/README.md:1-17`
- `v23/test_minimal_loop.py:1-232`

**Dependencies**

- Step 7。

**Size**

S

## 8. Work-item execution index

每项Key files的短文件名都相对v23/。W0固定DTO/RunSnapshot合同以打断文件相互引用；W3不等待W4实现，只消费W0字段，W4随后验证W3状态输出。W2/SQL只依赖固定合同，不形成Worker→Control→Worker实现循环。S/M/XL表示相对工作量，不是时间承诺；所有W仍合并为唯一M1。

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W0 | 冻结实现合同 | 六 op、三 disposition、cancel、owner、wait、工具和恢复语义无未决裁定 | design、plan、README | None | S |
| W1 | 单表 schema 和 gate DB | 单表、单 SQL、权限、CHECK 和 reset 均可运行 | `v23.sql`, `setup_db.py` | W0 | M |
| W2 | Worker DTO/FakeTool | DTO-only、实际 handler、同轮 bounded receipt | `worker.py` | W0/W1 | M |
| W3 | Control lifecycle | 六op、pending/done/recovered、fence同session、T1/T2确认丢失、恢复、取消、通知全部闭合 | `control.py` | W1/W2 | XL |
| W4 | Pure disposition | fail-closed 校验和固定三态优先级 | `disposition.py` | W3 | M |
| W5 | Host driver | 跨实例唯一driver、本地停车、稳定ID、stop/cancel、wait与completed语义 | `host.py` | W3/W4 | M |
| W6 | Runtime gate | §9/§9.10 全部 50 标签及适用子场景正向通过 | `test_minimal_loop.py` | W1–W5 | XL |
| W7 | Documentation and final gate | README/覆盖矩阵/偏差台账同步，完整gate退出0后按已授权追加closeout提交推送；原单提交顺序偏差不隐去 | `README.md`, gate, v23 review artifacts | W6 | S |

执行状态（全部由单 gate 及收尾文档支持，不以子工作包绿替代 M1）：

- [x] W0 合同冻结：三角色、六 op、三态、单表与隔离 loader。
- [x] W1 SQL/setup：真实角色/权限、SQL NULL CHECK、只加载 v23.sql。
- [x] W2 Worker：DTO-only、实际 FakeTool、有界执行与 storage-safe JSON。
- [x] W3 Control：fenced T1/Worker/T2、pending/done/recovered、取消/确认丢失/恢复。
- [x] W4 Disposition：完整 fail-closed 快照校验及固定优先级。
- [x] W5 Host：共享唯一 driver/Event、sync/async、稳定ID、停车、外部stop/current poll。
- [x] W6 唯一 runtime gate：全部 50 标签与 382 labeled subcases 实跑退出0。
- [x] W7 技术收尾：README、覆盖矩阵、偏差台账、本计划同步；提交前再跑完整gate。
- [x] M1 功能/技术验收：实际 complete gate 全绿；不是 Oracle 超时批准，不是 real-provider 可用证明。

M1 仓库交付仍须按 §11 执行明确路径 stage → diff/secrets/status 核对 → append-only commit → normal push。提交/推送失败即交付未完成；本 checklist 的技术完成不代替实际交付结果。

## 9. Complete runtime gate

唯一命令：

```bash
uv run python v23/test_minimal_loop.py
```

退出码非 0 即失败。以下 50 条断言必须全部保留并以运行时行为为主；编号连续只是阅读索引，不代表可独立关闭的 stage。

### 9.1 API 与基础边界

1. `v23_unknown_op_rejected`
   - 未知 op 零写；
   - 缺省 op 进入 wait。
2. `v23_start_worker_outside_tx`
   - admission 已提交后 Worker 才开始；
   - Worker 期间数据库连接 idle/closed。
3. `v23_start_receipt_committed`
   - start 返回前 receipt、status、revision 已 durable。
4. `v23_worker_called_once_per_op`
   - 每个被admit的start/steer/respond最多一次Worker；合法首次admission正常路径恰好一次；
   - T1不确定关闭路径可以零次，但从不补执行/重放；Worker不自续跑。
5. `v23_no_socket`
   - 测试和 v23 实现不使用外部网络；
   - 仅允许本地 Unix-domain PostgreSQL。

### 9.2 Vertical loop 与 disposition

6. `v23_vertical_run_steer_stop`
   - start → progress → run_now → steer → completed → stop。
7. `v23_progress_three_dispositions`
   - 同一 progress：
     - accepted → run_now；
     - not accepted → wait；
     - budget exhausted → stop。
8. `v23_budget_stop`
   - 非 waiting_input 的 ready Run 在 turns_used 等于预算时不再 steer；
   - waiting_input 且预算耗尽仍按 §5.3 返回 wait；respond admission 以 `budget_exhausted` 零写拒绝。
9. `v23_completed_is_not_reopened`
   - completed 的 steer/respond 都不调用 Worker；
   - decide 返回 stop。

### 9.3 Wait、通知和事务

10. `v23_wait_is_read_only`
    - wait 不改 revision、turns、status、op_cache。
11. `v23_wait_notification_only_wakes`
    - payload 不被当作状态；
    - 通知后重新查询快照。
12. `v23_wait_timeout_rereads`
    - timeout 返回重新查询的最新快照。
13. `v23_wait_read_listen_race_closed`
    - mutation 发生在首次 read 与 LISTEN 之间时不会丢失；
    - LISTEN 后立即 reread。
14. `v23_wait_notification_lost`
    - 屏蔽 notify 后，timeout/poll 仍收敛到最新 revision。
15. `v23_wait_notification_merged`
    - 多次 revision 合并为一次唤醒时，返回最终快照而不是 payload 状态。
16. `v23_transaction_idle_boundaries`
    - T1确认commit后才进入Worker，Worker本操作不持open transaction/SQL锁/runtime mutex；
    - 没有其它并发操作的barrier点，runtime connection必须IDLE；cancel短事务可独立提交，不被误归为Worker事务；
    - T2 commit后才notify，通知失败不重mutation；
    - wait/listener/Event/owner.join等待期间无idle in transaction，所有退出路径释放资源。

### 9.4 Input/respond 与 parent-child

17. `v23_respond_only_waiting_input`
    - ready/running/completed/stopped 的 respond 均拒绝。
18. `v23_respond_interaction_exact_match`
    - 错 interaction ID 零写、不调用 Worker；
    - 正确 ID 才进入 parent_response Worker。
19. `v23_parent_child_authority`
    - 只有正确 ParentActor 能 start child instruction/respond；
    - 兄弟或无关 parent 被拒绝。
20. `v23_host_continuation_has_no_input`
    - Host continuation 不能带新 instruction；
    - parent steer 缺 instruction 被拒绝。
21. `v23_parent_wait_does_not_schedule`
    - parent wait 只读 child；
    - 不调用 decide、steer、respond 或 Worker。

### 9.5 Revision、竞争和幂等

22. `v23_expected_revision_conflict`
    - stale revision 零写、不调用 Worker。
23. `v23_two_consumers_same_revision`
    - 两个消费者争夺同一 revision 时只有一个 admission 成功；
    - 另一个得到 revision conflict/busy；
    - Worker 只调用一次。
24. `v23_idempotent_mutation`
    - 相同 request ID、相同语义只返回原 response；
    - 不重复 Worker；
    - cache 命中不因新的 expected_revision 再写。
25. `v23_idempotency_conflict`
    - 相同 request ID 搭配不同 operation、actor 或语义字段立即拒绝；
    - 未授权 actor 不能通过 cache 探测 Run；
    - Run 不变。
26. `v23_pending_digest_and_recovery_receipt`
    - T1 durable 写入 pending，request_digest 与 active_input_digest 可分别验证；
    - done/recovered 的 operation/actor/request_digest 不匹配时零写、零 Worker；
    - recovered exact retry 返回同一 `recovered_orphan/owner_lost` response。
27. `v23_commit_ack_loss_no_replay`
    - T2 commit 成功但 ack 丢失时先读 done cache，revision 与 Worker 次数不增加；
    - fenced connection 失联后旧 owner 不能透明重连提交 T2；
    - 确定 rollback 才允许同 ID 重新 admission。
28. `v23_cancel_idempotency_and_zero_write`
    - 首次 running cancel 设置 cancel_requested、增加 revision 并缓存；
    - 相同 request ID 返回 cache；
    - 新 request ID 在 cancel_requested 状态下零写；
    - stale expected revision 仍 conflict。
29. `v23_respond_budget_admission`
    - waiting_input 且 turns_used==turn_budget 时 decide 仍为 wait；
    - respond 返回 budget_exhausted、零写、零 Worker。
30. `v23_t2_owner_only_retry`
    - T2 transient failure 前未提交时，原 owner 用同一 receipt 重试；
    - T2 commit 成功但 ack 丢失时直接返回 done cache；
    - 两种路径 Worker 调用数都保持 1；新请求不能代替 T2 重放。

### 9.6 Cancel、迟到回执和恢复

31. `v23_cancel_running`
    - running cancel 只设置 durable cancel request；
    - 不伪造 receipt。
32. `v23_late_worker_result_discarded`
    - cancel 先提交时，迟到 receipt 不增加 turns_used；
    - 不更新 latest_receipt；
    - 不 reopen。
33. `v23_t2_cancel_lock_order`
    - T2 与 cancel 锁同一行；
    - T2 先提交和 cancel 先提交两种顺序分别收敛；
    - 先提交者获胜。
34. `v23_cancel_ready_and_waiting`
    - ready/waiting_input 可以通过 cancel 关闭；
    - 关闭后 steer/respond 拒绝。
35. `v23_owner_disappearance_no_replay`
    - 健康fenced runtime确认owner消失才关闭其pending；任意新Control构造不得误关live owner；
    - 两进程抢fence失败者零recovery，旧fence断开后旧Worker迟到无T2写入；
    - recovered exact retry不增加revision/turns、不Worker。
36. `v23_process_restart_closes_orphans`
    - 真spawn/subprocess退出后新runtime先取得fence，再恢复全部无主running；
    - 同进程多个Control共享healthy runtime不是“重启”，不得重复recovery；
    - stopped/cancelled、cancel_requested=true、pending→recovered、revision一次，turns/latest不变、不重放。

### 9.7 Receipt、工具和安全关闭

37. `v23_invalid_receipt_closes_safely`
    - 非法 receipt 不写 latest_receipt；
    - Run 进入 stopped/invalid_worker_receipt。
38. `v23_worker_exception_closes_safely`
    - Worker exception 通过失败 receipt durable 关闭；
    - 调用方收到 WorkerError。
39. `v23_fake_tools_bounded`
    - FakeTool handler 实际执行；
    - 成功/失败都写同一 TurnReceipt；
    - 数量、单项、总量和 result 上限全部执行。
40. `v23_tool_failure_does_not_schedule`
    - 正常业务失败是同轮数据，不直接触发下一轮；handler运行异常由Control在事务外捕获并于T2提交failed，Host不得再Worker；
    - 所有已执行的有界工具记录仍在同一receipt。

### 9.8 Host 生命周期

41. `v23_single_run_coroutine`
    - 跨Host实例和sync/async入口同run_id第二driver在Host层拒绝，零DB/Worker副作用；
    - waiting_input/拒绝接纳无hot loop；respond/stop/admission signal及绕过Host的无signal变化均有界发现；
    - 正常失败/异常/外部stop后registry名额清理，后续合法观察不被永久HostBusy阻塞。
42. `v23_host_stop_calls_cancel`
    - 外部 stop 直接调用 cancel；
    - 不调用 decide；
    - 未关闭 Run 不会仅靠结束协程。
43. `v23_completed_not_cancelled`
    - 外部 stop 对 completed 不改变 status/revision；
    - 不变成 stopped。

### 9.9 独立性与 schema 边界

44. `v23_only_one_data_table`
    - public schema 只有 `v23_runs`。
45. `v23_load_is_single_sql`
    - setup 只加载 `v23.sql` 一次。
46. `v23_no_v13_v15_imports`
    - v23 runtime 不 import v13/v15。
47. `v23_no_static_control_map`
    - 不生成静态 CE 映射表冒充运行时。
48. `v23_no_events_effects_history_tables`
    - 不创建 events/effects/sessions/steps/history 等表。
49. `v23_control_worker_permissions`
    - 所有六 op 的行为连接实际使用 v23_control，断言 session_user/current_user；admin 只做 setup/审计/故障注入；
    - PUBLIC 无 CONNECT，worker NOLOGIN、不可 CONNECT，SET ROLE worker 无 SELECT/INSERT/UPDATE/DELETE 权限；
    - Control 不得修改 run_id/parent_run_id/turn_budget，不得创建其它表；
    - mutation/recovery 的 backend PID 与持 fence 的 session 相同，失联后旧 T2 无写入。
50. `v23_no_network`
    - 不调用真实 provider、HTTP client 或外部网络。

静态 source checks 可以保留用于确认单表、单 SQL、旧版本 import 等边界，但不能替代上述运行时证明，尤其不能替代：

- `Control.execute` 正向调用链；
- durable receipt 证明；
- T1/T2 事务边界；
- 行锁竞争；
- wait/LISTEN race；
- owner recovery；
- FakeTool 实际执行；
- cancel/T2 先后提交语义。

### 9.10 gate 的确定性子场景与运行纪律

编号引用下列场景，仍在同一 test_minimal_loop.py/main 中执行，不另拆stage。断言最终同时比对Control返回的快照、execute(poll)读回、admin审计的行/缓存、实际Worker/FakeTool计数；admin观察不替代Control入口的业务执行。

| Gate | 确定性构造与必须区分的子场景 |
|---|---|
| 1 / 10 / 24 / 25 / 28 | 拒绝/只读前后捕获整行（含op_cache）；未授权actor携带别人cached ID仍not_found_or_unauthorized；steer/respond/cancel换expected_revision重放仍同收据；在途异op/actor/input zero-write。 |
| 2 / 4 / 16 | T1确认后BlockingWorker进入Event barrier；记录操作相关backend/事务状态；此时另一Control线程能poll和cancel，证明owner没有持DB/runtime锁。Worker与各handler调用计数独立，BlockingWorker不得super调用重复记count。 |
| 6 / 17–21 | 两轮最小链和完整parent→child progress→steer needs_input→ParentActor respond→progress→steer completed两条独立场景；再用Host.drive接续child证明真实协调边，不能仅手工调用decide冒充Host。顶层Host respond、child Host拒答、兄弟parent拒绝、已关闭parent禁止child start全覆盖。 |
| 8 / 29 | ready budget耗尽→Host cancel；running budget耗尽→wait；waiting_input budget耗尽→wait且respond budget_exhausted，外部cancel唤醒parking。不把新排序写进decide。 |
| 11–15 | 首次read之后/LISTEN之前barrier提交变化；LISTEN之后屏蔽notify再提交变化，必须超时重读新revision（不能用timeout=0且快照不变冒充）；合并多revision一次wake；payload伪造revision/result或来自另一个Run只唤醒、快照必须读DB。 |
| 23 / 30 / 33 | 两个consumer用同revision同时进入barrier；runtime mutex串行admission但Worker区间释放，只有一个Worker；cancel与T2的实际FOR UPDATE均核验。测试先让cancel真实commit再T2；反序让T2真实commit，再poll新revision执行cancel；另测旧revision冲突，不能以stale cancel声称“先提交者”已验证。 |
| 26 / 27 / 30 | 每个子case单独统计pending/done/recovered与revision：commit前serialization/deadlock rollback、commit后健康连接ack-loss、fence session断开。T1分别确定rollback、已确认admission但响应丢失（join）、真正确认未知且未调Worker（recovery）。T2 done优先于active验证。 |
| 35 / 36 | 单进程多Control共享runtime不恢复live owner；子进程抢fence失败control_runtime_busy且零recovery；杀掉持fence子进程后新进程取得锁仅关闭一次pending；断开旧session而旧Python/Worker仍活着，旧T2不得写，新generation恢复，exact retry返回同一recovered。启动失败必须关闭候选连接、不泄漏session锁。 |
| 37 / 38 / 39 / 40 | 首轮和已有receipt两种非法回执/handler异常/late场景；停止不清空既有latest。business failure数据与handler raise相分离。9 calls预验证零handler；实际handler输出生成4096恰界、超单项、含framing的32768恰界/超aggregate；result/input_request各65536界限与finite JSON；失败记录仍有界。 |
| 41 / 42 / 43 | 两个Host实例及drive/drive_async同Run竞争第二个HostBusy零effect；无变化时Event wait计数/Control poll计数与timeout窗口有界而非hot loop；response/stop/admission setter signal和外部直接Control无signal mutation均收敛；cache返回历史cancel_requested后poll得到已关闭快照。 |
| 44–50 | 审计所有非system用户表而非仅静态扫描；DDL加载计数记录唯一v23.sql，不能用字符串count。角色以session_user/current_user实际确认；SET ROLE探针、PUBLIC CONNECT及限定UPDATE均实跑。禁止AF_INET/AF_INET6/HTTP/provider；只允许Unix PostgreSQL，子进程通过stdio/文件协调而非TCP socket。 |

- 所有fixture只在独立agent_v23_minimal_loop数据库中创建自己的Run；setup会DROP/CREATE该库，不并行运行两个整份gate，不触碰v8/v13/v15库。重启子进程不再次setup；复用已建库并经Control初始化恢复。
- gate main为每组异常抛出非零退出码；每条worker线程/子进程异常回传主线程，join timeout也fail。finally关闭read/listener/notifier/runtime连接，释放registry，终止fixture子进程并删除临时文件。
- 注入连接失败/强制关backend时只对测试标记的v23 session；admin probe不获得Worker写权限，不绕过生产入口证明正常op。临时输出不得含DSN密码、凭据、provider配置，不追加tracked scaffolding。
- 网络禁止由运行时network guard加Unix DSN检查共同证明；AST/no-old-import/source检查仅作辅助，不作为上述positive链的主体。gate不调用真实provider、真实工具，也不启动网络下载。

## 10. Final non-goals

本计划不交付：

1. `replan`、`repair`、`terminal`；
2. 第四种 disposition；
3. 第七个 op；
4. 后台 scheduler、cron、常驻 supervisor 或自动 tick；
5. wait 触发 Worker；
6. parent wait 代替 parent respond；
7. Worker 写 Run、自续跑或创建 child；
8. Host 直接写 PostgreSQL；
9. Host 直接调用 Worker；
10. events/effects/sessions/steps/history 表；
11. 全局公平调度；
12. 多 Run supervisor；
13. 真实 provider、真实工具、真实网络；
14. 取消杀死已经发出的模型请求；
15. 取消后的 Worker 重放；
16. 用自然语言 receipt 作为 Control 决策；
17. 把 execution_accepted 持久化成 scheduler 状态；
18. v13/v15 迁移、兼容层或 SQL 函数复用；
19. 静态映射表或 source scan 作为主要验收；
20. 将 parent-child 扩展为 DAG/workflow engine。

最终完成条件只有一个：

```bash
uv run python v23/test_minimal_loop.py
```

命令退出码为 `0`，且上述运行时 gate 全部通过，才可以把 v23 标记为完成。

## 11. 唯一里程碑 M1 与仓库收尾

初始计划本身不是“已实现/已通过gate”的证明。最终验收已以 §11.1 的实跑证据与覆盖矩阵形成；实现工作包W0–W7不是独立里程碑。M1为v23完整合同与唯一gate通过后的唯一交付里程碑；提前外部提交属于已披露的顺序偏差，按用户明确授权追加收尾，不宣称原单提交序列已履行。

### M1 Done when

1. 从仓库根实际执行 `uv run python v23/test_minimal_loop.py`，退出码0且§9全部50个gate及子case通过；Fake-only、Unix PostgreSQL、三角色/六op/三态/单表边界都成立。没有实跑不得写PASS。
2. 然后同步 `v23/README.md`、`docs/reviews/v23-conformance-matrix-2026-10-10.md` 与 `docs/reviews/v23-deviation-ledger-2026-10-10.md`。这些收尾工件本次已同步。矩阵映射设计§/本计划gate→测试函数/实际证据；偏差台账列现状→裁决→验证，不把未完成的 Oracle 审查或尚未执行的 commit/push 写成通过。
3. 单SQL约定：新增/改SQL都在v23/v23.sql且setup只加载它；AGENTS.md中v8/load.py累计注册规则是v8 stage规则，对独立v23标记“不适用”，不能为了履行旧loader习惯破坏本设计。其它版本生产代码/loader/tests不改。
4. git status检查工作区，按路径逐项stage，仅v23源码/gate/README、本计划、明确需要的设计/收尾工件；源设计仍未跟踪时实现者须明确纳入本次依赖路径，不顺手stage其它未跟踪材料。git status与staged diff再次检查，尤其不得含.env/API key/provider凭据。按照`v23: <祈使句摘要>`commit并push origin main，hook不跳过。
5. 失败即在该步骤停止：gate红先修；hook红修根因；push拒绝先fetch看差异、必要时安全rebase，不force或reset --hard，无法安全合并问用户。不用git add -A/git add ./--no-verify。

v23单独实现且不改共享生产文件，不要求为了本计划重跑所有历史版本的破坏性gate；若后续实施确有共享文件变更（本计划不授权），须先重新界定范围并按AGENTS复跑受影响gate，不能把新v23 green当历史回归证明。Fake-only green也不是产品/真实provider可用证明，真实provider未来任务仍在本计划非目标外。

### 11.1 M1 实际验收与最终交付纪律（2026-10-10）

收尾者核对了独立 peer 修正后的 worker.py/control.py/test_minimal_loop.py 与 SQL（NUL/storage-safe JSON、safe failure marker、正向 parent_instruction 证据），并从仓库根实际执行 `uv run python v23/test_minimal_loop.py`，退出码 0：**50/50 labels, 382 subcases; fake-only Unix PostgreSQL**。README/矩阵/偏差台账/本计划全部更新后，同一命令作为最终 staging 前 gate 再完整运行。若这个最终重跑失败，须停止交付并把状态如实退回失败，不用此前 green 跳过。

覆盖矩阵：`docs/reviews/v23-conformance-matrix-2026-10-10.md`；偏差及 peer/Oracle 处置：`docs/reviews/v23-deviation-ledger-2026-10-10.md`。单 SQL 的 v8 注册为不适用。最终 50 标签全部有运行时 subcases/source，可重新独立执行；/tmp 日志与 ignored prompt exports 不是 durable gate 依赖。

已保留的外部提前提交为 `1e3d5a472258794760b294674e5dfd7064629b5b`，2026-10-10 20:30 +08:00；它先于完整最终 gate/收尾，原一 M1 一提交顺序发生偏差。用户授权不 amend/重写/reset/force，以本次追加 `v23: <imperative summary>` 收尾并普通 `git push origin main`。设计稿在该外部提交中已受跟踪，仍列入明确依赖/stage 允许清单；其它无关 untracked 不纳入。

Oracle 旧 context 缺少 full runtime，新的完整 context 又超时/取消；`untitled-chat-2B4D73` 与 `untitled-chat-3CF52E` 没有全面验收结论。其 SQL P1 已修正，独立 peer review 的 P1/P2 修正按用户确认完成并实跑 green；不另起 Oracle/review，不把未返回结论虚构为无阻塞批准。最终交付结果以本收尾提交、origin/main 和交付报告的确切哈希/push结果核对，不预先伪写成功。

## 12. 决策处置与保真台账

本节使实施者无需阅读聊天或被清理的临时Oracle导出。来源：context_builder生成正文（2026-10-10）、Oracle A–H裁决、`docs/reviews/v23-minimal-agent-loop-plan-critique-2026-10-10.md`以及最终窄Oracle裁决。原critique保留为修订前的历史报告，以下是本计划的逐项处置，不宣称审查agent重新验收过修订版。

| Critique | 处置与理由 | 最终合同/验证 |
|---|---|---|
| P0-1 digest承载 | 采纳pending/done/recovered；同一JSONB保留request摘要，active_input保持真实输入摘要，避免在途幂等失去持久证据。 | §2.5.1、§3.3.1、§3.5；gate24–30 |
| P0-2 工具异常 | 区分业务失败与Python/序列化/超限异常；WorkerExecutionError带有界记录，由Control事务外catch并T2合成failed，遵守设计§6.5。 | §3.4.3、§5.3；gate38–40 |
| P0-3 Host忙循环 | 拒绝额外Control park入口，改本地Event有界停车+execute(poll)，与execute-only同覆盖且更小；不强求每次通知立即唤醒，超时保证有界发现。 | §2.5.4、§3.8.2；gate41及§9.10 |
| P0-4 stopped无回执 | 保留首轮invalid/orphan/late的used=0/NULL合法组合；仅worker_failed需要failed，completed/waiting/used>0仍需receipt。 | §3.7；gate37/35/32 |
| P1-1 ownership/fence | 单数据库一个active runtime，session fence同时承担所有mutation，失联旧generation不能透明重连或迁移receipt；不把锁释放当进程死亡。 | §2.5.2、§3.5–3.6；gate35–36/49 |
| P1-2 上限可达性 | aggregate按canonical数组含framing计算；9call执行前拒绝，真实FakeTool输出构造边界。 | §3.4.3；gate39 |
| P1-3 权限 | PUBLIC CONNECT撤销，真实v23_control跑六op，admin只setup/probe，worker NOLOGIN+SET ROLE CRUD探针。 | §2.5.6、§3.10；gate49 |
| P1-4 budget排序 | 不采纳Oracle F重排，权威§5.3 waiting_input优先；respond admission拒绝超预算；waiting+exhausted出口是明确external cancel。 | §2.5.5、§3.7；gate8/29 |
| P1-5 ID稳定 | 未完成语义操作跨确认丢失重试同ID；已完成下一轮是新ID；cache重放后poll当前状态。 | §3.8.5；gate24/27/30/42 |
| P1-6 跨Host唯一 | 使用(db_identity,run_id)进程级registry/Event，跨实例及sync/async统一；stop/respond不占driver。 | §3.8.1；gate41 |
| P1-7 recovered确定性 | 唯一recovered_orphan/owner_lost收据，保持turns/历史receipt，revision一次；不伪造正常committed。 | §3.6；gate26/35–36 |
| P2-1 引用 | 当前代码行号/AGENTS外部IO行范围已核验，Background引用改为§2；代码存在不等于已验收。 | §2–§4、§12.1 |
| P2-2 start字段 | T1枚举补input_digest和pending，同事务commit。 | §3.3.2；gate2/26 |
| P2-3 机制 | 每条race/lost/restart/idle gate有确定性barrier/hook、子进程、probe；不以sleep/新实例伪造重启。 | §2.5.7、§9.10 |
| P2-4 授权顺序 | actor→cache→expected_revision；未授权不得借cached ID窥探，steer/respond的新revision重放不新Worker。 | §3.3、§9.5；gate24–25 |
| P2-5 ack路径 | commit前确定rollback、commit后健康ack-loss、连接死亡分开；done优先active，新generation只recovery不T2重放。 | §3.5；gate27/30 |

### 12.1 生成基线的保真索引

| 基线实质内容 | 最终保留/纠正位置 |
|---|---|
| Summary/current-state、8文件边界、三角色/单表/六op、当前源码未验收 | §1–§2、§3.1、§4（未泛化为仅checklist） |
| cancel cache/零写/revision、completed不改写、四close reason | §2.4 A、§3.2/§3.3.5、§5/§9；澄清no-op ID不持久登记 |
| owner不重放、T2原owner同receipt重试、restart关闭 | §2.4 B、§3.5–3.6；纠正多进程误关与恢复收据任选问题 |
| DTO-only、tools同轮有限执行、数量/单项/总量/result约束 | §3.4、§4 worker、§9.7；纠正工具异常吞成completed、aggregate不可达 |
| SQL与Python校验职责、immutable字段/角色、gate DB单SQL | §2.4 E、§3.2/§3.10、§4 SQL/setup；增加真实权限运行证据 |
| 六op逐项请求/状态/授权/返回、input_kind、interaction matching | §3.3、§3.9、§5；respond预算admission补实，未新增别名 |
| request/input digest分离、T1/Worker/T2与通知边界 | §3.3.1、§3.5；补pending承载、cache-first和generation fence |
| pure decide校验/固定优先级/三种progress结果 | §3.7、gate7/8/29；纠正stopped必有receipt，保留waiting优先预算 |
| Host单Run driver、continuation/wait/stop、外部stop、parent协调 | §3.8–3.9；明确跨实例、稳定ID、本地停车，取消第二入口 |
| error/edge cases、迁移/回滚风险、no-provider/no-scheduler非目标 | §5–§6、§10全部保留；失败区分和风险收敛可定位 |
| 8 Step与W0–W7 Goal/Done when/Key files/Dependencies/Size | §7–§8全部保留，说明工作包非stage，依赖不循环 |
| 原47个gate、唯一命令、positive proof不被静态扫描替代 | §9原标签全部保留并补3个成为50条；§9.10给注入机制 |
| 新增决策依据、唯一M1与AGENTS收尾纪律 | §11–§12；不自动把文档修订当代码gate通过或提交 |

以上纠正都来自明确设计、当前代码或更小且同覆盖的替代方案；没有仅为篇幅删除准确细节。收尾静态核对检查全50标签连续、代码引用存在/行范围有效、Markdown围栏成对、六op/三态闭集未扩大、原基线47标签仍保留。该历史静态核对不替代实现gate；初始计划生成时未运行setup或test。实现收尾的实际完整gate证据现见 §11.1 与覆盖矩阵。

### 12.2 可执行状态与未决项

W0–W7 已按完整运行时 gate 完成技术验收，没有未解决的实施设计问题；最终 git 交付仍按 §11 执行并如实报告。固定限制必须显式接受：一个数据库同时一个active runtime；waiting+预算耗尽不自动关闭、需显式cancel；Host无signal变化是有界poll发现而非即时事件保证；取消不杀外部请求。若要多进程multi-writer、改变budget排序、真实provider或后台scheduler，属于后续设计变更，不在此计划暗中扩展。

参考：权威设计 `docs/designs/v23-minimal-agent-loop-2026-10-09.md:1-1397`、仓库 `AGENTS.md:1-78`、前述v23文件；历史模式仅参考 `v13/fair_driver/driver.py:19-44` 的短事务IDLE、`v13/control/test_control.py:603-644` 的角色/锁probe、`v8/closeout/v8_closeout.sql:116-142` 的通知wake hint。临时Oracle exports在保真核对后清理，所有绑定合同已内嵌本文，不依赖它们继续存在。
