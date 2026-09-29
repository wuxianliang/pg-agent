# v15 设计文档 rev 4 修订裁定（R-C 系列）

来源：rev 3 复审（oracle 组 `91693890-A7A5-44A3-AB04-B3F59D2BD919`，双轨）。本文是主 agent 对全部剩余 findings 的逐条裁决，binding。应用对象：`docs/designs/v15-jaz-dev.md`，修订后标 **设计修订 rev 4**，修订说明一行引用本文。

---

**R-C1（双轨 P0，§5.1/§3.15/§2）。** `GRANT EXECUTE ON FUNCTION v15.jaz_<name>(...) TO v15_repl`（仅此一个被授权者；`v15_worker` 不获此授权）。每个 definer 体仍独立断言 `current_user = 'v15_repl'` 与有效 `exec_context`。删除「因此由 `v15_owner` 调用 definer 体」一类措辞。同样适用于 `v15.jaz_tool`、`v15.jaz_prior_history`。§2 矩阵的 EXECUTE 行同步。

**R-C2（codex P0，§4.3/§3.5/§9.6）。** 种子消息的 `msg_seq` 0（`seed:system`）与 1（`seed:inputs`，存在时）**预留**：open 事务先解析 `invoke/enter` 效应，持久 hook 消息自 `max(seq)+1`（此时为 2）分配；种子正文在效应解析后渲染写入预留位（enter 的 `input_adds` 因此进入 inputs 种子）。dispatcher 分配 seq 一律 `max(seq)+1`，永不写 0/1。

**R-C3（grok P1，§4.7/§4.12）。** bind 实参 `SELECT (<arg_sql>)` 的**任何**错误（四个 V15 码与 PostgreSQL 原生 sqlstate 如 `22012`/`42501`/`42883` 一视同仁）→ `ROLLBACK TO SAVEPOINT` + `v15_complete_statement(..., 'failed', error)` + `COMMIT`。不得留下 `pending` 的 bind 语句无限重试。

**R-C4（grok P1，§9.1/§4.5）。** `llm_query/exit` 的 `io.attempt_id` 在未产生 attempt 即关 span 的路径（enter/send abort、预算 abort、I/O 耗尽）允许 JSON `null`。

**R-C5（grok P1，§4.5.1/§4.6.1）。** 迭代上限、I/O 耗尽、phase abort 等提交类终态关闭统一用 §4.3 的关闭形状：iteration `done` / `result_kind = continue`（写 `repl_history` 行）→ exit 事件 → exit phase（仅 blackboard）→ §4.8 送达。

**R-C6（grok P1，§4.5.1 步骤 6/§9.6）。** `v15_on_phase` 永不自行把 invoke 置终态：0 行预留时它只返回 `action = abort`（`fatal`、`V15_BUDGET_EXHAUSTED`）；终态行与 §4.8 由 `v15_begin_llm` 写。

**R-C7（grok P1，§11.3）。** settle/refund 的 `UPDATE` 加守卫 `AND calls_reserved >= <reserved_calls> AND cost_reserved >= <reserved_cost>`（差额下穿走 0 行 → `V15_INVALID_TRANSITION`，而非撞 CHECK）。

**R-C8（grok P1，§4.10）。** 语句修理分支「`running` 且子已终态」：先置父 bind-wait（`suspended`、清租约、fence 不动），再在同事务做 §4.8 送达；不得二次 bump fence。

**R-C9（grok P1，§4.1）。** 有序锁清单加入 `v15_begin_exec`（其 abort 路径写父）。

**R-C10（grok P1，§0.15）。** 措辞改为：phase 路径的预算预留写者是 dispatcher（`v15_dispatch_apply`）；重试路径与 stage 6–8 桩路径由 `v15_begin_llm` 执行同一条单次 `UPDATE`；LLM 路径的 `llm_messages` 只由 `v15_dispatch_apply` 写入。

**R-C11（grok partial，§9.6/§10.2）。** forcing 计数：dispatcher 从被接受的持久消息 id `budget_forcing:<ordinal>:<n>` 解析 `<ordinal>`，对 `budget_forcing:<ordinal>` 键加一，每个被接受效应一次。

**R-C12（codex P1，§9.5）。** hook 可保留的 abort 码集合闭合为 `{V15_IO_EXHAUSTED, V15_BUDGET_EXHAUSTED, V15_RECURSION_EXCEEDED, V15_ITERATION_EXCEEDED}`；hook 返回的其他任何码一律归一为 `V15_HOOK_ABORT`（`P1538` 已存在）。

**R-C13（codex P1，§6.4/§17）。** 事件触发器命令 tag 用 `TRUNCATE TABLE`（分类器首记号仍是 `TRUNCATE`）。

**R-C14（codex P1，§2/§6.4）。** `GRANT EXECUTE ON FUNCTION v15_current_scratch_schema() TO v15_repl`（仅），写入 §2 与 §6.4。

**R-C15（codex P1，§6.2/§4.7）。** bind 实参分类在字符串/注释/dollar-quote 之外的记号流中拒绝 `nextval(`/`setval(`/`currval(` → `V15_INVOKE_FORM`（序列变异防护；写防护仍是 `pg_stat_xact_user_tables` + 仅 USAGE 无 CREATE）。

**R-C16（codex P1，§9.6）。** 效应落地前，持久 `add_messages` 的 id 若已存在于 `llm_messages` → `V15_VALUE_INVALID`（phase 回滚），不触发原生 `23505`。

**R-C17（codex P1，§3 总则/§9.6/§10.2/§4.10）。** revision 规则全覆盖：blackboard UPSERT、`hook_counters`、`llm_attempts`、`llm_requests`、`iterations`、`statements`、§4.10 的全部修理 `UPDATE`，一律 `revision = revision + 1`。

**R-C18（codex P1，§3.1）。** `invokes.pool_id uuid NULL REFERENCES budget_pools(pool_id)`。

---

应用要求：保持既有结构/文风；§13 仍为 38 行 `P1501`–`P1538` 连续无空号（本轮无新码、无删码）；全文不得残留 oracle 元信息块；完成后自查：(a) 每条 R-C 在正文中可定位，(b) §13 完整性，(c) 无重复标题。

> **取代说明（rev 4 终审后追加）**：R-C1a/R-C10a/R-C2a 取代上文 R-C1/R-C10/R-C2 中的原句；冲突时以补充裁定与 `docs/designs/v15-jaz-dev.md` rev 4+ 正文为准。
