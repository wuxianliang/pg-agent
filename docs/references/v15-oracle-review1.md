## Ask Oracle ✅
- Oracle group status: completed
- Oracle group: `91693890-A7A5-44A3-AB04-B3F59D2BD919`

### Oracle
- Status: Completed
- Provider: `grokBuild`
- Model: `grok-4.7-build-fast-xhigh`
- Effective effort: Provider default / not specified
- Chat: `new-chat-279164`



The assembled contract keeps the paper’s two properties on the happy path: a canonical `bind_invoke` suspends between statements, §4.8 binds `kind=var` and resumes `resume_stmt+1` on the same iteration with `repl_exec` still open, and §4.12 continues that cursor without `v15_begin_llm`. Addressability of inputs, scope, `jaz.var`, `jaz.history`, and `jaz.prior_history` is coherent. The freeze is blocked by cross-chunk state-machine holes (retry is not scannable and attempt 2 has no legal insert path), kernel signatures that cannot carry the prompt or the child inputs, a scratch/tool privilege model PostgreSQL 18.4 will not execute as written, and §4/§9/§10 phase and budget contracts that describe different jsonb shapes and different writers for the same update.

## P0

### 1. Expired-attempt retry is not recoverable, and attempt 2 cannot be inserted
§4.10, §4.5.1, §4.12, §1.3, §0.23. Reclaim inserts a new `leased` attempt, then releases the invoke lease only when **no** `leased` attempt remains. `v15_next_runnable()` returns only `runnable`. `v15_claim` ignores `leased`. `v15_begin_llm` rejects an expired invoke lease with `V15_INVALID_TRANSITION`, and its precondition allows `iteration=llm` only when a `leased` attempt **already** exists — in which case it adopts and does not insert. `v15_mark_call_started` requires a live invoke lease. `v15_reclaim_expired` returns `int`, not attempt ids or fences.

After a crash, reclaim marks the old attempt `unknown`/`failed`, inserts attempt n+1, and leaves the invoke `leased` with `lease_until` in the past. Scan never returns it. Mark and begin both refuse it. The next expiry repeats this with `call_started=false` until `V15_IO_EXHAUSTED`. No retry calls FakeLLM. That breaks §0.6 and §0.23.

§4.5.1 also calls `enter`/`send` **before** the adopt branch, while the adopt branch says not to emit them again.

**Fix.** Reclaim only terminates the expired attempt and fixes the pool (§11.3). It sets that invoke `runnable`, bumps `invokes.fence`, and does not insert an attempt. Replace the §4.5.1 precondition with: `pending`, or `llm` with `llm_requests.status=open` and no `leased` attempt. Call `enter`/`send` only when `v15_span_open(llm_query)` is false. When the span is already open, insert attempt `n+1` with `fence=1`, reserve again, and do not emit `enter`/`send` (the `retry` audit row stays on reclaim, with `new_attempt_id` null until this insert).

### 2. `v15_begin_llm` and `v15_suspend_for_child` cannot see the data they must store
§4.2 signatures versus §4.5.1, §6.5, and §4.7.

`v15_begin_llm(p_invoke_id, p_fence, p_owner)` has nowhere to receive the rendered request or `logical_digest`. The renderer is Python (`render_prompt.py`); seeds are immutable; truncation happens before the digest. Child open is inside `v15_suspend_for_child(p_invoke_id, p_fence, p_stmt_index, p_statement_fence)`, which also has no `jsonb` argument, while §4.7 evaluates `<jsonb-expr>` as `v15_repl` and then creates bindings from that value. A definer body that re-evaluates the expression runs as `v15_owner`.

**Fix.**

```text
v15_begin_llm(p_invoke_id uuid, p_fence bigint, p_owner text,
              p_request jsonb, p_logical_digest text) returns uuid

v15_suspend_for_child(p_invoke_id uuid, p_fence bigint, p_stmt_index int,
                      p_statement_fence bigint, p_child_inputs jsonb) returns uuid
```

Worker renders and truncates, then calls `v15_begin_llm`. SQL checks `p_logical_digest` against the stored request with `attempt_id` removed, and performs the §6.5 commit-class `V15_VALUE_INVALID` abort itself. Same transaction, before `v15_suspend_for_child`, the worker `SELECT`s the child seed texts from `render_prompt.py` and passes them in (`p_system_text text, p_user_text text`). `v15_open_invoke` grows the same two text arguments for the root seed. Local Python render while the transaction is open is ordinary CPU, not provider I/O.

### 3. Kernel transitions that check `current_user` always raise `V15_ROLE`
§0.9, §0.20, §2 matrix: “内核转移 MUST 拒绝任何其他 `current_user`”; “只有 `current_user` 为 `v15_worker` 时” `v15_suspend_for_child` may insert a child. §4.1: the transition is `SECURITY DEFINER`, so inside the body `current_user` is `v15_owner`, and the check that matches the caller is `session_user = v15_worker`.

**Fix.** In §0.9, §0.20, and the §2 matrix, kernel transitions authorize `session_user = v15_worker`. `jaz.*` invoker wrappers keep `current_user = v15_repl`.

### 4. Scratch ownership, GRANT, `search_path`, and the DDL classifier do not run on PG 18.4
§0.26 and §4.1 say the scratch schema owner is `v15_worker`. `v15_open_invoke` is `SECURITY DEFINER` as `v15_owner`, so `CREATE SCHEMA` is owned by `v15_owner`. `CREATE SCHEMA … AUTHORIZATION v15_worker` requires `v15_owner` to be a member of `v15_worker` or a superuser. §2 gives `v15_owner` no memberships.

§4.6.2 puts `GRANT USAGE` inside `v15_prepare_statement`. Only the schema owner (or a superuser) can grant. §6.4 then has a definer event trigger `ALTER … OWNER TO v15_worker`. `ALTER OWNER` to a role the executor does not inherit requires superuser. `ddl_command_end` functions that are `SECURITY DEFINER` see `current_user = v15_owner`, so a guard written as `current_user = v15_repl` never sees the model.

Every transition is declared `SET search_path = pg_catalog`. `set_config('search_path', …, true)` inside that function is restored on function exit, so the model statement does not keep the scratch path. `USAGE` alone also does not allow `CREATE TABLE`; that needs `CREATE` on the schema.

Separately, §6.2 step 3 assigns every statement whose first token is `CREATE`/`ALTER`/`DROP`/`TRUNCATE` to `V15_DDL`. §0.26, §6.4, §6.5 (“You may create objects only in that schema”), and §17 require scratch DDL other than `CREATE FUNCTION`.

