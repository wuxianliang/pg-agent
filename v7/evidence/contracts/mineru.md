# MinerU ingestion contract (Phase 0 WI-3)

Evidence level: **E1** (source, harness, lock, and local output JSON inspected). This session did **not** re-run MinerU. A prior P19-S run exists as an evidence record, not as a re-executed E2 gate.

Related backend: MinerU **JSON → tree parser** is not blocked. **Live MinerU execution** (wheelhouse/venv + 187-file PDF-Extract-Kit snapshot **bytes on this machine**) is blocked. Container image digest is **N/A** (P19-S is `mineru[pipeline]` wheel + snapshot, not an OCI runtime; do not invent a digest). Darwin `profile_id` `mineru-3.4.4-pipeline-cpython312-darwin-arm64` is a runtime pin in `mineru_profile_id`, **not** `canonical_mineru_contract_version`.

## What was read

| Path | Role | Git / identity |
|---|---|---|
| `/Users/wxl/Projects/MinerU-Popo` | Post-processor that maps MinerU labels/bbox into Popo trees | `75c36a8c0f38adee03c78850366645a58cd5d4af` `master` (matches known SHA) |
| `/Users/wxl/MinerU` | Local parse **output corpus**, not a MinerU source tree. No `.git`. | E0 as upstream source; E1 as JSON samples |
| `/Users/wxl/mineru.json` | Operator MinerU config (device, models-dir, latex, llm-aided). **Contains secrets; not copied.** | `config_version` `"1.3.1"` |
| `/Users/wxl/Projects/repoprompt-ce-agno/benchmarks/duckrag_wi1/p19_mineru_process.py` | Offline PDF harness + golden content_list | repo `0c6ad30b000ac8ef532947b7b997933b6f28feb0` |
| `.../fixtures/p19-mineru-offline.pdf` | 672-byte 1-page fixture | present |
| `.../locks/mineru-3.4.4.lock.json` | PyPI/GitHub wheel lock | `version` `3.4.4`, `tag_commit_sha` `0dfc9460cd9ab693b9af60ae3fbffd7bc111b062` |
| `.../environments/mineru-3.4.4-cpython312-arm64/` | Canonical env contract (pipeline, CPython 3.12.13 arm64) | README + uv.lock + requirements-arm64.txt |
| `.../docs/investigations/duckrag-wi1/p19-s.json` | Prior completed P19-S evidence record (2026-08-07). Inspected, not re-run. | `run_status` `completed`; `genuine_offline_mineru_pdf_parse_completed` true |

Official unpacked MinerU 3.4.4 **source tree was not present** at `/Users/wxl/MinerU`. Upstream identity is the locked wheel, not a local git checkout.

## Frozen fields

### Runtime distribution (lock / harness; not live-hashed this session)

From `locks/mineru-3.4.4.lock.json`:

- package `mineru` version `3.4.4`
- wheel `mineru-3.4.4-py3-none-any.whl` sha256 `d4d678539782a7683d998e2914a52d96b5720676ce65658b29666b1f4d9dfd13` size `1540534`
- GitHub release tag `mineru-3.4.4-released`
- upstream repo `https://github.com/opendatalab/MinerU`
- tag commit `0dfc9460cd9ab693b9af60ae3fbffd7bc111b062`

From `p19_mineru_process.py:32-36` (pipeline model snapshot contract):

- `MODEL_REVISION` `ed6b654c018d742e65a17671e379c5e6ecc87ec9` (HuggingFace `opendatalab/PDF-Extract-Kit-1.0`)
- `MODEL_MANIFEST_SHA256` `8c4a6a53815e2a8f410d71350128d0db1276579ac9f50cd1dee56b165e4a4df6`
- `MODEL_FILE_COUNT` `187`
- `MODEL_TOTAL_BYTES` `15127785361`
- `MODEL_LICENSE` `AGPL-3.0`

Harness CLI for the frozen parse (`p19_mineru_process.py:813-827`):

```text
mineru -p <pdf> -o <out> -b pipeline -m txt -f false -t false
```

Env: `MINERU_MODEL_SOURCE=local`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `MODELSCOPE_OFFLINE=1`, `OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4` (`p19_mineru_process.py:670-687`).

