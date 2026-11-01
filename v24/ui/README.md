# v24 UI — M1 persistent environment and read loop

M1 is a synchronous scripted runtime; effective `exec` exposes only `read`. M2 (second family, render mapping and UI gate) has not started. No Chainlit or real provider is used.

From the repository root:

```sh
uv run python -m v24.ui.env --init
uv run python -m v24.ui.env --status
uv run python -m v24.ui.d_ui_6_acl --check
uv run python -m v24.ui.control --selftest
```

The environment is `agent_v24_ui` on the repository's embedded PostgreSQL. `.uidata/` contains private metadata, lock, journal, workspace and spill; it is ignored by Git. Init is create-only and returns `already_initialized` on an exact match. Drift refuses startup. `--migrate` prints `migration_unsupported` and exits 2. `--reset --yes` is destructive and was tested only against a disposable server; the existing environment was preserved.

The approved D-UI-6 helper supports only `--check` and `--apply`. It recognizes exact preupgrade, ACL-upgraded/metadata-old and completed states, holds the environment lock, checks target/server/OID/fingerprint, grants admin EXECUTE on `v24.install` only, and atomically updates the permissions and SQL-manifest digests. It never reloads SQL. Existing-state check/apply/check each exited 0: `preupgrade`, `completed`, `completed`. Database OID 4785566 and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` were preserved.

The selftest runs prepare/install/fiber activation, model → actual read subprocess → model final. It checks database-read install/fiber/manifest/artifact/adapter/descriptor digests, registry mismatch exceptions, RPC rollback and idle connections, exact `{read}` pins and model tools, and prints every effect's ID/kind/status/ordinal/time. Successful returned domain rejections are committed; Python/SQL exceptions are rolled back.

Empirical same-scope result (2026-11-02): first run `31c5aefd-5bc5-4d90-95f9-280352728cdf` completed with `done`; second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed in that same scope. M3 may use this evidence for scope reuse; M2 still must prove two requires across families.

Raw `remaining_tokens` includes admission reservation/refund and was `[15904,19995,15899,19990]`. The monotonic unspent budget (raw plus outstanding model reservation) was `[20000,19995,19995,19990]`, spending 10 tokens. This records the actual SQL behavior; no budget SQL was changed.

`read` is verbatim UTF-8 without line numbers, bounded to 2000 lines/32 KiB and the 40960-byte serialized-value budget; truncated text spills under `.v24/spill/`. It rejects sensitive paths, symlinks, traversal, nonregular files, invalid UTF-8, NUL, and files over 1 MiB. Known file failures use v2 failure frames/exit 3. Completion cap is 512; provider length termination fails the run rather than truncating a final. Skills and the other ten planned tools are later milestones.

The pre-existing fingerprint encoding uses the deterministic functions-then-columns compact JSON field order. M1 preserves that encoding and fingerprint instead of silently migrating existing metadata; the D-UI-6 helper changes exactly the two authorized digests. SQL-manifest arrays retain SQL_LOAD_ORDER.

Exact acceptance commands, exits and final lines are recorded in [the UI conformance matrix](../../docs/reviews/v24-ui-conformance-matrix-2026-11-01.md) and [deviation ledger](../../docs/reviews/v24-ui-deviation-ledger-2026-11-01.md). The commit stays on `v24/ui-chainlit`; no push.
