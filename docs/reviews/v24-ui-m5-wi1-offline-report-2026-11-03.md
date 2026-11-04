# v24 M5 WI-1 offline implementation handoff — 2026-11-03

Status: WI-1 implementation and offline tests delivered for coordinator inspection. **M5 remains incomplete**: no real provider call, measurement, capacity recommendation, browser acceptance, or formal Oracle review has occurred. The coordinator explicitly owns final formal review after WI-2/acceptance. Incident acceptance is also the coordinator's decision; the limits below must not be represented as proof of unchanged pre-incident logical state.

## Scope and material decisions

| Decision | Disposition and implementation |
|---|---|
| Smallest CLI layout | `v24/ui/real.py` contains both `create_real_adapter()` and the CLI. Command: `python -m v24.ui.real --real-provider-smoke`. This follows the explicit command in one Oracle lane and avoids a second wrapper module and any Chainlit import. |
| Work item boundary | Only `short` is accepted by the CLI. Workflow/probe scenarios and richer measurement receipts belong to WI-2; unsupported scenarios are rejected rather than silently running a different prompt. |
| Shared actual runtime | UI and CLI use `DeepSeekAdapter` and `AgentRuntime`. The real branch never constructs `FakeAppAdapter` or calls `ScriptedUiAdapter`. Fake remains the default mode. |
| Startup ordering | Mode/opt-in → DEEPSEEK key, then OPENAI fallback → adapter → local preflight → filesystem/lock/DB/runtime. Missing-key UI error is `credentials_absent`; CLI exits 2. Preflight failures expose only `preflight_failed`. |
| Baseline budgets | Shared frozen `UiLimits` records retain 8000 canonical-body bytes, request completion cap 512, timeout 120 seconds, worker default lease 30000 ms, and 24/24/20000/600000 run budget. No numerical budget changes; `MAX_SAFE_ARGS_BYTES` remains `None`. No arbitrary numeric CLI/environment overrides. |
| Frozen host/SQL contracts | No host, SQL/schema/load, artifact, skill, or vector changes. Reserve remains 4096; adapter default/clamp/lease/length behavior remains unchanged. |
| Prompt compatibility | Shared prompt lives in catalog; app retains a thin named function because the existing gate compiles that function via AST. Its resulting baseline bytes equal the former function. Fake footer values remain the same. |
| Journals | CLI creates a fresh private child evidence directory and retains journals on both completed and nonzero/unknown outcomes. UI persistent journals remain retained. Errors before journal creation report it absent. |
| Waiting | Real mode never asks or auto-responds; it reports `waiting_unsupported; use /cancel`. Fake interaction behavior is retained. |
| Partial startup resources | Runtime construction owns raw connections through second-connect, journal-open, and later constructor failures, closing acquired resources before propagating failure. |
| Audits/reviews | New offline contract test and external receipts suffice for WI-1. Neither protected M4 audit nor runner was modified or repurposed as an M5 audit. No formal Oracle review was invoked. M5 final audit and closing README/matrix/ledger changes are deferred; historical documents remain unchanged. |

Changed source files: `v24/ui/app.py`, `v24/ui/catalog.py`, `v24/ui/control.py`; new source files: `v24/ui/real.py`, `v24/ui/test_real_entry.py`. This report is the only new repository documentation file.

## First-attempt persistent PGDATA incident

Command: `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/test_real_entry.py > /tmp/v24-m5-focused-first.log 2>&1` (exit 1). Log birth/last-write: 17:49:46.199755–17:49:47.514320 Asia/Shanghai. Lines 1–2 are exactly:

```text
Error in sitecustomize; set PYTHONVERBOSE for traceback:
ModuleNotFoundError: No module named 'server'
```

Its final line is `AssertionError: length classification` (a separate test assertion bug: it matched prompt text rather than the model mapping). Full log SHA256: `ebaf3e45df7a7a1ef30a6fdf17069805ce93bcab3393aaf105966c3dce89d4c0`.

Root cause: the initial test launcher relied on `sitecustomize.py` to assign `server.PGDATA`; its PYTHONPATH contained the bootstrap directory but omitted the repository. Python reports a sitecustomize import error and continues executing the requested program. The unchanged S1 helper then imported repository `server.py` normally and used its default `.pgdata`. Merely correcting PYTHONPATH was insufficient as a fail-closed design.

