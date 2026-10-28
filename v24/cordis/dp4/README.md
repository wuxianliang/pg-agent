# Cordis v2 DP4

DP4 delivers the run lifecycle on the DP1/DP2/DP3 Cordis v2 kernel: production `run_start`, model/tool settlement, the restricted `chat_tool` reducer, run pin binding, the step budget, and terminal sealing. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp4-run-settlement-plan-2026-10-27.md`.

## Current status

**B0=`17c855d` is committed locally. W1 is implemented and committed locally. W2–W5 are unstarted.** B0 fixes HEAD `4b34bf2`, registers `sql/43_loop.sql` as the 18th manifest entry, extends the shared helper budget to four files, and records the 26-command pre-DP4 baseline in the DP4 conformance matrix. At B0 the 43 module was a behavior-free scaffold; W1 replaces it with the run_start planner primitives.

B0 evidence:

- 26 legacy commands ran serially, each in its own process; all exited 0, total 118 seconds.
- Real helper tree: 40=1373, 41=1211, 42=966, 43=2, sum 3552≤5000. The temporary four-file predicate admits exactly 5000 and rejects 5001.
- DDL prefix 461≤900; manifest 18; 10 tables; only `advance` is `SECURITY DEFINER`; source VIEW/EXTENSION 0.
- The twelve frozen `v24/sql` hashes are unchanged.

W1 adds the production `run_start` path. A real chat_tool P4 emits one ordinal-0 `run_start`; claim returns frozen `input`; success creates the run, run pins, one model_call successor and one run_progress event. Owner-closing, P0401, forged p4 successors, provider capability mismatch and both missing replay rights are zero-write refusal paths. CDP4-R1–R7 pass, and the 27-command W1 sequence (26 legacy + CDP4-R) is green in 117 seconds.

W1 capacity: 40=1546, 41=1211, 42=1000, 43=283, sum **4040≤5000**; DDL 461; manifest 18; 10 tables; one `SECURITY DEFINER`. Model/tool settlement, the reducer, budget/seal and e7→e13 remain W2–W4.

## DP4 gates

- `CDP4-R` — `run_start` production/binding.
- `CDP4-M` — model settlement and reducer.
- `CDP4-T` — tool settlement and batch barrier.
- `CDP4-X` — budget, termination, e7→e13.
- `CDP4-B` — layout, ACL, budget, frozen-surface regression.

## Publication

Per plan §3.10 decision 8, DP4 makes one local commit per milestone and does not push. A push requires the user to name the remote and branch first. `AGENTS.md`'s default `origin main` is not used for this branch.
