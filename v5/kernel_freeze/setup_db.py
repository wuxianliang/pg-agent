"""Create agent_v5_kernel_freeze and load the frozen v4 SQL stack. Own DB only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v5.load import load_stage, psql_has_row, run_psql

DB = "agent_v5_kernel_freeze"
STAGE = "kernel_freeze"


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")
    run_psql(server, DB, "CREATE EXTENSION IF NOT EXISTS vector;")
    load_stage(server, DB, STAGE)
    print("\n=== 验证 ===")
    ok = True
    for name, sql in [
        ("http_call_llm", "SELECT 1 FROM pg_proc WHERE proname='http_call_llm'"),
        ("apply_queue_result", "SELECT 1 FROM pg_proc WHERE proname='apply_queue_result'"),
        ("apply_llm_response", "SELECT 1 FROM pg_proc WHERE proname='apply_llm_response'"),
        ("emit_step", "SELECT 1 FROM pg_proc WHERE proname='emit_step'"),
        ("run_budget", "SELECT 1 FROM pg_proc WHERE proname='run_budget'"),
        ("record_budget_step", "SELECT 1 FROM pg_proc WHERE proname='record_budget_step'"),
        ("wb_spawn_agents", "SELECT 1 FROM pg_proc WHERE proname='wb_spawn_agents'"),
        ("wb_request_human", "SELECT 1 FROM pg_proc WHERE proname='wb_request_human'"),
        ("steps.meta",
         "SELECT 1 FROM information_schema.columns "
         "WHERE table_name='agent_steps' AND column_name='meta'"),
    ]:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out)
        print(f"  {DB}.{name}: {'✓' if found else '✗'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
