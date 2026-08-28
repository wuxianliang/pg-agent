# W1 — plugin_taxonomy

## Purpose

建立 v4 的单一 COMMENT taxonomy、plugin registry、queue binding 和 queue-message idempotency；把 v3 的 single hardcoded queue apply 改为 catalog-driven generic dispatcher，只实现 `llm` processor。

## Pass gate

1. 新建 `agent_v4_plugin_taxonomy` 成功，setup 不调用 SQL-side model HTTP。
2. v4 runtime guard 直接调用时抛出明确 v4 error；worker 无 `http_call_llm`/`pg_net`/`pgsql-http` model-call path。
3. 合法 metadata 可 refresh；malformed JSON、missing `plugin`、wrong return type、wrong arg map、duplicate tool/queue、invalid kind 均被拒绝。
4. 失败 refresh 后 registry rows 与失败前完全一致。
5. `apply_queue_result()` 无按 queue kind 的分支；四种 kind 仅出现在 metadata validation/probe。
6. 注入的 deterministic `scripted()` script 经 generic dispatcher 完成两轮 run，最终 `SUCCESS`。
7. crash-after-read 后 visibility replay 不重复逻辑 step；duplicate `(queue,msg_id)` apply 返回 replay 且不新增 `agent_steps`。
8. provider transient failure 在 worker-local retry 后仍遵守 apply/archive transaction 和 read-count DLQ。
9. README 记录 gate 证据。

**Evidence (2026-08-28)**

- Command: `uv run python -m v4.plugin_taxonomy.test_plugin_taxonomy`
- Database: `agent_v4_plugin_taxonomy`
- Result: `58/58 passed`
- Failed gate numbers: none
- Setup load order: `v3/pg_agent_pgmq.sql` → `v4_runtime_guard.sql` → `plugin_taxonomy.sql` then `refresh_plugins()` (1 queue_handler for `llm_requests`)

## Fail gate

- worker 绕过 generic dispatcher 直接调用 v3 `apply_llm_response()`；
- SQL HTTP guard 可被正常调用；
- refresh 失败后留下空 registry 或半刷新 registry；
- replay 产生重复 step；
- test 依赖 live model/network；
- 未明确 queue message cleanup/archive 语义；
- 修改 `v3/` 或 v1/v2 文件。

None of the fail-gate conditions triggered. Queue cleanup uses `pgmq.purge_queue()`; archive happens in the same transaction as `apply_queue_result()`.

## pgembed change

No — `pgmq` and core PostgreSQL were sufficient.

## Database

`agent_v4_plugin_taxonomy`

## Status

`passed` (58/58)
