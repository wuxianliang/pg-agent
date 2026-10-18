# Stages 41-42: Spacetime Registry and Consumer Overlay

## Current Acceptance (2026-10-19)

W5/W6 test and documentation acceptance passed in the isolated offline 51-item
sequence: 49 exit 0 plus the expected goal probes exit 1/2; trace bytes/mode
restored after all 51 items. Latest receipt and reproducibility details are at
"Offline Isolation Acceptance" below. Historical RED attempts are retained,
not combined. Parent coordinator review, staging, commit, push and post-commit clean-tree
verification have not been performed.

## Scope

Stage 41 is the immutable three-table/eight-function registration prefix after
Stage 40. `service`, `tool_profile`, and `prompt_section` are the complete kind
set. Stage 42 is a sentinel-delimited consumer overlay in the same SQL file:
claim pins, strict completion, eighth-key freshness and superseded projection.
There is no new loader stage, provider IO, notification/waiter surface, TTL or
GC. CE functions are neither called nor replaced; CE generation fields retain
their existing meaning. The loader still has exactly 41 entries.

Public APIs:

- `v13_registry_register(scope, kind, name, value, depends_on DEFAULT '{}')`
- `v13_registry_retire(scope, kind, name)`
- `v13_scope_chain(scope, actor DEFAULT NULL)`
- `v13_registry_context(scope, rev DEFAULT NULL, actor DEFAULT NULL)`

Writes return `{schema_version, ok, registration_id, revision}` on success.
`already_live` returns the live identity and `valid_from_rev`; `not_live` returns
no identity. Both are zero-write outcomes, with no clock allocation. Invalid
parameters raise and leave all changes rolled back.

## Clock and Intervals

`v13_registry_clock` is a global singleton, seeded at revision 0. Each successful
register or retire allocates exactly one revision. Lock order is clock -> meta
-> sessions (inside append_event) -> registrations; the event precedes the row
change. The clock row lock lasts until transaction completion: keep write
transactions short and do no external IO or waiting in them. At READ COMMITTED,
a concurrent same-key registration waits and then returns `already_live`;
REPEATABLE READ may instead raise 40001, which is a safe failure.

Registration intervals are half-open `[valid_from_rev, valid_to_rev)`. A
same-transaction register/retire pair receives consecutive revisions, not one
shared revision. There is no bulk-write API; a future bulk API must explicitly
define shared revision allocation. At most one live row exists per
`(scope, kind, name)`. Eight identity/value columns are immutable; DELETE is
forbidden. Owners can operationally close an interval directly, but host roles
have no table DML, so normal retirement goes through the function.

`v13_registry_meta.revision` is the last global revision written for that scope,
not a read-addressing counter. It is lazily upserted on successful writes and
may legitimately lag the global clock. Operations can reconcile it against
`max((payload->>'revision')::bigint)` over that scope's registry events. A missing
clock seed is a configuration error: reads and writes raise, with no fallback.

For context reads, NULL revision means the global current revision, negative
revision raises before authorization, zero means an empty registration plane,
and a future revision is clamped to the current clock and echoes that value.
An ancestor write after a pinned revision cannot alter the child's historical
registration view. Reads are STABLE and use one statement snapshot, with no
write, row lock, or notification.

## Resolution and Pinning

Scope traversal includes self at depth 0, walks leaf to root, and truncates at
32 rows or a repeated path UUID. Ordinary fork columns are write-once, so a
cycle is only a defensive read-path case. Unlike the downward cancellation
walk (cap 64, cycle raises), this read walk truncates without raising.

The nearest `(kind, name)` shadows more distant registrations. Services resolve
by an add-only dependency closure from the empty set; missing and cyclic
services are reported in `unresolved`, not raised. Dependencies name service
registrations, not `provides` entries. Arrays, dependencies, and missing names
are ordered by name. Entry provenance overrides any same-named value keys.
`prompt_section` remains an open object shape. For future tool-profile
consumption, `v13_interruptible()` is function-first and the profile is the
coverage/override surface; this stage has no profile consumer.

Context has exactly ten top-level keys: `schema_version`, `scope_id`, `revision`,
`tools_revision`, `services`, `tool_profiles`, `prompt_sections`, `tools`,
`unresolved`, `context_hash`. Hashing is SHA-256 of the remaining JSONB object's
PostgreSQL text representation. Both `unresolved` and `tools_revision` enter the
hash. Tools have exactly `name`, `description`, `kind`, `handler`, `param_spec`,
and `enabled`, including disabled rows unchanged.

