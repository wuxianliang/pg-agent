# s2-planes-grants — §2.1 slice/grant + §2.2 workspace_handle 与 WORKSPACE_LOST

来源:`/Users/wxl/Projects/pg-agent/docs/designs/v8-dev.md` 第 112–198 行(已冻结实现合同)。本 digest 为逐条抽取,冻结条款关键字段名 / code 字符串 / 公式均逐字引用,不得意译。P0B 判定标准见文末第 5 节。

## 0. 概念分层(四对象对照,逐字引用规格表)

| 对象 | 作用 | 不是什么 |
|---|---|---|
| 租户 `workspace_id` | RLS 行级隔离 | 不是 run 的 worktree |
| `slice` | 命名资源边界(corpus、路径前缀、tool 集合、secret 名) | 不是 grant 本身 |
| `grant` | 把 slice + capability 签给某个 session/step/plugin | 不是 catalog 行上的声明字段 |
| `workspace_handle` | 本 run 的执行态(worktree、REPL、未提交编辑) | 不是租户 id |

租户隔离与 agent 内授权不是同一层——RLS 租户隔离 MUST NOT 替代 slice-membership 的 agent 内资源边界检查(合取项 3)。

---

## 1. 数据库表(完整清单)

### 1.1 `slices` [P0B-CORE](表与最小 schema;见第 5 节判定说明)

规格给出的最小字段(逐字,text 块):

```text
slice_id, workspace_id, name, kind, spec, created_at, revoked_at
kind ∈ {corpus, fs_prefix, tool_set, secret, workspace_exec}
UNIQUE (workspace_id, name)
```

- 唯一约束(逐字):`UNIQUE (workspace_id, name)`。
- `kind` 闭合集(逐字):`{corpus, fs_prefix, tool_set, secret, workspace_exec}`。
- 撤销语义列:`revoked_at`(NULL = 未撤销;非 NULL 即撤销,且 MUST 在同一事务级联失效其下全部 grant,见合取项 1)。
- 不可变性保护:slice 的 `spec`(含 `workspace_id`/`slice_id` 绑定字段)创建后 MUST NOT 就地修改;任何变更(收紧或放宽)MUST 走撤销 + 重建——撤销旧 slice 在同一事务级联失效其下全部 grant,需要的 capability 在新 slice 上新签 grant(新 `grant_id`);MUST NOT UPDATE 既有行的 `spec`。(无触发器,靠「不提供 UPDATE 路径」的受保护函数约定;规格未给 DDL 级触发器。)
- 可选增列:若授权线性化采用机制 (b) `revocation_version` CAS,则 `slices` MUST 增列单调递增 `revocation_version`(撤销事务 MUST 递增所撤销行的版本)。[LATER](并发撤销竞争机制,P0B 单确定性闭环不涉及)
- 类型与 NOT NULL:规格仅部分给出(仅列名清单与闭合集,无逐列类型/NOT NULL DDL)。

### 1.2 `grants` [P0B-CORE](表与最小 schema;见第 5 节判定说明)

规格给出的最小字段(逐字,text 块):

```text
grant_id, workspace_id, slice_id, subject_kind, subject_id,
capability, constraints, issued_at, not_before, expires_at,
revoked_at, delegable
subject_kind ∈ {session, step, plugin_identity, driver}
capability ∈ {recall, fold, env_read, env_write, tool_resolve,
              authorize_effect, effect_submit, event_append,
              stream_ingest, process, network, credential, compact}
```

