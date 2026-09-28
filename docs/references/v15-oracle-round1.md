## Ask Oracle ✅
- Oracle group status: completed
- Oracle group: `54BBD0FD-1DC4-44CE-9500-E4BF8C6B0E8B`

### Oracle
- Status: Completed
- Provider: `grokBuild`
- Model: `grok-4.7-build-fast-xhigh`
- Effective effort: Provider default / not specified
- Chat: `new-chat-3A582E`



# v15 round 1 — architecture decisions

v15 is a Postgres-native invoke state machine: the model writes a restricted SQL statement list, a Python gate/worker performs only LLM I/O and statement splitting between transactions, and every authoritative transition is SQL. This preserves the paper’s two properties (recursive invoke, and everything the model sees is programmatically addressable) and v8 invariant 4 (no LLM I/O inside a transaction). It deliberately does not embed the jaz CPython REPL, and it does not reuse the v8 `sessions` / `effect_requests` schema.

---

## D1. REPL language

**Recommendation:** (a) an invoke-augmented **SQL statement-list** dialect, executed by a worker one statement per short transaction, as role `v15_repl`. `jaz.bind_invoke` / `jaz.return` / `jaz.raise` are **sole-statement suspension or termination forms** the worker classifies and rewrites; they are never ordinary expressions inside a `DO` block or a multi-call `SELECT`.

**Justification:** The paper’s formalism augments any Turing-complete language; pg-agent’s authoritative state is already SQL, and FakeLLM gates can drive `v15_*` functions the same way v8 gates drive SQL. plpython3u runs untrusted model code inside the backend and cannot suspend a `DO` block for an LLM call without holding a transaction open, which breaks invariant 4. An external Python subprocess REPL would re-host jaz and reduce Postgres to a queue, so property 2 would be true only in CPython, not in the database the spec is about. Same-iteration use of a child result — the imperative loop in the paper’s Figure 1 — still holds at **statement** granularity: the worker evaluates the inputs expression, commits a suspend row, runs the child to completion, binds the jsonb result, then runs the next statement. Expression-level `invoke()` and plpgsql `FOR` loops that call invoke cannot be suspended mid-body, because Postgres has no continuations and a raising function would roll back the statement that inserted the suspend.

**Canonical forms** (anything else that mentions these names fails with `V15_INVOKE_FORM`):

- `SELECT jaz.bind_invoke('<ident>', <jsonb-expr>);`
- `SELECT jaz.return(<jsonb-expr>);`
- `SELECT jaz.raise(<text-expr>);`
- `SELECT jaz.print(<text-expr>);`
- `SELECT jaz.assign('<ident>', <jsonb-expr>);`
- `SELECT jaz.tool('<ident>', <jsonb-expr>);`

Plain `SELECT` / `INSERT` / `UPDATE` / `DELETE` / `CREATE TABLE` are allowed only in that invoke’s scratch schema and must not mention the three control names. `DO`, `CALL`, `EXECUTE`, `CREATE FUNCTION|PROCEDURE`, `COPY`, explicit `BEGIN|COMMIT|ROLLBACK`, and dynamic SQL are `V15_DIALECT`. The authoritative splitter lives in the worker (`v15/protocol/split_sql.py`), dollar-quote and string aware; the database stores already-split statement rows. `statement_timeout` comes from resolved repl config; a leading `-- timeout: <seconds>` pragma overrides it for that iteration (positive finite only).

**Key risks:** Current models are worse at this dialect than at Python; that is acceptable because eval parity is out of scope. A naive `;` split will mis-parse dollar quotes — the protocol gate must own those cases. A missed classifier could execute `bind_invoke` inside a larger statement; the function itself, if ever called under `v15_repl`, raises `V15_INVOKE_FORM` rather than spawning. Scratch-schema DDL is contained by an event trigger plus grants, and that containment is a schema-stage gate, not a convention.

---

## D2. Execution topology

**Recommendation:** A persisted invoke tree driven by claim/lease, not a blocking SQL call. One worker (the test script) is a dumb loop over SQL transitions. Parent “blocking” on `invoke` means **status `suspended` until the child settles, then resume at the next statement of the same iteration**. Do not share v8’s effect/step/plugin tables; copy only the invariants (append-only log, fence, scan-not-NOTIFY, I/O outside the transaction).

**Core tables:**

- `invokes` — `invoke_id`, `parent_invoke_id`, `parent_iteration` (0-based, null at root), `root_invoke_id`, `depth` (root = 1), `status` (`pending|runnable|leased|suspended|completed|failed|aborted`), `return_value jsonb`, `error jsonb`, `fatal bool`, `recursion_available bool`, `resolved_config jsonb`, `config_scope_id`, `pool_id`, `fence`, `lease_owner`, `lease_until`.
- `iterations` — `(invoke_id, iteration)` 0-based; `status` (`pending|llm|executing|suspended|done`); `resume_stmt int`; `result_kind` (`continue|return|raise`).
- `statements` — `(invoke_id, iteration, stmt_index, sql, kind, status, bind_name, child_invoke_id)`.
- `llm_attempts` — `(attempt_id, invoke_id, iteration, fence, status pending|leased|settled|failed, request jsonb, response jsonb)`.
- `llm_messages` — persistent transcript, append-only per invoke (`seq`, `role`, `content`, `kind`).
- `invoke_events` — append-only audit `(invoke_id, seq)` with a per-invoke unique `seq`. Not the agent-visible history.

**Transition contract** (each is one transaction; FakeLLM is called by the test between them):

1. `v15_open_invoke(...)` inserts depth, copies scope bindings and propagating hooks, resolves and **freezes** config, writes the system+user seed, sets `runnable`.
2. `v15_claim(invoke_id, owner, ttl) → fence` only from `runnable` when the lease is free or expired. Stale fence on any later settle → `V15_STALE_FENCE`.
3. `v15_begin_llm` runs phase `llm_query/enter` then `send`. `abort` finishes the invoke with no attempt. `supply` skips the provider (replay, later). Otherwise insert `llm_attempts` leased and commit.
4. Worker calls FakeLLM **after commit**.
5. `v15_settle_llm(fence, response)` runs `complete` then `exit`, appends the assistant message, parses via the already-split statement list. Provider failure with attempts left records `failed` and returns to `runnable` without a REPL span.
6. `v15_begin_exec` runs `repl_exec/enter` then `send` (committed code). `supply` skips execution.
7. For each statement, worker either runs it as `v15_repl` or, for `bind_invoke`, evaluates `<jsonb-expr>` in a read-only txn and calls `v15_suspend_for_child`.
8. `v15_suspend_for_child` in **one** transaction: insert child `pending/runnable`, set parent statement waiting, iteration `suspended`, invoke `suspended`, clear the parent lease.
9. Child completion transaction: write `return_value` or error; bind parent `bind_name`; set statement done and parent `runnable` at `resume_stmt+1`. A child **raise** does not resume later statements; it becomes this iteration’s recoverable `Continue` observation (`V15_CHILD_ERROR`). `capture => true` is not in v15.
10. After the last statement, `v15_finish_exec` runs `complete`/`exit`. `return`/`raise` completes the invoke span (`invoke/complete`, `invoke/exit`) and stores the terminal result. `continue` appends the abbreviated observation and increments `iteration`.
11. `v15_run_until_quiescent` in the test claims any `runnable` row (child before suspended parent naturally, because the parent is not claimable).

**Crash rule:** a `leased` LLM attempt past `lease_until` is reclaimable. FakeLLM is deterministic, so retry re-calls and settles once. A statement lease works the same way: re-exec is allowed only when the statement status is still `pending` (no silent double `INSERT` into scratch). Scratch DML is not exactly-once across a crash mid-statement; the gate must show a **committed** statement is not re-run, and an **uncommitted** one is.

**Key risks:** Depth-70 trees are rows, not pinned connections or temp schemas that die on disconnect — bindings are ordinary tables (D4), scratch schemas are dropped at invoke end and survive suspend. Two workers settling one fence must fail closed; every gate that writes a settle path includes a stale-fence case. Fatal abort (`fatal=true`, budget, recursion over-cap) marks ancestors `aborted` in the same transaction so a parent cannot treat it as a recoverable `Continue`.

---

## D3. Hook system in SQL

**Recommendation:** A closed effect enum and a SQL dispatcher. Handlers are admin-owned `regprocedure` rows in `hook_defs`, not model-created functions. `v15_on_phase` is the only extension point the loop calls; schema installs an identity stub and the hooks stage `CREATE OR REPLACE`s it (plpgsql late-binds, so the loop file does not change). Baseline rows are installed only by `v15_open_invoke` and are immutable to `v15_repl` and to ordinary worker updates.

**Dispatch order:** `baseline`, then `propagating` (ancestor stack, outer→inner), then `local` (this invoke’s positional list). Propagating bindings are copied onto the child at open; local bindings are not. There is no `clear_hooks` and no per-class disable.

**Phases** (same lattice as jaz): for spans `invoke`, `llm_query`, `repl_exec` — `enter`, `send`, `complete`, `exit`. `exit` is observation-only except `llm_query` and `repl_exec`, which may still `abort`. `invoke/exit` accepts no control effect (`V15_INVALID_EFFECT`).

