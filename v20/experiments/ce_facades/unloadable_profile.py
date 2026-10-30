"""Design 4. Unloadable profile.

The kernel only knows runs. The caller's session_id is an external id. The
mapping row is written in the same transaction as start or retire. resume
changes run_id and leaves the external session_id in place. Writes stay thin.
get_log and extract_handoff fold events into a session shape on the read path.
A CE operation with no kernel verb is rejected.
"""

from __future__ import annotations

from typing import Any

from substrate import TERMINAL, Control, UnknownVerb


class UnloadableProfile:
    design_id = "unloadable_profile"
    title = "可卸载 profile"

    def __init__(self, control: Control) -> None:
        self.control = control
        self.loaded = True
        self.bindings: dict[str, dict[str, Any]] = {}
        self._start_payload: dict[str, Any] | None = None
        self._external_for_replay: str | None = None

    def unload(self) -> None:
        self.loaded = False

    def create_session(self, *, message: str) -> dict[str, Any]:
        self._require_loaded()
        external_id = self.control.new_id("ext")
        payload = {
            "request_id": self.control.new_id("req"),
            "message": message,
            "actor": "caller",
        }
        self.control.begin()
        try:
            run = self.control.execute("start", payload)

            def bind(run_id: str = run["run_id"]) -> None:
                self.bindings[external_id] = {
                    "run_id": run_id,
                    "previous_run_id": None,
                    "retired": False,
                }

            self.control.participate("bind", bind)
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        self._start_payload = payload
        self._external_for_replay = external_id
        return {
            "session_id": external_id,
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
        self._require_loaded()
        if (
            request_id is not None
            and self._start_payload is not None
            and self._start_payload["request_id"] == request_id
            and session_id == self._external_for_replay
        ):
            result = self.control.execute("start", dict(self._start_payload))
            return {
                "session_id": session_id,
                "run_id": result["run_id"],
                "replayed": True,
            }
        raise RuntimeError("profile start is bound with create_session")

    def accept_model_plan(self, *, session_id: str) -> dict[str, Any]:
        self._require_loaded()
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
        self._require_loaded()
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
        self._require_loaded()
        run_id = self._run_id(session_id)
        result = self.control.commit_forged_turn(
            run_id=run_id,
            prompt="ask the caller",
            disposition="needs_input",
        )
        return {"session_id": session_id, "run_id": run_id, **result}

    def respond(self, *, session_id: str, message: str) -> dict[str, Any]:
        self._require_loaded()
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
        self.steer(
            session_id=session_id, message="execute plan", artifact_refs=[digest]
        )
        run_id = self._run_id(session_id)
        self.control.commit_forged_turn(
            run_id=run_id,
            prompt="finish cited step",
            disposition="stop",
        )
        return {
            "authority": "read_path_fold",
            "digest": digest,
            "session_id": session_id,
            "run_id": run_id,
        }

    def resume_session(self, *, session_id: str) -> dict[str, Any]:
        self._require_loaded()
        old_run_id = self.bindings[session_id]["run_id"]
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

            def rebind(run_id: str = run["run_id"], previous: str = old_run_id) -> None:
                self.bindings[session_id] = {
                    "run_id": run_id,
                    "previous_run_id": previous,
                    "retired": False,
                }

            self.control.participate("rebind", rebind)
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
        self._require_loaded()
        run_id = self._run_id(session_id)
        ancestors = set(self._ancestor_runs(run_id))
        entries = [
            event
            for event in self.control.events
            if event.get("run_id") in ancestors
        ]
        return {
            "session_id": session_id,
            "run_id": run_id,
            "entries": entries,
            "folded_on_read": True,
        }

    def extract_handoff(self, *, session_id: str) -> dict[str, Any]:
        self._require_loaded()
        return {
            "session_id": session_id,
            "artifact_refs": self._folded_refs(session_id),
            "folded_on_read": True,
            "authority": "read_path_fold",
        }

    def list_sessions(self) -> list[str]:
        self._require_loaded()
        return list(self.bindings)

    def stop_session(self, *, session_id: str) -> dict[str, Any]:
        self._require_loaded()
        run_id = self._run_id(session_id)
        run = self.control.runs[run_id]
        self.control.begin()
        try:
            result = self.control.execute(
                "cancel",
                {
                    "request_id": self.control.new_id("req"),
                    "run_id": run_id,
                    "expected_revision": run["revision"],
                },
            )

            def retire() -> None:
                self.bindings[session_id]["retired"] = True

            self.control.participate("retire", retire)
            self.control.commit()
        except Exception:
            if self.control.in_transaction:
                self.control.rollback()
            raise
        return {"session_id": session_id, "run_id": run_id, **result}

    def cleanup_sessions(self, *, session_id: str) -> dict[str, Any]:
        self._require_loaded()
        rejected: str | None = None
        try:
            self.control.execute(
                "cleanup",
                {"request_id": self.control.new_id("req"), "session_id": session_id},
            )
        except UnknownVerb as exc:
            rejected = exc.verb
        run_id = self.bindings[session_id]["run_id"]
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
                "run_id": run_id,
                "scope": "profile",
            },
        )
        dropped = self.control.drop_export_contents()
        return {
            "tombstone_via": "rejected_cleanup_then_profile_note_purge",
            "kernel_verb_rejected": rejected,
            "kernel_cleanup_verb": False,
            "dropped_exports": dropped,
        }

    def view(self, session_id: str) -> dict[str, Any]:
        self._require_loaded()
        return {"session_id": session_id, "run_id": self._run_id(session_id)}

    def caller_bundle(self, session_id: str) -> None:
        del session_id
        return None

    def _require_loaded(self) -> None:
        if not self.loaded:
            raise RuntimeError("profile unloaded")

    def _run_id(self, session_id: str) -> str:
        return self.bindings[session_id]["run_id"]

    def _ancestor_runs(self, run_id: str) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        while run_id and run_id not in seen:
            seen.add(run_id)
            ids.append(run_id)
            parent = self.control.runs[run_id].get("parent_run_id")
            run_id = parent
        return ids

    def _folded_refs(self, session_id: str) -> list[str]:
        refs: list[str] = []
        for run_id in self._ancestor_runs(self._run_id(session_id)):
            for event in self.control.events:
                if event.get("run_id") != run_id:
                    continue
                for ref in event.get("artifact_refs") or []:
                    if ref and ref not in refs:
                        refs.append(ref)
        return refs
