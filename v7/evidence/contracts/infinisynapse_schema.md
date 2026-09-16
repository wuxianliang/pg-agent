# Infinisynapse schema workflow contract (Phase 0 WI-3)

Split contract (P2-5):

- **Workflow semantics:** **E1**, allowed. Frozen sequence is `list_tables → show_create → register_table` as context binding (not table-data copy).
- **Exact tool DTO / tool-shape:** **E0**, blocked. Current `src/agent/infini-sql/*.ts` handlers are **obfuscated**; original `original-app-tool-contracts-2026-05-27.json` is **missing** from the dirty tree. Exact DTO is not frozen E1.

Related backend: schema RAG **workflow semantics** are not blocked. Exact DTO backend is blocked. Do **not** copy JDBC/DatabaseHub/Infinity SQL runtime (plan §3.10, §3.15). v7 maps the workflow onto Flock schema snapshot + `register_table` as **context binding only**. Machine-checkable split: `infinisynapse_schema.json`.

## What was read

| Path | Notes |
|---|---|
| `/Users/wxl/Projects/infinisynapse` | git `c4def3563a2100012ad33826902a62263fb86614` `master` **dirty** (many `docs/investigations/*` deleted) |
| `src/modules/ai-rag/{ai-rag-sdk.controller.ts,ai-rag.module.ts,rag-hub.ts}` | RAG SDK HTTP + RagHub |
| `src/agent/tools/all-tool-specs.ts` | Tool name map |
| `src/agent/prompts/prompt-sections.ts` | Error-recovery workflow text |
| `src/modules/websocket/socket-module.ts` | Data-analysis agent allowed tools + workflow |
| `src/agent/infini-sql/handle-list-tables.ts` | Present, obfuscated |
| `docs/investigations/infinirag-rag-implementation-2026-06-03.md` | RAG implementation investigation |
| `prompt-exports/oracle-plan-2026-05-27-233922-infinity-sql-rewrite-b335.md` | Tool contracts table (cites the now-missing JSON) |
| `/Users/wxl/Projects/repoprompt-ce-agno/src/agno_infinisynapse/tools/sql_tools.py` | Rewrite of `execute_infinity_sql` only; **not** a confirmed reproduction of list/show-create/register |

## Frozen workflow (product)

v4.1 §3.10 (`flock-rag-on-duckdb-final-plan-v4.1.md:1051-1056`) plus Infinisynapse evidence:

```text
list_tables → show_create → register_table → execute SQL
```

Meanings to freeze for v7:

1. **`list_tables`**: discover relation names (and optional columns) from a bound schema source. Does not ingest table **data** into the schema RAG store.
2. **`show_create`**: return normalized DDL / metadata for one relation. Flock target API: `flock_schema_show_create(relation)` (plan §3.8).
3. **`register_table`**: add an **authorized relation descriptor** to the active schema context. **Does not copy table data** into schema RAG.
4. **`execute SQL`**: remains the existing guarded SQL tool. `use_rag_tool` must **not** grow an arbitrary SQL parameter.

Infinisynapse original **does** register resources into an Infinity SQL session (oracle-plan registration path). v7 **does not** replicate that engine. The frozen *agent-visible* sequence is the same; the storage is schema snapshot + context, not Byzer/Spark.

## Tool names and required params

`all-tool-specs.ts:158-161`:

```text
execute_infinity_sql
register_table
list_tables
show_create
load_infinity_sql_doc
```

Oracle-plan table (`oracle-plan-...b335.md:347-353`), sourced from the missing JSON (treat as E1 of the plan export, not of the deleted file):

| Tool | Required params |
|---|---|
| `execute_infinity_sql` | `brief`, `view_name`, `query` |
| `register_table` | `brief`, `database_name`, `table_name` |
| `list_tables` | `brief`, `database_name` |
| `show_create` | `brief`, `database_name`, `name` |
| `load_infinity_sql_doc` | `brief`, `statement_name` |

Result UI messages (`oracle-plan:370-378`): `list_tables` / `list_tables_result`, `show_create` / `show_create_result`, `register_table` / `register_table_result`.

Artifacts originally: `register_table/*_data.jsonl`, `register_table/*_stats.md`, `show_create/*.md`. v7 must not require those paths; they are original-app evidence only.

## Workflow text (source)

Data-analysis sub-agent (`socket-module.ts:329` excerpt in grep):  
“discover and register additional tables via list_tables → show_create → register_table”.

Error recovery (`prompt-sections.ts:138`):

- SQL syntax/column error → `show_create`
- Table not found → `list_tables` then `register_table`
- Timeout/network → retry **once**
- After 2–3 failed attempts, switch strategy

Allowed tools include `list_tables`, `show_create`, `register_table`, `execute_infinity_sql` (`socket-module.ts:279`).

## RAG vs schema (do not conflate)

`infinirag-rag-implementation-2026-06-03.md`: InfiniSynapse has **no** module named `infinirag`. Text RAG is `use_rag_tool` → `RagHub` → `AutoCoderRAGClient` (`auto-coder.rag`). Schema/database binding is `ai_rag_database_link` / `bindDatabases`. v7 splits **text store** and **schema store** physically (plan §3.10).

`use_rag_tool` required fields in investigation: `brief`, `question`, `server_name` (investigation §2). v7 named tool params are the v4.1 set (`query`, `mode`, …) — **not** a copy of Infini `server_name`.

## agno_infinisynapse (rewrite evidence)

`sql_tools.py:1-45`: implements `execute_infinity_sql` under `INFINI_PRODUCT_TOOLS`; explicitly **not** a reproduction of original parameters (contract §35). Do not freeze Infini SQL rewrite DTOs as Flock schema RAG.

## Open unknowns

- Clean TypeScript for `handleListTables` / `handleShowCreate` / `handleRegisterTable` (current files obfuscated).
- Deleted `docs/investigations/original-app-tool-contracts-2026-05-27.json` (git status `D`). Param table above is from the oracle-plan export.
- Exact `list_tables` column regex / `brief` semantics beyond “required param”.
- `/ai_database` controller missing from current `src` (investigation §1).

## Backend gate

Not blocked for **schema workflow list/show-create/register-table-as-context** (E1 workflow semantics). Blocked for **exact tool-shape / DTO** (E0: obfuscated handlers + missing original JSON). Blocked for any attempt to vendor DatabaseHub / Infinity SQL / JDBC. Flock catalog extraction functions (`duckdb_tables()` etc.) still need target-fork E2 (plan §3.10) — out of this WI.