**Effect enum (v15 core):** `abort`, `add_messages`, `drop_messages`, `disable_recursion`, `add_inputs`, `drop_inputs`, `modify_exec_result`, `blackboard_write`. `supply_llm_response` and `supply_invoke_result` / `modify_invoke_result` stay in the enum so the composer rejects them as unknown-at-this-phase rather than ignoring them, but no core hook emits supply or invoke-modify (ReturnType is later).

**`v15_on_phase(invoke_id, iteration, span, phase, io jsonb) → jsonb` contract the loop already honors in the loop stage:**

- `{"action":"proceed"}` — default stub.
- `action:"abort"` plus `error:{code,message}` and `fatal:bool`. Loop sets invoke `aborted` or `failed` and does not start I/O.
- `messages` — replacement shown-list for this query only unless an add/drop is marked `persistent:true`.
- `exec_result` — replaces the raw REPL result before history append (`modify_exec_result`). A downgrade to `continue` keeps the invoke alive (BudgetForcing).
- `recursion_available:false` — `disable_recursion`; prompt omits bind_invoke and `v15_suspend_for_child` raises `V15_RECURSION_DISABLED`.
- `bindings_delta` — add/drop inputs applied before the seed prompt is frozen at `invoke/enter`.

**Composition (inside the phase transaction, before return):**

- Same blackboard key, same phase, jsonb values distinct → `V15_BLACKBOARD_CONFLICT`. Equal jsonb coalesces. Object identity is not available for jsonb; that is a ledger deviation.
- Same input name, distinct jsonb → `V15_INPUT_CONFLICT`; equal coalesces.
- Multiple `abort`s become one error with `errors:[...]`. Any `fatal:true` makes the group fatal.
- Effect kind not legal for the phase → `V15_INVALID_EFFECT` (no skip).
- Each handler runs under a `SAVEPOINT`. A handler exception is logged to `invoke_events` and does **not** become an abort. `abort` is the only stop channel.
- Blackboard writes apply after every handler for that phase has returned, then `generation` increments. Readers in the same phase see the pre-write map.

**Blackboard:** `blackboard(invoke_id, key, value jsonb, generation bigint)` per invoke, seeded from `hook_defs.seed jsonb` (own config only) before `invoke/enter`. Not shared with the parent. Budget counters are not blackboard keys.

**Governance backstop:** `v15_begin_llm` / `v15_open_invoke` / `v15_suspend_for_child` check that every `hook_defs.baseline_required` type has a row for this invoke. Missing → `V15_BASELINE_MISSING` and no I/O. The numeric policy lives in one handler, not a second copy in the transition. `v15_repl` has no DML on `invoke_hooks`, `hook_defs`, `budget_pools`, or `invokes`.

**Key risks:** The phase-result contract must be frozen in the loop stage or hooks will grow a side channel. SAVEPOINT-per-handler can mask bugs; the hooks gate must show a raising handler does not suppress a sibling’s `abort`. Admin `regprocedure` extensibility is real for the database owner and unavailable to the model — a Python `class MyHook(Hook)` port is a later host feature, not v15 core.

---

## D4. Inputs, `__history__`, and “everything is a variable”

**Recommendation:** One privileged binding table plus SECURITY DEFINER accessors, a security-barrier history relation, and a per-invoke scratch schema for ordinary SQL tables. No per-invoke binding schema and no contextvars.

**Shapes:**

- `bindings(invoke_id, name, kind, value jsonb, tool_id, show_in_prompt, provenance)` with `kind in (input, scope, var, tool)`. PK `(invoke_id, name)`. Kinds are disjoint; a scope/input name collision at open is `V15_SCOPE_CONFLICT`.
- `repl_history(invoke_id, iteration, llm_response text, repl_output text, repl_exception jsonb)` — one row per finished iteration, including a failed statement (`repl_output` holds the SQL error text; `repl_exception` is `{sqlstate, code, message}` or null). Terminal `return`/`raise` store `repl_output ''`.
- `exec_context(backend_pid, invoke_id)` written by the worker role immediately before model statements. `jaz.var` / history reads use `pg_backend_pid()` only. `v15_repl` cannot write this table.
- Scratch schema `s_<invoke_id>` created at open, `search_path` set to that schema then `v15_api`. Dropped when the invoke reaches a terminal status.

**Addressing API (schema `v15_api`, executed as definer):**

- `jaz.var(name) → jsonb`, `jaz.assign(name, jsonb)`, `jaz.print(text)`, `jaz.tool(name, jsonb) → jsonb`
- `history` view: columns `iteration, llm_response, repl_output, repl_exception`, filtered to the current exec context, `security_barrier = true`
- Prompt text states both “`SELECT * FROM history`” and that `jaz.var('…')` reads inputs, scoped names, assigns, and child binds

**What propagates:** `kind=scope` rows are **jsonb-copied** onto the child at open. `kind=input` does not propagate. Explicit child inputs that overlap scope names fail open. `kind=var` (assigns and bind_invoke results) is local to the iteration’s invoke and does not propagate. Tools bound as `input` or `scope` follow that same rule.

**Prompt:** `v15_render_messages(invoke_id)` is SQL. It builds the seed once: system text (format instructions, history column list, bind_invoke description if `recursion_available`, scoped names) and user text (explicit inputs). Display truncation uses `max_invoke_input_length` and `truncation_prefix_ratio` from frozen protocol config; stored jsonb is complete. Observation truncation uses `max_repl_output_length` on the user message only; `repl_history.repl_output` keeps the full text. No Jinja.

**Tools in core:** `tool_catalog(tool_id, name, arg_schema jsonb, handler regprocedure, description text)`. `jaz.tool` calls the handler in the **statement** transaction. Handlers are pure SQL over data the invoke may read. A handler whose `tool_catalog.external` is true is rejected in v15 (`V15_EXTERNAL_TOOL`); external tools need the same suspend protocol as invoke and are later.

**Key risks:** jsonb copy means a child `jaz.assign` of a scoped name does not mutate the parent; the ledger must say so, or tests will “fix” it into aliasing. `history` must be proven not to leak across `invoke_id` (RLS or barrier view; gate includes a second invoke). Scratch `CREATE TABLE` plus an event trigger is part of the sandbox: the model can compute, and it cannot install a function. Cycles and non-json Python values have no representation; inputs are jsonb at `v15_open_invoke` (the test serializes).

---

## D5. Config stack

**Recommendation:** Profiles and ordered layers, resolved once at `v15_open_invoke` and stored on `invokes.resolved_config`. Component objects are jsonb and **replace as a whole** (`llm`, `repl`, `protocol`). Resolution order matches jaz: **base profile ⊕ global depth partial for this depth ⊕ propagating layers in push order ⊕ this invoke’s local layer**, later wins. A child inherits `config_scope_id` and does not inherit the parent’s local layer.

**Tables:**

- `config_profiles(profile_id, llm jsonb, repl jsonb, protocol jsonb, baseline_hooks jsonb)`
- `config_scopes(scope_id, profile_id)`
- `config_layers(layer_id, scope_id, ordinal, kind plain|depth, llm jsonb, repl jsonb, protocol jsonb, depth_map jsonb)` — null component key means “not present”, distinct from a JSON `null` value; use missing keys only
- Local override is a layer row with `scope_id` null and `invokes.local_layer_id` set, applied last, not copied to children
- `kind=depth` contributes only `depth_map[depth]` and nothing to a depth-less read
- Depth-map entries may not contain `depth_map` (`V15_DEPTH_SELF`)
- A second local layer on one invoke → `V15_CONFIG_LOCAL`

**Baseline hooks:** `baseline_hooks` on the profile is the immutable set. A layer may add propagating hook instances via `config_layers.extra_hooks jsonb` but a layer key `baseline_hooks` is `V15_BASELINE_IMMUTABLE`. Positional hooks on open are `channel=local` and are not a config layer (so a local RecursionLimit can be rejected by govern without a special config case).

**Worker rebase:** there is no `established` flag and no contextvar snapshot. The rows are the stack. `v15_get_config(invoke_id)` reads the frozen document, not a live re-fold, so a later profile update does not change an in-flight invoke. A child opened after that update folds the new base at its own open.

**Key risks:** Tests must show a protocol-only layer leaves `llm` intact, a later `llm` object replaces the earlier one without deep-merge, and a depth-2 partial does not apply at depth 1. Freezing at open drops jaz’s lazy “configure() under an active override updates the base beneath the shadow” behavior; do not reintroduce per-iteration re-fold. Presence-versus-JSON-null is the usual bug; the resolver must use `jsonb_exists`, not `IS NULL` on extracted values.

---

## D6. Budgets and limits

**Recommendation:** Five builtin handlers, all registered in `hook_defs`, enforced only through `v15_on_phase` plus the baseline-presence check. State that must survive across invokes lives in tables keyed by the **origin binding**, not in the blackboard.

