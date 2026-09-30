# v15 偏差台账（2026-09-29）

从 `docs/designs/v15-jaz-dev.md` §14 抄入。这些行是相对 jaz 参考运行时的有意差别。实现不得把它们修回参考运行时。本文件不是第二份行为合同。

D01–D26 抄自 rev 8。D27–D30 是 rev 9 追加，不重抄前 26 行。D31–D32 是 rev 10 追加。M2 的 `v15/return_hooks/test_return_hooks.py` 已覆盖封闭 DSL helper、ReturnType handler 与 ValidateReturn 注册协议。M2 评审修正后：形状校验对非字符串 `type` 显式 `false`；effect builder 仅显式 `true` 绕过，畸形 counter/ordinal fail-closed；cap 时多个 raise 取 ordinal 最小。

## 14.1 偏差

**V15-D01。** jaz 的一轮回复是 Python 片段。v15 的一轮回复是 PostgreSQL 语句列表，切分器是 `split_sql`。可观察后果：模型必须写 SQL；Python 缩进与 `import` 不会被执行。

**V15-D02。** jaz 的 `bind_invoke` 在同一次求值里阻塞到子树返回。v15 只在语句之间挂起，函数本身抛 `V15_INVOKE_FORM`。可观察后果：子结果要靠下一条已生成语句里的 `jaz.var` 读取；一条语句内部看不到子结果。

**V15-D03。** jaz 向模型展示 `__history__`。v15 的关系是 `jaz.history`，祖先用 `jaz.prior_history(uuid)`，当次请求用 `jaz.request_messages`，提示词禁止 `__history__` 这个名字。可观察后果：按属性访问历史的程序得不到那段关系；祖先历史要按 uuid 读取。

**V15-D04。** jaz 的 `return` / `raise` 是未加引号的语法。v15 的规范形式只有双引号 `jaz."return"` 与 `jaz."raise"`。可观察后果：未加引号的调用在执行前就是 `V15_INVOKE_FORM`。解析探针可以打印解析器的反应，但不得变成第二种规范拼写。

**V15-D05。** jaz 可以有异步工具与 `bind_name` 延续。v15 只有 `jaz.tool(name, args) returns jsonb`，在语句事务内同步结束。handler 是 `v15_tool_<name>` 拥有的 `SECURITY DEFINER` 纯函数，不写 scratch，调用时不 `SET ROLE`、不临时 `GRANT`。`external = true` 为 `V15_EXTERNAL_TOOL`。可观察后果：工具要么在本语句返回 jsonb，要么随保存点消失；没有工具挂起，也没有工具留下的 scratch 行。

**V15-D06。** jaz 的 `ainvoke` 与 `map_invoke` 可以在一轮里并发子调用。v15 一个 invoke 只有一个租约持有者，父在 `suspended` 时不可 claim。可观察后果：扫描结果里子先于重新 `runnable` 的父；不存在同一父迭代的两个 `running` 子语句。

**V15-D07。** jaz 用 Jinja 渲染提示。v15 的渲染器是 `render_prompt.py` 的纯函数，正文以 §6.5 的逐字段落为准。可观察后果：模板文件改动不会改变发给 FakeLLM 的 system 文本。最终 `logical_digest` 由 SQL 计算。消息 id 使用 §3.5 的冻结拼写。

**V15-D08。** jaz 的 hook 可以返回任意 Python 对象并直接改运行时。v15 的返回只解释为 §9.4 的闭集，预留名一律 `V15_INVALID_EFFECT`。不等的消息、`exec_result` 或 `budget` 回滚阶段。不等的 abort 码，或不在 §9.5 可保留闭集内的 abort 码，提交为 `V15_HOOK_ABORT`，不回滚，也不写 `payload.codes`。可观察后果：hook 不能替模型写出助手消息，也不能直接改 `invokes.return_value`。

**V15-D09。** jaz 可以在一次运行中途改配置。v15 在 open 时折叠进 `resolved_config` 后不再重折。可观察后果：open 之后 `UPDATE` profile，已打开 invoke 的 `config_digest` 不变；尚未出生的子 invoke 会看见新的 propagating 层。

**V15-D10。** jaz 参考实现的根深度从 0 起。v15 的根 `depth = 1`。可观察后果：`max_depth = 1` 的根不能再委托；`depth = max` 关闭递归，`depth > max` 才是 `V15_RECURSION_EXCEEDED`。

