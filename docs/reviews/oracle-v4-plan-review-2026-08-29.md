# Review: Oracle v4 Plan — Flock RAG on DuckDB (v7)

> **Subject:** `prompt-exports/oracle-plan-2026-08-29-161937-untitled-chat-f39d4d-dba3.md` (Oracle v4 authoritative plan, supersedes v3)
> **Reviewer:** planning-only independent critique; no code modified.
> **Date:** 2026-08-29

---

## 1. Context / Scope

The v4 plan proposes a v7 deployment-scoped, persistent RAG platform alongside the existing v6 run-scoped temporary DuckDB workbench. Scope of this review: verify the plan against six product constraints and surface incorrect assumptions, missing dependencies, overdesigned schemas, security/lifecycle gaps, and phase-ordering errors.

### Spot-check verification performed

| Plan claim | Verification | Result |
|---|---|---|
| v6 layout (`v6/session_durability`, `v6/source_ingress`, `v6/queue_bridge`, `v6/duck_tools`, `v6/load.py`) | `ls v6/` | ✅ Accurate |
| Target fork at `a1f0ab1911`, branch `integration/grammar-24919-20260829` | `git log` | ✅ Accurate |
| NEAREST grammar shape `JoinType? JOIN ... ApproxOrExact? 'NEAREST' NumberLiteral? 'BY' DistanceOrSimilarity Expression` | `select.gram:106–116` | ✅ Accurate; bare/aliased alternation exists |
| "不写数字时默认 top-1"; APPROX possibly == EXACT | `joinref.hpp:52–56` (`nearest_count = 1`, `nearest_approx` marked *informational*) | ✅ Accurate — plan's caution is well-founded |
| `Config::db` static global unsuitable for deployments | `flock/core/config.hpp:15–22` | ✅ Accurate |
| `FusionRRF` exists but is not a full ranking engine | `functions/scalar/fusion_rrf.hpp` | ✅ Accurate |

The plan's evidence discipline (E0–E3 gating) and its factual claims about the four repos check out where verifiable.

---

## 2. Constraint-by-constraint assessment

| # | Constraint | Verdict |
|---|---|---|
| 1 | v7 permanent RAG vs v6 temporary workbench isolation | **Satisfied, strong.** Explicit non-reuse list, separate queues/tables/APIs, architecture tests, and lifecycle tables. See F-1 for a residual concurrency gap. |
| 2 | MinerU JSON → Kohaku-style tree → DuckDB | **Mostly satisfied.** Contract freeze gated on real fixtures; tree invariants are thorough. See F-4 (line-range assumption) and F-6 (schema redundancy). |
| 3 | DuckDB 2.0 NEAREST + mdenseon dense + duckdb-tachiom multi-vector, unknown APIs gated | **Satisfied, exemplary.** No fabricated APIs; E0 items block phases; APPROX claims correctly withheld; no silent fallback. Verified NEAREST facts match the fork. |
| 4 | Full LongContextRAG parity + correct Flock C++ vs Python split | **Satisfied.** Split table (§3.14) is defensible: Flock owns parsing/indexing/ranking, Python owns LLM orchestration; `llm_rerank` explicitly not repurposed. See F-2 (streaming/queue interplay) and F-7 (ranking JSON round-trip). |
| 5 | Tree ingestion as independent Flock capability | **Weakly satisfied.** `flock_rag_ingest_mineru` is Flock-owned, but it is only ever specified against the persistent revisioned catalog — there is no acceptance criterion for using tree ingestion standalone (ad-hoc DB file, no v7 runtime). See F-9. |
| 6 | Separate but interoperable schema RAG (Infinisynapse RAG→Schema→SQL) | **Satisfied.** Physical separation, `provider_kind` preservation, hybrid routing, and the `list_tables → show_create → register_table → execute` choreography are all present. See F-5 (external adapter credentials). |

---

## 3. Findings, ranked by severity

### Critical

*(none — no constraint is violated outright)*

### High

