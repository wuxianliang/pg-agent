# s33-s4-compact-plugin — §3.3 seq/cancel/compact/repair + §4 插件协议开头

> 抽取自 `/Users/wxl/Projects/pg-agent/docs/designs/v8-dev.md` 行 697–760（§3.3 全部 + §4 插件协议 + §5 开头边界行）。冻结条款逐字引用；引用其他节的合同此处只登记指针、不复述（防漂移）。

## 1. 数据库表（完整清单）

### 1.1 `compactions`（compact 控制态表，DDL 冻结）[LATER]

列清单（逐字）：

```
compactions(session_id, compaction_id, base_seq, through_seq, status,
            owner_fence, lease_owner, lease_until,
            result_identity, abort_identity, created_at, updated_at)
```

约束（逐字引用）：

- `UNIQUE(session_id, compaction_id)`
- `base_seq`/`through_seq` 在 `compact_lock` 创建事务冻结、此后不可变（触发器或受保护写函数拒绝 UPDATE，数据库级强制）。`through_seq` 为该事务锁内可见的最大已分配 `seq`。
- `status NOT NULL CHECK (status IN ('locked','finalized','aborted'))`（闭合三值）
- 状态条件绑定（数据库级 CHECK 强制）：
  - `status='finalized'` ⟺ `result_identity IS NOT NULL` ∧ `abort_identity IS NULL`
  - `status='aborted'` ⟺ `abort_identity IS NOT NULL` ∧ `result_identity IS NULL`
  - `status='locked'` 时两列均 NULL
  - 违反该状态条件绑定的 INSERT/UPDATE MUST 被数据库级拒绝
- 「当前 compact lock」＝该 session 的唯一 `status='locked'` 行——部分唯一索引（逐字）：`UNIQUE INDEX ON compactions(session_id) WHERE status='locked'`，每 session 至多一个活跃 lock。状态机的 `idle` 不是行状态、是「该 session 无 `status='locked'` 行」的会话级状态。
- `owner_fence`/`lease_owner`/`lease_until` 为该 compaction 的 fence 与租约控制列（接管 CAS 与 stale 判定作用于本行）。
- `result_identity`/`abort_identity` 为终态结果 identity 列，取值与绑定见 §3「identity 与审计事件绑定合同」。
- `compact_finalize`/`compact_abort` 置终态**保留历史行**（MUST NOT 删除——`finalized`/`aborted` 行是审计与重放定位依据）；「释放回 `idle`」的精确语义＝该 session 无 `status='locked'` 行，下一次 compaction 申请新行（新 `compaction_id`）。

### 1.2 `session_events`（本节涉及的列与约束；完整 DDL 在 §3.1.2，规格仅部分给出）[P0B-CORE]

- 事件行同事务携带受保护归属列 `turn_id`（按事件归属赋值、此后不可改；数据库内部命令生成事件同样在追加事务内赋值）。
- semantic ordinal 双列（S01/S02）：
  - 公开 semantic 条目携调用方 `semantic_input_ordinal`——`UNIQUE(session_id, semantic_input_ordinal)` 部分唯一索引（仅公开 semantic 行）；唯一校验仅作用公开输入自身空间；同序完整事件内容比较域一致幂等、比较域任一分量不同 `IDEMPOTENCY_CONFLICT`（比较域定义见 §3.1.2 七步第 (4) 步，F1）。
  - 内部生成 semantic 事件携 `internal_semantic_ordinal`——纯数据库提交序（session 行锁内内部空间 max+1、按提交序分配；逻辑位置仅体现于 portable 投影键、该列仅内部审计/排序、不入任何 portable 投影）。
  - 两列互不交叉校验；两列不可变；observational/audit 不占任一列；分配与 seq 分配同一受控分配器同事务执行。
- 禁止独立 PG sequence、预留后外部 IO、删除或修改事件。
- raw 事件（provisional end 原始事件、历史 closer 原始事件、repair audit）仍在 `session_events` 只追加留存，仅不入 compact digest 输入。

### 1.3 `turn_end_closers`（closer 历史索引表；定义在 §3.1.2，规格仅部分给出）[LATER]

- repair 追加 turn-end closer 时按 `(session_id, turn_id, resolution_identity)`（digest+canonical 两级查重——按 resolution_digest 定位、命中后 canonical 字节精确全等比对）于该表幂等查重。

### 1.4 `internal_op_audits`（统一内部子操作审计宿表；定义在 §3.1.2，规格仅部分给出）[LATER]

- `compact_terminal_abort` 审计的持久化宿表——`event_key` 由数据库内部派生函数生成并随审计行同事务受保护写入，重放查询按三元组 `(parent_session_id, parent_command_id, internal_op_ordinal)` 定位返回该值。内部审计不分配 `session_events.seq`、不参与 semantic/portable trace。

### 1.5 `plugin_specs`（§4，伪 DDL）[LATER]

```text
plugin_specs:
  identity, contract_version, portability, fixture_digest,
  required_services, provided_services
```

### 1.6 `plugin_implementations`（§4，伪 DDL）[LATER]

```text
plugin_implementations:
  implementation_id, identity, contract_version, plugin_version, driver, locus,
  entry, implementation_digest, first_published_generation_id
```

- 显式携带 `contract_version` 并声明绑定 `(identity, contract_version) → plugin_specs(identity, contract_version)`（外键或等效约束）；不满足绑定的行 MUST NOT 进入目录与 generation。
- 唯一键冻结为 `(identity, contract_version, locus, driver, plugin_version)`——`driver` 不属于 implementation 身份，仅区分承载运行时：同 `(identity, contract_version, locus, plugin_version)` 的 Native 与 compat 实现以 `driver` 列区分为不同行并存。
- **全局不可变实体**：行不隶属任何单一 generation，创建后不可 UPDATE/DELETE。`first_published_generation_id` 仅是溯源记录，MUST NOT 表达归属或成员关系，不参与唯一键与任何调度/目录判定。
- 同键不同 `implementation_digest` 的再发布 MUST 稳定拒绝（不可变实体无改写路径）；实现内容变更 MUST 伴随 `plugin_version` 递增、产生新 implementation 行。

### 1.7 `generation_members`（§4，不可变成员表，伪 DDL）[LATER]

```text
generation_members:
  generation_id, implementation_id, included_at
  UNIQUE (generation_id, implementation_id)
```

- generation 与实现的成员关系唯一表达：generation 内容＝其成员行全集（成员行仅在发布事务写入、此后不可变，成员变更即新 generation）。
- 同一实现（同唯一键且同 `implementation_digest`）可被多个 generation 同时引用：refresh/发布解析到同键同 digest 插件时 MUST 复用该不可变行、为新 generation 插入新成员行，MUST NOT 插入第二个同键实现行、不得改写既有行。
- generation 无引用 GC 随其成员行一并执行；仍被任一在世 generation 引用的共享实现行 MUST NOT 删除。

### 1.8 `command_bindings`（引用；定义在 §3.1.2，规格仅部分给出）[P0B-CORE（合同本身）/ 此处应用 LATER]

- compact 步骤 (4) 引用：已占用且本次键对与 `first_request_hash` 不同 → `IDEMPOTENCY_CONFLICT`（写 `rejected_mismatch` receipt、MUST NOT 覆盖首次 binding）。

## 2. 命令与流程

### 2.1 `append_events` [P0B-CORE]

