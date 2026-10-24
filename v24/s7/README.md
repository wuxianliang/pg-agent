# v24 S7 — G6 concurrency evidence (W1 matrix complete)

Status: **W1 matrix complete**. All 16 G6 matrix bodies (`G6-A1`, `G6-B1`–`B3`,
`G6-C1`–`C3`, `D1`, `E1`, `F1`, `G6-G1`–`G3`, `H1`–`H3`) plus `G6-N1a`/`N1b`
are implemented and green. G6 is still **not** a gate: W2 owns the negatives
(`N2`–`N9`), the lock audits (`L1`–`L5`), the no-argument full run, the declared
cell-2 `G3b-5` closeout rerun and the closeout artifacts. No G6/11-of-11 claim
is made here.

Plan: `docs/plans/v24-s7-concurrency-2026-10-24.md` §4–§5, §8.1. Evidence only:
no SQL, no DDL, no loader change, no product change, no new error code.

## Run

```bash
# W1 matrix checkpoint (17 selected; not the full gate)
uv run python v24/s7/test_g6.py --only g6_a,g6_b,g6_c,g6_d,g6_e,g6_f,g6_g,g6_h,n1

# individual assertion
uv run python v24/s7/test_g6.py --only g6_n1

# the no-argument full gate belongs to W2 and is intentionally refused here
uv run python v24/s7/test_g6.py        # SystemExit: full gate is W2
```

`--only` accepts exact names (`g6_b2`) and group prefixes (`g6_a`, `g6_b`, `n1`,
…). Groups expand deterministically; an unimplemented name aborts with a
message naming the selector. Exit code 0 means every selected assertion ran and
every tag printed exactly one result line.

## Evidence form

Ordering is never inferred from "the command succeeded" and never from a sleep.
A writer that returned from a public wrapper keeps its transaction open, so the
transaction-scoped `pg_advisory_xact_lock(24,1)` (G) stays held; a second real
backend is then proven to queue on G with `pg_blocking_pids()` plus an ungranted
advisory `pg_locks` row (`classid=24, objid=1, objsubid=2`). Both transactions
commit after release, and the ten-table snapshot diff is asserted exactly.

```text
[G6-<ID>] holder=<role:pid> waiter=<role:pid> blocking_pids=<{...}> ungranted_advisory=<n> order=<first->second> diff=<table:+added/~changed/-removed> assert=<falsifiable claim>
[G6-<ID>-lock] wait_graph=<pid->{blockers}> cycle=false advisory_only=true winner=G
[G6-<ID>-zero] sha=<ten-table fingerprint> diff=zero-ten-tables assert=<read verb wrote nothing>
```

Two-order cells print one bare result line for order 1 (`[G6-X]`) and one
suffixed line for order 2 (`[G6-X-order2]`), exactly once each; `N1` is the one
split-tag cell (`G6-N1a`/`N1b`). `-lock`/`-zero` lines are extra evidence for the
same tag and are not counted as separate assertions.

## Harness (`g6_support.py`)

| helper | role |
|---|---|
| `snapshot` / `diff` / `fingerprint` / `format_diff` | thin wrappers over `v24/s6/g5_support.py` (no second ten-table implementation) |
| `held_g` | explicit `pg_advisory_xact_lock(24,1)` for controls; caller commits/rolls back |
| `wait_for_g_block` | deadline-bounded (no sleep) proof that a waiter queues on G: `pg_blocking_pids`, ungranted advisory row, holder `idle in transaction`, no product write lock held by the waiter |
| `assert_no_wait_cycle` | wait-for graph over live pids, cycle detection, "blocker is G", no non-G wait, no product write lock held by a waiter |
| `held_open_then_probe` | uncommitted writer + independent reader; reader must not block (`blocking_pids={}`), must take no advisory/tuple/relation write lock, and the ten-table snapshot around the committed read must be identical |
| `two_orders` | runs `first->second` and `second->first` through `ordered_advance_race`; a missing block is a failure |

`test_g6.py` adds `first_then_second`, which also tolerates a second command
that returns a W1 error envelope (a response is not a crash), and
`start_once`/`start_run`, which separate "leave the transaction open for the
race" from "commit".

## 18-cell map (§7: 6 rows × 3 columns)

