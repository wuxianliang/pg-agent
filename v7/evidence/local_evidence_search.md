# Local evidence hunt (Phase 0 P1-2 / WI-A)

**Written:** 2026-08-29  
**Work item:** WI-A (`prompt-exports/phase-0-orchestrate-checklist.md`)  
**Method:** targeted read-only `test` / `ls` / `find` / `mdfind` / `git rev-parse` / `shasum -a 256`. Did **not** walk all of `/Users/wxl`. Did **not** copy production cache/weights into git. Did **not** invent hashes. Did **not** re-run MinerU, mdenseon, or `nearest_basic.test`. Did **not** hash `duckdb-tachiom` 1.5.4 binaries as a v7 pin.

Authority for status encoding: plan §6 Phase 0 + checklist P1-2. Synthetic/E1 is **not** a Phase 0 pass. Affected backends stay blocked.

Evidence levels:

| Level | Meaning |
|---|---|
| E0 | unread / unknown / missing — cannot implement against |
| E1 | source / tests / static contract inspected |
| E2 | ran on target runtime / fixture this freeze (command + exit) |

---

## Commands run (this session)

Exit 0 with empty stdout still means “command succeeded,” not “artifact found.” `test` exit 1 = path missing.

| ID | Command | Exit | Result |
|---|---|---:|---|
| 01 | `test -d /Users/wxl/Projects` | 0 | present |
| 02 | `test -d /Users/wxl/.auto-coder` | 0 | present |
| 03 | `test -d /Users/wxl/.cache` | 0 | present |
| 04 | `test -d /Users/wxl/.grok` | 0 | present |
| 05 | `find /Users/wxl/Projects /Users/wxl/.auto-coder /Users/wxl/.cache /Users/wxl/.grok \( -name byzerai_store_duckdb.db -o -name byzerai_store_duckdb.db.wal \)` | 0 | **empty** (no stdout; stderr 0 lines) |
| 06 | `mdfind -onlyin /Users/wxl/Projects 'byzerai_store_duckdb.db'` | 0 | source/docs hits only (see below); no `.db` / `.wal` |
| 07 | `mdfind -onlyin /Users/wxl/.auto-coder 'byzerai_store_duckdb.db'` | 0 | empty |
| 08 | `mdfind -onlyin /Users/wxl/.cache 'byzerai_store_duckdb.db'` | 0 | empty |
| 09 | `mdfind -onlyin /Users/wxl/.grok 'byzerai_store_duckdb.db'` | 0 | empty |
| 10 | Python read `v7/tests/fixtures/legacy_cache/golden.v1.json` `metadata.corpus_kind` | 0 | `synthetic_from_source_schema` |
| 11 | `test -f v7/tests/fixtures/legacy_cache/golden.v1.json` | 0 | present |
| 12 | `ls v7/tests/fixtures/legacy_cache/` | 0 | `golden.v1.json`, `query_vector.4d.json`, `sidecar.marker` |
| 20 | `test -d /Users/wxl/Projects/rag/KohakuRAG` | 0 | present |
| 21 | `git -C /Users/wxl/Projects/rag/KohakuRAG rev-parse HEAD` | 0 | `f3d27c8d24616b75508795766355632640979e5b` |
| 22 | `git -C …/rag/KohakuRAG rev-parse --abbrev-ref HEAD` | 0 | `main` |
| 23 | `git -C …/rag/KohakuRAG status --porcelain=v1` | 0 | untracked `docs/investigations/` only |
| 24 | `test -d /Users/wxl/Projects/bookohakurag` | 0 | present |
| 25 | `git -C /Users/wxl/Projects/bookohakurag rev-parse HEAD` | **128** | **not a git repository** |
| 26 | `git -C /Users/wxl/Projects/bookohakurag rev-parse --abbrev-ref HEAD` | **128** | same |
| 27 | `test -d /Users/wxl/Projects/bookohakurag/KohakuRAG` | 0 | present |
| 28 | `git -C /Users/wxl/Projects/bookohakurag/KohakuRAG rev-parse HEAD` | 0 | `f3d27c8d24616b75508795766355632640979e5b` |
| 29 | `git -C …/bookohakurag/KohakuRAG rev-parse --abbrev-ref HEAD` | 0 | `main` |
| 30 | `ls …/KohakuRAG/tests` and `…/fixtures` (both checkouts) | tests 0; fixtures **1** | tests = 3 `.py` + README; **no `fixtures/` directory** |
| 31 | `find` tree/json under Kohaku `tests/` + `fixtures/` | **1** | `fixtures:` No such file or directory |
| 32 | `find …/KohakuRAG/tests -maxdepth 3 -iname '*.json' -o -iname '*tree*'` | 0 | **empty** (no JSON / tree fixtures) |
| 40 | `test -f v7/evidence/contracts/mineru.md` | 0 | present |
| 41 | `test -f v7/evidence/contracts/EVIDENCE_REGISTER.json` | 0 | present |
| 42 | `test -d /Users/wxl/.cache/duckrag-wi1-phase3/models` | **1** | **missing** |
| 43 | `test -d /Users/wxl/.cache/duckrag-wi1-phase3` | **1** | **missing** |
| 44 | `ls /Users/wxl/.cache/duckrag-wi1-phase3` | **1** | No such file or directory |
| 45 | `test -f …/locks/mineru-3.4.4.lock.json` + JSON walk for container/image digest | 0 | lock present; **no** container/image/digest/docker/oci fields |
| 50–53 | `test` claimed mdenseon cache dir / `model.safetensors` / `tokenizer.json` / HF hub `models--lightonai--mDenseOn` | **1** | all **absent** |
| 55 | `test -f …/locks/mdenseon-a5fdb000.lock.json` | 0 | present |
| 56 | `test -f …/p16_mdenseon.py` | 0 | present |
| 57 | `test -f …/fixtures/p16-mdenseon.json` | 0 | present |
| 58 | `ls -la` lock + `p16_mdenseon.py` + fixture + `p16_worker.py` | 0 | all present |
| 60 | `git -C /Users/wxl/Projects/tachiom rev-parse HEAD` | 0 | `69f6f3dc2eef3b543983eb71227bb65590e498a8` |
| 61 | `git -C …/tachiom describe --tags --always --dirty` | 0 | `v0.3.4-2-g69f6f3d` |
| 62 | `git -C …/tachiom rev-parse v0.3.4^{commit}` | 0 | `2d1b2050d60eb28462f9d9c451c2fe7653cc4aa9` |
| 63 | `rg tachiom\|TusKANNy duckdb-tachiom/Cargo.lock` | 0 | resolved source line below |
| 64 | `rg TARGET_DUCKDB_VERSION duckdb-tachiom/Makefile` | 0 | `TARGET_DUCKDB_VERSION=v1.5.4` |
| 65 | `test -f …/duckdb-tachiom/build/release/duckdb_tachiom.duckdb_extension` | 0 | file exists; **not** a v7 pin (see item) |
| 66 | `git -C /Users/wxl/Projects/duckdb-tachiom rev-parse HEAD` | 0 | `5c91f3cb5c4091cb70735449e546446a09136a04` |
| 70 | `test -f /Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/unittest` | 0 | present |
| 71 | `shasum -a 256` that unittest | 0 | `2924bc6ce716b2363c218c28e4418ad57c7e800f735cf0bd4520baf7df8519b8` |
| 72 | `git -C /Users/wxl/Projects/duckdb-pgagent rev-parse HEAD` | 0 | `a1f0ab191185c0852b162adc6feb206822dc9daa` |
| 73 | `git -C …/duckdb-pgagent tag --points-at HEAD` | 0 | `duckdb-special-20260829-g1` |
| 74 | `git -C …/duckdb-pgagent describe --tags --always --dirty` | 0 | `duckdb-special-20260829-g1` |
| 75 | `ls -l` unittest | 0 | 11567456 bytes, mtime 2026-08-29 12:21 |
| 76 | `file` unittest | 0 | Mach-O 64-bit executable arm64 |
| 81 | `mdfind … \| awk` keep `*.db` / `*.wal` | 0 | **empty** |
| 82 | `test -d v7/tests/fixtures/{kohaku,range_trio,mineru}` | **1** | all missing; only `legacy_cache/` |
| 83 | `test -f …/fixtures/p19-mineru-offline.pdf` and p16/p19 evidence records | 0 | PDF 672 bytes present; records present (not re-run) |
| 85 | Python print MinerU/mdenseon lock identities | 0 | see items; MinerU `image_digest`/`container_image_digest` = `None` |
| 86 | Python extract `[[package]] name = "tachiom"` from Cargo.lock | 0 | git tag `v0.3.4` `#2d1b2050…` |
| 87 | `test -d /Users/wxl/Projects/bookohakurag/.git` | **1** | no git root |

