# v15 stage 5 · repl

Gate: `uv run python v15/repl/test_repl.py`（退出码 0 = 通过）

库名 `agent_v15_repl`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 九个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库，再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "repl")`。角色语句不在 SQL 文件里。加载结束后 `v15_bootstrap` 改为 `NOLOGIN`。测试自建 `v15_tool_<name>`。

## 内容

`v15_repl.sql` 增加执行窗口，不建表。

- `v15_begin_exec`：`repl_exec/enter` 然后 `send`。桩阶段 `v15_on_phase` 仍返回 `proceed`。abort 关闭形状按 §4.6.1 / §4.5.1 写在函数里，父行走 §4.8；stage 9 替换 `v15_on_phase` 体之后生效。
- `v15_prepare_statement`：返回恰好 `statement_fence`、`timeout_ms`、`kind`、`scratch_schema`。不 `set_config`，不 `SET ROLE`。非 `bind_invoke` 授予 scratch 的 `USAGE, CREATE`；`bind_invoke` 只授予 `USAGE`。无 `GRANT OPTION`，无表级 `GRANT`。
- `v15_complete_statement`：`done` / `failed`。`return` / `raise` 成功时 `resume_stmt` 等于语句条数，其余 `done` 加 1。不 skip。返回前 `REVOKE` schema 权限。
- `v15_fail_statement`：`pending` 且 `error IS NULL` 记 `failed`。不 skip。取消路径在新连接上调用。
- `v15_register_tool`：目录登记。handler 由测试自建，`jaz.tool` 按 oid 调用。

worker 在函数外执行 `SET LOCAL search_path` 与 `statement_timeout = timeout_ms + 1000`。语句脚本是 `prepare` → `SAVEPOINT` → `SET ROLE v15_repl` → 执行 → `RESET ROLE` → `complete` → `COMMIT`。

## 本 stage 不证明

`v15_finish_exec`、`v15_suspend_for_child`、`v15_settle_llm`。后继 `skipped` 只在 finish。`v15_on_phase` 桩不返回 `abort`，所以关闭形状没有被本 gate 打到。
