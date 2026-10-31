# v24/s13 — Tool/Plugin ABI W1 vectors, W2 contracts and W3 registry/transport

This stage establishes the W1 contract and fixed vectors for ABI design §10 M1, adds the W2 pure host contract components, and implements W3 registry approval and independent line-json v2 transport. It contains reviewed data, independent Python/Node reference functions, and production host modules. W3 gates use process stubs; dispatcher/worker/provider wiring and filesystem-tool behavior remain downstream work. The W1 inventory and vector format are pinned in [`vectors/README.md`](vectors/README.md) and [`vectors/design_conformance.json`](vectors/design_conformance.json).

## W1 vectors

W1 format: `v24-tool-plugin-abi-w1-vectors-1`, with 10 suites and 71 fixed case IDs. B0 golden vectors/checker and the frozen v24 closeout remain separate; closeout is still 11/11. Descriptor bytes use PostgreSQL `jsonb::text`; request frames, renderers, manifests, and model text each use their own ABI serialization rule. The three renderer digests are frozen as `provisional_w2_pending`; W2 reproduces them byte-for-byte without editing the frozen labels. Artifact digest and timing evidence remain M3-pending; replay behavior remains M4-pending.

Run the read-only checks from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_contracts.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py --node
```

## W2 host contracts

W2 adds five pure modules under `v24/host/`: `canonical.py` (PostgreSQL canonical text, `J`, strict JSON, deep-freeze), `tool_schema.py` (closed schema subset), `renderers.py` (three host renderers, immutable registry, embedded goldens), `descriptor.py` (descriptor v2 validation), and `tool_results.py` (v2 envelopes, model text, budget measurement, frame classification). All five are synchronous, deterministic, and free of file/database/network/clock access.

Run the four W2 gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_descriptor.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_schema.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_renderers.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_results.py
```

Exit 0 with the command-specific `[passed]` marker is passed; exit 2/`[SKIP]` is unverified and blocks W2 completion; exit 1 or a missing marker is failed. W2 covers four of the nine s13 gates; W3 adds `test_registry.py` and `test_line_json.py` below; `test_tools.py`, `test_lifecycle.py`, and `test_node.py` remain downstream.

W2 reproduces 40 W2-domain cases from production code: descriptor 16 (including 9 canonical byte cases), schema 9, renderers 7 (including 21 inner golden cases and three digest pairs), and results 8. The three `m4_pending` result/lifecycle cases are asserted to remain unexecuted. A post-review hardening pass adds internal probes for decoder normalization, the `J` value domain, deep finite values, `ToolDispatchResult` outer-shape checks, renderer exception precedence, and object-shaped schemas; it does not change any vector case ID, status, owner, or expected value. The s13 checks are extension evidence; closeout remains 11/11 and s13 is not a twelfth closeout item. W2 does not prove M2 completion, W3 registry/line-json v2 behavior, W4 dispatcher/worker/provider wiring, filesystem tool semantics, or replay.

## W3 registry approval and line-json v2

W3 adds `ApprovedTool`, `ToolBinding`, `ApprovedPlugin.from_manifest()`, union registry matching, and an independent v2 frame builder/parser selected by the approved entry's protocol. The v1 approval fields and byte behavior remain covered by B0 and W3 compatibility probes.

