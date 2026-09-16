# s31a-identity-commands — §3.1 前半：身份、session 控制行、advance_session、claim/lease

> 源：`/Users/wxl/Projects/pg-agent/docs/designs/v8-dev.md` 第 199–298 行。覆盖：§3 开头、§3.1 总则、advance_session 伪代码、session 控制行、§3.1.1 Session 闭合状态与转移（含 driver_mode 切换、quiescing、terminal 子协议矩阵、heartbeat 生命周期矩阵与授权字段合同、fail_session、claim/lease/recovery_claim、受控 SQL 服务事务、request_cancel）、§3.1.2 标题与「统一命令名：」code block 起始行为止（§3.1.2 命令清单正文不在本 digest 范围）。
> 本节 MUST / MUST NOT 是强制合同。抽取为逐字关键字段/code/公式，未意译。

## 0. 根不变量（适用全节）[P0B-CORE]

- `logical step` 是一次模型决策及其后续工具批次；**不是一次 worker claim**。
- SQL MUST 先密封 decision 批次，收到成功的模型结果后才冻结工具 `plan_hash`、密封 tools 批次；MUST NOT 在模型结果返回前猜测工具请求。
- 每个批次的成员与 ordinal 密封后不可变；额外模型决策 MUST 新建 step。
- 任何事务 MUST NOT 等待外部网络、LLM、工具或宿主 handler。

## 1. 数据库表（完整清单）

### 1.1 session 控制行 [P0B-CORE]（规格仅部分给出：列名闭合清单冻结，类型/完整 DDL 未在本段给出）

session 控制行**必须**包含（逐字）：

```text
session_id, driver, driver_epoch, driver_mode, state, session_fence,
lease_owner, lease_until, lease_purpose, active_step_id, drain_step_id, next_seq,
cancellation_epoch, failure_code, active_catalog_generation
```

列语义与约束（本段冻结）：

- `state`：§3.1.1 十态闭合集（见 §4.1）；新 session 初态 MUST 为 `ready`；`completed`、`failed`、`cancelled` 是 terminal。
- `driver_mode`：闭合集 `{active, quiescing}`，独立于 session state；新 session MUST 为 `driver_mode=active`。（active [P0B-CORE]；quiescing 语义 [LATER]）
- `session_fence`：claim / 接管 / 终态变更时单调递增（见 §2.3、§2.11）；使旧协调写入失败。
- `lease_owner` / `lease_until` / `lease_purpose`：正常 session lease 只在 `claimed` 持有，离开时 MUST 清空 owner/expiry；正常/recovery lease 共用一个互斥槽；不得抢占未过期 lease；recovery 用 `lease_purpose=recovery`。[P0B-CORE]
- `active_step_id`：**单一活跃 step 模型**权威指针。同一 session 任一时刻至多存在一个非终态 step，由 step 表部分唯一约束强制（约束为权威真相源）；`active_step_id` 是该唯一活跃 step 的指针。create_step guard MUST 以 CAS 校验其为 NULL 或指向已终态 step；session 终态化时 MUST 在同一事务清空；terminal session MUST NOT 重新填充。[P0B-CORE]
- `drain_step_id`：**可空列（冻结）**，terminal failure-drain 定位指针。规则：terminal failure-drain 事务（§2.2 第 3 条 WORKSPACE_LOST fail-closed、§3.1.1 `fail_session` 第 (3) 类 INFRA 收束、§4 三合取 generation 收束引发的 session 立即终态化）使 session 终态化时，若该事务后仍存在非终态 drain step，MUST 在同一事务写入 `drain_step_id` 指向该唯一非终态 step（§4 三合取分支下 step 与 session 同事务终态化、不存在非终态 drain step 时保持 NULL）；`active_step_id` 按既有终态清空规则保持清空；后续 drain 操作（completion/repair/reconcile 收束与重复 drain 判定）MUST 按 `drain_step_id` 定位并锁定该 step；drain 完成（该 step 落终态）MUST 在同一事务清空 `drain_step_id`。「每 session 至多一个非终态 step」的部分唯一约束不变——`active_step_id` 与 `drain_step_id` 均为定位辅助指针、非第二真相源。（列存在于控制行清单中 [P0B-CORE-SCHEMA]；drain 语义 [LATER]）
- `next_seq`：统一 seq 分配器（事件 seq 无洞的载体）。[P0B-CORE]
- `cancellation_epoch`：首次有效 `request_cancel` 递增；terminal 上 cancel 不改变 epoch。[LATER]
- `failure_code`：终态失败 code。
- `active_catalog_generation`：§4 generation 权威值。

### 1.2 step 表（本段涉及的约束；完整列清单在 §3.2.1，此处规格仅部分给出）[P0B-CORE]

- 部分唯一约束（冻结）：**每 session 至多一行 `status` 属非终态集**的 step；非终态集即 §3.2.1 status 闭合集中**六个**非终态值。
- 域闭合：控制态不存在「已创建、未 seal、无 LLM slot」的持久化 planned step；不存在无 effect 的持久化 planned step。
- 已终态 step 不再参与任何转移判定，仅按 §3.2.1 既有优先级贡献最终 code 聚合。
- turn 闭合表示：turn 内存在成功的 `decision_only=true` 关闭 step（§3.1.2 持久化字段、§3.2.1 聚合规则 6）——唯一 turn-complete 信号。

## 2. 命令与流程

