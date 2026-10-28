# Cordis v2 DP4 Conformance Matrix

B0 executed on 2026-10-27 in worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch `v24`, HEAD `4b34bf28e83791a7af3356f8036237afca78b67a`. Every exit code in the B0 table is a process exit from a serial run on this worktree; no DP3/DP2 exit is copied as a DP4 result. DP4 production behavior is not implemented at B0.

## Scope

B0 fixes the baseline, registers the 18th manifest module, extends the four-file helper budget, and records the 26 pre-DP4 gates. W1 (`run_start`), W2 (model/reducer), W3 (tool), W4 (seal/budget), and W5 (closeout) are unstarted. `v24/cordis/sql/43_loop.sql` contains only a no-op scaffold.

## Environment

Commands ran from the worktree root. `uv run` resolved the worktree's `.venv`.

| Item | Observed value |
|---|---|
| `pwd -P` | `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` (exit 0) |
| `git rev-parse --show-toplevel` | same path (exit 0) |
| branch / upstream | `v24` / `origin/v24` |
| HEAD | `4b34bf28e83791a7af3356f8036237afca78b67a`, subject `v24: add DP3 W5 boundary gate and closeout` |
| `git fetch origin`; `origin/v24...v24` | exit 0; `0 0` |
| platform | Darwin 25.6.0 arm64, macOS 26.6.2 |
| uv / Python / psycopg2 | 0.8.24 / 3.12.11 / 2.9.12 (dt dec pq3 ext lo64) |
| PostgreSQL | 18.4 (`180004`), printed by the Cordis fixture self-check |
| `.venv` | worktree directory under `v99`, not the main checkout |

Before B0 added artifacts, `git status --porcelain=v1` showed 10 modified tracked paths and 26 untracked paths. They were preserved; none is staged by B0. The pre-existing modifications include user edits to the design, DP1/DP2 plans, DP1/DP2 matrices/ledgers, DP1/DP2 READMEs, and the DP1 critique. DP4 treats the design as read-only.

## Frozen SQL

All twelve `v24/sql/*.sql` SHA-256 values match the DP2/DP3 frozen column:

| SQL | SHA-256 | Matches DP2 matrix |
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

`git diff --exit-code 57e2c1e -- v24/load.py v24/sql v24/s1 ... v24/s12` exited 0 with no output. The run predates the B0 loader edit, so `v24/load.py` was frozen at that moment; B0 then registered `43_loop.sql` as required by its scope. `git diff --check` exited 0.

## Capacity

Physical lines use `str.splitlines()`, the same count as the DP1/DP2/DP3 budget asserts. DDL prefix is `10_installs.sql` through `17_effects.sql`, plus `20_relations.sql` and `30_triggers.sql`.

| Item | Before B0 | After B0 scaffold |
|---|---:|---:|
| `40_advance.sql` | 1373 | 1373 |
| `41_lifecycle.sql` | 1211 | 1211 |
| `42_teardown.sql` | 966 | 966 |
| `43_loop.sql` | absent | 2 (comment + no-op) |
| four-file helper sum | 3550 | **3552≤5000** |
| DDL prefix | 461 | **461≤900** |
| manifest | 17 | **18** |
| tables / `SECURITY DEFINER` | 10 / 1 (`advance`) | 10 / 1 (`advance`) |

DP1-K0 invoked the shared predicate on a temporary four-file tree of exactly 5000 physical lines and on a 5001-line tree; the first returned total 5000 and the second raised `AssertionError`. It then checked the real tree. The no-op line is required because psycopg2 rejects an empty SQL file; it creates no object and has no runtime effect.

## B0 serial gates

Each command below was a separate `uv run python` process, launched after the previous one exited. The runner stopped on the first non-zero exit. This is the final sequence after the 18-entry manifest was registered; all 26 exited 0, total elapsed 118 seconds.

