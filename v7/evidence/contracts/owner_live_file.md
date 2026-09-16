# Owner-only live-file mode (Phase 0 WI-5 / plan §3.3)

Evidence level: **E1** technical contract from v4.1 plan §3.3 (and review F-1). Phase 1 same-process writer/reader + non-owner live-file open failure is **E2** on the v7 wheel: `v7/evidence/phase1_runtime.e2.md`. This file remains the Phase 0 contract (register level stays E1).

Related backend: not an external engine. Phase 1 must fail closed if the target DuckDB binding cannot support same-process writer + query-only readers. Do **not** work around by letting other processes open the live file.

## What was read

- `/Users/wxl/Projects/pg-agent/docs/plans/flock-rag-on-duckdb-final-plan-v4.1.md` §3.3 (lines 245–393), §3.15, Phase 0 item 12, Phase 1 items 7–9
- `/Users/wxl/Projects/pg-agent/docs/reviews/oracle-v4-plan-review-2026-08-29.md` F-1 (single-process topology)
- NEAREST E2 already captured by sibling WI-5: `v7/evidence/nearest_e2_summary.md` (unittest exit 0 on `a1f0ab1911`). This file does **not** re-run NEAREST.

No runtime owner service exists yet. This freeze is the contract later code must implement.

## Frozen fields

### Mode

First ship: **owner-only live-file mode**.

> The live text/schema DuckDB files for a deployment may be opened only by the unique owner process.

Out of first ship:

- generation-stamped immutable query snapshots
- API / queue / benchmark / CLI workers opening live files
- multiple active owner processes / cross-host owner RPC
- native multi-process read-only opens of the same live file

One owner service process may own multiple deployments. First ship: **one** active owner service consumes the whole RAG queue family.

### Layout (paths not model-supplied)

```text
<RAG_ROOT>/<deployment_id>/
  .owner.lock
  manifest.json
  text/rag.duckdb
  schema/rag.duckdb
  backups/<backup_generation>/
  result_artifacts/<artifact_id>
```

Control socket: `<RAG_ROOT>/.control/rag-owner.sock`, mode `0600`. Clients do not take a socket-path parameter. Envelope: `request_id`, deployment binding, deadline; **no credential**.

### Store identity

Per-deployment fact tables **omit `deployment_id`**. Single-row `flock_rag_store_meta`:

- `deployment_id`
- `store_kind = text | schema`
- `store_uuid`
- `catalog_version`
- `created_at`
- `build_manifest_hash`

Open-time compare: expected deployment, path-derived identity, `manifest.json`, `flock_rag_store_meta`. Any mismatch → `RAG_STORE_IDENTITY_MISMATCH`. No auto-repair.

### Connections (same owner process)

Per deployment:

- one text writer connection
- one schema writer connection
- one deployment-level writer queue (serial persistent mutation)
- default **4** query-only readers per file; operator-tunable; hard cap **16**
- DuckDB connections are **not** shared across threads
- one reader serves one request at a time

Readers are **application-layer query-only**:

- read-only transactions
- connection-local TEMP staging allowed
- forbidden: persistent DDL/DML, `ATTACH`, `INSTALL`, `LOAD`
- created by the **same** owner process as the writer
- must not depend on a second process opening the file native read-only

Non-owner open of a live file **must fail** (acceptance: plan §3.14 “任何非 owner进程打开 live file 的测试必须失败”).

### Owner fencing

Order:

1. candidate takes `.owner.lock`
2. Postgres CAS lease generation
3. open text/schema files
4. identity/manifest check
5. recover incomplete operations
6. mark servable

Must **not** announce Postgres ownership before the file lock. Stale owner must not commit if lease is uncertain. Streaming requests do not auto-replay across owner generation change.

### Query pin

At query start pin: text catalog generation, active document revisions/index generations, schema snapshot generation, owner lease generation. Subsequent materialization uses pinned IDs. GC skips in-flight pins. Owner crash drops memory pins (and in-flight queries).

## Open unknowns

- File-lock implementation for `.owner.lock` (fcntl vs DuckDB file lock) is still not chosen for the owner service. Phase 1 E2 observed the **engine** lock: a second process `duckdb.connect` (rw and `read_only=True`) fails with a conflicting lock while the owner process holds a writer.

## Backend gate

Phase 1 E2 on the v7 binding: same-process writer + guarded readers, connection-local TEMP, and non-owner process open failure. Do **not** work around by letting other processes open the live file. Owner service / `.owner.lock` remain later phases.