### 2.1 `advance_session`（总控循环）[P0B-CORE]

逐字：

```text
advance_session(session_id)
  -> claim session lease
  -> tx: assemble + 初始 decision seal（含受控子操作 create_step：step 创建与 seal 同事务发布，§3.1.2：密封唯一 LLM slot）
  -> commit
  -> effect worker executes one persisted descriptor outside tx
  -> tx: complete_effect + append result event + aggregate step/session（终局路径；矩阵 (iii)/(iv) 且五款状态门接受时仅 observation（不 append 语义结果、不聚合））
  -> coordinator claims again and creates next sealed batch or waits/finishes
```

### 2.2 `create_step`（初始 decision seal 事务内的受控子操作）[P0B-CORE]

- 合同冻结：`create_step` 是**初始 decision seal 事务内的受控子操作**（与 §3.1.2 `create_effect_in_seal` 同模式）：step 的创建与初始 decision seal MUST 在同一事务发布。公开命令名 `create_step` 与其 receipt 幂等语义保留，但其执行事务即初始 decision seal 事务，不存在独立的持久化路径。
- guard（有序）：
  1. MUST 以 CAS 校验当前 `active_step_id` 为 NULL 或指向已终态 step（即上一 step 已收束）；活跃 step 仍非终态时 MUST NOT 创建新 step。
  2. 目标 turn 尚无成功的 `decision_only=true` 关闭 step（turn 未闭合才可创建）；turn 已闭合时 MUST NOT 创建同 turn 新 step，稳定拒绝 **`TURN_ALREADY_CLOSED`**。
  3. guard 通过后同事务创建 step 并接管指针、随即完成初始 decision seal（§3.1.2）一并提交。
- `create_step` 脱离初始 decision seal 事务的单独持久化 MUST 被拒绝（**不产生任何 step 行**）。
- 「有下一 step」的表示即 turn 未闭合——turn 内尚无 `decision_only=true` 的成功关闭 step 且 session 非终态——此时 coordinator MUST 创建下一 decision step；turn 已闭合时进入 §3.2.1 末段闭合分支，不存在其他后继计划表示。

### 2.3 `claim`（正常 claim）与协调 lease 合同 [P0B-CORE]

- claim MUST 锁 session 行，检查 expected driver/epoch、旧 fence、lease 空缺或已过期，单调递增 `session_fence` 并写 owner/expiry/purpose。
- heartbeat/yield/协调命令 MUST 同时匹配 owner、当前 fence、未过期 lease 和 driver/epoch（本句 heartbeat 指协调 lease 续期命令；`session/heartbeat` 观测 append 事件不参与 lease 所有权与续租判定——无推进/续租权限、非免授权，见 §2.12）。
- 正常 session lease 只在 `claimed` 持有；离开时 MUST 清空 owner/expiry。

### 2.4 `recovery_claim` [P0B-CORE（基本 CAS，kill-at-every-boundary chaos 所需）/ LATER（terminal 与 switch-intent 细则）]

- 可在任意 `N`（非终态）上、仅 lease 空缺或过期时以相同 CAS 获得 `lease_purpose=recovery`。[P0B-CORE]
- terminal `failed` session 仅限三类（terminal 子协议矩阵 (b) 行三类：§2.2 第 3 条 WORKSPACE_LOST、`fail_session` 第 (3) 类 INFRA、§4 GENERATION_REVOKED）收束的未决 effect / drain-pending step 收束与 step/effect failure-drain。[LATER]
- 任何 terminal session 若存在既存 switch intent，recovery claim 仅可用于 `reconcile(finish_switch)` 的屏障确认与 lease/fence/ownership 更新。[LATER]
- 两者均不得开展新工作；只改变 ownership，不改变业务 state；MUST 保留并核对 `active_step_id`（terminal session 上该指针恒为空、MUST NOT 重填——非终态 drain step 按 `drain_step_id` 定位与核对）。
- 扫描 MUST 覆盖过期 claimed、blocked/cancel 状态及过期 job。
- 接管 session MUST NOT 自动撤销仍有效 job lease（与 §3.2.2 接管流程第 2 步 guard 对齐）：recovery 对仍持有效 job lease 的 attempt MUST 跳过——不推进 `current_job_fence`、不撤销 lease、不结算，effect/attempt 状态不变，留待 job lease 到期后由重扫描或后续 recovery 处理；接管结算仅当该 attempt 的 job lease 已过期或已被明确撤销。

### 2.5 `FORCE_JOB_TAKEOVER` [LATER]

撤销仍有效 job lease 并立即接管仅经 operator 显式授权的受控内部操作 `FORCE_JOB_TAKEOVER`——记录 operator 身份、接管原因与审计；属受控内部入口而非普通 recovery（与 §0 不变量 3 一致）。

### 2.6 `reconcile(begin_switch)`：driver_mode active→quiescing [LATER]

driver 切换 MUST 由受权 `reconcile` 的模式操作完成，MUST 锁 session 并使用当前 recovery lease、expected driver/epoch/mode/fence CAS。

安全点 guard 四款（任一不满足 MUST 返回稳定 **`SWITCH_DEFERRED`**——guard 拒绝、可重新发起；MUST NOT 修改 mode/fence/switch intent 或撤销 lease，由调用方待条件经 seal / dispatch / completion / repair 收束后重试）：

