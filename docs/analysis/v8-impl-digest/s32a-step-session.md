# s32a-step-session — §3.2 前段：step/session 聚合规则、状态派生
> 来源：`docs/designs/v8-dev.md` 行 397–500（含边界）。覆盖 §3.2 标题、§3.2.1 全部（step 状态机、聚合规则 1–6、outcome_code/failure_code 派生表、session 聚合完整函数语义），以及 §3.2.2 前段（session/job fence 双字段拆分、唯一证据分类函数、recovery 接管原子流程、`FORCE_JOB_TAKEOVER` 完整合同、`effect_requests` 列清单与 `execution_mode` 权威列 N05/O06、双表权威性冻结与判定读取规则清单 A/B、`retry_eligible` 共享谓词、`retry_stop_reason` 有序分类函数与 R-01 分类输出缓存合同、`retry_cohort_allocation` 子操作开头）。
> 本 digest 逐字引用冻结字段名/code 字符串/公式；行 500 之后（`retry_cohort_allocation` 固定顺序的逐步合同、`complete_effect`/`repair`/`EffectResult`/`effect_attempts` 段等）不在本抽取范围，仅标注引用。

## 1. 数据库表（完整清单）

### 1.1 `steps` [P0B-CORE]
规格原文（行 404–407）列清单：

```text
steps(step_id, session_id, turn_id, status, stage, plan_hash,
      sealed_batch_no, pending_effect_count, unknown_effect_count,
      retryable_effect_count, terminal_effect_count, cancellation_epoch,
      retry_count, max_retries, outcome_code, created_at, updated_at, closed_at)
```

冻结要点：
- `retry_count`/`max_retries` 为该 step 全部 effect 创建时冻结预算的**派生缓存**（展示与聚合统计用，随每次 retry 同事务维护），**非权威判定源**；重试预算的权威作用域是 effect 级 `max_attempts`（预算耗尽 ⟺ `attempt_no ≥ max_attempts`）；`retry_eligible` 求值与 `retry_stop_reason` 分类 MUST NOT 以 `steps` 字段为判定输入（`retry_stop_reason` 列本身亦为分类输出列/可验证缓存、非判定输入）。
- `stage ∈ {decision, tools, closed}`；模型决策结果未返回前 `plan_hash` 不得冻结。
- `status` 闭合集（逐字）：
  ```text
  planned, ready, waiting_effect, failed_retryable, cancel_requested,
  blocked_unknown_effect, succeeded, failed_terminal, cancelled
  ```
- 不可变性保护：本段未给出 steps 级触发器 DDL（规格仅部分给出）。`outcome_code` 派生规则见 §2.1 派生表（闭合集，禁止 coordinator 代码另行推断）。
- 单一活跃 step：数据库部分唯一约束保证任一时刻至多一个非终态 step（行 464，逐字：「数据库部分唯一约束保证任一时刻至多一个非终态 step」）。[P0B-CORE]

### 1.2 `effect_requests` [P0B-CORE]
规格原文（行 483–490）列清单：

```text
effect_id, session_id, step_id, batch_id, dispatch_ordinal, tool_call_id,
effect_kind, execution_mode, driver, driver_epoch,
session_fence, dispatch_session_fence, current_job_fence, request_hash,
idempotency_key, status, retry_class, max_attempts, retry_stop_reason, attempt_no, dispatch_count,
provider_request_id, result_hash, grant_id, lease_owner, lease_until,
dispatched_at, created_at, updated_at
```

约束与冻结（逐字）：
- `execution_mode` 权威列（N05 冻结）：`NOT NULL CHECK (execution_mode IN ('streaming','non_streaming'))`（闭合二值集）——effect 创建事务写入、此后不可变（与 `retry_class`/`max_attempts` 同款 effect 级不可变元数据保护：触发器或受保护写函数拒绝 UPDATE）。它是流式调用模式的唯一判定权威；attempt 行与 `EffectDescriptor` 的回显仅为同值冻结副本。[P0B-CORE]
- 副本等值强制（O06 冻结）：(1) 创建等值校验——attempt 行创建（两条 seal 路径成员创建 `create_effect_in_seal` 与 `retry_cohort_allocation` 分配，两入口同款）与 descriptor 创建 MUST 由受保护写入函数在同事务校验副本值 = parent effect 行权威列值，不等值的创建稳定拒绝（零行写入）；(2) 读取点一致性复核——任何读取点（派发门、completion envelope 校验、流完整性适用域判定、recovery 接管、审计重放与 descriptor 创建等）触及副本时 MUST 对照 parent effect 行权威列执行等值复核，不一致 → 稳定拒绝 `INFRA_PROTOCOL_VIOLATION`（MUST NOT 静默采用任一侧值；不一致事实与两侧值留存于 audit，按 `fail_session` 受控内部入口第 (3) 类 INFRA 路径受控处理）；(3) descriptor 创建权威源——`EffectDescriptor` 创建 MUST 读 effect 行权威列复制副本（MUST NOT 读 attempt 副本或任何第二来源），同受 (2) 约束。[P0B-CORE]
- `current_job_fence`：effect 级 completion 写权限 fence（控制字段，非派生快照）——stale 判定（`STALE_JOB_FENCE`）的唯一权威，recovery 接管单调推进；seal 创建首个 attempt 时与 attempt 行 `dispatch_job_fence` 同值冻结。completion 的 CAS/验收（`EffectResult` 的 `job_fence` 匹配）读 `current_job_fence`，证据绑定与 attempt 归属读 `dispatch_job_fence`。[P0B-CORE]
- `retry_stop_reason`：effect 级分类输出列/可验证缓存（R-01 冻结，非判定输入；写入与复核合同见 §3.4）。[LATER]
- `dispatch_count`：派发计数控制字段，`ready -> dispatch_started` 派发门在同一事务递增。[P0B-CORE]
- `lease_owner`/`lease_until`：effect 级 job lease 控制权威。[LATER]
- effect 级不可变元数据（创建时冻结）：`retry_class`、`max_attempts`、`request_hash`、`idempotency_key`、`execution_mode`、`driver`/`driver_epoch`（ownership 不可变）。
- parent 派生执行快照（仅显示，非判定源）：快照范围 = attempt 行执行字段在 parent 行有对应列者——`status`、`attempt_no`、`result_hash`、`dispatched_at`、`provider_request_id`，及 `driver`/`driver_epoch`/`session_fence`/`dispatch_session_fence` 按对应 attempt 冻结值同事务维护的展示性副本；为当前最大 attempt 的同事务派生快照。parent 快照列的 UPDATE 以「快照仍指向该 attempt（`attempt_no` 匹配当前值）」为条件，条件不满足即零行更新。
- `retry_class` 闭合集 `{provider_idempotent, verifiable_no_effect, unsafe}`：`provider_idempotent` 仅当 provider 幂等能力在 effect 创建时已持久化证实；`verifiable_no_effect` 仅当存在可验证的「外部副作用未发生」证据；二者皆非即 `unsafe`。
- 数据库级 stale 强制：外部 completion 事务对 attempt 权威行的 UPDATE 以 `(effect_id, attempt_no)` + 该行 `dispatch_job_fence` CAS 为条件，且同一事务验收其 `job_fence` 与 effect 级 `current_job_fence` 相等（stale 判定唯一权威，不相等即 stale-reject、零行更新）。[P0B-CORE]

### 1.3 `effect_attempts`（规格仅部分给出——本段只给字段名与约束，完整 DDL 在行 500 后的 `effect_attempts` 段）[P0B-CORE]
本段明确点名：
- 主键 `(effect_id, attempt_no)`（由「当前 attempt = 该 effect 最大 `attempt_no` 的 attempt 行（由主键 `(effect_id, attempt_no)` 唯一派生，无需独立指针列）」）。
- 唯一约束 `(effect_id, dispatch_job_fence)`（接管事务提交前 crash 回滚后重启不重复分配的保证之一）。
- 本段提及的列：`attempt_no`、`driver`、`driver_epoch`、`session_fence`、`dispatch_session_fence`、`dispatch_job_fence`、`status`、`result_hash`、`dispatched_at`、`provider_request_id`、`superseded_by_attempt_no`、`execution_mode`（envelope 副本）。
- 冻结语义：`driver`/`driver_epoch`/`session_fence`/`dispatch_session_fence`/`dispatch_job_fence` 为创建 attempt 时冻结的不可变执行快照（attempt 行 `session_fence` 与 `dispatch_session_fence` 同值冻结、不构成两个判定权威）；`status`/`result_hash`/`dispatched_at`/`provider_request_id` 为随执行结算更新的执行权威；`superseded_by_attempt_no` 为取代关系标记列（非执行快照、非判定输入）。

