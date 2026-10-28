# Cordis v2 DP5 Deviation Ledger

This ledger records two B0 passes:

- the initial B0 at HEAD `f119429` on 2026-10-28, which was **blocked** at the then-current 5000 helper cap (`R=680<900`); and
- the B0 **re-adjudication** at HEAD `ba66776` with the user's uncommitted 41 refactor and 5500 cap, which **passes** capacity (`R=1162≥900`) and the 31 inherited gates.

The initial blocked result is kept as history and is not rewritten. No DP1–DP4 acceptance record is rewritten. W1 and W2 are recorded as local, verified milestones; W3+ behavior is not claimed.

## Initial B0 (2026-10-28, HEAD `f119429`) — historical, blocked at 5000

| Date | Item | Baseline / spec | B0 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-28 | Baseline HEAD | Plan records a DP4 planning snapshot; execution must re-record HEAD | Actual HEAD `f119429`, subject `v24: verify Cordis DP4 closing-owner rejection and final gates`; branch `v24`, upstream `origin/v24`; after fetch `origin/v24...HEAD` = `0 7` | `git rev-parse HEAD`; `git rev-list --left-right --count origin/v24...HEAD` |
| 2026-10-28 | DP4 W5 handoff | DP5 starts only after DP4 W5 acceptance | W5 delivered as `348b9b8` plus acceptance correction `f119429`; DP4 README/matrix/ledger and five DP4 gate scripts present | DP4 README; DP4 matrix W5; `git log --oneline origin/v24..HEAD` |
| 2026-10-28 | Capacity measurement | `R=5000−all 40–49 physical lines` | Real tree: 40=1549, 41=1211, 42=1000, 43=560; total **4320**; **R=680** | `[CDP1-K0] helper budget 4320<=5000` |
| 2026-10-28 | Admission threshold | Plan §5: `R<900` means no implementation scaffold, no W1 | **R=680<900, admission invalid.** No `44_events.sql`, no loader/budget change, no W1 | plan §5/§9-B0; initial matrix |
| 2026-10-28 | Old-gate evidence | B0 must run or inspect inherited gates | 31 commands rerun serially on that tree; **31/31 exit 0**, 184 s, s8 before s7 | `/tmp/dp5-b0-gates.tsv`; `/tmp/dp5-b0-gates.log` |
| 2026-10-28 | DDL / manifest / tables | DP4 closeout: DDL 461, manifest 18, ten tables, one DEFINER | Verified unchanged: `tables=10 manifest=18`, `definer=advance public_execute=0 views/extensions=0` | CDP2-B, CDP3-B, CDP4-B1 |
| 2026-10-28 | Publication | AGENTS says push `origin main`; branch is `v24` tracking `origin/v24`; DP4 decision 8 says local-only until the user names a target | No commit/push; branch target unresolved | DP4 README/ledger; `git branch -vv` |
| 2026-10-28 | Pre-existing work | Milestone isolation: do not stage unrelated files | 10 modified tracked paths and 27 untracked paths existed before B0 artifacts; none was reverted or staged | `/tmp/dp5-b0-status.txt` |

### Initial capacity blocker detail (superseded)

At HEAD `f119429`, 4320 helper lines left `R=5000−4320=680`, below the 900 admission threshold and below the plan's low-end DP5 estimate. The plan's only permitted relief under the 5000 cap was semantics-preserving de-duplication; a pair-agent audit estimated only 85–115 recoverable plumbing lines (optimistic ~120), still below 900. That conclusion is superseded by the 5500 re-adjudication below.

## B0 re-adjudication (2026-10-28, HEAD `ba66776`) — capacity pass

