"""Create the isolated v8 G12 database and load through the full order."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_gates"
STAGE = "gates"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    # G12: seed pass-through grants for the positive-path fixtures that use
    # the default 'drv' driver (per-test custom drivers seed their own
    # rows in the test bodies).
    import psycopg2
    from v8.grant.fixtures import seed_stage_grants
    _conn = psycopg2.connect(s.get_uri(DB))
    try:
        seed_stage_grants(_conn, drivers=DRIVERS)
    finally:
        _conn.close()
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
