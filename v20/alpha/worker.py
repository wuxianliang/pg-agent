"""DB-free Worker DTOs for the v20 alpha loop.

Bounds match v23/worker.py. Alpha requests also carry provider_handle and
tool_results, and both enter input_digest together with input_kind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import uuid4
import hashlib
import json
import math

MAX_TOOL_CALLS = 8
MAX_TOOL_ITEM_BYTES = 4096
MAX_TOOL_TOTAL_BYTES = 32768
MAX_RESULT_BYTES = 65536
MAX_TOOL_ERROR_BYTES = 512
INPUT_KINDS = frozenset({"initial", "parent_instruction", "host_continue", "parent_response"})
OUTCOMES = frozenset({"progress", "needs_input", "completed", "failed"})


class WorkerContractError(ValueError):
    """Raised when a Worker DTO violates the alpha contract. Nothing is written."""


class InTransaction(RuntimeError):
    """Raised when a model or tool call observes an open database transaction."""


def assert_outside_transaction() -> None:
    from v20.alpha.control import Control

    if Control.in_transaction():
        raise InTransaction("model or tool call inside a database transaction")


def _safe_text(value: str) -> bool:
    return not any(ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF for char in value)


def storage_safe_json(value: Any, *, limit: int = 4 * MAX_RESULT_BYTES) -> bytes:
    """Bounded canonical UTF-8 JSON safe for PostgreSQL jsonb, including keys."""
    remaining = limit

    def visit(item: Any, depth: int = 0) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 128:
            raise WorkerContractError("JSON traversal bound exceeded")
        kind = type(item)
        if item is None or kind is bool:
            return
        if kind is str:
            remaining -= len(item)
            if remaining < 0 or not _safe_text(item):
                raise WorkerContractError("JSON string is not storage-safe")
            return
        if kind is int:
            if item.bit_length() > 435412:
                raise WorkerContractError("JSON number exceeds jsonb numeric range")
            digits = len(str(abs(item)))
            remaining -= digits
            if digits > 131072 or remaining < 0:
                raise WorkerContractError("JSON number exceeds storage bound")
            return
        if kind is float and math.isfinite(item):
            return
        if kind in (list, dict):
            if len(item) > remaining:
                raise WorkerContractError("JSON traversal bound exceeded")
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        raise WorkerContractError("JSON object keys must be strings")
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            return
        raise WorkerContractError("value must be finite JSON")

    try:
        visit(value)
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        if len(encoded) > limit:
            raise WorkerContractError("JSON byte bound exceeded")
        return encoded
    except WorkerContractError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise WorkerContractError("value must be bounded storage-safe JSON") from exc


def canonical_json(value: Any) -> str:
    return storage_safe_json(value).decode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(storage_safe_json(value)).hexdigest()


def compute_input_digest(material: Mapping[str, Any]) -> str:
    """Digest of the worker input. input_kind, provider_handle and tool_results are inside."""
    body = {
        "base_revision": material["base_revision"],
        "continuation": bool(material["continuation"]),
        "input_kind": material["input_kind"],
        "instruction": material.get("instruction"),
        "provider_handle": material.get("provider_handle"),
        "response": material.get("response"),
        "run_id": material["run_id"],
        "tool_results": list(material.get("tool_results") or []),
        "turn_id": material["turn_id"],
    }
    return sha256_json(body)


def _bounded(value: Any, limit: int, label: str) -> None:
    encoded = storage_safe_json(value, limit=max(limit, 1) + 1)
    if len(encoded) > limit:
        raise WorkerContractError(f"{label} is too large")


@dataclass(frozen=True)
class WorkerRequest:
    run_id: str
    turn_id: str
    base_revision: int
    input_kind: str
    input_digest: str
    instruction: str | None = None
    response: Any = None
    continuation: bool = False
    provider_handle: Any = None
    tool_results: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = field(default_factory=tuple)


@dataclass(frozen=True)
class TurnReceipt:
    schema_version: int
    turn_id: str
    run_id: str
    base_revision: int
    input_kind: str
    input_digest: str
    outcome: str
    result: Any
    input_request: Any = None
    tool_calls: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "run_id": self.run_id,
            "base_revision": self.base_revision,
            "input_kind": self.input_kind,
            "input_digest": self.input_digest,
            "outcome": self.outcome,
            "result": self.result,
            "input_request": self.input_request,
            "tool_calls": [dict(call) for call in self.tool_calls],
            "request_id": None,
        }


def _identity(value: WorkerRequest | TurnReceipt) -> None:
    if type(value.run_id) is not str or not value.run_id:
        raise WorkerContractError("run_id must be a non-empty string")
    if type(value.turn_id) is not str or not value.turn_id:
        raise WorkerContractError("turn_id must be a non-empty string")
    if type(value.base_revision) is not int or not 1 <= value.base_revision <= 2**63 - 1:
        raise WorkerContractError("base_revision must be a positive bigint")
    if type(value.input_kind) is not str or value.input_kind not in INPUT_KINDS:
        raise WorkerContractError("unknown input_kind")
    if type(value.input_digest) is not str or len(value.input_digest) != 64:
        raise WorkerContractError("input_digest must be canonical SHA-256 hex")
    try:
        int(value.input_digest, 16)
    except ValueError as exc:
        raise WorkerContractError("input_digest must be canonical SHA-256 hex") from exc


def _tool_results_ok(value: Any, *, required: bool) -> list[Any]:
    if type(value) in (tuple, list):
        items = list(value)
    else:
        raise WorkerContractError("tool_results must be a list")
    if required and not items:
        raise WorkerContractError("host_continue requires tool_results")
    if not required and items:
        raise WorkerContractError("tool_results are only legal for host_continue")
    for item in items:
        if type(item) is not dict or set(item) != {"invocation_id", "tool_name", "output"}:
            raise WorkerContractError("tool result must carry invocation_id, tool_name and output")
        if type(item["invocation_id"]) is not str or type(item["tool_name"]) is not str:
            raise WorkerContractError("tool result identity must be text")
    _bounded(items, MAX_RESULT_BYTES, "tool_results")
    return items


def validate_request(request: WorkerRequest) -> None:
    if type(request) is not WorkerRequest:
        raise WorkerContractError("Worker must receive WorkerRequest")
    _identity(request)
    if type(request.continuation) is not bool:
        raise WorkerContractError("continuation must be bool")
    if request.provider_handle is not None:
        _bounded(request.provider_handle, MAX_RESULT_BYTES, "provider_handle")
    if request.input_kind in {"initial", "parent_instruction"}:
        if type(request.instruction) is not str or not request.instruction.strip():
            raise WorkerContractError("instruction must be a non-empty string")
        _bounded(request.instruction, MAX_RESULT_BYTES, "instruction")
        if request.response is not None or request.continuation:
            raise WorkerContractError("instruction input cannot carry response or continuation")
        _tool_results_ok(request.tool_results, required=False)
    elif request.input_kind == "host_continue":
        if not request.continuation or request.response is not None:
            raise WorkerContractError("host_continue must be a continuation without a response")
        if request.instruction is not None:
            _bounded(request.instruction, MAX_RESULT_BYTES, "instruction")
        _tool_results_ok(request.tool_results, required=True)
    else:
        if request.instruction is not None or request.continuation:
            raise WorkerContractError("parent_response cannot carry instruction or continuation")
        _bounded(request.response, MAX_RESULT_BYTES, "response")
        _tool_results_ok(request.tool_results, required=False)


def _validate_tool_calls(calls: Any) -> None:
    if type(calls) is not tuple or len(calls) > MAX_TOOL_CALLS:
        raise WorkerContractError("tool_calls must be a tuple of at most 8 records")
    for index, call in enumerate(calls, 1):
        if type(call) is not dict:
            raise WorkerContractError("tool call must be an object")
        if call.get("call_id") != index or type(call.get("name")) is not str or not call["name"].strip():
            raise WorkerContractError("tool call name must be a non-empty ordered record")
        if type(call.get("arguments")) is not dict:
            raise WorkerContractError("tool call arguments must be an object")
        _bounded(call, MAX_TOOL_ITEM_BYTES, "tool call")
    _bounded(list(calls), MAX_TOOL_TOTAL_BYTES, "tool_calls array")


def validate_receipt(receipt: TurnReceipt, request: WorkerRequest) -> None:
    validate_request(request)
    if type(receipt) is not TurnReceipt:
        raise WorkerContractError("Worker must return TurnReceipt")
    _identity(receipt)
    if type(receipt.schema_version) is not int or receipt.schema_version != 1:
        raise WorkerContractError("unsupported receipt schema_version")
    if receipt.run_id != request.run_id or receipt.turn_id != request.turn_id:
        raise WorkerContractError("receipt identity does not match Worker admission")
    if receipt.base_revision != request.base_revision:
        raise WorkerContractError("receipt base_revision does not match admission")
    if receipt.input_kind != request.input_kind or receipt.input_digest != request.input_digest:
        raise WorkerContractError("receipt input does not match Worker admission")
    if type(receipt.outcome) is not str or receipt.outcome not in OUTCOMES:
        raise WorkerContractError("unknown receipt outcome")
    _bounded(receipt.result, MAX_RESULT_BYTES, "result")
    if receipt.outcome == "needs_input":
        if type(receipt.input_request) is not dict or type(receipt.input_request.get("interaction_id")) is not str:
            raise WorkerContractError("needs_input requires an input_request object")
    elif receipt.input_request is not None:
        raise WorkerContractError("input_request is only legal for needs_input")
    _validate_tool_calls(receipt.tool_calls)
    if receipt.tool_calls and receipt.outcome != "progress":
        raise WorkerContractError("tool calls belong on a progress receipt")


def validate_stored_receipt(receipt: Mapping[str, Any]) -> None:
    """Check a receipt dict Control is about to store.

    Identity against the turn row stays in Control. This does not require the
    digest to equal a live WorkerRequest, so a gate can hand-build a receipt.
    """
    if type(receipt) is not dict:
        raise WorkerContractError("invalid turn receipt")
    if type(receipt.get("schema_version")) is not int or receipt.get("schema_version") != 1:
        raise WorkerContractError("unsupported receipt schema_version")
    outcome = receipt.get("outcome")
    if type(outcome) is not str or outcome not in OUTCOMES:
        raise WorkerContractError("unknown receipt outcome")
    _bounded(receipt.get("result"), MAX_RESULT_BYTES, "result")
    calls = receipt.get("tool_calls") or []
    if type(calls) is not list:
        raise WorkerContractError("tool_calls must be a list")
    _validate_tool_calls(tuple(calls))
    if calls and outcome != "progress":
        raise WorkerContractError("tool calls belong on a progress receipt")
    request = receipt.get("input_request")
    if outcome == "needs_input":
        if type(request) is not dict or type(request.get("interaction_id")) is not str:
            raise WorkerContractError("needs_input requires an input_request object")
    elif request is not None:
        raise WorkerContractError("input_request is only legal for needs_input")
    base = receipt.get("base_revision")
    if type(base) is not int or not 1 <= base <= 2**63 - 1:
        raise WorkerContractError("base_revision must be a positive bigint")
    digest = receipt.get("input_digest")
    if type(digest) is not str or len(digest) != 64:
        raise WorkerContractError("input_digest must be canonical SHA-256 hex")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise WorkerContractError("input_digest must be canonical SHA-256 hex") from exc


class FakeWorker:
    """Deterministic worker injected by the gate. It never receives a DSN."""

    def __init__(self, script: str = "default") -> None:
        if script not in {"default", "needs_input", "bare_progress"}:
            raise WorkerContractError("unknown FakeWorker script")
        self.script = script
        self.calls: list[WorkerRequest] = []

    def __call__(self, request: WorkerRequest) -> TurnReceipt:
        assert_outside_transaction()
        return self.run(request)

    def run(self, request: WorkerRequest) -> TurnReceipt:
        validate_request(request)
        self.calls.append(request)
        tool_calls: tuple[dict[str, Any], ...] = ()
        input_request = None
        if self.script == "needs_input":
            if request.input_kind == "parent_response":
                outcome = "completed"
                result: Any = {"ok": True}
            else:
                outcome = "needs_input"
                result = {"ok": True}
                input_request = {"interaction_id": str(uuid4()), "prompt": request.instruction or ""}
        elif self.script == "bare_progress":
            outcome = "progress"
            result = {"ok": True}
        elif request.tool_results:
            first = request.tool_results[0]["output"]
            text = first["text"] if isinstance(first, dict) else first
            outcome = "completed"
            result = {"saw": text}
        else:
            outcome = "progress"
            result = {"ok": True}
            tool_calls = ({
                "call_id": 1,
                "name": "echo",
                "arguments": {"text": request.instruction},
            },)
        receipt = TurnReceipt(
            1, request.turn_id, request.run_id, request.base_revision, request.input_kind,
            request.input_digest, outcome, result, input_request, tool_calls,
        )
        validate_receipt(receipt, request)
        return receipt
