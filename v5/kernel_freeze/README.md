# v5 W1 · kernel_freeze

Load the frozen v4 SQL stack as read-only paths (same pattern as v4 loading
`v3/pg_agent_pgmq.sql`). No SQL copies under this directory. Worker is v5-local
and does not `import v4`.

| | |
|---|---|
| Database | `agent_v5_kernel_freeze` |
| SQL | none (reads v3/v4 files via `v5/load.py`) |
| Worker | `v5/kernel_freeze/worker.py` |
| pgembed change | No |

## Commands

```bash
cd /Users/wxl/Projects/pg-agent
uv run python -m v5.kernel_freeze.setup_db
uv run python -m v5.kernel_freeze.test_kernel_freeze
```

## Gate

passed 31/31 (2026-08-28)
