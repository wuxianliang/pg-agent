"""Phase 0 gate for v7/VERSION_MANIFEST.json against plan §3.2.

Standalone check()/AssertionError style, matching v7/tests/test_legacy_cache_probe.py.
Run: uv run python v7/tests/test_version_manifest.py

Does not xfail. Does not invent hashes. Lock-copied values must match
v7/evidence/contracts; live-file-absent backends stay blocked; mdenseon /
tachiom / MinerU runtime must not be claimed as E2.

phase0_pass is derived by v7.gates.phase0_evaluator. release_gate.would_pass
is derived by v7.gates.release_evaluator and requires Phase 1–7 and E3.
They are not equal by construction.
NEAREST live E2 requires in-repo log + resolvable target binary (env/config);
absence is blocked, not a skip. External Cargo.lock/unittest paths come from
PG_AGENT_DUCKDB_TACHIOM_CARGO_LOCK / DUCKDB_TACHIOM_CARGO_LOCK and
PG_AGENT_UNITTEST_BIN / DUCKDB_PGAGENT_UNITTEST, not a developer home layout.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from v7.gates.phase0_evaluator import (
    BASELINE_BOOL_FIELDS,
    BASELINE_RELATION_BY_ID,
    BLOCKER_CLASS_BLOCKERS,
    BLOCKER_CLASS_CONFIGURATION,
    BLOCKER_CLASS_DIRTY_UNINITIALIZED,
    BLOCKER_CLASS_LIVE_EVIDENCE,
    BLOCKER_CLASS_MANIFEST,
    BLOCKER_CLASS_MISSING_BASELINES,
    BLOCKER_CLASS_OPEN_CORRECTIONS,
    BLOCKER_CLASS_REQUIRED_NULL_HASHES,
    BM25_COMPOSITE_KEY,
    BM25_CONFIG_HASH_KEY,
    BM25_SIBLING_KEYS,
    COMMIT_40_KEYS,
    COMMIT_RE,
    DIGEST_FIELDS,
    DUCKDB_PGAGENT_COMMIT,
    EVIDENCE_REGISTER_SCHEMA,
    EVALUATOR_ID,
    FLOCK_EXTENSION_CI_TOOLS_COMMIT,
    FOUR_REPO_COMMIT_KEYS,
    HASH_KEY_RE,
    IDENTICAL_CONCERN_CONTRACT_IDS,
    LIVE_MISSING_TO_GATE,
    MANIFEST_KIND,
    MINERU_PARSER_EXPECTED,
    NOT_APPLICABLE_HASH_PATHS,
    NOT_APPLICABLE_STATUS,
    NEAREST_BUILD_TAG,
    NEAREST_COMMAND,
    NEAREST_HISTORICAL_SCHEMA,
    NEAREST_LOG_REL,
    NEAREST_SHA256,
    NEAREST_SIZE_BYTES,
    NEAREST_STDERR_DELIM,
    NEAREST_STDOUT_DELIM,
    NEAREST_TARGET_E2_UNVERIFIED,
    NEAREST_WORKING_TREE_CLEAN,
    PHASE0_BLOCKER_CLASS_ORDER,
    PHASE0_PASS_EXEMPT_BACKEND_GATES,
    RECORDED_COMPLETENESS,
    REQUIRED_BACKEND_GATES,
    REQUIRED_BASELINE_IDS,
    REQUIRED_CONTRACT_IDS,
    REQUIRED_CONTRACT_SPECS,
    REQUIRED_HASH_FIELDS,
    NEAREST_BINARY_SOURCE_ID,
    PHASE0_ATTESTATION_SCHEMA,
    PHASE0_SOURCE_RELATIVE_PATHS,
    SCHEMA_VERSION,
    SECTION_32_REQUIRED_FIELDS,
    SHA256_RE,
    TACHIOM_TAG,
    TACHIOM_TAG_COMMIT,
    TAG_COMMIT_PAIRS,
    UNITTEST_BIN_ENV_VARS,
    NEAREST_LIVE_BINARY_RELPATH_FILE,
    attest_phase0_from_repo,
    evaluate_phase0,
    _resolve_configured_live_binary,
    evaluate_phase0_from_repo,
    phase0_record_consistency_errors,
    phase0_source_fingerprint,
    required_null_hash_paths,
)
from v7.gates import phase0_evaluator as phase0_mod
from v7.gates import release_evaluator as release_mod
from v7.gates.release_evaluator import (
    BLOCKER_CLASS_E3,
    BLOCKER_CLASS_PHASE0_ATTESTATION,
    BLOCKER_CLASS_PHASE_GATES,
    PHASE0_NOT_VERIFIED,
    PHASE0_SOURCE_CHANGED,
    PHASE_IDS,
    RELEASE_BLOCKER_CLASS_ORDER,
    default_e3_state,
    default_phase_gates,
    evaluate_release_from_repo,
    evaluate_release_gate,
    PHASE0_FINGERPRINT_MISMATCH,
    PHASE0_NOT_CANONICAL,
    PHASE0_SOURCE_UNBOUND,
    release_record_consistency_errors,
    release_result_validation_codes,
)

V7_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = V7_ROOT.parent
MANIFEST_PATH = V7_ROOT / "VERSION_MANIFEST.json"
PROVENANCE_PATH = V7_ROOT / "evidence" / "four_repo_provenance.json"
REGISTER_PATH = V7_ROOT / "evidence" / "contracts" / "EVIDENCE_REGISTER.json"
MINERU_CONTRACT_PATH = V7_ROOT / "evidence" / "contracts" / "mineru.md"
PLAN_PATH = REPO_ROOT / "docs" / "plans" / "flock-rag-on-duckdb-final-plan-v4.1.md"
TRACE_PATH = REPO_ROOT / "docs" / "plans" / "flock-rag-v4.1-review-correction-traceability.md"
CORRECTIONS_PATH = V7_ROOT / "evidence" / "corrections_register.json"
BASELINE_PATH = V7_ROOT / "evidence" / "phase0_baseline_status.json"
INFINI_JSON_PATH = V7_ROOT / "evidence" / "contracts" / "infinisynapse_schema.json"
NEAREST_JSON_PATH = V7_ROOT / "evidence" / "nearest_e2.json"
NEAREST_SUMMARY_PATH = V7_ROOT / "evidence" / "nearest_e2_summary.md"
NEAREST_LOG_PATH = V7_ROOT / "evidence" / "nearest_basic.e2.log"
README_PATH = V7_ROOT / "README.md"
HUNT_PATH = V7_ROOT / "evidence" / "local_evidence_search.md"
CARGO_LOCK_ENV_VARS = ("PG_AGENT_DUCKDB_TACHIOM_CARGO_LOCK", "DUCKDB_TACHIOM_CARGO_LOCK")
TACHIOM_CARGO_SOURCE_RE = re.compile(
    r"source = \"git\+https://github.com/TusKANNy/tachiom\.git\?tag=v0\.3\.4#([0-9a-f]{40})\""
)
META_KEY_RE = re.compile(
    r"(_status|_notes|_evidence_level|_kind|_path|_role|_optional)$",
    re.I,
)
META_KEYS = {
    "status",
    "notes",
    "evidence_level",
    "kind",
    "blocked",
    "not_e2",
    "reason",
    "related_backend",
}
MINERU_WHEEL_SHA256_FROM_CONTRACT = "d4d678539782a7683d998e2914a52d96b5720676ce65658b29666b1f4d9dfd13"
UNIQUE_UNRESOLVED_IDS = ["C3", "DR-PO-1", "DR-PO-2", "DR-PO-3"]
UNIQUE_PARTIAL_IDS = ["F-9", "F-12", "C5", "C6", "C7", "DR-SEC-4", "DR-T-2"]
PHASE0_INJECTABLE_CLASSES = [
    BLOCKER_CLASS_BLOCKERS,
    BLOCKER_CLASS_MISSING_BASELINES,
    BLOCKER_CLASS_OPEN_CORRECTIONS,
    BLOCKER_CLASS_REQUIRED_NULL_HASHES,
    BLOCKER_CLASS_CONFIGURATION,
    BLOCKER_CLASS_DIRTY_UNINITIALIZED,
    BLOCKER_CLASS_LIVE_EVIDENCE,
    BLOCKER_CLASS_MANIFEST,
]
MANDATORY_NESTED_FIELDS = [
    ("mineru_model_name_version_weights_hash", "single_file_weights_sha256"),
    ("tokenizer_identity_version_hash", "lfs_sha256"),
    ("embedding_dimension_dtype_normalization_batch", "dimension"),
    ("embedding_dimension_dtype_normalization_batch", "dtype"),
    ("embedding_dimension_dtype_normalization_batch", "normalization"),
    ("embedding_dimension_dtype_normalization_batch", "zero_norm_policy"),
    ("embedding_dimension_dtype_normalization_batch", "batch_contract"),
    ("mdenseon_package_native_runtime_version", "model_id"),
]

NEAREST_EXECUTION_FIELDS = [
    "evidence_level",
    "command",
    "cwd",
    "exit_code",
    "assertions",
    "log",
    "log_start_utc",
    "binary_path",
    "binary_sha256",
    "binary_size_bytes",
    "binary_file_type",
    "binary_mtime_local",
    "build_identity_commit",
    "build_identity_tag",
]

DIRTY_MANIFEST_KEYS = [
    ("pg-agent", "pg_agent_dirty"),
    ("flock", "flock_dirty"),
    ("duckdb-pgagent", "duckdb_pgagent_dirty"),
    ("duckdb-python-pgagent", "duckdb_python_pgagent_dirty"),
    ("duckdb-tachiom", "duckdb_tachiom_dirty"),
]

TACHIOM_CARGO_PIN_RE = re.compile(
    r"git\+https://github.com/TusKANNy/tachiom\.git\?tag=v0\.3\.4#([0-9a-f]{40})"
)


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"[{('PASS' if condition else 'FAIL')}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def _load_json(path: Path) -> dict:
    check(f"{path.name} exists", path.is_file(), str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    check(f"{path.name} is an object", isinstance(payload, dict), type(payload).__name__)
    return payload


def _is_meta_key(key: str) -> bool:
    return key in META_KEYS or bool(META_KEY_RE.search(key))


def _allowlisted_na_null_leaf(container: dict, key: str, path: str) -> bool:
    if path not in NOT_APPLICABLE_HASH_PATHS or container.get(key) is not None:
        return False
    status, _notes = _sibling_status_notes(container, key)
    return status == NOT_APPLICABLE_STATUS


def _required_null_keys(container: dict, path: str = "") -> list[str]:
    found: list[str] = []
    for key, value in container.items():
        if _is_meta_key(key) or value is not None:
            continue
        child = f"{path}.{key}" if path else key
        if _allowlisted_na_null_leaf(container, key, child):
            continue
        found.append(key)
    return found


def _contract_by_id(register: dict, contract_id: str) -> dict:
    contracts = register.get("contracts")
    check("EVIDENCE_REGISTER.contracts is a list", isinstance(contracts, list), type(contracts).__name__)
    matches = [row for row in contracts if row.get("id") == contract_id]
    check(f"register contains id {contract_id}", len(matches) == 1, [row.get("id") for row in contracts])
    return matches[0]


def _sibling_status_notes(container: dict, key: str) -> tuple[object, object]:
    status = container.get(f"{key}_status")
    notes = container.get(f"{key}_notes")
    value = container.get(key)
    if isinstance(value, dict):
        if status is None:
            status = value.get("status")
        if notes is None:
            notes = value.get("notes")
    return status, notes


def _iter_hash_nulls(obj: object, path: str = "") -> list[tuple[str, dict, str]]:
    found: list[tuple[str, dict, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else key
            if value is None and HASH_KEY_RE.search(key):
                found.append((child, obj, key))
            else:
                found.extend(_iter_hash_nulls(value, child))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            found.extend(_iter_hash_nulls(item, f"{path}[{index}]"))
    return found


def _resolve_optional_file(
    env_vars: tuple[str, ...],
    recorded: list[object],
    *,
    allow_absolute: bool = True,
    repo_root: Path | None = None,
) -> tuple[Path | None, str]:
    root = (Path(repo_root) if repo_root is not None else REPO_ROOT).resolve()
    for var in env_vars:
        raw = os.environ.get(var)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            try:
                anchored = (root / path).resolve()
                anchored.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                return None, f"env:{var}:missing"
            path = anchored
        if path.is_file():
            return path, f"env:{var}"
        return path, f"env:{var}:missing"
    for candidate in recorded:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.is_absolute():
            if not allow_absolute:
                continue
        else:
            try:
                resolved = (root / path).resolve()
                resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                continue
            path = resolved
        if path.is_file():
            return path, "recorded"
    return None, "absent"


@contextmanager
def _working_directory(path: Path | None):
    if path is None:
        yield
        return
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _passable_contract(spec: dict, manifest: dict) -> dict:
    blocked = False if spec["id"] in IDENTICAL_CONCERN_CONTRACT_IDS else spec["backend_blocked"]
    related = spec["related_backend"]
    row = {
        "id": spec["id"],
        "path": spec["path"],
        "related_backend": related,
        "notes": "synthetic contract row",
        "level": spec["level"],
        "backend_blocked": blocked,
        "backend_blocked_reason": "synthetic blocked" if blocked else None,
        "paths_read": ["synthetic/path"],
        "blockers": [],
    }
    if blocked:
        row["blockers"] = [
            {
                "id": f"{spec['id']}_blocker",
                "level": "E0",
                "blocks_backend": related,
                "detail": "synthetic blocker",
            }
        ]
    if spec["id"] == "infinisynapse_schema":
        row.update(
            {
                "workflow_semantics_frozen": True,
                "workflow_semantics_level": "E1",
                "exact_tool_dto_frozen": False,
                "exact_tool_dto_level": "E0",
                "machine_checkable": "v7/evidence/contracts/infinisynapse_schema.json",
            }
        )
    if spec["id"] == "infinisynapse_exact_dto":
        row.update(
            {
                "exact_tool_dto_frozen": False,
                "exact_tool_dto_level": "E0",
                "machine_checkable": "v7/evidence/contracts/infinisynapse_schema.json",
            }
        )
    if spec["id"] == "mdenseon":
        runtime = manifest["mdenseon_package_native_runtime_version"]
        embedding = manifest["embedding_dimension_dtype_normalization_batch"]
        tokenizer = manifest["tokenizer_identity_version_hash"]
        row["frozen_without_live_files"] = {
            "model_id": runtime["model_id"],
            "revision": runtime["revision"],
            "expected_dimension": embedding["dimension"],
            "dtype": embedding["dtype"],
            "normalization": embedding["normalization"],
            "zero_norm_policy": embedding["zero_norm_policy"],
            "weights_lfs_sha256_from_lock": manifest["mdenseon_model_weights_sha256"],
            "tokenizer_json_lfs_sha256_from_lock": tokenizer["lfs_sha256"],
        }
    if spec["id"] == "tachiom":
        row["git"] = {
            "tachiom": {
                "build_identity_commit": manifest["tachiom_commit"],
                "build_identity_tag": manifest["tachiom_tag"],
                "checkout_commit": manifest["tachiom_checkout_commit"],
            },
            "duckdb-tachiom": {"commit": manifest["duckdb_tachiom_commit"]},
            "duckdb-pgagent_target": {
                "commit": manifest["duckdb_pgagent_commit"],
                "tag": manifest["duckdb_pgagent_tag"],
            },
        }
    if spec["id"] == "nearest_basic":
        row.update(
            {
                "live_e2_requires_binary_and_log": True,
                "unverified_gate_level": "blocked",
                "unverified_blocker_id": NEAREST_TARGET_E2_UNVERIFIED,
                "binary": {
                    "sha256": NEAREST_SHA256,
                    "size_bytes": NEAREST_SIZE_BYTES,
                    "build_identity": {"commit": DUCKDB_PGAGENT_COMMIT, "tag": NEAREST_BUILD_TAG},
                },
            }
        )
    return row


def _historical_nearest_from_manifest(manifest: dict) -> dict:
    record = manifest["nearest_e2"]
    return {
        "schema_version": NEAREST_HISTORICAL_SCHEMA,
        "log_start_utc": "2026-08-29T10:51:08Z",
        "evidence_level": record["evidence_level"],
        "command": record["command"],
        "cwd": record["cwd"],
        "exit_code": record["exit_code"],
        "assertions": record["assertions"],
        "log": record["log"],
        "binary_path": record["binary_path"],
        "binary_sha256": record["binary_sha256"],
        "binary_size_bytes": record["binary_size_bytes"],
        "binary_file_type": record["binary_file_type"],
        "binary_mtime_local": record["binary_mtime_local"],
        "build_identity_commit": record["build_identity_commit"],
        "build_identity_tag": record["build_identity_tag"],
        "verification": dict(record["verification"]),
        "notes": "synthetic historical freeze",
    }


_SYNTHETIC_UNITTEST_PATH = "/synthetic/unittest"
_SYNTHETIC_UNITTEST_BYTES = b"pg-agent-synthetic-nearest-unittest\n"


@contextmanager
def _override_nearest_pins(sha256: str, size: int):
    old_sha = phase0_mod.NEAREST_SHA256
    old_size = phase0_mod.NEAREST_SIZE_BYTES
    phase0_mod.NEAREST_SHA256 = sha256
    phase0_mod.NEAREST_SIZE_BYTES = size
    try:
        yield
    finally:
        phase0_mod.NEAREST_SHA256 = old_sha
        phase0_mod.NEAREST_SIZE_BYTES = old_size


def _nearest_log_text(
    *,
    cwd: str,
    binary_path: str,
    command: str = NEAREST_COMMAND,
    commit: str = DUCKDB_PGAGENT_COMMIT,
    tag: str = NEAREST_BUILD_TAG,
    exit_code: int = 0,
    assertions: int = 112,
    working_tree: str = NEAREST_WORKING_TREE_CLEAN,
    start: str = "2026-08-29T10:51:08Z",
    end: str = "2026-08-29T10:51:09Z",
    include_commit: bool = True,
    include_tag: bool = True,
) -> str:
    lines = [
        f"command: {command}",
        f"cwd: {cwd}",
    ]
    if include_commit:
        lines.append(f"duckdb commit: {commit}")
    if include_tag:
        lines.append(f"duckdb tag: {tag}")
    lines.extend(
        [
            f"binary path: {binary_path}",
            f"working tree: {working_tree}",
            f"start: {start}",
            f"end: {end}",
            f"exit code: {exit_code}",
            "",
            NEAREST_STDOUT_DELIM,
            "Filters: test/sql/join/nearest/nearest_basic.test",
            "",
            "[0/1] (0%): test/sql/join/nearest/nearest_basic.test",
            "[1/1] (100%): test/sql/join/nearest/nearest_basic.test took 0.001s",
            "===============================================================================",
            f"All tests passed ({assertions} assertions in 1 test case)",
            "",
            NEAREST_STDERR_DELIM,
            "(empty)",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sync_default_nearest_artifact(
    manifest: dict,
    historical: dict | None,
    register: dict | None,
    *,
    sha256: str,
    size: int,
    binary_path: str,
) -> None:
    originals_sha = {NEAREST_SHA256}
    originals_size = {NEAREST_SIZE_BYTES}
    originals_path = {_SYNTHETIC_UNITTEST_PATH}

    def touch_record(record: dict | None) -> None:
        if not isinstance(record, dict):
            return
        if record.get("binary_sha256") in originals_sha:
            record["binary_sha256"] = sha256
        if record.get("binary_size_bytes") in originals_size:
            record["binary_size_bytes"] = size
        if record.get("binary_path") in originals_path:
            record["binary_path"] = binary_path

    if isinstance(manifest, dict):
        nearest = manifest.get("nearest_e2")
        if isinstance(nearest, dict):
            touch_record(nearest)
    touch_record(historical if isinstance(historical, dict) else None)
    if isinstance(register, dict):
        contracts = register.get("contracts")
        if isinstance(contracts, list):
            for row in contracts:
                if isinstance(row, dict) and row.get("id") == "nearest_basic":
                    binary = row.get("binary")
                    if isinstance(binary, dict):
                        if binary.get("sha256") in originals_sha:
                            binary["sha256"] = sha256
                        if binary.get("size_bytes") in originals_size:
                            binary["size_bytes"] = size


@contextmanager
def _passable_repo_session(
    manifest,
    baselines,
    corrections,
    provenance,
    register,
    historical,
    *,
    live_log: bool = True,
    live_binary: bool = True,
    log_text: str | None = None,
    binary_bytes: bytes | None = None,
    binary_path: Path | None = None,
    environ: dict[str, str] | None = None,
    pin_live_binary: bool = True,
    public: bool = False,
    log_mutate=None,
    eval_cwd: Path | None = None,
    inject_unittest_env: bool = True,
    configured_relpath_text: str | None = None,
    prepare_root=None,
):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact = Path(binary_path) if binary_path is not None else (root / "synthetic" / "unittest")
        payload = _SYNTHETIC_UNITTEST_BYTES if binary_bytes is None else binary_bytes
        digest = hashlib.sha256(payload).hexdigest()
        size = len(payload)
        if live_binary:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(payload)
            resolved_binary = str(artifact.resolve())
        else:
            resolved_binary = str(artifact)
        cwd = "/synthetic/duckdb-pgagent"
        if isinstance(historical, dict) and historical.get("cwd"):
            cwd = str(historical["cwd"])
        elif isinstance(manifest, dict):
            nearest = manifest.get("nearest_e2")
            if isinstance(nearest, dict) and nearest.get("cwd"):
                cwd = str(nearest["cwd"])
        if live_binary and pin_live_binary:
            _sync_default_nearest_artifact(
                manifest,
                historical if isinstance(historical, dict) else None,
                register if isinstance(register, dict) else None,
                sha256=digest,
                size=size,
                binary_path=resolved_binary,
            )
        log_binary_path = resolved_binary
        if isinstance(historical, dict) and historical.get("binary_path"):
            log_binary_path = str(historical["binary_path"])
        elif isinstance(manifest, dict):
            nearest = manifest.get("nearest_e2")
            if isinstance(nearest, dict) and nearest.get("binary_path"):
                log_binary_path = str(nearest["binary_path"])
        rendered_log = log_text
        if live_log and rendered_log is None:
            rendered_log = _nearest_log_text(cwd=cwd, binary_path=log_binary_path)
        if log_mutate is not None and rendered_log is not None:
            rendered_log = log_mutate(rendered_log)
        v7 = root / "v7"
        evidence = v7 / "evidence"
        contracts = evidence / "contracts"
        contracts.mkdir(parents=True, exist_ok=True)
        if manifest is not None:
            _write_json(v7 / "VERSION_MANIFEST.json", manifest)
        if baselines is not None:
            _write_json(evidence / "phase0_baseline_status.json", baselines)
        if corrections is not None:
            _write_json(evidence / "corrections_register.json", corrections)
        if provenance is not None:
            _write_json(evidence / "four_repo_provenance.json", provenance)
        if register is not None:
            _write_json(contracts / "EVIDENCE_REGISTER.json", register)
        if historical is not None:
            _write_json(evidence / "nearest_e2.json", historical)
        if configured_relpath_text is not None:
            (evidence / Path(NEAREST_LIVE_BINARY_RELPATH_FILE).name).write_text(
                configured_relpath_text, encoding="utf-8"
            )
        if live_log and rendered_log is not None:
            (evidence / "nearest_basic.e2.log").write_text(rendered_log, encoding="utf-8")
        if prepare_root is not None:
            prepare_root(root)
        env = {} if environ is None else dict(environ)
        if live_binary and inject_unittest_env:
            env.setdefault(UNITTEST_BIN_ENV_VARS[0], resolved_binary)
        pin_cm = (
            _override_nearest_pins(digest, size)
            if live_binary and pin_live_binary
            else nullcontext()
        )
        with pin_cm, _working_directory(eval_cwd):
            if public:
                result, verification = evaluate_phase0(root, environ=env), {}
            else:
                result, verification = evaluate_phase0_from_repo(root, environ=env)
            yield {
                "root": root,
                "result": result,
                "verification": verification,
                "environ": env,
            }


def _run_passable_repo(
    manifest,
    baselines,
    corrections,
    provenance,
    register,
    historical,
    **kwargs,
) -> tuple[dict, dict]:
    with _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        **kwargs,
    ) as session:
        return session["result"], session["verification"]


def _passable_gate_inputs() -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    commit = {
        "pg_agent_commit": "a" * 40,
        "flock_commit": "b" * 40,
        "duckdb_pgagent_commit": DUCKDB_PGAGENT_COMMIT,
        "duckdb_python_pgagent_commit": "d" * 40,
        "tachiom_commit": TACHIOM_TAG_COMMIT,
        "duckdb_tachiom_commit": "f" * 40,
    }
    checkout = "9" * 40
    parser = copy.deepcopy(MINERU_PARSER_EXPECTED)
    manifest = {
        **commit,
        "phase": 0,
        "manifest_kind": MANIFEST_KIND,
        "duckdb_engine_version": "v1.6.0-dev",
        "python_version": "CPython 3.12.13",
        "platform_architecture": "macOS arm64",
        "flock_abi_catalog_version": "synthetic.catalog/1",
        "mineru_runtime_distribution_version": "3.4.4",
        "mineru_container_image_digest": None,
        "mineru_container_image_digest_status": NOT_APPLICABLE_STATUS,
        "mineru_container_image_digest_notes": (
            "P19-S identity is mineru[pipeline] wheel + snapshot; OCI digest is not applicable."
        ),
        "mineru_model_name_version_weights_hash": {
            "name": "opendatalab/PDF-Extract-Kit-1.0",
            "version": "ed6b654c",
            "snapshot_manifest_sha256": "2" * 64,
            "single_file_weights_sha256": None,
            "single_file_weights_sha256_status": NOT_APPLICABLE_STATUS,
            "single_file_weights_sha256_notes": (
                "Identity is the 187-file snapshot manifest; single-file weights sha256 is not applicable."
            ),
        },
        "mineru_parser_config": parser,
        "canonical_mineru_contract_version": "synthetic-mineru-ingest-contract/1",
        "mdenseon_package_native_runtime_version": {
            "model_id": "lightonai/mDenseOn",
            "revision": "a5fdb000f7a21da96c3bddde3a782ef777316df3",
            "source": "https://huggingface.co/lightonai/mDenseOn",
            "library_name": "sentence-transformers",
            "lock_format": "duckrag-wi1-upstream-model/1",
            "expected_python": "3.12.13",
        },
        "mdenseon_model_weights_sha256": "3" * 64,
        "tokenizer_identity_version_hash": {
            "identity": "lightonai/mDenseOn tokenizer.json",
            "version": "a5fdb000f7a21da96c3bddde3a782ef777316df3",
            "lfs_sha256": "4" * 64,
        },
        "embedding_batch_contract": "batch=1",
        "embedding_dimension": 768,
        "embedding_dtype": "float32",
        "embedding_normalization": "float32-l2/1",
        "embedding_zero_norm_policy": "reject",
        "tokenizer_identity": "lightonai/mDenseOn tokenizer.json",
        "tokenizer_version": "a5fdb000f7a21da96c3bddde3a782ef777316df3",
        "tokenizer_hash": "4" * 64,
        "mineru_model_name": "opendatalab/PDF-Extract-Kit-1.0",
        "mineru_model_version": "ed6b654c",
        "mineru_model_snapshot_manifest_sha256": "2" * 64,
        "mineru_model_weights_sha256": None,
        "mineru_model_weights_sha256_status": NOT_APPLICABLE_STATUS,
        "mineru_model_weights_sha256_notes": (
            "Top-level alias of single-file weights; not applicable. Snapshot manifest is the identity."
        ),
        "tachiom_envelope_version": 1,
        "bm25_tokenizer": "synthetic-tokenizer",
        "bm25_stemming": "synthetic-stemming",
        "bm25_stop_words": "synthetic-stop-words",
        "bm25_case_folding": "synthetic-case-folding",
        "bm25_unicode_normalization": "synthetic-unicode",
        "bm25_field_weights": "synthetic-field-weights",
        "bm25_backend_version": "synthetic-bm25-backend",
        "bm25_config_hash": "7" * 64,
        "embedding_dimension_dtype_normalization_batch": {
            "dimension": 768,
            "dtype": "float32",
            "normalization": "float32-l2/1",
            "zero_norm_policy": "reject",
            "batch_contract": "batch=1",
        },
        "tachiom_static_loadable_artifact_sha256": "5" * 64,
        "tachiom_index_format_version": 1,
        "fts_extension_version": "6" * 40,
        "bm25_tokenizer_stemming_stopword_casefolding_unicode_config_hash": "7" * 64,
        "build_artifact_wheel_sha256": "8" * 64,
        "v6_python_wheel_path": "v6/dist/old.whl",
        "pg_agent_dirty": False,
        "flock_dirty": False,
        "duckdb_pgagent_dirty": False,
        "duckdb_python_pgagent_dirty": False,
        "duckdb_tachiom_dirty": False,
        "tachiom_checkout_dirty": False,
        "duckdb_pgagent_tag": NEAREST_BUILD_TAG,
        "duckdb_pgagent_tag_commit": DUCKDB_PGAGENT_COMMIT,
        "duckdb_python_pgagent_tag": "duckdb-python-special-synthetic",
        "duckdb_python_pgagent_tag_commit": "d" * 40,
        "duckdb_python_pgagent_vendored_engine_commit": DUCKDB_PGAGENT_COMMIT,
        "duckdb_python_pgagent_vendored_engine_equals_target": True,
        "tachiom_tag": TACHIOM_TAG,
        "tachiom_tag_commit": TACHIOM_TAG_COMMIT,
        "tachiom_commit_kind": "cargo_resolved_build_identity",
        "tachiom_checkout_commit": checkout,
        "tachiom_checkout_is_build_identity": False,
        "tachiom_checkout_tag": None,
        "tachiom_checkout_tag_status": "missing",
        "tachiom_checkout_describe": "synthetic-tachiom-describe",
        "duckdb_tachiom_tag": None,
        "duckdb_tachiom_tag_status": "missing",
        "duckdb_tachiom_cargo_tachiom_git_tag_pin": TACHIOM_TAG,
        "duckdb_tachiom_cargo_tachiom_git_tag_pin_commit": TACHIOM_TAG_COMMIT,
        "build_flags": {
            "v7_python_wheel": {
                "status": "recorded",
                "required_static_extensions": ["flock_extension", "fts_extension"],
                "target_duckdb_commit": commit["duckdb_pgagent_commit"],
                "artifact_path": "v7/dist/synthetic.whl",
                "separate_from_v6_wheel": True,
            }
        },
        "static_build_targets": {
            "flock_static": "flock_extension",
            "flock_loadable": "flock_loadable_extension",
            "fts_static": "fts_extension",
            "fts_loadable": "fts_loadable_extension",
            "tachiom_static_cmake": "tachiom_extension",
            "python_module": "_duckdb",
        },
        "backend_gates": {
            name: {
                "blocked": False,
                "evidence_level": "E2",
                "not_e2": False,
                "reason": "synthetic unblocked E2",
            }
            for name in REQUIRED_BACKEND_GATES
        },
        "completeness": {key: "recorded" for key in SECTION_32_REQUIRED_FIELDS},
        "mineru_profile_id": "mineru-3.4.4-pipeline-cpython312-darwin-arm64",
        "nearest_e2": {
            "evidence_level": "E2",
            "command": NEAREST_COMMAND,
            "cwd": "/synthetic/duckdb-pgagent",
            "exit_code": 0,
            "assertions": 112,
            "log": NEAREST_LOG_REL,
            "binary_path": "/synthetic/unittest",
            "binary_sha256": NEAREST_SHA256,
            "binary_size_bytes": NEAREST_SIZE_BYTES,
            "binary_file_type": "Mach-O 64-bit executable arm64",
            "binary_mtime_local": "2026-08-29T12:21:55",
            "build_identity_commit": DUCKDB_PGAGENT_COMMIT,
            "build_identity_tag": NEAREST_BUILD_TAG,
            "verification": {
                "binary_required_for_live_e2": True,
                "log_required_for_live_e2": True,
                "absent_binary_or_log_gate_level": "blocked",
            },
        },
    }
    manifest["completeness"]["mineru_container_image_digest"] = NOT_APPLICABLE_STATUS
    manifest["completeness"]["mineru_model_name_version_weights_hash"] = "recorded_from_lock"
    baselines = {
        "schema_version": SCHEMA_VERSION,
        "evaluator": EVALUATOR_ID,
        "phase0_pass": True,
        "blocker_ids": [],
        "blocker_classes": [],
        "reasons": [],
        "items": {
            item_id: {
                "contract_frozen": True,
                "live_runtime_missing": False,
                "acceptance_fixture_missing": False,
                "implementation_allowed": True,
                "release_allowed": True,
                "evidence_level": "E2",
                "blocked_backend": LIVE_MISSING_TO_GATE[item_id],
                "notes": "synthetic available baseline",
            }
            for item_id in REQUIRED_BASELINE_IDS
        },
    }
    manifest["backend_gates"]["live_mineru_runtime"] = {
        "blocked": True,
        "evidence_level": "E1",
        "not_e2": True,
        "reason": "cache absent; historical P19-S is not this-freeze live E2",
    }
    baselines["items"]["live_mineru_runtime"] = {
        "contract_frozen": True,
        "live_runtime_missing": True,
        "acceptance_fixture_missing": True,
        "implementation_allowed": False,
        "release_allowed": False,
        "evidence_level": "E0",
        "blocked_backend": "live_mineru_runtime",
        "notes": "operator cache missing; not a Phase 0 pass predicate (Option B, 2026-08-30)",
        "evidence_components": {
            "contract": {"level": "E1", "kind": "json", "id": "mineru"},
            "live_or_fixture": {"level": "E0", "kind": "runtime"},
        },
    }
    corrections = {
        "corrections": [
            {
                "id": "F-1",
                "status": "ABSORBED",
                "alias_of": None,
                "blocked_phase": None,
                "blocked_gate": None,
                "implementation_allowed": True,
                "release_allowed": True,
            }
        ],
        "counts": {
            "unique_unresolved": 0,
            "unique_partial": 0,
            "unique_unresolved_ids": [],
            "unique_partial_ids": [],
        },
    }
    provenance = {
        "repos": {
            "pg-agent": {"commit": commit["pg_agent_commit"], "branch": "main", "dirty": False, "tag": None},
            "flock": {
                "commit": commit["flock_commit"],
                "branch": "dev",
                "dirty": False,
                "tag": None,
                "submodules": {
                    "duckdb": {
                        "recorded_gitlink": DUCKDB_PGAGENT_COMMIT,
                        "initialized": True,
                        "status": "ok",
                    },
                    "extension-ci-tools": {
                        "recorded_gitlink": FLOCK_EXTENSION_CI_TOOLS_COMMIT,
                        "initialized": True,
                        "status": "ok",
                    },
                },
            },
            "duckdb-pgagent": {
                "commit": DUCKDB_PGAGENT_COMMIT,
                "branch": "integration/grammar",
                "dirty": False,
                "tag": NEAREST_BUILD_TAG,
            },
            "duckdb-python-pgagent": {
                "commit": commit["duckdb_python_pgagent_commit"],
                "branch": "integration/python",
                "dirty": False,
                "tag": "duckdb-python-special-synthetic",
                "vendored_engine": {
                    "commit": DUCKDB_PGAGENT_COMMIT,
                    "matches_duckdb_pgagent": True,
                },
            },
        },
        "external_not_four_repo": {
            "tachiom": {
                "commit": checkout,
                "dirty": False,
                "tag": None,
                "tag_status": "missing",
                "describe": "synthetic-tachiom-describe",
            },
            "duckdb-tachiom": {
                "commit": commit["duckdb_tachiom_commit"],
                "dirty": False,
                "tag": None,
                "tag_status": "missing",
            },
        },
        "static_build_targets_exact": {
            "flock": {"static_cmake_target": "flock_extension"},
            "fts": {"static_cmake_target": "fts_extension"},
            "tachiom": {"static_cmake_target": "tachiom_extension"},
            "python_loader": {"python_module_target": "_duckdb"},
        },
    }
    register = {
        "schema_version": EVIDENCE_REGISTER_SCHEMA,
        "evidence_levels": {
            "E0": "unread/unknown/missing — cannot implement against",
            "E1": "source/tests/static contract inspected",
            "E2": "ran on target runtime/fixture this freeze",
            "E3": "cross-repository integration/acceptance on the frozen four-repo pins. Phase 0 is not E3.",
        },
        "contracts": [_passable_contract(spec, manifest) for spec in REQUIRED_CONTRACT_SPECS],
    }
    historical = _historical_nearest_from_manifest(manifest)
    return manifest, baselines, corrections, provenance, register, historical, None


def _evaluate_passable(inputs: tuple | None = None) -> dict:
    manifest, baselines, corrections, provenance, register, historical, nearest = inputs or _passable_gate_inputs()
    return _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)


def _passed_phase_gates() -> dict:
    gates = {}
    for phase_id in PHASE_IDS:
        gates[phase_id] = {
            "state": "PASSED",
            "evidence_level": "E3" if phase_id == "phase_7" else "E2",
            "exit_criteria_passed": True,
        }
    return gates


def _passed_e3() -> dict:
    return {
        "state": "PASSED",
        "evidence_level": "E3",
        "frozen_four_repo_pins": True,
        "cross_repo_integration_passed": True,
        "phase_7_exit_criteria_passed": True,
    }


def _inject_blocker_class(
    cls: str,
    manifest: dict,
    baselines: dict,
    corrections: dict,
    provenance: dict,
    nearest: dict,
) -> dict:
    if cls == BLOCKER_CLASS_BLOCKERS:
        manifest.setdefault("backend_gates", {})["dense_mdenseon"] = {
            "blocked": True,
            "not_e2": True,
            "evidence_level": "E1",
            "reason": "synthetic blocked backend",
        }
    elif cls == BLOCKER_CLASS_MISSING_BASELINES:
        baselines["items"]["live_legacy_cache"]["live_runtime_missing"] = True
    elif cls == BLOCKER_CLASS_OPEN_CORRECTIONS:
        corrections.setdefault("corrections", []).append(
            {
                "id": "C3",
                "status": "UNRESOLVED",
                "alias_of": None,
                "blocked_phase": 1,
                "blocked_gate": "synthetic_open_correction",
                "implementation_allowed": False,
                "release_allowed": False,
            }
        )
    elif cls == BLOCKER_CLASS_REQUIRED_NULL_HASHES:
        manifest["tachiom_static_loadable_artifact_sha256"] = None
        manifest["completeness"]["tachiom_static_loadable_artifact_sha256"] = "blocked"
        manifest["tachiom_static_loadable_artifact_sha256_status"] = "blocked"
        manifest["tachiom_static_loadable_artifact_sha256_notes"] = "synthetic null"
    elif cls == BLOCKER_CLASS_CONFIGURATION:
        manifest["flock_abi_catalog_version"] = None
        manifest["completeness"]["flock_abi_catalog_version"] = "blocked"
        manifest["flock_abi_catalog_version_status"] = "blocked"
        manifest["flock_abi_catalog_version_notes"] = "synthetic null"
    elif cls == BLOCKER_CLASS_DIRTY_UNINITIALIZED:
        manifest["pg_agent_dirty"] = True
        row = (provenance.get("repos") or {}).get("pg-agent")
        if isinstance(row, dict):
            row["dirty"] = True
    elif cls == BLOCKER_CLASS_LIVE_EVIDENCE:
        pass
    elif cls == BLOCKER_CLASS_MANIFEST:
        del manifest["python_version"]
    else:
        raise ValueError(cls)
    return nearest


def derive_nearest_gate_level(*, log_ok: bool, binary_ok: bool) -> str:
    if log_ok and binary_ok:
        return "E2"
    return "blocked"


def _cargo_lock_candidates(provenance: dict) -> list[object]:
    candidates: list[object] = []
    external = (provenance.get("external_not_four_repo") or {}).get("duckdb-tachiom") or {}
    path = external.get("path")
    if isinstance(path, str) and path:
        recorded = Path(path)
        if not recorded.is_absolute():
            candidates.append(recorded / "Cargo.lock")
    return candidates


def _unittest_bin_candidates(nearest: dict, manifest: dict) -> list[object]:
    manifest_nearest = manifest.get("nearest_e2") or {}
    candidates: list[object] = [
        nearest.get("binary_path"),
        manifest_nearest.get("binary_path"),
    ]
    configured = _resolve_configured_live_binary(REPO_ROOT)
    if configured is not None:
        try:
            rel = configured.relative_to(REPO_ROOT.resolve())
            candidates.append(rel)
        except ValueError:
            pass
    return candidates


def test_required_section_32_keys(manifest: dict) -> None:
    completeness = manifest.get("completeness")
    check("completeness map exists", isinstance(completeness, dict), type(completeness).__name__)
    missing = [key for key in SECTION_32_REQUIRED_FIELDS if key not in manifest]
    missing_completeness = [key for key in SECTION_32_REQUIRED_FIELDS if key not in completeness]
    check("every §3.2 required field key exists", missing == [], missing)
    check("completeness map covers every §3.2 field", missing_completeness == [], missing_completeness)
    for key in SECTION_32_REQUIRED_FIELDS:
        check(f"§3.2 field {key}", key in manifest and key in completeness)


def test_duckdb_pgagent_pin(manifest: dict) -> None:
    commit = manifest.get("duckdb_pgagent_commit")
    check("duckdb_pgagent_commit is str", isinstance(commit, str), type(commit).__name__)
    check("duckdb_pgagent_commit is 40-char hex", bool(COMMIT_RE.match(str(commit))), commit)
    check("duckdb_pgagent_commit is a1f0ab191185…", commit == DUCKDB_PGAGENT_COMMIT, commit)
    check("duckdb_pgagent_commit starts with a1f0ab1911", str(commit).startswith("a1f0ab1911"), commit)


def test_four_repo_commits_match(manifest: dict, provenance: dict) -> None:
    repos = provenance.get("repos")
    check("four_repo_provenance.repos exists", isinstance(repos, dict), type(repos).__name__)
    for repo_name, manifest_key in FOUR_REPO_COMMIT_KEYS:
        recorded = repos.get(repo_name, {}).get("commit")
        check(
            f"provenance {repo_name} commit matches {manifest_key}",
            recorded == manifest.get(manifest_key),
            (recorded, manifest.get(manifest_key)),
        )
    external = provenance.get("external_not_four_repo") or {}
    dt = external.get("duckdb-tachiom")
    check("provenance duckdb-tachiom is a mapping", isinstance(dt, dict), type(dt).__name__)
    dt = dt or {}
    check(
        "provenance duckdb-tachiom commit is 40-char hex",
        bool(COMMIT_RE.match(str(dt.get("commit") or ""))),
        dt.get("commit"),
    )
    check(
        "provenance duckdb-tachiom commit matches duckdb_tachiom_commit",
        dt.get("commit") == manifest.get("duckdb_tachiom_commit"),
        (dt.get("commit"), manifest.get("duckdb_tachiom_commit")),
    )
    tachiom_ext = external.get("tachiom")
    check("provenance tachiom is a mapping", isinstance(tachiom_ext, dict), type(tachiom_ext).__name__)
    tachiom_ext = tachiom_ext or {}
    check(
        "provenance tachiom commit is 40-char hex",
        bool(COMMIT_RE.match(str(tachiom_ext.get("commit") or ""))),
        tachiom_ext.get("commit"),
    )
    check(
        "provenance tachiom checkout matches tachiom_checkout_commit, not the build pin",
        tachiom_ext.get("commit") == manifest.get("tachiom_checkout_commit") != manifest.get("tachiom_commit"),
        (tachiom_ext.get("commit"), manifest.get("tachiom_checkout_commit"), manifest.get("tachiom_commit")),
    )
    python_row = repos.get("duckdb-python-pgagent") or {}
    vendored = python_row.get("vendored_engine") or {}
    check(
        "provenance vendored_engine.matches_duckdb_pgagent is true",
        vendored.get("matches_duckdb_pgagent") is True,
        vendored,
    )
    duckdb_row = repos.get("duckdb-pgagent") or {}
    check(
        "provenance duckdb-pgagent tag equals NEAREST_BUILD_TAG",
        duckdb_row.get("tag") == manifest.get("duckdb_pgagent_tag") == NEAREST_BUILD_TAG,
        (duckdb_row.get("tag"), manifest.get("duckdb_pgagent_tag")),
    )


def test_commit_tag_vendored_identity(manifest: dict) -> None:
    for key in COMMIT_40_KEYS:
        value = manifest.get(key)
        check(f"{key} is 40-char hex", bool(COMMIT_RE.match(str(value or ""))), value)
    checkout = manifest.get("tachiom_checkout_commit")
    check(
        "tachiom_checkout_commit is 40-char hex",
        bool(COMMIT_RE.match(str(checkout or ""))),
        checkout,
    )
    for tag_key, tag_commit_key, pin_key in TAG_COMMIT_PAIRS:
        tag = manifest.get(tag_key)
        if not tag:
            continue
        tag_commit = manifest.get(tag_commit_key)
        check(
            f"{tag_commit_key} is 40-char hex",
            bool(COMMIT_RE.match(str(tag_commit or ""))),
            tag_commit,
        )
        check(
            f"{tag_key} commit equals {pin_key}",
            tag_commit == manifest.get(pin_key),
            (tag, tag_commit, manifest.get(pin_key)),
        )
    vendored = manifest.get("duckdb_python_pgagent_vendored_engine_commit")
    check(
        "vendored engine commit is 40-char hex",
        bool(COMMIT_RE.match(str(vendored or ""))),
        vendored,
    )
    check(
        "vendored engine equals duckdb-pgagent pin",
        vendored == manifest.get("duckdb_pgagent_commit") == DUCKDB_PGAGENT_COMMIT,
        (vendored, manifest.get("duckdb_pgagent_commit")),
    )
    check(
        "vendored/target equality flag is true",
        manifest.get("duckdb_python_pgagent_vendored_engine_equals_target") is True,
        manifest.get("duckdb_python_pgagent_vendored_engine_equals_target"),
    )


def test_tachiom_build_identity_is_cargo_resolved(manifest: dict, provenance: dict) -> None:
    pin = manifest.get("tachiom_commit")
    check("tachiom_commit is 40-char hex", bool(COMMIT_RE.match(str(pin or ""))), pin)
    check("tachiom_commit equals tag v0.3.4 commit", pin == TACHIOM_TAG_COMMIT, pin)
    check("tachiom_tag is v0.3.4", manifest.get("tachiom_tag") == "v0.3.4", manifest.get("tachiom_tag"))
    check(
        "tachiom_commit_kind is cargo_resolved_build_identity",
        manifest.get("tachiom_commit_kind") == "cargo_resolved_build_identity",
        manifest.get("tachiom_commit_kind"),
    )
    check(
        "tachiom_commit equals recorded cargo pin commit",
        pin == manifest.get("duckdb_tachiom_cargo_tachiom_git_tag_pin_commit") == TACHIOM_TAG_COMMIT,
        (pin, manifest.get("duckdb_tachiom_cargo_tachiom_git_tag_pin_commit")),
    )
    notes = str(manifest.get("duckdb_tachiom_cargo_tachiom_git_tag_pin_notes") or "")
    notes_match = TACHIOM_CARGO_PIN_RE.search(notes)
    check("repo-local cargo source line records tag v0.3.4 SHA", notes_match is not None, notes)
    check(
        "repo-local cargo source SHA equals tachiom_commit",
        (notes_match.group(1) if notes_match else "") == pin,
        (notes_match.group(1) if notes_match else None, pin),
    )
    cargo_lock, source = _resolve_optional_file(
        CARGO_LOCK_ENV_VARS,
        _cargo_lock_candidates(provenance),
        allow_absolute=False,
    )
    if cargo_lock is not None and cargo_lock.is_file():
        lock_text = cargo_lock.read_text(encoding="utf-8")
        match = TACHIOM_CARGO_SOURCE_RE.search(lock_text)
        check("Cargo.lock records tachiom git tag v0.3.4 with resolved SHA", match is not None, source)
        resolved = match.group(1) if match else ""
        check("tachiom_commit equals Cargo.lock resolved SHA", pin == resolved, (pin, resolved, source))
        check("live Cargo.lock source is env or repo-relative recorded", source.startswith("env:") or source == "recorded", source)
    else:
        check(
            "live duckdb-tachiom Cargo.lock absence is blocked, not a path-layout failure",
            source in {"absent", "recorded"} or str(source).endswith(":missing"),
            source,
        )
    checkout = manifest.get("tachiom_checkout_commit")
    check("checkout HEAD is recorded separately", bool(COMMIT_RE.match(str(checkout or ""))), checkout)
    check(
        "checkout is not the build identity",
        manifest.get("tachiom_checkout_is_build_identity") is False,
        manifest.get("tachiom_checkout_is_build_identity"),
    )
    check(
        "checkout HEAD is recorded separately from cargo pin",
        checkout != pin,
        (checkout, pin),
    )


def test_null_required_hashes_are_honest(manifest: dict) -> None:
    completeness = manifest["completeness"]
    for key in SECTION_32_REQUIRED_FIELDS:
        value = manifest.get(key)
        status = completeness.get(key)
        if value is None:
            sibling_status, sibling_notes = _sibling_status_notes(manifest, key)
            check(f"{key} null has sibling status", bool(sibling_status), sibling_status)
            check(f"{key} null has sibling notes", bool(sibling_notes), sibling_notes)
            check(
                f"{key} completeness is not recorded while value is null",
                status not in RECORDED_COMPLETENESS,
                status,
            )
            if key in NOT_APPLICABLE_HASH_PATHS and status == NOT_APPLICABLE_STATUS:
                check(
                    f"{key} completeness is not_applicable while value is null",
                    status == NOT_APPLICABLE_STATUS,
                    status,
                )
                check(
                    f"{key} sibling status is not_applicable while value is null",
                    sibling_status == NOT_APPLICABLE_STATUS,
                    sibling_status,
                )
            else:
                check(f"{key} completeness is blocked while value is null", status == "blocked", status)
        elif status in RECORDED_COMPLETENESS:
            check(f"{key} recorded completeness has a value", value is not None)

    for key in REQUIRED_HASH_FIELDS:
        value = manifest.get(key)
        if value is None:
            sibling_status, sibling_notes = _sibling_status_notes(manifest, key)
            check(f"required hash {key} null has sibling status", bool(sibling_status), sibling_status)
            check(f"required hash {key} null has sibling notes", bool(sibling_notes), sibling_notes)
            check(
                f"required hash {key} completeness != recorded",
                completeness.get(key) not in RECORDED_COMPLETENESS,
                completeness.get(key),
            )

    for path, container, key in _iter_hash_nulls(manifest):
        sibling_status, sibling_notes = _sibling_status_notes(container, key)
        check(f"null hash {path} has sibling status", bool(sibling_status), sibling_status)
        check(f"null hash {path} has sibling notes", bool(sibling_notes), sibling_notes)
        check(
            f"null hash {path} status is not a recorded completeness token",
            sibling_status not in RECORDED_COMPLETENESS,
            sibling_status,
        )


def test_recursive_nested_completeness(manifest: dict) -> None:
    """P1-4: parent completeness must not be recorded* while a required nested value is null.

    The Phase 0 bug was embedding_dimension_dtype_normalization_batch_status=recorded_from_lock
    with batch_contract=null, and mineru_model_name_version_weights_hash recorded with
    single_file_weights_sha256=null.
    """
    completeness = manifest["completeness"]

    def walk(obj: object, path: str) -> None:
        if not isinstance(obj, dict):
            if isinstance(obj, list):
                for index, item in enumerate(obj):
                    walk(item, f"{path}[{index}]")
            return
        for key, value in obj.items():
            if _is_meta_key(key):
                continue
            child = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                nested_nulls = _required_null_keys(value, child)
                if nested_nulls:
                    tokens = [completeness.get(key)] if path == "" else []
                    tokens.append(obj.get(f"{key}_status"))
                    tokens.append(value.get("status"))
                    for token in tokens:
                        if token is None:
                            continue
                        check(
                            f"{child} must not be recorded while nested {nested_nulls} are null",
                            token not in RECORDED_COMPLETENESS,
                            (token, nested_nulls),
                        )
                walk(value, child)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{child}[{index}]")

    walk(manifest, "")
    embedding = manifest.get("embedding_dimension_dtype_normalization_batch")
    check("embedding composite is a dict", isinstance(embedding, dict), type(embedding).__name__)
    if isinstance(embedding, dict) and embedding.get("batch_contract") is None:
        check(
            "embedding composite completeness is not recorded while batch_contract is null",
            completeness.get("embedding_dimension_dtype_normalization_batch") not in RECORDED_COMPLETENESS,
            completeness.get("embedding_dimension_dtype_normalization_batch"),
        )
        check(
            "embedding composite status is not recorded while batch_contract is null",
            manifest.get("embedding_dimension_dtype_normalization_batch_status") not in RECORDED_COMPLETENESS,
            manifest.get("embedding_dimension_dtype_normalization_batch_status"),
        )
    mineru_hash = manifest.get("mineru_model_name_version_weights_hash")
    if isinstance(mineru_hash, dict) and mineru_hash.get("single_file_weights_sha256") is None:
        nested_path = "mineru_model_name_version_weights_hash.single_file_weights_sha256"
        if not _allowlisted_na_null_leaf(mineru_hash, "single_file_weights_sha256", nested_path):
            check(
                "mineru weights composite completeness is not recorded while single-file sha is null",
                completeness.get("mineru_model_name_version_weights_hash") not in RECORDED_COMPLETENESS,
                completeness.get("mineru_model_name_version_weights_hash"),
            )


def test_lock_copied_values_match_register(manifest: dict, register: dict) -> None:
    frozen = _contract_by_id(register, "mdenseon").get("frozen_without_live_files")
    check("mdenseon frozen_without_live_files exists", isinstance(frozen, dict), frozen)
    check(
        "mdenseon weights sha copied from register lock",
        manifest.get("mdenseon_model_weights_sha256") == frozen.get("weights_lfs_sha256_from_lock"),
        (manifest.get("mdenseon_model_weights_sha256"), frozen.get("weights_lfs_sha256_from_lock")),
    )
    check("mdenseon weights sha is sha256 hex", bool(SHA256_RE.match(str(manifest.get("mdenseon_model_weights_sha256") or ""))))
    tokenizer_hash = None
    identity = manifest.get("tokenizer_identity_version_hash")
    if isinstance(identity, dict):
        tokenizer_hash = identity.get("lfs_sha256")
    check(
        "tokenizer lfs sha copied from register lock",
        tokenizer_hash == frozen.get("tokenizer_json_lfs_sha256_from_lock")
        and manifest.get("tokenizer_hash") == frozen.get("tokenizer_json_lfs_sha256_from_lock"),
        (tokenizer_hash, manifest.get("tokenizer_hash"), frozen.get("tokenizer_json_lfs_sha256_from_lock")),
    )
    check("embedding dimension 768 from lock", manifest.get("embedding_dimension") == frozen.get("expected_dimension") == 768)
    check("embedding dtype float32 from lock", manifest.get("embedding_dtype") == frozen.get("dtype") == "float32")
    check(
        "mdenseon model_id from lock",
        manifest.get("mdenseon_package_native_runtime_version", {}).get("model_id") == frozen.get("model_id"),
        manifest.get("mdenseon_package_native_runtime_version"),
    )

    mineru_md = MINERU_CONTRACT_PATH.read_text(encoding="utf-8")
    check("mineru contract contains wheel sha", MINERU_WHEEL_SHA256_FROM_CONTRACT in mineru_md)
    check("mineru version 3.4.4 from lock", manifest.get("mineru_runtime_distribution_version") == "3.4.4")
    check(
        "mineru wheel sha copied from contract lock",
        manifest.get("mineru_wheel_sha256") == MINERU_WHEEL_SHA256_FROM_CONTRACT,
        manifest.get("mineru_wheel_sha256"),
    )
    check("tachiom envelope version 1", manifest.get("tachiom_index_format_version") == 1)
    check("tachiom envelope version field 1", manifest.get("tachiom_envelope_version") == 1)


def test_live_absent_backends_stay_blocked(manifest: dict, baselines: dict) -> None:
    gates = manifest.get("backend_gates")
    check("backend_gates exists", isinstance(gates, dict), type(gates).__name__)
    for name in ("dense_mdenseon", "multi_vector_tachiom", "live_mineru_runtime"):
        gate = gates.get(name) or {}
        check(f"{name} blocked", gate.get("blocked") is True, gate)
        check(f"{name} not E2", gate.get("evidence_level") != "E2" and gate.get("not_e2") is True, gate)
    check("mineru container digest still null", manifest.get("mineru_container_image_digest") is None)
    check(
        "mineru container completeness not_applicable",
        manifest["completeness"].get("mineru_container_image_digest") == NOT_APPLICABLE_STATUS,
    )
    check(
        "tachiom artifact sha still blocked",
        manifest.get("tachiom_static_loadable_artifact_sha256") is None
        and manifest["completeness"].get("tachiom_static_loadable_artifact_sha256") == "blocked",
    )
    e2_completeness = [
        key
        for key in SECTION_32_REQUIRED_FIELDS
        if manifest["completeness"].get(key) in {"e2", "E2", "recorded_e2"}
    ]
    check("no §3.2 completeness claims E2", e2_completeness == [], e2_completeness)

    items = baselines.get("items")
    check("phase0 baselines items exist", isinstance(items, dict), type(items).__name__)
    for item_id, gate_name in LIVE_MISSING_TO_GATE.items():
        item = items.get(item_id) or {}
        gate = gates.get(gate_name) or {}
        if item.get("implementation_allowed") is False:
            check(f"{gate_name} blocked for missing {item_id}", gate.get("blocked") is True, gate)
            check(
                f"{gate_name} not E2 for missing {item_id}",
                gate.get("evidence_level") != "E2" and gate.get("not_e2") is True,
                gate,
            )
            check(f"{item_id} implementation_allowed is false", item.get("implementation_allowed") is False, item)
            check(f"{item_id} release_allowed is false", item.get("release_allowed") is False, item)
            check(
                f"{item_id} still missing live runtime or fixture",
                item.get("live_runtime_missing") is True or item.get("acceptance_fixture_missing") is True,
                item,
            )


def test_evidence_register_ids(register: dict) -> None:
    ids = [row.get("id") for row in register.get("contracts", [])]
    for contract_id in REQUIRED_CONTRACT_IDS:
        check(f"register id {contract_id}", contract_id in ids, ids)


def test_authority_does_not_claim_all_corrections_absorbed() -> None:
    plan = PLAN_PATH.read_text(encoding="utf-8")
    check("v4.1 plan exists", PLAN_PATH.is_file(), str(PLAN_PATH))
    check("v4.1 does not claim 全部纠正项 absorbed", "全部纠正项" not in plan)
    check("v4.1 states 并非全部吸收", "并非全部吸收" in plan)
    check(
        "v4.1 points at traceability as open-item list",
        "flock-rag-v4.1-review-correction-traceability.md" in plan,
    )
    check(
        "v4.1 points at corrections_register.json",
        "v7/evidence/corrections_register.json" in plan,
    )


def test_corrections_register_matches_traceability(corrections: dict) -> None:
    trace = TRACE_PATH.read_text(encoding="utf-8")
    rows = corrections.get("corrections")
    check("corrections list exists", isinstance(rows, list) and rows, type(rows).__name__)
    counts = corrections.get("counts") or {}
    unique_unresolved = [
        row["id"]
        for row in rows
        if row.get("status") == "UNRESOLVED" and not row.get("alias_of")
    ]
    unique_partial = [
        row["id"]
        for row in rows
        if row.get("status") == "PARTIAL" and not row.get("alias_of")
    ]
    check("unique unresolved count matches JSON counts", unique_unresolved == counts.get("unique_unresolved_ids") == UNIQUE_UNRESOLVED_IDS, unique_unresolved)
    check("unique partial count matches JSON counts", unique_partial == counts.get("unique_partial_ids") == UNIQUE_PARTIAL_IDS, unique_partial)
    check("counts.unique_unresolved is 4", counts.get("unique_unresolved") == 4, counts.get("unique_unresolved"))
    check("counts.unique_partial is 7", counts.get("unique_partial") == 7, counts.get("unique_partial"))
    check("traceability Unique UNRESOLVED names C3", "C3 / DR-DM-1" in trace and "DR-PO-1" in trace and "DR-PO-2" in trace and "DR-PO-3" in trace)
    check(
        "traceability Unique PARTIAL matches JSON",
        "F-9, F-12, C5, C6, C7, DR-SEC-4, DR-T-2" in trace,
    )
    for row in rows:
        status = row.get("status")
        check(f"{row.get('id')} status is known", status in {"ABSORBED", "PARTIAL", "UNRESOLVED"}, status)
        if status in {"UNRESOLVED", "PARTIAL"}:
            check(
                f"{row.get('id')} UNRESOLVED/PARTIAL has blocked_gate",
                isinstance(row.get("blocked_gate"), str) and bool(row.get("blocked_gate")),
                row,
            )
            check(f"{row.get('id')} implementation_allowed is false", row.get("implementation_allowed") is False, row)
            check(f"{row.get('id')} release_allowed is false", row.get("release_allowed") is False, row)
            check(f"{row.get('id')} blocked_phase key exists", "blocked_phase" in row, row)


def test_derived_gates(manifest: dict, baselines: dict, corrections: dict, provenance: dict, register: dict) -> None:
    derived, nearest = evaluate_phase0_from_repo(REPO_ROOT)
    rooted = evaluate_phase0(REPO_ROOT)
    check("canonical evaluate_phase0 equals from_repo result", rooted == derived, rooted)
    errors = phase0_record_consistency_errors(baselines, derived)
    check("recorded Phase 0 gate exactly equals evaluator", errors == [], errors)
    check("derived phase0_pass is false while required evidence is missing", derived["phase0_pass"] is False, derived)
    check(
        "dump omits live_mineru_runtime from Phase 0 pass blockers",
        "live_mineru_runtime" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "dump omits baseline.live_mineru_runtime from Phase 0 pass blockers",
        "baseline.live_mineru_runtime" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "dump omits range_trio_acceptance after fixture E2",
        "range_trio_acceptance" not in derived["blocker_ids"]
        and "kohaku_mineru_range_trio" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "canonical_mineru_contract_version remains a configuration gap",
        "canonical_mineru_contract_version" in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check("recorded phase0_pass is false", baselines.get("phase0_pass") is False, baselines.get("phase0_pass"))
    gate = manifest.get("release_gate") or {}
    check("release_gate.phase0 exactly equals Phase 0 evaluator", gate.get("phase0") == derived, gate.get("phase0"))
    release = evaluate_release_gate(derived, gate.get("phase_gates"), gate.get("e3"))
    bound_release = evaluate_release_gate(
        derived, gate.get("phase_gates"), gate.get("e3"), repo_root=REPO_ROOT
    )
    check("bound live release equals unbound live release", bound_release == release, bound_release)
    rel_errors = release_record_consistency_errors(gate, release)
    check("recorded release_gate exactly equals evaluator", rel_errors == [], rel_errors)
    check("recorded would_pass is false", gate.get("would_pass") is False, gate.get("would_pass"))
    check("recorded release_ready is false", gate.get("release_ready") is False, gate.get("release_ready"))
    check("derived release_ready is false", release["release_ready"] is False, release)
    check("would_pass equals release_ready, not phase0_pass by alias", release["would_pass"] is release["release_ready"])
    expected_classes = [
        cls
        for cls in PHASE0_BLOCKER_CLASS_ORDER
        if cls
        in {
            BLOCKER_CLASS_BLOCKERS,
            BLOCKER_CLASS_MISSING_BASELINES,
            BLOCKER_CLASS_OPEN_CORRECTIONS,
            BLOCKER_CLASS_REQUIRED_NULL_HASHES,
            BLOCKER_CLASS_CONFIGURATION,
            BLOCKER_CLASS_DIRTY_UNINITIALIZED,
        }
        or (cls == BLOCKER_CLASS_MANIFEST and BLOCKER_CLASS_MANIFEST in derived["blocker_classes"])
        or (cls == BLOCKER_CLASS_LIVE_EVIDENCE and nearest.get("verified") is not True)
    ]
    check("live Phase 0 blocker_classes equal evaluator order", derived["blocker_classes"] == expected_classes, derived["blocker_classes"])
    if nearest.get("verified") is not True:
        check(
            "unverified NEAREST is the stable live-evidence blocker",
            NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"],
            derived["blocker_ids"],
        )
    else:
        check(
            "verified NEAREST does not add nearest_target_e2_unverified",
            NEAREST_TARGET_E2_UNVERIFIED not in derived["blocker_ids"],
            derived["blocker_ids"],
        )
    flipped_baselines = copy.deepcopy(baselines)
    flipped_baselines["phase0_pass"] = True
    check(
        "flipping recorded phase0_pass to true is detected",
        bool(phase0_record_consistency_errors(flipped_baselines, derived)),
        phase0_record_consistency_errors(flipped_baselines, derived),
    )
    reordered = copy.deepcopy(baselines)
    reordered["blocker_ids"] = list(reversed(list(reordered.get("blocker_ids") or [])))
    check("reordering recorded blocker_ids is detected", bool(phase0_record_consistency_errors(reordered, derived)))
    mutated_reason = copy.deepcopy(baselines)
    if mutated_reason.get("reasons"):
        mutated_reason["reasons"][0] = dict(mutated_reason["reasons"][0])
        mutated_reason["reasons"][0]["code"] = "MANIFEST_FIELD_MISSING"
    check("mutating a recorded reason is detected", bool(phase0_record_consistency_errors(mutated_reason, derived)))
    flipped_gate = copy.deepcopy(gate)
    flipped_gate["would_pass"] = True
    flipped_gate["release_ready"] = True
    check(
        "flipping recorded release booleans to true is detected",
        bool(release_record_consistency_errors(flipped_gate, release)),
    )


def test_gate_relational_blocker_classes() -> None:
    passable = _evaluate_passable()
    check("constructed no-blocker scenario derives phase0_pass true", passable["phase0_pass"] is True, passable)
    check("constructed no-blocker reasons empty", passable["reasons"] == [], passable["reasons"])
    check("constructed no-blocker ids empty", passable["blocker_ids"] == [], passable["blocker_ids"])
    incomplete_release = evaluate_release_gate(passable, default_phase_gates(), default_e3_state())
    check(
        "passable Phase 0 still leaves release false",
        incomplete_release["release_ready"] is False and incomplete_release["would_pass"] is False,
        incomplete_release,
    )
    check(
        "passable Phase 0 is not used as would_pass",
        incomplete_release["would_pass"] is not passable["phase0_pass"],
        (passable["phase0_pass"], incomplete_release["would_pass"]),
    )
    unbound_complete = evaluate_release_gate(passable, _passed_phase_gates(), _passed_e3())
    check(
        "unbound passable Phase 0 cannot be release-ready",
        unbound_complete["release_ready"] is False and unbound_complete["would_pass"] is False,
        unbound_complete,
    )
    check(
        "unbound passable Phase 0 is source-unbound",
        PHASE0_SOURCE_UNBOUND in unbound_complete["blocker_ids"],
        unbound_complete["blocker_ids"],
    )
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    with _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
    ) as session:
        complete_release = evaluate_release_gate(
            session["result"],
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=session["root"],
            environ=session["environ"],
        )
        check(
            "canonical passable Phase 0 plus Phase 1-7 and E3 is release-ready",
            complete_release["release_ready"] is True and complete_release["would_pass"] is True,
            complete_release,
        )
        check("canonical passable Phase 0 actually passed", session["result"]["phase0_pass"] is True, session["result"])

    for cls in PHASE0_INJECTABLE_CLASSES:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        nearest = _inject_blocker_class(cls, manifest, baselines, corrections, provenance, nearest)
        live = cls != BLOCKER_CLASS_LIVE_EVIDENCE
        derived = _eval_passable_now(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
            live_log=live,
            live_binary=live,
        )
        check(f"{cls} forces derived phase0_pass false", derived["phase0_pass"] is False, derived)
        check(f"{cls} is present in derived blocker_classes", cls in derived["blocker_classes"], derived["blocker_classes"])
        release = evaluate_release_gate(derived, default_phase_gates(), default_e3_state())
        check(f"{cls} leaves release false", release["release_ready"] is False, release)
        baselines["phase0_pass"] = derived["phase0_pass"]
        baselines["blocker_ids"] = list(derived["blocker_ids"])
        baselines["blocker_classes"] = list(derived["blocker_classes"])
        baselines["reasons"] = list(derived["reasons"])
        consistent = phase0_record_consistency_errors(baselines, derived)
        check(f"{cls} honest recorded Phase 0 matches derived", consistent == [], consistent)
        baselines["phase0_pass"] = True
        contradictory = phase0_record_consistency_errors(baselines, derived)
        check(f"{cls} contradictory true phase0_pass is detected", bool(contradictory), contradictory)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    corrections["corrections"].append(
        {
            "id": "F-9",
            "status": "PARTIAL",
            "alias_of": None,
            "blocked_phase": 2,
            "blocked_gate": "synthetic_partial",
            "implementation_allowed": False,
            "release_allowed": False,
        }
    )
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    release = evaluate_release_gate(derived, default_phase_gates(), default_e3_state())
    check("PARTIAL open correction forces phase0 false", derived["phase0_pass"] is False, derived)
    check("PARTIAL open correction leaves release false", release["release_ready"] is False, release)
    check("PARTIAL reasons include open_corrections", BLOCKER_CLASS_OPEN_CORRECTIONS in derived["blocker_classes"], derived)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["flock"]["submodules"]["duckdb"] = {
        "recorded_gitlink": "1" * 40,
        "initialized": False,
        "status": "blocked",
    }
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("uninitialized flock.duckdb forces phase0 false", derived["phase0_pass"] is False, derived)
    check(
        "uninitialized submodule class is dirty_uninitialized_dependencies",
        BLOCKER_CLASS_DIRTY_UNINITIALIZED in derived["blocker_classes"],
        derived,
    )
    check(
        "blocked mismatched flock.duckdb gitlink is not extra manifest_contract",
        BLOCKER_CLASS_MANIFEST not in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    del baselines["items"][REQUIRED_BASELINE_IDS[0]]
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("deleting a required baseline item forces phase0 false", derived["phase0_pass"] is False, derived)
    check(
        "deleted required baseline class is missing_baselines",
        BLOCKER_CLASS_MISSING_BASELINES in derived["blocker_classes"],
        derived,
    )


def _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest=None, **kwargs):
    return _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        **kwargs,
    )[0]


def _eval_public_phase0(manifest, baselines, corrections, provenance, register, historical, nearest=None, **kwargs):
    return _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
        **kwargs,
    )[0]


def test_gate_mutations() -> None:
    for item_id in REQUIRED_BASELINE_IDS:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        del baselines["items"][item_id]
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"deleting baseline {item_id} fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"deleting baseline {item_id} is missing_baselines",
            BLOCKER_CLASS_MISSING_BASELINES in derived["blocker_classes"],
            derived["blocker_classes"],
        )

    for parent, nested in MANDATORY_NESTED_FIELDS:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        container = manifest[parent]
        if nested == "single_file_weights_sha256":
            del container[nested]
            label = f"deleting {parent}.{nested} fails Phase 0"
        else:
            container[nested] = None
            label = f"nulling {parent}.{nested} fails Phase 0"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(label, derived["phase0_pass"] is False, derived)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    corrections["corrections"].append(
        {
            "id": "DR-PO-1",
            "status": "UNRESOLVED",
            "alias_of": None,
            "blocked_phase": 1,
            "blocked_gate": "synthetic_unresolved",
            "implementation_allowed": False,
            "release_allowed": False,
        }
    )
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("opening a unique unresolved correction fails Phase 0", derived["phase0_pass"] is False, derived)
    check("opened correction id is present", "DR-PO-1" in derived["blocker_ids"], derived["blocker_ids"])

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["duckdb_tachiom_dirty"] = True
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("dirtying a dependency fails Phase 0", derived["phase0_pass"] is False, derived)
    check("dirty label is present", "duckdb-tachiom dirty" in derived["blocker_ids"], derived["blocker_ids"])

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived, missing_log = _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        live_log=False,
        live_binary=False,
    )
    check("missing NEAREST log/binary is unverified", missing_log["verified"] is False, missing_log)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived, mangled = _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        log_text="not a nearest log",
        live_binary=False,
    )
    check("mangled NEAREST log is unverified", mangled["verified"] is False, mangled)
    check("mangled NEAREST log has failure codes", bool(mangled["failure_codes"]), mangled)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived = _eval_passable_now(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        nearest,
        live_log=False,
        live_binary=False,
    )
    check("unverified NEAREST feeds Phase 0", NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"], derived)
    check("unverified NEAREST class is live_evidence", BLOCKER_CLASS_LIVE_EVIDENCE in derived["blocker_classes"], derived)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    phase0 = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    release = evaluate_release_gate(phase0, default_phase_gates(), default_e3_state())
    toggled = copy.deepcopy(release)
    toggled["phase_gates"]["phase_1"]["state"] = "PASSED"
    toggled["phase_gates"]["phase_1"]["exit_criteria_passed"] = True
    toggled["phase_gates"]["phase_1"]["evidence_level"] = "E2"
    reevaluated = evaluate_release_gate(phase0, toggled["phase_gates"], toggled["e3"])
    check("toggling one phase to PASSED still leaves release false", reevaluated["release_ready"] is False, reevaluated)
    check("remaining phase blockers stay", "phase_2_not_passed" in reevaluated["blocker_ids"], reevaluated["blocker_ids"])
    e3_toggled = copy.deepcopy(_passed_e3())
    e3_toggled["cross_repo_integration_passed"] = False
    still_blocked = evaluate_release_gate(phase0, _passed_phase_gates(), e3_toggled)
    check("incomplete E3 keeps release false", still_blocked["release_ready"] is False, still_blocked)
    check("incomplete E3 blocker id is e3_not_verified", "e3_not_verified" in still_blocked["blocker_ids"], still_blocked)


def test_production_mineru_hashes_remain_required_null(manifest: dict) -> None:
    paths = required_null_hash_paths(manifest)
    nested = "mineru_model_name_version_weights_hash.single_file_weights_sha256"
    check(
        "production digest is omitted from required_null_hash_paths",
        "mineru_container_image_digest" not in paths,
        paths,
    )
    check(
        "production single-file is omitted from required_null_hash_paths",
        nested not in paths,
        paths,
    )
    check("committed digest is still null", manifest.get("mineru_container_image_digest") is None)
    check(
        "committed digest completeness is not_applicable",
        manifest["completeness"].get("mineru_container_image_digest") == NOT_APPLICABLE_STATUS,
    )
    check(
        "committed digest sibling status is not_applicable",
        manifest.get("mineru_container_image_digest_status") == NOT_APPLICABLE_STATUS,
    )
    weights = manifest.get("mineru_model_name_version_weights_hash")
    check("weights mapping exists", isinstance(weights, dict), type(weights).__name__)
    if isinstance(weights, dict):
        check("committed single-file is still null", weights.get("single_file_weights_sha256") is None)
        check(
            "committed single-file status is not_applicable",
            weights.get("single_file_weights_sha256_status") == NOT_APPLICABLE_STATUS,
        )
        check(
            "parent weights completeness is recorded_from_lock",
            manifest["completeness"].get("mineru_model_name_version_weights_hash") == "recorded_from_lock",
        )
    check(
        "digest remains a required hash field",
        "mineru_container_image_digest" in REQUIRED_HASH_FIELDS,
    )
    check(
        "digest remains a digest field",
        "mineru_container_image_digest" in DIGEST_FIELDS,
    )
    check(
        "digest remains a section 3.2 field",
        "mineru_container_image_digest" in SECTION_32_REQUIRED_FIELDS,
    )
    check(
        "PHASE0_PASS_EXEMPT_BACKEND_GATES is exactly live_mineru_runtime",
        PHASE0_PASS_EXEMPT_BACKEND_GATES == frozenset({"live_mineru_runtime"}),
        PHASE0_PASS_EXEMPT_BACKEND_GATES,
    )
    check(
        "canonical mineru contract version stays null",
        manifest.get("canonical_mineru_contract_version") is None,
    )
    check(
        "canonical mineru contract version stays blocked",
        manifest.get("canonical_mineru_contract_version_status") == "blocked",
    )
    check(
        "mineru_profile_id is the Darwin profile, not the contract version",
        manifest.get("mineru_profile_id") == "mineru-3.4.4-pipeline-cpython312-darwin-arm64",
        manifest.get("mineru_profile_id"),
    )


def test_mineru_snapshot_identity_pins(manifest: dict) -> None:
    from v7.mineru import contracts

    contracts_src = (V7_ROOT / "mineru" / "contracts.py").read_text(encoding="utf-8")
    import_lines = [
        line.strip()
        for line in contracts_src.splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]
    check(
        "contracts.py import lines do not mention the evaluator",
        all("phase0_evaluator" not in line and "v7.gates" not in line for line in import_lines),
        import_lines,
    )
    check(
        "PROFILE_ID is not copied into canonical_mineru_contract_version",
        manifest.get("canonical_mineru_contract_version") != contracts.PROFILE_ID,
        manifest.get("canonical_mineru_contract_version"),
    )
    nested = (manifest.get("mineru_model_name_version_weights_hash") or {}).get("snapshot_manifest_sha256")
    top = manifest.get("mineru_model_snapshot_manifest_sha256")
    check(
        "manifest nested snapshot sha equals contracts",
        nested == contracts.MODEL_MANIFEST_SHA256,
        nested,
    )
    check(
        "manifest top-level snapshot sha equals contracts",
        top == contracts.MODEL_MANIFEST_SHA256,
        top,
    )
    profile = _load_json(V7_ROOT / "evidence" / "locks" / "mineru" / "profile.json")
    profile_sha = ((profile.get("pipeline_model") or {}).get("manifest_sha256"))
    check(
        "profile.json pipeline_model.manifest_sha256 equals contracts",
        profile_sha == contracts.MODEL_MANIFEST_SHA256,
        profile_sha,
    )
    p19s = _load_json(V7_ROOT / "evidence" / "duckrag" / "p19-s.json")
    p19s_sha = None
    for row in p19s.get("descriptors") or []:
        if isinstance(row, dict) and isinstance(row.get("model_closure"), dict):
            p19s_sha = row["model_closure"].get("manifest_sha256")
            break
    check(
        "p19-s.json model_closure.manifest_sha256 equals contracts",
        p19s_sha == contracts.MODEL_MANIFEST_SHA256,
        p19s_sha,
    )
    lock = _load_json(V7_ROOT / "evidence" / "locks" / "mineru" / "mineru-3.4.4.lock.json")
    artifacts = lock.get("pypi_artifacts") or []
    wheel_sha = artifacts[0].get("sha256") if artifacts and isinstance(artifacts[0], dict) else None
    check("wheel lock pins MINERU_WHEEL_SHA256", wheel_sha == contracts.MINERU_WHEEL_SHA256, wheel_sha)
    lock_text = json.dumps(lock)
    check(
        "wheel lock does not pin snapshot manifest sha",
        contracts.MODEL_MANIFEST_SHA256 not in lock_text,
        lock_text,
    )
    pdf = V7_ROOT / "tests" / "fixtures" / "range_trio" / "pdf" / "p19-mineru-offline.pdf"
    pdf_bytes = pdf.read_bytes()
    check("PDF size matches contracts", len(pdf_bytes) == contracts.PDF_SIZE_BYTES, len(pdf_bytes))
    check(
        "PDF sha matches contracts",
        hashlib.sha256(pdf_bytes).hexdigest() == contracts.PDF_SHA256,
    )
    p19s_bytes = (V7_ROOT / "evidence" / "duckrag" / "p19-s.json").read_bytes()
    check(
        "copied p19-s.json sha matches contracts",
        hashlib.sha256(p19s_bytes).hexdigest() == contracts.P19S_EVIDENCE_SHA256,
    )


def test_mineru_not_applicable_allowlist() -> None:
    nested_path = "mineru_model_name_version_weights_hash.single_file_weights_sha256"
    check(
        "not_applicable is an allowed completeness token",
        NOT_APPLICABLE_STATUS in phase0_mod.ALLOWED_COMPLETENESS,
    )
    check(
        "allowlist is digest + nested single-file + top-level alias",
        NOT_APPLICABLE_HASH_PATHS
        == frozenset(
            {
                "mineru_container_image_digest",
                nested_path,
                "mineru_model_weights_sha256",
            }
        ),
        NOT_APPLICABLE_HASH_PATHS,
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    null_paths = required_null_hash_paths(manifest)
    check(
        "passable omits digest from required_null_hash_paths",
        "mineru_container_image_digest" not in null_paths,
        null_paths,
    )
    check(
        "passable omits nested single-file from required_null_hash_paths",
        nested_path not in null_paths,
        null_paths,
    )
    live_gate = manifest["backend_gates"]["live_mineru_runtime"]
    live_item = baselines["items"]["live_mineru_runtime"]
    check("passable live mineru gate stays blocked", live_gate.get("blocked") is True, live_gate)
    check("passable live mineru gate stays E1 not_e2", live_gate.get("evidence_level") == "E1" and live_gate.get("not_e2") is True, live_gate)
    check(
        "passable live mineru baseline keeps live_runtime_missing true",
        live_item.get("live_runtime_missing") is True,
        live_item,
    )
    check(
        "passable live mineru kind stays runtime",
        ((live_item.get("evidence_components") or {}).get("live_or_fixture") or {}).get("kind") == "runtime",
        live_item,
    )
    test_recursive_nested_completeness(manifest)
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("synthetic N/A passable still phase0_pass", derived["phase0_pass"] is True, derived)
    check(
        "passable omits live_mineru_runtime pass blocker",
        "live_mineru_runtime" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "passable omits baseline.live_mineru_runtime pass blocker",
        "baseline.live_mineru_runtime" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check("nested N/A path is not a blocker", nested_path not in derived["blocker_ids"], derived["blocker_ids"])
    check(
        "manifest nested N/A path is not a blocker",
        f"manifest.{nested_path}" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "digest N/A path is not a blocker",
        "mineru_container_image_digest" not in derived["blocker_ids"]
        and "manifest.mineru_container_image_digest" not in derived["blocker_ids"],
        derived["blocker_ids"],
    )

    def public_eval(label: str, mutate) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, baselines)
        return _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )

    def fill_na_digest(manifest: dict, _baselines: dict) -> None:
        manifest["mineru_container_image_digest"] = "1" * 64

    filled = public_eval("N/A digest with a hash value", fill_na_digest)
    _assert_public_manifest_blocker(
        "N/A digest with a hash value",
        filled,
        "manifest.mineru_container_image_digest",
        "MANIFEST_STATUS_INVALID",
    )

    def parent_recorded_without_na(manifest: dict, _baselines: dict) -> None:
        obj = manifest["mineru_model_name_version_weights_hash"]
        obj["single_file_weights_sha256"] = None
        obj["single_file_weights_sha256_status"] = "blocked"
        obj["single_file_weights_sha256_notes"] = "missing without not_applicable"
        manifest["completeness"]["mineru_model_name_version_weights_hash"] = "recorded_from_lock"

    recorded_inputs = _passable_gate_inputs()
    parent_recorded_without_na(recorded_inputs[0], recorded_inputs[1])
    check(
        "parent recorded without N/A keeps nested path in required_null_hash_paths",
        nested_path in required_null_hash_paths(recorded_inputs[0]),
        required_null_hash_paths(recorded_inputs[0]),
    )
    recorded = public_eval("parent recorded_from_lock without nested N/A", parent_recorded_without_na)
    _assert_public_fail_closed("parent recorded_from_lock without nested N/A", recorded)
    check(
        "parent recorded without N/A is unavailable or status-invalid",
        nested_path in recorded["blocker_ids"]
        or f"manifest.{nested_path}" in recorded["blocker_ids"]
        or "manifest.mineru_model_name_version_weights_hash" in recorded["blocker_ids"],
        recorded["blocker_ids"],
    )

    def mark_scalar_na(field: str):
        def mutate(manifest: dict, _baselines: dict, name=field) -> None:
            manifest[name] = None
            manifest["completeness"][name] = NOT_APPLICABLE_STATUS
            manifest[f"{name}_status"] = NOT_APPLICABLE_STATUS
            manifest[f"{name}_notes"] = "synthetic not_applicable on a required hash"
            if name == BM25_COMPOSITE_KEY:
                manifest[BM25_CONFIG_HASH_KEY] = None
                manifest[f"{BM25_CONFIG_HASH_KEY}_status"] = NOT_APPLICABLE_STATUS
                manifest[f"{BM25_CONFIG_HASH_KEY}_notes"] = "synthetic not_applicable BM25 alias"
                for key in BM25_SIBLING_KEYS:
                    manifest[key] = None
                    manifest[f"{key}_status"] = "blocked"

        return mutate

    for field in (
        "tachiom_static_loadable_artifact_sha256",
        "mdenseon_model_weights_sha256",
        BM25_COMPOSITE_KEY,
    ):
        na_illegal = public_eval(f"not_applicable on {field}", mark_scalar_na(field))
        _assert_public_manifest_blocker(
            f"not_applicable on {field}",
            na_illegal,
            f"manifest.{field}",
            "MANIFEST_STATUS_INVALID",
        )
        check(
            f"not_applicable on {field} still reports REQUIRED_HASH_UNAVAILABLE",
            field in na_illegal["blocker_ids"],
            na_illegal["blocker_ids"],
        )
        check(
            f"not_applicable on {field} keeps required_null_hashes",
            BLOCKER_CLASS_REQUIRED_NULL_HASHES in na_illegal["blocker_classes"],
            na_illegal["blocker_classes"],
        )

    def e1_e2_overall_e2(_manifest: dict, baselines: dict) -> None:
        item = baselines["items"]["kohaku_tree_fixtures"]
        item["evidence_level"] = "E2"
        item["evidence_components"] = {
            "contract": {"level": "E1", "kind": "types", "id": "kohakurag"},
            "live_or_fixture": {"level": "E2", "kind": "fixtures"},
        }

    mixed = public_eval("E1+E2 components with overall E2", e1_e2_overall_e2)
    _assert_public_manifest_blocker(
        "E1+E2 components with overall E2",
        mixed,
        "manifest.baselines.kohaku_tree_fixtures.evidence_level",
        "MANIFEST_STATUS_INVALID",
    )


def test_nearest_missing_binary_or_log_downgrades() -> None:
    check("missing binary downgrades live nearest to blocked", derive_nearest_gate_level(log_ok=True, binary_ok=False) == "blocked")
    check("missing log downgrades live nearest to blocked", derive_nearest_gate_level(log_ok=False, binary_ok=True) == "blocked")
    check("missing binary and log downgrades live nearest to blocked", derive_nearest_gate_level(log_ok=False, binary_ok=False) == "blocked")
    check("binary+log present keeps live nearest E2", derive_nearest_gate_level(log_ok=True, binary_ok=True) == "E2")
    check("blocked live level is not E2", derive_nearest_gate_level(log_ok=True, binary_ok=False) != "E2")


def test_e3_defined_and_phase0_is_not_e3(register: dict, baselines: dict, manifest: dict) -> None:
    levels = register.get("evidence_levels")
    check("evidence_levels exists", isinstance(levels, dict), type(levels).__name__)
    check("E0 defined", "E0" in (levels or {}))
    check("E1 defined", "E1" in (levels or {}))
    check("E2 defined", "E2" in (levels or {}))
    check("E3 defined in register", "E3" in (levels or {}), levels)
    e3 = str((levels or {}).get("E3") or "")
    check("register E3 mentions four-repo pins", "four-repo pins" in e3, e3)
    check("register E3 says Phase 0 is not E3", "Phase 0 is not E3" in e3, e3)
    plan = PLAN_PATH.read_text(encoding="utf-8")
    check("plan defines E3 as frozen four-repo integration/acceptance", "E3定义为在冻结的四仓pin上完成跨仓库集成/验收" in plan)
    check("plan Phase 7 restates E3 definition", "当前Phase 0不是E3" in plan or "当前 Phase 0 不是 E3" in plan)
    e3_contracts = [row.get("id") for row in register.get("contracts") or [] if row.get("level") == "E3"]
    check("no register contract claims E3 in Phase 0", e3_contracts == [], e3_contracts)
    check("manifest phase is 0, not E3/Phase 7", manifest.get("phase") == 0, manifest.get("phase"))
    check("phase0_pass is false so Phase 0 is not an E3 pass", baselines.get("phase0_pass") is False)
    for item_id, item in (baselines.get("items") or {}).items():
        check(f"baseline {item_id} is not E3", item.get("evidence_level") != "E3", item.get("evidence_level"))


def test_phase0_baselines(baselines: dict) -> None:
    items = baselines.get("items")
    check("baselines.items is an object", isinstance(items, dict), type(items).__name__)
    check("phase0_pass is false", baselines.get("phase0_pass") is False, baselines.get("phase0_pass"))
    available = {"kohaku_tree_fixtures", "kohaku_mineru_range_trio"}
    for item_id in REQUIRED_BASELINE_IDS:
        item = items.get(item_id)
        check(f"baseline {item_id} exists", isinstance(item, dict), item)
        if not isinstance(item, dict):
            continue
        for field in BASELINE_BOOL_FIELDS:
            check(f"{item_id}.{field} is bool", isinstance(item.get(field), bool), item.get(field))
        if item_id in available:
            check(f"{item_id} implementation_allowed is true", item.get("implementation_allowed") is True, item)
            check(f"{item_id} release_allowed is true", item.get("release_allowed") is True, item)
            check(f"{item_id} live_runtime_missing is true", item.get("live_runtime_missing") is True, item)
            check(f"{item_id} acceptance_fixture_missing is false", item.get("acceptance_fixture_missing") is False, item)
            check(f"{item_id} evidence_level is E2", item.get("evidence_level") == "E2", item.get("evidence_level"))
        else:
            check(f"{item_id} implementation_allowed is false", item.get("implementation_allowed") is False, item)
            check(f"{item_id} release_allowed is false", item.get("release_allowed") is False, item)
            check(f"{item_id} live_runtime_missing is true", item.get("live_runtime_missing") is True, item)
            check(f"{item_id} acceptance_fixture_missing is true", item.get("acceptance_fixture_missing") is True, item)
    trio = items.get("kohaku_mineru_range_trio") or {}
    trio_components = trio.get("evidence_components") or {}
    check("trio evidence_components omits contract", "contract" not in trio_components, trio_components)
    check(
        "trio live_or_fixture is fixtures E2",
        (trio_components.get("live_or_fixture") or {}) == {"level": "E2", "kind": "fixtures"},
        trio_components,
    )
    live_item = items.get("live_mineru_runtime") or {}
    live_components = live_item.get("evidence_components") or {}
    check(
        "live_mineru_runtime kind stays runtime",
        (live_components.get("live_or_fixture") or {}).get("kind") == "runtime",
        live_item,
    )
    check(
        "live_mineru_runtime never claims live_runtime_missing false",
        live_item.get("live_runtime_missing") is True,
        live_item,
    )
    check(
        "kohaku golden fixture exists",
        (V7_ROOT / "tests" / "fixtures" / "kohaku" / "golden.v1.json").is_file(),
    )
    hunt = baselines.get("hunt_report") or {}
    present = HUNT_PATH.is_file()
    if present:
        check("hunt report present flag matches disk", hunt.get("present") is True, hunt)
    else:
        check("hunt report absent encoded honestly", hunt.get("present") is False, hunt)
        check("hunt report not used", hunt.get("used") is False, hunt)


def test_infinisynapse_workflow_vs_exact_dto(register: dict) -> None:
    split = _load_json(INFINI_JSON_PATH)
    workflow = split.get("workflow_semantics") or {}
    dto = split.get("exact_tool_dto") or {}
    check("workflow semantics frozen E1", workflow.get("frozen") is True and workflow.get("level") == "E1", workflow)
    check("exact tool DTO is not frozen", dto.get("frozen") is False, dto)
    check("exact tool DTO is not E1", dto.get("level") != "E1" and dto.get("level") == "E0", dto)
    check("exact tool DTO not_a_frozen_e1_tool_shape", dto.get("not_a_frozen_e1_tool_shape") is True, dto)
    check("exact tool DTO implementation_allowed is false", dto.get("implementation_allowed") is False, dto)
    schema_row = _contract_by_id(register, "infinisynapse_schema")
    dto_row = _contract_by_id(register, "infinisynapse_exact_dto")
    check("workflow contract exact_tool_dto_frozen is false", schema_row.get("exact_tool_dto_frozen") is False, schema_row)
    check("workflow contract does not freeze exact DTO as E1", schema_row.get("exact_tool_dto_level") == "E0", schema_row)
    check("exact DTO register row is E0", dto_row.get("level") == "E0", dto_row)
    check("exact DTO backend_blocked", dto_row.get("backend_blocked") is True, dto_row)
    md = (V7_ROOT / "evidence" / "contracts" / "infinisynapse_schema.md").read_text(encoding="utf-8").lower()
    check(
        "infinisynapse md does not call exact DTO frozen E1",
        "exact dto is not frozen e1" in md or "exact tool-shape is not frozen e1" in md,
        "missing exact-DTO-not-frozen-E1 language",
    )


def test_nearest_binary_hash(manifest: dict, register: dict) -> None:
    nearest = _load_json(NEAREST_JSON_PATH)
    for field in NEAREST_EXECUTION_FIELDS:
        check(f"nearest execution field {field} present", field in nearest, sorted(nearest))
    check("historical freeze evidence_level is E2", nearest.get("evidence_level") == "E2", nearest.get("evidence_level"))
    check("nearest exit_code is 0", nearest.get("exit_code") == 0, nearest.get("exit_code"))
    check("nearest assertions is 112", nearest.get("assertions") == 112, nearest.get("assertions"))
    check("nearest sha256 is 64 hex", bool(SHA256_RE.match(str(nearest.get("binary_sha256") or ""))), nearest.get("binary_sha256"))
    check("nearest sha256 is the verified value", nearest.get("binary_sha256") == NEAREST_SHA256, nearest.get("binary_sha256"))
    check("nearest size", nearest.get("binary_size_bytes") == 11567456, nearest.get("binary_size_bytes"))
    check(
        "nearest build identity commit",
        nearest.get("build_identity_commit") == DUCKDB_PGAGENT_COMMIT,
        nearest.get("build_identity_commit"),
    )
    check(
        "nearest build identity tag",
        nearest.get("build_identity_tag") == "duckdb-special-20260829-g1",
        nearest.get("build_identity_tag"),
    )
    check(
        "nearest command ran nearest_basic.test",
        "nearest_basic.test" in str(nearest.get("command") or ""),
        nearest.get("command"),
    )
    log_rel = nearest.get("log")
    check("nearest log field is in-repo evidence path", log_rel == "v7/evidence/nearest_basic.e2.log", log_rel)
    check("nearest raw log exists", NEAREST_LOG_PATH.is_file(), str(NEAREST_LOG_PATH))
    log_text = NEAREST_LOG_PATH.read_text(encoding="utf-8") if NEAREST_LOG_PATH.is_file() else ""
    check("nearest raw log has content", bool(log_text.strip()), len(log_text))
    check("nearest log records exit code 0", "exit code: 0" in log_text, log_text[:400])
    check("nearest log records 112 assertions", "112 assertions" in log_text, log_text[-400:])
    check("nearest log ran nearest_basic.test", "nearest_basic.test" in log_text)
    check("nearest log records build commit", DUCKDB_PGAGENT_COMMIT in log_text)
    verification = nearest.get("verification") or {}
    check("nearest verification object exists", isinstance(verification, dict) and verification, verification)
    check(
        "missing binary/log downgrades live nearest to blocked",
        verification.get("absent_binary_or_log_gate_level") == "blocked",
        verification,
    )
    check("live E2 requires binary", verification.get("binary_required_for_live_e2") is True, verification)
    check("live E2 requires log", verification.get("log_required_for_live_e2") is True, verification)
    unittest_bin, bin_source = _resolve_optional_file(
        UNITTEST_BIN_ENV_VARS,
        _unittest_bin_candidates(nearest, manifest),
        allow_absolute=False,
    )
    if unittest_bin is None:
        configured = _resolve_configured_live_binary(REPO_ROOT)
        if configured is not None:
            unittest_bin, bin_source = configured, "recorded"
    binary_ok = unittest_bin is not None and unittest_bin.is_file()
    log_ok = NEAREST_LOG_PATH.is_file() and bool(log_text.strip())
    live_level = derive_nearest_gate_level(log_ok=log_ok, binary_ok=binary_ok)
    recorded_bin = Path(str(nearest.get("binary_path") or "")).expanduser()
    if recorded_bin.is_file():
        recorded_digest = hashlib.sha256(recorded_bin.read_bytes()).hexdigest()
        check(
            "recorded-path metadata sha256 matches evidence",
            recorded_digest == NEAREST_SHA256,
            recorded_digest,
        )
        check(
            "recorded-path metadata size matches evidence",
            recorded_bin.stat().st_size == 11567456,
            recorded_bin.stat().st_size,
        )
    if binary_ok:
        assert unittest_bin is not None
        digest = hashlib.sha256(unittest_bin.read_bytes()).hexdigest()
        check("on-disk unittest sha256 matches evidence", digest == NEAREST_SHA256, (digest, bin_source))
        check(
            "on-disk unittest size matches evidence",
            unittest_bin.stat().st_size == 11567456,
            (unittest_bin.stat().st_size, bin_source),
        )
        check("verified nearest live gate is E2", live_level == "E2", (live_level, bin_source))
        check("live E2 source is env or repo-relative recorded", bin_source.startswith("env:") or bin_source == "recorded", bin_source)
    else:
        check("unverified nearest live gate is blocked, not E2", live_level == "blocked", (live_level, bin_source))
        check(
            "missing unittest binary is a blocked assertion, not a path-layout failure",
            bin_source in {"absent", "recorded"} or str(bin_source).endswith(":missing"),
            bin_source,
        )
    manifest_nearest = manifest.get("nearest_e2") or {}
    check(
        "manifest nearest sha256 matches evidence",
        manifest_nearest.get("binary_sha256") == NEAREST_SHA256,
        manifest_nearest.get("binary_sha256"),
    )
    check(
        "manifest nearest build identity",
        manifest_nearest.get("build_identity_commit") == DUCKDB_PGAGENT_COMMIT,
        manifest_nearest.get("build_identity_commit"),
    )
    check("manifest nearest historical evidence_level is E2", manifest_nearest.get("evidence_level") == "E2")
    check("manifest nearest exit_code is 0", manifest_nearest.get("exit_code") == 0, manifest_nearest.get("exit_code"))
    manifest_ver = manifest_nearest.get("verification") or {}
    check(
        "manifest nearest missing binary/log downgrades to blocked",
        manifest_ver.get("absent_binary_or_log_gate_level") == "blocked",
        manifest_ver,
    )
    if live_level != "E2":
        check("gate does not report live E2 without binary+log", live_level == "blocked", live_level)
    summary = NEAREST_SUMMARY_PATH.read_text(encoding="utf-8")
    check("nearest summary records sha256", NEAREST_SHA256 in summary)
    check("nearest summary records build commit", DUCKDB_PGAGENT_COMMIT in summary)
    check("nearest summary records blocked downgrade rule", "downgrades the live gate to blocked" in summary)
    row = _contract_by_id(register, "nearest_basic")
    check("register nearest sha256", (row.get("binary") or {}).get("sha256") == NEAREST_SHA256, row.get("binary"))
    check("register nearest historical level is E2", row.get("level") == "E2", row.get("level"))
    check("register nearest unverified gate level is blocked", row.get("unverified_gate_level") == "blocked", row)
    check("register nearest unverified blocker id", row.get("unverified_blocker_id") == NEAREST_TARGET_E2_UNVERIFIED, row)
    check("register nearest requires binary and log", row.get("live_e2_requires_binary_and_log") is True, row)
    if live_level != "E2":
        check("register does not treat unverified nearest as live E2", row.get("unverified_gate_level") != "E2")


def test_evaluator_owns_provenance_and_pins() -> None:
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance_missing = _eval_passable_now(manifest, baselines, corrections, None, register, historical, nearest)
    check("missing provenance fails Phase 0", provenance_missing["phase0_pass"] is False, provenance_missing)
    check(
        "missing provenance is manifest_contract",
        BLOCKER_CLASS_MANIFEST in provenance_missing["blocker_classes"],
        provenance_missing["blocker_classes"],
    )
    for repo_name, _key in FOUR_REPO_COMMIT_KEYS:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        del provenance["repos"][repo_name]
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"deleting provenance {repo_name} fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"deleting provenance {repo_name} is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        provenance["repos"][repo_name]["commit"] = "c" * 40
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"mismatched provenance commit for {repo_name} fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["pg_agent_dirty"] = "false"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("string dirty is not a clean state", derived["phase0_pass"] is False, derived)
    check("string dirty is manifest_contract", BLOCKER_CLASS_MANIFEST in derived["blocker_classes"], derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    del provenance["repos"]["flock"]["submodules"]["duckdb"]
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("missing flock.duckdb submodule fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["tachiom_commit"] = "e" * 40
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("wrong tachiom resolved commit fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["duckdb_python_pgagent_vendored_engine_equals_target"] = False
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("false vendored equality flag fails Phase 0", derived["phase0_pass"] is False, derived)


def test_evaluator_provenance_relationships() -> None:
    for name in ("tachiom", "duckdb-tachiom"):
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        del provenance["external_not_four_repo"][name]
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"missing external {name} fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"missing external {name} is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        provenance["external_not_four_repo"][name] = "not-a-mapping"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"malformed external {name} row fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"malformed external {name} row is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        del provenance["external_not_four_repo"][name]["commit"]
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"missing external {name} commit fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"missing external {name} commit is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        provenance["external_not_four_repo"][name]["commit"] = "not-a-commit"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"malformed external {name} commit fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"malformed external {name} commit is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        provenance["external_not_four_repo"][name]["commit"] = "c" * 40
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"mismatched external {name} commit fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"mismatched external {name} commit is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        provenance["external_not_four_repo"][name]["dirty"] = "false"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"non-boolean external {name} dirty fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"non-boolean external {name} dirty is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["external_not_four_repo"]["tachiom"]["commit"] = TACHIOM_TAG_COMMIT
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("external tachiom cargo pin instead of checkout fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "external tachiom cargo pin is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["duckdb-pgagent"]["tag"] = "wrong-tag"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("mismatched duckdb-pgagent provenance tag fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "mismatched duckdb-pgagent provenance tag is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["duckdb-python-pgagent"]["tag"] = "wrong-python-tag"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("mismatched duckdb-python-pgagent provenance tag fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "mismatched duckdb-python-pgagent provenance tag is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["duckdb-python-pgagent"]["vendored_engine"]["matches_duckdb_pgagent"] = False
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("false vendored matches_duckdb_pgagent fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "false vendored matches_duckdb_pgagent is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    del provenance["repos"]["duckdb-python-pgagent"]["vendored_engine"]["matches_duckdb_pgagent"]
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("missing vendored matches_duckdb_pgagent fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "missing vendored matches_duckdb_pgagent is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["flock"]["submodules"]["duckdb"] = {
        "recorded_gitlink": "1" * 40,
        "initialized": True,
        "status": "ok",
    }
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("fake initialized flock.duckdb gitlink fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "fake initialized flock.duckdb gitlink is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )
    check(
        "fake initialized flock.duckdb gitlink is not only dirty_uninitialized",
        BLOCKER_CLASS_DIRTY_UNINITIALIZED not in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["flock"]["submodules"]["extension-ci-tools"] = {
        "recorded_gitlink": "2" * 40,
        "initialized": True,
        "status": "ok",
    }
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("fake initialized extension-ci-tools gitlink fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "fake initialized extension-ci-tools gitlink is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )
    check(
        "fake initialized extension-ci-tools gitlink is not only dirty_uninitialized",
        BLOCKER_CLASS_DIRTY_UNINITIALIZED not in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    provenance["repos"]["flock"]["submodules"]["extension-ci-tools"] = {
        "recorded_gitlink": "2" * 40,
        "initialized": False,
        "status": "blocked",
    }
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("blocked mismatched extension-ci-tools gitlink fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "blocked mismatched extension-ci-tools is dirty_uninitialized_dependencies",
        BLOCKER_CLASS_DIRTY_UNINITIALIZED in derived["blocker_classes"],
        derived["blocker_classes"],
    )
    check(
        "blocked mismatched extension-ci-tools gitlink is not extra manifest_contract",
        BLOCKER_CLASS_MANIFEST not in derived["blocker_classes"],
        derived["blocker_classes"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["tachiom_checkout_commit"] = TACHIOM_TAG_COMMIT
    provenance["external_not_four_repo"]["tachiom"]["commit"] = TACHIOM_TAG_COMMIT
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("tachiom checkout equal to cargo pin fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "tachiom checkout equal to cargo pin is manifest_contract",
        BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
        derived["blocker_classes"],
    )


def test_evaluator_remaining_identity_relationships() -> None:
    def assert_public_manifest_block(label: str, mutate) -> None:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, provenance)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        check(f"{label} fails public evaluate_phase0", derived["phase0_pass"] is False, derived)
        check(
            f"{label} is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived = _eval_public_phase0(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("public evaluate_phase0 accepts honest passable snapshot", derived["phase0_pass"] is True, derived)

    def drop_cargo_tag_pin(manifest: dict, _provenance: dict) -> None:
        del manifest["duckdb_tachiom_cargo_tachiom_git_tag_pin"]

    assert_public_manifest_block("missing cargo tachiom git tag pin", drop_cargo_tag_pin)

    def mutate_cargo_tag_pin(manifest: dict, _provenance: dict) -> None:
        manifest["duckdb_tachiom_cargo_tachiom_git_tag_pin"] = "v0.3.4-forged"

    assert_public_manifest_block("mutated cargo tachiom git tag pin", mutate_cargo_tag_pin)

    def drop_tachiom_tag(manifest: dict, provenance: dict) -> None:
        del provenance["external_not_four_repo"]["tachiom"]["tag"]

    assert_public_manifest_block("missing external tachiom tag", drop_tachiom_tag)

    def drop_tachiom_tag_status(manifest: dict, provenance: dict) -> None:
        del provenance["external_not_four_repo"]["tachiom"]["tag_status"]

    assert_public_manifest_block("missing external tachiom tag_status", drop_tachiom_tag_status)

    def forge_tachiom_tag(manifest: dict, provenance: dict) -> None:
        provenance["external_not_four_repo"]["tachiom"]["tag"] = "v-forged"
        provenance["external_not_four_repo"]["tachiom"]["tag_status"] = "recorded"

    assert_public_manifest_block("contradictory external tachiom tag", forge_tachiom_tag)

    def mismatch_tachiom_describe(manifest: dict, provenance: dict) -> None:
        provenance["external_not_four_repo"]["tachiom"]["describe"] = "forged-describe"

    assert_public_manifest_block("contradictory tachiom checkout describe", mismatch_tachiom_describe)

    def drop_tachiom_describe(manifest: dict, provenance: dict) -> None:
        del provenance["external_not_four_repo"]["tachiom"]["describe"]

    assert_public_manifest_block("missing tachiom checkout describe", drop_tachiom_describe)

    def drop_manifest_tachiom_checkout_tag(manifest: dict, _provenance: dict) -> None:
        del manifest["tachiom_checkout_tag"]

    assert_public_manifest_block("missing tachiom_checkout_tag", drop_manifest_tachiom_checkout_tag)

    def drop_duckdb_tachiom_tag(manifest: dict, provenance: dict) -> None:
        del provenance["external_not_four_repo"]["duckdb-tachiom"]["tag"]

    assert_public_manifest_block("missing external duckdb-tachiom tag", drop_duckdb_tachiom_tag)

    def drop_duckdb_tachiom_tag_status(manifest: dict, provenance: dict) -> None:
        del provenance["external_not_four_repo"]["duckdb-tachiom"]["tag_status"]

    assert_public_manifest_block("missing external duckdb-tachiom tag_status", drop_duckdb_tachiom_tag_status)

    def forge_duckdb_tachiom_tag(manifest: dict, provenance: dict) -> None:
        provenance["external_not_four_repo"]["duckdb-tachiom"]["tag"] = "v-forged"
        provenance["external_not_four_repo"]["duckdb-tachiom"]["tag_status"] = "recorded"

    assert_public_manifest_block("contradictory external duckdb-tachiom tag", forge_duckdb_tachiom_tag)

    def drop_manifest_duckdb_tachiom_tag(manifest: dict, _provenance: dict) -> None:
        del manifest["duckdb_tachiom_tag"]

    assert_public_manifest_block("missing duckdb_tachiom_tag", drop_manifest_duckdb_tachiom_tag)

    def unknown_ok_status(manifest: dict, provenance: dict) -> None:
        provenance["repos"]["flock"]["submodules"]["duckdb"]["status"] = "unknown"

    assert_public_manifest_block("initialized true with unknown flock status", unknown_ok_status)

    def blocked_while_initialized(manifest: dict, provenance: dict) -> None:
        provenance["repos"]["flock"]["submodules"]["duckdb"]["status"] = "blocked"

    assert_public_manifest_block("initialized true with blocked flock status", blocked_while_initialized)

    def ok_while_uninitialized(manifest: dict, provenance: dict) -> None:
        provenance["repos"]["flock"]["submodules"]["duckdb"]["initialized"] = False

    assert_public_manifest_block("initialized false with ok flock status", ok_while_uninitialized)

    def unknown_uninitialized_status(manifest: dict, provenance: dict) -> None:
        provenance["repos"]["flock"]["submodules"]["extension-ci-tools"]["initialized"] = False
        provenance["repos"]["flock"]["submodules"]["extension-ci-tools"]["status"] = "unknown"

    assert_public_manifest_block("unknown flock status", unknown_uninitialized_status)

    def disagree_four_repo_dirty(manifest: dict, provenance: dict) -> None:
        manifest["flock_dirty"] = True

    assert_public_manifest_block("four-repo dirty disagreement", disagree_four_repo_dirty)

    def disagree_tachiom_checkout_dirty(manifest: dict, provenance: dict) -> None:
        manifest["tachiom_checkout_dirty"] = True

    assert_public_manifest_block("tachiom checkout dirty disagreement", disagree_tachiom_checkout_dirty)

    def disagree_duckdb_tachiom_dirty(manifest: dict, provenance: dict) -> None:
        provenance["external_not_four_repo"]["duckdb-tachiom"]["dirty"] = True

    assert_public_manifest_block("duckdb-tachiom dirty disagreement", disagree_duckdb_tachiom_dirty)


def test_evaluator_schema_cross_field_and_register_mutations() -> None:
    def assert_public_block(label: str, mutate) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, baselines, register)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        check(f"{label} fails public evaluate_phase0", derived["phase0_pass"] is False, derived)
        check(
            f"{label} is manifest_contract",
            BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        return derived

    def delete_nested_dimension(manifest: dict, _baselines: dict, _register: dict) -> None:
        del manifest["embedding_dimension_dtype_normalization_batch"]["dimension"]

    assert_public_block("deleting required nested embedding dimension", delete_nested_dimension)

    def delete_nested_model_id(manifest: dict, _baselines: dict, _register: dict) -> None:
        del manifest["mdenseon_package_native_runtime_version"]["model_id"]

    assert_public_block("deleting required nested mdenseon model_id", delete_nested_model_id)

    def engine_version_mapping(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["duckdb_engine_version"] = {"version": "v1.6.0-dev"}

    assert_public_block("mapping substituting for engine version scalar", engine_version_mapping)

    def weights_hash_mapping(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mdenseon_model_weights_sha256"] = {"sha256": "3" * 64}

    assert_public_block("mapping substituting for mdenseon weights hash", weights_hash_mapping)

    def digest_list(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mineru_container_image_digest"] = ["1" * 64]

    assert_public_block("list substituting for mineru image digest", digest_list)

    def invalid_digest(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mineru_container_image_digest"] = "sha256:not-a-digest"

    assert_public_block("invalid mineru image digest format", invalid_digest)

    def invalid_hash(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mdenseon_model_weights_sha256"] = "not-a-sha256"

    assert_public_block("invalid mdenseon weights hash format", invalid_hash)

    def unknown_wheel_status(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["build_flags"]["v7_python_wheel"]["status"] = "invented"

    assert_public_block("unknown v7 wheel status", unknown_wheel_status)

    def fts_not_commit(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["fts_extension_version"] = "not-a-commit"

    assert_public_block("fts extension version not a commit", fts_not_commit)

    def mismatch_dimension(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["embedding_dimension"] = 1024

    assert_public_block("mismatched duplicate embedding dimension", mismatch_dimension)

    def mismatch_dtype(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["embedding_dtype"] = "float16"

    assert_public_block("mismatched duplicate embedding dtype", mismatch_dtype)

    def mismatch_revision(manifest: dict, _baselines: dict, register: dict) -> None:
        manifest["tokenizer_identity_version_hash"]["version"] = "0" * 40
        manifest["tokenizer_version"] = "0" * 40
        for row in register["contracts"]:
            if row.get("id") == "mdenseon":
                row["frozen_without_live_files"]["revision"] = "0" * 40

    assert_public_block("mismatched tokenizer revision vs mdenseon runtime", mismatch_revision)

    def mismatch_tokenizer_hash(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["tokenizer_hash"] = "a" * 64

    assert_public_block("mismatched duplicate tokenizer hash", mismatch_tokenizer_hash)

    def mismatch_mineru_name(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mineru_model_name"] = "forged/model"

    assert_public_block("mismatched mineru model name vs nested object", mismatch_mineru_name)

    def mismatch_bm25_hash(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["bm25_config_hash"] = "0" * 64

    assert_public_block("mismatched bm25 config hash vs composite", mismatch_bm25_hash)

    def change_register_path(manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "mineru":
                row["path"] = "v7/evidence/contracts/forged.md"

    assert_public_block("changed register path", change_register_path)

    def change_register_backend(manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "temp_candidate_stage":
                row["related_backend"] = "forged_backend"
                row["blockers"] = []

    assert_public_block("changed register related_backend", change_register_backend)

    def change_tachiom_checkout(manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "tachiom":
                row["git"]["tachiom"]["checkout_commit"] = "c" * 40

    assert_public_block("changed register tachiom checkout commit", change_tachiom_checkout)

    def change_tachiom_target_tag(manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "tachiom":
                row["git"]["duckdb-pgagent_target"]["tag"] = "forged-tag"

    assert_public_block("changed register tachiom target tag", change_tachiom_target_tag)

    def duplicate_register_ids(manifest: dict, _baselines: dict, register: dict) -> None:
        register["contracts"].append(dict(register["contracts"][0]))

    assert_public_block("duplicate register contract ids", duplicate_register_ids)

    def unknown_baseline_level(manifest: dict, baselines: dict, _register: dict) -> None:
        baselines["items"]["live_mdenseon"]["evidence_level"] = "E4"

    assert_public_block("unknown baseline evidence_level", unknown_baseline_level)

    def contradictory_register_baseline(manifest: dict, baselines: dict, register: dict) -> None:
        baselines["items"]["live_mdenseon"]["live_runtime_missing"] = True
        baselines["items"]["live_mdenseon"]["acceptance_fixture_missing"] = True
        baselines["items"]["live_mdenseon"]["implementation_allowed"] = False
        baselines["items"]["live_mdenseon"]["release_allowed"] = False
        manifest["backend_gates"]["dense_mdenseon"] = {
            "blocked": True,
            "not_e2": True,
            "evidence_level": "E1",
            "reason": "synthetic live missing",
        }
        for row in register["contracts"]:
            if row.get("id") == "mdenseon":
                row["backend_blocked"] = False
                row["backend_blocked_reason"] = None
                row["blockers"] = []

    derived = assert_public_block(
        "contradictory unblocked register vs live-missing baseline",
        contradictory_register_baseline,
    )
    check(
        "contradictory register/baseline is not a silent pass",
        derived["phase0_pass"] is False,
        derived,
    )


def test_rl5_p1_2_ce289b_mutations() -> None:
    def public_eval(label: str, mutate) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, baselines, register)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        check(f"{label} fails public evaluate_phase0", derived["phase0_pass"] is False, derived)
        return derived

    def available_e0(_manifest: dict, baselines: dict, _register: dict) -> None:
        for item in baselines["items"].values():
            item["evidence_level"] = "E0"

    e0 = public_eval("available E0 false-pass", available_e0)
    check("available E0 is missing_baselines", BLOCKER_CLASS_MISSING_BASELINES in e0["blocker_classes"], e0)

    def available_e1(_manifest: dict, baselines: dict, _register: dict) -> None:
        for item in baselines["items"].values():
            item["evidence_level"] = "E1"

    e1 = public_eval("available E1 false-pass", available_e1)
    check("available E1 is missing_baselines", BLOCKER_CLASS_MISSING_BASELINES in e1["blocker_classes"], e1)

    def completeness_null(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["completeness"]["duckdb_engine_version"] = None

    completeness = public_eval("completeness token null", completeness_null)
    check("completeness null is manifest_contract", BLOCKER_CLASS_MANIFEST in completeness["blocker_classes"], completeness)

    def parser_backend(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mineru_parser_config"]["backend"] = "vlm"

    parser = public_eval("mineru parser backend not frozen", parser_backend)
    check("parser backend is manifest_contract", BLOCKER_CLASS_MANIFEST in parser["blocker_classes"], parser)

    def nested_weights(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["mineru_model_name_version_weights_hash"]["name"] = "forged/nested"

    weights = public_eval("nested mineru weights diverge from top-level", nested_weights)
    check("nested mineru weights is manifest_contract", BLOCKER_CLASS_MANIFEST in weights["blocker_classes"], weights)

    def missing_phase(manifest: dict, _baselines: dict, _register: dict) -> None:
        del manifest["phase"]

    public_eval("missing manifest phase", missing_phase)

    def wrong_phase(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["phase"] = 1

    public_eval("wrong manifest phase", wrong_phase)

    def missing_kind(manifest: dict, _baselines: dict, _register: dict) -> None:
        del manifest["manifest_kind"]

    public_eval("missing manifest_kind", missing_kind)

    def wrong_kind(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["manifest_kind"] = "forged_kind"

    public_eval("wrong manifest_kind", wrong_kind)

    def missing_schema(_manifest: dict, baselines: dict, _register: dict) -> None:
        del baselines["schema_version"]

    public_eval("missing baseline schema_version", missing_schema)

    def wrong_schema(_manifest: dict, baselines: dict, _register: dict) -> None:
        baselines["schema_version"] = "forged-schema/0"

    public_eval("wrong baseline schema_version", wrong_schema)

    def missing_evaluator(_manifest: dict, baselines: dict, _register: dict) -> None:
        del baselines["evaluator"]

    public_eval("missing baseline evaluator", missing_evaluator)

    def wrong_evaluator(_manifest: dict, baselines: dict, _register: dict) -> None:
        baselines["evaluator"] = "forged.evaluator"

    public_eval("wrong baseline evaluator", wrong_evaluator)

    def blocked_register_unblocked_gate(_manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "mdenseon":
                row["backend_blocked"] = True
                row["backend_blocked_reason"] = "forged blocked"
                row["blockers"] = [
                    {
                        "id": "mdenseon_blocker",
                        "level": "E0",
                        "blocks_backend": row["related_backend"],
                        "detail": "forged blocked",
                    }
                ]

    blocked = public_eval("blocked register with unblocked same backend", blocked_register_unblocked_gate)
    check(
        "blocked register vs unblocked backend is manifest_contract",
        BLOCKER_CLASS_MANIFEST in blocked["blocker_classes"],
        blocked,
    )

    def inconsistent_components(_manifest: dict, baselines: dict, _register: dict) -> None:
        baselines["items"]["kohaku_tree_fixtures"]["evidence_components"] = {
            "contract": {"level": "E1", "kind": "types", "id": "kohakurag"},
            "live_or_fixture": {"level": "E0", "kind": "fixtures"},
        }

    components = public_eval("E2 overall with E0 component", inconsistent_components)
    check(
        "inconsistent evidence_components is manifest_contract",
        BLOCKER_CLASS_MANIFEST in components["blocker_classes"],
        components,
    )


def test_rl5_p1_2_4f1ae1_mutations() -> None:
    def public_eval(label: str, mutate) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, baselines, register)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        check(f"{label} fails public evaluate_phase0", derived["phase0_pass"] is False, derived)
        return derived

    def _block_gate(manifest: dict, gate: str, level: str = "E0") -> None:
        manifest["backend_gates"][gate] = {
            "blocked": True,
            "not_e2": True,
            "evidence_level": level,
            "reason": "synthetic unavailable relation",
        }

    def frozen_false(_manifest: dict, baselines: dict, _register: dict) -> None:
        item = baselines["items"]["live_legacy_cache"]
        item["contract_frozen"] = False
        item["implementation_allowed"] = False
        item["release_allowed"] = False
        _block_gate(_manifest, "legacy_cache_live")

    frozen = public_eval("contract_frozen false with coherent blocked gate", frozen_false)
    check(
        "unfrozen baseline is missing_baselines",
        BLOCKER_CLASS_MISSING_BASELINES in frozen["blocker_classes"],
        frozen,
    )

    def e0_missing_false(manifest: dict, baselines: dict, _register: dict) -> None:
        baselines["items"]["live_legacy_cache"]["evidence_level"] = "E0"
        _block_gate(manifest, "legacy_cache_live")

    e0 = public_eval("E0 with missing flags false and blocked gate", e0_missing_false)
    check("E0 available-looking baseline is missing_baselines", BLOCKER_CLASS_MISSING_BASELINES in e0["blocker_classes"], e0)

    def e1_missing_false(manifest: dict, baselines: dict, _register: dict) -> None:
        baselines["items"]["live_legacy_cache"]["evidence_level"] = "E1"
        _block_gate(manifest, "legacy_cache_live", "E1")

    e1 = public_eval("E1 with missing flags false and blocked gate", e1_missing_false)
    check("E1 available-looking baseline is missing_baselines", BLOCKER_CLASS_MISSING_BASELINES in e1["blocker_classes"], e1)

    def disallowed_allowed_flags(manifest: dict, baselines: dict, _register: dict) -> None:
        item = baselines["items"]["live_legacy_cache"]
        item["live_runtime_missing"] = True
        item["acceptance_fixture_missing"] = True
        _block_gate(manifest, "legacy_cache_live")

    disallowed = public_eval("implementation_allowed while live/fixture missing", disallowed_allowed_flags)
    check(
        "allowed-while-blocked flags are manifest_contract",
        BLOCKER_CLASS_MANIFEST in disallowed["blocker_classes"],
        disallowed,
    )

    def available_with_blocked_gate(manifest: dict, _baselines: dict, _register: dict) -> None:
        _block_gate(manifest, "legacy_cache_live")

    blocked_gate = public_eval("available baseline with blocked gate", available_with_blocked_gate)
    check(
        "blocked gate vs available baseline is manifest_contract",
        BLOCKER_CLASS_MANIFEST in blocked_gate["blocker_classes"],
        blocked_gate,
    )

    def unavailable_with_unblocked_gate(_manifest: dict, baselines: dict, _register: dict) -> None:
        item = baselines["items"]["live_legacy_cache"]
        item["evidence_level"] = "E0"
        item["live_runtime_missing"] = True
        item["acceptance_fixture_missing"] = True
        item["implementation_allowed"] = False
        item["release_allowed"] = False

    unblocked_gate = public_eval("unavailable baseline with unblocked gate", unavailable_with_unblocked_gate)
    check(
        "unblocked gate vs unavailable baseline is manifest_contract",
        BLOCKER_CLASS_MANIFEST in unblocked_gate["blocker_classes"],
        unblocked_gate,
    )

    def phase_false(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["phase"] = False

    phase_f = public_eval("manifest.phase False", phase_false)
    check("phase False is manifest_contract", BLOCKER_CLASS_MANIFEST in phase_f["blocker_classes"], phase_f)
    check("phase False records manifest.phase", "manifest.phase" in phase_f["blocker_ids"], phase_f["blocker_ids"])

    def phase_true(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["phase"] = True

    phase_t = public_eval("manifest.phase True", phase_true)
    check("phase True records manifest.phase", "manifest.phase" in phase_t["blocker_ids"], phase_t["blocker_ids"])

    def phase_float(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest["phase"] = 0.0

    phase_z = public_eval("manifest.phase 0.0", phase_float)
    check("phase 0.0 records manifest.phase", "manifest.phase" in phase_z["blocker_ids"], phase_z["blocker_ids"])

    def unblock_exact_dto(_manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "infinisynapse_exact_dto":
                row["backend_blocked"] = False
                row["backend_blocked_reason"] = None
                row["blockers"] = []

    exact = public_eval("expected-blocked infinisynapse_exact_dto unblocked", unblock_exact_dto)
    check(
        "unblocked infinisynapse_exact_dto is manifest_contract",
        BLOCKER_CLASS_MANIFEST in exact["blocker_classes"],
        exact,
    )
    check(
        "unblocked infinisynapse_exact_dto records backend_blocked",
        "manifest.evidence_register.infinisynapse_exact_dto.backend_blocked" in exact["blocker_ids"],
        exact["blocker_ids"],
    )

    def block_unblocked_contract(_manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "mineru":
                row["backend_blocked"] = True
                row["backend_blocked_reason"] = "forged blocked"
                row["blockers"] = [
                    {
                        "id": "mineru_blocker",
                        "level": "E0",
                        "blocks_backend": row["related_backend"],
                        "detail": "forged blocked",
                    }
                ]

    mineru = public_eval("expected-unblocked mineru blocked", block_unblocked_contract)
    check(
        "blocked mineru is manifest_contract",
        BLOCKER_CLASS_MANIFEST in mineru["blocker_classes"],
        mineru,
    )
    check(
        "blocked mineru records backend_blocked",
        "manifest.evidence_register.mineru.backend_blocked" in mineru["blocker_ids"],
        mineru["blocker_ids"],
    )

    def block_available_identical(_manifest: dict, _baselines: dict, register: dict) -> None:
        for row in register["contracts"]:
            if row.get("id") == "mdenseon":
                row["backend_blocked"] = True
                row["backend_blocked_reason"] = "forged blocked"
                row["blockers"] = [
                    {
                        "id": "mdenseon_blocker",
                        "level": "E0",
                        "blocks_backend": row["related_backend"],
                        "detail": "forged blocked",
                    }
                ]

    identical_block = public_eval("available identical-concern register blocked", block_available_identical)
    check(
        "blocked mdenseon vs available baseline is manifest_contract",
        BLOCKER_CLASS_MANIFEST in identical_block["blocker_classes"],
        identical_block,
    )

    def unblock_unavailable_identical(manifest: dict, baselines: dict, register: dict) -> None:
        item = baselines["items"]["live_mdenseon"]
        item["evidence_level"] = "E0"
        item["live_runtime_missing"] = True
        item["acceptance_fixture_missing"] = True
        item["implementation_allowed"] = False
        item["release_allowed"] = False
        item["evidence_components"] = {
            "contract": {"level": "E0", "kind": "lock", "id": "mdenseon"},
            "live_or_fixture": {"level": "E0", "kind": "bytes"},
        }
        _block_gate(manifest, "dense_mdenseon")
        for row in register["contracts"]:
            if row.get("id") == "mdenseon":
                row["backend_blocked"] = False
                row["backend_blocked_reason"] = None
                row["blockers"] = []

    identical_unblock = public_eval("unavailable identical-concern register unblocked", unblock_unavailable_identical)
    check(
        "unblocked mdenseon vs unavailable baseline is manifest_contract",
        BLOCKER_CLASS_MANIFEST in identical_unblock["blocker_classes"],
        identical_unblock,
    )

    hash_field = "tachiom_static_loadable_artifact_sha256"

    def honest_null_hash(manifest: dict, _baselines: dict, _register: dict) -> None:
        manifest[hash_field] = None
        manifest["completeness"][hash_field] = "blocked"
        manifest[f"{hash_field}_status"] = "blocked"
        manifest[f"{hash_field}_notes"] = "synthetic missing hash"

    honest_null = public_eval("honest required null hash still unavailable", honest_null_hash)
    check(
        "honest null hash is required_null_hashes",
        BLOCKER_CLASS_REQUIRED_NULL_HASHES in honest_null["blocker_classes"],
        honest_null,
    )

    def delete_hash_status(manifest: dict, _baselines: dict, _register: dict) -> None:
        honest_null_hash(manifest, _baselines, _register)
        del manifest[f"{hash_field}_status"]

    deleted_status = public_eval("required null hash missing sibling status", delete_hash_status)
    check(
        "deleted hash status is manifest_contract",
        BLOCKER_CLASS_MANIFEST in deleted_status["blocker_classes"],
        deleted_status,
    )

    def empty_hash_notes(manifest: dict, _baselines: dict, _register: dict) -> None:
        honest_null_hash(manifest, _baselines, _register)
        manifest[f"{hash_field}_notes"] = ""

    empty_notes = public_eval("required null hash empty sibling notes", empty_hash_notes)
    check(
        "empty hash notes is manifest_contract",
        BLOCKER_CLASS_MANIFEST in empty_notes["blocker_classes"],
        empty_notes,
    )

    def recorded_completeness_null_hash(manifest: dict, _baselines: dict, _register: dict) -> None:
        honest_null_hash(manifest, _baselines, _register)
        manifest["completeness"][hash_field] = "recorded"

    recorded_complete = public_eval("required null hash with recorded completeness", recorded_completeness_null_hash)
    check(
        "recorded completeness on null hash is manifest_contract",
        BLOCKER_CLASS_MANIFEST in recorded_complete["blocker_classes"],
        recorded_complete,
    )

    def recorded_status_null_hash(manifest: dict, _baselines: dict, _register: dict) -> None:
        honest_null_hash(manifest, _baselines, _register)
        manifest[f"{hash_field}_status"] = "recorded"

    recorded_status = public_eval("required null hash with recorded status", recorded_status_null_hash)
    check(
        "recorded status on null hash is manifest_contract",
        BLOCKER_CLASS_MANIFEST in recorded_status["blocker_classes"],
        recorded_status,
    )


_MALFORMED_JSON_SCALARS = (
    ("list", []),
    ("object", {"forged": True}),
    ("bool", True),
    ("number", 0),
    ("null", None),
)
_MALFORMED_STATUS_VALUES = _MALFORMED_JSON_SCALARS + (("unknown-string", "not-a-status-token"),)


def _assert_public_fail_closed(label: str, derived: dict) -> dict:
    check(f"{label} fails public evaluate_phase0", derived["phase0_pass"] is False, derived)
    reasons = derived.get("reasons")
    check(
        f"{label} emits structured reasons",
        isinstance(reasons, list)
        and bool(reasons)
        and all(
            isinstance(row, dict) and row.get("blocker_class") and row.get("code") and "blocker_id" in row
            for row in reasons
        ),
        reasons,
    )
    check(f"{label} records blocker classes", bool(derived.get("blocker_classes")), derived.get("blocker_classes"))
    return derived


def _assert_public_manifest_blocker(label: str, derived: dict, blocker_id: str, code: str | None = None) -> dict:
    _assert_public_fail_closed(label, derived)
    check(
        f"{label} exact blocker_id {blocker_id}",
        blocker_id in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    match = next((row for row in derived["reasons"] if row.get("blocker_id") == blocker_id), None)
    check(f"{label} structured reason for {blocker_id}", isinstance(match, dict), derived.get("reasons"))
    if isinstance(match, dict):
        check(
            f"{label} {blocker_id} class is manifest_contract",
            match.get("blocker_class") == BLOCKER_CLASS_MANIFEST,
            match,
        )
        if code is not None:
            check(f"{label} {blocker_id} code is {code}", match.get("code") == code, match)
    return derived


def _null_mineru_single_file(manifest: dict) -> None:
    obj = manifest["mineru_model_name_version_weights_hash"]
    obj["single_file_weights_sha256"] = None
    obj["single_file_weights_sha256_status"] = "blocked"
    obj["single_file_weights_sha256_notes"] = "synthetic nested hash missing"
    manifest["completeness"]["mineru_model_name_version_weights_hash"] = "partial"


def _null_embedding_batch(manifest: dict) -> None:
    obj = manifest["embedding_dimension_dtype_normalization_batch"]
    obj["batch_contract"] = None
    obj["batch_contract_status"] = "blocked"
    obj["batch_contract_notes"] = "synthetic batch missing"
    obj["status"] = "partial"
    manifest["embedding_batch_contract"] = None
    manifest["embedding_dimension_dtype_normalization_batch_status"] = "partial"
    manifest["completeness"]["embedding_dimension_dtype_normalization_batch"] = "partial"


def _block_v7_wheel(manifest: dict) -> None:
    wheel = manifest["build_flags"]["v7_python_wheel"]
    wheel["status"] = "blocked"
    wheel["artifact_path"] = None
    wheel["artifact_path_status"] = "blocked"
    wheel["notes"] = "synthetic wheel blocked"
    manifest["build_artifact_wheel_sha256"] = None
    manifest["build_artifact_wheel_sha256_status"] = "blocked"
    manifest["build_artifact_wheel_sha256_notes"] = "synthetic wheel hash missing"
    manifest["completeness"]["build_artifact_wheel_sha256"] = "blocked"


def _with_kohaku_components(baselines: dict) -> None:
    baselines["items"]["kohaku_tree_fixtures"]["evidence_components"] = {
        "contract": {"level": "E1", "kind": "types", "id": "kohakurag"},
        "live_or_fixture": {"level": "E1", "kind": "fixtures"},
    }


def _honest_null_tachiom_hash(manifest: dict) -> None:
    field = "tachiom_static_loadable_artifact_sha256"
    manifest[field] = None
    manifest["completeness"][field] = "blocked"
    manifest[f"{field}_status"] = "blocked"
    manifest[f"{field}_notes"] = "synthetic missing hash"


def _honest_null_bm25(manifest: dict) -> None:
    manifest[BM25_COMPOSITE_KEY] = None
    manifest[BM25_CONFIG_HASH_KEY] = None
    manifest[f"{BM25_COMPOSITE_KEY}_status"] = "blocked"
    manifest[f"{BM25_COMPOSITE_KEY}_notes"] = "synthetic bm25 composite missing"
    manifest[f"{BM25_CONFIG_HASH_KEY}_status"] = "blocked"
    manifest[f"{BM25_CONFIG_HASH_KEY}_notes"] = "synthetic bm25 alias missing"
    manifest["completeness"][BM25_COMPOSITE_KEY] = "blocked"
    for key in BM25_SIBLING_KEYS:
        manifest[key] = None
        manifest[f"{key}_status"] = "blocked"


def test_rl5_p1_2_fail_closed_enum_scalar_mutations() -> None:
    def public_eval(label: str, mutate, blocker_id: str, code: str | None = None) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, baselines, corrections, provenance, register)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        return _assert_public_manifest_blocker(label, derived, blocker_id, code=code)

    locations = []

    def completeness_token(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["completeness"]["duckdb_engine_version"] = value

    locations.append(("completeness token", completeness_token, "manifest.completeness.duckdb_engine_version", True))

    def mineru_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["mineru_model_name_version_weights_hash"]["single_file_weights_sha256_status"] = value

    locations.append(
        (
            "mineru hash status",
            mineru_status,
            "manifest.mineru_model_name_version_weights_hash.single_file_weights_sha256_status",
            True,
        )
    )

    def mineru_token(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["completeness"]["mineru_model_name_version_weights_hash"] = value

    locations.append(
        (
            "mineru completeness",
            mineru_token,
            "manifest.completeness.mineru_model_name_version_weights_hash",
            True,
        )
    )

    def embedding_parent_token(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["completeness"]["embedding_dimension_dtype_normalization_batch"] = value

    locations.append(
        (
            "embedding hash completeness",
            embedding_parent_token,
            "manifest.completeness.embedding_dimension_dtype_normalization_batch",
            True,
        )
    )

    def embedding_obj_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["embedding_dimension_dtype_normalization_batch"]["status"] = value

    locations.append(
        (
            "embedding object status",
            embedding_obj_status,
            "manifest.embedding_dimension_dtype_normalization_batch.status",
            True,
        )
    )

    def embedding_batch_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["embedding_dimension_dtype_normalization_batch"]["batch_contract_status"] = value

    locations.append(
        (
            "embedding batch status",
            embedding_batch_status,
            "manifest.embedding_dimension_dtype_normalization_batch.batch_contract_status",
            True,
        )
    )

    def wheel_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["build_flags"]["v7_python_wheel"]["status"] = value

    locations.append(("wheel status", wheel_status, "manifest.build_flags.v7_python_wheel.status", True))

    def wheel_artifact(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["build_flags"]["v7_python_wheel"]["artifact_path"] = value

    locations.append(
        ("wheel artifact_path", wheel_artifact, "manifest.build_flags.v7_python_wheel.artifact_path", False)
    )

    def wheel_artifact_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["build_flags"]["v7_python_wheel"]["artifact_path_status"] = value

    locations.append(
        (
            "wheel artifact_path_status",
            wheel_artifact_status,
            "manifest.build_flags.v7_python_wheel.artifact_path_status",
            True,
        )
    )

    def backend_level(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["backend_gates"]["legacy_cache_live"]["evidence_level"] = value

    locations.append(
        (
            "backend gate evidence_level",
            backend_level,
            "manifest.backend_gates.legacy_cache_live.evidence_level",
            True,
        )
    )

    def mineru_ingest_level(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["backend_gates"]["mineru_json_ingest"]["evidence_level"] = value

    locations.append(
        (
            "mineru_json_ingest evidence_level",
            mineru_ingest_level,
            "manifest.backend_gates.mineru_json_ingest.evidence_level",
            True,
        )
    )

    def bm25_composite_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest[f"{BM25_COMPOSITE_KEY}_status"] = value

    locations.append(
        ("BM25 composite status", bm25_composite_status, f"manifest.{BM25_COMPOSITE_KEY}_status", True)
    )

    def bm25_alias_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest[f"{BM25_CONFIG_HASH_KEY}_status"] = value

    locations.append(("BM25 alias status", bm25_alias_status, f"manifest.{BM25_CONFIG_HASH_KEY}_status", True))

    def baseline_level(_manifest, baselines, _corrections, _provenance, _register, value) -> None:
        baselines["items"]["live_legacy_cache"]["evidence_level"] = value

    locations.append(
        (
            "baseline evidence_level",
            baseline_level,
            "manifest.baselines.live_legacy_cache.evidence_level",
            True,
        )
    )

    def component_contract_level(_manifest, baselines, _corrections, _provenance, _register, value) -> None:
        _with_kohaku_components(baselines)
        baselines["items"]["kohaku_tree_fixtures"]["evidence_components"]["contract"]["level"] = value

    locations.append(
        (
            "evidence_components contract level",
            component_contract_level,
            "manifest.baselines.kohaku_tree_fixtures.evidence_components.contract",
            True,
        )
    )

    def component_contract_kind(_manifest, baselines, _corrections, _provenance, _register, value) -> None:
        _with_kohaku_components(baselines)
        baselines["items"]["kohaku_tree_fixtures"]["evidence_components"]["contract"]["kind"] = value

    locations.append(
        (
            "evidence_components contract kind",
            component_contract_kind,
            "manifest.baselines.kohaku_tree_fixtures.evidence_components.contract",
            True,
        )
    )

    def component_live_level(_manifest, baselines, _corrections, _provenance, _register, value) -> None:
        _with_kohaku_components(baselines)
        baselines["items"]["kohaku_tree_fixtures"]["evidence_components"]["live_or_fixture"]["level"] = value

    locations.append(
        (
            "evidence_components live level",
            component_live_level,
            "manifest.baselines.kohaku_tree_fixtures.evidence_components.live_or_fixture",
            True,
        )
    )

    def component_live_kind(_manifest, baselines, _corrections, _provenance, _register, value) -> None:
        _with_kohaku_components(baselines)
        baselines["items"]["kohaku_tree_fixtures"]["evidence_components"]["live_or_fixture"]["kind"] = value

    locations.append(
        (
            "evidence_components live kind",
            component_live_kind,
            "manifest.baselines.kohaku_tree_fixtures.evidence_components.live_or_fixture",
            True,
        )
    )

    def correction_status(_manifest, _baselines, corrections, _provenance, _register, value) -> None:
        corrections["corrections"][0]["status"] = value

    locations.append(
        ("correction status", correction_status, "manifest.corrections_register.F-1.status", True)
    )

    def hash_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["tachiom_static_loadable_artifact_sha256_status"] = value

    locations.append(
        (
            "nullable hash status",
            hash_status,
            "manifest.tachiom_static_loadable_artifact_sha256_status",
            True,
        )
    )

    def hash_token(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["completeness"]["tachiom_static_loadable_artifact_sha256"] = value

    locations.append(
        (
            "nullable hash completeness",
            hash_token,
            "manifest.completeness.tachiom_static_loadable_artifact_sha256",
            True,
        )
    )

    def register_level(_manifest, _baselines, _corrections, _provenance, register, value) -> None:
        for row in register["contracts"]:
            if row.get("id") == "mineru":
                row["level"] = value

    locations.append(("register contract level", register_level, "manifest.evidence_register.mineru.level", True))

    def register_blocker_level(_manifest, _baselines, _corrections, _provenance, register, value) -> None:
        for row in register["contracts"]:
            if row.get("id") == "infinisynapse_exact_dto":
                row["blockers"][0]["level"] = value

    locations.append(
        (
            "register blocker level",
            register_blocker_level,
            "manifest.evidence_register.infinisynapse_exact_dto.blockers",
            True,
        )
    )

    def flock_submodule_status(_manifest, _baselines, _corrections, provenance, _register, value) -> None:
        provenance["repos"]["flock"]["submodules"]["duckdb"]["status"] = value

    locations.append(
        (
            "flock submodule status",
            flock_submodule_status,
            "provenance.repos.flock.submodules.duckdb.status",
            True,
        )
    )

    for location, mutate, blocker_id, include_unknown in locations:
        values = _MALFORMED_STATUS_VALUES if include_unknown else _MALFORMED_JSON_SCALARS
        for kind, value in values:
            code = (
                "MANIFEST_STATUS_INVALID"
                if blocker_id
                in {
                    "manifest.backend_gates.legacy_cache_live.evidence_level",
                    "manifest.backend_gates.mineru_json_ingest.evidence_level",
                }
                else None
            )
            public_eval(
                f"{location} {kind}",
                lambda manifest, baselines, corrections, provenance, register, mutate=mutate, value=value: mutate(
                    manifest, baselines, corrections, provenance, register, value
                ),
                blocker_id,
                code,
            )

    def delete_mineru_ingest_level(manifest, _baselines, _corrections, _provenance, _register) -> None:
        del manifest["backend_gates"]["mineru_json_ingest"]["evidence_level"]

    public_eval(
        "mineru_json_ingest missing evidence_level",
        delete_mineru_ingest_level,
        "manifest.backend_gates.mineru_json_ingest.evidence_level",
        "MANIFEST_FIELD_MISSING",
    )

    def blocked_artifact_status(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        _block_v7_wheel(manifest)
        manifest["build_flags"]["v7_python_wheel"]["artifact_path_status"] = value

    for kind, value in _MALFORMED_STATUS_VALUES:
        if value == "blocked":
            continue
        public_eval(
            f"blocked wheel artifact_path_status {kind}",
            lambda manifest, baselines, corrections, provenance, register, value=value: blocked_artifact_status(
                manifest, baselines, corrections, provenance, register, value
            ),
            "manifest.build_flags.v7_python_wheel.artifact_path_status",
        )

    def delete_blocked_artifact_status(manifest, _baselines, _corrections, _provenance, _register) -> None:
        _block_v7_wheel(manifest)
        del manifest["build_flags"]["v7_python_wheel"]["artifact_path_status"]

    public_eval(
        "blocked wheel missing artifact_path_status",
        delete_blocked_artifact_status,
        "manifest.build_flags.v7_python_wheel.artifact_path_status",
    )

    control_manifest, control_baselines, control_corrections, control_provenance, control_register, historical, nearest = (
        _passable_gate_inputs()
    )
    control = _eval_public_phase0(
        control_manifest,
        control_baselines,
        control_corrections,
        control_provenance,
        control_register,
        historical,
        nearest,
    )
    check("absent embedding status remains passable", control["phase0_pass"] is True, control)
    check(
        "absent wheel artifact_path_status remains passable",
        "manifest.build_flags.v7_python_wheel.artifact_path_status" not in control["blocker_ids"],
        control["blocker_ids"],
    )


def test_rl5_p1_2_consistency_fail_closed() -> None:
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived = _eval_public_phase0(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("passable public Phase 0 is true", derived["phase0_pass"] is True, derived)
    honest = phase0_record_consistency_errors(baselines, derived)
    check("honest passable recorded Phase 0 matches", honest == [], honest)

    for label, recorded in (
        ("bool True", True),
        ("number 1", 1),
        ("list", ["not-a-mapping"]),
        ("null", None),
    ):
        errors = phase0_record_consistency_errors(recorded, derived)
        check(
            f"non-mapping recorded baseline {label} is structured",
            isinstance(errors, list) and errors and all(isinstance(item, str) for item in errors),
            errors,
        )

    def recorded_payload(**overrides):
        payload = {
            "schema_version": derived["schema_version"],
            "evaluator": derived["evaluator"],
            "phase0_pass": derived["phase0_pass"],
            "blocker_ids": list(derived["blocker_ids"]),
            "blocker_classes": list(derived["blocker_classes"]),
            "reasons": list(derived["reasons"]),
        }
        payload.update(overrides)
        return payload

    for field, forged in (
        ("blocker_ids", True),
        ("blocker_ids", 1),
        ("blocker_ids", {"forged": True}),
        ("blocker_ids", None),
        ("blocker_classes", True),
        ("reasons", True),
        ("reasons", 1),
        ("reasons", {"forged": True}),
        ("reasons", None),
    ):
        errors = phase0_record_consistency_errors(recorded_payload(**{field: forged}), derived)
        check(
            f"malformed recorded {field}={forged!r} is structured",
            isinstance(errors, list) and errors and all(isinstance(item, str) for item in errors),
            errors,
        )

    release = evaluate_release_gate(derived, default_phase_gates(), default_e3_state())
    for label, recorded in (
        ("bool True", True),
        ("number 1", 1),
        ("list", [True]),
        ("null", None),
    ):
        errors = release_record_consistency_errors(recorded, release)
        check(
            f"non-mapping recorded release {label} is structured",
            isinstance(errors, list) and errors and all(isinstance(item, str) for item in errors),
            errors,
        )
    malformed_release = dict(release)
    malformed_release["reasons"] = True
    malformed_release["blocker_ids"] = {1: "x"}
    errors = release_record_consistency_errors(malformed_release, release)
    check(
        "malformed recorded release arrays are structured",
        isinstance(errors, list) and errors and all(isinstance(item, str) for item in errors),
        errors,
    )
    errors = release_record_consistency_errors(release, True)
    check(
        "non-mapping evaluated release is structured",
        isinstance(errors, list) and errors and all(isinstance(item, str) for item in errors),
        errors,
    )


def test_rl5_p1_2_bm25_config_hash_alias() -> None:
    def public_eval(label: str, mutate) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        return _assert_public_fail_closed(label, derived)

    def delete_alias(manifest: dict) -> None:
        del manifest[BM25_CONFIG_HASH_KEY]

    deleted = public_eval("BM25 alias key deleted", delete_alias)
    check(
        "deleted BM25 alias is manifest_contract",
        BLOCKER_CLASS_MANIFEST in deleted["blocker_classes"],
        deleted,
    )
    check(
        "deleted BM25 alias records missing field",
        f"manifest.{BM25_CONFIG_HASH_KEY}" in deleted["blocker_ids"],
        deleted["blocker_ids"],
    )

    for kind, value in _MALFORMED_JSON_SCALARS:
        if value is None:
            continue

        def malformed(manifest: dict, forged=value) -> None:
            manifest[BM25_CONFIG_HASH_KEY] = forged

        malformed_result = public_eval(f"BM25 alias {kind}", malformed)
        check(
            f"malformed BM25 alias {kind} is manifest_contract",
            BLOCKER_CLASS_MANIFEST in malformed_result["blocker_classes"],
            malformed_result,
        )

    def alias_null_vs_composite(manifest: dict) -> None:
        manifest[BM25_CONFIG_HASH_KEY] = None
        manifest[f"{BM25_CONFIG_HASH_KEY}_status"] = "blocked"
        manifest[f"{BM25_CONFIG_HASH_KEY}_notes"] = "synthetic alias null"

    mismatch = public_eval("BM25 alias null while composite recorded", alias_null_vs_composite)
    check(
        "null alias vs recorded composite is manifest_contract",
        BLOCKER_CLASS_MANIFEST in mismatch["blocker_classes"],
        mismatch,
    )

    def honest_null(manifest: dict) -> None:
        _honest_null_bm25(manifest)

    honest = public_eval("honest BM25 null hashes remain unavailable", honest_null)
    check(
        "honest BM25 null is required_null_hashes",
        BLOCKER_CLASS_REQUIRED_NULL_HASHES in honest["blocker_classes"],
        honest,
    )

    def missing_alias_status(manifest: dict) -> None:
        _honest_null_bm25(manifest)
        del manifest[f"{BM25_CONFIG_HASH_KEY}_status"]

    missing_status = public_eval("BM25 alias null missing sibling status", missing_alias_status)
    check(
        "missing BM25 alias status is manifest_contract",
        BLOCKER_CLASS_MANIFEST in missing_status["blocker_classes"],
        missing_status,
    )

    def empty_alias_notes(manifest: dict) -> None:
        _honest_null_bm25(manifest)
        manifest[f"{BM25_CONFIG_HASH_KEY}_notes"] = ""

    empty_notes = public_eval("BM25 alias null empty sibling notes", empty_alias_notes)
    check(
        "empty BM25 alias notes is manifest_contract",
        BLOCKER_CLASS_MANIFEST in empty_notes["blocker_classes"],
        empty_notes,
    )

    def recorded_alias_status(manifest: dict) -> None:
        _honest_null_bm25(manifest)
        manifest[f"{BM25_CONFIG_HASH_KEY}_status"] = "recorded"

    recorded_status = public_eval("BM25 alias null recorded status", recorded_alias_status)
    check(
        "recorded BM25 alias status is manifest_contract",
        BLOCKER_CLASS_MANIFEST in recorded_status["blocker_classes"],
        recorded_status,
    )

    def recorded_alias_completeness(manifest: dict) -> None:
        _honest_null_bm25(manifest)
        manifest["completeness"][BM25_CONFIG_HASH_KEY] = "recorded"

    recorded_complete = public_eval("BM25 alias null recorded completeness", recorded_alias_completeness)
    check(
        "recorded BM25 alias completeness is manifest_contract",
        BLOCKER_CLASS_MANIFEST in recorded_complete["blocker_classes"],
        recorded_complete,
    )

    def mismatched_alias_completeness(manifest: dict) -> None:
        _honest_null_bm25(manifest)
        manifest["completeness"][BM25_CONFIG_HASH_KEY] = "partial"

    mismatched_complete = public_eval("BM25 alias completeness disagrees with composite", mismatched_alias_completeness)
    check(
        "mismatched BM25 alias completeness is manifest_contract",
        BLOCKER_CLASS_MANIFEST in mismatched_complete["blocker_classes"],
        mismatched_complete,
    )

    def null_alias_completeness(manifest: dict) -> None:
        _honest_null_bm25(manifest)
        manifest["completeness"][BM25_CONFIG_HASH_KEY] = None

    null_complete = public_eval("BM25 alias completeness explicit null", null_alias_completeness)
    check(
        "explicit null BM25 alias completeness is manifest_contract",
        BLOCKER_CLASS_MANIFEST in null_complete["blocker_classes"],
        null_complete,
    )
    check(
        "explicit null BM25 alias completeness records completeness field",
        f"manifest.completeness.{BM25_CONFIG_HASH_KEY}" in null_complete["blocker_ids"],
        null_complete["blocker_ids"],
    )

    for kind, value in _MALFORMED_JSON_SCALARS:
        def malformed_notes(manifest: dict, forged=value) -> None:
            _honest_null_bm25(manifest)
            manifest[f"{BM25_CONFIG_HASH_KEY}_notes"] = forged

        notes_result = public_eval(f"BM25 alias notes {kind}", malformed_notes)
        check(
            f"malformed BM25 alias notes {kind} is manifest_contract",
            BLOCKER_CLASS_MANIFEST in notes_result["blocker_classes"],
            notes_result,
        )


def test_rl5_p1_2_supported_status_schema_mutations() -> None:
    def public_eval(label: str, mutate, blocker_id: str) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(manifest, baselines, corrections, provenance, register)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        derived = _assert_public_manifest_blocker(label, derived, blocker_id)
        match = next((row for row in derived["reasons"] if row.get("blocker_id") == blocker_id), None)
        check(
            f"{label} {blocker_id} code is MANIFEST_STATUS_INVALID",
            isinstance(match, dict) and match.get("code") == "MANIFEST_STATUS_INVALID",
            match,
        )
        return derived

    locations = []

    def mineru_runtime(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["mineru_runtime_distribution_version_status"] = value

    locations.append(
        (
            "mineru runtime status",
            mineru_runtime,
            "manifest.mineru_runtime_distribution_version_status",
        )
    )

    def mineru_config(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["mineru_parser_config_status"] = value

    locations.append(("mineru config status", mineru_config, "manifest.mineru_parser_config_status"))

    def mineru_model(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["mineru_model_name_status"] = value

    locations.append(("mineru model status", mineru_model, "manifest.mineru_model_name_status"))

    def mdenseon_runtime(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["mdenseon_package_native_runtime_version_status"] = value

    locations.append(
        (
            "mdenseon runtime status",
            mdenseon_runtime,
            "manifest.mdenseon_package_native_runtime_version_status",
        )
    )

    def embedding_dimension(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["embedding_dimension_status"] = value

    locations.append(("embedding dimension status", embedding_dimension, "manifest.embedding_dimension_status"))

    def tachiom_index(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["tachiom_index_format_version_status"] = value

    locations.append(
        ("tachiom index status", tachiom_index, "manifest.tachiom_index_format_version_status")
    )

    def fts_semver(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["fts_extension_semver_status"] = value

    locations.append(("FTS semver status", fts_semver, "manifest.fts_extension_semver_status"))

    def pg_agent_tag(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["pg_agent_tag_status"] = value

    locations.append(("pg-agent tag status", pg_agent_tag, "manifest.pg_agent_tag_status"))

    def flock_tag(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["flock_tag_status"] = value

    locations.append(("flock tag status", flock_tag, "manifest.flock_tag_status"))

    def tachiom_tag(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["tachiom_checkout_tag_status"] = value

    locations.append(
        ("tachiom checkout tag status", tachiom_tag, "manifest.tachiom_checkout_tag_status")
    )

    def static_target(manifest, _baselines, _corrections, _provenance, _register, value) -> None:
        manifest["static_build_targets"]["tachiom_static_cmake_status"] = value

    locations.append(
        (
            "static tachiom cmake status",
            static_target,
            "manifest.static_build_targets.tachiom_static_cmake_status",
        )
    )

    def repo_tag(_manifest, _baselines, _corrections, provenance, _register, value) -> None:
        provenance["repos"]["pg-agent"]["tag_status"] = value

    locations.append(
        ("provenance pg-agent tag status", repo_tag, "provenance.repos.pg-agent.tag_status")
    )

    def external_tag(_manifest, _baselines, _corrections, provenance, _register, value) -> None:
        provenance["external_not_four_repo"]["tachiom"]["tag_status"] = value

    locations.append(
        (
            "provenance tachiom tag status",
            external_tag,
            "provenance.external_not_four_repo.tachiom.tag_status",
        )
    )

    for location, mutate, blocker_id in locations:
        for kind, value in _MALFORMED_STATUS_VALUES:
            public_eval(
                f"{location} {kind}",
                lambda manifest, baselines, corrections, provenance, register, mutate=mutate, value=value: mutate(
                    manifest, baselines, corrections, provenance, register, value
                ),
                blocker_id,
            )

    control_manifest, control_baselines, control_corrections, control_provenance, control_register, historical, nearest = (
        _passable_gate_inputs()
    )
    control = _eval_public_phase0(
        control_manifest,
        control_baselines,
        control_corrections,
        control_provenance,
        control_register,
        historical,
        nearest,
    )
    check("absent optional supported statuses remain passable", control["phase0_pass"] is True, control)


def test_rl5_p1_2_release_phase_e3_enum_mutations() -> None:
    passable = _evaluate_passable()

    def assert_phase_blocked(label: str, release: dict, phase_id: str) -> None:
        check(f"{label} is not release-ready", release["release_ready"] is False, release)
        check(f"{label} would_pass is false", release["would_pass"] is False, release)
        blocker_id = f"{phase_id}_not_passed"
        check(f"{label} blocker is {blocker_id}", blocker_id in release["blocker_ids"], release["blocker_ids"])
        check(
            f"{label} class is phase_gates",
            BLOCKER_CLASS_PHASE_GATES in release["blocker_classes"],
            release["blocker_classes"],
        )
        match = next((row for row in release["reasons"] if row.get("blocker_id") == blocker_id), None)
        check(
            f"{label} reason code is PHASE_GATE_NOT_PASSED",
            isinstance(match, dict) and match.get("code") == "PHASE_GATE_NOT_PASSED",
            match,
        )
        check(
            f"{label} reason class is phase_gates",
            isinstance(match, dict) and match.get("blocker_class") == BLOCKER_CLASS_PHASE_GATES,
            match,
        )

    def assert_e3_blocked(label: str, release: dict) -> None:
        check(f"{label} is not release-ready", release["release_ready"] is False, release)
        check(f"{label} would_pass is false", release["would_pass"] is False, release)
        check(f"{label} blocker is e3_not_verified", "e3_not_verified" in release["blocker_ids"], release["blocker_ids"])
        check(
            f"{label} class is e3_integration",
            BLOCKER_CLASS_E3 in release["blocker_classes"],
            release["blocker_classes"],
        )
        match = next((row for row in release["reasons"] if row.get("blocker_id") == "e3_not_verified"), None)
        check(
            f"{label} reason code is E3_NOT_VERIFIED",
            isinstance(match, dict) and match.get("code") == "E3_NOT_VERIFIED",
            match,
        )

    for phase_id in PHASE_IDS:
        for field in ("state", "evidence_level"):
            for kind, value in _MALFORMED_STATUS_VALUES:
                gates = _passed_phase_gates()
                gates[phase_id] = dict(gates[phase_id])
                gates[phase_id][field] = value
                release = evaluate_release_gate(passable, gates, _passed_e3())
                assert_phase_blocked(f"{phase_id} {field} {kind}", release, phase_id)
            gates = _passed_phase_gates()
            gates[phase_id] = [gates[phase_id]]
            release = evaluate_release_gate(passable, gates, _passed_e3())
            assert_phase_blocked(f"{phase_id} object replaced with list", release, phase_id)

    for field in ("state", "evidence_level"):
        for kind, value in _MALFORMED_STATUS_VALUES:
            e3 = _passed_e3()
            e3[field] = value
            release = evaluate_release_gate(passable, _passed_phase_gates(), e3)
            assert_e3_blocked(f"e3 {field} {kind}", release)

    release = evaluate_release_gate(passable, _passed_phase_gates(), [_passed_e3()])
    assert_e3_blocked("e3 object replaced with list", release)

    unbound_complete = evaluate_release_gate(passable, _passed_phase_gates(), _passed_e3())
    check(
        "unbound unmutated passed gates are not release-ready",
        unbound_complete["release_ready"] is False,
        unbound_complete,
    )
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    with _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
    ) as session:
        complete = evaluate_release_gate(
            session["result"],
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=session["root"],
            environ=session["environ"],
        )
        check("bound unmutated passed gates remain release-ready", complete["release_ready"] is True, complete)


def test_malformed_nested_objects_block() -> None:
    for field in (
        "mineru_parser_config",
        "mineru_model_name_version_weights_hash",
        "mdenseon_package_native_runtime_version",
        "tokenizer_identity_version_hash",
        "embedding_dimension_dtype_normalization_batch",
        "static_build_targets",
    ):
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        del manifest[field]
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"deleting {field} fails Phase 0", derived["phase0_pass"] is False, derived)
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        manifest[field] = "not-an-object"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"malformed {field} fails Phase 0", derived["phase0_pass"] is False, derived)
        check(f"malformed {field} is manifest_contract", BLOCKER_CLASS_MANIFEST in derived["blocker_classes"], derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    del manifest["build_flags"]["v7_python_wheel"]
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("deleting v7 wheel config fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["build_flags"]["v7_python_wheel"] = "blocked"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("malformed v7 wheel object fails Phase 0", derived["phase0_pass"] is False, derived)
    for name in REQUIRED_BACKEND_GATES:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        del manifest["backend_gates"][name]["reason"]
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"backend gate {name} missing reason fails Phase 0", derived["phase0_pass"] is False, derived)


def test_baseline_relationship_mutations() -> None:
    for item_id in REQUIRED_BASELINE_IDS:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        baselines["items"][item_id]["contract_frozen"] = False
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"{item_id} unfrozen fails Phase 0", derived["phase0_pass"] is False, derived)
        check(
            f"{item_id} unfrozen is missing_baselines",
            BLOCKER_CLASS_MISSING_BASELINES in derived["blocker_classes"],
            derived["blocker_classes"],
        )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        baselines["items"][item_id]["live_runtime_missing"] = True
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        fixture_kind = BASELINE_RELATION_BY_ID[item_id].get("live_or_fixture_component_kind") == "fixtures"
        pass_exempt = BASELINE_RELATION_BY_ID[item_id].get("phase0_pass_required") is False
        if pass_exempt:
            check(
                f"{item_id} Option B live_runtime_missing stays pass-exempt",
                derived["phase0_pass"] is True,
                derived,
            )
            check(
                f"{item_id} live_runtime_missing remains true",
                baselines["items"][item_id]["live_runtime_missing"] is True,
            )
        elif fixture_kind:
            check(
                f"{item_id} missing live runtime still available with E2 fixtures",
                derived["phase0_pass"] is True,
                derived,
            )
        else:
            check(f"{item_id} missing live with allowed flags fails Phase 0", derived["phase0_pass"] is False, derived)
            check(
                f"{item_id} contradictory allowed flags are manifest_contract",
                BLOCKER_CLASS_MANIFEST in derived["blocker_classes"],
                derived["blocker_classes"],
            )
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        baselines["items"][item_id]["implementation_allowed"] = False
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        if pass_exempt:
            check(
                f"{item_id} Option B already-unavailable impl false stays pass-exempt",
                derived["phase0_pass"] is True,
                derived,
            )
        else:
            check(f"{item_id} release without implementation fails Phase 0", derived["phase0_pass"] is False, derived)
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        baselines["items"][item_id]["blocked_backend"] = "wrong_gate"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"{item_id} blocked_backend mismatch fails Phase 0", derived["phase0_pass"] is False, derived)
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        baselines["items"][item_id]["contract_frozen"] = "true"
        derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
        check(f"{item_id} non-boolean frozen fails Phase 0", derived["phase0_pass"] is False, derived)


def test_register_and_correction_schema_mutations() -> None:
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    register["contracts"] = "not-a-list"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("non-list contracts fail Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    register["contracts"][0] = "mineru"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("string contract row fails Phase 0 without throwing", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    register["contracts"].append(dict(register["contracts"][0]))
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("duplicate contract id fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    register["contracts"] = [row for row in register["contracts"] if row.get("id") != "nearest_basic"]
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("missing nearest_basic contract fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    for row in register["contracts"]:
        if row.get("id") == "infinisynapse_schema":
            row["exact_tool_dto_frozen"] = True
            row["exact_tool_dto_level"] = "E1"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("infinisynapse DTO inversion fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    corrections["corrections"].append("not-a-row")
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("malformed correction row fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    corrections["corrections"].append(dict(corrections["corrections"][0]))
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("duplicate correction id fails Phase 0", derived["phase0_pass"] is False, derived)


def _assert_public_nearest_unverified(label: str, derived: dict) -> dict:
    _assert_public_fail_closed(label, derived)
    check(
        f"{label} exact blocker_id {NEAREST_TARGET_E2_UNVERIFIED}",
        NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    match = next((row for row in derived["reasons"] if row.get("blocker_id") == NEAREST_TARGET_E2_UNVERIFIED), None)
    check(f"{label} structured nearest reason", isinstance(match, dict), derived.get("reasons"))
    if isinstance(match, dict):
        check(
            f"{label} class is live_evidence",
            match.get("blocker_class") == BLOCKER_CLASS_LIVE_EVIDENCE,
            match,
        )
        check(f"{label} code is NEAREST_E2_UNVERIFIED", match.get("code") == "NEAREST_E2_UNVERIFIED", match)
    return derived


def test_rl5_p1_2_correction_alias_graph() -> None:
    def public_eval(label: str, mutate) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(corrections)
        return _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )

    def self_alias(corrections: dict) -> None:
        row = corrections["corrections"][0]
        row["alias_of"] = row["id"]

    self_derived = public_eval("correction self-alias", self_alias)
    self_id = "manifest.corrections_register.F-1.alias_of"
    _assert_public_manifest_blocker("correction self-alias", self_derived, self_id, code="MANIFEST_FIELD_INVALID")
    self_match = next(row for row in self_derived["reasons"] if row.get("blocker_id") == self_id)
    check(
        "self-alias reason is self_alias",
        (self_match.get("details") or {}).get("reason") == "self_alias",
        self_match,
    )
    check(
        "self-alias does not hide behind an unrelated pass",
        self_derived["phase0_pass"] is False,
        self_derived,
    )

    def two_cycle(corrections: dict) -> None:
        template = dict(corrections["corrections"][0])
        left = dict(template)
        left["id"] = "CYCLE-A"
        left["alias_of"] = "CYCLE-B"
        right = dict(template)
        right["id"] = "CYCLE-B"
        right["alias_of"] = "CYCLE-A"
        corrections["corrections"].extend([left, right])

    cycle_derived = public_eval("correction 2-node alias cycle", two_cycle)
    cycle_ids = (
        "manifest.corrections_register.CYCLE-A.alias_of",
        "manifest.corrections_register.CYCLE-B.alias_of",
    )
    for cycle_id in cycle_ids:
        _assert_public_manifest_blocker(
            f"correction 2-node cycle {cycle_id}",
            cycle_derived,
            cycle_id,
            code="MANIFEST_FIELD_INVALID",
        )
        match = next(row for row in cycle_derived["reasons"] if row.get("blocker_id") == cycle_id)
        check(
            f"{cycle_id} reason is alias_cycle",
            (match.get("details") or {}).get("reason") == "alias_cycle",
            match,
        )


def test_rl5_p1_2_nearest_hermetic_recorded_path() -> None:
    live_historical = _load_json(NEAREST_JSON_PATH)
    recorded_path = live_historical.get("binary_path")
    check(
        "live historical records an absolute binary_path",
        isinstance(recorded_path, str) and Path(recorded_path).is_absolute(),
        recorded_path,
    )
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    historical["binary_path"] = recorded_path
    historical["binary_sha256"] = NEAREST_SHA256
    historical["binary_size_bytes"] = NEAREST_SIZE_BYTES
    manifest["nearest_e2"]["binary_path"] = recorded_path
    manifest["nearest_e2"]["binary_sha256"] = NEAREST_SHA256
    manifest["nearest_e2"]["binary_size_bytes"] = NEAREST_SIZE_BYTES
    derived = _eval_public_phase0(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        nearest,
        live_binary=False,
        live_log=True,
        pin_live_binary=False,
        environ={},
    )
    _assert_public_nearest_unverified("recorded absolute path with no env", derived)


def test_rl5_p1_2_nearest_configured_relpath_live() -> None:
    derived = evaluate_phase0(REPO_ROOT)
    check(
        "canonical evaluate_phase0 without unittest env closes nearest unverified",
        NEAREST_TARGET_E2_UNVERIFIED not in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    derived_empty = evaluate_phase0(REPO_ROOT, environ={})
    check(
        "canonical evaluate_phase0 with empty environ matches default environ",
        derived_empty == derived,
        derived_empty,
    )
    check(
        "canonical live_evidence class is gone once NEAREST verifies",
        BLOCKER_CLASS_LIVE_EVIDENCE not in derived["blocker_classes"],
        derived["blocker_classes"],
    )
    copied = [
        path
        for folder in (V7_ROOT / "evidence", V7_ROOT / "gates", V7_ROOT / "tests")
        for path in folder.rglob("*")
        if path.is_file() and path.name == "unittest" and path.stat().st_size == NEAREST_SIZE_BYTES
    ]
    check("target unittest binary was not copied into pg-agent", copied == [], copied)
    configured = _resolve_configured_live_binary(REPO_ROOT)
    check("configured relpath resolves to a file", configured is not None and configured.is_file(), configured)
    if configured is not None:
        check(
            "configured relpath is outside pg-agent",
            REPO_ROOT.resolve() not in configured.resolve().parents
            and configured.resolve() != REPO_ROOT.resolve(),
            configured,
        )
        digest = hashlib.sha256(configured.read_bytes()).hexdigest()
        check("configured binary sha256 matches freeze", digest == NEAREST_SHA256, digest)
        check("configured binary size matches freeze", configured.stat().st_size == NEAREST_SIZE_BYTES)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    ok = _eval_public_phase0(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        nearest,
        inject_unittest_env=False,
        environ={},
        configured_relpath_text="synthetic/unittest\n",
    )
    check("in-temp configured relpath verifies without env", ok["phase0_pass"] is True, ok)
    check(
        "in-temp configured relpath does not add nearest unverified",
        NEAREST_TARGET_E2_UNVERIFIED not in ok["blocker_ids"],
        ok["blocker_ids"],
    )

    def public_unverified(label: str, **kwargs) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
            inject_unittest_env=False,
            environ={},
            **kwargs,
        )
        return _assert_public_nearest_unverified(label, derived)

    public_unverified("missing configured relpath stays unverified")
    public_unverified("empty configured relpath", configured_relpath_text="\n")
    public_unverified("whitespace configured relpath", configured_relpath_text="   \n")
    public_unverified("absolute configured relpath", configured_relpath_text="/tmp/unittest\n")
    public_unverified("home configured relpath", configured_relpath_text="~/unittest\n")
    public_unverified("multiline configured relpath", configured_relpath_text="synthetic/unittest\nextra\n")
    public_unverified("backslash configured relpath", configured_relpath_text="synthetic\\unittest\n")
    public_unverified("missing configured target", configured_relpath_text="missing/unittest\n")
    public_unverified("comment configured relpath", configured_relpath_text="# synthetic/unittest\n")
    public_unverified("dollar configured relpath", configured_relpath_text="$HOME/unittest\n")
    public_unverified("dotdot-only configured relpath", configured_relpath_text="..\n")
    public_unverified("directory configured target", configured_relpath_text="synthetic\n")
    public_unverified(
        "hash-mismatched configured target",
        configured_relpath_text="synthetic/unittest\n",
        binary_bytes=b"not-the-nearest-unittest\n",
        pin_live_binary=False,
        live_binary=True,
    )

    def chmod_unreadable_relpath(root: Path) -> None:
        path = root / NEAREST_LIVE_BINARY_RELPATH_FILE
        path.chmod(0)

    public_unverified(
        "unreadable configured relpath",
        configured_relpath_text="synthetic/unittest\n",
        prepare_root=chmod_unreadable_relpath,
    )

    def chmod_unreadable_binary(root: Path) -> None:
        path = root / "synthetic" / "unittest"
        path.chmod(0)

    public_unverified(
        "unreadable configured binary",
        configured_relpath_text="synthetic/unittest\n",
        prepare_root=chmod_unreadable_binary,
    )


def test_rl5_p1_2_nearest_log_parser_mutations() -> None:
    def public_eval(label: str, mutate_log) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
            log_mutate=mutate_log,
        )
        return _assert_public_nearest_unverified(label, derived)

    def truncated_near_valid(text: str) -> str:
        header = text.split(NEAREST_STDOUT_DELIM, 1)[0]
        return header + "All tests passed (112 assertions in 1 test case)\n"

    public_eval("truncated near-valid nearest log", truncated_near_valid)

    def missing_stderr(text: str) -> str:
        return text.split(NEAREST_STDERR_DELIM, 1)[0]

    public_eval("nearest log missing stderr delimiter", missing_stderr)

    def missing_stdout(text: str) -> str:
        header, rest = text.split(NEAREST_STDOUT_DELIM, 1)
        stdout, stderr = rest.split(NEAREST_STDERR_DELIM, 1)
        return header + NEAREST_STDERR_DELIM + stderr

    public_eval("nearest log missing stdout delimiter", missing_stdout)

    def missing_filter(text: str) -> str:
        return text.replace("Filters: test/sql/join/nearest/nearest_basic.test", "Filters: other.test")

    public_eval("nearest log missing canonical filter", missing_filter)

    def dirty_working_tree(text: str) -> str:
        return text.replace(NEAREST_WORKING_TREE_CLEAN, "clean-ish")

    public_eval("nearest log non-canonical working_tree token", dirty_working_tree)

    def suffix_result(text: str) -> str:
        return text.replace(
            "All tests passed (112 assertions in 1 test case)",
            "All tests passed (112 assertions in 1 test case) EXTRA",
        )

    public_eval("nearest log result line suffix", suffix_result)

    def duplicate_stdout(text: str) -> str:
        return text.replace(NEAREST_STDOUT_DELIM, NEAREST_STDOUT_DELIM + "\n" + NEAREST_STDOUT_DELIM, 1)

    public_eval("nearest log duplicate stdout delimiter", duplicate_stdout)

    def duplicate_stderr(text: str) -> str:
        return text.replace(NEAREST_STDERR_DELIM, NEAREST_STDERR_DELIM + "\n" + NEAREST_STDERR_DELIM, 1)

    public_eval("nearest log duplicate stderr delimiter", duplicate_stderr)

    def failure_and_forged_pass(text: str) -> str:
        return text.replace(
            "All tests passed (112 assertions in 1 test case)",
            "ALL TESTS FAILED (1 failed)\nAll tests passed (112 assertions in 1 test case)",
        )

    public_eval("nearest log failure plus forged pass", failure_and_forged_pass)


def test_rl5_p1_2_nearest_relative_env_independent_of_cwd() -> None:
    with tempfile.TemporaryDirectory() as outside:
        outside_root = Path(outside)
        decoy = outside_root / "synthetic" / "unittest"
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_bytes(b"cwd-decoy-not-the-unittest\n")
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
            environ={UNITTEST_BIN_ENV_VARS[0]: "synthetic/unittest"},
            eval_cwd=outside_root,
        )
        check(
            "relative env binary is accepted from cwd outside the temp repo",
            derived["phase0_pass"] is True,
            derived,
        )
        check(
            "outside-cwd relative env does not add NEAREST unverified",
            NEAREST_TARGET_E2_UNVERIFIED not in derived["blocker_ids"],
            derived["blocker_ids"],
        )

        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        historical["binary_path"] = "synthetic/unittest"
        manifest["nearest_e2"]["binary_path"] = "synthetic/unittest"
        recorded = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
            environ={},
            inject_unittest_env=False,
            eval_cwd=outside_root,
        )
        check(
            "repo-relative recorded binary is accepted from cwd outside the temp repo",
            recorded["phase0_pass"] is True,
            recorded,
        )


def test_rl5_p1_2_correction_count_types() -> None:
    def public_eval(label: str, mutate, blocker_id: str) -> dict:
        manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
        mutate(corrections)
        derived = _eval_public_phase0(
            manifest,
            baselines,
            corrections,
            provenance,
            register,
            historical,
            nearest,
        )
        return _assert_public_manifest_blocker(label, derived, blocker_id, code="MANIFEST_FIELD_INVALID")

    def bool_unresolved(corrections: dict) -> None:
        corrections["counts"]["unique_unresolved"] = False

    public_eval(
        "correction unique_unresolved bool",
        bool_unresolved,
        "manifest.corrections_register.counts.unique_unresolved",
    )

    def bool_partial(corrections: dict) -> None:
        corrections["counts"]["unique_partial"] = True

    public_eval(
        "correction unique_partial bool",
        bool_partial,
        "manifest.corrections_register.counts.unique_partial",
    )

    def string_unresolved(corrections: dict) -> None:
        corrections["counts"]["unique_unresolved"] = "0"

    public_eval(
        "correction unique_unresolved string",
        string_unresolved,
        "manifest.corrections_register.counts.unique_unresolved",
    )

    def object_partial(corrections: dict) -> None:
        corrections["counts"]["unique_partial"] = {"n": 0}

    public_eval(
        "correction unique_partial object",
        object_partial,
        "manifest.corrections_register.counts.unique_partial",
    )

    def bool_ids(corrections: dict) -> None:
        corrections["counts"]["unique_unresolved_ids"] = False

    public_eval(
        "correction unique_unresolved_ids bool",
        bool_ids,
        "manifest.corrections_register.counts.unique_unresolved_ids",
    )

    def string_ids(corrections: dict) -> None:
        corrections["counts"]["unique_unresolved_ids"] = "C3"

    public_eval(
        "correction unique_unresolved_ids string",
        string_ids,
        "manifest.corrections_register.counts.unique_unresolved_ids",
    )

    def object_ids(corrections: dict) -> None:
        corrections["counts"]["unique_partial_ids"] = {"id": "F-9"}

    public_eval(
        "correction unique_partial_ids object",
        object_ids,
        "manifest.corrections_register.counts.unique_partial_ids",
    )

    def empty_id(corrections: dict) -> None:
        corrections["counts"]["unique_unresolved_ids"] = [""]

    public_eval(
        "correction unique_unresolved_ids empty string",
        empty_id,
        "manifest.corrections_register.counts.unique_unresolved_ids",
    )


def test_rl5_p1_2_cargo_lock_no_sibling_fallback(provenance: dict) -> None:
    sibling = REPO_ROOT.parent / "duckdb-tachiom" / "Cargo.lock"
    candidates = _cargo_lock_candidates(provenance)
    rendered = [str(Path(str(item))) for item in candidates]
    check("hard-coded sibling Cargo.lock is not a candidate", str(sibling) not in rendered, rendered)
    resolved_candidates = []
    for item in candidates:
        path = Path(str(item))
        if path.is_absolute():
            resolved_candidates.append(path.resolve())
        else:
            resolved_candidates.append((REPO_ROOT / path).resolve())
    check(
        "resolved candidates omit sibling Cargo.lock",
        sibling.resolve() not in resolved_candidates,
        resolved_candidates,
    )
    external = (provenance.get("external_not_four_repo") or {}).get("duckdb-tachiom") or {}
    recorded_path = external.get("path")
    if isinstance(recorded_path, str) and Path(recorded_path).is_absolute():
        check(
            "absolute recorded duckdb-tachiom path is not a live Cargo.lock candidate",
            str(Path(recorded_path) / "Cargo.lock") not in rendered,
            rendered,
        )
    cargo_lock, source = _resolve_optional_file(
        CARGO_LOCK_ENV_VARS,
        candidates,
        allow_absolute=False,
    )
    env_set = any(bool(os.environ.get(var)) for var in CARGO_LOCK_ENV_VARS)
    if env_set:
        check("documented env may still resolve Cargo.lock", str(source).startswith("env:"), (cargo_lock, source))
    else:
        check(
            "without env or repo-relative path, Cargo.lock is blocked/skipped",
            source == "absent" and cargo_lock is None,
            (cargo_lock, source),
        )


def test_forged_nearest_attestation_rejected() -> None:
    forged = {
        "schema_version": "flock-rag-nearest-live-verification/1",
        "verifier": "v7.gates.phase0_evaluator.verify_nearest_live",
        "verified": True,
        "live_gate_level": "E2",
        "failure_codes": [],
        "binary_source": "recorded",
        "records_sha256": "a" * 64,
        "observed": {
            "log": {
                "path": NEAREST_LOG_REL,
                "command": NEAREST_COMMAND,
                "cwd": "/synthetic/duckdb-pgagent",
                "exit_code": 0,
                "assertions": 112,
                "test_cases": 1,
                "binary_path": _SYNTHETIC_UNITTEST_PATH,
                "build_commit": DUCKDB_PGAGENT_COMMIT,
                "build_tag": NEAREST_BUILD_TAG,
                "start": "2026-08-29T10:51:08Z",
                "end": "2026-08-29T10:51:09Z",
                "working_tree_clean": True,
            },
            "binary": {
                "sha256": NEAREST_SHA256,
                "size_bytes": NEAREST_SIZE_BYTES,
                "build_identity": {"commit": DUCKDB_PGAGENT_COMMIT, "tag": NEAREST_BUILD_TAG},
            },
        },
    }
    injection_rejected = False
    try:
        evaluate_phase0(REPO_ROOT, nearest_verification=forged)
    except TypeError:
        injection_rejected = True
    check("canonical evaluate_phase0 rejects nearest_verification injection", injection_rejected)
    injection_rejected = False
    try:
        evaluate_phase0(REPO_ROOT, historical_nearest={"schema_version": "x"})
    except TypeError:
        injection_rejected = True
    check("canonical evaluate_phase0 rejects historical_nearest injection", injection_rejected)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived, verification = _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        live_log=False,
        live_binary=False,
    )
    check("short forged verified mapping fails Phase 0", derived["phase0_pass"] is False, derived)
    check("forged mapping is live_evidence", BLOCKER_CLASS_LIVE_EVIDENCE in derived["blocker_classes"], derived)
    check(
        "forged mapping uses stable NEAREST blocker",
        NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "forged mapping does not add other classes when snapshot is otherwise passable",
        derived["blocker_classes"] == [BLOCKER_CLASS_LIVE_EVIDENCE],
        derived,
    )
    check("missing observed log/binary fails Phase 0", derived["phase0_pass"] is False, derived)
    check("collector does not mark absent evidence verified", verification.get("verified") is not True, verification)
    check(
        "collector live_gate_level is coherent when unverified",
        verification.get("live_gate_level") == "blocked" and bool(verification.get("failure_codes")),
        verification,
    )

    contradictory_rejected = False
    try:
        evaluate_phase0(
            REPO_ROOT,
            nearest_verification={
                "verified": True,
                "live_gate_level": "E2",
                "failure_codes": ["LOG_MISSING"],
                "binary_source": "env",
            },
        )
    except TypeError:
        contradictory_rejected = True
    check("verified=true with failure codes cannot be injected", contradictory_rejected)
    check("verified=true with failure codes fails Phase 0", derived["phase0_pass"] is False, derived)
    check("missing records_sha256 fails Phase 0", derived["phase0_pass"] is False, derived)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    manifest["nearest_e2"] = dict(manifest["nearest_e2"])
    manifest["nearest_e2"]["command"] = "forged command"
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("manifest command mutation fails Phase 0", derived["phase0_pass"] is False, derived)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    historical = dict(historical)
    historical["binary_sha256"] = "0" * 64
    derived = _eval_passable_now(manifest, baselines, corrections, provenance, register, historical, nearest)
    check("historical hash mutation fails Phase 0", derived["phase0_pass"] is False, derived)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    derived, verification = _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        live_log=False,
        live_binary=False,
        environ={UNITTEST_BIN_ENV_VARS[0]: "/tmp/pg-agent-not-a-unittest-binary"},
    )
    check("alternate valid-looking binary_source fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "alternate valid-looking binary_source uses stable NEAREST blocker",
        NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check("alternate env source stays unverified", verification.get("verified") is not True, verification)

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    cwd = str(historical["cwd"])
    derived, verification = _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        log_text=_nearest_log_text(cwd=cwd, binary_path=_SYNTHETIC_UNITTEST_PATH, include_commit=False, include_tag=False),
    )
    check("omitted build identity fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "omitted build identity uses stable NEAREST blocker",
        NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"],
        derived["blocker_ids"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    historical = dict(historical)
    historical["binary_path"] = "/forged/elsewhere/unittest"
    manifest = dict(manifest)
    manifest["nearest_e2"] = dict(manifest["nearest_e2"])
    manifest["nearest_e2"]["binary_path"] = "/forged/elsewhere/unittest"
    derived, verification = _run_passable_repo(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
    )
    check("path mismatch fails Phase 0", derived["phase0_pass"] is False, derived)
    check(
        "path mismatch uses stable NEAREST blocker",
        NEAREST_TARGET_E2_UNVERIFIED in derived["blocker_ids"],
        derived["blocker_ids"],
    )
    check(
        "path mismatch records LOG_BINARY_PATH_MISMATCH",
        "LOG_BINARY_PATH_MISMATCH" in (verification.get("failure_codes") or []),
        verification,
    )


def test_release_rejects_malformed_phase0() -> None:
    passable = _evaluate_passable()
    unbound = evaluate_release_gate(passable, _passed_phase_gates(), _passed_e3())
    check("unbound passable Phase 0 is not release-ready", unbound["release_ready"] is False, unbound)
    check("unbound passable Phase 0 is source-unbound", PHASE0_SOURCE_UNBOUND in unbound["blocker_ids"], unbound)
    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    with _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
    ) as session:
        complete = evaluate_release_gate(
            session["result"],
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=session["root"],
            environ=session["environ"],
        )
        check("valid canonical passable Phase 0 can be release-ready", complete["release_ready"] is True, complete)

    def assert_unverified(phase0: dict, label: str) -> None:
        release = evaluate_release_gate(phase0, _passed_phase_gates(), _passed_e3())
        check(f"{label} is not release-ready", release["release_ready"] is False and release["would_pass"] is False, release)
        check(f"{label} blocker is phase0_not_verified", PHASE0_NOT_VERIFIED in release["blocker_ids"], release["blocker_ids"])
        check(
            f"{label} class is phase0_attestation",
            BLOCKER_CLASS_PHASE0_ATTESTATION in release["blocker_classes"],
            release["blocker_classes"],
        )
        reasons = [row for row in release["reasons"] if row.get("blocker_id") == PHASE0_NOT_VERIFIED]
        check(f"{label} reason code is PHASE0_NOT_VERIFIED", reasons and reasons[0].get("code") == "PHASE0_NOT_VERIFIED", reasons)

    forged = dict(passable)
    forged["phase0_pass"] = "false"
    assert_unverified(forged, "string boolean phase0_pass")
    forged = dict(passable)
    forged["schema_version"] = "wrong-schema"
    assert_unverified(forged, "wrong Phase 0 schema")
    forged = dict(passable)
    forged["evaluator"] = "not.the.evaluator"
    assert_unverified(forged, "wrong Phase 0 evaluator")
    forged = dict(passable)
    forged["phase0_pass"] = True
    forged["blocker_ids"] = ["dense_mdenseon"]
    forged["blocker_classes"] = [BLOCKER_CLASS_BLOCKERS]
    forged["reasons"] = [
        {
            "blocker_id": "dense_mdenseon",
            "blocker_class": BLOCKER_CLASS_BLOCKERS,
            "code": "BACKEND_GATE_BLOCKED",
            "details": {"gate": "dense_mdenseon"},
        }
    ]
    assert_unverified(forged, "phase0_pass true with blockers")
    forged = dict(passable)
    forged["phase0_pass"] = False
    assert_unverified(forged, "phase0_pass false with empty blockers")
    forged = dict(passable)
    forged["blocker_ids"] = "dense_mdenseon"
    assert_unverified(forged, "non-list blocker_ids")
    failed = copy.deepcopy(passable)
    failed["phase0_pass"] = False
    failed["blocker_ids"] = ["dense_mdenseon"]
    failed["blocker_classes"] = [BLOCKER_CLASS_BLOCKERS]
    failed["reasons"] = [
        {
            "blocker_id": "dense_mdenseon",
            "blocker_class": BLOCKER_CLASS_BLOCKERS,
            "code": "BACKEND_GATE_BLOCKED",
            "details": {"gate": "dense_mdenseon"},
        }
    ]
    inherited = evaluate_release_gate(failed, _passed_phase_gates(), _passed_e3())
    check("valid failed Phase 0 is not unverified", PHASE0_NOT_VERIFIED not in inherited["blocker_ids"], inherited)
    check("valid failed Phase 0 inherits blocker", "dense_mdenseon" in inherited["blocker_ids"], inherited)
    check("valid failed Phase 0 is not release-ready", inherited["release_ready"] is False, inherited)
    forged = dict(failed)
    forged["blocker_classes"] = ["unknown_class"]
    assert_unverified(forged, "unknown blocker class")
    forged = dict(failed)
    forged["reasons"] = [
        {
            "blocker_id": "dense_mdenseon",
            "blocker_class": BLOCKER_CLASS_BLOCKERS,
            "code": "NOT_A_CODE",
            "details": {},
        }
    ]
    assert_unverified(forged, "unknown reason code")
    forged = dict(failed)
    forged["reasons"] = ["free-form"]
    assert_unverified(forged, "string reason")


def test_rl5_p1_3_nearest_public_boundary() -> None:
    import v7.gates as gates_pkg

    phase0_params = list(inspect.signature(evaluate_phase0).parameters)
    from_repo_params = list(inspect.signature(evaluate_phase0_from_repo).parameters)
    check("public evaluate_phase0 parameters", phase0_params == ["repo_root", "environ"], phase0_params)
    check("evaluate_phase0_from_repo parameters", from_repo_params == ["repo_root", "environ"], from_repo_params)
    check(
        "package __all__ does not export private snapshot helper",
        "_evaluate_phase0_snapshot" not in gates_pkg.__all__,
        gates_pkg.__all__,
    )
    check(
        "package __all__ does not export NEAREST attester",
        "_attest_nearest_verification" not in gates_pkg.__all__,
        gates_pkg.__all__,
    )
    check("public evaluate_phase0 is exported", "evaluate_phase0" in gates_pkg.__all__, gates_pkg.__all__)
    for name, kwargs in (
        ("nearest_verification", {"nearest_verification": {"verified": True}}),
        ("historical_nearest", {"historical_nearest": {"schema_version": "x"}}),
        ("observed", {"observed": {"log": {}, "binary": {}}}),
        ("verified", {"verified": True}),
        ("source_fingerprint", {"source_fingerprint": "0" * 64}),
    ):
        rejected = False
        try:
            evaluate_phase0(REPO_ROOT, **kwargs)
        except TypeError:
            rejected = True
        check(f"public evaluate_phase0 rejects {name} injection", rejected)
        rejected = False
        try:
            evaluate_phase0_from_repo(REPO_ROOT, **kwargs)
        except TypeError:
            rejected = True
        check(f"evaluate_phase0_from_repo rejects {name} injection", rejected)


def test_rl5_p1_4_release_canonical_binding() -> None:
    empty = {
        "schema_version": SCHEMA_VERSION,
        "evaluator": EVALUATOR_ID,
        "phase0_pass": True,
        "blocker_ids": [],
        "blocker_classes": [],
        "reasons": [],
    }
    forged_unbound = evaluate_release_gate(empty, _passed_phase_gates(), _passed_e3())
    check("forged empty projection is not release-ready", forged_unbound["release_ready"] is False, forged_unbound)
    check(
        "forged empty projection is source-unbound",
        PHASE0_SOURCE_UNBOUND in forged_unbound["blocker_ids"],
        forged_unbound["blocker_ids"],
    )

    forged_live = evaluate_release_gate(
        empty, _passed_phase_gates(), _passed_e3(), repo_root=REPO_ROOT
    )
    check(
        "forged empty projection against live repo is not release-ready",
        forged_live["release_ready"] is False,
        forged_live,
    )
    check(
        "forged empty projection is not canonical for live repo",
        PHASE0_NOT_CANONICAL in forged_live["blocker_ids"],
        forged_live["blocker_ids"],
    )
    check(
        "forged empty projection still inherits live Phase 0 blockers",
        "dense_mdenseon" in forged_live["blocker_ids"]
        and "canonical_mineru_contract_version" in forged_live["blocker_ids"]
        and "live_mineru_runtime" not in forged_live["blocker_ids"]
        and len(forged_live["blocker_ids"]) >= 25,
        forged_live["blocker_ids"],
    )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    with _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
    ) as session:
        root = session["root"]
        env = session["environ"]
        phase0 = session["result"]
        check("passable public snapshot passed Phase 0", phase0["phase0_pass"] is True, phase0)
        fingerprint = phase0_source_fingerprint(root, environ=env)
        check("source fingerprint is 64 hex chars", bool(re.fullmatch(r"[0-9a-f]{64}", fingerprint)), fingerprint)
        matching = evaluate_release_gate(
            phase0,
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=root,
            environ=env,
            expected_source_fingerprint=fingerprint,
        )
        check("canonical matching fingerprint can be release-ready", matching["release_ready"] is True, matching)
        from_repo = evaluate_release_from_repo(
            root, _passed_phase_gates(), _passed_e3(), environ=env, expected_source_fingerprint=fingerprint
        )
        check("evaluate_release_from_repo matches bound evaluate_release_gate", from_repo == matching, from_repo)

        stale = evaluate_release_gate(
            phase0,
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=root,
            environ=env,
            expected_source_fingerprint="0" * 64,
        )
        check("stale fingerprint is not release-ready", stale["release_ready"] is False, stale)
        check(
            "stale fingerprint blocker id",
            PHASE0_FINGERPRINT_MISMATCH in stale["blocker_ids"],
            stale["blocker_ids"],
        )

        manifest_path = root / "v7" / "VERSION_MANIFEST.json"
        mutated = json.loads(manifest_path.read_text(encoding="utf-8"))
        gates = dict(mutated.get("backend_gates") or {})
        gates["dense_mdenseon"] = {
            "blocked": True,
            "not_e2": True,
            "evidence_level": "E1",
            "reason": "changed source input",
        }
        mutated["backend_gates"] = gates
        _write_json(manifest_path, mutated)
        changed = evaluate_release_gate(
            phase0,
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=root,
            environ=env,
            expected_source_fingerprint=fingerprint,
        )
        check("changed source input is not release-ready", changed["release_ready"] is False, changed)
        check(
            "changed source input fingerprint mismatches",
            PHASE0_FINGERPRINT_MISMATCH in changed["blocker_ids"],
            changed["blocker_ids"],
        )
        check(
            "changed source input is not canonical for stale projection",
            PHASE0_NOT_CANONICAL in changed["blocker_ids"],
            changed["blocker_ids"],
        )

    manifest, baselines, corrections, provenance, register, historical, nearest = _passable_gate_inputs()
    with _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
    ) as session:
        root = session["root"]
        env = session["environ"]
        phase0 = session["result"]
        wrong_schema = dict(phase0)
        wrong_schema["schema_version"] = "forged-schema/0"
        schema_release = evaluate_release_gate(
            wrong_schema, _passed_phase_gates(), _passed_e3(), repo_root=root, environ=env
        )
        check("wrong Phase 0 schema is not release-ready", schema_release["release_ready"] is False, schema_release)
        check(
            "wrong Phase 0 schema is unverified",
            PHASE0_NOT_VERIFIED in schema_release["blocker_ids"],
            schema_release["blocker_ids"],
        )
        wrong_eval = dict(phase0)
        wrong_eval["evaluator"] = "forged.evaluator"
        eval_release = evaluate_release_gate(
            wrong_eval, _passed_phase_gates(), _passed_e3(), repo_root=root, environ=env
        )
        check("wrong Phase 0 evaluator is not release-ready", eval_release["release_ready"] is False, eval_release)
        check(
            "wrong Phase 0 evaluator is unverified",
            PHASE0_NOT_VERIFIED in eval_release["blocker_ids"],
            eval_release["blocker_ids"],
        )
        original_fp = phase0_source_fingerprint(root, environ=env)
        old_evaluator = phase0_mod.EVALUATOR_ID
        old_schema = phase0_mod.SCHEMA_VERSION
        try:
            phase0_mod.EVALUATOR_ID = "forged.evaluator"
            forged_identity_fp = phase0_source_fingerprint(root, environ=env)
        finally:
            phase0_mod.EVALUATOR_ID = old_evaluator
        check(
            "evaluator identity is in source fingerprint",
            forged_identity_fp != original_fp,
            (original_fp, forged_identity_fp),
        )
        try:
            phase0_mod.SCHEMA_VERSION = "forged-schema/0"
            forged_schema_fp = phase0_source_fingerprint(root, environ=env)
        finally:
            phase0_mod.SCHEMA_VERSION = old_schema
        check(
            "schema identity is in source fingerprint",
            forged_schema_fp != original_fp,
            (original_fp, forged_schema_fp),
        )
        identity_release = evaluate_release_gate(
            phase0,
            _passed_phase_gates(),
            _passed_e3(),
            repo_root=root,
            environ=env,
            expected_source_fingerprint=forged_identity_fp,
        )
        check(
            "forged evaluator fingerprint is not release-ready",
            identity_release["release_ready"] is False,
            identity_release,
        )
        check(
            "forged evaluator fingerprint mismatches",
            PHASE0_FINGERPRINT_MISMATCH in identity_release["blocker_ids"],
            identity_release["blocker_ids"],
        )


def _source_rel_of(path: Path) -> str | None:
    posix = Path(path).as_posix()
    for rel in PHASE0_SOURCE_RELATIVE_PATHS:
        if posix.endswith("/" + rel) or posix.endswith(rel):
            return rel
    return None


def _scripted_source_reader(
    actions: dict[str, dict[int, str]],
    *,
    payload: bytes | None = None,
    on_read=None,
):
    counts: dict[str | None, int] = {}

    def reader(path: Path) -> bytes:
        rel = _source_rel_of(path)
        n = counts.get(rel, 0) + 1
        counts[rel] = n
        if on_read is not None and rel is not None:
            on_read(rel, n, path)
        action = (actions.get(rel) or {}).get(n) if rel is not None else None
        if action == "raise":
            raise OSError("injected source I/O failure")
        if action == "missing":
            try:
                path.unlink()
            except OSError:
                pass
            raise FileNotFoundError(str(path))
        if action == "mutate":
            extra = b"\n" if payload is None else payload
            original = path.read_bytes()
            path.write_bytes(original + extra)
            return path.read_bytes()
        if action == "replace":
            replacement = b'{"forged":true}' if payload is None else payload
            path.write_bytes(replacement)
            return path.read_bytes()
        return path.read_bytes()

    reader.counts = counts  # type: ignore[attr-defined]
    return reader


def _append_file_bytes(path: Path, extra: bytes = b"\n") -> None:
    path.write_bytes(path.read_bytes() + extra)


def _failed_phase0_with_ids(blocker_ids: list[str]) -> dict:
    reasons = [
        {
            "blocker_id": blocker_id,
            "blocker_class": BLOCKER_CLASS_MANIFEST,
            "code": "MANIFEST_FIELD_INVALID",
            "details": {"field": blocker_id},
        }
        for blocker_id in blocker_ids
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluator": EVALUATOR_ID,
        "phase0_pass": False,
        "blocker_ids": list(blocker_ids),
        "blocker_classes": [BLOCKER_CLASS_MANIFEST],
        "reasons": reasons,
    }


def _with_passable_release_session():
    manifest, baselines, corrections, provenance, register, historical, _nearest = _passable_gate_inputs()
    return _passable_repo_session(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        historical,
        public=True,
    )


def test_rl5_p1_4_release_attestation_races() -> None:
    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        att = attest_phase0_from_repo(root, environ=env)
        check("canonical attestation schema", att["schema_version"] == PHASE0_ATTESTATION_SCHEMA, att["schema_version"])
        check("canonical attestation is attested", att["attested"] is True, att)
        check("attestation fingerprint matches independent fingerprint", att["source_fingerprint"] == fingerprint, att)
        check("attestation projection passed Phase 0", att["phase0"]["phase0_pass"] is True, att["phase0"])

        capture_calls = {"n": 0}
        phase0_calls = {"n": 0}
        fingerprint_calls = {"n": 0}
        orig_capture = phase0_mod._capture_phase0_sources
        orig_phase0 = phase0_mod.evaluate_phase0
        orig_fingerprint = phase0_mod.phase0_source_fingerprint

        def wrap_capture(*args, **kwargs):
            capture_calls["n"] += 1
            return orig_capture(*args, **kwargs)

        def wrap_phase0(*args, **kwargs):
            phase0_calls["n"] += 1
            return orig_phase0(*args, **kwargs)

        def wrap_fingerprint(*args, **kwargs):
            fingerprint_calls["n"] += 1
            return orig_fingerprint(*args, **kwargs)

        phase0_mod._capture_phase0_sources = wrap_capture
        phase0_mod.evaluate_phase0 = wrap_phase0
        phase0_mod.phase0_source_fingerprint = wrap_fingerprint
        try:
            from_repo = evaluate_release_from_repo(
                root, _passed_phase_gates(), _passed_e3(), environ=env, expected_source_fingerprint=fingerprint
            )
        finally:
            phase0_mod._capture_phase0_sources = orig_capture
            phase0_mod.evaluate_phase0 = orig_phase0
            phase0_mod.phase0_source_fingerprint = orig_fingerprint
        check("from_repo on stable passable repo is release-ready", from_repo["release_ready"] is True, from_repo)
        check("from_repo captures Phase0 sources for S0/S1/S2", capture_calls["n"] == 3, capture_calls)
        check("from_repo does not call evaluate_phase0", phase0_calls["n"] == 0, phase0_calls)
        check("from_repo does not call phase0_source_fingerprint", fingerprint_calls["n"] == 0, fingerprint_calls)
        check("stable from_repo has no attestation validation errors", release_result_validation_codes(from_repo) == [], from_repo)

        counts: dict[str | None, int] = {}

        def counting_reader(path: Path) -> bytes:
            rel = _source_rel_of(path)
            counts[rel] = counts.get(rel, 0) + 1
            return path.read_bytes()

        attest_phase0_from_repo(root, environ=env, source_reader=counting_reader)
        for rel in PHASE0_SOURCE_RELATIVE_PATHS:
            check(f"attestation S0/S1/S2 reads {rel}", counts.get(rel) == 3, counts)

        observe_calls = {"n": 0}
        orig_observe = phase0_mod._observe_binary

        def wrap_observe(*args, **kwargs):
            observe_calls["n"] += 1
            return orig_observe(*args, **kwargs)

        phase0_mod._observe_binary = wrap_observe
        try:
            binary_stable = evaluate_release_from_repo(
                root, _passed_phase_gates(), _passed_e3(), environ=env, expected_source_fingerprint=fingerprint
            )
        finally:
            phase0_mod._observe_binary = orig_observe
        check("NEAREST binary is observed for eval then confirm", observe_calls["n"] == 2, observe_calls)
        check("stable binary identity remains release-ready", binary_stable["release_ready"] is True, binary_stable)
        check(
            "stable binary identity has no validation errors",
            release_result_validation_codes(binary_stable) == [],
            binary_stable,
        )

    race_cases = (
        ("v7/VERSION_MANIFEST.json", "mutate", "manifest between-read mutate"),
        ("v7/evidence/corrections_register.json", "replace", "corrections between-read replace"),
        ("v7/evidence/nearest_basic.e2.log", "mutate", "log between-read mutate"),
        ("v7/VERSION_MANIFEST.json", "missing", "manifest delete during confirm"),
        ("v7/evidence/four_repo_provenance.json", "raise", "provenance I/O failure during digest"),
        ("v7/evidence/contracts/EVIDENCE_REGISTER.json", "raise_first", "register I/O failure on first read"),
    )
    for rel, action, label in race_cases:
        with _with_passable_release_session() as session:
            root = session["root"]
            env = session["environ"]
            fingerprint = phase0_source_fingerprint(root, environ=env)
            if action == "raise_first":
                reader = _scripted_source_reader({rel: {1: "raise"}})
            else:
                reader = _scripted_source_reader({rel: {2: action}})
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
                source_reader=reader,
            )
            check(f"{label} is not release-ready", raced["release_ready"] is False, raced)
            check(
                f"{label} is source-changed",
                PHASE0_SOURCE_CHANGED in raced["blocker_ids"],
                raced["blocker_ids"],
            )
            check(
                f"{label} class is phase0_attestation",
                BLOCKER_CLASS_PHASE0_ATTESTATION in raced["blocker_classes"],
                raced["blocker_classes"],
            )
            check(
                f"{label} matching expected fingerprint cannot override race",
                raced["release_ready"] is False,
                raced,
            )
            if action == "raise":
                check(
                    f"{label} records SOURCE_UNREADABLE",
                    any(
                        row.get("blocker_id") == PHASE0_SOURCE_CHANGED
                        and "SOURCE_UNREADABLE" in (row.get("details") or {}).get("failure_codes", [])
                        for row in raced["reasons"]
                    ),
                    raced["reasons"],
                )

    def _source_changed_details(raced: dict) -> dict:
        for row in raced["reasons"]:
            if row.get("blocker_id") == PHASE0_SOURCE_CHANGED:
                return row.get("details") or {}
        return {}

    def _assert_raced_blocked(raced: dict, label: str, *, unreadable: bool = False) -> None:
        check(f"{label} does not raise and is not release-ready", raced["release_ready"] is False, raced)
        check(
            f"{label} is source-changed",
            PHASE0_SOURCE_CHANGED in raced["blocker_ids"],
            raced["blocker_ids"],
        )
        check(
            f"{label} class is phase0_attestation",
            BLOCKER_CLASS_PHASE0_ATTESTATION in raced["blocker_classes"],
            raced["blocker_classes"],
        )
        check(
            f"{label} keeps Phase1-7/E3 passed yet release false",
            raced["release_ready"] is False
            and all(raced["phase_gates"][phase_id]["state"] == "PASSED" for phase_id in PHASE_IDS)
            and raced["e3"]["state"] == "PASSED",
            raced,
        )
        check(
            f"{label} matching expected fingerprint cannot override instability",
            raced["release_ready"] is False,
            raced,
        )
        details = _source_changed_details(raced)
        if unreadable:
            check(
                f"{label} records SOURCE_UNREADABLE",
                "SOURCE_UNREADABLE" in (details.get("failure_codes") or []),
                details,
            )
            unread_paths = details.get("unreadable_paths") or []
            check(
                f"{label} lists nearest_binary or binary path as unreadable",
                NEAREST_BINARY_SOURCE_ID in unread_paths
                or any("unittest" in str(item) or str(item).endswith("unittest") for item in unread_paths),
                unread_paths,
            )

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        manifest_rel = "v7/VERSION_MANIFEST.json"
        baseline_rel = "v7/evidence/phase0_baseline_status.json"

        def mutate_manifest_on_later_baseline(rel: str, n: int, path: Path) -> None:
            if rel == baseline_rel and n == 2:
                _append_file_bytes(root / manifest_rel)

        raced = evaluate_release_from_repo(
            root,
            _passed_phase_gates(),
            _passed_e3(),
            environ=env,
            expected_source_fingerprint=fingerprint,
            source_reader=_scripted_source_reader({}, on_read=mutate_manifest_on_later_baseline),
        )
        _assert_raced_blocked(raced, "mutate already-read manifest when later baseline is read on confirmation pass n==2")

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        orig_observe = phase0_mod._observe_binary
        observe_n = {"n": 0}

        def mutate_json_during_b1(*args, **kwargs):
            observe_n["n"] += 1
            if observe_n["n"] == 2:
                _append_file_bytes(root / "v7/VERSION_MANIFEST.json")
            return orig_observe(*args, **kwargs)

        phase0_mod._observe_binary = mutate_json_during_b1
        try:
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
            )
        finally:
            phase0_mod._observe_binary = orig_observe
        _assert_raced_blocked(raced, "mutate earlier source during B1")

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        orig_observe = phase0_mod._observe_binary
        observe_n = {"n": 0}

        def delete_json_during_b1(*args, **kwargs):
            observe_n["n"] += 1
            if observe_n["n"] == 2:
                try:
                    (root / "v7/VERSION_MANIFEST.json").unlink()
                except OSError:
                    pass
            return orig_observe(*args, **kwargs)

        phase0_mod._observe_binary = delete_json_during_b1
        try:
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
            )
        finally:
            phase0_mod._observe_binary = orig_observe
        _assert_raced_blocked(raced, "delete earlier source during B1")

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        orig_capture = phase0_mod._capture_phase0_sources
        capture_n = {"n": 0}

        def mutate_during_s2(*args, **kwargs):
            capture_n["n"] += 1
            if capture_n["n"] == 3:
                _append_file_bytes(root / "v7/VERSION_MANIFEST.json")
            return orig_capture(*args, **kwargs)

        phase0_mod._capture_phase0_sources = mutate_during_s2
        try:
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
            )
        finally:
            phase0_mod._capture_phase0_sources = orig_capture
        _assert_raced_blocked(raced, "mutate earlier source during S2")

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        orig_observe = phase0_mod._observe_binary
        observe_n = {"n": 0}

        def raise_on_b1_observe(*args, **kwargs):
            observe_n["n"] += 1
            if observe_n["n"] == 2:
                raise OSError("injected binary confirm failure")
            return orig_observe(*args, **kwargs)

        phase0_mod._observe_binary = raise_on_b1_observe
        try:
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
            )
        finally:
            phase0_mod._observe_binary = orig_observe
        _assert_raced_blocked(raced, "binary unreadable during B1", unreadable=True)

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        orig_observe = phase0_mod._observe_binary
        observe_n = {"n": 0}

        def binary_read_failed_on_b1(*args, **kwargs):
            observe_n["n"] += 1
            if observe_n["n"] == 2:
                return None, ["BINARY_READ_FAILED"]
            return orig_observe(*args, **kwargs)

        phase0_mod._observe_binary = binary_read_failed_on_b1
        try:
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
            )
        finally:
            phase0_mod._observe_binary = orig_observe
        _assert_raced_blocked(raced, "BINARY_READ_FAILED during B1", unreadable=True)

    with _with_passable_release_session() as session:
        root = session["root"]
        env = session["environ"]
        fingerprint = phase0_source_fingerprint(root, environ=env)
        orig_observe = phase0_mod._observe_binary
        observe_n = {"n": 0}

        def mutate_during_b1_stale_fp(*args, **kwargs):
            observe_n["n"] += 1
            if observe_n["n"] == 2:
                _append_file_bytes(root / "v7/VERSION_MANIFEST.json")
            return orig_observe(*args, **kwargs)

        phase0_mod._observe_binary = mutate_during_b1_stale_fp
        try:
            raced = evaluate_release_from_repo(
                root,
                _passed_phase_gates(),
                _passed_e3(),
                environ=env,
                expected_source_fingerprint=fingerprint,
            )
        finally:
            phase0_mod._observe_binary = orig_observe
        _assert_raced_blocked(
            raced,
            "all phases1-7/E3 passed with stale expected fingerprint matching S0",
        )
        check(
            "matching stale S0 fingerprint does not emit PHASE0_FINGERPRINT_MISMATCH",
            PHASE0_FINGERPRINT_MISMATCH not in raced["blocker_ids"],
            raced["blocker_ids"],
        )
        check(
            "matching stale S0 fingerprint cannot override phase0_source_changed",
            PHASE0_SOURCE_CHANGED in raced["blocker_ids"] and raced["release_ready"] is False,
            raced["blocker_ids"],
        )


def test_rl5_p1_4_release_blocker_sink_and_validation() -> None:
    colliding_ids = [
        PHASE0_NOT_CANONICAL,
        PHASE0_SOURCE_CHANGED,
        "phase_1_not_passed",
        "e3_not_verified",
    ]
    colliding = _failed_phase0_with_ids(colliding_ids)
    release = evaluate_release_gate(colliding, default_phase_gates(), default_e3_state())
    check("colliding inherited IDs are not release-ready", release["release_ready"] is False, release)
    check("colliding inherited IDs have no validation errors", release_result_validation_codes(release) == [], release)
    check(
        "colliding inherited IDs are globally unique",
        len(release["blocker_ids"]) == len(set(release["blocker_ids"])),
        release["blocker_ids"],
    )
    for blocker_id in colliding_ids:
        check(
            f"colliding id {blocker_id} appears once",
            release["blocker_ids"].count(blocker_id) == 1,
            release["blocker_ids"],
        )
    phase1_reason = next(row for row in release["reasons"] if row["blocker_id"] == "phase_1_not_passed")
    check(
        "inherited phase_1_not_passed wins over phase-gate extra",
        phase1_reason["blocker_class"] == BLOCKER_CLASS_MANIFEST,
        phase1_reason,
    )
    e3_reason = next(row for row in release["reasons"] if row["blocker_id"] == "e3_not_verified")
    check(
        "inherited e3_not_verified wins over e3 extra",
        e3_reason["blocker_class"] == BLOCKER_CLASS_MANIFEST,
        e3_reason,
    )
    check(
        "release classes follow RELEASE_BLOCKER_CLASS_ORDER",
        release["blocker_classes"]
        == [cls for cls in RELEASE_BLOCKER_CLASS_ORDER if cls in set(release["blocker_classes"])],
        release["blocker_classes"],
    )
    reason_classes = [row["blocker_class"] for row in release["reasons"]]
    check(
        "release reasons are grouped by class order",
        reason_classes == sorted(reason_classes, key=lambda item: RELEASE_BLOCKER_CLASS_ORDER.index(item)),
        reason_classes,
    )

    sink = release_mod._ReleaseSink()
    sink.add(PHASE0_NOT_CANONICAL, BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "phase0_not_canonical"})
    sink.add(PHASE0_NOT_CANONICAL, BLOCKER_CLASS_PHASE0_ATTESTATION, "PHASE0_NOT_CANONICAL", {"dup": True})
    sink.add(PHASE0_SOURCE_CHANGED, BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "phase0_source_changed"})
    sink.add(PHASE0_SOURCE_CHANGED, BLOCKER_CLASS_PHASE0_ATTESTATION, "PHASE0_SOURCE_CHANGED", {"dup": True})
    sink.add("phase_1_not_passed", BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "phase_1_not_passed"})
    sink.add(
        "phase_1_not_passed",
        BLOCKER_CLASS_PHASE_GATES,
        "PHASE_GATE_NOT_PASSED",
        {"phase": "phase_1"},
    )
    sink.add(
        PHASE0_FINGERPRINT_MISMATCH,
        BLOCKER_CLASS_PHASE0_ATTESTATION,
        "PHASE0_FINGERPRINT_MISMATCH",
        {"expected": "0" * 64, "computed": None},
    )
    ids, classes, reasons = sink.assembled()
    check("sink collapses attestation collisions", ids.count(PHASE0_NOT_CANONICAL) == 1, ids)
    check("sink collapses source-changed collisions", ids.count(PHASE0_SOURCE_CHANGED) == 1, ids)
    check("sink collapses phase-gate collisions", ids.count("phase_1_not_passed") == 1, ids)
    by_id = {row["blocker_id"]: row for row in reasons}
    check(
        "sink first-wins keeps inherited class for phase0_not_canonical",
        by_id[PHASE0_NOT_CANONICAL]["blocker_class"] == BLOCKER_CLASS_MANIFEST,
        by_id[PHASE0_NOT_CANONICAL],
    )
    check(
        "sink first-wins keeps inherited class for phase0_source_changed",
        by_id[PHASE0_SOURCE_CHANGED]["blocker_class"] == BLOCKER_CLASS_MANIFEST,
        by_id[PHASE0_SOURCE_CHANGED],
    )
    check(
        "sink emits attestation class before inherited Phase0 classes",
        classes.index(BLOCKER_CLASS_PHASE0_ATTESTATION) < classes.index(BLOCKER_CLASS_MANIFEST),
        classes,
    )
    check(
        "unique fingerprint extra remains in attestation class",
        by_id[PHASE0_FINGERPRINT_MISMATCH]["blocker_class"] == BLOCKER_CLASS_PHASE0_ATTESTATION,
        by_id[PHASE0_FINGERPRINT_MISMATCH],
    )

    reversed_sink = release_mod._ReleaseSink()
    reversed_sink.add(PHASE0_NOT_CANONICAL, BLOCKER_CLASS_PHASE0_ATTESTATION, "PHASE0_NOT_CANONICAL", {})
    reversed_sink.add(PHASE0_NOT_CANONICAL, BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "later"})
    rev_ids, rev_classes, rev_reasons = reversed_sink.assembled()
    check("attestation-first collision keeps attestation class", rev_ids == [PHASE0_NOT_CANONICAL], rev_ids)
    check(
        "attestation-first collision class is phase0_attestation",
        rev_reasons[0]["blocker_class"] == BLOCKER_CLASS_PHASE0_ATTESTATION,
        rev_reasons,
    )
    check("attestation-first collision class order", rev_classes == [BLOCKER_CLASS_PHASE0_ATTESTATION], rev_classes)

    dup = copy.deepcopy(release)
    dup["blocker_ids"] = list(dup["blocker_ids"]) + [dup["blocker_ids"][0]]
    dup["reasons"] = list(dup["reasons"]) + [copy.deepcopy(dup["reasons"][0])]
    dup_codes = release_result_validation_codes(dup)
    check("duplicate blocker id is reported", "RELEASE_BLOCKER_ID_DUPLICATE" in dup_codes, dup_codes)

    reordered = copy.deepcopy(release)
    reordered["blocker_classes"] = list(reversed(list(reordered["blocker_classes"])))
    order_codes = release_result_validation_codes(reordered)
    check("reversed class list is reported", "RELEASE_CLASS_ORDER_INVALID" in order_codes, order_codes)

    misaligned = copy.deepcopy(release)
    misaligned["reasons"] = list(reversed(list(misaligned["reasons"])))
    align_codes = release_result_validation_codes(misaligned)
    check(
        "reversed reasons are reported",
        "RELEASE_REASON_ALIGNMENT_INVALID" in align_codes or "RELEASE_CLASS_ORDER_INVALID" in align_codes,
        align_codes,
    )

    live = evaluate_release_gate(evaluate_phase0(REPO_ROOT), default_phase_gates(), default_e3_state(), repo_root=REPO_ROOT)
    check("live bound release has no validation errors", release_result_validation_codes(live) == [], live)
    check("live bound release is not ready", live["release_ready"] is False, live)

    missing_phase0 = copy.deepcopy(live)
    del missing_phase0["phase0"]
    check(
        "deleted nested phase0 projection is reported",
        "RELEASE_PHASE0_PROJECTION_MISSING" in release_result_validation_codes(missing_phase0),
        release_result_validation_codes(missing_phase0),
    )
    replaced_phase0 = copy.deepcopy(live)
    replaced_phase0["phase0"] = []
    check(
        "replaced nested phase0 projection is reported",
        "RELEASE_PHASE0_PROJECTION_INVALID" in release_result_validation_codes(replaced_phase0),
        release_result_validation_codes(replaced_phase0),
    )
    malformed_phase0 = copy.deepcopy(live)
    malformed_phase0["phase0"] = dict(live["phase0"])
    malformed_phase0["phase0"]["phase0_pass"] = "false"
    check(
        "malformed nested phase0 projection is reported",
        "RELEASE_PHASE0_PROJECTION_INVALID" in release_result_validation_codes(malformed_phase0),
        release_result_validation_codes(malformed_phase0),
    )
    missing_gates = copy.deepcopy(live)
    del missing_gates["phase_gates"]
    check(
        "deleted phase_gates is reported",
        "RELEASE_PHASE_GATES_MISSING" in release_result_validation_codes(missing_gates),
        release_result_validation_codes(missing_gates),
    )
    replaced_gates = copy.deepcopy(live)
    replaced_gates["phase_gates"] = []
    check(
        "replaced phase_gates is reported",
        "RELEASE_PHASE_GATES_INVALID" in release_result_validation_codes(replaced_gates),
        release_result_validation_codes(replaced_gates),
    )
    incomplete_gates = copy.deepcopy(live)
    incomplete_gates["phase_gates"] = dict(live["phase_gates"])
    del incomplete_gates["phase_gates"]["phase_4"]
    check(
        "incomplete Phase1-7 mapping is reported",
        "RELEASE_PHASE_GATES_INVALID" in release_result_validation_codes(incomplete_gates),
        release_result_validation_codes(incomplete_gates),
    )
    malformed_gate_state = copy.deepcopy(live)
    malformed_gate_state["phase_gates"] = dict(live["phase_gates"])
    malformed_gate_state["phase_gates"]["phase_2"] = dict(live["phase_gates"]["phase_2"])
    malformed_gate_state["phase_gates"]["phase_2"]["exit_criteria_passed"] = 1
    check(
        "malformed phase-gate exit field is reported",
        "RELEASE_PHASE_GATES_INVALID" in release_result_validation_codes(malformed_gate_state),
        release_result_validation_codes(malformed_gate_state),
    )
    missing_e3 = copy.deepcopy(live)
    del missing_e3["e3"]
    check(
        "deleted e3 is reported",
        "RELEASE_E3_MISSING" in release_result_validation_codes(missing_e3),
        release_result_validation_codes(missing_e3),
    )
    replaced_e3 = copy.deepcopy(live)
    replaced_e3["e3"] = "PASSED"
    check(
        "replaced e3 is reported",
        "RELEASE_E3_INVALID" in release_result_validation_codes(replaced_e3),
        release_result_validation_codes(replaced_e3),
    )
    malformed_e3 = copy.deepcopy(live)
    malformed_e3["e3"] = dict(live["e3"])
    malformed_e3["e3"]["state"] = ["PASSED"]
    check(
        "malformed e3 state is reported",
        "RELEASE_E3_INVALID" in release_result_validation_codes(malformed_e3),
        release_result_validation_codes(malformed_e3),
    )
    nested_codes = release_result_validation_codes(missing_phase0)
    check(
        "nested validation preserves ordered/dedup sink",
        nested_codes == [code for code in release_mod.RELEASE_RESULT_CODES if code in nested_codes]
        and len(nested_codes) == len(set(nested_codes)),
        nested_codes,
    )


def test_readme_inventory() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    for needle in (
        "VERSION_MANIFEST.json",
        "corrections_register.json",
        "phase0_baseline_status.json",
        "legacy_cache",
        "NEAREST",
        "blocked",
        "synthetic",
        "E1",
        "E2",
        "E0",
        "E3",
        "Phase 1",
        "infinisynapse",
        "tachiom",
        "mdenseon",
        "MinerU",
        "Kohaku",
    ):
        check(f"README mentions {needle}", needle in text, needle)
    check("README does not claim Phase 0 pass", "Phase 0 is not a pass" in text or "Phase 0 has not passed" in text)
    check("README does not claim Phase 0 is E3", "not claimed in Phase 0" in text or "Phase 0 is not E3" in text)


def main() -> int:
    manifest = _load_json(MANIFEST_PATH)
    provenance = _load_json(PROVENANCE_PATH)
    register = _load_json(REGISTER_PATH)
    corrections = _load_json(CORRECTIONS_PATH)
    baselines = _load_json(BASELINE_PATH)
    test_required_section_32_keys(manifest)
    test_duckdb_pgagent_pin(manifest)
    test_four_repo_commits_match(manifest, provenance)
    test_commit_tag_vendored_identity(manifest)
    test_tachiom_build_identity_is_cargo_resolved(manifest, provenance)
    test_null_required_hashes_are_honest(manifest)
    test_production_mineru_hashes_remain_required_null(manifest)
    test_mineru_snapshot_identity_pins(manifest)
    test_recursive_nested_completeness(manifest)
    test_lock_copied_values_match_register(manifest, register)
    test_live_absent_backends_stay_blocked(manifest, baselines)
    test_evidence_register_ids(register)
    test_authority_does_not_claim_all_corrections_absorbed()
    test_corrections_register_matches_traceability(corrections)
    test_derived_gates(manifest, baselines, corrections, provenance, register)
    test_gate_relational_blocker_classes()
    test_gate_mutations()
    test_mineru_not_applicable_allowlist()
    test_evaluator_owns_provenance_and_pins()
    test_evaluator_provenance_relationships()
    test_evaluator_remaining_identity_relationships()
    test_evaluator_schema_cross_field_and_register_mutations()
    test_rl5_p1_2_ce289b_mutations()
    test_rl5_p1_2_4f1ae1_mutations()
    test_rl5_p1_2_fail_closed_enum_scalar_mutations()
    test_rl5_p1_2_consistency_fail_closed()
    test_rl5_p1_2_bm25_config_hash_alias()
    test_rl5_p1_2_supported_status_schema_mutations()
    test_rl5_p1_2_release_phase_e3_enum_mutations()
    test_malformed_nested_objects_block()
    test_baseline_relationship_mutations()
    test_register_and_correction_schema_mutations()
    test_rl5_p1_2_correction_alias_graph()
    test_rl5_p1_2_correction_count_types()
    test_rl5_p1_2_nearest_hermetic_recorded_path()
    test_rl5_p1_2_nearest_log_parser_mutations()
    test_rl5_p1_2_nearest_relative_env_independent_of_cwd()
    test_rl5_p1_2_cargo_lock_no_sibling_fallback(provenance)
    test_forged_nearest_attestation_rejected()
    test_rl5_p1_3_nearest_public_boundary()
    test_release_rejects_malformed_phase0()
    test_rl5_p1_4_release_canonical_binding()
    test_rl5_p1_4_release_attestation_races()
    test_rl5_p1_4_release_blocker_sink_and_validation()
    test_phase0_baselines(baselines)
    test_infinisynapse_workflow_vs_exact_dto(register)
    test_nearest_binary_hash(manifest, register)
    test_nearest_missing_binary_or_log_downgrades()
    test_e3_defined_and_phase0_is_not_e3(register, baselines, manifest)
    test_readme_inventory()
    print("[version_manifest] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
