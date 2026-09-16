# v8 修改方案

> 对 `docs/designs/v8.md` 的**规范补全**，不是把 v1–v7 拼成新内核。
> 宪法不动：一份行为合同、两份运行时；SQL 拥有 yield-loop；worker 无会话真相；`jobs` 是 effect 总线。

| 字段 | 值 |
|---|---|
| 对象 | `docs/designs/v8.md`（原文不改；本文件是修订指令） |
| 日期 | 2026-09-04 |
| 独立审核 | `docs/reviews/v8-independent-review-2026-09-04.md` |
| Oracle review | `prompt-exports/oracle-review-2026-09-04-094732-untitled-chat-2ea1a5-510a.md` |
| Oracle plan | `prompt-exports/oracle-plan-2026-09-04-095754-untitled-chat-2ea1a5-a48a.md` |
| 吸收范围 | v1–v7 的 *不变量 / 协议 / 验证纪律*，已对照源码抽查 |
| 明确不吸收 | v1 SQL 内 HTTP/`WHILE`；v3 PGMQ 当 loop 主人；v2/v3 sticky TEMP 当真相；v6 DuckDB 拥有循环；v7 Flock owner / waiver |

---

## 0. 融合策略

v8 先按自己的目标审过：方向对，规范不够。v1–v7 是另一条谱系，只从里面抽**已经在本仓库跑通过、且正好补审核缺口**的东西：

| 缺口（审核） | 吸收的是什么 | 不吸收的是什么 |
|---|---|---|
| effect 幂等 / stale worker | v3「等外部时不持 SQL 事务」；v4 `(queue,msg_id)` 只应用一次；v6 结果先缓存再 apply | PGMQ 当循环主人；`last_applied_hash` 当全 run 粗粒度幂等 |
| 四缝 vs 真实 IO | v1「决策纯函数、动作薄外壳、编排是数据」；v3 SQL 组织请求 / worker 执行；v4 catalog-driven dispatch | v1 `rlm_loop` 内 `WHILE + http_call_llm` |
| 目录世代 | v2/v4「全体校验通过才 TRUNCATE+INSERT」 | `plugin_bindings` 当第二套权威 |
| fold 可比 | v1 `fold_messages` 可单测；v5 32/128/256KiB 硬帽 | 用一轮 LLM 在内核里补缺失 prompt |
| 失败可比 | v2 `{Type,Phase,Problem,Solution}`；v6 redact + 截断 | 把 URI/密钥原样写 event |
| workspace handoff | v4 TEMP vs run_schema 显式建模；v6 `DUCK_SESSION_LOST` 失败封闭；v7 reader_guard | sticky 连接当会话真相；DuckDB 当 workspace 实现前提 |
| 子 run | v4 flat fanout + 一次唤醒 barrier | v1 同步嵌套 `rlm_loop`；三张 wait-group 表当第二状态机 |
| 证据纪律 | v7 E0–E3、未知必须 `null+notes`、phase gate ≠ release gate | Phase 0 waiver、tachiom 债务、Flock owner |

---

## 1. 针对审核的修改（按风险）

每条格式：**改什么 → 为什么 → 从哪吸收 / 明确拒绝**。对应审核 Finding 见独立审核稿。

### 1.1 固化 lease、fence、effect ledger

**对应 Top 1 / F2**

**改：** 在 §2.2 后加「claim、fence 与 effect 生命周期」；§5 补 `leases` / `effects` / `jobs` / `effect_attempts`。

- `claim` 必须带 `expected_driver`、`worker_id`、runtime capability。
- Native `checkpoint` 只收一个已持久化 `effect_id` 的结果信封，禁止 worker 任意塞 `events[]`。
- 每次成功 claim，`fence` 单调递增。
- 每个 effect 持有 `session_id, step_id, effect_id, dispatch_fence, attempt_no, retry_class, idempotency_key`。
- 闭合状态：`planned → ready → dispatch_started → {succeeded, failed_retryable, failed_terminal, cancelled_before_dispatch, unknown_outcome}`。
- **外部调用前**同一事务写入 `dispatch_started`；只有当前 fence 能提交结果。
- 废掉 `provider_key = md5(session_id || '/' || step_name)`。改成库内在 effect 创建时写入、跨 driver 稳定、每逻辑 LLM 调用唯一的 key。`step_id` 是主键；`step_name` 只是别名。
- `non_retryable` 一旦「已发出、结果未知」→ `unknown_outcome`，禁止自动重放。

