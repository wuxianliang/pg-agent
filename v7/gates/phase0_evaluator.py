"""Canonical Phase 0 evaluator.

Synchronous, read-only, deterministic for a fixed repository/evidence snapshot.
The public entry point is evaluate_phase0(repo_root, environ=...). It loads Phase 0
JSON from the repository and acquires NEAREST log/binary observations itself.
Does not acquire artifacts, run tests, or write evidence files.

Release attestation (attest_phase0_from_repo) uses a bracketed fail-closed
linearization protocol around the complete operation:

  S0 capture all Phase 0 sources into immutable bytes
  B0 materialize/evaluate from S0 bytes and observe the NEAREST binary
  S1 confirm all sources (complete capture, then compare)
  B1 observe the NEAREST binary
  S2 confirm all sources (complete capture, then compare)
  require S0 == S1 == S2 and B0 == B1

Linearization point: the last completed S2 source capture. The evaluated S0
bytes and B0 binary identity are attested only if that equality holds.
Finite rereads do not claim detection of mutations after S2 returns, including
after function return. Confirm-time binary I/O or path-resolution failures are
SOURCE_UNREADABLE (plus SOURCE_CHANGED), never changed-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from v7.mineru.contracts import MINERU_PARSER_EXPECTED

SCHEMA_VERSION = "flock-rag-phase0-baseline-status/3"
EVALUATOR_ID = "v7.gates.phase0_evaluator"
MANIFEST_KIND = "v7_build_model_artifact"

SECTION_32_REQUIRED_FIELDS = [
    "pg_agent_commit",
    "flock_commit",
    "duckdb_pgagent_commit",
    "duckdb_python_pgagent_commit",
    "duckdb_engine_version",
    "build_flags",
    "python_version",
    "platform_architecture",
    "flock_abi_catalog_version",
    "mineru_runtime_distribution_version",
    "mineru_container_image_digest",
    "mineru_model_name_version_weights_hash",
    "mineru_parser_config",
    "canonical_mineru_contract_version",
    "mdenseon_package_native_runtime_version",
    "mdenseon_model_weights_sha256",
    "tokenizer_identity_version_hash",
    "embedding_dimension_dtype_normalization_batch",
    "tachiom_commit",
    "duckdb_tachiom_commit",
    "tachiom_static_loadable_artifact_sha256",
    "tachiom_index_format_version",
    "fts_extension_version",
    "bm25_tokenizer_stemming_stopword_casefolding_unicode_config_hash",
    "build_artifact_wheel_sha256",
]

REQUIRED_HASH_FIELDS = [
    "mineru_container_image_digest",
    "mineru_model_name_version_weights_hash",
    "mdenseon_model_weights_sha256",
    "tokenizer_identity_version_hash",
    "tachiom_static_loadable_artifact_sha256",
    "bm25_tokenizer_stemming_stopword_casefolding_unicode_config_hash",
    "build_artifact_wheel_sha256",
]

NOT_APPLICABLE_STATUS = "not_applicable"
NOT_APPLICABLE_HASH_PATHS = frozenset({
    "mineru_container_image_digest",
    "mineru_model_name_version_weights_hash.single_file_weights_sha256",
    "mineru_model_weights_sha256",
})

FOUR_REPO_COMMIT_KEYS = [
    ("pg-agent", "pg_agent_commit"),
    ("flock", "flock_commit"),
    ("duckdb-pgagent", "duckdb_pgagent_commit"),
    ("duckdb-python-pgagent", "duckdb_python_pgagent_commit"),
]

FOUR_REPO_TAG_KEYS = [
    ("pg-agent", "pg_agent_tag"),
    ("flock", "flock_tag"),
    ("duckdb-pgagent", "duckdb_pgagent_tag"),
    ("duckdb-python-pgagent", "duckdb_python_pgagent_tag"),
]

COMMIT_40_KEYS = [
    "pg_agent_commit",
    "flock_commit",
    "duckdb_pgagent_commit",
    "duckdb_python_pgagent_commit",
    "tachiom_commit",
    "duckdb_tachiom_commit",
]

TAG_COMMIT_PAIRS = [
    ("duckdb_pgagent_tag", "duckdb_pgagent_tag_commit", "duckdb_pgagent_commit"),
    ("duckdb_python_pgagent_tag", "duckdb_python_pgagent_tag_commit", "duckdb_python_pgagent_commit"),
    ("tachiom_tag", "tachiom_tag_commit", "tachiom_commit"),
]

REQUIRED_CONTRACT_SPECS = [
    {
        "id": "mineru",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/mineru.md",
        "related_backend": "mineru_ingest",
    },
    {
        "id": "kohakurag",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/kohakurag.md",
        "related_backend": "text_catalog_tree",
    },
    {
        "id": "mdenseon",
        "level": "E1",
        "backend_blocked": True,
        "path": "v7/evidence/contracts/mdenseon.md",
        "related_backend": "dense_mdenseon",
    },
    {
        "id": "tachiom",
        "level": "E1",
        "backend_blocked": True,
        "path": "v7/evidence/contracts/tachiom.md",
        "related_backend": "multi_vector_tachiom",
    },
    {
        "id": "auto_coder_longcontext",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/auto_coder_longcontext.md",
        "related_backend": "longcontext_python",
    },
    {
        "id": "infinisynapse_schema",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/infinisynapse_schema.md",
        "related_backend": "schema_rag_workflow",
    },
    {
        "id": "infinisynapse_exact_dto",
        "level": "E0",
        "backend_blocked": True,
        "path": "v7/evidence/contracts/infinisynapse_schema.md",
        "related_backend": "schema_rag_exact_dto",
    },
    {
        "id": "owner_live_file",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/owner_live_file.md",
        "related_backend": "deployment_owner_runtime",
    },
    {
        "id": "temp_candidate_stage",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/temp_candidate_stage.md",
        "related_backend": "flock_ranking",
    },
    {
        "id": "line_range_mapping",
        "level": "E1",
        "backend_blocked": False,
        "path": "v7/evidence/contracts/line_range_mapping.md",
        "related_backend": "text_catalog_ranges",
    },
    {
        "id": "nearest_basic",
        "level": "E2",
        "backend_blocked": False,
        "path": "v7/evidence/nearest_e2_summary.md",
        "related_backend": "dense_nearest",
    },
]
REQUIRED_CONTRACT_IDS = [spec["id"] for spec in REQUIRED_CONTRACT_SPECS]
REQUIRED_CONTRACT_SPEC_BY_ID = {spec["id"]: spec for spec in REQUIRED_CONTRACT_SPECS}

BASELINE_RELATIONS = (
    {
        "baseline_id": "live_legacy_cache",
        "backend_gate": "legacy_cache_live",
        "contract_id": None,
        "concern": "live_only",
        "required_evidence_level": "E2",
    },
    {
        "baseline_id": "kohaku_tree_fixtures",
        "backend_gate": "kohaku_tree_acceptance",
        "contract_id": "kohakurag",
        "concern": "separate",
        "required_evidence_level": "E2",
        "contract_component_kind": "types",
        "live_or_fixture_component_kind": "fixtures",
    },
    {
        "baseline_id": "kohaku_mineru_range_trio",
        "backend_gate": "range_trio_acceptance",
        "contract_id": "line_range_mapping",
        "concern": "separate",
        "required_evidence_level": "E2",
        "contract_component_kind": "rules",
        "live_or_fixture_component_kind": "fixtures",
    },
    {
        "baseline_id": "live_mineru_runtime",
        "backend_gate": "live_mineru_runtime",
        "contract_id": "mineru",
        "concern": "separate",
        "required_evidence_level": "E2",
        "contract_component_kind": "json",
        "live_or_fixture_component_kind": "runtime",
        "phase0_pass_required": False,
    },
    {
        "baseline_id": "live_mdenseon",
        "backend_gate": "dense_mdenseon",
        "contract_id": "mdenseon",
        "concern": "identical",
        "required_evidence_level": "E2",
        "contract_component_kind": "lock",
        "live_or_fixture_component_kind": "bytes",
    },
    {
        "baseline_id": "target_tachiom_static_artifact",
        "backend_gate": "multi_vector_tachiom",
        "contract_id": "tachiom",
        "concern": "identical",
        "required_evidence_level": "E2",
        "contract_component_kind": "sql",
        "live_or_fixture_component_kind": "target_artifact",
    },
)
REQUIRED_BASELINE_IDS = [spec["baseline_id"] for spec in BASELINE_RELATIONS]
BASELINE_RELATION_BY_ID = {spec["baseline_id"]: spec for spec in BASELINE_RELATIONS}
LIVE_MISSING_TO_GATE = {spec["baseline_id"]: spec["backend_gate"] for spec in BASELINE_RELATIONS}
IDENTICAL_CONCERN_CONTRACT_IDS = {
    spec["contract_id"]
    for spec in BASELINE_RELATIONS
    if spec["concern"] == "identical" and spec["contract_id"]
}

BASELINE_BOOL_FIELDS = [
    "contract_frozen",
    "acceptance_fixture_missing",
    "live_runtime_missing",
    "implementation_allowed",
    "release_allowed",
]

REQUIRED_BACKEND_GATES = [
    "dense_mdenseon",
    "multi_vector_tachiom",
    "live_mineru_runtime",
    "mineru_json_ingest",
    "legacy_cache_live",
    "kohaku_tree_acceptance",
    "range_trio_acceptance",
]
PHASE0_PASS_EXEMPT_BACKEND_GATES = frozenset({"live_mineru_runtime"})

STATIC_BUILD_REQUIRED_KEYS = [
    "flock_static",
    "flock_loadable",
    "fts_static",
    "fts_loadable",
    "tachiom_static_cmake",
    "python_module",
]

STATIC_BUILD_EXPECTED = {
    "flock_static": "flock_extension",
    "flock_loadable": "flock_loadable_extension",
    "fts_static": "fts_extension",
    "fts_loadable": "fts_loadable_extension",
    "python_module": "_duckdb",
}

REQUIRED_V7_EXTENSIONS = ["flock_extension", "fts_extension"]

CONFIG_GAP_IDS = [
    "flock_abi_catalog_version",
    "canonical_mineru_contract_version",
    "embedding_batch_contract",
    "tachiom_static_cmake_target",
    "v7_python_wheel",
]

UNIQUE_UNRESOLVED_IDS = ["C3", "DR-PO-1", "DR-PO-2", "DR-PO-3"]
UNIQUE_PARTIAL_IDS = ["F-9", "F-12", "C5", "C6", "C7", "DR-SEC-4", "DR-T-2"]
OPEN_CORRECTION_STATUSES = {"UNRESOLVED", "PARTIAL"}
CORRECTION_STATUSES = {"ABSORBED", "PARTIAL", "UNRESOLVED"}

BLOCKER_CLASS_MANIFEST = "manifest_contract"
BLOCKER_CLASS_BLOCKERS = "blockers"
BLOCKER_CLASS_MISSING_BASELINES = "missing_baselines"
BLOCKER_CLASS_OPEN_CORRECTIONS = "open_corrections"
BLOCKER_CLASS_REQUIRED_NULL_HASHES = "required_null_hashes"
BLOCKER_CLASS_CONFIGURATION = "configuration_gaps"
BLOCKER_CLASS_DIRTY_UNINITIALIZED = "dirty_uninitialized_dependencies"
BLOCKER_CLASS_LIVE_EVIDENCE = "live_evidence"

PHASE0_BLOCKER_CLASS_ORDER = [
    BLOCKER_CLASS_MANIFEST,
    BLOCKER_CLASS_BLOCKERS,
    BLOCKER_CLASS_MISSING_BASELINES,
    BLOCKER_CLASS_OPEN_CORRECTIONS,
    BLOCKER_CLASS_REQUIRED_NULL_HASHES,
    BLOCKER_CLASS_CONFIGURATION,
    BLOCKER_CLASS_DIRTY_UNINITIALIZED,
    BLOCKER_CLASS_LIVE_EVIDENCE,
]

REASON_CODES = {
    "MANIFEST_FIELD_MISSING",
    "MANIFEST_FIELD_INVALID",
    "MANIFEST_HASH_NULL",
    "MANIFEST_HASH_FORMAT_INVALID",
    "MANIFEST_STATUS_INVALID",
    "BACKEND_GATE_BLOCKED",
    "BASELINE_MISSING_OR_UNAVAILABLE",
    "OPEN_CORRECTION",
    "REQUIRED_HASH_UNAVAILABLE",
    "CONFIG_UNRESOLVED",
    "DEPENDENCY_DIRTY_OR_UNINITIALIZED",
    "NEAREST_E2_UNVERIFIED",
}

PHASE0_RESULT_CODES = [
    "PHASE0_RESULT_NOT_OBJECT",
    "PHASE0_SCHEMA_VERSION_INVALID",
    "PHASE0_EVALUATOR_INVALID",
    "PHASE0_PASS_TYPE_INVALID",
    "PHASE0_BLOCKER_IDS_INVALID",
    "PHASE0_BLOCKER_CLASSES_INVALID",
    "PHASE0_REASONS_INVALID",
    "PHASE0_BLOCKER_ID_DUPLICATE",
    "PHASE0_CLASS_ORDER_INVALID",
    "PHASE0_REASON_ALIGNMENT_INVALID",
    "PHASE0_PASS_CONTRADICTS_BLOCKERS",
]

NEAREST_FAILURE_CODES = [
    "ATTESTATION_SCHEMA_INVALID",
    "MANIFEST_RECORD_INVALID",
    "HISTORICAL_RECORD_INVALID",
    "RECORD_FIELD_MISMATCH",
    "LOG_MISSING",
    "LOG_EMPTY",
    "LOG_MALFORMED",
    "LOG_COMMAND_MISMATCH",
    "LOG_CWD_MISMATCH",
    "LOG_EXIT_CODE_MISMATCH",
    "LOG_ASSERTION_COUNT_MISMATCH",
    "LOG_BINARY_PATH_MISMATCH",
    "LOG_BUILD_IDENTITY_MISMATCH",
    "BINARY_PATH_UNRESOLVED",
    "BINARY_READ_FAILED",
    "BINARY_SHA256_MISMATCH",
    "BINARY_SIZE_MISMATCH",
    "BINARY_BUILD_IDENTITY_MISMATCH",
]

NEAREST_TARGET_E2_UNVERIFIED = "nearest_target_e2_unverified"
NEAREST_SHA256 = "2924bc6ce716b2363c218c28e4418ad57c7e800f735cf0bd4520baf7df8519b8"
NEAREST_SIZE_BYTES = 11567456
NEAREST_LOG_REL = "v7/evidence/nearest_basic.e2.log"
NEAREST_ASSERTIONS = 112
NEAREST_EXIT_CODE = 0
NEAREST_TEST_NAME = "nearest_basic.test"
NEAREST_COMMAND = "./build/reldebug/test/unittest test/sql/join/nearest/nearest_basic.test"
NEAREST_BUILD_TAG = "duckdb-special-20260829-g1"
DUCKDB_PGAGENT_COMMIT = "a1f0ab191185c0852b162adc6feb206822dc9daa"
TACHIOM_TAG = "v0.3.4"
TACHIOM_TAG_COMMIT = "2d1b2050d60eb28462f9d9c451c2fe7653cc4aa9"
FLOCK_EXTENSION_CI_TOOLS_COMMIT = "b777c70d30942cca5bef62d6d4fa23a13362f398"
FLOCK_SUBMODULE_OK_GITLINKS = {
    "duckdb": DUCKDB_PGAGENT_COMMIT,
    "extension-ci-tools": FLOCK_EXTENSION_CI_TOOLS_COMMIT,
}
UNITTEST_BIN_ENV_VARS = ("PG_AGENT_UNITTEST_BIN", "DUCKDB_PGAGENT_UNITTEST")
NEAREST_LIVE_BINARY_RELPATH_FILE = "v7/evidence/nearest_live_binary.relpath"
NEAREST_VERIFICATION_SCHEMA = "flock-rag-nearest-live-verification/1"
NEAREST_VERIFIER_ID = "v7.gates.phase0_evaluator.verify_nearest_live"
SOURCE_FINGERPRINT_SCHEMA = "flock-rag-phase0-source-fingerprint/1"
PHASE0_ATTESTATION_SCHEMA = "flock-rag-phase0-attestation/1"
PHASE0_SOURCE_RELATIVE_PATHS = (
    "v7/VERSION_MANIFEST.json",
    "v7/evidence/phase0_baseline_status.json",
    "v7/evidence/corrections_register.json",
    "v7/evidence/four_repo_provenance.json",
    "v7/evidence/contracts/EVIDENCE_REGISTER.json",
    "v7/evidence/nearest_e2.json",
    NEAREST_LOG_REL,
)
ATTESTATION_FAILURE_CODES = (
    "SOURCE_CHANGED",
    "SOURCE_UNREADABLE",
)
NEAREST_HISTORICAL_SCHEMA = "flock-rag-phase0-nearest-e2/1"
EVIDENCE_REGISTER_SCHEMA = "flock-rag-phase0-evidence-register/1"

NEAREST_SHARED_FIELDS = [
    "evidence_level",
    "command",
    "cwd",
    "exit_code",
    "assertions",
    "log",
    "binary_path",
    "binary_sha256",
    "binary_size_bytes",
    "binary_file_type",
    "binary_mtime_local",
    "build_identity_commit",
    "build_identity_tag",
]
NEAREST_VERIFICATION_SHARED_FIELDS = [
    "binary_required_for_live_e2",
    "log_required_for_live_e2",
    "absent_binary_or_log_gate_level",
]

RECORDED_COMPLETENESS = {"recorded", "recorded_from_lock", "recorded_e1"}
ALLOWED_COMPLETENESS = RECORDED_COMPLETENESS | {"blocked", "partial", "missing", NOT_APPLICABLE_STATUS}
RECORDED_FROM_LOCK_LIVE_FILES_ABSENT = "recorded_from_lock_live_files_absent"
NULLABLE_HASH_STATUS_TOKENS = ALLOWED_COMPLETENESS | {RECORDED_FROM_LOCK_LIVE_FILES_ABSENT}
ALLOWED_EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3"}
EVIDENCE_RANK = {"E0": 0, "E1": 1, "E2": 2, "E3": 3}
ALLOWED_CONTRACT_COMPONENT_KINDS = {"types", "rules", "json", "lock", "sql"}
ALLOWED_LIVE_OR_FIXTURE_COMPONENT_KINDS = {"fixtures", "runtime", "bytes", "target_artifact", "live_cache"}

MINERU_RUNTIME_DISTRIBUTION_VERSION = "3.4.4"
MINERU_WHEEL_SHA256 = "d4d678539782a7683d998e2914a52d96b5720676ce65658b29666b1f4d9dfd13"
MDENSEON_EXPECTED_DIMENSION = 768
MDENSEON_EXPECTED_DTYPE = "float32"
TACHIOM_INDEX_FORMAT_VERSION = 1

REGISTER_ROW_REQUIRED_KEYS = (
    "id",
    "path",
    "level",
    "related_backend",
    "backend_blocked",
    "backend_blocked_reason",
    "notes",
    "paths_read",
    "blockers",
)

BM25_SIBLING_KEYS = [
    "bm25_tokenizer",
    "bm25_stemming",
    "bm25_stop_words",
    "bm25_case_folding",
    "bm25_unicode_normalization",
    "bm25_field_weights",
    "bm25_backend_version",
]
BM25_COMPOSITE_KEY = "bm25_tokenizer_stemming_stopword_casefolding_unicode_config_hash"
BM25_CONFIG_HASH_KEY = "bm25_config_hash"

TOKENIZER_TOP_TO_NESTED = {
    "tokenizer_identity": "identity",
    "tokenizer_version": "version",
    "tokenizer_hash": "lfs_sha256",
}
EMBEDDING_TOP_TO_NESTED = {
    "embedding_dimension": "dimension",
    "embedding_dtype": "dtype",
    "embedding_normalization": "normalization",
    "embedding_zero_norm_policy": "zero_norm_policy",
    "embedding_batch_contract": "batch_contract",
}
MINERU_TOP_TO_NESTED = {
    "mineru_model_name": "name",
    "mineru_model_version": "version",
    "mineru_model_snapshot_manifest_sha256": "snapshot_manifest_sha256",
}

SCALAR_HASH_FIELDS = {
    "mdenseon_model_weights_sha256",
    "tachiom_static_loadable_artifact_sha256",
    BM25_COMPOSITE_KEY,
    "build_artifact_wheel_sha256",
}
DIGEST_FIELDS = {"mineru_container_image_digest"}
MAPPING_HASH_FIELDS = {
    "mineru_model_name_version_weights_hash",
    "tokenizer_identity_version_hash",
}

SECTION_32_SCHEMA: dict[str, dict[str, Any]] = {
    "pg_agent_commit": {"kind": "commit"},
    "flock_commit": {"kind": "commit"},
    "duckdb_pgagent_commit": {"kind": "commit"},
    "duckdb_python_pgagent_commit": {"kind": "commit"},
    "duckdb_engine_version": {"kind": "str"},
    "build_flags": {"kind": "mapping"},
    "python_version": {"kind": "str"},
    "platform_architecture": {"kind": "str"},
    "flock_abi_catalog_version": {"kind": "str", "null_ok": True},
    "mineru_runtime_distribution_version": {"kind": "str", "equals": MINERU_RUNTIME_DISTRIBUTION_VERSION},
    "mineru_container_image_digest": {"kind": "digest", "null_ok": True},
    "mineru_model_name_version_weights_hash": {"kind": "mapping"},
    "mineru_parser_config": {"kind": "mapping"},
    "canonical_mineru_contract_version": {"kind": "str", "null_ok": True},
    "mdenseon_package_native_runtime_version": {"kind": "mapping"},
    "mdenseon_model_weights_sha256": {"kind": "sha256", "null_ok": True},
    "tokenizer_identity_version_hash": {"kind": "mapping"},
    "embedding_dimension_dtype_normalization_batch": {"kind": "mapping"},
    "tachiom_commit": {"kind": "commit"},
    "duckdb_tachiom_commit": {"kind": "commit"},
    "tachiom_static_loadable_artifact_sha256": {"kind": "sha256", "null_ok": True},
    "tachiom_index_format_version": {"kind": "int", "equals": TACHIOM_INDEX_FORMAT_VERSION},
    "fts_extension_version": {"kind": "commit"},
    BM25_COMPOSITE_KEY: {"kind": "sha256", "null_ok": True},
    "build_artifact_wheel_sha256": {"kind": "sha256", "null_ok": True},
}

NESTED_REQUIRED_LEAVES: dict[str, dict[str, dict[str, Any]]] = {
    "mineru_parser_config": {
        "backend": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["backend"]},
        "method": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["method"]},
        "cli": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["cli"]},
        "canonical_surface": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["canonical_surface"]},
        "page_idx": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["page_idx"]},
        "catalog_page": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["catalog_page"]},
        "bbox": {"kind": "str", "equals": MINERU_PARSER_EXPECTED["bbox"]},
        "formula": {"kind": "bool", "equals": MINERU_PARSER_EXPECTED["formula"]},
        "table": {"kind": "bool", "equals": MINERU_PARSER_EXPECTED["table"]},
        "env": {"kind": "mapping"},
        "required_artifacts": {"kind": "str_list"},
    },
    "mineru_model_name_version_weights_hash": {
        "name": {"kind": "str"},
        "version": {"kind": "str"},
        "snapshot_manifest_sha256": {"kind": "sha256"},
        "single_file_weights_sha256": {"kind": "sha256", "null_ok": True},
    },
    "mdenseon_package_native_runtime_version": {key: {"kind": "str"} for key in [
        "model_id",
        "revision",
        "source",
        "library_name",
        "lock_format",
        "expected_python",
    ]},
    "tokenizer_identity_version_hash": {
        "identity": {"kind": "str"},
        "version": {"kind": "str"},
        "lfs_sha256": {"kind": "sha256"},
    },
    "embedding_dimension_dtype_normalization_batch": {
        "dimension": {"kind": "positive_int"},
        "dtype": {"kind": "str"},
        "normalization": {"kind": "str"},
        "zero_norm_policy": {"kind": "str"},
        "batch_contract": {"kind": "str", "null_ok": True},
    },
    "build_flags": {
        "v7_python_wheel": {"kind": "mapping"},
    },
    "static_build_targets": {
        "flock_static": {"kind": "str", "equals": STATIC_BUILD_EXPECTED["flock_static"]},
        "flock_loadable": {"kind": "str", "equals": STATIC_BUILD_EXPECTED["flock_loadable"]},
        "fts_static": {"kind": "str", "equals": STATIC_BUILD_EXPECTED["fts_static"]},
        "fts_loadable": {"kind": "str", "equals": STATIC_BUILD_EXPECTED["fts_loadable"]},
        "tachiom_static_cmake": {"kind": "str", "null_ok": True},
        "python_module": {"kind": "str", "equals": STATIC_BUILD_EXPECTED["python_module"]},
    },
}

WHEEL_REQUIRED_LEAVES: dict[str, dict[str, Any]] = {
    "status": {"kind": "completeness"},
    "required_static_extensions": {"kind": "str_list"},
    "target_duckdb_commit": {"kind": "commit"},
    "separate_from_v6_wheel": {"kind": "bool"},
}

DUPLICATE_SCALAR_SCHEMA: dict[str, dict[str, Any]] = {
    "tokenizer_identity": {"kind": "str"},
    "tokenizer_version": {"kind": "str"},
    "tokenizer_hash": {"kind": "sha256"},
    "embedding_dimension": {"kind": "positive_int", "equals": MDENSEON_EXPECTED_DIMENSION},
    "embedding_dtype": {"kind": "str", "equals": MDENSEON_EXPECTED_DTYPE},
    "embedding_normalization": {"kind": "str"},
    "embedding_zero_norm_policy": {"kind": "str"},
    "embedding_batch_contract": {"kind": "str", "null_ok": True},
    "mineru_model_name": {"kind": "str"},
    "mineru_model_version": {"kind": "str"},
    "mineru_model_snapshot_manifest_sha256": {"kind": "sha256"},
    "mineru_wheel_sha256": {"kind": "sha256", "optional": True, "equals": MINERU_WHEEL_SHA256},
    "tachiom_envelope_version": {"kind": "int", "equals": TACHIOM_INDEX_FORMAT_VERSION},
    BM25_CONFIG_HASH_KEY: {"kind": "sha256", "null_ok": True},
    **{key: {"kind": "str", "null_ok": True} for key in BM25_SIBLING_KEYS},
}

HASH_KEY_RE = re.compile(r"(sha256|hash|digest)$", re.I)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
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
NEAREST_RESULT_LINE = f"All tests passed ({NEAREST_ASSERTIONS} assertions in 1 test case)"
_LOG_HEADER_SPECS = [
    ("command", "command: "),
    ("cwd", "cwd: "),
    ("build_commit", "duckdb commit: "),
    ("build_tag", "duckdb tag: "),
    ("binary_path", "binary path: "),
    ("working_tree", "working tree: "),
    ("start", "start: "),
    ("end", "end: "),
    ("exit_code", "exit code: "),
]
NEAREST_STDOUT_DELIM = "----- stdout -----"
NEAREST_STDERR_DELIM = "----- stderr -----"
NEAREST_WORKING_TREE_CLEAN = "clean (git status --porcelain empty)"
NEAREST_STDOUT_FILTER = f"Filters: test/sql/join/nearest/{NEAREST_TEST_NAME}"

DIRTY_MANIFEST_KEYS = [
    ("pg-agent", "pg_agent_dirty"),
    ("flock", "flock_dirty"),
    ("duckdb-pgagent", "duckdb_pgagent_dirty"),
    ("duckdb-python-pgagent", "duckdb_python_pgagent_dirty"),
    ("duckdb-tachiom", "duckdb_tachiom_dirty"),
]
# Authoritative dirty is the provenance git row: repos.<name>.dirty for the four
# repos; external_not_four_repo.tachiom.dirty vs tachiom_checkout_dirty;
# external_not_four_repo.duckdb-tachiom.dirty vs duckdb_tachiom_dirty.
DIRTY_AGREEMENT_KEYS = DIRTY_MANIFEST_KEYS + [
    ("tachiom", "tachiom_checkout_dirty"),
]
DIRTY_EXTERNAL_NAMES = {"tachiom", "duckdb-tachiom"}

FLOCK_SUBMODULE_ORDER = ["duckdb", "extension-ci-tools"]
FLOCK_SUBMODULE_STATUS_OK = "ok"
FLOCK_SUBMODULE_STATUS_BLOCKED = "blocked"
FLOCK_SUBMODULE_STATUSES = {FLOCK_SUBMODULE_STATUS_OK, FLOCK_SUBMODULE_STATUS_BLOCKED}
TAG_STATUS_MISSING = "missing"
TAG_STATUS_TOKENS = ALLOWED_COMPLETENESS
GENERIC_STATUS_TOKENS = NULLABLE_HASH_STATUS_TOKENS
CARGO_TACHIOM_GIT_TAG_PIN_KEY = "duckdb_tachiom_cargo_tachiom_git_tag_pin"
CARGO_TACHIOM_GIT_TAG_PIN_COMMIT_KEY = "duckdb_tachiom_cargo_tachiom_git_tag_pin_commit"

EMBEDDING_REQUIRED_NESTED = [
    "dimension",
    "dtype",
    "normalization",
    "zero_norm_policy",
    "batch_contract",
]

MDENSEON_RUNTIME_KEYS = [
    "model_id",
    "revision",
    "source",
    "library_name",
    "lock_format",
    "expected_python",
]

MINERU_PARSER_STRING_KEYS = [
    "backend",
    "method",
    "cli",
    "canonical_surface",
    "page_idx",
    "catalog_page",
    "bbox",
]


def _is_meta_key(key: str) -> bool:
    return key in META_KEYS or bool(META_KEY_RE.search(key))


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _allowed_str(value: object, allowed: Mapping[str, Any] | set[str] | frozenset[str] | Sequence[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _is_none_or(value: object, expected: object) -> bool:
    return value is None or value == expected


def _evidence_rank_of(level: object) -> int | None:
    if not isinstance(level, str):
        return None
    return EVIDENCE_RANK.get(level)


def _is_commit(value: object) -> bool:
    return isinstance(value, str) and bool(COMMIT_RE.match(value))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.match(value))


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and bool(IMAGE_DIGEST_RE.match(value))


def _is_str_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_non_empty_str(item) for item in value)
    )


def _is_nonneg_int(value: object) -> bool:
    return _is_int(value) and int(value) >= 0


def _is_id_list(value: object) -> bool:
    return isinstance(value, list) and all(_non_empty_str(item) for item in value)


def _value_matches_kind(kind: str, value: object) -> bool:
    if kind == "str":
        return _non_empty_str(value)
    if kind == "int":
        return _is_int(value)
    if kind == "positive_int":
        return _is_int(value) and int(value) > 0
    if kind == "bool":
        return _is_bool(value)
    if kind == "mapping":
        return isinstance(value, Mapping)
    if kind == "commit":
        return _is_commit(value)
    if kind == "sha256":
        return _is_sha256(value)
    if kind == "digest":
        return _is_digest(value)
    if kind == "str_list":
        return _is_str_list(value)
    if kind == "completeness":
        return _allowed_str(value, ALLOWED_COMPLETENESS)
    return False


def _reason(blocker_id: str, blocker_class: str, code: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "blocker_class": blocker_class,
        "code": code,
        "details": dict(details or {}),
    }


class _Sink:
    def __init__(self) -> None:
        self._by_class: dict[str, list[dict[str, Any]]] = {cls: [] for cls in PHASE0_BLOCKER_CLASS_ORDER}
        self._seen: set[str] = set()

    def add(self, blocker_id: str, blocker_class: str, code: str, details: Mapping[str, Any] | None = None) -> None:
        if blocker_class not in self._by_class:
            raise ValueError(blocker_class)
        if code not in REASON_CODES:
            raise ValueError(code)
        if blocker_id in self._seen:
            return
        self._seen.add(blocker_id)
        self._by_class[blocker_class].append(_reason(blocker_id, blocker_class, code, details))

    def result(self) -> dict[str, Any]:
        blocker_ids: list[str] = []
        blocker_classes: list[str] = []
        reasons: list[dict[str, Any]] = []
        for cls in PHASE0_BLOCKER_CLASS_ORDER:
            rows = self._by_class[cls]
            if not rows:
                continue
            blocker_classes.append(cls)
            for row in rows:
                blocker_ids.append(row["blocker_id"])
                reasons.append(row)
        return {
            "schema_version": SCHEMA_VERSION,
            "evaluator": EVALUATOR_ID,
            "phase0_pass": not blocker_ids,
            "blocker_ids": blocker_ids,
            "blocker_classes": blocker_classes,
            "reasons": reasons,
        }


def _coerce_repo_path(value: object, repo_root: Path | None) -> Path | None:
    if isinstance(value, Path):
        path = value.expanduser()
    elif _non_empty_str(value):
        path = Path(str(value)).expanduser()
    else:
        return None
    if path.is_absolute():
        try:
            return path.resolve()
        except (OSError, RuntimeError):
            return None
    if repo_root is None:
        return None
    try:
        root = Path(repo_root).resolve()
        resolved = (root / path).resolve()
        resolved.relative_to(root)
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _parse_configured_binary_relpath(text: object) -> str | None:
    """Parse a single POSIX repo-root-relative live-binary path. Fail closed."""
    if not isinstance(text, str) or "\x00" in text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    raw = lines[0]
    if raw.startswith(("#", "~", "$")) or "\\" in raw:
        return None
    path = Path(raw)
    if path.is_absolute() or raw in {".", ".."} or not path.parts:
        return None
    return raw


def _coerce_configured_live_path(value: object, repo_root: Path | None) -> Path | None:
    """Anchor a configured relative path at repo_root. Parent escape is allowed."""
    rel = _parse_configured_binary_relpath(str(value) if _non_empty_str(value) else None)
    if rel is None or repo_root is None:
        return None
    try:
        root = Path(repo_root).resolve()
        return (root / rel).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_configured_live_binary(repo_root: Path) -> Path | None:
    """Resolve the configured live unittest path. Missing/malformed/unreadable → None."""
    try:
        root = Path(repo_root).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    config = root / NEAREST_LIVE_BINARY_RELPATH_FILE
    try:
        if not config.is_file():
            return None
        text = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    resolved = _coerce_configured_live_path(text, root)
    if resolved is None:
        return None
    try:
        if not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved


def _resolve_optional_file(
    env_vars: Sequence[str],
    recorded: Iterable[object],
    *,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> tuple[Path | None, str]:
    """Resolve live files from env or repo-relative recorded paths.

    Relative env values are anchored to ``repo_root``, never process cwd.
    Recorded absolute developer paths are evidence metadata, not live inputs.
    """
    env = os.environ if environ is None else environ
    root = Path(repo_root).resolve() if repo_root is not None else None
    for var in env_vars:
        raw = env.get(var)
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            anchored = _coerce_repo_path(path, root)
            if anchored is None:
                return None, "env"
            path = anchored
        else:
            try:
                path = path.resolve()
            except (OSError, RuntimeError):
                return path, "env"
        if path.is_file():
            return path, "env"
        return path, "env"
    for candidate in recorded:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.is_absolute():
            continue
        resolved = _coerce_repo_path(path, root)
        if resolved is None or not resolved.is_file():
            continue
        return resolved, "recorded"
    return None, "absent"


def _not_applicable_null_hash(path: str, value: object, status: object) -> bool:
    return path in NOT_APPLICABLE_HASH_PATHS and status == NOT_APPLICABLE_STATUS and value is None


def required_null_hash_paths(manifest: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for key in REQUIRED_HASH_FIELDS:
        value = manifest.get(key)
        if value is None:
            status = _sibling_status(manifest, key)
            if not _not_applicable_null_hash(key, value, status):
                found.append(key)
        elif isinstance(value, dict):
            for nested_key, nested_val in value.items():
                if _is_meta_key(nested_key):
                    continue
                if nested_val is None and HASH_KEY_RE.search(nested_key):
                    path = f"{key}.{nested_key}"
                    status = _sibling_status(value, nested_key)
                    if not _not_applicable_null_hash(path, nested_val, status):
                        found.append(path)
    return found


def dirty_uninitialized_labels(manifest: Mapping[str, Any], provenance: Mapping[str, Any] | None) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label not in seen:
            seen.add(label)
            labels.append(label)

    for name, key in DIRTY_MANIFEST_KEYS:
        if manifest.get(key) is True:
            add(f"{name} dirty")
    repos = (provenance or {}).get("repos") if isinstance(provenance, Mapping) else {}
    if not isinstance(repos, Mapping):
        repos = {}
    for name, _key in DIRTY_MANIFEST_KEYS:
        if name == "duckdb-tachiom":
            continue
        row = repos.get(name)
        if isinstance(row, Mapping) and row.get("dirty") is True:
            add(f"{name} dirty")
    external = (provenance or {}).get("external_not_four_repo") if isinstance(provenance, Mapping) else {}
    if not isinstance(external, Mapping):
        external = {}
    dt = external.get("duckdb-tachiom")
    if isinstance(dt, Mapping) and dt.get("dirty") is True:
        add("duckdb-tachiom dirty")
    flock = repos.get("flock") if isinstance(repos.get("flock"), Mapping) else {}
    flock_subs = flock.get("submodules") if isinstance(flock.get("submodules"), Mapping) else {}
    for sub_name in FLOCK_SUBMODULE_ORDER:
        sub = flock_subs.get(sub_name)
        if not isinstance(sub, Mapping):
            add(f"flock.{sub_name} uninitialized")
            continue
        if sub.get("initialized") is False or sub.get("status") == "blocked":
            add(f"flock.{sub_name} uninitialized")
    for sub_name, sub in flock_subs.items():
        if sub_name in FLOCK_SUBMODULE_ORDER:
            continue
        if not isinstance(sub, Mapping):
            continue
        if sub.get("initialized") is False or sub.get("status") == "blocked":
            add(f"flock.{sub_name} uninitialized")
    return labels


def _unittest_bin_candidates(
    repo_root: Path,
    historical_nearest: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[object]:
    """Repo-relative configured paths only. Absolute recorded paths are not live inputs."""
    _ = Path(repo_root)
    candidates: list[object] = []
    records: list[Mapping[str, Any]] = []
    if isinstance(historical_nearest, Mapping):
        records.append(historical_nearest)
    manifest_nearest = manifest.get("nearest_e2") if isinstance(manifest, Mapping) else None
    if isinstance(manifest_nearest, Mapping):
        records.append(manifest_nearest)
    for record in records:
        raw = record.get("binary_path")
        if not _non_empty_str(raw):
            continue
        path = Path(str(raw)).expanduser()
        if path.is_absolute():
            continue
        candidates.append(path)
    return candidates


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _nearest_records_fingerprint(manifest_record: Mapping[str, Any], historical_record: Mapping[str, Any]) -> str:
    payload = {
        "shared": {key: manifest_record.get(key) for key in NEAREST_SHARED_FIELDS},
        "verification": {
            key: (manifest_record.get("verification") or {}).get(key)
            if isinstance(manifest_record.get("verification"), Mapping)
            else None
            for key in NEAREST_VERIFICATION_SHARED_FIELDS
        },
        "historical_schema": historical_record.get("schema_version"),
        "log_start_utc": historical_record.get("log_start_utc"),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _nearest_record_failures(record: Mapping[str, Any] | None, *, historical: bool) -> list[str]:
    if not isinstance(record, Mapping):
        return ["HISTORICAL_RECORD_INVALID"] if historical else ["MANIFEST_RECORD_INVALID"]
    failures: list[str] = []
    if historical and record.get("schema_version") != NEAREST_HISTORICAL_SCHEMA:
        failures.append("HISTORICAL_RECORD_INVALID")
    if historical and not _non_empty_str(record.get("log_start_utc")):
        failures.append("HISTORICAL_RECORD_INVALID")
    if record.get("evidence_level") != "E2":
        failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
    if record.get("command") != NEAREST_COMMAND or NEAREST_TEST_NAME not in str(record.get("command") or ""):
        failures.append("LOG_COMMAND_MISMATCH")
    if not _non_empty_str(record.get("cwd")):
        failures.append("LOG_CWD_MISMATCH")
    if record.get("exit_code") != NEAREST_EXIT_CODE:
        failures.append("LOG_EXIT_CODE_MISMATCH")
    if record.get("assertions") != NEAREST_ASSERTIONS:
        failures.append("LOG_ASSERTION_COUNT_MISMATCH")
    if record.get("log") != NEAREST_LOG_REL:
        failures.append("LOG_MALFORMED")
    if not _non_empty_str(record.get("binary_path")):
        failures.append("BINARY_PATH_UNRESOLVED")
    if record.get("binary_sha256") != NEAREST_SHA256:
        failures.append("BINARY_SHA256_MISMATCH")
    if record.get("binary_size_bytes") != NEAREST_SIZE_BYTES:
        failures.append("BINARY_SIZE_MISMATCH")
    if not _non_empty_str(record.get("binary_file_type")):
        failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
    if not _non_empty_str(record.get("binary_mtime_local")):
        failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
    if record.get("build_identity_commit") != DUCKDB_PGAGENT_COMMIT:
        failures.append("LOG_BUILD_IDENTITY_MISMATCH")
    if record.get("build_identity_tag") != NEAREST_BUILD_TAG:
        failures.append("LOG_BUILD_IDENTITY_MISMATCH")
    verification = record.get("verification")
    if not isinstance(verification, Mapping):
        failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
    else:
        if verification.get("binary_required_for_live_e2") is not True:
            failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
        if verification.get("log_required_for_live_e2") is not True:
            failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
        if verification.get("absent_binary_or_log_gate_level") != "blocked":
            failures.append("HISTORICAL_RECORD_INVALID" if historical else "MANIFEST_RECORD_INVALID")
    return failures


def _record_field_mismatches(manifest_record: Mapping[str, Any], historical_record: Mapping[str, Any]) -> bool:
    for key in NEAREST_SHARED_FIELDS:
        if manifest_record.get(key) != historical_record.get(key):
            return True
    man_ver = manifest_record.get("verification") if isinstance(manifest_record.get("verification"), Mapping) else {}
    hist_ver = historical_record.get("verification") if isinstance(historical_record.get("verification"), Mapping) else {}
    for key in NEAREST_VERIFICATION_SHARED_FIELDS:
        if man_ver.get(key) != hist_ver.get(key):
            return True
    return False


def _competing_nearest_result_line(line: str, canonical: str) -> bool:
    if line == canonical:
        return False
    if line.startswith("All tests passed"):
        return True
    folded = line.casefold()
    return folded.startswith("all tests failed") or folded.startswith("failed:")


def _parse_nearest_log(log_text: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    if log_text is None:
        return None, ["LOG_MISSING"]
    if not isinstance(log_text, str):
        return None, ["LOG_MALFORMED"]
    if not log_text.strip():
        return None, ["LOG_EMPTY"]
    stdout_count = log_text.count(NEAREST_STDOUT_DELIM)
    stderr_count = log_text.count(NEAREST_STDERR_DELIM)
    stdout_at = log_text.find(NEAREST_STDOUT_DELIM)
    stderr_at = log_text.find(NEAREST_STDERR_DELIM)
    if stdout_count != 1 or stderr_count != 1 or stdout_at < 0 or stderr_at < 0 or stderr_at < stdout_at:
        return None, ["LOG_MALFORMED"]
    header_block = log_text[:stdout_at]
    stdout_block = log_text[stdout_at + len(NEAREST_STDOUT_DELIM) : stderr_at]
    stderr_block = log_text[stderr_at + len(NEAREST_STDERR_DELIM) :]
    lines = [line.rstrip("\n") for line in header_block.splitlines() if line.strip()]
    seen: dict[str, str] = {}
    failures: list[str] = []
    for key, prefix in _LOG_HEADER_SPECS:
        matches = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
        if len(matches) != 1:
            failures.append("LOG_MALFORMED")
            continue
        seen[key] = matches[0]
    if failures:
        return None, [code for code in NEAREST_FAILURE_CODES if code in set(failures)]
    try:
        exit_code = int(seen["exit_code"])
    except (KeyError, ValueError, TypeError):
        return None, ["LOG_EXIT_CODE_MISMATCH"]
    if seen.get("working_tree") != NEAREST_WORKING_TREE_CLEAN:
        return None, ["LOG_BUILD_IDENTITY_MISMATCH"]
    stdout_nonempty = [line.strip() for line in stdout_block.splitlines() if line.strip()]
    stderr_nonempty = [line.strip() for line in stderr_block.splitlines() if line.strip()]
    filter_hits = [line for line in stdout_nonempty if line == NEAREST_STDOUT_FILTER]
    extra_filters = [line for line in stdout_nonempty if line.startswith("Filters:") and line != NEAREST_STDOUT_FILTER]
    if len(filter_hits) != 1 or extra_filters:
        return None, ["LOG_MALFORMED"]
    result_hits = [line for line in stdout_nonempty if line == NEAREST_RESULT_LINE]
    competing = [
        line
        for line in stdout_nonempty + stderr_nonempty
        if _competing_nearest_result_line(line, NEAREST_RESULT_LINE)
    ]
    if len(result_hits) != 1 or competing:
        return None, ["LOG_ASSERTION_COUNT_MISMATCH"]
    observation = {
        "path": NEAREST_LOG_REL,
        "command": seen.get("command"),
        "cwd": seen.get("cwd"),
        "exit_code": exit_code,
        "assertions": NEAREST_ASSERTIONS,
        "test_cases": 1,
        "binary_path": seen.get("binary_path"),
        "build_commit": seen.get("build_commit"),
        "build_tag": seen.get("build_tag"),
        "start": seen.get("start"),
        "end": seen.get("end"),
        "working_tree_clean": True,
    }
    return observation, []


def _observe_binary(path: Path, *, repo_root: Path | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    resolved = _coerce_repo_path(path, repo_root)
    if resolved is None:
        return None, ["BINARY_PATH_UNRESOLVED"]
    try:
        with resolved.open("rb") as handle:
            first = os.fstat(handle.fileno())
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
            second = os.fstat(handle.fileno())
        if first.st_size != second.st_size or first.st_mtime_ns != second.st_mtime_ns:
            return None, ["BINARY_READ_FAILED"]
        return {
            "sha256": digest.hexdigest(),
            "size_bytes": int(first.st_size),
            "path": str(resolved),
        }, []
    except OSError:
        return None, ["BINARY_READ_FAILED"]


def _order_nearest_failures(failures: Iterable[str]) -> list[str]:
    present = set(failures)
    return [code for code in NEAREST_FAILURE_CODES if code in present]


def _paths_equivalent(left: object, right: object, *, repo_root: Path | None = None) -> bool:
    left_path = _coerce_repo_path(left, repo_root)
    right_path = _coerce_repo_path(right, repo_root)
    return left_path is not None and right_path is not None and left_path == right_path


def _attest_nearest_verification(
    historical_nearest: Mapping[str, Any] | None,
    manifest: Mapping[str, Any] | None,
    *,
    log_observation: Mapping[str, Any] | None,
    binary_observation: Mapping[str, Any] | None,
    binary_source: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    man_nearest = None
    if isinstance(manifest, Mapping):
        raw = manifest.get("nearest_e2")
        man_nearest = raw if isinstance(raw, Mapping) else None
    hist = historical_nearest if isinstance(historical_nearest, Mapping) else None
    failures.extend(_nearest_record_failures(man_nearest, historical=False))
    failures.extend(_nearest_record_failures(hist, historical=True))
    if isinstance(man_nearest, Mapping) and isinstance(hist, Mapping) and _record_field_mismatches(man_nearest, hist):
        failures.append("RECORD_FIELD_MISMATCH")

    fingerprint = None
    if isinstance(man_nearest, Mapping) and isinstance(hist, Mapping):
        fingerprint = _nearest_records_fingerprint(man_nearest, hist)

    if not _allowed_str(binary_source, {"env", "recorded", "absent"}):
        failures.append("ATTESTATION_SCHEMA_INVALID")
        source = binary_source
    else:
        source = binary_source

    record = hist if isinstance(hist, Mapping) else man_nearest
    if log_observation is None:
        failures.append("LOG_MISSING")
    elif not isinstance(log_observation, Mapping):
        failures.append("LOG_MALFORMED")
    else:
        if not _is_none_or(log_observation.get("path"), NEAREST_LOG_REL):
            failures.append("LOG_MALFORMED")
        if log_observation.get("command") != NEAREST_COMMAND:
            failures.append("LOG_COMMAND_MISMATCH")
        if isinstance(record, Mapping) and log_observation.get("cwd") != record.get("cwd"):
            failures.append("LOG_CWD_MISMATCH")
        if log_observation.get("exit_code") != NEAREST_EXIT_CODE:
            failures.append("LOG_EXIT_CODE_MISMATCH")
        if log_observation.get("assertions") != NEAREST_ASSERTIONS or not _is_none_or(log_observation.get("test_cases"), 1):
            failures.append("LOG_ASSERTION_COUNT_MISMATCH")
        if isinstance(record, Mapping) and log_observation.get("binary_path") != record.get("binary_path"):
            failures.append("LOG_BINARY_PATH_MISMATCH")
        if log_observation.get("build_commit") != DUCKDB_PGAGENT_COMMIT or log_observation.get("build_tag") != NEAREST_BUILD_TAG:
            failures.append("LOG_BUILD_IDENTITY_MISMATCH")
        if log_observation.get("working_tree_clean") is not True:
            failures.append("LOG_BUILD_IDENTITY_MISMATCH")
        if not _non_empty_str(log_observation.get("start")) or not _non_empty_str(log_observation.get("end")):
            failures.append("LOG_MALFORMED")

    if binary_observation is None:
        failures.append("BINARY_PATH_UNRESOLVED" if source == "absent" else "BINARY_READ_FAILED")
    elif not isinstance(binary_observation, Mapping):
        failures.append("BINARY_READ_FAILED")
    else:
        if binary_observation.get("sha256") != NEAREST_SHA256:
            failures.append("BINARY_SHA256_MISMATCH")
        if binary_observation.get("size_bytes") != NEAREST_SIZE_BYTES:
            failures.append("BINARY_SIZE_MISMATCH")
        build = binary_observation.get("build_identity")
        if not isinstance(build, Mapping):
            failures.append("BINARY_BUILD_IDENTITY_MISMATCH")
        elif build.get("commit") != DUCKDB_PGAGENT_COMMIT or build.get("tag") != NEAREST_BUILD_TAG:
            failures.append("BINARY_BUILD_IDENTITY_MISMATCH")
        observed_path = binary_observation.get("path")
        if not _non_empty_str(observed_path):
            failures.append("BINARY_PATH_UNRESOLVED")
        else:
            if isinstance(log_observation, Mapping) and _non_empty_str(log_observation.get("binary_path")):
                if not _paths_equivalent(
                    observed_path, log_observation.get("binary_path"), repo_root=repo_root
                ):
                    failures.append("LOG_BINARY_PATH_MISMATCH")
            if isinstance(record, Mapping) and _non_empty_str(record.get("binary_path")):
                if not _paths_equivalent(
                    observed_path, record.get("binary_path"), repo_root=repo_root
                ):
                    failures.append("LOG_BINARY_PATH_MISMATCH")

    ordered = _order_nearest_failures(failures)
    verified = not ordered
    return {
        "schema_version": NEAREST_VERIFICATION_SCHEMA,
        "verifier": NEAREST_VERIFIER_ID,
        "verified": verified,
        "live_gate_level": "E2" if verified else "blocked",
        "failure_codes": [] if verified else ordered,
        "binary_source": source if _allowed_str(source, {"env", "recorded", "absent"}) else "absent",
        "records_sha256": fingerprint,
        "observed": {
            "log": dict(log_observation) if isinstance(log_observation, Mapping) else None,
            "binary": dict(binary_observation) if isinstance(binary_observation, Mapping) else None,
        },
    }


def _verify_nearest_live(
    historical_nearest: Mapping[str, Any] | None,
    manifest: Mapping[str, Any] | None,
    log_text: str | None,
    *,
    binary_path: Path | None,
    binary_source: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    log_observation, log_failures = _parse_nearest_log(log_text)
    binary_observation = None
    extra: list[str] = list(log_failures)
    if not _allowed_str(binary_source, {"env", "recorded", "absent"}):
        extra.append("ATTESTATION_SCHEMA_INVALID")
        source = binary_source
    else:
        source = binary_source
    if binary_path is None:
        extra.append("BINARY_PATH_UNRESOLVED")
        source = "absent" if source != "env" else "env"
    else:
        try:
            observed_path = _coerce_repo_path(binary_path, repo_root)
            if observed_path is None or not observed_path.is_file():
                extra.append("BINARY_PATH_UNRESOLVED")
                source = "absent" if source != "env" else "env"
            else:
                binary_observation, bin_failures = _observe_binary(observed_path, repo_root=repo_root)
                extra.extend(bin_failures)
                if isinstance(binary_observation, dict) and isinstance(log_observation, Mapping):
                    binary_observation = dict(binary_observation)
                    binary_observation["build_identity"] = {
                        "commit": log_observation.get("build_commit"),
                        "tag": log_observation.get("build_tag"),
                    }
        except OSError:
            extra.append("BINARY_READ_FAILED")
            binary_observation = None
    result = _attest_nearest_verification(
        historical_nearest,
        manifest,
        log_observation=log_observation,
        binary_observation=binary_observation,
        binary_source=source,
        repo_root=repo_root,
    )
    if extra:
        codes = set(result["failure_codes"]) | set(extra)
        result["failure_codes"] = _order_nearest_failures(codes)
        result["verified"] = False
        result["live_gate_level"] = "blocked"
    elif result["verified"] is True:
        result["failure_codes"] = []
        result["live_gate_level"] = "E2"
    else:
        result["live_gate_level"] = "blocked"
    return result


def _collect_nearest_live_evidence(
    repo_root: Path,
    manifest: Mapping[str, Any] | None,
    historical_nearest: Mapping[str, Any] | None,
    *,
    environ: Mapping[str, str] | None = None,
    log_text: str | None = None,
    log_loaded: bool = False,
    malformed_log: bool = False,
) -> dict[str, Any]:
    try:
        root = Path(repo_root).resolve()
    except (OSError, RuntimeError):
        root = Path(repo_root)
    if not log_loaded:
        log_path = root / NEAREST_LOG_REL
        malformed_log = False
        if not log_path.is_file():
            log_text = None
        else:
            try:
                log_text = log_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                log_text = None
                malformed_log = True

    man = manifest if isinstance(manifest, Mapping) else {}
    hist = historical_nearest if isinstance(historical_nearest, Mapping) else {}
    binary_path, source = _resolve_optional_file(
        UNITTEST_BIN_ENV_VARS,
        _unittest_bin_candidates(root, hist, man),
        environ=environ,
        repo_root=root,
    )
    def _path_is_file(path: Path | None) -> bool:
        if path is None:
            return False
        try:
            return path.is_file()
        except OSError:
            return False

    if source != "env" and not _path_is_file(binary_path):
        configured = _resolve_configured_live_binary(root)
        if configured is not None:
            binary_path, source = configured, "recorded"

    if source == "env" and not _path_is_file(binary_path):
        binary_path = None
        source = "env"
    elif not _path_is_file(binary_path):
        binary_path = None
        source = "absent"

    result = _verify_nearest_live(
        historical_nearest if isinstance(historical_nearest, Mapping) else None,
        manifest if isinstance(manifest, Mapping) else None,
        log_text,
        binary_path=binary_path,
        binary_source=source,
        repo_root=root,
    )
    if malformed_log:
        codes = set(result["failure_codes"]) | {"LOG_MALFORMED"}
        result["failure_codes"] = _order_nearest_failures(codes)
        result["verified"] = False
        result["live_gate_level"] = "blocked"
    if result["verified"] is True:
        result["failure_codes"] = []
        result["live_gate_level"] = "E2"
    else:
        result["verified"] = False
        result["live_gate_level"] = "blocked"
    return result


def _completeness_entry(manifest: Mapping[str, Any], key: str) -> tuple[bool, object]:
    completeness = manifest.get("completeness")
    if not isinstance(completeness, Mapping) or key not in completeness:
        return False, None
    return True, completeness.get(key)


def _completeness_of(manifest: Mapping[str, Any], key: str) -> object:
    present, value = _completeness_entry(manifest, key)
    return value if present else None


def _mapping_entry(container: Mapping[str, Any], key: str) -> tuple[bool, object]:
    if not isinstance(container, Mapping) or key not in container:
        return False, None
    return True, container.get(key)


def _nested_meta_entry(container: Mapping[str, Any], key: str, meta: str) -> tuple[bool, object]:
    present, nested = _mapping_entry(container, key)
    if present and isinstance(nested, Mapping):
        return _mapping_entry(nested, meta)
    return False, None


def _sibling_status_entry(container: Mapping[str, Any], key: str) -> tuple[bool, object]:
    present, value = _mapping_entry(container, f"{key}_status")
    if present:
        return True, value
    return _nested_meta_entry(container, key, "status")


def _sibling_notes_entry(container: Mapping[str, Any], key: str) -> tuple[bool, object]:
    present, value = _mapping_entry(container, f"{key}_notes")
    if present:
        return True, value
    return _nested_meta_entry(container, key, "notes")


def _sibling_status(container: Mapping[str, Any], key: str) -> object:
    present, value = _sibling_status_entry(container, key)
    return value if present else None


def _sibling_notes(container: Mapping[str, Any], key: str) -> object:
    present, value = _sibling_notes_entry(container, key)
    return value if present else None


def _reject_unallowed_enum(
    sink: _Sink,
    field: str,
    value: object,
    allowed: Mapping[str, Any] | set[str] | frozenset[str] | Sequence[str],
    extra: Mapping[str, Any] | None = None,
    *,
    blocker_id: str | None = None,
) -> bool:
    if _allowed_str(value, allowed):
        return True
    details: dict[str, Any] = {"field": field, "status": value}
    if extra:
        details.update(extra)
    sink.add(blocker_id or f"manifest.{field}", BLOCKER_CLASS_MANIFEST, "MANIFEST_STATUS_INVALID", details)
    return False


def _validate_present_enum(
    sink: _Sink,
    container: Mapping[str, Any],
    field: str,
    key: str,
    allowed: Mapping[str, Any] | set[str] | frozenset[str] | Sequence[str],
    extra: Mapping[str, Any] | None = None,
    *,
    required: bool = False,
) -> None:
    present, value = _mapping_entry(container, key)
    if not present:
        if required:
            _manifest_add(sink, field, "MANIFEST_FIELD_MISSING")
        return
    _reject_unallowed_enum(sink, field, value, allowed, extra)


def _validate_present_notes(sink: _Sink, container: Mapping[str, Any], field: str, key: str) -> None:
    present, value = _mapping_entry(container, key)
    if not present:
        return
    if not _non_empty_str(value):
        _manifest_add(sink, field, "MANIFEST_FIELD_INVALID")


def _manifest_add(sink: _Sink, field: str, code: str, extra: Mapping[str, Any] | None = None) -> None:
    details = {"field": field}
    if extra:
        details.update(extra)
    sink.add(f"manifest.{field}", BLOCKER_CLASS_MANIFEST, code, details)


def _observed_tag_pair_valid(tag: object, status: object) -> bool:
    if tag is None:
        return status == TAG_STATUS_MISSING
    return _non_empty_str(tag) and _non_empty_str(status) and status != TAG_STATUS_MISSING


def _validate_manifest_tag_observation(sink: _Sink, manifest: Mapping[str, Any], tag_key: str, status_key: str) -> None:
    if tag_key not in manifest:
        _manifest_add(sink, tag_key, "MANIFEST_FIELD_MISSING")
    elif manifest.get(tag_key) is not None and not _non_empty_str(manifest.get(tag_key)):
        _manifest_add(sink, tag_key, "MANIFEST_FIELD_INVALID")
    if status_key not in manifest:
        _manifest_add(sink, status_key, "MANIFEST_FIELD_MISSING")
    elif not _non_empty_str(manifest.get(status_key)):
        _manifest_add(sink, status_key, "MANIFEST_FIELD_INVALID")
    if tag_key in manifest and status_key in manifest and not _observed_tag_pair_valid(
        manifest.get(tag_key),
        manifest.get(status_key),
    ):
        _manifest_add(sink, tag_key, "MANIFEST_STATUS_INVALID")


def _provenance_add(sink: _Sink, field: str, code: str) -> None:
    sink.add(field, BLOCKER_CLASS_MANIFEST, code, {"field": field})


def _validate_external_tag_observation(
    sink: _Sink,
    manifest: Mapping[str, Any],
    name: str,
    row: Mapping[str, Any],
) -> None:
    if name == "tachiom":
        tag_key = "tachiom_checkout_tag"
        status_key = "tachiom_checkout_tag_status"
        describe_key = "tachiom_checkout_describe"
    else:
        tag_key = "duckdb_tachiom_tag"
        status_key = "duckdb_tachiom_tag_status"
        describe_key = None
    prefix = f"provenance.external_not_four_repo.{name}"
    if "tag" not in row:
        _provenance_add(sink, f"{prefix}.tag", "MANIFEST_FIELD_MISSING")
    if "tag_status" not in row:
        _provenance_add(sink, f"{prefix}.tag_status", "MANIFEST_FIELD_MISSING")
    if "tag" in row and "tag_status" in row:
        tag = row.get("tag")
        status = row.get("tag_status")
        if not _observed_tag_pair_valid(tag, status):
            _provenance_add(sink, f"{prefix}.tag", "MANIFEST_STATUS_INVALID")
        else:
            if tag != manifest.get(tag_key):
                _provenance_add(sink, f"{prefix}.tag", "MANIFEST_FIELD_INVALID")
            if status != manifest.get(status_key):
                _provenance_add(sink, f"{prefix}.tag_status", "MANIFEST_FIELD_INVALID")
    if describe_key is not None:
        describe = row.get("describe")
        if not _non_empty_str(describe) or describe != manifest.get(describe_key):
            _provenance_add(sink, f"{prefix}.describe", "MANIFEST_FIELD_INVALID")


def _validate_dirty_agreement(sink: _Sink, manifest: Mapping[str, Any], provenance: Mapping[str, Any]) -> None:
    repos = provenance.get("repos") if isinstance(provenance.get("repos"), Mapping) else {}
    external = provenance.get("external_not_four_repo") if isinstance(provenance.get("external_not_four_repo"), Mapping) else {}
    for name, key in DIRTY_AGREEMENT_KEYS:
        if name in DIRTY_EXTERNAL_NAMES:
            row = external.get(name)
            field = f"provenance.external_not_four_repo.{name}.dirty"
        else:
            row = repos.get(name)
            field = f"provenance.repos.{name}.dirty"
        if not isinstance(row, Mapping):
            continue
        if not _is_bool(row.get("dirty")) or not _is_bool(manifest.get(key)):
            continue
        if manifest.get(key) != row.get("dirty"):
            _provenance_add(sink, field, "MANIFEST_FIELD_INVALID")


def _require_mapping(sink: _Sink, value: object, field: str) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if value is None:
        _manifest_add(sink, field, "MANIFEST_FIELD_MISSING")
        return None
    _manifest_add(sink, field, "MANIFEST_FIELD_INVALID")
    return None


def _validate_mineru_parser_config(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    field = "mineru_parser_config"
    if field not in manifest:
        return
    cfg = _require_mapping(sink, manifest.get(field), field)
    if cfg is None:
        return
    for key in MINERU_PARSER_STRING_KEYS:
        if key not in cfg:
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_MISSING")
        elif not _non_empty_str(cfg.get(key)):
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_INVALID")
    for key in ("formula", "table"):
        if key not in cfg:
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_MISSING")
        elif not _is_bool(cfg.get(key)):
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_INVALID")
    env = cfg.get("env")
    if "env" not in cfg:
        _manifest_add(sink, f"{field}.env", "MANIFEST_FIELD_MISSING")
    elif not isinstance(env, Mapping) or not env:
        _manifest_add(sink, f"{field}.env", "MANIFEST_FIELD_INVALID")
    else:
        for env_key, env_val in env.items():
            if not _non_empty_str(env_key) or not isinstance(env_val, str):
                _manifest_add(sink, f"{field}.env", "MANIFEST_FIELD_INVALID")
                break
    artifacts = cfg.get("required_artifacts")
    if "required_artifacts" not in cfg:
        _manifest_add(sink, f"{field}.required_artifacts", "MANIFEST_FIELD_MISSING")
    elif (
        not isinstance(artifacts, list)
        or not artifacts
        or any(not _non_empty_str(item) for item in artifacts)
        or len(set(artifacts)) != len(artifacts)
    ):
        _manifest_add(sink, f"{field}.required_artifacts", "MANIFEST_FIELD_INVALID")
    elif list(artifacts) != list(MINERU_PARSER_EXPECTED["required_artifacts"]):
        _manifest_add(sink, f"{field}.required_artifacts", "MANIFEST_FIELD_INVALID")
    expected_env = MINERU_PARSER_EXPECTED["env"]
    if isinstance(env, Mapping) and dict(env) != dict(expected_env):
        _manifest_add(sink, f"{field}.env", "MANIFEST_FIELD_INVALID")


def _validate_mineru_model_hash(sink: _Sink, manifest: Mapping[str, Any], completeness: Mapping[str, Any]) -> None:
    field = "mineru_model_name_version_weights_hash"
    if field not in manifest:
        return
    value = manifest.get(field)
    obj = _require_mapping(sink, value, field)
    if obj is None:
        return
    for key in ("name", "version"):
        if key not in obj:
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_MISSING")
        elif not _non_empty_str(obj.get(key)):
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_INVALID")
    if "snapshot_manifest_sha256" not in obj:
        _manifest_add(sink, f"{field}.snapshot_manifest_sha256", "MANIFEST_FIELD_MISSING")
    elif not _is_sha256(obj.get("snapshot_manifest_sha256")):
        sink.add(
            f"manifest.{field}.snapshot_manifest_sha256",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_HASH_FORMAT_INVALID",
            {"field": f"{field}.snapshot_manifest_sha256"},
        )
    single = obj.get("single_file_weights_sha256")
    status_present, status = _mapping_entry(obj, "single_file_weights_sha256_status")
    if not status_present:
        status_present, status = _sibling_status_entry(obj, "single_file_weights_sha256")
    notes_present, notes = _mapping_entry(obj, "single_file_weights_sha256_notes")
    if not notes_present:
        notes = _sibling_notes(obj, "single_file_weights_sha256")
    if "single_file_weights_sha256" not in obj:
        _manifest_add(sink, f"{field}.single_file_weights_sha256", "MANIFEST_FIELD_MISSING")
    elif status == NOT_APPLICABLE_STATUS:
        if single is not None or not _non_empty_str(notes):
            _manifest_add(
                sink,
                f"{field}.single_file_weights_sha256",
                "MANIFEST_STATUS_INVALID",
                {"status": status},
            )
    elif single is None:
        if not _non_empty_str(status) or _allowed_str(status, RECORDED_COMPLETENESS) or not _non_empty_str(notes):
            _manifest_add(sink, f"{field}.single_file_weights_sha256", "MANIFEST_STATUS_INVALID", {"status": status})
        token = completeness.get(field)
        if _allowed_str(token, RECORDED_COMPLETENESS):
            sink.add(
                f"manifest.{field}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {"field": field, "status": token},
            )
    elif not _is_sha256(single):
        sink.add(
            f"manifest.{field}.single_file_weights_sha256",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_HASH_FORMAT_INVALID",
            {"field": f"{field}.single_file_weights_sha256"},
        )


def _validate_mdenseon_runtime(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    field = "mdenseon_package_native_runtime_version"
    if field not in manifest:
        return
    obj = _require_mapping(sink, manifest.get(field), field)
    if obj is None:
        return
    for key in MDENSEON_RUNTIME_KEYS:
        if key not in obj:
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_MISSING")
        elif not _non_empty_str(obj.get(key)):
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_INVALID")


def _validate_tokenizer_hash(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    field = "tokenizer_identity_version_hash"
    if field not in manifest:
        return
    obj = _require_mapping(sink, manifest.get(field), field)
    if obj is None:
        return
    for key in ("identity", "version"):
        if key not in obj:
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_MISSING")
        elif not _non_empty_str(obj.get(key)):
            _manifest_add(sink, f"{field}.{key}", "MANIFEST_FIELD_INVALID")
    if "lfs_sha256" not in obj:
        _manifest_add(sink, f"{field}.lfs_sha256", "MANIFEST_FIELD_MISSING")
    elif obj.get("lfs_sha256") is None:
        _manifest_add(sink, f"{field}.lfs_sha256", "MANIFEST_FIELD_MISSING")
    elif not _is_sha256(obj.get("lfs_sha256")):
        sink.add(
            f"manifest.{field}.lfs_sha256",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_HASH_FORMAT_INVALID",
            {"field": f"{field}.lfs_sha256"},
        )


def _validate_embedding_composite(sink: _Sink, manifest: Mapping[str, Any], completeness: Mapping[str, Any]) -> None:
    field = "embedding_dimension_dtype_normalization_batch"
    if field not in manifest:
        return
    obj = _require_mapping(sink, manifest.get(field), field)
    if obj is None:
        return
    nested_nulls: list[str] = []
    for item in EMBEDDING_REQUIRED_NESTED:
        if item not in obj:
            _manifest_add(sink, f"{field}.{item}", "MANIFEST_FIELD_MISSING")
            continue
        value = obj.get(item)
        if item == "dimension":
            if not _is_int(value) or value <= 0:
                _manifest_add(sink, f"{field}.{item}", "MANIFEST_FIELD_INVALID")
        elif item == "batch_contract":
            if value is None:
                nested_nulls.append(item)
                status_present, status = _mapping_entry(obj, "batch_contract_status")
                if not status_present:
                    status_present, status = _sibling_status_entry(obj, "batch_contract")
                notes_present, notes = _mapping_entry(obj, "batch_contract_notes")
                if not notes_present:
                    notes = _sibling_notes(obj, "batch_contract")
                if not _non_empty_str(status) or not _non_empty_str(notes):
                    _manifest_add(sink, f"{field}.batch_contract", "MANIFEST_STATUS_INVALID", {"status": status})
                if "embedding_batch_contract" in manifest and manifest.get("embedding_batch_contract") is not None:
                    _manifest_add(sink, "embedding_batch_contract", "MANIFEST_FIELD_INVALID")
            elif not _non_empty_str(value):
                _manifest_add(sink, f"{field}.{item}", "MANIFEST_FIELD_INVALID")
            elif "embedding_batch_contract" in manifest and manifest.get("embedding_batch_contract") != value:
                _manifest_add(sink, "embedding_batch_contract", "MANIFEST_FIELD_INVALID")
        else:
            if value is None:
                nested_nulls.append(item)
                _manifest_add(sink, f"{field}.{item}", "MANIFEST_FIELD_MISSING")
            elif not _non_empty_str(value):
                _manifest_add(sink, f"{field}.{item}", "MANIFEST_FIELD_INVALID")
    parent_tokens = [
        completeness.get(field),
        manifest.get(f"{field}_status"),
        obj.get("status"),
    ]
    if nested_nulls or obj.get("batch_contract") is None:
        for token in parent_tokens:
            if _allowed_str(token, RECORDED_COMPLETENESS):
                sink.add(
                    f"manifest.{field}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"field": field, "status": token},
                )
                break


def _validate_v7_wheel(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    flags = manifest.get("build_flags")
    if "build_flags" in manifest and flags is not None and not isinstance(flags, Mapping):
        _manifest_add(sink, "build_flags", "MANIFEST_FIELD_INVALID")
        return
    if not isinstance(flags, Mapping):
        return
    if "v7_python_wheel" not in flags:
        _manifest_add(sink, "build_flags.v7_python_wheel", "MANIFEST_FIELD_MISSING")
        return
    wheel = flags.get("v7_python_wheel")
    if not isinstance(wheel, Mapping):
        _manifest_add(sink, "build_flags.v7_python_wheel", "MANIFEST_FIELD_INVALID")
        return
    status = wheel.get("status")
    if not _allowed_str(status, ALLOWED_COMPLETENESS):
        if not _non_empty_str(status):
            _manifest_add(sink, "build_flags.v7_python_wheel.status", "MANIFEST_FIELD_INVALID")
        else:
            sink.add(
                "manifest.build_flags.v7_python_wheel.status",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {"field": "build_flags.v7_python_wheel.status", "status": status},
            )
    required = wheel.get("required_static_extensions")
    if not isinstance(required, list) or list(required) != list(REQUIRED_V7_EXTENSIONS):
        _manifest_add(sink, "build_flags.v7_python_wheel.required_static_extensions", "MANIFEST_FIELD_INVALID")
    target_commit = wheel.get("target_duckdb_commit")
    if not _is_commit(target_commit) or target_commit != manifest.get("duckdb_pgagent_commit"):
        _manifest_add(sink, "build_flags.v7_python_wheel.target_duckdb_commit", "MANIFEST_FIELD_INVALID")
    if wheel.get("separate_from_v6_wheel") is not True:
        _manifest_add(sink, "build_flags.v7_python_wheel.separate_from_v6_wheel", "MANIFEST_FIELD_INVALID")
    artifact = wheel.get("artifact_path")
    if artifact is not None and not _non_empty_str(artifact):
        _manifest_add(sink, "build_flags.v7_python_wheel.artifact_path", "MANIFEST_FIELD_INVALID")
    v6_path = manifest.get("v6_python_wheel_path")
    if artifact and v6_path and artifact == v6_path:
        _manifest_add(sink, "build_flags.v7_python_wheel.artifact_path", "MANIFEST_FIELD_INVALID")
    artifact_status_present, artifact_status = _mapping_entry(wheel, "artifact_path_status")
    if status == "blocked":
        if not _is_none_or(artifact, ""):
            _manifest_add(sink, "build_flags.v7_python_wheel.artifact_path", "MANIFEST_STATUS_INVALID")
        if not artifact_status_present or artifact_status != "blocked":
            sink.add(
                "manifest.build_flags.v7_python_wheel.artifact_path_status",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {
                    "field": "build_flags.v7_python_wheel.artifact_path_status",
                    "status": artifact_status,
                },
            )
        if not _non_empty_str(wheel.get("notes")):
            _manifest_add(sink, "build_flags.v7_python_wheel.notes", "MANIFEST_FIELD_MISSING")
    elif _allowed_str(status, RECORDED_COMPLETENESS):
        if not _non_empty_str(artifact) or not _is_sha256(manifest.get("build_artifact_wheel_sha256")):
            _manifest_add(sink, "build_flags.v7_python_wheel.artifact_path", "MANIFEST_FIELD_INVALID")
        if artifact_status_present and not _allowed_str(artifact_status, RECORDED_COMPLETENESS):
            sink.add(
                "manifest.build_flags.v7_python_wheel.artifact_path_status",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {
                    "field": "build_flags.v7_python_wheel.artifact_path_status",
                    "status": artifact_status,
                },
            )


def _validate_static_targets(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    targets = manifest.get("static_build_targets")
    if not isinstance(targets, Mapping):
        _manifest_add(sink, "static_build_targets", "MANIFEST_FIELD_INVALID")
        return
    for key in STATIC_BUILD_REQUIRED_KEYS:
        if key not in targets:
            _manifest_add(sink, f"static_build_targets.{key}", "MANIFEST_FIELD_MISSING")
            continue
        value = targets.get(key)
        expected = STATIC_BUILD_EXPECTED.get(key)
        if key == "tachiom_static_cmake":
            if value is None:
                status_present, status = _mapping_entry(targets, "tachiom_static_cmake_status")
                if not status_present:
                    status = _sibling_status(targets, "tachiom_static_cmake")
                notes_present, notes = _mapping_entry(targets, "tachiom_static_cmake_notes")
                if not notes_present:
                    notes = _sibling_notes(targets, "tachiom_static_cmake")
                if status != "blocked" or not _non_empty_str(notes):
                    _manifest_add(sink, "static_build_targets.tachiom_static_cmake", "MANIFEST_STATUS_INVALID")
            elif not _non_empty_str(value):
                _manifest_add(sink, "static_build_targets.tachiom_static_cmake", "MANIFEST_FIELD_INVALID")
        elif expected is not None and value != expected:
            _manifest_add(sink, f"static_build_targets.{key}", "MANIFEST_FIELD_INVALID")


def _validate_backend_gate_schema(sink: _Sink, manifest: Mapping[str, Any]) -> Mapping[str, Any] | None:
    gates = manifest.get("backend_gates")
    if not isinstance(gates, Mapping):
        _manifest_add(sink, "backend_gates", "MANIFEST_FIELD_INVALID")
        return None
    for name in REQUIRED_BACKEND_GATES:
        if name not in gates:
            _manifest_add(sink, f"backend_gates.{name}", "MANIFEST_FIELD_MISSING")
            continue
        gate = gates.get(name)
        if not isinstance(gate, Mapping):
            _manifest_add(sink, f"backend_gates.{name}", "MANIFEST_FIELD_INVALID")
            continue
        blocked = gate.get("blocked")
        level = gate.get("evidence_level")
        not_e2 = gate.get("not_e2")
        reason = gate.get("reason")
        malformed = False
        if not _is_bool(blocked):
            malformed = True
        if not _is_bool(not_e2):
            malformed = True
        if not _non_empty_str(reason):
            malformed = True
        if not _allowed_str(level, ALLOWED_EVIDENCE_LEVELS):
            malformed = True
        is_e2_or_e3 = _allowed_str(level, {"E2", "E3"})
        if _is_bool(not_e2) and _allowed_str(level, ALLOWED_EVIDENCE_LEVELS) and not_e2 is not (not is_e2_or_e3):
            malformed = True
        if blocked is True and is_e2_or_e3:
            malformed = True
        if blocked is True and not_e2 is not True:
            malformed = True
        if malformed:
            _manifest_add(sink, f"backend_gates.{name}", "MANIFEST_FIELD_INVALID")
    return gates


def _validate_kind(
    sink: _Sink,
    field: str,
    spec: Mapping[str, Any],
    value: object,
    *,
    present: bool,
) -> bool:
    if not present:
        if spec.get("optional"):
            return False
        _manifest_add(sink, field, "MANIFEST_FIELD_MISSING")
        return False
    kind = str(spec.get("kind") or "")
    null_ok = spec.get("null_ok") is True
    if value is None:
        if null_ok:
            return False
        _manifest_add(sink, field, "MANIFEST_FIELD_MISSING")
        return False
    if not _value_matches_kind(kind, value):
        if kind in {"sha256", "digest"} and isinstance(value, str):
            sink.add(
                f"manifest.{field}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_HASH_FORMAT_INVALID",
                {"field": field},
            )
        elif kind == "completeness" and _non_empty_str(value):
            sink.add(
                f"manifest.{field}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {"field": field, "status": value},
            )
        else:
            _manifest_add(sink, field, "MANIFEST_FIELD_INVALID")
        return False
    expected = spec.get("equals")
    if expected is not None and value != expected:
        _manifest_add(sink, field, "MANIFEST_FIELD_INVALID")
        return False
    return True


def _validate_declared_schema(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    for field, spec in SECTION_32_SCHEMA.items():
        if field not in manifest:
            continue
        _validate_kind(sink, field, spec, manifest.get(field), present=True)
    for field, spec in DUPLICATE_SCALAR_SCHEMA.items():
        _validate_kind(sink, field, spec, manifest.get(field), present=field in manifest)
    for parent, leaves in NESTED_REQUIRED_LEAVES.items():
        container = manifest.get(parent)
        if not isinstance(container, Mapping):
            continue
        for nested_key, spec in leaves.items():
            nested_field = f"{parent}.{nested_key}"
            _validate_kind(sink, nested_field, spec, container.get(nested_key), present=nested_key in container)
    flags = manifest.get("build_flags")
    if isinstance(flags, Mapping):
        wheel = flags.get("v7_python_wheel")
        if isinstance(wheel, Mapping):
            for nested_key, spec in WHEEL_REQUIRED_LEAVES.items():
                _validate_kind(
                    sink,
                    f"build_flags.v7_python_wheel.{nested_key}",
                    spec,
                    wheel.get(nested_key),
                    present=nested_key in wheel,
                )


def _validate_cross_field_identities(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    runtime = manifest.get("mdenseon_package_native_runtime_version")
    tokenizer = manifest.get("tokenizer_identity_version_hash")
    embedding = manifest.get("embedding_dimension_dtype_normalization_batch")
    mineru_model = manifest.get("mineru_model_name_version_weights_hash")
    runtime_obj = runtime if isinstance(runtime, Mapping) else None
    tokenizer_obj = tokenizer if isinstance(tokenizer, Mapping) else None
    embedding_obj = embedding if isinstance(embedding, Mapping) else None
    mineru_obj = mineru_model if isinstance(mineru_model, Mapping) else None

    if tokenizer_obj is not None and runtime_obj is not None:
        if tokenizer_obj.get("version") != runtime_obj.get("revision"):
            _manifest_add(sink, "tokenizer_identity_version_hash.version", "MANIFEST_FIELD_INVALID")
        if "tokenizer_version" in manifest and manifest.get("tokenizer_version") != runtime_obj.get("revision"):
            _manifest_add(sink, "tokenizer_version", "MANIFEST_FIELD_INVALID")

    if tokenizer_obj is not None:
        for top_key, nested_key in TOKENIZER_TOP_TO_NESTED.items():
            if top_key not in manifest:
                continue
            if manifest.get(top_key) != tokenizer_obj.get(nested_key):
                _manifest_add(sink, top_key, "MANIFEST_FIELD_INVALID")

    if embedding_obj is not None:
        if not _is_none_or(embedding_obj.get("dimension"), MDENSEON_EXPECTED_DIMENSION):
            _manifest_add(sink, "embedding_dimension_dtype_normalization_batch.dimension", "MANIFEST_FIELD_INVALID")
        if not _is_none_or(embedding_obj.get("dtype"), MDENSEON_EXPECTED_DTYPE):
            _manifest_add(sink, "embedding_dimension_dtype_normalization_batch.dtype", "MANIFEST_FIELD_INVALID")
        for top_key, nested_key in EMBEDDING_TOP_TO_NESTED.items():
            if top_key not in manifest:
                continue
            if manifest.get(top_key) != embedding_obj.get(nested_key):
                _manifest_add(sink, top_key, "MANIFEST_FIELD_INVALID")

    if mineru_obj is not None:
        for top_key, nested_key in MINERU_TOP_TO_NESTED.items():
            if top_key not in manifest:
                continue
            if manifest.get(top_key) != mineru_obj.get(nested_key):
                _manifest_add(sink, top_key, "MANIFEST_FIELD_INVALID")
        reconstructed = {
            nested_key: manifest.get(top_key)
            for top_key, nested_key in MINERU_TOP_TO_NESTED.items()
            if top_key in manifest
        }
        nested_identity = {key: mineru_obj.get(key) for key in reconstructed}
        if reconstructed and nested_identity != reconstructed:
            _manifest_add(sink, "mineru_model_name_version_weights_hash", "MANIFEST_FIELD_INVALID")

    if "tachiom_envelope_version" in manifest and manifest.get("tachiom_envelope_version") != manifest.get(
        "tachiom_index_format_version"
    ):
        _manifest_add(sink, "tachiom_envelope_version", "MANIFEST_FIELD_INVALID")


def _validate_bm25_config(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    composite = manifest.get(BM25_COMPOSITE_KEY)
    config_hash = manifest.get(BM25_CONFIG_HASH_KEY)
    alias_present = BM25_CONFIG_HASH_KEY in manifest
    composite_status_present, composite_status = _sibling_status_entry(manifest, BM25_COMPOSITE_KEY)
    if not composite_status_present:
        composite_status = _completeness_of(manifest, BM25_COMPOSITE_KEY)
    config_status_present, config_status = _sibling_status_entry(manifest, BM25_CONFIG_HASH_KEY)
    if not config_status_present:
        config_status = None
    composite_completeness_present, composite_completeness = _completeness_entry(manifest, BM25_COMPOSITE_KEY)
    alias_completeness_present, alias_completeness = _completeness_entry(manifest, BM25_CONFIG_HASH_KEY)
    if alias_present and config_hash != composite:
        _manifest_add(sink, BM25_CONFIG_HASH_KEY, "MANIFEST_FIELD_INVALID")
    if (
        config_status is not None
        and composite_status is not None
        and config_status != composite_status
    ):
        _manifest_add(sink, f"{BM25_CONFIG_HASH_KEY}_status", "MANIFEST_STATUS_INVALID")
    if alias_completeness_present:
        if not _allowed_str(alias_completeness, ALLOWED_COMPLETENESS):
            _manifest_add(
                sink,
                f"completeness.{BM25_CONFIG_HASH_KEY}",
                "MANIFEST_STATUS_INVALID",
                {"status": alias_completeness},
            )
        if composite_completeness_present and alias_completeness != composite_completeness:
            _manifest_add(
                sink,
                f"completeness.{BM25_CONFIG_HASH_KEY}",
                "MANIFEST_STATUS_INVALID",
                {"status": alias_completeness},
            )
    if composite is None:
        for key in BM25_SIBLING_KEYS:
            if key not in manifest:
                continue
            value = manifest.get(key)
            if value is not None:
                _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")
                continue
            status = _sibling_status(manifest, key)
            if not _non_empty_str(status) or _allowed_str(status, RECORDED_COMPLETENESS):
                _manifest_add(sink, key, "MANIFEST_STATUS_INVALID", {"status": status})
        if alias_present and config_hash is not None:
            _manifest_add(sink, BM25_CONFIG_HASH_KEY, "MANIFEST_FIELD_INVALID")
        if _allowed_str(composite_status, RECORDED_COMPLETENESS):
            _manifest_add(sink, BM25_COMPOSITE_KEY, "MANIFEST_STATUS_INVALID", {"status": composite_status})
        if alias_present and config_hash is None:
            notes = _sibling_notes(manifest, BM25_CONFIG_HASH_KEY)
            if (
                not _non_empty_str(config_status)
                or _allowed_str(config_status, RECORDED_COMPLETENESS)
                or not _non_empty_str(notes)
            ):
                _manifest_add(sink, BM25_CONFIG_HASH_KEY, "MANIFEST_STATUS_INVALID", {"status": config_status})
            if alias_completeness_present:
                completeness_token = alias_completeness
                completeness_field = f"completeness.{BM25_CONFIG_HASH_KEY}"
            else:
                completeness_token = composite_completeness
                completeness_field = f"completeness.{BM25_COMPOSITE_KEY}"
            if _allowed_str(completeness_token, RECORDED_COMPLETENESS):
                _manifest_add(
                    sink,
                    completeness_field,
                    "MANIFEST_STATUS_INVALID",
                    {"status": completeness_token},
                )
        return
    for key in BM25_SIBLING_KEYS:
        if key not in manifest:
            continue
        value = manifest.get(key)
        if not _non_empty_str(value):
            _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")


def _container_at_path(root: Mapping[str, Any], dotted: str) -> tuple[Mapping[str, Any] | None, str]:
    keys = dotted.split(".")
    container: object = root
    for key in keys[:-1]:
        if not isinstance(container, Mapping) or key not in container:
            return None, keys[-1]
        container = container[key]
    if not isinstance(container, Mapping):
        return None, keys[-1]
    return container, keys[-1]


def _manifest_status_field_specs() -> tuple[tuple[str, frozenset[str]], ...]:
    tag = frozenset(TAG_STATUS_TOKENS)
    generic = frozenset(GENERIC_STATUS_TOKENS)
    completeness = frozenset(ALLOWED_COMPLETENESS)
    specs: list[tuple[str, frozenset[str]]] = []
    for key in (
        "pg_agent_tag_status",
        "flock_tag_status",
        "duckdb_pgagent_tag_status",
        "duckdb_python_pgagent_tag_status",
        "tachiom_tag_status",
        "tachiom_checkout_tag_status",
        "duckdb_tachiom_tag_status",
    ):
        specs.append((key, tag))
    for root in (
        "flock_abi_catalog_version",
        "mineru_runtime_distribution_version",
        "mineru_wheel_sha256",
        "mineru_container_image_digest",
        "mineru_model_name",
        "mineru_model_version",
        "mineru_model_weights_sha256",
        "mineru_model_snapshot_manifest_sha256",
        "mineru_parser_config",
        "mineru_model_name_version_weights_hash",
        "canonical_mineru_contract_version",
        "mdenseon_package_native_runtime_version",
        "mdenseon_model_weights_sha256",
        "tokenizer_identity",
        "tokenizer_version",
        "tokenizer_hash",
        "tokenizer_identity_version_hash",
        "embedding_dimension",
        "embedding_dtype",
        "embedding_normalization",
        "embedding_zero_norm_policy",
        "embedding_batch_contract",
        "embedding_dimension_dtype_normalization_batch",
        "tachiom_static_loadable_artifact_sha256",
        "tachiom_index_format_version",
        "fts_extension_version",
        "fts_extension_semver",
        "build_artifact_wheel_sha256",
        BM25_COMPOSITE_KEY,
        BM25_CONFIG_HASH_KEY,
        *BM25_SIBLING_KEYS,
    ):
        specs.append((f"{root}_status", generic if not str(root).startswith("bm25") else completeness))
    specs.extend(
        (
            ("build_flags.v7_python_wheel.status", completeness),
            ("build_flags.v7_python_wheel.artifact_path_status", completeness),
            ("static_build_targets.tachiom_static_cmake_status", completeness),
            ("embedding_dimension_dtype_normalization_batch.status", completeness),
            ("embedding_dimension_dtype_normalization_batch.batch_contract_status", completeness),
            ("mineru_model_name_version_weights_hash.status", generic),
            ("mineru_model_name_version_weights_hash.single_file_weights_sha256_status", generic),
            ("tokenizer_identity_version_hash.status", generic),
            ("mdenseon_package_native_runtime_version.status", generic),
        )
    )
    return tuple(specs)


SUPPORTED_MANIFEST_STATUS_FIELDS = _manifest_status_field_specs()

# Nested provenance/register observation statuses such as subject_status,
# path_status, build_entry.*.status, MinerU-Popo tag_status, and git tree
# statuses ("not_a_git_source_tree", "no_git") are outside this contract.


def _validate_declared_status_field(
    sink: _Sink,
    container: Mapping[str, Any],
    field: str,
    key: str,
    allowed: Mapping[str, Any] | set[str] | frozenset[str] | Sequence[str],
    *,
    blocker_id: str | None = None,
) -> None:
    present, value = _mapping_entry(container, key)
    if not present:
        return
    _reject_unallowed_enum(sink, field, value, allowed, blocker_id=blocker_id)
    if key.endswith("_status"):
        value_key = key[: -len("_status")]
        value_present, associated = _mapping_entry(container, value_key)
        if value_present and associated is None and _allowed_str(value, RECORDED_COMPLETENESS):
            _reject_unallowed_enum(sink, field, value, (), extra={"associated": None}, blocker_id=blocker_id)
        notes_field = field[: -len("_status")] + "_notes" if field.endswith("_status") else f"{value_key}_notes"
        _validate_present_notes(sink, container, notes_field, f"{value_key}_notes")
        return
    if key == "status":
        notes_field = f"{field.rsplit('.', 1)[0]}.notes" if "." in field else "notes"
        _validate_present_notes(sink, container, notes_field, "notes")


def _validate_present_status_contract(
    sink: _Sink,
    manifest: Mapping[str, Any],
    completeness: Mapping[str, Any],
    *,
    baselines: Mapping[str, Any] | None = None,
    corrections: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    register: Mapping[str, Any] | None = None,
) -> None:
    if isinstance(completeness, Mapping):
        for key, token in completeness.items():
            _reject_unallowed_enum(sink, f"completeness.{key}", token, ALLOWED_COMPLETENESS, {"field": key})

    seen_fields: set[str] = set()
    for field, allowed in SUPPORTED_MANIFEST_STATUS_FIELDS:
        container, key = _container_at_path(manifest, field)
        if container is None:
            continue
        seen_fields.add(field)
        _validate_declared_status_field(sink, container, field, key, allowed)

    embedding_field = "embedding_dimension_dtype_normalization_batch"
    embedding = manifest.get(embedding_field)
    if isinstance(embedding, Mapping):
        _validate_present_notes(sink, embedding, f"{embedding_field}.batch_contract_notes", "batch_contract_notes")

    flags = manifest.get("build_flags")
    wheel = flags.get("v7_python_wheel") if isinstance(flags, Mapping) else None
    if isinstance(wheel, Mapping):
        _validate_present_notes(sink, wheel, "build_flags.v7_python_wheel.notes", "notes")

    for field in REQUIRED_HASH_FIELDS:
        value = manifest.get(field) if field in manifest else None
        if not isinstance(value, Mapping):
            continue
        for nested_key in value:
            if _is_meta_key(nested_key) or not HASH_KEY_RE.search(nested_key):
                continue
            nested_field = f"{field}.{nested_key}_status"
            if nested_field in seen_fields:
                continue
            _validate_declared_status_field(
                sink,
                value,
                nested_field,
                f"{nested_key}_status",
                GENERIC_STATUS_TOKENS,
            )

    gates = manifest.get("backend_gates")
    if isinstance(gates, Mapping):
        for name, gate in gates.items():
            if not isinstance(gate, Mapping):
                continue
            _validate_present_enum(
                sink,
                gate,
                f"backend_gates.{name}.evidence_level",
                "evidence_level",
                ALLOWED_EVIDENCE_LEVELS,
                required=name in REQUIRED_BACKEND_GATES,
            )

    if isinstance(baselines, Mapping):
        items = baselines.get("items")
        if isinstance(items, Mapping):
            for item_id, item in items.items():
                if not isinstance(item, Mapping):
                    continue
                _validate_declared_status_field(
                    sink,
                    item,
                    f"baselines.{item_id}.evidence_level",
                    "evidence_level",
                    ALLOWED_EVIDENCE_LEVELS,
                )

    if isinstance(corrections, Mapping):
        rows = corrections.get("corrections")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping) or not _non_empty_str(row.get("id")):
                    continue
                cid = str(row.get("id"))
                _validate_declared_status_field(
                    sink,
                    row,
                    f"corrections_register.{cid}.status",
                    "status",
                    CORRECTION_STATUSES,
                )

    if isinstance(register, Mapping):
        rows = register.get("contracts")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping) or not _non_empty_str(row.get("id")):
                    continue
                cid = str(row.get("id"))
                _validate_declared_status_field(
                    sink,
                    row,
                    f"evidence_register.{cid}.level",
                    "level",
                    ALLOWED_EVIDENCE_LEVELS,
                )

    if isinstance(provenance, Mapping):
        repos = provenance.get("repos")
        if isinstance(repos, Mapping):
            for repo_name in (name for name, _key in FOUR_REPO_COMMIT_KEYS):
                row = repos.get(repo_name)
                if not isinstance(row, Mapping):
                    continue
                present, status = _mapping_entry(row, "tag_status")
                if present:
                    _reject_unallowed_enum(
                        sink,
                        f"repos.{repo_name}.tag_status",
                        status,
                        TAG_STATUS_TOKENS,
                        blocker_id=f"provenance.repos.{repo_name}.tag_status",
                    )
                submodules = row.get("submodules") if repo_name == "flock" else None
                if isinstance(submodules, Mapping):
                    for sub_name in FLOCK_SUBMODULE_ORDER:
                        sub = submodules.get(sub_name)
                        if not isinstance(sub, Mapping):
                            continue
                        present, status = _mapping_entry(sub, "status")
                        if present:
                            _reject_unallowed_enum(
                                sink,
                                f"repos.flock.submodules.{sub_name}.status",
                                status,
                                FLOCK_SUBMODULE_STATUSES,
                                blocker_id=f"provenance.repos.flock.submodules.{sub_name}.status",
                            )
        external = provenance.get("external_not_four_repo")
        if isinstance(external, Mapping):
            for name in ("tachiom", "duckdb-tachiom"):
                row = external.get(name)
                if not isinstance(row, Mapping):
                    continue
                present, status = _mapping_entry(row, "tag_status")
                if present:
                    _reject_unallowed_enum(
                        sink,
                        f"external_not_four_repo.{name}.tag_status",
                        status,
                        TAG_STATUS_TOKENS,
                        blocker_id=f"provenance.external_not_four_repo.{name}.tag_status",
                    )


def _validate_manifest_contract(
    sink: _Sink,
    manifest: Mapping[str, Any],
    *,
    baselines: Mapping[str, Any] | None = None,
    corrections: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    register: Mapping[str, Any] | None = None,
) -> None:
    completeness = manifest.get("completeness")
    if not isinstance(completeness, Mapping):
        _manifest_add(sink, "completeness", "MANIFEST_FIELD_INVALID")
        completeness = {}
    _validate_present_status_contract(
        sink,
        manifest,
        completeness,
        baselines=baselines,
        corrections=corrections,
        provenance=provenance,
        register=register,
    )

    for key in SECTION_32_REQUIRED_FIELDS:
        if key not in manifest:
            _manifest_add(sink, key, "MANIFEST_FIELD_MISSING")
            continue
        if key not in completeness:
            _manifest_add(sink, f"completeness.{key}", "MANIFEST_FIELD_MISSING")
            token = None
        else:
            token = completeness.get(key)
            if not _allowed_str(token, ALLOWED_COMPLETENESS):
                sink.add(
                    f"manifest.completeness.{key}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"field": key, "status": token},
                )
        value = manifest.get(key)
        if value is None and _allowed_str(token, RECORDED_COMPLETENESS):
            sink.add(
                f"manifest.completeness.{key}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {"field": key, "status": token},
            )
        if key in COMMIT_40_KEYS and value is not None and not _is_commit(value):
            _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")

    if "python_version" in manifest and manifest.get("python_version") is not None and not _non_empty_str(manifest.get("python_version")):
        _manifest_add(sink, "python_version", "MANIFEST_FIELD_INVALID")
    index_format = manifest.get("tachiom_index_format_version")
    if index_format is not None and not _is_int(index_format):
        _manifest_add(sink, "tachiom_index_format_version", "MANIFEST_FIELD_INVALID")

    _validate_declared_schema(sink, manifest)
    _validate_mineru_parser_config(sink, manifest)
    _validate_mineru_model_hash(sink, manifest, completeness)
    _validate_mdenseon_runtime(sink, manifest)
    _validate_tokenizer_hash(sink, manifest)
    _validate_embedding_composite(sink, manifest, completeness)
    _validate_v7_wheel(sink, manifest)
    _validate_static_targets(sink, manifest)
    _validate_backend_gate_schema(sink, manifest)
    _validate_cross_field_identities(sink, manifest)
    _validate_bm25_config(sink, manifest)

    for key in REQUIRED_HASH_FIELDS:
        value = manifest.get(key)
        if value is None:
            continue
        if key in DIGEST_FIELDS:
            if not _is_digest(value):
                if isinstance(value, str):
                    sink.add(
                        f"manifest.{key}",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_HASH_FORMAT_INVALID",
                        {"field": key},
                    )
                else:
                    _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")
            continue
        if key in SCALAR_HASH_FIELDS:
            if isinstance(value, str):
                if not _is_sha256(value):
                    sink.add(
                        f"manifest.{key}",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_HASH_FORMAT_INVALID",
                        {"field": key},
                    )
            else:
                _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")
            continue
        if isinstance(value, str):
            if not SHA256_RE.match(value):
                sink.add(
                    f"manifest.{key}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_HASH_FORMAT_INVALID",
                    {"field": key},
                )
        elif isinstance(value, Mapping) and key in MAPPING_HASH_FIELDS:
            for nested_key, nested_val in value.items():
                if _is_meta_key(nested_key) or not HASH_KEY_RE.search(nested_key) or nested_val is None:
                    continue
                if not _is_sha256(nested_val):
                    sink.add(
                        f"manifest.{key}.{nested_key}",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_HASH_FORMAT_INVALID",
                        {"field": f"{key}.{nested_key}"},
                    )
        else:
            _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")


def _validate_identity_pins(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    if manifest.get("duckdb_pgagent_commit") != DUCKDB_PGAGENT_COMMIT:
        _manifest_add(sink, "duckdb_pgagent_commit", "MANIFEST_FIELD_INVALID")
    if manifest.get("duckdb_pgagent_tag") != NEAREST_BUILD_TAG:
        _manifest_add(sink, "duckdb_pgagent_tag", "MANIFEST_FIELD_INVALID")
    vendored = manifest.get("duckdb_python_pgagent_vendored_engine_commit")
    if not _is_commit(vendored) or vendored != manifest.get("duckdb_pgagent_commit"):
        _manifest_add(sink, "duckdb_python_pgagent_vendored_engine_commit", "MANIFEST_FIELD_INVALID")
    if manifest.get("duckdb_python_pgagent_vendored_engine_equals_target") is not True:
        _manifest_add(sink, "duckdb_python_pgagent_vendored_engine_equals_target", "MANIFEST_FIELD_INVALID")
    for tag_key, tag_commit_key, pin_key in TAG_COMMIT_PAIRS:
        tag = manifest.get(tag_key)
        if not _non_empty_str(tag):
            _manifest_add(sink, tag_key, "MANIFEST_FIELD_INVALID")
            continue
        tag_commit = manifest.get(tag_commit_key)
        if not _is_commit(tag_commit) or tag_commit != manifest.get(pin_key):
            _manifest_add(sink, tag_commit_key, "MANIFEST_FIELD_INVALID")
    if manifest.get("tachiom_commit") != TACHIOM_TAG_COMMIT:
        _manifest_add(sink, "tachiom_commit", "MANIFEST_FIELD_INVALID")
    if manifest.get("tachiom_tag") != TACHIOM_TAG:
        _manifest_add(sink, "tachiom_tag", "MANIFEST_FIELD_INVALID")
    if manifest.get("tachiom_tag_commit") != manifest.get("tachiom_commit"):
        _manifest_add(sink, "tachiom_tag_commit", "MANIFEST_FIELD_INVALID")
    cargo_tag_pin = manifest.get(CARGO_TACHIOM_GIT_TAG_PIN_KEY)
    if CARGO_TACHIOM_GIT_TAG_PIN_KEY not in manifest:
        _manifest_add(sink, CARGO_TACHIOM_GIT_TAG_PIN_KEY, "MANIFEST_FIELD_MISSING")
    elif cargo_tag_pin != TACHIOM_TAG or cargo_tag_pin != manifest.get("tachiom_tag"):
        _manifest_add(sink, CARGO_TACHIOM_GIT_TAG_PIN_KEY, "MANIFEST_FIELD_INVALID")
    if manifest.get(CARGO_TACHIOM_GIT_TAG_PIN_COMMIT_KEY) != manifest.get("tachiom_commit"):
        _manifest_add(sink, CARGO_TACHIOM_GIT_TAG_PIN_COMMIT_KEY, "MANIFEST_FIELD_INVALID")
    if manifest.get("tachiom_commit_kind") != "cargo_resolved_build_identity":
        _manifest_add(sink, "tachiom_commit_kind", "MANIFEST_FIELD_INVALID")
    checkout = manifest.get("tachiom_checkout_commit")
    if not _is_commit(checkout):
        _manifest_add(sink, "tachiom_checkout_commit", "MANIFEST_FIELD_INVALID")
    elif checkout == manifest.get("tachiom_commit") or checkout == TACHIOM_TAG_COMMIT:
        _manifest_add(sink, "tachiom_checkout_commit", "MANIFEST_FIELD_INVALID")
    if manifest.get("tachiom_checkout_is_build_identity") is not False:
        _manifest_add(sink, "tachiom_checkout_is_build_identity", "MANIFEST_FIELD_INVALID")
    if not _non_empty_str(manifest.get("tachiom_checkout_describe")):
        _manifest_add(sink, "tachiom_checkout_describe", "MANIFEST_FIELD_INVALID")
    _validate_manifest_tag_observation(sink, manifest, "tachiom_checkout_tag", "tachiom_checkout_tag_status")
    _validate_manifest_tag_observation(sink, manifest, "duckdb_tachiom_tag", "duckdb_tachiom_tag_status")
    for _name, key in DIRTY_AGREEMENT_KEYS:
        if not _is_bool(manifest.get(key)):
            _manifest_add(sink, key, "MANIFEST_FIELD_INVALID")


def _validate_provenance(sink: _Sink, manifest: Mapping[str, Any], provenance: Mapping[str, Any] | None) -> None:
    if not isinstance(provenance, Mapping):
        sink.add(
            "provenance",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance"},
        )
        return
    repos = provenance.get("repos")
    if not isinstance(repos, Mapping):
        sink.add(
            "provenance.repos",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.repos"},
        )
        repos = {}
    for repo_name, manifest_key in FOUR_REPO_COMMIT_KEYS:
        row = repos.get(repo_name)
        if not isinstance(row, Mapping):
            sink.add(
                f"provenance.repos.{repo_name}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_MISSING",
                {"field": f"provenance.repos.{repo_name}"},
            )
            continue
        if not _is_commit(row.get("commit")):
            sink.add(
                f"provenance.repos.{repo_name}.commit",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.repos.{repo_name}.commit"},
            )
        elif row.get("commit") != manifest.get(manifest_key):
            sink.add(
                f"provenance.repos.{repo_name}.commit",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.repos.{repo_name}.commit"},
            )
        if not _non_empty_str(row.get("branch")):
            sink.add(
                f"provenance.repos.{repo_name}.branch",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.repos.{repo_name}.branch"},
            )
        if not _is_bool(row.get("dirty")):
            sink.add(
                f"provenance.repos.{repo_name}.dirty",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.repos.{repo_name}.dirty"},
            )
        tag = row.get("tag")
        if tag is not None and not _non_empty_str(tag):
            sink.add(
                f"provenance.repos.{repo_name}.tag",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.repos.{repo_name}.tag"},
            )
    for repo_name, manifest_key in FOUR_REPO_TAG_KEYS:
        row = repos.get(repo_name)
        if not isinstance(row, Mapping):
            continue
        if row.get("tag") != manifest.get(manifest_key):
            sink.add(
                f"provenance.repos.{repo_name}.tag",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.repos.{repo_name}.tag"},
            )
    duckdb_row = repos.get("duckdb-pgagent") if isinstance(repos.get("duckdb-pgagent"), Mapping) else None
    if duckdb_row is not None and not _is_none_or(duckdb_row.get("commit"), DUCKDB_PGAGENT_COMMIT) and _is_commit(duckdb_row.get("commit")):
        sink.add(
            "provenance.repos.duckdb-pgagent.commit",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.repos.duckdb-pgagent.commit"},
        )
    if duckdb_row is not None and not _is_none_or(duckdb_row.get("tag"), NEAREST_BUILD_TAG) and _non_empty_str(duckdb_row.get("tag")):
        sink.add(
            "provenance.repos.duckdb-pgagent.tag",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.repos.duckdb-pgagent.tag"},
        )
    python_row = repos.get("duckdb-python-pgagent") if isinstance(repos.get("duckdb-python-pgagent"), Mapping) else None
    if isinstance(python_row, Mapping):
        vendored = python_row.get("vendored_engine")
        if not isinstance(vendored, Mapping):
            sink.add(
                "provenance.repos.duckdb-python-pgagent.vendored_engine.commit",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "provenance.repos.duckdb-python-pgagent.vendored_engine.commit"},
            )
        else:
            if not _is_commit(vendored.get("commit")) or vendored.get("commit") != manifest.get("duckdb_pgagent_commit"):
                sink.add(
                    "provenance.repos.duckdb-python-pgagent.vendored_engine.commit",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "provenance.repos.duckdb-python-pgagent.vendored_engine.commit"},
                )
            if vendored.get("matches_duckdb_pgagent") is not True:
                sink.add(
                    "provenance.repos.duckdb-python-pgagent.vendored_engine.matches_duckdb_pgagent",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "provenance.repos.duckdb-python-pgagent.vendored_engine.matches_duckdb_pgagent"},
                )
    flock_row = repos.get("flock") if isinstance(repos.get("flock"), Mapping) else None
    if isinstance(flock_row, Mapping):
        subs = flock_row.get("submodules")
        if not isinstance(subs, Mapping):
            sink.add(
                "provenance.repos.flock.submodules",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "provenance.repos.flock.submodules"},
            )
        else:
            for sub_name in FLOCK_SUBMODULE_ORDER:
                sub = subs.get(sub_name)
                if not isinstance(sub, Mapping):
                    sink.add(
                        f"provenance.repos.flock.submodules.{sub_name}",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_FIELD_MISSING",
                        {"field": f"provenance.repos.flock.submodules.{sub_name}"},
                    )
                    continue
                if not _is_commit(sub.get("recorded_gitlink")):
                    sink.add(
                        f"provenance.repos.flock.submodules.{sub_name}.recorded_gitlink",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_FIELD_INVALID",
                        {"field": f"provenance.repos.flock.submodules.{sub_name}.recorded_gitlink"},
                    )
                if not _is_bool(sub.get("initialized")):
                    sink.add(
                        f"provenance.repos.flock.submodules.{sub_name}.initialized",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_FIELD_INVALID",
                        {"field": f"provenance.repos.flock.submodules.{sub_name}.initialized"},
                    )
                status = sub.get("status")
                initialized = sub.get("initialized")
                if not _allowed_str(status, FLOCK_SUBMODULE_STATUSES):
                    sink.add(
                        f"provenance.repos.flock.submodules.{sub_name}.status",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_FIELD_INVALID" if not _non_empty_str(status) else "MANIFEST_STATUS_INVALID",
                        {"field": f"provenance.repos.flock.submodules.{sub_name}.status"},
                    )
                elif _is_bool(initialized) and (initialized is True) != (status == FLOCK_SUBMODULE_STATUS_OK):
                    sink.add(
                        f"provenance.repos.flock.submodules.{sub_name}.status",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_STATUS_INVALID",
                        {"field": f"provenance.repos.flock.submodules.{sub_name}.status"},
                    )
                required_gitlink = FLOCK_SUBMODULE_OK_GITLINKS.get(sub_name)
                claimed_ok = status == FLOCK_SUBMODULE_STATUS_OK
                # Only status==ok may satisfy the frozen gitlink; blocked uninitialized may keep a mismatch.
                if (
                    required_gitlink is not None
                    and claimed_ok
                    and _is_commit(sub.get("recorded_gitlink"))
                    and sub.get("recorded_gitlink") != required_gitlink
                ):
                    sink.add(
                        f"provenance.repos.flock.submodules.{sub_name}.status",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_STATUS_INVALID",
                        {"field": f"provenance.repos.flock.submodules.{sub_name}.status"},
                    )
    external = provenance.get("external_not_four_repo")
    if not isinstance(external, Mapping):
        sink.add(
            "provenance.external_not_four_repo",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.external_not_four_repo"},
        )
        external = {}
    for name in ("tachiom", "duckdb-tachiom"):
        row = external.get(name)
        if not isinstance(row, Mapping):
            sink.add(
                f"provenance.external_not_four_repo.{name}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_MISSING",
                {"field": f"provenance.external_not_four_repo.{name}"},
            )
            continue
        if not _is_commit(row.get("commit")):
            sink.add(
                f"provenance.external_not_four_repo.{name}.commit",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.external_not_four_repo.{name}.commit"},
            )
        else:
            expected = (
                manifest.get("tachiom_checkout_commit")
                if name == "tachiom"
                else manifest.get("duckdb_tachiom_commit")
            )
            if row.get("commit") != expected:
                sink.add(
                    f"provenance.external_not_four_repo.{name}.commit",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": f"provenance.external_not_four_repo.{name}.commit"},
                )
        if not _is_bool(row.get("dirty")):
            sink.add(
                f"provenance.external_not_four_repo.{name}.dirty",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"provenance.external_not_four_repo.{name}.dirty"},
            )
        _validate_external_tag_observation(sink, manifest, name, row)
    _validate_dirty_agreement(sink, manifest, provenance)
    exact = provenance.get("static_build_targets_exact")
    man_targets = manifest.get("static_build_targets") if isinstance(manifest.get("static_build_targets"), Mapping) else {}
    if not isinstance(exact, Mapping):
        sink.add(
            "provenance.static_build_targets_exact",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.static_build_targets_exact"},
        )
        return
    flock = exact.get("flock") if isinstance(exact.get("flock"), Mapping) else None
    fts = exact.get("fts") if isinstance(exact.get("fts"), Mapping) else None
    tachiom = exact.get("tachiom") if isinstance(exact.get("tachiom"), Mapping) else None
    python_loader = exact.get("python_loader") if isinstance(exact.get("python_loader"), Mapping) else None
    if flock is None or flock.get("static_cmake_target") != man_targets.get("flock_static"):
        sink.add(
            "provenance.static_build_targets_exact.flock",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.static_build_targets_exact.flock"},
        )
    if fts is None or fts.get("static_cmake_target") != man_targets.get("fts_static"):
        sink.add(
            "provenance.static_build_targets_exact.fts",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.static_build_targets_exact.fts"},
        )
    if tachiom is None or tachiom.get("static_cmake_target") != man_targets.get("tachiom_static_cmake"):
        sink.add(
            "provenance.static_build_targets_exact.tachiom",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.static_build_targets_exact.tachiom"},
        )
    if python_loader is None or python_loader.get("python_module_target") != man_targets.get("python_module"):
        sink.add(
            "provenance.static_build_targets_exact.python_loader",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "provenance.static_build_targets_exact.python_loader"},
        )


def _relation_for_backend_gate(gate_name: str) -> Mapping[str, Any] | None:
    for spec in BASELINE_RELATIONS:
        if spec["backend_gate"] == gate_name:
            return spec
    return None


def _baseline_phase0_pass_required(relation: Mapping[str, Any] | None) -> bool:
    if not isinstance(relation, Mapping):
        return True
    return relation.get("phase0_pass_required", True) is not False


def _phase0_pass_exempt_unavailable_item(
    item: object,
    relation: Mapping[str, Any] | None,
    gate: object,
) -> bool:
    """Option B: honest unavailable live_mineru_runtime is not a pass blocker.

    Exempt does not apply when the baseline item is absent or dishonest.
    Never treats live_runtime_missing false as pass-exempt.
    """
    if not isinstance(relation, Mapping) or not isinstance(item, Mapping):
        return False
    if _baseline_phase0_pass_required(relation):
        return False
    gate_name = str(relation.get("backend_gate") or "")
    if gate_name not in PHASE0_PASS_EXEMPT_BACKEND_GATES:
        return False
    if item.get("contract_frozen") is not True:
        return False
    if item.get("live_runtime_missing") is not True:
        return False
    if item.get("implementation_allowed") is not False:
        return False
    if item.get("release_allowed") is not False:
        return False
    if not _gate_matches_baseline_availability(gate, False):
        return False
    components = item.get("evidence_components")
    live = components.get("live_or_fixture") if isinstance(components, Mapping) else None
    if not isinstance(live, Mapping):
        return False
    expected_kind = relation.get("live_or_fixture_component_kind")
    if expected_kind is not None and live.get("kind") != expected_kind:
        return False
    if live.get("level") != "E0":
        return False
    return True


def _validate_backend_gates(
    sink: _Sink,
    manifest: Mapping[str, Any],
    baselines: Mapping[str, Any] | None = None,
) -> None:
    gates = manifest.get("backend_gates")
    if not isinstance(gates, Mapping):
        return
    items = baselines.get("items") if isinstance(baselines, Mapping) else None
    for name in REQUIRED_BACKEND_GATES:
        gate = gates.get(name)
        if not isinstance(gate, Mapping):
            continue
        blocked = gate.get("blocked")
        level = gate.get("evidence_level")
        not_e2 = gate.get("not_e2")
        if not _is_bool(blocked) or not _allowed_str(level, ALLOWED_EVIDENCE_LEVELS):
            continue
        if blocked is True and (_allowed_str(level, {"E2", "E3"}) or not_e2 is not True):
            continue
        if blocked is True:
            relation = _relation_for_backend_gate(name)
            item = items.get(relation["baseline_id"]) if isinstance(items, Mapping) and relation else None
            if _phase0_pass_exempt_unavailable_item(item, relation, gate):
                continue
            sink.add(name, BLOCKER_CLASS_BLOCKERS, "BACKEND_GATE_BLOCKED", {"gate": name})


def _evidence_meets(level: object, required: str) -> bool:
    left = _evidence_rank_of(level)
    right = _evidence_rank_of(required)
    return left is not None and right is not None and left >= right


def _baseline_bool_fields_typed(item: Mapping[str, Any]) -> bool:
    return all(_is_bool(item.get(field)) for field in BASELINE_BOOL_FIELDS)


def _baseline_requires_live_runtime(relation: Mapping[str, Any] | None) -> bool:
    """Fixture-kind items can be available without a live service/runtime."""
    if not isinstance(relation, Mapping):
        return True
    return relation.get("live_or_fixture_component_kind") != "fixtures"


def _baseline_live_blocks(item: Mapping[str, Any], relation: Mapping[str, Any] | None) -> bool:
    return item.get("live_runtime_missing") is True and _baseline_requires_live_runtime(relation)


def _baseline_flag_coherence_ok(
    item: Mapping[str, Any],
    relation: Mapping[str, Any] | None = None,
) -> bool:
    if not _baseline_bool_fields_typed(item):
        return False
    frozen = item.get("contract_frozen") is True
    fixture_missing = item.get("acceptance_fixture_missing") is True
    impl = item.get("implementation_allowed") is True
    rel = item.get("release_allowed") is True
    if rel and not impl:
        return False
    if (impl or rel) and (not frozen or _baseline_live_blocks(item, relation) or fixture_missing):
        return False
    return True


def _baseline_available(
    item: Mapping[str, Any],
    required: str = "E2",
    relation: Mapping[str, Any] | None = None,
) -> bool:
    return (
        _baseline_bool_fields_typed(item)
        and _baseline_flag_coherence_ok(item, relation)
        and item.get("contract_frozen") is True
        and item.get("acceptance_fixture_missing") is False
        and not _baseline_live_blocks(item, relation)
        and item.get("implementation_allowed") is True
        and item.get("release_allowed") is True
        and _evidence_meets(item.get("evidence_level"), required)
    )


def _gate_matches_baseline_availability(gate: object, available: bool) -> bool:
    if not isinstance(gate, Mapping):
        return False
    blocked = gate.get("blocked")
    not_e2 = gate.get("not_e2")
    level = gate.get("evidence_level")
    if not _is_bool(blocked) or not _is_bool(not_e2) or not _allowed_str(level, ALLOWED_EVIDENCE_LEVELS):
        return False
    if available:
        return blocked is False and not_e2 is False and _evidence_meets(level, "E2")
    return blocked is True and not_e2 is True and not _evidence_meets(level, "E2")


def _min_evidence_level(levels: Sequence[object]) -> str | None:
    ranked = [level for level in levels if _evidence_rank_of(level) is not None]
    if not ranked:
        return None
    return min(ranked, key=lambda level: int(_evidence_rank_of(level) or 0))


def _validate_evidence_components(
    sink: _Sink,
    item_id: str,
    item: Mapping[str, Any],
    relation: Mapping[str, Any],
    register_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    overall = item.get("evidence_level")
    required = str(relation.get("required_evidence_level") or "E2")
    components = item.get("evidence_components")
    contract_id = relation.get("contract_id")
    expected_kind = relation.get("contract_component_kind")
    live_kind = relation.get("live_or_fixture_component_kind")
    split_required = expected_kind is not None and not _evidence_meets(overall, required)
    if split_required and not isinstance(components, Mapping):
        sink.add(
            f"manifest.baselines.{item_id}.evidence_components",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"item": item_id, "field": "evidence_components"},
        )
        return
    if components is None:
        return
    if not isinstance(components, Mapping):
        sink.add(
            f"manifest.baselines.{item_id}.evidence_components",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"item": item_id, "field": "evidence_components"},
        )
        return
    allowed_component_keys = {"contract", "live_or_fixture"}
    if any(key not in allowed_component_keys for key in components):
        sink.add(
            f"manifest.baselines.{item_id}.evidence_components",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"item": item_id, "field": "evidence_components"},
        )
    contract = components.get("contract")
    live = components.get("live_or_fixture")
    component_levels: list[object] = []
    if split_required or "contract" in components:
        if not isinstance(contract, Mapping):
            sink.add(
                f"manifest.baselines.{item_id}.evidence_components.contract",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"item": item_id, "field": "evidence_components.contract"},
            )
        else:
            c_level = contract.get("level")
            c_kind = contract.get("kind")
            c_id = contract.get("id")
            component_levels.append(c_level)
            if (
                not _allowed_str(c_level, ALLOWED_EVIDENCE_LEVELS)
                or not _allowed_str(c_kind, ALLOWED_CONTRACT_COMPONENT_KINDS)
                or (expected_kind is not None and c_kind != expected_kind)
                or (contract_id is not None and c_id != contract_id)
                or (contract_id is None and c_id is not None)
            ):
                sink.add(
                    f"manifest.baselines.{item_id}.evidence_components.contract",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"item": item_id, "field": "evidence_components.contract"},
                )
            row = register_by_id.get(str(contract_id)) if contract_id else None
            if isinstance(row, Mapping) and _allowed_str(c_level, ALLOWED_EVIDENCE_LEVELS) and row.get("level") != c_level:
                sink.add(
                    f"manifest.baselines.{item_id}.evidence_components.contract",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"item": item_id, "field": "evidence_components.contract"},
                )
    if split_required or "live_or_fixture" in components:
        if not isinstance(live, Mapping):
            sink.add(
                f"manifest.baselines.{item_id}.evidence_components.live_or_fixture",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"item": item_id, "field": "evidence_components.live_or_fixture"},
            )
        else:
            l_level = live.get("level")
            l_kind = live.get("kind")
            component_levels.append(l_level)
            if (
                not _allowed_str(l_level, ALLOWED_EVIDENCE_LEVELS)
                or not _allowed_str(l_kind, ALLOWED_LIVE_OR_FIXTURE_COMPONENT_KINDS)
                or (live_kind is not None and l_kind != live_kind)
            ):
                sink.add(
                    f"manifest.baselines.{item_id}.evidence_components.live_or_fixture",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"item": item_id, "field": "evidence_components.live_or_fixture"},
                )
            missing_blocks_e2 = item.get("acceptance_fixture_missing") is True or (
                _baseline_requires_live_runtime(relation) and item.get("live_runtime_missing") is True
            )
            if missing_blocks_e2:
                if not _is_none_or(l_level, "E0"):
                    sink.add(
                        f"manifest.baselines.{item_id}.evidence_components.live_or_fixture",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_STATUS_INVALID",
                        {"item": item_id, "field": "evidence_components.live_or_fixture"},
                    )
    min_level = _min_evidence_level(component_levels)
    if min_level is not None and _allowed_str(overall, ALLOWED_EVIDENCE_LEVELS) and overall != min_level:
        sink.add(
            f"manifest.baselines.{item_id}.evidence_level",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_STATUS_INVALID",
            {"item": item_id, "field": "evidence_level"},
        )


def _validate_baselines(sink: _Sink, baselines: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    items = baselines.get("items") if isinstance(baselines, Mapping) else None
    if not isinstance(items, Mapping):
        items = {}
    gates = manifest.get("backend_gates") if isinstance(manifest.get("backend_gates"), Mapping) else {}
    for item_id in REQUIRED_BASELINE_IDS:
        blocker_id = item_id if item_id not in REQUIRED_BACKEND_GATES else f"baseline.{item_id}"
        relation = BASELINE_RELATION_BY_ID[item_id]
        required = str(relation["required_evidence_level"])
        expected_gate = relation["backend_gate"]
        item = items.get(item_id)
        gate = gates.get(expected_gate) if isinstance(gates, Mapping) else None
        if not isinstance(item, Mapping):
            sink.add(
                blocker_id,
                BLOCKER_CLASS_MISSING_BASELINES,
                "BASELINE_MISSING_OR_UNAVAILABLE",
                {"item": item_id, "missing": True},
            )
            if not _gate_matches_baseline_availability(gate, False):
                sink.add(
                    f"manifest.backend_gates.{expected_gate}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"item": item_id, "gate": expected_gate, "available": False},
                )
            continue
        bools_ok = _baseline_bool_fields_typed(item)
        live_missing = item.get("live_runtime_missing") is True
        fixture_missing = item.get("acceptance_fixture_missing") is True
        available = _baseline_available(item, required, relation)
        if not available:
            details: dict[str, Any] = {"item": item_id, "required_evidence_level": required}
            if not bools_ok:
                details["invalid_bool_fields"] = True
            details["live_runtime_missing"] = bool(item.get("live_runtime_missing"))
            details["acceptance_fixture_missing"] = bool(item.get("acceptance_fixture_missing"))
            details["evidence_level"] = item.get("evidence_level")
            if not _phase0_pass_exempt_unavailable_item(item, relation, gate):
                sink.add(blocker_id, BLOCKER_CLASS_MISSING_BASELINES, "BASELINE_MISSING_OR_UNAVAILABLE", details)
        if not _allowed_str(item.get("evidence_level"), ALLOWED_EVIDENCE_LEVELS):
            sink.add(
                f"manifest.baselines.{item_id}.evidence_level",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"item": item_id, "field": "evidence_level"},
            )
        if not _non_empty_str(item.get("notes")):
            sink.add(
                f"manifest.baselines.{item_id}.notes",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"item": item_id, "field": "notes"},
            )
        if item.get("blocked_backend") != expected_gate:
            sink.add(
                f"manifest.baselines.{item_id}.blocked_backend",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"item": item_id, "field": "blocked_backend"},
            )
        if bools_ok:
            frozen = item.get("contract_frozen") is True
            impl = item.get("implementation_allowed") is True
            rel = item.get("release_allowed") is True
            blocking_live = _baseline_live_blocks(item, relation)
            if (not frozen and (impl or rel)) or ((blocking_live or fixture_missing) and (impl or rel)):
                sink.add(
                    f"manifest.baselines.{item_id}.implementation_allowed",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"item": item_id},
                )
            elif rel and not impl:
                sink.add(
                    f"manifest.baselines.{item_id}.release_allowed",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"item": item_id},
                )
            elif impl and (not frozen or blocking_live or fixture_missing):
                sink.add(
                    f"manifest.baselines.{item_id}.implementation_allowed",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"item": item_id},
                )
        if not _gate_matches_baseline_availability(gate, available):
            sink.add(
                f"manifest.backend_gates.{expected_gate}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {
                    "item": item_id,
                    "gate": expected_gate,
                    "available": available,
                    "direction": "blocked_gate" if available else "unblocked_gate",
                },
            )


CORRECTION_COUNT_KEYS = (
    "unique_unresolved",
    "unique_partial",
    "unique_unresolved_ids",
    "unique_partial_ids",
)


def _correction_alias_edges(by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    edges: dict[str, str] = {}
    for cid, row in by_id.items():
        alias = row.get("alias_of")
        if _non_empty_str(alias):
            edges[cid] = str(alias)
    return edges


def _correction_alias_cycle_nodes(edges: Mapping[str, str]) -> set[str]:
    in_cycle: set[str] = set()
    for start in edges:
        seen: list[str] = []
        walking: set[str] = set()
        node: str | None = start
        while node is not None and node in edges:
            if node in walking:
                idx = seen.index(node) if node in seen else 0
                in_cycle.update(seen[idx:])
                in_cycle.add(node)
                break
            walking.add(node)
            seen.append(node)
            node = edges.get(node)
    return in_cycle


def _correction_alias_reason(cid: str, row: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]], cycles: set[str]) -> str | None:
    alias = row.get("alias_of")
    if alias is None:
        return None
    if not _non_empty_str(alias):
        return "invalid_target"
    target_id = str(alias)
    if target_id == cid:
        return "self_alias"
    if cid in cycles:
        return "alias_cycle"
    target = by_id.get(target_id)
    if target is None:
        return "missing_target"
    if _non_empty_str(target.get("alias_of")):
        return "alias_to_alias"
    return None


def _correction_alias_is_valid(cid: str, row: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]], cycles: set[str]) -> bool:
    alias = row.get("alias_of")
    if not _non_empty_str(alias):
        return False
    if _correction_alias_reason(cid, row, by_id, cycles) is not None:
        return False
    target = by_id.get(str(alias))
    if target is None:
        return False
    return target.get("status") == row.get("status")


def _validate_corrections(sink: _Sink, corrections: Mapping[str, Any]) -> None:
    rows = corrections.get("corrections") if isinstance(corrections, Mapping) else None
    if not isinstance(rows, list):
        sink.add(
            "manifest.corrections_register.corrections",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "corrections"},
        )
        rows = []
    by_id: dict[str, Mapping[str, Any]] = {}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            sink.add(
                f"manifest.corrections_register.corrections[{index}]",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections[{index}]"},
            )
            continue
        cid = row.get("id")
        if not _non_empty_str(cid):
            sink.add(
                f"manifest.corrections_register.corrections[{index}].id",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections[{index}].id"},
            )
            continue
        cid_s = str(cid)
        if cid_s in seen:
            sink.add(
                f"manifest.corrections_register.{cid_s}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid_s}", "duplicate": True},
            )
            continue
        seen.add(cid_s)
        by_id[cid_s] = row
        status = row.get("status")
        if not _allowed_str(status, CORRECTION_STATUSES):
            sink.add(
                f"manifest.corrections_register.{cid_s}.status",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid_s}.status"},
            )
            continue
        alias = row.get("alias_of")
        if alias is not None and not _non_empty_str(alias):
            sink.add(
                f"manifest.corrections_register.{cid_s}.alias_of",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid_s}.alias_of"},
            )
        blocked_phase = row.get("blocked_phase")
        if blocked_phase is not None and (not _is_int(blocked_phase) or blocked_phase < 0 or blocked_phase > 7):
            sink.add(
                f"manifest.corrections_register.{cid_s}.blocked_phase",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid_s}.blocked_phase"},
            )
        blocked_gate = row.get("blocked_gate")
        if blocked_gate is not None and not _non_empty_str(blocked_gate):
            sink.add(
                f"manifest.corrections_register.{cid_s}.blocked_gate",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid_s}.blocked_gate"},
            )
        if not _is_bool(row.get("implementation_allowed")) or not _is_bool(row.get("release_allowed")):
            sink.add(
                f"manifest.corrections_register.{cid_s}.implementation_allowed",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid_s}.implementation_allowed"},
            )
            continue
        if status == "ABSORBED":
            if blocked_phase is not None or blocked_gate is not None or row.get("implementation_allowed") is not True or row.get("release_allowed") is not True:
                sink.add(
                    f"manifest.corrections_register.{cid_s}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"field": f"corrections.{cid_s}"},
                )
        elif not _non_empty_str(blocked_gate) or row.get("implementation_allowed") is not False or row.get("release_allowed") is not False:
            sink.add(
                f"manifest.corrections_register.{cid_s}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {"field": f"corrections.{cid_s}"},
            )
    edges = _correction_alias_edges(by_id)
    cycles = _correction_alias_cycle_nodes(edges)
    for cid, row in by_id.items():
        reason = _correction_alias_reason(cid, row, by_id, cycles)
        if reason is not None:
            sink.add(
                f"manifest.corrections_register.{cid}.alias_of",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"corrections.{cid}.alias_of", "reason": reason},
            )
            continue
        alias = row.get("alias_of")
        if not _non_empty_str(alias):
            continue
        target = by_id.get(str(alias))
        if target is not None and target.get("status") != row.get("status"):
            sink.add(
                f"manifest.corrections_register.{cid}.status",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {"field": f"corrections.{cid}.status"},
            )
    open_rows: dict[str, Mapping[str, Any]] = {}
    for cid, row in by_id.items():
        if _correction_alias_is_valid(cid, row, by_id, cycles):
            continue
        if _allowed_str(row.get("status"), OPEN_CORRECTION_STATUSES):
            open_rows[cid] = row
    for cid in UNIQUE_UNRESOLVED_IDS + UNIQUE_PARTIAL_IDS:
        row = open_rows.get(cid)
        if row is None:
            continue
        sink.add(cid, BLOCKER_CLASS_OPEN_CORRECTIONS, "OPEN_CORRECTION", {"status": row.get("status")})
    expected = set(UNIQUE_UNRESOLVED_IDS + UNIQUE_PARTIAL_IDS)
    for cid in sorted(open_rows):
        if cid in expected:
            continue
        sink.add(cid, BLOCKER_CLASS_OPEN_CORRECTIONS, "OPEN_CORRECTION", {"status": open_rows[cid].get("status")})
    counts = corrections.get("counts") if isinstance(corrections, Mapping) else None
    unique_unresolved = [cid for cid, row in open_rows.items() if row.get("status") == "UNRESOLVED"]
    unique_partial = [cid for cid, row in open_rows.items() if row.get("status") == "PARTIAL"]
    unique_unresolved_ordered = [cid for cid in UNIQUE_UNRESOLVED_IDS if cid in open_rows] + sorted(
        cid for cid in unique_unresolved if cid not in UNIQUE_UNRESOLVED_IDS
    )
    unique_partial_ordered = [cid for cid in UNIQUE_PARTIAL_IDS if cid in open_rows] + sorted(
        cid for cid in unique_partial if cid not in UNIQUE_PARTIAL_IDS
    )
    if not isinstance(counts, Mapping):
        sink.add(
            "manifest.corrections_register.counts",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_MISSING" if isinstance(corrections, Mapping) and "counts" not in corrections else "MANIFEST_FIELD_INVALID",
            {"field": "corrections.counts"},
        )
    else:
        for key in CORRECTION_COUNT_KEYS:
            if key not in counts:
                sink.add(
                    f"manifest.corrections_register.counts.{key}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_MISSING",
                    {"field": f"corrections.counts.{key}"},
                )
        unresolved_n = counts.get("unique_unresolved")
        if "unique_unresolved" in counts and not _is_nonneg_int(unresolved_n):
            sink.add(
                "manifest.corrections_register.counts.unique_unresolved",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_unresolved"},
            )
        elif "unique_unresolved" in counts and unresolved_n != len(unique_unresolved_ordered):
            sink.add(
                "manifest.corrections_register.counts.unique_unresolved",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_unresolved"},
            )
        unresolved_ids = counts.get("unique_unresolved_ids")
        if "unique_unresolved_ids" in counts and not _is_id_list(unresolved_ids):
            sink.add(
                "manifest.corrections_register.counts.unique_unresolved_ids",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_unresolved_ids"},
            )
        elif "unique_unresolved_ids" in counts and unresolved_ids != unique_unresolved_ordered:
            sink.add(
                "manifest.corrections_register.counts.unique_unresolved_ids",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_unresolved_ids"},
            )
        partial_n = counts.get("unique_partial")
        if "unique_partial" in counts and not _is_nonneg_int(partial_n):
            sink.add(
                "manifest.corrections_register.counts.unique_partial",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_partial"},
            )
        elif "unique_partial" in counts and partial_n != len(unique_partial_ordered):
            sink.add(
                "manifest.corrections_register.counts.unique_partial",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_partial"},
            )
        partial_ids = counts.get("unique_partial_ids")
        if "unique_partial_ids" in counts and not _is_id_list(partial_ids):
            sink.add(
                "manifest.corrections_register.counts.unique_partial_ids",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_partial_ids"},
            )
        elif "unique_partial_ids" in counts and partial_ids != unique_partial_ordered:
            sink.add(
                "manifest.corrections_register.counts.unique_partial_ids",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "corrections.counts.unique_partial_ids"},
            )


def _hash_path_container(manifest: Mapping[str, Any], path: str) -> tuple[Mapping[str, Any] | None, str, str]:
    if "." not in path:
        return manifest, path, path
    top, leaf = path.split(".", 1)
    nested = manifest.get(top)
    if not isinstance(nested, Mapping):
        return None, leaf, top
    return nested, leaf, top


def _required_null_hash_is_honest(manifest: Mapping[str, Any], path: str) -> tuple[bool, dict[str, Any]]:
    container, key, top = _hash_path_container(manifest, path)
    completeness = manifest.get("completeness")
    token = completeness.get(top) if isinstance(completeness, Mapping) else None
    if container is None:
        return False, {"path": path, "status": None, "completeness": token}
    status = _sibling_status(container, key)
    notes = _sibling_notes(container, key)
    details = {"path": path, "status": status, "completeness": token}
    if not _non_empty_str(status) or not _non_empty_str(notes):
        return False, details
    if _allowed_str(status, RECORDED_COMPLETENESS) or _allowed_str(token, RECORDED_COMPLETENESS):
        return False, details
    return True, details


def _iter_required_hash_leaves(
    manifest: Mapping[str, Any],
) -> Iterable[tuple[str, object, Mapping[str, Any], str, str]]:
    for key in REQUIRED_HASH_FIELDS:
        if key not in manifest:
            continue
        value = manifest.get(key)
        if isinstance(value, Mapping):
            for nested_key, nested_val in value.items():
                if _is_meta_key(nested_key) or not HASH_KEY_RE.search(nested_key):
                    continue
                yield f"{key}.{nested_key}", nested_val, value, nested_key, key
        else:
            yield key, value, manifest, key, key
    for path in NOT_APPLICABLE_HASH_PATHS:
        if "." in path or path in REQUIRED_HASH_FIELDS or path not in manifest:
            continue
        yield path, manifest.get(path), manifest, path, path


def _validate_not_applicable_hash_contract(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    completeness = manifest.get("completeness")
    completeness_map = completeness if isinstance(completeness, Mapping) else {}
    seen: set[str] = set()
    for path, value, container, key, top in _iter_required_hash_leaves(manifest):
        if path in seen:
            continue
        seen.add(path)
        status = _sibling_status(container, key)
        notes = _sibling_notes(container, key)
        token = completeness_map.get(top)
        status_na = status == NOT_APPLICABLE_STATUS
        completeness_na = path == top and token == NOT_APPLICABLE_STATUS
        details = {"path": path, "status": status, "completeness": token}
        allowlisted = path in NOT_APPLICABLE_HASH_PATHS
        if not allowlisted:
            if status_na or completeness_na:
                sink.add(f"manifest.{path}", BLOCKER_CLASS_MANIFEST, "MANIFEST_STATUS_INVALID", details)
            continue
        if not (status_na or completeness_na):
            continue
        if value is not None or (status_na and not _non_empty_str(notes)):
            sink.add(f"manifest.{path}", BLOCKER_CLASS_MANIFEST, "MANIFEST_STATUS_INVALID", details)


def _validate_hashes(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    _validate_not_applicable_hash_contract(sink, manifest)
    for path in required_null_hash_paths(manifest):
        sink.add(path, BLOCKER_CLASS_REQUIRED_NULL_HASHES, "REQUIRED_HASH_UNAVAILABLE", {"path": path})
        honest, details = _required_null_hash_is_honest(manifest, path)
        if not honest:
            sink.add(
                f"manifest.{path}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                details,
            )


def _config_unresolved(manifest: Mapping[str, Any], field_id: str) -> tuple[bool, dict[str, Any]]:
    if field_id == "flock_abi_catalog_version":
        value = manifest.get("flock_abi_catalog_version")
        status_present, status = _sibling_status_entry(manifest, "flock_abi_catalog_version")
        if not status_present:
            status = _completeness_of(manifest, "flock_abi_catalog_version")
        return value is None, {"field": field_id, "status": status}
    if field_id == "canonical_mineru_contract_version":
        value = manifest.get("canonical_mineru_contract_version")
        status_present, status = _sibling_status_entry(manifest, "canonical_mineru_contract_version")
        if not status_present:
            status = _completeness_of(manifest, "canonical_mineru_contract_version")
        return value is None, {"field": field_id, "status": status}
    if field_id == "embedding_batch_contract":
        top = manifest.get("embedding_batch_contract")
        embedding = manifest.get("embedding_dimension_dtype_normalization_batch")
        nested = embedding.get("batch_contract") if isinstance(embedding, Mapping) else None
        status_present, status = _sibling_status_entry(manifest, "embedding_batch_contract")
        if not status_present and isinstance(embedding, Mapping):
            status_present, status = _mapping_entry(embedding, "batch_contract_status")
            if not status_present:
                status = None
        return top is None or nested is None, {"field": field_id, "status": status}
    if field_id == "tachiom_static_cmake_target":
        targets = manifest.get("static_build_targets")
        if not isinstance(targets, Mapping) or "tachiom_static_cmake" not in targets:
            return True, {"field": field_id, "status": "missing"}
        value = targets.get("tachiom_static_cmake")
        status_present, status = _mapping_entry(targets, "tachiom_static_cmake_status")
        if not status_present:
            status = _sibling_status(targets, "tachiom_static_cmake")
        return value is None, {"field": field_id, "status": status}
    if field_id == "v7_python_wheel":
        flags = manifest.get("build_flags")
        wheel = flags.get("v7_python_wheel") if isinstance(flags, Mapping) else None
        if not isinstance(wheel, Mapping):
            return True, {"field": field_id, "status": "missing"}
        status = wheel.get("status")
        hash_value = manifest.get("build_artifact_wheel_sha256")
        unresolved = status == "blocked" or hash_value is None or _is_none_or(wheel.get("artifact_path"), "")
        return unresolved, {"field": field_id, "status": status}
    return False, {"field": field_id}


def _validate_configuration(sink: _Sink, manifest: Mapping[str, Any]) -> None:
    for field_id in CONFIG_GAP_IDS:
        unresolved, details = _config_unresolved(manifest, field_id)
        if unresolved:
            sink.add(field_id, BLOCKER_CLASS_CONFIGURATION, "CONFIG_UNRESOLVED", details)


def _validate_dependencies(sink: _Sink, manifest: Mapping[str, Any], provenance: Mapping[str, Any] | None) -> None:
    for label in dirty_uninitialized_labels(manifest, provenance):
        sink.add(
            label,
            BLOCKER_CLASS_DIRTY_UNINITIALIZED,
            "DEPENDENCY_DIRTY_OR_UNINITIALIZED",
            {"label": label},
        )


def _contract_blocker_valid(row: Mapping[str, Any], blocker: object, seen_ids: set[str]) -> bool:
    if not isinstance(blocker, Mapping):
        return False
    bid = blocker.get("id")
    if not _non_empty_str(bid) or bid in seen_ids:
        return False
    if not _allowed_str(blocker.get("level"), ALLOWED_EVIDENCE_LEVELS):
        return False
    blocks = blocker.get("blocks_backend")
    if blocks is not None and not _non_empty_str(blocks):
        return False
    if not _non_empty_str(blocker.get("detail")):
        return False
    return True


def _expected_register_backend_blocked(
    spec: Mapping[str, Any],
    cid_s: str,
    baselines: Mapping[str, Any] | None,
) -> bool:
    if cid_s not in IDENTICAL_CONCERN_CONTRACT_IDS:
        return bool(spec["backend_blocked"])
    relation = next((row for row in BASELINE_RELATIONS if row.get("contract_id") == cid_s), None)
    items = baselines.get("items") if isinstance(baselines, Mapping) else None
    item = items.get(str(relation["baseline_id"])) if isinstance(items, Mapping) and relation else None
    if isinstance(item, Mapping) and relation is not None:
        return not _baseline_available(item, str(relation["required_evidence_level"]), relation)
    return bool(spec["backend_blocked"])


def _validate_register(
    sink: _Sink,
    register: Mapping[str, Any] | None,
    manifest: Mapping[str, Any],
    baselines: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(register, Mapping):
        sink.add(
            "manifest.evidence_register",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "evidence_register"},
        )
        return
    if register.get("schema_version") != EVIDENCE_REGISTER_SCHEMA:
        sink.add(
            "manifest.evidence_register.schema_version",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "evidence_register.schema_version"},
        )
    levels = register.get("evidence_levels")
    if not isinstance(levels, Mapping) or set(levels) != ALLOWED_EVIDENCE_LEVELS or any(not _non_empty_str(levels.get(key)) for key in ALLOWED_EVIDENCE_LEVELS):
        sink.add(
            "manifest.evidence_register.evidence_levels",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "evidence_register.evidence_levels"},
        )
    contracts = register.get("contracts")
    if not isinstance(contracts, list):
        sink.add(
            "manifest.evidence_register.contracts",
            BLOCKER_CLASS_MANIFEST,
            "MANIFEST_FIELD_INVALID",
            {"field": "evidence_register.contracts"},
        )
        return
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(contracts):
        if not isinstance(row, Mapping):
            sink.add(
                f"manifest.evidence_register.contracts[{index}]",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.contracts[{index}]"},
            )
            continue
        cid = row.get("id")
        if not _non_empty_str(cid):
            sink.add(
                f"manifest.evidence_register.contracts[{index}].id",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.contracts[{index}].id"},
            )
            continue
        cid_s = str(cid)
        if cid_s in by_id:
            sink.add(
                f"manifest.evidence_register.{cid_s}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}", "duplicate": True},
            )
            continue
        by_id[cid_s] = row
        for key in REGISTER_ROW_REQUIRED_KEYS:
            if key not in row:
                sink.add(
                    f"manifest.evidence_register.{cid_s}.{key}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_MISSING",
                    {"field": f"evidence_register.{cid_s}.{key}"},
                )
        for key in ("path", "related_backend", "notes"):
            if not _non_empty_str(row.get(key)):
                sink.add(
                    f"manifest.evidence_register.{cid_s}.{key}",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": f"evidence_register.{cid_s}.{key}"},
                )
        spec = REQUIRED_CONTRACT_SPEC_BY_ID.get(cid_s)
        if spec is not None:
            if _non_empty_str(row.get("path")) and row.get("path") != spec.get("path"):
                sink.add(
                    f"manifest.evidence_register.{cid_s}.path",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": f"evidence_register.{cid_s}.path"},
                )
            if _non_empty_str(row.get("related_backend")) and row.get("related_backend") != spec.get("related_backend"):
                sink.add(
                    f"manifest.evidence_register.{cid_s}.related_backend",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": f"evidence_register.{cid_s}.related_backend"},
                )
        level = row.get("level")
        if not _allowed_str(level, ALLOWED_EVIDENCE_LEVELS) or (spec is not None and level != spec["level"]):
            sink.add(
                f"manifest.evidence_register.{cid_s}.level",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}.level"},
            )
        blocked = row.get("backend_blocked")
        if not _is_bool(blocked):
            sink.add(
                f"manifest.evidence_register.{cid_s}.backend_blocked",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}.backend_blocked"},
            )
        elif spec is not None and blocked is not _expected_register_backend_blocked(spec, cid_s, baselines):
            expected_blocked = _expected_register_backend_blocked(spec, cid_s, baselines)
            sink.add(
                f"manifest.evidence_register.{cid_s}.backend_blocked",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {
                    "field": f"evidence_register.{cid_s}.backend_blocked",
                    "expected": expected_blocked,
                    "actual": blocked,
                },
            )
        reason = row.get("backend_blocked_reason")
        if blocked is True:
            if not _non_empty_str(reason):
                sink.add(
                    f"manifest.evidence_register.{cid_s}.backend_blocked_reason",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": f"evidence_register.{cid_s}.backend_blocked_reason"},
                )
        elif reason is not None:
            sink.add(
                f"manifest.evidence_register.{cid_s}.backend_blocked_reason",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}.backend_blocked_reason"},
            )
        paths_read = row.get("paths_read")
        if not isinstance(paths_read, list) or not paths_read or any(not _non_empty_str(path) for path in paths_read):
            sink.add(
                f"manifest.evidence_register.{cid_s}.paths_read",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}.paths_read"},
            )
        blockers = row.get("blockers")
        if not isinstance(blockers, list):
            sink.add(
                f"manifest.evidence_register.{cid_s}.blockers",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}.blockers"},
            )
            blockers = []
        seen_blocker_ids: set[str] = set()
        matching = False
        for blocker in blockers:
            if not _contract_blocker_valid(row, blocker, seen_blocker_ids):
                sink.add(
                    f"manifest.evidence_register.{cid_s}.blockers",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": f"evidence_register.{cid_s}.blockers"},
                )
                break
            assert isinstance(blocker, Mapping)
            seen_blocker_ids.add(str(blocker.get("id")))
            if blocker.get("blocks_backend") == row.get("related_backend"):
                matching = True
        if blocked is True and not matching:
            sink.add(
                f"manifest.evidence_register.{cid_s}.blockers",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": f"evidence_register.{cid_s}.blockers"},
            )
        if cid_s == "infinisynapse_schema":
            if (
                row.get("workflow_semantics_frozen") is not True
                or row.get("workflow_semantics_level") != "E1"
                or row.get("exact_tool_dto_frozen") is not False
                or row.get("exact_tool_dto_level") != "E0"
                or row.get("machine_checkable") != "v7/evidence/contracts/infinisynapse_schema.json"
            ):
                sink.add(
                    "manifest.evidence_register.infinisynapse_schema",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.infinisynapse_schema"},
                )
        if cid_s == "infinisynapse_exact_dto":
            if (
                row.get("exact_tool_dto_frozen") is not False
                or row.get("exact_tool_dto_level") != "E0"
                or row.get("machine_checkable") != "v7/evidence/contracts/infinisynapse_schema.json"
            ):
                sink.add(
                    "manifest.evidence_register.infinisynapse_exact_dto",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.infinisynapse_exact_dto"},
                )
        if cid_s == "mdenseon":
            frozen = row.get("frozen_without_live_files")
            if not isinstance(frozen, Mapping):
                sink.add(
                    "manifest.evidence_register.mdenseon.frozen_without_live_files",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.mdenseon.frozen_without_live_files"},
                )
            else:
                runtime = manifest.get("mdenseon_package_native_runtime_version")
                embedding = manifest.get("embedding_dimension_dtype_normalization_batch")
                tokenizer = manifest.get("tokenizer_identity_version_hash")
                emb_dim = embedding.get("dimension") if isinstance(embedding, Mapping) else None
                emb_dtype = embedding.get("dtype") if isinstance(embedding, Mapping) else None
                mismatches = [
                    not isinstance(runtime, Mapping) or frozen.get("model_id") != runtime.get("model_id"),
                    not isinstance(runtime, Mapping) or frozen.get("revision") != runtime.get("revision"),
                    frozen.get("revision") != (tokenizer.get("version") if isinstance(tokenizer, Mapping) else None),
                    frozen.get("revision") != manifest.get("tokenizer_version") if "tokenizer_version" in manifest else False,
                    frozen.get("expected_dimension") != emb_dim,
                    frozen.get("expected_dimension") != manifest.get("embedding_dimension"),
                    frozen.get("dtype") != emb_dtype,
                    frozen.get("dtype") != manifest.get("embedding_dtype"),
                    frozen.get("normalization") != (embedding.get("normalization") if isinstance(embedding, Mapping) else None),
                    frozen.get("normalization") != manifest.get("embedding_normalization"),
                    frozen.get("zero_norm_policy") != (embedding.get("zero_norm_policy") if isinstance(embedding, Mapping) else None),
                    frozen.get("zero_norm_policy") != manifest.get("embedding_zero_norm_policy"),
                    frozen.get("weights_lfs_sha256_from_lock") != manifest.get("mdenseon_model_weights_sha256"),
                    frozen.get("tokenizer_json_lfs_sha256_from_lock")
                    != (tokenizer.get("lfs_sha256") if isinstance(tokenizer, Mapping) else None),
                    frozen.get("tokenizer_json_lfs_sha256_from_lock") != manifest.get("tokenizer_hash"),
                ]
                if any(mismatches):
                    sink.add(
                        "manifest.evidence_register.mdenseon.frozen_without_live_files",
                        BLOCKER_CLASS_MANIFEST,
                        "MANIFEST_FIELD_INVALID",
                        {"field": "evidence_register.mdenseon.frozen_without_live_files"},
                    )
        if cid_s == "tachiom":
            git = row.get("git") if isinstance(row.get("git"), Mapping) else {}
            tachiom_git = git.get("tachiom") if isinstance(git.get("tachiom"), Mapping) else {}
            dt_git = git.get("duckdb-tachiom") if isinstance(git.get("duckdb-tachiom"), Mapping) else {}
            target = git.get("duckdb-pgagent_target") if isinstance(git.get("duckdb-pgagent_target"), Mapping) else {}
            if tachiom_git.get("build_identity_commit") != manifest.get("tachiom_commit") or tachiom_git.get("build_identity_tag") != manifest.get("tachiom_tag"):
                sink.add(
                    "manifest.evidence_register.tachiom.build_identity",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.tachiom.build_identity"},
                )
            if tachiom_git.get("checkout_commit") != manifest.get("tachiom_checkout_commit"):
                sink.add(
                    "manifest.evidence_register.tachiom.checkout",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.tachiom.checkout"},
                )
            if dt_git.get("commit") != manifest.get("duckdb_tachiom_commit"):
                sink.add(
                    "manifest.evidence_register.tachiom.duckdb_tachiom",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.tachiom.duckdb_tachiom"},
                )
            if target.get("commit") != manifest.get("duckdb_pgagent_commit") or target.get("tag") != manifest.get("duckdb_pgagent_tag"):
                sink.add(
                    "manifest.evidence_register.tachiom.target_duckdb",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.tachiom.target_duckdb"},
                )
        if cid_s == "nearest_basic":
            if (
                row.get("live_e2_requires_binary_and_log") is not True
                or row.get("unverified_gate_level") != "blocked"
                or row.get("unverified_blocker_id") != NEAREST_TARGET_E2_UNVERIFIED
            ):
                sink.add(
                    "manifest.evidence_register.nearest_basic",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.nearest_basic"},
                )
            binary = row.get("binary") if isinstance(row.get("binary"), Mapping) else {}
            build = binary.get("build_identity") if isinstance(binary.get("build_identity"), Mapping) else {}
            if (
                binary.get("sha256") != NEAREST_SHA256
                or binary.get("size_bytes") != NEAREST_SIZE_BYTES
                or build.get("commit") != DUCKDB_PGAGENT_COMMIT
                or build.get("tag") != NEAREST_BUILD_TAG
            ):
                sink.add(
                    "manifest.evidence_register.nearest_basic.binary",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_FIELD_INVALID",
                    {"field": "evidence_register.nearest_basic.binary"},
                )
    for contract_id in REQUIRED_CONTRACT_IDS:
        if contract_id not in by_id:
            sink.add(
                f"manifest.evidence_register.{contract_id}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_MISSING",
                {"field": f"evidence_register.{contract_id}"},
            )


def _register_rows_by_id(register: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    if not isinstance(register, Mapping):
        return by_id
    contracts = register.get("contracts")
    if not isinstance(contracts, list):
        return by_id
    for row in contracts:
        if not isinstance(row, Mapping):
            continue
        cid = row.get("id")
        if _non_empty_str(cid) and str(cid) not in by_id:
            by_id[str(cid)] = row
    return by_id


def _validate_register_baseline_coherence(
    sink: _Sink,
    register: Mapping[str, Any] | None,
    baselines: Mapping[str, Any] | None,
    manifest: Mapping[str, Any] | None,
) -> None:
    if not isinstance(baselines, Mapping):
        return
    items = baselines.get("items")
    if not isinstance(items, Mapping):
        return
    gates = manifest.get("backend_gates") if isinstance(manifest, Mapping) and isinstance(manifest.get("backend_gates"), Mapping) else {}
    by_id = _register_rows_by_id(register)
    for relation in BASELINE_RELATIONS:
        item_id = str(relation["baseline_id"])
        item = items.get(item_id)
        if not isinstance(item, Mapping):
            continue
        _validate_evidence_components(sink, item_id, item, relation, by_id)
        required = str(relation.get("required_evidence_level") or "E2")
        available = _baseline_available(item, required, relation)
        expected_blocked = not available
        gate_name = str(relation["backend_gate"])
        gate = gates.get(gate_name) if isinstance(gates, Mapping) else None
        gate_blocked = isinstance(gate, Mapping) and gate.get("blocked") is True
        if gate_blocked is not expected_blocked or not _gate_matches_baseline_availability(gate, available):
            sink.add(
                f"manifest.backend_gates.{gate_name}",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {
                    "item": item_id,
                    "gate": gate_name,
                    "available": available,
                    "gate_blocked": gate_blocked,
                    "expected_blocked": expected_blocked,
                },
            )
        contract_id = relation.get("contract_id")
        row = by_id.get(str(contract_id)) if contract_id else None
        concern = relation.get("concern")
        if not isinstance(row, Mapping):
            continue
        register_blocked = row.get("backend_blocked") is True
        cid = row.get("id")
        if concern == "identical":
            if register_blocked != gate_blocked:
                sink.add(
                    f"manifest.evidence_register.{cid}.backend_blocked",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {
                        "item": item_id,
                        "field": "backend_blocked",
                        "gate": gate_name,
                        "register_blocked": register_blocked,
                        "gate_blocked": gate_blocked,
                    },
                )
            if register_blocked and _allowed_str(item.get("evidence_level"), {"E2", "E3"}):
                sink.add(
                    f"manifest.baselines.{item_id}.evidence_level",
                    BLOCKER_CLASS_MANIFEST,
                    "MANIFEST_STATUS_INVALID",
                    {"item": item_id, "field": "evidence_level"},
                )
        elif concern == "separate" and register_blocked and not gate_blocked:
            sink.add(
                f"manifest.evidence_register.{cid}.backend_blocked",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_STATUS_INVALID",
                {
                    "item": item_id,
                    "field": "backend_blocked",
                    "gate": gate_name,
                    "register_blocked": register_blocked,
                    "gate_blocked": gate_blocked,
                },
            )


def _validate_nearest(sink: _Sink, nearest_verification: Mapping[str, Any] | None) -> None:
    verification = nearest_verification if isinstance(nearest_verification, Mapping) else None
    if isinstance(verification, Mapping) and verification.get("verified") is True:
        codes = verification.get("failure_codes")
        level = verification.get("live_gate_level")
        if codes in (None, []) and level == "E2":
            return
    failures: list[str] = []
    if isinstance(verification, Mapping):
        codes = verification.get("failure_codes")
        if isinstance(codes, list):
            failures = [code for code in codes if isinstance(code, str)]
        if verification.get("verified") is True and failures:
            failures = _order_nearest_failures(set(failures) | {"ATTESTATION_SCHEMA_INVALID"})
    sink.add(
        NEAREST_TARGET_E2_UNVERIFIED,
        BLOCKER_CLASS_LIVE_EVIDENCE,
        "NEAREST_E2_UNVERIFIED",
        {"failures": failures},
    )


def _validate_phase0_envelopes(
    sink: _Sink,
    manifest: Mapping[str, Any] | None,
    baselines: Mapping[str, Any] | None,
) -> None:
    if isinstance(manifest, Mapping):
        phase = manifest.get("phase")
        if not _is_int(phase) or phase != 0:
            sink.add(
                "manifest.phase",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "phase"},
            )
        if manifest.get("manifest_kind") != MANIFEST_KIND:
            sink.add(
                "manifest.manifest_kind",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "manifest_kind"},
            )
    if isinstance(baselines, Mapping):
        if baselines.get("schema_version") != SCHEMA_VERSION:
            sink.add(
                "manifest.phase0_baselines.schema_version",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "phase0_baselines.schema_version"},
            )
        if baselines.get("evaluator") != EVALUATOR_ID:
            sink.add(
                "manifest.phase0_baselines.evaluator",
                BLOCKER_CLASS_MANIFEST,
                "MANIFEST_FIELD_INVALID",
                {"field": "phase0_baselines.evaluator"},
            )


def _evaluate_phase0_snapshot(
    manifest: Mapping[str, Any] | None,
    baselines: Mapping[str, Any] | None,
    corrections: Mapping[str, Any] | None,
    provenance: Mapping[str, Any] | None,
    register: Mapping[str, Any] | None,
    *,
    nearest_verification: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sink = _Sink()
    if not isinstance(manifest, Mapping):
        sink.add("manifest", BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "manifest"})
        _validate_nearest(sink, nearest_verification)
        return sink.result()
    if not isinstance(baselines, Mapping):
        sink.add("manifest.phase0_baselines", BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "baselines"})
    if not isinstance(corrections, Mapping):
        sink.add("manifest.corrections_register", BLOCKER_CLASS_MANIFEST, "MANIFEST_FIELD_INVALID", {"field": "corrections"})
    _validate_phase0_envelopes(sink, manifest, baselines if isinstance(baselines, Mapping) else None)
    _validate_manifest_contract(
        sink,
        manifest,
        baselines=baselines if isinstance(baselines, Mapping) else None,
        corrections=corrections if isinstance(corrections, Mapping) else None,
        provenance=provenance if isinstance(provenance, Mapping) else None,
        register=register if isinstance(register, Mapping) else None,
    )
    _validate_identity_pins(sink, manifest)
    _validate_provenance(sink, manifest, provenance if isinstance(provenance, Mapping) else None)
    _validate_register(
        sink,
        register,
        manifest,
        baselines if isinstance(baselines, Mapping) else None,
    )
    _validate_backend_gates(sink, manifest, baselines if isinstance(baselines, Mapping) else None)
    _validate_baselines(sink, baselines if isinstance(baselines, Mapping) else {}, manifest)
    _validate_register_baseline_coherence(
        sink,
        register if isinstance(register, Mapping) else None,
        baselines if isinstance(baselines, Mapping) else None,
        manifest,
    )
    _validate_corrections(sink, corrections if isinstance(corrections, Mapping) else {})
    _validate_hashes(sink, manifest)
    _validate_configuration(sink, manifest)
    _validate_dependencies(sink, manifest, provenance if isinstance(provenance, Mapping) else None)
    _validate_nearest(sink, nearest_verification)
    return sink.result()


def _read_source_bytes(
    path: Path,
    source_reader: Callable[[Path], bytes] | None,
) -> tuple[bytes | None, str | None]:
    try:
        if source_reader is None:
            data = path.read_bytes()
        else:
            data = source_reader(path)
    except FileNotFoundError:
        return None, "missing"
    except IsADirectoryError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    if not isinstance(data, (bytes, bytearray)):
        return None, "unreadable"
    return bytes(data), None


def _digest_bytes(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {"present": False}
    return {
        "present": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _parse_json_mapping(data: bytes | None) -> dict[str, Any] | None:
    if data is None:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_json_mapping(path: Path) -> dict[str, Any] | None:
    data, _error = _read_source_bytes(path, None)
    return _parse_json_mapping(data)


def _digest_source_file(path: Path) -> dict[str, Any]:
    data, _error = _read_source_bytes(path, None)
    return _digest_bytes(data)


NEAREST_BINARY_SOURCE_ID = "nearest_binary"


def _capture_phase0_sources(
    repo_root: Path,
    *,
    source_reader: Callable[[Path], bytes] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Capture every Phase 0 JSON/log into immutable bytes (one S0/S1/S2 pass).

    ``confirm`` is ignored. Confirmation is a later complete recapture compared
    as a whole, never a per-file immediate-only check.
    """
    del confirm
    try:
        root = Path(repo_root).resolve()
    except (OSError, RuntimeError):
        root = Path(repo_root)
    files: dict[str, dict[str, Any]] = {}
    unreadable: set[str] = set()
    for rel in PHASE0_SOURCE_RELATIVE_PATHS:
        data, error = _read_source_bytes(root / rel, source_reader)
        if error == "unreadable":
            unreadable.add(rel)
        files[rel] = {
            "data": data,
            "error": error,
            "digest": _digest_bytes(data),
        }
    return {
        "repo_root": root,
        "files": files,
        "changed_paths": [],
        "unreadable_paths": [rel for rel in PHASE0_SOURCE_RELATIVE_PATHS if rel in unreadable],
    }


