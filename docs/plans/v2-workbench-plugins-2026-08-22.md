# v2 Workbench Plugins: Plan

## Goal

Upgrade only v2 (`da_agent`) so the Postgres-only data-analysis workbench is extended by one SQL plugin file at a time, with an explicit COMMENT/registry/prompt standard. Do not route workbench operations through `jobs`/`worker()`/`job_handler`.

Locate objects by **symbol name**; line numbers in this document are snapshots as of 2026-08-22 and may drift.

Open questions from the scaffold are **resolved**: keep `da_*` as unadvertised legacy helpers; resolve TEMP VIEW names only in `pg_my_temp_schema()` (unqualified).

## Background

Authoritative investigation: `docs/investigations/cordis-workbench-plugins-2026-08-22.md`.

- v1/v2 queue plugins: `COMMENT {"job_handler"}` → `refresh_handlers()` → `handlers` → `worker()` (`v2/pg_agent_functional.sql:294-327,465-497`). `cordis_services` unused (`v1/pg_agent_fixed.sql:111-118`).
- DA is synchronous: `agent_run_data_analysis` → `rlm_loop` → `rlm_eval` → `exec_sql_readonly` in the caller session (`v2/pg_agent_data_analysis.sql:149-177`; `v2/pg_agent_rlm.sql:395-514,361-388`).
- `make_da_prompt` is IMMUTABLE and hardcoded (`v2/pg_agent_data_analysis.sql:92-117`); `rlm_loop` currently calls it directly (`v2/pg_agent_rlm.sql:419-424`); `da_system_prompt` is STABLE and test-only (`:138-147`).
- `exec_sql_readonly` lexical blacklist includes `create` (`v2/pg_agent_functional.sql:252-287`); `SELECT fn()` can still mutate inside the function (`da_sample` `EXECUTE format`, `:62-89`). TEMP objects are session-local; `worker()` is a different backend.
- v1 `w_tools` COMMENT `llm_tool` scan (`v1/pg_agent_poml.sql:263-283`) is the prompt-inventory precedent.

## References

- `docs/investigations/cordis-workbench-plugins-2026-08-22.md`
- `v2/setup_db.py`, `v2/README.md`, `v2/TEST_REPORT.md`
- `v1/run_tests.py:262-286` (comment add/render/restore)
- Design critique: `docs/reviews/v2-workbench-plugins-plan-review-2026-08-22.md` (findings folded into this plan)

## Work items (execution index)

| ID | Goal | Done when | Key files | Dependencies | Size |
|---|---|---|---|---|---|
| W1 | Core registry + resolvers | Table, helpers, refresh/render, empty-registry prompt section, atomic failed refresh | `v2/pg_agent_workbench_core.sql` | functional + rlm loaded | M |
| W2 | DA prompt wrapper | `make_da_prompt` still IMMUTABLE, no `da_*` ads; `da_system_prompt` appends tools; `rlm_loop` DA branch calls `da_system_prompt(p_run_id)` | `v2/pg_agent_data_analysis.sql`, `v2/pg_agent_rlm.sql:419-424` | W1 | S |
| W3 | Loaders | After W1: load core and refresh (0 tools). After each plugin file exists, append it to `SQL_FILES` and refresh. Six-tool count is a **final** gate after W7, not a mid-sequence setup check | `v2/setup_db.py`, `v2/test_data_analysis.py` | grows with W1 then W4–W7 | S |
| W4 | Read-only brief query | `wb_brief_query` + host TEMP VIEW tests, isolation | `v2/plugin_brief_query.sql` | W1 | M |
| W5 | TEMP VIEW list/columns | Current-session views only | `v2/plugin_temp_views.sql` (read-only half) | W1, W4 | S |
| W6 | TEMP VIEW create/drop + validator | Conservative token validator + `CREATE VIEW` error capture (no EXPLAIN plan walk); outer CREATE still rejected by `rlm_eval` | `v2/plugin_temp_views.sql` | W5 | M |
| W7 | SQL curator | Delegates create; notes; atomic failure | `v2/plugin_sql_curator.sql` | W6 | M |
| W8 | Tests + docs | Registry/isolation/validator/runtime sequences; README + TEST_REPORT | `v2/test_data_analysis.py`, `v2/README.md`, `v2/TEST_REPORT.md` | W1–W7 | M |

Orchestration batches (status):

- [x] Batch A — W1+W2+W3: core registry, DA prompt wrapper, loaders (0 tools until plugins exist) — 2026-08-22, tests 32/32
- [x] Batch B — W4+W5+W6: `plugin_brief_query` then `plugin_temp_views` (list/columns then create/drop) — 2026-08-22, tests 60/60（附带修复：core 参数类型比对 oidvector 0 起始 off-by-one；make_da_prompt 增加“code 与 final_answer 互斥”规则 0，消除 DeepSeek 填充 code 导致的无法终结退化）
- [x] Batch C — W7+W8: curator, remaining tests/docs, six-tool final gate — 2026-08-22, tests 80/80（curator 委托 create + 8000 上限 + 备注子事务原子性，事件触发器回归覆盖；新增 mock http_call_llm 序列与嵌套 success grounding；README/TEST_REPORT 更新）

The specification below is the implementation-ready design. Work items organize it; they do not replace it.

---


# 1. Summary

Upgrade only v2/database `da_agent` with a session-local workbench plugin surface that is discovered from PostgreSQL function comments and exposed through the existing data-analysis RLM prompt, without routing workbench operations through `jobs`, `worker()`, or `job_handler`. The implementation adds `v2/pg_agent_workbench_core.sql`, three independently loadable plugin files, and a small prompt-wiring change: `make_da_prompt()` remains an immutable static prompt while the existing stable `da_system_prompt()` appends the catalog-rendered workbench tool list, and `rlm_loop()` calls that wrapper instead of calling `make_da_prompt()` directly (`v2/pg_agent_rlm.sql:419-424`; `v2/pg_agent_data_analysis.sql:92-147`). The first plugin is read-only `plugin_brief_query`; session-local TEMP VIEW lifecycle operations follow in `plugin_temp_views`, and curated view creation follows in `plugin_sql_curator`. Existing `da_list_tables()`, `da_show_create()`, and `da_sample()` remain available as legacy non-plugin functions but are removed from the canonical DA prompt because the prior review identified their public-schema-only discovery scope as too narrow (`v2/pg_agent_data_analysis.sql:16-89`; `prompt-exports/oracle-review-2026-08-22-175500-untitled-chat-023cdb-0e13.md`).

# 2. Current-state analysis

## 2.1 Existing runtime responsibilities and ownership

The v2 runtime is split into three SQL layers loaded in order by `v2/setup_db.py:19-24,44-49`:

1. `pg_agent_functional.sql` owns the shared infrastructure:
   - `jobs`, `agent_runs`, and append-only `agent_steps` (`v2/pg_agent_functional.sql:20-54`).
   - Pure prompt/decision functions such as `make_system_prompt()`, `parse_llm_output()`, and `fold_messages()` (`v2/pg_agent_functional.sql:100-205`).
   - The read-only SQL shell `exec_sql_readonly()` (`v2/pg_agent_functional.sql:252-287`).
   - Queue-plugin discovery through `handlers` and `refresh_handlers()` (`v2/pg_agent_functional.sql:299-327`).
   - The asynchronous queue dispatcher `worker()` (`v2/pg_agent_functional.sql:465-497`).

2. `pg_agent_rlm.sql` owns the RLM execution model:
   - Per-run persistent variables in `rlm_vars`.
   - SQL observation and run binding through `rlm_query()` and `rlm_eval()` (`v2/pg_agent_rlm.sql:345-388`).
   - The shared controller `rlm_loop()` (`v2/pg_agent_rlm.sql:395-514`).
   - RLM/CodeAct delegation and queue adapters, which remain outside the workbench scope (`v2/pg_agent_rlm.sql:515-838`).

3. `pg_agent_data_analysis.sql` owns the data-analysis profile:
   - Existing helper functions `da_list_tables()`, `da_show_create()`, and `da_sample()` (`v2/pg_agent_data_analysis.sql:16-89`).
   - The immutable DA prompt `make_da_prompt()` (`v2/pg_agent_data_analysis.sql:92-117`).
   - Observation wrapping and the existing stable `da_system_prompt()` (`v2/pg_agent_data_analysis.sql:119-147`).
   - The public entrypoint `agent_run_data_analysis()` (`v2/pg_agent_data_analysis.sql:149-177`).

The workbench additions must preserve this ownership split. The shared functional layer must not acquire workbench-specific execution logic, and the RLM controller must not acquire one-off branches for individual plugins.

