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

W2 adds five pure modules under `v24/host/`: `canonical.py` (PostgreSQL canonical text, `J`, strict JSON, deep-freeze), `tool_schema.py` (closed schema subset), `renderers.py` (four host renderers — the three `v24.fs.*` renderers plus the W9 additive `v24.text.plain` — immutable registry, embedded goldens), `descriptor.py` (descriptor v2 validation), and `tool_results.py` (v2 envelopes, model text, budget measurement, frame classification). All five are synchronous, deterministic, and free of file/database/network/clock access.

Run the four W2 gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_descriptor.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_schema.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_renderers.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_results.py
```

Exit 0 with the command-specific `[passed]` marker is passed; exit 2/`[SKIP]` is unverified and blocks W2 completion; exit 1 or a missing marker is failed. W2 covers four of the nine s13 gates; W3 adds `test_registry.py` and `test_line_json.py` below; `test_tools.py`, `test_lifecycle.py`, and `test_node.py` remain downstream.

W2 reproduces 40 W2-domain cases from production code: descriptor 16 (including 9 canonical byte cases), schema 9, renderers 7 (including 21 inner golden cases and three digest pairs, unchanged from W1), and results 8. `test_renderers.py` reads `renderers.json` and, since W9, `v24/s13/vectors/text_plain_v1.json` as well: the registry holds 4 renderers, and the text suite runs 9 positives through both layers (renderer and page) and 21 negatives through exactly one declared layer. The three `m4_pending` result/lifecycle cases are asserted to remain unexecuted. A post-review hardening pass adds internal probes for decoder normalization, the `J` value domain, deep finite values, `ToolDispatchResult` outer-shape checks, renderer exception precedence, and object-shaped schemas; it does not change any vector case ID, status, owner, or expected value. The s13 checks are extension evidence; closeout remains 11/11 and s13 is not a twelfth closeout item. W2 does not prove M2 completion, W3 registry/line-json v2 behavior, W4 dispatcher/worker/provider wiring, filesystem tool semantics, or replay.

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

W4a wires the W3 approval model and line-json v2 transport into the live paths: `tool_pages.validate_page` enforces the §5.6 success-page relations before rendering (since W9 it consults a sibling `TEXT_PAGE_CONTRACTS` table after `BUILTIN_PAGE_CONTRACTS`, i.e. BUILTIN-then-TEXT dispatch; `contracts=3`, the kind map and the limit map remain BUILTIN-only), `plugins._tool_v2` follows the fixed thirteen-step order, `worker._execute_tool` uses the handler-provided `model_text`, `deepseek._tools` accepts v2 descriptors, and `registry._ApprovedEntry.environment()` injects the approved `V24_WORKSPACE_ROOT` when the allowlist names it. `w4_stub_plugin.py` is a test asset only; `plugins/fs_read.py` and `plugins/fs_tools.js` remain W4b.

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

## M3 declaration (2026-11-01)

Design Appendix C.18 is the authority for this declaration. **M3 is complete under the C.18 evidence standard**: W5 supplies the read evidence, W6 supplies the list/search evidence, and this run supplies the fresh 32-command sweep and seven scope audits. The frozen 16 read, 7 list and 24 search outputs remain byte-identical; no vector, pin, host or SQL behavior was promoted.

The 12-second evidence is three separate layers and is not merged: T1 deterministic injected-clock branches through the production `searchTool` (S06–S11); T2 constant/descriptor/source assertions (S24: `SCAN_BUDGET_MS=12000`, search `timeout_ms=15000`, margin 3000); T3 one real-clock observation (S25: `real_clock_elapsed_ms=50.463`, overshoot `0.463`, recorded only, no elapsed threshold). This run's read evidence is `read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`, `read_1m_wall_ms=97`, `read_peak_kib=3959.904`, with R26 succeeding under the unchanged 5000 ms host deadline. The Node artifact remains `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`.

Appending C.18 changed the design from 113843 bytes / `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` to 121521 bytes / `778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d`; the old bytes are an exact prefix, and all 25 references to 23 pinned spans retain their line ranges, headings and content SHA. `design_conformance.json` changed only `design_input.sha256_at_review`; `test_contracts.py` changed only `DESIGN_SHA256`.

The measured 32-command serial run passed 32/32, with exact command-specific `[passed]` last lines for rows 1–31 and empty output for the SQL diff; no exit 2 or `[SKIP]` occurred. The seven scope audits passed the precheck and the post-documentation final run. Rows 14–24 are the eleven frozen closeout commands: closeout remains **11/11**; s13 is extension evidence, not a twelfth item.

**This section supersedes the earlier W4b/W4c/W5/W6 sentences that say “not an M3-complete declaration” or “M3 timing/cutoff remains pending”; those paragraphs remain as stage records.** Under C.18.6, `tool.search_budget_timing_m3_pending` stays the frozen `m3_pending` provenance token; the frozen manifest `"M3-pending"` placeholders and `compatibility.*_claimed=false` are unchanged. The declaration does not claim a hard real-time 12-second bound, Linux real coverage, or subdirectory non-UTF-8 coverage: `linux_real=not_run`, and the platform evidence remains macOS root-level shim.

## M5 closeout (2026-11-01)

**M5 is complete under design §10 and C.18.1.** §7.5 items 1–3 are executed: main design §5.1/§5.4 are revised inline (lines 275/297) with a dated Appendix C.7 entry, and the drift-factcheck D2/D3/D4 carry dated M5 notes. Items 4–5 were already delivered by the W1–W6 ledger/matrix increments; this closeout appends the M5 sections without rewriting history.

All 34 frozen `status` positions are adjudicated in the [M5 section of the conformance matrix](../../docs/reviews/v24-conformance-matrix-2026-10-23.md) — 10 `design_conformance` suites, 8 `tool_contracts`, 5 `manifest_adapter_v2`, 11 `results_v2`. The script-derived counts are 8/10/5/11, and the 2 `design_resolved` decisions are excluded. The verdict set is 28 `E-SAT`, 3 `E-SAT-T`, 2 `E-SAT-PH` and 1 `FROZEN-EXPECTED`; no token was promoted, no JSON byte changed, and both `"M3-pending"` placeholders remain.

The M5-0 vectors baseline is the actual M3 commit `e58204c29afacd27b72e35e9e7eaeb6e32c11dac`, not `2307077`: `git diff --exit-code e58204c -- v24/s13/vectors` is empty, and `git diff --exit-code e58204c -- v24/sql` is empty. The 32-command serial sweep passed 32/32 with exact command-specific last lines for rows 1–31 and empty SQL output; seven scope audits passed precheck and the post-documentation final run. Rows 14–24 remain the eleven frozen closeout commands: **closeout stays 11/11**; s13 is extension evidence, not a twelfth item.

This run's artifacts remain `read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c` and Node source/copy/entry equality for `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`; `read_1m_wall_ms=97`, `read_peak_kib=3959.904`, and S25 `real_clock_elapsed_ms=50.635` / overshoot `0.635`. The declaration still does not claim a hard real-time 12-second bound, Linux real, subdirectory non-UTF-8 coverage, or automatic tool re-execution; `linux_real=not_run`. Full commands, times, hashes, audits and limits are in the [M5 execution record](../../docs/reviews/v24-tool-plugin-abi-m5-closeout-execution-2026-11-01.md); evidence directory `/tmp/v24-abi-m5-20261031T164407Z/`.

## W7 lifecycle and recovery closure (2026-11-01)

W7 is a post-M5 recovery-closure stage, not a new design §10 milestone: M4 stays complete under C.11 and M5 stays complete. It closes the three gaps named by the W4c record — every crash window (enumerated as K0–K5 plus K3.5), mixed-batch replay with multiple pending tools, and a real process restart — without changing host, SQL, vectors, design pins or any frozen test.

The gate command is unchanged:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_lifecycle.py
```

