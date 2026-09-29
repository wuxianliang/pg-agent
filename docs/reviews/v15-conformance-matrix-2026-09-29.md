# v15 覆盖矩阵（2026-09-29）

记 stage 1–10 gate 已经断言的条目。行为以 `docs/designs/v15-jaz-dev.md` rev 9 为准。矩阵不是第二份合同。

完整 `SQL_LOAD_ORDER`：

1. `v15/schema/v15_schema.sql`
2. `v15/namespace/v15_namespace.sql`
3. `v15/config/v15_config.sql`
4. `v15/protocol/v15_protocol.sql`
5. `v15/repl/v15_repl.sql`
6. `v15/io/v15_io.sql`
7. `v15/loop/v15_loop.sql`
8. `v15/tree/v15_tree.sql`
9. `v15/govern/v15_govern.sql`
10. `v15/provider/v15_provider.sql`

合运行时是这十个文件都加载之后。`agent_v15_provider` 是这个库。`agent_v15_govern` 与更早的 `agent_v15_*` 库是前缀 gate，不是合运行时。

状态来自实跑：`uv run python v15/govern/test_govern.py` 退出码 0。随后复跑 stage 1–8 的 gate，退出码都是 0。

| # | 条文 | 状态 | 测试落点 | 断言的行为 |
|---|---|---|---|---|
| 1 | §0.3 `invoke_events` 只追加，同一 `invoke_id` 的 `seq` 连续 | ✅ | `v15/schema/test_schema.py` | `UPDATE`/`DELETE` 被拒绝；跳号插入被拒绝；`seq = 0` 可写入 |
| 2 | §0.13 清单恰好一行；四项上限为 `>= 1` 的整数；`v15_assert_manifest()` 是真检查 | ✅ | 同上 | 种子行的摘要等于四列重算；摘要被改写后抛 `P1504`；删行后同样抛 `P1504`；第二行与 `< 1` 不能留下 |
| 3 | §0.14 `v15_repl` 无内核 DML，无内核转移 `EXECUTE` | ✅ | 同上 | worker 直接 `INSERT` 与调用 `v15_on_phase` 被拒绝；`SET ROLE v15_repl` 后写 `exec_context` 被拒绝 |
| 4 | §0.19 自定义码能 `RAISE`，gate 按 `sqlstate` 分类 | ✅ | 同上 | `P1504`、`P1512`、`P1521`、`P1522`、`P1532` 按 `pgcode` 断言。本 stage 不覆盖 §13 其余码 |
| 5 | §0.20 身份：worker 成员关系；definer 体内不切换角色；模型语句 `current_user` 是 `v15_repl` | ✅ | 同上 | `v15_worker` 对 `v15_repl` 为 `INHERIT FALSE, SET TRUE`；`v15_owner` 不是成员；`SECURITY DEFINER` 体不含 `SET ROLE`；`SET ROLE` 后 `current_user` 是 `v15_repl` 且 `session_user` 仍是 `v15_worker`；`session_user = v15_repl` 时不能 `SET ROLE v15_worker` |
| 6 | §0.24 span 只记在 `invoke_events`，不另建 span 表 | ✅ | 同上 | 库内没有 `programs` / `turns` / `spans` / `phases`；`v15_span_open` 在有 `enter` 无后继 `exit` 时为真，写入 `exit` 后为假 |
| 7 | §0.26 scratch 隔离与事件触发器 | ✅ | 同上 | `v15_repl` 无 `TEMP`；guard 是 `SECURITY INVOKER` 且 `search_path = pg_catalog`，schema 名来自全限定 `v15.v15_current_scratch_schema()`；scratch 内 `CREATE TABLE` 成功且属主为 `v15_repl`；`public`/`outside` 的 `CREATE TABLE`、`CREATE FUNCTION`、`ALTER TABLE`，以及越界 `DROP`，抛 `P1512` |
| 8 | §0.28 `v15_on_phase` 桩与 `v15_assert_manifest()` 真检查 | ✅ | 同上 | 桩返回恰好 `contract = 1` 且 `action = proceed`；断言函数在清单损坏时抛 `P1504`，不是空成功 |
| 9 | §0.17 历史隔离与祖先范围 | ✅ | `v15/namespace/test_namespace.py` | `jaz.history` 只出当前 `exec_context` 的 invoke；另一 invoke 的行不出现，无历史的 invoke 行集为空；无本后端 `exec_context` 抛 `P1523`。`jaz.prior_history` 对自身与祖先返回已结束历史，无关 id、后代与 NULL 抛 `P1510`，无历史行时为空表 |
| 10 | §0.20 / §5.1 包装与 definer 身份 | ✅ | 同上 | 非 `v15_repl` 调用包装抛 `P1522`；未 `SET ROLE` 的 worker 没有 `EXECUTE`（`42501`）；definer 直接调用不抛 `P1522`，无 `exec_context` 或语句非 `running` 抛 `P1523`。包装与 definer 的 `EXECUTE` 只在 `v15_repl` |
| 11 | §0.22 打印与结束互斥 | ✅ | 同上 | `kind = return` 且 `capture <> ''` 时 `jaz."return"` 抛 `P1515`，不写 `return_value`，invoke 仍是 `runnable`。`kind = raise` 且 capture 非空时 `jaz."raise"` 同样抛 `P1515`，不写 `error` |
| 12 | §0.29 外部工具不调用 handler | ✅ | 同上 | `tool_catalog.external = true` 且 binding 与 grant 都在时，`jaz.tool` 抛 `P1517`，handler 未被调用。合取失败抛 `P1507` |
| 13 | §5.2 保留字与名字 | ✅ | 同上 | 保留字、非法文法、SQL NULL 抛 `P1524`。`Return` 不是保留字，可以 `assign` |
| 14 | §5.3 `var` / `assign` / 控制函数 | ✅ | 同上 | `var` 读 `input` / `scope` / `var`，拒 `tool` 与缺失名，不改 `revision`。`assign` 新名字插入 `kind = var`、`revision = 0`；已有 `var` 则 `revision` 加 1 且 `show_in_prompt` 不变；已有 `input` / `scope` / `tool` 抛 `P1524` 且 kind 不变。`jaz."return"` / `jaz."raise"` 只在匹配的 `kind` 上写入且不改 `status`；kind 不匹配与 `bind_invoke` 抛 `P1503`，不插入子 invoke。`print` 按调用顺序拼接 `capture` |
| 15 | §5.4 `jaz.request_messages` | ✅ | 同上 | 列是 `seq` / `role` / `kind` / `content`。行来自当前 invoke 与迭代上 `n` 最大且 `settled` 的 `request.messages`；无已结算 attempt、其他迭代、其他 invoke 都是空表。无 `exec_context` 抛 `P1523` |
| 16 | §0.16 / §8.2 折叠后冻结 | ✅ | `v15/config/test_config.py` | 四层各自生效且后者胜；protocol-only 层不动 llm；后写 llm 整体替换。depth=2 的 partial 不影响 depth=1。子路径不收 local。改 profile 后新的 resolve 变，已写入的 invoke 行 `config_digest` 不变，且仍等于 `md5(resolved_config::text)` |
| 17 | §8.1 列 `IS NOT NULL` 与 partial `jsonb_exists` | ✅ | 同上 | SQL NULL 列不替换；JSON `null` 列与 partial 里键存在而值为 null 都抛 `P1524`；partial 缺键不替换。未选中的非法 depth 键不参与本次折叠 |
| 18 | §8.2 / §8.3 / §8.6 配置错误码 | ✅ | 同上 | depth 层写组件列或 `extra_hooks`、partial 再含 `depth_map` 抛 `P1530`。local 指向 scope 层或 depth 层、子路径传入 local 抛 `P1531`。partial 或 extra_hooks 含 `baseline_hooks` 抛 `P1532` |
| 19 | §8.5 / §11.2 两枚清单摘要与收紧 | ✅ | 同上 | `p_ceilings` 为空时有效摘要等于单例行摘要；收紧后不等，且不抄单例摘要。子路径与当时清单逐项取 min，不大于父也不大于清单。放宽抛 `P1505`；非整数与 `< 1` 抛 `P1524` |

