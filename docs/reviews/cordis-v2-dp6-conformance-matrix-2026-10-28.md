# Cordis v2 DP6 Conformance Matrix

B0 (admission audit) executed on 2026-10-28 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `fad3a55800d8ccb9548ec720886e07ad8fcc2c13`. **This matrix now records B0 and W1.** B0 created no DP6 runtime/SQL/test scaffold; W1 then implemented the fair scanner, `ensure`, observer ACL and `CDP6-S` gate. W2–W5 remain unimplemented. The B0 verdict below is preserved as history; the operative W1 status is in §W1 implementation. B0's original capacity verdict was **blocked at admission** (helper tree exactly 5500/5500, no proven semantics-preserving reclaim, 380–560 estimated new helper lines). The user's same-day authorization (`授权无视容量预算要求`) waives the three line-count budgets. The B0 verdict below is preserved as history; W1 semantic admission was subsequently resolved by Oracle (both lanes admitted `ensure` with corrections), and the corrected W1 implementation/CDP6-S evidence is in §W1 implementation. W2–W5 remain unimplemented.

Authority: `docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md` (B0 §3.1–3.4, §4.3.1, §4.4–4.7, §5, §9.1), `docs/designs/cordis-plugin-system-2026-10-25.md` §10.1 (including the 2026-10-28 authorization paragraph), and the user's 2026-10-28 authorization. DP1–DP5 historical Results and artifacts were read only.

## B0 verdict (post-authorization, 2026-10-28)

User authorization, verbatim: **「授权无视容量预算要求」**.

| Scope | Effect |
|---|---|
| DP6 helper total line count (previously 5500) | waived as an admission/gate failure condition; still measured and reported |
| `43_loop.sql` per-file readability line count (previously 700) | waived as an admission/gate failure condition; still measured and reported |
| Domain DDL physical line count (previously 900) | waived as an admission/gate failure condition; still measured and reported |
| `closure<=512`, `successor<=16`, protocol key/depth, ACL, validator/postcondition, replay, transaction-external IO | **unchanged**; all semantic/ACL/file/manifest negative examples still apply. The old line-only probes (5500/5501, 43≤700, DDL≤900) are revoked by the authorization |
| New finite line cap | **none set**; the authorization does not substitute a different number |
| W1 semantic admission | **resolved (W1)** — Oracle group `D2EED4FF-ECCC-44C2-803A-7CA520DFC462` admitted `ensure` with corrections; see §W1 semantic admission, the Oracle design record, and §W1 implementation. Reuse/rollback remains W4-open |

The original blocked-at-admission analysis below is preserved as historical evidence (it is why the authorization was requested and why W1 begins from `R=0`). At B0 the operative result was: capacity admission passes by explicit authorization; B0 baseline + capacity done; W1 semantic admission pending; W1–W5 not started; `ensure`/reuse not implemented. W1 later resolved the semantic admission and implemented `ensure`/the scanner; reuse/rollback remains W4-open.

## Milestone status

| Milestone | Status at B0 |
|---|---|
| B0 | **baseline + capacity done** |
| W1 `CDP6-S` | **complete** (Oracle semantic admission with corrections; corrected `test_scanner.py` and final 36-command serial run) |
| W2 `CDP6-R` | not started |
| W3 `CDP6-U/D` | not started |
| W4 `CDP6-H` | not started |
| W5 `CDP6-B` | not started |

W1 gate `v24/cordis/dp6/test_scanner.py` exists and passed; the remaining four DP6 command names (`test_recovery.py`, `test_dispose.py`, `test_upgrade.py`, `test_boundaries.py`) are still not implemented/not run.

## Environment

| Item | Observed value |
|---|---|
| `pwd -P` | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` |
| branch / upstream | `v24` / `origin/v24` |
| HEAD | `fad3a55800d8ccb9548ec720886e07ad8fcc2c13`, subject `v24: add Cordis DP5 W5 final boundary gate and closeout`, 2026-10-28 20:24:38 +0800 |
| `origin/v24` after `git fetch origin` | `fad3a558...` (same commit), `git rev-list --left-right --count origin/v24...HEAD` = `0 0` |
| `origin/main` after fetch | `4635b4a0471a88c6bac05a7fa4ef83830da1a21b`, subject `v24: finalize fairness release audit`; `origin/main...HEAD` = `4 32` |
| main checkout (read-only check) | `/Users/wxl/Projects/pg-agent`, branch `main`, HEAD `ab34d6972a17f688c4a11adba89e363d74adbe81`, 125 dirty entries; not touched |
| platform | Darwin 25.6.0 arm64, macOS 26.6.2 |
| uv / Python / psycopg2 | 0.8.24 / 3.12.11 / 2.9.12 (dt dec pq3 ext lo64) |
| PostgreSQL | 18.4 (`180004`), printed by `v24/cordis/dp1/setup_db.py --self-check` |
| database fixture | each gate launched its own pgembed server subprocess over a private Unix socket; no external Postgres, no network, no real provider socket |

## Baseline workspace and protection

`git fetch origin` exited 0. Before B0 wrote anything, `git status --porcelain=v1 -uall` had exactly **10 modified tracked paths and 27 untracked paths** (the DP6 plan itself was one of the untracked paths). All 37 paths were SHA-256-hashed to `/tmp/dp6_b0/user_paths_sha256.txt`; immediately after the 35-gate run the status list was byte-identical and every hash matched again (`/tmp/dp6_b0/user_paths_sha256_after.txt`, diff exit 0). No user path was reverted, staged, overwritten or cleaned.

Modified tracked paths (pre-existing user work):

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
M v24/cordis/dp2/README.md
```

The 27 untracked entries are documentation/analysis/design/review files plus `docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md`; the full list and hashes are in the two `/tmp/dp6_b0` manifests. B0 wrote only the four authorized DP6 artifacts listed at the end of this matrix.

## Inherited artifact and gate inventory

DP1–DP5 plans, conformance matrices and stage READMEs all exist at HEAD. The inherited 35-command sequence was taken from `docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md` §"W5 35-command serial regression" and `v24/cordis/dp5/README.md` §"W5 verification", then every referenced file was checked to exist before running. The order preserves the historical `v24/s8` before `v24/s7` inversion; it was not re-sorted.

| Item | Observed |
|---|---|
| `v24/cordis/load.py` manifest | 19 entries, exact canonical order |
| DP1–DP5 stage directories | `dp1`–`dp5` present; 22 `test_*.py` scripts |
| DP5 final gate count | 35 commands |
| DP5 plan/README/matrix/ledger | present, read only |
| DP6 gate scripts | **none exist** (`v24/cordis/dp6/` contained no files before B0) |

Canonical manifest at HEAD:

```text
00_schema.sql, 10_installs.sql, 11_scopes.sql, 12_fibers.sql,
13_episodes.sql, 14_contributions.sql, 15_pins.sql, 16_runs.sql,
17_effects.sql, 18_events.sql, 19_requests.sql, 20_relations.sql,
30_triggers.sql, 40_advance.sql, 41_lifecycle.sql, 42_teardown.sql,
43_loop.sql, 44_events.sql, 50_permissions.sql
```

## Frozen surfaces

The twelve frozen `v24/sql/*.sql` SHA-256 values match the DP5 matrix column exactly; `git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 … v24/s12` exited 0 and `git diff --check` exited 0.