| Hook | Channel | Phase | Effect | State |
|---|---|---|---|---|
| `iteration_limit` | propagating or baseline; local allowed | `llm_query/enter` | `abort` `V15_ITERATION_EXCEEDED` when `iteration >= max_iterations` (0-based). Warning `add_messages` transient when `max_iterations - iteration <= warn_remaining` | stateless; reads `iterations` |
| `recursion_limit` | propagating or baseline only; local open → `V15_RECURSION_LOCAL_FORBIDDEN` | `invoke/enter` | depth `> max_depth` → fatal `abort` `V15_RECURSION_EXCEEDED`; depth `= max_depth` → `disable_recursion` | stateless; reads `invokes.depth` |
| `budget_pool` | propagating | `llm_query/enter` and `exit` | enter: if reserved totals would exceed `cost_limit` or `calls_limit`, fatal `abort` `V15_BUDGET_EXHAUSTED`. Warning transient message under `warn_*_remaining`. exit on proceed: settle actual `cost_usd` from the response | `budget_pools` row shared by every invoke that inherited the binding |
| `budget_forcing` | propagating or local | `repl_exec/complete` | first `refusals` terminal `return` results become `modify_exec_result` `continue` with `refusal_text` | `hook_counters(binding_origin_id, invoke_id, n)` |
| `context_window_warning` | propagating or local | `llm_query/enter` | transient `add_messages` when `prompt_tokens / max_input_tokens >= warn_fraction` | last `prompt_tokens` on `llm_attempts`; char/4 proxy if the fake omits usage |

**Budget atomicity:** `v15_begin_llm` reserves one call (and optional cost ceiling) with `UPDATE budget_pools SET calls_reserved = calls_reserved + 1 WHERE pool_id=$1 AND (calls_limit IS NULL OR calls_used + calls_reserved < calls_limit)`. The phase hook performs that update; a lost race is the same `V15_BUDGET_EXHAUSTED` abort. `v15_settle_llm` moves reservation into `calls_used` / `cost_used`. Reclaim of an expired `leased` attempt releases the reservation in the same transaction as the reclaim, then retries. No second numeric implementation in the worker.

**Loop consequences already required before the govern gate:** abort skips I/O; fatal abort walks `parent_invoke_id` and aborts ancestors; `modify_exec_result` to `continue` appends an observation and does not complete the invoke; `disable_recursion` is visible to `v15_suspend_for_child`; transient messages are sent to FakeLLM and are not inserted into `llm_messages`.

**Key risks:** A shared pool plus a future parallel `map_invoke` deadlocks if reservation and invoke-row locks order differently; v15 core is sequential, and the reserve statement must lock `budget_pools` before `invokes`. BudgetForcing’s counter is per invoke (jaz shares one Python instance across the `with` block — **deviation**: v15 counts per invoke so one child cannot burn the parent’s refusals). Context-window “tokens” are whatever FakeLLM writes, else `length/4`; the warning text tells the model to `jaz.bind_invoke` the remaining work and to pass `history` by reading the view, not by inlining it.

---

## D7. Scope of v15

**Recommendation:** Nine stages, core loop only. In scope: the two paper properties, local vs propagating config and hooks, the five governance hooks, pure-SQL tools, FakeLLM, lease reclaim. Out of scope until a later spec: ReturnType / ValidateReturn / ValidateREPLCode, trajectory record/replay, OTel/Langfuse/Jaeger, CodeAct ablation, real provider adapters and the `unknown` side-effect state, `map_invoke` fan-out, external tools, `ainvoke`, Jinja, Display/catalog rendering, token-native stamp-back.

**Cut rationale:** Those later items sit on top of spans, messages, and bindings and do not change the state machine. Shipping them inside v15 would couple the gate plan to provider SDKs and to jaz-evals. ReturnType is the most tempting inclusion because the paper’s figure uses it; it is a `modify_invoke_result` hook at `invoke/complete` and can land as v16 without a schema break if the effect enum value exists now and the composer rejects it at every phase except that one.

---

## Deviation ledger (do not “fix” these back to 1:1)

1. **`invoke` is a sole statement, not an expression.** Same-iteration binding is preserved; mid-expression and mid-`DO` invoke are `V15_INVOKE_FORM`. Reason: no continuations; invariant 4.
2. **Values are jsonb.** Coalesce uses jsonb equality. Tools are catalog ids. No DataFrame, closure, or by-identity `__jaz_get__` wrapper. The host serializes before `v15_open_invoke`.
3. **Scope is a snapshot copy** at child open, not a shared mutable Python object.
4. **No contextvars and no `established` rebase.** Propagation is `config_scope_id`, copied `scope` bindings, and copied propagating hook rows.
5. **Capture is `jaz.print` into `iteration_output`**, concatenated into `repl_output`. It is not a stdout proxy. Uncaught SQL errors are that iteration’s recoverable observation.
6. **No `try/except` around a child.** Child raise aborts the rest of the parent statement list into `V15_CHILD_ERROR`. Fatal child abort aborts the ancestor chain instead.
7. **Handlers are catalogued `regprocedure`s.** The model cannot `CREATE FUNCTION` a hook. Owner-installed handlers are the extension mechanism.
8. **Baseline presence is grant- and trigger-enforced.** Stronger than jaz’s “please don’t clear hooks”.
9. **Config is frozen on the invoke row at open.** Later `configure` affects only invokes opened afterward.
10. **History is a relation** (`history` view / `repl_history`) with the three jaz fields, queried with SQL. The prompt describes columns, not Python attributes.
11. **One leaseholder per invoke; children run only while the parent is `suspended`.** No `ainvoke`, no in-iteration parallel map.
12. **BudgetForcing refusals are per invoke**, not one mutable hook object across the tree.
13. **Real LLM exactly-once / `unknown` is not implemented.** Expired FakeLLM leases retry. The `llm_attempts.status` column leaves room for `unknown` without using it.
14. **`reject_finish_on_printed_output` defaults true.** A statement list that both `jaz.print`s and `jaz.return`s fails the iteration as a recoverable `Continue` (`V15_PRINT_AND_RETURN`) and does not complete the invoke.

---

## Stage / gate plan

Cumulative load in `v15/load.py` (`SQL_LOAD_ORDER`, `STAGE_THROUGH`). Each stage dir: `v15_<stage>.sql`, `setup_db.py` (drop/create database, `load_stage` through itself), `test_<stage>.py` (`uv run python v15/<stage>/test_<stage>.py`, exit 0). Role `v15_repl` exists from stage 1. Tests call SQL transitions and a tiny in-script FakeLLM; they never open a network socket.

| # | Stage | SQL | Gate | Proves |
|---|---|---|---|---|
| 1 | `schema` | `v15/schema/v15_schema.sql` | `test_schema.py` | Tables, enums, fences, append-only `invoke_events` seq, `v15_repl` denied DML on control tables and denied `pg_read_file` / `dblink` if present. Stub `v15_on_phase` returns `{"action":"proceed"}`. Scratch event trigger rejects `CREATE FUNCTION`. |
| 2 | `config` | `v15/config/v15_config.sql` | `test_config.py` | Resolve order base ⊕ depth ⊕ propagating ⊕ local; component replace not deep-merge; local layer absent on the child; depth partial does not apply at other depths; `V15_DEPTH_SELF`, `V15_CONFIG_LOCAL`, `V15_BASELINE_IMMUTABLE`. |
| 3 | `namespace` | `v15/namespace/v15_namespace.sql` | `test_namespace.py` | `jaz.var` / `assign` / `print`; scope copy vs input non-copy; `V15_SCOPE_CONFLICT`; `history` view isolated per invoke; exec_context pid binding; `v15_repl` cannot set another invoke’s context. |
| 4 | `protocol` | `v15/protocol/v15_protocol.sql` plus worker `split_sql.py` | `test_protocol.py` | Whole message is the program; `--` comments kept as non-statements; dollar-quotes; sole-form classifier; `V15_DIALECT` / `V15_INVOKE_FORM`; seed prompt contains inputs, scope, history columns, bind_invoke docs; truncation of observation text only; timeout pragma parse. |
| 5 | `loop` | `v15/loop/v15_loop.sql` | `test_loop.py` | Single invoke, no children: claim, begin/settle LLM outside any open txn (gate asserts `txid_current` differs), exec statements, print capture, return value to the host, raise, history row per iteration, 0-based iteration, print-and-return rejection, stale fence, expired attempt reclaimed once, committed statement not re-run. |
| 6 | `tools` | `v15/tools/v15_tools.sql` | `test_tools.py` | Catalog tool bound as input and as scope; `jaz.tool` return visible to later statements; tool error becomes recoverable output; scoped tool present on a child without being an explicit input; `V15_EXTERNAL_TOOL`; tool handler cannot update `invokes`. |
| 7 | `tree` | `v15/tree/v15_tree.sql` | `test_tree.py` | `bind_invoke` suspends parent, child depth+1 sees scope snapshot and not parent inputs or parent local config, child return bound for the **next** parent statement, grandchild resume, child raise → parent `Continue` with `V15_CHILD_ERROR`, fatal flag aborts ancestors, parent not claimable while `suspended`, crash mid-child still resumes parent once. |
| 8 | `hooks` | `v15/hooks/v15_hooks.sql` (`CREATE OR REPLACE v15_on_phase`) | `test_hooks.py` | Two handlers, one phase, order-independent coalesce; `V15_BLACKBOARD_CONFLICT` and `V15_INPUT_CONFLICT`; writes invisible until the next phase (`generation`); `V15_INVALID_EFFECT`; SAVEPOINT isolates a raising handler; local hook absent on child; propagating hook present; baseline row reappears if deleted (`V15_BASELINE_MISSING` if the required type is absent at begin_llm). |
| 9 | `govern` | `v15/govern/v15_govern.sql` | `test_govern.py` | Iteration hard-stop before the over-cap LLM call and transient warning; recursion disable at the leaf and fatal abort past it; local recursion rejected; shared pool reserve/settle across parent and child, refund on expired attempt, `V15_BUDGET_EXHAUSTED` with no leased attempt left behind; BudgetForcing turns the first N returns into continues then allows return; context-window warning is transient (not in `llm_messages`) and names `bind_invoke`. |

