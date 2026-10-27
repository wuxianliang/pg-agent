# Cordis v2 DP3 Conformance Matrix

B0 executed on 2026-10-27 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `9fe6b5b170776907d490fab079fca63cdde6aa28`. Every exit code in the B0 table is the process exit from that serial run. DP2's 2026-10-26 exits, including the W5 rerun on `d5fd1bc`, are not copied here. Durations were not recorded. W1 later ran its own 22-command sequence on the same uncommitted HEAD. That sequence is the W1 section. It does not replace the B0 numbers.

## Scope

B0 (`ba4f533`) records the baseline; W1 (`103ec596`) adds layout/budget/protocol probes; W2 (`72af2528`) adds live invalidation and entry into closing. W3 (`284d7f2`) adds production P6 drain, inverse, run/activation pin release and episode close. W4 adds bounded dispose for activated installs; its evidence is in the W4 section below. B0/W1/W2/W3 sections retain their gate-time history. W4 is delivered by this commit. W5 remains unimplemented; CDP3-B is not claimed.

## Environment

Commands were run in the worktree root. `uv run` resolved Python and psycopg2 from this worktree's `.venv`, which is a real directory owned by `wxl` (uid 501), not a symlink, and not the same inode as `/Users/wxl/Projects/pg-agent/.venv`.

| Item | Observed value |
|---|---|
| `pwd -P` | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` (exit 0) |
| `git rev-parse --show-toplevel` | same path (exit 0) |
| branch | `v24` (exit 0) |
| HEAD | `9fe6b5b170776907d490fab079fca63cdde6aa28` (exit 0), subject `v24: correct DP2 plan status after W5 closeout` |
| upstream | `origin/v24` (exit 0) |
| `git fetch origin` | exit 0 |
| `git rev-list --left-right --count origin/v24...v24` | `0 0` (exit 0) |
| `git branch -vv` | `* v24 9fe6b5b [origin/v24]` |
| platform | Darwin 25.6.0 arm64, macOS 26.6.2 build 25G83 |
| uv | 0.8.24 |
| Python | 3.12.11 |
| psycopg2 | 2.9.12 (dt dec pq3 ext lo64), imported from the worktree `.venv` |
| PostgreSQL | 18.4 (`180004`), printed by the Cordis fixture self-check |
| `.venv` | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99/.venv`, directory, owner `wxl`, not a symlink |

Before B0 added artifacts, `git status --porcelain=v1 --untracked-files=all` showed 10 modified tracked docs and 25 untracked paths. Those pre-existing changes were preserved. No implementation or test file changed during the gates.

## Frozen SQL

All twelve `v24/sql/*.sql` SHA-256 values match the DP2 matrix frozen column:

| SQL | SHA-256 | Matches DP2 matrix |
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

`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12` exited 0 with no output. `git diff --check` exited 0.

## B0 capacity

This section is the B0 measurement. W1 counts are in the W1 section and do not replace these rows. Physical lines use `str.splitlines()`, the same count as DP1/DP2 budget asserts. DDL prefix is `10_installs.sql` through `17_effects.sql`, plus `20_relations.sql` and `30_triggers.sql`.

| Item | Observed |
|---|---|
| `40_advance.sql` | 1130. CDP2-B printed `advance=1130` |
| `41_lifecycle.sql` | 1097. Filesystem count; the gate print does not include this number |
| `42_teardown.sql` | absent |
| helper sum | 2227, under the revised 5000 total. The old gates still assert one file ≤1200 and were not migrated |
| DDL prefix | 414. CDP1-D printed `DDL lines 414`; CDP2-B printed `ddl=414` |
| manifest | 16 files in `v24/cordis/load.py`. Loader self-check and CDP2-B both require 16 |
| tables | 10. CDP2-B printed `tables=10` |
| `SECURITY DEFINER` | source has one, on `advance`. CDP2-B asserts the catalog count is 1 before its budget print; that process exited 0. The print line itself does not include the digit |
| views / extensions | 0 `CREATE VIEW` and 0 `CREATE EXTENSION` in the 16 Cordis SQL files. No gate printed a catalog count |
| closure | Cordis gates printed `512/513 early cutoff` (CDP1-K4) and `513 closure cutoff` (CDP2-K4b). v24 G8 printed `H_ok=509 -> C=512` and `H_bad=510 -> C=513 retry_with_closure` |
| batch | CDP2-A3 printed `1/32/33 provides batch at most 32` |
| successors | CDP1-K3 printed `16/17 successors`. Source rejects `successors` length above 16 and ordinals outside 0..15 |

## B0 serial gates

Each command was a separate process. None was joined with `;`, run in the background, or skipped after a failure. There was no failure. These exits are the B0 run. The W1 rerun is a separate table.

