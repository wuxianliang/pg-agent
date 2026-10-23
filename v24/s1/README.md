# v24 S1 kernel — W6 final

Authority: [S1 plan](../../docs/plans/v24-s1-kernel-2026-10-23.md) §§4.13.4, 4.14.2–4.14.4, 4.16, 4.18–4.19, 5. **S1 is complete: W1–W6 implemented, all four gates exit 0, closeout artifacts present.** Commit/push follows the repository's milestone rule; this file is written before that commit.

## Layout and load

`v24/load.py` holds the canonical six-file manifest and loads only an active prefix, in order:

```text
00_schema.sql → 10_schema.sql → 20_triggers.sql
→ 30_advance.sql → 40_interpreters.sql → 50_permissions.sql
```

The loader rejects non-prefix manifests, symlinks, unregistered files, and directories posing as SQL. `50_permissions.sql` must stay last: it grants EXECUTE only after every entry point exists, and its fail-closed `DO` block checks function owner, `search_path`, and PUBLIC EXECUTE after the grants.

`setup_db.py` creates a uniquely named database from `template0`, loads the prefix in one transaction as `v24_owner`, verifies the catalog closed set, and drops database then roles after OID re-verification. Roles are two layers: four `NOLOGIN` group roles (`v24_owner`, `v24_admin`, `v24_service`, `v24_operator`) plus per-fixture LOGIN roles that are members of exactly one group. Tests connect as the LOGIN role, so `session_user` is a real login identity and `SET ROLE` is observable.

## Identity and ACL

`advance` is the only `SECURITY DEFINER` function and the only write authority. It runs as `v24_owner`, which owns the schema and every object and therefore keeps the table DML that powers the DEFINER. The three protocol roles hold **zero table privileges**; they reach domain state only through the entry points.

| role | EXECUTE | advance-internal matrix |
|---|---|---|
| `v24_owner` | none via protocol (migration/login identity only) | not a protocol caller |
| `v24_admin` | `advance`, `scope_control`, four pure helpers | `command_scope_control` + `action=create_root` only; no claim/settlement, no other command |
| `v24_service` | `advance`, `install`, `scope_control`, four pure helpers | any command except root creation; claim + host settlement |
| `v24_operator` | same as service | any command except root creation; **no** claim/settlement |

Identity is `v24.principal_id(session_user)`, never `current_user` or `current_setting('role')`. `SET ROLE` therefore changes the ACL identity but not the principal. `claim_owner` is `session_user::text`.

`50_permissions.sql` revokes schema/table/function privileges from `PUBLIC` and the three protocol roles, revokes the global `PUBLIC EXECUTE` default, then grants only the entry points and the four pure helpers (`canonical_json`, `effect_id_for`, `principal_id`, `error_v1`; wrappers are INVOKER and their callers need these). It never revokes from `v24_owner`: doing so makes the DEFINER's writes fail with `permission denied for table`.

## Command and `scope_control`

`scope_control(action, parent_scope_id, realm_routes, default_realm, request_key)` builds the normal command outcome and calls `advance`. It derives `effect_id` from `(principal, request_key, 'command_scope_control')`; `advance` asserts the passed id equals the derivation before any replay lookup.

- `create_root`: `route_path=[id]`, `root_id=id`, `parent_id IS NULL`; only `v24_admin`.
- `create_child`: `route_path = parent.route_path || new_id`, inherits `root_id`; rejected as W1 `scope_closed` if the parent has `close_requested_at`.
- `close`: writes only `close_requested_at`; `closed_at` stays NULL (draining belongs to S5).

The command delta is the frozen §4.14.4 shape: `domain.insert/update`, `effect`, `request.response`, `events`, `successors`, `error`, with preflight limits (declared tables only, ≤16 rows, ≤64 events, ≤16 successors) and a fixed apply order. Rejections are W0 (no rows) except the stable W1 kinds (`scope_closed`, `install_identity_conflict`), whose failed effect and request row commit together. `invalid_outcome` is a preflight refusal in S1 and writes nothing; the auditable-failure form required by design L279 belongs to S3 and is recorded as ledger I7.

## Install and FakeHost

`install(scope_id, owner_fiber_id, manifest_bytes, artifact_digest, request_key)` constructs the normal command outcome. The payload encodes original UTF-8 manifest bytes as base64 and artifact digest as PostgreSQL bytea hex (`\x...`); `manifest.adapter_digest` uses the same hex format. Identity/version/requires/provides/adapter come from parsing those bytes. `manifest_digest` hashes the original bytes, so even a whitespace change is a different digest.

Root installs require NULL owner. Non-null owners are rejected as W0 `invalid_args` before closure discovery, including nonexistent owners. Duplicate identity/version with identical manifest/artifact digests returns the existing install in `emitted`, with its own command receipt; different digests produce a stable W1 `install_identity_conflict` receipt. Closing scopes produce W1 `scope_closed`.

Preparation rule: nonempty provides or nonzero-length artifact bytes require `preparing`; empty provides plus empty artifact bytes mean declaration-only `installed`. Host effect ordinal is 0; its id is `md5(command_effect_id || ':host_prepare:0')::uuid`, and reservation is `v24:host_prepare:<host_effect_id>`. No new protocol code or domain schema column is introduced.

