"""In-process tools. echo does no IO. read_file reads one workspace root."""
from __future__ import annotations

from typing import Any
import contextvars

from v20.alpha.read_file import ReadError, read_text
from v20.alpha.worker import (
    MAX_TOOL_ERROR_BYTES,
    MAX_TOOL_ITEM_BYTES,
    InTransaction,
    WorkerContractError,
    assert_outside_transaction,
    canonical_json,
)


_workspace_root: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "v20_workspace_root", default=None
)


def use_workspace(root: str | None):
    return _workspace_root.set(root)


def reset_workspace(token) -> None:
    _workspace_root.reset(token)


class ToolFailed(Exception):
    """A tool failure settled later by accept_tool_result. The run status stays put."""

    def __init__(self, message: str) -> None:
        encoded = message.encode("utf-8")[:MAX_TOOL_ERROR_BYTES]
        super().__init__(encoded.decode("utf-8", errors="ignore"))


def echo(arguments: Any) -> dict[str, str]:
    """Return the same text. Rejects an open transaction before doing any work."""
    assert_outside_transaction()
    if type(arguments) is not dict or set(arguments) != {"text"} or type(arguments.get("text")) is not str:
        raise ToolFailed("invalid arguments")
    encoded = canonical_json(arguments).encode("utf-8")
    if len(encoded) > MAX_TOOL_ITEM_BYTES:
        raise ToolFailed("arguments too large")
    return {"text": arguments["text"]}


def read_file(arguments: Any, root: str | None) -> dict[str, str]:
    """Read a UTF-8 file inside root. The root is host configuration, not a run column."""
    assert_outside_transaction()
    if type(arguments) is not dict or set(arguments) - {"path", "start_line", "limit"}:
        raise ToolFailed("invalid arguments")
    path = arguments.get("path")
    if type(path) is not str:
        raise ToolFailed("invalid arguments")
    start = arguments.get("start_line")
    limit = arguments.get("limit")
    if start is not None and type(start) is not int:
        raise ToolFailed("invalid arguments")
    if limit is not None and type(limit) is not int:
        raise ToolFailed("invalid arguments")
    if type(root) is not str or not root.strip():
        raise ToolFailed("workspace root is not set")
    try:
        text = read_text(root, path, start, limit)
    except ReadError as exc:
        raise ToolFailed(f"{exc.code}: {exc.message}") from exc
    return {"path": path, "text": text}


def run_tool(name: str, arguments: Any) -> dict[str, Any]:
    """Dispatch the closed tool set. Unknown names fail outside any transaction."""
    try:
        assert_outside_transaction()
    except InTransaction:
        raise
    if type(name) is not str:
        raise ToolFailed("unknown tool")
    try:
        if name == "echo":
            return echo(arguments)
        if name == "read_file":
            return read_file(arguments, _workspace_root.get())
        raise ToolFailed("unknown tool")
    except WorkerContractError as exc:
        raise ToolFailed(str(exc)) from exc