| Date | Item | Baseline / spec | B0 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-28 | Baseline HEAD | The initial B0 ran at `f119429`; DP4 has since advanced | Actual HEAD `ba66776`, subject `v24: split Cordis DP4 settlement validation helpers`; branch `v24`, upstream `origin/v24`; after fetch `origin/v24` = `4b34bf2`, `origin/v24...HEAD` = `0 9` | `git rev-parse HEAD`; `git rev-list --left-right --count origin/v24...HEAD` |
| 2026-10-28 | DP4 follow-ups | DP5 must inherit the actual W5 tree, not the earlier 5000-era snapshot | W5 chain is `348b9b8`, `f119429`, `73973d1`, `ba66776`; the last two harden settlement validation and split the settlement helpers. DP4 README/matrix/ledger record both | DP4 README "Review fix" and "Readability follow-up"; DP4 matrix/ledger; `git log --oneline origin/v24..HEAD` |
| 2026-10-28 | `43_loop` stability | Current 43 must be safe to build on; DP4 had just split helpers | 43 is **592** lines, **25** private functions, no working-tree diff against HEAD, SHA-256 `63a12aa13d360ad6d5b84511a3c31a13217184b79e214944fa4a9a03b7fe0943`; `CDP4-T/X/B` all pass | `git diff --exit-code HEAD -- v24/cordis/sql/43_loop.sql`; `shasum -a 256`; gate logs 29–31 |
| 2026-10-28 | 41 refactor | User's uncommitted dedup; must not change production semantics | `fiber_chain` one recursive SQL walker replaces four PL/pgSQL walkers; 41 **1211→1197** (net −14). Normal/cycle/512-overflow paths pass CDP2/CDP3; a missing owner is unreachable because `20_relations.sql:8` has `FOREIGN KEY(owner_id) REFERENCES v24_cordis.fibers(id)`. 41 remains byte-identical to the user's pre-B0 version | `git diff --numstat`; `shasum -a 256 v24/cordis/sql/41_lifecycle.sql`; CDP2/CDP3 gates |
| 2026-10-28 | 5500 helper contract | 2026-10-28 user authorization: private helper total 5000→5500; `R≥900` retained | `v24/cordis/helper_budget.py` has `LIMIT=5500`; tests import `LIMIT`; design §10.1 already states 5500. DP1/DP2 historical 5000 notes are superseded by the design line and this B0 | `helper_budget.py`; tests `test_kernel.py`/`test_install.py`/`test_boundaries.py`/`test_closeout.py`; design §10.1 |
| 2026-10-28 | Capacity measurement | `R=5500−all 40–49 physical lines` | Real tree: 40=1549, 41=1197, 42=1000, 43=592; total **4338**; **R=1162** | `[CDP1-K0] helper budget 4338<=5500`; CDP2-B, CDP3-B, CDP4-B1 |
| 2026-10-28 | Admission threshold | Plan §5: `R<900` no W1; `R≥900` admission only | **R=1162≥900, admission passes.** The low-end DP5 estimate (+790) fits; the high end (+1020) leaves 142 lines. Every milestone must still keep the actual total ≤5500 | initial matrix; plan §5/§9-B0; B0-revised plan Result |
| 2026-10-28 | Predicate proof | The 5500/5501 boundary must be invoked, not a literal comparison | CDP1-K0 builds temporary four-file trees of exactly 5500 (accepted) and 5501 (rejected), then measures the real 4338 tree | `[CDP1-K0]`; CDP3-B1; CDP4-B2 |
| 2026-10-28 | 31-command regression | Full inherited sequence on the current tree, one process at a time, s8 before s7 | **31/31 exit 0**, wall 185.9 s (sum 185.8 s); no failure; every command's exit/duration in the matrix | `/tmp/dp5-b0-readjudication/gates.tsv`; `gates.log`; per-gate `gate-01..31.log` |
| 2026-10-28 | Frozen SQL | Twelve `v24/sql` hashes and `57e2c1e` frozen diff must not change | All twelve SHA-256 match the DP4 matrix; `git diff --exit-code 57e2c1e -- v24/load.py v24/sql … v24/s12` exit 0; `git diff --check` exit 0 | DP5 matrix "Frozen SQL"; `/tmp/dp5-b0-readjudication/pre-hashes.txt` |
| 2026-10-28 | DDL / manifest / tables / ACL | Current DP4 closeout: DDL 461, manifest 18, ten tables, one DEFINER, public EXECUTE 0 | Verified: `tables=10 manifest=18 helpers=4338 … ddl=461 definer=advance public_execute=0`; no VIEW/EXTENSION | CDP2-B, CDP3-B, CDP4-B1 |
| 2026-10-28 | No implementation scaffold | B0 must not create an empty 44 or start W1 | No `44_events.sql`; `v24/cordis/load.py` remains 18 entries; no W1 code or `CDP5-*` script was created | `ls`; `v24/cordis/load.py`; matrix "Not covered" |
| 2026-10-28 | 43 per-file cap | DP4 readability follow-up relaxed 43 to ≤700 | 43=592≤700; `dp4/test_closeout.py` still asserts the cap; total is governed by the 5500 helper cap | CDP4-B2; `test_closeout.py` |
| 2026-10-28 | Pre-existing work | Preserve the user's dirty boundary; do not stage unrelated files | 18 modified tracked paths and 30 untracked entries are recorded; B0 wrote only the four DP5 artifacts. The 41 hash is unchanged from the pre-B0 value; `dp3/test_live.py` has no diff | DP5 matrix "Workspace snapshot"; `/tmp/dp5-b0-readjudication/pre-status.txt` |
| 2026-10-28 | Publication | AGENTS says `origin main`; branch is `v24` tracking `origin/v24`; remote is stale at `4b34bf2` | No commit, no push. The user reports DP4 was pushed in another session, but this worktree cannot prove the target; publication is left to orchestration | `git fetch origin`; `origin/v24`/`origin/main`; DP5 matrix "Publication target conflict" |
| 2026-10-28 | DP5 scripts | Four scripts are planned, not present | `dp5/README.md` is the only new DP5 directory content; no `test_listeners.py`, `test_dispatch.py`, `test_resolution.py`, or `test_boundaries.py` exists. The command index marks them future, not run | `ls v24/cordis/dp5/`; DP5 matrix "Future DP5 command index" |

