# v24 S2 capability plane — final

Authority: [S2 plan](../../docs/plans/v24-s2-capability-2026-10-23.md). **S2 is complete: W1–W7 implemented, all five gates exit 0, closeout artifacts present.** The S3 closeout corrections below reflect the current code.

## Layout and load

```text
00_schema → 10_schema → 20_triggers → 30_advance → 40_interpreters
→ 45_capability → 50_permissions
```

`45_capability.sql` holds the read-only `resolve`, the `fiber_control`/`dispose` wrappers, the two `check_policy` helpers, the no-op receipt builder and `u_effects_reconcile`. The closure CTE, command dispatch and delta applier were extended **in place** in `30_advance.sql` / `40_interpreters.sql` (D-S2-11): duplicating those functions in 45 would create two definitions that drift. No new tables, no new columns.

## `resolve` (C8)

`v24.resolve(scope_id, keys[])` was `STABLE` / `SECURITY INVOKER` in S2; S3 W1 changed it to `STABLE` / `SECURITY DEFINER` because protocol roles have zero table privileges (the S2 defect was that service-role invocation would raise `42501`; S2 had only exercised it as migration owner). It returns exactly B.3's six columns:

```text
(key, slot_id, provider_episode_id, descriptor, descriptor_digest, live)
```

- Input order preserved; one row per key; unresolved keys are `live=false` with NULL columns.
- Realm routing is leaf-first along `route_path`: deepest explicit `realm_routes[key]`, else deepest non-empty `default_realm`, else unresolved. **No cross-realm fallback.**
- Live predicate: `slots.released_at IS NULL AND slots.withdrawn_at IS NULL AND episodes.state='active' AND fibers.disposed_at IS NULL AND provider scope.close_requested_at IS NULL`.
- >256 keys → `22023`; empty array → empty result; unknown scope → all `live=false`; writes nothing.

## `fiber_control` (C10)

`v24.fiber_control(fiber_id, action, expected_control_seq, request_key)` is `SECURITY INVOKER`; it only builds the `command_fiber_control` outcome and calls `advance`. CAS mismatch is W1 `stale_generation`.

One advance executes **one bounded reconcile stage**:

| action | behavior |
|---|---|
| `on` / `retry` toward on | activation: episode (`epoch=max+1`) → contribution slots → activation pins → switch `current_episode_id` → settle or born-settle `fiber_reconcile` |
| `off` | stage A: `active→retiring`, `retire_started_at`, withdraw this generation's slots; stage B if barriers clear: release consumer pins, release slots, close episode, clear current |
| already satisfied | no-op receipt, zero domain diff |
| `retry` without failure | no-op |
| direction flip during cleanup | intent only (`want_on`/`control_seq`), ready reconcile kept |

Activation failures (`install_not_ready`, `scope_closed`, `dependency_unresolved`, `provide_conflict`) are W1 receipts with `failure_seq`/`failure` on the fiber and **no** episode/slot/pin.

Stage-B barriers: any live external activation pin on this episode's slots; any child install not `disposed` (by the historical owner columns); any unsettled `host_prepare`/`host_release` for this install. A barrier commits stage A, writes nothing in stage B and returns `deferred`; the ready reconcile is driven again by a same-direction command with a new key (D-S2-3).

`check_policy` v1 is the closed pure-data predicate `{"v":1,"op":"equals","path":[...],"value":<scalar>}`. Invalid shapes are rejected at install admission; a false predicate is `dependency_unresolved` at activation.

## Install fiber and child admission (C9)

Every new install creates exactly one inactive fiber:

```text
fiber_id = md5(install_id::text || ':fiber')::uuid
want_on=false, current_episode_id=NULL, control_seq=0, next_contribution_seq=0
```

The fiber id is deterministic, so the existing `emitted` ABI is unchanged. Child admission derives `owner_episode_id` only from `fibers.current_episode_id` and writes the historical pair; refusals: `already_terminal` (disposed), `owner_closing` (`want_on=false`), `install_not_ready` (no active current episode), `invalid_args` (nonexistent owner, checked before closure discovery). E1→E2 leaves old installs and their owner columns untouched.