envelope/前置：锁定 session control row，校验 driver/epoch/fence（driver/epoch 校验的 `session/heartbeat`-quiescing 旧 epoch 例外见 §3.1.1 heartbeat 生命周期矩阵注 (iv)——记录不匹配、不拒绝，L4-U03）与 expected seq。

有序语义：

1. **expected seq 校验后置（L4-U-R01）**：位于全批查重之后、仅对含新插入条目的批次生效。全重复批次（归并后逻辑条目集合口径，F2）返回既有 identity/seq 区间，MUST NOT 校验 expected seq、不推进 `next_seq`（§3.1.2 公开 semantic append 唯一实现路径 expected seq 特例）。
2. 批次合同（§3.1.2 命令表）：先全量校验与去重、任一条目失败整批原子拒绝；已存在条目返回已有 seq、仅新条目占用连续区间。
3. 连续分配 `next_seq..next_seq+n-1`（`n`＝本次**新插入**事件数）。
4. 事件行同事务赋值受保护 `turn_id` 与 semantic ordinal 双列（同 §1.2；分配与 seq 分配同一受控分配器同事务执行）。

闭合 code：`IDEMPOTENCY_CONFLICT`（同序比较域任一分量不同）。

### 2.2 `request_cancel` [LATER]

- 是唯一递增 session `cancellation_epoch` 的命令；与 dispatch gate 锁同一 session row。
- cancel 先提交：已发布（`ready`）effect → `cancelled_before_dispatch`（code `ABORTED_BEFORE_DISPATCH`）。`planned` 为 seal 事务内临时构建态、不持久化（§3.2.2 状态闭合）——cancel 先落地时，其后到达的 seal 因 CAS 校验无 sticky cancel 而整体零副作用拒绝、不发布任何成员，不存在 planned 成员取消路径。
- dispatch 与 cancel 竞态按提交序三段裁定：
  1. dispatch 先于 cancel 提交 → 该 effect 保持 `dispatch_started`（in-flight）。
  2. sticky latch 已设之后，in-flight 终局结算只能是现有四类：`cancelled_after_dispatch`（含 provider 取消原样 `CANCELLED_BY_PROVIDER` 与 sticky 抑制 retryable `CANCELLED_BY_REQUEST_AFTER_DISPATCH` 两 code——各自按证据出处由取消映射表唯一写入、不得互相覆盖；sticky latch MUST NOT 将已写下的 `CANCELLED_BY_PROVIDER` 改写为 `CANCELLED_BY_REQUEST_AFTER_DISPATCH`，AJ01/§3.2.2 共享取消收束子操作第五出口）、`unknown_outcome`、`succeeded`＋`COMPLETED_AFTER_CANCEL` audit、或真实的已知 terminal failure 原样（sticky latch 存在时已知 retryable failure 经共享取消收束子操作同事务转 `cancelled_after_dispatch`）。观测留口：矩阵 (iii)/(iv) 五款状态门接受的观测不是终局结算，MUST NOT 写 `COMPLETED_AFTER_CANCEL`/`RETRY_SUPPRESSED_BY_CANCEL`、MUST NOT 触发 `shared_cancel_closure`。
  3. 终局先于 cancel 提交 → 按无 sticky 普通终局既有规则收束；随后到达的 `request_cancel` 按共享取消收束子操作四入口清单 (β)（已知结果处置）执行。**(β) 遍历对象限定（AJ02，冻结）**：遍历对象＝cancel 提交时仍非终态的已知结果（如 `failed_retryable`/`unknown_outcome`）；**已终态的 `succeeded`/`failed_terminal`/`cancelled_*` 不属 (β) 遍历对象**——terminal no-op 路径上 MUST NOT 补写 `COMPLETED_AFTER_CANCEL`；已终态 effect/step 的终态与已写下的 code（含取消 code——AJ01 同款）保持原样；terminal session 上 cancel 返回原终态（§3.1.1 回指）。
- partial prefix 单独不是 provider cancellation evidence：dispatch 后本地 timeout、崩溃或取消且无 provider 终局证据时，effect MUST 为 `unknown_outcome`（code `UNKNOWN_AFTER_DISPATCH`），MUST NOT 推断为已知取消。provider 证实取消（或 repair 提交 provider 取消证据）在无本地 sticky latch 时，经 §3.2.1 聚合规则 3 的扩展触发将 step/session 收束为 `cancelled`（cancel-wins，派生 code 见 §3.2.1 派生表）。

闭合 code：`ABORTED_BEFORE_DISPATCH`、`CANCELLED_BY_PROVIDER`、`CANCELLED_BY_REQUEST_AFTER_DISPATCH`、`UNKNOWN_AFTER_DISPATCH`；audit code：`COMPLETED_AFTER_CANCEL`；`RETRY_SUPPRESSED_BY_CANCEL`（观测路径 MUST NOT 写）。

### 2.3 `repair` [LATER]

- 必须取得 recovery claim，带稳定 `repair_id/command_id`、evidence type/digest、effect/attempt/`dispatch_job_fence`（attempt 归属与证据绑定，§3.2.2 双 fence 拆分）。
- 拒绝路径：无可验证证据、或证据经 §3.2.2 唯一证据分类函数分类输出仍为 `unknown` → 均返回 `REPAIR_EVIDENCE_REQUIRED`，unknown 保持不变（不修改控制态）。
- repair 只能追加稳定 closer/audit，不能修改旧事件。
- 追加 turn-end closer 的 repair 事务 MUST 按 §3.1.2 turn-end 槽位合同 (v) 受控校验六条执行（顺序冻结：幂等查重前置先于链头校验）：
  1. 先按 `(session_id, turn_id)` 锁定定位唯一槽位（槽位行锁按 §3.1.2 八位主锁序 turn_end_slot 位取得——attempt 行锁之后、compact 行锁之前）。
  2. 按 `(session_id, turn_id, resolution_identity)`（digest+canonical 两级查重）于 `turn_end_closers` 幂等查重：既有 closer 且 payload/派生 `event_key`/predecessor 完全一致 → 幂等返回已有 closer（不执行链头校验——重发携带旧 supersedes 亦返回）；同 resolution 但 payload 不一致 → 稳定 `IDEMPOTENCY_CONFLICT`（不落第二条 closer）。
  3. 既有 closer 不存在 → `supersedes_event_key` MUST 属于同一 session/turn 且为该槽位当前链上的 provisional end 或最新已提交 closer（当前链头），MUST NOT 指向任意历史事件；`resolution_identity` MUST 与当前链 predecessor 关系一致。
  4. CAS 重读发现链头已前进时按当前链重新分类——相同 resolution 幂等返回已有 closer、不同 resolution MUST NOT 覆盖已提交新 closer（稳定拒绝）。
  5. 跨 session、跨 turn、指向非槽位事件、不在当前链上的引用统一稳定拒绝（闭合 code `REPAIR_TARGET_INVALID`，receipt 落 `rejected_mismatch` 保留该 code、零控制态修改）。
