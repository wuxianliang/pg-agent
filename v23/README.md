# v23 minimal agent loop

v23 is a new, deliberately small vertical loop with three roles:

- **Worker** performs exactly one fake model/tool turn outside database transactions and returns one `TurnReceipt`.
- **Control** is the only `execute(op)` entry. It performs short admission and commit transactions, idempotency, revision checks, cancellation, and committed snapshots.
- **Host** owns one driver coroutine per Run, calls the pure `decide` function, and invokes exactly one Control operation at a time.

The six operations are `start`, `poll`, `wait`, `cancel`, `steer`, and `respond`. A missing operation is `wait`; no other operation exists. `decide` returns only `run_now`, `wait`, or `stop`.

There is one durable table, `v23_runs`. Admission commits before Worker execution; commit happens after Worker execution; no PostgreSQL transaction spans Worker or tool work. `wait` reads, commits, then listens only as a wakeup and rereads after timeout/notification. The only durable close reasons are `cancelled`, `worker_failed`, `invalid_worker_receipt`, and `late_result_after_cancel`.

The gate resets its own local database, loads only `v23.sql`, and uses Fake Worker/Fake tools without network sockets:

```bash
uv run python v23/test_minimal_loop.py
```