def _nearest_failure_code_set(nearest_verification: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(nearest_verification, Mapping):
        return set()
    codes = nearest_verification.get("failure_codes")
    if not isinstance(codes, list):
        return set()
    return {code for code in codes if isinstance(code, str)}


def _nearest_binary_identity(nearest_verification: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(nearest_verification, Mapping):
        return {
            "present": False,
            "binary_source": None,
            "path": None,
            "sha256": None,
            "size_bytes": None,
            "build_identity": None,
            "error": "missing",
        }
    observed = nearest_verification.get("observed")
    observed_map = observed if isinstance(observed, Mapping) else {}
    binary = observed_map.get("binary")
    source = nearest_verification.get("binary_source")
    io_unreadable = "BINARY_READ_FAILED" in _nearest_failure_code_set(nearest_verification)
    error = "unreadable" if io_unreadable else None
    if not isinstance(binary, Mapping):
        return {
            "present": False,
            "binary_source": source,
            "path": None,
            "sha256": None,
            "size_bytes": None,
            "build_identity": None,
            "error": error,
        }
    build = binary.get("build_identity")
    return {
        "present": True,
        "binary_source": source,
        "path": binary.get("path"),
        "sha256": binary.get("sha256"),
        "size_bytes": binary.get("size_bytes"),
        "build_identity": dict(build) if isinstance(build, Mapping) else build,
        "error": error,
    }


def _source_capture_delta(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> tuple[list[str], set[str]]:
    """Compare two complete source captures. Not a per-file immediate check."""
    changed: list[str] = []
    unreadable: set[str] = set()
    first_files = first.get("files") if isinstance(first.get("files"), Mapping) else {}
    second_files = second.get("files") if isinstance(second.get("files"), Mapping) else {}
    if not isinstance(first_files, Mapping):
        first_files = {}
    if not isinstance(second_files, Mapping):
        second_files = {}
    for rel in PHASE0_SOURCE_RELATIVE_PATHS:
        first_entry = first_files.get(rel)
        second_entry = second_files.get(rel)
        first_map = first_entry if isinstance(first_entry, Mapping) else {}
        second_map = second_entry if isinstance(second_entry, Mapping) else {}
        if first_map.get("data") != second_map.get("data") or first_map.get("error") != second_map.get("error"):
            changed.append(rel)
        if second_map.get("error") == "unreadable":
            unreadable.add(rel)
    return changed, unreadable


def _absorb_path_delta(
    changed: list[str],
    unreadable: set[str],
    delta_changed: Iterable[str],
    delta_unreadable: Iterable[str],
) -> None:
    for rel in delta_changed:
        if rel not in changed:
            changed.append(rel)
    unreadable.update(delta_unreadable)


def _binary_confirm_unreadable(
    first_binary: Mapping[str, Any],
    second_binary: Mapping[str, Any],
    confirm_nearest: Mapping[str, Any] | None,
    *,
    binary_exc: bool,
) -> bool:
    if binary_exc or second_binary.get("error") == "unreadable":
        return True
    codes = _nearest_failure_code_set(confirm_nearest)
    if "BINARY_READ_FAILED" in codes:
        return True
    if "BINARY_PATH_UNRESOLVED" in codes and first_binary.get("present") is True:
        return True
    return False


def _confirm_phase0_snapshot(
    snapshot: Mapping[str, Any],
    *,
    source_reader: Callable[[Path], bytes] | None = None,
    nearest_verification: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """S1 → B1 → S2 confirmation against immutable S0 bytes and B0 identity.

    Linearization point: the last completed S2 capture. S0 bytes and B0 binary
    identity are attested iff S0 == S1 == S2 and B0 == B1. Mutations after this
    function returns are outside the bracket.
    """
    root = snapshot["repo_root"]
    files = snapshot["files"]
    changed: list[str] = []
    unreadable: set[str] = set(snapshot.get("unreadable_paths") or [])

    try:
        snapshot_s1 = _capture_phase0_sources(root, source_reader=source_reader)
    except (OSError, RuntimeError, TypeError, ValueError):
        snapshot_s1 = {
            "repo_root": root,
            "files": {
                rel: {"data": None, "error": "unreadable", "digest": _digest_bytes(None)}
                for rel in PHASE0_SOURCE_RELATIVE_PATHS
            },
            "changed_paths": list(PHASE0_SOURCE_RELATIVE_PATHS),
            "unreadable_paths": list(PHASE0_SOURCE_RELATIVE_PATHS),
        }
    delta_s1, unread_s1 = _source_capture_delta(snapshot, snapshot_s1)
    _absorb_path_delta(changed, unreadable, delta_s1, unread_s1)
    unreadable.update(snapshot_s1.get("unreadable_paths") or [])

    first_binary = _nearest_binary_identity(nearest_verification)
    binary_exc = False
    confirm_nearest: Mapping[str, Any] | None
    try:
        log_text, malformed_log = _log_text_from_snapshot(snapshot)
        confirm_nearest = _collect_nearest_live_evidence(
            root,
            _parse_json_mapping(files["v7/VERSION_MANIFEST.json"]["data"]),
            _parse_json_mapping(files["v7/evidence/nearest_e2.json"]["data"]),
            environ=environ,
            log_text=log_text,
            log_loaded=True,
            malformed_log=malformed_log,
        )
        second_binary = _nearest_binary_identity(confirm_nearest)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError):
        confirm_nearest = None
        second_binary = {
            "present": False,
            "binary_source": first_binary.get("binary_source"),
            "path": first_binary.get("path"),
            "sha256": None,
            "size_bytes": None,
            "build_identity": None,
            "error": "unreadable",
        }
        binary_exc = True

    try:
        snapshot_s2 = _capture_phase0_sources(root, source_reader=source_reader)
    except (OSError, RuntimeError, TypeError, ValueError):
        snapshot_s2 = {
            "repo_root": root,
            "files": {
                rel: {"data": None, "error": "unreadable", "digest": _digest_bytes(None)}
                for rel in PHASE0_SOURCE_RELATIVE_PATHS
            },
            "changed_paths": list(PHASE0_SOURCE_RELATIVE_PATHS),
            "unreadable_paths": list(PHASE0_SOURCE_RELATIVE_PATHS),
        }
    delta_s2, unread_s2 = _source_capture_delta(snapshot, snapshot_s2)
    _absorb_path_delta(changed, unreadable, delta_s2, unread_s2)
    delta_s1_s2, unread_s1_s2 = _source_capture_delta(snapshot_s1, snapshot_s2)
    _absorb_path_delta(changed, unreadable, delta_s1_s2, unread_s1_s2)
    unreadable.update(snapshot_s2.get("unreadable_paths") or [])

    if second_binary != first_binary:
        binary_label = first_binary.get("path") or second_binary.get("path") or NEAREST_BINARY_SOURCE_ID
        if str(binary_label) not in changed:
            changed.append(str(binary_label))
    if _binary_confirm_unreadable(
        first_binary,
        second_binary,
        confirm_nearest,
        binary_exc=binary_exc,
    ):
        unreadable.add(NEAREST_BINARY_SOURCE_ID)
        path_label = first_binary.get("path") or second_binary.get("path")
        if _non_empty_str(path_label):
            unreadable.add(str(path_label))
        if NEAREST_BINARY_SOURCE_ID not in changed:
            changed.append(NEAREST_BINARY_SOURCE_ID)
    return changed, _ordered_unreadable(unreadable)


def _ordered_unreadable(unreadable: set[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for rel in list(PHASE0_SOURCE_RELATIVE_PATHS) + [NEAREST_BINARY_SOURCE_ID]:
        if rel in unreadable and rel not in seen:
            ordered.append(rel)
            seen.add(rel)
    for rel in unreadable:
        if rel not in seen:
            ordered.append(rel)
            seen.add(rel)
    return ordered


def _log_text_from_snapshot(snapshot: Mapping[str, Any]) -> tuple[str | None, bool]:
    entry = snapshot["files"][NEAREST_LOG_REL]
    data = entry.get("data")
    malformed = entry.get("error") == "unreadable"
    if data is None:
        return None, malformed
    try:
        return data.decode("utf-8"), malformed
    except UnicodeDecodeError:
        return None, True


def _materialize_phase0_inputs(
    snapshot: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[
    Path,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any],
]:
    files = snapshot["files"]
    root = snapshot["repo_root"]
    manifest = _parse_json_mapping(files["v7/VERSION_MANIFEST.json"]["data"])
    baselines = _parse_json_mapping(files["v7/evidence/phase0_baseline_status.json"]["data"])
    corrections = _parse_json_mapping(files["v7/evidence/corrections_register.json"]["data"])
    provenance = _parse_json_mapping(files["v7/evidence/four_repo_provenance.json"]["data"])
    register = _parse_json_mapping(files["v7/evidence/contracts/EVIDENCE_REGISTER.json"]["data"])
    historical = _parse_json_mapping(files["v7/evidence/nearest_e2.json"]["data"])
    log_text, malformed_log = _log_text_from_snapshot(snapshot)
    nearest_verification = _collect_nearest_live_evidence(
        root,
        manifest,
        historical,
        environ=environ,
        log_text=log_text,
        log_loaded=True,
        malformed_log=malformed_log,
    )
    return root, manifest, baselines, corrections, provenance, register, historical, nearest_verification


def _nearest_source_identity(nearest_verification: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(nearest_verification, Mapping):
        return {"present": False}
    observed = nearest_verification.get("observed")
    observed_map = observed if isinstance(observed, Mapping) else {}
    log = observed_map.get("log")
    binary = observed_map.get("binary")
    failure_codes = nearest_verification.get("failure_codes")
    return {
        "present": True,
        "schema_version": nearest_verification.get("schema_version"),
        "verifier": nearest_verification.get("verifier"),
        "verified": nearest_verification.get("verified"),
        "live_gate_level": nearest_verification.get("live_gate_level"),
        "failure_codes": list(failure_codes) if isinstance(failure_codes, list) else failure_codes,
        "binary_source": nearest_verification.get("binary_source"),
        "records_sha256": nearest_verification.get("records_sha256"),
        "log": None
        if not isinstance(log, Mapping)
        else {
            "path": log.get("path"),
            "command": log.get("command"),
            "exit_code": log.get("exit_code"),
            "assertions": log.get("assertions"),
            "build_commit": log.get("build_commit"),
            "build_tag": log.get("build_tag"),
        },
        "binary": None
        if not isinstance(binary, Mapping)
        else {
            "sha256": binary.get("sha256"),
            "size_bytes": binary.get("size_bytes"),
            "build_identity": binary.get("build_identity"),
        },
    }


def _fingerprint_phase0_files(
    files: Mapping[str, Mapping[str, Any]],
    nearest_verification: Mapping[str, Any] | None,
) -> str:
    payload = {
        "schema": SOURCE_FINGERPRINT_SCHEMA,
        "phase0_schema_version": SCHEMA_VERSION,
        "evaluator": EVALUATOR_ID,
        "files": {rel: dict(files[rel]) for rel in PHASE0_SOURCE_RELATIVE_PATHS},
        "nearest": _nearest_source_identity(nearest_verification),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _fingerprint_from_snapshot(
    snapshot: Mapping[str, Any],
    nearest_verification: Mapping[str, Any] | None,
) -> str:
    files = {rel: dict(snapshot["files"][rel]["digest"]) for rel in PHASE0_SOURCE_RELATIVE_PATHS}
    return _fingerprint_phase0_files(files, nearest_verification)


def attest_phase0_from_repo(
    repo_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    source_reader: Callable[[Path], bytes] | None = None,
) -> dict[str, Any]:
    """Bracketed Phase 0 attestation: S0 → B0 → S1 → B1 → S2.

    Evaluates immutable S0 bytes. Confirms with complete source recaptures S1
    and S2 around a second binary observation B1. A matching stale expected
    fingerprint cannot override S0 != S1, S1 != S2, S0 != S2, B0 != B1, or
    confirm-time SOURCE_UNREADABLE. Detection is not claimed after S2 returns.
    """
    env = None if environ is None else dict(environ)
    snapshot = _capture_phase0_sources(repo_root, source_reader=source_reader)
    _root, manifest, baselines, corrections, provenance, register, _historical, nearest = _materialize_phase0_inputs(
        snapshot, environ=env
    )
    phase0 = _evaluate_phase0_snapshot(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        nearest_verification=nearest,
    )
    fingerprint = _fingerprint_from_snapshot(snapshot, nearest)
    try:
        changed_paths, unreadable_paths = _confirm_phase0_snapshot(
            snapshot,
            source_reader=source_reader,
            nearest_verification=nearest,
            environ=env,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        changed_paths = list(PHASE0_SOURCE_RELATIVE_PATHS)
        unreadable_paths = list(PHASE0_SOURCE_RELATIVE_PATHS)
    failure_present = set()
    if changed_paths:
        failure_present.add("SOURCE_CHANGED")
    if unreadable_paths:
        failure_present.add("SOURCE_UNREADABLE")
    failure_codes = [code for code in ATTESTATION_FAILURE_CODES if code in failure_present]
    return {
        "schema_version": PHASE0_ATTESTATION_SCHEMA,
        "evaluator": EVALUATOR_ID,
        "attested": not failure_codes,
        "phase0": phase0,
        "source_fingerprint": fingerprint,
        "nearest_verification": nearest,
        "failure_codes": failure_codes,
        "changed_paths": list(changed_paths),
        "unreadable_paths": list(unreadable_paths),
    }


def evaluate_phase0_from_repo(
    repo_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _capture_phase0_sources(repo_root, confirm=False)
    _root, manifest, baselines, corrections, provenance, register, _historical, nearest_verification = (
        _materialize_phase0_inputs(snapshot, environ=environ)
    )
    result = _evaluate_phase0_snapshot(
        manifest,
        baselines,
        corrections,
        provenance,
        register,
        nearest_verification=nearest_verification,
    )
    return result, nearest_verification


def phase0_source_fingerprint(
    repo_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    snapshot = _capture_phase0_sources(repo_root, confirm=False)
    _root, _manifest, _baselines, _corrections, _provenance, _register, _historical, nearest = _materialize_phase0_inputs(
        snapshot, environ=environ
    )
    return _fingerprint_from_snapshot(snapshot, nearest)


def evaluate_phase0(
    repo_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    result, _verification = evaluate_phase0_from_repo(repo_root, environ=environ)
    return result


def phase0_result_validation_codes(result: object) -> list[str]:
    codes: list[str] = []
    if not isinstance(result, Mapping):
        return ["PHASE0_RESULT_NOT_OBJECT"]
    if result.get("schema_version") != SCHEMA_VERSION:
        codes.append("PHASE0_SCHEMA_VERSION_INVALID")
    if result.get("evaluator") != EVALUATOR_ID:
        codes.append("PHASE0_EVALUATOR_INVALID")
    if not _is_bool(result.get("phase0_pass")):
        codes.append("PHASE0_PASS_TYPE_INVALID")
    ids = result.get("blocker_ids")
    classes = result.get("blocker_classes")
    reasons = result.get("reasons")
    ids_ok = isinstance(ids, list) and all(_non_empty_str(item) for item in ids)
    classes_ok = isinstance(classes, list) and all(_allowed_str(item, PHASE0_BLOCKER_CLASS_ORDER) for item in classes)
    reasons_ok = isinstance(reasons, list)
    if not ids_ok:
        codes.append("PHASE0_BLOCKER_IDS_INVALID")
    if not classes_ok:
        codes.append("PHASE0_BLOCKER_CLASSES_INVALID")
    if not reasons_ok:
        codes.append("PHASE0_REASONS_INVALID")
    if ids_ok and len(ids) != len(set(ids)):
        codes.append("PHASE0_BLOCKER_ID_DUPLICATE")
    if classes_ok:
        expected_classes = [cls for cls in PHASE0_BLOCKER_CLASS_ORDER if cls in set(classes)]
        if list(classes) != expected_classes:
            codes.append("PHASE0_CLASS_ORDER_INVALID")
    if ids_ok and reasons_ok:
        if len(ids) != len(reasons):
            codes.append("PHASE0_REASON_ALIGNMENT_INVALID")
        else:
            reason_classes: list[str] = []
            for index, (blocker_id, reason) in enumerate(zip(ids, reasons)):
                if not isinstance(reason, Mapping):
                    codes.append("PHASE0_REASONS_INVALID")
                    break
                if set(reason) != {"blocker_id", "blocker_class", "code", "details"}:
                    codes.append("PHASE0_REASONS_INVALID")
                    break
                if reason.get("blocker_id") != blocker_id:
                    codes.append("PHASE0_REASON_ALIGNMENT_INVALID")
                    break
                if not _allowed_str(reason.get("blocker_class"), PHASE0_BLOCKER_CLASS_ORDER):
                    codes.append("PHASE0_REASONS_INVALID")
                    break
                if not _allowed_str(reason.get("code"), REASON_CODES):
                    codes.append("PHASE0_REASONS_INVALID")
                    break
                if not isinstance(reason.get("details"), Mapping):
                    codes.append("PHASE0_REASONS_INVALID")
                    break
                reason_classes.append(str(reason.get("blocker_class")))
            else:
                projected = [cls for cls in PHASE0_BLOCKER_CLASS_ORDER if cls in set(reason_classes)]
                if classes_ok and list(classes) != projected:
                    codes.append("PHASE0_REASON_ALIGNMENT_INVALID")
                grouped = [cls for cls in reason_classes]
                if grouped != sorted(grouped, key=lambda item: PHASE0_BLOCKER_CLASS_ORDER.index(item)):
                    codes.append("PHASE0_CLASS_ORDER_INVALID")
    empty = ids_ok and reasons_ok and classes_ok and ids == [] and classes == [] and reasons == []
    if _is_bool(result.get("phase0_pass")) and (result.get("phase0_pass") is True) != empty:
        codes.append("PHASE0_PASS_CONTRADICTS_BLOCKERS")
    ordered: list[str] = []
    seen_codes: set[str] = set()
    for code in PHASE0_RESULT_CODES:
        if code in codes and code not in seen_codes:
            ordered.append(code)
            seen_codes.add(code)
    return ordered


def phase0_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    codes = phase0_result_validation_codes(result)
    if codes:
        raise ValueError("invalid Phase 0 result: " + ",".join(codes))
    return {
        "schema_version": result["schema_version"],
        "evaluator": result["evaluator"],
        "phase0_pass": result["phase0_pass"],
        "blocker_ids": list(result["blocker_ids"]),
        "blocker_classes": list(result["blocker_classes"]),
        "reasons": [dict(row) for row in result["reasons"]],
    }


def _recorded_list(value: object, field: str, errors: list[str]) -> list[Any] | None:
    if isinstance(value, list):
        return value
    errors.append(f"{field} recorded is not an array")
    return None


def phase0_record_consistency_errors(
    recorded_baseline: Mapping[str, Any],
    evaluated_phase0: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(recorded_baseline, Mapping):
        return ["recorded Phase 0 baseline is not an object"]
    evaluated_codes = phase0_result_validation_codes(evaluated_phase0)
    if evaluated_codes:
        errors.append(f"evaluated Phase 0 result is invalid: {evaluated_codes}")
        return errors
    evaluated = phase0_projection(evaluated_phase0)
    recorded_ids = _recorded_list(recorded_baseline.get("blocker_ids"), "blocker_ids", errors)
    recorded_classes = _recorded_list(recorded_baseline.get("blocker_classes"), "blocker_classes", errors)
    recorded_reasons = _recorded_list(recorded_baseline.get("reasons"), "reasons", errors)
    if recorded_baseline.get("schema_version") != evaluated["schema_version"]:
        errors.append(
            "schema_version recorded="
            f"{recorded_baseline.get('schema_version')!r} evaluated={evaluated['schema_version']!r}"
        )
    if recorded_baseline.get("evaluator") != evaluated["evaluator"]:
        errors.append(
            f"evaluator recorded={recorded_baseline.get('evaluator')!r} evaluated={evaluated['evaluator']!r}"
        )
    if recorded_baseline.get("phase0_pass") is not evaluated["phase0_pass"]:
        errors.append(
            "phase0_pass recorded="
            f"{recorded_baseline.get('phase0_pass')!r} evaluated={evaluated['phase0_pass']!r}"
        )
    if recorded_ids is not None and recorded_ids != evaluated["blocker_ids"]:
        errors.append(f"blocker_ids recorded={recorded_ids!r} evaluated={evaluated['blocker_ids']!r}")
    if recorded_classes is not None and recorded_classes != evaluated["blocker_classes"]:
        errors.append(
            f"blocker_classes recorded={recorded_classes!r} evaluated={evaluated['blocker_classes']!r}"
        )
    if recorded_reasons is not None and recorded_reasons != evaluated["reasons"]:
        errors.append("reasons do not exactly equal evaluator output")
    if recorded_reasons is not None and any(isinstance(row, str) for row in recorded_reasons):
        errors.append("recorded reasons must be structured objects, not strings")
    if len(evaluated["blocker_ids"]) != len(evaluated["reasons"]):
        errors.append("evaluator reasons length != blocker_ids length")
    for index, (blocker_id, reason) in enumerate(zip(evaluated["blocker_ids"], evaluated["reasons"])):
        if not isinstance(reason, Mapping):
            errors.append(f"reason[{index}] is not an object")
            continue
        if reason.get("blocker_id") != blocker_id:
            errors.append(f"reason[{index}].blocker_id != blocker_ids[{index}]")
        if not _allowed_str(reason.get("blocker_class"), PHASE0_BLOCKER_CLASS_ORDER):
            errors.append(f"reason[{index}] has unknown blocker_class {reason.get('blocker_class')!r}")
        if not _allowed_str(reason.get("code"), REASON_CODES):
            errors.append(f"reason[{index}] has unknown code {reason.get('code')!r}")
        if reason.get("blocker_class") not in evaluated["blocker_classes"]:
            errors.append(f"reason[{index}] class not listed in blocker_classes")
    seen: set[str] = set()
    for blocker_id in evaluated["blocker_ids"]:
        if blocker_id in seen:
            errors.append(f"duplicate blocker_id {blocker_id}")
        seen.add(blocker_id)
    return errors
