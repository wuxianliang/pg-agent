# W3 — queue_kinds

## Purpose

在不修改 `apply_queue_result()` generic dispatcher 的前提下，加入 `embed`、`sql_heavy`、`human_inbox` 三种实际 queue kind，以及 WAITING/resume。

## Pass gate

1. 三个 additional queues、三个 DLQ、对应 queue handler 都注册；`apply_queue_result()` 仍无 kind branch。
2. injected embedding processor 完成 request；无 SQL HTTP、无 live provider。
3. sql-heavy 在独立 connection 执行，不能读 sticky TEMP VIEW/KV；timeout 与 structured SQL error 可验证。
4. scripted async tool 后只 emit wait，不立即 enqueue next LLM。
5. `run_state()` 报告 `WAITING_QUEUE`/`WAITING_HUMAN`，结果后只 resume 一次。
6. `human_answer()` 对 open 成功，对 missing/answered 返回 conflict。
7. duplicate queue result / duplicate human answer 不产生 duplicate logical steps。
8. pgvector availability + README `pgembed change: No`。

**Evidence (2026-08-28)**

- Command: `uv run python -m v4.queue_kinds.test_queue_kinds`
- Database: `agent_v4_queue_kinds`
- Result: `38/38 passed`
- Failed gate numbers: none
- Vector: `CREATE EXTENSION vector` succeeded on the current pgembed bundle

## Fail gate

Queue kind 写成 generic dispatcher if/else；worker poll human inbox；sql-heavy 走 sticky run connection；SQL 决定 embedding/model provider。均未触发。

## pgembed change

No — existing `pgmq`, `pgvector`, and core PostgreSQL were sufficient.

## Database

`agent_v4_queue_kinds`

## Status

`passed` (38/38)
