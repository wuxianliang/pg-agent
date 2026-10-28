# Cordis v2 DP6 — fair maintenance, crash recovery and receipt journal

Status 2026-10-28: **W1 fair scanner and W2 external-effect crash recovery are implemented and
gated; the final 37-command serial run is recorded in the conformance matrix. W3–W5 remain future
milestones.** This directory contains the single-host maintenance scanner, the `ensure` wake-up
command, the independent observer ACL, the W2 claim/receipt/journal executor and the `CDP6-S`/
`CDP6-R` gates. It does not contain terminal-unknown resolution, dispose-tree convergence evidence
or upgrade/rollback; those are W3–W5.

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

## W2 deliverables

| Surface | File | Contract |
|---|---|---|
| external executor | `v24/cordis/dp6/driver.py` | `Executor`: claim through `advance`, close/verify IDLE, Fake/trusted handler outside every DB transaction, receipt `advance` in a new short transaction; `host_io`/non-host listener/unsupported paths never invoke a handler |
| receipt journal | `v24/cordis/dp6/driver.py` | `ReceiptJournal`: one 0600 JSON file per effect/token under a 0700 directory, atomic temp write + file/dir fsync, canonical SHA-256, duplicate/torn/conflict detection; deleted only after `committed`/`replay`, quarantined when the DB says `stale_claim`/`receipt_conflict` |
| `run_start` source binding | `v24/cordis/dp6/driver.py` | `RunStartSource`: binding fixes `effect_id + contract_version + handler_digest + request + steps + digest`; inbox is consumed once; missing waits, corrupt/duplicate/conflicting/mismatched input blocks without invention |
| dispatch progress | `v24/cordis/dp6/driver.py` | child rows are read from committed facts; `unknown` is debt, never joined; pending children continue; all-terminal parent still ready is a zero-write invariant, never a fabricated seal |
| W2 gate | `v24/cordis/dp6/test_recovery.py` | CDP6-R R1–R28: real child-process kill/restart, claim rollback/COMMIT-loss, journal boundaries, receipt replay/conflict, 2×2 replay rights, run_start source/allocation, L-Iter, dispatch modes, withdraw/dispose ack loss and IDLE/no-network discipline |

W2 changed no SQL, loader, manifest or frozen surface. No command kind, table, column, protocol
error code, second scheduler or second writer was added. `advance` remains the only
`SECURITY DEFINER` function and the only domain writer.

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

## W2 external execution and recovery contract

`Maintainer` uses an `Executor` when external execution is enabled; without it the scanner remains the
W1 observer-only diagnostic mode. For every external effect:

1. `run_start` resolves the trusted source binding before claim; missing, corrupt, duplicate,
   conflicting or contract-mismatched input is reported without a claim. The binding fixes the
   original request and initial step count by `effect_id + contract_version + handler_digest` and an
   integrity digest; the adapter cannot replace them.
2. Claim is one short `READ COMMITTED` transaction through `advance` (`class='claim'`). After COMMIT
   the connection is verified `TRANSACTION_STATUS_IDLE` and closed.
3. The frozen input and claim execution descriptor are handed to the Fake/trusted handler while zero
   database connections are open. No adapter runs inside a transaction.
4. A complete receipt (effect id, actor, original attempt/fence/owner and full outcome) is written
   atomically to the fsynced journal **before** settlement.
5. Settlement is a new short `advance` transaction with the same token and bytes. A lost COMMIT
   response is retried with identical bytes and the DB's replay-first decides. `committed`/`replay`
   removes the journal entry; `stale_claim`/`receipt_conflict` quarantines it; every other failure
   keeps it. No lease timeout, process death or empty response is upgraded to success/failure.

Replay rights come from the frozen contract, not from the host: only `repeat=true` **and**
`concurrent=true` permits a post-expiry reclaim. A credible original token may settle after lease
expiry while it is still current; a new fence makes the old token `stale_claim`. A terminal receipt
replays without a second reducer/event; different bytes are `receipt_conflict` and zero-write.

Dispatch is recovered only from committed child rows: `unknown` children stay debt and are never
joined; `ready`/`claimed` children continue; an all-terminal parent still `ready` is an invariant, not
an invitation to invent an `acc` or seal. `host_io` is reported unsupported and never sent to a
handler. Journal files are `0600` inside a `0700` directory; their content is trusted host data and
must not be logged. The executor opens no socket and starts no thread.

## Scanner contract

Topics and page order (`ORDER BY id`, `LIMIT 64`, independent cursor per topic):