The existing `.pgdata/log` establishes the actual server lifecycle:

```text
2026-11-03 17:49:46.532 CST [32795] LOG:  starting PostgreSQL 18.4 on aarch64-apple-darwin25.6.0, compiled by Apple clang version 21.0.0 (clang-2100.1.1.101), 64-bit
2026-11-03 17:49:46.533 CST [32795] LOG:  listening on Unix socket "/Users/wxl/Projects/pg-agent/.pgdata/.s.PGSQL.5432"
2026-11-03 17:49:46.696 CST [32801] LOG:  database system was shut down at 2026-11-03 11:38:24 CST
2026-11-03 17:49:46.707 CST [32795] LOG:  database system is ready to accept connections
2026-11-03 17:49:47.332 CST [32795] LOG:  received fast shutdown request
2026-11-03 17:49:47.342 CST [32795] LOG:  database system is shut down
```

This was a start of a stopped existing cluster, not attachment to an already running server. The helper's normal EOF cleanup stopped it; no leftover server or cleanup failure was reported. The cluster's logs, WAL, global catalogs, handle list, and other runtime files therefore cannot be called unchanged.

Actual database DDL in that interval:

```text
2026-11-03 17:49:46.792 CST [32806] LOG:  statement: CREATE DATABASE "v24_s1_32788_db1ec9562300" TEMPLATE template0
2026-11-03 17:49:47.300 CST [32821] LOG:  statement: DROP DATABASE "v24_s1_32788_db1ec9562300" WITH (FORCE)
```

Exactly four fixture login roles (`_owner`, `_admin`, `_service`, `_operator`) were also created at 17:49:46.864–.867 and dropped at 17:49:47.323–.329. No group-role CREATE/DROP appears in the interval. S1 `setup_db()` creates a new randomized name, loads SQL only there, and its exact-name/OID cleanup drops that fixture; it does not reset an existing UI DB. The test reached only its first CLI stop scenario before the assertion failed; the later Backend fixture was not reached. Persistent UI `open_env/init_env/drop_env/migrate_env` was not called.

Evidence and its limits:

- The retained 310 statement log entries in the incident interval contain no `agent_v24_ui` name. This is supporting evidence, not connection-level SQL auditing of every database.
- Existing `.uidata/loaded.json` identifies `agent_v24_ui` with database OID `4785566`; that OID directory still exists. All 379 files under `.pgdata/base/4785566` have mtimes no later than `2026-11-02T16:54:22.154316+08:00`, before the incident.
- All `.uidata` files have pre-incident mtimes: loaded metadata Nov 1, journal/turns/sessions/lock Nov 2. Current file hashes and mtimes are retained in the read-only incident evidence JSON.
- The original baseline manifest covers tracked files and 52 original untracked files, **not** ignored persistent database contents. No pre-incident dump or relation hashes were captured. Consequently a strict before/after logical-equality proof of the existing UI database is unavailable. No database was started to collect retrospective queries, and no persistent state was deleted, repaired, restored, or reset.
- After the incident, a read-only filesystem metadata baseline was taken for 67,330 PGDATA/UI paths (size, mtime_ns, inode, mode). The repaired tests and full checks are compared against it. This proves no subsequent metadata changes within that observed set; it does not retroactively certify the earlier incident or compare atime/logical SQL state.

Read-only evidence is at `/tmp/v24-m5-wi1-receipts-20261103/incident-readonly-evidence.json`; the original incident's cluster-log byte segment is offset `1587681223`, length `645213`, SHA256 `c352d8f20b812ccaafdadcd6308f770dfd1de0ead991aea2b645a4ee8ee48dfb` in `.pgdata/log`. The original cluster log remains in place.

## Fail-closed prevention and tests

The real module no longer creates or relies on sitecustomize. It launches an explicit `python -I -c` child that imports `_private_db_helper` and supplies a fresh absolute private PGDATA path. That function rejects existing/noncanonical paths and nonprivate parents before calling `pgembed.get_server(explicit_path, cleanup_mode='stop')`. It never calls repository `server.get_server()` and never omits the PGDATA argument. The child's main-program import failure terminates it instead of allowing a fallback.