Tools have **no historical time axis**: even an old or zero registry revision
returns current tools and their current `v13_tools_meta.revision`. Phase 2 pins
`(scope_id, context_revision, tools_revision)` and requires both fences to be
rechecked before claim commit; a changed scalar rolls back CAS and pin.

Registry events intentionally advance `v13_probe.session_version` and
`max_event_seq`; an in-flight advance becomes stale and reparses. This is a
safe consequence of the changed world, not a CE interaction or regression.

## ACL Matrix

The eight Stage 41 functions are SECURITY DEFINER with fixed
`search_path = pg_catalog, public` and a trusted superuser owner. No host role has CREATE on public or database
TEMPORARY in the isolated deployment.

| Object/access | PUBLIC | worker | resolve | recall | route |
| --- | --- | --- | --- | --- | --- |
| registrations/meta SELECT | - | - | - | SELECT | SELECT |
| registrations/meta DML | - | - | - | - | - |
| clock, all access | - | - | - | - | - |
| register/retire EXECUTE | - | - | - | - | EXECUTE |
| scope_chain/context EXECUTE | - | - | - | EXECUTE | EXECUTE |
| caller/read_ok/chain_inner/frozen EXECUTE | - | - | - | - | - |

`resolve` is intentionally excluded from the eight Stage 41 registry functions
(42501), a narrower boundary than older three-role read surfaces. Phase 2 grants
only the narrow fences/projection helpers listed below, not registry context. With NULL actor, real
caller must be superuser or route/recall member; SET ROLE downgrades are honored.
With non-NULL actor, caller membership is not checked: an existing self or
direct parent authorizes the read. Thus EXECUTE is the actual outer boundary;
unlike stage 23's self-deny rule, this surface follows CE's self-or-parent rule.
Unknown scopes, unauthorized callers, and unknown/unrelated actors share one
canonical empty context (NULL scope, zero scalars, empty arrays, fixed hash),
or zero chain rows. A known, authorized but unregistered scope instead returns
its real identity, current scalars, and all tools.

## Deviation Index

References target the Stage 41 (registry) section in
`docs/reviews/v13-control-plane-deviation-ledger-2026-09-26.md`:

| Reference | Decision |
| --- | --- |
| S41R-1 | Global clock replaces per-scope addressing; meta is diagnostic. |
| S41R-2 | Tools revision is the second fence and enters the hash. |
| S41R-3 | Read ACL intentionally excludes resolve. |
| S41R-4 | Caller/read authorization reproduces CE shape, with no CE call. |
| S41R-5 | Upward cap 32 and cycle truncation differ from downward writes. |
| S41R-6 | Consumer claim additions deferred; fair_claim SIX unchanged. |
| S41R-7 | Registry events intentionally move advance's stale fences. |
| S41R-8 | Interruptible function first; profiles have no consumer yet. |
| S41R-9 | Unresolved diagnostics enter the context hash. |
| S41R-10 | Prompt-section object shape remains open. |
| S41R-11 | Negative/zero/future revision means raise/empty/clamp. |
| S41R-12 | Optional CE registration_generation mapping remains deferred. |
| S41R-13 | Six guard adaptations; CE SQL/setup/README byte-pinned to cbf65cf, CE test diffs limited to its loader-tail assertion. |

## Connection and Lifecycle

`connect_test_database` and its route/recall/worker/plain wrappers accept either
`TestDatabase` or a database name with `server`. Both resolve aliases to that
database's temporary host roles: the handle uses its recorded `roles`, while
the name uses `_role_names(name)`. `role=None` leaves the URI identity unchanged;
other explicit PostgreSQL role names pass through unchanged. Failed connections
propagate without fallback or retry. Callers own connections and must close them.
The gate checks real `session_user` and `current_user` through both inputs, using
`closing`, IDLE connections and identity-only queries. Exact name/OID cleanup
and the frozen CE setup remain unchanged.

## Phase 2 Runtime Contract

The Stage 41 prefix SHA-256 remains
`e5222e1499001f3a734292d8456d2b431fcfcd2a5862952bfcc38137caee34d4`.
`setup_db.py` captures pre-registry, prefix and overlay catalogs separately.
Stage 42 adds exactly two tables and eleven function signatures, replaces
exactly 21 existing definitions, and adds one events capture trigger. It adds
no role, sequence, database/schema privilege or loader entry. Pin columns,
indexes, constraints and immutable/capture triggers are closed-set validated.
The five-parameter completion wrapper and snapshot wrapper remain unchanged.

