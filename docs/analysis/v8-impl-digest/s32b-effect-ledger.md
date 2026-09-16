# s32b-effect-ledger — §3.2 中段：effect ledger、effect_attempts、双 fence、状态闭合

> 来源：`/Users/wxl/Projects/pg-agent/docs/designs/v8-dev.md` 第 501–600 行（冻结合同，逐字抽取）。
> 本段覆盖：共享批次重试分配子操作（retry_cohort_allocation）、`retry_effect`、batch slot 不可变、effect 状态闭合（九值集）、取消/未知 code 闭合映射、共享取消收束子操作（shared_cancel_closure）、`failed_retryable` 闭合出口、`repair`（unknown 出口）、**effect_attempts 完整 DDL**、dispatch 派发门、`EffectDescriptor`/`EffectResult` ABI、`EffectResult.outcome` 声明权威、LLM 流式流完整性 grammar（stream_complete 矩阵 + stream_progress 状态门 + observation receipt 合同）、`complete_effect` 两层验证/四步序、**effect_audit DDL（截至 600 行，联合 CHECK 截断）**。

---

## 1. 数据库表（完整清单）

### 1.1 `effect_attempts` — attempt 权威表 [P0B-CORE：表 DDL 与首个 attempt 路径；superseded 写入/后继分配语义 LATER]

完整列清单（逐字，规格 561 行）：

```
effect_attempts(effect_id, attempt_no, session_id, step_id, driver, driver_epoch,
  session_fence, dispatch_session_fence, dispatch_job_fence, request_hash,
  idempotency_key, execution_mode, status, superseded_by_attempt_no,
  dispatched_at, provider_request_id, result_hash, created_at, completed_at)
```

- 主键：`(effect_id, attempt_no)`
- 唯一约束：`(effect_id, dispatch_job_fence)`
- 两者共同「保证重放不重复分配」（505 行）。