## 2.2 End-to-end DA control flow today

The current DA path is synchronous and remains in the caller’s PostgreSQL backend:

1. `agent_run_data_analysis()` inserts an `agent_runs` row with `paradigm='data_analysis'`, `depth=0`, and `max_depth=0`, binds `rlm.run_id`, stores `question` and optional `context` in `rlm_vars`, and invokes `rlm_loop()` (`v2/pg_agent_data_analysis.sql:149-177`).
2. `rlm_loop()` loads the run, detects the DA paradigm, and currently constructs the system prompt by calling `make_da_prompt()` directly (`v2/pg_agent_rlm.sql:419-424`).
3. It folds prior `agent_steps` into messages, calls `http_call_llm()` through `sql_retry()`, and parses the model’s JSON response (`v2/pg_agent_rlm.sql:430-466`).
4. The returned SQL/code is passed to `rlm_eval()`, which binds the run ID for the duration of the evaluation and routes the submitted text to `exec_sql_readonly()` (`v2/pg_agent_rlm.sql:361-388`).
5. `exec_sql_readonly()` performs lexical checks, rejects multi-statement input and write/utility keywords, and executes the remaining query as a bounded `SELECT` wrapper (`v2/pg_agent_functional.sql:252-287`).
6. DA observations are passed through `da_wrap_obs()`, stored as `last_obs` in `rlm_vars`, and appended to `agent_steps` as a `tool` step (`v2/pg_agent_rlm.sql:487-509`).
7. The runtime gate tracks `v_got_q` and refuses a DA `final_answer` until at least one submitted SQL statement has returned an outer `success=true` observation (`v2/pg_agent_rlm.sql:400-414,468-486`).

The workbench plugin call must therefore be a single SQL expression such as `SELECT wb_brief_query(...)`, executed by `rlm_eval()` in the same backend that owns the TEMP VIEW. It must not enqueue a job.

## 2.3 Existing queue-plugin infrastructure is not the workbench seam

The existing queue plugin contract requires a function of shape `(p_job jobs) RETURNS void`, with registration encoded by `COMMENT {"job_handler": ...}` and discovered by `refresh_handlers()` (`v2/pg_agent_functional.sql:299-327`). `worker()` claims jobs with `FOR UPDATE SKIP LOCKED`, looks up `handlers.fn`, and invokes the handler in the worker backend (`v2/pg_agent_functional.sql:465-497`).

That mechanism remains valid for asynchronous jobs, including the existing RLM and hybrid queue adapters (`v2/pg_agent_rlm.sql:805-838`), but it cannot own session-local workbench state. A TEMP VIEW created by `worker()` would belong to the worker backend rather than the backend running `agent_run_data_analysis()` (`v2/pg_agent_functional.sql:465-497`; `v2/pg_agent_data_analysis.sql:149-177`). Workbench functions must therefore use a separate registry and direct `SELECT` invocation.

The v1 `llm_tool` scan is a useful metadata precedent: `w_tools()` scans PostgreSQL function comments and renders a Markdown tool list (`v1/pg_agent_poml.sql:263-283`). The new workbench registry reuses that catalog-comment pattern but must not reuse `handlers` or the `job_handler` key.

## 2.4 Existing restrictions and extension points

The relevant hard constraints are:

- `exec_sql_readonly()` rejects `create`, `set`, `execute`, `call`, `do`, DML, and other utility keywords in the submitted statement (`v2/pg_agent_functional.sql:252-287`).
- A function call such as `SELECT wb_temp_view_create(...)` can pass the outer lexical check because the submitted statement contains a `SELECT` and the function name is not a standalone `create` token; the function must independently validate its SQL argument. This is consistent with the existing `da_sample()` precedent, which performs dynamic SQL inside a `SELECT`-callable function (`v2/pg_agent_data_analysis.sql:62-89`).
- The DA prompt is currently immutable and hardcodes both the SQL API and `da_*` shortcuts (`v2/pg_agent_data_analysis.sql:92-117`).
- `da_system_prompt()` already provides a stable run-aware wrapper but is currently used only by tests; `rlm_loop()` calls `make_da_prompt()` directly (`v2/pg_agent_data_analysis.sql:138-147`; `v2/pg_agent_rlm.sql:419-424`).
- The existing test harness hardcodes the three SQL files in `SQL_FILES` and reloads them before testing (`v2/test_data_analysis.py:19-25`), while `setup_db.py` performs the normal deployment load (`v2/setup_db.py:19-24,44-49`).

These are the extension points. No second RLM loop, no second SQL executor, and no new run-state table are required.

# 3. Design

## 3.1 Workbench boundary and non-goals

### In scope

The workbench plugin system will provide:

- Catalog-based discovery of SELECT-callable PostgreSQL functions.
- Prompt rendering for installed workbench tools.
- Current-session TEMP VIEW inspection.
- A bounded read-only preview of one current-session TEMP VIEW.
- Explicitly named, validated TEMP VIEW lifecycle operations.
- A curated-view wrapper that adds session-local metadata.
- PostgreSQL table-backed workbench data only.

### Out of scope

The following remain unchanged:

- `jobs`, `handlers`, `refresh_handlers()`, and `worker()` (`v2/pg_agent_functional.sql:299-327,465-497`).
- v1 SQL files and v1 databases (`v1/pg_agent_fixed.sql:109-119`; `v1/pg_agent_functional.sql:285-470`).
- CSV, JSON-file, filesystem, or external object-store ingestion.
- RLM delegation, hybrid behavior, SSE, or protocol compatibility outside the existing v2 DA path (`v2/pg_agent_rlm.sql:515-838`).
- The existing `agent_runs`, `agent_steps`, and `rlm_vars` schema.

A plugin may define several related tools in one SQL file, but all tools in that file must share one plugin identifier and one clearly bounded capability.

## 3.2 `workbench_core`: registry and shared session-resolution contract

### File and ownership

Create `v2/pg_agent_workbench_core.sql`. It is loaded after `pg_agent_rlm.sql` and before `pg_agent_data_analysis.sql` and the plugin files (`v2/setup_db.py:19-24`).

The core file owns:

1. The persistent registry table.
2. Catalog-comment validation and refresh.
3. Prompt rendering.
4. Shared TEMP VIEW identifier validation and current-session resolution helpers.

It does not own a specific workbench tool and does not execute arbitrary user SQL.

### Registry table

Define the following persistent table shape:

```text
workbench_tools
├── tool_name       text PRIMARY KEY
├── plugin_name     text NOT NULL
├── fn              regprocedure NOT NULL
├── metadata        jsonb NOT NULL
└── refreshed_at    timestamptz NOT NULL DEFAULT now()
```

Semantics:

- `tool_name` is the callable PostgreSQL function name and is globally unique within the database.
- `plugin_name` identifies the SQL plugin file/module that owns the tool.
- `fn` stores the full function identity, including argument types; use `regprocedure`, not `regproc`, so the registry names a specific signature and does not follow a same-name replacement to a different OID. Overloads are still forbidden at refresh (`tool_name` = `proname` is unique).
- `metadata` stores the validated full JSON comment.
- `refreshed_at` identifies when the registry row was generated, not when the tool was invoked.
- The registry is deployment state, not per-agent-run state. It must not contain `run_id` or TEMP VIEW data.

v2 currently runs as a single embedded role (`server.py` / `v2/setup_db.py` manage no extra GRANT/ROLE). Do not invent a GRANT in this increment. If a future multi-role deployment appears, grant `SELECT` on `workbench_tools` to the DA executor then. Registry metadata contains only function signatures, descriptions, and capability declarations; it must not contain row data or secrets.

### Internal TEMP VIEW helpers

The core file should define underscore-prefixed, non-registered helpers so all plugins apply exactly the same identifier policy:

```text
_wb_normalize_temp_view_name(p_name text) RETURNS text
_wb_temp_view_oid(p_name text) RETURNS oid
_wb_temp_view_columns(p_relid oid) RETURNS jsonb
```

Required behavior:

- `_wb_normalize_temp_view_name()` trims surrounding whitespace and accepts only ASCII identifiers matching `[A-Za-z_][A-Za-z0-9_]*`.
- Reject names longer than PostgreSQL’s effective identifier length of 63 bytes so the name used for lookup cannot differ from the name created by PostgreSQL.
- Return `NULL` for empty, dotted, quoted, schema-qualified, or otherwise invalid names.
- `_wb_temp_view_oid()` resolves only a relation whose namespace equals `pg_my_temp_schema()` and whose `relkind` is a regular view (`'v'`).
- If the session has never created a temp object, `pg_my_temp_schema()` returns `0`; treat that as “no TEMP VIEW namespace” and return NULL / empty list. Do not special-case OID 0 as a real schema.
- It must not resolve permanent `public` views, temporary tables, materialized views, foreign tables, or any relation in another schema.
- `_wb_temp_view_columns()` returns columns ordered by `attnum`, excluding dropped attributes, with at least `ordinal`, `name`, and PostgreSQL display type from `format_type(atttypid, atttypmod)`.

