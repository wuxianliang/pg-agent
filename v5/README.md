# pg-agent v5：SQL slot assembly and generate-then-retrieve

Seven stages, each in its own database. v3/v4 SQL is loaded as **read-only
paths** (same pattern as v4 reading `v3/pg_agent_pgmq.sql`). Worker code is
v5-local and does not `import v4`. LLM HTTP stays out of SQL.

Plan: [docs/plans/v5-prompt-assembly-2026-08-28.md](../docs/plans/v5-prompt-assembly-2026-08-28.md).

| 顺序 | Stage | Database | Status |
|---|---|---|---|
| W1 | [`kernel_freeze/`](kernel_freeze/) | `agent_v5_kernel_freeze` | passed 31/31 |
| W2 | [`prompt_taxonomy/`](prompt_taxonomy/) | `agent_v5_prompt_taxonomy` | passed 16/16 |
| W3 | [`recipe_components/`](recipe_components/) | `agent_v5_recipe_components` | passed 33/33 |
| W4 | [`prompt_pipeline/`](prompt_pipeline/) | `agent_v5_prompt_pipeline` | passed 14/14 |
| W5 | [`named_tools/`](named_tools/) | `agent_v5_named_tools` | passed 9/9 |
| W6 | [`generate_missing/`](generate_missing/) | `agent_v5_generate_missing` | passed 14/14 |
| W7 | [`integration/`](integration/) | `agent_v5_integration` | passed 8/8 |

## Commands

```bash
cd /Users/wxl/Projects/pg-agent
uv sync

uv run python -m v5.kernel_freeze.setup_db
uv run python -m v5.kernel_freeze.test_kernel_freeze

uv run python -m v5.prompt_taxonomy.setup_db
uv run python -m v5.prompt_taxonomy.test_prompt_taxonomy

uv run python -m v5.recipe_components.setup_db
uv run python -m v5.recipe_components.test_recipe_components

uv run python -m v5.prompt_pipeline.setup_db
uv run python -m v5.prompt_pipeline.test_prompt_pipeline

uv run python -m v5.named_tools.setup_db
uv run python -m v5.named_tools.test_named_tools

uv run python -m v5.generate_missing.setup_db
uv run python -m v5.generate_missing.test_generate_missing

uv run python -m v5.integration.setup_db
uv run python -m v5.integration.test_v5
```

If any command fails, stop. Do not begin the next stage, do not reuse another
stage database, and do not modify v1–v4 or pgembed.

## Behaviour

- `prepare_llm_request()` assembles PGMQ `messages` from ordered SQL slots.
- Missing required stored parts: first **visible** `llm_requests` turn writes
  them via named `wb_store_prompt_part`. User question is a hint.
- Generated **role/task** are globally reused for the same
  `(recipe_name, recipe_version)` (first writer wins).
- After W5, `action` may be `execute_sql` or a registered `wb_*` name.

## pgembed change

No.