| # | Command | Exit | Printed result used as evidence |
|---:|---|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | `[passed] Cordis canonical loader and five refusal probes` |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PostgreSQL `('18.4', '180004')`, psycopg2 2.9.12; `[passed] Cordis fixture: transaction/catalog/role family/OID cleanup` |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | CDP1-E1, E2, E3; `[passed] CDP1-E` |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | CDP1-D1…D4, including terminal attempt/fence +1 and -1 -> `55000`; `[passed] CDP1-D (117 zero-write negative probes plus positive/COMMIT cases)` |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | CDP1-K1…K5, including `16/17 successors` and `512/513 early cutoff`; `[passed] CDP1-K (66 committed zero-write assertions; W3 reconcile on/advance is production; off/retry and dispose remain 0A000)` |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | CDP2-K1…K8 and K4b, including `513 closure cutoff`; `[passed] CDP2-K (W1 continuation, typed delta, closure, terminal receipt, events)` |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | CDP2-I1…I7, I5b, I5c, I6, I6b, I6c; `[passed] CDP2-I (W2 install declaration, scope/owner admission, resolver, W2 guards)` |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | CDP2-A1…A6, including `1/32/33 provides batch at most 32`; `[passed] CDP2-A` |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | CDP2-B1…B5; `[CDP2-B4/B5] multi-fiber dispose; tables=10 manifest=16 advance=1130 ddl=414`; `[passed] CDP2-B` |
| 10 | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | psycopg2 2.9.12, unix-only socket; `[passed] v24/s1 setup self-check` |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | ten tables, T2–T4 guards; `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | G1-A/P/Q/H/F/R/B/D/J/I/K/C/L1/L2 and three role families at 30 DML refusals; `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | G3a-A1…A6, W2a/W2b/W2c, J, B/C/D/E, F/G, K; `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | G2a-0…11 and G3b-1…5; `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | G2b-A…T-10, four claim-race trials, unknown-wall suite; `[passed] v24 S4 W1-W6` |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | G4-A…Q including M-1…M-8; `[passed] v24 S5 W1-W4` |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | G5-K1…K10, W2, D1…D6; `[passed] v24 S6 W1-W4` |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | G7-A…H and N1–N7; `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | G6-A…H, N1–N9, L1–L5; `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | G8-H1…H13, C1/C2, L1…L3, R1, D1a/D1b/D2, W1; `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` |

Order 19 then 20 follows the plan: s8 before s7.

## B0 not covered

At B0, DP3 production paths were uncovered: live propagation, Divert/Raise/Leave, withdraw/release, inverse, P6 drain, and bounded dispose of an already-activated instance. No CDP3 script existed. The 5000/5001 budget boundary was not executed. Commit and push were not performed. W1 later changed the budget gate and added CDP3-P; it did not implement those production paths. See the W1 section.

## W1 (2026-10-27)

Same worktree and the same uncommitted HEAD `9fe6b5b170776907d490fab079fca63cdde6aa28`. No commit and no push. This records the pre-commit rerun. This commit publishes W1 to `origin/v24` under the 2026-10-27 authorization. The fixture self-check again printed PostgreSQL `('18.4', '180004')` and psycopg2 2.9.12. `git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12` exited 0. `git diff --check` exited 0. This section records the serial rerun after two P2 proof gaps were closed. `40_advance.sql`, `41_lifecycle.sql`, and `42_teardown.sql` were not edited in that fix, so the line counts match the first W1 measurement.

Physical lines use `str.splitlines()`. Helper modules are Cordis SQL files whose two-digit prefix is 40–49.

| Item | Observed |
|---|---|
| `40_advance.sql` | 1170. CDP1-K0, CDP2-K0, CDP2-I0, and CDP2-B printed this count |
| `41_lifecycle.sql` | 1097. Same prints |
| `42_teardown.sql` | 16. Same prints. The file exists and is the 17th manifest entry |
| helper sum | 2283 ≤ 5000. Shared `assert_helper_budget` in `v24/cordis/helper_budget.py` is invoked on temporary directories whose files are exactly `40_advance.sql`, `41_lifecycle.sql`, and `42_teardown.sql`. A tree of 5000 physical lines returns total 5000. A tree of 5001 physical lines raises `AssertionError` with total 5001. The same function then checks the real tree. CDP1-K0 calls `prove_helper_budget_boundary()` directly and does not import DP2. DP2 `test_support.assert_helper_budget` runs that proof before the real directory, so CDP2-K0, CDP2-I0, and CDP2-B exercise it. A literal 5000/5001 integer comparison is not the proof. CDP1-K0, CDP2-K0, and CDP2-I0 print `predicate admits a 5000-line tree and rejects 5001` |
| DDL prefix | 414. CDP1-D printed `DDL lines 414`; CDP2-B printed `ddl=414` |
| manifest | 17. Loader self-check requires 17. CDP2-B printed `manifest=17` |
| tables | 10. CDP2-B printed `tables=10` |
| `SECURITY DEFINER` | source has one, on `advance`. CDP2-B asserts the catalog count is 1. CDP3-P4 asserts the same |
| views / extensions | 0 `CREATE VIEW` and 0 `CREATE EXTENSION` in the 17 Cordis SQL files. Source scan, not a catalog count |
| closure / batch / successors | unchanged from the B0 prints: `512/513`, `1/32/33`, `16/17` |

`42_teardown.sql` defines `command_barrier`, which returns NULL, and stable `lifecycle_step`, which returns exactly `{tag:"idle"}`. CDP3-P4 shows that tag, shows `lifecycle_step` is absent from `advance` and `interpret_command`, and shows only `advance` is SECURITY DEFINER. The idle body is not a teardown selector. W2/W3 replace it. The other six planned helpers are not created.

