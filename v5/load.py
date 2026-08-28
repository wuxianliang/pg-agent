"""Cumulative SQL load order for v5 stages.

The first 12 entries are the same files as v4/load.py SQL_LOAD_ORDER,
still pointing at v3/ and v4/ (read-only). v5 does not copy those files
and does not import v4.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V5_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V5_ROOT.parent

# 1–12: read-only v3/v4 inputs (identical to v4/load.py lines 14–27).
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
    V5_ROOT / "prompt_taxonomy" / "prompt_taxonomy.sql",
    V5_ROOT / "recipe_components" / "prompt_recipe.sql",
    V5_ROOT / "prompt_pipeline" / "prompt_pipeline.sql",
    V5_ROOT / "named_tools" / "named_tools.sql",
    V5_ROOT / "generate_missing" / "prompt_generation.sql",
]

# Files that register COMMENT plugins; setup must refresh after each.
# Membership matches v4/load.py REFRESH_AFTER, expressed as those v4 paths.
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
    V5_ROOT / "prompt_taxonomy" / "prompt_taxonomy.sql",
    V5_ROOT / "recipe_components" / "prompt_recipe.sql",
    V5_ROOT / "generate_missing" / "prompt_generation.sql",
}

STAGE_THROUGH = {
    "kernel_freeze": 12,
    "prompt_taxonomy": 13,
    "recipe_components": 14,
    "prompt_pipeline": 15,
    "named_tools": 16,
    "generate_missing": 17,
    "integration": 17,
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