**Fix.** Schema owner is `v15_owner` (the definer who creates it). `v15_repl` receives no committed `USAGE` or `CREATE`. `v15_prepare_statement` grants both for non-bind statements, and only `USAGE` for `bind_invoke`, with no `GRANT OPTION`. The worker, after prepare returns, runs `SELECT set_config('search_path', scratch || ', pg_catalog', true)`. Drop “`ALTER … OWNER TO v15_worker`”. `v15_scratch_guard` is `SECURITY INVOKER` and only `RAISE`s: `CREATE FUNCTION|PROCEDURE|ROUTINE` → `V15_DDL`; any new object whose schema is not `exec_context.scratch_schema` → `V15_DDL`. `CREATE EVENT TRIGGER` stays in superuser `setup_db`. Terminal `DROP SCHEMA … CASCADE` runs as `v15_owner`; `GRANT v15_repl TO v15_owner` so owner-checks cover objects created by `v15_repl`. Access after commit is cut by revoking schema `USAGE`.

Replace §6.2 step 3 with: first token `CREATE FUNCTION|PROCEDURE|ROUTINE|EXTENSION|ROLE|DATABASE` or `GRANT`/`REVOKE`/`COMMENT`/`VACUUM`/`REINDEX`/`CLUSTER`/`SECURITY` → `V15_DDL`. `CREATE`/`DROP` `TABLE|INDEX|VIEW`, `CREATE TABLE AS`, `ALTER TABLE`, and `TRUNCATE` stay `kind=plain` with an empty `reject_code`; the event trigger is the schema boundary.

### 5. Tool calls inherit `v15_owner`, and PUBLIC can execute handlers
§5.3 calls the tool `regprocedure` from `v15.jaz_tool`, which is `SECURITY DEFINER`. An invoker tool therefore runs as `v15_owner` and can write kernel tables. A definer tool runs as its `NOLOGIN` owner and cannot see the scratch schema, which contradicts §5.5 (“`jaz.tool` 的 scratch 写入留下”). New functions are `EXECUTE`-granted to `PUBLIC` by default; §9.3 never revokes that, so `v15_repl` can call a tool or hook body and skip `tool_grants`.

§9.2 checks only `md5(prosrc)`. `ALTER FUNCTION … OWNER` / `SET search_path` leaves `prosrc` unchanged, so a later call still passes `V15_HANDLER_DIGEST` and runs as the new owner. The registration trigger does not fire on `ALTER FUNCTION`.

Hooks as `SECURITY DEFINER` owned by `v15_hook_<key>` are the right shape. A `SECURITY INVOKER` handler called from a definer dispatcher would run as `v15_owner`. Do not switch hooks to the codex `v15_hook_runner` invoker model.

**Fix.** At registration, `REVOKE ALL ON FUNCTION … FROM PUBLIC`. Hook `EXECUTE` goes only to `v15_owner`. Tool `EXECUTE` goes only to `v15_owner`. Tool handlers are `SECURITY INVOKER`. `v15.jaz_tool` does `SET LOCAL ROLE v15_repl`, calls the tool, then `RESET ROLE` before return (`GRANT v15_repl TO v15_owner WITH SET TRUE, INHERIT FALSE`). On every hook and tool call, re-check `proowner`, `provolatile = 's'`, `prosecdef`, language, and exact `search_path=pg_catalog` (one element, no `pg_temp`). `handler_digest` is `md5` of `pg_get_functiondef` plus owner and `proconfig`, which is the digest scope in the codex alternative §9.4; keep the adopted `STABLE`-only rule (the alternative also allowed `IMMUTABLE`).

### 6. Budget updates name two quantities and two writers
§4.5.1 and §4.5.3 always do `calls_reserved ± 1` and `calls_used + 1`. §11.3 and §9.4 use `reserve_calls` (any integer `>= 1`) and `reserve_cost`, and §11.3 stores `budget_reserve_calls` on the attempt. §4.10 “重新预留 1 次调用” while §11.3 says the new attempt “重新走预留”. §0.15 says only the dispatcher writes pools; §4.5.1 writes them in `v15_begin_llm`. §11.3 places the reserve at the end of `llm_query/enter`; §9.6 places that same reserve after `send` returns `proceed`. `action=abort` is commit-class (§4.1). A reserve inside `enter` that `send` then aborts commits `calls_reserved` with no attempt row and no refund in §4.8.

There is no `cost_reserved` column. The §11.3 predicate `cost_used + reserve_cost <= cost_limit` does not hold a reservation across transactions.

**Fix.** One reserve, inside `v15_on_phase`, after `send` returns `proceed` and before the attempt insert. Quantity is the composed `reserve_calls` / `reserve_cost`, default `{1, 0}`. `v15_begin_llm` does not issue a second `UPDATE`. Persist both numbers on `llm_attempts.request`. Settle and reclaim add/subtract those stored numbers (§11.3), and the §4.5.3 / §4.10 “± 1” sentences are deleted. Reclaim of attempt n+1 is the §4.5 insert path (finding 1), so hooks run only when the span is still closed; a retry copies the previous attempt’s `budget_reserve_calls` and `budget_reserve_cost` and reserves those, because reclaim does not call `v15_on_phase`. Any terminal path after a successful reserve refunds `calls_reserved` by the stored amount in that same transaction (`unknown` still moves it into `calls_used`). Add `cost_reserved numeric NOT NULL DEFAULT 0` and the same conditional `UPDATE` pattern as calls, or state in §11.3 that `reserve_cost` is a single-statement precheck and settle-time `V15_BUDGET_EXHAUSTED` is the real cost ceiling.

### 7. Lock order deadlocks
§4.1 and §11.3: lock `budget_pools` by `pool_id`, then `invokes` by `invoke_id`. §4.5.1 checks and locks the invoke, then locks the pool. §4.9 locks the child for the fence check; §4.8 then locks ancestors, which can have smaller `invoke_id`s. §4.8 also updates non-terminal descendants but the lock sentence names only the child and ancestors.

**Fix.** Any transition that will touch a pool or more than one invoke reads the id set first (unlocked), locks pools in `pool_id` order, then locks every invoke it will write — self, ancestors, and non-terminal descendants — in `invoke_id` order, then re-reads fences and statuses. `v15_finish_exec` uses that order before the §4.9 checks.