### 1.4 本段引用但 DDL 在别处的表（规格仅点名）
- `sessions`：session 级控制字段 `cancellation_epoch`（取消判定与 envelope 校验读 `sessions` 行权威值，MUST NOT 读取任何 effect/attempt/parent 侧副本；`effect_requests`/`effect_attempts` 均不设该列）；另含协调 lease、`session_fence`、终态与 `failure_code`、`active_step_id`/`drain_step_id`。[cancellation_epoch envelope 校验：P0B-CORE]
- `catalog_generation`：step/job 绑定的 generation 状态行，§4 检查用；recovery 接管第 1 步预锁（共享读）。[LATER]
- `effect_audit`：stale completion 完整 received binding、`RETRY_STOPPED_BY_CLOSURE`/`RETRY_SUPPRESSED_BY_CANCEL`/`COMPLETED_AFTER_CANCEL` audit 记录。[stale completion audit：P0B-CORE；retry/取消 audit：LATER]
- sealed batch manifest 与 slot 成员（批次边界与 cohort 成员资格）。[P0B-CORE（批次边界）]

## 2. 命令与流程

### 2.1 effect → step → session 聚合（同一 control transaction，固定优先级）[规则 2/6 与优先级框架：P0B-CORE；规则 1/3/4/5：LATER]
- 优先级（逐字）：`unknown > pending > cancel 收束（sticky cancel 或非本地 provider 取消）> failed_terminal > failed_retryable > success`；命中首条规则即决定控制终态，不存在实现自由裁量。
- 聚合触发面收口（AF01）：聚合触发的 `complete` 仅限终局结算路径（§3.2.2 四步后第 (3) 分支）；矩阵 (iii)/(iv) 且五款门接受的观测**不是**本聚合触发——观测路径 MUST NOT 调用本节聚合，写集以 §3.2.2 grammar (0)(iii) 为准（规则 1–6 的求值输入不含观测写入路径）。
- 前置禁令（行 433，逐字）：存在 `pending_effect_count>0` 或 `unknown_effect_count>0` 时禁止任何 terminal step/session；唯一例外是 §2.2 第 3 条 WORKSPACE_LOST fail-closed 与 §3.1.1 `fail_session` 受控内部入口第 (3) 类 INFRA 收束——session 均 MUST 立即 terminal `failed`（`failure_code` 固定为 `WORKSPACE_LOST` 或对应 INFRA code），step 不得因 pending 被提前终态化。`failed_retryable` effect 不是 step terminal failure；`unknown_outcome` 不得自动变为 retryable。每次 retry 必须在同一事务递增 `attempt_no` 与（派生缓存）`retry_count`，仍复用原 `effect_id/request_hash/idempotency_key`。
- 规则序（逐字摘录，公式性内容原样）：
  1. 任一 `unknown_outcome` → step/session `blocked_unknown_effect`（唯一例外：WORKSPACE_LOST fail-closed 下 session 目标固定为 `failed`）。[LATER]
  2. 否则任一 pending sibling：非 sticky cancel 下 step 与 session 目标均为 `waiting_effect`；sticky cancel 下 step MUST 为 `cancel_requested`（保持取消等待，不得创建新 effect 或 retry），session 目标固定 `waiting_effect`，不得重新开放 work。[P0B-CORE]
  3. 否则 sticky cancel 已请求，或存在非本地收束的 `cancelled_after_dispatch`（provider 证实取消或 repair 提交 provider 取消证据，即 effect code `CANCELLED_BY_PROVIDER`），且无 unknown/pending：cancel-wins——step 与 session 控制终态 MUST 为 `cancelled`，即使 sibling 中存在 `failed_terminal`。sticky cancel 下 `failed_retryable` effect MUST 由共享取消收束子操作收束为 `cancelled_after_dispatch`（effect code `CANCELLED_BY_REQUEST_AFTER_DISPATCH`，audit 另记 `RETRY_SUPPRESSED_BY_CANCEL`）；无本地 sticky latch 的 provider 取消收束下，剩余 `failed_retryable` effect MUST NOT 创建新 attempt 且 MUST 同一收束事务经受控边 `failed_retryable -> failed_terminal` 原子收束（保留原失败 code，audit 另记 `RETRY_STOPPED_BY_CLOSURE`）；`failed_terminal` effect 保留 failure audit——sticky cancel 收束为 `FAILED_TERMINAL_CANCELLED`，provider 取消收束为 `FAILED_TERMINAL_PROVIDER_CANCELLED`；成功 effect 记录 `COMPLETED_AFTER_CANCEL` audit。[LATER]
  4. 否则任一 `failed_terminal` effect（任何 `retry_stop_reason` 取值）→ 规则 4 关闭整个批次：父层终态化前 MUST 在同一事务关闭全部残留 `failed_retryable` sibling（各经受控边 `failed_retryable -> failed_terminal` 落终态，保留原失败 code，audit 另记 `RETRY_STOPPED_BY_CLOSURE`，并按有序分类函数持久化确定 `retry_stop_reason`——残留 sibling 落 `not_retry_eligible`）；全部收束后才派生 step `failed_terminal`、session `failed`；code 由本批 terminal 失败 `retry_stop_reason` 集合唯一派生：存在 `not_retry_eligible` 或 `first_attempt_failure` → `FAILED_TERMINAL`（同批另有 `budget_exhausted` 不改变 code）；否则（全部为 `budget_exhausted`）→ `FAILED_RETRY_BUDGET_EXHAUSTED`。[LATER]
  5. 否则（规则 4/5 互斥且穷尽）任一 `failed_retryable` → step `failed_retryable`、session `ready`。持久化状态中不存在「不满足 `retry_eligible` 的 `failed_retryable`」（分类时即落 `failed_terminal` 并同事务持久化 `retry_stop_reason`）；聚合事务 MUST 按冻结输入复评各 `failed_retryable` 的 `retry_eligible`：复评不满足（防御性，正常不可达，命中即实现缺陷）MUST 经受控边同事务收束为 `failed_terminal`（audit `RETRY_STOPPED_BY_CLOSURE`）并转规则 4 语义派生。[LATER]
  6. 无 cancel、unknown、failure 且 sealed batch 全部成功：`stage=decision` 且返回 tool calls 时 step 聚合回 `ready, stage=decision` 并冻结 `plan_hash`，session 目标固定 `ready`（coordinator 可 claim 执行 §3.1.2 tools seal），对应 tools 批次只能经 §3.1.2 seal 创建一次；显式持久化 `decision_only=true` 的 decision 或 `final_tools=true` 的 tools batch 成功时 step=`succeeded`。turn 续行判定冻结为持久化合同：`decision_only=true` 标记是唯一 turn-complete 信号。`final_tools=true` 的 tools batch 全成功使 step 终态化时 turn 尚未关闭：session MUST 为 `ready`，coordinator MUST 创建下一 decision step——「下一 step」存在性由 turn 未闭合这一持久化事实（当前 turn 内尚无 `decision_only=true` 的成功关闭 step）决定，MUST NOT 以「无下一 step」等非持久化判据终态化 session。`decision_only=true` 的 decision step 成功即 turn 关闭 step，session 聚合仍 MUST 为 `ready`；聚合本身 MUST NOT 产生 `completed`——`completed` 仅经 §3.1.1 `finish_session` 进入，其 guard 与本条共用同一 SQL 判定函数（turn 内全部 step 成功且最后一个 step 为 `decision_only=true` 关闭 step），不存在其他 `completed` 路径。repair 恢复路径同样命中本条。session 因上述任一聚合离开 `claimed` 时，MUST 在同一事务撤销协调 lease 并递增 `session_fence`，使旧协调写入失败。[P0B-CORE]
- 收尾冻结（行 444，逐字）：并行完成顺序不得影响聚合；使用固定 `dispatch_ordinal`。空的、尚未密封的 batch 不得成功关闭。[P0B-CORE]
- 派生表（step `outcome_code` 与 session `failure_code` MUST 由矩阵确定性派生，闭合集，禁止 coordinator 代码另行推断；逐字行摘录）：

