# v6 DuckDB Workbench — pg-agent Seam Reconnaissance

_Read-only investigation of where a DuckDB temporary workbench attaches on frozen v5.
No v6 code, no edits to v1–v5._

---

## 1. Executive Summary

A DuckDB temporary analysis workbench for v6 attaches at the **worker process boundary**, not inside PostgreSQL. The sticky v4/v5 `wb_*` tools are PostgreSQL functions bound to `pg_my_temp_schema()` on the sticky run connection; DuckDB has no equivalent backend. The correct v6 pattern is a **mixed SQL/worker design**:

1. New `wb_duck_*` COMMENT-registered `llm_tool` scheduler functions (SQL side, enqueue-only).
2. A new `duck_heavy_requests` PGMQ queue with a registered `queue_handler`.
3. Worker-side `DuckSessionManager` owning per-run in-memory DuckDB connections.
4. Generic `apply_queue_result()` dispatcher resumes the run after worker execution.

PostgreSQL remains the source of truth. DuckDB is a temporary analytical execution layer. The existing v5 process invariants (own DB per stage, `REFRESH_AFTER` protocol, no SQL-side LLM HTTP, v6-local worker code) are preserved.

---

## 2. Sticky TEMP Analog

### v4/v5 Current State

The v4 `sticky_workbench` tools operate on `pg_my_temp_schema()` within the sticky PostgreSQL connection (`AgentWorker.conn_for(run_id)`):

- `wb_temp_view_list()` — enumerates temp views in current backend.
- `wb_temp_view_create()` — creates/replaces a temp view.
- `wb_temp_view_drop()` — drops a temp view without CASCADE.
- `wb_brief_query()` — bounded preview with `limit + 1` truncation probe.
- `wb_sql_curate()` — atomic create + COMMENT ON VIEW.

Key helpers in `workbench_core.sql`:
- `_wb_normalize_temp_view_name()` — validates simple identifiers.
- `_wb_temp_view_oid()` — resolves view OID via `pg_my_temp_schema()`.
- `_wb_temp_view_columns()` — returns ordered column metadata.

These views are **connection-scoped**: they disappear when the sticky connection closes. They are visible only to subsequent turns of the same run on the same connection.

### v6 DuckDB Analog

DuckDB runs **outside PostgreSQL** — in the v6 worker process. There is no `pg_my_temp_schema()` equivalent. The analog is:

| v4/v5 PostgreSQL | v6 DuckDB |
|---|---|
| Sticky `AgentWorker.conn_for(run_id)` | Worker-owned `DuckSession` keyed by `run_id` |
| `pg_my_temp_schema()` temp views | In-memory DuckDB temporary views |
| Connection close → state lost | Worker process loss → `DUCK_SESSION_LOST` error |
| `temp` mode (connection-scoped) | In-memory DuckDB, no persistence |
| `replayable` mode (per-run schema `agent_run_<32hex>`) | In-memory DuckDB reconstructed from PostgreSQL metadata tables |

**Critical boundary**: PostgreSQL SQL functions **cannot** see or manipulate DuckDB session state. DuckDB tools must never assume PostgreSQL TEMP VIEWs or `session_set()` values exist in DuckDB.

---

## 3. Named `wb_*` vs `execute_sql`

### v5 Dispatch (`v5/named_tools/named_tools.sql`)

`invoke_named_llm_tool(p_action, p_action_input)`:

1. Looks up `plugin_bindings` where `binding_type = 'llm_tool'` and `binding_name = p_action`.
2. Reads COMMENT metadata (`llm_tool.args` map).
3. Validates JSON object arguments against declared arg names.
4. Coerces JSON values to PostgreSQL function parameter types (`text`, `integer`, `boolean`, `jsonb`).
5. Dynamically executes the PostgreSQL function with named arguments.
6. Wraps result in standard named-tool envelope: `{success, data, row_count, tool, args}`.

`apply_llm_response()` already handles **asynchronous** tools:
- Detects `defer=true` in nested result.
- Emits a `wait` step with `wait_kind`, `queue`, `request_id`, `tool`.
- Returns `{done: false, waiting: true}` — the run enters `WAITING_QUEUE`.

