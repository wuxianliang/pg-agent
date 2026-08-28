# v5 prompt assembly: POML-inspired SQL slots and generate-then-retrieve

## 1. Summary

Create a new, sequential `pg-agent/v5/` tree that **loads the final v4 SQL stack as read-only paths** (same pattern as v4 loading `v3/pg_agent_pgmq.sql`) without modifying `v1/`, `v2/`, `v3/`, `v4/`, or `pgembed`, then adds a v5-only prompt taxonomy, versioned recipe storage, XML authoring/compiler support, an ordered SQL retrieval pipeline, **named `wb_*` dispatch**, and **visible first-turn generation** of missing stored parts. The v5 runtime will replace only the v4 `prepare_llm_request()` assembly seam: instead of calling `make_system_prompt(...) || render_plugin_tools()`, it will retrieve ordered prompt components as JSONB chat-message arrays, append the current question and live history, and place the resulting `messages` directly into the PGMQ payload. If required stored parts are missing, the first `llm_requests` job is a normal visible agent turn: bootstrap messages include the user question and `wb_store_prompt_part`. After parts land in recipe-global `prompt_parts` (first-writer-wins), the next assemble retrieves them. SQL never calls an LLM. Worker code lives under `v5/` (v4 Python is not imported at runtime). Generic `apply_queue_result()`, budget, fan-out, and session modes stay the v4 baseline.

## Goal

Freeze v4 as a read-only baseline, then make `prepare_llm_request()` assemble PGMQ `messages` as an ordered pipeline of SQL retrieval slots (POML-inspired components, Postgres-native). Seeded recipe parts live in tables; if a task is missing a required part, the agent generates it via the out-of-DB worker, stores it, then retrieves it on the next assemble. LLM HTTP stays out of SQL.

## Background

### v4/v3 enqueue seam (what v5 must replace, not wrap in Python)

- `agent_start()` inserts `agent_runs` then `enqueue_llm_request()` (`v3/pg_agent_pgmq.sql:401`).
- `enqueue_llm_request()` calls `prepare_llm_request()` and `pgmq.send('llm_requests', payload, '{"x-pgmq-group": run_id}')` (`v3/pg_agent_pgmq.sql:384-398`).
- v3 `prepare_llm_request()` is STABLE: `make_system_prompt(max_rows)` + `fold_messages(system, question, steps)` (`v3/pg_agent_pgmq.sql:348-381`). Payload keys: `run_id`, `question`, `step`, `max_steps`, `messages`, plus GUC snapshots `model`/`api_uri`.
- v4 overlays `prepare_llm_request()` once, in `v4/sticky_workbench/workbench_core.sql:47-81`, concatenating `make_system_prompt(...) || render_plugin_tools()`. Later stages do not replace it.
- v4 workers apply via `apply_queue_result()` (`v4/plugin_taxonomy/worker.py:271`, `v4/queue_kinds/worker.py:140`), never `apply_llm_response()` directly. LLM HTTP is disabled by `v4/plugin_taxonomy/v4_runtime_guard.sql`.

### v4 overlay freeze (kernel debt)

SQL load order is 12 files in `v4/load.py` (`SQL_LOAD_ORDER`). Last-writer-wins:

| Symbol | Last overlay |
|---|---|
| `prepare_llm_request` | `sticky_workbench/workbench_core.sql:47` |
| `apply_llm_response` | `observability_budget/observability_budget.sql:192` (includes queue_kinds wait + budget) |
| `apply_llm_result` | `observability_budget/observability_budget.sql:159` (`sanitize_step_metrics` + `maybe_resume_parent`) |
| `run_state` | `queue_kinds/queue_kinds.sql:209` (`WAITING_QUEUE` / `WAITING_HUMAN`) |
| `fail_run` | `subagent_fanout/subagent_fanout.sql` (`maybe_resume_parent`; `CREATE OR REPLACE FUNCTION fail_run` at `v4/subagent_fanout/subagent_fanout.sql:141`) |
| session views / `session_set` | `session_durability/session_durability.sql` |

`plugin_bindings.binding_type` is currently only `llm_tool` | `queue_handler` (`v4/plugin_taxonomy/plugin_taxonomy.sql:17`). Prompt slots are a new binding type or a sibling table.

v1/v2/v3/v4 trees stay read-only for v5, same rule as v4 vs v3 (`docs/plans/v4-expansion-2026-08-28.md` version boundary).

### v1 POML in Postgres (prior art, not copy-paste)

`v1/pg_agent_poml.sql` already implements:

- Text template expand: `poml_expand_vars` / `poml_expand_for` / `poml_expand_if` / `poml_expand_template` (`v1/pg_agent_poml.sql:19-89`). `{{path}}` via jsonb `#>>`; no JS expressions.
- XML IR: `xmlparse` + `xpath`; writers registered by COMMENT `{"poml_writer":"<tag>"}` into `poml_writers` (`:95-170`).
- Data-in-prompt: `w_table` reads `query`/`limit` attributes and calls `exec_sql_readonly` (`:231`).
- Tools inventory: `w_tools` scans `llm_tool` COMMENTs (`:263-282`).
- Stored source: `prompt_templates(template_name, version, source, params)` + `render_template()` (`:291-310`). Seeded `agent_system` INSERT at `:314`.
- Entry: `agent_run_poml()` renders then `agent_loop()` (`:384`). **That loop still calls `http_call_llm` in SQL** — forbidden in v4/v5.

v1 tests skip XML if libxml is missing (`v1/run_tests.py` around C2/C3). Current pgembed configures Postgres `--with-libxml` (`pgembed/pgbuild/Makefile:20`).

v2 dropped the POML file; v4 prompt assembly is string concat, not slots.

### Microsoft POML (reference model, not runtime)

Local clone: `/Users/wxl/projects/poml` (same as `/Users/wxl/Projects/poml`). Docs: https://microsoft.github.io/poml/latest/

- Semantic components: `Role`/`Task`/`Example` in `packages/poml/components/instructions.tsx` (Role ~31, Task ~74, Example ~262).
- Table/document pull **files** (`src`, csv/excel/pdf), not SQL (`packages/poml/components/table.tsx`, `document.tsx`).
- Template engine is JS: `<let>`, `for`, `if`, `<include>`, `{{ }}` expressions (`packages/poml/file.tsx` `handleLet` ~501, `handleForLoop` ~444, `handleIfCondition` ~477).
- Output is chat `Message[]` with speakers system/human/ai/tool (`packages/poml/base.tsx` ~15,63; `writer.ts` `writeMessages` ~252). Python SDK: `python/poml/api.py` `poml()`.

v5 takes **ordered semantic parts + data components + messages as output**. It does not port the React IR, JS expressions, file `src=`, CSS stylesheets, or `poml`/`pomljs` SDKs into SQL.

### Where “base prompt” comes from today

1. Hardcoded `make_system_prompt()` format string (`v3/pg_agent_pgmq.sql:56`).
2. v1 seeded `prompt_templates` row `agent_system`.
3. Live catalog: `render_plugin_tools()` / v1 `w_tools`.
4. Live history: `fold_messages()` over `agent_steps` kinds `llm`/`tool`.

There is **no** generate-missing-part path: if role/task/examples are absent, nothing asks the model to write them into a table and re-assemble.

### User decisions already in (do not reopen)

- PGMQ messages are assembled in SQL/PL/pgSQL; each concrete step is a SQL retrieval.
- Worker consumes already-ordered `messages`; it does not concatenate system prompts.
- LLM HTTP never returns to SQL.
- Missing required parts: agent generates, stores in DB, later retrieve — this capability is required.
- v4 process: one `v5/<slug>/`, own DB, gates, v1–v4 immutable.
- No pgai, Redis, LiteLLM Proxy, Cordis-in-Postgres, `apply_queue_result` kind-if.
- `pgembed` already builds PostgreSQL with libxml support; no pgembed change is expected.

### Mid-flow decisions (2026-08-28; do not reopen)

User answers, locked:

1. **Kernel freeze:** like `v4/load.py` reading `v3/pg_agent_pgmq.sql`, `v5/load.py` **reads** the 12 v3/v4 SQL paths. Do not copy those files into `v5/kernel_freeze/sql/` or anywhere under `v5/`. Do not `import v4` at worker runtime.
2. **Generate-missing:** the **first visible agent turn** writes missing stored parts. User question is a hint in that turn’s messages. Not a hidden pre-LLM generate queue.
3. **Named tools:** insert stage `named_tools` (W5) so `action` may be a registered `wb_*` name. It lands after the pipeline (W4) and before generate-missing (W6).
4. **Part scope:** generated **role** and **task** are **globally reused** for the same `(recipe_name, recipe_version)`. Other stored `if_missing` parts (`output_format`, required `example`) use the same `prompt_parts` PK, so they follow the same rule. Generation turns and budget stay run-scoped. First writer wins (`ON CONFLICT DO NOTHING`).

## 2. Current-state analysis

### 2.1 Frozen v4 responsibilities and ownership

The v4 runtime has four relevant boundaries:

1. **SQL run state and enqueue**
   - `agent_runs` owns run identity, question, limits, parent/depth/session information, and budget limits.
   - `agent_steps` is append-only event history.
   - `agent_start()` creates a run and calls `enqueue_llm_request()`.
   - `enqueue_llm_request()` prepares one payload and sends it to `llm_requests`, with `x-pgmq-group=run_id`.

2. **SQL prompt preparation**
   - The v4 `prepare_llm_request()` overlay in `sticky_workbench/workbench_core.sql` reads the run and its steps.
   - It creates one system string using `make_system_prompt(...) || render_plugin_tools()`.
   - It calls `fold_messages(system, question, steps)`.
   - It returns the PGMQ payload, including `messages`, `model`, and `api_uri`.

3. **Out-of-DB worker**
   - `v4/plugin_taxonomy/worker.py` owns the poll connection and one sticky connection per `run_id`.
   - `v4/queue_kinds/worker.py` extends it for `llm_requests`, `embed_requests`, and `sql_heavy_requests`.
   - The worker calls the model or processor outside a SQL transaction.
   - It applies the result with `apply_queue_result(queue, msg_id, run_id, result)` and archives the message in the same transaction.

4. **Generic result application**
   - `apply_queue_result()` resolves a `queue_handler` binding by queue name.
   - It deduplicates `(queue_name,msg_id)` through `processed_queue_messages`.
   - It sets transaction-local `pg_agent.current_run_id`.
   - It dynamically invokes the registered `(text,jsonb) -> jsonb` handler.
   - It does not contain queue-kind-specific branches.
   - The `llm_requests` handler reaches the final v4 `apply_llm_result()` and then `apply_llm_response()`.

