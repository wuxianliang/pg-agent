"""Pure read of a committed snapshot. This function does not touch the database."""
from __future__ import annotations

from typing import Mapping


def decide(snapshot: Mapping[str, object]) -> str:
    """Return run_now, wait, needs_input, stop, or failed.

    The caller's own expects_handle row is not a pending turn and not a handle wait.
    depended_handle_state is the row named by depends_on_request_id.
    """
    status = snapshot.get("run_status", snapshot.get("status"))
    if status == "completed":
        return "stop"
    if status in {"failed", "cancelled"}:
        return "failed"
    if status == "expired":
        return "failed"
    if snapshot.get("depended_handle_state") == "pending":
        return "wait"
    if snapshot.get("pending_tool") or snapshot.get("pending_turn"):
        return "run_now"
    if status == "waiting_for_input":
        return "needs_input"
    if status == "running":
        return "wait"
    return "failed"