### CMD 06 mdfind hits (not a database)

All hits are source or docs mentioning the filename. Sample `file(1)` types: Python / UTF-8 markdown / text. No DuckDB file.

```
/Users/wxl/Projects/pg-agent/v7/migration/legacy_cache_probe.py
/Users/wxl/Projects/pg-agent/v7/evidence/legacy_cache_live_path.md
/Users/wxl/Projects/pg-agent/v7/tests/test_legacy_cache_probe.py
/Users/wxl/Projects/pg-agent/prompt-exports/oracle-review-2026-08-29-192243-untitled-chat-803791-3e89.md
/Users/wxl/Projects/pg-agent/docs/plans/flock-rag-on-duckdb-final-plan-v3.md
/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-08-29-161937-untitled-chat-f39d4d-dba3.md
/Users/wxl/Projects/pg-agent/docs/plans/flock-rag-on-duckdb-v7-final-plan-v4.md
/Users/wxl/Projects/pg-agent/docs/reviews/oracle-v4-plan-review-2026-08-29.md
/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-08-29-163811-untitled-chat-f39d4d-de73.md
/Users/wxl/Projects/pg-agent/prompt-exports/phase-0-orchestrate-checklist.md
/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-08-29-132636-auto-coder-rag-duckd-6483.md
/Users/wxl/Projects/pg-agent/prompt-exports/oracle-plan-2026-08-29-152517-flock-rag-on-duckdb-c695.md
/Users/wxl/Projects/auto_coder-3.0.74/src/autocoder/rag/cache/local_duckdb_storage_cache.py
/Users/wxl/Projects/rag/auto_coder-3.0.45/src/autocoder/rag/cache/local_duckdb_storage_cache.py
/Users/wxl/Projects/duckdb-web-main/prompt-exports/oracle-plan-2026-06-16-110325-duckdb-rag-plan-142c-a76b.md
/Users/wxl/Projects/duckdb-web-main/prompt-exports/duckdb-rag-v1-architecture-review-2026-06-16.md
/Users/wxl/Projects/docs/autocoderrag.txt
/Users/wxl/Projects/reporath/rag/cache/local_duckdb_storage_cache.py
```

