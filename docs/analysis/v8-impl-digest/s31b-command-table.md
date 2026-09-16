# s31b-command-table — §3.1 后半：命令表、append_events 七步、事件键三层

> 来源：`/Users/wxl/Projects/pg-agent/docs/designs/v8-dev.md` 第 299–396 行（§3.1.2 核心命令与 receipt 幂等 + §3.1.2 事件键三层 + turn-end 槽位数据合同）。本文件是冻结合同的实现抽取摘要：关键字段名、code 字符串、字节公式逐字引自规格，不得意译。

---

## 1. 数据库表（完整清单）

### 1.1 `command_receipts`（DDL 冻结）[P0B-CORE]

```text
command_receipts(
  session_id, command_id, command_kind, command_request_hash,
  outcome, result_canonical, result_hash, created_at
)
UNIQUE(session_id, command_id, command_request_hash)
```

- 注（规格原文）：「`command_request_hash` 与 `first_request_hash` 存类型化键对 `(receipt_key_kind, receipt_key_value)`」——上述 UNIQUE **等价** `(session_id, command_id, receipt_key_kind, receipt_key_value)`。
- `receipt_key_kind ∈ {canonical_request_hash, rejection_fingerprint, transport_rejection_key}`（闭合集）；`receipt_key_value` 为该 kind 的键值（§1.3 对应算法输出；`canonical_request_hash` 即 `computed_request_hash`，SQL 按 canonical profile 重算值）。
- 三键 kind 唯一归属为**字段级冻结**：`accepted` 一律 `canonical_request_hash`；payload 拒绝（payload 不可规范化，路径 (c)）一律 `rejection_fingerprint`；transport 拒绝（路径 (a)/(b)）一律 `transport_rejection_key`，MUST NOT 入 accepted 命名空间（accepted 命名空间仅含 `canonical_request_hash`）。
- 跨租户查询边界：拒绝 receipt 绑定授权调用上下文，MUST NOT 借此跨租户查询；声明 hash 仅存 receipt payload 供审计，不参与任何键。
- 保留语义：receipt 与 command binding MUST 保留至 session/effect 数据一并显式销毁，MUST NOT 被 compaction 清理。

### 1.2 `command_bindings`（DDL 冻结）[P0B-CORE]

```text
command_bindings(session_id, command_id, first_request_hash, first_outcome)
UNIQUE(session_id, command_id)
```

- binding 由**首个可归属请求**（任意四类 outcome：`accepted` / `rejected_*` / `repair_required`）占用；`first_outcome` 记录首次实际结局；`first_request_hash` 存 `(receipt_key_kind, receipt_key_value)` 键对。
- 首占分流：canonical 路径按第 (4) 步实际结局首占；(b)/(c) 拒绝路径不进入第 (3)(4) 步，直接以对应 transport/schema 拒绝结局首占。

### 1.3 `internal_op_audits`（DDL 冻结）[LATER]

内部子操作审计持久化表——`effect_audit` 域外的内部子操作 audit 行（目标为 compaction 等非 effect 对象者）的独立表：

```text
internal_op_audits(
  parent_session_id NOT NULL,      -- 统一审计 envelope 必填字段（本表即其持久化）；本表唯一 session 列——
                                   --   所有 FK/RLS/唯一约束/查询均指它（不设第二 session 列，无同值冗余）
  parent_command_id NOT NULL,      -- 父命令 command_id
  internal_op_ordinal NOT NULL CHECK (internal_op_ordinal >= 0),  -- 父命令事务内分配、不可变（触发器或受保护写函数拒绝 UPDATE）
  internal_op_kind NOT NULL CHECK (internal_op_kind IN
    ('failure_drain','shared_cancel_closure','compact_terminal_abort','infra_closure','generation_revocation_drain')),
  source_operation NOT NULL,       -- 触发来源操作
  target_identity NOT NULL,        -- 目标对象 identity 的规范字节表示（UUID 一律 RFC 9562 16 字节 binary、非 UUID 文本 UTF-8 原样）
  event_key NOT NULL,              -- 数据库内部派生 identity
  parent_receipt_ref NOT NULL      -- 绑定父命令 receipt 的引用（随父 receipt 同事务留存）
)
UNIQUE(parent_session_id, parent_command_id, internal_op_ordinal)   -- 三元组幂等键（I02）
UNIQUE(parent_session_id, event_key)   -- 替代 session 级约束（唯一 session 列即 parent_session_id，I-R02）
```

- `event_key` 由**数据库内部派生函数**在父命令事务内生成：绑定 `(parent_session_id, parent_command_id, internal_op_kind, internal_op_ordinal, target_identity 规范字节)` 五元组派生域，同输入 MUST 返回同键，随审计行同事务受保护写入（G01(b) 数据库内部派生 identity、非 portable 比较对象）。
- `compactions.abort_identity` ≡ 该表对应 `compact_terminal_abort` 行的 `event_key`（§3.3 回指；重放按三元组定位返回该 event_key）。
- `compactions.result_identity` **不再绑定任何内部审计事件 `event_key`**（N01）——取值为独立版本化摘要 `compaction_result_digest@v1`；semantic 比较使用独立的 `compact_result_identity@v1`（N02）。
- `effect_audit` 域内子操作行**不入本表**（两键作用域互斥）：落 `effect_audit`、携带 `internal_op_kind`/`parent_command_id`/`internal_op_ordinal` 三列（内部行三列 MUST 非 NULL 且 `audit_context_session_id`=parent_session_id），行唯一性由该表去重键（扩至 **10 列**，§3.2.2）承载。
- `effect_audit` 内部行（`internal_op_kind` 非 NULL）的 expected 归属四列（`session_id`/`step_id`/`effect_id`/`attempt_no`）MUST 全非 NULL（数据库级联合 CHECK，L4-R04）——无 effect 归属的 session 级内部操作（如 `compact_terminal_abort`）MUST NOT 写入 `effect_audit`、仅入 `internal_op_audits`。

### 1.4 `turn_end_slots`（DDL 冻结）[P0B-CORE]

canonical end 槽位持久化行（§1.2「每 turn 至多一条 canonical `turn/end`」由数据库约束强制）：

```text
turn_end_slots(session_id, turn_id, turn_end_key, head_event_key, slot_status, resolution_identity_canonical, version)
```

- `session_id` 外键引用 `sessions`。
- `turn_end_key NOT NULL` 且**创建后不可变**（触发器或受保护写函数拒绝 UPDATE，与 `effect_attempts` 冻结快照列同款保护）；不接受调用者指定。
- `head_event_key NOT NULL`：该槽位 supersedes 链**当前链头**事件的 `event_key`（初始为该 turn 初始 provisional end 的 `event_key`）；仅经受保护槽位更新函数随 closer 追加受保护更新。
- `slot_status NOT NULL CHECK (slot_status IN ('provisional','known'))`（闭合二值：provisional unknown end → `provisional`；已知终结 end/closer → `known`）。
- `resolution_identity_canonical`（bytea，可 NULL）：当前已知终结 resolution 的 canonical 字节（链头为 provisional 时 NULL）。
- `version NOT NULL`（bigint，槽位行版本号，每次受保护更新 +1、CAS 用）。
- `UNIQUE(session_id, turn_id)`（每 turn 至多一个槽位行）；另增 `UNIQUE(session_id, turn_id, turn_end_key)`（closer 历史表复合外键的被引用前提）。
- 四列 `head_event_key`/`slot_status`/`resolution_identity_canonical`/`version` MUST NOT 经受保护槽位更新函数外任何路径修改（数据库级强制）。
- 槽位行创建入口（同事务）：产生该 turn 初始 provisional end 的数据库内部事务（`complete_effect` 分类 `unknown_outcome` 时）MUST 同事务写槽位行；其他 turn-end 写入路径（cancel 收束、repair closer、已知终结 end）在槽位行不存在时同事务按同一派生创建；`UNIQUE(session_id, turn_id)` 使并发双写收敛为单行。初始行：`slot_status='provisional'`、`head_event_key`=provisional end 的 event_key、`resolution_identity_canonical`=NULL、`version=1`（初始 provisional end 不是 closer、不写 closers 历史行）。

### 1.5 `turn_end_closers`（DDL 冻结）[LATER]

closer 历史索引表：

```text
turn_end_closers(session_id, turn_id, turn_end_key, resolution_identity_canonical, resolution_digest, supersedes_event_key, closer_event_key, event_seq)
UNIQUE(session_id, turn_id, resolution_digest)
```

- `resolution_digest`：32 字节 binary NOT NULL，= SHA-256(`resolution_identity_canonical`) 的原生 32 字节摘要，随行同事务计算写入、不可变——唯一约束承载列。
- `resolution_identity_canonical`（bytea，NOT NULL）：**非索引留存列**（canonical 字节长度上不设界、不建索引——超长或不可压缩 resolution 不使唯一索引不可实现，J08）；NOT NULL（closer 恒携带具名 resolution；provisional 链头无 resolution 的事实由槽位表承载）。
- `(session_id, turn_id, turn_end_key)` 三列**复合外键**引用 `turn_end_slots` 同三列（错误 turn_end_key 由此数据库级拒绝；三列组合指向他槽位但 turn 归属不符的形态由受保护槽位更新函数的候选链头归属校验拒绝——函数层，J09）。
- 每列语义：`turn_end_key`=槽位行冻结值（不可变冗余列）；`resolution_identity_canonical`=该 closer 的 resolution canonical 字节；`resolution_digest`=其 SHA-256 原生 32 字节 binary 摘要；`supersedes_event_key`=其 predecessor 事件键；`closer_event_key`=该 closer 事件的 `event_key`；`event_seq`=该事件的 `seq`。
- **仅**受保护槽位更新函数可在同事务插入（追加 closer＋更新链头＋插入历史行三位一体）；写入后行不可变（触发器或受保护写函数拒绝一切 UPDATE；DELETE 仅随统一数据销毁策略级联）。
- `closer_event_key`（及槽位表 `head_event_key`、本表 `supersedes_event_key`）各受复合外键 `(session_id, event_key)` 引用 `session_events` 既有唯一约束（H02；同事务写入序：先追加事件行、后写槽位/closers 行，或 `DEFERRABLE INITIALLY DEFERRED`——孤立 key 数据库级不可落库）。

### 1.6 `session_events` 增列（本段定义）[P0B-CORE]

**(a) `turn_id` 受保护归属列（H02，数据库级）**：事件归属 turn——追加事务内按事件归属赋值、此后不可改（触发器或受保护写函数拒绝 UPDATE）；无 turn 归属的事件（如 `session/heartbeat` 等会话级观测事件——P01 拆分后心跳按归属二分：会话级 `session/heartbeat` 无 turn 归属为 NULL，attempt 级 `attempt/heartbeat` 按其所属 effect/step 的 turn 归属赋值）为 NULL。

**(b) semantic ordinal 双列（持久化，DDL 冻结；L4-R05 原单列拆分——S01 序号作用域分离 / S02 内部序定义收口）**：

