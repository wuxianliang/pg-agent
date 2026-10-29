# Cordis v2 DP6 W1 — Oracle semantic admission and `ensure` design record

Date: 2026-10-28. Worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD
`78e21500cc716203ae5d978d7e2948aa4bcf66e0`. Authority: `docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md`
§4.1–4.4, `docs/reviews/cordis-v2-dp6-conformance-matrix-2026-10-28.md` §W1 semantic admission, and the
B0 deviation ledger. This record resolves the two B0 proof points **before** W1 code is written.

## Oracle provenance

| Item | Value |
|---|---|
| Oracle group | `D2EED4FF-ECCC-44C2-803A-7CA520DFC462` |
| Primary lane | `codex` / `gpt-6.1-sol-xhigh`, chat `new-chat-AB0DCA` |
| Additional lane | `openCode` / `kimi-code-plan-cn/k3.1-pro`, chat `new-chat-oracle-2-BD1ACF` |
| Exported response | `prompt-exports/oracle-chat-2026-10-28-232411-new-chat-ab0dca-d52e.md` (gitignored; retained locally) |
| Question scope | current 40/41/42/50 SQL, `dp1/setup_db.py` role fixture, B0 matrix/ledger, plan §4.3.1 |

Both lanes returned **admit-with-corrections**. The corrections are material: B0's withdrawn draft
(failure check before teardown; every closing/p6 gap mapped to `ensure_no_work`) is **not** used.

## Adjudication

`ensure` is admissible as a fourth `command_reconcile` action on the existing exact payload
`{fiber_id, action, expected_control_seq}`. It adds no command kind, interpreter, table, column,
error code, or second writer. It is a **wake-up probe**: on genuine work it commits only the existing
P0 `schedule` delta (empty domain, empty events, exactly one ordinal-0 `advance` successor); otherwise
it returns an uncached zero-write `stale_generation` diagnosis, or raises `0A000` for a real invariant
fault. The existing `advance`/`interpret_reconcile`/`reconcile_branch`/`p0_delta`/`validate_domain`
path remains the single decision and write boundary.

The two B0 blockers are resolved as follows.

1. **Teardown dominates failure by construction.** Failure suppression is consulted only after the
   recursive `advance` classification returns `p1` (the sole activation branch). An active fiber that
   is no longer live returns `leave`; a closing episode returns `p6`; neither path reads
   `fibers.failure`. Therefore a committed same-generation activation failure cannot suppress an
   already-started teardown.
2. **A missing atomically required successor is an invariant fault.** Two independent predicates
   prove the obligation, both evaluated before slot/no-work classification:
   - persisted-emission evidence: a succeeded command parent's committed `requests.response->'emitted'`
     names an effect row that does not exist;
   - phase evidence: a `reloading` episode with no open reconcile slot, or a `closing` episode that
     already persisted a `contributions_released`/`pins_released` event for that episode and has no
     open reconcile slot.
   Both raise `0A000 / missing_reconcile_successor`. Legitimate `successors: []` deltas (leave,
   close, `fiber_control`, terminal dispose) persist an empty `emitted` and cannot false-positive.

## Final ordered `ensure` algorithm

Executed inside `advance` under `pg_advisory_xact_lock(24,1)`, after replay-first and the locked
closure re-check. `f` is the target fiber, `inst` its install, `ep` the current episode.

**A. Current-episode consistency (fault before no-work).**
- If `f.current_episode_id IS NOT NULL`: the episode must exist, belong to `f`, and have
  `closed_at IS NULL`; otherwise `0A000 / phase_drift`.
- If `f.current_episode_id IS NULL`: no open episode may exist for `f`; otherwise `0A000 / phase_drift`.
- If `f.current_episode_id IS NULL AND f.retire_started_at IS NOT NULL`: `0A000 / phase_drift`.
  `episode_close` clears `retire_started_at`; the state is not reachable through the supplied
  transitions. The additional Oracle lane preferred `owner_closing`/`ensure_no_work`; the stricter
  fault is adopted so the state cannot be silently normalised.

**B. Persisted-emission invariant.** If `ensure_emission_missing(f.id)` (below) is true:
`0A000 / missing_reconcile_successor`. This runs before slot/terminal/no-work so a fresh slot cannot
hide older atomic damage.

**C. Required-continuation invariants.**
- `reloading` and no ready/claimed `command_reconcile` slot for `f`: `0A000 / missing_reconcile_successor`.
  A `ready` slot is the atomic successor; a claimed `command_reconcile` is unreachable under the
  current authorization (commands are never claimable), but is accepted by the same slot predicate.
