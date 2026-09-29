# v15 设计文档 rev 5 修订裁定（R-D 系列）

来源：rev 4 新鲜视角终审（oracle 组 `6E014473-9DDE-4584-952E-926B06D0CE13`，grok + codex 双轨）。主 agent 逐条裁决，binding。应用后标 **设计修订 rev 5**，修订说明追加一行引用本文。

---

**R-D1（grok P0-1，§3.5/§4.3/§9.6）。** `invoke/enter` 的持久 hook 消息不再由 `v15_on_phase` 插入：phase 函数对 `invoke/enter` 只应用 input/recursion/blackboard 效应并**返回** `messages`（不写 `llm_messages`）。`v15_open_invoke` 与 `v15_suspend_for_child` 的子 open 路径随后：插 `seed:system`（seq 0，正文 `p_system`）→ 若效应后仍存在 `show_in_prompt` 输入则插 `seed:inputs`（seq 1）→ 返回的持久消息按 `max(seq)+1` 插入。§3.5 注明这是 enter 路径上唯一的非 dispatcher 写者；LLM 路径的 hook 消息仍只由 `v15_on_phase` 在预留之后写入。

**R-D2（grok P0-2，§2/§4.1）。** `GRANT EXECUTE ON FUNCTION v15_on_phase(...), v15_assert_manifest(), v15_assert_invoke_manifest(uuid)` **to `v15_owner`**（无 GRANT OPTION）——转移函数以 definer 身份（`v15_owner`）嵌套调用它们，无此授权即 `42501`。`v15_span_open` 另授 `v15_worker`（worker 循环直接调用）。`v15_on_phase` 与两个 assert 不授其他角色。

**R-D3（grok P1-3，§0.8/§1.2/§4.8）。** `runnable` 子只**建立** §4.8 的结构前置（父 bind-wait）；同事务送达只发生在子已 `completed`/`failed`/`aborted` 时。§4.7「子出生即终态」才直接走 §4.8。澄清 §0.8 与 §1.2 的对应措辞。

**R-D4（grok P1-4，§4.12）。** 步骤 6 的 finish 前置：仅当本 worker 仍持有租约、迭代 `executing`、`repl_exec` span 打开时调用 `v15_finish_exec`；若 suspend 事务已收束本迭代（或 invoke 已非 `leased`），回到步骤 1。

**R-D5（grok P1-5，§3.4/§4.5.1/§6.5/§7.2）。** 最终请求的**消息 id 与顺序**取自存储的 `llm_messages`；**system 正文**每次由 `v15_begin_llm` 用提交后的 `recursion_available` 与 bindings 重渲染进 base 元素 `seed:system`（可与存储种子不同）；inputs 正文跟随当前 `kind = input` 行（仅截断）。SQL 校验 id/kind/顺序并接受 system 正文差异。`p_system`/`p_child_system` 是 open 时的转录种子，open 渲染用 `depth < effective max_depth`；其后 enter 的 `disable_recursion` 不改写种子。

**R-D6（grok P1-6，§4.3/§4.1/§9.1）。** 每个写 `exit` 事件的关闭路径（含深度守卫失败与 `invoke/enter` abort）都在事件之后调用对应 exit phase（`io = {outcome}`，outcome 按 `fatal` 取 `failed`/`aborted`；handler 仅可写黑板）。

**R-D7（grok P1-7，§13）。** 四个码（`V15_RECURSION_DISABLED`、`V15_SCOPE_CONFLICT`、`V15_INVOKE_FORM`、`V15_VALUE_INVALID`）在 §13 行内追加注记：「由 `v15_suspend_for_child` 抛出并经 §4.7 捕获 → 语句失败（提交 `failed` 行）」；其余场合维持原分类。

**R-D8（grok P1-8，§6.4/§17）。** `v15_scratch_guard` 创建为 `SECURITY INVOKER SET search_path = pg_catalog`，助手调用写全限定 `v15.v15_current_scratch_schema()`。

**R-D9（grok P1-9，§15）。** `setup_db.py` 在装载前创建 NOLOGIN 角色 `v15_hook_governance_iterations|depth|io|statement`（stage 1 前）；五个可选 hook 的 `v15_hook_*` 角色在 `v15_govern.sql` 前（stage 9 的 setup）；测试自建 `v15_tool_<name>`，均在 `SQL_LOAD_ORDER` 之外。

**R-D10（codex P0-1，§15/§2）。** 库名匹配改 `starts_with(datname, 'agent_v15_')`（或显式转义下划线）；全文排查 `LIKE 'agent_v15_%'`。

**R-D11（codex P0-2，§6.2 第 4 步）。** 事务控制拒绝表补全同义词：`END`、`ABORT`、`RELEASE`（与既有 `BEGIN`/`COMMIT`/`ROLLBACK`/`SAVEPOINT`/`START` 并列）→ `V15_DIALECT`。

