"""Closed, deterministic JSON Schema subset for v24 tool contracts.

The host accepts exactly thirteen keywords.  Anything else is an
``unsupported_schema`` at approval time; the host never guesses at JSON Schema
semantics outside this subset.  Validation reports only the first error, in a
fixed rule order, so two implementations of the same descriptor agree on the
error path and rule.

This module is a leaf above ``canonical``: it performs no I/O, reads no clock,
and has no process-level cache.  ``compile_schema`` returns a closure that the
caller (the W3 approval object) owns and may reuse across instances.
"""
from __future__ import annotations

from typing import Any, Callable

from .canonical import (
    SAFE_INTEGER_MAX,
    CanonicalError,
    _freeze,
    compact_json,
)

ALLOWED_KEYWORDS = frozenset({
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "enum",
    "description",
})

# The 29 explicitly rejected keywords are documented in the W2 plan; they are
# rejected by the closed-set check above.  Keeping the list here makes the
# rejection intentional rather than incidental.
DENIED_KEYWORDS = frozenset({
    "$ref", "$defs", "definitions", "$schema", "$id", "oneOf", "anyOf",
    "allOf", "not", "if", "then", "else", "pattern", "format", "default",
    "const", "number", "patternProperties", "propertyNames", "uniqueItems",
    "minProperties", "maxProperties", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "contentEncoding", "readOnly", "writeOnly", "examples",
})

JSON_TYPES = frozenset({
    "object", "array", "string", "integer", "boolean", "null",
})

_TYPE_KEYWORDS = {
    "minItems": "array",
    "maxItems": "array",
    "minLength": "string",
    "maxLength": "string",
    "minimum": "integer",
    "maximum": "integer",
}

MAX_DEPTH = 16
MAX_NODES = 256
MAX_PROPERTIES = 128
MAX_ENUM = 64

KINDS = frozenset({"parameters", "output_schema"})


class SchemaError(ValueError):
    """A schema leaves the closed subset.

    ``reason`` is ``unsupported_schema`` or ``duplicate_enum``.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class InstanceError(ValueError):
    """An instance violates a schema that already passed ``assert_supported``."""

    def __init__(self, path: str, rule: str):
        self.path = path
        self.rule = rule
        super().__init__(f"{path}: {rule}")


def _unsupported() -> None:
    raise SchemaError("unsupported_schema")


def _is_safe_integer(value: Any, *, nonnegative: bool = False) -> bool:
    return (
        type(value) is int
        and abs(value) <= SAFE_INTEGER_MAX
        and (not nonnegative or value >= 0)
    )


def _declared_types(schema: dict) -> frozenset[str] | None:
    if "type" not in schema:
        return None
    declared = schema["type"]
    if isinstance(declared, str):
        if declared not in JSON_TYPES:
            _unsupported()
        return frozenset({declared})
    if not isinstance(declared, list):
        _unsupported()
    if not 2 <= len(declared) <= 4:
        _unsupported()
    if any(not isinstance(item, str) or item not in JSON_TYPES for item in declared):
        _unsupported()
    if len(set(declared)) != len(declared):
        _unsupported()
    return frozenset(declared)


class _Metrics:
    __slots__ = ("nodes", "depth", "max_properties", "max_enum")

    def __init__(self) -> None:
        self.nodes = 0
        self.depth = 0
        self.max_properties = 0
        self.max_enum = 0


def _check_schema(schema: Any, depth: int, metrics: _Metrics) -> None:
    if not isinstance(schema, dict):
        _unsupported()
    if any(not isinstance(key, str) for key in schema):
        _unsupported()
    if not ALLOWED_KEYWORDS.issuperset(schema):
        _unsupported()

    metrics.nodes += 1
    metrics.depth = max(metrics.depth, depth)
    if depth > MAX_DEPTH or metrics.nodes > MAX_NODES:
        _unsupported()

    declared = _declared_types(schema)

    if "description" in schema and not isinstance(schema["description"], str):
        _unsupported()

    if "properties" in schema:
        properties = schema["properties"]
        if not isinstance(properties, dict):
            _unsupported()
        if any(not isinstance(name, str) for name in properties):
            _unsupported()
        if len(properties) > MAX_PROPERTIES:
            _unsupported()
        if declared is not None and "object" not in declared:
            _unsupported()
        metrics.max_properties = max(metrics.max_properties, len(properties))
        for child in properties.values():
            _check_schema(child, depth + 1, metrics)

    if "required" in schema:
        required = schema["required"]
        if not isinstance(required, list):
            _unsupported()
        if any(not isinstance(name, str) for name in required):
            _unsupported()
        if len(set(required)) != len(required):
            _unsupported()
        if "properties" not in schema:
            _unsupported()
        properties = schema["properties"]
        if any(name not in properties for name in required):
            _unsupported()

    if "additionalProperties" in schema:
        if type(schema["additionalProperties"]) is not bool:
            _unsupported()
        if declared is not None and "object" not in declared:
            _unsupported()
    if declared is not None and "object" in declared:
        if "additionalProperties" not in schema:
            _unsupported()

    if "items" in schema:
        if not isinstance(schema["items"], dict):
            _unsupported()
        if declared is not None and "array" not in declared:
            _unsupported()
        _check_schema(schema["items"], depth + 1, metrics)
    if declared is not None and "array" in declared:
        if "items" not in schema:
            _unsupported()

    for keyword, needed in _TYPE_KEYWORDS.items():
        if keyword not in schema:
            continue
        nonnegative = keyword not in ("minimum", "maximum")
        if not _is_safe_integer(schema[keyword], nonnegative=nonnegative):
            _unsupported()
        if declared is not None and needed not in declared:
            _unsupported()

    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_ENUM:
            _unsupported()
        metrics.max_enum = max(metrics.max_enum, len(values))
        try:
            encoded = [compact_json(item) for item in values]
        except CanonicalError:
            _unsupported()
        if len(set(encoded)) != len(encoded):
            raise SchemaError("duplicate_enum")


def assert_supported(schema: Any, *, kind: str) -> None:
    """Reject anything outside the closed schema subset.

    ``kind`` has no default: a ``parameters`` root must be an object with
    ``additionalProperties:false``, and that requirement must not be skipped
    by an output-schema caller.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown schema kind: {kind!r}")
    if not isinstance(schema, dict):
        _unsupported()
    metrics = _Metrics()
    _check_schema(schema, 1, metrics)
    if kind == "parameters":
        if schema.get("type") != "object":
            _unsupported()
        if schema.get("additionalProperties") is not False:
            _unsupported()


