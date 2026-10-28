# Cordis v2 DP6 — fair maintenance, crash recovery and receipt journal

Status 2026-10-29: **W1 fair scanner, W2 external-effect crash recovery, W3 unknown debt / dispose
convergence, W4 drain-based upgrade/rollback + HMR trigger and W5 final boundary closeout are
implemented and gated. The final 40-command serial run (39 inherited + `test_boundaries.py`) is
recorded in the conformance matrix; `CDP6-B` passes.** This directory contains the single-host
maintenance scanner, the `ensure` wake-up command, the independent observer ACL, the W2
claim/receipt/journal executor, the W3 debt diagnostics and dispose convergence evidence, the W4
switch driver/HMR trigger, the W5 whole-boundary gate, and the
`CDP6-S`/`CDP6-R`/`CDP6-U-D`/`CDP6-H`/`CDP6-B` gates. "W5 complete" means the documented boundaries
and frozen surfaces are verified; it does **not** claim terminal-unknown resolution, multi-host
correctness or seamless in-process HMR (see Known limitations).

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

## W3 deliverables

| Surface | File | Contract |
|---|---|---|
| effect-unknown debt | `v24/cordis/dp6/driver.py` | the `unknown` topic now reads the raw fiber/episode/run/install facts and reports `unknown_effect_debt` with `fiber_id`, `episode_id`, `run_id`, `fiber_disposed`, `install_state` and a raw-fact `blocks` list; no decision or write |
| inverse-unknown debt | `v24/cordis/dp6/driver.py` | the `inverse_unknown` topic reports `inverse_unknown_debt` with the owner scope, `inverse_op`, `install_state`, `blocks` and a stable `debt_digest` (the trusted resource/compensation descriptor is never copied) |
| sealed-subtree inverse barrier | `v24/cordis/sql/42_teardown.sql` (`dispose_plan`) | an unreleased `inverse='unknown'` contribution anywhere in the sealed subtree returns `blocked_unknown / inverse` before any progress write |
| W3 gate | `v24/cordis/dp6/test_dispose.py` | CDP6-U1–U6 and D1–D4: debt discovery/immutability/safe replay, restart, multi-level owner/provider/listener/run/pin convergence, repeat dispose/replay, SIGKILL after COMMIT, graph/closure bounds and permission negatives |

W3 changed only `42_teardown.sql` (one predicate), `driver.py` diagnostics and the new gate. No
command kind, table, column, protocol error code, second scheduler, second writer or second
interpreter was added. `advance` remains the only `SECURITY DEFINER` writer, and terminal
effect/contribution/tombstone facts remain immutable.

## W4 deliverables

| Surface | File | Contract |
|---|---|---|
| drain switch driver | `v24/cordis/dp6/driver.py` (`SwitchPlan`, `SwitchDriver`) | freezes operation UUID/actor/source/target/digest/source-seq; every phase is rebuilt from committed `requests`/`fibers`/`installs`/`episodes`/`contributions`; every write is the existing `command_install`/`command_reconcile` through `advance`; drain is produced only by the W1 scanner |
| rollback reuse declaration | `v24/cordis/sql/41_lifecycle.sql` | a second exact `command_install` payload `{mode:'reuse',install_id,fiber_id,expected_digest}` creates one fiber on an immutable install: no scope/install row, no declaration rewrite, existing child contribution/`dispose_child`/iterator rules |
| reuse event | `v24/cordis/sql/40_advance.sql` | `install_reused` exact payload (`scope_id,fiber_id,owner_fiber_id,owner_episode_id,child_contribution_id`); no new command kind, table, column or error code |
| HMR trigger | `v24/cordis/dp6/driver.py` (`HmrTrigger`) | one pre-deployed JSON descriptor per identity; it compares the running install version+digest and submits the identical frozen switch request; no download, import, ESM cache or state hot-swap |
| W4 gate | `v24/cordis/dp6/test_upgrade.py` | CDP6-H1–H9 plus the H3b early-activation negative, H3c dependency-unresolved and H4a–H4d real SIGKILL/restart boundaries; 14 disposable databases, Fake/no adapter, no network |