The chosen API policy is **`pg_my_temp_schema()` only**. An external caller cannot pass `pg_temp.foo`; every plugin view-name argument is an unqualified name. This narrow policy prevents schema-qualified input from becoming a second parsing and authorization path. SQL text supplied to a create/curate operation may still contain ordinary PostgreSQL references, including `pg_temp` references, because those are part of the submitted query rather than the plugin’s object-resolution parameter.

### Comment metadata contract

Every registered workbench function must have a JSON comment with this shape:

```json
{
  "workbench_plugin": "plugin_<lowercase_slug>",
  "llm_tool": {
    "name": "wb_<function_name>",
    "description": "One-line description",
    "args": {
      "p_argument": "text"
    },
    "returns": "jsonb",
    "session_scope": "current_session",
    "capability": "read_only"
  }
}
```

Rules:

- `workbench_plugin` is a non-empty string matching `plugin_[a-z][a-z0-9_]*`.
- `llm_tool.name` must equal the PostgreSQL function’s `proname`.
- `description` must be one line, non-empty, and bounded to a reasonable catalog/prompt size; reject embedded control characters and newlines.
- `args` is an object whose keys exactly match the named input arguments. Values are the PostgreSQL type names used by the function. Defaults are taken from PostgreSQL’s catalog signature when rendered and are not duplicated in the metadata map.
- `returns` must be exactly `jsonb`. This keeps all tool results on the same serialization path.
- `session_scope` must be `current_session`.
- `capability` must be one of:
  - `read_only`
  - `temp_view_mutation`
- A workbench comment must not contain `job_handler`. If both keys are present, `refresh_workbench_tools()` must fail rather than silently creating two different interpretations of the function.
- Registered functions must be public-schema ordinary functions (`prokind='f'`), not procedures, aggregates, or window functions, and must return `jsonb`.
- Workbench functions must not be tagged with `job_handler`; this keeps the queue registry and the workbench registry disjoint (`v2/pg_agent_functional.sql:309-327`).

### `refresh_workbench_tools()`

Signature:

```text
refresh_workbench_tools() RETURNS integer
```

Behavior:

1. Scan `pg_proc` in the `public` schema, using `obj_description(p.oid, 'pg_proc')` in the same catalog-oriented style as `refresh_handlers()` (`v2/pg_agent_functional.sql:309-327`).
2. Select functions whose comment is a JSON object containing `workbench_plugin`.
3. Parse and validate the full metadata contract above.
4. Verify the function’s return type, callable kind, argument names/types, tool name, plugin identifier, and capability.
5. Reject:
   - malformed JSON;
   - missing `llm_tool`;
   - duplicate `tool_name`;
   - duplicate or mismatched argument metadata;
   - a `job_handler` key;
   - unsupported capability or session scope;
   - a non-`jsonb` return type.
6. Rebuild `workbench_tools` from the validated candidate set using `TRUNCATE workbench_tools` then `INSERT`, matching `refresh_handlers()` (`v2/pg_agent_functional.sql:315`). `TRUNCATE` takes `ACCESS EXCLUSIVE` and is transaction-rollbackable, which is what makes concurrent refreshes serialize and failed refresh restore the prior table.
7. Return the inserted row count.

The rebuild must be statement-atomic: validate the full candidate set **before** TRUNCATE, or run TRUNCATE+INSERT in one function so any exception rolls back both. If validation or insertion fails, the previous registry contents must remain available after the failed call is rolled back. Do not implement “last duplicate wins”; duplicate tool names are an installation error. Do not use `DELETE`+`INSERT` without an exclusive lock.

Repeated refreshes with unchanged function comments must produce the same rows and count. A plugin author must run refresh after adding, replacing, or removing a plugin function. The registry does not have a foreign key to `pg_proc`, so a dropped function can leave stale metadata until refresh; the renderer must omit registry rows whose function OID no longer resolves.

### `render_workbench_tools()`

Signature:

```text
render_workbench_tools() RETURNS text
```

Properties:

- `STABLE`, because it reads `workbench_tools` and `pg_proc`.
- Does not invoke registered functions.
- Renders only live registry rows.
- Orders read-only tools before mutation tools, then by `plugin_name` and `tool_name`. This makes the read-only `plugin_brief_query` surface appear before TEMP VIEW mutation tools.
- Uses the actual PostgreSQL function signature from `pg_get_function_arguments()` so defaults and argument names reflect the callable function.
- Uses validated metadata only for the description and capability label.

The rendered section must explicitly tell the model:

- All listed calls are SQL functions invoked as one `SELECT`.
- `exec_sql_readonly()` wraps that SELECT; the observation envelope is `{success, data:[{<function_name>: <plugin jsonb>}], row_count}`. Inspect the **nested** plugin object for `success` / `Type` / `Problem`; an outer `success: true` can wrap a nested workbench error.
- Tools operate in the current PostgreSQL session.
- `read_only` tools cannot alter workbench state.
- `temp_view_mutation` tools may change only current-session `pg_temp`.
- Arbitrary `CREATE`, `DROP`, `ALTER`, DML, or multi-statement SQL remains forbidden.

With no registered tools, return a stable “no workbench tools installed” section rather than an empty string; this makes prompt behavior inspectable and avoids implying that an unlisted tool exists.

## 3.3 DA prompt integration

### Static prompt

Keep the `make_da_prompt(p_max_rows int)` signature and `IMMUTABLE` volatility (`v2/pg_agent_data_analysis.sql:92-117`). Its static content must continue to include:

- The strict RLM JSON protocol.
- The one-`SELECT`/`WITH`-per-round rule.
- The successful-query-before-finalization rule.
- `information_schema.tables`, `information_schema.columns`, and `pg_catalog` as the primary discovery path.
- The prohibition on arbitrary write/DDL SQL and delegation.

Remove the “optional shortcuts” instruction that advertises `da_list_tables()`, `da_show_create()`, and `da_sample()`. This preserves the function signatures while ensuring the canonical agent contract does not prefer the public-schema-only helpers criticized by the prior review (`v2/pg_agent_data_analysis.sql:92-117`; `prompt-exports/oracle-review-2026-08-22-175500-untitled-chat-023cdb-0e13.md`).

### Stable wrapper

Repurpose the existing `da_system_prompt(p_run_id text)` (`v2/pg_agent_data_analysis.sql:138-147`) as the live runtime wrapper:

1. Read `max_rows` from the specified `agent_runs` row.
2. Raise the existing “run does not exist” error when the ID is unknown.
3. Build the immutable static body through `make_da_prompt(max_rows)`.
4. Append `render_workbench_tools()`.
5. Return the combined prompt.

This avoids adding another wrapper and gives the already-tested function a real runtime role.

### RLM controller wiring

Change only the DA prompt construction inside `rlm_loop()`:

- Current behavior at `v2/pg_agent_rlm.sql:419-424`: DA runs call `make_da_prompt(...)` directly.
- Required behavior: DA runs call `da_system_prompt(p_run_id)`.

No plugin-specific branch may be added to `rlm_loop()`. The existing per-step controller, `rlm_eval()` path, observation wrapping, `last_obs` storage, step emission, and `v_got_q` finalization gate remain shared (`v2/pg_agent_rlm.sql:395-514`).

Non-DA RLM and hybrid prompts remain unchanged. Workbench tools must not be appended to `make_rlm_prompt()` or `make_hybrid_prompt()` (`v2/pg_agent_rlm.sql:63-129`).

## 3.4 Explicit plugin development standard

A later author adding `plugin_<slug>.sql` must follow this contract.

### File rules

- File path: `v2/plugin_<slug>.sql`.
- File contains only PostgreSQL definitions for one plugin capability.
- File must be idempotent under repeated loading: use replace/create-if-not-exists patterns consistent with the existing v2 SQL files.
- File must not alter `rlm_loop()`, `exec_sql_readonly()`, `worker()`, `handlers`, or `agent_runs`.
- File must not create a `jobs` handler or use `COMMENT {"job_handler": ...}`.
- File must declare each LLM-visible function’s `COMMENT` in the same file as its definition.
- File must state its dependency position in a header comment and be loaded after `workbench_core`.
- Every exposed function must return `jsonb` and use one of the two approved capability values.
- Every identifier supplied by a caller must be validated before interpolation, and every identifier inserted into dynamic SQL must use identifier quoting equivalent to `format('%I', ...)`.
- User-provided SQL must never be concatenated as an identifier or comment literal.
- Functions should be `SECURITY INVOKER`; no plugin may use `SECURITY DEFINER` without a separately reviewed privilege boundary.
- No plugin may read CSV/JSON files or filesystem paths.

