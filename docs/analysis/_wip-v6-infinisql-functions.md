# InfiniSQL Functional Inventory (Item 1)

> **Scope.** This is a functional extraction of InfiniSQL from the selected `ghidra-projects` design/research documents. It is not an InfiniSynapse architecture description and is not a v6 implementation plan. Runtime details such as NestJS, SSE, task folders, SQLite replication, or delegate merge machinery are intentionally excluded except where a source document is needed to distinguish functional behavior from implementation structure.
>
> **Evidence precedence.** `03-execute-infinity-sql-implementation.md` and `06-tool-contracts-from-capture.md` are the capture-corrected sources. They supersede older static boundary conclusions where they disagree, especially the older “reject CTE/WITH” and “reject LIMIT” policies. The captures show ordinary CTEs and `LIMIT` reaching the engine successfully, with result truncation handled separately.

## 1. Functional model

InfiniSQL is a session-oriented data-analysis surface in which an agent progressively turns registered or inline data into **named, queryable temporary views**. The essential contract is not a particular server architecture or Spark implementation. It is the loop:

```text
register or load a source
    → create a named result view
    → reference that view in a later statement
    → inspect or preview a bounded result
    → optionally export or explicitly recall a larger artifact
```

The session is the continuity boundary. It contains the source registrations, temporary views, session variables, and enough ordered SQL/metadata to let later calls refer to prior names. A result-producing query is therefore both an analysis operation and a session mutation: on success it introduces a new named artifact; on failure it returns a diagnostic and must not be treated as a successful new view.

The common abstraction is a **typed, guarded mutation surface over a session-scoped registry of named data artifacts**. The artifacts are data views rather than code representations: each view has a name, a producing statement, source/dependency information, and a bounded display representation. This is the functional portion that can inform another temporary SQL workbench without importing InfiniSynapse’s surrounding runtime.

Sources: `ghidra-projects/docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md`; `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md`.

## 2. Tool contracts

### 2.1 Captured peer tools

The capture-corrected contract treats `register_table`, `list_tables`, and `show_create` as **independent peer tools**, not sub-operations hidden inside `execute_infinity_sql`. Each has its own `say` subtype and result subtype. The common required purpose field is `brief`.

| Tool | Captured input contract | Functional role | Result/behavior |
|---|---|---|---|
| `execute_infinity_sql` | `brief`, `view_name`, `query` | Execute one analysis statement and, for result-producing branches, materialize a named temporary view. | Status events use `execute_infinity_sql`; result event is `sql_query_result`. Results are slimmed for the live context and may be archived for later reading. |
| `register_table` | `brief`, `database_name`, `table_name`; captures also show generated `jobName`, `status`, `elapsedMs`. | Make an external table/file visible to the session as a queryable registered relation. | Separate tool/result path. Captured success was not available in the A1 trace, so the exact success payload is less certain than the input contract. |
| `list_tables` | `brief`, `databaseName`, `tableRegex`, `columnRegex`; captures use `workspace_files` and `columnRegex:"."` as examples. | Inspect available registered/source/session relations. | `list_tables_result`; read-only inspection. |
| `show_create` | `brief`, `database_name`, `name`; example uses `database_name:"infinity_session"`. | Inspect the definition of a source table/view or a session temporary view. | `show_create_result`; read-only inspection. |
| `load_infinity_sql_doc` | `brief`, `statement_name`. | Provide a dialect/statement reference before using an unfamiliar advanced surface. | Documentation/context result; loading documentation does not itself enable unsupported execution. |
| `use_external_tool` | `brief`, `command_name`, `arguments`. | Invoke a separately defined external command surface. | Independent `use_external_tool_result`; capability boundaries were not fully captured. |
| `tool` | `brief` plus operation-specific fields; captured operations include `listFilesTopLevel` and `readFile`. | Access workspace files under the file-system policy. | Independent `tool_result`; this is not SQL execution. |
| `delegate` | `brief`, `name`, `target_count`, and task entries containing `name`, `type`, and `prompt`. | Assign data-analysis work to child agents. | `delegate_result`; full child outputs are summarized for the parent and can be recalled from archived files. This is a collaboration surface, not part of the SQL engine contract. |