**R-D12（codex P0-3，§9.2/§5.3）。** handler/工具调用文本改为由 oid 解析出 `quote_ident(namespace) || '.' || quote_ident(proname) || '($1::jsonb)'`（`regprocedure::text` 自带参数签名，不能直接拼 `($1)`）。hook 与工具同一机制。

**R-D13（codex P1-1，§9.1/§9.6/§4.5.1）。** send 包络加 dispatcher 专用 `enter_effect` 载体键：`v15_begin_llm` 把 enter 的返回作为 send 调用 `io.enter_effect` 传入；dispatcher 在 send handler 之前应用它（enter 的输入/黑板/递归效果），并把它排除在 handler 快照之外。§9.1 的 send 必填键表加 `enter_effect`（enter 无效应时为 `null`）。

**R-D14（codex P1-2，§4.5.3/§4.9/§4.12）。** 有序首错语义：以**下标最小**的 `failed` 语句为本迭代错误；其后的 preclassified `failed` 行在到达执行边界或更早的 `return`/`raise` 完成时改记 `skipped`；§4.12 的停止判定只看「当前执行边界处」的错误，不看未来 preclassified 失败。§4.9 的 continue 前置相应改写。

**R-D15（codex P1-3，§4.6.2/§4.7/§5.3）。** 终端与 bind 实参求值要求**恰好一行**：`SELECT (<expr>)` 零行或多行 → 语句失败 `V15_VALUE_INVALID`。`kind = return/raise` 的语句标 `done` 前必须验证 `invokes.return_value`/`invokes.error` 已写入（SRF 参数如 `jsonb_array_elements('[]')` 导致函数未执行时不得标 done，按失败收束）。

**R-D16（codex P1-4，§6.2/§6.4/§0.18/§17）。** `TRUNCATE` 从方言中移除（`TRUNCATE` 不触发 `ddl_command_end`，事件触发器无法执法）→ 分类器 `V15_DIALECT`；删除 allowlist 中的 TRUNCATE 与相关 gate；模型用 `DELETE` 清空。`DROP TABLE/INDEX/VIEW` 的对象身份检查改走 `sql_drop` 事件触发器 + `pg_event_trigger_dropped_objects()`（`ddl_command_end` 不含 drop 的对象身份）。

**R-D17（codex P1-5，§4.5.4/§11.3）。** 退款算术修正：终态退款从 `calls_reserved`/`cost_reserved` **减去**存储的预留量（usage 不动），配既有下溢守卫。

**R-D18（codex P1-6，§9.6/§10.2/§4.9）。** forcing 计数更新归属 `v15_finish_exec`：接受 return→continue 改写时，对每个被接受的 `budget_forcing:<ordinal>:<n>` 消息把 `budget_forcing:<ordinal>` 加一（每消息一次）。dispatcher 不在 complete 中改计数。

**R-D19（codex P1-7，§4.7/§13）。** suspend 捕获集加入 `V15_GOVERNANCE_RAISE`（子 open 的收紧校验失败按语句失败收束，不得留 `pending` 无限重试）。

**R-D20（codex P1-8，§9.5/§13）。** 保留码的 `fatal` 位归一：hook 返回保留码时，`fatal` 强制取 §13 该码的规范 fatal 值（不匹配的返回不报错、直接归一）。

**R-D21（codex P1-9，§4.6.2/§4.7/§17）。** 取消策略统一：语句被取消（`57014` 等）→ worker 丢弃该连接（不复用），在新事务 `v15_fail_statement` 记 `failed`；超时归一为 `V15_STATEMENT_TIMEOUT`，其余取消保留原生 sqlstate。bind 路径同 policy。

**R-D22（P2 批）。** (a) `\u0000` 是**六**个字符（`\`,`u`,`0`,`0`,`0`,`0`），全文修正长度表述，gate 断言六个字面字符。(b) 删除文末残留的 `Error [provider_error]...` 行。(c) §4.2 补 `v15_next_runnable() returns setof uuid`。(d) `statements.error_sqlstate` 定义为恒等于 `error->>'sqlstate'`（或删列，二选一，取定义）。(e) `bindings.tool_id` 加 `REFERENCES tool_catalog(tool_id)`。(f) §6.2 序列函数拒绝匹配「`(` 前的标识符」，覆盖 `pg_catalog.nextval(` 等带限定形式。(g) §9 全文统一只说 `v15_on_phase`（清除「落地例程」等暗示第二函数的措辞）。(h) §5.4/§3.15：`jaz.history` 与 `jaz.request_messages` 在 exec_context 缺失时同样抛 `V15_INVALID_TRANSITION`；§15 stage 2 gate 注明断言对象。(i) `docs/references/v15-rev4-rulings.md` 追加一行：R-C1a/R-C10a/R-C2a 取代原 R-C1/R-C10/R-C2 对应句子。

---

自查同前：§13 仍 38 行 `P1501`–`P1538` 连续（无新码）；单标题；无 oracle 元信息；文末无工具输出残留。
