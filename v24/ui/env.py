"""Persistent environment owner for the v24 Chainlit slice."""
from __future__ import annotations
import argparse, contextlib, fcntl, hashlib, json, os, sys, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from psycopg2 import Error as DatabaseError, connect, sql
from psycopg2.extensions import make_dsn, parse_dsn

ROOT = Path(__file__).resolve().parents[2]
DB_NAME = "agent_v24_ui"
GROUPS = ("v24_owner", "v24_admin", "v24_service", "v24_operator")
ROLE_GROUPS = {"admin":"v24_admin", "service":"v24_service"}
from v24.load import SQL_LOAD_ORDER, load_stage, validate_manifest
from server import get_server
from v24.s1.setup_db import validate_local_dsn, _create_or_check_group, _role_state
from v24.s1.setup_db import EXPECTED_TABLES

class AlreadyRunning(RuntimeError):
    def __init__(self, pid): self.pid = pid; super().__init__("already_running")

@dataclass(frozen=True)
class UiEnv:
    repo_root: Path; data_dir: Path; db_name: str; socket_dir: Path; port: int
    maintenance_dsn: str; admin_dsn: str; service_dsn: str
    journal_path: Path; spawn_dir: Path; workspace_root: Path
    spill_root: Path; skills_root: Path


def _server_info():
    server = get_server()
    info = server.get_postmaster_info()
    if info is None or info.socket_dir is None or info.port is None: raise RuntimeError("endpoint_unavailable")
    params = parse_dsn(server.get_uri("postgres")); params["host"] = str(info.socket_dir); params["port"] = str(info.port)
    params.pop("dbname", None)
    return params


def _dsn(params, db, user=None):
    data = dict(params, dbname=db)
    if user: data["user"] = user
    return make_dsn(**data)


def open_env(*, init=False, root=None):
    repo = Path(root or ROOT).resolve()
    data = repo / ".uidata"
    data.mkdir(mode=0o700, exist_ok=True); os.chmod(data, 0o700)
    for name in ("spawn", "workspace", "spill"):
        (data / name).mkdir(mode=0o700, exist_ok=True)
    params = _server_info()
    os.environ.setdefault("V24_SPILL_ROOT", str((data / "spill").resolve()))
    os.environ.setdefault("V24_SKILLS_ROOT", str((repo / "v24" / "ui" / "skills").resolve()))
    maintenance = _dsn(params, "postgres")
    admin = _dsn(params, DB_NAME, f"{DB_NAME}_admin")
    service = _dsn(params, DB_NAME, f"{DB_NAME}_service")
    for dsn in (maintenance, admin, service):
        validate_local_dsn(dsn, str(params["host"]))
    return UiEnv(repo, data, DB_NAME, Path(params["host"]), int(params["port"]), maintenance, admin, service,
                 data / "journal.jsonl", data / "spawn", (data / "workspace").resolve(),
                 (data / "spill").resolve(), (repo / "v24" / "ui" / "skills").resolve())


def acquire_lock(data_dir):
    path = Path(data_dir) / "lock"; fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try: pid = int(os.pread(fd, 32, 0).decode())
        except (ValueError, OSError): pid = "unknown"
        os.close(fd); raise AlreadyRunning(pid)
    os.ftruncate(fd, 0); os.write(fd, str(os.getpid()).encode()); os.fsync(fd); return fd


def release_lock(fd):
    if fd is not None:
        try: fcntl.flock(fd, fcntl.LOCK_UN)
        finally: os.close(fd)


def _oid(conn, name):
    with conn.cursor() as cur:
        cur.execute("SELECT oid::bigint FROM pg_database WHERE datname=%s", (name,)); row = cur.fetchone()
    return None if row is None else int(row[0])


def _role(conn, name):
    with conn.cursor() as cur:
        cur.execute("SELECT oid FROM pg_roles WHERE rolname=%s", (name,)); row = cur.fetchone()
    return None if row is None else int(row[0])