| SQL | SHA-256 |
|---|---|
| `00_schema.sql` | `05b6b47e0f71881e64fba3c55609c16608e4bc15c44f321ad5a87ede7979bc6d` |
| `10_schema.sql` | `a365a235edefe49258038bef4b28a3cd5f8204ab22a71336e892efc706cbae76` |
| `20_triggers.sql` | `1c75ce97c79abdba9151bd8dfd22bb7b1167c10e256ed8fa54d4adf927da5af1` |
| `30_advance.sql` | `087a5bcdb4b9132e25b2d04bc0a31606d429fba5d5cfbb0a257f0a2440715870` |
| `40_interpreters.sql` | `2ebefff558f243891a613787a47ef68dcfb825b1bcc16b78f019e328f982c5f9` |
| `45_capability.sql` | `f629ddd511754a4828da4b4dc4da278c1a4bfcb2359f15f00fd6634f9e4f332e` |
| `46_cleanup.sql` | `bb32336bf6e262f62a55a78d55bf3ac7b649c06a50bdda9eda6263f96ed083ef` |
| `47_verbs.sql` | `5c5bdc611f33f5b37d1652f29aeda97323882487c27cf800ac53371a76ea0265` |
| `48_loop.sql` | `f23a93cdd5c14966442bf30eb1339b6e110c3b1c279b95650704aa9e12870f30` |
| `49_host_reads.sql` | `242748a0fe29cbedc723df9d5de18dd1fba7e9767cfce56a3bc218d1a17ce6c4` |
| `49_recovery.sql` | `b46abde9f5fc4259f9ea833440ca0c0815a4a14a578e058b861f59990d90af8d` |
| `50_permissions.sql` | `578cba9fefc0e0238d6ffd42e458b235bd59ae56a7fa6b1f84a2de36fddbdafe` |

Cordis-line hashes at HEAD (also in `/tmp/dp6_b0/code_sha256.txt`):

```text
40_advance.sql   721965816ac255f05cf2cddc45b035cce82810d341c665b26c8fe6ebf7e11560
41_lifecycle.sql 4b917d3103d4ed2d851554923ef8066740bf656cf8cdc6d6fafcd4ed2d2cf3e5
42_teardown.sql  c983850cd8bba53beba2f8f7c650bce07753b3883f80da26785edd55b3f1731e
43_loop.sql      ac7eeab71001bdcee4a0bd7cdc349a4047ecadeb04dca40b08e0e1301fcc903f
44_events.sql    092736127aa5dac6acdc7f6abfb84ca87b98c02048fd4c0eb115559632770324
load.py          6fb4f62c05cac34420e0e15c11640cbfc18a0e99134f635cdb2dffafebe650c1
helper_budget.py 943a6a3cd63f0feb09f82edf5ca4484b9d6515d01e575034f33b61760e18b11f
50_permissions.sql 5fa11caf3877597b0a109d3c91d6fb09ecf8bbc907aa4634316e1d68fafa6a87
```

## Capacity measurement

Physical lines use `str.splitlines()` — the same count as `v24/cordis/helper_budget.py` and the DP1–DP5 gates. 40–49 were measured in full (not only 40–44). Every 40–49 file present is a helper; there is no 45–49 file in the Cordis line.

The line-count limits in this table are the historical B0 measurements. Under the 2026-10-28 authorization the helper total, 43 per-file and domain-DDL counts are **reported, not enforced**; the non-line rows (manifest 19, tables 10, DEFINER, public EXECUTE, closure/successor) remain enforced.

| Helper module | Physical lines | Note |
|---|---:|---|
| `40_advance.sql` | 1685 | |
| `41_lifecycle.sql` | 1473 | |
| `42_teardown.sql` | 1020 | |
| `43_loop.sql` | 700 | measured; the old 700 per-file cap is waived, still report-only |
| `44_events.sql` | 622 | |
| **40–49 total** | **5500** | |
| **R = 5500 − total** | **0** | historical; no longer an admission condition |

| Item | Measured | Limit | Result |
|---|---:|---:|---|
| Helper total | 5500 | 5500 (historical) | measured/report-only |
| `R` | **0** | >0 and repair reserve (historical) | recorded; capacity admitted by authorization |
| Domain DDL `10`–`17` + `20_relations` + `30_triggers` | **465** | 900 (historical) | measured/report-only |
| Bookkeeping DDL `18_events` + `19_requests` (counted separately) | **22** | (not in domain prefix) | `18`=11, `19`=11 |
| Manifest entries | 19 | 19 | pass |
| Domain tables | 10 | 10 | pass |
| `pg_proc` rows in `v24_cordis` | 170 | (162 helper symbols + 8 trigger guards) | pass |
| Unique `SECURITY DEFINER` | `advance` | `advance` | pass |
| Public EXECUTE functions | 0 | 0 | pass |
| VIEW / materialized view / EXTENSION | 0 / 0 / 0 | 0 | pass |
| Command kinds | 3 (`command_install`, `command_reconcile`, `command_dispose`) | 3 | pass |
| Protocol error codes | 24 in the closed `error_v1` array | 24 | pass |
| Closure / successor bound | 512 / 16 | 512 / 16 | pass |
| `43_loop.sql` per-file cap | 700 | 700 (historical) | measured/report-only |
| `helper_budget.assert_helper_budget` | admits 5500, rejects 5501 at B0 | — | historical; W1 converts to measurement-only |

Independent catalog query (fresh disposable database built through `v24.cordis.dp1.setup_db.TestDB`, not read from a DP5 log):

```text
tables: contributions, effects, episodes, events, fibers, installs, pins, requests, runs, scopes  (10, all relkind='r')
proc_n=170, definers=['advance'], public_execute=[], extensions=[]
admin/service/operator table grants: [] ; function grants: ['advance'] only
schema owner: the fixture owner group; family roles: 4 group roles (+4 login roles created by the fixture)
```

Domain DDL detail: `10`=21, `11`=7, `12`=16, `13`=14, `14`=23, `15`=16, `16`=13, `17`=27, `20`=29, `30`=299 → **465**. Bookkeeping: `18`=11, `19`=11 → **22**.

## B0 serial gates

One `uv run python` process per command, launched only after the previous process exited; no concurrency, no joined commands, no skip. The runner stopped on the first non-zero exit; none occurred. **35/35 exit 0; per-command sum 199.9 s; wall span 201.0 s.** Logs: `/tmp/dp6_b0/gates/gate-01..35.log`; summary: `/tmp/dp6_b0/gates/gates.tsv`. These runs predate the doc-only authorization amendment; no SQL, Python or budget file changed afterwards, and no gate reads `docs/`, so this remains the code baseline for B0 and W1.

| # | Command | Exit | Seconds | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0.6 | canonical loader, 19 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1.8 | PostgreSQL 18.4 / psycopg2 2.9.12 / role-family cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1.6 | CDP1-E exact 19-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 1.8 | CDP1-D; DDL 465 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 14.8 | CDP1-K; helper 5500≤5500, 5500/5501 |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4.3 | CDP2-K continuation/typed delta/closure/replay |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4.5 | CDP2-I declaration/admission |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3.6 | CDP2-A activation/provide bounds |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4.2 | CDP2-B; `tables=10 manifest=19 helpers=5500 ddl=465` |
| 10 | `uv run python v24/load.py` | 0 | 0.6 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1.7 | v24/s1 fixture |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 2.2 | G1-O owner DDL |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2.8 | G1 kernel/commands/claim/locks/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2.0 | S2 W1–W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5.6 | S3 W1–W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4.0 | S4 W1–W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3.3 | S5 W1–W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 3.8 | S6 W1–W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2.4 | S8 G7-A…H + N1–N7 (historical s8-before-s7) |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 6.5 | S7 G6-A…H + N1–N9 + L1–L5 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 10.1 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3.2 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 11.1 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6.4 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 6.0 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 6.9 | CDP3-B1…B13; 5500/5501 |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 7.3 | CDP4-R1…R7 |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 6.1 | CDP4-M1…M5 |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 12.8 | CDP4-T1…T8 |
| 30 | `uv run python v24/cordis/dp4/test_boundaries.py` | 0 | 9.2 | CDP4-X1…X7/M6/e7→e13 |
| 31 | `uv run python v24/cordis/dp4/test_closeout.py` | 0 | 16.1 | CDP4-B1…B6; `helpers=5500 43=700 ddl=465` |
| 32 | `uv run python v24/cordis/dp5/test_resolution.py` | 0 | 9.1 | CDP5-R R1–R8 |
| 33 | `uv run python v24/cordis/dp5/test_listeners.py` | 0 | 5.4 | CDP5-E E1–E7 |
| 34 | `uv run python v24/cordis/dp5/test_dispatch.py` | 0 | 12.6 | CDP5-D D1–D12 |
| 35 | `uv run python v24/cordis/dp5/test_boundaries.py` | 0 | 5.5 | CDP5-B B1–B6 |