W4 changed `40_advance.sql` (+7) and `41_lifecycle.sql` (+204); `42`/`43`/`44`, the loader,
permission file and manifest are untouched. No command kind, table, column, protocol error code,
second scheduler, second writer or second interpreter was added. `advance` remains the only
`SECURITY DEFINER` writer and the only domain writer.

## W5 deliverables

| Surface | File | Contract |
|---|---|---|
| final boundary gate | `v24/cordis/dp6/test_boundaries.py` | `CDP6-B` B1–B6: canonical 19-file manifest and loader negatives; ten tables/no VIEW/EXTENSION; three command kinds and the three lifecycle interpreters; 24 errors; one `advance` DEFINER with PUBLIC EXECUTE 0; one G lock; exact observer column ACL and the original admin/service/operator ACL; real install/reconcile/dispose commits; immutable terminal/request rows, unique ready successor slot and replay-first; closure 512/513, successor 16/17, body keys 200/201 and depth 32/33; frozen `v24/load.py`, `v24/sql/**`, `v24/s1`–`s12` and the `57e2c1e` diff |
| closeout artifacts | this README, DP6 matrix, deviation ledger, DP6 plan Result | measured line counts, 40-command evidence, residual debts and honest non-claims |

W5 changed no SQL, loader, permission file, manifest, driver or frozen surface. It added no table,
column, command kind, protocol error code, interpreter, scheduler or writer.

## Unknown-debt contract

Two distinct debts are discovered by the scanner and neither is ever guessed into a result:

1. **Effect outcome unknown.** A terminal `effects.status='unknown'` row carries the debt. The
   diagnostic is `unknown_effect_debt` (stable `effect_id`, owner fiber/episode/run, own install
   state, `blocks`). `p6_plan` and `dispose_plan` return `blocked_unknown`; a claim returns
   `receipt_conflict`; no lease expiry, process death, empty handler response or elapsed time
   changes the outcome or writes a reducer/event. Repeating a quiet scan creates no command/effect
   row.
2. **Contribution inverse unknown.** An unreleased contribution whose `inverse` op is `unknown`
   carries the debt. The diagnostic is `inverse_unknown_debt` (stable contribution id, owner scope,
   `debt_digest`, `blocks`). `p6_plan` blocks on the batch and `dispose_plan` blocks the sealed
   subtree as `blocked_unknown / inverse`; the contribution is never released, re-inverted or
   deleted, and the owner never reports completion.

`blocks` is a diagnostic label computed only from raw observer columns
(`installs.state`, `fibers.current_episode_id/dispose_requested_at`, `runs.ended_at`): it names the
obligation classes this terminal debt touches, never a scheduling decision. A debt on a descendant
fiber reports its own install state; the sealed ancestor remains visible through `dispose_plan` and
the `disposes` topic.

**Manual reconciliation remains a design gate.** If an operator verifies and compensates an external
resource out of band, the database has no approved ABI to record that fact, so W3 keeps the debt
blocked instead of inventing a state transition, a table, a column or a terminal rewrite (CDP6-U6,
deviation ledger DP6-D40).

## Dispose convergence contract

`dispose_subtree`, `dispose_plan`, `dispose_delta`, `p6_plan` and `p6_delta` remain the only dispose
planners. W3 changes one predicate: an unreleased inverse-unknown contribution blocks the sealed
subtree before any successor is scheduled, so a permanently blocked install is a stable
`blocked_unknown` rather than an endless stream of committed no-op dispose receipts. The existing
coalesced refresh (`wait_slot` → committed empty receipt) is retained because DP3-D5 gates it; a
candidate `deferred / slot` replacement was implemented, rejected by that inherited gate and
reverted (deviation ledger DP6-D41).