- 不得把 dispatch 后 unknown 修成 pre-dispatch cancellation。
- recovery claim 可接管状态集合与 guard 以 §3.1.1 为唯一权威（本节 MUST NOT 重复枚举）：任意非终态 `N`（含 `blocked_unknown_effect`、`cancel_requested`）且 lease 空缺或已过期（`lease IS NULL OR expired`）时，MUST 以 CAS 校验 expected driver/epoch 取得，单调递增 `session_fence`，保留并核对 `active_step_id`。
- 终态例外（完整引用 §3.1.1）：terminal `failed` session 的 recovery claim/repair/reconcile 例外同时适用于 §2.2 第 3 条 WORKSPACE_LOST failure-drain、§3.1.1 `fail_session` 第 (3) 类 INFRA failure-drain 与 §4 GENERATION_REVOKED 收束（terminal 子协议矩阵 (b) 行三类）（`INFRA_ASSEMBLY_FAILED`/`INFRA_PROTOCOL_VIOLATION`）——三类 drain 后的 terminal session 均仅限收束既有未决 effect（unknown 的 repair、in-flight pending 的 completion 收束）、step failure-drain（含 drain-pending 重复判定）与审计，MUST NOT 创建新工作（step/effect/attempt/seal/retry/dispatch）、MUST NOT 改变 session 终态或 `failure_code`、MUST NOT 重建 workspace；以及存在既存 switch intent 的 terminal session（仅限 `reconcile(finish_switch)` 的屏障确认与 lease/fence/ownership 更新）。session 接管不等同于 job lease 接管。

闭合 code：`REPAIR_EVIDENCE_REQUIRED`、`IDEMPOTENCY_CONFLICT`、`REPAIR_TARGET_INVALID`。

### 2.4 driver switch（`begin_switch` / `reconcile(finish_switch)`）[LATER]

- 流程：`ACTIVE ->（begin_switch 安全点 guard）-> QUIESCING ->（仅 repair/reconcile 收束旧 epoch 工作，MUST NOT 重新产生可执行 ready 工作）-> reconcile(finish_switch) 按 §3.1.1 CAS 屏障确认 -> driver_epoch++ -> ACTIVE`。
- begin_switch 安全点 guard（任一不满足返回稳定 `SWITCH_DEFERRED`、不改 mode/fence/switch intent）：
  - (i) 无未密封 tools plan（无 step 处于 ready, stage=decision）；
  - (ii) 无 stage=decision in-flight effect；
  - (iii) 无任何未 dispatch 的 `ready` effect（已密封未派发也不行；`planned` 不持久化，已提交控制态中本项判据即 `ready`）；
  - (iv) 无非终态且仍可能经 completion/repair 产生 tools plan 的 decision step（含 blocked_unknown_effect 的 stage=decision step）。
- 屏障条件：无旧 epoch 非终态 effect、无 unresolved unknown、无有效旧 job lease 或已必被 stale-reject、active step 可切换、无未密封计划。收束与屏障不得倒置——repair/reconcile 正是达成屏障的手段，屏障在其后由 finish_switch CAS 复核，不存在循环顺序。
- QUIESCING 拒绝全部新工作与新 attempt（含已持旧 lease 的 coordinator）。切换完成后旧 epoch 写入一律 stale-reject。
- 切换能力按 §1.1 版本化 `driver_switch_capability` 声明：`supported` 的 driver MUST 满足完整协议；`unsupported` 的 driver 创建后不可变，`begin_switch` MUST 在任何 mode、fence 或 switch intent 变更之前返回 `UNSUPPORTED`。
- 存在既存 switch intent 的 terminal session 允许受限 recovery claim 与 `reconcile(finish_switch)`：只更新 mode/driver/driver_epoch/ownership/session_fence，MUST NOT 改变业务终态，屏障条件仍须全部满足。

闭合 code：`SWITCH_DEFERRED`、`UNSUPPORTED`（§5 行 760 另有 `DRIVER_QUIESCING`——quiescing 拒绝的 effect completion 为终局 completion）。

### 2.5 `inspect` / `transition_wait` [LATER]

- `inspect` 只读；wait/notify、fork 与 compact 的规则在 §3.3 内完整冻结，本节为唯一权威。
- `transition_wait(fence, predicate, observed_version)` MUST 在同一事务重新检查条件；满足则不 waiting，不满足才写等待条件并释放 lease。NOTIFY 只作 hint，扫描 ready、满足 predicate 的 waiting、到期 timer 和 `lease_until` 过期的 `claimed` 恢复进度。

### 2.6 compact 三受控命令（`compact_lock` / `compact_finalize` / `compact_abort`）[LATER]

envelope（引用 §3.1.2 统一命令合同）：携带 `command_id`/computed hash、receipt 与首占实际 outcome、主锁序 compact 锁位（末位——八位主锁序 turn_end_slot 槽位位之后）、授权经 `compact` capability 有效 grant（§2.1）。

- `compact_lock` 是 `idle → locked` 的唯一进入命令（申请）；存在任一非终态 LLM effect → 稳定拒绝 `COMPACT_BUSY_EFFECTS`（可重试，不改变任何控制态）。创建事务冻结 `base_seq` 与 `through_seq`（`through_seq`＝该事务锁内可见的最大已分配 `seq`）。
- `compact_finalize` 是 `locked → finalized` 的唯一命令路径；同一事务按冻结范围产出 compaction 结果并写 `compaction/end` 审计事件（payload 与 `result_identity` 列值同事务写入，两阶段生成见 §3）。
- `compact_abort` 是 `locked → aborted` 的唯一命令路径；释放 lock 回 `idle`。`aborted`（经 `compact_abort` 或终态事务受控 abort）MUST NOT 产出 compaction 结果事件。
- compact 与 LLM effect 互斥（闭合冲突矩阵，两侧命令经同一 session 行锁串行化，线性化点为事务提交序、先提交者赢）：
  1. `compact_lock` 时存在任一非终态 LLM effect → `COMPACT_BUSY_EFFECTS`；
  2. 创建/seal LLM effect 时存在 active compact lock（`locked` 态）→ `COMPACT_IN_PROGRESS`；§3.2.2 `ready -> dispatch_started` 派发门的 compact 检查同以 active compact lock 为拒绝条件。
- `compact_finalize`/`compact_abort` 均 fenced 操作，MUST 以 owner+fence CAS 提交；lock 的 lease 到期后新 owner 经 recovery lease CAS 接管（单调推进 fence）；被接管后旧 owner MUST stale-reject（稳定 `STALE_COMPACT_FENCE`，写 receipt/audit、MUST NOT 改变控制态）。

**compact 命令定位顺序（冻结，七步定位序——授权前置＋receipt 幂等前置；MUST NOT 合并、跳过或互换）**：

