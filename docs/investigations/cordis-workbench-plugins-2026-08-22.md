# Investigation: v1 Cordis plugin system → v2 Postgres-only workbench plugins

## Summary

v1 设计了**真的 SQL 作业插件**（`COMMENT job_handler` → `refresh_handlers()` → `handlers` → `worker()`），`cordis_services` 只是未接线的表。v2 **继承了这套队列插件，但数据分析没用它**：DA 走 `rlm_loop` + 写死在 `make_da_prompt` 里的 SELECT API。Postgres-only 工作台应另做 `workbench_plugin` 注册表 + 当前会话可 `SELECT` 的函数；**不要**用 `worker()` 建 TEMP VIEW（会话绑错）。第一插件应是只读的 `plugin_brief_query`，再上 `plugin_temp_views`。

## Symptoms
- Need to know whether v1 designed a Cordis-style plugin system.
- Need to know whether v2 inherited it.
- Constraint: all workbench tables live in PostgreSQL (no CSV/JSON file sources).
- Goal: design the data-analysis workbench as loadable plugins, one plugin per increment.

## Hypotheses (Phase 1)
1. v1 encoded Cordis as SQL: `COMMENT ON FUNCTION` metadata + `handlers`/`cordis_services` tables + `refresh_handlers()` catalog scan (not a JS plugin runtime).
2. v2 copied `pg_agent_functional.sql` (jobs/handlers) but `data_analysis` did not register workbench ops as plugins; capabilities are hardcoded in `make_da_prompt` / `rlm_loop`.
3. A Postgres-only workbench plugin is: a SQL file of functions + COMMENT schema + `refresh_handlers()` (or a workbench-specific registry), each plugin mutating named TEMP VIEWs in the current session.

## Background / Prior Research

### Git archaeology (`df0a8c3` → `c131994`)

Repo has two commits. Cordis-style plugins shipped in the **first commit** (`df0a8c3`), not a later add-on. `c131994` only moved files into `v1/` / `v2/`.

v1 mechanism (SQL catalog metaprogramming, not a JS runtime):

1. `cordis_services` table — `v1/pg_agent_fixed.sql` (~L111). Provider/service registry; **not wired into dispatch** in these files.
2. `handlers(job_type, fn regproc)` — `v1/pg_agent_functional.sql` (~L301).
3. `refresh_handlers()` TRUNCATEs `handlers` and rebuilds from `obj_description(pg_proc)` JSON with key `job_handler` (~L305–319). Bootstrap `SELECT refresh_handlers()` (~L379).
4. Plugin contract: function `(p_job jobs) RETURNS void` + `COMMENT ON FUNCTION ... '{"job_handler":"..."}'`.
5. Built-ins: `h_schema_all_tables`, `h_sample_table`, `h_agent_run`.
6. `llm_tool` in COMMENT is a **separate** POML scan (`v1/pg_agent_poml.sql` ~L262–274) for prompt tool lists; original handlers only have `job_handler`. Tests note default tool list is empty without `llm_tool`.

### Cordis (Koishi) model — mapping note

Cordis is a JS plugin/DI kernel: plugins register into a `Context`, expose named **services**, isolate side effects, can be loaded/unloaded. pg-agent’s analog is: plugin = SQL function + COMMENT metadata; registry = `handlers` rebuilt from `pg_catalog`; dispatcher = `worker()` lookup by `job_type`. `cordis_services` looks like an unused service-locator stub.

A web explore intended to fetch Koishi Cordis docs was steered toward “DeepSeek harnesses”; it concluded DeepSeek is only the LLM backend via `openai.*` GUCs + `http_call_llm`, not a plugin kernel. Treat Koishi mapping as analogy, not a fetched spec.


## Investigator Findings
<!-- Pair investigator appends here. -->

### 1. v1 Cordis plugin system: real mechanism vs stubs

**Conclusion: v1 has a real SQL job-plugin mechanism, but `cordis_services` is only a registry-table stub.** The implementation is catalog-driven dispatch, not a Cordis/Koishi runtime.

#### Real: `COMMENT` → `refresh_handlers()` → `handlers` → `worker()` → `h_*`

