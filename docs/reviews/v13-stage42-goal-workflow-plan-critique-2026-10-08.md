# v13 Stage 42 plan critique

## Context / Scope

Compared `docs/plans/v13-stage42-goal-workflow-2026-10-08.md` with the generated plan in `prompt-exports/oracle-plan-2026-10-08-230335-deep-plan-v13-stage-9ebb.md`, from `# v13 Stage 42` through the References. The composed prompt and selected-file dump before that heading were context only. Parent contract is stage 42 of `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md`. Stage 43–45, D-3, and I1–I4 stay out of scope.

Spot-checks were limited to seams those texts specify: `v13_enqueue_effect`'s default argument, `serve`'s return, the quota policy and `v13_should_run_gate` order, `v13_goal_fingerprint`, `v13_triage_steer`, the spawn arm's early returns, `v13_workflow_resolve`, and `r1_phase_d_prefix_allowance`.

Not reopened: the six-key success object; three-key shape and missing objects; the rolled-back `quota_window` version 2 `allowed=0` proof; no `RealChain` construction. Not treated as losses: `goal_stopped` at `v13/govern/v13_govern.sql:438-446`; `serve`'s second value `accepted` via `v13/acl/v13_acl.sql:456` and `v13/loop_driver/driver.py:385`; the `test_plan_arm.py:1731` import guard; the human enqueue copied from `v13/agentctl_verbs/test_agentctl_verbs.py:213-217`; `v13_last_user_seq` returning -1.

## Findings

### 1. Export content missing, weakened, or generalized

No implementation-bearing loss. The texts differ only in the closed corrections above, the fingerprint hedge in §5, and one scheduling sentence. The export's "W1–W4 与文档同一次提交" is not a dropped rule: both texts already run the gates before the document closeout, and the plan's "W1–W6 … 两条 gate 都绿、文档收尾之后" matches §6. The export's four-argument `v13_enqueue_effect(..., NULL)` is the same call as the three-argument fixture copy. The fourth argument defaults to NULL (`v13/control/v13_control.sql:903-904`). `v13_pending_human` does not read `interaction_ref`. Do not restore the uuid `interaction_ref` or the explicit NULL.

### 2. Under-specified seams, contradictions, and bad references

**2.1 NULL `p_sid` is shape only if the comparison is NULL-safe.**

§3.2 step 5 says a SQL NULL `p_sid` makes `p_sid::text` NULL, so any canonical subject text "differs" and the return is the shape object, not missing. The shape matrix does not include this call. In PL/pgSQL, `IF subject <> p_sid::text` is not taken when the right side is NULL. The function then fails the existence check and returns missing. Predicates stay uncalled, so the zero-increment check does not catch the wrong reason. The function is not `STRICT`, so this call is in contract.

Correction: compare with `IS DISTINCT FROM`, not `<>`. Add one matrix row: `p_sid` is SQL NULL, the suggestion is otherwise legal, expect the shape object, and the three predicate deltas are 0. Do not declare `STRICT`.

**2.2 "该夹具的 SQL 日志" is not a defined log.**

§3.7 requires the human fixture's SQL log to contain no cancel or complete. The success script must call five-argument `v13_complete`. A process-wide log, or `driver.calls` after the success script, cannot be empty of that call. The human fixture runs first, but nothing records a fixture-local log.

Correction: the proof is the fixture function's AST, which §3.7 already requires for `v13_goal_stop` and `v13_enqueue_effect`. That function must not `Call` `v13_cancel`, `v13_complete`, `v13_agentctl_answer`, or `v13_agentctl_cancel`, and must not `UPDATE` the human row. Do not scan a process log. Keep the success script's `v13_complete`.

**2.3 "第 1 步的绑定" is the first advance, not layer resolve.**

§3.4 step 11 says the fold row with `effect_id IS NOT NULL` exists because "第 1 步的绑定已经写下 effect_id". Ordered step 1 only calls `v13_workflow_resolve`. The bind is the provider arm's `todo_delta`, apply id prefix `bind:`, written in the same `advance(root)` that enqueues the llm effect, before that arm returns `waiting` (`v13/plan_arm/v13_plan_arm.sql:309-328`). Query the fold at step 11, after `serve`. The bound `effect_id` is the llm effect and stays set after complete. Do not require it to be the `read_file_py` effect. A query before that advance returns NULL, and `v13_child_pointer` then raises `v13: workflow pointer: payload`.

### 3. Details the code disproves

**3.1 Repo-wide `git grep` cannot stay green.**

§3.7 proves the constant with `git grep -n GOAL_WORKFLOW_MAX_ADVANCE -- .` and requires the only hit to be the new test. `git grep` searches tracked files. This plan contains the identifier, and the parent contract contains it at `docs/plans/v13-three-layer-goal-workflow-plan-2026-10-06.md:238`. Both are untracked today, so the milestone gate can pass. Sixty-three files under `docs/plans/` are already tracked. Committing this plan, the parent, or a review that quotes the identifier makes the gate red. The parent's sentence is about the implementation tree, not about plan documents.

