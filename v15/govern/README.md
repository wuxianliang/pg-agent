# v15 stage 9 · govern

Gate: `uv run python v15/govern/test_govern.py`（退出码 0 = 通过）

库名 `agent_v15_govern`。`setup_db.py` 先加载到 tree，记下 `v15_on_phase` 与四个治理 handler 的 oid，再执行 `v15_govern.sql`，断言 oid 未变。这九个文件只是 govern 前缀；stage 10 provider 加载后才是合运行时。

## 内容

`v15_on_phase` 在同一签名上 `CREATE OR REPLACE`。本目录是前缀 gate；完整合运行时在 `v15/provider`。它按 ordinal 调 hook，校验效应闭集，合成后按 §9.6 落地。`llm_query/send` 的预留是第一笔落库；0 行只返回 `V15_BUDGET_EXHAUSTED`，不写效应。四个治理 handler 替换原桩。五个可选 hook 在这里新建，并插入 `hook_defs`。

## 不在本文件

角色语句在 `setup_db.py`。效应落地不另设函数。前序 SQL 不 `DROP` 这些函数。