- `v1/pg_agent_functional.sql:293-301` states the contract explicitly: a plugin is a `(p_job jobs) RETURNS void` handler, registration is a function `COMMENT`, and “new plugin = one function + one comment.” The `handlers(job_type text primary key, fn regproc)` table is defined at `v1/pg_agent_functional.sql:299-302`.
- `refresh_handlers()` at `v1/pg_agent_functional.sql:305-323` truncates `handlers` and scans `pg_proc` in the `public` schema. It parses `obj_description(p.oid, 'pg_proc')::jsonb`, selects the top-level `job_handler` key, and stores the function OID as `regproc`. This is real registration/discovery, but only for queue handlers bearing that metadata.
- The built-in handler functions are `h_schema_all_tables(p_job jobs)` (`v1/pg_agent_functional.sql:326-346`), `h_sample_table(p_job jobs)` (`:349-361`), and `h_agent_run(p_job jobs)` (`:364-377`). Their comments register `schema_all_tables`, `sample_table`, and `agent_run` respectively. The file calls `SELECT refresh_handlers()` at `:379`.
- `worker()` at `v1/pg_agent_functional.sql:461-493` is the actual dispatcher. It selects a `PENDING` row from `jobs` with `FOR UPDATE SKIP LOCKED` (`:469-473`), marks it `RUNNING` (`:475`), looks up `handlers.fn` by `job_type` (`:477`), dynamically executes the handler with the whole `jobs` row (`:479-483`), and marks failures `ERROR` (`:484-489`). An unknown `job_type` raises `未注册的 job_type` (`:480`).
- v1 also has an older, separate `agent_worker()` in `v1/pg_agent_fixed.sql:598-671`. It operates on `agent_jobs` and uses a hardcoded IF-chain, not `handlers`; it should not be conflated with the functional/RLM handler system.

**`cordis_services` is not wired into this path.** `v1/pg_agent_fixed.sql:109-119` only creates the table (`service_name`, `provider_run_id`, `config`, `is_default`, timestamps). A repository-wide v1 search found no insert, select, lookup, or dispatch reference beyond that definition. There is no call from `worker()`, `refresh_handlers()`, or any `h_*` function. Therefore it is an aspirational service registry/table stub, not an active service locator or plugin lifecycle.

#### Real but separate: v1 `llm_tool`

- `v1/pg_agent_poml.sql:262-284` defines `w_tools(node xml, style jsonb)`. It separately scans function comments for a top-level `llm_tool` JSON object and renders a Markdown tool list for the POML `<tools/>` component (`:262-274`), using `name` and `description` (`:276-280`).
- The sample metadata at `v1/pg_agent_poml.sql:441-443` shows that `llm_tool` can coexist with `job_handler` on the same function. It is prompt/tool-description discovery, not worker dispatch and not invocation routing.
- The v1 test demonstrates the distinction: `v1/run_tests.py:278-284` first asserts that the default prompt has no tools, then adds `llm_tool` to `h_sample_table` and checks that `<tools/>` includes it, then restores the comment. The normal handler comments at `v1/pg_agent_functional.sql:346`, `:361`, and `:377` contain only `job_handler`, so they are queue-registered but not automatically LLM-exposed through this POML mechanism.

### 2. Did v2 inherit the system?

**Yes for the generic queue subsystem; no for the v2 data-analysis tool surface.** The v2 functional file is effectively a compatibility-adjusted copy of the v1 functional file in the relevant sections.

#### Handler/refresh/h_* diff

- v2 keeps the same handler schema and scan at `v2/pg_agent_functional.sql:303-327` and the same three functional handlers/comments at `:330-381`; deployment invokes `SELECT refresh_handlers()` at `:383`.
- v2 keeps the same `worker()` shape at `v2/pg_agent_functional.sql:465-497`: `jobs` row claim, `handlers` lookup, dynamic `SELECT fn($1)`, and error update. The v1 counterpart is `v1/pg_agent_functional.sql:461-493`.
- The actual v1→v2 diff in `pg_agent_functional.sql` changes PG17/type/JSON-message compatibility details (for example `regproc`/`regprocedure` handling and message-array construction), not the handler contract or worker dispatch. The handler blocks remain structurally the same.
- v2’s RLM file adds/retains queue adapters: `h_rlm_run(p_job jobs)` and `h_hybrid_run(p_job jobs)` at `v2/pg_agent_rlm.sql:805-836`, with `job_handler` comments at `:820` and `:836`, followed by `SELECT refresh_handlers()` at `:838`. v1’s standalone RLM has `h_rlm_run` at `v1/pg_agent_rlm.sql:670-685`; the integrated v1 variant has both at `v1/pg_agent_rlm_integrated.sql:787-818`. v2 therefore inherited and extended the queue registry, adding `hybrid_run` to the active v2 RLM file.
- v2 removed the v1-only `cordis_services` definition: there are no `cordis_services`/`cordisServices` references in the v2 SQL/Python tree. It also removed the v1 POML file and all v2 `llm_tool`/`w_tools` machinery; the only v2 metadata scan visible is `refresh_handlers()` for `job_handler`.

