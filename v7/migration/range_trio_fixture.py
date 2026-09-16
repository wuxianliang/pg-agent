"""Phase 0 generator for Kohaku/MinerU/legacy range-trio fixtures.

Authority: docs/designs/phase0-mineru-unblock.md (Accepted) PR3 / WI3.

Imports DuckRAG P19-S PDF bytes + canonical content_list (no MinerU rerun).
Generates a tiny code source_line leg and a synthetic legacy_flat leg.

Does not import mineru, does not read the 15GB snapshot cache, does not
claim a live MinerU runtime, Kohaku service, or live byzerai_store_duckdb.db.
Does not flip phase0_baseline_status.json to E2.

--write and --check are mutually exclusive. There is no --live-parse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

GOLDEN_VERSION = 1
SCHEMA_VERSION = "flock-rag-range-trio-fixture/1"
CORPUS_KIND = "imported_and_generated_fixtures"
COMMAND = "uv run python v7/migration/range_trio_fixture.py --write"

PDF_REL = "v7/tests/fixtures/range_trio/pdf/p19-mineru-offline.pdf"
CONTENT_LIST_REL = "v7/tests/fixtures/range_trio/pdf/content_list.json"
CODE_REL = "v7/tests/fixtures/range_trio/code/sample.py"
LEGACY_REL = "v7/tests/fixtures/range_trio/legacy/flat.txt"
LEGACY_GOLDEN_REL = "v7/tests/fixtures/legacy_cache/golden.v1.json"
PROFILE_REL = "v7/evidence/locks/mineru/profile.json"
WHEEL_LOCK_REL = "v7/evidence/locks/mineru/mineru-3.4.4.lock.json"
UV_LOCK_REL = "v7/evidence/locks/mineru/uv.lock"
REQUIREMENTS_REL = "v7/evidence/locks/mineru/requirements-arm64.txt"
P19_LOCK_REL = "v7/evidence/locks/mineru/p19-cpython312-arm64.lock.json"
P19S_REL = "v7/evidence/duckrag/p19-s.json"

PDF_SHA256 = "163c9ac8f7f857904793b01fa9f031cebbe83f186b9cfc3510b9a371e464922c"
PDF_SIZE_BYTES = 672
CODE_SHA256 = "db6f869ad70f5fe8910a7c7bf9d625edea9a4508333ecdd64fb1425a628d938e"
CODE_SIZE_BYTES = 252
LEGACY_SHA256 = "d6ad7d0569e8fecc07d58f3203d86952b9f5bf7017ffa30910be3cbc89405d04"
LEGACY_SIZE_BYTES = 125
P19S_SHA256 = "ae77a11045b4ce9a26705b0665ee54d11f67f26e37b72755253f46c92b0dff55"
P19S_SIZE_BYTES = 19125
PROFILE_FILE_SHA256 = "8d33e78801fc5bf2d461877442cd986d6fe50e338abe74bebf115205a33a2f8d"
PROFILE_FILE_SIZE_BYTES = 2424
WHEEL_LOCK_FILE_SHA256 = "beb6754da1da4718ad7a5bd6a36fdaa5720f7d56f966969972abd7d27be8ce30"
WHEEL_LOCK_FILE_SIZE_BYTES = 1057
UV_LOCK_SHA256 = "5b2b5e38c1fbe2c594df879bd19209426211b4c15d3a5e223865415145f0393b"
UV_LOCK_SIZE_BYTES = 30647
REQUIREMENTS_SHA256 = "9de6d1af4d6e61197d01032ce2e78039c57f74d7c2d95e98dd9ac7c1964651f7"
REQUIREMENTS_SIZE_BYTES = 16855
P19_LOCK_SHA256 = "2bc744715ae0407de1f30e62f6a4f64ec4eff8eff706ef58250267dcda3d91b5"
P19_LOCK_SIZE_BYTES = 26394

MINERU_WHEEL_SHA256 = "d4d678539782a7683d998e2914a52d96b5720676ce65658b29666b1f4d9dfd13"
MODEL_MANIFEST_SHA256 = "8c4a6a53815e2a8f410d71350128d0db1276579ac9f50cd1dee56b165e4a4df6"
PROFILE_ID = "mineru-3.4.4-pipeline-cpython312-darwin-arm64"
HARNESS_REVISION = "duckrag-wi1-harness/2"
P19S_RUN_ID = "p19-s-20260807T041212.416512Z"
DUCKRAG_HEAD_AT_COPY = "0c6ad30b000ac8ef532947b7b997933b6f28feb0"
P19S_REPOSITORY_REVISION = "a6f9e079ded72250c8a7ef4a9372613382707795"
SOURCE_MAIN_REVISION = "cd2d4c4951bbd993ea81d9be862d943aa213711e"
PAGE_SIZE = [612, 792]
WHEEL_CLOSURE_COUNT = 84

# Two objects from p19_mineru_process.py expected content_list. Not a string array.
CANONICAL_CONTENT_LIST: list[dict[str, Any]] = [
    {
        "type": "text",
        "text": "DuckRAG P19-S Fixture",
        "text_level": 1,
        "bbox": [112, 70, 439, 94],
        "page_idx": 0,
    },
    {
        "type": "text",
        "text": "Offline MinerU process-control verification.",
        "bbox": [112, 113, 488, 132],
        "page_idx": 0,
    },
]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = REPO_ROOT / "v7" / "tests" / "fixtures" / "range_trio"
PDF_PATH = REPO_ROOT / PDF_REL
CONTENT_LIST_PATH = REPO_ROOT / CONTENT_LIST_REL
CODE_PATH = REPO_ROOT / CODE_REL
LEGACY_PATH = REPO_ROOT / LEGACY_REL
GOLDEN_PATH = FIXTURE_DIR / "golden.v1.json"

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_INVALID_INPUT = 4
EXIT_GOLDEN_MISMATCH = 5

COPIED_IDENTITY = (
    (PROFILE_REL, PROFILE_FILE_SHA256, PROFILE_FILE_SIZE_BYTES),
    (WHEEL_LOCK_REL, WHEEL_LOCK_FILE_SHA256, WHEEL_LOCK_FILE_SIZE_BYTES),
    (UV_LOCK_REL, UV_LOCK_SHA256, UV_LOCK_SIZE_BYTES),
    (REQUIREMENTS_REL, REQUIREMENTS_SHA256, REQUIREMENTS_SIZE_BYTES),
    (P19_LOCK_REL, P19_LOCK_SHA256, P19_LOCK_SIZE_BYTES),
    (P19S_REL, P19S_SHA256, P19S_SIZE_BYTES),
)


class FixtureError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_file(path: Path) -> bytes:
    try:
        if not path.is_file():
            raise FixtureError(f"missing {path}", EXIT_INVALID_INPUT)
        return path.read_bytes()
    except OSError as exc:
        raise FixtureError(f"cannot read {path}: {exc}", EXIT_UNEXPECTED) from exc


def require_utf8(path: Path) -> str:
    data = require_file(path)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FixtureError(f"invalid UTF-8 {path}: {exc}", EXIT_INVALID_INPUT) from exc


def require_copied_file(rel: str, expected_sha: str, expected_size: int) -> bytes:
    path = REPO_ROOT / rel
    data = require_file(path)
    got_sha = sha256_bytes(data)
    if len(data) != expected_size or got_sha != expected_sha:
        raise FixtureError(
            f"{rel} size/sha mismatch: size={len(data)} sha256={got_sha}",
            EXIT_GOLDEN_MISMATCH,
        )
    return data


def load_json(path: Path) -> Any:
    try:
        return json.loads(require_utf8(path))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"invalid JSON {path}: {exc}", EXIT_INVALID_INPUT) from exc


def dump_golden(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def bbox_in_page(bbox: Any, page_size: list[int] = PAGE_SIZE) -> bool:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in bbox):
        return False
    x0, y0, x1, y1 = bbox
    return 0 <= x0 <= x1 <= page_size[0] and 0 <= y0 <= y1 <= page_size[1]


def split_source_lines(text: str, rel: str) -> list[str]:
    if not text.endswith("\n"):
        raise FixtureError(f"{rel} must end with a newline", EXIT_INVALID_INPUT)
    if "\r" in text:
        raise FixtureError(f"{rel} must use \\n newlines only", EXIT_INVALID_INPUT)
    lines = text.split("\n")[:-1]
    if not lines:
        raise FixtureError(f"{rel} has no lines", EXIT_INVALID_INPUT)
    return lines


def canonical_content_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise FixtureError("content_list must be two objects", EXIT_INVALID_INPUT)
    if any(isinstance(item, str) or not isinstance(item, dict) for item in raw):
        raise FixtureError("content_list must be objects, not a string array", EXIT_INVALID_INPUT)
    if raw != CANONICAL_CONTENT_LIST:
        raise FixtureError("content_list does not match p19_mineru_process.py expected", EXIT_GOLDEN_MISMATCH)
    for item in raw:
        bbox = item.get("bbox")
        if not bbox_in_page(bbox):
            raise FixtureError(f"bbox not in-page on 612x792: {bbox!r}", EXIT_GOLDEN_MISMATCH)
        if item.get("page_idx") != 0:
            raise FixtureError(f"page_idx must be 0, got {item.get('page_idx')!r}", EXIT_GOLDEN_MISMATCH)
    return list(raw)


def read_pdf_leg() -> dict[str, Any]:
    data = require_file(PDF_PATH)
    got_sha = sha256_bytes(data)
    if len(data) != PDF_SIZE_BYTES or got_sha != PDF_SHA256:
        raise FixtureError(
            f"PDF size/sha mismatch: size={len(data)} sha256={got_sha}",
            EXIT_GOLDEN_MISMATCH,
        )
    content_list = canonical_content_list(load_json(CONTENT_LIST_PATH))
    return {
        "range_origin": "page_bbox",
        "source_rel": PDF_REL,
        "pdf_sha256": PDF_SHA256,
        "pdf_size_bytes": PDF_SIZE_BYTES,
        "page_size": list(PAGE_SIZE),
        "page_idx": 0,
        "catalog_page": 1,
        "line_start": None,
        "line_end": None,
        "content_list": content_list,
        "provenance": imported_pdf_provenance(),
    }


def _require_pinned_text(path: Path, rel: str, expected_sha: str, expected_size: int) -> str:
    data = require_file(path)
    got_sha = sha256_bytes(data)
    if len(data) != expected_size or got_sha != expected_sha:
        raise FixtureError(
            f"{rel} size/sha mismatch: size={len(data)} sha256={got_sha}",
            EXIT_GOLDEN_MISMATCH,
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FixtureError(f"invalid UTF-8 {rel}: {exc}", EXIT_INVALID_INPUT) from exc


def read_code_leg() -> dict[str, Any]:
    text = _require_pinned_text(CODE_PATH, CODE_REL, CODE_SHA256, CODE_SIZE_BYTES)
    lines = split_source_lines(text, CODE_REL)
    return {
        "range_origin": "source_line",
        "source_rel": CODE_REL,
        "corpus_kind": "generated_source_line_fixture",
        "source_sha256": CODE_SHA256,
        "source_size_bytes": CODE_SIZE_BYTES,
        "line_start": 1,
        "line_end": len(lines),
        "newline": "\n",
    }


def read_legacy_leg() -> dict[str, Any]:
    text = _require_pinned_text(LEGACY_PATH, LEGACY_REL, LEGACY_SHA256, LEGACY_SIZE_BYTES)
    lines = split_source_lines(text, LEGACY_REL)
    return {
        "range_origin": "legacy_flat",
        "source_rel": LEGACY_REL,
        "corpus_kind": "synthetic_from_source_schema",
        "source_sha256": LEGACY_SHA256,
        "source_size_bytes": LEGACY_SIZE_BYTES,
        "related_legacy_golden": LEGACY_GOLDEN_REL,
        "line_start": 1,
        "line_end": len(lines),
        "notes": (
            "Not live byzerai_store_duckdb.db. Projection text is synthetic. "
            "related_legacy_golden _id doc_alpha_0 is compatibility intent only."
        ),
    }


def build_golden() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "golden_version": GOLDEN_VERSION,
        "corpus_kind": CORPUS_KIND,
        "not_live_mineru_runtime": True,
        "not_live_kohaku_service": True,
        "not_live_legacy_cache": True,
        "command": COMMAND,
        "legs": {
            "pdf": read_pdf_leg(),
            "code": read_code_leg(),
            "legacy": read_legacy_leg(),
        },
        "notes": (
            "PDF imported from DuckRAG P19-S; code/legacy generated. "
            "Not live MinerU, Kohaku, or legacy cache. Origin-shape only; "
            "not plan §3.14 diversity. This freeze does not mark baseline E2."
        ),
    }


def generate() -> dict[str, Any]:
    verify_copied_identity()
    return build_golden()


def write_golden(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_golden(payload), encoding="utf-8")
    except OSError as exc:
        raise FixtureError(f"cannot write {path}: {exc}", EXIT_UNEXPECTED) from exc


def compare_to_committed(generated: Mapping[str, Any], committed_path: Path = GOLDEN_PATH) -> None:
    committed = load_json(committed_path)
    if not isinstance(committed, Mapping):
        raise FixtureError(f"committed golden is not an object: {committed_path}", EXIT_INVALID_INPUT)
    if dump_golden(generated) != dump_golden(committed):
        raise FixtureError(
            "generated golden does not match committed golden.v1.json",
            EXIT_GOLDEN_MISMATCH,
        )


def _p19s_model_manifest(payload: Mapping[str, Any]) -> str | None:
    for descriptor in payload.get("descriptors") or []:
        if not isinstance(descriptor, Mapping):
            continue
        closure = descriptor.get("model_closure")
        if isinstance(closure, Mapping) and closure.get("manifest_sha256"):
            return str(closure["manifest_sha256"])
    return None


def _p19s_content_list(payload: Mapping[str, Any]) -> Any:
    for descriptor in payload.get("descriptors") or []:
        if not isinstance(descriptor, Mapping):
            continue
        summary = descriptor.get("canonical_pdf_summary")
        if isinstance(summary, Mapping) and "content" in summary:
            return summary.get("content")
    return None


def _p19s_source_main_revision(payload: Mapping[str, Any]) -> str | None:
    for descriptor in payload.get("descriptors") or []:
        if not isinstance(descriptor, Mapping):
            continue
        snapshot = descriptor.get("execution_snapshot")
        if isinstance(snapshot, Mapping) and snapshot.get("source_main_revision"):
            return str(snapshot["source_main_revision"])
    return None


def imported_pdf_provenance() -> dict[str, Any]:
    p19s = load_json(REPO_ROOT / P19S_REL)
    if not isinstance(p19s, Mapping):
        raise FixtureError("p19-s.json is not an object", EXIT_INVALID_INPUT)
    profile = load_json(REPO_ROOT / PROFILE_REL)
    if not isinstance(profile, Mapping):
        raise FixtureError("profile.json is not an object", EXIT_INVALID_INPUT)
    env = p19s.get("environment_profile")
    evidence_profile_id = env.get("profile_id") if isinstance(env, Mapping) else None
    run_id = p19s.get("run_id")
    repo_rev = p19s.get("repository_revision")
    harness = p19s.get("harness_revision")
    source_main = _p19s_source_main_revision(p19s)
    copied_profile_id = profile.get("profile_id")
    if run_id != P19S_RUN_ID:
        raise FixtureError(f"p19-s.json run_id {run_id!r} != {P19S_RUN_ID}", EXIT_GOLDEN_MISMATCH)
    if repo_rev != P19S_REPOSITORY_REVISION:
        raise FixtureError(f"p19-s.json repository_revision {repo_rev!r}", EXIT_GOLDEN_MISMATCH)
    if harness != HARNESS_REVISION:
        raise FixtureError(f"p19-s.json harness_revision {harness!r}", EXIT_GOLDEN_MISMATCH)
    if source_main != SOURCE_MAIN_REVISION:
        raise FixtureError(f"p19-s.json source_main_revision {source_main!r}", EXIT_GOLDEN_MISMATCH)
    if evidence_profile_id != PROFILE_ID or copied_profile_id != PROFILE_ID:
        raise FixtureError(
            f"profile_id mismatch evidence={evidence_profile_id!r} copied={copied_profile_id!r}",
            EXIT_GOLDEN_MISMATCH,
        )
    return {
        "kind": "imported_from_duckrag_p19s",
        "duckrag_head_at_copy": DUCKRAG_HEAD_AT_COPY,
        "p19s_run_id": str(run_id),
        "p19s_evidence_sha256": P19S_SHA256,
        "p19s_repository_revision_synthetic": str(repo_rev),
        "source_main_revision": str(source_main),
        "harness_revision": str(harness),
        "profile_id": str(copied_profile_id),
        "mineru_invoked_this_freeze": False,
    }


def verify_copied_identity() -> None:
    for rel, expected_sha, expected_size in COPIED_IDENTITY:
        require_copied_file(rel, expected_sha, expected_size)

    profile = load_json(REPO_ROOT / PROFILE_REL)
    if not isinstance(profile, Mapping):
        raise FixtureError("profile.json is not an object", EXIT_INVALID_INPUT)
    pipeline = profile.get("pipeline_model")
    if not isinstance(pipeline, Mapping):
        raise FixtureError("profile.json pipeline_model missing", EXIT_INVALID_INPUT)
    snapshot = pipeline.get("manifest_sha256")
    if snapshot != MODEL_MANIFEST_SHA256:
        raise FixtureError(
            f"snapshot pin lives at profile.json pipeline_model.manifest_sha256; got {snapshot!r}",
            EXIT_GOLDEN_MISMATCH,
        )
    if profile.get("artifact_count") != WHEEL_CLOSURE_COUNT:
        raise FixtureError(
            f"profile artifact_count {profile.get('artifact_count')!r} != {WHEEL_CLOSURE_COUNT}",
            EXIT_GOLDEN_MISMATCH,
        )
    if profile.get("profile_id") != PROFILE_ID:
        raise FixtureError(f"profile_id {profile.get('profile_id')!r}", EXIT_GOLDEN_MISMATCH)

    lock = load_json(REPO_ROOT / WHEEL_LOCK_REL)
    if not isinstance(lock, Mapping):
        raise FixtureError("wheel lock is not an object", EXIT_INVALID_INPUT)
    artifacts = lock.get("pypi_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise FixtureError("wheel lock pypi_artifacts missing", EXIT_INVALID_INPUT)
    wheel_sha = artifacts[0].get("sha256") if isinstance(artifacts[0], Mapping) else None
    if wheel_sha != MINERU_WHEEL_SHA256:
        raise FixtureError(
            f"wheel lock sha field {wheel_sha!r} != {MINERU_WHEEL_SHA256}",
            EXIT_GOLDEN_MISMATCH,
        )
    lock_text = (REPO_ROOT / WHEEL_LOCK_REL).read_text(encoding="utf-8")
    if "snapshot_manifest" in lock_text or MODEL_MANIFEST_SHA256 in lock_text:
        raise FixtureError("wheel lock must not carry the snapshot pin", EXIT_GOLDEN_MISMATCH)

    requirements = require_file(REPO_ROOT / REQUIREMENTS_REL).decode("utf-8")
    hash_lines = [line for line in requirements.splitlines() if "--hash=sha256:" in line]
    if len(hash_lines) != WHEEL_CLOSURE_COUNT:
        raise FixtureError(
            f"requirements-arm64.txt hash lines {len(hash_lines)} != {WHEEL_CLOSURE_COUNT}",
            EXIT_GOLDEN_MISMATCH,
        )

    p19s = load_json(REPO_ROOT / P19S_REL)
    if not isinstance(p19s, Mapping):
        raise FixtureError("p19-s.json is not an object", EXIT_INVALID_INPUT)
    if p19s.get("run_id") != P19S_RUN_ID:
        raise FixtureError(f"p19-s.json run_id {p19s.get('run_id')!r}", EXIT_GOLDEN_MISMATCH)
    if p19s.get("repository_revision") != P19S_REPOSITORY_REVISION:
        raise FixtureError(
            f"p19-s.json repository_revision {p19s.get('repository_revision')!r}",
            EXIT_GOLDEN_MISMATCH,
        )
    if p19s.get("harness_revision") != HARNESS_REVISION:
        raise FixtureError(
            f"p19-s.json harness_revision {p19s.get('harness_revision')!r}",
            EXIT_GOLDEN_MISMATCH,
        )
    if _p19s_source_main_revision(p19s) != SOURCE_MAIN_REVISION:
        raise FixtureError("p19-s.json source_main_revision mismatch", EXIT_GOLDEN_MISMATCH)
    if _p19s_model_manifest(p19s) != MODEL_MANIFEST_SHA256:
        raise FixtureError("p19-s.json model_closure.manifest_sha256 mismatch", EXIT_GOLDEN_MISMATCH)
    if _p19s_content_list(p19s) != CANONICAL_CONTENT_LIST:
        raise FixtureError("p19-s.json canonical content_list mismatch", EXIT_GOLDEN_MISMATCH)
    fixtures = p19s.get("fixtures")
    fixture_sha = None
    if isinstance(fixtures, list) and fixtures and isinstance(fixtures[0], Mapping):
        fixture_sha = fixtures[0].get("sha256")
    if fixture_sha != PDF_SHA256:
        raise FixtureError(f"p19-s.json fixture sha {fixture_sha!r}", EXIT_GOLDEN_MISMATCH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or check MinerU range-trio fixtures")
    parser.add_argument("--write", action="store_true", help="write v7/tests/fixtures/range_trio/golden.v1.json")
    parser.add_argument("--check", action="store_true", help="require generated output to match the committed golden")
    args = parser.parse_args(argv)
    if args.write and args.check:
        parser.error("--write and --check are mutually exclusive; use --check to verify the committed golden")
    try:
        golden = generate()
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
