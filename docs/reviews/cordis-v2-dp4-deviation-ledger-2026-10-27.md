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

## W1 observations (2026-10-27)

Same worktree, B0 `17c855d` plus W1 changes. The 27-command sequence (26 legacy + CDP4-R) is green; this section does not rewrite B0.

| Date | Item | Plan / baseline | W1 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-27 | Batch semantics | §3.5 called `batch` both the original frozen list and a list with the current tool removed; `p_fact` has no current ordinal/key/call_id | Resolved to **frozen original batch**. The reducer only uses `live_siblings`; a continuation clears `batch`, sealing requires `batch=[]`, and an unknown wall keeps the frozen list. No current-tool fact is smuggled into the reducer | Plan §3.5 amended; `reduce_chat_tool` contract; W3 will test the intermediate state |
| 2026-10-27 | Claim read channel | Protocol roles have no table SELECT; service needs prompt/args | Success claim responses now include frozen top-level `input`. DP1-K exact-key assertion was updated. This is the only read channel; no table grant was added | CDP4-R2/R6; DP1-K2 |
| 2026-10-27 | P4 phase | Plan/critique split producer liveness from settlement | Producer requires current episode `reloading` plus activation totality; settlement requires current active episode plus `fiber_live_resolve_ok`. `P0401` is caught and returned as `retry_with_closure` | CDP4-R1/R5 |
| 2026-10-27 | Owner contract ownership | Critique: owner must not declare model/tool contracts | Agent install declares only `run_start`; model/tool contracts are read through each run pin's provider install. A capability mismatch is `invalid_outcome` | CDP4-R6 |
| 2026-10-27 | Refusal response reason | Plan says owner-closing refusal returns the reason | `validate_and_apply_delta` adds `reason` only when the one event is `run_refused`; normal responses keep the original five keys | CDP4-R5/R7 |
| 2026-10-27 | DP1 ACL assertion | Old gate asserted service unauthorized for model/tool/run_start | Replaced with service admitted for `host_io/run_start/model_call/tool_call` claim/settle; admin/operator still unauthorized. Claim response now includes `input` | DP1-K1/K2 |
| 2026-10-27 | DP3 B6 writer assertion | Old gate asserted no source `INSERT/UPDATE runs` and settlement `0A000` | Host-io settlement remains `0A000`; source run DML now exists behind typed ops, so the assertion checks presence and keeps scanner/recovery absence plus read-only `run_pin_release_delta` | CDP3-B6 |
| 2026-10-27 | Capacity | Projected W1 43 ≤560, total ≤5000 | Actual 40=1546, 41=1211, 42=1000, 43=283, sum 4040≤5000; DDL 461 | CDP1-K0/CDP2-B/CDP3-B |
| 2026-10-27 | Publication | Local commits only until target confirmed | W1 committed locally; no push and `main` untouched | W1 commit |

### W1 not covered

Model/tool settlement, reducer, `run_seal`, budget exhaustion, final/model_failed terminal states, run pin release on terminal, and e7→e13 remain unimplemented.

## W2 observations (2026-10-27)

Same worktree, W1 `e8b6cce` plus W2 changes. The 28-command sequence (26 legacy + CDP4-R + CDP4-M) is green; this section does not rewrite B0/W1.

| Date | Item | Plan / baseline | W2 treatment | Evidence |
|---|---|---|---|---|
| 2026-10-27 | W2/W3 boundary repair | Plan W2 includes the complete pure reducer; W3 owns tool receipt/settlement | `tool_receipt_valid`, `tool_delta`, the `run_delta` tool dispatch, `tool_body` and `test_loop.py` were removed before the W2 gate run. The reducer keeps its complete tool branch. Full W3 work is preserved in `/tmp/dp4-w3-backup-20261028-151753` with SHA-256; W2 tree has 43=459, restoring W3 yields 554≤560 | W2 43 function list; CDP4-M; backup `SHA256SUMS` |
| 2026-10-27 | 40/42 plumbing already committed | Plan lists 40/42 as W2 key files | W1's commit had already landed the generic run plumbing (`run_state`/`run_budget` ops and appliers, model/tool successor exact-shape checks, ACL, claim `input`). W2 needed no 40/42 edit and does not re-claim it; W2 adds the 43 interpreter/reducer, support helpers and test | `git show e8b6cce -- v24/cordis/sql/40_advance.sql v24/cordis/sql/42_teardown.sql`; W2 `git diff --stat` |
| 2026-10-27 | Extra `model_delta` planner | §3.2 describes one `run_delta` planner with three branches | Implementation dispatches `model_call` to a private `model_delta` (and W3 will add `tool_delta`) from `run_delta`. No table, writer, kind or public surface is added; behavior is identical and 43 stays 459 (W2) / 554 (W3) ≤560 | 43 function list; CDP4-M1/M5 |
| 2026-10-27 | Close intents deferred | M6 and sealing are W4 | `final`, `budget_exhausted` and `model_failed` intents return `invalid_outcome{reason:run_seal_unimplemented}` in W2. The reducer already produces the closed intent; W4 wires `run_seal`/pin release | CDP4-M does not claim M6; plan W4 |
| 2026-10-27 | Frozen batch | §3.5 batch is the original frozen list; `p_fact` has no current item | W2 M1 asserts the full one-element batch and never shrinks it. The intermediate sibling state remains W3 T1; W1's ledger row owns the semantic decision | CDP4-M1 |
| 2026-10-27 | Capacity | Four-file sum ≤5000, 43 ≤560 | W2 actual 40=1546, 41=1211, 42=1000, 43=459, sum **4216≤5000**; DDL 461; manifest 18; 10 tables; one DEFINER | CDP1-K0, CDP2-B |
| 2026-10-27 | Publication | Local commits only until target confirmed | W2 committed locally; no push and `main` untouched | W2 commit |

### W2 not covered

Tool receipt/settlement/barrier and continuation (W3); `run_seal`, terminal closure, pin release and e7→e13 (W4); closeout gates and CDP4-B (W5).