| 20 | §0.18 / §6.1 切分 | ✅ | `v15/protocol/test_protocol.py` | 嵌套块注释、字符串 / `E''` / `U&''` / 标识符引号 / 行注释里的分号不切开；dollar-quote 异 tag 是文本、同 tag 闭合且不按栈嵌套；空语句消去、首尾空白去掉；未闭合不产生部分列表，`kind = plain`、`reject_code = V15_DIALECT`、`sql` 为原文 |
| 21 | §0.18 / §6.1 NUL | ✅ | 同上 | 每个 NUL 换成六字符 `\u0000`，`reject_code = V15_VALUE_INVALID`，不再另报未闭合。本 stage 不调用 `v15_settle_llm` |
| 22 | §0.18 / §6.2 五式与控制名 | ✅ | 同上 | 五条规范形式识别出对应 `kind`，`arg_sql` 为原文区间。未加引号 `return` / `raise` 为 `V15_INVOKE_FORM`。带引号必须正好小写。字符串、注释、dollar-quote 内的控制名不是拒绝。非字面量 ident、保留字、超长名字为 `V15_INVOKE_FORM`。`bind_invoke` 的 `arg_sql` 在引号外出现写记号或 `nextval` / `setval` / `currval`（含 `pg_catalog.`）为 `V15_INVOKE_FORM` |
| 23 | §0.18 / §6.2 方言与 DDL | ✅ | 同上 | `DO`（含 `DO $$ … $$`）为 `V15_DIALECT`。`ALTER TABLE` 加列、`CREATE FUNCTION` 等 §6.2 第 3/6 步为 `V15_DDL`。`TRUNCATE`、`END` / `ABORT` / `RELEASE` 及其余实用语句为 `V15_DIALECT`。scratch 白名单与 `WITH RECURSIVE` 为 `plain`、空拒绝码。本 stage 不在 scratch 里执行它们 |
| 24 | §6.3 超时 pragma | ✅ | 同上 | 只认第一行整行 `-- timeout:` 加有限正十进制秒。`floor(秒 * 1000) >= 1` 才合法。配不上或 floor 为 0 是 `V15_VALUE_INVALID`。第二行及以后是普通注释。存放文本保留 pragma 行 |
| 25 | §6.5 / §0.25 渲染 | ✅ | 同上 | 冻结段落与规格代码块逐字相同，含 `jaz.history` 措辞。`recursion_available = false` 时正文不出现 `bind_invoke`。scoped 名按字节序，隐藏名不出现，工具行带 description。无显式输入时 user 段为 `None`。截断按码点，不改 `message_id`；system 不截断；观测先受 `max_repl_output_length`，仍超限则从最旧观测收到标记，再截显式输入。不计算 digest |
| 26 | V15-D04 未加引号探针 | ✅ | 同上 | `SELECT jaz.return('null'::jsonb)` 与 `SELECT jaz.raise('x')` 的解析器反应只打印到标准输出，不写入仓库文件，也不成为第二种规范拼写。分类器仍在执行前拒绝 |