## W1 implementation (2026-10-28, HEAD `ba66776`)

W1 is a local, verified milestone. The rows below record what changed against the B0/DP4 baseline and what remains deliberately out of scope. No DP1–DP4 acceptance record is rewritten.

| Date | Item | Baseline / spec | W1 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-28 | Overlay ABI | `installs.overlay jsonb`; design §8.1 depth ≤4; plan §4.2.1 exact two-map ABI | `{}` is legacy identity; non-empty exact `{v,services,listeners}`; services patches merge recursively, array/scalar/null replace wholesale; patch and effective descriptor semantic depth ≤4; unknown targets, shape errors, protocol key budget and top-level `capability`/`contract_version`/`identity`/`version`/`artifact_digest` patches are `invalid_args` | CDP5-R1; CDP2-I3 updated |
| 2026-10-28 | Listener overlay namespace | Plan §4.2.1 says both maps exist and W2 adds listener declarations | W1 requires the `listeners` map but rejects any non-empty target because no listener declaration exists yet. This is a staged boundary, not a silent merge into services; W2 replaces it with declared-listener validation | CDP5-R1 `listener namespace`; plan §9 W1 Result |
| 2026-10-28 | Intercept ABI | `scopes.intercept`; design §6.5 nearest rule/depth ≤4; plan §4.2.2 | `{}` legacy or exact `{v,rules}`; 1–16 unique `(realm,key)` rules; `reject` or full `replace` with descriptor/hex64 digest/contract_version; digest, depth, rule-key and duplicate checks are `invalid_args`; resolve-time capability/contract incompatibility makes the key unavailable | CDP5-R2 |
| 2026-10-28 | Intercept rule bound | Plan says rule count is bounded by existing payload/key/closure budgets, not an unbounded lookup | W1 caps a scope at **16** rules. The body's recursive 200-key limit would already bound nested rule objects to roughly this order; the explicit cap is recorded so W2/W3 do not silently raise it | CDP5-R2 16 committed / 17 rejected |
| 2026-10-28 | Descriptor depth | Plan §4.2.1: object/array root is layer 1, scalar adds no container layer, ABI wrapper not counted | `descriptor_depth` is pure and shared by overlay/intercept; `{a:{b:{c:{d:1}}}}` is depth 4 and admitted, one more object is depth 5 and rejected; the overlay/rule wrapper is not passed to the function | CDP5-R1/R2 |
| 2026-10-28 | Effective resolution | Plan §4.2.3: P2 stores overlay-applied descriptor; resolve applies intercept; check/view/run/claim use the final effective descriptor | `resolve` returns the intercept-replaced descriptor and `H(C(effective))`; P1/P2 validators, `activation_total`, `fiber_live_state`, `run_bindings`, `run_digests`, tool successors, settlement and claim all use the same resolver; no second digest source or raw-hash fallback | CDP5-R3; CDP4-T4a/T4b; CDP2/CDP3 |
| 2026-10-28 | Claim execution | Plan §4.2.3: non-empty config claim adds `execution:{descriptor,descriptor_digest}`; empty config keeps the old response | `claim_execution` returns the key only when the provider overlay patches that key or a matching intercept rule exists. The legacy model/tool claim response and the run_start/host claim shape are unchanged. The descriptor/digest must match the frozen committed view; `claim_contract` still reads `installs.contracts`, so fake `handler_digest`/`replay` keys in a replace descriptor cannot expand authorization | CDP5-R3/R3b; CDP4-R/T |
| 2026-10-28 | Old-run drain | Plan §4.2.3: use run.scope/key, pinned contribution, provider columns; do not call a resolver requiring current availability; released/epoch/digest mismatch rejects | `run_binding_desc` reads the pinned contribution and the frozen committed-view digest, applies the scope rule without provider liveness, and rejects a released pin or digest drift. A withdrawn provider contribution still drains; a new `resolve` is unavailable; a frozen-view contract/digest mismatch or a released pin rejects; the binding is not re-selected | CDP5-R4; CDP4-T4a/T4b |
| 2026-10-28 | Scope guard | Plan §4.2.3: freeze `scopes.realm_overrides`/`intercept` on UPDATE with 55000; do not claim it existed | `30_triggers.sql` now freezes both columns (+4 DDL) while retaining id/parent/close-tombstone rules. DP2/DP3 fixtures that mutated realm/intercept were moved to INSERT-time setup or replaced with a real withdrawal; the guard itself is tested | CDP5-R8; CDP2-I5; CDP3-L4 |
| 2026-10-28 | Replaced fail-closed points | DP2/DP3 rejected all non-empty overlay/intercept with `0A000` | `install_admission`, `activation_admission`, `activation_bindings`, `scope_live_fault`, `live_node_fault` and `service_realm` now accept valid configuration and fail closed only on invalid shape, digest/contract mismatch or incompatible resolution; the old `scope_intercepted` helper is removed | CDP2-I3; CDP3-B6; CDP5-R1/R2 |
| 2026-10-28 | Capacity | B0: 4338, R=1162, DDL 461 | W1: 40=1567, 41=1354, 42=1007, 43=668, total **4596**, **R=904**, DDL **465**, 138 private functions. Cap remains 5500; no limit/test/mode was removed | CDP1-K0; CDP2-B; CDP3-B1; CDP4-B; CDP5-R |
| 2026-10-28 | No event scaffold | W2/W3 own listener, dispatch, 44 and loader 19 | No `44_events.sql`, no loader change (18 entries), no listener registration, no dispatch producer, no typed event op, no `CDP5-E/D/B`; R5–R7 deferred to W4 | `ls`; `v24/cordis/load.py`; CDP5-R |
| 2026-10-28 | Publication | AGENTS says `origin main`; branch is `v24` tracking `origin/v24`; B0 left the target unresolved | W1 is a local commit; no force, no inferred target, no push to `main` or `origin/v24` | this ledger; plan §9; `git branch -vv` |