| # | Command | Exit | Evidence |
|---:|---|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | canonical loader and five refusal probes |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | PostgreSQL 18.4, psycopg2 2.9.12, fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | CDP1-E exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | CDP1-D; DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | CDP1-K; helper 3552, 5000 admitted / 5001 rejected |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | CDP2-K continuation/typed delta/closure/replay |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | CDP2-I install declaration/admission |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | CDP2-A activation and provide bounds |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | CDP2-B `tables=10 manifest=18 helpers=3552 ... ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | v24 loader self-check |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | G1-O owner DDL |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | CDP3-B1…B13 |

Order 19 then 20 follows the plan: s8 before s7. No command was concurrent, joined with `;`, or skipped after a failure.

## B0 not covered

- No `run_start`, model/tool settlement, reducer, budget/seal, run writer, or DP4 gate exists yet. CDP4-R/M/T/X/B are not claimed.
- `host_io` and settlement remain `0A000`; `dispatch`/`listener_call` remain unwired; no scanner exists. These are DP3 facts, not DP4 evidence.
- B0 did not push. Publication remains blocked on the user naming a remote/branch (plan §3.10 decision 8).

## W1 / CDP4-R (2026-10-27)

Same worktree and branch `v24`, HEAD `17c855d` (B0) plus W1 changes before staging. The 26 legacy commands and `CDP4-R` were launched one process at a time; all 27 exited 0, total 117 seconds.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 1 | canonical loader, 18 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1 | fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 2 | CDP1-E, exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 2 | CDP1-D, DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 14 | CDP1-K; helper 4040, 5000/5001 proof; service ACL for four effect kinds |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4 | CDP2-K continuation/typed delta/closure |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4 | CDP2-B, manifest 18 |
| 10 | `uv run python v24/load.py` | 0 | 0 | v24 loader |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 2 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 2 | G1-O |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 4 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 4 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 10 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 4 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 10 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 6 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 7 | CDP3-B1…B13; host_io settlement still `0A000` |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 5 | CDP4-R1…R7 |

| W1 invariant | Actual evidence |
|---|---|
| Production run_start | Real install→P0→P1→P2→P4 on a chat_tool agent emits exactly one ordinal-0 `run_start`; a non-chat_tool install emits none. Producer requires `reloading` + activation totality, not `active`. CDP4-R1 |
| Binding | Claim returns frozen `input`; success creates one `runs` row, two run pins, one ordinal-0 `model_call` with three digests, and one `run_progress` step=0 event. CDP4-R2 |
| Replay | Same receipt returns `disposition=replay, emitted=[]` with unchanged ten-table snapshot; different bytes is `receipt_conflict`. CDP4-R3 |
| Forged p4 | Two successors, ordinal 1, extra input key and non-chat_tool each yield `invalid_outcome` with zero write. CDP4-R4 |
| Refusal | Owner-closing success settles without run/pins/successor and emits one `run_refused{owner_closing}`; a `P0401` probe yields `retry_with_closure` and leaves the effect claimed. CDP4-R5 |
| Contract subject | Owner declares only `run_start`; model/tool claims read provider contracts. A tool effect bound to a model pin is `invalid_outcome` zero-write. CDP4-R6 |
| Replay rights | `repeat=false` and `concurrent=false` providers install normally but `run_start` refuses with `replay_right_missing`, no run/pins, one event, replay-consistent. CDP4-R7 |
| Capacity | 40=1546, 41=1211, 42=1000, 43=283, sum **4040≤5000**; DDL 461; manifest 18; 10 tables; one DEFINER |

### W1 not covered

- Model/tool settlement and the reducer are not implemented. A model_call can be claimed but not settled.
- `run_seal`, budget exhaustion, final/model_failed closure, pin release on run terminal, and e7→e13 are W4.
- The source-level run-writer assertion in DP3-B6 was replaced by the W1 production writer; `host_io` settlement remains `0A000` and no scanner exists.
- W1 was committed locally only; no push.

## W2 / CDP4-M (2026-10-27)

Same worktree and branch `v24`, HEAD `e8b6cce` (W1) plus W2 changes before staging. W3-only code (`tool_receipt_valid`, `tool_delta`, the `run_delta` tool dispatch, `tool_body`, `test_loop.py`) was removed from this tree before the run; the pure reducer keeps its complete tool branch. The 26 legacy commands, `CDP4-R` and `CDP4-M` were launched one process at a time; all 28 exited 0, total 121 seconds.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 1 | canonical loader, 18 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 2 | fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1 | CDP1-E, exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 2 | CDP1-D, DDL 461 |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 14 | CDP1-K; helper 4216, 5000/5001 proof; service ACL for four effect kinds |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 3 | CDP2-K continuation/typed delta/closure |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 5 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4 | CDP2-B, `helpers=4216 40=1546 41=1211 42=1000 43=459 ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | 1 | v24 loader |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 2 | G1-O |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 6 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 4 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 10 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 11 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 5 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 7 | CDP3-B1…B13; `host_io` settlement still `0A000` |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 5 | CDP4-R1…R7 regression |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 5 | CDP4-M1…M5 |