---

## Item tables

### 1. `live_legacy_cache`

| Field | Value |
|---|---|
| found / missing | **missing** live `byzerai_store_duckdb.db` and `.wal` |
| identity | none for live bytes. Golden `v7/tests/fixtures/legacy_cache/golden.v1.json` `metadata.corpus_kind` = `synthetic_from_source_schema` only (`source_defaults.database_filename` = `byzerai_store_duckdb.db`) |
| E-level | **E0** live corpus/schema/rows/retrieval. Source defaults remain E1 in `auto_coder-3.0.74` (not re-derived here). Synthetic golden is **not** a live baseline |
| backend gated | `legacy_cache_live` (canonical importer / Phase 2 live import). Probe-vs-synthetic is a separate test path; it does not unblock live import |

Find of `byzerai_store_duckdb.db` / `.wal` under `/Users/wxl/Projects`, `/Users/wxl/.auto-coder`, `/Users/wxl/.cache`, `/Users/wxl/.grok` was empty. mdfind hits are source/docs, not a DB file.

Recommended booleans:

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | true | true | false | false |

---

### 2. `kohaku_tree_fixtures`

| Field | Value |
|---|---|
| found / missing | **source found**; **tree JSON fixtures missing** |
| identity | `/Users/wxl/Projects/rag/KohakuRAG` HEAD `f3d27c8d24616b75508795766355632640979e5b` `main`. `/Users/wxl/Projects/bookohakurag` exists but is **not** a git root (rev-parse exit 128). Nested `/Users/wxl/Projects/bookohakurag/KohakuRAG` HEAD **same** `f3d27c8d24616b75508795766355632640979e5b` `main` |
| E-level | **E1** NodeKind/types (see `v7/evidence/contracts/kohakurag.md`). **E0** golden tree JSON fixtures |
| backend gated | `kohaku_tree_acceptance`. Type vocabulary is frozen; tree-ingest **acceptance** is blocked |

