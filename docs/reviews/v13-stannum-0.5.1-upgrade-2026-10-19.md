# v13 Stannum 0.5.1 Upgrade Evidence

## State

Upgrade implementation and independent 51-item regression PASS. Oracle plan
and implementation review chat `untitled-chat-52843A` plus user authorization
select independent upgrade U before registry Phase 3. Actual commit/push identity
is reported separately; this document does not prefill its own future identity.
Baseline `93d05f12090ce4b27b62b1a6f90d3c1b438eab68`, v99/origin/v99.
Scoped Phase 3 stash `99d334fe90af613605b6e9ec2a7d7c0a3c5abd2d` is retained;
unrelated Stage41 review remains excluded. Original Phase 3 run01 RED remains
historical, not reinterpreted as PASS.

## Environment And Sources

PG 18.4; Python pgembed 0.3.0rc2 editable external fork. Installed/default/
library version observed as Stannum 0.5.1. External Stannum source HEAD
`42d28642748ed2b4b24c712985595218105b2de8` clean, ahead one; external pgembed
HEAD `2ed63ed4be748f7573b2ddae7e71dc722abe149a` has user changes. Neither is
modified. Source HEAD is not proof of installed library build provenance.
Actual backend lsof mapping: `/Users/wxl/Projects/pgembed/src/pgembed/pginstall/lib/postgresql/stannum.dylib`;
SHA-256 `9ca3e369d2f3d50b7bfc2156697c48c5f01c3ecc0fb7833a731866ea4571b0cc`.
pg_proc.probin is `stannum`; dynamic_library_path contains a stale missing
historical isolated prefix then $libdir, and lsof confirms the active library
above. No settings or external files were changed. Capabilities reports
contract_version=1, engine={name:stannum,format:STN3,version:0.5.0},
limits.max_expansion=1024. That engine version is the contract target, not a
misinstalled 0.5.0 library (version()/extversion/default are all 0.5.1).

Upstream 0.4.0/0.5.1 SQL diff preserves existing signatures/ACL and adds only
capabilities (IMMUTABLE STRICT PARALLEL SAFE C INVOKER). 0.5.0->0.5.1 SQL is
no-op; binary fixes missing-AM planner lookup after LOAD. Storage is different:
0.4 LSG requires REINDEX; new STN3 is not downgrade-readable. The upstream
upgrade runbook requires downtime, backup/clean shutdown, restart, ALTER,
non-concurrent REINDEX, verify, rebuilt replicas and restore-only rollback.
This work uses fresh stage databases, not a production migration.

## Implementation And Oracle Disposition

Four version checks use a fixed 0.5.1 constant. V12 uses actual upstream
`contract_version` and `engine.name/format`, correcting Oracle's inaccurate
top-level key suggestion. Contract engine.version remains distinct from
extension/library version. V13 uses actual pg_proc.probin, unique template0
database, LOAD before CREATE, ordinary planning before/after, finally cleanup.
Existing production SQL, queries, index settings and grants stay unchanged.
Any observed compatibility differences must have source plus runtime evidence,
precise replacement assertions and explicit records here, not broad fallbacks.

## Frozen Scope

Shared r0 proof compares all historical v13 bytes. Parity, ports, read_tools
and registry already call it; their local predicates do not reject the three
changed mgraph/characterize paths. Independent stage_bytes comparisons in
plan_arm, workspace_admit, frontier_gap, goal_supervise, goal_supervisor,
fair_claim and fair_driver do reject them and now use a shared exact normalizer.
Only those function bodies change outside plan_arm and the usage gate.