| # | §7 cell | assertion | status in this checkpoint |
|---:|---|---|---|
| 1 | start × install/activate | `G6-A1` (+ order-2 `A1b`) | **implemented / green** |
| 2 | start × deactivate/retire | — (`G3b-5` rerun at closeout) | **not a G6 body** (plan §5.2); closeout rerun pending W2 |
| 3 | start × dispose | `G6-N1a`/`N1b` | **implemented / green** |
| 4 | poll/wait × install/activate | `G6-B1` | **implemented / green** |
| 5 | poll/wait × deactivate/retire | `G6-B2` | **implemented / green** |
| 6 | poll/wait × dispose | `G6-B3` | **implemented / green** |
| 7 | cancel × install/activate | `G6-C1` | **implemented / green** |
| 8 | cancel × deactivate/retire | `G6-C2` + `G6-N5` | **G6-C2 green**; N5 pending W2 |
| 9 | cancel × dispose | `G6-C3` | **implemented / green** |
| 10 | steer × install/activate | `G6-D1` + `G6-N3` | **G6-D1 green**; N3 pending W2 |
| 11 | steer × deactivate/retire | `G6-E1` + `G6-N4` | **G6-E1 green**; N4 pending W2 |
| 12 | steer × dispose | `G6-F1` | **implemented / green** |
| 13 | respond × install/activate | `G6-G1` | **implemented / green** |
| 14 | respond × deactivate/retire | `G6-G2` + `G6-N2` | **G6-G2 green**; N2 pending W2 |
| 15 | respond × dispose | `G6-G3` | **implemented / green** |
| 16 | model/tool × install/activate | `G6-H1` + `G6-N9` | **G6-H1 green**; N9 pending W2 |
| 17 | model/tool × deactivate/retire | `G6-H2` + `G6-N5` | **G6-H2 green**; N5 pending W2 |
| 18 | model/tool × dispose | `G6-H3` | **implemented / green** |

No cell is marked "covered" without a result line; cell 2 is the plan's declared
"rerun only" intersection and is not counted as a G6 body.

## Fixture notes (no spec change)

- **Activation pins require a dependency.** `fiber_control(on)` creates an
  activation pin only when the activated install declares `requires`. `G6-A1`
  therefore gives the dependent fiber B a `requires: base` provider so the
  "activation pin unchanged by start" assertion is real. A dependency-free
  activation creates no pin (the `G3b-4` fixture shape), and `G6-B1` asserts
  exactly that (`pins` untouched).
- **A1 seeds the fiber `want_on=false`, not `true`.** With `current_episode_id
  NULL` and no episode, `v24.start` is refused `provider_unavailable` W1 either
  way; seeding `false` makes the following `fiber_control(on)` a real
  transition (the same shape as `pin_barrier_fixture`) instead of an
  already-on no-op.
- **The run pin must be real.** A dependency-free start creates no run pin and
  would make off/dispose vacuously non-blocking. Every off/dispose cell starts
  the run with a `dep`/`base` requirement so the first command owns a live run
  pin; the self-provide shape binds that pin to the same fiber's episode/slot.
- **Waiting interactions and T2 claims use the public path.** Respond cells are
  built with real `start → claim → settle(interaction)`; the S4
  `produce_waiting_interaction` helper starts a dependency-free run with no pin,
  so it cannot exercise the retire barrier. T2 cells use a real `claim_effect`
  and then `v24.advance` with the exact receipt.
- **`model_call.pin_id` is always NULL.** Only a `tool_call` successor binds a
  run pin. C2/E1 therefore use a claimed tool to retain the pin; the model/T2
  cells use the pin the start command already created.
- **H2/H3 "late" T2 is current-generation.** Off/dispose do not advance
  `runs.driving_generation`, so a post-off/post-dispose T2 still matches the
  frozen generation: it records the exact fact/cost and publishes exactly one
  continuation on that same generation, creates no new pin and does not revive
  the install. Genuinely old-generation late receipts are W2's `N5`/`N8`
  (cancel/steer generations), not claimed here.
- **Observers are separate connections.** After `SET ROLE v24_owner`,
  `pg_stat_activity.state` is invisible for other roles, so the reader-state
  probe uses a privileged autocommit observer. It only reads
  `pg_stat_activity`/`pg_locks`; it never writes and never takes G.
- **Readers stay in transaction.** The poll/wait reader keeps its transaction
  open until the writer commits, which is what makes "reader saw the old
  committed state" and "reader took no lock" simultaneously checkable.
- **All writes go through public wrappers** (`v24.start`,
  `v24.fiber_control`, `v24.dispose`, `v24.cancel`, `v24.steer`,
  `v24.respond`, `v24.advance`); domain rows are read by the owner fixture
  connection and seeded only to build initial state.

## Mechanical guards

- No `sleep` and no socket in `v24/s7/**`; ordering is held-G/barrier only.
- `git diff --exit-code -- v24/sql v24/load.py` stays empty; the 24-code error
  set, loader order and DDL are untouched.
- Every gate run is sequential: the fixture DROPs/CREATEs one database.

## Debt / not claimed

- This checkpoint does **not** claim G6 green, 11/11, W2, or any W2 negative.
- No starvation/fairness claim (`D-S7-2`), no real provider/network, no
  cross-host lease, no G5 crash-window re-test.
- `D-S7-1` (dispose closure locking) and `D-S7-3` (cross-scope child install)
  remain open until W2's `N7`/closeout work; `D-S7-2` has no starvation/fairness
  claim either. None of the three is silently assumed.
