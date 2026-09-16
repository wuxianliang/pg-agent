"""Cumulative SQL load order for v9 stages.

The first 21 entries are the complete v6 inherited stack, still pointing at
v3/, v4/, v5/, and v6/ (read-only). v9 does not copy those SQL files and does
not import the older version packages at runtime. Entries 22-24 are the v9
context_early overlay (schema, queue, lifecycle).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V9_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V9_ROOT.parent

# 1-21: read-only v3/v4/v5/v6 inputs (identical to the v6 SQL_LOAD_ORDER,
# resolved against the same repo-rooted absolute paths).
SQL_LOAD_ORDER: list[Path] = [
    AGENT_ROOT / "v3" / "pg_agent_pgmq.sql",
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "v4_runtime_guard.sql",
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "plugin_taxonomy.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "workbench_core.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_brief_query.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_temp_views.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_sql_curator.sql",
    AGENT_ROOT / "v4" / "queue_kinds" / "queue_kinds.sql",
    AGENT_ROOT / "v4" / "queue_kinds" / "plugin_async_tasks.sql",
    AGENT_ROOT / "v4" / "subagent_fanout" / "subagent_fanout.sql",
    AGENT_ROOT / "v4" / "session_durability" / "session_durability.sql",
    AGENT_ROOT / "v4" / "observability_budget" / "observability_budget.sql",
    AGENT_ROOT / "v5" / "prompt_taxonomy" / "prompt_taxonomy.sql",
    AGENT_ROOT / "v5" / "recipe_components" / "prompt_recipe.sql",
    AGENT_ROOT / "v5" / "prompt_pipeline" / "prompt_pipeline.sql",
    AGENT_ROOT / "v5" / "named_tools" / "named_tools.sql",
    AGENT_ROOT / "v5" / "generate_missing" / "prompt_generation.sql",
    AGENT_ROOT / "v6" / "source_ingress" / "duck_sources.sql",
    AGENT_ROOT / "v6" / "queue_bridge" / "duck_queue.sql",
    AGENT_ROOT / "v6" / "duck_tools" / "duck_tools.sql",
    AGENT_ROOT / "v6" / "dialect_guardrails" / "duck_prompt.sql",
    # 22-24: v9 context_early overlay.
    V9_ROOT / "ctx_schema" / "ctx_schema.sql",
    V9_ROOT / "ctx_queue" / "ctx_queue.sql",
    V9_ROOT / "ctx_lifecycle" / "ctx_lifecycle.sql",
]

# Files that register COMMENT plugins; setup must refresh after each.
# Membership matches the v6 REFRESH_AFTER (same resolved v4/v5/v6 paths) plus
# v9/ctx_queue/ctx_queue.sql, which registers plugin_ctx_queue's COMMENT.
REFRESH_AFTER = {
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "plugin_taxonomy.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_brief_query.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_temp_views.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_sql_curator.sql",
    AGENT_ROOT / "v4" / "queue_kinds" / "queue_kinds.sql",
    AGENT_ROOT / "v4" / "queue_kinds" / "plugin_async_tasks.sql",
    AGENT_ROOT / "v4" / "subagent_fanout" / "subagent_fanout.sql",
    AGENT_ROOT / "v4" / "session_durability" / "session_durability.sql",
    AGENT_ROOT / "v4" / "observability_budget" / "observability_budget.sql",
    AGENT_ROOT / "v5" / "prompt_taxonomy" / "prompt_taxonomy.sql",
    AGENT_ROOT / "v5" / "recipe_components" / "prompt_recipe.sql",
    AGENT_ROOT / "v5" / "generate_missing" / "prompt_generation.sql",
    AGENT_ROOT / "v6" / "queue_bridge" / "duck_queue.sql",
    AGENT_ROOT / "v6" / "duck_tools" / "duck_tools.sql",
    AGENT_ROOT / "v6" / "dialect_guardrails" / "duck_prompt.sql",
    V9_ROOT / "ctx_queue" / "ctx_queue.sql",
}

STAGE_THROUGH = {
    "kernel_freeze": 21,
    "ctx_schema": 22,
    "ctx_queue": 23,
    "ctx_lifecycle": 24,
    "ctx_worker": 24,
    "integration": 24,
}


def files_through(stage: str) -> list[Path]:
    n = STAGE_THROUGH[stage]
    return SQL_LOAD_ORDER[:n]


def run_psql(server, database: str, sql: str, on_error_stop: bool = True) -> str:
    uri = server.get_uri(database)
    proc = subprocess.run(
        [str(POSTGRES_BIN_PATH / "psql"), uri, "-v",
         "ON_ERROR_STOP=" + ("1" if on_error_stop else "0"), "-q"],
        input=sql.encode(),
        capture_output=True,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0 and on_error_stop:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out


def load_stage(server, database: str, stage: str) -> None:
    for path in files_through(stage):
        if not path.exists():
            raise FileNotFoundError(f"missing SQL in load order: {path}")
        out = run_psql(server, database, path.read_text(), on_error_stop=True)
        errors = [l for l in out.splitlines() if "ERROR" in l or "FATAL" in l]
        print(f"[loaded ] {database} <- {path.name}: {'FAIL' if errors else 'OK'}")
        for e in errors:
            print(f"          {e}")
        if errors:
            raise RuntimeError(f"errors loading {path}")
        if path.resolve() in {p.resolve() for p in REFRESH_AFTER}:
            out = run_psql(server, database, "SELECT refresh_plugins();")
            print(f"[refresh] {database} after {path.name}: {out.strip() or 'OK'}")


def psql_has_row(out: str) -> bool:
    return "1 row" in out or "pgmq" in out or bool(re.search(r"\n\s*1\s*\n", out))
