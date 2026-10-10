# v23 M1 conformance matrix

**Date: 2026-10-10 · Technical acceptance: PASS, 50/50 labels, 382 labeled runtime subcases.**

Authority: `docs/designs/v23-minimal-agent-loop-2026-10-09.md` (2026-10-10 revision), plan §9/§9.10, repository AGENTS.md. Actual command from the repository root:

```bash
uv run python v23/test_minimal_loop.py
```

Observed exit code: **0** on the current independent-peer-fixed source, before closeout documentation; the same whole command is run again after all source/docs updates and before staging. Required final summary:

```text
v23 M1 runtime gate: green; 50/50 labels, 382 subcases; fake-only Unix PostgreSQL
```

The counts below are actual `[PASS]` output counts, not test-case estimates or 50 labels standing in for omitted subcases. The single gate and these descriptions are durable evidence; `/tmp/pg-agent-v23-closeout-pre-docs-2026-10-10.log` and the final closeout log are supplementary execution logs, not required gate dependencies. Real provider/product acceptance and other versions' regression gates are not claimed.

## Test-function index

All locations are in **`v23/test_minimal_loop.py`**. Function names, not frozen line numbers, are the durable navigation anchors.

| Alias | Actual test function | Main proof |
|---|---|---|
| API | `test_api_vertical_and_authority` | Real six-op/Host vertical and full parent-child chains, positive ParentActor instruction steer, authorization/input/replay/closed/budget cases |
| DEC | `test_disposition_validation` | Strict pure snapshot/receipt shape and type rejection, fixed priority, no mutation, legal stopped-null |
| RACE | `test_pending_cancel_and_competition` | Committed T1/blocked Worker, shared runtime/join, cancel zero-write, simultaneous CAS consumers, actual NOWAIT row-lock probes and both commit orders |
| WAIT | `test_waits_and_notifications` | First-read/LISTEN and second-read barriers, real lost/merged/forged/other-Run hints, positive timeout/new snapshot and post-commit notify failure |
| FAULT | `test_commit_faults_and_owner_loss` | Real SQLSTATE rollback and actual commit-then-ack-loss, frozen DTO retry, pending join, local owner disappearance and backend-kill fencing |
| RESTART | `test_process_restart` | Separate interpreter holds fence/two pending Runs; competing process busy; actual process termination; new-process recovery preserves prior receipt |
| SAFE | `test_storage_safe_receipts` | Actual decoded NUL/surrogate/numeric and field/key rejection, first/prior receipt preservation, stable error/cache replay, legal literal escape text and sanitized failure marker |
| JSON | `test_json_text_controls` | Positive Control start/parent_instruction/respond/result keys/text/tool data round-trip and cache replay for newline/tab/CR and other legal controls; actual NUL request negatives |
| TOOL | `test_receipts_and_tools` | Invalid DTO/Worker errors, real sequential FakeTool outputs and all canonical byte bounds, failure records, late receipt/history priority |
| HOST | `test_host_registry_parking_and_ids` | Cross-Control/Host sync/async uniqueness, parking/locks, wake/timeout paths, cleanup, stable IDs/CAS/ack loss/current poll |
| STOP | `test_host_stop_and_cached_cancel` | External stop without decide, historical cancel/current poll, one cancel then wait, stable stop ID on CAS |
| SCHEMA | `test_schema_permissions_and_isolation` | All user tables, actual one-SQL load counter, real role/CRUD/column/DDL probes, same mutation/fence backend, SQL NULL probes, runtime network guard |

`proof` prints a labeled subcase only after its predicates pass; `zero_write` also compares the entire durable row (including xmin/op_cache), current poll and Worker count. `durable` compares operation snapshot, independent Control poll and admin row. Worker/Host/owner-join tasks propagate exceptions to the main gate; barriers, joins and subprocess waits have finite deadlines. Admin SQL does setup/audit/fault or isolated constraint probes only, never substitutes for Control business behavior. SQL positive constraint probes are deliberately rolled back, not extra application-state rows.

## All 50 required labels

Each row's status is **PASS**; numbers are plan §9 labels and actual labeled subcase counts. Design sections refer to the authority above.