`tests/` in both checkouts: `test_integration.py`, `test_jinav4.py`, `test_openrouter.py`, `README.md`. No `fixtures/` directory. No `*.json` under `tests/`. Plan §3.14 KohakuRAG document/tree fixtures: **unsatisfied as a file artifact**.

Recommended booleans:

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | true | true | false | false |

---

### 3. `kohaku_mineru_range_trio`

| Field | Value |
|---|---|
| found / missing | **missing** PDF / code / legacy golden trio |
| identity | none. Mapping rules live in `v7/evidence/contracts/line_range_mapping.md` (not re-executed). `v7/tests/fixtures/` has only `legacy_cache/` |
| E-level | **E1** `range_origin` rules. **E0** acceptance fixtures. Not E2 |
| backend gated | `range_trio_acceptance` |

Recommended booleans:

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | true | true | false | false |

---

### 4. `live_mineru_runtime`

| Field | Value |
|---|---|
| found / missing | JSON **contract** found (E1). **Live runtime missing**: container image digest **E0**; `/Users/wxl/.cache/duckrag-wi1-phase3/models` **missing** |
| identity | Wheel lock `…/locks/mineru-3.4.4.lock.json`: package `mineru` `3.4.4`, tag `mineru-3.4.4-released`, `tag_commit_sha` `0dfc9460cd9ab693b9af60ae3fbffd7bc111b062`, repo `https://github.com/opendatalab/MinerU`. Lock has **no** `image_digest` / `container_image_digest`. P19 PDF fixture present (672 bytes) at `…/fixtures/p19-mineru-offline.pdf` — harness fixture, **not** a live model/container pin. Prior `p19-s.json` is an inspected record, **not** re-run |
| E-level | **E1** JSON node types / page / bbox (`mineru.md`, `EVIDENCE_REGISTER.json`). **E0** container digest + live PDF-Extract-Kit snapshot this session |
| backend gated | `live_mineru_runtime` (live parse). JSON → tree parser contract is separate and remains E1; this hunt does not unblock live execution |

Register blockers cited, not re-hashed here: harness `MODEL_REVISION` `ed6b654c018d742e65a17671e379c5e6ecc87ec9`, `MODEL_MANIFEST_SHA256` `8c4a6a53815e2a8f410d71350128d0db1276579ac9f50cd1dee56b165e4a4df6` — **files not present** under the claimed cache, so those strings are lock/harness identity only.

Recommended booleans:

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | true | true | false | false |

---

### 5. `live_mdenseon`

| Field | Value |
|---|---|
| found / missing | **lock / script / invariant fixture found**. **Live** `model.safetensors` and `tokenizer.json` **absent** at claimed cache and HF hub cache |
| identity | Lock `/Users/wxl/Projects/repoprompt-ce-agno/benchmarks/duckrag_wi1/locks/mdenseon-a5fdb000.lock.json`: `model_id` `lightonai/mDenseOn`, `revision` `a5fdb000f7a21da96c3bddde3a782ef777316df3`. Also present: `p16_mdenseon.py`, `p16_worker.py`, `fixtures/p16-mdenseon.json`. Claimed live dir `/Users/wxl/.cache/duckrag-wi1-phase3/models/mdenseon-a5fdb000f7a21da96c3bddde3a782ef777316df3` **missing**. `/Users/wxl/.cache/huggingface/hub/models--lightonai--mDenseOn` **missing** |
| E-level | **E1** lock/harness/fixture. **E0** live weights. Not E2 (p16 not re-run). Do **not** treat lock `lfs_sha256` as a re-hash of files on disk |
| backend gated | `dense_mdenseon` |

Lock-stated LFS identities (copied from SOURCE lock; **not** computed from live bytes this session):

- `model.safetensors` lfs_sha256 `a336c49fc679aeb23969114b12fb7317804da3cc7d8bc214818009dea39d545c`
- `tokenizer.json` lfs_sha256 `a086e6a7efb90bbab8e379a63f3463fb13e6256ebec3343c1f1612cab693935b`

Recommended booleans:

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | true | true | false | false |