| 27 | §4.6.2 单语句事务与函数外 `search_path` | ✅ | `v15/repl/test_repl.py` | prepare 返回恰好四键，不改 `search_path`、不改角色。worker 在函数外 `SET LOCAL search_path` 后，scratch 里 `CREATE TABLE` / `INSERT` / `SELECT` 成功，属主是 `v15_repl`。`done` 语句重放 prepare 抛 `P1523` |
| 28 | §4.6.2 / §17 scratch 权限 | ✅ | 同上 | 已提交状态下 `v15_repl` 没有 scratch 的 `USAGE`/`CREATE`。prepare 对普通语句授予这两项且无 `GRANT OPTION`，无表级 `GRANT`；`bind_invoke` 只授予 `USAGE`。complete 之后收回。兄弟 schema 没有 `USAGE`，建表被拒绝。`v15_repl` 不能调用 `set_config` |
| 29 | §5.3 `assign` / `print` | ✅ | 同上 | `assign` 写入 `kind = var`。`print` 按调用顺序拼进 `capture`，中间无分隔符 |
| 30 | §4.6.2 / §5.3 引号 `return` / `raise` | ✅ | 同上 | 成功调用只暂存 `return_value` 或 `invokes.error`（`V15_RAISE` / `P1529`），invoke 仍是 `leased`。`resume_stmt` 等于语句条数。后继保持 `pending`，不在 complete 里 skip |
| 31 | §0.22 `V15_PRINT_AND_RETURN` | ✅ | 同上 | 已提交的 `print` 留下 `capture`。随后的 `return` 抛 `P1515`，不写 `return_value`，invoke 不终态，后继不 skip |
| 32 | §5.3 / §12.3 工具 | ✅ | 同上 | `v15_register_tool` 拒绝非 STABLE handler（`P1537`）且不留行。调用期 handler 的 `current_user` 是 `v15_tool_<name>`，返回后模型语句仍是 `v15_repl` / `session_user = v15_worker`。`v15_repl` 没有 handler 的 `EXECUTE`。`external = true` 抛 `P1517`。handler 异常、写内核表、写 scratch 都是 `P1525`，不留工具属主的 scratch 表 |
| 33 | §0.9 `jaz.bind_invoke` | ✅ | 同上 | 实执行抛 `P1503`，不插入子 invoke。prepare 只授 `USAGE` |
| 34 | §4.6.2 超时与取消 | ✅ | 同上 | 长语句被另一条 `v15_worker` 连接 `pg_cancel_backend`。到进程截止的取消丢掉该连接，新事务 `v15_fail_statement` 记 `P1526`。截止前的取消保留 `57014`。被取消事务的 `exec_context` 回到语句开始之前。后继不 skip |
| 35 | §0.7 已提交语句不重跑 | ✅ | 同上 | 杀连接后，已 `done` 的语句保持 `done`，重放 prepare 抛 `P1523`。未提交的 prepare 回到 `pending`。`exec_context` 回到上一笔已提交修订 |
| 36 | §17 级联删除探针 | ✅ | 同上 | `v15_owner` 的 definer 创建 schema，`v15_repl` 在该 scratch 建表，definer `DROP SCHEMA … CASCADE` 后 schema 不存在。`v15_owner` 不是 `v15_repl` 的成员。函数体内没有 `SET ROLE`。不写后备路径 |
| 37 | §4.1 租约与栅栏 | ✅ | 同上 | 栅栏不符且仍 `leased` 抛 `P1501`。owner 不符、再次 `begin_exec`、租约过期抛 `P1523` |

§2 的 `EXECUTE` 归属、§3 的 21 张表/PK/终态 CHECK、§11.1 的 invoke 清单断言，由 stage 1 gate 覆盖，不另立不变量编号。stage 2–6 不新增表。`v15_protocol.sql` 只有注释。stage 5 不实现 `v15_finish_exec`，因此 complete / fail 不把后继标成 `skipped`；切点是 `resume_stmt`。`v15_on_phase` 桩仍返回 `proceed`。stage 6 的 abort 关闭形状在 `v15_begin_llm` 里，桩打不到 phase abort；迭代上限、I/O 耗尽、预留 0 行和 `input_chars` 超限会走到关闭。本 gate 没有父 invoke。

| 38 | §4.5 / §12 全链 | ✅ | `v15/io/test_io.py` | claim 颁发 fence。begin 返回 `proceed` 及 attempt、request、digest、`n`。mark 之后、会话无打开事务时才 `FakeLLM.complete`。settle 后 attempt `settled`，迭代 `executing`，助手消息与 `pending` 语句留下。`llm_query` 以 `completed` 关闭，`invoke` span 仍开 |
| 39 | §4.5.1 载体 | ✅ | 同上 | send 事件的 `io` 含 `enter_messages` 与 `enter_overlay`，桩路径都是 JSON `null`。begin 不把 hook 消息插入 `llm_messages` |
| 40 | §4.13 `V15_STALE_FENCE` | ✅ | 同上 | 仍 `leased` 时出示旧 fence，begin 与 settle 都抛 `P1501`，不写 attempt、不写 response |
| 41 | §0.6 / §4.10 / §12 `unknown` | ✅ | 同上 | `call_started` 已提交而租约过期：行变 `unknown`，`calls_used` 加上存放的预留，`cost_used` 不变。不插入新 attempt。span 保持打开。迟结算抛 `P1502`，不写转录 |
| 42 | §12 `failed` | ✅ | 同上 | 未 mark 而过期：行变 `failed`，只释放预留，不加 `calls_used`。mark 之前 settle 抛 `P1523`。终态再 settle 抛 `P1502` |
| 43 | §4.5.1 重试 | ✅ | 同上 | 回收后重新 claim，再 `begin_llm` 插入 `n+1`。不复制 `enter` / `send` 事件。`logical_digest` 不变 |
| 44 | §0.21 / §4.5.1 `V15_IO_EXHAUSTED` | ✅ | 同上 | `n` 将超过有效上限时不插入该行。request `exhausted`，invoke `failed`、`fatal = false`、`P1513`。scratch 删除 |
| 45 | §4.5.1 / §11.3 预留 0 行 | ✅ | 同上 | 池盖不住缺省预留时返回 `abort`，`fatal = true`、`P1514`。不插入 attempt，预留不加。无父时只有自身 `aborted` |
| 46 | §4.5.1 迭代上限 | ✅ | 同上 | `iteration >= max` 在 enter 之前提交类关闭，`P1520`，`fatal = false`。不写 `llm_query/enter`。历史行 `repl_output` 为空 |
| 47 | §4.5.1 `input_chars` | ✅ | 同上 | 超限是提交类 `V15_VALUE_INVALID`。base 形状不对是回滚类 `P1524`，invoke 仍 `leased` |
| 48 | §4.5.3 `p_statements` | ✅ | 同上 | digest、kind、规范 `bind_invoke` 缺 `arg_sql` 都抛 `P1524`，attempt 仍 `leased`，不留语句行 |
| 49 | §4.11 / §17 切分失败 | ✅ | 同上 | 未闭合合成一行 `failed`，`error.code = V15_DIALECT`（`P1511`），attempt `settled`。本 stage 不执行、不 continue |
| 50 | §17 NUL | ✅ | 同上 | 六字符 `\u0000` 替换后的合成行结算为 `failed`，`V15_VALUE_INVALID`，attempt `settled`。原始 NUL 不进入 settle 参数 |
| 51 | §4.10 租约收回 | ✅ | 同上 | 无过期 attempt 时返回 0。过期 invoke 的 `running` 语句回到 `pending`，fence 加 1，审计 `lease_reclaimed`。未过期调用无写入 |
| 52 | §4.13 `40001` / `40P01` | ✅ | 同上 | 分类结果是整段重试，不是 `P1523`。不据此把 attempt 收成 `unknown` |
| 53 | §12 FakeLLM | ✅ | 同上 | 同一 `(logical_digest, n)` 两次 `complete` 返回同一 jsonb。未登记键在 Python 里失败。实现不导入时钟、随机或套接字 |