All tools require `brief`; omission produces retry feedback such as “Missing value for required parameter `brief`” rather than a completed operation. The purpose field is therefore a universal tool-level guardrail, not just descriptive UI metadata.

Sources: `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md` §§1–2, 5–6, 13; `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` §§1, 4, “独立工具”.

### 2.2 `execute_infinity_sql` fields

The stable three-argument functional contract is:

```text
execute_infinity_sql(brief, view_name, query)
```

- `brief`: required one-sentence purpose/intent. Missing `brief` is a recoverable tool-schema error and causes a retry.
- `view_name`: required for result-producing branches; the captured implementation validates it against `[a-zA-Z0-9_]+`. It is the intended session artifact name.
- `query`: required statement text. The original surface calls this Infinity SQL/MLSQL, but the functional contract is an engine-facing statement body plus a named output binding.

The implementation-level design normalizes the statement, classifies its leading family, and appends a trailing `AS <view_name>` when a result branch does not already contain the output binding. The output binding is a materialization instruction, not merely a normal projection alias. In a DuckDB-shaped implementation, the corresponding operation would be explicit `CREATE [OR REPLACE] TEMP VIEW <view_name> AS SELECT ...`, while preserving the user-visible function of the original contract.

The capture notes also show common tool status fields (`status`, `elapsedMs`) and a live execution event followed by a slimmed result. These are transport/display details; the important functional result is the named session artifact plus bounded result information.

Source: `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` §§“工具契约”, “主流程”, “sanitizer”; `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md` §§1–3.

## 3. Register → named view → chain → bounded preview

### 3.1 Register or load

There are several ingress forms:

1. **`register_table`** makes an external table/file available to later analysis. The session retains source database/table information and a session-visible registration name.
2. **`set ... scope='session'` followed by `load jsonStr.<var> AS <view>`** supplies inline line-delimited JSON through a session variable and materializes it as a view. This is a two-call flow; the session scope is required for the later load to see the variable.
3. **`load ... AS <view>`** is the general load/result branch. The captured design specifically treats `load jsonStr` as a supported session-variable path and local file loading as a guarded path.

The source registration and the result-view registry are related but distinct: registering a source makes an input available; executing a result statement creates a derived named artifact.

### 3.2 Execute and materialize a named result

For a result-producing query, the functional sequence is:

```text
validate required fields
  → normalize statement
  → determine/append output binding
  → execute against the current session engine
  → obtain columns and rows
  → create/register the named temporary view
  → publish a bounded result
  → retain metadata/summary for later recall
```

The result view is session-visible and can be queried by later statements. The model is intentionally incremental: rather than requiring one monolithic query, an agent can create `sales_by_month`, then create `ranked_regions` from it, then preview the latter. The session prompt renders the current registry as `infinity_session` context so the agent can discover what names exist.

The source implementation describes the result branch as `execute → addTemporaryView → reduce → sql_query_result → archive/summarize`. The implementation detail of the archive is not the functional identity; the functional identity is that the full relation/view remains available to the session while the immediate agent-facing response is reduced.

### 3.3 Chaining

A later query may reference:

- a registered source table;
- a prior temporary view;
- combinations of prior views and registered sources;
- where the supported session-variable flow is enabled, a view loaded from a prior session variable.

The session model should therefore retain at least a logical dependency edge from each derived view to the source registrations, prior views, and relevant variables used to create it. This supports inspection, replay, invalidation, and useful diagnostics even if the original engine itself carried the physical dependency information.

`DIRECT_QUERY` is a different source-native route in the original product: its inner native query is not allowed to use the session’s temporary tables/views. For the narrow functional inventory here, it is an excluded execution surface; it must not be conflated with ordinary `SELECT_AS`/named-view chaining.

Sources: `ghidra-projects/docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md` §“PROBE A”; `ghidra-projects/docs/research/infinisql-duckdb-production/session-semantics-research.md` §§“Session state candidate shape”, “Statement-family session side effects”; `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md` §§“Core session state”, “Statement side-effect matrix”.

### 3.4 Bounded preview and truncation