**为什么：** 拒掉过期 checkpoint 只能防日志污染，不能防旧 worker 再打一次 LLM/工具。没有 dispatch marker，§1.2 第 6 条（未派出 vs 已流出前缀）无法实现。`step_name='llm'` 会让不同 turn 撞同一个 provider key，直接破坏第 9 条。

**吸收：** v3 的「等模型不持事务」+ apply 侧幂等（`v3/worker.py`、`apply_llm_response`）；v4 `processed_queue_messages ON CONFLICT DO NOTHING` 升格为 effect-level ledger（`v4/plugin_taxonomy/plugin_taxonomy.sql`）；v6「库外结果缓存后再 apply」、不可静默重放。

**拒绝：** v3 `last_applied_hash` 当全 run 幂等；v1 用 SQL `sql_retry` 包真实副作用；visibility timeout 自动重做 `non_retryable`。

---

### 1.2 收紧四缝，补 SQL↔worker 的 effect ABI

**对应 Top 2 / F1 / F4**

**改：** §2.3 四缝仍是 `recall / fold / env_read / tool_dispatch`，但定位改成：**插件访问领域数据与工具目录的唯一合法 seam**，不是 LLM / 工具执行 / workspace mutation 的全部机制。

§2.2 新增 **effect ABI**（不对插件开放的第五条数据缝，是 loop 与 worker 的唯一执行协议）：

1. SQL 按 fold、grants、catalog、当前 fence 产生 durable `EffectDescriptor`。
2. worker 只执行该 descriptor 描述的一次 LLM 或 tool effect。
3. worker 回交 schema-valid `EffectResult`。
4. SQL 按 result / effect state / fence 生成 canonical events，并决定 `yield | wait | sleep | complete | fail`。

`tool_dispatch` 改为：在当前 slice/grant/catalog 内解析并授权一条 tool route，产出 descriptor 的输入——不是「只返回描述」。

`agent_tick` 不是第三套状态机，是 yield-loop 动词的事务编排入口。Native worker **不得**决定下一步、不得自行进 tool loop、不得直接 append 事件。

`define_tool.execute` 由 effect runner 调用；只拿 capability-scoped context 和已验证参数；不得拿裸业务 PG 连接。

**为什么：** 现文同时要求「`tool_dispatch` 不执行」和「`execute` / `llm.complete` / memories 能产生 effect」。poller 的 `dispatch(task)` 没定义 task 是什么，四语言会把控制流放在不同位置，行为合同立刻裂。

**吸收：** v1 L0–L5 职责切分（`v1/pg_agent_functional.sql` 开头口诀）；v3「SQL 组织请求、worker 执行、回库 apply」；v4 catalog-driven generic dispatch、控制流不看 queue kind。

**拒绝：** v1 `rlm_loop` 内 `WHILE + http_call_llm`；v3 worker apply 完自己再 `enqueue` 下一轮；v5 动态 SQL 绕过 capability seam。

---

### 1.3 §5 升格为规范性数据合同

**对应 Top 3 / F7**

**改：** 删掉「与修正案一致」。§5 改名「规范性数据合同」。每个持久对象列出最小字段、唯一约束、写入者、生命周期。完整 DDL 放附录，正文不能只剩表名。

最小对象：`sessions`（含不可变 `driver`、`next_seq`、`next_fence`）、`session_events`（含 `turn_id/step_id/effect_id/surface_op/source_event_seqs/ignorable/schema_version`）、`leases`、`effects`/`jobs`/`effect_attempts`、`plugin_catalog`/`catalog_generations`/`tool_catalog`/`tool_routes`/`handler_registrations`、`grants`/`slices`/`workspaces`/`compaction_locks`/`forks`、`kv_current`/`kv_history`。

枚举封闭：event type、`surface_op`、effect kind、retry class、driver、plugin lifecycle、workspace lifecycle。

`append_events` 是唯一事件写入口：锁 `sessions` 行后分配 `next_seq`，**已提交事件连续无洞**。禁止用可回滚留洞的 `bigserial`/`sequence` 当 session 语义序号。