- `subject_kind` 闭合集(逐字):`{session, step, plugin_identity, driver}`。
- `capability` 闭合集(逐字,13 个):`{recall, fold, env_read, env_write, tool_resolve, authorize_effect, effect_submit, event_append, stream_ingest, process, network, credential, compact}`。
- 有效期半开区间:`[not_before, expires_at)`(当前时间必须落在此区间,见有效判定)。
- 外键/等效约束(逐字):grant、slice、调用 session 与目标资源的 `workspace_id` 租户一致性「MUST 由复合外键或等效数据库约束强制,MUST NOT 只靠约定(§0 不变量 12)」。
- 不可变性保护:grant 的 `constraints`(含 `workspace_id`/`slice_id` 绑定字段)创建后 MUST NOT 就地修改;仅变更 grant 约束同样 MUST 撤销旧 grant、新签 grant(新 `grant_id`),MUST NOT UPDATE 既有行的 `spec`/`constraints`。
- 可选增列:同 1.1,机制 (b) 时 MUST 增列单调递增 `revocation_version`。[LATER]
- 类型与 NOT NULL:规格仅部分给出。
- 注意:规格未给 `grants` 的 UNIQUE 约束(与 `slices` 的 `UNIQUE (workspace_id, name)` 不同)。

### 1.3 `workspace_handles` [LATER]

规格给出的字段(逐字,text 块):

```text
workspace_handles(
  handle_id, session_id, run_id, workspace_id,
  owner_fence, status, checkpoint_seq, checkpoint_digest,
  op_seq, generation, created_at, lost_reason
)
UNIQUE (session_id, run_id)
```

- 唯一约束(逐字):`UNIQUE (session_id, run_id)`——同时保证「唯一初始化」与「handle_id MUST NOT 复用」。
- `status` 闭合集(逐字):`{uninitialized, active, handoff_ready, lost, discarded}`。
- 类型与 NOT NULL:规格仅部分给出(仅列名清单 + 唯一约束 + status 闭合集)。

### 1.4 受控 mutation 记录(表名规格未给)[LATER]

§2.2 第 1 条 (i) 要求「为该 op 持久化登记态 `status=in_flight`(受控 mutation 记录)」,(iii) 「把该 op 写回 `status=completed`」。即存在一张受控 mutation 记录表:至少含 `handle_id` 关联、`op_seq`、`status`(闭合态至少 `{in_flight, completed}`,外加「已随接管失效」的收束态)。规格仅部分给出(无表名、无 DDL)。

---

## 2. 命令与流程

### 2.1 有效 grant 判定(所有授权检查共用的前置谓词)[P0B-CORE]

逐字:「有效 grant 当且仅当以下条件全部合取成立:`revoked_at IS NULL`、当前时间在 `[not_before, expires_at)`、`subject` 匹配调用者、`capability` 覆盖本次调用、`constraints`(路径 / 命令 / 目标 / TTL / max_bytes / max_rows)全部满足」,以及三个强制合取项:

1. 「所属 slice 的 `revoked_at IS NULL`;slice 撤销 MUST 在同一事务级联失效其下全部 grant(或等效检查)——仅检查 grant 自身的 `revoked_at` 不足以判定有效。」
2. 「grant、slice、调用 session 与目标资源的 `workspace_id` 租户一致;该一致性 MUST 由复合外键或等效数据库约束强制,MUST NOT 只靠约定(§0 不变量 12)。」
3. 「实际访问对象属于 `slice.spec` 指定的资源集合;slice-membership 校验 MUST 对所有 capability 统一执行,RLS 租户隔离 MUST NOT 替代该 agent 内资源边界检查。」

`constraints` 可约束维度(逐字枚举):路径 / 命令 / 目标 / TTL / max_bytes / max_rows。

### 2.2 事务内 grant 检查点清单(失败返回 `GRANT_DENIED`)[P0B-CORE]

逐字:「下列动作必须在**同一事务**中检查有效 grant,失败返回 `GRANT_DENIED`,不得进入 `dispatch_started`,不得向模型展示未授权工具:」

- `recall` / `fold` / `env_read` / `env_write`
- `tool_resolve`(决定模型可见集合)
- `authorize_effect`(按具体参数再授权)
- `effect_submit` 以及 `ready -> dispatch_started`
- 两条 seal 路径事务内的 effect 成员创建(§3.1.2 `create_effect_in_seal`:初始 decision seal 的唯一 LLM slot 与 tools seal 的全部 tool effect——seal 授权阶段;任一成员失败 → 整个 seal 零副作用稳定拒绝 `GRANT_DENIED`,不创建任何成员)