The convergence order is unchanged and gated: listener call and open run defer the plan; external
consumer pins defer P6 until every pin is released; a child install/fiber tombstones before its
owner; episodes/contributions/pins/effects history is retained; a committed dispose step replays
byte-identically; a COMMIT followed by SIGKILL leaves one receipt and an empty-memory restart
converges.

The committed owner graph is acyclic and depth-bounded by the existing deferred `fibers_graph`
constraint trigger (pin/run/owner cycles → `23514 'fiber graph cycle'`; a 512-edge path →
`23514 'fiber graph validation limit'`; owner re-parenting → `55000`; a dangling owner insert →
`23503`). No new cycle guard was added to `dispose_subtree` because committed cycles are
unreachable; the gate proves those rejections instead.

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

## Drain-based switch contract

A switch is one frozen intent, submitted through the existing command protocol and advanced only by
committed facts. `SwitchPlan` fixes `kind` (`U` upgrade / `R` rollback), `operation` UUID, `actor`,
`source_fiber`, `target_fiber`, `source_seq`, `source_install`, `target_install`,
`expected_digest`, the exact first-request payload and the expected service keys. The keys are:

```text
cordis/dp6/switch/v1/<U|R>/<operation>/<source>/<target>/<source-seq>/start
cordis/dp6/switch/v1/<U|R>/<operation>/<source>/<target>/off/<source-seq>
cordis/dp6/switch/v1/<U|R>/<operation>/<source>/<target>/on/0
```

They are non-reserved (the reserved `cordis/reconcile/...` continuation pairing is unchanged) and
bounded well below the 512-character request-key limit. The first request is the existing
`command_install` (new declaration for `U`, reuse declaration for `R`); `off`/`on` are existing
`command_reconcile` commands at the frozen source sequence and target sequence `0`. All three use the
same real LOGIN; `advance` records that actor on each effect. The committed `requests` row stores the
canonical payload bytes, so a restart can re-verify the declaration (version/digest/ids) instead of
inventing a new intent. Conflicting bytes on the same actor/key are `request_conflict`; the same
operation UUID from another actor is `effect_id_conflict`; a second unfinished operation on one
`(scope, identity)` slot is `switch_slot_busy`, except an explicit reversal whose source is the
other operation's target and whose target install is the other operation's source install.

`SwitchDriver.status` derives the phase from committed facts only:

```text
start_pending -> off_pending -> draining -> on_pending -> activating -> complete
                                            \-> failed (activation failure at the current seq)
any stage -> blocked (payload/actor/digest/slot/stale-seq/target-moved/address-missing)
```

- **start** creates the new immutable install/fiber (or the rollback fiber on the old install) with
  `want_on=false, control_seq=0`.
- **off** is sent only at the frozen `source_seq`; an independent control change is
  `blocked/stale_control_seq`, never silently retargeted.
- **draining** waits until the source is `want_on=false`, has no open episode, no
  `retire_started_at`, no unreleased contribution, no live pin (consumer or provider), no open run,
  and no ready/claimed/unknown effect. The scanner produces the drain; the driver never writes a
  lifecycle column.
- **on** is sent only when the target is still the same fiber at `control_seq=0`, never on.
- **complete** requires the target episode active, no pending reconcile slot, and (when the expected
  key set is known) every declared service key live from that exact episode. The empty window
  between the old release and the new activation is legal and observable; two live versions are
  impossible because `contributions_service_addr` still arbitrates the address.

Rollback reuses the old immutable install through the exact 4-key payload. Admission (under G and
the same closure lock) requires: the install is `installed`; the digest matches; it is not a root
install; its scope lineage is open; its owner fiber/episode is the live current generation (owner
install installed, want_on, no dispose/retire/failure); every existing fiber of the install is off
and drained; there is no unknown effect on any of its fibers; and the target fiber does not exist.
The declaration (scope, owner, manifest, contracts, overlay, policy, digest) is read from the old
install and never rewritten. The delta is fiber-only: one `fiber_create`, one child
`contribution_append` with `dispose_child` inverse, one `episode_progress`, one `install_reused`
event, no successors, no scope/install row. `validate_install_domain` requires exactly those ops,
fields, ledger seq/iterator and event; `assert_delta_applied` proves the applied fiber/contribution/
progress postcondition. The closure seed is the immutable install + scope + owner fiber/episode +
owner-episode contributions + every fiber of the install, so `dispose_subtree` already covers the
old and new instances and `install_dispose_finish` requires all of them tombstoned.

