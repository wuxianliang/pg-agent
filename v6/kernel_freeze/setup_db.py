"""Create the isolated v6 W1 database and load the inherited v5 SQL stack."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v6.load import load_stage, psql_has_row, run_psql

DB = "agent_v6_kernel_freeze"
STAGE = "kernel_freeze"


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")
    run_psql(server, DB, "CREATE EXTENSION IF NOT EXISTS vector;")
    load_stage(server, DB, STAGE)

    checks = [
        ("pgmq", "SELECT 1 FROM pg_extension WHERE extname='pgmq'"),
        ("http guard", "SELECT 1 FROM pg_proc WHERE proname='http_call_llm'"),
        ("apply_queue_result", "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'"),
        ("apply_llm_response", "SELECT 1 FROM pg_proc WHERE proname='apply_llm_response'"),
        ("assemble_prompt_messages", "SELECT 1 FROM pg_proc WHERE proname='assemble_prompt_messages'"),
        ("invoke_named_llm_tool", "SELECT 1 FROM pg_proc WHERE proname='invoke_named_llm_tool'"),
        ("visible prompt store", "SELECT 1 FROM pg_proc WHERE proname='wb_store_prompt_part'"),
        ("agent_start_session", "SELECT 1 FROM pg_proc WHERE proname='agent_start_session'"),
        ("agent_system v2", "SELECT 1 FROM prompt_recipes WHERE recipe_name='agent_system' AND version=2 AND active"),
    ]
    ok = True
    print("\n=== W1 inherited baseline ===")
    for name, sql in checks:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out)
        print(f"  {name}: {'✓' if found else '✗'}  {out.strip()[:100]!r}")
        ok = ok and found
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
