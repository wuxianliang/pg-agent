# v24 S7 — G6 concurrency evidence (W2 complete / G6 green)

Status: **W2 complete / G6 green** (2026-10-24). The no-argument
`uv run python v24/s7/test_g6.py` selects all **30/30 IDs** (16 matrix bodies,
9 forced negatives `N1`–`N9`, 5 lock-order audits `L1`–`L5`) and exits 0. The
S7 closeout list is **11/11** (the ten existing `v24` gates plus full G6).
W1 (matrix + harness) and W2 (negatives, lock audits, full run, final 18-cell
map, closeout artifacts) are both complete. S7 remains **evidence-only**: Fake
fixtures only, no product change (no SQL, DDL, loader or error-code change),
no real provider/network.

Plan: `docs/plans/v24-s7-concurrency-2026-10-24.md` §4–§5, §8.1–§8.3.

## Run

```bash
# the gate: no argument, all 30 IDs
uv run python v24/s7/test_g6.py

# subset/debug path only (never a gate claim), e.g. the W1 matrix subset
uv run python v24/s7/test_g6.py --only g6_a,g6_b,g6_c,g6_d,g6_e,g6_f,g6_g,g6_h,n1

# one assertion
uv run python v24/s7/test_g6.py --only g6_n1
```

The no-argument full run **is** the gate: exit code 0 means all thirty IDs ran
and every tag printed exactly one result line. Its final line is:

```text
[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5
```

`--only` accepts exact names (`g6_b2`) and group prefixes (`g6_a`, `g6_b`,
`n1`, …) and is a **subset/debug path**, not the gate. A selector the gate
does not implement remains a hard error: the run prints the offending selector
and aborts before executing any assertion (`--only: unknown selector 'g6_n99'`).
Exit code 0 for a subset means every selected assertion ran and every selected
tag printed exactly one result line.

## 30-ID gate surface

The gate counts **IDs**, not result lines: **16 matrix + 9 negatives + 5 lock
audits = 30**. Every row below is green in the no-argument run.

