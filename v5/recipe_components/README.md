# v5 W3 · recipe_components

Relational `prompt_recipes` / `prompt_slots` / `prompt_parts` are the runtime
source of truth. XML is compile-time authoring only.

| | |
|---|---|
| Database | `agent_v5_recipe_components` |
| SQL | `prompt_recipe.sql` |
| pgembed change | No |

```bash
cd /Users/wxl/Projects/pg-agent
uv run python -m v5.recipe_components.setup_db
uv run python -m v5.recipe_components.test_recipe_components
```

## Gate

passed 33/33 (2026-08-28)