- `closing` and no slot and an existing `contributions_released` or `pins_released` event for
  `ep` (entity `fiber`, entity id `f`, payload `episode_id = ep.id`):
  `0A000 / missing_reconcile_successor`. A closing state immediately after `episode_closing` has no
  release event and is legitimate.
- A closing state whose last command was a `retry` (which emits a successor) is already covered by B.

**D. Generation fence.** `expected_control_seq IS DISTINCT FROM f.control_seq` →
`stale_generation / reconcile_generation` (existing stale semantics; zero write).

**E. Slot no-work.** `reconcile_slot_open(f.id)` → `stale_generation / ensure_slot_present`.
The non-reserved ensure effect is not inserted before apply, so it cannot observe itself.

**F. Terminal no-work.** `f.disposed_at IS NOT NULL OR inst.state='disposed'` →
`stale_generation / ensure_no_work`. `dispose_requested_at`/`dispose_pending` are deliberately not
included: they may still need leave/P6 cleanup and belong to the dispose path.

**G. Recursive lifecycle classification.** `built := reconcile_branch(f.id,'advance',expected)`:

| `built` | ensure result |
|---|---|
| error with `sqlstate='0A000'` | propagate the invariant fault |
| error `already_terminal` or `owner_closing` | `stale_generation / ensure_no_work` |
| any other error (`dependency_unresolved`, `retry_with_closure`, `install_not_ready`, `scope_closed`, …) | propagate unchanged |
| `active_noop`, `idle_noop` | `stale_generation / ensure_no_work` |
| `p1` + same-generation failure predicate | `stale_generation / ensure_failure_suppressed` |
| `p1` without that predicate, `leave`, `p6` | work |
| anything else (`p2`, `p4`, `divert`, `raise`, unexpected `p0`) | `0A000 / ensure_branch` |

Same-generation failure predicate (identical to 42:298/42:306):

```sql
jsonb_typeof(f.failure)='object'
AND v24_cordis.json_int(f.failure->'control_seq',0,9223372036854775807)
AND (f.failure->>'control_seq')::bigint=f.control_seq
```

**H. Work return.** `{kind:'p0',mode:'schedule',control_seq:f.control_seq}`; `interpret_reconcile`
returns `p0_delta(f.id,built)` immediately and never enters activation/P2/P4 logic.

## Persisted-emission predicate (exact shape)

```sql
EXISTS (
  SELECT 1
  FROM (
    SELECT p.id FROM v24_cordis.effects p
     WHERE p.kind='command_reconcile' AND p.status='succeeded' AND p.fiber_id=p_fiber
    UNION
    SELECT p.id FROM v24_cordis.effects p
     JOIN v24_cordis.events ev ON ev.effect_id=p.id
     WHERE p.kind='command_dispose' AND p.status='succeeded'
       AND v24_cordis.json_uuid(p.input->'install_id')
       AND ev.entity_type='install' AND ev.entity_id::text=p.input->>'install_id'
       AND ev.event_kind='install_dispose_progress'
       AND ev.payload->>'phase' IN ('fiber_requested','work_scheduled')
       AND ev.payload->>'fiber_id'=p_fiber::text
       AND ev.payload->'scheduled_targets' @> jsonb_build_array(p_fiber::text)
       AND v24_cordis.fiber_in_install_subtree(p_fiber,(p.input->>'install_id')::uuid)
  ) par
  LEFT JOIN v24_cordis.requests rq ON rq.effect_id=par.id
  WHERE rq.effect_id IS NULL
     OR rq.response->>'v' IS DISTINCT FROM '1'
     OR rq.response->>'disposition' IS DISTINCT FROM 'committed'
     OR rq.response->>'effect_id' IS DISTINCT FROM par.id::text
     OR jsonb_typeof(rq.response->'emitted') IS DISTINCT FROM 'array'
     OR EXISTS (
       SELECT 1 FROM jsonb_array_elements(
         CASE WHEN jsonb_typeof(rq.response->'emitted')='array'
              THEN rq.response->'emitted' ELSE '[]'::jsonb END) x(value)
       WHERE NOT v24_cordis.json_uuid(x.value)
          OR NOT EXISTS (SELECT 1 FROM v24_cordis.effects child
                         WHERE child.id=CASE WHEN v24_cordis.json_uuid(x.value)
                          THEN (x.value#>>'{}')::uuid END)
     )
);
```

