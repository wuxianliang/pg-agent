## Ask Oracle ✅
- Oracle group status: completed
- Oracle group: `54BBD0FD-1DC4-44CE-9500-E4BF8C6B0E8B`

### Oracle
- Status: Completed
- Provider: `grokBuild`
- Model: `grok-4.7-build-fast-xhigh`
- Effective effort: Provider default / not specified
- Chat: `new-chat-3A582E`



# v15 round 2 — rulings and spec skeleton

Round 1 stands: Postgres holds the invoke tree, the worker only does LLM I/O and splitting, and the model’s program is SQL. This round freezes the places the two tracks disagreed. The extra-parent-turn design is rejected. Governance is fail-closed and grant-enforced. Expired LLM work becomes a terminal `unknown` attempt plus a new attempt row. `v15_on_phase` is a stub until stage 9, with the return contract frozen before the loop is written.

---

## R1–R5

### R1 — Agree, with the suspension boundary pinned

Adopt the statement-list REPL. One assistant message is one program (`π` = identity over that text). The worker splits it, runs it one statement per transaction as `v15_repl`, and on a canonical `SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);` it does **not** enter the child inside that statement. It evaluates `<jsonb-expr>` in a **read-only** transaction, commits `v15_suspend_for_child`, runs the child to a terminal state, binds the jsonb, and executes the **next statement of the same parent iteration**. No new parent LLM call.

That is the Figure 1 / tail-delegation property. Depth-70 StuLife-style handover is:

```sql
SELECT jaz.bind_invoke('delegated', jsonb_build_object(
  'prev_history_ref', to_jsonb('<parent invoke uuid>'::text),
  'next_steps', to_jsonb('...'::text)
));
SELECT jaz.return(jaz.var('delegated'));
```

Two statements, one parent response, one child tree. Codex V15-D01 (spend another parent turn to read the child) is not a v15 deviation; it contradicts the property this version exists to keep.

Pin the boundary so “mid-statement” is not implemented inside a statement:

- Suspension is **intra-iteration and inter-statement**.
- `jaz.bind_invoke` the function, if it actually runs, **raises `V15_INVOKE_FORM` and inserts no child**. Only worker-side `v15_suspend_for_child` creates invokes.
- A `DO $$...$$;` is **one statement** in the list. Plpgsql locals stay cell-local and never become `bindings`. It is not the program form.
- A non-canonical statement whose text contains `jaz.bind_invoke`, `jaz.return`, or `jaz.raise` is rejected **before** execution, so a `DO`/`EXCEPTION` handler cannot swallow a spawn. Obfuscated dynamic SQL still cannot spawn: the function has no insert path.
- `jaz.return` / `jaz.raise` / `jaz.print` / `jaz.assign` run **inside** the statement transaction (SECURITY DEFINER, narrow writes). They do not need a worker rewrite. `bind_invoke` does, because holding that transaction open across the child would put LLM I/O inside a transaction.

Earlier statements in the list stay committed when a later statement fails (same persistence as a Python REPL namespace). The failed statement’s transaction rolls back. Later statements do not run. The iteration becomes one recoverable `Continue`.

### R2 — Agree, with one correctness refinement

Adopt the operator manifest, tighten-only ceilings, tool grants, NOLOGIN handler owners, pinned `search_path`, `P15xx`, and the authority matrix.

Do **not** treat `STABLE`/`IMMUTABLE` as a sandbox, and do **not** require `IMMUTABLE`. PostgreSQL does not enforce volatility at execution time, and the planner may constant-fold `IMMUTABLE`. Governance hooks that `UPDATE budget_pools` from a handler would also break “effects apply after the dispatch loop.”

Refinement that makes the volatility rule true:

- Handlers are `SECURITY DEFINER`, `LANGUAGE` sql or plpgsql, `provolatile = 's'`, `search_path = pg_catalog` only, owner `NOLOGIN` and not superuser, **no grants on kernel tables**, no C-language handlers.
- They receive the phase snapshot as jsonb and **return effects**. They do not write.
- The dispatcher (stage 9 body of `v15_on_phase`) is the only writer for blackboard, budget, and abort application.
- Registration rejects `IMMUTABLE` and rejects any handler with table grants.
- Baseline/governance handler exceptions fail the phase (`V15_GOVERNANCE_FAULT`). Other handler exceptions are appended to `invoke_events` and produce no effects (jaz’s log-and-continue, narrowed so a broken ceiling cannot be skipped).

Manifest ceilings are mandatory and finite: `max_iterations`, `max_depth`, `max_io_attempts`, `max_statement_ms` (the last two are required by R3 and by `pg_sleep` / runaway scratch SQL; both are integers `>= 1`). Missing or non-finite → `V15_GOVERNANCE_MISSING` at `v15_open_invoke`, no LLM call. Caller may add a **tighter** local ceiling. A looser one → `V15_GOVERNANCE_RAISE`. Omitting the caller hook is normal: `v15_open_invoke` installs the manifest values as baseline hooks. There is no model-facing disable.

Jaz forbids a **local** `RecursionLimit` because that channel does not propagate and the subtree would be unbounded. Here the baseline still propagates the manifest, so a local hook that only aborts earlier is a tighten, not a hole. v15 allows that. Ledger it; do not port jaz’s local-channel raise.

`max_iterations` / `max_depth` are **not** config keys. A config object carrying them is an unknown option.

### R3 — Confirm, with settle and budget rules

Expired lease → that `llm_attempts` row becomes `unknown` and stays there. Reclaim inserts a **new** attempt on the same `llm_requests` row. FakeLLM is invoked only for the new row, after the reclaim transaction commits. Deterministic FakeLLM and the unknown state both hold: tests see two rows, identical responses, one `unknown` and one `settled`.

Additional rules, otherwise retry is either silent or an infinite spend loop:

- A late `v15_settle_llm` for an `unknown` (or otherwise non-leased) attempt raises `V15_ATTEMPT_NOT_SETTLEABLE` and does not append the transcript.
- The worker may record `failed` only if the provider call was **never started**. Once the call has started, the only terminal statuses are `settled` or `unknown`.
- `unknown` increments `calls_used` (conservative). The in-flight reservation is released and the new attempt reserves again. Crash-retry cannot refund its way past the pool.
- Attempts per request stop at manifest `max_io_attempts`. The next one aborts that invoke with `V15_IO_EXHAUSTED` (`fatal=false`). Pool exhaustion remains `V15_BUDGET_EXHAUSTED` (`fatal=true`).
- Statement execution does **not** use `unknown`. Status and scratch/binding effects commit in one transaction. Crash before commit leaves `pending` and re-run is safe; `done` is never re-executed.

`attempt_id` is stored in the request payload now so a later real adapter can pass an idempotency token. v15 does not claim provider exactly-once. Double billing after `unknown` is a recorded deviation, not something the reclaim path papers over.

### R4 — Agree; freeze the view sentence; keep the quiescent driver out of SQL

Model API, schema `jaz`: `var`, `assign`, `print`, `tool`, `return`, `raise`, `bind_invoke`. Kernel API, schema `v15`: `v15_open_invoke`, `v15_claim`, `v15_begin_llm`, `v15_settle_llm`, `v15_begin_exec`, `v15_suspend_for_child`, `v15_finish_exec`, `v15_on_phase`. Role `v15_repl`. History view **`jaz.history`**. Do not also create `"__history__"`.

`v15_run_until_quiescent` is **Python in the worker**, not a SQL function. A SQL loop that pulled FakeLLM or a provider would violate invariant 4. SQL may expose `v15_next_runnable()` (scan). The worker is what loops.

`jaz.tool` is an ordinary in-transaction function (external tools are `V15_EXTERNAL_TOOL`). `jaz.var` is too. `return` / `raise` / `print` / `assign` / `bind_invoke` are the control forms; the first three plus `assign` execute in-statement, `bind_invoke` is worker-intercepted.

Prompt text to freeze (this is the agent-facing description; it replaces jaz’s `__history__` list copy):

> You have a view `jaz.history`. Each finished REPL iteration of this invoke is one row. `iteration` 0 is the first turn; the greatest `iteration` is the most recent. Columns: `iteration integer`, `llm_response text` (your full response), `repl_output text` (what you printed, including error text; `''` when that turn returned or raised), `repl_exception jsonb` (`null` if that turn had no recoverable error; otherwise `sqlstate`, `code`, `message`). Read it with SQL, for example `SELECT repl_output FROM jaz.history WHERE iteration = 0`. It is not a Python list and it is not named `__history__`. The current turn is not a row yet. A turn suspended at `jaz.bind_invoke` is still current. To read an ancestor’s finished history, call `jaz.prior_history(<uuid>)` with an ancestor invoke id; any other id fails.

`jaz.prior_history(uuid)` is an extra model-facing function beyond the R4 list. It is required so tail delegation can pass history **by ancestor id** instead of `jsonb_agg` copying every prior row into the child (depth 70 would otherwise copy the transcript 70 times, and prompt truncation would destroy the copy the model can see). It returns rows only for the current invoke or an ancestor (`V15_HISTORY_SCOPE` otherwise). The child prompt shows the uuid, not the transcript. The binding remains a jsonb string the child can pass to the function.

`jaz.var` is `VOLATILE`. An `IMMUTABLE` or cached plan would serve a binding from before `assign` or before resume.

### R5 — Keep the 9-stage order; stub now, replace in stage 9

No dependency violation if the **physical tables and the phase-result contract** exist in stage 1 and the **dispatcher body** does not.

Pick the stub. Codex’s “hooks stage before the loop” forces the FakeLLM loop to wait on the full algebra and loads a dispatcher that wants budget and blackboard tables before those behaviors exist. Privilege isolation does not require the algebra: it is roles, grants, registration checks, and “`v15_repl` cannot register or become `v15_worker`.” That is a stage 1 gate. The loop only needs a frozen jsonb contract.

- Stage 1 defines `v15_on_phase` as `SECURITY DEFINER` returning `{"contract":1,"action":"proceed"}` and defines a **real** `v15_assert_manifest()` (not a stub) over the manifest table.
- Stage 7’s transitions call `v15_on_phase` and `v15_assert_manifest` and interpret the contract. They do not encode numeric ceilings (one enforcement point, the stage 9 baseline hooks).
- Stage 9 `CREATE OR REPLACE`s `v15_on_phase` only. Same argument types, same oid. It must not `DROP FUNCTION`.
- Unknown contract keys or `"contract" <> 1` → `V15_PHASE_CONTRACT` (fail closed). Stage 9 may fill keys stage 7 already accepts; it may not require the loop to learn new ones.
- A prefix load through stage 7 is a test scaffold. Invariant 0: only the full `SQL_LOAD_ORDER` is a conforming runtime. The Python worker also has a test fuse so a stub-hook run cannot spin.

Stage order (unchanged from the ruling):

| # | Stage | Proves first |
|---|---|---|
| 1 | `schema` | Tables, roles, grants, manifest presence function, phase stub, registration predicate, event trigger, no TEMP for `v15_repl` |
| 2 | `namespace` | Bindings, scope copy, `jaz.history` / `jaz.prior_history`, `exec_context` |
| 3 | `config` | base ⊕ depth ⊕ propagating ⊕ local, frozen document, whole-component replace |
| 4 | `protocol` | Splitter, dialect, render, history wording, truncation |
| 5 | `repl` | Statement executor, scratch, sandbox, print/assign/return/raise, committed statement not re-run |
| 6 | `io` | Requests, attempts, fence, `unknown`, new-row retry, conservative charge |
| 7 | `loop` | One invoke, FakeLLM outside any open transaction, spans, history row, phase contract |
| 8 | `tree` | Suspend/resume, same-iteration bind, child error, fatal ancestor walk |
| 9 | `govern` | Real dispatcher, effect algebra, blackboard generation, five builtins, manifest ceilings, tool grants, end-to-end |

---

## Current-state facts that fix these rulings

- Jaz `CodeOnlyProtocol.parse` never fails; syntax errors become a recoverable `Continue`. v15 dialect errors do the same to the **iteration**, and governance/ACL errors fail the **invoke**.
- History is one entry per finished iteration, 0-based, appended after the turn. Terminal `Return`/`Raise` store `repl_output ''`. `reject_finish_on_printed_output` defaults true. v15 keeps all three.
- `IterationLimit` aborts at `LLMQueryEnter` when `iteration >= max_iterations`. `RecursionLimit` disables recursion at `depth == max_depth` and aborts when `depth > max_depth`. Root depth is 1. v15 uses that arithmetic against the **manifest**, not against an opt-in hook the caller remembered to pass.
- Jaz `Abort` is containable by a parent unless the exception is fatal-category. v15 maps that to the `fatal` bit on the phase result. Budget exhaustion is fatal to ancestors; iteration and recursion ceilings are not.
- Jaz applies blackboard writes after the handler loop and composes by equality, not registration order. v15 does that in SQL with jsonb equality (no object identity).
- Config fold is base, then global depth layer, then propagating layers, then local; groups replace as a whole. v15 freezes the folded jsonb on the invoke row at open (jaz refolds lazily; that laziness exists for ContextVar re-base, which v15 does not have).

---

## Outline — `docs/designs/v15-jaz-dev.md`

### 0. Invariants

0. **Conforming runtime.** The contract is this document on PostgreSQL 18.4. A database is conforming only after `v15/load.py` has loaded every entry in `SQL_LOAD_ORDER`. A prefix load is a gate scaffold and MUST NOT be shipped. Gates are `uv run python v15/<stage>/test_*.py` with exit 0. Tests MUST use FakeLLM only and MUST NOT open a network socket.

1. **Two properties.** Model SQL MUST be able to suspend the current iteration at `jaz.bind_invoke` and continue that same iteration with the child result in `jaz.var`. Every value shown to the model — explicit inputs, scoped names, tool results, this invoke’s finished history, and an ancestor history it was given by id — MUST be readable by model SQL. The parent MUST NOT spend an LLM call merely to observe a child result.

2. **Authority of rows.** `v15.invoke_events` is append-only; per `invoke_id`, `seq` is contiguous, monotonic, and unique. `invokes`, `iterations`, `statements`, `llm_requests`, `llm_attempts`, and leases are the control plane. Worker memory MUST NOT be treated as recoverable state.

3. **No external I/O in a transaction.** An LLM call MUST run only after the leasing transaction has committed and before a later transaction settles it. No SQL function may loop the provider or call FakeLLM. `v15_run_until_quiescent` is worker Python.

4. **Fences.** A claim has one fence. A settle, reclaim, or exec step with a stale fence MUST raise `V15_STALE_FENCE` and MUST NOT change control state.

5. **Unknown LLM attempts.** Lease expiry sets that attempt to `unknown`, which is terminal. A later response for it MUST raise `V15_ATTEMPT_NOT_SETTLEABLE` and MUST NOT enter the transcript. Retry MUST insert a new attempt row on the same request. The expired row MUST NOT be rewritten to `failed` or `settled`.

6. **Statement atomicity.** A model statement’s scratch and binding effects and its `statements.status` commit in one transaction. Status `done` MUST NOT be executed again. This rule does not apply to LLM attempts.

