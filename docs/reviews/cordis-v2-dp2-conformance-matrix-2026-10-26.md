# Cordis v2 DP2 Conformance Matrix

B0 executed on 2026-10-26 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `0590d4703ea1404febbc82d6114fd8d91f385902`. Every exit code below is an actual process result from this run; no historical DP1 exit code is reused. Durations were not collected because they are not required B0 evidence; each row's evidence is the actual exit code plus the named assertions printed by that run.

## Scope

B0 is a baseline-verification milestone only. Covered: repository/environment facts, the five existing Cordis DP1 commands, the eleven v24 regression commands, the separate s9 gate, the twelve frozen SQL SHA-256 values, the frozen diff, the current SQL line budgets, and the four DP2 documentation artifacts. Not covered: any DP2 implementation and any DP2 named assertion (CDP2-K/I/A/B remain unimplemented and unrun). Local verification is complete and the B0 milestone is **closed**: on 2026-10-26 the user authorized per-milestone commit + push to `origin/v24`, and B0 was committed and pushed accordingly (closure commit `v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`).

## B0 environment and repository facts

| Item | Observed value |
|---|---|
| worktree / branch | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` / `v24` |
| HEAD | `0590d4703ea1404febbc82d6114fd8d91f385902` |
| upstream | `origin/v24`; `git rev-list --left-right --count origin/v24...v24` = `0 0` |
| DP1 delivery commits | `5163b23` loader/fixture, `e9ccf30` DDL, `69efd38` kernel/ACL, `0590d47` closeout |
| frozen comparison baseline | `57e2c1e` (not the DP2 expected HEAD) |
| Python / psycopg2 / PostgreSQL | 3.12.11 / 2.9.12 (dt dec pq3 ext lo64) / 18.4 (180004), Unix socket only |
| tracked working tree | no modified, staged, or deleted tracked files |
| untracked files | 24 pre-existing files, all under `docs/` (user inputs, preserved and not staged); B0 adds only its own three artifacts |
| Cordis manifest | `v24/cordis/load.py` unchanged, fifteen files `00,10,11,12,13,14,15,16,17,18,19,20,30,40,50` |
| SQL budget | `v24/cordis/sql/40_advance.sql` = 340 physical lines (≤1200); DDL prefix `10`–`17`/`20`/`30` = 350 physical lines (≤900) |
| production implementation | `v24/cordis/sql/**` untouched by B0; lifecycle interpreters still `0A000` |

## B0 actual results — five Cordis DP1 commands

| Gate | Command | Exit | Observed named assertions |
|---|---|---:|---|
| loader | `uv run python v24/cordis/load.py` | 0 | `[passed] Cordis canonical loader and five refusal probes` |
| fixture | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PG 18.4 (180004), psycopg2 2.9.12; `[passed] Cordis fixture: transaction/catalog/role family/OID cleanup` |
| CDP1-E | `uv run python v24/cordis/dp1/test_environment.py` | 0 | CDP1-E1 exact manifest + five refusal families; E2 socket-only/libpq refusals; E3 current/empty prefix catalogs, caller transaction, core functions |
| CDP1-D | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | CDP1-D1…D4; DDL lines 350; `[passed] CDP1-D (97 zero-write negative probes plus positive/COMMIT cases)` |
| CDP1-K | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | CDP1-K1…K5; `[passed] CDP1-K (66 committed zero-write assertions; lifecycle interpreters remain 0A000)` |

## B0 actual results — eleven v24 regression commands and the separate s9 gate

| Gate | Command | Exit | Observed named assertions |
|---|---|---:|---|
| v24 loader | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` |
| v24 s1 fixture | `uv run python v24/s1/setup_db.py --self-check` | 0 | psycopg2/socket/loader/DSN/fixture/cleanup self-checks all passed |
| v24 G1 DDL | `uv run python v24/s1/test_ddl.py` | 0 | ten tables, FK split, partial indexes, five trigger groups, T2–T4 guard rejections |
| v24 G1 | `uv run python v24/s1/test_g1.py` | 0 | G1-A/P/Q/H/F/R/B/D/J/I/J/K/C/L1/L2, Done 1–8; three role-family ACL suites; 30 DML refusals each |
| v24 S2 | `uv run python v24/s2/test_g3a.py` | 0 | G3a-A1…A6, W2a/W2b/W2c, J, B/C/D/E, F/G, K |
| v24 S3 | `uv run python v24/s3/test_g2.py` | 0 | G2a-0…11, G3b-1…5, pin predicate suite |
| v24 S4 | `uv run python v24/s4/test_g2b.py` | 0 | G2b-A…T-10, ledger equation cases, 4 race trials, unknown-wall suite |
| v24 S5 | `uv run python v24/s5/test_g4.py` | 0 | G4-A…Q including M-1…M-8 boundary matrix |
| v24 S6 | `uv run python v24/s6/test_g5.py` | 0 | G5-K1…K10, W2, D1…D6; disposable DB probes |
| v24 S8 | `uv run python v24/s8/test_g7.py` | 0 | G7-A…H plus N1–N7 (15 named sub-cases) |
| v24 S7 | `uv run python v24/s7/test_g6.py` | 0 | G6-A…H, N1–N9, L1–L5 (35 named sub-cases) with pg_blocking_pids evidence |
| s9 (separate) | `uv run python v24/s9/test_g8.py` | 0 | G8-H1…H13, C1/C2, L1…L3, R1, D1a/D1b/D2, W1 — 23 named cases |

## Frozen v24 baseline

All twelve `v24/sql/*.sql` SHA-256 values match the DP1 P0 record exactly:

| SQL | B0 SHA-256 | Matches DP1 P0 |
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

`git diff 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12` exited 0 with no output: the frozen v24 loader, SQL and stage directories are byte-identical to the comparison baseline. No frozen file was modified to make a regression pass.

## DP2 named-assertion coverage

DP2 named assertions are **not implemented and not run**. They are listed here with their planned work item so that B0 is not read as partial DP2 coverage.

| Assertion | Planned work item | Producer | Evidence | Exit | Uncovered remainder |
|---|---|---|---|---:|---|
| CDP2-K1…K8 | W1 | `v24/cordis/dp2/test_kernel.py` | none — file does not exist | — | all: lock order, ready continuation replay/identity/forgery, typed delta shapes and branch permissions, injected-fault atomicity, terminal guard, generation recheck, aggregate events |
| CDP2-I1…I5 | W2 | `v24/cordis/dp2/test_install.py` | none — file does not exist | — | all: three scope variants, declaration validation, owner ledger, realm routing, deferred unique-root guard |
| CDP2-A1…A6 | W3 | `v24/cordis/dp2/test_activation.py` | none — file does not exist | — | all: P0 CAS/no-op, P1 freeze, P2 batching ≤32, P4 totality, address exclusivity, ownership/DAG |
| CDP2-B1…B5 | W4 | `v24/cordis/dp2/test_boundaries.py` | none — file does not exist | — | all: unsupported `0A000` boundaries, basic dispose proofs and host-obligation refusals, table/manifest/budget invariants |

B0 therefore covers **zero** DP2 named assertions. It covers the DP1 named assertions CDP1-E1…E3, CDP1-D1…D4 and CDP1-K1…K5 by rerun, and the eleven v24 plus s9 regression suites by rerun.

## B0 uncovered items

- All DP2 lifecycle behavior: install, scope creation, resolve/check, P0–P4 activation, typed delta, successor execution, aggregate events, basic dispose.
- The 33-item `provides` batch fixture, the 512/513 DP2 closure boundary and every forced negative in plan §3.13.
- SQL budget for new helpers: only the current 340/1200 and 350/900 baselines are measured; no DP2 helper exists yet.
- Publication: resolved by user authorization on 2026-10-26 (per-milestone commit + push to `origin/v24`). The closure commit was pushed without force and without bypassing hooks, and the 24 pre-existing untracked `docs/**` user inputs were deliberately left out of the commit.