The final serial sweep reports:

```text
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
```

`cases=30` uses function-level counting: the 14 W4c sub-scenarios (A1+B1+C1+D3+E1+F3+G1+H1+L2) plus one case per R01–R16. `recovery_probes=16` is fixed; R11's four artifact shapes, R13's restart stage, R14's success/known-error/crash stages, R15's three pending effects and R16's backfill are sub-probes of one case each. The file grew from 645 to 2,849 lines; the measured gate wall time is ≈40.4 s, and the sweep's row-30 window is `2026-10-31T20:03:34Z` → `2026-10-31T20:04:14Z`, below the 90 s cap.

| Window | Crash point | Cases |
|---|---|---|
| K0 | `effect_prepared` written, `dispatch_started` not written | R01 (tool), R07 (`host_prepare`), R08 (`host_release`) |
| K1 | `dispatch_started` written, handler not entered | R02 |
| K2 | after a real plugin spawn, before `dispatch_finished` | R03 (host child `SIGKILL`, real plugin process) |
| K3 | `dispatch_finished` written, settlement not written | R04 (model), R05, R10, R14 (v1), R15 (3 pending) |
| K3.5 | DB settlement committed, journal `settlement_committed` not written | R16 |
| K4 | after settlement | R06 |
| K5 | model `dispatch_finished` written, settlement not written | R04 |