1. **授权调用上下文与 session 归属校验（最高优先）**——MUST 持有 `compact` capability 有效 grant 且目标 `session_id` 归属该授权调用上下文；无授权/归属不符 → 稳定拒绝 `GRANT_DENIED`（授权前置拒绝位于命令 receipt 命名空间之外：不读/不写任何 command receipt、不占 command binding，改写独立授权拒绝审计行；未知或无权目标不泄漏存在性）。本步先于 receipt 幂等查重与全部后续步骤。
2. **请求键计算**——按 §3.1.2 判定分流计算 `(receipt_key_kind, receipt_key_value)`：transport 合法且 payload 可规范化 → `canonical_request_hash`；transport 畸形 → `transport_rejection_key`；payload 不可规范化 → `rejection_fingerprint`。
3. **原 receipt 查重（命中即返回）**——按 `(session_id, command_id, receipt_key_kind, receipt_key_value)` 查找；命中 → 幂等返回原 receipt（无论 `accepted` 还是 `rejected_*`）；命中后不再校验 lease、历史行定位、compact fence 与参数一致性；仅历史响应读取，MUST NOT 授予旧 owner 新写权限。
4. **binding 冲突检查**——`command_bindings` 已占用且键对与 `first_request_hash` 不同 → `IDEMPOTENCY_CONFLICT`（写 `rejected_mismatch` receipt、MUST NOT 覆盖首次 binding）。
5. **统一前置分流（仅对未命中既有 receipt 的新请求）**——(a) 拒绝键路径 → MUST NOT 进入业务判定段，直接以 `rejected_mismatch`（保留具体 code）首占 binding 与写 receipt，MUST NOT 计算或比较 canonical hash；(b) canonical 路径 → 声明 hash 与 computed hash 不一致 → `REQUEST_HASH_MISMATCH`（`rejected_mismatch` 保留该 code；receipt 键为 computed hash；仅修正声明 hash 复用同 `command_id` 仍返回原拒绝，须以新 `command_id` 重发）；一致 → 进入 (6)。
6. **业务判定段与执行/终态返回**——(a) lease 要求：terminal session（`completed`/`failed`/`cancelled`）compact 终态历史行重放属只读 replay，允许无协调 lease；非 terminal MUST 持有有效协调 lease 与匹配 `session_fence`（envelope 携带当前 `session_fence`、匹配 owner/未过期 lease）。(b) 定位历史行：先按 `(session_id, compaction_id)` 查 `compactions` 行；无历史行或 `locked` → 按锁状态与 owner fence CAS 既有规则（recovery 接管条件＝`locked` 行 `lease_until` 已过期＋新 owner fence CAS 单调推进）。(c) 终态行的 fence 与参数判定：(i) 调用方 owner fence 与行 `owner_fence`（终态化时冻结）匹配，不符 → 稳定 `STALE_COMPACT_FENCE`（优先于参数比对）；(ii) 参数一致性——`base_seq`/`through_seq` 与冻结值相等、规范化 payload（§1.3 canonical profile 重算）与命令目标身份 `(session_id, compaction_id)` 同历史冻结值一致（`command_id` 与命令种类不在比对域）。(d) 执行/终态返回：`locked`＋本 owner → 正常 fenced finalize/abort；终态行完全一致 → 终态幂等返回（`finalized` → 原 `result_identity`；`aborted` → 原 `abort_identity`；MUST NOT 创建第二行或产出第二次结果事件，控制态零修改）；任一参数不一致 → 固定 `IDEMPOTENCY_CONFLICT`（receipt 落 `rejected_mismatch`；不返回旧结果、不产出事件、控制态零修改）。
7. **receipt/binding 写入**——(3) 命中分支不重复写；其余分支按 §3.1.2 统一 receipt 合同写本次 receipt 与 command binding（首占语义：canonical 首次执行在 (6) 完成后同事务提交；(5) 拒绝分支首占后同事务提交）。

**两分支显式拆分（冻结）**：同 `command_id` receipt 重放（步骤 (3) 命中）与跨 `command_id` 终态查询（经 (5)(6) 分类；terminal 无协调 lease 只读 replay 例外仅作用于本分支）是两条独立分支，测试与断言各归各分支。

**终态 replay 判定序（冻结五步）**：(1) 授权调用上下文与 session 归属校验（最高优先）；(2) lease 要求（terminal 允许无协调 lease 只读 replay）；(3) compact owner fence stale 校验（`STALE_COMPACT_FENCE`，优先于参数冲突）；(4) 参数一致性（不一致 → `IDEMPOTENCY_CONFLICT`）；(5) 完全一致 → 只读返回历史 identity、控制态零修改。

**终态事务同受控 abort（冻结）**：session 进入任一 terminal 状态（`completed`/`failed`/`cancelled`）的事务 MUST 在同一事务 abort 该 session 仍处 `locked` 的 compact lock——该受控 abort 是 session 终态事务的内部子操作、非独立命令（不另立 `command_id`/receipt，不走 `compact_abort` 命令入口；审计随所属终态命令的 receipt/audit 留存）：按 fenced abort 语义推进 compact owner fence、lock 落 `aborted` 并同事务写入 `abort_identity`（＝本受控 abort 写入的 `compact_terminal_abort` 审计的 `event_key`；MUST NOT 产出 compaction 结果事件）、控制态回 `idle`。此后旧 owner 的 `compact_finalize`/`compact_abort` 因 owner fence 已被推进 MUST stale-reject（`STALE_COMPACT_FENCE`）。

闭合 code：`COMPACT_BUSY_EFFECTS`、`COMPACT_IN_PROGRESS`、`STALE_COMPACT_FENCE`、`GRANT_DENIED`、`IDEMPOTENCY_CONFLICT`、`REQUEST_HASH_MISMATCH`。

### 2.7 context inject / reminder（行 709）[LATER]

- inject 固定 `assembly_cutoff_seq`：cutoff 之前可见，之后留到下一次 assemble；fold、recall、catalog、grant 和 policy 绑定同一 manifest hash。
- context inject 默认不新开 turn、不唤醒 idle session；reminder 使用显式 `wake_policy` 与 `turn_policy`，可在 timer 到期后唤醒。

### 2.8 fork（行 711）[LATER]

- 保存 `parent_session_id`、`parent_through_seq`、`fork_depth` 和 manifest version；`inherited_event_count` 只能作为缓存。继承范围是 parent `seq <= parent_through_seq`；父会话后续追加、repair 或 compact 不改变子会话的逻辑历史；跨 session source 必须保存 `{session_id, seq}`。
- fork guard（冻结）：`parent_through_seq` MUST 指向稳定切点——`seq <= parent_through_seq` 范围内不得存在未闭合 turn（含 unresolved unknown 或 pending 非终态 effect 的 turn）；稳定性按切点以内的事件及其 resolution 判定，MUST NOT 借用切点之后的父 repair——父在切点之后才 repair 的 unknown 对该切点仍为未解决 → 拒绝 `FORK_CUTOFF_UNSTABLE`。不满足时 fork 命令稳定拒绝 `FORK_CUTOFF_UNSTABLE`（调用方可改用更早且满足 guard 的切点重试，父会话控制态不受影响）。
- 子会话不继承任何控制态或 effect（step/effect/attempt、lease、fence、cancellation latch、compact lock、job 等控制平面对象只存在于父会话）；切点以内已解决的原始 unknown marker 按前缀规则继承（历史只追加），但在子 canonical trace 中被 closer 取代、不以 provisional 表示出现。

闭合 code：`FORK_CUTOFF_UNSTABLE`。

### 2.9 §4 插件发布与 generation 下线协议 [LATER]

**发布流程**（generation 生命周期见 §4 状态机）：完整扫描与 digest 校验、依赖解析与成员全集冻结（未变插件复用全局不可变行并插入新成员行、变更插件产生新实现行，generation digest 按成员列表计算）、worker 预加载并上报 readiness、原子切换 active 指针、新 assemble 绑定新 generation、已有 step/job 继续使用旧 generation、无引用后再 GC。构建期任一环节失败（完整扫描、digest 校验、依赖解析、预加载任一失败）的候选 MUST 经 `building → failed` 终止，且 MUST NOT 发布或改动 active 指针。

