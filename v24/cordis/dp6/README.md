# Cordis v2 DP6 — W1 fair rediscovery / maintenance scanner

Status 2026-10-28: **W1 implementation and corrected `CDP6-S` coverage complete; the final
36-command serial run is recorded in the conformance matrix. W2–W5 remain future milestones.** This
directory contains the single-host maintenance scanner, the `ensure` wake-up command, the independent
observer ACL and the `CDP6-S` gate. It does not contain external-effect execution, receipt
journal/crash recovery, unknown resolution, dispose-tree convergence evidence or upgrade/rollback;
those are W2–W5.

- Plan: `docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md`
- Conformance matrix: `docs/reviews/cordis-v2-dp6-conformance-matrix-2026-10-28.md`
- Deviation ledger: `docs/reviews/cordis-v2-dp6-deviation-ledger-2026-10-28.md`
- W1 semantic-admission / Oracle design record:
  `docs/reviews/cordis-v2-dp6-w1-oracle-design-2026-10-28.md`
- Authority: `docs/designs/cordis-plugin-system-2026-10-25.md`; DP1–DP5 remain the inherited
  implementation. Frozen `v24/load.py`, `v24/sql/**` and `v24/s1`–`s12` were not modified.

## W1 deliverables

| Surface | File | Contract |
|---|---|---|
| fair scanner | `v24/cordis/dp6/driver.py` | read-only topics, independent keyset pages, round-robin, lossable cursors, `advance` for every decision/write, actor reconnect |
| `ensure` wake-up | `v24/cordis/sql/40_advance.sql`, `41_lifecycle.sql`, `42_teardown.sql` | fourth `command_reconcile` action on the existing exact payload; invariant-first selector; P0 `schedule` delta only |
| observer ACL + fixture | `v24/cordis/sql/50_permissions.sql`, `v24/cordis/dp1/setup_db.py` | independent NOLOGIN group + LOGIN, column-only SELECT, no EXECUTE/DML/TEMP; create/verify/cleanup |
| budget/gate conversion | `v24/cordis/helper_budget.py` + DP1–DP5 gates | physical lines measured/reported, no numeric cap; required-file/manifest negatives retained |
| gate | `v24/cordis/dp6/test_scanner.py` | CDP6-S (8 specification items) plus observer ACL, fixture lifecycle, independent-process restart, raw-row replay and transaction discipline |

No command kind, table, column, protocol error code, second scheduler or second writer was added.
`advance` remains the only `SECURITY DEFINER` function and the only domain writer.

## `ensure` command contract

Exact payload (unchanged shape):

```json
{"fiber_id":"<uuid>","action":"ensure","expected_control_seq":<int>}
```

Key: `cordis/dp6/ensure/<fiber-uuid>/<attempt-uuid>` (non-reserved; `cordis/reconcile/...` remains
reserved for the ordinal-0 `advance` successor). Effect id is the existing
`effect_id_for(principal, key, 'command_reconcile')`; the actor is the real LOGIN that calls
`advance`.

The selector runs under the existing G lock after replay-first and the locked-closure re-check:

1. current-episode consistency (dangling/closed/foreign episode, and NULL episode with non-NULL
   `retire_started_at`) → `0A000 / phase_drift`;
2. persisted-emission invariant: a succeeded command parent's committed `emitted` set names a missing
   effect row (reconcile parents for the fiber; dispose parents only when their persisted
   `install_dispose_progress` event proves this fiber was a scheduled target) →
   `0A000 / missing_reconcile_successor`;
3. required-continuation invariant: `reloading` with no reconcile slot, or `closing` with a persisted
   `contributions_released`/`pins_released` event for that episode and no slot →
   `0A000 / missing_reconcile_successor`;
4. stale expected sequence → `stale_generation / reconcile_generation`;
5. open slot → `stale_generation / ensure_slot_present`;
6. disposed fiber/install → `stale_generation / ensure_no_work`;
7. recursive `reconcile_branch(fiber,'advance',expected)`:
   - `p1` with the same-generation failure predicate → `stale_generation / ensure_failure_suppressed`;
   - `p1` without it, `leave`, `p6` → work;
   - `active_noop`/`idle_noop` → `ensure_no_work`;
   - `already_terminal`/`owner_closing` → `ensure_no_work`;
   - other errors propagate unchanged; unexpected successful branches are `0A000 / ensure_branch`.

