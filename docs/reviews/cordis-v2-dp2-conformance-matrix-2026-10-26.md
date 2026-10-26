# Cordis v2 DP2 Conformance Matrix

B0 executed on 2026-10-26 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `0590d4703ea1404febbc82d6114fd8d91f385902`. Every exit code below is an actual process result from this run; no historical DP1 exit code is reused. Durations were not collected because they are not required B0 evidence; each row's evidence is the actual exit code plus the named assertions printed by that run.

## Scope

B0 is a baseline-verification milestone only; W1 is the first DP2 implementation milestone. B0 covered repository/environment facts, the five existing Cordis DP1 commands, the eleven v24 regression commands, the separate s9 gate, the twelve frozen SQL SHA-256 values, the frozen diff, the current SQL line budgets, and the four DP2 documentation artifacts. W1 covers ready-continuation execution/replay, reserved successor identity, P0→P1 generation, command closure, typed delta/applier, terminal receipt guard and CDP2-K; it closed at commit `50affb0`, pushed to `origin/v24`. W2 covers install declaration, contracts/check, root/existing/child scope admission, owner ledger, unique-root / final-state DAG / committed-view guard and resolver; its CDP2-I and the full 19-gate post-fix sweep are green locally; the one bounded Oracle review completed, six findings were fixed, and W2 is closed out with commit/push to `origin/v24` in this run. W3–W5, CDP2-A and CDP2-B remain unimplemented and unrun. The W1 bounded Oracle review is complete: five actionable findings were raised and fixed. The B0 milestone is closed: on 2026-10-26 the user authorized per-milestone commit + push to `origin/v24`, and B0 was committed and pushed accordingly.

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

## W1 actual results — 2026-10-26

W1 was executed in the same worktree on top of B0 HEAD `5e36a5a`, branch `v24`, and closed at commit `50affb0` (subject: `v24: implement DP2 continuation and typed delta kernel`), pushed to `origin/v24`.

| Gate | Command | Exit | Observed named assertions |
|---|---|---:|---|
| CDP1-D | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | D1–D4; 113 zero-write probes; terminal reopen/outcome/settled/attempt (increase and decrease)/fence/claim/lease → `55000`; printed `terminal attempt/fence +1 and -1 -> 55000`; request response immutable |
| CDP1-K | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | K1–K5; 66 committed zero-write assertions; malformed command → `invalid_args`, valid lifecycle → `0A000` |
| CDP2-K | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | K1 lock order/replay bypass; K2 P0→P1→P2→P4/install/dispose/replay + mixed-history timestamp preservation; K3 forged identity/non-ready/ordinal; K4 nine typed ops, six event null/type, invalid successor, branch denial; K4b production seams, owner/dispose/pin/provide bounds, 512 fibers + 1 episode 513 cutoff, P0 no-op; K5 injected faults; K6 terminal guard; K7 generation and retry; K8 aggregate events |
| Cordis loader/fixture/environment | `load.py`, `setup_db.py --self-check`, `test_environment.py` | 0 | fifteen-file manifest refusal probes; PG 18.4/psycopg2 2.9.12; socket-only/libpq refusals; exact prefix catalogs |
| eleven v24 + s9 | the B0 command list, rerun serially | 0 | same named assertions as the B0 table; s9 23 cases; no domain regression |

The W1 gate is a disposable-DB probe: it creates two `TestDB` databases, leaves production `interpret_command`/`interpret_settlement` at `0A000`, and replaces the interpreters only in the probe DB so the real `advance`, `validate_delta`, `validate_domain`, `validate_and_apply_delta`, triggers and lock graph execute. `test_support.py` reuses DP1's `Server`/`TestDB`/`TABLES`/`snapshot`; no production DB is reused.

W1 budgets and preservation:

| Item | W1 observed value |
|---|---|
| `40_advance.sql` | 1196 physical lines (≤1200), 4 lines remaining |
| DDL prefix `10`–`17`/`20`/`30` | 360 physical lines (≤900); `30_triggers.sql` 194 |
| canonical manifest | fifteen files at W1 close; W2 later adds `41_lifecycle.sql` (sixteen files) |
| frozen v24 core | `v24/load.py`, `v24/sql/**`, `v24/s1`–`v24/s12` unchanged; twelve SHA-256 and `57e2c1e` diff rechecked |
| production seam | direct install is data-only; reconcile/dispose spec-valid paths remain `0A000`; W3/W4 own activation/dispose |

