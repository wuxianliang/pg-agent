# Line-range mapping rules (Phase 0 WI-5 / plan §3.5 + review F-4)

Evidence level: **E1**. Derivation rule is frozen from the plan plus MinerU JSON samples that contain **no** source-line fields. **Not E2** (no golden PDF/code/legacy trio executed in this freeze).

Related backend: TokenLimiter and catalog invariants 8–9. PDF synthetic lines must never be called source lines.

## What was read

- Plan §3.5 (`flock-rag-on-duckdb-final-plan-v4.1.md:489–605`), TokenLimiter range interpretation (`:1107–1114`), §3.15 “将PDF synthetic line称为源码行”
- Review F-4 (`docs/reviews/oracle-v4-plan-review-2026-08-29.md:63-65`): MinerU emits page/block/bbox; 1-based line ranges are an imported code-file assumption
- MinerU samples under `/Users/wxl/MinerU` (`content_list.json`, `layout.json`): bbox + `page_idx`; no `start_line` / `end_line` / `line_idx` on content_list (30-file scan)
- P19 harness bbox validator: page-pixel vs `page_size` (`p19_mineru_process.py:695-699`)
- auto-coder TokenLimiter: 1-based closed lines (`token_limiter.py:21-41`, `types.py:61-63`)
- KohakuRAG PDF pages 1-based (`pdf_utils.py:93`) vs MinerU `page_idx` 0-based

## Frozen `range_origin` (closed set)

| value | When | Line fields | What TokenLimiter / SourceCode may show |
|---|---|---|---|
| `source_line` | Input itself has trustworthy stable line numbers (code, plain text files) | 1-based **closed** `line_start`/`line_end` aligned to the real file | May be described as source lines |
| `normalized_line` | PDF (or other layout doc) after a **persisted** normalized text projection | 1-based closed lines into `rag_projection_line` | Synthetic normalized lines **only**. Metadata must also carry `range_origin`, page, bbox. **Never** call these PDF/source-file lines |
| `page_bbox` | No reliable linear map | `line_start`/`line_end` **NULL** (invariant 9) | Locate by page/bbox/node/char. TokenLimiter must **not** fabricate line ranges |
| `legacy_flat` | auto-coder DuckDB cache `content`/`raw_content` | 1-based closed lines on the persisted flat projection | Compatibility only. Do not invent section/page/bbox/table/image |

Every public range must have a legal `range_origin` (plan quality gate).

## Canonical locators (always, independent of lines)

- `page_start` / `page_end`: **1-based** (convert MinerU `page_idx + 1`)
- `bbox_json`: page-relative; MinerU content_list bbox is page-pixel xyxy `[x0,y0,x1,y1]` with `0 ≤ x0 ≤ x1 ≤ page_width` and `0 ≤ y0 ≤ y1 ≤ page_height` (P19 validator)
- `node_start_id` / `node_end_id`
- `projection_id`
- `char_start` / `char_end`: **0-based half-open**, Unicode **code points**
- optional `line_start` / `line_end`: **1-based closed**, only when origin is not `page_bbox`

## Projection tables

`rag_text_projection`: `projection_id, document_id, revision, projection_kind, normalization_version, text, text_hash, line_count, created_at`.

`rag_projection_line`: `projection_id, line_number, char_start, char_end, page_number?, node_id?`.

Constraints:

- `line_number` starts at 1
- char ranges stay 0-based half-open
- text, normalization version, line table, hash written atomically
- node/chunk line ranges may only cite **that** projection
- normalization change → new document revision or projection generation
- **Forbidden:** re-splitting the same text at query time and calling it a persistent source range

## Derivation rules (F-4)

1. **PDF / MinerU:** native origin is `page_bbox`. If and only if v7 writes a stable normalized projection (pinned `normalization_version`), it **may** also expose `normalized_line`. OCR `lines[]` inside middle/layout JSON are layout lines, not `source_line`.
2. **Code / plain text:** `source_line` from the file’s newline split (`\n`), 1-based closed, matching auto-coder `add_line_numbers`.
3. **Legacy cache:** `legacy_flat` from persisted `content`/`raw_content` newlines. No fake MinerU tree.
4. **Compatibility facade** `SourceCode.start_line/end_line`: allowed for `source_line` and `normalized_line` (and `legacy_flat`); **forbidden** for `page_bbox`. PDF facade must include `range_origin` in metadata.
5. Invariant 8 (“line range matches projection line table”) applies **only when line fields are non-NULL**.

## What is not a source line

- MinerU `content_list` block order
- Popo tree `level` / `block_ids`
- layout.json `lines[].spans[]`
- KohakuRAG sentence index
- TokenLimiter display prefixes (`"{n} {line}"`) unless `range_origin=source_line`

## Open unknowns

- Exact newline/Unicode normalization for `normalized_line` (`normalization_version` string not assigned yet).
- Whether to keep OCR layout-line maps as a **non-public** debug table (not `source_line`).
- Golden fixtures for the three classes (PDF / code / legacy): origin-shape trio is at `v7/tests/fixtures/range_trio/` (fixture **E2**; `live_runtime_missing` still true; not live parse; not plan §3.14 large/multipage/table corpus). `normalization_version` for `normalized_line` is still unassigned.

## Backend gate

Ingestion of PDF as `source_line` is a contract violation. TokenLimiter on `page_bbox` without fabricating lines is required before PDF QA ships.