| # | Runtime label | Design / plan contract | Test functions | Subcases | Concrete evidence |
|---|---|---|---|---:|---|
| 1 | `v23_unknown_op_rejected` | Design §4; plan §9.1 | API, JSON | 11 | Unknown op and malformed request whole-row zero-write; absent/null op reaches wait |
| 2 | `v23_start_worker_outside_tx` | Design §6.2; plan §9.1 | RACE | 1 | Blocked Worker observes committed running/pending; fence session IDLE, no row lock |
| 3 | `v23_start_receipt_committed` | Design §4.1 | API, JSON | 5 | Return snapshot equals poll/admin row; revision2/turn1/receipt/done response durable |
| 4 | `v23_worker_called_once_per_op` | Design §1/§4/§6.2 | API, RACE, FAULT | 8 | Start/Host continuation/respond/parent_instruction exact counts; retry/known rollback no duplicate external effect |
| 5 | `v23_no_socket` | Design §8; plan §9.1/§9.10 | SCHEMA | 1 | Runtime AF_INET/AF_INET6/TCP PostgreSQL guards reject; actual connections Unix-only |
| 6 | `v23_vertical_run_steer_stop` | Design §1/§7 | API | 2 | Actual Host two-turn chain and explicit parent-child needs_input/respond/Host-resume chain |
| 7 | `v23_progress_three_dispositions` | Design §5 | API, DEC | 47 | Accepted/refused/exhausted outputs, pure unchanged snapshots and malformed snapshot/receipt rejection |
| 8 | `v23_budget_stop` | Design §5.3; plan §2.5.5 | API, DEC | 3 | Real ready budget Host cancel; waiting and running fixed precedence over budget |
| 9 | `v23_completed_is_not_reopened` | Design §3.2/§4.5–4.6 | API | 2 | Completed steer/respond rejected, no writes/Worker |
| 10 | `v23_wait_is_read_only` | Design §4.3 | API | 10 | Full row/cache unchanged; invalid since/timeout rejected, normal timeout read-only |
| 11 | `v23_wait_notification_only_wakes` | Design §6.3 | WAIT | 2 | Forged business/high-revision payload and real other-Run notifications cannot construct target state |
| 12 | `v23_wait_timeout_rereads` | Design §4.3/§6.3 | WAIT | 1 | Notify suppressed after listener read barrier; positive timeout rereads newer committed revision |
| 13 | `v23_wait_read_listen_race_closed` | Design §4.3; plan §9.10 | WAIT | 1 | Real commit between first read and LISTEN; immediate complete reread finds change |
| 14 | `v23_wait_notification_lost` | Design §6.3 | WAIT | 1 | Suppressed post-commit hint still converges to poll/admin current state |
| 15 | `v23_wait_notification_merged` | Design §6.3 | WAIT | 1 | Multiple actual committed revisions, one hint; final DB snapshot wins over payload |
| 16 | `v23_transaction_idle_boundaries` | Design §6.2–6.3; plan §9.10 | RACE, WAIT, HOST, SCHEMA | 10 | Backend/pg_stat_activity IDLE probes, lock-free join/Event/LISTEN, released listeners, commit-before-notify and no retry on notify failure |
| 17 | `v23_respond_only_waiting_input` | Design §4.6 | API, RACE | 5 | Ready/running/completed/stopped refuse respond without mutation/Worker |
| 18 | `v23_respond_interaction_exact_match` | Design §4.6 | API, JSON | 9 | Wrong interaction/schema/options zero-write; exact answer binds parent_response Worker |
| 19 | `v23_parent_child_authority` | Design §4.1/§4.5/§4.6/§7 | API, JSON | 13 | Explicit actual-parent child creation/respond/instruction; Host/sibling rejection; closed-parent denial; top-level Host answer |
| 20 | `v23_host_continuation_has_no_input` | Design §4.5 | API, JSON | 6 | Host input injection, missing parent instruction and steer bypass of waiting input rejected |
| 21 | `v23_parent_wait_does_not_schedule` | Design §7.7 | API | 1 | Parent wait full row/calls unchanged with decide forbidden |
| 22 | `v23_expected_revision_conflict` | Design §4; plan §9.5 | API | 1 | Stale continuation CAS rejects zero-write/Worker |
| 23 | `v23_two_consumers_same_revision` | Design §4.5; plan §9.10 | RACE | 1 | Barrier launches two same-revision consumers; one admission and one revision_conflict |
| 24 | `v23_idempotent_mutation` | Design §4; plan §2.5.1 | API, RACE, JSON | 9 | Start normalized absent/null revision, pending join, historical steer/respond and positive parent-instruction exact replay no writes/Worker |
| 25 | `v23_idempotency_conflict` | Design §4; plan §2.5.1 | API, RACE, FAULT | 12 | Changed op/authorized actor/input/instruction and unauthorized cached-ID access reject without leaks/writes/Worker |
| 26 | `v23_pending_digest_and_recovery_receipt` | Plan §2.5.1/§3.6 | RACE, FAULT, RESTART | 9 | Independently canonical request/input digests, pending atomic fields, unique recovered receipt exact replay/mismatch checks |
| 27 | `v23_commit_ack_loss_no_replay` | Design §6.5; plan §3.5/§9.10 | FAULT, HOST | 12 | T1 known rollback/unknown commit/confirmed caller-loss join; T2 rollback/healthy/dead ack; Host same-ID confirmation retry |
| 28 | `v23_cancel_idempotency_and_zero_write` | Design §4.4 | RACE | 5 | First running cancel cached; same-ID changed CAS replay; new-ID already-requested and closed cancel zero-write; stale CAS conflict |
| 29 | `v23_respond_budget_admission` | Plan §2.5.5 | API, HOST | 2 | Exhausted waiting decide wait; respond budget_exhausted no mutation/Worker; explicit cancel wakes parking |
| 30 | `v23_t2_owner_only_retry` | Design §6.5; plan §3.5 | FAULT | 5 | Serialization/deadlock original thread uses identical frozen DTO; ack uses done; foreign-thread pending T2 zero-write rejected |
| 31 | `v23_cancel_running` | Design §4.4/§6.4 | RACE | 1 | Real durable cancel_requested retains active and no invented receipt/turn |
| 32 | `v23_late_worker_result_discarded` | Design §6.4–6.5 | RACE, TOOL | 7 | Normal/invalid/exception late first/prior turns cannot reopen or change accepted turns/receipt |
| 33 | `v23_t2_cancel_lock_order` | Design §6.5 | RACE | 6 | Both actual FOR UPDATE lock probes; cancel-first discard; T2-first receipt preservation/fresh cancel and stale CAS rejection; completed wins |
| 34 | `v23_cancel_ready_and_waiting` | Design §4.4 | API | 4 | Both states durably stopped/cancelled; further steer/respond zero-write rejected |
| 35 | `v23_owner_disappearance_no_replay` | Design §6.5; plan §2.5.2 | RACE, FAULT, RESTART | 5 | Healthy shared runtime no false recovery; missing owner once; other-process fence loser; killed old session/still-live Worker cannot finalize |
| 36 | `v23_process_restart_closes_orphans` | Design §6.5; plan §9.10 | RESTART | 3 | Actual subprocess termination; new interpreter fence/recovery of two Runs, preserving prior receipt/turns and revision once |
| 37 | `v23_invalid_receipt_closes_safely` | Design §3.4/§4.1; peer P1 | DEC, SAFE, TOOL | 70 | DTO-only/identity/type/bounds; decoded NUL/surrogate/numeric unsafe fields/keys first/prior cases durably close and replay same error; legal literal text positive |
| 38 | `v23_worker_exception_closes_safely` | Design §6.5 | DEC, SAFE, TOOL | 4 | Failed DTO durable worker_failed; first/prior exception response/error stable; safe sanitized failure-marker replay |
| 39 | `v23_fake_tools_bounded` | Design §3.4/§6.2; plan §3.4.3 | SAFE, JSON, TOOL | 28 | Real handlers, count9 zero-effects; 4096/4097, framed32768/32769, result/input_request65536/65537, UTF-8/jsonb-safe traversal/marker bounds, and valid control text round-trip |
| 40 | `v23_tool_failure_does_not_schedule` | Design §3.4/§6.5 | TOOL | 15 | Business failure same-turn data; handler/serialization/overflow/NUL-output failures stop next handlers, preserve bounded records and never schedule repair/Worker |
| 41 | `v23_single_run_coroutine` | Design §6.1; plan §3.8 | HOST | 17 | Cross-Control/Host sync/async second driver zero-effects; bounded Event parking/wake/direct-no-signal; exception cleanup; stable IDs/new consumed-turn IDs and current poll after cache |
| 42 | `v23_host_stop_calls_cancel` | Design §7.6; plan §3.8.4 | STOP | 5 | External stop forbids decide, historical cancel followed by poll, one running cancel then wait, stable stop ID across CAS |
| 43 | `v23_completed_not_cancelled` | Design §7.6 | API | 1 | External completed stop leaves status/revision/whole row unchanged |
| 44 | `v23_only_one_data_table` | Design §2 | SCHEMA | 1 | Actual catalog audit across non-system schemas: only public.v23_runs |
| 45 | `v23_load_is_single_sql` | Design §2; plan §3.10 | SCHEMA | 1 | Recorded actual setup DDL execution: v23.sql exactly once, not string-count evidence |
| 46 | `v23_no_v13_v15_imports` | Design §1–2 | SCHEMA | 1 | AST boundary supplement to positive independent runtime chains |
| 47 | `v23_no_static_control_map` | Design §1/§8 | SCHEMA | 1 | Runtime delivery file inventory contains no CE mapping artifacts |
| 48 | `v23_no_events_effects_history_tables` | Design §2 | SCHEMA | 1 | Actual all-user-table audit excludes events/effects/sessions/steps/history |
| 49 | `v23_control_worker_permissions` | Design §2; plan §2.5.6 | RACE, FAULT, RESTART, SCHEMA | 14 | Actual v23_control session/current role and same fence/mutation/recovery backend; Worker connect/CRUD denied, immutable-column/DDL denied, active/JSON NULL constraints reject |
| 50 | `v23_no_network` | Design §8–9; plan §9.10 | SCHEMA | 1 | Fake-only full guarded runtime and child fixtures; Unix DSN enforcement, no real provider/client |

