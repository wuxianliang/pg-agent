# v13 Stage 40 plan critique

## Context / Scope

Compared `docs/plans/v13-stage40-agentctl-observe-2026-10-08.md` with the generated plan in `prompt-exports/oracle-plan-2026-10-08-185901-stage-40-agentctl-ob-9ed2.md`, from `# v13 Stage 40 / S1：agentctl_observe 开发计划` through the delivery conclusion. The composed prompt and selected-file dump before that heading were context only.

Spot-checks were limited to seams the two texts actually specify: parse entry, spawn argument/return, pointer writer arguments, advance security, and the plan_arm closure functions. Settled items are not reopened: S1 only; hints are `{session_id, hint}`; no-call proof is `pg_stat_xact_user_functions` and hard-fails if counts are unavailable; database connection follows `v13/fair_claim/setup_db.py` with no extra Unix-socket check; relative to `fb295ac`, the append is exactly `fair_claim/39` then `agentctl/40`.

## Findings

### 1. Export content missing, weakened, or generalized

No unsettled implementation-bearing content was dropped. The written plan is the generated plan plus three settled corrections (append pair, connection, and the confirmation paragraph) and one tighter spawn-argument sentence. That sentence is kept; its misreading is finding 3.

Do not treat the removed Unix-socket check or the removed 36–38 “append” rows as weakenings.

### 2. Under-specified seams, contradictions, and bad references

**2.1 Policy `COMMIT` disarms the call counter.**

`§3.6` step 6 commits `agentctl_observe_probe`. `§3.5` arms `track_functions=all` as transaction-local and proves availability with one rollback-able probe. `SET LOCAL` ends at that commit. `pg_stat_xact_user_functions` only counts the current transaction, and only while the GUC is on. A probe that ran before the commit does not arm later measurement transactions. Those transactions then see no rows. A calls-delta of 0 can false-pass “observe/hint/writer were not called” unless the hard-fail probe runs again in the same transaction as the measured call.

Correction, without changing the settled counter view: on every connection that measures calls, `SET track_functions = all` for the session, then run the hard-fail probe inside the measurement transaction before the call. Session-level `SET` survives the policy commit; `SET LOCAL` does not. Do not reuse a pre-commit probe.

The second baseline the risk section calls “两个基线” but never names is `78e77c710bf06a0a1c771b822a3837c5db4c66d0`, already required by `r1_phase_d_prefix_allowance` in `v13/plan_arm/test_plan_arm.py:409`. Do not substitute `HEAD` for either commit.

**2.2 The ten synthetic cases have no host.**

`allow()` inside `r1_phase_d_prefix_allowance` rejects paths. `r1_load_append_ok` rejects load lines. Cases 2, 3, 4, and 10 must be built as tracked-set mutations and passed through `allow()`. Cases 5–9 must call `r1_load_append_ok` on an in-memory `load.py` whose append relative to `fb295ac` is the legal pair plus one mutation. Case 1 must pass both. Putting the list in only one function leaves the other closure untested. Existing negatives stay where they are.

### 3. Details the code disproves

**3.1 The routed fixture never reaches `remaining=0`.**

Both texts set `typesafe.mock_response` and then call `v13_parse`. The live function is the stage 10 replacement, `v13/filter/v13_filter.sql:485-489`. Its first CTE calls `v13_guc_required('typesafe.provider')` and `v13_guc_required('typesafe.model')`. `v13/envelope/v13_envelope.sql:321-327` raises `V3002` when either setting is missing or blank. No load script sets a database default. `v13/economy/v13_economy.sql:358` calls that envelope before any remaining/failed logic, and no later stage replaces `v13_parse`.

Correction: before any parse, copy the session-level pair from `v13/spawn/test_spawn.py:136-137`:

```text
set_config('typesafe.provider', 'mock', false)
set_config('typesafe.model', 'jev-mock', false)
```

`is_local=false` is the pattern that already passes parse gates. `jev-mock` matches `mock_from_needed`. Do not add `endpoint` or `api_key`; a non-empty `mock_response` is what keeps the ask off the network. Do not put these `set_config` calls in production SQL.

**3.2 `根max(seq)` is not a legal pointer argument on a fresh root.**