**V15-D11。** jaz 的子调用沿用父的现场配置对象。v15 的子用父的 `config_scope_id` 按子深度重新折叠，不继承 `local_layer_id`，也不复制父的 `resolved_config`。可观察后果：父子的 `config_digest` 可以不同；父的 local 替换对子不可见。

**V15-D12。** jaz 可以把 hook 的可变状态交给子。v15 复制父 invoke 上已经冻结的 propagating 行的 `hook_def_id` 与 `config`，`state` 置为 `{}`，不复制 local 行，也不按子 open 当时的 `extra_hooks` 再装一份。`ordinal` 在子的 baseline 之后重新连续编号。可观察后果：父的 `budget_forcing:<ordinal>` 计数不会出现在子的 `hook_counters` 里。

**V15-D13。** jaz 在一次 Python 求值里的赋值，异常之后仍可能留在进程里。v15 一条语句一个保存点，失败则该语句的 binding 与 `capture` 消失，已提交的前序语句保留。可观察后果：失败语句的 `jaz.assign` 在下一轮 `jaz.var` 里看不见。

**V15-D14。** jaz 把提供方失败当成异常再重试。v15 把每一次尝试写成 `llm_attempts` 行：未开始而过期是 `failed`，已开始而过期是 `unknown`，成功是 `settled`。`v15_reclaim_expired()` 无参数，不插入 attempt，也不调用阶段函数；没有存活 `leased` attempt 的过期 invoke 租约在同一次调用里收回。可观察后果：迟到响应不能补写转录。`retry` 事件的 `new_attempt_id` 为 JSON `null`。新行只在之后的 `v15_begin_llm`。

**V15-D15。** jaz 的预算耗尽通常停在当前调用。v15 在池盖不住预留或金额超限时 `fatal = true`，同一事务中止该 invoke、祖先，以及这些行中仍非终态的后代。预留失败时，本轮还没写下的 hook 效应不写。可观察后果：祖先不会停在 `suspended` 等待一个已经 `aborted` 的子。

**V15-D16。** jaz 的迭代与递归上限多来自可选配置。v15 强制恰好一行 `governance_manifest`，调用方只能收紧。可观察后果：没有清单行时 `v15_open_invoke` 抛 `V15_GOVERNANCE_MISSING`，不会先去租 LLM。invoke 上的摘要是有效上限，不是单例摘要的拷贝。

**V15-D17。** jaz 常以名字约定暴露工具。v15 要求 `kind = tool` 的 binding 与 `tool_grants` 行同时存在。可观察后果：只复制其中一项时 `jaz.tool` 抛 `V15_TOOL_UNAUTHORIZED`，invoke 不因此终态。

**V15-D18。** jaz 可以有独立的 span 对象。v15 的 span 只是 `invoke_events` 的行，没有 `programs`、`turns`、`spans`、`phases` 表。可观察后果：轨迹查询就是按 `seq` 读事件。父在 `suspended` 期间 `repl_exec` 没有 `exit`。`outcome` 只用小写的 `completed`、`aborted`、`failed`。

**V15-D19。** jaz 的截断有时落在保存下来的观测上。v15 只截断送进 base 的观测文本；`llm_messages` 与 `repl_history.repl_output` 保存全文。失败的 continue 里，这份全文是 capture 与 `[v15 exception …]` 块拼成的观测。可观察后果：`jaz.history` 的 `repl_output` 可以长于模型在下一轮 request 里看见的那一截。

**V15-D20。** jaz 的词法是 Python。v15 的词法是 §6.1：嵌套块注释、不按栈嵌套的 dollar-quote。`DO` 不是一条可执行语句，首记号 `DO` 在执行前失败 `V15_DIALECT`。`ALTER TABLE` 一律 `V15_DDL`，模型要改表就先 `DROP` 再 `CREATE`。可观察后果：`DO $$ … $$;` 与 `ALTER TABLE` 都变成结算时的失败行，函数体与改表都不运行。`WITH RECURSIVE` 仍是一条可执行的 `plain`。

