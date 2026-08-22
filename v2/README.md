# pg-agent v2（数据分析系统）

独立库 `da_agent`，不 DROP v1 的库。

```bash
uv run python v2/setup_db.py
uv run python v2/test_data_analysis.py
```

入口：`SELECT agent_run_data_analysis('问题');`
循环：共用 `rlm_loop`，`paradigm=data_analysis` 时用 `make_da_prompt`，且必须先成功 SELECT 才能交卷。
