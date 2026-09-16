# Flock RAG v4.1 — review correction traceability

Phase 0 WI-1 deliverable. Authority: `docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md`.
This file maps review findings to v4.1 text. It does not restate the reviews as implementation authority.

Sources (review **bodies not edited**):

| ID prefix | Reviewed artifact | Review file |
|---|---|---|
| F-1 … F-13 | Oracle v4 plan (`prompt-exports/oracle-plan-2026-08-29-161937-untitled-chat-f39d4d-dba3.md`) | `docs/reviews/oracle-v4-plan-review-2026-08-29.md` |
| C1 … C10 and DR-* | Earlier Oracle Flock RAG plan (`prompt-exports/oracle-plan-2026-08-29-141649-flock-rag-on-duckdb-3525.md`) | `docs/reviews/flock-rag-on-duckdb-plan-review-2026-08-29.md` |

Method:

- Status is taken only from v4.1 wording, not from v3/v4 or from intent.
- **ABSORBED**: v4.1 contains the requested correction (or removes the incorrect claim).
- **PARTIAL**: some of the correction is in v4.1; the rest is not written.
- **UNRESOLVED**: the requested correction is not in v4.1.
- Overlapping findings are listed under every review ID; the later row may say “same as …”.
- Confirmations and “sound / satisfied” verdicts that do not ask for a change are not rows.

v4.1 header (unique authority):

> 本输出：**Oracle v4.1 最终权威计划**，是后续实现、评审和验收的唯一计划依据。

---

## 1. Oracle v4 plan review — F-1 … F-13