stage 7 不包含子 invoke。`v15_open_invoke` 在本 stage 落地，因为 loop 之前没有 open。`v15_on_phase` 桩仍返回 `proceed`。无父时终态直接关闭；有父时调用已有的 `v15_io_deliver_child`，不在本 stage 重写 §4.8。

| 54 | §4.3 根 open | ✅ | `v15/loop/test_loop.py` | worker 传入已渲染的 system。open 后 `runnable`，种子 `seed:system`，四行 baseline，scratch 存在。空输入不写 `seed:inputs` |
| 55 | §4.12 单 invoke 全链 | ✅ | 同上 | `run_until_quiescent` 从 open 扫到 `return` 的 `completed`。不依赖 `NOTIFY`。`v15_next_runnable` 按 `invoke_id` 稳定序，claim 顺序与扫描一致 |
| 56 | §4.9 return / raise | ✅ | 同上 | return：历史 `repl_output` 为空，invoke `completed`，scratch 删除，span 先 `repl_exec/exit completed` 再 `invoke/complete` 与 `invoke/exit completed`。raise：`P1529`，不写 `invoke/complete`，`repl_exec/exit` 与 `invoke/exit` 为 `failed` |
| 57 | §4.9 / R-G1 切点 | ✅ | 同上 | 成功 `return` 之后的 preclassified `failed` 变为 `skipped`。有序首错停在失败行，更后的 `pending` 被 skip，更前的 `done` 保留 |
| 58 | §4.11 空消息 / 散文 / 切分失败 | ✅ | 同上 | 空消息消耗迭代，`repl_output` 为空，`repl_exec/exit` 为 `completed`，invoke 不终态。散文 `42601` 写入 `sqlstate` 与 `code`，走 continue。未闭合合成行 `V15_DIALECT`，attempt `settled`，同样 continue |
| 59 | §4.9 continue 与历史时点 | ✅ | 同上 | `print` 之后当前轮不在 `repl_history`，也不出现在 `jaz.history`。finish 之后上一轮才入历史。失败 continue 的 `repl_exec/exit` 仍是 `completed` |
| 60 | §9.1 exit 信封 | ✅ | 同上 | `v15_repl_fatal_expand` 的 `llm_query/exit` phase `io` 是 `{attempt_id}`（可为 JSON `null`）；事件 payload 仍含匹配的 `outcome`。`repl_exec/exit` 与 `invoke/exit` 的 phase `io` 是 `{outcome}`。settle 路径的 `llm_query/exit` 同样是 `{attempt_id}` |
| 61 | §4.13 `40001` | ✅ | 同上 | worker 把 `40001` 整段重试，不改写成 `P1523`。`40P01` 同类，`55P03` 不是 |
| 62 | §4.6.2 进程截止 | ✅ | 同上 | 短 pragma 的长语句被另一条连接取消，记 `P1526`，连接不复用 |

stage 8 是树。fatal 只走桩预留耗尽。`invoke/enter` abort 的同事务送达是把桩临时改成返回 `abort`，不是 hook。hook 产生的 fatal 与 enter abort 仍是 stage 9。

| 63 | §0.2 / §4.8 同迭代消费 | ✅ | `v15/tree/test_tree.py` | 父一次回复里 `bind_invoke` 后的下一条 `jaz.var` 读到子结果并 `return`。父迭代仍是 0，`llm_attempts` 仍是 1。等待期间父 `repl_exec` 没有 `exit` |
| 64 | §4.7 先 bind-wait 再子 open | ✅ | 同上 | 挂起审计在送达之前。子停在 `runnable` 时父是 `suspended`、无租约，`v15_claim` 返回 NULL，扫描不返回父 |
| 65 | §4.8 三分支 | ✅ | 同上 | 子 `completed` 写 `kind = var`。子 `raise` 时父语句是 `V15_CHILD_ERROR`（`P1528`）、剩余语句 `skipped`、迭代 `continue`，子行保留 `V15_RAISE`。名字被 scope 占用是 `V15_DELIVERY_CONFLICT`（`P1527`），子仍 `completed`，不覆盖 scope |
| 66 | §0.11 / §4.8 fatal 展开 | ✅ | 同上 | 子孙的桩预留耗尽把父、子、孙都收成 `aborted`、`fatal = true`、`V15_BUDGET_EXHAUSTED`。链上原来 `running` 的 bind 语句失败，更晚语句 `skipped`。没有 `running` 残留。父语句不是 `V15_CHILD_ERROR` |
| 67 | §4.7 深度守卫同事务送达 | ✅ | 同上 | 子出生即 `V15_RECURSION_EXCEEDED`，无 attempt，scratch 已删。父语句是 `V15_CHILD_ERROR`，父不停在 `suspended` |
| 68 | §4.7 桩 `invoke/enter` abort 同事务送达 | ✅ | 同上 | 桩对深度 ≥ 2 的 enter 返回非 fatal `V15_HOOK_ABORT` 时，子 `failed` 并保留该码，父语句是 `V15_CHILD_ERROR`，父不停在 `suspended`。不是 hook 产生的 abort |
| 69 | §4.10 bind-wait 修理 | ✅ | 同上 | 过期租约、语句 `running` 且子已终态时，先置 `suspended` 再送达。`fence` 不加。`resume_stmt` 指向下一条，随后该语句读到送达的 var |
| 70 | §4.12 崩溃后扫回 | ✅ | 同上 | 杀掉停在 bind-wait 的 worker 后，新 worker 把子跑到终态，送达，父从下一条已生成语句继续，不再次调父 LLM |
| 71 | §7.2 / §8.3 按值复制与继承 | ✅ | 同上 | 子 `assign` 不改父 scope。显式 input 与 explicit 工具不进子。scope 工具连 `tool_grants` 复制。子不收父 local layer，不拷父 `resolved_config`，propagating hook 以新 ordinal 接上，local hook 不复制 |
| 72 | §4.7 求值捕获 | ✅ | 同上 | `V15_RECURSION_DISABLED`、`V15_SCOPE_CONFLICT`、`V15_INVOKE_FORM`（`jaz.assign` 与 scratch 写）、零行 `V15_VALUE_INVALID`、原生 `22012` 都把该语句提交为 `failed`，不留子行，不留在 `pending` |

stage 9 是合运行时。`v15_on_phase` 与四个治理 handler 同 oid 替换。可选 hook 只在 govern 文件创建。

