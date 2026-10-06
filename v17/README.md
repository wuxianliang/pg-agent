# v17 — SBCL worker for v12

One line: v12's seven SQL files loaded read-only by path; a SBCL worker
(postmodern → pgembed) replaces the Python `QueueWorker` and adds a new
effect class — develop/execute in persistent Lisp worlds whose state lives
entirely in Postgres (jiti kernel semantics ported, code written fresh;
plan: `docs/plans/v17-sbcl-worker-plan-2026-10-06.md`).

## Layout

```
v17/
  load.py            cumulative SQL_LOAD_ORDER (v12's 7 + store + world)
  store/             G1: jiti file store as 4 Postgres tables + 5 functions
  world/             G2: reference world over pgstore (kernel + adapter;
                     v17_world.sql pins routing conventions, no new tables)
  queue/             G3: SBCL worker vs v12 G6 seven scenarios — GREEN
  lisptools/         G4: lisp: tool jobs end-to-end (placeholder)
  develop/           G5: agent-grown tools full chain (placeholder)
  repair/            G6: condition/restart repair over the journal (placeholder)
  lisp/
    v17.asd          systems v17/kernel, v17/pgstore, v17/worker, v17/tests,
                     umbrella v17
    asd-registry.lisp  ASDF source-registry bootstrap (load after quicklisp)
    run-worker.lisp  sbcl --script entry for the queue worker (env-driven:
                     V17_PUMP_MODE once/daemon, V17_WORKER_ID, fake/real
                     Jev+LLM backends)
    src/             kernel.lisp (world/session/attempt/condition-loop/
                     capture/policy gate), reference-world.lisp (adapter),
                     pgstore.lisp (postmodern store + world glue),
                     pgmq.lisp (read/archive/set_vt), jev.lisp + llm.lisp
                     (gate fakes + real OpenRouter clients), worker.lisp (pump)
    tests/           fiveam suites (store, world, queue) + runners + crash
                     child
    quicklisp/       project-local quicklisp (gitignored, do not commit)
```

## Gates

Convention (same as v12): `uv run python v17/<stage>/test_<stage>.py`,
exit code 0 = pass; each stage's `setup_db.py` DROP/CREATEs
`agent_v17_<stage>` and loads `load.py:files_through(<stage>)`. The Python
gate orchestrates: get_server (repo-root `server.py`) → load SQL → fork an
SBCL worker subprocess with `PGSOCKETDIR`/`PGDATABASE` in env → assert DB
state.

| Stage | Status |
|---|---|
| G1 store | **green** — `v17/store/test_store.py` (DDL / fiveam store suite over forked SBCL / ancestry corruption / concurrent publish / crash-no-half-revision) |
| G2 world | **green** — `v17/world/test_world.py` (twice example / preview restore / error→checkpoint / unrecorded-change refusal / cross-process byte-identical capture / catalogue export→import identity / fiveam world suite) |
| G3 queue | **green** — `v17/queue/test_queue.py` (v12 G6 seven scenarios rerun against the Lisp worker + jsonb canary + python/lisp cross-language race) |