| Interface | Loaded Phase 2 contract |
| --- | --- |
| global claim | Exact `{effect_id,attempt_no,fence,kind,request,context_revision}` |
| fair claim | Same six plus `root_session_id`; owner-only entry, route gets 42501 |
| CE claim | Original seven-key CE shape, no registry pin |
| strict completion | Seven required parameters, zero defaults; exact attempt/fence/revision pin |
| legacy completion | Five/six parameters remain accepted, including unpinned legacy effects |
| probe / envelope | Eight freshness keys / 21 top-level envelope keys |
| snap / advance | Snap projects the supplied envelope; advance compares the eighth revision key |
| logical judge identity | `v13_effect_envelope` strips registry revision as well as existing watermarks |

Stage 39 fair_claim/fair_driver gates intentionally load the frozen prefix and
retain SIX. The independently loaded overlay gate proves SEVEN and owner/fair
versus route/global identities; changing the prefix-only assertion to SEVEN
would misstate its installed API. This is recorded as S42R-6.

Worker adapter protocol: start IDLE, claim under route (global) or owner (fair),
exact-lookup the pin, read `registry_context(scope, context_revision)`, cache by
the three-part key, recheck both fences and commit. A changed fence rolls back
the claim. Fake IO runs only after commit/IDLE; completion opens a separate
transaction and uses the seven-parameter overload. This is protocol acceptance,
not a new production worker driver or real-provider parity claim.

Strict completion checks token mismatch before revision validation. NULL/negative
revision gives 22023, missing exact pin gives P0001, revision mismatch returns
stale, a terminal exact token replays, and an old exact pin can still settle
accepted after global invalidation. Superseded events remain append-only audit
history; projection, not completion, excludes them from current control.

### Loaded Definitions and Superseded Consumers

Every row below is the effective overlay definition, checked in loaded
`pg_proc`, not an earlier shadowed SQL copy. Original files remain byte-pinned.

| Effective objects | Overridden source / predicate placement |
| --- | --- |
| `v13_claim`, `v13_claim_fair` | fanout / fair_claim CAS and atomic pin |
| six-parameter `v13_complete` | ACL body delegates to shared invoker-security contextual implementation; strict overload delegates with required pin |
| `v13_probe`, `v13_judgment_envelope` | manifest / final filter definition; one-statement fences |
| `v13_snap_of`, `v13_effect_envelope` | resolve / envelope; pure revision projection / watermark removal |
| `v13_advance` | Final plan_arm definition replaces earlier fanout/triage copies; tool-call aggregation, predecessor selection and repair/material/approval/wake queries filter before selection |
| `v13_route` | loop finish query filters machine events, retaining origin_user_seq |
| `v13_canonical_state` | resolve current-turn machine-message branch only; historical audit stays visible |
| `v13_parse` | economy effect-backed resolve/failed retry count; synthetic failure still counts |
| `v13_cap_answer_anchor`, `v13_cap_human_answered` | seam human event/effect/anchor; answered delegates to the filtered anchor |
| `v13_harness_tail_gap`, `v13_tail_gap_cap_exempt` | seam effect and signal evidence |
| `v13_triage_fold_reason`, `v13_triage_block_explore_spawn` | triage signal/cap-human and tool-call queries |
| `v13_closeout` | spawn repair/replan/material/wake/approval receipt evidence |
| `v13_recover_idle`, `v13_scheduler_hint` | govern signal/fingerprint/nudge and unconsumed tool-call count |

`current(pin)` requires equality to both the **global** registry clock and tools
revision, not diagnostic per-scope meta. Unrelated-scope register/retire also
invalidates old pin/advance work. A missing/malformed event anchor with pin
history is false without raising; unpinned legacy, CE and synthetic sources
remain eligible. Exact attempt/fence event mapping survives reclaims. Capture
failure rolls back event, sequence, effect settlement and mapping together.
Tool-call/repair/human payload guards are not widened.

### Phase 2 ACL

Both pin tables are owner-only: no PUBLIC, worker, resolve, recall, route,
spawn_owner or temporary host table/column rights. All added helpers and trigger
functions are owner SECURITY DEFINER with fixed search_path, except completion
wrappers/common implementation, which retain INVOKER security so current_user
authorization is not turned into an owner bypass.