| 聚合结果 | step `outcome_code` | session state / `failure_code` | 标注 |
|---|---|---|---|
| 任一 `unknown_outcome` | `UNKNOWN_AFTER_DISPATCH` | `blocked_unknown_effect` / NULL | [LATER] |
| sticky-cancel 收束，无 `failed_terminal` effect | `CANCELLED_BY_REQUEST` | `cancelled` / `CANCELLED_BY_REQUEST` | [LATER] |
| sticky-cancel 收束，存在 `failed_terminal` effect（cancel-wins） | `FAILED_TERMINAL_CANCELLED` | `cancelled` / `CANCELLED_BY_REQUEST`，failure 保留在 step `outcome_code` 与 audit | [LATER] |
| 非本地 provider 取消收束（规则 3 扩展触发，无 sticky cancel），无 `failed_terminal` effect | `CANCELLED_BY_PROVIDER` | `cancelled` / `CANCELLED_BY_PROVIDER` | [LATER] |
| 非本地 provider 取消收束，存在 `failed_terminal` effect（cancel-wins） | `FAILED_TERMINAL_PROVIDER_CANCELLED` | `cancelled` / `CANCELLED_BY_PROVIDER`，failure 保留在 step `outcome_code` 与 audit | [LATER] |
| `failed_terminal`（无 cancel；唯一命中：本批 terminal 失败中存在 `retry_stop_reason ∈ {not_retry_eligible, first_attempt_failure}`——含规则 4 关闭残留 eligible sibling 产生的 `not_retry_eligible`——经规则 4；同批另有 `budget_exhausted` 时 code 仍为本行） | `FAILED_TERMINAL` | `failed` / `FAILED_TERMINAL` | [LATER] |
| `failed_retryable` 且满足 `retry_eligible` | `FAILED_RETRYABLE` | `ready` / NULL | [LATER] |
| retry 预算耗尽（不满足 `retry_eligible`；唯一命中：收束后本批 terminal 失败全部为 `retry_stop_reason=budget_exhausted`、无任何 `not_retry_eligible`/`first_attempt_failure`——经规则 4 按 reason 集合唯一派生，原规则 5 否分支场景并入规则 4） | `FAILED_RETRY_BUDGET_EXHAUSTED` | `failed` / `FAILED_RETRY_BUDGET_EXHAUSTED`（step 终态 `failed_terminal`） | [LATER] |
| 全部成功 terminalize | `SUCCEEDED` | `ready` / NULL（`completed` 仅经 §3.1.1 `finish_session` 进入，guard 与聚合规则 6 共用同一 SQL 判定函数；聚合 MUST NOT 派生 `completed`） | [P0B-CORE] |
| §2.2 第 3 条 WORKSPACE_LOST fail-closed | 按该条 (b) 三分支：存在未决 unknown 的 step 维持 `UNKNOWN_AFTER_DISPATCH`（`blocked_unknown_effect`），repair 收束后落 `WORKSPACE_LOST`；存在 in-flight pending 的 step（drain pending）保持 `waiting_effect`/`cancel_requested` 且 `outcome_code` 为 NULL，全部收束后落 `WORKSPACE_LOST`；两者皆无的未完成 step 即落 `WORKSPACE_LOST`（上述收束后 step 终态均为 `failed_terminal`） | `failed` / `WORKSPACE_LOST`（未决 effect 收束与 drain 均不改变该终态） | [LATER] |
| `fail_session` 受控内部入口第 (3) 类：INFRA_ASSEMBLY_FAILED 收束 | 未完成 step 落 `failed_terminal` / `INFRA_ASSEMBLY_FAILED`（drain 三分支与 WORKSPACE_LOST 同款；已终态 step 保持原 `outcome_code`） | `failed` / `INFRA_ASSEMBLY_FAILED` | [LATER] |
| `fail_session` 受控内部入口第 (3) 类：INFRA_PROTOCOL_VIOLATION 收束 | 未完成 step 落 `failed_terminal` / `INFRA_PROTOCOL_VIOLATION`（同上） | `failed` / `INFRA_PROTOCOL_VIOLATION` | [LATER] |
| §4 generation 强制下线（`active → failed`）收束（仅三合取分支：无法续行 × 无法经既有聚合规则（规则 3/4/5、取消收束）终态化 × 无未决 unknown/pending） | 落 `failed_terminal` / `GENERATION_REVOKED`；能经既有规则终态化时终态与 code 按对应既有行派生、MUST NOT 被 `GENERATION_REVOKED` 覆盖（§4 第 5 条三合取）；已终态 step 保持原 `outcome_code`；全部已决 effect 成功且无需该 generation 续行的 step 按规则 6 正常续行 | `failed` / `GENERATION_REVOKED`（仅三合取分支派生，经 §3.1.1 `fail_session` 第 (1) 类来源） | [LATER] |

- 非终态 code 规则（行 464，逐字）：`planned` / `ready` / `waiting_effect` / `cancel_requested` 的 `outcome_code` 为 NULL；`failed_retryable` 与 `blocked_unknown_effect` 虽非终态，按上表保留派生 code。
- session 聚合完整性（行 464 摘录）：规则 1–6 仅对唯一活跃 step（`active_step_id` 指向；terminal session 上唯一非终态 drain step 由 `drain_step_id` 定位——其收束事务引用同一聚合矩阵派生 step 状态、但 session 终态恒不变）求值并即时派生 session 转移，不存在跨多个非终态 step 的组合归并。不存在无 effect 的持久化 planned step（§3.1 `create_step` 与初始 decision seal 同事务发布）。`failed_terminal` step 与 pending step 不可能同时非终态。已终态 step 不参与转移判定，仅按既有优先级贡献最终 code 聚合。全部已终态 step 成功时按 turn 闭合状态互斥二分：turn 未闭合 → session 目标 `ready`，coordinator 按 §3.1 create_step guard 创建下一 decision step；turn 已闭合 → session MUST 经 §3.1.1 `finish_session` 收束为 `completed`，coordinator MUST NOT 创建同 turn 新 step（§3.1 create_step guard 稳定拒绝 `TURN_ALREADY_CLOSED`）。effect 取消 code 按 §3.2.2 闭合映射保留。

### 2.2 recovery 接管（对无结果 in-flight attempt 的原子流程）[LATER]
前置（行 472，逐字要点）：MUST 按下列原子流程在**单一事务**内执行（第 1–4 步一次提交，不存在两事务边界的持久化中间态）；不得仅凭 `session_fence` 变化判定外部 effect 未执行，session 接管本身不隐式撤销任何 job lease（§3.1.1）；接管结算以该 attempt 的 job lease 已过期或已被明确撤销为前置（第 2 步 guard）。