#### v2 setup/tests do not use the queue for DA

- `v2/setup_db.py:17-24` loads only `pg_agent_functional.sql`, `pg_agent_rlm.sql`, and `pg_agent_data_analysis.sql`; `:44-49` performs the load loop; `:56-68` only verifies function/extension existence. It never calls `refresh_handlers()` from Python and never inserts into `jobs`.
- `v2/test_data_analysis.py:135-166` tests the DA prompt and calls `da_list_tables()`, `da_show_create(...)`, and `da_sample(...)` directly with `SELECT`. The insert at `:169-177` creates an `agent_runs` row for `rlm_eval` guard testing, not a `jobs` row. The DA test’s end-to-end call at `:185-190` is `SELECT agent_run_data_analysis(...)`; no `jobs` insert or `worker()` call is involved.
- In the v2 SQL, the only DA-adjacent job examples are commented examples: `v2/pg_agent_functional.sql:505-509` and `v2/pg_agent_rlm.sql:851-854`. The executable `refresh_handlers()` calls are deployment-time SQL at `v2/pg_agent_functional.sql:383` and `v2/pg_agent_rlm.sql:838`, not DA runtime dispatch.

#### Exact v2 RLM/DA tool surface

- `agent_run_data_analysis(...)` at `v2/pg_agent_data_analysis.sql:149-177` creates an `agent_runs` row with `paradigm='data_analysis'`, `depth=0`, and `max_depth=0` (`:166-168`), binds the session run ID, and calls `rlm_loop(v_run_id)` (`:175`).
- `rlm_loop()` at `v2/pg_agent_rlm.sql:395-514` chooses `make_da_prompt(...)` when `agent_runs.paradigm='data_analysis'` (`:420-424`). It evaluates the model’s returned `code` through `rlm_eval()` and, for DA, wraps the observation with `da_wrap_obs()` (`:487-504`). It does not look up `handlers`, enqueue `jobs`, or call `worker()`.
- `make_da_prompt()` at `v2/pg_agent_data_analysis.sql:92-117` hardcodes the DA API: `rlm_query('SELECT ...')`, `information_schema.tables/columns` and `pg_catalog`, `env_keys/env_peek/env_search/env_len/env_get`, plus the convenience functions `da_list_tables()`, `da_show_create()`, and `da_sample()` (`:111-116`). It explicitly forbids `CREATE`, DML, and sub-agent tools (`:103-108`).
- `rlm_query()` at `v2/pg_agent_rlm.sql:345-349` is only a thin wrapper over `exec_sql_readonly()`. `rlm_eval()` at `:351-380` also routes submitted SQL to `exec_sql_readonly()`.
- The non-DA RLM prompt at `v2/pg_agent_rlm.sql:63-88` exposes the env functions, `rlm_query`, `codeact_spawn`, and conditionally `rlm_spawn`, `rlm_map`, and `rlm_list`. The hybrid prompt at `:114-129` uses an `action`/`action_input` protocol (`execute_sql` or `rlm`). None of these prompt APIs are handler names.
- `exec_sql_readonly()` at `v2/pg_agent_functional.sql:252-287` rejects `create`, `insert`, `update`, `delete`, etc. before dynamic execution. Thus `rlm_query('CREATE TEMP VIEW ...')` is intentionally blocked. The existing DA convenience functions are ordinary SELECT-callable functions; they are not `h_*` handlers.

**Disproof of inheritance as a DA plugin system:** v2 inherited the generic `handlers`/`worker()` infrastructure, but there is zero runtime path from the DA LLM’s JSON/code decision to `jobs` → `worker()` → `h_*`. The DA surface is hardcoded prompt text plus SELECT-callable SQL functions.

