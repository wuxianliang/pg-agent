# v13 Registry Phase 3 Closeout

## Current State

2026-10-19: G0/G1/G2 reconciled after independent Stannum upgrade U.
Original precommit run01 remains RED at #26; its #27-51 were NOT RUN.
User then authorized a 0.5.1 upgrade, planned/reviewed with Oracle and committed
and pushed independently as U `16e2d8b682b3b449fa45620805d337a668a6294d`.
U passed its own targeted16 and complete51 (908.70s); that is not Phase3 evidence.
New precommit run02 passed all51 contracts (918.90s). A postcommit remains
pending, A/B not yet committed; no future commit or push identity is prefilled.
Phase3 remains docs/evidence-only relative to U, not a runtime/test implementation.

Baseline: worktree `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99`, branch
`v99`, upstream `origin/v99`, remote `https://github.com/wuxianliang/pg-agent.git`.
Re-locked HEAD and origin/v99 are both
`16e2d8b682b3b449fa45620805d337a668a6294d` (ahead/behind 0/0, after U push).
The original run01 baseline was `93d05f12090ce4b27b62b1a6f90d3c1b438eab68`.
Stannum is now pinned to 0.5.1; see the independent upgrade plan/report.
Restored scoped stash `99d334fe90af613605b6e9ec2a7d7c0a3c5abd2d` remains
retained: twelve files restored byte-exact, matrix/ledger keep both U and P3
sections after append-only conflict resolution. No U changes enter A again.
The chain is Phase 1 implementation `69e118d`, evidence `5be562d`, Phase 2
implementation `937a864`, evidence `93d05f1`. Main is not merged or pushed.
Unrelated untracked `docs/reviews/v13-registry-stage41-plan-review-2026-10-17.md`
is excluded. All current tracked changes are the plan's documentation paths;
no executable source, dependency, fixture, trace, ACL or loader changes are allowed.

## Evidence Levels

DIRECT means an actual named probe/receipt observed the specific scenario.
STATIC means source or loaded catalog inspection, not runtime scenario coverage.
INFERRED is a combination without an independent assertion. NOT CLAIMED denotes
unimplemented or excluded behavior; NOT RUN never means PASS. Historical results
are not combined into either Phase 3 sequence.

Historical Phase 1 postcommit: 50 items, 48 exit 0 plus expected exit 1/2,
registry 16/16 groups and 481 checks. Phase 2 precommit: full 51, 951.81s;
postcommit on `937a864`: full 51, 911.44s, 49 exit 0 plus expected exit 1/2,
registry 16/16 groups, 485 checks, zero independent failures; consumer 289.
S42R-9 is the separate RED #30 compiler attempt (480.16s, exit 1; #31-51 NOT RUN).
S42R-10 is the separate RED old-SDK TLS preflight (ports/full sequence NOT RUN).
S42R-11/12 record the later successful offline rounds; none erases those REDs.

## Installation And Catalog Evidence

Source references below are symbols and baseline SQL line numbers, not promises
that documentation line numbers remain fixed. Prefix bytes before the Stage 42
sentinel are SHA-256
`e5222e1499001f3a734292d8456d2b431fcfcd2a5862952bfcc38137caee34d4`.
`v13/registry/setup_db.py::_registry_sql_parts`, `validate_stage41_prefix`,
`validate_stage42_overlay` and `validate_delta` enforce the boundary. The loader
has 41 entries, ending fair_claim/39, ce_run/40, registry/41. Registry contains
only README, SQL, setup_db.py, test_registry.py and test_consumer.py.

An actual fresh isolated setup/catalog audit created and cleaned up
`ll_registry_50788_9b6b80` on this baseline. It loaded Stage 1-40, prefix and overlay;
validators reported prefix +3 tables/+8 functions, overlay +2 tables/+11 signatures,
20 replacements, zero added sequences/roles/schema/database ACL changes. This
catalog observation is STATIC contract evidence, not a separate claim-window test.
The complete regression must independently exercise the existing guards.

### All Twenty Effective Replacements

Every row is an effective loaded overlay definition; earlier copies are not the
operative source. `setup_db.py::STAGE42_REPLACEMENTS` is the exact signature set;
`native_acl_closure` checks catalog closure. Original SQL stays byte-pinned.

