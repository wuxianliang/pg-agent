"""In-process echo tool. No filesystem, subprocess, or socket."""
from __future__ import annotations

from typing import Any

from v20.alpha.worker import (
    MAX_TOOL_ERROR_BYTES,
    MAX_TOOL_ITEM_BYTES,
    InTransaction,
    WorkerContractError,
    assert_outside_transaction,
    canonical_json,
)


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


def run_tool(name: str, arguments: Any) -> dict[str, str]:
    """Dispatch the closed tool set. Unknown names fail outside any transaction."""
    try:
        assert_outside_transaction()
    except InTransaction:
        raise
    if type(name) is not str or name != "echo":
        raise ToolFailed("unknown tool")
    try:
        return echo(arguments)
    except WorkerContractError as exc:
        raise ToolFailed(str(exc)) from exc