Wire v1 conformance: `command_dispose` takes exactly `{install_id}`; the probe-derived `basic_dispose` delta alone carries `fiber_ids`. Root scope is exactly `{mode,id,realm_overrides}`, existing `{mode,id}`, child `{mode,id,parent_id}`. `test_kernel.py` inserts its DP1 directory with `Path(__file__).resolve()` before fixture imports; K2 asserts the one-entity `[0,1,2,3]` cursor. The `40_advance.sql` review fixes left only 4 lines at W1 close. The user resolved the W2 layout by authorizing `v24/cordis/sql/41_lifecycle.sql`; W2 then measured `40_advance.sql` 1119/1200 and DDL 414/900, so the cap is viable with the new file. This was an integration decision, not a scope change.

The **full bounded Oracle review** raised five findings, all fixed in W1: (1) `event_payload_valid`/`json_array_valid` validate all six lifecycle event variants (nested UUID/integer/boolean/array types and nulls; DP1 host `receipt` remains object-only) and branch comparisons use `IS DISTINCT FROM`; (2) lifecycle successors are prevalidated as command_reconcile/ordinal 0/exact input before DML and invalid kinds return `invalid_outcome`/`successor_kind`; (3) dispose closure uses `UNION ... LIMIT 513` with an append-time bound; (4) `basic_dispose` only stamps non-disposed fibers and preserves existing timestamps; (5) the P2 cross-fiber negative supplies a valid event/successor and asserts `p1_context` with the episode DML sentinel. New negatives: six event variants null/type, invalid successor, 512 fibers + 1 episode closure, mixed-history dispose.

K2 episode-binding negative is deliberately non-NULL: the child points at a closed episode or an open episode whose fiber `current_episode_id` is NULL; both are rejected before any request/event/DML. The owner full-schema snapshot is identical before and after.

W1 boundary not claimed: ownerful/child-scope install admission and resolver (W2), full P0–P4 production activation (W3), production dispose (W4), cross-LOGIN continuation principal separation, and any W5 closeout. W2 is now implemented locally (next section); W3/W4 remain unimplemented, and the W1 boundary statement is historical. `effects_one_reconcile` still allows one ready/claimed reconcile per fiber; CDP2-K's 16-successor structural bound therefore mostly exercises non-reconcile successor kinds. A failed P1/P2 child remains `ready` with no request and can be retried once; K7 proves replay does not duplicate it.

**Bounded Oracle review status: complete.** The full bounded review raised five findings — event null/type (P1.1), successor prevalidation (P1.2), dispose closure 513 (P1.3), dispose timestamp preservation (P1.4), and the cross-fiber test reaching `p1_context` (P2) — all fixed and covered by CDP2-K/CDP1. Two earlier focused Oracle chats separately confirmed the parent-fiber predicate and the terminal guard's `ready`→`succeeded`/terminal rejection, and surfaced the attempt/fence ordering issue now fixed. Full-file review requests timed out against `codex_custom_gpt-6-astra-xhigh`; that timeout is not claimed as a completed full-file review and does not negate the completed bounded review. Per instruction there were no retries after the timeout.

**Actual W1 exit codes (18/18):**

```text
EXIT 0 :: v24/load.py
EXIT 0 :: v24/s1/setup_db.py --self-check
EXIT 0 :: v24/s1/test_ddl.py
EXIT 0 :: v24/s1/test_g1.py
EXIT 0 :: v24/s2/test_g3a.py
EXIT 0 :: v24/s3/test_g2.py
EXIT 0 :: v24/s4/test_g2b.py
EXIT 0 :: v24/s5/test_g4.py
EXIT 0 :: v24/s6/test_g5.py
EXIT 0 :: v24/s8/test_g7.py
EXIT 0 :: v24/s7/test_g6.py
EXIT 0 :: v24/s9/test_g8.py
EXIT 0 :: v24/cordis/load.py
EXIT 0 :: v24/cordis/dp1/setup_db.py --self-check
EXIT 0 :: v24/cordis/dp1/test_environment.py
EXIT 0 :: v24/cordis/dp1/test_ddl.py
EXIT 0 :: v24/cordis/dp1/test_kernel.py
EXIT 0 :: v24/cordis/dp2/test_kernel.py
```

