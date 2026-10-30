"""In-process Control substrate for the CE facade experiment.

One writer: Control.execute. Events are append-only. Idempotent receipts and
revision CAS live here. Model calls and export file IO fail while a
transaction is open. Nothing in this module touches a database or the network.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable


PUBLIC_VERBS = frozenset(
    {"start", "poll", "wait", "steer", "respond", "cancel", "spawn", "handoff"}
)
INTERNAL_VERBS = frozenset(
    {
        "admit_turn",
        "accept_turn_receipt",
        "admit_tool",
        "accept_tool_result",
        "recover_owner",
        "note_purge",
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

TERMINAL = frozenset({"stopped", "cancelled", "failed"})

DISPOSITION_STATUS = {
    "run_now": "running",
    "wait": "waiting",
    "needs_input": "needs_input",
    "stop": "stopped",
    "failed": "failed",
}


class ControlError(Exception):
    pass


class UnknownVerb(ControlError):
    def __init__(self, verb: str) -> None:
        super().__init__(f"unknown verb {verb}")
        self.verb = verb


class EntryError(ControlError):
    def __init__(self, verb: str) -> None:
        super().__init__(f"{verb} only enters through agent_manage")
        self.verb = verb


class RevisionConflict(ControlError):
    pass


class IdempotencyConflict(ControlError):
    pass


class TransactionError(ControlError):
    pass


class CitationError(ControlError):
    def __init__(self, digest: str) -> None:
        super().__init__(f"digest is not a committed artifact: {digest}")
        self.digest = digest


def canonical(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_of(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def payload_digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "request_id"}
    return digest_of(body)


class _Tx:
    def __init__(self, tx_id: str) -> None:
        self.tx_id = tx_id
        self.verbs: list[str] = []
        self.objects: set[str] = set()
        self.profile_writes: list[str] = []
        self.side: list[Callable[[], None]] = []
        self.runs: dict[str, dict[str, Any]] = {}
        self.workflows: dict[str, dict[str, Any]] = {}
        self.steps: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.ops: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []


class Control:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.operations: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.workflow_runs: dict[str, dict[str, Any]] = {}
        self.workflow_steps: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.tool_invocations: dict[str, dict[str, Any]] = {}
        self.exports: dict[str, bytes] = {}
        self.tx_log: list[dict[str, Any]] = []
        self._seq = 0
        self._tx: _Tx | None = None

    @property
    def in_transaction(self) -> bool:
        return self._tx is not None

    def new_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq}"

    def begin(self) -> str:
        if self._tx is not None:
            raise TransactionError("transaction already open")
        self._tx = _Tx(self.new_id("tx"))
        return self._tx.tx_id

    def commit(self) -> dict[str, Any]:
        tx = self._require_tx()
        self.runs.update(tx.runs)
        self.workflow_runs.update(tx.workflows)
        self.workflow_steps.update(tx.steps)
        self.sessions.update(tx.sessions)
        self.artifacts.update(tx.artifacts)
        self.turns.update(tx.turns)
        self.tool_invocations.update(tx.tools)
        self.operations.update(tx.ops)
        for event in tx.events:
            event["seq"] = len(self.events) + 1
            self.events.append(event)
        for fn in tx.side:
            fn()
        record = {
            "tx_id": tx.tx_id,
            "verbs": list(tx.verbs),
            "objects": sorted(tx.objects),
            "profile_writes": list(tx.profile_writes),
            "committed": True,
        }
        self.tx_log.append(record)
        self._tx = None
        return record

    def rollback(self) -> None:
        if self._tx is None:
            raise TransactionError("no transaction open")
        self._tx = None

    def participate(self, name: str, fn: Callable[[], None]) -> None:
        tx = self._require_tx()
        tx.profile_writes.append(name)
        tx.side.append(fn)

    def execute(
        self, verb: str, payload: dict[str, Any], *, entry: str = "public"
    ) -> dict[str, Any]:
        if verb not in ALLOWED_VERBS:
            raise UnknownVerb(verb)
        if verb in MANAGE_VERBS and entry != "agent_manage":
            raise EntryError(verb)
        if "request_id" not in payload:
            raise ControlError("request_id required")
        digest = payload_digest(payload)
        existing = self._find_op(payload["request_id"])
        if existing is not None:
            if existing["payload_digest"] != digest:
                raise IdempotencyConflict(payload["request_id"])
            return copy.deepcopy(existing["result"])
        owned = self._tx is None
        if owned:
            self.begin()
        try:
            result = self._dispatch(verb, payload)
            stored = copy.deepcopy(result)
            assert self._tx is not None
            self._tx.ops[payload["request_id"]] = {
                "request_id": payload["request_id"],
                "verb": verb,
                "payload_digest": digest,
                "result": copy.deepcopy(stored),
            }
            self._tx.objects.add("operations")
            self._tx.verbs.append(verb)
            if owned:
                self.commit()
            return stored
        except Exception:
            if owned and self._tx is not None:
                self.rollback()
            raise

    def call_model(self, prompt: str) -> str:
        if self._tx is not None:
            raise TransactionError("model call inside a transaction")
        return f"fake-completion:{prompt[:80]}"

    def write_export(self, name: str, content: bytes) -> None:
        if self._tx is not None:
            raise TransactionError("file write inside a transaction")
        self.exports[name] = bytes(content)

    def read_export(self, name: str) -> bytes:
        if self._tx is not None:
            raise TransactionError("file read inside a transaction")
        return self.exports.get(name, b"")

    def drop_export_contents(self) -> int:
        if self._tx is not None:
            raise TransactionError("file write inside a transaction")
        dropped = 0
        for key in list(self.exports):
            if self.exports[key] != b"":
                dropped += 1
            self.exports[key] = b""
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
    ) -> dict[str, Any]:
        if self._tx is not None:
            raise TransactionError("forged turn inside a transaction")
        admitted = self.execute(
            "admit_turn",
            {
                "request_id": self.new_id("req"),
                "run_id": run_id,
                "expected_revision": self.runs[run_id]["revision"],
            },
        )
        text = self.call_model(prompt)
        if export_name is not None:
            self.write_export(export_name, text.encode("utf-8"))
        payload: dict[str, Any] = {
            "request_id": self.new_id("req"),
            "run_id": run_id,
            "turn_id": admitted["turn_id"],
            "expected_revision": self.runs[run_id]["revision"],
            "receipt": {"text": text, "disposition": disposition},
        }
        if artifact_body is not None:
            payload["artifact"] = {
                "kind": artifact_kind or "blob",
                "body": artifact_body,
            }
        return self.execute("accept_turn_receipt", payload)

    def _require_tx(self) -> _Tx:
        if self._tx is None:
            raise TransactionError("no transaction open")
        return self._tx

    def _find_op(self, request_id: str) -> dict[str, Any] | None:
        if self._tx is not None and request_id in self._tx.ops:
            return self._tx.ops[request_id]
        return self.operations.get(request_id)

    def _dispatch(self, verb: str, payload: dict[str, Any]) -> dict[str, Any]:
        handler = {
            "start": self._start,
            "poll": self._poll,
            "wait": self._wait,
            "steer": self._steer,
            "respond": self._respond,
            "cancel": self._cancel,
            "spawn": self._spawn,
            "handoff": self._handoff,
            "admit_turn": self._admit_turn,
            "accept_turn_receipt": self._accept_turn_receipt,
            "admit_tool": self._admit_tool,
            "accept_tool_result": self._accept_tool_result,
            "recover_owner": self._recover_owner,
            "note_purge": self._note_purge,
            "manage_create_session": self._manage_create_session,
            "manage_resume_session": self._manage_resume_session,
            "manage_stop_session": self._manage_stop_session,
            "manage_cleanup": self._manage_cleanup,
        }[verb]
        return handler(payload)

    def _event(self, kind: str, **fields: Any) -> dict[str, Any]:
        tx = self._require_tx()
        event = {
            "event_id": self.new_id("evt"),
            "seq": None,
            "kind": kind,
            "artifact_refs": list(fields.pop("artifact_refs", []) or []),
            "digest": fields.pop("digest", None),
            "scope": fields.pop("scope", None),
            "run_id": fields.pop("run_id", None),
            "workflow_run_id": fields.pop("workflow_run_id", None),
            "session_id": fields.pop("session_id", None),
            "tx_id": tx.tx_id,
        }
        event.update(fields)
        tx.events.append(event)
        tx.objects.add("events")
        return event

    def _require_committed(self, refs: list[str]) -> None:
        for ref in refs:
            if ref not in self.artifacts:
                raise CitationError(ref)

    def _cas(self, row: dict[str, Any], expected: int | None) -> None:
        if expected is None or row["revision"] != expected:
            raise RevisionConflict(
                f"expected revision {expected}, found {row['revision']}"
            )

    def _edit_run(self, run_id: str) -> dict[str, Any]:
        tx = self._require_tx()
        staged = tx.runs.get(run_id)
        if staged is not None:
            tx.objects.add("runs")
            return staged
        current = self.runs.get(run_id)
        if current is None:
            raise ControlError(f"unknown run {run_id}")
        copied = copy.deepcopy(current)
        tx.runs[run_id] = copied
        tx.objects.add("runs")
        return copied

    def _read_run(self, run_id: str) -> dict[str, Any]:
        if self._tx is not None and run_id in self._tx.runs:
            return self._tx.runs[run_id]
        current = self.runs.get(run_id)
        if current is None:
            raise ControlError(f"unknown run {run_id}")
        return current

    def _edit_workflow(self, workflow_run_id: str) -> dict[str, Any]:
        tx = self._require_tx()
        staged = tx.workflows.get(workflow_run_id)
        if staged is not None:
            tx.objects.add("workflow_runs")
            return staged
        current = self.workflow_runs.get(workflow_run_id)
        if current is None:
            raise ControlError(f"unknown workflow {workflow_run_id}")
        copied = copy.deepcopy(current)
        tx.workflows[workflow_run_id] = copied
        tx.objects.add("workflow_runs")
        return copied

    def _edit_session(self, session_id: str) -> dict[str, Any]:
        tx = self._require_tx()
        staged = tx.sessions.get(session_id)
        if staged is not None:
            tx.objects.add("sessions")
            return staged
        current = self.sessions.get(session_id)
        if current is None:
            raise ControlError(f"unknown session {session_id}")
        copied = copy.deepcopy(current)
        tx.sessions[session_id] = copied
        tx.objects.add("sessions")
        return copied

    def _edit_turn(self, turn_id: str) -> dict[str, Any]:
        tx = self._require_tx()
        staged = tx.turns.get(turn_id)
        if staged is not None:
            tx.objects.add("turns")
            return staged
        current = self.turns.get(turn_id)
        if current is None:
            raise ControlError(f"unknown turn {turn_id}")
        copied = copy.deepcopy(current)
        tx.turns[turn_id] = copied
        tx.objects.add("turns")
        return copied

    def _new_run(
        self,
        *,
        message: str,
        parent_run_id: str | None,
        resume_from: str | None = None,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        tx = self._require_tx()
        run_id = self.new_id("run")
        run = {
            "run_id": run_id,
            "status": "running",
            "revision": 1,
            "parent_run_id": parent_run_id,
            "resume_from": resume_from,
            "workflow_run_id": workflow_run_id,
            "message": message,
            "owner_generation": 1,
        }
        tx.runs[run_id] = run
        tx.objects.add("runs")
        return run

    # stop_session and cancel share this transition.
    def _transition_cancel(self, run: dict[str, Any]) -> bool:
        if run["status"] in TERMINAL:
            return False
        run["status"] = "cancelled"
        run["revision"] += 1
        return True

    def _start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("target") == "workflow":
            workflow_run_id = self.new_id("wf")
            workflow = {
                "workflow_run_id": workflow_run_id,
                "status": "running",
                "revision": 1,
                "message": payload.get("message") or "",
                "current_run_id": None,
                "child_run_ids": [],
                "step_ids": [],
            }
            tx = self._require_tx()
            tx.workflows[workflow_run_id] = workflow
            tx.objects.add("workflow_runs")
            self._event("start", workflow_run_id=workflow_run_id)
            return {
                "workflow_run_id": workflow_run_id,
                "run_id": None,
                "revision": 1,
            }
        refs = list(payload.get("artifact_refs") or [])
        self._require_committed(refs)
        parent = payload.get("parent_run_id") or payload.get("resume_from")
        run = self._new_run(
            message=payload.get("message") or "",
            parent_run_id=parent,
            resume_from=payload.get("resume_from"),
        )
        self._event("start", run_id=run["run_id"], artifact_refs=refs)
        return {
            "run_id": run["run_id"],
            "parent_run_id": parent,
            "revision": run["revision"],
            "session_id": run["run_id"],
        }

    def _poll(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._read_run(payload["run_id"])
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "revision": run["revision"],
        }

    def _wait(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._edit_run(payload["run_id"])
        if run["status"] in TERMINAL:
            raise ControlError("cannot wait on a terminal run")
        self._cas(run, payload.get("expected_revision"))
        run["status"] = "waiting"
        run["revision"] += 1
        self._event("wait", run_id=run["run_id"])
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "revision": run["revision"],
        }

    def _steer(self, payload: dict[str, Any]) -> dict[str, Any]:
        refs = list(payload.get("artifact_refs") or [])
        self._require_committed(refs)
        run = self._edit_run(payload["run_id"])
        if run["status"] in TERMINAL:
            raise ControlError("cannot steer a terminal run")
        self._cas(run, payload.get("expected_revision"))
        run["status"] = "running"
        run["revision"] += 1
        self._event(
            "steer",
            run_id=run["run_id"],
            artifact_refs=refs,
            message=payload.get("message"),
        )
        return {
            "run_id": run["run_id"],
            "revision": run["revision"],
            "status": run["status"],
        }

    def _respond(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._edit_run(payload["run_id"])
        if run["status"] != "needs_input":
            raise ControlError("respond requires needs_input")
        self._cas(run, payload.get("expected_revision"))
        run["status"] = "running"
        run["revision"] += 1
        self._event(
            "respond", run_id=run["run_id"], message=payload.get("message")
        )
        return {
            "run_id": run["run_id"],
            "revision": run["revision"],
            "status": run["status"],
        }

    def _cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("target") == "workflow":
            workflow = self._edit_workflow(payload["workflow_run_id"])
            current = workflow.get("current_run_id")
            if current:
                run = self._edit_run(current)
                if self._transition_cancel(run):
                    self._event(
                        "cancel",
                        run_id=current,
                        workflow_run_id=workflow["workflow_run_id"],
                    )
            if workflow["status"] not in TERMINAL:
                workflow["status"] = "cancelled"
                workflow["revision"] += 1
                self._event(
                    "cancel", workflow_run_id=workflow["workflow_run_id"]
                )
            return {
                "workflow_run_id": workflow["workflow_run_id"],
                "status": workflow["status"],
            }
        run = self._edit_run(payload["run_id"])
        if run["status"] not in TERMINAL:
            self._cas(run, payload.get("expected_revision"))
            self._transition_cancel(run)
            self._event("cancel", run_id=run["run_id"])
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "revision": run["revision"],
        }

    def _spawn(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow = self._edit_workflow(payload["workflow_run_id"])
        if workflow["status"] in TERMINAL:
            raise ControlError("cannot spawn into a terminal workflow")
        run = self._new_run(
            message=payload.get("message") or "",
            parent_run_id=payload.get("parent_run_id"),
            workflow_run_id=workflow["workflow_run_id"],
        )
        workflow["current_run_id"] = run["run_id"]
        workflow["child_run_ids"].append(run["run_id"])
        workflow["revision"] += 1
        self._event(
            "spawn",
            run_id=run["run_id"],
            workflow_run_id=workflow["workflow_run_id"],
        )
        return {
            "run_id": run["run_id"],
            "workflow_run_id": workflow["workflow_run_id"],
            "workflow_revision": workflow["revision"],
            "parent_run_id": run["parent_run_id"],
            "revision": run["revision"],
        }

    def _handoff(self, payload: dict[str, Any]) -> dict[str, Any]:
        refs_in = list(payload.get("input_artifact_refs") or [])
        refs_out = list(payload.get("output_artifact_refs") or [])
        extra = list(payload.get("artifact_refs") or [])
        cited = refs_in + extra
        self._require_committed(cited + refs_out)
        step_id = None
        if payload.get("workflow_run_id"):
            workflow = self._edit_workflow(payload["workflow_run_id"])
            expected = payload.get("expected_workflow_revision")
            if expected is None or workflow["revision"] != expected:
                raise RevisionConflict(
                    f"expected workflow revision {expected}, found {workflow['revision']}"
                )
            workflow["revision"] += 1
            tx = self._require_tx()
            step_id = self.new_id("step")
            step = {
                "step_id": step_id,
                "seq": len(self.workflow_steps) + len(tx.steps) + 1,
                "workflow_run_id": workflow["workflow_run_id"],
                "run_id": payload.get("run_id"),
                "input_artifact_refs": list(refs_in or cited),
                "output_artifact_refs": list(refs_out),
                "status": "committed",
            }
            tx.steps[step_id] = step
            tx.objects.add("workflow_steps")
            workflow["step_ids"].append(step_id)
        if payload.get("session_id"):
            session = self._edit_session(payload["session_id"])
            expected_session = payload.get("expected_session_revision")
            if expected_session is None or session["revision"] != expected_session:
                raise RevisionConflict(
                    f"expected session revision {expected_session}, found {session['revision']}"
                )
            for ref in cited:
                if ref not in session["artifact_chain"]:
                    session["artifact_chain"].append(ref)
            session["revision"] += 1
        self._event(
            "handoff",
            run_id=payload.get("run_id"),
            workflow_run_id=payload.get("workflow_run_id"),
            session_id=payload.get("session_id"),
            artifact_refs=cited + refs_out,
        )
        return {
            "step_id": step_id,
            "run_id": payload.get("run_id"),
            "artifact_refs": cited + refs_out,
        }

    def _admit_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._edit_run(payload["run_id"])
        if run["status"] in TERMINAL:
            raise ControlError("cannot admit a turn on a terminal run")
        self._cas(run, payload.get("expected_revision"))
        run["revision"] += 1
        turn_id = self.new_id("turn")
        turn = {"turn_id": turn_id, "run_id": run["run_id"], "status": "admitted"}
        tx = self._require_tx()
        tx.turns[turn_id] = turn
        tx.objects.add("turns")
        self._event("admit_turn", run_id=run["run_id"])
        return {
            "turn_id": turn_id,
            "run_id": run["run_id"],
            "revision": run["revision"],
        }

    def _accept_turn_receipt(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._edit_run(payload["run_id"])
        turn = self._edit_turn(payload["turn_id"])
        if turn["run_id"] != run["run_id"]:
            raise ControlError("turn does not belong to run")
        if turn["status"] != "admitted":
            raise ControlError("turn is not admitted")
        digest = None
        artifact = payload.get("artifact")
        if artifact is not None:
            digest = digest_of(artifact["body"])
            tx = self._require_tx()
            tx.artifacts[digest] = {
                "digest": digest,
                "kind": artifact.get("kind") or "blob",
                "body": artifact["body"],
                "run_id": run["run_id"],
            }
            tx.objects.add("artifacts")
        if run["status"] == "cancelled":
            turn["status"] = "discarded"
            self._event(
                "late_result_discarded",
                run_id=run["run_id"],
                digest=digest,
                artifact_refs=[digest] if digest else [],
            )
            return {
                "discarded": True,
                "digest": digest,
                "run_id": run["run_id"],
                "revision": run["revision"],
                "turn_id": turn["turn_id"],
            }
        self._cas(run, payload.get("expected_revision"))
        disposition = payload["receipt"]["disposition"]
        if disposition not in DISPOSITION_STATUS:
            raise ControlError(f"unknown disposition {disposition}")
        run["status"] = DISPOSITION_STATUS[disposition]
        run["revision"] += 1
        turn["status"] = "committed"
        turn["receipt"] = payload["receipt"]
        self._event(
            "accept_turn_receipt",
            run_id=run["run_id"],
            digest=digest,
            artifact_refs=[digest] if digest else [],
        )
        return {
            "discarded": False,
            "digest": digest,
            "run_id": run["run_id"],
            "revision": run["revision"],
            "status": run["status"],
            "turn_id": turn["turn_id"],
        }

    def _admit_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._edit_run(payload["run_id"])
        if run["status"] in TERMINAL:
            raise ControlError("cannot admit a tool on a terminal run")
        self._cas(run, payload.get("expected_revision"))
        run["revision"] += 1
        invocation_id = self.new_id("tool")
        invocation = {
            "invocation_id": invocation_id,
            "run_id": run["run_id"],
            "status": "admitted",
            "tool_name": payload.get("tool_name"),
        }
        tx = self._require_tx()
        tx.tools[invocation_id] = invocation
        tx.objects.add("tool_invocations")
        self._event("admit_tool", run_id=run["run_id"])
        return {
            "invocation_id": invocation_id,
            "run_id": run["run_id"],
            "revision": run["revision"],
        }

    def _accept_tool_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        refs = list(payload.get("artifact_refs") or [])
        self._require_committed(refs)
        run = self._edit_run(payload["run_id"])
        tx = self._require_tx()
        invocation_id = payload["invocation_id"]
        if invocation_id in tx.tools:
            invocation = tx.tools[invocation_id]
        else:
            current = self.tool_invocations.get(invocation_id)
            if current is None:
                raise ControlError(f"unknown tool invocation {invocation_id}")
            invocation = copy.deepcopy(current)
            tx.tools[invocation_id] = invocation
        tx.objects.add("tool_invocations")
        if invocation["status"] != "admitted":
            raise ControlError("tool invocation is not admitted")
        if run["status"] == "cancelled":
            invocation["status"] = "discarded"
            self._event(
                "late_result_discarded", run_id=run["run_id"], scope="tool"
            )
            return {"discarded": True, "run_id": run["run_id"]}
        self._cas(run, payload.get("expected_revision"))
        run["revision"] += 1
        invocation["status"] = "committed"
        invocation["result_digest"] = payload.get("result_digest")
        self._event(
            "accept_tool_result",
            run_id=run["run_id"],
            artifact_refs=refs,
            digest=payload.get("result_digest"),
        )
        return {
            "discarded": False,
            "run_id": run["run_id"],
            "revision": run["revision"],
        }

    def _recover_owner(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._edit_run(payload["run_id"])
        if payload.get("seen_generation") != run["owner_generation"]:
            raise RevisionConflict("owner fence mismatch")
        run["owner_generation"] += 1
        run["revision"] += 1
        self._event("recover_owner", run_id=run["run_id"])
        return {
            "run_id": run["run_id"],
            "owner_generation": run["owner_generation"],
            "revision": run["revision"],
        }

    def _note_purge(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._event(
            "purge_tombstone",
            run_id=payload.get("run_id"),
            workflow_run_id=payload.get("workflow_run_id"),
            session_id=payload.get("session_id"),
            scope=payload.get("scope"),
        )
        return {"events_deleted": 0, "tombstone": True, "scope": payload.get("scope")}

    def _manage_create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = self.new_id("sess")
        session = {
            "session_id": session_id,
            "status": "running",
            "current_run_id": payload.get("run_id"),
            "artifact_chain": [],
            "revision": 1,
        }
        tx = self._require_tx()
        tx.sessions[session_id] = session
        tx.objects.add("sessions")
        self._event(
            "manage_create_session",
            session_id=session_id,
            run_id=payload.get("run_id"),
        )
        return {
            "session_id": session_id,
            "run_id": payload.get("run_id"),
            "revision": 1,
        }

    def _manage_resume_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._edit_session(payload["session_id"])
        self._cas(session, payload.get("expected_revision"))
        session["current_run_id"] = payload["run_id"]
        session["status"] = "running"
        session["revision"] += 1
        self._event(
            "manage_resume_session",
            session_id=session["session_id"],
            run_id=payload["run_id"],
        )
        return {
            "session_id": session["session_id"],
            "run_id": payload["run_id"],
            "revision": session["revision"],
        }

    def _manage_stop_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._edit_session(payload["session_id"])
        run_id = session.get("current_run_id")
        if run_id:
            run = self._edit_run(run_id)
            if self._transition_cancel(run):
                self._event(
                    "cancel", run_id=run_id, session_id=session["session_id"]
                )
        if session["status"] not in TERMINAL:
            session["status"] = "cancelled"
            session["revision"] += 1
        self._event(
            "manage_stop_session",
            session_id=session["session_id"],
            run_id=run_id,
        )
        return {
            "session_id": session["session_id"],
            "run_id": run_id,
            "status": session["status"],
            "transition": "cancel",
        }

    def _manage_cleanup(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._edit_session(payload["session_id"])
        run_id = session.get("current_run_id")
        if run_id:
            run = self._edit_run(run_id)
            if self._transition_cancel(run):
                self._event(
                    "cancel", run_id=run_id, session_id=session["session_id"]
                )
        self._event(
            "purge_tombstone",
            session_id=session["session_id"],
            run_id=run_id,
            scope="session",
        )
        return {
            "session_id": session["session_id"],
            "events_deleted": 0,
            "tombstone": True,
        }