- (i) 无未密封 tools plan（无 step 处于 `ready, stage=decision`）；
- (ii) 无 stage=decision 的 in-flight effect（其 completion 可能返回 tool calls、产生新的未密封 plan）；
- (iii) 无任何未 dispatch 的 `ready` effect——已密封但未派发同样不满足（quiescing 内不可 dispatch、无法自然收束；`planned` 为 seal 事务内临时构建态、不持久化（§3.2.2 状态闭合），已提交控制态中不存在 planned effect，本项判据即 `ready`）；
- (iv) 无任何处于非终态且仍可能经 completion/repair 产生 tools plan 的 decision step（含 `blocked_unknown_effect` 的 stage=decision step——其 repair 成功会按 §3.2.1 聚合规则 6 回到 `ready, stage=decision`，产生 quiescing 内不可 seal 的 plan）。（域闭合：不存在无 effect 的持久化 planned step——(iv) 无需额外覆盖该形态。）

满足时 MUST：持久化唯一 switch identity 与 target_driver、递增 session_fence 并撤销当前协调 lease（遵守 checkpoint/lost）；MUST NOT 自动撤销仍有效 job lease。进入 quiescing 时不存在可产生新 tools plan 的路径：tools-stage in-flight effect 的完成（`final_tools=true`）只终态化 step、不产生新 plan；残留 `failed_retryable` 经 §3.2.2 受控边收束、unknown 经 repair 收束，均不创建新 attempt，finish_switch 屏障可达。

### 2.7 `reconcile(finish_switch)`：quiescing→active [LATER]

MUST 在同一 CAS 事务确认：

- 无旧 epoch 非终态 effect、无 unresolved unknown、无有效旧 job lease（或已逐个推进 fence 并撤销至必被 stale-reject——该推进受 §3.2.2 接管流程第 2 步 job lease 有效性 guard 约束：仅限已过期/已被撤销的 lease，仍有效 lease 只能等待到期或经 operator 受权 `FORCE_JOB_TAKEOVER`）；
- 且 active_step_id 为空或指向已终态 step、无未密封计划。

随后 MUST 一次性写 target_driver、`driver_epoch+1`、`session_fence+1`、清空 lease/switch intent，保留 sticky cancel/failure 与既有 session state；MUST NOT 无条件置 session 为 ready。对存在既存 switch intent 的 terminal session，finish_switch 只更新 mode/driver/driver_epoch/ownership/session_fence，MUST NOT 改变业务终态（屏障条件仍须全部满足）。

quiescing→quiescing（同 mode）：仅 `repair` / `reconcile` 可收束旧 epoch 工作；MUST NOT 创建新工作或新 attempt；`stream_progress` 以五款状态门为唯一入口（`attempt/heartbeat` 各自门）。

### 2.8 quiescing 拒绝与例外集 [LATER]

- `quiescing` 下所有 epoch 的 `create_step / prepare_step / create_effect / seal_batch / retry_effect / dispatch_effect` MUST 返回 **`DRIVER_QUIESCING`**，包括进入 quiescing 前已持 lease 的 coordinator；guard MUST 在业务 mutation 前锁 session 检查。
- 同样拒绝（返回 `DRIVER_QUIESCING`）：普通 claim、语义输入类 append（`user/message`、`turn/start`、`agent/inject`）、**终局** completion（`complete_effect` 的终局结算路径，W01 终局限定）、timer/wait/sleep/finish/fail 推进。
- 观测类写入例外（Q03，照常接受、均非新工作）：
  - 观测类白名单 append：`assistant/chunk`、`session/heartbeat`；
  - attempt 级观测写入（W01 显式枚举）：`attempt/heartbeat`、`stream_progress`（后者即 `stream_complete=false` 非终局 stream observation，`complete_effect` 的非终局子操作例外，§3.2.2 grammar (0)(iii)：以五款状态门为唯一裁定入口，quiescing 不是五款之一、不阻观测——满足「当前执行 attempt、未终局、未 superseded、窗口内」即接受、零控制态修改）；
  - `session/heartbeat` 在 quiescing 下并允许**旧 epoch**（L4-U03：envelope 的 driver/epoch 对该类型降为记录不匹配、不拒绝）；
  - 不推进状态、不触发 seal/dispatch/retry（迟到尾部 chunk 按 §1.2 屏障 (b)(d) 既有生命周期处理）；
  - 历史 receipt 重放、audit、inspect、recovery claim/heartbeat/yield 只服务屏障，不开放新工作。
- 受权 `request_cancel` MUST 仍可设置 stop latch，但其 effect 收束 MUST 委托同事务的 `reconcile` 路径。
- 旧 worker **终局** result MUST 经 `reconcile` 的结果接收子操作按 §3.2.2 全 envelope 校验结算（X01＋Y01 终局限定：`stream_complete=false` 中间事实经 §3.2.2 共用四步序判定后仅 `complete_effect` 五款状态门可收作 observation；`reconcile` 结果接收遇该形态固定拒绝 **`OBSERVATION_WRONG_ENTRY`**、MUST NOT 写 stream_progress/observation——§3.2.2 四步后分流第 (2) 分支）。`reconcile` 结果接收是 quiescing 下唯一合法终局结算入口（不套 `DRIVER_QUIESCING`；该拒绝作用于 `complete_effect` 终局命令）。
- 切换完成后所有旧 epoch 新写入 MUST stale-reject；历史 receipt 读取不属于新写入。

### 2.9 `fail_session`（受控内部入口，不是独立公开失败路径）[LATER]

