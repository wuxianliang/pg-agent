"""Create the isolated v13 mgraph_assembly database and load through
mgraph_assembly (16 files).

Hard fail-closed if the stannum extension is not available (the
mgraph_assembly stage inherits the post-characterize stannum library via
the mgraph prefix; same face as memory/summary/mgraph setup_db).
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql
from v13.resolve.setup_db import run_probes

DB = "agent_v13_mgraph_assembly"
STAGE = "mgraph_assembly"


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
        print("rollback: leave mgraph_assembly unloaded; run characterize first")
        raise SystemExit(1)


# Deployment ACL (same face as memory/summary/mgraph setup_db): roles need
# engine-schema USAGE + the two owner-only-ACL scoring internals for
# role-executed reader chains (prefix files 9-11 consume them).
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