CDP3-P is `v24/cordis/dp3/test_protocol.py`. It replaces `command_barrier` only. Production `interpret_command` returns `{kind, step, barrier, context}` and does not return a raw four-key delta. `advance` unwraps `kind=ready` before `validate_and_apply_delta`. A delta with no top-level `kind` still goes to the applier, so the existing DP2 probe stays valid. Deferred, `blocked_unknown`, and `unsupported` are the disposable barrier probe. CDP3-P3 records ten-table zero writes, no effect settlement, request, event, or successor, and a second connection acquiring `pg_try_advisory_xact_lock(24,1)` only after the caller commits. That probe is not production P6. Replay-first is checked before the barrier is restored. One admitted existing-scope install is committed while `command_barrier` still returns NULL (`disposition` committed). The function is then replaced with `{disposition:deferred}` and with `{disposition:blocked_unknown}`. The identical request (same key, same payload, same effect) returns the original response. The ten-table snapshot is unchanged, and exactly one request and one event remain. The original function is restored afterward in `finally`. That replay is not production P6 and is not a W3 first commit after the barrier is satisfied.

CDP3-P1 shows valid-identity generation, target, and phase drift as `{class:"control", reason}` with no `code`, and shows `advance` of the generation case still raises `0A000` with an unchanged snapshot. Forged continuation input stays `effect_id_conflict` / `continuation_identity`. CDP3-P2 shows ready-input `UPDATE` is `55000`, a second ready reconcile is `23505`, `on` beside that slot and `off` are `0A000`, a different LOGIN is `effect_id_conflict`, and a live claim is `stale_claim` / `claim_busy`. No coalesce receipt is written. `off`/`retry` stay unimplemented.

Each command below was a separate process. The runner stopped on the first non-zero exit. There was no failure. CDP3-L/T/D/B were not run.

