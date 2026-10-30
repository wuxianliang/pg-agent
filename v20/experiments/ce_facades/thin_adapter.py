"""Design 1. Thin adapter.

There is no session object. The caller's session_id is the run_id. resume
starts a new run and keeps the old id only as parent. create_session,
resume_session, and stop_session are aliases of start, start-with-resume_from,
and cancel. Cleanup is caller orchestration, not a kernel verb. Handoff is the
caller passing an artifact ref into the next start or steer.
"""

from __future__ import annotations

from typing import Any

from substrate import TERMINAL, Control


class ThinAdapter:
    design_id = "thin_adapter"
    title = "薄适配器"

    def __init__(self, control: Control) -> None:
        self.control = control
        self._start_payload: dict[str, Any] | None = None
        self.session_ids: list[str] = []
        self.caller_refs: dict[str, list[str]] = {}

    def create_session(self, *, message: str) -> dict[str, Any]:
        payload = {
            "request_id": self.control.new_id("req"),
            "message": message,
            "actor": "caller",
        }
        result = self.control.execute("start", payload)
        self._start_payload = payload
        run_id = result["run_id"]
        self.session_ids.append(run_id)
        self.caller_refs[run_id] = []
        return {
            "session_id": run_id,
            "run_id": run_id,
            "start_request_id": payload["request_id"],
            "alias_of": "start",
        }

    def start(
        self,
        *,
        session_id: str,
        message: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            request_id is not None
            and self._start_payload is not None
            and self._start_payload["request_id"] == request_id
        ):
            result = self.control.execute("start", dict(self._start_payload))
            return {
                "session_id": result["run_id"],
                "run_id": result["run_id"],
                "replayed": True,
                "alias_of": "start",
            }
        raise RuntimeError("thin adapter start is the create_session alias")

    def accept_model_plan(self, *, session_id: str) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        body = {"kind": "plan", "text": "expand then contract", "run_id": run_id}
        result = self.control.commit_forged_turn(
            run_id=run_id,
            prompt="write a plan",
            disposition="run_now",
            artifact_kind="plan",
            artifact_body=body,
            export_name=f"plan-{run_id}",
        )
        self._remember(session_id, result["digest"])
        return result

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
        self.steer(session_id=session_id, message="execute plan", artifact_refs=[digest])
        self._remember(session_id, digest)
        run_id = self._run_id(session_id)
        self.control.commit_forged_turn(
            run_id=run_id,
            prompt="finish cited step",
            disposition="stop",
        )
        return {
            "authority": "caller_explicit_ref",
            "digest": digest,
            "session_id": session_id,
            "run_id": run_id,
        }

    def resume_session(self, *, session_id: str) -> dict[str, Any]:
        refs = list(self.caller_refs.get(session_id, []))
        result = self.control.execute(
            "start",
            {
                "request_id": self.control.new_id("req"),
                "message": "resume",
                "resume_from": session_id,
                "parent_run_id": session_id,
                "artifact_refs": refs,
                "actor": "caller",
            },
        )
        new_run_id = result["run_id"]
        self.caller_refs[new_run_id] = refs
        self.session_ids.append(new_run_id)
        return {
            "session_id": new_run_id,
            "run_id": new_run_id,
            "parent_run_id": session_id,
            "alias_of": "start",
        }

    def get_log(self, *, session_id: str) -> dict[str, Any]:
        run_ids = self._ancestor_runs(session_id)
        entries = [
            event
            for event in self.control.events
            if event.get("run_id") in run_ids
        ]
        return {"session_id": session_id, "run_id": session_id, "entries": entries}

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "artifact_refs": list(self.caller_refs.get(session_id, [])),
            "folded_on_read": False,
            "authority": "caller_explicit_ref",
        }

    def list_sessions(self) -> list[str]:
        return list(self.session_ids)

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        run = self.control.runs[session_id]
        result = self.control.execute(
            "cancel",
            {
                "request_id": self.control.new_id("req"),
                "run_id": session_id,
                "expected_revision": run["revision"],
            },
        )
        return {"session_id": session_id, "alias_of": "cancel", **result}

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        for run_id in list(self.session_ids):
            run = self.control.runs[run_id]
            if run["status"] not in TERMINAL:
                self.control.execute(
                    "cancel",
                    {
                        "request_id": self.control.new_id("req"),
                        "run_id": run_id,
                        "expected_revision": run["revision"],
                    },
                )
        self.control.execute(
            "note_purge",
            {
                "request_id": self.control.new_id("req"),
                "run_id": session_id,
                "scope": "caller",
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "caller_loop",
            "kernel_verb_rejected": None,
            "kernel_cleanup_verb": False,
            "dropped_exports": dropped,
        }

    def view(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "run_id": session_id}

    def caller_bundle(self, session_id: str) -> list[str]:
        return list(self.caller_refs.get(session_id, []))

    def _run_id(self, session_id: str) -> str:
        return session_id

    def _remember(self, session_id: str, digest: str | None) -> None:
        if not digest:
            return
        refs = self.caller_refs.setdefault(session_id, [])
        if digest not in refs:
            refs.append(digest)

    def _ancestor_runs(self, run_id: str) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        while run_id and run_id not in seen:
            seen.add(run_id)
            ids.append(run_id)
            run_id = self.control.runs[run_id].get("parent_run_id")
        return ids
