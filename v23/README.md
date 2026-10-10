# v23 minimal agent loop

**M1 technical acceptance: PASS — 2026-10-10; 50/50 runtime labels, 382 labeled subcases.** Delivery uses the user-authorized append-only closeout after the premature external commit `1e3d5a4`; the originally planned single-commit sequence did not occur. See the conformance matrix and deviation ledger below. No Oracle-wide approval is claimed.

## Three roles, one durable truth

- **Worker** executes one model simulation and finite, sequential FakeTool handlers outside database transactions and returns one strict `TurnReceipt` DTO. It cannot read/write PostgreSQL, create Runs, call Control, or schedule another turn.
- **Control** is the sole business entry, `execute(op, actor, request)`. It owns authorization, revision CAS, admission, receipt validation/finalization, cancellation, idempotency and committed snapshots. It does not implement long-running policy.
- **Host** drives one Run through Control snapshots and pure `decide`. All Host instances and synchronous/asynchronous entry points share a thread-safe `(db_identity, run_id)` driver registry/Event. Host never reads SQL or invokes Worker directly; children are started only from an explicit `ParentActor` request.

The only durable data table is `v23_runs`, including parent references and its non-evicting `op_cache`. Snapshots exclude the cache. There is no events/effects/sessions/steps/history table, second scheduler, old-version import, migration or provider integration.

## Six operations and three decisions

`start`, `poll`, `wait`, `cancel`, `steer`, `respond` are the closed operation set; absent/null op means `wait`.

- `start` creates a top-level Host Run or an explicitly authorized parent child and executes one turn.
- `steer` accepts either Host `continuation=true` with no new instruction, or a ParentActor's explicit `parent_instruction`.
- `respond` requires `waiting_input`, the exact interaction ID, a valid answer and remaining budget. Host answers top-level Runs; only the actual parent answers children. Supported response-schema declarations are `type` and object `required`, not full JSON Schema.
- `poll` and `wait` are read-only and never schedule. `wait` does a short read, ends the transaction, LISTENs on an autocommit connection, immediately rereads, and rereads after notification or positive timeout. Payloads are wake hints, never state.
- `cancel` closes ready/waiting Runs or durably marks a running Run cancelled. New-ID repeat cancellation when already requested, and completed/stopped cancellation, are zero-write. The first accepted request is cached; its immutable receipt can describe a historical running snapshot.

`decide(snapshot, execution_accepted)` validates the complete snapshot/receipt before returning only `run_now`, `wait`, `stop`. Fixed priority: closed → running → cancel requested → waiting input → failed → exhausted budget → execution refused → ready continuation. Invalid snapshots raise `ValueError`. Running precedes cancellation, and waiting input precedes budget: an exhausted waiting Run rejects respond and needs explicit cancel. Legal first-turn stopped/null-receipt closures remain valid; `worker_failed` requires an accepted failed receipt.

## Transactions, fencing and retries

For start/steer/respond: **T1 admission commit → one DB-free Worker turn → T2 receipt/state/cache commit → best-effort notification**. Runtime/registry/SQL locks and database transactions do not span Worker, tool, owner-join, LISTEN or Host Event waits.

A normalized local Unix endpoint/port/database defines `db_identity`; behavior sessions use `v23_control`. One active runtime per database holds one session advisory fence. All mutation/recovery uses that same fenced session; compatible Controls share it. Fence loss permanently fails the old generation closed: no transparent reconnect and no old-receipt migration. New fenced startup recovers orphaned pending Runs as stopped/cancelled with the unique `recovered_orphan/owner_lost` receipt, preserving turns/prior receipt and never replaying Worker.

Request digests and actual input digests are distinct. Exact pending retries join the live original owner; done/recovered receipts replay before a new revision check, after authorization. Known T2 rollback retries the same frozen receipt, never Worker; committed acknowledgement loss reads done cache. Unknown T1 commit with pending and no Worker execution recovers fail-closed. Worker failures and invalid DTOs close durably and replay the same typed error/response.

Cancellation does not kill an already issued call. Cancel-first makes T2 discard any late normal/invalid/failed receipt without changing turns/prior receipt or reopening. T2-first accepts its receipt; a later cancel uses the new revision and cannot replace completed. The only stopped reasons are `cancelled`, `worker_failed`, `invalid_worker_receipt`, `late_result_after_cancel`.

## Host parking and stop

`Host.drive` starts a top-level Run when supplied all start arguments, or polls/resumes an existing Run/child. `drive_async` wraps the same unique driver. Each unconsumed semantic request keeps its ID across acknowledgement loss/CAS; a consumed next continuation gets a fresh ID. Every operation receipt is followed by current poll before deciding.

Waiting input or execution refusal uses Event clear → poll/redecide → finite Event wait → poll. Default `idle_interval=0.05`, strictly positive/finite and ≤1 second. Respond/explicit forwarding, stop and acceptance setters signal the shared Event; mutations outside Host are found by bounded timeout polling. External `Host.stop` uses poll/cancel/wait, not `decide`, and waits for durable close. Completed is returned unchanged. Finally releases the active driver reservation on success/error.

## Bounded fake execution and storage safety

FakeTool handlers really execute and their admitted input/output or bounded execution-failure marker belongs to that same committed receipt. Business `{ok:false}` is data; handler/serialization/size failures stop the current turn as `worker_failed`, never silently complete or schedule another turn.

- ≤8 calls; ninth-call plan rejected before any handler.
- Each canonical UTF-8 tool record ≤4096 bytes; full array including framing ≤32768 bytes.
- Result/input request ≤65536 bytes; failure marker ≤512 bytes.
- Worker and Control share bounded canonical `storage_safe_json`: finite JSON, string keys, no decoded NUL or surrogate characters, bounded jsonb numeric values, depth ≤128 and bounded traversal/serialization. Newline/tab/carriage return and other valid C0/C1 controls remain legal in multiline instructions and arbitrary JSON keys/text and round-trip unchanged. Literal backslash escape-looking text also remains legal; actual NUL is not. The overbroad control-character rejection was corrected before delivery; storage/traversal bounds are recorded in the deviation ledger.

## The sole gate

From the repository root:

```bash
uv run python v23/test_minimal_loop.py
```

Exit 0 is acceptance. The script resets **only** `agent_v23_minimal_loop`, loads `v23.sql` once, uses FakeWorker/FakeTool and Unix-domain PostgreSQL only, and rejects AF_INET/AF_INET6/TCP. Admin connections only set up, audit or inject faults; all normal behavior uses Control under `v23_control`. Real subprocess restart/fence fixtures use files/stdio, not network sockets. Do not run two complete destructive gates concurrently.

The final gate covers 50 labels and 382 subcases, including actual transactions/locks, wait races, commit faults, process recovery, permissions, byte boundaries, jsonb-safe receipt rejection and Host coordination. It is not real-provider/product acceptance or a historical-version regression claim. v23 is independent; `v8/load.py` registration is not applicable and was not changed.

Durable evidence:

- `docs/reviews/v23-conformance-matrix-2026-10-10.md`: every label, test-function mapping, runtime subcase count and evidence scope.
- `docs/reviews/v23-deviation-ledger-2026-10-10.md`: fixed review findings, input restrictions, premature external commit/order deviation and incomplete Oracle review/authorized independent-review closure.
- `docs/plans/v23-minimal-agent-loop-plan-2026-10-10.md`: W1–W7 and M1 acceptance/closeout checklist.
