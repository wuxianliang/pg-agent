# Cordis v2 DP4

DP4 delivers the run lifecycle on the DP1/DP2/DP3 Cordis v2 kernel: production `run_start`, model/tool settlement, the restricted `chat_tool` reducer, run pin binding, the step budget, and terminal sealing. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp4-run-settlement-plan-2026-10-27.md`.

## Current status

**B0 is implemented and committed locally. W1–W5 are unstarted.** B0 fixes HEAD `4b34bf2`, registers `sql/43_loop.sql` as the 18th manifest entry, extends the shared helper budget to four files, and records the 26-command pre-DP4 baseline in the DP4 conformance matrix. The 43 module is a behavior-free scaffold.

B0 evidence:

- 26 legacy commands ran serially, each in its own process; all exited 0, total 118 seconds.
- Real helper tree: 40=1373, 41=1211, 42=966, 43=2, sum 3552≤5000. The temporary four-file predicate admits exactly 5000 and rejects 5001.
- DDL prefix 461≤900; manifest 18; 10 tables; only `advance` is `SECURITY DEFINER`; source VIEW/EXTENSION 0.
- The twelve frozen `v24/sql` hashes are unchanged.

No DP4 behavior is claimed at B0: `host_io` and settlement still refuse with `0A000`, `dispatch`/`listener_call` remain unwired, and there is no scanner.

## DP4 gates

- `CDP4-R` — `run_start` production/binding.
- `CDP4-M` — model settlement and reducer.
- `CDP4-T` — tool settlement and batch barrier.
- `CDP4-X` — budget, termination, e7→e13.
- `CDP4-B` — layout, ACL, budget, frozen-surface regression.

## Publication

Per plan §3.10 decision 8, DP4 makes one local commit per milestone and does not push. A push requires the user to name the remote and branch first. `AGENTS.md`'s default `origin main` is not used for this branch.