**Intermediate failure (honest record).** The first post-review full rerun stopped at `[5] uv run python v24/cordis/dp1/test_kernel.py` with `EXIT 1`; `test_kernel.py:428` raised `KeyError: 'disposition'`. The strict event validator had initially rejected DP1’s synthetic `receipt` event (`payload {}`), causing the successful host settlement to return an error. Adding the object-only `receipt` carve-out restored CDP1-K, and the final 18-command rerun above is all `EXIT 0`; the failed run is not counted as passing evidence.

## W2 actual results — 2026-10-26

W2 was implemented in the same worktree on top of W1 commit `50affb0`, branch `v24`. The new canonical file is `v24/cordis/sql/41_lifecycle.sql`, between `40_advance.sql` and `50_permissions.sql`; the manifest is sixteen files. `40_advance.sql` keeps only a 3-line command entry seam (`install_preflight` + typed error return). No table, column, enum or extension was added; the fifteen-table invariant is unchanged.

| Gate | Command | Exit | Observed named assertions |
|---|---|---:|---|
| loader | `uv run python v24/cordis/load.py` | 0 | sixteen-file canonical loader and five refusal probes |
| DP1 fixture | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PG 18.4 (180004), psycopg2 2.9.12; transaction/catalog/role family/OID cleanup |
| CDP1-E | `uv run python v24/cordis/dp1/test_environment.py` | 0 | exact sixteen-file manifest; socket-only/libpq refusals; prefix catalogs |
| CDP1-D | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 117 zero-write negative probes plus positive/COMMIT cases; DDL lines 414; committed-view and graph guards |
| CDP1-K | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 66 committed zero-write assertions; W2 install is data-only; reconcile/dispose remain `0A000` |
| CDP2-K | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | W1 continuation, typed delta, closure, terminal receipt, events; production install data-only |
| CDP2-I | `uv run python v24/cordis/dp2/test_install.py` | 0 | I1–I7, I5b/I5c, I6b/I6c: direct root/ownerless existing install; owner ledger/uppercase UUID/iterator/failure; declaration/contracts/check four replay combinations; resolver/realms/provider admission; closed/disposal-request ancestry; unique root/pin/run cycle/committed view; dense DAG; forged deltas; disposed root |
| v24 loader/fixture | `uv run python v24/load.py`; `v24/s1/setup_db.py --self-check` | 0 | v24 loader; one-transaction closed-set catalog and OID-verified cleanup |
| v24 s1–s9 | the eleven B0 commands plus s9, rerun serially | 0 | G1–G8 named assertions; s9 23 cases; no domain regression |

The complete 19-command sequence, in execution order, is:

```text
1  uv run python v24/cordis/load.py                          EXIT 0
2  uv run python v24/cordis/dp1/setup_db.py --self-check     EXIT 0
3  uv run python v24/cordis/dp1/test_environment.py          EXIT 0
4  uv run python v24/cordis/dp1/test_ddl.py                  EXIT 0
5  uv run python v24/cordis/dp1/test_kernel.py               EXIT 0
6  uv run python v24/cordis/dp2/test_kernel.py               EXIT 0
7  uv run python v24/cordis/dp2/test_install.py              EXIT 0
8  uv run python v24/load.py                                 EXIT 0
9  uv run python v24/s1/setup_db.py --self-check             EXIT 0
10 uv run python v24/s1/test_ddl.py                          EXIT 0
11 uv run python v24/s1/test_g1.py                           EXIT 0
12 uv run python v24/s2/test_g3a.py                          EXIT 0
13 uv run python v24/s3/test_g2.py                           EXIT 0
14 uv run python v24/s4/test_g2b.py                          EXIT 0
15 uv run python v24/s5/test_g4.py                           EXIT 0
16 uv run python v24/s6/test_g5.py                           EXIT 0
17 uv run python v24/s8/test_g7.py                           EXIT 0
18 uv run python v24/s7/test_g6.py                           EXIT 0
19 uv run python v24/s9/test_g8.py                           EXIT 0
```

W2 budgets and preservation:

| Item | W2 observed value |
|---|---|
| `40_advance.sql` | 1119 physical lines (≤1200); 3-line command entry seam |
| `41_lifecycle.sql` | 586 physical lines; new canonical file after 40 |
| DDL prefix `10`–`17`/`20`/`30` | 414 physical lines (≤900); `30_triggers.sql` 248 |
| canonical manifest | sixteen files in `v24/cordis/load.py`; DP1 environment tuple matched |
| frozen v24 core | `v24/load.py`, `v24/sql/**`, `v24/s1`–`v24/s12` unchanged; twelve SHA-256 and `57e2c1e` diff rechecked |
| production seam | W2 checkpoint: P0–P4 and dispose were `0A000`. W3 now implements P0–P4; dispose remains `0A000` |