**Root installs cannot be reused.** A root install has no owner and a second ownerless fiber would
violate the single-root `fibers_graph` invariant; admission returns
`invalid_args / install_reuse_root` and the driver returns `switch_target_install_exists` for the
in-place variant. Non-root child installs are fully supported. A disposed install
(`install_not_ready / install_reuse_state`) or a changed owner episode
(`owner_closing / install_reuse_owner`) is never revived.

**Restart.** `resume(kind, operation, actor)` parses the one committed start key and rebuilds the
plan from the committed request bytes; a U plan carries the declaration, an R plan derives the
expected service keys from the source fiber's retained service-contribution history. The driver then
continues at the first missing phase. If the first request never committed, the database has no
intent: only the caller can resubmit the same operation UUID/key/payload. There is no phase table,
cursor or scheduler; `SwitchPlan.as_dict()`/`from_dict()` let a caller persist its own intent, but
the committed request remains authoritative.

## HMR trigger

`HmrTrigger(driver, directory, actor)` reads one pre-deployed JSON descriptor per managed identity:

```json
{"identity":"svc","version":"2","artifact_digest":"<sha256>",
 "operation_uuid":"<uuid>","source_fiber_id":"<uuid>",
 "install_id":"<uuid>","target_fiber_id":"<uuid>",
 "manifest":{},"contracts":{},"policy_ref":null,"overlay":{}}
```

A tick compares the running source install's version+digest with the descriptor. If equal it returns
`hmr_current`; otherwise it calls `SwitchDriver.start` with the descriptor's fixed operation/target
UUIDs and scope/owner read from the source install. Repeating a tick sees the committed operation and
replays (`hmr_inflight`/`start_replay`); a different descriptor under the same operation is blocked,
never treated as a new intent. Missing/corrupt/mismatched descriptors are `hmr_*` diagnostics with no
write. The trigger opens no socket, imports no code, downloads nothing, invalidates no ESM cache and
moves no in-process state: it only submits the same version-switch request. The manual driver flow
works without any watcher.

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
7. For an upgrade/rollback, build `SwitchDriver` with the same observer/actor factories and call
   `plan_upgrade`/`plan_rollback`, then `start` and `step`/`drive`. The caller supplies the operation
   UUID, target fiber UUID and (for an upgrade) the new declaration; `start` fixes the request key.
   Do not hand-edit `want_on`/`control_seq`, do not create a second phase table, and do not submit
   `on` before the source drain observation says `on_pending`.
8. For HMR, write the pre-deployed descriptor and call `HmrTrigger.tick()` periodically. It only
   submits the same switch request; never reload modules, invalidate an ESM cache or move process
   state.

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

## CDP6-U/D gate

```bash
uv run python v24/cordis/dp6/test_dispose.py
```

The gate covers: a terminal effect unknown and an unreleased inverse-unknown contribution built
separately, each reported as stable debt with owner scope and zero-write `blocked_unknown` barriers
at dispose and P6; repeated quiet scans creating no command/effect row and no reducer/event; terminal
immutability and `receipt_conflict` instead of a fabricated claim; an unrelated expiry-reclaimable
effect settling once under the debt; a real dispose COMMIT followed by SIGKILL and an empty-memory
restart converging; one dispose key replaying byte-identically with a conflicting payload rejected
and post-tombstone commands `already_terminal`; a ready listener, an open run and two consumers
sharing one provider contribution each deferring the sealed subtree, with grandchild-install/fiber
completion ordered before the child install/fiber and all history retained; owner re-parent/dangling
owner, pin-cycle, mixed owner+pin-cycle and over-depth rejections at COMMIT; a >256 withdraw closure
and an in-flight slot staying stable and zero-write; and service/operator/admin/observer negatives
proving no LOGIN can rewrite, release or insert around a debt.

