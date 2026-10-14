"""Single-threaded host loop. It calls Control; it does not insert rows itself.

drive does not call decide. decide is for a caller reading a committed snapshot.
A FenceRejected accept or publish ends the drive as failed and does not publish again.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping
from uuid import uuid4
import threading

from v20.alpha.control import Control, ControlError
from v20.alpha.tools import InTransaction, ToolFailed, run_tool
from v20.alpha.worker import (
    TurnReceipt,
    WorkerRequest,
    compute_input_digest,
    validate_receipt,
)

ENTRY = frozenset({"start", "steer", "respond", "claim_resume"})


def _obj(value: Any) -> Any:
    if isinstance(value, str):
        import json
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class Host:
    """One drive at a time in this process. A second caller gets Rejected."""

    _gate = threading.Lock()

    def __init__(self, control: Control, worker: Callable[..., TurnReceipt]) -> None:
        self.control = control
        self.worker = worker

    def drive(
        self,
        verb: str,
        actor: str,
        payload: Mapping[str, Any],
        *,
        handle_timeout: float = 2.0,
    ) -> dict[str, Any]:
        if not Host._gate.acquire(blocking=False):
            raise ControlError("Rejected")
        try:
            return self._drive(verb, actor, dict(payload), handle_timeout)
        finally:
            Host._gate.release()

    def _drive(
        self,
        verb: str,
        actor: str,
        payload: dict[str, Any],
        handle_timeout: float,
    ) -> dict[str, Any]:
        if verb not in ENTRY:
            raise ControlError("Rejected")
        admitted = self.control.execute(verb, actor, payload)
        resolved = self.control.resolve_handle(admitted["request_id"], timeout=handle_timeout)
        if resolved["state"] == "pending":
            return self._out("wait", self._poll(admitted["run_id"]))
        self.provider_handle = resolved["handle"] if resolved["state"] == "present" else None
        opened = False
        run_id = admitted["run_id"]
        for _ in range(24):
            snap = self._poll(run_id)
            if snap["pending_tools"]:
                end = self._tools(actor, snap)
                if end is not None:
                    return end
                continue
            if snap["pending_turns"]:
                end = self._turn(actor, snap)
                if end is not None:
                    return end
                continue
            if snap["continue_needed"]:
                self._admit(actor, snap, "host_continue")
                continue
            driving = snap["driving"]
            if driving and driving["status"] == "pending" and not opened:
                self._admit(actor, snap, self._initial_kind(snap, driving))
                opened = True
                continue
            return self._out("wait", snap)
        raise ControlError("Rejected", "drive did not finish")

    def _poll(self, run_id: str) -> dict[str, Any]:
        return self.control.execute("poll", "alpha", {"run_id": run_id})

    def _out(self, disposition: str, snap: Mapping[str, Any]) -> dict[str, Any]:
        driving = snap.get("driving") or {}
        request_id = driving.get("request_id") if isinstance(driving, Mapping) else None
        return {
            "disposition": disposition,
            "request_id": request_id,
            "verb": "drive",
            "status": snap.get("status"),
            "run_id": snap.get("run_id"),
            "session_id": snap.get("session_id"),
            "revision": snap.get("revision"),
        }

    def _initial_kind(self, snap: Mapping[str, Any], driving: Mapping[str, Any]) -> str:
        verb = driving["verb"]
        if verb == "respond":
            return "parent_response"
        if verb in {"claim_resume", "steer"}:
            return "initial"
        if snap.get("parent_session_id"):
            return "parent_instruction"
        return "initial"

    def _admit(self, actor: str, snap: Mapping[str, Any], kind: str) -> None:
        driving = snap["driving"]
        payload: dict[str, Any] = {
            "request_id": str(uuid4()),
            "run_id": snap["run_id"],
            "epoch_id": driving["epoch_id"],
            "owner_generation": snap["owner_generation"],
            "input_kind": kind,
            "instruction": driving["input_message"],
        }
        if snap.get("transcript_turn_id"):
            payload["transcript_turn_id"] = snap["transcript_turn_id"]
        self.control.execute("admit_turn", actor, payload)

    def _tools(self, actor: str, snap: Mapping[str, Any]) -> dict[str, Any] | None:
        for tool in snap["pending_tools"]:
            try:
                output: Any = run_tool(tool["tool_name"], tool["arguments"])
                status = "completed"
            except InTransaction:
                raise
            except ToolFailed as exc:
                output = {"error": str(exc)}
                status = "failed"
            try:
                self.control.execute("accept_tool_result", actor, {
                    "request_id": tool["request_id"],
                    "status": status,
                    "output": output,
                })
            except ControlError as exc:
                if exc.code == "FenceRejected":
                    return self._out("failed", self._poll(snap["run_id"]))
                raise
        return None

    def _turn(self, actor: str, snap: Mapping[str, Any]) -> dict[str, Any] | None:
        turn = snap["pending_turns"][0]
        initial = _obj(turn.get("receipt")) or {}
        kind = initial["input_kind"]
        driving = snap["driving"]
        if kind == "parent_response":
            instruction = None
            response: Any = driving["input_message"]
            continuation = False
            results: list[Any] = []
        elif kind == "host_continue":
            instruction = driving["input_message"]
            response = None
            continuation = True
            results = list(snap["tool_results"])
        else:
            instruction = initial.get("instruction")
            response = None
            continuation = False
            results = []
        material = {
            "base_revision": snap["revision"],
            "continuation": continuation,
            "input_kind": kind,
            "instruction": instruction,
            "provider_handle": self.provider_handle,
            "response": response,
            "run_id": snap["run_id"],
            "tool_results": results,
            "turn_id": turn["turn_id"],
        }
        request = WorkerRequest(
            run_id=snap["run_id"],
            turn_id=turn["turn_id"],
            base_revision=snap["revision"],
            input_kind=kind,
            input_digest=compute_input_digest(material),
            instruction=instruction,
            response=response,
            continuation=continuation,
            provider_handle=self.provider_handle,
            tool_results=results,
        )
        driving_id = driving["request_id"]
        receipt = self.worker(request)
        validate_receipt(receipt, request)
        body = receipt.as_dict()
        body["request_id"] = turn["request_id"]
        try:
            self.control.execute("accept_turn_receipt", actor, {
                "request_id": turn["request_id"],
                "receipt": body,
            })
        except ControlError as exc:
            if exc.code == "FenceRejected":
                return self._out("failed", self._poll(snap["run_id"]))
            raise
        return self._branch(actor, turn, receipt, driving_id)

    def _branch(
        self,
        actor: str,
        turn: Mapping[str, Any],
        receipt: TurnReceipt,
        driving_id: str,
    ) -> dict[str, Any] | None:
        snap = self._poll(turn["run_id"])
        driving = snap.get("driving") or {}
        if driving.get("request_id") != driving_id:
            return self._stale_drive(actor, snap, driving_id)
        calls = list(receipt.tool_calls)
        if calls:
            if snap["completed_tool_count"]:
                return self._final(actor, snap, "failed", receipt, "repeated tool round", driving_id)
            if snap["driving"]["snapshot_seq"] is None:
                ended = self._progress(actor, snap, bare=False, driving_id=driving_id)
                if ended is not None:
                    return ended
                snap = self._poll(turn["run_id"])
                if (snap.get("driving") or {}).get("request_id") != driving_id:
                    return self._stale_drive(actor, snap, driving_id)
            for call in calls:
                self.control.execute("admit_tool", actor, {
                    "request_id": str(uuid4()),
                    "run_id": snap["run_id"],
                    "epoch_id": turn["epoch_id"],
                    "turn_id": turn["turn_id"],
                    "tool_name": call["name"],
                    "arguments": call["arguments"],
                    "owner_generation": snap["owner_generation"],
                })
            return None
        if receipt.outcome == "progress":
            if snap["bare_progress"]:
                return self._final(
                    actor, snap, "failed", receipt, "repeated progress without tools", driving_id,
                )
            ended = self._progress(actor, snap, bare=True, driving_id=driving_id)
            if ended is not None:
                return ended
            snap = self._poll(turn["run_id"])
            if (snap.get("driving") or {}).get("request_id") != driving_id:
                return self._stale_drive(actor, snap, driving_id)
            self._admit(actor, snap, receipt.input_kind)
            return None
        if receipt.outcome == "needs_input":
            return self._final(actor, snap, "waiting_for_input", receipt, None, driving_id)
        if receipt.outcome == "completed":
            return self._final(actor, snap, "completed", receipt, None, driving_id)
        if receipt.outcome == "failed":
            return self._final(actor, snap, "failed", receipt, "worker failed", driving_id)
        raise ControlError("Rejected")

    def _stale_drive(self, actor: str, snap: Mapping[str, Any], driving_id: str) -> dict[str, Any]:
        """Publish the captured request so a steered-away attempt fences, then stop."""
        try:
            self.control.execute("publish_snapshot", actor, {
                "request_id": driving_id,
                "mode": "progress",
                "snapshot_seq": 1,
                "preview": "",
            })
        except ControlError as exc:
            if exc.code != "FenceRejected":
                raise
        return self._out("failed", self._poll(snap["run_id"]))

    def _progress(
        self,
        actor: str,
        snap: Mapping[str, Any],
        *,
        bare: bool,
        driving_id: str,
    ) -> dict[str, Any] | None:
        driving = snap["driving"]
        seq = 1 if driving["snapshot_seq"] is None else int(driving["snapshot_seq"]) + 1
        try:
            self.control.execute("publish_snapshot", actor, {
                "request_id": driving_id,
                "mode": "progress",
                "snapshot_seq": seq,
                "preview": (driving["input_message"] or "")[:200],
                "bare_progress": bare,
            })
        except ControlError as exc:
            if exc.code == "FenceRejected":
                return self._out("failed", self._poll(snap["run_id"]))
            raise
        return None

    def _final(
        self,
        actor: str,
        snap: Mapping[str, Any],
        outcome: str,
        receipt: TurnReceipt,
        reason: str | None,
        driving_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": driving_id,
            "mode": "final",
            "outcome": outcome,
            "preview": outcome,
            "result": receipt.result,
            "no_handle": True,
        }
        if outcome == "waiting_for_input":
            payload["interaction"] = receipt.input_request
        if outcome == "failed":
            payload["failure_reason"] = reason or "failed"
        try:
            self.control.execute("publish_snapshot", actor, payload)
        except ControlError as exc:
            if exc.code == "FenceRejected":
                return self._out("failed", self._poll(snap["run_id"]))
            raise
        word = {"waiting_for_input": "needs_input", "completed": "stop", "failed": "failed"}[outcome]
        return self._out(word, self._poll(snap["run_id"]))