## §9.10 deterministic subcase reconciliation

- API/readonly/idempotency: whole-row/cache/xmin before/after, actor authorization before cache, changed expected revision replay and pending op/actor/input mismatches. Positive ParentActor instruction steer is independently proved, not inferred from rejection cases.
- Transaction boundary: committed T1 inspected at blocked Worker; actual libpq transaction status and admin backend state; independent cancel can commit while Worker/join waits; T2/cancel actual row locks observed using NOWAIT. Locks are not inferred merely from successful output.
- Wait: hooks pause after first read and after effective LISTEN/second read. Mutations really commit in those windows; suppressed notification still needs positive timeout/reread. Merged/forged/other-Run hints never supply state.
- Faults: SQLSTATE40001 and40P01 before commit are distinct from actual commit followed by raised acknowledgement loss. T1 unknown pending recovers without executing; confirmed original owner joins; T2 original owner retains the same DTO. Dead fence does not transparently reconnect.
- Restart: independent interpreters and actual process termination, two pending Runs (one has prior receipt), fence contender failure with candidate backend cleanup, single recovery revision and exact recovered replay. Same-process new Control is explicitly not treated as restart.
- Receipt/tools: initial/prior invalid and handler/late cases; actual decoded U+0000 versus literal escape-looking text; bounded failed markers; handlers create reachable per-item/framed-aggregate/exact-result/input-request boundaries.
- Host: actual Host resumes child, sync/async and separate instances share registry; Event park/poll counts bounded; explicit response/stop/admission signals and direct Control/no-signal convergence; successful/failed/error cleanup; cached historical responses followed by current poll.
- Isolation: actual user-table audit, observed DDL load, session/role/PID probes and runtime socket/Unix-PostgreSQL guard, including subprocess fixtures. Static import/file scans only supplement these proofs.

