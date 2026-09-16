"""Phase 0 read-only probe for auto-coder `.cache/byzerai_store_duckdb.db`.

Authority: docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md §3.6 / §6 Phase 0 item 4.

This module never writes the probed file, never INSTALL-s extensions, and never
creates a v7 catalog. Ordinary logs use basename+hash tokens, not absolute paths
or raw content.

Source (auto_coder-3.0.74):
- rag/cache/local_duckdb_storage_cache.py
  DuckDBLocalContext loads json/fts/vss; database_name=byzerai_store_duckdb.db;
  table_name=rag_duckdb; CREATE TABLE _id VARCHAR, file_path VARCHAR, content TEXT,
  raw_content TEXT, vector FLOAT[], mtime FLOAT; vector_search uses
  list_cosine_similarity(vector, ?) with score IS NOT NULL AND score >= ? LIMIT ?.
- common/__init__.py AutoCoderArgs
  rag_duckdb_vector_dim=1024, rag_duckdb_query_similarity=0.1,
  rag_duckdb_query_top_k=10000, enable_hybrid_index=False.

Probe LIMIT is PROBE_TOP_K_CAP, not AutoCoderArgs top_k=10000. Implicit
SYNTHETIC_QUERY_VECTOR is allowed only for synthetic 4D fixtures whose observed
dimension is 4. Retrieval never pads or truncates query vectors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import duckdb

GOLDEN_VERSION = 1
LEGACY_DB_FILENAME = "byzerai_store_duckdb.db"
LEGACY_TABLE = "rag_duckdb"
SAMPLE_LIMIT = 16
SCORE_DECIMALS = 8

# Diagnostic LIMIT cap. Source default 10000 is recorded but not used as-is.
PROBE_TOP_K_CAP = 32

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_MISSING_DB = 2
EXIT_INVALID_CORPUS_KIND = 3
EXIT_DIMENSION_MISMATCH = 4
EXIT_MISSING_FILE = 5
EXIT_INVALID_INPUT = 6

# Frozen from AutoCoderArgs / LocalDuckDBStorageCache (see module docstring).
SOURCE_DEFAULTS: dict[str, Any] = {
    "database_filename": LEGACY_DB_FILENAME,
    "table_name": LEGACY_TABLE,
    "similarity": 0.1,
    "top_k": 10000,
    "dimension": 1024,
    "enable_hybrid_index": False,
    "extensions": ["json", "fts", "vss"],
    "columns": [
        {"name": "_id", "source_type": "VARCHAR"},
        {"name": "file_path", "source_type": "VARCHAR"},
        {"name": "content", "source_type": "TEXT"},
        {"name": "raw_content", "source_type": "TEXT"},
        {"name": "vector", "source_type": "FLOAT[]"},
        {"name": "mtime", "source_type": "FLOAT"},
    ],
}

SOURCE_CITATIONS = {
    "storage_cache": "auto_coder-3.0.74/src/autocoder/rag/cache/local_duckdb_storage_cache.py",
    "autocoder_args": "auto_coder-3.0.74/src/autocoder/common/__init__.py",
}

# Exact retrieval shape from LocalDuckdbStorage.vector_search (table name frozen).
LEGACY_VECTOR_SEARCH_SQL = """
SELECT _id, file_path, mtime, score
FROM (
    SELECT *, list_cosine_similarity(vector, ?) AS score
    FROM rag_duckdb
) sq
WHERE score IS NOT NULL
AND score >= ?
ORDER BY score DESC LIMIT ?;
""".strip()

# Tiny schema-compatible rows for unit tests when no live cache exists.
# Observed dimension is 4 by design; source default dimension remains 1024.
SYNTHETIC_CORPUS_KIND = "synthetic_from_source_schema"
LIVE_CORPUS_KIND = "live_auto_coder_cache"
ALLOWED_CORPUS_KINDS = frozenset({SYNTHETIC_CORPUS_KIND, LIVE_CORPUS_KIND})
SYNTHETIC_QUERY_VECTOR: list[float] = [1.0, 0.0, 0.0, 0.0]
SYNTHETIC_QUERY_DIMENSION = len(SYNTHETIC_QUERY_VECTOR)
SYNTHETIC_DDL = """
CREATE TABLE rag_duckdb (
    _id VARCHAR,
    file_path VARCHAR,
    content TEXT,
    raw_content TEXT,
    vector FLOAT[],
    mtime FLOAT
);
""".strip()
SYNTHETIC_ROWS: tuple[dict[str, Any], ...] = (
    {
        "_id": "doc_alpha_0",
        "file_path": "sample/alpha.txt",
        "content": "alpha one",
        "raw_content": "alpha one",
        "vector": [1.0, 0.0, 0.0, 0.0],
        "mtime": 1000.0,
    },
    {
        "_id": "doc_beta_0",
        "file_path": "sample/beta.txt",
        "content": "beta two",
        "raw_content": "beta two",
        "vector": [0.6, 0.8, 0.0, 0.0],
        "mtime": 1001.0,
    },
    {
        "_id": "doc_gamma_0",
        "file_path": "sample/gamma.txt",
        "content": "gamma three",
        "raw_content": "gamma three",
        "vector": [0.0, 1.0, 0.0, 0.0],
        "mtime": 1002.0,
    },
    {
        "_id": "doc_nullvec_0",
        "file_path": "sample/nullvec.txt",
        "content": "null vector row",
        "raw_content": "null vector row",
        "vector": None,
        "mtime": 1003.0,
    },
    {
        "_id": "doc_dup_0",
        "file_path": "sample/dup_a.txt",
        "content": "dup a",
        "raw_content": "dup a",
        "vector": [0.0, 0.0, 1.0, 0.0],
        "mtime": 1004.0,
    },
    {
        "_id": "doc_dup_0",
        "file_path": "sample/dup_b.txt",
        "content": "dup b",
        "raw_content": "dup b",
        "vector": [0.0, 0.0, 0.0, 1.0],
        "mtime": 1005.0,
    },
)

_READ_ONLY_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
}

# Bounded generic scanner only. Known paths passed via paths=/known_paths= are
# the guaranteed redaction surface. Arbitrary exception text is not a parser.
_HARD_PATH_DELIMITERS = frozenset("\"',;()[]{}\n\r")


def _strip_wrapping_quotes(text: str) -> str:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _path_for_basename(path: Path | str) -> str:
    text = _strip_wrapping_quotes(str(path))
    lower = text.lower()
    if lower.startswith("file:"):
        rest = text[5:]
        if rest.startswith("///"):
            text = rest[2:]
        elif rest.startswith("//"):
            hostpath = rest[2:]
            slash = hostpath.find("/")
            text = hostpath[slash:] if slash >= 0 else hostpath
        else:
            text = rest
    if text.startswith("\\\\?\\"):
        body = text[4:]
        if body.startswith("UNC\\") or body.startswith("UNC/"):
            text = "\\\\" + body[4:]
        else:
            text = body
    return text


def path_token(path: Path | str) -> str:
    """Log-safe token: basename plus hash of the full path, never the path itself."""
    raw = str(path)
    digest = hashlib.sha256(os.fsencode(raw)).hexdigest()[:12]
    normalized = _path_for_basename(raw)
    unified = normalized.replace("\\", "/")
    parts = [part for part in unified.split("/") if part and part != "."]
    if parts and len(parts[0]) == 2 and parts[0][1] == ":":
        parts = parts[1:]
    name = parts[-1] if parts else (Path(normalized).name or "path")
    name = name.split("?")[0].split("#")[0]
    if not name:
        name = "path"
    return f"{name}#{digest}"


def _known_path_variants(path: Path | str) -> list[str]:
    raw = str(path)
    stripped = _strip_wrapping_quotes(raw)
    variants = [raw, stripped]
    posix = stripped.replace("\\", "/")
    windows = stripped.replace("/", "\\")
    variants.extend([posix, windows])
    if stripped.startswith("/") and not stripped.lower().startswith("file:"):
        variants.extend(
            [
                f"file://{stripped}",
                f"file://{posix}",
                f"file:{stripped}",
            ]
        )
    quoted = []
    for item in list(variants):
        quoted.append(f'"{item}"')
        quoted.append(f"'{item}'")
    variants.extend(quoted)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    ordered.sort(key=len, reverse=True)
    return ordered


def _replace_known_paths(text: str, known_paths: Iterable[Path | str]) -> str:
    redacted = text
    for path in known_paths:
        token = path_token(path)
        for variant in _known_path_variants(path):
            if variant in redacted:
                redacted = redacted.replace(variant, token)
    return redacted


def _is_abs_path_start(text: str, index: int) -> int | None:
    if index >= len(text):
        return None
    rest = text[index:]
    lower = rest.lower()
    prev = text[index - 1] if index else ""
    if rest[:1] in {"'", '"'}:
        inner = _is_abs_path_start(text, index + 1)
        if inner is not None:
            return 0
    if lower.startswith("file:"):
        return 5
    if rest.startswith("\\\\?\\"):
        return 4
    if rest.startswith("\\\\"):
        return 2
    if len(rest) >= 3 and rest[0].isalpha() and rest[1] == ":" and rest[2] in "\\/":
        return 2
    if rest.startswith("/") and not (prev and (prev.isalnum() or prev in "_.-")):
        return 1
    return None


def _consume_path_span(text: str, start: int, prefix_len: int) -> int:
    index = start + prefix_len
    if start < len(text) and text[start] in "'\"":
        quote = text[start]
        index = start + 1
        while index < len(text) and text[index] != quote:
            index += 1
        if index < len(text):
            index += 1
        return index
    while index < len(text):
        ch = text[index]
        if ch in _HARD_PATH_DELIMITERS:
            break
        index += 1
    return index


def _scan_generic_paths(text: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(text):
        prefix_len = _is_abs_path_start(text, index)
        if prefix_len is None:
            pieces.append(text[index])
            index += 1
            continue
        end = _consume_path_span(text, index, prefix_len)
        span = text[index:end]
        pieces.append(path_token(span))
        index = end
    return "".join(pieces)


def sanitize_cli_text(text: str, *, known_paths: Iterable[Path | str] = ()) -> str:
    """Replace known and recognized absolute paths with path_token.

    Guarantee: every path passed in known_paths is tokenized in full, including
    spaces, tabs, Unicode whitespace, quotes, file: URIs, Windows extended
    paths, and UNC paths. Recognized generic absolute-path forms are redacted
    by a bounded scanner that prefers over-redaction to leakage. Arbitrary
    third-party exception text is not a fully reliable path parser; main()
    maps unknown exceptions to the fixed message `unexpected error`.
    """
    redacted = _replace_known_paths(text, known_paths)
    return _scan_generic_paths(redacted)


class ProbeError(Exception):
    """Sanitized probe failure. Messages must not include absolute paths or raw content."""

    exit_code = EXIT_UNEXPECTED

    def __init__(self, message: str = "", *, paths: Iterable[Path | str] = ()) -> None:
        self.known_paths = tuple(paths)
        super().__init__(sanitize_cli_text(message, known_paths=self.known_paths))


class InvalidCorpusKindError(ProbeError):
    exit_code = EXIT_INVALID_CORPUS_KIND


class DimensionMismatchError(ProbeError):
    exit_code = EXIT_DIMENSION_MISMATCH


class ProbeInputError(ProbeError):
    exit_code = EXIT_INVALID_INPUT


def sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "sha256": file_sha256(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def tree_signatures(root: Path) -> dict[str, dict[str, Any]]:
    """Recursive size/mtime/SHA for every file under root, including WAL and sidecars."""
    signatures: dict[str, dict[str, Any]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            signatures[rel] = file_signature(path)
    return signatures


def _round_score(value: Any) -> float:
    return round(float(value), SCORE_DECIMALS)


def _hash_record(_id: Any, file_path: Any, content: Any, raw_content: Any, mtime: Any, vector: Any) -> dict[str, Any]:
    vector_len = None if vector is None else len(vector)
    vector_digest = None
    if vector is not None:
        packed = json.dumps([_round_score(x) for x in vector], separators=(",", ":"))
        vector_digest = sha256_text(packed)
    return {
        "_id": None if _id is None else str(_id),
        "file_path_sha256": sha256_text(None if file_path is None else str(file_path)),
        "content_sha256": sha256_text(None if content is None else str(content)),
        "raw_content_sha256": sha256_text(None if raw_content is None else str(raw_content)),
        "mtime": None if mtime is None else float(mtime),
        "vector_len": vector_len,
        "vector_sha256": vector_digest,
    }


@contextmanager
def open_legacy_cache_readonly(database_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if not database_path.is_file():
        raise FileNotFoundError(
            sanitize_cli_text(
                f"legacy cache missing: {database_path}",
                known_paths=(database_path,),
            )
        )
    connection = duckdb.connect(
        str(database_path),
        read_only=True,
        config=dict(_READ_ONLY_CONFIG),
    )
    try:
        yield connection
    finally:
        connection.close()


def _extension_status(connection: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT extension_name, loaded, installed, install_path
        FROM duckdb_extensions()
        WHERE extension_name IN ('json', 'fts', 'vss')
        ORDER BY extension_name
        """
    ).fetchall()
    status: dict[str, dict[str, Any]] = {}
    for name, loaded, installed, install_path in rows:
        origin = "unavailable"
        if install_path == "(BUILT-IN)":
            origin = "built-in"
        elif installed:
            origin = "installed"
        status[str(name)] = {
            "loaded": bool(loaded),
            "installed": bool(installed),
            "origin": origin,
        }
    for name in SOURCE_DEFAULTS["extensions"]:
        status.setdefault(name, {"loaded": False, "installed": False, "origin": "unavailable"})
    return status


