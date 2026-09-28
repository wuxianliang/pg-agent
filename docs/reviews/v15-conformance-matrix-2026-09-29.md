# v15 覆盖矩阵（2026-09-29）

记 stage 1–5 gate 已经断言的条目。行为以 `docs/designs/v15-jaz-dev.md` rev 8 为准。矩阵不是第二份合同。未列出的 §0 条目尚未有 gate。

状态来自实跑：`uv run python v15/repl/test_repl.py` 退出码 0。随后复跑 `v15/schema/test_schema.py`、`v15/namespace/test_namespace.py`、`v15/config/test_config.py`、`v15/protocol/test_protocol.py`，四道都是退出码 0。

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

§2 的 `EXECUTE` 归属、§3 的 21 张表/PK/终态 CHECK、§11.1 的 invoke 清单断言，由 stage 1 gate 覆盖，不另立不变量编号。stage 2–5 不新增表。`v15_protocol.sql` 只有注释。stage 5 不实现 `v15_finish_exec`，因此 complete / fail 不把后继标成 `skipped`；切点是 `resume_stmt`。`v15_on_phase` 桩仍返回 `proceed`，abort 关闭形状在 `v15_begin_exec` 里，本 gate 打不到。stage 5 gate 之后复跑 stage 1–4，四道都是退出码 0。
