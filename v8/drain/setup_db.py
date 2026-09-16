"""Create the isolated v8 G15 database and load through the drain stage.

G15 (failure-drain) adds the §3.1.1 fail_session class (3) INFRA closure. Its
SQL file sits after the cancel stage (position 14), so the stage load set
runs through it — every consumer the drain gate exercises (the shared
pre-dispatch sync, the aggregation counters, the retry-stop-reason CAS and
the effect-stage reject path's IF to_regprocedure guard) is loaded.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_drain"
STAGE = "drain"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    # G15: seed pass-through grants for the default 'drv' driver the
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
