"""Design 3 repair. Stable session id points at one workflow; steps own the chain."""

from __future__ import annotations

from typing import Any

from control import EXPORTS, TERMINAL, Control, file_digest


class SessionObject:
    design_id = "session_object"
    title = "会话一等对象"
    repair_note = (
        "sessions 行只保存稳定 session_id 和 workflow_run_id，不再自带 revision 或 artifact 链。"
        "步骤序号和输入输出在 workflow_steps。日志按 events.session_id 索引读取。"
    )

    def __init__(self, control: Control) -> None:
        self.control = control

    def create_session(self, *, message: str) -> dict[str, Any]:
        self.control.begin()
        try:
            workflow = self.control.execute(
                "start",
                {
                    "request_id": self.control.new_id("req"),
                    "target": "workflow",
                    "message": message,
                },
            )
            session = self.control.execute(
                "manage_create_session",
                {
                    "request_id": self.control.new_id("req"),
                    "workflow_run_id": workflow["workflow_run_id"],
                },
                entry="agent_manage",
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {
            "session_id": session["session_id"],
            "run_id": None,
            "workflow_run_id": workflow["workflow_run_id"],
        }

    def start(self, *, session_id: str, message: str) -> dict[str, Any]:
        workflow_run_id = self._workflow_id(session_id)
        result = self.control.execute(
            "spawn",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": workflow_run_id,
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
            workflow_run_id=self._workflow_id(session_id),
            session_id=session_id,
        )
        return {
            "digest": result["digest"],
            "path": result["path"],
            "run_id": run_id,
            "session_id": session_id,
        }

    def steer(self, *, session_id: str, message: str) -> dict[str, Any]:
        run = self.control.fetch_run(self._run_id(session_id))
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
            workflow_run_id=self._workflow_id(session_id),
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
        workflow_run_id = self._workflow_id(session_id)
        workflow = self.control.fetch_workflow(workflow_run_id)
        run_id = workflow["current_run_id"]
        self.control.execute(
            "handoff",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": workflow_run_id,
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
            workflow_run_id=workflow_run_id,
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
        workflow_run_id = self._workflow_id(session_id)
        parent = self._run_id(session_id)
        self.control.begin()
        try:
            spawned = self.control.execute(
                "spawn",
                {
                    "request_id": self.control.new_id("req"),
                    "workflow_run_id": workflow_run_id,
                    "message": "resume",
                    "parent_run_id": parent,
                    "session_id": session_id,
                },
            )
            self.control.execute(
                "manage_resume_session",
                {
                    "request_id": self.control.new_id("req"),
                    "session_id": session_id,
                    "run_id": spawned["run_id"],
                },
                entry="agent_manage",
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {
            "session_id": session_id,
            "run_id": spawned["run_id"],
            "parent_run_id": parent,
        }

    def get_log(self, *, session_id: str) -> dict[str, Any]:
        self.control.cur.execute(
            """
            SELECT event_id, kind, run_id, session_id, workflow_run_id, digest
            FROM events
            WHERE session_id = %s
            ORDER BY event_id
            """,
            (session_id,),
        )
        return {
            "session_id": session_id,
            "entries": [dict(row) for row in self.control.cur.fetchall()],
            "steps": self.control.fetch_steps(self._workflow_id(session_id)),
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        steps = self.control.fetch_steps(self._workflow_id(session_id))
        latest = steps[-1]
        refs = list(latest["input_artifact_refs"]) + list(latest["output_artifact_refs"])
        return {
            "session_id": session_id,
            "artifact_refs": refs,
            "folded_on_read": False,
            "authority": "workflow_step_io",
            "seq": latest["seq"],
        }

    def list_sessions(self) -> list[str]:
        self.control.cur.execute("SELECT session_id FROM sessions ORDER BY session_id")
        return [row["session_id"] for row in self.control.cur.fetchall()]

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        result = self.control.execute(
            "manage_stop_session",
            {"request_id": self.control.new_id("req"), "session_id": session_id},
            entry="agent_manage",
        )
        return result

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        session = self.control.fetch_session(session_id)
        if session["status"] not in TERMINAL and session["status"] != "purged":
            workflow = self.control.fetch_workflow(session["workflow_run_id"])
            if workflow["status"] not in TERMINAL:
                self.stop_session(session_id=session_id)
        result = self.control.execute(
            "manage_cleanup",
            {"request_id": self.control.new_id("req"), "session_id": session_id},
            entry="agent_manage",
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "manage_cleanup",
            "kernel_verb_rejected": None,
            "dropped_exports": dropped,
            **result,
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
        for position, created in enumerate((first, second), start=1):
            self.control.execute(
                "attach_workflow",
                {
                    "request_id": self.control.new_id("req"),
                    "macro_id": macro["macro_id"],
                    "workflow_run_id": created["workflow_run_id"],
                    "position": position,
                },
            )
        path = EXPORTS.parent / exported["path"]
        steps = self.control.fetch_steps(second["workflow_run_id"])
        return {
            "macro_id": macro["macro_id"],
            "workflow_ids": [first["workflow_run_id"], second["workflow_run_id"]],
            "digest": exported["digest"],
            "file_matches_digest": file_digest(path) == exported["digest"],
            "second_step_inputs": list(steps[-1]["input_artifact_refs"]),
            "alias_rows": 0,
            "session_rows": 2,
            "external_rows": 0,
        }

    def _workflow_id(self, session_id: str) -> str:
        return self.control.fetch_session(session_id)["workflow_run_id"]

    def _run_id(self, session_id: str) -> str:
        return self.control.fetch_workflow(self._workflow_id(session_id))["current_run_id"]
