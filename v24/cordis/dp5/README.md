# Cordis v2 DP5

DP5 delivers the event surface and effective-descriptor resolution on the DP1–DP4 Cordis v2 kernel: listener production registration, `dispatch`/`listener_call` with the five dispatch modes, overlay/intercept effective descriptors, and the design G4 event refinement evidence. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md`.

## Current status

**W1 and W2 are implemented, verified and locally committed. W2 is committed on top of W1 `c3ddd94`. W3 has not been started: dispatch production, `listener_call` execution, host receipts, the event planner and `44_events.sql` do not exist.**

W2 delivers listener registration and revocation only:

- optional manifest fifth key `listeners`, length 0–16, each item an exact eight-key declaration
  `{listener_id,event,mode,priority,filter,exec,contract_version,sync_reads}`;
- `in_db` execs `const`/`acc`/`append`/`fail` with fixed `in_db_v1`; `host` exec requires
  `contracts.listener_call` and inherits its contract version/handler/replay rights;
- `sync_reads` must be the JSON literal `false`; mode, filter, priority, event and listener id are bounded;
- `registration_plan(install)` is the unified `provides ++ listeners` sequence with kind/original index,
  overlay-applied descriptor and independent `contract_version`;
- one P2 iterator/seq/`registered_through` stream across services and listeners, at most 32 appends per batch,
  including a provider whose combined declaration crosses 32 items;
- P4 totality checks every plan item's kind/seq/descriptor/contract/realm-address/inverse and quantity, not just `provides`;
- listener contributions use `realm/key/prev = NULL`, `inverse = {op:"delete_row"}`, and the existing
  `(fiber,episode,event,listener_id)` unique index as the final defence;
- listener overlay targets are now declared-listener validation: only `priority`/`filter` may change, identity
  fields and `exec`/`contract_version`/`sync_reads` are protected, and service/listener namespaces are independent;
- the existing P5 withdrawal and P6 LIFO `delete_row` release now have production listener evidence; rows remain as
  withdrawn/released tombstones and the inverse is immutable.

W2 does **not** deliver:

- dispatch producer, event planner, `dispatch`/`listener_call` execution, host receipts, `ready_effects`, virtual
  receipts or typed event ops (`CDP5-D`, W3);
- snapshot ordering across episodes, not-yet-created snapshot `unavailable`, or a real listener drain; those remain
  W3 D evidence;
- `44_events.sql`, the loader 19-entry change, or the five-file budget tree;
- `CDP5-B` (W5) or R5–R7 (W4).

## Capacity

W2 adds no helper file and does not change the loader or the 5500 cap. W2 measured 40–49 at **4745**, so
`R = 5500 − 4745 = 755`.

| Item | B0 | W1 actual | W2 actual |
|---|---:|---:|---:|
| `40_advance.sql` | 1549 | 1567 | **1589** |
| `41_lifecycle.sql` | 1197 | 1354 | **1473** |
| `42_teardown.sql` | 1000 | 1007 | **1015** |
| `43_loop.sql` | 592 | 668 | **668** |
| Helper total | 4338 | 4596 | **4745** |
| `R = 5500 − total` | 1162 | 904 | **755** |
| DDL prefix | 461 | 465 | **465** |
| Manifest entries | 18 | 18 | **18** |
| Private functions | 129 | 138 | **144** |
| Domain tables | 10 | 10 | **10** |
| `SECURITY DEFINER` / public EXECUTE | `advance` / 0 | `advance` / 0 | **`advance` / 0** |

W2 consumed 149 helper lines (4596→4745): 40 +22, 41 +119, 42 +8, 43 unchanged. No mode, validator, limit or
test was removed to fit. The remaining `R=755` is a measurement, not a W3 capacity proof. `44_events.sql` was not
created; `v24/cordis/load.py` remains 18 entries; the twelve frozen `v24/sql` hashes and `v24/s1`–`s12` are unchanged.

## W2 verification

The inherited 31 commands were rerun in the B0 order (s8 before s7), followed by the W1 `CDP5-R` script and the new
`CDP5-E` script. Each command ran as a separate process, serially; **33/33 exited 0 in 167 s**.
Summary: `/tmp/dp5-w2-final2/gates.tsv`; per-command logs `/tmp/dp5-w2-final2/gate-01..33.log`.

```bash
uv run python v24/cordis/dp5/test_listeners.py
```

The W2 gate is independent, serial, no-network, and reuses the existing `dp1/setup_db.py`, `dp2/test_support.py`,
`dp3/test_teardown.py` and `dp4/dp4_support.py` fixtures. It prints:

```text
[CDP5-E1] legacy four-key and listeners=[] register identically; optional fifth key, unknown keys and declared-listener overlay validation
[CDP5-E2] service+listener total 33 crosses two batches; seq/iterator/plan are continuous; P4 totality activates; a target change after batch one Diverts with no mixed registration
[CDP5-E3] duplicate listener_id and same-episode event/id collision reject; a new episode reuses the same listener_id over the retained released row
[CDP5-E4] forged listener realm/key/prev/inverse/contract/seq/descriptor and missing/extra appends are invalid_outcome with zero write; the unmodified plan commits
[CDP5-E5] 16/17 boundary and invalid mode/filter/exec/contract/sync_reads/identity declarations all reject invalid_args with zero write
[CDP5-E6] production P5 withdraws all listener rows; P6 releases in strict LIFO batches 32..1 then 0..0 and retains the historical listener rows/descriptors/inverse
[CDP5-E7] listeners create no pin/run; fixture provider-owned ready/claimed block P6 as deferred and unknown blocks it as blocked_unknown
[passed] CDP5-E (W2: E1-E7 registration/revocation subset; ordering/unavailable/real drain deferred to W3 D)
```

Coverage is deliberately limited to registration/withdrawal:

| Item | W2 evidence | Not claimed |
|---|---|---|
| E1 | legacy four-key and `listeners=[]` produce the same contribution projection; unknown fifth keys rejected; declared listener overlay patches only `priority`/`filter`; cross-namespace same name | listener ordering |
| E2 | 30 services + 3 listeners = 33; batches 32/1; continuous seq/iterator; P4 activates; target change after batch one Diverts with the prefix intact | cross-episode ordering, snapshot unavailable |
| E3 | duplicate `listener_id`, same-episode `(event,listener_id)` SQLSTATE 23505, new episode reuse over the retained released row | real dispatch identity |
| E4 | forged realm/key/prev/inverse/contract/seq/descriptor, missing/extra appends and forged P4-with-withdrawn-listener are `invalid_outcome` with zero write | dispatch child forging |
| E5 | 16 declared listeners and a contracted host listener register; 17 plus invalid mode/filter/exec/contract/sync_reads/identity reject `invalid_args` with zero write | host execution |
| E6 | production P5 withdrawal, P6 LIFO `contribution_inverse` release in batches 32..1 then 0..0, historical listener rows/descriptors/inverse retained | real listener_call drain |
| E7 | no listener pin/run; fixture provider-owned `listener_call` `ready`/`claimed` make P6 `deferred`, `unknown` makes it `blocked_unknown` | source cross-provider unknown, emit source exit, real host receipts |

The E7 effects are explicitly labelled owner fixtures; they prove the existing P6 barrier facts, not a W2 dispatch
producer. E4’s direct `interpret_reconcile` probe is a validator/fixture path and does not persist a listener call.
W3 D must add the real producer/drain, ordering, unavailable items and host receipt evidence. E6’s batches are P5/P6
ledger evidence, not a claim that a W2 listener was executed.

## W1 retained behavior

W1’s overlay/intercept ABI, effective descriptor/digest resolution, configured model/tool claim `execution`, old-run
drain and the `30_triggers.sql` scope UPDATE guard are unchanged. W2 replaced the W1 blanket listener-overlay rejection
with declared-listener validation. R1 currently keeps its old unknown-target rejection case; E1 adds the declared
success and cross-namespace case. `CDP5-R` still passes R1–R4/R8; R5–R7 remain W4.

## B0 history

B0 re-adjudication passed capacity admission on 2026-10-28 at HEAD `ba66776` and is retained in the plan §9 and the
DP5 matrix/ledger. The worktree is branch `v24`; fetched `origin/v24` is still `4b34bf2`, so the branch was 9 ahead /
0 behind before the W1 commit. The user reports DP4 was pushed in another session, but this worktree cannot prove the
remote target.

DP4 handoff: `348b9b8` W5, `f119429` acceptance correction, `73973d1` settlement-validation hardening, `ba66776`
settlement-helper split. `43_loop.sql` was 592 lines / 25 private functions at B0 with no working-tree diff. The
inherited 31-command sequence passed **31/31** in **185.9 s** at B0. W1 then passed **32/32** in **155 s**; W2 passed
**33/33** on top of that.

## Artifacts

- `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md` — §9 W2 Result and updated status.
- `docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md` — W2 scope, capacity and the 33-command regression.
- `docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md` — W2 treatment rows and remaining unclaimed scope.
- This README — W2 status, capacity and next action.

## Next action

W3: add `44_events.sql`, the loader 19-entry change and the five-file budget tree in one milestone with the p4
producer/snapshot/closure, four typed event ops, virtual receipts, `in_db` cascade, host claim/receipt,
`ready_effects`/`execution`, parent/child IDs, request-response cache consistency, source/provider fences, all
validators/postconditions and `CDP5-D`. W3 must also deliver the ordering, not-yet-created `unavailable` and real
drain evidence that W2 deliberately leaves to D.

## Publication

`AGENTS.md` says push `origin main`, but this worktree is branch `v24` tracking `origin/v24`; the plan’s handoff
explicitly leaves the target to orchestration or a user-named remote/branch. W2 is committed locally; no push was
performed. If the target is `origin/v24`, fetch first and use an ordinary fast-forward push; if it is `main` or another
ref, name it explicitly.