projection 可物化，但只能从 log 重建。`sessions` 的协调字段不是第二份行为真相。

**为什么：** 合同词（`ignorable`、`ABORTED_BEFORE_DISPATCH`、fork 切点）没有结构就无法实现 fold/repair/跨 driver 比较。`UNIQUE(session_id, seq)` 不等于无洞。

**吸收：** v1 append-only steps + 状态由折叠推出（`agent_runs` 故意无 status 列）；v4 注册表全量校验、原子替换。

**拒绝：** 把 v1/v3 `bigserial` 直接当 v8 seq；v4 `plugin_bindings` 与 v8 catalog 并列。

---

### 1.4 「相同 raw 事件」改为「相同 canonical trace」

**对应 Top 4 / F6 / F14**

**改：** §1.2 第 1 条改为比较 **canonical trace**。raw `session_events` 允许 driver-specific 传输细节。

新增 `normalize_events(driver, persisted_events) → canonical_trace`：

- 归属键：`turn_id` / `step_id` / `effect_id`
- `assistant/chunk` 与 `turn/delta` 按 seq 合并
- 有 final `assistant/message` 时校验并采用 final
- 无 final / 部分流 / timeout / cancel / repair 的标准表示
- `ignorable`、timestamp、attempt、worker metadata 不参与跨 driver 比较
- 比较顺序由逻辑 turn/step/effect plan 决定，不靠 wall-clock

§1.3 的 plan-mode 差异收窄：pending plan-mode **只是**不可观察、不可授权、不可触发 effect 的运行时缓存；crash/handoff 后两边都从最后一条 canonical event 恢复。它不是 portable 行为。

`execute` 返回值必须 schema-valid JSON；序列化固定 **RFC 8785 / JCS**。禁止 `NaN`/`Infinity`/裸二进制/locale date。`output.render` 是无 IO 纯函数，UTF-8；suite 比较规范化字节。

**为什么：** §1.2 要类型序列相同，§1.3 又允许三种落盘方式，规则不能同时成立。没有 canonical JSON，TS/Python/Swift/SQL 会在数字、键序、错误对象上吵死。

**吸收：** v1 `fold_messages` 作为可单测纯函数的方法，不复用其 event 形状；v5 assemble 必须有稳定输出。

**拒绝：** 用 JSONB 文本、语言默认键序、token 密度判断等价。

---

### 1.5 driver 互斥下沉到数据库

**对应 Top 5 / F3**

**改：** `sessions.driver` 创建时写入，**会话生命周期内不可变**。换 driver 只能 fork 新 session。

`claim` / heartbeat / checkpoint / yield / wait / sleep / complete / fail 都验 `expected_driver` + fence。

claim 原子条件：

1. `sessions.driver = expected_driver`
2. 无未过期 lease，或旧 lease 已按规范 stale
3. worker 已登记当前 step 所需 locus capability
4. 当前 catalog 对该 driver 有唯一可执行 route

compat host 的 driver 检查降为调用同一数据库 API 的结果，不是安全边界。

**为什么：** Native claim 无 driver 参数时，配错的 Native worker 可以领走 compat session。

**吸收：** v4 先查 catalog 再执行的 generic dispatcher。

**拒绝：** 两个 runtime 各自维护 ownership；靠 gateway 配置当锁。

---

### 1.6 catalog generation + tool route + handler drain

**对应 Top 6 / F5 / F16**

**改：** `refresh_plugins()` 升级为 generation 协议：

1. 扫描并校验全部候选
2. 一事务创建新 `catalog_generation`
3. 新 generation `active`
4. 旧 generation `draining`
5. 新 assemble 只看新 generation
6. 旧 generation 只收束已绑定它的 in-flight effects
7. drain 完成或超时 → `disabled`

分工：`plugin_catalog` = 逻辑声明；`tool_catalog` = 对模型可见的工具合同；`tool_routes` = 每个 `(scope, driver, canonical_tool_name)` 在一个 generation 内**一条**执行路；`handler_registrations` = 短租约运行态，不是权威。

`tool_dispatch` 和 effect dispatch 都校验 generation + registration；否则 fail closed——不许「模型看得见、没人能跑」，也不许旧 handler 接下一代 effect。

