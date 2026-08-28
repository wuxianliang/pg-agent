# W6 · duck_tools

目标：把 InfiniSQL 核心工作台能力暴露为 enqueue-only named tools。

计划工具：
- `wb_duck_register`
- `wb_duck_query`
- `wb_duck_brief_query`
- `wb_duck_list`
- `wb_duck_columns`
- `wb_duck_show_create`
- `wb_duck_drop`

所有工具从 `agent_current_run_id()` 取得 run，不接受模型传入 run_id；SQL 函数不执行 DuckDB、不连接外部源，只写 operation、发送 PGMQ 并返回 v5 能识别的嵌套 defer 结果。
