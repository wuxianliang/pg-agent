# Plan Review: Flock RAG on DuckDB special repo

- **Reviewed artifact**: `prompt-exports/oracle-plan-2026-08-29-141649-flock-rag-on-duckdb-3525.md` (Oracle plan, ~2,900 lines)
- **Reviewer**: design agent (independent critique, planning-only — no code changed)
- **Date**: 2026-08-29
- **Scope**: (1) nine-dimension gap matrix completeness, (2) DuckDB 2.0 PEG / special repository / static-Python assumptions, (3) phase ordering and dependency risks, (4) data-model / index / API overreach, (5) security, concurrency, rollback, test gaps, (6) corrections ranked by severity.

---

## 1. Verification of load-bearing claims

I re-checked the plan's factual backbone against the three loaded repos. Overall the plan's evidence discipline is good — most claims trace to real code.

### Confirmed accurate

| Plan claim | Verification |
|---|---|
| flock uses old-style `ParserExtension` (`duck_parse`/`duck_plan`/`duck_bind`) + `OperatorExtension::Register` | `flock/src/flock_extension.cpp:18-22`, `flock/src/include/flock_extension.hpp:16-58` ✓ |
| `CREATE/DROP EXTENSION REPOSITORY`, `INSTALL ... FROM/VERSION`, `USING PUBLIC KEY(S)` grammar | `duckdb/src/parser/peg/grammar/statements/load.gram` ✓ (tokens are quoted literals, e.g. `'CREATE' OrReplace? 'EXTENSION' 'REPOSITORY'`) |
| Repo files `~/.duckdb/extension_repositories/*.duckdb_extension.repo.json`, format v1, key pin from `prefix + .well-known/duckdb-extension-repo.json` when key omitted | `extension_repository_manager.hpp:28-35` (`FILE_EXTENSION`, `METADATA_FILE`), `extension_repository_manager.cpp:131,394` (pinning comments) ✓ |
| `allow_extension_repositories` undecided→allowed/forbidden one-way ratchet | `custom_settings.cpp:177`, `ParseAccess` in `extension_repository_manager.cpp:201-229` ✓ |
| Repo filename `.duckdb_extension.` segment covered by write protection | `opener_file_system.cpp:19` / `opener_file_system.hpp:40` ✓ |
| RSA-2048 public-key format | `extension_repository_manager.cpp:78` `IsValidRSA2048PublicKey` ✓ |
| `duckdb_extension_repositories()` columns (name, prefix, type, key_fingerprints, public_keys) | `duckdb_extension_repositories.cpp:20-32` ✓ |
| `llm_rerank` sliding window, `flock_row_id` injection/validation, token-limit retry shrinking batch | `llm_rerank/implementation.cpp:86` (`SlidingWindow`), `:27-71` (ID validation), `:222` (`batch_size *= 0.9`) ✓ |
| `llm_embedding` emits `LIST` result, no persistence | `llm_embedding/implementation.cpp:101` ✓ |
| `Config::db` is a static global; `flock_storage` ATTACH with `(READ_ONLY)` + RAII `StorageAttachmentGuard` | `core/config/config.cpp:10,82,121-122,129-166` ✓ |
| `Model::GetModelDetailsAsJson()` serializes `secret` | `model_manager/model.cpp:294` (`result["secret"] = ...`) ✓ |
| v6 worker: `autoinstall/autoload=false`, `enable_external_access=false`, memory limit | `pg-agent/v6/session_durability/duckdb_runtime.py:141-144` ✓ |
| PGMQ `duck_heavy_requests` enqueue-only tools | `v6/duck_tools/duck_tools.sql:29` ✓ |
| v6 validator rejects non-SELECT via `extract_statements` | `v6/dialect_guardrails/duckdb_validation.py:68-78` ✓ |
| Wheel `1.6.0.dev365` = engine `v2.0.0-alpha38615`; `CREATE EXTENSION REPOSITORY` → `ParserException` on that wheel | `pg-agent/docs/analysis/_wip-v6-duckdb20.md:17-21,91` ✓ |
| vss patch still present upstream (vector index unsettled) | `duckdb/.github/patches/extensions/vss/` exists ✓ |