| W2 invariant | Actual evidence |
|---|---|
| Model settlement | e8 claim→success spends `3→2`, stores `step=1, phase='tools'`, and freezes `batch=[{ordinal:0,key:'tool',call_id:'c1'}]`. One `tool_call` successor has the model effect as parent, ordinal 0, and exactly `{v,run_id,pin_id,key,descriptor_digest,call_id,args,contract}`. One `run_progress` carries step=1, remaining=2, phase=`tools`. CDP4-M1 |
| Digests | `policy`, `schema` and `toolset` equal `run_digests(run)` byte-for-byte. Tampering any one is `invalid_outcome` with an unchanged ten-table snapshot. CDP4-M2 |
| Schema negatives | Unknown result key, non-null `interaction`, `final` plus tool calls, 17 tool calls, unknown tool key, duplicate `call_id`, negative usage, non-string text: each is `invalid_outcome` and leaves the effect claimed with zero write. CDP4-M3 |
| Reducer purity | `reduce_chat_tool` is `IMMUTABLE`; its recursive `pg_depend` closure contains no `pg_class`. A deliberately reading `BEGIN ATOMIC` probe exposes `pg_class`, proving the detector is live. CDP4-M4 |
| Rollback | Failure injected on the receipt (events insert), the event (effects insert with parent) and the successor (after effects insert with parent) rolls back the whole advance: ten-table plus `requests` snapshot equals pre-call and the model effect remains `claimed`. CDP4-M5 |
| Capacity | 40=1546, 41=1211, 42=1000, 43=459, sum **4216≤5000**; DDL 461; manifest 18; 10 tables; one DEFINER (`advance`) |

### W2 not covered

- Tool receipt, tool settlement, sibling/lease facts, the batch barrier, continuation uniqueness, unknown siblings and tool pin liveness are W3. `test_loop.py` was not run and is not part of W2.
- `run_seal`, final/budget/model_failed terminal closure, pin release and e7→e13 are W4; M6 is deferred with them. In W2 a `close_run` intent returns `invalid_outcome{reason:run_seal_unimplemented}`.
- The frozen-batch decision stands: W2 never shrinks `batch`; the intermediate sibling settlement state is a W3 T1 check.
- W2 was committed locally only; no push.

## W3 / CDP4-T (2026-10-27)

