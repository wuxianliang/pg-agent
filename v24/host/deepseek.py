"""v24 DeepSeek adapter: serialization, parsing, v24 mapping and lease policy.

Reused without modification from ``v15.provider``: ``StdlibTransport``, the
provider error classes/detail helper, and the versioned pricing functions.  The
v24 adapter deliberately does not reuse ``DeepSeekProvider.complete`` or
``_classify``: the v24 model-call dialect is wider (tools, reasoning history,
tool-call ids) and maps to kernel outcomes itself.

Fixed contract:

* model is exactly ``deepseek-flash``;
* ``0 < timeout_s <= 239``;
* every request carries ``stream: false``;
* ``tool_choice`` is never sent (``required`` is rejected in thinking mode);
* no undocumented fields such as ``parallel_tool_calls``;
* the endpoint is the official HTTPS root ``https://api.deepseek.com`` and
  ``OPENAI_API_URI`` is never read;
* the lease is ``min((ceil(timeout_s)+60)*1000, 300000)``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from v15.provider.deepseek import StdlibTransport
from v15.provider.errors import ProviderRejected, ProviderUncertain, detail
from v15.provider.pricing import PRICING_REVISION, compute_cost, is_peak

from .descriptor import RESERVED_KEY

MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
ENDPOINT = BASE_URL + "/chat/completions"
TIMEOUT_MAX_S = 239.0
DEFAULT_COMPLETION_CAP = 256
MAX_COMPLETION_CAP = 512
FRAMING_MARGIN = 256
_MAX_TOOL_CALLS = 16
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CAUSES = frozenset({"start", "steer", "respond", "continuation", "spawn"})


class AdapterFailure(RuntimeError):
    """A local failure that must be settled as v24 ``failure`` with zero HTTP."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ProviderReply:
    """Closed provider reply record; it goes to the journal, never to the DB."""

    finish_kind: str
    content: str | None
    tool_calls: tuple[dict, ...] | None
    prompt_tokens: int | None
    completion_tokens: int | None
    wall_ms: int
    reasoning_content: str | None
    response_id: str | None
    provider_metadata: dict

    def to_dict(self) -> dict:
        return {
            "finish_kind": self.finish_kind,
            "content": self.content,
            "tool_calls": list(self.tool_calls) if self.tool_calls is not None else None,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "wall_ms": self.wall_ms,
            "reasoning_content": self.reasoning_content,
            "response_id": self.response_id,
            "provider_metadata": self.provider_metadata,
        }

    @property
    def tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class PreparedCall:
    body: dict
    tool_map: dict
    messages: list[dict]
    reserve_tokens: int
    max_tokens: int
    estimate: int

    def to_journal(self) -> dict:
        return {
            "body": self.body,
            "tool_map": self.tool_map,
            "reserve_tokens": self.reserve_tokens,
            "max_tokens": self.max_tokens,
            "estimate": self.estimate,
        }


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _int_token(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_name(key: str) -> str:
    base = _SAFE_NAME.sub("_", key).strip("_")[:80] or "tool"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"[:128]


def _v2_provider_name(key: str) -> str:
    """v2 §6.4 name:key; unsafe keys still use the v1 sanitizer.

    v1 is frozen by B0/G9 and always keeps the hash suffix.  v2 keys are
    descriptor-approved keys; when such a key is already a legal provider
    function name the provider sees it unchanged.
    """
    if _SAFE_NAME.sub("_", key).strip("_") == key and len(key) <= 80:
        return key
    return _safe_name(key)


def provider_tool_name(key: str) -> str:
    """Public deterministic provider tool name for a v24 pin key."""
    if not isinstance(key, str) or not key:
        raise ValueError("key")
    return _safe_name(key)


def _message_ok(message) -> bool:
    return isinstance(message, dict) and isinstance(message.get("role"), str)


def _usage_from_message(usage) -> tuple[int | None, int | None]:
    if not isinstance(usage, dict):
        return None, None
    prompt = _int_token(usage.get("prompt_tokens"))
    completion = _int_token(usage.get("completion_tokens"))
    return prompt, completion


def _usage_result(tokens: int | None, wall_ms: int) -> dict:
    if tokens is None:
        return {"text": None}
    return {"text": None, "usage": {"tokens": tokens, "wall_ms": wall_ms}}


class DeepSeekAdapter:
    def __init__(self, *, api_key: str | None = None, timeout_s: float = 120.0,
                 transport=None, clock=None, monotonic=None):
        import os

        if api_key is None:
            api_key = (os.environ.get("DEEPSEEK_API_KEY")
                       or os.environ.get("OPENAI_API_KEY") or "")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise ValueError("timeout_s")
        if not (0 < timeout_s <= TIMEOUT_MAX_S):
            raise ValueError("timeout_s")
        self._api_key = api_key
        self.timeout_s = float(timeout_s)
        self.monotonic = monotonic or time.monotonic
        self.transport = (transport if transport is not None
                          else StdlibTransport(monotonic=self.monotonic))
        self.clock = clock or (lambda: datetime.now(ZoneInfo("Asia/Shanghai")))

    # -- no secrets in repr/logs ----------------------------------------
    def __repr__(self) -> str:
        return (f"DeepSeekAdapter(model={MODEL!r}, timeout_s={self.timeout_s!r}, "
                f"configured={bool(self._api_key)})")

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def preflight(self) -> dict | None:
        if not self._api_key:
            return detail("credentials_absent")
        return None

    @classmethod
    def lease_ms(cls, timeout_s: float) -> int:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise ValueError("timeout_s")
        if not (0 < timeout_s <= TIMEOUT_MAX_S):
            raise ValueError("timeout_s")
        return min((int(math.ceil(timeout_s)) + 60) * 1000, 300000)

    # -- request construction -------------------------------------------
    def build(self, effect: dict, history: list[dict],
              pins: list[dict]) -> PreparedCall:
        if not self._api_key:
            raise AdapterFailure("credentials_absent")
        request = effect.get("request") if isinstance(effect, dict) else None
        if not isinstance(request, dict):
            raise AdapterFailure("request_invalid")
        cause = request.get("cause")
        if cause not in _CAUSES:
            raise AdapterFailure("request_invalid")
        reserve = request.get("reserve")
        tokens = reserve.get("tokens") if isinstance(reserve, dict) else None
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
            raise AdapterFailure("reserve_zero")

        messages, seed_messages, appended = self._messages(request, cause, history)
        tools, tool_map = self._tools(pins)
        self._validate_history(messages, has_tools=bool(tools))
        provider_messages = self._provider_messages(messages)
        body = {"model": MODEL, "messages": provider_messages, "stream": False}
        if tools:
            body["tools"] = tools
        estimate = len(_canonical(body).encode("utf-8")) + FRAMING_MARGIN
        output = request.get("input", {})
        cap = output.get("max_output_tokens") if isinstance(output, dict) else None
        if cap is None:
            cap = DEFAULT_COMPLETION_CAP
        if isinstance(cap, bool) or not isinstance(cap, int):
            raise AdapterFailure("max_output_tokens_invalid")
        cap = max(1, min(cap, MAX_COMPLETION_CAP))
        available = tokens - estimate
        max_tokens = min(cap, available)
        if max_tokens < 1:
            raise AdapterFailure("reserve_insufficient")
        body["max_tokens"] = max_tokens
        return PreparedCall(
            body=body,
            tool_map=tool_map,
            messages=provider_messages,
            reserve_tokens=tokens,
            max_tokens=max_tokens,
            estimate=estimate,
        )

    def _messages(self, request: dict, cause: str, history: list[dict]):
        seed_messages = None
        appended = []
        if cause in ("start", "spawn"):
            source = request.get("input")
            messages = source.get("messages") if isinstance(source, dict) else None
            if not isinstance(messages, list) or not messages:
                raise AdapterFailure("input_messages_missing")
            seed_messages = []
            for item in messages:
                if (not isinstance(item, dict)
                        or item.get("role") not in ("system", "user")
                        or not isinstance(item.get("content"), str)):
                    raise AdapterFailure("input_messages_invalid")
                seed_messages.append({"role": item["role"],
                                      "content": item["content"]})
            messages = list(seed_messages)
        else:
            if not isinstance(history, list) or not history:
                raise AdapterFailure("history_missing")
            messages = [dict(item) for item in history]
            if cause == "steer":
                instruction = request.get("instruction")
                if not isinstance(instruction, str) or not instruction:
                    raise AdapterFailure("instruction_invalid")
                appended.append({"role": "user", "content": instruction})
            elif cause == "respond":
                response = request.get("response")
                if not isinstance(response, dict):
                    raise AdapterFailure("response_invalid")
                appended.append({"role": "user", "content": _canonical(response)})
            messages.extend(appended)
        return messages, seed_messages, appended

    @staticmethod
    def _provider_messages(messages: list[dict]) -> list[dict]:
        """Convert journal-shaped messages into the provider wire shape."""
        out = []
        for item in messages:
            role = item.get("role")
            if role in ("system", "user"):
                out.append({"role": role, "content": item["content"]})
            elif role == "assistant":
                message = {"role": "assistant", "content": item.get("content", "")}
                if isinstance(item.get("reasoning_content"), str):
                    message["reasoning_content"] = item["reasoning_content"]
                calls = item.get("tool_calls")
                if calls:
                    message["tool_calls"] = [
                        {"id": call["id"], "type": "function",
                         "function": {"name": call["name"],
                                      "arguments": call["arguments"]}}
                        for call in calls
                    ]
                out.append(message)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": item["tool_call_id"],
                            "content": item["content"]})
            else:
                raise AdapterFailure("history_invalid")
        return out

    @staticmethod
    def _validate_history(messages: list[dict], *, has_tools: bool) -> None:
        seen_ids = set()
        for item in messages:
            if not isinstance(item, dict) or not isinstance(item.get("role"), str):
                raise AdapterFailure("history_invalid")
            role = item["role"]
            if role in ("system", "user"):
                if not isinstance(item.get("content"), str):
                    raise AdapterFailure("history_invalid")
            elif role == "assistant":
                if "content" in item and not isinstance(item["content"], (str, type(None))):
                    raise AdapterFailure("history_invalid")
                calls = item.get("tool_calls")
                if calls is None:
                    continue
                if not isinstance(calls, list):
                    raise AdapterFailure("history_invalid")
                if has_tools:
                    reasoning = item.get("reasoning_content")
                    if not isinstance(reasoning, str):
                        raise AdapterFailure("history_missing_reasoning")
                for call in calls:
                    if (not isinstance(call, dict)
                            or not isinstance(call.get("id"), str)
                            or not isinstance(call.get("name"), str)
                            or not isinstance(call.get("arguments"), str)):
                        raise AdapterFailure("history_invalid")
                    if call["id"] in seen_ids:
                        raise AdapterFailure("history_duplicate_tool_call_id")
                    seen_ids.add(call["id"])
            elif role == "tool":
                if (not isinstance(item.get("tool_call_id"), str)
                        or item["tool_call_id"] not in seen_ids
                        or not isinstance(item.get("content"), str)):
                    raise AdapterFailure("history_invalid")
            else:
                raise AdapterFailure("history_invalid")

    @staticmethod
    def _tools(pins: list[dict]):
        if not pins:
            return None, {"by_provider": {}, "by_key": {}, "descriptors": {}}
        by_provider, by_key, descriptors = {}, {}, {}
        for pin in pins:
            if not isinstance(pin, dict) or pin.get("released_at") is not None:
                continue
            key = pin.get("key")
            if not isinstance(key, str) or not key:
                raise AdapterFailure("pin_invalid")
            if key in by_key:
                raise AdapterFailure("duplicate_pin_key")
            descriptor = pin.get("descriptor")
            tool = descriptor.get("tool") if isinstance(descriptor, dict) else None
            if not isinstance(descriptor, dict) or not isinstance(tool, dict):
                raise AdapterFailure("descriptor_invalid")
            version = descriptor.get("v")
            is_v2 = type(version) is int and version == 2
            if is_v2:
                # Provider-side self-consistency only: the approval authority
                # is the dispatcher's match_tool().  The projection below is
                # identical to v1, so v1 request bytes cannot move.
                tool_key = tool.get("key")
                if (not isinstance(tool_key, str) or tool_key != key
                        or tool_key == RESERVED_KEY):
                    raise AdapterFailure("descriptor_invalid")
            elif version != 1:
                raise AdapterFailure("descriptor_invalid")
            parameters = tool.get("parameters")
            if not isinstance(parameters, dict) or parameters.get("type") != "object":
                raise AdapterFailure("descriptor_invalid")
            description = tool.get("description", "")
            if not isinstance(description, str):
                raise AdapterFailure("descriptor_invalid")
            name = _v2_provider_name(key) if is_v2 else _safe_name(key)
            if name in by_provider:
                raise AdapterFailure("tool_name_collision")
            by_provider[name] = key
            by_key[key] = name
            descriptors[key] = {
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        tools = [{"type": "function",
                  "function": {"name": item["name"],
                               "description": item["description"],
                               "parameters": item["parameters"]}}
                 for item in descriptors.values()]
        return tools, {"by_provider": by_provider, "by_key": by_key,
                       "descriptors": descriptors}

    # -- HTTP ------------------------------------------------------------
    def send(self, prepared: PreparedCall) -> tuple[int, bytes, int]:
        payload = _canonical(prepared.body).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": "application/json",
        }
        deadline = self.monotonic() + self.timeout_s
        started = self.monotonic()
        try:
            status, raw = self.transport.post(ENDPOINT, payload, headers, deadline)
        except (ProviderRejected, ProviderUncertain):
            raise
        except (TimeoutError, OSError) as exc:
            raise ProviderUncertain(detail("transport")) from exc
        wall_ms = int(max(0.0, self.monotonic() - started) * 1000)
        if not isinstance(status, int) or not isinstance(raw, (bytes, bytearray)):
            raise ProviderUncertain(detail("transport"))
        return status, bytes(raw), wall_ms

    # -- response classification / mapping ------------------------------
    def interpret(self, prepared: PreparedCall, status: int, raw: bytes,
                  wall_ms: int) -> dict:
        if 300 <= status <= 399:
            return self._unknown("http_3xx", wall_ms)
        if status in (408, 429) or 500 <= status <= 599:
            return self._unknown(f"http_{status}", wall_ms)
        if 400 <= status <= 499:
            return self._failure("http_status", 0, wall_ms)
        if status != 200:
            return self._unknown(f"http_{status}", wall_ms)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._unknown("response_not_json", wall_ms)
        if not isinstance(body, dict):
            return self._unknown("response_not_object", wall_ms)
        if "model" in body and body.get("model") != MODEL:
            return self._unknown("model_mismatch", wall_ms)
        choices = body.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(
                choices[0], dict):
            return self._unknown("choices_invalid", wall_ms)
        choice = choices[0]
        finish = choice.get("finish_reason")
        message = choice.get("message")
        if not isinstance(message, dict):
            return self._unknown("message_invalid", wall_ms)
        usage = body.get("usage")
        prompt, completion = _usage_from_message(usage)
        if not isinstance(usage, dict) or prompt is None or completion is None:
            return self._unknown("usage_invalid", wall_ms)
        tokens = prompt + completion
        content = message.get("content")
        reasoning = message.get("reasoning_content")
        if reasoning is not None and not isinstance(reasoning, str):
            return self._unknown("reasoning_invalid", wall_ms, tokens)
        response_id = body.get("id") if isinstance(body.get("id"), str) else None
        if response_id is not None and not _ID_RE.fullmatch(response_id):
            response_id = None
        metadata = {
            "finish_reason": finish if isinstance(finish, str) else None,
            "model": body.get("model") if isinstance(body.get("model"), str) else None,
            "response_id": response_id,
            "pricing_revision": PRICING_REVISION,
        }
        cost = self._cost(prompt, completion, body)
        if cost is not None:
            metadata.update(cost)
        reply = ProviderReply(
            finish_kind=finish if isinstance(finish, str) else "unknown",
            content=content if isinstance(content, str) else None,
            tool_calls=None,
            prompt_tokens=prompt,
            completion_tokens=completion,
            wall_ms=wall_ms,
            reasoning_content=reasoning,
            response_id=response_id,
            provider_metadata=metadata,
        )
        if finish == "content_filter":
            return self._failure("content_filter", tokens, wall_ms, reply)
        if finish == "tool_calls":
            return self._tool_calls(prepared, message, content, reply, tokens, wall_ms)
        if finish == "stop":
            calls = message.get("tool_calls")
            if calls is not None and not isinstance(calls, list):
                return self._unknown("contradictory_finish", wall_ms, tokens, reply)
            if isinstance(calls, list) and calls:
                return self._unknown("contradictory_finish", wall_ms, tokens, reply)
            if not isinstance(content, str):
                return self._unknown("content_missing", wall_ms, tokens, reply)
            result = {"final": {"text": content}}
            if tokens is not None:
                result["usage"] = {"tokens": tokens, "wall_ms": wall_ms}
            assistant = {"role": "assistant", "content": content}
            if reasoning is not None:
                assistant["reasoning_content"] = reasoning
            return {"class": "success", "result": result, "reply": reply.to_dict(),
                    "assistant_message": assistant, "tool_calls": None,
                    "reason": None}
        if finish in ("length", "aborted", "insufficient_system_resource",
                      "other", None):
            return self._unknown(f"finish_{finish}", wall_ms, tokens, reply)
        return self._unknown("finish_unknown", wall_ms, tokens, reply)

    def _tool_calls(self, prepared: PreparedCall, message: dict, content,
                    reply: ProviderReply, tokens: int | None, wall_ms: int) -> dict:
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            return self._unknown("tool_calls_missing", wall_ms, tokens, reply)
        if len(calls) == 0:
            return self._failure("zero_tool_calls", tokens, wall_ms, reply)
        if len(calls) > _MAX_TOOL_CALLS:
            return self._failure("too_many_tool_calls", tokens, wall_ms, reply)
        if content is not None and not isinstance(content, str):
            return self._unknown("contradictory_content", wall_ms, tokens, reply)
        by_provider = prepared.tool_map["by_provider"]
        parsed, ids = [], set()
        for call in calls:
            if not isinstance(call, dict):
                return self._failure("tool_call_invalid", tokens, wall_ms, reply)
            ident = call.get("id")
            function = call.get("function")
            if (not isinstance(ident, str) or not ident
                    or not isinstance(function, dict)
                    or not isinstance(function.get("name"), str)
                    or not isinstance(function.get("arguments"), str)):
                return self._failure("tool_call_invalid", tokens, wall_ms, reply)
            if ident in ids:
                return self._failure("duplicate_tool_call_id", tokens, wall_ms, reply)
            ids.add(ident)
            name = function["name"]
            key = by_provider.get(name)
            if key is None:
                return self._failure("unknown_tool_name", tokens, wall_ms, reply)
            try:
                args = json.loads(function["arguments"])
            except (json.JSONDecodeError, TypeError):
                return self._failure("invalid_tool_arguments", tokens, wall_ms, reply)
            if not isinstance(args, dict):
                return self._failure("invalid_tool_arguments", tokens, wall_ms, reply)
            parsed.append({"provider_id": ident, "provider_name": name,
                           "key": key, "args": args,
                           "arguments": function["arguments"]})
        result_calls = [{"key": item["key"], "args": item["args"]}
                        for item in parsed]
        result = {"tool_calls": result_calls}
        if isinstance(content, str):
            result["text"] = content
        if tokens is not None:
            result["usage"] = {"tokens": tokens, "wall_ms": wall_ms}
        assistant = {
            "role": "assistant",
            "content": content if isinstance(content, str) else "",
            "tool_calls": [
                {"id": item["provider_id"], "type": "function",
                 "name": item["provider_name"], "arguments": item["arguments"]}
                for item in parsed
            ],
        }
        if reply.reasoning_content is not None:
            assistant["reasoning_content"] = reply.reasoning_content
        return {"class": "success", "result": result, "reply": reply.to_dict(),
                "assistant_message": assistant, "tool_calls": parsed,
                "reason": None}

    def _unknown(self, reason: str, wall_ms: int, tokens: int | None = None,
                 reply: ProviderReply | None = None) -> dict:
        return {"class": "unknown", "result": _usage_result(tokens, wall_ms),
                "reply": reply.to_dict() if reply is not None else None,
                "assistant_message": None, "tool_calls": None, "reason": reason}

    def _failure(self, reason: str, tokens: int | None, wall_ms: int,
                 reply: ProviderReply | None = None) -> dict:
        return {"class": "failure", "result": _usage_result(tokens, wall_ms),
                "reply": reply.to_dict() if reply is not None else None,
                "assistant_message": None, "tool_calls": None, "reason": reason}

    def _cost(self, prompt: int | None, completion: int | None,
              body: dict) -> dict | None:
        if prompt is None or completion is None:
            return None
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        hit = _int_token(usage.get("prompt_cache_hit_tokens"))
        miss = _int_token(usage.get("prompt_cache_miss_tokens"))
        if hit is None or miss is None:
            # The v24 contract only needs a trustworthy total; cache detail is
            # metadata and is reported as absent rather than guessed.
            hit, miss = 0, prompt
        try:
            priced_at = self.clock()
            peak = is_peak(priced_at)
            if peak is None:
                return None
            cost = compute_cost(MODEL, prompt_cache_miss_tokens=miss,
                                prompt_cache_hit_tokens=hit,
                                completion_tokens=completion, at=priced_at)
        except Exception:
            return None
        if cost is None or not isinstance(cost, Decimal) or not cost.is_finite():
            return None
        return {"peak": peak, "cost_usd": str(cost)}