**F-1. Cross-process reader/writer concurrency on DuckDB files is unspecified and likely broken as written.**
DuckDB permits exactly one process to hold a read-write handle on a database file; other processes may open it read-only only when no writer holds it. The plan creates a `rag_query_requests` queue that "query 可在 active generation 上并发执行" and an owner-worker writer model, but never states that query workers must *be* the owner process (or use read-only snapshot copies). If any non-owner worker claims a query operation while the owner holds the writer connection, the file open fails. §3.3's "reader pool" is per-`DeploymentRagStore`, but the queue design (§3.4) implies multi-worker claim semantics.
*Correction:* Phase 6 must state one of: (a) all query handling is pinned to the lease-holding owner process; (b) queries use `read_only` connections and the writer is closed between ingest operations; or (c) queries run against generation-stamped read-only file copies. Add an integration test: non-owner worker claims query while owner is mid-ingest.

**F-2. Streaming QA over the deferred queue path is contradictory and unresolved.**
§3.11 builds a live streaming generator (LLM futures, cancel events, `answer_delta`); §3.12 routes `use_rag_tool` through `rag_query_requests` (a deferred PGMQ envelope). A deferred queue execution cannot stream tokens back to the model-facing tool call. The plan never defines which path streams and which defers, nor how stream events are persisted/replayed for deferred results.
*Correction:* Define explicitly: streaming only on the synchronous provider path; the queued path returns a bounded non-streaming summary envelope. Add this to the Phase 5→6 handoff contract.

**F-3. Phase-ordering bug: the legacy auto-coder cache importer is Phase 7, but Phase 0 baselines and Phase 3 parity depend on it.**
§6.2 requires the Phase 0 golden baseline to use "auto-coder legacy DuckDB fixture," and Phase 3 exit criterion 11 requires "simple retrieval parity" against auto-coder fixtures — yet the importer (`.cache/byzerai_store_duckdb.db` → v7 catalog) is scheduled in Phase 7 (§8, Phase 7 item 1). You cannot establish parity in Phase 3 without the import path.
*Correction:* Move a minimal read-only legacy importer (or fixture-level converter) to Phase 0/2; keep only the production-grade opt-in importer in Phase 7.

### Medium

**F-4. 1-based line ranges are an imported assumption that MinerU output does not natively support.**
`rag_node.line_start/line_end`, `rag_chunk` line ranges, and TokenLimiter 1-based ranges come from auto-coder's code-file RAG. MinerU emits page/block/bbox structure — there are no source lines. The plan does list "source line/range 生成规则" in the Phase 0 freeze (§3.5), but treats line ranges as a guaranteed invariant (§3.6 invariant 8) rather than a derived, possibly-absent attribute.
*Correction:* Make line ranges explicitly derived (e.g., from `normalized_text` splitting) with a documented derivation rule, or nullable with `page/bbox` as the authoritative locator for PDFs. Phase 0 must produce the derivation rule before invariant 8 is enforceable.

**F-5. Missing dependency: credential storage for schema-RAG external DB adapters and v7 Python LLM calls.**
The plan forbids model-supplied DSNs and Flock's secret manager for RAG, but never says where external-adapter credentials (schema RAG §3.10) or Python-side LLM API keys (relevance filter, QA) live. This is a security-relevant gap, not a detail.
*Correction:* Add a Phase 4/6 work item: operator-managed secret source (env/Postgres vault pattern consistent with existing pg-agent practice), referenced by alias only.

**F-6. Overdesigned/redundant `deployment_id` columns, applied inconsistently.**
Each deployment has its own physical text/schema DuckDB files (§3.3), making a `deployment_id` column inside those files redundant. Worse, it's inconsistent: `rag_document`, `rag_section`, `rag_node`, `rag_edge`, `rag_metadata` carry it; `rag_page`, `rag_table`, `rag_image`, `rag_chunk`, `rag_vector`, `rag_index_manifest` do not.
*Correction:* Drop `deployment_id` from all per-deployment-file tables (identity comes from the file), or add it everywhere with a justification. Dropping is simpler and shrinks every PK.