Scoping rules:
- every succeeded `command_reconcile` parent for the fiber;
- a `command_dispose` parent only when its own progress event proves this fiber was a scheduled target
  (`fiber_requested` with non-null `scheduled_targets`, or `work_scheduled`) and the fiber is in that
  install's subtree. `fiber_control` also emits phase `fiber_requested` but `scheduled_targets=null`
  and `successors=[]`, so it is excluded by the array containment test.
- empty `emitted` produces no rows; leave/close/terminal steps cannot false-positive;
- the check is existence-only: any still-present child, whatever its status, discharges the
  obligation.

The historical read runs under the global advisory lock and is **not** expanded into the 512-target
closure.

## Validation flow through `advance`

1. **Payload.** Add `ensure` to `reconcile_payload_valid`'s action set. Shape stays exactly
   `{fiber_id,action,expected_control_seq}`. Non-reserved key `cordis/dp6/ensure/<fiber>/<attempt-uuid>`
   pairs correctly (`reserved` iff action=`advance`).
2. **Preflight.** Add `ensure` to the `reconcile_preflight` call site so a missing fiber returns
   `not_found_or_denied / reconcile_fiber` rather than a closure retry.
3. **Replay-first.** An existing request returns the stored response; conflicting bytes return
   `request_conflict`. No-op/fault results never insert a request, so they are not cached.
4. **Seed.** In `reconcile_command_seed`, extend the current-episode contribution, run and run-pin
   filters from `action='advance'` to `action IN ('advance','ensure')`. Activation-candidate refs stay
   `advance`-only (ensure never executes P4).
5. **Closure/lock.** `command_closure` → `lock_closure` → rediscover/equality unchanged. The seed
   includes the fiber/episode/contributions/runs/pins and resolve refs needed to classify P6 and to
   re-check under lock.
6. **Interpret.** `interpret_reconcile` loads `f`, calls `reconcile_branch(f.id,'ensure',expected)`;
   `{kind:'error',sqlstate:'0A000'}` is raised with that reason, other errors go through `error_v1`,
   and the work branch goes to `p0_delta` and returns immediately.
7. **Structure/domain validation.** `validate_delta` already accepts empty domain/events plus one
   ordinal-0 `command_reconcile(action='advance')` successor. `validate_domain` re-runs
   `reconcile_branch(f,'ensure',expected)`; the result is `kind='p0'`, so the existing exact check
   `p_delta IS NOT DISTINCT FROM p0_delta(f,v_expected)` is sufficient. `delta_write_closure_ok` and
   `assert_delta_applied` are vacuous for the empty domain; no event is required.
8. **Apply.** Only after validation: the parent ensure effect (kind `command_reconcile`, input with
   `action='ensure'`, `episode_id=NULL` via `command_binding`), the ready ordinal-0 successor bound to
   the current episode, and the request response are inserted atomically. The successor's existing
   `continuation_state` identity/binding checks are unchanged; parent action/episode do not enter that
   check.

Zero-write: every no-work/fault path returns or raises before `validate_and_apply_delta`, so no
effects/requests/domain/events rows and no `want_on`/`control_seq` change. Locks are transaction-scoped
and released on commit/rollback.

## Observer ACL and fixture

- Add an `observer` NOLOGIN/NOINHERIT group and a separate `observer` LOGIN that inherits only that
  group; create/verify them in `v24/cordis/dp1/setup_db.py` alongside the four existing roles.
- Add `observer` to `role_family()`'s validated group suffixes; do **not** add it to `role_allowed`'s
  admin/service/operator aliases, so the observer cannot call `advance`.
- `50_permissions.sql` keeps the single `SECURITY DEFINER` (`advance`), revokes PUBLIC table/function
  privileges, grants the observer schema USAGE and only column-level SELECT on:
  - `fibers(id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,current_episode_id,failure,retire_started_at,dispose_requested_at,disposed_at)`
  - `episodes(id,fiber_id,epoch,state,closed_at)`
  - `effects(id,parent_id,ordinal,fiber_id,episode_id,run_id,kind,status,input,request_actor,attempt,fence,claim_owner,lease_until,outcome,settled_at)`
  - `installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,artifact_digest,state)`
  - `requests(principal_id,request_key,request_bytes,request_digest,effect_id,response)`
  - `runs(id,owner_fiber_id,owner_episode_id,ended_at)`
  - `contributions(id,fiber_id,episode_id,kind,realm,key,inverse,withdrawn_at,released_at)`
  - `pins(id,consumer_fiber_id,consumer_episode_id,consumer_run_id,contribution_id,released_at)`
