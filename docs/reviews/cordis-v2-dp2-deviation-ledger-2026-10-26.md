# Cordis v2 DP2 Deviation Ledger

DP1 history is preserved in `docs/reviews/cordis-v2-dp1-deviation-ledger-2026-10-25.md` and is not rewritten here. This ledger records DP2 implementation choices, protocol extensions, failures and corrections. B0 produced no implementation deviation; its entries record baseline facts and the one unresolved publication question.

| Date | Item | Baseline / spec | DP2 treatment | Rationale and evidence |
|---|---|---|---|---|
| 2026-10-26 | Publication target | Plan §7 and worktree tracking say `v24` / `origin/v24`; root and worktree `AGENTS.md:50-57` say push `origin main` | Resolved by explicit user authorization on 2026-10-26: each milestone commits and then pushes to `origin/v24`. B0 was closed with one commit containing only the four DP2 artifact paths; no branch switch, no history rewrite, no force | Publishing is a user authorization, not an engineering choice. The authorization is task-specific for this DP2 line and does not rewrite the `AGENTS.md` `origin main` rule or the main checkout's branch binding. |
| 2026-10-26 | Worktree AGENTS.md content | Main checkout `AGENTS.md` allows two real-socket entry points | The `v99` worktree copy additionally lists `v24/host/smoke.py --real-provider-smoke` as a third entry | Environment fact only; no gate opened a socket. Recorded so later milestones do not mistake the two copies for one file. |
| 2026-10-26 | Frozen hash count naming | DP1 W4 closeout text says "explicit nine frozen SQL diff" while listing twelve hashes; DP2 plan §3.14 says twelve files | B0 records twelve SHA-256 values as the authoritative frozen set and verifies all twelve | The plan's twelve-file requirement is the stricter reading; all twelve matched DP1 P0 byte-for-byte. |
| 2026-10-26 | Gate durations | DP1 matrix recorded per-command seconds | B0 records exit codes and printed named assertions, no durations | Timings are not required B0 evidence; the exit code plus the printed named assertions are the record for each command. |
| 2026-10-26 | Untracked working-tree files | `AGENTS.md` forbids `git add -A` / `git add .` | the 24 pre-existing untracked `docs/**` user inputs were left unstaged and unmodified; no unrelated file entered B0 scope | Milestone isolation; B0 only creates/updates the four DP2 artifacts named by the plan. |
| 2026-10-26 | Python version | DP1 README records Python 3.12.11 | Re-verified via `uv run python --version` and `import psycopg2`: 3.12.11 / 2.9.12 / PG 18.4 (180004) | Current-run evidence, not copied from DP1 history. |

## B0 scope boundary

- No production implementation was written: `v24/cordis/sql/**`, `v24/load.py`, `v24/sql/**` and `v24/s1`–`v24/s12` are untouched, and the twelve frozen hashes plus the `57e2c1e` diff prove it.
- No DP2 gate script, helper, table, column, enum, extension or SQL file was created. `v24/cordis/dp2/` contains only this stage's README.
- All eleven v24 commands, the separate s9 gate and the five Cordis DP1 commands exited 0 when executed serially during this B0 verification. No gate was weakened, skipped, or run concurrently.
- DP2 named assertions CDP2-K/I/A/B are unimplemented and unrun; no DP2 lifecycle behavior is claimed.

## Milestone status

B0 local verification and its four artifacts are complete, and the milestone is **closed**: the user authorized per-milestone commit + push to `origin/v24`, and B0 was committed (closure commit `v24: close out Cordis DP2 B0 baseline with gate and frozen evidence`) and pushed without force or hook bypass. The repository rule that each milestone must be pushed before the next one starts still applies to W1–W5, which remain unstarted.

## Open

- Publication target (see first row). Until the user chooses `origin/v24` or `origin main`, every subsequent milestone is likewise blocked at commit/push, because the repo rule requires each milestone to be pushed before the next one starts.
