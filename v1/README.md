# pg-agent v1（原始系统）

CodeAct / RLM / POML 原版，不包含 data_analysis 入口。

```bash
uv run python v1/setup_db.py    # 库：agent_fixed, agent_func, agent_rlm
uv run python v1/run_tests.py
```

共享嵌入式 Postgres 在仓库根目录 `.pgdata/`（`server.py`）。