Work commits the existing P0 `schedule` delta: empty domain, empty events, exactly one ordinal-0
`command_reconcile` successor with `action='advance'` and the current `control_seq`. The successor is
then advanced by the scanner; `ensure` itself never changes `want_on`/`control_seq`. Because failure
is consulted only on the `p1` branch, an active non-live fiber (`leave`) or a closing episode (`p6`)
still runs teardown.

Every no-work/fault path returns or raises before `validate_and_apply_delta`: ten-table zero write, no
request/effect row, no cached no-op. A committed schedule replays by request key; no-op results are
intentionally uncached and a fresh attempt UUID is used after a received result.

## Scanner contract

Topics and page order (`ORDER BY id`, `LIMIT 64`, independent cursor per topic):

```text
fibers            disposed_at IS NULL                                  -> ensure
commands          ready command_reconcile                              -> reserved advance continuation
disposes          installs.state='dispose_pending'                     -> fresh command_dispose
external          ready/claimed host/run/model/tool/listener/dispatch  -> diagnostics only (W2)
expired           claimed with lease_until < clock_timestamp()         -> diagnostics only (W2)
unknown           effects.status='unknown'                             -> debt diagnostic
inverse_unknown   released_at IS NULL AND inverse->>'op'='unknown'     -> debt diagnostic
```

Each page is a short READ COMMITTED transaction that is committed before any `advance` call; there is
no cross-page snapshot and no persistent cursor. One page per topic per pass, starting topic rotated
per pass; the cursor advances to the last row after the page is handled (a short/empty page wraps to
the beginning). An item failure is recorded and does not stop the page or later topics. New low-key
rows are seen on the next wrap. The scanner is at-least-once: a lost cursor replays a page, which is
safe because `ensure` is a no-op/slot/replay and commands use the unique reconcile slot and
replay-first.

Actor rule:
- reads use the independent observer LOGIN; it has no `advance` EXECUTE and no table DML;
- `ensure` and fresh `command_dispose` use a configured real admin/service/operator LOGIN;
- a reserved continuation opens a direct connection as that effect's `request_actor` and verifies
  `SELECT session_user` equals it **before** calling `advance`; no `SET ROLE`, no impersonation;
- a missing credential is a scanner-local `blocked_actor_credential`, leaves the item untouched and
  does not stop other items or topics.

W1 never claims, settles or invokes a handler for an external effect. `host_io` is reported as
`unsupported_host_io`; ready/claimed external/dispatch effects as `external_pending`/
`claimed_external_pending`/`dispatch_pending`; expired claims as `expired_claim_pending`. Claim,
receipt journal, crash injection and dispatch/run recovery are W2.

## Observer ACL

`v24_cordis.role_family()` validates an `observer` NOLOGIN/NOINHERIT group in the random family;
`role_allowed` remains limited to admin/service/operator, so the observer cannot call `advance`.
`50_permissions.sql` grants the observer schema USAGE and column-level SELECT only:

```text
fibers(id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,current_episode_id,
       failure,retire_started_at,dispose_requested_at,disposed_at)
episodes(id,fiber_id,epoch,state,closed_at)
effects(all columns)
installs(id,scope_id,owner_fiber_id,owner_episode_id,identity,version,artifact_digest,state)
requests(all columns)
runs(id,owner_fiber_id,owner_episode_id,ended_at)
contributions(id,fiber_id,episode_id,kind,realm,key,inverse,withdrawn_at,released_at)
pins(id,consumer_fiber_id,consumer_episode_id,consumer_run_id,contribution_id,released_at)
```

No table-level SELECT, no INSERT/UPDATE/DELETE/TRUNCATE, no function EXECUTE, no CREATE on the schema.
`events` is intentionally not granted in W1: the scanner does not read events to schedule, and the
close/P6 invariant runs inside the definer. Database TEMP is denied to the observer by revoking the
PUBLIC default in the fixture and re-granting it to the four inherited groups; the one inherited
hostile temp-catalog negative explicitly grants TEMP to its foreign login so that assertion is
preserved, not weakened.

## Runbook

1. Load the canonical Cordis SQL as the schema owner (`v24/cordis/load.py`); the fixture creates the
   observer group/login and the gate verifies the exact grants.
