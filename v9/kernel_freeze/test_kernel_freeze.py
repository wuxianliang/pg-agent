"""W1 gate: v9 loads the inherited v6 SQL stack by path and keeps the generic runtime seam."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V9_ROOT = ROOT.parent
AGENT_ROOT = V9_ROOT.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v9.kernel_freeze.setup_db import DB, main as setup_db
from v9.load import SQL_LOAD_ORDER

# The first 21 entries of SQL_LOAD_ORDER must equal the v6 inherited stack,
# item by item (repo-rooted literals embedded here so the loader cannot drift).
EXPECTED_INHERITED_PREFIX = [
    "v3/pg_agent_pgmq.sql",
    "v4/plugin_taxonomy/v4_runtime_guard.sql",
    "v4/plugin_taxonomy/plugin_taxonomy.sql",
    "v4/sticky_workbench/workbench_core.sql",
    "v4/sticky_workbench/plugin_brief_query.sql",
    "v4/sticky_workbench/plugin_temp_views.sql",
    "v4/sticky_workbench/plugin_sql_curator.sql",
    "v4/queue_kinds/queue_kinds.sql",
    "v4/queue_kinds/plugin_async_tasks.sql",
    "v4/subagent_fanout/subagent_fanout.sql",
    "v4/session_durability/session_durability.sql",
    "v4/observability_budget/observability_budget.sql",
    "v5/prompt_taxonomy/prompt_taxonomy.sql",
    "v5/recipe_components/prompt_recipe.sql",
    "v5/prompt_pipeline/prompt_pipeline.sql",
    "v5/named_tools/named_tools.sql",
    "v5/generate_missing/prompt_generation.sql",
    "v6/source_ingress/duck_sources.sql",
    "v6/queue_bridge/duck_queue.sql",
    "v6/duck_tools/duck_tools.sql",
    "v6/dialect_guardrails/duck_prompt.sql",
]
EXPECTED_V9_TAIL = [
    "v9/ctx_schema/ctx_schema.sql",
    "v9/ctx_queue/ctx_queue.sql",
    "v9/ctx_lifecycle/ctx_lifecycle.sql",
]


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def relative_paths(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(AGENT_ROOT)) for p in paths]


def main() -> int:
    print("[W1] creating isolated database")
    check("setup", setup_db() == 0)

    loader_text = (V9_ROOT / "load.py").read_text()
    check("v9 loader has no runtime v6 import", not re.search(r"^\s*(from|import)\s+v6\b", loader_text, re.M))
    check("v9 loader has no runtime v5 import", not re.search(r"^\s*(from|import)\s+v5\b", loader_text, re.M))
    check("v9 loader has no runtime v4 import", not re.search(r"^\s*(from|import)\s+v4\b", loader_text, re.M))

    check("v9 inherited prefix has 21 entries", len(SQL_LOAD_ORDER[:21]) == 21)
    check(
        "v9 inherited prefix matches the v6 stack item by item",
        relative_paths(SQL_LOAD_ORDER[:21]) == EXPECTED_INHERITED_PREFIX,
        relative_paths(SQL_LOAD_ORDER[:21]),
    )
    check(
        "v9 full load order is the 21 inherited + 3 v9 overlay files",
        len(SQL_LOAD_ORDER) == 24
        and relative_paths(SQL_LOAD_ORDER[21:]) == EXPECTED_V9_TAIL,
        relative_paths(SQL_LOAD_ORDER),
    )
    check("kernel_freeze contains no copied SQL", not list(ROOT.glob("**/*.sql")))
    check("all 24 load-order paths exist", all(p.exists() for p in SQL_LOAD_ORDER), relative_paths(SQL_LOAD_ORDER))

    uri = get_server().get_uri(DB)
    import psycopg2
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            seam_checks = {
                "generic apply": "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'",
                "LLM apply": "SELECT 1 FROM pg_proc WHERE proname='apply_llm_response'",
                "prompt assembly": "SELECT 1 FROM pg_proc WHERE proname='assemble_prompt_messages'",
                "named tool dispatch": "SELECT 1 FROM pg_proc WHERE proname='invoke_named_llm_tool'",
                "visible prompt store": "SELECT 1 FROM pg_proc WHERE proname='wb_store_prompt_part'",
                "session entry": "SELECT 1 FROM pg_proc WHERE proname='agent_start_session'",
            }
            for label, sql in seam_checks.items():
                cur.execute(sql)
                check(label, cur.fetchone() is not None)

            cur.execute("SELECT count(*) FROM plugin_bindings")
            (bindings,) = cur.fetchone()
            check("plugin_bindings populated after refresh_plugins", bindings > 0, f"count={bindings}")

            cur.execute("SELECT queue_name FROM pgmq.meta")
            queues = {row[0] for row in cur.fetchall()}
            check("pgmq.meta has llm_requests", "llm_requests" in queues, sorted(queues))
            check("pgmq.meta has duck_heavy_requests", "duck_heavy_requests" in queues)

            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            (llm_before,) = cur.fetchone()
            cur.execute(
                "INSERT INTO agent_runs(run_id, question, max_steps) "
                "VALUES ('w1-v9-parked-run', 'v9 W1 parked run', 10)"
            )
            cur.execute("SELECT 1 FROM agent_runs WHERE run_id='w1-v9-parked-run'")
            check("agent_runs accepts a parked run insert", cur.fetchone() is not None)
            cur.execute("SELECT count(*) FROM agent_steps WHERE run_id='w1-v9-parked-run'")
            check("parked run has zero steps", cur.fetchone()[0] == 0)
            cur.execute("SELECT count(*) FROM pgmq.q_llm_requests")
            check("parked run enqueues no LLM request", cur.fetchone()[0] == llm_before)
            cur.execute("DELETE FROM agent_runs WHERE run_id='w1-v9-parked-run'")
            check("agent_runs parked run delete round-trips", cur.rowcount == 1)
    finally:
        conn.close()

    print("[W1] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
