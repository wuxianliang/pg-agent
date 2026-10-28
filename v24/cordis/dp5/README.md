# Cordis v2 DP5

DP5 delivers the event surface and effective-descriptor resolution on the DP1–DP4 Cordis v2 kernel: listener production registration, `dispatch`/`listener_call` with the five dispatch modes, overlay/intercept effective descriptors, and the design G4 event refinement evidence. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md`.

## Current status

**W1 is implemented, verified and locally committed on top of `ba66776`. The inherited 31-command sequence plus `CDP5-R` passes. W2 has not been started; listener registration, dispatch production, `44_events.sql`, the loader 19-entry change and the event planner do not exist yet.**

W1 delivers:

- exact overlay ABI (`{}` legacy identity, or `{v,services,listeners}` with a services patch map and an empty listeners map in W1);
- recursive object merge, whole replacement for array/scalar/null, semantic descriptor depth ≤4, protected identity fields and unknown-target rejection;
- exact intercept ABI (`{}` or `{v,rules}`), bounded 1–16 unique `(realm,key)` rules, `reject`/`replace`, digest/depth validation, and resolve-time capability/contract compatibility;
- nearest-scope rule selection after realm resolution, with no stacking and no fallback after reject;
- effective descriptors in `resolve`, P1/P2 validation, `activation_total`, committed view, check policy, run bindings, run digests, tool successors, settlement and claim;
- `execution:{descriptor,descriptor_digest}` on configured model/tool claims; the empty-config claim response is byte-compatible with DP4;
- old-run drain from the pinned contribution and frozen committed-view descriptor digest/contract version without requiring a currently available provider;
- the `30_triggers.sql` scope guard freezing `realm_overrides`/`intercept` (SQLSTATE 55000) plus the existing close-tombstone rule.

W1 does **not** deliver listener registration, listener overlay application, dispatch production, `44_events.sql`, the loader 19-entry change, typed event ops, or `CDP5-E/D/B`. The listeners map is shape-required but must be empty: without W2 listener declarations, any listener target is an unknown declaration and is rejected `invalid_args`; W2 replaces that rejection with declared-listener validation. R5–R7 remain W4 work.

## Capacity

The user's uncommitted `41_lifecycle.sql` refactor (one `fiber_chain` walker replacing four PL/pgSQL walkers) and the 5500 helper cap remain the baseline. W1 adds W1 behavior and tests; it does not lower the cap or move helpers outside 40–49.

| Item | B0 | W1 actual |
|---|---:|---:|
| `40_advance.sql` | 1549 | **1567** |
| `41_lifecycle.sql` | 1197 | **1354** |
| `42_teardown.sql` | 1000 | **1007** |
| `43_loop.sql` | 592 | **668** |
| Helper total | 4338 | **4596** |
| `R = 5500 − total` | 1162 | **904** |
| DDL prefix | 461 | **465** |
| Manifest entries | 18 | **18** |
| Private functions | 129 | **138** |
| Domain tables | 10 | **10** |
| `SECURITY DEFINER` / public EXECUTE | `advance` / 0 | `advance` / 0 |

W1 consumed 258 helper lines (4338→4596); `R=904` remains above the plan's 900 admission floor for the next milestone, but it is not a W2/W3 capacity proof. Every later milestone must still measure and stay ≤5500; if the remaining work cannot fit, the plan's §1/§5 re-adjudication rule applies rather than deleting a validator or mode.

DDL grew 461→465 solely from the four-line `scopes` UPDATE guard; the DDL ceiling remains 900. The twelve frozen `v24/sql` hashes, `v24/load.py` (18 entries), and `v24/s1`–`s12` are untouched. `44_events.sql` was not created.

## W1 verification

The inherited 31 commands were rerun in the B0 order (s8 before s7), followed by `CDP5-R`; **32/32 exited 0 in 155 s**, one process at a time. Summary `/tmp/dp5-w1/gates.tsv`; per-command logs `/tmp/dp5-w1/gate-01..32.log`. The delivered gate on its own is:

```bash
uv run python v24/cordis/dp5/test_resolution.py
```

The script is independent, serial, no-network, and uses the existing `dp1/setup_db.py`, `dp2/test_support.py` and `dp4/dp4_support.py` fixtures. It prints:

```text
[CDP5-R1] overlay recursive merge, array/scalar/null replacement, protected identity, unknown target, dual namespace, depth 4/5 and wrapper boundary
[CDP5-R2] nearest replace/reject, realm-first matching, depth 4/5, forged digest and resolve-time contract rejection; production scope_create path
[CDP5-R3] check view/run input/toolset/claim execution all use the effective descriptor; empty configuration keeps the legacy claim shape
[CDP5-R3b] no-config run keeps the DP4 claim shape and raw digest/toolset
[CDP5-R4] withdrawn provider pins still drain with the frozen effective config; frozen contract drift and released pins reject without rebinding
[CDP5-R8] scope realm/intercept UPDATE guard, close tombstone, install overlay immutability and private helper ACL
[passed] CDP5-R (W1: R1-R4/R8; R5-R7 deferred to W4)
```

Coverage is deliberately limited to the delivered W1 surface. R2's listener namespace case asserts the W1 rejection; W2 must replace it with a declared-listener patch success and a cross-namespace duplicate-name case. R4 uses a withdrawn provider contribution (not a retired provider fiber) because DP4's run-liveness check still owns provider-fiber closure; the pinned/frozen effective config is the W1 object under test. R8's handler/replay evidence is produced in R3: a replace descriptor carrying fake `handler_digest`/`replay` fields cannot change `claim_contract`, which still reads `installs.contracts`.

## B0 history

B0 re-adjudication passed capacity admission on 2026-10-28 at HEAD `ba66776` and is retained in the plan §9 and the DP5 matrix/ledger. The worktree is branch `v24`; fetched `origin/v24` is still `4b34bf2`, so the branch is **9 ahead / 0 behind** before the W1 commit. The user reports DP4 was pushed in another session, but this worktree cannot prove the remote target.

DP4 handoff: `348b9b8` W5, `f119429` acceptance correction, `73973d1` settlement-validation hardening, `ba66776` settlement-helper split. `43_loop.sql` was 592 lines / 25 private functions at B0 with no working-tree diff. The inherited 31-command sequence passed **31/31** in **185.9 s** at B0.

## Artifacts

- `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md` — §9 W1 Result and updated status.
- `docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md` — B0 history plus the W1 implementation and the 32-command regression.
- `docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md` — B0 history plus W1 treatment rows and remaining unclaimed scope.
- This README — W1 status, capacity and next action.

## Next action

W2: listener declaration registration and withdrawal (eight-key `listeners`, `registration_plan`, cross-32 iterator, P4 totality, `delete_row` withdrawal, E registration subset). W2 must not produce dispatch, must not introduce `44_events.sql`, and must replace the W1 listeners-map rejection with declared-listener overlay validation. Re-run the 31 inherited commands plus the delivered E subset and the existing W1 gate, then update the artifacts and commit.

## Publication

`AGENTS.md` says push `origin main`, but this worktree is branch `v24` tracking `origin/v24`; the plan's handoff explicitly leaves the target to orchestration or a user-named remote/branch. W1 is committed locally; no push was forced or inferred. If the target is `origin/v24`, fetch first and use an ordinary fast-forward push; if it is `main` or another ref, name it explicitly.