### v6 Attachment

New `wb_duck_*` functions are registered as `llm_tool` bindings (same as v4 `wb_*` tools). They are **scheduler-only** — they never execute DuckDB. Their behavior:

1. Validate arguments (`brief`, identifiers, limits).
2. Allocate a `request_id` and per-run `op_seq`.
3. Insert metadata into v6 PostgreSQL tables.
4. Send a message to `duck_heavy_requests` PGMQ.
5. Return the deferred envelope:

```json
{
  "success": true,
  "defer": true,
  "wait_kind": "queue",
  "queue": "duck_heavy_requests",
  "request_id": "<uuid>",
  "tool": "wb_duck_query"
}
```

`invoke_named_llm_tool()` already supports this envelope shape. **No change to v5 named-tool dispatch is required.**

### Key Difference from `execute_sql`

| Aspect | `execute_sql` | `wb_duck_*` |
|---|---|---|
| Execution | Immediate on sticky PostgreSQL connection | Deferred to worker DuckDB session |
| State visibility | PostgreSQL TEMP VIEWs | DuckDB temporary relations (invisible to PostgreSQL) |
| Result | Direct JSON result | Deferred envelope → wait step → queue → worker → `apply_queue_result()` |
| Session scope | `run_connection` (PostgreSQL) | `run_id` (worker DuckDB) |

---

## 4. Workbench vs Queue Registry Non-Intersection

### v4 Rule

`plugin_bindings` distinguishes:
- `binding_type = 'llm_tool'` — functions callable by the LLM.
- `binding_type = 'queue_handler'` — functions that apply queue results.

**No COMMENT may declare both binding kinds for the same function.** This ensures the SQL-side scheduler and the worker-side executor are separate code paths.

### v6 Preservation

- `wb_duck_*` scheduler functions → `llm_tool` bindings only.
- `apply_duck_heavy_result()` (or equivalent) → `queue_handler` binding only.
- The worker calls `apply_queue_result()` with the queue name — the generic dispatcher routes to the registered handler.

This separation is **mandatory**. A function that both the LLM can call and the worker can invoke would bypass the queue's idempotency, ordering, and crash-recovery semantics.

---

## 5. `sql_heavy` Isolation

### v4 Precedent (`v4/queue_kinds/README.md`)

`sql_heavy_requests`:
- Executes on a **separate PostgreSQL connection** (`_run_sql_heavy` opens `connect(self.uri, autocommit=True)` then closes it).
- **Cannot see sticky TEMP VIEW/KV state** — it has no access to `pg_my_temp_schema()` of the run connection.
- Timeout and structured SQL error are verified.

### v6 Extension

DuckDB is **more isolated** than `sql_heavy`:

| Dimension | `sql_heavy` | DuckDB (`duck_heavy_requests`) |
|---|---|---|
| Execution location | Separate PostgreSQL connection | Worker process, in-memory DuckDB |
| Sees sticky TEMP | No | No (cannot see any PostgreSQL session state) |
| State persistence | None (query result only) | Per-run in-memory DuckDB + PostgreSQL metadata |
| Crash recovery | Queue replay reruns SQL | `temp` mode: session lost; `replayable` mode: reconstruct from metadata |
| Result scope | Single query result | Multi-step workbench session (register → view → chain → preview) |

**Visibility rule (must be preserved)**:
```
PostgreSQL sticky TEMP VIEW/KV
  ≠
worker DuckDB session
```

A DuckDB operation may read **registered persistent PostgreSQL tables** (via source registration), but it must not assume PostgreSQL TEMP objects exist in DuckDB. PostgreSQL SQL tools must not assume DuckDB views exist.

---

## 6. Session Temp vs Run-Schema

### v4 Semantics (`v4/session_durability/README.md`)

Two PostgreSQL session modes:
- **`temp`** (default): connection-scoped TEMP objects; disappear on connection close.
- **Durable per-run schema**: `agent_run_<32hex>` derived from server-generated `run_id`; survives connection close; resumable by new worker.

