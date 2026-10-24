# v24 S5 cleanup closure — final

Authority: [S5 plan](../../docs/plans/v24-s5-cleanup-2026-10-24.md) §4 (C24–C27), §7, §12.1–12.5. **S5 is complete: W1–W4 implemented, W5 closeout, all eight gates exit 0.** The local milestone commit message is `v24: close S5 cleanup closure (G4)`; it is not pushed.

## Layout and load

```text
00 → 10 → 20 → 30 → 40 → 45 → 46_cleanup → 47 → 48 → 50
```

`46_cleanup.sql` is inserted between `45_capability.sql` and `47_verbs.sql` in `v24/load.py`'s `CANONICAL_ORDER`/`SQL_LOAD_ORDER` and in the `v24/s1/setup_db.py` self-check fixture. It holds twelve `SECURITY INVOKER` helpers: `cleanup_edges`, `cleanup_closure`, `cleanup_cycle`, `cleanup_graph`, `cleanup_pending`, `cleanup_slots`, `install_disposed_ok`, `install_disposed_ok_except_release`, `cleanup_close_closure`, `scope_closable`, `deactivate_stage`, `dispose_stage`. It adds no tables, columns, indexes, grants, or `SECURITY DEFINER`; `advance` remains the only writable DEFINER.

## Contracts C24–C27

| Contract | Frozen behavior |
|---|---|
| C24 cleanup order | Merged owner+dependency DAG: child install before owner, consumer before provider, one slot release per advance by `contribution_seq DESC`, cycle → W1 `cleanup_cycle`. |
| C25 inspect convergence | `inspect_resource` is claimable and settles `known`/`absent`/`unknown`; deterministic id, byte-equal target reservation, matching target digest; `resource_quiesced_at` only on success. |
| C26 scope close | Command-driven phase machine `request → drain → retire → cascade → barrier → finalize`; one phase per new request key; `closed_at` only in finalize; child scope before parent; no new admission after `close_requested_at`. |
| C27 full dispose closure | Tombstone only after all six obligations; owner cascade child-first; dependency order via live-pin barrier; retry states for failure/unknown; contribution withdrawal before episode close. |

## Owner and dependency order

The graph is built only from existing columns. An owner edge is `child_install → owner_install` through the immutable `(owner_fiber_id, owner_episode_id)` pair (the episode must exist; `current_episode_id` is never consulted). A dependency edge is `consumer_install → provider_install` for every live pin, via `consumer_episode_id` or `consumer_run_id → runs.owner_fiber_id`, to `provider_episode_id`. `cleanup_closure` walks this scope's installs, their transitive owner descendants, and dependency neighbours in both directions; admission is not tightened (D-S5-10).

`cleanup_graph` returns a bounded topological order. `depth` is the longest-path-to-sink rank over simple paths inside the closure (0 for a sink), capped at 64 edges; on the acyclic graphs S5 accepts, every edge `u → v` has `rank(u) > rank(v)`, so `ORDER BY depth DESC` emits child before owner and consumer before provider.

`dispose_stage` uses iterative arrays, not recursive SQL. Pass 1 marks the owner subtree `dispose_pending` parent-first (stamping `dispose_effect` only on first entry); pass 2 walks reverse discovery order, so children release before owners. A release id is `md5(by_effect||':host_release:'||install_id||':0')`; an existing `ready|claimed` release is reused instead of duplicated.

`cleanup_cycle` walks both edge kinds and returns a closed path `{A,B,C,A}`, or `{head}` as the fail-closed 65-node sentinel. `dispose_stage` checks the root before touching any row and every queued install before it is updated; any hit aborts the whole stage with W1 `cleanup_cycle`, `detail={path,install_id}`, zero domain writes, one failed command effect and one request. G4-E covers a 3-install owner cycle (path length 4), the defensive admission probe, a queued dependency cycle that discards the accumulated root `dispose_pending`, and the 65-node chain with graph depth ≤64. Those cycles are seeded through direct owner-role DML; no public path is claimed to construct one, and admission's check is defensive (D-S5-9).

## Inspect three-state

The claim shape is exactly `{v:1,install_id,target,target_effect_id,target_reservation,target_request_digest}`, with `target ∈ host_prepare|host_release`. `target_reservation` must byte-equal the target effect's `v24:host_prepare:`/`v24:host_release:` reservation, `target_request_digest` must be its 64-hex digest, and the target must be `unknown` with `resource_quiesced_at IS NULL`. The inspect effect itself must be ordinal 0, have no pin, and be parented by a `command_dispose`/`command_scope_control`/`command_fiber_control` effect.