### Installation protocol

For each plugin:

1. Load the plugin SQL after its declared dependencies.
2. Run `SELECT refresh_workbench_tools()`.
3. Assert that the expected tools appear exactly once.
4. Test direct `SELECT` calls in the same connection that owns any TEMP VIEW fixtures.
5. Test that the plugin does not appear in `handlers` after `refresh_handlers()` (`v2/pg_agent_functional.sql:309-327`).
6. Update the v2 loader and tests if the plugin is part of the default `da_agent` distribution.
7. Do not edit `rlm_loop()`.

### Tool result standard

Success results must contain:

```json
{
  "success": true,
  "...": "operation-specific fields"
}
```

Expected validation, missing-object, and execution failures must contain:

```json
{
  "success": false,
  "Type": "WORKBENCH_ERROR",
  "Phase": "Validation|Resolution|Execution",
  "Problem": "specific failure",
  "Solution": "actionable recovery"
}
```

The result must not expose stack traces, SQL credentials, or unbounded row data.

## 3.5 `plugin_brief_query.sql`

### Purpose and ownership

Create `v2/plugin_brief_query.sql`. It is the first user-facing plugin and must be read-only. It depends only on `workbench_core`.

### Public function

```text
wb_brief_query(
    p_view  text,
    p_limit integer DEFAULT 20
) RETURNS jsonb
```

Function properties:

- `STABLE`.
- `SECURITY INVOKER`.
- Registered with `workbench_plugin = "plugin_brief_query"`.
- Capability `read_only`.
- Executes only against the current backend’s TEMP VIEW namespace.

### Input rules

- Normalize `p_view` with `_wb_normalize_temp_view_name()`.
- Return a structured validation error for null, empty, dotted, quoted, overlong, or malformed names.
- Accept `p_limit` default 20. An explicit SQL `NULL` for `p_limit` uses the same default 20 (PostgreSQL default argument behavior); do not treat NULL as a validation error.
- Require `1 <= p_limit <= 50` after defaulting; return a validation error for zero, negative, or larger values. The upper bound aligns with the existing DA/SQL result budget (`v2/pg_agent_functional.sql:252-287`; `v2/pg_agent_data_analysis.sql:92-117`).

### Algorithm

1. Resolve the normalized name through `_wb_temp_view_oid()`.
2. If no current-session regular TEMP VIEW exists, return a resolution error.
3. Read its ordered column metadata through `_wb_temp_view_columns()`.
4. Execute a dynamically built, fully qualified query against that resolved TEMP VIEW, selecting at most `p_limit + 1` rows.
5. Convert each row to JSONB.
6. Return only the first `p_limit` rows.
7. Set `truncated=true` if the extra probe row existed; otherwise set it to `false`.

Success shape:

```json
{
  "success": true,
  "view": "sales_view",
  "columns": [
    {"ordinal": 1, "name": "month", "type": "text"},
    {"ordinal": 2, "name": "revenue", "type": "integer"}
  ],
  "data": [
    {"month": "2025-01", "revenue": 100}
  ],
  "row_count": 1,
  "truncated": false
}
```

`row_count` is the number of returned preview rows, not the total number of rows in the view. The function must not perform an unbounded count.

### Edge behavior

- Empty view: success with columns, `data=[]`, `row_count=0`, `truncated=false`.
- Temporary table with the requested name: resolution failure because only `relkind='v'` is accepted.
- Permanent view with the requested name: resolution failure because only `pg_my_temp_schema()` is searched.
- JSON conversion failure for an unsupported value: execution error with no partial result.
- The function must not mutate the view, `agent_runs`, `rlm_vars`, or any permanent table.

## 3.6 `plugin_temp_views.sql`

### Purpose and incrementing order

Create `v2/plugin_temp_views.sql` after `plugin_brief_query.sql`. Develop and verify the read-only list/column operations first; only then enable the create/drop operations in the same plugin increment. The prompt renderer must order read-only tools before mutation tools regardless of catalog creation order.

All functions in this file use the shared core identifier and namespace helpers.

### `wb_temp_view_list()`

```text
wb_temp_view_list() RETURNS jsonb
```

Properties:

- `STABLE`, `SECURITY INVOKER`, capability `read_only`.
- Lists only regular views in `pg_my_temp_schema()`.
- Orders names alphabetically.
- Returns view name, column count, optional view note, and no row data.

Shape:

```json
{
  "success": true,
  "views": [
    {"view": "sales_view", "column_count": 4, "note": null}
  ]
}
```

The function must return an empty array for a connection with no TEMP VIEWs.

### `wb_temp_view_columns(text)`

```text
wb_temp_view_columns(
    p_view text
) RETURNS jsonb
```

Properties:

- `STABLE`, `SECURITY INVOKER`, capability `read_only`.
- Uses the same name validation and current-session resolution as `wb_brief_query()`.
- Returns the ordered column metadata without reading any rows.

Shape:

```json
{
  "success": true,
  "view": "sales_view",
  "columns": [
    {"ordinal": 1, "name": "month", "type": "text"},
    {"ordinal": 2, "name": "revenue", "type": "integer"}
  ]
}
```

### `wb_temp_view_create(text, text, boolean)`

```text
wb_temp_view_create(
    p_view       text,
    p_select_sql text,
    p_replace    boolean DEFAULT true
) RETURNS jsonb
```

Properties:

- `VOLATILE`, `SECURITY INVOKER`, capability `temp_view_mutation`.
- Creates or replaces a TEMP VIEW in the current session only.
- Does not use `CASCADE`.
- Does not update `workbench_tools` or any permanent table.
- Does not auto-drop the view at the end of an agent run; TEMP VIEW lifetime is the connection’s responsibility.

#### Inner SQL validator

The function must validate `p_select_sql` independently of `exec_sql_readonly()`. The outer blacklist is not a sufficient validator because a `SELECT` function call can contain dynamic SQL internally (`v2/pg_agent_functional.sql:252-287`; `v2/pg_agent_data_analysis.sql:62-89`).

The validator must:

1. Reject null, empty, NUL-containing, and overlong SQL. Use a maximum of 16,000 characters for the general lifecycle function.
2. Reject any semicolon, including one inside a string literal. This is intentionally conservative and guarantees one statement.
3. Reject SQL comment markers `--`, `/*`, and `*/` to avoid lexical keyword hiding. This introduces safe false positives but simplifies the validator’s threat model.
4. Require the first token to be exactly `SELECT` or `WITH`.
5. Reject standalone utility/DML tokens including, at minimum, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `GRANT`, `REVOKE`, `COPY`, `EXECUTE`, `CALL`, `DO`, `VACUUM`, `ANALYZE`, `REINDEX`, `CLUSTER`, `DISCARD`, `LOCK`, `SET`, `RESET`, `LOAD`, `LISTEN`, `NOTIFY`, `UNLISTEN`, `INTO`, and `FOR`.
6. After the token checks, run `CREATE [OR REPLACE] TEMP VIEW … AS <sql>` and map PostgreSQL’s own view-definition errors (including data-modifying `WITH` and `SELECT INTO`, which `CREATE VIEW` already rejects) to `Phase=Validation` structured JSON. Do **not** add a separate `EXPLAIN` plan-walk: it is redundant with `CREATE VIEW`, and `EXPLAIN` without `ANALYZE` can still evaluate `IMMUTABLE` functions.
7. Perform token checks and DDL in one exception boundary so a failure leaves the previous view unchanged when replacement fails.

This is a conservative SQL hygiene layer, not a complete function-purity sandbox. A permitted `SELECT` can still call a user-defined volatile function if the invoking role has permission. The plugin must remain `SECURITY INVOKER`, and deployment must not treat it as a privilege-escalation boundary.

#### Create semantics

- Invalid name or SQL: structured validation error.
- Existing TEMP VIEW and `p_replace=false`: structured resolution/conflict error; existing view remains.
- Existing TEMP VIEW and `p_replace=true`: attempt `CREATE OR REPLACE TEMP VIEW`.
- Existing TEMP TABLE or other TEMP relation: reject; do not drop or replace it.
- Same name in permanent schema only: create the TEMP VIEW; the permanent relation is not modified.
- Replacement that changes incompatible view columns/types: return the PostgreSQL error as a bounded execution error and preserve the previous view.
- Success returns the normalized name, whether replacement occurred, and the resulting columns.