def schema_metrics(schema: Any) -> dict:
    """Measure the closed-subset structure of a schema.

    The result is ``{depth, nodes, max_properties, max_enum}`` measured over
    schema nodes only: root is one node and each ``properties.<k>`` or
    ``items`` child adds one.  ``enum`` values are values, not schema nodes.
    """
    if not isinstance(schema, dict):
        _unsupported()
    metrics = _Metrics()
    _check_schema(schema, 1, metrics)
    return {
        "depth": metrics.depth,
        "nodes": metrics.nodes,
        "max_properties": metrics.max_properties,
        "max_enum": metrics.max_enum,
    }


def _path(parent: str, name: str) -> str:
    identifier = (
        bool(name)
        and name[0].isascii()
        and (name[0].isalpha() or name[0] == "_")
        and all(ch.isascii() and (ch.isalnum() or ch == "_") for ch in name)
    )
    if identifier:
        return f"{parent}.{name}"
    return parent + "[" + compact_json(name).decode("utf-8") + "]"


def _matches(instance: Any, name: str) -> bool:
    if name == "object":
        return isinstance(instance, dict)
    if name == "array":
        return isinstance(instance, list)
    if name == "string":
        return isinstance(instance, str)
    if name == "integer":
        return type(instance) is int and abs(instance) <= SAFE_INTEGER_MAX
    if name == "boolean":
        return type(instance) is bool
    return instance is None


def _sorted_keys(mapping: dict) -> list[str]:
    return sorted(mapping, key=lambda name: name.encode("utf-8"))


def _validate_instance(schema: dict, instance: Any, path: str) -> None:
    declared = _declared_types(schema)

    if declared is not None and not any(
        _matches(instance, name) for name in declared
    ):
        raise InstanceError(path, "type")

    is_object = isinstance(instance, dict) and (
        declared is None or "object" in declared
    )
    is_array = isinstance(instance, list) and (
        declared is None or "array" in declared
    )
    is_string = isinstance(instance, str) and (
        declared is None or "string" in declared
    )
    is_integer = type(instance) is int and (
        declared is None or "integer" in declared
    )

    if is_object:
        for name in schema.get("required", []):
            if name not in instance:
                raise InstanceError(_path(path, name), "required")
        if schema.get("additionalProperties") is False:
            properties = schema.get("properties", {})
            for name in _sorted_keys(instance):
                if name not in properties:
                    raise InstanceError(_path(path, name), "additional")

    if "enum" in schema:
        try:
            encoded = compact_json(instance)
            if all(encoded != compact_json(item) for item in schema["enum"]):
                raise InstanceError(path, "enum")
        except CanonicalError:
            raise InstanceError(path, "enum") from None

    if is_string:
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise InstanceError(path, "min_length")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise InstanceError(path, "max_length")

    if is_integer:
        if "minimum" in schema and instance < schema["minimum"]:
            raise InstanceError(path, "minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise InstanceError(path, "maximum")

    if is_array:
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise InstanceError(path, "min_items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise InstanceError(path, "max_items")

    if is_object:
        properties = schema.get("properties", {})
        for name in _sorted_keys(instance):
            if name in properties:
                _validate_instance(properties[name], instance[name],
                                   _path(path, name))

    if is_array and "items" in schema:
        for index, item in enumerate(instance):
            _validate_instance(schema["items"], item, f"{path}[{index}]")


def compile_schema(schema: Any, *, kind: str) -> Callable[[Any], None]:
    """Validate a schema and return a reusable instance-checking closure.

    The closure captures a deep-frozen copy of the schema.  There is no
    process-level cache: the caller owns the closure for the lifetime of its
    approval object.
    """
    assert_supported(schema, kind=kind)
    frozen = _freeze(schema)

    def compiled(instance: Any) -> None:
        _validate_instance(frozen, instance, "$")

    return compiled


def validate(schema: Any, instance: Any) -> None:
    """Validate one instance against an output-schema-shaped schema."""
    compile_schema(schema, kind="output_schema")(instance)