| # | Command | Exit | Printed result used as evidence |
|---:|---|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | `[passed] Cordis canonical loader and five refusal probes` |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PostgreSQL `('18.4', '180004')`, psycopg2 2.9.12; `[passed] Cordis fixture: transaction/catalog/role family/OID cleanup` |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | CDP1-E1, E2, E3; `[passed] CDP1-E` |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | CDP1-D1…D4; `[passed] CDP1-D (117 zero-write negative probes plus positive/COMMIT cases)` |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | `[CDP1-K0] helper budget 2283<=5000 {'40_advance.sql': 1170, '41_lifecycle.sql': 1097, '42_teardown.sql': 16}; predicate admits a 5000-line tree and rejects 5001`; CDP1-K1…K5; `[passed] CDP1-K (66 committed zero-write assertions; W3 reconcile on/advance is production; off/retry and dispose remain 0A000)` |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | `[CDP2-K0]` prints the same helper-budget sentence as CDP1-K0; CDP2-K1…K8 and K4b, including K7 `drift 0A000`; `[passed] CDP2-K (W1 continuation, typed delta, closure, terminal receipt, events)` |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | `[CDP2-I0]` prints the same helper-budget sentence as CDP1-K0; CDP2-I1…I7 and the named extras; `[passed] CDP2-I (W2 install declaration, scope/owner admission, resolver, W2 guards)` |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | CDP2-A1…A6, including `1/32/33 provides batch at most 32`; `[passed] CDP2-A` |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | `[CDP2-B4/B5] multi-fiber dispose; tables=10 manifest=17 helpers=2283 40=1170 41=1097 42=16 ddl=414`; `[passed] CDP2-B` |
| 10 | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7` with the same G2a/G3b case list as the B0 row |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3` with G7-A…H and N1–N7 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2` with G6-A…H, N1–N9, L1–L5 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | CDP3-P1…P4; `[CDP3-P3] non-production barrier routes deferred, blocked_unknown and unsupported; G is held until the caller commits; replay-first keeps the original response while the barrier is non-ready`; `[passed] CDP3-P` |

Order 19 then 20 follows the plan: s8 before s7. Command 22 is the only new DP3 gate in this milestone.

## W1 not covered

At the W1 gate-time snapshot, live propagation, Divert/Raise/Leave, withdraw/release, inverse, production P6 classification, and bounded dispose of an already-activated instance were not implemented. CDP3-L/T/D/B were not added. The idle `lifecycle_step` and the deferred barrier probe were not those behaviors. Commit and push had not yet occurred. W1 was subsequently published as `103ec596`.

## W2 (2026-10-27)

Final serial run in the same worktree, branch `v24`, HEAD `103ec596040506e74a7babdc240312885843d9f0` plus W2 uncommitted changes. Every process below exited 0; total elapsed gate time was **87.36 seconds**. The runner awaited each process and stopped on any failure. Raw development evidence was captured in `/tmp/pg-agent-dp3-w2-final-gates.json` and `.log`; the durable command/results record is below. These are new W2 results, not copied B0/W1 exits. This commit publishes only W2; subsequent plan work pauses.

| Requirement | Evidence through real advance unless explicitly marked fixture |
|---|---|
| Shared transitive live; resolve/admission/reconcile agree | L1 production M→A→B invalidation; L5 exact require/view/pin keys, epoch/digest/check, scope/owner closure. DP2-I real install/owner admission and dense DAG; DP2-A production service/child successes retained |
| Old frozen pins readable | L1 old activation/run pins remain readable after provider off/closing/withdraw; owner fixture releases prove unreadable afterward. No production W3 release claim |
| P0 on/off/retry CAS, no-op receipt/replay, I7 | P2/P5 real controls; ready/claimed coalescing preserves frozen input/actor/identity, one slot; all required bigint increments overflow with zero writes; terminal/lineage refusals retained |
| Old NULL/non-NULL fence routing | P1/P6 generation/target drift is control classification; obsolete NULL-fence on/off and on/off/on settle empty no-op, clear I7, never begin a new generation; subsequent legal current control reaches active |
| Reload drift Divert | P1, L4/L8: target/control drift closes as divert without withdrawal, failure, inverse or iterator change; independent domain diagnosis matches interpreter |
| Active invalidation Leave/P5 | L1/L7: exact visibility set ≤256 withdrawn atomically;257 rejected before writes; child/reservation debts unchanged, no pin release |
| P1 missing dependency | DP2-A/B: `dependency_unresolved`, ten-table zero writes, no episode/failure/receipt/successor; same retained input succeeds after provider appears |
| Classified P2/P3/P4 Raise | L3/L4: all five exact failure-v1 combinations, seven keys/types/NULL/ranges, p4 first attributable manifest key; unassignable/empty-provides corruption propagates. DP2-A keeps committed prefix32 after later conflict, plus real batches1/32/33 |
| Narrow after-write conflict | L2 second INSERT AFTER trigger sees34 rows after committed prefix32; exact23505 + `contributions_service_addr` rolls back current two contributions and iterator, then same advance validates/applies one Raise. Earlier prefix and immutable facts preserved |
| Atomicity and unknown SQL failures | L2 domain/iterator/effect settlement/request/event/successor six U0007 boundaries roll back whole call; other23505/FK/CHECK/cancel/timeout propagate unchanged |
| Independent typed validator and fresh applier checks | L8 rejects forged P1 target, stale P2 vs Divert and forged failure diagnosis; production wrong target first proves write closure refusal, direct private validator with expanded closure independently proves `p1_target` refusal. Suppressed INSERT triggers fresh VOLATILE post-write failure |
| Guards | L9 monotonic closing/outcome/withdraw/failure, exact failure frozen episode seq, typed close/null constructor negatives and deferred active-pin/released-contribution consistency. Existing child CHECK retained |
| Closure and history | L6 DAG distinct512 succeeds/513 refuses; exact write closure512/513;601 closed episodes and600 terminal parents do not inflate current work. Existing lock ordering/G/replay tests retained |
| Cumulative compatibility | All21 old commands plus P/L passed. DP1-K now69 committed zero-write assertions; ACL, claim, identity, replay, locks, service/child, basic dispose and six host statuses retained |

One Oracle review identified the old NULL-fence slot being stranded and an insufficient independent P1 target negative. Both were fixed and covered by P6/L8 before the final batch. No second review was requested. Earlier development failures and assertion migrations are recorded in the deviation ledger.

| # | Command | Exit | Seconds | Printed final result |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0.49 | Cordis canonical loader and five refusal probes |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1.54 | Cordis fixture: transaction/catalog/role family/OID cleanup; PG18.4/psycopg2 2.9.12 |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1.60 | CDP1-E |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 1.68 | CDP1-D,117 zero-write negatives plus positive/COMMIT |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 13.54 | CDP1-K,69 committed zero-write assertions |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 3.30 | CDP2-K |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 3.92 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3.01 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 3.21 | CDP2-B |
| 10 | `uv run python v24/load.py` | 0 | 0.51 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1.57 | v24/s1 setup self-check |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 1.60 | v24 W2 G1-O owner DDL probes |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2.45 | v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 1.84 | v24 S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5.17 | v24 S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 3.77 | v24 S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3.16 | v24 S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 3.65 | v24 S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2.36 | v24 S8 W1-W3, G7-A…H + N1–N7 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 6.38 | v24 S7 W1-W2, G6-A…H + N1–N9 + L1–L5 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 9.99 | v24 G8,23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 2.65 | CDP3-P, P1…P6 including production P0 and obsolete NULL fence |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 9.97 | CDP3-L, L1…L9 |

Order s8 before s7 follows §4.1. No gate was run concurrently.

| W2 invariant | Actual evidence |
|---|---|
| Helper physical lines |40=1259,41=1119,42=557,sum2935≤5000; CDP1-K0/CDP2-K0/I0/B prints agree. Actual temporary module trees still prove5000 accepts/5001 rejects |
| DDL prefix |458≤900, CDP1-D/CDP2-B |
| Canonical loader |17 exact entries; no loader change in W2; loader/E/B green |
| Catalog/ACL |10 tables, one SECURITY DEFINER=`advance`; new helpers private, protocol role tests green |
| Views/extensions |0/0 source CREATE scan, not a new catalog claim |
| Freeze |All12 SHA-256 values rechecked against DP2 matrix and equal the Frozen SQL table above; full `57e2c1e` frozen diff exit0; v8 vs HEAD diff exit0 |
| Hygiene/isolation |`git diff --check` exit0; original10 dirty docs+24 unrelated untracked files preserved against34-path SHA-256 snapshot; only exact W2 paths staged |

## W2 not covered / pause boundary

At W2, P6 inverse, production pin release/episode close, activated dispose and CDP3-T/D/B were unimplemented. `command_barrier` production returned NULL and `lifecycle_step` stayed idle/unwired. Child inverse CHECK compatibility was unchanged. W2 owner fixtures for released pins, run/cell/listener/reservation, cycles and damaged/history facts proved only the named ledger/negative boundaries. No production listener registration/dispatch, run settlement, external recovery or automatic invalidation fan-out was claimed. W2 was published to `origin/v24` as `72af2528`. W3 evidence is below.

## W3 (2026-10-27)


Final serial run in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `72af2528` (W2 baseline) plus W3 changes before staging. Every process below exited 0; total elapsed gate time was **62.92 seconds**. Each command was a separate process, awaited before the next; the runner stopped on the first non-zero exit. No command was run concurrently. W3 is delivered by this commit.

| Requirement | Evidence through real `advance` unless explicitly marked fixture |
|---|---|
| P6 selector and barrier | `p6_plan` selects exactly one branch; `command_barrier` maps deferred/blocked_unknown/unsupported. CDP3-P7 real deferred is ten-table zero-write, leaves the continuation ready and consumes no request/effect. |
| First commit after barrier clears | CDP3-P7 ends the open owned run, resubmits the identical effect/outcome, and commits `episode_closed`; the DB acquires G only after the deferred caller commits. |
| Byte-identical replay | CDP3-P7 compares the same request's stored `response::text` and ten-table snapshot before and after replay; one request and one event remain. |
| Inverse batch | CDP3-T8: 33 contributions produce 32 (seq 32→1) then 1 (seq 0), strict `seq DESC`, no filtering or skipping. CDP3-T2/T8 keep physical rows and compare descriptor/inverse/seq. |
| Pin batch | CDP3-T4 releases an ended-run pin before contribution inverse. CDP3-T9: 31 run pins order by run/key/id, activation pins by key/id, combined first batch exactly 32 with run pins first; remaining activation pin is next. |
| Activation pin without run | CDP3-T3: live consumer activation pin defers provider release; real consumer pin-release unblocks the same provider request. |
| Run fixture boundary | CDP3-T4: open run defers; `run_pin_release_delta` returns `[]` while open and the pin after `ended_at`; run result stays NULL and no settlement is written. |
| Effect barriers | CDP3-T5: ready dispatch defers; claimed with expired lease still defers (not completion/cancel); settling it allows close; unknown is `blocked_unknown` zero-write; host_io is `0A000` with an unchanged ten-table snapshot. |
| Unsupported/unknown inverse | CDP3-T6: cell `restore_prev` and reservation `release_reservation` return SQLSTATE `0A000` with whole-call rollback; `unknown` returns `blocked_unknown` zero-write. P5 withdraws service/cell/listener only; reservation keeps its debt. |
| Listener inverse | CDP3-T7b: owner-fixture listener is withdrawn by P5; P6 releases the ledger row, keeps descriptor/inverse, and the unique listener address is occupied before release and reusable after. No dispatch or production listener registration is claimed. |
| Child inverse | CDP3-T7: parent P5 does not withdraw the child contribution; P6 defers until an owner-fixture `disposed_at` tombstone; inverse then sets `withdrawn_at` as release bookkeeping and `released_at`, preserving descriptor/FK and leaving P5 visibility claims unchanged. |
| History and address | CDP3-T10: released pin and `prev_contribution_id` rows remain queryable; a second registration conflicts after withdraw but before release; the address registers again only after release. |
| Close | CDP3-T1/T2: empty and non-empty episodes close with `closed_at`, `current_episode_id=NULL`, `retire_started_at=NULL`, unchanged state/outcome/failure/want_on and no new episode. |
| Lifecycle layout | `lifecycle_step` stays idle and unreferenced by `advance`/`interpret_command`; CDP3-P4 asserts only `advance` is SECURITY DEFINER. The new run `ended_at` guard is additive. |

| # | Command | Exit | Seconds | Printed final result |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0.05 | Cordis canonical loader and five refusal probes |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 0.62 | Cordis fixture: transaction/catalog/role family/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 0.69 | CDP1-E |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 0.78 | CDP1-D,117 zero-write negatives plus positive/COMMIT |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 12.49 | CDP1-K,69 committed zero-write assertions |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 2.39 | CDP2-K |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 3.07 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 2.17 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 2.35 | CDP2-B |
| 10 | `uv run python v24/load.py` | 0 | 0.06 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 0.67 | v24/s1 setup self-check |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 0.67 | v24 W2 G1-O owner DDL probes |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 1.57 | v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 0.93 | v24 S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 4.20 | v24 S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 2.85 | v24 S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 2.26 | v24 S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 2.80 | v24 S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 1.49 | v24 S8 W1-W3, G7-A…H + N1–N7 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 5.29 | v24 S7 W1-W2, G6-A…H + N1–N9 + L1–L5 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 8.91 | v24 G8,23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 1.98 | CDP3-P, P1…P7 including real P6 deferred/first commit/replay |
| 23 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 4.63 | CDP3-T, T1…T10 |

Order s8 before s7 follows §4.1. No gate was run concurrently.

| W3 invariant | Actual evidence |
|---|---|
| Helper physical lines | 40=1356, 41=1141, 42=758, sum **3255≤5000**; CDP1-K0/CDP2-K0/I0/B prints agree. Temporary 5000/5001 trees still prove the boundary |
| DDL prefix | 461≤900 |
| Canonical loader | 17 exact entries; loader unchanged and self-check green |
| Catalog/ACL | 10 tables, one SECURITY DEFINER (`advance`), public function EXECUTE 0, no new public writer |
| Views/extensions | 0/0 source CREATE scan and catalog view count 0 |
| Freeze | All 12 SHA-256 values equal the DP2 matrix; full `57e2c1e` frozen diff exit 0; v8 vs HEAD diff exit 0 |
| Hygiene/isolation | `git diff --check` exit 0; the original 10 dirty docs and 24 unrelated untracked files remain untouched; W3 changes stay in the worktree |

| W3 not covered / fixture boundary |
|---|
| W4 activated dispose, DP4 settlement, DP5 listener/dispatch/intercept/overlay, DP6 scanner/fairness/external recovery and child cleanup fan-out are not implemented. |
| `host_io` and settlement remain conservative refusals; no terminal label is treated as proof that an external resource was released. |
| Listener inverse, cell/reservation/unknown inverse, run/pin facts, child tombstone, effect barriers and historical rows are owner fixtures. They prove named ledger/blocking behavior only, not production registration, dispatch, run settlement or child cleanup. |
| The child `withdrawn_at` write is release bookkeeping forced by the existing CHECK, not a P5 visibility withdrawal. |
| P6 inverse/pin steps emit an ordinal-0 successor because fresh `advance` requests require a reserved key; the host enters P6 through a P0 `off` schedule. Close emits no successor and starts no episode. |
| `lifecycle_step` remains read-only idle and unwired. No W4 dispose handoff is claimed. |
| W3 is delivered by this commit to `origin/v24`. |

## W4 (2026-10-27)

Same worktree and branch `v24`, HEAD `284d7f2d420f6c9a73b1326bb7b4497ee8fa498e` plus W4 changes before staging. The 21 legacy commands and CDP3-P/T/D were launched one process at a time; **all 24 exited 0, total 93 seconds**. This commit publishes W4 to `origin/v24`.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 1 | canonical loader, 17 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1 | fixture/role family/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 2 | CDP1-E |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 2 | CDP1-D, DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 13 | CDP1-K, 5000/5001 budget proof |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4 | CDP2-K, staged dispose probe path |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4 | CDP2-I, ancestor seal admission |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4 | CDP2-B, staged clean/multi-fiber dispose, obligations/host six states |
| 10 | `uv run python v24/load.py` | 0 | 0 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 2 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 1 | G1-O owner DDL probes |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 3 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 5 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 3 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 10 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3 | CDP3-P, unchanged W1-W3 protocol |
| 23 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 5 | CDP3-T, unchanged W3 teardown |
| 24 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 6 | CDP3-D1…D7 |

Order s8 before s7 follows §4.1. No gate was run concurrently. The earlier split runs that found and fixed DP2 kernel/install adaptations are not counted as green; the table above is the final continuous sequence.

| W4 invariant | Actual evidence |
|---|---|
| Seal and admission | First `command_dispose` writes only `install_dispose_request` + `requested`; `dispose_ancestor_sealed` blocks descendant install/on/retry/resolve before cleanup. CDP3-D2 |
| Bounded object steps | Deepest descendant fiber → child-install tombstone → own fiber → parent install tombstone; one successor maximum, ordinal 0. CDP3-D1 |
| Parent controller | Parent does not occupy a successor; every later step uses a fresh same-LOGIN `command_dispose` key, and the original key replays byte-identically. CDP3-D1 |
| Successor whitelist | `continuation_state` accepts a dispose parent only for ordinal 0, a sealed target install, a selected fiber in its owner subtree, and when the parent receipt's `emitted` names this exact effect; different LOGIN gets `effect_id_conflict`. CDP3-D3/D8 |
| Event cardinality | Domain write → one domain event; successor-only → one `work_scheduled`; domain+successor → one domain event; replay/coalescing → zero events. CDP3-D1 |
| Independent validator | Forged target, phase and successor-only event are rejected by `dispose_delta` recomputation with zero write. CDP3-D7 |
| Parent-last | Grandchild install completion precedes child install completion, which precedes the parent fiber tombstone and parent install `completed`; child-install selection is depth DESC. CDP3-D1 |
| Deferred/no lock wait | Open run → v1 deferred, ten-table snapshot unchanged; caller commit frees G for a second connection; ended run then progresses. CDP3-D5 |
| host_io | ready/claimed/unknown/succeeded/failed/cancelled all remain `0A000`; terminal labels are not release proof. CDP3-D4 |
| Unknown debt | Non-host `unknown` effect → `blocked_unknown` with zero write. CDP3-D6 |
| Rank driver | Fuel `16×(1+F+I+E+C+P)`; every domain step lowers M, successor-only schedule lowers U, coalescing unchanged, no deferred/unsupported in the main fixture. CDP3-D1 |
| History closure | 600 settled effects on the selected fiber do not inflate the dispose closure; the install still converges. CDP3-D9 |
| Validator state | `dispose_delta` also rejects terminal/deferred/unsupported plan states before exact comparison; JSON-error negatives use ten-table snapshots instead of rollback-before-assert. CDP3-D7/DP2-B |
| No revival | Post-tombstone on/retry/register remain refused; installations stay `disposed`. CDP3-D2 |

A post-implementation Oracle review raised four issues; all were verified and fixed before the final run: (1) `dispose_command_seed` pulled historical episodes/effects/runs/pins into closure, now it locks only the target install and selected fiber/child install with episode/owner/scope coming from reference discovery; (2) a dispose parent successor was not bound to ordinal 0 or the parent's persisted `emitted` set, now both are required; (3) `basic_dispose` remained a validator/applier bypass, now removed with its event and probe usage; (4) JSON-error negatives rolled back before asserting, now they commit and compare ten-table snapshots. Self-review also found child-install completion ordered by id rather than depth, which could permanently defer a finishable grandchild; selection is now depth DESC and CDP3-D1 exercises root→child→grandchild. CDP3-D8/D9 were added for forged successors and history-inflated closure.

| W4 capacity / freeze / scope | Observed |
|---|---|
| Helper physical lines | 40=1373, 41=1193, 42=964, sum **3530≤5000**; temporary 5000/5001 proof still runs |
| DDL prefix | 461≤900 |
| Manifest / tables | 17 exact entries; 10 tables |
| DEFINER / ACL | one `SECURITY DEFINER` (`advance`); public function EXECUTE 0; new helpers private |
| Views/extensions | source CREATE scan 0/0; catalog view count 0 |
| Freeze | all 12 SHA-256 values equal the DP2 matrix; full `57e2c1e` frozen diff exit 0; v8 vs HEAD diff exit 0 |
| Hygiene/isolation | `git diff --check` exit 0; pre-existing 10 dirty docs and 24 unrelated untracked files preserved; only W4 paths staged |

| W4 not covered / fixture boundary |
|---|
| W5/CDP3-B closeout, DP4 settlement, DP5 listener/dispatch/intercept/overlay, DP6 scanner/fairness/external recovery and unbounded child fan-out are not implemented. |
| `host_io` and settlement remain conservative refusals; no terminal label is treated as proof of external release. |
| Open runs, unknown effects and external consumer pins are blocking fixtures in CDP3-D5/D6; they prove the bounded barrier, not a production run loop or external recovery. |
| `basic_dispose` and `install_disposed` were removed from the typed-op, validator, applier and event closed sets. Staged dispose is the only path, including probe tests. |
| `lifecycle_step` remains read-only idle and unwired; production dispose selection lives in `dispose_plan`/`dispose_delta`. |
| W4 is delivered by this commit to `origin/v24`. |

## W5 / closeout (2026-10-27)

Same worktree and branch `v24`, HEAD `f6a3a74` plus W5 changes before staging. The 21 legacy commands and CDP3-P/L/T/D/B were launched one process at a time; **all 26 exited 0, total 121.64 seconds**. W4's 24-command table omitted CDP3-L; W5 includes it. The first W5 sequence stopped at CDP3-L5 on the owner-chain cycle fixture, exposing a W4 regression that was fixed before this final sequence (see the deviation row below).

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0.59 | canonical loader, 17 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1.75 | fixture/role family/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1.68 | CDP1-E |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 1.78 | CDP1-D, DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 16.03 | CDP1-K, 5000/5001 budget proof |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 3.64 | CDP2-K, staged dispose probe path |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4.49 | CDP2-I, ancestor seal admission |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3.55 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4.40 | CDP2-B, staged dispose and obligations |
| 10 | `uv run python v24/load.py` | 0 | 0.56 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1.63 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 1.86 | G1-O owner DDL probes |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2.73 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 1.96 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5.91 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4.07 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3.54 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 4.91 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 3.00 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7.46 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 11.05 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3.16 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 11.46 | CDP3-L, including cycle/overflow fix |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 7.80 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 5.91 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 6.72 | CDP3-B1…B13 |

Order s8 before s7 follows §4.1. No gate was run concurrently. The earlier W5 sequence that failed at CDP3-L5 is not counted as green; the table above is the final continuous sequence after the fix.

| W5 invariant | Actual evidence |
|---|---|
| Layout / budget / manifest | 10 tables; 0 new public writers; only `advance` is SECURITY DEFINER; 40/41/42 and future 40–49 helpers total 3550≤5000 with temporary 5000/5001 proof; DDL prefix 461≤900; manifest 17; source VIEW/EXTENSION 0; public function EXECUTE 0. CDP3-B1 |
| Production service/child | Real install/activation/resolve creates a live service contribution and a live child contribution; no fixture is used. CDP3-B2 |
| Listener fixture boundary | A listener row is an explicitly labelled owner fixture; real P6 teardown releases the ledger row and keeps descriptor/inverse/physical row. No production listener registration or dispatch is claimed. CDP3-B3 |
| Unsupported inverse | Real cell and reservation contributions each make `advance` raise `0A000`; ten-table snapshot is unchanged. Unknown inverse returns `blocked_unknown` with zero write and keeps the debt row. CDP3-B4 |
| Barrier fields / lease expiry | Ready and claimed non-reconcile effects defer the drain; status, claim owner, lease, attempt and fence are unchanged; an expired lease is not cancelled, completed or treated as release. A second connection takes G after the caller commits. CDP3-B5 |
| Settlement / unwired surfaces | Claimed `host_io` settlement still raises `0A000` with no write; intercept and overlay installs raise `0A000`; dispatch/run_start cannot be admitted as commands; no production INSERT/UPDATE of `runs`, no recovery/scanner function, and `run_pin_release_delta` is read-only. CDP3-B6 |
| Caps / history | Structural successor 16 accepted and 17/duplicate refused; real closure seed 512 accepted and 513 refused; 600 terminal parents plus 601 closed generations leave the current closure under 50; real P6 inverse batches 32 then 1. CDP3-B7 |
| Address concurrency | Two simultaneous same-realm/same-key P2 attempts through separate connections yield exactly one live service contribution and one committed p2 `provide_conflict/address_conflict` Raise; two different realms both stay live and resolve locally. CDP3-B8 |
| P5 exact set | Exactly 256 service contributions are withdrawn with the exact event ID set; 257 eligible contributions refuse before writes with `retry_with_closure/withdraw_budget`; child/reservation debts are untouched. CDP3-B9 |
| Post-lock drift | Another session locks a pin/run/child contribution, then mutates its reference after the advance's first closure read; the real advance returns `retry_with_closure` with no DML, request, event or successor. CDP3-B10b |
| Postcondition rollback | Suppressing the inverse contribution update raises `23514`; suppressing the close episode update also raises `23514`; ten-table snapshots are unchanged in both cases. CDP3-B10 |
| Event cardinality | Domain+successor dispose produces exactly one `fiber_requested` event; successor-only produces exactly one `work_scheduled` event and no lifecycle-table change; coalescing emits nothing; replay adds no event. CDP3-B11 |
| Validator independence | A replaced interpreter returning forged target, phase, event or successor is rejected by the production validator with `invalid_outcome` and zero write. CDP3-B12 |
| Iterator / loader / guards | Iterator keys stay exactly `v,next_index,registered_through,control_seq`; the canonical loader refuses autocommit/online use; control-seq decrease, closed-episode rewrite, withdrawn/released reversal, run-end rewrite and scope-close rewrite all raise and leave snapshots unchanged. CDP3-B13 |

| Evidence class | W5 examples |
|---|---|
| Production path | Real service and child activation; real P5/P6 inside teardown; real staged dispose; real same-key race through two connections; real 512/513 closure discovery; real inverse/close postcondition rollback; real event cardinality; real validator rejection; real forward-only guard probes. |
| Owner fixture | Listener ledger row; cell/reservation/unknown inverse rows; ready/claimed barrier effect; claimable `host_io` row for settlement; run/pin/child drift targets and pre-lock mutation; 600 terminal parents and 601 closed generations; temporary fault-injection triggers; forged interpreter probe. Each is labelled at the point of use. |
| Not implemented / unclaimed | DP4 settlement, DP5 listener/dispatch/intercept/overlay, DP6 scanner/fairness/external recovery, unbounded child cleanup fan-out, production listener registration/dispatch and a production run loop. Owner fixtures do not upgrade those boundaries. |

| W5 capacity / freeze / scope | Observed |
|---|---|
| Helper physical lines | 40=1373, 41=1211, 42=966, sum **3550≤5000**; temporary 5000/5001 proof runs inside CDP1-K/CDP2-K/CDP3-B |
| DDL prefix | 461≤900 |
| Manifest / tables | 17 exact entries; 10 tables; source VIEW/EXTENSION 0 |
| DEFINER / ACL | one `SECURITY DEFINER` (`advance`); public function EXECUTE 0; public DML 0; service/admin/operator can execute only `advance` |
| Freeze | all 12 `v24/sql` SHA-256 values equal the DP2 matrix; `57e2c1e` frozen diff exit 0; v8 vs HEAD diff exit 0 |
| Hygiene/isolation | `git diff --check` exit 0; pre-existing dirty docs and unrelated untracked files preserved; only W5 paths staged |
| Deferred/G | ten-table snapshot unchanged and a second connection acquires G after the deferred caller commits |

| W5 deviation / fix | Detail |
|---|---|
| CDP3-L cycle regression | The first 26-command W5 sequence stopped at CDP3-L5: an owner-chain cycle was reported as `lineage`/`owner_closing`, not `cycle`/`retry_with_closure`. Root cause: W4's `dispose_ancestor_sealed` deliberately fails closed on cycles and overflow, and both `live_node_fault` and `activation_admission` used it before graph diagnostics. Fix: a private `lineage_fault` now distinguishes `cycle`/`closure_overflow` from sealed lineage; `activation_admission` maps it to `retry_with_closure`, and `live_node_fault` supplies the cycle/overflow fault to `fiber_live_state`. Sealed-lineage behavior is unchanged. Production SQL changed only 41 (+18 lines) and 42 (+2 lines); no table, column, enum, extension, public writer or new scheduler was added. The full 26-command sequence was rerun from command 1 and is the table above. |

| W5 not covered / final scope |
|---|
| DP4 settlement, DP5 listener/dispatch/intercept/overlay, DP6 scanner/fairness/external recovery and unbounded child cleanup fan-out are not implemented. |
| `host_io` and settlement remain conservative refusals; no terminal label is treated as proof of external release. |
| Listener, cell, reservation, unknown, run, cell/listener inverse, drift targets and history rows are owner fixtures or explicit barriers; they do not establish production registration, dispatch, settlement or external recovery. |
| W5 is delivered by this commit to `origin/v24`. |