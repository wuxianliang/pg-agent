"""Descriptor v2 validation for the v24 tool/plugin ABI.

``validate_descriptor`` enforces the closed descriptor shape, the closed schema
subset for both ``parameters`` and ``output_schema``, the renderer identity, and
the PostgreSQL byte/depth bounds.  It is pure: it reads no clock, file, database
or network, never mutates its input, and returns a deep-frozen copy.

The module sits above ``canonical``, ``tool_schema`` and ``renderers`` and is
not imported by any existing host runtime module during W2.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .canonical import (
    SAFE_INTEGER_MAX,
    CanonicalError,
    _FrozenDict,
    _freeze,
    compact_json,
    descriptor_digest,
    pg_jsonb_text,
    strict_loads,
)
from .renderers import RENDERERS, RendererRegistry
from .tool_schema import SchemaError, assert_supported

KEY_RE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
RESERVED_KEY = "agent.spawn"

DESCRIPTOR_REASONS = frozenset({
    "invalid_descriptor",
    "descriptor_key_mismatch",
    "renderer_not_approved",
    "renderer_digest_mismatch",
})

TOP_KEYS = frozenset({"v", "tool"})
TOOL_KEYS = frozenset({
    "key", "description", "parameters", "output_schema", "render", "limits",
    "concurrency", "replay_class", "annotations",
})
RENDER_KEYS = frozenset({"id", "version", "digest"})
LIMIT_KEYS = (
    "timeout_ms",
    "max_args_bytes",
    "max_value_bytes",
    "max_content_bytes",
    "max_meta_bytes",
)
LIMIT_RANGES = {
    "timeout_ms": (1, 25000),
    "max_args_bytes": (1, 65536),
    "max_value_bytes": (1, 49152),
    "max_content_bytes": (1, 65536),
    "max_meta_bytes": (2, 16384),
}
ANNOTATION_KEYS = frozenset({
    "read_only", "destructive", "idempotent", "open_world",
})
CONCURRENCY = frozenset({"parallel", "exclusive"})
REPLAY_CLASSES = frozenset({"read_only", "idempotent", "mutating", "external"})

MAX_DESCRIPTOR_DEPTH = 16
MAX_DESCRIPTOR_PG_BYTES = 16384


class DescriptorError(ValueError):
    """A descriptor fails the v2 closed contract.

    ``reason`` is one of :data:`DESCRIPTOR_REASONS`; no other value escapes
    ``validate_descriptor``.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _invalid() -> None:
    raise DescriptorError("invalid_descriptor")


def _is_safe_integer(value: Any) -> bool:
    return type(value) is int and abs(value) <= SAFE_INTEGER_MAX


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def descriptor_depth(value: Any) -> int:
    """Return the deepest nested-container depth of a JSON value.

    The root container is depth 1 and each nested object/array adds one.  Scalar
    values are depth 0.  This is the measure used by the descriptor's
    ``depth_cap``; it is deliberately not the schema-node count.
    """
    if isinstance(value, dict):
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return 0
    deepest = 0
    for child in children:
        if isinstance(child, (dict, list)):
            deepest = max(deepest, descriptor_depth(child))
    return deepest + 1


def descriptor_pg_bytes(descriptor: Any) -> int:
    """Return the UTF-8 byte length of the PostgreSQL ``jsonb::text`` form."""
    return len(pg_jsonb_text(descriptor).encode("utf-8"))


def parse_descriptor(raw: str | bytes) -> dict:
    """Strictly decode a descriptor document without leaking raw text.

    Lexical checks (duplicate keys, ``-0``, floats/exponents, ``NaN`` and
    ``Infinity``, unsafe integers, lone surrogates) are preserved by
    ``canonical.strict_loads``.  Every decode failure maps to a single
    ``invalid_descriptor`` reason.
    """
    try:
        value = strict_loads(raw)
    except (CanonicalError, json.JSONDecodeError, UnicodeDecodeError):
        _invalid()
    if not isinstance(value, dict):
        _invalid()
    return value


def _check_closed_set(value: Any, expected: frozenset[str]) -> dict:
    if not isinstance(value, dict):
        _invalid()
    if set(value) != expected:
        _invalid()
    return value


def _check_key(key: Any) -> str:
    if not isinstance(key, str):
        _invalid()
    if "\x00" in key or KEY_RE.fullmatch(key) is None:
        _invalid()
    if key == RESERVED_KEY:
        _invalid()
    return key


def _check_description(description: Any) -> str:
    if not isinstance(description, str) or "\x00" in description:
        _invalid()
    length = _utf8_len(description)
    if not 1 <= length <= 4096:
        _invalid()
    return description