列级约束（逐字，数据库级强制，依赖 PG ≥ 15）：
- `effect_id`/`session_id`/`step_id` NOT NULL；归属一致由**复合外键**（或等效数据库约束）强制——`(effect_id, session_id, step_id)` 引用 `effect_requests` 同名唯一列组，跨 effect-session-step 归属的 attempt 行被数据库拒绝。
- `attempt_no` NOT NULL CHECK (`attempt_no >= 1`)（零/负 attempt 拒绝）。
- `dispatch_job_fence` NOT NULL（空 fence 拒绝）。注记（逐字）：首个 attempt 创建与 cohort 后继分配时 `dispatch_job_fence` = 同事务推进后的 effect 级 `current_job_fence`（同事务初始化、同值冻结，双 fence 拆分），此后仅随新 attempt 分配单调递增、永不回退，不存在空 fence 持久化窗口。
- `driver`/`driver_epoch`/`session_fence`/`dispatch_session_fence` NOT NULL。
- `execution_mode` NOT NULL CHECK (execution_mode IN ('streaming','non_streaming'))——effect 行权威列的同值冻结副本，非判定权威（N05）。
- `status` NOT NULL CHECK (`status` IN (九值集——见 §4 状态机；非法 status 值拒绝)。
- `superseded_by_attempt_no` 可 NULL；非 NULL 时 CHECK (`superseded_by_attempt_no > attempt_no`)；且受**延迟自引用外键**约束：`(effect_id, superseded_by_attempt_no)` 外键引用同表 `(effect_id, attempt_no)`（`DEFERRABLE INITIALLY DEFERRED`——同事务提交时校验：分配事务先写旧 attempt 取代标记、后插入后继 attempt 行的次序合法）。指向同 effect 更大 `attempt_no` 的真实后继执行 attempt；跨 effect 后继被复合外键拒绝。

不可变性保护（触发器或受保护写函数，数据库级强制）：
- `superseded_by_attempt_no` 写入路径受限定：仅可由 `retry_cohort_allocation` 分配事务（两入口）同事务一次性写入，写入后禁止一切 UPDATE/清空。
- **attempt 冻结字段禁止 UPDATE**——创建时快照列 `driver`/`driver_epoch`/`session_fence`/`dispatch_session_fence`/`dispatch_job_fence`/`execution_mode`（同值副本，N05——列入冻结快照列保护清单）创建后禁止 UPDATE（触发器或等效数据库级强制）；`status`/`result_hash`/`dispatched_at`/`provider_request_id`/`completed_at` 等执行权威字段按既有合同随结算更新，不受此限。

行创建路径（闭合，两路且仅两路）：
1. **首个 attempt（`attempt_no=1`）** [P0B-CORE]：仅经 seal 事务成员创建路径（§3.1.2 `create_effect_in_seal`：初始 decision seal 的唯一 LLM slot 与 tools seal 的全部 tool effect，同事务创建），冻结初始 fence/envelope 必要字段——`dispatch_job_fence`（初值即同事务新分配并写入 effect 级 `current_job_fence` 的 fence 值，两者同值冻结，双 fence 拆分）、`driver`/`driver_epoch` 与 `session_fence`/`dispatch_session_fence`（创建 attempt 时冻结的执行快照，双表权威性冻结——envelope 校验读 attempt 行权威值）、`request_hash`/`idempotency_key` 等 §3.2.2 既有 ABI 字段，status 为待派发。**不存在其他首个 attempt 创建入口。**
2. **后继 attempt（`attempt_no>1`）** [LATER]：仅经共享批次重试分配子操作 `retry_cohort_allocation` 的两入口（普通 `retry_effect` 与本节 recovery 接管第 3(c) 步）分配（详见 §2.1）。

每行是其所标单次执行 attempt 的唯一权威状态（双表权威性冻结）；每条分配/结算路径 MUST 在同一事务同步 parent 快照。

### 1.2 `effect_audit` — 拒绝/审计表 [P0B-CORE：基础列（结构层拒绝路径要求的最小 expected/received 元组）；内部子操作三列 LATER]

完整列清单（逐字，规格 571–592 行）：

```text
effect_audit(
  audit_id, created_at, reason, command_id, result_hash, result_fingerprint,
  result_parse_path, raw_invalid_class, binding_invalid_class,
  session_id, step_id, effect_id, attempt_no,
  received_session_id, received_step_id, received_effect_id, received_attempt_no,
  expected_driver,                 received_driver,
  expected_driver_epoch,           received_driver_epoch,
  expected_dispatch_session_fence, received_dispatch_session_fence,
  expected_job_fence,              received_job_fence,
  -- expected 侧验收权威为 effect 级 current_job_fence（双 fence 拆分，§3.2.2）；received 为 worker 回报值
  expected_request_hash,           received_request_hash,
  expected_idempotency_key_hash,   received_idempotency_key_hash,
  received_binding_raw,
  received_result_raw,
  audit_context_session_id NOT NULL,  -- 取自已授权命令调用上下文，MUST NOT 取自 received binding 的不可信字段
  internal_op_kind,   -- NULL=普通 completion 路径审计行；非 NULL=effect 域内部子操作行（三列全有全无，联合 CHECK，Q05）
  parent_command_id,  -- 内部子操作行 MUST 非 NULL（= 触发该子操作的父命令 command_id）
  internal_op_ordinal,-- 父命令事务内 ordinal（同 §3.1.2 分配规则、不可变）；内部子操作行 MUST 非 NULL 且 >= 0
  audit_key_kind, audit_key_value
)
```

唯一约束（逐字）：
```
UNIQUE NULLS NOT DISTINCT (audit_context_session_id, effect_id, attempt_no,
  audit_key_kind, audit_key_value, result_fingerprint, reason,
  internal_op_kind, parent_command_id, internal_op_ordinal)
```

列级约束（逐字，数据库级强制，依赖 PG ≥ 15）：
- `audit_key_kind` NOT NULL CHECK (audit_key_kind IN ('canonical_binding','malformed_binding','invalid_binding'))
- `audit_key_value` NOT NULL；`result_fingerprint` NOT NULL
- `result_parse_path` NOT NULL CHECK (result_parse_path IN ('complete','raw_invalid','empty'))
- `reason` NOT NULL
- `internal_op_kind` 可 NULL CHECK (internal_op_kind IN ('failure_drain','shared_cancel_closure','compact_terminal_abort','infra_closure','generation_revocation_drain'))——五值闭合集（§3.1.2 内部子操作闭合集）；NULL=普通 completion 路径审计行、非 NULL=内部子操作行（该类行 MUST 非 NULL）
- `parent_command_id` / `internal_op_ordinal` 均可 NULL（NULL=普通行）；内部子操作行两列 MUST 非 NULL 且 `audit_context_session_id` = 该子操作的 parent_session_id（父命令作用域三列同源）；`internal_op_ordinal` CHECK (>= 0)、不可变
- 内部三列联合 CHECK（数据库级强制，Q05——三列全有全无）：`CHECK ((internal_op_kind IS NULL AND parent_command_id IS NULL …` —— **本 DDL 在第 600 行截断，联合 CHECK 完整式与后续列见下一段规格（>600 行），由相邻 digest 承接**。

### 1.3 `effect_requests` — effect parent 表（本段部分给出）[P0B-CORE]

规格仅部分给出（完整 DDL 在 §3.2 前段），本段明确点名的列与约束：
- `status`：parent 派生执行快照列——快照域照旧，其列级 CHECK 值域与 attempt 权威行同域（同一九值集，见 §4）、非判定源（双表权威性冻结，542 行）。
- `execution_mode`：effect 行权威列（NOT NULL 闭合集 CHECK、创建时写入、此后不可变，N05）——**流完整性适用域的唯一判定权威**（见 §3）。
- `current_job_fence`：effect 级控制字段——**completion 验收 stale 判定唯一权威**（双 fence 拆分；envelope 比对时读 effect 行）。
- 复合唯一列组 `(effect_id, session_id, step_id)`（被 `effect_attempts` 复合外键引用）。
- batch slot 不可变约束（511 行，逐字）：`UNIQUE(session_id, step_id, batch_id, dispatch_ordinal)`；tool effect 另受 `UNIQUE(session_id, batch_id, tool_call_id)` 约束。seal 后 MUST NOT 补建、删除 slot 或改变成员与顺序。

### 1.4 `sessions`（本段部分给出）
- `cancellation_epoch`：session 级控制字段（`sessions` 行权威）——不冻结入 attempt 行；Descriptor 回显与验收判定均读 `sessions` 行（565 行）。

---

## 2. 命令与流程

### 2.1 共享批次重试分配子操作 `retry_cohort_allocation` [LATER]

两入口共用：普通 `retry_effect` 与本节 recovery 接管第 3(c) 步。六步（逐条，502–507 行）：

1. **虚拟聚合（许可判定）**：对当前全批结算态运行一次批次判定前置虚拟聚合（§3.2.1 规则 1–6 及全部例外分支，与普通 completion 同一判定函数）；本阶段聚合仅做许可判定（是否允许创建下一 attempt），不派生、不写任何 step/session 控制态；虚拟聚合的例外分支集显式排除 §4 GENERATION_REVOKED 三合取（无法续行 × 无法经既有聚合规则终态化 × 无未决 unknown/pending）——虚拟聚合不执行 generation 收束，该收束仅由第 6 步分配后最终聚合、第 4 步拒绝分配后的最终聚合与 §4 下线 drain 执行。
2. **cohort 冻结**：仅当虚拟聚合命中规则 5 时，冻结本次 eligible retry cohort = 该批全部满足共享谓词 `retry_eligible` 的 `failed_retryable` effect（全集，MUST NOT 子集化——不得只重试部分 sibling，不存在逐 effect 分配变体）。
3. **cohort 授权检查（分配时点，两入口共用）**：MUST 按 §2.1 授权线性化点在同一事务实时重验 cohort 全部成员的 grant/slice 有效性（§0 不变量 17 同源检查），锁序遵守 §3.1.2 固定顺序——grant/slice 行锁位于 session 行锁之后、generation/step/effect/attempt 行锁之前；多行按 `(workspace_id, slice_id, grant_id)` 升序。任一成员 grant 或所属 slice 已撤销 → 整个子操作不分配（MUST NOT 部分分配/子集分配）：不创建任何新 attempt、不递增任何 `attempt_no`、不写派生缓存，cohort 全体维持 `failed_retryable`（与既有 `GRANT_DENIED` 零控制态修改同语义）；分配前已完成的旧 attempt 结算与规则 3/4 命中的收束照常进行（授权不阻塞收束）；grant 有效性 MUST NOT 塞进共享谓词 `retry_eligible`。拒绝对外表示按入口区分：普通 `retry_effect` 稳定拒绝 `GRANT_DENIED`；recovery 入口按接管流程第 3(c)(iii) 步（命令 receipt 整体 `accepted`，授权拒绝记于 `result_canonical` 子结果 `allocation_denied: GRANT_DENIED`，不写 `rejected_mismatch`）。
4. **generation 检查（与 seal/dispatch 同款第三道门）**：授权通过后，在统一锁序的 generation 锁位（grant/slice 行锁之后、step 行锁之前）锁定 cohort 成员所属 step 绑定的 `catalog_generation` 行（共享读；下线事务排他写；recovery 入口不在此位补锁——其接管事务已按完整八位预锁集先行取得）。同事务读取其状态：已为 `failed` → 整个子操作零分配稳定拒绝（闭合 code `GENERATION_REVOKED`，与 seal 门同语义）：不创建任何新 attempt、不递增任何 `attempt_no`、不写派生缓存，cohort 全体维持 `failed_retryable`。对外表示：普通 `retry_effect` 稳定拒绝（receipt `rejected_mismatch` 保留 code `GENERATION_REVOKED`）；recovery 入口记入 receipt `result_canonical` 子结果 `allocation_denied: GENERATION_REVOKED`（命令整体 `accepted`）。**拒绝分配后的最终聚合（generation 收束层，冻结）**：generation 拒绝（零分配）后，同事务 MUST 按未分配的全批状态执行最终聚合（与第 6 步同一判定函数，例外分支集含 §4 GENERATION_REVOKED 三合取）：命中三合取 → cohort 全体经本节受控边 `failed_retryable -> failed_terminal` 同事务收束（保留原失败 code，audit 另记 `RETRY_STOPPED_BY_CLOSURE` 与 `GENERATION_REVOKED` 上下文，`retry_stop_reason` 按有序分类函数持久化为 `not_retry_eligible`），step/session 按 §3.2.1 派生表 GENERATION_REVOKED 行收束——不永久保留 retryable（§3.1.2 拒绝规则第二显式例外）；未命中三合取 → cohort 维持 `failed_retryable`（收束由 §4 下线事务重扫描与既有聚合路径拥有）。下线与 allocation 按 generation 行锁线性化（先提交者赢）。`retired` generation 不受限。
5. **同事务分配**：generation 检查通过时，同一事务为 cohort 全部成员各分配下一 attempt（`attempt_no+1`，复用原 `effect_id/request_hash/idempotency_key`，写入合法 envelope：新分配 fence（同事务单调推进 effect 级 `current_job_fence` 至该新值，attempt 行冻结为其 `dispatch_job_fence`）、当前 `driver`/`driver_epoch` 与 `session_fence`/`dispatch_session_fence`（创建 attempt 时冻结的执行快照；`cancellation_epoch` 为 session 级控制字段、不冻结入 attempt 行——读 `sessions` 行）、`request_hash`/`idempotency_key` 等 §3.2.2 既有 ABI 字段，status 为待派发）；主键 `(effect_id, attempt_no)` 与唯一 `(effect_id, dispatch_job_fence)` 保证重放不重复分配；成员 effect 同事务转 `ready`；cohort 各成员被取代的当前（旧）attempt 行同事务写入 `superseded_by_attempt_no` = 其新分配的 `attempt_no`（两入口同款；旧 attempt 状态均保持不变、不落新终态；recovery 入口的接管流程第 4 步单事务原子合并不变）。
6. **分配后最终聚合**：MUST 按最终全批状态执行 §3.2.1 统一聚合（与普通 completion 同一判定函数）——cohort 全体已重新出现未决（待派发）effect，命中规则 2：step 与 session 目标均落 `waiting_effect`；不存在按规则 5 派生 session `ready` 的分配后出口（规则 5 判定仅存在于第 1 步许可阶段）。

### 2.2 `retry_effect` [LATER]

执行前置冻结为 step 级批次条件：目标 effect 处 `failed_retryable` 且满足 `retry_eligible`（cohort 成员资格），所属 step 处 `failed_retryable`，且该批按子操作第 1 步虚拟聚合命中 §3.2.1 规则 5（前置不满足 → 稳定拒绝 `rejected_mismatch`）。命中时 MUST 调用子操作为整批 cohort 分配。授权检查共用子操作第 3 步、generation 门共用第 4 步（覆盖 cohort 全体成员）：任一成员 grant 或所属 slice 已撤销 → MUST 稳定拒绝 `GRANT_DENIED`，仅写规定的 receipt 与 audit——cohort 全体成员 effect/step 保持 `failed_retryable`，session、lease、fence 均保持请求事务进入前的值——两种初始条件显式闭合（初始 `claimed` → 拒绝后仍 `claimed`，协调 lease 不隐式释放、`session_fence` 不递增；初始 `ready` → 保持 `ready`；coordinator MUST 经独立命令显式 yield 或合法取消/收束路径释放 lease，拒绝事务 MUST NOT 隐式释放 lease 或递增 fence；无新 attempt 故 effect 级 `current_job_fence` 亦不变），不创建新 attempt、不递增任何 `attempt_no`、不写派生缓存。授权拒绝（`GRANT_DENIED`）保持零控制态修改、MUST NOT 自行终态化或改写 code。step 绑定 generation 已 `failed` → 稳定拒绝（receipt `rejected_mismatch` 保留 code `GENERATION_REVOKED`），且同事务执行拒绝分配后的最终聚合（见 §2.1 第 4 步）。

### 2.3 `create_effect`（公开入口，replay/查重模式）[P0B-CORE]

MUST 校验：slot 所属 step、`batch_id` 为该 step 当前已 seal 的 batch、`dispatch_ordinal`（与 `tool_call_id`）落在该 batch 冻结的 slot manifest 内且 payload 与 seal 提交的 `plan_hash`/manifest 一致。创建走 CAS——slot 不存在则插入；已存在且 `request_hash` 一致则仅返回已有 effect；不一致 MUST `rejected_mismatch`。「`batch_id` 为该 step 当前已 seal 的 batch」前置仅约束公开 `create_effect`。

### 2.4 `create_effect_in_seal`（§3.1.2 受控子操作，构建模式）[P0B-CORE]

seal 事务内部对同一事务内 manifest 已冻结、sealed 标记尚未发布置位的 batch 创建成员（共用上述 slot 唯一约束与 manifest/payload 校验）；成员创建前 MUST 已通过该 seal 事务的 seal 授权阶段实时授权（§3.1.2）；事务末尾一次性置 sealed 后即落入不可变约束——两模式各据其时点，不构成前置循环。本路径是首个 attempt（`attempt_no=1`）的唯一创建入口（同事务冻结初始 fence/envelope 字段，status 待派发，发布即 ready）。

### 2.5 dispatch 派发门（`ready -> dispatch_started`）[P0B-CORE]

必须**在同一事务**检查：cancellation、compact、session/job fence、grant、handler readiness，以及 effect 所属 step/job 绑定的 `catalog_generation` 状态（§4 第 1 条）[LATER]。grant 检查 MUST 按 §2.1 授权线性化点实时重验当前撤销状态（§0 不变量 17），assemble manifest 快照不豁免本检查。generation 绑定为 `failed` 时 MUST 稳定拒绝派发（闭合 code `GENERATION_REVOKED`）、不进入 `dispatch_started` [LATER]；拒绝为只读，遵守 §3.1.2 拒绝规则：仅写 receipt（`rejected_mismatch`，保留 code `GENERATION_REVOKED`）与规定 audit，MUST NOT 修改任何控制态。`retired` generation 不受限。提交后才允许外部 IO。派发门绑定该已分配 attempt（首个与后继 attempt 同规），不存在「effect 已 `ready`（或 `attempt_no` 已推进）而对应 attempt 行不存在」的持久化窗口，**dispatch MUST NOT 补建任何 attempt 行**（P0B：dispatch 只绑定既有 attempt）。

### 2.6 `complete_effect`（两层验证 + 四步序）[P0B-CORE；observation/流式分流 LATER]

验证冻结为**两层验证、固定顺序**（先结构层、后语义层，MUST NOT 互换、跳过或合并）。**两入口共用序（冻结，X01）**：`complete_effect` 与 `reconcile` 的**结果接收子操作**两入口 MUST 共用本两层验证与下述四步序（同一证据经两入口 MUST 得到相同分类与相同矩阵结果）。**四步之后的分流按命令入口拆定（冻结，Y01）**：
1. 字段矩阵 (iii)/(iv) 形态（`stream_complete=false` 非终局 stream observation）**仅 `complete_effect`** → 按五款状态门唯一裁定（quiescing 不是五款之一、不阻观测）[LATER]；
2. `reconcile` 结果接收遇 (iii)/(iv) 形态 → MUST NOT 终局结算、MUST NOT 写 stream_progress/observation——固定拒绝闭合 code `OBSERVATION_WRONG_ENTRY`（receipt `rejected_mismatch` 保留该 code；零控制态修改、仅 receipt 与规定 audit）[LATER]；
3. 其余形态为**终局结算**——quiescing 下终局命令 `complete_effect` MUST 返回 `DRIVER_QUIESCING`、不结算（§3.1.1 quiescing 总规则「终局」限定，W01），终局结算仅经 `reconcile` 结果接收执行；active 态下两入口的终局结算照常执行 [LATER]。

**流事实判定四步序（冻结，W02）**：
- (i) 第 (1) 步结构层 payload schema **不含** `stream_complete` 字段矩阵（本步只含 canonical profile/ABI 类型校验）；
- (ii) 唯一证据分类函数求值（本节单一定义）；
- (iii) 仅当分类输出 `known_success` ∧ effect 行 `execution_mode='streaming'` 时套 grammar (0) 字段矩阵——两 reject 形态 → 零控制态拒绝（保留「结构层」称谓、显式位于证据分类之后，`complete_effect` 四步序第 (iii) 步，W02/O04）；
- (iv) 分类输出非 `known_success`（取消/失败/unknown）→ 不套矩阵（流事实字段的缺失/形态不构成 schema reject；所携字段值的域内合法性仍受第 (1) 步 canonical profile/ABI 值域校验约束；F3 豁免依据：按经认证证据类别 × 冻结执行模式）、按证据分类结果收束。
四步序唯一、MUST NOT 互换或跳过。

**第 (1) 步结构层**（P0B-CORE）——依次验证：
- transport 与命令结构；
- 身份（ABI、effect/session/step、driver/epoch、attempt_no、request_hash/idempotency_key）与 attempt envelope；
- pre-dispatch cancellation 仅接受数据库生成的取消结果（worker 不可伪造）；
- 其余 outcome 再验证 `dispatch_session_fence`、effect 级 `current_job_fence`、outcome 与 payload schema（含 §1.3 canonical profile 第 (1) 步 schema 校验拒绝；本步 payload schema 不含 `stream_complete` 字段矩阵；grammar 第 (3)/(4) 项的值域校验——计数负值/非整数/超界/`C≠N+1` 矛盾/零计数矛盾，属所携字段值的域内合法性校验——在本步适用、不依赖证据类别与执行模式）。

envelope 比对源（判定读取规则，四源）：`driver`/`driver_epoch`/`session_fence`/`dispatch_session_fence`/`attempt_no` 读 attempt 行执行快照；`current_job_fence` 读 effect 行控制字段；`cancellation_epoch` 读 `sessions` 行。

**结构层任一失败 → 稳定拒绝、零控制态修改**：completion 不被接受，effect 维持原状态等待收束，不得修改 control 或 semantic event，返回稳定 stale/mismatch 或 `REPAIR_REQUIRED`，仅在同一事务写 receipt 与 `effect_audit`（拒绝记录不构成控制态修改），最小字段为 expected/received 成对绑定元组（即 §1.2 effect_audit 的列清单）。

### 2.7 `repair`（unknown_outcome 唯一出口）[LATER]

- `unknown_outcome` 的所有出口只能由 `repair` 执行，且只能落到 `succeeded | failed_terminal | cancelled_after_dispatch`；普通 `complete_effect` 遇到 unknown 必须返回 `REPAIR_REQUIRED`。
- repair 提交的证据 MUST 经唯一证据分类函数分类并满足其当前执行 attempt 绑定要求（「旧 attempt 证据不可复用」限定为已被更大 `attempt_no` 取代的执行 attempt 的证据冒充当前执行 attempt 的证据——`current_job_fence` 推进不改变待 repair 的执行身份，绑定该 unknown attempt 自身的证据经授权 repair 正常采信）。
- 证据无法通过绑定要求（无可验证绑定证据），或证据绑定正确但经该函数分类输出仍为 `unknown`（如仅有绑定当前 attempt 的「外部副作用未发生」证据而无任何 provider 终局回执、或失败回执但外部副作用状态不明）→ 均 MUST 稳定拒绝 `REPAIR_EVIDENCE_REQUIRED` 且不修改控制态（unknown 保持不变），§3.3。
- repair 将 unknown 收束为 `failed_terminal` 时 MUST 在同一事务按全路径共用的有序分类函数持久化 `retry_stop_reason`（effect 级 repair 出口永不产生新 attempt，取值仍按函数第 1–3 项按序判定），code 按 §3.2.1 派生表唯一派生。
- repair 后必须在同一事务重新聚合全部 siblings；effect 级 `unknown_outcome` 永不 repair 为 effect 级 `ready`、永不产生新 attempt，禁止 timer retry（该限制限定 effect 级，与 §3.2.1 step 表的 step 级受控恢复出边不冲突）。
- repair 证实 decision effect `succeeded` 且其持久化 result 含 tool calls 时，step 级按 §3.2.1 聚合规则 6 聚合至 `ready, stage=decision` 供 §3.1.2 tools seal，effect 级仍不产生新 attempt、不重放旧 effect。

### 2.8 共享取消收束子操作 `shared_cancel_closure`（sticky latch 存在时的统一收束路径）[LATER]

五个出口（终局结算 completion 与 recovery 接管第 3 步 sticky 命中 MUST 走同一条收束路径）：
1. 已知 retryable failure → 同事务转 `cancelled_after_dispatch`（code `CANCELLED_BY_REQUEST_AFTER_DISPATCH`，audit 另记 `RETRY_SUPPRESSED_BY_CANCEL`）；
2. 已知 terminal failure → 原样保留 `failed_terminal` 与原失败 code，父层按 §3.2.1 聚合规则 3 cancel-wins 派生；
3. 成功 → 保留 `succeeded` 并记 `COMPLETED_AFTER_CANCEL` audit；
4. unknown → 照常 `blocked_unknown_effect`，repair 收束后仍回本子操作；
5. **已知取消（`known_cancellation`，第五出口——AJ01）**：分类输出 `known_cancellation` 的结果（provider 证实取消、或 repair 提交取消证据等既有取消证据形态）→ effect 保持 `cancelled_after_dispatch` 与取消映射表已写下的 code（`CANCELLED_BY_PROVIDER` MUST NOT 改写为 `CANCELLED_BY_REQUEST_AFTER_DISPATCH`——sticky latch 只改变父层派生，MUST NOT 改写既有取消事实的 effect code 出处）；MUST NOT 再写 `COMPLETED_AFTER_CANCEL`/`RETRY_SUPPRESSED_BY_CANCEL`（该两 audit 仅分别属于成功与被抑制 retryable 两类出口的写入点）。

父层仍按 §3.2.1 规则 3 sticky 优先派生 step/session。

**触发源收口（AG01）**：仅限终局结算入口清单（各自在同一事务内执行，MUST NOT 依赖重放旧取消命令）：
- (α) §3.2.2 四步后第 (3) 分支（终局结算）的 `complete_effect` 终局结算与 `reconcile` 结果接收结算（两入口）；
- (β) `request_cancel` 的已知结果处置（遍历对象限 **cancel 提交时仍非终态的已知结果**，AJ02——限定合同见 §3.3 三段式 (3)）；
- (γ) `repair` 的已知结果收束；
- (δ) recovery 接管第 3 步已知结果处置（(b) 结算与 (c) sticky 命中）。

矩阵 (iii)/(iv) 且五款状态门接受的观测（四步后第 (1) 分支——observation receipt `outcome=accepted` 亦不例外）MUST NOT 触发 `shared_cancel_closure`、MUST NOT 写 `COMPLETED_AFTER_CANCEL`/`RETRY_SUPPRESSED_BY_CANCEL`、MUST NOT 改 effect/step 终态（写集以 grammar (0)(iii) AF01 句为准）。

### 2.9 pre-dispatch 取消双表原子同步（冻结）[LATER]

三路径（`request_cancel` / §2.2 第 3 条 failure-drain / §4 第 3 条 generation drain）把 ready effect 转 `cancelled_before_dispatch` 时，其当前 attempt（最大 attempt_no 行）同事务转 `cancelled_before_dispatch`、parent 派生执行快照同事务同步（双表权威性冻结——两表一致、无单边中间态）。数据库内部取消路径、非 worker completion：不产生 completion 语义事件/receipt；迟到 worker completion 因 attempt 已终态（terminalization 后唯一允许操作为 audit/receipt 重放）被既有 envelope/mismatch 规则拒绝、仅写 receipt 与 effect_audit。seal 事务内的取消 = 整个 seal 零副作用拒绝（sticky cancel 等 seal CAS 拒绝条件命中时不发布任何成员），不存在事务内 planned 成员逐个转 cancelled_before_dispatch 的路径。

---

## 3. 字节级算法

### 3.1 双 fence 拆分 [P0B-CORE]

- effect 级 `current_job_fence`：控制字段，completion 验收 stale 判定**唯一权威**；首个 attempt 创建与 cohort 后继分配时同事务推进，此后仅随新 attempt 分配单调递增、永不回退。
- attempt 行 `dispatch_job_fence`：该 attempt 执行 fence 的不可变快照（绑定外部执行与证据；证据绑定与 attempt 归属按 attempt 行 `dispatch_job_fence`）。创建时 `dispatch_job_fence` = 同事务推进后的 effect 级 `current_job_fence`（同值冻结）。
- `EffectResult.job_fence` 在验收时与 effect 级 `current_job_fence` 匹配（stale 判定唯一权威）。
- `dispatch_session_fence`：attempt 创建时冻结的不可变 session fence 执行快照（attempt 行权威，envelope 校验读 attempt 行权威值）。

### 3.2 LLM 流式流完整性计数 ABI grammar（冻结公式）[LATER]

**适用域唯一判定权威**：effect 行 `execution_mode` 权威列（NOT NULL 闭合集 CHECK、创建事务写入、此后不可变，N05）；attempt 行与 `EffectDescriptor` 回显为同值副本、非判定源；MUST NOT 以 worker 声明 outcome、result 自报『非流式』或任何运行时声明决定适用性。

成功 result（唯一证据分类函数输出 `known_success`）另 MUST 携带 provider 流结束事实字段——`stream_complete` 标志与 `final_chunk_index`/`chunk_count`（二者其一或等价计数）。

**(0) `stream_complete` 字段矩阵（O04 冻结，五形态穷尽；套用位置冻结 W02——四步序第 (iii) 步，位于证据分类之后、计数判据 (1)–(7) 之前）**（「计数」= `final_chunk_index`/`chunk_count` 恰一在场、或并存且满足 `C=N+1`）：
- (i) `stream_complete=true` ∧ 计数 → **完整流**——(1)–(3) 收齐判据适用，等值断言按 §1.2 (a) 执行；
- (ii) `stream_complete` **缺失**（无论有无计数）→ **schema reject**（无论声明 outcome，F3）；
- (iii) `stream_complete=false` ∧ 计数完整 → **pending**——非终局 stream observation（独立观测，冻结，P04）；
- (iv) `stream_complete=false` ∧ 计数缺失 → **pending**（同 (iii)）；
- (v) `stream_complete=true` ∧ 无计数 → **schema reject**。

**(1)–(7) 计数判据（逐字）**：
- (1) `final_chunk_index = N` ⇔ 流收齐条件 = 该流已接受 chunk 的 index 集合**恰等于** {0..N}——统一集合判据（集合精确相等）：[0,N] 全部在场**且无任何已接受的额外 index（>N）**，缺任一 index 或存在额外 index 均未收齐；
- (2) `chunk_count = C` ⇔ 必须恰好 C 个已接受 chunk 且其 index 集合恰等于 {0..C-1}（最大 index = C-1 为该集合判据的推论——单表示与 (1) 同一集合判据）；
- (3) 两字段并存 MUST 满足 `C = N+1`，违反（任何 `C ≠ N+1` 形态，含零计数与 ≥1 的 `final_chunk_index` 并存）→ 结构层 payload schema reject（域内矛盾校验、不依赖证据类别，W02 注记；稳定拒绝、零控制态修改）；
- **额外 index 判据（独立流结束范围冲突判据，F4/L4-FINAL-04）**：流完整 ⟺ 已接受 index 集合恰等于 {0..N} ∧ `C=N+1`；存在超出已认证结束范围的已接受 index（>N——无论超前/迟到、无论 chunk 内容是否为空——空额外 chunk 同判据、不豁免）→ **直接记录 `CANONICALIZER_CONFLICT` 冲突事实**（判据 = 超出已认证结束范围这一事实本身，非由 final/chunk 全文等值失败推导——超范围即冲突，MUST NOT 执行等值验证）；全文等值验证仅在集合完整时执行；等值验证已完成后到达的额外 index → 冲突照记（迟到 chunk 照常接受为 observational 事件，范围检查独立记冲突——仅影响冲突审计事实与双层验收器布尔，不改业务终态）；
- (4) schema reject 值域（结构层，仅凭 result payload 可判定）：计数字段负值、非整数；`final_chunk_index` 超过其**收窄值域上界 `2^63-2`**（N04——`C=N+1` 最大 `2^63-1`，与 `chunk_count` 上界及 §1.3 tagged integer 范围一致；三表示等价由此恢复：`final_chunk_index=N ≤ 2^63-2` ⇔ `chunk_count=C=N+1 ≤ 2^63-1`）；`chunk_count` 超过 `2^63-1`；`stream_complete=true` 且计数为零（`chunk_count=0`——`chunk_count=0` 单独出现同样拒绝）。矩阵两 reject 形态（(0)(ii)/(0)(v)）不入本值域清单（经四步序第 (iii) 步套用）；
- (5) 计数与已收 chunk 不一致且缺 index（承诺的 [0,N]/C 个中尚有未到达）→ 该 attempt 的 final/chunk 等值验证处 **pending**（等待窗口，§1.2 (b)——completion 不因等值验证阻塞、照常收束），MUST NOT 判 `CANONICALIZER_CONFLICT`；
- (6) 重复 index → 既有幂等/冲突规则（同四元组同内容幂等去重、异内容 `CANONICALIZER_CONFLICT`，§1.2）；
- (7) **窗口耗尽**（等待窗口由 lease/超时语义覆盖）→ 该 LLM effect 按唯一证据分类函数以已持久化证据分类收束：无绑定该 attempt 的终局证据 → `unknown_outcome`（code `UNKNOWN_AFTER_DISPATCH`，待 repair），同一事务另记 `STREAM_INCOMPLETE` audit reason（`effect_audit.reason` 字段值、非新闭合 code）；已有合法成功回执（含完整流结束事实）的 attempt 不因窗口耗尽改判。

**stream_progress 状态门（拒绝优先序冻结，L4-R03＋F5——先于 observation receipt 合同执行、后于结构层 envelope/payload schema 校验与证据分类求值；位于身份/receipt 重放判定之后；按优先序首中即停）**：
1. **session 终态门（最高优先）**：terminal session（五类终态全部）上的 stream_progress observation 一律稳定拒绝固定 code `SESSION_TERMINAL`；本款先于一切 attempt 级状态与窗口判定；
2. **superseded**：attempt 已被取代（`superseded_by_attempt_no` 非 NULL）→ 固定 `rejected_stale`；
3. **attempt 四终态**：attempt 已终态 → `rejected_mismatch` 保留闭合 code `STREAM_CLOSED`（`unknown_outcome` 不属四终态——归第 4 款）；
4. **unknown/窗口耗尽**：attempt 已收束 `unknown_outcome` 或等待窗口已耗尽 → `REPAIR_REQUIRED`（receipt `repair_required`）；
5. **接受条件**：仅当目标 attempt 为当前执行 attempt（最大 `attempt_no` 行且未被取代）、未终局（等待窗口内 `dispatch_started` 维持中）且等待窗口内时，方进入 observation receipt 合同。
quiescing 注记（W01）：stream_progress 是 `complete_effect` 的非终局子操作例外——quiescing 下终局 completion 仍 MUST 返回 `DRIVER_QUIESCING`，本非终局 observation 按五款门唯一裁定，quiescing 不是五款之一。

**observation receipt 完整合同（冻结，Q04）**：
- (i) `outcome=accepted`（outcome 四值闭合集不扩；receipt 键为 computed hash、按 §3.1.2 统一规则落盘）；
- (ii) 占用 `(session_id, command_id)` binding、`first_outcome=accepted`；同 `command_id` 同键重试幂等返回原 observation receipt、不重复执行、不重复写观测；同 `command_id` 换 payload 复用 → 既有 `IDEMPOTENCY_CONFLICT`（§3.1.2 (2)），首次 binding 不受影响；
- (iii) receipt `result_canonical` 保存 observation identity 三元组 **`(attempt_no, observation_ordinal, payload digest)`**（canonical 表示——`observation_ordinal` 按 O01 (α) 在生成命令事务内分配、receipt 重试复用同 ordinal；payload digest 为该 observation payload 按 §1.3 canonical profile 的 hash）；
- (iv) observation receipt 与终局结算 receipt 相互独立（不同 `command_id` 天然隔离）。

**控制态零修改（观测写集权威收口，AF01）**：观测路径 MUST NOT 调用 §3.2.1 聚合；MUST NOT 修改 `sessions.state`/协调 lease/`session_fence`/`cancellation_epoch`/`steps.status`/聚合计数列（＝steps 的 `pending_effect_count`/`unknown_effect_count`/`retryable_effect_count`/`terminal_effect_count` 四列）；另 MUST NOT 修改该 attempt 的 `result_hash`/`status`/`provider_request_id` 与 parent 派生执行快照；写集 = observation receipt + `stream_progress` 观测事件 + 规定 audit（本款外无第四类写入）；观测事件为 O01 (α) 可重复观测——observation_kind `stream_progress`。

**observation payload 分层合同（冻结，S04）**：
1. 仅入 observational/audit 存储——O01 (α) 观测事件（observation_kind `stream_progress`、`observation_ordinal` 按 O01 分配）与 observation receipt（payload digest）；received binding/result 审计载体照常适用；observation payload MUST NOT 直接进入 semantic normalize 输入（normalize 输入域 = 已接受 `session_events` 事件，观测事件被 §3.3 两 digest 输入层排除）；
2. 流完整性集合判定只消费已接受 chunk 事件——收齐判定集合事实唯一来源 = 经统一受控函数提取的该流已接受 chunk 事件 index 集合；observation 计数字段仅为 observational 审计留存、不构成流集合事实；终局结算的收齐判定只读已接受 chunk 事件集合与终局 result 自身的计数字段；
3. `assistant/partial` 合成不受 observation 影响——partial 前缀合成来源唯一 = 已接受 chunk 事件；
4. 组合 vectors（多 observation 乱序/不同 payload/重复 payload/终局 result 组合）见 Conformance 10；不因中间事实终态化、MUST NOT 判 `CANONICALIZER_CONFLICT`、MUST NOT 分类为已知失败。窗口耗尽按第 (7) 项收束——无终局证据 → `unknown_outcome`＋`STREAM_INCOMPLETE`；窗口内后续到达 `stream_complete=true`（计数完整）result → 按形态 (i) 完整流正常结算（经**新 `command_id`**）；窗口耗尽后迟到终局 result → 既有证据分类路径（`REPAIR_REQUIRED`、其终局证据 observational/audit 留存并可作为 repair 证据）。

### 3.3 其他具名常量/哈希 [P0B-CORE]
- `request_hash`/`idempotency_key`：attempt 行 ABI 字段，后继分配复用原值（LATER 路径）；audit 记 `expected_idempotency_key_hash`/`received_idempotency_key_hash`（哈希存储）。
- compat adapter：裸 `cancelled` 不得使用，必须先依据 dispatch marker 转换，否则返回 `CANCELLATION_PHASE_REQUIRED`。

---

## 4. 状态机

### 4.1 effect 状态闭合（`effect_requests.status` 与 `effect_attempts.status` 同一九值域）[P0B-CORE]

存储闭合集（九值，逐字）：`{planned, ready, dispatch_started, succeeded, failed_retryable, failed_terminal, cancelled_before_dispatch, cancelled_after_dispatch, unknown_outcome}`。两表各自以列级 CHECK 强制该九值集（数据库级、无第十值）。`planned` 为 seal 事务内临时构建态、不持久化——列级 CHECK 仍含该值（事务内插入即校验），但已提交控制态不存在 planned effect 行。

合法转移（逐边，515–540 行）：

```text
planned -> ready -> dispatch_started
   -- planned 为 seal 事务内临时构建态、不持久化（冻结，镜像 §3.1 create_step 同事务化先例）：两条 seal 路径
   --（§3.1.2）在创建首个 attempt 后、同一事务将已密封 effect 直接写为 ready（发布即 ready、派发门
   -- ready -> dispatch_started 立即可见）；planned -> ready 边仅存在于 seal 事务内
ready -> cancelled_before_dispatch
   -- request_cancel 或 §2.2 第 3 条 WORKSPACE_LOST failure-drain（drain/guard 只作用于已发布 effect：仅自 ready 出边）；
   -- seal 事务内的取消 = 整个 seal 零副作用拒绝；pre-dispatch 取消双表原子同步（冻结）：三路径转 ready effect 时
   -- 其当前 attempt（最大 attempt_no 行）同事务转 cancelled_before_dispatch、parent 派生执行快照同事务同步
dispatch_started -> succeeded | failed_retryable | failed_terminal
                 | cancelled_after_dispatch | unknown_outcome
dispatch_started -> ready
   -- 仅 recovery 接管流程（经 retry_cohort_allocation 第 3(c) 步）：effect 级 current_job_fence 已推进、旧 job lease
   -- 已撤销、旧 attempt 已写入 superseded_by_attempt_no（保留原状态）且 cohort 新 attempt 行已同事务原子分配
   --（无「ready 而无新 attempt」窗口）；不得由 worker 触发
failed_retryable -> ready
   -- retry_cohort_allocation（retry_effect / recovery 接管第 3(c) 步两入口）：整批 cohort 各分配下一 attempt
   --（attempt_no+1、复用原 identity），同事务原子
failed_retryable -> cancelled_after_dispatch
   -- sticky cancel 收束（code=CANCELLED_BY_REQUEST_AFTER_DISPATCH，audit 另记 RETRY_SUPPRESSED_BY_CANCEL，不得 retry）
failed_retryable -> failed_terminal
   -- 批次终态收束受控边：规则 3 provider-cancel 收束、聚合规则 4 terminal failure 批次关闭（任一 failed_terminal
   -- 存在即触发——含纯预算耗尽批次，原规则 5 否分支场景并入）、§2.2 第 3 条 WORKSPACE_LOST failure-drain、
   -- §4 generation 强制下线收束（audit 另记 GENERATION_REVOKED 上下文）、quiescing 下 reconcile 对旧 epoch 的收束
   -- 与 recovery 接管第 3(c) 步非 sticky 关闭命中；同一收束事务内原子执行，保留 provider/工具原失败 code，
   -- audit 另记 RETRY_STOPPED_BY_CLOSURE，并按全路径共用的有序分类函数持久化 retry_stop_reason；
   -- MUST NOT 伪造取消证据或改写为取消 code；sticky cancel 收束仍走上边 cancelled_after_dispatch
unknown_outcome -> succeeded | failed_terminal | cancelled_after_dispatch
   -- 所有出口只能由 repair 执行（§2.7）
succeeded|failed_terminal|cancelled_before_dispatch|cancelled_after_dispatch -> terminal
   -- terminal 是分类标签、非存储状态
```

**terminalization 判定（冻结）**：`status ∈ {succeeded, failed_terminal, cancelled_before_dispatch, cancelled_after_dispatch}`（四终态值）。terminalization 后该 effect 的唯一允许操作为 audit/receipt 重放（迟到 completion 只进 audit、`superseded_by_attempt_no` 取代标记不改终态、`unknown_outcome` 为非终态、其出口才落终态）。

### 4.2 attempt 状态机
- 同九值 CHECK（与 effect 同域）；`dispatch_started` 后随结算落任一出口值；`unknown_outcome` 为非终态（repair 修复）。
- 「当前执行 attempt」判定 = 最大 `attempt_no` 行（唯一判定权威；`superseded_by_attempt_no` 是取代关系的显式持久化标记与可审计依据，非第二判定权威）。
- 取代语义冻结（superseded）[LATER]：该列非 NULL ⇒ 该 attempt 不再作为「当前执行 attempt」参与聚合/判定/repair 采信（其证据自此属「旧 attempt 证据不可复用」域，仅 observational/audit 留存）、不可 retry、迟到 completion 只进 audit（不改控制态）；旧 attempt 保留其原有终态/证据状态（MUST NOT 改动该行既有 `status`/`result_hash`/证据字段）；本列非判定输入（四源判定读取规则不含本列）。

### 4.3 effect 终态取消/未知 code 闭合映射（canonicalizer 与 control plane 共用，MUST NOT 另建第二套取消 code）[LATER]

| effect 终态 | code |
|---|---|
| `cancelled_before_dispatch` | `ABORTED_BEFORE_DISPATCH`（仅由数据库内部命令——`request_cancel` 或 §2.2 第 3 条 failure-drain——产生，worker 不可伪造） |
| `cancelled_after_dispatch`：provider 证实取消，或 repair 提交 provider 取消证据 | `CANCELLED_BY_PROVIDER`；partial prefix 单独不足以判定 |
| `cancelled_after_dispatch`：sticky cancel 下 coordinator 抑制/收束，或 repair 证实取消请求先于副作用生效 | `CANCELLED_BY_REQUEST_AFTER_DISPATCH`；audit 另记 `RETRY_SUPPRESSED_BY_CANCEL` |
| `unknown_outcome` | `UNKNOWN_AFTER_DISPATCH` |
| `succeeded` | `SUCCEEDED`；cancel 后完成另记 `COMPLETED_AFTER_CANCEL` audit |
| `failed_terminal` / `failed_retryable` | provider/工具返回的稳定失败 code，原样保留 |

派生（555 行）：step `outcome_code` 与 session `failure_code` 由 §3.2.1 派生表从本映射确定性生成。无本地 sticky latch 时 `CANCELLED_BY_PROVIDER` 经 §3.2.1 聚合规则 3 扩展触发收束（step `CANCELLED_BY_PROVIDER` / `FAILED_TERMINAL_PROVIDER_CANCELLED`、session `cancelled` / `CANCELLED_BY_PROVIDER`）；WORKSPACE_LOST failure-drain 的未 dispatch effect 复用 `ABORTED_BEFORE_DISPATCH`、未完成 step 使用闭合 `WORKSPACE_LOST`；`fail_session` INFRA 收束同款（session 终态见 §3.2.1 派生表 INFRA 行）。

---

## 5. ABI 对象（envelope 必填字段）

### 5.1 `EffectDescriptor` [P0B-CORE]
必须回显（逐字）：`effect_id, session_id, step_id, driver, driver_epoch, session_fence, dispatch_session_fence, dispatch_job_fence, attempt_no, request_hash, idempotency_key, cancellation_epoch` 及既有 ABI（含 `execution_mode` 回显——effect 行 `execution_mode` 权威列的同值副本：descriptor 创建事务复制该权威值、此后不可变；流完整性适用域的唯一判定权威是 effect 行 `execution_mode` 列，descriptor/attempt 回显非判定源）、generation、参数和 grant 字段。`dispatch_session_fence` 是该 attempt 创建时冻结的不可变 session fence 执行快照（attempt 行权威）；`dispatch_job_fence` 是该 attempt 执行 fence 的不可变快照；当前控制操作的 `session_fence` 仅用于命令 envelope 与 session 聚合；`cancellation_epoch` 为 session 级控制字段（`sessions` 行权威）。

### 5.2 `EffectResult` [P0B-CORE]
必须包含（逐字）：`effect_id, session_id, step_id, driver, driver_epoch, dispatch_session_fence, job_fence, attempt_no, request_hash, idempotency_key`（其中 `job_fence` 在验收时与 effect 级 `current_job_fence` 匹配——stale 判定唯一权威；证据绑定与 attempt 归属按 attempt 行 `dispatch_job_fence`），且 `outcome ∈ {succeeded, failed_retryable, failed_terminal, cancelled_before_dispatch, cancelled_after_dispatch, unknown_outcome}`。

**`EffectResult.outcome` 声明权威关系（冻结）**：`outcome` 是 worker 自报的**不可信声明**，MUST NOT 作为 effect 最终状态的判定输入——最终 effect 状态仅由本节唯一证据分类函数输出 + `retry_eligible`/收束环境派生（证据权威）。envelope 与证据校验通过后，声明 `outcome` 与按证据派生的结果**不一致**时 MUST NOT 拒绝整个 completion（completion 按派生结果正常收束结算、receipt `accepted`），同一事务在 `effect_audit.reason` 记 `RESULT_OUTCOME_MISMATCH`（reason 字段值、非新闭合 code——不进入本节任何闭合 code 集、不改变 code 派生与审计去重键语义），worker 声明值仅审计留痕；声明与派生一致时无该记录。本条不改变结构层既有拒绝路径：pre-dispatch cancellation 声明仍仅接受数据库生成的取消结果，结构层失败的 completion 照常整单拒绝。

---

## 6. P0B 相关性标注汇总

[P0B-CORE]（P0B 最小闭环必需）：
- `effect_attempts` 表 DDL 全量（列/主键 `(effect_id,attempt_no)`/唯一 `(effect_id,dispatch_job_fence)`/NOT NULL/CHECK/复合外键/冻结列触发器）——首个 attempt 断言、双 fence、dispatch 不补建、stale completion 拒绝的载体；
- 首个 attempt（`attempt_no=1`）seal 事务创建路径（`create_effect_in_seal`，`dispatch_job_fence` 同值冻结，发布即 ready、不持久化 planned）；
- 双 fence 拆分（`current_job_fence` 验收唯一权威 vs `dispatch_job_fence` 证据绑定快照；stale completion 拒绝）；
- 状态闭合核心边：`planned -> ready`（seal 事务内）、`ready -> dispatch_started`、`dispatch_started -> succeeded`；九值 CHECK；terminalization 判定；
- dispatch 派发门同事务检查（cancellation/compact/session/job fence/grant/handler readiness；只绑定既有 attempt、MUST NOT 补建）；
- `complete_effect` 两层验证+四步序判定层（身份/envelope/fence/canonical profile schema；结构层失败零控制态拒绝+receipt+audit）与成功证据分类收束（含 `EffectResult.outcome` 声明权威、`RESULT_OUTCOME_MISMATCH`）；
- `EffectDescriptor`/`EffectResult` 必填字段 ABI；
- `effect_audit` 基础列与 `UNIQUE NULLS NOT DISTINCT`（拒绝路径最小 expected/received 元组）；
- batch slot 唯一约束（`UNIQUE(session_id, step_id, batch_id, dispatch_ordinal)`、`UNIQUE(session_id, batch_id, tool_call_id)`）与 slot CAS/`request_hash` 一致幂等；
- `execution_mode` 权威列（建表即有；其流式判定用途 LATER）。

[LATER]（完整抽取备后续里程碑）：
- `retry_cohort_allocation` 全部 6 步（虚拟聚合/cohort 冻结/授权检查/generation 门/同事务分配/分配后最终聚合）与 `retry_effect`；
- `superseded_by_attempt_no` 写入与取代语义（列与约束建表落地，写入路径 LATER）；延迟自引用外键；
- `dispatch_started -> ready` recovery 接管边；
- `failed_retryable -> ready` / `-> failed_terminal` / `-> cancelled_after_dispatch` 边及 `RETRY_STOPPED_BY_CLOSURE`/`retry_stop_reason`（有序分类函数）；
- 取消 code 映射表全部（`ABORTED_BEFORE_DISPATCH`/`CANCELLED_BY_PROVIDER`/`CANCELLED_BY_REQUEST_AFTER_DISPATCH`/`UNKNOWN_AFTER_DISPATCH`/`COMPLETED_AFTER_CANCEL`）与 pre-dispatch 取消双表原子同步；
- `shared_cancel_closure`（五出口+AG01 触发源收口 (α)(β)(γ)(δ)）；
- `repair`（`REPAIR_REQUIRED`/`REPAIR_EVIDENCE_REQUIRED`/`retry_stop_reason`/decision effect 聚合规则 6）；
- `unknown_outcome` 全部出口；
- LLM 流式流完整性 grammar 全量（`stream_complete` 矩阵 (0)(i)–(v)、计数判据 (1)–(7)、`2^63-2`/`2^63-1` 值域、`C=N+1`、集合精确相等 {0..N}、额外 index 判据 F4、`CANONICALIZER_CONFLICT`、`STREAM_INCOMPLETE`）；
- stream_progress 状态门五款（`SESSION_TERMINAL`/`rejected_stale`/`STREAM_CLOSED`/`REPAIR_REQUIRED`/接受条件）与 quiescing 注记 W01；
- observation receipt 合同 Q04（`(attempt_no, observation_ordinal, payload digest)` 三元组、binding/`IDEMPOTENCY_CONFLICT`）与观测写集 AF01、payload 分层 S04；
- 入口拆定 Y01 的 (1)/(2)/(3) 款（`OBSERVATION_WRONG_ENTRY`、`DRIVER_QUIESCING`）；
- `GENERATION_REVOKED` 门（dispatch 门与分配第 4 步、拒绝分配后的最终聚合）；
- `effect_audit` 内部子操作三列（`internal_op_kind` 五值闭合集/`parent_command_id`/`internal_op_ordinal` 联合 CHECK Q05）——注：其完整联合 CHECK 在 600 行截断，续文由下一段 digest 承接。

---

## 附：本段边界说明
- 本 digest 覆盖 §3.2 中段 501–600 行；`effect_audit` 联合 CHECK 的完整式与 effect ledger 后续内容（语义层验证、receipt 结构等）在 600 行之后，由相邻 digest（§3.2 后段）承接。
- 上文依赖（不在本段、实现时需参照）：§3.2.1 规则 1–6 聚合与派生表、§3.2.2 前段（effect_requests DDL、唯一证据分类函数、四源判定读取规则）、§3.1.2（统一 receipt/binding 合同、内部子操作审计合同、锁序、拒绝规则）、§1.2（流完整性屏障）、§1.3（canonical profile、tagged integer）、§2.1（授权线性化点）、§2.2 第 3 条（WORKSPACE_LOST failure-drain）、§4（generation 强制下线协议）、O01/Q04/S04/F3/F4/F5/L4 系列、N04/N05/W01/W02/X01/Y01/AJ01/AJ02/AG01/AF01/M02/M04/P04/Q05 冻结注记。
