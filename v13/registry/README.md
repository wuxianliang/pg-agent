# Stage 41: Spacetime Registry

## Scope

A pure registration plane: three tables and eight functions, appended after
Stage 40. `service`, `tool_profile`, and `prompt_section` are the complete kind
set. There is no consumer-side integration, worker pinning enforcement, claim
key addition, eighth advance probe key, superseded absorption, provider IO,
notification/waiter surface, TTL, or GC. Existing CE functions are neither
called nor replaced; CE generation fields retain their existing meaning.

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
returns current tools and their current `v13_tools_meta.revision`. A future
consumer/cache must pin `(scope, registry revision, tools_revision)`, not just
registry revision. The second scalar is already exposed and hashed, but claim
contracts and enforced dual-scalar pinning are deferred to design section 11.5.

Registry events intentionally advance `v13_probe.session_version` and
`max_event_seq`; an in-flight advance becomes stale and reparses. This is a
safe consequence of the changed world, not a CE interaction or regression.

## ACL Matrix

All functions are SECURITY DEFINER with fixed `search_path = pg_catalog, public`
and a trusted superuser owner. No host role has CREATE on public or database
TEMPORARY in the isolated deployment.

| Object/access | PUBLIC | worker | resolve | recall | route |
| --- | --- | --- | --- | --- | --- |
| registrations/meta SELECT | - | - | - | SELECT | SELECT |
| registrations/meta DML | - | - | - | - | - |
| clock, all access | - | - | - | - | - |
| register/retire EXECUTE | - | - | - | - | EXECUTE |
| scope_chain/context EXECUTE | - | - | - | EXECUTE | EXECUTE |
| caller/read_ok/chain_inner/frozen EXECUTE | - | - | - | - | - |

`resolve` is intentionally excluded from every registry function (42501), a
narrower boundary than older three-role read surfaces. With NULL actor, real
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

## Gate Commands and Results (2026-10-18)

The final post-P1 precommit sequence passed all 50 items: 48 scripts exited 0 and the
two additional goal_supervisor probes exited their expected 1/2. Every item
ran independently and restored `v13/pi_parity/traces/pg.jsonl` byte-for-byte
and with its original mode. Raw commands, exit codes, durations, and logs:
`prompt-exports/w4-registry-precommit4-p1-20261018/results.json` (ignored evidence).
Each table row is the exact argument to `UV_FROZEN=1 uv run python`.
The same ordered manifest must be replayed after commit; its actual results
belong in the final closeout report, not prefilled as successful here.

| # | Path and Arguments | Precommit Exit |
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
claim pinning, and framework DB worker-parity remain outside this milestone.