- No table-level SELECT, no INSERT/UPDATE/DELETE/TRUNCATE, no function EXECUTE, no CREATE on the
  schema. `events` is not granted in W1: the scanner does not read events to schedule, and P6/close
  diagnosis is inside the definer. (Oracle suggested optional `events` columns for diagnostics; not
  required by the W1 queries, so least privilege wins and this is recorded as deferred.)
- Database `TEMP` is a PUBLIC default in PostgreSQL. A per-role revoke cannot defeat a PUBLIC grant.
  The fixture therefore revokes `TEMP` from PUBLIC on the disposable database and re-grants it to the
  four inherited fixture groups, leaving the observer LOGIN without TEMP. The one inherited hostile
  temp-catalog negative (`dp1/test_kernel.py`) explicitly grants TEMP to its foreign service login so
  that semantic assertion is preserved rather than weakened. `CONNECT` remains PUBLIC.

## Scanner boundary and actor rule

- Read-only observer connection; per-topic independent keyset pages (`ORDER BY id`, `LIMIT 64`), one
  short READ COMMITTED transaction per page, committed before any `advance` call. No cross-page
  snapshot, no persistent cursor; cursors are lossable memory only.
- Round-robin topics; advance the cursor after each handled row (including blocked/deferred), never
  skip a page tail, wrap on a short/empty page. One item's failure is caught and recorded; it does not
  stop other items or topics.
- Only `advance` performs decisions/writes. The scanner classifies raw facts, builds the exact
  request envelope, and calls `advance`; it never writes tables, never calls helpers, never holds the
  G lock while sleeping or doing IO.
- `ensure` is issued as a configured real admin/service/operator LOGIN. Reserved continuations open a
  direct connection as `effects.request_actor` and verify `SELECT session_user` equals it; no
  `SET ROLE`/impersonation. Missing credential → scanner-local `blocked_actor_credential`, no write,
  item skipped, other items continue.
- W1 does **not** execute external effects. `host_io`, ready/claimed `dispatch`/`listener_call`/model/tool/
  run effects are diagnosed (`external_pending`, `unsupported_host_io`, `dispatch_pending`); unknown
  and inverse-unknown are debt diagnostics. A Fake handler may be injected by the gate only to prove it
  is never called in W1. Claim/receipt/crash recovery remains W2 (scope correction confirmed by both
  Oracle lanes).

## Remaining limitations recorded for later milestones

- A ready reconcile slot's full identity is revalidated by `continuation_state` when the scanner
  advances it; `ensure` treats the unique-index slot as the driver and does not duplicate that
  validation. A malformed slot is therefore reported through the continuation path, not silently
  treated as no-work.
- Under unbounded adversarial low-key insertions, UUID keyset paging alone cannot promise a hard
  liveness bound; W1 states the operational E1/E2 assumptions rather than claiming unconditional
  fairness.
- External-effect execution, receipt journal, crash injection and dispatch/run recovery are W2.
- The observer has no `events` SELECT in W1; if a later diagnostic needs it, add the exact columns
  with a gate.
- No new finite line cap is set; all physical counts remain measured/reported.

**Admission verdict: W1 semantic admission is resolved — `ensure` admitted with the corrections above.**

## Implementation review addendum (2026-10-28)

After implementation and the parent-requested CDP6-S coverage correction, the corrected staged diff was
reviewed once by Oracle group `6B696214-99CB-48A0-BEC6-131CBDE8508F`:

| Lane | Provider / model | Chat | Verdict |
|---|---|---|---|
| Primary | `codex` / `gpt-6.1-sol-xhigh` | `new-chat-7BEF5C` | ACCEPT WITH CORRECTIONS |
| Additional | `openCode` / `kimi-code-plan-cn/k3.1-pro` | `new-chat-oracle-2-ABB6CD` | ACCEPT WITH CORRECTIONS |

Both lanes accepted the corrected production-path coverage (independent-process restart/lost cursor,
duplicate/out-of-order/stale raw rows, real deferred/`blocked_unknown`/>512-closure fairness,
insertion before/after cursor, transaction IDLE, zero-write/quiet passes) and requested two additions:

1. exercise the `command_dispose` half of `ensure_emission_missing` for `fiber_requested` and
   `work_scheduled` targets, with an unrelated negative control;
2. prove `session_user` verification with a real but wrong LOGIN, not only a nonexistent credential.

Both were added as `[CDP6-S3b]` and `[CDP6-S9b]`; the corrected gate passed. No driver or SQL semantic
relaxation was needed, and the review did not identify a new design blocker.