- `semantic_input_ordinal`（公开 append semantic 条目；bigint；数据库级 `CHECK (semantic_input_ordinal BETWEEN 1 AND 2^63-1)`；值域冻结 L4-U01：闭区间 [1, 2^63-1] 的整数——2^63 及以上、负值、非整数一律拒绝）：
  - append 批次内每个语义类白名单条目（`user/message`、`turn/start`、`agent/inject`）MUST 携带调用方 `semantic_input_ordinal`（条目级 envelope 字段）；观测类白名单条目（`assistant/chunk`、`session/heartbeat`）不适用、不携带；缺失或值域外 → envelope 校验层稳定拒绝。
  - 该序号进入 portable 投影/摘要元素时编码一律为 `canonical_integer_bytes`。
  - **列值 = 调用方值**（数据库不按到达序改派）；`UNIQUE(session_id, semantic_input_ordinal)` 部分唯一索引（仅公开 semantic 行）。
  - 唯一校验仅作用于公开输入自身空间（S01：与 `internal_semantic_ordinal` 无关，内部数值不构成公开条目的拒绝或合并依据；不存在任何调用方序与内部序的比较/避让/碰撞交叉校验）。
- `internal_semantic_ordinal`（内部生成 semantic 事件）：
  - 列值定义为**纯数据库提交序（S02 方案 1 冻结）**：由生成控制事务在 session 行锁内分配（seal、completion、cancel/reconcile 收束、repair 全部先锁 session 行），数值 = 自「该 session 内部 semantic 行当前已分配最大 `internal_semantic_ordinal` + 1」起同事务连续递增（仅统计内部空间、不读公开列）。
  - 按提交序分配、不按逻辑生成位置分配；逻辑生成位置仅体现于 portable 投影键；out-of-order 并发仅使相关事件 ordinal 互换、portable 投影与 §3.3 两 digest 不变（Conformance 断言）。
  - 仅内部审计/排序用途；MUST NOT 进入任何 portable 投影。
- 两列列级条件约束：公开 semantic 行 `semantic_input_ordinal` MUST 非 NULL 且 `internal_semantic_ordinal` MUST NULL；内部 semantic 行 `internal_semantic_ordinal` MUST 非 NULL 且 `semantic_input_ordinal` MUST NULL；非 semantic 行两列 MUST NULL。observational/audit 类事件 MUST NOT 占任一列。
- `UNIQUE(session_id, semantic_input_ordinal)`（仅公开 semantic 行）与 `UNIQUE(session_id, internal_semantic_ordinal)`（仅内部 semantic 行）两个部分唯一索引各自在自己作用域内强制（互不为对方的拒绝依据）；两列追加事务内赋值、此后不可变（受保护列）；分配与 seq 分配同一受控分配器同事务执行。

### 1.7 其他表（规格仅部分给出，本段回指）

- `compactions`（§3.3）：`abort_identity` ≡ `internal_op_audits` 中 `compact_terminal_abort` 行的 `event_key`；`result_identity` = `compaction_result_digest@v1`（N01/N02）。[LATER]
- `effect_audit`（§3.2.2）：去重键扩至 10 列；`internal_op_kind`/`parent_command_id`/`internal_op_ordinal` 三列 + 归属四列联合 CHECK（L4-R04）。[LATER]
- 独立 ingress/malformed receipt 存储（路径 (a)）：键对 kind=`transport_rejection_key`；不创建 `command_bindings` 行、不占用任何 `command_id`。[LATER]
- 独立授权拒绝审计行（授权前置拒绝）：键 = 调用安全上下文＋命令标识（同上下文同命令标识的重复拒绝幂等合并为一行）。[LATER]

---

## 2. 命令与流程

### 2.0 统一命令名列表（闭合，逐字）[P0B-CORE 为整体命令面]

```text
append_events  create_step  prepare_step  create_effect  seal_batch
retry_effect  dispatch_effect  complete_effect  request_cancel
transition_wait  transition_sleep  finish_session  fail_session  repair  reconcile
compact_lock  compact_finalize  compact_abort
compat_unmapped_audit  -- compat adapter 受限内部 audit 命令（未知 DSH 类型审计落盘；event_class=audit、非流事件）
FORCE_JOB_TAKEOVER  -- 受控内部操作（operator 显式授权的强制 job 接管；非普通 recovery）
```

capability 映射（MUST）：`event_append` → `append_events`；`effect_submit` → `create_effect`；`compact` → `compact_lock`/`compact_finalize`/`compact_abort`（§3.3 compact 状态机三个受控命令入口——申请/finalize/abort 对应 `locked` 进入与终态转移；名称不是第二套状态机）。compact 三命令全部受统一命令合同约束：envelope 携带 `command_id`/`command_request_hash`、receipt 与 `command_bindings` 首占实际 outcome、固定锁序 compact 锁位（末位）、授权经 `compact` capability 有效 grant。

`stream_ingest` **不映射为独立命令**——它是公开 `append_events` 追加 `assistant/chunk`（白名单观测类）时叠加于 `event_append` 之上的第 (6) 项调用方归属校验输入，不构成第二事件入口。`fail_session` 是受控内部入口而非独立公开失败路径：仅可由 §3.1.1 列出的三类来源触发，公开调用者 MUST NOT 指定任意 `failure_code`。`FORCE_JOB_TAKEOVER` 同为受控内部入口：受统一命令合同约束（envelope/computed hash/receipt 与首占语义），receipt 与 audit MUST 记录 operator 身份与接管原因；普通 recovery 命令 MUST NOT 携带或触发该语义。

### 2.1 通用 envelope 与事务合同 [P0B-CORE]

- 所有写命令 MUST 携带 `command_id, session_id, driver, driver_epoch, command_request_hash`（调用方按同一 canonical profile 计算并声明的值；SQL 一律重算为 `computed_request_hash`，receipt 与 binding 一律以 computed 为准）。
- 协调/repair/compact 命令另带当前 `session_fence`；completion 带 §3.2.2 的 attempt envelope；取消由已授权控制调用者请求；compact 三命令另经 `compact` capability 有效 grant 授权。
- 调用方 MUST 首次发送前生成 command_id，response-loss retry MUST 原样复用全部输入。
- **envelope driver/epoch 注（L4-U03）**：envelope 携带的 `driver`/`driver_epoch` 与 session 当前值不匹配 → `rejected_stale`；唯一例外——`session/heartbeat` 于 session `quiescing` 态：该类型校验降级为记录不匹配、不拒绝（仅记提交 epoch；MUST NOT 续租/推进 fence，零控制态）。[LATER]
- `command_request_hash` MUST 由 SQL 按 canonical profile 重算，覆盖 command kind、目标 identity、expected seq/fence 和完整 payload（输入 = 完整 payload 的已转义表示，§1.3 规范步骤 0 → profile 管线）；MUST NOT 与 effect 的不可变 `request_hash` 混用。
- **八位主锁序（冻结）**：事务 MUST 按 `session→grant/slice→generation→step→effect→attempt→turn_end_slot→compact` 固定顺序加锁。
  - `turn_end_slot` 槽位行锁为第七位（attempt 之后、compact 之前）；仅由触及槽位的入口介入：`complete_effect`（provisional end 创建/已知终结 end 写槽位/未知收束触及槽位）、`request_cancel` 收束、`repair`（经唯一受保护槽位更新函数）、`reconcile` 收束及 `FORCE_JOB_TAKEOVER` 接管结算——一律 `SELECT ... FOR UPDATE`；MUST NOT 在取得槽位行锁后回取 attempt 及更前位行锁、MUST NOT 与 compact 行锁互换次序；其余事务不锁槽位行、锁链不变。
  - compact 锁行位于主锁序末位，仅由三个 compact 受控命令与 session 终态事务的受控 abort 子操作介入。
  - grant/slice 行锁仅由执行 §2.1 授权检查的事务介入（多行按 `(workspace_id, slice_id, grant_id)` 升序）。
  - generation 行锁由读取/修改 generation 状态的事务介入（两条 seal 路径共享读、`retry_cohort_allocation` generation 门、recovery 接管第 1 步完整八位预锁集共享读、§4 下线事务排他写）。
- 事务 MUST 在任何业务 mutation 前查询/占用 command binding 与 receipt 唯一键；并发相同命令只能有一个执行者。receipt、控制修改、事件和 job 入队 MUST 同事务提交；回滚后全部不存在。

### 2.2 receipt/binding 判定序（四步 + 三类拒绝路径，判定顺序固定）[P0B-CORE：序 (1)–(4) 与 canonical 路径；(a)(b)(c) 拒绝路径 LATER]

权限校验后，receipt 查找与 binding 绑定一律以类型化键对 `(receipt_key_kind, receipt_key_value)` 为准。调用方 envelope 携带的声明 hash 仅是校验对象，MUST NOT 作为 receipt 键或 binding 键，MUST NOT 仅凭声明 hash 命中另一 payload 的 receipt。**分流冻结**：第 (1)(2) 步三键共用（computed hash / rejection fingerprint / transport rejection key——查重、首占与冲突对三类键统一执行）；第 (3)(4) 步（声明 hash 校验与首次执行判定）仅适用于 `canonical_request_hash` 路径；`transport_rejection_key` 路径 (b) 与 `rejection_fingerprint` 路径 (c) 的请求无法计算 computed hash，MUST NOT 计算或比较 canonical hash，该两路径在无既有 binding 时直接以对应 transport/schema 拒绝结局（`rejected_mismatch`，保留具体 code）同事务写 binding 与 receipt，不进入第 (3)(4) 步。

1. **先查既有 receipt（含拒绝）**：执行资格判定前 MUST 先按 `(session_id, command_id, receipt_key_kind, receipt_key_value)` 查找既有 receipt——命中 → 幂等返回该原 receipt，无论原结局是 `accepted` 还是 `rejected_*`（原 accepted 原样返回，不再校验已变化的 seq/state/fence/epoch，不重复执行或增加 audit 计数）。仅是历史响应读取，MUST NOT 授予旧 owner 新写权限。
2. **command_id 占用**：`command_bindings` 语义是**首次可归属请求即占用 command_id**——首个进入命令命名空间的有效请求（无论最终结局为四类 `outcome` 中哪一类——`accepted`、`rejected_*` 或 `repair_required`）MUST 在同一事务占用 binding，记录首次键对与首次结局（`first_outcome`），不只绑 accepted。已占用后到达的不同键值（不同 computed hash 或不同拒绝键值）→ `IDEMPOTENCY_CONFLICT`：写 `rejected_mismatch` receipt（键为该不同请求的键对），MUST NOT 覆盖首次 binding；冲突拒绝 MUST NOT 毒化 accepted binding——首次为 `accepted` 时，匹配 `first_request_hash` 的重试仍按 (1) 返回原 accepted receipt，同冲突变体的重发也按 (1) 返回原 conflict 拒绝。
3. **声明 hash 校验（仅 binding 未占用时）**：声明 hash ≠ `computed_request_hash` → `REQUEST_HASH_MISMATCH` 拒绝（`rejected_mismatch`，保留该具体 code）：receipt 键与记录一律使用 computed hash、声明 hash 仅存入 payload 供审计，MUST NOT 执行命令；该拒绝同样按 (2) 占用 binding（首次结局=`rejected_mismatch`）——仅修正声明 hash 后复用同 `command_id`（payload 不变、computed hash 不变）MUST 仍返回原拒绝、不执行；须以新 `command_id` 重发方可执行。
4. **首次执行**：binding 未占用且声明 hash 与 computed hash 一致 → 进入完整身份/状态/业务 guard 判定（expected seq/fence/epoch、driver/mode、sticky cancel 与各命令自身 guard），在同一事务按**实际 outcome** 写 binding（`first_outcome`）与 receipt（首占与 receipt 原子提交）。声明 hash 校验通过本身不等于 `accepted`——首占结局可为 `outcome` 闭合集全部四类：guard 通过并执行 → `accepted`；guard 失败按既有分类落对应结局（旧 fence/epoch → `rejected_stale`；`TURN_ALREADY_CLOSED`/`GRANT_DENIED` 等身份/schema/guard/幂等冲突 → `rejected_mismatch`，保留具体 code；`REPAIR_REQUIRED` → `repair_required`）。
   - **expected seq 对 `append_events` 的适用范围限定（L4-U-R01）**：expected seq 检查位于全批校验与事件级查重之后、仅对含新插入条目的批次生效——全重复批次（所有条目命中既有事件——批内归并后逻辑条目集合口径，F2）按事件级幂等返回既有 identity/seq 区间、MUST NOT 校验 expected seq 或推进 `next_seq`（fence/epoch/driver/mode 不在该特例豁免范围）。

