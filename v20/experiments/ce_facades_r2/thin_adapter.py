"""Design 1 repair. Stable alias row, citation loaded from committed artifacts."""

from __future__ import annotations

from typing import Any

from control import EXPORTS, Control, file_digest


class ThinAdapter:
    design_id = "thin_adapter"
    title = "薄适配器"
    repair_note = (
        "调用方 session_id 是已提交的 session_aliases 行，resume 在同一事务里换 run 并改指向。"
        "下一步的 digest 从 artifacts 表读出，不留在调用方内存。"
        "宏观任务另建 workflow，不把别名行变成 workflow 容器。"
    )

    def __init__(self, control: Control) -> None:
        self.control = control

    def create_session(self, *, message: str) -> dict[str, Any]:
        del message
        result = self.control.execute(
            "bind_alias",
            {"request_id": self.control.new_id("req")},
        )
        return {"session_id": result["session_id"], "run_id": None}

    def start(self, *, session_id: str, message: str) -> dict[str, Any]:
        self.control.begin()
        try:
            run = self.control.execute(
                "start",
                {
                    "request_id": self.control.new_id("req"),
                    "message": message,
                    "session_id": session_id,
                },
            )
            self.control.execute(
                "bind_alias",
                {
                    "request_id": self.control.new_id("req"),
                    "session_id": session_id,
                    "run_id": run["run_id"],
                },
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {"session_id": session_id, "run_id": run["run_id"]}

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
        loaded = self.control.latest_artifact_for_runs(
            self.control.alias_run_ids(session_id)
        )
        if loaded is None or loaded["digest"] != digest:
            raise RuntimeError("citation was not loaded from committed artifacts")
        run = self.control.fetch_run(self._run_id(session_id))
        self.control.execute(
            "steer",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run["run_id"],
                "message": "cite",
                "artifact_refs": [loaded["digest"]],
                "expected_revision": run["revision"],
                "owner_generation": run["owner_generation"],
                "session_id": session_id,
            },
        )
        self.control.commit_forged_turn(
            run_id=run["run_id"],
            prompt="finish cited step",
            disposition="stop",
            session_id=session_id,
        )
        return {
            "authority": "committed_artifact_row",
            "digest": loaded["digest"],
            "session_id": session_id,
            "run_id": run["run_id"],
            "folded_on_read": False,
        }

    def resume_session(self, *, session_id: str) -> dict[str, Any]:
        parent = self._run_id(session_id)
        self.control.begin()
        try:
            run = self.control.execute(
                "start",
                {
                    "request_id": self.control.new_id("req"),
                    "message": "resume",
                    "parent_run_id": parent,
                    "session_id": session_id,
                },
            )
            self.control.execute(
                "bind_alias",
                {
                    "request_id": self.control.new_id("req"),
                    "session_id": session_id,
                    "run_id": run["run_id"],
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
            "parent_run_id": parent,
        }

    def get_log(self, *, session_id: str) -> dict[str, Any]:
        run_ids = self.control.alias_run_ids(session_id)
        self.control.cur.execute(
            """
            SELECT event_id, kind, run_id, session_id, digest, artifact_refs
            FROM events
            WHERE session_id = %s OR run_id = ANY(%s)
            ORDER BY event_id
            """,
            (session_id, run_ids),
        )
        return {
            "session_id": session_id,
            "entries": [dict(row) for row in self.control.cur.fetchall()],
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        artifact = self.control.latest_artifact_for_runs(
            self.control.alias_run_ids(session_id)
        )
        refs = [] if artifact is None else [artifact["digest"]]
        return {
            "session_id": session_id,
            "artifact_refs": refs,
            "folded_on_read": False,
            "authority": "committed_artifact_row",
        }

    def list_sessions(self) -> list[str]:
        self.control.cur.execute(
            "SELECT session_id FROM session_aliases ORDER BY session_id"
        )
        return [row["session_id"] for row in self.control.cur.fetchall()]

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        run = self.control.fetch_run(self._run_id(session_id))
        result = self.control.execute(
            "cancel",
            {
                "request_id": self.control.new_id("req"),
                "run_id": run["run_id"],
                "expected_revision": run["revision"],
                "session_id": session_id,
            },
        )
        return {"session_id": session_id, **result}

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        run = self.control.fetch_run(self._run_id(session_id))
        if run["status"] not in {"stopped", "cancelled", "failed"}:
            self.stop_session(session_id=session_id)
        self.control.execute(
            "note_purge",
            {
                "request_id": self.control.new_id("req"),
                "run_id": self._run_id(session_id),
                "session_id": session_id,
                "scope": "alias",
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "alias_tombstone",
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
        first = self._macro_workflow("macro plan")
        second = self._macro_workflow("macro implement")
        body = {"kind": "plan", "text": "macro plan", "run_id": first["run_id"]}
        exported = self.control.commit_forged_turn(
            run_id=first["run_id"],
            prompt="macro plan",
            disposition="run_now",
            artifact_kind="plan",
            artifact_body=body,
            export_name=f"macro-{first['run_id']}",
            workflow_run_id=first["workflow_run_id"],
            session_id=first["alias_id"],
        )
        loaded = self.control.latest_artifact_for_runs([first["run_id"]])
        workflow = self.control.fetch_workflow(second["workflow_run_id"])
        self.control.execute(
            "handoff",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": second["workflow_run_id"],
                "run_id": second["run_id"],
                "input_artifact_refs": [loaded["digest"]],
                "output_artifact_refs": [],
                "expected_workflow_revision": workflow["revision"],
                "session_id": second["alias_id"],
            },
        )
        for position, member in enumerate((first, second), start=1):
            self.control.execute(
                "attach_workflow",
                {
                    "request_id": self.control.new_id("req"),
                    "macro_id": macro["macro_id"],
                    "workflow_run_id": member["workflow_run_id"],
                    "position": position,
                },
            )
        path = EXPORTS.parent / exported["path"]
        steps = self.control.fetch_steps(second["workflow_run_id"])
        return {
            "macro_id": macro["macro_id"],
            "workflow_ids": [first["workflow_run_id"], second["workflow_run_id"]],
            "digest": loaded["digest"],
            "file_matches_digest": file_digest(path) == loaded["digest"],
            "second_step_inputs": list(steps[-1]["input_artifact_refs"]),
            "alias_rows": 2,
            "session_rows": 0,
            "external_rows": 0,
        }

    def _macro_workflow(self, message: str) -> dict[str, str]:
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
            run = self.control.execute(
                "spawn",
                {
                    "request_id": self.control.new_id("req"),
                    "workflow_run_id": workflow["workflow_run_id"],
                    "message": message,
                },
            )
            alias = self.control.execute(
                "bind_alias",
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
        return {
            "workflow_run_id": workflow["workflow_run_id"],
            "run_id": run["run_id"],
            "alias_id": alias["session_id"],
        }

    def _run_id(self, session_id: str) -> str:
        current = self.control.fetch_alias(session_id)["current_run_id"]
        if not current:
            raise RuntimeError("alias has no run")
        return current
