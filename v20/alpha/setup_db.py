"""Drop and recreate the v20 alpha database, then load its one SQL file."""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server import get_server

DB = "agent_v20_alpha"
CONTROL_ROLE = "v20_alpha_control"
WORKER_ROLE = "v20_alpha_worker"
SQL_FILE = Path(__file__).with_name("schema.sql")


def local_dsn(database: str = DB, *, user: str | None = CONTROL_ROLE) -> str:
    """Return a local Unix-domain DSN. Behavior connections use v20_alpha_control."""
    uri = get_server().get_uri(database)
    params = parse_dsn(uri)
    if not params.get("host", "").startswith("/"):
        raise ValueError("v20 alpha requires a local PostgreSQL Unix-domain connection")
    if user is not None:
        params["user"] = user
    return make_dsn(**params)


def main() -> int:
    admin = psycopg2.connect(local_dsn("postgres", user=None))
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DB)))
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
    finally:
        admin.close()

    loader = psycopg2.connect(local_dsn(user=None))
    loader.autocommit = True
    try:
        with loader.cursor() as cur:
            cur.execute(SQL_FILE.read_text(encoding="utf-8"))
            cur.execute("GRANT pg_read_all_stats TO v20_alpha_control")
    finally:
        loader.close()

    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