Operator file `/Users/wxl/mineru.json` (do not copy credentials): `device` `mps`; `models-dir.pipeline` and `models-dir.vlm` point at ModelScope caches; `config_version` `1.3.1`. That operator config is **not** the P19-S locked pipeline profile.

### Canonical JSON artifacts

Harness requires exactly one of each (`p19_mineru_process.py:719-723`):

- `*_content_list.json` (not `*_content_list_v2.json`)
- `*_content_list_v2.json`
- `*_middle.json`

Local corpus under `/Users/wxl/MinerU` commonly also has `*_model.json`, `layout.json`, markdown, and `images/`. Sample `layout.json` top-level extras: `_backend=hybrid`, `_effort=medium`, `_ocr_enable=true`, `_version_name=3.4.0` (this corpus is **not** proven to be the 3.4.4 pipeline harness).

### `content_list.json` (canonical ingestion surface)

List of block objects. Observed keys by `type` (samples; not a closed enum from MinerU source):

| `type` | Typical keys | Notes |
|---|---|---|
| `text` | `bbox`, `page_idx`, `text`, optional `text_level` | `text_level` present marks a title in Popo (`label_normalization.py:551-553`) |
| `table` | `bbox`, `page_idx`, `img_path`, `table_body` (HTML), `table_caption[]`, `table_footnote[]` | table/image refs are paths + caption arrays, not tree IDs |
| `image` | `bbox`, `page_idx`, `img_path`, `image_caption[]`, `image_footnote[]`, `content` | |
| `list` | `bbox`, `page_idx`, `list_items[]`, `sub_type` | |
| `equation` | `bbox`, `page_idx`, `text`, `text_format` (`latex`) | |
| `code` | `bbox`, `page_idx`, `sub_type`, `code_caption[]`, `code_body` | |
| `chart` | `bbox`, `page_idx`, `img_path`, `content`, `chart_caption[]`, `chart_footnote[]`, `sub_type` | |
| `header` / `footer` / `page_number` / `page_footnote` / `aside_text` / `ref_text` | `bbox`, `page_idx`, text-like fields | |

Union of `type` across 30 local `content_list.json` files: `text`, `header`, `page_footnote`, `aside_text`, `image`, `chart`, `list`, `page_number`, `equation`, `table`, `code`, `ref_text`, `footer`. Unknown types must be preserved as raw JSON (plan §3.5 invariant 11).

**Page index:** `page_idx` is **0-based**. P19 golden uses `page_idx: 0` (`p19_mineru_process.py:739`). Catalog `page_start/page_end` is 1-based (plan §3.5); convert with `page_idx + 1`. MinerU-Popo already does this (`label_normalization.py:513`, `:561`).

**BBox:** length-4 **xyxy**. P19 validator (`p19_mineru_process.py:695-699`):

```text
0 <= x0 <= x1 <= page_size[0] and 0 <= y0 <= y1 <= page_size[1]
```

So canonical bbox is **page-pixel**, origin consistent with MinerU page coordinates (top-left in observed samples), **not** 0..1 and **not** a native source-line range. P19 fixture page_size `[612, 792]` (`p19_mineru_process.py:731-732`). Layout/middle `page_size` is `[width, height]` in the same pixel space.

P19 golden blocks (`p19_mineru_process.py:733-747`):

```json
[
  {"type":"text","text":"DuckRAG P19-S Fixture","text_level":1,"bbox":[112,70,439,94],"page_idx":0},
  {"type":"text","text":"Offline MinerU process-control verification.","bbox":[112,113,488,132],"page_idx":0}
]
```

### `layout.json` / `_middle.json` (tree + OCR lines)

`layout.json` / middle shape (sample + Popo `MineruReader._read_middle`):

```text
pdf_info[]:
  page_idx          # 0-based
  page_size         # [width, height]
  preproc_blocks[]
  para_blocks[]     # type, bbox, angle, lines[], index, level
  discarded_blocks[]
```

A block `lines[]` entry has `bbox` and `spans[]`; a span has `bbox`, `type`, `content`. These are **OCR/layout lines**, not PDF source-file line numbers. Across 30 `content_list.json` files, **zero** `line_idx` / `start_line` / `end_line` keys were observed.