The parent refuses pre-existing S1 helpers, validates the child's PGDATA attestation and S1's active Unix endpoint, and only then permits `setup_db()`. Child environment excludes provider credentials and PG/libpq overrides. Failure closes/reaps/unregisters the helper and never starts the fixture. Journals and private evidence remain retained when created.

The offline suite injects an actual child-process import failure, requires exactly one launch, zero setup_db calls, zero provider dispatches, no cluster creation, and cleared helper registration. It also rejects existing PGDATA and foreign helpers. Successful UI/CLI tests use the actual DeepSeek adapter with a local injected transport, assert both HostDB connections IDLE at transport entry, and prohibit Python network socket construction during runtime tests. Stop and length replies prove success and unknown/nonzero journal retention without provider calls. Startup tests cover missing credentials, key precedence, preflight errors, partial-construction cleanup, baseline prompt bytes and limits, and the asynchronous hub error. Before/after persistent-state metadata is required identical.

## Verification receipts

The tables below distinguish the final focused suite from the final entire existing runner. All failed and earlier passing attempt logs remain at their original `/tmp` paths; they are not replaced by the final success. No source hash is retroactively claimed for a failed development snapshot.

### Final top-level commands

| Check | Exact command | Exit | Exact last line | Log |
|---|---|---:|---|---|
| focused-failclosed-r2 | `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/test_real_entry.py` | 0 | `[passed] M5 real entry offline contracts; sockets=0; capacity=unmeasured` | `/tmp/v24-m5-focused-failclosed-r2.log` |
| runner-post-failclosed | `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python v24/ui/run_m4_checks.py --log-dir /tmp/v24-m5-wi1-existing-r3-20261103` | 0 | `[passed] M4 private checks; commands=16; exits=0; skips=0; persistent_pgdata_untouched=true` | `/tmp/v24-m5-wi1-existing-r3-runner.log` |
| module-no-flag-final | `UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python -m v24.ui.real` | 0 | `not_requested` | `/tmp/v24-m5-cli-not-requested-final.log` |
| module-no-key-final | `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run python -m v24.ui.real --real-provider-smoke` | 2 | `credentials_absent` | `/tmp/v24-m5-cli-absent-final.log` |

The entire-run result is 16 existing commands, **separate from** the one focused M5 command. Combined final tests: 17 commands, all green. The public missing-key exit 2 is its expected contract result. No audit command is included in the 16; the old audit was deliberately not run.

### Entire existing runner: actual child argv and last lines

The runner used sanitized environment/private PGDATA and executed the exact argv below; its reproduce commands and per-log/source SHA256 are in the JSON receipts.

| Actual command | Exit | Exact last line |
|---|---:|---|
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/ui/test_ui_gate.py` | 0 | `[passed] v24 UI gate; steps=10; effects=5; artifacts=2; families=2` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/ui/test_backend_regressions.py` | 0 | `[passed] backend regressions; read7_exec11=three_processes_each; empty_answer=real_entry_zero_rpc; old_binding=readonly; same_scope_next_start=true; busy_steer_cancel=true; close_checkpoint=targeted_fiber_off_before_dispose; repeated_close=authoritative; python_connect_tripwire=true; db_transport=unix` |
| `/Users/wxl/Projects/pg-agent/.venv/bin/python3 v24/ui/test_artifact_regressions.py` | 0 | `[passed] M4 artifact regressions; full_spill_gt1MiB=true; snapshot_reuse=true; skip_counts=true; no_stdout_kill_cleanup=true; shell_exit_supervision=true; supervisor_status=true; provider_calls=0` |

### Retained earlier attempts

