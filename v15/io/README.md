# v15 stage 6 · io

Gate: `uv run python v15/io/test_io.py`（退出码 0 = 通过）

库名 `agent_v15_io`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 十一个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库，再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "io")`。角色语句不在 SQL 文件里。

## 内容

`v15_io.sql` 增加 LLM 窗口，不建表。`FakeLLM` 在 `v15/fake_llm.py`，键是 `(logical_digest, n)`。

- `v15_claim`：`runnable` 且租约空缺或已过期时 `SKIP LOCKED`，fence 加 1。抢不到返回 SQL NULL。
- `v15_begin_llm`：首次路径校验 base、算 `input_chars` 与 base digest，写 `llm_query/enter` 再 `send`。桩阶段 `v15_on_phase` 仍返回 `proceed`。`enter_messages` / `enter_overlay` 按 §4.5.1 传入 send，本函数不把 hook 消息插入 `llm_messages`。`pool_id` 为空时 attempt 记 1 与 0，不对池 `UPDATE`；非空时按缺省预留。0 行是提交类 `V15_BUDGET_EXHAUSTED`，`fatal = true`，不插入 attempt。重试不发 enter/send，复制上一行的 messages 与预留量，插入 `n+1`。
- `v15_mark_call_started`：`call_started` 从 false 提交为 true。已是 true 抛 `P1523`。
- `v15_settle_llm`：先看终态（`P1502`），再看栅栏（`P1501`）。`call_started = false` 抛 `P1523`。proceed 写助手消息和语句，迭代改为 `executing`，不 skip。切分失败的合成行在这里成为 `failed`，attempt 为 `settled`。
- `v15_reclaim_expired()`：无参数。过期且 `call_started` 的 attempt 为 `unknown` 并计入 `calls_used`；未开始的为 `failed`，只释放预留。不插入 attempt，不调用 phase。没有存活 `leased` attempt 的过期 invoke 租约收回，fence 加 1，并修理 `running` 语句。

提交类关闭走自身终态与 span 关闭。`llm_query/exit` 的 `io` 是 `{attempt_id}`，可为 JSON `null`。有父时调用点走 §4.8；本 gate 没有父场景。

FakeLLM 只在 mark 提交之后、会话没有打开的事务时调用。`40001` / `40P01` 由测试里的 worker 分类模拟为整段重试，不改写成 `P1523`。

## 本 stage 不证明

`v15_finish_exec`、空消息或散文的 continue、子 invoke 送达、hook 返回的 abort。下游 continue 是 stage 7。
