"""Provider exceptions. str() is the class name only."""
from __future__ import annotations

DETAIL_KEYS = frozenset({"class", "http_status", "finish_reason"})


def detail(cls: str, http_status=None, finish_reason=None) -> dict:
    return {
        "class": cls,
        "http_status": http_status,
        "finish_reason": finish_reason,
    }


class ProviderError(Exception):
    def __init__(self, info: dict) -> None:
        if not isinstance(info, dict) or set(info) != DETAIL_KEYS:
            raise TypeError("detail")
        if not isinstance(info["class"], str) or info["class"] == "":
            raise TypeError("detail")
        super().__init__(type(self).__name__)
        self.detail = {
            "class": info["class"],
            "http_status": info["http_status"],
            "finish_reason": info["finish_reason"],
        }

    def __str__(self) -> str:
        return type(self).__name__


class ProviderPreflight(ProviderError):
    pass


class ProviderRejected(ProviderError):
    pass


class ProviderUncertain(ProviderError):
    pass