Key printed assertions:

```text
[CDP1-K0] helper budget 5500<=5500 {'40_advance.sql': 1685, '41_lifecycle.sql': 1473, '42_teardown.sql': 1020, '43_loop.sql': 700, '44_events.sql': 622}; predicate admits a 5500-line tree and rejects 5501
[CDP2-B4/B5] multi-fiber dispose; tables=10 manifest=19 helpers=5500 40=1685 41=1473 42=1020 43=700 ddl=465
[CDP5-B1] tables=10 manifest=19 definer=advance public_execute=0 views/extensions=0 commands=3 protocol_errors=24
[CDP5-B2] helpers=40=1685 41=1473 42=1020 43=700 44=622 total=5500==5500 ddl=465<=900; 5500/5501 and loader missing/duplicate/order probes refused
[CDP5-B6] twelve frozen v24/sql hashes, frozen 57e2c1e diff and git diff --check hold; 162 private helpers with one DEFINER, no public EXECUTE, pure helpers immutable/token-free; same-LOGIN cache replay and terminal replay-first hold
```

No gate was skipped, no gate was modified, and no failure was rewritten as success. The only `grep -i failure` hits in the logs are assertion prose (e.g. "tool failure", "prepare failure"), not failed gates; no log contains a traceback or non-zero assertion.

## Seam audit for DP6

### `ensure` wake-up ABI — absent

- `v24/cordis/sql/40_advance.sql:292-299` `reconcile_payload_valid` accepts exactly `{fiber_id,action,expected_control_seq}` with `action IN ('on','advance','off','retry')`. There is no `ensure`.
- `v24/cordis/sql/41_lifecycle.sql:1171` re-checks `action NOT IN ('on','off','retry','advance')` in `interpret_reconcile`; `reconcile_command_seed` filters closure members by `action='advance'`.
- The three command kinds are fixed at `17_effects.sql:8`; `advance` is the only DEFINER writer. A scanner cannot insert a successor or write `want_on` directly.
- The closed 24-code `error_v1` set already contains `stale_generation`, so the proposed `detail.reason` values (`ensure_no_work`, `ensure_failure_suppressed`, `ensure_slot_present`) would not require a new error code — but the action token, the zero-write classification, the slot check and the P0 `schedule` reuse would still require 40/41 changes.

### Rollback/reuse install ABI — absent

- `v24/cordis/sql/41_lifecycle.sql:329-347` `install_payload_valid` requires exactly 11 keys and has no `mode`/`reuse` alternative. `10_installs.sql:20` enforces `UNIQUE(scope_id,identity,version)`, so a duplicate old install cannot be created.
- `interpret_install` → `install_admission` → `install_delta` always create one install and one fiber; `validate_install_domain` (`41:582`) hard-requires exactly one `install_create` **and** one `fiber_create` with install fields equal to the payload.
- A `{mode:'reuse', install_id, fiber_id, expected_digest}` path therefore needs a new preflight/admission branch, a fiber-only delta path with `child` contribution/`dispose_child` inverse, a second domain-validator shape and seed updates. None exists at HEAD.

### Scanner actor / observer ACL — absent

- `v24/cordis/sql/50_permissions.sql` handles only `admin`, `service`, `operator`: it revokes all schema/table/function privileges from them and grants only `EXECUTE ON v24_cordis.advance`. The independent catalog query shows **zero table grants** and only `advance` executable for all three.
- There is no observer NOLOGIN group, no observer LOGIN, no column-level SELECT, and no observer `SET ROLE`/principal. `v24/cordis/dp1/setup_db.py` creates only the four existing aliases.
- The repository contains no `scanner`, `sweep` or `recover` function (grep over `v24/cordis/sql` returns nothing). The host driver directory `v24/cordis/dp6/` did not exist before B0.
- Design §4.2's observer column whitelist is therefore a future ACL work package (50_permissions + setup_db fixture), not an existing capability. It is **not** counted against the 5500 helper cap because `50_permissions.sql` is outside 40–49; it is still an unproven SQL/ACL change.

### Dispose / unknown seams — present, reusable

- `42_teardown.sql:833` `dispose_subtree` recursively covers all fibers of an install plus descendant fibers; `dispose_plan` processes `depth DESC` (children before owner), then child installs, then the root; `dispose_delta` emits `fiber_dispose_request`/`fiber_dispose_finish`/`install_dispose_finish` transitions.
- Unknown barriers are real: `p6_plan` returns `blocked_unknown` for an `effect` unknown and for `inverse->>'op'='unknown'` (the schema requires a non-null `debt` for that op); `dispose_plan` blocks `host_io` as `unsupported` and any non-host `unknown` effect as `blocked_unknown`; `dispose_block_kind` maps `unknown` to `blocked_unknown`.
- Terminal effect receipts are immutable: `30_triggers.sql:82-90` raises `55000` on any terminal `outcome`/`attempt`/`fence`/`settled_at` replacement. No private UPDATE bypass exists.
- `host_io` stays `0A000` (unsupported) by design; DP6 must report/block it, not execute it.
- The plan's "shared artifact still referenced by another install is not deleted" item is **not applicable as written**: there is no artifact table, blob store or delete path — `installs.artifact_digest` is only a hex64 text column. B0 records this as N/A rather than claiming a preserved-artifact test, and DP6 adds no artifact subsystem.

## W1 semantic admission (B0 document-level audit, resolved 2026-10-28)

Capacity authorization did **not** admit W1. B0 initially recorded a document-level adjudication only. **B0 verdict: baseline + capacity done; W1 semantic admission pending; W1–W5 not started; `ensure`/reuse were not implemented.**

The pending proof points were then resolved by an Oracle design adjudication (group `D2EED4FF-ECCC-44C2-803A-7CA520DFC462`, two lanes: `codex/gpt-6.1-sol-xhigh` and `openCode/kimi-code-plan-cn/k3.1-pro`). The full design record is `docs/reviews/cordis-v2-dp6-w1-oracle-design-2026-10-28.md`; the exported response is `prompt-exports/oracle-chat-2026-10-28-232411-new-chat-ab0dca-d52e.md` (gitignored). **Verdict: `ensure` admitted with corrections.** The final ordering, exact predicates and validation flow are recorded there and summarised below; B0's withdrawn draft (failure before teardown; every closing/p6 gap → `ensure_no_work`) is not used.

### `ensure` wake-up — envelope compatible; admission resolved with corrections

The command envelope, replay-first, lock/closure, unique-slot and zero-write insertion points are identified. **No `ensure` precedence algorithm is approved by B0.** The earlier draft that checked same-generation failure before teardown, and mapped every `p6`/closing result to `ensure_no_work`, is **withdrawn**: it conflicts with §4.3.1 ("failure cannot block an already-started teardown"; a missing atomic successor in reloading/closing must be an invariant fault, not a no-work claim).