def _list_user_tables(connection: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name
        """
    ).fetchall()
    return [
        {"schema": str(schema), "name": str(name), "type": str(table_type)}
        for schema, name, table_type in rows
    ]


def _columns(connection: duckdb.DuckDBPyConnection, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT column_name, data_type, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name = ?
        ORDER BY ordinal_position
        """,
        [table],
    ).fetchall()
    return [
        {
            "name": str(name),
            "observed_type": str(data_type),
            "nullable": str(is_nullable).upper() == "YES",
            "ordinal": int(ordinal),
        }
        for name, data_type, is_nullable, ordinal in rows
    ]


def _null_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    row = connection.execute(
        f"""
        SELECT
            count(*) FILTER (_id IS NULL),
            count(*) FILTER (file_path IS NULL),
            count(*) FILTER (content IS NULL),
            count(*) FILTER (raw_content IS NULL),
            count(*) FILTER (vector IS NULL),
            count(*) FILTER (mtime IS NULL)
        FROM {LEGACY_TABLE}
        """
    ).fetchone()
    assert row is not None
    names = ["_id", "file_path", "content", "raw_content", "vector", "mtime"]
    return {name: int(value) for name, value in zip(names, row)}


def _duplicate_ids(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT _id, count(*) AS n
        FROM {LEGACY_TABLE}
        GROUP BY _id
        HAVING count(*) > 1
        ORDER BY _id
        """
    ).fetchall()
    return [{"_id": None if _id is None else str(_id), "count": int(n)} for _id, n in rows]


def _dimension_stats(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    row = connection.execute(
        f"""
        SELECT
            min(len(vector)),
            max(len(vector)),
            count(DISTINCT len(vector)),
            count(*) FILTER (vector IS NOT NULL)
        FROM {LEGACY_TABLE}
        """
    ).fetchone()
    assert row is not None
    min_dim, max_dim, distinct_dims, non_null = row
    mixed = int(distinct_dims or 0) > 1
    observed = None
    if non_null and min_dim is not None and not mixed:
        observed = int(min_dim)
    return {
        "min": None if min_dim is None else int(min_dim),
        "max": None if max_dim is None else int(max_dim),
        "distinct_lengths": int(distinct_dims or 0),
        "non_null_vectors": int(non_null),
        "observed_dimension": observed,
        "mixed": mixed,
    }


def _golden_records(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT _id, file_path, content, raw_content, mtime, vector
        FROM {LEGACY_TABLE}
        ORDER BY _id NULLS LAST, mtime NULLS LAST
        LIMIT {SAMPLE_LIMIT}
        """
    ).fetchall()
    return [_hash_record(*row) for row in rows]