| # | Effective object | Last pre-overlay source | Overlay SQL / filtering location |
|---|---|---|---|
| 1 | `v13_claim(text,integer)` | fanout | 822; CAS, immutable pin, double fences |
| 2 | `v13_claim_fair(text,integer)` | fair_claim | 878; advisory/root/child/effect, pin |
| 3 | six-argument `v13_complete` | ACL | 1298; delegates to invoker common implementation |
| 4 | `v13_probe` | manifest | 1324; eighth freshness key |
| 5 | `v13_judgment_envelope` | final filter | 1341; one-statement fences, 21 keys |
| 6 | `v13_snap_of` | resolve | 1457; supplied envelope projection only |
| 7 | `v13_effect_envelope` | envelope | 1475; strips registry revision from judge identity |
| 8 | `v13_advance` | final plan_arm, not fanout/triage | 1483; eighth-key stale; tool-call aggregation, predecessor, repair/material/approval/wake filtering before selection |
| 9 | `v13_route` | loop/advance | 2069; finish machine events, preserving origin_user_seq |
| 10 | `v13_canonical_state` | resolve | 2111; current-turn machine messages, not historical audit |
| 11 | `v13_parse` | economy | 2130; effect-backed resolve/failed; synthetic still counts |
| 12 | `v13_cap_answer_anchor` | seam | 2155; human event/effect/anchor |
| 13 | `v13_cap_human_answered` | seam | 2228; filtered anchor delegation |
| 14 | `v13_tail_gap_cap_exempt` | seam | 2237; signal evidence |
| 15 | `v13_harness_tail_gap` | seam | 2301; effect and signal evidence |
| 16 | `v13_triage_fold_reason` | triage | 2335; signal and cap-human |
| 17 | `v13_triage_block_explore_spawn` | triage | 2370; tool-call existence |
| 18 | `v13_closeout` | spawn | 2388; repair/replan/material/wake/approval receipts |
| 19 | `v13_recover_idle` | govern | 2595; signal/fingerprint/nudge |
| 20 | `v13_scheduler_hint` | govern | 2659; unconsumed tool-call count |

### Schema, Interfaces And Projection

Prefix: registrations, singleton global clock, diagnostic scope meta; eight
functions. Registration allocates one global revision per successful register or
retire, intervals `[from,to)`, no writes for already_live/not_live, and lock order
clock -> meta -> sessions/append_event -> registrations. Missing seed fails closed.
Scope traversal nearest-shadows, caps at 32/repeated UUID; unresolved dependencies
are diagnostics in the ten-key context hash. Tools remain current even at old/zero
registry revision; cache identity is `(scope_id,context_revision,tools_revision)`.

Overlay pin table: primary key `(effect_id,attempt_no)`, exact unique
`(effect_id,attempt_no,fence)`, scope/context/tools revisions and claimed_at;
attempt/fence positive, revisions nonnegative. Event-pin table: primary key
`(session_id,event_seq)`, FK to events and FK to the exact pin triple. Loaded
`trg_v13_effect_context_pin_frozen` rejects UPDATE/DELETE;
`trg_v13_effect_context_event_pin_frozen` validates INSERT source and rejects
UPDATE/DELETE. Loaded events AFTER INSERT capture uses exact attempt/fence,
not latest-pin guessing. Existing business payload guards remain unchanged.

Global claim: only worker/lease parameters, exact six keys effect_id/attempt_no/
fence/kind/request/context_revision, ordinary host identity route. Fair claim:
same plus root_session_id, owner-only, route denied. CE keeps its independent
seven-key/no-registry-pin plane. Five-argument completion wrapper is unchanged;
six-argument wrapper is replaced; seven-argument strict overload has zero defaults.
Common and wrappers remain INVOKER so current_user authorization cannot become
an owner bypass. Strict checks token first, then NULL/negative revision 22023,
missing exact pin P0001, mismatched revision stale. Exact old pin may settle
accepted; terminal exact token may replay.