The v5 design preserves these ownership boundaries. The new pipeline belongs in SQL prompt/recipe files; generation execution belongs in the stage-local worker; generated-part persistence belongs in a queue handler; generic queue dispatch remains unchanged.

### 2.2 Existing message construction and transformation boundaries

The current v4 flow is:

```text
agent_start(question)
  -> INSERT agent_runs
  -> enqueue_llm_request(run_id)
  -> prepare_llm_request(run_id)
  -> make_system_prompt(max_rows)
  -> render_plugin_tools()
  -> string concatenation
  -> fold_messages(system, question, agent_steps)
  -> PGMQ llm_requests payload
  -> worker reads payload
  -> worker calls model outside SQL
  -> apply_queue_result()
  -> apply_llm_result()
  -> apply_llm_response()
  -> emit llm/tool/final/error/wait/budget steps
  -> optionally enqueue next llm request
```

The v5 replacement is at assembly **and** (after W5) at `apply_llm_response` tool dispatch. Generate-missing does **not** add a hidden PGMQ queue. All model work stays on `llm_requests`:

```text
agent_start(question)
  -> INSERT agent_runs and pin recipe version
  -> enqueue_llm_request(run_id)
  -> prepare_llm_request(run_id)
  -> assemble_prompt_messages(run_id)
  -> if ready: messages = full recipe (role/task/…/question/history)
  -> if required stored parts missing:
       -> messages = bootstrap recipe (generate instructions + user question as hint + store tool)
       -> still request_type=llm on llm_requests
  -> worker processes llm_requests outside SQL (visible llm step)
  -> apply_queue_result -> apply_llm_result -> apply_llm_response
  -> named action wb_store_prompt_part writes prompt_parts (ON CONFLICT DO NOTHING)
  -> next prepare: if parts complete, full recipe; else bootstrap again
```

The worker never concatenates prompt pieces. Bootstrap turns are ordinary `kind='llm'` / `kind='tool'` steps. `run_state` is `RUNNING`, not a synthetic wait.

### 2.3 Constraints that block a direct reuse of v1 POML

The v1 implementation is useful for concepts but cannot be loaded into v5:

- It depends on the v1 functional stack and its object names.
- Its `poml_write()`/writer registry is a runtime XML tree walker, whereas v5 needs an ordered SQL retrieval pipeline with explicit slot rows.
- Its template engine has different semantics and is not compatible with the requirement to reject JavaScript expressions.
- Its `agent_run_poml()` eventually calls `http_call_llm()` inside SQL.
- Its `<table query="...">` component executes SQL from XML attributes, which would introduce a second SQL execution path.

v5 therefore reuses only:

- PostgreSQL `xmlparse` and `xpath`;
- stored prompt source as an authoring concept;
- semantic component names such as role, task, example, and output format;
- JSONB chat-message output;
- the idea that catalog comments can register callable capabilities.

### 2.4 Constraints that must remain unchanged

The following are hard compatibility boundaries:

- `apply_queue_result(queue_name, msg_id, run_id, result)` remains the only generic SQL apply entrypoint.
- No queue-kind conditional logic may be added to `apply_queue_result()`.
- `apply_llm_response()` continues to understand `llm_decision` with `thought`, `action`, `action_input`, and `final_answer`.
- The v5 prompt lists tools by name. After the named-tool stage, `action` may be `execute_sql` **or** a registered `llm_tool` name. Until that stage loads, seeded recipes still describe the v4 `execute_sql` wrap so W4 tests can run.
- `exec_sql_readonly()` remains the outer SQL validator and retains its existing lexical false positives.
- Workbench tools remain current-sticky-connection tools.
- `fold_messages()` remains the authoritative representation of existing `llm` and `tool` history.
- Model/provider/API-key selection remains in Python. SQL may continue to include the existing non-secret `model` and `api_uri` GUC snapshots in queue payloads.
- Generated content must not be written into step metadata as unbounded prompt text or raw provider output.
- No new extension is needed. `xml`, `xpath`, JSONB, PGMQ, ordinary tables, and PostgreSQL functions are sufficient.

## 3. Design

### 3.1 Resolved design decisions

#### Recipe source of truth: relational runtime rows

**Decision:** `prompt_recipes`, `prompt_slots`, and `prompt_parts` are the canonical runtime source of truth. An optional XML document is stored as authoring/provenance input and compiled into those rows; XML is not parsed or walked during every request.

**Rationale:** The v5 requirement is an ordered SQL retrieval pipeline. Rows make position, requiredness, retriever identity, generation policy, and version pinning explicit. The v1 recursive writer registry would add runtime indirection and allow XML structure to determine execution behavior indirectly. Compilation keeps XML useful without making XML or arbitrary writer dispatch part of the hot path.

The runtime does not support:

- JavaScript expressions;
- `<let>`, `<include>`, or dynamic loop evaluation;
- `src=` file loading;
- CSS/style processing;
- CSV, PDF, filesystem, or external document retrieval;
- arbitrary SQL stored in XML attributes.

#### Generate-missing trigger: first visible LLM turn (user-confirmed)

**Decision:** Missing required stored parts do **not** enqueue a hidden `prompt_part_requests` queue. `prepare_llm_request()` still returns `request_type='llm'` and `enqueue_llm_request()` still sends `llm_requests`. When `assemble_prompt_messages()` reports `status='missing'`, prepare builds **bootstrap messages** from a seeded recipe `agent_system_generate` (or equivalent compile-time bootstrap slots): generate instructions, the **current user question as hint**, the list of missing `slot_key`s, and live tools including `wb_store_prompt_part`.

That first turn is a normal `agent_steps` `llm` event. The model writes parts via named tool calls. The next `prepare_llm_request()` retrieves stored parts. If required parts remain missing, the next turn is bootstrap again until parts exist or `max_steps` / budget / DLQ ends the run. Premature `final_answer` while required generatable parts are still missing does **not** emit `kind='final'`; apply re-enqueues bootstrap or records a bounded error if no steps remain.

`compile_prompt_recipe()` remains deployment/authoring only.

**Rationale:** Matches “agent 自己先生成” as a visible turn that can see the task. Keeps one model queue and one apply path. The user question is allowed in the generator prompt (mid-flow decision 2).

#### Generated versus live slots

The following policies are fixed:

| Component | Runtime source | Required by default | Generation allowed |
|---|---|---:|---:|
| `role` | `prompt_parts` | yes | yes |
| `task` | `prompt_parts` | yes | yes |
| `example` | `prompt_parts` | no unless recipe marks it required | yes when required |
| `output_format` | `prompt_parts` | yes | yes |
| `tools` | live `render_plugin_tools()` | yes | never |
| `question` | live `agent_runs.question` | yes | never |
| `history` | live `agent_steps` through existing fold semantics | yes, empty is valid | never |
| future retrieval/data component | live SQL retriever | recipe-specific | never in this increment |

**Global reuse (user-confirmed):** a generated `role` or `task` is stored once per `(recipe_name, recipe_version, slot_key)` and served to **every later run** of that recipe version, including runs with a different user question. The new question is only the live `question` slot; it must not rewrite `role`/`task`. The generating turn and its budget remain run-scoped. Concurrent generators: first successful insert wins; losers observe `replayed=true` and do not overwrite.

The v5 definition of `task` is a stable system instruction component. The user’s current natural-language question remains the separate live `question` user message. `wb_store_prompt_part` rejects a stored text equal to the current run’s `question`, so user-specific content is not persisted as a global recipe part.

#### Named tool calling: dedicated stage before generate-missing (user-confirmed)

**Decision:** After the pipeline overlays `prepare_llm_request()`, a v5 stage overlays `apply_llm_response()` so `action` may be either `execute_sql` or a registered `llm_tool` name (`wb_*`).

Protocol:

```json
{
  "thought": "...",
  "action": "wb_brief_query",
  "action_input": {"p_view": "south_rev", "p_limit": 20},
  "final_answer": null
}
```

`execute_sql` remains valid; its `action_input` stays a single SQL string. Named-tool `action_input` is a JSON object whose keys match `llm_tool.args`. `llm_decision.sql` continues to hold the raw `action_input` text; apply branches on `action`.

Apply algorithm for named tools:

1. Resolve `plugin_bindings` where `binding_type='llm_tool'` and `binding_name = action`.
2. Reject unknown names with the existing unknown-action observation, not a silent `execute_sql` wrap.
3. Parse `action_input` as JSONB object; reject arrays, scalars, extra keys, missing required args, and type mismatches using the COMMENT `args` map.
4. `EXECUTE` the bound `regprocedure` on the sticky run connection (`SECURITY INVOKER`).
5. Emit `kind='tool'` with the same outer envelope as today: `exec_sql_readonly`-style `{success,data,row_count}` wrapping the function jsonb, plus `sql` replaced by `tool`/`args` fields so history is auditable.
6. Nested tool `success` is still not implied by outer `success=true`.
7. Async `llm_tool.async=true` tools keep the v4 wait/defer path.

Generate-missing depends on this dispatcher so the bootstrap turn can call `wb_store_prompt_part` by name.

**Rationale:** User required named `wb_*` in this v5 sequence. Doing it after assembly and before generate-missing avoids teaching the generator `execute_sql` wrapping for a store tool.

### 3.2 v5 version boundary and frozen kernel

#### Load policy (user-confirmed: read-only v4 paths, same pattern as v4 reading v3)

`v4/load.py` does **not** copy `v3/pg_agent_pgmq.sql`; it lists that path as the first `SQL_LOAD_ORDER` entry and `path.read_text()`s it. `v5/load.py` does the same for the entire v4 stack: it **lists the same 12 paths**, still pointing at `v3/` and `v4/` files. It must not:

- copy those 12 files into `v5/kernel_freeze/sql/` or any other `v5/` directory;
- `from v4.load import SQL_LOAD_ORDER` / `files_through` (that would be `import v4`);
- symlink or mutate v3/v4 files.

Mirror this shape (paths identical to `v4/load.py` lines 14–27):

