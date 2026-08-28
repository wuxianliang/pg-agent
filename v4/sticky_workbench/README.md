# W2 — sticky_workbench

## Purpose

把 v2 workbench 的六个 SELECT-callable 工具放到 v3 异步 loop 中。所有 TEMP VIEW / KV 操作发生在 `AgentWorker.conn_for(run_id)` 的 sticky connection 上。

## Pass gate

1. registry 最终 exactly six workbench tool bindings，metadata 为 v4 `plugin` + `llm_tool`。
2. `render_plugin_tools()` 描述 v3 action 协议、嵌套 envelope、sticky run scope。
3. deterministic `scripted()` run 在 sticky connection 上 create view -> query view -> final。
4. 同一 `run_id` 后续 turn 能看见前一轮 view/KV；另一条 psycopg 连接看不见。
5. caller connection 的 TEMP VIEW 不是 worker fixture。
6. permanent view、TEMP table、非法标识符、DML/注释/分号、不兼容 replacement、dependent drop 均 structured error。
7. 全部 workbench 函数 `SECURITY INVOKER`，不经过 v2 `worker()`。
8. README 记录 gate 与 `pgembed change: No`。

**Evidence (2026-08-28)**

- Command: `uv run python -m v4.sticky_workbench.test_sticky_workbench`
- Database: `agent_v4_sticky_workbench`
- Result: `35/35 passed`
- Failed gate numbers: none
- Load order: (1)–(7); `refresh_plugins()` after each plugin SQL file; final llm_tool count = 6 plus 1 `llm_requests` handler

## Fail gate

Workbench tool 走 SQL HTTP、跨 backend 看见 TEMP、使用 v2 `code` 协议、直接编辑 v2/v3、cleanup/rollback 语义不清。均未触发。

## pgembed change

No — TEMP VIEW and core PostgreSQL were sufficient.

## Database

`agent_v4_sticky_workbench`

## Status

`passed` (35/35)