| Finding | Severity (review) | v4.1 section | Status | How v4.1 addresses it (quote / summary) |
|---|---|---|---|---|
| **F-1** Cross-process reader/writer on DuckDB files unspecified; query workers may not be the owner | High | §3.3; also §1, §3.4 queue family, §3.14 并发与 failover 门, §3.15, Phase 6 | **ABSORBED** | Chooses review option (a), not (b)/(c): “同一 deployment 的 live text/schema DuckDB 文件只允许唯一 owner 进程打开.” Query-only readers are same-process; “不依赖第二个进程以 native read-only mode 打开同一文件.” `rag_query_requests` “只由 active owner service 消费.” Gate: “任何非 owner进程打开 live file 的测试必须失败.” First period explicitly does **not** implement generation-stamped snapshots or non-owner live opens. |
| **F-2** Streaming QA vs deferred `rag_query_requests` contradictory | High | §3.4; also §3.11–3.12, §3.15, Phase 5→6 | **ABSORBED** | Three mutually exclusive modes: `stream`/`defer`; `true/true` → `RAG_ARGUMENT_ERROR`. “只有 direct streaming path 可以返回 `answer_delta`”; deferred “内部不得产生或持久化 `answer_delta`”; “不得在 owner 不可达时把 `stream=true` 静默降级为 deferred.” Phase 6 exit: “streaming只走IPC; deferred永不返回 `answer_delta`.” |
| **F-3** Legacy importer in Phase 7 but Phase 0/3 parity depends on it | High | §3.6; also §1, §5.8, Phase 0/2/7, §3.15 | **ABSORBED** | “Phase 0：最小只读 probe”; “Phase 2：正式 canonical importer”; “Phase 7 只调用该 importer 执行生产迁移，不再首次开发 importer.” §3.15: 首期不做 “在Phase 7首次开发legacy importer.” |
| **F-4** 1-based line ranges assumed; MinerU has page/bbox, not source lines | Medium | §3.5; also §3.11 TokenLimiter, §5.4, Phase 0 item 5/exit | **ABSORBED** | “不能假设 MinerU 原生提供源码行号.” Canonical locators are page/bbox/node/char; line ranges optional. Closed `range_origin` set: `source_line` / `normalized_line` / `page_bbox` / `legacy_flat`. Invariants 8–9: line ranges must match projection line table; `page_bbox` line fields empty. TokenLimiter “不得把 `page_bbox` range伪造成 line range.” Phase 0 exit: “line-range mapping规则冻结.” |
| **F-5** No credential store for schema-RAG adapters and Python LLM keys | Medium | §3.10 Secret registry; also §3.12–3.13, Phase 4, §5.5 | **ABSORBED** | “统一使用 pg-agent/operator secret registry.” Covers “external schema adapter credential” and “LLM provider key.” Postgres/DuckDB/queue/manifest store only opaque refs; Flock SQL “不接受 credential、DSN、token或 secret ref”; v7 LongContext “不复用 Flock旧 `llm_*` secret flow.” |
| **F-6** Redundant/inconsistent `deployment_id` columns in per-file tables | Medium | §3.3 文件内 deployment identity; also §3.5, §3.10, Phase 2 exit | **ABSORBED** | “所有 per-deployment fact tables **省略 `deployment_id`**”; identity is one-row `flock_rag_store_meta` plus external `manifest.json`; mismatch → `RAG_STORE_IDENTITY_MISMATCH`. Phase 2 exit: “Facts表不重复deployment ID.” |
| **F-7** `flock_rag_rank_candidates(candidates_json)` full-text JSON round-trip | Medium | §3.8 Candidate stage; also Phase 3 exit, §4.1 `candidate_stage.py` | **ABSORBED** | “取消上一版 `candidates_json` full-text round trip.” TEMP stage is ID/score/ordinal/`range_origin` only; “明确不包含：chunk text; raw MinerU JSON; embedding; 完整 metadata JSON.” Phase 3 exit: “无full-text candidates JSON往返.” Ranking stays in Flock over the stage, not over a JSON payload. |
| **F-8** Query metrics writes vs read-only reader pool | Medium | §3.9; also §3.13, Phase 6 exit | **ABSORBED** | “Query-only reader 不写 `rag_query_metrics` 或任何 persistent DuckDB table.” Query returns bounded metrics; owner `RagMetricsSink` async-upserts Postgres; “不回写 text/schema DuckDB.” Phase 6 exit: “reader不写query metrics.” |
| **F-9** Constraint 5: no standalone tree-ingestion acceptance test (throwaway DuckDB, no v7 runtime/Postgres/queues) | Low | §3.8 `flock_rag_ingest_mineru`; §4.2 `test/sql/rag/mineru_tree.test`; Phase 2 | **PARTIAL** | Ingestion is a Flock table function with Flock SQL tests in Phase 2 (before Phase 6 owner/queues). v4.1 does **not** write the requested Phase 2 exit criterion: ingest a MinerU fixture into a throwaway DuckDB file via `flock_rag_ingest_mineru` with no v7 runtime, no Postgres, no queues. |
| **F-10** Manifest pins commits but not MinerU install, mdenseon weights, tokenizer | Low | §3.2 Manifest 必备字段; Phase 0 items 6/11; identity shape superseded by **F-14** | **ABSORBED** | Manifest still pins MinerU **install** (wheel+lock+profile) and **weights** (snapshot manifest sha256); mdenseon package/runtime + “mdenseon model weights SHA-256”; “tokenizer identity、version/hash.” Superseded by F-14 for MinerU identity **shape**: runtime identity is wheel sha256 + `profile_id` + 84-wheel lock, model identity is HF revision + `snapshot_manifest_sha256` + file_count + total_bytes (no single-file weights sha). Container digest is N/A (not an OCI runtime), not a remaining F-10 gap. |
| **F-11** No retention/GC for RETIRED revisions and `backups/<generation>/` | Low | §3.7; also §4.1 cleanup/backup/gc, Phase 2/6/7, `test_retention_gc.py` | **ABSORBED** | Default policy: last 2 retired revisions and all retired but not yet 30 days old; last 3 backups and all backups not yet 14 days old; raw MinerU JSON follows revision; pins/legal-hold never expire until unpinned. Owner-only GC with dry-run/apply and generation fence. |
| **F-12** Phase 2 “text/schema catalog schema versioning” vs schema tables in Phase 4 | Low | Phase 2 work 1–2; Phase 4; §3.3 `store_kind`/`catalog_version` | **PARTIAL** | Phase 2 still says “实现text/schema catalog versioning” while schema RAG relation tables remain Phase 4. Store-level identity (`flock_rag_store_meta`, `store_kind = text\|schema`, `catalog_version`) is specified in §3.3 and started in Phase 2, but the Phase 2/4 wording split F-12 flagged is not rewritten to “text catalog only” or “schema tables moved earlier.” |
| **F-13** “Signed and verified extensions” moot for static linking | Low | §3.2; §3.15; §4.3–4.4; Phase 1 | **ABSORBED** | v4.1 never states a runtime extension signature check. First period forbids runtime `INSTALL`/`LOAD` and network extension download. Verification is build-time/manifest: exact commits, “wheel和extension artifact hashes,” ABI/catalog mismatch refuses open. |