```python
V5_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = V5_ROOT.parent

# 1–12: read-only v3/v4 inputs (do not copy).
SQL_LOAD_ORDER: list[Path] = [
    AGENT_ROOT / "v3" / "pg_agent_pgmq.sql",
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "v4_runtime_guard.sql",
    AGENT_ROOT / "v4" / "plugin_taxonomy" / "plugin_taxonomy.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "workbench_core.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_brief_query.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_temp_views.sql",
    AGENT_ROOT / "v4" / "sticky_workbench" / "plugin_sql_curator.sql",
    AGENT_ROOT / "v4" / "queue_kinds" / "queue_kinds.sql",
    AGENT_ROOT / "v4" / "queue_kinds" / "plugin_async_tasks.sql",
    AGENT_ROOT / "v4" / "subagent_fanout" / "subagent_fanout.sql",
    AGENT_ROOT / "v4" / "session_durability" / "session_durability.sql",
    AGENT_ROOT / "v4" / "observability_budget" / "observability_budget.sql",
]
# Later stages append, in order:
#   V5_ROOT / "prompt_taxonomy" / "prompt_taxonomy.sql",
#   V5_ROOT / "recipe_components" / "prompt_recipe.sql",
#   V5_ROOT / "prompt_pipeline" / "prompt_pipeline.sql",
#   V5_ROOT / "named_tools" / "named_tools.sql",
#   V5_ROOT / "generate_missing" / "prompt_generation.sql",
```

At W1, `SQL_LOAD_ORDER` is **exactly those 12 paths** — do not list v5 overlay files that do not exist yet. Each later stage **appends** its SQL file and extends `STAGE_THROUGH`. `files_through("kernel_freeze")` is always the 12-path prefix. `REFRESH_AFTER` for that prefix is the same membership as `v4/load.py` `REFRESH_AFTER`, expressed as those v4 paths.

W1 freeze test (documented source read, not runtime `import v4` in the worker): read `v4/load.py` as text and assert its 12 `SQL_LOAD_ORDER` relative paths equal v5’s first 12 entries, in order. Also `git diff` empty for v1–v4 and no `*.sql` under `v5/kernel_freeze/`.

Python worker: v4 workers must not be mutated. W1 places a v5-local worker under `v5/kernel_freeze/worker.py` adapted from the v4 chain (`plugin_taxonomy` → `queue_kinds` → `observability_budget`) with imports rewritten to `v5.kernel_freeze`. Later stages may copy-extend that **Python** file only. Runtime `import v4` is forbidden in v5 workers. Tests may read v4 source files as text for the freeze gate above.

W1 does **not** hash-copy SQL. It `read_text()`s v3/v4 paths into `agent_v5_kernel_freeze` and asserts v4 gate behavior plus “v5 code does not write v4 files.”

#### Frozen behavior

W1 verifies that loading those v4 paths still provides:

- the runtime guard for `http_call_llm()` and `agent_run()`;
- `agent_start()` → `enqueue_llm_request()` → v4 `prepare_llm_request()`;
- generic `apply_queue_result()`;
- sticky worker connections;
- v4 budget and wait semantics;
- PGMQ archive-after-apply behavior.

After W1 passes, only v5-local overlays may replace symbols.

### 3.3 Prompt taxonomy extension

#### Choice of extension mechanism

Use a new `plugin_bindings.binding_type = 'prompt_slot'` rather than a sibling table.

This keeps prompt retrievers in the same validated COMMENT taxonomy and lets the pipeline resolve retrievers through the same `regprocedure` catalog. `apply_queue_result()` continues filtering only `binding_type='queue_handler'`; it does not need a queue-kind branch.

#### Modified `plugin_bindings` constraints

The v5 taxonomy overlay changes the allowed values to:

```text
llm_tool
queue_handler
prompt_slot
```

The per-type nullability constraint becomes:

- `llm_tool`: `queue_name`, `queue_kind`, and `consumer` must be null;
- `queue_handler`: all three queue fields must be non-null;
- `prompt_slot`: all three queue fields must be null.

The existing primary key `(binding_type, binding_name)` remains.

Do **not** add a `prompt_generate` queue kind. Generation uses `llm_requests` and `wb_store_prompt_part`. `apply_queue_result()` stays unchanged. Legal `capability` list gains `prompt_mutation` for the store tool.

No queue-specific branch is added to `apply_queue_result()`.

#### Prompt-slot COMMENT contract

Every SQL prompt retriever receives a top-level `plugin` object and a `prompt_slot` object, and must not also carry `llm_tool` or `queue_handler`.

Example shape:

```json
{
  "plugin": {
    "name": "plugin_prompt_components"
  },
  "prompt_slot": {
    "name": "prompt_stored_part",
    "description": "Retrieve a stored role, task, example, or output-format part",
    "component_types": [
      "role",
      "task",
      "example",
      "output_format"
    ],
    "source": "stored",
    "generation": "if_missing",
    "args": {
      "p_run_id": "text",
      "p_config": "jsonb"
    },
    "returns": "jsonb"
  }
}
```

Required validation:

- `plugin.name` follows the existing `plugin_[a-z][a-z0-9_]*` rule.
- The function is a public ordinary function with `prokind='f'`.
- The function return type is `jsonb`.
- The function has exactly two named arguments: `p_run_id text`, `p_config jsonb`.
- `prompt_slot.name` equals `proname`.
- `component_types` is a non-empty array containing only the closed component set:
  - `role`
  - `task`
  - `example`
  - `output_format`
  - `tools`
  - `question`
  - `history`
- `source` is `stored` or `live`.
- `generation` is `never` or `if_missing`.
- `source=live` requires `generation=never`.
- A prompt-slot function cannot also declare `llm_tool` or `queue_handler`.
- Prompt-slot functions must be `STABLE` or `IMMUTABLE` (`provolatile` in `{s,i}`); `refresh_plugins()` rejects `VOLATILE` retrievers.
- `source=live` requires `generation=never` (already). Extra negative tests: live+`if_missing`, prompt_slot combined with `llm_tool`, illegal `component_types`.
- `job_handler` and legacy v2 `workbench_plugin` metadata remain rejected.
- Duplicate prompt-slot names are rejected.

The v5 `refresh_plugins()` overlay must retain validate-all-then-replace behavior:

1. Scan all relevant public function comments.
2. Build and validate candidate package and binding sets without modifying registry tables.
3. Validate prompt-slot metadata alongside existing LLM and queue metadata.
4. After every candidate is valid, execute `TRUNCATE TABLE plugin_bindings, plugin_packages`.
5. Insert all candidate packages and bindings in the same transaction.
6. Roll back the truncate and inserts on any error, preserving the previous registry contents.

The refresh function must continue to serialize concurrent rebuilds through the table lock acquired by `TRUNCATE`.

#### Prompt retriever interfaces

W3 registers these prompt-slot retrievers (W6 adds `prompt_live_missing`):

```text
prompt_stored_part(p_run_id text, p_config jsonb) RETURNS jsonb
prompt_live_tools(p_run_id text, p_config jsonb) RETURNS jsonb
prompt_live_question(p_run_id text, p_config jsonb) RETURNS jsonb
prompt_live_history(p_run_id text, p_config jsonb) RETURNS jsonb
```

All are synchronous, SQL-side retrieval functions. None performs network I/O or arbitrary SQL from caller-supplied text.

Each returns a JSONB envelope:

```json
{
  "success": true,
  "messages": [
    {
      "role": "system|user|assistant|tool",
      "content": "bounded text"
    }
  ],
  "source": "stored|live",
  "component": "role|task|example|output_format|tools|question|history"
}
```

A missing stored part is represented as:

```json
{
  "success": false,
  "Type": "PROMPT_PART_MISSING",
  "Phase": "Resolution",
  "slot_key": "task",
  "component": "task"
}
```

The assembler, not the retriever, decides whether that missing result is optional, generatable, or a hard recipe error.

### 3.4 Relational recipe and part model

#### `prompt_recipes`

Create:

```text
prompt_recipes
├── recipe_name   text
├── version       integer
├── source_xml    xml not null
├── format_version integer not null default 1
├── active        boolean not null default false
├── created_at    timestamptz not null default now()
└── PRIMARY KEY (recipe_name, version)
```

Add a partial unique index allowing at most one active version per recipe name.

Runtime rules:

- Recipe versions are immutable after activation.
- A new definition is a new version.
- `source_xml` is authoring/provenance data.
- Runtime retrieval uses `prompt_slots` and `prompt_parts`, not `source_xml`.
- The default recipe is `agent_system`, version `1`.

#### `prompt_slots`

Create:

```text
prompt_slots
├── recipe_name       text
├── recipe_version    integer
├── position          integer
├── slot_key          text
├── component_type    text
├── retriever_name    text
├── required          boolean not null
├── generation_policy text
├── config            jsonb not null default '{}'
└── PRIMARY KEY (recipe_name, recipe_version, position)
```

Additional constraints:

- `position > 0`.
- `slot_key` is a bounded ASCII identifier-like key.
- `(recipe_name, recipe_version, slot_key)` is unique.
- `component_type` is one of `role`, `task`, `example`, `output_format`, `tools`, `question`, `history`.
- `generation_policy` is `never` or `if_missing`.
- Live components must use `never`.
- `retriever_name` must resolve to a registered `prompt_slot` binding during compile and assembly.
- `config` is bounded JSONB. The compiler rejects oversized hints and unknown configuration keys.

#### `prompt_parts`

Create:

```text
prompt_parts
├── recipe_name          text
├── recipe_version       integer
├── slot_key             text
├── component_type       text
├── value_kind           text
├── value                jsonb not null
├── source                text not null
├── generator_request_id text
├── content_hash         text not null
├── created_at           timestamptz not null default now()
└── PRIMARY KEY (recipe_name, recipe_version, slot_key)
    -- no updated_at: first-writer-wins never updates rows
    -- PK is recipe-version global: role/task reused by every run of that version
```

Allowed `value_kind`:

- `text`: `value` is a JSONB string.
- `messages`: `value` is an array of bounded `{role,content}` objects.

Allowed `source`:

- `seeded`
- `generated`

Validation rules:

- Scalar components use `value_kind='text'`.
- `example` components use `value_kind='messages'`.
- Generated text is limited to 8,000 characters.
- Generated example arrays are limited to 16 messages and 8,000 characters per message.
- `content_hash` is SHA-256 of `value::text` (jsonb canonical text). No `updated_at` column.
- Generated inserts use first-writer-wins with `ON CONFLICT DO NOTHING`; a second generation result must never overwrite an existing recipe part.
- After a `role`/`task` row exists for `(recipe_name, recipe_version)`, a later `agent_start()` with a **different question** must assemble those same rows (`prompt_mode` is not `generate_missing` for that slot).

#### Run recipe pinning

Add to `agent_runs`:

```text
prompt_recipe_name    text
prompt_recipe_version integer
```

The v5 recipe overlay adds a `BEFORE INSERT` trigger:

