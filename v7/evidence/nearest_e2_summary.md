# NEAREST E2 verification (Phase 0)

**Verdict: E2** — unittest exit code 0; `nearest_basic.test` executed and passed (112 assertions, 1 test case).

- Command: `./build/reldebug/test/unittest test/sql/join/nearest/nearest_basic.test`
- CWD: `/Users/wxl/Projects/duckdb-pgagent`
- Commit: `a1f0ab191185c0852b162adc6feb206822dc9daa` (`duckdb-special-20260829-g1`)
- Binary: `/Users/wxl/Projects/duckdb-pgagent/build/reldebug/test/unittest`
- Binary SHA-256: `2924bc6ce716b2363c218c28e4418ad57c7e800f735cf0bd4520baf7df8519b8`
- Binary type / size / mtime: Mach-O 64-bit executable arm64; 11567456 bytes; 2026-08-29T12:21:55 local
- Build identity: duckdb-pgagent commit `a1f0ab191185c0852b162adc6feb206822dc9daa` tag `duckdb-special-20260829-g1`
- Machine-checkable: `v7/evidence/nearest_e2.json`
- Raw log: `v7/evidence/nearest_basic.e2.log`
- DuckDB source was not modified; Phase 1 was not implemented. SHA-256 is of the on-disk binary (re-hashed this freeze); the E2 log recorded exit 0 on the same path and commit.

## Behaviors actually executed

The sqllogictest file is a single case (`# name: test/sql/join/nearest/nearest_basic.test`). Query labels are comments. All of the following ran (suite passed as a whole; no skip/xfail):

| Behavior | Test comment / query label | Executed |
| --- | --- | --- |
| APPROX kNN | `# Batch recommendations: 2 nearest products per user (BY SIMILARITY)` — `APPROX NEAREST 2 BY SIMILARITY` | yes |
| EXACT kNN | `# Ad-hoc vector search with an explicit query vector, BY DISTANCE, EXACT` — `EXACT NEAREST 3 BY DISTANCE` | yes |
| APPROX vs EXACT | `# APPROX and EXACT produce identical results (APPROX is currently informational)` — EXCEPT of both | yes |
| Prefilter | `# Pre-filtered subquery target (EU products only), aliased` — join of `WHERE country='EU'` subquery | yes |
| Implicit top-1 | `# Default count is 1 when NEAREST has no number` — `NEAREST BY DISTANCE` with no k | yes |
| Implicit top-1 (bare) | `# Unaliased base-table target (bare grammar path)` — `NEAREST 1` | yes |
| APPROX unaliased | `# Unaliased + APPROX (bare path must not consume APPROX as an alias)` | yes |

Also executed (same file): empty-target INNER vs LEFT OUTER; duplicate left rows; non-vector `abs(q.x - t.y)` ranking; NULL ranking drop; BY SIMILARITY vs BY DISTANCE opposite ends.

Evidence grade is **E2** only because exit code was 0. No duckdb-pgagent files were edited.

## Live gate vs historical freeze

This file is a **historical freeze** of an E2 run. The Phase 0 evaluator reports live E2 only if `v7/evidence/nearest_basic.e2.log` exists and has content **and** the target `unittest` binary is present (env `PG_AGENT_UNITTEST_BIN` / `DUCKDB_PGAGENT_UNITTEST`, or the repo-root-relative path in `v7/evidence/nearest_live_binary.relpath`) and SHA-256/size/fields match. The recorded absolute `binary_path` is freeze metadata, not a live input. Missing, malformed, or mismatched binary, log, or relpath config **downgrades the live gate to blocked** and emits stable blocker `nearest_target_e2_unverified`. Historical evidence here is preserved separately from that live result. Do not claim E2 from absence. Do not invent a new E2 execution. This is not E3.