def _run_legacy_retrieval(
    connection: duckdb.DuckDBPyConnection,
    query_vector: Sequence[float],
    *,
    similarity: float,
    top_k: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        LEGACY_VECTOR_SEARCH_SQL,
        [list(query_vector), similarity, top_k],
    ).fetchall()
    hits: list[dict[str, Any]] = []
    for _id, file_path, mtime, score in rows:
        hits.append(
            {
                "_id": None if _id is None else str(_id),
                "file_path_sha256": sha256_text(None if file_path is None else str(file_path)),
                "mtime": None if mtime is None else float(mtime),
                "score": _round_score(score),
            }
        )
    return hits


def validate_corpus_kind(corpus_kind: str) -> str:
    if corpus_kind not in ALLOWED_CORPUS_KINDS:
        raise InvalidCorpusKindError("invalid corpus_kind")
    return corpus_kind


def _require_finite_number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeInputError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ProbeInputError(f"{name} must be a finite number")
    return number


def validate_query_vector(query_vector: Sequence[Any]) -> list[float]:
    if query_vector is None or len(query_vector) == 0:
        raise ProbeInputError("query_vector must be non-empty")
    return [_require_finite_number("query_vector", item) for item in query_vector]


def validate_similarity(similarity: Any) -> float:
    return _require_finite_number("similarity", similarity)