有序步骤：
1. **锁 session 行（recovery lease）→ 预锁集合冻结**：接管事务可能执行 attempt 分配时，预锁集合冻结为完整八位锁序前置全集 `session → grant/slice → generation → step → effect → attempt`（`turn_end_slot` 与 `compact` 两后位按序后置取得）。锁集 = 目标批次（active step 当前 sealed batch）中可能进入 cohort 的全部 effect 的 grant/slice 行全集（显式含已由普通 completion 结算为 eligible `failed_retryable` 的 sibling 的 grant，MUST NOT 只锁本次接管的 in-flight effect）+ 该批 effect 绑定 step 的 `catalog_generation` 行（共享读，与 seal/allocation 同款）。取得顺序固定：先无锁读取定位不可变关联（`grant_id` 为 effect 行不可变字段，无锁读取仅用于定位、不作为授权判定）→ 再按统一锁序取得完整锁集：grant/slice 多行按 `(workspace_id, slice_id, grant_id)` 升序，随后 generation 行（共享读），全部位于 session 行锁之后、step/effect/attempt 行锁之前；generation 行 MUST 在任何 step/effect/attempt 行锁之前取得（锁序倒置禁止；generation 已为 `failed` 时在既有锁序内返回/记录 `allocation_denied: GENERATION_REVOKED`、不分配）→ 按 §3.1.2 固定顺序锁 effect 行与其当前 attempt。
2. **CAS 校验 + job lease 有效性 guard（冻结）**：CAS 校验 attempt 仍处 `dispatch_started` 且 effect 级 `current_job_fence` 仍等于该 attempt 的 `dispatch_job_fence`（未被取代），并校验该 attempt 的 job lease 有效性——仅当 job lease 已过期或已被明确撤销时，才允许本事务 CAS 推进 `current_job_fence` 与接管结算：同一事务 CAS 单调推进 effect 级 `current_job_fence`（无论随后是否分配新 attempt 均照常推进），attempt 行 `dispatch_job_fence` 快照保持不变，并撤销该 attempt 的 job lease（置过期），使携带旧 fence 的 completion 经 envelope 校验必然 `rejected_stale`（code `STALE_JOB_FENCE`）。job lease 仍有效（未过期且未被明确撤销；session lease 过期不隐含 job lease 失效）→ 本事务 MUST 跳过该 attempt：不推进、不撤销、不执行第 3–4 步（effect/attempt 状态不变，in-flight 照旧）；recovery 可重复执行，扫描覆盖此等待态（活怞性经 lease TTL 闭合）。
3. **三个有序判定处理旧 attempt**（先来先决，MUST NOT 合并、跳过或互相替代；结果已知性与继续尝试资格两处 MUST 统一使用唯一证据分类函数）。旧 attempt 处置三种情形闭合：无绑定证据 → 转 `unknown_outcome` 待 repair；有绑定证据 → 按分类输出分支（仅 `known_success`/`known_failure`/`known_cancellation` 进入终局结算；`unknown` → 转 `unknown_outcome` 待 repair，MUST NOT 终局结算）；cohort 分配成功、被新 attempt 取代 → 旧 attempt 写入 `superseded_by_attempt_no`（指向新 attempt_no、保留其原有状态、不落新状态值）。
   - (a) 结果已知性（第一判定）：MUST 调用唯一证据分类函数分类。
   - (b) 结算（第二判定）：`known_success` / `known_cancellation` 照常结算（各自既有成功/取消收束路径），MUST NOT 进入重试判定；`unknown` → 旧 attempt 与 effect MUST 进入 `unknown_outcome`（code `UNKNOWN_AFTER_DISPATCH`），只能 `repair`，预算耗尽但结果未知仍为 `unknown_outcome`；`known_failure` 进入第三判定。
   - (c) `known_failure` 的处置（第三判定，四级固定顺序）：执行许可 gate → effect 级 `retry_eligible` 结算 → 批次判定前置（虚拟聚合）→ 仅虚拟聚合命中 §3.2.1 规则 5 且 cohort 授权与 generation 检查通过时分配新 attempt（经 `retry_cohort_allocation`，与普通 `retry_effect` 同一子操作）。
     - 执行许可 gate 语义仅为禁止继续执行：任一命中即 MUST NOT 执行 `dispatch_started -> ready`、MUST NOT 创建下一 attempt。gate 条件（闭合）：sticky cancel 已设置；session 已因 WORKSPACE_LOST fail-closed 或 `fail_session` 第 (3) 类 INFRA 收束终态失败；该 effect 所属批次已终态收束；`driver_mode=quiescing`。
     - gate 命中后终态去向二分（sticky cancel 优先判定）：sticky cancel 命中 → MUST 先走共享取消收束子操作：已知 retryable failure → 同事务转 `cancelled_after_dispatch`（code `CANCELLED_BY_REQUEST_AFTER_DISPATCH`，audit `RETRY_SUPPRESSED_BY_CANCEL`）；已知 terminal failure → 原样保留 `failed_terminal` 与原失败 code，父层按规则 3 cancel-wins 派生；成功 → 保留 `succeeded` 并记 `COMPLETED_AFTER_CANCEL` audit；已知取消（`known_cancellation`）→ 第五出口（AJ01）：effect 保持 `cancelled_after_dispatch` 与取消映射表已写下的 code（`CANCELLED_BY_PROVIDER` MUST NOT 改写为 `CANCELLED_BY_REQUEST_AFTER_DISPATCH`）、MUST NOT 另记 `COMPLETED_AFTER_CANCEL`/`RETRY_SUPPRESSED_BY_CANCEL`。非 sticky 关闭条件命中 → effect MUST 经受控边 `failed_retryable -> failed_terminal` 同事务落终态（保留原失败 code，audit `RETRY_STOPPED_BY_CLOSURE`，`retry_stop_reason` 按有序分类函数持久化）。
     - gate 通过后按共享谓词 `retry_eligible` 结算 effect 级失败类别：不满足 → 旧 attempt 与 effect 落 `failed_terminal`，同事务持久化 `retry_stop_reason`（该 `failed_terminal` 随即作为虚拟聚合的规则 4 输入）；满足 → effect 结算为 `failed_retryable`（非终态结算态）。
     - 批次判定前置（虚拟聚合）：MUST 以结算后的全批 effect 状态运行 §3.2.1 聚合判定（规则 1–6 及全部例外分支，与普通 completion 同一判定函数；同一接管事务结算多个 effect 时按全部结算后的全批状态一次求值）。(i) 命中规则 1/2 → 本事务只完成该 effect 的结算与状态落盘，MUST NOT 分配新 attempt；(ii) 命中规则 3/4 的终态收束条件 → 执行共享收束（残留 eligible `failed_retryable` 经受控边同事务关闭，`retry_stop_reason` 持久化为 `not_retry_eligible`），MUST NOT 分配新 attempt；(iii) 仅当虚拟聚合命中规则 5 → attempt 分配 MUST 调用 `retry_cohort_allocation`（虚拟聚合许可判定 → cohort 冻结（全集、不得子集）→ cohort 授权检查 → generation 检查（读第 1 步预锁的 generation 行、不补锁；已 `failed` 时记 `allocation_denied: GENERATION_REVOKED` 子结果、不分配，并按子操作第 4 步同款执行拒绝分配后的最终聚合——三合取命中即收束 `GENERATION_REVOKED`、未命中维持 `failed_retryable`）→ 同事务为 cohort 全部成员分配下一 attempt）。授权通过：旧 attempt 写入 `superseded_by_attempt_no`、cohort 全部 effect 回到 `ready`、新 attempt 行同一事务原子分配（`attempt_no+1`，复用原 `effect_id/request_hash/idempotency_key`，写入合法 envelope——新 `dispatch_job_fence` = 本接管事务第 2 步推进后的 `current_job_fence` 新值、当前 `driver`/`driver_epoch` 与 `session_fence`/`dispatch_session_fence`（`cancellation_epoch` 为 session 级控制字段、不冻结入 attempt 行——读 `sessions` 行）、status 为待派发）。分配后最终聚合按最终全批状态派生（两阶段显式声明：分配前虚拟聚合仅做许可判定；分配完成后 MUST 重新执行统一聚合）——cohort 全体已重新出现未决 effect，命中规则 2 → step 与 session 目标均落 `waiting_effect`，不存在「分配后按规则 5 派生 session `ready`」的出口。仅规则 5 命中但 cohort 授权拒绝（任一成员 grant 或所属 slice 已撤销）→ 不分配、不递增任何 `attempt_no`，cohort 全体维持 `failed_retryable`（与普通 `retry_effect` 的 `GRANT_DENIED` 零控制态修改同语义），最终聚合按未分配的全批状态派生（规则 5 → step `failed_retryable`、session `ready`），该 recovery 命令 receipt 整体 `outcome=accepted`，cohort 分配授权拒绝记录于 receipt `result_canonical` 的子结果字段 `allocation_denied: GRANT_DENIED`（方案 1 冻结：不是命令级拒绝、不写 `rejected_mismatch`；接管与旧 attempt 结算 MUST NOT 因该子结果回滚；规则 3/4 命中的收束同样照常，授权不阻塞收束）。
     - 显式声明：「旧 attempt 证据已知为 `known_failure` 且该 effect 满足 `retry_eligible`」不等价于「本批现在允许重试」——批次级条件（规则 5：全批无 terminal/cancel/unknown/pending sibling 且全部失败 effect 均为 eligible retryable）是独立前置，effect 级资格判定永远不能替代或短路批次级判定。
