"""Create agent_v4_session_durability and load W1–W5 overlay. Own DB only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v4.load import load_stage, psql_has_row, run_psql

DB = "agent_v4_session_durability"
STAGE = "session_durability"


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
        ("agent_start_session", "SELECT 1 FROM pg_proc WHERE proname='agent_start_session'"),
        ("cleanup_run_session", "SELECT 1 FROM pg_proc WHERE proname='cleanup_run_session'"),
        ("session_mode col",
         "SELECT 1 FROM information_schema.columns "
         "WHERE table_name='agent_runs' AND column_name='session_mode'"),
    ]:
        out = run_psql(server, DB, sql + ";")
        found = psql_has_row(out)
        print(f"  {DB}.{name}: {'✓' if found else '✗'}  {out.strip()[:80]!r}")
        ok = ok and found
    print("\n全部就绪" if ok else "\n有缺失对象！")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