The captured behavior separates **stored analysis state** from **display/result state**. The engine obtains up to `databaseReturnLimit + 1`, with the captured default `databaseReturnLimit=500`; the extra row determines whether the result is complete. The response includes at most the configured limit and marks the result as truncated/incomplete when the probe row exists.

This means:

- SQL `LIMIT` is not the same thing as the tool’s display bound.
- A view can retain the full query result while the agent sees only a bounded sample.
- Stats/data helpers and archived files are wrapper/result artifacts, not replacements for the session view.
- Large results are reduced for prompt context and can be explicitly recalled through a file-reading tool when that path is enabled.

The later capture explicitly records `LIMIT 100` completing successfully and says `disableLimitQuery` defaults to allowing `LIMIT`; CTEs likewise are not blocked at the tool layer. Older static boundary documents that rejected CTE/WITH or treated `LIMIT` as a default rejection are superseded for this capture-corrected functional account.

Sources: `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` §§“抓包实证修正”, “_do_result_branch”, “配置门控”; `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md` §§3, 9; `ghidra-projects/docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md` §“Agent–tool contract”.

## 4. Session artifacts and visibility

The functional session is best represented as a registry with these artifacts:

```text
Session
├── set_sqls / session variables       ordered SET history and values
├── register_tables                    source identity and session-visible name
├── temporary_views                    named derived relations and definitions
├── databases / enabled sources       available source metadata
├── statement history                  accepted operations and diagnostics
└── result/archive references          bounded summaries and recall pointers
```

### 4.1 Registered tables

A registration preserves the original source identity (database/table or file information) and the name by which the agent can query it. In a DuckDB-oriented approximation, it becomes a relation in the current connection/catalog plus metadata describing its provenance and materialization mode. The registration operation is separate from `execute_infinity_sql` and is not equivalent to a source-native direct query.

### 4.2 Temporary views

A successful result-producing statement creates a named temporary view/relation in the current session. The record should include at least:

- `view_name`;
- producing statement/tool ID;
- normalized/raw SQL definition;
- creation status/time;
- output columns/sample metadata;
- source/dependency names;
- generation or replacement information if replacement is ever supported.

The original documents establish the product concept and chaining, but do not dynamically confirm every physical lifecycle detail. In particular, duplicate-name behavior, exact overwrite semantics, and restart survival remain design/validation questions rather than settled original-runtime facts.

### 4.3 Session variables and SQL history

The inline JSON path makes session variables first-class functional state: `SET` updates a session variable namespace, and a later `load jsonStr` consumes it. Ordered `set_sqls` are also useful replay material. A statement history can record normalized query, branch/class, output name, status, row/truncation metadata, and diagnostic references without changing the core meaning of the temporary view registry.

### 4.4 Task/conversation boundary

The strongest functional evidence says registered resources and temporary views persist for the conversation and remain visible across later tool calls in the same session. The exact physical key—task, conversation, user, project, or engine—is not proven by static schema strings. The safe functional statement is therefore **same-session reuse**, not engine-global visibility. Unrelated sessions should not see one another’s temporary views unless an explicit sharing/export mechanism exists.

### 4.5 Display, stats, and archive artifacts

`sql_query_result`, stats/data helper surfaces, reduced summaries, and archived Markdown/JSONL are output representations around an execution. They should be kept conceptually separate from the core SQL state:

```text
core session state: registered sources + temporary views + variables
result state:       bounded sample + columns + truncation/statistics
archive state:      recallable file references or exports
```

This distinction prevents a bounded preview from being mistaken for a truncated underlying view and prevents an archive pointer from being mistaken for a durable copy of the business data.

Sources: `ghidra-projects/docs/research/infinisql-duckdb-production/session-semantics-research.md`; `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md`; `ghidra-projects/docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md`.

## 5. Error envelope and recovery loop

The standard diagnostic is a four-part envelope:

```text
{
  "Type":    "...",
  "Phase":   "...",
  "Problem": "...",
  "Solution": "..."
}
```

The captured user-facing form renders the same fields as an `Infinity SQL Error` with the original query, a human-readable diagnosis, and recovery guidance. The recovery guidance emphasizes fixing the stated problem rather than bypassing it, and feeds the diagnostic back into the agent context so the agent can retry with a corrected statement.