`N → failed` 仅经下列三类闭合来源触发（guard 即此三类闭合来源，**无第四类**），公开调用者 MUST NOT 指定任意 `failure_code`：

1. §3.2.1 规则 4 的 terminal failure 分支（含原规则 5 否分支并入规则 4 的场景，如纯预算耗尽批次；规则 5 正分支的 session 目标为 `ready`、step `failed_retryable`，不是 `N → failed` 来源），code 由派生表唯一派生，及 §4 generation 强制下线三合取分支（§4 第 5 条三合取成立时的 `GENERATION_REVOKED` 派生表行）；
2. §2.2 第 3 条 WORKSPACE_LOST fail-closed（既有三分支 drain）；
3. 基础设施失败闭合集 **`{INFRA_ASSEMBLY_FAILED, INFRA_PROTOCOL_VIOLATION}`**——仅用于 assemble 层与协议层的不可恢复错误（如 assemble 无法构造合法 manifest、协议不变量被违反且不可经 repair/reconcile 收束）。drain 与 WORKSPACE_LOST 同款：session 立即 terminal `failed`（`failure_code`=对应 INFRA code），未 dispatch effect → `cancelled_before_dispatch`，in-flight effect 按 unknown/pending/皆无三分支随 completion/repair/reconcile 逐步收束，未完成 step → `failed_terminal`、`outcome_code`=对应 INFRA code（§3.2.1 派生表 INFRA 行）。凡本合同针对 WORKSPACE_LOST 规定的未决 effect 收束、drain、terminal session 例外与 recovery claim 例外条款，对 INFRA 收束同样适用，仅 session/step code 按对应 INFRA code 替换。

### 2.10 `request_cancel` [LATER]（其 turn/end 派生复用 §1.2 唯一 turn-finalization reducer，reducer 本身 [P0B-CORE]）

- MUST 是粘性停止：首次有效命令递增 `cancellation_epoch` 并关闭所有未密封计划（quiescing 时由同事务 reconcile 执行）；后续取消请求返回已有 latch。
- 取消后 MUST NOT 创建 step/effect、密封新工作、dispatch 或 retry（包括取消前已计划但未 dispatch 的工作）。
- pre-dispatch 取消双表原子同步（数据库内部取消路径、非 worker completion，合同唯一冻结于 §2.2 第 3 条 (a) 与 §3.2.2 状态图注）：cancel 事务（quiescing 时为同事务 `reconcile` 路径）将已发布 `ready` effect 收束为 `cancelled_before_dispatch` 时，其当前 attempt 行同事务转 `cancelled_before_dispatch`。
- terminal session 上 cancel MUST 返回原终态且不改变 epoch。
- **无活跃工作分支**：设置 latch 的同一事务内，若 session 处于非终态且**无非终态 step 且无未决 effect**（三个已识别窗口：新建 `ready` 尚无任何 step；`waiting_event`/`sleeping`（其转入 guard 已保证无非终态 step/effect）；step 已终态但 session 尚未 `finish_session`——含 turn 关闭 step（`decision_only=true`）成功后等待 finish、与 `final_tools` 批次成功后等待下一 decision step 两亚类），MUST 在该事务直接把 session 收束为 `cancelled`（`failure_code=CANCELLED_BY_REQUEST`，复用 §3.2.1 派生表既有行；不经 §3.2.1 规则 1–6 求值——无活跃 step 可聚合；quiescing 时与未密封计划关闭一样经同事务 `reconcile` 路径执行）。已有 terminal step 保持原终态与 `outcome_code` 不变（结果保留于 trace/audit）；同事务清空 `active_step_id`（§3.1 既有规则）、撤销协调 lease 并递增 `session_fence`（使旧协调写入失败）。
- canonical 输出与 §1.2 唯一 turn-finalization reducer 对齐、MUST NOT 另设第二套 `turn/end` 规则：
  - 无任何 turn 时不产生 turn 事件；
  - 已闭合 turn 不改写其既有 end（已终态 step 的结果保留于 trace/audit）；
  - 存在已开启 turn 时按 §1.2 优先级 (2) dispatch-phase guard 唯一派生——该 turn 无任何曾进入 `dispatch_started` 的 effect（含无任何 effect/未决工作）→ `turn/end {interrupted:true, reason:cancelled_by_request_before_dispatch}`；存在曾进入 `dispatch_started` 的 effect（含其终态）→ `turn/end {interrupted:true, reason:cancelled_by_request_after_dispatch}`。
- 与 `finish_session` 的竞争按数据库提交序唯一裁定（两命令均先锁 session 行）：cancel 先提交 → session `cancelled`，其后到达的 `finish_session` MUST 返回原终态且不改变任何状态；finish 先提交 → session `completed`，其后到达的 cancel 按上句 terminal 规则返回原终态且不改变 epoch。

### 2.11 受控 SQL 服务事务规则（`complete_effect` / `request_cancel` / timer 唤醒）[P0B-CORE]

- 协调命令/repair MUST 使用当前 session lease。
- `complete_effect`、`request_cancel` 和 timer 唤醒是受控 SQL 服务事务：MUST 锁 session 行并执行各自身份校验；不要求 job worker 取得协调 lease。
- 若将 `claimed` 改为别的 state，MUST 撤销协调 lease 并递增 session_fence，使旧协调写入失败。（双 fence 基本语义的一部分）
- 所有这些事务都 MUST 遵守 workspace checkpoint/lost 既有规则；MUST NOT 在事务中 materialize 或执行外部 I/O。

