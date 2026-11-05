"""Shared session-service value types and backend protocol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class StartResult:
    run_id: str
    scope_id: str | None = None
    realm: str | None = None
    binding: dict[str, Any] = field(default_factory=dict)
    run: dict[str, Any] | None = None


class SessionBackend(Protocol):
    """The only runtime surface the transport-neutral service needs.

    The S0 UI adapter implements this with AgentRuntime.  Tests may use a
    scripted fake.  The service never passes session_id to v24.start; the
    backend only uses it for host-side scope/key bookkeeping.
    """

    def start(self, *, session_id: str, message: str, toolset: str | None,
              budget: dict, run_key: str, workspace_root: str | None,
              model: str | None, seed: list[dict] | None = None,
              binding: dict | None = None) -> StartResult:
        ...

    def poll(self, run_id: str, after_revision: int = 0) -> dict:
        ...

    def cancel(self, run_id: str, request_key: str) -> dict:
        ...

    def steer(self, run_id: str, message: str, generation: int,
              request_key: str) -> dict:
        ...

    def respond(self, run_id: str, interaction_id: str, response: dict,
                generation: int, request_key: str) -> dict:
        ...