## CDP6-H gate

```bash
uv run python v24/cordis/dp6/test_upgrade.py
```

The gate covers: a new declaration identity with a same-digest new version, in-place install
overwrite rejected by the driver, the command admission and the immutable-install trigger, and a
duplicate `(scope,identity,version)` refused (`H1`); an open run, an activation pin and created host
listener children each keeping the old address live while the source drains, with the released pin
and contribution history still readable and `resolve` moving to the new generation (`H2`); one live
provider per slot throughout, the unique address index refusing a second live insert, an observable
empty window with no live row and no resolution, and activation only after the old release (`H3`);
activation attempted before the release failing with `provide_conflict`, never two live versions,
then a fresh rollback restoring the old declaration (`H3b`); an unmet dependency leaving the switch
`activating` with no episode, no failure write, an empty address and a successful explicit rollback
(`H3c`); a real pre-COMMIT rollback leaving no intent, and real child-process SIGKILLs after the
start/off COMMIT, mid-P6, at the address release and after the on COMMIT resumed from committed
facts with exactly one request per phase and no duplicate install/fiber/episode (`H4a`–`H4d`);
conflicting payload/actor, same-slot concurrency, an independent control change, an
independently enabled target, a duplicate fiber, a digest mismatch and a changed owner episode all
refused or safely blocked (`H5`); rollback on the immutable old declaration with a new fiber/episode,
old fiber asleep, whole-install dispose covering both historical instances, then disposed-install
reuse refused (`H6`); a terminal unknown keeping the upgrade draining and refusing rollback reuse
without clearing the debt (`H7`); an upgraded service and event listener resolving only to the new
generation with the window/dispatch children never mixed (`H8`); and HMR ticks submitting the
identical stable request, replaying on a repeat tick, blocking descriptor corruption/mismatch and
exposing no download/ESM path (`H9`).

## CDP6-B gate

```bash
uv run python v24/cordis/dp6/test_boundaries.py
```

The gate is the W5 closeout and re-proves the inherited boundaries against the current catalog and
real protocol, not by copying constants:

- `[CDP6-B1]` the 19-entry canonical Cordis manifest, its missing/duplicate/out-of-order/
  unregistered/symlink/directory refusals, the measured helper/DDL counts (no cap), ten tables with
  zero views/materialized views/extensions, exactly three command kinds, exactly three lifecycle
  interpreters (`interpret_install`/`interpret_reconcile`/`interpret_dispose`) mapped from
  `interpret_command`, 24 closed protocol errors, exactly one `SECURITY DEFINER` (`advance`),
  PUBLIC EXECUTE 0 and one G lock. Real contention proves `advance` waits on `24,1` and writes
  nothing when cancelled.
- `[CDP6-B2]` the observer LOGIN owns no schema/table/function and has exactly the eight-table
  column whitelist; table SELECT, all column privileges outside the whitelist, DML/TRUNCATE, TEMP,
  CREATE, `advance` EXECUTE and protocol roles are refused. The original admin/service/operator
  LOGINs have no table or column privilege at all, only `advance` EXECUTE, no owner membership, and
  every direct DML is `42501` with a ten-table byte-equal snapshot.
- `[CDP6-B3]` real `command_install`, `command_reconcile` and `command_dispose` commits prove all
  three interpreters; a fourth `command_unknown` is `invalid_args` with ten-table zero write.
- `[CDP6-B4]` one ready reconcile successor; `ensure` on the open slot is
  `stale_generation/ensure_slot_present` zero-write; consuming the successor and replaying the
  identical bytes returns the cached response with no new row; conflicting bytes and a foreign
  LOGIN are zero-write `request_conflict`/`effect_id_conflict`; terminal effect and request UPDATEs
  are `55000`; a second ready reconcile slot is `23505`.