闭合拒绝 code(逐字):`GRANT_DENIED`。

### 2.3 两道实时门(两阶段授权快照边界)[P0B-CORE](两道门各自成立、互不豁免的基本语义)

逐字要点:

- 模型可见工具集由 `tool_resolve` 绑定 assemble manifest 的固定快照产生(§3.3:fold、recall、catalog、grant 和 policy 绑定同一 manifest hash)——「快照冻结的只是『模型本轮可见什么』」。[LATER:manifest hash 绑定细节属 §3.3]
- 第一道实时门(seal 阶段实时授权):§3.1.2 两条 seal 路径(初始 decision seal 与 tools seal)「在创建任何 batch/effect/attempt 之前,MUST 对本次将创建的全部 effect 按具体参数执行完整实时授权(本节有效 grant 全部合取条件 + slice-membership + 参数级 `authorize_effect`,相关 grant/slice 行锁按 §3.1.2 固定锁序取得);任一成员授权失败 → 整个 seal 零副作用稳定拒绝 `GRANT_DENIED`」。
- 第二道实时门(dispatch 门):实际派发(`ready -> dispatch_started`)MUST 实时重验当前 grant/slice 撤销状态与全部合取条件(§0 不变量 17);「manifest 快照不豁免 dispatch 时重验——assemble 之后、dispatch 之前发生的撤销 MUST 使该 dispatch 返回 `GRANT_DENIED`,MUST NOT 因工具已在 manifest 快照中可见而放行」。
- 逐字:「dispatch 门(`ready -> dispatch_started`)的授权检查是**第二道实时门**,MUST NOT 替代 seal 阶段授权;两道门各自独立成立,任一门通过不豁免另一门。」

### 2.4 授权线性化点(撤销 vs 授权检查的并发裁定)[LATER]

逐字要点:

- 「grant/slice 撤销与授权检查的并发竞争由数据库事务提交序唯一裁定(数据库时钟是唯一判定口径,不依赖应用时钟)。」
- 撤销事务与每个授权检查事务(seam 调用、`tool_resolve`、`authorize_effect`、`ready -> dispatch_started`、§3.1.2 两条 seal 路径的 seal 授权阶段)MUST 在同一事务锁定同一批 grant/slice 行,机制二选一:
  - (a) `SELECT ... FOR UPDATE` 固定锁序——同一事务内多行按 `(workspace_id, slice_id, grant_id)` 升序加锁,并遵守 §3.1.2 固定锁序(grant/slice 行锁位于 session 行锁之后、generation/step/effect/attempt 行锁之前);
  - (b) 校验单调递增的 `revocation_version` CAS——采用该方案时 `slices`/`grants` MUST 增列单调递增 `revocation_version`,撤销事务 MUST 递增所撤销行的版本,授权检查事务提交前 MUST CAS 校验读到的版本未被推进,被推进即重读重判或返回 `GRANT_DENIED`。
- 裁定规则闭合(逐字):「撤销先提交,其后开始的授权检查 MUST 见 `revoked` 并返回 `GRANT_DENIED`;授权/dispatch 先提交,则该已提交动作有效,其后提交的撤销 MUST NOT 追溯取消已 `dispatch_started` 的 attempt——已派发 attempt 只经 §3.2.2 fence/lease 规则与 completion/repair 流程收束,撤销仅使该 grant 下后续授权检查与下一次 dispatch(含 retry attempt 的派发)失败 `GRANT_DENIED`。」

### 2.5 slice/grant 内容不可变(撤销 + 重建)[LATER](建表时不提供 UPDATE 路径即天然满足)

逐字:「slice 的 `spec` 与 grant 的 `constraints`(含 `workspace_id`/`slice_id` 绑定字段)创建后 MUST NOT 就地修改,消灭『读到的 spec 与校验时不同』的中间态。任何变更(收紧或放宽)MUST 走撤销 + 重建:撤销旧 slice 在同一事务级联失效其下全部 grant(合取项 1),需要的 capability 在新 slice 上新签 grant(新 `grant_id`);仅变更 grant 约束同样 MUST 撤销旧 grant、新签 grant,MUST NOT UPDATE 既有行的 `spec`/`constraints`。」

