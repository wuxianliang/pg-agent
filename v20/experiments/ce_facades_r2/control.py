"""PostgreSQL Control for the round-two facade experiment.

Control.execute is the only writer. Model calls and export files stay outside
the open transaction. poll/wait do not hold a transaction while they block.
"""

from __future__ import annotations

import hashlib
import json
import select
import threading
import time
from pathlib import Path
from typing import Any, Callable

import psycopg2
from psycopg2.extras import Json, RealDictCursor

EXPORTS = Path(__file__).resolve().parent / "exports"
CHANNEL = "v20_ce_facade"
TERMINAL = frozenset({"stopped", "cancelled", "failed"})
DISPOSITION_STATUS = {
    "run_now": "running",
    "wait": "waiting",
    "needs_input": "needs_input",
    "stop": "stopped",
    "failed": "failed",
}
PUBLIC_VERBS = frozenset(
    {"start", "poll", "wait", "steer", "respond", "cancel", "spawn", "handoff"}
)
INTERNAL_VERBS = frozenset(
    {
        "admit_turn",
        "accept_turn_receipt",
        "recover_owner",
        "note_purge",
        "bind_macro",
        "attach_workflow",
        "bind_alias",
        "bind_external",
    }
)
MANAGE_VERBS = frozenset(
    {
        "manage_create_session",
        "manage_resume_session",
        "manage_stop_session",
        "manage_cleanup",
    }
)
ALLOWED_VERBS = PUBLIC_VERBS | INTERNAL_VERBS | MANAGE_VERBS


class ControlError(Exception):
    pass


class UnknownVerb(ControlError):
    def __init__(self, verb: str) -> None:
        super().__init__(verb)
        self.verb = verb


class EntryError(ControlError):
    def __init__(self, verb: str) -> None:
        super().__init__(verb)
        self.verb = verb


class RevisionConflict(ControlError):
    pass


class IdempotencyConflict(ControlError):
    pass


class TransactionError(ControlError):
    pass


class CitationError(ControlError):
    def __init__(self, digest: str) -> None:
        super().__init__(digest)
        self.digest = digest