### 8. §4, §9, and §10 disagree on the phase jsonb the transitions must honor
§4.1 / §9 opening: `v15_on_phase` returns top-level `code` and the key set `contract, action, fatal, code, messages, exec_result, recursion_available, input_adds, input_drops, blackboard_writes, budget`. §9.4 handlers return `error` and `message_drops`, not `code`. §9.7 tells §4 to read `code` “原样”. §9.5 both synthesizes disagreeing aborts into a **committed** abort whose code is `V15_EFFECT_CONFLICT` (with `payload.codes`) and says conflict codes **roll back** the phase. §13 classifies `V15_EFFECT_CONFLICT` as rollback-class. §9.4 isolates a non-baseline “bad shape” and also says a reserved key such as `supply_llm_response` is always `V15_INVALID_EFFECT` for every channel. Those keys are outside the allowed handler key set, so both sentences apply.

§9.1 required `io` keys are not what §4 passes: `llm_query/send` needs `input_chars` (§4.5.1 passes `iteration` and `logical_digest` only); `complete`/`exit` need `attempt_id`; `repl_exec/enter` needs `iteration` and `resume_stmt`; `repl_exec/complete` needs `result_kind`, `return_value`, `error`, `capture`. Stage 9 enforcement of §9.1 raises `V15_PHASE_CONTRACT` on a normal call. The `iteration` vs `io.iteration` check fires for phases whose `io` has no `iteration` (`invoke/enter` carries `depth`).

§10.2’s forcing payload is `"return_value": null` (JSON null). §9.4 requires SQL NULL. A handler can only return jsonb, so the forcing effect is `V15_INVALID_EFFECT` as written. §4.9’s continue precondition requires **no** `return` row; §9.4 says this effect takes the continue branch anyway. `invokes.return_value` is already set by `jaz."return"`.

§4.1 “回滚类只有” omits `V15_EFFECT_CONFLICT`, `V15_BLACKBOARD_CONFLICT`, `V15_INPUT_CONFLICT`, `V15_HANDLER_DIGEST`, `V15_HANDLER_SHAPE`, `V15_DEPTH_SELF`, `V15_CONFIG_LOCAL`, `V15_BASELINE_IMMUTABLE`, structural `V15_DELIVERY_CONFLICT`, and root `V15_SCOPE_CONFLICT`, all rollback-class in §13.

**Fix.** Handler object and phase object stay distinct. Handlers return `error: {code, message}`. The dispatcher’s return uses top-level `code` and does not include `error` or `message_drops`. Unequal abort codes, unequal budgets, and reserved effect names raise `V15_EFFECT_CONFLICT` or `V15_INVALID_EFFECT` and roll the transition back for every channel; delete the committed `payload.codes` abort. Unknown keys from a non-baseline handler stay on the §9.2 audit path only when they are not reserved effect names. `io.iteration` is compared only on phases that list `iteration` in §9.1. §4.5 and §4.9 pass the §9.1 key set. §4.9 gains: when `repl_exec/complete` returns `exec_result.result_kind=continue`, clear `invokes.return_value`, keep the `return` statement `done`, and write the continue history. Inner nulls are JSON null. Replace §4.1’s closed rollback list with “classification is §13”.

### 9. `manifest_digest` is defined as two different hashes
§3.13: “open 把当时的 `manifest_digest` 抄到 `invokes.manifest_digest`” (the singleton row). §4.3 and §8.5: `invokes.manifest_digest = md5(effective ceilings::text)`, which changes when `p_ceilings` tightens. §11.1 compares the baseline ceilings to `invokes.manifest_digest`. A tightened open then fails the next `v15_begin_llm` with `V15_MANIFEST_DIGEST`.

**Fix.** Replace the §3.13 sentence with: “`invokes.manifest_digest` is §8.5’s digest of this invoke’s effective ceilings. `governance_manifest.manifest_digest` is the digest of the singleton row only. They are equal only when `p_ceilings` is null and the manifest has not changed since open.”

### 10. A lexically invalid assistant message never becomes `Continue`
§6.1: an unclosed quote, comment, or dollar-quote rejects the whole message with `V15_DIALECT` and produces no statement list. §4.5.3: a bad `p_statements` array is `V15_VALUE_INVALID`, rollback-class, so the `call_started` attempt stays `leased`. §1.2 and §4.11: dialect errors end the iteration as `Continue`. Expiry then charges the attempt as `unknown` and the finding-1 retry burns `max_io_attempts`.

**Fix.** Split failure still calls `v15_settle_llm` with one element: `kind=plain`, `reject_code=V15_DIALECT`, `sql` the original text. The worker does not execute it. `v15_finish_exec` takes continue. NUL in the response uses that same single failed row, not a rollback of settle.

### 11. Child hook ordinals are assigned twice
§8.3 copies the parent’s `ordinal`. §8.6 assigns ordinals from 0 across a freshly installed baseline, then propagating hooks. A child whose baseline is longer than the parent’s (profile `baseline_hooks` changed, or governance rows reinstalled at 0..3) collides with the copied propagating ordinals. `PRIMARY KEY (invoke_id, ordinal)` aborts child open, which aborts same-iteration delegation.

**Fix.** Replace the §8.3 ordinal sentence with: “Child open does not copy parent ordinal numbers. Baseline is installed by §8.6 from 0. Propagating rows follow in the parent’s relative order with new contiguous ordinals. `state` is `{}`. Local rows are not copied.”

## P1

### 12. §1.2 sends ACL failures to a terminal invoke
“治理与 ACL 错误使 invoke 走终态（不变量 11、13、14）.” §13 classifies `V15_TOOL_UNAUTHORIZED` as statement failure. §4.1 leaves the invoke running.

**Fix.** “Iteration, recursion, I/O-attempt, and fatal budget failures end the invoke (§0.11, §0.13, §0.21). `V15_TOOL_UNAUTHORIZED` fails that statement only (§0.14, §13).”

### 13. `governance_io` cannot see `n`
§10.1 aborts when the next attempt’s `n > max`. §9.1 `llm_query/enter` `io` lists only `iteration`. Handlers have no kernel-table grants. The kernel check in §4.5.1 still enforces the ceiling.

**Fix.** Add required `io.next_attempt_n` on `llm_query/enter`. `governance_io` reads that field.

### 14. §0.25 vs the context-window warning
§0.25: when `recursion_available` is false the prompt does not name `bind_invoke`. §10.2 keeps the two-statement tail in the transient warning anyway (“警告文本不随深度改写”). That text is model-visible. The codex alternative’s ContextWindowWarning switched leaf invokes to finish guidance; use that behavior.