### 2.6 `stream_ingest` capability(双 grant 合取)[LATER]

逐字要点:

- `stream_ingest`:「公开 `append_events` 追加白名单观测类 `assistant/chunk` 的调用方能力」。
- 与 `event_append` 构成**双 grant 合取**(两 capability 各自独立签发、互不替代、互不隐含)。
- chunk append 的调用方授权**三合取**:有效 `event_append` grant AND 有效 `stream_ingest` grant AND 调用方身份与该 effect 绑定 provider/adapter/driver/epoch 全匹配;缺任一(含持有 `stream_ingest` 但缺 `event_append`)稳定拒绝 `CHUNK_ATTRIBUTION_INVALID`。
- 冻结于 §3.1.2 六项归属校验第 (6) 项:调用方 subject 即该 effect 绑定的受权 provider/adapter(经 grant/driver 链解析);两 grant 均受本节有效 grant 全部合取条件(含 slice-membership)约束,不另建第二套授权模型。
- 闭合拒绝 code(逐字):`CHUNK_ATTRIBUTION_INVALID`。

### 2.7 `compact` capability [LATER]

逐字:「三个 compact 受控命令(`compact_lock`/`compact_finalize`/`compact_abort`,§3.1.2 统一命令合同、§3.3 compact 状态机)的调用方能力——调用方 subject 为该 session 绑定的受权 driver/coordinator 身份(经 grant/driver 链解析),受本节有效 grant 全部合取条件(含 slice-membership)约束,不另建第二套授权模型。」

命令名(逐字):`compact_lock`、`compact_finalize`、`compact_abort`。

### 2.8 插件目录与调度门 [LATER]

逐字:「`plugin_specs.required_services` 只是目录声明;缺对应 grant 时 activator 不得把该实现标为可调度。T2/T3 compat 插件是 operator-trusted host capability,必须声明文件 / 网络 / 子进程 profile;未提供强制 sandbox 时不得声称支持不可信插件。」

### 2.9 受控 workspace mutation 三段协议(§2.2 第 1 条)[LATER]

前提(逐字):「持有 session lease 的 worker 才可 mutate。workspace mutation 是带完成态的受控操作,MUST 按固定三段执行:」

1. **登记**——同一 DB 事务内 CAS 登记(逐字公式):
   `UPDATE ... SET op_seq = op_seq+1 WHERE handle_id=? AND owner_fence=? AND op_seq=expected`
   并为该 op 持久化登记态 `status=in_flight`(受控 mutation 记录);CAS 失败则拒绝,MUST NOT 在该事务内执行外部 IO。
2. **事务外执行**——实际文件/REPL 操作在数据库事务外执行。
3. **fenced publish**——在同一 DB 事务把该 op 写回 `status=completed` 并推进 checkpoint,checkpoint digest MUST 覆盖最新已完成 `op_seq`/`generation`。

发布点 fencing(逐字):「lease/fence 被接管后,旧 worker 的 publish MUST 被 `owner_fence` CAS 拒绝,stale publish MUST NOT 写进 checkpoint;其事务外写入只能落到当前 generation 私有对象/不可变区域,MUST NOT 污染新 worker 视图。」

补充:「只读不占 `op_seq`」;受控 mutation 三段在 `active` 状态内推进 `op_seq` 与 checkpoint,不构成 `status` 迁移。

### 2.10 yield 前 checkpoint 协议(§2.2 第 2 条)[LATER]

逐字:「`yield` / 释放 session lease 之前,必须在同一控制事务中确认无 `in_flight` mutation(全部受控操作已 `completed` 或已随接管失效)且 checkpoint 等于最新已完成执行态(digest 覆盖 worktree manifest、REPL 变量引用、最新已完成 `op_seq`/`generation`),方可写入 `handoff_ready` 的 checkpoint;无法证明时 MUST 追加 `workspace/lost` 并置 `lost`,按第 3 条走 `WORKSPACE_LOST`,MUST NOT 恢复『旧但 digest 自身正确』的 checkpoint——digest 自身正确不等于覆盖最新已提交执行态。」