Functional error categories include:

- required-parameter or invalid output-name errors;
- parser/syntax failures;
- source/file loading failures;
- unknown table/view or binding failures;
- execution/runtime failures;
- connection/source failures;
- unsupported branch or capability diagnostics where a narrow target intentionally does not implement an original advanced surface.

A key capture correction is that the real tool did **not** use a broad family of invented `INFINISQL_*_REJECTED` pre-validation codes for CTE, unknown tables, `DIRECT_QUERY`, or multi-statement cases. Those failures reached the Byzer/Spark engine and were then wrapped by `processInfiniSQLError`. A DuckDB functional equivalent should preserve the distinction between:

```text
tool contract/guard failure
  vs parser/binder/engine failure
  vs source/connection failure
  vs explicitly unsupported target surface
```

It should not claim that an engine error is a product-policy rejection merely because the target backend differs. The error wrapper may map backend exception classes to stable `Type` values, but it should preserve the engine-originated problem and add a concrete solution hint.

Missing `brief` is the clearest retry case: the tool reports the missing required field, the agent context receives retry feedback, and the call is repeated with complete arguments. This is different from a successful session mutation; no view should be created by a missing-parameter attempt.

Sources: `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` §§“抓包实证修正”, “errors”; `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md` §9; `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md` §“Diagnostics and provenance requirements”.

## 6. Guardrails and side-effect policy

The functional guardrails fall into several layers.

### 6.1 Tool-level guardrails

- `brief` is required for every captured tool.
- `query` is required for `execute_infinity_sql`.
- Result-producing calls require a valid `view_name`, with the captured simple-name rule `[a-zA-Z0-9_]+`.
- Empty/invalid input is reported before a successful mutation.
- Status and elapsed-time fields identify the operation without changing its SQL semantics.

### 6.2 Statement normalization and execution boundary

The implementation documents trimming, comment removal, and semicolon normalization before classification, and models one tool call as one statement. The capture evidence does **not** justify an invented special rejection taxonomy for every malformed or multi-statement case; the backend parser may be the component that reports the failure. A compatible target should nevertheless maintain a single-operation budget and fail closed on ambiguous multi-statement input.

### 6.3 Success-only session mutation

The target safety rule in the session research is atomic at the logical artifact level:

- accepted query succeeds → create/register the named view and its metadata;
- validation rejection or backend failure → do not create or replace the view;
- failed registration → do not leave a new successful registration;
- read-only inspection → no core session mutation.

The original runtime’s exact partial-state behavior was not fully confirmed, so this is a safe functional target policy, not a claim of original runtime parity. Duplicate names are likewise unresolved in the original evidence; the standalone persistence design recommends reject-on-duplicate by default, with atomic replacement only as an explicit later policy.

### 6.4 Source and file boundaries

The captured file path rules require workspace/upload prefixing, reject absolute paths and `..` traversal, and constrain file reads/listing to a workspace policy. The standalone DuckDB design notes that a single-user implementation could choose a different local-path policy, but a faithful safe boundary should retain an owned workspace prefix or an equivalent sandbox.

`SAVE` was captured as allowed when writing to the built-in `workspace_files` store, using a form like:

```sql
SAVE overwrite <view> AS csv.`workspace_files.<name>`
```

That is a controlled export side effect, not unrestricted arbitrary-path writing. Any equivalent must constrain the destination and prevent path traversal.

### 6.5 Sensitive values and templating

The design calls out template expansion (`:{expr}` / `${var}`) as a high-risk path because it can combine expression evaluation with file-system access. A safe target should allow only explicitly supported session variables or reject arbitrary templates. Values marked `ParameterVisibility.UN_SELECT` must not be exposed through result rows or reduced output, because a secret selected into a preview would be disclosed to the agent.

### 6.6 Engine-side failures are not silently broadened

The engine receives the supported query body; the wrapper does not pretend to provide all Byzer/Spark/MLSQL semantics. Unsupported advanced commands should be classified as unsupported or represent-only in a narrow DuckDB target rather than passed through under a misleading compatibility claim.