Same worktree and branch `v24`, HEAD `8cbc5f3` (W2) plus W3 changes before staging. The 26 legacy commands, `CDP4-R`, `CDP4-M` and `CDP4-T` were launched one process at a time; all 29 exited 0, total 134 seconds.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 1 | canonical loader, 18 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1 | fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 2 | CDP1-E, exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 2 | CDP1-D, `DDL lines 461` |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 13 | CDP1-K; helper 4266, 5000/5001 proof; service ACL |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4 | CDP2-K continuation/typed delta/closure |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 4 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4 | CDP2-B, `helpers=4266 40=1546 41=1211 42=1000 43=509 ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | 0 | v24 loader |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 2 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 1 | G1-O |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 3 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 6 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 5 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 4 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 3 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 3 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 11 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 11 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 6 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 5 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 7 | CDP3-B1…B13; `tables=10 manifest=18 helpers=4266 ... ddl=461 definer=advance` |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 6 | CDP4-R1…R7 regression |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 5 | CDP4-M1…M5 regression |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 9 | CDP4-T1…T7 |

| W3 invariant | Actual evidence |
|---|---|
| Batch barrier | With two tools, the first settlement returns `emitted=[]`, keeps the frozen two-entry batch and spends budget 3→2. The second returns one `emitted` id and closes the batch (`phase='model'`, `batch=[]`, budget 2→1). The single ready continuation is ordinal 0, parent is the second tool, key `model`, digests equal `run_digests(run)`, pin is the model run pin. Replay returns `replay` with `emitted=[]` and no second continuation. CDP4-T1/T2a |
| Two-connection race | Two threads pass one barrier and settle the two claimed siblings. Exactly one response has `emitted` length 1 and the other zero; the single continuation's parent is the effect from the emitting response; both tools are `succeeded`, batch is empty, budget is 1. CDP4-T2b |
| Expired lease | Both leases are expired before settlement (`bool_and(lease_until < clock_timestamp())`). The first settlement still sees the other `claimed` tool as a live sibling, so it emits nothing and keeps batch entry `c0`; the second emits the continuation. CDP4-T3 |
| Withdrawn pin | A tool contribution is `withdrawn_at IS NOT NULL` while its pin is `released_at IS NULL`; claim and settlement still commit and emit the model continuation. CDP4-T4a |
| Released pin | The pin is released after claim; settlement returns `dependency_unresolved`, the ten-table snapshot is unchanged and the effect remains `claimed`. CDP4-T4b |
| pin/key mismatch | Both directions (model pin with `key='tool'`; tool pin with `key='nope'`) are `invalid_outcome` with an unchanged snapshot and the effect still `ready`. The planner is called as `run_delta`, the single W3 entry point. CDP4-T4c |
| Unknown sibling | The first tool settles `unknown`: status `unknown`, step and budget unchanged, frozen batch retained, no continuation. A third ready tool on the same parent is `blocked_unknown` with zero write. The second sibling's trusted receipt is accepted, spends budget 3→2, leaves `phase='tools'` and the two-entry batch, emits no continuation, leaves the run pin unreleased and the run non-terminal; `p6_plan` returns `blocked_unknown`. CDP4-T5 |
| Tool failure | A `failure` receipt is committed, marks the effect `failed`, closes the batch, increments step and emits one ordinal-0 model continuation. CDP4-T6 |
| Receipt replay | An expired original token still settles once; one continuation exists. Same token with different bytes is `receipt_conflict` with an unchanged snapshot and still one continuation. CDP4-T7a |
| Reclaim | Reclaim advances `attempt` to 2 and `fence` upward; the old token is `stale_claim` with zero write and the effect stays `claimed`; the new token settles and spends budget 2→1. CDP4-T7b |
| Missing replay right | A provider with `repeat=true, concurrent=false` is used through an owner fixture: first claim succeeds, the expired lease cannot be reclaimed (`blocked_unknown`) and the attempt stays 1 with zero write. This is fixture evidence, as B3 anticipates. CDP4-T7c |

### DDL count verification

W1 changed `16_runs.sql` by extending the existing `state` CHECK with `octet_length(state::text)<=65536` on the same physical line (`+1/-1` diff). `test_ddl.py` computes `sum(len(path.read_text().splitlines()) for the 10 prefix files)`; the measured value is **461** and includes the CHECK. The plan's “`16_runs.sql` (+1 行)” describes the predicate, not an added line, so 461 is correct and must not be replaced by 462.

| Capacity | 40=1546, 41=1211, 42=1000, 43=509, sum **4266≤5000**; 43=509≤560 (down from the 555-line pre-merge state); DDL 461; manifest 18; 10 tables; one DEFINER (`advance`) |

### W3 not covered

- `run_seal`, final/budget/model_failed terminal closure, run pin release on terminal and e7→e13 are W4; M6 is tested there.
- CDP4-B layout/ACL/frozen-surface closeout and the full 31-command serial closeout are W5.
- W3 was committed locally only; no push.

## W4 / CDP4-X (2026-10-27)

Same worktree and branch `v24`, HEAD `dbd943d` (W3) plus W4 changes before staging. The 26 legacy commands plus `CDP4-R`, `CDP4-M`, `CDP4-T` and `CDP4-X` were launched one process at a time; all 30 exited 0, total 141.6 seconds.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 1 | canonical loader, 18 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 2 | fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 2 | CDP1-E, exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 2 | CDP1-D, `DDL lines 461` |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 14 | CDP1-K; helper 4317, 5000/5001 proof |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 4 | CDP2-K |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 4 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 4 | CDP2-B, `helpers=4317 40=1546 41=1211 42=1000 43=560 ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | 1 | v24 loader |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 2 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 2 | G1-O |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 3 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 2 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 5 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 4 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 4 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 3 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 7 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 11 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 11 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 7 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 6 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 7 | CDP3-B1…B13; `tables=10 manifest=18 helpers=4317 ... ddl=461 definer=advance` |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 6 | CDP4-R1…R7 regression |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 5 | CDP4-M1…M5 regression |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 10 | CDP4-T1…T7 regression |
| 30 | `uv run python v24/cordis/dp4/test_boundaries.py` | 0 | 7 | CDP4-X1/X1b…X5, M6, e7→e13 |

