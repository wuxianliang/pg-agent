# W4 · session_durability

目标：定义每个 run 的 DuckDB 内存会话生命周期和恢复边界。

- `temp`：绑定当前 worker；worker 丢失即 `DUCK_SESSION_LOST`，run 失败关闭。
- `run_schema`：PostgreSQL 只保存 source/view 定义、依赖和有界元数据；新 worker 重读当前源并按依赖重放，不保证历史快照。

通过门：同 run 可链式查询；不同 run 隔离；temp loss 不会静默创建空会话；run_schema 可重放且明确标记 rehydrated/degraded；子 run 不共享父 artifacts。


**状态：✅ Gate 已通过（2026-08-28）。**
