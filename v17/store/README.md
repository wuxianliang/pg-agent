# v17/store — G1: the Lisp world store as Postgres tables

Gate: `uv run python v17/store/test_store.py` (exit 0 = pass; drop/creates
`agent_v17_store`, loads `v17/load.py:files_through("store")`).

## Surface

`v17_store.sql` holds the world store: `lisp_worlds` (registry),
`lisp_revisions` (revision = state_text + manifest, per-world no-hole seq),
`lisp_current` (CURRENT pointer, CAS'd in the same transaction as the
revision INSERT), `lisp_journal` (append-only event journal). Revisions and
journal are append-only (trigger); `lisp_current` is control state.

Functions: `v17_publish_revision` (advisory-lock single-writer per world,
INSERT + pointer CAS as one atomic unit in the caller's transaction),
`v17_load_revision` (default CURRENT), `v17_list_revisions` (ancestry
validation: contiguous seq, parent links, no cycles, no orphans — violations
raise), `v17_append_journal` (operation-start/finish events validated:
record must be an object with non-empty string `id` and `status`;
`operation_id` must agree with `record.id` and is backfilled from it —
`v17_recover_operations` groups by `record->>'id'`, so malformed records
would silently fold or lose recovery state), `v17_recover_operations`
(running→interrupted fold, newest first, ≤100).

## Lisp side

`v17/lisp/src/pgstore.lisp` (system `v17/pgstore`) wraps the SQL functions
one-to-one: `create-world` / `find-world` / `publish-revision` /
`load-revision` / `list-revisions` / `append-journal` / `recover-operations`,
plus two macros: `with-store-connection` (sets
`cl-postgres:*unix-socket-dir*` from `PGSOCKETDIR`, db from `PGDATABASE`;
`postmodern:connect` never sets `*database*`, so all DB work goes through
the macro — plan §2.1 lesson 1) and `with-store-transaction` (one explicit
transaction on the current connection).

**Transaction discipline (the plan §1/§3.1 crash-safety contract):** the
worker's publish, its operation-finish journal entry and the queue's
`complete_job` must share ONE commit — that is what closes jiti's uncertain
publication window. A bare `postmodern:query` is one autocommitted
statement, so `publish-revision` **refuses to run outside
`with-store-transaction`** (detected via postmodern's
`*current-logical-transaction*`; a bare call signals `store-error` before
touching the DB). `append-journal` stays callable autocommit for the
operation-start entry (jiti writes it before the op runs); the
operation-finish entry belongs in the publish's transaction.
Manifests/events are alists with string keys, encoded with yason; `publish`
pins key `"sbcl"` to `(lisp-implementation-version)` when absent, and
`load-revision` signals `revision-version-mismatch` when a revision's pinned
version differs from this image (plan §7.4: drift = loud failure).
State text is stored/read as opaque text; the world side (G2) writes it with
`*print-readably*`.

## Gate scenarios (test_store.py)

- DDL shape: four tables; UNIQUE(world_id,seq), CHECK seq>=1, UNIQUE world
  name, append-only triggers all enforced.
- publish/load/list/rollback/journal/recover/version-refusal end-to-end via
  the fiveam suite (`v17/lisp/tests/store-suite.lisp`, run by
  `run-store-suite.lisp` in a forked `sbcl --script` subprocess with
  `PGSOCKETDIR`/`PGDATABASE` in env), including:
  **autocommit publish refused** (`publish-revision` outside
  `with-store-transaction` signals `store-error`, nothing published) and
  **journal operation-event validation** (missing record/id/status and
  disagreeing `operation_id` raise; `operation_id` backfilled from
  `record.id`).
- Ancestry corruption detection: seq hole / broken parent link / cycle /
  orphans (made with the append-only trigger temporarily disabled, rolled
  back after each case) — `v17_list_revisions` must raise.
- Concurrent publish: two psycopg2 connections race
  `v17_publish_revision` on one world. **Semantics: both win.** The
  advisory xact lock serializes them; seqs come out unique and hole-free
  ({1,2}), CURRENT ends at seq 2. (A loser exists only if a writer bypasses
  the lock, which the CAS UPDATE then turns into a loud error.)
- Journal validation (SQL side, direct psycopg2): malformed operation
  events raise; rejected appends leave no seq holes; non-operation events
  stay free-form.
- Crash: forked SBCL child BEGINs, INSERTs a raw revision row (seq 999,
  bypassing the publish function), prints READY, pauses; the gate SIGKILLs
  it — CURRENT unmoved, no orphan row (uncommitted txn rolled back).
- SBCL version mismatch: covered inside the fiveam suite
  (`sbcl-version-mismatch-refused`).