| EXECUTE | route | recall | resolve | spawn_owner | worker / PUBLIC |
| --- | --- | --- | --- | --- | --- |
| fences | yes | yes | yes | - | - |
| pin insert / exact lookup | yes | - | - | - | - |
| pin match | yes | - | - | yes | - |
| event_current | yes | yes | yes | yes | - |
| effect_current | yes | - | yes | - | - |
| strict/common completion | yes | - | - | yes | - |
| registry context | yes | yes | - | - | - |

Recall needs event_current for its canonical read chain (S42R-1). Actual current
spawn needs the same narrow EXECUTE for spawn_owner's
`fork -> prefix_identity -> canonical_state` (S42R-2). Neither receives
`effect_current` or pin-table access. Existing global-claim EXECUTE for the
trusted non-login spawn_owner is preserved from Stage 20, not newly granted;
route is the only ordinary host identity admitted to global claim.

### Lock Evidence and Review

Consumer barriers use exact backend PIDs, `pg_blocking_pids` and ungranted
`pg_locks` entries, not elapsed sleeps as evidence. A registry writer holds the
clock update while waiting on its scope session; another-scope claim/pin commits
without a clock reverse wait. Completion holds session before waiting on effect.
Fair claim holds advisory 13002 before root, root before child, then returns NULL
on effect NOWAIT contention without partial CAS/pin. Mapping failure injection
proves rollback rather than inferring atomicity from a happy-path count.

Govern's handed-off red observation used query-text matching and could select
the observer or another backend. The original gate independently reran exit 0;
the narrow fix captures the actual updater PID and requires a transaction lock
wait. Its exact two edits are byte-proven against the fixed govern baseline by
`r0_source_scope`; all other govern test bytes remain frozen (S42R-3).

Oracle review was read via `oracle_chat_log` (`untitled-chat-9347AA`). Its
spawn_owner execution, exact human payload and function-ACL mutation suggestions
are exercised. Trigger/FK catalog strings install successfully on the actual
PostgreSQL 18.4 catalog; the superseded source fixture is pinned, with legacy
coverage separate. Prefix SIX versus overlay SEVEN is documented above. No
second review, real provider, commit or push is claimed.

## Gate Manifest (Phase 2: Original 50 Plus Consumer)

Each row is run independently with `UV_FROZEN=1 uv run python`; restore
`v13/pi_parity/traces/pg.jsonl` bytes and mode after every row. The exit column
is the expected contract, not a substitute for the current receipt below.
Rows 1-50 retain the Stage 41 order; row 51 is the independent consumer gate.

### Stage 41 Historical Result (2026-10-18)

The final post-P1 precommit sequence passed all 50 items: 48 scripts exited 0 and the
two additional goal_supervisor probes exited their expected 1/2. Every item
ran independently and restored `v13/pi_parity/traces/pg.jsonl` byte-for-byte
and with its original mode. Raw commands, exit codes, durations, and logs:
`prompt-exports/w4-registry-precommit4-p1-20261018/results.json` (ignored evidence).
Each table row is the exact argument to `UV_FROZEN=1 uv run python`.
The same ordered manifest must be replayed after commit; its actual results
belong in the final closeout report, not prefilled as successful here.