卸载三分：对未来 assemble 立即不可见；对已创建 effect 按 drain/取消/`unknown_outcome`；本进程 LIFO disposer 只撤本进程登记。

compat publisher 只能写 `driver_scope=dsh-compat` 的 route。

**为什么：** 「目录权威」和「apply 只登记本进程」目前没接上。同名、不同 locus、不同 driver 谁赢也没写。

**吸收：** v2 `refresh_workbench_tools()`、v4 `refresh_plugins()` 的「全体校验、失败旧表不动」（已核 `v4/plugin_taxonomy/plugin_taxonomy.sql:216`）。

**拒绝：** 把 `plugin_bindings` 当第二目录；`TRUNCATE` 掉仍有 in-flight 的唯一可追溯版本。

---

### 1.7 取消 / compaction / crash 的统一 dispatch gate

**对应 Top 7 / F8**

**改：**

- `cancel/requested` 是 durable event
- `compaction/start` 取得带 fence 的 `compaction_lock`
- `ready → dispatch_started` 的事务必须同时检查：未取消、无 compaction 阻塞、当前 fence 有效
- 没跨过 gate 的工具 → `ABORTED_BEFORE_DISPATCH`
- 已跨过的按 result / partial / unknown 收束
- 并行工具用稳定 `effect_plan_index`，取消时逐 effect 判断，不靠 wall-clock 决定「前缀」
- **P0 compaction 是纯 SQL fold**，锁期间禁止创建或派发 LLM effect
- `release_stale()` 按 effect 状态修：未 dispatch → 取消或再排队；已 dispatch 且幂等 → 同 key 恢复；已 dispatch 且 `non_retryable` → `unknown_outcome`；已有 durable result → 只补终结事件，不改历史
- `inspect` / projection rebuild / dry-run 无写

**为什么：** 没有 dispatch marker，第 6 条无法实现。compaction 若自己调 LLM，和第 5 条打架。

**吸收：** v3「崩溃靠持久协议恢复」，不用 PGMQ visibility 当唯一真相；v4 child replay 不重复唤醒；v6 失败不静默造空状态。

**拒绝：** 同步 nested loop；用 queue `read_ct` 表达「是否真正派出」。

---

### 1.8 RLS / slice / grant / workspace handoff 变成可执行边界

**对应 Top 8 / F9 / F10**

**改：** 新增「授权与 workspace 合同」：

| 词 | 含义 |
|---|---|
| 租户 `workspace_id` | RLS 租户隔离 |
| `slice` | 可访问的命名资源边界 |
| `grant` | 对某 slice/capability 的主体、操作、有效期、撤销 |
| `workspace_handle` | run 私有执行态（worktree / REPL），**不是**租户 id |

每次 seam 调用、route 解析、effect dispatch 都验有效 grant。

最小 DB role：API（只能经受控函数追加用户输入）/ worker（claim/prepare/dispatch/commit，禁止对 `session_events` 或业务表直接 DML）/ SQL plugin（无业务表直权）。`SECURITY DEFINER` 固定 `search_path`。

T2/T3 compat 插件是 **operator-trusted host capability**，必须声明文件/网络/子进程 profile。未提供强制 sandbox，就不得声称支持不可信插件。

workspace 状态：`active → handoff_ready → lost | discarded`。yield 前必须写 checkpoint/manifest，或显式 `workspace/lost`。下一 worker 只能 materialize checkpoint；缺失返回 `WORKSPACE_LOST`，**禁止**静默建空 workspace。

fork 默认不继承 live handle；只继承标记 delegable 的 immutable slice，并为 child 签发新 grant。

**为什么：** 「run 私有」和「yield 可换 worker」现在互相打架。`required_grants[]` 只是 metadata，不是安全边界。最小 grant 不能等到 P2。

**吸收：** v4 session lifetime 显式建模、`cleanup_run_session()` 只在 terminal 删；v6 `DUCK_SESSION_LOST`、凭证不进队列、mutation 顺序门；v7 raw handle 不外泄、非 owner 打不开。

**拒绝：** v2/v3 sticky TEMP 当会话真相；把 DuckDB 或 `run_schema` 当成 v8 workspace 的实现前提。

---

### 1.9 观测、脱敏、预算

**对应 F11**