Oracle review §4 recommendations 1–7 only reorder F-1…F-13; not separate findings.
Constraint table rows 1–6 point at F-1, F-4, F-6, F-2, F-7, F-9, F-5; not separate findings.

### 1.1 Post-v4.1 plan amendments

Rows written into v4.1 **after** its freeze, from implementation evidence — not Oracle review findings. They are excluded from the `oracle_v4_F` bucket (stays mapped 13 / ABSORBED 11) and never change the unique UNRESOLVED / PARTIAL lists. Each amendment is ABSORBED in the same change that lands it.

| Finding | Severity | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|---|
| **F-14** v4.1 §3.2 / the F-10 landing pinned MinerU identity as a container image digest plus a weights hash readable as single-file weights; DuckRAG P19-S shows the real identity is the `mineru[pipeline]==3.4.4` wheel + 84-wheel lock + `profile_id` + 187-file snapshot manifest. Phase 0 also made live MinerU execution a `phase0_pass` predicate, beyond its E1 contract exit. | Medium | §3.2 必备字段/兼容规则; §3.13 MinerU执行/获取; §3.14 baseline corpus; Phase 0 工作 5 与出口; §4.1 `v7/mineru/contracts.py` | **ABSORBED** | §3.2 now pins MinerU runtime identity = wheel sha256 + `profile_id` + 84-wheel lock; container image digest **N/A** (not an OCI runtime; stays null, never a fabricated hash). Model identity = HF revision + `snapshot_manifest_sha256` + file_count + total_bytes; no single-file weights sha. N/A digest/single-file do not count as hash missing for the release gate; other required hashes still fail when missing. Phase 0 exit keeps the E1 contract freeze, records range-trio acceptance as fixtures E2 (`v7/tests/fixtures/range_trio/`, origin-shape only; 小PDF、大PDF、多页、table/image corpus stays unsatisfied/later), and adds **Option B (2026-08-30)**: live MinerU execution is not a `phase0_pass` predicate; the `live_mineru_runtime` gate stays honestly blocked. `canonical_mineru_contract_version` stays blocked and is not covered by F-14. Authority: `docs/designs/phase0-mineru-unblock.md` (Accepted 2026-08-30). |

---

## 2. Design review — ranked corrections C1 … C10

This review targeted the earlier ~2,900-line Oracle plan, not the v4 draft. v4.1 claims to inherit “design review 纠正.” Mapping is still against **v4.1 text only**.

