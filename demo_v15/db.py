"""Idempotent roles, one named database, full v15 load. Never drops gate databases."""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import get_server
from v15.load import load_stage
from v15.provider.support import FLASH_SCOPE, seed_flash_profile
from v15.worker import connect_worker as connect_worker_dsn

from task import CALLS_LIMIT, COST_LIMIT_TEXT

DEFAULT_DB = "agent_demo_v15"
_DB_NAME = re.compile(r"^agent_demo_v15(?:_[a-z0-9]+)?$")
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
_ROLE_SQL = {
    "v15_bootstrap": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
    "v15_owner": "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
    "v15_worker": "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
    "v15_repl": "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
}


class WorkerUserError(RuntimeError):
    pass


def check_name(dbname: str) -> str:
    if not isinstance(dbname, str) or _DB_NAME.fullmatch(dbname) is None:
        raise ValueError(dbname)
    return dbname


def connect_admin(server):
    conn = psycopg2.connect(server.get_uri("postgres"))
    conn.autocommit = True
    return conn


def connect_super(server, dbname: str):
    conn = psycopg2.connect(server.get_uri(check_name(dbname)))
    conn.autocommit = False
    return conn


def connect_worker(server, dbname: str):
    return connect_worker_dsn(server.get_uri(check_name(dbname)))


def _role_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    return cur.fetchone() is not None


def _create_role(cur, name: str, attrs: str) -> bool:
    if _role_exists(cur, name):
        return False
    cur.execute(
        sql.SQL("CREATE ROLE {} " + attrs).format(sql.Identifier(name))
    )
    return True


def ensure_roles(cur) -> bool:
    made = _create_role(cur, "v15_bootstrap", _ROLE_SQL["v15_bootstrap"])
    _create_role(cur, "v15_owner", _ROLE_SQL["v15_owner"])
    _create_role(cur, "v15_worker", _ROLE_SQL["v15_worker"])
    _create_role(cur, "v15_repl", _ROLE_SQL["v15_repl"])
    for name in HOOK_ROLES:
        _create_role(cur, name, "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
    cur.execute(
        """
        SELECT 1
        FROM pg_auth_members a
        JOIN pg_roles r ON r.oid = a.roleid
        JOIN pg_roles m ON m.oid = a.member
        WHERE r.rolname = 'v15_repl' AND m.rolname = 'v15_worker'
        """
    )
    if cur.fetchone() is None:
        cur.execute("GRANT v15_repl TO v15_worker WITH INHERIT FALSE, SET TRUE")
    return made


def terminate_database(cur, dbname: str) -> None:
    cur.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = %s
          AND pid <> pg_backend_pid()
        """,
        (dbname,),
    )


def drop_database(server, dbname: str) -> None:
    dbname = check_name(dbname)
    conn = connect_admin(server)
    try:
        cur = conn.cursor()
        terminate_database(cur, dbname)
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone() is not None:
            cur.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname))
            )
    finally:
        conn.close()


def database_exists(server, dbname: str) -> bool:
    conn = connect_admin(server)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (check_name(dbname),))
        return cur.fetchone() is not None
    finally:
        conn.close()


def _nologin_bootstrap(server, created_bootstrap: bool, setup_error: BaseException | None) -> None:
    try:
        conn = connect_admin(server)
        try:
            cur = conn.cursor()
            if not created_bootstrap and not _role_exists(cur, "v15_bootstrap"):
                return
            cur.execute("ALTER ROLE v15_bootstrap NOLOGIN")
        finally:
            conn.close()
    except Exception:
        if setup_error is None:
            raise


def setup(dbname: str = DEFAULT_DB):
    dbname = check_name(dbname)
    server = get_server()
    created_bootstrap = False
    setup_error: BaseException | None = None
    try:
        conn = connect_admin(server)
        try:
            cur = conn.cursor()
            created_bootstrap = _create_role(cur, "v15_bootstrap", _ROLE_SQL["v15_bootstrap"])
            ensure_roles(cur)
            terminate_database(cur, dbname)
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is not None:
                cur.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname))
                )
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        finally:
            conn.close()
        load_stage(server, dbname, "provider")
        return server
    except BaseException as exc:
        setup_error = exc
        raise
    finally:
        _nologin_bootstrap(server, created_bootstrap, setup_error)


def seed_and_pool(conn) -> str:
    pool_id = str(uuid.uuid4())

    def write(cur) -> None:
        seed_flash_profile(cur)
        cur.execute(
            """
            INSERT INTO v15.budget_pools (pool_id, calls_limit, cost_limit)
            VALUES (%s::uuid, %s, %s::numeric)
            """,
            (pool_id, CALLS_LIMIT, COST_LIMIT_TEXT),
        )

    cur = conn.cursor()
    try:
        write(cur)
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        if exc.pgcode != "42501":
            raise
        cur.execute("SET ROLE v15_owner")
        write(cur)
        cur.execute("RESET ROLE")
        conn.commit()
    return pool_id


def worker_identity(conn) -> tuple[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT session_user::text, current_user::text")
    session_user, current_user = cur.fetchone()
    conn.rollback()
    return session_user, current_user


def require_worker(conn) -> None:
    session_user, current_user = worker_identity(conn)
    if session_user != "v15_worker" or current_user != "v15_worker":
        raise WorkerUserError(session_user)


def flash_model(conn) -> str | None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.llm->>'model'
        FROM v15.config_scopes s
        JOIN v15.config_profiles p ON p.profile_id = s.profile_id
        WHERE s.scope_id = %s::uuid
        """,
        (FLASH_SCOPE,),
    )
    row = cur.fetchone()
    conn.rollback()
    return None if row is None else row[0]


def abandon_installed(conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT to_regprocedure(
          'v15.v15_provider_abandon(uuid,bigint,bigint,text,jsonb)'
        ) IS NOT NULL
        """
    )
    ok = bool(cur.fetchone()[0])
    conn.rollback()
    return ok


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    server = get_server()
    if "--drop-only" in argv:
        name = DEFAULT_DB
        idx = argv.index("--drop-only")
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            name = argv[idx + 1]
        drop_database(server, name)
        print("dropped")
        return 0
    setup(DEFAULT_DB)
    conn = connect_super(server, DEFAULT_DB)
    try:
        seed_and_pool(conn)
        model = flash_model(conn)
        installed = abandon_installed(conn)
    finally:
        conn.close()
    if model != "deepseek-flash" or not installed:
        print("fail open_failed", file=sys.stderr)
        return 1
    worker = connect_worker(server, DEFAULT_DB)
    try:
        require_worker(worker)
    except WorkerUserError:
        print("fail open_failed", file=sys.stderr)
        return 1
    finally:
        worker.close()
    print("[ready]", DEFAULT_DB)
    print("session_user=v15_worker")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