**依赖解析**：manifest 的 `requires`/`provides` 带版本范围、optional、priority。稳定拓扑排序（冻结）：`priority DESC, identity ASC, plugin_version ASC`，同键并列时依次以 `driver`、`implementation_id` 的字节序决出稳定全序；排序口径冻结——字符串比较一律按 UTF-8 字节序（code point 序），MUST NOT 依赖数据库 locale（如 `LC_COLLATE`）或宿主默认排序；`plugin_version` 比较冻结为 dotted-numeric 按 `(major, minor, patch)` 数值比较（缺失段按 0 补齐）；依赖环、同一 `driver` 范围内重复 provide、版本不匹配整代拒绝。

**`active → failed` 下线协议（闭合，逐条 MUST 实现）**：

1. **不可调度**：§3.2.2 派发门（`ready -> dispatch_started`）增加 generation 状态检查——effect 所属 step/job 绑定的 `catalog_generation` 为 `failed` 时未 dispatch effect MUST 拒绝派发（新闭合稳定 code `GENERATION_REVOKED`）且不进入 `dispatch_started`；拒绝为只读（仅写 receipt `rejected_mismatch` 保留 code 与规定 audit，MUST NOT 修改任何控制态）。seal 门同款：§3.1.2 两条 seal 路径（初始 decision seal 与 tools seal，即 `prepare_step`/`seal_batch`）MUST 同事务检查 step 绑定 `catalog_generation` 状态——已 `failed` 时稳定拒绝（`GENERATION_REVOKED`，零副作用）；下线事务与两条 seal 路径在读取/修改 generation 状态时 MUST 对该 generation 行加锁（seal 共享读、下线排他写），该锁纳入 §3.1.2 统一固定锁序。retry allocation 门同款：§3.2.2 `retry_cohort_allocation`（两入口）分配前同款锁定 step 绑定 generation——已 `failed` 时零分配稳定拒绝（`GENERATION_REVOKED`；普通入口 receipt `rejected_mismatch` 保留该 code，recovery 入口记入 `allocation_denied: GENERATION_REVOKED` 子结果；命中第 5 条三合取即收束 `failed_terminal`/`GENERATION_REVOKED`，未命中则 cohort 维持 `failed_retryable` 由重扫描收束）。
2. **active 指针处置**：active generation 进入 `failed` 时，active 指针 MUST 由 operator 经显式命令回退到上一可用 generation 或显式置空，并作为版本化配置持久化（记录操作者、时间与目标 generation，可审计）；MUST NOT 自动漂移。指针置空期间新 assemble MUST 稳定拒绝 `NO_ACTIVE_GENERATION`（不改变 session/step/lease/fence 控制态；被拒 coordinator 经第 4 条显式 yield 后回 `ready` 等待）。
3. **未派发工作 drain**：下线事务对绑定该 failed generation 的全部未 dispatch（`ready`；`planned` 不持久化）effect 同事务转 `cancelled_before_dispatch`（code 复用既有 `ABORTED_BEFORE_DISPATCH`，由数据库内部命令产生；audit 另记 `GENERATION_REVOKED` 上下文）；其当前 attempt 行同事务转 `cancelled_before_dispatch`（pre-dispatch 取消双表原子同步——数据库内部取消路径、非 worker completion；迟到 worker completion 按既有 envelope/mismatch 规则拒绝）。
4. **in-flight**：已 dispatch effect 持有 generation 快照，允许完成（与 `retired` 同规则）；completion/repair 按既有路径结算。完成的 step 正常续行：全部已决 effect 成功、且续行无需依赖该 failed generation 新 dispatch/seal/retry 的 step 按 §3.2.1 既有聚合规则终态化或续行；续行创建的下一 step 绑定回退后的 active generation；指针置空期间新 assemble 稳定拒绝 `NO_ACTIVE_GENERATION`（零控制态修改，沿用 §3.2.2 `GRANT_DENIED` 冻结模式：拒绝保持请求事务进入前的 session/lease/fence——正常 claim 后被拒保持 `claimed`，MUST NOT 隐式释放 lease 或递增 fence；coordinator MUST 经独立、遵守 §2.2 checkpoint/lost 合同的显式 yield 释放 lease 后回 `ready` 等待）。
5. **step 收束（优先既有规则）**：step 能经 §3.2.1 既有聚合规则（规则 3/4/5、取消收束）终态化时，终态与 code MUST 按既有规则派生（如混合成员中 unknown 经 repair 证实失败且 `budget_exhausted` → 规则 4 派生 step/session `FAILED_RETRY_BUDGET_EXHAUSTED`），MUST NOT 被 `GENERATION_REVOKED` 覆盖。仅当**三合取**成立——因该 failed generation 无法续行（存在被本协议 drain 的 `cancelled_before_dispatch` 成员，或续行需依赖该 generation 的新 dispatch/seal/retry）、无法经既有聚合规则终态化、且无未决 unknown/pending——的未完成 step → `failed_terminal`、`outcome_code=GENERATION_REVOKED`（新闭合 code，进 §3.2.1 派生表），session 同事务派生 `failed`/`GENERATION_REVOKED`（经 §3.1.1 `fail_session` 第 (1) 类来源）；残留 `failed_retryable` effect 同事务经 §3.2.2 受控边 `failed_retryable -> failed_terminal` 收束（保留原失败 code，`retry_stop_reason` 按既有有序分类函数持久化）。存在未决 unknown 的 step 维持 `blocked_unknown_effect`；存在 in-flight pending 的 step 停留 `waiting_effect`/`cancel_requested`（drain pending，不提前终态化）。sticky cancel 已设置时既有取消收束（cancel-wins）优先。
6. **与 readiness 故障的区分（保持）**：`active → failed` 仅用于发布后致命缺陷强制下线；运行期 handler 故障走 readiness/健康状态（目录 active 不等于 handler ready、worker 未加载对应 digest 不得 claim），MUST NOT 混用两种失败。
7. **下线事务锁集与并发协议（全序预锁＋重扫重试，冻结）**：(a) 全序预锁——按当前绑定集（该 generation 已关联的全部 step 所属 session，含已终态 session 的历史 step 归属）以 session identity 全序（UUID 一律 RFC 9562 16 字节 binary 字节序、非 UUID 文本 UTF-8 字节序）逐一取得全部已关联 session 行锁；(b) 取 generation 排他锁——预锁完成后按八位主锁序取得目标 generation 行排他锁；(c) 锁内重扫描绑定集；(d) 发现未预锁的新关联 session → 本事务内部回滚整体重试（释放全部已取得锁，按新绑定集重新全序预锁；MUST NOT 倒序补锁）；收敛为条件性保证（前提：新关联最终停止＋公平调度；部署选项：运维可在下线前临时关闭新绑定准入）；(e) drain 与置 `failed` 在最终锁集内执行。隔离级别前提：下线事务 MUST 运行于 READ COMMITTED，其他隔离级别在协议入口稳定拒绝 `ISOLATION_UNSUPPORTED`（recovery 接管/`FORCE_JOB_TAKEOVER`/终态 drain 等一切锁后重扫描协议同款）。

### 2.10 §4 runtime 合同（行 745–751）