`probe` has eight keys, envelope 21, snap only projects its input, advance compares
the eighth key (absent is stale), and effect_envelope removes registry_revision
so the logical judge identity does not drift. Current helpers compare pins with
the global clock and current tools revision. Missing/malformed mapping with pin
history is false; legacy/CE/synthetic with no pin history remains eligible.
Audit is retained; superseded projection is not cancellation, requeue or IO undo.

### ACL And Loaded Owner Call Graph

All registry helpers have fixed search_path; new helpers are trusted owner
DEFINER except INVOKER completion wrappers/common. Owners retain owner rights;
the table below describes non-owner host EXECUTE. PUBLIC/worker have none.

| Access | route | recall | resolve | spawn_owner |
|---|---|---|---|---|
| prefix registrations/meta SELECT | yes | yes | no | no |
| prefix register/retire | yes | no | no | no |
| scope_chain/context | yes | yes | no | no |
| private prefix helper EXECUTE | no | no | no | no |
| pin/event-pin table and column rights | no | no | no | no |
| fences | yes | yes | yes | no |
| pin insert / exact lookup | yes | no | no | no |
| pin matches | yes | no | no | yes |
| event_current | yes | yes | yes | yes |
| effect_current | yes | no | yes | no |
| strict/common completion | yes | no | no | yes |
| global claim entry EXECUTE | yes | no | no | yes, latent failure below |
| fair claim | no | no | no | no |

Clock is owner-only, all host prefix DML is denied, and all host pin table/column
rights are denied. NULL actor honors actual caller/SET ROLE; explicit actor reads
require self/direct parent behind the outer EXECUTE boundary. Unknown/unauthorized
scopes return canonical empty context; authorized unregistered scopes preserve
identity and tools. Recall canonical and spawn_owner fork->prefix_identity->
canonical_state require only event_current, not effect_current or pin-table rights.

The loaded owner=spawn_owner/prosecdef query returned SIX functions, not merely
the three in the early spawn-only stage: ce_insert_session, fork, open_session,
policy_share, spawn_batch_allowed, spawn_subsession. Each loaded prosrc was read;
none references claim. policy_share and batch_allowed use fixed policy/budget
helpers; ce_insert_session is a fixed INSERT; open_session is a fixed root INSERT;
fork/spawn use their fixed helper chains, not arbitrary SQL. SQL/Python role-switch
search distinguishes fixture SET ROLE from spawn installation self-check. This is
STATIC inspection of the given code, not proof that arbitrary future dynamic SQL
is unreachable. NOLOGIN is not that proof.

Loaded `v13_open_session(jsonb)` returns uuid, zero defaults, VOLATILE DEFINER,
owner spawn_owner, search_path pg_catalog/public; EXECUTE only owner and route.
The isolation runbook therefore uses this approved API, not direct session INSERT.

### Locks, Atomicity And Scenario Pointers

`test_registry.py`: native_load_untouched and native_plan_arm_closed_set enforce
prefix/loader/five-file closure; native_as_of, dependency, ACL/tools probes cover
registration resolution. `test_consumer.py`: native_claim_complete covers claim,
strict/legacy completion and keys; native_event_pin_atomicity covers exact mapping,
FK/guard fault injection and rollback of event/seq/effect/mapping;
native_w4_projection, native_w4_tool_parse, native_w4_control, native_w4_human,
native_actual_tool_spawn and native_plan_signal_evidence cover the listed consumers.
native_freshness and native_statement_snapshot cover real register effects on
probe/envelope/advance, tools fences and logical judge identity; native_acl_closure
checks owner/security/search_path/default/ACL/catalog and mutation negatives.

native_lock_barriers uses exact backend PIDs, pg_blocking_pids and ungranted
pg_locks, not sleep-based inference: writer clock waiting on its session does not
reverse-block another scope claim; completion is session -> effect; fair is
advisory13002 -> root -> child -> effect NOWAIT, with NULL and zero partial CAS/pin
on contention. Govern's historical observer correction uses actual updater PID
and transaction-lock wait, byte-locked by r0_source_scope. Phase 3 changes none.

## Four Oracle Dispositions And Limits

1. Correct 21 to 20 replacements; new signatures are separate. Loaded validators
   agree. Any unexpected changed-object superset is a Phase 2 defect, not a docs fix.