- For a top-level run with no explicit recipe, select the active `agent_system` recipe.
- For a child run, inherit the parent’s pinned recipe name/version.
- Reject an explicitly supplied recipe that does not exist.
- After backfill, both columns become `NOT NULL`.

This avoids changing every existing v4 run-creation call site while ensuring an active-recipe change cannot alter an existing run’s prompt definition.

If no recipe is `active`, `agent_start()` fails and rolls back. Deactivating the last version is an operator error; recover by compiling/activating a version. Do not `DELETE` `prompt_parts` of an active version except in tests (`DELETE` in W6 tests is explicit fixture cleanup, not a product API). Replace bad generated text by compiling a **new version**. Pinned runs keep the old version even if it is no longer active.

### 3.5 XML authoring and compilation

#### Scope

Implement an SQL-only compiler using PostgreSQL `xmlparse`, `xpath`, `jsonb`, and ordinary SQL/PL/pgSQL.

The accepted direct-child grammar is:

```xml
<poml>
  <role>...</role>
  <task>...</task>
  <example>
    <user>...</user>
    <assistant>...</assistant>
  </example>
  <output-format>...</output-format>
  <tools/>
  <question/>
  <history/>
</poml>
```

Allowed attributes are limited to:

- `required="true|false"`;
- `generate="never|if_missing"`;
- `hint="bounded generation hint"`;
- `slot="bounded slot key"` for examples.

Reject all other attributes.

The compiler must reject:

- malformed XML;
- a root other than `<poml>`;
- unknown component tags;
- duplicate singleton components (`role`, `task`, `output-format`, `tools`, `question`, `history`);
- invalid example children;
- empty required static text;
- unbounded source or hint text;
- JavaScript-looking expression syntax used as a template language;
- `<include>`, `<let>`, `<for>`, `<if>`, or file `src=` constructs.

The compiler does not evaluate expressions. Literal `{{...}}` text is rejected in the authoring source rather than interpreted.

#### Compiler interface

```text
compile_prompt_recipe(
    p_recipe_name text,
    p_version integer,
    p_source xml,
    p_activate boolean default false
) RETURNS integer
```

The function is VOLATILE and must update the recipe, slots, and seeded parts atomically. It writes the XML document, derives ordered slots from `xpath('/poml/*', p_source)` in document order, assigns `position = 10 * ordinal` (1-based; 10, 20, …), and rejects more than 32 direct children. It validates every component and inserts the runtime rows.

If `p_activate=true`, it deactivates the previous version and activates the new version in the same transaction. Existing runs remain pinned to their old version.

The compiler may use small internal helpers such as:

```text
prompt_xml_tag(xml) RETURNS text
prompt_xml_text(xml) RETURNS text
prompt_xml_attributes_valid(xml) RETURNS boolean
```

These helpers are not prompt retrievers and are not registered as `prompt_slot` bindings.

#### Seeded `agent_system` recipe

The seeded recipe migrates the semantic content of v4 `make_system_prompt()` into rows rather than calling that function at runtime.

The default ordered slots are:

| Position | Slot | Component | Retriever | Required |
|---:|---|---|---|---:|
| 10 | `role` | `role` | `prompt_stored_part` | yes |
| 20 | `task` | `task` | `prompt_stored_part` | yes |
| 30 | `example_1` | `example` | `prompt_stored_part` | no |
| 40 | `output_format` | `output_format` | `prompt_stored_part` | yes |
| 50 | `tools` | `tools` | `prompt_live_tools` | yes |
| 100 | `question` | `question` | `prompt_live_question` | yes |
| 110 | `history` | `history` | `prompt_live_history` | yes |

The seeded role/task/output format text must preserve the v4 protocol and restrictions:

- `thought/action/action_input/final_answer`;
- one SQL statement per round;
- no trailing semicolon;
- bounded result rows;
- no arbitrary writes or DDL;
- query-before-finalization behavior;
- session KV semantics;
- listed workbench functions are called inside `SELECT`;
- the outer observation envelope and nested tool result must be distinguished.

The seed may include one optional example, but the pipeline must support examples represented as multiple user/assistant messages.

### 3.6 Ordered SQL retrieval pipeline

#### Assembly interface

Add:

```text
assemble_prompt_messages(
    p_run_id text
) RETURNS jsonb
```

The function is `STABLE` and does not write tables, send PGMQ messages, call model providers, or invoke arbitrary user SQL.

Its result has one of these statuses:

```json
{
  "status": "ready",
  "recipe_name": "agent_system",
  "recipe_version": 1,
  "messages": [...],
  "slot_trace": [...]
}
```

```json
{
  "status": "missing",
  "recipe_name": "agent_system",
  "recipe_version": 1,
  "missing": [
    {
      "position": 20,
      "slot_key": "task",
      "component": "task",
      "generation_policy": "if_missing",
      "config": {}
    }
  ],
  "slot_trace": [...]
}
```

Hard retrieval or recipe errors are returned as bounded structured errors:

```json
{
  "status": "error",
  "success": false,
  "Type": "PROMPT_ASSEMBLY_ERROR",
  "Phase": "Recipe|Resolution|Validation|Execution",
  "Problem": "specific bounded failure",
  "Solution": "actionable recovery"
}
```

`prepare_llm_request()` converts hard errors into an exception, preserving the existing unknown-run failure behavior. Missing generatable parts: **W4** raises `PROMPT_ASSEMBLY_ERROR` (bootstrap recipe does not exist yet). **W6** replaces that branch with bootstrap `llm` messages. W4 tests assert `assemble_prompt_messages()` `status='missing'` directly; they do not require a successful `enqueue_llm_request()` for missing parts.

#### Algorithm

For the run’s pinned recipe:

1. Load all `prompt_slots` ordered by `position`.
2. Reject a missing retriever binding or a component/retriever mismatch.
3. For each slot:
   - invoke the registered `(text,jsonb) -> jsonb` retriever;
   - validate the returned envelope;
   - if it returns `PROMPT_PART_MISSING`:
     - if the slot is optional, record an omitted optional slot and continue;
     - if `generation_policy='if_missing'`, append it to `missing`;
     - otherwise return a hard recipe error;
   - if successful, append its `messages` array to the output JSONB array.
4. Reject invalid message roles, null content, oversized content, more than 32 slots, more than 128 messages, or a serialized message array over 262144 bytes. These four caps are SQL constants inside `assemble_prompt_messages()` / `wb_store_prompt_part`, not GUCs.
5. If any required generatable part is missing, return `status='missing'` with no usable LLM message array.
6. Otherwise return `status='ready'` with the ordered message array.

The assembly operation uses JSONB array concatenation only to append message arrays in order. It does not construct one system string by concatenating role/task/tools text.

#### Slot retriever behavior

`prompt_stored_part`:

- Reads the run-pinned recipe and `p_config.slot_key`.
- Requires a `prompt_parts` row for required parts.
- Returns a system message for text components.
- Returns the stored user/assistant message array for examples.
- Never calls `render_plugin_tools()` or reads history.

`prompt_live_tools`:

- Calls existing `render_plugin_tools()`.
- Returns one system message containing the live catalog section.
- The no-tools section remains a valid successful live result.
- It never copies or caches the catalog.

`prompt_live_question`:

- Reads `agent_runs.question` for `p_run_id`.
- Returns exactly one user message.
- It does not read `prompt_parts`.

`prompt_live_history`:

- Reads the run’s `agent_steps` ordered by `seq`.
- Reuses the existing `fold_messages()` mapping for `llm` and `tool` steps, removing the system and question entries from that result so the slot returns history only.
- Ignores `budget`, `wait`, and other non-`llm`/`tool` events (no `prompt_generation` step kind).
- Returns an empty message array for a new run.

#### `prepare_llm_request()` after v5

The v5 overlay preserves the existing function signature:

```text
prepare_llm_request(p_run_id text) RETURNS jsonb
```

For a ready recipe it returns the existing payload keys plus v5 fields:

```json
{
  "request_type": "llm",
  "run_id": "...",
  "question": "...",
  "step": 1,
  "max_steps": 10,
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "prompt_recipe": {
    "name": "agent_system",
    "version": 1
  },
  "model": "...",
  "api_uri": "..."
}
```

For missing required generatable parts it still returns `request_type='llm'` (bootstrap messages), plus:

```json
{
  "prompt_mode": "generate_missing",
  "missing_parts": [{"slot_key": "task", "component": "task"}]
}
```

The v5 implementation must not reference `make_system_prompt()` and must not directly call `render_plugin_tools()`; the latter is invoked only through the registered live slot retriever.

When assembly returns `status='missing'`, `prepare_llm_request()` does **not** return `request_type='prompt_generate'`. It returns `request_type='llm'` with bootstrap `messages` (recipe `agent_system_generate`), `prompt_mode='generate_missing'`, pinned recipe metadata, and the same payload keys the worker already understands. `enqueue_llm_request()` always `pgmq.send`s `llm_requests` with `x-pgmq-group=run_id`.

#### `enqueue_llm_request()` after v5

Keep the signature:

```text
enqueue_llm_request(p_run_id text) RETURNS bigint
```

Preserving the return type avoids changing v4 callers such as `_resume_from_queue_result()` and fan-out continuation. There is no second queue for prompt parts. If prepare raises a hard assembly error, enqueue fails and no message is sent.

### 3.7 Named `wb_*` dispatch

Stage `named_tools` overlays `apply_llm_response()` only.

`execute_sql` path is unchanged (`exec_sql_readonly`, lexical false positives preserved).

Named path: `action` matches `plugin_bindings.binding_name` for `llm_tool`. Call the bound function with named JSON args on the sticky connection. Observation payload:

```json
{
  "tool": "wb_brief_query",
  "args": {"p_view": "south_rev", "p_limit": 20},
  "observation": "{...function jsonb...}"
}
```

`fold_messages()` already maps `kind='tool'` to a user Observation. Keep that. Tests must show sticky TEMP views created by `action=wb_temp_view_create` are visible on the next turn via `wb_brief_query`.

Do not add queue-kind branches. Async tools still return `defer=true` from the SQL function; wait detection stays catalog-driven (`llm_tool.async`).

W5 overlays **only** `apply_llm_response()`. Do not overlay `parse_llm_output()`: `llm_decision.sql` already stores raw `action_input` (`v3/pg_agent_pgmq.sql`, `d.sql := j ->> 'action_input'`).

