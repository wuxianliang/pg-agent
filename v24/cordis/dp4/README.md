# Cordis v2 DP4

DP4 delivers the run lifecycle on the DP1/DP2/DP3 Cordis v2 kernel: production `run_start`, model/tool settlement, the restricted `chat_tool` reducer, run pin binding, the step budget, and terminal sealing. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp4-run-settlement-plan-2026-10-27.md`.

## Current status

**B0=`17c855d`, W1=`e8b6cce`, W2=`8cbc5f3` and W3=`dbd943d` are committed locally. W4 is implemented and committed locally. W5 is unstarted.** B0 fixes HEAD `4b34bf2`, registers `sql/43_loop.sql` as the 18th manifest entry, extends the shared helper budget to four files, and records the 26-command pre-DP4 baseline in the DP4 conformance matrix. At B0 the 43 module was a behavior-free scaffold; W1 replaces it with the run_start planner primitives.

B0 evidence:

- 26 legacy commands ran serially, each in its own process; all exited 0, total 118 seconds.
- Real helper tree: 40=1373, 41=1211, 42=966, 43=2, sum 3552≤5000. The temporary four-file predicate admits exactly 5000 and rejects 5001.
- DDL prefix 461≤900; manifest 18; 10 tables; only `advance` is `SECURITY DEFINER`; source VIEW/EXTENSION 0.
- The twelve frozen `v24/sql` hashes are unchanged.

W1 adds the production `run_start` path. A real chat_tool P4 emits one ordinal-0 `run_start`; claim returns frozen `input`; success creates the run, run pins, one model_call successor and one run_progress event. Owner-closing, P0401, forged p4 successors, provider capability mismatch and both missing replay rights are zero-write refusal paths. CDP4-R1–R7 pass, and the 27-command W1 sequence (26 legacy + CDP4-R) is green in 117 seconds.

W2 adds model settlement and the restricted `chat_tool` reducer. `CDP4-M1`–`M5` pass: an e8 model success spends 3→2, stores `step=1, phase='tools'` with the frozen batch, and emits one exact ordinal-0 `tool_call` successor; the three digests are compared byte-for-byte and drift in any one is `invalid_outcome` with zero write; schema negatives are zero-write; the reducer is `IMMUTABLE` with no `pg_class` dependency and a reading `BEGIN ATOMIC` probe is detected; receipt/event/successor injection points all roll back with the effect still claimed. The 28-command W2 sequence (26 legacy + CDP4-R + CDP4-M) is green in 121 seconds.

W3 adds tool settlement and the batch barrier. `CDP4-T1`–`T7` pass: N tool settlements emit no continuation until the last sibling closes the batch, then exactly one ordinal-0 `model_call` whose parent is that tool; two connections racing two siblings yield exactly one continuation, observed by the batch closer only; expired leases still count as live siblings; a withdrawn-but-unreleased pin settles the old run while a released pin is `dependency_unresolved` zero-write; an unknown sibling accepts a trusted receipt and charges budget but emits no continuation or seal and keeps the pin, while a new claim and P6 are `blocked_unknown`; failure closes the batch; replay/reclaim follow the provider's repeat/concurrent rights. W3 merges model/tool settlement into the single `run_delta` planner (43=509, 555→509), removing the W2 `model_delta` and W3 `tool_delta` split. The 29-command sequence (26 legacy + CDP4-R/M/T) is green in 134 seconds.

W4 adds terminal sealing. `CDP4-X1`–`X5` and `M6` pass: `final` seals and releases both run pins in one transaction; `budget_exhausted` seals at model N>budget (dropped=N, no partial tool batch) and at tool 1→0; `model_failed` seals with the error object; a completed run's pins are released while provider activation pins remain; P6 is no longer deferred/run. Terminal paths are split: the same receipt replays, different bytes conflict, a new effect on the sealed run is `already_terminal` zero-write, and direct DML reopen of a terminal effect is `55000`. API claim of the original terminal effect is replay-first `receipt_conflict`, not `55000`. A forged-planner probe proves the independent validator rejects wrong budget, seal `effect_id`, missing pin release, and successor key/capability spoofing. The model pin is selected by `descriptor.capability='model_call'` rather than the literal key `'model'`; `CDP4-X1b` carries a real provider key `'brain'` through run_start→model→tool→continuation→final. The e7→e13 walk retires the model provider (contribution withdrawn, pin readable, epoch 1), retires the agent, observes e11c/e12 `deferred` zero-write, then settles the continuation `final` and releases the run pins without re-resolving. W4 also completes the `validate_run_domain` model/tool checks (state step, old-minus-one budget, successor binding, seal `effect_id`, all live run pins). The 30-command sequence (26 legacy + CDP4-R/M/T/X) is green in 141.6 seconds.

W4 capacity: 40=1546, 41=1211, 42=1000, 43=560, sum **4317≤5000**; 43=560≤560; DDL measured 461 (the `state` CHECK is inline); manifest 18; 10 tables; one `SECURITY DEFINER`. W5 closeout remains.

## DP4 gates

- `CDP4-R` — `run_start` production/binding.
- `CDP4-M` — model settlement and reducer.
- `CDP4-T` — tool settlement and batch barrier.
- `CDP4-X` — budget, termination, e7→e13.
- `CDP4-B` — layout, ACL, budget, frozen-surface regression.

## Publication

Per plan §3.10 decision 8, DP4 makes one local commit per milestone and does not push. A push requires the user to name the remote and branch first. `AGENTS.md`'s default `origin main` is not used for this branch.
