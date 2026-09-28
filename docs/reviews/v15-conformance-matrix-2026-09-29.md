# v15 覆盖矩阵（2026-09-29）

记 stage 1–3 gate 已经断言的条目。行为以 `docs/designs/v15-jaz-dev.md` rev 8 为准。矩阵不是第二份合同。未列出的 §0 条目尚未有 gate。

状态来自实跑：`uv run python v15/config/test_config.py` 退出码 0；随后 `uv run python v15/schema/test_schema.py` 退出码 0；随后 `uv run python v15/namespace/test_namespace.py` 退出码 0。

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

§2 的 `EXECUTE` 归属、§3 的 21 张表/PK/终态 CHECK、§11.1 的 invoke 清单断言，由 stage 1 gate 覆盖，不另立不变量编号。stage 2 与 stage 3 不新增表。
