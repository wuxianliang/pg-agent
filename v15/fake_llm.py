"""Deterministic FakeLLM. Key is (logical_digest, n).

No clock, no random source, no socket. An unregistered key fails in Python;
the caller must not settle that attempt.
"""
from __future__ import annotations

from copy import deepcopy


class FakeLLM:
    def __init__(self) -> None:
        self._script: dict[tuple[str, int], dict] = {}

    def register(self, digest: str, n: int, response: dict) -> None:
        if not isinstance(digest, str) or digest == "":
            raise TypeError("digest")
        if type(n) is not int or n < 1:
            raise TypeError("n")
        if not isinstance(response, dict) or not isinstance(response.get("content"), str):
            raise TypeError("response")
        if "prompt_tokens" in response and (
            type(response["prompt_tokens"]) is not int or response["prompt_tokens"] < 0
        ):
            raise TypeError("prompt_tokens")
        if "cost_usd" in response and (
            isinstance(response["cost_usd"], bool)
            or not isinstance(response["cost_usd"], (int, float))
            or response["cost_usd"] < 0
        ):
            raise TypeError("cost_usd")
        self._script[(digest, n)] = deepcopy(response)

    def complete(self, logical_digest: str, n: int, request: dict) -> dict:
        if not isinstance(logical_digest, str) or type(n) is not int:
            raise TypeError("logical_digest and n")
        if not isinstance(request, dict):
            raise TypeError("request")
        key = (logical_digest, n)
        if key not in self._script:
            raise KeyError(key)
        return deepcopy(self._script[key])