- 每个 step/job 固定 `catalog_generation`、`plugin_version`/`implementation_digest`、contract version。worker 未加载对应 digest 不得 claim；目录 active 不等于 handler ready。[LATER]
- `apply(ctx, config)` 必须是进程内幂等的纯登记过程，不做外部 IO、不改会话状态。登记键至少为 `(generation_id, identity, plugin_version, handler_name)`；同 digest 重复登记是 no-op，不同 digest 是冲突。handler registry 只是非权威缓存。[LATER]
- Native `ctx` 只提供 `tools.register(define_tool(...))`、`systemPrompt.section`、`on(event, handler)` 投票登记和 `get(key)`。hook 不包 `next()`，按封闭代数折叠。hook 元数据包含 `criticality`、`failure_policy`、`timeout_ms`、`priority` 和 `stable_order_key`：mandatory authorization/policy 缺席、超时、错误均 deny/reject；advisory 才可 pass/degraded。工具可见性与具体调用授权分两阶段，入队前必须按参数和当前 grant 再授权。[LATER]
- 并发工具在 dispatch 前写入 `tool_call_id`、`step_id`、`batch_id`、`dispatch_ordinal`、`concurrency_group`、`exclusive_scope`、`max_parallelism`。认领时由数据库约束/租约表实现 session、workspace、tenant、provider 或 resource key 级并发限制；模型语义按 ordinal 折叠，完成时间仅作观测字段。[dispatch 绑定身份字段（`tool_call_id`/`step_id`/`batch_id`/`dispatch_ordinal`）为 P0B dispatch 闭环所需；`concurrency_group`/`exclusive_scope`/`max_parallelism` 与认领时并发限制 LATER]

### 2.11 §5 dsh-compat 开头（行 753–759，范围边界附带）[LATER]

- compat host 使用 pinned 的 DSH package、Node、profile digest、adapter 和 canonicalizer 版本。profile 只替换 persistence/storage provider，不另建 JSONL 真相；所有事件经统一受控路径写入 `session_events`——语义结果类事件（assistant final、`tool/result`、`turn/end` 等）MUST 按 §5.1「写入路径」列路由到对应 ledger 命令（compat 经 completion/repair facade，绑定生成 identity），MUST NOT 经公开 append facade 直接写入等价语义事件；输入类/观测类事件经公开 append facade 写入（§3.1.2 事件类型权限矩阵白名单 `public_append_types@v1`，越权类型稳定拒绝 `EVENT_TYPE_RESTRICTED`）；`ctx.tools.register` 同步 tool catalog，inject 遵守明确的 wake/turn policy。
- 社区包分级：T0/T1 可先挂 compat；T2 将文件访问改走 storageDomain；T3 的 pty/LSP/spawn 留在 host 但状态入库；T4 自实现 Persistence 或 UI slots 的包由 host 替换或排除。声称 portable 必须通过同一 fixture 的 native 与 compat suite。
- compat driver 切换同 §1.1 声明执行；quiescing 拒绝的 effect completion 为终局 completion（终局结算路径返回 `DRIVER_QUIESCING`）；`stream_progress` 非终局 stream observation 以 §3.2.2 五款状态门为唯一入口；所有 claim、append、effect completion 携带 `(session_id, driver, driver_epoch, fence)`，旧 epoch 的迟到写入一律拒绝。

## 3. 字节级算法

### 3.1 `compaction_result_digest@v1`（compact result_identity 列值；两阶段生成第 (2) 步）[LATER]

两阶段生成（冻结，N01——循环定义消除）：`compact_finalize` 事务内 `compaction/end` 的生成顺序固定为 **semantic payload → digest → event_key**、MUST NOT 互换或合并。

1. 组装 semantic payload——`compaction/end` payload 的全部非自引用字段（结构化绑定字段 `(session_id, compaction_id, identity_class)` 与 semantic 结果字段 `through_seq`/`logical_cutoff_digest`/`compact_result_identity`/`replacement_set_digest`）。
2. `compaction_result_digest@v1` ＝ SHA-256(由 payload 中**排除清单外**全部字段构成的 JSON 对象按 §1.3 canonical profile（规范步骤 0＋六步）序列化的 canonical bytes)，输出小写十六进制。**冻结自引用字段排除清单 `{result_identity, event_key, abort_identity}`** 同时适用于本键输入与 event_key 派生输入的 canonical payload hash（仅经版本号提升改变；本键后续任何变更 MUST 发布新版本号、MUST NOT 就地改写）。该 digest 即 `result_identity` 列值，作为 payload 的 `result_identity` 字段写入（自引用字段的值由本阶段产生、不进入 digest 输入）。
3. `event_key` 按 §3.1.2 事件键第 (1) 层 (b) 派生，其 canonical payload hash 按同一排除视图计算（取值即 (2) 的 digest——同一排除视图、同一 profile），绑定 `(session_id, event_type, occurrence_identity=(compaction_id, identity_class), 该 payload hash)`。

两个输出均只依赖 semantic payload，不存在循环。`compaction_result_digest@v1` 为 canonical 内容摘要（§1.3 profile、跨运行时字节级一致）；`compaction/end` 的 `event_key` 保持数据库内部派生 identity（非 portable 比较对象）。字节级 vectors 见 Conformance 6。两类审计的 payload MUST 携带结构化绑定字段 `(session_id, compaction_id, identity_class ∈ {result, abort})`。

### 3.2 canonical record 编码（两 digest 的共用摘要元素，O03＋P02 冻结）[LATER]

digest 输入层的每个 canonical semantic trace 元素编码为一个长度定界 record（逐字）：

```
[event_class][event_type][turn_id][step_id][dispatch_ordinal][portable_occurrence_identity][canonical payload digest raw32]
```

- 字段序冻结（MUST NOT 重排、增删字段）；前六个变长段各自前置 8 字节大端长度定界（与既有版本化键 framing 同款）。
- `event_class`/`event_type` 为其标识的 UTF-8 字节；`turn_id`/`step_id` 按 §3.1.2 `event_key@v1` 第 (iv) 条 identity 字段字节表示（UUID 一律 RFC 9562 16 字节 binary、非 UUID 文本 UTF-8 原样）；`dispatch_ordinal` 为其十进制数字 ASCII 字节（`canonical_integer_bytes` 同款、无前导零）。
- `portable_occurrence_identity` 段（P02 第七字段）——该事件 occurrence identity 的 **portable 投影**编码：段体＝投影元组逐分量 `[8 字节大端长度][分量原始字节]`（UUID 一律 RFC 9562 16 字节 binary、非 UUID 文本标识 UTF-8 原样、整数按 `canonical_integer_bytes` 十进制 ASCII、canonical 结构化字节按其 canonical JSON 字节；分量个数与次序由来源分流唯一决定，无分量计数前缀）。投影规则（实例化 §3.1.2 统一声明，MUST NOT 另立第二套）：
  - 公开 append 语义事件 ＝ `(semantic_input_ordinal)`
  - seal 生成 `tool/call` ＝ `(dispatch_ordinal)`（slot 序——同 step 跨 batch 的同 ordinal 并列由全序末键 canonical payload digest 决出）
  - 已知终结 `turn/end` ＝ `(turn_id)`（生成身份 `(command_id, turn_end_key)` 中 `command_id` 为控制面 ID 排除、`turn_end_key` 由 `(session_id, turn_id)` 唯一派生——投影收敛为 `(turn_id)`）
  - completion 生成的语义结果事件 ＝ `(effect_id)`（Q01 收窄——不含 `attempt_no`）
  - provisional `turn/end {outcome:unknown}` ＝ `(turn_id, provisional_unknown_effect_set_digest@v1)`（L4-R01 拆分；digest 字节算法唯一定义于 §3.1.2 portable logical occurrence identity (d′)，本节 MUST NOT 复述）
  - repair closer ＝ `(turn_id, resolution_identity canonical 字节)`（closer 生成身份经 `closer_event_key@v1` 派生自 `(turn_end_key, supersedes_event_key, resolution_identity)`——投影剔除全部派生键与控制面 ID）
  - 缺失（无 occurrence identity 的事件——防御性口径）为零长度段（长度前缀 0、无内容）；缺失归属字段为零长度段（无 turn/step 归属的 semantic 事件）。