| W4 invariant | Actual evidence |
|---|---|
| final seal | A model `final` receipt spends 1→0, writes `state.phase='sealed'`, `state.final=true`, `batch=[]`, `result={v:1,reason:'final',output:<model result>,dropped_tool_calls:0}`, emits no successor and releases both run pins in the same advance. The one `run_progress` payload has `sealed=true`, `reason='final'`, step 1, remaining 0, phase sealed. CDP4-X1 |
| Custom model key | A real provider keyed `brain` runs run_start→model→tool→continuation→final. The model effect, tool-to-continuation successor, continuation effect and both run pins carry `brain`; the terminal seal then releases both pins. A forged planner probe rejects a key mismatch and a tool-capability pin with `run_successor`. CDP4-X1b |
| budget_exhausted | Model success with 3 distinct tool calls at `r'=2` seals `budget_exhausted` with `dropped_tool_calls=3`, keeps budget 2 and creates zero tool effects. Tool success at 1→0 seals with dropped 0 and budget 0. CDP4-X2a/X2b |
| model_failed (M6) | A model failure receipt writes `reason='model_failed'`, `output` equal to the receipt `error` object, `dropped_tool_calls=0`, no successor, both run pins released and one `run_progress` with `sealed=true`. CDP4-M6 |
| Terminal paths | Same receipt returns `disposition=replay, emitted=[]` with an unchanged snapshot; different bytes returns `receipt_conflict`; a newly inserted ready model effect on the sealed run claims then settles to `already_terminal` zero-write; direct DML reopen of the terminal effect is `55000`; API claim of the same terminal effect is replay-first `receipt_conflict`. CDP4-X1 |
| Terminal claim deviation | Plan §3.6/X1 says an already-terminal effect re-claim is `55000`. The actual API path is replay-first `receipt_conflict` (the terminal effect has a stored receipt); `55000` is raised only by direct DML reopening the immutable row. W4 records both paths separately and does not claim `advance`-claim `55000`. CDP4-X1 |
| Defensive budget | Forcing `remaining_steps=0` on an open run makes the next model settlement `budget_exceeded` with an unchanged snapshot and the effect still claimed. CDP4-X5 |
| e7→e13 | Real production chain: run_start(3)→model(tool)→tool→continuation with budget 1; retire model provider (contribution withdrawn, pin readable, provider epoch 1), retire agent, e11c and e12 P6 both `deferred` zero-write; the continuation settles `final` on the old pin/epoch, budget 0, run pins released, contribution/epoch unchanged, provider activation pins still live, `run_pin_release_delta` empty, and P6 no longer `deferred/run`. CDP4-X3/X4 |
| Independent validator | A probe replaces `run_delta` with a forged planner and passes deltas that match it: wrong `run_budget`, wrong seal `effect_id`, missing one live pin, a successor with a random `pin_id`, and (X1b) a `brain` continuation whose key or capability is spoofed. `validate_run_domain` rejects them independently as `run_state_delta`, `run_seal_delta`, `run_seal_delta` and `run_successor`. X1b pins the model successor with `pin.key=input.key` plus `descriptor.capability='model_call'`, not the literal `'model'`. CDP4-X6/X1b |
| Capacity | 40=1546, 41=1211, 42=1000, 43=560, sum **4317≤5000**; 43=560≤560; DDL measured 461; manifest 18; 10 tables; one DEFINER (`advance`) |

### DDL count and W5 citation

The DDL count is still **461**: the W1 `state` CHECK is an inline predicate on the existing line. §4.5/B2’s “实测 462” is stale; W5 must cite 461, not 462.

### W4 not covered

- `CDP4-B` layout/ACL/frozen-surface closeout and the full 31-command W5 sequence remain.
- The known W5 test gaps (R4 calling a private function rather than `advance`, R4 missing non-chat_tool/existing-run) are unchanged by W4.
- W4 was committed locally only; no push.

## W5 / CDP4-B (2026-10-27)

Same worktree and branch `v24`, W5 `348b9b8` plus the final acceptance correction. The 26 legacy commands plus `CDP4-R`, `CDP4-M`, `CDP4-T`, `CDP4-X` and `CDP4-B` were launched one process at a time; all 31 exited 0, total 147.0 seconds. Log: `/tmp/dp4-w5-gates-verified.log`.