def validate_top_k(top_k: Any) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ProbeInputError("top_k must be a positive integer")
    if top_k <= 0:
        raise ProbeInputError("top_k must be a positive integer")
    if top_k > PROBE_TOP_K_CAP:
        raise ProbeInputError(f"top_k exceeds probe cap {PROBE_TOP_K_CAP}")
    return top_k


def load_query_vector_file(path: Path | str) -> list[float]:
    vector_path = Path(path)
    if not vector_path.is_file():
        raise FileNotFoundError(
            sanitize_cli_text(
                f"query vector file missing: {vector_path}",
                known_paths=(vector_path,),
            )
        )
    try:
        payload = json.loads(vector_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ProbeInputError("query vector file is not valid JSON") from None
    if not isinstance(payload, list):
        raise ProbeInputError("query vector file must be a JSON list of floats")
    return validate_query_vector(payload)


def _resolve_query_vector(
    query_vector: Sequence[float] | None,
    *,
    observed_dimension: int | None,
    mixed: bool,
    corpus_kind: str,
) -> list[float]:
    if mixed:
        raise DimensionMismatchError("mixed vector dimensions; retrieval refused")
    if observed_dimension is None:
        raise DimensionMismatchError("observed vector dimension unavailable; retrieval refused")
    if query_vector is None:
        if corpus_kind == SYNTHETIC_CORPUS_KIND and observed_dimension == SYNTHETIC_QUERY_DIMENSION:
            return list(SYNTHETIC_QUERY_VECTOR)
        raise DimensionMismatchError(
            f"query vector required for observed_dimension={observed_dimension}"
        )
    resolved = list(query_vector)
    if len(resolved) != observed_dimension:
        raise DimensionMismatchError(
            f"query vector dimension {len(resolved)} != observed_dimension {observed_dimension}"
        )
    return resolved


def write_synthetic_schema_fixture(destination: Path) -> Path:
    """Create a tiny schema-compatible DuckDB file for unit tests.

    Not called by probe_legacy_cache. Caller supplies a new path; this must not
    be used to mutate a live auto-coder cache.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            sanitize_cli_text(
                f"refusing to overwrite existing file {destination}",
                known_paths=(destination,),
            )
        )
    connection = duckdb.connect(str(destination))
    try:
        connection.execute(SYNTHETIC_DDL)
        insert_sql = f"INSERT INTO {LEGACY_TABLE} VALUES (?, ?, ?, ?, ?, ?)"
        for row in SYNTHETIC_ROWS:
            connection.execute(
                insert_sql,
                [
                    row["_id"],
                    row["file_path"],
                    row["content"],
                    row["raw_content"],
                    row["vector"],
                    row["mtime"],
                ],
            )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    return destination


def probe_legacy_cache(
    database_path: Path | str,
    *,
    corpus_kind: str,
    query_vector: Sequence[float] | None = None,
    query_vector_file: Path | str | None = None,
    similarity: float | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Inspect a legacy cache file without writing it."""
    validate_corpus_kind(corpus_kind)
    path = Path(database_path)
    if query_vector is not None and query_vector_file is not None:
        raise ProbeInputError("provide query_vector or query_vector_file, not both")
    provided_vector: list[float] | None = None
    if query_vector_file is not None:
        provided_vector = load_query_vector_file(query_vector_file)
    elif query_vector is not None:
        provided_vector = validate_query_vector(query_vector)
    similarity_value = (
        SOURCE_DEFAULTS["similarity"] if similarity is None else validate_similarity(similarity)
    )
    top_k_value = PROBE_TOP_K_CAP if top_k is None else validate_top_k(top_k)
    logs: list[str] = []
    logs.append(f"open read_only {path_token(path)}")

    with open_legacy_cache_readonly(path) as connection:
        access_mode = connection.execute(
            "SELECT value FROM duckdb_settings() WHERE name = 'access_mode'"
        ).fetchone()
        library_version, source_id = connection.execute(
            "SELECT library_version, source_id FROM pragma_version()"
        ).fetchone()
        extensions = _extension_status(connection)
        tables = _list_user_tables(connection)
        table_names = [row["name"] for row in tables]
        if LEGACY_TABLE not in table_names:
            raise RuntimeError(f"missing table {LEGACY_TABLE}; found {table_names}")
        columns = _columns(connection, LEGACY_TABLE)
        row_count = int(connection.execute(f"SELECT count(*) FROM {LEGACY_TABLE}").fetchone()[0])
        nulls = _null_counts(connection)
        duplicates = _duplicate_ids(connection)
        dimensions = _dimension_stats(connection)
        records = _golden_records(connection)
        query = _resolve_query_vector(
            provided_vector,
            observed_dimension=dimensions["observed_dimension"],
            mixed=dimensions["mixed"],
            corpus_kind=corpus_kind,
        )
        hits = _run_legacy_retrieval(
            connection,
            query,
            similarity=similarity_value,
            top_k=top_k_value,
        )
        top1 = hits[:1]
        logs.append(
            f"table={LEGACY_TABLE} rows={row_count} dim={dimensions['observed_dimension']} "
            f"dup_ids={len(duplicates)} hits={len(hits)}"
        )

    report: dict[str, Any] = {
        "golden_version": GOLDEN_VERSION,
        "metadata": {
            "corpus_kind": corpus_kind,
            "source_citations": SOURCE_CITATIONS,
            "sample_limit": SAMPLE_LIMIT,
        },
        "source_defaults": SOURCE_DEFAULTS,
        "duckdb": {
            "package": duckdb.__version__,
            "library_version": library_version,
            "source_id": source_id,
            "access_mode": None if access_mode is None else access_mode[0],
        },
        "extensions": extensions,
        "enable_hybrid_index": SOURCE_DEFAULTS["enable_hybrid_index"],
        "schema_snapshot": {
            "tables": tables,
            "columns": columns,
            "type_notes": "DuckDB information_schema reports TEXT as VARCHAR",
        },
        "stats": {
            "row_count": row_count,
            "null_counts": nulls,
            "duplicate_ids": duplicates,
            "dimension": dimensions,
        },
        "golden_records": records,
        "retrieval_expected": {
            "sql": LEGACY_VECTOR_SEARCH_SQL,
            "query_vector": query,
            "similarity": similarity_value,
            "top_k": top_k_value,
            "top_k_cap": PROBE_TOP_K_CAP,
            "hits": hits,
            "top_1": top1,
        },
        "log_lines": logs,
        "db_token": path_token(path),
        "db_sha256": file_sha256(path),
    }
    return report


def report_to_golden(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "golden_version": report["golden_version"],
        "metadata": report["metadata"],
        "source_defaults": report["source_defaults"],
        "duckdb": report["duckdb"],
        "extensions": report["extensions"],
        "enable_hybrid_index": report["enable_hybrid_index"],
        "schema_snapshot": report["schema_snapshot"],
        "stats": report["stats"],
        "golden_records": report["golden_records"],
        "retrieval_expected": report["retrieval_expected"],
    }


def _paths_alias(left: Path | str, right: Path | str) -> bool:
    a = Path(left)
    b = Path(right)
    if a == b:
        return True
    try:
        if a.resolve() == b.resolve():
            return True
    except OSError:
        pass
    try:
        if a.exists() and b.exists() and a.samefile(b):
            return True
    except OSError:
        pass
    return False


def _path_exists_or_symlink(path: Path) -> bool:
    try:
        return path.is_symlink() or path.exists()
    except OSError:
        return False


def _reject_golden_destination(destination: Path, source: Path) -> None:
    if _paths_alias(destination, source):
        raise ProbeInputError(
            f"refusing golden-out alias of probed db {source}",
            paths=(source, destination),
        )
    if _path_exists_or_symlink(destination):
        raise ProbeInputError(
            f"refusing to overwrite existing golden destination {destination}",
            paths=(destination,),
        )


def dump_golden(
    report: Mapping[str, Any],
    destination: Path,
    *,
    source_db: Path | str,
) -> Path:
    """Write redacted golden JSON using exclusive create. Never aliases --db."""
    destination = Path(destination)
    source = Path(source_db)
    _reject_golden_destination(destination, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_golden_destination(destination, source)
    payload = json.dumps(report_to_golden(report), indent=2, sort_keys=True) + "\n"
    try:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError:
        raise ProbeInputError(
            f"refusing to overwrite existing golden destination {destination}",
            paths=(destination,),
        ) from None
    return destination


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only probe of auto-coder DuckDB cache")
    parser.add_argument("--db", type=Path, help="Path to byzerai_store_duckdb.db")
    parser.add_argument("--corpus-kind", default=SYNTHETIC_CORPUS_KIND)
    parser.add_argument("--query-vector-file", type=Path, help="JSON list of floats matching observed dimension")
    parser.add_argument("--similarity", type=float, help="Finite similarity threshold (default: source 0.1)")
    parser.add_argument("--top-k", type=int, help=f"Positive LIMIT up to probe cap {PROBE_TOP_K_CAP}")
    parser.add_argument("--golden-out", type=Path, help="Write redacted golden JSON (not the cache)")
    return parser.parse_args(argv)


def _exit_error(message: str, code: int) -> int:
    print(sanitize_cli_text(message), file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        if args.db is None:
            print("no --db given; live cache is not bundled with this probe", file=sys.stderr)
            return EXIT_MISSING_DB
        report = probe_legacy_cache(
            args.db,
            corpus_kind=args.corpus_kind,
            query_vector_file=args.query_vector_file,
            similarity=args.similarity,
            top_k=args.top_k,
        )
        for line in report["log_lines"]:
            print(line)
        print(
            json.dumps(
                {
                    "corpus_kind": report["metadata"]["corpus_kind"],
                    "rows": report["stats"]["row_count"],
                    "observed_dimension": report["stats"]["dimension"]["observed_dimension"],
                    "hits": len(report["retrieval_expected"]["hits"]),
                    "db": report["db_token"],
                    "sha256": report["db_sha256"],
                },
                sort_keys=True,
            )
        )
        if args.golden_out is not None:
            dump_golden(report, args.golden_out, source_db=args.db)
            print(f"wrote golden {path_token(args.golden_out)}")
        return EXIT_OK
    except InvalidCorpusKindError as exc:
        return _exit_error(str(exc), EXIT_INVALID_CORPUS_KIND)
    except DimensionMismatchError as exc:
        return _exit_error(str(exc), EXIT_DIMENSION_MISMATCH)
    except ProbeInputError as exc:
        return _exit_error(str(exc), EXIT_INVALID_INPUT)
    except FileNotFoundError as exc:
        return _exit_error(str(exc), EXIT_MISSING_FILE)
    except ProbeError as exc:
        return _exit_error(str(exc), int(getattr(exc, "exit_code", EXIT_UNEXPECTED)))
    except Exception:
        return _exit_error("unexpected error", EXIT_UNEXPECTED)


if __name__ == "__main__":
    raise SystemExit(main())
