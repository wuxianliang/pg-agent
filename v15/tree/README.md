# v15 stage 8 · tree

Gate: `uv run python v15/tree/test_tree.py`（退出码 0 = 通过）

库名 `agent_v15_tree`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 九个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库，再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "tree")`。

## 内容

`v15_suspend_for_child` 是子 invoke 的唯一插入路径。顺序是 §4.7：先插入子行，立刻把父写成 bind-wait，然后才跑深度守卫与 `invoke/enter`。子 open 复用 `v15_loop_close_open`、`v15_loop_compose_inputs`、`v15_loop_install_hook`、`v15_resolve_child_config` 与已有的 `v15_io_deliver_child` / `v15_repl_fatal_expand`。没有改 `v15_open_invoke` 的签名。

worker 认出 `bind_invoke` 后不执行 `jaz.bind_invoke`。它只授过的 `USAGE` 上求值已存放的 `arg_sql`，用父 scope 快照和子 inputs 预渲染子种子，再调用 suspend。五码和求值错误回到保存点并提交 `failed`。挂起成功后回到扫描，不给父再发一次 LLM。

## 本 stage 不证明

hook 返回的 `fatal = true`，以及 hook 自己在 `invoke/enter` 上的 abort。那些是 stage 9。本 gate 的 enter abort 只把桩临时改成返回 `abort`，用来证明同事务送达。fatal 展开只走桩预留耗尽。
