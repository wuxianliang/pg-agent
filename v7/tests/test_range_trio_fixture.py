"""Phase 0 gate for MinerU/code/legacy range-trio fixtures.

Standalone check()/AssertionError style, matching v7/tests/test_kohaku_tree_fixture.py.
Run: uv run python v7/tests/test_range_trio_fixture.py

Does not import mineru, does not read the 15GB snapshot cache, and does not
mark phase0_baseline_status.json E2.
"""
from __future__ import annotations

import ast
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from v7.migration.range_trio_fixture import (
    CANONICAL_CONTENT_LIST,
    CODE_PATH,
    CODE_REL,
    CODE_SHA256,
    CODE_SIZE_BYTES,
    COMMAND,
    CONTENT_LIST_PATH,
    CORPUS_KIND,
    FixtureError,
    GOLDEN_PATH,
    HARNESS_REVISION,
    LEGACY_GOLDEN_REL,
    LEGACY_PATH,
    LEGACY_REL,
    LEGACY_SHA256,
    LEGACY_SIZE_BYTES,
    MINERU_WHEEL_SHA256,
    MODEL_MANIFEST_SHA256,
    PAGE_SIZE,
    PDF_PATH,
    PDF_REL,
    PDF_SHA256,
    PDF_SIZE_BYTES,
    PROFILE_ID,
    PROFILE_REL,
    P19S_REPOSITORY_REVISION,
    P19S_RUN_ID,
    REPO_ROOT,
    SCHEMA_VERSION,
    SOURCE_MAIN_REVISION,
    WHEEL_LOCK_REL,
    bbox_in_page,
    dump_golden,
    generate,
    load_json,
    main as fixture_main,
    require_utf8,
    split_source_lines,
    verify_copied_identity,
)

GENERATOR_PATH = REPO_ROOT / "v7" / "migration" / "range_trio_fixture.py"
IDENTITY_NOTE = REPO_ROOT / "v7" / "evidence" / "mineru_identity.md"


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
    check("not live MinerU", golden.get("not_live_mineru_runtime") is True)
    check("not live Kohaku", golden.get("not_live_kohaku_service") is True)
    check("not live legacy cache", golden.get("not_live_legacy_cache") is True)
    check("command", golden.get("command") == COMMAND, golden.get("command"))
    check("canonical dump is stable", dump_golden(golden) == GOLDEN_PATH.read_text(encoding="utf-8"))
    check("generated golden matches committed", dump_golden(generate()) == dump_golden(golden))


def test_write_check_mutex_and_no_live_parse() -> None:
    with redirect_stderr(io.StringIO()):
        try:
            fixture_main(["--write", "--check"])
        except SystemExit as exc:
            check("--write and --check are mutually exclusive", exc.code == 2, exc.code)
        else:
            raise AssertionError("--write --check did not exit")
    with redirect_stderr(io.StringIO()):
        try:
            fixture_main(["--live-parse"])
        except SystemExit as exc:
            check("unknown --live-parse", exc.code == 2, exc.code)
        else:
            raise AssertionError("--live-parse was accepted")
    source = GENERATOR_PATH.read_text(encoding="utf-8")
    check("generator does not register --live-parse", "add_argument(\"--live-parse\"" not in source and "add_argument('--live-parse'" not in source)
    check("generator does not read duckrag cache", ".cache/duckrag-wi1" not in source)
    check("generator does not mention mineru.json", "mineru.json" not in source)