Sources: `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` §§“🔴 抓包实证修正”, “安全边界”, “单语句 + 分类”; `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md` §§4, 7, 9; `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md` §§“Statement side-effect matrix”, “Diagnostics and provenance requirements”.

## 7. Dialect strategy: target the real engine

The research recommends **Strategy B: rewrite the agent prompt for the target DuckDB dialect**, rather than teaching Spark/Byzer syntax and maintaining a broad Spark-to-DuckDB translation shim.

The reason is functional rather than architectural: the engine is below the tool contract and invisible to the agent. If the target engine is DuckDB, the agent should generate DuckDB SQL directly, and parser/binder errors should close the loop by giving the agent actionable correction information.

The highest-risk captured differences are:

| Original Spark/MLSQL form | DuckDB-oriented form | Why it matters |
|---|---|---|
| `date_format(d, 'yyyy-MM')` | `strftime(d, '%Y-%m')` | Java date-format tokens differ from C `strftime` tokens. |
| `to_date(s, 'yyyy-MM-dd')` | `CAST(s AS DATE)` or `strptime(s, '%Y-%m-%d')::DATE` | Function and format semantics differ. |
| `get_json_object(j, '$.a')` | JSON path access or `json_extract(j, '$.a')` | JSON syntax/type handling differs. |
| `collect_list(x)` | `list(x)` or `array_agg(x)` | Aggregate name differs. |
| `substring_index(s, delim, n)` | `split_part`/list operations or a documented helper | No direct native equivalent in the matrix. |
| `regexp_replace` | Same function name, but verify regex dialect | Java regex and DuckDB’s regex behavior differ. |
| trailing `SELECT ... AS view_name` | explicit `CREATE VIEW view_name AS SELECT ...` | The trailing `AS` is an output-materialization binding, not just a column alias. |

The strategy should be accompanied by a tested dialect corpus. The matrix is a candidate compatibility aid, not a promise of Spark parity. Functions that are directly compatible can remain unchanged; functions with different names, format strings, type rules, regular-expression behavior, division/operator semantics, or window-frame defaults need explicit prompt guidance and regression coverage.

The target should preserve the functional named-view workflow while allowing the SQL body to be native to the actual engine. “Functionally similar to InfiniSQL” therefore does not mean accepting every original MLSQL token; it means retaining the register/name/chain/preview contract and giving the agent a truthful dialect.

Sources: `ghidra-projects/docs/design/infinisql-standalone-duckdb/01-function-compatibility-matrix.md`; `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` §§“策略B 函数差异语料”, “DuckDB 执行 seam”; `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md` §3.

## 8. Persistence Candidate B: replay definitions, not bulk rows

Candidate B is the replayable-metadata model. The temporary execution engine remains ephemeral; durable storage retains enough **definitions and lineage** to reconstruct the logical session after a restart.

### 8.1 What is persisted

The design documents identify these durable metadata classes:

- session identity and lifecycle metadata;
- registered-table/source metadata: source kind, original database/table or file reference, registration name, and materialization method;
- ordered `SET` SQL/session-variable history where that surface is enabled;
- temporary-view definitions: view name, producing SQL, source tool, dependencies, timestamps, and generation/status;
- statement history and bounded result metadata such as row count, completeness/truncation, diagnostic code, and archive pointers;
- metadata-only session snapshots containing names/references, not business rows.

### 8.2 What is not persisted by Candidate B

Candidate B does **not** persist:

- the full source-table row payload;
- every temporary-view result as a durable table/file;
- a durable engine database that silently becomes the system of record;
- unrestricted full result data in the session metadata ledger.

The source data remains at its source, and replay re-reads or re-registers it. Archived JSONL/Markdown or export files are a separate explicit artifact tier; they are not evidence that Candidate B stores bulk rows as session state.

### 8.3 Replay sequence

A fresh engine session is reconstructed in dependency order:

```text
open metadata store
  → recreate registered source relations
  → replay ordered SET/session-variable definitions
  → recreate temporary views in dependency order
  → record any drift/failure diagnostics
  → expose the reconstructed session
```

