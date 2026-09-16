"""Create the isolated v8 G14 database and load through the full order.

G14 (concurrency / race-probe gate) adds NO SQL of its own: it reuses the
frozen G12 (`gates`) load set and exercises the lock-wait interleavings of
the already-delivered gates. The stage key `concurrency` therefore carries
the same SQL_LOAD_ORDER position as `gates`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_concurrency"
STAGE = "concurrency"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    # G14: seed pass-through grants for the default 'drv' driver the
    # positive-path fixtures use; per-test drivers seed their own rows.
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