**Implementation order:** 1→9 as listed; each stage’s database load is the prefix through that stage, so the stage is testable before the next file exists. Stages 8 and 9 must land as additive `CREATE OR REPLACE` of `v15_on_phase` plus new tables, without editing `v15_loop.sql` transitions except for calls that stage 5 already makes. Stage 5’s interpreter of `action/messages/exec_result/recursion_available` is part of the loop gate (exercised with a test-only hook registered only in `test_hooks.py` / `test_govern.py`, not by weakening stage 5).

**Unknown to validate during stage 5:** whether `security_barrier` on `history` plus `search_path` is enough on PG 18.4 when the model’s `SELECT` calls a scratch-schema function in the target list. The schema gate’s event trigger forbids functions in scratch; re-check with a function created by the superuser in another schema and granted to `v15_repl` — accessor must still ignore that function’s `SET` attempts on `exec_context`.

### Oracle 2
- Status: Completed
- Provider: `codex`
- Model: `gpt-5.6-sol`
- Effective effort: `xhigh`
- Chat: `new-chat-oracle-2-B4017F`



# Summary

pg-agent v15 should be a new, standalone PostgreSQL-native implementation rather than a modification of frozen v8/v13 code. The model should write one PostgreSQL SQL/PL/pgSQL statement per turn, executed under a constrained database login; LLM and external-tool calls should be durable out-of-transaction I/O requests driven by a worker. Because PostgreSQL cannot suspend a transaction inside a model-written SQL expression and later resume its stack frame, recursive `invoke` becomes a terminal cell action: it persists a child invoke, logically suspends the parent, and delivers the child’s result into the parent’s durable namespace before the parent’s next model turn. The rest of JAZ’s architecture—named inputs, dynamic scope, configurable protocol, immutable span events, closed composable hook effects, generational blackboards, recursive configuration inheritance, and governance hooks—can be translated directly into relational state and transactional transition functions.

# Current-state analysis

## JAZ control and data flow

The Python reference implementation currently follows this path:

1. `jaz.invoke()` / `jaz.ainvoke()` in `jaz/src/jaz/invoke.py`:
   - Separates a positional `ConfigOverride` from local `Hook` instances.
   - Validates positional arguments and `ReturnType` multiplicity.
   - Chooses the inherited `Prehook` or creates a depth-1 root.
   - Normalizes t-string input values.
2. `_build_invoke_setup()`:
   - Resolves `ConfigStack` at the absolute recursion depth using:
     `base → global depth layer → propagating layers → local override`.
   - Resolves ambient `jaz.scope` and rejects any explicit-input/scope name collision.
   - Creates the invoke identity and parent linkage.
   - Builds a closure-backed recursive `invoke` tool carrying parent scope, config stack, hook context, and child depth.
   - Constructs one `Agent` and one per-invoke `HookDispatcher`.
3. `Agent.invoke()` / `Agent.ainvoke()` in `jaz/src/jaz/_agent.py`:
   - Resolves input wrappers through `resolve_inputs()` while preserving raw wrappers for prompt rendering.
   - Seeds the per-invoke `Blackboard`.
   - Opens the `InvokeEnter → InvokeSend → InvokeComplete → InvokeExit` span.
   - Applies `AddInputs`, `DropInputs`, and `DisableRecursion`.
   - Initializes a fresh `REPLState`, renders the opening messages, and creates the shared `__history__` list.
4. Each loop iteration:
   - Opens an LLM-query span.
   - Applies message edits at `LLMQueryEnter`.
   - Commits the shown messages at `LLMQuerySend`.
   - Calls or supplies the LLM response.
   - Applies response transforms at `LLMQueryComplete`.
   - Closes `LLMQueryExit`.
   - `CodeOnlyProtocol.parse()` treats the complete response as executable Python.
   - Opens a REPL-execution span, applies namespace/code edits, executes or supplies a result, and transforms it.
   - Appends a protocol-owned history entry and, for `Continue`, a rendered observation.
5. A recursive call is a normal blocking Python function call. The parent’s REPL stack remains live until the child returns or raises.

Hook state has two activation channels: context-managed hooks propagate to descendants via `ContextVar`, while positional hooks are owned by one `HookDispatcher`. Events are frozen snapshots. All active hooks see the same event and blackboard generation; only after all handlers return are effects composed and blackboard writes applied. Configuration and scope use context-local ambient state only as a same-context bridge, with explicit snapshot-and-bind behavior added for worker threads.

## PostgreSQL constraints

The following JAZ mechanics cannot be carried over literally:

- An LLM call cannot occur inside a PostgreSQL transaction because of v8 invariant 4.
- A SQL or PL/pgSQL execution frame cannot be committed, suspended while a child agent performs multiple external calls, and later resumed at the original expression.
- Python object identity, arbitrary live callables, `ContextVar` propagation, process-local hook objects, and live exception objects have no durable PostgreSQL equivalent.
- Session-local SQL state such as temporary tables, prepared statements, or backend-local variables cannot be authoritative because workers can restart or resume an invoke on another connection.

Therefore v15 requires a persisted state machine rather than a direct translation of `Agent.invoke()`. This is a new vertical implementation under `v15/`; it should reuse v8’s durable request/fence patterns without importing or modifying v8’s frozen tables or SQL.

# Design decisions

## D1. REPL language

### Recommendation

Choose **(a) model-written PostgreSQL SQL**, allowing one top-level SQL statement per turn, including a `DO` block for PL/pgSQL control flow. Do not use `plpython3u`, and do not put the REPL in an external Python subprocess.

The response protocol remains code-only: the entire LLM response is the proposed SQL statement. The statement is executed inside PostgreSQL through a constrained, `SECURITY INVOKER` cell executor under a dedicated `v15_agent_exec` login. That login receives no direct write access to kernel tables and can interact only through the agent-facing `jaz` schema.

The model-facing primitives should have these conceptual interfaces:

```text
jaz.var(name)                         -> jsonb
jaz.set_var(name, value)              -> void
jaz.print(value)                      -> void
jaz.finish(value)                     -> void
jaz.fail(error)                       -> void
jaz.invoke(bind_name, inputs, ...)    -> void
jaz.call_tool(bind_name, tool, args)  -> void
```

These are action-recording APIs, not ordinary blocking functions. A cell may produce at most one terminal or suspension action (`finish`, `fail`, `invoke`, or `call_tool`). With no such action, the cell produces `Continue`. Output is accumulated explicitly through `jaz.print`; arbitrary `SELECT` result sets are not part of the stable REPL-output contract.

The executor must run the submitted text as one server-side dynamic statement. This has three load-bearing consequences:

- Multiple top-level statements and transaction-control statements are rejected.
- `COMMIT`, `ROLLBACK`, and procedures that perform transaction control cannot break cell atomicity.
- Local PL/pgSQL variables exist only inside that statement; persistent state must go through `jaz.set_var`.

### Justification

SQL plus PL/pgSQL is PostgreSQL’s native Turing-complete substrate and keeps all authoritative REPL state, access control, and execution inside the database. It allows the system to enforce capabilities through roles and grants and makes invocation state independently recoverable after worker failure. `plpython3u` would execute untrusted Python in the database backend and would tempt implementations to make provider or tool calls from inside a transaction, directly conflicting with invariant 4. An external Python REPL could preserve JAZ’s blocking call stack more closely, but the namespace, history, sandbox, and child-continuation state would then be authoritative outside PostgreSQL, defeating the purpose of a native implementation.

### Key risks

- **SQL is not a complete hostile-code sandbox.** The execution login can still observe portions of `pg_catalog`, consume CPU, and attempt denial of service. v15 must use a dedicated database/role, revoke `CREATE` and `TEMP`, grant no untrusted procedural languages, constrain accessible schemas/functions, and apply `statement_timeout`. The spec must not claim OS-level isolation.
- **SQL statement atomicity differs from Python.** An uncaught SQL error rolls back variable writes and `jaz.print` calls made by that statement. Python’s REPL can retain mutations and stdout that happened before an exception. This is a required deviation.
- **No backend-local persistence.** Temporary tables, session GUCs, and prepared statements must not be advertised as persistent REPL state.
- **Executor behavior must be pinned on PG 18.4.** The REPL gate must prove that the dynamic execution path accepts a single `DO`/SQL statement, rejects multiple top-level commands and transaction control, and converts SQL errors into a recoverable structured observation without leaving an open transaction.