事件类型(逐字):`workspace/lost`。

### 2.11 `materialize(checkpoint_digest)`(§2.2 第 3 条前半)[LATER]

下一 worker claim 后只能 `materialize(checkpoint_digest)`,且 checkpoint MUST 覆盖最新已完成执行态(最新已完成 `op_seq`/`generation`;存在未收束 `in_flight` mutation 即不满足)。拒绝条件(逐字四项):「文件缺失、digest 不匹配、checkpoint 未覆盖最新已完成执行态、handle 已 `lost`」→ 返回 `WORKSPACE_LOST`,「**禁止**打开空 workspace 继续跑,不得假装 workspace 还在,MUST NOT 恢复『旧但 digest 自身正确』的 checkpoint」。

### 2.12 WORKSPACE_LOST fail-closed 与确定性 failure-drain(§2.2 第 3 条后半)[LATER]

触发(逐字):「一旦记录 `workspace/lost` 或 `WORKSPACE_LOST`(无论经第 2 条 yield 前路径还是本条 materialize 检出),session MUST fail closed:同一控制事务内经 §3.1.1 fail 路径立即进入 `failed` 且 `failure_code=WORKSPACE_LOST`,不存在『由政策决定』的分支。」

该事务同时执行确定性 failure-drain,闭合 step/effect 收束链:

(a) **effect drain**:
- 全部 `ready` 未 dispatch effect 同事务转 `cancelled_before_dispatch`,code `ABORTED_BEFORE_DISPATCH`,由数据库内部命令产生,worker 不可伪造。
- 判据说明(逐字):「drain/guard 作用于已发布 effect——`planned` 为 seal 事务内临时构建态、不持久化(§3.2.2 状态闭合),已提交控制态不存在 planned effect,本项判据即 `ready`」。
- **pre-dispatch 取消双表原子同步(冻结)**:该取消是数据库内部取消路径、非 worker completion——effect 行与其当前 attempt(最大 `attempt_no` 行)MUST 在同一事务一并转 `cancelled_before_dispatch`,parent 派生执行快照同事务同步(§3.2.2 双表权威性冻结——两表一致、无单边中间态),不产生 completion 语义事件或 completion receipt;迟到的 worker completion 因 attempt 已终态(terminalization 后唯一允许操作为 audit/receipt 重放,§3.2.2)被既有 envelope/mismatch 规则拒绝、仅写 receipt 与 `effect_audit`;本同步规则对三条 pre-dispatch 取消路径(`request_cancel`、本条 failure-drain、§4 第 3 条 generation drain)同款适用(§3.2.2 状态图注)。
- 未密封 tools plan 作废——已接受的 decision result 保留为 audit/历史,MUST NOT 创建 tools effect。

(b) **step drain 三分支**(逐字):「step 按 drain 三分支收束,不得因 pending 被提前终态化(session 已立即终态,step 的等待状态不改变该事实)」:
- (i) 已存在未决 unknown 的 step → 维持 `blocked_unknown_effect`;
- (ii) 否则存在 pending(in-flight `dispatch_started`)effect 的 step → 停留在聚合规则 2 对应的非终态等待状态(非 sticky cancel 下 `waiting_effect`、sticky cancel 下 `cancel_requested`),标记 drain pending;
- (iii) 两者皆无的未完成(未终态)step → `failed_terminal`、outcome_code `WORKSPACE_LOST`(闭合 code,进 §3.2.1 派生表与失败 code 集)。
- 后续 completion/repair/reconcile 到达时 MUST 在同一事务重复执行同一 drain 判定:新产生的 unknown → step `blocked_unknown_effect`;in-flight effect 全部收束(含经 repair)→ 其未 dispatch effect 按 (a)、step 落 `failed_terminal`/`WORKSPACE_LOST`;MUST NOT 重新开放 seal/retry/tools 或成功终态化 step。WORKSPACE_LOST 后 step 级成功终态化 MUST NOT 发生(fail-closed 前已终态的成功 step 保留原终态,仅可 audit)。