## `dispose` + `host_release` (C11)

`v24.dispose(install_id, request_key)` is `SECURITY INVOKER`. It persists `dispose_pending` and `dispose_effect`, then checks:

1. every episode of the install is `closed` and `current_episode_id IS NULL`;
2. every slot is released;
3. every child install (historical owner columns) is `disposed`;
4. no `ready`/`claimed` host effect references the install.

When clear it tombstones the install's own fibers (`disposed_at`, `want_on=false`) and emits one `host_release` (`effect_id = md5(command_effect_id || ':host_release:0')`, reservation `v24:host_release:<effect_id>`). `preparing`/`prepare_unknown` stop at `dispose_pending`; inspect convergence is S5. A `disposed` install answers new keys with `already_terminal`; the original key replays.

`host_release` settlement: success → `disposed` + `disposed_at` + `install_disposed`; failure/unknown → state stays `dispose_pending` (failure is visible on the effect). While `dispose_pending`, a `host_prepare` receipt is refused as `receipt_conflict`.

## ACL

At S2 close, `advance` was the only `SECURITY DEFINER` function. S3 W1 adds the read-only DEFINER allowlist (`resolve`, `poll`, `wait_check`, `run_owner`, `run_projection`); `run_owner`/`run_projection` are internal and have no protocol-role EXECUTE grants; `fiber_control` and `dispose` remain INVOKER; EXECUTE is granted to `v24_admin`, `v24_service`, `v24_operator` (plus the existing entry points). `check_policy_valid`/`check_policy_ok`/`capability_noop` are ungranted helpers used by the DEFINER. The protocol roles still hold zero table privileges; `test_g1.py` re-runs the exact EXECUTE set and the 30 DML refusals per role.

## Actual verification — 2026-10-23

Run from `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` on branch `v24` (PostgreSQL 18.4, psycopg2 2.9.12):

| command | exit code |
|---|---:|
| `uv run python v24/load.py` | 0 |
| `uv run python v24/s1/setup_db.py --self-check` | 0 |
| `uv run python v24/s1/test_ddl.py` | 0 |
| `uv run python v24/s1/test_g1.py` | 0 |
| `uv run python v24/s2/test_g3a.py` | 0 |

`test_g3a.py` groups: A1–A6 resolver, W2a–W2c closure/reconcile infrastructure, J install admission, B/C/D/E activation and failure atomicity, F/G deactivation barrier and E1→E2, K dispose, L ACL/static.

Historical failures and their corrections are recorded in the matrix §0.1 and the ledger §4; no assertion was deleted or weakened.

On 2026-10-24 the five commands above plus `uv run python v24/s3/test_g2.py` were rerun serially and all exited 0 (matrix §0). The S2 A1 console label still says INVOKER; the current catalog assertion and S3 G2a-0 verify DEFINER and real protocol-role reads.

## Boundaries (not covered by S2)

- S2 proves the activation-pin half. S3 G3b-1…5 passed on 2026-10-24, completing G3 (G3a+G3b); full claimed/unknown settlement release remains unverified / S4. G3b-4 is sequential evidence; G3b-5 proves start/off serialization with two connections and lock barriers.
- `inspect_resource` convergence is S5; S2 only stops `prepare_unknown` at `dispose_pending`.
- Owner cascade, scope close, recursive children barriers and the full dispose closure are S5; S2 does leaf dispose only.
- S2 provided `resolve`; S3 adds the run projection read APIs `poll` and `wait_check`.
- S3 `start` now writes `runs` with `revision=1`; advance increments revision on visible-state changes. It is no longer constant 0.
- FakeHost is in-process and not a transport proof; recovery covers two journal windows only.
- Current concurrency evidence includes G exclusivity/first-lock, the activation-pin barrier, and S3 G3b-5 start/off lock barriers; the full matrix remains S7/G6.