| Requirement | Source fact | Consequence |
|---|---|---|
| exact payload | `reconcile_payload_valid` (`40:292-299`) accepts `{fiber_id,action,expected_control_seq}` and four actions | add `ensure` to the action token only; keys stay exact |
| replay-first | `advance` checks `requests` before payload semantics (`40:1531-1535`); request/effect rows are inserted only in `validate_and_apply_delta` (`40:1214` "No effect/request row exists before this point") | same key/bytes replays; conflicting bytes `request_conflict`; no-op error is not cached |
| non-reserved key | `reserved := request_key LIKE 'cordis/reconcile/%'`; pairing requires reserved iff action=`advance` (`40:1536-1548`) | `cordis/dp6/ensure/...` is non-reserved and passes pairing |
| deterministic effect id | `effect_id_for(principal,key,kind)` (`40:6-9`), principal from `session_user` (`40:1523`) | reconnect actor must be the same LOGIN; see actor section |
| closure/lock | `command_closure` → `reconcile_command_seed`; `advance` locks `lock_closure`, re-discovers and compares (`40:1599-1607`); `lock_closure` is `SELECT … FOR UPDATE` only (`40:254-274`) | extend seed action filters to `ensure`; selector executes after G/closure locks |
| unique slot | `effects_one_reconcile` partial unique index (`17_effects.sql:27`); `reconcile_slot_open` checks ready/claimed (`42:410-414`) | slot presence must be checked under G; exact relation to failure/teardown is unsettled |
| failure suppression | `fibers.failure` exact JSON (`12_fibers.sql:11`); same-generation equality pattern at `42:298`/`42:306`; failure set at `40:1295-1296` | same-generation equality exists, but it **must not preempt an already-started teardown**; exact placement is pending |
| teardown priority | `activation_admission` checks dispose/ancestor seal/retire before owner failure (`41:966-981`); `reconcile_branch` returns `p6` for closing (`42:546`) | teardown must dominate failure; closing handling cannot be reduced to `ensure_no_work` |
| P0 schedule | `p0_delta` mode `schedule` returns empty domain/events and exactly one ordinal-0 `advance` successor (`42:443-466`) | a success path writes only effect+request+successor; no `want_on`/`control_seq` change |
| zero-write errors | `interpret_reconcile`/`reconcile_branch`/`p0_delta` are read-only; error returns before `validate_and_apply_delta` (`40:1658-1684`) | no-work/slot/failure/dispose/stale/closure errors write no table row |
| error ABI | 24-code `error_v1` already contains `stale_generation`, `retry_with_closure`, `dependency_unresolved`, `owner_closing`, `install_not_ready`, `already_terminal` (`40:13-17`) | new only `detail.reason` strings; no new protocol code |

**The two B0 proof points are resolved (Oracle, 2026-10-28):**

1. **failure vs already-started teardown — resolved by ordering.** The final order evaluates structural invariants, generation, slot and terminal state first, then delegates to `reconcile_branch(f,'advance',expected)`. Failure is consulted **only** when the delegated result is `p1`, the sole activation branch. An active non-live fiber returns `leave`; a closing episode returns `p6`; neither reads `fibers.failure`. A same-generation failure can therefore never suppress an already-started teardown. `owner_closing`/`already_terminal` map to zero-write `ensure_no_work`; other errors propagate.
2. **missing atomic successor — resolved by two exact predicates, both before no-work.** (a) `emit` evidence: any succeeded `command_reconcile` parent for the fiber (plus a `command_dispose` parent only when its persisted `install_dispose_progress` event proves this fiber was a `fiber_requested`/`work_scheduled` target in that install subtree) whose committed `requests.response->'emitted'` names a missing effect row; (b) phase evidence: a `reloading` episode with no reconcile slot, or a `closing` episode that already persisted `contributions_released`/`pins_released` for that episode and has no slot. Both raise `0A000 / missing_reconcile_successor`; empty `emitted` and legitimate `successors:[]` leave/close/terminal deltas cannot false-positive. The exact SQL is in the Oracle design record.

Final `ensure` order (after loading `f`/install/current episode): current-episode consistency (including NULL episode + non-NULL `retire_started_at` → `0A000 / phase_drift`); emitted-missing invariant; reloading/closing progress invariant; expected sequence (`stale_generation / reconcile_generation`); open slot (`ensure_slot_present`); disposed (`ensure_no_work`); recursive `advance` classification; `p1` + same-generation failure (`ensure_failure_suppressed`); `p1`/`leave`/`p6` → P0 `schedule` successor. `interpret_reconcile` returns `p0_delta` for the work branch; `validate_domain`'s existing exact `p0_delta` equality is the validator, and apply is the only writer. All no-work/fault paths return or raise before `validate_and_apply_delta`, so they are ten-table zero-write and never cached.

Envelope changes still required (implemented in W1): add the `ensure` action token and preflight, extend `reconcile_command_seed` action filters for contributions/runs/pins (activation-candidate refs stay `advance`-only), and add the early `interpret_reconcile` branch. No command kind, error code, table, column, validator branch or second writer is added.

### Actor reconnect — same real LOGIN, no `SET ROLE`

- `advance` derives `principal := principal_id(session_user)` (`40:1523`); `principal_id` is `md5(login)::uuid` (`40:2-3`), and `effects.request_actor` stores the text login (`17_effects.sql:11`).
- Reserved continuations require `e.request_actor = session_user` and the same principal (`40:339-342`); `role_allowed` requires a real LOGIN in exactly one admin/service/operator group, not superuser (`40:172-190`).
- Therefore the host must reconnect **as the original actor LOGIN** from a trusted credential map keyed by `request_actor`; verify `SELECT session_user` immediately after connect. `SET ROLE` is insufficient (session_user unchanged); `SET SESSION AUTHORIZATION` is host impersonation and is not used.
- Missing/ambiguous credential is an explicit host `blocked_actor_credential` report, with no DB write and no fallback to owner/superuser/observer. The observer login is read-only and cannot call `advance` (see design §4.2 / W1 ACL).
- This is document-level feasible; the credential store and blocked report are W1 host work, not B0.

### Raw-fact pagination predicates (scanner observes only)

Each topic uses its own keyset cursor, `LIMIT $page` (proposal: 64), a short `READ COMMITTED` transaction per page, and no cross-page snapshot or persistent cursor. The scanner never decides live/target/failure; it calls `ensure`/claim/settle and `advance` revalidates.

| Topic | Raw predicate / columns | Order / key | Revalidated by |
|---|---|---|---|
| fiber discovery | `fibers WHERE disposed_at IS NULL`; select `id,install_id,owner_id,owner_episode_id,scope_id,want_on,control_seq,current_episode_id,failure,retire_started_at,dispose_requested_at,disposed_at` | `ORDER BY id`, key `id` | `ensure` → `reconcile_branch`/`activation_admission` |
| ready command continuation | `effects WHERE kind='command_reconcile' AND status='ready'`; select `id,parent_id,ordinal,fiber_id,episode_id,input,request_actor,attempt,fence` | `ORDER BY id`, key `id` | `continuation_state` / `reconcile` |
| ready external effect | `effects WHERE status='ready' AND kind IN ('run_start','model_call','tool_call','listener_call','host_io')`; select `id,fiber_id,episode_id,run_id,kind,input,request_actor` | `ORDER BY id`, key `id` | `claim`/`claim_contract`/`barrier_ready`; `host_io` → unsupported |
| expired claim | `effects WHERE status='claimed' AND lease_until < clock_timestamp()`; select `id,kind,claim_owner,attempt,fence,lease_until,input,request_actor` | `ORDER BY lease_until,id`; key `(lease_until,id)` | `claim`: repeat+concurrent, fence, lease; no local decision |
| dispatch child | `effects WHERE kind='listener_call' AND parent_id IS NOT NULL AND status IN ('ready','claimed')`; parent dispatch by `parent_id`; select `id,parent_id,ordinal,status,fiber_id,episode_id` | `ORDER BY id`, key `id` | `dispatch_progress`/receipt; scanner never claims/settles `dispatch` |
| dispatch parent anomaly | `effects d WHERE d.kind='dispatch' AND d.status IN ('ready','claimed')` plus child count/status summary; all children terminal but parent not sealed → report invariant fault | `ORDER BY d.id`, key `id` | no write; DP5 atomic contract, no new progress engine |
| dispose install | `installs WHERE state='dispose_pending'` plus `effects WHERE kind='command_dispose' AND status IN ('ready','claimed')`; select `id,state,owner_fiber_id,owner_episode_id` | `ORDER BY id`, key `id` | `dispose_plan`/`dispose_delta` |
| dispose fiber | `fibers WHERE dispose_requested_at IS NOT NULL AND disposed_at IS NULL`; select `id,install_id,owner_id,current_episode_id,control_seq` | `ORDER BY id`, key `id` | `dispose_fiber_next`/`p6_plan` |
| unknown effect (debt) | `effects WHERE status='unknown'`; select `id,kind,fiber_id,episode_id,run_id,parent_id,input,outcome` | `ORDER BY id`, key `id` | diagnostic/`blocked_unknown`; no resolution write |
| inverse unknown (debt) | `contributions WHERE released_at IS NULL AND inverse->>'op'='unknown' AND inverse ? 'debt' AND inverse->'debt' <> 'null'::jsonb`; select `id,fiber_id,episode_id,kind,inverse` | `ORDER BY id`, key `id` | `p6_plan`/`dispose_plan` `blocked_unknown` |