| # | Path and Arguments | Expected Exit |
| --- | --- | --- |
| 1 | `v13/acl/test_acl.py` | 0 |
| 2 | `v13/attention/test_attention.py` | 0 |
| 3 | `v13/catalog/test_catalog.py` | 0 |
| 4 | `v13/ce_run/test_ce_run.py` | 0 |
| 5 | `v13/characterize/test_characterize.py` | 0 |
| 6 | `v13/chunks/test_chunks.py` | 0 |
| 7 | `v13/control/test_control.py` | 0 |
| 8 | `v13/economy/test_economy.py` | 0 |
| 9 | `v13/envelope/test_envelope.py` | 0 |
| 10 | `v13/fair_claim/test_fair_claim.py` | 0 |
| 11 | `v13/fair_driver/test_fair_driver.py` | 0 |
| 12 | `v13/fanout/test_fanout.py` | 0 |
| 13 | `v13/filter/test_filter.py` | 0 |
| 14 | `v13/frontier_gap/test_frontier_gap.py` | 0 |
| 15 | `v13/goal_supervise/test_goal_supervise.py` | 0 |
| 16 | `v13/goal_supervisor/test_goal_supervisor.py` | 0 |
| 17 | `v13/goal_supervisor/test_goal_supervisor.py --unattended-continuation` | 1 |
| 18 | `v13/goal_supervisor/test_goal_supervisor.py bad-args` | 2 |
| 19 | `v13/govern/test_govern.py` | 0 |
| 20 | `v13/handoff/test_handoff.py` | 0 |
| 21 | `v13/loop/test_loop.py` | 0 |
| 22 | `v13/loop_driver/test_loop_driver.py` | 0 |
| 23 | `v13/manifest/test_manifest.py` | 0 |
| 24 | `v13/memory/test_memory.py` | 0 |
| 25 | `v13/mgraph/test_mgraph.py` | 0 |
| 26 | `v13/mgraph/test_stannum_usage.py` | 0 |
| 27 | `v13/mgraph_assembly/test_mgraph_assembly.py` | 0 |
| 28 | `v13/observe/test_observe.py` | 0 |
| 29 | `v13/periphery/test_periphery.py` | 0 |
| 30 | `v13/pi_parity/test_pi_parity.py` | 0 |
| 31 | `v13/pi_ports/test_pi_ports.py` | 0 |
| 32 | `v13/plan_arm/test_plan_arm.py` | 0 |
| 33 | `v13/plan_contract/test_plan_contract.py` | 0 |
| 34 | `v13/plan_read/test_plan_read.py` | 0 |
| 35 | `v13/quota_window/test_quota_window.py` | 0 |
| 36 | `v13/read_tools/test_read_tools.py` | 0 |
| 37 | `v13/real_chain/test_real_chain.py` | 0 |
| 38 | `v13/recall/test_recall.py` | 0 |
| 39 | `v13/registry/test_registry.py` | 0 |
| 40 | `v13/resolve/test_resolve.py` | 0 |
| 41 | `v13/schema/test_schema.py` | 0 |
| 42 | `v13/seam/test_seam.py` | 0 |
| 43 | `v13/should_run/test_should_run.py` | 0 |
| 44 | `v13/spawn/test_spawn.py` | 0 |
| 45 | `v13/summary/test_summary.py` | 0 |
| 46 | `v13/triage/test_triage.py` | 0 |
| 47 | `v13/twophase/test_twophase.py` | 0 |
| 48 | `v13/workflow_bind/test_workflow_bind.py` | 0 |
| 49 | `v13/workspace_admit/test_workspace_admit.py` | 0 |
| 50 | `v13/workspace_exec/test_workspace_exec.py` | 0 |
| 51 | `v13/registry/test_consumer.py` | 0 |

After the P1 identity fix, registry independently passed 16/16 groups, 481
checks, zero independent-case failures (`UV_FROZEN=1 uv run python
v13/registry/test_registry.py`, exit 0). In plan section 9.2 order the group
counts are `49/3/9/4/12/21/4/6/30/12/16/135/130/8/31/11`.
The final full-sequence counts are:
CE passed 16/16 groups and 665 checks; plan_arm passed 104, fair_claim 137,
goal_supervisor 74. read_tools passed E4, including a separate nested registry
run (16/16, 481). These are distinct runs, not replacement evidence.
The pre-P1 precommit3 sequence (16/16, 473) remains historical evidence only:
`prompt-exports/w4-registry-precommit3-20261018/results.json`.

Historical attempts remain recorded: the first sequence stopped at item 16
on cached-only registry discovery; the Oracle-approved exact four-file
exception and 13 pure in-memory cases corrected it. The second sequence
stopped at item 17 because the runner incorrectly required the FAIL marker to
be the final line; the actual exit 1 and trailing ask_user refusal were valid.
Only the ignored runner was corrected, then all 50 items restarted from 1.
Evidence: `prompt-exports/w4-registry-precommit-20261018/` and
`prompt-exports/w4-registry-precommit2-20261018/`.

PI_PARITY_REQUIRE_ALL was not enabled. Default parity exited 0 while reporting
`not_run/toolchain_absent planes=node_modules`, also in E4; no all-plane/strict
claim is made. The gate uses local PostgreSQL, fake data, exact-name/OID cleanup,
import-safe helpers, and lock barriers without sleeps. Defensive chain-cycle
coverage is static only; cap behavior is exercised. Consumer-side advance,
claim pinning, and framework DB worker-parity remained outside Stage 41.

### Historical Phase 2 Final Sequence Attempt (2026-10-19): RED

