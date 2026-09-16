"""Create the isolated v8 G4 database and load the effect stage."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_effect"
STAGE = "effect"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    # G12: seed pass-through grants for the positive-path gates — the
    # seal/dispatch/cohort authorization is live from G12; subject
    # resolution goes through each session's driver, unconstrained rows
    # (negative vectors seed their own rows in the test bodies).
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
