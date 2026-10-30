"""v2 tool result envelopes, model text and budget accounting.

The module owns the wire shape of a tool outcome (``success`` / ``failure`` /
``unknown``), the model-visible text join, and the exact byte measurements used
against descriptor limits.  It deliberately does not implement the W4
scenario-to-error mapping or any page-selection policy.

All functions are pure and deterministic; no I/O and no clock access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .canonical import SAFE_INTEGER_MAX, CanonicalError, compact_json

CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
WINDOWS_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")

MAX_CONTENT_BLOCKS = 16
MAX_MESSAGE_BYTES = 1024
FRAME_TARGET = 60000
TRANSPORT_HARD_CAP = 65536

FORBIDDEN_MESSAGE_FRAGMENTS = (
    "\x00",
    "Traceback (",
    "stack trace",
    "DEEPSEEK_API_KEY=",
    "OPENAI_API_KEY=",
)

RESULT_CLASSES = ("success", "failure", "unknown")


class ToolResultError(ValueError):
    """A tool outcome violates the v2 result contract.

    ``reason`` is ``invalid_outcome`` (usage shape) or ``invalid_tool_output``
    (envelope/content/error/meta shape).
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ToolDispatchResult:
    """A validated dispatch result and the text shown to the model.

    ``class_`` is ``success``, ``failure`` or ``unknown``.  An ``unknown``
    result never generates a model continuation, so its ``model_text`` is
    required to be the empty string.
    """

    class_: str
    result: dict
    model_text: str

    def __post_init__(self) -> None:
        if self.class_ not in RESULT_CLASSES:
            raise ToolResultError("invalid_outcome")
        if not isinstance(self.result, dict):
            raise ToolResultError("invalid_outcome")
        if not isinstance(self.model_text, str):
            raise ToolResultError("invalid_outcome")
        if self.class_ == "unknown" and self.model_text != "":
            raise ToolResultError("invalid_outcome")


def _invalid_output() -> None:
    raise ToolResultError("invalid_tool_output")


def _invalid_outcome() -> None:
    raise ToolResultError("invalid_outcome")


def _assert_content(content: Any) -> list:
    if not isinstance(content, list) or not 1 <= len(content) <= MAX_CONTENT_BLOCKS:
        _invalid_output()
    for block in content:
        if type(block) is not dict or set(block) != {"type", "text"}:
            _invalid_output()
        if block["type"] != "text" or not isinstance(block["text"], str):
            _invalid_output()
    return content


def _assert_meta(meta: Any) -> None:
    if not isinstance(meta, dict):
        _invalid_output()
    try:
        compact_json(meta)
    except CanonicalError:
        _invalid_output()


def _message_is_leaked(message: str) -> bool:
    if any(fragment in message for fragment in FORBIDDEN_MESSAGE_FRAGMENTS):
        return True
    for token in message.split():
        if token.startswith("/"):
            return True
        if WINDOWS_DRIVE_RE.match(token):
            return True
        if token.startswith("\\\\"):
            return True
    return False


def _assert_error(error: Any) -> None:
    if type(error) is not dict or set(error) != {"code", "message"}:
        _invalid_output()
    code = error["code"]
    message = error["message"]
    if not isinstance(code, str) or CODE_RE.fullmatch(code) is None:
        _invalid_output()
    if not isinstance(message, str):
        _invalid_output()
    try:
        message_bytes = message.encode("utf-8")
    except UnicodeEncodeError:
        _invalid_output()
    if len(message_bytes) > MAX_MESSAGE_BYTES:
        _invalid_output()
    if _message_is_leaked(message):
        _invalid_output()


def success_output(value: Any, content: list, meta: dict | None = None) -> dict:
    """Build a success envelope and materialize an omitted meta as ``{}``."""
    output = {"value": value, "content": content, "meta": {} if meta is None else meta}
    assert_success_output(output)
    return output


