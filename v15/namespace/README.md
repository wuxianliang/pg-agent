# v15 stage 2 · namespace

Gate: `uv run python v15/namespace/test_namespace.py`（退出码 0 = 通过）

库名 `agent_v15_namespace`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 十一个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库（含 stage 1 的 `agent_v15_schema`），再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "namespace")`。角色语句不在 SQL 文件里。加载结束后 `v15_bootstrap` 改为 `NOLOGIN`。

## 内容

- `jaz.<name>`：plpgsql、`VOLATILE`、`SECURITY INVOKER`。`current_user` 不是 `v15_repl` 时抛 `V15_ROLE`（`P1522`），否则调用 `v15.jaz_<name>`
- `v15.jaz_<name>`：plpgsql、`VOLATILE`、`SECURITY DEFINER`、`search_path = pg_catalog`、属主 `v15_owner`。只断言本后端 `exec_context` 且该语句 `running`，否则 `V15_INVALID_TRANSITION`（`P1523`），不断言 `current_user`
- 公开函数：`var`、`assign`、`print`、`tool`、`"return"`、`"raise"`、`bind_invoke`、`prior_history`
- 视图 `jaz.history`、`jaz.request_messages`：属主 `v15_owner`，`security_barrier = true`，`security_invoker = false`。没有本后端 `exec_context` 行时抛 `P1523`。基表 `SELECT` 不授给 `v15_repl`
- §5.4 没有 `jaz.variables` / `jaz.tools`，本 stage 不建

`EXECUTE` 只授 `v15_repl`：包装与 `v15.jaz_*` 都是。`v15_worker` 未 `SET ROLE` 时不继承。`exec_context` 与 binding / iteration / invoke 的直接 DML 不授 `v15_repl` 或 `v15_worker`；写入发生在属主 `v15_owner` 的 definer 体内。

视图要在零行时也能抛错，所以从 `v15.v15_exec_view()` 取当前行。该函数不是模型面签名，`EXECUTE` 授给 `v15_repl`，只为了视图能调用它。

## 本 stage 不证明

`v15_prepare_statement` / `v15_complete_statement`、语句保存点、切分器、worker 循环。gate 以超级用户插入 invoke、iteration、`running` 语句和 `exec_context` 来布置场景，断言函数与视图的行为。
