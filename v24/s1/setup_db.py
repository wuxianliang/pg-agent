"""Disposable, exact-identity PostgreSQL fixture for v24/s1."""
from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import os
import re
import secrets
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import (
    TRANSACTION_STATUS_INTRANS,
    make_dsn,
    parse_dsn,
)

ROOT = Path(__file__).resolve().parent
_NAME_RE = re.compile(r"^v24_s1_([0-9]+)_([0-9a-f]{12})$")
_GROUPS = ("v24_owner", "v24_admin", "v24_service", "v24_operator")
_ROLE_GROUPS = {
    "owner": "v24_owner",
    "admin": "v24_admin",
    "service": "v24_service",
    "operator": "v24_operator",
}
_LOCK_KEY = 0x5632345331

# Script execution starts at the worktree root in the documented command.
_REPO_ROOT = ROOT.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from v24.load import (  # noqa: E402
    CANONICAL_ORDER,
    SQL_LOAD_ORDER,
    load_stage,
    self_check_manifest,
    validate_manifest,
)


def validate_local_dsn(dsn: str, expected_socket: str) -> dict[str, str]:
    """Reject TCP, fallback, multi-host, and libpq service-indirected DSNs."""
    params = parse_dsn(dsn)
    host = params.get("host", "")
    if (
        not host.startswith("/")
        or "," in host
        or Path(host).resolve() != Path(expected_socket).resolve()
    ):
        raise ValueError("v24/s1 requires the active pgembed Unix socket host")
    if any(key in params for key in ("hostaddr", "service", "servicefile")):
        raise ValueError("hostaddr and libpq service indirection are forbidden")
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise ValueError("libpq hostaddr/service environment overrides are forbidden")
    if "," in params.get("port", ""):
        raise ValueError("multiple PostgreSQL ports are forbidden")
    return params


_setup_process = None
_setup_endpoint = None


def _close_server_helper(*, timeout: float = 2) -> None:
    """Close the private pgembed helper, escalating only if it does not exit."""
    global _setup_process, _setup_endpoint
    process = _setup_process
    if process is None:
        return
    errors = []
    try:
        if process.stdin is not None:
            process.stdin.close()
    except Exception as exc:
        errors.append(exc)

    code = None
    forced = False
    for sig in (None, signal.SIGTERM, signal.SIGKILL):
        if sig is not None:
            forced = True
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        try:
            code = process.wait(timeout=timeout)
            break
        except subprocess.TimeoutExpired:
            continue
    if code is None:
        raise RuntimeError("v24/s1 pgembed helper could not be reaped")

    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        pass
    else:
        forced = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        errors.append(RuntimeError("v24/s1 pgembed helper left a live process-group member"))

    _setup_process = _setup_endpoint = None
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception as exc:
                errors.append(exc)
    if forced or code != 0 or errors:
        failure = RuntimeError(f"v24/s1 pgembed helper cleanup failed: forced={forced}, exit={code}")
        for error in errors:
            failure.add_note(repr(error))
        raise failure


