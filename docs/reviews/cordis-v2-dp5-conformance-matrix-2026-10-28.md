# Cordis v2 DP5 Conformance Matrix

B0 re-adjudication executed on 2026-10-28 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, at HEAD `ba66776` plus the user's uncommitted `41_lifecycle.sql` refactor and `helper_budget.py` 5500 cap. W1 was then implemented on the same HEAD and verified by the inherited 31 commands plus `CDP5-R`. This matrix records B0 and W1: DP4 handoff inspection, the current `43_loop.sql` stability check, the relaxed 5500 capacity contract, the 31-command pre-DP5 regression, the admission decision, the W1 overlay/intercept/effective-descriptor implementation, and the 32-command W1 regression. W2+ does not exist.

The prior blocked-at-5000 B0 record is retained in the plan §9 as history; it is superseded by this re-adjudication. DP1–DP4 historical acceptance records are not rewritten.

## Scope

B0 claims:

- DP4 W5 plus the two settlement-validation follow-ups are present at HEAD `ba66776`, with their README/matrix/ledger and all five DP4 gate scripts.
- `43_loop.sql` is stable: 592 lines, 25 private functions, no working-tree diff against HEAD, and `CDP4-T/X/B` pass.
- The user's uncommitted 41 `fiber_chain` dedup was inspected; it replaces four PL/pgSQL walkers with one recursive SQL walker, is 14 lines smaller, and passes the inherited CDP2/CDP3 gates. `fibers_owner_id_fkey` makes a missing owner unreachable, so the shared walker's end-of-chain behavior is not a production semantic drift.
- The 5500 helper cap is real and exercised: four-file total **4338≤5500**, temporary tree **5500 admitted / 5501 rejected**, `R=1162≥900`.
- Twelve frozen `v24/sql` hashes and the `57e2c1e` frozen diff are unchanged; `git diff --check` is clean.
- The 31-command pre-DP5 sequence (26 legacy + `CDP4-R/M/T/X/B`) was rerun serially on this tree; **31/31 exited 0** in **185.9 s**.
- The inherited command index, helper symbol inventory, workspace snapshot, and publication conflict were captured for W1+.

B0 does **not** claim any DP5 behavior, any `CDP5-E/D/R/B` gate, any `44_events.sql`, any loader/budget implementation change beyond the user's already-present 41/limit edits, or any G4 completion. Capacity admission passes.

## W1 scope

W1 claims only overlay/intercept plus effective-descriptor consistency and its guard:

- exact overlay ABI: `{}` legacy identity or `{v,services,listeners}`; services patches merge recursively, arrays/scalars/null replace, semantic depth ≤4, protected identity fields and unknown targets rejected; the listeners map is shape-required but must be empty until W2 declares listeners;
- exact intercept ABI: `{}` or `{v,rules}`, 1–16 unique `(realm,key)` rules, `reject`/`replace`, hex64 digest equal to `H(C(descriptor))`, depth ≤4, resolve-time capability/contract compatibility;
- nearest-scope rule after realm resolution, whole replacement, no stacking, reject makes the key unavailable, no fallback;
- effective descriptor/digest in `resolve`, P1/P2 validators, `activation_total`, committed view/check, `fiber_live_state`, run bindings/digests (frozen descriptor digest and contract version), tool successors, settlement and configured model/tool claim `execution`;
- the `30_triggers.sql` scope guard for `realm_overrides`/`intercept` (55000) and the existing close-tombstone rule;
- R1–R4/R8 in `v24/cordis/dp5/test_resolution.py`.

W1 does **not** claim listener declaration/registration/withdrawal, listener overlay application, dispatch production, `44_events.sql`, the loader 19-entry change, typed event ops, `CDP5-E/D/B`, R5–R7, or any G4 completion. The W1 listeners-map rejection is a staged boundary, not a W2 implementation.

## Environment

Commands ran from the worktree root. `uv run` resolved the worktree's `.venv`.

