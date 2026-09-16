# Connection-local TEMP candidate stage (Phase 0 WI-5 / plan §3.8)

Evidence level: **E1** technical contract from v4.1 §3.8 (correcting review F-7 `candidates_json`). Phase 1 connection-local TEMP on the v7 binding is **E2**: `v7/evidence/phase1_runtime.e2.md`. This file remains the Phase 0 contract (register level stays E1). Ranking over the stage is still Phase 3.

Related backend: ranking must not accept arbitrary table names. Full-text candidate JSON round-trip is **forbidden**.

## What was read

- `docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md` §3.8 (lines 760–806), LongContext materialization order (790–804), scoring engine (808–829)
- `docs/reviews/oracle-v4-plan-review-2026-08-29.md` F-7
- Reader rules in §3.3 (TEMP allowed; persistent writes forbidden)

## Frozen fields

### Stage lifetime

- One query-only reader connection handles **one** query at a time.
- Stage is **connection-local TEMP** (not a persistent table, not shared across connections).
- Destroyed with the connection/query; never written into `text/rag.duckdb` or `schema/rag.duckdb`.
- Flock ranking (`flock_rag_rank_staged`) reads **only** this internal stage. It does **not** take a model- or user-supplied table name. Named-tool forbidden params include “arbitrary source table name” (plan §3.12).

### Required columns (closed set)

```text
candidate_id
document_id
revision
chunk_id
document_ordinal
chunk_ordinal
source_query_ordinal
bm25_score?              -- nullable
dense_score?             -- nullable
multi_vector_score?      -- nullable
llm_relevance_score?     -- nullable; filled after Python filter
page_start
page_end
line_start               -- nullable; NULL when range_origin=page_bbox
line_end                 -- nullable
range_origin
```

`range_origin` ∈ `{source_line, normalized_line, page_bbox, legacy_flat}` (see `line_range_mapping.md`).

### Explicitly excluded

- chunk text
- raw MinerU JSON
- embedding vectors
- full metadata JSON

### Materialization order (no full-text in ranking JSON)

```text
1. Flock recall: IDs/scores/ordinals only
2. TEMP stage
3. Flock preliminary dedup/fusion/rank
4. Truncate to LLM-filter candidate cap
5. Materialize those texts for Python filter
6. Python returns (candidate_id, llm_relevance_score)
7. Update TEMP scores
8. Flock final scoring + document order
9. Truncate final context set
10. Late materialize text/range/section/page metadata
11. Python TokenLimiter / context assembly
```

Python must not send full text back into Flock. `llm_rerank` is not this engine.

### Scoring tie-break (frozen)

```text
combined_score DESC
document_score DESC
document_ordinal ASC
chunk_ordinal ASC
candidate_id ASC
```

## Open unknowns

- Exact TEMP table/view **name** inside Flock C++ (must be internal, not user-visible). Phase 1 E2 used `rag_candidates` as the Python-side probe name.
- SQL types in the Phase 1 probe: scores `DOUBLE`, ordinals `INTEGER`, ids/origin `VARCHAR`. Flock C++ may still choose `BIGINT` vs `UBIGINT` in Phase 3.

Phase 1 E2 on the v7 binding: TEMP is connection-local; it does not leak to another reader or persist into the writer’s main schema.

## Backend gate

Ranking implementation is blocked until this column set is used. Reintroducing `candidates_json` with text is a contract violation.