### 2.12 两类 heartbeat：生命周期 + 授权字段合同（冻结）[LATER]

**heartbeat 授权字段合同（L4-R06）**——两类均零控制态修改（仅观测事件、统一 seq 分配或 `observation_ordinal`、receipt 与规定 audit 写入）：

(1) `session/heartbeat`（公开 append 白名单观测类）——「无 lease」限定为「不参与 lease 所有权与续租判定」，非免授权（S05）：不校验、不消耗、不续期任何 session/job lease，不承载任何推进或续租权限，亦不以 lease 持有/owner 匹配为接受条件；但 MUST 满足公开 append 全部标准校验（无一豁免）：
  - (i) 有效 `event_append` capability grant（§2.1 有效 grant 全部合取条件 + slice-membership）；
  - (ii) 调用安全上下文与目标 session 归属（跨租户/无授权拒绝——授权前置最高优先）；
  - (iii) 类型白名单（`public_append_types@v1` 内，越权类型 `EVENT_TYPE_RESTRICTED`）；
  - (iv) session 生命周期门（quiescing 照常、terminal 拒绝 `SESSION_TERMINAL`）；
  - (v) 标准 envelope/批次/receipt/seq 合同（统一 envelope + computed hash、§3.1.2 批次合同、统一 seq 分配器、receipt 幂等/首占）；envelope 无附加 lease/fence 字段（「无 lease」的精确含义即校验栈中不存在 lease 项——不是跳过校验栈其余各项）；
  - (vi) quiescing 旧 epoch 例外（L4-U03）：quiescing 时 envelope 的 driver/driver_epoch 校验对该类型降级为记录不匹配、不拒绝（旧 epoch 心跳照常接受、正常分配 seq 落盘，仅将提交 epoch 及差异记入事件/audit；MUST NOT 续租任何 lease、MUST NOT 推进任何 fence/epoch）；active 态照常（不匹配 `rejected_stale`）；terminal 一律拒（`SESSION_TERMINAL`）。

(2) `attempt/heartbeat`（数据库内部观测事件）——经受保护观测写入函数（O01）按四款校验：
  - (i) attempt 归属——`effect_id`/`attempt_no` MUST 定位该 session 的持久化 attempt 行（归属不符稳定拒绝、零事件落盘）；
  - (ii) 未终态——attempt 已终态（terminalization 四终态）稳定拒绝、零事件落盘；
  - (iii) 当前 job lease owner（fence 匹配）——写入方 MUST 为该 attempt 绑定 job lease 的当前 owner，且其 fence/driver_epoch 与 attempt 行冻结快照（`dispatch_job_fence`/`driver_epoch` 权威值，§3.2.2 双表权威性冻结）匹配；例外（quiescing 与 terminal failure-drain）——该两态下允许旧 epoch worker 的心跳（drain 观测需要），audit 记录提交方 epoch（与快照不一致时照常写入并记录差异）；
  - (iv) superseded / lease 失效 → 固定 `rejected_stale`——attempt 已被取代（`superseded_by_attempt_no` 非 NULL）、或写入方非当前 lease owner、或该 job lease 已被撤销/接管时，稳定拒绝固定 code `rejected_stale`（receipt 按 §3.1.2 规则落 `rejected_stale`、零事件落盘、零控制态修改，同 `command_id` 重试幂等返回同拒绝）。

`SESSION_TERMINAL` 拒绝按 §3.1.2 receipt 规则落 `rejected_mismatch` 并保留该 code（零事件落盘、零控制态修改，同 `command_id` 重试幂等返回同拒绝）。

## 3. 字节级算法

本范围（L199–298）**未定义任何具名版本化字节级算法**（无 xxx@v1/@v2 的编码公式在本段给出）。本段引用但定义在别处的算法/合同（实现时到对应 digest 取）：

- `public_append_types@v1`（类型白名单，§3.1.2）；
- 统一 envelope + computed hash（§3.1.2）；
- 统一 seq 分配器（session 控制行 `next_seq` 列承载）；
- `observation_ordinal` 分配（O01，§3.2.2 一侧）。

## 4. 状态机

### 4.1 session state 闭合集 [P0B-CORE]

```text
ready, claimed, waiting_effect, waiting_event, sleeping,
cancel_requested, blocked_unknown_effect, completed, failed, cancelled
```

- terminal：`completed`、`failed`、`cancelled`；新 session 初态 MUST 为 `ready`。
- 下表与 §3.2.1 的唯一聚合函数共同定义全部合法转换；未列出的转换 MUST NOT 执行。
- `N` 表示本表所有非终态；guard 不满足 MUST 拒绝且不改业务状态。

### 4.2 driver_mode 闭合集 [LATER]

`driver_mode ∈ {active, quiescing}`，独立于 session state 的闭合集；新 session MUST 为 `active`。切换仅经受权 `reconcile` 模式操作（§2.6/§2.7），MUST 锁 session 并使用当前 recovery lease、expected driver/epoch/mode/fence CAS。

### 4.3 session 合法转移表（逐字）[核心行 P0B-CORE，标于行末]

