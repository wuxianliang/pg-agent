"""Design 2. The caller session id is the workflow run id."""

from __future__ import annotations

from typing import Any

from control import EXPORTS, TERMINAL, Control, file_digest


class WorkflowContainer:
    design_id = "workflow_container"
    title = "会话即 workflow 容器"
    repair_note = "身份模型保持不变。这一轮只补上 Postgres、等待、并发、恢复、宏观任务和真实导出。"

    def __init__(self, control: Control) -> None:
        self.control = control

    def create_session(self, *, message: str) -> dict[str, Any]:
        result = self.control.execute(
            "start",
            {
                "request_id": self.control.new_id("req"),
                "message": message,
                "target": "workflow",
            },
        )
        return {"session_id": result["workflow_run_id"], "run_id": None}

    def start(self, *, session_id: str, message: str) -> dict[str, Any]:
        result = self.control.execute(
            "spawn",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": session_id,
                "message": message,
                "session_id": session_id,
            },
        )
        return {"session_id": session_id, "run_id": result["run_id"]}

    def export_plan(self, *, session_id: str) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        body = {"kind": "plan", "text": "expand then contract", "run_id": run_id}
        result = self.control.commit_forged_turn(
            run_id=run_id,
            prompt="write a plan",
            disposition="run_now",
            artifact_kind="plan",
            artifact_body=body,
            export_name=f"plan-{run_id}",
            workflow_run_id=session_id,
            session_id=session_id,
        )
        return {
            "digest": result["digest"],
            "path": result["path"],
            "run_id": run_id,
            "session_id": session_id,
        }

    def steer(self, *, session_id: str, message: str) -> dict[str, Any]:
        workflow = self.control.fetch_workflow(session_id)
        if workflow["status"] in TERMINAL:
            raise RuntimeError("workflow container is terminal")
        run = self.control.fetch_run(workflow["current_run_id"])
        if run["status"] in TERMINAL:
            return self._steer_spawn(session_id, message, run["run_id"])
        result = self.control.execute(
            "steer",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run["run_id"],
                "message": message,
                "expected_revision": run["revision"],
                "owner_generation": run["owner_generation"],
                "session_id": session_id,
            },
        )
        return {"session_id": session_id, "run_id": run["run_id"], **result}

    def poll(self, *, session_id: str) -> dict[str, Any]:
        run = self.control.fetch_run(self._run_id(session_id))
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "revision": run["revision"],
            "owner_generation": run["owner_generation"],
        }

    def drive_to_needs_input(self, *, session_id: str) -> dict[str, Any]:
        run_id = self._run_id(session_id)
        result = self.control.commit_forged_turn(
            run_id=run_id,
            prompt="ask the caller",
            disposition="needs_input",
            workflow_run_id=session_id,
            session_id=session_id,
        )
        return {"session_id": session_id, "run_id": run_id, **result}

    def respond(self, *, session_id: str, message: str) -> dict[str, Any]:
        run = self.control.fetch_run(self._run_id(session_id))
        result = self.control.execute(
            "respond",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run["run_id"],
                "message": message,
                "expected_revision": run["revision"],
                "owner_generation": run["owner_generation"],
                "session_id": session_id,
            },
        )
        return {"session_id": session_id, "run_id": run["run_id"], **result}

    def cite(self, *, session_id: str, digest: str) -> dict[str, Any]:
        workflow = self.control.fetch_workflow(session_id)
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
                "session_id": session_id,
            },
        )
        self.control.commit_forged_turn(
            run_id=run_id,
            prompt="finish cited step",
            disposition="stop",
            workflow_run_id=session_id,
            session_id=session_id,
        )
        return {
            "authority": "workflow_step_io",
            "digest": digest,
            "session_id": session_id,
            "run_id": run_id,
            "folded_on_read": False,
        }

    def resume_session(self, *, session_id: str) -> dict[str, Any]:
        steered = self._steer_spawn(
            session_id,
            "resume",
            self._run_id(session_id),
            refs=self._step_refs(session_id),
        )
        return steered

    def get_log(self, *, session_id: str) -> dict[str, Any]:
        self.control.cur.execute(
            """
            SELECT event_id, kind, run_id, workflow_run_id, session_id, digest
            FROM events
            WHERE workflow_run_id = %s
               OR run_id IN (
                    SELECT run_id FROM runs WHERE workflow_run_id = %s
               )
            ORDER BY event_id
            """,
            (session_id, session_id),
        )
        entries = [dict(row) for row in self.control.cur.fetchall()]
        return {
            "session_id": session_id,
            "entries": entries,
            "steps": self.control.fetch_steps(session_id),
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        steps = self.control.fetch_steps(session_id)
        latest = steps[-1]
        refs = list(latest["input_artifact_refs"]) + list(latest["output_artifact_refs"])
        return {
            "session_id": session_id,
            "artifact_refs": refs,
            "folded_on_read": False,
            "authority": "workflow_step_io",
            "step_id": latest["step_id"],
            "seq": latest["seq"],
        }

    def list_sessions(self) -> list[str]:
        self.control.cur.execute(
            "SELECT workflow_run_id FROM workflow_runs ORDER BY workflow_run_id"
        )
        return [row["workflow_run_id"] for row in self.control.cur.fetchall()]

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        result = self.control.execute(
            "cancel",
            {
                "request_id": self.control.new_id("req"),
                "target": "workflow",
                "workflow_run_id": session_id,
                "session_id": session_id,
            },
        )
        return {"session_id": session_id, **result}

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        workflow = self.control.fetch_workflow(session_id)
        for run_id in self.control.workflow_run_ids(session_id):
            run = self.control.fetch_run(run_id)
            if run["status"] not in TERMINAL:
                self.control.execute(
                    "cancel",
                    {
                        "request_id": self.control.new_id("req"),
                        "run_id": run_id,
                        "expected_revision": run["revision"],
                        "session_id": session_id,
                    },
                )
        workflow = self.control.fetch_workflow(session_id)
        if workflow["status"] not in TERMINAL:
            self.stop_session(session_id=session_id)
        self.control.execute(
            "note_purge",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": session_id,
                "session_id": session_id,
                "scope": "workflow",
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "workflow_container_tombstone",
            "kernel_verb_rejected": None,
            "dropped_exports": dropped,
        }

    def view(self, session_id: str) -> dict[str, Any]:
        run = self.control.fetch_run(self._run_id(session_id))
        return {
            "session_id": session_id,
            "run_id": run["run_id"],
            "revision": run["revision"],
            "owner_generation": run["owner_generation"],
            "status": run["status"],
        }

    def build_macro(self) -> dict[str, Any]:
        macro = self.control.execute(
            "bind_macro",
            {"request_id": self.control.new_id("req"), "title": "migration"},
        )
        first = self.create_session(message="macro plan")
        self.start(session_id=first["session_id"], message="plan the macro")
        exported = self.export_plan(session_id=first["session_id"])
        second = self.create_session(message="macro implement")
        self.start(session_id=second["session_id"], message="implement the macro")
        self.cite(session_id=second["session_id"], digest=exported["digest"])
        for position, session_id in enumerate(
            (first["session_id"], second["session_id"]), start=1
        ):
            self.control.execute(
                "attach_workflow",
                {
                    "request_id": self.control.new_id("req"),
                    "macro_id": macro["macro_id"],
                    "workflow_run_id": session_id,
                    "position": position,
                },
            )
        path = EXPORTS.parent / exported["path"]
        steps = self.control.fetch_steps(second["session_id"])
        return {
            "macro_id": macro["macro_id"],
            "workflow_ids": [first["session_id"], second["session_id"]],
            "digest": exported["digest"],
            "file_matches_digest": file_digest(path) == exported["digest"],
            "second_step_inputs": list(steps[-1]["input_artifact_refs"]),
            "alias_rows": 0,
            "session_rows": 0,
            "external_rows": 0,
        }

    def _run_id(self, session_id: str) -> str:
        return self.control.fetch_workflow(session_id)["current_run_id"]

    def _step_refs(self, session_id: str) -> list[str]:
        refs: list[str] = []
        for step in self.control.fetch_steps(session_id):
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
        parent_run_id: str,
        refs: list[str] | None = None,
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
                    "session_id": session_id,
                },
            )
            self.control.execute(
                "handoff",
                {
                    "request_id": self.control.new_id("req"),
                    "workflow_run_id": session_id,
                    "run_id": spawned["run_id"],
                    "input_artifact_refs": list(refs or []),
                    "output_artifact_refs": [],
                    "expected_workflow_revision": spawned["workflow_revision"],
                    "session_id": session_id,
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
        }
