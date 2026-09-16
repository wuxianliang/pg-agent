"""Phase 0 gate for KohakuRAG generated tree fixtures.

Standalone check()/AssertionError style, matching v7/tests/test_legacy_cache_probe.py.
Run: uv run python v7/tests/test_kohaku_tree_fixture.py

Does not require KohakuRAG, torch, or kohakuvault. Regenerating the golden
against the pinned checkout is optional via --check on the generator.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from v7.migration.kohaku_tree_fixture import (
    CLOSED_NODE_KINDS,
    CORPUS_KIND,
    GOLDEN_PATH,
    PINNED_KOHAKU_COMMIT,
    SCHEMA_VERSION,
    dump_golden,
    main as fixture_main,
    porcelain_blocks_generation,
    tree_invariants,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "kohaku"
DOCUMENTS_DIR = FIXTURE_DIR / "documents"


def check(name: str, cond: bool, extra: object = None) -> None:
    if not cond:
        suffix = "" if extra is None else f": {extra!r}"
        raise AssertionError(f"{name}{suffix}")


def _load_golden() -> dict:
    payload = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    check("golden is an object", isinstance(payload, dict), type(payload).__name__)
    return payload


def test_golden_metadata(golden: dict) -> None:
    check("schema_version", golden.get("schema_version") == SCHEMA_VERSION, golden.get("schema_version"))
    check("golden_version is 1", golden.get("golden_version") == 1, golden.get("golden_version"))
    check("corpus_kind", golden.get("corpus_kind") == CORPUS_KIND, golden.get("corpus_kind"))
    check("not a live Kohaku service", golden.get("not_live_kohaku_service") is True)
    check("embedder was not invoked", golden.get("embedder_invoked") is False)
    check("pinned Kohaku commit", golden.get("kohaku_commit") == PINNED_KOHAKU_COMMIT, golden.get("kohaku_commit"))
    check("src tree recorded clean", golden.get("kohaku_src_clean") is True)
    check("canonical dump is stable", dump_golden(golden) == GOLDEN_PATH.read_text(encoding="utf-8"))


def test_dirty_src_and_write_check_policy() -> None:
    check("empty porcelain is clean", porcelain_blocks_generation([]) == [])
    check(
        "tracked modification blocks",
        porcelain_blocks_generation([" M src/kohakurag/indexer.py"]) == [" M src/kohakurag/indexer.py"],
    )
    check(
        "untracked module blocks",
        porcelain_blocks_generation(["?? src/kohakurag/extra.py"]) == ["?? src/kohakurag/extra.py"],
    )
    with redirect_stderr(io.StringIO()):
        try:
            fixture_main(["--write", "--check"])
        except SystemExit as exc:
            check("--write and --check are mutually exclusive", exc.code == 2, exc.code)
        else:
            raise AssertionError("--write --check did not exit")


def test_source_documents_exist() -> None:
    for name in ("headings.md", "plain.txt", "nested.json"):
        path = DOCUMENTS_DIR / name
        check(f"{name} exists", path.is_file(), path)
        check(f"{name} is not empty", path.stat().st_size > 0, path)


def test_tree_invariants(golden: dict) -> None:
    documents = golden.get("documents")
    check("documents is a list of 3", isinstance(documents, list) and len(documents) == 3, documents)
    recomputed = tree_invariants(documents)
    check("recorded invariants match recomputation", golden.get("invariants") == recomputed, golden.get("invariants"))
    check("no ATTACHMENT nodes", recomputed.get("attachment_nodes_present") is False, recomputed)
    check("closed kind set includes attachment", list(CLOSED_NODE_KINDS) == recomputed.get("node_kinds_closed"))
    check("kinds present omit attachment", "attachment" not in recomputed.get("kinds_present"), recomputed)
    ids = [doc.get("id") for doc in documents]
    check("document ids", ids == ["doc-md", "doc-text", "doc-json"], ids)


def _assert_tree(doc_id: str, tree: list) -> dict:
    check(f"{doc_id} tree is a list", isinstance(tree, list) and tree, type(tree).__name__)
    by_id = {}
    for row in tree:
        check(f"{doc_id} row is object", isinstance(row, dict), row)
        node_id = row.get("node_id")
        check(f"{doc_id} node_id unique", node_id not in by_id, node_id)
        by_id[node_id] = row
        kind = row.get("kind")
        check(f"{node_id} kind in closed set", kind in CLOSED_NODE_KINDS, kind)
        check(f"{node_id} has no embedding field", "embedding" not in row, row)
        for key in ("title", "text", "metadata", "child_ids"):
            check(f"{node_id} has {key}", key in row, row)
    roots = [row for row in tree if row.get("parent_id") is None]
    check(f"{doc_id} one document root", len(roots) == 1 and roots[0].get("kind") == "document", roots)
    check(f"{doc_id} root id", roots[0].get("node_id") == doc_id, roots[0].get("node_id"))
    return by_id


def test_markdown_tree(golden: dict) -> None:
    doc = next(item for item in golden["documents"] if item["id"] == "doc-md")
    check("markdown source_rel", doc.get("source_rel") == "v7/tests/fixtures/kohaku/documents/headings.md")
    by_id = _assert_tree("doc-md", doc["tree"])
    sections = [row for row in doc["tree"] if row["kind"] == "section"]
    titles = [row["title"] for row in sections]
    check("markdown section titles", titles == ["Intro", "Details", "Nested", "Closing"], titles)
    check("heading level 1 Intro", by_id["doc-md:sec1"]["metadata"].get("level") == 1)
    check("heading level 2 Details", by_id["doc-md:sec2"]["metadata"].get("level") == 2)
    check("heading level 3 Nested", by_id["doc-md:sec3"]["metadata"].get("level") == 3)
    check("global paragraph counter continues in sec2", "doc-md:sec2:p3" in by_id, sorted(by_id))
    check("global sentence counter continues", "doc-md:sec1:p2:s3" in by_id, sorted(by_id))
    sentences = [row["text"] for row in doc["tree"] if row["kind"] == "sentence"]
    check("split 'First paragraph. Second sentence here!'", "First paragraph." in sentences and "Second sentence here!" in sentences, sentences)


def test_plain_text_autogenerated_section(golden: dict) -> None:
    doc = next(item for item in golden["documents"] if item["id"] == "doc-text")
    by_id = _assert_tree("doc-text", doc["tree"])
    sections = [row for row in doc["tree"] if row["kind"] == "section"]
    check("plain text has one autogenerated section", len(sections) == 1, sections)
    check("autogenerated metadata", sections[0]["metadata"].get("autogenerated") is True, sections[0]["metadata"])
    check("plain root exists", "doc-text" in by_id)


def test_json_payload_preserves_declared_sentences(golden: dict) -> None:
    doc = next(item for item in golden["documents"] if item["id"] == "doc-json")
    by_id = _assert_tree("doc-json", doc["tree"])
    declared = by_id["doc-json:sec1:p1"]
    check("declared paragraph text", declared["text"] == "Declared paragraph. Extra sentence.")
    child_texts = [by_id[child]["text"] for child in declared["child_ids"]]
    check(
        "declared sentences kept",
        child_texts == ["Declared paragraph.", "Extra sentence."],
        child_texts,
    )
    split = by_id["doc-json:sec2:p2"]
    split_texts = [by_id[child]["text"] for child in split["child_ids"]]
    check(
        "indexer splits missing sentences",
        split_texts == ["No sentences listed.", "Indexer must split this."],
        split_texts,
    )
    payload = doc["payload"]
    check("payload document_id", payload.get("document_id") == "doc-json")
    check("payload has two sections", len(payload.get("sections") or []) == 2, payload.get("sections"))


def main() -> int:
    golden = _load_golden()
    test_golden_metadata(golden)
    test_dirty_src_and_write_check_policy()
    test_source_documents_exist()
    test_tree_invariants(golden)
    test_markdown_tree(golden)
    test_plain_text_autogenerated_section(golden)
    test_json_payload_preserves_declared_sentences(golden)
    print("[kohaku_tree_fixture] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