2. Accept latent spawn_owner global-claim EXECUTE mismatch: invoker first calls
   fences without permission, STATIC 42501 before CAS. No dedicated denial probe
   exists. Given call graph has no production caller; a reachable caller blocks
   closeout and requires a separately scoped Phase 2 repair.
3. Claim double-fence check and fake adapter recheck do not lock the clock. A
   writer may commit after the final read but before COMMIT. No commit-instant
   freshness or always-latest external IO guarantee. Function-internal 40001 branch
   is STATIC, not independently triggered; only adapter-detected change/rollback
   has direct protocol-model coverage.
4. Real register/retire -> later successful claim gets new revision and old-pin
   current projection flips is INFERRED when writer committed and reader uses a
   new snapshot. Adjacent freshness and clock-projection tests do not constitute
   an independent combination assertion. pin_matches remains historical exact
   matching and does not read clock; event_current/effect_current do.

Tool profiles and prompt consumers, production strict adapters, multilingual DB
parity, PI_PARITY_REQUIRE_ALL, real provider, CE generation mapping, TTL/GC,
production online migration/rollback and main integration are NOT CLAIMED.
Global invalidation blast radius, tools without history, append-only growth and
the final-check window are accepted costs, not Phase 3 fixes. Any actual gate red,
partial write, reachable latent caller or projection defect stops this closeout.

## Environment And Run Receipts

User approved rebuilding the old PiSwift test checkout. The detached
`/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift` was restored at v0.87.1,
`bfccb32f2d6318b75519b2c1790e7e66e133f5da`. Active
`/Users/wxl/Projects/PiSwift` remains clean main at
`a73c391ce1d891b7b6f8f37a8508f184a31703e3`, not switched or edited.
Ignored package copies change only the local dependency path; frozen original
manifests and Sources are hash-protected. Real /usr/bin/swift uses --package-path,
--disable-automatic-resolution and --skip-update with the old 25-pin lock and
existing local caches. This environment is local/ignored, not a portable install.

Preflight `phase3-preflight-20261019-run02-results.json` reports parity then ports
exit 0 and trace restoration; verify reports external checkouts and frozen sources
unchanged. Earlier run01 is separately retained, not spliced.
Default parity skips missing node_modules; no all-plane or provider claim.

After U, independent `phase3-preflight-20261019-run03` again ran parity then
ports, both exit0 with trace bytes/mode restored. Final verify passed, active
and old PiSwift clean and frozen Sources/manifests unchanged. Static recheck
confirmed prefix hash, 20 replacements, 11 signatures, loader41, registry
five-file closure and exact 51 manifest rows equal both U README and plan.
The previous run02 preflight is historical, not reused as this new preflight.

Invocation from V99 root:

```bash
export PATH="$PWD/prompt-exports/w5-piswift-compat/bin:$PATH"
export W5_SWIFT_OFFLINE=1 UV_FROZEN=1
uv run python prompt-exports/w5-phase2-runner.py phase3-precommit-20261019-run02
# Only after A push and tracked clean:
uv run python prompt-exports/w5-phase2-runner.py phase3-postcommit-20261019-run01
uv run python prompt-exports/w5-piswift-compat/verify.py
```

Runner is the unchanged ignored `w5-phase2-runner.py`, timeout 600s/item, strict
serial order and first unexpected result stops. Each command is `UV_FROZEN=1 uv
run python` plus the exact path/args in the 51-row README manifest. #17 requires
FAIL/ask_user refusal, #18 usage before DB setup. Every result must record exit,
duration, valid and trace restoration. The runner does not verify check counts;
manual #39/#51 SUMMARY checks and verify/HEAD/status remain mandatory.