JSON→SQL args: `refresh_plugins()` already checks COMMENT `args` against the PG signature. At call time, apply builds `USING` values from JSONB; a cast failure becomes a structured `NAMED_TOOL_ERROR` observation (`Phase=Validation`), not an uncaught exception that aborts apply. Coerce jsonb string/number/bool/null to the declared PG type names `text`, `integer`, `boolean`, `jsonb` only. Other PG types in `llm_tool.args` are rejected at refresh.

W3 seeds `agent_system` v1 text that still describes `execute_sql` wrapping so W4 tests pin version 1. W5 compiles and **activates `agent_system` v2** whose stored role/task/output-format describe named `wb_*` actions. W4 tests must pin `prompt_recipe_version=1`. W6/W7 use the active v2 recipe. Generate-missing must not start until named dispatch exists.

### 3.8 Generate-then-store-then-retrieve (visible turn)

No `prompt_part_requests` queue. No `apply_prompt_part_result` handler. No `prompt_generation_waits` wait-row protocol.

**Export superseded (do not reintroduce):** `prompt_generation_requests`, `prompt_generation_waits`, `prompt_part_requests` (+ DLQ), queue kind `prompt_generate`, `apply_prompt_part_result()`, and a `run_state` overlay for prompt waits. Bootstrap turns are ordinary `llm`/`tool` steps, so budget and `RUNNING` status fall out of the existing apply loop.

#### Store tool

```text
wb_store_prompt_part(p_slot_key text, p_value jsonb) RETURNS jsonb
```

COMMENT: `plugin` + `llm_tool` with `capability` a new legal value `prompt_mutation` (W2 taxonomy must allow it) or reuse `temp_view_mutation` only if W2 would otherwise expand capabilities anyway — **prefer adding `prompt_mutation`** so store is not confused with TEMP views.

Behavior:

- `agent_current_run_id()` required.
- Slot must belong to the run’s pinned recipe and have `generation_policy='if_missing'`.
- Reject live slots (`tools`, `question`, `history`).
- Validate before insert:
  - text components: `value_kind='text'`, JSON string, length 1..8000, not equal to the run’s `question` (reject echo of the user question into global system parts);
  - example components: `value_kind='messages'`, array of 1..16 objects, each `role` in (`user`,`assistant`), non-empty content ≤8000 chars;
  - `value_kind` must match `component_type` (text vs messages);
  - reject API keys, `Bearer ` prefixes, filesystem-path-shaped strings, and objects that look like full provider payloads (`choices`, `usage` at top level).
- Persist only the extracted `value`, never the raw model `raw` field.
- `INSERT INTO prompt_parts ... ON CONFLICT DO NOTHING`.
- Return `{success, stored, replayed, slot_key, recipe_name, recipe_version}`.
- `replayed=true` is a successful non-error observation; bootstrap task text must tell the model that another run already stored the part and it should continue filling remaining slots.
- Emit no extra LLM enqueue; the ordinary apply loop enqueues the next LLM if the model did not final (and while parts are missing, final is suppressed).

#### Bootstrap recipe

Seed `agent_system_generate` version 1:

| Position | Slot | Source |
|---:|---|---|
| 10 | generate_role | stored |
| 20 | generate_task | stored (instructs: write missing slots via `wb_store_prompt_part`) |
| 50 | tools | live |
| 60 | missing_list | live retriever `prompt_live_missing` — JSON list of missing slot_key/component/hint |
| 100 | question | live (user question is the hint) |
| 110 | history | live |

`prompt_live_missing` is a fifth prompt-slot retriever registered in the generate-missing stage. `source=live`, `generation=never`.

When `assemble_prompt_messages(run_id)` for the **pinned user recipe** is `missing`, `prepare_llm_request()` assembles **bootstrap** messages from `agent_system_generate` instead of failing or sending a non-LLM payload.

Bootstrap recipe slots are all `generation_policy='never'` and are seeded in the same W6 transaction as the recipe. If assembling `agent_system_generate` itself returns `missing` or `error`, `prepare_llm_request()` raises `PROMPT_ASSEMBLY_ERROR` (no nested bootstrap).

`prompt_live_missing(p_run_id, p_config)` computes the missing list for the **pinned user recipe only** (never for the bootstrap recipe). It must not call `assemble_prompt_messages` on the bootstrap recipe. Implementation: scan `prompt_slots`/`prompt_parts` for the pinned recipe. The user recipe must not contain a `missing_list` slot. Bootstrap payload `prompt_recipe` names the user recipe; `prompt_mode='generate_missing'` is also copied into the llm step payload (`payload->>'prompt_mode'`) so operators can see bootstrap turns without a new step kind.

Bootstrap turns **count** toward `max_steps` and `record_budget_step()`. There is no separate generation allowance. Tests start runs with `max_steps` large enough to cover store turns plus the task.

The bootstrap recipe name is hard-coded as `agent_system_generate` in the W6 `prepare_llm_request()` overlay (one global generator recipe).

Premature-final detection: the W6 `apply_llm_response()` overlay, before emitting `kind='final'`, runs an `EXISTS` probe over required `if_missing` slots of the pinned user recipe that still lack `prompt_parts`. Do not re-enter full `assemble_prompt_messages()` on every apply unless the probe is insufficient.

#### Apply overlay while parts are missing

In `apply_llm_response()`, if the pinned user recipe still has required generatable parts missing:

- `final_answer` does not emit `kind='final'`.
- If steps remain, emit tool/llm as usual and enqueue the next LLM (bootstrap again).
- If `max_steps` reached, emit `kind='error'` `missing_prompt_parts`.

Once all required stored parts exist, later turns use the full user recipe (including the same question and history, so bootstrap llm/tool steps appear in history unless `fold_messages` filters `prompt_mode` — **do not filter them**; the user asked for a visible turn).

#### Recipe-global first-writer-wins (role/task reuse)

`prompt_parts` PK `(recipe_name, recipe_version, slot_key)` is the reuse key. There is no `run_id` in the PK.

- Run A of `agent_system` v2 generates `role`/`task` → rows exist for that version.
- Run B of `agent_system` v2, even with a different question, **skips bootstrap** for those slots and retrieves the same text.
- Run C of `agent_system` v3 (new compile) has its own empty parts and may generate again.
- Concurrent A and B: `ON CONFLICT DO NOTHING` keeps the first committed text; the loser gets `replayed=true`.

#### Tables

Keep `prompt_recipes` / `prompt_slots` / `prompt_parts` only. Do not add `prompt_generation_requests` or extra PGMQ queues.

Optional audit: the `wb_store_prompt_part` tool observation plus `prompt_parts.source='generated'` and `generator_request_id` set to the current `run_id` (informational; not a second PK).

### 3.9 Worker and concurrency model

#### Stage-local worker

`v5/kernel_freeze/worker.py` is adapted from the v4 worker chain and does not `import v4`. Named tools and generate-missing do **not** add poll queues. `llm_fn` injection covers bootstrap turns. Retain VT, `MAX_READ_CT`, apply+archive one transaction, sticky `conn_for`.

#### Ordering and duplicate behavior

- Multiple `wb_store_prompt_part` calls in one run or across runs: first insert wins.
- Duplicate PGMQ apply: `processed_queue_messages` + `last_applied_hash`.
- Crash after read: existing v4 VT replay; hash prevents duplicate llm steps.
- DLQ on the **llm** queue fails the run via `fail_run()`; already-written global parts remain for later runs.

#### Cancellation and interruption

- Worker kill before apply: message remains for VT replay; parts written only if a previous apply committed.
- TEMP session still dies with sticky close; `prompt_parts` are durable.

### 3.10 Error handling and edge cases

| Operation | Failure | Required behavior |
|---|---|---|
| Recipe lookup | Run has no pinned recipe | Raise bounded `PROMPT_ASSEMBLY_ERROR`; do not send a queue message. |
| Recipe lookup | Active recipe missing during new run | `agent_start()` transaction fails and rolls back the run insert. |
| XML compile | Malformed XML or unsupported tag | Roll back recipe, slot, and part changes; report validation error. |
| XML compile | Duplicate singleton component | Roll back the whole compile. |
| XML compile | Unsupported JS/file construct | Reject as validation error; do not interpret it. |
| Slot assembly | Missing optional part | Omit it and continue. |
| Slot assembly | Missing required generatable part | Assemble bootstrap messages; still enqueue `llm_requests` (visible turn). |
| Slot assembly | Missing required non-generatable part | Raise a recipe error; no model call. |
| Slot assembly | Missing retriever binding | Return a resolution error; do not silently skip the slot. |
| Slot assembly | Retriever returns malformed envelope | Return a bounded execution/validation error; do not enqueue. |
| Slot assembly | Message count/size exceeds bound | Fail closed with `PROMPT_TOO_LARGE`. |
| Named action | Unknown `wb_*` name | Tool observation unknown-action; do not wrap as `execute_sql`. |
| Named action | Bad JSON args | Structured validation error observation; no function call. |
| Store part | Live slot or `generation_policy=never` | `wb_store_prompt_part` returns structured error; no write. |
| Store part | Part already exists | `stored=false`, `replayed=true`; no overwrite. |
| Bootstrap | Premature `final_answer` while required parts missing | Do not emit `kind='final'`; enqueue another LLM or error at max_steps. |
| Generation LLM | Budget usage absent under active hard budget | Fail closed; do not treat bootstrap success as user SUCCESS. |
| Generation LLM | `llm_requests` DLQ | `fail_run()`; already-written global parts remain. |
| Queue replay | Same `(queue,msg_id)` reapplied | Generic dispatcher returns replay result; no duplicate part, step, or LLM enqueue. |
| Tool catalog | No installed tools | Existing `render_plugin_tools()` no-tools section becomes a successful live slot. |
| History | No prior `llm`/`tool` steps | Return an empty history array. |
| History | `budget`/`wait` steps present | Exclude them from folded conversation, preserving `fold_messages()` (`llm`/`tool` only). Bootstrap llm/tool steps **remain** in history (visible turn). |
| Outer SQL | Embedded blocked keyword triggers v4 lexical false positive | Preserve the existing error; do not weaken `exec_sql_readonly()`. |
| SQL HTTP | Direct `http_call_llm()` or `agent_run()` call | v4 runtime guard continues to raise the explicit prohibition. |

### 3.11 Persistence and serialization

#### New persistent schema

The v5 schema additions are:

- `prompt_recipes`;
- `prompt_slots`;
- `prompt_parts`;
- `agent_runs.prompt_recipe_name`;
- `agent_runs.prompt_recipe_version`;
- `plugin_bindings.binding_type='prompt_slot'`;
- `wb_store_prompt_part`;
- bootstrap recipe `agent_system_generate`.