**V15-D21。** jaz 的 hook 可以替换模型响应或子调用结果。v15 拒绝 `supply_llm_response`、`supply_invoke_result`、`modify_invoke_result`、`supply_exec_result`、`modify_llm_response`。可观察后果：这些名字使阶段事务回滚，invoke 状态不变。非 baseline handler 抛出的异常才只留审计。

**V15-D22。** `jaz.history` 与 `jaz.request_messages` 的 `security_barrier` 阻止用户条件被推到视图之下。`EXPLAIN` 不是隔离边界：隔离 gate 必须再开一个 invoke 并断言行集，不得用 `EXPLAIN` 文本当证据。可观察后果：能解释视图的角色仍可能看见视图定义；看不见另一个 invoke 的已提交历史行或请求行。

**V15-D23。** local 的 `recursion_limit` 允许作为收紧安装，但不复制给子。可观察后果：父在 `depth = local.max` 时不能再 `bind_invoke`。子不受父的 local 上限约束。

**V15-D24。** 实参求值不能把本事务改成 `READ ONLY`：`v15_prepare_statement` 已经写过控制行。v15 不引入 `V15_INVOKE_EXPR_WRITE`。求值只授予 scratch 的 `USAGE`，不授予 `CREATE`，也不做任何表级 `GRANT`。表的属主仍是 `v15_repl`，所以属主权挡不住写自己的表。背书是 `arg_sql` 的写记号、会写的 `jaz.*`，以及 `pg_stat_xact_user_tables` 上的写入，全部 `V15_INVOKE_FORM`。可观察后果：实参里的 `INSERT` 失败，并且没有子 invoke 行。

**V15-D25。** jaz 有完整的 Python 控制流。v15 的一轮是直线语句列表。跨 invoke 的递归只走 `bind_invoke`。一条语句内部的迭代只走 `WITH RECURSIVE`。`DO` 被拒绝，因为在 `session_user = v15_worker` 的连接里，顶层 `RESET ROLE` 会从 `v15_repl` 回到 worker。可观察后果：模型写 `DO` 得到 `V15_DIALECT`。`DO` 若要重新进入语言，必须换成 `session_user` 本身无权的模型连接；那是后续版本。

**V15-D26。** jaz 允许 hook 在 exit 上 abort，从而改写已经决定的 outcome。v15 的 `invoke/exit`、`llm_query/exit` 与 `repl_exec/exit` 只允许 `blackboard_write`。outcome 行在调用阶段函数之前写入。exit 上的 abort 是 `V15_INVALID_EFFECT`，整笔回滚。可观察后果：exit hook 不能把 `completed` 改成 `failed`；它只能写下一次 phase 才看得见的黑板。

**V15-D27。** jaz 会发送 `temperature`。v15 的 DeepSeek allowlist 模型不上送 `temperature` / `top_p`。值仍留在 `resolved_config`。实现不得把它们补进线协议来对齐 jaz。

**V15-D28。** 供应商无幂等。unknown 之后的新 attempt 可能在供应商侧重复计费。`cost_used` 只含已 settle 的自算成本，可以低于发票，也可以因节假日按高峰估算而高于发票。`cost_used` 是估算值，`cost_limit` 是治理闸门，不是对账单。

**V15-D29。** `reasoning_content` 不是助手程序，不进 `llm_messages.content`。思考文本不得被拼进 `content`。审计只可带 `reasoning_chars`，不带正文。

**V15-D30。** 高峰只按上海时区周一至周五的两个半开窗口 `[09:00, 12:00)` 与 `[14:00, 18:00)` 估算，不含法定节假日。假日若落在周一至周五，按高峰计价，方向是多报，不少报。实现不得为了贴近发票而补节假日日历。

**V15-D31。** jaz 的 ReturnType / ValidateReturn 用 Python 类型与异常对象，并在 InvokeComplete 再查一次。v15 用封闭 jsonb 类型规格与注册式 SQL handler，只在 `repl_exec/complete` 校验。可恢复拒绝是 return→continue 加持久消息；耗尽后是 return→raise / `P1540`。`P1540` 不是 abort 保留码。没有第二次谓词调用。validator 直接 `RAISE` 仍走异常隔离，不算校验拒绝。

**V15-D32。** spec 键名限制为 `^[A-Za-z_][A-Za-z0-9_]{0,62}$`，嵌套深度 ≤ 8。`jsonb` 的 `number` 不区分整数与浮点。enum 通过性按数值相等，展示按 `elem::text`。对象渲染的 required 按数组序，可选键按 UTF-8 字节序，项之间是 `, `。