(c) **session 终态**:session 保持 `failed`/`WORKSPACE_LOST`;§3.1.1 terminal 子协议矩阵 (b) 行允许的 failure-drain 收束覆盖上述 drain(经既有 complete/repair/reconcile 路径执行);本终态化事务若存在非终态 drain step,MUST 同事务写入 `sessions.drain_step_id` 指向该唯一非终态 step(§3.1 drain_step_id 合同——`active_step_id` 按既有规则保持清空、MUST NOT 在 terminal session 重填;后续 drain 操作按 `drain_step_id` 定位与锁定,drain 完成同事务清空)。若当时存在 in-flight 未决 effect,其后续 completion/repair 仅用于收束 effect 与审计,MUST NOT 使 session 离开 `failed`、MUST NOT 恢复执行或重建 workspace 继续;重建/继续的唯一途径是 fork 新 session、新建 handle。

### 2.13 fork 继承规则(§2.2 第 4 条)[LATER]

逐字:「fork 默认不继承 live handle。子 session 只能继承 `delegable=true` 且 kind 为不可变 slice 的 grant 副本(新 `grant_id`);live worktree / REPL 必须新建 handle。」

### 2.14 capability API 边界(§2.2 第 5 条)[LATER]

逐字:「raw path、raw DB connection、跨 worker 活对象不得离开 capability API。凭证不进 `session_events`、jobs payload 或常规日志。」

---

## 3. 字节级算法

本节(§2.1/§2.2)不含 `xxx@v1` 形式的具名版本化字节级算法。与本节相关的具名公式/机制:

1. **受控 mutation CAS 公式**(§2.2 第 1 条 (i),逐字):
   `UPDATE ... SET op_seq = op_seq+1 WHERE handle_id=? AND owner_fence=? AND op_seq=expected`
2. **`revocation_version` CAS 协议**(机制 (b),逐字语义):撤销事务递增所撤销行版本;授权检查事务提交前 CAS 校验读到的版本未被推进;被推进即重读重判或返回 `GRANT_DENIED`。[LATER]
3. **checkpoint digest 覆盖要求**(非字节公式,覆盖物清单逐字):worktree manifest、REPL 变量引用、最新已完成 `op_seq`/`generation`。digest 的具体字节编码由 §3.3(checkpoint_digest 计算所在)定义,本节只约束覆盖范围与「MUST NOT 恢复旧但 digest 自身正确的 checkpoint」。[LATER]

---

## 4. 状态机

### 4.1 `workspace_handles.status` 状态机 [LATER]

闭合状态集(逐字):`{uninitialized, active, handoff_ready, lost, discarded}`。

权威完整迁移表(逐字;「第 1–5 条正文规定各边的执行协议,与表冲突时以表为准;未列出的迁移 MUST NOT 执行,`lost` 与 `discarded` 为终态、无出边」):

