"""DeepSeek chat-completions adapter. Gate tests inject transport; no socket by default."""
from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from v15.provider.errors import ProviderRejected, ProviderUncertain, detail
from v15.provider.pricing import PRICING_REVISION, compute_cost, is_peak

ALLOWLIST = frozenset({"deepseek-flash"})
_DEFAULT_BASE = "https://api.deepseek.com/v1"
_CHUNK = 65536
_MAX_BYTES = 10 * 1024 * 1024
_INT4 = 2147483647
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_ROLES = frozenset({"system", "user", "assistant"})
_ABANDON_FINISH = frozenset({"insufficient_system_resource", "aborted"})
_TRANSIENT_400 = "could not parse the json body"


def build_opener():
    proxy = urllib.request.ProxyHandler({})
    redirect = _NoRedirect()
    opener = urllib.request.build_opener(proxy, redirect)
    opener.v15_proxy = proxy
    opener.v15_redirect = redirect
    return opener


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    def http_error_301(self, req, fp, code, msg, headers):
        return fp

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _sanitize(text: str) -> str:
    text = text.replace("\x00", "\\u0000")
    return "".join(ch for ch in text if 32 <= ord(ch) != 127)


def _integral(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float) and value.is_integer() and 1 <= value <= _INT4:
        return int(value)
    return None


def read_bounded(resp, deadline: float, *, monotonic, chunk: int = _CHUNK, limit: int = _MAX_BYTES) -> bytes:
    parts: list[bytes] = []
    total = 0
    while True:
        if monotonic() >= deadline:
            resp.close()
            raise ProviderUncertain(detail("transport"))
        try:
            block = resp.read(chunk)
        except (TimeoutError, urllib.error.URLError, OSError, http.client.HTTPException):
            resp.close()
            raise ProviderUncertain(detail("transport")) from None
        if not block:
            return b"".join(parts)
        total += len(block)
        parts.append(block)
        if total > limit or monotonic() >= deadline:
            resp.close()
            raise ProviderUncertain(detail("transport"))


class StdlibTransport:
    def __init__(self, *, monotonic=None, opener_factory=None) -> None:
        self.monotonic = monotonic or time.monotonic
        self.opener_factory = opener_factory
        self._resp = None

    def close(self) -> None:
        resp = self._resp
        self._resp = None
        if resp is not None:
            resp.close()

    def post(self, url: str, body: bytes, headers: dict, deadline: float) -> tuple[int, bytes]:
        if self.monotonic() >= deadline:
            raise ProviderUncertain(detail("transport"))
        factory = self.opener_factory or build_opener
        opener = factory()
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            raise ProviderUncertain(detail("transport"))
        try:
            resp = opener.open(request, timeout=remaining)
        except urllib.error.HTTPError as exc:
            self._resp = exc
            try:
                if self.monotonic() >= deadline:
                    raise ProviderUncertain(detail("transport"))
                return exc.code, read_bounded(exc, deadline, monotonic=self.monotonic)
            finally:
                self.close()
        except (TimeoutError, urllib.error.URLError, OSError):
            raise ProviderUncertain(detail("transport")) from None
        self._resp = resp
        try:
            if self.monotonic() >= deadline:
                raise ProviderUncertain(detail("transport"))
            status = resp.status if hasattr(resp, "status") else resp.getcode()
            return int(status), read_bounded(resp, deadline, monotonic=self.monotonic)
        finally:
            self.close()


def _usage_int(usage: dict, key: str) -> int:
    if key not in usage:
        raise ProviderUncertain(detail("usage_invalid"))
    value = usage[key]
    if isinstance(value, bool) or type(value) is not int or value < 0 or value > _INT4:
        raise ProviderUncertain(detail("usage_invalid"))
    return value


