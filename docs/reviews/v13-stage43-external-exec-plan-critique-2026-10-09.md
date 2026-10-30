# v13 Stage 43 plan critique

## Context / Scope

Compared `docs/plans/v13-stage43-external-exec-2026-10-09.md` with the generated plan in `prompt-exports/oracle-plan-2026-10-09-015516-v13-stage43-external-30a9.md`, from `# v13 Stage 43` (export line 174) through the References. The composed prompt and selected-file dump before that heading were context only. Oracle rulings in `prompt-exports/oracle-chat-2026-10-09-013449-untitled-chat-58124a-90ec.md` stay closed.

Spot-checks were limited to seams those texts specify: `r1_load_append_ok`'s contiguous walker, `allow()` / `git ls-files`, `v13_spawn_subsession`'s argument check, `v13_open_session`'s initial status, the `pg_stat_xact_user_functions` lookup in `measured_reject`, `v13_named_sql_writer` / `v13_spawn_writer_ok` on an unknown name, `v13_route`'s table grants, and the sql arm's exception path.

Not reopened: fixture classification only; the classifier does not call the three writers or become a third dispatcher; no file sink; no envelope change; route snapshot stays `controller` / 1; no registered identity, trusted bind, or task lease. Not treated as losses: the citation corrections in §1. Checked and holding, so not open seams: `v13_named_sql_writer` returns NULL and `v13_spawn_writer_ok` returns false for an unknown STABLE INVOKER name; `v13_route` already has `SELECT` on `sessions` and `v13_policies`. Do not add a writer branch or a new grant.

## Findings

### 1. Export content missing, weakened, or generalized

No implementation-bearing loss. The plan is the export plus four citation corrections. Do not restore the export's lines.

- `v13_route` `action=sql` is `v13/loop/advance.sql:151-153` (function starts `:110`), not `:146-149`.
- The sql arm is `v13/plan_arm/v13_plan_arm.sql:772-813` (`turn/route` write `:770`, `RETURN 'progressed'` `:813`), not `:770-822`.
- `files_through` is `v13/load.py:108-110`. `SQL_LOAD_ORDER`'s last item is `:59`. Not `:106-108`.
- `agentctl_steer` `param_spec` keys are `target` and `text` at `v13/agentctl_verbs/v13_agentctl_verbs.sql:345-357`. `mock_from_needed` is `v13/loop/test_loop.py:111`. `set_mock` is `:67`.

The export's "check the signature at implementation time" is not a dropped rule. The plan still stops if the live row or signature has changed. It only records what those lines are now.

### 2. Under-specified seams, contradictions, and bad references

**2.1 `ext_steer_sql_arm` cannot both own step 10 and obey its source ban.**

§3.8 introduces one local function, `ext_steer_sql_arm`, then lists steps 1–14 as its ordered procedure. Step 10 reads calls of `public.v13_external_exec_classify(uuid,jsonb)`. The same section says that function's source must not contain `v13_external_exec_classify`, and that the classification fixtures' source must not contain `v13_parse` or `v13_advance`. A file-wide substring scan is already forbidden, because the forbidden-token tuple would red itself. The split is not named. One function that contains both strings fails its own scan. A scan that is never attached to a function does not run.

Correction: `ext_steer_sql_arm` owns steps 1–9 and 11–13 only. Its source has `v13_parse` / `v13_advance` and not the classifier name. A sibling, the function that owns label `ext_steer_classify_uncalled`, reads the funcid count before calling `ext_steer_sql_arm` and again after, in the same uncommitted transaction. That sibling's source has the classifier signature and not `v13_parse` or `v13_advance`. `main` may call both. Do not scan the whole file.

**2.2 JSON null and SQL NULL are different binds. The table does not say so.**

§3.6 distinguishes `ext_shape_null_spec` (SQL NULL) from `ext_shape_json_null` (JSON null). Both expect shape. psycopg2 sends Python `None` as SQL NULL. `cur.execute("SELECT ...(%s::jsonb)", (None,))` does not produce JSON null. If both rows are bound that way, `ext_shape_json_null` passes without sending JSON null. A body that calls `v13_json_keys` before the step-1 typeof check then raises: `coalesce` does not replace jsonb null, and `jsonb_object_keys` rejects it (`v13/control/v13_control.sql:102-105`). The shape matrix stays green.

Correction: copy the sentinels in `v13/goal_workflow/test_goal_workflow.py:209-220`. SQL NULL is the literal `NULL::jsonb`. JSON null is the literal `'null'::jsonb`. Do not pass Python `None` for both. Nested JSON null (`verb` null) can stay `json.dumps`. Do not add a third failure object.

