# v5 W2 · prompt_taxonomy

Extend `plugin_bindings` with `prompt_slot` and `llm_tool.capability=prompt_mutation`.
Generic `apply_queue_result()` is unchanged.

| | |
|---|---|
| Database | `agent_v5_prompt_taxonomy` |
| SQL | `prompt_taxonomy.sql` |
| pgembed change | No |

```bash
cd /Users/wxl/Projects/pg-agent
uv run python -m v5.prompt_taxonomy.setup_db
uv run python -m v5.prompt_taxonomy.test_prompt_taxonomy
```

## Gate

passed 16/16 (2026-08-28)