| 73 | §0.12 / §9 合成 | ✅ | `v15/govern/test_govern.py` | 同 phase 等值黑板合并为一代；不等值抛 `P1533` 且不留行。输入不等抛 `P1534` 且不留 binding。同 id 消息不等抛 `P1535`。预留名抛 `P1506`。未知键抛 `P1516` |
| 74 | §0.15 / §9.2 调用 | ✅ | 同上 | `public` 同名诱饵不被调用。同会话 `CREATE OR REPLACE` 后 oid 不变，不更新摘要抛 `P1536`，更新后新体生效。只 `GRANT` 或给 owner 表权限也是 `P1536` |
| 75 | §9.2 异常隔离 | ✅ | 同上 | 非 baseline `RAISE` 留审计、兄弟效应仍落地、事务继续。baseline `RAISE` 抛 `P1508`，审计不留下。exit 上 abort 抛 `P1506`，outcome 行回滚。exit 可以写黑板 |
| 76 | §0.12 代际 | ✅ | 同上 | 同 phase 后一个 handler 读到的代数是写入前的 0，落地后该键 generation 为 1 |
| 77 | §9.5 / R-C12 / R-D20 | ✅ | 同上 | 保留码外的 abort 归一为 `V15_HOOK_ABORT`。`V15_ITERATION_EXCEEDED` 的 fatal 归一为 false。保留码不一致时顶层也是 `V15_HOOK_ABORT`，fatal 取归一后的或 |
| 78 | §10.1 四个治理 hook | ✅ | 同上 | 迭代 `>= max` 在租赁前 abort `P1520`，不插 attempt。`next_attempt_n > max` 为 `P1513`。`depth = max` 关闭递归，`depth > max` 为 `P1519`。语句毫秒与 ceiling 不一致时 handler 抛 `P1521`。超时地板不超过治理 max |
| 79 | §10.2 可选 hook | ✅ | 同上 | `iteration_limit` 更紧时下一轮租赁前 abort `P1520`。`budget_forcing:<ordinal>:<n>` 正文逐字冻结，complete 不改计数。窗口警告两套正文逐字冻结；叶子变体不含 `bind_invoke`；瞬态行不进 `llm_messages` |
| 80 | §11.3 池 | ✅ | 同上 | `budget_pool` 预留恰好一次，结算把存放量转入 `calls_used`。未开始的回收退回预留且不加 `calls_used`。预留 0 行是 `P1514`、`fatal = true`，不插 attempt，池不动 |
| 81 | §9.3 登记 | ✅ | 同上 | `IMMUTABLE`、`pg_temp`、错 owner、内核表权限、C 语言都抛 `P1537`，不留 `hook_defs` 行 |
| 82 | §4.3 / §4.8 hook 终态 | ✅ | 同上 | 子 `invoke/enter` 的 hook abort 同事务送达，父语句是 `V15_CHILD_ERROR`，子行保留 `V15_RECURSION_EXCEEDED`，父不停在 `suspended`。hook 返回的 `fatal = true` 把父和子都收成 `aborted` / `V15_BUDGET_EXHAUSTED` |
| 83 | §10.2 端到端 | ✅ | 同上 | 根→子→孙加 `budget_forcing`、窗口警告和池，`FakeLLM` 剧本经 `run_until_quiescent` 收敛。三行都 `completed`。警告不入 `llm_messages`。叶子 `recursion_available = false` |

## M3 · §0

| 条 | 证明 | 断言的行为 |
|---|---|---|
| §0.0 合运行时 | `v15/govern/test_govern.py` | 九文件加载后的库才跑 dispatcher。前缀库不是合运行时 |
| §0.1 版本隔离 | 同上 | 只改 `v15/` 与 v15 文档，不改 v8 / v13 |
| §0.2 同迭代消费 | `v15/tree/test_tree.py` | 父下一条 `jaz.var` 读到子结果，父不再次 LLM |
| §0.3 行是权威 | `v15/schema/test_schema.py` | `invoke_events` 只追加，`seq` 连续 |
| §0.4 事务内无外部 IO | `v15/io/test_io.py` | FakeLLM 只在无打开事务时调用。SQL 不调 provider |
| §0.5 栅栏 | `v15/repl/test_repl.py`、`v15/io/test_io.py` | 旧 fence 抛 `P1501`，不改控制态 |
| §0.6 unknown | `v15/io/test_io.py` | 已开始而过期是 `unknown`；迟结算抛 `P1502`，不写转录 |
| §0.7 语句原子性 | `v15/repl/test_repl.py` | 已 `done` 的语句不重跑；未提交的 prepare 回到 `pending` |
| §0.8 语句间挂起 | `v15/tree/test_tree.py` | 挂起在语句之间。函数本身不产子 |
| §0.9 函数不产子 | `v15/repl/test_repl.py` | `jaz.bind_invoke` 抛 `P1503`，不插子行 |
| §0.10 一个租约持有者 | `v15/tree/test_tree.py` | `suspended` 不可 claim。扫描不返回父 |
| §0.11 fatal | `v15/tree/test_tree.py`、`v15/govern/test_govern.py` | 桩预留耗尽与 hook `fatal = true` 都展开祖先。非 fatal 只结束本 invoke |
| §0.12 效应代数 | `v15/govern/test_govern.py` | 闭集、合成、预留最先、代际屏障、保留码归一 |
| §0.13 治理清单 | `v15/schema/test_schema.py`、`v15/config/test_config.py` | 恰好一行。调用方只能收紧。放宽抛 `P1505` |
| §0.14 授权靠 grant | `v15/namespace/test_namespace.py`、`v15/govern/test_govern.py` | 无 grant 的工具抛 `P1507`，invoke 不因此终态 |
| §0.15 handler 只返回效应 | `v15/govern/test_govern.py` | 按 oid 调用。摘要或表权限漂移抛 `P1536`。baseline 异常是 `P1508` |
| §0.16 配置冻结 | `v15/config/test_config.py` | open 之后改 profile，已打开行的 `config_digest` 不变 |
| §0.17 历史隔离 | `v15/namespace/test_namespace.py` | 另一 invoke 的历史不出现。无关 id 抛 `P1510` |
| §0.18 方言 | `v15/protocol/test_protocol.py` | 五式、`DO` 为 `V15_DIALECT`、`ALTER TABLE` 为 `V15_DDL` |
| §0.19 SQLSTATE | `v15/schema/test_schema.py` 起 | gate 按 `pgcode` 分类。本族不用 `P0001` 当合同码 |
| §0.20 身份 | `v15/schema/test_schema.py`、`v15/namespace/test_namespace.py` | 转移看 `session_user`。模型语句的 `current_user` 是 `v15_repl`。definer 体不 `SET ROLE` |
| §0.21 attempt 上限 | `v15/io/test_io.py`、`v15/govern/test_govern.py` | 越限不插行。预留数量来自合成结果，不是写死的 1 |
| §0.22 打印与结束互斥 | `v15/namespace/test_namespace.py`、`v15/repl/test_repl.py` | 既打印又 return / raise 抛 `P1515`，invoke 不终态 |
| §0.23 扫描恢复 | `v15/loop/test_loop.py`、`v15/tree/test_tree.py` | 丢失 `NOTIFY` 仍能扫回。回收能送达已终态的子 |
| §0.24 span 只在事件 | `v15/schema/test_schema.py`、`v15/loop/test_loop.py` | 没有 span 表。exit 的 outcome 是小写三值 |
| §0.25 深度与迭代 | `v15/tree/test_tree.py`、`v15/govern/test_govern.py` | `depth = max` 关递归，`depth > max` 才是 `P1519`。迭代上限在租赁前 |
| §0.26 scratch | `v15/schema/test_schema.py`、`v15/repl/test_repl.py` | 属主 `v15_owner`。终态由属主 `DROP SCHEMA … CASCADE`。体内无 `SET ROLE` |
| §0.27 历史时点 | `v15/loop/test_loop.py` | 当前轮不在 `repl_history`。finish 之后才入历史 |
| §0.28 阶段签名 | `v15/schema/test_schema.py`、`v15/govern/test_govern.py` | 桩与真体同 oid。`contract` 不是 1 或未知键抛 `P1516` |
| §0.29 工具同步 | `v15/namespace/test_namespace.py`、`v15/repl/test_repl.py` | 语句内返回 jsonb。调用后 `current_user` 仍是 `v15_repl`。`external = true` 抛 `P1517` |