| Finding | Severity | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|---|
| **C1** Parser migration is not a hard blocker; `parse_function` still runs on PEG failure; `parser_override` skipped in DEFAULT; override signature already in `parser_extension.hpp:150`; rewrite parser section / de-scope Phase 2 atomicity | High | §4.2 明确不修改; §2.4 | **ABSORBED** | v4.1 does not treat PEG `parser_override` as a RAG blocker or a Phase 1 discovery item. RAG “明确不修改 … 现有 custom parser model/prompt statements.” Existing `llm_*` / custom parser stay; v7 RAG is additive. The false “callback signature unknowable until Phase 1” claim is not in v4.1. (Enum/file citation slips: see C8 / DR-I-2 / DR-I-3.) |
| **C2** Single-writer DuckDB file constraint unaddressed; define multi-worker behavior; two-process contention test | High | §3.3; §3.14; Phase 6; same as **F-1** | **ABSORBED** | Owner-only live-file mode; one active owner service; non-owner open must fail. |
| **C3** Immutable `document_version` over-committed before Phase 0 update semantics; downgrade to conditional; provide overwrite-in-place fallback | High | §3.5 Revision activation; §3.6 | **UNRESOLVED** | Requested correction is absent. v4.1 makes revisioned catalog **core** (`BUILDING → … → atomic active_revision swap → previous revision RETIRED`) and uses the same revision transaction for legacy import. There is no “conditional on Phase 0 update-semantics” label and no overwrite-in-place fallback. |
| **C4** Pinned pg-agent wheel lacks special-repo grammar; Phase 7 is external-clients only; static wheel is near-term pg-agent distribution; dynamic path is not a peer of pg-agent integration | Medium | §3.2; §4.4; Phase 1; §3.15 | **ABSORBED** | pg-agent v7 distribution is the static `duckdb-python-pgagent` artifact “与 v6 wheel 分离.” No special-repository workstream or phase. First period: no runtime `INSTALL`/`LOAD`, no network extension download. |
| **C5** Phase 0 needs degraded mode if auto-coder cannot be executed (freeze from source + fixtures; defer runtime goldens) | Medium | Phase 0 入口/工作/出口 | **PARTIAL** | Phase 0 is mostly read-only evidence plus a cache **probe** (does not require standing up auto-coder 3.0.74 as a live RAG service). There is **no named degraded path**. Entrance assumes “legacy auto-coder cache和fixture可访问”; exit still requires “Legacy golden baseline已生成.” v3’s “degraded inventory可推进 Phase 1/2” language is not in v4.1. |
| **C6** Artifact revocation: minimum-version / blocklist; “bad signed artifact” drill; key rotation cannot recall a signed bad release | Medium | §3.2; §5.2; §5.9 | **PARTIAL** | Pin-by-hash and “旧binary不得原地打开新格式文件”; rollback restores matching old backup + old runtime. No version-blocklist, minimum-version recommendation, yank/denylist, or “bad signed artifact” drill. Special-repo signing (the original C6 setting) is also out of v4.1 scope. |
| **C7** Embedding storage: use `FLOAT[]` or justify `DOUBLE[]` before schema lock | Medium | §3.2 dtype; §3.5 `rag_vector`; Phase 0 item 6 | **PARTIAL** | v4.1 does **not** default new catalog embeddings to `DOUBLE[]`. `rag_vector` is “chunk/vector role/model/dimension/embedding”; dtype is a manifest/Phase 0 freeze. It does **not** explicitly select `FLOAT[]` (v3 did). Legacy cache `vector FLOAT[]` is only described as the old schema. |
| **C8** Factual slips: `AllowParserOverride` values are `*_OVERRIDE`; gating in `parser.cpp` not `parse_iterator.cpp`; setting in `settings.hpp` / `autogenerated_settings.cpp`; flock `.gitmodules` tracks `main`, v1.5.4 pin is CI-only | Low | §3.2 flock constraint; §4.2 (parser out of RAG edits) | **ABSORBED** | Those incorrect names/paths/submodule claims are **not restated** in v4.1. Flock “不得使用 floating DuckDB submodule.” v4.1 does not re-document the CI-only v1.5.4 pin as a current-state fact (the original false “submodule pin” claim is gone). |
| **C9** Gap-matrix rerank row missing 待 Phase 0; add per-row “closed by” verification column | Low | §2.3 当前差距矩阵; §3.11; Phase 0 item 8 | **ABSORBED** | Nine-dimension v3 matrix is replaced. §2.3 rows include LongContextRAG / candidate ranking with a **关闭条件** column. `llm_rerank` “不作为替代实现”; Phase 0 reads LongContext filter/retry defaults rather than hardcoding sliding-window as auto-coder unknown. |
| **C10** Per-API result projections (drop always-NULL score columns from `flock_rag_search_vector`) or document the NULL contract | Low | §3.8 Flock SQL API | **ABSORBED** | No 13-column uniform search row with permanently NULL `lexical_score`/`fused_score`/`rerank_score`. `flock_rag_recall` returns IDs/scores/ordinals only; `flock_rag_search` is a convenience facade that materializes after rank. |