```text
fibers            disposed_at IS NULL                                  -> ensure
commands          ready command_reconcile                              -> reserved advance continuation
disposes          installs.state='dispose_pending'                     -> fresh command_dispose
external          ready/claimed host/run/model/tool/listener/dispatch  -> W2 claim/handler/receipt; without executor diagnostics
expired           claimed with lease_until < clock_timestamp()         -> W2 reclaim only with replay rights; otherwise blocked
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

With an executor, ready external effects are claimed and settled under the W2 contract; an unexpired
claim waits, an expired claim is reclaimed only when the frozen contract permits repeat+concurrent,
and `host_io` is reported `unsupported_host_io` without a handler call. Dispatch parents are inspected
from child rows, never claimed or sealed by the host. Without an executor (W1 mode) external rows are
diagnostics only: `external_pending`/`claimed_external_pending`/`dispatch_pending`; expired claims are
`expired_claim_pending`. Unknown effects and inverse-unknown contributions remain debt diagnostics in
both modes and are never guessed into a terminal result.

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
3. For external execution, construct the `Executor` with the same credential map, a trusted
   `handler`, a durable `ReceiptJournal` directory and, for `run_start`, a pre-deployed
   `RunStartSource` directory. Missing credentials/source are reported blocks, never impersonated or
   invented; never place the journal/source under a world-readable path.
4. Call `Maintainer.run_once()` periodically (or `run(rounds)`). A process restart loses only memory
   cursors; the next pass starts from the beginning, replays any surviving journal entry with its
   original token, and rediscovers committed facts. Do not delete journal files manually.
5. Inspect `Report.actions`/`Report.diagnostics`: `committed` means a protocol write; `stale_generation`
   reasons `ensure_no_work`/`ensure_slot_present`/`ensure_failure_suppressed` are expected no-ops;
   `invariant_fault` is `0A000` and must be reported, not retried in a tight loop; `blocked_actor_credential`
   means a credential is missing; `blocked_unknown`, `journal_corrupt`, `dispatch_*_invariant` and
   `receipt_not_publishable` are debt/blocks, not resolutions.
6. Stop the scanner before external adapters on rollback; keep effects, unknown receipts, pins and
   tombstones. Do not clear the DB, quarantine journal entries or hand-edit lifecycle rows.

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

## CDP6-R gate

```bash
uv run python v24/cordis/dp6/test_recovery.py
```

The gate covers: real child-process kill/restart at claim before/after COMMIT, during the Fake
adapter, after the adapter returns and before the journal fsync, after journal write, and before/after
settlement COMMIT; receipt replay with no second reducer/event and conflicting bytes zero-write;
terminal outcome immutability; the repeat/concurrent 2×2 replay matrix, concurrent post-expiry reclaim
with exactly one new fence, old-token settlement before replacement and `stale_claim` after it;
`run_start` source missing/corrupt/duplicate/mismatch and allocation-before-claim; L-Iter batch
rollback; install, withdraw and dispose COMMIT-ack loss restart convergence; all five dispatch modes
after a committed child, unknown-child non-join and the settled-parent invariant; unknown debt;
missing/wrong actor credentials; corrupt/duplicate journal blocking; and IDLE/no-network discipline.

## Verified W2 baseline

Measured at the W2 gate (physical lines, `str.splitlines()`, same count as the gates):

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
dp6/test_scanner.py 1311 / dp6/driver.py 1028 / dp6/test_recovery.py 1737  (report-only; no cap)
```

W2 changed no SQL, loader, manifest or frozen surface, so the W1 SQL measurements above are unchanged.

The 37-command serial gate evidence (35 inherited + `test_scanner.py` + `test_recovery.py`) is recorded
in the conformance matrix with exit code and elapsed time. No real provider socket, external adapter or
network call was used; every gate used a disposable pgembed database and Fake handlers. The W1
corrected gate was reviewed once by Oracle group `6B696214-99CB-48A0-BEC6-131CBDE8508F` (both lanes:
accept with corrections). No W2 Oracle review result was persisted before the prior review wrapper was
stopped; this acceptance session therefore did not launch a duplicate review and records the direct
code audit plus the 37-command run instead.

## Known limitations / non-claims

- W2 is not W3–W5 evidence. Terminal-unknown resolution, the full dispose-tree convergence matrix and
  drain upgrade/rollback/HMR remain unimplemented.
- `host_io` and non-host listener execution remain unsupported/blocked; no real adapter is used by any
  gate.
- Unknown effect outcomes and inverse-unknown contributions remain debt/`blocked_unknown`; W2 never
  converts lease expiry, process death or an empty response into success/failure.
- A journal entry whose DB receipt is `stale_claim`/`receipt_conflict` is quarantined as `.dead` for
  manual inspection; the host does not silently resolve or delete it, and does not retry it.
- A `run_start` handler that returns no publishable receipt leaves the effect claimed and does not
  invent an unknown terminal outcome; recovery requires the original source/credential or manual
  handling.
- A ready reconcile slot's full identity is revalidated by `continuation_state` when the continuation
  is advanced; `ensure` treats the unique-index slot as the driver and does not duplicate that check.
  A malformed slot is therefore diagnosed through the continuation path, not treated as no-work.
- Under unbounded adversarial low-key insertions, UUID keyset paging alone cannot promise a hard
  liveness bound; the scanner relies on the documented E1/E2 operational assumptions and does not
  claim unconditional fairness.
- The observer has no `events` SELECT; if a later diagnostic needs it, add exact columns with a gate.
- No new finite line cap was set. The old 5500/700/900 assertions are measurement-only; all required
  file/manifest and semantic/ACL/boundary negatives remain.