The inverse-unknown shape is not inferred: `14_contributions.sql:12-13` requires `inverse` to be an object with string `op` in the closed set and, for `op='unknown'`, a non-null `debt`; fixtures use `{'op':'unknown','debt':{'reason':...,'resource':...}}` (`dp3/test_boundaries.py:187`, `dp3/test_teardown.py:296`).

`deferred`/`blocked_unknown`/unsupported results only update the host report; they do not create rows or block other keys. A page may return fewer than `LIMIT`; wrap to the first key after exhaustion. New low-key rows are visible next wrap because the cursor is not a snapshot.

### Reuse/rollback W4 premise — conditionally closable for non-root only, not proven

- `fibers.install_id` is a plain FK (`20_relations.sql`), so multiple fibers per install are schema-legal; `UNIQUE(scope_id,identity,version)` (`10_installs.sql:20`) is not violated because reuse creates no install row.
- Root reuse is **not closable**: `install_admission` rejects any second owner-null fiber (`unique_root`, `41:463-466`); root rollback must be rejected, not emulated.
- Non-root reuse still needs all of: an alternative exact 4-key payload validator; bypass of the existing-install/existing-fiber/identity conflict checks (`41:453-462`); a fiber-only `install_delta` branch with `child` contribution/`dispose_child` inverse and event; a `validate_install_domain` branch that does **not** require `install_create` (`41:618-639`); seed/lock of old install, scope, owner episode, all same-install fibers and child contributions; and live owner/obligation checks.
- Concrete open ABI point: `command_binding` is `IMMUTABLE` and derives the effect owner from payload `owner` (`41:878-887`). A 4-key reuse payload has no owner, so W4 must choose either a `STABLE` resolver over the old install or validator-resolved owner. That choice, plus the multi-fiber dispose gate, is not proven in B0.
- **Verdict:** no fundamental schema contradiction for non-root reuse, but the W4 design premise is **not closed**; W4 semantic admission pending.

## Original capacity analysis (pre-authorization, preserved)

The measurements and formula in this section produced the original blocked verdict. They remain the baseline evidence — helper 5500, `43=700`, DDL 465, `R=0` — and the three line counts are still reported every milestone. Under the 2026-10-28 authorization they are **not** admission or gate failure conditions, and no replacement cap is set.

Plan §3.3 formula with measured B0 values:

```text
measured helper baseline                            = 5500
− demonstrated semantics-preserving recovered       = 0      (none attempted/proven in B0)
+ DP6 SQL work packages (ensure+reuse+diagnostics)   = 260–440
+ repair reserve                                    = 120
= required capacity                                 = 380–560
≤ authorized cap                                    = 5500
```

| Work package | Where | Low | High | Basis |
|---|---|---:|---:|---|
| `ensure` action: payload token, ensure classification/slot/failure-suppression, P0 `schedule` successor, seed filters | `40`, `41` | 85 | 120 | comparable bodies: `interpret_reconcile` 148, `reconcile_branch` 199 |
| Reuse-declaration rollback: alt payload shape, admission locks/verification, fiber-only delta, domain validator, seed | `41` | 175 | 260 | comparable bodies: `install_admission` 102, `validate_install_domain` 125, `install_delta` 59, `install_command_seed` 42 |
| Optional SQL diagnostic surface (`45_maintenance.sql`) | new 45 | 0 | 60 | avoided by host-side observer SELECT; zero only if diagnostics stay in Python |
| **Repair reserve** (post-gate fixes; the tree has no slack) | `40`–`44` | 120 | 120 | at least one gate-driven fix across two modules; 43 has zero per-file room |
| **Total required helper capacity** | | **380** | **560** | |

Observer ACL (50_permissions + `setup_db.py`) adds roughly 40–70 SQL lines plus fixture code but **0 helper lines** under the current cap definition; it does not rescue the helper budget. DDL has 435 lines of headroom (`465≤900`), so DDL is not the blocker either. `43_loop.sql` is exactly 700/700, so recovery must come from `40`, `41`, `42` or `44`, not from 43.

**Effective remaining capacity:** `R_eff = 5500 − 5500 − 560 = −560` (best case `−380`). There is **no proven semantics-preserving reclaim**, so both bounds are negative. Per B0's rule ("R<0 或没有明确维修余量时，实施阻塞"), the verdict is:

> **Original B0 verdict (pre-authorization, preserved): blocked at admission. W1 was not started. No DP6 SQL/runtime/test scaffold was created.** This verdict is superseded only for the three line-count budgets by the 2026-10-28 user authorization; all semantic boundaries remain.

This was the pre-authorization reasoning. The capacity part is now superseded by the 2026-10-28 authorization (no new cap was set); the ABI part is not a capacity issue and remains open W1/W4 work.

## Historical re-adjudication options (pre-authorization, superseded)

These options were drafted before the 2026-10-28 authorization and are preserved only as the reasoning trail. Option 2 (a higher finite cap) is explicitly **not** adopted: the user authorized ignoring the line-count budgets, and B0 set no replacement number.

1. ~~Authorize a separate DP6.0 semantics-preserving refactor~~ — not required by the authorization; useful only if a later milestone wants to reduce measured lines.
2. ~~Amend the authorized cap to ≥6060~~ — **moot and not done**; no new finite cap is set.
3. **Descope `ensure`/reuse** — still a possible design choice, not taken; both remain planned W1/W4 work.
4. **Reduce optional SQL diagnostics** — still available as an implementation choice; not a capacity blocker.

## W1 atomic budget/gate change list (not executed in B0)

The 2026-10-28 authorization waives only the three line-count ceilings. W1 must land the following changes atomically with the budget/gate update, and must not weaken any file/manifest or semantic assertion. B0 changed none of these files.

| File:line | Current assertion | W1 change (line-count only) | Must remain |
|---|---|---|---|
| `v24/cordis/helper_budget.py:3-12,22` | `LIMIT=5500`; `assert_helper_budget` raises when `total > LIMIT` | keep measuring `total`/`counts`; remove the upper-bound rejection; set no replacement cap | `HELPERS` required-file tuple; missing-file `AssertionError`; per-file counts |
| `v24/cordis/helper_budget.py:37-53` | `prove_helper_budget_boundary` proves 5500 admitted / 5501 rejected | replace with measurement-only proof; use the missing-required-file negative as the surviving predicate proof | required-file rejection; no new numeric cap |
| `v24/cordis/dp1/test_kernel.py:19,548-550` | calls boundary proof; prints `total<=LIMIT` and 5500/5501 | drop boundary proof and cap claim; keep measured print | CDP1-K semantic tests; 19-file manifest |
| `v24/cordis/dp1/test_ddl.py:112` | `assert len(names)==10 and lines<=900` | drop `lines<=900` only | `len(names)==10`; all DDL/trigger semantics |
| `v24/cordis/dp2/test_support.py:19-20,374-377` | wrapper calls boundary proof, then real-tree predicate | stop calling boundary; still return measured counts and enforce required files | required-file behavior; real-tree measurement |
| `v24/cordis/dp2/test_kernel.py:28,1100-1104` | helper cap print + `ddl <= 900` | drop cap print/claim and DDL upper bound | `len(ddl)==10`; CDP2-K semantics |
| `v24/cordis/dp2/test_install.py:21,715-719` | helper cap print + `ddl <= 900` | drop cap claim and DDL upper bound | `len(ddl)==10`; CDP2-I install semantics |
| `v24/cordis/dp2/test_boundaries.py:20,259,263` | `assert_helper_budget` + `prefix <= 900` | keep measurement; drop `prefix<=900` | 19 SQL files; tables=10; definer=1; CDP2-B |
| `v24/cordis/dp3/test_boundaries.py:31-32,77-83,120` | boundary proof; `total<=LIMIT`; `ddl<=900` | drop boundary proof and both upper bounds | `set(counts)==set(HELPERS)`, exact per-file counts, DDL file set; CDP3-B semantics |
| `v24/cordis/dp4/test_closeout.py:24,72-79,109` | boundary proof; `43<=700`; `total<=LIMIT`; `ddl<=900` | drop boundary proof and all three upper bounds | `set(counts)==set(HELPERS)`, exact per-file counts; CDP4-B1…B6 semantics |
| `v24/cordis/dp5/test_boundaries.py:33-35,126-144,196` | boundary proof; `LIMIT==5500`; `total==5500`; `43<=700`; `ddl<=900` | drop boundary proof, exact-cap equality and all three upper bounds; keep measurement print | `counts==measured_helpers()`, missing-44 negative, 19-manifest/duplicate/unregistered/symlink negatives; CDP5-B1…B6 semantics |