### 3. Details the code disproves

**3.1 Step 4 is not a call `v13_spawn_subsession` accepts.**

§3.8 step 4 says one child, `task` `routed child`, `tool_call_id` `tc-` plus 8 hex. It does not give the second argument. `v13_spawn_subsession` raises `v13: spawn args` unless the spec's keys are exactly `children` and `schema_version`, `schema_version` is numeric 1, and `children` is an array (`v13/spawn/v13_spawn.sql:330-335`). The working call is `spawn_one` (`v13/agentctl_verbs/test_agentctl_verbs.py:200-214`). A raise here is not the ready-count stop in step 5. `v13/spawn/v13_spawn.sql` is already on the blocked list, so editing it cannot make a wrong call green.

Correction: the second argument is `{"schema_version":1,"children":[{"tool_call_id":"tc-"+8 hex,"task":"routed child"}]}`. Take `child` from `children[0].session_id` of that jsonb, as text. Pass that text as `param::agentctl_steer::target`'s choice. Do not treat the function return as a uuid. Do not edit spawn. `v13_open_session` already inserts `status='ready'` (`v13/spawn/v13_spawn.sql:312`); the user message before spawn is what makes `next_seq >= 1`. Keep that order.

**3.2 "没有行则当作 0" is true only for a funcid lookup.**

§3.8 step 10 names `public.v13_external_exec_classify(uuid,jsonb)` and says a missing row counts as 0. `pg_stat_xact_user_functions` has `funcid`, `schemaname`, `funcname`, and `calls`. `funcname` is `v13_external_exec_classify`, not the signature. A predicate that matches the signature string against `funcname` finds no row before and after the call. The delta is 0 even if advance called the classifier. The cited precedent does not do that. It binds `funcid` to a `regprocedure` (`v13/agentctl_verbs/test_agentctl_verbs.py:438-441`).

Correction: `funcid = 'public.v13_external_exec_classify(uuid,jsonb)'::regprocedure`, then `coalesce(sum(calls), 0)`. A missing row before the first call is 0. Do not match the signature string against `funcname`. Keep the existing `v13_control_authorized(NULL, NULL)` probe. If that probe's delta is below 1, fail with `environment block: track_functions`. Do not downgrade the uncalled assertion. Do not `COMMIT` inside the window; `COMMIT` clears `pg_stat_xact_*`.

The contiguous-number negatives are not disproved. `r1_load_append_ok` walks the appended tail and expects `base+1`, `base+2`, ... (`v13/plan_arm/test_plan_arm.py:389-392`). `"goal_workflow": 45` fails that needle before duplicate-number. `"external_exec": 44` fails it because 42 is followed by 44. Keep both replaces. Do not change the needle to `duplicate stage number`.

### 4. Absent from both texts

**4.1 A green `progressed` does not mean the handler succeeded.**

The sql arm writes `turn/route` before the `CASE` (`v13/plan_arm/v13_plan_arm.sql:770`), then catches `OTHERS` from the dynamic `EXECUTE` and still `RETURN 'progressed'` (`:795-813`). A missing or raising handler leaves `action=sql` and `tool=agentctl_steer` in place. §3.8's stop rule covers a word that is not `progressed`. It does not cover a failed effect under a green word. Neither text says this.

Correction: do not add `effects` status, `tool/result`, or `write_targets` assertions. Do not edit `v13_plan_arm.sql` or `advance.sql` if a failed effect is visible. The closed proof remains the word, the route payload, and the classifier delta of 0. A green `ext_steer_sql_arm` is not handler success and is not a product entry.

No new cancellation path, owner, or lease is required. The classifier is a synchronous STABLE read with no product caller. A canceled statement aborts and writes nothing. Do not add a cancel token, a file sink, or an identity column.

### 5. Questions that change design or order

None. The spawn argument, the funcid lookup, and the sibling that owns `ext_steer_classify_uncalled` are fixed by the live functions. They do not reopen the seven-step order, the two-key failures, the single `agentctl_steer` proof, `controller` / 1, or the ban on the classifier calling the writers.

## Recommendations

1. Do not revert the four citation corrections in §1.
2. Split the uncalled measurement out of `ext_steer_sql_arm` (§2.1). Bind JSON null as `'null'::jsonb`, not Python `None` (§2.2).
3. Call `v13_spawn_subsession` with the `spawn_one` spec and read `children[0].session_id` (§3.1). Count classifier calls by `funcid`, not by a signature string (§3.2). Keep the `45` and `44` contiguous negatives.
4. Do not treat `progressed` as handler success, and do not widen the proof to make it so (§4.1).
