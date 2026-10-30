"""Design 4 repair. External id is a committed row in the same transaction as the run."""

from __future__ import annotations

from typing import Any

from control import EXPORTS, Control, file_digest


class UnloadableProfile:
    design_id = "unloadable_profile"
    title = "可卸载 profile"
    repair_note = (
        "external_ids 和 external_runs 在 start 或 resume 的同一事务里写入，另一条连接能 SELECT 到。"
        "cleanup 走 note_purge 并把映射标成 purged，不再把 cleanup 当成被拒绝的 kernel 动词。"
        "get_log 仍在读路径折叠，折叠来源是已提交的 external_runs。"
    )

    def __init__(self, control: Control) -> None:
        self.control = control

    def create_session(self, *, message: str) -> dict[str, Any]:
        del message
        result = self.control.execute(
            "bind_external",
            {"request_id": self.control.new_id("req")},
        )
        return {"session_id": result["external_id"], "run_id": None}

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
            bound = self.control.execute(
                "bind_external",
                {
                    "request_id": self.control.new_id("req"),
                    "external_id": session_id,
                    "run_id": run["run_id"],
                },
            )
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {"session_id": bound["external_id"], "run_id": run["run_id"]}

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
            self.control.external_run_ids(session_id)
        )
        if loaded is None or loaded["digest"] != digest:
            raise RuntimeError("profile citation missing committed artifact")
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
            "authority": "read_path_fold",
            "digest": loaded["digest"],
            "session_id": session_id,
            "run_id": run["run_id"],
            "folded_on_read": True,
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
                "bind_external",
                {
                    "request_id": self.control.new_id("req"),
                    "external_id": session_id,
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
        run_ids = self.control.external_run_ids(session_id)
        self.control.cur.execute(
            """
            SELECT event_id, kind, run_id, session_id, digest, artifact_refs
            FROM events
            WHERE run_id = ANY(%s) OR session_id = %s
            ORDER BY event_id
            """,
            (run_ids, session_id),
        )
        return {
            "session_id": session_id,
            "entries": [dict(row) for row in self.control.cur.fetchall()],
            "folded_on_read": True,
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        artifact = self.control.latest_artifact_for_runs(
            self.control.external_run_ids(session_id)
        )
        refs = [] if artifact is None else [artifact["digest"]]
        return {
            "session_id": session_id,
            "artifact_refs": refs,
            "folded_on_read": True,
            "authority": "read_path_fold",
        }

    def list_sessions(self) -> list[str]:
        self.control.cur.execute(
            """
            SELECT external_id FROM external_ids
            WHERE status = 'active'
            ORDER BY external_id
            """
        )
        return [row["external_id"] for row in self.control.cur.fetchall()]

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
                "scope": "profile",
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "profile_tombstone",
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
        first = self._macro_member("macro plan")
        second = self._macro_member("macro implement")
        body = {"kind": "plan", "text": "macro plan", "run_id": first["run_id"]}
        exported = self.control.commit_forged_turn(
            run_id=first["run_id"],
            prompt="macro plan",
            disposition="run_now",
            artifact_kind="plan",
            artifact_body=body,
            export_name=f"macro-{first['run_id']}",
            workflow_run_id=first["workflow_run_id"],
            session_id=first["external_id"],
        )
        workflow = self.control.fetch_workflow(second["workflow_run_id"])
        self.control.execute(
            "handoff",
            {
                "request_id": self.control.new_id("req"),
                "workflow_run_id": second["workflow_run_id"],
                "run_id": second["run_id"],
                "input_artifact_refs": [exported["digest"]],
                "output_artifact_refs": [],
                "expected_workflow_revision": workflow["revision"],
                "session_id": second["external_id"],
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
            "digest": exported["digest"],
            "file_matches_digest": file_digest(path) == exported["digest"],
            "second_step_inputs": list(steps[-1]["input_artifact_refs"]),
            "alias_rows": 0,
            "session_rows": 0,
            "external_rows": 2,
        }

    def _macro_member(self, message: str) -> dict[str, str]:
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
            external = self.control.execute(
                "bind_external",
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
            "external_id": external["external_id"],
        }

    def _run_id(self, session_id: str) -> str:
        current = self.control.fetch_external(session_id)["run_id"]
        if not current:
            raise RuntimeError("external id has no run")
        return current