| # | ID | group | assertion (what its result line proves) | result tags | status |
|---:|---|---|---|---|---|
| 1 | `A1` | matrix cell 1 | start × activate: a start blocked on G binds the just-activated episode; the activation pin is unchanged by start | `G6-A1` / `G6-A1b` (two orders) | green |
| 2 | `B1` | matrix cell 4 | poll/wait × activate: the reader never queues on G and writes zero rows | `G6-B1` / `G6-B1-zero` | green |
| 3 | `B2` | matrix cell 5 | poll/wait × retire: the reader sees the old committed state, takes no G or non-G write lock, zero writes | `G6-B2` / `G6-B2-zero` | green |
| 4 | `B3` | matrix cell 6 | poll/wait × dispose: the same read-only proof while dispose is open | `G6-B3` / `G6-B3-zero` | green |
| 5 | `C1` | matrix cell 7 | cancel × activate: cancel seals only run1 and releases its pin; the queued start creates run2 on the same activated episode; activation pin and slot stay intact | `G6-C1` / `G6-C1-order2` | green |
| 6 | `C2` | matrix cell 8 | cancel × retire: the claimed tool keeps the run pin; off is deferred until settle, then slot/episode release | `G6-C2` / `G6-C2-order2` | green |
| 7 | `C3` | matrix cell 9 | cancel × dispose: dispose never tombstones before the run pin is clear; both orders drain to disposed | `G6-C3` / `G6-C3-order2` | green |
| 8 | `D1` | matrix cell 10 | steer × activate: activation pin byte-identical; steer emits no model; the new run binds the same episode; pending steer carries generation/epoch 2 | `G6-D1` / `G6-D1-order2` | green |
| 9 | `E1` | matrix cell 11 | steer × retire: steer follows the old pin; retire-first still accepts the active steer; exactly one `cause='steer'` model; slot released after the pin | `G6-E1` / `G6-E1-order2` | green |
| 10 | `F1` | matrix cell 12 | steer × dispose: continuity cannot revive a disposed/pending fiber; the order-2 steer is `already_terminal` W1 with zero domain write and `disposed_at` only after the drain | `G6-F1` / `G6-F1-order2` | green |
| 11 | `G1` | matrix cell 13 | respond × activate: respond consumes only the original interaction; exactly one continuation; run2 binds the same episode; no second interaction | `G6-G1` / `G6-G1-order2` | green |
| 12 | `G2` | matrix cell 14 | respond × retire: the answer commits while the slot waits; only one interaction; release only after continuation terminal and pin release | `G6-G2` / `G6-G2-order2` | green |
| 13 | `G3` | matrix cell 15 | respond × dispose: dispose never cancels a live interaction; order-2 respond is `already_terminal` W1 with zero revival; `disposed_at` only after the drain | `G6-G3` / `G6-G3-order2` | green |
| 14 | `H1` | matrix cell 16 | model/tool × activate: the T2 receipt is exact on the frozen generation; one continuation; run2 resolves the current episode; turn/cost counted once | `G6-H1` / `G6-H1-order2` | green |
| 15 | `H2` | matrix cell 17 | model/tool × retire: the receipt is a fact and the pin gates release; late T2 records fact/cost on the frozen generation with no new pin/slot; `requests` is `(2,0,0)` | `G6-H2` / `G6-H2-order2` | green |
| 16 | `H3` | matrix cell 18 | model/tool × dispose: external results never revive the install; order-2 late T2 records fact/cost only; drain is off → new-key dispose → `host_release` | `G6-H3` / `G6-H3-order2` | green |
| 17 | `N1` | negative | start/dispose both orders: start-first run pin blocks dispose (pending, no tombstone); dispose-first tombstones, then start is `provider_unavailable` W1 with zero run | `G6-N1a` / `G6-N1b` | green |
| 18 | `N2` | negative | respond/cancel both orders: respond-first consumes the interaction and readies one successor; cancel-first is `already_terminal` W1 with zero new model; G decides the winner | `G6-N2a` / `G6-N2b` | green |
| 19 | `N3` | negative | terminal steer: the final T2 holds G; the queued steer returns `already_terminal` W1, writes no domain rows and leaves run result/`ended_at`/cost unchanged | `G6-N3` | green |
| 20 | `N4` | negative | steer/withdraw: off-first withdraws the slot; the active steer still follows the old pin and writes `pending_steer`; settlement yields exactly one `cause='steer'` model and the slot is not released early | `G6-N4` | green |
| 21 | `N5` | negative | cancel/retire plus a late T2, both orders: the claimed tool keeps the run pin live until IO silence; the late T2 records fact/cost with zero old-generation successor; the second off drains | `G6-N5a` / `G6-N5b` | green |
| 22 | `N6` | negative | scope close vs an installed install (`N6a`) and a `prepare_unknown` install (`N6b`): no premature `closed`; `N6b` follows `prepare_failed` → direct tombstone (0 `host_release`) → closed | `G6-N6a` / `G6-N6b` | green |
| 23 | `N7` | negative | owner retire/dispose vs a real cross-scope child install (`new_child_scope` + `admit_install(owner_fiber=…)`), both orders: child-first never tombstones the owner; owner-first refuses the child `owner_closing` W1 with zero child | `G6-N7a` / `G6-N7b` | green |
| 24 | `N8` | negative | T2/cancel both orders: T2-first records the receipt/cost and one ready successor that cancel archives; cancel-first lets the late T2 record fact/cost with zero successor while the claimed tool keeps the pin | `G6-N8a` / `G6-N8b` | green |
| 25 | `N9` | negative | same spawn key/different canonical bytes: exactly one child; the loser gets `receipt_conflict`; the new parent outcome gets the 24th code `spawn_key_conflict`; ten tables byte-equal; one child/effect and one grant | `G6-N9` | green |
| 26 | `L1` | lock audit | start/dispose counterexample: the waiter queues on G only, takes no product row/relation lock before G, wait graph has no cycle, winner is G | `G6-L1a` / `G6-L1b` | green |
| 27 | `L2` | lock audit | cancel/retire counterexample: the cancel/off waiter waits on G, not on the run pin or fiber row; pin releases only after silence; no cycle | `G6-L2a` / `G6-L2b` | green |
| 28 | `L3` | lock audit | spawn parent/child vs cancel parent/child: both runs take their row locks under G in UUID order; no deadlock or blocking-pids cycle; both cancelled; winner is G | `G6-L3a` / `G6-L3b` | green |
| 29 | `L4` | lock audit | two provider switches: the second off queues on G before touching any slot; release follows commit order, not call order; no cycle | `G6-L4a` / `G6-L4b` | green |
| 30 | `L5` | lock audit | respond/cancel: the interaction is a projection on the run row, not a separate lock object; the waiter queues on G alone; no cycle | `G6-L5a` / `G6-L5b` | green |

