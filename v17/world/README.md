# v17/world — G2: reference world over pgstore

`v17_world.sql` adds no tables and no pgmq kinds (plan §3.2); it pins the
routing conventions — `tools.handler = 'lisp:<function-name>'`,
`jobs.kind = 'lisp_eval'`, `jobs.kind = 'lisp_develop'` with caller-supplied
executable `goals`/`invariants` (jiti's acceptance contract: an unmet goal
permits safe intermediate progress, a violated invariant refuses the
revision and restores the checkpoint).

The stage's substance is on the Lisp side:

- `v17/lisp/src/kernel.lisp` — the kernel (jiti kernel semantics, fresh
  code): `world` defstruct with adapter hooks + single-owner lock;
  `session` on a worker thread coupled to its controller by inbox/outbox
  mailboxes, with a generation counter rejecting stale proposals and a
  budget bounding consumed actions; `attempt` = snapshot checkpoint →
  evaluate → invariants → commit or restore; `condition-loop` = live
  restart menu with repair forms and `:resume`; `capture-managed-state` =
  deterministic readable tree → byte vector (pinned printer control, so
  two images fed identical operations capture byte-identical vectors);
  `printed-values` bounded printing; `parse-one-form`/`validate-form`
  conservative policy gate; `check-predicates`. Durability enters through
  optional session function slots (publish-fn / rollback-fn / journal-fn /
  current-revision-fn), so the kernel stays DB-agnostic.
- `v17/lisp/src/reference-world.lisp` — the reference adapter: one EQUAL
  hash table (`*STATE*` in the world's own package) plus direct named
  `defun`/`fmakunbound` edits; snapshot/restore/managed-state/catalogue/
  export/import; export/import produce and consume ONE readable string —
  the revision row's `state_text`, never a file; any definition change
  that bypassed the recorder fails the next capture loudly.
- `v17/lisp/src/pgstore.lisp` — gains `publish-world-revision` /
  `load-world-revision`, pairing an adapter world with its durable
  identity (export → `v17_publish_revision` inside
  `with-store-transaction`; `v17_load_revision` → import, with the SBCL
  version identity check before any import).
- `v17/lisp/tests/world-suite.lisp` — fiveam suite (52 checks): policy
  gate, bounded printing, capture determinism/readability, session
  protocol (develop/execute/preview/error/stale-generation), unrecorded
  change refusal, snapshot/restore, export/import round-trip, catalogue,
  budget/goal edges, single-owner, and the pgstore revision round-trip.

Gate: `uv run python v17/world/test_world.py` (exit 0 = pass). Scenarios:

- `lisp/session-scenarios.lisp` — twice example (develop
  `(defun twice (x) (* 2 x))` → execute `(twice (twice 3))` = 12), preview
  restore (preview incf returns 1, state stays 0), error back to
  checkpoint (error pauses on the restart menu, `:abort` restores, state
  unchanged), stale-generation rejection, unrecorded fmakunbound/defun
  refusal.
- `lisp/capture-bytes.lisp` — two independent SBCL processes build the
  same world from the same operations and store their capture vectors in
  `world_gate_captures`; the gate compares them byte for byte.
- `lisp/publish-world.lisp` + `lisp/load-world.lisp` — publish a world
  (twice/thrice + data) as revision seq 1; a fresh process imports CURRENT
  and calls the functions; catalogue text and call results (12) must
  match across export→import.
- the fiveam world suite runs as part of the gate.

The `world_gate_captures`/`world_gate_texts` tables are gate-local scratch
created by `test_world.py`, not part of the stage SQL surface.