三类 transport/payload 拒绝路径（显式区分，三键作用域互斥、MUST NOT 混用，均绑定授权调用上下文）[LATER]：
- (a) **ID 不可归属**（无有效 `command_id`/`session_id`，无法进入命令命名空间）：以 `transport_rejection_key@v1`（= SHA-256(接入层收到的原始报文/帧字节)）记 `rejected_mismatch` 拒绝记录，写入独立 ingress/malformed receipt 存储（键对 kind=`transport_rejection_key`）；**不创建 `command_bindings` 行、不占用任何 `command_id`**——同报文重发按该键幂等返回原拒绝记录。
- (b) **transport 畸形**（有有效 ID，但声明 hash header 重复或缺失、payload 边界不可定位）：稳定拒绝（`rejected_mismatch`，保留具体 code）并同样以 `transport_rejection_key@v1` 记录，MUST 按 (1)(2) 同事务处理：无既有 binding 时占用 command binding（`first_outcome=rejected_mismatch`）；已有 binding 时按 (2) 落 `IDEMPOTENCY_CONFLICT`，首次键对与 `first_outcome` 均保持不变；同键重发按 (1) 幂等返回原拒绝。
- (c) **transport 合法但 payload 不可规范化**：按 §1.3 `rejection_fingerprint@v1`（输入 = payload 原始字节）记拒绝 receipt（`rejected_mismatch`），经分流占用 command_id；MUST NOT 计算或比较 canonical hash、不执行第 (3)(4) 步。
- 判定顺序固定：(b) 先于 (c)——transport 合法性是 payload 规范化判定的前提，两者同时不满足时以 `transport_rejection_key@v1` 记录（MUST NOT 退回 fingerprint）；(a) 与 (b)/(c) 由 ID 可归属性互斥。

### 2.3 outcome 闭合集与拒绝语义 [P0B-CORE]

所有进入命令处理的可归属请求，无论接受或拒绝，MUST 写稳定 receipt；`outcome ∈ {accepted, rejected_stale, rejected_mismatch, repair_required}`。旧 fence/epoch MUST 为 `rejected_stale`，identity/schema/guard/幂等冲突 MUST 为 `rejected_mismatch`（保留具体 code），`REPAIR_REQUIRED` MUST 为 `repair_required`。

**授权前置拒绝（receipt 命名空间之外，冻结）** [LATER]：先于一切 receipt/binding 处理的授权门拒绝（授权门保持最高优先、先于 receipt 幂等查重）位于命令 receipt 命名空间之外：MUST NOT 写 `command_receipts`/`command_bindings`、MUST NOT 读取或覆盖既有 receipt、不占用 command binding；MUST 写独立授权拒绝审计行——绑定调用安全上下文＋目标命令标识＋`GRANT_DENIED`，键 = 调用安全上下文＋命令标识（重复拒绝幂等合并为一行）；不入三键类型化拒绝 receipt 体系、不入 accepted 命名空间。不改变进入第 (3)(4) 步之后的 guard 阶段 `GRANT_DENIED`——该拒绝照常按 `rejected_mismatch` 写 receipt。

拒绝 MUST 不改业务 control/semantic event（显式例外两个 [LATER]：其一为语义层检查失败触发 `fail_session` 第 (3) 类 INFRA 收束的拒绝——如初始 decision seal 的 `DECISION_PLAN_INVALID`；其二为 §3.2.2 共享批次重试分配子操作第 4 步 generation 拒绝后的最终聚合——命中 §4 `GENERATION_REVOKED` 三合取时同事务写 generation 收束控制态）；但 receipt 与拒绝相关的 `effect_audit` MUST 在同一事务提交后才返回，MUST NOT 通过事务 rollback 丢失拒绝记录；无 effect 关联的拒绝只写 receipt。未知或无权访问的目标 MUST 在授权调用上下文下记录拒绝且不泄漏目标存在性；MUST NOT 借此跨租户查询 expected 值。

### 2.4 统一内部子操作审计合同（冻结）[LATER]

- 内部子操作闭合集为五类：`failure_drain`（§2.2 第 3 条 WORKSPACE_LOST failure-drain）、`shared_cancel_closure`（§3.2.2 共享取消收束子操作）、`compact_terminal_abort`（§3.3 compact lock 受控 abort——终态事务路径与 `compact_abort` 命令路径，后者 `parent_command_id` 为该命令自身 `command_id`）、`infra_closure`（§3.1.1 `fail_session` 第 (3) 类 INFRA 收束）、`generation_revocation_drain`（§4 强制下线收束）。
- 每类 MUST 携带统一审计 envelope：`parent_command_id`（触发该子操作的父命令 command_id）、`parent_session_id`（必填——`command_id` 的唯一占用是 session 内语义（`command_bindings` 以 `(session_id, command_id)` 为唯一键），跨 session 同名 `command_id` 是两个互不相关的命令；内部子操作审计的唯一索引与重放键由此以 `parent_session_id` 首列隔离）、source operation 与 internal operation identity（子操作类别 + 本次执行 identity）。
- **不立独立 command/receipt**（子操作不是命令），但子操作 audit MUST 绑定父 receipt：audit 行 MUST 含 `parent_command_id` 与 op identity，随父命令 receipt 同事务留存。
- `internal_op_ordinal`（bigint，自 0 起单调递增，CHECK >= 0）：父命令事务内分配、不可变（写入后禁止 UPDATE）。
- **ordinal 分配规则（冻结）**：先按五类全序定类间次序，同类多目标之间按目标对象 identity 的确定性字节序稳定排序（UUID 一律 RFC 9562 16 字节 binary、非 UUID 文本 UTF-8 原样——与 `event_key@v1` 第 (iv) 条同款表示）；分配在父命令事务内一次性完成、不可变。「五类全序 × 同类目标字节序」唯一确定——同类同目标必然同 ordinal、命中唯一索引合并为单条 audit。
- **固定调用顺序（五类全序，冻结）**：`generation_revocation_drain → infra_closure → failure_drain → shared_cancel_closure → compact_terminal_abort`（资源性收束最先、compact abort 最后）。同一事务内子操作的执行与 audit 落盘顺序即 `internal_op_ordinal` 升序——ordinal 顺序、执行顺序、落盘顺序三者同一。异类子操作各自独立 audit、互不合并。
- **重放序（冻结）**：一律按 `(parent_session_id, parent_command_id, internal_op_ordinal)` 三元组升序读取（同 session 内即按 `(command_id, internal_op_ordinal)` 升序）；MUST NOT 依赖 `created_at` 或物理插入序。
- 内部子操作 audit 不分配 `session_events.seq`、不参与 semantic/portable trace（`compaction/end` 等既有 session_events 审计事件不受影响、仍正常分配 seq）。
- 显式声明：非独立命令 ≠ 无 identity/幂等/审计——子操作恒有 identity（op identity + 目标对象 identity + `internal_op_ordinal`）、恒有幂等（唯一索引）、恒有审计（绑定父 receipt），缺任一即实现缺陷。

### 2.5 命令表（逐行：receipt 的稳定结果与额外约束）