Explicitly **not** changed by the authorization:

- 19-entry `CANONICAL_ORDER`, canonical prefix/order, missing/duplicate/unregistered/symlink refusals, required helper-file set.
- 10 domain tables, 3 command kinds, 24 protocol errors, unique `SECURITY DEFINER=advance`, public EXECUTE 0, no VIEW/EXTENSION.
- `closure<=512` (513 rejected), `successor<=16` (17 rejected), protocol 200/201 keys, depth 32/33, ACL matrix, validator/postcondition, replay-first, transaction-external IO.
- No semantic/ACL/file/manifest gate or negative example may be deleted. The **only** permitted removals are the old line-only probes (5500/5501 admit/reject, `43<=700`, `ddl<=900`), explicitly revoked by the 2026-10-28 authorization; replace them with measurement/report assertions. No new finite line cap may be introduced.

## W1 implementation and gate evidence

W1 was implemented from HEAD `78e21500cc716203ae5d978d7e2948aa4bcf66e0` on branch `v24`. The Oracle admission record is `docs/reviews/cordis-v2-dp6-w1-oracle-design-2026-10-28.md`; the exported two-lane response is `prompt-exports/oracle-chat-2026-10-28-232411-new-chat-ab0dca-d52e.md` (gitignored).

### Implemented surfaces

| Surface | Files | Result |
|---|---|---|
| `ensure` action | `40_advance.sql`, `41_lifecycle.sql`, `42_teardown.sql` | exact payload action; non-reserved key; preflight; seed filters extended only for contributions/runs/pins; early interpreter branch; `ensure_branch` + `ensure_emission_missing`; P0 `schedule` delta only |
| fair scanner | `v24/cordis/dp6/driver.py` | 7 independent keyset topics, `LIMIT 64`, short READ COMMITTED page then commit, round-robin with rotated start, page-tail handling and wrap, lossable cursors, actor reconnect/`session_user` verification, `advance` only for writes, external/debt diagnostics only |
| observer ACL | `50_permissions.sql`, `dp1/setup_db.py` | observer NOLOGIN/NOINHERIT group + LOGIN; schema USAGE; column-only SELECT; no table SELECT/DML/function EXECUTE/CREATE/TEMP; `role_family` observes the group, `role_allowed` excludes it; fixture creates/verifies/removes it; TEMP revoked from PUBLIC and re-granted only to the four inherited groups |
| budget/gate conversion | `helper_budget.py`, DP1–DP5 gates | measurement-only helper proof + required-file negative; old 5500/5501, 43≤700 and DDL≤900 asserts removed; measured prints retained; DP5 B6 private-helper/`pg_proc` counts updated 162/170 → 164/172 for the two new helpers |
| W1 gate | `dp6/test_scanner.py` | CDP6-S plus observer ACL, fixture lifecycle, independent-process restart, raw-row replay, real-blocker fairness and transaction discipline |

No command kind, table, column, protocol error code, second scheduler, second writer or validator branch was added. `advance` remains the only DEFINER and the only writer.

### CDP6-S assertions passed

```text
[CDP6-S10] driver source has no direct DML, sleep, socket or thread; only writer call is advance
[CDP6-S7]  observer LOGIN: column-only SELECT; no table SELECT/DML/EXECUTE/TEMP/CREATE;
            single DEFINER, public EXECUTE 0, role_allowed false for observer
[CDP6-S1f] observer LOGIN/group/database created and exactly removed by the fixture
[CDP6-S2]  ensure quiet/stale/work; teardown-before-failure; same-generation failure suppression
[CDP6-S4]  ensure replay-first, conflicting bytes, concurrent unique slot
[CDP6-S3]  reconcile-parent emitted-missing / reloading-no-slot / closing-release /
            retire-without-episode are 0A000 faults with zero write
[CDP6-S3b] command_dispose fiber_requested/work_scheduled missing successors are 0A000 faults
            with zero write; unrelated dispatches do not false-positive
[CDP6-S5a] >page closing fibers; keys inserted before and after the advanced cursor are
            rediscovered within bounded wraps
[CDP6-S5b] >page ready command continuations advanced fairly with no skip
[CDP6-S5c] >page dispose_pending installs converge through the original dispose protocol
[CDP6-S6]  real >512 closure, deferred, blocked_unknown and bad-actor first items do not starve
            same-page healthy commands, other topics or debt diagnostics; repeated quiet passes
            are zero-write and do not tight-loop
[CDP6-S8]  host_io/unknown/expired/ready-external/inverse debt are diagnostics only;
            no handler, no claim, no write
[CDP6-S9]  missing request_actor credential blocked locally; other items still advance
[CDP6-S9b] a real but wrong LOGIN is rejected by session_user verification; the ready effect
            stays unclaimed/zero-write and a correctly-bound sibling advances
[CDP6-S11] provider withdrawal wakes the consumer at unchanged control_seq; repeated quiet
            scans are ten-table zero-growth
[CDP6-S12] duplicate/out-of-order/stale rows revalidate in advance; replay adds no
            request/effect and stale fiber state is zero-write
[CDP6-S13] a separate driver process, a SIGKILLed driver and a third empty-memory process
            rediscover the same canonical DB and converge with no durable cursor
[CDP6-S14] every observer read and advance transaction ends IDLE before close; no residual
            child session or idle-in-transaction
```

### Oracle review of the corrected gate

Oracle group `6B696214-99CB-48A0-BEC6-131CBDE8508F` reviewed the corrected staged diff
(snapshot `2026-10-28/2358`, all.patch + MAP from `repo:v99`): primary `codex/gpt-6.1-sol-xhigh`
(chat `new-chat-7BEF5C`) and additional `openCode/kimi-code-plan-cn/k3.1-pro`
(chat `new-chat-oracle-2-ABB6CD`). Both returned **ACCEPT WITH CORRECTIONS**. The two requested
additions were applied: `[CDP6-S3b]` covers the Oracle-specific `command_dispose`
`fiber_requested`/`work_scheduled` missing-successor predicate with a negative control, and
`[CDP6-S9b]` proves a real but wrong LOGIN is rejected by `session_user` verification while a
correctly-bound sibling advances. The corrected gate passed afterward; no driver or SQL relaxation
was needed.

### 36-command serial gate evidence (2026-10-28)

One `uv run python` process per command, launched only after the previous exited; no concurrency, no joined commands, no skip. The runner stopped on the first non-zero exit; none occurred. **36/36 exit 0; per-command sum 216.5 s; wall ≈217.0 s.** Logs: `/tmp/dp6_w1_final3/gates/gate-01..36.log`; summary `/tmp/dp6_w1_final3/gates.tsv`. The 35 inherited commands retain the B0/DP5 order (including s8-before-s7); `test_scanner.py` is the final W1 gate and contains the corrected coverage plus both Oracle-requested additions.

