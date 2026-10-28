# Cordis v2 DP4 Deviation Ledger

B0 is a baseline/scaffold milestone. Rows below are observations from the 2026-10-27 run in `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` at `4b34bf28e83791a7af3356f8036237afca78b67a`. They do not rewrite DP1/DP2/DP3 history.

| Date | Item | Baseline / spec | DP4 B0 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-27 | Publication | `AGENTS.md` says push `origin main`; DP4 plan §3.10 decision 8 says local commits only until the user names a remote/branch | No commit and no push during B0 evidence collection. This commit is local. `main` is untouched | `git branch --show-current`=`v24`; `origin/v24...v24`=`0 0` before B0 |
| 2026-10-27 | Baseline HEAD | DP4 plan records planning HEAD `4b34bf2` | Revalidated: branch `v24`, HEAD `4b34bf2`, upstream `origin/v24`, `0 0` divergence | `git rev-parse HEAD`; `git fetch origin` |
| 2026-10-27 | Pre-existing work | Milestone isolation: do not stage unrelated files or overwrite user edits | 10 modified tracked docs and 26 untracked paths existed before B0. They remain unstaged; only B0 paths are staged | Baseline `git diff` snapshot in `/tmp/dp4-baseline.diff`; `git status` |
| 2026-10-27 | Empty 43 module | Plan B0 says create an empty `43_loop.sql` | A truly empty file and a comment-only file both fail psycopg2's loader with `can't execute an empty query`. B0 writes one comment plus `DO $scaffold$ BEGIN NULL; END $scaffold$;`. It creates no object. The helper total is therefore 3552, not the projected 3550 | CDP1-K0 `helper budget 3552<=5000`; loader exit 0 |
| 2026-10-27 | Four-file budget proof | Shared predicate must admit exactly 5000 and reject 5001 | `HELPERS` and the temporary tree now include `43_loop.sql`; the proof invokes the predicate on both temporary trees before the real tree | CDP1-K0 and CDP2-B; 5000 admitted / 5001 raised |
| 2026-10-27 | Manifest count | Registering 43 changes the canonical prefix from 17 to 18 | Updated loader and every fixed manifest assertion in DP1-E/CDP1-K/CDP2-B/CDP3-B. No SQL object was added | CDP1-E, CDP1-K, CDP2-B, CDP3-B all exit 0 |
| 2026-10-27 | Design ownership | The design has pre-existing user modifications and is read-only for DP4 | No design edit is part of B0. The baseline diff is preserved rather than reverted | `/tmp/dp4-baseline.diff`; `git status` |
| 2026-10-27 | Frozen v24 SQL | Twelve `v24/sql/*.sql` hashes must not change | All twelve hashes match the DP2 matrix; frozen `57e2c1e` diff exits 0 after B0 because B0 touches only Cordis files | Hash table in the DP4 matrix |

## Final scope

B0 claims only the 26-command pre-DP4 baseline and the 18-entry scaffold. DP4 run settlement, reducer, budget/seal, CDP4-R/M/T/X/B, and all DP5/DP6 surfaces remain unclaimed until their milestones.