def digest_of(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Control:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.tx_log: list[dict[str, Any]] = []
        self._explicit = False
        self._verbs: list[str] = []
        self._objects: set[str] = set()
        self._notifies: list[tuple[str, int]] = []
        self._tx_id = ""
        self._connect()

    def _connect(self) -> None:
        self.conn = psycopg2.connect(self.dsn)
        self.conn.autocommit = True
        self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        self.cur.execute("SET statement_timeout = '15s'")
        self.cur.execute("SET lock_timeout = '10s'")

    def close(self) -> None:
        self.conn.close()

    @property
    def in_transaction(self) -> bool:
        return self._explicit

    def backend_pid(self) -> int:
        return self.conn.get_backend_pid()

    def new_id(self, prefix: str) -> str:
        self.cur.execute("SELECT nextval('ids') AS n")
        return f"{prefix}_{self.cur.fetchone()['n']}"

    def begin(self) -> str:
        if self._explicit:
            raise TransactionError("transaction already open")
        self.cur.execute("BEGIN")
        self._explicit = True
        self._verbs = []
        self._objects = set()
        self._notifies = []
        self._tx_id = self.new_id("tx")
        return self._tx_id

    def commit(self) -> dict[str, Any]:
        if not self._explicit:
            raise TransactionError("no transaction open")
        for run_id, revision in self._notifies:
            self.cur.execute(
                "SELECT pg_notify(%s, %s)",
                (CHANNEL, f"{run_id}|{revision}"),
            )
        self.cur.execute("COMMIT")
        record = {
            "tx_id": self._tx_id,
            "verbs": list(self._verbs),
            "objects": sorted(self._objects),
            "committed": True,
        }
        self.tx_log.append(record)
        self._explicit = False
        return record

    def rollback(self) -> None:
        if not self._explicit:
            raise TransactionError("no transaction open")
        self.cur.execute("ROLLBACK")
        self._explicit = False

    def execute(
        self, verb: str, payload: dict[str, Any], *, entry: str = "public"
    ) -> dict[str, Any]:
        if verb not in ALLOWED_VERBS:
            raise UnknownVerb(verb)
        if verb in MANAGE_VERBS and entry != "agent_manage":
            raise EntryError(verb)
        if "request_id" not in payload:
            raise ControlError("request_id required")
        owned = not self._explicit
        if owned:
            self.begin()
        try:
            existing = self._find_op(payload["request_id"])
            if existing is not None:
                if existing["payload_digest"] != digest_of(payload):
                    raise IdempotencyConflict(payload["request_id"])
                if owned:
                    self.commit()
                return existing["result"]
            result = self._dispatch(verb, payload)
            self.cur.execute(
                """
                INSERT INTO operations (request_id, verb, payload_digest, result)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    payload["request_id"],
                    verb,
                    digest_of(payload),
                    Json(result),
                ),
            )
            self._objects.add("operations")
            self._verbs.append(verb)
            if owned:
                self.commit()
            return result
        except Exception:
            if owned and self._explicit:
                self.rollback()
            raise

    def call_model(self, prompt: str) -> str:
        if self._explicit:
            raise TransactionError("model call inside a transaction")
        return f"fake-completion:{prompt[:80]}"

    def write_export(self, name: str, content: bytes) -> Path:
        if self._explicit:
            raise TransactionError("file write inside a transaction")
        EXPORTS.mkdir(parents=True, exist_ok=True)
        path = EXPORTS / name
        path.write_bytes(content)
        return path

    def read_export(self, name: str) -> bytes:
        if self._explicit:
            raise TransactionError("file read inside a transaction")
        path = EXPORTS / name
        if not path.exists():
            return b""
        return path.read_bytes()

    def drop_export_contents(self) -> int:
        if self._explicit:
            raise TransactionError("file write inside a transaction")
        if not EXPORTS.exists():
            return 0
        dropped = 0
        for path in EXPORTS.iterdir():
            if path.is_file() and path.stat().st_size:
                path.write_bytes(b"")
                dropped += 1
        return dropped

    def commit_forged_turn(
        self,
        *,
        run_id: str,
        prompt: str,
        disposition: str,
        artifact_kind: str | None = None,
        artifact_body: dict[str, Any] | None = None,
        export_name: str | None = None,
        session_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        if self._explicit:
            raise TransactionError("forged turn inside a transaction")
        run = self.fetch_run(run_id)
        admitted = self.execute(
            "admit_turn",
            {
                "request_id": self.new_id("req"),
                "run_id": run_id,
                "expected_revision": run["revision"],
                "owner_generation": run["owner_generation"],
                "session_id": session_id,
                "workflow_run_id": workflow_run_id,
            },
        )
        text = self.call_model(prompt)
        payload: dict[str, Any] = {
            "request_id": self.new_id("req"),
            "run_id": run_id,
            "turn_id": admitted["turn_id"],
            "expected_revision": self.fetch_run(run_id)["revision"],
            "owner_generation": self.fetch_run(run_id)["owner_generation"],
            "receipt": {"text": text, "disposition": disposition},
            "session_id": session_id,
            "workflow_run_id": workflow_run_id,
        }
        if artifact_body is not None:
            raw = json.dumps(artifact_body, sort_keys=True).encode()
            name = export_name or f"artifact-{run_id}"
            path = self.write_export(name, raw)
            payload["artifact"] = {
                "kind": artifact_kind or "blob",
                "body": artifact_body,
                "path": str(path.relative_to(EXPORTS.parent)),
                "digest": file_digest(path),
            }
        return self.execute("accept_turn_receipt", payload)

    def wait_for(
        self,
        run_id: str,
        after_revision: int,
        produce: Callable[[], None],
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Block with no open transaction. produce() must commit a newer revision."""
        if self._explicit:
            raise TransactionError("wait inside a transaction")
        idle = (
            self.conn.info.transaction_status
            == psycopg2.extensions.TRANSACTION_STATUS_IDLE
        )
        listen = psycopg2.connect(self.dsn)
        listen.autocommit = True
        payload = None
        try:
            with listen.cursor() as cur:
                cur.execute(f"LISTEN {CHANNEL}")
            ready = threading.Event()

            def _produce() -> None:
                ready.wait(timeout)
                produce()

            worker = threading.Thread(target=_produce)
            worker.start()
            ready.set()
            deadline = time.time() + timeout
            while time.time() < deadline and payload is None:
                ready_fds, _, _ = select.select([listen], [], [], 0.2)
                if not ready_fds:
                    continue
                listen.poll()
                while listen.notifies:
                    note = listen.notifies.pop(0)
                    if note.payload.split("|", 1)[0] == run_id:
                        payload = note.payload
                        break
            worker.join(timeout)
        finally:
            listen.close()
        if payload is None:
            raise ControlError(f"no notify for {run_id}")
        fields = payload.split("|")
        if len(fields) != 2:
            raise ControlError(f"notify payload must be run_id|revision, got {payload}")
        observed = self.fetch_run(run_id)
        return {
            "waiter_transaction_open": False,
            "main_connection_idle": idle,
            "path": "notify",
            "payload_fields": ["run_id", "revision"],
            "payload": payload,
            "observed_revision": observed["revision"],
            "after_revision": after_revision,
            "advanced": observed["revision"] > after_revision,
        }

    def abandon_owner(self) -> int:
        """Close this backend so recover_owner can see the owner pid is gone."""
        if self._explicit:
            raise TransactionError("cannot abandon inside a transaction")
        pid = self.conn.get_backend_pid()
        self.conn.close()
        self._connect()
        for _ in range(50):
            self.cur.execute(
                "SELECT 1 FROM pg_stat_activity WHERE pid = %s",
                (pid,),
            )
            if self.cur.fetchone() is None:
                return pid
            time.sleep(0.05)
        raise ControlError("owner backend still visible after close")

    def fetch_run(self, run_id: str) -> dict[str, Any]:
        self.cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown run {run_id}")
        return dict(row)

    def fetch_workflow(self, workflow_run_id: str) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM workflow_runs WHERE workflow_run_id = %s",
            (workflow_run_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown workflow {workflow_run_id}")
        return dict(row)

    def fetch_steps(self, workflow_run_id: str) -> list[dict[str, Any]]:
        self.cur.execute(
            """
            SELECT * FROM workflow_steps
            WHERE workflow_run_id = %s
            ORDER BY seq
            """,
            (workflow_run_id,),
        )
        return [dict(row) for row in self.cur.fetchall()]

    def fetch_alias(self, session_id: str) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM session_aliases WHERE session_id = %s",
            (session_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown alias {session_id}")
        return dict(row)

    def fetch_session(self, session_id: str) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM sessions WHERE session_id = %s",
            (session_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown session {session_id}")
        return dict(row)

    def fetch_external(self, external_id: str) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM external_ids WHERE external_id = %s",
            (external_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown external id {external_id}")
        return dict(row)

    def latest_artifact_for_runs(self, run_ids: list[str]) -> dict[str, Any] | None:
        if not run_ids:
            return None
        self.cur.execute(
            """
            SELECT digest, path, run_id, kind
            FROM artifacts
            WHERE run_id = ANY(%s)
            ORDER BY digest DESC
            LIMIT 1
            """,
            (run_ids,),
        )
        row = self.cur.fetchone()
        return dict(row) if row else None

    def alias_run_ids(self, session_id: str) -> list[str]:
        self.cur.execute(
            "SELECT run_id FROM alias_runs WHERE session_id = %s ORDER BY run_id",
            (session_id,),
        )
        return [row["run_id"] for row in self.cur.fetchall()]

    def external_run_ids(self, external_id: str) -> list[str]:
        self.cur.execute(
            """
            SELECT run_id FROM external_runs
            WHERE external_id = %s
            ORDER BY run_id
            """,
            (external_id,),
        )
        return [row["run_id"] for row in self.cur.fetchall()]

    def workflow_run_ids(self, workflow_run_id: str) -> list[str]:
        self.cur.execute(
            """
            SELECT run_id FROM runs
            WHERE workflow_run_id = %s
            ORDER BY run_id
            """,
            (workflow_run_id,),
        )
        return [row["run_id"] for row in self.cur.fetchall()]

    def _find_op(self, request_id: str) -> dict[str, Any] | None:
        self.cur.execute(
            "SELECT payload_digest, result FROM operations WHERE request_id = %s",
            (request_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            return None
        return {
            "payload_digest": row["payload_digest"],
            "result": row["result"],
        }

    def _event(self, kind: str, **fields: Any) -> None:
        refs = list(fields.get("artifact_refs") or [])
        self.cur.execute(
            """
            INSERT INTO events (
                kind, run_id, workflow_run_id, session_id, digest,
                artifact_refs, message, scope
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                kind,
                fields.get("run_id"),
                fields.get("workflow_run_id"),
                fields.get("session_id"),
                fields.get("digest"),
                refs,
                fields.get("message"),
                fields.get("scope"),
            ),
        )
        self._objects.add("events")

    def _require_artifacts(self, digests: list[str]) -> None:
        for digest in digests:
            self.cur.execute(
                "SELECT 1 FROM artifacts WHERE digest = %s",
                (digest,),
            )
            if self.cur.fetchone() is None:
                raise CitationError(digest)

    def _lock_run(self, run_id: str) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM runs WHERE run_id = %s FOR UPDATE",
            (run_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown run {run_id}")
        return dict(row)

    def _cas_run(
        self,
        run: dict[str, Any],
        expected: int | None,
        *,
        status: str | None = None,
        owner_generation: int | None = None,
        seen_generation: int | None = None,
        owner_backend_pid: int | None = None,
    ) -> dict[str, Any]:
        if expected is None or run["revision"] != expected:
            raise RevisionConflict(
                f"expected revision {expected}, found {run['revision']}"
            )
        if seen_generation is not None and run["owner_generation"] != seen_generation:
            raise RevisionConflict("owner fence mismatch")
        new_revision = run["revision"] + 1
        new_status = status or run["status"]
        new_gen = (
            owner_generation
            if owner_generation is not None
            else run["owner_generation"]
        )
        new_pid = (
            owner_backend_pid
            if owner_backend_pid is not None
            else run["owner_backend_pid"]
        )
        self.cur.execute(
            """
            UPDATE runs
            SET revision = %s, status = %s,
                owner_generation = %s, owner_backend_pid = %s
            WHERE run_id = %s AND revision = %s
            RETURNING *
            """,
            (new_revision, new_status, new_gen, new_pid, run["run_id"], expected),
        )
        updated = self.cur.fetchone()
        if updated is None:
            raise RevisionConflict(f"lost CAS on {run['run_id']}")
        self._objects.add("runs")
        self._notifies.append((run["run_id"], new_revision))
        return dict(updated)

    def _lock_workflow(self, workflow_run_id: str) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM workflow_runs WHERE workflow_run_id = %s FOR UPDATE",
            (workflow_run_id,),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError(f"unknown workflow {workflow_run_id}")
        return dict(row)

    def _bump_workflow(self, workflow: dict[str, Any], expected: int | None) -> int:
        if expected is not None and workflow["revision"] != expected:
            raise RevisionConflict(
                f"expected workflow revision {expected}, found {workflow['revision']}"
            )
        self.cur.execute(
            """
            UPDATE workflow_runs
            SET revision = revision + 1
            WHERE workflow_run_id = %s AND revision = %s
            RETURNING revision
            """,
            (workflow["workflow_run_id"], workflow["revision"]),
        )
        row = self.cur.fetchone()
        if row is None:
            raise RevisionConflict(workflow["workflow_run_id"])
        self._objects.add("workflow_runs")
        return row["revision"]

    def _insert_run(
        self,
        *,
        message: str,
        parent_run_id: str | None,
        workflow_run_id: str | None,
    ) -> dict[str, Any]:
        run_id = self.new_id("run")
        self.cur.execute("SELECT pg_backend_pid() AS pid")
        pid = self.cur.fetchone()["pid"]
        self.cur.execute(
            """
            INSERT INTO runs (
                run_id, revision, status, message, parent_run_id,
                workflow_run_id, owner_generation, owner_backend_pid
            )
            VALUES (%s, 1, 'running', %s, %s, %s, 1, %s)
            RETURNING *
            """,
            (run_id, message, parent_run_id, workflow_run_id, pid),
        )
        self._objects.add("runs")
        run = dict(self.cur.fetchone())
        self._notifies.append((run_id, 1))
        return run

    def _dispatch(self, verb: str, payload: dict[str, Any]) -> dict[str, Any]:
        handler = {
            "start": self._start,
            "spawn": self._spawn,
            "handoff": self._handoff,
            "steer": self._steer,
            "respond": self._respond,
            "cancel": self._cancel,
            "admit_turn": self._admit_turn,
            "accept_turn_receipt": self._accept_turn_receipt,
            "recover_owner": self._recover_owner,
            "note_purge": self._note_purge,
            "bind_macro": self._bind_macro,
            "attach_workflow": self._attach_workflow,
            "bind_alias": self._bind_alias,
            "bind_external": self._bind_external,
            "manage_create_session": self._manage_create_session,
            "manage_resume_session": self._manage_resume_session,
            "manage_stop_session": self._manage_stop_session,
            "manage_cleanup": self._manage_cleanup,
        }[verb]
        return handler(payload)

    def _start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("target") == "workflow":
            workflow_run_id = self.new_id("wf")
            self.cur.execute(
                """
                INSERT INTO workflow_runs (
                    workflow_run_id, revision, status, message, current_run_id
                )
                VALUES (%s, 1, 'running', %s, NULL)
                """,
                (workflow_run_id, payload.get("message") or ""),
            )
            self._objects.add("workflow_runs")
            self._event(
                "start",
                workflow_run_id=workflow_run_id,
                session_id=payload.get("session_id"),
            )
            return {
                "workflow_run_id": workflow_run_id,
                "run_id": None,
                "revision": 1,
            }
        parent = payload.get("parent_run_id") or payload.get("resume_from")
        run = self._insert_run(
            message=payload.get("message") or "",
            parent_run_id=parent,
            workflow_run_id=payload.get("workflow_run_id"),
        )
        self._event(
            "start",
            run_id=run["run_id"],
            workflow_run_id=payload.get("workflow_run_id"),
            session_id=payload.get("session_id"),
            artifact_refs=list(payload.get("artifact_refs") or []),
        )
        return {
            "run_id": run["run_id"],
            "parent_run_id": parent,
            "revision": run["revision"],
            "owner_generation": run["owner_generation"],
        }

    def _spawn(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow = self._lock_workflow(payload["workflow_run_id"])
        if workflow["status"] in TERMINAL:
            raise ControlError("cannot spawn into a terminal workflow")
        run = self._insert_run(
            message=payload.get("message") or "",
            parent_run_id=payload.get("parent_run_id"),
            workflow_run_id=workflow["workflow_run_id"],
        )
        self.cur.execute(
            """
            UPDATE workflow_runs
            SET current_run_id = %s, revision = revision + 1
            WHERE workflow_run_id = %s
            RETURNING revision
            """,
            (run["run_id"], workflow["workflow_run_id"]),
        )
        revision = self.cur.fetchone()["revision"]
        self._objects.add("workflow_runs")
        self._event(
            "spawn",
            run_id=run["run_id"],
            workflow_run_id=workflow["workflow_run_id"],
            session_id=payload.get("session_id"),
        )
        return {
            "run_id": run["run_id"],
            "workflow_run_id": workflow["workflow_run_id"],
            "workflow_revision": revision,
            "parent_run_id": run["parent_run_id"],
            "revision": run["revision"],
            "owner_generation": run["owner_generation"],
        }

    def _handoff(self, payload: dict[str, Any]) -> dict[str, Any]:
        refs_in = list(payload.get("input_artifact_refs") or [])
        refs_out = list(payload.get("output_artifact_refs") or [])
        self._require_artifacts(refs_in + refs_out)
        workflow = self._lock_workflow(payload["workflow_run_id"])
        expected = payload.get("expected_workflow_revision")
        revision = self._bump_workflow(workflow, expected)
        self.cur.execute(
            """
            SELECT COALESCE(MAX(seq), 0) + 1 AS seq
            FROM workflow_steps
            WHERE workflow_run_id = %s
            """,
            (workflow["workflow_run_id"],),
        )
        seq = self.cur.fetchone()["seq"]
        step_id = self.new_id("step")
        self.cur.execute(
            """
            INSERT INTO workflow_steps (
                step_id, seq, workflow_run_id, run_id,
                input_artifact_refs, output_artifact_refs, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'committed')
            """,
            (
                step_id,
                seq,
                workflow["workflow_run_id"],
                payload.get("run_id"),
                refs_in,
                refs_out,
                ),
        )
        self._objects.add("workflow_steps")
        self._event(
            "handoff",
            run_id=payload.get("run_id"),
            workflow_run_id=workflow["workflow_run_id"],
            session_id=payload.get("session_id"),
            artifact_refs=refs_in + refs_out,
        )
        return {
            "step_id": step_id,
            "seq": seq,
            "workflow_revision": revision,
            "artifact_refs": refs_in + refs_out,
        }

    def _steer(self, payload: dict[str, Any]) -> dict[str, Any]:
        refs = list(payload.get("artifact_refs") or [])
        self._require_artifacts(refs)
        run = self._lock_run(payload["run_id"])
        if run["status"] in TERMINAL:
            raise ControlError("cannot steer a terminal run")
        updated = self._cas_run(
            run,
            payload.get("expected_revision"),
            status="running",
            seen_generation=payload.get("owner_generation"),
        )
        self._event(
            "steer",
            run_id=run["run_id"],
            workflow_run_id=run["workflow_run_id"],
            session_id=payload.get("session_id"),
            artifact_refs=refs,
            message=payload.get("message"),
        )
        return {
            "run_id": updated["run_id"],
            "revision": updated["revision"],
            "status": updated["status"],
            "owner_generation": updated["owner_generation"],
        }

    def _respond(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._lock_run(payload["run_id"])
        if run["status"] != "needs_input":
            raise ControlError("respond requires needs_input")
        updated = self._cas_run(
            run,
            payload.get("expected_revision"),
            status="running",
            seen_generation=payload.get("owner_generation"),
        )
        self._event(
            "respond",
            run_id=run["run_id"],
            workflow_run_id=run["workflow_run_id"],
            session_id=payload.get("session_id"),
            message=payload.get("message"),
        )
        return {
            "run_id": updated["run_id"],
            "revision": updated["revision"],
            "status": updated["status"],
        }

    def _cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("target") == "workflow":
            workflow = self._lock_workflow(payload["workflow_run_id"])
            current = workflow["current_run_id"]
            if current:
                run = self._lock_run(current)
                if run["status"] not in TERMINAL:
                    self._cas_run(run, run["revision"], status="cancelled")
                    self._event(
                        "cancel",
                        run_id=current,
                        workflow_run_id=workflow["workflow_run_id"],
                        session_id=payload.get("session_id"),
                    )
            if workflow["status"] not in TERMINAL:
                self.cur.execute(
                    """
                    UPDATE workflow_runs
                    SET status = 'cancelled', revision = revision + 1
                    WHERE workflow_run_id = %s
                    """,
                    (workflow["workflow_run_id"],),
                )
                self._objects.add("workflow_runs")
                self._event(
                    "cancel",
                    workflow_run_id=workflow["workflow_run_id"],
                    session_id=payload.get("session_id"),
                )
            return {
                "workflow_run_id": workflow["workflow_run_id"],
                "status": "cancelled",
            }
        run = self._lock_run(payload["run_id"])
        if run["status"] not in TERMINAL:
            self._cas_run(
                run,
                payload.get("expected_revision", run["revision"]),
                status="cancelled",
            )
            self._event(
                "cancel",
                run_id=run["run_id"],
                workflow_run_id=run["workflow_run_id"],
                session_id=payload.get("session_id"),
            )
        return {"run_id": run["run_id"], "status": "cancelled"}

    def _admit_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._lock_run(payload["run_id"])
        if run["status"] in TERMINAL:
            raise ControlError("cannot admit a turn on a terminal run")
        updated = self._cas_run(
            run,
            payload.get("expected_revision"),
            seen_generation=payload.get("owner_generation"),
        )
        turn_id = self.new_id("turn")
        self.cur.execute(
            """
            INSERT INTO turns (turn_id, run_id, status)
            VALUES (%s, %s, 'admitted')
            """,
            (turn_id, run["run_id"]),
        )
        self._objects.add("turns")
        self._event(
            "admit_turn",
            run_id=run["run_id"],
            workflow_run_id=payload.get("workflow_run_id") or run["workflow_run_id"],
            session_id=payload.get("session_id"),
        )
        return {
            "turn_id": turn_id,
            "run_id": run["run_id"],
            "revision": updated["revision"],
        }

    def _accept_turn_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._lock_run(payload["run_id"])
        self.cur.execute(
            "SELECT * FROM turns WHERE turn_id = %s FOR UPDATE",
            (payload["turn_id"],),
        )
        turn = self.cur.fetchone()
        if turn is None or turn["run_id"] != run["run_id"]:
            raise ControlError("turn does not belong to run")
        if turn["status"] != "admitted":
            raise ControlError("turn is not admitted")
        digest = None
        artifact = payload.get("artifact")
        if artifact is not None:
            digest = artifact["digest"]
            self.cur.execute(
                """
                INSERT INTO artifacts (digest, kind, body, path, run_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    digest,
                    artifact.get("kind") or "blob",
                    Json(artifact["body"]),
                    artifact.get("path"),
                    run["run_id"],
                ),
            )
            self._objects.add("artifacts")
        disposition = payload["receipt"]["disposition"]
        if disposition not in DISPOSITION_STATUS:
            raise ControlError(f"unknown disposition {disposition}")
        updated = self._cas_run(
            run,
            payload.get("expected_revision"),
            status=DISPOSITION_STATUS[disposition],
            seen_generation=payload.get("owner_generation"),
        )
        self.cur.execute(
            """
            UPDATE turns SET status = 'committed', receipt = %s
            WHERE turn_id = %s
            """,
            (Json(payload["receipt"]), payload["turn_id"]),
        )
        self._objects.add("turns")
        self._event(
            "accept_turn_receipt",
            run_id=run["run_id"],
            workflow_run_id=payload.get("workflow_run_id") or run["workflow_run_id"],
            session_id=payload.get("session_id"),
            digest=digest,
            artifact_refs=[digest] if digest else [],
        )
        return {
            "digest": digest,
            "path": None if artifact is None else artifact.get("path"),
            "run_id": run["run_id"],
            "revision": updated["revision"],
            "status": updated["status"],
            "turn_id": payload["turn_id"],
        }

    def _recover_owner(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._lock_run(payload["run_id"])
        if payload.get("seen_generation") != run["owner_generation"]:
            raise RevisionConflict("owner fence mismatch")
        self.cur.execute(
            "SELECT 1 FROM pg_stat_activity WHERE pid = %s",
            (run["owner_backend_pid"],),
        )
        if self.cur.fetchone() is not None:
            raise ControlError("owner still alive")
        self.cur.execute("SELECT pg_backend_pid() AS pid")
        pid = self.cur.fetchone()["pid"]
        updated = self._cas_run(
            run,
            run["revision"],
            owner_generation=run["owner_generation"] + 1,
            owner_backend_pid=pid,
        )
        self._event(
            "recover_owner",
            run_id=run["run_id"],
            workflow_run_id=run["workflow_run_id"],
            session_id=payload.get("session_id"),
        )
        return {
            "run_id": updated["run_id"],
            "owner_generation": updated["owner_generation"],
            "revision": updated["revision"],
            "owner_backend_pid": updated["owner_backend_pid"],
        }

    def _note_purge(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("scope") == "profile" and payload.get("session_id"):
            self.cur.execute(
                """
                UPDATE external_ids SET status = 'purged'
                WHERE external_id = %s
                """,
                (payload["session_id"],),
            )
            self._objects.add("external_ids")
        self._event(
            "purge_tombstone",
            run_id=payload.get("run_id"),
            workflow_run_id=payload.get("workflow_run_id"),
            session_id=payload.get("session_id"),
            scope=payload.get("scope"),
        )
        return {"events_deleted": 0, "tombstone": True}

    def _bind_macro(self, payload: dict[str, Any]) -> dict[str, Any]:
        macro_id = self.new_id("macro")
        self.cur.execute(
            """
            INSERT INTO macro_tasks (macro_id, title, revision)
            VALUES (%s, %s, 1)
            """,
            (macro_id, payload.get("title") or ""),
        )
        self._objects.add("macro_tasks")
        self._event("bind_macro", scope=macro_id)
        return {"macro_id": macro_id, "revision": 1}

    def _attach_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.cur.execute(
            """
            INSERT INTO macro_workflows (macro_id, workflow_run_id, position)
            VALUES (%s, %s, %s)
            """,
            (
                payload["macro_id"],
                payload["workflow_run_id"],
                payload["position"],
            ),
        )
        self._objects.add("macro_workflows")
        self._event(
            "attach_workflow",
            workflow_run_id=payload["workflow_run_id"],
            scope=payload["macro_id"],
        )
        return {
            "macro_id": payload["macro_id"],
            "workflow_run_id": payload["workflow_run_id"],
        }

    def _bind_alias(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id") or self.new_id("alias")
        run_id = payload.get("run_id")
        self.cur.execute(
            "SELECT * FROM session_aliases WHERE session_id = %s FOR UPDATE",
            (session_id,),
        )
        existing = self.cur.fetchone()
        if existing is None:
            self.cur.execute(
                """
                INSERT INTO session_aliases (session_id, current_run_id, revision)
                VALUES (%s, %s, 1)
                """,
                (session_id, run_id),
            )
            revision = 1
        else:
            revision = existing["revision"] + 1
            self.cur.execute(
                """
                UPDATE session_aliases
                SET current_run_id = %s, revision = %s
                WHERE session_id = %s
                """,
                (run_id, revision, session_id),
            )
        self._objects.add("session_aliases")
        if run_id:
            self.cur.execute(
                """
                INSERT INTO alias_runs (session_id, run_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (session_id, run_id),
            )
            self._objects.add("alias_runs")
        self._event("bind_alias", session_id=session_id, run_id=run_id)
        return {
            "session_id": session_id,
            "run_id": run_id,
            "revision": revision,
        }

    def _bind_external(self, payload: dict[str, Any]) -> dict[str, Any]:
        external_id = payload.get("external_id") or self.new_id("ext")
        run_id = payload.get("run_id")
        self.cur.execute(
            "SELECT * FROM external_ids WHERE external_id = %s FOR UPDATE",
            (external_id,),
        )
        existing = self.cur.fetchone()
        if existing is None:
            self.cur.execute(
                """
                INSERT INTO external_ids (external_id, run_id, profile_name, status)
                VALUES (%s, %s, 'ce', 'active')
                """,
                (external_id, run_id),
            )
        elif run_id:
            self.cur.execute(
                """
                UPDATE external_ids
                SET run_id = %s, status = 'active'
                WHERE external_id = %s
                """,
                (run_id, external_id),
            )
        if run_id:
            self.cur.execute(
                """
                INSERT INTO external_runs (external_id, run_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (external_id, run_id),
            )
            self._objects.add("external_runs")
        self._objects.add("external_ids")
        self._event("bind_external", session_id=external_id, run_id=run_id)
        return {"external_id": external_id, "run_id": run_id}

    def _manage_create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = payload.get("session_id") or self.new_id("sess")
        self.cur.execute(
            """
            INSERT INTO sessions (session_id, workflow_run_id, status)
            VALUES (%s, %s, 'running')
            """,
            (session_id, payload["workflow_run_id"]),
        )
        self._objects.add("sessions")
        self._event(
            "manage_create_session",
            session_id=session_id,
            workflow_run_id=payload["workflow_run_id"],
        )
        return {
            "session_id": session_id,
            "workflow_run_id": payload["workflow_run_id"],
        }

    def _manage_resume_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.cur.execute(
            "SELECT * FROM sessions WHERE session_id = %s FOR UPDATE",
            (payload["session_id"],),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError("unknown session")
        self._event(
            "manage_resume_session",
            session_id=payload["session_id"],
            workflow_run_id=row["workflow_run_id"],
            run_id=payload.get("run_id"),
        )
        return {
            "session_id": payload["session_id"],
            "workflow_run_id": row["workflow_run_id"],
            "run_id": payload.get("run_id"),
        }

    def _manage_stop_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.cur.execute(
            """
            UPDATE sessions SET status = 'cancelled'
            WHERE session_id = %s
            RETURNING workflow_run_id
            """,
            (payload["session_id"],),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError("unknown session")
        self._objects.add("sessions")
        cancelled = self._cancel(
            {
                "target": "workflow",
                "workflow_run_id": row["workflow_run_id"],
                "session_id": payload["session_id"],
            }
        )
        self._event(
            "manage_stop_session",
            session_id=payload["session_id"],
            workflow_run_id=row["workflow_run_id"],
        )
        return {"session_id": payload["session_id"], **cancelled}

    def _manage_cleanup(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.cur.execute(
            """
            UPDATE sessions SET status = 'purged'
            WHERE session_id = %s
            RETURNING workflow_run_id
            """,
            (payload["session_id"],),
        )
        row = self.cur.fetchone()
        if row is None:
            raise ControlError("unknown session")
        self._objects.add("sessions")
        self._event(
            "purge_tombstone",
            session_id=payload["session_id"],
            workflow_run_id=row["workflow_run_id"],
            scope="session",
        )
        return {
            "session_id": payload["session_id"],
            "events_deleted": 0,
            "tombstone": True,
        }
