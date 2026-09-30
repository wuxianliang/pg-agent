"""Deterministic FakeTool. Dispatch key is tool_name.

No clock, no random source, no socket. An unregistered name returns
{"ok": false}. Default fake_search returns a closed success object.
"""
from __future__ import annotations

from copy import deepcopy


class FakeTool:
    def __init__(self) -> None:
        self._script: dict[str, dict] = {
            "fake_search": {"ok": True, "value": {"hits": []}},
        }
        self.calls: list[tuple[str, object]] = []

    def register(self, tool_name: str, result: dict) -> None:
        if not isinstance(tool_name, str) or tool_name == "":
            raise TypeError("tool_name")
        if not isinstance(result, dict):
            raise TypeError("result")
        self._script[tool_name] = deepcopy(result)

    def call(self, tool_name: str, args) -> dict:
        if not isinstance(tool_name, str):
            raise TypeError("tool_name")
        self.calls.append((tool_name, deepcopy(args)))
        if tool_name not in self._script:
            return {"ok": False}
        return deepcopy(self._script[tool_name])