---

## 3. Design review — §1 numbered inaccuracies

| Finding | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|
| **DR-I-1** “PEG parser override is a hard migration blocker; old `parse_function` cannot be the final implementation” overstated; override typedef already known | §4.2; same as **C1** | **ABSORBED** | Parser override is not a RAG migration blocker; existing custom parser is unmodified. |
| **DR-I-2** Enum names `DEFAULT/FALLBACK/STRICT` vs `DEFAULT_OVERRIDE/FALLBACK_OVERRIDE/STRICT_OVERRIDE` | — (not restated) | **ABSORBED** | Incorrect enum names do not appear in v4.1. |
| **DR-I-3** FALLBACK/STRICT gating mis-cited as `parse_iterator.cpp` / `custom_settings.cpp`; actual `parser.cpp`, `settings.hpp` / `autogenerated_settings.cpp` | — (not restated) | **ABSORBED** | Those file citations do not appear in v4.1. |
| **DR-I-4** “flock pinned DuckDB v1.5.4 submodule” is wrong; `.gitmodules` is `branch = main`; v1.5.4 is CI-only | §3.2 四仓硬约束 | **ABSORBED** | v4.1 does not claim a v1.5.4 submodule pin. Constraint: Flock “使用目标 DuckDB fork 编译；不得使用 floating DuckDB submodule.” |

---

## 4. Design review — other named findings (not already a C\* row)

Unnumbered issues in §§2–6 that ask for a plan change. Duplicates of C\* are omitted here except a pointer.

### 4.1 Gap matrix (§2)

| Finding | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|
| **DR-GM-1** Rerank auto-coder cell missing 待 Phase 0 | §2.3; §3.11; same as **C9** | **ABSORBED** | See C9. |
| **DR-GM-2** Matrix has no per-row verification / “closed by” column | §2.3 | **ABSORBED** | Gap matrix has a **关闭条件** column. |
| **DR-GM-3** Credential/secret lifecycle omitted from the nine dimensions | §2.3 Credential storage row; §3.10 | **ABSORBED** | Explicit gap-matrix row: operator secret registry; “Postgres/DuckDB/queue/log 无明文凭据.” |

### 4.2 Phase ordering (§4)

| Finding | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|
| **DR-PO-1** P1 forks the critical path (fork build + signed test artifact + static loader sequential before RAG schema); no P1-lite / parallel catalog against upstream | Phase 1 原子落地 | **UNRESOLVED** | Phase 1 still requires “target DuckDB、Flock static integration、loader、manifest和smoke tests必须一起合入” before Phase 2 catalog. No headers-only / upstream-parallel catalog path. |
| **DR-PO-2** P2 “parser/CMake/CI/ABI 必须原子落地” unresourced; no named rollback for a half-merged P2 | Phase 1–2 原子落地; §5.9 | **UNRESOLVED** | v4.1 still demands atomic landings. §5.9 is **production catalog** rollback (stop owner, restore backup, matching old runtime), not a merge/feature-flag strategy for a half-merged Phase 2. Parser atomicity is moot (C1) but CMake/ABI atomicity remains without a named half-merge rollback. |
| **DR-PO-3** Missing workstream: maintain/patch flock v0.4.0 on DuckDB 1.5.x during migration | — | **UNRESOLVED** | v4.1 has no owner, phase, or workstream for the flock v0.4.0 release line. |
| **DR-PO-4** Special-repo phase numbered sequentially between static-wheel phases though it is parallel and has no pg-agent consumer | Phase 1 / Phase 7; same as **C4** | **ABSORBED** | No special-repository phase. Phase 7 is production migration/cutover, not repo publishing. |

### 4.3 Data model / API overreach (§5)