| 命令 | receipt 稳定结果与额外约束 | 标注 |
|---|---|---|
| `append_events` | **批次合同（冻结）**：先对全部条目完成校验与去重（类型权限矩阵、chunk 六项归属校验、逐项事件键查重——任一条目校验失败 → 整批原子拒绝、零事件落盘、`next_seq` 不推进，不存在部分插入中间态）。receipt 为**双部分**：(1) 按输入序的逐项事件 identity/seq 映射——已存在条目（semantic 条目查重判据 = ordinal × 完整事件内容比较域、chunk 条目 = 四元组 × 内容）返回其已有 seq、新条目返回其新分配 seq、批内归并条目的全部输入位置映射同一新 `event_key`/seq（F2）；(2) 本次**新插入事件**的连续 seq 区间（可空——全重复批次为空区间）；区间长度 `n` 仅指本次新插入事件数（非批次条目总数；批内归并条目计一次——`n` 与「全重复/含新条目」分类一律按归并后逻辑条目集合，F2）；`session_events` 无洞不变量仅约束该新分配区间（`next_seq..next_seq+n-1` 连续）；越权类型稳定拒绝（`EVENT_TYPE_RESTRICTED`）；`assistant/chunk` 另受六项归属校验（任一不满足稳定拒绝 `CHUNK_ATTRIBUTION_INVALID`，零事件落盘）；semantic 条目（含混合批次）的唯一执行路径与双幂等七步序见 §2.8 | [P0B-CORE] |
| `prepare_step` / `seal_batch` | MUST 共用唯一 seal 实现（初始 decision seal 与 tools seal 两条路径）；返回原 decision result identity 与 plan_hash（tools seal）、batch_id、sealed_batch_no、effect_id 有序列表和 seal receipt identity，MUST NOT 建立另一套 stage 状态机；两条路径同事务检查 step 绑定的 `catalog_generation` 状态——已为 `failed` 时稳定拒绝（闭合 code `GENERATION_REVOKED`，零副作用）；两条路径同事务执行 seal 授权阶段（在创建任何 batch/effect/attempt 之前按 §2.1 实时授权本次将创建的全部 effect——grant/slice 行锁按固定锁序先于 generation 行锁取得；任一成员失败 → `GRANT_DENIED` 零副作用稳定拒绝） | [P0B-CORE：初始 decision seal 路径；tools seal LATER] |
| `create_effect` | 原 effect_id；公开模式：MUST 通过 §3.2.2 不可变 batch-slot 校验（batch 必须已 seal）与创建 CAS；seal 后同 slot 同请求仅返回已有 effect，不得补建或改变成员（seal 事务内部成员创建经受控子操作 `create_effect_in_seal`） | [LATER] |
| `reconcile` | 原 switch/recovery/结果接收的动作与结算 identity；MUST 遵守 §3.1.1 mode guard（含 `begin_switch` 安全点，不满足返回稳定 `SWITCH_DEFERRED`）和 §3.2.2 旧 attempt 失效流程，MUST NOT 绕过 repair 证据要求；其结果接收子操作与 `complete_effect` 共用 §3.2.2 两层验证与流事实判定四步序（X01 两入口共用序——reconcile 结果接收是 quiescing 下唯一合法终局结算入口、结算路径不套 `DRIVER_QUIESCING`；reconcile 结果接收遇字段矩阵 (iii)/(iv) 形态 MUST NOT 终局结算、MUST NOT 写 stream_progress/observation，固定拒绝闭合 code `OBSERVATION_WRONG_ENTRY`（receipt `rejected_mismatch` 保留 code、零控制态修改）） | [LATER] |
| `complete_effect` | 终局结算返回 attempt 结果及 seq 并由 SQL 生成 canonical 语义事件（worker MUST NOT 附带任意 events[]）；(0) 矩阵 (ii)/(v)（`known_success` ∧ streaming ∧ `stream_complete` 缺失或 true 无计数）→ 结构层 schema reject（证据分类之后、零控制态，四步序第 (iii) 步，W02），不走下三款、不占单次终局结算约束；`stream_complete=false` 分流按 Y01 同一谓词三款：(1) **仅当**四步序判定为矩阵 (iii)/(iv) 且五款状态门接受 → 返回 observation identity 三元组（receipt `result_canonical`）、生成 `stream_progress` 观测事件、不生成终局语义事件、不占单次终局结算约束——观测路径 MUST NOT 调用 §3.2.1 聚合；MUST NOT 修改 `sessions.state`/协调 lease/`session_fence`/`cancellation_epoch`/`steps.status`/聚合计数列；写集 = observation receipt + `stream_progress` 观测事件 + 规定 audit（AF01）；观测 MUST NOT 触发 `shared_cancel_closure`、MUST NOT 写 `COMPLETED_AFTER_CANCEL`/`RETRY_SUPPRESSED_BY_CANCEL`；(2) `stream_complete=false` 但非 (iii)/(iv)（非 `known_success` / 非流式）→ **终局**路径（按证据收束；quiescing 下本命令终局仍 `DRIVER_QUIESCING`）；(3) (iii)/(iv) 但五款状态门拒绝 → 对应拒绝码，MUST NOT 写 `stream_progress`；不同 command_id 不能重复结算同一 attempt（单次结算约束仅约束**终局结算**——仅 (1) 款非终局 stream observation 不占用该约束）；本行不覆盖 reconcile（遇 (iii)/(iv) 仍 `OBSERVATION_WRONG_ENTRY`） | [P0B-CORE：非流式 known_success 终局路径 + assistant message 事件；流式观测款 (1)(3) LATER] |
| `repair` | 原 resolution/closer seq；`UNIQUE(session_id,repair_id)` MUST 校验相同 repair payload，且 effect resolution CAS 防止不同 repair_id 重复修同一版本 | [LATER] |
| `compact_lock` | 原 compaction identity（`compaction_id` 与冻结的 `base_seq`/`through_seq`）；受 §3.3 冲突矩阵约束（存在任一非终态 LLM effect → 稳定拒绝 `COMPACT_BUSY_EFFECTS`）与该节状态机 guard；既有历史行命中按 §3.3 七步定位序（授权/归属最高优先＋receipt 幂等前置——同 `command_id` receipt 命中即原样返回，不再校验 lease/历史/fence/参数；lease 要求位于业务判定段 (6)(a)——统一前置分流为步骤 (5)）同款分类（完全一致 → 幂等返回原 compaction identity；范围/payload/目标身份不一致 → `IDEMPOTENCY_CONFLICT`） | [LATER] |
| `compact_finalize` | 原 compaction 结果 identity 与 `compaction/end` 审计事件 seq；MUST 以 owner+fence CAS 提交，按冻结范围（`seq <= through_seq`）产出结果；stale owner → `STALE_COMPACT_FENCE`；终态历史行重放按 §3.3 七步定位序（receipt 幂等前置；统一前置分流步骤 (5) 后 lease 要求与终态 replay 判定序五步：授权/归属 → lease（terminal session 允许无协调 lease 只读 replay）→ stale fence → 参数一致 → 幂等返回）（终态行存在 → 与历史冻结值校验：完全一致 → 按行终态幂等返回 `finalized` → 原 `result_identity`（= `compaction_result_digest@v1` 独立摘要——非 event_key）、`aborted` → 原 `abort_identity`（= 绑定 `compact_terminal_abort` 审计的 `event_key`）；范围/payload/目标身份任一不一致 → 固定 `IDEMPOTENCY_CONFLICT`（不返回旧结果、不产出事件）；owner fence 已被接管推进 → `STALE_COMPACT_FENCE`；均不产出第二次结果事件） | [LATER] |
| `compact_abort` | 原 abort identity（持久化为 `compactions.abort_identity`，状态条件绑定 `status='aborted'` 非空 / `finalized` 为 NULL）；MUST 以 owner+fence CAS 提交、释放 lock 回 `idle`、MUST NOT 产出 compaction 结果事件；stale owner → `STALE_COMPACT_FENCE`；终态历史行重放同 §3.3 七步定位序（终态 replay 判定序五步同款：`aborted` → 原 `abort_identity`、`finalized` → 原 `result_identity`；范围/payload/目标身份任一不一致 → 固定 `IDEMPOTENCY_CONFLICT`；owner fence 已被接管推进 → `STALE_COMPACT_FENCE`） | [LATER] |
| `compat_unmapped_audit` | 原 `compat/unmapped` audit 事件 identity 与 seq 区间；envelope MUST 携带 adapter identity、fixture digest、未知 DSH 类型的 canonical identity 与 payload hash（computed hash 按统一合同重算）；调用方为该 session 绑定的受权 compat adapter（adapter identity 经命令 envelope 校验）；受统一 receipt/binding（`command_id` 首占实际 outcome；同 `command_id` 同 payload 幂等重放返回原 audit 事件，不同 payload → 稳定 `IDEMPOTENCY_CONFLICT`）；写入 `compat/unmapped` 事件（`event_class=audit`、正常 seq 分配、`event_key` 为非流事件数据库内部派生——事件键第 (1) 层 (b)）；不改变业务调度状态与 effect/step 结算状态——统一 seq 分配器、receipt/binding 与规定审计的元数据写入不受此限（「使 fixture 失败」是验收报告状态——audit 落盘即该 fixture 失败标志，验收层判定非控制态）；MUST NOT 写任何 effect 语义结果类事件 | [LATER] |
| `FORCE_JOB_TAKEOVER` | 原接管结算 identity（成功时：旧 attempt 结算结果与（如批次判定命中）cohort 新 attempt 分配的 identity）；专用 envelope（统一字段之上另携）：目标 `effect_id`/`attempt_no`、expected effect 级 `current_job_fence`、expected job lease owner+expiry、operator identity（canonical 表示，经 operator 控制面授权校验——复用 §2.1 grant 模型（subject_kind 按既有闭合集）或既有 operator 显式命令通道）、force reason（canonical 字节，非空、长度上限见 §3.2.2 冻结值）；固定 outcome 闭合四类：成功（按 §3.2.2 普通接管第 2–4 步同款原子语义执行）/目标不存在或已终态（`rejected_mismatch`，保留具体 code）/job fence 或 lease 已被取代（`rejected_stale`）/普通 guard 未禁止时使用（`rejected_mismatch`，闭合 code `FORCE_NOT_REQUIRED`）；使用前置（仅当普通 recovery guard 因 job lease 仍有效而跳过时可用）、判定序与重放/多命令语义唯一见 §3.2.2 接管流程第 2 步 | [LATER] |

命令表中无独立行的命令（本段仅列名，合同在别处）：`create_step`（受控子操作/命令，合同在 §3.1 前半「§3.1 `create_step` 合同」）、`dispatch_effect`（合同在 §3.2.2 派发门 `ready -> dispatch_started`——P0B 要求「只绑定既有 attempt、不补建」）、`retry_effect`、`request_cancel`（合同在 §3.1.1/292 行，粘性停止）、`transition_wait`/`transition_sleep`、`finish_session`（§3.1.1；以 `decision_only=true` 判定 turn 关闭）、`fail_session`（§3.1.1 三类来源）。

### 2.6 seal 两条路径（`prepare_step` 与 `seal_batch` 是同一原子 seal 实现的两个入口，按 CAS 前置状态显式区分）

#### 2.6.1 初始 decision seal [P0B-CORE]

CAS 前置：step 经受控子操作 `create_step` 在本事务内创建、创建即 `planned, stage=decision`。同一事务内 MUST：

1. 创建 step（经受控子操作 `create_step`，创建即 `planned, stage=decision`）。
2. **seal 授权阶段（第一道实时门，两 seal 路径同款合同）**：在创建任何 step（成员）/LLM slot/batch/首个 attempt 之前，MUST 按固定锁序取得本次将创建的全部 effect（本路径即唯一 LLM slot）的相关 grant/slice 行锁（grant/slice 锁位在 generation 行锁之前，多行按 `(workspace_id, slice_id, grant_id)` 升序），并对每个将创建的 effect 按其具体参数执行完整授权检查（§2.1 有效 grant 全部合取条件 + slice-membership + 参数级 `authorize_effect`）——任一成员授权失败 → 整个 seal 零副作用稳定拒绝（`GRANT_DENIED`，receipt `rejected_mismatch` 保留该 code：不创建 step（成员）、LLM slot、batch、首个 attempt 或 seal receipt，仅写规定的拒绝 receipt 与 audit；assemble manifest 快照不豁免本阶段授权——assemble 之后、seal 之前发生的撤销 MUST 使本 seal 拒绝；§3.2.2 dispatch 门的授权检查是第二道实时门，MUST NOT 替代本阶段授权）。[seal 授权阶段整体 LATER——P0B 最小闭环未含 grant 模型；其余步骤 P0B-CORE]
3. **generation 检查**紧随授权阶段（同源按 tools seal guard 2 检查 step 绑定的 `catalog_generation` 状态，同事务读取）——已为 `failed` 时 MUST 稳定拒绝（闭合 code `GENERATION_REVOKED`，receipt `rejected_mismatch` 保留该 code；零副作用；线性化：seal 事务共享读 vs 下线事务排他写，均对 generation 行加锁、先提交者赢——下线先提交则 seal 拒绝且不创建任何 LLM slot，seal 先提交则其未 dispatch effect 由下线事务重扫描 drain 收束）。[LATER——§4 generation 域]
4. 创建并密封唯一 LLM slot：该 LLM effect 的成员创建经 `create_effect_in_seal`，同事务创建其**首个 attempt**：`attempt_no=1`，冻结初始 fence/envelope 必要字段——`dispatch_job_fence`（初值即同事务新分配并写入 effect 级 `current_job_fence` 的 fence 值，**两者同值冻结**，§3.2.2 双 fence 拆分）、`driver`/`driver_epoch` 与 `session_fence`/`dispatch_session_fence`（创建 attempt 时冻结的执行快照，§3.2.2 双表权威性冻结——envelope 校验读 attempt 行权威值）、`request_hash`/`idempotency_key` 等 §3.2.2 既有 ABI 字段，status 为待派发；**首个 attempt 的唯一创建入口即 seal 事务成员创建**（§3.2.2 effect_attempts 分配规则）。[P0B-CORE——P0B 断言「首个 attempt」「双 fence 基本语义」的落点]
5. 写 `sealed_batch_no` 与唯一 batch identity；step 创建与 seal 同事务发布（§3.1 `create_step` 合同，与 `create_effect_in_seal` 同模式）——**不存在「已创建、未 seal、无 LLM slot」的持久化中间态**，也不存在对既有未 seal step 的独立校验/接管路径。[P0B-CORE]
6. **发布即 ready（冻结）**：seal 事务内在创建首个 attempt 后、同一事务将已密封 effect 直接写为 `ready`（`planned` 仅为 seal 事务内的临时构建态——成员创建时的构建值、事务内即被覆盖为 `ready`，**不存在持久化的 planned effect**；派发门 `ready -> dispatch_started` 对该 effect 提交后立即可见）。[P0B-CORE]
7. 事务内命中 seal CAS 拒绝条件（含 sticky cancel 已设）时 = 整个 seal 零副作用拒绝、不发布任何成员（planned 取消即整个 seal 拒绝，不存在事务内逐成员转 `cancelled_before_dispatch` 的路径）；CAS 同时校验 driver/epoch/fence、active mode、无 sticky cancel。[P0B-CORE]
8. 聚合为 `waiting_effect`，不得暴露未密封或部分密封的批次。[P0B-CORE]