Replay therefore restores the **logical workbench definition**, not necessarily the exact historical data result. If a source file/table changed, a dependency disappeared, or a function’s dialect semantics changed, a replayed view may differ or fail. The implementation should report that explicitly rather than claiming an exact snapshot restore.

The documents also distinguish Candidate A (in-memory only), Candidate C (materialized persisted session), and Candidate D (inline-JSON-enabled extension). Candidate B is the requested middle ground: continuity through replayable registrations/SQL/lineage without bulk-row persistence.

### 8.4 Evidence qualification

The existence of SQLite/task fields named `session`, `variables`, `sqls`, `register_tables`, and `databases` proves that app/task metadata persistence was represented in the recovered materials. It does **not** by itself prove that the original runtime serialized complete temporary-view data into those fields. Candidate B is therefore a documented standalone design choice and functional persistence model, not an assertion that every original InfiniSQL runtime persistence detail was dynamically confirmed.

Sources: `ghidra-projects/docs/design/infinisql-standalone-duckdb/02-sqlite-persistence-schema.md`; `ghidra-projects/docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md` §§“Persistence tiers”, “Abstraction”; `ghidra-projects/docs/research/infinisql-duckdb-production/session-semantics-research.md` §§“Persistence and SQLite `ai_task.session`”, “Candidate B — Replayable persisted session metadata”; `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md` §“Persistence, isolation, and visibility”.

## 9. In-scope versus out-of-scope functional surface

This section distinguishes the **functional core extracted for a temporary analytical workbench** from broader InfiniSQL/Byzer product surfaces. “Out of scope” here means out of scope for the narrow DuckDB-like functional target being documented; it does not deny that the original product exposed or discussed some of these features.

### 9.1 In scope for the functional core

- Required-purpose tool calls (`brief`) with stable argument schemas.
- Explicit source registration/listing/definition inspection as peer tools.
- Session-scoped registered relations and temporary views.
- One result-producing statement yielding a named output artifact.
- Later queries referencing earlier named artifacts.
- Bounded result preview with `databaseReturnLimit=500`-style limit-plus-one truncation detection.
- Engine/parser/binder errors wrapped in `{Type, Phase, Problem, Solution}` diagnostics and returned through a retry/self-correction loop.
- Controlled session-variable flow (`SET ... scope='session'` → `load jsonStr`) as an auxiliary captured pattern, subject to explicit size/type/security policy in any target implementation.
- Explicit, sandboxed export to an owned workspace destination if export is included; export is not required for the core register/chain/preview loop.
- Replayable metadata persistence of registrations, definitions, ordered session setup, and lineage—never bulk rows under Candidate B.

### 9.2 Out of scope: `DIRECT_QUERY`

`DIRECT_QUERY` is a source-native route for JDBC/ES/Mongo/file-source behavior in the original product. Its inner query is source-specific and is not the same thing as a session `SELECT` over registered relations. The original evidence also says source-native direct queries cannot see session temporary views.

For the narrow DuckDB-like functional surface, `DIRECT_QUERY` is **not executable support**. It should be rejected or represented with a clear diagnostic, and the user should be directed toward explicit registration/import followed by ordinary named-view analysis. A target must not reinterpret a JDBC/ES/Mongo native payload as DuckDB SQL merely because both contain a `query` field.

Sources: `ghidra-projects/docs/research/infinisql-language-reverse/postgres-backend-boundary.md` §§“Role separation”, “Infinisql behavior classification on Postgres”; `ghidra-projects/docs/research/infinisql-language-reverse/duckdb-backend-boundary.md` §§“Non-goals”, “IR routing table”; `ghidra-projects/docs/research/infinisql-duckdb-production/duckdb-only-production-boundary.md` rows for `DIRECT_QUERY` and file-source direct query.

### 9.3 Out of scope: ET/ML and model execution

Byzer/Spark ET commands, `DataTranspose`-style advanced transforms, model training/prediction, model registries, and broad MLlib semantics are not part of the narrow SQL workbench. They require separate semantic/runtime support and must not be advertised as ordinary DuckDB `SELECT` compatibility.