Children inherit the parent's mode but do not share the parent's schema.

### v6 DuckDB Mapping

| v4 PostgreSQL Mode | v6 DuckDB Mapping |
|---|---|
| `temp` | In-memory DuckDB connection owned by one worker process; lost on worker loss returns `DUCK_SESSION_LOST`. |
| Durable per-run schema | In-memory DuckDB reconstructed from replayable definitions in PostgreSQL metadata tables. Bulk rows are NOT stored. |
| Child inherits mode | Child receives same mode value, fresh DuckDB connection, separate `(run_id, artifact_name)` namespace. |
| Parent/child schema isolation | No implicit artifact sharing; children must re-register sources. |

**Key invariant**: The v6 session mode is inherited from v4/v5. v6 must not create a second independently configurable mode. The existing `agent_runs` field and run-creation interface must be inspected before implementation.

**Metadata tables** (PostgreSQL, not DuckDB):
- `duck_workbench_sessions` — one row per run workbench.
- `duck_artifacts` — logical artifact registry (sources and views).
- `duck_operations` — append-only execution/audit record.

These store **definitions, state, lineage, and bounded metadata** — never bulk source rows.

---

## 7. `apply_queue_result` / `invoke_named_llm_tool`

### Current Flow (v5)

```
LLM action
  → apply_llm_response()
    → invoke_named_llm_tool(action, action_input)
      → plugin_bindings lookup
      → PostgreSQL function on sticky connection
        → result returned to apply_llm_response()
```

### DuckDB-Augmented Flow (v6)

```
LLM action: wb_duck_query(...)
  → invoke_named_llm_tool("wb_duck_query", '{"brief":"...","view_name":"x","query":"..."}')
    → wb_duck_query() SQL scheduler
      → validates args, allocates request_id + op_seq
      → inserts metadata into duck_operations
      → sends to PGMQ duck_heavy_requests
      → returns {success:true, defer:true, wait_kind:"queue", queue:"duck_heavy_requests", ...}
  → apply_llm_response() detects defer=true
    → emits 'wait' step
    → returns {done:false, waiting:true}
  → run enters WAITING_QUEUE
  → worker polls duck_heavy_requests
    → DuckSessionManager.get_or_open(run_id)
    → validates and executes DuckDB operation
    → calls apply_queue_result("duck_heavy_requests", msg_id, run_id, result)
      → generic dispatcher routes to registered queue_handler
      → PostgreSQL metadata committed
      → run resumed once
```

**No change to `invoke_named_llm_tool()` or `apply_queue_result()` is required.** The existing async named-tool metadata and generic queue dispatcher already support this pattern.

---

## 8. v5 Process Invariants for v6/`load.py`

### v5 Pattern (`v5/load.py`)

```python
SQL_LOAD_ORDER: list[Path] = [
    # 1–12: read-only v3/v4 inputs
    AGENT_ROOT / "v3" / "pg_agent_pgmq.sql",
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "v4_runtime_guard.sql",
    # ... 10 more v3/v4 files ...
    # 13–17: v5 files
    V5_ROOT / "prompt_taxonomy" / "prompt_taxonomy.sql",
    V5_ROOT / "recipe_components" / "prompt_recipe.sql",
    V5_ROOT / "prompt_pipeline" / "prompt_pipeline.sql",
    V5_ROOT / "named_tools" / "named_tools.sql",
    V5_ROOT / "generate_missing" / "prompt_generation.sql",
]

REFRESH_AFTER = {
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "plugin_taxonomy.sql",
    # ... all files that register COMMENT plugins ...
    V5_ROOT / "generate_missing" / "prompt_generation.sql",
}

STAGE_THROUGH = {
    "kernel_freeze": 12,
    "prompt_taxonomy": 13,
    # ...
    "integration": 17,
}
```

### v6 Requirements

v6 `load.py` must:

1. **Reuse v5 SQL paths, not copy them.** v5 reads v3/v4 paths directly; v6 must read v5 paths directly.
2. **Append v6 SQL files in stage order.** Cumulative load order: v3/v4/v5 files first, then v6 files.
3. **Define `REFRESH_AFTER` for every inherited and new COMMENT plugin file.**
4. **Define `STAGE_THROUGH` for each v6 stage** (W1 kernel_freeze through W9 integration).
5. **Preserve `ON_ERROR_STOP` psql behavior.** A failing stage stops the sequence.
6. **Not import v5 or v4 worker code at runtime.** Worker is v6-local.

**Invariants preserved from v5:**
- Each stage uses its own database.
- A failing stage stops the sequence.
- v1–v5 files are loaded read-only.
- Every COMMENT plugin file is followed by `SELECT refresh_plugins()`.
- SQL never calls model HTTP.
- Worker code is v6-local and does not import v5 or v4 at runtime.
- Generic queue application remains generic (`apply_queue_result()` has no queue-kind branches).

---

## 9. Recommended Attachment Points

### Where DuckDB Attaches

| Component | Location | Role |
|---|---|---|
| `v6/load.py` | Cumulative SQL load order | Inherits all 17 v5 files; appends v6 SQL |
| `v6/kernel_freeze/` | Verify frozen v5 baseline | Proves v5 integration remains green |
| `v6/duckdb_runtime.py` | `DuckSessionManager`, `DuckSession` | Worker-owned per-run DuckDB lifecycle |
| `v6/duckdb_ingress.py` | `PostgresSourceResolver` | Maps `source_id` to PostgreSQL DSN; bounded snapshot |
| `v6/duckdb_validation.py` | Argument, identifier, SQL validator | Ports `_wb_validate_select_sql` semantics to DuckDB dialect |
| `v6/duckdb_results.py` | Bounded preview, `limit + 1` truncation | Ordered columns, JSON-safe conversion |
| `v6/duckdb_errors.py` | DuckDB/PostgreSQL error classification | Four-part `{Type, Phase, Problem, Solution}` envelope |
| `v6/source_ingress/duck_sources.sql` | PostgreSQL metadata tables | `duck_workbench_sessions`, `duck_artifacts`, `duck_operations` |
| `v6/queue_bridge/duck_queue.sql` | `duck_heavy_requests` + DLQ + handler | Queue registration, idempotency, `apply_duck_heavy_result()` |
| `v6/duck_tools/duck_tools.sql` | `wb_duck_*` scheduler functions | COMMENT-registered `llm_tool` bindings; enqueue-only |
| `v6/dialect_guardrails/duck_prompt.sql` | Prompt recipe | Distinguishes `execute_sql` vs `wb_duck_*`; teaches explicit DuckDB 2.0 SQL |
| `v6/budget_observability/duck_budget.sql` | Bounded metrics, budgets | Source/query budgets, timeout, memory limits |

### Worker Attachment

In `v6/kernel_freeze/worker.py` (derived from v5, no v5/v4 imports):

1. Poll `duck_heavy_requests` in `pump_once()`.
2. Map to `DuckDBWorkerProcessor` (new component).
3. `DuckSessionManager.get_or_open(run_id)` — owns per-run connection.
4. Execute validated DuckDB operations.
5. Call `apply_queue_result()` for every result (existing generic path).
6. Release DuckDB sessions on terminal cleanup.

### What Must NOT Live in SQL

These responsibilities are **worker-side only** and must never appear in SQL files:

1. **DuckDB execution** — PostgreSQL functions cannot access worker-local DuckDB connections.
2. **DuckDB connection management** — `DuckSessionManager` is a Python runtime object.
3. **DuckDB session state** — in-memory, not stored in PostgreSQL.
4. **Source credentials** — resolved by `PostgresSourceResolver` from worker config/secrets; never in SQL payloads, `duck_sources`, `agent_steps`, PGMQ messages, or tool results.
5. **LLM HTTP calls** — existing prohibition; SQL-side model HTTP remains forbidden.
6. **Bulk data storage** — DuckDB is temporary analysis; source rows are not persisted in PostgreSQL metadata.
7. **DuckDB memory/timeout configuration** — set on the worker-side DuckDB connection, not via PostgreSQL parameters.
8. **DuckDB parser/AST operations** — validation may use DuckDB's parser, but that is a Python-side library call, not SQL.

