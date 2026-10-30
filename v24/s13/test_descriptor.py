"""W2 descriptor contract gate: canonical bytes, closed sets, render identity.

Read-only over ``v24/s13/vectors/descriptor_v2.json``.  DB-free, Node-free,
socket-free and subprocess-free.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host import canonical, descriptor, renderers  # noqa: E402

VECTORS = Path(__file__).resolve().parent / "vectors" / "descriptor_v2.json"
SENTINEL = "__W2_RAW_JSON_SENTINEL_7f3c1d__"


def expect_reason(fn, reason):
    try:
        fn()
    except descriptor.DescriptorError as exc:
        assert exc.reason == reason, (reason, exc.reason)
        return exc.reason
    raise AssertionError(f"expected DescriptorError({reason!r})")


def expect_canonical(fn, reason):
    try:
        fn()
    except canonical.CanonicalError as exc:
        assert exc.reason == reason, (reason, exc.reason)
        return
    raise AssertionError(f"expected CanonicalError({reason!r})")


def _path_parts(path: str) -> list[str]:
    return [] if path == "$" else path.split(".")


def _materialize(value):
    if (
        isinstance(value, dict)
        and set(value) == {"count", "repeat"}
        and type(value["count"]) is int
        and isinstance(value["repeat"], str)
    ):
        return value["repeat"] * value["count"]
    return value


def _apply(base: dict, row: dict) -> dict:
    document = copy.deepcopy(base)
    parts = _path_parts(row["path"])
    operation = row["operation"]
    if operation == "delete":
        parent = document
        for part in parts[:-1]:
            parent = parent[part]
        del parent[parts[-1]]
    elif operation == "replace":
        parent = document
        for part in parts[:-1]:
            parent = parent[part]
        parent[parts[-1]] = _materialize(row["value"])
    elif operation == "add_extra":
        parent = document
        for part in parts:
            parent = parent[part]
        parent[row["key"]] = row["value"]
    else:
        raise AssertionError(f"unknown operation {operation!r}")
    return document


def _parse_raw(base: dict, row: dict) -> dict:
    document = copy.deepcopy(base)
    parts = _path_parts(row["path"])
    parent = document
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = SENTINEL
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    needle = json.dumps(SENTINEL)
    assert raw.count(needle) == 1
    raw = raw.replace(needle, row["raw_json"])
    return descriptor.parse_descriptor(raw.encode("utf-8"))


def _tampered_registry(digest: str):
    read = renderers.RENDERERS.by_id("v24.fs.read.text", 1)
    assert read is not None
    ref = renderers.RendererRef(read.ref.id, read.ref.version, digest)
    return renderers.RendererRegistry(
        (renderers.Renderer(ref, read.projection, read.fn),)
    )


def main() -> int:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = document["cases"]
    assert document["format"] == "v24-tool-plugin-abi-w1-vectors-1"
    assert len(cases) == 16

    bases = {case["input_id"]: case["input"] for case in cases
             if case["kind"] == "byte"}
    assert len(bases) == 9

    reasons_seen = set()
    byte_cases = 0
    canonical_cases = 0

    # 1. Nine byte cases: six PostgreSQL canonical forms and three full
    # descriptors.  Expected bytes come only from the frozen vector.
    for case in cases:
        if case["kind"] != "byte":
            continue
        byte_cases += 1
        if case["id"].startswith("canon."):
            canonical_cases += 1
            text = canonical.pg_jsonb_text(case["input"])
            encoded = text.encode("utf-8")
            assert text == case["expected_text"], case["id"]
            assert encoded.hex() == case["expected_hex"], case["id"]
            assert len(encoded) == case["expected_length"], case["id"]
            assert hashlib.sha256(encoded).hexdigest() == case["expected_sha256"], case["id"]
            continue

        before = copy.deepcopy(case["input"])
        frozen = descriptor.validate_descriptor(case["input"])
        assert case["input"] == before, f"{case['id']}: input mutated"
        assert isinstance(frozen, canonical._FrozenDict), case["id"]
        try:
            frozen["tool"] = {}
        except TypeError:
            pass
        else:
            raise AssertionError(f"{case['id']}: accepted descriptor is mutable")

        text = canonical.pg_jsonb_text(frozen)
        encoded = text.encode("utf-8")
        assert text == case["expected_text"], case["id"]
        assert encoded.hex() == case["expected_hex"], case["id"]
        assert len(encoded) == case["expected_length"], case["id"]
        assert hashlib.sha256(encoded).hexdigest() == case["expected_sha256"], case["id"]
        assert canonical.descriptor_digest(frozen) == case["descriptor_digest"], case["id"]
        manifest = renderers.RENDERERS.by_id(
            frozen["tool"]["render"]["id"], frozen["tool"]["render"]["version"]
        )
        assert manifest is not None
        assert manifest.ref.digest == frozen["tool"]["render"]["digest"]

    assert byte_cases == 9 and canonical_cases == 6

    # 2. Seven table cases.  Mutations are applied to a test-side deep copy;
    # raw_json is spliced back into JSON text and must go through strict parse.
    table_cases = 0
    for case in cases:
        if case["kind"] != "table":
            continue
        table_cases += 1
        for row in case["input"]:
            base = copy.deepcopy(bases[row["base_ref"]]) if "base_ref" in row else \
                copy.deepcopy(row["descriptor"])
            if "operation" in row:
                candidate = _apply(base, row)
            else:
                candidate = base
            if "raw_json" in row:
                try:
                    candidate = _parse_raw(base, row)
                except descriptor.DescriptorError as exc:
                    reason = exc.reason
                    assert reason in descriptor.DESCRIPTOR_REASONS
                    reasons_seen.add(reason)
                    assert row["expected"] == "invalid_descriptor", (case["id"], row)
                    continue
            assert candidate is not None

            expected = row["expected"]
            if "registry_digest" in row:
                registry = _tampered_registry(row["registry_digest"])
                reason = expect_reason(
                    lambda: descriptor.validate_descriptor(
                        candidate, render_registry=registry
                    ),
                    "renderer_digest_mismatch",
                )
            elif "provide_key" in row:
                reason = expect_reason(
                    lambda: descriptor.validate_descriptor(
                        candidate, provide_key=row["provide_key"]
                    ),
                    "descriptor_key_mismatch",
                )
            elif expected == "accepted":
                descriptor.validate_descriptor(candidate)
                reason = "accepted"
            else:
                reason = expect_reason(
                    lambda: descriptor.validate_descriptor(candidate), expected
                )
            if reason != "accepted":
                reasons_seen.add(reason)
            if "container_depth" in row:
                assert descriptor.descriptor_depth(candidate) == row["container_depth"]
            if "pg_bytes" in row:
                assert descriptor.descriptor_pg_bytes(candidate) == row["pg_bytes"]

    assert table_cases == 7

    # 3. Fail-closed default: a registry without the renderer must reject even
    # when the descriptor itself is well-formed.
    reason = expect_reason(
        lambda: descriptor.validate_descriptor(
            bases["descriptor.v2.read"],
            render_registry=renderers.RendererRegistry(()),
        ),
        "renderer_not_approved",
    )
    assert reason == "renderer_not_approved"

    unknown_id = copy.deepcopy(bases["descriptor.v2.read"])
    unknown_id["tool"]["render"]["id"] = "v24.fs.unknown.text"
    reasons_seen.add(expect_reason(
        lambda: descriptor.validate_descriptor(unknown_id),
        "renderer_not_approved",
    ))
    unknown_version = copy.deepcopy(bases["descriptor.v2.read"])
    unknown_version["tool"]["render"]["version"] = 2
    reasons_seen.add(expect_reason(
        lambda: descriptor.validate_descriptor(unknown_version),
        "renderer_not_approved",
    ))
    digest_mismatch = copy.deepcopy(bases["descriptor.v2.read"])
    digest_mismatch["tool"]["render"]["digest"] = "0" * 64
    reasons_seen.add(expect_reason(
        lambda: descriptor.validate_descriptor(digest_mismatch),
        "renderer_digest_mismatch",
    ))
    assert reasons_seen == set(descriptor.DESCRIPTOR_REASONS), reasons_seen

    # 4. Stable multi-fault priority: provide-key identity (step 16) beats
    # renderer approval (step 17), and unknown renderer beats digest mismatch.
    both = copy.deepcopy(bases["descriptor.v2.read"])
    both["tool"]["render"]["id"] = "v24.fs.unknown.text"
    expect_reason(
        lambda: descriptor.validate_descriptor(both, provide_key="list"),
        "descriptor_key_mismatch",
    )
    expect_reason(
        lambda: descriptor.validate_descriptor(
            digest_mismatch, provide_key="list"
        ),
        "descriptor_key_mismatch",
    )
    expect_reason(
        lambda: descriptor.validate_descriptor(
            unknown_id,
            render_registry=_tampered_registry("0" * 64),
        ),
        "renderer_not_approved",
    )

    # 5. Parser negatives that never reach table rows.
    for raw in (
        '{"v":2,"v":2,"tool":{}}',
        '{"tool":{"annotations":{"read_only":true,"read_only":false}}}',
        '{"v":NaN}',
        '{"v":Infinity}',
        '{"v":-Infinity}',
        "null",
        "[]",
        "2",
    ):
        expect_reason(lambda raw=raw: descriptor.parse_descriptor(raw),
                      "invalid_descriptor")
    expect_reason(lambda: descriptor.parse_descriptor(b"\xff"),
                  "invalid_descriptor")

    # 6. The canonical leaf keeps its independent canonicalization contracts.
    assert canonical.escaped_len("a\n雪") == len("a\\n雪".encode("utf-8"))
    assert canonical.compact_json({"é": 1, "a": 2}) == '{"a":2,"é":1}'.encode()
    expect_canonical(lambda: canonical.compact_json({1: "x"}), "non_string_key")
    expect_canonical(lambda: canonical.compact_json(1.5), "non_integer_number")
    expect_canonical(lambda: canonical.compact_json(2 ** 53), "unsafe_integer")
    expect_canonical(lambda: canonical.compact_json("\ud800"), "lone_surrogate")
    expect_canonical(lambda: canonical.strict_loads("1e3"), "non_integer_number")
    expect_canonical(lambda: canonical.strict_loads("-0"), "negative_zero")
    expect_canonical(lambda: canonical.strict_loads("NaN"), "non_json_constant")

    # 7. registry compatibility: the extracted names keep one identity.
    from v24.host import registry  # noqa: E402
    for name in (
        "_FrozenDict", "_FrozenList", "_freeze", "_quote",
        "pg_jsonb_text", "descriptor_digest", "RegistryError",
    ):
        assert getattr(registry, name) is getattr(canonical, name), name
    assert registry.RegistryError is canonical.RegistryError
    try:
        canonical.descriptor_digest([])
    except registry.RegistryError:
        pass
    else:
        raise AssertionError("non-dict digest accepted")

    print(
        "[passed] W2 descriptor contract; cases=16; "
        "canonical_python=9; reasons=4"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
