"""Phase 0 gate for the read-only auto-coder DuckDB cache probe.

Standalone check()/AssertionError style, matching v6/duckdb_probe/test_duckdb_probe.py.
Run: uv run python v7/tests/test_legacy_cache_probe.py
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from v7.migration.legacy_cache_probe import (
    EXIT_DIMENSION_MISMATCH,
    EXIT_INVALID_CORPUS_KIND,
    EXIT_INVALID_INPUT,
    EXIT_MISSING_DB,
    EXIT_MISSING_FILE,
    GOLDEN_VERSION,
    LEGACY_DB_FILENAME,
    LEGACY_TABLE,
    LIVE_CORPUS_KIND,
    PROBE_TOP_K_CAP,
    SOURCE_DEFAULTS,
    SYNTHETIC_CORPUS_KIND,
    SYNTHETIC_DDL,
    SYNTHETIC_QUERY_VECTOR,
    SYNTHETIC_ROWS,
    ProbeError,
    ProbeInputError,
    dump_golden,
    file_signature,
    main as probe_main,
    open_legacy_cache_readonly,
    path_token,
    probe_legacy_cache,
    report_to_golden,
    sanitize_cli_text,
    tree_signatures,
    write_synthetic_schema_fixture,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "legacy_cache"
GOLDEN_PATH = FIXTURE_DIR / "golden.v1.json"
QUERY_VECTOR_4D_PATH = FIXTURE_DIR / "query_vector.4d.json"
SIDECAR_MARKER_PATH = FIXTURE_DIR / "sidecar.marker"
# Independent leak oracle — not the production sanitizer. Split on both
# separators so partial redaction of `My Secret/db.sqlite` is still a leak.
ABS_PATH_SAMPLES = (
    "/data/secret.db",
    "/mnt/foo",
    "/root/x",
    r"C:\Users\secret.db",
    r"D:/data/secret.db",
    r"\\server\share\secret.db",
)
WHITESPACE_PATH_SAMPLES = (
    "/Users/x/My Secret/db.sqlite",
    "/Users/x/My\tSecret/db.sqlite",
    "/Users/x/My\u00a0Secret/db.sqlite",
    '"/Users/x/My Secret/db.sqlite"',
    "file:///Users/x/My Secret/db.sqlite",
    r"\\?\C:\Users\My Secret\db.sqlite",
    r"\\server\share\My Secret\db.sqlite",
)


def _independent_path_suffixes(original: str) -> list[str]:
    text = original.strip().strip("'\"")
    lower = text.lower()
    if lower.startswith("file:"):
        rest = text[5:]
        text = rest[2:] if rest.startswith("//") else rest
        if text.startswith("/") and not text.startswith("//"):
            pass
        elif "//" in text[:8] and "/" in text[2:]:
            text = text[text.find("/", 2) :]
    if text.startswith("\\\\?\\"):
        body = text[4:]
        text = "\\\\" + body[4:] if body.upper().startswith("UNC") else body
    unified = text.replace("\\", "/")
    parts = [part for part in unified.split("/") if part and part != "."]
    suffixes: list[str] = []
    for index in range(len(parts) - 1):
        posix = "/".join(parts[index:])
        windows = "\\".join(parts[index:])
        suffixes.append(posix)
        if windows != posix:
            suffixes.append(windows)
    return suffixes


def _leaf_name(original: str) -> str:
    text = original.strip().strip("'\"")
    unified = text.replace("\\", "/")
    parts = [part for part in unified.split("/") if part and part != "."]
    leaf = parts[-1] if parts else text
    if len(leaf) == 2 and leaf[1] == ":":
        return "path"
    return leaf.split("?")[0].split("#")[0]


def _independent_path_leak(haystack: str, original: str) -> str | None:
    if original in haystack:
        return original
    stripped = original.strip().strip("'\"")
    if stripped and stripped in haystack:
        return stripped
    leaf = _leaf_name(original)
    token_ok = f"{leaf}#"
    for suffix in _independent_path_suffixes(original):
        if suffix == leaf:
            continue
        if suffix in haystack:
            if token_ok in haystack and suffix.startswith(leaf):
                continue
            return suffix
    return None


def _independent_abs_path_leak(text: str) -> str | None:
    """Find a leftover absolute-path start without using the production scanner."""
    index = 0
    length = len(text)
    while index < length:
        rest = text[index:]
        prev = text[index - 1] if index else ""
        hit = None
        if rest.lower().startswith("file:"):
            hit = rest[: min(80, length - index)]
        elif rest.startswith("\\\\?\\") or rest.startswith("\\\\"):
            hit = rest[: min(80, length - index)]
        elif len(rest) >= 3 and rest[0].isalpha() and rest[1] == ":" and rest[2] in "\\/":
            hit = rest[: min(80, length - index)]
        elif rest.startswith("/") and not (prev and (prev.isalnum() or prev in "_.-#")):
            hit = rest[: min(80, length - index)]
        if hit:
            return hit.split("\n", 1)[0]
        index += 1
    return None
CONTENT_LEAKS = tuple(
    str(row[key])
    for row in SYNTHETIC_ROWS
    for key in ("content", "raw_content", "file_path")
    if row.get(key)
)
PINNED_DUCKDB_PACKAGE = "1.6.0.dev366+ga1f0ab1911"
PINNED_LIBRARY_VERSION = "v1.6.0-dev13823"
PINNED_SOURCE_ID = "a1f0ab1911"


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"[{('PASS' if condition else 'FAIL')}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def raises(fn, pattern: str | None = None) -> str:
    try:
        fn()
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        if pattern:
            check(f"raises {pattern}", re.search(pattern, msg, re.I) is not None, msg)
        return msg
    raise AssertionError("expected exception")


def _load_golden() -> dict:
    check("golden fixture exists", GOLDEN_PATH.is_file(), GOLDEN_PATH.name)
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _sidecar_names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


def _build_fixture(tmpdir: Path) -> Path:
    cache_dir = tmpdir / ".cache"
    destination = cache_dir / LEGACY_DB_FILENAME
    write_synthetic_schema_fixture(destination)
    return destination


def _build_dimension_fixture(tmpdir: Path, dimension: int, *, name: str = "dim.db") -> Path:
    destination = tmpdir / name
    vector = [0.0] * dimension
    vector[0] = 1.0
    connection = duckdb.connect(str(destination))
    try:
        connection.execute(SYNTHETIC_DDL)
        connection.execute(
            f"INSERT INTO {LEGACY_TABLE} VALUES (?, ?, ?, ?, ?, ?)",
            ["doc_d", "sample/d.txt", "dim row", "dim row", vector, 1.0],
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    return destination


def _assert_no_leaks(label: str, blobs: list[str]) -> None:
    joined = "\n".join(blobs)
    abs_hit = _independent_abs_path_leak(joined)
    check(f"{label} has no absolute paths", abs_hit is None, abs_hit or "")
    leaked = [token for token in CONTENT_LEAKS if token in joined]
    check(f"{label} has no raw content or file_path", leaked == [], leaked)


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = probe_main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def _assert_cli_clean(label: str, out: str, err: str, *paths: Path) -> None:
    _assert_no_leaks(label, [out, err])
    blob = out + err
    check(f"{label} omits traceback", "Traceback" not in blob)
    for path in paths:
        check(f"{label} omits {path.name} absolute path", str(path) not in blob, str(path))


def test_pinned_runtime() -> None:
    check("exact Python package", duckdb.__version__ == PINNED_DUCKDB_PACKAGE, duckdb.__version__)
    check("macOS only", sys.platform == "darwin", sys.platform)
    check("arm64 only", os.uname().machine == "arm64", os.uname().machine)
    check("CPython 3.12 only", sys.version_info[:2] == (3, 12), sys.version)
    check("source default similarity", SOURCE_DEFAULTS["similarity"] == 0.1, SOURCE_DEFAULTS["similarity"])
    check("source default top_k", SOURCE_DEFAULTS["top_k"] == 10000, SOURCE_DEFAULTS["top_k"])
    check("source default dimension", SOURCE_DEFAULTS["dimension"] == 1024, SOURCE_DEFAULTS["dimension"])
    check("hybrid index default false", SOURCE_DEFAULTS["enable_hybrid_index"] is False)
    check("golden version", GOLDEN_VERSION == 1, GOLDEN_VERSION)
    check("probe top_k cap below source default", PROBE_TOP_K_CAP < SOURCE_DEFAULTS["top_k"], PROBE_TOP_K_CAP)
    check("probe top_k cap positive", PROBE_TOP_K_CAP > 0, PROBE_TOP_K_CAP)


def test_probe_source_is_read_only() -> None:
    src = Path(__file__).resolve().parent.parent / "migration" / "legacy_cache_probe.py"
    text = src.read_text(encoding="utf-8")
    check("opens with read_only=True", "read_only=True" in text)
    check(
        "probe does not execute INSTALL",
        'execute("INSTALL' not in text and "execute('INSTALL" not in text and "install_extension" not in text,
    )
    check("probe does not CREATE v7 catalog tables", "rag_document" not in text)
    check('dump_golden exclusive create', 'open("x"' in text or "O_EXCL" in text)
    check("dump_golden does not write_text destination", "destination.write_text" not in text)


def test_synthetic_probe_matches_golden() -> dict:
    golden = _load_golden()
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_"))
    try:
        db_path = _build_fixture(tmpdir)
        before = file_signature(db_path)
        tree_before = tree_signatures(db_path.parent)
        sidecars_before = _sidecar_names(db_path.parent)
        report = probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND)
        after = file_signature(db_path)
        tree_after = tree_signatures(db_path.parent)
        sidecars_after = _sidecar_names(db_path.parent)

        check("corpus kind", report["metadata"]["corpus_kind"] == SYNTHETIC_CORPUS_KIND)
        check("access_mode read_only", report["duckdb"]["access_mode"] == "read_only", report["duckdb"])
        check("duckdb package pin", report["duckdb"]["package"] == PINNED_DUCKDB_PACKAGE, report["duckdb"])
        check("library_version pin", report["duckdb"]["library_version"] == PINNED_LIBRARY_VERSION, report["duckdb"])
        check("source_id pin", report["duckdb"]["source_id"] == PINNED_SOURCE_ID, report["duckdb"])
        check("fixture sha256 unchanged", before["sha256"] == after["sha256"], (before["sha256"], after["sha256"]))
        check("fixture size unchanged", before["size"] == after["size"], (before["size"], after["size"]))
        check("fixture mtime_ns unchanged", before["mtime_ns"] == after["mtime_ns"], (before["mtime_ns"], after["mtime_ns"]))
        check("recursive signatures unchanged", tree_before == tree_after, (tree_before, tree_after))
        check("no new sidecar files", sidecars_before == sidecars_after, (sidecars_before, sidecars_after))

        tables = [row["name"] for row in report["schema_snapshot"]["tables"]]
        check("only legacy table", tables == [LEGACY_TABLE], tables)
        col_names = [row["name"] for row in report["schema_snapshot"]["columns"]]
        check(
            "column names",
            col_names == ["_id", "file_path", "content", "raw_content", "vector", "mtime"],
            col_names,
        )
        observed_types = [row["observed_type"] for row in report["schema_snapshot"]["columns"]]
        check(
            "observed types",
            observed_types == ["VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "FLOAT[]", "FLOAT"],
            observed_types,
        )
        check("row count", report["stats"]["row_count"] == len(SYNTHETIC_ROWS), report["stats"]["row_count"])
        check(
            "observed dimension is synthetic 4",
            report["stats"]["dimension"]["observed_dimension"] == 4,
            report["stats"]["dimension"],
        )
        check(
            "null vector counted",
            report["stats"]["null_counts"]["vector"] == 1,
            report["stats"]["null_counts"],
        )
        check("duplicate id recorded", report["stats"]["duplicate_ids"] == [{"_id": "doc_dup_0", "count": 2}])
        check("json extension recorded", "json" in report["extensions"], report["extensions"])
        check("fts extension recorded", "fts" in report["extensions"], report["extensions"])
        check("vss extension recorded", "vss" in report["extensions"], report["extensions"])
        check("hybrid flag frozen false", report["enable_hybrid_index"] is False)

        hits = report["retrieval_expected"]["hits"]
        check("retrieval uses source similarity", report["retrieval_expected"]["similarity"] == 0.1)
        check("retrieval uses probe top_k cap", report["retrieval_expected"]["top_k"] == PROBE_TOP_K_CAP)
        check("retrieval records top_k cap", report["retrieval_expected"]["top_k_cap"] == PROBE_TOP_K_CAP)
        check("query vector", report["retrieval_expected"]["query_vector"] == SYNTHETIC_QUERY_VECTOR)
        check("two hits above 0.1", len(hits) == 2, hits)
        check("top-1 is alpha", hits[0]["_id"] == "doc_alpha_0" and hits[0]["score"] == 1.0, hits[0])
        check("second is beta", hits[1]["_id"] == "doc_beta_0", hits[1])
        check("top_1 matches first hit", report["retrieval_expected"]["top_1"] == [hits[0]])
        check("gamma filtered by similarity", all(hit["_id"] != "doc_gamma_0" for hit in hits), hits)

        goldenized = report_to_golden(report)
        check("matches frozen golden", goldenized == golden, _golden_diff(golden, goldenized))
        _assert_no_leaks("probe log_lines", list(report["log_lines"]))
        _assert_no_leaks("golden payload", [json.dumps(goldenized, sort_keys=True)])
        return report
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _golden_diff(expected: dict, actual: dict) -> str:
    if expected == actual:
        return ""
    return json.dumps(
        {"expected_keys": sorted(expected.keys()), "actual_keys": sorted(actual.keys())},
        sort_keys=True,
    )


def test_synthetic_builder_refuses_overwrite() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_ow_"))
    try:
        db_path = _build_fixture(tmpdir)
        before = file_signature(db_path)
        raises(lambda: write_synthetic_schema_fixture(db_path), "refusing to overwrite")
        after = file_signature(db_path)
        check("refused overwrite left sha256", before["sha256"] == after["sha256"])
        check("refused overwrite left mtime", before["mtime_ns"] == after["mtime_ns"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_read_only_write_fails() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_ro_"))
    try:
        db_path = _build_fixture(tmpdir)
        before = file_signature(db_path)
        with open_legacy_cache_readonly(db_path) as connection:
            raises(
                lambda: connection.execute(
                    f"INSERT INTO {LEGACY_TABLE} VALUES ('z','z','z','z',[0.0,0.0,0.0,1.0],0.0)"
                ),
                "read-only|readonly",
            )
            raises(
                lambda: connection.execute("CREATE TABLE rag_document(id VARCHAR)"),
                "read-only|readonly",
            )
        after = file_signature(db_path)
        check("write attempt did not mutate sha256", before["sha256"] == after["sha256"])
        check("write attempt did not mutate mtime", before["mtime_ns"] == after["mtime_ns"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_golden_metadata_is_synthetic() -> None:
    golden = _load_golden()
    check("golden corpus kind", golden["metadata"]["corpus_kind"] == SYNTHETIC_CORPUS_KIND)
    check("golden is not a live corpus", golden["metadata"]["corpus_kind"] != LIVE_CORPUS_KIND)
    check("enable_hybrid_index frozen", golden["enable_hybrid_index"] is False)
    check("source dimension remains 1024", golden["source_defaults"]["dimension"] == 1024)
    check("golden retrieval top_k is probe cap", golden["retrieval_expected"]["top_k"] == PROBE_TOP_K_CAP)


def test_dimension_safe_query_vector() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_dim_"))
    try:
        db4 = _build_fixture(tmpdir)
        report = probe_legacy_cache(db4, corpus_kind=SYNTHETIC_CORPUS_KIND)
        check("implicit 4D synthetic vector allowed", report["retrieval_expected"]["query_vector"] == SYNTHETIC_QUERY_VECTOR)

        explicit = probe_legacy_cache(
            db4,
            corpus_kind=SYNTHETIC_CORPUS_KIND,
            query_vector=list(SYNTHETIC_QUERY_VECTOR),
        )
        check("explicit matching 4D vector works", explicit["retrieval_expected"]["hits"] == report["retrieval_expected"]["hits"])

        live_explicit = probe_legacy_cache(
            db4,
            corpus_kind=LIVE_CORPUS_KIND,
            query_vector=list(SYNTHETIC_QUERY_VECTOR),
        )
        check("live kind accepts explicit 4D vector", live_explicit["retrieval_expected"]["query_vector"] == SYNTHETIC_QUERY_VECTOR)
        raises(
            lambda: probe_legacy_cache(db4, corpus_kind=LIVE_CORPUS_KIND),
            r"query vector required",
        )
        raises(
            lambda: probe_legacy_cache(db4, corpus_kind=SYNTHETIC_CORPUS_KIND, query_vector=[1.0, 0.0, 0.0]),
            r"dimension",
        )
        raises(
            lambda: probe_legacy_cache(
                db4,
                corpus_kind=SYNTHETIC_CORPUS_KIND,
                query_vector=[1.0, 0.0, 0.0, 0.0, 0.0],
            ),
            r"dimension",
        )

        db8 = _build_dimension_fixture(tmpdir, 8, name="dim8.db")
        vec8 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        omitted = raises(
            lambda: probe_legacy_cache(db8, corpus_kind=SYNTHETIC_CORPUS_KIND),
            r"query vector required",
        )
        check("omitted non-4D message has no content", all(token not in omitted for token in CONTENT_LEAKS), omitted)
        matched = probe_legacy_cache(db8, corpus_kind=SYNTHETIC_CORPUS_KIND, query_vector=vec8)
        check("explicit 8D vector works", matched["stats"]["dimension"]["observed_dimension"] == 8)
        check("explicit 8D hit", matched["retrieval_expected"]["hits"][0]["_id"] == "doc_d")
        raises(
            lambda: probe_legacy_cache(db8, corpus_kind=SYNTHETIC_CORPUS_KIND, query_vector=list(SYNTHETIC_QUERY_VECTOR)),
            r"dimension",
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_query_vector_from_file() -> None:
    check("4D query vector fixture exists", QUERY_VECTOR_4D_PATH.is_file(), QUERY_VECTOR_4D_PATH.name)
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_qfile_"))
    try:
        db_path = _build_fixture(tmpdir)
        report = probe_legacy_cache(
            db_path,
            corpus_kind=SYNTHETIC_CORPUS_KIND,
            query_vector_file=QUERY_VECTOR_4D_PATH,
        )
        check("file-loaded vector matches 4D fixture", report["retrieval_expected"]["query_vector"] == SYNTHETIC_QUERY_VECTOR)
        check("file-loaded retrieval still ranks alpha first", report["retrieval_expected"]["hits"][0]["_id"] == "doc_alpha_0")

        bad = tmpdir / "bad.json"
        bad.write_text("[1.0, 0.0, 0.0]\n", encoding="utf-8")
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, query_vector_file=bad),
            r"dimension",
        )
        missing = tmpdir / "missing.json"
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, query_vector_file=missing),
            r"query vector file missing",
        )
        raises(
            lambda: probe_legacy_cache(
                db_path,
                corpus_kind=SYNTHETIC_CORPUS_KIND,
                query_vector=list(SYNTHETIC_QUERY_VECTOR),
                query_vector_file=QUERY_VECTOR_4D_PATH,
            ),
            r"not both",
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_bounded_probe_inputs() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_bound_"))
    try:
        db_path = _build_fixture(tmpdir)
        raises(
            lambda: probe_legacy_cache(
                db_path,
                corpus_kind=SYNTHETIC_CORPUS_KIND,
                query_vector=[float("nan"), 0.0, 0.0, 0.0],
            ),
            r"finite",
        )
        raises(
            lambda: probe_legacy_cache(
                db_path,
                corpus_kind=SYNTHETIC_CORPUS_KIND,
                query_vector=[float("inf"), 0.0, 0.0, 0.0],
            ),
            r"finite",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, query_vector=[]),
            r"empty|non-empty",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, similarity=float("nan")),
            r"finite",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, similarity=float("inf")),
            r"finite",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, top_k=0),
            r"positive",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, top_k=-1),
            r"positive",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, top_k=PROBE_TOP_K_CAP + 1),
            r"cap",
        )
        capped = probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND, top_k=1)
        check("explicit in-cap top_k honored", capped["retrieval_expected"]["top_k"] == 1)
        check("top_k=1 returns one hit", len(capped["retrieval_expected"]["hits"]) == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_corpus_kind_allowlist() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_kind_"))
    try:
        db_path = _build_fixture(tmpdir)
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind="not_a_kind"),
            r"invalid corpus_kind",
        )
        raises(
            lambda: probe_legacy_cache(db_path, corpus_kind="/Users/wxl/secret-corpus"),
            r"invalid corpus_kind",
        )
        ok = probe_legacy_cache(
            db_path,
            corpus_kind=LIVE_CORPUS_KIND,
            query_vector=list(SYNTHETIC_QUERY_VECTOR),
        )
        check("live_auto_coder_cache allowed", ok["metadata"]["corpus_kind"] == LIVE_CORPUS_KIND)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cli_sanitized_errors() -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_cli_"))
    try:
        missing_code, missing_out, missing_err = _run_cli([])
        check("cli missing --db exit", missing_code == EXIT_MISSING_DB, missing_code)
        _assert_cli_clean("cli missing --db", missing_out, missing_err)

        missing_db = Path("/Users/wxl/does-not-exist-legacy-probe/byzerai_store_duckdb.db")
        code, out, err = _run_cli(["--db", str(missing_db), "--corpus-kind", SYNTHETIC_CORPUS_KIND])
        check("cli missing file exit", code == EXIT_MISSING_FILE, code)
        _assert_cli_clean("cli missing db", out, err, missing_db)
        check("cli missing db uses path token", "#" in err and "byzerai_store_duckdb.db" in err, err)

        db_path = _build_fixture(tmpdir)
        kind_path = Path("/Users/wxl/secret-corpus")
        code, out, err = _run_cli(["--db", str(db_path), "--corpus-kind", str(kind_path)])
        check("cli invalid corpus_kind exit", code == EXIT_INVALID_CORPUS_KIND, code)
        _assert_cli_clean("cli invalid corpus_kind", out, err, db_path, kind_path)
        check("cli invalid corpus_kind message", "invalid corpus_kind" in err, err)

        vec3 = tmpdir / "q3.json"
        vec3.write_text("[1.0, 0.0, 0.0]\n", encoding="utf-8")
        code, out, err = _run_cli(
            [
                "--db",
                str(db_path),
                "--corpus-kind",
                SYNTHETIC_CORPUS_KIND,
                "--query-vector-file",
                str(vec3),
            ]
        )
        check("cli dimension mismatch exit", code == EXIT_DIMENSION_MISMATCH, code)
        _assert_cli_clean("cli dimension mismatch", out, err, db_path, vec3)

        db8 = _build_dimension_fixture(tmpdir, 8, name="cli-dim8.db")
        code, out, err = _run_cli(["--db", str(db8), "--corpus-kind", SYNTHETIC_CORPUS_KIND])
        check("cli omitted non-4D exit", code == EXIT_DIMENSION_MISMATCH, code)
        _assert_cli_clean("cli omitted non-4D", out, err, db8)

        missing_vec = Path("/Users/wxl/does-not-exist-legacy-probe/query_vector.json")
        code, out, err = _run_cli(
            [
                "--db",
                str(db_path),
                "--query-vector-file",
                str(missing_vec),
            ]
        )
        check("cli missing vector file exit", code == EXIT_MISSING_FILE, code)
        _assert_cli_clean("cli missing vector file", out, err, db_path, missing_vec)

        code, out, err = _run_cli(
            ["--db", str(db_path), "--corpus-kind", SYNTHETIC_CORPUS_KIND, "--top-k", "0"]
        )
        check("cli invalid top_k exit", code == EXIT_INVALID_INPUT, code)
        _assert_cli_clean("cli invalid top_k", out, err, db_path)

        code, out, err = _run_cli(
            [
                "--db",
                str(db_path),
                "--corpus-kind",
                SYNTHETIC_CORPUS_KIND,
                "--query-vector-file",
                str(QUERY_VECTOR_4D_PATH),
            ]
        )
        check("cli file vector success", code == 0, code)
        _assert_cli_clean("cli file vector success", out, err, db_path, QUERY_VECTOR_4D_PATH)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _prepare_immutable_cache(tmpdir: Path) -> tuple[Path, Path, dict]:
    db_path = _build_fixture(tmpdir)
    cache_dir = db_path.parent
    shutil.copy2(SIDECAR_MARKER_PATH, cache_dir / SIDECAR_MARKER_PATH.name)
    wal_path = Path(str(db_path) + ".wal")
    wal_path.write_bytes(b"fake-wal-bytes-not-a-real-duckdb-wal")
    nested = cache_dir / "extra" / "note.txt"
    nested.parent.mkdir()
    nested.write_text("nested sidecar\n", encoding="utf-8")
    return db_path, cache_dir, tree_signatures(cache_dir)


def _assert_cache_frozen(label: str, cache_dir: Path, before: dict) -> None:
    after = tree_signatures(cache_dir)
    check(f"{label} db/wal/sidecar signatures unchanged", before == after, (before, after))


def test_golden_out_rejects_overwrite_and_alias() -> None:
    check("sidecar fixture exists", SIDECAR_MARKER_PATH.is_file(), SIDECAR_MARKER_PATH.name)
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_golden_out_"))
    try:
        db_path, cache_dir, before = _prepare_immutable_cache(tmpdir)
        argv_base = ["--db", str(db_path), "--corpus-kind", SYNTHETIC_CORPUS_KIND]

        code, out, err = _run_cli(argv_base + ["--golden-out", str(db_path)])
        check("exact golden-out==db exit", code == EXIT_INVALID_INPUT, code)
        check("exact collision mentions alias", re.search(r"alias", err, re.I) is not None, err)
        _assert_cli_clean("exact golden-out collision", out, err, db_path)
        _assert_cache_frozen("exact collision", cache_dir, before)

        report = probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND)
        _assert_cache_frozen("probe before dump_golden", cache_dir, before)
        raises(lambda: dump_golden(report, db_path, source_db=db_path), r"alias")
        dotted = db_path.parent / "." / db_path.name
        raises(lambda: dump_golden(report, dotted, source_db=db_path), r"alias")
        _assert_cache_frozen("dump_golden exact/dotted collision", cache_dir, before)

        link_out = tmpdir / "golden-link.json"
        link_out.symlink_to(db_path)
        link_stat = file_signature(db_path)
        code, out, err = _run_cli(argv_base + ["--golden-out", str(link_out)])
        check("symlink golden-out->db exit", code == EXIT_INVALID_INPUT, code)
        check("symlink golden-out mentions alias", re.search(r"alias", err, re.I) is not None, err)
        _assert_cli_clean("symlink golden-out collision", out, err, db_path, link_out)
        check("symlink golden-out still a symlink", link_out.is_symlink())
        check(
            "symlink golden-out still points at db",
            link_out.resolve() == db_path.resolve(),
        )
        after_link = file_signature(db_path)
        check("symlink collision left db sha256", link_stat["sha256"] == after_link["sha256"])
        check("symlink collision left db mtime", link_stat["mtime_ns"] == after_link["mtime_ns"])
        _assert_cache_frozen("symlink golden-out->db", cache_dir, before)

        db_link = tmpdir / "linked-cache.db"
        db_link.symlink_to(db_path)
        code, out, err = _run_cli(
            ["--db", str(db_link), "--corpus-kind", SYNTHETIC_CORPUS_KIND, "--golden-out", str(db_path)]
        )
        check("symlink db golden-out=real exit", code == EXIT_INVALID_INPUT, code)
        check("symlink db mentions alias", re.search(r"alias", err, re.I) is not None, err)
        _assert_cli_clean("symlink db collision", out, err, db_path, db_link)
        _assert_cache_frozen("symlink db vice versa", cache_dir, before)
        raises(lambda: dump_golden(report, db_link, source_db=db_path), r"alias")
        raises(lambda: dump_golden(report, db_path, source_db=db_link), r"alias")
        _assert_cache_frozen("dump_golden symlink collision", cache_dir, before)

        existing = tmpdir / "existing-golden.json"
        existing_payload = "ORIGINAL_GOLDEN_PAYLOAD_DO_NOT_TRUNCATE\n"
        existing.write_text(existing_payload, encoding="utf-8")
        existing_sig = file_signature(existing)
        code, out, err = _run_cli(argv_base + ["--golden-out", str(existing)])
        check("existing golden-out exit", code == EXIT_INVALID_INPUT, code)
        check(
            "existing dest mentions overwrite",
            re.search(r"overwrite|existing", err, re.I) is not None,
            err,
        )
        _assert_cli_clean("existing golden-out", out, err, db_path, existing)
        after_existing = file_signature(existing)
        check("existing golden sha256 unchanged", existing_sig["sha256"] == after_existing["sha256"])
        check("existing golden size unchanged", existing_sig["size"] == after_existing["size"])
        check("existing golden mtime_ns unchanged", existing_sig["mtime_ns"] == after_existing["mtime_ns"])
        check(
            "existing golden bytes unchanged",
            existing.read_text(encoding="utf-8") == existing_payload,
        )
        _assert_cache_frozen("existing golden dest", cache_dir, before)
        raises(lambda: dump_golden(report, existing, source_db=db_path), r"overwrite|existing")
        _assert_cache_frozen("dump_golden existing dest", cache_dir, before)
        check(
            "direct dump_golden did not truncate existing",
            existing.read_text(encoding="utf-8") == existing_payload,
        )

        ok_dest = tmpdir / "ok" / "golden.json"
        code, out, err = _run_cli(argv_base + ["--golden-out", str(ok_dest)])
        check("golden-out exclusive create exit", code == 0, code)
        check("golden-out wrote new file", ok_dest.is_file())
        _assert_cli_clean("golden-out success", out, err, db_path, ok_dest)
        _assert_cache_frozen("successful golden-out", cache_dir, before)
        written_sig = file_signature(ok_dest)
        written_text = ok_dest.read_text(encoding="utf-8")
        code, out, err = _run_cli(argv_base + ["--golden-out", str(ok_dest)])
        check("second golden-out exclusive create rejected", code == EXIT_INVALID_INPUT, code)
        check(
            "second write overwrite error",
            re.search(r"overwrite|existing", err, re.I) is not None,
            err,
        )
        _assert_cli_clean("second golden-out", out, err, db_path, ok_dest)
        after_second = file_signature(ok_dest)
        check("second write did not truncate sha256", written_sig["sha256"] == after_second["sha256"])
        check("second write did not mutate mtime", written_sig["mtime_ns"] == after_second["mtime_ns"])
        check("second write left bytes", ok_dest.read_text(encoding="utf-8") == written_text)
        _assert_cache_frozen("second golden-out rejected", cache_dir, before)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sanitize_cli_text_arbitrary_roots() -> None:
    for raw in ABS_PATH_SAMPLES + WHITESPACE_PATH_SAMPLES:
        check(f"independent oracle flags unredacted {raw}", _independent_path_leak(raw, raw) is not None, raw)
        redacted = sanitize_cli_text(raw, known_paths=(raw,))
        leak = _independent_path_leak(redacted, raw)
        check(f"known_paths sanitize omits {raw}", leak is None, leak or redacted)
        check(f"sanitize tokenizes {raw}", "#" in redacted, redacted)
        wrapped = f"cannot open {raw} for probe"
        redacted_wrapped = sanitize_cli_text(wrapped, known_paths=(raw,))
        wrapped_leak = _independent_path_leak(redacted_wrapped, raw)
        check(f"wrapped known_paths sanitize omits {raw}", wrapped_leak is None, wrapped_leak or redacted_wrapped)
        err = ProbeInputError(f"cannot open {raw}", paths=(raw,))
        check(f"ProbeError(paths=) omits {raw}", _independent_path_leak(str(err), raw) is None, str(err))
        check(f"ProbeError args omit {raw}", all(_independent_path_leak(str(arg), raw) is None for arg in err.args), err.args)
        check("ProbeInputError is ProbeError", isinstance(err, ProbeError))
        token = path_token(raw)
        check(f"path_token basename omits dirs for {raw}", raw not in token, token)
        check(f"path_token has no unix root for {raw}", not token.startswith("/"), token)
        check(f"path_token has no unc for {raw}", not token.startswith("\\"), token)
        check(f"path_token uses leaf for {raw}", _leaf_name(raw) in token.split("#", 1)[0] or "#" in token, token)

    generic = sanitize_cli_text("/data/secret.db")
    check("generic scanner tokenizes unix root", _independent_path_leak(generic, "/data/secret.db") is None, generic)
    spaced = sanitize_cli_text("cannot open /Users/x/My Secret/db.sqlite now")
    check(
        "generic scanner does not leave My Secret/db.sqlite",
        _independent_path_leak(spaced, "/Users/x/My Secret/db.sqlite") is None,
        spaced,
    )

    relative = "sample/alpha.txt"
    check("relative path is not an abs leak", _independent_abs_path_leak(relative) is None, relative)
    check("sanitize leaves relative path", sanitize_cli_text(relative) == relative)

    fake_leak = "error opening /data/secret.db now"
    check("independent oracle flags unredacted unix root", _independent_abs_path_leak(fake_leak) is not None)

    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_abscli_"))
    try:
        missing_unix = (
            Path("/data/does-not-exist-legacy-probe/byzerai_store_duckdb.db"),
            Path("/mnt/foo/byzerai_store_duckdb.db"),
            Path("/root/x/byzerai_store_duckdb.db"),
        )
        for missing in missing_unix:
            code, out, err = _run_cli(["--db", str(missing), "--corpus-kind", SYNTHETIC_CORPUS_KIND])
            blob = out + err
            check(f"cli missing {missing.as_posix()} exit", code == EXIT_MISSING_FILE, code)
            _assert_cli_clean(f"cli missing {missing.name}", out, err, missing)
            check(f"cli omits {missing.as_posix()}", str(missing) not in blob)

        win = r"C:\Users\does-not-exist-legacy-probe\secret.db"
        code, out, err = _run_cli(["--db", win, "--corpus-kind", SYNTHETIC_CORPUS_KIND])
        blob = out + err
        check("cli missing windows drive exit", code == EXIT_MISSING_FILE, code)
        _assert_cli_clean("cli missing windows drive", out, err)
        check("cli omits windows drive path", win not in blob)

        unc = r"\\server\share\does-not-exist-legacy-probe.db"
        code, out, err = _run_cli(["--db", unc, "--corpus-kind", SYNTHETIC_CORPUS_KIND])
        blob = out + err
        check("cli missing unc exit", code == EXIT_MISSING_FILE, code)
        _assert_cli_clean("cli missing unc", out, err)
        check("cli omits unc path", unc not in blob)

        db_path = _build_fixture(tmpdir)
        vec = Path("/mnt/foo/does-not-exist-legacy-probe-vector.json")
        code, out, err = _run_cli(
            [
                "--db",
                str(db_path),
                "--corpus-kind",
                SYNTHETIC_CORPUS_KIND,
                "--query-vector-file",
                str(vec),
            ]
        )
        blob = out + err
        check("cli missing /mnt vector exit", code == EXIT_MISSING_FILE, code)
        _assert_cli_clean("cli missing /mnt vector", out, err, db_path, vec)
        check("cli omits /mnt vector path", str(vec) not in blob)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_recursive_immutability_with_sidecars() -> None:
    check("sidecar fixture exists", SIDECAR_MARKER_PATH.is_file(), SIDECAR_MARKER_PATH.name)
    tmpdir = Path(tempfile.mkdtemp(prefix="legacy_cache_probe_side_"))
    try:
        db_path = _build_fixture(tmpdir)
        cache_dir = db_path.parent
        shutil.copy2(SIDECAR_MARKER_PATH, cache_dir / SIDECAR_MARKER_PATH.name)
        wal_path = Path(str(db_path) + ".wal")
        wal_path.write_bytes(b"fake-wal-bytes-not-a-real-duckdb-wal")
        nested = cache_dir / "extra" / "note.txt"
        nested.parent.mkdir()
        nested.write_text("nested sidecar\n", encoding="utf-8")
        before = tree_signatures(cache_dir)
        check("signature includes db", LEGACY_DB_FILENAME in before, sorted(before))
        check("signature includes wal", f"{LEGACY_DB_FILENAME}.wal" in before, sorted(before))
        check("signature includes sidecar", SIDECAR_MARKER_PATH.name in before, sorted(before))
        check("signature includes nested sidecar", "extra/note.txt" in before, sorted(before))
        probe_legacy_cache(db_path, corpus_kind=SYNTHETIC_CORPUS_KIND)
        after = tree_signatures(cache_dir)
        check("recursive db/wal/sidecar signatures unchanged", before == after, (before, after))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    test_pinned_runtime()
    test_probe_source_is_read_only()
    test_golden_metadata_is_synthetic()
    test_synthetic_probe_matches_golden()
    test_synthetic_builder_refuses_overwrite()
    test_read_only_write_fails()
    test_dimension_safe_query_vector()
    test_query_vector_from_file()
    test_bounded_probe_inputs()
    test_corpus_kind_allowlist()
    test_cli_sanitized_errors()
    test_golden_out_rejects_overwrite_and_alias()
    test_sanitize_cli_text_arbitrary_roots()
    test_recursive_immutability_with_sidecars()
    print("[legacy_cache_probe] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