- 末段为该事件 canonical payload 的 SHA-256 **原生 32 字节 binary**（`raw32`——定长段、无长度前缀；payload 摘要计算沿用 §1.3 canonical profile 既有）。
- record 版本注记：本 record 编码（七字段含 `portable_occurrence_identity`）与完整全序为首次落盘前的字段与排序精确化（沿 `malformed_binding_fingerprint@v2` 先例）；Q01/Q02 投影收窄、L4-R01/R02/R05、S01/S02/S03 均发生于首次落盘之前，版本号保持、不存在迁移条款。

### 3.3 digest 输入层（冻结，L4-R02——两 digest 的唯一输入层）[LATER]

- 被覆盖域的 canonical semantic trace ＝ `normalize(session_events 截断至 seq <= through_seq)` 输出中的 semantic 类元素全集（normalize 为 §1.2 唯一权威的确定性函数）。
- **截断边界冻结（S03）**：normalize 只消费 `seq <= through_seq` 内可见的事件及其在该范围内闭合的 supersedes 链——provisional `turn/end {outcome:unknown}` 仅当其 closer 位于范围内才被当前链头 closer 取代；**指向范围外 closer 的 provisional 保留 provisional 表示**（normalize MUST NOT 读取 compact 时点之后的槽位当前链头来替换截断历史）；未收束时同样保留唯一 provisional 表示；被取代的历史/中间 closer 不出现在输入 trace；repair 审计信封（`event_class=audit`）与全部 observational/audit 类元素排除；normalize 自 observational chunk 合成的 `assistant/partial` 前缀表示不入 semantic 覆盖集。
- 两 digest 均在 `compact_finalize` 事务内按本输入层计算并同事务持久化（不引用范围外事件或任何控制态）。

### 3.4 `logical_cutoff_digest`（(a)）[LATER]

输入 trace 全集各自编码为完整 canonical record，按**版本化逻辑序**逐 record 排序后顺序拼接的 SHA-256（小写十六进制）。逻辑序冻结为**完整全序（P02）**（逐字）：

```
(turn_id, step_id, dispatch_ordinal, event_type, portable_occurrence_identity, canonical payload digest)
```

- 事件 logical 归属升序；归属内并列依次按 `event_type`、`portable_occurrence_identity`、canonical payload 摘要逐级决出——末三键消除同位置并列的全部实现自由度，六键全同即同一 record。
- 各键按其 record 段编码（含段长度前缀）的原始字节序比较（等价于先按段长度、再按内容字节序——消除前缀包含歧义）；缺失归属分量为零长度段、按空字节参与序；`canonical payload digest` 按其 raw32 字节序。不依赖数据库内部派生键、数据库 locale 与事件物理存储序。
- 同全序键重复事件的 multiset 语义（冻结）：六键全等的多个事件其 record 必然逐字节相同，排序后自然相邻、多次出现均保留——(a) 以全序承载。

### 3.5 `replacement_set_digest`（(b)）[LATER]

- 同 (a) 输入层（N03 作用域同步收窄：输入域自「覆盖事件全集」改为「覆盖 canonical semantic trace 全集」）各自编码为完整 canonical record 后、按 **record 整体字节序**排序的 multiset 编码——全部 record 按其整体字节全序排序后顺序拼接的 SHA-256。multiset 语义保持：同一 record 的多次出现均保留（多重度不丢失）、输入呈现序不影响编码。
- 排序口径与 (a) 的差异即两字段分工：(a) 按完整全序逐 record、(b) 按 record 整体字节序——同一 record 集的两种确定性编码；record 含 `event_type` 与归属位置段，两 digest 对「同 payload 异 event_type/异归属」均敏感（Conformance 6 负向断言）。

### 3.6 `compact_result_identity@v1`（(c)，独立版本化 portable 结果 identity）[LATER]

逐字公式：

```
SHA-256("v8:compact-result@v1\0" || [8 字节大端长度]session_id 原始字节 || raw32(logical_cutoff_digest) || raw32(replacement_set_digest))
```

- 输出小写十六进制；域分离前缀为 ASCII 字符串 `v8:compact-result@v1` 后随单个 NUL 字节（含版本标签、进入 hash 输入）；session_id 原始字节前置 8 字节大端长度定界（identity 字段字节表示按 §3.1.2 `event_key@v1` 第 (iv) 条通用条款——UUID 一律 RFC 9562 16 字节 binary、非 UUID 文本 UTF-8 原样）；两个摘要段为定长 32 字节原生 binary（`raw32(·)`——定长段、无长度前缀）。
- **输入域收窄为仅 portable logical 输入（O02）**：session 身份＋两个 semantic 摘要——显式排除 `base_seq` 与 `compaction_id`，不含数据库内部 event_key。全部输入为持久化 logical 字段与 canonical 摘要，可跨运行时独立重算、属跨语言 golden vector 断言层级。
- 排除断言（O02）：两份 compact 结果被覆盖 observational/audit 事件数不同、`compaction_id` 不同而 session 相同、两 digest 相同 → `compact_result_identity@v1` **相同**（`base_seq` 同理排除——Conformance 6 断言）。
- semantic 比较不使用 `result_identity` 列值，改用本键；normalize 的 compact semantic 结果表示唯一源自 finalize 记录提取（§1.2 事件分类表 compact 行注），MUST NOT 自事件流重算、猜测或改写。规范化输入前缀模型与比较语义（F6/L4-FINAL-06）：被覆盖集不同（两 digest 任一不同）→ semantic 比较失败；observational 隔离（N03）：两运行-time 被覆盖 observational/audit 事件数不同而 semantic 事件集相同 → 三字段一致 → compact semantic 比较通过。

### 3.7 §4 依赖解析排序（非 hash 但冻结口径）[LATER]

`priority DESC, identity ASC, plugin_version ASC`；同键并列依次以 `driver`、`implementation_id` 的字节序决出稳定全序；字符串比较一律按 UTF-8 字节序（code point 序），MUST NOT 依赖数据库 locale（如 `LC_COLLATE`）或宿主默认排序；`plugin_version` 比较冻结为 dotted-numeric 按 `(major, minor, patch)` 数值比较（缺失段按 0 补齐）。generation digest 覆盖成员列表（成员全集的规范化表示按 §1.3 canonical profile 计算，两代成员不同即 digest 不同）。

### 3.8 本节引用但定义在别处的具名键（指针，防漂移）[LATER]

`event_key@v1`（§3.1.2 第 (1) 层 (b)、第 (iv) 条）、`closer_event_key@v1`、`provisional_unknown_effect_set_digest@v1`（§3.1.2 (d′)）、`canonical_integer_bytes`、`malformed_binding_fingerprint@v2`（先例引用）、`public_append_types@v1`（§3.1.2 权限矩阵）。