---

## D2. Execution topology

### Recommendation

Represent every invoke as a row-backed state machine. Use separate authoritative tables for invokes, turns, messages, spans, waits/deliveries, variables, and external I/O requests. Do not block a PostgreSQL transaction while waiting for an LLM, tool, or child invoke.

The invoke state set should be closed and distinguish an agent-produced raise from machinery failure:

```text
created
ready_llm
waiting_llm
ready_exec
waiting_child
waiting_tool
completed       -- Completed(Return)
raised          -- Completed(Raise)
aborted         -- hook Abort owned by this invoke
failed          -- machinery/fatal failure before a normal result
```

The normal transition path is:

```text
created
  → InvokeEnter / InvokeSend
  → ready_llm
  → LLMQueryEnter / LLMQuerySend
  → waiting_llm
  → external LLM call outside every transaction
  → LLMQueryComplete / LLMQueryExit
  → ready_exec
  → REPLExecEnter / REPLExecSend
  → execute one SQL cell
  → REPLExecComplete / REPLExecExit
  → ready_llm | waiting_child | waiting_tool | completed | raised
```

### Parent suspension and child delivery

`jaz.invoke(bind_name, inputs, ...)` stages one child action in the parent cell transaction. Cell finalization then:

1. Creates the child invoke with:
   - `parent_invoke_id`
   - parent turn and iteration
   - absolute `depth + 1`
   - inherited scope, hook stack, config stack, and budget-pool references
   - explicit child inputs
2. Creates a unique parent wait record.
3. Marks the parent `waiting_child`.
4. Leaves the parent’s `REPLExec` span open.
5. Commits; no transaction remains open while the child runs.

When the child reaches a terminal outcome, it creates an idempotent pending delivery. A later database transition, not a trigger with hidden recursion, consumes that delivery:

- On `Return`, it binds the returned JSON value to the requested `bind_name`.
- On an ordinary `Raise` or child-local `Abort`, it records structured error metadata without binding a success value.
- It exposes every delivery through `jaz.child_results`, including child ID, success/error kind, value, and error.
- It completes the suspended parent `REPLExec` span with a `Continue` result whose output tells the parent what was delivered.
- It appends the parent history entry and transitions the parent to `ready_llm`.

The returned value is therefore usable in the parent’s **next model turn**, through `jaz.var(bind_name)`. It is not returned to the original SQL expression. A fatal governance or machinery failure propagates upward by terminally failing the parent rather than becoming recoverable feedback.

Only one blocking child or tool wait is permitted per cell in the v15 core. Fanout and multiple concurrent child waits are deferred.

### External I/O request model

Use `jaz_v15.io_requests` and `jaz_v15.io_attempts` for LLM and external-tool operations. Keep these distinct from JAZ hook effects; “hook effect” and “external I/O request” must never share a table or type name.

The request protocol should reuse v8’s proven patterns:

- Stable request identity.
- Attempt identity and independent claim fence.
- Short claim transaction, then commit.
- Provider/FakeLLM/FakeTool invocation with no open database transaction.
- Separate fenced settlement transaction.
- Stale settlement rejected.
- Expired in-flight attempts become `unknown` rather than silently becoming ordinary failures.
- `NOTIFY` is a wake hint only; scanning authoritative rows always recovers work.

A child invoke is **not** an external I/O request. Creating it is an ordinary transactional control-state transition.

### Justification

This topology preserves the semantic fact that a parent invoke waits for its child while honoring PostgreSQL’s transaction and crash-recovery boundaries. Persisting the open parent REPL span makes the event lifecycle honest: `REPLExecComplete` and `REPLExecExit` do not fire until the child result exists. Delivering the result as the next observation preserves model-level usability even though the SQL stack cannot resume. Separating hook effects from external requests avoids conflating JAZ’s effect algebra with v8’s durable provider-call machinery.

### Key risks

- A child call necessarily costs an additional parent LLM turn before the parent can use the value.
- Parent recovery must handle a child that became terminal just before a worker crash. A unique wait/delivery key and compare-and-swap transition must make replay idempotent.
- A wake may be duplicated or dropped. Duplicate deliveries must no-op; dropped notifications must be repaired by scanning.
- A worker crash after a provider call but before settlement is an unknown outcome. The system must not fabricate a response or silently issue a replacement call under the same attempt.
- Long-running trees retain open invoke and REPL spans across many transactions; span closure gates must cover normal, abort, and fatal-unwind paths.

### Authority boundary

The final v15 spec should include this explicit authority matrix:

| Object | Authority |
|---|---|
| `invokes`, `turns`, `messages`, `variables` | Authoritative agent/control state |
| `invoke_waits`, `deliveries` | Authoritative parent/child synchronization |
| `io_requests`, `io_attempts` | Authoritative external-work state |
| `spans`, `events`, composed hook effects | Authoritative lifecycle/audit facts |
| Config snapshots, hook activations/state, blackboard entries | Authoritative policy state |
| `jaz.__history__` | Non-authoritative view derived from authoritative turn records |
| Runnable/claimable views | Non-authoritative projections of control state |
| `NOTIFY` payloads | Non-authoritative wake hints |
| Rendered prompt caches and reporting summaries | Rebuildable, non-authoritative projections |

---

## D3. Hook system in SQL

### Recommendation

Translate hooks into versioned, table-registered SQL handlers with immutable event rows, persisted decisions, closed effect types, and a transactional SQL dispatcher.

### Hook registry and activation

Use these conceptual components:

- `hook_definitions`
  - stable key and version/digest
  - event type
  - handler `regprocedure`
  - required/baseline flag
  - failure policy
  - allowed owner role
- `hook_activations`
  - definition/version
  - configuration JSON
  - mutable durable state JSON
  - scope: required baseline, propagating subtree, or invoke-local
  - deterministic activation ordinal
- `hook_state`
  - activation-owned state and revision
- `hook_effects`
  - immutable per-event handler outputs
- `blackboard_entries`
  - per-invoke key/value/generation

The resolved dispatch order should remain:

```text
required baseline hooks
→ inherited propagating hooks
→ invoke-local hooks
```

Order determines invocation and stable rendering only. Composition may not use “last hook wins” unless a particular effect contract explicitly says so.

### Handler contract

A registered handler should be conceptually equivalent to:

```text
handler(
    event,
    hook_config,
    prior_hook_state,
    blackboard_snapshot
) → hook_decision
```

`hook_decision` contains:

- zero or more closed `Effect` records
- the activation’s replacement state, if changed

Handlers receive values, not writable table references. The dispatcher buffers all decisions before applying any of them. A handler must not directly mutate agent state or the blackboard.

Registration is operator-only and must validate that a handler:

- has the exact required signature;
- is owned by a constrained NOLOGIN hook-owner role;
- runs as that constrained owner with a fixed safe `search_path`;
- is not owned by a superuser, `BYPASSRLS`, or role-management principal;
- is declared `STABLE` or `IMMUTABLE`;
- uses an approved language such as SQL or PL/pgSQL;
- has no grants to mutate kernel tables or call privileged mutation helpers.

Built-in handlers use the same registry and decision contract. Their state changes are applied by the dispatcher, not by private side effects inside handlers.

### Event and span records

Persist the JAZ event taxonomy:

- Invoke: `Enter`, `Send`, `Complete`, `Exit`
- LLM query: `Enter`, `Send`, `Complete`, `Exit`, `Retry`
- REPL execution: `Enter`, `Send`, `Complete`, `Exit`

Every event row carries at least:

- event and span IDs;
- invoke ID, parent identity, depth, iteration where applicable;
- event type;
- effective config snapshot ID;
- active hook activation IDs in dispatch order;
- immutable stage payload;
- blackboard generation observed;
- emission timestamp.

An `Exit` carries a tagged outcome:

```text
Completed(result)
Aborted(error)
Failed(error)
```

The span row remains open across LLM/tool/child waits. `Enter` and `Send` generally occur in the pre-work transaction; `Complete` and `Exit` occur in the later settlement/delivery transaction.

### Dispatcher algorithm

For one event, `dispatch_event(event_id)` must:

1. Lock the event’s invoke and relevant hook-state rows in stable ID order.
2. Resolve baseline, propagating, and local activations.
3. Materialize one event payload and one blackboard snapshot.
4. Call every handler against those same snapshots.
5. Record handler failures and decisions.
6. Validate every effect against the event’s allowlist.
7. Compose effects by kind.
8. Reject irresolvable conflicts.
9. Persist the composed decision and update hook activation state.
10. Apply blackboard writes as one batch, after all handlers have run.
11. Increment the blackboard generation only after that batch commits.
12. Apply the composed agent-state change.

