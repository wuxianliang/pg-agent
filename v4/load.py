"""Fixed cumulative SQL load order for v4 stages. v3 files are read-only inputs."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pgembed import POSTGRES_BIN_PATH

V4_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V4_ROOT.parent

# Indices are 1-based in the plan: (1) v3 base … (12) observability.
SQL_LOAD_ORDER: list[Path] = [
    AGENT_ROOT / "v3" / "pg_agent_pgmq.sql",                          # 1
    V4_ROOT / "plugin_taxonomy" / "v4_runtime_guard.sql",             # 2
    V4_ROOT / "plugin_taxonomy" / "plugin_taxonomy.sql",              # 3
    V4_ROOT / "sticky_workbench" / "workbench_core.sql",              # 4
    V4_ROOT / "sticky_workbench" / "plugin_brief_query.sql",          # 5
    V4_ROOT / "sticky_workbench" / "plugin_temp_views.sql",           # 6
    V4_ROOT / "sticky_workbench" / "plugin_sql_curator.sql",          # 7
    V4_ROOT / "queue_kinds" / "queue_kinds.sql",                      # 8
    V4_ROOT / "queue_kinds" / "plugin_async_tasks.sql",               # 9
    V4_ROOT / "subagent_fanout" / "subagent_fanout.sql",              # 10
    V4_ROOT / "session_durability" / "session_durability.sql",        # 11
    V4_ROOT / "observability_budget" / "observability_budget.sql",    # 12
]

# Files that register COMMENT plugins; setup must refresh after each.
REFRESH_AFTER = {
    V4_ROOT / "plugin_taxonomy" / "plugin_taxonomy.sql",
    V4_ROOT / "sticky_workbench" / "plugin_brief_query.sql",
    V4_ROOT / "sticky_workbench" / "plugin_temp_views.sql",
    V4_ROOT / "sticky_workbench" / "plugin_sql_curator.sql",
    V4_ROOT / "queue_kinds" / "queue_kinds.sql",
    V4_ROOT / "queue_kinds" / "plugin_async_tasks.sql",
    V4_ROOT / "subagent_fanout" / "subagent_fanout.sql",
    V4_ROOT / "session_durability" / "session_durability.sql",
    V4_ROOT / "observability_budget" / "observability_budget.sql",
}

STAGE_THROUGH = {
    "plugin_taxonomy": 3,
    "sticky_workbench": 7,
    "queue_kinds": 9,
    "subagent_fanout": 10,
    "session_durability": 11,
    "observability_budget": 12,
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