| Finding | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|
| **DR-DM-1** Document versioning over-committed | §3.5; same as **C3** | **UNRESOLVED** | See C3. |
| **DR-DM-2** Filter AST **operator list** frozen pre-Phase 0; keep mechanism, not the ten-operator inventory | §3.12 `use_rag_tool` | **ABSORBED** | v4.1 does not freeze a ten-operator JSON filter AST. Named-tool parameters have no filter-AST field. (No replacement metadata-filter mechanism is specified either; that was not C3-style “keep the mechanism.”) |
| **DR-DM-3** Uniform 13-column projection with always-NULL scores | §3.8; same as **C10** | **ABSORBED** | See C10. |
| **DR-DM-4** `DOUBLE[]` embedding storage | §3.2/§3.5; same as **C7** | **PARTIAL** | See C7. |
| **DR-DM-5** BM25 “conditional” but schema already reserves `lexical_terms` / `lexical_stats` | §3.5; §3.8 BM25 | **ABSORBED** | v4.1 does not reserve `lexical_terms`/`lexical_stats`. BM25 is a Phase 3 index + tokenizer/config hash in `rag_index_manifest`; FTS reuse vs Flock-owned BM25 is an explicit either/or, not dead tables in v1 schema. |

### 4.4 Security, concurrency, rollback, tests (§6)

| Finding | v4.1 section | Status | How v4.1 addresses it |
|---|---|---|---|
| **DR-SEC-1** `.well-known` metadata fetch: no TLS/CA, size cap, timeout | §3.15 | **ABSORBED** | Finding applies to special-repository bootstrap. v4.1 first period has no special-repo client path: no runtime network extension download, no `INSTALL`/`LOAD`. |
| **DR-SEC-2** No OS permissions for `~/.duckdb/extension_repositories/` trust-anchor files | §3.3 IPC `0600`; §3.15 | **ABSORBED** | Special-repo JSON trust anchors are not a v4.1 mechanism. Owner socket dir is operator-created, owner-user only, socket `0600`. |
| **DR-SEC-3** No artifact revocation | §3.2/§5.9; same as **C6** | **PARTIAL** | See C6. |
| **DR-SEC-4** Error redaction should include **provider response bodies** (may echo payloads) | §3.12 Error taxonomy | **PARTIAL** | Redaction list: “credential、DSN、绝对路径、token、prompt截断和脱敏”; “不原样透传 DuckDB/HTTP exception.” Provider **response bodies** are not named on the redaction list. |
| **DR-CON-1** Single-writer file model | §3.3; same as **C2** / **F-1** | **ABSORBED** | See F-1 / C2. |
| **DR-CON-2** `BUILDING → READY` catalog pointer swap needs read-consistency / snapshot guarantee (one statement or equivalent test) | §3.3 Generation pin; §3.5 Revision activation; §3.14 并发门 | **ABSORBED** | Queries pin catalog/revision/index/lease at start; “已开始的 query 仍读取旧 revision”; GC skips in-flight pins; swap is “atomic active_revision swap.” Concurrency gate: writer index build or active swap concurrent with 8 queries; started queries keep the pinned generation. |
| **DR-RB-1** Importer is one-way; if P3 import corrupts, only rollback is delete schema — use a staging schema first | §3.5; §3.6; Phase 2 exit | **ABSORBED** | Importer writes a **BUILDING** revision with the same activation rules as MinerU: required-backend failure does not activate; “旧 revision保持 active”; “ingestion failure不破坏旧active revision.” Not a separate `flock_rag` staging schema; BUILDING revision is the staging mechanism. |
| **DR-RB-2** Old flock opening a file already upgraded by vNext: “old flock ignores `flock_rag`” should be a stated, tested invariant | §3.2; §5.2; §5.9 | **ABSORBED** | Different mechanism than “ignore extra schema”: “DuckDB/Flock/tachiom ABI 或 catalog format 不匹配：拒绝打开 live store”; “禁止使用旧binary对新DuckDB文件执行in-place downgrade”; rollback uses matching old backup + old runtime. |
| **DR-T-1** Property/fuzz tests for filter AST | §3.12 (no filter AST) | **ABSORBED** | Subject removed with DR-DM-2. If a filter AST is added later, this test gap returns. |
| **DR-T-2** Importer test at **corpus scale** (goldens ≠ robustness on real volume) | Phase 2 fixtures; Phase 7 items 1–4 | **PARTIAL** | Phase 2: real MinerU/Kohaku/legacy **fixtures** round-trip. Phase 7: production legacy import dry-run + “对真实MinerU corpus执行ingestion/index.” No named corpus-scale / volume-robustness importer test distinct from fixtures and production cutover. |
| **DR-T-3** CI performance-regression gate: “record baselines” with no alert threshold | §3.14 性能门 | **ABSORBED** | Numeric gates: simple retrieval p95 ≤ Phase 0 same-host baseline `1.25x`; owner IPC extra p95 ≤ 20 ms and ≤ 20% of non-LLM retrieval; ingestion/index memory peak ≤ `1.5x` comparable baseline. |
| **DR-T-4** Automated check that omitted-key `CREATE EXTENSION REPOSITORY` (TOFU) is refused for pg-agent | §3.15 | **ABSORBED** | Special-repo TOFU path is not a v4.1 pg-agent runtime path (no `INSTALL`/`LOAD` / network extension download). |