| # | Command | Exit | Duration (s) | Evidence |
|---:|---|---:|---:|---|
| 1 | `uv run python v24/cordis/load.py` | 0 | 0 | canonical loader, 18 entries |
| 2 | `uv run python v24/cordis/dp1/setup_db.py --self-check` | 0 | 1 | fixture/role/OID cleanup |
| 3 | `uv run python v24/cordis/dp1/test_environment.py` | 0 | 1 | CDP1-E, exact 18-entry manifest |
| 4 | `uv run python v24/cordis/dp1/test_ddl.py` | 0 | 0 | CDP1-D, `DDL lines 461` |
| 5 | `uv run python v24/cordis/dp1/test_kernel.py` | 0 | 22 | CDP1-K; helper 4320, 5000/5001 |
| 6 | `uv run python v24/cordis/dp2/test_kernel.py` | 0 | 3 | CDP2-K |
| 7 | `uv run python v24/cordis/dp2/test_install.py` | 0 | 3 | CDP2-I |
| 8 | `uv run python v24/cordis/dp2/test_activation.py` | 0 | 3 | CDP2-A |
| 9 | `uv run python v24/cordis/dp2/test_boundaries.py` | 0 | 3 | CDP2-B, `helpers=4320 40=1549 41=1211 42=1000 43=560 ddl=461` |
| 10 | `uv run python v24/load.py` | 0 | 0 | v24 loader |
| 11 | `uv run python v24/s1/setup_db.py --self-check` | 0 | 1 | v24/s1 setup |
| 12 | `uv run python v24/s1/test_ddl.py` | 0 | 0 | G1-O |
| 13 | `uv run python v24/s1/test_g1.py` | 0 | 2 | G1 kernel/commands/ACL |
| 14 | `uv run python v24/s2/test_g3a.py` | 0 | 1 | S2 W1-W6 |
| 15 | `uv run python v24/s3/test_g2.py` | 0 | 4 | S3 W1-W7 |
| 16 | `uv run python v24/s4/test_g2b.py` | 0 | 3 | S4 W1-W6 |
| 17 | `uv run python v24/s5/test_g4.py` | 0 | 3 | S5 W1-W4 |
| 18 | `uv run python v24/s6/test_g5.py` | 0 | 3 | S6 W1-W4 |
| 19 | `uv run python v24/s8/test_g7.py` | 0 | 2 | S8 W1-W3 |
| 20 | `uv run python v24/s7/test_g6.py` | 0 | 6 | S7 W1-W2 |
| 21 | `uv run python v24/s9/test_g8.py` | 0 | 10 | G8, 23 cases |
| 22 | `uv run python v24/cordis/dp3/test_protocol.py` | 0 | 3 | CDP3-P |
| 23 | `uv run python v24/cordis/dp3/test_live.py` | 0 | 11 | CDP3-L |
| 24 | `uv run python v24/cordis/dp3/test_teardown.py` | 0 | 7 | CDP3-T |
| 25 | `uv run python v24/cordis/dp3/test_dispose.py` | 0 | 6 | CDP3-D |
| 26 | `uv run python v24/cordis/dp3/test_boundaries.py` | 0 | 6 | CDP3-B1…B13; `tables=10 manifest=18 helpers=4320 ddl=461 definer=advance` |
| 27 | `uv run python v24/cordis/dp4/test_run.py` | 0 | 6 | CDP4-R1…R7 + real-advance R4 |
| 28 | `uv run python v24/cordis/dp4/test_reducer.py` | 0 | 4 | CDP4-M1…M5 + strengthened M4 closure |
| 29 | `uv run python v24/cordis/dp4/test_loop.py` | 0 | 11 | CDP4-T1…T7 + T4b-model/T4c advance |
| 30 | `uv run python v24/cordis/dp4/test_boundaries.py` | 0 | 8 | CDP4-X1…X7/M6/e7→e13; 20 forged run_start negatives + positive refusal |
| 31 | `uv run python v24/cordis/dp4/test_closeout.py` | 0 | 14 | CDP4-B1…B6; B5b seed=97 closure=137 |

