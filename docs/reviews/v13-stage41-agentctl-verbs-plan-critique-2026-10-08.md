# v13 Stage 41 plan critique

## Context / Scope

Compared `docs/plans/v13-stage41-agentctl-verbs-2026-10-08.md` with the three generated plans in `prompt-exports/oracle-plan-2026-10-08-204117-stage41-agentctl-f15-41e6.md`, from each `# v13 Stage 41` heading through that lane's delivery text. The composed prompt and selected-file dump before `## Generated Plan` were context only.

Spot-checks were limited to seams those texts actually specify: complete's human channel, the sql-arm subtransaction, catalog volatility exemption, the DDL revision bump, `v13_context_fresh`, and the stage 40 fixture the plan copies. Settled items are not reopened: workspace may be written while `actl_steer_body_consumed` stays red; policy check before `v13_control_authorized`; answer success keys are `schema_version`, `caller`, `target`, `effect_id`, `outcome`; ban `EXCEPTION ... WHEN` capture blocks, not the substring `EXCEPTION`; no open-ended `42501` grant repair.

Verb-specific error strings in lanes 1 and 2 are not a required restoration. The plan's unified needles still separate shape, policy, kinship, effect, and non-`accepted`. Lane 2's answer object that drops `caller` is the settled rejection, not a hole in the plan.

## Findings

### 1. Export content missing, weakened, or generalized

**1.1 `writer_ok`'s security conjunctions are required and unproved.**

Lane 1 requires a rolled-back negative variant for each security attribute, so `v13_spawn_writer_ok` and the catalog insert guard still reject. The plan states the conjunctions in §3.6 and then, correctly, refuses to scan `writer_ok` in `actl_no_io` because the denylist literals live in that body (`v13/spawn/v13_spawn.sql:1678-1685`). A happy-path `writer_ok = true` still passes if the replacement drops the IO scan, the ACL check, or the volatility check.

Correction: in a savepoint, create a throwaway `(uuid, jsonb) → jsonb` function whose name is not a `tools.handler`. One variant per conjunct (banned substring, owner, `provolatile`, `proconfig`, PUBLIC `EXECUTE`, `v13_route` `EXECUTE`, signature). Expect `writer_ok` false and a tools `INSERT` rejected. Roll back. Do not replace `v13_tools_guard` or `v13_tools_catalog_frozen`. A name that is already a sql handler bumps `tools_revision` (`v13/schema/v13_core.sql:1074-1078`) and stales every later parse on that connection.

**1.2 The watermark proof no longer attributes `stale` to the steer.**

Lane 1 takes the target snapshot only after the user message and the in-flight effect exist, then steers, then advances that saved snapshot, and requires the stale call itself to add no business row. §3.10 collapses this to "old parse snapshot returns stale; request/token unchanged." A user message appended after the snapshot also moves `max_event_seq`. The child's `v13_parse` is a different session from the root fixture that arms the GUCs.

Correction: finish every child write, then parse, then save `request`, `request_hash`, `attempt_no`, `fence`, and lease columns, then steer, then `v13_advance` the saved snapshot. Expect `stale`, `next_seq` increased only by the steer, and those effect columns unchanged. The session must already have `typesafe.provider` and `typesafe.model` set; the live envelope raises `V3002` otherwise (`v13/filter/v13_filter.sql:488-489`, `v13/envelope/v13_envelope.sql:321-327`). That stale result is not body consumption.

**1.3 `actl_controller_observe_routed` can pass without using the new bands.**

Lane 1 runs the existing observe route on `controller` / 1 so the sixteen pass bands are actually consulted. The plan names the assertion and the policy, but not parse → advance. A threshold row count, or a direct `v13_agentctl_observe` call, never reads `thresholds`.

Correction: copy `actl_observe_routed` (`v13/agentctl/test_agentctl.py:693-698`), with the root opened on `controller` / 1, stated noul `0.9` for `ids` and `hint`, the post-parse context update, then advance. Expect `action=sql`, `tool=agentctl_observe`, and `request.params` not `{}`. Do not change the stage 40 wrapper.

### 2. Under-specified seams, contradictions, and bad references

**2.1 The number-`1` fixture does not raise if `interaction_ref` is text-extracted.**

§3.4 says copy `interaction_ref` from the locked `effect.request`. Lane 2 writes `effect.request->>'interaction_ref'`. `v13_complete` raises only when the submitted jsonb type is not string, or the text extraction differs (`v13/acl/v13_acl.sql:343-346`). `->>` turns JSON number `1` into text `'1'`, which equals `request->>'interaction_ref'`. Complete then accepts. The claim commits inside a successful call, so the fixture no longer proves post-claim rollback.

Correction: copy `request->'interaction_ref'` (jsonb), not `->>`. Assert the exception text starts with `v13: human interaction_ref mismatch`. Exact equality fails: the live message is `v13: human interaction_ref mismatch (submitted=%, current=%)`. SQL `OR` does not short-circuit, so a number still formats as `submitted=1, current=1`. Do not assert that the two sides differ. Do not accept a bare exception plus `ready`: a pre-claim `v13: agentctl answer` leaves the same row.

**2.2 "Not exactly accepted" is not a NULL-safe test.**

Lane 1 requires a comparison that treats SQL NULL as failure. §3.4 and §3.5 say "不是恰好" and "其他文本". In PL/pgSQL, `IF v_word <> 'accepted'` and `IF v_word NOT IN ('accepted', 'replay')` are not taken when `v_word` is NULL. The function would then return success.