If any composition or mandatory-policy check fails, the entire event transaction rolls back or closes the affected span through a fail-closed terminal path; no partial effects become visible.

### Composition rules

Preserve JAZ’s rules where the SQL value model permits:

- Add maps: same key and equal canonical value coalesce; differing values conflict.
- Drops: set union.
- Message/code edits: resolve against the immutable `Enter` snapshot, not a progressively modified value.
- Suppliers and transformers: use the same kind precedence and conflict rules as JAZ.
- Distinct `Return` values conflict; equal JSON values coalesce.
- Multiple aborts or raises produce a deterministic grouped-error payload ordered by activation ordinal.
- `Abort` supersedes supply/transform effects.
- Control effects at `Exit` are invalid. Blackboard writes remain separately valid under the global blackboard rule.
- Unknown or malformed effect kinds fail loudly.

Python’s “identity first, guarded `!=` second” becomes:

1. Equal stable reference handles are identical.
2. Otherwise compare canonical typed JSON envelopes with `IS NOT DISTINCT FROM`.
3. Any value that cannot be canonically compared is a conflict, not a coalesce.

### Generational blackboard

Every invoke owns a blackboard. All handlers at event E read generation N. Their `BlackboardWrite`s are buffered. Identical same-key writes coalesce; differing same-key writes raise a conflict. The batch becomes generation N+1 only after every handler and all effect validation has completed. No handler at E can observe a peer’s write from E.

### Required baseline governance

Required hooks must not be normal activations that a caller can omit or delete. Use a versioned governance manifest owned by the schema owner. Hook resolution always prepends every required definition, regardless of caller-supplied activations.

Enforce this through:

- no model/worker DML privileges on definitions or the manifest;
- a manifest digest pinned on each root invoke;
- invocation and advancement refusing to proceed when the required manifest is absent, disabled, mismatched, or fails to execute;
- required handlers always using `fail_closed`;
- optional user handlers using JAZ-compatible `isolate_and_record` behavior for ordinary handler exceptions.

An invalid effect or effect conflict is not an isolatable handler exception; it is a broken decision and fails the event.

### Justification

This preserves JAZ’s central property that hooks observe immutable snapshots and influence execution only through a finite effect algebra. Passing state into a pure decision function replaces process-local mutable hook instances without exposing the kernel tables. Persisting events and decisions also makes a dispatch crash-recoverable and auditable. Required hooks need stricter failure behavior than Python JAZ’s current “log and continue” handling because PostgreSQL is the enforcement boundary, and v8 invariant 11 requires missing or broken mandatory policy to fail closed.

### Key risks

- PostgreSQL cannot safely execute arbitrary operator-supplied functions merely because they are labeled `STABLE`. Registration must also constrain ownership, privileges, language, and `search_path`.
- Shared propagating hook state can be touched by multiple roots. The dispatcher must lock activation state deterministically.
- Persisting every event and raw decision adds write amplification. This is accepted for v15 correctness; compaction is later.
- Optional-hook exception isolation and mandatory-hook failure must remain visibly distinct in event outcomes.
- Setup/teardown resource lifecycles have no direct SQL equivalent. Durable hook activation state replaces them; external tracing exporters belong in later workers, not handler setup methods.

### Initial fail-closed code family

The full spec should freeze, at minimum, these symbolic failures and assign each a stable five-character SQLSTATE in the `P15xx` class:

| Symbolic code | Condition |
|---|---|
| `V15_GOVERNANCE_MISSING` | Required manifest/handler absent or digest mismatch |
| `V15_GOVERNANCE_FAILED` | Required handler failed |
| `V15_INVALID_EFFECT` | Effect not accepted at this event or malformed |
| `V15_EFFECT_CONFLICT` | Composed effects cannot be resolved |
| `V15_BLACKBOARD_CONFLICT` | Same-event writes disagree |
| `V15_INPUT_SCOPE_CONFLICT` | Explicit input duplicates a scoped name |
| `V15_CONFIG_INVALID` | Unknown field, wrong component shape, or illegal local depth override |
| `V15_STALE_FENCE` | Stale worker/attempt/delivery settlement |
| `V15_INVALID_TRANSITION` | State-machine precondition failed |
| `V15_EXEC_PROTOCOL` | Multiple statements, multiple terminal actions, or forbidden transaction control |
| `V15_TOOL_UNAUTHORIZED` | Invoke lacks a grant for the requested tool |
| `V15_BUDGET_UNREPORTABLE` | Cost budget configured but the adapter cannot report cost |

---

## D4. Inputs, scope, tools, and `__history__`

### Recommendation

Use one durable variable relation and stable filtered views/functions, not one schema per invoke.

### Variable representation

`jaz_v15.variables` should be keyed by `(invoke_id, name)` and carry:

- name;
- source/provenance: `explicit`, `scope`, `hook`, `repl`, or `delivery`;
- value kind;
- canonical JSON value or a stable catalog handle;
- display description;
- hidden/display policy;
- revision and creation turn.

The v15 core value kinds should be:

- `json`: canonical JSON-compatible scalar/container;
- `tool_ref`: stable tool catalog ID;
- `relation_ref`: reserved but not generally writable until a later relational-input stage.

All public input names and `bind_name` values must satisfy a frozen identifier rule and must not use reserved framework names.

Agent-facing access is through:

- `jaz.var(name)` and `jaz.has_var(name)`;
- read-only `jaz.variables`;
- `jaz.inputs` and `jaz.scope` provenance views.

Assignments persist only through `jaz.set_var`. A normal SQL local variable, CTE, or PL/pgSQL variable lasts only for the current cell.

### Dynamic scope

Represent `jaz.scope` as explicit, durable scope layers rather than process `ContextVar`s:

- A root launch receives a resolved scope-layer stack.
- Inner layers shadow outer layers.
- A child automatically inherits its parent’s resolved scope.
- A child request may add a subtree scope layer.
- Explicit child inputs do not propagate further.
- An explicit input colliding with any resolved scope name fails with `V15_INPUT_SCOPE_CONFLICT`.
- Scope mappings are snapshotted when an invoke is created. JSON values are immutable values, not shared mutable Python references.

No “partial unbind” operation is needed in the core, matching `jaz.scope`.

### History

Expose a read-only `jaz.__history__` view filtered by the current invoke context. It should contain one row per completed REPL iteration, ordered from iteration 0, with at least:

- `iteration`;
- full raw LLM response/code;
- committed SQL code after hook edits;
- full REPL output;
- structured SQL exception/error payload or null;
- terminal/control result metadata.

There is no initialization row. A suspended child/tool cell does not get a history row until its delivery completes the open REPL span. The terminal entry is appended after the terminal turn, so—as in JAZ—the finishing agent cannot read its own terminal entry during that turn.

`jaz.__history__` is a projection over authoritative turn/result rows, not a second writable history store.

### Tools

Represent tools as catalog capabilities:

- `tool_definitions`: name, version/digest, description, input/output schema, execution kind;
- `tool_grants`: which root/invoke or scope can call which tool;
- tool references may be passed as input or scope values;
- `jaz.tools` exposes only granted tools;
- `jaz.call_tool(bind_name, tool_name, args)` stages one durable tool request and suspends the REPL span;
- delivery binds a successful value and records every result in `jaz.tool_results`.

The core supports FakeTool workers only. A pure SQL tool may eventually execute synchronously, but it must still be cataloged and permissioned; arbitrary function execution is not an implicit tool surface.

### Prompt rendering

The SQL protocol should preserve JAZ’s separate presentation channels:

- Scoped variables render in the system prompt.
- Explicit inputs render in the user prompt.
- Both are addressable through the same variable API.
- A hidden value is bound but omitted from prompt rendering.
- The recursive `invoke` API is advertised only when recursion is available.
- Tool descriptions come from the catalog, while invocation uses the stable catalog name/ID.
- Large values may be abbreviated in the prompt, while `jaz.var` and history retain the full stored value.

### Justification

A stable variable table and filtered API survive worker restarts and connection changes, while per-invoke schemas would create catalog bloat, expensive DDL, complicated cleanup, and unsafe `search_path` behavior. JSONB is PostgreSQL’s most predictable heterogeneous durable value representation and gives total equality for hook composition. The resulting syntax is not bare variable access, but every item shown to the model remains programmatically addressable, satisfying the paper’s semantic property rather than copying Python’s lexical spelling.

### Key risks

- JSONB is narrower than JAZ’s arbitrary Python-object domain.
- Relation handles require careful ownership, snapshot, and ACL semantics and should not be improvised in the core.
- Scope values are copied immutable values/handles, not shared mutable object references.
- Tool calls are continuation actions, not ordinary synchronous SQL function results.
- The current invoke context used by `jaz.var` and views must be derived from a fenced execution token, not a caller-settable GUC alone.

---

## D5. Config stack

### Recommendation

Use versioned config bases and ordered layer records, with each invoke storing an immutable resolved snapshot and the propagating stack it may pass to children.

The configuration shape remains three whole components:

```text
Config {
    llm:      configured LLM component
    repl:     configured SQL REPL component
    protocol: configured code-only protocol component
}
```