## M3 · §13

| 码 | SQLSTATE | 证明 | 断言的行为 |
|---|---|---|---|
| `V15_STALE_FENCE` | `P1501` | `v15/io/test_io.py` | 仍 leased 时旧 fence 不写 attempt、不写 response |
| `V15_ATTEMPT_NOT_SETTLEABLE` | `P1502` | 同上 | `unknown` / `failed` 再 settle 被拒，不写转录 |
| `V15_INVOKE_FORM` | `P1503` | `v15/repl/test_repl.py`、`v15/tree/test_tree.py` | 函数不产子。实参写记号或求值错误把语句收成 `failed` |
| `V15_GOVERNANCE_MISSING` | `P1504` | `v15/schema/test_schema.py` | 清单损坏或缺失时 assert 抛这个码 |
| `V15_GOVERNANCE_RAISE` | `P1505` | `v15/config/test_config.py`、`v15/govern/test_govern.py` | 放宽 ceiling 或可选 hook 的 max 被拒。open 不留行 |
| `V15_INVALID_EFFECT` | `P1506` | `v15/govern/test_govern.py` | 预留名、exit abort、不允许的效应回滚阶段 |
| `V15_TOOL_UNAUTHORIZED` | `P1507` | `v15/namespace/test_namespace.py`、`v15/govern/test_govern.py` | 无 grant 的 `jaz.tool` 只失败该语句 |
| `V15_GOVERNANCE_FAULT` | `P1508` | `v15/govern/test_govern.py` | baseline handler 抛异常时阶段回滚，不留审计 |
| `V15_SCOPE_CONFLICT` | `P1509` | `v15/tree/test_tree.py` | 子 open 撞名把该语句收成 `failed`，不留子行 |
| `V15_HISTORY_SCOPE` | `P1510` | `v15/namespace/test_namespace.py` | 非自身非祖先的 `prior_history` 被拒 |
| `V15_DIALECT` | `P1511` | `v15/protocol/test_protocol.py`、`v15/io/test_io.py` | `DO` 等在分类时拒绝。未闭合合成行结算为 `failed` |
| `V15_DDL` | `P1512` | `v15/schema/test_schema.py`、`v15/protocol/test_protocol.py` | `ALTER TABLE` 与越界 DDL 被拒 |
| `V15_IO_EXHAUSTED` | `P1513` | `v15/io/test_io.py`、`v15/govern/test_govern.py` | 下一 attempt 越限不插入。hook 在 enter 返回同一码 |
| `V15_BUDGET_EXHAUSTED` | `P1514` | `v15/io/test_io.py`、`v15/govern/test_govern.py` | 预留 0 行是 fatal abort。不插 attempt，效应不写 |
| `V15_PRINT_AND_RETURN` | `P1515` | `v15/repl/test_repl.py` | 已打印再 return 抛这个码，invoke 不终态 |
| `V15_PHASE_CONTRACT` | `P1516` | `v15/govern/test_govern.py` | 返回对象含未列出的键时阶段回滚 |
| `V15_EXTERNAL_TOOL` | `P1517` | `v15/repl/test_repl.py` | `external = true` 不调用 handler |
| `V15_RECURSION_DISABLED` | `P1518` | `v15/tree/test_tree.py` | 递归已关时 `bind_invoke` 把语句收成 `failed` |
| `V15_RECURSION_EXCEEDED` | `P1519` | `v15/tree/test_tree.py`、`v15/govern/test_govern.py` | 内核守卫与 hook abort 都是提交类。父语句另记 `V15_CHILD_ERROR` |
| `V15_ITERATION_EXCEEDED` | `P1520` | `v15/io/test_io.py`、`v15/govern/test_govern.py` | 租赁 attempt 之前中止。更紧的可选 hook 同样不插越限行 |
| `V15_MANIFEST_DIGEST` | `P1521` | `v15/schema/test_schema.py`、`v15/govern/test_govern.py` | 有效上限摘要不符，或治理 handler 的 max 与 ceiling 不一致 |
| `V15_ROLE` | `P1522` | `v15/namespace/test_namespace.py` | 非 `v15_repl` 调包装被拒 |
| `V15_INVALID_TRANSITION` | `P1523` | `v15/repl/test_repl.py`、`v15/io/test_io.py` | 租约、owner、重复 begin、mark 前 settle 被拒 |
| `V15_VALUE_INVALID` | `P1524` | `v15/config/test_config.py`、`v15/io/test_io.py`、`v15/tree/test_tree.py` | 折叠、base 形状、零行实参各自按自己的路径失败 |
| `V15_HANDLER_FAILED` | `P1525` | `v15/repl/test_repl.py` | 工具 handler 异常只失败该语句 |
| `V15_STATEMENT_TIMEOUT` | `P1526` | `v15/repl/test_repl.py`、`v15/loop/test_loop.py` | 进程截止把长语句收成这个码 |
| `V15_DELIVERY_CONFLICT` | `P1527` | `v15/tree/test_tree.py` | 绑定名被 scope 占用时不覆盖，子仍 `completed` |
| `V15_CHILD_ERROR` | `P1528` | `v15/tree/test_tree.py`、`v15/govern/test_govern.py` | 子 `failed` 时父语句用这个码，不抄子码 |
| `V15_RAISE` | `P1529` | `v15/loop/test_loop.py` | `jaz."raise"` 把 invoke 收成 `failed`，不写 `invoke/complete` |
| `V15_DEPTH_SELF` | `P1530` | `v15/config/test_config.py` | depth 层写组件列或 partial 再含 `depth_map` 被拒 |
| `V15_CONFIG_LOCAL` | `P1531` | 同上 | local 指向 scope / depth 层，或子路径传入 local，被拒 |
| `V15_BASELINE_IMMUTABLE` | `P1532` | `v15/schema/test_schema.py`、`v15/config/test_config.py` | 改写 baseline 行或层里写 `baseline_hooks` 被拒 |
| `V15_BLACKBOARD_CONFLICT` | `P1533` | `v15/govern/test_govern.py` | 同 phase 同键 value 不等则回滚，不留行 |
| `V15_INPUT_CONFLICT` | `P1534` | 同上 | 同名 input 不等则回滚，不留 binding |
| `V15_EFFECT_CONFLICT` | `P1535` | 同上 | 同 id 消息载荷不等则回滚 |
| `V15_HANDLER_DIGEST` | `P1536` | 同上 | 体、GRANT、表权限任一漂移都在调用前失败 |
| `V15_HANDLER_SHAPE` | `P1537` | `v15/repl/test_repl.py`、`v15/govern/test_govern.py` | 登记拒绝 IMMUTABLE、错 search_path、错 owner、表权限、C 语言 |
| `V15_HOOK_ABORT` | `P1538` | `v15/govern/test_govern.py` | 保留码外的 abort，或规范化后不一致的 abort，顶层用这个码 |
| `V15_PROVIDER_REJECTED` | `P1539` | `v15/provider/test_provider.py` | 预检或已开始的确定性拒绝提交为这个码，`fatal = false`，无助手消息。hook 带回它则归一为 `V15_HOOK_ABORT`，不因 `P1506` 被拒 |