7. **Where suspend happens.** Suspension is between statements of one iteration. The jsonb argument is evaluated read-only, then `v15_suspend_for_child` commits the child. The following statement sees the bind. Canonical tail delegation is `bind_invoke` then `return` of that name, in one assistant message.

8. **The function does not spawn.** `jaz.bind_invoke`, if executed, MUST raise `V15_INVOKE_FORM` and MUST NOT insert a child. Only `v15_suspend_for_child` as `v15_worker` creates a child.

9. **One advancer.** A `suspended` invoke MUST NOT be claimable. One leaseholder advances an invoke. v15 has no parallel map and no async invoke.

10. **Fatal bit.** `fatal=true` (shared pool exhausted, operator abort) marks that invoke and every ancestor aborted in the same transaction. `fatal=false` (iteration ceiling, recursion ceiling, `jaz.raise`, child error, I/O attempt cap) ends that invoke only; the parent iteration becomes a recoverable `Continue`.

11. **Effect algebra.** The effect set is closed. An effect illegal for the phase MUST raise `V15_INVALID_EFFECT`. Same-key composition is order-independent: equal jsonb coalesces; unequal values, input adds, or returns fail the phase. Blackboard writes become visible only on the next phase. Handlers in one phase read the pre-write snapshot.

12. **Manifest.** `max_iterations`, `max_depth`, `max_io_attempts`, and `max_statement_ms` MUST be integers `>= 1` on the single operator manifest row. Otherwise `v15_open_invoke` raises `V15_GOVERNANCE_MISSING` and MUST NOT lease an LLM attempt. Callers MAY tighten. Loosening MUST raise `V15_GOVERNANCE_RAISE`. Open installs the manifest ceilings as baseline hooks. Model SQL and non-baseline hooks MUST NOT remove them.

13. **Grants, not convention.** `v15_repl` has no DML and no EXECUTE on kernel transitions, is not a member of `v15_worker` or any hook-owner role, and cannot write `v15.exec_context` or change `search_path` / `role`. A bound tool name without `tool_grants` MUST raise `V15_TOOL_UNAUTHORIZED`.

14. **Handlers.** Registered handlers MUST be SECURITY DEFINER, NOLOGIN non-superuser owner, STABLE, SQL or plpgsql, `search_path = pg_catalog`, with no kernel table grants. `IMMUTABLE` and C handlers MUST be rejected at registration. The dispatcher calls them by `regprocedure` oid. Baseline handler exceptions MUST raise `V15_GOVERNANCE_FAULT`. Other handler exceptions MUST be audit rows and MUST NOT become effects.

15. **Config fold.** Effective config is base profile, then the global depth partial for this depth, then propagating layers in ordinal order, then this invoke’s local layer. Later wins. `llm`, `repl`, and `protocol` replace as whole objects. Absent keys are not writes. The fold is stored on the invoke at open and MUST NOT be refolded from later profile edits. Local layers MUST NOT be copied to children. A depth partial MUST NOT contain `depth_map`.

16. **Addressable state.** Model-visible values are jsonb. Scope rows are copied onto the child at open; input rows are not. A name that is both MUST raise `V15_SCOPE_CONFLICT`. `jaz.history` is a security-barrier view of this invoke’s **finished** iterations. `jaz.prior_history` returns rows only for self or an ancestor. Prompts describe `jaz.history` and MUST NOT describe `__history__`. Observation text MAY be truncated; stored `repl_output` MUST be complete.

17. **Dialect.** The assistant message is the program. The Python splitter is the authority and MUST understand quotes, nested block comments, and arbitrary dollar-quote tags. `bind_invoke`, `return`, and `raise` are canonical sole `SELECT`s; any other statement whose text contains those calls MUST fail `V15_INVOKE_FORM` before execution. A `DO` block is one statement. `CALL`, `EXECUTE`, `COPY`, transaction control, `SET`/`RESET`, and `CREATE FUNCTION` MUST fail `V15_DIALECT` or `V15_DDL`.

18. **SQLSTATE.** Every `V15_*` error MUST use a distinct sqlstate in `P1500`–`P1599`. Gates MUST classify by sqlstate. This family MUST NOT use `P0001`.

19. **Current user.** Model statements run with `current_user = v15_repl`. Kernel transitions MUST refuse any other current user. `jaz` mutators MUST refuse any current user other than `v15_repl`. Manifest writes and hook registration MUST refuse everyone except the bootstrap owner.

20. **Attempt and budget caps.** A request MUST NOT grow past `max_io_attempts`. An `unknown` attempt increments `calls_used` and releases only its reservation; the new attempt reserves again. If the pool cannot cover that reservation, the invoke aborts `fatal=true` with `V15_BUDGET_EXHAUSTED` and MUST NOT lease another attempt.

21. **Print and return.** `reject_finish_on_printed_output` defaults true and MUST NOT be turned off by model SQL. A list that prints and also returns or raises finishes as `Continue` with `V15_PRINT_AND_RETURN`.

22. **Scan, don’t listen.** Progress MUST be recoverable by selecting runnable rows. `NOTIFY` is not part of correctness.

### 1. Scope

Freeze v15 as the nine stages above: the two paper properties, SQL REPL, persisted tree, config fold, closed effect algebra, five governance hooks, pure-SQL tools, FakeLLM. Defer ReturnType, ValidateReturn, ValidateREPLCode, trajectory replay, OTel/Langfuse/Jaeger, real providers, `map_invoke`, external tools, `ainvoke`, Jinja, and Display/catalog rendering. The effect enum reserves their names so a later version can enable them without a new code point; v15 composers reject them at every phase.

### 2. Architecture

Freeze the worker cycle: `v15_claim` → `v15_begin_llm` → commit → FakeLLM → `v15_settle_llm` → `v15_begin_exec` → for each statement either run it as `v15_repl` or suspend → `v15_finish_exec`. One assistant message is one iteration. Child invokes are rows, claimed only while the parent is `suspended`.

### 3. Roles and authority matrix

Freeze roles `v15_bootstrap` (setup_db only), `v15_owner` (NOLOGIN, owns kernel tables and SECURITY DEFINER transitions), `v15_worker` (EXECUTE on transitions, member of `v15_repl`, not superuser), `v15_repl` (model SQL), and one NOLOGIN `v15_hook_<name>` per registered handler with no role memberships.

| Action | bootstrap | owner via definer | worker | v15_repl | hook owner | PUBLIC |
|---|---|---|---|---|---|---|
| Kernel DML | setup | yes | no direct grants | no | no | no |
| Call `v15_*` transitions | setup | yes | yes, and `current_user` must be worker | no | no | no |
| LLM / FakeLLM | no | no | yes, outside a txn | no | no | no |
| Model statement in scratch | no | no | only after `SET LOCAL ROLE v15_repl` | yes | no | no |
| Write `exec_context`, manifest, `tool_grants`, `hook_defs` | setup | yes | no | no | no | no |
| EXECUTE `jaz.var/assign/print/tool/return/raise/bind_invoke/prior_history` | no | definer body | no (wrong current_user) | yes | no | no |
| Register a handler | setup | yes | no | no | no | no |

Committed state MUST NOT grant `v15_repl` USAGE on scratch schemas. Each model-statement transaction GRANTs USAGE on that invoke’s schema, runs the statement, REVOKEs, then commits. `v15_repl` is not a member of `v15_worker`, so `SET ROLE` / `set_config('role', ...)` cannot escalate. Database TEMP privilege is revoked from `v15_repl`.

### 4. Data model

Freeze these tables (all created in stage 1; later stages only add functions and grants):

- `invokes` — identity, `parent_invoke_id`, `parent_iteration`, `root_invoke_id`, `depth` (root = 1), status `pending|runnable|leased|suspended|completed|failed|aborted`, `return_value jsonb`, `error jsonb`, `fatal bool`, `recursion_available bool`, `resolved_config jsonb`, `config_scope_id`, `local_layer_id`, `pool_id`, `fence`, `lease_owner`, `lease_until`, `scratch_schema`.
- `iterations` — `(invoke_id, iteration)` 0-based; status `pending|llm|executing|suspended|done`; `resume_stmt`; `result_kind`; `capture text` (prints accumulated across suspend).
- `statements` — `(invoke_id, iteration, stmt_index, sql, kind, status, bind_name, child_invoke_id)`.
- `llm_requests` — one logical query: `(request_id, invoke_id, iteration)`.
- `llm_attempts` — `(attempt_id, request_id, n, status leased|settled|failed|unknown, fence, lease_until, request jsonb, response jsonb)`.
- `llm_messages` — append-only transcript. Transient hook messages MUST NOT be inserted here; they live only on the attempt’s request jsonb.
- `repl_history` — `iteration, llm_response, repl_output, repl_exception jsonb`. One row when an iteration finishes, including a failed statement. Terminal return/raise stores `repl_output ''`.
- `bindings` — `(invoke_id, name, kind input|scope|var|tool, value jsonb, tool_id, show_in_prompt)`.
- `exec_context` — `(backend_pid pk, invoke_id, scratch_schema)` written by the worker in the model transaction **before** `SET ROLE`, overwritten every statement. Not a GUC. Not a temp table.
- `invoke_events` — append-only audit.
- `config_profiles`, `config_scopes`, `config_layers` (`kind plain|depth`, component jsonb, `depth_map jsonb`, `ordinal`).
- `hook_defs` — `regprocedure`, channel `baseline|propagating|local`, `baseline_required bool`, volatility and owner checks stored at registration.
- `invoke_hooks` — copied rows for this invoke, dispatch order baseline then propagating (outer→inner) then local.
- `blackboard` — `(invoke_id, key, value jsonb, generation)`.
- `budget_pools` — `calls_limit, cost_limit, calls_used, calls_reserved, cost_used`.
- `hook_counters` — BudgetForcing refusals, keyed by invoke.
- `governance_manifest` — singleton ceilings.
- `tool_catalog`, `tool_grants`.

Scratch schema name is `s_` plus the invoke uuid in hex (32 chars, unquoted). Created at open by the worker, dropped when the invoke reaches a terminal status.

### 5. Transition contracts

Freeze each transition as one transaction. After `v15_begin_llm` commits, the session MUST NOT hold an open transaction across FakeLLM. `v15_begin_llm` / `v15_suspend_for_child` / `v15_open_invoke` call `v15_on_phase` and honor `abort` by not starting I/O. `v15_settle_llm` is the only writer of assistant transcript rows. `v15_suspend_for_child` in one transaction: insert child `runnable`, set this statement waiting, iteration `suspended`, invoke `suspended`, clear the parent lease. Child terminal transaction: on return, bind `kind=var` and set parent `runnable` at `resume_stmt+1`; on non-fatal child failure, parent iteration becomes `Continue` with `V15_CHILD_ERROR` and later statements do not run; on `fatal`, abort ancestors. Stale fence and `current_user` checks run before any write. `lock_timeout` is set on kernel transitions so a stuck lock fails closed.

Phase result the loop already understands in stage 7:

- `contract` must be 1.
- `action`: `proceed` or `abort`.
- `fatal` bool, `error` `{code, sqlstate, message}`.
- `messages` with `persistent` bool (persistent ones are applied to `llm_messages`; transient ones are copied onto the attempt request only).
- `exec_result` kind `continue|return|raise` (BudgetForcing’s downgrade).
- `recursion_available` false means `v15_suspend_for_child` raises `V15_RECURSION_DISABLED`.
- `input_adds` / `input_drops`, `blackboard_writes`.
- `budget`: reserve or settle, applied by the dispatcher, not by the handler.

### 6. Dialect

Freeze the splitter in `v15/protocol/split_sql.py` (quote, nested `/* */`, dollar tags). The database stores already-split statement rows and MUST NOT re-split with SQL regex.

Canonical sole statements:

- `SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);`
- `SELECT jaz.return(<jsonb-expr>);`
- `SELECT jaz.raise(<text-expr>);`
- `SELECT jaz.print(<text-expr>);`
- `SELECT jaz.assign('<ident>', <jsonb-expr>);`

