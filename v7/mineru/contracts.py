"""Phase 0 MinerU identity constants.

Parse identity is the mineru[pipeline]==3.4.4 wheel + 84-wheel lock + Darwin
profile_id + 187-file PDF-Extract-Kit snapshot manifest + 1-page PDF golden.
OCI container digest and single-file weights are not applicable.

Do NOT assign PROFILE_ID to VERSION_MANIFEST canonical_mineru_contract_version.
That ingest-contract field stays null/blocked (user Q2, 2026-08-30).

This module must not import v7.gates.phase0_evaluator.
Snapshot pin is profile.json pipeline_model.manifest_sha256 and the copied
p19-s.json model_closure. The wheel lock pins only the wheel sha256 field.
"""
from __future__ import annotations

from typing import Any

# Do NOT assign PROFILE_ID to VERSION_MANIFEST canonical_mineru_contract_version.
PROFILE_ID = "mineru-3.4.4-pipeline-cpython312-darwin-arm64"
HARNESS_REVISION = "duckrag-wi1-harness/2"
EXECUTION_BACKEND = "mineru_pipeline_cpu_offline"
MINERU_VERSION = "3.4.4"
MINERU_WHEEL_NAME = "mineru-3.4.4-py3-none-any.whl"
MINERU_WHEEL_SHA256 = "d4d678539782a7683d998e2914a52d96b5720676ce65658b29666b1f4d9dfd13"
MINERU_WHEEL_SIZE_BYTES = 1_540_534
MINERU_TAG_COMMIT_SHA = "0dfc9460cd9ab693b9af60ae3fbffd7bc111b062"
MODEL_REPOSITORY = "opendatalab/PDF-Extract-Kit-1.0"
MODEL_REVISION = "ed6b654c018d742e65a17671e379c5e6ecc87ec9"
MODEL_MANIFEST_SHA256 = "8c4a6a53815e2a8f410d71350128d0db1276579ac9f50cd1dee56b165e4a4df6"
MODEL_FILE_COUNT = 187
MODEL_TOTAL_BYTES = 15_127_785_361
PDF_REL = "v7/tests/fixtures/range_trio/pdf/p19-mineru-offline.pdf"
PDF_SHA256 = "163c9ac8f7f857904793b01fa9f031cebbe83f186b9cfc3510b9a371e464922c"
PDF_SIZE_BYTES = 672
P19S_REL = "v7/evidence/duckrag/p19-s.json"
P19S_EVIDENCE_SHA256 = "ae77a11045b4ce9a26705b0665ee54d11f67f26e37b72755253f46c92b0dff55"
P19S_RUN_ID = "p19-s-20260807T041212.416512Z"
IDENTITY_LOCK_REL = "v7/evidence/locks/mineru/mineru-3.4.4.lock.json"
IDENTITY_PROFILE_REL = "v7/evidence/locks/mineru/profile.json"
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
PAGE_SIZE = [612, 792]

MINERU_PARSER_EXPECTED: dict[str, Any] = {
    "backend": "pipeline",
    "method": "txt",
    "formula": False,
    "table": False,
    "cli": "mineru -p <pdf> -o <out> -b pipeline -m txt -f false -t false",
    "canonical_surface": "content_list.json",
    "page_idx": "0-based",
    "catalog_page": "page_idx + 1",
    "bbox": "page-pixel xyxy",
    "env": {
        "MINERU_MODEL_SOURCE": "local",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "MODELSCOPE_OFFLINE": "1",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
    },
    "required_artifacts": [
        "*_content_list.json",
        "*_content_list_v2.json",
        "*_middle.json",
    ],
}