**Fix.** When `recursion_available` is false, the warning body stops after the `jaz.history` / `jaz.prior_history` sentences and does not contain `bind_invoke`.

### 15. §0.18 and §6.2 classify control-word mentions differently
§0.18 fails any non-canonical statement whose **text contains** `jaz.bind_invoke` / `jaz."return"` / `jaz."raise"` / unquoted return/raise. §6.2 step 2 matches the token stream outside strings, comments, and dollar quotes. The spawn backstop is still §0.9 (the function inserts nothing).

**Fix.** Point §0.18 at the §6.2 token rule so a literal inside a string is not `V15_INVOKE_FORM`.

### 16. Delivery name clash has two codes
§4.8: if `bind_name` is already `input`/`scope`/`tool`, the parent uses `V15_DELIVERY_CONFLICT`, then “走下面的非 fatal 失败”, and that procedure stores `V15_CHILD_ERROR`.

**Fix.** “Name collision uses the non-fatal delivery procedure with parent `error.code = V15_DELIVERY_CONFLICT`. The child stays `completed`. `V15_CHILD_ERROR` is only for a child whose own status is `failed`.”

### 17. Smaller cross-chunk corrections
- §10.1 “`V15_GOIFEST_DIGEST`” is `V15_MANIFEST_DIGEST`.
- §4.13: a suspend that did not bump `fence` returns `V15_INVALID_TRANSITION` (§4.7). `V15_STALE_FENCE` applies after the fence actually changes.
- §3.3: `statements.status=failed` means this statement will not run; the iteration stays `executing` until `v15_finish_exec`. Classifier-rejected rows are `failed` at settle, before any statement transaction.
- §8.4: a baseline `DELETE`/`UPDATE` raises `V15_BASELINE_IMMUTABLE` (§11.1), not `V15_GOVERNANCE_MISSING`.
- §0.24 outcome words are the lowercase §3.9 check values `completed` / `aborted` / `failed`.
- §8.2 depth-layer guard: “`llm`/`repl`/`protocol` IS NOT NULL”, not `jsonb_exists` on a SQL NULL.
- §3.12 counter key for forcing is `budget_forcing:<ordinal>` (§9.6), not the hook name alone.
- Header binds K1–K6, and no K text is in the tree. §18 already says the behavior authority is this file; delete the “K 裁定覆盖两轨残留冲突” sentence or check the rulings in beside this file.
- Privileges to add in §2: `USAGE` on schemas `jaz` and `v15` for `v15_repl` and `v15_worker`; `EXECUTE` on `pg_cancel_backend(int)` for `v15_worker` only. Cancel runs on a second connection; the connection inside the model statement is blocked. `CREATE EVENT TRIGGER` runs as the superuser setup session.
- §6.5 digest: the worker computes `logical_digest` after truncation and passes it to `v15_begin_llm` (finding 2). SQL stores that value and does not truncate a second time.
- §15: stages 6–7 implement §4 abort handling (`action`, `fatal`, `code`) even though the stub returns `proceed`. Stage 9 is the first gate that returns `abort`. `run_until_quiescent` is what stage 7+ tests call; stage 6 tests call the claim/begin/mark/settle/reclaim functions plus `FakeLLM.complete`, and do not require `v15_finish_exec`.

## P2

- Attempt `fence` starts at 1 on each new row (§4.5.1). “回收后再插入则使用新值” is the new `attempt_id`, not a global fence counter.
- §1.2’s `v15_settle_llm(fence, response)` is shorthand for the §4.2 argument list.
- §4.9 continue with a failed statement closes `repl_exec` as `completed`; §4.8 child error closes it as `failed`. Gates should assert those two outcomes separately.
- §6.5’s history paragraph is the frozen prompt. It is shorter than the R4 quotation in `v15-oracle-round2.md`. Gates compare §6.5, not the oracle paragraph.
- `md5(jsonb::text)` and `md5(sql)` are PostgreSQL 18.4 casts in database encoding UTF8. Python only mirrors them; it does not invent its own jsonb encoding.
- Deadlock (`40P01`) is outside the §4.1 rewrite into `V15_INVALID_TRANSITION`. Either add it beside lock timeout and serialization failure, or gates must accept `40P01`.
- §3.1’s status/lease/return_value implications are prose. A `CHECK` per terminal status keeps a buggy transition from committing `completed` with SQL NULL `return_value`.
- Parent/child `parent_invoke_id` and `parent_iteration` need `CHECK ((parent_invoke_id IS NULL) = (parent_iteration IS NULL))`.

## Verdict

**DO NOT FREEZE.** The delegation happy path and the error-code table’s `P1501`–`P1537` numbering are in good shape. Findings 1–11 are implementable only by changing this document first: an implementation that follows §4’s signatures, §4.10’s reclaim, §0.20’s `current_user` check, or §6.2’s blanket `CREATE` rejection cannot meet §0 or survive PostgreSQL 18.4.

### Oracle 2
- Status: Completed
- Provider: `codex`
- Model: `gpt-5.6-sol`
- Effective effort: `xhigh`
- Chat: `new-chat-oracle-2-16333E`



## Summary

The change adds the full PostgreSQL-native JAZ v15 behavioral specification together with the paper and oracle provenance. The intended architecture is coherent at a high level: durable statement-list execution, same-iteration child continuation, fenced out-of-transaction LLM I/O, relational bindings/history, and fail-closed governance. However, the assembled specification is not ready to freeze. Several cross-chunk contradictions make core paths impossible or unsafe as written, especially the `SET ROLE` execution model, scratch-schema ownership, Python prompt-rendering versus SQL transition signatures, bind-expression persistence, expired-attempt recovery, terminal statement handling, phase semantics, and budget accounting.

# P0 — Blocks implementation

1. **`docs/designs/v15-jaz-dev.md` §0.9, §0.20, §2, §4.1 — Kernel identity is specified as both `current_user` and `session_user`.**

   > “只有 `current_user` 为 `v15_worker` 时调用的 `v15_suspend_for_child` 可以创建子 invoke.”  
   > “内核转移 MUST 拒绝任何其他 `current_user`.”  
   > “转移函数的授权谓词是 `session_user = v15_worker`。`SECURITY DEFINER` 体内的 `current_user` 是 `v15_owner`……”

   A `SECURITY DEFINER` transition owned by `v15_owner` necessarily sees `current_user = v15_owner`; requiring `current_user = v15_worker` makes every transition fail. The later `session_user` rule is the implementable one.

   **Minimal fix:** replace the kernel clauses with:

   > Kernel transition authorization MUST require `session_user = 'v15_worker'`. Inside a `SECURITY DEFINER` transition, `current_user` is expected to be `v15_owner` and MUST NOT be used to identify the worker. Model-facing wrappers continue to require `current_user = 'v15_repl'`.

   Apply the same wording to §0.9, §0.20, and the §2 matrix.