**改：** 每个 effect attempt 关联：`session_id, turn_id, step_id, effect_id, attempt_no, fence, driver, plugin identity/generation, tool route, provider_key, workspace_handle`。

最小审计：claim、heartbeat、fence reject、dispatch start、commit、retry、unknown outcome、grant denial、catalog generation 切换、handler drain、workspace loss。

metrics allowlist（沿用已验证字段）：`worker_id, attempts, duration_ms, model, provider, input_tokens, output_tokens, total_tokens, cost_usd`。

日志/错误里的 URI、password、API key、token、secret 必须脱敏，错误文本有上限；prompt 原文不进常规指标。

budget 检查发生在 durable apply/commit 边界，worker 本地判断不能单独把 session 标 terminal。

**为什么：** 双 driver 漂移、stale worker、provider 超时、catalog 版本错，只靠 `session_events` 查不清。没有 allowlist，日志会变成越权数据路径。

**吸收：** v4 `sanitize_step_metrics` + `record_budget_step` 在 apply 内收束（`v4/observability_budget/observability_budget.sql`）；v6 `redact()` 剥 URI/密钥、截断 1000（`v6/budget_observability/duckdb_errors.py`）。

**拒绝：** GUC 暂存 metrics；完整 prompt/credential 进 job payload。

---

### 1.10 §6 改成可执行的三层 suite

**对应 F12**

**改：** 仍是两个 driver 各跑一遍。13 条散项改成三层：

1. **共享 canonical trace**：同一 fixture 比 canonical trace、canonical tool JSON、render bytes
2. **共享持久协议 / fault-injection**：lease、fence、dispatch gate、repair、fork、丢 notify
3. **adapter/runtime**：Native tick ABI、compat coordinator/storage、授权、workspace

每个 fixture 用 deterministic fake LLM / fake provider / fake tool。真实模型输出**不能**当 runtime 等价判据。

建议固定的 13 个 suite：

1. catalog / execute / render / unload
2. append、inject、seq 连续、fold
3. driver-checked claim、stale lease、fence reject
4. effect ledger、provider key、retry、unknown outcome
5. crash / load / repair / inspect 无写
6. reject 与 compaction gate
7. timeout、cancel、并行 tool 前缀
8. notify 丢失后的 seq/rev 补拉
9. fork 切点、child enqueue、parent barrier
10. portable hook 代数、canonical JSON、render
11. RLS、grant、secret redaction、fail-closed
12. workspace handoff / loss / mutation order
13. dsh-compat persistence / coordinator / storage contract

每条声明：输入 fixture、允许的 raw 差异、canonical oracle、故障注入点、两 driver 断言范围。

**为什么：** 现在 fork 没有测试；「两边都绿」不等于合同被验证。

**吸收：** v4 分阶段 gate、无网络 deterministic test、replay 不重复逻辑步；v7 evidence 分级、blocker 明示、phase gate ≠ release gate。

**拒绝：** 单边绿就标 portable；用真实 LLM 非确定性输出做合规。

---

### 1.11 Portable Hook Profile v1

**对应 F13**

**改：** `portability=portable` 必须声明 profile version。只允许两类可移植 hook：

- `pre_step`：`pass | reject(code, details) | augment(messages[])`
- `post_tool`：`pass | block(code, details) | augment(contexts[])`

fold 排序：`(priority DESC, plugin_identity ASC, hook_name ASC)`。reject/block 优先，冲突取排序最前的失败。message/context 拼接用同一排序，废除含糊的「按序 prepend」。

compat 可以继续 `next()` 以保住官方 listener 链，但 portable handler **不得**读/改/吞下游返回对象。可移植结果只能来自同一份输入与 config。

`缺席/超时 = pass` **只**适用于 advisory hook。授权、过滤、工具选择必须走四缝 / dispatch gate，fail closed。

**为什么：** 只靠一个 `portability` 字段挡不住「改下游返回值 / 不调用 next / 依赖洋葱顺序」——这些 Native 表示不了。

**吸收：** v1 可组合纯决策；v4 metadata 必须过全量校验。

**拒绝：** Native 仿 Fiber / `waterfall(next)`；把安全授权做成可超时 pass 的 hook。

---

### 1.12 dsh-compat adapter 合同

**对应 F15**

