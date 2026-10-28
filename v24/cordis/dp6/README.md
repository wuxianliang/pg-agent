# Cordis v2 DP6 — B0 audit status (no runtime implemented)

This directory is an **audit artifact only**. As of 2026-10-28 it contains no driver, scanner, SQL, migration, test or gate. DP6 has **not** been implemented, and no DP6 gate exists or has run.

- Plan: `docs/plans/v24-cordis-dp6-recovery-maintenance-plan-2026-10-28.md`
- B0 matrix: `docs/reviews/cordis-v2-dp6-conformance-matrix-2026-10-28.md`
- B0 ledger: `docs/reviews/cordis-v2-dp6-deviation-ledger-2026-10-28.md`
- Authority: `docs/designs/cordis-plugin-system-2026-10-25.md`; DP1–DP5 are the inherited implementation.

## B0 verdict

**B0 baseline + capacity done; W1 semantic admission pending; W1–W5 not started.**

User authorization (2026-10-28), verbatim: **「授权无视容量预算要求」**. It waives only three line-count budgets: the DP6 helper total, the `43_loop.sql` per-file readability count, and the domain-DDL physical count. It does **not** change `closure<=512`, `successor<=16`, protocol key/depth, ACL, validator/postcondition, replay or transaction-external IO, and it sets **no replacement finite cap**. The three counts remain measured and reported every milestone; they are no longer an admission or gate failure condition.

Original capacity arithmetic, preserved as evidence:

```text
measured helper baseline (40–49)                   5500
− demonstrated semantics-preserving reclaim           0
+ DP6 SQL work packages (ensure+reuse+diagnostics)  260–440
+ repair reserve                                    120
= required capacity                                380–560
= original R_eff                             −560 (best −380)
```

The original `blocked at admission` conclusion is preserved in the B0 matrix and plan Result. It is superseded only for the three line counts by the authorization. Capacity waiver does **not** admit W1: see the matrix §“W1 semantic admission”.

## Milestone status

| Milestone | Status |
|---|---|
| B0 | **baseline + capacity done; W1 semantic admission pending** |
| W1 `CDP6-S` | not started |
| W2 `CDP6-R` | not started |
| W3 `CDP6-U/D` | not started |
| W4 `CDP6-H` | not started |
| W5 `CDP6-B` | not started |

## W1 semantic admission — pending, not claimed

Capacity authorization does not admit W1. Document-level findings (details in the B0 matrix):

- **`ensure`**: only the command envelope is compatible. Add the action token, seed filters and an `interpret_reconcile` branch; locks/closure, replay-first, unique slot and zero-write insertion points are identified. **Two semantic points are unproven:** failure must not preempt an already-started teardown, and a reloading/closing fiber missing an atomic successor must be an invariant fault rather than `ensure_no_work`. No replacement order is approved; not implemented or gated.
- **Actor reconnect**: must connect as the original `effects.request_actor` LOGIN via a trusted credential map; verify `session_user`; never `SET ROLE`/`SET SESSION AUTHORIZATION`; missing credential is `blocked_actor_credential`, no fallback.
- **Pagination**: scanner reads raw fact pages per topic (fiber/effect/expired/dispose/unknown/dispatch); all live/target/failure decisions stay in `advance`. Predicate table is in the matrix.
- **Reuse/rollback**: non-root only; root is rejected by `unique_root`. Non-root still needs the 4-key payload, fiber-only delta/validator, seed/lock and a `command_binding` owner-source decision. W4 semantic admission pending.
- No DP6 runtime, SQL, test or gate exists.

## Verified baseline

