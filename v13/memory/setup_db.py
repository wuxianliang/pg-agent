"""Create the isolated v13 memory database and load through memory.

Hard fail-closed if the stannum extension is not available (the memory
stage depends on the post-characterize stannum library). Deployment ACL
for the engine schema lives here (same face as filter setup_db).
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql
from v13.resolve.setup_db import run_probes

DB = "agent_v13_memory"
STAGE = "memory"


def probe_extension(server) -> None:
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name='stannum'")
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        print("[fail] stannum not in pg_available_extensions")
        print("rollback: leave memory unloaded; run characterize first")
        raise SystemExit(1)


# Deployment ACL (README 台账): roles need engine-schema USAGE + the two
# owner-only-ACL scoring internals for role-executed reader chains (N2 face).
GRANTS = """
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[])
TO v13_recall, v13_resolve, v13_route;
"""


def main() -> int:
    s = get_server()
    probe_extension(s)
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    run_psql(s, DB, GRANTS)
    run_probes(s, DB)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
