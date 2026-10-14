"""Sole write entry for the v20 alpha kernel."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Mapping
from uuid import uuid4
import json
import math
import select
import threading
import time

import psycopg2
from psycopg2.extras import Json, RealDictCursor, register_default_jsonb
from psycopg2.extensions import TRANSACTION_STATUS_IDLE

from v20.alpha.worker import (
    WorkerContractError,
    canonical_json,
    sha256_json,
    storage_safe_json,
    validate_stored_receipt,
)

CHANNEL = "v20_alpha_run_changed"
_tls = threading.local()

ADMISSION = frozenset({"start", "claim_resume", "steer", "respond", "admit_turn", "admit_tool"})
HANDLE_VERBS = frozenset({"start", "claim_resume", "steer", "respond"})
KNOWN = ADMISSION | frozenset({
    "poll", "wait", "cancel", "cleanup", "recover_owner", "publish_snapshot",
    "accept_turn_receipt", "accept_tool_result", "record_provider_handle",
})
RUNNABLE = frozenset({"running", "waiting_for_input"})
TERMINAL_RUN = frozenset({"completed", "failed", "cancelled", "expired"})
RESUME_OK = TERMINAL_RUN


class ControlError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.committed = False
        super().__init__(message or code)


def _int(value: Any) -> int:
    if type(value) is not int:
        raise ControlError("Rejected")
    return value


def _timeout(value: Any) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ControlError("Rejected")
    return float(value)


def _require_handle_op(op) -> None:
    if not op["expects_handle"] or op["verb"] not in HANDLE_VERBS:
        raise ControlError("Rejected")


def _load(value: Any) -> Any:
    """Return a jsonb value as a Python object. psycopg2 may hand back text."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _message(payload: Mapping[str, Any]) -> str:
    text = payload.get("input_message")
    if type(text) is not str or not text.strip():
        raise ControlError("Rejected")
    storage_safe_json(text)
    return text