**F-7. `flock_rag_rank_candidates(candidates_json)` round-trips full candidate text through JSON into DuckDB just to sort.**
Candidates include `text` and `metadata_json`; serializing potentially hundreds of chunks (top_k up to legacy 10000) into JSON to re-enter DuckDB for a deterministic sort is heavy and adds a failure mode (JSON size limits, encoding). The ranking logic is pure arithmetic over scores/ordinals.
*Correction:* Either pass a slim candidate projection (ids + scores + ordinals only, no text) into the ranking function, or justify why ranking must live in Flock at all given the LLM scores originate in Python. If kept, document the payload bound.

**F-8. Query-path metrics writes conflict with the read-only reader pool.**
§3.9 writes RAG metrics to `rag_query_metrics` in DuckDB, but queries execute on reader connections (§3.3) which should be read-only. Writing per-query metrics requires the writer connection, serializing the read path.
*Correction:* Buffer metrics in memory on the reader and hand off to the owner/writer asynchronously, or write metrics only to Postgres/observability (which the plan already supports as an option — make it the default).

### Low

**F-9. Constraint 5 (tree ingestion as an independent Flock capability) lacks a standalone acceptance test.**
Add a Phase 2 exit criterion: ingest a MinerU fixture into a throwaway DuckDB file via `flock_rag_ingest_mineru` with no v7 runtime, no Postgres, no queues — proving the capability is independently usable and testable.

**F-10. MinerU runtime and model-artifact supply chain are absent from the manifest.**
The version manifest (§3.1) pins code commits but not: the MinerU installation itself (a heavy Python/GPU dependency that produces the input JSON), mdenseon model weights (storage, signing, hash), or the tokenizer used by `token_counter` (must match the QA LLM's tokenizer for TokenLimiter parity). All three affect reproducibility.
*Correction:* Add MinerU version+config hash, mdenseon model artifact hash, and tokenizer identifier to the Phase 0 manifest.

**F-11. No retention/GC policy for RETIRED revisions and `backups/<generation>/`.**
`cleanup.py` covers failed generations and stale leases but not retired-revision pruning or backup rotation; per-revision `raw_mineru_json` (full JSON per revision) plus indexes makes storage growth unbounded.
*Correction:* Add a retention knob (keep last N revisions / M backups) to `rag_deployments` and a cleanup test.

**F-12. Phase 2 work item 1 says "text/schema catalog schema versioning" but schema tables only arrive in Phase 4.**
Minor internal inconsistency; either scope Phase 2 to text catalog only or move schema catalog versioning earlier.

**F-13. "Signed and verified extensions" (§3.3 step 8) is moot for statically linked extensions.**
DuckDB extension signing applies to loadable binaries from repositories; with static linking and no runtime `INSTALL`/`LOAD`, verification is the build-time manifest check the plan already mandates. Reword to avoid implying a runtime signature check that doesn't exist.

---

## 4. Recommendations (action order)

1. **(F-1)** Pin down the single-process writer/reader topology before Phase 6 design is final; add the non-owner-claims-query test.
2. **(F-3)** Pull a minimal legacy-cache importer into Phase 0/2 so Phase 3 parity is executable.
3. **(F-2)** Specify streaming-vs-deferred as mutually exclusive paths in the Phase 5→6 contract.
4. **(F-4, F-6)** Phase 0 must freeze the line-range derivation rule; simplify catalog schemas (drop redundant `deployment_id`).
5. **(F-5, F-10, F-11)** Extend the manifest and add credential/retention work items to Phases 4/6.
6. **(F-7, F-8)** Slim the ranking payload; default metrics to Postgres/observability, not the reader-path DuckDB file.
7. **(F-9, F-12, F-13)** Add the standalone-ingestion acceptance test; fix the Phase 2/4 scoping wording; reword the signing claim.

## 5. Overall verdict

The plan is unusually strong on evidence discipline, unknown-API gating (constraint 3), and the v6/v7 isolation boundary (constraint 1); its verifiable factual claims about the target fork and Flock internals are accurate. It should **not** proceed to implementation as-is: F-1 through F-3 require plan amendments (concurrency topology, importer ordering, streaming/queue contract) before Phase 0 exits, and the medium findings are cheap to fix now and expensive to retrofit later.