- `[CDP6-B5]` body keys 200/201 and depth 32/33; structural successors 16/17 and duplicate ordinal;
  real `discover_closure` 512/513 and delta-write closure 512/513; a 15-listener activation commits
  16 effects while 16 listeners/17 successors is `invalid_outcome/budget` with no dispatch or child
  row.
- `[CDP6-B6]` the twelve frozen `v24/sql` hashes, the frozen `v24/load.py` + `v24/s1`–`s12` diff
  against `57e2c1e`, `git diff --check`, and the frozen v24 loader's 12-entry self-check and five
  refusal probes.

## Verified W3 baseline

Measured at the W3 gate (physical lines, `str.splitlines()`, same count as the gates):

```text
40_advance.sql  1685
41_lifecycle.sql 1481
42_teardown.sql 1119
43_loop.sql      700
44_events.sql    622
40-49 total     5607      (report-only; 2026-10-28 authorization, no cap)
domain DDL       465      (report-only; bookkeeping 18+19 = 22 separate)
manifest 19 / tables 10 / pg_proc 172 (164 private helpers + 8 trigger guards)
one DEFINER advance / public EXECUTE 0 / command kinds 3 / protocol errors 24
closure 512 / successor 16 unchanged
dp6/test_scanner.py 1311 / dp6/test_recovery.py 1737 / dp6/driver.py 1076 / dp6/test_dispose.py 956
                  (report-only; no cap)
```

The 38-command serial gate evidence (35 inherited + `test_scanner.py` + `test_recovery.py` +
`test_dispose.py`) is recorded in the conformance matrix with exit code and elapsed time. No real
provider socket, external adapter or network call was used; every gate used a disposable pgembed
database and Fake handlers. The W1 corrected gate was reviewed once by Oracle group
`6B696214-99CB-48A0-BEC6-131CBDE8508F` (both lanes: accept with corrections). No W2 or W3 Oracle
review result was persisted; this acceptance session therefore did not launch a duplicate review and
records the direct code audit plus the 38-command run instead.

## Verified W4 baseline

Measured at the W4 gate (physical lines, `str.splitlines()`, same count as the gates):

```text
40_advance.sql  1692      (+7: install_reused payload)
41_lifecycle.sql 1685     (+204: reuse payload/admission/delta/validator/seed/binding)
42_teardown.sql 1119
43_loop.sql      700
44_events.sql    622
40-49 total     5818      (report-only; 2026-10-28 authorization, no cap)
domain DDL       465      (report-only; bookkeeping 18+19 = 22 separate)
manifest 19 / tables 10 / pg_proc 172 (164 private helpers + 8 trigger guards)
one DEFINER advance / public EXECUTE 0 / command kinds 3 / protocol errors 24
closure 512 / successor 16 / address uniqueness / I7 unchanged
dp6/driver.py 1868 / dp6/test_upgrade.py 1215
                  (report-only; no cap)
```

The 39-command serial gate evidence (35 inherited + `test_scanner.py` + `test_recovery.py` +
`test_dispose.py` + `test_upgrade.py`) is recorded in the conformance matrix; per-command sum
283.3 s, wall ≈306.2 s, 39/39 exit 0. No real provider socket, external adapter or network call was
used; every gate used a disposable pgembed database and Fake/absent handlers. No W4 Oracle design
was launched because the reuse admission was proven against the existing ABI (payload, closure,
validator, postcondition, owner/episode, I7, unique address, dispose); the root-install limitation
is recorded as a gated refusal, not worked around.

## Verified W5 final baseline

Measured at the W5 gate on 2026-10-29, start HEAD `ea2a18ca235d69a24b188311e247b8fd137a3d0e`
(branch `v24`, `origin/v24` same SHA). The W5 change is test/docs only; the SQL and runtime
measurements are unchanged from W4:

```text
40_advance.sql  1692
41_lifecycle.sql 1685
42_teardown.sql 1119
43_loop.sql      700
44_events.sql    622
40-49 total     5818      (report-only; 2026-10-28 authorization, no cap)
domain DDL       465      (report-only; bookkeeping 18+19 = 22 separate)
manifest 19 / tables 10 / pg_proc 172 (164 private helpers + 8 trigger guards)
one DEFINER advance / public EXECUTE 0 / command kinds 3 / protocol errors 24
lifecycle interpreters 3 / one G lock / closure 512 / successor 16
dp6/driver.py 1868 / dp6/test_boundaries.py 690   (report-only; no cap)
```

The final 40-command serial evidence (35 inherited + `dp6/test_scanner.py` + `test_recovery.py` +
`test_dispose.py` + `test_upgrade.py` + `test_boundaries.py`) is in the conformance matrix:
**40/40 exit 0, per-command sum 284.449 s, wall 284.5 s**, one `uv run python` process per command,
stop-on-first-nonzero, no skip and no concurrency. Logs are `/tmp/dp6_w5/gates/gate-01..40.log`;
summary `/tmp/dp6_w5/gates.tsv`. Every database was a disposable pgembed instance; all handlers were
Fake or absent; no real provider socket or network call was used. No W5 design blocker was met, so
no scoped Oracle design was opened.

## Known limitations / non-claims

- W5 is a boundary/closeout gate, not a new runtime capability: it added no SQL, driver, table,
  column, command kind, error code, interpreter, scheduler or writer. It verifies the documented
  surfaces but does not make any blocked/debt state disappear.
- No persisted W4 Oracle review result exists. The W4 review attempt ended without a result/export
  (controller failure); W4 acceptance is the direct admission proof plus the 39-command run, **not**
  a review pass. W5 did not launch a duplicate review and does not claim one.
- Root-install rollback is structurally unsupported: a second ownerless fiber violates the
  single-root invariant, so `install_reuse_root` / `switch_target_install_exists` is a gated refusal.
  Non-root child installs are fully supported.
- A rollback resumed after a crash derives its expected service keys from the source fiber's
  retained service-contribution history; an install whose address set changed without a source
  contribution is reported as `blocked/switch_address_missing`, not guessed.
- The HMR descriptor is a host-side pre-deployed file, not a database table; its `operation_uuid` and
  target UUIDs are fixed by the deploy step. The trigger never downloads, imports, invalidates an
  ESM cache or preserves in-process state.
- A switch whose source drain is blocked (unknown debt, missing replay right, live pin/run/child)
  stays `draining`/`blocked`; the operator must resolve the obligation or start an explicit
  rollback. There is no timeout-based escalation.
- W3's 38-command and W4's 39-command evidence are historical; the W5 40-command run supersedes
  them. `CDP6-B` and the W5 closeout are implemented and passed, without weakening the inherited
  boundary gates.
- DP6 does not claim multi-host correctness, global fairness enforced by the database, external
  exactly-once, automatic terminal-unknown resolution, seamless version switching or an artifact
  store. The HMR boundary remains a host-side trigger, not an in-process module swap.
- Automatic terminal-unknown resolution is a design gate, not a W3 deliverable: an out-of-band
  compensation has no approved ABI, so the debt stays blocked (CDP6-U6).
- Below a debt, `blocks` names the obligation classes touched by raw facts; it is a diagnostic
  label, not a planner verdict, and a descendant debt reports its own install state rather than an
  ancestor's `dispose_pending`.
- `host_io` and non-host listener execution remain unsupported/blocked; no real adapter is used by any
  gate.
- Unknown effect outcomes and inverse-unknown contributions remain debt/`blocked_unknown`; DP6 never
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
- A coalesced dispose refresh while a reconcile slot is open keeps the inherited `wait_slot` →
  committed empty-receipt contract (DP3-D5). It is not claimed as zero-write; the inverse-unknown
  debt path is the one proven to be write-free.
- No new finite line cap was set. The old 5500/700/900 assertions are measurement-only; all required
  file/manifest and semantic/ACL/boundary negatives remain.
