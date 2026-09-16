# pg-agent v7 — Phase 0 (waived) + Phase 1 runtime

This directory is the start of the additive v7 Flock RAG work. It is **not** an owner service.

Authority: [`docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md`](../docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md) (Oracle v4.1). Phase 0 freezes evidence, four-repo provenance, and contracts. **Phase 0 has not passed.** On 2026-08-30 it was marked `passed_with_user_waiver`; unresolved Phase 0 Oracle P0/P1 and missing external evidence remain recorded as waived/open, not fixed.

Phase 1 (target DuckDB/Flock Python static runtime) has a local implementation: Flock pin `a1f0ab191185c0852b162adc6feb206822dc9daa` / `duckdb-special-20260829-g1`, `flock_rag_health()`, static FTS, **tachiom blocked** (`RAG_MULTI_VECTOR_UNAVAILABLE`), separate v7 wheel. Do not enter Phase 2.

Open review corrections (not all absorbed): [`docs/plans/flock-rag-v4.1-review-correction-traceability.md`](../docs/plans/flock-rag-v4.1-review-correction-traceability.md) and [`evidence/corrections_register.json`](evidence/corrections_register.json). Unique UNRESOLVED: C3 / DR-DM-1, DR-PO-1, DR-PO-2, DR-PO-3. Unique PARTIAL: F-9, F-12, C5, C6, C7, DR-SEC-4, DR-T-2.

The v6 DuckDB pin in the repo-root `pyproject.toml` (`duckdb==1.6.0.dev366+ga1f0ab1911`) must not be changed to a v7 wheel in-place.

| v7 artifact | SHA-256 |
|---|---|
| `../duckdb-python-pgagent/dist-v7/duckdb-1.6.0.dev366-cp312-cp312-macosx_26_0_arm64.whl` | `d4e8fd28e6c6daa22dba349ed253b45b7a9f01e110126f65dc79a126308ba5ff` |
| v6 `dist-special-g1/duckdb-1.6.0.dev366+ga1f0ab1911-...whl` (do not reuse) | `fa4ba6fb193e98d9273d494d1255393a4df33b8d6890fbbcdd65b064b3c15ad9` |

Phase 1 runtime tests (v7 wheel, not the v6 pin): `HOME=... /path/to/v7-venv/bin/python v7/tests/test_phase1_runtime.py`. tachiom is absent; flock and fts are `STATICALLY_LINKED`. Health row `fts=unknown` is the Flock compile flag default; `duckdb_extensions()` is the link authority. E2 record: [`evidence/phase1_runtime.e2.md`](evidence/phase1_runtime.e2.md).

## Phase 0 deliverables