Illustrative success shape:

```json
{
  "success": true,
  "view": "sales_summary",
  "replaced": false,
  "columns": [
    {"ordinal": 1, "name": "segment", "type": "text"},
    {"ordinal": 2, "name": "revenue", "type": "bigint"}
  ]
}
```

### `wb_temp_view_drop(text)`

```text
wb_temp_view_drop(
    p_view text
) RETURNS jsonb
```

Properties:

- `VOLATILE`, `SECURITY INVOKER`, capability `temp_view_mutation`.
- Resolves only the current session’s TEMP VIEW.
- Uses `DROP VIEW` without `CASCADE`.
- Returns a structured error for malformed or missing names.
- Dependency errors are returned without removing dependent objects.
- Repeated drops are not silently treated as success; a missing view is a resolution error so the model can distinguish an already-clean state from a failed requested operation.

Success shape:

```json
{
  "success": true,
  "view": "sales_summary",
  "dropped": true
}
```

## 3.7 `plugin_sql_curator.sql`

### Purpose

Create `v2/plugin_sql_curator.sql` after `plugin_temp_views.sql`. This plugin provides a higher-level, documented way to define or replace a named curated TEMP VIEW.

### Public function

```text
wb_sql_curate(
    p_view       text,
    p_select_sql text,
    p_note       text DEFAULT NULL
) RETURNS jsonb
```

Properties:

- `VOLATILE`, `SECURITY INVOKER`, capability `temp_view_mutation`.
- Always uses controlled replacement semantics; there is no caller-facing `p_replace` flag.
- Delegates common view creation and SQL validation to `wb_temp_view_create()` rather than duplicating the validator.
- Applies a stricter 8,000-character SQL limit for curated definitions.
- Rejects a note longer than 1,000 characters or containing NUL characters.
- Treats null or whitespace-only notes as **clear the note**. A repeated `wb_sql_curate` without `p_note` is a full restatement: it replaces the view and clears documentation. There is no “omit to keep previous note” mode on this signature.
- Stores the note as a PostgreSQL comment on the current-session TEMP VIEW. The comment is session-scoped with the view and is returned by `wb_temp_view_list()`.
- Atomicity mechanism: wrap `wb_temp_view_create(...)` plus `COMMENT ON VIEW` in a PL/pgSQL block that uses a `SAVEPOINT` (or an inner `BEGIN … EXCEPTION` subtransaction). If create returns `success=false` jsonb, return that object (no DDL happened). If create succeeds and note application then fails, `ROLLBACK TO SAVEPOINT` / re-raise so the replaced view does not remain; catch at the outer function and return structured `WORKBENCH_ERROR`. Do not rely on create’s jsonb error return to undo DDL it already committed inside its own swallowed exception path — if `wb_temp_view_create` swallows errors as jsonb, curator must only apply the note after a `success=true` result **and** still hold a savepoint around both the create SQL and the comment so a later failure undoes the view.

Success shape:

```json
{
  "success": true,
  "view": "sales_summary",
  "replaced": true,
  "note": "Monthly revenue by segment",
  "columns": [
    {"ordinal": 1, "name": "segment", "type": "text"},
    {"ordinal": 2, "name": "revenue", "type": "bigint"}
  ]
}
```

The curator does not materialize rows into a permanent table and does not ingest external files. It defines a lazy TEMP VIEW over PostgreSQL relations.

## 3.8 Resolution of the existing `da_*` helper question

**Decision: retain the existing helpers as legacy non-plugin functions, but stop advertising them as prompt shortcuts. Do not migrate them into `workbench_plugin` comments in this increment.**

Rationale:

- Removing them would break the existing direct-call tests and any callers using their stable signatures (`v2/test_data_analysis.py:F2`; `v2/pg_agent_data_analysis.sql:26-89`).
- Registering them now would preserve their narrow public-schema/plain-table behavior as the official workbench contract, which is the exact scope problem identified by the prior oracle review (`prompt-exports/oracle-review-2026-08-22-175500-untitled-chat-023cdb-0e13.md`).
- The canonical DA prompt already has the correct extensibility point—ordinary `information_schema`/`pg_catalog` queries through `rlm_eval()`—and should use that rather than adding more fixed shortcuts (`v2/pg_agent_data_analysis.sql:92-117`; `v2/pg_agent_rlm.sql:361-388`).
- A later plugin may provide privilege-aware schema/relation introspection with a broader, explicitly documented scope. That later migration is not part of this work.

The functions remain callable for compatibility, but none receives `workbench_plugin` metadata and none appears in `render_workbench_tools()`.

## 3.9 State and data flow

### Plugin installation flow

```text
plugin_*.sql
  → public function definitions
  → COMMENT metadata in pg_proc
  → refresh_workbench_tools()
  → workbench_tools rows
  → render_workbench_tools()
  → da_system_prompt(run_id)
  → rlm_loop() system message
```

All catalog and registry operations occur in the deployment connection. A refresh after a plugin file is loaded is required before a new DA run sees the tool.

Duplicate metadata or out-of-order installation fails at refresh rather than producing an ambiguous prompt. Repeated refreshes are idempotent.

### Tool invocation flow

```text
LLM JSON code
  → rlm_eval(run_id, code)
  → exec_sql_readonly(code, max_rows)
  → one SELECT expression invoking wb_*
  → plugin function in the same backend
  → current pg_my_temp_schema()
  → bounded JSONB result
  → outer exec_sql_readonly observation
  → da_wrap_obs()
  → rlm_vars.last_obs
  → agent_steps(kind='tool')
  → next fold_rlm_messages()
```

The LLM does not call `workbench_tools.fn` through a dispatcher. The registry is a prompt inventory and validation catalog; PostgreSQL resolves the actual function call from the SQL emitted by the model.

### TEMP VIEW lifecycle

- TEMP VIEWs are owned by the current backend and survive across multiple agent runs on that same connection until explicitly dropped or the connection ends.
- `agent_run_data_analysis()` must not automatically drop them because the workbench is intended to support a persistent SQL REPL/session (`v2/pg_agent_data_analysis.sql:149-177`; `v2/pg_agent_rlm.sql:63-88`).
- A connection pool must explicitly clear workbench TEMP VIEWs when a logical user session ends; otherwise a later logical user on the same backend can see them.
- `rlm.run_id` remains run-scoped and is restored by the existing entrypoint/`rlm_eval()` logic; it is not used as the TEMP VIEW ownership key (`v2/pg_agent_rlm.sql:361-388`; `v2/pg_agent_data_analysis.sql:149-177`).

### Out-of-order, duplicate, and dropped events

- A plugin installed without a refresh is not visible in the prompt; manual direct calls may still work if the caller knows the function name.
- A refresh while a run is already active does not update that run’s already-built `v_system`; the next run sees the refreshed registry.
- A function dropped without refresh is omitted by the renderer when its OID no longer resolves, but the stale row remains until refresh.
- A repeated `wb_temp_view_create(..., true)` is an intentional idempotent replacement.
- A repeated create with `p_replace=false` returns a conflict.
- A repeated drop returns a missing-view error.
- If a tool observation is clipped by `rlm_loop()`, the existing `last_obs` variable retains the full JSON observation while the step payload contains the bounded text (`v2/pg_agent_rlm.sql:487-509`).
- No plugin-level deduplication is added to `agent_steps`; the existing append-only event model remains authoritative (`v2/pg_agent_functional.sql:44-54,219-229`).

## 3.10 Concurrency, isolation, and lifecycle

- All workbench calls are synchronous and execute in the caller’s PostgreSQL backend through `rlm_eval()` (`v2/pg_agent_rlm.sql:361-388`).
- Registry refresh is deployment-time global state. Concurrent refreshes serialize on the registry table lock; deployment should not refresh while DA runs are being used.
- `render_workbench_tools()` reads one catalog/registry snapshot per prompt construction. It must not cache across runs.
- TEMP VIEW creation/drop is transactionally protected by PostgreSQL DDL semantics. A caught validation or DDL failure must not leave a partially created or partially replaced view.
- `statement_timeout` and cancellation follow the existing `rlm_eval()`/`exec_sql_readonly()` error path (`v2/pg_agent_rlm.sql:361-388`; `v2/pg_agent_functional.sql:252-287`). If cancellation aborts the enclosing transaction, the caller must roll back before issuing further commands.
- The functions do not create background workers, sockets, files, or permanent rows.
- A long-running query inside a view remains subject to the caller’s `statement_timeout`; the brief plugin bounds result rows but does not guarantee bounded query execution time.