No extra PGMQ queue for prompt parts.

No existing `agent_steps.payload` shape changes. The existing `meta` field and budget rules remain.

#### Migration strategy

The supported v5 deployment path is a fresh `agent_v5_<stage>` database created by each stage setup script. No v4 database is upgraded in place.

For a future existing v5 database:

1. Add recipe pin columns as nullable.
2. Install and activate `agent_system` version 1.
3. Backfill null run recipe columns to `agent_system`, version 1.
4. Install the pinning trigger.
5. Validate every existing run references an existing recipe version.
6. Set both columns `NOT NULL`.
7. Skip generation tables and extra queues — none exist. Install `wb_store_prompt_part` and the bootstrap recipe instead.
8. Refresh the plugin registry only after the v5 taxonomy constraints are installed.
9. Rebuild prompt parts only through explicit recipe compilation; do not infer parts from old concatenated prompt strings.

Existing active runs must be stopped or allowed to finish before changing the v5 registry or recipe definitions. New recipe versions never mutate old versions.

#### Rollback

Rollback is database-level, not in-place code rollback:

1. Stop v5 workers and stop accepting new v5 runs.
2. Leave generated v5 tables and queues intact for evidence if needed.
3. Switch callers back to the immutable v4 database and v4 worker.
4. Do not load v4 SQL into a v5 database after v5 has added the `prompt_slot` binding type; the old v4 constraints and refresh function do not understand the v5 taxonomy.
5. If the v5 database must be removed, drop only the relevant `agent_v5_<stage>` database with `WITH (FORCE)`.

The v4 database remains available because v5 uses separate databases.

### 3.12 Tradeoffs and rationale

- **Rows as runtime source of truth:** directly satisfies ordered SQL retrieval and makes requiredness/generation/versioning queryable; runtime XML walking would add an unnecessary interpreter layer.
- **XML as compile-time authoring:** preserves the POML-inspired authoring concept and PostgreSQL `xml`/`xpath` implementation while avoiding JavaScript semantics and arbitrary XML-driven execution.
- **New `prompt_slot` binding type:** keeps prompt retrievers in the existing COMMENT/`regprocedure` registry, while `apply_queue_result()` remains unchanged because it filters queue handlers.
- **No extra generate queue:** bootstrap turns are ordinary `llm_requests` results, so generated text is stored only through `wb_store_prompt_part`, never through `apply_llm_response` parse-as-decision.
- **Visible bootstrap LLM turn:** matches “agent generates missing parts” and can use the current question as hint; hidden generate queues were rejected mid-flow.
- **Named `wb_*` actions:** required in this v5 sequence; generate-missing stores via `wb_store_prompt_part` rather than a second apply handler.
- **Recipe-global parts:** first writer wins; later runs skip bootstrap if parts exist.
- **`execute_sql` kept:** ad-hoc SQL still works; named tools are an additional apply branch, not a replacement.
- **No change to `fold_messages()`:** history is already correctly represented; the new history retriever wraps its existing behavior instead of duplicating its event mapping.
- **No pgembed change:** the required `xml`/`xpath` support is already compiled through `--with-libxml`, and PGMQ is already bundled.

### 3.13 Residual questions and validation gates

No unresolved product decision is allowed to block implementation. The following are implementation validations with prescribed outcomes:

1. **Exact final v4 worker source**
   - `v4/observability_budget/worker.py` exists and subclasses `v4.queue_kinds.worker.AgentWorker`.
   - W1 adapts that chain under `v5/kernel_freeze/` with rewritten imports. SQL is loaded from v4 paths, not copied. Do not `import v4` at runtime.

2. **PostgreSQL XML behavior**
   - In W3, validate `xmlparse(CONTENT ...)`, `xpath('/poml/*', ...)`, text extraction, and XML comment/attribute handling against the bundled PostgreSQL 18.4.
   - If the expected libxml functions are unavailable, stop the stage and investigate the pgembed build; do not replace XML with Python parsing.

3. **PGMQ function signatures**
   - In W5 setup, verify `pgmq.create`, `pgmq.send`, `pgmq.read`, `pgmq.archive`, and `pgmq.purge_queue` signatures against the bundled PGMQ extension.
   - Adapt only the v5-local worker if the bundled signature differs; do not change the queue contract or add another queue system. Do not copy v4 SQL.

4. **Recipe scope**
   - Locked: recipe-global parts, first-writer-wins. Do not change PK after W3.

5. **Named action protocol**
   - Mandatory (W5). Generate-missing (W6) must not start until named dispatch passes.

6. **W3 vs W5 seed text**
   - Locked: W3 seeds `agent_system` v1 with `execute_sql` wording; W4 pins version 1; W5 activates v2 named-tool wording.

7. **Generation step budget**
   - Locked: bootstrap turns consume `max_steps` and token/cost budget. No separate allowance.

8. **Bootstrap recipe identity**
   - Locked: hard-coded `agent_system_generate` in the W6 overlay.

9. **Assembly bounds**
   - Locked: constants 32 slots, 128 messages, 262144 bytes, 8000-char parts. Not GUCs.

## 4. File-by-file impact

### New: `v5/README.md`

- Document the seven-stage order, stage databases, commands, read-only v4 SQL load, SQL HTTP prohibition, prompt-slot taxonomy, named tools, visible generate-missing, and no-pgembed-change decision.
- Record final gate counts and dates after implementation.
- Depend on all stage README evidence.

### New: `v5/load.py`

- Duplicate the 12 Path literals from `v4/load.py` `SQL_LOAD_ORDER`, still pointing at `v3/` and `v4/` files (see §3.2). Then append v5 overlay files.
- `STAGE_THROUGH["kernel_freeze"] = 12`. Later keys: `prompt_taxonomy`, `recipe_components`, `prompt_pipeline`, `named_tools`, `generate_missing`, `integration`.
- `REFRESH_AFTER` for the v4 prefix uses those v4 paths (same membership as `v4/load.py`).
- Additional refresh points after taxonomy, recipe retriever COMMENTs, named-tools overlay if it registers functions, and W6 `wb_store_prompt_part` / `prompt_live_missing` COMMENTs.
- Run every SQL file through `psql` with `ON_ERROR_STOP=1` via `path.read_text()`, same as `v4/load.py` `load_stage`.
- Do **not** `import v4`, copy SQL into `v5/`, or mutate v4 paths.
- Dependency: all stage setup modules.

### New: `v5/kernel_freeze/worker.py`

- Adapt the v4 worker chain (`plugin_taxonomy` → `queue_kinds` → `observability_budget`) with imports rewritten under `v5.kernel_freeze`.
- Preserve sticky connections, queue reading, retries, DLQ, generic apply, archive-after-apply.
- Do not import v4 at runtime. Do not copy v4 SQL into this directory.
- Dependency: W1 freeze gate.

### New: `v5/kernel_freeze/setup_db.py`

- Drop/recreate only `agent_v5_kernel_freeze`.
- Load v3/v4 SQL via `v5/load.py` paths.
- Verify guard, queues, final overlay symbols. Do not require copied SQL hashes.
- Dependency: `v5/load.py`.

### New: `v5/kernel_freeze/test_kernel_freeze.py`

- Assert that loading v3/v4 SQL paths behaves as v4 did before v5 overlays.
- Read `v4/load.py` as text and assert its 12 `SQL_LOAD_ORDER` relative paths equal v5’s first 12 entries, in order.
- Verify direct SQL HTTP and synchronous `agent_run()` are blocked.
- Verify `apply_queue_result()` is generic and v4 worker apply/archive behavior remains intact.
- Verify no v1–v4 source changes (`git diff` empty). No `*.sql` under `v5/kernel_freeze/`. Worker source has no `import v4`.
- Dependency: read-only v3/v4 SQL paths and v5-local worker.

### New: `v5/kernel_freeze/__init__.py`

- Mark the stage as an importable Python package.
- No runtime behavior.

### New: `v5/prompt_taxonomy/prompt_taxonomy.sql`

- Alter the v5-local `plugin_bindings` binding-type constraint to include `prompt_slot`.
- Add the prompt-slot nullability branch.
- Replace the v4-local `refresh_plugins()` with a validate-all-then-`TRUNCATE` implementation that validates prompt-slot metadata and `prompt_mutation`.
- Preserve existing LLM and queue binding validation and `job_handler`/`workbench_plugin` rejection.
- Do not modify `apply_queue_result()` logic except for using the unchanged registry table.
- Dependency: W1 read-only v4 SQL load; must land with loader refresh logic atomically.

### New: `v5/prompt_taxonomy/setup_db.py`

- Create `agent_v5_prompt_taxonomy`.
- Load the frozen kernel and taxonomy overlay.
- Refresh the registry.
- Verify all existing v4 bindings remain and prompt-slot binding type is accepted.
- Dependency: W1 gate.

### New: `v5/prompt_taxonomy/test_prompt_taxonomy.py`

- Test valid/invalid prompt-slot COMMENT metadata.
- Test duplicate prompt-slot names, wrong signatures, unsupported components, illegal combinations, and malformed JSON.
- Verify failed refresh leaves `plugin_packages` and `plugin_bindings` byte-for-byte unchanged.
- Verify `prompt_mutation` is accepted as an `llm_tool.capability`.
- Verify `apply_queue_result()` source contains no queue-kind branch.
- Restore all catalog comments in `finally`; do not reload files while malformed comments remain.
- Dependency: taxonomy SQL.

### New: `v5/prompt_taxonomy/README.md`

- Record `Purpose`, `Pass gate`, `Fail gate`, and `pgembed change`.
- State that the stage extends taxonomy without changing generic queue dispatch.
- Dependency: test evidence.

### New: `v5/prompt_taxonomy/__init__.py`

- Mark the stage package.

### New: `v5/recipe_components/prompt_recipe.sql`

- Add `prompt_recipes`, `prompt_slots`, and `prompt_parts`.
- Add XML helper and `compile_prompt_recipe(...)`.
- Add the four prompt-slot retrievers:
  - `prompt_stored_part`;
  - `prompt_live_tools`;
  - `prompt_live_question`;
  - `prompt_live_history`.
- Add their `plugin` + `prompt_slot` comments.
- Seed the `agent_system` recipe and its initial role/task/output-format parts.
- Add `agent_runs.prompt_recipe_name` and `prompt_recipe_version`.
- Add the recipe-pinning trigger.
- Dependency: prompt taxonomy; must load after the new `refresh_plugins()` implementation.

### New: `v5/recipe_components/setup_db.py`

