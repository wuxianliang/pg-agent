# Cordis v2 DP4 Conformance Matrix

B0 executed on 2026-10-27 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `4b34bf28e83791a7af3356f8036237afca78b67a`. Every exit code in the B0 table is a process exit from a serial run on this worktree; no DP3/DP2 exit is copied as a DP4 result. DP4 production behavior is not implemented at B0.

## Scope

B0 fixes the baseline, registers the 18th manifest module, extends the four-file helper budget, and records the 26 pre-DP4 gates. W1 (`run_start`), W2 (model/reducer), W3 (tool), W4 (seal/budget), and W5 (closeout) are unstarted. `v24/cordis/sql/43_loop.sql` contains only a no-op scaffold.

## Environment

Commands ran from the worktree root. `uv run` resolved the worktree's `.venv`.

| Item | Observed value |
|---|---|
| `pwd -P` | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` (exit 0) |
| `git rev-parse --show-toplevel` | same path (exit 0) |
| branch / upstream | `v24` / `origin/v24` |
| HEAD | `4b34bf28e83791a7af3356f8036237afca78b67a`, subject `v24: add DP3 W5 boundary gate and closeout` |
| `git fetch origin`; `origin/v24...v24` | exit 0; `0 0` |
| platform | Darwin 25.6.0 arm64, macOS 26.6.2 |
| uv / Python / psycopg2 | 0.8.24 / 3.12.11 / 2.9.12 (dt dec pq3 ext lo64) |
| PostgreSQL | 18.4 (`180004`), printed by the Cordis fixture self-check |
| `.venv` | worktree directory under `v99`, not the main checkout |

Before B0 added artifacts, `git status --porcelain=v1` showed 10 modified tracked paths and 26 untracked paths. They were preserved; none is staged by B0. The pre-existing modifications include user edits to the design, DP1/DP2 plans, DP1/DP2 matrices/ledgers, DP1/DP2 READMEs, and the DP1 critique. DP4 treats the design as read-only.

## Frozen SQL

All twelve `v24/sql/*.sql` SHA-256 values match the DP2/DP3 frozen column:

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

`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 ... v24/s12` exited 0 with no output. The run predates the B0 loader edit, so `v24/load.py` was frozen at that moment; B0 then registered `43_loop.sql` as required by its scope. `git diff --check` exited 0.

## Capacity

Physical lines use `str.splitlines()`, the same count as the DP1/DP2/DP3 budget asserts. DDL prefix is `10_installs.sql` through `17_effects.sql`, plus `20_relations.sql` and `30_triggers.sql`.

| Item | Before B0 | After B0 scaffold |
|---|---:|---:|
| `40_advance.sql` | 1373 | 1373 |
| `41_lifecycle.sql` | 1211 | 1211 |
| `42_teardown.sql` | 966 | 966 |
| `43_loop.sql` | absent | 2 (comment + no-op) |
| four-file helper sum | 3550 | **3552≤5000** |
| DDL prefix | 461 | **461≤900** |
| manifest | 17 | **18** |
| tables / `SECURITY DEFINER` | 10 / 1 (`advance`) | 10 / 1 (`advance`) |

DP1-K0 invoked the shared predicate on a temporary four-file tree of exactly 5000 physical lines and on a 5001-line tree; the first returned total 5000 and the second raised `AssertionError`. It then checked the real tree. The no-op line is required because psycopg2 rejects an empty SQL file; it creates no object and has no runtime effect.

## B0 serial gates

Each command below was a separate `uv run python` process, launched after the previous one exited. The runner stopped on the first non-zero exit. This is the final sequence after the 18-entry manifest was registered; all 26 exited 0, total elapsed 118 seconds.

| # | Command | Exit | Evidence |
|---:|---|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | canonical loader and five refusal probes |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PostgreSQL 18.4, psycopg2 2.9.12, fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | CDP1-E exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | CDP1-D; DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | CDP1-K; helper 3552, 5000 admitted / 5001 rejected |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | CDP2-K continuation/typed delta/closure/replay |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | CDP2-I install declaration/admission |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | CDP2-A activation and provide bounds |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | CDP2-B `tables=10 manifest=18 helpers=3552 ... ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | G1-O owner DDL |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | CDP3-B1…B13 |

Order 19 then 20 follows the plan: s8 before s7. No command was concurrent, joined with `;`, or skipped after a failure.

## B0 not covered

- No `run_start`, model/tool settlement, reducer, budget/seal, run writer, or DP4 gate exists yet. CDP4-R/M/T/X/B are not claimed.
- `host_io` and settlement remain `0A000`; `dispatch`/`listener_call` remain unwired; no scanner exists. These are DP3 facts, not DP4 evidence.
- B0 did not push. Publication remains blocked on the user naming a remote/branch (plan §3.10 decision 8).