### Inaccuracies found

1. **"PEG parser override is a hard migration blocker; old `ParserExtension` cannot be the final implementation"** — overstated. In upstream `duckdb/src/parser/parser.cpp:277-290` the 2.0 PEG parser explicitly hands per-statement PEG failures to legacy `parse_function` extensions ("On per-statement PEG failure, hand the rest of the query to parse_function extensions"). Separately, `parser_override` is a *field on the same `ParserExtension` class* (`parser_extension.hpp:167`), invoked only when `allow_parser_override_extension` is FALLBACK/STRICT (`parser.cpp:252-273`) and **skipped entirely in DEFAULT mode** (`parser.cpp:255-257`). So flock's existing `parse_function` path plausibly keeps working on 2.0 without any override registration; the migration is a design choice (cleaner semantics, non-default-mode availability), not a hard requirement. The plan also claims the callback signature is unknowable until Phase 1 reads the target fork ("当前选定文件没有提供准确 C++ callback 声明") — wrong: the exact typedef is already in the loaded tree at `parser_extension.hpp:150` (`ParserOverrideResult (*)(ParserExtensionInfo*, const string&, ParserOptions&)`).
2. **Enum names**: plan writes `AllowParserOverride` DEFAULT/FALLBACK/STRICT; actual values are `DEFAULT_OVERRIDE`/`FALLBACK_OVERRIDE`/`STRICT_OVERRIDE` (`allow_parser_override.hpp:15`). Trivial but the plan elsewhere demands file-accurate citations.
3. **Mis-cited files**: plan attributes the FALLBACK/STRICT gating to `parse_iterator.cpp`; it is in `src/parser/parser.cpp`. The `allow_parser_override_extension` setting lives in `settings.hpp:201` / `autogenerated_settings.cpp:42`, not `custom_settings.cpp` as implied.
4. **"flock pinned DuckDB v1.5.4 submodule"**: `flock/.gitmodules` tracks `branch = main` for both `duckdb` and `extension-ci-tools`; the v1.5.4 pin exists only in `MainDistributionPipeline.yml:28-39`. The submodule pin claim is wrong, and it matters: an unpinned `main` submodule means flock's local build ABI is already drifting, which slightly *strengthens* the plan's case for a manifest-locked target fork but weakens its "current state" description.

---

## 2. Gap matrix (nine dimensions)

**Complete as specified**: all nine user-mandated dimensions are rows, auto-coder cells are honestly marked 待 Phase 0, and the "DuckDB 2.0 原生" column stays within verifiable claims. Two nits:

- The 重排 (rerank) row's auto-coder cell ("需确认是否 LLM/cross-encoder…") lacks the bold 待 Phase 0 marker used in the other eight rows — inconsistent unknowns-flagging in exactly the dimension where the plan later hardcodes sliding-window semantics.
- The matrix has no column for **verification method** per row, even though the plan elsewhere demands every claim carry one. The 验证策略 section covers this globally, but per-row traceability (which Phase-0 artifact closes which cell) would make the matrix self-auditing.
- Minor omission: credential/secret lifecycle is a cross-cutting RAG concern (embedding model keys rotate; persisted `embedding_secret_name` must stay resolvable) and fits none of the nine rows cleanly. Worth an explicit note under 数据模型.

## 3. DuckDB 2.0 assumptions

