"""The sole v23 lifecycle entry: fenced T1 -> one DB-free Worker -> T2.

Owners and runtimes are process-local resources. Only v23_runs is durable truth.
A lost fence is never reconnected, and its Workers are never replayed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID, uuid4
import copy
import hashlib
import json
import math
import os
import re
import select
import threading
import time

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, make_dsn, parse_dsn

from v23.disposition import canonical_uuid, integer
from v23.worker import (MAX_RESULT_BYTES, TurnReceipt, WorkerRequest, WorkerContractError,
                        WorkerExecutionError, validate_request, validate_receipt, storage_safe_json)

OPS = frozenset({"start", "poll", "wait", "cancel", "steer", "respond"})
CHANNEL = "v23_run_changed"
FENCE = (23, 23001)
_MUTATIONS = frozenset({"start", "cancel", "steer", "respond"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RETRY_CODES = frozenset({"40001", "40P01"})


@dataclass(frozen=True)
class HostActor:
    """Trusted Host capability; child responses still require ParentActor."""


@dataclass(frozen=True)
class ParentActor:
    parent_run_id: str

    def __post_init__(self) -> None:
        canonical_uuid(self.parent_run_id)


class ControlError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WorkerError(RuntimeError):
    def __init__(self, response: dict[str, Any]):
        self.code = "worker_failed"
        self.response = copy.deepcopy(response)
        super().__init__(self.code)


@dataclass
class _Owner:
    digest: str
    worker_request: WorkerRequest
    generation: UUID
    operation: str
    actor: Any
    request: dict[str, Any]
    thread: threading.Thread = field(default_factory=threading.current_thread)
    done: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    error: BaseException | None = None
    admission_snapshot: dict[str, Any] | None = None


@dataclass
class _Runtime:
    identity: tuple[str, int, str]
    config: dict[str, str]
    conn: Any
    pid: int = field(default_factory=os.getpid)
    generation: UUID = field(default_factory=uuid4)
    mutex: Any = field(default_factory=threading.RLock)
    lost: bool = False
    closing: bool = False
    closed: bool = False
    references: int = 0


# Lock order: runtime.mutex -> _owners_lock -> SQL row locks.
# _runtimes_lock is only for resource construction/reference counting, never joins.
_runtimes: dict[tuple[str, int, str], _Runtime] = {}
_runtimes_lock = threading.RLock()
_owners: dict[tuple[tuple[str, int, str], str, str], _Owner] = {}
_owners_lock = threading.RLock()
_worker_scope = threading.local()


class _CommitUncertain(Exception):
    """The caller has no commit acknowledgement; inspect durable cache, not Worker."""


def _canonical(value: Any) -> bytes:
    # Request digests and the frozen T2 receipt share the Worker DTO storage boundary.
    return storage_safe_json(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: copy.deepcopy(value) for key, value in row.items() if key != "op_cache"}
    for key in ("run_id", "parent_run_id", "active_operation_id"):
        if result.get(key) is not None:
            result[key] = str(result[key])
    return {"schema_version": 1, **result}


class Control:
    def __init__(self, dsn: str, worker: Any):
        params = parse_dsn(dsn)
        host = params.get("host", "")
        if not host.startswith("/") or "," in host or params.get("hostaddr"):
            raise ValueError("v23 accepts only local PostgreSQL Unix-domain connections")
        if params.get("user") != "v23_control":
            raise ControlError("invalid_control_role")
        host = os.path.realpath(host)
        params["host"] = host
        self.dsn = make_dsn(**params)
        self.worker = worker
        self._closed = False
        changed = []
        # Normalize using libpq's actual endpoint/defaults, not the raw DSN spelling.
        candidate = psycopg2.connect(self.dsn, application_name="v23_control_fence")
        try:
            effective = candidate.get_dsn_parameters()
            with candidate.cursor() as cur:
                cur.execute("SELECT current_database(), session_user, current_user")
                database, session_user, current_user = cur.fetchone()
            candidate.commit()
            if session_user != "v23_control" or current_user != "v23_control":
                raise ControlError("invalid_control_role")
            if database != effective["dbname"]:
                raise ControlError("invalid_database_identity")
            self.db_identity = (host, int(effective["port"]), database)
            # Credentials/role/options must also agree when sharing a session.
            config = {key: value for key, value in effective.items()
                      if key not in {"host", "port", "dbname", "application_name",
                                     "fallback_application_name"}}
            with _runtimes_lock:
                runtime = _runtimes.get(self.db_identity)
                if runtime is not None and runtime.pid != os.getpid():
                    raise ControlError("control_runtime_forked")
                if runtime is not None and not runtime.lost and not runtime.closed:
                    # libpq may not yet know that the server killed its backend.
                    # Verify the existing fenced session before deciding to reuse it.
                    self._runtime = runtime
                    try:
                        with self._tx("runtime_check"):
                            pass
                    except ControlError as exc:
                        if exc.code != "control_runtime_lost":
                            raise
                if runtime is not None and not runtime.lost and not runtime.closed:
                    if runtime.closing:
                        raise ControlError("control_runtime_closed")
                    if runtime.config != config:
                        raise ControlError("control_runtime_incompatible")
                    self._runtime = runtime
                else:
                    with candidate.cursor() as cur:
                        cur.execute("SELECT pg_try_advisory_lock(%s, %s)", FENCE)
                        acquired = cur.fetchone()[0]
                    candidate.commit()
                    if not acquired:
                        raise ControlError("control_runtime_busy")
                    runtime = _Runtime(self.db_identity, config, candidate)
                    self._runtime = runtime
                    candidate = None  # runtime now owns the fenced session
                    try:
                        changed = self._recover_orphans()
                    except BaseException:
                        self._lose_runtime()
                        raise
                    _runtimes[self.db_identity] = runtime
                runtime.references += 1
        finally:
            if candidate is not None:
                candidate.close()
        for snapshot in changed:
            self._post_commit_notify(snapshot)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self, timeout_seconds: float = 5.0) -> None:
        """Release this handle; last handle drains owners, then releases the fence.

        A deadline does not kill Workers: it fences them out and leaves pending
        for a new runtime's fail-closed recovery.
        """
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise ValueError("finite nonnegative close timeout required")
        runtime = self._runtime
        self._check_pid()
        with _runtimes_lock:
            if self._closed:
                return
            self._closed = True
            runtime.references -= 1
            if runtime.references:
                return
            with runtime.mutex:
                runtime.closing = True
        deadline = time.monotonic() + timeout_seconds
        while True:
            with runtime.mutex, _owners_lock:
                owners = [owner for key, owner in _owners.items()
                          if key[0] == self.db_identity and owner.generation == runtime.generation]
            if not owners or time.monotonic() >= deadline:
                break
            # Never hold resource/owner/SQL locks while waiting.
            owners[0].done.wait(min(0.05, max(0, deadline - time.monotonic())))
        with runtime.mutex:
            runtime.closed = True
            if owners:
                runtime.lost = True
            runtime.conn.close()

    def _check_pid(self) -> None:
        if self._runtime.pid != os.getpid():
            raise ControlError("control_runtime_forked")

    def _lose_runtime(self) -> None:
        runtime = self._runtime
        with runtime.mutex:
            runtime.lost = True
            # Closing a broken session releases any remaining fence; never reopen it.
            runtime.conn.close()

    def _ensure_runtime(self, *, admission: bool = False) -> None:
        self._check_pid()
        runtime = self._runtime
        if runtime.lost or runtime.conn.closed:
            self._lose_runtime()
            raise ControlError("control_runtime_lost")
        if runtime.closed or admission and runtime.closing:
            raise ControlError("control_runtime_closed")

    def _commit(self, conn: Any, phase: str) -> None:
        """Private injection seam: a test may fail before or after real commit."""
        conn.commit()

    @contextmanager
    def _tx(self, phase: str = "mutation", *, admission: bool = False):
        runtime = self._runtime
        with runtime.mutex, _owners_lock:
            self._ensure_runtime(admission=admission)
            conn = runtime.conn
            committing = False
            try:
                if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                    conn.rollback()
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("BEGIN")
                    # Verify ownership without reacquiring/recounting the session lock.
                    cur.execute("""SELECT session_user, current_user, EXISTS (
                        SELECT 1 FROM pg_locks WHERE locktype='advisory'
                        AND pid=pg_backend_pid() AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
                        AND classid=%s AND objid=%s AND objsubid=2 AND granted) AS fenced""", FENCE)
                    identity = cur.fetchone()
                    if (identity["session_user"] != "v23_control" or identity["current_user"] != "v23_control"
                            or not identity["fenced"]):
                        self._lose_runtime()
                        raise ControlError("control_runtime_lost")
                    yield cur
                    committing = True
                    self._commit(conn, phase)
            except BaseException as exc:
                broken = (conn.closed or isinstance(exc, (psycopg2.InterfaceError, psycopg2.OperationalError))
                          and getattr(exc, "pgcode", None) not in _RETRY_CODES)
                if broken:
                    self._lose_runtime()
                else:
                    try:
                        conn.rollback()
                    except psycopg2.Error:
                        self._lose_runtime()
                if committing and getattr(exc, "pgcode", None) not in _RETRY_CODES:
                    raise _CommitUncertain() from exc
                if runtime.lost and not isinstance(exc, ControlError):
                    raise ControlError("control_runtime_lost") from exc
                raise

    @contextmanager
    def _read_tx(self):
        self._check_pid()
        conn = psycopg2.connect(self.dsn, application_name="v23_control_read")
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    yield cur
        finally:
            conn.close()

    def _notify(self, snapshot: Mapping[str, Any]) -> None:
        conn = psycopg2.connect(self.dsn, application_name="v23_notify")
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps({
                    "run_id": snapshot["run_id"], "revision": snapshot["revision"]})))
        finally:
            conn.close()

    def _post_commit_notify(self, snapshot: Mapping[str, Any]) -> None:
        # Wake hint only. Even injected notifier failure cannot undo/retry a mutation.
        try:
            self._notify(snapshot)
        except Exception:
            pass

    def _owner_key(self, run_id: str, request_id: str):
        return (self.db_identity, run_id, request_id)

    def _live_owner(self, row: Mapping[str, Any], entry: Mapping[str, Any]) -> _Owner | None:
        key = self._owner_key(str(row["run_id"]), str(row["active_operation_id"]))
        owner = _owners.get(key)
        if owner is None or owner.generation != self._runtime.generation or owner.done.is_set() or not owner.thread.is_alive():
            return None
        self._match_active(row, entry, owner)
        return owner

    @staticmethod
    def _match_active(row: Mapping[str, Any], entry: Mapping[str, Any], owner: _Owner | None = None) -> None:
        if (row["status"] != "running" or row["active_operation_id"] is None
                or row["active_base_revision"] != entry["admission_revision"]
                or row["active_input_digest"] != entry["input_digest"]):
            raise ControlError("active_operation_conflict")
        if owner is not None:
            wr = owner.worker_request
            if (str(wr.run_id) != str(row["run_id"]) or owner.request["request_id"] != str(row["active_operation_id"])
                    or wr.base_revision != entry["admission_revision"] or wr.input_digest != entry["input_digest"]
                    or owner.digest != entry["request_digest"] or owner.operation != entry["operation"]
                    or Control._actor_digest(owner.actor) != entry["actor_digest"]):
                raise ControlError("active_operation_conflict")

    @staticmethod
    def _validate_entry(entry: Any) -> None:
        fields = {"state", "operation", "actor_digest", "request_digest", "input_digest",
                  "admission_revision", "response", "error_code"}
        if type(entry) is not dict or set(entry) != fields:
            raise ControlError("invalid_op_cache")
        if entry["state"] not in {"pending", "done", "recovered"} or entry["operation"] not in _MUTATIONS:
            raise ControlError("invalid_op_cache")
        for key in ("actor_digest", "request_digest"):
            if type(entry[key]) is not str or _HEX.fullmatch(entry[key]) is None:
                raise ControlError("invalid_op_cache")
        if entry["operation"] == "cancel":
            if entry["state"] != "done" or entry["input_digest"] is not None or entry["admission_revision"] is not None:
                raise ControlError("invalid_op_cache")
        elif (type(entry["input_digest"]) is not str or _HEX.fullmatch(entry["input_digest"]) is None
              or type(entry["admission_revision"]) is not int or not 1 <= entry["admission_revision"] <= 2**63 - 1):
            raise ControlError("invalid_op_cache")
        if entry["state"] == "pending":
            if entry["response"] is not None or entry["error_code"] is not None:
                raise ControlError("invalid_op_cache")
        else:
            response = entry["response"]
            if (type(response) is not dict or response.get("schema_version") != 1
                    or response.get("operation") != entry["operation"] or type(response.get("snapshot")) is not dict
                    or "op_cache" in response["snapshot"]):
                raise ControlError("invalid_op_cache")
            if entry["state"] == "recovered":
                if (entry["error_code"] != "owner_lost" or response.get("outcome") != "recovered_orphan"
                        or response.get("error_code") != "owner_lost"):
                    raise ControlError("invalid_op_cache")
            elif entry["error_code"] not in {None, "worker_failed", "invalid_worker_receipt"}:
                raise ControlError("invalid_op_cache")

    def _entry(self, row: Mapping[str, Any], op: str, actor: Any, req: Mapping[str, Any]) -> dict | None:
        entry = row["op_cache"].get(req["request_id"])
        if entry is None:
            return None
        self._validate_entry(entry)
        if (entry["operation"] != op or entry["actor_digest"] != self._actor_digest(actor)
                or entry["request_digest"] != self._request_digest(op, actor, req)):
            raise ControlError("idempotency_conflict")
        return entry

    @staticmethod
    def _replay(entry: Mapping[str, Any]) -> dict[str, Any]:
        response = copy.deepcopy(entry["response"])
        if entry["error_code"] == "worker_failed":
            raise WorkerError(response)
        if entry["error_code"] == "invalid_worker_receipt":
            error = WorkerContractError("invalid_worker_receipt")
            error.code = "invalid_worker_receipt"
            error.response = response
            raise error
        return response

    def _recover_row(self, cur: Any, row: dict[str, Any]) -> dict[str, Any]:
        request_id = str(row["active_operation_id"])
        entry = row["op_cache"].get(request_id)
        self._validate_entry(entry)
        if entry["state"] != "pending":
            raise ControlError("active_operation_conflict")
        self._match_active(row, entry)
        row.update(status="stopped", close_reason="cancelled", cancel_requested=True,
                   revision=row["revision"] + 1)
        self._clear_active(row)
        response = {"schema_version": 1, "operation": entry["operation"], "outcome": "recovered_orphan",
                    "error_code": "owner_lost", "snapshot": _snapshot(row)}
        row["op_cache"][request_id] = {**entry, "state": "recovered", "response": response, "error_code": "owner_lost"}
        self._write(cur, row)
        return response

    def _recover_orphans(self) -> list[dict[str, Any]]:
        changed = []
        with self._tx("recovery") as cur:
            cur.execute("SELECT * FROM v23_runs WHERE status='running' ORDER BY run_id FOR UPDATE")
            for row in cur.fetchall():
                entry = row["op_cache"].get(str(row["active_operation_id"]))
                self._validate_entry(entry)
                if self._live_owner(row, entry) is None:
                    changed.append(self._recover_row(cur, row)["snapshot"])
        return changed

    @staticmethod
    def _clear_active(row: dict[str, Any]) -> None:
        row.update(active_operation_id=None, active_base_revision=None, active_input_digest=None)

    @staticmethod
    def _write(cur: Any, row: Mapping[str, Any]) -> None:
        cur.execute("""UPDATE v23_runs SET status=%s, revision=%s, turns_used=%s,
                       latest_receipt=%s, active_operation_id=%s, active_base_revision=%s,
                       active_input_digest=%s, cancel_requested=%s, op_cache=%s, close_reason=%s
                       WHERE run_id=%s""", (
            row["status"], row["revision"], row["turns_used"],
            Json(row["latest_receipt"]) if row["latest_receipt"] is not None else None,
            row["active_operation_id"], row["active_base_revision"], row["active_input_digest"],
            row["cancel_requested"], Json(row["op_cache"]), row["close_reason"], str(row["run_id"])))

    @staticmethod
    def _authorize(actor: Any, row: Mapping[str, Any], *, respond: bool = False) -> None:
        if isinstance(actor, HostActor) and (not respond or row["parent_run_id"] is None):
            return
        if isinstance(actor, ParentActor) and str(row["parent_run_id"]) == actor.parent_run_id:
            return
        raise ControlError("not_found_or_unauthorized")

    def _authorize_op(self, op: str, actor: Any, row: Mapping[str, Any]) -> None:
        self._authorize(actor, row, respond=op in {"start", "respond"})

    def _read_row(self, actor: Any, run_id: str, *, op: str = "poll") -> dict[str, Any]:
        with self._read_tx() as cur:
            cur.execute("SELECT * FROM v23_runs WHERE run_id=%s", (run_id,))
            row = cur.fetchone()
            if row is None:
                raise ControlError("not_found_or_unauthorized")
            self._authorize_op(op, actor, row)
            return row

    def _read(self, actor: Any, run_id: str) -> dict[str, Any]:
        return _snapshot(self._read_row(actor, run_id))

    @staticmethod
    def _request(op: str, request: Any) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise ControlError("invalid_request")
        fields = {
            "start": {"run_id", "parent_run_id", "instruction", "turn_budget", "request_id", "expected_revision"},
            "poll": {"run_id"}, "wait": {"run_id", "since_revision", "timeout_seconds"},
            "cancel": {"run_id", "expected_revision", "request_id"},
            "steer": {"run_id", "expected_revision", "request_id", "parent_instruction", "continuation"},
            "respond": {"run_id", "expected_revision", "request_id", "interaction_id", "response"},
        }
        if set(request) - fields[op]:
            raise ControlError("invalid_request")
        try:
            result = copy.deepcopy(dict(request))
            canonical_uuid(result["run_id"])
            if op in _MUTATIONS:
                canonical_uuid(result["request_id"])
            if op == "start":
                if result.setdefault("expected_revision", None) is not None:
                    raise ValueError("start has no expected_revision")
                integer(result["turn_budget"], 1)
                if result["turn_budget"] > 2**31 - 1:
                    raise ValueError("budget out of range")
                if type(result["instruction"]) is not str or not result["instruction"].strip():
                    raise ValueError("empty instruction")
                if len(_canonical(result["instruction"])) > MAX_RESULT_BYTES:
                    raise ValueError("instruction too large")
                if result["parent_run_id"] is not None:
                    canonical_uuid(result["parent_run_id"])
                    if result["parent_run_id"] == result["run_id"]:
                        raise ValueError("self parent")
            elif op in {"cancel", "steer", "respond"}:
                if integer(result["expected_revision"]) > 2**63 - 1:
                    raise ValueError("revision out of range")
            if op == "steer":
                if ("parent_instruction" in result) == ("continuation" in result):
                    raise ControlError("missing_steer_input")
                if "continuation" in result:
                    if result["continuation"] is not True:
                        raise ControlError("missing_steer_input")
                elif (type(result["parent_instruction"]) is not str or not result["parent_instruction"].strip()
                      or len(_canonical(result["parent_instruction"])) > MAX_RESULT_BYTES):
                    raise ControlError("missing_steer_input")
            if op == "wait":
                timeout = result.setdefault("timeout_seconds", 0)
                if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 3600:
                    raise ValueError("invalid timeout")
                since = result.setdefault("since_revision", None)
                if since is not None and integer(since) > 2**63 - 1:
                    raise ValueError("revision out of range")
            if op == "respond":
                canonical_uuid(result["interaction_id"])
                if len(_canonical(result["response"])) > MAX_RESULT_BYTES:
                    raise ValueError("response too large")
        except ControlError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ControlError("invalid_request") from exc
        return result

    def execute(self, op: str | None = None, actor: Any = None,
                request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        op = "wait" if op is None else op
        if not isinstance(op, str) or op not in OPS:
            raise ControlError("unknown_op")
        if getattr(_worker_scope, "active", False):
            raise ControlError("worker_reentrancy")
        if self._closed:
            raise ControlError("control_runtime_closed")
        self._check_pid()
        req = self._request(op, request)
        self._actor_digest(actor)
        if op == "poll":
            return {"schema_version": 1, "operation": op, "snapshot": self._read(actor, req["run_id"])}
        if op == "wait":
            return self._wait(actor, req)
        if self._runtime.lost or self._runtime.closed or self._runtime.conn.closed:
            # A dead generation may only observe an already durable receipt.
            self._lose_runtime()
            row = self._read_row(actor, req["run_id"], op=op)
            entry = self._entry(row, op, actor, req)
            if entry is not None and entry["state"] != "pending":
                return self._replay(entry)
            raise ControlError("control_runtime_lost")
        if op == "cancel":
            return self._cancel(actor, req)
        return self._mutate(op, actor, req)

    @staticmethod
    def _actor_digest(actor: Any) -> str:
        if isinstance(actor, HostActor):
            identity = {"kind": "host"}
        elif isinstance(actor, ParentActor):
            identity = {"kind": "parent", "parent_run_id": actor.parent_run_id}
        else:
            raise ControlError("not_found_or_unauthorized")
        return _digest(identity)

    @staticmethod
    def _request_digest(op: str, actor: Any, req: Mapping[str, Any]) -> str:
        semantic = {key: value for key, value in req.items()
                    if key not in {"request_id", "expected_revision", "timeout_seconds"}}
        return _digest({"operation": op, "actor_digest": Control._actor_digest(actor), "request": semantic})

    @staticmethod
    def _input(op: str, actor: Any, req: Mapping[str, Any]) -> dict[str, Any]:
        if op == "start":
            kind, instruction, response, continuation = "initial", req["instruction"], None, False
        elif op == "respond":
            kind, instruction, response, continuation = "parent_response", None, req["response"], False
        elif isinstance(actor, HostActor):
            if req.get("continuation") is not True or "parent_instruction" in req:
                raise ControlError("missing_steer_input")
            kind, instruction, response, continuation = "host_continue", None, None, True
        else:
            if "parent_instruction" not in req or "continuation" in req:
                raise ControlError("missing_steer_input")
            kind, instruction, response, continuation = "parent_instruction", req["parent_instruction"], None, False
        return {"input_kind": kind, "instruction": instruction, "response": response, "continuation": continuation}

    @staticmethod
    def _validate_response(value: Any, input_request: Mapping[str, Any]) -> None:
        # Empty options means an open question. JSON equality must not equate true/1.
        options = input_request.get("options")
        if options and not any(_canonical(value) == _canonical(option) for option in options):
            raise ControlError("invalid_response")
        schema = input_request.get("response_schema", {})
        kinds = {"object": (dict,), "array": (list,), "string": (str,), "integer": (int,),
                 "number": (int, float), "boolean": (bool,), "null": (type(None),)}
        kind = schema.get("type")
        if kind is not None and (kind not in kinds or type(value) not in kinds[kind]):
            raise ControlError("invalid_response")
        if isinstance(value, dict) and any(key not in value for key in schema.get("required", [])):
            raise ControlError("invalid_response")

    def _admit(self, op: str, actor: Any, req: dict[str, Any], cur: Any, row: dict | None) -> _Owner:
        inputs = self._input(op, actor, req)
        input_digest = _digest(inputs)
        run_id, request_id = req["run_id"], req["request_id"]
        if op == "start":
            parent_id = req["parent_run_id"]
            if parent_id is None:
                if not isinstance(actor, HostActor):
                    raise ControlError("not_found_or_unauthorized")
            else:
                if not isinstance(actor, ParentActor) or actor.parent_run_id != parent_id:
                    raise ControlError("not_found_or_unauthorized")
                # Same runtime mutex serializes parent/child writes; child does not
                # exist yet. Existing starts never acquire a second parent row lock.
                cur.execute("SELECT status FROM v23_runs WHERE run_id=%s FOR UPDATE", (parent_id,))
                parent = cur.fetchone()
                if parent is None or parent["status"] in {"stopped", "completed"}:
                    raise ControlError("not_found_or_unauthorized")
            revision = 1
        else:
            assert row is not None
            if row["revision"] != req["expected_revision"]:
                raise ControlError("revision_conflict")
            if op == "steer":
                if row["status"] == "waiting_input":
                    raise ControlError("waiting_input_requires_respond")
                if row["status"] == "running":
                    raise ControlError("busy")
                if row["status"] != "ready":
                    raise ControlError("closed")
            else:
                if row["status"] != "waiting_input":
                    raise ControlError("not_waiting_input")
                input_request = row["latest_receipt"]["input_request"]
                if req["interaction_id"] != input_request["interaction_id"]:
                    raise ControlError("interaction_conflict")
                self._validate_response(req["response"], input_request)
            if row["cancel_requested"]:
                raise ControlError("closed")
            if row["turns_used"] >= row["turn_budget"]:
                raise ControlError("budget_exhausted")
            revision = row["revision"] + 1
        wr = WorkerRequest(UUID(run_id), uuid4(), revision, inputs["input_kind"], input_digest,
                           inputs["instruction"], inputs["response"], inputs["continuation"])
        validate_request(wr)
        digest = self._request_digest(op, actor, req)
        owner = _Owner(digest, wr, self._runtime.generation, op, actor, copy.deepcopy(req))
        entry = {"state": "pending", "operation": op, "actor_digest": self._actor_digest(actor),
                 "request_digest": digest, "input_digest": input_digest, "admission_revision": revision,
                 "response": None, "error_code": None}
        if op == "start":
            cur.execute("""INSERT INTO v23_runs(run_id, parent_run_id, status, revision, turn_budget,
                           active_operation_id, active_base_revision, active_input_digest, op_cache)
                           VALUES (%s,%s,'running',1,%s,%s,1,%s,%s) RETURNING *""",
                        (run_id, req["parent_run_id"], req["turn_budget"], request_id, input_digest,
                         Json({request_id: entry})))
            row = cur.fetchone()
        else:
            row.update(status="running", revision=revision, active_operation_id=request_id,
                       active_base_revision=revision, active_input_digest=input_digest)
            row["op_cache"][request_id] = entry
            self._write(cur, row)
        # Pre-register while mutex/registry/SQL locks are held. Only a confirmed
        # COMMIT permits Worker; rollback or uncertainty removes this registration.
        owner.admission_snapshot = _snapshot(row)
        _owners[self._owner_key(run_id, request_id)] = owner
        return owner

    def _remove_owner(self, owner: _Owner) -> None:
        with self._runtime.mutex, _owners_lock:
            key = self._owner_key(owner.request["run_id"], owner.request["request_id"])
            if _owners.get(key) is owner:
                _owners.pop(key)
            owner.done.set()

    def _join_owner(self, owner: _Owner, op: str, actor: Any, req: dict[str, Any]) -> dict[str, Any]:
        while not owner.done.wait(0.05):
            if not owner.thread.is_alive():
                return self._mutate(op, actor, req)  # authorized, fenced local recovery
            if self._runtime.lost or self._runtime.conn.closed:
                raise ControlError("control_runtime_lost")
        if owner.error is not None:
            raise owner.error
        assert owner.response is not None
        return copy.deepcopy(owner.response)

    def _resolve_t1_uncertainty(self, op: str, actor: Any, req: dict[str, Any]) -> dict[str, Any]:
        # Worker has not been called. Pending is never permission to supplement it.
        if self._runtime.lost:
            raise ControlError("control_runtime_lost")
        changed = None
        with self._tx("recovery") as cur:
            cur.execute("SELECT * FROM v23_runs WHERE run_id=%s FOR UPDATE", (req["run_id"],))
            row = cur.fetchone()
            if row is None:
                raise ControlError("admission_unconfirmed")
            self._authorize_op(op, actor, row)
            entry = self._entry(row, op, actor, req)
            if entry is None:
                raise ControlError("admission_unconfirmed")
            if entry["state"] == "pending":
                if str(row["active_operation_id"]) != req["request_id"]:
                    raise ControlError("active_operation_conflict")
                changed = self._recover_row(cur, row)
                entry = row["op_cache"][req["request_id"]]
        if changed is not None:
            self._post_commit_notify(changed["snapshot"])
        return self._replay(entry)

    def _mutate(self, op: str, actor: Any, req: dict[str, Any]) -> dict[str, Any]:
        owner = duplicate = entry = recovered = None
        try:
            with self._tx("T1", admission=True) as cur:
                if op == "start":
                    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,23))", (req["run_id"],))
                cur.execute("SELECT * FROM v23_runs WHERE run_id=%s FOR UPDATE", (req["run_id"],))
                row = cur.fetchone()
                if row is not None:
                    self._authorize_op(op, actor, row)
                    entry = self._entry(row, op, actor, req)
                    if entry is not None and entry["state"] == "pending":
                        if str(row["active_operation_id"]) != req["request_id"]:
                            raise ControlError("active_operation_conflict")
                        duplicate = self._live_owner(row, entry)
                        if duplicate is None:
                            recovered = self._recover_row(cur, row)
                            entry = row["op_cache"][req["request_id"]]
                    elif entry is None and op == "start":
                        raise ControlError("idempotency_conflict")
                elif op != "start":
                    raise ControlError("not_found_or_unauthorized")
                if entry is None:
                    owner = self._admit(op, actor, req, cur, row)
        except BaseException as exc:
            if isinstance(exc, _CommitUncertain) and owner is not None:
                # T1 acknowledgement loss has no executable owner. Resolve the
                # durable pending record before waking joiners, so every exact
                # retry observes the same recovered receipt rather than this
                # internal uncertainty exception.
                try:
                    recovered_response = self._resolve_t1_uncertainty(op, actor, req)
                except BaseException as recovery_exc:
                    owner.error = recovery_exc
                    self._remove_owner(owner)
                    raise
                owner.response = copy.deepcopy(recovered_response)
                self._remove_owner(owner)
                return recovered_response
            if owner is not None:
                owner.error = exc
                self._remove_owner(owner)
            raise
        if recovered is not None:
            self._post_commit_notify(recovered["snapshot"])
        if duplicate is not None:
            return self._join_owner(duplicate, op, actor, req)
        if entry is not None:
            return self._replay(entry)
        assert owner is not None
        # T1 is confirmed, the fenced connection is IDLE and all locks are released.
        try:
            self._post_commit_notify(owner.admission_snapshot)
            # Notification is outside locks and can be delayed. Do not begin a
            # fresh external effect if shutdown/fence loss was discovered during
            # that interval. This check does not migrate ownership or reconnect.
            with self._runtime.mutex, _owners_lock:
                self._ensure_runtime()
                if _owners.get(self._owner_key(req["run_id"], req["request_id"])) is not owner:
                    raise ControlError("active_operation_conflict")
            worker_error = None
            _worker_scope.active = True
            try:
                try:
                    receipt = self.worker.run(copy.deepcopy(owner.worker_request))
                except Exception as exc:
                    worker_error = exc
                    wr = owner.worker_request
                    if isinstance(exc, WorkerExecutionError):
                        result, calls = copy.deepcopy(exc.result), copy.deepcopy(exc.tool_calls)
                    else:
                        result, calls = {"ok": False, "error": {"code": "worker_runtime"}}, ()
                    receipt = TurnReceipt(1, wr.turn_id, wr.run_id, wr.base_revision, wr.input_kind,
                                          wr.input_digest, "failed", result, tool_calls=calls)
                # Freeze the one returned DTO once, never rebuild/re-run it on T2 retry.
                try:
                    receipt = copy.deepcopy(receipt) if type(receipt) is TurnReceipt else receipt
                except Exception:
                    receipt = None
            finally:
                _worker_scope.active = False
            attempts = 0
            while True:
                try:
                    final_entry, changed = self._finalize(op, req, owner, receipt, worker_error)
                    break
                except _CommitUncertain:
                    row = self._read_row(actor, req["run_id"], op=op)
                    final_entry = self._entry(row, op, actor, req)
                    if final_entry is None or final_entry["state"] == "pending":
                        if self._runtime.lost:
                            raise ControlError("control_runtime_lost")
                        raise ControlError("finalization_unconfirmed")
                    changed = False
                    break
                except psycopg2.Error as exc:
                    # Only known rollback, live original owner and healthy same fence.
                    if exc.pgcode not in _RETRY_CODES or attempts >= 3:
                        raise
                    attempts += 1
                    time.sleep(0.01)  # transaction/locks already ended
            owner.response = copy.deepcopy(final_entry["response"])
            if changed:
                self._post_commit_notify(owner.response["snapshot"])
            return self._replay(final_entry)
        except BaseException as exc:
            owner.error = exc
            raise
        finally:
            self._remove_owner(owner)

    def _finalize(self, op: str, req: Mapping[str, Any], owner: _Owner,
                  receipt: Any, worker_error: Exception | None) -> tuple[dict[str, Any], bool]:
        changed = False
        with self._tx("T2") as cur:
            cur.execute("SELECT * FROM v23_runs WHERE run_id=%s FOR UPDATE", (req["run_id"],))
            row = cur.fetchone()
            if row is None:
                raise ControlError("not_found_or_unauthorized")
            self._authorize_op(op, owner.actor, row)
            entry = self._entry(row, op, owner.actor, req)
            if entry is None:
                raise ControlError("active_operation_conflict")
            # A COMMIT ack can be lost after active has been cleared. Cache first.
            if entry["state"] != "pending":
                return copy.deepcopy(entry), False
            if (owner.generation != self._runtime.generation or owner.thread is not threading.current_thread()
                    or _owners.get(self._owner_key(req["run_id"], req["request_id"])) is not owner
                    or owner.done.is_set() or str(row["active_operation_id"]) != req["request_id"]):
                raise ControlError("active_operation_conflict")
            self._match_active(row, entry, owner)
            failure, outcome = None, "committed"
            if row["cancel_requested"]:
                row.update(status="stopped", close_reason="late_result_after_cancel")
                outcome = "late_result_discarded"
            else:
                try:
                    validate_receipt(receipt, owner.worker_request)
                    durable_receipt = json.loads(_canonical(receipt.as_dict()))
                except (WorkerContractError, TypeError, ValueError, OverflowError, RecursionError):
                    row.update(status="stopped", close_reason="invalid_worker_receipt")
                    failure = "invalid_worker_receipt"
                else:
                    row["latest_receipt"] = durable_receipt
                    row["turns_used"] += 1
                    row["status"] = {"progress": "ready", "needs_input": "waiting_input",
                                     "completed": "completed", "failed": "stopped"}[receipt.outcome]
                    row["close_reason"] = "worker_failed" if receipt.outcome == "failed" else None
                    if receipt.outcome == "failed":
                        failure = "worker_failed"
            # Invalid/late closures deliberately preserve the previously accepted receipt.
            row["revision"] += 1
            self._clear_active(row)
            response = {"schema_version": 1, "operation": op, "outcome": outcome, "snapshot": _snapshot(row)}
            entry = {**entry, "state": "done", "response": response, "error_code": failure}
            row["op_cache"][req["request_id"]] = entry
            self._write(cur, row)
            changed = True
        return copy.deepcopy(entry), changed

    def _cancel(self, actor: Any, req: dict[str, Any]) -> dict[str, Any]:
        changed = False
        try:
            with self._tx("cancel", admission=True) as cur:
                cur.execute("SELECT * FROM v23_runs WHERE run_id=%s FOR UPDATE", (req["run_id"],))
                row = cur.fetchone()
                if row is None:
                    raise ControlError("not_found_or_unauthorized")
                self._authorize(actor, row)
                entry = self._entry(row, "cancel", actor, req)
                if entry is not None:
                    return self._replay(entry)
                if row["revision"] != req["expected_revision"]:
                    raise ControlError("revision_conflict")
                if row["status"] in {"completed", "stopped"}:
                    outcome = "already_closed"
                elif row["status"] == "running" and row["cancel_requested"]:
                    outcome = "cancel_requested"  # genuine zero write, including cache
                else:
                    changed = True
                    row["revision"] += 1
                    row["cancel_requested"] = True
                    if row["status"] == "running":
                        outcome = "cancel_requested"
                    else:
                        row.update(status="stopped", close_reason="cancelled")
                        outcome = "cancelled"
                response = {"schema_version": 1, "operation": "cancel", "outcome": outcome, "snapshot": _snapshot(row)}
                if changed:
                    row["op_cache"][req["request_id"]] = {
                        "state": "done", "operation": "cancel", "actor_digest": self._actor_digest(actor),
                        "request_digest": self._request_digest("cancel", actor, req), "input_digest": None,
                        "admission_revision": None, "response": response, "error_code": None}
                    self._write(cur, row)
        except _CommitUncertain:
            row = self._read_row(actor, req["run_id"], op="cancel")
            entry = self._entry(row, "cancel", actor, req)
            if entry is not None:
                return self._replay(entry)
            raise ControlError("control_runtime_lost" if self._runtime.lost else "cancellation_unconfirmed")
        if changed:
            self._post_commit_notify(response["snapshot"])
        return response

    @staticmethod
    def _wait_result(snapshot: Mapping[str, Any], since: int | None) -> str | None:
        if since is None:
            return "already_interesting"
        if snapshot["revision"] > since:
            return "changed"
        if snapshot["status"] in {"waiting_input", "completed", "stopped"}:
            return "already_interesting"
        return None

    def _before_listen(self) -> None:
        """Private test seam after the first committed read, before LISTEN."""

    def _after_listen(self, listener: Any) -> None:
        """Private test seam after LISTEN is effective (listener is IDLE)."""

    def _wait(self, actor: Any, req: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._read(actor, req["run_id"])
        since = req["since_revision"]
        result = self._wait_result(snapshot, since)
        if result is None:
            self._before_listen()
            listener = psycopg2.connect(self.dsn, application_name="v23_wait")
            listener.autocommit = True
            try:
                with listener.cursor() as cur:
                    cur.execute("LISTEN " + CHANNEL)
                self._after_listen(listener)
                # The second complete read closes the read/LISTEN race.
                snapshot = self._read(actor, req["run_id"])
                result = self._wait_result(snapshot, since)
                deadline = time.monotonic() + req["timeout_seconds"]
                while result is None and time.monotonic() < deadline:
                    remaining = max(0, deadline - time.monotonic())
                    if not select.select([listener], [], [], remaining)[0]:
                        break
                    listener.poll()
                    if listener.notifies:
                        listener.notifies.clear()  # payload is never business state
                        snapshot = self._read(actor, req["run_id"])
                        result = self._wait_result(snapshot, since)
                # Re-read even after timeout/lost/irrelevant/coalesced notifications.
                snapshot = self._read(actor, req["run_id"])
                result = self._wait_result(snapshot, since) or "timed_out"
            finally:
                listener.close()
        return {"schema_version": 1, "operation": "wait", "wait_result": result, "snapshot": snapshot}
