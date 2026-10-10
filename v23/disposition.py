"""Strict, side-effect-free three-way v23 disposition over committed snapshots."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID
import re

from v23.worker import (TurnReceipt, WorkerRequest, WorkerContractError,
                        validate_receipt)

STATUSES = {"ready", "running", "waiting_input", "completed", "stopped"}
CLOSE_REASONS = {"cancelled", "worker_failed", "invalid_worker_receipt", "late_result_after_cancel"}
SNAPSHOT_FIELDS = frozenset({"schema_version", "run_id", "parent_run_id", "status", "revision",
                            "turn_budget", "turns_used", "latest_receipt", "active_operation_id",
                            "active_base_revision", "active_input_digest", "cancel_requested", "close_reason"})
RECEIPT_FIELDS = frozenset({"schema_version", "turn_id", "run_id", "base_revision", "input_kind",
                           "input_digest", "outcome", "result", "input_request", "tool_calls"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def canonical_uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("expected a canonical UUID string")
    return value


def integer(value: Any, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("expected an integer in range")
    return value


def _durable_receipt(receipt: Any, run_id: str, revision: int) -> str:
    """Validate the JSON representation with the same bounded DTO validator.

    The original input is not durable. A shape-only WorkerRequest supplies the
    echoed identity; it does not recompute a digest or invent scheduler input.
    """
    if type(receipt) is not dict or set(receipt) != RECEIPT_FIELDS:
        raise ValueError("malformed durable receipt")
    if canonical_uuid(receipt["run_id"]) != run_id:
        raise ValueError("receipt Run identity contradicts snapshot")
    turn_id = UUID(canonical_uuid(receipt["turn_id"]))
    base = integer(receipt["base_revision"], 1)
    if base >= revision:
        raise ValueError("receipt revision contradicts snapshot")
    if type(receipt["tool_calls"]) is not list:
        raise ValueError("durable tool_calls must be an array")
    kind = receipt["input_kind"]
    request = WorkerRequest(UUID(run_id), turn_id, base, kind, receipt["input_digest"],
                            instruction="shape" if kind in {"initial", "parent_instruction"} else None,
                            continuation=kind == "host_continue")
    dto = TurnReceipt(receipt["schema_version"], turn_id, UUID(run_id), base, kind,
                      receipt["input_digest"], receipt["outcome"], receipt["result"],
                      receipt["input_request"], tuple(receipt["tool_calls"]))
    validate_receipt(dto, request)
    return dto.outcome


def validate_snapshot(snapshot: Mapping[str, Any], execution_accepted: bool) -> None:
    if not isinstance(snapshot, Mapping) or type(execution_accepted) is not bool:
        raise ValueError("snapshot and boolean execution_accepted required")
    try:
        if set(snapshot) != SNAPSHOT_FIELDS:
            raise ValueError("snapshot fields do not match schema")
        if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
            raise ValueError("unsupported snapshot schema")
        run_id = canonical_uuid(snapshot["run_id"])
        parent = snapshot["parent_run_id"]
        if parent is not None and (canonical_uuid(parent) == run_id):
            raise ValueError("self parent")
        revision = integer(snapshot["revision"])
        budget = integer(snapshot["turn_budget"], 1)
        used = integer(snapshot["turns_used"])
        if revision > 2**63 - 1 or budget > 2**31 - 1 or used > budget:
            raise ValueError("revision/budget/turns out of range")
        status = snapshot["status"]
        if type(status) is not str or status not in STATUSES:
            raise ValueError("unknown Run status")
        if type(snapshot["cancel_requested"]) is not bool:
            raise ValueError("cancel_requested must be boolean")
        active, base, digest = (snapshot[key] for key in (
            "active_operation_id", "active_base_revision", "active_input_digest"))
        if status == "running":
            canonical_uuid(active)
            if integer(base, 1) > revision:
                raise ValueError("invalid running admission/budget")
            if type(digest) is not str or _HEX.fullmatch(digest) is None:
                raise ValueError("invalid active input digest")
        elif any(value is not None for value in (active, base, digest)):
            raise ValueError("non-running Run has active fields")
        reason = snapshot["close_reason"]
        if status == "stopped":
            if type(reason) is not str or reason not in CLOSE_REASONS:
                raise ValueError("invalid close reason")
        elif reason is not None:
            raise ValueError("only stopped Runs have a close reason")
        receipt = snapshot["latest_receipt"]
        outcome = None
        if receipt is not None:
            outcome = _durable_receipt(receipt, run_id, revision)
            if used == 0:
                raise ValueError("receipt requires an accepted turn")
            expected = {"ready": "progress", "waiting_input": "needs_input", "completed": "completed"}
            if status in expected and outcome != expected[status]:
                raise ValueError("receipt outcome contradicts Run status")
            if status == "running" and (outcome not in {"progress", "needs_input"}
                                        or receipt["base_revision"] >= base):
                raise ValueError("invalid prior receipt for running admission")
            if status == "stopped" and outcome == "completed":
                raise ValueError("completed receipt cannot be stopped")
            if outcome == "failed" and (status != "stopped" or reason != "worker_failed"):
                raise ValueError("failed receipt must be stopped/worker_failed")
        elif status in {"waiting_input", "completed"} or used != 0:
            raise ValueError("Run status/turns require a receipt")
        if reason == "worker_failed" and outcome != "failed":
            raise ValueError("worker_failed requires a failed receipt")
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError, WorkerContractError) as exc:
        raise ValueError("malformed snapshot") from exc


def decide(snapshot: Mapping[str, Any], execution_accepted: bool) -> dict[str, Any]:
    validate_snapshot(snapshot, execution_accepted)
    status = snapshot["status"]
    receipt = snapshot["latest_receipt"] or {}
    if status in {"completed", "stopped"}:
        decision = "stop"
    elif status == "running":
        decision = "wait"
    elif snapshot["cancel_requested"]:
        decision = "stop"
    elif status == "waiting_input":
        decision = "wait"
    elif receipt.get("outcome") == "failed" or snapshot["turns_used"] >= snapshot["turn_budget"]:
        decision = "stop"
    elif not execution_accepted:
        decision = "wait"
    else:
        decision = "run_now"
    return {"schema_version": 1, "run_id": snapshot["run_id"],
            "observed_revision": snapshot["revision"], "decision": decision}