| Path | Role | Status an operator must not misread |
|---|---|---|
| `VERSION_MANIFEST.json` | Every plan §3.2 field; unknowns are `null` + sibling status/notes | Incomplete. Nested lock copies may be `partial`. `release_gate.would_pass` / `release_ready` are **false**. |
| `gates/phase0_evaluator.py` | Canonical Phase 0 evaluator | Exact `phase0_pass` / `blocker_ids` / `blocker_classes` / structured reasons. |
| `gates/release_evaluator.py` | Distinct final release evaluator | Requires Phase 0 **and** Phase 1–7 **and** E3. Not equal to `phase0_pass` by construction. |
| `constraints-macos-arm64.txt` | macOS arm64 pins / known build commands | Pins only; not a green build. |
| `evidence/four_repo_provenance.json` | Four-repo commit/branch/dirty/tag/build_entry | Recorded. pg-agent dirty. Flock duckdb submodule floating/uninitialized. |
| `evidence/corrections_register.json` | Machine-checkable ABSORBED/PARTIAL/UNRESOLVED | Open items remain. Not all corrections absorbed. |
| `evidence/phase0_baseline_status.json` | Live/fixture/runtime booleans | Four of six required items still missing live/acceptance evidence. `kohaku_tree_fixtures` and `kohaku_mineru_range_trio` have E2 generated/imported fixtures (`live_runtime_missing` still true; not a live Kohaku service or live MinerU parse). Live MinerU / live legacy / live mdenseon / target tachiom stay missing with implementation_allowed / release_allowed false. |
| `evidence/contracts/EVIDENCE_REGISTER.json` | Contract index | Mix of E0/E1/E2. **E3** is defined (cross-repository integration/acceptance on the frozen four-repo pins) and is **not** a Phase 0 claim. Read `backend_blocked` and exact-DTO flags. |
| `evidence/contracts/mineru.md` | MinerU JSON node/page/bbox | **E1** JSON ingest. OCI container digest **N/A**. **E0** live MinerU runtime (wheelhouse/venv/187-file snapshot bytes still absent). |
| `evidence/contracts/kohakurag.md` | Kohaku NodeKind / tree types | **E1** types. **E2** generated Kohaku-native tree fixtures (`v7/tests/fixtures/kohaku/`). Tree ingest acceptance unblocked for those fixtures. MinerU→Kohaku mapping still E0. |
| `evidence/contracts/line_range_mapping.md` | `range_origin` rules | **E1** rules. **E2** origin-shape range-trio fixtures (`v7/tests/fixtures/range_trio/`; `live_runtime_missing` still true; not live parse). |
| `evidence/contracts/mdenseon.md` | Dense encoder lock fields | **E1** lock. **E0** live weights/tokenizer bytes. Dense backend **blocked**. |
| `evidence/contracts/tachiom.md` | Multi-vector SQL/envelope | **E1** SQL. Build identity is Cargo-resolved tachiom `v0.3.4` (`2d1b2050…`), not local checkout HEAD. **E0** target-fork static artifact. Multi-vector **blocked**. |
| `evidence/contracts/auto_coder_longcontext.md` | LongContext defaults | **E1** source. QA tokenizer hash still **E0**. |
| `evidence/contracts/infinisynapse_schema.md` + `.json` | Schema RAG | Workflow semantics **E1 allowed**. Exact tool DTO **E0 blocked** (obfuscated handlers; missing original JSON). |
| `evidence/contracts/owner_live_file.md` | Owner-only live file | **E1** Phase 0 contract. Phase 1 E2 on v7 wheel (`evidence/phase1_runtime.e2.md`): same-process readers + non-owner open fails. |
| `evidence/contracts/temp_candidate_stage.md` | TEMP candidate stage | **E1** Phase 0 contract. Phase 1 E2 connection-local TEMP on v7 wheel. Ranking remains Phase 3. |
| `evidence/phase1_runtime.e2.md` + `.json` + `.log` | Phase 1 runtime | **E2** on v7 wheel (health, NEAREST, WHOLE_ARCHIVE symbols, reader guard, non-owner lock). tachiom still blocked. Not E3. |
| `evidence/legacy_cache_live_path.md` | Live auto-coder cache hunt | **E0** — live `byzerai_store_duckdb.db` missing. |
| `migration/legacy_cache_probe.py` + `tests/test_legacy_cache_probe.py` | Read-only probe | Probe vs **synthetic** fixture is E2 of the probe machinery. Synthetic is **not** a live golden baseline. |
| `tests/fixtures/legacy_cache/golden.v1.json` | Synthetic schema fixture | Labeled `synthetic_from_source_schema`. Not live corpus. |
| `migration/kohaku_tree_fixture.py` + `tests/test_kohaku_tree_fixture.py` + `tests/fixtures/kohaku/` | Kohaku tree fixtures | **E2** `generated_from_kohaku_source` at Kohaku pin `f3d27c8d…`. Not a live Kohaku service. Not MinerU→Kohaku. |
| `evidence/kohaku_tree_fixtures.md` | Fixture freeze note | Command + what is not claimed. |
| `evidence/nearest_e2_summary.md` + `nearest_e2.json` + `nearest_basic.e2.log` | target NEAREST | Historical freeze **E2** unittest exit 0 (112 assertions) at duckdb-pgagent `a1f0ab191185…` / tag `duckdb-special-20260829-g1`. Binary SHA-256 recorded. Live gate reports E2 only if the in-repo log and target unittest binary verify; otherwise **blocked**. Not E3. |
| `tests/test_version_manifest.py` | Phase 0 manifest/gates | Run: `uv run python v7/tests/test_version_manifest.py` |

## Blocked / synthetic / E1 / E2 / missing (short)

| Item | Level | Implementation | Release |
|---|---|---|---|
| Live legacy cache | E0 missing | blocked | blocked |
| Kohaku tree fixtures | E2 generated_from_kohaku_source (types E1) | acceptance allowed for these fixtures | still blocked overall |
| Kohaku/MinerU/legacy range trio | E2 fixtures origin-shape (`live_runtime_missing` still true; not live parse) | acceptance allowed for these fixtures | still blocked overall |
| Live MinerU runtime | E0 missing (JSON E1) | live parse blocked | blocked |
| Live mdenseon bytes | E0 missing (lock E1) | dense blocked | blocked |
| Target tachiom static artifact | E0 missing (SQL E1) | multi-vector blocked | blocked |
| Infinisynapse workflow | E1 | workflow mapping allowed | blocked (overall) |
| Infinisynapse exact DTO | E0 | blocked | blocked |
| NEAREST on duckdb-pgagent | historical E2; live E2 requires binary+log else blocked | n/a (engine already in fork) | does not make Phase 0 pass; not E3 |
| Synthetic legacy golden | synthetic / not live | must not be treated as live E2 | blocked |
| v7 wheel | E2 recorded (`phase1_runtime.e2.md`) | Phase 1 runtime allowed | still blocked overall |
| Flock ABI catalog version / BM25 config hash | missing | blocked | blocked |
| MinerU container digest | N/A (`null` + `not_applicable`; not an OCI runtime) | n/a (identity is wheel+snapshot) | does not block identity; live parse still blocked |

`phase0_pass` in `evidence/phase0_baseline_status.json` is **false**; it is derived by the canonical Phase 0 evaluator (`gates/phase0_evaluator.py`) from modeled blocker IDs/classes/structured reasons (manifest contract, backend blockers, missing baselines, open corrections, required null hashes, configuration gaps, dirty/uninitialized dependencies, and live NEAREST verification). `VERSION_MANIFEST.json` `release_gate.would_pass` is **false**; it is derived by the distinct final release evaluator (`gates/release_evaluator.py`) and remains false until Phase 1–7 and E3 pass. They are not equal by construction. **E3** (cross-repository integration/acceptance on the frozen four-repo pins) is not claimed in Phase 0.
