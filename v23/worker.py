"""One-shot, DB-free Worker DTOs and bounded fake execution for v23."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4
import hashlib
import json
import math
import re

MAX_TOOL_CALLS = 8
MAX_TOOL_ITEM_BYTES = 4096
MAX_TOOL_TOTAL_BYTES = 32768
MAX_RESULT_BYTES = 65536
MAX_TOOL_ERROR_BYTES = 512
INPUT_KINDS = frozenset({"initial", "parent_instruction", "host_continue", "parent_response"})
OUTCOMES = frozenset({"progress", "needs_input", "completed", "failed"})
JSON_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class WorkerContractError(ValueError):
    """Raised when a Worker DTO violates the v23 contract."""


@dataclass(frozen=True)
class WorkerRequest:
    run_id: UUID
    turn_id: UUID
    base_revision: int
    input_kind: str
    input_digest: str
    instruction: str | None = None
    response: Any = None
    continuation: bool = False


@dataclass(frozen=True)
class TurnReceipt:
    schema_version: int
    turn_id: UUID
    run_id: UUID
    base_revision: int
    input_kind: str
    input_digest: str
    outcome: str
    result: Any
    input_request: Mapping[str, Any] | None = None
    tool_calls: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "turn_id": str(self.turn_id),
            "run_id": str(self.run_id),
            "base_revision": self.base_revision,
            "input_kind": self.input_kind,
            "input_digest": self.input_digest,
            "outcome": self.outcome,
            "result": self.result,
            "input_request": self.input_request,
            "tool_calls": list(self.tool_calls),
        }


def _safe_text(value: str) -> bool:
    # Inspect decoded characters, not literal backslash escape text.
    return not any(ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF for char in value)


def storage_safe_json(value: Any, *, limit: int = 4 * MAX_RESULT_BYTES) -> bytes:
    """Bounded canonical UTF-8 JSON safe for PostgreSQL jsonb (including keys)."""
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
            # jsonb uses numeric: at most 131072 digits before the decimal.
            # Bound conversion first, including when Python's digit limit is disabled.
            if item.bit_length() > 435412:
                raise WorkerContractError("JSON number exceeds jsonb numeric range")
            digits = len(str(abs(item)))
            remaining -= digits
            if digits > 131072 or remaining < 0:
                raise WorkerContractError("JSON number exceeds storage bound")
            return
        if kind is float and math.isfinite(item):
            return  # Every finite Python float fits PostgreSQL numeric's range/scale.
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
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > limit:
            raise WorkerContractError("JSON byte bound exceeded")
        return encoded
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise WorkerContractError("value must be bounded storage-safe JSON") from exc


def _json(value: Any) -> bytes:
    return storage_safe_json(value)


def _json_bytes(value: Any) -> int:
    return len(_json(value))


def _bounded(value: Any, limit: int, label: str) -> bytes:
    encoded = storage_safe_json(value, limit=limit + 1)
    if len(encoded) > limit:
        raise WorkerContractError(f"{label} is too large")
    return encoded


def _identity(value: Any) -> None:
    if type(value.run_id) is not UUID or type(value.turn_id) is not UUID:
        raise WorkerContractError("run_id and turn_id must be UUID objects")
    if type(value.base_revision) is not int or not 1 <= value.base_revision <= 2**63 - 1:
        raise WorkerContractError("base_revision must be a positive bigint")
    if type(value.input_kind) is not str or value.input_kind not in INPUT_KINDS:
        raise WorkerContractError("unknown input_kind")
    if type(value.input_digest) is not str or _DIGEST.fullmatch(value.input_digest) is None:
        raise WorkerContractError("input_digest must be canonical SHA-256 hex")


def validate_request(request: WorkerRequest) -> None:
    if type(request) is not WorkerRequest:
        raise WorkerContractError("Worker must receive WorkerRequest")
    _identity(request)
    if type(request.continuation) is not bool:
        raise WorkerContractError("continuation must be bool")
    if request.input_kind in {"initial", "parent_instruction"}:
        if type(request.instruction) is not str or not request.instruction.strip():
            raise WorkerContractError("instruction must be a non-empty string")
        _bounded(request.instruction, MAX_RESULT_BYTES, "instruction")
        if request.response is not None or request.continuation:
            raise WorkerContractError("instruction input cannot carry response/continuation")
    elif request.input_kind == "host_continue":
        if request.instruction is not None or request.response is not None or not request.continuation:
            raise WorkerContractError("host_continue must contain only continuation")
    else:
        if request.instruction is not None or request.continuation:
            raise WorkerContractError("parent_response cannot carry instruction/continuation")
        _bounded(request.response, MAX_RESULT_BYTES, "response")


def _validate_input_request(value: Any, outcome: str) -> None:
    if outcome != "needs_input":
        if value is not None:
            raise WorkerContractError("input_request is only legal for needs_input")
        return
    if type(value) is not dict:
        raise WorkerContractError("needs_input requires an input_request object")
    _bounded(value, MAX_RESULT_BYTES, "input_request")
    interaction_id = value.get("interaction_id")
    try:
        if type(interaction_id) is not str or str(UUID(interaction_id)) != interaction_id:
            raise ValueError
    except (TypeError, ValueError, AttributeError) as exc:
        raise WorkerContractError("interaction_id must be a canonical UUID string") from exc
    if "options" in value and type(value["options"]) is not list:
        raise WorkerContractError("options must be a finite JSON array")
    if "response_schema" in value:
        schema = value["response_schema"]
        if type(schema) is not dict or set(schema) - {"type", "required"}:
            raise WorkerContractError("unsupported response_schema declaration")
        if "type" in schema and (type(schema["type"]) is not str or schema["type"] not in JSON_TYPES):
            raise WorkerContractError("unsupported response_schema type")
        if "required" in schema:
            required = schema["required"]
            if (schema.get("type") != "object" or type(required) is not list
                    or any(type(key) is not str for key in required)
                    or len(required) != len(set(required))):
                raise WorkerContractError("required must declare unique object field names")


def _validate_tool_calls(calls: Any) -> None:
    if type(calls) is not tuple or len(calls) > MAX_TOOL_CALLS:
        raise WorkerContractError("tool_calls must be a tuple of at most 8 records")
    for index, call in enumerate(calls, 1):
        if type(call) is not dict:
            raise WorkerContractError("tool call must be an object")
        if type(call.get("call_id")) is not int or call["call_id"] != index:
            raise WorkerContractError("tool call IDs must be ordered bounded sequence numbers")
        if type(call.get("name")) is not str or not call["name"].strip():
            raise WorkerContractError("tool call name must be non-empty")
        if set(call) == {"call_id", "name", "input", "output", "error"}:
            if call["error"] is not None:
                raise WorkerContractError("normal tool results must use output, not error")
        elif set(call) == {"call_id", "name", "input_digest", "input_bytes", "error"}:
            if (index != len(calls) or type(call["input_digest"]) is not str
                    or _DIGEST.fullmatch(call["input_digest"]) is None
                    or type(call["input_bytes"]) is not int or call["input_bytes"] < 0
                    or type(call["error"]) is not dict or set(call["error"]) != {"code"}
                    or type(call["error"]["code"]) is not str
                    or call["error"]["code"] not in _EXECUTION_CODES):
                raise WorkerContractError("invalid execution failure record")
            _bounded(call, MAX_TOOL_ERROR_BYTES, "tool failure record")
        else:
            raise WorkerContractError("invalid tool record fields")
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
    _validate_input_request(receipt.input_request, receipt.outcome)
    _validate_tool_calls(receipt.tool_calls)
    if receipt.outcome != "failed" and any(call["error"] is not None for call in receipt.tool_calls):
        raise WorkerContractError("execution failure records require a failed receipt")


_EXECUTION_CODES = frozenset({"invalid_plan", "unknown_tool", "handler_exception",
                              "tool_serialization", "tool_overflow", "worker_runtime"})


class WorkerExecutionError(RuntimeError):
    """A failed turn; only bounded executed records and a fixed error code escape."""

    def __init__(self, code: str, tool_calls: tuple[Mapping[str, Any], ...] = ()) -> None:
        if type(code) is not str or code not in _EXECUTION_CODES:
            code = "worker_runtime"
        _validate_tool_calls(tool_calls)
        self.code = code
        self.tool_calls = tuple(json.loads(_json(list(tool_calls))))
        self.result = {"ok": False, "error": {"code": code}}
        super().__init__(code)


@dataclass(frozen=True)
class FakeTool:
    name: str
    handler: Callable[[Any], Any]


def _failure_record(index: int, name: str, encoded_input: bytes, code: str) -> dict[str, Any]:
    # UTF-8 truncation also bounds multi-byte names, without leaking raw inputs/outputs.
    short_name = name.encode("utf-8", errors="replace")[:128].decode("utf-8", errors="ignore")
    short_name = "".join(char if _safe_text(char) else "?" for char in short_name).strip() or "<tool>"
    while _json_bytes(short_name) > 128:
        short_name = short_name[:-1]
    record = {"call_id": index, "name": short_name, "input_digest": hashlib.sha256(encoded_input).hexdigest(),
              "input_bytes": len(encoded_input), "error": {"code": code}}
    _bounded(record, MAX_TOOL_ERROR_BYTES, "tool failure record")
    return record


class FakeWorker:
    """A deterministic one-call Worker; it never owns a database connection."""

    def __init__(
        self,
        plans: Mapping[UUID | str, list[Any]] | None = None,
        *,
        default: Any = "completed",
        tools: Mapping[str, FakeTool] | None = None,
    ) -> None:
        self._plans = {str(key): list(value) for key, value in (plans or {}).items()}
        self.default = default
        self.tools = dict(tools or {})
        self.calls: list[WorkerRequest] = []

    def _next_plan(self, request: WorkerRequest) -> Any:
        queue = self._plans.get(str(request.run_id))
        if queue:
            return queue.pop(0)
        return self.default

    def _prepare_tools(self, raw: Any) -> list[tuple[FakeTool, Any, bytes]]:
        if type(raw) not in (list, tuple) or len(raw) > MAX_TOOL_CALLS:
            raise WorkerExecutionError("invalid_plan")
        prepared = []
        for index, spec in enumerate(raw, 1):
            if type(spec) is not dict or set(spec) != {"name", "input"}:
                raise WorkerExecutionError("invalid_plan")
            name = spec["name"]
            if type(name) is not str or not name.strip():
                raise WorkerExecutionError("invalid_plan")
            encoded_input = _json(spec["input"])
            _bounded({"call_id": index, "name": name, "input": spec["input"],
                      "output": None, "error": None}, MAX_TOOL_ITEM_BYTES, "tool envelope")
            tool = self.tools.get(name)
            if tool is None:
                raise WorkerExecutionError("unknown_tool")
            if type(tool) is not FakeTool or type(tool.name) is not str or tool.name != name or not callable(tool.handler):
                raise WorkerExecutionError("invalid_plan")
            prepared.append((tool, json.loads(encoded_input), encoded_input))
        return prepared

    def run(self, request: WorkerRequest) -> TurnReceipt:
        validate_request(request)
        self.calls.append(request)
        records: list[dict[str, Any]] = []
        try:
            plan = self._next_plan(request)
            if callable(plan):
                plan = plan(request)
            if type(plan) is TurnReceipt:
                validate_receipt(plan, request)
                return plan
            if type(plan) is str:
                plan = {"outcome": plan, "result": {"ok": True, "turn": len(self.calls)}}
            if type(plan) is not dict or set(plan) - {"outcome", "result", "input_request", "tool_calls"}:
                raise WorkerExecutionError("invalid_plan")
            outcome = plan.get("outcome", "completed")
            input_request = plan.get("input_request")
            if outcome == "needs_input" and input_request is None:
                input_request = {"interaction_id": str(uuid4()), "prompt": "input required", "options": []}
            receipt = TurnReceipt(1, request.turn_id, request.run_id, request.base_revision,
                                  request.input_kind, request.input_digest, outcome,
                                  plan.get("result", {"ok": True}), input_request)
            # Validate the whole plan before any externally observable handler effect.
            validate_receipt(receipt, request)
            result = json.loads(_json(receipt.result))
            input_request = json.loads(_json(receipt.input_request))
            prepared = self._prepare_tools(plan.get("tool_calls", ()))
        except WorkerExecutionError:
            raise
        except WorkerContractError:
            raise WorkerExecutionError("invalid_plan") from None
        except Exception:
            raise WorkerExecutionError("worker_runtime") from None

        for index, (tool, tool_input, encoded_input) in enumerate(prepared, 1):
            code = "worker_runtime"
            try:
                try:
                    output = tool.handler(tool_input)
                except Exception:
                    code = "handler_exception"
                    raise
                # Record the admitted input, not a potentially mutated handler argument.
                record = {"call_id": index, "name": tool.name, "input": json.loads(encoded_input),
                          "output": output, "error": None}
                code = "tool_serialization"
                encoded_record = _json(record)
                code = "tool_overflow"
                if len(encoded_record) > MAX_TOOL_ITEM_BYTES:
                    raise WorkerContractError("tool call is too large")
                record = json.loads(encoded_record)
                _bounded(records + [record], MAX_TOOL_TOTAL_BYTES, "tool_calls array")
                records.append(record)
            except Exception:
                marker = _failure_record(index, tool.name, encoded_input, code)
                raise WorkerExecutionError(code, tuple(records + [marker])) from None
        try:
            receipt = TurnReceipt(1, request.turn_id, request.run_id, request.base_revision,
                                  request.input_kind, request.input_digest, outcome, result,
                                  input_request, tuple(records))
            validate_receipt(receipt, request)
            return receipt
        except Exception:
            raise WorkerExecutionError("worker_runtime", tuple(records)) from None


class InvalidReceiptWorker(FakeWorker):
    """Deliberately violates the return contract to test invalid-receipt closure."""

    def run(self, request: WorkerRequest) -> TurnReceipt:
        validate_request(request)
        self.calls.append(request)
        return TurnReceipt(
            schema_version=999,
            turn_id=request.turn_id,
            run_id=request.run_id,
            base_revision=request.base_revision,
            input_kind=request.input_kind,
            input_digest=request.input_digest,
            outcome="completed",
            result={},
        )