def _loads(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None


def _transient_400(raw: bytes) -> bool:
    body = _loads(raw)
    if not isinstance(body, dict):
        return False
    err = body.get("error")
    if not isinstance(err, dict):
        return False
    message = err.get("message")
    if not isinstance(message, str):
        return False
    return _TRANSIENT_400 in message.lower()


def _finish_or_other(finish) -> str:
    if finish in _ABANDON_FINISH:
        return finish
    return "other"


def _provider_meta(body: dict, finish, usage: dict, at: datetime, peak: bool, reasoning_chars: int) -> dict:
    meta = {
        "finish_reason": _sanitize(finish) if isinstance(finish, str) else None,
        "usage": {
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "prompt_cache_hit_tokens": usage["prompt_cache_hit_tokens"],
            "prompt_cache_miss_tokens": usage["prompt_cache_miss_tokens"],
        },
        "pricing_revision": PRICING_REVISION,
        "peak": peak,
        "priced_at": at.isoformat(),
        "reasoning_chars": reasoning_chars,
    }
    ident = body.get("id")
    if isinstance(ident, str):
        cleaned = _sanitize(ident)
        if _ID_RE.fullmatch(cleaned):
            meta["id"] = cleaned
    model = body.get("model")
    if isinstance(model, str):
        cleaned = _sanitize(model)[:80]
        if cleaned:
            meta["model"] = cleaned
    return meta


def _classify(status: int, raw: bytes, clock) -> dict:
    if 300 <= status <= 399:
        raise ProviderUncertain(detail("transport", http_status=status))
    if 200 <= status <= 299 and status != 200:
        raise ProviderUncertain(detail("finish_reason", finish_reason="other"))
    if status in (408, 429) or 500 <= status <= 599:
        raise ProviderUncertain(detail("http_status", http_status=status))
    if status == 400 and _transient_400(raw):
        raise ProviderUncertain(detail("transport", http_status=400))
    if 400 <= status <= 499:
        raise ProviderRejected(detail("http_status", http_status=status))
    if status != 200:
        raise ProviderUncertain(detail("transport"))
    body = _loads(raw)
    if not isinstance(body, dict):
        raise ProviderUncertain(detail("transport"))
    if "model" in body and body.get("model") != "deepseek-flash":
        raise ProviderRejected(detail("finish_reason", finish_reason="model_mismatch"))
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderUncertain(detail("finish_reason", finish_reason="other"))
    choice = choices[0]
    finish = choice.get("finish_reason")
    if finish == "content_filter":
        raise ProviderRejected(detail("finish_reason", finish_reason="content_filter"))
    if finish in _ABANDON_FINISH:
        raise ProviderUncertain(detail("finish_reason", finish_reason=finish))
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderUncertain(detail("finish_reason", finish_reason=_finish_or_other(finish)))
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderUncertain(detail("finish_reason", finish_reason=_finish_or_other(finish)))
    reasoning = message.get("reasoning_content")
    reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise ProviderUncertain(detail("usage_invalid"))
    prompt_tokens = _usage_int(usage, "prompt_tokens")
    completion_tokens = _usage_int(usage, "completion_tokens")
    hit = _usage_int(usage, "prompt_cache_hit_tokens")
    miss = _usage_int(usage, "prompt_cache_miss_tokens")
    if hit + miss != prompt_tokens:
        raise ProviderUncertain(detail("usage_invalid"))
    priced_at = clock()
    if not isinstance(priced_at, datetime):
        raise ProviderUncertain(detail("unpriced"))
    peak = is_peak(priced_at)
    cost = compute_cost(
        "deepseek-flash",
        prompt_cache_miss_tokens=miss,
        prompt_cache_hit_tokens=hit,
        completion_tokens=completion_tokens,
        at=priced_at,
    )
    if cost is None or not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0:
        raise ProviderUncertain(detail("unpriced" if cost is None else "usage_invalid"))
    if peak is None:
        raise ProviderUncertain(detail("unpriced"))
    return {
        "content": content,
        "prompt_tokens": prompt_tokens,
        "cost_usd": cost,
        "provider": _provider_meta(
            body,
            finish,
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "prompt_cache_hit_tokens": hit,
                "prompt_cache_miss_tokens": miss,
            },
            priced_at,
            peak,
            reasoning_chars,
        ),
    }


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 120.0,
        transport=None,
        clock=None,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        if base_url is None:
            base_url = os.environ.get("OPENAI_API_URI") or _DEFAULT_BASE
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise ValueError("timeout_s")
        if not (timeout_s > 0 and timeout_s < 600):
            raise ValueError("timeout_s")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)
        self.transport = transport if transport is not None else StdlibTransport()
        self.clock = clock or (lambda: datetime.now(ZoneInfo("Asia/Shanghai")))

    def close(self) -> None:
        closer = getattr(self.transport, "close", None)
        if closer is not None:
            closer()

    def preflight(self, llm_config: dict) -> dict | None:
        if self.api_key == "":
            return detail("credentials_absent")
        if not isinstance(llm_config, dict):
            return detail("model_missing")
        model = llm_config.get("model")
        if not isinstance(model, str) or model == "":
            return detail("model_missing")
        if model not in ALLOWLIST:
            return detail("model_not_allowlisted")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            return detail("endpoint_rejected")
        return None

    def complete(self, logical_digest: str, n: int, request: dict, llm_config: dict | None = None) -> dict:
        del logical_digest, n
        if not isinstance(llm_config, dict) or not isinstance(llm_config.get("model"), str):
            raise ProviderRejected(detail("request_invalid"))
        if llm_config["model"] not in ALLOWLIST:
            raise ProviderRejected(detail("request_invalid"))
        if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
            raise ProviderRejected(detail("request_invalid"))
        messages = []
        for item in request["messages"]:
            if not isinstance(item, dict):
                raise ProviderRejected(detail("request_invalid"))
            role = item.get("role")
            content = item.get("content")
            if role not in _ROLES or not isinstance(content, str):
                raise ProviderRejected(detail("request_invalid"))
            messages.append({"role": role, "content": content})
        body = {"model": llm_config["model"], "messages": messages, "stream": False}
        max_tokens = _integral(llm_config.get("max_output_tokens"))
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        deadline = time.monotonic() + self.timeout_s
        try:
            status, raw = self.transport.post(
                self.base_url + "/chat/completions",
                payload,
                headers,
                deadline,
            )
        except ProviderUncertain:
            raise
        except ProviderRejected:
            raise
        except (TimeoutError, urllib.error.URLError, OSError):
            raise ProviderUncertain(detail("transport")) from None
        return _classify(status, raw, self.clock)