Twelve IDs carry explicit two-order sub-tags: `A1`/`A1b`, `N1a`/`N1b`,
`N2a`/`N2b`, `N5a`/`N5b`, `N6a`/`N6b`, `N7a`/`N7b`, `N8a`/`N8b`, and
`L1a`/`L1b` … `L5a`/`L5b`. The other eighteen IDs are single-tag IDs:
`B1`–`B3`, `C1`–`C3`, `D1`, `E1`, `F1`, `G1`–`G3`, `H1`–`H3`, `N3`, `N4`,
`N9`. A matrix body that exercises both orders may still print a suffixed
`G6-<ID>-order2` line (for example `G6-C1-order2`); that is the same ID, not a
new one. Each result tag prints exactly once; a sub-tag is not an extra ID.

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

The count is by ID: all thirty IDs are accounted for, and every result tag
prints exactly once. A two-order sub-tag (for example `G6-N1a` and `G6-N1b`)
prints once each, and a matrix body with a reverse order prints one additional
`-order2` line (for example `G6-C1-order2`); `A1` is the exception, whose
reverse order prints `G6-A1b`. `-lock`/`-zero` lines are extra
evidence for the same tag and are never counted as separate assertions.

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

| # | §7 cell | assertion | final status |
|---:|---|---|---|
| 1 | start × install/activate | `G6-A1` (`A1`/`A1b`) | **final / green** |
| 2 | start × deactivate/retire | `G3b-5` closeout rerun only — not a G6 body | **final / green** |
| 3 | start × dispose | `G6-N1a`/`G6-N1b` | **final / green** |
| 4 | poll/wait × install/activate | `G6-B1` | **final / green** |
| 5 | poll/wait × deactivate/retire | `G6-B2` | **final / green** |
| 6 | poll/wait × dispose | `G6-B3` | **final / green** |
| 7 | cancel × install/activate | `G6-C1` | **final / green** |
| 8 | cancel × deactivate/retire | `G6-C2` + `G6-N5` | **final / green** |
| 9 | cancel × dispose | `G6-C3` | **final / green** |
| 10 | steer × install/activate | `G6-D1` + `G6-N3` | **final / green** |
| 11 | steer × deactivate/retire | `G6-E1` + `G6-N4` | **final / green** |
| 12 | steer × dispose | `G6-F1` | **final / green** |
| 13 | respond × install/activate | `G6-G1` | **final / green** |
| 14 | respond × deactivate/retire | `G6-G2` + `G6-N2` | **final / green** |
| 15 | respond × dispose | `G6-G3` | **final / green** |
| 16 | model/tool × install/activate | `G6-H1` + `G6-N9` | **final / green** |
| 17 | model/tool × deactivate/retire | `G6-H2` + `G6-N5` | **final / green** |
| 18 | model/tool × dispose | `G6-H3` | **final / green** |

No cell is empty: every row is green. Cell 2 is the plan's declared "rerun
only" intersection: its evidence is the `G3b-5` closeout rerun below, not a G6
body and not a 31st ID. Cell 2 was rerun on 2026-10-24 with
`uv run python v24/s3/test_g2.py` (exit 0); its evidence line is:

```text
[G3b-5] two fresh fixtures/two connections: pg_blocking_pids + waiting advisory pg_locks prove G serialization; start-first/off deferred; off-first/start dependency_unresolved with no run/pin
```

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
- **N6b: `prepare_unknown` + inspect `absent` is the `prepare_failed` path.**
  The real product path is `prepare_failed → direct tombstone (0
  host_release) → closed`, the same shape as `G4-J2`. The plan §5.3 shorthand
  "inspect absent + release → disposed" must be read through this real path;
  this is a documentation clarification, not a weakened assertion.
- **N8b: the run pin is held by the tool child.** `model_call.pin_id` is NULL;
  the run pin is held by the claimed tool child (the `G2b-O` shape), and only
  that tool going silent releases it.