`v13/workflow_bind/v13_workflow_bind.sql:148-150` raises `v13: workflow pointer: payload` if `p_up_to_seq` is NULL or negative. `max(seq)` over a root created by `v13_open_session` is NULL: that function inserts no event. The direct pointer fixture never requires a root event. The payload field is not checked against real events; any `bigint >= 0` is accepted.

`v13_plan_map_root` (`v13/plan_contract/v13_plan_contract.sql:25`) is not a plan-row lookup. It walks `parent_session_id` and returns the root, so that argument is valid once the child row exists. Passing it does not create the missing `up_to_seq`.

Correction: pass `0`, or append one event on the root and only then use `max(seq)`. Do not call `v13_child_pointer` with `max(seq)` of an event-free root. Do not insert the pointer event directly.

**3.3 The spawn citation is the argument check, not the return.**

`v13/spawn/v13_spawn.sql:331-334` rejects any argument key set other than `children` + `schema_version`. That part of the plan is right, and the “no third key” rule should stay. The created-path return at `:459-463` is `{replay_kind, parent_session_id, children, reservation}` and has no `schema_version`. Asserting the return key set from the plan sentence fails a successful spawn. Read `children[0].session_id` from that return.

Related, and already satisfied by the written order: `:347-348` raises `v13: spawn requires prefix` when `next_seq < 1`. The user/message must stay before spawn. Do not clear a ready/claimed effect to get past advance; direct spawn does not insert an effects row.

### 4. Absent from both texts

**4.1 Empty success does not prove `v13_observe` ran.**

`v13_observe` returns zero rows, without an error, when any id is unauthorized (`v13/observe/v13_observe.sql`, the authorized loop before the read loop). A wrapper that returns the empty success object locally, without calling `v13_observe`, satisfies `actl_actor_gate` and `actl_observe_no_hint_on_empty`. Those assertions require hint calls `= 0`, and observe calls `= 0` only on the shape path. They never require observe calls `= 1` on unauthorized, self, or missing-target inputs. That is the path the closed rule uses to keep kinship inside `v13_observe` rather than in a local filter.

Correction: in the same count window, assert `v13_observe` calls `= 1` for those three empty-success cases and for one authorized success, and `= 0` for shape. Do not add a spy and do not replace the function.

**4.2 The routed fixture does not prove the `v13_route` grant.**

`v13_advance` at `v13/plan_arm/v13_plan_arm.sql:332-335` is `SECURITY INVOKER`. The gate connects as the database owner, so the sql arm bypasses `GRANT`. `actl_acl_closed` is the only assertion that `v13_route` can execute the new function. It does not say the call must be a legal authorized observe. A shape-failure call only needs `EXECUTE` on the wrapper plus `PUBLIC` execute on `v13_json_keys` / `v13_canonical_uuid`. It does not touch `v13_observe`, `v13_scheduler_hint`, or `events`.

The grants already exist (`v13_observe` and `v13_scheduler_hint` are granted to `v13_route`; `v13_route` has `SELECT` on `events`). This does not change the function. It changes the assertion: as `v13_route`, call a legal spec with one authorized child and `hint=true`, and expect `ok=true` with one row and one hint element. Keep the recall `42501` call.

Cancellation needs no new wrapper behavior. The function has no wait, and the sql arm’s existing `query_canceled` branch stays untouched.

### 5. Questions that change design or order

1. Will `actl_acl_closed` use a second connection, as `v13/observe/test_observe.py:545` does after `commit`? If yes, the probe policy must be committed before that connection inserts a session, and that connection needs its own `track_functions` arming and hard-fail probe. If every case stays on one connection and uses savepoints, the policy `COMMIT` in `§3.6` step 6 is unnecessary and is what clears `SET LOCAL`.

No other open question changes the function, the load append, or the file closure.

## Recommendations

- Add the two session-level GUC settings before every `v13_parse`. Do not add a network endpoint.
- Re-arm `track_functions` in the measurement transaction. Keep `pg_stat_xact_user_functions` and the hard-fail. Do not add a spy.
- Pass `0` (or `max(seq)` only after a real root event) to `v13_child_pointer`. Keep the writer call outside the observe window.
- Bind observe calls `= 1` on empty-success authorization failures, and make the `v13_route` success call an authorized `hint=true` observe.
- Host the synthetic cases in the function that actually rejects that input.
- Do not remove the shape matrix, the exact four paths, the spawn argument key set, or the fixture order. Do not reopen the settled connection, hint-element, counter-view, or 36–38 append decisions.