**改：** §3.3 后加 **persistence-pg canonical adapter contract**：

- DSH 事件 → v8 raw event → canonical event 的映射表
- `turn_id` / `step_id` / `effect_id` / `source_event_seqs` / `ignorable` 从哪来
- append 去重键、seq 分配、repair 前置状态、repair 新增事件
- 官方 `load()` 哪些属于合同，哪些只是 compat 内部缓存
- provider/tool dispatch 如何经过共享 effect ledger 和 dispatch marker

compat repair 必须走与 Native 共享的 canonical repair，不能凭 host 内存猜「工具是否已流出」。

P0 前置验证：官方 Cordis/DSH 公共集成点是否足以在外部 effect 前持久化 `dispatch_started`。做不到，compat 不得宣称满足 §1.2 第 6、9 条——先缩小支持面或补 interception。

「官方 PersistenceCoordinator」「storage-pg 过 `tests/contract.ts`」改成带版本/commit/测试摘要的 adapter manifest。

**为什么：** DSH 内部事件和 repair 不会天然满足 v8 的 fence、ledger、seq、canonical trace。映射留给实现者，双模式必然漂。

**吸收：** v3/v4 持久 apply 边界和 idempotent replay。

**拒绝：** 另存 JSONL 当 compat 真相；用进程内 Map 代替 durable dispatch marker。

---

### 1.13 路线图改为「协议先冻、功能后扩」

**对应 F17**

**改：** 按第 4 节重排。`storage-pg`、effect ledger、driver-checked claim、最小 grants、canonical normalizer、cancel/compaction gate 不得再拆到 P1/P2。P0 不再只证明 `greet` 能跑，而必须证明 Native 与 compat 走同一不可回退协议。

**为什么：** 现在 P0 已经跑 compat host，却把 `storage-pg` 放 P1；P2 才接 grant，四缝从 P0 就是安全边界。早期 demo 会反向锁死协议。

**吸收：** v4–v6 每阶段独立 gate、失败即停；v7「evidence gate 与 release gate 不能混同」。

**拒绝：** user waiver；未解决 blocker 也声称阶段通过。

---

### 1.14 去掉外部术语的隐式依赖

**对应 F18**

**改：**

- 删除 §5「与修正案一致」（和开头「独立新稿」冲突）
- 新增 glossary：RSI、基因组、slice、grant、workspace、tenant workspace、run、turn、step、effect、repair、canonical event、storageDomain、catalog generation、route、driver、locus
- 「yield 五件套」明确为 `claim / checkpoint / yield / wait / sleep`；`complete/fail`、`heartbeat`、`release_stale` 是终结与维护动词
- `zcordis-pgembed`、`pg_cordis`、DSH packages、`PersistenceCoordinator`、`DefineToolOptions`、`tests/contract.ts`、`deepseek-harness-sdk` 进入外部兼容清单：用途、适用范围、版本/commit、接口摘要、验证证据。未知一律 `null + note`。P0 禁止未解析外部项时宣称 compat contract 已过

**为什么：** 独立设计不能让「修正案」「zcordis 的核」承担没写出来的规范。「五件套」现在列了八组动词。

**吸收：** v7 `null + notes`、未知不编造。

**拒绝：** 把 v7 Flock 依赖、waiver、未验证外部细节写进 v8 合同。

---

### 1.15 措辞

**对应 F19**

**改：** 「不进行为合同」→「不作为行为合同」。给「本步工具」「并行度」「exclusive」「工具触发子 run」「纯数据 hook」补正式定义。纯 SQL hook 仍过 grant/RLS、超时、输入 schema；「不入队」≠「绕过授权」。

**吸收：** v1 `TEST_REPORT.md` 的教训——`\\b`、`jsonb ||` 对 object 是合并、`::regproc` vs `::regprocedure`、`regexp_match` 1-based，都会让校验静默失效。这些写进附录 J，不是 v1 兼容义务。

---

## 2. 审核没点名、但仍值得写进 v8 的