| 来源 | 目标 | 唯一 guard / 操作 |
|---|---|---|
| `ready` | `claimed` | 正常 claim 成功，driver_mode=active，无 sticky cancel/failure [P0B-CORE] |
| `claimed` | `ready` | 显式 yield 或 recovery 接管后释放；保留已有 active step，不重新生成工作 [P0B-CORE] |
| `claimed` | `waiting_event`, `sleeping` | 无非终态 step/effect；持久化未满足 predicate 或 wake time [LATER] |
| `waiting_event`, `sleeping` | `ready` | predicate 满足或 timer 到期；无 stop latch [LATER] |
| `claimed` | `completed` | `finish_session`：guard 与 §3.2.1 聚合规则 6 共用同一 SQL 判定函数——turn 内全部 step 成功且最后一个 step 为 `decision_only=true` 关闭 step（§3.1.2 既有持久化字段、唯一 turn-complete 信号），且无未密封计划或待处理工作；`completed` 仅经本行进入，MUST NOT 存在其他 `completed` 路径 [P0B-CORE] |
| `N` | §3.2.1 聚合目标 | 仅 seal/retry/complete/cancel/fail/repair/reconcile 的原子聚合；不得由 worker 指定目标；聚合触发的 `complete` 仅限终局结算路径（§3.2.2 四步后第 (3) 分支）——矩阵 (iii)/(iv) 且五款门接受的观测不是本行触发（AF01：观测路径零聚合，写集见 §3.2.2 grammar (0)(iii)）[P0B-CORE] |
| `N` | `cancelled` | 仅 `request_cancel` 无活跃工作分支（本节 request_cancel 段）：sticky latch 设置时 session 无非终态 step 且无未决 effect → 同事务直接收束 `cancelled`/`CANCELLED_BY_REQUEST`，不经 §3.2.1 聚合求值；已有 terminal step 保持原终态 [LATER] |
| terminal | 原状态 | 仅按下文 terminal 子协议矩阵（五类终态 × (a)–(e)）允许的操作执行；矩阵未列出的操作一律 MUST NOT 执行（含以开展新工作为目的的普通 claim / recovery claim——受限 recovery claim 仅服务于矩阵 (b) failure-drain 或 (d) finish_switch 两类用途）；fork MUST 创建另一 session（切点稳定性另受 §3.3 fork guard 约束）[LATER] |

### 4.4 terminal 子协议矩阵（冻结）[LATER]

terminal session 上的全部允许操作按 session 终态类别 × 操作类别唯一裁定；矩阵未列出的操作对全类 MUST NOT 执行。五类操作（先冻结操作定义再查矩阵）：

- (a) **只读**：receipt 重放、audit、inspect（含 compact 终态历史行只读 replay——§3.3 terminal session 允许无协调 lease 只读 replay 例外与本行同源）。
- (b) **failure-drain 收束**：既有 in-flight completion / pending 的 completion 收束、unknown 的 `repair`、`reconcile` 收束与 step/effect failure-drain（含 drain-pending 非终态 step 的重复 drain 判定）——非终态 drain step 按 §3.1 `drain_step_id` 定位与锁定，session MUST 保持原终态、MUST NOT 恢复执行或重建 workspace；受限 recovery claim 服务于本类用途（repair/reconcile/drain 收束所需的 recovery claim 即经本类允许）。
- (c) **迟到合法归属 chunk 观测留存**：terminal session 后迟到的合法归属 `assistant/chunk`（通过 §3.1.2 六项归属校验）照常白名单 append（观测类、非新工作——不创建任何 step/effect/attempt），仅作 observational 留存，MUST NOT 改变已关闭结果或已收束 decision；不改变业务调度状态与 effect/step 结算状态——统一 seq 分配器、receipt/binding 与规定审计的元数据写入不受此限（迟到 chunk 的 append 本身经统一 seq 分配器分配 seq、写 receipt 与规定审计；等值验证生命周期拆分见 §1.2 流完整性屏障 (d)）。
- (d) **既存 switch intent 的受限 finish_switch**：存在既存 switch intent 的 terminal session 允许受限 recovery claim（仅此用途）与 `reconcile(finish_switch)`——只改 mode/driver/driver_epoch/ownership/session_fence，MUST NOT 改变业务终态，finish_switch 屏障条件仍须全部满足。
- (e) **永久禁止（全类）**：新 step/effect/attempt/seal/retry/dispatch 与普通 claim（含以开展新工作为目的的 recovery claim；(b)/(d) 类受限 claim 不属本项）；**公开 append 白名单类型中，除矩阵 (c) 迟到 chunk 外一律拒绝**——terminal session 上的公开 append（`session/heartbeat` 等白名单观测类与 `user/message`/`turn/start`/`agent/inject` 白名单输入类）稳定拒绝（闭合 code **`SESSION_TERMINAL`**，§3.1.2 事件类型权限矩阵；矩阵 (c) 的迟到合法归属 `assistant/chunk` 是唯一例外）；attempt 级观测（`attempt/heartbeat`）按 heartbeat 生命周期矩阵裁定。

| terminal 类别 | (a) 只读 | (b) failure-drain 收束 | (c) 迟到 chunk 观测 | (d) 受限 finish_switch | (e) 新工作/普通 claim |
|---|---|---|---|---|---|
| `completed` | ✓ | ✗ | ✓ | ✓ | 禁止 |
| `cancelled` | ✓ | ✗ | ✓ | ✓ | 禁止 |
| `failed` / `WORKSPACE_LOST` | ✓ | ✓（§2.2 第 3 条 fail-closed drain） | ✓ | ✓ | 禁止 |
| `failed` / INFRA（`INFRA_ASSEMBLY_FAILED`、`INFRA_PROTOCOL_VIOLATION`） | ✓ | ✓（§3.1.1 `fail_session` 第 (3) 类，与 WORKSPACE_LOST 同款） | ✓ | ✓ | 禁止 |
| `failed` / `GENERATION_REVOKED` | ✓ | ✓（§4 三合取收束：下线事务 drain 与后续 completion/repair/reconcile 收束） | ✓ | ✓ | 禁止 |