The fixture owns `v24_fake.journal`, separate from the ten v24 tables. Its schema assertion accepts exactly `{v24, v24_fake}` beyond PostgreSQL built-ins and template public schema, and tests reject a third application schema. FakeHost receives existing connections and creates no sockets. It requires an idle worker and an autocommit journal connection, verifies the claim through committed visibility, journals before simulated IO, and returns a receipt before settlement advance. Scripted outcomes are succeed/fail/unknown/crash_before_journal/crash_after_journal. Reservation retry reuses a completed journal result; an unfinished journal returns unknown without another simulated operation. Recovery beyond this fixture remains out of S1 scope.

## Settlement-mode contract

`validate_and_apply_delta` infers mode exclusively from `p_outcome.class`: `success`, `failure`, or `unknown` selects settlement; `command` keeps command admission. The delta does not select its own mode. The W5 branch delegates to the INVOKER `validate_and_apply_install_delta`; only `advance` is SECURITY DEFINER. Other settlement effect kinds still raise SQLSTATE `0A000`.

Settlement resolves kind, scope and install from the stored effect, consumes only `domain.update.installs` with the matching install key and the exact target state, requires the install in the locked closure and `preparing`, and rejects request rows or domain inserts. `effect.status` must match the class, and `effect.outcome` must equal the exact received outcome. The settled receipt is stored unchanged for the existing S2 replay check (which excludes transport `receipt_key`).

| class | install state | effect status | resource_quiesced_at |
|---|---|---|---|
| success | installed | succeeded | now() |
| failure | prepare_failed | failed | now() |
| unknown | prepare_unknown | unknown | NULL |

Application order is install transition → existing effect UPDATE → events. It sets `outcome` and `settled_at`, clears both `claim_owner` and `lease_until`, preserves attempt/fence and effect identity/request fields, and inserts no request. All delta checks precede DML; SQL/trigger errors roll back T2. Unknown rejects any successor at preflight. S1 host_prepare emits no successors for success/failure either. Each accepted settlement emits one `host_prepare_settled` install event; replay emits none.

## Implementation disclosures

- `f_effects_parent` and `f_events_effect` are DEFERRABLE (the plan listed plain FKs); `to_jsonb`-cycle closure is asserted at COMMIT.
- `c_installs_ident` was renamed `c_installs_identity_len` to avoid colliding with `u_installs_ident`.
- The fixture's schema closed set is `{v24, v24_fake}`; a third application schema is still rejected.
- G1-A permits the named INVOKER `validate_and_apply_install_delta` to contain `UPDATE v24.effects`; `prosecdef=true` remains exactly `{v24.advance}`, no grant exists on the helper, and only `advance` contains `pg_advisory_xact_lock`. This keeps the single-write-authority claim while sharing delta application with W5.
- Settlement mode is inferred from `p_outcome.class`; the delta never selects its own execution domain.
- Full ledger: [`docs/reviews/v24-deviation-ledger-2026-10-23.md`](../../docs/reviews/v24-deviation-ledger-2026-10-23.md).

## Actual verification — 2026-10-23

Run from `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` on branch `v24` (PostgreSQL 18.4, psycopg2 2.9.12):

| command | exit code |
|---|---:|
| `uv run python v24/load.py` | 0 |
| `uv run python v24/s1/setup_db.py --self-check` | 0 |
| `uv run python v24/s1/test_ddl.py` | 0 |
| `uv run python v24/s1/test_g1.py` | 0 |

Historical failures, retained per the ledger rule:

| run | failure | correction |
|---|---|---|
| W5 first | `test_g1.py` = 1: `AmbiguousColumn: column reference "manifest" is ambiguous` | renamed the local to `parsed_manifest`; gate 0 |
| W6 first | ACL probe expected `42501`, got `428C9` | UPDATE probe now skips identity/generated columns; gate 0 |
| W6 second | `permission denied for table effects` after `SET ROLE` | create temp shadows after `SET ROLE`, drop before `RESET ROLE`; gate 0 |
| W6 third | gate hung >600 s | the rollback trigger was committed before use and dropped explicitly, so no cross-session DDL lock; gate 0 |

G1-B also gained an injected-fault rollback probe in W6: a committed `BEFORE INSERT ON v24.events` trigger raises `23514` after the scope, effect and request rows have already been written (frozen order: domain → effect → request → events), and the ten-table snapshot before/after is byte-equal.

## Boundaries (not covered by S1)

- No read API: the "read request writes nothing" assertion is N/A until S3.
- No domain behavior for `runs`/`fibers`/`episodes`/`slots`/`pins`; catalog and owner-DDL probes only.
- No full scope close/drain (S5), no six verbs, loop, budgets, spawn, seal, or cleanup DAG.
- `advance` returns `revision = 0`; this is the known C2 hole and must be written back before S3.
- FakeHost is in-process and not a transport proof; crash recovery covers two journal windows only.
- Concurrency evidence is limited to G exclusivity and "G is the first lock" (G1-L); the full matrix belongs to S7/G6.