## W2 implementation (2026-10-28, HEAD `c3ddd94`)

W2 is a local, verified milestone for listener registration/revocation only. The rows below replace the W1 blanket listener-overlay rejection and record what remains deliberately outside W2.

| Date | Item | Baseline / spec | W2 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-28 | Manifest declaration | Plan §4.1: optional fifth key `listeners`, 0–16 exact eight-key items; missing/empty legacy fast path | `manifest_shape_valid` accepts exactly four keys or four+`listeners`; each listener validates listener_id/event/mode/priority/filter/exec/contract_version/sync_reads; listener_id unique in the manifest; `listeners=[]` returns the legacy provides plan | CDP5-E1/E5; CDP2-I3 |
| 2026-10-28 | Exec/contracts | Plan §4.1: `in_db` fixed `in_db_v1`; `host` requires `contracts.listener_call` and equal version; `sync_reads` JSON false | `listener_exec_valid`/`listener_desc_shape`/`listener_desc_valid` enforce the exact exec variants, fail-code text, host capability, contract presence/version and literal false; malformed declarations are `invalid_args` with zero write | CDP5-E5; CDP5-E1 |
| 2026-10-28 | Registration plan | Plan §4.1: `registration_plan(install)` = provides ++ listeners with kind/original position | `registration_plan` returns kind/index/key/overlay-applied descriptor/contract_version; P2, P4, `activation_total`, `validate_domain`, `reconcile_branch` and `reconcile_command_seed` route through it (seed only needs service addresses) | CDP5-E2/E4; CDP2-A3; CDP3-L4 |
| 2026-10-28 | Cross-32 iterator | Plan §4.1: one P2 stream, ≤32/batch, next_index/registered_through continuous | 30 services + 3 listeners registered in batches 32/1; seq 0..32; iterator next_index 33, registered_through 32; P4 activates; a target change after batch one Diverts and keeps prefix 32 | CDP5-E2 |
| 2026-10-28 | P4 totality | Plan §4.1: every plan item kind/seq/descriptor/contract/inverse/quantity, not only provides | `activation_total` counts service+listener rows, checks each seq/kind/realm/key/descriptor/contract/prev/inverse, and 40 P4 independently rejects a forged `episode_activate` when a listener row is withdrawn | CDP5-E2/E4; CDP2/CDP3 |
| 2026-10-28 | Listener ledger row | Plan §4.1: realm/key/prev NULL, `inverse={op:delete_row}`, separate contract_version | `contribution_append` accepts `kind='listener'` only with null realm/key/prev, exact seven-key descriptor and delete_row inverse; the existing `(fiber,episode,event,listener_id)` unique index is the final defence | CDP5-E3/E4 |
| 2026-10-28 | Identity/withdrawal | Plan §4.1/§4.6: duplicate listener_id and same-episode event/id reject; new episode may reuse; P5/P6 logical tombstones | Duplicate manifest id is invalid_args; same-episode collision is 23505; a new episode reuses the id over the retained released row; production P5 withdraws all listener rows and P6 releases in LIFO batches 32..1 then 0..0 without deleting rows, descriptors or inverse | CDP5-E3/E6 |
| 2026-10-28 | Listener overlay | Plan §4.2.1: dual namespace, declared targets only, priority/filter only, identity/exec/contract protected | W1 rejected every non-empty listener map; W2 resolves each target to a declared listener and applies recursive merge to the seven-key descriptor, rejecting unknown targets, protected fields and invalid filters. A service key and listener_id may share a name | CDP5-E1; CDP5-R1 still passes |
| 2026-10-28 | Independent validator | Plan §4.1: forged delta/wrong registration is `invalid_outcome`; DB uniqueness SQLSTATE preserved | Forged listener realm/key/prev/inverse/contract/seq/descriptor, missing/extra appends and P4 over a withdrawn listener are `invalid_outcome` with a full ten-table snapshot unchanged; the unmodified plan commits | CDP5-E4 |
| 2026-10-28 | P6 listener barrier | Plan §6.2 E7: no listener pin/run; provider-owned ready/claimed/unknown fixture effects block P6 | Listener registration creates no pin/run and no dispatch/listener_call effect; owner-fixture `listener_call` ready/claimed make P6 `deferred`, unknown makes it `blocked_unknown`. No real drain is claimed | CDP5-E7 |
| 2026-10-28 | Not delivered | W3 owns producer/execution/44/loader/typed ops; W4 R5–R7 | No `44_events.sql`, loader 19-entry change, dispatch producer, listener_call execution, host receipt, event planner, ordering, unavailable or real drain; E1–E7 explicitly exclude them | `ls`; `v24/cordis/load.py`; CDP5-E output |
| 2026-10-28 | Capacity | W1: 4596, R=904, DDL 465, 138 functions | W2: 40=1589, 41=1473, 42=1015, 43=668, total **4745**, **R=755**, DDL **465**, **144** functions. Cap remains 5500; no limit/test/mode removed | CDP1-K0; CDP2-B; CDP3-B1; CDP4-B; CDP5-E |
| 2026-10-28 | Regression | Inherited 31 + W1 R + W2 E | **33/33 exit 0** (167 s), one process at a time, s8 before s7 | `/tmp/dp5-w2-final2/gates.tsv`; `gate-01..33.log` |
| 2026-10-28 | Publication | AGENTS says `origin main`; branch `v24` tracks `origin/v24`; target unresolved | W2 is a local commit; no force, no inferred target, no push | this ledger; plan §9; `git branch -vv` |

