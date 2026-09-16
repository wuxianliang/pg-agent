# v8 独立审核（不对照 v1–v7）

| 字段 | 值 |
|---|---|
| 对象 | `docs/designs/v8.md` |
| 日期 | 2026-09-04 |
| 方式 | RepoPrompt Oracle `review`（chat `untitled-chat-2EA1A5`） |
| 导出 | `prompt-exports/oracle-review-2026-09-04-094732-untitled-chat-2ea1a5-510a.md` |
| 前提 | v8 是独立设计。本审核**不**用 v1–v7 评定 v8。 |
| 后续 | 吸取 v1–v7 后的修改方案见 `docs/designs/v8-revision.md` |

---

## 总评

v8 的方向已经成形：一份行为合同、两份运行时；log / projection / workspace 三态；拒绝 Native `next()`、第二队列、共享 `global_rev`、同一 session 双 driver。守恒目标（事件、工具 JSON、inject、reject、compact、取消、卸载、fork 切点、LLM 幂等）写得很清楚。

问题是：它目前是**架构宣言和路线图**，还不是可交给多个实现团队的规范。最大缺口正好落在「漂移是 bug」上——canonicalization、step/effect ABI、fence 与 stale worker、外部副作用幂等、插件生命周期、权限执行、crash 语义都要靠实现者自行发明。若现在编码，最可能出现的不是局部 bug，而是 Native 和 compat 各自合理、整体却不可比较的两套行为。

---

## 文档在说什么

- **Native 默认**：Postgres 保存会话并拥有 yield-loop；worker 执行 LLM / 工具 / 外部 effect，不持有会话真相。
- **dsh-compat 第二实现**：Node host 跑官方 Cordis / `dsh-agent-loop`，经 persistence-pg / storage-pg 写入同一份 `session_events`。
- **插件**：目录行 + `apply` 只登记 + handler；可移植插件必须在两个 driver 上过同一 fixture。
- **明确拒绝**：Fiber、Native `next()`、第二队列当 loop 主人、worker 直写 `session_events`、共享 `global_rev`、全局 advisory lock、同一 session 被两个 driver 同时认领。

---

## Findings

### F1 · critical · §2.2 / §2.3 / §2.5 / §5

**四缝声明没有覆盖实际 effect 和写路径。** §2.3 把 `recall / fold / env_read / tool_dispatch` 写成「唯一合法 IO」，且 `tool_dispatch`「只返回工具描述，不执行」。同时 §2.2 有 `llm` / `tools` 阶段，§2.5 的 `define_tool` 有 `execute`，P0 还要 `llm.complete`。

实现者只能二选一：handler/worker 直接做 IO（违反四缝），或者没有任何合法的工具执行和 LLM 路径。

**建议：** 区分两类接口——(1) 数据/授权缝：四缝；(2) effect 协议：`llm_complete` / `tool_execute` / `workspace_mutate`，经 `jobs` + effect ledger。或把 `tool_dispatch` 改成「授权并生成 durable effect」。

### F2 · critical · §2.2 / §3.3 / §5 / §6.10–11

**lease/fence 只能挡住旧 checkpoint，挡不住旧副作用。** 没有规定 fence 是否单调、claim/heartbeat/yield 的原子条件、job 是否绑定 `(session_id, step_id, fence)`、lease 过期后旧 worker 能否继续发 LLM/跑工具、`release_stale()` 如何处理进行中的 HTTP/pty。

`provider_key = md5(session_id || '/' || step_name)` 只是字符串。若每轮都用 `step_name='llm'`，不同 turn 会撞键。

**建议：** 单调 fence；dispatch 前再验 fence/取消；effect ledger；`non_retryable` 的「已发出结果未知」进 `UNKNOWN`，禁止自动重放；`step_id` 每逻辑 LLM 调用唯一。

### F3 · major · §0 / §2.2 / §3.3 / §5

**driver 互斥没有数据库级约束。** Native `claim(session_id, worker_id)` 无 `expected_driver`。compat 只在 host 侧检查。`sessions.driver` 是否可变未定义。

**建议：** claim 校验 `expected_driver`；driver 创建后不可变，或只能在无 active lease / 无 running effect 时显式迁移。

### F4 · major · §2.2 / §2.5 / §7 P0

**SQL loop 与 worker poller 的边界未定义。** 「循环在 SQL」同时给出 worker `claim → dispatch → checkpoint`。`agent_tick` 是编排函数，但没说 worker 拿到的是 task、effect descriptor 还是已组装 prompt。

**建议：** `tick_prepare(fence) → descriptor`；host 只执行一个 descriptor；`tick_commit(fence, effect_id, result) → next state`。四语言同一 wire ABI。

### F5 · major · §2.4 / §2.5 / §3.3 / §6.1,7

**持久目录与进程内 handler 生命周期脱节。** catalog 是权威，`apply` 只登记本进程 handler。未说明：active 插件何时保证有 handler；一 worker unload 后其他 worker 是否仍发布该工具；refresh 如何处理 in-flight；`tool_catalog` 与 `plugin_catalog` 是否同事务。

**建议：** `pending → active → draining → disabled`；assemble 只选当前 generation 且有可用 handler 的工具。

### F6 · major · §1.2 / §1.3 / §3.3 / §6

**「相同事件序列」与允许的实现差互相矛盾。** §1.2 要相同类型序列；§1.3 允许 Native `turn/delta` 或只写最终 `assistant/message`，compat 多写 `assistant/chunk`。归一化函数未定义。

另：§1.3 允许 compat 丢失 pending plan-mode，§6.3 又要求杀进程后恢复——必须二选一。

**建议：** 定义 `normalize_events(driver, events) → canonical_events`。plan-mode 要么排除出合同，要么两边都必须持久化。