Its id is `md5(owner_effect::text||':inspect_resource:'||install_id::text||':0')::uuid`; the same command reuses the id and an existing `ready|claimed` inspect, and if no inspect is pending a new dispose key derives a new id. The inspect effect has no separate reservation field — `:inspect_resource:` appears only inside the deterministic id — and the target's reservation is carried unchanged in `target_reservation`.

| target | `known` | `absent` | `unknown` |
|---|---|---|---|
| `host_prepare` | `preparing|prepare_unknown → installed` | `→ prepare_failed` | keep original state; inspect again later |
| `host_release` | `dispose_pending → disposed` (no second release) | stay pending; new key emits a fresh release (new id/reservation) | stay pending; new key emits another inspect; never re-release |

Only an inspect success (`known` or `absent`) sets `resource_quiesced_at=now()` on the inspected target effect; the inspect effect's own column stays NULL for success, failure, and unknown. A failed `host_release` has a quiescence proof and is retried with a new key, new effect, and new reservation. An `unknown` release is never re-released before a successful inspect: a new key inspects the same target reservation, and a failed/unknown inspect clears nothing.

## Scope close phases

`close` enters through `command_scope_control`; a same request key replays the first response. Each new key executes exactly one phase and emits exactly one `scope_close_phase` event. `closed_at` is written only by finalize, and only when `scope_closable` returns `ok`.