Run the two W3 gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_registry.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_line_json.py
```

Exit 0 plus the command-specific `[passed]` last line is passed; exit 2/`[SKIP]` is unverified and blocks W3 completion; exit 1 or a missing marker is failed. Registry coverage is 17 cases, three manifest byte cases, 14 construction reasons and six zero-spawn match paths. Transport coverage is 10 cases, seven frame byte cases, all 55 parse rows (46 invalid + nine whitespace), five preflight rejections and four unknown outcomes; the marker also confirms `v1_bytes_unchanged=true`. The final registry gate additionally checks noncanonical bytes/UTF-8 str manifest identity and successful `ApprovedTool` closure recompilation; the transport gate preserves and exercises the v1 `run(adapter=...)` keyword interface. The two gates use stubs and do not open database/network/Node connections or prove real subprocess lifecycle behavior.

The measured 26-command serial run passed every command, including all inherited checks. Evidence and limitations are in the [W3 execution record](../../docs/reviews/v24-tool-plugin-abi-w3-execution-2026-10-31.md). Frozen vector labels remain unchanged (`frames_v2` stays `m2_pending`; artifact evidence stays `m3_pending`). W3 is extension evidence and **does not prove M2 completion**. Closeout remains **11/11**, and s13 is not a twelfth closeout item. Dispatcher/worker/provider wiring, filesystem semantics, pagination, 12-second timing, artifact digest computation and replay remain downstream.

## W4a dispatcher, worker and provider wiring (M2)

W4a wires the W3 approval model and line-json v2 transport into the live paths: `tool_pages.validate_page` enforces the §5.6 success-page relations before rendering, `plugins._tool_v2` follows the fixed thirteen-step order, `worker._execute_tool` uses the handler-provided `model_text`, `deepseek._tools` accepts v2 descriptors, and `registry._ApprovedEntry.environment()` injects the approved `V24_WORKSPACE_ROOT` when the allowlist names it. `w4_stub_plugin.py` is a test asset only; `plugins/fs_read.py` and `plugins/fs_tools.js` remain W4b.

Run the two new gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_pages.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_wiring.py
```

Exit 0 plus the command-specific `[passed]` last line is passed; exit 2/`[SKIP]` is unverified and blocks W4a; exit 1 or a missing marker is failed. `test_pages` is DB-free (5417 page cases, 4281 oracle differentials, two documented reference gaps excluded one-sided). `test_wiring` uses PostgreSQL and local stub subprocesses only; it covers provider projection bytes, handler normalization, six pre-spawn zero-spawn paths (sentinel + `--spawn-log`), eleven end-to-end v2 scenarios, per-tool timeouts, lease using the tool timeout, and the 11-byte model-text vector. It prints `[scope] passed base=c8c4bd0 checks=6` before its marker.

The measured 29-command serial run on base `c8c4bd0` passed every command; rows 14–24 are the eleven frozen closeout commands, so closeout remains **11/11** and s13 is not a twelfth closeout item. **M2 is complete** after W4a: the four M2 gates (`test_descriptor`, `test_registry`, `test_line_json` plus the W4a wiring gate) are green, G9/G10/Node and v1 golden bytes are unchanged, and no real provider was called.

This completion does **not** mean real filesystem tools, pagination convergence, mixed batch, crash/restart, replay, or the 12-second budget are verified. W4b (filesystem read/list/search) and W4c (lifecycle/replay/Node) remain downstream. Evidence, command times, last lines and hashes are in the [W4a execution record](../../docs/reviews/v24-tool-plugin-abi-w4-execution-2026-10-31.md); evidence directory `/tmp/w4a-20261031T025906/`.

## W4b filesystem read/list/search tools (M3 implementation)

W4b adds the real v2 tool plugins `v24/s13/plugins/fs_read.py` (Python `read`) and `v24/s13/plugins/fs_tools.js` (one Node install providing `list` + `search`), plus `v24/s13/fixtures.py` and `v24/s13/test_tools.py`. The fixture layer materializes the reviewed vector trees, builds v2 manifests with the SQL-compatible adapter digest, and reuses `v24/s11/plugin_fixtures.PluginHarness` for the DB-backed integration cases.

