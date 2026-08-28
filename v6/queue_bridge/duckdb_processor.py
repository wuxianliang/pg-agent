"""DuckDB queue processor. It executes outside PostgreSQL and returns a bounded result."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from v6.session_durability.duckdb_runtime import DuckSessionManager, SessionError
from v6.dialect_guardrails.duckdb_validation import QueryValidationError, validate_read_query
from v6.budget_observability.duckdb_results import bounded_result
from v6.budget_observability.duckdb_errors import error_envelope
from v6.budget_observability.duck_budget import DuckBudget
from v6.source_ingress.duckdb_ingress import IngressError, PostgresSourceResolver, SnapshotBudget, snapshot_table


class DuckDBWorkerProcessor:
    def __init__(self, pg_uri: str, *, resolver: PostgresSourceResolver | None = None, worker_id: str = "v6-worker-1"):
        self.pg_uri = pg_uri
        self.worker_id = worker_id
        self.resolver = resolver
        self.budget = DuckBudget()
        self.budget.validate()
        self.sessions = DuckSessionManager(pg_uri, worker_id=worker_id, resolver=resolver)
        self._run_locks: dict[str, threading.Lock] = {}
        self._completed: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        for run_id in list(self.sessions.sessions):
            self.sessions.close_run(run_id)
        self._run_locks.clear()
        self._completed.clear()

    def _run_lock(self, run_id: str) -> threading.Lock:
        with self._lock:
            return self._run_locks.setdefault(run_id, threading.Lock())

    def _pg(self):
        import psycopg2
        conn = psycopg2.connect(self.pg_uri)
        conn.autocommit = True
        return conn

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _operation(self, payload: dict[str, Any]):
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT request_id, run_id, op_seq, op_kind, status, request_payload, "
                    "definition_hash, worker_id, started_at FROM duck_operations WHERE request_id=%s",
                    (payload.get("request_id"),),
                )
                return cur.fetchone()
        finally:
            conn.close()

    def _infer_dependencies(self, run_id: str, query: str) -> list[str]:
        import re
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT artifact_name FROM duck_artifacts WHERE run_id=%s AND artifact_status='ACTIVE'", (run_id,))
                names = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()
        # Conservative inference: false positives only make drop/replay safer.
        return [name for name in names if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", query, re.I)]

    def _has_dependents(self, run_id: str, artifact_name: str) -> bool:
        conn = self._pg()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM duck_artifacts WHERE run_id=%s AND artifact_status='ACTIVE' AND depends_on ? %s LIMIT 1",
                    (run_id, artifact_name),
                )
                return cur.fetchone() is not None
        finally:
            conn.close()

    def _error(self, type_: str, problem: str, solution: str, *, request_id: str, op_seq: int, retryable: bool = False) -> dict[str, Any]:
        return {
            "success": False, "Type": type_, "Phase": "DuckDB", "Problem": problem[:1000],
            "Solution": solution[:1000], "request_id": request_id, "op_seq": op_seq,
            "worker_id": self.worker_id, "retryable": retryable,
        }

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or "")
        if not request_id:
            return self._error("DUCK_ARGUMENT_ERROR", "request_id is required", "Create a queue operation through a v6 scheduler tool.", request_id="", op_seq=0)
        row = self._operation(payload)
        if row is None:
            return self._error("DUCK_OPERATION_NOT_FOUND", f"unknown request_id: {request_id}", "Do not publish hand-written DuckDB queue messages.", request_id=request_id, op_seq=int(payload.get("op_seq") or 0))
        db_request, run_id, op_seq, op_kind, status, request_payload, stored_hash, claimed_worker, started_at = row
        op_seq = int(op_seq)
        if db_request != request_id or str(payload.get("run_id")) != run_id or int(payload.get("op_seq") or 0) != op_seq:
            return self._error("DUCK_OPERATION_CONFLICT", "queue payload does not match PostgreSQL operation metadata", "Retry using the original operation message.", request_id=request_id, op_seq=op_seq)
        if status in {"SUCCEEDED", "FAILED", "DLQ", "REPLAYED"}:
            return {"success": True, "replayed": True, "request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id}
        if request_id in self._completed:
            return dict(self._completed[request_id])
        request_payload = request_payload if isinstance(request_payload, dict) else json.loads(request_payload or "{}")
        if stored_hash is not None and str(payload.get("payload_hash") or "") != stored_hash:
            return self._error("DUCK_OPERATION_CONFLICT", "payload hash does not match operation metadata", "Retry using the original operation message.", request_id=request_id, op_seq=op_seq)

        conn = self._pg()
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT last_completed_op_seq, session_mode, status FROM duck_workbench_sessions WHERE run_id=%s FOR UPDATE", (run_id,))
                session_row = cur.fetchone()
                if session_row is None:
                    conn.rollback()
                    return self._error("DUCK_SESSION_NOT_FOUND", f"missing session metadata for {run_id}", "Create the workbench session before publishing operations.", request_id=request_id, op_seq=op_seq)
                last_completed, mode, session_status = session_row
                if op_seq != int(last_completed) + 1:
                    conn.rollback()
                    return {
                        "success": False, "status": "retry", "retryable": True,
                        "Type": "DUCK_OPERATION_OUT_OF_ORDER", "Phase": "Ordering",
                        "Problem": f"operation {op_seq} arrived after last completed {last_completed}",
                        "Solution": "Wait for the preceding operation to complete.",
                        "request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id,
                    }
                if session_status == "TERMINAL" or (session_status == "LOST" and mode != "run_schema"):
                    conn.rollback()
                    return self._error("DUCK_SESSION_LOST", f"session is {session_status}", "Start a new run or use run_schema replay.", request_id=request_id, op_seq=op_seq)
                stale = started_at is None or (time.time() - started_at.timestamp()) > 300
                if status == "RUNNING" and mode == "temp" and stale:
                    conn.rollback()
                    return self._error(
                        "DUCK_SESSION_LOST", "a previous temp worker lease expired",
                        "Start a new run; temp sessions cannot be recovered after worker loss.",
                        request_id=request_id, op_seq=op_seq,
                    )
                claimable = status == "QUEUED" or (
                    status == "RUNNING" and mode == "run_schema" and stale
                )
                if not claimable:
                    conn.rollback()
                    return {
                        "success": False, "status": "retry", "retryable": True,
                        "Type": "DUCK_OPERATION_CLAIMED", "Phase": "Ordering",
                        "Problem": f"operation is already {status} by {claimed_worker}",
                        "Solution": "Wait for the current owner or recover through run_schema.",
                        "request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id,
                    }
                cur.execute(
                    "UPDATE duck_operations SET status='RUNNING', worker_id=%s, started_at=now() "
                    "WHERE request_id=%s AND status=%s AND (status='QUEUED' OR started_at IS NULL OR started_at < now()-interval '300 seconds')",
                    (self.worker_id, request_id, status),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return {
                        "success": False, "status": "retry", "retryable": True,
                        "Type": "DUCK_OPERATION_CLAIM_CONFLICT", "Phase": "Ordering",
                        "Problem": "operation claim changed concurrently", "Solution": "Retry after visibility timeout.",
                        "request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id,
                    }
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        with self._run_lock(run_id):
            try:
                session = self.sessions.get_or_open(run_id)
                if op_kind == "register":
                    if self.resolver is None:
                        raise IngressError("DUCK_SOURCE_NOT_FOUND", "no source resolver configured", "Configure source aliases.")
                    result = snapshot_table(
                        session.connection, self.resolver,
                        source_id=request_payload["source_id"], schema_name=request_payload["schema_name"],
                        table_name=request_payload["table_name"], artifact_name=request_payload["artifact_name"],
                        budget=SnapshotBudget(
                            max_rows=min(int(request_payload.get("max_rows") or self.budget.source_rows), self.budget.source_rows),
                            max_bytes=min(int(request_payload.get("max_bytes") or self.budget.source_bytes), self.budget.source_bytes),
                        ),
                    ).as_dict()
                    result["artifact"] = {
                        "artifact_name": request_payload["artifact_name"], "artifact_kind": "source",
                        "source_id": request_payload["source_id"], "source_schema": request_payload["schema_name"],
                        "source_table": request_payload["table_name"], "columns": result["columns"],
                        "definition_hash": hashlib.sha256(json.dumps(result["columns"], sort_keys=True).encode()).hexdigest(),
                    }
                elif op_kind == "query":
                    artifact = request_payload["artifact_name"]
                    validated = validate_read_query(request_payload["query"], session.connection)
                    dependencies = request_payload.get("depends_on") or self._infer_dependencies(run_id, validated.sql)
                    result = session.create_view(
                        artifact, validated.sql,
                        timeout_ms=min(int(request_payload.get("timeout_ms") or self.budget.timeout_ms), self.budget.timeout_ms),
                    )
                    result = {
                        "success": True, "artifact": {
                            "artifact_name": artifact, "artifact_kind": "view",
                            "definition_sql": validated.sql, "depends_on": dependencies,
                            "columns": [{"name": c} for c in result["columns"]], "definition_hash": result["definition_hash"],
                        },
                        **bounded_result(result["columns"], result["preview"], 500),
                    }
                elif op_kind == "brief_query":
                    name = request_payload["artifact_name"]; limit = int(request_payload.get("limit") or 20)
                    columns, rows = session.query_bounded(
                        f'SELECT * FROM "{name}" LIMIT {limit + 1}', limit + 1,
                        timeout_ms=self.budget.timeout_ms,
                    )
                    result = {"success": True, "artifact_name": name, **bounded_result(columns, rows, limit)}
                elif op_kind == "list":
                    rows = session.connection.execute("SHOW TABLES").fetchall()
                    result = {"success": True, "artifacts": [{"name": row[0]} for row in rows[:1000]], "truncated": len(rows) > 1000}
                elif op_kind == "columns":
                    name = request_payload["artifact_name"]
                    rows = session.connection.execute(f'DESCRIBE "{name}"').fetchall()
                    result = {"success": True, "artifact_name": name, "columns": [
                        {"name": row[0], "type": row[1], "null": row[2]}
                        for row in rows[:1000]
                    ], "truncated": len(rows) > 1000}
                elif op_kind == "show_create":
                    name = request_payload["artifact_name"]
                    result = {"success": True, "artifact_name": name, "definition_sql": request_payload.get("definition_sql")}
                elif op_kind == "drop":
                    name = request_payload["artifact_name"]
                    if self._has_dependents(run_id, name):
                        return {
                            "success": False, "Type": "DUCK_DEPENDENCY_EXISTS", "Phase": "Validation",
                            "Problem": f"active artifact depends on {name}",
                            "Solution": "Drop dependent views first; v6 does not execute CASCADE.",
                            "request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id,
                        }
                    view_exists = session.connection.execute(
                        "SELECT count(*) FROM duckdb_views() WHERE view_name=?", [name]
                    ).fetchone()[0]
                    table_exists = session.connection.execute(
                        "SELECT count(*) FROM duckdb_tables() WHERE table_name=?", [name]
                    ).fetchone()[0]
                    if view_exists:
                        session.connection.execute(f'DROP VIEW "{name}"')
                    elif table_exists:
                        session.connection.execute(f'DROP TABLE "{name}"')
                    else:
                        return self._error(
                            "DUCK_ARTIFACT_NOT_FOUND", f"artifact does not exist: {name}",
                            "Use wb_duck_list to inspect the current run.",
                            request_id=request_id, op_seq=op_seq,
                        )
                    result = {"success": True, "dropped": True, "artifact": {"artifact_name": name, "artifact_kind": "view"}}
                else:
                    return self._error("DUCK_ARGUMENT_ERROR", f"unsupported operation: {op_kind}", "Use one of the registered v6 DuckDB operations.", request_id=request_id, op_seq=op_seq)
                result.update({"request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id})
                self._completed[request_id] = dict(result)
                return result
            except (IngressError, SessionError, QueryValidationError) as exc:
                return {**getattr(exc, "envelope", error_envelope(exc)), "request_id": request_id, "op_seq": op_seq, "worker_id": self.worker_id}
            except Exception as exc:
                return {**error_envelope(exc, request_id=request_id, op_seq=op_seq), "worker_id": self.worker_id}