## 3.11 Error handling and edge cases

| Operation | Failure | Required behavior |
|---|---|---|
| Registry refresh | Malformed comment JSON | Abort refresh; preserve previous registry; report function identity and metadata problem. |
| Registry refresh | Duplicate tool name | Abort; no last-wins behavior. |
| Registry refresh | Wrong return type or unsupported capability | Abort; function is not registered. |
| Registry render | Stale dropped function | Omit stale row; deployment must refresh. |
| Brief query | Invalid or schema-qualified view name | `WORKBENCH_ERROR`, `Validation`. |
| Brief query | Missing/non-view relation | `WORKBENCH_ERROR`, `Resolution`. |
| Brief query | Empty view | Success with columns and zero rows. |
| Brief query | Row JSON conversion failure | `WORKBENCH_ERROR`, `Execution`; no partial result. |
| Temp create | SQL is not a single SELECT/WITH | Reject before DDL. |
| Temp create | DML CTE or utility plan | Reject after planning-only validation. |
| Temp create | Existing relation is not a view | Reject without dropping it. |
| Temp create | Incompatible `CREATE OR REPLACE` | Return execution error and preserve old view. |
| Temp drop | Dependency prevents restricted drop | Return execution error; do not use CASCADE. |
| Curator | Note too long or contains NUL | Reject before changing the view. |
| Outer RLM call | `exec_sql_readonly` false-positive keyword match inside the submitted SQL text | Existing outer executor returns an SQL error; the plugin is not invoked. Prompt/test documentation must acknowledge this limitation (`v2/pg_agent_functional.sql:252-287`). |
| DA finalization | Model answers before any outer successful SQL observation | Existing `v_got_q` feedback path continues the loop and prevents a final step (`v2/pg_agent_rlm.sql:468-486`). |

The runtime gate measures successful outer SQL execution, not whether a nested JSONB result has `"success": true`. A plugin that returns a structured “missing view” JSONB result has still executed a valid SQL function call; the prompt must instruct the model to inspect the nested result before claiming data-derived conclusions.

## 3.12 Persistence and serialization

### Persistent additions

Only the following persistent object is added:

```text
workbench_tools
```

It is additive and generated from function comments. No existing `agent_runs`, `agent_steps`, `rlm_vars`, or `jobs` columns change (`v2/pg_agent_functional.sql:20-54`; `v2/pg_agent_rlm.sql:20-46`).

Plugin functions and their comments are persistent PostgreSQL catalog objects. The registry must be refreshed after catalog changes.

### Session-only additions

TEMP VIEWs and their PostgreSQL comments are session-local. They are not migrated, backed up as workbench data, or shared between connections.

### Existing data migration

No row migration is required. Existing databases should receive the new SQL files in this order:

```text
pg_agent_functional.sql
pg_agent_rlm.sql
pg_agent_workbench_core.sql
pg_agent_data_analysis.sql
plugin_brief_query.sql
plugin_temp_views.sql
plugin_sql_curator.sql
SELECT refresh_workbench_tools()
```

`setup_db.py` currently recreates `da_agent` from scratch (`v2/setup_db.py:36-49`), so CI/test installation is naturally clean. For an existing database, the same files are idempotent and should be applied with `ON_ERROR_STOP=1`.

### Rollback

Rollback must occur in the reverse dependency order:

1. Stop new DA runs.
2. Drop or remove the plugin functions.
3. Refresh the workbench registry.
4. Revert `rlm_loop()` to call the static prompt or retain `da_system_prompt()` only while the core function exists.
5. Drop `workbench_tools` and core helpers if the feature is being fully removed.

The old `make_da_prompt()` signature remains compatible, so a partial rollback can preserve basic DA behavior even if no workbench tools are installed.

## 3.13 Tradeoffs and rationale

- **Separate registry instead of `handlers`:** preserves the existing async queue contract and prevents session-local TEMP VIEWs from being created in the wrong backend (`v2/pg_agent_functional.sql:299-327,465-497`).
- **Stable wrapper instead of changing `make_da_prompt()` volatility:** keeps the pure/static prompt testable and prevents catalog state from being mislabeled immutable (`v2/pg_agent_data_analysis.sql:92-147`).
- **Registry inventory instead of dynamic function dispatch:** the model already emits SQL and `rlm_eval()` already executes it; a second dispatcher would add indirection without solving session affinity (`v2/pg_agent_rlm.sql:361-388`).
- **`pg_my_temp_schema()` only:** reduces identifier parsing and prevents callers from asking the plugin to resolve arbitrary schemas.
- **Read-only first plugin:** validates catalog discovery, prompt rendering, same-session behavior, and bounded JSON serialization before introducing a controlled DDL escape through `SELECT` (`v2/pg_agent_functional.sql:252-287`).
- **Retaining but de-advertising `da_*`:** avoids a breaking API change while preventing narrow legacy helpers from becoming the new workbench contract.
- **Conservative SQL validator:** accepts safe common cases at the cost of rejecting semicolons/comments and some literals that would be harmless. This is preferable to treating the outer keyword blacklist as a complete safety boundary.

# 4. File-by-file impact

## New: `v2/pg_agent_workbench_core.sql`

- Add `workbench_tools`.
- Add `_wb_normalize_temp_view_name()`, `_wb_temp_view_oid()`, and `_wb_temp_view_columns()`.
- Add `refresh_workbench_tools()` and `render_workbench_tools()`.
- Add validation for `workbench_plugin`/`llm_tool` metadata and reject `job_handler` overlap.
- Why: existing `refresh_handlers()` provides catalog-scan precedent but has the wrong function contract and queue/session semantics (`v2/pg_agent_functional.sql:299-327,465-497`).
- Dependency: requires the base PostgreSQL catalog and v2 functional/RLM schema; must load before `pg_agent_data_analysis.sql` and all plugin files.

## New: `v2/plugin_brief_query.sql`

- Add `wb_brief_query(text, integer) RETURNS jsonb`.
- Add its `workbench_plugin` and `llm_tool` comment.
- Why: first plugin must be read-only and operate on a host-created TEMP VIEW before mutation capability is introduced.
- Dependency: requires `pg_agent_workbench_core.sql`.

## New: `v2/plugin_temp_views.sql`

- Add `wb_temp_view_list()`.
- Add `wb_temp_view_columns(text)`.
- Add `wb_temp_view_create(text,text,boolean)`.
- Add `wb_temp_view_drop(text)`.
- Add the shared inner SELECT/WITH validation path and the four tool comments.
- Why: owns current-session TEMP VIEW lifecycle and is the only plugin allowed to expose controlled TEMP VIEW mutation.
- Dependency: requires `pg_agent_workbench_core.sql`; may reuse the core resolver and must be loaded after `plugin_brief_query.sql` for the declared increment order.

## New: `v2/plugin_sql_curator.sql`

- Add `wb_sql_curate(text,text,text) RETURNS jsonb`.
- Add its workbench metadata comment.
- Add note validation and session-local TEMP VIEW comment handling.
- Why: provides a higher-level curated-view operation without duplicating the lower-level SQL validator.
- Dependency: requires `plugin_temp_views.sql`.

## Modify: `v2/pg_agent_data_analysis.sql`

- Keep `make_da_prompt(integer)` and its immutable signature.
- Remove `da_*` shortcut advertising from the prompt text.
- Change `da_system_prompt(text)` so it appends `render_workbench_tools()` to the static prompt.
- Keep `da_list_tables()`, `da_show_create()`, and `da_sample()` unchanged as legacy direct-call functions.
- Why: the existing stable wrapper is the correct catalog-aware prompt seam, while the existing helpers are too narrow to advertise as the canonical workbench API (`v2/pg_agent_data_analysis.sql:16-147`).
- Dependency: must be loaded after `v2/pg_agent_workbench_core.sql`.

## Modify: `v2/pg_agent_rlm.sql`

- In the DA branch of `rlm_loop()`, replace the direct `make_da_prompt(...)` call at the current prompt construction site with `da_system_prompt(p_run_id)` (`v2/pg_agent_rlm.sql:419-424`).
- Do not add plugin-specific dispatch or branches.
- Preserve `rlm_eval()`, `da_wrap_obs()`, `v_got_q`, `last_obs`, and `agent_steps` behavior (`v2/pg_agent_rlm.sql:361-514`).
- Why: this is the only runtime integration point required for all future plugins.

This change must be deployed atomically with the `da_system_prompt()` implementation because the new RLM call depends on that function.

## Modify: `v2/setup_db.py`