`p16-mdenseon.json` is an invariant schema fixture, not a live encode on this machine. It does not satisfy Phase 0 live dense acceptance.

---

### 6. `target_tachiom_static_artifact`

| Field | Value |
|---|---|
| found / missing | **source found**; **v7-compatible static/loadable artifact missing** |
| identity | Local checkout `/Users/wxl/Projects/tachiom` HEAD `69f6f3dc2eef3b543983eb71227bb65590e498a8` (`v0.3.4-2-g69f6f3d`). **Cargo-resolved** (not local HEAD): `git+https://github.com/TusKANNy/tachiom.git?tag=v0.3.4#2d1b2050d60eb28462f9d9c451c2fe7653cc4aa9`. Tag object confirmed via `git rev-parse v0.3.4^{commit}` = `2d1b2050d60eb28462f9d9c451c2fe7653cc4aa9`. `duckdb-tachiom` HEAD `5c91f3cb5c4091cb70735449e546446a09136a04`. Makefile `TARGET_DUCKDB_VERSION=v1.5.4` (`USE_UNSTABLE_C_API=1`) — **not** duckdb-pgagent `a1f0ab1911` |
| E-level | **E1** SQL names / envelope from source. **E0** artifact rebuilt+hashed for `a1f0ab1911` / `duckdb-special-20260829-g1` |
| backend gated | `multi_vector_tachiom` |

`build/release/duckdb_tachiom.duckdb_extension` exists on disk (`test -f` exit 0). It is a **v1.5.4 unstable C API** build, not a v7 target-fork artifact. **No v7-compatible artifact hash** is recorded. This session did **not** SHA-256 that 1.5.4 file (would be the wrong pin).

Recommended booleans:

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | true | true | false | false |

---

### 7. `nearest_basic` (present; not a P1-2 gap)

| Field | Value |
|---|---|
| found / missing | **found** |
| identity | Binary `/Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/unittest` SHA-256 `2924bc6ce716b2363c218c28e4418ad57c7e800f735cf0bd4520baf7df8519b8` (re-hashed this hunt; matches `v7/evidence/nearest_e2.json`). Size 11567456. Mach-O arm64. duckdb-pgagent HEAD `a1f0ab191185c0852b162adc6feb206822dc9daa`, tag `duckdb-special-20260829-g1` |
| E-level | **E2** already recorded (`nearest_e2.json` / `nearest_basic.e2.log`, unittest exit 0, 112 assertions). This hunt re-identified the binary; it did **not** re-run the test |
| backend gated | none for `dense_nearest` |

Recommended booleans (this backend only; does not authorize product release):

| `contract_frozen` | `acceptance_fixture_missing` | `live_runtime_missing` | `implementation_allowed` | `release_allowed` |
|---|---|---|---|---|
| true | false | false | true | true |

---

## Recommended booleans (encode for WI-C)

Machine-checkable. `implementation_allowed` / `release_allowed` stay **false** while live runtime or acceptance fixtures are missing. Synthetic/E1 is not Phase 0 pass.

| item | found/missing | E-level | backend gated | contract_frozen | acceptance_fixture_missing | live_runtime_missing | implementation_allowed | release_allowed |
|---|---|---|---|---|---|---|---|---|
| `live_legacy_cache` | missing live DB; golden synthetic only | E0 live | `legacy_cache_live` | true | true | true | false | false |
| `kohaku_tree_fixtures` | source found; tree JSON missing | E1 types / E0 fixtures | `kohaku_tree_acceptance` | true | true | true | false | false |
| `kohaku_mineru_range_trio` | missing | E1 rules / E0 fixtures | `range_trio_acceptance` | true | true | true | false | false |
| `live_mineru_runtime` | JSON contract found; digest + models missing | E1 JSON / E0 runtime | `live_mineru_runtime` | true | true | true | false | false |
| `live_mdenseon` | lock/script/fixture found; live weights missing | E1 lock / E0 bytes | `dense_mdenseon` | true | true | true | false | false |
| `target_tachiom_static_artifact` | source found; v7 artifact missing | E1 SQL / E0 target artifact | `multi_vector_tachiom` | true | true | true | false | false |
| `nearest_basic` | found | E2 | (none) | true | false | false | true | true |