Trace original/final target SHA-256:
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`, mode 0644.
Both rounds must separately confirm every item's restored bytes/mode plus final
hash; no checkout-based trace restoration. Ignored numbered logs/results/manifest/
head files remain local, and their loss limits independent re-audit; the permanent
per-item record below is the self-contained outcome summary.

### Original Precommit Run01 (Historical RED)

RED_REGRESSION, receipt `prompt-exports/phase3-precommit-20261019-run01/`.
HEAD before/after: `93d05f12090ce4b27b62b1a6f90d3c1b438eab68`; fetched
origin/v99 unchanged (0/0). Documentation-dirty tree: the eleven modified paths
and three new Phase 3 documents in the approved allowlist; unrelated Stage41
review remains untracked/excluded. No executable diff or staging. Total recorded
item time 202.46s. #1-25 met their contracts; #26 failed V1 in 6.59s, exit 1
(expected 0), so #27-51 were NOT RUN. No full precommit acceptance or A/B.

Read-only diagnosis: installed `pg_extension.extversion`, available default and
`stannum.version()` all report `0.5.1`; `version_checks` requires `0.4.0`
at `v13/mgraph/test_stannum_usage.py:605`. PostgreSQL is 18.4. The test and
extension were not modified during that original run. At that point separate
Stannum restoration required approval beyond PiSwift. The later user direction
superseded restoration with independent upgrade U; the original RED is retained,
and a new run02 must start from #1. No results are spliced.

All 26 executed rows restored trace bytes/mode; final SHA-256 equals the target
above, mode 0644. Post-run verify reports active/old PiSwift clean and frozen
sources/manifests unchanged. Every command below has prefix
`UV_FROZEN=1 uv run python`; `T/F` are recorded valid values, restore refers
to that item's trace bytes/mode, and `-` denotes no execution/measurement.

| # | Path and arguments | Exit / expected | Seconds | Valid | Restore | Key output/status |
|---|---|---|---|---|---|---|
| 1 | `v13/acl/test_acl.py` | 0 / 0 | 2.75 | T | T | [acl] ALL PASS (197) |
| 2 | `v13/attention/test_attention.py` | 0 / 0 | 2.20 | T | T | [attention] ALL PASS (156) |
| 3 | `v13/catalog/test_catalog.py` | 0 / 0 | 3.64 | T | T | [catalog] ALL PASS |
| 4 | `v13/ce_run/test_ce_run.py` | 0 / 0 | 14.62 | T | T | 16/16 groups, 665 checks, zero independent failures |
| 5 | `v13/characterize/test_characterize.py` | 0 / 0 | 6.79 | T | T | ALL PASS |
| 6 | `v13/chunks/test_chunks.py` | 0 / 0 | 9.20 | T | T | ALL PASS |
| 7 | `v13/control/test_control.py` | 0 / 0 | 4.45 | T | T | [PASS] stage 17 gates |
| 8 | `v13/economy/test_economy.py` | 0 / 0 | 9.39 | T | T | ALL PASS |
| 9 | `v13/envelope/test_envelope.py` | 0 / 0 | 7.87 | T | T | [envelope] ALL PASS |
| 10 | `v13/fair_claim/test_fair_claim.py` | 0 / 0 | 5.63 | T | T | [ok] 137 checks |
| 11 | `v13/fair_driver/test_fair_driver.py` | 0 / 0 | 5.21 | T | T | [ok] 42 checks |
| 12 | `v13/fanout/test_fanout.py` | 0 / 0 | 2.25 | T | T | [done] fanout |
| 13 | `v13/filter/test_filter.py` | 0 / 0 | 26.13 | T | T | ALL PASS |
| 14 | `v13/frontier_gap/test_frontier_gap.py` | 0 / 0 | 7.84 | T | T | [ok] 59 checks |
| 15 | `v13/goal_supervise/test_goal_supervise.py` | 0 / 0 | 7.52 | T | T | [ok] 172 checks |
| 16 | `v13/goal_supervisor/test_goal_supervisor.py` | 0 / 0 | 5.80 | T | T | [gate] Fake checks only; unattended authorization remains accept_unattended.py |
| 17 | `v13/goal_supervisor/test_goal_supervisor.py --unattended-continuation` | 1 / 1 | 5.86 | T | T | 74 checks; FAIL unattended_continuation/ask_user (expected) |
| 18 | `v13/goal_supervisor/test_goal_supervisor.py bad-args` | 2 / 2 | 0.35 | T | T | usage marker; no DB setup |
| 19 | `v13/govern/test_govern.py` | 0 / 0 | 2.75 | T | T | [govern] ALL PASS (228) |
| 20 | `v13/handoff/test_handoff.py` | 0 / 0 | 2.26 | T | T | [handoff] ALL PASS (240) |
| 21 | `v13/loop/test_loop.py` | 0 / 0 | 9.76 | T | T | [M3 loop] ALL PASS |
| 22 | `v13/loop_driver/test_loop_driver.py` | 0 / 0 | 5.89 | T | T | [ok] 91 checks |
| 23 | `v13/manifest/test_manifest.py` | 0 / 0 | 7.22 | T | T | [manifest] ALL PASS |
| 24 | `v13/memory/test_memory.py` | 0 / 0 | 7.72 | T | T | ALL PASS |
| 25 | `v13/mgraph/test_mgraph.py` | 0 / 0 | 32.77 | T | T | [mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN |
| 26 | `v13/mgraph/test_stannum_usage.py` | 1 / 0 | 6.59 | F | T | FAIL V1: installed 0.5.1, required 0.4.0 |
| 27 | `v13/mgraph_assembly/test_mgraph_assembly.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 28 | `v13/observe/test_observe.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 29 | `v13/periphery/test_periphery.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 30 | `v13/pi_parity/test_pi_parity.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 31 | `v13/pi_ports/test_pi_ports.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 32 | `v13/plan_arm/test_plan_arm.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 33 | `v13/plan_contract/test_plan_contract.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 34 | `v13/plan_read/test_plan_read.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 35 | `v13/quota_window/test_quota_window.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 36 | `v13/read_tools/test_read_tools.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 37 | `v13/real_chain/test_real_chain.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 38 | `v13/recall/test_recall.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 39 | `v13/registry/test_registry.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 40 | `v13/resolve/test_resolve.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 41 | `v13/schema/test_schema.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 42 | `v13/seam/test_seam.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 43 | `v13/should_run/test_should_run.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 44 | `v13/spawn/test_spawn.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 45 | `v13/summary/test_summary.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 46 | `v13/triage/test_triage.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 47 | `v13/twophase/test_twophase.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 48 | `v13/workflow_bind/test_workflow_bind.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 49 | `v13/workspace_admit/test_workspace_admit.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 50 | `v13/workspace_exec/test_workspace_exec.py` | - / 0 | - | - | - | NOT RUN after #26 failure |
| 51 | `v13/registry/test_consumer.py` | - / 0 | - | - | - | NOT RUN after #26 failure |

