# Cordis v2 DP3 Conformance Matrix

B0 executed on 2026-10-27 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `9fe6b5b170776907d490fab079fca63cdde6aa28`. Every exit code in the B0 table is the process exit from that serial run. DP2's 2026-10-26 exits, including the W5 rerun on `d5fd1bc`, are not copied here. Durations were not recorded. W1 later ran its own 22-command sequence on the same uncommitted HEAD. That sequence is the W1 section. It does not replace the B0 numbers.

## Scope

B0 (`ba4f533`) records the baseline; W1 (`103ec596`) adds layout/budget/protocol probes. This commit delivers W2 live invalidation and entry into closing. Current evidence is in the W2 section; B0/W1 sections retain their gate-time history. W3–W5 are unimplemented and paused after this W2 publication to `origin/v24`. CDP3-T/D/B are not claimed.

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

P6 inverse, production pin release/episode close, activated dispose and CDP3-T/D/B remain unimplemented. `command_barrier` production returns NULL and `lifecycle_step` stays idle/unwired; W2 uses the independently validated reconcile selector rather than claiming that stub is a P6 selector. Child inverse CHECK compatibility is unchanged. Owner fixtures for released pins, run/cell/listener/reservation, cycles and damaged/history facts prove only the named ledger/negative boundaries. No production listener registration/dispatch, run settlement, external recovery or automatic invalidation fan-out is claimed. W2 publishes independently to `origin/v24`, then all later plan work pauses per user instruction.