## Capacity contract history

The authoritative line is design §10.1: **advance and all private helper modules 40–49, all physical lines, total ≤5500** (user authorization 2026-10-28; replaces the 2026-10-27 5000 line and the earlier 1200 per-advance line). The budget is not per file; splitting functions or moving them between 40–49 does not escape it. The 43 per-file 700 cap is an additional readability cap, not a substitute for the 5500 total.

The measured history is:

| Point | 40 | 41 | 42 | 43 | Total | Remaining vs cap | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| DP4 planning snapshot | 1546 | 1211 | 1000 | 459 | 4216 | 784 vs 5000 | planning only |
| Initial B0 at `f119429` | 1549 | 1211 | 1000 | 560 | 4320 | 680 vs 5000 | blocked |
| B0 re-adjudication at `ba66776` + user edits | 1549 | 1197 | 1000 | 592 | 4338 | **1162 vs 5500** | **pass** |
| W1 at `c3ddd94` | 1567 | 1354 | 1007 | 668 | 4596 | 904 vs 5500 | pass |
| W2 at `c3ddd94` | 1589 | 1473 | 1015 | 668 | **4745** | **755 vs 5500** | **pass** |

DP1/DP2 docs still carry their 2026-10-27 "5000" notes; those are historical statements about the previous authorization and do not override design §10.1's 2026-10-28 5500 line. B0 did not rewrite those historical records.

