"""Design 3. Session as a first-class object.

Sessions are rows. manage_create_session, manage_resume_session,
manage_stop_session, and manage_cleanup enter Control only through
agent_manage. session_id stays stable across resume while current_run_id
changes. Stopping a session uses the same transition as cancel. Handoff lives
on the session artifact chain.
"""

from __future__ import annotations

from typing import Any

from substrate import Control


class SessionObject:
    design_id = "session_object"
    title = "会话一等对象"

    def __init__(self, control: Control) -> None:
        self.control = control
        self._start_payload: dict[str, Any] | None = None
        self.session_ids: list[str] = []

    def agent_manage(self, verb: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.control.execute(verb, payload, entry="agent_manage")

    def create_session(self, *, message: str) -> dict[str, Any]:
        payload = {
            "request_id": self.control.new_id("req"),
            "message": message,
            "actor": "caller",
        }
        self.control.begin()
        try:
            run = self.control.execute("start", payload)
            session = self.agent_manage(
                "manage_create_session",
                {
                    "request_id": self.control.new_id("req"),
                    "run_id": run["run_id"],
                },
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        self._start_payload = payload
        self.session_ids.append(session["session_id"])
        return {
            "session_id": session["session_id"],
            "run_id": run["run_id"],
            "start_request_id": payload["request_id"],
        }

    def start(
        self,
        *,
        session_id: str,
        message: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        del message
        if (
            request_id is not None
            and self._start_payload is not None
            and self._start_payload["request_id"] == request_id
        ):
            result = self.control.execute("start", dict(self._start_payload))
            return {
                "session_id": session_id,
                "run_id": result["run_id"],
                "replayed": True,
            }
        raise RuntimeError("session object already started inside create_session")

    def accept_model_plan(self, *, session_id: str) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        body = {"kind": "plan", "text": "expand then contract", "run_id": run_id}
        return self.control.commit_forged_turn(
            run_id=run_id,
            prompt="write a plan",
            disposition="run_now",
            artifact_kind="plan",
            artifact_body=body,
            export_name=f"plan-{run_id}",
        )

    def steer(
        self,
        *,
        session_id: str,
        message: str,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        run = self.control.runs[run_id]
        result = self.control.execute(
            "steer",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run_id,
                "message": message,
                "artifact_refs": list(artifact_refs or []),
                "expected_revision": run["revision"],
            },
        )
        return {"session_id": session_id, "run_id": run_id, **result}

    def drive_to_needs_input(self, *, session_id: str) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        result = self.control.commit_forged_turn(
            run_id=run_id,
            prompt="ask the caller",
            disposition="needs_input",
        )
        return {"session_id": session_id, "run_id": run_id, **result}

    def respond(self, *, session_id: str, message: str) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        run = self.control.runs[run_id]
        result = self.control.execute(
            "respond",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run_id,
                "message": message,
                "expected_revision": run["revision"],
            },
        )
        return {"session_id": session_id, "run_id": run_id, **result}

    def run_citing_step(self, *, session_id: str, digest: str) -> dict[str, Any]:
        session = self.control.sessions[session_id]
        run_id = session["current_run_id"]
        self.control.execute(
            "handoff",
            {
                "request_id": self.control.new_id("req"),
                "session_id": session_id,
                "run_id": run_id,
                "artifact_refs": [digest],
                "expected_session_revision": session["revision"],
            },
        )
        self.control.commit_forged_turn(
            run_id=run_id,
            prompt="finish cited step",
            disposition="stop",
        )
        return {
            "authority": "session_artifact_chain",
            "digest": digest,
            "session_id": session_id,
            "run_id": run_id,
        }

    def resume_session(self, *, session_id: str) -> dict[str, Any]:
        session = self.control.sessions[session_id]
        old_run_id = session["current_run_id"]
        expected = session["revision"]
        self.control.begin()
        try:
            run = self.control.execute(
                "start",
                {
                    "request_id": self.control.new_id("req"),
                    "message": "resume",
                    "resume_from": old_run_id,
                    "parent_run_id": old_run_id,
                    "actor": "caller",
                },
            )
            self.agent_manage(
                "manage_resume_session",
                {
                    "request_id": self.control.new_id("req"),
                    "session_id": session_id,
                    "run_id": run["run_id"],
                    "expected_revision": expected,
                },
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {
            "session_id": session_id,
            "run_id": run["run_id"],
            "parent_run_id": old_run_id,
        }

    def get_log(self, *, session_id: str) -> dict[str, Any]:
        run_ids = {
            event.get("run_id")
            for event in self.control.events
            if event.get("session_id") == session_id and event.get("run_id")
        }
        current = self.control.sessions[session_id]["current_run_id"]
        run_ids.add(current)
        parent = self.control.runs[current].get("parent_run_id")
        if parent:
            run_ids.add(parent)
        entries = [
            event
            for event in self.control.events
            if event.get("session_id") == session_id or event.get("run_id") in run_ids
        ]
        return {
            "session_id": session_id,
            "run_id": current,
            "entries": entries,
            "artifact_chain": list(
                self.control.sessions[session_id]["artifact_chain"]
            ),
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "artifact_refs": list(self.control.sessions[session_id]["artifact_chain"]),
            "folded_on_read": False,
            "authority": "session_artifact_chain",
        }

    def list_sessions(self) -> list[str]:
        return list(self.session_ids)

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        result = self.agent_manage(
            "manage_stop_session",
            {
                "request_id": self.control.new_id("req"),
                "session_id": session_id,
            },
        )
        return {"session_id": session_id, "transition": "cancel", **result}

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        result = self.agent_manage(
            "manage_cleanup",
            {
                "request_id": self.control.new_id("req"),
                "session_id": session_id,
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "manage_cleanup",
            "kernel_verb_rejected": None,
            "kernel_cleanup_verb": False,
            "dropped_exports": dropped,
            **result,
        }

    def view(self, session_id: str) -> dict[str, Any]:
        session = self.control.sessions[session_id]
        return {"session_id": session_id, "run_id": session["current_run_id"]}

    def caller_bundle(self, session_id: str) -> None:
        del session_id
        return None

    def _run_id(self, session_id: str) -> str:
        return self.control.sessions[session_id]["current_run_id"]
