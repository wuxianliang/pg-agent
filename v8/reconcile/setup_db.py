"""Create the isolated v8 G18 database and load through the reconcile stage.

G18 (reconcile) adds the §3.1.1 driver-switch positive protocol (the
session_switch_intents companion table, the driver switch capability
declarations and the unified v_reconcile entry). Its SQL file sits between
the drain and compat stages, so the stage load set runs through it — every
consumer the gate exercises (the quiescing guards in effect/retry, the
takeover controlled edge, the compat switch routing, the compact lock
coexistence and the fork provenance) is loaded.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_reconcile"
STAGE = "reconcile"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    # G18: seed pass-through grants for the default 'drv' driver the
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