## Final unclaimed scope

B0 claims: DP4 handoff verification at `ba66776`, current 43 stability, the 41 refactor inspection, the 5500 capacity contract, the 31-command serial regression, the real 4338/1162/461 measurement, the admission pass, and the command/symbol index.

W1 claims: overlay/intercept exact ABI and boundaries; effective descriptor/digest through resolve/check/view/run/claim; configured claim `execution`; old-run drain; the scope UPDATE guard; R1–R4/R8; the W1 capacity measurement (4596/904/465/138); and the W1 local commit.

W2 claims: optional five-key manifest, exact eight-key listener declarations and exec/contract/sync_reads validation; `registration_plan` = provides++listeners; cross-32 iterator/seq/registered_through and P4 totality; listener contribution shape/`delete_row` inverse; declared-listener overlay validation; production P5/P6 listener withdrawal/release; E1–E7 registration/revocation subset; the W2 capacity measurement (4745/755/465/144); and the W2 local commit. It explicitly does not claim W3 ordering, unavailable, real drain, host receipts or execution.

Unclaimed and not implemented:

- W3 `44_events.sql`, loader 19, budget five-file tree, p4 producer, dispatch/listener_call execution, typed ops, virtual receipts, `CDP5-D`; also listener ordering, not-yet-created `unavailable`, real drain and host receipt evidence deliberately left by W2.
- W2 did deliver listener declaration/registration/withdrawal, listener overlay application and the `CDP5-E` registration subset; those are no longer unclaimed.
- W4 refinement reference and deviations; `CDP5-R5–R7`.
- W5 full `CDP5-B`, all-new-and-old closeout, final push-ready result.
- DP6 scanner/recovery/unknown reconciliation and any G4 item outside events/resolution.
- Any push for W1/W2. Publication target remains unresolved; the local commits are not evidence of a remote target.
