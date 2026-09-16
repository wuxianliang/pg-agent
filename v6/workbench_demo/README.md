# v6 workbench_demo · Streamlit 演示页

在一个页面里人工驱动 W9 集成链路，看 v6 的实际效果：

```text
① invoke_named_llm_tool (PG named tool, 写 duck_operations 元数据)
② duck_heavy_requests (PGMQ 消息)
③ DuckDBWorkerProcessor (库外 worker, DuckDB 真正执行)
④ apply_queue_result (结果写回 PG, 更新 duck_artifacts / op_seq)
```

页面同时扮演「模型」（调 named tool）和「worker」（跑 DuckDB processor）两个角色。

## 启动

```bash
uv run streamlit run v6/workbench_demo/app.py
```

首次打开后的操作顺序：

1. 侧栏勾选「我确认要重建数据库」→ 点 **初始化 / 重置数据库**（重建 `agent_v6_integration` 并加载 21 个 SQL）。
2. 点 **播种演示数据**（生成 `sales` 72 行 + `regions` 4 行，并自动进入白名单）。
3. **创建 run**（默认 `temp` 模式）。
4. 「工具调用」页点 **一键演示链**，或手动选择 `wb_duck_*` 工具执行。

## 页面结构

| 区域 | 内容 |
|---|---|
| 💬 对话 | **真 LLM 对话**：每条提问 = 一个 agent run，模型自主调 wb_duck_* 工具，思考/工具/结果实时渲染 |
| 侧栏 · LLM | api_uri / model / api_key（默认 DeepSeek，key 取环境变量 DEEPSEEK_API_KEY） |
| 侧栏 · 数据库 | 建库/重置、播种、白名单（修改会重建 worker，temp 会话按 LOST 处理） |
| 侧栏 · Worker | 进程内 `DuckDBWorkerProcessor`；worker_id 可改 |
| 侧栏 · Agent Run | run 元数据、workbench 会话状态（NEW/OPEN/LOST/TERMINAL）、op_seq 进度 |
| 侧栏 · 模拟 worker 崩溃 | 关闭 DuckDB 会话并标记 LOST，验证 temp fail-closed |
| 🛠 工具调用 | 7 个 `wb_duck_*` 工具表单 + 一键演示链；每次调用展开四段链路的真实 JSON |
| 📦 Artifacts | `duck_artifacts`：source/view、依赖、generation、完整定义 |
| 🧾 Operations | `duck_operations`：op_seq、状态、耗时、错误类型 |
| 📈 队列与预算 | PGMQ 深度、DLQ、`DuckBudget` 全部硬上限、操作状态分布 |

## 已演示的关键语义

- **enqueue-only 工具**：`wb_duck_*` 在 PG 侧只校验+写元数据+发 PGMQ，DuckDB 查询全部在库外执行。
- **op_seq 顺序门**：操作必须按 `last_completed_op_seq + 1` 依次 apply。
- **依赖保护删除**：先删被依赖的 source 会被 `DUCK_DEPENDENCY_EXISTS` 拒绝（无 CASCADE）。
- **temp 会话 fail-closed**：worker 崩溃/进程重启后 run 标记 LOST，不会静默开空会话。

注意：页面刷新（浏览器 F5）不影响进程内 DuckDB 会话；但 Streamlit 进程重启会让所有 temp 会话变 LOST——这正是 v6 的设计语义。