| Item | Observed value |
|---|---|
| `pwd -P` | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` (exit 0) |
| branch / upstream | `v24` / `origin/v24` |
| HEAD | `ba66776cab82d05cbd1a0ef97bb27f5e1895378f`, subject `v24: split Cordis DP4 settlement validation helpers` |
| `git fetch origin` | exit 0 |
| `origin/v24` | `4b34bf28e83791a7af3356f8036237afca78b67a`, subject `v24: add DP3 W5 boundary gate and closeout` |
| `origin/main` | `4635b4a`, subject `v24: finalize fairness release audit` |
| `git rev-list --left-right --count origin/v24...HEAD` | `0 9` (0 behind, 9 ahead) |
| platform | Darwin 25.6.0 arm64, macOS 26.6.2 |
| uv / Python / psycopg2 | 0.8.24 / 3.12.11 / 2.9.12 (dt dec pq3 ext lo64) |
| PostgreSQL | 18.4 (`180004`), printed by the Cordis fixture self-check |
| `.venv` | worktree directory under `v99`, not the main checkout |

`git status --porcelain=v1` showed 18 modified tracked paths and 30 untracked entries before B0 wrote its artifacts. The 41 refactor, `helper_budget.py`, and the dp1/dp2/dp3/dp4 test edits are user/uncommitted work preserved by B0; they are not B0-created. None was reverted or staged. Full snapshot: `/tmp/dp5-b0-readjudication/pre-status.txt`.

## DP4 handoff

DP4 is delivered at HEAD as nine commits ahead of the fetched `origin/v24`:

```text
17c855d v24: establish Cordis DP4 baseline and 18-entry scaffold
e8b6cce v24: add Cordis DP4 run_start production and binding
8cbc5f3 v24: add Cordis DP4 model settlement and reducer
dbd943d v24: add Cordis DP4 tool settlement and batch barrier
faccab4 v24: add Cordis DP4 run sealing and terminal closure
348b9b8 v24: harden Cordis DP4 run_start validation and close out W5
f119429 v24: verify Cordis DP4 closing-owner rejection and final gates
73973d1 v24: harden Cordis DP4 run settlement validation
ba66776 v24: split Cordis DP4 settlement validation helpers
```

Evidence inspected:

- `v24/cordis/dp4/README.md` records W5=`348b9b8` plus the 2026-10-28 acceptance correction, review fix, and readability follow-up; the last two changed `43_loop.sql` to 592 lines and 25 functions.
- `docs/reviews/cordis-v2-dp4-conformance-matrix-2026-10-27.md` records the 31-command sequence, B1–B6, the review-fix evidence, and the readability-follow-up evidence (`43=592`, per-file cap 700, four-file sum 4352 at that time).
- `docs/reviews/cordis-v2-dp4-deviation-ledger-2026-10-27.md` records the same follow-ups, the local-only publication decision, and the external uncommitted-file boundary.
- `v24/cordis/dp4/test_closeout.py` asserts `43_loop.sql <= 700` and `total <= helper_budget.LIMIT`; the current 43 is 592.

The user reports DP4 was pushed in another session. This worktree's fetched `origin/v24` is still `4b34bf2`, so B0 records the local delivery and the stale remote fact but does not infer a publication target.

## Frozen SQL

All twelve `v24/sql/*.sql` SHA-256 values match the DP4 matrix's frozen column:

| SQL | SHA-256 | Matches DP4 matrix |
|---|---|---|
| `00_schema.sql` | `05b6b47e0f71881e64fba3c55609c16608e4bc15c44f321ad5a87ede7979bc6d` | yes |
| `10_schema.sql` | `a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76` | yes |
| `20_triggers.sql` | `1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1` | yes |
| `30_advance.sql` | `087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870` | yes |
| `40_interpreters.sql` | `2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9` | yes |
| `45_capability.sql` | `f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e` | yes |
| `46_cleanup.sql` | `bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef` | yes |
| `47_verbs.sql` | `5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265` | yes |
| `48_loop.sql` | `f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30` | yes |
| `49_host_reads.sql` | `242748a0fe29cbedc723df9d5de18dd1fba7e9767cfce56a3bc218d1a17ce6c4` | yes |
| `49_recovery.sql` | `b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d` | yes |
| `50_permissions.sql` | `578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe` | yes |

```bash
git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12
```

It exited 0 with no output. `git diff --check` exited 0.

## Capacity and admission

Physical lines use `str.splitlines()`, the same count as the DP1/DP2/DP3/DP4 budget asserts. DDL prefix is `10_installs.sql` through `17_effects.sql`, plus `20_relations.sql` and `30_triggers.sql`.

| Helper module | Physical lines |
|---|---:|
| `40_advance.sql` | 1549 |
| `41_lifecycle.sql` | 1197 |
| `42_teardown.sql` | 1000 |
| `43_loop.sql` | 592 |
| **40–49 total** | **4338** |

`R = 5500 − 4338 = 1162`.

| Item | Observed | Limit | Result |
|---|---:|---:|---|
| Helper total | 4338 | 5500 | pass |
| Remaining capacity `R` | **1162** | **≥900 admission** | **pass** |
| DDL prefix | 461 | 900 | pass |
| Manifest entries | 18 | 18 (current) | pass |
| Domain tables | 10 | 10 | pass |
| `SECURITY DEFINER` | 1 (`advance`) | 1 (`advance`) | pass |
| `44_events.sql` | absent | absent at B0 | pass (intentional) |

The plan's DP5 helper estimate is a net **+790 to +1020** lines. The measured `R=1162` covers the high estimate with 142 lines left. `R≥900` is admission, not a capacity proof; every milestone still has to keep the actual total ≤5500.

**B0 admission verdict: pass.** At B0, W1 was capacity-admitted but not started. Per plan §5/§9-B0, B0 did not create `44_events.sql`, did not change `v24/cordis/load.py` (18 entries), and did not add W1 code. The 41 refactor and `helper_budget.py` 5500 edit are the user's pre-existing uncommitted work; B0 preserved them byte-for-byte.

### W1 actual capacity

W1 changed only `30_triggers.sql` (DDL) and the four helper modules. It did not add a fifth helper file or change the loader/budget contract.

| Helper module | B0 | W1 | W1 delta |
|---|---:|---:|---:|
| `40_advance.sql` | 1549 | **1567** | +18 |
| `41_lifecycle.sql` | 1197 | **1354** | +157 |
| `42_teardown.sql` | 1000 | **1007** | +7 |
| `43_loop.sql` | 592 | **668** | +76 |
| **40–49 total** | 4338 | **4596** | **+258** |

`R = 5500 − 4596 = 904`. `R≥900` remains true for the next milestone, but it is not a W2/W3 capacity proof: W2–W5 must still measure and stay ≤5500. No mode, validator or limit was removed to fit.

| Item | W1 observed | Limit | Result |
|---|---:|---:|---|
| Helper total | 4596 | 5500 | pass |
| Remaining `R` | **904** | ≥900 (B0 admission) | pass |
| DDL prefix | **465** | 900 | pass |
| Manifest entries | 18 | 18 | pass |
| Private functions | 138 | (inventory) | +9 net |
| Domain tables | 10 | 10 | pass |
| `SECURITY DEFINER` | 1 (`advance`) | 1 (`advance`) | pass |
| public EXECUTE | 0 | 0 | pass |
| `44_events.sql` | absent | absent at W1 | pass (intentional) |

The 4-line DDL delta is exactly the `scopes.realm_overrides`/`intercept` UPDATE guard. The function delta is ten new private helpers (`descriptor_depth`, `descriptor_merge`, `descriptor_patch_ok`, `overlay_apply`, `install_overlay_valid`, `scope_intercept_valid`, `intercept_for`, `descriptor_effective`, `run_binding_desc`, `claim_execution`) minus the removed `scope_intercepted`.

## Refactor and 43 stability inspection

### 41 `fiber_chain` dedup

`git diff --numstat -- v24/cordis/sql/41_lifecycle.sql` is `47 61`, net **−14** lines (1211→1197). The refactor:

- adds `v24_cordis.fiber_chain(uuid)`, one `STABLE` recursive SQL walker that returns the owner chain with `depth`, `cycle`, and `overflow`;
- rewrites `fiber_lineage_open`, `dispose_ancestor_sealed`, `lineage_fault`, and `fiber_in_install_subtree` as SQL over that walker instead of four separate PL/pgSQL loops;
- keeps the 512-depth and cycle markers, and the same `scopes`/`installs` checks.

Reviewed semantics: normal open chains, cycles, and the 512/513 overflow boundary are gate-covered by CDP2/CDP3; the one apparent difference (a missing `owner_id`) is unreachable because `20_relations.sql:8` declares `FOREIGN KEY(owner_id) REFERENCES v24_cordis.fibers(id)`. The 41 hash after B0 is `1014b315afe731c1232ae8f2984977c30e7854f0e78f38d46086d0db93d1d2c7`; no production behavior was changed by B0.

### `helper_budget.py` 5500

`v24/cordis/helper_budget.py` now has `LIMIT = 5500`. The test modules import `LIMIT` rather than hardcoding 5000. CDP1-K0 exercised temporary four-file trees of exactly 5500 lines (accepted) and 5501 (rejected), then measured the real tree:

```text
[CDP1-K0] helper budget 4338<=5500 {'40_advance.sql': 1549, '41_lifecycle.sql': 1197, '42_teardown.sql': 1000, '43_loop.sql': 592}; predicate admits a 5500-line tree and rejects 5501
```

### 43 `43_loop.sql` stability

| Check | Result |
|---|---|
| Physical lines | 592 |
| Private functions | 25 |
| `git diff --exit-code HEAD -- v24/cordis/sql/43_loop.sql` | exit 0 (no working-tree diff) |
| SHA-256 | `63a12aa13d360ad6d5b84511a3c31a13217184b79e214944fa4a9a03b7fe0943` |
| Last commits | `73973d1` (harden settlement validation), `ba66776` (split settlement helpers) |
| DP4 gates | `CDP4-T` 13.4 s, `CDP4-X` 9.7 s, `CDP4-B` 16.6 s, all exit 0 |
| Per-file cap | 592≤700 (`dp4/test_closeout.py`) |

The file contains the `run_settlement_unimplemented` refusal for non-run/model/tool kinds at line 410, which is the intended closed-set fallback, not a W5 stub. No `44_events.sql`, loader, or budget implementation change was made by B0.

## B0 serial gates

Each command was a separate `uv run python` process, launched after the previous one exited. The runner stopped on the first non-zero exit; none occurred. The DP4 order s8 before s7 is preserved. All 31 exited 0; wall time 185.9 s (per-command sum 185.8 s). Log: `/tmp/dp5-b0-readjudication/gates.log`; summary: `/tmp/dp5-b0-readjudication/gates.tsv`.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0.9 | canonical loader, 18 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 2.2 | PostgreSQL 18.4, psycopg2 2.9.12 |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1.8 | CDP1-E exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 1.9 | CDP1-D; DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 15.5 | CDP1-K; helper 4338≤5500, 5500/5501 boundary |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4.2 | CDP2-K continuation, typed delta, closure, replay |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 6.2 | CDP2-I declaration/admission; helper 4338 |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3.9 | CDP2-A activation and provide bounds |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4.5 | CDP2-B; `tables=10 manifest=18 helpers=4338 40=1549 41=1197 42=1000 43=592 ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | 0.6 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1.8 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 1.8 | G1-O owner DDL |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2.8 | G1 kernel, commands, claim, locks, ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2.1 | S2 W1–W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 6.2 | S3 W1–W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 6.4 | S4 W1–W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 4.3 | S5 W1–W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 4.5 | S6 W1–W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 3.0 | S8 W1–W3 G7-A…H + N1–N7 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7.7 | S7 W1–W2 G6-A…H + N1–N9 + L1–L5 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 12.6 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3.5 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 13.2 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6.9 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 7.0 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 7.6 | CDP3-B1…B13; `helpers=4338 40=1549 41=1197 42=1000 ddl=461`, 5500/5501 boundary |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 7.0 | CDP4-R1…R7 |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 6.0 | CDP4-M1…M5 |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 13.4 | CDP4-T1…T8 |
| 30 | `uv run python v24/cordis/dp4/test_boundaries.py` | 0 | 9.7 | CDP4-X1…X7/M6/e7→e13 |
| 31 | `uv run python v24/cordis/dp4/test_closeout.py` | 0 | 16.6 | CDP4-B1…B6; `helpers=4338 43=592 ddl=461` |

Key closeout assertions from the logs:

```text
[CDP1-K0] helper budget 4338<=5500 {'40_advance.sql': 1549, '41_lifecycle.sql': 1197, '42_teardown.sql': 1000, '43_loop.sql': 592}; predicate admits a 5500-line tree and rejects 5501
[CDP2-B4/B5] multi-fiber dispose; tables=10 manifest=18 helpers=4338 40=1549 41=1197 42=1000 43=592 ddl=461
[CDP3-B1] tables=10 manifest=18 helpers=4338 40=1549 41=1197 42=1000 ddl=461 definer=advance public_execute=0, views/extensions=0, 5500/5501 boundary proven
[CDP4-B1] tables=10 manifest=18 helpers=4338 43=592 ddl=461 definer=advance public_execute=0 views/extensions=0
[CDP4-B2] 5500/5501 helper-tree predicate reran; DDL 461<=900; 43<=700
[CDP4-B6] twelve frozen v24/sql hashes, load.py since B0, DP2-frozen diff and git diff --check are unchanged
```

## W1 serial gates

W1 ran the 31 inherited commands in the B0 order (s8 before s7) plus `CDP5-R`, each in a separate process, stopping on the first non-zero exit. None occurred. Wall time **155 s**; per-command sum 155 s. Summary: `/tmp/dp5-w1/gates.tsv`; per-command logs `/tmp/dp5-w1/gate-01..32.log`.

| # | Command | Exit | Duration (s) |
|---:|---|---:|---:|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0 |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 2 |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1 |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 2 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 14 |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4 |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4 |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3 |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4 |
| 10 | `uv run python v24/load.py` | 0 | 0 |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 2 |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 2 |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2 |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 6 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 10 |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3 |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 10 |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6 |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 5 |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 7 |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 6 |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 5 |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 11 |
| 30 | `uv run python v24/cordis/dp4/test_boundaries.py` | 0 | 8 |
| 31 | `uv run python v24/cordis/dp4/test_closeout.py` | 0 | 13 |
| 32 | `uv run python v24/cordis/dp5/test_resolution.py` | 0 | 5 |

Key W1 assertions from the logs:

```text
[CDP1-K0] helper budget 4596<=5500 {'40_advance.sql': 1567, '41_lifecycle.sql': 1354, '42_teardown.sql': 1007, '43_loop.sql': 668}; predicate admits a 5500-line tree and rejects 5501
[CDP2-B4/B5] multi-fiber dispose; tables=10 manifest=18 helpers=4596 40=1567 41=1354 42=1007 43=668 ddl=465
[CDP3-B1] tables=10 manifest=18 helpers=4596 40=1567 41=1354 42=1007 ddl=465 definer=advance public_execute=0, views/extensions=0, 5500/5501 boundary proven
[CDP4-B1] tables=10 manifest=18 helpers=4596 43=668 ddl=465 definer=advance public_execute=0 views/extensions=0
[CDP4-B2] 5500/5501 helper-tree predicate reran; DDL 465<=900; 43<=700
[passed] CDP5-R (W1: R1-R4/R8; R5-R7 deferred to W4)
```

The DP4 closeout assertion was changed from the historical exact `DDL 461` to the plan ceiling `DDL<=900`; the actual print uses the measured 465. `43=668` is under the DP4 per-file 700 cap.

### Future DP5 command index

W1 delivered `test_resolution.py` (R1–R4/R8). W2/W3/W4/W5 append their own scripts/subset:

```bash
uv run python v24/cordis/dp5/test_listeners.py   # W2, CDP5-E registration subset
uv run python v24/cordis/dp5/test_dispatch.py    # W3, CDP5-D
uv run python v24/cordis/dp5/test_resolution.py  # W1 now; W4 completes R5-R7
uv run python v24/cordis/dp5/test_boundaries.py  # W5, CDP5-B
```

W2 runs the inherited set plus the delivered E registration subset and the existing W1 resolution script; W3 adds D; W4 completes R; W5 adds B. A missing item is not a skip-to-green: each milestone must name what is not yet covered. All commands run from the v99 root, one process at a time, with no concurrent DROP/CREATE of the same gate database.

## Handoff inventory

Manifest at HEAD, in canonical order:

```text
00_schema.sql, 10_installs.sql, 11_scopes.sql, 12_fibers.sql,
13_episodes.sql, 14_contributions.sql, 15_pins.sql, 16_runs.sql,
17_effects.sql, 18_events.sql, 19_requests.sql, 20_relations.sql,
30_triggers.sql, 40_advance.sql, 41_lifecycle.sql, 42_teardown.sql,
43_loop.sql, 50_permissions.sql
```

Private helper symbols are **138 functions** across four modules after W1 (full extraction):

```text
40_advance.sql (32):
principal_id, canonical_json, effect_id_for, error_v1
exact_keys, json_uuid, json_int, json_text
json_hex64, json_array_valid, json_uuid_set, event_payload_valid
role_family, role_allowed, valid_body, target_refs
discover_closure, lock_closure, barrier_ready, successor_request_key
successor_effect_id, reconcile_payload_valid, command_seed, command_closure
continuation_state, command_control, interpret_command, interpret_settlement
validate_delta, validate_domain, validate_and_apply_delta, advance

41_lifecycle.sql (52):
json_bool, json_key, json_text_map, descriptor_depth
descriptor_merge, descriptor_patch_ok, overlay_apply, install_overlay_valid
scope_intercept_valid, check_policy_valid, check_policy_ok, contracts_valid
manifest_shape_valid, scope_shape_valid, owner_shape_valid, install_payload_valid
scope_lineage_open, fiber_chain, fiber_lineage_open, dispose_ancestor_sealed
lineage_fault, fiber_in_install_subtree, install_admission, install_delta
interpret_install, validate_install_domain, install_command_seed, intercept_for
descriptor_effective, resolve, install_preflight, command_binding
install_references, require_key, activation_fail, activation_bubble
service_realm, reconcile_successor, empty_success, activation_admission
activation_dag, provider_closure_ok, activation_bindings, activation_consistent
activation_total, interpret_reconcile, reconcile_preflight, reconcile_command_seed
dispose_command_seed, dispose_preflight, dispose_block_reason, interpret_dispose

42_teardown.sql (27):
delta_write_closure_ok, assert_delta_applied, command_barrier, lifecycle_step
failure_v1, failure_v1_valid, scope_live_fault, live_node_fault
fiber_live_state, fiber_live_resolve_ok, pin_readable, reconcile_slot_open
withdraw_ids, closing_delta, p0_delta, branch_error
branch_raise, branch_divert, reconcile_branch, run_pin_release_delta
p6_plan, p6_delta, dispose_subtree, dispose_block_kind
dispose_fiber_next, dispose_plan, dispose_delta

43_loop.sql (27):
run_policy, chat_tool_schema, run_state_valid, run_digests_of
run_digests, run_id_for, run_pin_id_for, model_receipt_valid
tool_receipt_valid, reduce_chat_tool, run_bindings, run_bindings_valid
run_binding_desc, claim_execution, run_progress, run_seal_result
unknown_body_valid, unknown_delta, run_refused, run_successor_binding
run_successors, run_settle_facts, claim_contract, run_start_successor
run_delta, validate_run_domain, settlement_seed
```

Existing DP4 gate scripts (all rerun above): `dp4/test_run.py`, `dp4/test_reducer.py`, `dp4/test_loop.py`, `dp4/test_boundaries.py`, `dp4/test_closeout.py`; support is `dp4/dp4_support.py`.

## Workspace snapshot

18 modified tracked paths (all pre-existing user work; B0 preserved them):

```text
M docs/designs/cordis-plugin-system-2026-10-25.md
M docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md
M docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md
M docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md
M docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md
M docs/reviews/cordis-v2-dp2-conformance-matrix-2026-10-26.md
M docs/reviews/cordis-v2-dp2-deviation-ledger-2026-10-26.md
M docs/reviews/v24-cordis-dp1-foundation-plan-critique-2026-10-25.md
M v24/cordis/dp1/README.md
M v24/cordis/dp1/test_kernel.py
M v24/cordis/dp2/README.md
M v24/cordis/dp2/test_install.py
M v24/cordis/dp2/test_kernel.py
M v24/cordis/dp2/test_support.py
M v24/cordis/dp3/test_boundaries.py
M v24/cordis/dp4/test_closeout.py
M v24/cordis/helper_budget.py
M v24/cordis/sql/41_lifecycle.sql
```

The 41 refactor is byte-identical to the pre-B0 working-tree version (`sha256 1014b315…`); `dp3/test_live.py` has no diff. The 5500 cap and its test imports are also pre-B0 work.

30 untracked entries (including the DP5 plan/critique and this B0 directory):

```text
docs/analysis/cordis-v99-vs-zcordis-2026-10-21.md
docs/analysis/oracle-eval-brief-2026-10-21.md
docs/designs/cordis-db-plugin-six-verb-report-2026-10-21.md
docs/designs/cordis-db-plugin-six-verb-report-plan-2026-10-21.md
docs/designs/cordis-plugin-core-2026-10-22.md
docs/designs/v13-multilingual-plugin-plane-2026-10-20.md
docs/designs/v13-multilingual-plugin-plane-control-annex-2026-10-20.md
docs/designs/v13-multilingual-plugin-plane-plan-2026-10-20.md
docs/designs/v99-core-ce-phase0-historical-2026-10-20.md
docs/designs/v99-core-native-plugin-plane-2026-10-20.md
docs/investigations/sag2-embedding-free-retrieval-survey-2026-10-21.md
docs/investigations/v13-duplicate-capabilities-audit-2026-10-20.md
docs/investigations/v13-harness2-self-improvement-fit-2026-10-20.md
docs/investigations/v13-self-improving-multilingual-plugins-feasibility-2026-10-20.md
docs/investigations/v24-pg-reactive-fit-2026-10-25.md
docs/plans/v13-recursive-harness-self-improvement-plan-2026-10-20.md
docs/plans/v24-closeout-followup-2026-10-25.md
docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md
docs/plans/v99-core-native-plugin-plane-2026-10-20.md
docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md
docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md
docs/reviews/v13-registry-stage41-plan-review-2026-10-17.md
docs/reviews/v24-closeout-plan-critique-2026-10-25.md
docs/reviews/v24-cordis-dp2-lifecycle-plan-critique-2026-10-26.md
docs/reviews/v24-cordis-dp3-teardown-plan-critique-2026-10-27.md
docs/reviews/v24-cordis-dp4-run-settlement-plan-critique-2026-10-27.md
docs/reviews/v24-cordis-dp5-events-resolution-plan-critique-2026-10-28.md
docs/reviews/v99-core-native-plugin-seam-decisions-2026-10-20.md
docs/reviews/v99-core-phase0-plan-critique-2026-10-20.md
v24/cordis/dp5/
```

B0 wrote only the four DP5 artifacts (plan/matrix/ledger/README); the plan and critique already existed as untracked files. No pre-existing path was reverted, overwritten, or staged.

### W1 touched paths

W1 modified or added exactly these paths (the commit stages only these, plus the five required inherited test updates):

```text
M v24/cordis/sql/30_triggers.sql
M v24/cordis/sql/40_advance.sql
M v24/cordis/sql/41_lifecycle.sql
M v24/cordis/sql/42_teardown.sql
M v24/cordis/sql/43_loop.sql
?? v24/cordis/dp5/README.md
?? v24/cordis/dp5/test_resolution.py
?? docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md
?? docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md
?? docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md
M v24/cordis/dp2/test_support.py
M v24/cordis/dp2/test_install.py
M v24/cordis/dp3/test_live.py
M v24/cordis/dp3/test_boundaries.py
M v24/cordis/dp4/test_closeout.py
```

The five test files already carried pre-B0/B0-era edits (the 5500 `LIMIT` import/docstring and the 41-refactor fixture work); W1's required test changes are layered on top. Pre-existing unrelated paths — `docs/designs/cordis-plugin-system-2026-10-25.md`, DP1–DP4 plan/review files, `dp1/test_kernel.py`, `dp2/test_kernel.py`, `dp2/README.md`, `helper_budget.py`, the untracked analysis/design/review files, and the DP1–DP4 artifacts — are not part of the W1 commit.

## Publication target conflict

`AGENTS.md` says the working branch tracks `origin/main` and pushes there. The actual worktree is branch `v24`, tracking `origin/v24`; after `git fetch origin`, `origin/v24` is `4b34bf2` and HEAD is 9 commits ahead. `origin/main` is a different commit (`4635b4a`). The user reports DP4 was pushed in another session, but this worktree cannot prove which remote/ref received it, and the stale `origin/v24` is not evidence of a safe target.

B0 did not commit and did not push. W1 is committed locally on `v24` after the 32-command regression; no push was performed because no remote/ref was named and the branch's `origin/v24` is stale. The W1 commit is not evidence of a safe publication target. Publication remains for orchestration or an explicit user-named remote/branch.

## Not covered

- No W2+ behavior; no listener declaration/registration/withdrawal, listener overlay application, dispatch producer, `44_events.sql`, typed event op, or event planner.
- No `44_events.sql`; the loader remains 18 entries and `helper_budget.py` remains the user's 5500-cap version.
- No `CDP5-E/D/B` script or database gate, and no R5–R7 (W4). Only `v24/cordis/dp5/test_resolution.py` exists and was run (R1–R4/R8).
- No DP6 scanner/recovery/unknown-reconciliation work; no claim that G4 is complete.
- No push for B0 or W1. Capacity and the W1 local commit are proven; remote publication is unresolved.