def failure_output(code: str, message: str, content: list,
                   meta: dict | None = None) -> dict:
    """Build a known-failure envelope and materialize an omitted meta."""
    output = {
        "error": {"code": code, "message": message},
        "content": content,
        "meta": {} if meta is None else meta,
    }
    assert_failure_output(output)
    return output


def unknown_output(code: str, message: str) -> dict:
    """Build an unknown-outcome envelope; it has no value, content or meta."""
    output = {"error": {"code": code, "message": message}}
    assert_unknown_output(output)
    return output


def assert_success_output(obj: Any) -> None:
    """Validate a success envelope; omitted and explicit ``{}`` meta agree."""
    if not isinstance(obj, dict):
        _invalid_output()
    keys = set(obj)
    if keys not in ({"value", "content"}, {"value", "content", "meta"}):
        _invalid_output()
    _assert_content(obj["content"])
    if "meta" in obj:
        _assert_meta(obj["meta"])


def assert_failure_output(obj: Any) -> None:
    """Validate a known-failure envelope."""
    if not isinstance(obj, dict):
        _invalid_output()
    keys = set(obj)
    if keys not in ({"error", "content"}, {"error", "content", "meta"}):
        _invalid_output()
    _assert_error(obj["error"])
    _assert_content(obj["content"])
    if "meta" in obj:
        _assert_meta(obj["meta"])


def assert_unknown_output(obj: Any) -> None:
    """Validate an unknown-outcome envelope (error only)."""
    if not isinstance(obj, dict) or set(obj) != {"error"}:
        _invalid_output()
    _assert_error(obj["error"])


def assert_usage(usage: Any) -> None:
    """Validate the closed ``{wall_ms}`` usage object."""
    if not isinstance(usage, dict) or set(usage) != {"wall_ms"}:
        _invalid_outcome()
    wall_ms = usage["wall_ms"]
    if type(wall_ms) is not int or not 0 <= wall_ms <= SAFE_INTEGER_MAX:
        _invalid_outcome()


def assert_builtin_meta(meta: Any) -> None:
    """Validate the three built-in plugins' meta policy: only ``None``/``{}``."""
    if meta is None:
        return
    if isinstance(meta, dict) and not meta:
        return
    _invalid_output()


def join_content(content: Any) -> str:
    """Join text blocks with ``\\n``; no trailing LF and no meta."""
    blocks = _assert_content(content)
    return "\n".join(block["text"] for block in blocks)


def frame_bytes(value: Any) -> int:
    """Return the exact tool-frame bytes for ``value`` plus its trailing LF."""
    frame = {"ok": True, "v": 2, "result": {"value": value}}
    return len(compact_json(frame)) + 1


def measure(args: Any, value: Any, content: Any, meta: Any = None) -> dict:
    """Measure the five budget domains in canonical JSON bytes.

    The default meta is normalized to ``{}`` (2 bytes).  Measurement never
    truncates or rejects; callers compare the result with descriptor limits.
    """
    normalized_meta = {} if meta is None else meta
    try:
        return {
            "args": len(compact_json(args)),
            "value": len(compact_json(value)),
            "content": len(compact_json(content)),
            "meta": len(compact_json(normalized_meta)),
            "frame": frame_bytes(value),
        }
    except CanonicalError:
        raise ToolResultError("invalid_tool_output") from None


def classify_frame(total: int) -> str:
    """Classify a frame byte count against the built-in target and transport."""
    if total <= FRAME_TARGET:
        return "within_builtin_target"
    if total <= TRANSPORT_HARD_CAP:
        return "over_builtin_target_transport_valid"
    return "stdout_limit_unknown"


__all__ = [
    "FRAME_TARGET",
    "TRANSPORT_HARD_CAP",
    "ToolDispatchResult",
    "ToolResultError",
    "assert_builtin_meta",
    "assert_failure_output",
    "assert_success_output",
    "assert_unknown_output",
    "assert_usage",
    "classify_frame",
    "failure_output",
    "frame_bytes",
    "join_content",
    "measure",
    "success_output",
    "unknown_output",
]