**Phase 0 P1-2 hunt verdict:** required live baselines/fixtures/runtimes are still missing except target NEAREST. Do not enter Phase 1 on gated backends. Operator must supply live `byzerai_store_duckdb.db`, Kohaku/range-trio goldens, MinerU image digest + model snapshot, mdenseon weights matching the lock, and a duckdb-tachiom artifact built for `a1f0ab1911` with a recorded SHA-256 — none of those were fabricated here.

---

## Iteration 3 re-hunt (2026-08-29)

Read-only. Did not invent hashes, copy production files, or treat duckdb-tachiom 1.5.4 binaries as the v7 pin. Status booleans unchanged.

| Item | Result |
|---|---|
| live `byzerai_store_duckdb.db` under Projects / `.auto-coder` / `.cache` / `.grok` | **MISSING** (find stdout empty) |
| Kohaku tree/range fixtures (`rag/KohakuRAG`, `bookohakurag/KohakuRAG`) | dirs present; `tests/` is three Python files + README; **no `fixtures/`**; no tree/range JSON |
| MinerU runtime digest | `MinerU-Popo` and `/Users/wxl/MinerU` exist as parse-output trees; **no container digest** |
| mdenseon `model.safetensors` / tokenizer bytes | **MISSING** (lock JSON + contract only) |
| target tachiom artifact for duckdb-pgagent `a1f0ab1911` | duckdb-tachiom has 1.5.4 `duckdb_tachiom.duckdb_extension`; **not** in duckdb-pgagent `build/reldebug/extension`; **still blocked** |
| duckdb-pgagent unittest + duckdb-tachiom `Cargo.lock` | **present** on this machine (optional live NEAREST/Cargo verify; not a clean-checkout requirement) |

---

## Iteration 4 — Kohaku tree fixtures (2026-08-30)

Generated Kohaku-native trees from KohakuRAG `f3d27c8d24616b75508795766355632640979e5b` (`parsers.py` + `indexer._build_tree`, no embedder). Artifacts: `v7/tests/fixtures/kohaku/`. Evidence: `v7/evidence/kohaku_tree_fixtures.md`.

This does **not** supply MinerU→Kohaku mapping, range-trio goldens, live cache, MinerU digest, mdenseon bytes, or a tachiom artifact for `a1f0ab1911`. KohakuRAG's own tree still has no in-repo `fixtures/` directory.

---

## Addendum — MinerU identity (2026-08-30)

Append-only. Does **not** rewrite the 2026-08-29 hunt above.

| Finding | Status |
|---|---|
| Parse identity | `mineru[pipeline]==3.4.4` wheel sha256 `d4d67853…` (lock **field**, no `.whl` bytes) + Darwin `profile_id` `mineru-3.4.4-pipeline-cpython312-darwin-arm64` + 187-file snapshot manifest `8c4a6a53…` copied from in-tree `v7/evidence/locks/mineru/profile.json` and `v7/evidence/duckrag/p19-s.json`. **Not** an OCI container. |
| `mineru-3.4.4.lock.json` | Wheel pin only. **No** snapshot / OCI / container digest fields. |
| 83-wheel README | DuckRAG `environments/.../README.md` tail (“exact 83-wheel”, “P19-S remains unresolved”) is **pre-2026-08-07** and expired. Authority is `p19-s.json` (84-wheel, `run_status` completed). |
| OCI digest / single-file weights | **N/A** (`null` + `not_applicable`). Do not invent hashes. `dockerrr8277/mineru-popo-vllm:latest` is not a pin. |
| Range trio | Origin-shape fixtures at `v7/tests/fixtures/range_trio/` (`page_bbox` / `source_line` / `legacy_flat`). Fixture **E2**; `live_runtime_missing` still **true**. Not live parse. Not plan §3.14 diversity corpus. |
| P19-S | Historical record (in-tree copy sha256 `ae77a110…`). `temp_and_output_removed: true`. **Not** this-freeze live E2. |
| Live MinerU cache | `$HOME/.cache/duckrag-wi1` still **absent**. Operator re-provision stays in DuckRAG (`v7/evidence/mineru_identity.md`). Not a `phase0_pass` predicate (Option B). |
| Still missing | live `byzerai_store_duckdb.db`; mdenseon live bytes; tachiom target artifact for `a1f0ab1911`; `canonical_mineru_contract_version`. `phase0_pass` remains **false**. |