---

## 10. Key Precedents and Constraints

### `sql_heavy` Cannot See Sticky TEMP

v4 `queue_kinds` proves that a separate execution context (even within PostgreSQL) cannot see sticky session state. DuckDB is a **stronger isolation boundary** — it is a separate runtime entirely. The design must not attempt to make PostgreSQL TEMP VIEWs visible to DuckDB or vice versa.

### `prepare_llm_request()` is SQL-side Only

`prepare_llm_request()` in `workbench_core.sql` assembles messages from `agent_steps` and `make_system_prompt()`. It does not and cannot reference DuckDB state. The prompt recipe (`agent_system` v2+) teaches the model to use `wb_duck_*` tools; DuckDB session inspection happens through tool results in `agent_steps`, not through SQL-side catalog queries.

### Idempotency and Crash Recovery

The existing generic queue infrastructure provides:
- `(queue_name, msg_id)` idempotency via `apply_queue_result()`.
- Duplicate queue results do not create duplicate logical steps.
- PGMQ `read_ct` tracking and DLQ for exhausted retries.

v6 adds:
- `request_id` uniqueness in `duck_operations`.
- `(run_id, op_seq)` uniqueness for per-run ordering.
- `temp` mode: worker loss → `DUCK_SESSION_LOST`; model must rebuild.
- `replayable` mode: new worker reads `duck_artifacts` metadata and reconstructs DuckDB session from source snapshots + view definitions.

### Error Contract Continuity

InfiniSQL's four-part `{Type, Phase, Problem, Solution}` ≈ pg-agent `WORKBENCH_ERROR`. v6 DuckDB errors keep the same shape:

- `Type`: `DUCK_ARGUMENT_ERROR`, `DUCK_IDENTIFIER_ERROR`, `DUCK_UNSUPPORTED_STATEMENT`, `DUCK_SOURCE_NOT_ALLOWED`, `DUCK_SOURCE_NOT_FOUND`, `DUCK_PARSE_ERROR`, `DUCK_EXECUTION_ERROR`, `DUCK_SESSION_LOST`, `DUCK_TIMEOUT`, `DUCK_MEMORY_LIMIT`, etc.
- `Phase`: `Validation`, `Resolution`, `Execution`, `Queue`.
- `Problem`: Human-readable description; engine errors length-limited and stripped of DSNs/credentials.
- `Solution`: Actionable guidance.

Engine-originated messages (DuckDB parser/binder) may be included in `Problem` but must not be the sole diagnostic — the mapper must preserve the distinction between validation failure, PostgreSQL source failure, DuckDB engine failure, and queue failure.

---

## 11. Open Questions for v6 Implementation

1. **Does the v4 `session_durability.sql` expose the session mode field in the run-start interface?** Must be confirmed before v6 session mode inheritance is implemented.
2. **What is the exact `apply_queue_result()` signature?** Must be confirmed to ensure the DuckDB result handler matches.
3. **What is the `plugin_bindings` COMMENT schema for `queue_handler` bindings?** Must be confirmed for the new DuckDB queue handler.
4. **DuckDB wheel:** locked to `duckdb==1.6.0.dev365` on macOS arm64 (engine `v2.0.0-alpha38615`). No other versions or OS.
5. **Postgres extension vs pgembed 18.4:** live `ATTACH READ_ONLY` works, including filter pushdown and snapshot `CREATE TABLE AS`. Query session must not `LOAD postgres` (`postgres_scan` still networks after lock). Optional sidecar copy only. `pg_duckdb` (Postgres-side) rejected. See main report §4.5.1.
6. **Grammar-extension / trailing `AS view_name`:** not usable on this wheel (`|>` parse error, `INSTALL pipe` 404, trailing `AS` is a table alias). Do not schedule.

---

_Reconnaissance complete. No files modified. Next step: v6 implementation planning (Item 4 in the oracle plan)._
