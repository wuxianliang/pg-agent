"""Drop/recreate only the v23 gate database, then load its one SQL file."""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import get_server

DB = "agent_v23_minimal_loop"
CONTROL_ROLE = "v23_control"
WORKER_ROLE = "v23_worker"
SQL_FILE = Path(__file__).with_name("v23.sql")


def local_dsn(database: str = DB, *, user: str | None = CONTROL_ROLE) -> str:
    """Return a local Unix-domain DSN; v23 behavior connections use v23_control."""
    uri = get_server().get_uri(database)
    params = parse_dsn(uri)
    if not params.get("host", "").startswith("/"):
        raise ValueError("v23 requires a local PostgreSQL Unix-domain connection")
    if user is not None:
        params["user"] = user
    return make_dsn(**params)


def _probe_permissions(admin_dsn: str) -> None:
    """Check the role/database boundary before exposing the reset as ready."""
    admin = psycopg2.connect(admin_dsn)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                SELECT
                    has_database_privilege('public', %s, 'CONNECT'),
                    has_database_privilege(%s, %s, 'CONNECT'),
                    has_database_privilege(%s, %s, 'CONNECT'),
                    (SELECT rolcanlogin FROM pg_roles WHERE rolname = %s)
                """,
                (DB, CONTROL_ROLE, DB, WORKER_ROLE, DB, WORKER_ROLE),
            )
            database_values = cur.fetchone()
        if database_values != (False, True, False, False):
            raise RuntimeError(f"v23 database permission probe failed: {database_values!r}")
    finally:
        admin.close()

    target = psycopg2.connect(local_dsn(user=None))
    target.autocommit = True
    try:
        with target.cursor() as cur:
            cur.execute(
                """
                SELECT
                    has_table_privilege(%s, 'public.v23_runs', 'SELECT'),
                    has_table_privilege(%s, 'public.v23_runs', 'INSERT'),
                    has_table_privilege(%s, 'public.v23_runs', 'UPDATE'),
                    has_table_privilege(%s, 'public.v23_runs', 'DELETE'),
                    has_column_privilege(%s, 'public.v23_runs', 'status', 'UPDATE'),
                    has_column_privilege(%s, 'public.v23_runs', 'run_id', 'UPDATE'),
                    has_column_privilege(%s, 'public.v23_runs', 'parent_run_id', 'UPDATE'),
                    has_column_privilege(%s, 'public.v23_runs', 'turn_budget', 'UPDATE')
                """,
                (CONTROL_ROLE, CONTROL_ROLE, CONTROL_ROLE, CONTROL_ROLE,
                 CONTROL_ROLE, CONTROL_ROLE, CONTROL_ROLE, CONTROL_ROLE),
            )
            table_values = cur.fetchone()
        if table_values != (True, True, False, False, True, False, False, False):
            raise RuntimeError(f"v23 table permission probe failed: {table_values!r}")
    finally:
        target.close()

    control = psycopg2.connect(local_dsn(user=CONTROL_ROLE), application_name="v23_setup_probe")
    try:
        with control.cursor() as cur:
            cur.execute("SELECT session_user, current_user, 1")
            session_user, current_user, one = cur.fetchone()
        if (session_user, current_user, one) != (CONTROL_ROLE, CONTROL_ROLE, 1):
            raise RuntimeError(
                f"v23 control credential probe failed: {(session_user, current_user, one)!r}"
            )
    finally:
        control.close()

    try:
        worker = psycopg2.connect(local_dsn(user=WORKER_ROLE), connect_timeout=2)
    except psycopg2.Error:
        return
    else:
        worker.close()
        raise RuntimeError("v23_worker unexpectedly connected despite NOLOGIN/no CONNECT")


def main() -> int:
    admin_dsn = local_dsn("postgres", user=None)
    admin = psycopg2.connect(admin_dsn)
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
            cur.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(DB)))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(DB), sql.Identifier(CONTROL_ROLE)
            ))
            cur.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(DB), sql.Identifier(WORKER_ROLE)
            ))
            cur.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    finally:
        loader.close()

    _probe_permissions(admin_dsn)
    print("[ready]", DB, "(one SQL file; v23_control behavior role)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
