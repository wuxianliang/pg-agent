# Cordis v2 DP3 Deviation Ledger

B0 is a baseline and documentation milestone. It changes no production SQL, no test, and no frozen v24 file. Rows below are observations from the 2026-10-27 run in `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` at `9fe6b5b170776907d490fab079fca63cdde6aa28`. They do not rewrite DP2 history in `docs/reviews/cordis-v2-dp2-deviation-ledger-2026-10-26.md`.

| Date | Item | Baseline / spec | DP3 B0 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-27 | Publication | `AGENTS.md` says push `origin main`. DP2's 2026-10-26 authorization was `origin/v24` for that line only. Plan §7 says that authorization does not extend to DP3 | No commit and no push. Pre-existing dirty docs and untracked user files were left unstaged | `git status` after the gates showed the same 10 modified tracked paths as before the run. B0 then edited only its own doc paths |
| 2026-10-27 | Publication authorization | Gate-time status was no commit. `AGENTS.md` still says push `origin main`. DP2's authorization does not extend to DP3 | The user on 2026-10-27 authorized every DP3 milestone to `origin/v24`. This commit publishes B0 only | This commit |
| 2026-10-27 | HEAD versus DP2 W5 | W5's recorded rerun is on `d5fd1bc`. Current HEAD is two commits later: `92f15a3` then `9fe6b5b` | The 21 exits in the DP3 matrix are this HEAD's process results. The `d5fd1bc` exits stay in the DP2 README/ledger as history | `git rev-parse HEAD` and `git log --oneline d5fd1bc..HEAD`. After `git fetch origin`, `origin/v24...v24` is `0 0` |
| 2026-10-27 | Budget gate versus measurement | User revision sets advance plus every private helper module at ≤5000 physical lines. DP1 `test_kernel.py` and DP2 `test_boundaries.py` still assert a single file ≤1200 | Filesystem count with `splitlines()`: 40=1130, 41=1097, 42 absent, sum=2227, DDL prefix=414. CDP2-B printed `advance=1130 ddl=414` and passed its ≤1200/≤900 asserts. The 5000-pass/5001-reject migration was not added or run | Passing old gates are not the new boundary test |
| 2026-10-27 | CDP1-K dispose sentence | W4 basic dispose exists and CDP2-B commits a clean child tombstone | The kernel gate prints a fixed sentence, `off/retry and dispose remain 0A000`, from `test_kernel.py`. B0 quotes that sentence and does not edit the test | Same serial run: CDP1-K exit 0 and CDP2-B exit 0 with `tables=10 manifest=16 advance=1130 ddl=414`. CDP2-B also asserts exactly one `SECURITY DEFINER` before that print |
| 2026-10-27 | View and extension census | Plan §4.2 asks for view/extension 0 | The 16 Cordis SQL files contain no `CREATE VIEW` and no `CREATE EXTENSION`. None of the 21 gates printed a catalog count of views or extensions, so this row is a source scan, not a live catalog probe | Python regex over `v24/cordis/sql/*.sql` |
| 2026-10-27 | Worktree dirtiness | Milestone isolation: do not stage unrelated files | Before B0 artifacts, status had 10 modified tracked docs and 25 untracked paths. Those stayed. B0 adds this ledger, the DP3 matrix, `v24/cordis/dp3/README.md`, the DP1 pointer, and current-state corrections in the DP2 README/matrix/ledger and the DP3 plan | `git status --porcelain=v1 --untracked-files=all` |

## Not claimed

- No DP3 production behavior, no `42_teardown.sql`, and no CDP3 gate.
- No new 5000/5001 budget assertion.
- No claim that the 2026-10-26 DP2 exits were re-used as this run.
- The gate row above records the pre-commit run. This commit publishes B0 to `origin/v24` and does not publish W1.
