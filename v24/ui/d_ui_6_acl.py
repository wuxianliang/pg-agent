"""Narrow D-UI-6 ACL repair for an existing v24 UI environment.

Only --check and --apply are supported.  This helper never reloads SQL or
replays migrations; it grants the one missing public wrapper privilege and
atomically refreshes the two loaded.json digests.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from psycopg2 import Error as DatabaseError, connect

from .env import (
    DB_NAME,
    _current,
    _dsn,
    _oid,
    _server_info,
    SQL_LOAD_ORDER,
    AlreadyRunning,
    acquire_lock,
    open_env,
    release_lock,
)

FUNCTION = "v24.install(uuid,uuid,bytea,bytea,text)"
OLD_PERMISSIONS_SHA256 = "578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe"
SQL_ORDER = tuple(SQL_LOAD_ORDER)


def _loaded(env):
    path = env.data_dir / "loaded.json"
    if not path.exists():
        raise RuntimeError("uninitialized")
    return path, json.loads(path.read_text(encoding="utf-8"))


def _validate_identity(env, loaded):
    if loaded.get("db_name") != DB_NAME or env.db_name != DB_NAME:
        raise RuntimeError("database_identity")
    params = _server_info()
    if str(env.socket_dir) != str(params["host"]) or env.port != int(params["port"]):
        raise RuntimeError("server_identity")
    with contextlib.closing(connect(env.maintenance_dsn)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('data_directory'), system_identifier::text FROM pg_control_system()")
            data_directory, system_identifier = cur.fetchone()
        oid = _oid(conn, DB_NAME)
    expected_data = str((env.repo_root / ".pgdata").resolve())
    if str(Path(data_directory).resolve()) != expected_data or not system_identifier:
        raise RuntimeError("server_identity")
    if oid is None or loaded.get("database_oid") != oid:
        raise RuntimeError("database_oid")
    current = _current(env)
    if current.get("database_oid") != oid or loaded.get("db_fingerprint") != current.get("db_fingerprint"):
        raise RuntimeError("database_oid")
    if loaded.get("db_name") != current.get("db_name") or loaded.get("w9_required") != current.get("w9_required"):
        raise RuntimeError("metadata_identity")
    if set(loaded.get("file_digests", {})) != set(SQL_ORDER):
        raise RuntimeError("metadata_drift")
    if set(loaded) != set(current) | {"initialized_at"} or loaded.get("format_version") != 2 or loaded.get("ui_state_version") != 1:
        raise RuntimeError("metadata_drift")
    if current["file_digests"]["50_permissions.sql"] != "3f5faef04cdd18e992336cf093bb535d78377ce01154cf57a58e34d048de7ee2":
        raise RuntimeError("permissions_source_drift")
    for name in SQL_ORDER:
        if name != "50_permissions.sql" and loaded["file_digests"].get(name) != current["file_digests"].get(name):
            raise RuntimeError("metadata_drift")
    return current


def _acl(env):
    with contextlib.closing(connect(env.admin_dsn)) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
                       a.privilege_type, a.is_grantable
                  FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
                 WHERE p.oid=%s::regprocedure
                 ORDER BY 1,2
            """, (FUNCTION,))
            rows = cur.fetchall()
        conn.rollback()
    return tuple((str(role), str(priv), bool(grantable)) for role, priv, grantable in rows)


def _has_install(env):
    with contextlib.closing(connect(env.admin_dsn)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT has_function_privilege(session_user,%s,'EXECUTE')", (FUNCTION,))
            value = bool(cur.fetchone()[0])
        conn.rollback()
    return value


def _state(env, loaded, current):
    old_acl = tuple(sorted((("v24_operator", "EXECUTE", False), ("v24_owner", "EXECUTE", False), ("v24_service", "EXECUTE", False))))
    new_acl = tuple(sorted(old_acl + (("v24_admin", "EXECUTE", False),)))
    acl = _acl(env)
    old_digest = loaded.get("file_digests", {}).get("50_permissions.sql")
    new_digest = current.get("file_digests", {}).get("50_permissions.sql")
    old_manifest = hashlib.sha256(json.dumps([[name, loaded["file_digests"][name]] for name in SQL_ORDER], separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    metadata_old = old_digest == OLD_PERMISSIONS_SHA256 and loaded.get("sql_manifest_digest") == old_manifest
    metadata_new = old_digest == new_digest and loaded.get("sql_manifest_digest") == current.get("sql_manifest_digest")
    if acl == old_acl and metadata_old:
        return "preupgrade"
    if acl == new_acl and metadata_old:
        return "acl_upgraded_metadata_old"
    if acl == new_acl and metadata_new:
        return "completed"
    raise RuntimeError("acl_metadata_drift")


def _write_loaded(path: Path, loaded: dict, current: dict):
    updated = dict(loaded)
    updated["file_digests"] = dict(loaded["file_digests"])
    updated["file_digests"]["50_permissions.sql"] = current["file_digests"]["50_permissions.sql"]
    updated["sql_manifest_digest"] = current["sql_manifest_digest"]
    fd, raw = tempfile.mkstemp(prefix="loaded.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(updated, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(raw, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(raw):
            os.unlink(raw)


def apply_acl(env):
    path, loaded = _loaded(env)
    current = _validate_identity(env, loaded)
    state = _state(env, loaded, current)
    if state == "completed":
        return state
    if state == "acl_upgraded_metadata_old":
        _write_loaded(path, loaded, current)
        return "completed"
    # The only SQL this helper is allowed to execute.
    params = _server_info()
    grant_dsn = _dsn(params, DB_NAME)
    with contextlib.closing(connect(grant_dsn)) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("GRANT EXECUTE ON FUNCTION v24.install(uuid,uuid,bytea,bytea,text) TO v24_admin")
        conn.commit()
    if not _has_install(env):
        raise RuntimeError("acl_not_applied")
    _write_loaded(path, loaded, current)
    return "completed"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.check == args.apply:
        parser.error("choose exactly one of --check/--apply")
    fd = None
    try:
        env = open_env()
        fd = acquire_lock(env.data_dir)
        path, loaded = _loaded(env)
        current = _validate_identity(env, loaded)
        state = _state(env, loaded, current)
        if args.apply:
            state = apply_acl(env)
        print(json.dumps({"status": state}, sort_keys=True))
        return 0
    except AlreadyRunning as exc:
        print(f"already_running pid={exc.pid}", file=sys.stderr)
        return 3
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (DatabaseError, ValueError, OSError):
        print("environment_error", file=sys.stderr)
        return 2
    finally:
        release_lock(fd)


if __name__ == "__main__":
    raise SystemExit(main())