| Attempt | Exit | Exact last line | Log |
|---|---:|---|---|
| focused-first | 1 | `AssertionError: length classification` | `/tmp/v24-m5-focused-first.log` |
| focused-second | 1 | `AssertionError: dispatch finish count` | `/tmp/v24-m5-focused-second.log` |
| focused-third | 1 | `RuntimeError: workspace_invalid` | `/tmp/v24-m5-focused-third.log` |
| focused-fourth | 1 | `v24.host.journal.JournalError: journal directory must be private (0700); got 0755: /private/var/folders/s7/nqsvqzc17pz9bh_71pfc2nv40000gn/T/v24-entry-offline-n58ti46f/ui` | `/tmp/v24-m5-focused-fourth.log` |
| focused-fifth | 0 | `[passed] M5 real entry offline contracts; sockets=0; capacity=unmeasured` | `/tmp/v24-m5-focused-fifth.log` |
| runner-first | 1 | `[failed] M4 checks; stopped at nonzero/SKIP; see results.json` | `/tmp/v24-m5-wi1-existing-runner.log` |
| runner-final | 0 | `[passed] M4 private checks; commands=16; exits=0; skips=0; persistent_pgdata_untouched=true` | `/tmp/v24-m5-wi1-existing-r2-runner.log` |
| focused-failclosed-r1 | 1 | `RuntimeError: credentials_absent` | `/tmp/v24-m5-focused-failclosed-r1.log` |

All focused attempts use the exact focused command shown above, with each listed log redirection. `runner-first` used `--log-dir /tmp/v24-m5-wi1-existing-20261103`; its first UI gate ended `AssertionError: actual app prompt helper missing`. The earlier passing runner (`runner-final` in JSON, **before the fail-closed production fix**) used `--log-dir /tmp/v24-m5-wi1-existing-r2-20261103`; it does not certify the later fix. Every wrapper command, exit, log hash and last line is retained in `receipts.json`.

Earlier failures were resolved without weakening gates: first assertion matched prompt text; second counted installation records instead of the run's model mapping; third used macOS's unresolved temporary-directory alias; fourth created a test journal parent with 0755; initial full UI gate required the named app helper; failclosed-r1 created a test adapter after entering the deliberately credential-free helper context. The actual bootstrap incident and prevention are assessed separately above. An initial development `uv run python -` also rewrote root `uv.lock`; only that generated lockfile change was restored, and its hash equals baseline. Subsequent verification used `UV_NO_SYNC=1 UV_NO_ENV_FILE=1`.

### Source hashes and closing state

The following are the actual final source SHA256 values; no production/test source changed after final tests. Full checked-script hashes, frozen-file hashes, log hashes and baseline audit are in `/tmp/v24-m5-wi1-receipts-20261103/receipts.json`.

| Changed/new source | SHA256 |
|---|---|
| `v24/ui/app.py` | `eabd56bf5acba895341ca551ac620dbcd8332ac5dce17b22c119c79a28122f5d` |
| `v24/ui/catalog.py` | `bc272423161e317fe8c53fe3a41d9e13fafd4dd6af67b3a713de3b56e6a32fb5` |
| `v24/ui/control.py` | `2f07bcd35f06c50e2eec0d9f7f0044f61159938461ee180b2053b74202a3b730` |
| `v24/ui/real.py` | `759d663d8604d2bd9a2853566d159ede01597de911aa1e69c14d0732562d1935` |
| `v24/ui/test_real_entry.py` | `7310b71cd63de8b593f28c331e16f89402f0c0f9cbfee55018b48e1374f2dc0d` |

Final read-only baseline comparison: branch `v24/ui-chainlit`, HEAD `a6ba59657c53d3cf1a7e00cc90aad80bf025f617`, main/origin-main `1143dce6da0572bccab083da9a6be0175210b062`. Only the three named tracked source files differ; all 52 original untracked hashes match; index is empty. Protected M4 audit/runner and all host/SQL/schema/load files match baseline. `git diff --check` exits 0, with no output. No staging, commit, push, amend, main mutation, or persistent-state repair/reset occurred.

The post-fix persistent comparison covers 67,330 existing paths, with zero size/mtime_ns/inode/mode differences after final focused and entire checks. It excludes atime and any retrospective logical-state claim.

Remaining acceptance boundary: coordinator inspection of this uncommitted tree and incident assessment. No provider/reconnect blocker was encountered. WI-2 real workflows/capacity evidence, browser acceptance, M5 audit/closing artifacts and final formal review remain unperformed by instruction. Capacity remains unmeasured/None; no budget checkpoint was entered.