Each component is a complete JSON object validated against its component schema. Setting a component replaces it; fields are not recursively merged across component versions.

### Sources and resolution order

Store four distinct sources:

1. Versioned base config.
2. Versioned global exact-depth partials.
3. Ordered propagating layers:
   - unconditional `ConfigOverride`;
   - exact-depth `ConfigOverrideByDepth`.
4. One optional invoke-local plain override.

Resolve at absolute depth, with root depth 1:

```text
base
⊕ exact global depth partial
⊕ applicable propagating layers in declaration order
⊕ local override
```

Later values replace earlier component values.

A `ConfigOverrideByDepth` is legal only as a propagating layer. Passing it as the local override fails with `V15_CONFIG_INVALID`, matching JAZ’s rejection of a degenerate one-invoke depth map.

### Durable scoping

Because there is no Python `with` stack:

- Root launch records the propagating layer IDs active for the root.
- A child inherits those IDs.
- A child request may add a new propagating layer for that child subtree.
- A child request may also carry one local override for that child only.
- An invoke’s own local layer is not added to the child stack.
- Hook and scope activations use the same explicit subtree/local distinction, but remain separate tables and contracts.

### Snapshot behavior

At invoke creation, resolve and persist:

- base version;
- layer IDs and versions;
- absolute depth;
- resolved config JSON;
- config digest.

All events from that invoke reference the same snapshot. Descendants resolve from the root-pinned base/depth version plus their inherited/new layers.

This intentionally prevents a process-wide config change from silently altering an already-running durable tree.

### Baseline hooks

Required baseline hooks are **not** a mutable config component. They are resolved from the operator-owned governance manifest and pinned separately on the root invoke. This prevents a config override from replacing or removing enforcement.

### Justification

The resolution order is the same as `ConfigStack.resolve_for_depth()` in `jaz/src/jaz/config.py`, including exact depth, ordered propagating layers, and a final local layer. Persisting the stack and resolved snapshot makes the result reproducible across worker restarts. Keeping required hooks outside config closes the possibility that a configuration write could strip the database’s mandatory enforcement boundary.

### Key risks

- Whole-component replacement must be explicit in validation and documentation; a JSON deep merge would silently recreate the unsound configuration behavior that JAZ removed.
- A child must inherit the parent’s propagating stack, not the parent’s resolved config, or depth layers will not resolve correctly.
- Snapshotting differs from the Python implementation’s process-live global base behavior. This is deliberate for durable execution and must be in the deviation ledger.
- Layer order must be stored, not inferred from timestamps.

---

## D6. Budgets and limits

### Recommendation

Implement these as built-in hooks over the same registry/effect path as custom hooks. Their durable state must live in hook activation or pool rows, never worker memory.

| Hook | State scope | Event/enforcement point |
|---|---|---|
| `IterationLimit` | Per invoke | `LLMQueryEnter` before request creation |
| `RecursionLimit` | Propagating subtree | `InvokeEnter` |
| `BudgetPool` | Explicit shared pool, potentially spanning roots | Check/reserve at `LLMQueryEnter`; account at completed `LLMQueryExit` |
| `BudgetForcing` | Per invoke within activation | `REPLExecComplete` transform boundary |
| `ContextWindowWarning` | Per invoke | Record tokens at completed `LLMQueryExit`; add warning at next `LLMQueryEnter` |

### IterationLimit

- Iterations remain zero-based.
- At `iteration >= max_iterations`, emit `Abort` before creating an LLM request.
- Warning thresholds emit `AddMessages`.
- The remaining-turn calculation uses the same count semantics as JAZ.
- A mandatory finite operator ceiling should exist even if the caller does not add its own limit. The caller may tighten but not raise that ceiling.

### RecursionLimit

- At `depth == max_depth`, emit `DisableRecursion`; both the prompt and executable `jaz.invoke` surface disappear.
- At `depth > max_depth`, emit `Abort` as a backstop.
- Child creation independently rechecks the absolute depth so a forged action row cannot bypass the hook.
- A mandatory operator maximum depth should be present.

### BudgetPool

- A pool is an explicit durable object referenced by hook activations.
- Descendants inherit the same pool ID.
- Multiple roots may deliberately share one pool ID, reproducing a reused context-managed `BudgetPool`.
- Call budget admission is serialized by locking the pool row and reserving the call at `LLMQueryEnter`.
- Completed response settlement accounts cost exactly once by request ID.
- A cost budget requires an adapter that reports cost before the first request; otherwise fail with `V15_BUDGET_UNREPORTABLE`.
- Cost is checked before each request using settled spend; one request may overshoot a monetary budget because its cost is unknown until completion, matching JAZ’s sequential behavior.
- Warnings are `AddMessages`, not direct conversation mutation.

### BudgetForcing

At `REPLExecComplete`, when the raw result is `Return` or `Raise` and the configured refusal count has not been exhausted, emit `ModifyExecResult(Continue(...))`. This keeps the invoke alive for another turn. The refusal count is durable per invoke and activation. It must also work when the raw result was supplied rather than executed.

### ContextWindowWarning

- Read prompt-token usage only from completed LLM-query outcomes.
- Resolve the model’s maximum input tokens from the invoke’s frozen LLM config.
- At the next `LLMQueryEnter`, emit a transient warning when the configured fraction is crossed.
- Delegate guidance must inspect `can_recurse`; a cap leaf must receive finish guidance rather than an impossible sub-invoke instruction.
- Missing token metrics disable this advisory hook but do not weaken hard iteration/depth limits.

### Fail-closed baseline

The governance manifest should require at least:

- a finite hard iteration ceiling;
- a finite hard recursion ceiling;
- authorization for all tools;
- valid request/fence policy.

Cost budgeting, budget forcing, and context warnings remain optional unless an operator policy explicitly requires them.

### Justification

These placements match the JAZ event semantics: liveness limits belong at the always-present `LLMQueryEnter`, recursion availability is fixed at `InvokeEnter`, terminal-result nudges belong at `REPLExecComplete`, and context usage is known only after the LLM query completes. Database rows and row locks replace Python object state and thread locks, allowing budget enforcement to survive retries and coordinate across descendants or multiple roots.

### Key risks

- Accounting must be idempotent by stable request ID; retries and duplicate settlements cannot charge twice.
- Cost may be incurred even when settlement is lost. Such attempts remain `unknown`; the budget ledger must expose uncertainty instead of recording zero.
- A policy change while a request is in flight must not retroactively pretend the request never occurred.
- Mandatory limits are stricter than stock JAZ, where these hooks are opt-in. This is a documented database-governance deviation.

---

## D7. Scope of v15

### Recommendation

Ship a nine-stage core that demonstrates the two paper-defining properties and PostgreSQL-native governance, while intentionally excluding provider integrations and higher-level operational features.

### In scope

1. Code-only SQL/PL/pgSQL REPL with persistent variable state.
2. Arbitrary named JSON inputs and separate prompt/render metadata.
3. Durable dynamic scope with child inheritance.
4. Programmatically queryable `jaz.__history__`.
5. Recursive invoke as persisted parent suspension and child delivery.
6. Tool catalog, capability grants, and durable FakeTool execution.
7. Config base, exact-depth layers, propagating overrides, and local overrides.
8. Immutable Enter/Send/Complete/Exit event rows.
9. Closed hook effects, deterministic composition, and generational blackboard.
10. Durable LLM/tool request claim, fence, settlement, unknown-outcome handling, and FakeLLM/FakeTool adapters.
11. Mandatory iteration/depth/tool-authorization governance.
12. `BudgetPool`, `BudgetForcing`, and `ContextWindowWarning`.
13. Complete ACL and role proof for the model execution role.
14. Standalone cumulative stage databases and gates on PostgreSQL 18.4.

### Later

- Real LLM provider adapters and provider-specific retries/pricing.
- Jaeger, Langfuse, OpenTelemetry, and external trace exporters.
- Trajectory replay/workflow replay, despite reserving supply-effect contracts.
- `ReturnType`, `ValidateReturn`, and rich SQL/JSON schema validation hooks.
- CodeAct ablation/parity hooks and jaz-evals-compatible harnesses.
- Parallel child fanout or multiple outstanding child/tool waits per parent.
- Arbitrary relation/object input handles beyond JSON and catalog capabilities.
- Python or other language REPL compatibility.
- Session compaction, event archival, and projection optimization.
- Human approval/UI surfaces.
- Production scheduler scaling, multi-tenant quotas, and real-provider unknown-outcome policy refinements.

### Justification

This cut is large enough to prove the paper’s semantics—recursive invoke plus programmatic access to all named inputs and history—without making the first version depend on external provider behavior or tracing systems. It also includes the hook/config/governance machinery needed to show that the framework is extensible rather than a one-off loop. Nine cumulative stages fit the repository’s established gate discipline while keeping each milestone narrow enough to test independently.

### Key risks

- The core is not provider-ready merely because it has a durable request table.
- SQL syntax and continuation semantics will prevent byte-for-byte parity with existing Python prompts and eval traces.
- Without fanout, the first release validates recursive delegation but not multi-agent parallelism.
- JSON-only values limit some paper examples involving live DataFrames or arbitrary Python tools.