### Precommit Run02 On Upgrade U: PASS

Receipt `prompt-exports/phase3-precommit-20261019-run02/`. HEAD before/after
`16e2d8b682b3b449fa45620805d337a668a6294d`, documentation-dirty and unstaged;
the eleven modified and three new approved documents are A's scope. No
executable/loader/dependency/trace changes relative to U. Complete restarted
51-item sequence: 918.90s, 49 exit0 plus expected #17 exit1/#18 exit2, all
valid=true/trace_restored=true. Outer registry:16/16,485,zero failures; consumer289.
Final verify confirms both external PiSwift checkouts clean and frozen source
bytes unchanged. Final trace equals the baseline SHA-256 above, mode0644.
Default node_modules SKIP remains a limitation. U's sequence is not reused.

Each command has prefix `UV_FROZEN=1 uv run python`. Numbered log names are
`NN-<path with slashes replaced by hyphens>.log` under the receipt directory.

| # | Path and arguments | Exit / expected | Seconds | Valid / restore | Key output |
|---|---|---|---|---|---|
| 1 | `v13/acl/test_acl.py` | 0 / 0 | 2.78 | T / T | [acl] ALL PASS (197) |
| 2 | `v13/attention/test_attention.py` | 0 / 0 | 2.27 | T / T | [attention] ALL PASS (156) |
| 3 | `v13/catalog/test_catalog.py` | 0 / 0 | 3.61 | T / T | [catalog] ALL PASS |
| 4 | `v13/ce_run/test_ce_run.py` | 0 / 0 | 14.93 | T / T | SUMMARY groups 16 passed 16 failed 0 checks 665 independent_case_failures 0 failures [] |
| 5 | `v13/characterize/test_characterize.py` | 0 / 0 | 6.83 | T / T | ALL PASS |
| 6 | `v13/chunks/test_chunks.py` | 0 / 0 | 9.41 | T / T | ALL PASS |
| 7 | `v13/control/test_control.py` | 0 / 0 | 4.45 | T / T | [PASS] stage 17 gates |
| 8 | `v13/economy/test_economy.py` | 0 / 0 | 9.35 | T / T | ALL PASS |
| 9 | `v13/envelope/test_envelope.py` | 0 / 0 | 7.89 | T / T | [envelope] ALL PASS |
| 10 | `v13/fair_claim/test_fair_claim.py` | 0 / 0 | 5.76 | T / T | [ok] 137 checks |
| 11 | `v13/fair_driver/test_fair_driver.py` | 0 / 0 | 5.27 | T / T | [ok] 42 checks |
| 12 | `v13/fanout/test_fanout.py` | 0 / 0 | 2.53 | T / T | [done] fanout |
| 13 | `v13/filter/test_filter.py` | 0 / 0 | 26.01 | T / T | ALL PASS |
| 14 | `v13/frontier_gap/test_frontier_gap.py` | 0 / 0 | 8.91 | T / T | [ok] 59 checks |
| 15 | `v13/goal_supervise/test_goal_supervise.py` | 0 / 0 | 7.31 | T / T | [ok] 172 checks |
| 16 | `v13/goal_supervisor/test_goal_supervisor.py` | 0 / 0 | 6.12 | T / T | [gate] Fake checks only; unattended authorization remains accept_unattended.py |
| 17 | `v13/goal_supervisor/test_goal_supervisor.py --unattended-continuation` | 1 / 1 | 5.94 | T / T | Expected FAIL unattended_continuation / ask_user |
| 18 | `v13/goal_supervisor/test_goal_supervisor.py bad-args` | 2 / 2 | 0.38 | T / T | Expected usage; no DB setup |
| 19 | `v13/govern/test_govern.py` | 0 / 0 | 2.76 | T / T | [govern] ALL PASS (228) |
| 20 | `v13/handoff/test_handoff.py` | 0 / 0 | 2.24 | T / T | [handoff] ALL PASS (240) |
| 21 | `v13/loop/test_loop.py` | 0 / 0 | 9.41 | T / T | [M3 loop] ALL PASS |
| 22 | `v13/loop_driver/test_loop_driver.py` | 0 / 0 | 6.75 | T / T | [ok] 91 checks |
| 23 | `v13/manifest/test_manifest.py` | 0 / 0 | 7.26 | T / T | [manifest] ALL PASS |
| 24 | `v13/memory/test_memory.py` | 0 / 0 | 7.99 | T / T | ALL PASS |
| 25 | `v13/mgraph/test_mgraph.py` | 0 / 0 | 32.51 | T / T | [mgraph M1+M2+M3+M4+v2-V1+V2] groups A+D+E+F+G+H: ALL GREEN |
| 26 | `v13/mgraph/test_stannum_usage.py` | 0 / 0 | 6.96 | T / T | ALL PASS (77) |
| 27 | `v13/mgraph_assembly/test_mgraph_assembly.py` | 0 / 0 | 12.35 | T / T | ALL J GREEN (W1: J1-J3; W2: J4-J7; W3: J8-J9) |
| 28 | `v13/observe/test_observe.py` | 0 / 0 | 1.93 | T / T | [observe] ALL PASS (147) |
| 29 | `v13/periphery/test_periphery.py` | 0 / 0 | 7.09 | T / T | ALL PASS (130 checks) |
| 30 | `v13/pi_parity/test_pi_parity.py` | 0 / 0 | 18.71 | T / T | [SKIP] not_run/toolchain_absent planes=node_modules |
| 31 | `v13/pi_ports/test_pi_ports.py` | 0 / 0 | 44.83 | T / T | [PASS] H6 |
| 32 | `v13/plan_arm/test_plan_arm.py` | 0 / 0 | 5.81 | T / T | [ok] 104 checks |
| 33 | `v13/plan_contract/test_plan_contract.py` | 0 / 0 | 2.05 | T / T | [ok] 93 checks |
| 34 | `v13/plan_read/test_plan_read.py` | 0 / 0 | 1.98 | T / T | [ok] 11 checks |
| 35 | `v13/quota_window/test_quota_window.py` | 0 / 0 | 68.26 | T / T | [quota_window] ALL PASS (226) |
| 36 | `v13/read_tools/test_read_tools.py` | 0 / 0 | 473.26 | T / T | [PASS] E4 |
| 37 | `v13/real_chain/test_real_chain.py` | 0 / 0 | 2.12 | T / T | [ok] 24 checks |
| 38 | `v13/recall/test_recall.py` | 0 / 0 | 9.89 | T / T | ALL PASS |
| 39 | `v13/registry/test_registry.py` | 0 / 0 | 12.03 | T / T | 16/16 groups, 485 checks, zero failures |
| 40 | `v13/resolve/test_resolve.py` | 0 / 0 | 6.39 | T / T | [M2 resolve] ALL PASS |
| 41 | `v13/schema/test_schema.py` | 0 / 0 | 1.32 | T / T | [M1 schema] ALL PASS |
| 42 | `v13/seam/test_seam.py` | 0 / 0 | 5.23 | T / T | [PASS] stage 21 gates |
| 43 | `v13/should_run/test_should_run.py` | 0 / 0 | 2.34 | T / T | [should_run] ALL PASS (194) |
| 44 | `v13/spawn/test_spawn.py` | 0 / 0 | 1.90 | T / T | [PASS] stage 18 gates |
| 45 | `v13/summary/test_summary.py` | 0 / 0 | 12.31 | T / T | ALL PASS |
| 46 | `v13/triage/test_triage.py` | 0 / 0 | 1.89 | T / T | [done] triage |
| 47 | `v13/twophase/test_twophase.py` | 0 / 0 | 6.42 | T / T | [M4 twophase] ALL PASS |
| 48 | `v13/workflow_bind/test_workflow_bind.py` | 0 / 0 | 2.05 | T / T | [ok] 8 checks |
| 49 | `v13/workspace_admit/test_workspace_admit.py` | 0 / 0 | 5.71 | T / T | [ok] 65 checks |
| 50 | `v13/workspace_exec/test_workspace_exec.py` | 0 / 0 | 3.40 | T / T | [ok] 54 checks |
| 51 | `v13/registry/test_consumer.py` | 0 / 0 | 4.00 | T / T | 289 checks |