2. **`docs/designs/v15-jaz-dev.md` §2, §6.4, §17 “DO 里的 SET” — `DO` can escape from `v15_repl` back to the privileged worker role.**

   > Worker logs in as `v15_worker`, then runs `SET LOCAL ROLE v15_repl`.  
   > “`SET ROLE v15_worker` 仍必须失败，因为 `v15_repl` 不是 `v15_worker` 的成员。”

   This misses `RESET ROLE` and `RESET SESSION AUTHORIZATION`. Because the session user remains `v15_worker`, model code inside a `DO` block can attempt to restore the session user rather than `SET ROLE v15_worker`. Once restored, it can call worker-only transition functions. A top-level classifier does not protect against utility statements or dynamic SQL inside `DO`.

   The same section acknowledges that `DO` can bypass the top-level `SET` ban, but post-statement `RESET ALL` is too late: privileged operations can occur before the statement returns.

   **Minimal safe fix:** reject `DO` in §6.2 until model statements run in a session whose `session_user` is itself unprivileged:

   > Add `DO` to the §6.2 utility-statement rejection list with `V15_DIALECT`. Remove the prompt claim that a `DO` block is supported and the related §17 gates.

   If retaining `DO` is essential, the execution topology must be redesigned around an unprivileged model session plus capability-token-protected prepare/complete functions. `SET ROLE` from a privileged worker session is not an adequate sandbox.

3. **`docs/designs/v15-jaz-dev.md` §0.26, §2, §4.1, §4.6.2, §6.2, §6.4 — Scratch DDL is simultaneously promised, rejected, and not granted.**

   Conflicting requirements include:

   - The prompt says the model may create objects in its scratch schema.
   - §6.2 rejects every `CREATE`, `ALTER`, `DROP`, and `TRUNCATE` before execution.
   - `v15_prepare_statement` grants only schema `USAGE`, not `CREATE`.
   - The scratch schema is owned by `v15_worker`, while terminal cleanup runs inside a function owned by `v15_owner`.
   - The event trigger attempts to transfer new objects to `v15_worker`.

   Therefore scratch `CREATE TABLE` cannot work. Additionally, `v15_owner` generally cannot create a schema owned by `v15_worker`, grant privileges on tables owned by that role, transfer objects to it, or drop its schema without an appropriate membership relationship. Those memberships are expressly absent.

   **Minimal fix:**

   - Make `v15_owner` the scratch-schema owner.
   - During an allowed DDL statement, transactionally grant and later revoke `USAGE, CREATE ON SCHEMA ...` to/from `v15_repl`.
   - Leave model-created tables owned by `v15_repl`; do not perform `ALTER ... OWNER` in the event trigger.
   - Replace the blanket DDL rejection with an explicit safe allowlist, such as scratch-local `CREATE/DROP TABLE`, `CREATE/DROP INDEX`, restricted `ALTER TABLE`, and `TRUNCATE`.
   - Require all other DDL to fail with `V15_DDL`.

   Alternatively, remove scratch DDL from the language and prompt everywhere, but that is a larger semantic reduction.

4. **`docs/designs/v15-jaz-dev.md` §6.4 — The security-definer event-trigger guard cannot observe `current_user = v15_repl`.**

   > “`v15_scratch_guard` 是 `ddl_command_end` 触发器，函数 `SECURITY DEFINER`。当 `current_user = v15_repl` 时……”

   Inside a `SECURITY DEFINER` trigger function, `current_user` is its owner, not the role that issued the DDL. Consequently, the stated branch will not run. Its `ALTER ... OWNER TO v15_worker` operation also has the ownership problems described above and may recursively fire event triggers.

   **Minimal fix:** make the event-trigger function `SECURITY INVOKER`, test `current_user = v15_repl`, and use a narrowly scoped security-definer read helper if it needs `exec_context`. Remove the owner-transfer operation. The trigger must implement a command-tag allowlist rather than merely checking `CREATE FUNCTION` and target schema.

5. **`docs/designs/v15-jaz-dev.md` §4.6.2 — `set_config(..., true)` inside a function with `SET search_path = pg_catalog` cannot reliably configure the later model statement.**

   > `v15_prepare_statement` performs `set_config('search_path', ...)` and sets `statement_timeout`, then returns; the worker executes the model statement afterward.

   Function-level configuration creates a GUC nesting boundary. A transaction-local setting made inside a function carrying a `SET search_path` clause is restored when the function exits; it must not be relied on to configure the caller’s subsequent query.

   **Minimal fix:** have `v15_prepare_statement` return the validated schema name and timeout only. The outer worker transaction must then execute, after the function returns and before changing role:

   ```sql
   SET LOCAL search_path = <validated-and-quoted-scratch>, pg_catalog;
   SET LOCAL statement_timeout = '<validated-ms>ms';
   SET LOCAL ROLE v15_repl;
   ```

   The worker deadline remains authoritative.

6. **`docs/designs/v15-jaz-dev.md` §4.3, §4.5.1, §6.5 — Prompt rendering is assigned to Python, but SQL transitions need data they cannot obtain.**

   > “渲染器是 `v15/protocol/render_prompt.py` 的纯函数.”  
   > `v15_open_invoke` writes rendered seed messages.  
   > `v15_begin_llm(p_invoke_id, p_fence, p_owner)` inserts the final request and logical digest.

   `v15_open_invoke` and `v15_begin_llm` are SQL functions and cannot invoke the Python renderer. Their signatures contain neither rendered messages nor a logical digest. §4.5 nevertheless says the worker computes and passes the digest in `send.io`, but there is no parameter through which to do that. Hook message effects can also alter the final request after any precomputed digest.

   **Minimal fix:** define one explicit boundary:

   - Add a worker-readable, security-definer prompt snapshot function.
   - Have Python render base messages after open.
   - Extend the signature to something like:

     ```text
     v15_begin_llm(
       p_invoke_id uuid,
       p_fence bigint,
       p_owner text,
       p_base_messages jsonb,
       p_input_chars int
     ) returns jsonb
     ```

   - Let `v15_begin_llm` apply enter/send message effects, form the final request, and compute the digest over a frozen canonical representation.
   - Move immutable seed-message insertion from open to the first successful begin-LLM transaction, so the same mechanism works for children.

   Without this change, neither roots nor SQL-created children can produce their specified prompts.

