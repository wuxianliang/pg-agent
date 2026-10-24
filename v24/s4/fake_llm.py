"""Deterministic in-process loop hosts for v24 S4 gates.

Both fakes are pure Python: they open no sockets, read no files, never sleep
and never use randomness.  A script is consumed at most once per entry; an
exhausted script is a gate failure, not a retry signal.

FakeLLM entry shape (``script`` is a list)::

    {"cause": "start", "result": {"text": "..."}}          # match request.cause
    {"step": 0, "result": {"text": "..."}}                 # match request.state.step
    {"cause": "continuation", "step": 1, "result": {...}}  # both must match
    {"result": {...}}                                      # order-only wildcard

Every entry must carry a ``result`` object.  The first unused entry whose
selectors match is returned (deep-copied) and recorded in ``calls``.

FakeTool script shape (``script`` is a dict)::

    {"search": {"status": "ok", "output": {"hits": []}}}

``invoke(request)`` resolves ``request.tool.key`` (or the top-level ``key``)
and returns the registered result.  An unregistered key is a gate failure.
"""
from __future__ import annotations

from copy import deepcopy


_LLM_SELECTORS = frozenset({"cause", "step", "state.step"})
_LLM_ENTRY_KEYS = _LLM_SELECTORS | {"result"}


class FakeLLM:
    """Scripted model host.  ``calls`` records every request, deep-copied."""

    def __init__(self, script):
        if not isinstance(script, (list, tuple)):
            raise TypeError("FakeLLM script must be a list of result entries")
        self._entries = []
        for index, entry in enumerate(script):
            if not isinstance(entry, dict):
                raise TypeError(f"FakeLLM script[{index}] must be an object")
            unknown = set(entry) - _LLM_ENTRY_KEYS
            if unknown:
                raise ValueError(f"FakeLLM script[{index}] has unknown keys {sorted(unknown)}")
            if "result" not in entry or not isinstance(entry["result"], dict):
                raise ValueError(f"FakeLLM script[{index}] requires a result object")
            cause = entry.get("cause")
            if cause is not None and not isinstance(cause, str):
                raise TypeError(f"FakeLLM script[{index}].cause must be a string")
            step = entry.get("step", entry.get("state.step"))
            if step is not None and (not isinstance(step, int) or isinstance(step, bool)):
                raise TypeError(f"FakeLLM script[{index}].step must be an integer")
            self._entries.append({
                "cause": cause,
                "step": step,
                "result": deepcopy(entry["result"]),
                "used": False,
            })
        self.calls = []

    @staticmethod
    def _request_cause(request):
        cause = request.get("cause")
        return cause if isinstance(cause, str) else None

    @staticmethod
    def _request_step(request):
        state = request.get("state")
        if not isinstance(state, dict):
            return None
        step = state.get("step")
        return step if isinstance(step, int) and not isinstance(step, bool) else None

    def complete(self, request):
        """Return the first matching unused scripted result.

        Raises ``RuntimeError`` when the script cannot answer the request; the
        gates treat that as a failure because no retry or fallback may occur.
        """
        if not isinstance(request, dict):
            raise TypeError("FakeLLM.complete requires a request object")
        self.calls.append(deepcopy(request))
        cause = self._request_cause(request)
        step = self._request_step(request)
        for entry in self._entries:
            if entry["used"]:
                continue
            if entry["cause"] is not None and entry["cause"] != cause:
                continue
            if entry["step"] is not None and entry["step"] != step:
                continue
            entry["used"] = True
            return deepcopy(entry["result"])
        raise RuntimeError(
            "FakeLLM script exhausted: no unused entry for "
            f"cause={cause!r} state.step={step!r}"
        )


class FakeTool:
    """Scripted tool host keyed by the tool key; ``calls`` records requests."""

    def __init__(self, script):
        if not isinstance(script, dict):
            raise TypeError("FakeTool script must be a dict of key -> result")
        for key, result in script.items():
            if not isinstance(key, str) or not key:
                raise TypeError("FakeTool script keys must be nonempty strings")
            if not isinstance(result, dict):
                raise TypeError(f"FakeTool script[{key!r}] must be an object")
        self._script = deepcopy(script)
        self.calls = []

    @staticmethod
    def _tool_key(request):
        if not isinstance(request, dict):
            return None
        tool = request.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get("key"), str):
            return tool["key"]
        key = request.get("key")
        return key if isinstance(key, str) else None

    def invoke(self, request):
        """Return the registered tool result or raise on an unknown key."""
        self.calls.append(deepcopy(request))
        key = self._tool_key(request)
        if key is None:
            raise RuntimeError("FakeTool request carries no tool.key")
        if key not in self._script:
            raise RuntimeError(f"FakeTool has no scripted result for key {key!r}")
        return deepcopy(self._script[key])