The normalizer accepts only each final complete file's SHA-256, restores fixed
`93d05f1` bytes, and then runs the original historical proof. This uses full-file
digest pins (the repo's existing pattern), stronger than masking literal edit
blocks: every approved byte is required and every additional change rejected.
No historical base or protected path set changes. Diff exclusions happen only
after current hash and restored bytes agree with that diff's original base,
and lstat proves a regular file with the same Git executable mode;
unrelated differences remain visible. Old-or-new acceptance is prohibited.
Four negative cases passed: version regression, out-of-block byte append,
P1 assertion deletion, unrelated SQL mutation; old usage bytes also rejected.
All seven pure stage_bytes entry points passed before full gate execution.

| Exact approved file | SHA-256 |
|---|---|
| mgraph/test_stannum_usage.py | `131af0f54caef6d75e3f18acdddc25d1eb30354f98c2d303a18e949938d6a295` |
| mgraph/README.md | `042b9463421bea29015e1e58f88648c09947d8c56d0aa9c28d861e68d204d251` |
| characterize/README.md | `62be8af89cb16f577960d2356ea4515ab9b26bc28f902c32981970d16365846f` |
| workspace_admit/test_workspace_admit.py | `c61ac64232b10bbf61a37053e0afa2f4a63cfbc9221b3e8589cc531f4e282804` |
| frontier_gap/test_frontier_gap.py | `73f07c2969bbb354ee570c23809260b4443b7cba8d52162d93493f6fa36f9b85` |
| goal_supervise/test_goal_supervise.py | `21dd53695cfc6c38629dd48c777ba55e8518110882706b0cacc4d5c1853a5dfb` |
| goal_supervisor/test_goal_supervisor.py | `ea567128242a5acbc4419afe252bad79256c2fdeab069ec82391ab878855c6fd` |
| fair_claim/test_fair_claim.py | `f0b5d6a0d295d24a27396bae1e4a55df908047b63546af1050d259dc4fa468d2` |
| fair_driver/test_fair_driver.py | `8bbc8381f9ef88d6f5609fd3a18728d1d316ad482756a0f3a60a34fe4148f6c4` |

## Tests

Usage run01 passed V12/V13 and all P probes, then RED at old F5 (expected
single-column rejection, actual success); later cases NOT RUN. Source
storage/mod.rs::envelope_fields/apply_field_weights validates positive finite
weights then forces a single field to 1.0. Run02's F5 proves explicit body:1.0
is accepted with exact reloption, one match and clean verify; F5b/c prove zero
weight and ALTER rejection with exact XX000/messages. Run02 exit 0, 77 checks.
F9 average_length remains 0.0, all six F13 GUC defaults unchanged, jieba stamp
matches, plans and R permission denials unchanged. No broader fallback added.

Injected failures at V13b and V13c separately propagated the original error
and left zero lifecycle databases. Real successful runs also left zero; this
is not a simulated successful lifecycle substituted for the gate.

Targeted run01: characterize exit0/6.81s, mgraph exit0/33.03s, usage exit0/7.04s;
plan_arm exit1/2.10s due its additional dirty comparison. Remaining targeted
items NOT RUN. All four trace restored. Scope investigation above supplied
exact local diff normalization, not a runtime change. Run02 restarts all 16
targeted gates from the beginning; complete51 is independent and still pending.

Targeted run02 completed all 16 serial items. Each command is
`UV_FROZEN=1 uv run python <path>` with the offline PiSwift environment;
logs are `prompt-exports/stannum-051-targeted-run02/NN.log`. Every exit is 0
and every trace was restored (SHA-256 below, mode 0644).

| NN | Path (under v13/) | Seconds | Summary |
|---|---|---|---|
| 01 | characterize/test_characterize.py | 6.86 | ALL PASS |
| 02 | mgraph/test_mgraph.py | 32.51 | ALL GREEN |
| 03 | mgraph/test_stannum_usage.py | 7.07 | 77 checks |
| 04 | plan_arm/test_plan_arm.py | 5.93 | 104 checks |
| 05 | frontier_gap/test_frontier_gap.py | 8.61 | 59 checks |
| 06 | goal_supervise/test_goal_supervise.py | 7.68 | 172 checks |
| 07 | goal_supervisor/test_goal_supervisor.py | 6.31 | 74 checks, fake only |
| 08 | fair_claim/test_fair_claim.py | 5.85 | 137 checks |
| 09 | fair_driver/test_fair_driver.py | 5.64 | 42 checks |
| 10 | loop_driver/test_loop_driver.py | 6.06 | 91 checks |
| 11 | workspace_admit/test_workspace_admit.py | 6.34 | 65 checks |
| 12 | pi_parity/test_pi_parity.py | 18.52 | PiSwift stable; node_modules SKIP |
| 13 | pi_ports/test_pi_ports.py | 45.14 | H1-H6 PASS |
| 14 | read_tools/test_read_tools.py | 474.62 | E4 PASS |
| 15 | registry/test_registry.py | 12.39 | 16/16 groups, 485 checks, zero failures |
| 16 | registry/test_consumer.py | 3.98 | 289 checks |

## Implementation Review

The first review request returned no response after a watchdog failure;
recovery in the same Oracle chat returned one P1 and two P2 findings. All
three were addressed before the independent complete51:

- P1: a content-only whole-path exclusion could hide executable or symlink
  changes. Both diff normalization and r0 proof now require a regular file
  with the historical Git mode. Temporary-file executable/symlink negatives
  passed, alongside the seven pure stage guards and original mutations.
- P2: use BaseExceptionGroup so KeyboardInterrupt plus cleanup RuntimeError
  preserves both exceptions. Fault injection passed and both connections
  closed. This is a cleanup failure test, not a substitute for real V13.
- P2: ledger now records all nine pinned files, not four.

After these fixes, usage and plan_arm were independently rerun, both exit0
(`prompt-exports/stannum-051-review-targeted/{mgraph,plan_arm}.log`). The final
usage digest is the value in the table above. PiSwift verify remained green.
No second implementation review is claimed or required.

Before commit, normal GitHub resolution to 20.205.243.166 repeatedly timed out.
An independent DNS lookup returned 172.182.252.133; a one-command
`http.curloptResolve=github.com:443:172.182.252.133` override fetched successfully
with the original HTTPS hostname/certificate verification and remote URL.
No system DNS or Git configuration was changed. Fetched origin/v99 still equals
the locked baseline (0/0 ahead/behind); push must be verified separately.

Upgrade complete51: PASS with independent label
`stannum-051-upgrade-20261019-run01`. No success is inferred from the original
Phase 3 #1-25 partial sequence. All actual failures and unexecuted remainders
remain retained. Trace baseline SHA-256:
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`.

## Independent Upgrade 51-Item Regression

PASS, 908.70 seconds total recorded item time; 49 exit0, #17 exit1 refusal,
#18 exit2 usage. All 51 valid=true and trace_restored=true. Baseline HEAD
before/after is `93d05f12090ce4b27b62b1a6f90d3c1b438eab68`; the U paths
were dirty/unstaged and Phase3 remained stashed. Final verify passed, both
PiSwift checkouts clean, frozen Sources/manifests unchanged, trace SHA-256
matches above with mode0644. Manual outer #39/#51 summaries confirm 485/289.
Default parity node_modules is SKIP; no provider or all-plane claim.

Commands have prefix `UV_FROZEN=1 uv run python`. Logs are under
`prompt-exports/stannum-051-upgrade-20261019-run01/` named
`NN-<path with slashes replaced by hyphens>.log`. This permanent table
does not depend on retained ignored receipts to interpret the outcomes.

| # | Path / args | Exit / expected | Seconds | Valid / restore | Key output |
|---|---|---|---|---|---|
| 1 | `v13/acl/test_acl.py` | 0 / 0 | 2.61 | T / T | [acl] ALL PASS (197) |
| 2 | `v13/attention/test_attention.py` | 0 / 0 | 2.23 | T / T | [attention] ALL PASS (156) |
| 3 | `v13/catalog/test_catalog.py` | 0 / 0 | 3.66 | T / T | [catalog] ALL PASS |
| 4 | `v13/ce_run/test_ce_run.py` | 0 / 0 | 15.30 | T / T | SUMMARY groups 16 passed 16 failed 0 checks 665 independent_case_failures 0 failures [] |
| 5 | `v13/characterize/test_characterize.py` | 0 / 0 | 6.82 | T / T | ALL PASS |
| 6 | `v13/chunks/test_chunks.py` | 0 / 0 | 9.54 | T / T | ALL PASS |
| 7 | `v13/control/test_control.py` | 0 / 0 | 4.49 | T / T | [PASS] stage 17 gates |
| 8 | `v13/economy/test_economy.py` | 0 / 0 | 9.38 | T / T | ALL PASS |
| 9 | `v13/envelope/test_envelope.py` | 0 / 0 | 8.08 | T / T | [envelope] ALL PASS |
| 10 | `v13/fair_claim/test_fair_claim.py` | 0 / 0 | 5.86 | T / T | [ok] 137 checks |
| 11 | `v13/fair_driver/test_fair_driver.py` | 0 / 0 | 5.43 | T / T | [ok] 42 checks |
| 12 | `v13/fanout/test_fanout.py` | 0 / 0 | 2.32 | T / T | [done] fanout |
| 13 | `v13/filter/test_filter.py` | 0 / 0 | 26.18 | T / T | ALL PASS |
| 14 | `v13/frontier_gap/test_frontier_gap.py` | 0 / 0 | 8.78 | T / T | [ok] 59 checks |
| 15 | `v13/goal_supervise/test_goal_supervise.py` | 0 / 0 | 7.66 | T / T | [ok] 172 checks |
| 16 | `v13/goal_supervisor/test_goal_supervisor.py` | 0 / 0 | 6.25 | T / T | [gate] Fake checks only; unattended authorization remains accept_unattended.py |
| 17 | `v13/goal_supervisor/test_goal_supervisor.py --unattended-continuation` | 1 / 1 | 5.96 | T / T | Expected FAIL unattended_continuation / ask_user |
| 18 | `v13/goal_supervisor/test_goal_supervisor.py bad-args` | 2 / 2 | 0.39 | T / T | Expected usage; no DB setup |
| 19 | `v13/govern/test_govern.py` | 0 / 0 | 2.82 | T / T | [govern] ALL PASS (228) |
| 20 | `v13/handoff/test_handoff.py` | 0 / 0 | 2.25 | T / T | [handoff] ALL PASS (240) |
| 21 | `v13/loop/test_loop.py` | 0 / 0 | 9.74 | T / T | [M3 loop] ALL PASS |
| 22 | `v13/loop_driver/test_loop_driver.py` | 0 / 0 | 5.82 | T / T | [ok] 91 checks |
| 23 | `v13/manifest/test_manifest.py` | 0 / 0 | 7.23 | T / T | [manifest] ALL PASS |
| 24 | `v13/memory/test_memory.py` | 0 / 0 | 7.77 | T / T | ALL PASS |
| 25 | `v13/mgraph/test_mgraph.py` | 0 / 0 | 33.14 | T / T | [mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN |
| 26 | `v13/mgraph/test_stannum_usage.py` | 0 / 0 | 6.98 | T / T | ALL PASS (77) |
| 27 | `v13/mgraph_assembly/test_mgraph_assembly.py` | 0 / 0 | 12.44 | T / T | ALL J GREEN (W1: J1-J3; W2: J4-J7; W3: J8-J9) |
| 28 | `v13/observe/test_observe.py` | 0 / 0 | 1.91 | T / T | [observe] ALL PASS (147) |
| 29 | `v13/periphery/test_periphery.py` | 0 / 0 | 7.15 | T / T | ALL PASS (130 checks) |
| 30 | `v13/pi_parity/test_pi_parity.py` | 0 / 0 | 18.35 | T / T | [SKIP] not_run/toolchain_absent planes=node_modules |
| 31 | `v13/pi_ports/test_pi_ports.py` | 0 / 0 | 45.05 | T / T | [PASS] H6 |
| 32 | `v13/plan_arm/test_plan_arm.py` | 0 / 0 | 5.57 | T / T | [ok] 104 checks |
| 33 | `v13/plan_contract/test_plan_contract.py` | 0 / 0 | 2.06 | T / T | [ok] 93 checks |
| 34 | `v13/plan_read/test_plan_read.py` | 0 / 0 | 2.01 | T / T | [ok] 11 checks |
| 35 | `v13/quota_window/test_quota_window.py` | 0 / 0 | 68.22 | T / T | [quota_window] ALL PASS (226) |
| 36 | `v13/read_tools/test_read_tools.py` | 0 / 0 | 462.33 | T / T | [PASS] E4 |
| 37 | `v13/real_chain/test_real_chain.py` | 0 / 0 | 2.12 | T / T | [ok] 24 checks |
| 38 | `v13/recall/test_recall.py` | 0 / 0 | 9.87 | T / T | ALL PASS |
| 39 | `v13/registry/test_registry.py` | 0 / 0 | 11.48 | T / T | 16/16 groups, 485 checks, zero failures |
| 40 | `v13/resolve/test_resolve.py` | 0 / 0 | 6.37 | T / T | [M2 resolve] ALL PASS |
| 41 | `v13/schema/test_schema.py` | 0 / 0 | 1.34 | T / T | [M1 schema] ALL PASS |
| 42 | `v13/seam/test_seam.py` | 0 / 0 | 5.19 | T / T | [PASS] stage 21 gates |
| 43 | `v13/should_run/test_should_run.py` | 0 / 0 | 2.36 | T / T | [should_run] ALL PASS (194) |
| 44 | `v13/spawn/test_spawn.py` | 0 / 0 | 1.92 | T / T | [PASS] stage 18 gates |
| 45 | `v13/summary/test_summary.py` | 0 / 0 | 12.43 | T / T | ALL PASS |
| 46 | `v13/triage/test_triage.py` | 0 / 0 | 1.93 | T / T | [done] triage |
| 47 | `v13/twophase/test_twophase.py` | 0 / 0 | 6.41 | T / T | [M4 twophase] ALL PASS |
| 48 | `v13/workflow_bind/test_workflow_bind.py` | 0 / 0 | 2.04 | T / T | [ok] 8 checks |
| 49 | `v13/workspace_admit/test_workspace_admit.py` | 0 / 0 | 5.95 | T / T | [ok] 65 checks |
| 50 | `v13/workspace_exec/test_workspace_exec.py` | 0 / 0 | 3.51 | T / T | [ok] 54 checks |
| 51 | `v13/registry/test_consumer.py` | 0 / 0 | 4.00 | T / T | 289 checks |

Upgrade acceptance is PASS. Commit identity and actual push outcome are
reported separately, never prefilled into this commit. Upgrade results do not
substitute either of the two later Phase3 sequences.