成功 decision result 的持久化（已进入终局结算——流式仅字段矩阵形态 (i)，非流式 `known_success`，Y02/Conf 5 同一口径；pending observation 排除）MUST 持久化 `decision_result_identity=(effect_id, attempt_no, result_hash, event_key)`（`event_key` 为该语义结果事件的原始事件键）、规范化 tools plan 与显式 `decision_only` / `final_tools` 标记。[P0B-CORE]

**标记组合冻结为双向互斥穷尽 schema**（合法组合仅两种，其余一切组合无聚合出口——无 tool calls 不能等 seal、非 `decision_only` 不能关闭 turn、单一活跃 step 又阻止新建）：空 tools plan ⟺ `decision_only=true`，且该分支 `final_tools` MUST 固定持久化为 `false`；非空 tools plan ⟺ `decision_only=false ∧ final_tools=true`。其余一切组合（含 空 plan × `decision_only=false`（`final_tools` 任意）、空 plan × `decision_only=true` × `final_tools=true`、非空 plan × `decision_only=true`（`final_tools` 任意）、非空 plan × `final_tools=false` 等）MUST 稳定拒绝 `DECISION_PLAN_INVALID`（receipt 分类落 `rejected_mismatch`、保留该具体 code）。该检查属 §3.2.2 两层验证的语义层（时序限定 X02＋Y02：仅已进入终局结算的成功 decision result 触发；不属 §1.3 canonical schema——被拒 payload 可正常规范化，receipt 键为 computed hash）。[P0B-CORE——P0B 闭环走 `decision_only=true` 空 plan 分支]

被拒结果的收束（同一事务确定性完成，不留中间态）[LATER]：该拒绝同时将对应 LLM effect 落 `failed_terminal`（code 复用既有闭合 `INFRA_PROTOCOL_VIOLATION`，`retry_stop_reason` 同事务按 §3.2.2 全路径唯一有序分类函数持久化；预算原因 MUST NOT 改变 effect code 与父层 INFRA code），step/session 按 §3.1.1 `fail_session` 第 (3) 类 INFRA 路径同事务收束（session `failed`/`INFRA_PROTOCOL_VIOLATION`，未完成 step `failed_terminal`/`INFRA_PROTOCOL_VIOLATION`）；父层 code 优先级限定（冻结）：若 session 已有持久化 failure cause（`WORKSPACE_LOST` 或既有 INFRA code），本拒绝仍将 effect 落 `failed_terminal`/`INFRA_PROTOCOL_VIOLATION` 并留 audit，但 session `failure_code` MUST 保持既有 cause（INFRA code 仅记录于 effect/audit 层，MUST NOT 改写父层 code）。

额外模型决策 MUST 新建 step，不存在由 coordinator 推断的非最终 tools 批次。显式持久化的 `decision_only=true` 是唯一的 turn-complete 信号：§3.2.1 聚合规则 6 与 §3.1.1 `finish_session` 共用该持久化字段判定 turn 是否关闭，不新增第二字段、不依赖 coordinator 内存推断。[P0B-CORE]

#### 2.6.2 tools seal（CAS 前置 `ready, stage=decision`）[LATER]

有 tool calls 的已进入终局结算的成功 decision result（同口径——流式仅形态 (i)，非流式 `known_success`）MUST 将 step 聚合至 `ready, stage=decision`，冻结该 result identity 与 `plan_hash`，MUST NOT 提前创建 tools。四步：

1. MUST 先查 command receipt 与唯一 seal receipt（tools seal 按该 decision result 的 seal receipt；初始 decision seal 按该 step 首个 batch 的 seal receipt）；相同 result/batch identity、plan_hash 及 slot payload 重放（即使换 command_id）MUST 仅返回原 seal receipt，并为新 command_id 保存引用原结果的 receipt；不一致 MUST mismatch。
2. MUST 锁 session/step（多类行锁一律按固定锁序——grant/slice 与 generation 行锁位于 step 行锁之前），CAS 校验 `status=ready, stage=decision`、expected sealed_batch_no、driver/epoch/fence、active mode、无 sticky cancel；seal 授权阶段（与初始 decision seal 同款合同——manifest 全体 slot）；generation 检查紧随授权阶段（已为 `failed` → `GENERATION_REVOKED` 零副作用稳定拒绝；线性化：检查共享读 vs 下线排他写，先提交者赢——seal 先提交不豁免未 dispatch tool effect 的 drain 收束）；MUST 核验该 step 已接受的 decision result identity，按持久化 plan 重算并匹配 `plan_hash`、显式 `final_tools=true`。该 identity 不区分来源：repair 路径为被证实成功的 decision effect 持久化的 `decision_result_identity` 与规范化 tools plan MUST 与正常 completion 写入的同构，可被本条 CAS 与 `plan_hash` 重算原样消费，MUST NOT 因来源为 repair 而另建第二套 identity、豁免核验或绕过重算。
3. MUST 在同一事务一次性写 `stage=tools`、`sealed_batch_no+1`、唯一 batch identity、完整 slot manifest 及全部 tool effect，密封 batch 并聚合至 `waiting_effect`。成员创建经受控子操作 `create_effect_in_seal`，两模式区分：`create_effect_in_seal` 对同一事务内 manifest 已冻结、sealed 标记尚未发布置位的 batch 创建成员，**不受 §3.2.2 公开 `create_effect` 的「batch 必须已 seal」前置约束**，并 MUST 在同一事务为该 effect 创建首个 attempt（`attempt_no=1`，冻结字段同初始 decision seal 第 4 条——dispatch_job_fence/current_job_fence 同值、执行快照、request_hash/idempotency_key，status 待派发；首个 attempt 唯一创建入口即 seal 事务成员创建，后继 attempt 仅经 §3.2.2 `retry_cohort_allocation` 两入口分配），事务末尾一次性置 sealed（原子发布）——不存在「未 seal 不能创建、已 seal 不能补建」的前置循环；各 tool effect 同款「发布即 ready」合同；事务内取消/CAS 拒绝 = 整个 tools seal 零副作用拒绝、不发布任何成员；公开 `create_effect` 仅在已 sealed batch 上执行既有同 slot 同请求 lookup/replay CAS，MUST NOT 插入新成员。不得暴露部分 batch 或先提交 slot 再补 effect。
4. 只有已持久化 `decision_only=true` 的成功 decision 或 `final_tools=true` 的全成功 tools batch 才可成功 terminalize；MUST 写 `stage=closed`。失败/取消终态仍按 §3.2.1 矩阵收束，不受成功标记限制。

#### 2.6.3 pending observation 排除段（显式，AA01——两条 seal 导语的反向边界）[LATER]

字段矩阵形态 (iii)/(iv)（`stream_complete=false` 的 pending stream observation——`known_success` ∧ 流式适用域内）MUST NOT 写 `decision_result_identity`、MUST NOT 冻结 `plan_hash`/`decision_only`/`final_tools`、MUST NOT 将 step 聚合至 `ready`（tools seal 前置的 `ready, stage=decision` 聚合在内）/`succeeded`、MUST NOT 生成 `assistant/message` 等终局语义事件——五款状态门接受时写集 = observation receipt + `stream_progress` 观测事件 + 规定 audit（observation receipt 即 `result_canonical` 三元组；零结算：控制态零修改、不触任何 seal 前置）；观测 MUST NOT 触发 `shared_cancel_closure`、MUST NOT 写 `COMPLETED_AFTER_CANCEL`/`RETRY_SUPPRESSED_BY_CANCEL`；门拒绝或 `OBSERVATION_WRONG_ENTRY` 仅写拒绝 receipt/audit（四步后分流第 (1) 分支：仅 `complete_effect` 五款状态门入口，`reconcile` 固定 `OBSERVATION_WRONG_ENTRY`）。

### 2.7 append_events 冻结事件类型权限矩阵（闭合）