| Item | Value |
|---|---|
| worktree / branch / HEAD | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` / `v24` / `fad3a55800d8ccb9548ec720886e07ad8fcc2c13` |
| upstream | `origin/v24` = `fad3a55` (`0 0`) |
| helper lines | 40=1685, 41=1473, 42=1020, 43=700, 44=622; **total 5500**; `R=0` (historical; line caps waived, counts still reported) |
| DDL | domain prefix 465 (old 900 cap waived, still reported); bookkeeping 18=11 + 19=11 = 22 separately |
| manifest / tables / functions | 19 / 10 / 170 `pg_proc` (162 helper symbols + 8 trigger guards) |
| privileges | unique `SECURITY DEFINER=advance`, public EXECUTE 0; admin/service/operator have no table grants and only `advance` EXECUTE |
| bounds | closure 512, successors 16, protocol 24 error codes, 3 command kinds |
| frozen | twelve `v24/sql` SHA-256 match; `git diff --exit-code 57e2c1e -- …` exit 0; `git diff --check` exit 0 |
| inherited gates | **35/35 exit 0**, per-command sum 199.9 s, wall 201.0 s; logs `/tmp/dp6_b0/gates/` |

## Known ABI gaps (not implemented)

- **`ensure` does not exist.** `reconcile_payload_valid` accepts only `on/advance/off/retry`; a scanner cannot wake `advance` after losing memory without a protocol change in 40/41.
- **Reuse-declaration install/rollback does not exist.** `install_payload_valid` has 11 exact keys and no `mode:'reuse'`; `UNIQUE(scope_id,identity,version)` prevents duplicating the old install; `install_delta`/`validate_install_domain` require exactly one `install_create` + `fiber_create`.
- **Observer actor does not exist.** No observer NOLOGIN/LOGIN, no column-level SELECT; 50_permissions only manages admin/service/operator and grants only `advance`.
- **No scanner/sweep/recover and no host driver.**
- **Dispose/unknown seams do exist** (`dispose_subtree`, `dispose_plan`, `dispose_delta`, `p6_plan`) and terminal effect receipts are immutable (`30_triggers.sql:82-90`); DP6 must prove a gap before touching them.
- There is no artifact store, so the plan's "shared artifact not deleted" item is N/A rather than implemented.

## Reproduce the B0 measurements (read-only)

Run from this worktree root; do not parallelise the gate scripts because each fixture DROP/CREATEs its own database.

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
git status --porcelain=v1 -uall
shasum -a 256 v24/cordis/sql/4*.sql
git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 v24/s2 v24/s3 v24/s4 v24/s5 v24/s6 v24/s7 v24/s8 v24/s9 v24/s10 v24/s11 v24/s12
```

The 35 inherited commands and their exact order are listed in the B0 matrix and in `docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md` §"W5 35-command serial regression".

## Future DP6 gate index — not implemented, not run

None of these files exists. They must not be reported green:

```text
v24/cordis/dp6/test_scanner.py    # CDP6-S  not implemented / not run
v24/cordis/dp6/test_recovery.py   # CDP6-R  not implemented / not run
v24/cordis/dp6/test_dispose.py    # CDP6-U/D not implemented / not run
v24/cordis/dp6/test_upgrade.py    # CDP6-H  not implemented / not run
v24/cordis/dp6/test_boundaries.py # CDP6-B  not implemented / not run
```

## Current operational guidance

Do not deploy, run or claim a DP6 maintenance loop from this tree. There is no scanner, no `ensure` wake-up and no observer credential. B0 baseline/capacity is done and capacity-admitted by authorization, but W1 semantic admission is **pending** and W1–W5 remain separate milestones. W1 must land the line-count-only budget/gate changes atomically (exact assertion list in the matrix §“W1 atomic budget/gate change list”), keeping the 19-entry manifest/file checks and every semantic negative; `ensure`/reuse ABI audits remain W1/W4 work.

## Handoff boundaries and staging

- **DP5 handoff supersession:** `v24/cordis/dp5/README.md` §“Next action” lists a broader candidate scope. DP6 §2 replaces it: scanner/recovery/unknown/dispose/upgrade are in; `cancel`/`steer`/`respond` are **not added**; spawn/child runs, cell/reservation production writers, multi-host, realm ACL, `thisArg` and synchronous disposer chains are out. DP5 README is historical and was not edited.
- **Shared artifact gate:** N/A. There is no artifact store, blob or delete path, and DP6 adds no artifact subsystem.
- **Mixed-file staging:** `docs/designs/cordis-plugin-system-2026-10-25.md` already contains user changes. Stage only the §10.1 authorization hunk (`git add -p`) and inspect `git diff --cached -- docs/designs/cordis-plugin-system-2026-10-25.md`; never stage the whole file. The DP6 plan is untracked. B0 performed no commit/push.

## Publication

Publication authorized on 2026-10-28 for the current branch **`origin/v24`** via a normal commit and ordinary push. Only the five B0 DP6 artifacts are published; the design file is a mixed file and only its authorization hunk is staged, leaving the pre-existing user 5500 rewrite unstaged. The 35 inherited gates passed earlier; this is a docs-only publication and was not rerun for that reason. W1 semantic admission is still pending and is not claimed by this commit.