2. Provide the scanner with a read-only observer connection factory, a trusted credential map from
   real admin/service/operator LOGINs, and one configured `ensure` actor. Do not use the observer or
   a superuser as the product writer.
3. Call `Maintainer.run_once()` periodically (or `run(rounds)`). A process restart loses only memory
   cursors; the next pass starts from the beginning and rediscovers committed facts.
4. Inspect `Report.actions`/`Report.diagnostics`: `committed` means a protocol write; `stale_generation`
   reasons `ensure_no_work`/`ensure_slot_present`/`ensure_failure_suppressed` are expected no-ops;
   `invariant_fault` is `0A000` and must be reported, not retried in a tight loop; `blocked_actor_credential`
   means a credential is missing; debt diagnostics are not resolutions.
5. Stop the scanner before external adapters on rollback; keep effects, unknown receipts, pins and
   tombstones. Do not clear the DB or hand-edit lifecycle rows.

## CDP6-S gate

```bash
uv run python v24/cordis/dp6/test_scanner.py
```

The gate covers: observer ACL and fixture lifecycle; ensure quiet/slot/stale/work; same-generation
failure suppression with teardown first; reconcile- and dispose-parent emitted/reloading/closing/retire
invariant faults with zero write; replay-first, conflicting bytes and concurrent unique slot; >page
fibers, ready continuations and dispose installs with wrap; insertion both before and after an advanced
cursor rediscovered within bounded wraps; duplicate/out-of-order/stale raw rows revalidated by
`advance` without repeated effects; real >512 closure, deferred, `blocked_unknown` and bad-actor first
items not starving same-page healthy commands or other topics; diagnostics-only external/expired/
unknown/inverse debt with zero handler calls and zero write; missing and wrong-real-LOGIN actor
credentials blocked locally while a correctly-bound sibling advances; every reader/advance transaction
committed or rolled back to IDLE before close with no residual session; a separate driver process, a
SIGKILLed driver and a third empty-memory process converging on the same canonical DB; and driver DML
purity.

## Verified W1 baseline

Measured at the W1 commit (physical lines, `str.splitlines()`, same count as the gates):

```text
40_advance.sql  1685
41_lifecycle.sql 1481
42_teardown.sql 1112
43_loop.sql      700
44_events.sql    622
40-49 total     5600      (report-only; 2026-10-28 authorization, no cap)
domain DDL       465      (report-only; bookkeeping 18+19 = 22 separate)
manifest 19 / tables 10 / pg_proc 172 (164 private helpers + 8 trigger guards)
one DEFINER advance / public EXECUTE 0 / command kinds 3 / protocol errors 24
closure 512 / successor 16 unchanged
dp6/test_scanner.py 1311 / dp6/driver.py 326  (report-only; no cap)
```

The 36-command serial gate evidence (35 inherited + `test_scanner.py`) is recorded in the conformance
matrix with exit code and elapsed time. No real provider socket, external adapter or network call was
used; every gate used a disposable pgembed database and Fake handlers. The corrected gate was also
reviewed once by Oracle group `6B696214-99CB-48A0-BEC6-131CBDE8508F` (both lanes: accept with
corrections); the two requested additions — `command_dispose` missing-successor coverage and a real
wrong-`session_user` mismatch — are included as `[CDP6-S3b]`/`[CDP6-S9b]`.

## Known limitations / non-claims

- W1 is not crash-recovery evidence. External claim/receipt/journal, dispatch half-way rebuild and
  `run_start` source binding are W2.
- External effects are diagnosed, never executed. `host_io` remains `0A000`/unsupported.
- A ready reconcile slot's full identity is revalidated by `continuation_state` when the continuation
  is advanced; `ensure` treats the unique-index slot as the driver and does not duplicate that check.
  A malformed slot is therefore diagnosed through the continuation path, not treated as no-work.
- Under unbounded adversarial low-key insertions, UUID keyset paging alone cannot promise a hard
  liveness bound; W1 relies on the documented E1/E2 operational assumptions and does not claim
  unconditional fairness.
- The observer has no `events` SELECT; if a later diagnostic needs it, add exact columns with a gate.
- No new finite line cap was set. The old 5500/700/900 assertions are measurement-only; all required
  file/manifest and semantic/ACL/boundary negatives remain.
- W2–W5 are separate fresh-session milestones; this README does not claim them.
