# Phase 1 runtime E2

**Verdict: E2** — `v7/tests/test_phase1_runtime.py` exit 0 on the v7 wheel, not the v6 pin.

- Command: `/tmp/v7-phase1-verify/bin/python v7/tests/test_phase1_runtime.py`
- CWD: `/Users/wxl/Projects/pg-agent`
- Wheel: `duckdb-python-pgagent/dist-v7/duckdb-1.6.0.dev366-cp312-cp312-macosx_26_0_arm64.whl`
- Wheel SHA-256: `d4e8fd28e6c6daa22dba349ed253b45b7a9f01e110126f65dc79a126308ba5ff`
- Installed `_duckdb.cpython-312-darwin.so` SHA-256: `ade34cde28a7dfa7ca3ed960e06b78d25c756a0edb3cc8dadc4c02302c1e4a63`
- Target DuckDB commit: `a1f0ab191185c0852b162adc6feb206822dc9daa`
- Machine-checkable: `v7/evidence/phase1_runtime.e2.json`
- Raw log: `v7/evidence/phase1_runtime.e2.log` (SHA-256 `48d0b92eebf0780847ac0fd1bd068e909c553f2650dbc7626fc78a5d5ba6bda8`)

## Behaviors actually executed

| Check | Result |
|---|---|
| v7/v6 wheel hashes distinct and match freeze | pass |
| `flock_rag_health()` abi/catalog/tachiom/manifest/fts | pass; tachiom `RAG_MULTI_VECTOR_UNAVAILABLE`; flock/fts `STATICALLY_LINKED` |
| `EXACT NEAREST 3` | pass (`P1,P2,P5`) |
| `APPROX NEAREST 3` recorded, not defaulted | pass (currently identical) |
| `nm -gU` keeps `RagRegistry`, `FtsExtension`, `RegisterLinkedExtensions`; no tachiom | pass |
| same-process writer + 4 default / 16-cap readers | pass |
| connection-local TEMP `rag_candidates` | pass (no leak to other reader or writer) |
| reader persistent DDL/DML, `ATTACH`/`INSTALL`/`LOAD` rejected | pass |
| non-owner subprocess `connect` rw and `read_only=True` | pass (DuckDB live-file lock: conflicting lock) |

stderr `flock_storage` attach messages are Flock LLM storage auto-attach under isolated `HOME`, not the live RAG file.

Health `manifest=phase_1_in_progress` is the compiled placeholder while catalog is `not_initialized`. Do not treat that string as “Phase 1 work unfinished.” Do not enter Phase 2 catalog from this file. tachiom stays blocked. Not E3.