# Required deviation-ledger entries

The eventual `docs/reviews/v15-deviation-ledger-*.md` should contain at least the following entries. These are architectural deviations, not implementation defects.

| ID | JAZ behavior | v15 behavior and rationale | Observable consequence |
|---|---|---|---|
| `V15-D01` | `invoke()` blocks and returns inside the same Python expression | `jaz.invoke` terminates the current SQL cell, suspends the parent, and delivers into the next model turn | Child consumption requires an explicit bind name and an additional parent LLM turn |
| `V15-D02` | Arbitrary Python objects and callables can be input values | Core values are JSONB or stable catalog handles; tools are catalog capabilities | No arbitrary object identity or direct callable invocation |
| `V15-D03` | Inputs are bare Python variables | Inputs use `jaz.var`/filtered views | Property 2 is preserved semantically, not lexically |
| `V15-D04` | Python mutations/stdout before a recoverable exception may survive | A failing SQL statement rolls back its statement-local writes/output | Error turns are atomic |
| `V15-D05` | `ContextVar` implements lexical dynamic scope | Scope, hook, and config propagation use explicit durable layer IDs and creation-time snapshots | No implicit thread/task context propagation |
| `V15-D06` | Global configuration may remain process-live | Root/base versions and invoke configs are pinned for durable reproducibility | Mid-run global config changes affect only later roots |
| `V15-D07` | Hook objects may mutate local state and run setup/teardown | SQL handlers return decisions plus replacement durable state; no setup/teardown lifecycle | External resources cannot be owned by a handler instance |
| `V15-D08` | Ordinary hook exceptions, including governance bugs, are logged and ignored | Required governance hook failures are fatal/fail-closed; optional hooks may be isolated | Stronger enforcement semantics |
| `V15-D09` | Limits are opt-in | Operator iteration and recursion ceilings are mandatory and cannot be disabled | Every production invoke has finite hard caps |
| `V15-D10` | Python can launch parallel sub-invokes | Core v15 permits one blocking child/tool wait per cell | Fanout deferred |
| `V15-D11` | History stores live exception objects | History stores structured SQL error records | Exception identity and arbitrary attributes are unavailable |
| `V15-D12` | REPL process/session state can persist naturally | Only relational variables/messages/history are persistent; temp/backend-local state is unsupported | Restart-safe behavior at the cost of narrower REPL state |

# Proposed stage and gate plan

`v15/load.py` should append each SQL file in the order below, with `STAGE_THROUGH` values 1–9. Every `setup_db.py` drops and recreates its isolated stage database and calls the cumulative loader through its own stage. SQL files use plain `CREATE` statements without `IF NOT EXISTS`.

| # | Stage | SQL file | Standalone gate | What the gate proves |
|---:|---|---|---|---|
| 1 | `schema` | `v15/schema/v15_core.sql` | `v15/schema/test_schema.py` | Roles, closed enums, invokes/turns/messages/spans/events, append-only constraints, parent/depth invariants, legal state transitions, terminal-result vs failed-outcome distinction, and stable SQLSTATE/error codes |
| 2 | `values` | `v15/values/v15_values.sql` | `v15/values/test_values.py` | Explicit inputs, scope shadowing, explicit/scope conflict refusal, variable persistence across connections, hidden/display metadata, current-invoke filtering, history projection shape, and inability of the agent role to access another invoke |
| 3 | `config` | `v15/config/v15_config.sql` | `v15/config/test_config.py` | Exact resolution order; whole-component replacement; exact-depth behavior; local override highest precedence; local depth override rejection; child inheritance excluding parent-local layers; immutable config snapshots and digests |
| 4 | `hooks` | `v15/hooks/v15_hooks.sql` | `v15/hooks/test_hooks.py` | Handler registration restrictions; baseline/propagating/local order; event-effect allowlists; deterministic add/drop/supply/modify/abort composition; invalid-effect failure; optional vs required handler failures; same-event blackboard invisibility and conflict behavior |
| 5 | `repl` | `v15/repl/v15_repl.sql` | `v15/repl/test_repl.py` | Code-only identity parsing; one-statement SQL/`DO` execution; `jaz.var`, `set_var`, `print`, `finish`, and `fail`; one-control-action rule; statement rollback on error; timeout behavior; no transaction escape; and model-role ACL isolation |
| 6 | `io` | `v15/io/v15_io.sql` | `v15/io/test_io.py` | LLM/tool request and attempt identities; claim leases and fences; stale settlement rejection; duplicate settlement idempotency; unknown outcome after abandoned attempt; authorization; notifications as hints; FakeLLM/FakeTool callbacks running with no open transaction |
| 7 | `loop` | `v15/loop/v15_loop.sql` | `v15/loop/test_loop.py` | Complete non-recursive invoke loop using FakeLLM: initial prompt, LLM and REPL span order, message edits, raw SQL parse, Continue observation, Return/Raise completion, one history row per completed iteration, and closure of every opened span |
| 8 | `recursion` | `v15/recursion/v15_recursion.sql` | `v15/recursion/test_recursion.py` | Parent suspension without an open transaction; child creation/depth/parent iteration; successful bind delivery; recoverable child error; fatal propagation; duplicate/dropped wake recovery; open parent REPL span closure; scope/config/hook inheritance; and one-wait-per-cell enforcement |
| 9 | `govern` | `v15/govern/v15_govern.sql` | `v15/govern/test_govern.py` | Mandatory manifest enforcement and ACL non-bypass; iteration and recursion hard stops; shared BudgetPool accounting; unreportable-cost refusal; BudgetForcing; recursion-aware ContextWindowWarning; end-to-end nested FakeLLM/FakeTool run; and all required failures closing spans correctly |

Each stage directory should also contain `README.md`. The implementation line should maintain:

- `docs/reviews/v15-conformance-matrix-*.md`
- `docs/reviews/v15-deviation-ledger-*.md`

Those files must be updated as part of each stage milestone, consistent with `AGENTS.md`.

# File-by-file impact

## Round-1 design artifact

- `docs/designs/v15-jaz-dev.md`
  - Later freezes the decisions above into numbered invariants, schemas, transition contracts, SQLSTATE codes, authority matrix, API contracts, deviations, and gates.
  - Must not claim literal compatibility for the deviations listed above.

## New implementation tree

- `v15/load.py`
  - Defines `SQL_LOAD_ORDER`, `STAGE_THROUGH`, `files_through`, `run_psql`, and `load_stage`.
  - Contains only v15 paths; no imports from v8/v13 SQL state.
- `v15/<stage>/v15_<stage>.sql`
  - One cumulative stage artifact for each row in the stage table.
- `v15/<stage>/setup_db.py`
  - Creates the isolated stage database and cumulatively loads through that stage.
- `v15/<stage>/test_<stage>.py`
  - Standalone executable gate, exit code 0 on success.
- `v15/<stage>/README.md`
  - Stage contract, run command, and delivered SQL surface.
- `docs/reviews/v15-conformance-matrix-*.md`
  - Maps frozen v15 requirements to gates.
- `docs/reviews/v15-deviation-ledger-*.md`
  - Records every intentional difference from JAZ.

No v8 or v13 SQL, load order, or frozen design document should be modified.

# Risks and migration

v15 is a new versioned implementation, so there is no in-place schema or persisted-data migration from v8/v13. Its stage databases and load order are independent. The primary rollback requirement is therefore repository-level: lower v15 stages must continue loading and passing after later files are appended. Every stage milestone must run its own gate and all earlier v15 gates before updating review artifacts, committing, and pushing as required by `AGENTS.md`.

The two highest-risk implementation assumptions must be proven early rather than deferred:

1. On PostgreSQL 18.4, the chosen dynamic cell executor must structurally reject multiple top-level statements and transaction termination while accepting the approved one-statement SQL/`DO` language.
2. A registered hook function owned by a constrained NOLOGIN role must execute with only that owner’s grants even when called from the privileged dispatcher, with a pinned `search_path` and no kernel-table mutation route.

If either gate fails, the fallback must be a narrower language/registration surface—not a relaxation of the transaction or privilege invariants.

# Implementation order

1. Freeze `docs/designs/v15-jaz-dev.md`, including exact table columns, transition predicates, SQLSTATE assignments, role grants, and deviation ledger language.
2. Add `v15/load.py` and the `schema` milestone.
3. Add durable values/scope/history access.
4. Add versioned config resolution and invoke snapshots.
5. Add hooks, effects, span events, and blackboard composition.
6. Add the constrained SQL REPL and code-only protocol.
7. Add durable out-of-transaction I/O requests with FakeLLM/FakeTool.
8. Add the non-recursive loop.
9. Add recursive parent suspension and child/tool delivery.
10. Add mandatory governance and the final end-to-end gate.

Stages 7–9 are behaviorally dependent on the earlier contracts but remain separate milestones. Within each milestone, its SQL, setup script, gate, README, conformance matrix update, and deviation-ledger update must land atomically.