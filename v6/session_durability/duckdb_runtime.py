"""Run-scoped DuckDB sessions and metadata-driven rehydration."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
import threading
from dataclasses import dataclass
from typing import Any

import duckdb
import psycopg2

from v6.source_ingress.duckdb_ingress import PostgresSourceResolver, snapshot_table

_DANGEROUS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|COPY|CREATE|ALTER|DROP|TRUNCATE|ATTACH|DETACH|"
    r"CONNECT|INSTALL|LOAD|CALL|PRAGMA|SET|RESET|EXPORT|SECRET)\b", re.I
)


class SessionError(RuntimeError):
    def __init__(self, type_: str, problem: str, solution: str):
        super().__init__(problem)
        self.envelope = {
            "success": False, "Type": type_, "Phase": "Session",
            "Problem": problem[:1000], "Solution": solution[:1000],
        }


@dataclass
class DuckSession:
    run_id: str
    mode: str
    worker_id: str
    generation: int
    connection: duckdb.DuckDBPyConnection

    def __post_init__(self) -> None:
        self.lock = threading.RLock()
        self.closed = False

    def close(self) -> None:
        if not self.closed:
            self.connection.close()
            self.closed = True

    def query_bounded(self, query: str, limit: int, *, timeout_ms: int = 120000) -> tuple[list[str], list[Any]]:
        if self.closed:
            raise SessionError("DUCK_SESSION_LOST", "DuckDB session is closed", "Start a new run or rehydrate a run_schema session.")
        with self.lock:
            timer = threading.Timer(max(1, timeout_ms) / 1000.0, self.connection.interrupt)
            timer.daemon = True
            timer.start()
            try:
                cur = self.connection.execute(query)
                rows = cur.fetchmany(limit)
                columns = [d[0] for d in cur.description]
                return columns, rows
            finally:
                timer.cancel()

    def create_view(self, name: str, select_sql: str, *, timeout_ms: int = 120000) -> dict[str, Any]:
        if self.closed:
            raise SessionError("DUCK_SESSION_LOST", "DuckDB session is closed", "Start a new run or rehydrate a run_schema session.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", name):
            raise SessionError("DUCK_IDENTIFIER_ERROR", f"invalid view name: {name!r}", "Use a simple SQL identifier.")
        query = select_sql.strip().rstrip(";")
        if not query or ";" in query or _DANGEROUS.search(query):
            raise SessionError("DUCK_READ_ONLY_VIOLATION", "view definition is not a single read-only SELECT", "Use one SELECT statement without DML, DDL, or external access.")
        with self.lock:
            self.connection.execute("BEGIN")
            timer = threading.Timer(max(1, timeout_ms) / 1000.0, self.connection.interrupt)
            timer.daemon = True
            timer.start()
            try:
                self.connection.execute(f'CREATE TEMP VIEW "{name}" AS {query}')
                cur = self.connection.execute(f'SELECT * FROM "{name}" LIMIT 501')
                preview = cur.fetchmany(501)
                columns = [d[0] for d in cur.description]
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise
            finally:
                timer.cancel()
        return {"name": name, "columns": columns, "preview": preview, "definition_hash": hashlib.sha256(query.encode()).hexdigest()}


class DuckSessionManager:
    def __init__(self, pg_uri: str, *, worker_id: str = "v6-worker-1", resolver: PostgresSourceResolver | None = None):
        if sys.platform != "darwin" or platform.machine() != "arm64":
            raise SessionError("DUCK_PLATFORM_UNSUPPORTED", "v6 DuckDB runtime only supports macOS arm64", "Run v6 on the locked macOS arm64 environment.")
        self.pg_uri = pg_uri
        self.worker_id = worker_id
        self.resolver = resolver
        self.sessions: dict[str, DuckSession] = {}
        self._manager_lock = threading.RLock()

    def _pg(self):
        conn = psycopg2.connect(self.pg_uri)
        conn.autocommit = True
        return conn

    def ensure_metadata_session(self, run_id: str, mode: str = "temp") -> None:
        if mode not in {"temp", "run_schema"}:
            raise SessionError("DUCK_ARGUMENT_ERROR", f"invalid session mode: {mode}", "Use temp or run_schema.")
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO duck_workbench_sessions(run_id, session_mode) VALUES (%s,%s) ON CONFLICT (run_id) DO NOTHING",
                    (run_id, mode),
                )
        finally:
            conn.close()

    def _mode_generation(self, run_id: str) -> tuple[str, int, str]:
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT session_mode, session_generation, status FROM duck_workbench_sessions WHERE run_id=%s", (run_id,))
                row = cur.fetchone()
            if row is None:
                raise SessionError("DUCK_SESSION_NOT_FOUND", f"no DuckDB session metadata for run {run_id}", "Create the run session before using the workbench.")
            return row
        finally:
            conn.close()

    @staticmethod
    def _open_connection() -> duckdb.DuckDBPyConnection:
        if duckdb.__version__ != "1.6.0.dev365":
            raise SessionError("DUCK_RUNTIME_UNSUPPORTED", f"unexpected duckdb package {duckdb.__version__}", "Install duckdb==1.6.0.dev365.")
        con = duckdb.connect()
        engine = con.execute("SELECT version()").fetchone()[0]
        if engine != "v2.0.0-alpha38615":
            con.close()
            raise SessionError("DUCK_RUNTIME_UNSUPPORTED", f"unexpected DuckDB engine {engine}", "Use the locked v2.0.0-alpha38615 wheel.")
        con.execute("SET autoinstall_known_extensions=false")
        con.execute("SET autoload_known_extensions=false")
        con.execute("SET enable_external_access=false")
        con.execute("SET memory_limit='512 MiB'")
        return con

    def get_or_open(self, run_id: str) -> DuckSession:
        with self._manager_lock:
            current = self.sessions.get(run_id)
            if current is not None and not current.closed:
                return current
            mode, generation, status = self._mode_generation(run_id)
            if status == "TERMINAL" or (mode == "temp" and status != "NEW"):
                if mode == "temp" and status != "TERMINAL":
                    conn = self._pg()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE duck_workbench_sessions SET status='LOST', last_error=%s::jsonb WHERE run_id=%s",
                                ('{"Type":"DUCK_SESSION_LOST","Problem":"temp session owner is no longer present"}', run_id),
                            )
                    finally:
                        conn.close()
                raise SessionError("DUCK_SESSION_LOST", f"session {run_id} is {status}", "Start a new run; temp sessions cannot be reopened by another worker.")
            session = DuckSession(run_id, mode, self.worker_id, generation + 1, self._open_connection())
            self.sessions[run_id] = session
            conn = self._pg()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE duck_workbench_sessions SET status='OPEN', worker_id=%s, session_generation=%s WHERE run_id=%s",
                        (self.worker_id, session.generation, run_id),
                    )
            finally:
                conn.close()
            if mode == "run_schema":
                try:
                    self.hydrate(run_id)
                except Exception:
                    session.close()
                    self.sessions.pop(run_id, None)
                    raise
            return session

    def close_run(self, run_id: str, *, lost: bool | None = None) -> None:
        with self._manager_lock:
            session = self.sessions.pop(run_id, None)
            mode = session.mode if session is not None else self._mode_generation(run_id)[0]
            if session is not None:
                session.close()
            final_lost = (mode == "temp") if lost is None else lost
            status = "LOST" if final_lost else "DEGRADED"
            conn = self._pg()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE duck_workbench_sessions SET status=%s, last_error=CASE WHEN %s THEN %s::jsonb ELSE last_error END, updated_at=now() WHERE run_id=%s",
                        (status, final_lost, '{"Type":"DUCK_SESSION_LOST","Problem":"temp session closed"}', run_id),
                    )
            finally:
                conn.close()

    def mark_terminal(self, run_id: str) -> None:
        self.close_run(run_id, lost=False)
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE duck_workbench_sessions SET status='TERMINAL' WHERE run_id=%s", (run_id,))
        finally:
            conn.close()

    def hydrate(self, run_id: str) -> dict[str, Any]:
        session = self.sessions.get(run_id)
        if session is None or session.closed:
            raise SessionError("DUCK_SESSION_LOST", f"no live session for run {run_id}", "Open the run through get_or_open().")
        if session.mode != "run_schema":
            raise SessionError("DUCK_ARGUMENT_ERROR", "hydrate is only available for run_schema", "Use run_schema for definition replay.")
        if self.resolver is None:
            raise SessionError("DUCK_SOURCE_NOT_FOUND", "no source resolver configured", "Configure source aliases before hydrating.")
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT artifact_name, artifact_kind, source_id, source_schema, source_table, definition_sql, depends_on, definition_hash "
                    "FROM duck_artifacts WHERE run_id=%s AND artifact_status='ACTIVE' ORDER BY artifact_kind, artifact_name",
                    (run_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        restored: list[str] = []
        for name, kind, source_id, schema_name, table_name, _, _, _ in rows:
            if kind == "source":
                snapshot_table(
                    session.connection, self.resolver, source_id=source_id,
                    schema_name=schema_name, table_name=table_name, artifact_name=name,
                )
                restored.append(name)
        pending = [r for r in rows if r[1] == "view"]
        while pending:
            progress = False
            for row in list(pending):
                name, _, _, _, _, definition_sql, depends_on, stored_hash = row
                deps = depends_on if isinstance(depends_on, list) else json.loads(depends_on or "[]")
                if all(dep in restored for dep in deps):
                    from v6.dialect_guardrails.duckdb_validation import validate_read_query
                    validated = validate_read_query(definition_sql, session.connection)
                    expected_hash = hashlib.sha256(validated.sql.encode()).hexdigest()
                    if stored_hash and stored_hash != expected_hash:
                        raise SessionError("DUCK_SESSION_DEGRADED", f"definition hash mismatch for {name}", "Discard the changed metadata or create a new run.")
                    session.create_view(name, validated.sql)
                    restored.append(name)
                    pending.remove(row)
                    progress = True
            if not progress:
                raise SessionError("DUCK_SESSION_DEGRADED", "view dependency graph cannot be rehydrated", "Remove missing dependencies or start a new run.")
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE duck_workbench_sessions SET status='OPEN' WHERE run_id=%s", (run_id,))
        finally:
            conn.close()
        return {"success": True, "run_id": run_id, "rehydrated": restored, "generation": session.generation}