R09 (mixed batch: two successes and one timeout, with the read executing last), R11 (four disk-artifact tamper shapes), R12 (workspace root moved away) and R13 (timeout process-group cleanup) are orthogonal pre-spawn/timeout probes, not new K labels.

Two test-only assets carry the evidence. `w4_stub_plugin.py` adds the `grandchild` scenario (a grandchild that stays in the plugin process group) and the `kill_parent` scenario (the plugin `SIGKILL`s its host parent after spawn); `kill_parent` is selected only by R03's `stub_spec` and is not used by any production descriptor, fixture module or other scenario. `w7_recover.py` is the fresh-process reconciler: it opens only `HostDB`/`HostJournal`, calls `_reconcile`, never constructs a registry and never spawns, and prints `[w7-recover] reconciled=N settlements=M`; `settlements` is this process's journal increment. R05/R06/R15/R16 and the v1/v2 recovery in R14 use it.

The fresh-process results are `R05 reconciled=1 settlements=1`, `R06 reconciled=0 progress=0`, `R15 reconciled=3 settlements=3` after three pending settlements, and `R16 reconciled=0 settlements=1` with payload `reason=database_terminal` / `conflict=false`. R03's host child ends `WIFSIGNALED` with `WTERMSIG=SIGKILL(9)` and the plugin `invoke` count stays 1 before and after recovery; R13 observes both the plugin and its grandchild as empty `ps -o stat=` states after 1.131 s without any signal from the test side.

W7 adds no host, SQL, vector, fixture-module, design or pin changes. `git diff --exit-code a41ce22 -- v24/host v24/sql v24/s13/vectors` is empty, the B0 v1 provider-request and tool-message bytes are unchanged, and all tool effects remain `no_replay`. Closeout remains **11/11**; s13 is extension evidence, not a twelfth closeout item.

The [W7 execution record](../../docs/reviews/v24-tool-plugin-abi-w7-execution-2026-11-01.md) contains provenance, source digests, the 32-row serial table, seven audit tables, R15/R16 fresh-process evidence, R03/R13 cleanup observations, limits and deviations. Raw evidence is in `/tmp/v24-abi-w7-20261031T200002Z/`; the publication receipt there records the commit/push outcome externally.

## W8 v1 acceptance（2026-11-01）

W8 是 design §7.4 done-when 1–8 的首次逐项验收，不是 M6，不是 M5 重做，也不新增 M 阶段。M1–M5 与 W7 的既有 authority 不变：M4 按 C.11 完成，M5 按 C.18.1/C.18.7 完成，W7 是 M5 之后的恢复收口；W8 只链接这些声明，不重新裁决 34 个冻结 `status` 位置，也不做 promotion。

本轮实际执行日为 2026-11-01（+08:00），`HEAD_sweep=5dcbf633ca7b08e171255ee3cf2900d0e5dd6008`，`origin/main` 同点。冻结的 32 条串行命令全部 exit 0，第 1–31 条末行精确匹配，第 32 条 SQL diff 输出为空；无 exit 2/`[SKIP]`。**32/32**；closeout 仍 **11/11**；s13 是 extension evidence，不是第 12 条。SUP-1 在 row 32 之后独立运行，exit 0，末行 `[pass] B0-2 DB-only multi-provides probe; zero process spawns`；它是 W8 自加的补充观察，不进入八项裁决，不占 row 33，也不是第 12 条。

