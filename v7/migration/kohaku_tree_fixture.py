"""Phase 0 generator for KohakuRAG tree JSON fixtures.

Authority: docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md §3.14 / §6 Phase 0 item 5.

Runs KohakuRAG parsers + DocumentIndexer._build_tree at a pinned commit.
Does not call the embedder, does not load Jina/torch, does not invent hashes,
and does not claim a live Kohaku RAG service.

Corpus kind is generated_from_kohaku_source. That is E2 of the fixture
machinery against Kohaku source, not a production LanceDB index.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Mapping

GOLDEN_VERSION = 1
SCHEMA_VERSION = "flock-rag-kohaku-tree-fixture/1"
CORPUS_KIND = "generated_from_kohaku_source"
PINNED_KOHAKU_COMMIT = "f3d27c8d24616b75508795766355632640979e5b"
CLOSED_NODE_KINDS = ("document", "section", "paragraph", "sentence", "attachment")
KOHAKU_ROOT_ENV = "PG_AGENT_KOHAKURAG_ROOT"
DEFAULT_KOHAKU_ROOTS = (
    Path("/Users/wxl/Projects/rag/KohakuRAG"),
    Path("/Users/wxl/Projects/bookohakurag/KohakuRAG"),
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = REPO_ROOT / "v7" / "tests" / "fixtures" / "kohaku"
DOCUMENTS_DIR = FIXTURE_DIR / "documents"
GOLDEN_PATH = FIXTURE_DIR / "golden.v1.json"

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_MISSING_KOHAKU = 2
EXIT_COMMIT_MISMATCH = 3
EXIT_INVALID_INPUT = 4
EXIT_GOLDEN_MISMATCH = 5
EXIT_DIRTY_SOURCE = 6


class FixtureError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _default_kohaku_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get(KOHAKU_ROOT_ENV)
    if env:
        roots.append(Path(env).expanduser())
    roots.extend(DEFAULT_KOHAKU_ROOTS)
    return roots


def resolve_kohaku_root(explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit is not None else _default_kohaku_roots()
    for candidate in candidates:
        if candidate is None:
            continue
        src = candidate / "src" / "kohakurag"
        if (src / "parsers.py").is_file() and (src / "indexer.py").is_file():
            return candidate.resolve()
    raise FixtureError(
        f"KohakuRAG source not found (set {KOHAKU_ROOT_ENV})",
        EXIT_MISSING_KOHAKU,
    )


def kohaku_commit(root: Path) -> str:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FixtureError(f"cannot read KohakuRAG HEAD: {exc}", EXIT_MISSING_KOHAKU) from exc
    commit = raw.strip()
    if len(commit) != 40:
        raise FixtureError(f"KohakuRAG HEAD is not a 40-char commit: {commit!r}", EXIT_COMMIT_MISMATCH)
    return commit


def porcelain_blocks_generation(lines: list[str]) -> list[str]:
    """Any porcelain line under src/kohakurag blocks generation."""
    return [line for line in lines if line.strip()]


def kohaku_src_dirty_lines(root: Path) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--", "src/kohakurag"],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FixtureError(f"cannot read KohakuRAG src status: {exc}", EXIT_MISSING_KOHAKU) from exc
    return porcelain_blocks_generation(raw.splitlines())


def require_clean_kohaku_src(root: Path) -> None:
    dirty = kohaku_src_dirty_lines(root)
    if dirty:
        raise FixtureError(
            "KohakuRAG src/kohakurag is dirty; generation must use an unmodified pinned tree: "
            + "; ".join(dirty[:8]),
            EXIT_DIRTY_SOURCE,
        )


def _install_embeddings_stub() -> None:
    if "kohakurag.embeddings" in sys.modules:
        return
    stub = types.ModuleType("kohakurag.embeddings")

    class EmbeddingModel:  # noqa: D401 - protocol placeholder
        pass

    class JinaEmbeddingModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("kohaku tree fixture generator must not embed")

    def average_embeddings(*args: object, **kwargs: object) -> None:
        raise RuntimeError("kohaku tree fixture generator must not embed")

    stub.EmbeddingModel = EmbeddingModel
    stub.JinaEmbeddingModel = JinaEmbeddingModel
    stub.average_embeddings = average_embeddings
    sys.modules["kohakurag.embeddings"] = stub


def _load_kohaku_module(modname: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise FixtureError(f"cannot load {modname} from {path}", EXIT_MISSING_KOHAKU)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


def load_kohaku(root: Path) -> tuple[Any, Any]:
    """Load parsers + indexer without kohakurag/__init__.py (kohakuvault / torch)."""
    src = root / "src" / "kohakurag"
    pkg = sys.modules.get("kohakurag")
    if pkg is None:
        pkg = types.ModuleType("kohakurag")
        pkg.__path__ = [str(src)]
        pkg.__package__ = "kohakurag"
        sys.modules["kohakurag"] = pkg
    _load_kohaku_module("kohakurag.types", src / "types.py")
    _load_kohaku_module("kohakurag.text_utils", src / "text_utils.py")
    parsers = _load_kohaku_module("kohakurag.parsers", src / "parsers.py")
    _install_embeddings_stub()
    indexer = _load_kohaku_module("kohakurag.indexer", src / "indexer.py")
    return parsers, indexer


class _NoEmbed:
    dimension = 0

    async def embed(self, texts: object) -> object:
        raise RuntimeError("kohaku tree fixture generator must not embed")


def _kind_value(kind: object) -> str:
    value = getattr(kind, "value", kind)
    return str(value)


def serialize_tree(root: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        children = list(getattr(node, "children") or [])
        rows.append(
            {
                "node_id": node.node_id,
                "kind": _kind_value(node.kind),
                "parent_id": node.parent_id,
                "title": node.title,
                "text": node.text,
                "metadata": dict(node.metadata or {}),
                "child_ids": [child.node_id for child in children],
            }
        )
        for child in children:
            walk(child)

    walk(root)
    return rows


def serialize_payload(parsers: Any, payload: Any) -> dict[str, Any]:
    return parsers.payload_to_dict(payload)


def build_tree(indexer_mod: Any, payload: Any) -> Any:
    return indexer_mod.DocumentIndexer(embedding_model=_NoEmbed())._build_tree(payload)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def generate_documents(parsers: Any, indexer_mod: Any, documents_dir: Path) -> list[dict[str, Any]]:
    headings_path = documents_dir / "headings.md"
    plain_path = documents_dir / "plain.txt"
    nested_path = documents_dir / "nested.json"
    for path in (headings_path, plain_path, nested_path):
        if not path.is_file():
            raise FixtureError(f"missing source document {path.name}", EXIT_INVALID_INPUT)

    md_text = _read_text(headings_path)
    md_payload = parsers.markdown_to_payload(
        document_id="doc-md",
        title="Headings sample",
        markdown_text=md_text,
        metadata={"fixture": "markdown", "source_kind": "markdown"},
    )
    plain_text = _read_text(plain_path)
    plain_payload = parsers.text_to_payload(
        document_id="doc-text",
        title="Plain sample",
        text=plain_text,
        metadata={"fixture": "text", "source_kind": "text", "autogenerated_section": True},
    )
    nested_raw = json.loads(_read_text(nested_path))
    if not isinstance(nested_raw, dict):
        raise FixtureError("nested.json must be an object", EXIT_INVALID_INPUT)
    json_payload = parsers.dict_to_payload(nested_raw)
    roundtrip = parsers.dict_to_payload(parsers.payload_to_dict(json_payload))
    if parsers.payload_to_dict(roundtrip) != parsers.payload_to_dict(json_payload):
        raise FixtureError("dict_to_payload round-trip drifted", EXIT_UNEXPECTED)

    docs = [
        {
            "id": "doc-md",
            "source_kind": "markdown",
            "source_rel": "v7/tests/fixtures/kohaku/documents/headings.md",
            "payload": serialize_payload(parsers, md_payload),
            "tree": serialize_tree(build_tree(indexer_mod, md_payload)),
        },
        {
            "id": "doc-text",
            "source_kind": "text",
            "source_rel": "v7/tests/fixtures/kohaku/documents/plain.txt",
            "payload": serialize_payload(parsers, plain_payload),
            "tree": serialize_tree(build_tree(indexer_mod, plain_payload)),
        },
        {
            "id": "doc-json",
            "source_kind": "json",
            "source_rel": "v7/tests/fixtures/kohaku/documents/nested.json",
            "payload": serialize_payload(parsers, json_payload),
            "tree": serialize_tree(build_tree(indexer_mod, json_payload)),
        },
    ]
    return docs


def tree_invariants(documents: list[Mapping[str, Any]]) -> dict[str, Any]:
    kinds: set[str] = set()
    attachment = 0
    node_count = 0
    for doc in documents:
        tree = doc.get("tree")
        if not isinstance(tree, list) or not tree:
            raise FixtureError(f"{doc.get('id')} tree is empty", EXIT_UNEXPECTED)
        by_id = {row["node_id"]: row for row in tree if isinstance(row, Mapping)}
        roots = [row for row in tree if isinstance(row, Mapping) and row.get("parent_id") is None]
        if len(roots) != 1 or roots[0].get("kind") != "document":
            raise FixtureError(f"{doc.get('id')} must have one document root", EXIT_UNEXPECTED)
        for row in tree:
            if not isinstance(row, Mapping):
                raise FixtureError(f"{doc.get('id')} tree row is not an object", EXIT_UNEXPECTED)
            kind = row.get("kind")
            if kind not in CLOSED_NODE_KINDS:
                raise FixtureError(f"{doc.get('id')} unknown kind {kind!r}", EXIT_UNEXPECTED)
            kinds.add(str(kind))
            node_count += 1
            if kind == "attachment":
                attachment += 1
            parent_id = row.get("parent_id")
            if parent_id is not None and parent_id not in by_id:
                raise FixtureError(f"{row.get('node_id')} parent missing", EXIT_UNEXPECTED)
            for child_id in row.get("child_ids") or []:
                child = by_id.get(child_id)
                if not isinstance(child, Mapping) or child.get("parent_id") != row.get("node_id"):
                    raise FixtureError(f"{child_id} parent/child mismatch", EXIT_UNEXPECTED)
    return {
        "node_kinds_closed": list(CLOSED_NODE_KINDS),
        "kinds_present": sorted(kinds),
        "attachment_nodes_present": attachment > 0,
        "attachment_node_count": attachment,
        "node_count": node_count,
        "document_count": len(documents),
        "id_pattern": "{document_id}:sec{n}:p{n}:s{n} with global counters",
    }


def build_golden(
    *,
    kohaku_root: Path,
    commit: str,
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "golden_version": GOLDEN_VERSION,
        "corpus_kind": CORPUS_KIND,
        "not_live_kohaku_service": True,
        "kohaku_commit": commit,
        "kohaku_src_clean": True,
        "kohaku_root_env": KOHAKU_ROOT_ENV,
        "command": "uv run python v7/migration/kohaku_tree_fixture.py --write",
        "embedder_invoked": False,
        "documents": documents,
        "invariants": tree_invariants(documents),
        "notes": (
            "Generated by executing KohakuRAG parsers.py and indexer._build_tree "
            f"at {commit}. Embeddings were not computed. Not a live Kohaku service."
        ),
    }


def dump_golden(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_golden(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_golden(payload), encoding="utf-8")


def generate(
    *,
    kohaku_root: Path | None = None,
    allow_commit_mismatch: bool = False,
) -> dict[str, Any]:
    root = resolve_kohaku_root(kohaku_root)
    commit = kohaku_commit(root)
    if commit != PINNED_KOHAKU_COMMIT and not allow_commit_mismatch:
        raise FixtureError(
            f"KohakuRAG HEAD {commit} != pinned {PINNED_KOHAKU_COMMIT}",
            EXIT_COMMIT_MISMATCH,
        )
    require_clean_kohaku_src(root)
    parsers, indexer_mod = load_kohaku(root)
    documents = generate_documents(parsers, indexer_mod, DOCUMENTS_DIR)
    return build_golden(kohaku_root=root, commit=commit, documents=documents)


def compare_to_committed(generated: Mapping[str, Any], committed_path: Path = GOLDEN_PATH) -> None:
    if not committed_path.is_file():
        raise FixtureError(f"missing committed golden {committed_path}", EXIT_INVALID_INPUT)
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    if dump_golden(generated) != dump_golden(committed):
        raise FixtureError("generated golden does not match committed golden.v1.json", EXIT_GOLDEN_MISMATCH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or check Kohaku tree fixtures")
    parser.add_argument("--kohaku-root", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="write v7/tests/fixtures/kohaku/golden.v1.json")
    parser.add_argument("--check", action="store_true", help="require generated output to match the committed golden")
    parser.add_argument("--allow-commit-mismatch", action="store_true")
    args = parser.parse_args(argv)
    if args.write and args.check:
        parser.error("--write and --check are mutually exclusive; use --check to verify the committed golden")
    try:
        golden = generate(
            kohaku_root=args.kohaku_root,
            allow_commit_mismatch=args.allow_commit_mismatch,
        )
        if args.write:
            write_golden(GOLDEN_PATH, golden)
        elif args.check:
            compare_to_committed(golden)
        else:
            sys.stdout.write(dump_golden(golden))
        return EXIT_OK
    except FixtureError as exc:
        sys.stderr.write(f"{exc}\n")
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