### MinerU-Popo label map (adapter, not MinerU native)

`CANONICAL_TYPES = {title, text, image, table, caption}` (`label_normalization.py:31`).

`map_mineru_label` (`label_normalization.py:588-605`):

| MinerU `type` | canonical | popo_type |
|---|---|---|
| `title` | title | title |
| `image` | image | image |
| `table` | table | table |
| `image_caption` / `table_caption` / `image_footnote` / `table_footnote` | caption | same label |
| `equation` / `interline_equation` / `inline_equation` | text | equation |
| `list` | text | list_item |
| supplement labels (`page_title`, `page_number`, `page_footnote`, `header`, `aside_text`, `footer`, …) | text | mapped supplement |
| `discarded`, `image_body`, `table_body` | skip | skip |
| other | text | text |

Popo `normalize_text` (`label_normalization.py:135-138`): replace `\u3000` and `\n` with space, collapse whitespace, strip. **This is Popo normalization, not a MinerU-native contract.** v7 must pin its own `normalization_version` rather than silently inheriting Popo.

Popo `normalize_bbox_to_unit(..., assumed_scale=1000)` on content_list (`label_normalization.py:561`) is **not** the v7 catalog bbox: v7 stores page-pixel (or an explicit scale in metadata) plus 1-based page.

Popo tree nodes (`output_cases/trees/1.json`, `get_json_tree.py:22-33`): `type`, `title`, `metadata`, `content`, `level`, `location[{bbox, page}]`, `block_ids`, `children`. `page` in Popo trees is **1-based**. `content` may embed `<|txt_split|>` / `<|txt_contd|>`. This tree is evidence of a downstream mapping, not the MinerU JSON contract.

### Line projection feasibility

- PDF has **no native source lines**. Do not emit `range_origin=source_line` for MinerU PDF.
- Stable synthetic lines are feasible **only** from a persisted normalized text projection (`range_origin=normalized_line`).
- If only layout exists, use `range_origin=page_bbox` and leave line fields NULL.
- OCR `lines[]` inside middle/layout JSON are **not** `source_line`.

See `line_range_mapping.md`.

## Open unknowns (E0)

- Unpacked MinerU 3.4.4 **source** at a local git checkout.
- Whether `/Users/wxl/MinerU` corpus (`_version_name=3.4.0`, `_backend=hybrid`) is byte-compatible with the P19-S `3.4.4` `pipeline` CLI. Treat corpus as samples of shape, not as the golden parser version.
- Live PDF-Extract-Kit snapshot was not re-hashed this session (harness / in-tree `profile.json` constants exist; 187 files not present, hash not recalculated).
- `content_list_v2.json` page-of-blocks schema (title/paragraph/page_header/…) is observed but **not** the P19 canonical summary (`content_list` is).
- VLM backend (`mineru.json` `models-dir.vlm`) is operator-local and **out of** the P19-S pipeline freeze.
- `canonical_mineru_contract_version`: mineru.md has **no** document-level version string. Darwin `profile_id` is not that field. Kept `null` / `blocked` (user 2026-08-30).

MinerU **container image digest** is **N/A** (not an E0 gap): P19-S is not an OCI container runtime. Field remains null + `not_applicable`. Do not invent a digest.

## Evidence level and backend gate

- JSON node types / page / bbox / table-image refs / no native lines: **E1**.
- Wheel + snapshot identity: **E1** copied (lock / `profile.json` / `p19-s.json`). Snapshot files absent → not recalculated.
- P19-S prior run: evidence **record** at in-tree `v7/evidence/duckrag/p19-s.json`; **not** re-executed → do not mark live runtime E2.
- Range-trio origin-shape fixtures: **E2** of fixtures (`v7/tests/fixtures/range_trio/`); `live_runtime_missing` still true.
- Live wheelhouse/venv/187-file snapshot bytes: **E0** until re-provisioned this freeze.

v7 Flock `flock_rag_ingest_mineru` must parse `content_list` + middle/layout, keep unknown nodes as raw JSON, convert `page_idx+1`, store page-pixel bbox, and never call synthetic lines “source lines”.