### F7 · major · §2 / §5 / §6 / §7 P0

**核心 schema、事件语法、API ABI 缺失。** §5 只有表名和少量字段。`surface_op` / `source_event_seqs` / `ignorable` / `ABORTED_BEFORE_DISPATCH` 等是合同词，没有结构。`UNIQUE(session_id, seq)` 不能保证无洞——PG sequence 回滚会留间隙。

**建议：** 附录给最小字段、唯一约束、写入者、状态转移、`append_events` 的 seq 分配规则。

### F8 · major · §1.2 / §3.3 / §6.3,5–8

**取消、compaction、crash 的竞态不完整。** 没有 dispatch marker 就无法区分「未派出」和「已流出前缀」。若 compaction 自己调 LLM，与「锁期间不派 LLM」矛盾。

**建议：** `effect_intent / dispatch_started / effect_completed`；compaction 在 P0 定为纯 SQL fold。

### F9 · major · §2.3 / §2.4 / §2.5 / §3.2 / §5

**权限只是约定。** 「不准直选业务表」和 `required_grants[]` 没有 DB role、SECURITY DEFINER、grant 强制检查、secret 范围、host sandbox。T2/T3 还允许 fs / pty / spawn。

**建议：** 最小 role 模型；seam 端强制 grant；T2/T3 标为 operator-trusted，不要假装不可信沙箱。

### F10 · major · §2.1 / §2.3 / §5 / §7 P2

**workspace / slice / grant 撑不住 yield handoff。** workspace 是「run 私有」，但 yield 后可换 worker。slice/grant 无对象结构、签发、过期、撤销、fork 传播。最小 grant 模型不能推迟到 P2。

**建议：** `workspace_handle` 与租户 `workspace_id` 分开；yield 前 checkpoint 或显式 `WORKSPACE_LOST`。

### F11 · major · 全文

**观测和审计字段不足。** 缺 `run_id` / `step_id` / `attempt_id` / `effect_id` / `plugin_generation` 的关联规范；缺 claim、fence reject、grant denial、catalog 切换的审计。

### F12 · major · §1.2 / §6

**§6 的 13 条没有覆盖 §1.2 的 9 条。** fork 切点**没有对应测试**。没有 canonical oracle、provider mock、driver 互斥、grant、workspace handoff、refresh 原子性、stale worker。

**建议：** 三层 suite——(1) canonical trace/JSON；(2) 持久协议/fault injection；(3) adapter/runtime。全部用 deterministic fake LLM/tool。

### F13 · major · §1.1 / §1.3 / §2.5 / §4

**portable hook 子集未形式化。** 哪些 DSH hook 可翻译、priority 相同如何折、`缺席/超时=pass` 是否适用于授权 hook，都没写。授权类 hook 必须 fail closed。

### F14 · major · §1.2 / §2.5 / §6.1

**canonical JSON 和 render 未定义。** 未规定 RFC 8785 / 键序 / NaN / 二进制 / renderer 超时。四语言很容易在「可移植」上吵出不同答案。

### F15 · major · §1.3 / §3.1 / §3.3 / §6.3

**compat crash/recovery 没有证明能对齐 Native。** DSH `load()` 如何映射到 `seq` / `source_event_seqs` / `ignorable` / dispatch marker，未定义。

### F16 · major · §2.4 / §3.3 / §4 / §6.1

**共享 `tool_catalog` 的作用域不清楚。** 按 session、workspace、driver 还是 cluster 全局？同 identity 不同 locus 谁赢？

### F17 · major · §7

**路线图把协议基础推后，且 P0/P1 自相矛盾。**

1. P0 compat overlay 已依赖 `storage-pg`，`storage-pg` 却在 P1。
2. P0「四缝空壳失败封闭」又要跑通 `assemble → llm.complete → greet`。
3. P2 才接 slice+grant，四缝从 P0 就是安全边界。
4. P1 只绿 greet/inject/reject，合同还要求 fork/取消/compaction/repair/幂等。

**建议：** P0 = 不可回退的协议核，不是功能 demo。

### F18 · major · 开头 / §2.2 / §3.1 / §5 / §7 / §8

**独立设计仍依赖未定义的外部规范。** 「与修正案一致」、zcordis-pgembed、pg_cordis 五件套、PersistenceCoordinator、`tests/contract.ts`、RSI 基因组、slice/grant 都没有版本或在文内重述。「yield 五件套」实际列出八组动词。

### F19 · nit · §1.3 / §2.2 / §2.5 / §7

「不进行为合同」疑似笔误。「一次 LLM + 本步工具」的并行/子 run 边界未形式化。「纯数据 hook 不入队」未说明是否仍受 grant/超时约束。

---

## 必须改的 Top 8（按实现风险）

1. 补齐 lease / fence / effect 协议。
2. 解决「四缝」与实际 effect 的矛盾。
3. 增加规范性 schema 和状态机。
4. 定义 canonical trace 和 canonical JSON。
5. driver 互斥下沉到数据库协议。
6. catalog/handler 的 generation、unload、drain、多 worker 生命周期。
7. 取消、compaction、hook 超时、crash repair 的竞态语义。
8. 可执行的 capability、RLS、runtime role、workspace handoff。

---

## 不要改的好决策

- 「一份行为合同、两份运行时」。
- `session_events` 是历史唯一真相；projection 可重建；workspace 不是历史。
- 会话 `(session_id, seq)` 与 KV `kv_rev` 分离；禁止 `global_rev`。
- `jobs` 是 effect 总线，禁止第二队列当 loop 主人。
- 同一 session 只有一个 driver。
- Native 不仿 Fiber/`next()`；compat 用官方 DSH loop。
- `refresh_plugins()` 全体校验通过才切换目录。
- 先写行为 fixture，再 native，再 compat。
