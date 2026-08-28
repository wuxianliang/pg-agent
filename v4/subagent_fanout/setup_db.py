"""Create agent_v4_subagent_fanout and load W1–W4 overlay. Own DB only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v4.load import load_stage, psql_has_row, run_psql

DB = "agent_v4_subagent_fanout"
STAGE = "subagent_fanout"


def main() -> int:
    server = get_server()
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")
    run_psql(server, DB, "CREATE EXTENSION IF NOT EXISTS vector;")
    load_stage(server, DB, STAGE)
    print("\n=== 验证 ===")
    ok = True
    checks = [
        ("wb_spawn_agents", "SELECT 1 FROM pg_proc WHERE proname='wb_spawn_agents'"),
        ("maybe_resume_parent", "SELECT 1 FROM pg_proc WHERE proname='maybe_resume_parent'"),
        ("agent_wait_groups", "SELECT 1 FROM pg_class WHERE relname='agent_wait_groups'"),
        ("agent_wait_members", "SELECT 1 FROM pg_class WHERE relname='agent_wait_members'"),
        ("agent_wait_deliveries", "SELECT 1 FROM pg_class WHERE relname='agent_wait_deliveries'"),
        ("spawn tool",
         "SELECT count(*) FROM plugin_bindings WHERE binding_name='wb_spawn_agents'"),
    ]
    for name, sql in checks:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out) or bool(re.search(r"\n\s*1\s*\n", out))
        print(f"  {DB}.{name}: {'✓' if found else '✗'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
