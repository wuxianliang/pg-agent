"""Create the isolated v15 govern database and load the full runtime."""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from server import get_server
from v15.load import load_stage, run_psql

DB = "agent_v15_govern"
STAGE = "govern"
ROOT = Path(__file__).resolve().parent

HOOK_ROLES = (
    "v15_hook_governance_iterations",
    "v15_hook_governance_depth",
    "v15_hook_governance_io",
    "v15_hook_governance_statement",
    "v15_hook_iteration_limit",
    "v15_hook_recursion_limit",
    "v15_hook_budget_pool",
    "v15_hook_budget_forcing",
    "v15_hook_context_window_warning",
)

OID_NAMES = (
    "v15_on_phase",
    "governance_iterations",
    "governance_depth",
    "governance_io",
    "governance_statement",
)


def _connect(server, database: str):
    conn = psycopg2.connect(server.get_uri(database))
    conn.autocommit = True
    return conn


def _drop_databases(cur) -> None:
    cur.execute(
        """
        SELECT datname
        FROM pg_database
        WHERE starts_with(datname, 'agent_v15_')
        ORDER BY datname
        """
    )
    for (name,) in cur.fetchall():
        cur.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
        )


def _terminate_role_backends(cur) -> None:
    cur.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE usename IS NOT NULL
          AND starts_with(usename, 'v15_')
          AND pid <> pg_backend_pid()
        """
    )


def _revoke_memberships(cur) -> None:
    cur.execute(
        """
        SELECT r.rolname, m.rolname
        FROM pg_auth_members a
        JOIN pg_roles r ON r.oid = a.roleid
        JOIN pg_roles m ON m.oid = a.member
        WHERE starts_with(r.rolname, 'v15_')
           OR starts_with(m.rolname, 'v15_')
        """
    )
    for role, member in cur.fetchall():
        cur.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(role), sql.Identifier(member)
            )
        )


def _drop_roles(cur) -> None:
    cur.execute(
        """
        SELECT rolname
        FROM pg_roles
        WHERE starts_with(rolname, 'v15_tool_')
           OR starts_with(rolname, 'v15_hook_')
        ORDER BY rolname
        """
    )
    names = [row[0] for row in cur.fetchall()]
    names.extend(["v15_repl", "v15_worker", "v15_owner", "v15_bootstrap"])
    for name in names:
        cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def _create_roles(cur) -> None:
    cur.execute(
        "CREATE ROLE v15_bootstrap LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    )
    cur.execute(
        "CREATE ROLE v15_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    )
    cur.execute(
        "CREATE ROLE v15_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    )
    cur.execute(
        "CREATE ROLE v15_repl NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    )
    for name in HOOK_ROLES:
        cur.execute(
            sql.SQL(
                "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
            ).format(sql.Identifier(name))
        )
    cur.execute("GRANT v15_repl TO v15_worker WITH INHERIT FALSE, SET TRUE")


def _oids(cur) -> dict[str, str]:
    cur.execute(
        """
        SELECT p.proname, p.oid::text
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'v15'
          AND p.proname = ANY(%s)
        """,
        (list(OID_NAMES),),
    )
    found = dict(cur.fetchall())
    missing = [name for name in OID_NAMES if name not in found]
    if missing:
        raise RuntimeError(f"missing functions before govern replace: {missing}")
    return found


def main() -> int:
    server = get_server()
    conn = _connect(server, "postgres")
    try:
        cur = conn.cursor()
        _drop_databases(cur)
        _terminate_role_backends(cur)
        _revoke_memberships(cur)
        _drop_roles(cur)
        _create_roles(cur)
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
    finally:
        conn.close()
    load_stage(server, DB, "tree")
    conn = _connect(server, DB)
    try:
        cur = conn.cursor()
        before = _oids(cur)
        cur.execute(
            """
            CREATE TABLE public.v15_pre_govern_oids (
              proname text PRIMARY KEY,
              oid oid NOT NULL
            )
            """
        )
        cur.executemany(
            "INSERT INTO public.v15_pre_govern_oids (proname, oid) VALUES (%s, %s::oid)",
            list(before.items()),
        )
    finally:
        conn.close()
    run_psql(server, DB, (ROOT / "v15_govern.sql").read_text(), on_error_stop=True)
    conn = _connect(server, DB)
    try:
        cur = conn.cursor()
        after = _oids(cur)
        if after != before:
            raise RuntimeError(f"oid changed across govern replace: {before} -> {after}")
        cur.execute("ALTER ROLE v15_bootstrap NOLOGIN")
    finally:
        conn.close()
    print("[ready]", DB)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