After the goal_supervisor frozen-path correction, the final sequential run was
`UV_FROZEN=1 uv run python prompt-exports/w5-phase2-runner.py w5-phase2-final-20261019`.
Items 1-29 matched their contracts: 27 exited 0, item 17 exited the expected 1
with FAIL/ask_user refusal, and item 18 exited the expected 2 with usage before
DB setup. Item 30 exited an unexpected 1 after 480.16 seconds, so items 31-51
were NOT RUN. This was a compiler failure, not the runner's 600-second timeout.
The runner exited 1. No additional round or external dependency repair followed.

Evidence (ignored local artifacts):
`prompt-exports/w5-phase2-final-20261019/results.json`, `manifest.json`, `head.txt`
and numbered per-item logs in the same directory. The receipt contains exactly
30 executed items; NOT RUN below is absence of execution, not an exit code.

| # / Gate / Actual Exit | # / Gate / Actual Exit | # / Gate / Actual Exit |
| --- | --- | --- |
| 1 acl: `0` | 18 goal_supervisor bad-args: `2` (expected) | 35 quota_window: NOT RUN |
| 2 attention: `0` | 19 govern: `0` | 36 read_tools: NOT RUN |
| 3 catalog: `0` | 20 handoff: `0` | 37 real_chain: NOT RUN |
| 4 ce_run: `0` | 21 loop: `0` | 38 recall: NOT RUN |
| 5 characterize: `0` | 22 loop_driver: `0` | 39 registry: NOT RUN |
| 6 chunks: `0` | 23 manifest: `0` | 40 resolve: NOT RUN |
| 7 control: `0` | 24 memory: `0` | 41 schema: NOT RUN |
| 8 economy: `0` | 25 mgraph: `0` | 42 seam: NOT RUN |
| 9 envelope: `0` | 26 mgraph/stannum_usage: `0` | 43 should_run: NOT RUN |
| 10 fair_claim: `0` | 27 mgraph_assembly: `0` | 44 spawn: NOT RUN |
| 11 fair_driver: `0` | 28 observe: `0` | 45 summary: NOT RUN |
| 12 fanout: `0` | 29 periphery: `0` | 46 triage: NOT RUN |
| 13 filter: `0` | 30 pi_parity: **`1` (unexpected)** | 47 twophase: NOT RUN |
| 14 frontier_gap: `0` | 31 pi_ports: NOT RUN | 48 workflow_bind: NOT RUN |
| 15 goal_supervise: `0` | 32 plan_arm: NOT RUN | 49 workspace_admit: NOT RUN |
| 16 goal_supervisor: `0` | 33 plan_contract: NOT RUN | 50 workspace_exec: NOT RUN |
| 17 goal_supervisor --unattended-continuation: `1` (expected) | 34 plan_read: NOT RUN | 51 registry/consumer: NOT RUN |

The current external `/Users/wxl/Projects/PiSwift` HEAD was read-only observed as
`a73c391ce1d891b7b6f8f37a8508f184a31703e3`. The frozen driver fails at
`main.swift:233` because `createAgentSession` now throws but the call lacks
`try`, and at `main.swift:310` because `toolExecutionEnd` now has five tuple
members instead of four. PostgreSQL/PIG assertions reached PASS before this
failure, but that does not make parity green. Neither PiSwift nor the frozen
driver was changed to bypass it (S42R-9).