4. **单事务原子合并**：「旧 completion 必被 stale-reject」与「新 attempt 已分配且具备合法 envelope」由接管事务一次提交同时保证——CAS 推进 `current_job_fence`、撤销旧 job lease、旧 attempt 取代标记、（条件成立时）新 attempt 行原子分配与 effect 置 `ready` 不可拆分为多次提交，MUST NOT 先提交「effect `ready`、旧 attempt 已失效」再另行创建新 attempt，不存在「已 `ready` 而无新 attempt」的持久化窗口，也不存在旧 attempt 仍可接受 completion 而新 attempt 已存在的持久化状态。并发旧 completion 在 effect/attempt 行锁上排队，接管事务提交后按新 `current_job_fence` 全 envelope 校验 stale-reject（行锁内可见性即线性化点）；接管事务提交前 crash → 全部变更随事务回滚、不存在（原子性），无需扫描恢复，重启后按未接管原状态重新执行，新 attempt 行不重复分配（主键 `(effect_id, attempt_no)` 与唯一 `(effect_id, dispatch_job_fence)` 保证）。
5. **旧 completion 随后到达**：按 `EffectResult` 全 envelope 校验后返回 `rejected_stale` 稳定 receipt（§3.1.2）并写 `effect_audit` 完整 received binding；不改控制态、不追加语义事件。
6. **聚合顺序**：effect 只按当前最大 `attempt_no` 的已接受 completion 聚合；被取代 attempt（`superseded_by_attempt_no` 非 NULL）的迟到结果仅进 audit，MUST NOT 重新聚合或覆盖。`current_job_fence` 仍有效（仍等于该 attempt 的 `dispatch_job_fence`）的合法迟到 completion 不受本流程影响（§6 第 3 条）。

### 2.3 `FORCE_JOB_TAKEOVER`（受控内部操作完整命令合同，冻结）[LATER]
撤销仍有效 job lease 并立即接管（不等自然到期）只能经 operator 显式授权命令执行（属受控内部入口、非普通 recovery）。
- (a) 使用前提（唯一可用条件）：仅当普通 recovery 接管 guard 因该 attempt 的 job lease 仍有效（未过期且未被明确撤销）而跳过时方可使用（attempt 处 `dispatch_started`、effect 级 `current_job_fence` 未被取代、job lease 仍有效）；operator 显式授权是其独立授权基础，不复用、也不消费 recovery claim 的 lease 空缺/过期前提。
- (b) envelope（§3.1.2 统一命令合同叠加）：统一字段 `command_id`/`session_id`/`driver`/`driver_epoch`/`command_request_hash`/`session_fence` 之上另携带：目标 `effect_id`/`attempt_no`；expected effect 级 `current_job_fence`；expected job lease owner+expiry（该 attempt 绑定 job lease 的当前持有者与到期）；operator identity（canonical 表示，经 operator 控制面授权校验——复用 §2.1 grant 模型（subject_kind 按既有闭合集，如 driver）或既有 operator 显式命令通道；授权失败失败封闭拒绝）；force reason（canonical 字节，非空、长度上限冻结为 4096 字节，超限 envelope 校验层稳定拒绝）。
- (c) 固定 outcome（闭合四类；判定序冻结：目标 → stale → 前置 → 执行）：(1) 成功——按接管流程第 2–4 步同款原子语义执行，receipt 与 audit MUST 记录 operator identity 与 force reason；(2) 目标不存在或已终态（effect/attempt 无持久化行，或 attempt 非 `dispatch_started`、已结算或已被取代）→ `rejected_mismatch`（保留具体 code）；(3) job fence 或 job lease 已被取代（expected `current_job_fence` 或 expected lease owner/expiry 与行上当前值不符）→ `rejected_stale`；(4) 普通 guard 未禁止时使用（使用前提不满足）→ `rejected_mismatch`、闭合 code `FORCE_NOT_REQUIRED`（零控制态修改）。四类结局均按 §3.1.2 统一 receipt/binding 合同落盘（首占语义既有）。
- (d) 重放与多命令：同 `command_id` 重放按 §3.1.2 (1) 幂等返回原 receipt（accepted 或首次拒绝结局）；同 `(session_id, effect_id, attempt_no)` 上不同 operator/reason 的后续 force 请求是各自独立命令（各自新 `command_id`、各自 receipt/binding 首占；MUST NOT 复用前次 force 的 `command_id`——复用且键值不一致即按 §3.1.2 (2) 落 `IDEMPOTENCY_CONFLICT`；前次 force 成功后的后续 force 按 (2)/(3) 分类）。
- 普通 recovery 命令 MUST NOT 携带或触发该语义（携带 force 语义的请求在授权校验层拒绝）。

### 2.4 共享批次重试分配子操作 `retry_cohort_allocation`（两入口统一分配单位，冻结）[LATER]
普通 `retry_effect`（coordinator 路径）与 recovery 接管第 3(c) 步（recovery 路径）创建下一 attempt MUST 走同一条子操作，分配单位是**批次 cohort**（不是单个 effect），按固定顺序执行，MUST NOT 合并、跳过、互换或由任一入口私有实现。本段（行 500）仅到此处——固定顺序逐步合同在行 500 之后，规格仅部分给出。从本段其他处可确定的子操作要素：虚拟聚合许可判定 → cohort 冻结（该批全部 eligible `failed_retryable`，全集、不得子集——两入口统一分配单位）→ cohort 授权检查（§2.1 线性化点、§3.1.2 同锁序）→ generation 检查（§4 第 1 条第三道门）→ 同事务为 cohort 全部成员分配下一 attempt（各完成 effect 级 `failed_retryable -> ready` 与 `attempt_no+1`，复用原 `effect_id/request_hash/idempotency_key`；不再逐 effect 单独分配）。

### 2.5 本段引用、完整合同在范围之外的命令/子操作
- `complete_effect`（completion 入口）：本段冻结其结果已知性分类 MUST 调用唯一证据分类函数（见 §3.3.5）；worker 声明 `outcome` 不参与该分类（不可信声明、MUST NOT 作为判定输入）。
- `repair`（repair 入口）：同样 MUST 引用唯一证据分类函数；三入口（complete/recovery 第 3(a) 步/repair）分类 MUST 一致。`blocked_unknown_effect` 的唯一操作入口。
- `retry_effect`（普通重试）：MUST 经 `retry_cohort_allocation`；「session/lease/fence 保持进入前值」的零控制态修改合同（授权拒绝 `GRANT_DENIED` 场景）。
- `finish_session`（§3.1.1）：`completed` 唯一入口，guard 与聚合规则 6 共用同一 SQL 判定函数。
- 共享取消收束子操作（§3.2.2）：`request_cancel`、终局结算 completion、repair、reconcile 结果接收与 recovery 第 3 步已知结果处置均可触发——触发源限终局结算入口清单，矩阵 (iii)/(iv) 观测不触发；不依赖重放旧取消命令。
- `create_step` / seal（§3.1/§3.1.2）：step 创建与初始 decision seal 同事务发布；tools seal 同一事务写 `stage=tools`、`sealed_batch_no+1`、batch identity 与全部 tool effect。

## 3. 字节级算法

### 3.1 聚合优先级公式 [P0B-CORE]
`unknown > pending > cancel 收束（sticky cancel 或非本地 provider 取消）> failed_terminal > failed_retryable > success`（命中首条规则即决定控制终态，不存在实现自由裁量）。

### 3.2 共享谓词 `retry_eligible`（全文统一）[LATER]
逐字：`retry_eligible(effect) := retry budget 可用 AND retry_class ∈ {provider_idempotent, verifiable_no_effect} AND 对应证据已在控制态持久化`，其中 `retry budget 可用 ⟺ attempt_no < max_attempts`（effect 级、创建时冻结）。适用面（逐字）：`failed_retryable` 的普通 `retry_effect`、recovery 接管创建下一 attempt、§3.2.1 聚合规则 5 以及 `blocked_unknown_effect -> failed_retryable` 聚合补全出边 MUST 以该谓词为前提，MUST NOT 只检查预算。grant/slice 有效性**不是** `retry_eligible` 的谓词输入（MUST NOT 把授权塞进该谓词）——授权检查在 attempt 分配时点由 `retry_cohort_allocation` 按 §2.1 实时执行。`unsafe` 的无结果 attempt 接管后只能进入 `unknown_outcome`。

### 3.3 重试预算公式 [LATER]
逐字：`max_attempts` 是该 effect 创建时冻结的 effect 级重试预算上限（含首次 attempt，即 `max_attempts = 1 + 重试次数上限`），创建后不可变；预算耗尽 ⟺ 当前 attempt 权威行的 `attempt_no ≥ max_attempts`（权威判定只读 attempt 权威行与本行创建时冻结字段——parent 快照列 `attempt_no` 仅为派生展示、MUST NOT 作判定源）。同 step 的并行 sibling 各自独立持有并消耗自己的预算，MUST NOT 跨 effect 挤占、共享或挪用。

