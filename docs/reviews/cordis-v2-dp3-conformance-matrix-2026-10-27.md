# Cordis v2 DP3 Conformance Matrix

B0 executed on 2026-10-27 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `9fe6b5b170776907d490fab079fca63cdde6aa28`. Every exit code below is the process exit from this serial run. DP2's 2026-10-26 exits, including the W5 rerun on `d5fd1bc`, are not copied here. Durations were not recorded. No DP3 gate exists yet, so this matrix does not claim CDP3-P/L/T/D/B.

## Scope

B0 records the live baseline and corrects stale DP2 current-state text. It does not implement teardown. W1–W5 of DP3 are unstarted.

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

## Capacity

Physical lines use `str.splitlines()`, the same count as DP1/DP2 budget asserts. DDL prefix is `10_installs.sql` through `17_effects.sql`, plus `20_relations.sql` and `30_triggers.sql`.

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

## Serial gates

Each command was a separate process. None was joined with `;`, run in the background, or skipped after a failure. There was no failure.

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

## Not covered

DP3 production paths are uncovered: live propagation, Divert/Raise/Leave, withdraw/release, inverse, P6 drain, and bounded dispose of an already-activated instance. No CDP3 script was run because none exists. The 5000/5001 budget boundary was not executed. Commit and push were not performed.