def test_check_does_not_import_mineru() -> None:
    tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check("no mineru import", alias.name.split(".", 1)[0] != "mineru", alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            check("no mineru from-import", node.module.split(".", 1)[0] != "mineru", node.module)
    before = {name for name in sys.modules if name == "mineru" or name.startswith("mineru.")}
    check("--check exit 0", fixture_main(["--check"]) == 0)
    after = {name for name in sys.modules if name == "mineru" or name.startswith("mineru.")}
    check("--check did not import mineru", after == before, after - before)


def test_three_range_origins(golden: dict) -> None:
    legs = golden.get("legs")
    check("legs is an object", isinstance(legs, dict), type(legs).__name__)
    check("leg keys", set(legs) == {"pdf", "code", "legacy"}, set(legs) if isinstance(legs, dict) else legs)
    check("no normalized_line leg", "normalized_line" not in legs)
    origins = {name: legs[name].get("range_origin") for name in ("pdf", "code", "legacy")}
    check("pdf origin", origins["pdf"] == "page_bbox", origins)
    check("code origin", origins["code"] == "source_line", origins)
    check("legacy origin", origins["legacy"] == "legacy_flat", origins)
    check("three distinct origins", set(origins.values()) == {"page_bbox", "source_line", "legacy_flat"}, origins)


def test_pdf_leg(golden: dict) -> None:
    pdf = golden["legs"]["pdf"]
    check("pdf source_rel", pdf.get("source_rel") == PDF_REL)
    check("pdf sha256", pdf.get("pdf_sha256") == PDF_SHA256, pdf.get("pdf_sha256"))
    check("pdf size", pdf.get("pdf_size_bytes") == PDF_SIZE_BYTES, pdf.get("pdf_size_bytes"))
    check("on-disk pdf sha", __import__("hashlib").sha256(PDF_PATH.read_bytes()).hexdigest() == PDF_SHA256)
    check("on-disk pdf size", PDF_PATH.stat().st_size == PDF_SIZE_BYTES)
    check("page_size", pdf.get("page_size") == PAGE_SIZE, pdf.get("page_size"))
    check("page_idx", pdf.get("page_idx") == 0, pdf.get("page_idx"))
    check("catalog_page", pdf.get("catalog_page") == 1, pdf.get("catalog_page"))
    check("line_start JSON null", pdf.get("line_start") is None, pdf.get("line_start"))
    check("line_end JSON null", pdf.get("line_end") is None, pdf.get("line_end"))
    raw = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    check("serialized line_start is null", raw["legs"]["pdf"]["line_start"] is None)
    check("serialized line_end is null", raw["legs"]["pdf"]["line_end"] is None)
    content_list = pdf.get("content_list")
    check("content_list is two objects", isinstance(content_list, list) and len(content_list) == 2, content_list)
    check("content_list not strings", all(isinstance(item, dict) for item in content_list), content_list)
    check("content_list canonical", content_list == CANONICAL_CONTENT_LIST, content_list)
    disk_list = json.loads(CONTENT_LIST_PATH.read_text(encoding="utf-8"))
    check("content_list.json matches canonical", disk_list == CANONICAL_CONTENT_LIST, disk_list)
    for item in content_list:
        check("bbox in-page", bbox_in_page(item.get("bbox")), item.get("bbox"))
        check("page_idx 0", item.get("page_idx") == 0, item.get("page_idx"))
    provenance = pdf.get("provenance")
    check("imported provenance", isinstance(provenance, dict) and provenance.get("kind") == "imported_from_duckrag_p19s")
    check("mineru not invoked this freeze", provenance.get("mineru_invoked_this_freeze") is False)
    check("provenance run_id from p19-s", provenance.get("p19s_run_id") == P19S_RUN_ID)
    check("provenance harness from p19-s", provenance.get("harness_revision") == HARNESS_REVISION)
    check("provenance repo rev from p19-s", provenance.get("p19s_repository_revision_synthetic") == P19S_REPOSITORY_REVISION)
    check("provenance source_main from p19-s", provenance.get("source_main_revision") == SOURCE_MAIN_REVISION)
    check("provenance profile_id", provenance.get("profile_id") == PROFILE_ID)


def test_code_and_legacy_legs(golden: dict) -> None:
    code = golden["legs"]["code"]
    check("code source_rel", code.get("source_rel") == CODE_REL)
    check("code corpus_kind", code.get("corpus_kind") == "generated_source_line_fixture")
    check("code newline", code.get("newline") == "\n")
    code_text = CODE_PATH.read_text(encoding="utf-8")
    code_lines = split_source_lines(code_text, CODE_REL)
    check("code line_start", code.get("line_start") == 1)
    check("code line_end covers file", code.get("line_end") == len(code_lines), (code.get("line_end"), len(code_lines)))
    check("code sha pin", code.get("source_sha256") == CODE_SHA256, code.get("source_sha256"))
    check("code size pin", code.get("source_size_bytes") == CODE_SIZE_BYTES, code.get("source_size_bytes"))
    parsed = ast.parse(code_text)
    check("sample.py parses as Python", any(isinstance(node, ast.FunctionDef) and node.name == "greeting" for node in parsed.body))
    check("sample.py is not markdown heading", not code_text.lstrip().startswith("#"))

    legacy = golden["legs"]["legacy"]
    check("legacy source_rel", legacy.get("source_rel") == LEGACY_REL)
    check("legacy corpus_kind", legacy.get("corpus_kind") == "synthetic_from_source_schema")
    check("related legacy golden", legacy.get("related_legacy_golden") == LEGACY_GOLDEN_REL)
    legacy_lines = split_source_lines(LEGACY_PATH.read_text(encoding="utf-8"), LEGACY_REL)
    check("legacy line_start", legacy.get("line_start") == 1)
    check("legacy line_end covers file", legacy.get("line_end") == len(legacy_lines), (legacy.get("line_end"), len(legacy_lines)))
    check("legacy sha pin", legacy.get("source_sha256") == LEGACY_SHA256, legacy.get("source_sha256"))
    check("legacy size pin", legacy.get("source_size_bytes") == LEGACY_SIZE_BYTES, legacy.get("source_size_bytes"))
    notes = str(legacy.get("notes") or "")
    check("legacy notes deny live cache", "Not live byzerai_store_duckdb.db" in notes, notes)
    check("legacy source denies live db", "not from live byzerai_store_duckdb.db" in LEGACY_PATH.read_text(encoding="utf-8"))


def test_copied_identity_and_freeze_note() -> None:
    verify_copied_identity()
    profile = json.loads((REPO_ROOT / PROFILE_REL).read_text(encoding="utf-8"))
    check(
        "snapshot pin is profile pipeline_model.manifest_sha256",
        profile["pipeline_model"]["manifest_sha256"] == MODEL_MANIFEST_SHA256,
        profile["pipeline_model"]["manifest_sha256"],
    )
    lock = json.loads((REPO_ROOT / WHEEL_LOCK_REL).read_text(encoding="utf-8"))
    check("wheel sha is lock field", lock["pypi_artifacts"][0]["sha256"] == MINERU_WHEEL_SHA256)
    lock_text = (REPO_ROOT / WHEEL_LOCK_REL).read_text(encoding="utf-8")
    check("wheel lock is not snapshot pin", MODEL_MANIFEST_SHA256 not in lock_text)
    check("freeze note exists", IDENTITY_NOTE.is_file(), IDENTITY_NOTE)
    note = IDENTITY_NOTE.read_text(encoding="utf-8")
    check("freeze note has no --live-parse on generator", "--live-parse" not in note.split("Operator")[0] or "no `--live-parse`" in note.lower() or "no --live-parse" in note.lower())
    check("freeze note forbids live-parse flag", "live-parse" in note.lower())
    check("claimed vs not claimed", "Not claimed" in note or "not claimed" in note.lower())


def test_invalid_json_and_utf8(tmp_path: Path | None = None) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as raw:
        folder = Path(raw)
        bad_json = folder / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        try:
            load_json(bad_json)
        except FixtureError as exc:
            check("malformed JSON is FixtureError", exc.exit_code == 4, exc.exit_code)
        else:
            raise AssertionError("malformed JSON did not raise")
        bad_utf8 = folder / "bad.txt"
        bad_utf8.write_bytes(b"\xff\xfe not utf8")
        try:
            require_utf8(bad_utf8)
        except FixtureError as exc:
            check("invalid UTF-8 is FixtureError", exc.exit_code == 4, exc.exit_code)
        else:
            raise AssertionError("invalid UTF-8 did not raise")


def main() -> int:
    golden = _load_golden()
    test_golden_metadata(golden)
    test_write_check_mutex_and_no_live_parse()
    test_three_range_origins(golden)
    test_pdf_leg(golden)
    test_code_and_legacy_legs(golden)
    test_copied_identity_and_freeze_note()
    test_invalid_json_and_utf8()
    test_check_does_not_import_mineru()
    print("[range_trio_fixture] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