def _atexit_server_helper() -> None:
    try:
        _close_server_helper()
    except BaseException as exc:
        print(
            f"[failed] pgembed helper cleanup: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)


atexit.register(_atexit_server_helper)


@contextlib.contextmanager
def server_helper_scope():
    """Report helper cleanup failures while preserving a primary exception."""
    primary_error = None
    try:
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            _close_server_helper()
        except BaseException as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(f"pgembed helper cleanup failed: {cleanup_error!r}")


def _server_helper() -> None:
    """Start pgembed in a child process and retain its handle until EOF."""
    from server import get_server

    server = None
    primary_error = None

    def terminate(signum, frame):
        raise SystemExit(128 + signum)

    old_handler = signal.signal(signal.SIGTERM, terminate)
    try:
        server = get_server()
        info = server.get_postmaster_info()
        if info is None or info.socket_dir is None or info.port is None:
            raise RuntimeError("pgembed did not report its active Unix endpoint")
        print(
            json.dumps(
                {
                    "uri": server.get_uri("postgres"),
                    "socket": str(info.socket_dir),
                    "port": info.port,
                }
            ),
            flush=True,
        )
        sys.stdin.read()
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            if server is not None:
                server.cleanup()
        except BaseException as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(f"pgembed cleanup failed: {cleanup_error!r}")
        finally:
            signal.signal(signal.SIGTERM, old_handler)


def _read_helper_endpoint(process, *, timeout: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise RuntimeError("v24/s1 pgembed helper endpoint deadline exceeded")
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError("v24/s1 pgembed helper exited before reporting endpoint")
        data.extend(chunk)
        if len(data) > 4096:
            raise RuntimeError("v24/s1 pgembed endpoint exceeds size limit")
    return json.loads(data.split(b"\n", 1)[0])


def _server_and_base_dsn() -> tuple[Any, dict[str, str]]:
    """Start or reuse one private helper and attest its Unix socket endpoint."""
    global _setup_process, _setup_endpoint
    try:
        if _setup_process is None:
            _setup_process = subprocess.Popen(
                ["uv", "run", "python", "v24/s1/setup_db.py", "--server-helper"],
                cwd=_REPO_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                start_new_session=True,
            )
            _setup_endpoint = _read_helper_endpoint(_setup_process)
        if _setup_process.poll() is not None:
            raise RuntimeError("v24/s1 pgembed helper exited while fixture was live")

        endpoint = _setup_endpoint
        params = validate_local_dsn(endpoint["uri"], endpoint["socket"])
        uri_params = parse_dsn(endpoint["uri"])
        params["port"] = str(endpoint["port"])
        host = Path(params["host"])
        if not host.is_dir() or not (host / f".s.PGSQL.{params['port']}").exists():
            raise RuntimeError("v24/s1 endpoint does not identify an active Unix socket")
        if "port" in uri_params and int(uri_params["port"]) != endpoint["port"]:
            raise RuntimeError("v24/s1 URI port differs from pgembed's active port")
        params.pop("dbname", None)
        return _setup_process, params
    except BaseException as exc:
        try:
            _close_server_helper()
        except BaseException as cleanup_error:
            exc.add_note(f"pgembed startup cleanup failed: {cleanup_error!r}")
        raise


def _dsn(params: dict[str, str], database: str, *, user: str | None = None) -> str:
    result = dict(params, dbname=database)
    if user is not None:
        result["user"] = user
    dsn = make_dsn(**result)
    validate_local_dsn(dsn, params["host"])
    return dsn


def _new_name() -> str:
    return f"v24_s1_{os.getpid()}_{secrets.token_hex(6)}"


def _validate_name(name: str) -> None:
    match = _NAME_RE.fullmatch(name)
    if match is None or int(match.group(1)) != os.getpid():
        raise ValueError(f"refusing to manage a database outside this fixture process: {name!r}")


def _object_oid(conn, query: str, value: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(query, (value,))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def _database_oid(conn, name: str) -> int | None:
    return _object_oid(
        conn,
        "SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=%s",
        name,
    )


def _role_state(conn, role: str):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT oid::bigint, rolsuper, rolinherit, rolcreaterole,
                      rolcreatedb, rolcanlogin, rolreplication, rolbypassrls
                 FROM pg_catalog.pg_roles WHERE rolname=%s""",
            (role,),
        )
        return cur.fetchone()


def _create_or_check_group(conn, group: str) -> tuple[int, bool]:
    state = _role_state(conn, group)
    created = state is None
    if created:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(group))
            )
        state = _role_state(conn, group)
    expected = (False, False, False, False, False, False, False)
    if state is None or tuple(state[1:]) != expected:
        raise RuntimeError(f"existing role {group} is not the expected inert NOLOGIN group")
    return int(state[0]), created


def _drop_database_exact(admin_dsn: str, name: str, oid: int) -> None:
    _validate_name(name)
    with contextlib.closing(psycopg2.connect(admin_dsn)) as conn:
        conn.autocommit = True
        current = _database_oid(conn, name)
        if current is None:
            return
        if current != oid:
            raise RuntimeError(f"refusing database cleanup: OID changed for {name} ({current} != {oid})")
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _drop_role_exact(
    admin_dsn: str,
    role: str,
    oid: int,
    *,
    alias: str | None = None,
    database_name: str | None = None,
    group: bool = False,
) -> None:
    if alias is not None:
        if (
            alias not in _ROLE_GROUPS
            or database_name is None
            or role != f"{database_name}_{alias}"
        ):
            raise ValueError(f"not a fixture LOGIN role: {role}")
    elif not group or role not in _GROUPS:
        raise ValueError(f"not a fixture group role: {role}")

    with contextlib.closing(psycopg2.connect(admin_dsn)) as conn:
        conn.autocommit = True
        state = _role_state(conn, role)
        if state is None:
            return
        expected = (
            (False, True, False, False, True, False, False)
            if alias is not None
            else (False, False, False, False, False, False, False)
        )
        if int(state[0]) != oid or tuple(state[1:]) != expected:
            raise RuntimeError(f"refusing role cleanup: identity or attributes changed for {role}")
        if alias is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT parent.rolname
                         FROM pg_catalog.pg_auth_members AS m
                         JOIN pg_catalog.pg_roles AS parent ON parent.oid=m.roleid
                        WHERE m.member=%s::regrole""",
                    (role,),
                )
                memberships = {row[0] for row in cur.fetchall()}
            if memberships != {_ROLE_GROUPS[alias]}:
                raise RuntimeError(f"refusing role cleanup: unexpected memberships for {role}: {memberships}")
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _cleanup_resources(
    admin_dsn: str,
    name: str | None,
    database_oid: int | None,
    roles: dict[str, str],
    role_oids: dict[str, int],
    created_groups: dict[str, int],
    lock_conn,
) -> None:
    errors = []
    database_removed = name is None
    if name is not None:
        try:
            if database_oid is None:
                if _database_oid(lock_conn, name) is not None:
                    raise RuntimeError("database exists without a recorded OID; refusing cleanup")
            else:
                _drop_database_exact(admin_dsn, name, database_oid)
            database_removed = True
        except Exception as exc:
            errors.append(exc)
    if database_removed:
        for alias, role in roles.items():
            try:
                _drop_role_exact(
                    admin_dsn,
                    role,
                    role_oids[alias],
                    alias=alias,
                    database_name=name,
                )
            except Exception as exc:
                errors.append(exc)
        for group, oid in created_groups.items():
            try:
                _drop_role_exact(admin_dsn, group, oid, group=True)
            except Exception as exc:
                errors.append(exc)
    try:
        lock_conn.close()
    except Exception as exc:
        errors.append(exc)
    if errors:
        raise RuntimeError("fixture cleanup failed: " + "; ".join(str(exc) for exc in errors)) from errors[0]


@dataclass
class StageTestDB:
    """One uniquely named S1 database and the exact roles it created."""

    name: str
    oid: int
    roles: dict[str, str]
    role_oids: dict[str, int]
    maintenance_dsn: str
    _base_dsn: dict[str, str] = field(repr=False)
    _created_groups: dict[str, int] = field(default_factory=dict, repr=False)
    _connections: list[Any] = field(default_factory=list, repr=False)
    _lock_conn: Any = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)
    loaded_files: tuple[str, ...] = ()
    catalog: dict[str, Any] = field(default_factory=dict)

    @property
    def admin_dsn(self) -> str:
        """The pgembed maintenance login, for fixture setup and catalog probes."""
        return _dsn(self._base_dsn, self.name)

    def role_dsn(self, alias: str) -> str:
        if alias not in self.roles:
            raise KeyError(alias)
        return _dsn(self._base_dsn, self.name, user=self.roles[alias])

    def connect(self, role: str | None = None):
        """Connect as pgembed admin, or as one of this fixture's LOGIN roles."""
        if self._closed:
            raise RuntimeError("fixture is already cleaned up")
        conn = psycopg2.connect(self.admin_dsn if role is None else self.role_dsn(role))
        self._connections.append(conn)
        return conn

    def cleanup(self) -> None:
        if self._closed:
            return
        errors = []
        for conn in reversed(self._connections):
            try:
                conn.close()
            except Exception as exc:
                errors.append(exc)
        self._connections.clear()
        try:
            _cleanup_resources(
                self.maintenance_dsn,
                self.name,
                self.oid,
                self.roles,
                self.role_oids,
                self._created_groups,
                self._lock_conn,
            )
        except Exception as exc:
            errors.append(exc)
        self._lock_conn = None
        self._closed = True
        if errors:
            raise RuntimeError("fixture cleanup failed: " + "; ".join(str(exc) for exc in errors)) from errors[0]

    close = cleanup

    def __enter__(self) -> "StageTestDB":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.cleanup()
        except Exception as cleanup_error:
            if exc is None:
                raise
            exc.add_note(f"fixture cleanup also failed: {cleanup_error}")
        return False


def _catalog_snapshot(conn) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT n.nspname, r.rolname
                 FROM pg_catalog.pg_namespace AS n
                 JOIN pg_catalog.pg_roles AS r ON r.oid=n.nspowner
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
                  AND n.nspname !~ '^pg_(toast|temp)'
                ORDER BY n.nspname"""
        )
        snapshot["schemas"] = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """SELECT c.relname, c.relkind
                 FROM pg_catalog.pg_class AS c
                 JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace
                WHERE n.nspname='v24'
                ORDER BY c.relname, c.relkind"""
        )
        snapshot["relations"] = [tuple(row) for row in cur.fetchall()]
        cur.execute(
            """SELECT e.extname
                 FROM pg_catalog.pg_extension AS e
                 JOIN pg_catalog.pg_namespace AS n ON n.oid=e.extnamespace
                WHERE n.nspname='v24'
                ORDER BY e.extname"""
        )
        snapshot["extensions"] = [row[0] for row in cur.fetchall()]
    return snapshot


EXPECTED_TABLES: frozenset[str] = frozenset({
    "scopes", "runs", "effects", "pins", "episodes",
    "fibers", "slots", "installs", "events", "requests",
})


def _assert_closed_catalog(conn) -> dict[str, Any]:
    snapshot = _catalog_snapshot(conn)
    assert snapshot["schemas"] == [("v24", "v24_owner"), ("v24_fake", "v24_owner")], snapshot
    tables = frozenset(
        name for name, kind in snapshot["relations"] if kind in ("r", "p")
    )
    views = frozenset(
        name for name, kind in snapshot["relations"] if kind in ("v", "m")
    )
    assert tables == EXPECTED_TABLES, (tables, EXPECTED_TABLES, snapshot)
    assert views == frozenset(), (views, snapshot)
    assert snapshot["extensions"] == [], snapshot
    return snapshot


def setup_db() -> StageTestDB:
    """Create, load, and return one isolated v24/s1 database fixture."""
    validate_manifest()
    _server_process, base_dsn = _server_and_base_dsn()
    maintenance_dsn = _dsn(base_dsn, "postgres")
    lock_conn = psycopg2.connect(maintenance_dsn)
    lock_conn.autocommit = True
    created_groups: dict[str, int] = {}
    roles: dict[str, str] = {}
    role_oids: dict[str, int] = {}
    name = None
    database_oid = None
    fixture = None
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_catalog.pg_advisory_lock(%s)", (_LOCK_KEY,))
            cur.execute(
                "SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user"
            )
            row = cur.fetchone()
            if row is None or not row[0]:
                raise RuntimeError("v24/s1 fixture requires the trusted pgembed superuser")

        pending_groups = {}
        lock_conn.autocommit = False
        try:
            with lock_conn:
                for group in _GROUPS:
                    group_oid, was_created = _create_or_check_group(lock_conn, group)
                    if was_created:
                        pending_groups[group] = group_oid
            created_groups = pending_groups
        finally:
            lock_conn.autocommit = True

        name = _new_name()
        _validate_name(name)
        with lock_conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(name)
                )
            )
        database_oid = _database_oid(lock_conn, name)
        if database_oid is None:
            raise RuntimeError("new v24/s1 database is missing from pg_database; refusing cleanup")
        with lock_conn.cursor() as cur:
            cur.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO v24_owner").format(
                    sql.Identifier(name)
                )
            )

        pending_roles = {alias: f"{name}_{alias}" for alias in _ROLE_GROUPS}
        pending_role_oids = {}
        lock_conn.autocommit = False
        try:
            with lock_conn:
                with lock_conn.cursor() as cur:
                    for alias, group in _ROLE_GROUPS.items():
                        role = pending_roles[alias]
                        cur.execute(
                            sql.SQL(
                                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB "
                                "NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS"
                            ).format(sql.Identifier(role))
                        )
                        cur.execute(
                            sql.SQL("GRANT {} TO {}").format(
                                sql.Identifier(group), sql.Identifier(role)
                            )
                        )
                        state = _role_state(lock_conn, role)
                        if state is None:
                            raise RuntimeError(f"new fixture LOGIN role missing: {role}")
                        pending_role_oids[alias] = int(state[0])
            roles, role_oids = pending_roles, pending_role_oids
        finally:
            lock_conn.autocommit = True

        fixture = StageTestDB(
            name=name,
            oid=database_oid,
            roles=roles,
            role_oids=role_oids,
            maintenance_dsn=maintenance_dsn,
            _base_dsn=base_dsn,
            _created_groups=created_groups,
            _lock_conn=lock_conn,
        )
        with contextlib.closing(psycopg2.connect(fixture.admin_dsn)) as conn:
            if conn.autocommit:
                raise AssertionError("fixture owner connection unexpectedly uses autocommit")
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("SET ROLE {}").format(sql.Identifier("v24_owner"))
                    )
                fixture.loaded_files = load_stage(conn)
                # Fixture-only IO evidence: never part of the ten-table domain DDL.
                with conn.cursor() as cur:
                    cur.execute("""CREATE SCHEMA v24_fake AUTHORIZATION v24_owner;
                        CREATE TABLE v24_fake.journal (
                          id bigserial PRIMARY KEY, effect_id uuid NOT NULL,
                          attempt bigint NOT NULL, fence bigint NOT NULL,
                          op text NOT NULL, payload jsonb NOT NULL, result jsonb,
                          started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                          finished_at timestamptz,
                          UNIQUE(effect_id, attempt, fence)
                        )""")
                if conn.get_transaction_status() != TRANSACTION_STATUS_INTRANS:
                    raise AssertionError("load_stage committed instead of leaving the transaction open")
        with contextlib.closing(psycopg2.connect(fixture.admin_dsn)) as conn:
            fixture.catalog = _assert_closed_catalog(conn)
        return fixture
    except Exception as original:
        if fixture is not None:
            try:
                fixture.cleanup()
            except Exception as cleanup_error:
                original.add_note(f"fixture setup cleanup also failed: {cleanup_error!r}")
        else:
            try:
                _cleanup_resources(
                    maintenance_dsn,
                    name,
                    database_oid,
                    roles,
                    role_oids,
                    created_groups,
                    lock_conn,
                )
            except Exception as cleanup_error:
                original.add_note(f"fixture setup cleanup also failed: {cleanup_error!r}")
        raise


def _assert_role_layout(db: StageTestDB) -> None:
    for alias, group in _ROLE_GROUPS.items():
        role = db.roles[alias]
        with contextlib.closing(psycopg2.connect(db.maintenance_dsn)) as admin_conn:
            state = _role_state(admin_conn, group)
            assert state is not None and tuple(state[1:]) == (
                False,
                False,
                False,
                False,
                False,
                False,
                False,
            ), (group, state)
            login_state = _role_state(admin_conn, role)
            assert login_state is not None and int(login_state[0]) == db.role_oids[alias]
            assert tuple(login_state[1:]) == (
                False,
                True,
                False,
                False,
                True,
                False,
                False,
            ), (role, login_state)
            admin_conn.rollback()
        with contextlib.closing(db.connect(alias)) as role_conn:
            with role_conn.cursor() as cur:
                cur.execute(
                    "SELECT session_user::text, current_user::text, "
                    "pg_catalog.pg_has_role(session_user, %s, 'USAGE')",
                    (group,),
                )
                assert cur.fetchone() == (role, role, True), (alias, role)
                cur.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(group)))
                cur.execute("SELECT current_user::text")
                assert cur.fetchone() == (group,), (alias, group)
            role_conn.rollback()


def _assert_tcp_dsns_rejected(expected_socket: str) -> None:
    unsafe_dsns = (
        "dbname=postgres",
        "host=127.0.0.1",
        "host=localhost",
        f"host={expected_socket},{expected_socket}",
        f"host={expected_socket} hostaddr=127.0.0.1",
        f"host={expected_socket} service=forbidden",
        "host=/tmp",
    )
    for dsn in unsafe_dsns:
        try:
            validate_local_dsn(dsn, expected_socket)
        except ValueError:
            continue
        raise AssertionError(f"unsafe DSN accepted: {dsn}")


def _self_check() -> None:
    expected_canonical = (
        "00_schema.sql",
        "10_schema.sql",
        "20_triggers.sql",
        "30_advance.sql",
        "40_interpreters.sql",
        "45_capability.sql",
        "46_cleanup.sql",
        "47_verbs.sql",
        "48_loop.sql",
        "50_permissions.sql",
    )
    assert CANONICAL_ORDER == expected_canonical, CANONICAL_ORDER
    assert SQL_LOAD_ORDER == expected_canonical[:len(SQL_LOAD_ORDER)], SQL_LOAD_ORDER
    self_check_manifest()
    print("[loader] canonical prefix and rejection probes passed")

    endpoint = _setup_endpoint
    assert endpoint is not None
    _assert_tcp_dsns_rejected(endpoint["socket"])
    print("[dsn] TCP and libpq indirection rejection probes passed")

    cleanup_db_name = None
    cleanup_login_roles = ()
    cleanup_groups = ()
    cleanup_admin_dsn = None
    with setup_db() as db:
        cleanup_db_name = db.name
        cleanup_login_roles = tuple(db.roles.values())
        cleanup_groups = tuple(db._created_groups)
        cleanup_admin_dsn = db.maintenance_dsn
        assert db.loaded_files == SQL_LOAD_ORDER, db.loaded_files
        assert db.catalog["schemas"] == [("v24", "v24_owner"), ("v24_fake", "v24_owner")], db.catalog
        assert frozenset(
            name for name, kind in db.catalog["relations"] if kind in ("r", "p")
        ) == EXPECTED_TABLES, db.catalog
        assert not [
            name for name, kind in db.catalog["relations"] if kind in ("v", "m")
        ], db.catalog
        _assert_role_layout(db)

        probe = db.connect()
        probe.autocommit = True
        try:
            try:
                load_stage(probe)
            except ValueError as exc:
                assert "autocommit" in str(exc), exc
            else:
                raise AssertionError("load_stage accepted an autocommit connection")
        finally:
            probe.close()
        print("[fixture] one-transaction load and closed-set catalog passed")

    with contextlib.closing(psycopg2.connect(cleanup_admin_dsn)) as conn:
        assert _database_oid(conn, cleanup_db_name) is None, cleanup_db_name
        for role in cleanup_login_roles:
            assert _role_state(conn, role) is None, role
        for group in cleanup_groups:
            assert _role_state(conn, group) is None, group
        conn.rollback()
    print("[cleanup] OID-verified database-first cleanup passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="create, inspect, and precisely clean a v24/s1 fixture",
    )
    parser.parse_args(argv)
    try:
        with server_helper_scope():
            _server_and_base_dsn()
            print(f"[environment] psycopg2={psycopg2.__version__} socket=unix-only")
            _self_check()
    except Exception as exc:
        print(f"[failed] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    print("[passed] v24/s1 setup self-check")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--server-helper"]:
        _server_helper()
    else:
        raise SystemExit(main())
