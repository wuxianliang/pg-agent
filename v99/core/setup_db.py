"""Disposable, exact-identity PostgreSQL fixture for v99/core.

Importing is side-effect free. `setup_db()` creates one unique database and
returns a manager; callers close their connections before cleanup (or register
connections with `db.connect()`, which cleanup closes automatically).
"""
from __future__ import annotations

import argparse
import atexit
import json
import select
import contextlib
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn

ROOT = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^v99_core_([0-9]+)_([0-9a-f]{12})$")
GROUPS = ("v99_core_operator", "v99_core_service", "v99_core_reader")
ALIASES = {"operator": "v99_core_operator", "service": "v99_core_service", "reader": "v99_core_reader"}
_LOCK_KEY = 0x563939434F5245

# Script execution starts at the repository root in the documented command.
_REPO_ROOT = ROOT.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from v99.core.load import CORE_SQL_LOAD_ORDER, load_core, validate_manifest  # noqa: E402
from v99.core.catalog import assert_function_catalog  # noqa: E402


def validate_local_dsn(dsn: str, expected_socket: str) -> dict[str, str]:
    """Reject fallback, TCP, multiple hosts, and libpq service indirection."""
    params = parse_dsn(dsn)
    host = params.get("host", "")
    if (not host.startswith("/") or "," in host
            or Path(host).resolve() != Path(expected_socket).resolve()):
        raise ValueError("v99/core requires the single active pgembed Unix socket host")
    if any(key in params for key in ("hostaddr", "service", "servicefile")):
        raise ValueError("hostaddr and libpq service indirection are forbidden")
    if any(os.environ.get(key) for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")):
        raise ValueError("libpq hostaddr/service environment overrides are forbidden")
    if "," in params.get("port", ""):
        raise ValueError("multiple PostgreSQL ports are forbidden")
    return params


_setup_process = None
_setup_endpoint = None


def _close_server_helper(*, timeout=2):
    """EOF, TERM, then KILL the private helper group; retain handle until reaped."""
    global _setup_process, _setup_endpoint
    process = _setup_process
    if process is None:
        return
    errors = []
    try:
        process.stdin.close()
    except Exception as exc:
        errors.append(exc)
    reaped = False
    forced = False
    try:
        for sig in (None, signal.SIGTERM, signal.SIGKILL):
            if sig is not None:
                forced = True
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass  # It may have exited between wait and signal.
            try:
                code = process.wait(timeout=timeout)
                reaped = True
                break
            except subprocess.TimeoutExpired:
                continue
        if not reaped:
            raise RuntimeError('uv setup helper could not be reaped; live handle retained')
        # The waited process may be the uv shim while a child in its private
        # session survived. Verify the whole group is gone before dropping the
        # saved process handle; kill any residual helper descendants.
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
            errors.append(RuntimeError('uv setup helper left a live process-group member'))
    finally:
        if reaped:
            _setup_process = _setup_endpoint = None
            try:
                process.stdout.close()
            except Exception as exc:
                errors.append(exc)
    if forced or code != 0 or errors:
        failure = RuntimeError(f'uv setup helper cleanup failed: forced={forced}, exit={code}')
        for error in errors:
            failure.add_note(repr(error))
        raise failure


def _atexit_server_helper():
    try:
        _close_server_helper()
    except BaseException as exc:
        # Exceptions raised by an atexit callback otherwise print and still
        # return exit 0. A leaked helper is a failed setup, so make that
        # diagnostic observable to the invoking script.
        print(f'[failed] uv setup helper atexit cleanup: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        os._exit(1)


atexit.register(_atexit_server_helper)


@contextlib.contextmanager
def server_helper_scope():
    """Report cleanup failures before script exit, retaining primary failures."""
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
            primary_error.add_note(f'uv setup helper cleanup failed: {cleanup_error!r}')


def _server_helper():
    """Authorized uv setup child retains pgembed handle until parent pipe EOF."""
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
            raise RuntimeError('pgembed did not report its active Unix endpoint')
        print(json.dumps({'uri':server.get_uri('postgres'), 'socket':str(info.socket_dir), 'port':info.port}), flush=True)
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
            primary_error.add_note(f'pgembed handle cleanup failed: {cleanup_error!r}')
        finally:
            signal.signal(signal.SIGTERM, old_handler)


def _read_helper_endpoint(process, *, timeout=60):
    deadline = time.monotonic() + timeout
    data = bytearray()
    while b'\n' not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise RuntimeError('uv setup helper endpoint deadline exceeded')
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            raise RuntimeError('uv setup helper exited before reporting endpoint')
        data.extend(chunk)
        if len(data) > 4096:
            raise RuntimeError('uv setup helper endpoint exceeds size limit')
    return json.loads(data.split(b'\n', 1)[0])


def _server_and_base_dsn():
    """Keep pgembed startup/attestation in an explicitly allowed uv setup child.

    Holding the helper's stdin open retains its pgembed handle. No direct
    postgres/pg_config process is launched by the guarded gate process.
    """
    global _setup_process, _setup_endpoint
    try:
        if _setup_process is None:
            _setup_process = subprocess.Popen(
                ['uv', 'run', 'python', 'v99/core/setup_db.py', '--server-helper'],
                cwd=_REPO_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                start_new_session=True,
            )
            _setup_endpoint = _read_helper_endpoint(_setup_process)
        if _setup_process.poll() is not None:
            raise RuntimeError('uv setup helper exited while fixture was live')
        endpoint = _setup_endpoint
        params = validate_local_dsn(endpoint['uri'], endpoint['socket'])
        params['port'] = str(endpoint['port'])
        host = Path(params['host'])
        if not host.is_dir() or not (host / f".s.PGSQL.{params['port']}").exists():
            raise RuntimeError('uv setup endpoint does not identify an active Unix socket')
        if 'port' in parse_dsn(endpoint['uri']) and int(parse_dsn(endpoint['uri'])['port']) != endpoint['port']:
            raise RuntimeError('uv setup URI port differs from actual pgembed port')
        params.pop('dbname', None)
        return _setup_process, params
    except BaseException as exc:
        try:
            _close_server_helper()
        except BaseException as cleanup_error:
            exc.add_note(f'uv setup startup cleanup failed: {cleanup_error!r}')
        raise


def _dsn(params: dict[str, str], database: str, *, user: str | None = None) -> str:
    result = dict(params, dbname=database)
    if user is not None:
        result["user"] = user
    dsn = make_dsn(**result)
    validate_local_dsn(dsn, params["host"])
    return dsn


def local_dsn(database: str, *, user: str | None = None) -> str:
    """Create a validated local DSN; user=None retains pgembed's admin user."""
    _, params = _server_and_base_dsn()
    return _dsn(params, database, user=user)


def _new_name() -> str:
    return f"v99_core_{os.getpid()}_{secrets.token_hex(6)}"


def _validate_name(name: str) -> None:
    match = NAME_RE.fullmatch(name)
    if match is None or int(match.group(1)) != os.getpid():
        raise ValueError(f"refusing to manage database outside this fixture process: {name!r}")


def _object_oid(conn, query: str, value: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(query, (value,))
        row = cur.fetchone()
    return None if row is None else int(row[0])


def _role_state(conn, role: str):
    with conn.cursor() as cur:
        cur.execute("""SELECT oid::bigint, rolsuper, rolinherit, rolcreaterole,
                            rolcreatedb, rolcanlogin, rolreplication, rolbypassrls
                       FROM pg_catalog.pg_roles WHERE rolname=%s""", (role,))
        return cur.fetchone()


def _create_or_check_group(conn, group: str) -> tuple[int, bool]:
    state = _role_state(conn, group)
    created = state is None
    if created:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS").format(sql.Identifier(group)))
        state = _role_state(conn, group)
    expected = (False, False, False, False, False, False, False)
    if state is None or tuple(state[1:]) != expected:
        raise RuntimeError(f"existing role {group} is not the expected inert NOLOGIN fixture group")
    return int(state[0]), created


def _database_oid(conn, name: str) -> int | None:
    return _object_oid(conn, "SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=%s", name)


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


def _drop_role_exact(admin_dsn: str, role: str, oid: int, *, login: bool, group: bool = False) -> None:
    alias = None
    if login:
        database_name, _, alias = role.rpartition('_')
        _validate_name(database_name)
        if alias not in ALIASES:
            raise ValueError(f'not a fixture login role: {role}')
    elif not group or role not in GROUPS:
        raise ValueError(f'not a fixture group: {role}')
    with contextlib.closing(psycopg2.connect(admin_dsn)) as conn:
        conn.autocommit = True
        state = _role_state(conn, role)
        if state is None:
            return
        expected = ((False, True, False, False, True, False, False) if login
                    else (False, False, False, False, False, False, False))
        if int(state[0]) != oid or tuple(state[1:]) != expected:
            raise RuntimeError(f"refusing role cleanup: identity or attributes changed for {role}")
        if login:
            with conn.cursor() as cur:
                cur.execute("SELECT parent.rolname FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles parent ON parent.oid=m.roleid WHERE m.member=%s::regrole", (role,))
                memberships = {row[0] for row in cur.fetchall()}
            if memberships != {ALIASES[alias]}:
                raise RuntimeError(f"refusing role cleanup: unexpected memberships for {role}: {memberships}")
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@dataclass
class CoreTestDB:
    server: Any
    name: str
    oid: int
    roles: dict[str, str]
    role_oids: dict[str, int]
    admin_dsn: str
    _base_dsn: dict[str, str] = field(repr=False)
    _created_groups: dict[str, int] = field(default_factory=dict, repr=False)
    _connections: list[Any] = field(default_factory=list, repr=False)
    loaded_files: tuple[str, ...] = ()
    before_catalog: dict[str, Any] = field(default_factory=dict)
    after_catalog: dict[str, Any] = field(default_factory=dict)
    _closed: bool = field(default=False, repr=False)
    _lock_conn: Any = field(default=None, repr=False)

    @property
    def database_oid(self) -> int:
        return self.oid

    @property
    def maintenance_dsn(self) -> str:
        """Administrative endpoint on postgres, used only for lifecycle cleanup."""
        return _dsn(self._base_dsn, "postgres", user=None)

    @property
    def admin_uri(self) -> str:
        return self.admin_dsn

    @property
    def operator_dsn(self) -> str:
        return self.role_dsn("operator")

    @property
    def service_dsn(self) -> str:
        return self.role_dsn("service")

    @property
    def reader_dsn(self) -> str:
        return self.role_dsn("reader")

    def role_dsn(self, alias: str) -> str:
        if alias not in self.roles:
            raise KeyError(alias)
        return _dsn(self._base_dsn, self.name, user=self.roles[alias])

    def connect(self, alias: str = "admin"):
        if self._closed:
            raise RuntimeError("fixture is already cleaned up")
        uri = self.admin_uri if alias == "admin" else self.role_dsn(alias)
        conn = psycopg2.connect(uri)
        self._connections.append(conn)
        return conn

    def cleanup(self) -> None:
        if self._closed:
            return
        errors = []
        for conn in reversed(self._connections):
            try:
                conn.close()
            except Exception as exc:  # cleanup must continue and report every failure
                errors.append(exc)
        self._connections.clear()
        database_removed = False
        try:
            _drop_database_exact(self.maintenance_dsn, self.name, self.oid)
            database_removed = True
        except Exception as exc:
            errors.append(exc)
        for alias, role in (self.roles.items() if database_removed else ()):
            try:
                _drop_role_exact(self.maintenance_dsn, role, self.role_oids[alias], login=True)
            except Exception as exc:
                errors.append(exc)
        for group, oid in (self._created_groups.items() if database_removed else ()):
            try:
                _drop_role_exact(self.maintenance_dsn, group, oid, login=False, group=True)
            except Exception as exc:
                errors.append(exc)
        if self._lock_conn is not None:
            try:
                self._lock_conn.close()
            except Exception as exc:
                errors.append(exc)
            self._lock_conn = None
        self._closed = True
        if errors:
            raise RuntimeError("fixture cleanup failed: " + "; ".join(str(e) for e in errors)) from errors[0]

    close = cleanup

    def __enter__(self) -> "CoreTestDB":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            self.cleanup()
        except Exception as cleanup_error:
            if exc is None:
                raise
            if hasattr(exc, "add_note"):
                exc.add_note(f"fixture cleanup also failed: {cleanup_error}")
        return False


def _catalog_snapshot(conn) -> dict[str, Any]:
    """Bounded catalog evidence for the isolated schema, not arbitrary DB state."""
    snapshot: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname='v99_core'")
        snapshot["schemas"] = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT extname, n.nspname FROM pg_catalog.pg_extension e JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace WHERE n.nspname='v99_core' ORDER BY extname")
        snapshot["extensions"] = [tuple(r) for r in cur.fetchall()]
        cur.execute("""SELECT c.relname, c.relkind FROM pg_catalog.pg_class c
                       JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname='v99_core' ORDER BY c.relname""")
        snapshot["relations"] = [tuple(r) for r in cur.fetchall()]
        cur.execute("""SELECT p.proname, pg_catalog.pg_get_function_identity_arguments(p.oid)
                       FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                       WHERE n.nspname='v99_core' ORDER BY p.proname, 2""")
        snapshot["functions"] = [tuple(r) for r in cur.fetchall()]
        cur.execute("""SELECT p.proname, p.proowner::regrole::text, p.prosecdef,
                              coalesce(array_to_string(p.proconfig, ','), '')
                       FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                       WHERE n.nspname='v99_core' AND p.proname LIKE 'v99_core_%'
                       ORDER BY p.proname, pg_catalog.pg_get_function_identity_arguments(p.oid)""")
        snapshot["function_security"] = [tuple(r) for r in cur.fetchall()]
        cur.execute("""SELECT t.tgname, c.relname FROM pg_catalog.pg_trigger t
                       JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
                       JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                       WHERE n.nspname='v99_core' AND NOT t.tgisinternal ORDER BY 1,2""")
        snapshot["triggers"] = [tuple(r) for r in cur.fetchall()]
        cur.execute("""SELECT i.relname FROM pg_catalog.pg_class i
                       JOIN pg_catalog.pg_namespace n ON n.oid=i.relnamespace
                       WHERE n.nspname='v99_core' AND i.relkind='i' ORDER BY 1""")
        snapshot["indexes"] = [r[0] for r in cur.fetchall()]
    return snapshot


def setup_db(load_sql: bool = True) -> CoreTestDB:
    """Create one fixture; hold the fixed-group lock until exact cleanup.

    SQL is loaded in one transaction. Role creation is transactional as well;
    an initialization failure cleans only identities recorded by this call.
    """
    validate_manifest()
    server, base_dsn = _server_and_base_dsn()
    maintenance_dsn = _dsn(base_dsn, "postgres", user=None)
    lock_conn = psycopg2.connect(maintenance_dsn)
    lock_conn.autocommit = True
    created_groups: dict[str, int] = {}
    roles: dict[str, str] = {}
    role_oids: dict[str, int] = {}
    name = None
    database_oid = None
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_catalog.pg_advisory_lock(%s)", (_LOCK_KEY,))
            cur.execute("SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=current_user")
            if not cur.fetchone()[0]:
                raise RuntimeError("fixture requires the trusted pgembed superuser")
        # Publish ownership records only after the role transaction commits.
        pending_groups = {}
        lock_conn.autocommit = False
        try:
            with lock_conn:
                for group in GROUPS:
                    group_oid, created = _create_or_check_group(lock_conn, group)
                    if created:
                        pending_groups[group] = group_oid
            created_groups = pending_groups
        finally:
            lock_conn.autocommit = True
        name = _new_name()
        _validate_name(name)
        with lock_conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
            cur.execute(sql.SQL("REVOKE CONNECT, TEMP ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO v99_core_operator, v99_core_service, v99_core_reader").format(sql.Identifier(name)))
        database_oid = _database_oid(lock_conn, name)
        if database_oid is None:
            raise RuntimeError("new fixture database missing from catalog; cleanup must refuse")
        pending_roles = {alias: f"{name}_{alias}" for alias in ALIASES}
        pending_role_oids = {}
        lock_conn.autocommit = False
        try:
            with lock_conn:
                with lock_conn.cursor() as cur:
                    for alias, group in ALIASES.items():
                        role = pending_roles[alias]
                        cur.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS").format(sql.Identifier(role)))
                        cur.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(role)))
                        pending_role_oids[alias] = int(_role_state(lock_conn, role)[0])
            roles, role_oids = pending_roles, pending_role_oids
        finally:
            lock_conn.autocommit = True
        fixture = CoreTestDB(
            server=server, name=name, oid=database_oid, roles=roles,
            role_oids=role_oids, admin_dsn=_dsn(base_dsn, name),
            _base_dsn=base_dsn, _created_groups=created_groups, _lock_conn=lock_conn,
        )
        with contextlib.closing(psycopg2.connect(fixture.admin_dsn)) as conn:
            fixture.before_catalog = _catalog_snapshot(conn)
            conn.rollback()
            if load_sql:
                with conn:
                    fixture.loaded_files = load_core(conn)
            fixture.after_catalog = _catalog_snapshot(conn)
        return fixture
    except Exception as original:
        cleanup_errors = []
        # Database first: later ACL may reference roles, so roles cannot be
        # dropped safely until the database has been removed.
        database_removed = name is None
        if name is not None:
            try:
                if database_oid is None:
                    if _database_oid(lock_conn, name) is not None:
                        raise RuntimeError("database exists without a recorded OID; refusing cleanup")
                else:
                    _drop_database_exact(maintenance_dsn, name, database_oid)
                database_removed = True
            except Exception as exc:
                cleanup_errors.append(exc)
        if database_removed:
            for alias, role in roles.items():
                try:
                    _drop_role_exact(maintenance_dsn, role, role_oids[alias], login=True)
                except Exception as exc:
                    cleanup_errors.append(exc)
            for group, group_oid in created_groups.items():
                try:
                    _drop_role_exact(maintenance_dsn, group, group_oid, login=False, group=True)
                except Exception as exc:
                    cleanup_errors.append(exc)
        try:
            lock_conn.close()
        except Exception as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            original.add_note("fixture setup cleanup also failed: " + "; ".join(map(str, cleanup_errors)))
        raise


def _assert_raises_sqlstate(conn, code: str, statement: str, params=()) -> None:
    savepoint = "v99_selfcheck_probe"
    with conn.cursor() as cur:
        cur.execute(f"SAVEPOINT {savepoint}")
        try:
            cur.execute(statement, params)
        except psycopg2.Error as exc:
            if exc.pgcode != code:
                raise AssertionError(f"expected SQLSTATE {code}, got {exc.pgcode}: {exc}") from exc
            cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            cur.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        cur.execute(f"RELEASE SAVEPOINT {savepoint}")
    raise AssertionError(f"expected SQLSTATE {code}: {statement}")


def _assert_route_acl(conn, alias: str) -> None:
    """Check the final EXECUTE matrix as the actual non-superuser LOGIN."""
    routes = {
        'operator': ('v99_core_start(uuid,text,text)', 'v99_core_cancel(uuid,uuid,text)',
                     'v99_core_steer(uuid,uuid,text,text,bigint)', 'v99_core_respond(uuid,uuid,text,jsonb,text)',
                     'v99_core_poll(uuid,uuid,bigint)', 'v99_core_wait_check(uuid,uuid,bigint,bigint,bigint)'),
        'reader': ('v99_core_poll(uuid,uuid,bigint)', 'v99_core_wait_check(uuid,uuid,bigint,bigint,bigint)'),
        'service': ('v99_core_driver_acquire(uuid,text,integer)', 'v99_core_discover(uuid,text,bigint)',
                    'v99_core_claim_effect(uuid,uuid,text,bigint)', 'v99_core_worker_history(uuid,text,bigint)',
                    'v99_core_accept_receipt(uuid,text,text,bigint,jsonb)', 'v99_core_recover_unknown(uuid,text,bigint)'),
    }
    private = ('v99_core_write_snapshot(uuid,uuid,text,text,jsonb,jsonb,uuid,text,text,boolean)',
               'v99_core_settle_human(uuid,uuid,jsonb)', 'v99_core_closeout(uuid,text,uuid,text,jsonb)')
    with conn.cursor() as cur:
        for signature in routes[alias]:
            cur.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", ('v99_core.' + signature,))
            assert cur.fetchone()[0] is True, (alias, 'missing EXECUTE', signature)
        for signature in set(routes['operator'] + routes['reader'] + routes['service']) - set(routes[alias]):
            cur.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", ('v99_core.' + signature,))
            assert cur.fetchone()[0] is False, (alias, 'unexpected EXECUTE', signature)
        for signature in private:
            cur.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')", ('v99_core.' + signature,))
            assert cur.fetchone()[0] is False, (alias, 'private helper exposed', signature)
        cur.execute("SELECT has_schema_privilege(current_user,'v99_core','CREATE'), has_table_privilege(current_user,'v99_core.core_runs','SELECT')")
        assert cur.fetchone() == (False, False), (alias, 'schema/table ACL')
        # A temporary table is a database privilege, and must be denied to hosts.
        try:
            cur.execute('CREATE TEMP TABLE v99_temp_acl_probe(x integer)')
        except psycopg2.Error:
            conn.rollback()
        else:
            raise AssertionError((alias, 'TEMP unexpectedly granted'))


def _self_check() -> None:
    expected = ("00_extensions.sql", "10_schema.sql", "20_ledger.sql", "30_ce.sql", "40_permissions.sql")
    if CORE_SQL_LOAD_ORDER != expected:
        raise AssertionError(f"final five-file manifest mismatch: {CORE_SQL_LOAD_ORDER}")
    print("[environment] python/psycopg2/final five-file SQL manifest verified")
    with setup_db() as db:
        if db.loaded_files != expected:
            raise AssertionError(f"unexpected loaded SQL files: {db.loaded_files}")
        snap = db.after_catalog
        with contextlib.closing(db.connect()) as catalog_conn:
            assert_function_catalog(catalog_conn)
            catalog_conn.rollback()
        if snap["schemas"] != ["v99_core"] or snap["extensions"] != [("pgcrypto", "v99_core")]:
            raise AssertionError(f"unexpected schema/extension catalog: {snap}")
        required_relations = {"core_runs", "core_epochs", "core_operations", "core_effects", "core_events", "core_snapshots", "core_wakes", "core_effect_pins", "core_requests", "core_tools", "core_meta"}
        found_relations = {name for name, kind in snap["relations"] if kind in ("r", "p")}
        if found_relations != required_relations:
            raise AssertionError(f"W1 relation catalog mismatch: {found_relations ^ required_relations}")
        if not {"v99_core_effects_primary", "v99_core_effects_human", "v99_core_effects_claimed"}.issubset(snap["indexes"]):
            raise AssertionError("effect cardinality indexes are missing")
        expected_triggers = {"v99_core_events_immutable", "v99_core_pins_immutable", "v99_core_requests_immutable", "v99_core_effect_binding", "v99_core_operation_binding", "v99_core_pin_binding", "v99_core_catalog_changed"}
        if expected_triggers != {name for name, _ in snap["triggers"]}:
            raise AssertionError(f"trigger catalog mismatch: {snap['triggers']}")
        expected_indexes = {'v99_core_effects_claimed','v99_core_effects_human','v99_core_effects_pk','v99_core_effects_primary','v99_core_effects_run_id','v99_core_effects_run_key','v99_core_epochs_open','v99_core_epochs_pk','v99_core_epochs_run_id','v99_core_epochs_run_ordinal','v99_core_events_closed','v99_core_events_id','v99_core_events_pk','v99_core_meta_pk','v99_core_operations_pk','v99_core_operations_request_unique','v99_core_operations_run_attempt','v99_core_operations_run_id','v99_core_pins_pk','v99_core_requests_pk','v99_core_runs_pk','v99_core_snapshots_pk','v99_core_tools_pk','v99_core_wakes_cursor','v99_core_wakes_pk'}
        if set(snap['indexes']) != expected_indexes:
            raise AssertionError(f"index catalog mismatch: {set(snap['indexes']) ^ expected_indexes}")
        if {name for name, _ in snap['triggers']} != expected_triggers:
            raise AssertionError('trigger catalog is not closed')
        ledger_functions = {
            'v99_core_error', 'v99_core_digest', 'v99_core_caller_role', 'v99_core_has_role',
            'v99_core_lock_run', 'v99_core_lock_work', 'v99_core_driver_error', 'v99_core_append_event',
            'v99_core_wake', 'v99_core_write_snapshot', 'v99_core_enqueue_effect',
            'v99_core_driver_acquire', 'v99_core_claim_effect', 'v99_core_mark_unknown',
            'v99_core_settle_effect', 'v99_core_settle_human', 'v99_core_recover_unknown',
            'v99_core_closeout',
        }
        permission_functions = {'v99_core_start','v99_core_cancel','v99_core_steer','v99_core_respond','v99_core_poll','v99_core_wait_check','v99_core_driver_acquire','v99_core_discover','v99_core_claim_effect','v99_core_worker_history','v99_core_accept_receipt','v99_core_recover_unknown'}
        if {name for name, _ in snap['functions'] if name in permission_functions} != permission_functions:
            raise AssertionError('final public route function catalog mismatch')
        ce_functions = {
            'v99_core_business_reason','v99_core_require','v99_core_keys','v99_core_uuid','v99_core_positive','v99_core_request_id',
            'v99_core_valid_error','v99_core_valid_response','v99_core_valid_receipt','v99_core_tool_error',
            'v99_core_result_error','v99_core_replay','v99_core_journal','v99_core_add_operation','v99_core_admit_turn',
            'v99_core_snapshot_projection','v99_core_start','v99_core_poll','v99_core_wait_check','v99_core_insert_user',
            'v99_core_cancel','v99_core_control_publish','v99_core_steer','v99_core_respond','v99_core_discover',
            'v99_core_worker_history','v99_core_publish_snapshot','v99_core_accept_receipt',
        }
        found_ledger = {name for name, _ in snap['functions'] if name in ledger_functions}
        if found_ledger != ledger_functions:
            raise AssertionError(f'W2 ledger function catalog mismatch: {ledger_functions - found_ledger}')
        found_ce = {name for name, _ in snap['functions'] if name in ce_functions}
        if found_ce != ce_functions:
            raise AssertionError(f'W3 CE function catalog mismatch: {ce_functions - found_ce}')
        expected_helpers = {'v99_core_valid_interaction','v99_core_immutable','v99_core_effect_binding','v99_core_pin_binding','v99_core_catalog_changed'}
        expected_core_functions = ledger_functions | ce_functions | expected_helpers
        found_core_functions = {name for name, _ in snap['functions'] if name.startswith('v99_core_')}
        if found_core_functions != expected_core_functions:
            raise AssertionError(f"v99 function signature/name catalog drift: {found_core_functions ^ expected_core_functions}")
        if any(owner != 'postgres' for _, owner, _, _ in snap['function_security']):
            raise AssertionError('v99_core function owner drift')
        if any(is_definer and path not in ('search_path=pg_catalog, v99_core','search_path=pg_catalog,v99_core')
               for _, _, is_definer, path in snap['function_security']):
            raise AssertionError('SECURITY DEFINER search_path drift')
        conn = psycopg2.connect(db.admin_uri)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT v99_core.digest('fixture','sha256') IS NOT NULL")
                    assert cur.fetchone()[0]
                    cur.execute("SELECT catalog_revision FROM v99_core.core_meta WHERE singleton")
                    assert cur.fetchone()[0] == 1
                    a, b, op1, op2 = (str(uuid.uuid4()) for _ in range(4))
                    cur.execute("INSERT INTO v99_core.core_runs(run_id,status) VALUES (%s,'running'),(%s,'running')", (a,b))
                    epoch_a_id, epoch_b_id = str(uuid.uuid4()), str(uuid.uuid4())
                    cur.execute("INSERT INTO v99_core.core_epochs(epoch_id,run_id,ordinal,continuity_generation,registration_generation,transition_kind) VALUES (%s,%s,1,1,1,'initial'),(%s,%s,1,1,1,'initial')", (epoch_a_id,a,epoch_b_id,b))
                    # Re-read the two epoch IDs through the run key for repeatable composite-FK probes.
                    cur.execute("SELECT epoch_id FROM v99_core.core_epochs WHERE run_id=%s", (a,)); epoch_a = cur.fetchone()[0]
                    cur.execute("SELECT epoch_id FROM v99_core.core_epochs WHERE run_id=%s", (b,)); epoch_b = cur.fetchone()[0]
                    cur.execute("INSERT INTO v99_core.core_operations(operation_id,request_id,run_id,epoch_id,verb,turn_ordinal,attempt_seq,status,payload_digest,completed_at) VALUES (%s,'req-a',%s,%s,'admit_turn',1,1,'pending','x',NULL),(%s,'req-b',%s,%s,'admit_turn',1,1,'pending','x',NULL)", (op1,a,epoch_a,op2,b,epoch_b))
                    effect = str(uuid.uuid4())
                    cur.execute("INSERT INTO v99_core.core_effects(effect_id,run_id,operation_id,kind,request,request_digest,idempotency_key,epoch_ordinal,turn_ordinal) VALUES (%s,%s,%s,'llm','{}','d','key-a',1,1)", (effect,a,op1))
                    _assert_raises_sqlstate(conn, "23503", "INSERT INTO v99_core.core_effects(effect_id,run_id,operation_id,kind,request,request_digest,idempotency_key,epoch_ordinal,turn_ordinal) VALUES (%s,%s,%s,'llm','{}','d','key-cross',1,1)", (str(uuid.uuid4()),a,op2))
                    human = str(uuid.uuid4())
                    cur.execute("INSERT INTO v99_core.core_effects(effect_id,run_id,operation_id,kind,request,request_digest,idempotency_key,epoch_ordinal,turn_ordinal) VALUES (%s,%s,%s,'human','{}','d','key-human',1,1)", (human,a,op1))
                    _assert_raises_sqlstate(conn, "23505", "INSERT INTO v99_core.core_effects(effect_id,run_id,operation_id,kind,request,request_digest,idempotency_key,epoch_ordinal,turn_ordinal) VALUES (%s,%s,%s,'human','{}','d','key-human-2',1,1)", (str(uuid.uuid4()),a,op1))
                    _assert_raises_sqlstate(conn, "23505", "INSERT INTO v99_core.core_effects(effect_id,run_id,operation_id,kind,request,request_digest,idempotency_key,epoch_ordinal,turn_ordinal) VALUES (%s,%s,%s,'llm','{}','d','key-primary-2',1,1)", (str(uuid.uuid4()),a,op1))
                    # Exercise the operation-side trigger as W2 will update
                    # admissions during settlement; a no-op update must work.
                    cur.execute("UPDATE v99_core.core_operations SET status='pending' WHERE operation_id=%s", (op1,))
                    _assert_raises_sqlstate(conn, "23514", "UPDATE v99_core.core_operations SET turn_ordinal=2 WHERE operation_id=%s", (op1,))
                    _assert_raises_sqlstate(conn, "23514", "INSERT INTO v99_core.core_effect_pins(effect_id,attempt_no,fence,driver_fence,context_revision,catalog_revision,request_digest) VALUES (%s,1,1,NULL,1,1,'d')", (effect,))
                    cur.execute("INSERT INTO v99_core.core_effect_pins(effect_id,attempt_no,fence,driver_fence,context_revision,catalog_revision,request_digest) VALUES (%s,1,1,NULL,1,1,'d')", (human,))
                    for table in ('core_events', 'core_effect_pins', 'core_requests'):
                        for mutation in ('UPDATE', 'DELETE', 'TRUNCATE'):
                            statement = (f"UPDATE v99_core.{table} SET " +
                                         {'core_events':'seq=seq', 'core_effect_pins':'fence=fence', 'core_requests':'kind=kind'}[table]
                                         if mutation == 'UPDATE' else f"{mutation} " + ('FROM ' if mutation == 'DELETE' else '') + f"v99_core.{table}")
                            _assert_raises_sqlstate(conn, "23514", statement)
                    cur.execute("UPDATE v99_core.core_tools SET enabled=enabled")
                    cur.execute("SELECT catalog_revision FROM v99_core.core_meta WHERE singleton")
                    assert cur.fetchone()[0] == 2
        finally:
            conn.close()
        if db.before_catalog['schemas'] or db.before_catalog['relations']:
            raise AssertionError('fixture was not empty before loading')
        for alias in ALIASES:
            with contextlib.closing(psycopg2.connect(db.role_dsn(alias))) as host:
                with host.cursor() as cur:
                    cur.execute("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user")
                    assert cur.fetchone() == (db.roles[alias], False, False, False)
                    cur.execute("SELECT has_database_privilege(current_user,%s,'CONNECT'), has_database_privilege(current_user,%s,'TEMP')", (db.name, db.name))
                    assert cur.fetchone() == (True, False), (alias, 'database ACL')
                host.rollback()
                _assert_route_acl(host, alias)
        print(f"[load] files={','.join(db.loaded_files)} schema={snap['schemas']} tables={len(required_relations)} indexes={len(snap['indexes'])}; operator/reader/service LOGIN ACL verified")
    with setup_db(load_sql=False) as empty:
        if empty.loaded_files or empty.after_catalog["schemas"] or empty.after_catalog["relations"]:
            raise AssertionError("load_sql=False must leave the database free of v99 core objects")
        print(f"[empty-fixture] load_sql=False database={empty.name} oid={empty.oid}")
        wrong = empty.oid + 1
        try:
            _drop_database_exact(empty.maintenance_dsn, empty.name, wrong)
        except RuntimeError:
            pass
        else:
            raise AssertionError("cleanup accepted a mismatched database OID")
        role = empty.roles['operator']
        try:
            _drop_role_exact(empty.maintenance_dsn, role, empty.role_oids['operator'] + 1, login=True)
        except RuntimeError:
            pass
        else:
            raise AssertionError('cleanup accepted a mismatched role OID')
        with contextlib.closing(psycopg2.connect(empty.admin_uri)) as probe:
            if _database_oid(probe, empty.name) != empty.oid:
                raise AssertionError("wrong-OID cleanup removed the fixture database")
            assert int(_role_state(probe, role)[0]) == empty.role_oids['operator']
    # Prove manager cleanup removes this exact database and its unique roles.
    with contextlib.closing(psycopg2.connect(db.maintenance_dsn)) as admin:
        if _database_oid(admin, db.name) is not None:
            raise AssertionError("fixture database survived context cleanup")
        if any(_role_state(admin, role) is not None for role in db.roles.values()):
            raise AssertionError("fixture login roles survived cleanup")
    _fixture_failure_checks()
    print("[cleanup] exact database/role identity removed; mismatched OID refused")


def _fixture_failure_checks() -> None:
    """Reproducible W1 failure cleanup probes; no final ACL assertions."""
    from unittest.mock import patch

    def resources():
        with contextlib.closing(psycopg2.connect(local_dsn('postgres'))) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT datname,oid FROM pg_database WHERE datname LIKE 'v99_core_%' ORDER BY 1")
                databases = cur.fetchall()
                cur.execute("SELECT rolname,oid FROM pg_roles WHERE rolname LIKE 'v99_core_%' ORDER BY 1")
                return databases, cur.fetchall()

    before = resources()
    with patch(__name__ + '.load_core', side_effect=RuntimeError('injected W1 loader failure')):
        try:
            setup_db()
        except RuntimeError as exc:
            assert str(exc) == 'injected W1 loader failure'
        else:
            raise AssertionError('loader failure was swallowed')
    assert resources() == before, 'initialization failure leaked database/roles'
    original = ValueError('original body failure')
    fixture = setup_db(load_sql=False)
    # Keep the real cleanup available after injecting a diagnostic failure.
    with patch.object(fixture, 'cleanup', side_effect=RuntimeError('cleanup probe')):
        try:
            with fixture:
                raise original
        except ValueError as exc:
            assert exc is original and any('cleanup probe' in note for note in exc.__notes__)
        else:
            raise AssertionError('cleanup masked the body failure')
    fixture.cleanup()
    assert resources() == before, 'failure cleanup probes leaked resources'
    _, params = _server_and_base_dsn()
    expected_socket = params['host']
    for dsn in ('dbname=postgres', 'host=127.0.0.1', 'host=localhost',
                f"host={expected_socket},{expected_socket}",
                f"host={expected_socket} hostaddr=127.0.0.1",
                f"host={expected_socket} service=forbidden", 'host=/tmp'):
        try:
            validate_local_dsn(dsn, expected_socket)
        except ValueError:
            pass
        else:
            raise AssertionError(f'unsafe DSN accepted: {dsn}')
    print('[failure probes] loader failure cleanup, original exception preservation, strict DSN rejection passed')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true", help="create, inspect, and precisely clean W1 fixtures")
    parser.parse_args(argv)
    try:
        with server_helper_scope():
            _server_and_base_dsn()
            print(f"[environment] psycopg2={psycopg2.__version__} socket=unix-only pgcrypto=available")
            _self_check()
    except Exception as exc:
        print(f"[failed] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    print("[passed] v99/core setup self-check")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ['--server-helper']:
        _server_helper()
    else:
        raise SystemExit(main())