### 3.4 `retry_stop_reason` 唯一有序分类函数 + 分类输出缓存合同（R-01 冻结）[LATER]
闭合输出集（互斥）：`retry_stop_reason ∈ {budget_exhausted, first_attempt_failure, not_retry_eligible}`，按序首中即停、后项显式排除前项：
1. retry budget 已用尽（创建时冻结过重试预算——`max_attempts>1`——且 `attempt_no ≥ max_attempts`，均为 effect 级权威字段）→ `budget_exhausted`；
2. 否则，该 effect 从创建起即不具备重试资格（如 `retry_class=unsafe` 且无可验证「外部副作用未发生」证据、`max_attempts=1` 即创建时零重试预算）→ `first_attempt_failure`；
3. 否则——曾具备重试资格但当前证据/条件不满足（证据未在控制态持久化，或所处收束环境禁止新 attempt）→ `not_retry_eligible`。

约束：首试 `unsafe` 只归第 2 项，MUST NOT 同时落 `not_retry_eligible`；`max_attempts=1` 只归第 2 项，MUST NOT 按预算口径归入 `budget_exhausted`。分类函数的判定输入 MUST 仅为创建时持久化的 `retry_class`/`max_attempts` 与分类时已在控制态持久化的证据、收束环境事实，MUST NOT 以可变当前字段（含 step 级派生缓存 `retry_count`/`max_retries`、后续变更的聚合计数）反推历史。

分类输出缓存合同（`effect_requests.retry_stop_reason` 写入与复核）：凡把 effect 分类为 `failed_terminal` 的写路径事务（completion 分类、recovery 接管、repair 收束、受控关闭边与规则 4 的残留 sibling 收束）MUST **每次**按分类函数从权威输入**重算**分类值，并在同一事务 CAS 写入该列：列无值 → 写入重算值；列已有值 → 已有值仅用于幂等复核——一致 → 幂等返回、不重复写；不一致 → 按 `fail_session` 受控内部入口第 (3) 类以 `INFRA_PROTOCOL_VIOLATION` 受控处理：MUST NOT 静默采用已存旧值、MUST NOT 以重算值改写已存历史 reason（列保持原值，两侧值留存于 audit）。该列任何读取方 MUST NOT 以已存值替代重算语义；`retry_eligible` 求值、分类函数自身与聚合规则状态判定 MUST NOT 读该列；code 派生仅按输出投影消费（读已 CAS 验证的函数输出）。

code 派生映射（逐字）：`budget_exhausted` → `FAILED_RETRY_BUDGET_EXHAUSTED`、`not_retry_eligible` 与 `first_attempt_failure` → `FAILED_TERMINAL`，均经 §3.2.1 规则 4 按 reason 集合唯一派生。

### 3.5 唯一证据分类函数（单一定义，冻结）[P0B-CORE（success 路径在最小闭环内；判定表整体冻结实现）]
引用方（逐字）：`complete_effect`（completion 入口）、recovery 接管第 3(a) 步（recovery 入口）与 `repair`（repair 入口）三处 MUST 引用本函数，以其判定表与绑定要求为唯一证据门槛，MUST NOT 复述、收窄或另建第二套证据分类——同一证据经三入口分类 MUST 一致。

输入两类证据，**均 MUST 绑定当前 attempt**：
- provider 回执类证据 MUST 同时满足三项绑定方可采信：(1) provider 回执身份绑定（回执可关联到该 attempt 的 `provider_request_id` 或等价 provider 侧请求标识）；(2) payload 关联（回执内容与该 attempt 的 `request_hash`/`idempotency_key` 对应）；(3) 接收路径（证据经 provider→worker→控制态的既有 completion/audit 路径持久化，MUST NOT 由本地 timeout、崩溃或推测构造）。
- 「外部副作用未发生」证据 MUST 已在控制态持久化并绑定当前 attempt。

输出闭合集：`known_success | known_failure | known_cancellation | unknown`。判定表按序首中即停、后项显式排除前项：
1. provider 证实成功终局 → `known_success`；
2. provider 证实取消，或取消请求先于副作用生效的取消证据 → `known_cancellation`；
3. provider 给出确定性失败回执**且**（该回执本身或已持久化证据）证明外部副作用未发生 → `known_failure`；
4. provider 失败回执但外部副作用状态不明 → `unknown`——即使 `provider_idempotent`：幂等能力只保证重试安全，MUST NOT 作为结果已知性证据；
5. 其余所有情况 → `unknown`（兜底，穷尽闭合）——含「仅有绑定当前 attempt 的『外部副作用未发生』证据、而无任何 provider 终局回执」（无副作用证据只佐证重试安全、不证明结果已知）；含「无任何绑定当前 attempt 的证据」；无论预算状态如何，MUST NOT 把预算耗尽当作已知 terminal failure。

fence 失效与 attempt 被取代是两件事，MUST NOT 混淆：(i) `current_job_fence` 推进只撤销旧 worker 对该 attempt 的直接 completion 写入资格（stale-reject；attempt 行 `dispatch_job_fence` 不随之改写），不改变待 repair 的执行身份——未创建后继 attempt 时，绑定该 unknown attempt（该 effect 当前最大 `attempt_no` 的执行 attempt）自身的回执与副作用证据经授权 `repair` MUST 正常采信收束；(ii) 「旧 attempt 证据不可复用」限定为：把**其他执行 attempt**（已被更大 `attempt_no` 取代的 attempt）的回执或副作用证据冒充**当前执行 attempt** 的证据——此类证据仅按迟到结果规则 observational/audit 留存，MUST NOT 参与当前执行 attempt 的分类。预算与幂等状态只约束「是否允许再试」，不证明外部结果已知（§0 不变量 7）。

completion 侧分流（`complete_effect`，逐字）：函数输出 `known_failure` 时以 `retry_eligible` 为前提分流——满足方可分类 `failed_retryable`，不满足 MUST 分类 `failed_terminal`；函数输出 `unknown` 时 MUST 分类 `unknown_outcome`（code `UNKNOWN_AFTER_DISPATCH`），MUST NOT 标记为 retryable——不存在「有预算但不可安全重试」的悬空分类；`known_success`/`known_cancellation` 按既有成功/取消收束路径结算。

### 3.6 锁序（八位主锁序 + 后位）[LATER（recovery/allocation 路径）]
逐字：完整八位锁序前置全集 `session → grant/slice → generation → step → effect → attempt`（八位主锁序见 §3.1.2——`turn_end_slot` 与 `compact` 两后位按序后置取得：接管结算/收束触及 turn-end 槽位时，槽位行锁在 attempt 行锁之后、compact 行锁之前取得）。grant/slice 多行按 `(workspace_id, slice_id, grant_id)` 升序；generation 行（共享读）MUST 在任何 step/effect/attempt 行锁之前取得（与 §4 下线事务按同序串行化、防死锁环路）。

### 3.7 字节上限
- force reason：canonical 字节，非空、长度上限冻结为 **4096 字节**，超限 envelope 校验层稳定拒绝。[LATER]

## 4. 状态机

### 4.1 step 状态机（§3.2.1，闭合）[P0B-CORE（闭合集与 planned/waiting_effect/succeeded 主路径）；cancel/unknown/retry 转移 LATER]
状态集：`planned, ready, waiting_effect, failed_retryable, cancel_requested, blocked_unknown_effect, succeeded, failed_terminal, cancelled`；`stage ∈ {decision, tools, closed}`。