| W5 invariant | Actual evidence |
|---|---|
| B1 layout | Ten tables, manifest 18, only `advance` is `SECURITY DEFINER`, public EXECUTE 0, public DML 0, no source VIEW/EXTENSION; all three aliases can execute only `advance`. CDP4-B1 |
| B2 budget | The temporary four-file tree predicate admits exactly 5000 and rejects 5001; real 40=1549, 41=1211, 42=1000, 43=560, sum **4320≤5000**; DDL **461≤900**; 43 **560≤560**. CDP4-B1/B2 |
| B3 ACL | Service claims host_io (settlement is the interpreter's documented `0A000`), and claims/settles run_start/model/tool; admin and operator are `unauthorized` for run_start/model/tool claim and settlement; a real foreign-family LOGIN with explicit schema/EXECUTE grants is `unauthorized`. CDP4-B3 |
| B4 write surface | `runs` is written only in `run_create` (INSERT), `run_state`/`run_budget`/`run_seal` (three UPDATEs); `pins` only in `run_pin_bind` inside the five `ELSIF v_op='run_` branches; the one pins UPDATE is in `pins_release`. `host_io` six effect states are `0A000` (private interpreter for terminal states plus production `advance` for claimed), `dispatch`/`listener_call` are unclaimable, no scanner/sweep/recover function exists, and `run_pin_release_delta` has no DML. A real brain-model run rejects `tool_calls key='brain'` as `invalid_outcome` zero-write. CDP4-B4 |
| B5 limits | Successor 16/17, batch 16/17, run pins 32/33 and closure 512/513 behave as specified; 600 historical effects leave `settlement_seed` and its closure small; host_io seed is exactly `[{t:effects,id:<effect>}]`. CDP4-B5 |
| B5 manifest | `manifest_shape_valid` accepts 256 and rejects 257. The shape-legal 224 unrelated + 32 model/tool production attempt is `retry_with_closure` at activation because each resolved require expands to contribution+fiber+episode (224×3) before the 32 bindings; this is recorded, not claimed as executable. The 288-entry committed_view is an owner-injected fixture created at episode birth, is not a legal manifest (288 requires rejected), and filters to 32 run bindings; a ready run_start effect on that episode gives `settlement_seed=97` and `discover_closure=137` (both non-NULL and <512), proving only the 32 model/tool bindings are expanded. CDP4-B5a/B5b |
| B6 frozen | Twelve `v24/sql` SHA-256 hashes match; `v24/load.py` is unchanged since B0; the twelve DP2-frozen files have no diff from `57e2c1e`; `git diff --check` is clean. CDP4-B6 |
| R4 actual advance | `interpret_command` is replaced and the p4 effect is submitted through `advance` for two, ordinal-1, bad-input, non-chat_tool and existing-run cases; each is `invalid_outcome` with an unchanged ten-table snapshot. CDP4-R4 |
| T4c actual advance | Model-pin/tool-key is rejected at claim; tool-pin/`nope` and tool-pin/`model` are claimed and then rejected by settlement; all zero-write. CDP4-T4c |
| X6/X1b actual advance | `run_delta` is replaced; forged budget/seal/pins/successor and brain key/capability spoofs are submitted through `advance`, rejected independently, with unchanged snapshots. X7 now forges run_start initial state/budget, the pin set (missing/extra/wrong contribution/epoch), model successor run/pin/key/capability/digests/contract/ordinal/uniqueness and empty-domain owner_closing/start_failed/replay_right_missing (20 negatives), all `invalid_outcome` with unchanged snapshots; a legal failure refusal still commits. CDP4-X6/X1b/X7 |
| Tool fact capability | `run_delta.tools` joins contributions and filters `descriptor.capability='tool_call'`; a brain model pin is no longer accepted as a tool key. CDP4-B4 |
| Purity closure | `reduce_chat_tool` closure contains non-catalog `exact_keys/json_int/json_text/model_receipt_valid/tool_receipt_valid`, each with a non-null `prosqlbody`; relation dependency count is 0; a reading BEGIN ATOMIC probe is detected. 40 `exact_keys/json_text/json_int` converted to BEGIN ATOMIC. CDP4-M4 |
| Terminal claim | API claim of a terminal effect is replay-first `receipt_conflict`; direct DML reopen is `55000`. Plan §3.6/§4.4 and the ledger now state this split. CDP4-X1 |

### Oracle review (single pass)

One `mode=review` call covered B0..W5 with a `4b34bf2..working tree` artifact (18 tracked files, +3174/−66) plus the untracked `test_closeout.py` in selection. Direct findings applied: run-settlement domain length/cardinality check; released model pin now `dependency_unresolved` with T4b-model; T4c batch keys isolated; 288 committed_view assembled before episode insert; B2 explicit 5000/5001 proof; plan terminal-claim/DDL 461 correction; model-pin capability/key rules retained; complete run_start independent re-derivation (initial state/budget, pin projection, model successor, empty-domain refusal) now implemented. No new review was run.

**No residual boundary**: the run_start independent re-derivation requested by the single review is implemented in `validate_run_domain` (initial state/remaining budget, the full pin projection from `run_bindings`, the unique model successor's run/pin/key/digests/contract, and the empty-domain refusal reason/receipt/event) and exercised by X7's 20 forged-planner negatives plus a legal `start_failed` positive. 43 is **560≤560**; the checks were paid for by merging duplicated uniqueness scans and duplicated settlement predicates, not by line squeezing or moving functions to another file.

### Capacity and DDL

- 40=1549, 41=1211, 42=1000, 43=560; four-file sum **4320≤5000**.
- DDL prefix **461≤900**; manifest 18; ten tables; one `SECURITY DEFINER` (`advance`).
- The stale “462” references in the plan are corrected to 461; W1's `state` CHECK is an inline change on an existing physical line.

### W5 not covered

- Push target selection; W5 is a local commit only.

### W5 acceptance correction (2026-10-28)

Creation now independently requires the current active/live owner and `run_bindings_valid`; `live_ok IS NOT TRUE` rejects NULL as well as false. X7 adds a real off/closing transition followed by the stale nonempty creation delta: `advance` returns `invalid_outcome` and all ten tables are unchanged. This is negative case 20, in addition to the legal failure-refusal positive. The final 31-command log above replaces the earlier run because SQL changed during that run; `348b9b8` remains in history and the correction is a separate local commit.


## Review fix (2026-10-28)

Oracle review export `prompt-exports/oracle-review-2026-10-28-173620-new-chat-c89fc8-8a3d.md` (primary lane failed on the provider input limit; Oracle 2 completed) identified P1-1/P1-2/P2. The fix is confined to `sql/43_loop.sql` (560 lines) plus the DP4 gates/docs. `run_progress`, `run_seal_result`, and `run_settle_facts` are canonical builders; `validate_run_domain` re-derives and exact-compares the full expected delta (state, event, seal result, successors) instead of only checking fields, and enforces the unknown `{kind}` contract. `run_start` creation also gets the full expected delta comparison.

| Review invariant | Actual evidence |
|---|---|
| P1-1 full state/event/result | X6 event missing/run_id/effect_id/effect_kind/step/remaining/phase/sealed/reason, state origin/step/batch, seal output/reason/dropped, all `invalid_outcome` with `run_state_delta`; X7 run_start event mutations with `run_start_delta`; full expected-delta comparison in `validate_run_domain` |
| P1-2 successors | X6 successor contract version/digest, descriptor digest, args, call_id, key, ordinal; X1b continuation ordinal=0/contract version/digest/digests; all `run_state_delta` zero-write; canonical builder in `run_settle_facts` |
| P2 unknown | T8a/T8b model/tool wrong kind, extra key, non-object, legal unknown; T8c run_start unknown; all zero-write except legal model/tool unknown, which commits with no domain/event/successor |
| Capacity | 40=1549, 41=1211, 42=1000, 43=560, sum **4320≤5000**; DDL **461≤900**; 43 **560≤560**; no line squeezing or file moves; duplicate settlement/event/successor code merged into builders |
| Gates | 31/31 serial independent processes exit 0, 176s, `/tmp/dp4-review-fix-gates-commit-20261028.log` |

External parallel work: during this task the worktree gained uncommitted edits to `41_lifecycle.sql`, `helper_budget.py`, `dp1/test_kernel.py`, `dp2/test_install.py`, `dp2/test_kernel.py`, `dp2/test_support.py`, `dp3/test_boundaries.py`, and `dp4/test_closeout.py`. They are not part of this fix. They were preserved; the 31-gate run temporarily restored them to HEAD to verify the exact commit tree and restored them byte-identically afterwards (SHA-256 compared). The commit stages only the review-fix paths.


## Review-fix readability follow-up (2026-10-28)

The user authorized relaxing the per-file 43 cap. The settlement helpers were split for readability without weakening the exact comparisons; the validator still recomputes from DB/receipt/reducer facts and never calls `run_delta` for expected values.

| Review invariant | Actual evidence |
|---|---|
| Readable independent projections | `run_settle_facts` is facts/intents only; `run_successors` + `run_successor_binding` construct successors; `unknown_body_valid`/`unknown_delta` encode the P2 contract; `run_refused` deduplicates refusal events |
| P2 validator proof | T8a replaces `run_delta` with a function returning the otherwise-valid empty unknown delta; a wrong-kind unknown body is still rejected as `run_unknown` with zero write |
| P1-1 extra forged cases | X6 adds `state_final`, `event_sealed_tools`, `event_missing_tools`, and `successor_extra`; all are `invalid_outcome` with `run_state_delta` and unchanged ten-table snapshots |
| Capacity | 43=592, per-file cap **700**; 40=1549, 41=1211, 42=1000, sum **4352≤5000** (safety line, not a compression target); DDL **461≤900**; 5000/5001 helper-tree boundary |
| Gates | 31/31 serial independent processes exit 0, 201s, `/tmp/dp4-readability-gates-20261028.log` |

External parallel work: the uncommitted `41_lifecycle.sql`, `helper_budget.py`, dp1/dp2/dp3 test, and `dp4/test_closeout.py` edits remain preserved and unstaged. The commit-tree run restored them to HEAD (with the clean `test_closeout.py` cap change) and restored them byte-identically afterwards.
