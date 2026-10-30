"""W2 renderer contract gate: golden bytes, registry identity and digests.

Read-only over ``v24/s13/vectors/renderers.json``.  DB-free, Node-free,
socket-free and subprocess-free.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v24.host import renderers  # noqa: E402
from v24.host.canonical import compact_json, escaped_len  # noqa: E402

VECTORS = Path(__file__).resolve().parent / "vectors" / "renderers.json"
SOURCE = Path(renderers.__file__).read_text(encoding="utf-8")

RENDERER_BY_CASE = {
    "render.read.golden": "v24.fs.read.text",
    "render.list.golden": "v24.fs.list.text",
    "render.search.golden": "v24.fs.search.text",
}

GOLDEN_KEYS = ("id", "args", "value", "content", "meta")


def budget_measures(args, value, content, meta):
    """Independent re-implementation of the five W2 budget domains."""
    frame = {"ok": True, "v": 2, "result": {"value": value}}
    return {
        "args": len(compact_json(args)),
        "value": len(compact_json(value)),
        "content": len(compact_json(content)),
        "meta": len(compact_json({} if meta is None else meta)),
        "frame": len(compact_json(frame)) + 1,
    }


def expect_renderer_error(fn, reason):
    try:
        fn()
    except renderers.RendererError as exc:
        assert exc.reason == reason, (reason, exc.reason)
        return
    raise AssertionError(f"expected RendererError({reason!r})")


def main() -> int:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = document["cases"]
    assert document["format"] == "v24-tool-plugin-abi-w1-vectors-1"
    assert len(cases) == 7
    by_id = {case["id"]: case for case in cases}

    # 1. The production registry contains exactly the three built-ins, with
    # version 1 and projection 1, and exposes no mutator.
    assert len(renderers.RENDERERS) == 3
    assert isinstance(renderers.RENDERERS.entries, tuple)
    assert {entry.ref.id for entry in renderers.RENDERERS.entries} == {
        "v24.fs.read.text", "v24.fs.list.text", "v24.fs.search.text",
    }
    for entry in renderers.RENDERERS.entries:
        assert entry.ref.version == 1
        assert entry.projection == 1
        assert len(entry.ref.digest) == 64
        try:
            entry.ref = None
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError("Renderer is mutable")

    # 2. Twenty-one embedded golden cases: five-key equality with the vectors,
    # rendered bytes, frozen measures, and the 27+E(T) content identity.
    golden_cases = 0
    for case in cases:
        if case["id"] not in RENDERER_BY_CASE:
            continue
        renderer_id = RENDERER_BY_CASE[case["id"]]
        vector_cases = case["input"]["cases"]
        embedded = renderers._GOLDEN_BY_ID[renderer_id]
        assert len(embedded) == case["expected"]["case_count"]
        assert len(vector_cases) == len(embedded)
        entry = renderers.RENDERERS.by_id(renderer_id, 1)
        assert entry is not None
        for vector_case, embedded_case in zip(vector_cases, embedded):
            golden_cases += 1
            assert set(embedded_case) == set(GOLDEN_KEYS)
            for key in GOLDEN_KEYS:
                assert embedded_case[key] == vector_case[key], (
                    vector_case["id"], key,
                )
            content, meta = renderers.RENDERERS.render(
                entry.ref, vector_case["args"], vector_case["value"]
            )
            assert content == vector_case["content"], vector_case["id"]
            assert meta == vector_case["meta"], vector_case["id"]
            assert budget_measures(
                vector_case["args"], vector_case["value"], content, meta
            ) == vector_case["measures"], vector_case["id"]
            assert case["expected"]["single_text_block"] is True
            assert len(content) == 1 and content[0]["type"] == "text"
            text = content[0]["text"]
            assert len(compact_json(content)) == 27 + escaped_len(text), \
                vector_case["id"]
    assert golden_cases == 21

    # 3. Three manifest byte cases and three fixed digest pairs.
    manifests = 0
    for case in cases:
        if case["kind"] != "byte":
            continue
        manifests += 1
        data = case["input"]
        renderer_id = data["id"]
        golden = renderers._GOLDEN_BY_ID[renderer_id]
        assert renderers.golden_digest(golden) == data["golden_digest"]
        manifest = {
            "id": renderer_id,
            "version": data["version"],
            "projection": data["projection"],
            "golden_digest": data["golden_digest"],
        }
        encoded = compact_json(manifest)
        assert encoded == bytes.fromhex(case["expected_hex"]), case["id"]
        assert encoded == case["expected_text"].encode("utf-8"), case["id"]
        assert len(encoded) == case["expected_length"], case["id"]
        assert hashlib.sha256(encoded).hexdigest() == case["expected_sha256"]
        assert case["render_digest"] == case["expected_sha256"]
        assert renderers.render_digest(
            renderer_id, data["version"], data["projection"], golden
        ) == case["render_digest"]
        entry = renderers.RENDERERS.by_id(renderer_id, data["version"])
        assert entry is not None
        assert entry.ref.digest == case["render_digest"]
    assert manifests == 3

    digest_case = by_id["render.digest.provisional_values"]
    assert set(digest_case["input"]["ordered_case_ids"]) == {"read", "list", "search"}
    for short, renderer_id in (
        ("read", "v24.fs.read.text"),
        ("list", "v24.fs.list.text"),
        ("search", "v24.fs.search.text"),
    ):
        assert renderers.render_digest(
            renderer_id, 1, 1, renderers._GOLDEN_BY_ID[renderer_id]
        ) == digest_case["expected"][short]

    # 4. by_id ignores the digest; lookup requires full identity.
    read = renderers.RENDERERS.by_id("v24.fs.read.text", 1)
    assert read is not None
    wrong_digest = renderers.RendererRef(read.ref.id, read.ref.version, "0" * 64)
    assert renderers.RENDERERS.by_id(wrong_digest.id, wrong_digest.version) is read
    expect_renderer_error(
        lambda: renderers.RENDERERS.lookup(wrong_digest), "renderer_not_approved"
    )
    expect_renderer_error(
        lambda: renderers.RENDERERS.lookup(
            renderers.RendererRef("v24.fs.unknown.text", 1, read.ref.digest)
        ),
        "renderer_not_approved",
    )
    expect_renderer_error(
        lambda: renderers.RENDERERS.lookup(
            renderers.RendererRef(read.ref.id, 2, read.ref.digest)
        ),
        "renderer_not_approved",
    )
    assert renderers.RENDERERS.lookup(read.ref) is read
    expect_renderer_error(
        lambda: renderers.RENDERERS.render(
            wrong_digest, {"path": "a"}, {"text": "", "total_lines": 0}
        ),
        "renderer_not_approved",
    )

    # 5. Duplicate (id, version) is refused at registry construction.
    try:
        renderers.RendererRegistry((read, read))
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate renderer accepted")

    def raises(args, value):
        raise RuntimeError("boom")

    def bad_content(args, value):
        return [], {}

    def too_many(args, value):
        return ([{"type": "text", "text": ""}] * 17), {}

    def bad_block(args, value):
        return [{"type": "text", "text": "", "extra": True}], {}

    def bad_meta(args, value):
        return [{"type": "text", "text": ""}], []

    for fn, reason in (
        (raises, "render_failed"),
        (bad_content, "invalid_tool_content"),
        (too_many, "invalid_tool_content"),
        (bad_block, "invalid_tool_content"),
        (bad_meta, "invalid_tool_content"),
    ):
        registry = renderers.RendererRegistry((
            renderers.Renderer(
                renderers.RendererRef("v24.fs.test.text", 1, "1" * 64), 1, fn
            ),
        ))
        expect_renderer_error(
            lambda registry=registry: registry.render(
                renderers.RendererRef("v24.fs.test.text", 1, "1" * 64), {}, {}
            ),
            reason,
        )

    # 6. Production source never reads the frozen vector directory and never
    # imports the budget module.
    assert "s13/vectors" not in SOURCE
    assert "tool_results" not in SOURCE

    print(
        "[passed] W2 renderer contract; cases=7; "
        "golden_cases=21; digest_pairs=3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
