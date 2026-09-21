"""Create the isolated v13 characterize database and load through characterize.

Hard fail-closed if the text-search extension is not in pg_available_extensions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql
from v13.resolve.setup_db import run_probes

DB = "agent_v13_characterize"
STAGE = "characterize"


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
        print("[fail] text-search extension not in pg_available_extensions")
        print("rollback: leave characterize unloaded; T0 tsvector remains")
        raise SystemExit(1)


def main() -> int:
    s = get_server()
    probe_extension(s)
    run_psql(s, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(s, "postgres", f"CREATE DATABASE {DB};")
    load_stage(s, DB, STAGE)
    run_probes(s, DB)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