Every executed item, including the failed item 30, has `trace_restored=true`:
`v13/pi_parity/traces/pg.jsonl` SHA-256
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`, mode `0644`.
There is no tracked trace diff. No trace-restoration claim is made for unrun items.

Distinct independent evidence: consumer **289 checks, exit 0**
(`/tmp/v99-consumer-final.log`); registry **16/16 groups, 485 checks, zero
independent failures, exit 0** (`/tmp/v99-registry-final2.log`). Seven static
entrances (fair_claim, fair_driver, frontier_gap, goal_supervise,
goal_supervisor, workspace_admit, plan_arm) also passed independently
(`/tmp/v99-all-static.log`). In the final sequence, goal_supervisor passed 74,
govern 228, CE 665, fair_claim 137, fair_driver 42, frontier_gap 59,
goal_supervise 172 and handoff 240. The frozen goal_supervisor entrance and the
exact govern correction therefore showed no conflict in this run.

**Precommit conditions are NOT met:** full 51-item acceptance is red and 21
items remain unrun in the final sequence. W5/W6 acceptance is not complete;
documentation records the result rather than declaring the milestone done.
No staging, commit, push or post-commit verification was performed.

### Historical Compatibility Preflight (2026-10-19): RED

On the user's continuation, read-only branch/log/status inspection found the
active PiSwift checkout clean on main at `a73c391`. There is no retained old
local branch; the retained tag `v0.87.1` points to
`bfccb32f2d6318b75519b2c1790e7e66e133f5da`, the documented historical driver
baseline. Its SDK is `async` without `throws`, and `toolExecutionEnd` has four
members. The older remote branches are not the version-0.87.1 contract baseline.
A detached worktree was created at
`/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift`; active main was not switched.

Both frozen Package.swift files hardcode `/Users/wxl/Projects/PiSwift`; no
environment override exists. SwiftPM rejected a local mirror for the filesystem
dependency. An ignored PATH wrapper instead invokes the real `/usr/bin/swift`
with its existing `--package-path` option against isolated package copies.
Their Sources are byte-identical; the only copied manifest delta is the local
PiSwift dependency path. No tracked driver/manifest or external source changed.
Wrapper, source hashes, invocation log and before/after checkout evidence are
under `prompt-exports/w5-piswift-compat/`.

Preflight `pi_parity` exited **1**: SwiftPM attempted to update
`https://github.com/MacPaw/OpenAI.git` and failed with
`LibreSSL SSL_connect: SSL_ERROR_SYSCALL` to github.com:443. This failure occurs
before the old-version driver can be proven to compile/run; API inspection is
not a passing gate. Per the user's stop-on-unexpected-failure instruction,
ports was NOT RUN and the new full 51-item sequence was NOT STARTED. No retry,
network/dependency workaround or resolution-policy change was made.
`preflight-results.json` records trace restoration with the same SHA-256/mode
as above. `environment-after.json` proves active HEAD/status, clean detached
worktree and frozen source/manifest bytes unchanged. The earlier 30-item final
receipt remains historical, not combined with this preflight. S42R-10 records
the then-current blocker; at that point W5/W6 acceptance and precommit
conditions remained unmet. The user's subsequent offline investigation request
and successful new sequence are recorded below.

### Offline Isolation Acceptance (2026-10-19): PASS

S42R-11 closes the environment blocker without modifying the active checkout,
frozen driver, original manifests or external source. The old tag's version-3
Package.resolved contains 25 pins. The OpenAI pin is
`4ed3ea99ff9dfd2a760509ddb31020f4b153ef93`; the active checkout cache has that
exact HEAD and `.build/repositories/OpenAI-f436e9d2` contains the commit.
Existing pg-agent `.piswift-build-parity` and `.piswift-build` caches were
sufficient; copying the active cache was unnecessary. Copying the old lock to
each isolated package and adding `--disable-automatic-resolution --skip-update`
avoided the failing update. Initial offline release build exited 0 in 472.93s.

Local environment (retained for review, ignored artifacts are not committed):

- Active `/Users/wxl/Projects/PiSwift`: clean main at
  `a73c391ce1d891b7b6f8f37a8508f184a31703e3`, unchanged before/after.
- Detached `/tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift`: clean tag v0.87.1 at
  `bfccb32f2d6318b75519b2c1790e7e66e133f5da`; never switched the active checkout.
- `prompt-exports/w5-piswift-compat/prepare.py` made isolated package copies;
  only their dependency path differs. `bin/swift` checks copied Sources against
  the frozen originals on every build and calls real `/usr/bin/swift` with
  `--package-path`; it does not synthesize a binary or bypass a gate assertion.
- `swift-invocations.jsonl`, `offline-build1.log`, `offline-results.json`,
  `offline-pi_parity.log`, `offline-pi_ports.log`, environment-before/after JSON
  and `verify.py` preserve commands, preflight results and protection checks.

Reproduction in this retained local environment, from the pg-agent root:

```bash
# Already-created detached worktree; no checkout/switch of active PiSwift.
# Creation command was:
# git -C /Users/wxl/Projects/PiSwift worktree add --detach /tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift v0.87.1
cp /tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift/Package.resolved prompt-exports/w5-piswift-compat/piswift_driver/Package.resolved
cp /tmp/pg-agent-w5-PiSwift-v0.87.1/PiSwift/Package.resolved prompt-exports/w5-piswift-compat/piswift_port/Package.resolved
export PATH="$PWD/prompt-exports/w5-piswift-compat/bin:$PATH"
export W5_SWIFT_OFFLINE=1 UV_FROZEN=1
# Use fresh labels/receipt directories to preserve this run's evidence.
uv run python prompt-exports/w5-piswift-compat/preflight.py --label offline-replay
uv run python prompt-exports/w5-phase2-runner.py w5-phase2-offline51-replay
uv run python prompt-exports/w5-piswift-compat/verify.py
```