八项 projection 为 1 PASS、2 PASS、3 PASS、4 PASS、5 PASS-LIMITED、6 PASS、7 PASS、8 PASS；17 个 canonical token 与 17 行 register 见 [W8 execution record](../../docs/reviews/v24-tool-plugin-abi-w8-execution-2026-11-01.md)，8 行投影与三张残余债务表见 [conformance matrix](../../docs/reviews/v24-conformance-matrix-2026-10-23.md) 的 W8 小节。七项 scope audit 已完成 precheck 7/7；final 7/7 见 record 的 final 表；confirmation 只记外置 receipt，不成为第二张仓库内审计表。

当前 row-29/30/31 marker：

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true
[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node
```

不声明硬实时 12 秒上界；C.18.3 的 T1/T2/T3 保持分层。`linux_real=not_run`；非 UTF-8 文件名证据仅为 macOS root-level shim，不覆盖子目录真实非法名称。不声明工具自动重执行，tool 仍为 `no_replay`。不承诺慢 scope 的分页收敛。不调用真实 provider，不进行 gate 对外网络访问；"无网络"是逐行构造论证，不是 OS 级隔离证明。

以下 supersedes **只作用于"当前状态查询"用途**，原文保留、不改字节：

- 开篇 "dispatcher/worker/provider wiring and filesystem-tool behavior remain downstream work"；
- W1 的 artifact/timing/replay pending 当前状态表述（冻结 token 的 provenance 含义仍保留）；
- W4a 的 W4b/W4c downstream 表述；
- W4b/W4c/W5 的 "M3 timing/cutoff remains pending"；
- W6 的 "not an M3-complete declaration" 与 "C.18 仍待后续声明"；
- W4c 小节的 `cases=14` marker（`:100`）。

这些 supersedes 不抹掉真实的阶段证据边界；例如 "W2 单独不能证明 M2" 仍然有效。W8 只更新整个系列当前状态的读法，并把当前权威值指向 `cases=30; recovery_probes=16`（本文件 `:184` 与 W7 record 的 row 30）。证据目录 `/tmp/v24-abi-w8-20261101T033123Z/`；发布 commit/push 结果只进外置 `publication-receipt.txt`，不进入本节。

## Execution

Capture is candidate generation, not a gate. It requires two fresh external destinations and byte comparison before promotion. Checkers are read-only, have no re-bless mode, and do not execute production tools.

2026-10-30 W1 execution: both independent captures matched byte-for-byte; contract inventory passed (10 suites/71 cases); Python/PostgreSQL/Node fixed-vector comparison passed (9 canonical cases); all 20 final serial W1/B0/inherited checks passed, recorded in the [`W1 execution record`](../../docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.

2026-10-30 W2 execution: the four W2 gates plus all 20 inherited W1/B0/closeout/G9/G10/Node/multilingual commands exited 0 with no exit 2/SKIP; evidence is recorded in the [`W2 execution record`](../../docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.

2026-11-02 W9 execution (updated by the same-day follow-up hardening): all 13 s13 gates exited 0 in one serial sweep (Node `v24.13.1` present, so `test_node.py --node` printed `[passed]`, not `[SKIP]`/exit 2). `test_wiring` now asserts **whole-module AST equality** of `v24/host/renderers.py` against `c8c4bd0` after stripping exactly the five documented W9 additive nodes (`_TEXT_KEYS`, `_TEXT_STATUS`, `_text`, `_GOLDEN["text"]`, and the `v24.text.plain` `_BUILTIN_SPECS` element), in addition to the old three renderers' source-segment pins (the `_GOLDEN` dict literal and the three old `_BUILTIN_SPECS` tuples) and the `v24/s13/vectors/text_plain_v1.json` allowance. Each strip must match exactly once, so a deleted or duplicated additive node fails rather than quietly shrinking or widening the additive surface; a mismatch dumps a `difflib` unified diff of both ASTs. The earlier narrow 2026-11-02 amendment pinned only the golden dict plus those three tuples and is superseded by this closed-world check. No SQL, no real provider, no network; evidence is in the [W9 record](../../docs/reviews/v24-tool-plugin-abi-w9-text-plain-2026-11-02.md).
