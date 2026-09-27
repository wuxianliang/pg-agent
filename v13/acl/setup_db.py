"""Create the isolated v13 acl database and load through stage 23."""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v13.load import load_stage, run_psql

ROOT = Path(__file__).resolve().parent
DB = "agent_v13_acl"

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


def prepare(server) -> None:
    probe_extension(server)
    run_psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    run_psql(server, "postgres", f"CREATE DATABASE {DB};")
    load_stage(server, DB, "catalog")
    run_psql(server, DB, GRANTS)


def apply_acl(server) -> None:
    run_psql(server, DB, (ROOT / "v13_acl.sql").read_text())


def main() -> int:
    s = get_server()
    prepare(s)
    apply_acl(s)
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