- **语义结果类事件**——`assistant/message`（final）、`tool/result`、`turn/end {interrupted:true}`、`turn/end {outcome:unknown}`、repair closer 等（凡由 effect 终局/收束产生的语义结果）——MUST 仅由**数据库内部命令**（`complete_effect` / `repair` / seal / `request_cancel` 收束 / `reconcile`）生成并绑定其生成 identity（completion/repair/seal receipt、effect 终态、decision result identity）。[P0B-CORE]
- 公开 `append_events`（含 §5 compat append facade）仅允许版本化精确枚举的白名单 **`public_append_types@v1 = {user/message, turn/start, agent/inject, assistant/chunk, session/heartbeat}`**（闭合集：输入类 `user/message`、`turn/start`、`agent/inject` 与观测类 `assistant/chunk`、`session/heartbeat`；MUST NOT 以「等」类开放措辞或运行时参数扩展，新增事件类型 MUST 发布新的 whitelist 版本号且旧版本集合不可变）。[P0B-CORE——user/message 是 P0B 入口]
- 越权事件类型 MUST 稳定拒绝（闭合 code `EVENT_TYPE_RESTRICTED`，receipt 落 `rejected_mismatch` 并保留该具体 code）。[P0B-CORE]
- **`session/heartbeat` 拆分注记（P01，废弃拆分）** [LATER]：早期草案以单一裸类型 `heartbeat` 横跨两套 occurrence identity 规则——已废弃拆分为 `session/heartbeat`（公开 append 白名单观测类：会话级、无 attempt 归属，occurrence identity 按公开条目既有规则 `(command_id, batch_item_ordinal)`；不参与 lease 所有权与续租判定（非免授权——授权栈照常适用），L4-R06/S05）与 `attempt/heartbeat`（数据库内部观测事件：不在本白名单，identity 按 O01 (α) `(effect_id, attempt_no, observation_kind, observation_ordinal)`、observation_kind `heartbeat`；授权按 §3.1.1——attempt 归属 + 未终态 + 当前 job lease owner（fence 匹配；quiescing/terminal failure-drain 旧 epoch 例外、audit 记 epoch），superseded/lease 失效固定 `rejected_stale`，L4-R06）；裸 `heartbeat` 自两边移除——公开 append 提交裸 `heartbeat` 或 `attempt/heartbeat` 均稳定拒绝 `EVENT_TYPE_RESTRICTED`。本集合修订发生于首次落盘实现之前（@v1 从未实现或部署，沿版本化键首次落盘精确化先例——同 `malformed_binding_fingerprint@v2` 模式）。
- **session 生命周期拒绝（Q03）** [LATER]：terminal session 上的公开 append 白名单类型中，除 §3.1.1 terminal 子协议矩阵 (c) 迟到合法归属 `assistant/chunk` 外一律稳定拒绝（闭合 code `SESSION_TERMINAL`，落 `rejected_mismatch` 保留该 code、零事件落盘）；`attempt/heartbeat` 等 attempt 级观测在 attempt 已终态时由受保护观测写入函数稳定拒绝。
- MUST NOT 借 append 绕过 effect ledger 直接制造语义结果——`event_key` 唯一性仅作为兜底防线，不是第一道门。
- `compat/unmapped`（audit）不在该白名单内：公开 append 追加同样 MUST 稳定拒绝 `EVENT_TYPE_RESTRICTED`；其唯一合法写入路径是正式统一命令 `compat_unmapped_audit`（见命令表）。[LATER]

### 2.8 公开 `assistant/chunk` 归属校验（六项，同一事务，冻结）[LATER]

白名单内的 `assistant/chunk`（含 §5 compat append facade 写入——compat adapter 即受权 caller）MUST 在同一事务通过全部归属校验方可追加：

1. `effect_id` 属于当前 session 的已持久化 effect；
2. `attempt_no` 为该 effect 已持久化 attempt 行中的当前执行 attempt（最大 `attempt_no`）或已接受结算的 attempt；
3. `stream_id` 可归属该 effect 绑定的 provider/adapter（经其 grant/driver 链——`stream_id` 由 provider 流或 compat adapter 按该绑定分配，§1.2；不可归属或归属他 effect/provider 流的 `stream_id` 拒绝）；
4. 该 effect 已进入 `dispatch_started`（按持久化 dispatch marker 判定，chunk MUST NOT 先于派发到达）；
5. `chunk_index` 值域与重复/乱序约束（值域语义与 §1.2 冻结一致）——同 `(effect_id, attempt_no, stream_id, chunk_index)` 同内容按既有规则幂等去重（流事件 `event_key` 由该四元组按版本化派生规则确定性派生、append 查重先按四元组定位），同四元组异内容按既有路径处理（§1.2 `CANONICALIZER_CONFLICT` 稳定拒绝、不落盘第二条），乱序到达（含暂留空隙，如 `2,0,1`）照常接受、MUST NOT 拒绝——到达顺序与连续性不参与合法性判定；值域非法仅限负值、非整数两类（值域 `0 ≤ chunk_index ≤ 2^63-1`）、各稳定拒绝——超 `2^63-1` 上界的输入已在 canonical schema 先行校验层按既有 code 路径稳定拒绝（§1.3），不到达本项；
6. **调用方归属校验（三合取，冻结）**——(i) 调用方持有有效 `event_append` grant（基础能力，§2.1 全部合取条件 + slice-membership——chunk append 不豁免基础 append 能力）；(ii) 调用方持有有效 `stream_ingest` grant（双 grant 合取注记——持有 `stream_ingest` 而缺 `event_append` 同样拒绝）；(iii) **身份全匹配**——公开 append 调用方的 `caller_subject` MUST 匹配该 effect 绑定的 provider/adapter（经其 grant/driver 链解析——与第 (3) 项 stream_id 归属同源同链），且其 driver/epoch 与该 attempt 创建时冻结的绑定一致（读 attempt 行权威执行快照）。缺任一项均属失败。

任一不满足 → 稳定拒绝 `CHUNK_ATTRIBUTION_INVALID`（闭合 code，落 `rejected_mismatch` 保留该具体 code）：零控制态修改、不追加任何事件（未归属/被拒 chunk 不落盘）；canonicalizer 按 §1.2 消费前提注只消费通过本校验的 chunk。

### 2.9 公开 semantic append 的唯一实现路径（受保护数据库函数，七步顺序冻结，L4-U02）[P0B-CORE]

公开 `append_events` 批次（semantic 条目与观测条目的混合批次同函数原子完成——批次合同既有原子性即由本函数承载）MUST 封装为**唯一受保护数据库函数**执行——命令 receipt/binding 判定序 (1)–(4) 在其外层照常先决（同 `command_id` 幂等重放经 receipt (1) 命中返回、不进入本函数），函数承载通过判定后的批次执行，**不存在第二实现路径**；函数内七步顺序冻结、MUST NOT 合并/跳过/互换：

1. **session 行锁**——按八位主锁序首位取得 session control row 行锁（两并发公开 append 由此串行化，后到者在锁内重读全部判定输入）。
2. **全批次结构/权限校验**——批次合同全部校验与去重前置：类型权限矩阵（越权 `EVENT_TYPE_RESTRICTED`）、envelope/批次结构与 `semantic_input_ordinal` 携带/值域、**semantic 条目必填字段清单（W03）**——`event_type`、`schema_version`、`canonicalizer_version` 与归属三元组 `(turn_id, step_id, effect_id)` 列为 semantic 条目（`user/message`、`turn/start`、`agent/inject`）的 envelope 必填项：任一必填缺失（条目未声明该字段）→ envelope 结构拒绝（`rejected_mismatch` 保留具体 code、整批原子拒绝、零事件落盘），MUST NOT 落到第 (4) 步 ordinal 比较域冲突——`IDEMPOTENCY_CONFLICT` 仅承载「必填字段组完整在场而值互异」的比较冲突；归属三元组的「必填」指归属声明到场：不适用分量以显式 NULL 或按事件类型固定的 NULL 归属规则唯一确定其值（NULL 是值、不是缺失）；**公开 semantic 输入归属矩阵（冻结，X03——3 类 × 3 分量，唯一定义见 §1.2，本步为其执行落点）**：三个输入类白名单类型的归属三元组取值一律 `turn_id` MUST 非 NULL、`step_id`/`effect_id` MUST 固定 NULL（`agent/inject` 的 `turn_id` 指定注入位置——cutoff 语义衔接 §3.3）；违反 → 本步 envelope 结构拒绝、MUST NOT 落到第 (4)/(5) 步（即使同 `semantic_input_ordinal` 既有事件在场亦然）；chunk 六项归属校验、session 生命周期门（quiescing 拒语义输入；terminal 拒绝除矩阵 (c) 迟到 `assistant/chunk` 外的公开类型——混合批次含任何不允许条目仍整批拒绝，L4-U02/U-R02）；任一条目失败 → 整批原子拒绝、零事件落盘、`next_seq` 不推进（本步不含 expected seq 校验）。
   - **expected seq 特例（L4-U-R01，冻结）**：expected seq 校验不属第 (2) 步前置——位于全批校验与逻辑 ordinal 查重（第 (3)–(5) 步）完成之后、按批次形态二分：全重复批次（所有逻辑条目命中既有事件——批内归并后集合口径、归并条目计一次，F2）→ 直接返回既有 identity/seq 区间，MUST NOT 校验 expected seq、不推进 `next_seq`（幂等重放语义——与命令级 receipt 重放「不再校验已变化的 seq/state/fence/epoch」同款分层，本特例作用于跨 `command_id` 的事件级查重命中；driver/epoch/fence 校验不在豁免范围）；存在新插入条目 → 才校验 expected seq（不符 → `rejected_stale` 既有）并进入第 (6) 步原子分配连续新区间。
3. **按 `(session_id, semantic_input_ordinal)` 同时查重既有行与本批条目集合（F2/L4-FINAL-02）**——对批次内每个 semantic 条目以其 ordinal 在公开输入空间（部分唯一索引既有）查找既有事件，并对批次自身执行同一查重（批内同 ordinal 条目集合）；查重比对一律按第 (4) 步冻结的完整事件内容比较域执行；`n` 与 expected seq 的「全重复批次/含新插入条目」分类一律按**归并后逻辑条目集合**判定。
4. **同序完整事件内容比较域一致（F1/L4-FINAL-01，比较域冻结）**——比较域 = 五分量 `{event_type, schema_version/canonicalizer_version, (turn_id, step_id, effect_id) 归属三元组, canonical payload}`（canonical payload 按 §1.3 canonical profile 字节比对；归属三元组按持久化值逐分量比对、含 NULL；两版本字段按事件声明值比对）：同 ordinal 且比较域完全一致 → 该条目（或归并条目）**返回既有事件的 `event_key`/`seq`**（不落盘第二条——无论本次 `command_id` 与既有事件生成命令是否相同）；**批内归并（冻结，F2）**——批内多个条目同 ordinal 且比较域完全一致 → 归并为一个逻辑条目：新事件代表 = 最小 `batch_item_ordinal` 的条目（其 raw occurrence identity `(command_id, batch_item_ordinal)` 即该新事件 `event_key` 的派生输入），全部对应输入位置在 receipt 逐项映射中映射同一新 `event_key`/seq，归并不产生第二条事件、不重复计入 `n`。
5. **同序比较域任一分量不同**——含同 canonical payload 而异 `event_type`、异归属、异 schema/canonicalizer 版本的形态——→ 整批固定 `IDEMPOTENCY_CONFLICT`（receipt 落 `rejected_mismatch` 保留该 code、零事件落盘——批内条目间冲突与对既有行冲突同 code，均在**任何插入前**判定——不存在部分插入中间态）。
6. **仅对不存在 ordinal 的 semantic 条目**（批内归并条目按其代表条目——最小 `batch_item_ordinal`——的 raw occurrence identity 派生，F2）：按请求 raw occurrence identity（`(command_id, batch_item_ordinal)`）派生内部 `event_key`；观测类条目按各自既有键（chunk 四元组等）查重、命中者返回已有 seq——全部需新插入事件统一分配新 seq（`next_seq..next_seq+n-1` 连续区间、`n` = 本次新插入事件数）。
7. **双部分 receipt 的逐项 identity 映射**——receipt 第一部分对命中 (4) 的条目一律返回既有事件 identity（既有 `event_key`/`seq`，不返回本次请求侧派生身份；批内归并条目的全部对应输入位置映射同一新 `event_key`/seq）；本次请求 occurrence identity 仅记录于 receipt payload 供审计，不产生第二事件、不改写既有事件 identity。

