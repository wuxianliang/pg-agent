# v15 覆盖矩阵（2026-09-29）

初版。只记 stage 1 gate 已经断言的 §0 条目。行为以 `docs/designs/v15-jaz-dev.md` rev 8 为准。矩阵不是第二份合同。未列出的 §0 条目尚未有 gate。

状态来自实跑：`uv run python v15/schema/test_schema.py`，退出码 0。

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

§2 的 `EXECUTE` 归属、§3 的 21 张表/PK/终态 CHECK、§11.1 的 invoke 清单断言，由同一 gate 覆盖，不另立不变量编号。