`LLM UDFs`, ByzerLLM/Ray execution, arbitrary ScriptUDFs, retrieval/ET pipelines, shell/assert plugins, and other plugin-driven model/runtime behavior are likewise out of scope for the functional SQL core. A documentation/catalog tool may describe such a surface, but “represent-only” is not the same as executable support.

Sources: `ghidra-projects/docs/research/infinisql-language-reverse/duckdb-backend-boundary.md` §§“Non-goals”, “Handling unsupported or approximate rules”; `ghidra-projects/docs/research/infinisql-duckdb-production/duckdb-only-production-boundary.md` rows for ET/ML, LLM/RAG/shell/plugin surfaces; `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md` branch handling and “仍 probe-gated”.

### 9.4 Out of scope: visualization

SQL-level visualization commands, ECharts/YAML visualization plugins, and chart-specific output protocols are outside the SQL executor’s functional core. A separate visualization consumer may use a supported named view as input, but visualization is not a reason to broaden the SQL statement language or the session mutation model.

Sources: `ghidra-projects/docs/research/infinisql-duckdb-production/duckdb-only-production-boundary.md` visualization row; `ghidra-projects/docs/research/infinisql-language-reverse/duckdb-backend-boundary.md` non-goals.

### 9.5 Other deliberately separate surfaces

- `SAVE`/export is an explicit external side effect, not ordinary view chaining; if enabled, it must remain workspace-scoped and separately audited.
- `load_infinity_sql_doc` is documentation/context, not an execution capability switch.
- `delegate` and file-based result recall are collaboration/output mechanisms, not part of the SQL engine or named-view semantics.
- Exact original frontend lifecycle/API parity is not required to preserve the functional register/chain/preview contract.
- Full Byzer/Infinity SQL compatibility is not claimed. The proper label for the narrow target is a DuckDB-like/narrow InfiniSQL functional surface.

## 10. Functional invariants to carry forward

The selected documents support these invariants for any implementation that borrows the functional model:

1. **Purposeful, typed operations.** Every tool call carries a required `brief`; tools are peers with explicit schemas.
2. **Named artifacts.** A successful result has a stable, validated session name.
3. **Session continuity.** Later operations can reference prior registered sources and temporary views in the same session.
4. **Separate stored state and display state.** Full session relations are distinct from bounded previews, statistics, and archive pointers.
5. **Capture-corrected query policy.** Ordinary CTEs and `LIMIT` are allowed by the observed tool path; the result bound is enforced at reduction/preview time.
6. **Error transparency.** Backend failures are wrapped in a four-part diagnostic without inventing misleading product rejection codes.
7. **Mutation discipline.** Rejected/failed operations do not count as successful artifact creation; exact original partial-state behavior remains a validation point.
8. **Dialect truthfulness.** Prompt/tool guidance should target the actual backend dialect rather than silently promising Spark/Byzer parity.
9. **Safe side effects.** File reads/writes, template expansion, secrets, and native-source access are bounded by explicit policies.
10. **Replayable definitions, not bulk data.** Candidate B restores logical session structure by replaying source registrations, session setup, and view definitions; it is not a row archive.

### Source index

- `ghidra-projects/docs/design/infinisql-standalone-duckdb/01-function-compatibility-matrix.md`
- `ghidra-projects/docs/design/infinisql-standalone-duckdb/02-sqlite-persistence-schema.md`
- `ghidra-projects/docs/design/infinisql-standalone-duckdb/03-execute-infinity-sql-implementation.md`
- `ghidra-projects/docs/design/infinisql-standalone-duckdb/06-tool-contracts-from-capture.md`
- `ghidra-projects/docs/design/unified-temp-workbench/SYNTHESIS-BRIEF.md`
- `ghidra-projects/docs/research/infinisql-duckdb-production/decision-summary.md`
- `ghidra-projects/docs/research/infinisql-duckdb-production/duckdb-only-production-boundary.md`
- `ghidra-projects/docs/research/infinisql-duckdb-production/session-semantics-research.md`
- `ghidra-projects/docs/research/infinisql-language-reverse/session-view-semantics-model.md`
- `ghidra-projects/docs/research/infinisql-language-reverse/duckdb-backend-boundary.md`
- `ghidra-projects/docs/research/infinisql-language-reverse/postgres-backend-boundary.md`