并发裁定：任意双幂等命中形态的并发由第 (1) 步 session 行锁全序串行化——先提交者按 (3)–(7) 落库，后到者锁内重读后按 (4)/(5) 分类，不存在分别处理两类幂等的多路径。**唯一索引冲突转义（防御性）**：任何异常时序下到达的 `UNIQUE(session_id, semantic_input_ordinal)`（或 `UNIQUE(session_id, event_key)`）索引冲突 MUST 在函数内捕获并转义为 (4)/(5) 对应分类结果（幂等返回或 `IDEMPOTENCY_CONFLICT` receipt），MUST NOT 向调用方泄漏裸约束违反。

portable 前提注记（冻结）：两运行时对相同 semantic 输入序列产生相同 `semantic_input_ordinal` 序——由共享输入序承载（同 fixture 的调用方按输入合同分配相同序列，随 fixture 冻结）；内部事件提交先后不影响公开输入接受与 portable trace（S01/S02，Conformance 断言）。派生函数版本化（随 `canonical_profile_version = @v1` 冻结、仅经版本号提升改变），同输入 MUST 返回同键——确定性由数据库函数层保证（两运行时经同一 SQL 层同一函数写入，不存在第二派生路径）。

---

## 3. 字节级算法

### 3.1 `event_key@v1`（流事件——`assistant/chunk` 唯一流事件类型）[LATER]

跨运行时确定性派生，属**跨语言 golden vector 字节级断言层级（portable 断言对象）**。字节算法完整冻结、无实现自由度（随 `canonical_profile_version = @v1` 冻结；任何变更 MUST 发布新版本号、MUST NOT 就地改写）：

```text
event_key@v1 = SHA-256("v8:event-key@v1\0"
                    || [8B 大端长度]effect_id 原始字节
                    || uint64be(attempt_no)
                    || [8B 大端长度]stream_id 原始字节
                    || canonical_integer_bytes(chunk_index))
```

- 域分离前缀 `"v8:event-key@v1\0"` = ASCII 字符串 `v8:event-key@v1` 后随单个 NUL 字节（`0x00`）——前缀含版本标签、承担域分离，进入 hash 输入。
- 两个变长原始字节段（effect_id、stream_id）一律前置 8 字节大端长度定界（消除与定界样式字节的拼接歧义）。
- `attempt_no` 以 8 字节大端无符号整数编码（uint64be；域内 `attempt_no >= 1` 恒可无损编码）。
- `chunk_index` 以 `canonical_integer_bytes` 编码。
- **输出**：SHA-256 的 32 字节 digest 以小写十六进制 UTF-8 编码（64 字节）作为 `event_key` 值；内容 hash 作为冲突校验值，不参与派生输入；调用方提交的 `event_key` 仅为校验对象——与派生值不一致即 mismatch 拒绝。
- 查重语义：同四元组同内容 MUST 幂等返回已有事件；同四元组异内容 MUST 稳定 `CANONICALIZER_CONFLICT` 拒绝（不落盘第二条）；跨 `stream_id` 顺序保持 §1.2 既有规则（不同流不合并、无法确定即失败封闭）。

### 3.2 `canonical_integer_bytes`（冻结）[P0B-CORE]

整数值的**十进制数字 ASCII 字节**（`0`–`9`、无前导零；值 0 编码为单字节 `0x30`）。number 与 `$int` 两种输入形态在到达派生函数前已由表示分区各归其合法形态；本算法只作用于**整数值**（输入形态差异不进入键）——「同一整数值的两种形态经转换得到字节级相同的派生键」是本编码与 event_key 派生函数层的性质（隔离单元测试断言，Conformance 10 两层拆分）。凡 ordinal/整数进入 portable 投影或摘要元素的编码一律用本编码。

### 3.3 `turn_end_key@v1`（canonical end 槽位键）[P0B-CORE]

每 turn 唯一的 canonical end 槽位键；随 `canonical_profile_version = @v1` 冻结；字节算法完整冻结、无实现自由度、**不接受调用者指定**：

```text
turn_end_key@v1 = SHA-256("v8:turn-end-key@v1\0"
                     || [8 字节大端长度]session_id 原始字节
                     || [8 字节大端长度]turn_id 原始字节)
```

- 域分离前缀为 ASCII 字符串 `v8:turn-end-key@v1` 后随单个 NUL 字节（`0x00`，与 `event_key@v1` 同款域分离样式、含版本标签、进入 hash 输入）。
- 两个变长原始字节段（session_id、turn_id）一律前置 8 字节大端长度定界；字节表示按 `event_key@v1` 第 (iv) 条冻结解释（UUID 一律 RFC 9562 16 字节 binary、非 UUID 文本 UTF-8 原样）。
- 输出为 SHA-256 digest 的小写十六进制 UTF-8 字节（64 字节）。派生输入不含任何 payload 或事件内容（槽位键只绑定 turn 身份）。
- 槽位创建后不可变；后续 completion/cancel/repair MUST 按 `(session_id, turn_id)` 定位并复用该行（不存在第二槽位行；写入值与派生值不一致即 mismatch 拒绝，调用方 MUST NOT 指定槽位键）。

### 3.4 `closer_event_key@v1`（repair closer 事件键）[LATER]

```text
closer_event_key@v1 = SHA-256("v8:closer-event-key@v1\0"
                         || [8 字节大端长度]turn_end_key 字节
                         || [8 字节大端长度]supersedes_event_key 字节
                         || [8 字节大端长度]resolution_identity canonical 字节)
```

- 域分离前缀为 ASCII 字符串 `v8:closer-event-key@v1` 后随单个 NUL 字节（`0x00`）；三个变长字节段一律前置 8 字节大端长度定界：
  - `turn_end_key` 字节 = 槽位行按 `turn_end_key@v1` 派生并冻结的值（64 字节小写 hex UTF-8）的原始字节；
  - `supersedes_event_key` 字节 = 被替代事件 `event_key` 值（同为 64 字节小写 hex UTF-8 形态）的原始字节；
  - `resolution_identity` canonical 字节 = 该结构化对象按 §1.3 canonical profile（规范步骤 0 + 第 (1)–(6) 步）序列化的 canonical JSON 字节。
- 输出为 SHA-256 digest 的小写十六进制 UTF-8 字节（64 字节）。调用者提交的 `event_key` 仅为校验对象（不一致 → mismatch 拒绝），不是派生输入（调用者提交的 resolution 值仅作对象校验——不一致即 mismatch，派生永远按本条算法执行）。

### 3.5 `provisional_unknown_effect_set_digest@v1`（provisional end 的 portable 投影分量）[LATER]

随 `canonical_profile_version = @v1` 冻结、字节算法完整冻结无实现自由度（仅经版本号提升改变；**版本标签是键名一部分、MUST NOT 进入 hash 输入**）：

- **输入** = 该 turn 的 unknown effect 集：求值输入域内 effect 级语义结果呈现 unknown 分类（`unknown_outcome`——§1.2 unknown 行的 effect 级未知结果表示，含 unknown 语义结果事件与 `assistant/partial {outcome:unknown}` 合成表示）的全部 effect 的 `effect_id` 全集（不因 closer 取代而剔除——历史只追加；空集构造上不可达：provisional end 仅在首个 unknown 分类时创建，防御性口径下空集按空字节序列编码）。
- **编码** = 集内 `effect_id` 按其 RFC 9562 16 字节 binary 字节序升序、每个前置 8 字节大端长度定界后顺序拼接。
- **digest** = SHA-256(拼接字节)，输出小写十六进制 UTF-8（64 字节）。
- identity 字段字节表示按 `event_key@v1` 第 (iv) 条通用条款。

### 3.6 identity 字段字节表示（键派生输入冻结，三键通用条款——第 (iv) 条）[P0B-CORE]

适用于 `event_key@v1`、`turn_end_key@v1`、`closer_event_key@v1` 三键的全部变长「原始字节」段，统一冻结：所有参与键派生的 identity 字段（`effect_id`/`session_id`/`step_id`/`turn_id`）为 UUID 时一律取 **RFC 9562 的 16 字节 binary 表示**（无连字符、无大小写歧义——带连字符或任何大小写的文本形态 MUST NOT 直接参与键派生；文本形态 UUID 在命令 envelope 校验层解析并二进制化，同一 UUID 的任何文本形态不得产生不同派生键）；`stream_id` 与其他非 UUID 文本标识一律按 **UTF-8 字节原样**（不经 Unicode 归一、不转义改写）；编码错误（非合法 UTF-8）或 NULL 的 identity 字段在命令 envelope 校验层稳定拒绝、不进入任何键派生。该表示随 `canonical_profile_version = @v1` 冻结，仅经版本号提升改变。（internal_op_audits 的 target_identity/ordinal 分配同款表示。）

### 3.7 非流事件 `event_key`（数据库内部派生 identity）[P0B-CORE]

- (b) 分支：`user/message`、`turn/start`、`agent/inject`、`session/heartbeat` 等公开 append 白名单类型，`assistant/message`、`tool/call`、`tool/result`、`compaction/*`、`compat/unmapped` 等数据库内部命令生成事件，及全部 observational 事件（turn-end 槽位/closer 键有既有专门算法，仍属跨语言断言层级、不属本分支）的 `event_key` 为**数据库内部派生 identity**：MUST 由数据库受控函数在追加事务内派生，绑定 `(session_id, event_type, occurrence_identity, canonical payload hash)`（identity 字段按数据库存储表示参与绑定——同函数同表示，无跨运行时字节形态断言需求）。
- **自引用字段排除（compaction/end，N01）**：`compaction/end`（及任何今后携带清单内字段的 compact 审计事件）派生输入中的 canonical payload hash 显式排除冻结自引用字段清单 `{result_identity, event_key, abort_identity}`（排除清单、两阶段生成顺序与 `compaction_result_digest@v1` 唯一冻结于 §3.3，本层不复述）。
- `internal_op_audits.event_key`：绑定 `(parent_session_id, parent_command_id, internal_op_kind, internal_op_ordinal, target_identity 规范字节)` 五元组派生域，数据库内部派生函数在父命令事务内生成，同输入 MUST 返回同键，同事务受保护写入。[LATER]
- portable 边界（显式声明）：非流事件 `event_key` 不属于跨运行时 portable 比较对象——portable 比较使用 logical 结构（turn/step/effect 归属 + canonical payload，§1.2 既有）；对非流事件键的合同断言层级是**数据库内部一致性**（同输入同键、`UNIQUE(session_id, event_key)` 追加幂等、调用方提交键与函数派生值不一致即 mismatch 拒绝），不是跨语言 golden vector 字节级断言。

### 3.8 拒绝键算法（§1.3 定义，本段引用）[LATER]

- `transport_rejection_key@v1` = SHA-256(接入层收到的原始报文/帧字节)——计算不需要 payload 边界、不引用 canonical hash 或 rejection fingerprint。
- `rejection_fingerprint@v1`：输入 = payload 原始字节。
- `canonical_request_hash`（即 `computed_request_hash`）：SQL 按 canonical profile 对完整 payload 的已转义表示重算（§1.3 规范步骤 0 → profile 管线），覆盖 command kind、目标 identity、expected seq/fence 和完整 payload。[P0B-CORE]

