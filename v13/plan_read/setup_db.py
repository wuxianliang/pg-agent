"""Create a one-shot plan_read database. Never DROP an existing name."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql

ROOT = Path(__file__).resolve().parent
DB = f"ll_plan_read_{os.getpid()}"
CREATED = False

GRANTS = """
GRANT USAGE ON SCHEMA stannum TO v13_recall, v13_resolve, v13_route;
GRANT EXECUTE ON FUNCTION
  stannum.score_bound(text,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.score_bound_indexed(tid,text,integer,integer,integer,real,real,real,text[],text[]),
  stannum.tokenize(text,text,text,text,text,integer,text,text)
TO v13_recall, v13_resolve, v13_route;
"""


def probe_extension(server) -> None:
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM pg_available_extensions "
            "WHERE name IN ('stannum','pg_jsonschema')")
        found = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    missing = {"stannum", "pg_jsonschema"} - found
    if missing:
        print("[fail] missing extensions:", ",".join(sorted(missing)))
        raise SystemExit(1)


def name_exists(server) -> bool:
    conn = psycopg2.connect(server.get_uri("postgres"))
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def main() -> int:
    global CREATED
    if DB.startswith("agent_v13_") or DB == "agent_v13_longloop_p0_probe":
        print("[refuse] illegal database name", DB)
        return 1
    server = get_server()
    probe_extension(server)
    if name_exists(server):
        print("[refuse] database exists, not dropping", DB)
        return 1
    run_psql(server, "postgres", f'CREATE DATABASE "{DB}";')
    CREATED = True
    load_stage(server, DB, "plan_read")
    run_psql(server, DB, GRANTS)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
