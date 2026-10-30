"""W2 closed schema-subset gate.

Read-only over ``v24/s13/vectors/schema_v2.json``.  DB-free, Node-free,
socket-free and subprocess-free.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host import tool_schema  # noqa: E402
from v24.host.tool_schema import (  # noqa: E402
    InstanceError,
    SchemaError,
    assert_supported,
    compile_schema,
    schema_metrics,
)

VECTORS = Path(__file__).resolve().parent / "vectors" / "schema_v2.json"


def schema_result(schema, kind="output_schema") -> str:
    try:
        assert_supported(schema, kind=kind)
        return "accepted"
    except SchemaError as exc:
        return exc.reason


def first_error(schema, instance, kind="output_schema"):
    try:
        compile_schema(schema, kind=kind)(instance)
        return ("accepted",)
    except SchemaError as exc:
        return (exc.reason,)
    except InstanceError as exc:
        return (exc.path, exc.rule)


def run_row(case_id: str, row: dict, kind: str) -> None:
    expected = row.get("first", row.get("expected"))
    if "instance" in row:
        result = first_error(row["schema"], row["instance"], kind)
        if isinstance(expected, dict):
            assert result == (expected["path"], expected["rule"]), (case_id, row, result)
        else:
            assert result[-1] == expected or result == (expected,), (case_id, row, result)
        return
    if case_id == "schema.no_default_injection":
        before = json.dumps(row["args"], sort_keys=True)
        result = first_error(row["schema"], row["args"], kind)
        assert result == ("accepted",), (case_id, result)
        assert json.dumps(row["args"], sort_keys=True) == before
        return
    result = schema_result(row["schema"], kind)
    assert result == expected, (case_id, row, result)


def first_error_call(compiled, instance):
    try:
        compiled(instance)
        return ("accepted",)
    except InstanceError as exc:
        return (exc.path, exc.rule)


def main() -> int:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = document["cases"]
    assert document["format"] == "v24-tool-plugin-abi-w1-vectors-1"
    assert len(cases) == 9

    by_id = {case["id"]: case for case in cases}
    assert set(by_id) == {
        "schema.keyword_allow_deny",
        "schema.type_nullable",
        "schema.required_additional_items",
        "schema.enum_json_distinct",
        "schema.schema_bounds",
        "schema.instance_bounds",
        "schema.root_parameters",
        "schema.error_path_order",
        "schema.no_default_injection",
    }

    # 1. Thirteen allowed keywords, 29 denied, 13 malformed allowed forms.
    keyword_case = by_id["schema.keyword_allow_deny"]["input"]
    assert len(keyword_case["allowed"]) == 13
    assert len(keyword_case["denied"]) == 29
    assert len(keyword_case["invalid_allowed"]) == 13
    for group in ("allowed", "denied", "invalid_allowed"):
        for row in keyword_case[group]:
            result = schema_result(row["schema"], row.get("kind", "output_schema"))
            assert result == row["expected"], (row["keyword"], result, row)
    assert {row["keyword"] for row in keyword_case["allowed"]} == set(
        tool_schema.ALLOWED_KEYWORDS
    )
    assert {row["keyword"] for row in keyword_case["denied"]} == set(
        tool_schema.DENIED_KEYWORDS
    )

    # 2. Remaining eight cases, each with its own input shape.
    for case_id, case in by_id.items():
        if case_id == "schema.keyword_allow_deny":
            continue
        rows = case["input"]
        if case_id == "schema.enum_json_distinct":
            for row in rows:
                result = schema_result({"enum": row["values"]})
                assert result == row["expected"], (case_id, row, result)
            continue
        if case_id == "schema.root_parameters":
            for row in rows:
                result = schema_result(row["schema"], row["kind"])
                assert result == row["expected"], (case_id, row, result)
            continue
        if case_id == "schema.no_default_injection":
            run_row(case_id, rows, "parameters")
            continue
        if isinstance(rows, list):
            for row in rows:
                run_row(case_id, row, "output_schema")
        else:
            run_row(case_id, rows, rows.get("kind", "output_schema"))

    # 3. Structural bounds: measured, not only accepted/rejected.
    bounds = {row["id"]: row for row in by_id["schema.schema_bounds"]["input"]}
    assert schema_metrics(bounds["depth_16"]["schema"])["depth"] == 16
    assert schema_metrics(bounds["nodes_256"]["schema"])["nodes"] == 256
    assert schema_metrics(bounds["properties_128"]["schema"])["max_properties"] == 128
    assert schema_metrics(bounds["enum_64"]["schema"])["max_enum"] == 64
    for row in bounds.values():
        assert schema_result(row["schema"]) == row["expected"], row["id"]

    # 4. JSON-distinct enum: key order is irrelevant, array order is relevant,
    # and true/1/"1"/null are distinct.
    assert schema_result({"enum": [{"a": 1, "b": 2}, {"b": 2, "a": 1}]}
                         ) == "duplicate_enum"
    assert schema_result({"enum": [[1, 2], [2, 1]]}) == "accepted"
    assert schema_result({"enum": [True, 1, "1", None]}) == "accepted"

    # 5. First-error rule order is fixed at each node.
    assert first_error({"type": "string", "enum": ["a"], "minLength": 5},
                       "") == ("$", "enum")
    string_schema = {"type": "string", "minLength": 2, "maxLength": 4}
    assert first_error(string_schema, "") == ("$", "min_length")
    assert first_error(string_schema, "abcde") == ("$", "max_length")
    integer_schema = {"type": "integer", "minimum": 1, "maximum": 3}
    assert first_error(integer_schema, 0) == ("$", "minimum")
    assert first_error(integer_schema, 4) == ("$", "maximum")
    array_schema = {"type": "array", "items": {}, "minItems": 1, "maxItems": 2}
    assert first_error(array_schema, []) == ("$", "min_items")
    assert first_error(array_schema, [1, 2, 3]) == ("$", "max_items")

    # 6. Path spelling: identifiers, bracketed keys, empty key, array index.
    object_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {"type": "array", "items": {"type": "string"}},
            "": {"type": "string"},
            "a-b": {"type": "string"},
        },
    }
    assert first_error(object_schema, {"items": [0]}) == ("$.items[0]", "type")
    assert first_error(object_schema, {"": 0}) == ('$[""]', "type")
    assert first_error(object_schema, {"a-b": 0}) == ('$["a-b"]', "type")

    # 7. Nullable unions do not let the null branch trigger other constraints.
    nullable = {"type": ["integer", "null"], "minimum": 1}
    assert first_error(nullable, None) == ("accepted",)
    assert first_error(nullable, 1) == ("accepted",)
    assert first_error(nullable, 0) == ("$", "minimum")
    assert first_error(nullable, "1") == ("$", "type")

    # 8. Compiled closures are reusable, deep-frozen and never process-cached.
    mutable = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }
    compiled = compile_schema(mutable, kind="parameters")
    mutable["properties"]["x"]["type"] = "integer"
    assert first_error_call(compiled, {"x": 1}) == ("$.x", "type")
    assert compiled({"x": "ok"}) is None
    assert compile_schema(mutable, kind="parameters") is not \
        compile_schema(mutable, kind="parameters")

    # 9. Parameters root requirements are not silently relaxed.
    assert schema_result({"type": "object", "additionalProperties": False},
                         "parameters") == "accepted"
    assert schema_result({}, "parameters") == "unsupported_schema"
    assert schema_result({}, "output_schema") == "accepted"
    assert schema_result({"type": "object"}, "parameters") == "unsupported_schema"

    print(
        "[passed] W2 schema contract; cases=9; "
        "first_error_order=frozen; defaults_injected=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