## Scope, review and delivery caveats

`v8/load.py` registration is not applicable to the isolated single-SQL v23 database; no shared production/history files or loaders were changed. The final storage-safe JSON restriction rejects only decoded NUL/surrogates and bounds numeric/depth/traversal/bytes; the initial blanket C0/C1 rejection was corrected before delivery. `test_json_text_controls` proves newline/tab/CR and other valid controls through Control. Waiting-input budget precedence, single active runtime, non-killing cancellation and bounded unsignalled polling remain intentional design limits.

The user confirmed independent peer review P1/P2 findings fixed and authorized closing out after rerun; the closeout owner inspected those changes and actually reproduced the corrected 382 subcases after the user's final multiline/control-character spot-check. Oracle chats `untitled-chat-2B4D73` / `untitled-chat-3CF52E` did not deliver a comprehensive final verdict (packaging gaps/timeouts/cancellation), so this matrix does **not** attribute comprehensive approval to Oracle. No additional review cycle was started for closeout.

External premature commit `1e3d5a4` is preserved unchanged. Final repository delivery uses an append-only closeout commit and ordinary push, per explicit user authorization; original one-M1/one-commit sequencing did not occur. Exact commit/push outcome belongs to git and the final delivery report, not a fabricated self-referential hash. See `v23-deviation-ledger-2026-10-10.md` for finding disposition and historical process deviation.