- Create `agent_v5_recipe_components`.
- Load through the recipe component stage.
- Refresh plugin bindings after retriever definitions.
- Verify the active recipe, ordered slots, four retriever bindings, and seeded parts.
- Dependency: W2 gate.

### New: `v5/recipe_components/test_recipe_components.py`

- Test XML parsing and direct-child order.
- Test singleton/unknown-tag/attribute/empty-content rejection.
- Test rejection of JS expressions, includes, file sources, and unsupported POML constructs.
- Test text and example message serialization.
- Test optional versus required parts and generation policy.
- Test recipe version activation and run pinning.
- Test that prompt retrievers do not perform network calls or arbitrary user SQL.
- Dependency: recipe SQL and taxonomy.

### New: `v5/recipe_components/README.md`

- Document recipe row source of truth, XML compile behavior, component grammar, gates, and `pgembed change: No`.
- Dependency: tests.

### New: `v5/recipe_components/__init__.py`

- Mark the stage package.

### New: `v5/prompt_pipeline/prompt_pipeline.sql`

- Add `assemble_prompt_messages(p_run_id)`.
- Replace the v4 `prepare_llm_request()` overlay.
- Replace the v4 `enqueue_llm_request()` overlay while preserving its signature and return type.
- Implement ordered JSONB message accumulation and slot trace.
- Use `prompt_live_tools` rather than calling `render_plugin_tools()` directly.
- Use `prompt_live_history` rather than duplicating `fold_messages()` logic.
- Add hard size/message-count limits.
- Preserve existing payload keys and add `request_type` and pinned recipe metadata.
- Dependency: recipe tables/retrievers; this overlay must load after all recipe component definitions.

### New: `v5/prompt_pipeline/setup_db.py`

- Create `agent_v5_prompt_pipeline`.
- Load the cumulative stack through the pipeline overlay.
- Verify `prepare_llm_request()` no longer references the v4 string-concatenation path.
- Dependency: W3 gate.

### New: `v5/prompt_pipeline/test_prompt_pipeline.py`

- Assert exact message order for role/task/example/output/tools/question/history.
- Assert live tools change after registry refresh without changing stored recipe parts.
- Assert history includes only existing `llm`/`tool` events.
- Assert empty history and empty tool catalog behavior.
- Assert recipe version pinning across active-version changes.
- Assert ready payload shape and missing payload shape.
- Assert worker receives the complete ordered array without prompt concatenation.
- Dependency: pipeline SQL.

### New: `v5/prompt_pipeline/README.md`

- Document the replacement seam, ready/missing contracts, message order, and `pgembed change: No`.
- Dependency: tests.

### New: `v5/prompt_pipeline/__init__.py`

- Mark the stage package.

### New: `v5/named_tools/named_tools.sql`

- Overlay `apply_llm_response()` only so `action` may be a registered `llm_tool` name.
- JSON `action_input` mapped to named function args on the sticky connection.
- Keep `execute_sql` + `exec_sql_readonly`.
- Keep async wait detection for `llm_tool.async`.
- Dependency: W4 pipeline.

### New: `v5/named_tools/setup_db.py` / `test_named_tools.py` / `README.md` / `__init__.py`

- Database `agent_v5_named_tools`.
- Tests: `action=wb_temp_view_create` then `wb_brief_query`; unknown name; bad args; `execute_sql` still works.
- Dependency: W4 gate.

### New: `v5/generate_missing/prompt_generation.sql`

- Add `wb_store_prompt_part(text,jsonb)` with `llm_tool` + `prompt_mutation`.
- Add `prompt_live_missing` retriever.
- Seed bootstrap recipe `agent_system_generate`.
- Overlay `prepare_llm_request()` so `status='missing'` builds bootstrap `llm` messages (includes user question).
- Overlay `apply_llm_response()` so premature `final_answer` cannot complete the user task while required parts are missing.
- Dependency: named tools.

### New: `v5/generate_missing/setup_db.py`

- Create `agent_v5_generate_missing`.
- Load through generate-missing. No extra PGMQ queues.
- Dependency: W5 gate.

### New: `v5/generate_missing/test_generate_missing.py`

- Delete a required part; `agent_start`; first payload is bootstrap `llm_requests` containing the user question.
- Scripted named `wb_store_prompt_part`; row appears in `prompt_parts`.
- Next assemble includes stored text at the recipe position.
- Second run, same recipe version, **different question**: skips bootstrap for `role`/`task`; stored system text is reused; only live question differs.
- Concurrent store: first-writer-wins, `replayed=true`, no overwrite.
- Premature final_answer does not SUCCESS.
- Bootstrap llm/tool steps appear in later history.
- Dependency: generation SQL.
- Test active hard budget with missing usage fails closed.
- Dependency: generation worker and SQL handler.

### New: `v5/generate_missing/README.md`

- Document bootstrap payload shape, `wb_store_prompt_part` contract, premature-`final_answer` suppression, recipe-version global `role`/`task` reuse, first-writer-wins, and `pgembed change: No`.
- Dependency: tests.

### New: `v5/generate_missing/__init__.py`

- Mark the stage package.

### New: `v5/integration/setup_db.py`

- Create `agent_v5_integration`.
- Load the complete final cumulative stack from a fresh database.
- Run all refresh points and final object checks.
- Dependency: all preceding stage gates.

### New: `v5/integration/test_v5.py`

- Run the final cumulative scripted flow: missing parts → visible named store turn → retrieve → second run reuses `role`/`task` → named workbench tool → final answer.
- Re-run freeze, taxonomy, pipeline, generation, replay, budget, and SQL HTTP checks against the final stack.
- Assert no source changes under `v1/`, `v2/`, `v3/`, `v4/`, or `pgembed/`.
- Dependency: all v5 stage implementations.

### New: `v5/integration/README.md`

- Record final pass counts, commands, database, complete load order, failed-gate policy, and `pgembed change: No`.
- Dependency: final test evidence.

### New: `v5/integration/__init__.py`

- Mark the final stage package.

### Do not modify

- `pg-agent/v1/**`, `pg-agent/v2/**`, `pg-agent/v3/**`, and `pg-agent/v4/**`;
- `pg-agent/server.py`;
- the root `pg-agent/pyproject.toml`;
- `pgembed/pgbuild/Makefile`;
- pgembed source, metadata, CI, or tests.

The only exception would be a proven failure of the existing libxml/PGMQ bundle during a stage gate. In that case, stop the stage and follow the existing pgembed change checklist rather than implementing a workaround.

## 5. Risks and migration

### 5.1 Prompt payload compatibility

Ready LLM payloads retain the existing keys and add `request_type` plus recipe metadata. The `messages` value changes from a single concatenated system message to an ordered array of system/example/user/history messages. The worker already consumes a `messages` array, so no provider adapter change is required.

Missing stored parts still produce an ordinary `llm_requests` payload whose `messages` are the bootstrap recipe. There is no second request_type routed to another queue.

### 5.2 Taxonomy compatibility

Adding `prompt_slot` to `plugin_bindings.binding_type` is intentionally v5-local. The v4 refresh function and constraints cannot safely operate on a v5 database. Separate stage databases plus loading v4 SQL as read-only paths (never writing those files) avoid cross-version catalog corruption.

### 5.3 Generated prompt quality

Generated role/task/example/output-format text is model-produced **recipe-global** system content, and the generator **sees the current user question**. That combination is a trust boundary: one run can shape later runs. Mitigations required by this plan: (1) reject stored text equal to the user question; (2) persist `source='generated'` and `generator_request_id=run_id` for audit; (3) operators inspect `prompt_parts` via SQL before relying on a recipe version in production; (4) a new recipe version is the way to replace bad generated text (`ON CONFLICT DO NOTHING` never updates). Tests must use injected `llm_fn` only.

### 5.4 Generation races

Two runs may generate the same missing recipe part concurrently. `prompt_parts` uses first-writer-wins insertion, and each run has its own generation request and budget ownership. A later generation result cannot overwrite the already stored part. The behavior is deterministic at the database commit boundary, not at provider response order.

### 5.5 Recipe activation during active runs

A run pins its recipe version at insertion. Changing the active recipe affects only new runs. Existing runs continue using their pinned slots and parts, while live tools/history continue reflecting current catalog/history state by design.

### 5.6 PGMQ failure and replay

Bootstrap and normal turns share `llm_requests`. A provider failure does not archive the message. Crash after apply is covered by `processed_queue_messages` and `last_applied_hash`. DLQ calls `fail_run()`. Successfully inserted `prompt_parts` remain for later runs.

## Work items (execution index)

| ID | Stage | Database | Depends | Size | Done when |
|---|---|---|---|---|---|
| W1 | `kernel_freeze` | `agent_v5_kernel_freeze` | v4 baseline | L | `v5/load.py` lists the same 12 v3/v4 paths as `v4/load.py` (no SQL copies, no `import v4`); HTTP guard; generic apply; v4 wait/budget/fan-out pass |
| W2 | `prompt_taxonomy` | `agent_v5_prompt_taxonomy` | W1 | M | `prompt_slot` + `prompt_mutation` accepted; failed refresh byte-identical; no kind branch in `apply_queue_result` |
| W3 | `recipe_components` | `agent_v5_recipe_components` | W2 | L | XML compile; seeded `agent_system`; four retrievers; run pin; JS/`src=` rejected |
| W4 | `prompt_pipeline` | `agent_v5_prompt_pipeline` | W3 | L | Ordered messages; no `make_system_prompt`; ready vs missing (missing still `request_type=llm` after W6; W4 may expose assemble status only) |
| W5 | `named_tools` | `agent_v5_named_tools` | W4 | L | `action=wb_*` with JSON args; sticky tools work; `execute_sql` still works |
| W6 | `generate_missing` | `agent_v5_generate_missing` | W5 | XL | First visible turn stores parts via `wb_store_prompt_part`; next assemble retrieves; first-writer-wins; no extra queue |
| W7 | `integration` | `agent_v5_integration` | W6 | M | Full scripted flow; v1–v4/pgembed diffs empty |

### W1 — `kernel_freeze`

- **Goal:** v5 loader that **reads** v3/v4 SQL paths the way v4 reads `v3/pg_agent_pgmq.sql`; v5-local worker adapted from the v4 chain.
- **Done when:** first 12 load paths match `v4/load.py`; `agent_v5_kernel_freeze` passes v4-equivalent gates; no `*.sql` under `v5/kernel_freeze/`; worker has no `import v4`.
- **Key files:** `v5/load.py`, `v5/kernel_freeze/worker.py`, `setup_db.py`, `test_kernel_freeze.py`, `README.md`.
- **Dependencies:** immutable v3 SQL + v4 overlays in `v4/load.py` `SQL_LOAD_ORDER`.
- **Size:** L