- Extend `SQL_FILES` from the current three files to the full ordered stack:
  1. `pg_agent_functional.sql`
  2. `pg_agent_rlm.sql`
  3. `pg_agent_workbench_core.sql`
  4. `pg_agent_data_analysis.sql`
  5. `plugin_brief_query.sql`
  6. `plugin_temp_views.sql`
  7. `plugin_sql_curator.sql`
- Grow `SQL_FILES` as each work item lands: after W1 include `pg_agent_workbench_core.sql`; append each `plugin_*.sql` only when that file exists (W4–W7).
- After each load of new workbench SQL, execute `SELECT refresh_workbench_tools()` and fail if the call errors. Assert registered count **equals the number of plugin tools installed so far** (0 after core-only, 1 after brief_query, 3 after temp_views read-only if only list+columns are registered… **final six-tool count is a W7/W8 gate**, not a W3 setup failure).
- Extend verification to check the core table/functions; add per-plugin function existence checks as those files land (`v2/setup_db.py:56-68`).
- Why: the current normal loader knows only the three pre-workbench files (`v2/setup_db.py:19-24,44-49`). Expanding to seven files before plugins exist would fail `ON_ERROR_STOP=1`.
- Dependency: lands incrementally with W1 and W4–W7.

## Modify: `v2/test_data_analysis.py`

- Extend `SQL_FILES` and reload order to match `setup_db.py` (`v2/test_data_analysis.py:19-25`).
- Refresh the registry after loading.
- Preserve existing F2 direct tests for `da_*` compatibility (`v2/test_data_analysis.py:F2`).
- Add registry tests:
  - exact six registered tools;
  - deterministic render order;
  - no workbench function in `handlers`;
  - malformed/duplicate metadata rejection and registry preservation;
  - refresh idempotence.
- Add same-session TEMP VIEW tests:
  - host-created TEMP VIEW visible to `wb_brief_query`;
  - second connection cannot see it;
  - public view and TEMP TABLE are rejected;
  - columns, empty view, row limit, and truncation behavior.
- Add TEMP VIEW lifecycle tests:
  - list/columns;
  - create SELECT/WITH;
  - reject DML, DML CTE, comments, semicolons, and invalid names;
  - replace/no-replace behavior;
  - restricted drop and dependency errors.
- Add curator note/list tests.
- Existing F0d (`information_schema` / query-before-final / no spawn) still passes after dropping `da_*` ads. **Add** a negative assertion `'da_list_tables' not in make_da_prompt(50)` and that `da_system_prompt(run_id)` contains the rendered workbench section (`v2/test_data_analysis.py:136-141,214`).
- Add deterministic mocked-provider tests for:
  - a plugin SQL call followed by final answer;
  - final answer before any SQL being rejected;
  - an unsuccessful SQL observation not enabling finalization.
- Retain DeepSeek F4/F5 as network smoke tests and require at least one recorded tool `code` to mention the fixture/view used, following the grounding requirement from the prior review (`prompt-exports/oracle-review-2026-08-22-175500-untitled-chat-023cdb-0e13.md`).
- Keep fixture setup and TEMP VIEW cleanup in `try/finally`; the existing fixture lifecycle already follows this pattern in the current test body (`v2/test_data_analysis.py:test_data_analysis()`).

## Modify: `v2/README.md`

- Document the new load order and `SELECT refresh_workbench_tools()` deployment step.
- Document that DA workbench tools are current-session SQL functions, not queue jobs.
- Document the plugin file standard, required comment keys, `jsonb` return contract, and `pg_my_temp_schema()`-only view-name policy.
- Document that `da_*` helpers remain legacy compatibility functions and are not canonical prompt tools.
- Why: the current README describes only the three-file DA stack and the RLM entrypoint (`v2/README.md`).

## Modify: `v2/TEST_REPORT.md`

- Add the workbench scope and final installed tool count.
- Record registry, prompt, same-session, isolation, validator, lifecycle, and curator test groups.
- Keep the existing evidence boundary that this is a narrow PostgreSQL data-analysis system, not a broader protocol implementation (`v2/TEST_REPORT.md`).
- Record that direct TEMP VIEW mutation through a `SELECT` function is guarded by the plugin validator and remains subject to the existing outer lexical false positives.

## Modify: `docs/plans/v2-workbench-plugins-2026-08-22.md`

- Resolve the two open questions:
  - legacy `da_*` functions retained but no longer advertised or registered;
  - API view identifiers resolve through `pg_my_temp_schema()` only.
- Replace the open-question section with the final registry metadata contract, plugin file order, and verification expectations.
- Why: this document is the in-progress plan being completed, while the investigation remains authoritative background.

## Do not modify

- `v2/pg_agent_functional.sql`: the queue plugin system and `exec_sql_readonly()` remain shared infrastructure and are intentionally not changed (`v2/pg_agent_functional.sql:252-327,465-497`).
- `v2/server.py`: it only manages the embedded PostgreSQL server and has no knowledge of SQL object loading (`server.py:1-55`).
- Any v1 SQL or test file: the requested boundary is v2/database `da_agent` only (`v1/README.md`; `v1/pg_agent_rlm_integrated.sql`).

# 5. Risks and migration

## 5.1 `SELECT`-wrapped mutation is a capability boundary

`exec_sql_readonly()` blocks direct `CREATE` and `DROP`, but a `SELECT` function can perform dynamic SQL internally, as already demonstrated by `da_sample()` (`v2/pg_agent_functional.sql:252-287`; `v2/pg_agent_data_analysis.sql:62-89`). Therefore `wb_temp_view_create()` and `wb_sql_curate()` must be treated as explicit capabilities, not as ordinary read-only functions.

Mitigations:

- `SECURITY INVOKER`.
- Current-session TEMP VIEW scope only.
- Strict identifier validation.
- No `CASCADE`.
- Conservative SQL validator plus planning-only parse.
- Capability labels in metadata and prompt.
- No arbitrary `CREATE`/`DROP` in the static prompt.

This design is not a complete sandbox against side-effecting functions invoked from an otherwise valid SELECT. If untrusted database roles or hostile SQL must be supported, the implementation requires a stronger parser/role boundary than the current repository provides.

## 5.2 Outer blacklist false positives

The existing executor scans the full submitted text, including string literals (`v2/pg_agent_functional.sql:252-287`). A valid call such as `SELECT wb_temp_view_create('v', 'SELECT ...')` can be rejected if the embedded SQL string contains a standalone blocked word. This is an existing executor limitation, not a plugin registry problem.

The implementation must document this behavior and include a regression test. Do not weaken the shared blacklist as part of this work; changing it would affect all CodeAct and RLM paths.

## 5.3 TEMP VIEW leakage through pooled connections

TEMP VIEWs survive across agent runs on the same backend. This is intentional for the persistent SQL REPL model (`v2/pg_agent_rlm.sql:63-88`), but it means a connection pool can leak workbench state between logical users. The host/session manager must drop or discard the backend when logical ownership ends. The plugin layer cannot infer logical user boundaries from `run_id`.

## 5.4 Registry staleness

`workbench_tools.fn` is a stored `regprocedure` value and is not a foreign key to `pg_proc`. Dropping a plugin function without refreshing leaves stale metadata. The renderer must skip unresolved functions, and deployment must always run `refresh_workbench_tools()` after plugin installation or removal.

## 5.5 View replacement compatibility

PostgreSQL may reject `CREATE OR REPLACE VIEW` when the replacement changes existing column names or incompatible types. The plugin must return that error and leave the original view intact. It must not silently drop and recreate the view because that could invalidate dependent TEMP VIEWs.

## 5.6 Migration and rollback

The change is additive to stored schemas and requires no conversion of existing rows. Existing DA callers can continue using `agent_run_data_analysis()`; they receive a prompt with installed tools only after the new wrapper and registry are deployed. Existing callers of `make_da_prompt()` retain the same signature and static behavior, although the prompt no longer advertises the legacy `da_*` shortcuts.

Rollback must remove or refresh plugins before dropping the core registry, and the `rlm_loop()`/`da_system_prompt()` pair must be reverted atomically if the workbench feature is removed.

# 6. Implementation order

1. **Add the core registry and shared resolver.**
   - Create `v2/pg_agent_workbench_core.sql`.
   - Verify the table, helper signatures, metadata validation, empty-registry rendering, and idempotent refresh.
   - This step is independently loadable after the current functional/RLM stack.

2. **Wire the stable DA prompt wrapper.**
   - Update `make_da_prompt()` to remove `da_*` shortcut advertising while preserving its immutable static contract.
   - Update `da_system_prompt()` to append `render_workbench_tools()`.
   - Update `rlm_loop()` to call `da_system_prompt(p_run_id)` in the DA branch.
   - Land the `pg_agent_rlm.sql` and `pg_agent_data_analysis.sql` changes atomically because the new runtime call depends on the wrapper existing.
   - Verify that non-DA RLM prompt functions remain unchanged.

