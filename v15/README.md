# v15

合运行时是 `v15/load.py` 的 `SQL_LOAD_ORDER` 十个文件都加载之后。顺序：

1. `v15/schema/v15_schema.sql`
2. `v15/namespace/v15_namespace.sql`
3. `v15/config/v15_config.sql`
4. `v15/protocol/v15_protocol.sql`
5. `v15/repl/v15_repl.sql`
6. `v15/io/v15_io.sql`
7. `v15/loop/v15_loop.sql`
8. `v15/tree/v15_tree.sql`
9. `v15/govern/v15_govern.sql`
10. `v15/provider/v15_provider.sql`

跑合运行时 gate：

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL \
  UV_NO_ENV_FILE=1 \
  uv run python v15/provider/test_provider.py
```

前缀 gate 仍是 `uv run python v15/<stage>/test_<stage>.py`。退出码 0 为通过。`agent_v15_provider` 是这十个文件都加载的库。`agent_v15_govern` 与 `agent_v15_tree` 之类仍是前缀库，不是合运行时。`setup_db.py` 会删掉每一个 `agent_v15_` 库，所以 gate 要串行跑。

覆盖矩阵：`docs/reviews/v15-conformance-matrix-2026-09-29.md`。行为以 `docs/designs/v15-jaz-dev.md` rev 9 为准。