### W2 — `prompt_taxonomy`

- **Goal:** extend v5-local `plugin_bindings` with `prompt_slot` and `llm_tool.capability=prompt_mutation`.
- **Done when:** refresh validate-all-then-TRUNCATE still atomic; invalid COMMENTs roll back to identical rows.
- **Key files:** `v5/prompt_taxonomy/prompt_taxonomy.sql`, tests, README.
- **Dependencies:** W1.
- **Size:** M

### W3 — `recipe_components`

- **Goal:** relational recipes/slots/parts, XML compiler, four retrievers, seeded `agent_system`, run pinning.
- **Done when:** compile tests and retriever tests pass; libxml/`xpath` works on the bundled server or the stage stops for pgembed checklist.
- **Key files:** `v5/recipe_components/prompt_recipe.sql`, tests, README.
- **Dependencies:** W2.
- **Size:** L

### W4 — `prompt_pipeline`

- **Goal:** `assemble_prompt_messages()` + overlay `prepare_llm_request`/`enqueue_llm_request`.
- **Done when:** message order matches §7.5; `make_system_prompt` is gone; W4 `missing` raises `PROMPT_ASSEMBLY_ERROR` (bootstrap arrives in W6).
- **Key files:** `v5/prompt_pipeline/prompt_pipeline.sql`, tests, README.
- **Dependencies:** W3.
- **Size:** L

### W5 — `named_tools`

- **Goal:** `action` may be a registered `llm_tool` name with JSON `action_input`; `execute_sql` remains.
- **Done when:** scripted sticky workbench run uses `wb_temp_view_create` / `wb_brief_query` by name; unknown names and bad args are structured errors.
- **Key files:** `v5/named_tools/named_tools.sql`, tests, README.
- **Dependencies:** W4.
- **Size:** L

### W6 — `generate_missing`

- **Goal:** missing required stored parts are written on a **visible** first LLM turn via `wb_store_prompt_part`, then retrieved.
- **Done when:** §7.6 cases pass; `llm_requests` is used (no extra queue); question appears in bootstrap messages; same recipe version reuses `role`/`task` across runs; first-writer-wins.
- **Key files:** `v5/generate_missing/prompt_generation.sql` (`wb_store_prompt_part`, bootstrap recipe, `prompt_live_missing`, apply overlay), tests, README.
- **Dependencies:** W5.
- **Size:** XL

### W7 — `integration`

- **Goal:** one fresh DB: missing parts → visible store turn → full recipe → named tool → final.
- **Done when:** `test_v5.py` passes; git diffs for v1–v4 and pgembed are empty.
- **Key files:** `v5/integration/*`, `v5/README.md`.
- **Dependencies:** W6.
- **Size:** M

## 6. Implementation order

1. **W1 kernel freeze.** `v5/load.py` points at v3/v4 SQL. v5-local worker. No prompt behavior. DB `agent_v5_kernel_freeze`.
2. **W2 prompt taxonomy.** `prompt_slot` + `prompt_mutation`. No new queue kind. DB `agent_v5_prompt_taxonomy`.
3. **W3 recipe components.** Tables, XML compile, four retrievers, seed `agent_system`, pin columns. DB `agent_v5_recipe_components`.
4. **W4 prompt pipeline.** `assemble_prompt_messages` + `prepare_llm_request` overlay. Missing status is observable; bootstrap send lands in W6. DB `agent_v5_prompt_pipeline`.
5. **W5 named tools.** `action=wb_*` JSON args. DB `agent_v5_named_tools`.
6. **W6 generate-missing.** `wb_store_prompt_part`, bootstrap recipe, visible first turn; `role`/`task` globally reused for that recipe version. DB `agent_v5_generate_missing`.
7. **W7 integration.** Fresh `agent_v5_integration`: missing part → named store turn (question in bootstrap) → second run reuses `role`/`task` → named workbench tool → final.
8. **Documentation and immutability evidence.**
   - Fill all stage README files with actual commands, pass/fail counts, and `pgembed change: No`.
   - Fill the top-level v5 README with cumulative order and final status.
   - Run:
     ```text
     git diff -- pg-agent/v1 pg-agent/v2 pg-agent/v3 pg-agent/v4
     git diff -- pgembed
     ```
   - Both diffs must be empty.
   - If any pgembed diff exists, stop finalization and determine whether it was an unauthorized change or a proven missing-bundle failure.

## 7. Verification design

### 7.1 Common harness

Every stage setup/test pair follows the v4 conventions:

- use `pgembed.POSTGRES_BIN_PATH`;
- use `server.get_server()` and the shared embedded server;
- use `run_psql()` with `ON_ERROR_STOP=1`;
- drop/recreate only the stage’s own database;
- close all psycopg connections and workers in `finally`;
- return non-zero on the first failed stage;
- use stable named assertions;
- use `pgmq.purge_queue()` for queue cleanup;
- use explicit `TRUNCATE ... RESTART IDENTITY` or `DELETE` for ordinary tables;
- drop temporary probe functions explicitly and restore comments in `finally`;
- close sticky worker connections and verify TEMP-state destruction where applicable.

### 7.2 Deterministic mocks

Use the established `scripted()` contract from `v3/test_v3.py` and `v4/queue_kinds/test_queue_kinds.py`:

- the worker constructor receives `llm_fn`;
- every call is counted;
- the script returns deterministic raw model text or structured values;
- generation tests use ordered queue insertion and a single worker unless concurrency is the subject of the test;
- concurrency tests use explicit barriers or controlled processing order;
- no live provider, API key, network, or SQL HTTP call is used.

For generation, the script returns JSON with the expected `value_kind` and `value`. The worker parses and validates it before applying.

### 7.3 Required static checks

Final v5 checks must confirm:

- no v5 normal-path call to `http_call_llm()`;
- `agent_run()` remains guard-blocked;
- no `pgai`, Redis, LiteLLM Proxy, postgres-task-queue, or Cordis-in-Postgres dependency;
- no worker source directly calls `apply_llm_response()`;
- `apply_queue_result()` has no queue-kind conditional;
- `prepare_llm_request()` no longer calls `make_system_prompt()` or concatenates `render_plugin_tools()`;
- worker code never concatenates prompt components;
- generated raw provider responses and secrets are not stored in `agent_steps.meta`;
- v1–v4 and pgembed are unchanged.

### 7.4 Recipe and XML tests

Verify:

- direct-child XML order maps exactly to slot positions;
- `role`, `task`, `output-format`, and `example` map to the correct `component_type`;
- example messages preserve user/assistant order;
- tools/question/history produce no stored part row;
- unknown tags and unsupported attributes fail;
- JS expressions and file-source constructs fail;
- replacing a recipe creates a new version;
- active recipe switching does not change a pinned run;
- malformed compile rolls back all rows;
- required missing parts produce `status='missing'`;
- optional missing parts do not block assembly.

### 7.5 Pipeline tests

For a seeded recipe, assert the exact ordered roles:

```text
system role
system task
optional example user
optional example assistant
system output-format
system live tools
user question
assistant/tool history
```

Verify:

- no history exists on the first request;
- `llm` and `tool` steps appear in later history;
- `budget` and `wait` steps do not appear in folded conversation history; bootstrap `llm`/`tool` steps do;
- live tool catalog changes are visible on the next assembly;
- the output contains the exact nested `exec_sql_readonly()` observation contract;
- an outer `success=true` does not imply nested tool success.

### 7.6 Generate-then-retrieve tests

At minimum:

1. Delete a required `prompt_parts` row using explicit `DELETE`.
2. `agent_start()` with a known question string.
3. First `llm_requests` payload is `request_type='llm'`, `prompt_mode='generate_missing'`, and the user question appears in `messages`.
4. Scripted model calls `action=wb_store_prompt_part` with JSON args.
5. `prompt_parts` contains the generated value; `source='generated'`; no API key in `agent_steps.meta`.
6. Next prepare uses the full recipe; generated text sits in the correct slot.
7. A second run with the **same recipe version and a different question** skips bootstrap for existing `role`/`task`; those system messages equal run 1’s stored parts; only the live `question` slot differs (global reuse).
8. Concurrent second store is `replayed=true` and does not overwrite.
9. Premature `final_answer` before parts exist does not emit `kind='final'`.
10. Bootstrap `llm`/`tool` steps remain in later history.
11. Crash-after-read replay does not duplicate the stored part.
12. `llm_requests` DLQ / max_steps while still missing → `ERROR`.

### 7.7 Final runbook

After implementation, run stages strictly in order:

```bash
cd /Users/wxl/Projects/pg-agent
uv sync

uv run python -m v5.kernel_freeze.setup_db
uv run python -m v5.kernel_freeze.test_kernel_freeze

uv run python -m v5.prompt_taxonomy.setup_db
uv run python -m v5.prompt_taxonomy.test_prompt_taxonomy

uv run python -m v5.recipe_components.setup_db
uv run python -m v5.recipe_components.test_recipe_components

uv run python -m v5.prompt_pipeline.setup_db
uv run python -m v5.prompt_pipeline.test_prompt_pipeline

uv run python -m v5.named_tools.setup_db
uv run python -m v5.named_tools.test_named_tools

uv run python -m v5.generate_missing.setup_db
uv run python -m v5.generate_missing.test_generate_missing

uv run python -m v5.integration.setup_db
uv run python -m v5.integration.test_v5
```

If any command fails, stop and record the failed gate in that stage’s README. Do not begin the next stage, do not reuse another stage database, and do not modify the immutable v1–v4 or pgembed trees.

## References

- https://github.com/microsoft/poml
- https://microsoft.github.io/poml/latest/language/components/
- https://microsoft.github.io/poml/latest/language/template/
- https://microsoft.github.io/poml/latest/deep-dive/ir/
- Local POML clone: `/Users/wxl/projects/poml`
- `pg-agent/docs/plans/v4-expansion-2026-08-28.md`
- `pg-agent/docs/plans/v2-workbench-plugins-2026-08-22.md`
- `pg-agent/docs/reviews/v2-workbench-plugins-plan-review-2026-08-22.md`
- `pg-agent/docs/investigations/cordis-workbench-plugins-2026-08-22.md`
- `pg-agent/v1/pg_agent_poml.sql`
- `pg-agent/v3/pg_agent_pgmq.sql`
- `pg-agent/v4/README.md`
- `pgembed/pgbuild/Makefile` (`--with-libxml`)