D2 轨迹回放不启用 `supply_llm_response`，摘要复用 `llm_requests.logical_digest`。

## 14.2 故意保留

下列行为是论文性质或本版合同的目标，不是偏差。gate 必须证明它们仍然成立：

- 父迭代的下一条已生成语句用 `jaz.var` 读到子结果，父为此不再次调用 LLM。
- 模型能读到显式输入、scope、本 invoke 已结束的历史、按祖先 id 授予的祖先历史，以及当前迭代已结算 attempt 的冻结请求（`jaz.request_messages`，含 hook 消息）。
- 尾委托就是 §6.5 的两句规范语句，中间没有另一次父 LLM。`recursion_available = false` 时，提示与 `context_window_warning` 都不写出 `bind_invoke`。
- 同一迭代既打印又 `return` 或 `raise`，得到 `V15_PRINT_AND_RETURN`，invoke 不因此终态。
- 四项治理上限始终存在，且只能收紧。
- scope 按值复制，`var` 与显式 input 不向子传播。
- `unknown` attempt 不是成功，迟到响应不进转录。
- 五个可选 hook 的可观察意图：更紧的迭代与递归、池预留、拒绝过早的 `return`、以及按 `recursion_available` 二选一的瞬态窗口警告。

stage 1 只装了清单单例与四项上限的检查。stage 4 不新增偏差行。`test_protocol.py` 覆盖 D01 / D04 / D07 / D20 / D25 的切分、分类与渲染返回值，不结算语句。`recursion_available = false` 时 system 正文不写出 `bind_invoke`；`context_window_warning` 的两套正文仍是 stage 9。保留清单的其余行为要等后续 stage 的 gate。

stage 5 不新增偏差行。`test_repl.py` 覆盖 D05 的同步工具调用、D13 的保存点回滚，以及 D24 里「prepare 不把事务改成只读、bind 只授 `USAGE`」这一截。`jaz.bind_invoke` 实执行仍是 `V15_INVOKE_FORM`，不产子。级联删除探针在 PostgreSQL 18.4 上通过，终态删除不改成函数内 `SET ROLE`。后继 `skipped` 仍是 finish 的事，不是本 stage 的偏差。

stage 8 不新增偏差行。`test_tree.py` 覆盖保留清单里的同迭代 `jaz.var`、父不再次 LLM、scope 按值复制、以及 D02 / D06 / D10 / D11 / D15 的可观察后果。`context_window_warning` 的两套正文仍是 stage 9。

stage 9 不新增偏差行，也不把任何一行修回 jaz。`test_govern.py` 覆盖 D08 的效应闭集与 `V15_HOOK_ABORT`、D15 的预留失败不写效应、D21 的预留名回滚与非 baseline 异常隔离、D26 的 exit 不能 abort。五个可选 hook 的可观察意图也在这一 gate：更紧的迭代上限、池预留恰好一次、`budget_forcing:<ordinal>:<n>`、以及按 `recursion_available` 二选一的瞬态窗口警告。

stage 10 追加 D27–D30，不把任何一行修回 jaz。D01–D26 的权威正文仍在规格 §14；本文件不重抄那 26 行当第二合同。M1 的 provider gate 证明的是 SQL 转移与 hook 归一，不证明 D27 的线协议或 D29 的思考文本。

## Demo

尾委托 demo 不新增 V15-D 行。它不修改渲染器、切分器、worker 或 provider。真实调用的计价、无幂等与思考文本仍由 D27–D30 覆盖。更深链 demo 不新增 V15-D，不修改渲染器、切分器、worker、provider、namespace。C1 同迭代扇出不新增 V15-D，不修改渲染器、切分器、worker、provider、namespace。

驱动源码已入库（`demo_v15/` 下 8 个文件，force-add）。`reports/` 仍不入库。这一笔不新增 V15-D 行。


## Merge verification（2026-09-30）

v15 线并入 main 不新增 V15-D、不改 D01–D30 语义；只搬运已冻结历史。八个 demo 源文件仍 tracked，reports/pyc/.env 仍不入库；demo 未升级为 gate；十道 gate 在合并树上全量重跑全绿。