class Control:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.conn = psycopg2.connect(
            dsn, cursor_factory=RealDictCursor, application_name="v20_alpha_control"
        )
        self.conn.autocommit = False
        register_default_jsonb(conn_or_curs=self.conn, loads=json.loads)
        self._bind()

    def close(self) -> None:
        if self.conn is not None and not self.conn.closed:
            if self.conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                self.conn.rollback()
            self.conn.close()

    def __enter__(self) -> Control:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _bind(self) -> None:
        _tls.control = self

    @staticmethod
    def in_transaction() -> bool:
        ctrl = getattr(_tls, "control", None)
        if ctrl is None or ctrl.conn is None or ctrl.conn.closed:
            return False
        return ctrl.conn.get_transaction_status() != TRANSACTION_STATUS_IDLE

    @contextmanager
    def _tx(self):
        if self.in_transaction():
            raise ControlError("Rejected")
        cur = self.conn.cursor()
        try:
            yield cur
        except ControlError as exc:
            if not exc.committed:
                self.conn.rollback()
            raise
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()
        finally:
            cur.close()

    def execute(self, verb: str, actor: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self._bind()
        if type(actor) is not str or not actor.strip():
            raise ControlError("Rejected")
        if type(verb) is not str or verb not in KNOWN:
            raise ControlError("UnknownVerb")
        if payload is None:
            payload = {}
        if type(payload) is not dict or "input_artifact_digest" in payload:
            raise ControlError("Rejected")
        if verb == "poll":
            return self._poll(payload)
        if verb == "wait":
            return self._wait(payload)
        try:
            with self._tx() as cur:
                result = getattr(self, f"_v_{verb}")(cur, payload)
        except WorkerContractError as exc:
            raise ControlError("WorkerContractError", str(exc)) from exc
        notify = result.pop("_notify", None)
        if notify:
            self._notify(notify[0], notify[1])
        return result

    def _notify(self, run_id: str, revision: int) -> None:
        try:
            if self.conn.closed:
                return
            if self.in_transaction():
                self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute("SELECT pg_notify(%s, %s)", (CHANNEL, f"{run_id}|{revision}"))
            self.conn.commit()
        except Exception:
            try:
                if self.conn.closed:
                    return
                if self.conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                    self.conn.rollback()
            except Exception:
                return

    def _event(self, cur, kind: str, session_id: str | None, run_id: str | None,
               epoch_id: str | None, message: str | None) -> None:
        cur.execute(
            """INSERT INTO v20_events (kind, session_id, run_id, epoch_id, message)
               VALUES (%s, %s, %s, %s, %s)""",
            (kind, session_id, run_id, epoch_id, message),
        )

    def _activity(self, cur, transcript_turn_id: str, role: str, item_kind: str,
                  text: str, tool_invocation_id: str | None = None) -> None:
        cur.execute(
            """SELECT COALESCE(MAX(sequence_index), 0) + 1 AS n
               FROM v20_transcript_activities WHERE turn_id = %s""",
            (transcript_turn_id,),
        )
        seq = cur.fetchone()["n"]
        cur.execute(
            """INSERT INTO v20_transcript_activities
               (activity_id, turn_id, sequence_index, role, item_kind, text, tool_invocation_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (str(uuid4()), transcript_turn_id, seq, role, item_kind, text or "", tool_invocation_id),
        )

    def _backend_pid(self, cur) -> int:
        cur.execute("SELECT pg_backend_pid() AS pid")
        return cur.fetchone()["pid"]

    def _pid_alive(self, cur, pid: int | None) -> bool:
        if pid is None:
            return False
        cur.execute("SELECT pid FROM pg_stat_activity WHERE pid = %s", (pid,))
        return cur.fetchone() is not None

    def _lock_run(self, cur, run_id: str):
        cur.execute("SELECT * FROM v20_runs WHERE run_id = %s FOR UPDATE", (run_id,))
        run = cur.fetchone()
        if run is None:
            raise ControlError("Rejected")
        cur.execute("SELECT * FROM v20_sessions WHERE session_id = %s FOR UPDATE", (run["session_id"],))
        session = cur.fetchone()
        return run, session

    def _lock_epoch_id(self, cur, epoch_id: str):
        cur.execute("SELECT * FROM v20_epochs WHERE epoch_id = %s FOR UPDATE", (epoch_id,))
        epoch = cur.fetchone()
        if epoch is None:
            raise ControlError("Rejected")
        return epoch

    def _lock_current_epoch(self, cur, session):
        cur.execute(
            """SELECT * FROM v20_epochs WHERE session_id = %s AND ordinal = %s FOR UPDATE""",
            (session["session_id"], session["last_epoch_ordinal"]),
        )
        epoch = cur.fetchone()
        if epoch is None:
            raise ControlError("Rejected")
        return epoch

    def _reload_run(self, cur, run_id: str):
        cur.execute("SELECT * FROM v20_runs WHERE run_id = %s", (run_id,))
        return cur.fetchone()

    def _reload_op(self, cur, request_id: str):
        cur.execute("SELECT * FROM v20_operations WHERE request_id = %s", (request_id,))
        return cur.fetchone()

    def _shape(self, verb: str, run, op=None, **extra: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "request_id": None if op is None else op["request_id"],
            "verb": verb,
            "status": None if run is None else run["status"],
            "run_id": None if run is None else run["run_id"],
            "session_id": None if run is None else run["session_id"],
            "revision": None if run is None else run["revision"],
        }
        if op is not None:
            body.update({
                "operation_status": op["status"],
                "expects_handle": op["expects_handle"],
                "handle_state": op["handle_state"],
                "depends_on_request_id": op["depends_on_request_id"],
                "attempt_seq": op["attempt_seq"],
                "snapshot_seq": op["snapshot_seq"],
                "epoch_id": op["epoch_id"],
                "owner_generation": op["owner_generation"],
                "input_message": op["input_message"],
                "result": op["result"],
            })
        body.update(extra)
        return body

    def _replay(self, cur, verb: str, op) -> dict[str, Any]:
        cur.execute(
            """SELECT r.* FROM v20_runs r
               JOIN v20_epochs e ON e.run_id = r.run_id
               WHERE e.epoch_id = %s""",
            (op["epoch_id"],),
        )
        run = cur.fetchone()
        cur.execute("SELECT parent_session_id FROM v20_sessions WHERE session_id = %s", (run["session_id"],))
        parent = cur.fetchone()["parent_session_id"]
        return self._shape(verb, run, op, parent_session_id=parent)

    def _begin_admission(self, cur, verb: str, payload: Mapping[str, Any]):
        request_id = payload.get("request_id")
        if type(request_id) is not str or not request_id:
            raise ControlError("Rejected")
        digest = sha256_json(dict(payload))
        cur.execute("SELECT pg_advisory_xact_lock(20020, hashtext(%s))", (request_id,))
        cur.execute("SELECT * FROM v20_operations WHERE request_id = %s FOR UPDATE", (request_id,))
        existing = cur.fetchone()
        if existing is not None:
            if existing["verb"] != verb or existing["payload_digest"] != digest:
                raise ControlError("IdempotencyConflict")
        return digest, existing

    def _next_attempt(self, cur, session_id: str) -> int:
        cur.execute(
            """SELECT COALESCE(MAX(o.attempt_seq), 0) AS n
               FROM v20_operations o JOIN v20_epochs e ON e.epoch_id = o.epoch_id
               WHERE e.session_id = %s""",
            (session_id,),
        )
        return cur.fetchone()["n"] + 1

    def _depends_on(self, cur, session_id: str, attempt_seq: int) -> str | None:
        cur.execute(
            """SELECT o.request_id FROM v20_operations o
               JOIN v20_epochs e ON e.epoch_id = o.epoch_id
               WHERE e.session_id = %s AND o.expects_handle AND o.attempt_seq < %s
               ORDER BY o.attempt_seq DESC LIMIT 1""",
            (session_id, attempt_seq),
        )
        row = cur.fetchone()
        return None if row is None else row["request_id"]

    def _insert_op(self, cur, *, request_id: str, verb: str, epoch_id: str, owner_generation: int,
                   attempt_seq: int, expects_handle: bool, handle_state: str,
                   depends_on: str | None, input_message: str, digest: str) -> None:
        cur.execute(
            """INSERT INTO v20_operations (
                   request_id, verb, epoch_id, owner_generation, attempt_seq, snapshot_seq,
                   status, handle_state, expects_handle, depends_on_request_id,
                   input_message, input_retained, payload_digest, result)
               VALUES (%s, %s, %s, %s, %s, NULL, 'pending', %s, %s, %s, %s, false, %s, NULL)""",
            (request_id, verb, epoch_id, owner_generation, attempt_seq, handle_state,
             expects_handle, depends_on, input_message, digest),
        )

    def _finish_pending(self, cur, epoch_id: str, new_status: str) -> None:
        cur.execute(
            """SELECT o.request_id, o.handle_state,
                      EXISTS (SELECT 1 FROM v20_provider_handle_attempts a
                              WHERE a.request_id = o.request_id) AS has_attempt
               FROM v20_operations o
               WHERE o.epoch_id = %s AND o.status = 'pending'
               FOR UPDATE""",
            (epoch_id,),
        )
        for row in cur.fetchall():
            handle = row["handle_state"]
            if not row["has_attempt"] and handle == "pending":
                handle = "absent"
            cur.execute(
                "UPDATE v20_operations SET status = %s, handle_state = %s WHERE request_id = %s",
                (new_status, handle, row["request_id"]),
            )

    def _settle_completed_handles(self, cur, session_id: str) -> None:
        cur.execute(
            """UPDATE v20_operations o SET handle_state = 'absent'
               FROM v20_epochs e
               WHERE o.epoch_id = e.epoch_id AND e.session_id = %s
                 AND o.status = 'completed' AND o.handle_state = 'pending'
                 AND NOT EXISTS (
                     SELECT 1 FROM v20_provider_handle_attempts a WHERE a.request_id = o.request_id)""",
            (session_id,),
        )

    def _close_epoch(self, cur, epoch_id: str) -> None:
        cur.execute(
            """UPDATE v20_epochs SET closed_at = clock_timestamp()
               WHERE epoch_id = %s AND closed_at IS NULL""",
            (epoch_id,),
        )

    def _transcript_id(self, cur, session_id: str, explicit: str | None = None) -> str:
        if explicit is not None:
            if type(explicit) is not str or not explicit:
                raise ControlError("Rejected")
            cur.execute(
                """SELECT turn_id FROM v20_transcript_turns
                   WHERE turn_id = %s AND session_id = %s""",
                (explicit, session_id),
            )
            if cur.fetchone() is None:
                raise ControlError("Rejected")
            return explicit
        cur.execute(
            """SELECT turn_id FROM v20_transcript_turns WHERE session_id = %s
               ORDER BY started_at, turn_id LIMIT 1""",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ControlError("Rejected")
        return row["turn_id"]

    def _insert_epoch(self, cur, session, run, kind: str, ordinal: int, continuity: int) -> str:
        epoch_id = str(uuid4())
        cur.execute(
            """INSERT INTO v20_epochs (
                   epoch_id, session_id, run_id, ordinal, continuity_generation, transition_kind,
                   activation_id, registration_generation, closed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)""",
            (epoch_id, session["session_id"], run["run_id"], ordinal, continuity, kind,
             str(uuid4()), session["registration_generation"]),
        )
        return epoch_id

    def _driving(self, cur, session_id: str):
        cur.execute(
            """SELECT o.* FROM v20_operations o
               JOIN v20_epochs e ON e.epoch_id = o.epoch_id
               WHERE e.session_id = %s AND o.expects_handle AND o.status = 'pending'
               ORDER BY o.attempt_seq DESC LIMIT 1
               FOR UPDATE""",
            (session_id,),
        )
        return cur.fetchone()

    def _expected_kind(self, cur, session, driving) -> str:
        cur.execute(
            """SELECT t.receipt, t.status
               FROM v20_turns t
               JOIN v20_operations o ON o.request_id = t.request_id
               WHERE t.epoch_id = %s AND o.attempt_seq > %s
               ORDER BY o.attempt_seq""",
            (driving["epoch_id"], driving["attempt_seq"]),
        )
        after = cur.fetchall()
        if not after:
            if driving["verb"] == "respond":
                return "parent_response"
            if driving["verb"] in {"claim_resume", "steer"}:
                return "initial"
            if session["parent_session_id"]:
                return "parent_instruction"
            return "initial"
        last = after[-1]
        receipt = _load(last["receipt"]) or {}
        if last["status"] != "completed":
            raise ControlError("Rejected")
        if receipt.get("tool_calls"):
            return "host_continue"
        if receipt.get("outcome") == "progress":
            kind = receipt.get("input_kind")
            if kind not in {"initial", "parent_instruction", "host_continue", "parent_response"}:
                raise ControlError("Rejected")
            return kind
        raise ControlError("Rejected")

    def _tool_results(self, cur, epoch_id: str) -> list[dict[str, Any]]:
        cur.execute(
            """SELECT i.invocation_id, i.tool_name, o.result
               FROM v20_tool_invocations i
               JOIN v20_operations o ON o.request_id = i.request_id
               WHERE i.epoch_id = %s AND o.status = 'completed'
               ORDER BY o.attempt_seq, i.invocation_id""",
            (epoch_id,),
        )
        items = []
        for row in cur.fetchall():
            result = _load(row["result"]) or {}
            items.append({
                "invocation_id": row["invocation_id"],
                "tool_name": row["tool_name"],
                "output": result.get("output"),
            })
        return items

    def _fence(self, cur, run, epoch_id: str | None, op, reason: str) -> None:
        if op is not None and op["status"] == "pending":
            cur.execute(
                "UPDATE v20_operations SET status = 'archived' WHERE request_id = %s",
                (op["request_id"],),
            )
        self._event(cur, "archive", run["session_id"], run["run_id"], epoch_id, reason)
        self.conn.commit()
        err = ControlError("FenceRejected", reason)
        err.committed = True
        raise err

    def _epoch_matches(self, epoch, session) -> bool:
        return epoch["closed_at"] is None and epoch["ordinal"] == session["last_epoch_ordinal"]

    def _apply_handle(self, cur, op, run, session, epoch, handle: Any) -> None:
        storage_safe_json(handle)
        cur.execute(
            """INSERT INTO v20_provider_handle_attempts (request_id, attempt_seq, epoch_id, handle)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (request_id) DO UPDATE
                 SET handle = EXCLUDED.handle, attempt_seq = EXCLUDED.attempt_seq,
                     epoch_id = EXCLUDED.epoch_id""",
            (op["request_id"], op["attempt_seq"], op["epoch_id"], Json(handle)),
        )
        cur.execute(
            "UPDATE v20_operations SET handle_state = 'present' WHERE request_id = %s",
            (op["request_id"],),
        )
        current = self._epoch_matches(epoch, session) and op["owner_generation"] == run["owner_generation"]
        if not current or op["status"] not in {"pending", "completed"}:
            return
        cur.execute(
            "SELECT attempt_seq FROM v20_session_provider_handles WHERE session_id = %s FOR UPDATE",
            (session["session_id"],),
        )
        row = cur.fetchone()
        if row is None:
            return
        if row["attempt_seq"] is not None and op["attempt_seq"] < row["attempt_seq"]:
            return
        cur.execute(
            """UPDATE v20_session_provider_handles
               SET epoch_id = %s, attempt_seq = %s, provider_cleanup_handle = %s
               WHERE session_id = %s""",
            (epoch["epoch_id"], op["attempt_seq"], Json(handle), session["session_id"]),
        )

    def _load_op_context(self, cur, request_id: str):
        cur.execute("SELECT epoch_id FROM v20_operations WHERE request_id = %s", (request_id,))
        found = cur.fetchone()
        if found is None:
            raise ControlError("Rejected")
        cur.execute("SELECT run_id FROM v20_epochs WHERE epoch_id = %s", (found["epoch_id"],))
        run_id = cur.fetchone()["run_id"]
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_epoch_id(cur, found["epoch_id"])
        cur.execute("SELECT * FROM v20_operations WHERE request_id = %s FOR UPDATE", (request_id,))
        op = cur.fetchone()
        return run, session, epoch, op

    # --- verbs -----------------------------------------------------------------

    def _v_start(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest, existing = self._begin_admission(cur, "start", payload)
        if existing is not None:
            return self._replay(cur, "start", existing)
        text = _message(payload)
        session_id = payload.get("session_id") or str(uuid4())
        if type(session_id) is not str or not session_id:
            raise ControlError("Rejected")
        parent = payload.get("parent_session_id")
        if parent is not None:
            if type(parent) is not str or not parent:
                raise ControlError("Rejected")
            cur.execute("SELECT 1 FROM v20_sessions WHERE session_id = %s", (parent,))
            if cur.fetchone() is None:
                raise ControlError("Rejected")
        cur.execute("SELECT 1 FROM v20_sessions WHERE session_id = %s", (session_id,))
        if cur.fetchone() is not None:
            raise ControlError("Rejected")
        runtime = payload.get("owning_runtime_id") or "alpha"
        if type(runtime) is not str or not runtime:
            raise ControlError("Rejected")
        pid = self._backend_pid(cur)
        name = payload.get("name") if type(payload.get("name")) is str else ""
        cur.execute(
            """INSERT INTO v20_sessions (
                   session_id, owning_runtime_id, owning_runtime_generation, registration_generation,
                   last_epoch_ordinal, continuity_generation, state, resumable, list_hidden,
                   parent_session_id, revision, updated_at)
               VALUES (%s, %s, 1, 1, 1, 1, 'active', true, false, %s, 1, clock_timestamp())""",
            (session_id, runtime, parent),
        )
        cur.execute(
            """INSERT INTO v20_session_profiles (session_id, name) VALUES (%s, %s)""",
            (session_id, name),
        )
        cur.execute("INSERT INTO v20_session_provider_handles (session_id) VALUES (%s)", (session_id,))
        cur.execute(
            """INSERT INTO v20_runs (
                   run_id, session_id, revision, status, transcript_item_count,
                   owner_generation, owner_backend_pid, updated_at)
               VALUES (%s, %s, 1, 'running', 0, 1, %s, clock_timestamp())""",
            (session_id, session_id, pid),
        )
        epoch_id = str(uuid4())
        cur.execute(
            """INSERT INTO v20_epochs (
                   epoch_id, session_id, run_id, ordinal, continuity_generation, transition_kind,
                   activation_id, registration_generation)
               VALUES (%s, %s, %s, 1, 1, 'initial', %s, 1)""",
            (epoch_id, session_id, session_id, str(uuid4())),
        )
        self._insert_op(
            cur, request_id=payload["request_id"], verb="start", epoch_id=epoch_id,
            owner_generation=1, attempt_seq=1, expects_handle=True, handle_state="pending",
            depends_on=None, input_message=text, digest=digest,
        )
        transcript_id = str(uuid4())
        cur.execute(
            """INSERT INTO v20_transcript_turns (turn_id, session_id, retention_tier, started_at)
               VALUES (%s, %s, 'alpha', clock_timestamp())""",
            (transcript_id, session_id),
        )
        self._activity(cur, transcript_id, "user", "request", text)
        self._event(cur, "start", session_id, session_id, epoch_id, payload["request_id"])
        op = self._reload_op(cur, payload["request_id"])
        run = self._reload_run(cur, session_id)
        body = self._shape("start", run, op, parent_session_id=parent, transcript_turn_id=transcript_id)
        body["_notify"] = (session_id, run["revision"])
        return body

    def _open_follow(self, cur, run, session, epoch, payload, verb: str, digest: str,
                     text: str, kind: str, *, touch_owner: bool) -> dict[str, Any]:
        self._close_epoch(cur, epoch["epoch_id"])
        self._finish_pending(cur, epoch["epoch_id"], "closed")
        self._settle_completed_handles(cur, session["session_id"])
        attempt = self._next_attempt(cur, session["session_id"])
        depends = self._depends_on(cur, session["session_id"], attempt)
        ordinal = session["last_epoch_ordinal"] + 1
        continuity = session["continuity_generation"] + (1 if kind == "unrelated" else 0)
        epoch_id = self._insert_epoch(cur, session, run, kind, ordinal, continuity)
        pid = self._backend_pid(cur)
        cur.execute(
            """UPDATE v20_sessions SET
                   state = 'active', last_epoch_ordinal = %s, continuity_generation = %s,
                   revision = revision + 1, updated_at = clock_timestamp()
               WHERE session_id = %s""",
            (ordinal, continuity, session["session_id"]),
        )
        generation = run["owner_generation"]
        cur.execute(
            """UPDATE v20_runs SET
                   status = 'running', revision = revision + 1, interaction = NULL,
                   failure_reason = NULL, owner_backend_pid = %s, updated_at = clock_timestamp()
               WHERE run_id = %s""",
            (pid, run["run_id"]),
        )
        if touch_owner:
            generation = run["owner_generation"]
        self._insert_op(
            cur, request_id=payload["request_id"], verb=verb, epoch_id=epoch_id,
            owner_generation=generation, attempt_seq=attempt, expects_handle=True,
            handle_state="pending", depends_on=depends, input_message=text, digest=digest,
        )
        transcript = self._transcript_id(cur, session["session_id"])
        self._activity(cur, transcript, "user", "request", text)
        self._event(cur, verb, session["session_id"], run["run_id"], epoch_id, payload["request_id"])
        op = self._reload_op(cur, payload["request_id"])
        fresh = self._reload_run(cur, run["run_id"])
        body = self._shape(verb, fresh, op, parent_session_id=session["parent_session_id"])
        body["_notify"] = (run["run_id"], fresh["revision"])
        return body

    def _v_steer(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest, existing = self._begin_admission(cur, "steer", payload)
        if existing is not None:
            return self._replay(cur, "steer", existing)
        text = _message(payload)
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        expected = _int(payload.get("expected_revision"))
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_current_epoch(cur, session)
        if not session["resumable"] or session["state"] == "terminal":
            raise ControlError("Rejected")
        if "owner_generation" in payload and payload["owner_generation"] != run["owner_generation"]:
            raise ControlError("Rejected")
        if expected != run["revision"] or expected != session["revision"]:
            raise ControlError("RevisionConflict")
        return self._open_follow(cur, run, session, epoch, payload, "steer", digest, text, "steering",
                                 touch_owner=False)

    def _v_claim_resume(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest, existing = self._begin_admission(cur, "claim_resume", payload)
        if existing is not None:
            return self._replay(cur, "claim_resume", existing)
        text = _message(payload)
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        kind = payload.get("transition_kind", "related_follow_up")
        if kind not in {"related_follow_up", "unrelated"}:
            raise ControlError("Rejected")
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_current_epoch(cur, session)
        if not session["resumable"] or session["state"] == "terminal":
            raise ControlError("Rejected")
        if run["status"] in RUNNABLE:
            if self._pid_alive(cur, run["owner_backend_pid"]):
                raise ControlError("AlreadyActive")
            raise ControlError("Rejected")
        if run["status"] not in RESUME_OK:
            raise ControlError("Rejected")
        return self._open_follow(cur, run, session, epoch, payload, "claim_resume", digest, text, kind,
                                 touch_owner=False)

    def _v_respond(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest, existing = self._begin_admission(cur, "respond", payload)
        if existing is not None:
            return self._replay(cur, "respond", existing)
        text = _message(payload)
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        expected = _int(payload.get("expected_revision"))
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_current_epoch(cur, session)
        if run["status"] != "waiting_for_input":
            raise ControlError("Rejected")
        if not session["resumable"] or session["state"] == "terminal":
            raise ControlError("Rejected")
        if expected != run["revision"] or expected != session["revision"]:
            raise ControlError("RevisionConflict")
        if not self._epoch_matches(epoch, session):
            raise ControlError("Rejected")
        attempt = self._next_attempt(cur, session["session_id"])
        depends = self._depends_on(cur, session["session_id"], attempt)
        self._insert_op(
            cur, request_id=payload["request_id"], verb="respond", epoch_id=epoch["epoch_id"],
            owner_generation=run["owner_generation"], attempt_seq=attempt, expects_handle=True,
            handle_state="pending", depends_on=depends, input_message=text, digest=digest,
        )
        cur.execute(
            """UPDATE v20_runs SET status = 'running', revision = revision + 1, interaction = NULL,
                   updated_at = clock_timestamp() WHERE run_id = %s""",
            (run_id,),
        )
        cur.execute(
            """UPDATE v20_sessions SET revision = revision + 1, updated_at = clock_timestamp()
               WHERE session_id = %s""",
            (session["session_id"],),
        )
        transcript = self._transcript_id(cur, session["session_id"])
        self._activity(cur, transcript, "user", "request", text)
        self._event(cur, "respond", session["session_id"], run_id, epoch["epoch_id"], payload["request_id"])
        op = self._reload_op(cur, payload["request_id"])
        fresh = self._reload_run(cur, run_id)
        body = self._shape("respond", fresh, op, parent_session_id=session["parent_session_id"])
        body["_notify"] = (run_id, fresh["revision"])
        return body

    def _v_cancel(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_current_epoch(cur, session)
        if run["status"] not in RUNNABLE:
            return self._shape("cancel", run, parent_session_id=session["parent_session_id"])
        cur.execute(
            """UPDATE v20_runs SET status = 'cancelled', revision = revision + 1,
                   updated_at = clock_timestamp() WHERE run_id = %s""",
            (run_id,),
        )
        cur.execute(
            """UPDATE v20_sessions SET revision = revision + 1, updated_at = clock_timestamp()
               WHERE session_id = %s""",
            (session["session_id"],),
        )
        self._close_epoch(cur, epoch["epoch_id"])
        self._finish_pending(cur, epoch["epoch_id"], "closed")
        self._event(cur, "cancel", session["session_id"], run_id, epoch["epoch_id"], "cancel")
        fresh = self._reload_run(cur, run_id)
        body = self._shape("cancel", fresh, parent_session_id=session["parent_session_id"])
        body["_notify"] = (run_id, fresh["revision"])
        return body

    def _v_cleanup(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id")
        session_id = payload.get("session_id")
        if run_id is None and type(session_id) is str:
            cur.execute("SELECT run_id FROM v20_runs WHERE session_id = %s", (session_id,))
            found = cur.fetchone()
            if found is None:
                raise ControlError("Rejected")
            run_id = found["run_id"]
        if type(run_id) is not str:
            raise ControlError("Rejected")
        hidden = payload.get("list_hidden", False)
        if type(hidden) is not bool:
            raise ControlError("Rejected")
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_current_epoch(cur, session)
        if session["state"] == "terminal" and session["resumable"] is False:
            return self._shape("cleanup", run, parent_session_id=session["parent_session_id"])
        self._close_epoch(cur, epoch["epoch_id"])
        self._finish_pending(cur, epoch["epoch_id"], "closed")
        notify = run["status"] in RUNNABLE
        if notify:
            cur.execute(
                """UPDATE v20_runs SET status = 'cancelled', revision = revision + 1,
                       updated_at = clock_timestamp() WHERE run_id = %s""",
                (run_id,),
            )
            cur.execute(
                """UPDATE v20_sessions SET state = 'terminal', resumable = false, list_hidden = %s,
                       revision = revision + 1, updated_at = clock_timestamp()
                   WHERE session_id = %s""",
                (hidden, session["session_id"]),
            )
        else:
            cur.execute(
                """UPDATE v20_sessions SET state = 'terminal', resumable = false, list_hidden = %s,
                       updated_at = clock_timestamp() WHERE session_id = %s""",
                (hidden, session["session_id"]),
            )
        self._event(cur, "cleanup", session["session_id"], run_id, epoch["epoch_id"], "cleanup")
        fresh = self._reload_run(cur, run_id)
        body = self._shape("cleanup", fresh, parent_session_id=session["parent_session_id"])
        if notify:
            body["_notify"] = (run_id, fresh["revision"])
        return body

    def _v_recover_owner(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_current_epoch(cur, session)
        if self._pid_alive(cur, run["owner_backend_pid"]):
            raise ControlError("AlreadyActive")
        if run["status"] == "expired":
            return self._shape("recover_owner", run, parent_session_id=session["parent_session_id"])
        if run["status"] not in RUNNABLE:
            raise ControlError("Rejected")
        cur.execute(
            """UPDATE v20_runs SET owner_generation = owner_generation + 1, status = 'expired',
                   revision = revision + 1, updated_at = clock_timestamp()
               WHERE run_id = %s""",
            (run_id,),
        )
        cur.execute(
            """UPDATE v20_sessions SET registration_generation = registration_generation + 1,
                   state = 'interrupted', revision = revision + 1, updated_at = clock_timestamp()
               WHERE session_id = %s""",
            (session["session_id"],),
        )
        self._close_epoch(cur, epoch["epoch_id"])
        self._finish_pending(cur, epoch["epoch_id"], "archived")
        self._settle_completed_handles(cur, session["session_id"])
        self._event(cur, "recover_owner", session["session_id"], run_id, epoch["epoch_id"], "recover")
        fresh = self._reload_run(cur, run_id)
        body = self._shape("recover_owner", fresh, parent_session_id=session["parent_session_id"])
        body["_notify"] = (run_id, fresh["revision"])
        return body

    def _v_admit_turn(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest, existing = self._begin_admission(cur, "admit_turn", payload)
        if existing is not None:
            return self._replay(cur, "admit_turn", existing)
        instruction = payload.get("instruction")
        if type(instruction) is not str:
            raise ControlError("Rejected")
        storage_safe_json(instruction)
        run_id = payload.get("run_id")
        epoch_id = payload.get("epoch_id")
        kind = payload.get("input_kind")
        if type(run_id) is not str or type(epoch_id) is not str or type(kind) is not str:
            raise ControlError("Rejected")
        owner = _int(payload.get("owner_generation"))
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_epoch_id(cur, epoch_id)
        if epoch["run_id"] != run["run_id"] or epoch["session_id"] != session["session_id"]:
            raise ControlError("Rejected")
        if not self._epoch_matches(epoch, session) or run["status"] not in RUNNABLE:
            raise ControlError("Rejected")
        if owner != run["owner_generation"]:
            raise ControlError("Rejected")
        driving = self._driving(cur, session["session_id"])
        if driving is None:
            raise ControlError("Rejected")
        expected = self._expected_kind(cur, session, driving)
        if kind != expected or instruction != driving["input_message"]:
            raise ControlError("Rejected")
        results: list[Any] = []
        if expected == "host_continue":
            cur.execute(
                """SELECT count(*) AS n FROM v20_operations
                   WHERE epoch_id = %s AND verb = 'admit_tool' AND status = 'pending'""",
                (epoch_id,),
            )
            if cur.fetchone()["n"]:
                raise ControlError("Rejected")
            results = self._tool_results(cur, epoch_id)
            if "tool_results" in payload and canonical_json(payload["tool_results"]) != canonical_json(results):
                raise ControlError("Rejected")
        elif payload.get("tool_results"):
            raise ControlError("Rejected")
        attempt = self._next_attempt(cur, session["session_id"])
        self._insert_op(
            cur, request_id=payload["request_id"], verb="admit_turn", epoch_id=epoch_id,
            owner_generation=run["owner_generation"], attempt_seq=attempt, expects_handle=False,
            handle_state="absent", depends_on=None, input_message=instruction, digest=digest,
        )
        turn_id = str(uuid4())
        explicit = payload.get("transcript_turn_id")
        transcript = self._transcript_id(cur, session["session_id"], explicit if explicit else None)
        receipt = {"input_kind": kind, "instruction": instruction}
        if expected == "host_continue":
            receipt["tool_results"] = results
        cur.execute(
            """INSERT INTO v20_turns (
                   turn_id, request_id, run_id, epoch_id, owner_generation, transcript_turn_id,
                   status, receipt)
               VALUES (%s, %s, %s, %s, %s, %s, 'admitted', %s)""",
            (turn_id, payload["request_id"], run_id, epoch_id, run["owner_generation"],
             transcript, Json(receipt)),
        )
        self._activity(cur, transcript, "user", "request", instruction)
        self._event(cur, "admit_turn", session["session_id"], run_id, epoch_id, payload["request_id"])
        op = self._reload_op(cur, payload["request_id"])
        return self._shape("admit_turn", run, op, turn_id=turn_id, transcript_turn_id=transcript,
                           parent_session_id=session["parent_session_id"])

    def _matched(self, epoch, session, op, run) -> bool:
        return self._epoch_matches(epoch, session) and op["owner_generation"] == run["owner_generation"]

    def _v_accept_turn_receipt(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        target = payload.get("request_id")
        receipt = payload.get("receipt")
        if type(target) is not str or type(receipt) is not dict:
            raise ControlError("Rejected")
        run, session, epoch, op = self._load_op_context(cur, target)
        cur.execute("SELECT * FROM v20_turns WHERE request_id = %s FOR UPDATE", (target,))
        turn = cur.fetchone()
        if turn is None:
            raise ControlError("Rejected")
        claimed = receipt.get("request_id", target)
        if claimed != target:
            self._event(cur, "archive", session["session_id"], run["run_id"], epoch["epoch_id"],
                        "request_id mismatch")
            return self._shape("accept_turn_receipt", run, op)
        matched = self._matched(epoch, session, op, run)
        if op["status"] == "completed" and matched:
            return self._shape("accept_turn_receipt", run, op)
        if not (op["status"] == "pending" and matched and run["status"] in RUNNABLE):
            self._fence(cur, run, epoch["epoch_id"], op, "turn fence")
        initial = _load(turn["receipt"]) or {}
        validate_stored_receipt(receipt)
        if receipt.get("run_id") != turn["run_id"] or receipt.get("turn_id") != turn["turn_id"]:
            raise WorkerContractError("receipt identity does not match the turn")
        if receipt.get("input_kind") != initial.get("input_kind"):
            raise ControlError("Rejected")
        stored = dict(receipt)
        stored["request_id"] = target
        cur.execute(
            """UPDATE v20_operations SET status = 'completed', result = %s WHERE request_id = %s""",
            (Json(stored), target),
        )
        cur.execute(
            "UPDATE v20_turns SET status = 'completed', receipt = %s WHERE turn_id = %s",
            (Json(stored), turn["turn_id"]),
        )
        if turn["transcript_turn_id"]:
            self._activity(cur, turn["transcript_turn_id"], "assistant", "response",
                           canonical_json(receipt.get("result")))
        self._event(cur, "accept_turn_receipt", session["session_id"], run["run_id"],
                    epoch["epoch_id"], target)
        op = self._reload_op(cur, target)
        return self._shape("accept_turn_receipt", run, op)

    def _v_admit_tool(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest, existing = self._begin_admission(cur, "admit_tool", payload)
        if existing is not None:
            return self._replay(cur, "admit_tool", existing)
        run_id = payload.get("run_id")
        epoch_id = payload.get("epoch_id")
        turn_id = payload.get("turn_id")
        name = payload.get("tool_name")
        if type(run_id) is not str or type(epoch_id) is not str or type(turn_id) is not str:
            raise ControlError("Rejected")
        if type(name) is not str or not name.strip():
            raise ControlError("Rejected")
        owner = _int(payload.get("owner_generation"))
        arguments = payload.get("arguments")
        stored_input = canonical_json({"tool_name": name, "arguments": arguments})
        run, session = self._lock_run(cur, run_id)
        epoch = self._lock_epoch_id(cur, epoch_id)
        if not self._epoch_matches(epoch, session) or run["status"] not in RUNNABLE:
            raise ControlError("Rejected")
        if owner != run["owner_generation"] or epoch["run_id"] != run["run_id"]:
            raise ControlError("Rejected")
        cur.execute("SELECT * FROM v20_turns WHERE turn_id = %s", (turn_id,))
        turn = cur.fetchone()
        if turn is None or turn["run_id"] != run["run_id"] or turn["epoch_id"] != epoch["epoch_id"]:
            raise ControlError("Rejected")
        attempt = self._next_attempt(cur, session["session_id"])
        self._insert_op(
            cur, request_id=payload["request_id"], verb="admit_tool", epoch_id=epoch_id,
            owner_generation=run["owner_generation"], attempt_seq=attempt, expects_handle=False,
            handle_state="absent", depends_on=None, input_message=stored_input, digest=digest,
        )
        invocation_id = payload.get("invocation_id") or str(uuid4())
        if type(invocation_id) is not str or not invocation_id:
            raise ControlError("Rejected")
        cur.execute(
            """INSERT INTO v20_tool_invocations (
                   invocation_id, request_id, run_id, turn_id, epoch_id, owner_generation,
                   tool_name, status, request_digest, lease_deadline)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'admitted', %s,
                       clock_timestamp() + interval '30 seconds')""",
            (invocation_id, payload["request_id"], run_id, turn_id, epoch_id,
             run["owner_generation"], name, sha256_json(arguments)),
        )
        if turn["transcript_turn_id"]:
            self._activity(cur, turn["transcript_turn_id"], "tool", "tool_request", stored_input,
                           invocation_id)
        self._event(cur, "admit_tool", session["session_id"], run_id, epoch_id, payload["request_id"])
        op = self._reload_op(cur, payload["request_id"])
        return self._shape("admit_tool", run, op, invocation_id=invocation_id, turn_id=turn_id)

    def _v_accept_tool_result(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        target = payload.get("request_id")
        if type(target) is not str:
            raise ControlError("Rejected")
        status = payload.get("status")
        if status not in {"completed", "failed"}:
            raise ControlError("Rejected")
        run, session, epoch, op = self._load_op_context(cur, target)
        cur.execute("SELECT * FROM v20_tool_invocations WHERE request_id = %s FOR UPDATE", (target,))
        invocation = cur.fetchone()
        if invocation is None:
            raise ControlError("Rejected")
        claimed = payload.get("receipt_request_id", target)
        if claimed != target:
            self._event(cur, "archive", session["session_id"], run["run_id"], epoch["epoch_id"],
                        "request_id mismatch")
            return self._shape("accept_tool_result", run, op)
        matched = self._matched(epoch, session, op, run)
        if op["status"] == "completed" and matched:
            return self._shape("accept_tool_result", run, op)
        if not (op["status"] == "pending" and matched and run["status"] in RUNNABLE):
            self._fence(cur, run, epoch["epoch_id"], op, "tool fence")
        output = payload.get("output")
        storage_safe_json(output)
        result = {"status": status, "output": output, "tool_name": invocation["tool_name"]}
        cur.execute(
            """UPDATE v20_operations SET status = 'completed', result = %s WHERE request_id = %s""",
            (Json(result), target),
        )
        cur.execute(
            """UPDATE v20_tool_invocations SET status = %s, result_digest = %s
               WHERE invocation_id = %s""",
            (status, sha256_json(output), invocation["invocation_id"]),
        )
        cur.execute("SELECT transcript_turn_id FROM v20_turns WHERE turn_id = %s", (invocation["turn_id"],))
        turn = cur.fetchone()
        if turn and turn["transcript_turn_id"]:
            self._activity(cur, turn["transcript_turn_id"], "tool", "tool_result", canonical_json(output),
                           invocation["invocation_id"])
        self._event(cur, "accept_tool_result", session["session_id"], run["run_id"],
                    epoch["epoch_id"], target)
        op = self._reload_op(cur, target)
        fresh = self._reload_run(cur, run["run_id"])
        return self._shape("accept_tool_result", fresh, op)

    def _v_publish_snapshot(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        request_id = payload.get("request_id")
        if type(request_id) is not str:
            raise ControlError("Rejected")
        mode = payload.get("mode")
        if mode not in {"progress", "final"}:
            raise ControlError("Rejected")
        if payload.get("no_handle") and payload.get("provider_handle") is not None:
            raise ControlError("Rejected")
        run, session, epoch, op = self._load_op_context(cur, request_id)
        _require_handle_op(op)
        matched = self._matched(epoch, session, op, run)
        if mode == "progress":
            seq = _int(payload.get("snapshot_seq"))
            if seq < 1:
                raise ControlError("Rejected")
            if not (matched and op["status"] == "pending" and run["status"] == "running"):
                self._fence(cur, run, epoch["epoch_id"], op, "snapshot fence")
            if op["snapshot_seq"] is not None and seq <= op["snapshot_seq"]:
                return self._shape("publish_snapshot", run, op)
            preview = payload.get("preview")
            if preview is not None and type(preview) is not str:
                raise ControlError("Rejected")
            cur.execute(
                "UPDATE v20_operations SET snapshot_seq = %s WHERE request_id = %s",
                (seq, request_id),
            )
            cur.execute(
                """UPDATE v20_runs SET revision = revision + 1, latest_assistant_preview = %s,
                       updated_at = clock_timestamp() WHERE run_id = %s""",
                (preview, run["run_id"]),
            )
            cur.execute(
                """UPDATE v20_sessions SET revision = revision + 1, updated_at = clock_timestamp()
                   WHERE session_id = %s""",
                (session["session_id"],),
            )
            self._event(cur, "publish_snapshot", session["session_id"], run["run_id"],
                        epoch["epoch_id"], request_id)
            if payload.get("bare_progress"):
                self._event(cur, "bare_progress", session["session_id"], run["run_id"],
                            epoch["epoch_id"], request_id)
            if payload.get("provider_handle") is not None:
                self._apply_handle(cur, op, run, session, epoch, payload["provider_handle"])
            op = self._reload_op(cur, request_id)
            fresh = self._reload_run(cur, run["run_id"])
            body = self._shape("publish_snapshot", fresh, op)
            body["_notify"] = (run["run_id"], fresh["revision"])
            return body
        if op["status"] == "completed" and matched:
            return self._shape("publish_snapshot", run, op)
        if not (matched and op["status"] == "pending" and run["status"] == "running"):
            self._fence(cur, run, epoch["epoch_id"], op, "snapshot fence")
        outcome = payload.get("outcome")
        if outcome not in {"waiting_for_input", "completed", "failed"}:
            raise ControlError("Rejected")
        preview = payload.get("preview")
        if preview is not None and type(preview) is not str:
            raise ControlError("Rejected")
        interaction = payload.get("interaction") if outcome == "waiting_for_input" else None
        failure = payload.get("failure_reason") if outcome == "failed" else None
        if failure is not None and type(failure) is not str:
            raise ControlError("Rejected")
        if interaction is not None:
            storage_safe_json(interaction)
        stored = {
            "outcome": outcome,
            "result": payload.get("result"),
            "preview": preview,
            "interaction": interaction,
            "failure_reason": failure,
        }
        storage_safe_json(stored)
        cur.execute("SELECT 1 FROM v20_provider_handle_attempts WHERE request_id = %s", (request_id,))
        has_attempt = cur.fetchone() is not None
        handle_state = op["handle_state"]
        if payload.get("no_handle") and not has_attempt and handle_state == "pending":
            handle_state = "absent"
        new_state = "dormant" if outcome == "completed" else session["state"]
        cur.execute(
            """UPDATE v20_runs SET revision = revision + 1, status = %s,
                   latest_assistant_preview = %s, interaction = %s, failure_reason = %s,
                   updated_at = clock_timestamp() WHERE run_id = %s""",
            (outcome, preview, None if interaction is None else Json(interaction), failure, run["run_id"]),
        )
        cur.execute(
            """UPDATE v20_sessions SET revision = revision + 1, state = %s,
                   updated_at = clock_timestamp() WHERE session_id = %s""",
            (new_state, session["session_id"]),
        )
        cur.execute(
            """UPDATE v20_operations SET status = 'completed', result = %s, handle_state = %s
               WHERE request_id = %s""",
            (Json(stored), handle_state, request_id),
        )
        self._event(cur, "publish_snapshot", session["session_id"], run["run_id"],
                    epoch["epoch_id"], request_id)
        if payload.get("provider_handle") is not None:
            fresh_op = self._reload_op(cur, request_id)
            self._apply_handle(cur, fresh_op, run, session, epoch, payload["provider_handle"])
        op = self._reload_op(cur, request_id)
        fresh = self._reload_run(cur, run["run_id"])
        body = self._shape("publish_snapshot", fresh, op)
        body["_notify"] = (run["run_id"], fresh["revision"])
        return body

    def _v_record_provider_handle(self, cur, payload: Mapping[str, Any]) -> dict[str, Any]:
        request_id = payload.get("request_id")
        if type(request_id) is not str or "handle" not in payload or payload["handle"] is None:
            raise ControlError("Rejected")
        run, session, epoch, op = self._load_op_context(cur, request_id)
        _require_handle_op(op)
        before_result = op["result"]
        before_status = op["status"]
        self._apply_handle(cur, op, run, session, epoch, payload["handle"])
        restored = None if before_result is None else Json(_load(before_result))
        cur.execute(
            """UPDATE v20_operations SET status = %s, result = %s, handle_state = 'present'
               WHERE request_id = %s""",
            (before_status, restored, request_id),
        )
        self._event(cur, "record_provider_handle", session["session_id"], run["run_id"],
                    epoch["epoch_id"], request_id)
        op = self._reload_op(cur, request_id)
        fresh = self._reload_run(cur, run["run_id"])
        return self._shape("record_provider_handle", fresh, op)

    @contextmanager
    def _read(self):
        """Read and return the connection to idle, including when the read rejects."""
        if self.in_transaction():
            raise ControlError("Rejected")
        cur = self.conn.cursor()
        try:
            yield cur
        except Exception:
            if self.conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                self.conn.rollback()
            raise
        else:
            self.conn.commit()
        finally:
            cur.close()

    def _poll(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._bind()
        if self.in_transaction():
            raise ControlError("Rejected")
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        with self._read() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT * FROM v20_runs WHERE run_id = %s", (run_id,))
            run = cur.fetchone()
            if run is None:
                raise ControlError("Rejected")
            cur.execute("SELECT * FROM v20_sessions WHERE session_id = %s", (run["session_id"],))
            session = cur.fetchone()
            cur.execute(
                """SELECT * FROM v20_epochs WHERE session_id = %s AND ordinal = %s""",
                (session["session_id"], session["last_epoch_ordinal"]),
            )
            epoch = cur.fetchone()
            cur.execute(
                """SELECT o.* FROM v20_operations o
                   JOIN v20_epochs e ON e.epoch_id = o.epoch_id
                   WHERE e.session_id = %s AND o.expects_handle
                   ORDER BY (o.status = 'pending') DESC, o.attempt_seq DESC LIMIT 1""",
                (session["session_id"],),
            )
            driving = cur.fetchone()
            dep_state = None
            if driving and driving["depends_on_request_id"]:
                cur.execute(
                    "SELECT handle_state FROM v20_operations WHERE request_id = %s",
                    (driving["depends_on_request_id"],),
                )
                dep = cur.fetchone()
                dep_state = None if dep is None else dep["handle_state"]
            epoch_id = None if epoch is None else epoch["epoch_id"]
            pending_tools = []
            pending_turns = []
            completed_tools = 0
            bare = False
            continue_needed = False
            tool_results: list[Any] = []
            if epoch_id is not None:
                cur.execute(
                    """SELECT o.request_id, o.input_message, i.invocation_id, i.tool_name, i.turn_id, i.epoch_id
                       FROM v20_operations o
                       JOIN v20_tool_invocations i ON i.request_id = o.request_id
                       WHERE o.verb = 'admit_tool' AND o.status = 'pending' AND o.epoch_id = %s
                       ORDER BY o.attempt_seq""",
                    (epoch_id,),
                )
                for row in cur.fetchall():
                    try:
                        parsed = __import__("json").loads(row["input_message"])
                        arguments = parsed.get("arguments")
                    except (TypeError, ValueError):
                        arguments = None
                    pending_tools.append({
                        "request_id": row["request_id"],
                        "invocation_id": row["invocation_id"],
                        "tool_name": row["tool_name"],
                        "arguments": arguments,
                        "turn_id": row["turn_id"],
                        "epoch_id": row["epoch_id"],
                    })
                cur.execute(
                    """SELECT o.request_id, t.turn_id, t.epoch_id, t.run_id, t.receipt, t.owner_generation
                       FROM v20_operations o
                       JOIN v20_turns t ON t.request_id = o.request_id
                       WHERE o.verb = 'admit_turn' AND o.status = 'pending' AND o.epoch_id = %s
                       ORDER BY o.attempt_seq""",
                    (epoch_id,),
                )
                pending_turns = [dict(row) for row in cur.fetchall()]
                if (
                    driving is not None
                    and driving["status"] == "pending"
                    and driving["expects_handle"]
                ):
                    cur.execute(
                        """SELECT count(*) AS n FROM v20_tool_invocations i
                           JOIN v20_operations o ON o.request_id = i.request_id
                           WHERE i.epoch_id = %s AND o.status = 'completed'
                             AND o.attempt_seq > %s""",
                        (epoch_id, driving["attempt_seq"]),
                    )
                    completed_tools = cur.fetchone()["n"]
                tool_results = self._tool_results(cur, epoch_id)
                if driving and driving["status"] == "pending" and not pending_tools and not pending_turns:
                    cur.execute(
                        """SELECT t.receipt, t.status FROM v20_turns t
                           JOIN v20_operations o ON o.request_id = t.request_id
                           WHERE t.epoch_id = %s AND o.attempt_seq > %s
                           ORDER BY o.attempt_seq""",
                        (driving["epoch_id"], driving["attempt_seq"]),
                    )
                    after = cur.fetchall()
                    if after:
                        last = after[-1]
                        receipt = _load(last["receipt"]) or {}
                        if last["status"] == "completed" and receipt.get("tool_calls"):
                            continue_needed = True
            if driving is not None:
                cur.execute(
                    """SELECT 1 FROM v20_events
                       WHERE kind = 'bare_progress' AND run_id = %s AND message = %s LIMIT 1""",
                    (run_id, driving["request_id"]),
                )
                bare = cur.fetchone() is not None
            cur.execute(
                """SELECT turn_id FROM v20_transcript_turns WHERE session_id = %s
                   ORDER BY started_at, turn_id LIMIT 1""",
                (session["session_id"],),
            )
            transcript = cur.fetchone()
            cur.execute(
                "SELECT provider_cleanup_handle, attempt_seq, epoch_id FROM v20_session_provider_handles WHERE session_id = %s",
                (session["session_id"],),
            )
            handle_row = cur.fetchone()
        driving_view = None
        if driving is not None:
            driving_view = {
                "request_id": driving["request_id"],
                "verb": driving["verb"],
                "status": driving["status"],
                "snapshot_seq": driving["snapshot_seq"],
                "input_message": driving["input_message"],
                "handle_state": driving["handle_state"],
                "epoch_id": driving["epoch_id"],
                "owner_generation": driving["owner_generation"],
                "depends_on_request_id": driving["depends_on_request_id"],
                "attempt_seq": driving["attempt_seq"],
            }
        return {
            "request_id": None,
            "verb": "poll",
            "status": run["status"],
            "run_status": run["status"],
            "run_id": run["run_id"],
            "session_id": run["session_id"],
            "revision": run["revision"],
            "owner_generation": run["owner_generation"],
            "epoch_id": epoch_id,
            "ordinal": None if epoch is None else epoch["ordinal"],
            "continuity_generation": session["continuity_generation"],
            "parent_session_id": session["parent_session_id"],
            "session_state": session["state"],
            "resumable": session["resumable"],
            "pending_tool": bool(pending_tools),
            "pending_turn": bool(pending_turns),
            "pending_tools": pending_tools,
            "pending_turns": pending_turns,
            "depended_handle_state": dep_state,
            "driving": driving_view,
            "bare_progress": bare,
            "continue_needed": continue_needed,
            "completed_tool_count": completed_tools,
            "tool_results": tool_results,
            "transcript_turn_id": None if transcript is None else transcript["turn_id"],
            "handle": None if handle_row is None else handle_row["provider_cleanup_handle"],
            "preview": run["latest_assistant_preview"],
            "interaction": run["interaction"],
            "failure_reason": run["failure_reason"],
        }

    def _before_listen(self) -> None:
        return None

    def _after_listen(self, listener: Any) -> None:
        return None

    def _before_authoritative_read(self, listener: Any) -> None:
        return None

    def _during_wait(self, listener: Any) -> None:
        return None

    def _wait(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self._bind()
        if self.in_transaction():
            raise ControlError("Rejected")
        run_id = payload.get("run_id")
        if type(run_id) is not str:
            raise ControlError("Rejected")
        timeout = _timeout(payload.get("timeout_seconds", 2.0))
        since = payload.get("since_revision")
        if since is not None:
            since = _int(since)
        listener = psycopg2.connect(self.dsn, application_name="v20_alpha_wait")
        listener.autocommit = False
        try:
            self._before_listen()
            with listener.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("LISTEN " + CHANNEL)
            listener.commit()
            self._after_listen(listener)
            if listener.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                listener.commit()
            self._before_authoritative_read(listener)

            def read() -> dict[str, Any]:
                with listener.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT r.revision, r.status, r.session_id, r.run_id
                           FROM v20_runs r WHERE r.run_id = %s""",
                        (run_id,),
                    )
                    row = cur.fetchone()
                listener.commit()
                if row is None:
                    raise ControlError("Rejected")
                return row

            row = read()
            if since is None or row["revision"] > since:
                return self._wait_shape(row)
            self._during_wait(listener)
            if listener.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                listener.commit()
            deadline = time.monotonic() + float(timeout)
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                ready, _, _ = select.select([listener], [], [], remaining)
                if not ready:
                    break
                listener.poll()
                listener.notifies.clear()
                row = read()
                if since is not None and row["revision"] > since:
                    return self._wait_shape(row)
            row = read()
            return self._wait_shape(row)
        finally:
            listener.close()

    def _wait_shape(self, row) -> dict[str, Any]:
        return {
            "request_id": None,
            "verb": "wait",
            "status": row["status"],
            "run_status": row["status"],
            "run_id": row["run_id"],
            "session_id": row["session_id"],
            "revision": row["revision"],
        }

    def resolve_handle(self, request_id: str, timeout: float = 2.0) -> dict[str, Any]:
        """Wait outside a transaction for depends_on_request_id. One wait, then return."""
        self._bind()
        if self.in_transaction():
            raise ControlError("Rejected")
        timeout = _timeout(timeout)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT depends_on_request_id, expects_handle FROM v20_operations WHERE request_id = %s",
                (request_id,),
            )
            row = cur.fetchone()
        self.conn.commit()
        if row is None:
            raise ControlError("Rejected")
        dep = row["depends_on_request_id"]
        if not dep:
            return {"state": "empty", "handle": None}
        return self._resolve_dep(dep, float(timeout), allow_wait=True)

    def _resolve_dep(self, dep_id: str, timeout: float, allow_wait: bool) -> dict[str, Any]:
        with self.conn.cursor() as cur:
            cur.execute(
                """SELECT o.handle_state, o.attempt_seq, e.session_id
                   FROM v20_operations o JOIN v20_epochs e ON e.epoch_id = o.epoch_id
                   WHERE o.request_id = %s""",
                (dep_id,),
            )
            op = cur.fetchone()
        self.conn.commit()
        if op is None:
            return {"state": "empty", "handle": None}
        if op["handle_state"] == "present":
            return {"state": "present", "handle": self._attempt_handle(dep_id)}
        if op["handle_state"] == "absent":
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT a.handle FROM v20_operations o
                       JOIN v20_epochs e ON e.epoch_id = o.epoch_id
                       JOIN v20_provider_handle_attempts a ON a.request_id = o.request_id
                       WHERE e.session_id = %s AND o.expects_handle AND o.handle_state = 'present'
                         AND o.attempt_seq < %s
                       ORDER BY o.attempt_seq DESC LIMIT 1""",
                    (op["session_id"], op["attempt_seq"]),
                )
                earlier = cur.fetchone()
            self.conn.commit()
            if earlier is not None:
                return {"state": "present", "handle": earlier["handle"]}
            return {"state": "empty", "handle": None}
        if not allow_wait:
            return {"state": "pending"}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
            with self.conn.cursor() as cur:
                cur.execute("SELECT handle_state FROM v20_operations WHERE request_id = %s", (dep_id,))
                current = cur.fetchone()
            self.conn.commit()
            if current is None or current["handle_state"] != "pending":
                return self._resolve_dep(dep_id, timeout, allow_wait=False)
        return {"state": "pending"}

    def _attempt_handle(self, request_id: str):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT handle FROM v20_provider_handle_attempts WHERE request_id = %s",
                (request_id,),
            )
            row = cur.fetchone()
        self.conn.commit()
        return None if row is None else row["handle"]
