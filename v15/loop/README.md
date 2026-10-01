# v15 stage 7 · loop

Gate: `uv run python v15/loop/test_loop.py`（退出码 0 = 通过）

库名 `agent_v15_loop`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 十二个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库，再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "loop")`。角色语句不在 SQL 文件里。

## 内容

`v15_open_invoke` 放在本 stage。loop 之前没有 open；§15 把 open 放在循环之前的能力线上，规格没锁死实现 stage。根 open 按 §4.3：折叠配置、安装 baseline、建 scratch、写 `seed:system`。效应后的 inputs 种子由 SQL 按 §6.5 组成，不调用 Python 渲染器。本 gate 没有父。

`v15_finish_exec` 按 §4.9：先锁，再按 R-G1 切点 skip，再校验三分支。`return` / `raise` 的切点是该语句下标，不是 `resume_stmt`。return 切点之前的 `failed` 行仅当 `error.code` 属于 `{V15_TOOL_BINDING, V15_TOOL_FAILED, V15_TOOL_EXHAUSTED, V15_TOOL_UNAUTHORIZED}` 时可跳过；其它先验失败不得 return-completed。对比 gate 在 `test_loop.py`。continue 写历史与观测，插入下一迭代，invoke 回到 `runnable`，不关 `invoke` span，不删 scratch。无父时直接终态。有父时调用已有的 `v15_io_deliver_child`，不在本 stage 重写 §4.8。

`v15/worker.py` 的 `run_until_quiescent` 是 §4.12 的循环。FakeLLM 只在 mark 提交之后、会话没有打开的事务时调用。`40001` / `40P01` 整段重试。语句截止时间到了从另一条连接 `pg_cancel_backend`，然后丢掉该连接，新事务 `v15_fail_statement`。

## 信封纠偏

`v15_repl_close_span` 原先对所有 span 的 phase `io` 都传 `{outcome}`。按 R-F5 / §9.1，`llm_query/exit` 的 phase `io` 是 `{attempt_id}`，可为 JSON `null`。`repl_exec/exit` 与 `invoke/exit` 仍是 `{outcome}`。事件 payload 继续带与 exit 行相同的 `outcome`。`v15_io_exit_query` 本来就是这个形状，没有改。

## 本 stage 不证明

子 invoke、`v15_suspend_for_child`、hook 返回的 `exec_result` 改写、phase abort。桩仍返回 `proceed`。