7. **`docs/designs/v15-jaz-dev.md` §3.3, §4.5.3, §4.7, §6.2 — The persisted statement does not contain the classified bind argument that suspension requires.**

   `p_statements` contains only:

   ```text
   {"sql","sql_digest","kind","reject_code"}
   ```

   The `statements` table has `bind_name` but no extracted JSON expression. §4.7 then requires the worker to execute exactly the classifier-extracted `<jsonb-expr>`, while `v15_suspend_for_child` receives neither the expression nor a parsed control payload. Re-parsing in SQL is prohibited.

   **Minimal fix:** add a nullable `arg_sql text` or `control_args jsonb` column to `statements`, and require control rows passed to settle to include:

   ```json
   {
     "sql": "...",
     "sql_digest": "...",
     "kind": "bind_invoke",
     "bind_name": "child",
     "arg_sql": "<exact second argument expression>",
     "reject_code": null
   }
   ```

   Validate all fields in `v15_settle_llm`; `v15_suspend_for_child` must read the stored `arg_sql`.

8. **`docs/designs/v15-jaz-dev.md` §4.10, §4.12 — Reclaim creates an unusable replacement attempt, and recovery may re-call an already-started attempt.**

   On expiry, reclaim inserts a new leased attempt for `p_owner`, but leaves the invoke leased to the old owner with an expired invoke lease. The subsequent invoke-reclaim branch explicitly skips invokes that still have a leased attempt. The new owner therefore cannot claim or mark the new attempt, and `v15_next_runnable()` cannot see the invoke.

   Separately, §4.12 says:

   > “attempt 已 `call_started` → 直接 FakeLLM 再 settle”

   A recovered worker cannot know whether the provider call already occurred. Reissuing the same started attempt contradicts the `unknown` invariant and can duplicate provider effects.

   **Minimal fix:**

   - Reclaim should terminalize the old attempt and return the invoke to `runnable`, bumping the invoke fence and clearing its lease.
   - It should not create the replacement attempt.
   - After a normal claim commits, a retry branch in `v15_begin_llm` should create attempt `n+1` on the same request without replaying `enter`/`send`.
   - A worker may call FakeLLM only immediately after it successfully changes `call_started=false` to `true` in its own control flow. Encountering a pre-existing `call_started=true` row must wait for expiry/reclaim; it must never re-call that attempt.

9. **`docs/designs/v15-jaz-dev.md` §11.1 versus §0.6 and §4.10 — Missing governance prevents expired attempts from ever becoming `unknown`.**

   > `v15_reclaim_expired` must call `v15_assert_manifest()` and `v15_assert_invoke_manifest()` before modifying control rows.

   If the manifest is missing or damaged, reclaim rolls back and leaves externally started attempts permanently leased. This violates the unconditional rule that expired started attempts become terminal `unknown`, leaks reservations, and leaves late-settlement behavior ambiguous.

   **Minimal fix:** split cleanup from admission:

   > Reclaim MUST always terminalize expired attempts and release/charge their stored reservations using attempt-local and invoke-frozen data. Manifest validation gates only creation of a replacement attempt or new external work. A missing manifest may leave the invoke non-progressable, but it MUST NOT block unknown finalization.

10. **`docs/designs/v15-jaz-dev.md` §4.6.2, §4.9, §9.4, §9.7 — Return/raise and BudgetForcing cannot complete consistently.**

    Two separate core failures exist:

    - Completing a `return` or `raise` statement only increments `resume_stmt`; trailing pending statements are then executed before finish, despite the claim that return/raise terminate the program.
    - BudgetForcing changes a committed return candidate to `continue`, but the old `return` statement remains done and `invokes.return_value` remains populated. That violates the stated continue precondition and leaves stale terminal state.
    - §9.7 says every candidate, including `raise`, passes through `repl_exec/complete`; §4.9 explicitly emits no `repl_exec/complete` for raise.

    **Minimal fix:**

    - When a return/raise statement completes, mark all later pending statements `skipped` and set `resume_stmt` to the end.
    - Always dispatch `repl_exec/complete` for `continue`, `return`, and `raise`.
    - If a valid `return → continue` effect is accepted, clear `invokes.return_value`, allow the current iteration to finish as `continue` despite its done return statement, and retain later statements as skipped.
    - Define the abort path from `repl_exec/complete` before writing terminal state.
    - Emit a consistent `repl_exec/complete` event for raise.

11. **`docs/designs/v15-jaz-dev.md` §4.5, §4.10, §11.3 — Budget reservations are not representable or consistently accounted.**

    The hook supports `reserve_calls > 1` and `reserve_cost`, but:

    - §4.5 and §4.10 add/subtract exactly one call.
    - §11.3 later uses the configured quantity.
    - `budget_pools` has no `cost_reserved` column, so a cost reservation is only checked, not persisted. Concurrent invokes can all pass the same cost check.
    - Attempt rows have no typed reservation fields; the values are buried in request JSON.

    **Minimal fix:**

    - Add `cost_reserved numeric NOT NULL DEFAULT 0`.
    - Add `pool_id`, `reserved_calls`, and `reserved_cost` to `llm_attempts`, or freeze equivalent typed columns elsewhere.
    - Reserve and release both axes atomically.
    - Use `reserved_calls` rather than literal `1` in §4.5, §4.10, and §12.
    - On unknown, move reserved calls to used calls and release reserved cost without inventing actual cost; a new attempt reserves afresh.
    - Validate `prompt_tokens >= 0` and `cost_usd >= 0`.

12. **`docs/designs/v15-jaz-dev.md` §6.1, §4.5.3, §4.11 — Whole-message splitter failures have no settlement path.**

    Unclosed strings/comments/dollar quotes are required to become a recoverable `V15_DIALECT` statement failure with no partial statement list. But splitting occurs before `v15_settle_llm`, and settle only accepts a valid statement array. If the worker simply raises, the provider call remains leased and is eventually marked `unknown`, which is incorrect: the response was known.

    NUL is worse: PostgreSQL text/JSONB cannot store `\u0000`, so the stated normal `p_response jsonb` path is impossible.

    **Minimal fix:**

    - Add an explicit program-rejection settlement path, or allow settle to receive `p_program_error`.
    - It must settle and charge the attempt, store a safe digest/audit representation, create a synthetic failed statement or equivalent iteration error, and continue with `V15_DIALECT`/`V15_VALUE_INVALID`.
    - Define a byte-safe or escaped audit representation for NUL-containing responses rather than requiring them in PostgreSQL `text` or `jsonb`.