Run the W4b gate from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_tools.py
```

The macOS-first run reports `[evidence] non_utf8_source=preload_shim; linux_real=not_run` before the marker. APFS rejects raw non-UTF-8 filenames, so the fixture probe selects a test-only Node preload (`v24/s13/w4b_non_utf8_preload.cjs`) that appends exactly one `0xff` directory entry for the designated root; the production plugins contain no test seam. Linux uses a real `b"\xff"` name and reports `non_utf8_source=filesystem`; `linux_real` remains pending until that run is executed. The shim is guarded by preload preflight, control-directory, ledger and list/search differential assertions; the frozen vector `expected`/`status` values are unchanged.

The measured 30-command serial run on base `3d95d5f` passed every command; rows 14–24 are the eleven frozen closeout commands, so closeout remains **11/11** and s13 is not a twelfth closeout item. The W4b marker is:

```text
[passed] W4 fs tools; cases=74; read=16; list=7; search=24; pagination_converged=true; page_contracts_imported=3
```

**M3 implementation is complete, but timing/cutoff is pending.** This is not an M3-complete declaration: the 12-second scan budget and cutoff page-fill timing are not proven, and `tool.search_budget_timing_m3_pending` remains `m3_pending`. W4c (lifecycle/replay/Node) remains downstream. Evidence and limitations are in the [W4b execution record](../../docs/reviews/v24-tool-plugin-abi-w4b-execution-2026-10-31.md); evidence directory `/tmp/w4b-20261031T043334/`.

## W4c lifecycle, replay and Node extension

W4c adds `v24/s13/test_lifecycle.py` (G12-A…H + G12-L, mixed batch and journal replay) and `v24/s13/test_node.py` (one Node install, list + search, real lifecycle). It uses the real Python/Node subprocesses, the local PostgreSQL test database and the existing journal replay path; no provider socket is opened.

Run the two W4c gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_lifecycle.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_node.py --node
```

The measured 32-command serial run on base `80dc0c4` passed every command; rows 14–24 are the eleven frozen closeout commands, so closeout remains **11/11** and s13 is not a twelfth closeout item. The W4c markers are:

```text
[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true
[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node
```

The replay section proves `replay_source=journal tool_message`, `rerender=false`, `second_spawn=false` and `journal_event_types_unchanged=true`; the three replay-related `m4_pending` vectors are executed but retain their `status` field. Node missing is an explicit `[SKIP]` exit 2 and is not recorded as a pass. **M4 is complete** for this gate, but W4b's **M3 implementation timing/cutoff remains pending**; `tool.search_budget_timing_m3_pending` stays `m3_pending` and no 12-second wall-clock gate was added. Evidence and limitations are in the [W4c execution record](../../docs/reviews/v24-tool-plugin-abi-w4c-execution-2026-10-31.md); evidence directory `/tmp/w4c-20261031T044427/`.

## W5 Python read closeout (2026-10-31)

W5 closes the Python `read` implementation and evidence gaps within the existing W4b tool: bounded two-pass scanning on one file descriptor, additive four-domain candidate measurement including continuation footers, empty-page budget checks, hardened open and best-effort file-change detection. The frozen 16 read cases remain byte-identical; 29 new read probes are counted separately. The existing gate command is unchanged:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_tools.py
```

The final serial sweep reports:

```text
[evidence] read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c; read_1m_wall_ms=113; read_peak_kib=3959.904; permission_probe=real
[passed] W4 fs tools; cases=103; read=16; read_probes=29; list=7; search=24; pagination_converged=true; page_contracts_imported=3
```

The wide 1,047,999-byte input succeeds through the DB-backed executor within the unchanged 5000 ms host deadline; the measured peak for the wide/newline memory probes is below 8 MiB. Earlier W5-4 verified runs recorded 92–93 ms; 113 ms is this final sweep's actual observation, not a new timing threshold. The hardware-independent serialization probe and the real host deadline remain the guards.

All 32 required commands exited 0 in order: commands 1–31 have their exact command-specific markers; command 32 is the SQL diff with empty output. No exit 2 or `[SKIP]` occurred. Seven scope audits are recorded as a precheck and rerun after documentation, immediately before staging. Closeout remains **11/11**; s13 is extension evidence, not a twelfth closeout item. **M3 timing/cutoff remains pending**: `tool.search_budget_timing_m3_pending` stays `m3_pending`; `linux_real=not_run` and the frozen manifest pending labels are unchanged. No design, pin, host, SQL, Node plugin or frozen-vector behavior changes belong to W5.

The [W5 execution record](../../docs/reviews/v24-tool-plugin-abi-w5-execution-2026-10-31.md) contains provenance, source/artifact digests, the 32-row serial table, seven audits, deviations and limits. Raw evidence is in `/tmp/w5-20261031T063812Z/`.

## W6 Node list/search closeout (2026-10-31)

W6 closes the Node `list`/`search` compliance and evidence gaps within the existing W4b install. Only `v24/s13/plugins/fs_tools.js` changes production behavior; `fixtures.py` adds `node_workspace`, and `test_tools.py` adds `js_call`, strict `check_error`, 11 list probes and 26 search probes. Search now records `stopReason ∈ {eof, sentinel, file-cap, time-cap}`, applies the §5.6 post-selection rule (a cutoff page succeeds only when the selected `k = m = limit`, or `k < m`), and checks `SCAN_BUDGET_MS = 12000` at C0 (before the walk) and C1 (directory before recursion, regular file after the file-cap check). Slashless globs match the basename, `offset`/`limit` use `Number.isSafeInteger`, page/footer arithmetic uses BigInt-backed `addSafe`, and empty list/search pages pass all four output budgets. The test-only seam is the optional third `options` argument; there are no new env/argv switches.

The existing gate command is unchanged:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_tools.py
```