矩阵注：
- (1) 其余 `failed` code（`FAILED_TERMINAL`、`FAILED_RETRY_BUDGET_EXHAUSTED`）不属 failure-drain 三类——其收束路径（§3.2.1 聚合规则 4）不产生非终态 drain step，仅适用 (a)(c)(d)(e)、不适用 (b)。
- (2) `completed`/`cancelled` 类 (b) 为 ✗：两类收束路径（聚合规则 3/6、`finish_session`、request_cancel 无活跃工作分支）均以无 pending/unknown 为前置，不存在 drain 收束需求；迟到写按 (a) 只读与既有 stale/终态规则处理。attempt 级观测写入的终态适用按注 (5) heartbeat 生命周期矩阵与其类别自身状态门裁定（`attempt/heartbeat` 的 failure-drain 例外不适用于 `stream_progress`——注 (5) 矩阵注 (iii)，S06）。
- (3) compact lock 终态受控 abort 不是 terminal session 上的操作，而是**进入** terminal 的事务的内部子操作：session 进入任一 terminal 状态的事务 MUST 在同一事务 abort 仍处 `locked` 的 compact lock（§3.3 终态事务受控 abort——session 终态事务内部子操作、非独立命令；fenced abort 推进 compact owner fence、lock 落 `aborted` 回 `idle`，旧 owner 此后 stale-reject **`STALE_COMPACT_FENCE`**）。
- (4) fork 创建的是另一 session（新控制态，本 session 上无新工作），不受 (e) 禁止——其切点稳定性由 §3.3 fork guard 独立约束。
- (5) heartbeat 生命周期矩阵见 4.5。

### 4.5 heartbeat 生命周期矩阵（冻结，Q03）[LATER]

P01 拆分后的两类心跳（`session/heartbeat` 公开 append 观测类 / `attempt/heartbeat` 数据库内部观测事件）在 session 生命周期各态的行为按下列矩阵唯一裁定（矩阵未列形态不存在；「照常」= 与该态无关地按各自既有合同执行——公开 append 经统一 seq 分配器分配 seq、内部观测按 O01 (α) 分配 `observation_ordinal`）：

| session 生命周期态 | `session/heartbeat`（公开 append） | `attempt/heartbeat`（内部观测） |
|---|---|---|
| `active` / `claimed`（含全部非终态业务态） | 照常（公开 append、统一 seq 分配） | 照常（O01 ordinal 分配） |
| `quiescing` | 照常（白名单观测 append、非新工作——不推进状态、不触新工作，注 (i)；允许旧 epoch——envelope driver/epoch 记录不匹配、不拒绝，注 (iv)） | 照常（内部观测、非新工作——同款注记；允许旧 epoch——授权字段合同 (2)(iii) 例外既有） |
| terminal × failure-drain 三类（`failed`/WORKSPACE_LOST、INFRA、GENERATION_REVOKED）且目标 attempt 未终态（in-flight） | 拒绝（矩阵 (e)：`SESSION_TERMINAL`） | 照常（drain 观测需要——矩阵 (b) 收束服务的观测面，attempt 未终态则观测写入照常） |
| terminal 其余全部形态（failure-drain 三类的 attempt 已终态；`completed`/`cancelled` 全部——其收束路径以无 pending/unknown 为前置、attempt 均已终态） | 拒绝（矩阵 (e)：`SESSION_TERMINAL`） | 拒绝（attempt 已终态——terminalization 后唯一允许操作为 audit/receipt 重放（§3.2.2），受保护观测写入函数稳定拒绝、零事件落盘、零控制态修改） |

矩阵注：
- (i) quiescing 行的「照常」不与 quiescing 段「普通 claim、append……MUST 同样拒绝」冲突——该拒绝指语义输入类 append（`user/message`、`turn/start`、`agent/inject`，返回 `DRIVER_QUIESCING`）；观测类白名单 append 与 attempt 级观测写入均非新工作、照常接受。
- (ii) `SESSION_TERMINAL` 拒绝按 §3.1.2 receipt 规则落 `rejected_mismatch` 并保留该 code（零事件落盘、零控制态修改，同 `command_id` 重试幂等返回同拒绝）。
- (iii) 矩阵仅覆盖两类心跳（observation_kind `heartbeat`）；**`attempt/heartbeat` 的 failure-drain/in-flight「照常」例外不适用于任何其他 attempt 级观测类别（两类 attempt 级观测分开裁定，S06）**：`stream_progress`（非终局 stream observation，§3.2.2 grammar (0)(iii)）在 terminal session 上一律按其自身状态门第 (1) 款（session 终态门，优先序最高——L4-R03/F5）稳定拒绝 `SESSION_TERMINAL`；quiescing 行为措辞同步（W01）：quiescing 下该类别 = 终局 completion 拒（`complete_effect` 终局结算路径 MUST 返回 `DRIVER_QUIESCING`）＋ 观测按各自门（`stream_progress` 为非终局子操作例外，以五款状态门为唯一裁定入口——quiescing 不是五款之一、不构成第六款拒绝：terminal/superseded/四终态/窗口耗尽逐级先行，仅当前且窗口内方接受，满足即接受、零控制态修改）。
- (iv) quiescing 下 `session/heartbeat` 允许旧 epoch（冻结，L4-U03）：envelope 的 driver/driver_epoch 校验对该类型降级为记录不匹配、不拒绝；MUST NOT 续租任何 lease、MUST NOT 推进任何 fence——零控制态修改；active 态不适用本款（照常标准校验，不匹配 → `rejected_stale`——active/quiescing 两态均接受心跳、epoch 判定不同）；terminal 一律拒（`SESSION_TERMINAL`）。

