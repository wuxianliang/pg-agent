"""Pure canonical and JSON helpers shared by v24 host contracts.

This module is deliberately a leaf: it imports only the Python standard
library and performs no I/O. PostgreSQL jsonb text canonicalization remains
separate from the compact JSON form (``J``) used by W2 budgets and digests.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

SAFE_INTEGER_MAX = 2**53 - 1


class CanonicalError(ValueError):
    """A value or JSON document violates a canonicalization contract."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RegistryError(RuntimeError):
    """An approved adapter entry is structurally invalid or ambiguous."""


class _FrozenDict(dict):
    """A JSON object that cannot be mutated after registry construction."""

    def _readonly(self, *args, **kwargs):
        raise TypeError("approved adapter parameters are immutable")

    __setitem__ = _readonly
    __delitem__ = _readonly
    __ior__ = _readonly
    clear = _readonly
    pop = _readonly
    popitem = _readonly
    setdefault = _readonly
    update = _readonly


class _FrozenList(list):
    """A JSON array that cannot be mutated after registry construction."""

    def _readonly(self, *args, **kwargs):
        raise TypeError("approved adapter parameters are immutable")

    __setitem__ = _readonly
    __delitem__ = _readonly
    __iadd__ = _readonly
    __imul__ = _readonly
    append = _readonly
    clear = _readonly
    extend = _readonly
    insert = _readonly
    pop = _readonly
    remove = _readonly
    reverse = _readonly
    sort = _readonly


def _freeze(value):
    """Deep-freeze the JSON-shaped ``parameters`` field."""
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def pg_jsonb_text(value) -> str:
    """Render the exact text PostgreSQL ``jsonb::text`` produces."""
    if isinstance(value, dict):
        items = sorted(value.items(),
                       key=lambda kv: (len(kv[0].encode("utf-8")),
                                       kv[0].encode("utf-8")))
        return "{" + ", ".join(
            f"{_quote(key)}: {pg_jsonb_text(item)}" for key, item in items
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(pg_jsonb_text(item) for item in value) + "]"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return json.dumps(value, allow_nan=False)
    if isinstance(value, str):
        return _quote(value)
    raise TypeError(f"unsupported JSON value in descriptor: {type(value)!r}")


def descriptor_digest(descriptor: dict) -> str:
    """SHA-256 hex of the PostgreSQL canonical descriptor text."""
    if not isinstance(descriptor, dict):
        raise RegistryError("descriptor must be an object")
    return hashlib.sha256(pg_jsonb_text(descriptor).encode("utf-8")).hexdigest()


def _scalar(text: str) -> str:
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        raise CanonicalError("lone_surrogate")
    return text


def _safe_integer(value: int) -> str:
    if abs(value) > SAFE_INTEGER_MAX:
        raise CanonicalError("unsafe_integer")
    return str(value)


def _compact_encode(value: Any) -> str:
    """Encode ``J`` with an explicit stack, not Python call recursion.

    A finite JSON document is legal regardless of its depth; a recursive
    encoder would reject deep-but-valid values once Python's recursion limit
    is reached.  The explicit stack also makes cycle detection precise:
    ``circular_reference`` instead of an out-of-context ``RecursionError``.
    Output bytes are identical to the recursive form.
    """
    out: list[str] = []
    active: set[int] = set()
    stack: list[tuple[str, Any]] = [("value", value)]
    while stack:
        tag, item = stack.pop()
        if tag == "text":
            out.append(item)
            continue
        if tag == "leave":
            active.discard(item)
            continue
        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise CanonicalError("circular_reference")
            active.add(identity)
            keys = []
            for key in item:
                if not isinstance(key, str):
                    raise CanonicalError("non_string_key")
                _scalar(key)
                try:
                    encoded = key.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise CanonicalError("lone_surrogate") from exc
                keys.append((encoded, key))
            keys.sort(key=lambda entry: entry[0])
            stack.append(("leave", identity))
            stack.append(("text", "}"))
            for index in range(len(keys) - 1, -1, -1):
                key = keys[index][1]
                stack.append(("value", item[key]))
                stack.append(("text", ":"))
                stack.append(("text", _quote(key)))
                if index:
                    stack.append(("text", ","))
            stack.append(("text", "{"))
        elif isinstance(item, list):
            identity = id(item)
            if identity in active:
                raise CanonicalError("circular_reference")
            active.add(identity)
            stack.append(("leave", identity))
            stack.append(("text", "]"))
            for index in range(len(item) - 1, -1, -1):
                stack.append(("value", item[index]))
                if index:
                    stack.append(("text", ","))
            stack.append(("text", "["))
        elif isinstance(item, str):
            _scalar(item)
            out.append(_quote(item))
        elif item is True:
            out.append("true")
        elif item is False:
            out.append("false")
        elif item is None:
            out.append("null")
        elif type(item) is int:
            out.append(_safe_integer(item))
        elif isinstance(item, float):
            raise CanonicalError("non_integer_number")
        else:
            raise CanonicalError("unsupported_json_value")
    return "".join(out)


def compact_json(value: Any) -> bytes:
    """Return W2's compact, scalar-safe JSON bytes (the canonical ``J``)."""
    try:
        return _compact_encode(value).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalError("lone_surrogate") from exc


def escaped_len(text: str) -> int:
    """Return the UTF-8 byte length of a JSON string's escaped payload."""
    if not isinstance(text, str):
        raise CanonicalError("expected_string")
    return len(compact_json(text)) - 2


def strict_loads(raw: str | bytes) -> Any:
    """Decode strict JSON while preserving lexical numeric and key checks."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "strict")
    elif not isinstance(raw, str):
        raise CanonicalError("invalid_input")

    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise CanonicalError("duplicate_key")
            obj[_scalar(key)] = value
        return obj

    def integer(token):
        if token == "-0":
            raise CanonicalError("negative_zero")
        # Reject by digit count before ``int()``: Python caps decimal string
        # conversion at 4300 digits and would otherwise leak a bare
        # ``ValueError``.  Any 17-digit magnitude already exceeds 2**53 - 1.
        digits = token[1:] if token.startswith("-") else token
        if len(digits) > len(str(SAFE_INTEGER_MAX)):
            raise CanonicalError("unsafe_integer")
        value = int(token)
        _safe_integer(value)
        return value

    def no_float(token):
        raise CanonicalError("non_integer_number")

    def no_constant(token):
        raise CanonicalError("non_json_constant")

    value = json.loads(raw, object_pairs_hook=pairs, parse_int=integer,
                       parse_float=no_float, parse_constant=no_constant)

    def visit(item):
        if isinstance(item, str):
            _scalar(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                _scalar(key)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return value