- **H2: `requests` is `(2,0,0)`.** The expectation moved from 3 to 2; this was
  a test-expectation bug, not a product bug, and there is no product change.
- **H2/H3 "late" T2 is current-generation.** Off/dispose do not advance
  `runs.driving_generation`, so a post-off/post-dispose T2 still matches the
  frozen generation: it records the exact fact/cost and publishes exactly one
  continuation on that same generation, creates no new pin and does not revive
  the install. Genuinely old-generation late receipts are covered by `N5`
  (cancel/retire) and `N8` (T2/cancel).
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

## 11/11 closeout commands

Run from the repository root, in this order; all eleven exited 0 on
2026-10-24:

```bash
uv run python v24/load.py
uv run python v24/s1/setup_db.py --self-check
uv run python v24/s1/test_ddl.py
uv run python v24/s1/test_g1.py
uv run python v24/s2/test_g3a.py
uv run python v24/s3/test_g2.py
uv run python v24/s4/test_g2b.py
uv run python v24/s5/test_g4.py
uv run python v24/s6/test_g5.py
uv run python v24/s8/test_g7.py
uv run python v24/s7/test_g6.py
```

The historical S6/S8 closeout count of **10/10** is retained as history: it was
measured before G6 existed. S7 appends full G6 as the eleventh command; G6 does
not replace any of the ten, and their commands, order, assertions and numbering
are unchanged.

## M-H extension check (G8, not a closeout gate)

M-H adds the host read surface and an **extension check**, not a twelfth
closeout command. The 11 commands above, their order and the **11/11** count
are unchanged. The separate check is:

```bash
uv run python v24/s9/test_g8.py
```

No-argument run selects all **23/23** G8 IDs and exits 0 (2026-10-24). It
covers the 9 public host readers, the hidden `host_scope_allowed` helper, the
ACL counts (admin 26 / service 27 / operator 27 EXECUTE; 17 DEFINERs; 27
`GRANT EXECUTE` statements), held-G snapshot reads, pagination, the 64-item
64.00 MiB page, closure slope (`B=3`; `H_ok=509`, `H_bad=510`, `C=512/513`),
lease and recovery edges, D-S6-12 (`G8-D1a`) and D-S8-7 (`G8-D2`). See
[`v24/s9/README.md`](../s9/README.md) for the exact evidence and boundaries.

This extension check does **not** change the historical S7 result: S7 remains
11/11 and its conclusions stand. The G8 run is recorded as
**passed / 23/23** for M-H.

## Mechanical guards

- No `sleep` and no socket in `v24/s7/**`; ordering is held-G/barrier only.
- The historical S7 guard was an empty `git diff --exit-code -- v24/sql
  v24/load.py`. After M-H that command is intentionally non-empty (new
  `49_host_reads.sql`, `50_permissions.sql`, loader registration). The frozen
  nine kernel files still produce an empty diff:
  `git diff --exit-code -- v24/sql/10_schema.sql v24/sql/20_triggers.sql
  v24/sql/30_advance.sql v24/sql/40_interpreters.sql v24/sql/45_capability.sql
  v24/sql/46_cleanup.sql v24/sql/47_verbs.sql v24/sql/48_loop.sql
  v24/sql/49_recovery.sql`; the 24-code error set and ten-table DDL are
  untouched.
- Every gate run is sequential: the fixture DROPs/CREATEs one database.

## Debt / not claimed

- **D-S7-1 (dispose-closure lock order): closed / not triggered.** N7 plus
  L1/L2 found no product lock-order or deadlock bug; this answers D-S5-8's
  dispose-closure question.
- **D-S7-3 (cross-scope child install): not triggered / not needed.** N7
  builds a real cross-scope child with `new_child_scope` +
  `admit_install(owner_fiber=…)` and passes on the public path.
- **D-S7-2 (starvation/fairness): remains an explicit debt.** No
  starvation-freedom or fairness claim is made; that needs a dedicated design
  and evidence.

## Boundaries

- Fake fixtures only: no real provider and no network.
- No cross-host lease claim.
- No starvation/fairness claim (`D-S7-2`).
- No G5 crash-window re-test.
- No multi-host claim.
- Evidence-only: no product change and no new SQL/DDL/loader/error code.
