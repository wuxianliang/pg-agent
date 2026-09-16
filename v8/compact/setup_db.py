"""Create the isolated v8 G17 database and load through the compact stage.

G17 (compact) appends its SQL at the END of the load order (no mid-order
insertion), so its stage load set is the full file list — the compact gate
exercises the seal/dispatch/cohort paths it guards with to_regclass, the
shared pre-dispatch sync it relies on for the terminal abort, and the
internal_op_audits carrier created by the G16 audit stage.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_compact"
STAGE = "compact"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    import psycopg2
    from v8.grant.fixtures import STAGE_WORKSPACE, seed_grant, seed_stage_grants
    _conn = psycopg2.connect(s.get_uri(DB))
    try:
        sid = seed_stage_grants(_conn, drivers=DRIVERS)
        # The G17 commands authorize on the `compact` capability (§3.3 step
        # 1). The default stage capability set does not include it, so seed
        # one permissive compact grant per driver on the same slice.
        for drv in DRIVERS:
            seed_grant(_conn, f"g-stage-{drv}-compact", STAGE_WORKSPACE, sid,
                       "driver", drv, "compact")
    finally:
        _conn.close()
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