| 写入 v8 | 为什么 | 来源 | 不吸收 |
|---|---|---|---|
| §2 前加责任分层：纯 fold/validation、状态编排、effect execution、catalog activation、runtime transport | 防止 SQL / worker / handler 同时拥有路由和状态决策；每层可独立测 | v1 L0–L5 | SQL 内 LLM HTTP 与同步 `WHILE` |
| `assemble` 硬帽：32 slot / 128 message / 256 KiB canonical prompt；超限在 dispatch 前失败或进确定性 compaction | 防止不同语言序列化或无界 recall 得到不同 prompt | v5 `assemble_prompt_messages_for`（已核 `c_max_slots=32` 等） | 用一轮 LLM 在内核里生成缺失 part |
| SQL-locus 工具参数闭合类型：`text` / `integer` / `boolean` / `jsonb`；键与登记签名精确一致 | 禁止隐式 cast、多余参数、签名漂移绕过 catalog | v5 `invoke_named_llm_tool` | 任意类型 dynamic SQL |
| 统一错误信封：`success, Type, Phase, Problem, Solution` + 稳定 `code` + 关联 ID；脱敏截断 | 失败行为必须跨 driver 可比 | v2 WORKBENCH_ERROR；v6 redact | DB 内部错误/URI/credential 原样落盘 |
| 可变 workspace 的每-handle `op_seq`，只对 mutation 串行；只读仍可并行 | 不全局串行，又能恢复同一 worktree 的修改顺序 | v6 `last_completed_op_seq+1` | DuckDB session / duck_heavy 队列合同 |
| 子 run = durable `wait`：child terminal 后由 log-derived projection 判定**一次**唤醒；重复完成不重复唤醒 | 保住「子 run 一律 enqueue」，避免未定义同步递归 | v4 `maybe_resume_parent` | 同步 `rlm_loop(v_child)`；三张 wait-group 表当第二状态机 |
| 协议证据清单：schema version、外部兼容清单、suite 结果、已知限制、未验证项 | 防止无证据写成「已支持」 | v7 VERSION_MANIFEST / EVIDENCE_REGISTER | Flock owner 范围、waiver |
| 设计 conformance gate ≠ 生产 release gate | suite 绿只证明行为合同；发布还要权限部署、provider、监控、灾备证据 | v7 `phase0_evaluator` vs `release_evaluator` | 一个绿单测 = 可发布 |

---

## 3. 修订后 v8 应有的章节骨架

正文不动宪法（§0、双模式目的、三态、明确不做），按下面扩：

| 节 | 必须写出的最小内容 |
|---|---|
| §0.1 独立性与非目标 | 不迁移、不加载、不继承 v1–v7 schema/runtime；拒绝清单 |
| §1.2 行为合同 | 9 条不变量每条链到 suite ID 和 canonical oracle |
| §1.5 Canonical trace | raw→canonical、chunk/delta/final、忽略字段、JCS、render |
| §2.0 Native 责任边界 | 谁拥有控制流；worker 只执行 descriptor |
| §2.2a claim/fence/effect | 五件套 vs 维护动词；状态机；stale repair；幂等键 |
| §2.2b Tick ABI | `Claim` / `EffectDescriptor` / `EffectResult` / `TickDirective` 字段与事务边界 |
| §2.3 四缝与授权 | 每缝输入输出、grant 检查、失败码；与 effect ABI 的边界 |
| §2.4a catalog generation | `pending→active→draining→disabled`；route 唯一；unload |
| §2.6 workspace / slice / grant | 租户 vs 执行态命名；handoff；fork 继承 |
| §3.4 compat adapter | 官方事件映射、dispatch interception、compat-only 范围 |
| §5 规范性数据合同 | 取代「数据面要点」 |
| §6 Conformance matrix | 13 suite + 设计 gate vs release gate |

附录 A–J：术语与外部兼容清单；schema 字段合同；状态机与失败矩阵；Native ABI；canonical event/JSON/render；portable hook profile；安全与凭证；观测/错误/预算；fixture 与 gate；PostgreSQL 实现陷阱。

附录**不**要求完整 DDL，但禁止只有表名。

---

## 4. 修订后的 P0–P3

v8 是新 schema / 新 runtime。P0 **不含**任何 v1–v7 数据迁移或 loader 依赖。

### P0 · 不可回退协议核

范围：glossary + 外部 manifest；§5 schema；`append_events`；连续 session seq；独立 KV rev；driver-checked claim；单调 fence；effect ledger；`jobs` 当 effect 总线；cancel/compaction gate；最小 role/RLS/grant；canonical JSON/trace；deterministic harness；Native fake LLM 单 step；compat persistence/storage 单 trace。

