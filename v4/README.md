# pg-agent v4：staged expansion

六个 stage 严格顺序执行，每个 stage 在自己的数据库里通过 gate 后才能开始下一个。完整计划见
[docs/plans/v4-expansion-2026-08-28.md](../docs/plans/v4-expansion-2026-08-28.md)。

| 顺序 | Stage | Database | 一句话 | Status |
|---|---|---|---|---|
| W1 | [`plugin_taxonomy/`](plugin_taxonomy/) | `agent_v4_plugin_taxonomy` | COMMENT taxonomy、plugin registry、generic queue apply | passed 58/58 |
| W2 | [`sticky_workbench/`](sticky_workbench/) | `agent_v4_sticky_workbench` | v2 六个 workbench tools 移到 v3 sticky connection | passed 35/35 |
| W3 | [`queue_kinds/`](queue_kinds/) | `agent_v4_queue_kinds` | embed、sql_heavy、human_inbox 三种 queue kind | passed 38/38 |
| W4 | [`subagent_fanout/`](subagent_fanout/) | `agent_v4_subagent_fanout` | PGMQ groups 做 parent/child fan-out | passed 30/30 |
| W5 | [`session_durability/`](session_durability/) | `agent_v4_session_durability` | TEMP 与 per-run schema 两种 session lifetime 对比 | passed 20/20 |
| W6 | [`observability_budget/`](observability_budget/) | `agent_v4_observability` | bounded step metadata 与 budget enforcement | passed 21/21 |

## Run commands

```bash
cd /Users/wxl/Projects/pg-agent
uv sync
uv run python -m v4.plugin_taxonomy.test_plugin_taxonomy
uv run python -m v4.sticky_workbench.test_sticky_workbench
uv run python -m v4.queue_kinds.test_queue_kinds
uv run python -m v4.subagent_fanout.test_subagent_fanout
uv run python -m v4.session_durability.test_session_durability
uv run python -m v4.observability_budget.test_observability_budget
```

Each test module drops/recreates only its own database, then loads the cumulative SQL order through that stage. LLM HTTP is disabled in SQL by `v4_runtime_guard.sql` immediately after the v3 baseline. Tests inject `llm_fn` / `embed_fn`; they do not call live providers.

## SQL HTTP prohibition

`http_call_llm()` and `agent_run()` raise `v4 forbids SQL-side model HTTP; use the out-of-DB worker`. Workers call `apply_queue_result()`; they never call `apply_llm_response()` directly.

## pgembed decision

No pgembed change for W1–W6. Existing bundle (`pgmq`, `pgvector`, core PostgreSQL TEMP/schema/LISTEN) was sufficient. `pg_tle` remains a future packaging option only, not a runtime dependency.

## Status

All six stages passed their gates (2026-08-28).
