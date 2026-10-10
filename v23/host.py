"""One process-local driver per (database, Run), using only Control.execute.

Local Events are wake hints, never Run truth. Parking always clears the hint,
then polls before waiting, and wakes/timeout always lead to a fresh poll.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import threading
from typing import Any, Mapping
from uuid import uuid4

from v23.control import Control, HostActor, ControlError, WorkerError
from v23.disposition import canonical_uuid, decide
from v23.worker import WorkerContractError


class HostBusyError(RuntimeError):
    pass


@dataclass
class _Slot:
    active: bool = False
    event: threading.Event = field(default_factory=threading.Event)
    accepted: bool | None = None


_registry: dict[tuple[Any, str], _Slot] = {}
_registry_lock = threading.RLock()


def _interval(value: Any, *, idle: bool) -> float:
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not (0 < value <= 1 if idle else 0 <= value <= 3600)):
        raise ValueError("invalid idle_interval" if idle else "invalid timeout_seconds")
    return float(value)


class Host:
    def __init__(self, control: Control, *, execution_accepted: bool = True,
                 timeout_seconds: float = 0.05, idle_interval: float = 0.05):
        if type(execution_accepted) is not bool:
            raise ValueError("execution_accepted must be bool")
        self.control = control
        self._execution_accepted = execution_accepted
        self.timeout_seconds = _interval(timeout_seconds, idle=False)
        self.idle_interval = _interval(idle_interval, idle=True)

    @property
    def execution_accepted(self) -> bool:
        with _registry_lock:
            return self._execution_accepted

    @execution_accepted.setter
    def execution_accepted(self, value: bool) -> None:
        if type(value) is not bool:
            raise ValueError("execution_accepted must be bool")
        with _registry_lock:
            self._execution_accepted = value
            for (identity, _), slot in _registry.items():
                if identity == self.control.db_identity:
                    slot.event.set()

    def _slot(self, run_id: str) -> _Slot:
        canonical_uuid(run_id)
        with _registry_lock:
            return _registry.setdefault((self.control.db_identity, run_id), _Slot())

    def set_execution_accepted(self, run_id: str, value: bool) -> None:
        """A shared, non-durable per-Run admission parameter and wake hint."""
        if type(value) is not bool:
            raise ValueError("execution_accepted must be bool")
        slot = self._slot(run_id)
        with _registry_lock:
            slot.accepted = value
            slot.event.set()

    def _accepted(self, slot: _Slot) -> bool:
        with _registry_lock:
            return self._execution_accepted if slot.accepted is None else slot.accepted

    def _poll(self, run_id: str) -> dict[str, Any]:
        return self.control.execute("poll", HostActor(), {"run_id": run_id})["snapshot"]

    def _execute_retry(self, op: str, actor: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        # Transport/response loss is not a new semantic operation. Do not poll
        # and replace its ID: an admitted pending op must join its original owner.
        for attempt in range(3):
            try:
                return self.control.execute(op, actor, request)
            except (ConnectionError, TimeoutError):
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def forward(self, op: str, actor: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        """Forward an explicit actor/request; never derive child work from a receipt."""
        slot = self._slot(request["run_id"])
        try:
            return self._execute_retry(op, actor, request)
        finally:
            slot.event.set()  # including lost acknowledgement after a real commit

    def respond(self, actor: Any, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.forward("respond", actor, request)

    def _wait(self, run_id: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        return self.control.execute("wait", HostActor(), {
            "run_id": run_id, "since_revision": snapshot["revision"],
            "timeout_seconds": self.timeout_seconds})["snapshot"]

    def _park(self, event: threading.Event) -> None:
        """Private test seam; no connection, registry lock or runtime lock held."""
        event.wait(self.idle_interval)

    def stop(self, run_id: str, request_id: str | None = None) -> dict[str, Any]:
        """External stop is poll/cancel/wait, not a disposition or coroutine abort."""
        slot = self._slot(run_id)
        request_id = _next_request_id() if request_id is None else canonical_uuid(request_id)
        try:
            snapshot = self._poll(run_id)
            while snapshot["status"] not in {"completed", "stopped"}:
                if snapshot["cancel_requested"] and snapshot["status"] == "running":
                    snapshot = self._wait(run_id, snapshot)
                    continue
                try:
                    self._execute_retry("cancel", HostActor(), {
                        "run_id": run_id, "expected_revision": snapshot["revision"],
                        "request_id": request_id})
                except ControlError as exc:
                    if exc.code != "revision_conflict":
                        raise
                # A cached cancel receipt may describe an old running revision.
                snapshot = self._poll(run_id)
                slot.event.set()
            return snapshot
        finally:
            slot.event.set()

    def drive(self, run_id: str, *, instruction: str | None = None,
              turn_budget: int | None = None, run_request_id: str | None = None) -> dict[str, Any]:
        """Start a top-level Run, or poll/resume an explicitly created Run/child."""
        slot = self._slot(run_id)
        with _registry_lock:
            if slot.active:
                raise HostBusyError(run_id)
            slot.active = True
        try:
            start_args = (instruction, turn_budget, run_request_id)
            if any(value is not None for value in start_args):
                if any(value is None for value in start_args):
                    raise ValueError("start requires instruction, turn_budget and run_request_id")
                try:
                    self._execute_retry("start", HostActor(), {
                        "run_id": run_id, "parent_run_id": None, "instruction": instruction,
                        "turn_budget": turn_budget, "request_id": run_request_id})
                except (WorkerError, WorkerContractError) as exc:
                    if not hasattr(exc, "response"):
                        raise
            snapshot = self._poll(run_id)  # never decide from historical op_cache
            continuation_id = None
            cancel_id = None
            while True:
                disposition = decide(snapshot, self._accepted(slot))
                if disposition["decision"] == "run_now":
                    continuation_id = continuation_id or _next_request_id()
                    try:
                        self._execute_retry("steer", HostActor(), {
                            "run_id": run_id, "expected_revision": snapshot["revision"],
                            "request_id": continuation_id, "continuation": True})
                    except ControlError as exc:
                        if exc.code != "revision_conflict":
                            raise
                        snapshot = self._poll(run_id)
                        if decide(snapshot, self._accepted(slot))["decision"] != "run_now":
                            continuation_id = None  # definite non-admission; no longer applicable
                        continue
                    except (WorkerError, WorkerContractError) as exc:
                        if not hasattr(exc, "response"):
                            raise
                    continuation_id = None  # consumed; the next turn must have a new ID
                    snapshot = self._poll(run_id)
                elif disposition["decision"] == "wait":
                    continuation_id = None
                    if snapshot["status"] == "running":
                        snapshot = self._wait(run_id, snapshot)
                    else:
                        slot.event.clear()
                        snapshot = self._poll(run_id)
                        current = decide(snapshot, self._accepted(slot))["decision"]
                        if current == "wait" and snapshot["status"] != "running":
                            self._park(slot.event)
                        snapshot = self._poll(run_id)
                else:
                    if snapshot["status"] in {"completed", "stopped"}:
                        return snapshot
                    cancel_id = cancel_id or _next_request_id()
                    try:
                        self._execute_retry("cancel", HostActor(), {
                            "run_id": run_id, "expected_revision": snapshot["revision"],
                            "request_id": cancel_id})
                    except ControlError as exc:
                        if exc.code != "revision_conflict":
                            raise
                    snapshot = self._poll(run_id)
        finally:
            with _registry_lock:
                slot.active = False
                slot.event.set()

    async def drive_async(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        # Shield the thread on coroutine cancellation: never release the unique
        # driver slot while the synchronous worker is still driving the Run.
        task = asyncio.create_task(asyncio.to_thread(self.drive, run_id, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise


def _next_request_id() -> str:
    return str(uuid4())