## stage 10 · SQL

D27–D30 的句子在规格 §14 与偏差台账。线协议、计价与 `reasoning_content` 由 10.8–10.14 证明。冒烟脚本不是 gate，由 10.15 证明。

| # | 条文 | 状态 | 测试落点 | 断言的行为 |
|---|---|---|---|---|
| 10.1 | §0.0 gate 不开网络 | ✅ | `v15/provider/test_provider.py` | 进程内剥掉四枚凭据。`urlopen` 罩成 `AssertionError("network")` 且计数为 0。断网点是默认 opener 构造，不是 `urlopen`。适配器只用注入传输 |
| 10.8 | 价目 fail-closed | ✅ | 同上 | flash 两档精确到 `Decimal`。12:00 与 18:00 空闲。`deepseek-v4-pro`、未知模型、naive 时间返回 `None`，不是 0 |
| 10.9 | 线上无 temperature / D27 | ✅ | 同上 | 捕获的 JSON 无 `temperature`、无 `top_p`、`stream` 为 false；`max_output_tokens` 成 `max_tokens`；消息序与 request 一致且无 `message_id` |
| 10.10 | keyless 与凭据优先级 | ✅ | 同上 | 显式参数 > `DEEPSEEK_API_KEY` > `OPENAI_API_KEY` > `""`。import 不读 env。无 key 的 preflight 是 `credentials_absent`，传输计数 0 |
| 10.11 | HTTP 分类 | ✅ | 同上 | 402/401/422/404/403/400/499 与 `content_filter`/`model_mismatch` reject。400 body-parse、429/503/timeout/URLError/3xx/非 200 2xx/usage_invalid/unpriced abandon。空串与 `length` settle。缺 usage 不以 0 settle |
| 10.12 | NUL 与 Decimal settle | ✅ | 同上 | 先切分后替换。库内 content 与语句 sql 含六字符序列且不含 NUL，语句 `V15_VALUE_INVALID`，attempt `settled`。`Decimal("0.15")` 入库与之相等，不是二进制浮点 |
| 10.13 | worker 回归 | ✅ | 同上 | FakeLLM 仍把 `SELECT jaz."return"(...)` 跑到 `completed`。KeyError 不 settle。脚本化重试只把第二次成本记入 `cost_used`。`max_io=1` 不插第二行 |
| 10.14 | D29 reasoning | ✅ | 同上 | `reasoning_content` 不进 `content`，审计只有 `reasoning_chars` |
| 10.2 | §4.5.5 unstarted | ✅ | 同上 | 不 mark。attempt `failed`，不计 call。invoke `failed`、`fatal = false`、`P1539`、`message = ''`。无助手消息，无语句，scratch 已删 |
| 10.3 | §4.5.5 started reject | ✅ | 同上 | attempt `unknown`，按行上存放的预留计入 `calls_used`，`cost_used` 不增。invoke 同上 `P1539`。无助手消息。再调用抛 `P1502` |
| 10.4 | §4.5.5 abandon | ✅ | 同上 | attempt `unknown`。invoke `runnable`，fence 加 1，租约空。`llm_query` span 仍开。retry 的 `new_attempt_id` 为 JSON null。`max_io_attempts = 1` 时不再插入新行，终态是 `V15_IO_EXHAUSTED` |
| 10.5 | §4.8 子送达 | ✅ | 同上 | 子保留 `V15_PROVIDER_REJECTED` / `P1539`。父语句 `V15_CHILD_ERROR` / `P1528`。父 `runnable`，不是 `aborted` |
| 10.6 | §9.5 / §13 hook 归一 | ✅ | 同上 | hook 返回 `V15_PROVIDER_REJECTED`。阶段不抛 `P1506`。提交后的 invoke 是 `V15_HOOK_ABORT` / `P1538`，`fatal = false`，`message = ''` |
| 10.7 | §15 前缀 | ✅ | 同上 | `files_through("govern")` 仍是前 9 个且末项为 govern SQL。完整列表长度为 10 且末项为 provider SQL |
| 10.15 | 冒烟脚本不是 gate | ✅ | 同上 | `smoke.py` 不是 `test_*.py`，不是合运行时证明。无 flag 打印 `not_requested` 退出 0，不构造适配器。`--real-provider-smoke` 无 key 打印 `credentials_absent` 退出 2，不调用 `complete`。默认传输边界 `side_effect=AssertionError`，这两条不触网 |