3. **Update the normal loader and test loader for core (progressive).**
   - Append `pg_agent_workbench_core.sql` to `SQL_FILES` in `v2/setup_db.py` and `v2/test_data_analysis.py`.
   - Call `refresh_workbench_tools()` after load; expect **zero** tools until W4.
   - Verify a clean `da_agent` setup succeeds with `ON_ERROR_STOP=1`.
   - Do **not** list plugin files that do not exist yet. Append them in steps 4–7.

4. **Add and verify `plugin_brief_query.sql`.**
   - Implement the read-only function and comment metadata.
   - Append the file to both loaders; refresh; expect **one** tool.
   - Create a host-owned TEMP VIEW in the test connection.
   - Verify preview rows, columns, empty views, limits, truncation, invalid names, missing views, `pg_my_temp_schema()=0` empty list, and cross-connection isolation.

5. **Add the read-only portion of `plugin_temp_views.sql`.**
   - Implement `wb_temp_view_list()` and `wb_temp_view_columns()`.
   - Verify that only current-session TEMP VIEWs appear and that temporary tables/permanent views are excluded.
   - Confirm prompt rendering places read-only tools before mutation tools.

6. **Add the mutation portion of `plugin_temp_views.sql`.**
   - Implement the conservative token validator (steps 1–5 in §3.6); rely on `CREATE TEMP VIEW` itself for DML-CTE / `SELECT INTO` rejection.
   - Implement `wb_temp_view_create()` and `wb_temp_view_drop()`.
   - Refresh; expect **five** tools after list/columns/create/drop plus brief_query (or four temp-view tools + brief_query = five).
   - Verify direct DDL remains rejected by `rlm_eval()`, while approved `SELECT wb_temp_view_create(...)` calls work in-session.
   - Verify rejection of semicolons, comments, DML, utility statements, invalid identifiers, non-view collisions, and incompatible replacement.
   - Verify no permanent relation is changed.

7. **Add `plugin_sql_curator.sql`.**
   - Delegate view creation to the lifecycle plugin with the savepoint/subtransaction mechanism in §3.7.
   - Add stricter SQL-length and note validation.
   - Attach and list session-local notes; omitted `p_note` clears the previous note.
   - Verify atomic failure behavior when note application or replacement fails.
   - Append the file to loaders; refresh; **final gate: registered count is six.**

8. **Add deterministic runtime tests (mock via function override).**
   - In the isolated `da_agent` test connection, `CREATE OR REPLACE FUNCTION http_call_llm(jsonb)` with the same signature `rlm_loop` uses (`sql_retry('http_call_llm(jsonb)'::regprocedure, …)` at `v2/pg_agent_rlm.sql:436`). Serve a preloaded JSON response queue from a temp table.
   - Run plugin-in-loop sequences (brief_query then final; premature final; failed SQL does not open the gate).
   - Reload `pg_agent_functional.sql` (or restore the original `http_call_llm`) **before** DeepSeek F4/F5. Do not leave the stub in place across SQL reloads that call `refresh_handlers()`.
   - Keep DeepSeek F4/F5 as separate smoke tests. Grounding: require a successful **nested** plugin or SQL observation (do not treat outer `success: true` wrapping nested `success: false` as a pass); at least one `payload.code` must name the fixture/view (`v2/test_data_analysis.py:185-214`).

9. **Run registry separation tests.**
   - Run `refresh_handlers()`.
   - Assert no `wb_*` function appears in `handlers`.
   - Assert all expected workbench functions appear in `workbench_tools`.
   - Exercise malformed and duplicate metadata probes and confirm failed refresh preserves the prior registry.

10. **Complete documentation and report.**
    - Update `v2/README.md`, `v2/TEST_REPORT.md`, and `docs/plans/v2-workbench-plugins-2026-08-22.md`.
    - Do not modify v1 documentation or SQL.

# 7. Verification plan

## 7.1 Static and catalog verification

The final database must satisfy:

- `workbench_tools` exists with the specified columns and primary key.
- `refresh_workbench_tools()` and `render_workbench_tools()` exist with the specified signatures.
- The six final tools are registered exactly once:
  - `wb_brief_query`
  - `wb_temp_view_list`
  - `wb_temp_view_columns`
  - `wb_temp_view_create`
  - `wb_temp_view_drop`
  - `wb_sql_curate`
- `make_da_prompt(50)` remains immutable and contains schema-first instructions but no `da_*` shortcut list.
- `da_system_prompt(run_id)` contains the rendered tool section.
- `rlm_loop()` references `da_system_prompt()` in its DA prompt branch and does not contain plugin-specific names.
- `refresh_handlers()` does not register any `wb_*` function.

These checks extend the existing setup verification pattern in `v2/setup_db.py:56-68` and the prompt assertions in `v2/test_data_analysis.py:136-141,214`.

## 7.2 Registry behavior

Test:

- Initial refresh returns six.
- Second refresh returns six and does not duplicate rows.
- Removing one plugin function followed by refresh removes exactly that tool.
- A malformed workbench comment aborts refresh and leaves the prior registry unchanged. **Restore the function COMMENT in `finally`.** A `{`-prefixed invalid JSON comment also breaks `refresh_handlers()` (`v2/pg_agent_functional.sql:322-323`) and any later reload of functional/rlm SQL (`:383`, `v2/pg_agent_rlm.sql:838`). Do not trigger handler refresh or SQL reload while the probe comment is in place.
- A duplicate `llm_tool.name` aborts refresh.
- A workbench comment containing `job_handler` aborts refresh.
- A function with the wrong return type is rejected.
- A stale registry row is omitted from rendered prompt after its function is dropped.

The install/uninstall pattern follows the existing v1 comment-discovery test precedent, which mutates a function comment, re-renders, and restores it (`v1/run_tests.py:262-286`).

## 7.3 Session isolation

Using two PostgreSQL connections:

1. Connection A creates a TEMP VIEW and successfully calls `wb_brief_query()`.
2. Connection B calls the same function with the same name and receives a missing-view result.
3. A permanent view of the same name does not satisfy the plugin lookup.
4. A TEMP TABLE of the same name does not satisfy the plugin lookup.
5. Connection A’s `wb_temp_view_list()` does not expose objects from B.

This directly verifies the session-local constraint that prevents using `worker()` as the workbench seam (`v2/pg_agent_functional.sql:465-497`).

## 7.4 SQL safety and lifecycle

Test each rejected input through the direct plugin function and, where relevant, through `rlm_eval()`:

- empty and malformed view names;
- schema-qualified names;
- semicolon-containing SQL;
- SQL comments;
- top-level DML;
- DML inside a `WITH`;
- `SELECT INTO`;
- utility statements;
- incompatible view replacement;
- non-view name collision;
- restricted drop of a depended-on view.

For every rejection, verify:

- the result has `success=false`;
- `Type`, `Phase`, `Problem`, and `Solution` are present;
- no unexpected permanent object or TEMP VIEW was created;
- an existing view remains unchanged after failed replacement.

## 7.5 Runtime prompt and grounding

Use a deterministic test LLM sequence in addition to the existing DeepSeek smoke test:

- Response 1: a single `SELECT wb_brief_query(...)`.
- Response 2: a final answer with no code.
- Assert the tool step contains the exact workbench function call and a successful preview observation.
- Assert the final step exists only after the tool step.

Separate negative sequence:

- Response 1: final answer with no code.
- Response 2: final answer with no code.
- Assert no final step is emitted and the run ends with the existing maximum-step/error behavior.

For the network smoke test, retain the fixture-specific grounding requirement: at least one successful tool step must reference the fixture relation or TEMP VIEW, and the final answer must contain the expected derived value rather than merely a generic successful query (`prompt-exports/oracle-review-2026-08-22-175500-untitled-chat-023cdb-0e13.md`; `v2/test_data_analysis.py:185-214`).

## 7.6 Regression verification

Run the existing v2 data-analysis assertions unchanged except where prompt text intentionally changes:

- empty question rejection;
- legacy `da_*` direct-call compatibility;
- `DELETE`/`DROP` rejection through `rlm_eval()`;
- successful query-before-final behavior;
- consecutive runs do not reuse `rlm.run_id`;
- no child runs for DA.

The v1 suite must remain untouched and should not be required for v2 workbench installation. The embedded server remains the same `server.py`-managed PostgreSQL instance (`server.py:1-55`).