## 4. 状态机

### 4.1 compact 控制状态机（闭合集）[LATER]

```
idle → locked(compaction_id, base_seq, through_seq, owner_fence, lease) → {finalized, aborted}
```

- 三个受控命令驱动：`compact_lock` 是 `idle → locked` 的唯一进入命令（申请）；`compact_finalize` 是 `locked → finalized` 的唯一命令路径；`compact_abort` 是 `locked → aborted` 的唯一命令路径。compaction 的 `start/end` 是审计事件，真正锁位于 control plane。
- `finalized`/`aborted` 是该 `compaction_id` 的终态，进入终态的同一事务即释放 compact lock（控制态回 `idle`，供下一次 compaction 重新申请）。
- `aborted`（经 `compact_abort` 或终态事务受控 abort）MUST NOT 产出 compaction 结果事件。
- `idle` 不是行状态、是「该 session 无 `status='locked'` 行」的会话级状态（部分唯一索引强制）。

### 4.2 session driver mode（driver switch）[LATER]

```
ACTIVE → QUIESCING → ACTIVE（reconcile(finish_switch) CAS 屏障确认后 driver_epoch++）
```

- begin_switch 安全点 guard 四条件（见 §2.4）任一不满足 → 稳定 `SWITCH_DEFERRED`、不改 mode/fence/switch intent。
- QUIESCING 拒绝全部新工作与新 attempt（含已持旧 lease 的 coordinator）；仅 repair/reconcile 可收束旧 epoch 工作、MUST NOT 重新产生可执行 ready 工作。
- 切换完成后旧 epoch 写入一律 stale-reject。

### 4.3 generation 生命周期（§4）[LATER]

```
building -> {active, failed}
active -> {retired, failed}
```

- `building → failed`：构建期任一环节失败（完整扫描、digest 校验、依赖解析、预加载）。
- `active → failed`：仅用于发布后发现致命缺陷需强制下线；触发七条下线协议（§2.9）。运行期 handler 故障走 readiness/健康状态，MUST NOT 混用。
- `retired`：已绑定 step/job 继续使用旧 generation；无引用后 GC。

### 4.4 本节引用的 effect/step/session 状态（定义在 §3.1/§3.2，此处为引用面）

- effect（非终态→终局闭合集，[LATER] 除 dispatch/complete 基本面）：`ready`、`dispatch_started`（in-flight）；终局结算四类（sticky latch 已设后）：`cancelled_after_dispatch`、`unknown_outcome`、`succeeded`（＋`COMPLETED_AFTER_CANCEL` audit）、已知 terminal failure 原样；另有 `cancelled_before_dispatch`、`failed_retryable`、`failed_terminal`（受控边 `failed_retryable -> failed_terminal`）。`planned` 为 seal 事务内临时构建态、**不持久化**（§3.2.2 状态闭合）——已提交控制态不存在 planned effect。
- step：`blocked_unknown_effect`、`waiting_effect`、`cancel_requested`、`failed_terminal`（三合取下 `outcome_code=GENERATION_REVOKED`）。
- session 终态闭合：`completed`/`failed`/`cancelled`；step 状态 `ready, stage=decision`（begin_switch guard (i) 判据）。
- P0B 相关：`ready`（发布）→ `dispatch_started`（派发门）→ 终局（成功证据分类 `succeeded`）这条主干是 P0B 闭环的 effect 状态面 [P0B-CORE]；cancel/unknown/repair 相关状态 [LATER]。

## 5. P0B 相关性标注

判定标准：P0B 最小闭环＝user event → create step（与初始 decision seal 同事务）→ create fake LLM effect（seal 事务内同事务创建唯一首个 attempt 行 attempt_no=1）→ dispatch（只绑定既有 attempt、不补建）→ complete effect（成功证据分类＋assistant message 事件）→ step/session 聚合 → yield/finish_session；外加 kill-at-every-boundary chaos、命令幂等（command_id receipt/binding）、canonical profile、事件 seq 无洞、turn finalization reducer、双 fence 基本语义（stale completion 拒绝）、Conformance 1 核心断言。

### [P0B-CORE]

- **`append_events` 完整合同**（§2.1）：session control row 锁＋driver/epoch/fence 校验（双 fence 基本语义的 append 面）、expected seq 校验后置、全重复批次不推进 `next_seq`、连续分配 `next_seq..next_seq+n-1`（seq 无洞核心断言）、批次原子拒绝、`turn_id` 受保护归属列、semantic ordinal 双列（S01/S02——P0B 闭环的 completion 生成 assistant message 事件即「completion 生成的语义结果事件」，走 `internal_semantic_ordinal` 纯提交序分配）、禁止独立 PG sequence/预留后外部 IO/删除修改事件。
- **canonical profile（§1.3）**：本范围内所有 digest/键计算的基础（P0B 显式列入；完整定义在 §1.3）。
- **命令 receipt/binding 幂等模式**（§3.1.2 统一合同；本范围 compact 七步定位序是其应用实例——模式为 CORE，compact 应用本身 LATER）。
- **dispatch 前写入的绑定身份字段**：`tool_call_id`、`step_id`、`batch_id`、`dispatch_ordinal`（行 751 前半；dispatch 只绑定既有 attempt 的闭环所需）。
- **effect 主干状态面**：`ready` → `dispatch_started` → 成功终局（§4.4）。

### [LATER]（完整抽取于上文，仅打标）

- `request_cancel` 全部取消语义（`cancellation_epoch`、sticky latch、三段竞态裁定、(β) 遍历限定 AJ02、AJ01 code 不覆盖、partial prefix 非证据）。
- `repair` 全部（recovery claim、`turn_end_closers` 查重六条、终态例外矩阵）。
- driver switch（`begin_switch`/`reconcile(finish_switch)`、QUIESCING、`driver_switch_capability`）。
- `inspect`、`transition_wait`。
- compaction 全套：`compactions` 表、三个受控命令、七步定位序、终态 replay 判定序五步、终态事务同受控 abort、冲突矩阵、全部五个具名算法（`compaction_result_digest@v1`、canonical record 编码、digest 输入层、`logical_cutoff_digest`、`replacement_set_digest`、`compact_result_identity@v1`）。
- context inject/reminder（`assembly_cutoff_seq`、`wake_policy`/`turn_policy`）。
- fork（guard、`FORK_CUTOFF_UNSTABLE`、控制态不继承）。
- §4 插件协议全套：三表、generation 生命周期、发布流程、依赖解析排序、`active → failed` 七条下线协议、`apply(ctx, config)`、Native `ctx` 面、hook 元数据与两阶段授权、认领时并发限制（`concurrency_group`/`exclusive_scope`/`max_parallelism`）。
- §5 compat 开头（pinned 版本、写入路径路由、`public_append_types@v1`/`EVENT_TYPE_RESTRICTED`、T0–T4 分级、`DRIVER_QUIESCING` 终局 completion）。

实现注记（不打标、供实现者参考）：P0B 若 schema 上 step/job 的 `catalog_generation` 为必填列，需要一个固定的种子 active generation 即可满足最小闭环；seal/dispatch 门的 generation 状态检查逻辑本身属下线协议（LATER），但列绑定宜在 P0B schema 一次到位。