Correction: `v_word IS DISTINCT FROM 'accepted'` for answer. For cancel, raise unless `v_word` is exactly `accepted` or exactly `replay`, using `IS DISTINCT FROM` on both. Do not use `<>` or `NOT IN`.

**2.3 The superuser non-child case contradicts policy-first unless the caller is `controller` / 1.**

§3.2 maps a missing caller row to `v13: agentctl policy`. §3.10 says a superuser calling on a non-child gets `v13: session not found`. The second message is reached only after the policy check passes. A `default` / 1 caller fails the assertion and looks like an order bug.

Correction: that case uses a `controller` / 1 caller and a target that is not its direct child. `default` / 1, and the test-only `controller` version 2, stay in `actl_policy_fail_close`.

**2.4 The threshold column list cannot be inserted as written.**

§3.7 copies `signal`, `band_no`, `lo`, `hi`, `action`. The primary key and the draft-parent guard also require `policy_name` and `policy_version` (`v13/schema/v13_core.sql:488-496`, `:527-536`). An `INSERT ... SELECT *` that keeps `default` / 2 either hits the primary key or is rejected because that version is already frozen.

Correction: use the shape at `v13/agentctl/test_agentctl.py:303-308`, with the identity rewritten to `('controller', 1)`. §2.4 already points at that function; §3.7's column list does not replace it.

### 3. Details the code disproves

**3.1 Replace-before-parse is required; the digest reason is not.**

§3.10 part 4, and lane 1, say the fault definition must exist before parse so the frozen handler digest matches the call. `handler_digest` is an audit key. It does not participate in step 0 (`v13/resolve/v13_resolve.sql:188-191`). `CREATE OR REPLACE` of a `(uuid, jsonb)` function whose name is a `tools.handler` runs `v13_tools_ddl_bump` and increments `tools_revision` (`v13/schema/v13_core.sql:1068-1078`). Step 0 compares that revision (`v13/plan_arm/v13_plan_arm.sql:360-368`). A post-parse replace returns `stale` even when the live body is the one advance will execute. The sql arm does not compare digest at `EXECUTE`.

Correction: keep the replace before parse, inside the outer savepoint, because of `tools_revision`. Roll back before any success parse. Do not move the replace after parse, and do not treat a digest mismatch as the gate.

**3.2 Lane 1's pre-parse context update is the failing order.**

Lane 1 §3.12 step 7 says not to copy stage 40's post-parse `UPDATE`, and to stop rather than move it back after parse if parse invalidates it. `v13_context_required` includes the decision count. Parse inserts decisions, so a pre-parse write is already stale at advance. `v13_context_fresh` compares the live required token to `sessions.context_active_revision` (`v13/manifest/v13_manifest.sql:207-208`). That column is not one of the seven watermark keys. The green order is parse, then the update, then advance (`v13/agentctl/test_agentctl.py:693-698`). The plan's §3.9 step 9 is the correction. Do not restore lane 1.

**3.3 `SET ROLE v13_route` does not prove table grants.**

Lane 1 requires a successful call of all three wrappers as `v13_route`, and says a superuser success must not mask missing table privileges. The wrappers are `SECURITY DEFINER` owned by `v13_spawn_owner`. Inside the body, `current_user` is the owner, including when the caller is a superuser. `SET ROLE v13_route` proves `EXECUTE` on the wrapper. Owner `UPDATE` on `effects` is already required for the direct answer success to return. The plan's one authorized steer, plus `EXECUTE` checks on all three signatures, is the grant proof. Do not add two more role successes in order to prove table ACL.

**3.4 The terminal-replay setup is not blocked.**

§3.5 says to stop and report if `UPDATE sessions.status` to `cancelled` is rejected, and not to switch the wrapper to closeout. `v13/acl/test_acl.py:502` already performs that update. The unknown-wall trigger returns immediately for `completed` / `failed` / `cancelled` (`v13/control/v13_control.sql:598-600`). Use that update for the separate `replay` case. Do not halt on the hedge, and do not call `v13_closeout` from the wrapper.

### 4. Absent from both texts

**4.1 A missing context update fails as `waiting`, not as an exception.**

`v13_advance` at `v13/plan_arm/v13_plan_arm.sql:693-705` enqueues `context_refresh`, calls `v13_send_work`, sets the root `status` to `waiting`, and returns `waiting`. Neither the plan nor the lanes name that symptom. An implementer who omitted §3.9 step 9 will see a human-looking wait and can "fix" it by editing triage, envelope, or advance. Those files stay frozen. Add the update. Do not treat `waiting` here as `triage_fail_closed`.

No new wrapper behavior is required for statement cancel. The sql arm's existing `query_canceled` branch stays untouched. The wrappers have no wait.

### 5. Questions that change design or order

None. The copy operator, the revision bump, and the post-parse context update are fixed by the live functions. They do not reopen policy-before-authorization, the answer return keys, or the red D-3 gate.

## Recommendations

1. Add the rolled-back `writer_ok` negative variants in §1.1. Keep `actl_no_io` off that function body.
2. Restore the watermark order in §1.2, including the child's parse GUC, and make `actl_controller_observe_routed` a real sql-arm run (§1.3).
3. Copy `interaction_ref` with `->`, and use `IS DISTINCT FROM` for both return-word checks (§2.1, §2.2).
4. Pin the superuser non-child caller to `controller` / 1, and insert thresholds with the stage 40 `SELECT` shape under `('controller', 1)` (§2.3, §2.4).
5. Keep replace-before-parse and post-parse context alignment. Change the reasons to `tools_revision` and `v13_context_fresh`, not digest and not lane 1's stop (§3.1, §3.2, §4.1).
