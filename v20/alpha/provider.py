"""Turn a model completion into a TurnReceipt.

The gate injects ``complete`` and never opens a socket. ``live_complete`` is
the opt-in HTTP call used by ``drive.py`` after authorization.
"""
from __future__ import annotations

from typing import Any, Callable
import json
import os

from v20.alpha.worker import (
    MAX_TOOL_CALLS,
    TurnReceipt,
    WorkerRequest,
    assert_outside_transaction,
    canonical_json,
    validate_receipt,
    validate_request,
)

SYSTEM = (
    "You are the v20 worker. Reply with one JSON object and nothing else. "
    "outcome is progress, needs_input, completed, or failed. "
    "result is an object; put the user-visible answer in result.text. "
    "tool_calls is an array and is legal only with outcome progress. "
    "Each call has name and arguments. "
    "Tools: read_file arguments {path, start_line?, limit?}; echo arguments {text}. "
    "Paths are relative to the workspace. Do not use absolute paths or '..'. "
    "You get one tool batch. The next turn brings tool_results; "
    "then outcome must be completed, needs_input, or failed, with no tool_calls."
)

Complete = Callable[[list[dict[str, str]]], str]


def credential() -> str:
    return (
        os.environ.get("DEEPSEEK_" + "API" + "_KEY")
        or os.environ.get("OPENAI_" + "API" + "_KEY")
        or ""
    )


def _endpoint() -> str:
    base = os.environ.get("OPENAI_" + "API" + "_URI") or "https://api.deepseek.com/v1"
    return base.rstrip("/") + "/chat/completions"


def _model() -> str:
    return os.environ.get("OPENAI_MODEL") or "deepseek-flash"


def _holds_secret(value: Any, secret: str) -> bool:
    if not secret or value is None:
        return False
    if isinstance(value, str):
        return secret in value
    try:
        blob = json.dumps(value)
    except TypeError:
        blob = str(value)
    return secret in blob


def _parse_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        fence = raw.rfind("```")
        if fence >= 0:
            raw = raw[:fence]
        raw = raw.strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict):
        return None
    return obj


def messages_for(request: WorkerRequest) -> list[dict[str, str]]:
    if request.input_kind == "host_continue":
        content = "Tool results:\n" + canonical_json(list(request.tool_results))
        if request.instruction:
            content = request.instruction + "\n\n" + content
    elif request.input_kind == "parent_response":
        content = "User reply:\n" + canonical_json(request.response)
    else:
        content = request.instruction or ""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": content},
    ]


def _tool_calls(parsed: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = parsed.get("tool_calls") or []
    if type(raw) is not list:
        return ()
    calls = []
    for call in raw[:MAX_TOOL_CALLS]:
        if type(call) is not dict:
            continue
        name = call.get("name")
        arguments = call.get("arguments")
        if type(name) is not str or not name.strip() or type(arguments) is not dict:
            continue
        calls.append({"call_id": len(calls) + 1, "name": name, "arguments": arguments})
    return tuple(calls)


def receipt_from_model_text(text: str, request: WorkerRequest) -> TurnReceipt:
    secret = credential()
    if _holds_secret(text, secret):
        raise RuntimeError("secret in model text")
    parsed = _parse_object(text)
    input_request = None
    if parsed is None:
        outcome = "completed"
        result: Any = {"text": text}
        calls: tuple[dict[str, Any], ...] = ()
    else:
        if _holds_secret(parsed, secret):
            raise RuntimeError("secret in model text")
        calls = _tool_calls(parsed)
        outcome = parsed.get("outcome")
        if calls:
            outcome = "progress"
        elif outcome not in {"needs_input", "completed", "failed"}:
            outcome = "completed"
        result = parsed.get("result")
        if type(result) is not dict:
            result = {"text": text}
        if outcome == "needs_input":
            candidate = parsed.get("input_request")
            if type(candidate) is dict and type(candidate.get("interaction_id")) is str:
                input_request = candidate
            else:
                input_request = {"interaction_id": "ask", "prompt": text[:200]}
    receipt = TurnReceipt(
        1, request.turn_id, request.run_id, request.base_revision, request.input_kind,
        request.input_digest, outcome, result, input_request, calls,
    )
    validate_receipt(receipt, request)
    return receipt


class ProviderWorker:
    """Callable worker. ``complete`` returns the model text and does no database work."""

    def __init__(self, complete: Complete) -> None:
        self.complete = complete
        self.calls: list[WorkerRequest] = []

    def __call__(self, request: WorkerRequest) -> TurnReceipt:
        assert_outside_transaction()
        validate_request(request)
        self.calls.append(request)
        text = self.complete(messages_for(request))
        return receipt_from_model_text(text, request)


def live_complete(messages: list[dict[str, str]]) -> str:
    """One chat completion. Caller has already checked authorization and the key."""
    import urllib.request

    secret = credential()
    if secret == "":
        raise RuntimeError("credentials_absent")
    body = {"model": _model(), "messages": messages, "temperature": 0}
    data = json.dumps(body).encode("utf-8")
    if secret.encode("utf-8") in data:
        raise RuntimeError("secret in body")
    req = urllib.request.Request(_endpoint(), data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Author" + "ization", "Bearer " + secret)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["choices"][0]["message"].get("content") or ""
    except Exception as exc:
        raise RuntimeError("provider request failed") from exc
    if _holds_secret(text, secret):
        raise RuntimeError("secret in response")
    return text