### 3. Postgres-only TEMP VIEW workbench design

#### Why `handlers`/`worker()` is the wrong primary seam for RLM TEMP VIEWs

The existing `job_handler` contract requires `(p_job jobs) RETURNS void` (`v2/pg_agent_functional.sql:297-300`), while DA emits one SELECT/WITH expression and `rlm_loop()` executes it inline through `rlm_eval()` (`v2/pg_agent_rlm.sql:395-514`). A direct workbench function such as `wb_temp_view_create(text,text)` is therefore not callable through the current handler contract without an adapter and a job insert.

More importantly, a TEMP VIEW is session-local. `agent_run_data_analysis()` and `rlm_loop()` run synchronously in the caller’s PostgreSQL session (`v2/pg_agent_data_analysis.sql:149-177`), while the queue design explicitly supports multiple worker sessions (`v2/pg_agent_functional.sql:505-509`). A handler that creates a TEMP VIEW in a worker session creates it in the worker’s session, not in the RLM session that will later query it; it is invisible to that RLM and disappears with the worker session. This is a semantic mismatch, not merely missing prompt wiring.

The correct reuse is the **catalog-comment idea**, not the `job_handler` dispatch path:

1. Each plugin is one SQL file defining trusted, SELECT-callable functions against the current session’s named TEMP VIEWs.
2. Each function gets a separate metadata key such as `workbench_plugin` plus an `llm_tool` object. Do not label these functions with only `job_handler`; that would register them as `jobs` handlers even though their signatures and invocation model are different.
3. A small core file can define `workbench_tools` and `refresh_workbench_tools()`, scanning `pg_proc` comments in the same style as `refresh_handlers()`, but storing `regprocedure`/metadata for SELECT-callable functions. The registry can be rendered into the DA prompt. Because the current `make_da_prompt()` is `IMMUTABLE` and hardcodes its list (`v2/pg_agent_data_analysis.sql:92-117`), dynamic plugin discovery would require either a separate `STABLE` renderer appended by `rlm_loop()` (`v2/pg_agent_rlm.sql:420-424`) or changing the prompt composition to call a stable catalog-rendering function.
4. Install/load order remains one plugin SQL file at a time; after loading a plugin, run `SELECT refresh_workbench_tools()` in the same database. The plugin’s functions are persistent, but the named TEMP VIEW instances are created later in the agent connection and remain scoped to that connection.

A minimal registry/prompt core would have these signatures:

```sql
CREATE TABLE workbench_tools (
    tool_name text PRIMARY KEY,
    plugin_name text NOT NULL,
    fn regprocedure NOT NULL,
    metadata jsonb NOT NULL
);
CREATE OR REPLACE FUNCTION refresh_workbench_tools() RETURNS integer;
CREATE OR REPLACE FUNCTION render_workbench_tools() RETURNS text; -- STABLE
```

#### Proposed plugin-file sketch (signatures + COMMENT JSON)

The following is a design sketch, not an applied source change. Function bodies should validate identifiers, reject semicolons/write keywords in user-provided SELECT text, use `format('%I', name)` for identifiers, and execute as `SECURITY INVOKER` unless a narrowly reviewed privilege boundary is intentional.

**`plugin_temp_views.sql` — session-local workbench lifecycle**

```sql
CREATE OR REPLACE FUNCTION wb_temp_view_create(
    p_view text,
    p_select_sql text,
    p_replace boolean DEFAULT true
) RETURNS jsonb; -- VOLATILE; validates SELECT/WITH, then CREATE OR REPLACE TEMP VIEW

COMMENT ON FUNCTION wb_temp_view_create(text, text, boolean) IS
'{
  "workbench_plugin":"plugin_temp_views",
  "llm_tool":{
    "name":"wb_temp_view_create",
    "description":"Create or replace a named TEMP VIEW in the current RLM session from one validated SELECT/WITH",
    "args":{"p_view":"text","p_select_sql":"text","p_replace":"boolean"},
    "returns":"jsonb",
    "session_scope":"current_session",
    "mutation":"temp_view_only"
  }
}';

CREATE OR REPLACE FUNCTION wb_temp_view_drop(p_view text) RETURNS jsonb;
CREATE OR REPLACE FUNCTION wb_temp_view_list() RETURNS jsonb;
CREATE OR REPLACE FUNCTION wb_temp_view_columns(p_view text) RETURNS jsonb;
```

