# v15 stage 13 · tools

Gate: `uv run python v15/tools/test_tools.py`（退出码 0 = 通过）。只用 FakeLLM / FakeTool，不开网络。

库名 `agent_v15_tools`。`load_stage(..., "tools")` 加载全部十三个 SQL 文件。这是合运行时库。更早的 `agent_v15_*` 仍是前缀库。`setup_db.py` 会删掉每一个 `agent_v15_` 库，所以 gate 要串行跑。

本 stage 是「其后不得加表」的唯一例外：追加 `tool_requests` 与 `tool_attempts`。`v15_tools.sql` 是 `SQL_LOAD_ORDER` 末项。`invokes.status` 增加 `tool_wait`（不是 `suspended`，无子 invoke，不可 claim）。规范语句 `SELECT jaz.bind_tool('<bind_ident>', '<tool_name>', <jsonb-expr>);`。三码：`V15_TOOL_BINDING`/`P1543`、`V15_TOOL_FAILED`/`P1544`、`V15_TOOL_EXHAUSTED`/`P1545`。含 `bind_tool` / `tool_wait` 的树导出为 `P1524`。

Python `FakeTool` 在 `v15/fake_tool.py`，与 FakeLLM 并列，不进装载序。只在 `call_started` 已提交、会话无打开事务时调用。默认未注册名返回 `{"ok": False}`。worker 把不可 JSON 编码或非规范 `ok` 形状收成 `{"ok":false}` 再 settle（有意收窄 SQL 侧 P1524 会留 leased attempt）。`Classification` 相等是五字段。gate 与 FakeTool 不建 socket。