13. **`docs/designs/v15-jaz-dev.md` §4.3, §9.1, §9.4–§9.7 — Several allowed phase outcomes have no state-machine semantics.**

    - `invoke/enter` allows `abort`, and §9.1 requires open to call it, but §4.3 does not define the resulting root/child terminal state, history, scratch cleanup, or parent delivery.
    - `llm_query/send` requires `input_chars` in §9.1, while §4.5 says its I/O contains only `iteration` and `logical_digest`.
    - Multiple abort codes are first converted into a `V15_EFFECT_CONFLICT` abort, then described as a rollback-class conflict. Those outcomes are mutually exclusive.
    - §9.7 claims §4.9 consumes aborts from `repl_exec/complete`, but §4.9 has no such branch.

    **Minimal fix:** add one normative transition table covering every permitted `(span, phase, action)` pair. In particular:

    - Define invoke-enter abort as a committed terminal close, including child delivery where applicable.
    - Require `llm_query/send.io` to contain `iteration`, final or provisional request digest, and `input_chars`.
    - Divergent abort codes must raise rollback-class `V15_EFFECT_CONFLICT`; they must not be committed as an abort code.
    - Define finish-time phase abort before mutating the candidate result.

# P1 — Must fix before freeze

1. **`docs/designs/v15-jaz-dev.md` between §8.6 and §9, and document header — Accidental oracle transcript material remains in the normative document.**

   The file contains:

   > `### Oracle 2`  
   > `Status: failed`  
   > `#### Partial response`

   The authority header also gives K1–K6 precedence, but no adopted K1–K6 source or definitions exist in the document or referenced file list.

   **Suggestion:** remove the entire oracle metadata block. Either include a concise adopted K1–K6 ruling section/path or remove the K1–K6 precedence sentence and state that the assembled document itself is the only post-oracle authority.

2. **`docs/designs/v15-jaz-dev.md` §4.1 and §13 — The “rollback classes only” list contradicts the error table.**

   > “回滚类只有：…”

   The list omits `V15_INVALID_EFFECT`, all effect conflicts, config errors, baseline immutability, delivery-structure conflict, and handler digest/shape errors, all classified as rollback-class in §13.

   **Suggestion:** replace the exhaustive list with:

   > Rollback-class conditions are exactly those marked 回滚类 in §13. This section names common examples but is not a second exhaustive list.

   Also correct the §10.1 typo `V15_GOIFEST_DIGEST` to `V15_MANIFEST_DIGEST`.

3. **`docs/designs/v15-jaz-dev.md` §1.2 versus §4.1 and §13 — ACL failure behavior is contradictory.**

   > “治理与 ACL 错误使 invoke 走终态.”

   Yet `V15_TOOL_UNAUTHORIZED`, model-side `V15_ROLE`, and native permission errors are statement failures followed by recoverable continue.

   **Suggestion:** replace it with:

   > Governance aborts may terminate the invoke as defined in §4 and §13. Model-statement ACL and tool-authorization errors are recoverable statement failures unless §13 explicitly classifies them otherwise.

4. **`docs/designs/v15-jaz-dev.md` §8.2 and §0.16 — `jsonb_exists` is applied to relational component columns.**

   `config_layers.llm`, `repl`, and `protocol` are nullable columns, not keys in a layer JSON object. Calls such as “component column 任一 `jsonb_exists`” are not meaningful without a key argument.

   **Suggestion:** specify:

   - Plain-layer column presence uses SQL `IS NOT NULL`.
   - A JSONB value of `null` is present but invalid because it is not an object.
   - Depth-partial key presence uses `jsonb_exists(partial, 'llm')`, etc.

5. **`docs/designs/v15-jaz-dev.md` §3.13, §4.3, §8.5, §11.1 — `manifest_digest` denotes two different values.**

   §3.13 says the singleton digest is copied into the invoke. §4.3 and §8.5 say `invokes.manifest_digest` is instead the digest of the invoke’s effective, possibly tightened ceilings.

   **Suggestion:** rename the invoke column conceptually to `ceilings_digest`, or explicitly state:

   > `governance_manifest.manifest_digest` digests the operator manifest. `invokes.manifest_digest` digests the invoke-effective ceilings and is not copied from the singleton row.

   If both facts are needed, store both columns.

6. **`docs/designs/v15-jaz-dev.md` §8.3, §8.6 — Propagating hook copying can duplicate hooks or collide ordinals.**

   Child open both re-resolves the current scope/layers and copies parent propagating `invoke_hooks`, while saying copied rows retain their ordinals. A changed number of child baseline hooks can collide with those ordinals.

   **Suggestion:** choose one source of truth. Prefer copying the parent’s frozen propagating hook rows, then assign new child ordinals after the child’s baseline rows while preserving relative order. Do not reinstall the same `extra_hooks` from current config layers.

7. **`docs/designs/v15-jaz-dev.md` §9.2–§9.3, §5.3 — Runtime handler validation is too narrow.**

   Runtime validation compares only `md5(pg_proc.prosrc)`. `ALTER FUNCTION` can change owner, security mode, volatility, language configuration, or search path without changing `prosrc`.

   **Suggestion:** explicitly adopt the richer digest requirement from the unadopted round-3 codex alternative: digest and revalidate identity arguments, return type, language, volatility, `prosecdef`, owner, `proconfig`, and `pg_get_functiondef(oid)`. Apply the same rule to tool handlers. Continue using `V15_HANDLER_DIGEST` for runtime drift.

8. **`docs/designs/v15-jaz-dev.md` §9.4 — Malformed optional-handler returns are silently isolated despite the closed-effect invariant.**

   A non-baseline handler returning an invalid object is treated like a thrown exception and discarded. That differs from a returned forbidden effect, which rolls back the phase.

   **Suggestion:** isolate only exceptions actually thrown during handler execution. A normally returned malformed shape, unknown key, reserved effect, or invalid phase effect must fail the phase with `V15_INVALID_EFFECT` or `V15_PHASE_CONTRACT`, regardless of channel.