`wb_temp_view_create()` is intentionally called as `SELECT wb_temp_view_create(...)`. That outer SQL passes the current read-only wrapper’s lexical check, but the function is an explicit, privileged workbench mutation; its internal validator must not become an arbitrary-DDL escape hatch. If the security model cannot accept this controlled exception, keep TEMP VIEW creation outside the LLM loop as host-issued setup SQL and expose only read/query plugins to the LLM.

**`plugin_brief_query.sql` — query one named workbench view**

```sql
CREATE OR REPLACE FUNCTION wb_brief_query(
    p_view text,
    p_limit integer DEFAULT 20
) RETURNS jsonb; -- STABLE/READS SQL DATA; returns bounded rows + columns + row_count

COMMENT ON FUNCTION wb_brief_query(text, integer) IS
'{
  "workbench_plugin":"plugin_brief_query",
  "llm_tool":{
    "name":"wb_brief_query",
    "description":"Return a bounded JSON preview from a named current-session TEMP VIEW",
    "args":{"p_view":"text","p_limit":"integer"},
    "returns":"jsonb",
    "session_scope":"current_session",
    "read_only":true
  }
}';
```

**`plugin_sql_curator.sql` — produce/update a curated named view**

```sql
CREATE OR REPLACE FUNCTION wb_sql_curate(
    p_view text,
    p_select_sql text,
    p_note text DEFAULT NULL
) RETURNS jsonb; -- VOLATILE; validates/normalizes a SELECT/WITH and delegates to temp-view creation

COMMENT ON FUNCTION wb_sql_curate(text, text, text) IS
'{
  "workbench_plugin":"plugin_sql_curator",
  "llm_tool":{
    "name":"wb_sql_curate",
    "description":"Validate and materialize a named curated TEMP VIEW from a read-only SELECT/WITH",
    "args":{"p_view":"text","p_select_sql":"text","p_note":"text"},
    "returns":"jsonb",
    "session_scope":"current_session",
    "mutation":"temp_view_only"
  }
}';
```

**Recommended boundary:** `plugin_temp_views` owns lifecycle and session checks; `plugin_brief_query` is read-only and safe to expose first; `plugin_sql_curator` is added only after the validator and privilege policy are tested. The plugin registry/prompt renderer should expose only installed functions whose comments carry `workbench_plugin`/`llm_tool`; it should not imply that a function is callable merely because it has a `job_handler` comment.

### Bottom-line answers

1. **v1:** `handlers` + `refresh_handlers()` + `worker()` + `h_*` is real queue plugin infrastructure. `cordis_services` is unused scaffolding. `llm_tool` is a separate v1 POML prompt inventory, not dispatch.
2. **v2:** inherited and extended the generic handler subsystem, but DA/RLM uses hardcoded SELECT-callable APIs and never enters the jobs worker path.
3. **Design:** for a Postgres-only named TEMP VIEW workbench, reuse comment-based catalog discovery with a workbench-specific registry/prompt renderer; use SELECT-callable functions in the RLM session. Do not use `handlers`/`worker()` as the primary seam for TEMP VIEW plugins because queue execution is job/session-oriented and cannot expose handler tools to the current DA protocol.

## Investigation Log

### Phase 1 - Triage
**Hypothesis:** Cordis in v1 is SQL catalog metaprogramming, not Koishi JS.
**Findings:** Confirmed. `df0a8c3` already shipped `handlers` + `refresh_handlers` + `h_*`. `cordis_services` unused.
**Evidence:** `v1/pg_agent_functional.sql:294-327`, `v1/pg_agent_fixed.sql:109-118`.
**Conclusion:** Confirmed.

### Phase 1.5 - External
**Hypothesis:** Git history and Koishi Cordis docs would show a later port.
**Findings:** Two commits only; plugin system is day-one. Web probe was steered to DeepSeek harnesses; DeepSeek is LLM backend only.
**Evidence:** `git log` `df0a8c3`, `c131994`.
**Conclusion:** No later Cordis port.

### Phase 3 - Pair
**Hypothesis:** v2 inherited handlers but DA does not dispatch through them; TEMP VIEW plugins must be session-local SELECT functions.
**Findings:** Confirmed. See Investigator Findings.
**Evidence:** `v2/pg_agent_data_analysis.sql:92-117,149-177`; `v2/pg_agent_rlm.sql:418-426`; `exec_sql_readonly` create ban at `v2/pg_agent_functional.sql:259`.
**Conclusion:** Confirmed.

