"""Design 2. Session as a workflow container.

session_id is the workflow_run_id. start spawns a child run inside that
container. When the child is terminal and the container is still alive, steer
spawns a new run and writes the workflow step's artifact refs in the same
transaction. Handoff lives on the committed step input/output refs.
"""

from __future__ import annotations

from typing import Any

from substrate import TERMINAL, Control


class WorkflowContainer:
    design_id = "workflow_container"
    title = "会话即 workflow 容器"

    def __init__(self, control: Control) -> None:
        self.control = control
        self.session_ids: list[str] = []

    def create_session(self, *, message: str) -> dict[str, Any]:
        result = self.control.execute(
            "start",
            {
                "request_id": self.control.new_id("req"),
                "message": message,
                "target": "workflow",
                "actor": "caller",
            },
        )
        session_id = result["workflow_run_id"]
        self.session_ids.append(session_id)
        return {"session_id": session_id, "run_id": None}

    def start(
        self,
        *,
        session_id: str,
        message: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        del request_id
        result = self.control.execute(
            "spawn",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": session_id,
                "message": message,
            },
        )
        return {"session_id": session_id, "run_id": result["run_id"]}

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
        return result

    def steer(
        self,
        *,
        session_id: str,
        message: str,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        workflow = self.control.workflow_runs[session_id]
        if workflow["status"] in TERMINAL:
            raise RuntimeError("workflow container is terminal")
        run_id = workflow["current_run_id"]
        run = self.control.runs[run_id]
        refs = list(artifact_refs or [])
        if run["status"] in TERMINAL:
            return self._steer_spawn(session_id, message, refs, run_id)
        result = self.control.execute(
            "steer",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run_id,
                "message": message,
                "artifact_refs": refs,
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
        workflow = self.control.workflow_runs[session_id]
        run_id = workflow["current_run_id"]
        self.control.execute(
            "handoff",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": session_id,
                "run_id": run_id,
                "input_artifact_refs": [digest],
                "output_artifact_refs": [],
                "expected_workflow_revision": workflow["revision"],
            },
        )
        self.control.commit_forged_turn(
            run_id=run_id,
            prompt="finish cited step",
            disposition="stop",
        )
        return {
            "authority": "workflow_step_io",
            "digest": digest,
            "session_id": session_id,
            "run_id": run_id,
        }

    def resume_session(self, *, session_id: str) -> dict[str, Any]:
        refs = self._step_refs(session_id)
        steered = self.steer(
            session_id=session_id, message="resume", artifact_refs=refs
        )
        return {
            "session_id": session_id,
            "run_id": steered["run_id"],
            "parent_run_id": steered.get("parent_run_id"),
        }

    def get_log(self, *, session_id: str) -> dict[str, Any]:
        workflow = self.control.workflow_runs[session_id]
        child_ids = set(workflow["child_run_ids"])
        entries = [
            event
            for event in self.control.events
            if event.get("workflow_run_id") == session_id
            or event.get("run_id") in child_ids
        ]
        steps = [
            step
            for step in self.control.workflow_steps.values()
            if step["workflow_run_id"] == session_id
        ]
        steps.sort(key=lambda step: step["seq"])
        return {
            "session_id": session_id,
            "run_id": workflow["current_run_id"],
            "entries": entries,
            "steps": steps,
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        steps = [
            step
            for step in self.control.workflow_steps.values()
            if step["workflow_run_id"] == session_id
        ]
        steps.sort(key=lambda step: step["seq"])
        latest = steps[-1]
        refs = list(latest["input_artifact_refs"]) + list(latest["output_artifact_refs"])
        return {
            "session_id": session_id,
            "artifact_refs": refs,
            "folded_on_read": False,
            "authority": "workflow_step_io",
            "step_id": latest["step_id"],
        }

    def list_sessions(self) -> list[str]:
        return list(self.session_ids)

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        result = self.control.execute(
            "cancel",
            {
                "request_id": self.control.new_id("req"),
                "target": "workflow",
                "workflow_run_id": session_id,
            },
        )
        return {"session_id": session_id, **result}

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        workflow = self.control.workflow_runs[session_id]
        for run_id in list(workflow["child_run_ids"]):
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
        if workflow["status"] not in TERMINAL:
            self.control.execute(
                "cancel",
                {
                    "request_id": self.control.new_id("req"),
                    "target": "workflow",
                    "workflow_run_id": session_id,
                },
            )
        self.control.execute(
            "note_purge",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": session_id,
                "scope": "workflow",
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "workflow_container_tombstone",
            "kernel_verb_rejected": None,
            "kernel_cleanup_verb": False,
            "dropped_exports": dropped,
        }

    def view(self, session_id: str) -> dict[str, Any]:
        workflow = self.control.workflow_runs[session_id]
        return {"session_id": session_id, "run_id": workflow["current_run_id"]}

    def caller_bundle(self, session_id: str) -> None:
        del session_id
        return None

    def _run_id(self, session_id: str) -> str:
        return self.control.workflow_runs[session_id]["current_run_id"]

    def _step_refs(self, session_id: str) -> list[str]:
        refs: list[str] = []
        steps = [
            step
            for step in self.control.workflow_steps.values()
            if step["workflow_run_id"] == session_id
        ]
        steps.sort(key=lambda step: step["seq"])
        for step in steps:
            for ref in list(step["input_artifact_refs"]) + list(
                step["output_artifact_refs"]
            ):
                if ref not in refs:
                    refs.append(ref)
        return refs

    def _steer_spawn(
        self,
        session_id: str,
        message: str,
        refs: list[str],
        parent_run_id: str,
    ) -> dict[str, Any]:
        self.control.begin()
        try:
            spawned = self.control.execute(
                "spawn",
                {
                    "request_id": self.control.new_id("req"),
                    "workflow_run_id": session_id,
                    "message": message,
                    "parent_run_id": parent_run_id,
                },
            )
            self.control.execute(
                "handoff",
                {
                    "request_id": self.control.new_id("req"),
                    "workflow_run_id": session_id,
                    "run_id": spawned["run_id"],
                    "input_artifact_refs": list(refs),
                    "output_artifact_refs": [],
                    "expected_workflow_revision": spawned["workflow_revision"],
                },
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {
            "session_id": session_id,
            "run_id": spawned["run_id"],
            "parent_run_id": parent_run_id,
            "revision": spawned["revision"],
        }