def _ensure_roles(conn, env):
    conn.autocommit = True
    with conn.cursor() as cur:
        for group in GROUPS:
            _create_or_check_group(conn, group)
        if _oid(conn, env.db_name) is None: cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(env.db_name)))
        cur.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO v24_owner").format(sql.Identifier(env.db_name)))
        for alias, group in ROLE_GROUPS.items():
            role = f"{env.db_name}_{alias}"
            if _role(conn, role) is None:
                cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                cur.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(role)))
            state = _role_state(conn, role)
            if state is None or tuple(state[1:]) != (False, True, False, False, True, False, False):
                raise RuntimeError("role_drift")
            cur.execute("SELECT parent.rolname FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid WHERE m.member=%s::regrole", (role,))
            if cur.fetchall() != [(group,)]: raise RuntimeError("role_drift")


def _sql_digests():
    files = {name: hashlib.sha256((ROOT / "v24" / "sql" / name).read_bytes()).hexdigest() for name in SQL_LOAD_ORDER}
    raw = json.dumps([[n, files[n]] for n in SQL_LOAD_ORDER], separators=(",", ":"), ensure_ascii=False).encode()
    return files, hashlib.sha256(raw).hexdigest()


def _fingerprint(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT proname, pg_get_function_identity_arguments(p.oid), pg_get_function_result(p.oid), md5(prosrc)
                       FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='v24'
                       ORDER BY proname, pg_get_function_identity_arguments(p.oid)""")
        funcs = [list(r) for r in cur.fetchall()]
        cur.execute("""SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
                       md5(coalesce(pg_get_expr(d.adbin,d.adrelid),''))
                       FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
                       LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                       WHERE n.nspname='v24' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum""")
        cols = [list(r) for r in cur.fetchall()]
    raw = json.dumps({"functions": funcs, "columns": cols}, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _current(env):
    files, manifest = _sql_digests()
    with contextlib.closing(connect(env.maintenance_dsn)) as maint:
        oid = _oid(maint, env.db_name)
    if oid is None:
        return {"format_version":2,"db_name":env.db_name,"database_oid":None,"file_digests":files,
                "sql_manifest_digest":manifest,"db_fingerprint":None,"ui_state_version":1,"w9_required":"v24.text.plain/v1"}
    with contextlib.closing(connect(env.admin_dsn)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='v24'")
            table_names = frozenset(row[0] for row in cur.fetchall())
            tables = len(table_names)
            if table_names != EXPECTED_TABLES: raise RuntimeError("schema_drift")
            cur.execute("SELECT count(*) FROM pg_class WHERE relnamespace='v24'::regnamespace AND relkind IN ('v','m')")
            if cur.fetchone()[0] != 0: raise RuntimeError("schema_drift")
            cur.execute("SELECT count(*) FROM pg_extension WHERE extnamespace='v24'::regnamespace")
            if cur.fetchone()[0] != 0: raise RuntimeError("schema_drift")
        fp = _fingerprint(conn) if tables else None
    return {"format_version":2,"db_name":env.db_name,"database_oid":oid,"file_digests":files,
            "sql_manifest_digest":manifest,"db_fingerprint":fp,"ui_state_version":1,"w9_required":"v24.text.plain/v1"}


def _write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.chmod(tmp, 0o600)
    with open(tmp, "rb") as f: os.fsync(f.fileno())
    os.replace(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(dfd)
    finally: os.close(dfd)


def init_env(env):
    loaded = env.data_dir / "loaded.json"
    # A failed first load may leave an empty database without metadata. Only
    # that empty, local database is eligible for completing initialization.
    empty_unrecorded = False
    if not loaded.exists():
        with contextlib.closing(connect(env.maintenance_dsn)) as maint:
            exists = _oid(maint, env.db_name) is not None
        if exists:
            with contextlib.closing(connect(_dsn(_server_info(), env.db_name))) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%%' AND n.nspname NOT LIKE 'pg_temp_%%'")
                    empty_unrecorded = cur.fetchone()[0] == 0
            if not empty_unrecorded: raise RuntimeError("schema_drift")
    current = None if empty_unrecorded else _current(env)
    if current is not None and current.get("database_oid") is None:
        current = None
    if not loaded.exists() and current is not None:
        raise RuntimeError("schema_drift")
    if loaded.exists() and current:
        old = json.loads(loaded.read_text())
        if all(old.get(k) == current.get(k) for k in current):
            return ["already_initialized"]
        raise RuntimeError("schema_drift")
    if loaded.exists(): raise RuntimeError("schema_drift")
    with contextlib.closing(connect(env.maintenance_dsn)) as conn: _ensure_roles(conn, env)
    params = _server_info()
    owner_dsn = _dsn(params, env.db_name)
    with contextlib.closing(connect(owner_dsn)) as conn:
        conn.autocommit = False
        with conn.cursor() as cur: cur.execute("SET ROLE v24_owner")
        load_stage(conn); conn.commit()
    current = _current(env); current["initialized_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(loaded, current)
    readme = env.workspace_root / "README.md"
    if not readme.exists(): readme.write_text("# v24 ui scratch\n", encoding="utf-8")
    return list(SQL_LOAD_ORDER)


def status_env(env):
    loaded = env.data_dir / "loaded.json"
    if not loaded.exists(): return {"reason":"uninitialized"}
    current = _current(env); old = json.loads(loaded.read_text())
    diffs = [k for k in current if old.get(k) != current.get(k)]
    return {"status":"ok" if not diffs else "schema_drift", "diffs":diffs, "db_name":env.db_name}


def migrate_env(env): raise RuntimeError("migration_unsupported")

def drop_env(env, *, yes=False):
    if not yes: raise RuntimeError("confirmation_required")
    loaded = env.data_dir / "loaded.json"
    if not loaded.exists(): raise RuntimeError("schema_drift")
    # Explicit reset is the recovery path for a drifted environment. Keep the
    # recorded identity check, but do not require status_env() to be healthy.
    expected_oid = json.loads(loaded.read_text())["database_oid"]
    with contextlib.closing(connect(env.maintenance_dsn)) as conn:
        conn.autocommit = True
        if _oid(conn, env.db_name) != expected_oid: raise RuntimeError("schema_drift")
        conn.cursor().execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(env.db_name)))
    for name in ("loaded.json", "journal.jsonl", "sessions.json", "turns.jsonl"): (env.data_dir / name).unlink(missing_ok=True)


def main(argv=None):
    p = argparse.ArgumentParser()
    ops = p.add_mutually_exclusive_group(required=True)
    for name in ("init", "status", "migrate", "reset"):
        ops.add_argument("--" + name, action="store_true")
    p.add_argument("--yes", action="store_true"); p.add_argument("--root")
    a = p.parse_args(argv)
    fd = None
    try:
        env = open_env(root=a.root)
        fd = acquire_lock(env.data_dir)
        if a.init: print(json.dumps({"status":"ok","loaded":init_env(env)})); return 0
        if a.status:
            status = status_env(env); print(json.dumps(status)); return 0 if status.get("status") == "ok" else 2
        if a.migrate: migrate_env(env)
        if a.reset: drop_env(env, yes=a.yes); return 0
        p.error("choose an operation")
    except AlreadyRunning as exc: print(f"already_running pid={exc.pid}", file=sys.stderr); return 3
    except RuntimeError as exc: print(str(exc), file=sys.stderr); return 2 if str(exc) in {"migration_unsupported","schema_drift","uninitialized"} else 1
    except (DatabaseError, ValueError, OSError):
        # Never print connection strings, SQL contents, or metadata payloads.
        print("environment_error", file=sys.stderr); return 2
    finally: release_lock(fd)

if __name__ == "__main__": raise SystemExit(main())