Gate：

1. 任一 schema/API/外部项无定义或无版本证据 → 失败
2. Native 与 compat 写入同一 canonical trace
3. stale fence、duplicate result、unknown outcome、driver mismatch、grant denial 都有绿 fixture
4. worker 外部等待不持 SQL 事务
5. 禁止 SQL HTTP、第二 queue loop、direct event DML

来源：F1–F4、F7–F10、F15、F17、F18；v3 worker 边界；v4 idempotent apply；v6 fail-closed；v7 manifest 纪律。

### P1 · 目录与第一个 portable 能力

范围：catalog generations；tool routes；handler registrations；Portable Hook Profile；`greet` 的 Native + compat 两实现；inject/reject/timeout/unload。真实 provider 可选，**不能**替代 fake suite。

Gate：相关 suite 双 driver 过；refresh 失败不影响旧 generation；unload 不再暴露新 route；provider key 在 retry 中稳定；无直连业务表的静态/运行时检查过。

来源：F5、F6、F12–F14、F16；v2/v4 原子刷新；v5 工具校验。

### P2 · 多 runtime 与第三态扩展

范围：Python/Swift/SQL/TS route；同一 Native turn 出现第二语言工具；memories；credential provider；最小 worktree/REPL；delegable slice/grant；workspace `op_seq`；fork + child barrier。

Gate：换 runtime 不改 canonical trace；handoff 能恢复 checkpoint，丢失固定 `WORKSPACE_LOST`；mutation 顺序不乱；fork 的 `inherited_event_count` / grant / child resume 确定；credentials 不进 events/jobs/logs。

来源：F10–F12；v4 durability/fanout；v6 op_seq 与失联 fail-closed；v7 reader guard。

### P3 · 生态与 RSI

范围：一个真实 T0 社区包在 compat 上零改跑；抽 fixture；Native 重写并标 portable；RSI 的 propose/eval/commit/rollback **只**动 Native catalog generation。

Gate：社区包的 adapter 映射、官方 contract、v8 suite 都有证据；Native 重写后 canonical trace 与 compat 相等；RSI 不可改 compat runtime；rollback 只切 generation，不改既有 history。

来源：v8 原 §4/§7；F12、F15、F18；v7 evidence/gate 纪律。

---

## 5. 明确不改的宪法

修改只补执行协议，不削弱：

1. **一份行为合同、两份运行时。** 漂移是 bug。
2. **Native 默认，SQL 拥有 yield-loop。** worker 无会话真相。
3. **dsh-compat 是第二实现**，不是临时桥，也不是第三条循环。
4. **同一 `session_id` 只有一个 driver。** 本方案把它做成数据库协议。
5. **三态：** `session_events` 历史唯一真相；projection 可重建；workspace 可丢弃，不变成历史。
6. **两套时钟：** `(session_id, seq)` 与 `kv_rev` 分离；禁止 `global_rev`。
7. **`jobs` 是 effect 总线**，不是第二 loop 主人。
8. **Native 不仿 Fiber / `next()` / isolate 子树。**
9. **插件 = 目录行 + `apply` 只登记 + handler。** 不让 `apply` 重新承担业务循环。
10. **四缝失败封闭。** 只澄清它们是领域访问缝，不是绕过 effect ABI 的漏洞。
11. **`refresh_plugins()` 全体校验后切换。** 改为 generation/drain，而不是即时遗忘旧版。
12. **子 run 一律 enqueue。** 不恢复同步 nested LLM loop。
13. **RSI 只进化 Native 基因组。** portable 结果仍须在 compat 上回归。

---

## 6. 建议的落地顺序（相对本文件）

1. 把本方案第 1–5 节合进 `docs/designs/v8.md` 的下一稿（保留宪法原文，扩规范附录）。
2. 先写附录 B/C/D/E（schema、状态机、ABI、canonical trace）——没有它们 P0 不能开工。
3. 再写 Portable Hook Profile 和 compat adapter 映射表。
4. 最后才是 greet 的双 driver 实现。

本文件**不**修改 `v8.md` 原文，等确认后再合稿。