Actual preflight ran parity then ports, both exit 0 and trace restored. Then
`PATH="$PWD/prompt-exports/w5-piswift-compat/bin:$PATH" W5_SWIFT_OFFLINE=1 UV_FROZEN=1 uv run python prompt-exports/w5-phase2-runner.py w5-phase2-offline51-20261019`
ran the full manifest from item 1 once, strictly serial, without a failed gate.
Runner exit 0; 51 receipt rows, all `valid=true` and `trace_restored=true`.
Total item duration 951.81s; no historical attempt is combined into this result.

Receipt: `prompt-exports/w5-phase2-offline51-20261019/results.json`; same directory
contains exact manifest, HEAD and 51 numbered logs. Actual exits for every item:

| # / Gate / Actual Exit | # / Gate / Actual Exit | # / Gate / Actual Exit |
| --- | --- | --- |
| 1 acl: `0` | 18 goal_supervisor bad-args: `2` (expected) | 35 quota_window: `0` |
| 2 attention: `0` | 19 govern: `0` | 36 read_tools: `0` |
| 3 catalog: `0` | 20 handoff: `0` | 37 real_chain: `0` |
| 4 ce_run: `0` | 21 loop: `0` | 38 recall: `0` |
| 5 characterize: `0` | 22 loop_driver: `0` | 39 registry: `0` |
| 6 chunks: `0` | 23 manifest: `0` | 40 resolve: `0` |
| 7 control: `0` | 24 memory: `0` | 41 schema: `0` |
| 8 economy: `0` | 25 mgraph: `0` | 42 seam: `0` |
| 9 envelope: `0` | 26 mgraph/stannum_usage: `0` | 43 should_run: `0` |
| 10 fair_claim: `0` | 27 mgraph_assembly: `0` | 44 spawn: `0` |
| 11 fair_driver: `0` | 28 observe: `0` | 45 summary: `0` |
| 12 fanout: `0` | 29 periphery: `0` | 46 triage: `0` |
| 13 filter: `0` | 30 pi_parity: `0` | 47 twophase: `0` |
| 14 frontier_gap: `0` | 31 pi_ports: `0` | 48 workflow_bind: `0` |
| 15 goal_supervise: `0` | 32 plan_arm: `0` | 49 workspace_admit: `0` |
| 16 goal_supervisor: `0` | 33 plan_contract: `0` | 50 workspace_exec: `0` |
| 17 goal_supervisor --unattended-continuation: `1` (expected) | 34 plan_read: `0` | 51 registry/consumer: `0` |

In this sequence registry passed 16/16 groups, 485 checks, zero independent
failures; consumer passed 289 checks; govern 228, goal_supervisor 74, CE 665,
fair_claim 137, fair_driver 42, plan_arm 104, quota_window 226 passed. read_tools
E4 passed in 487.54s, including its nested registry and parity/ports runs.
Goal_supervisor's frozen entrance and exact govern correction show no conflict.
The consumer's plan-section-5 worker protocol, real lock barriers, event
atomicity/malformed, actual current/superseded spawn, dual-connection snapshot,
freshness and catalog closure assertions all passed in item 51.

Trace final SHA-256 is
`3496c6a4c98937a009fed3144d0cdcac84dd1e788fd2854769cc9aca705d933a`, mode 0644,
with no tracked trace diff. Active PiSwift and detached worktree remain clean;
original frozen Sources/manifests are hash-identical. Default parity still
reports `not_run/toolchain_absent planes=node_modules`; PI_PARITY_REQUIRE_ALL
was not enabled, so no all-plane claim is made. No real provider was used.

**W5/W6 test and documentation preconditions are met.** This closeout agent's
handoff scope excludes staging, commit and push. The original instruction quoted
in plan section 7 is a coordinator-to-closeout-agent boundary, not a user waiver
of AGENTS' task-wide commit/push requirement. Parent coordinator review,
path/credential staging inspection, commit, clean-tree replay and v99 push
remain pending; this is not a claim of a committed milestone.