| 来源 | 目标 | Guard / 同事务原子更新(逐字) |
|---|---|---|
| `uninitialized` | `active` | 首次初始化:同一事务 CAS 写入(`UNIQUE(session_id, run_id)` 保证唯一初始化)`owner_fence`(初始持有者)、初始 `generation`、`op_seq=0`、`status=active`;`checkpoint_seq`/`checkpoint_digest` 为空 |
| `active` | `handoff_ready` | 受控 checkpoint 完成(第 2 条):guard 为无未收束 `in_flight` mutation(全部受控操作已 `completed` 或已随接管失效)且 checkpoint 覆盖最新已完成执行态;同事务写 `status=handoff_ready` 并推进 `checkpoint_seq`/`checkpoint_digest`(覆盖 worktree manifest、REPL 变量引用、最新已完成 `op_seq`/`generation`);`owner_fence`/`generation`/`op_seq` 不变 |
| `handoff_ready` | `active` | 下一 worker `materialize(checkpoint_digest)` 成功且 checkpoint 覆盖最新已完成执行态(含无未收束 `in_flight` mutation,第 3 条):同事务 CAS 更新 `owner_fence` 为新 worker、`generation+1`、`status=active`;`op_seq` 延续不归零,checkpoint 字段保留 |
| `active` | `lost` | 检测到丢失或一致性不可证明:含第 2 条 yield 前无法证明无 `in_flight` mutation、fenced publish 被 `owner_fence` CAS 拒绝后无法收束该受控操作;同事务写 `status=lost` 与 `lost_reason`,并按第 3 条在同一控制事务执行 WORKSPACE_LOST fail-closed |
| `handoff_ready` | `lost` | materialize 失败或超时,或 checkpoint 缺失、digest 不匹配、未覆盖最新已完成执行态(第 3 条任一拒绝条件);同事务写 `status=lost` 与 `lost_reason`,并按第 3 条在同一控制事务执行 WORKSPACE_LOST fail-closed |
| `active`、`handoff_ready` | `discarded` | run `complete` / `fail` 后:同事务写 `status=discarded`;workspace 对象按保留策略清理,此后不接受任何迁移 |

各状态语义:
- `uninitialized`:尚未初始化,唯一入口态。
- `active`:当前 worker 持有(`owner_fence`);受控 mutation 三段在此态推进 `op_seq`/checkpoint,不构成迁移。
- `handoff_ready`:checkpoint 已固化、可交接;`owner_fence`/`generation`/`op_seq` 冻结不变。
- `lost`:终态。保留 `lost_reason` 诊断;handle_id MUST NOT 复用(`UNIQUE(session_id, run_id)` 既有);重建只能按第 3 条 fork 新 session、新建 handle。
- `discarded`:终态。run `complete`/`fail` 后清理;此后不接受任何迁移。

### 4.2 受控 mutation 记录状态机 [LATER]

闭合态(由第 1/2 条文本归纳):`in_flight` → `completed`(fenced publish 成功);`in_flight` → 已随接管失效(被新 worker 接管后收束,无独立 code 名)。语义:`in_flight` 存在时不可写 `handoff_ready`(guard),materialize 视为 checkpoint 未覆盖最新已完成执行态。

### 4.3 slice / grant 撤销状态(隐含)[P0B-CORE](判定谓词本身)

- slice:`revoked_at IS NULL` ⇔ 未撤销;撤销时同事务级联失效其下全部 grant。
- grant:`revoked_at IS NULL` + 时间落 `[not_before, expires_at)` + subject/capability/constraints 匹配 ⇔ 有效(完整合取见 §2.1)。
- 无状态机转移可言:内容不可变,变更 = 撤销(旧行终态)+ 新建(新 `grant_id`)。

### 4.4 WORKSPACE_LOST drain 引用的外部状态机片段 [LATER](属 §3.1/§3.2,此处为冻结引用)

- effect:`ready` → `cancelled_before_dispatch`(code `ABORTED_BEFORE_DISPATCH`);`planned` 为 seal 事务内临时构建态、不持久化;`dispatch_started` = in-flight。
- attempt:与 effect 同事务转 `cancelled_before_dispatch`(最大 `attempt_no` 行);终态化后唯一允许操作为 audit/receipt 重放。
- step:`blocked_unknown_effect`(有未决 unknown)/ `waiting_effect`(非 sticky cancel 等待)/ `cancel_requested`(sticky cancel 等待)/ `failed_terminal`(outcome_code `WORKSPACE_LOST`)。
- session:`failed`,`failure_code=WORKSPACE_LOST`;`sessions.drain_step_id` 写入 → drain 完成同事务清空;`active_step_id` 保持清空、MUST NOT 在 terminal session 重填。

---

## 5. P0B 相关性标注(判定汇总)