`jaz.var` and `jaz.tool` may appear inside expressions. Allowed non-control statements: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE/DROP TABLE`, `CREATE/DROP INDEX`, `CREATE TABLE AS` / `SELECT INTO`, and one `DO` block, all confined to the scratch schema plus `jaz.*` calls. A leading `-- timeout: <seconds>` applies to that statement only and MUST be a positive finite number not above the manifest. Empty or whitespace-only messages consume an iteration and execute nothing. Prose that is not SQL becomes a recoverable statement error, not an invoke abort.

### 7. Namespace, history, tools

Freeze `jaz.history` as `security_barrier = true`, `security_invoker = false`, owner `v15_owner`, base table SELECT revoked from `v15_repl`. Columns and prompt text are R4’s paragraph. `jaz.prior_history(uuid)` is the delegation reference. `jaz.tool` calls a catalog `regprocedure` in the statement transaction; `tool_catalog.external` is always `V15_EXTERNAL_TOOL` in v15. Tool handlers run as their NOLOGIN owner with no kernel grants. `exec_context` is the only identity `jaz.*` uses (`pg_backend_pid()`); accessors are schema-qualified and VOLATILE.

### 8. Config

Freeze profiles plus ordered layers, resolved once in `v15_open_invoke` into `invokes.resolved_config`. Missing component keys are left untouched (`jsonb_exists`, not SQL NULL). `kind=depth` contributes only `depth_map[depth]`. A second local layer is `V15_CONFIG_LOCAL`. A layer key `baseline_hooks` or `depth_map` inside a depth partial is `V15_BASELINE_IMMUTABLE` / `V15_DEPTH_SELF`. Children inherit `config_scope_id` and the propagating hook rows, not the local layer and not local hooks. No `established` flag and no ContextVar rebase.

### 9. Hooks, effects, blackboard

Freeze dispatch order baseline, then propagating outer→inner, then local. Propagating rows are copied at open; local rows are not. Spans `invoke`, `llm_query`, `repl_exec` with phases `enter`, `send`, `complete`, `exit`. `invoke/exit` accepts no control effect. `exit` on the two per-turn spans may still `abort`. Effect enum: `abort`, `add_messages`, `drop_messages`, `disable_recursion`, `add_inputs`, `drop_inputs`, `modify_exec_result`, `blackboard_write`, plus reserved `supply_llm_response`, `supply_invoke_result`, `modify_invoke_result`, `supply_exec_result`, `modify_llm_response` which v15 rejects at every phase. Same-key blackboard or input conflicts raise. Multiple aborts become one error list; any `fatal=true` wins. Equal jsonb coalesces. Each handler runs under a SAVEPOINT so a non-baseline exception does not poison the phase transaction; a baseline exception does fail it. Generation increments when the dispatcher applies the write batch. `v15_begin_llm` refuses to lease if any `baseline_required` type is missing (`V15_BASELINE_MISSING`).

Builtin phase placement: `iteration_limit` at `llm_query/enter`; `recursion_limit` at `invoke/enter` (disable at equal depth, abort above); `budget_pool` at `llm_query/enter` and `exit`; `budget_forcing` at `repl_exec/complete` (first N returns become `continue`, counter per invoke); `context_window_warning` at `llm_query/enter` as a **transient** message whose text is the two-statement SQL delegation in R1, naming `jaz.history` and `jaz.prior_history`, not `__history__` and not `return invoke(...)`.

### 10. Governance and budgets

Freeze the singleton manifest and the tighten-only rule. `v15_assert_manifest` is real from stage 1. Numeric comparisons live only in the stage 9 baseline hooks, reading the same columns. Iteration abort when `iteration >= max_iterations`, before lease. Recursion: depth starts at 1. Worker `statement_timeout` is `min(resolved repl timeout, manifest max_statement_ms, per-statement pragma)`. Pool `UPDATE ... WHERE calls_used + calls_reserved < calls_limit` is the reservation, lock `budget_pools` before `invokes`, and the dispatcher performs it while applying the phase. Context-window ratio uses FakeLLM `prompt_tokens` when present, else `length/4`, and the warning text says so.

### 11. I/O and unknown

Freeze the request/attempt split and R3’s status rules. Reclaim is `v15_reclaim_expired`, a normal transaction that does not call FakeLLM. `failed` is allowed only when the worker has not started the call. `n` starts at 1 and must stay `<= max_io_attempts`.

### 12. Error codes

Freeze sqlstate assignment (confirm `P15` is absent from PG 18.4 `errcodes.txt` before coding; if it is present, stop and renumber in this document rather than picking a private code in a gate):

| Code | SQLSTATE | When |
|---|---|---|
| `V15_GOVERNANCE_MISSING` | P1501 | Manifest row missing or ceiling non-finite |
| `V15_GOVERNANCE_RAISE` | P1502 | Caller ceiling looser than manifest |
| `V15_GOVERNANCE_FAULT` | P1503 | Baseline handler raised |
| `V15_BASELINE_MISSING` | P1504 | Required baseline row absent at lease |
| `V15_ITERATION_EXCEEDED` | P1505 | `iteration >= max_iterations` |
| `V15_RECURSION_EXCEEDED` | P1506 | `depth > max_depth` |
| `V15_RECURSION_DISABLED` | P1507 | `bind_invoke` at the leaf |
| `V15_BUDGET_EXHAUSTED` | P1508 | Pool cannot reserve; fatal |
| `V15_IO_EXHAUSTED` | P1509 | Attempt cap; non-fatal |
| `V15_STALE_FENCE` | P1510 | Fence mismatch |
| `V15_ATTEMPT_NOT_SETTLEABLE` | P1511 | Settle of unknown/failed/settled |
| `V15_INVOKE_FORM` | P1512 | Control call not a canonical sole statement, or function actually executed |
| `V15_INVOKE_EXPR_WRITE` | P1513 | bind argument tried to write in the read-only eval |
| `V15_DIALECT` | P1514 | Forbidden statement kind |
| `V15_DDL` | P1515 | Event trigger rejected DDL |
| `V15_ROLE` | P1516 | `current_user` mismatch |
| `V15_TOOL_UNAUTHORIZED` | P1517 | No grant |
| `V15_EXTERNAL_TOOL` | P1518 | `external` catalog row |
| `V15_SCOPE_CONFLICT` | P1519 | Scope name also passed as input |
| `V15_HISTORY_SCOPE` | P1520 | `prior_history` uuid is not self/ancestor |
| `V15_CONFIG_LOCAL` | P1521 | Two local layers |
| `V15_DEPTH_SELF` | P1522 | Nested depth map |
| `V15_BASELINE_IMMUTABLE` | P1523 | Layer tries to replace baseline set |
| `V15_BLACKBOARD_CONFLICT` | P1524 | Same phase, same key, unequal jsonb |
| `V15_INPUT_CONFLICT` | P1525 | Same name, unequal jsonb |
| `V15_INVALID_EFFECT` | P1526 | Effect not legal for the phase |
| `V15_PHASE_CONTRACT` | P1527 | Contract version or unknown keys |
| `V15_CHILD_ERROR` | P1528 | Non-fatal child failure surfaced to parent |
| `V15_PRINT_AND_RETURN` | P1529 | Print plus return/raise in one iteration |
| `V15_HOOK_REGISTER` | P1530 | Handler failed ownership / volatility / grant checks |

### 13. Deviation ledger (seed)

Record these as accepted; do not “fix” them back to CPython:

1. The REPL language is a SQL statement list. `π` is identity over that text.
2. Invoke suspends between statements, not inside an expression or a `DO` body.
3. Tail delegation is the two-statement form in R1. Same-iteration bind is required; an extra parent LLM turn is a bug, not a deviation.
4. The history relation is `jaz.history` with the columns in R4. There is no `"__history__"` list and no `BaseException` object (`repl_exception` is jsonb).
5. Values are jsonb. Coalesce uses jsonb equality. No `__jaz_get__`, no by-identity wrappers. The host serializes before `v15_open_invoke`.
6. Scope is a snapshot copy at child open.
7. History handover is an ancestor uuid plus `jaz.prior_history`, not a shared mutable object and not a jsonb copy of the transcript.
8. Iteration, recursion, I/O-attempt, and statement-timeout ceilings are mandatory and finite. In jaz they are opt-in (recursion unbounded by default).
9. A local recursion hook may tighten. Jaz rejects that channel; v15 does not, because the baseline still propagates.
10. An expired LLM attempt stays `unknown`; retry is a new row. Cost of a real provider call that might have happened is not refunded. v15 does not implement jaz’s in-process retry and does not implement provider exactly-once.
11. BudgetForcing’s refusal count is per invoke, not one mutable object across a `with` block.
12. Capture is `jaz.print` into `iterations.capture`. There is no stdout proxy.
13. A child error skips the rest of the parent statement list (`V15_CHILD_ERROR`). There is no in-list `try/except` around a child. Fatal aborts walk ancestors; ordinary aborts do not.
14. Earlier statements of a failed iteration remain committed.
15. Handlers are registered `regprocedure`s. The model cannot `CREATE FUNCTION` a hook.
16. Config is frozen on the invoke at open.
17. No `ainvoke` and no in-iteration parallel map.
18. `DO` locals are cell-local.
19. ReturnType, ValidateReturn, ValidateREPLCode, replay, and tracing backends are out of scope. Their effect names are reserved and rejected.
20. Baseline handler exceptions fail closed. Jaz logs and continues for every hook; v15 keeps log-and-continue only for non-baseline hooks.
21. Volatility is not a write barrier. Grants plus “handlers return effects” are.

Preserved on purpose (not deviations): 0-based iterations; history row only after the iteration finishes; terminal `repl_output` is `''`; print-and-return is rejected; component replace rather than deep-merge; blackboard generation barrier; root depth 1; disable-at-cap and abort-past-cap.

### 14. Gate plan

Freeze `v15/load.py` as a cumulative `SQL_LOAD_ORDER` / `STAGE_THROUGH` copy of the v13 loader. Each stage directory has `setup_db.py` (DROP/CREATE `agent_v15_<stage>`, `load_stage` through itself) and one `test_<stage>.py`. The stage 9 file is the only `CREATE OR REPLACE` of `v15_on_phase`. Schema SQL keeps the proceed stub forever so a reorder cannot load the full dispatcher before later objects exist; plpgsql late binding is not an excuse to move it earlier.

| Stage | SQL | Gate | Must prove |
|---|---|---|---|
| 1 schema | `v15/schema/v15_schema.sql` | `test_schema.py` | Matrix negatives; `v15_repl` cannot `set_config`, `pg_sleep`, TEMP, or `CREATE FUNCTION`; manifest assert; stub contract; event trigger rejects `CREATE FUNCTION` |
| 2 namespace | `v15/namespace/v15_namespace.sql` | `test_namespace.py` | Scope copy vs input non-copy; `V15_SCOPE_CONFLICT`; history isolated; `prior_history` ancestor check; `v15_repl` cannot forge `exec_context` |
| 3 config | `v15/config/v15_config.sql` | `test_config.py` | Fold order; whole-object replace; local layer absent on child; depth partial isolation; `V15_DEPTH_SELF`, `V15_CONFIG_LOCAL`, `V15_BASELINE_IMMUTABLE` |
| 4 protocol | `v15/protocol/v15_protocol.sql`, `split_sql.py` | `test_protocol.py` | Dollar-quote and nested-comment cases below; sole-form classifier; prompt contains the R4 history paragraph and the two-statement bind; observation truncated, stored output not |
| 5 repl | `v15/repl/v15_repl.sql` | `test_repl.py` | Scratch CREATE/INSERT; sibling schema USAGE denied; DO locals not bindings; return/raise/print/assign; print-and-return; committed statement not re-run after a killed connection; `jaz.bind_invoke` executed as SQL raises and inserts nobody |
| 6 io | `v15/io/v15_io.sql` | `test_io.py` | Stale fence; expiry → `unknown` + new row; late settle rejected; `failed` only if the call was not started; conservative `calls_used`; cap `V15_IO_EXHAUSTED` |
| 7 loop | `v15/loop/v15_loop.sql` | `test_loop.py` | FakeLLM strictly outside a transaction (`txid` changes); one history row per finished iteration; empty message consumes an iteration; phase stub proceed; abort result from a test double of the contract skips I/O; manifest missing fails open |
| 8 tree | `v15/tree/v15_tree.sql` | `test_tree.py` | Parent `llm_attempts` count unchanged across a child; bind visible to the next statement; scope snapshot; child raise → `V15_CHILD_ERROR`; fatal aborts ancestors; suspended parent not claimable |
| 9 govern | `v15/govern/v15_govern.sql` | `test_govern.py` | Conflict and coalesce; generation barrier; baseline fault vs non-baseline continue; local hook absent on child; ceilings; tighten/raise; pool reserve across parent and child; BudgetForcing; transient context warning not stored in `llm_messages`; same-session `CREATE OR REPLACE` visible without reconnect; unauthorized tool |

Stage 7’s “test double” of the phase contract is a **fixture function installed by the test into a table the stub consults**, or a test-only wrapper schema, and it MUST NOT be in `SQL_LOAD_ORDER`. Production `v15_on_phase` in stages 1–8 only returns proceed.

### 15. Non-authoritative

These MUST NOT be used to overturn §0: the jaz Python REPL sandbox (import/attribute allowlists, stdout proxy, compiler), Jinja templates, `__history__` attribute wording, eval harness prompts under `jaz-evals/`, the StuLife/AppWorld prompt appendices, v8 `sessions` / `effect_requests` / plugin generations, v13 stage layout, round-1 chat wording where it disagrees with this document (in particular any “retry the same FakeLLM row in place” sentence), psycopg exception class names, and token-native stamp-back. The jaz paper’s two properties and the v8 rule “external I/O is not in a transaction; unknown is not success” are authoritative. Pinned Python behavior cited in §0 is authoritative only at the granularity written there.

### 16. Freeze protocol

This file, once committed, changes only by a new design revision. A behavior change lands in the same commit as the deviation-ledger edit and the gate that pins it. Implementations MUST NOT weaken a gate to match code. If PG 18.4 `errcodes.txt` already contains `P15`, implementation stops and this section 12 is renumbered before any gate asserts a sqlstate. `CREATE OR REPLACE` of `v15_on_phase` outside `v15/govern/v15_govern.sql` is a contract break.

---

## What will bite on PG 18.4

**`DO` and dollar quotes.** The outer statement `DO $body$ ... $body$;` is one cell; semicolons inside the tag are not statement boundaries. Tags nest and are not only `$$` (`$a$` … `$b$` … `$b$` … `$a$`). The splitter must track tag state, standard strings, `E''` / `U&''`, escaped quotes, line comments, and **nested** block comments (`/* /* */ */` is one comment in Postgres). A regex split will both cut a `DO` in half and glue two statements together. Gate strings: `DO $$ BEGIN PERFORM 'a;b'; END $$;`, `DO $body$ BEGIN PERFORM $$;$$; END $body$;`, `DO $a$ BEGIN PERFORM $b$ ; $b$; END $a$;`, a nested block comment containing `;`, and two real statements after such a `DO`.

**The classifier must not “parse inside” the `DO` string, and must not trust that omission.** Outer-only parse sees `DO <text>` and will miss `PERFORM jaz.bind_invoke(...)` in the body. Require a raw substring rejection of `jaz.bind_invoke` / `jaz.return` / `jaz.raise` on every non-canonical statement (false positives in comments and literals are acceptable). The security backstop is separate: the function raises and does not insert, so an `EXCEPTION WHEN OTHERS` around an obfuscated `EXECUTE 'jaz.' || 'bind_invoke'` cannot create a child. Do not spend the stage on a plpgsql parser.

**`SET` inside `DO` bypasses a statement-level SET ban.** `search_path` and `role` are GUCs. Revoke `EXECUTE` on `pg_catalog.set_config(text,text,boolean)` from PUBLIC in this dedicated database and grant it only to `v15_worker` and owner. Also revoke from `v15_repl`: `pg_sleep` and its interval forms, `pg_read_file` / `pg_read_binary_file` / `pg_ls_dir` / `pg_stat_file`, `pg_advisory_lock` family, `pg_terminate_backend`, `pg_cancel_backend`, `lo_import` / `lo_export`, and `dblink` if present. Revocation is database-local; `setup_db` must not call those afterward.

**Scratch USAGE.** Granting `v15_repl` USAGE on every `s_<hex>` at create time lets a `DO` block `SET search_path` to a sibling invoke’s schema. Grants are transactional. The committed state has **no** USAGE for `v15_repl`. The worker’s statement transaction is: update `exec_context`, `GRANT USAGE` on this scratch schema only (no GRANT OPTION), `SET LOCAL ROLE v15_repl`, run the one statement, `RESET ROLE`, `REVOKE USAGE`, commit. Crash aborts the grant with the statement. Schema owner stays `v15_worker`. Table owner may be `v15_repl` and still cannot see the schema without USAGE.

**Do not implement `exec_context` as a GUC or a temp table.** `set_config` is the GUC hole above. Temp tables are session-visible; a model `CREATE TEMP TABLE` can squat on the name the worker expects. `REVOKE TEMP ON DATABASE … FROM PUBLIC` and do not grant TEMP to `v15_repl`. Permanent `v15.exec_context`, worker-only DML, overwritten at the start of every model transaction in that same transaction. `jaz.*` reads it as SECURITY DEFINER by `pg_backend_pid()` with `search_path` pinned so a scratch object cannot shadow `pg_catalog`.

**Event triggers are not the sandbox.** `ddl_command_end` does not see `SET`, `SELECT`, or function calls. It does not cover global objects (roles, databases); those are already impossible for a non-superuser. It **must** still reject, for `current_user = v15_repl`, everything except `CREATE/DROP TABLE`, `CREATE/DROP INDEX`, `ALTER TABLE` that stays in the current scratch schema (no owner change, no `ENABLE ROW LEVEL SECURITY` as an escape, no `SET SCHEMA`), and `CREATE TABLE AS` / `SELECT INTO` into that schema. `CREATE FUNCTION/PROCEDURE/TRIGGER/RULE/POLICY/EVENT TRIGGER/EXTENSION/FOREIGN TABLE` are `V15_DDL`. Worker `CREATE SCHEMA s_<32 hex>` is allowed; `v15_repl` creating a schema is not. Verify on 18.4 that `CREATE TEMP TABLE` is either caught by this trigger or already impossible via TEMP revoke — the gate should attempt it and require failure, not assume the matrix.

**security_barrier.** Define `jaz.history` with `security_barrier = true` and `security_invoker = false`, and revoke SELECT on `repl_history` from `v15_repl`. Barrier views still leak through **error messages and planner estimates**; they do not stop a `LEAKPROOF` function the operator marked carelessly. Do not mark model-callable functions LEAKPROOF. The gate: a second invoke’s rows are invisible; a function in the outer SELECT list granted to `v15_repl` does not observe the other invoke; `EXPLAIN` is not a supported isolation boundary (ledger it, do not pretend otherwise).

**`regprocedure` and `CREATE OR REPLACE`.** Replacement keeps the oid; `DROP` + `CREATE` does not, and every `invoke_hooks` row would dangle. Spec forbids drop. Call with `format('%s($1,$2)', oid::regprocedure)`, which is schema-qualified and does not consult `search_path`. Plpgsql caches plans; PG invalidates them when the callee is replaced, but stage 9’s gate MUST show a **same-session** call after `CREATE OR REPLACE` sees the new body. Do not `PREPARE` model statements across a suspend/resume — `jaz.var` would be a stale plan. Simple query protocol each statement.

**Read-only bind arguments.** `READ ONLY` rejects DML even from SECURITY DEFINER, including `nextval`. Evaluate `SELECT (<jsonb-expr>)` only, never `SELECT jaz.bind_invoke(...)`. A volatile function in the expr that writes fails the statement with `V15_INVOKE_EXPR_WRITE` and creates no child.

**Handler STABLE is a promise, not a check.** The registration predicate must look at `pg_proc.provolatile`, `proowner`, `proconfig`, `prolang`, and `has_table_privilege` for the owner. A STABLE body that updates a table will still run if the owner has the grant — so the owner must not have the grant, and budget math stays in the dispatcher.

**`v15_on_phase` late binding is why the stub’s signature is frozen in stage 1.** Callers bind by oid. Stage 9 changes the body only. Adding an argument in stage 9 silently leaves the loop calling the old oid if someone creates a second overload. One signature, forever in v15: `(invoke_id uuid, iteration int, span text, phase text, io jsonb) returns jsonb`.

**Statement timeout vs `statement_timeout` GUC.** Set it with `SET LOCAL` in the worker transaction **after** `SET ROLE`, from the manifest cap. A `DO` block can still `SET LOCAL statement_timeout = 0` unless that GUC is not settable by `v15_repl`. Lock it down the same way as `search_path`: after role switch, the worker (as a definer helper) should set the timeout, and `v15_repl` must not be able to raise it. If a gate shows `SET LOCAL statement_timeout` inside `DO` succeeds, add `statement_timeout` to the parameters the role cannot set (`ALTER ROLE v15_repl` does not do this per statement). Practical enforcement that does work: a **clock in the worker** around the statement (Python deadline) plus the GUC as a backstop. The worker deadline is the one the model cannot clear. Freeze both; do not rely on the GUC alone.

**Custom sqlstate `P15xx`.** Five characters, class `P1`. `P0001`–`P0004` are plpgsql and will make every gate that matches “raise_exception” pass for the wrong reason. Assert `diag.sqlstate`. Unknown classes surface in psycopg as `DatabaseError` / `InternalError`; do not match exception subclass.

**Same-txn `exec_context` rollback.** A failed model statement rolls back the context update with it. The next statement must overwrite the pid row again before any `jaz.*` call. A reused backend pid after crash is safe only because of that overwrite, not because pids are unique over time.

**Hook SAVEPOINT vs baseline.** A SAVEPOINT around a baseline handler that raises, followed by “continue the loop,” would recreate the jaz footgun R2 closes. Baseline failure aborts the phase transaction. Non-baseline failure rolls back to the SAVEPOINT, writes an `invoke_events` row, and continues. The govern gate needs both cases in one phase.

### Oracle 2
- Status: Completed
- Provider: `codex`
- Model: `gpt-5.6-sol`
- Effective effort: `xhigh`
- Chat: `new-chat-oracle-2-B4017F`



# Summary

Round 2 should freeze the grok architecture with one correction in terminology: v15 uses a **statement-list continuation state machine**, not literal suspension inside a PostgreSQL statement. The model response is preserved verbatim, split into PostgreSQL top-level statements with a dollar-quote-aware scanner, and executed statement by statement; `jaz.bind_invoke(...)` commits its statement, persists the parent cursor at the next statement, and resumes there after child delivery without another parent LLM call. The implementation remains a new `v15/` vertical that reuses JAZ’s semantic contracts and v8’s fencing/unknown-outcome patterns, but does not modify v8/v13 tables or runtime code.

# Current-state analysis

## Existing JAZ responsibilities and data flow

The Python implementation has four relevant layers.

1. **Invocation construction — `jaz/src/jaz/invoke.py` and `_invoke_tool.py`**
   - Public `invoke()` extracts one local `ConfigOverride`, validates positional hooks, resolves the active `Prehook`, resolves ambient `jaz.scope`, and constructs a per-invoke `Agent`.
   - `_build_invoke_setup()` resolves configuration using the existing stack order:
     `base → global depth layer → propagating layers → local override`.
   - The synthesized recursive tool from `_invoke_tool.py` closes over the parent scope, config stack, hook context, and child depth.
   - A Python child call is a normal blocking function call; the parent Python frame remains live until the child returns or raises.

2. **Agent loop — `jaz/src/jaz/_agent.py`**
   - `Agent.invoke()` resolves input wrappers through `resolve_inputs()` from `inputs.py`.
   - It seeds a per-invoke `Blackboard`, dispatches `InvokeEnter`/`InvokeSend`, initializes `REPLState`, renders the opening messages, and owns the `__history__` list.
   - Each iteration performs:
     `LLMQuery Enter/Send/provider/Complete/Exit → protocol.parse() → REPLExec Enter/Send/exec/Complete/Exit → history → observation`.
   - The loop terminates on `Return`, `Raise`, or an effect-driven abort.

3. **Protocol and REPL — `jaz/src/jaz/protocol/code_only.py`, `repl/base.py`, `repl/python_repl.py`**
   - `CodeOnlyProtocol.parse()` is effectively identity parsing: the entire model response becomes Python source.
   - `PythonREPL` owns a persistent mutable namespace, captures output, binds inputs and `__history__`, and converts top-level `return`/`raise` into `Return`/`Raise` results.
   - `REPLState` is per-invoke, while the configured REPL object is reusable.
   - The current protocol history entry stores the full response, output, and a Python exception object; v15 must replace the exception object with structured JSON.

4. **Hooks, effects, configuration, and scope**
   - `hooks/events/*` defines the closed span taxonomy: Invoke, LLMQuery, and REPLExec each have Enter/Send/Complete/Exit; LLMQuery also has Retry.
   - `hooks/effects.py` defines the closed effect algebra and event-specific validity.
   - `hooks/dispatcher.py` snapshots events, dispatches all hooks against the same event/blackboard generation, composes effects, and applies blackboard writes after the handler loop.
   - `hooks/blackboard.py` implements same-event conflict detection and next-event visibility.
   - `config.py` implements ordered raw layers and depth resolution.
   - `scope.py` uses a `ContextVar` for same-context propagation and snapshots scope into child setup data for worker/thread boundaries.

## PostgreSQL constraints that force the v15 architecture

The Python call stack cannot be transplanted literally.

- A PostgreSQL transaction cannot remain open while an LLM or external tool call occurs.
- PostgreSQL cannot pause an executing SQL statement or `DO` block, perform child work in another transaction, and resume the original statement at its expression boundary.
- Backend-local state, temporary tables, GUCs, prepared statements, Python object identity, live callables, and `ContextVar` values cannot be authoritative across worker restart or connection changes.
- A PostgreSQL SQL function cannot safely call an arbitrary registered hook through a privileged `SECURITY DEFINER` dispatcher without accidentally giving the hook the dispatcher’s privileges.

The correct v15 architecture is therefore a **durable program/cursor state machine**. The implementation must preserve JAZ’s observable semantics where possible while recording every necessary deviation explicitly.

## Reusable existing patterns

Reuse the following concepts, not their Python or v8 storage implementations:

- `CodeOnlyProtocol`’s identity-parser principle.
- `ConfigStack.resolve_for_depth()`’s exact precedence order.
- JAZ’s Enter/Send/Complete/Exit span lifecycle.
- JAZ’s event-specific effect validity and deterministic composition.
- `Blackboard._apply_writes()`’s generational write barrier.
- JAZ’s explicit-input versus scoped-input distinction.
- v8’s independent lease/fence identities, stale-settlement rejection, `unknown` external outcomes, and `NOTIFY`-as-wake-hint rule.
- v8/v13’s cumulative loader and standalone gate convention.

Do not reuse:

- Python `Agent`, `PythonREPL`, `ContextVar` state, live hook objects, or Python exception values as authoritative runtime state.
- v8/v13 tables, SQL functions, schemas, or load files.
- A single-cell executor as the primary REPL model.
- A generic `SECURITY DEFINER` hook dispatcher that executes user handlers with kernel privileges.

# Design

## Round-2 adjudication

### R1 — statement-list SQL REPL with continuation

**Verdict: Agree, with the implementation-critical refinement that suspension is between top-level statements, never inside a statement or `DO` block.**

The model response remains the protocol identity: it is stored verbatim and split into a list of PostgreSQL statements. Each statement commits independently. A top-level `jaz.bind_invoke(bind_name, inputs_jsonb)` action commits the current statement, creates the child, stores the parent cursor at the next statement ordinal, and leaves the parent REPLExec span open. When the child returns, v15 binds the result and resumes at that ordinal without issuing another parent LLM request. This directly fixes the codex proposal’s V15-D01 and preserves tail-delegation economics. A `DO $$...$$;` block is one statement; its local variables are cell-local and it cannot suspend for a child or external tool. The splitter must treat semicolons inside dollar-quoted bodies as content, not delimiters.

The following are frozen:

- `jaz.bind_invoke` is a **continuation action**, not a synchronous SQL expression.
- It may be used only in a top-level SQL statement, not inside `DO`.
- A successful child return is bound to the requested variable name before the next statement starts.
- The next statement is executed from the persisted cursor; the bind statement is never rerun.
- If the statement list has no next statement, the program completes normally and the next LLM call is an ordinary new iteration; v15 does not claim that every child call eliminates all future parent LLM calls.
- A terminal `jaz.return` or `jaz.raise` ends the program after its containing statement commits; later statements in the stored list are dead and are not executed.
- A statement error stops the current program, rolls back that statement, records a recoverable structured observation, and does not execute trailing statements.

The child-error policy must be explicit in the final document: a normal child `Raise` is delivered as a structured child outcome and ends the current parent program as a recoverable error; a fatal child failure propagates as a parent machinery failure. v15 does not promise Python-style `try/except` around a child suspension across statement boundaries.

### R2 — governance hardening

**Verdict: Agree without change.**

The governance manifest, finite mandatory limits, tool grants, hook ownership restrictions, fixed `search_path`, `STABLE`/`IMMUTABLE` handler requirement, no kernel-table grants, `P15xx` SQLSTATE family, authority matrix, and fail-closed behavior are all required. The final design must add one privilege-separation detail: hook handlers must execute under an unprivileged `v15_hook_runner` current user, while the worker applies their returned effects under the kernel role in a separate controlled phase.

### R3 — unknown attempts and FakeLLM determinism

**Verdict: Agree with request-level retry refinement.**

An expired or abandoned `io_attempts` row transitions to `unknown` permanently; that attempt is never settled later and is never reused. If the request policy allows retry, v15 creates a new attempt row for the same logical request. The request remains pending until the new attempt settles or the request reaches its retry terminal state.

FakeLLM must be deterministic by **logical request identity plus explicit retry ordinal**, not by “number of callback invocations.” This permits tests to assert that an unknown attempt creates a new attempt without making a deterministic FakeLLM produce a different answer merely because the worker crashed.

### R4 — naming surface

**Verdict: Agree.**

The model-facing schema is `jaz`; kernel tables and transition functions are in `v15`.

The frozen model-facing functions are:

```text
jaz.var(name text) → jsonb
jaz.assign(name text, value jsonb) → void
jaz.print(value jsonb) → void
jaz.tool(bind_name text, tool_name text, args jsonb) → void
jaz.return(value jsonb) → void
jaz.raise(error jsonb) → void
jaz.bind_invoke(bind_name text, inputs jsonb) → void
```

The exact `jaz.tool` signature intentionally includes both a destination name and a catalog tool name, because external tool execution cannot return synchronously inside the SQL statement.

The history surface is the read-only view `jaz.history`. PostgreSQL technically permits an unquoted identifier beginning with underscores, but `jaz.history` is the better frozen interface because it is an explicit relation, avoids pretending that SQL has a Python magic variable, and makes the prompt wording unambiguous.

The prompt must say:

> The current invoke’s completed interaction history is available as the read-only relation `jaz.history`. Query it with SQL, for example `SELECT ... FROM jaz.history ORDER BY iteration`. It is not writable and does not include the currently executing program until that program completes.

### R5 — stage order and hook timing

**Verdict: Agree with the grok ordering and use a permanent no-op hook stub.**

Stage 1 creates a stable `v15_on_phase(phase_id uuid)` signature whose initial implementation returns an empty decision. Stages 5–7 call that function at the defined phase boundaries but therefore run without hook behavior. Stage 9 creates the hook registry/effect/blackboard machinery and `CREATE OR REPLACE`s the same function signature with the real dispatcher.

This ordering is preferable because:

- Stage 5 can prove the dynamic SQL executor before hook behavior exists.
- Stage 7 can prove the complete loop against a no-op phase dispatcher.
- Stage 9 can test that hooks alter already-proven loop behavior rather than making hook implementation a prerequisite for the first loop gate.
- The phase function’s signature is fixed early, preventing later hook work from changing loop call sites.

The stub and replacement must have identical argument and return types. Function bodies may late-bind tables introduced in stage 9, but earlier stages must never reference hook tables that do not yet exist.

---

## Target document skeleton: `docs/designs/v15-jaz-dev.md`

The following is the complete section/subsection outline. Each line states what that section freezes.

### Document header

#### Title and status

Freezes v15 as a new PostgreSQL-native JAZ implementation specification for PostgreSQL 18.4, not a modification of v8 or v13.

#### Authority statement

Freezes this document as the normative behavior contract; Python JAZ, the paper, v8/v13 documents, and implementation digests are references only where explicitly cited.

#### Version and environment baseline

Freezes the `v15/` tree convention, PostgreSQL 18.4, `uv run python v15/<stage>/test_*.py`, exit code 0 as pass, and FakeLLM/FakeTool-only tests.

#### Input fingerprints

Records the exact fingerprints of the JAZ paper, selected JAZ source files, `AGENTS.md`, v8/v13 loader conventions, and the v15 design baseline used for implementation.

---

## §0. Non-negotiable invariants

1. **Version isolation.** v15 MUST use only the `v15` schema/tree and MUST NOT modify v8/v13 SQL, load order, frozen specifications, or persisted data.
2. **Database authority.** Invoke state, program source/cursors, variables, configuration snapshots, requests, attempts, waits, deliveries, spans, phases, effects, and blackboard generations MUST be authoritative relational state, not reconstructible projections.
3. **Controlled mutation.** `v15_repl` MUST NOT receive direct table DML privileges on `v15`; model code MUST mutate framework state only through the `jaz` API.
4. **External I/O boundary.** LLM and external-tool calls MUST NOT execute inside a PostgreSQL transaction; the claim transaction MUST commit before the worker calls the provider, and settlement MUST use a later fenced transaction.
5. **Persisted execution.** A worker crash MUST leave enough durable state to resume or fail closed without relying on Python stack frames, backend-local variables, temporary tables, or `ContextVar`s.
6. **Identity protocol.** The model response MUST be stored verbatim; protocol parsing MUST not extract markdown/XML code blocks or rewrite the response before statement splitting.
7. **Statement boundaries.** Each top-level statement MUST execute in its own bounded transaction; v15 MUST NOT suspend inside a statement or `DO` block.
8. **Dollar-quote-aware splitting.** The splitter MUST recognize single-quoted strings, escaped strings, quoted identifiers, line comments, nested block comments, and tagged/untagged dollar-quoted strings; semicolons inside those constructs MUST NOT split the response.
9. **Action cardinality.** One statement MUST contain at most one state-changing `jaz` action; multiple action calls or incompatible action/DML combinations MUST fail with `V15_EXEC_PROTOCOL`.
10. **Statement cursor monotonicity.** A committed statement ordinal MUST advance exactly once; a worker MUST NOT rerun a statement whose completion transaction committed.
11. **Continuation semantics.** `jaz.bind_invoke` MUST persist the next statement ordinal and resume there after a successful child delivery without another parent LLM query.
12. **Child delivery idempotency.** Child completion and parent delivery MUST be compare-and-swap/fence protected; duplicate or reordered deliveries MUST be no-ops, and lost notifications MUST be recoverable by scanning.
13. **Independent fences.** Invoke claims, I/O attempts, statement execution leases, and parent-delivery claims MUST have independent fences; an old fence MUST never settle or advance state after takeover.
14. **Unknown external outcomes.** An expired I/O attempt MUST become `unknown`; it MUST NOT be silently converted to an ordinary failure or settled later; a retry MUST create a new attempt row.
15. **Namespace addressability.** Every explicit input and scope binding shown to the model MUST be addressable through `jaz.var`, `jaz.variables`, or a granted catalog view; explicit inputs MUST NOT silently shadow scope bindings.
16. **History addressability.** The completed invoke history MUST be available through `jaz.history`; the view MUST expose only the current invoke’s rows and MUST NOT be writable.
17. **Scratch isolation.** Model-created relations MUST live only in the invoke’s scratch schema; the model MUST NOT create functions, procedures, extensions, roles, schemas, databases, or privileged objects.
18. **Span closure.** Every opened Invoke, LLMQuery, or REPLExec span MUST close with `Completed`, `Aborted`, or `Failed`, including worker crash recovery and fatal-unwind paths.
19. **Immutable phase snapshots.** Every hook handler for a phase MUST observe the same immutable event payload, active-hook order, config snapshot, and blackboard generation.
20. **Closed effects.** Effects MUST belong to the frozen effect taxonomy; an effect invalid at a phase MUST fail loudly and MUST NOT be ignored.
21. **Generational blackboard.** Blackboard writes from phase E MUST be invisible to every handler dispatched for E and MUST become visible only at the next generation.
22. **Configuration precedence.** Config resolution MUST be `base ⊕ exact-depth ⊕ propagating layers in declaration order ⊕ local`; later layers win by whole-component replacement.
23. **Frozen configuration.** An invoke MUST persist its resolved config and layer references at open time; later global config changes MUST affect only later invokes.
24. **Governance fail-closed.** A missing, disabled, mismatched, unauthorized, or failed mandatory governance manifest MUST prevent invoke advancement with a `V15_GOVERNANCE_*` error.
25. **Mandatory finite limits.** Every root MUST receive finite operator iteration and recursion ceilings; callers MAY tighten them but MUST NOT raise, remove, or bypass them.
26. **Privilege enforcement.** Safety and authorization constraints MUST be enforced through PostgreSQL roles, grants, ownership, and transition-function checks, not merely prompt instructions or naming conventions.
27. **Deterministic tests.** All standalone gates MUST use FakeLLM/FakeTool and MUST NOT contact real providers or external networks.
28. **Cumulative gates.** Every later stage gate MUST load and pass all earlier registered stages before the stage is considered complete.

---

## §1. Semantic target and architecture

### §1.1 JAZ properties preserved

Freezes that model-written SQL is Turing-complete within the permitted PostgreSQL/PLpgSQL dialect and that recursive invocation plus addressable inputs/history remain the two defining properties.

### §1.2 JAZ-to-v15 semantic mapping

Maps Python `invoke`, REPL state, inputs, scope, `__history__`, hooks, config, and exceptions to v15 rows, views, SQL functions, and durable transitions.

### §1.3 Actors and responsibilities

Defines the host launcher, database kernel functions, SQL execution worker, hook-runner role, LLM/tool provider worker, and test fakes, including which actor may hold a transaction.

### §1.4 End-to-end control chain

Freezes the path:

```text
v15_open_invoke
→ prompt render
→ v15_begin_llm
→ committed claim
→ external FakeLLM/provider call
→ v15_settle_llm
→ split/store statement list
→ v15_begin_exec
→ v15_repl execution
→ v15_finish_exec
→ next statement / child wait / terminal result / next LLM query
```

### §1.5 Scope of v15

Freezes in-scope JSON values, SQL/PLpgSQL REPL, durable child continuation, FakeLLM/FakeTool, config, spans, hooks, blackboard, governance, ACLs, and crash-safe request fencing.

### §1.6 Deferred features

Freezes as later work real provider adapters, provider-specific pricing/retry logic, external tracing backends, user-facing replay/resumability, `<chatName="pg-agent v15 JAZ SQL architecture freeze">

# Summary

Round 2 should freeze a PostgreSQL-native, statement-list JAZ runtime: the model response is preserved as an identity SQL/PLpgSQL statement list, each top-level statement commits independently, and `jaz.bind_invoke(...)` suspends the persisted program **between statements** so the child result is bound before the parent executes its next already-generated statement—without spending another parent LLM call. The implementation remains a durable worker-driven state machine, with `v15` owning kernel state and transitions, `jaz` exposing the model-facing SQL surface, `v15_repl` executing constrained model SQL, and a final hooks/governance stage replacing an early no-op `v15_on_phase` stub. The document should preserve JAZ’s event/effect/blackboard/config semantics where SQL can represent them, explicitly record the unavoidable SQL/JSONB/continuation deviations, and freeze PostgreSQL 18.4 privilege and transaction boundaries before implementation begins.

# Current-state analysis

## Existing JAZ responsibilities and data flow

The Python implementation has four relevant layers.

1. **Invocation setup — `jaz/src/jaz/invoke.py` and `_invoke_tool.py`**
   - Public `invoke()` extracts one local `ConfigOverride`, validates positional hooks, chooses or creates a `Prehook`, resolves dynamic scope, resolves configuration at absolute recursion depth, and creates a recursive closure through `get_invoke_tool()`.
   - `ConfigOverride` passed positionally applies only to the current invoke; context-managed overrides propagate through descendants.
   - `scope.py` uses a `ContextVar` as a same-context bridge, then snapshots scope into descendant setup data so worker-thread calls can inherit it.
   - `_invoke_tool.py` exposes the blocking recursive `invoke()` callable to model-written Python.

2. **Agent loop — `jaz/src/jaz/_agent.py`**
   - Resolves input wrappers through `resolve_inputs()` from `jaz/src/jaz/inputs.py`.
   - Creates one per-invoke `HookDispatcher`, seeds its blackboard, opens the invoke span, applies input effects, initializes a `REPLState`, renders the initial prompt, then repeatedly:
     1. opens an LLM query span;
     2. applies message edits;
     3. calls the LLM;
     4. parses the entire response through the protocol;
     5. opens a REPL execution span;
     6. executes code against persistent REPL state;
     7. appends one history entry;
     8. either appends an observation and loops or returns/raises.
   - `__history__` is a list owned by the agent loop and surfaced by reference through `REPLState`.

3. **Protocol and REPL — `protocol/code_only.py`, `repl/base.py`, `repl/python_repl.py`**
   - `CodeOnlyProtocol.parse()` is effectively identity parsing: the complete LLM response becomes Python source.
   - `PythonREPL` owns a persistent mutable namespace, captures output, rewrites top-level `return`/`raise`, and returns `Continue`, `Return`, or `Raise`.
   - The protocol owns prompt formatting, observation formatting, and `REPLHistoryEntry` construction.
   - JAZ permits arbitrary Python objects and callables, which cannot be persisted or safely represented as PostgreSQL values without a catalog/handle layer.

4. **Hooks and effects — `hooks/events/*`, `hooks/effects.py`, `hooks/dispatcher.py`, `hooks/blackboard.py`**
   - Events are immutable snapshots with `Enter → Send → Complete → Exit` span semantics.
   - Effects are collected from all hooks and composed only after all hooks have observed the same event.
   - `BlackboardWrite` is deferred until the event dispatch loop finishes, then applied as one generation.
   - Hook propagation is process-local/context-local; local hooks belong to one dispatcher and do not propagate.
   - Built-ins such as `IterationLimit`, `RecursionLimit`, `BudgetPool`, `BudgetForcing`, and `ContextWindowWarning` are implemented as ordinary hooks.

## PostgreSQL constraints that force a new topology

The Python implementation cannot be transplanted literally because:

- PostgreSQL cannot hold an open transaction while waiting for an LLM or external tool.
- PostgreSQL cannot suspend a running SQL or PL/pgSQL call and later resume its stack frame after a child invoke completes.
- Backend-local state, temporary tables, GUCs, prepared statements, Python object identity, `ContextVar` state, and live exception objects are not restart-safe authoritative state.
- `jaz.bind_invoke()` can therefore suspend only at a **top-level statement boundary**, never inside an executing `DO` block or arbitrary SQL expression.
- External I/O must be represented by durable requests and attempts, claimed in a short database transaction, executed outside the transaction, and settled through a fenced transaction.

The correct solution is consequently a new vertical `v15/` implementation. It should reuse the semantic contracts from JAZ and the durable lease/fence patterns from v8, but must not reuse v8/v13 tables, loaders, or frozen SQL.

## Reusable extension points

The v15 design should reuse:

- The JAZ event taxonomy from `jaz/src/jaz/hooks/events/__init__.py`.
- The effect families and composition intent from `jaz/src/jaz/hooks/effects.py`.
- The generational blackboard contract from `jaz/src/jaz/hooks/blackboard.py`.
- The exact config resolution order in `jaz/src/jaz/config.py`.
- The identity protocol principle from `jaz/src/jaz/protocol/code_only.py`.
- The protocol-owned history projection concept from `CodeOnlyProtocol.build_history_entry()`.
- The cumulative stage-loader and standalone-gate conventions from `v8/load.py`, `v13/load.py`, and `v13/observe/test_observe.py`.
- v8 invariants 3–8, 11, and 12: independent fences, unknown external outcomes, `NOTIFY` as a hint, fail-closed governance, and database-enforced permissions.

The following must not be copied as implementation mechanisms:

- Python `ContextVar` propagation.
- Python callable/tool identity.
- A live mutable `REPLState`.
- A blocking recursive Python call stack.
- Raw exception objects.
- Hook instances with setup/teardown lifecycle.
- v8/v13 persisted schemas.

# Design

## Round-2 adjudication

### R1 — statement-list SQL REPL with continuation

**Verdict: Agree, with one terminology refinement.**

The model response is a raw SQL/PLpgSQL **statement list**, and `jaz.bind_invoke(bind_name, inputs_jsonb)` suspends the persisted program after its containing top-level statement commits. The parent resumes at the next stored statement ordinal after the child returns, so a parent can consume a child result without another parent LLM query. This replaces codex’s rejected single-cell design and restores the tail-delegation economics of the paper: a depth-70 chain does not automatically incur 70 additional parent-model turns.

The implementation must not claim literal mid-statement suspension. A PostgreSQL statement or `DO` block always runs to completion or rollback. The exact invariant is:

> `jaz.bind_invoke()` suspends **between top-level statements in one stored program**, never inside a SQL statement, PL/pgSQL block, expression, or function stack frame.

A `DO $$...$$;` block is one statement in the list. It may use `jaz.var`, `jaz.assign`, `jaz.print`, `jaz.return`, or `jaz.raise`, but it MUST NOT call `jaz.bind_invoke` or `jaz.tool`; those operations require a continuation boundary and are rejected with `V15_EXEC_PROTOCOL`.

The continuation behavior is:

```text
LLM response
  → split into stored statements
  → execute statement 0
  → execute statement 1
  → SELECT jaz.bind_invoke(...)
  → commit statement 2
  → persist cursor = 3 and parent WAITING_CHILD
  → run child outside the parent transaction
  → bind child Return into parent variable
  → resume statement 3
  → finish remaining statements
  → close one REPL execution span and append one history row
```

If the list ends immediately after the child bind, the parent program completes and the next parent LLM turn is normal; the no-extra-call guarantee applies when the stored list contains subsequent statements that consume the result.

### R2 — governance hardening

**Verdict: Agree without reduction.**

The v15 contract must require:

- An operator-owned, versioned governance manifest.
- Mandatory finite iteration and recursion ceilings.
- Caller limits may be stricter but may never raise, disable, or omit the manifest limits.
- Missing, invalid, stale, or non-executable governance fails closed.
- Tool calls require explicit catalog grants.
- Hook handlers must satisfy ownership, volatility, privilege, and search-path constraints.
- Every custom v15 failure uses SQLSTATE class `P15xx`.
- The authority matrix is part of the frozen specification, not an implementation note.

Because a privileged `SECURITY DEFINER` dispatcher would accidentally execute hook handlers with privileged `current_user`, the final design must invoke registered handlers under a separate unprivileged `v15_hook_runner` role. The dispatcher returns decisions; the worker-owned kernel transition applies them afterward.

### R3 — unknown attempt followed by a new request attempt

**Verdict: Agree with the request-level retry refinement.**

An expired or abandoned `io_attempts` row becomes `unknown`; it is never settled as an ordinary failure and is never reused. If the request policy permits retry, the request remains the same logical request and receives a new attempt row:

```text
io_requests.request_id = R
  attempt 1 → unknown
  attempt 2 → claimed
  attempt 2 → settled
```

The new attempt has a new attempt ID, lease, fence, and provider invocation. This preserves v8’s unknown-outcome rule while allowing FakeLLM tests to continue deterministically.

FakeLLM must default to deterministic responses keyed by the logical request payload/digest, not by “number of times the Python callback happened to run.” Tests that intentionally model non-idempotent providers may opt into attempt-sensitive behavior and must assert that duplicate external effects are possible.

### R4 — naming surface

**Verdict: Agree.**

The frozen schemas and names are:

- Model-facing schema: `jaz`.
- Kernel schema: `v15`.
- Model execution role: `v15_repl`.
- History view: `jaz.history`.
- Model-facing functions:
  - `jaz.var`
  - `jaz.assign`
  - `jaz.print`
  - `jaz.tool`
  - `jaz.return`
  - `jaz.raise`
  - `jaz.bind_invoke`
- Kernel functions:
  - `v15_open_invoke`
  - `v15_claim`
  - `v15_begin_llm`
  - `v15_settle_llm`
  - `v15_begin_exec`
  - `v15_suspend_for_child`
  - `v15_finish_exec`
  - `v15_on_phase`
  - `v15_run_until_quiescent`

PostgreSQL technically accepts identifiers beginning with underscores, but `jaz.history` is the correct frozen surface because it is an ordinary schema-qualified relation rather than an attempted emulation of a Python magic variable. The prompt must say:

> The current invoke’s interaction history is available as the read-only SQL view `jaz.history`; query it with statements such as `SELECT ... FROM jaz.history ORDER BY iteration`.

The prompt MUST NOT describe a bare `__history__` variable.

### R5 — stage order and hook-stub placement

**Verdict: Agree with the preferred order and choose the stub-first topology.**

The nine stages are:

1. schema;
2. values/namespace;
3. config;
4. protocol;
5. repl/loop-exec;
6. io;
7. loop;
8. tree;
9. hooks+govern.

Stage 1 creates a stable no-op `v15_on_phase` signature. Stages 5–8 call it from the beginning, but it returns an empty decision. Stage 9 creates the hook registry, effect algebra, dispatcher, blackboard, governance manifest, and `CREATE OR REPLACE`s the same function signature with the real dispatcher.

This is preferable to loading hooks before the loop because:

- The loop can be proven end-to-end without hook implementation noise.
- The stable phase seam is exercised from the first executable stage.
- The final hook stage can test that the loop actually honors every phase boundary.
- Handler privilege isolation is independently testable after the core state machine is already working.

## Target document skeleton: `docs/designs/v15-jaz-dev.md`

The following is the complete section outline to freeze in the design document. Each subsection’s first sentence should be its normative freeze statement.

### Document header and status

- **Title and status block** — freezes v15 as a new PostgreSQL-native implementation, with this document as its sole behavioral authority.
- **Repository and runtime baseline** — freezes PostgreSQL 18.4, `v15/` as the implementation root, cumulative loading, and standalone Python gates.
- **Reference inputs** — records the JAZ paper, selected Python files, v8/v13 conventions, and `AGENTS.md` as non-authoritative explanatory inputs.
- **Authority disclaimer** — states that the paper defines the two core semantic properties, while this document defines the PostgreSQL realization and intentional deviations.

---

## §0 Non-negotiable invariants

1. **Version isolation** — v15 MUST use only the `v15` schema/tree and MUST NOT modify v8/v13 schemas, loaders, frozen designs, or gates.
2. **PostgreSQL baseline** — every v15 gate MUST run against PostgreSQL 18.4 and MUST fail if required PostgreSQL behavior differs.
3. **Database authority** — invokes, programs, statements, variables, config snapshots, waits, I/O requests, attempts, spans, events, effects, blackboards, and scratch-schema ownership MUST be authoritative relational state.
4. **Projection boundary** — views, prompt renders, `NOTIFY`, ready queues, summaries, and metrics MUST NOT be treated as a second source of truth.
5. **External-I/O boundary** — LLM calls, external tools, network calls, and provider callbacks MUST NOT execute inside a PostgreSQL transaction.
6. **Worker state machine** — the worker MUST persist progress before leaving a transaction and MUST resume from relational state after process or connection loss.
7. **Raw protocol identity** — the complete LLM response MUST be stored without fence extraction or prose repair; protocol parsing may split statements but MUST NOT rewrite source content.
8. **Safe statement splitting** — the splitter MUST recognize PostgreSQL strings, identifiers, comments, nested block comments, dollar-quoted bodies, and semicolon boundaries without regex-only parsing.
9. **Statement continuation boundary** — `jaz.bind_invoke` and `jaz.tool` MUST suspend only after their containing top-level statement commits; they MUST NOT suspend inside a statement or `DO` block.
10. **Statement cursor durability** — a successfully committed statement MUST advance the stored cursor in the same authoritative transaction and MUST NOT be re-executed after acknowledgement.
11. **Statement rollback** — a SQL error rolls back only the current statement transaction; prior committed statements in the same program remain committed, trailing statements do not execute, and the program produces a structured recoverable observation unless the error is machinery-fatal.
12. **Single action per statement** — a model statement MUST contain at most one mutating `jaz` action; multiple action calls or incompatible action combinations MUST fail with `V15_EXEC_PROTOCOL`.
13. **Child continuation economics** — a successful child return MUST bind before the parent’s next stored statement and MUST NOT require another parent LLM query.
14. **Parent/child identity** — every child MUST carry its parent invoke, parent program, parent statement, absolute depth, inherited scope snapshot, inherited config layers, and shared budget-pool identity.
15. **Independent fences** — invoke claims, I/O attempts, execution claims, and child deliveries MUST each have independent fences; stale owners MUST NOT mutate current state.
16. **Unknown external outcomes** — an expired or abandoned external attempt MUST become `unknown`; no worker may fabricate a response or settle that attempt as an ordinary failure.
17. **Request retry identity** — a retry after `unknown` MUST create a new attempt row for the same logical request and MUST NOT reuse the expired attempt identity.
18. **JSONB value domain** — model-visible values MUST be JSONB values or catalog handles; arbitrary Python object identity and live callables MUST NOT enter authoritative v15 state.
19. **Namespace isolation** — explicit inputs and dynamic scope MUST remain separate provenance channels; name collisions MUST fail closed.
20. **History isolation** — `jaz.history` MUST expose only the current invoke’s completed turn history and MUST be backed by authoritative turn/program records.
21. **Scratch isolation** — model SQL MAY create or mutate only objects in its invoke-owned scratch schema; it MUST NOT create persistent functions, extensions, roles, schemas, or objects in `jaz`/`v15`.
22. **Span closure** — every opened Invoke, LLMQuery, and REPLExec span MUST close with `Completed`, `Aborted`, or `Failed`; open spans MUST survive worker transactions but MUST NOT remain silently unclosed.
23. **Hook snapshot semantics** — all handlers for one phase MUST observe the same immutable event, config snapshot, active-hook order, and blackboard generation.
24. **Deferred blackboard writes** — blackboard writes MUST be applied only after every handler for the phase has returned; same-phase writes MUST NOT be visible to peer handlers.
25. **Config precedence** — config resolution MUST be `base ⊕ exact-depth ⊕ propagating layers in declaration order ⊕ local`, with later values winning by whole component.
26. **Mandatory governance** — the operator manifest’s required hooks and finite limits MUST be present, executable, digest-valid, and non-disableable; otherwise the invoke MUST fail closed.
27. **Database-enforced ACLs** — model restrictions, hook restrictions, scratch restrictions, and governance restrictions MUST be enforced by PostgreSQL ownership and privileges, not only by prompt instructions.
28. **Stable error family** — all v15-defined failures MUST use frozen SQLSTATE values in class `P15xx`.
29. **Test-provider isolation** — tests MUST use FakeLLM/FakeTool implementations and MUST NOT invoke real providers or network services.
30. **Cumulative gates** — every stage gate MUST load all SQL through that stage and MUST pass independently with exit code 0.

---

## §1 Semantic objective and architecture overview

### §1.1 JAZ semantic target

Freezes the two properties v15 MUST preserve: model-written executable code may recursively invoke agents, and all invocation inputs plus completed interaction history are programmatically addressable.

### §1.2 PostgreSQL realization

Freezes SQL/PLpgSQL statement lists as the model language, durable tables as runtime state, and a worker as the external-I/O scheduler.

### §1.3 Execution actors

Freezes responsibilities for the model session (`v15_repl`), database kernel (`v15_owner` functions), worker (`v15_worker`), hook runner (`v15_hook_runner`), hook owner (`v15_hook_owner`), and test harness.

### §1.4 End-to-end call chain

Freezes:

```text
v15_open_invoke
  → Invoke phases
  → prompt render
  → v15_begin_llm
  → commit request
  → provider call outside transaction
  → v15_settle_llm
  → split/store program
  → v15_begin_exec
  → execute statement list
  → child/tool suspension or terminal/continue
  → v15_finish_exec
  → history/projection
  → next LLM request or invoke completion
```

### §1.5 In-scope and deferred behavior

Freezes the nine-stage core and explicitly defers provider adapters, external tracing backends, user-facing replay/resumability, `ValidateReturn`, rich return-type validation, fanout, arbitrary relation handles, and Python compatibility.

---

## §2 Authority model and relational schema

### §2.1 Identifier and timestamp rules

Freezes UUID identifiers for logical objects, bigint iteration/statement ordinals, `timestamptz` UTC timestamps, immutable source digests, and explicit revision/fence columns.

### §2.2 Invoke control table

Freezes `v15.invokes` with at least:

```text
invoke_id
root_invoke_id
parent_invoke_id
parent_program_id
parent_statement_no
depth
state
governance_manifest_id
base_config_version_id
resolved_config_snapshot_id
propagating_config_layer_ids
scope_snapshot_id
budget_pool_id
current_program_id
current_iteration
terminal_result
terminal_error
created_at
updated_at
```

### §2.3 Program and statement tables

Freezes `v15.programs` as the authoritative raw LLM program record and `v15.program_statements` as immutable split statements with ordinal, source text, digest, dialect kind, status, and execution outcome.

### §2.4 Turn and message tables

Freezes `v15.turns` and `v15.messages` as authoritative prompt/response state, including raw LLM response, committed SQL source, observation output, structured errors, message provenance, and iteration.

### §2.5 Variables and scope tables

Freezes `v15.variables` keyed by `(invoke_id, name)` with JSONB value, provenance, value kind, visibility, revision, and last-producing program; freezes immutable scope snapshots/layers with shadowing and inheritance metadata.

### §2.6 Tool catalog and authorization tables

Freezes `v15.tool_definitions`, `v15.tool_grants`, `v15.tool_requests`, and tool deliveries, including tool name/digest, input/output schema, execution kind, granted scope, bind name, and result/error state.

### §2.7 Execution-context and scratch tables

Freezes `v15.exec_context` as backend-pid-bound private context state and `v15.scratch_schemas` as the invoke-owned scratch-schema registry; model SQL MUST resolve context through the backend identity rather than a caller-settable invoke ID.

### §2.8 Configuration tables

Freezes immutable base config versions, exact-depth layer records, ordered propagating layer records, local override records, resolved snapshots, component digests, and the child inheritance rule.

### §2.9 I/O request and attempt tables

Freezes `v15.io_requests` as logical work identity and `v15.io_attempts` as claim/fence identity, including unknown outcomes, retry ordinal, lease expiration, provider receipt, and settlement digest.

### §2.10 Wait and delivery tables

Freezes `v15.invoke_waits` and `v15.deliveries` as the authoritative parent/child and parent/tool continuation protocol, with unique idempotency keys based on parent wait and logical result.

### §2.11 Span and phase tables

Freezes `v15.spans` and append-only `v15.phases` for Invoke, LLMQuery, REPLExec, and LLMQueryRetry lifecycle records; phase payloads are immutable JSONB snapshots.

### §2.12 Hook registry and activation tables

Freezes hook definitions, handler procedure identity, handler digest, activation scope, activation ordinal, baseline status, required failure policy, and durable handler state.

### §2.13 Effect and blackboard tables

Freezes immutable raw handler decisions, composed effect decisions, blackboard generations, same-phase pending writes, and applied key/value revisions.

### §2.14 Non-authoritative objects

Freezes the following authority matrix:

| Object | Authority status |
|---|---|
| `v15.invokes` | Authoritative invoke control state |
| `v15.programs`, `v15.program_statements` | Authoritative program source and cursor |
| `v15.turns`, `v15.messages`, `v15.variables` | Authoritative agent-visible state |
| `v15.io_requests`, `v15.io_attempts` | Authoritative external-work state |
| `v15.invoke_waits`, `v15.deliveries` | Authoritative continuation state |
| `v15.spans`, `v15.phases` | Authoritative lifecycle facts |
| Hook registry, activations, decisions, blackboard generations | Authoritative policy/effect state |
| Scratch schema catalogs | Authoritative SQL scratch state |
| `jaz.history`, `jaz.variables`, `jaz.tools` | Non-authoritative filtered views |
| Ready/runnable views | Non-authoritative scheduling projections |
| `NOTIFY` payloads | Non-authoritative wake hints |
| Prompt renders, summaries, metrics | Rebuildable projections |

---

## §3 State machines and transition contracts

### §3.1 Invoke states

Freezes the closed invoke state set:

```text
created
ready_llm
waiting_llm
ready_exec
waiting_child
waiting_tool
completed
raised
aborted
failed
```

### §3.2 Program states

Freezes program states:

```text
stored
running
waiting_child
waiting_tool
continued
completed
raised
failed
```

### §3.3 I/O and attempt states

Freezes request/attempt states, lease ownership, retry limits, `unknown`, and known-failure settlement.

### §3.4 `v15_open_invoke`

Freezes root and child creation inputs, parent linkage, depth calculation, manifest pinning, scope snapshotting, config resolution, scratch-schema allocation, and initial `created → ready_llm` transition.

### §3.5 `v15_claim`

Freezes claim selection, `FOR UPDATE SKIP LOCKED`, worker identity, lease duration, owner fence, and stale-owner rejection.

### §3.6 `v15_begin_llm`

Freezes the transaction that opens the LLM span, resolves `LLMQueryEnter`/`LLMQuerySend`, persists the outbound request, and commits before any provider call.

### §3.7 `v15_settle_llm`

Freezes fenced response/error settlement, `LLMQueryComplete`/`LLMQueryExit`, retry behavior, response persistence, and transition to program execution.

### §3.8 `v15_begin_exec`

Freezes program cursor validation, statement claim, backend context binding, statement timeout, search path, role switch to `v15_repl`, and execution-span ownership.

### §3.9 `v15_finish_exec`

Freezes statement commit, action interpretation, cursor advancement, output/error accumulation, terminal result construction, and the rule that the completed statement cannot run again.

### §3.10 `v15_suspend_for_child`

Freezes child creation from a bind action, parent wait creation, parent cursor advancement, open REPL span retention, and `waiting_child` transition.

### §3.11 Child delivery

Freezes successful child-return binding, recoverable child-error representation, fatal propagation, duplicate delivery no-op, and dropped-wake recovery by authoritative scanning.

### §3.12 Tool delivery

Freezes the equivalent tool continuation path, authorization check, request retry behavior, result binding, and tool-error behavior.

### §3.13 `v15_run_until_quiescent`

Freezes the database-only driver contract: it may advance durable state and return work requiring external execution, but it MUST NOT invoke an LLM or external tool.

### §3.14 Cancellation and interruption

Freezes operator abort behavior, worker crash recovery, statement rollback, external-attempt unknown handling, and remaining-state preservation.

---

## §4 Model-facing namespace and SQL API

### §4.1 Current execution context

Freezes how `jaz` functions locate the current invoke, program, statement, scratch schema, and execution token without trusting a model-settable GUC.

### §4.2 `jaz.var`

Freezes `jaz.var(name text) → jsonb`, including missing-name behavior, reserved names, JSON null, and current-invoke-only lookup.

### §4.3 `jaz.assign`

Freezes `jaz.assign(name text, value jsonb) → void`, durable assignment timing, name validation, revisioning, and statement rollback behavior.

### §4.4 `jaz.print`

Freezes `jaz.print(value jsonb) → void`, output serialization, output buffering, output limits, and history/observation inclusion.

### §4.5 `jaz.return`

Freezes `jaz.return(value jsonb) → void` as a deferred terminal action that ends the program after its containing statement commits.

### §4.6 `jaz.raise`

Freezes `jaz.raise(error jsonb) → void` as a deferred structured terminal raise, including required error fields and fatal/non-fatal classification.

### §4.7 `jaz.bind_invoke`

Freezes `jaz.bind_invoke(bind_name text, inputs jsonb) → void`, requiring a JSON object of named child inputs, one bind action per statement, no `DO`-block use, and direct success-value binding.

### §4.8 `jaz.tool`

Freezes `jaz.tool(bind_name text, tool_name text, args jsonb) → void`, catalog lookup, capability authorization, request staging, suspension behavior, and result binding.

### §4.9 Read-only model views

Freezes:

- `jaz.variables` with name, value, provenance, kind, visibility, and revision.
- `jaz.tools` with only granted tool definitions.
- `jaz.history` with one row per completed LLM/program iteration.
- Optional `jaz.child_results` and `jaz.tool_results` views for structured delivery/error inspection.

### §4.10 History shape

Freezes `jaz.history` columns:

```text
turn_id
invoke_id
iteration
llm_response
program_source
executed_statement_count
stdout
error
outcome
created_at
```

The view is append-derived, read-only, current-invoke-filtered, ordered by iteration, and contains no initialization row or incomplete suspended program.

### §4.11 Context and reserved names

Freezes valid identifier syntax, reserved framework names, explicit-input/scope collision rejection, and the distinction between SQL local variables and durable `jaz.assign` variables.

---

## §5 Protocol, rendering, and SQL dialect

### §5.1 Raw response contract

Freezes the full LLM response as stored program source, with no markdown-fence extraction, prose repair, or code rewriting before splitting.

### §5.2 Statement splitter

Freezes a lexical scanner that handles:

- single-quoted strings and doubled quotes;
- `E'...'` escape strings;
- double-quoted identifiers;
- line comments;
- nested block comments;
- tagged and untagged dollar quotes;
- parentheses and semicolon boundaries;
- empty statements;
- source offsets and exact retained text.

Semicolons inside `DO $$...$$` bodies MUST NOT split the outer response.

### §5.3 Dialect classifier

Freezes top-level command classification sufficient to identify `SELECT`, `WITH`, `DO`, DML, permitted scratch DDL, transaction control, `CALL`, `COPY`, `CREATE FUNCTION`, and other rejected commands.

### §5.4 Allowed and forbidden statement classes

Freezes the model SQL allowlist and denylist, including scratch-only DDL, rejection of transaction control, `CREATE EXTENSION`, role/database/system commands, persistent function creation, `COPY PROGRAM`, `CALL`, `LISTEN`, `NOTIFY`, and unapproved procedural languages.

### §5.5 Action-statement grammar

Freezes the rule that action statements are top-level read statements containing at most one mutating `jaz` action; `jaz.var` may appear in expressions; `jaz.bind_invoke` and `jaz.tool` are not legal inside `DO`.

### §5.6 `DO` block behavior

Freezes `DO` as one atomic statement with cell-local PL/pgSQL variables, statement rollback on error, no continuation suspension, and no guarantee that a deferred `jaz.return` or `jaz.raise` stops execution inside the block immediately.

### §5.7 SQL results and observations

Freezes that ordinary result sets are not automatically shown to the model; model-visible output must be assigned through `jaz.assign` or emitted through `jaz.print`.

### §5.8 Prompt rendering

Freezes system/user prompt sections for SQL mechanics, named inputs, scoped values, tool catalog, `jaz.history`, `jaz.bind_invoke`, terminal actions, statement lists, and continuation behavior.

### §5.9 Observation rendering

Freezes structured output/error rendering, truncation, statement counts, child/tool error presentation, and the rule that the full source/output remains in authoritative records even when the prompt observation is abbreviated.

---

## §6 Inputs, dynamic scope, and value representation

### §6.1 Explicit input representation

Freezes root and child input payloads as JSONB objects keyed by valid names.

### §6.2 Scope representation

Freezes dynamic scope as immutable durable layers inherited by descendants through layer IDs, with inner layers shadowing outer layers and explicit inputs remaining non-propagating.

### §6.3 Input/scope conflict

Freezes `V15_INPUT_SCOPE_CONFLICT` when a name appears in both resolved scope and explicit inputs.

### §6.4 Value kinds

Freezes JSON scalar/container values plus explicit catalog handles for tools and future relation references; arbitrary object references are out of scope.

### §6.5 Prompt versus binding representation

Freezes full JSONB storage and binding while allowing prompt rendering to abbreviate or hide values through metadata fields.

---

## §7 Configuration resolution

### §7.1 Component model

Freezes `Config(llm, repl, protocol)` as three whole JSON component records; setting one component replaces the entire component rather than recursively merging fields.

### §7.2 Layer types

Freezes base, exact-depth, propagating, and local layer records.

### §7.3 Resolution order

Freezes:

```text
base
⊕ exact-depth base layer
⊕ propagating layers in declaration order
⊕ local override
```

with later values winning.

### §7.4 Root snapshot

Freezes base version, layer IDs, absolute depth, resolved JSON, and digest at invoke creation.

### §7.5 Child inheritance

Freezes child inheritance of the parent’s base version and propagating layers while excluding the parent’s local override.

### §7.6 Configuration mutability

Freezes that a configuration change affects only later invoke roots; an already-open invoke and its descendants use their pinned versions.

---

## §8 Hook events, effects, and blackboard

### §8.1 Event taxonomy

Freezes Invoke, LLMQuery, REPLExec, and LLMQueryRetry events and their fields.

### §8.2 Span lifecycle

Freezes `Enter → Send → Complete → Exit`, conditional child events, outcome variants `Completed`, `Aborted`, and `Failed`, and cross-transaction open spans.

### §8.3 Hook registry

Freezes table-registered SQL handlers using exact `regprocedure` identity, version/digest, activation ordinal, scope, configuration JSONB, and durable state JSONB.

### §8.4 Handler contract

Freezes the conceptual handler shape:

```text
(event_snapshot jsonb,
 hook_config jsonb,
 prior_state jsonb,
 blackboard_snapshot jsonb)
→ {effects jsonb[], next_state jsonb}
```

Handlers MUST return decisions and MUST NOT directly mutate kernel state.

### §8.5 Closed effect taxonomy

Freezes the effect variants:

```text
Abort
AddInputs
DropInputs
AddVariables
DropVariables
InsertCode
DeleteCode
AddMessages
DropMessages
SupplyLLMResponse
ModifyLLMResponse
SupplyExecResult
ModifyExecResult
SupplyInvokeResult
ModifyInvokeResult
DisableRecursion
BlackboardWrite
```

### §8.6 Event/effect allowlist

Freezes which effect kinds are valid at each event and requires `V15_INVALID_EFFECT` for out-of-stage effects.

### §8.7 Effect composition

Freezes:

- identity-first then guarded equality;
- union for drops;
- conflict on divergent same-key adds;
- deterministic code/message edit resolution against the original snapshot;
- supply/modify result kind precedence;
- grouped raises;
- abort precedence;
- no effects at InvokeExit except blackboard writes;
- deterministic activation-ordinal ordering for grouped errors.

### §8.8 Generational blackboard

Freezes generation N as the read snapshot for every handler at one event, generation N+1 after the full write batch, identical same-key writes coalescing, and divergent writes raising `V15_BLACKBOARD_CONFLICT`.

### §8.9 Hook failure policy

Freezes required-hook failure as fail-closed and optional-hook ordinary exceptions as isolated-and-recorded, while malformed effects and composition conflicts remain fatal policy errors.

### §8.10 Privilege-separated dispatcher

Freezes `v15_on_phase` as a `SECURITY INVOKER` dispatcher executed under `v15_hook_runner`, returning decisions without kernel writes; the worker applies validated decisions using owner-controlled transition functions.

### §8.11 `regprocedure` validation

Freezes registration-time and dispatch-time verification of function existence, exact signature, owner, volatility, security-definer status, language, search path, execute privileges, and digest.

---

## §9 Built-in hooks and limits

### §9.1 `IterationLimit`

Freezes enforcement at `LLMQueryEnter`, zero-based iteration semantics, hard abort threshold, and warning messages.

### §9.2 `RecursionLimit`

Freezes enforcement at `InvokeEnter`, recursion affordance removal through `DisableRecursion`, absolute depth checking, and over-cap backstop.

### §9.3 `BudgetPool`

Freezes shared pool identity, row-lock admission, request-level accounting, idempotent settlement, unknown-cost treatment, call limits, cost limits, and warning messages.

### §9.4 `BudgetForcing`

Freezes terminal-result transformation at `REPLExecComplete`, refusal count, continuation message, and durable refusal state.

### §9.5 `ContextWindowWarning`

Freezes token metric storage, warning threshold, next-query injection, and recursion-aware delegation guidance.

### §9.6 Mandatory versus optional built-ins

Freezes finite iteration/recursion ceilings and tool authorization as mandatory governance, while cost budgets, budget forcing, and context warnings remain policy-selectable.

---

## §10 Governance, ACLs, and database security

### §10.1 Roles

Freezes:

- `v15_owner`: `NOLOGIN`, owns schemas, tables, triggers, and security-definer kernel functions.
- `v15_worker`: external worker login with only approved transition-function execution privileges.
- `v15_repl`: `NOLOGIN` model-execution role with model API execution and per-invoke scratch privileges only.
- `v15_hook_runner`: `NOLOGIN` invoker role with read-only snapshot access and handler execution privileges.
- `v15_hook_owner`: `NOLOGIN` owner role for registered handlers.
- test/setup roles: isolated operator privileges only in stage databases.

### §10.2 Model role privileges

Freezes that `v15_repl` has no direct table privileges on `v15`, no create privilege on `jaz`, no temporary-table privilege, no untrusted language privilege, no role membership, and no access to another invoke’s scratch schema.

### §10.3 Security-definer function rules

Freezes fixed `search_path`, explicit qualification, no writable schemas in the search path, context verification by backend identity, and no model-controlled security-definer parameters.

### §10.4 Scratch-schema event triggers

Freezes DDL enforcement through database event triggers and ACLs covering `ddl_command_end`, `sql_drop`, and relevant DDL paths; only the current invoke scratch schema may be modified by `v15_repl`.

### §10.5 Governance manifest

Freezes manifest version, digest, required hook definitions, finite iteration/recursion caps, required tool authorization policy, and root invoke pinning.

### §10.6 Governance bypass prevention

Freezes that model SQL cannot disable baseline hooks, delete manifest rows, alter registry definitions, change role privileges, modify kernel tables, or replace required handler procedures.

### §10.7 Handler ownership restrictions

Freezes `NOLOGIN` ownership, `SECURITY INVOKER`, SQL/PLpgSQL-only language policy, `STABLE`/`IMMUTABLE` volatility, pinned `search_path`, no kernel table grants, and explicit execution grants only to `v15_hook_runner`.

### §10.8 Tool authorization

Freezes root/scope/invoke grants, tool digest pinning, unauthorized-call failure, and no arbitrary function invocation from model SQL.

---

## §11 Fail-closed error-code table

The document should freeze this initial mapping:

| Symbolic code | SQLSTATE | Condition |
|---|---:|---|
| `V15_GOVERNANCE_MISSING` | `P1501` | Required manifest or baseline handler missing/stale |
| `V15_GOVERNANCE_FAILED` | `P1502` | Required governance handler failed |
| `V15_INVALID_EFFECT` | `P1503` | Effect invalid at current event |
| `V15_EFFECT_CONFLICT` | `P1504` | Effects cannot compose deterministically |
| `V15_BLACKBOARD_CONFLICT` | `P1505` | Same-generation blackboard writes disagree |
| `V15_INPUT_SCOPE_CONFLICT` | `P1506` | Explicit input conflicts with resolved scope |
| `V15_CONFIG_INVALID` | `P1507` | Invalid component, layer, depth, or override |
| `V15_STALE_FENCE` | `P1508` | Stale worker/attempt/delivery settlement |
| `V15_INVALID_TRANSITION` | `P1509` | State transition precondition failed |
| `V15_EXEC_PROTOCOL` | `P1510` | Invalid statement list, action, or suspension use |
| `V15_TOOL_UNAUTHORIZED` | `P1511` | Tool grant is absent or stale |
| `V15_BUDGET_UNREPORTABLE` | `P1512` | Required cost metric is unavailable |
| `V15_STATEMENT_REPLAY` | `P1513` | Completed statement would execute again |
| `V15_IO_UNKNOWN` | `P1514` | External attempt outcome cannot be known |
| `V15_SCRATCH_DDL` | `P1515` | Model DDL targets a forbidden object |
| `V15_REPL_CONTEXT` | `P1516` | Model API lacks a valid execution context |
| `V15_HANDLER_REGISTRATION` | `P1517` | Handler fails ownership/signature/privilege checks |
| `V15_HANDLER_FAILED` | `P1518` | Optional handler execution failed |
| `V15_DIALECT_UNSUPPORTED` | `P1519` | Statement command or language is not permitted |
| `V15_STATEMENT_TIMEOUT` | `P1520` | Model statement exceeded its limit |
| `V15_DELIVERY_CONFLICT` | `P1521` | Child/tool delivery conflicts with existing binding |
| `V15_VALUE_INVALID` | `P1522` | Value is not valid JSONB/catalog data |
| `V15_ITERATION_LIMIT` | `P1523` | Mandatory or configured iteration limit reached |
| `V15_RECURSION_LIMIT` | `P1524` | Mandatory or configured recursion limit reached |
| `V15_CHILD_RAISE` | `P1525` | Recoverable child raised a structured error |
| `V15_IO_FAILURE` | `P1526` | External request settled with known failure |
| `V15_CONTEXT_LEAK` | `P1527` | Execution context cleanup or ownership invariant failed |
| `V15_MANIFEST_DIGEST` | `P1528` | Pinned governance digest differs from current manifest |

The final document should also freeze which errors are recoverable model observations, which close a span as `Failed`, and which are fail-closed machinery failures.

---

## §12 Intentional deviation ledger seed

### `V15-D01` — continuation is between statements, not a Python call stack

The parent does not block a SQL stack frame; it stores a program cursor and resumes at the next statement after child delivery, preserving no-extra-parent-call economics but making the continuation boundary observable.

### `V15-D02` — SQL values replace arbitrary Python objects

Core values are JSONB or catalog handles; arbitrary object identity, Python callables, and live shared references are unavailable.

### `V15-D03` — `jaz.var` replaces bare Python variable binding

All model-visible invocation values are addressable through `jaz.var`, `jaz.variables`, or the relevant catalog view rather than bare names.

### `V15-D04` — `jaz.history` replaces `__history__`

History is a read-only SQL relation, not a mutable Python list; the prompt explicitly names `jaz.history`.

### `V15-D05` — statement-list atomicity differs from Python REPL mutation

A failing statement rolls back its own assignments, prints, and scratch changes, while prior statements remain committed.

### `V15-D06` — child errors cannot resume a Python exception handler across statements

A recoverable child/tool error is delivered as structured durable error state and observation; a Python-style `try/except` stack cannot remain suspended across the child wait.

### `V15-D07` — scope is durable layer state

Dynamic scope is represented by immutable scope-layer snapshots rather than `ContextVar` propagation and shared Python object references.

### `V15-D08` — configuration is pinned at invoke open

A later base-config change cannot alter an already-open durable invoke tree.

### `V15-D09` — hook instances become registered pure decision handlers

SQL handlers return effects and next state; Python setup/teardown, live object identity, and direct mutable hook fields do not exist.

### `V15-D10` — mandatory governance is stronger than stock JAZ

Finite iteration and recursion limits are required by the database governance manifest and cannot be disabled by ordinary callers.

### `V15-D11` — unknown external outcomes may produce a new request attempt

An expired attempt is preserved as `unknown`; retry, when allowed, uses a new attempt identity and may duplicate an external provider call.

### `V15-D12` — `DO` blocks are atomic cells

A `DO` block may contain local PL/pgSQL state but cannot suspend for a child or external tool.

### `V15-D13` — SQL result sets are not automatic observations

The model must explicitly use `jaz.print` or `jaz.assign` to make values part of the agent-visible interaction state.

### `V15-D14` — one blocking child/tool action per statement

Fanout and multiple simultaneous continuations are deferred beyond the v15 core.

---

## §13 Stage and gate plan

### Stage 1 — schema

- **Directory:** `v15/schema/`
- **SQL:** `v15/schema/v15_core.sql`
- **Setup:** `v15/schema/setup_db.py`
- **Gate:** `v15/schema/test_schema.py`
- **Proves:** roles, schemas, enums, core tables, append-only protections, state transitions, stable SQLSTATEs, fences, scratch metadata, and the no-op `v15_on_phase` stub.

### Stage 2 — values/namespace

- **Directory:** `v15/values/`
- **SQL:** `v15/values/v15_values.sql`
- **Setup:** `v15/values/setup_db.py`
- **Gate:** `v15/values/test_values.py`
- **Proves:** explicit inputs, scope snapshots, variable persistence, `jaz.var`, `jaz.assign`, context binding, security-barrier views, `jaz.history` shape, and cross-invoke isolation.

### Stage 3 — config

- **Directory:** `v15/config/`
- **SQL:** `v15/config/v15_config.sql`
- **Setup:** `v15/config/setup_db.py`
- **Gate:** `v15/config/test_config.py`
- **Proves:** component validation, whole-component replacement, exact-depth resolution, propagating/local precedence, child inheritance, snapshot digests, and caller-tightening-only governance limits.

### Stage 4 — protocol

- **Directory:** `v15/protocol/`
- **SQL:** `v15/protocol/v15_protocol.sql`
- **Worker helper:** `v15/protocol/split_sql.py`
- **Setup:** `v15/protocol/setup_db.py`
- **Gate:** `v15/protocol/test_protocol.py`
- **Proves:** identity response preservation, dollar-quote-safe splitting, nested comment handling, command classification, DO-block semicolon handling, rejected transaction-control syntax, prompt rendering, and `jaz.history` wording.

### Stage 5 — repl/loop-exec

- **Directory:** `v15/repl/`
- **SQL:** `v15/repl/v15_repl.sql`
- **Setup:** `v15/repl/setup_db.py`
- **Gate:** `v15/repl/test_repl.py`
- **Proves:** `v15_repl` ACLs, backend-pid execution context, scratch-schema creation, event-trigger DDL gates, one-statement transaction boundaries, `jaz.print`, `jaz.assign`, `jaz.return`, `jaz.raise`, `jaz.bind_invoke`/`jaz.tool` rejection inside DO, statement rollback, statement timeout, and statement-not-rerun behavior.

### Stage 6 — io

- **Directory:** `v15/io/`
- **SQL:** `v15/io/v15_io.sql`
- **Setup:** `v15/io/setup_db.py`
- **Gate:** `v15/io/test_io.py`
- **Proves:** request/attempt identity, claim lease, independent fence, out-of-transaction FakeLLM/FakeTool execution, known failure, unknown expiry, new-attempt retry, stale settlement rejection, duplicate settlement idempotency, and wake-hint recovery.

### Stage 7 — loop

- **Directory:** `v15/loop/`
- **SQL:** `v15/loop/v15_loop.sql`
- **Setup:** `v15/loop/setup_db.py`
- **Gate:** `v15/loop/test_loop.py`
- **Proves:** one invoke from open through FakeLLM response, protocol split, multi-statement execution, per-statement commits, observation/history generation, Invoke/LLMQuery/REPLExec spans, terminal return/raise, and invocation of the no-op `v15_on_phase` stub.

### Stage 8 — tree

- **Directory:** `v15/tree/`
- **SQL:** `v15/tree/v15_tree.sql`
- **Setup:** `v15/tree/setup_db.py`
- **Gate:** `v15/tree/test_tree.py`
- **Proves:** parent cursor suspension, child creation, child scope/config inheritance, direct next-statement result binding, no extra parent LLM call, child error handling, fatal propagation, duplicate/dropped delivery recovery, and one-wait-per-statement enforcement.

### Stage 9 — hooks+govern

- **Directory:** `v15/hooks_govern/`
- **SQL:** `v15/hooks_govern/v15_hooks_govern.sql`
- **Setup:** `v15/hooks_govern/setup_db.py`
- **Gate:** `v15/hooks_govern/test_hooks_govern.py`
- **Proves:** handler registration hardening, `v15_hook_runner` privilege separation, event/effect composition, blackboard generations, baseline manifest pinning, mandatory finite limits, five built-in hooks, tool authorization, final `v15_on_phase` replacement, and an end-to-end nested FakeLLM/FakeTool run.

### Loader contract

Freezes `v15/load.py` with the nine SQL files in exactly the stage order above, plain `CREATE` statements, `files_through(stage)`, `STAGE_THROUGH`, `run_psql`, and `load_stage` behavior copied conceptually from v8/v13 without importing their schemas.

---

## §14 PostgreSQL 18.4 implementation hazards and required probes

### §14.1 Dollar-quoted splitting

The splitter must handle `DO $$ BEGIN ...; ...; END $$;`, tagged dollar quotes, semicolons in nested strings, escaped strings, and nested block comments; a naive `source.split(";")` implementation is prohibited.

### §14.2 `jaz.return` and `jaz.raise` parser behavior

The implementation must verify on PostgreSQL 18.4 that `jaz.return(...)` and `jaz.raise(...)` are valid schema-qualified function calls; if the DDL parser treats either spelling specially, only the function declaration/call quoting may change, not the frozen public names.

### §14.3 Transaction-control detection

The statement classifier must reject explicit `BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT`, `RELEASE`, prepared transactions, and transaction-control procedures before execution; PostgreSQL’s own implicit transaction behavior is not sufficient as the only defense.

### §14.4 `DO` and continuation detection

The implementation must not attempt to infer a suspension point from the PL/pgSQL call stack; `jaz.bind_invoke` and `jaz.tool` must be rejected when the execution context identifies the enclosing statement as `DO`.

### §14.5 Event-trigger coverage

Event triggers must be tested for:

- `CREATE TABLE`;
- `CREATE TABLE AS`;
- `SELECT INTO`;
- `ALTER TABLE`;
- `DROP TABLE`;
- `TRUNCATE`;
- `CREATE VIEW`;
- attempted `CREATE FUNCTION`;
- DDL inside `DO`;
- `sql_drop` cleanup;
- denied `CREATE TEMP`;
- attempts to target `jaz`, `v15`, or another invoke’s scratch schema.

Event triggers are defense-in-depth, not the sole ACL boundary; ownership and role privileges must reject forbidden operations even if a command is outside event-trigger coverage.

### §14.6 Security-barrier view leaks

`jaz.history`, `jaz.variables`, and `jaz.tools` must be `security_barrier` views over owner-controlled relations, with no direct `v15` table grants to `v15_repl`. The current-invoke predicate must derive from backend-bound execution context, not a user-settable GUC. Tests must attempt cross-invoke predicates, lateral access, function-based predicates, and schema shadowing.

### §14.7 Security-definer search paths

Every `SECURITY DEFINER` kernel function must set a fixed search path containing only trusted schemas and must not include `public`, a scratch schema, or uncontrolled `pg_temp`. All table and function references in security-definer code must be schema-qualified.

### §14.8 `regprocedure` late binding

A `regprocedure` stores function identity, not merely a stable textual name. The implementation must test:

- overloaded handler names;
- dropped handler functions;
- `CREATE OR REPLACE FUNCTION` with unchanged OID but changed body;
- changed argument types;
- changed owner;
- revoked execute privilege;
- altered volatility/security-definer flags.

Dispatch must reject digest or metadata drift before executing the handler.

### §14.9 Handler privilege context

A test handler must report `current_user`, `session_user`, `current_setting('search_path')`, and accessible relations. The gate must prove handlers execute as `v15_hook_runner`, not `v15_owner`, and cannot mutate kernel tables even when the worker owns the surrounding state transition.

### §14.10 Backend-pid context lifecycle

The gate must prove that context rows are cleared on normal completion, statement error, timeout, worker crash recovery, and connection reuse; a recycled backend PID must not inherit another invoke’s context.

### §14.11 JSONB equality and values

Effect conflict and blackboard coalescing must use PostgreSQL JSONB equality semantics, with explicit rejection of unsupported numeric/non-JSON values and deterministic treatment of object key order.

### §14.12 Implicit result and output behavior

The gate must prove that a bare `SELECT` result is not silently treated as model-visible output and that only `jaz.print`, `jaz.assign`, history, and structured observations form the agent-visible state.

### §14.13 FakeLLM unknown retry determinism

The I/O gate must simulate a provider call that occurs before the worker crashes, mark the first attempt unknown, create a new attempt, and verify deterministic FakeLLM behavior without pretending that an external provider call was exactly once.

# File-by-file impact

## Files changed by this Round-2 design deliverable

### `docs/designs/v15-jaz-dev.md`

- **Change:** Add the frozen v15 design according to the complete skeleton above.
- **Why:** This file becomes the authority for the statement-list continuation model, SQL naming surface, schema contracts, transitions, hooks, governance, errors, deviations, and gates.
- **Ordering:** Must land before any v15 SQL or worker implementation.

## Files planned for subsequent implementation

### `v15/load.py`

- Define the nine-entry `SQL_LOAD_ORDER`.
- Define `STAGE_THROUGH`, `files_through`, `run_psql`, and `load_stage`.
- Must be added before the first stage gate.

### `v15/schema/v15_core.sql`

- Define schemas, roles, enums, core tables, append-only triggers, state transitions, stable errors, and the no-op `v15_on_phase`.
- Must land before all later SQL.

### `v15/values/v15_values.sql`

- Define variables, scope snapshots, execution contexts, history/namespace views, and model API read/write functions.
- Depends on schema IDs, roles, and error helpers.

### `v15/config/v15_config.sql`

- Define config layers, validation, resolution, snapshots, and digests.
- Depends on invokes and value identity.

### `v15/protocol/v15_protocol.sql`

- Define protocol metadata, prompt/render functions, source records, and protocol limits.
- `v15/protocol/split_sql.py` implements worker-side lexical splitting and classification.
- Depends on values and config.

### `v15/repl/v15_repl.sql`

- Define scratch-schema lifecycle, model execution privileges, DDL event triggers, statement execution transitions, action staging, and finish semantics.
- Depends on protocol, variables, config, and the stage-1 phase stub.

### `v15/io/v15_io.sql`

- Define logical requests, attempts, claims, leases, fences, unknown state, and settlement functions.
- Depends on invokes, spans, and errors.

### `v15/loop/v15_loop.sql`

- Define the non-recursive loop and phase calls against the no-op hook stub.
- Depends on protocol, REPL, I/O, and spans.

### `v15/tree/v15_tree.sql`

- Define parent waits, child creation, delivery, continuation cursor advancement, and fatal propagation.
- Depends on loop, variables, config, scope, and I/O.

### `v15/hooks_govern/v15_hooks_govern.sql`

- Define hook registry, handler validation, effects, blackboard, dispatcher replacement, manifest, built-ins, and governance ACLs.
- Must be loaded after the loop/tree stages so it can replace the phase stub without changing its signature.

### Stage `setup_db.py` and `test_*.py` files

- Each stage receives its own isolated database setup and standalone gate.
- Every gate must cumulatively load all SQL through its declared stage.
- Tests must define FakeLLM/FakeTool locally or in test-only helpers; no production provider adapters are added.

### `docs/reviews/v15-conformance-matrix-*.md`

- Add one row per frozen invariant and gate assertion after each milestone.

### `docs/reviews/v15-deviation-ledger-*.md`

- Add the deviation entries from §12 and any later implementation-discovered deviation before the corresponding milestone is committed.

No v8/v13 file is part of the v15 implementation change.

# Implementation order

1. Freeze `docs/designs/v15-jaz-dev.md`, including all table fields, function signatures, state predicates, SQLSTATE assignments, role grants, and deviation entries.
2. Run PostgreSQL 18.4 probes for `jaz.return`, `jaz.raise`, event-trigger coverage, security-barrier filtering, `regprocedure` dispatch, and `SET LOCAL ROLE` handler execution.
3. Add `v15/load.py` and stage 1 schema artifacts; run `v15/schema/test_schema.py`.
4. Add stage 2 values/namespace artifacts; run both stage 1 and stage 2 gates.
5. Add stage 3 config artifacts; verify exact precedence and snapshot behavior.
6. Add the protocol splitter and rendering artifacts; make the dollar-quote and command-classification gate pass before implementing the executor.
7. Add stage 5 REPL/scratch execution; land the dynamic executor, context isolation, DDL event-trigger, and statement-not-rerun behavior atomically.
8. Add stage 6 I/O requests/attempts and FakeLLM/FakeTool tests; prove unknown-attempt/new-attempt behavior before adding the loop.
9. Add stage 7 loop against the no-op `v15_on_phase` stub; prove one invoke end-to-end without hooks.
10. Add stage 8 parent/child continuation and delivery; prove child consumption from the next stored statement without a parent LLM call.
11. Add stage 9 hooks/governance; replace `v15_on_phase`, add the privilege-separated dispatcher, compose effects, enforce the manifest, and run the end-to-end governance gate.
12. After each stage, run every cumulative gate, update the conformance matrix and deviation ledger, update the stage README, then follow `AGENTS.md`’s required test → artifact update → explicit staging → commit → push order.