Correction: `git grep -n -F GOAL_WORKFLOW_MAX_ADVANCE -- v13`, and require every hit to be `v13/goal_workflow/test_goal_workflow.py`. Keep the separate check that the assignment `= 4` occurs once in that file. README still must not contain the identifier.

**3.2 Prefix NULL does not mean `v13_route` enqueued `low_intent_confidence`.**

§2.5 and §3.10 say a NULL prefix continues to `v13_route` and enqueues human with `reason=low_intent_confidence`. After the prefix call, `v13_advance` calls `v13_triage_steer` and returns that word if it is not NULL, before `v13_route`. On a root with no answered `triage` decision, `v13_triage_steer` enqueues human and returns (`v13/triage/v13_triage.sql:453-454`, reason `triage_fail_closed`). A child whose `v13_should_run` is false takes the same prefix NULL at `v13/plan_arm/v13_plan_arm.sql:161`.

Correction: keep the success failure as any `kind=human` row, or a `low_intent_confidence` event. Do not require `low_intent_confidence` as the only fall-through symptom. Do not edit `v13_triage_steer`, `v13_route`, or `_snap_with` to make the route sentence true. The fifth advance still must not run.

**3.3 A second word of `waiting` is not a FakeLLM failure.**

§3.4 step 10 says the second word is `progressed` because the spawn arm returns at `:508`. That return is real (`v13/plan_arm/v13_plan_arm.sql:508`). Two earlier returns in the same arm are `waiting` and do not spawn: `v13_should_run` false at `:486`, and `v13_spawn_batch_allowed` false at `:489`. §3.10 maps a non-`progressed` second word only to blank text or a bad `tool_call`. The seed allows one child (`v13/spawn/v13_spawn.sql:25`, `max_nonterminal` 8), and checkpoint 3 requires `admitted` true, so the happy path should not hit `:486`. A red word is still not permission to edit the FakeLLM or `v13_advance`.

Correction: if the wrapped word is `waiting`, stop and report which of `:486` or `:489` fired. Do not change `spawn_budget`, `v13_spawn_batch_allowed`, or the spawn arm. Do not treat `waiting` here as the prefix llm arm.

**3.4 An event-less session does not make `v13_goal_fingerprint` raise.**

§3.6 and §5 say to stop and report if fingerprint raises on the quiet `goal_stop` session, and not to add `user/message`. The function does not raise for that reason. It reads the session, calls `v13_probe` (`v13/govern/v13_govern.sql:58`), coalesces missing probe fields, and returns a hash. With no `goal/stopped` or `goal/resumed` event, `v13_goal_fold` returns `running` (`:116-117`). `v13_goal_stop` then appends `goal/stopped` when the caller is the control operator and no effect is `ready`, `claimed`, or `unknown`.

Correction: run the fixture as written. Do not add `user/message`. Do not treat "no events" as a stop. Stop only if `v13_goal_stop` actually raises, and do not edit `v13_govern.sql`.

### 4. Absent from both texts

**4.1 `admitted = should_run AND quota_eligible` is not observable under version 3.**

The closed `allowed=0` proof must stay: `quota_eligible=false`, `should_run=false`, `admitted=false`, `gate="quota_window"`, then roll back. Under `should_run` version 3, `quota_window` is `block` and is evaluated before `goal_stopped` (`v13/govern/v13_govern.sql:429-432`). Quota failure therefore makes `v13_should_run` false. A body that sets `admitted` to `should_run` and still returns the real `quota_eligible` boolean passes that proof, the `goal_stop` proof, the discard proof, and the returned-triple invariant. Those fixtures never have `should_run` true and `quota_eligible` false.

Correction: in a second SAVEPOINT, before the success script, insert an inactive `should_run` version whose only gate is `{"id":"quota_window","effect":"shadow"}`, and activate `quota_window` version 2 with `allowed=0`. Deactivate the previous active row of each name before activating the new one. Expect `should_run=true`, `quota_eligible=false`, `admitted=false`, `gate=null`. Roll back. Re-check that `quota_window` version 1 and `should_run` version 3 are the active rows. Do not replace the closed `gate="quota_window"` proof. Do not leave either version active. Do not `UPDATE` `value`.

No new cancellation path is required. The script's exception path already rolls back the open transaction and drops only the database this process created.

### 5. Questions that change design or order

None. The NULL comparison, the grep scope, the fall-through symptom, and the shadow-gate fixture are fixed by the live functions. They do not reopen the six-key object, the `allowed=0` proof, or the ban on constructing `RealChain`.

## Recommendations

1. Compare `subject_session_id` to `p_sid::text` with `IS DISTINCT FROM`, and add the NULL `p_sid` shape row (§2.1).
2. Prove the human fixture by AST, not by a process SQL log (§2.2). Query the bound todo only after the first `advance(root)` (§2.3).
3. Scope the constant grep to `v13/` (§3.1). Treat a non-`progressed` second word as `:486` or `:489`, not as a FakeLLM bug (§3.3). Keep any human row as the fall-through failure; do not require `low_intent_confidence` (§3.2).
4. Run `v13_goal_stop` on the event-less session. Do not add `user/message` (§3.4).
5. Add the rolled-back shadow `should_run` fixture beside the closed `allowed=0` proof. Do not replace that proof (§4.1).