P0B 最小闭环判定标准(任务给定,user event → create step + 初始 decision seal 同事务 → create fake LLM effect(seal 事务内同事务创建唯一首个 attempt 行 attempt_no=1)→ dispatch(只绑定既有 attempt、不补建)→ complete effect(成功证据分类 + assistant message 事件)→ step/session 聚合 → yield/finish_session;外加 kill-at-every-boundary chaos、命令幂等、canonical profile、seq 无洞、turn finalization reducer、双 fence 基本语义(stale completion 拒绝)、Conformance 1 核心断言)。

### [P0B-CORE]

1. **`slices` 表 + 最小 schema + `UNIQUE (workspace_id, name)` + kind 闭合集**:seal 授权与 dispatch 门的数据依赖(闭环路径经过两道门,需要可判定的 grant 数据模型;P0B 测试 seed 一条可通过的 grant 即可)。
2. **`grants` 表 + 最小 schema + subject_kind/capability 闭合集 + workspace_id 复合外键(或等效约束)**:同上;capability 闭合集中 P0B 实际行使的是 `authorize_effect` / `effect_submit` / `tool_resolve` / `event_append` 路径所覆盖的判定。
3. **有效 grant 判定谓词(基础五条件 + 三强制合取项 1/2/3)**:seal 门与 dispatch 门共用的前置谓词,闭环必经。
4. **`GRANT_DENIED` 拒绝路径 + 两道实时门检查点**(seal 阶段 `create_effect_in_seal` 成员创建前完整实时授权、零副作用稳定拒绝;`ready -> dispatch_started` 实时重验;两道门各自独立、任一通过不豁免另一门):P0B 的 seal 事务与 dispatch 转移按冻结合同必须内嵌这两个检查点(测试环境签发全通过 grant 走正路径)。
5. **slice/grant 内容不可变的表级行为**(不提供 `spec`/`constraints` 的 UPDATE 路径):建表即定型,P0B 天然满足,无需额外实现。

### [LATER](完整抽取已在上文,后续里程碑直接引用)

1. 授权线性化点(机制 (a) `SELECT ... FOR UPDATE` 固定锁序 `(workspace_id, slice_id, grant_id)` 升序 + §3.1.2 锁序嵌套;机制 (b) `revocation_version` CAS + 增列;裁定规则闭合)——grant/slice 撤销并发竞争,P0B 无撤销场景。
2. 两阶段授权的 manifest 快照细节(§3.3 manifest hash 绑定)——P0B 用固定 canonical profile。
3. `stream_ingest` 双 grant 合取 + `CHUNK_ATTRIBUTION_INVALID`。
4. `compact` capability(`compact_lock`/`compact_finalize`/`compact_abort`)。
5. `plugin_specs.required_services` 目录声明、T2/T3 compat 插件 profile、sandbox 声明约束。
6. §2.2 全部:`workspace_handles` 表与五状态状态机、受控 mutation 三段协议(CAS 公式)、yield 前 checkpoint 协议、`materialize(checkpoint_digest)` 及四项拒绝条件、WORKSPACE_LOST fail-closed 与确定性 failure-drain((a)(b)(c) 全链、`ABORTED_BEFORE_DISPATCH`、`drain_step_id`)、fork 继承规则、capability API 边界。P0B 的 fake LLM 闭环无 workspace 执行态(无文件/REPL mutation),yield 为 session 层命令,双 fence 基本语义指 stale completion 拒绝(effect 层,§3.2.2);workspace 层 fence(fenced publish 拒绝)留待含 workspace 的里程碑。

### 实现注意事项(给后续实现者)

- `slices`/`grants` 无完整类型级 DDL,实现时补类型/NOT NULL 需与 §0 不变量 12(workspace_id 一致性由复合外键或等效数据库约束强制)对齐,且不引入规格外的 UPDATE 路径。
- `grants` 规格未给 UNIQUE 约束,不要自行发明幂等键;命令幂等以 §3.1.2 command_id receipt 为准。
- WORKSPACE_LOST drain 中引用的 effect/step/session 状态与 code 属 §3.1/§3.2 冻结条款,实现 drain 时以那两节 digest 为权威,本节只锁定触发条件与同事务原子性要求。
