"""Create the isolated v8 G19a database and load through the assemble stage.

G19a (assemble) adds the §2 seam checkpoints and the two-phase assemble
manifest snapshot (v10's Plan/Bind prerequisite). Its SQL file sits right
after the grant stage (the seams consume the grant model) and before the
stream stage, so the stage load set runs through it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v8.load import load_stage, run_psql

DB = "agent_v8_assemble"
STAGE = "assemble"
DRIVERS = ("drv",)


def main() -> int:
    s = get_server()
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    # G19a: seed pass-through grants for the default 'drv' driver; the seam
    # tests seed their own constrained/revoked rows per vector.
    import psycopg2
    from v8.grant.fixtures import seed_stage_grants, STAGE_CAPABILITIES
    _conn = psycopg2.connect(s.get_uri(DB))
    try:
        # G19a: the seam capabilities join the default stage set so the
        # positive seam paths have pass-through grants; the negative
        # vectors (no grant / revoked / slice revoked / constrained) seed
        # their own rows in the test body.
        seed_stage_grants(_conn, drivers=DRIVERS,
                          capabilities=STAGE_CAPABILITIES + (
                              "recall", "fold", "env_read", "env_write",
                              "tool_resolve"))
    finally:
        _conn.close()
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
