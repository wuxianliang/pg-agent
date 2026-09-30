# v15 stage 4 · protocol

Gate: `uv run python v15/protocol/test_protocol.py`（退出码 0 = 通过）

库名 `agent_v15_protocol`。这是前缀 gate 库，不是合运行时。合运行时只在 `SQL_LOAD_ORDER` 十一个文件都加载之后。

`setup_db.py` 先删掉每一个 `starts_with(datname, 'agent_v15_')` 的库（含 stage 1–3），再重建集群角色，然后 `CREATE DATABASE` 并 `load_stage(..., "protocol")`。角色语句不在 SQL 文件里。加载结束后 `v15_bootstrap` 改为 `NOLOGIN`。

## 内容

`v15_protocol.sql` 只有注释。切分与渲染不在库内，加载成功且不建表。

- `split_sql(source) -> list[str] | SplitFailure`：§6.1 词法切分。未闭合返回 `SplitFailure`，不产生部分列表。正文含 NUL 时先换成六字符 `\u0000`，`reject_code = V15_VALUE_INVALID`，不再报未闭合。
- `classify_statement(sql) -> (kind, bind_name, arg_sql, reject_code)`：顺序以 §6.2 为准。空的 `reject_code` / `bind_name` / `arg_sql` 是 `None`。
- `timeout_pragma_ms(sql)`：合法的第一行 `-- timeout:` 返回 `floor(秒 * 1000)`，否则 `None`。非法 pragma 由分类器写成 `V15_VALUE_INVALID`，已有方言/DDL/形式拒绝码时不覆盖。
- `sql_without_timeout_pragma(sql)`：执行文本去掉第一行 timeout 注释。存放文本仍保留该行。
- `render_system` / `render_inputs` / `truncate_text` / `truncate_base` / `render_base`：§6.5。`recursion_available = false` 时删去两处 `bind_invoke` 教学。长度按码点，与 `char_length` 一致。不计算 `logical_digest`。

## 本 stage 不证明

`v15_settle_llm`、attempt、迭代状态、scratch 里执行 `WITH RECURSIVE`。切分失败的结算是 stage 6，continue 是 stage 7。未加引号 `return` / `raise` 的解析器反应只打印到 gate 标准输出，不写入仓库文件，也不是第二种规范拼写。