## M3 · §14

| 行 | 证明 | 断言的行为 |
|---|---|---|
| V15-D01 | `v15/protocol/test_protocol.py` | 一轮回复按 SQL 切分，不是 Python |
| V15-D02 | `v15/tree/test_tree.py` | 子结果在下一条已生成语句里用 `jaz.var` 读取 |
| V15-D03 | `v15/protocol/test_protocol.py`、`v15/namespace/test_namespace.py` | 历史是 `jaz.history` / `jaz.prior_history`，提示词没有 `__history__` |
| V15-D04 | `v15/protocol/test_protocol.py` | 未加引号的 return / raise 在执行前就是 `V15_INVOKE_FORM`。探针只打印 |
| V15-D05 | `v15/repl/test_repl.py` | 工具在语句内同步返回 jsonb，不写 scratch，不切换角色 |
| V15-D06 | `v15/tree/test_tree.py` | 父 `suspended` 时不可 claim。没有同一父迭代的两个 running 子语句 |
| V15-D07 | `v15/protocol/test_protocol.py` | 渲染正文以冻结段落为准，不读模板文件 |
| V15-D08 | `v15/govern/test_govern.py` | 效应闭集。不等的消息回滚。不等的 abort 码提交为 `V15_HOOK_ABORT` |
| V15-D09 | `v15/config/test_config.py` | open 之后改 profile，已打开 invoke 的摘要不变 |
| V15-D10 | `v15/tree/test_tree.py`、`v15/govern/test_govern.py` | 根深度是 1。`depth = max` 关递归，`depth > max` 才越限 |
| V15-D11 | `v15/tree/test_tree.py` | 子按自己的深度重折，不拷父的 `resolved_config`，不收 local |
| V15-D12 | `v15/tree/test_tree.py` | propagating 行以新 ordinal 复制。local 不复制。计数不跟着走 |
| V15-D13 | `v15/repl/test_repl.py` | 失败语句的写入随保存点消失。已提交的前序语句还在 |
| V15-D14 | `v15/io/test_io.py` | 过期 attempt 是 `failed` 或 `unknown`。回收不插新 attempt，不调阶段函数 |
| V15-D15 | `v15/tree/test_tree.py`、`v15/govern/test_govern.py` | 池盖不住预留时 fatal 展开。尚未写下的 hook 效应不写 |
| V15-D16 | `v15/schema/test_schema.py`、`v15/config/test_config.py` | 没有清单就不能 open。invoke 摘要是有效上限，不是单例摘要的拷贝 |
| V15-D17 | `v15/namespace/test_namespace.py`、`v15/govern/test_govern.py` | 只有 binding 没有 grant 时 `jaz.tool` 抛 `P1507` |
| V15-D18 | `v15/schema/test_schema.py`、`v15/loop/test_loop.py` | span 只是事件行。父等待期间 `repl_exec` 没有 exit |
| V15-D19 | `v15/protocol/test_protocol.py`、`v15/loop/test_loop.py` | 截断只发生在送进模型的 base。历史行保存观测全文 |
| V15-D20 | `v15/protocol/test_protocol.py` | `DO` 是 `V15_DIALECT`。`ALTER TABLE` 是 `V15_DDL`。`WITH RECURSIVE` 仍是 `plain` |
| V15-D21 | `v15/govern/test_govern.py` | `supply_llm_response` 使阶段回滚。非 baseline 抛出的异常才只留审计 |
| V15-D22 | `v15/namespace/test_namespace.py` | 隔离证据是第二个 invoke 的行集，不是 `EXPLAIN` |
| V15-D23 | `v15/tree/test_tree.py` | local hook 不复制给子。子只接 propagating 行 |
| V15-D24 | `v15/repl/test_repl.py`、`v15/tree/test_tree.py` | bind 实参只授 `USAGE`。写记号和 scratch 写都是 `V15_INVOKE_FORM` |
| V15-D25 | `v15/protocol/test_protocol.py` | `DO` 被拒绝。语句内部的迭代只走 `WITH RECURSIVE` |
| V15-D26 | `v15/govern/test_govern.py` | exit 上的 abort 回滚，outcome 行不留下。exit 只能写黑板 |

D27–D30 已写入规格与台账。D27 与 D29 由 provider gate 的线协议与 reasoning 断言证明。D28 与 D30 是记账口径，不在本 gate 里对发票。

## Demo evidence（不是 gate）

| 跑次 | 模式 | 结果 | 落点 | 断言的行为 |
|---|---|---|---|---|
| 2026-09-29 NOTE_V1 | DEMO_MODE=real deepseek-flash lease 240s | tail_ok relay_ok | 驱动源码已入库（demo_v15/ 下 8 个文件）；reports/ 仍 gitignore、不入库 | 绑定迭代恰好两句且下一条 return 读到子 var；该迭代恰好一条 settled 且 max(n) 等于它；suspend 与 deliver 之间无 repl_exec exit；十道 gate 不导入该驱动。 |
| 2026-09-29 CHAIN hops=8 | DEMO_MODE=real deepseek-flash lease 240s | tail_ok relay_ok | gitignore 的 demo_v15/reports/ | 链长 N=8 时每一环的绑定迭代恰好两句且下一条 return 读到子 var；该迭代恰好一条 settled；suspend 与 deliver 之间无 repl_exec/exit。十道 gate 不导入该驱动。 |
| 2026-09-29 RECALL hops=5 | 同上 | tail_ok recall_soft_fail（token 列提取：叶搜了 llm_response，token 在 repl_output） | 同上 | 根 iteration 0 的 repl_output 持有 token；子 input 无 facts；叶语句含 jaz.prior_history(根 uuid)；根绑定迭代的 request 含瞬态 context_window_warning，且该行不在 llm_messages。 |