9. **`docs/designs/v15-jaz-dev.md` §3.5, §9.4–§9.6 — Hook message IDs are not persisted or mapped.**

   Hook effects address messages by `id`, while `llm_messages` stores only `(invoke_id, msg_seq)`. Persistent messages lose their effect ID, and the spec never defines IDs for existing request messages.

   **Suggestion:** either add a stable `message_id text` column or define request IDs deterministically from stored rows, such as `db:<msg_seq>`, and preserve hook-provided IDs on persistent rows.

10. **`docs/designs/v15-jaz-dev.md` §0.25, §6.5, §10.2 — A recursion-disabled prompt can still advertise `bind_invoke`.**

    §0.25 says the prompt must no longer describe `bind_invoke` at maximum depth. §10.2 explicitly retains a ContextWindowWarning containing the two-statement delegation recipe when `recursion_available=false`.

    **Suggestion:** use two warning variants. At a recursion-disabled leaf, the warning must contain finish guidance only and must not include the name `bind_invoke`.

11. **`docs/designs/v15-jaz-dev.md` §0.2, §6.5, §9.4 — Hook-added prompt messages are visible but not programmatically addressable.**

    Persistent and transient hook messages are sent to the model, but neither `jaz.history` nor another model-facing relation exposes the exact request the model saw. This weakens the paper’s second property.

    **Suggestion:** add a read-only `jaz.prompt_messages`/`jaz.current_request` relation derived from the settled attempt request and current `exec_context`, including system, explicit-input, persistent-hook, and transient-hook messages. Alternatively, narrow the claimed paper property explicitly, but that would be a substantive fidelity deviation.

12. **`docs/designs/v15-jaz-dev.md` §3.6, §4.9, and the authoritative Round-2 R4 wording — Failed-turn `repl_output` disagrees with the frozen history contract.**

    Round 2 says `repl_output` contains printed output including error text. §4.9 stores only `capture` and places the error solely in `repl_exception` and the observation message.

    **Suggestion:** for failed continues, store the full formatted capture-plus-error observation in `repl_output`; retain `repl_exception` as structured metadata. Keep terminal return/raise output as `''`.

13. **`docs/designs/v15-jaz-dev.md` §5.5 versus §5.3 and §4.6.2 — Tool scratch writes are claimed but not authorized.**

    The table says a tool’s scratch writes remain committed, but the tool owner receives neither scratch `USAGE` nor table DML. The grants go only to `v15_repl`.

    **Suggestion:** remove the “tool scratch writes” row and define v15 tools as pure `(jsonb) → jsonb` functions over their arguments. Granting tool owners dynamic scratch access would substantially complicate isolation and should be a later feature.

14. **`docs/designs/v15-jaz-dev.md` §5.1 — The proposed `LANGUAGE sql` wrapper body uses procedural `IF`/`RAISE`.**

    SQL-language functions do not support the shown procedural body directly.

    **Suggestion:** use a `LANGUAGE plpgsql SECURITY INVOKER` wrapper for the role check, or call a dedicated SQL-visible assertion helper that raises the frozen error.

15. **`docs/designs/v15-jaz-dev.md` §4.1 — Serialization failures cannot always be rewritten to `V15_INVALID_TRANSITION`.**

    A serialization failure may be raised at transaction commit, outside the transition function, so no SQL function can guarantee rewriting its SQLSTATE.

    **Suggestion:** expose `40001` as an allowed transaction-level retry signal, or require the Python worker to classify it separately. Do not promise a server-side `P1523` rewrite for commit-time failures.

16. **`docs/designs/v15-jaz-dev.md` §15 — Stage databases are not independently repeatable because roles are cluster-global.**

    Each setup drops only a database, while stage-1 SQL uses ordinary role creation. Running another stage setup on the same PostgreSQL cluster will encounter existing `v15_*` roles.

    **Suggestion:** freeze a setup preamble that drops/recreates all v15 roles in dependency order after terminating stage connections, or require a fresh isolated PostgreSQL cluster per gate. Keep role cleanup outside the ordinary cumulative SQL files.

17. **`docs/designs/v15-jaz-dev.md` §17 “P15 探针” — The proposed runtime probe is not portable.**

    PostgreSQL does not expose its complete `errcodes.txt` through a normal catalog, and packaged installations need not include source-tree `errcodes.txt`.

    **Suggestion:** check a repository-pinned PostgreSQL 18.4 errcode snapshot at design/build time, and have runtime gates verify only `server_version_num` plus the ability to raise the chosen custom codes.

# P2 — Improvements

1. **`docs/designs/v15-jaz-dev.md` §3.15, §5.4, §6.5 — Do not promise implicit ordering from a view.**

   A view-level `ORDER BY` is not a reliable API ordering guarantee for arbitrary outer queries.

   **Suggestion:** change prompt text to instruct `ORDER BY iteration`, and describe the relation as keyed by iteration rather than inherently ordered.

2. **`docs/designs/v15-jaz-dev.md` §17 “return 探针” — The gate should not modify the repository.**

   Writing `v15/protocol/return_probe.txt` during a test leaves a dirty working tree and makes results installation-dependent.

   **Suggestion:** assert or print the probe result in the gate. If an artifact is desired, generate and commit it once as part of a design revision, not during every test.

3. **`docs/designs/v15-jaz-dev.md` §8.5, §4.5.1 — Canonical digest input remains underspecified.**

   `md5(jsonb::text)` is reasonable and deterministic within the frozen PostgreSQL version, but the profile/layer multi-column digest and Python-to-SQL logical request digest do not define one canonical envelope.

   **Suggestion:** define exact JSONB objects for every digest, including field names and absent/null treatment, and compute the final request digest in PostgreSQL from that envelope.

4. **`docs/designs/v15-jaz-dev.md` §3 opening and §10/§15 — “Later stages only add functions, views and grants” is too strong.**

   Stage 9 must insert optional `hook_defs`, replace governance handler bodies, and update handler digests.

   **Suggestion:** change the sentence to permit catalog seed DML and the specifically authorized `CREATE OR REPLACE` operations while still prohibiting new tables.

# Verdict

**DO NOT FREEZE.**

The same-iteration child continuation and relational addressability design can work, but the current document contains blocking authorization, transaction-boundary, recovery, prompt-construction, control-flow, and accounting contradictions. Resolve all P0 findings and the localized P1 inconsistencies before treating this as an implementable frozen contract.