**W2 bounded review status: complete.** The one bounded Oracle review (two lanes) completed and raised six findings, all fixed and re-gated: uppercase caller UUID text versus canonical UUID comparison (event/domain canonicalization plus regression); `fiber_lineage_open` ignoring `dispose_requested_at` (now closes every ancestor, with child-install and descendant-resolve negatives); owner iterator accepting string `v` or extra keys (now exact `{v,next_index,registered_through,control_seq}` with numeric `v`); owner admission ignoring current-generation `failure` (now `owner_closing`/`install_owner_failure`); `guard_fiber_graph` counting paths via `UNION ALL` (now deduplicated reachability, distinct-element limit, multiple-root/cycle/depth retained, dense-DAG regression); and the forged install-owner test mutating `fiber_create` instead of `install_create`. The post-fix 19-command sequence is all `EXIT 0`; W2 is committed/pushed to `origin/v24` in this closeout, and no W3 work was started.


## DP2 named-assertion coverage

CDP2-K is implemented and passed by W1; CDP2-I is implemented and passed by W2; CDP2-A is implemented and passed by W3; CDP2-B remains unimplemented. They are listed with their planned work item so B0 is not read as DP2 coverage.

| Assertion | Planned work item | Producer | Evidence | Exit | Uncovered remainder |
|---|---|---|---|---:|---|
| CDP2-K1…K8 | W1 | `v24/cordis/dp2/test_kernel.py` | CDP2-K exit 0 with K1–K8/K4b printed assertions | 0 | covered: lock order, ready continuation replay/identity/forgery, typed delta shapes and branch permissions, injected-fault atomicity, terminal guard, generation recheck, aggregate events. Remaining: W3/W4 domains and cross-LOGIN continuation |
| CDP2-I1…I7/I5b/I6b | W2 | `v24/cordis/dp2/test_install.py` | CDP2-I exit 0 with all named sections printed | 0 | covered: direct data-only install, three scope variants, declaration/contracts/check, owner ledger, resolver/realms/provider admission, unique root, pin/run DAG cycles, committed-view immutable, forged deltas, disposed root. Remaining: W3/W4 behavior |
| CDP2-A1…A6 | W3 | `v24/cordis/dp2/test_activation.py` | CDP2-A exit 0; A1–A6 printed | 0 | covered: real P0–P4 for 0/1/32/33, retry after missing dependency and failed later batch, realm split, real owner, immutable view. Remaining: reachable command graphs do not build a pin cycle (direct `activation_dag` proves the cycle result); dispose and DP3 drift conversion are W4/later |
| CDP2-B1…B5 | W4 | `v24/cordis/dp2/test_boundaries.py` | none — file does not exist | — | all: unsupported `0A000` boundaries, basic dispose proofs and host-obligation refusals, table/manifest/budget invariants |

B0 therefore covers **zero** DP2 named assertions; W1 covers CDP2-K1…K8 (exit 0); W2 covers CDP2-I1…I7/I5b/I6b (exit 0); W3 covers CDP2-A1…A6 (exit 0). B0 covers the DP1 named assertions CDP1-E1…E3, CDP1-D1…D4 and CDP1-K1…K5 by rerun, and the eleven v24 plus s9 regression suites by rerun.

## B0 uncovered items

- At B0, all DP2 lifecycle behavior was unverified. W1 later covered CDP2-K; W2 later covered install/scope/resolve/check and the W2 guards. P0–P4 activation, production dispose and the W4 boundary remain uncovered.
- The 33-item `provides` batch fixture, the 512/513 DP2 closure boundary and every forced negative in plan §3.13.
- SQL budget for new helpers: B0 measured only 340/1200 and 350/900. W2 later measured 40=1119, 41=586, DDL=414, manifest=16.
- Publication: resolved by user authorization on 2026-10-26 (per-milestone commit + push to `origin/v24`). The closure commit was pushed without force and without bypassing hooks; the pre-existing untracked `docs/**` user inputs were deliberately left out of the commit (the B0 snapshot had 24; the current worktree has 23).