The final serial sweep reports:

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
```

The 37 new probes cover the five file-cap shapes, four time-cap shapes, EOF/sentinel priority, no-fitting-prefix and empty-page budgets, slashless/slash/`?`/`**` glob behavior, glob accounting, safe-integer and footer overflow, precheck counters, context rendering/measurement, code-point columns and truncation, hidden/`.git`, and the eleven list boundaries (byte-full pagination, injected caps/scanLimit, nested `.git`, symlinks/specials, root non-UTF-8, UTF-8 order, offset/empty, defaults and content equality). S24 also asserts the constant/descriptor/source structure, the three-way artifact digest and tamper rejection, and host exit-3 passthrough for `output_too_large`/`invalid_tool_output`.

The three 12-second evidence layers are kept separate: T1 deterministic injected-clock branches through the production `searchTool` (S06–S11); T2 constant/descriptor/source assertions (S24: 12000, 15000, margin 3000, `process.env` only in `rootPath`, `hrtime` only in `searchTool`); T3 one real-clock observation (S25: `real_clock_elapsed_ms=50.331`, overshoot `0.331`, no elapsed threshold). S26's hard assertion is the 600-call `JSON.stringify` count; `enum_cost_wall_ms=126.674` is recorded only. This does **not** prove a 12-second wall-clock guarantee and is **not an M3-complete declaration**: `tool.search_budget_timing_m3_pending` stays `m3_pending`, and C.18 remains for the later M3 declaration stage.

The measured 32-command serial run on base `82e5440` passed 32/32; rows 14–24 are the eleven frozen closeout commands, so closeout remains **11/11** and s13 is not a twelfth closeout item. The seven scope audits (six inherited `c8c4bd0` checks plus the `82e5440` W6 delta with path+sha256 untracked comparison) passed both the precheck and the post-documentation final run. The `fs_tools.js` source, installed copy and approved-entry SHA-256 are all `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`; `fixtures.py` is `f2b5b84d9539ad9580645cabb15bf92dd169bb6a75b00c2eb1f25f069ac99bf5` and `test_tools.py` is `4df195f18d9583d920e64b1e5a5715d3626b97abdc00ffb0313651879d992d92`. `linux_real=not_run`; L07 covers only the root-level non-UTF-8 entry. The [W6 execution record](../../docs/reviews/v24-tool-plugin-abi-w6-execution-2026-10-31.md) contains provenance, the 32-row table, audits, deviations and limits; evidence is in `/tmp/w6-20261031T113313Z/`.

## Execution

Capture is candidate generation, not a gate. It requires two fresh external destinations and byte comparison before promotion. Checkers are read-only, have no re-bless mode, and do not execute production tools.

2026-10-30 W1 execution: both independent captures matched byte-for-byte; contract inventory passed (10 suites/71 cases); Python/PostgreSQL/Node fixed-vector comparison passed (9 canonical cases); all 20 final serial W1/B0/inherited checks passed, recorded in the [`W1 execution record`](../../docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.

2026-10-30 W2 execution: the four W2 gates plus all 20 inherited W1/B0/closeout/G9/G10/Node/multilingual commands exited 0 with no exit 2/SKIP; evidence is recorded in the [`W2 execution record`](../../docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.