允许转移及守卫（表逐行摘录）：
- **`planned` → `waiting_effect`, `cancel_requested`, `failed_terminal`**：`waiting_effect` 仅经 §3.1.2 初始 decision seal（step 创建与 seal 同事务发布：`create_step` 受控子操作在本事务内创建 step、创建并密封唯一 LLM slot——`planned` 前置状态仅存在于该 seal 事务内，不存在已创建未 seal 的持久化 planned step，无「先创建、后 seal」的跨事务路径）；`cancel_requested` 仅由 sticky cancel 关闭未密封计划，取消收束在同一事务内经两跳完成（`planned -> cancel_requested -> cancelled`），不引入直达 `cancelled` 的出边；`failed_terminal` 仅经 §2.2 第 3 条 WORKSPACE_LOST failure-drain（(b)，`outcome_code=WORKSPACE_LOST`）；不存在 `planned -> ready` 出边——`ready` 仅表示已接受 decision result 后等待 §3.1.2 tools seal。
- **`ready` → `waiting_effect`, `cancel_requested`, `failed_terminal`**：进入 `waiting_effect` 仅经 §3.1.2 seal：同一事务写 `stage=tools`、`sealed_batch_no+1`、batch identity 与全部 tool effect；decision 完成返回 tool calls 时聚合回 `ready, stage=decision` 并冻结 `plan_hash`；不存在 `ready -> succeeded` 出边——成功终态化仅由满足聚合规则 6 的普通 completion 或 repair 聚合执行，来源状态可为 `waiting_effect` 或 `blocked_unknown_effect`（`decision_only=true` 的 decision completion/repair 在聚合时直接终态化 `succeeded`、不停留 `ready`）；`ready` 无 in-flight 批次、无可达 terminalize guard，唯一合法操作是 §3.1.2 tools seal 或被 sticky cancel 关闭；`failed_terminal` 仅经 WORKSPACE_LOST failure-drain（未密封 tools plan 作废）；`ready, stage=decision` 仅表示已接受包含 tools plan 的 decision result，MUST 先经 tools seal；`final_tools=true` 只在已密封且全部成功的 tools batch 上作为成功终态条件，不得由 `ready` 直接成功终态化。
- **`waiting_effect` → `ready`, `failed_retryable`, `blocked_unknown_effect`, `failed_terminal`, `cancel_requested`, `succeeded`, `cancelled`**：同一批次聚合；`ready` 仅表示 decision 结果可经 §3.1.2 seal 计划下一密封批次；`cancelled` 仅由同事务聚合命中规则 3 直达（sticky cancel 已请求或存在非本地收束的 provider 取消且无 unknown/pending，覆盖取消与最后一次 completion 在同一事务收束、无需 `cancel_requested` 中间态）；`failed_terminal` 另可经 WORKSPACE_LOST failure-drain（(b) 三分支：存在 in-flight pending 时不提前终态化——非 sticky cancel 下维持 `waiting_effect` 并标记 drain pending，sticky cancel 下转 `cancel_requested`；全部 in-flight effect 收束后落 (iii) `failed_terminal`、`outcome_code=WORKSPACE_LOST`）。
- **`failed_retryable` → `waiting_effect`, `failed_terminal`, `cancel_requested`, `cancelled`**：仅 `retry_effect`；`waiting_effect` 仅经 `retry_effect`：同一事务经 `retry_cohort_allocation` 为整批 cohort（该批全部满足 `retry_eligible` 的 `failed_retryable` effect，全集、不得子集）各完成 effect 级 `failed_retryable -> ready` 与 `attempt_no+1`，step 随所在批次重新出现未决 effect 而回到 `waiting_effect`；不存在 `failed_retryable -> ready` 出边——effect 级 `ready` 不得映射为 step 级 `ready`（§3.2.2 状态表独立）；retry MUST 经 `retry_cohort_allocation`（批次前置：虚拟聚合命中规则 5 且 cohort 授权检查通过；effect 级资格是成员条件、不是分配充分条件）；成员资格不满足（含 retry budget 耗尽）时所属批次按聚合矩阵 terminal failure 收束，effect MUST 同事务经受控边 `failed_retryable -> failed_terminal` 落终态（保留原失败 code，audit 另记 `RETRY_STOPPED_BY_CLOSURE`），派生 code 由 `retry_stop_reason` 唯一决定；sticky cancel 下由共享取消收束子操作收束为 `cancelled`（effect code `CANCELLED_BY_REQUEST_AFTER_DISPATCH`、audit `RETRY_SUPPRESSED_BY_CANCEL`），不得 retry；provider-cancel 收束、规则 4 批次关闭（含纯预算耗尽批次）与 WORKSPACE_LOST drain 下同样经受控边原子收束、MUST NOT 创建新 attempt。
- **`cancel_requested` → `waiting_effect`, `cancelled`, `blocked_unknown_effect`, `failed_terminal`**：sticky cancel 后按聚合矩阵收束（cancel-wins，控制终态只能是 `cancelled` 或经 unknown 的 `blocked_unknown_effect`）；pending 时保持取消等待（规则 2 sticky 分支），不得创建新 effect 或 retry；`failed_terminal` 仅经 WORKSPACE_LOST failure-drain 三分支。
- **`blocked_unknown_effect` → `ready`, `waiting_effect`, `cancel_requested`, `failed_retryable`, `succeeded`, `failed_terminal`, `cancelled`**：仅 `repair`，且 effect 级只能落到 `succeeded | failed_terminal | cancelled_after_dispatch` 对应终态；`ready` 是受控恢复出边：仅当 `repair` 将全部未决 unknown effect 以已证实证据收束为终态、且唯一 decision effect 被证实 `succeeded`、其 repair 持久化了 `decision_result_identity` 与规范化 tools plan（含 `final_tools=true`）时，step 按规则 6 聚合至 `ready, stage=decision`（冻结 `plan_hash`）；`decision_only=true` 的 decision repair 成功则直接聚合 `succeeded`；兄弟仍有 pending 时：非 sticky cancel 下 `waiting_effect`、sticky cancel 下按规则 2 为 `cancel_requested`；`failed_retryable` 是聚合补全出边：仅当 `repair` 清除该批次最后一个 unknown、同事务重新聚合命中规则 5（剩余 retryable sibling 满足 `retry_eligible`）时进入，该转移 MUST NOT 为任何已被 repair 收束的 effect 创建新 attempt；`failed_terminal` 另含 WORKSPACE_LOST 下 repair 收束后的 drain（repair 证实失败时 effect 仍持久化 `retry_stop_reason`，step 层 code 被 `WORKSPACE_LOST` 覆盖）；「永不回到 `ready`、永不产生新 attempt」限定 effect 级——step 级 `ready` 恢复出边不创建任何 effect 新 attempt、不重放旧 effect。
- **terminal（`succeeded`, `failed_terminal`, `cancelled`）**：无出边；仅允许 audit 与 receipt 重放（只读）；session 级 terminal 例外操作按 §3.1.1 terminal 子协议矩阵（五类 × (a)–(e)）裁定——矩阵 (b) 类 failure-drain 收束作用于该 session 的非终态（drain-pending）step，已终态 step 终态与 `outcome_code` 不变、不参与转移判定。
- **`failed_terminal` 出边 guard 来源统一扩展（行 431）**：除 WORKSPACE_LOST failure-drain 外，另含 §4 generation 强制下线（`active → failed`）drain——同款三分支语义（存在未决 unknown 的 step 维持 `blocked_unknown_effect` 待 repair 收束；存在 in-flight pending 的 step 停留 `waiting_effect`/`cancel_requested`（drain pending）允许完成；两者皆无、因 failed generation 无法续行、且无法经既有聚合规则（规则 3/4/5、取消收束）终态化的未完成 step 落 `failed_terminal`、`outcome_code=GENERATION_REVOKED`——能经既有规则终态化时终态与 code 按既有规则派生、MUST NOT 被 `GENERATION_REVOKED` 覆盖（§4 第 5 条三合取））；`planned`/`ready` 的未密封计划作废与 §2.2 第 3 条 (a) 同款（已接受 decision result 保留 audit，MUST NOT 创建 tools effect）；各状态行内「仅经 WORKSPACE_LOST」的限定同步读作「WORKSPACE_LOST 或 §4 generation 强制下线」，`outcome_code` 分别为 `WORKSPACE_LOST` / `GENERATION_REVOKED`。

### 4.2 session 状态派生（聚合目标，非独立转移表——session 状态机在 §3.1.1）[P0B-CORE（ready/waiting_effect 派生与 finish_session 收束）]
- 聚合可达 session 目标：`waiting_effect`（规则 2）、`ready`（规则 5/6）、`blocked_unknown_effect`（规则 1）、`cancelled`（规则 3）、`failed`（规则 4 / WORKSPACE_LOST / INFRA / GENERATION_REVOKED）、`completed`（仅经 `finish_session`，聚合 MUST NOT 派生）。
- 单一活跃 step 模型：session 聚合遵循 §3.1，对全部可达状态是完整函数；规则 1–6 仅对唯一活跃 step（`active_step_id`；terminal session 上 `drain_step_id`）求值；terminal session 后 MUST NOT 创建新 step（§3.1 create_step guard）。
- session 因聚合离开 `claimed` 时，MUST 在同一事务撤销协调 lease 并递增 `session_fence`，使旧协调写入失败。
- session lease 与 effect/job lease 独立；session lease turnover 不得仅因当前 `session_fence` 不同而取消已跨 dispatch gate 的 job。
- session 级控制字段 `cancellation_epoch` 读 `sessions` 行权威值（envelope 校验同）。