### 3.9 `resolution_digest`（turn_end_closers 列）[LATER]

= SHA-256(`resolution_identity_canonical`) 的**原生 32 字节 binary 摘要**（非 hex），随行同事务计算写入、不可变。

---

## 4. 状态机

### 4.1 `turn_end_slots.slot_status`（闭合二值）[P0B-CORE]

- `provisional`：当前链头为 provisional unknown end（`turn/end {outcome:unknown}`）。
- `known`：当前链头为已知终结 end / closer。
- 转移：仅经受保护槽位更新函数随 closer 追加/已知终结 end 更新（`provisional → known`；known 链头上的后续 repair closer 保持 `known`）；`version` 每次受保护更新 +1（CAS 用）。

### 4.2 effect（本段可见转移；权威状态机在 §3.2.2）[P0B-CORE]

- **发布即 ready（冻结）**：seal 事务内创建首个 attempt 后同事务将已密封 effect 直接写为 `ready`；`planned` 仅为 seal 事务内的临时构建态（成员创建时的构建值、事务内即被覆盖），**不存在持久化的 planned effect**（镜像 §3.1 `create_step` 同事务化先例）。派发门 `ready -> dispatch_started` 对该 effect 提交后立即可见。
- `cancelled_before_dispatch`：pre-dispatch 取消收束（取消事务将已发布 `ready` effect 收束，当前 attempt 行同事务同步转 `cancelled_before_dispatch`——双表原子同步，§2.2 第 3 条 (a)）。[LATER]
- `failed_terminal`：DECISION_PLAN_INVALID 收束路径等（code `INFRA_PROTOCOL_VIOLATION`）。[LATER]

### 4.3 step（本段可见转移；权威在 §3.2.1）[P0B-CORE：初始 seal 段]

- 创建即 `planned, stage=decision`（初始 decision seal 的 CAS 前置状态；step 创建与 seal 同事务发布——不存在「已创建、未 seal、无 LLM slot」的持久化中间态，也不存在 planned-无-effect step）。
- 成功 decision 终局后聚合至 `ready, stage=decision`（冻结 result identity 与 plan_hash，不提前创建 tools）→ tools seal 置 `stage=tools` → 成功 terminalize 置 `stage=closed`（仅 `decision_only=true` 的成功 decision 或 `final_tools=true` 的全成功 tools batch）。[tools 段 LATER]
- 聚合为 `waiting_effect`（seal 后聚合态，不得暴露未密封或部分密封批次）。
- `failed_terminal`（INFRA 收束路径下未完成 step）。[LATER]

### 4.4 session（权威在 §3.1.1，本段引用）[LATER]

本段提及的状态/转移：`quiescing`（heartbeat epoch 例外、reconcile 结算入口）；`failed`（INFRA 收束）；`cancelled`（`failure_code=CANCELLED_BY_REQUEST`）；`completed`（`finish_session`）；cancel 与 `finish_session` 的竞争按数据库提交序唯一裁定（两命令均先锁 session 行：cancel 先提交 → `cancelled`，其后 `finish_session` 返回原终态；finish 先提交 → `completed`，其后 cancel 返回原终态且不改变 epoch）。

### 4.5 命令 receipt outcome（闭合四类）[P0B-CORE]

`outcome ∈ {accepted, rejected_stale, rejected_mismatch, repair_required}`——首占即定（binding `first_outcome`），同 `command_id` 重试按 (1) 幂等返回首次结局；`FORCE_JOB_TAKEOVER` 专用四 outcome（成功/目标不存在或已终态 `rejected_mismatch`/fence 或 lease 已被取代 `rejected_stale`/`FORCE_NOT_REQUIRED`）。

### 4.6 compaction 状态机（§3.3 引用）[LATER]

`compact_lock`（申请）/`compact_finalize`/`compact_abort`（终态转移）对应 `locked` 进入与终态转移；abort 释放 lock 回 `idle`；owner+fence CAS（`STALE_COMPACT_FENCE`）；session 终态事务对仍处 `locked` 的 compact lock 的受控 abort 是终态事务的内部子操作 `compact_terminal_abort`（不另立 command_id/receipt、不走 `compact_abort` 命令入口）。

---

## 5. P0B 相关性标注（汇总）

判定标准：P0B 最小闭环 = user event → create step（与初始 decision seal 同事务）→ create fake LLM effect（seal 事务内同事务创建唯一首个 attempt 行 attempt_no=1）→ dispatch（只绑定既有 attempt、不补建）→ complete effect（成功证据分类 + assistant message 事件）→ step/session 聚合 → yield/finish_session；外加 kill-at-every-boundary chaos、命令幂等（command_id receipt/binding）、canonical profile、事件 seq 无洞、turn finalization reducer、双 fence 基本语义（stale completion 拒绝）、Conformance 1 核心断言（首个 attempt / 发布即 ready / 不存在持久化 planned / 不存在 planned-无-effect step / append 幂等与 seq 无洞）。

### [P0B-CORE]

- 表：`command_receipts`、`command_bindings`（命令幂等）；`turn_end_slots`（turn finalization reducer 落地，含 `turn_end_key@v1`、受保护槽位更新函数、`UNIQUE(session_id, turn_id)`）；`session_events` 增列 `turn_id`（H02）、`semantic_input_ordinal`/`internal_semantic_ordinal` 双列及两部分唯一索引与列级条件约束。
- 命令：`append_events`（user/message 入口 + 批次合同双部分 receipt + 白名单 `public_append_types@v1` + `EVENT_TYPE_RESTRICTED`）；`prepare_step`（初始 decision seal 路径：create_step 同事务、LLM slot、首个 attempt_no=1、双 fence 同值冻结、发布即 ready、CAS 拒绝零副作用、聚合 `waiting_effect`）；`dispatch_effect`（只绑定既有 attempt——合同在 §3.2.2）；`complete_effect`（非流式 `known_success` 终局路径：SQL 生成 canonical 语义事件/assistant message、单次终局结算约束、终局路径款 (2)）；`finish_session`（以 `decision_only=true` 为唯一 turn-complete 信号——合同在 §3.1.1）。
- 合同：通用 envelope 五字段与 computed_request_hash 重算（canonical profile）；八位主锁序；receipt/binding 判定序 (1)–(4)（canonical 路径）；expected seq 特例 L4-U-R01（全重复批次不校验 expected seq、不推进 next_seq）；outcome 闭合集四类；receipt/binding 同事务原子、回滚全不存在、保留至显式销毁。
- seal 段：初始 decision seal 的 CAS/创建/发布序（第 1/2/4–8 步）；`decision_result_identity=(effect_id, attempt_no, result_hash, event_key)`；`decision_only`/`final_tools` 双向互斥穷尽 schema（P0B 走「空 tools plan ⟺ decision_only=true ∧ final_tools=false」分支）。
- 事件键：第 (1) 层 `UNIQUE(session_id, event_key)` 原始追加幂等；非流事件数据库内部派生（四元组绑定）；occurrence identity 公开 append 路径 `(command_id, batch_item_ordinal)`；内部生成事件中「completion 生成的语义结果事件（`assistant/message`、`tool/result`）与 provisional `turn/end {outcome:unknown}` = `(effect_id, attempt_no)`」；portable 投影 (a) 公开语义 `(semantic_input_ordinal)` 与 (d) completion 语义结果 `(effect_id)`。
- 七步：公开 semantic append 唯一实现路径（session 行锁 → 全批校验 → ordinal 查重 → 比较域一致幂等返回 → 分量不同 IDEMPOTENCY_CONFLICT → 新事件连续 seq 区间 `next_seq..next_seq+n-1` 无洞 → 双部分 receipt 逐项映射）；唯一索引冲突转义。
- 算法：`turn_end_key@v1`、`canonical_integer_bytes`、identity 字段字节表示通用条款（RFC 9562 16 字节 binary / UTF-8 原样）、`canonical_request_hash`（SQL 重算）。

### [LATER]（完整抽取于上文，仅标记）

- 表：`internal_op_audits`（五类内部子操作审计）、`turn_end_closers`（closer 历史）、`compactions` 回指列、`effect_audit` 10 列去重键、独立 ingress/malformed receipt 存储、独立授权拒绝审计行。
- 命令：`create_effect`（公开模式 batch-slot 校验）、`retry_effect`、`request_cancel`（粘性停止/latch/无活跃工作分支——合同在 §3.1.1）、`transition_wait`、`transition_sleep`、`fail_session`（三类来源受控入口）、`repair`、`reconcile`（X01 共用序、`OBSERVATION_WRONG_ENTRY`、`SWITCH_DEFERRED`）、`compact_lock`/`compact_finalize`/`compact_abort`（§3.3 七步定位序、终态 replay 五步判定序、`STALE_COMPACT_FENCE`/`COMPACT_BUSY_EFFECTS`）、`compat_unmapped_audit`、`FORCE_JOB_TAKEOVER`（专用 envelope、四 outcome、`FORCE_NOT_REQUIRED`）。
- 合同段：统一内部子操作审计合同（五类闭合集、五类全序、ordinal 分配规则、重放序）；三键类型化的 (a)(b)(c) transport/payload 拒绝路径（`transport_rejection_key@v1`/`rejection_fingerprint@v1`）；授权前置拒绝（receipt 命名空间之外）；L4-U03 heartbeat quiescing epoch 例外；seal 授权阶段与 generation 检查（`GENERATION_REVOKED`，依赖 §2.1 grant 模型与 §4 generation 域）；tools seal 四步（`create_effect_in_seal` 两模式、slot 级 occurrence、`stage=tools`/`stage=closed`）；pending observation 排除段 AA01；`complete_effect` 流式观测款 (1)(3)（`stream_progress`、五款状态门、Y01 三款）；P01 heartbeat 拆分（`session/heartbeat`/`attempt/heartbeat`）；Q03 `SESSION_TERMINAL`；chunk 六项归属校验（`CHUNK_ATTRIBUTION_INVALID`）；观测事件身份分流 O01（(α) 可重复/ordinal 与 (β) 不可重复/基数约束清单 `attempt_created`/`attempt_dispatched`/`attempt_superseded`/`attempt_cancelled_before_dispatch`）；portable 投影 (b)(c)(d′)(e)；repair closer 六条受控校验（`REPAIR_TARGET_INVALID`）；DECISION_PLAN_INVALID 的 INFRA 收束（`failed_terminal`/`INFRA_PROTOCOL_VIOLATION`、父层 code 优先级限定）。
- 算法：`event_key@v1`（流事件四元组派生）、`closer_event_key@v1`、`provisional_unknown_effect_set_digest@v1`、`transport_rejection_key@v1`、`rejection_fingerprint@v1`、`internal_op_audits.event_key` 五元组派生、`resolution_digest`、compaction/end 自引用排除清单 `{result_identity, event_key, abort_identity}`、`compaction_result_digest@v1`/`compact_result_identity@v1`（§3.3 权威）。