### A Postcommit Sequence

NOT RUN; A not committed/pushed. No A identity or clean-tree result is prefilled.

## Documentation And Deployment Index

README carries the runbook within the frozen five-file directory. It supports only
fresh disposable installation and authorized read-only catalog checks. Existing
production upgrade/rollback requires stop-write, backup/audit preservation and a
separate migration design; no drop/replay/delete-pin recipe is provided. A root
anchor uses inspected open_session and does not become all sessions' ancestor.

Tutorial ch02/ch03 correct claim signature; ch06 corrects six-column tools and
sql/tool/llm kinds; ch08 corrects claim planes, handler filtering, profiles and
fake-versus-production scope; ch12 states interruptible is function-hardcoded.
Design section 11 item 6 records the actual side-table implementation and links
this closeout. Phase1/Phase2 plan tops now acknowledge 69e118d/5be562d and
937a864/93d05f1. Matrix has an independent P3 section, ledger P3R-1..7;
S42R-9/10 RED and S42R-11/12 successes remain historical.

## Commit Protocol

One bounded Phase 3 Oracle review (`untitled-chat-85AA1B`) was read. Its concrete
findings corrected the plan header, preflight receipt pointer and ch08 ID wording.
The suggested missing-report warning was a diff-view omission: the untracked
report and design/Phase1/Phase2 edits were verified directly in the worktree and
will be staged by their approved paths. No additional runtime review is claimed.

A contains approved documents and actual precommit evidence, then immediately
pushes origin/v99. A tracked-clean tree must run all 51 again from #1. B may only
append results to README/matrix/ledger/this report and plan section 11; all other
tracked paths and README manifest bytes/parsed 51 entries must match A. Normal
hooks, scoped add and diff/credential review are mandatory. No third 51-item
round is required for verified result-only B. B's own future hash/push is never
prefilled: final read-only delivery reports B and origin/v99 equality, without C.