---

## 5. Counts

| Source | IDs mapped | ABSORBED | PARTIAL | UNRESOLVED |
|---|---:|---:|---:|---:|
| Oracle v4 review F-* | 13 | 11 | 2 (F-9, F-12) | 0 |
| Design review C* | 10 | 6 | 3 (C5, C6, C7) | 1 (C3) |
| Design review DR-I-* | 4 | 4 | 0 | 0 |
| Design review other unique DR-* | 19 listed (several alias C*) | see table | DR-SEC-4, DR-T-2, DR-DM-4/C7, DR-SEC-3/C6 | C3/DR-DM-1, DR-PO-1, DR-PO-2, DR-PO-3 |
| Post-v4.1 plan amendments (§1.1) | 1 | 1 (F-14) | 0 | 0 |
| **Unique UNRESOLVED** | | | | **C3 / DR-DM-1, DR-PO-1, DR-PO-2, DR-PO-3** |

Unique PARTIAL (deduped): **F-9, F-12, C5, C6, C7, DR-SEC-4, DR-T-2**.

Machine-checkable mirror (status / unique counts / blocked gates): `v7/evidence/corrections_register.json`. Review bodies in §§1–4 are not edited. UNRESOLVED / PARTIAL remain open; they are not absorbed. Post-v4.1 amendments (§1.1) are not Oracle F-findings: `oracle_v4_F` stays mapped 13 / ABSORBED 11; F-14 mirrors in the register as ABSORBED with `blocked_phase: null` under `counts.post_v41_amendments`.

---

## 6. Docs freeze notes (WI-1)

| Doc | Banner / authority | WI-1 action |
|---|---|---|
| `docs/plans/flock-rag-on-duckdb-final-plan-v3.md` | First line: superseded by `flock-rag-on-duckdb-final-plan-v4.1.md`; “Do not use it for implementation.” | Confirmed; not duplicated. Inner “权威性声明” still describes v3 historically; top banner is the do-not-implement signal. |
| `docs/plans/flock-rag-on-duckdb-v7-final-plan-v4.md` | First line: “This Oracle v4 draft is replaced by `flock-rag-on-duckdb-final-plan-v4.1.md`. Do not use it for implementation.” | Confirmed; not duplicated. Inner “本文：Oracle v4 权威开发计划” remains historical under the superseded banner. |
| `docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md` | Unique authoritative plan; header does **not** claim all review corrections are absorbed. Open items live in this file and `v7/evidence/corrections_register.json`. | Header/§4.1 name the v4 draft, this map, and the JSON register. |
| Review files | v4.1: “不改review内容；只由v4.1链接” | Bodies unchanged. |