### 4.6 lease 生命周期 [P0B-CORE 基本款 / LATER 细则]

- 正常 session lease 只在 `claimed` 持有；离开时 MUST 清空 owner/expiry。
- claim CAS 与四匹配见 §2.3；recovery_claim 见 §2.4；单一互斥槽、不得抢占未过期 lease。
- 接管结算与 job lease guard（跳过仍有效 job lease 的 attempt）见 §2.4；`FORCE_JOB_TAKEOVER` 见 §2.5。

## 5. P0B 相关性标注汇总

**[P0B-CORE]**（本段中为最小闭环所必需）：

1. 根不变量：logical step 定义、先密封 decision 批次后冻结工具 `plan_hash`、批次成员与 ordinal 密封后不可变、事务不等外部（§0）。
2. session 控制行 15 列闭合清单（`drain_step_id` 列存在为 SCHEMA-CORE，其 drain 语义为 LATER）。
3. step 表部分唯一约束（每 session 至多一行非终态 status）＋ 无持久化 planned step 域闭合（Conformance 1「不存在持久化 planned / 不存在 planned-无-effect step」断言依据）。
4. `advance_session` 六步循环（含「effect worker executes one persisted descriptor outside tx」）。
5. `create_step` 受控子操作：与初始 decision seal 同事务、CAS guard、`TURN_ALREADY_CLOSED`、脱离 seal 事务的单独持久化 MUST 被拒（不产生任何 step 行）。
6. claim CAS（锁行、expected driver/epoch、旧 fence、lease 空缺或过期、单调递增 `session_fence`）＋ heartbeat/yield/协调命令四匹配（owner、当前 fence、未过期 lease、driver/epoch）。
7. `recovery_claim` 基本 CAS（任意 N、仅 lease 空缺或过期、`lease_purpose=recovery`、不开展新工作）——kill-at-every-boundary chaos 测试恢复路径所需。
8. 受控 SQL 服务事务规则：`complete_effect`/`request_cancel`/timer 锁 session 行、不要求 job worker 协调 lease、改 `claimed` 出态时撤销协调 lease＋递增 session_fence（双 fence 基本语义：旧协调写入 stale 失败）。
9. session 转移表核心行：`ready→claimed`、`claimed→ready`（yield/recovery 释放、保留 active step）、`claimed→completed`（finish_session 与 §3.2.1 聚合规则 6 共用同一 SQL 判定函数）、`N→聚合目标`（仅 seal/retry/complete/cancel/fail/repair/reconcile 原子聚合；观测零聚合 AF01）。
10. turn 未闭合表示（无成功 `decision_only=true` 关闭 step 且 session 非终态 → MUST 创建下一 decision step）；turn finalization 唯一 reducer 在 §1.2（cancel 侧派生亦复用之，MUST NOT 另设第二套 `turn/end` 规则）。
11. `next_seq` 统一 seq 分配器（事件 seq 无洞断言的载体）。

**[LATER]**（完整抽取于上文，仅打标记）：

- driver_mode 切换全套：`reconcile(begin_switch)` 四款安全点 guard、`SWITCH_DEFERRED`、`reconcile(finish_switch)` 屏障与一次性写、quiescing→quiescing 规则。
- quiescing 拒绝与例外集：`DRIVER_QUIESCING` 命令集、观测白名单例外、`reconcile` 结果接收唯一终局结算入口、`OBSERVATION_WRONG_ENTRY`。
- terminal 子协议矩阵（五类终态 × (a)–(e)）与矩阵注 (1)–(5)（含 compact lock 终态受控 abort、`STALE_COMPACT_FENCE`）。
- `drain_step_id` 全部 drain 定位语义（terminal failure-drain 三类写入/清空规则）。
- `fail_session` 受控内部入口三类闭合来源（含 INFRA 闭合集 `{INFRA_ASSEMBLY_FAILED, INFRA_PROTOCOL_VIOLATION}` drain 同款规则）。
- `request_cancel` 全套（粘性 latch、pre-dispatch 双表原子同步、无活跃工作分支、turn/end 派生、与 finish_session 提交序竞争）。
- heartbeat 生命周期矩阵与授权字段合同（`session/heartbeat`/`attempt/heartbeat`、`rejected_stale`/`rejected_mismatch`/`SESSION_TERMINAL`）。
- `FORCE_JOB_TAKEOVER` 受控内部操作。
- 转移表 LATER 行：`claimed→waiting_event/sleeping`、`waiting_event/sleeping→ready`、`N→cancelled`（request_cancel 分支）、terminal→原状态。
- `recovery_claim` 的 terminal 三类收束用途与 switch-intent 用途细则。