def _check_render(render: Any) -> None:
    _check_closed_set(render, RENDER_KEYS)
    renderer_id = render["id"]
    if not isinstance(renderer_id, str) or KEY_RE.fullmatch(renderer_id) is None:
        _invalid()
    version = render["version"]
    if not _is_safe_integer(version) or not 1 <= version <= SAFE_INTEGER_MAX:
        _invalid()
    digest = render["digest"]
    if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
        _invalid()


def _check_limits(limits: Any) -> None:
    _check_closed_set(limits, frozenset(LIMIT_KEYS))
    for name in LIMIT_KEYS:
        value = limits[name]
        low, high = LIMIT_RANGES[name]
        if not _is_safe_integer(value) or not low <= value <= high:
            _invalid()


def _check_enums(tool: dict) -> None:
    if tool["concurrency"] not in CONCURRENCY:
        _invalid()
    if tool["replay_class"] not in REPLAY_CLASSES:
        _invalid()


def _check_annotations(tool: dict) -> None:
    annotations = _check_closed_set(tool["annotations"], ANNOTATION_KEYS)
    for name in ANNOTATION_KEYS:
        if type(annotations[name]) is not bool:
            _invalid()


def _check_implications(tool: dict) -> None:
    annotations = tool["annotations"]
    if tool["replay_class"] == "read_only":
        if annotations["read_only"] is not True:
            _invalid()
        if annotations["destructive"] is not False:
            _invalid()
        if annotations["idempotent"] is not True:
            _invalid()
    if annotations["read_only"] is True and annotations["destructive"] is not False:
        _invalid()
    if tool["concurrency"] == "parallel" and annotations["read_only"] is not True:
        _invalid()


def validate_descriptor(
    descriptor: Any,
    *,
    provide_key: str | None = None,
    render_registry: RendererRegistry = RENDERERS,
) -> _FrozenDict:
    """Validate a descriptor v2 document and return a deep-frozen copy.

    Validation order is fixed and part of the contract.  Only the four
    :data:`DESCRIPTOR_REASONS` escape; schema, canonicalization and container
    errors are normalized to ``invalid_descriptor``.
    """
    try:
        return _validate_descriptor(
            descriptor,
            provide_key=provide_key,
            render_registry=render_registry,
        )
    except DescriptorError:
        raise
    except (SchemaError, CanonicalError, TypeError, ValueError,
            AttributeError, UnicodeError, RecursionError):
        raise DescriptorError("invalid_descriptor") from None


def _validate_descriptor(
    descriptor: Any,
    *,
    provide_key: str | None,
    render_registry: RendererRegistry,
) -> _FrozenDict:
    # 1. Top-level object and closed set.
    _check_closed_set(descriptor, TOP_KEYS)

    # 2. Protocol version; bool is not an integer.
    version = descriptor["v"]
    if type(version) is not int or version != 2:
        _invalid()

    # 3. tool object and closed set.
    tool = _check_closed_set(descriptor["tool"], TOOL_KEYS)

    # 4. key.
    key = _check_key(tool["key"])

    # 5. description.
    _check_description(tool["description"])

    # 6. parameters.
    assert_supported(tool["parameters"], kind="parameters")

    # 7. output schema.
    assert_supported(tool["output_schema"], kind="output_schema")

    # 8. render identity shape.
    _check_render(tool["render"])

    # 9. limits shape and ranges.
    _check_limits(tool["limits"])

    # 10. enum fields.
    _check_enums(tool)

    # 11. annotations shape.
    _check_annotations(tool)

    # 12. annotation implications.
    _check_implications(tool)

    # 13. container depth.
    if descriptor_depth(descriptor) > MAX_DESCRIPTOR_DEPTH:
        _invalid()

    # 14. Full safe-integer / Unicode / JSON-shape scan.  Lexical checks for
    # parsed input already ran in parse_descriptor; this covers in-process
    # dicts and non-string keys.
    compact_json(descriptor)

    # 15. PostgreSQL canonical size.
    if descriptor_pg_bytes(descriptor) > MAX_DESCRIPTOR_PG_BYTES:
        _invalid()

    # 16. provide key identity.
    if provide_key is not None and provide_key != key:
        raise DescriptorError("descriptor_key_mismatch")

    # 17. renderer identity.
    render = tool["render"]
    renderer = render_registry.by_id(render["id"], render["version"])
    if renderer is None:
        raise DescriptorError("renderer_not_approved")
    if renderer.ref.digest != render["digest"]:
        raise DescriptorError("renderer_digest_mismatch")

    return _freeze(descriptor)


__all__ = [
    "DESCRIPTOR_REASONS",
    "DescriptorError",
    "descriptor_depth",
    "descriptor_digest",
    "descriptor_pg_bytes",
    "parse_descriptor",
    "validate_descriptor",
]