| # | Command | Exit | Seconds |
|---:|---|---:|---:|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0.5 |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1.6 |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1.6 |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 1.9 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 14.3 |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 3.5 |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4.4 |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3.4 |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 3.7 |
| 10 | `uv run python v24/load.py` | 0 | 0.5 |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1.6 |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 1.6 |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2.5 |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 1.8 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5.2 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 3.8 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3.3 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 3.7 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2.4 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 6.3 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 11.2 |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3.1 |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 10.6 |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6.1 |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 5.9 |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 6.7 |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 7.6 |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 6.3 |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 12.6 |
| 30 | `uv run python v24/cordis/dp4/test_boundaries.py` | 0 | 10.8 |
| 31 | `uv run python v24/cordis/dp4/test_closeout.py` | 0 | 15.6 |
| 32 | `uv run python v24/cordis/dp5/test_resolution.py` | 0 | 8.8 |
| 33 | `uv run python v24/cordis/dp5/test_listeners.py` | 0 | 5.6 |
| 34 | `uv run python v24/cordis/dp5/test_dispatch.py` | 0 | 15.1 |
| 35 | `uv run python v24/cordis/dp5/test_boundaries.py` | 0 | 6.2 |
| 36 | `uv run python v24/cordis/dp6/test_scanner.py` | 0 | 16.7 |

Key printed assertions:

```text
[CDP1-K0] helper lines measured 5600 {40=1685 41=1481 42=1112 43=700 44=622}; no line cap
[CDP2-B4/B5] tables=10 manifest=19 helpers=5600 ... ddl=465
[CDP3-B1] tables=10 manifest=19 helpers=5600 ... ddl=465 ... line counts measured with no cap
[CDP4-B1/B2] tables=10 manifest=19 helpers=5600 43=700 ddl=465 ... no line cap
[CDP5-B2] helpers=... total=5600 ddl=465; line counts measured (no cap), missing-44 negative retained
[CDP5-B6] twelve frozen hashes, frozen 57e2c1e diff and git diff --check hold; 164 private
          helpers with one DEFINER, no public EXECUTE, pure helpers immutable/token-free
[CDP6-S3b] command_dispose fiber_requested/work_scheduled missing successors are 0A000 faults
          with zero write; unrelated dispatches do not false-positive
[CDP6-S6] real >512 closure, deferred, blocked_unknown and bad-actor first items do not starve
          same-page healthy commands, other topics or debt diagnostics
[CDP6-S9b] a real but wrong LOGIN is rejected by session_user verification; the ready effect
          stays unclaimed/zero-write and a correctly-bound sibling advances
[CDP6-S12] duplicate/out-of-order/stale rows revalidate in advance; replay adds no request/effect
[CDP6-S13] a separate driver process, a SIGKILLed driver and a third empty-memory process
          rediscover the same canonical DB and converge with no durable cursor
[CDP6-S14] every observer read and advance transaction ends IDLE before close; no residual session
[passed] CDP6-S
```

### Measured W1 baseline

Physical lines use `str.splitlines()`, the same count as the gates: `40`=1685, `41`=1481, `42`=1112, `43`=700, `44`=622; **40–49 total 5600** (report-only; no replacement cap). Domain DDL `10`–`17`+`20`+`30` = **465**; bookkeeping `18`+`19` = 11+11 = **22** separately. Manifest 19, tables 10, `pg_proc` **172** (164 private helper symbols + 8 trigger guards), unique DEFINER `advance`, public EXECUTE 0, no VIEW/EXTENSION, 3 command kinds, 24 protocol errors, closure 512 / successor 16. `v24/cordis/dp6/test_scanner.py` measures 1311 lines and `driver.py` 326 lines (report-only; no cap). The twelve frozen `v24/sql` SHA-256 values and the `57e2c1e` frozen diff still hold; `git diff --check` exits 0.

### W1 publication and staging

W1 stages only the W1 code and DP6 artifacts: the four SQL files, `helper_budget.py`, the DP1–DP5 gate changes, `dp1/setup_db.py`, `driver.py`, `test_scanner.py`, the DP6 README/matrix/ledger/plan and the Oracle design record. `docs/designs/cordis-plugin-system-2026-10-25.md` remains a mixed file; its pre-existing user 5500 rewrite is **not** staged (the B0 authorization hunk is already in the base commit). Per the parent handoff, this session returns the corrected staged diff for verification and does **not** commit or push; the normal milestone commit/push is performed after that verification. W2–W5 are not started.

## Staging and DP5 handoff

**Mixed-file staging warning.** `docs/designs/cordis-plugin-system-2026-10-25.md` already carries user modifications. Stage only the §10.1 authorization hunk (`git add -p` or an equivalent patch), then inspect `git diff --cached -- docs/designs/cordis-plugin-system-2026-10-25.md`; never `git add` the whole file. The DP6 plan is untracked and contains only the planning file plus the B0 Result/addendum. No commit/push was performed.

**DP5 handoff supersession.** `v24/cordis/dp5/README.md` §“Next action” lists a broader candidate scope. DP6 §2 adjudication replaces it: scanner/fair recovery, receipt/dispatch/run recovery, unknown debt/dispose convergence and drain upgrade/rollback are in; `cancel`/`steer`/`respond`, spawn/child runs, cell/reservation production writers, multi-host, realm ACL, `thisArg` and synchronous disposer chains are **not added**. DP5 README is historical and is not edited.

**Shared artifact gate = N/A.** There is no artifact table, blob store or delete path; `installs.artifact_digest` is a hex64 text column. DP6 does not add an artifact subsystem, so no shared-artifact gate is defined.

## Publication (B0 historical note)

Publication authorized on 2026-10-28 for the current branch **`origin/v24`**, with a normal commit and ordinary push (no force/reset). The earlier AGENTS `origin main` vs `origin/v24` conflict is recorded as historical and is resolved by explicit authorization. W1's corrected staged diff is returned for parent verification before that commit/push; see §W1 publication and staging.

This B0 section publishes only the five DP6 artifacts. `docs/designs/cordis-plugin-system-2026-10-25.md` is a mixed file: only the 2026-10-28 authorization markers/paragraph are staged; its pre-existing user 5500 rewrite remains unstaged. The 35 inherited gates passed earlier; that B0 publication changed docs only. At B0 W1 semantic admission was still pending; it was later resolved and implemented as recorded in §W1 implementation and gate evidence.

## Artifacts written by B0

```text
 M docs/designs/cordis-plugin-system-2026-10-25.md                    (pre-existing user modification; §10.1 authorization paragraph appended)
?? docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md   (pre-existing untracked; B0 Result + authorization addendum appended)
?? docs/reviews/cordis-v2-dp6-conformance-matrix-2026-10-28.md          (this file)
?? docs/reviews/cordis-v2-dp6-deviation-ledger-2026-10-28.md
?? v24/cordis/dp6/README.md                                             (audit artifact; no runtime claim)
```

No DP1–DP5 Result, matrix, ledger, README or SQL was modified; no loader/budget/frozen file was touched; no test scaffold was created. The other 35 pre-existing user paths remain byte-identical.

## Appendix: pre-B0 workspace manifest (SHA-256)

Full `git status --porcelain=v1 -uall` manifest hashed before B0 wrote anything. The design and plan hashes are pre-B0 values: both were intentionally amended by the authorization (`docs/designs/...` §10.1 appended; DP6 plan `Result` + addendum appended). The other 35 paths were rehashed unchanged after the 35 gates and after the B0 artifacts were written. `M` = tracked modification, `??` = untracked.

Post-authorization hashes: committed design blob = `01b6c93b443153ef285f6f1edbbbc9ae3977594d` (HEAD + this authorization hunk only); design worktree blob = `fabc6390d5503d4d5f23439e17210d3ea295176c` (still carries the pre-existing user 5500 rewrite, unstaged); DP6 plan = `ccbd5a57f92d510bbf1b33d48eaabe6057855c9f5d2afc6014694618f6d0432e`. Design changes in the commit: §10.1 historical markers and the authorization paragraph. Plan changes: current normative line-cap clauses updated and `Result` addendum appended.