### 4.3 effect 状态（本段引用；完整闭合状态表在 §3.2.2 后段「状态表独立」处，超出本抽取范围——规格仅部分给出）
本段出现的 effect 级状态/标记：`ready`、`dispatch_started`、`unknown_outcome`、`failed_retryable`、`failed_terminal`、`cancelled_after_dispatch`、`succeeded`。受控边（逐字）：`failed_retryable -> failed_terminal`（受控关闭边：保留原失败 code，audit `RETRY_STOPPED_BY_CLOSURE`）。派发门：`ready -> dispatch_started`（同事务递增 `dispatch_count`）。effect 级取消 code 闭合映射引用 `CANCELLED_BY_PROVIDER`、`CANCELLED_BY_REQUEST_AFTER_DISPATCH`。effect 级 `unknown_outcome` 出口只有 §3.2.2 的三个终态（succeeded | failed_terminal | cancelled_after_dispatch 对应终态）。

### 4.4 attempt 状态/标记（`effect_attempts`，本段部分给出）
- 状态：`dispatch_started`（in-flight）；被取代 = 存在后继 attempt（持久化即 `superseded_by_attempt_no` 非 NULL，保留其原有状态、不落新状态值）。
- 「当前 attempt」= 该 effect 最大 `attempt_no` 的 attempt 行（由主键 `(effect_id, attempt_no)` 唯一派生，无需独立指针列）。
- 取代语义：旧 attempt 的证据自此属「旧 attempt 证据不可复用」域、迟到 completion 只进 audit。

### 4.5 双表权威性冻结与判定读取规则（字段权威性拆分，逐字段冻结）[P0B-CORE]
字段权威归属 = attempt 执行快照 + effect 不可变元数据 + effect 控制字段 + session 控制字段四源，parent 展示快照仅显示：
1. effect 级不可变元数据（`effect_requests` 行权威，创建时冻结）：`retry_class`、`max_attempts`、`request_hash`、`idempotency_key`、`execution_mode`、`driver`/`driver_epoch`。
2. attempt 执行权威（执行快照，`effect_attempts` 行）：`attempt_no`、`driver`、`driver_epoch`、`session_fence`、`dispatch_session_fence`、`dispatch_job_fence`（不可变执行快照）、`status`、`result_hash`、`dispatched_at`、`provider_request_id`（随执行结算更新）、`superseded_by_attempt_no`（取代标记，非判定输入）。
3. effect 级控制字段（`effect_requests` 行内可变控制态）：`current_job_fence`、`dispatch_count`、`lease_owner`/`lease_until`、`retry_stop_reason`（分类输出列/可验证缓存，显式移出判定输入）。
4. session 级控制字段（`sessions` 行）：`cancellation_epoch`。

判定读取规则（两读取集清单，作用域冻结）：
- **清单 A——completion/recovery/repair 读取集（effect 级判定）**：envelope 校验、结果已知性分类（唯一证据分类函数）、`retry_eligible` 求值与 effect 终态结算 MUST 且仅读取：当前 attempt 的权威执行字段 + effect 级不可变元数据权威字段 + effect 级控制字段（`current_job_fence`/`dispatch_count`/`lease_owner`/`lease_until`；`retry_stop_reason` 显式移出）+ session 级控制字段（`cancellation_epoch`，读 `sessions` 行）。
- **清单 B——step/session 聚合读取集（聚合状态机求值）**：§3.2.1 聚合规则 1–6 的状态判定、driver mode 判定（§3.1.1 begin_switch 安全点 guard 与 finish_switch 屏障）、failure-drain 的合法读取集合 = 清单 A 全部来源，另含：`steps` 行（`status`/`stage`/`plan_hash` 与 decision 标记 `decision_only`/`final_tools`、聚合计数列）、sealed batch manifest 与 slot 成员、已接受 decision result identity、step/job 绑定的 generation 状态（`catalog_generation`）、failure-drain 控制事实（`drain_step_id`、sticky cancel latch、terminal session 终态与 `failure_code`）。
- 两清单均 MUST NOT 以 parent 的派生执行快照或任何展示副本替代权威来源；code 派生对 `retry_stop_reason` 集合的消费是输出投影、不是状态判定输入。
- 同事务读取-更新顺序冻结：锁内先读两类权威字段（当前 attempt 权威执行字段 + effect 级不可变元数据）→ CAS 更新 attempt 权威行 → 同一事务同步 parent 派生执行快照与 effect 级分类字段（`retry_stop_reason` 按缓存合同每次重算写入，非快照复制）；stale completion（envelope 校验失败或 attempt 已被取代）只写 receipt/audit，MUST NOT 更新 parent 快照或任何 attempt 行；recovery 接管事务自身在推进 `current_job_fence` 后对旧 attempt 的结算/终局标记是权威写入，不经该等值验收（其门槛是接管第 3 步证据绑定与分类，证据归属按 `dispatch_job_fence`）。

## 5. P0B 相关性标注

### [P0B-CORE]（最小闭环必需）
- `steps` 表与 status/stage 闭合集、`plan_hash` 冻结规则、单活跃 step 部分唯一约束。
- `effect_requests` 表核心列（含 `execution_mode` NOT NULL CHECK、`current_job_fence`、`dispatch_count` 派发门递增）与 effect 级不可变元数据冻结。
- `effect_attempts` 首个 attempt 行（seal 事务内同事务创建唯一首个 attempt、`attempt_no=1`）与主键/唯一约束。
- 聚合优先级公式与规则 2（waiting_effect）、规则 6（成功/decision_only/final_tools/turn 续行/finish_session 共用 SQL 判定函数/离开 claimed 撤 lease 递增 `session_fence`）。
- 派生表 `SUCCEEDED` 行；非终态 code NULL 规则。
- 唯一证据分类函数（known_success 路径为闭环「成功证据分类」一环；判定表整体冻结）。
- job fence 双字段拆分与 stale completion 拒绝（`current_job_fence` 唯一权威、`STALE_JOB_FENCE`、外部 completion UPDATE 的 CAS 条件、迟到 completion `rejected_stale` + audit）。
- `execution_mode` 权威列 N05 + 副本等值强制 O06（创建等值校验在 seal 内发生）。
- 双表权威性冻结与清单 A 读取集（completion envelope 校验读 attempt 权威值）。
- 固定 `dispatch_ordinal`；空 batch 不得成功关闭。
- Conformance 1 相关持久化断言落点：不存在持久化 planned step（无 planned-无-effect）、发布即 ready、append 幂等与 seq 无洞（事件侧，本段提供状态侧输入）。

### [LATER]（完整抽取、后续里程碑）
- 聚合规则 1（unknown/blocked）、3（cancel 收束全部 code 族）、4（批次关闭 + `retry_stop_reason` 集合派生）、5（failed_retryable）；`cancel_requested`/`blocked_unknown_effect`/`failed_retryable` 状态的进入与出边。
- sticky cancel / 共享取消收束子操作 / `CANCELLED_BY_REQUEST(_AFTER_DISPATCH)` / `CANCELLED_BY_PROVIDER` / `FAILED_TERMINAL_CANCELLED` / `FAILED_TERMINAL_PROVIDER_CANCELLED` / `COMPLETED_AFTER_CANCEL` / `RETRY_SUPPRESSED_BY_CANCEL`。
- `retry_effect` / `retry_cohort_allocation` / `retry_eligible` / `retry_stop_reason` 有序分类函数与 R-01 缓存合同 / `FAILED_RETRYABLE` / `FAILED_TERMINAL` / `FAILED_RETRY_BUDGET_EXHAUSTED`。
- `repair` 与 `blocked_unknown_effect` 恢复出边 / `decision_result_identity`。
- recovery 接管原子流程全六步（八位锁序、job lease guard、三判定、虚拟聚合两阶段、superseded 标记）。
- `FORCE_JOB_TAKEOVER` 完整合同（含 4096 字节 force reason 上限、`FORCE_NOT_REQUIRED`、`IDEMPOTENCY_CONFLICT` 重放规则）。
- WORKSPACE_LOST failure-drain 三分支、`fail_session` INFRA（`INFRA_ASSEMBLY_FAILED`/`INFRA_PROTOCOL_VIOLATION`）收束、§4 generation 强制下线 `GENERATION_REVOKED` 三合取 drain。
- job lease（`lease_owner`/`lease_until`）与 `effect_audit` 的 retry/取消审计族；`catalog_generation` 预锁。