`request` writes `close_requested_at` and `scope_close_requested`; `drain` writes `close_intent={kind:'close'}` to at most 8 non-terminal runs but never rewrites run status or releases run pins (terminality remains C23's seal, D-S5-1); `retire` updates at most 8 of this scope's undisposed fibers (`want_on=false`, `control_seq+1`, active episode `retiring`, slots withdrawn); `cascade` runs `dispose_stage(...,'close')` for at most 16 rows/successors, ordering installs by `scope_depth DESC` so child scopes go first; `barrier` records `pending` (`{runs,fibers,installs,children}`), `blockers`, and `ok`; `finalize` writes `closed_at` and `scope_closed`.

If a barrier is not clean, a new key re-enters the earliest incomplete phase (drain, retire, cascade) rather than finalizing early. `scope_closable` requires no open child scopes, no undisposed installs or fibers, no non-terminal runs, no live pins, and no `ready|claimed` or `unknown`-without-quiesced host/inspect effects. Child-before-parent is enforced by the child-scope count; G4-G asserts `child.closed_at < parent.closed_at`.

After `close_requested_at` is set, `create_child`, `install`, `start`, and `fiber_control(on)` return W1 `scope_closed`. The first three write no domain rows; `fiber_control(on)` changes only the existing W1 `fibers.failure_seq`/`failure` columns. There is no worker, `LISTEN`, or automatic progress: only a new request key advances the scope.

## Dispose stages

`deactivate_stage(fiber, by_effect, mode)` is shared by `fiber_control(off)` (`control`) and `dispose_stage` (`command|cascade|close`). It locks the fiber and its current/open episode. An active episode becomes `retiring` and up to 5 unreleased slots are withdrawn; non-control modes stop after that retire stage. With a clear barrier, `control` continues in the same call. The barrier is live provider pins on the episode/fiber, undisposed child installs attached to the fiber, and `ready|claimed` or `unknown`-without-quiesced host/inspect effects for the install. It then releases up to 8 consumer-side pins held by the episode (provider pins are never released by the provider); when that pin batch is drained it releases exactly one slot — the maximum `contribution_seq` — and closes the episode (`state='closed'`, `closed_at`, `current_episode_id=NULL`) only when every slot is released, the barrier is clear, and children are disposed. It never writes `fibers.disposed_at`.

`dispose_stage` keeps the owner cascade bounded. Pass 1 marks the owner subtree `dispose_pending` parent-first (`prepare_failed` takes the direct-tombstone path instead); pass 2 works one fiber stage per install per advance. A retire, a non-final contribution release, or a close-only stage returns to the caller; only the stage that releases the final contribution and leaves no other fiber work continues to the release/tombstone path. Reverse-dependency order is enforced by the pin barrier: a provider slot cannot release while a consumer holds a live pin, and the consumer's off/cascade releases it.

The six `install_disposed_ok` obligations are: (1) every fiber is tombstoned; (2) every episode is closed; (3) every slot is released; (4) every child install found through the fixed owner pair is disposed; (5) no `ready|claimed` host/inspect effect and no `unknown`-without-quiesced effect references the install, excluding the effect being settled or quiesced in this delta; (6) no `cleanup_cycle` reaches it. `install_disposed_ok_except_release` is the pre-release form covering the first four, unknown effects, and cycle; the caller still judges `ready|claimed` reuse. The applier recomputes `install_disposed_ok` before a release success, an inspect `known`, a command direct tombstone, and a close direct tombstone.

Retry states: release `failure` (quiesced set) keeps `dispose_pending`, and a new key emits a new release (new effect id/reservation); release `unknown` (quiesced NULL) keeps `dispose_pending`, and a new key emits only an inspect against the same target reservation; a settled release replays the first response for the same key and returns `already_terminal` for a new key (domain zero write, one failed effect/request); a `host_prepare` receipt during `dispose_pending` is `receipt_conflict`. A `prepare_failed` install that never had a successful prepare tombstones directly with zero releases and `install_disposed{released:false}`; if the same stage did fiber work, that tombstone waits for the next key.

Both stages are bounded: `deactivate_stage` writes at most 1 fiber + 1 episode + 5 withdrawals + 8 pin releases + 1 slot release = 16 rows; `dispose_stage` returns `blocked` before a 17th row and caps successors at ordinals 0..15. There is no recursion and no background worker.

## ACL

All twelve cleanup helpers are `SECURITY INVOKER`, owned by `v24_owner`, with `SET search_path = pg_catalog, v24`; none has a protocol-role EXECUTE grant. The `50_permissions.sql` fail-closed block still sees exactly six `SECURITY DEFINER` functions: `advance` (the only writable one) plus the S3 read-only allowlist `resolve`, `poll`, `wait_check`, `run_owner`, `run_projection`, with their shape checks unchanged. `46_cleanup.sql` contains no `GRANT` and no `prosecdef=true`. `advance` reaches the helpers through its command interpreters; the read helpers are exercised by the owner connection in the gate. The three protocol roles still hold zero table privileges, and G1-A/G1-P remain green.

## Actual verification — 2026-10-24

Controller-run from `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` on branch `v24` (HEAD `2272b71`, PostgreSQL 18.4, psycopg2 2.9.12), eight commands serially; raw exit codes:

| command | exit code |
|---|---:|
| `uv run python v24/load.py` | 0 |
| `uv run python v24/s1/setup_db.py --self-check` | 0 |
| `uv run python v24/s1/test_ddl.py` | 0 |
| `uv run python v24/s1/test_g1.py` | 0 |
| `uv run python v24/s2/test_g3a.py` | 0 |
| `uv run python v24/s3/test_g2.py` | 0 |
| `uv run python v24/s4/test_g2b.py` | 0 |
| `uv run python v24/s5/test_g4.py` | 0 |

`test_g4.py` prints `[passed] v24 S5 W1-W4`; G4-A…Q are all present, including the eight G4-M negatives and the extra W1 cascade probe. All 23 `error_v1` codes have a producer (23 produced / 0 unproduced). G4-Q's `cleanup_pending` sequence is `[6,6,4,4,2,2,0]`: non-increasing, with a strict drop only when a counted install/effect obligation clears.

## Implementation disclosures

- No `v24/s5/fake_cleanup_host.py` was created. Release and inspect receipts are submitted directly through `advance`; prepare reuses the S1 fixture.
- Inspect and close settlement are inlined in the existing delta appliers in `40_interpreters.sql`: S1 G1-A pins the writable-function allowlist and `test_g1.py` is outside the S5 change set. The semantics follow §5.5; only the separate applier function names are absent.
- The `30_advance.sql` child-install closure edge was not extended. `dispose_stage` locks the children it walks inside the bounded cascade; a wider lock/closure edge is left to S7.
- `cleanup_graph.depth` is the longest-path-to-sink rank (0 for a sink), not a seed depth. That rank is what makes `ORDER BY depth DESC` child-before-owner and consumer-before-provider for every edge.
- Stage errors use `write:true` with a failed command effect and its request row, matching G4-E's W1 write class; the §5.2 draft's `write:false` is not used.
- `cleanup_pending` is non-increasing, not strictly decreasing. Retire and single-slot-release stages can leave it unchanged because slots and pins are not counted; it drops only when a counted run/install/fiber/child-scope/host-effect obligation clears.
- The inspect request uses the W2-frozen `target_*` key names; C25's draft top-level `reservation`/`request_digest` names were superseded by §12.2.

## Boundaries (not covered by S5)

- Crash recovery, lease reclaim, and automatic inspect are S6. S5 leaves an abandoned `claimed` effect alone and needs a new command key to make progress.
- The full three-plane concurrency matrix is S7. S5 proves only serial, single-connection request-key phases and one bounded phase per key: ≤16 rows, ≤16 successors, no recursive stage calls, no background worker. It makes no concurrent interleaving or lock-order claim.
- `closed_at`, `disposed`, and `resource_quiesced_at` are facts S6 consumes; S5 does not implement a recovery or reclaim state machine over them.
- FakeHost fixtures and direct receipts are in-process and are not transport proofs; no socket, real host, or external IO is exercised.