```text
541ac47f42f097e65c08e33dd8226645ea8378fb9db7c477886a73afd172f764  M docs/designs/cordis-plugin-system-2026-10-25.md
4143d999b3332fc19b7ca109faf555781b4260d72c4ab76c5f1c8f7254ae4e24  M docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md
455d9737ec89dba2fa99ccd9d7a3428ad5db5df7b7b6e8796f1f6127b94d559e  M docs/plans/v24-cordis-dp2-lifecycle-plan-2026-10-26.md
0906e65879fa4b43123b8c0918c2518d1664d3f97daec7e2fb34768ab71a3a70  M docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md
8cffa528e566589af598e05dad948007811e1d93db3fff82f47b03871bf06d68  M docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md
ef844c4d90c6f939fb01ab46ee8da53d3c20547b74b842a71d7e4f5a222eeb00  M docs/reviews/cordis-v2-dp2-conformance-matrix-2026-10-26.md
8b45e164758ab073ed82efd056ca458f869386c760c7bcfbb9adc07e622b5369  M docs/reviews/cordis-v2-dp2-deviation-ledger-2026-10-26.md
a6f79e36e1371423184289c1c3f5c40d52e628415be1b831cd27d82e39b5c242  M docs/reviews/v24-cordis-dp1-foundation-plan-critique-2026-10-25.md
526acb2d14ff0ce1c2505004386165d2c2e43b732fb916734266b2e294155575  M v24/cordis/dp1/README.md
3cef006ab8611dd21935cc2f7ad28a71ad3fec5db87aeb9bd887c142149182ed  M v24/cordis/dp2/README.md
e803a14cf363281536c8b71d94d0220e77882d135e698b3bcaf856fd5c2acbbe  ?? docs/analysis/cordis-v99-vs-zcordis-2026-10-21.md
1fd5a5e38ba9095c7aa19531d5fcec131ab9319d57062573fd107c2c462f4e77  ?? docs/analysis/oracle-eval-brief-2026-10-21.md
06fd5408800fb466fbb7025359e27a45fdc7d2bf26f007abb1a2a6969e7de4b5  ?? docs/designs/cordis-db-plugin-six-verb-report-2026-10-21.md
90714c3f51a5ae5fc54d17fcb92df15e4c8b07ecbb48bfaa5a71b5a24dcce77a  ?? docs/designs/cordis-db-plugin-six-verb-report-plan-2026-10-21.md
e2f8696eba539a60269f46f7cd18a3c2273abe89b24ec51adb11a1ad85db1813  ?? docs/designs/cordis-plugin-core-2026-10-22.md
2d1f92a7ea1d4181b1b5f61dfea707cb50e3a9fd37044a1afdacefd3a7c1c4c3  ?? docs/designs/v13-multilingual-plugin-plane-2026-10-20.md
6d29be1892c9a640cad16dc78d762ba89e467889cadc6bb34c0db14e9b058419  ?? docs/designs/v13-multilingual-plugin-plane-control-annex-2026-10-20.md
b257e03035ace7d40b7a6c9b20e484546de222610d4569a72345d6314c2bdde6  ?? docs/designs/v13-multilingual-plugin-plane-plan-2026-10-20.md
de26831ee6ab09c5f1181189bfc4a7e2f64a7910d170b783e6633d1977f84e44  ?? docs/designs/v99-core-ce-phase0-historical-2026-10-20.md
12cc3b23cf92110c4f8145342c51c5d93bd2b506fe9777f2d7c8c6bdd6da1e9c  ?? docs/designs/v99-core-native-plugin-plane-2026-10-20.md
166d446a0844667642547fbb8c5ceac2c3c97cbf68daee1e542954f96ab69bb8  ?? docs/investigations/sag2-embedding-free-retrieval-survey-2026-10-21.md
aece89fee316456d2e288f73d807f2b4412bc52a9b1f959e9a0a4da1a3b4e908  ?? docs/investigations/v13-duplicate-capabilities-audit-2026-10-20.md
563315871b32bb604b8a31b301ba9a40a33afa0c487cac2e8f9dd90ab4b3b9a0  ?? docs/investigations/v13-harness2-self-improvement-fit-2026-10-20.md
3c2453c8c7b41502dd258939e9620516dc20fc0dfef2971b92689aabcc11de40  ?? docs/investigations/v13-self-improving-multilingual-plugins-feasibility-2026-10-20.md
a58b3ae84133a87d1b6a8e3000ea178ce9ad2b60166ccb0de0977ddfd8a9ea12  ?? docs/investigations/v24-pg-reactive-fit-2026-10-25.md
329729b8bdb025c6eeafbf30c36bb1d9046ab4e56404d21528c3b103c8aafe8d  ?? docs/plans/v13-recursive-harness-self-improvement-plan-2026-10-20.md
864afb4d4236d46cad891d260154305425ecb25821dcabbfe279057ccd764abf  ?? docs/plans/v24-closeout-followup-2026-10-25.md
6df7aa496916e4ac2f426639cead9dec0272bd92e91ca008e48c513c5f9ce3a1  ?? docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md
1cac6904721094afe0bbdf69272e3348d47d4622e41c000ac65d6fdb2e7f5f1e  ?? docs/plans/v99-core-native-plugin-plane-2026-10-20.md
7f88c9332060d79efd0c4e4ca91c31b6de555cdedc13172cab75c76c9b933f70  ?? docs/reviews/v13-registry-stage41-plan-review-2026-10-17.md
0f590551c9984f05a15b966310d7f6f327dd45b3247d5e43f84164e66d6239e5  ?? docs/reviews/v24-closeout-plan-critique-2026-10-25.md
460f711bda8eecf5b32cedf520363ac54db846867c7c5c63f56fb112be5460ca  ?? docs/reviews/v24-cordis-dp2-lifecycle-plan-critique-2026-10-26.md
10c62ab2648dc592afeba588d2e660ce9224117bfda41f99bf765c9ee9448f73  ?? docs/reviews/v24-cordis-dp3-teardown-plan-critique-2026-10-27.md
2192aa857279ee8aec520b4359bba5d5ad7f60fef21df7feb23aa229d141cb08  ?? docs/reviews/v24-cordis-dp4-run-settlement-plan-critique-2026-10-27.md
68a56eed397fb3c5759a7f234a0ea1e838c7b3a28c6ba2a940a50656eb5e1610  ?? docs/reviews/v24-cordis-dp5-events-resolution-plan-critique-2026-10-28.md
b047be95cd539ccac45f3e128fb88a979ecd63abc81314e80341ddc2ce2d4fa4  ?? docs/reviews/v99-core-native-plugin-seam-decisions-2026-10-20.md
7858aa57ccc025a392b2ccc9adc3b9ea24b21109355104c2368fb210d261c60f  ?? docs/reviews/v99-core-phase0-plan-critique-2026-10-20.md
```

## Not covered

- **W1 is implemented and gated.** `ensure`, the fair scanner, the observer ACL/fixture and `CDP6-S` are covered above; `test_scanner.py` passes and the 36-command serial suite is green.
- **W2–W5 are still future milestones.** No external-effect executor, receipt journal/crash recovery, dispatch/run recovery, terminal-unknown resolution, dispose-tree convergence evidence or drain upgrade/rollback is implemented. `test_recovery.py`, `test_dispose.py`, `test_upgrade.py` and `test_boundaries.py` are **not implemented and not run**.
- Reuse-declaration install/rollback is **not** implemented; W4 semantic admission remains pending. The 2026-10-28 capacity authorization does not admit it.
- W1 does not execute external effects; `host_io` remains unsupported/`0A000`, and external/expired/unknown items are diagnostics only. W2 owns claim/receipt/journal and crash injection.
- No real provider socket, no network, no external adapter; all gate DBs were disposable pgembed instances and all handlers were Fake or absent.
- W2–W5 will be handled in later fresh sessions; this W1 publication does not claim them.