### Phase 4 - Oracle
**Hypothesis:** First plugin should be temp-view create.
**Findings:** Rejected. `SELECT wb_temp_view_create(...)` bypasses the lexical CREATE blacklist. First user plugin = `plugin_brief_query` (read-only, host-created TEMP VIEW fixture). Core registry file first.
**Evidence:** Oracle chat `untitled-chat-6B3C76` / `prompt-exports/oracle-chat-2026-08-22-203247-untitled-chat-6b3c76-39f1.md`.
**Conclusion:** Confirmed with revised increment order.

## Root Cause

There are two different “plugin” ideas in this repo, and they were collapsed under the name Cordis.

1. **Queue plugins (real, inherited):** A function `(p_job jobs) RETURNS void` plus `COMMENT … {"job_handler":…}` is scanned by `refresh_handlers()` into `handlers`. `worker()` claims a `jobs` row and `EXECUTE`s the function. This shipped in v1 functional SQL (`v2` copy at `pg_agent_functional.sql:294-327`, worker ~465+) and v2 RLM still registers `h_rlm_run` / `h_hybrid_run`. `cordis_services` (`v1/pg_agent_fixed.sql:111-118`) is **not** part of this path—no reads or writes anywhere else.

2. **DA tool surface (not plugins):** `agent_run_data_analysis` inserts `paradigm='data_analysis'` and calls `rlm_loop` (`v2/pg_agent_data_analysis.sql:166-175`). The loop picks `make_da_prompt` (`v2/pg_agent_rlm.sql:418-422`), which is `IMMUTABLE` and **hardcodes** `rlm_query` / `information_schema` / `da_*` (`:92-117`). Tests and `setup_db.py` never insert `jobs` or call `worker()` for DA. Adding a workbench as another `job_handler` would run in a **different session**, so `CREATE TEMP VIEW` would not be visible to the RLM connection that later `SELECT`s it. Separately, `exec_sql_readonly` lexically forbids `create` (`:259`), but `SELECT some_fn()` that internally DDL still passes the wrapper—so mutation plugins are a capability hole unless they validate internally.

## Recommendations

1. **Do not** register workbench ops as `job_handler` / `worker()` plugins. Keep that system for async jobs only.
2. Add `v2/pg_agent_workbench_core.sql`: table `workbench_tools`, `refresh_workbench_tools()`, `render_workbench_tools()` scanning COMMENT keys `workbench_plugin` + `llm_tool` (mirror `refresh_handlers` but `regprocedure`, not `regproc`). Load after `pg_agent_rlm.sql`.
3. Split `make_da_prompt` into IMMUTABLE static body + **STABLE** wrapper that appends `render_workbench_tools()`. `rlm_loop` already calls `make_da_prompt`; no per-plugin loop edits.
4. **First plugin file:** `plugin_brief_query.sql` — `wb_brief_query(p_view, p_limit)` read-only, only current-session TEMP views (`pg_my_temp_schema()`). Host `CREATE TEMP VIEW` in tests.
5. **Second:** `plugin_temp_views.sql` — `list`/`columns` before `create`/`drop`. `wb_temp_view_create` must validate a single SELECT/WITH, no DML CTE, `format('%I')`, `SECURITY INVOKER`. Do not rely on `exec_sql_readonly` blacklist.
6. **Third:** `plugin_sql_curator.sql` wrapping create with stricter SQL hygiene.
7. Prompt text: arbitrary CREATE still forbidden; only listed workbench mutation tools may change `pg_temp`.
8. `setup_db.py`: load core + `plugin_*.sql` then `SELECT refresh_workbench_tools()`.

## Preventive Measures

- Never reuse `job_handler` for session-scoped TEMP objects.
- Keep `llm_tool` (prompt inventory) distinct from `job_handler` (queue dispatch) and `workbench_plugin` (session SELECT APIs).
- Treat `SELECT fn()` as a possible write; document capability in COMMENT and enforce inside the function.
- Do not mark catalog-reading prompt builders `IMMUTABLE`.
- Leave `cordis_services` unused or delete in v2 rather than implying a live Cordis kernel.