- **Special-repository mechanism**: sound and verified against upstream main (§1). The TOFU-avoidance argument (always bootstrap with explicit `USING PUBLIC KEY`) is correct given the pin-on-create behavior at `extension_repository_manager.cpp:394`.
- **PEG parser assumption**: partially unsound — see Correction C1. The plan builds Phase 2 around a "hard" parser migration and forbids dual parser paths, but upstream code shows (a) legacy `parse_function` is still consulted on PEG failure, and (b) `parser_override` is inactive in DEFAULT mode. The real decision is subtler: if flock wants `CREATE MODEL` to work for users who never touch `allow_parser_override_extension`, the legacy `parse_function` path is precisely the DEFAULT-mode mechanism, so "禁止旧 parser" would *remove* DEFAULT-mode functionality. The plan needs to either (i) keep `parse_function` as the DEFAULT-mode path and document that `parser_override` is only for FALLBACK/STRICT users, or (ii) accept that flock syntax requires a non-default setting and say so in the README.
- **Static-Python assumption**: directionally right (locked v6 worker can't `INSTALL`/`LOAD` at runtime — verified), and the plan correctly refuses to assume `duckdb_loader.cmake` target names in the unloaded fork. But it underweights one fact it itself verified: the pinned wheel `1.6.0.dev365` **lacks the special-repository grammar entirely** (`ParserException` at `EXTENSION`, `_wip-v6-duckdb20.md:91`). So for pg-agent's actual runtime, the special-repo track is irrelevant today; the dependency graph (§5) presents dynamic and static as peer paths when only the static path can ship first. This also means Phase 7 (special repo publishing) has **no consumer inside pg-agent** until the wheel is rebased — it serves only external DuckDB clients, which should be stated explicitly.

## 4. Phase ordering and dependency risks

Ordering (0 → 1 → 2 → …) is sensible and the "first three phases are unskippable" framing is right. Risks:

- **P0 has no fallback.** Exit criteria require *running* the old auto-coder RAG to produce golden output. If auto-coder 3.0.74's dependency environment can't be stood up, everything downstream blocks on "goldens". The plan logs unrunnable modules as blockers but offers no degraded mode (e.g., deriving goldens from auto-coder's own test fixtures/docs, or freezing contract from source reading alone with parity tests deferred). Add an explicit P0-degraded path.
- **P1 forks the critical path twice**: building the DuckDB fork *and* producing a signed test artifact *and* validating the static loader are sequential gates before flock can even compile against 2.0. No timeboxing or "P1-lite" (headers/diff only) interim exit is defined; a single fork build failure stalls all RAG work even though RAG schema/chunking design (P3) is largely ABI-independent and could proceed against upstream main in parallel.
- **P2 atomicity demand is load-bearing but unresourced**: "parser、CMake、CI 和 ABI 变更必须原子落地" is correct, yet there is no named rollback strategy for a half-merged P2 (feature flag? branch-long-lived?). Given Correction C1 (legacy parse path still functional), P2 could be de-risked into two landings — ABI/build first, parser second.
- **Missing workstream**: maintaining/patching the flock v0.4.0 release line during migration is mentioned only as a rollback note (§6.7) with no owner or phase. If migration slips, v0.4.0 on DuckDB 1.5.x still needs security/bugfix releases.
- **P9 depends on P8 (static wheel), P8 on P1 fork contracts — but P7 (special repo) depends on nothing in P8/P9.** Fine, but then P7 should not sit between P6 and P8 in a numbered narrative that reads as sequential; make the parallelism explicit.

## 5. Data model / index / API overreach

- **Document versioning is over-committed.** Immutable `document_version` + `is_current` flip + per-version chunk/embedding rows is a strong design decision taken *before* Phase 0 establishes auto-coder's actual update semantics. If auto-coder overwrites in place (common for simple RAG stores), this doubles storage and complicates every write path for zero parity benefit. It is presented as 设计决定 ("工程师不应重新选择") — that label should be conditional on Phase 0 evidence. **Downgrade to conditional.**
- **Filter AST operator list frozen pre-Phase-0.** Ten operators with allowlisted fields is a reasonable security posture, but fixing the set now risks both over-fit (operators auto-coder never had) and under-fit (e.g., `exists`, array contains, prefix match). Keep the *mechanism* (JSON → AST → parameterized expression) as the decision; keep the operator inventory as Phase-0 output.
- **Uniform result projection is an API smell.** `flock_rag_search_vector` returns `lexical_score`, `fused_score`, `rerank_score` columns that are always NULL for pure vector search. Consistency aids the hybrid orchestrator, but users of the vector API pay for a 13-column row with 3-4 permanently NULL fields. Prefer per-API projections with a shared core, or document the NULL contract explicitly.
- **`DOUBLE[]` embedding storage**: embeddings are FP32 from every provider flock supports; `DOUBLE[]` doubles the largest table's footprint and I/O for the exact-scan baseline that the plan itself calls the correctness path. Consider `FLOAT[]` (or justify DOUBLE) — the plan's own performance-baseline section would immediately surface this.
- **BM25 scope is correctly conditional** ("若 Phase 0 golden contract 要求") — good; but the 8-table schema already reserves `lexical_terms`/`lexical_stats`, so "conditional" should apply to the schema too, else v1 ships dead tables.
- Not overreach: refusing opaque index blobs, gating VSS, exact-backend-first, and refusing silent ANN fallback are all well-judged.

## 6. Security, concurrency, rollback, tests

**Security** — strong overall (explicit key pinning, no-TOFU bootstrap, secret-redaction boundary, parameterized filters, payload hygiene). Gaps:

- The `.well-known` metadata fetch path (used for rotation/bootstrap when key omitted) has no stated transport requirements beyond "HTTPS prefix": no TLS version/CAD requirements, no size cap on the metadata or artifact downloads, no timeout. A malicious or compromised prefix could serve unbounded artifacts.
- No statement about `~/.duckdb/extension_repositories/` file permissions — the repo JSON is write-protected via DuckDB's opener FS, but nothing about OS-level perms on a trust-anchor file.
- **No artifact revocation story.** If a correctly-signed but bad flock artifact ships, key rotation does not recall it (installed clients keep it; DuckDB has no revocation list). The plan needs a version-blocklist / minimum-version recommendation in the bootstrap docs at minimum.
- Error-redaction list (DSN/secret/Authorization) is good; add provider *response* bodies, which can echo request payloads.

**Concurrency** — the per-`DatabaseInstance` ownership and mutex-keyed cache design is sound, but:

- **The plan never addresses DuckDB's single-writer file model.** The RAG catalog is a persistent DuckDB *file*; concurrent upserts from two processes (or even two pg-agent workers pointed at the same file) are not just "transaction conflicts" — DuckDB does not support multi-process write access to one file at all. §3.15 says the RAG worker uses "a configured persistent DuckDB file" but never states the single-writer/single-owner constraint or what happens if two workers race the file lock. This is the largest concurrency hole.
- Cross-connection upsert of the same `external_id` is handled by unique-constraint conflict, good; but `BUILDING → READY` index swap "原子切换 catalog pointer" needs a statement about read-consistency: DuckDB MVCC gives snapshot isolation, so a long search may read a half-swapped catalog unless the swap is one statement — worth an explicit test (§9.4 lists rebuild/search concurrency, OK, but the exit criteria don't name the snapshot guarantee).

**Rollback** — schema-migration additive + no-downgrade + catalog FAILED/STALE marking is reasonable. Two gaps: (a) the importer is one-way; if P3's import corrupts data, the only rollback is "delete `flock_rag` schema" — say so explicitly and make the importer write to a staging schema first; (b) §6.7 says rollback to old flock means switching release lines, but doesn't address a *database file already upgraded by vNext* being opened by old flock — old flock ignores `flock_rag`, fine, but that should be a stated, tested invariant, not an implication.

**Tests** — §9 is thorough (goldens, mock-provider rerank determinism, persistence/reopen matrix, tamper/wrong-key). Missing:

- Property/fuzz tests for the filter AST (arbitrary JSON → never panics, never produces unparameterized SQL).
- Importer test at corpus scale (golden corpus proves parity, not robustness on auto-coder's real data volume).
- A CI performance-regression gate — §9.5 says "record baselines" but defines no alert threshold, so regressions will be recorded and ignored.
- No test that *omitted-key* `CREATE EXTENSION REPOSITORY` (TOFU path) is refused by pg-agent-facing docs/scripts — the plan relies on discipline, not an automated check.

## 7. Corrections ranked by severity

| # | Severity | Correction |
|---|---|---|
| C1 | **High** | The parser migration is not a hard blocker and the override signature is already known. Upstream `parser.cpp:277-290` still dispatches PEG-failed statements to legacy `parse_function`; `parser_override` is a `ParserExtension` field (`parser_extension.hpp:150,167`) gated by `allow_parser_override_extension` and skipped in DEFAULT mode (`parser.cpp:255-257`). Rewrite §3.12: keep `parse_function` as the DEFAULT-mode path (or explicitly require the setting), drop the claim that the callback signature awaits Phase-1 discovery, and re-scope Phase 2's "atomic" demand accordingly. |
| C2 | **High** | Single-writer DuckDB file constraint for the RAG catalog is unaddressed. State explicitly in §3.11/§3.15 that `flock_rag` lives in a file with exactly one writing process, define multi-worker behavior (queue-serialized writer or per-worker DBs), and add a two-process contention test. |
| C3 | **High** | Document versioning is a pre-Phase-0 over-commitment. Reclassify §3.3's immutable-version model from 设计决定 to "conditional on Phase 0 update-semantics findings"; provide the simpler overwrite-in-place variant as the fallback. |
| C4 | **Medium** | The pinned pg-agent wheel lacks the special-repo grammar entirely (`_wip-v6-duckdb20.md:91`). Say plainly that Phase 7 serves external clients only and that pg-agent's only near-term distribution is the static wheel; adjust the §5 dependency graph so the dynamic path is not a peer dependency of the pg-agent integration. |
| C5 | **Medium** | Phase 0 needs a degraded mode: if auto-coder can't be executed, freeze the contract from source + auto-coder's own fixtures and defer runtime goldens, rather than blocking P1–P3 wholesale. |
| C6 | **Medium** | Artifact revocation: add a minimum-version/blocklist recommendation to bootstrap docs and a "bad signed artifact" drill to §6.2/§9.1; key rotation alone cannot recall a signed bad release. |
| C7 | **Medium** | Embedding storage type: use `FLOAT[]` (or justify `DOUBLE[]`) before §3.3 becomes a migration-locked schema; this is the largest table in the system. |
| C8 | **Low** | Fix factual slips: `AllowParserOverride` values are `*_OVERRIDE` (`allow_parser_override.hpp:15`); gating lives in `parser.cpp`, not `parse_iterator.cpp`; the setting lives in `settings.hpp`/`autogenerated_settings.cpp`; flock's `.gitmodules` tracks `main`, the v1.5.4 pin is CI-only (`MainDistributionPipeline.yml:28-39`). |
| C9 | **Low** | Rerank row of the gap matrix: add the missing 待 Phase 0 marker; add a per-row "closed by" verification column. |
| C10 | **Low** | Per-API result projections (drop always-NULL score columns from `flock_rag_search_vector`), or document the NULL contract. |

## 8. Overall assessment

The plan is unusually well-evidenced for its size: its separation of 已验证事实 / 待 Phase 0 / 设计决定 mostly holds up under re-verification, the special-repository mechanism description is accurate, and the refusal to bet on VSS/unfrozen APIs is the right call. The two structural problems are (a) the parser-migration framing, which misreads how the 2.0 PEG parser coexists with legacy `parse_function` extensions and invents a discovery dependency on the target fork for a signature already visible upstream (C1), and (b) lifecycle mismatches that survive the plan's own evidence: a multi-worker RAG catalog on a single-writer file (C2), and a distribution track (special repo) whose only intended consumer can't parse it (C4). Fix C1–C4 and the phase plan's core remains intact; the rest are tightenings, not rewrites.
