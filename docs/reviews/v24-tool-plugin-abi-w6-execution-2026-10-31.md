# v24 Tool/Plugin ABI W6 execution record

Date: 2026-10-31 (+08:00). Scope: Node `list`/`search` closeout in the [W6 plan](../plans/v24-tool-plugin-abi-w6-node-list-search-2026-10-31.md), within design §10 M3. W6-0…W6-5 were completed before this closeout run; W6-6 is the sweep, W6-7 the documentation and final audit, and W6-8 the publication. W6 does **not** complete M3: search timing/cutoff remains `m3_pending`.

## Result

The required 32 commands ran serially in the plan's order and all exited 0. The first command started at 2026-10-31T11:43:16Z and the last command started at 2026-10-31T11:45:24Z; these are command start times, not a measured end-to-end duration. Commands 1–31 ended in their exact command-specific `[passed]` lines. Command 32 was the pinned SQL diff: exit 0, a zero-byte log, an empty last-line field, and no `[passed]`. No exit 2, `[SKIP]` or missing required marker occurred.

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
```

Rows 14–24 are the eleven frozen closeout commands. Closeout remains **11/11**; s13 is extension evidence, not a twelfth item. W6 closes the Node list/search compliance and evidence gaps; **M3 timing/cutoff remains pending**, `tool.search_budget_timing_m3_pending` stays `m3_pending`, and `linux_real=not_run`.

## Candidate and provenance

- Checkout `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `82e5440012c2fa38a9ec63f86acc8c676a7ab500` (W5 closeout).
- Environment: uv `0.8.24 (252f88733 2025-10-07)`, Python `3.14.6`, Node `v24.13.1`, Darwin `25.6.0` / macOS `26.6.2` / arm64; local PostgreSQL and real local plugin subprocesses.
- Exactly nine candidate paths: `v24/s13/plugins/fs_tools.js`, `v24/s13/fixtures.py`, `v24/s13/test_tools.py`, `v24/s13/README.md`, `docs/reviews/v24-conformance-matrix-2026-10-23.md`, `docs/reviews/v24-deviation-ledger-2026-10-23.md`, this execution record, `docs/reviews/v24-tool-plugin-abi-w6-plan-critique-2026-10-31.md`, and `docs/plans/v24-tool-plugin-abi-w6-node-list-search-2026-10-31.md`.
- Evidence directory `/tmp/w6-20261031T113313Z/`. It contains provenance, the initial porcelain and untracked path+sha256 snapshot, red-baseline logs/summary, W6-2…W6-5 checkpoints, `01.log`–`32.log`, `results.tsv`, `merged.log`, `scope-precheck/` and the seven precheck logs. The final audit, final source manifest and final porcelain are written by the W6-7/W6-8 rerun below; the publication receipt records the actual commit SHA externally.

The implementation bytes at the sweep boundary are:

| Source / artifact | SHA-256 |
|---|---|
| `v24/s13/plugins/fs_tools.js` (source, installed copy and approved entry) | `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5` |
| `v24/s13/fixtures.py` | `f2b5b84d9539ad9580645cabb15bf92dd169bb6a75b00c2eb1f25f069ac99bf5` |
| `v24/s13/test_tools.py` | `4df195f18d9583d920e64b1e5a5715d3626b97abdc00ffb0313651879d992d92` |
| Unchanged ABI design | `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` |

The three `fs_tools.js` digests are equal, and `spec.entry.require_artifact()` accepted the copy; S24 flips one installed byte and observes `artifact_digest_mismatch` before restoring the original and re-verifying the digest.

Stable evidence digests:

| Evidence file | SHA-256 |
|---|---|
| `results.tsv` | `ba8e458ca3fb35864324f1deba4e763c00585c7a001a5f67ae20108d297db7be` |
| `merged.log` | `6e56c9a8d6c0418f143a73f37adff4bf7ef667cd8742d04c73f1f5f98daeef28` |
| `provenance.txt` | `ca6a6bdc9aa7c5a42b7e036a1516cdfb19ed8a06b5e1c17409274f4f9eccb7c4` |
| `baseline-untracked.txt` | `eef8c749c619bae8d6948ec11fdc4bba33551b2fc8b1c6fc212084356ccf4ece` |
| `red-baseline.log` | `baf039f772a4e38c0805c1376cba74aac13753157b61ab73b873855c013a1bef` |
| `red-baseline-summary.tsv` | `f5802380cae5c1f5aa0a9db3b7b5b4fdd592603ef53ce7a18118e261d1692981` |
| `red-baseline-details.txt` | `7cb35d77d4e65a728b5a5768a0648f1326323f147f9827988368db9cba18188d` |
| `scope-precheck/scope-audit.tsv` | `e039728e1f8a779ccb72ebc21987628a3e59cce3d9a4b220c7b68e18b6285310` |

Every sweep command used exactly this prefix, including the final SQL diff:

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

The runner launches one producer at a time from the repository root, redirects stdout/stderr to its numbered log, and captures the producer's return code directly. The TSV stores the fully expanded command, UTC start, exit code, real last line and log SHA-256. No pipeline/tail supplies an exit code or synthesizes a marker. Empty SQL output is an empty string in the TSV; `<empty>` in the table below is presentation only.

## Implementation and coverage

W6 makes one production-file change. `fs_tools.js` replaces the two booleans `stopped`/`scopeExhausted` with `stopReason ∈ {eof, sentinel, file-cap, time-cap}`; removes the early `scopeExhausted && total < offset+limit` guard; applies the §5.6 post-selection rule (a cutoff page succeeds only when the selected `k = m = limit`, or `k < m`); adds the `SCAN_BUDGET_MS = 12000` budget with C0 (once before the walk) and C1 (directory before recursion, regular file after the file-cap check) clock reads; changes glob compilation to `{regex, basenameOnly}`; validates `offset`/`limit` with `Number.isSafeInteger`; routes page/footer arithmetic through BigInt-backed `addSafe`; checks all four output domains for empty and non-empty pages; and accepts an optional third `options` argument (`now`, `budgetMs`, `fileLimit`, `scanLimit`, `caps`, `trace`). `fixtures.py` adds `node_workspace`; `test_tools.py` adds `js_call`, strict `check_error`, 11 list probes and 26 search probes, and the extended marker.

| Coverage | Implementation / evidence | Result |
|---|---|---|
| S01–S05 | file-cap count-full, byte-full (`k<m`), before-fill, before-offset and empty | Passed; S01 returns the 2-hit `cutoff_count_full` shape with `scanned_files:10000` |
| S06–S11 | injected clock: time-cap count-full/before-fill/before-offset/empty, EOF priority, sentinel priority | Passed; `trace.nowCalls` 4/4/4/3/2/3/4 and stop reasons match |
| S12 | no fitting value/content/meta/frame prefix; `fileLimit:1`; empty `output_too_large`; offset priority | Passed |
| S13–S15 | slashless glob matches basename; slash glob and `**`/`?` unchanged | Passed; old code returned 0 hits for `*.py` and 1 for `?.txt` |
| S16 (a–d) | unsafe offset/limit, huge offset, `addSafe` overflow, footer overflow | Passed; direct-frame offset is `invalid_path`, 2^53 rounding does not produce a page |
| S17 | glob-excluded files still count toward `scanned_files` and the 10000 file budget | Passed; `scanned_files=3`, `fileLimit:2` => `search_scope_too_large` |
| S18–S23 | precheck order/counters, whole-file long-line skip, context rendering/measurement, code-point column, 500-code-point truncation, hidden/`.git` | Passed |
| S24 | 12000/15000/margin constants, source structure, `process.env` only in `rootPath`, `hrtime` only in `searchTool`, exports, digest/tamper and host exit-3 passthrough | Passed |
| S25 | one real-clock observation with `budgetMs=50` over 10,000 files | `real_clock_elapsed_ms=50.331`, overshoot `0.331`; result was the allowed cutoff/empty outcome; no elapsed threshold |
| S26 | all-prefix enumeration cost | `json_stringify_count=600` (200 candidates × 3 domains), `enum_cost_wall_ms=126.674`; wall time recorded only |
| L01–L11 | byte-full pagination, injected caps/scanLimit, nested `.git`, hidden subtree, symlink/special, root non-UTF-8, UTF-8 order, offset/empty, defaults and content equality | Passed; L07 remains root-level only |
| Compatibility | frozen 16 read / 7 list / 24 search cases; contracts, vectors, registry, line-json, B0, DB gates, lifecycle and Node gates | All passed; no frozen expected/status/pin change |

The red baseline was measured against `82e5440` before the implementation. Old S01 returned `search_scope_too_large`; old S13 returned 0 hits for `*.py`; old S15 returned 1 hit for `?.txt`; old unsafe offset returned `offset_out_of_range` while unsafe limit already returned `invalid_path`; old S24 had no `SCAN_BUDGET_MS`/`addSafe`/`searchTool`/`listTool`/`emptyMeasures` exports. S14, S17(a), S18–S23, L01, L03(a)(c), L04–L11 were green guards; S02–S12 (except S14), S16(b)–(d), S17(b), S24's digest/host sub-assertions, S25 and L02/L03(b) were green-only because the old module did not expose the seam. The 74 frozen cases were green before the edit (`cases=103` including W5's 29 read probes).

**12-second evidence is three separate layers, not a wall-clock guarantee.** T1 is the deterministic injected-clock branch exercised through the production `searchTool` (S06–S11); T2 is the constant/descriptor/source-structure assertion (S24: 12000, 15000, margin 3000, `process.env` only in `rootPath`, `hrtime` only in `searchTool`); T3 is one real-clock observation (S25) whose elapsed value is recorded and is not a pass condition. `tool.search_budget_timing_m3_pending` remains `m3_pending`; C.18 belongs to the later M3 declaration stage.

## Scope and compatibility audits

All seven checks passed the precheck. Their command start times span 2026-10-31T11:45:30Z–11:45:33Z. The release procedure reruns the entire set after all documentation and immediately before staging; that final run replaces the top-level scope table/logs. The table records the precheck last lines; the final run must reproduce them with exit 0.

| # | Check | Base | Exit | Actual last line |
|---|---|---|---:|---|
| 1 | Frozen modules/s13 tests and no new frozen-directory files | `c8c4bd0` | 0 | `[scope] passed frozen_modules_and_untracked` |
| 2 | Vectors except design metadata | `c8c4bd0` | 0 | `[scope] passed vectors_except_design_conformance` |
| 3 | Design-conformance restoration after SHA substitution | `c8c4bd0` | 0 | `[scope] passed design_conformance_restore` |
| 4 | Registry exact D12 patch and whole-file equality | `c8c4bd0` | 0 | `[scope] passed registry_exact_patch` |
| 5 | Host import purity | `c8c4bd0` | 0 | `[scope] passed host_import_purity` |
| 6 | SQL zero diff | `c8c4bd0` | 0 | `[scope] passed sql_zero_diff` |
| 7 | Tracked W6 delta union changed/new/removed untracked is a nine-path candidate subset | `82e5440` | 0 | `[scope] passed w6_candidate_only` |

Audit 1 extends the inherited frozen check to the W2/W3 s13 test/reference files and asserts `test_contracts.py` restores byte-for-byte after replacing only its design SHA with the `c8c4bd0` value. W4/W5-added files cannot be zero-diff against `c8c4bd0`; the W6 addition freezes `v24/host`, `v24/sql`, `v24/s13/vectors`, `docs/designs`, `fs_read.py`, the preload and the specified s13 tests/references at `82e5440`, excluding only the three W6 code/test paths. Audit 7 uses the original W6-0 `baseline-untracked.txt` (`<sha256>  <path>`) and compares both paths and content digests, so an unchanged path with changed bytes is a delta. The pre-existing `.ctx-export-*`, `.token-probe*`, `ctx_export_check*`, M3 investigation and `v20/experiments/ce_native_d5/**` remain outside the candidate set and outside staging. The plan and critique are themselves candidate paths; the execution record is the ninth.

## Final 32-command serial run

Every command below is prefixed by the exact `$ENVPFX` expansion above. Start times are UTC; last lines and log digests come directly from the producer logs.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T11:43:16Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T11:43:45Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T11:43:49Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T11:43:50Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T11:43:50Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T11:43:51Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T11:43:52Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T11:43:52Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T11:43:53Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T11:43:53Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T11:43:55Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T11:43:58Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T11:44:00Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T11:44:02Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T11:44:02Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T11:44:04Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T11:44:06Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T11:44:09Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T11:44:11Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T11:44:20Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `58ca20e5606ab6c61c9bb9f1a7e256e73271fe9d681d18a49577f30648ea282e` |
| 21 | 2026-10-31T11:44:24Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `0611fc29c59fd48858d422421fd52cd1e5723c2b460045e9e967e88b80be978c` |
| 22 | 2026-10-31T11:44:29Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `a80600a7c0c8b3d8ab728c2c30b811458e60b65fa59b67b9565680a726573caf` |
| 23 | 2026-10-31T11:44:33Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `05b3f85b9c006ac78aa8d602449e2b20b30bad29b702963647c85bdce9dfa27f` |
| 24 | 2026-10-31T11:44:35Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `41cbc8af9dc5eb5c0667449873af42470e11f9c36d4c3f2ddf578ac1adaac7c8` |
| 25 | 2026-10-31T11:44:42Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T11:44:45Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T11:44:48Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T11:44:50Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `7a83cabac5a9ca15c99b0dcc5ccfa1f073785f17cde00ec2242f8f701fa1aad8` |
| 29 | 2026-10-31T11:44:52Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `afd5d01964ed65a6d35d438f939ef32161d4c7dbb147197fcf5f6d6309b2c058` |
| 30 | 2026-10-31T11:45:10Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true` | `e0e76e0b042bf67dbc7b3db3586940bf59f06eb98cd2b065ebbbbf99daf476a4` |
| 31 | 2026-10-31T11:45:22Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-10-31T11:45:24Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Deviations

D-ABI-W6-1…14 in the [ledger](v24-deviation-ledger-2026-10-23.md) record the accepted specification conflicts and narrowed boundaries: frozen `glob_16` wins over the §6.3 wording for glob-excluded `scanned_files`; the 12-second evidence standard is three-layer and not a wall-clock guarantee; C0/C1 narrow the budget checkpoints; empty-page `output_too_large` and `addSafe`'s `invalid_tool_output` are plugin-emitted codes outside the list/search closed sets; `entry_too_large` is defensive and proved only through injected caps; the list scan cap counts raw `readdir` entries; glob-excluded files consume the file budget; 2^53-level offsets are `invalid_path` only through the direct frame because `_tool_v2` rejects them before spawn; the early guard is replaced by the post-selection rule; slashless glob matches basename; the seam is only the optional third argument; W6 supplies the W4 O8=B follow-up evidence without changing the `m3_pending` declaration; and `linux_real`/subdirectory non-UTF-8 remain outside this run. No design, vector, pin, host, SQL or `fs_read.py` change was made; no STOP condition fired.

## Limits

- **M3 remains pending:** no proof of search's 12-second scan/cutoff wall-clock behavior, cross-platform timing or Linux real non-UTF-8 filenames; `tool.search_budget_timing_m3_pending` remains `m3_pending`, `linux_real=not_run`. W6 supplies deterministic cutoff evidence only.
- **Timing is not a gate:** S25 records one observation (50.331 ms elapsed at `budgetMs=50`, overshoot 0.331 ms); S26 records 126.674 ms but asserts only the 600 `JSON.stringify` structural count. Neither is a performance threshold.
- **Injected/unreachable paths:** `entry_too_large`, empty-page `output_too_large`, the `addSafe` overflow and the 2^53 direct-frame offset are proved with narrowed caps or direct frames; normal host validation rejects oversized arguments before spawn, and built-in caps do not reach the list entry/empty output errors.
- **Trusted workspace:** synchronous `readdir`/`readFile` cannot be cancelled mid-call; exceeding the host's 15000 ms deadline would be an unknown `timeout`, not the plugin's `search_scope_too_large` classification. No such case occurred.
- **Non-UTF-8 coverage:** L07 asserts only the root-level `0xff` entry; macOS subdirectory injection is not covered. Linux `filesystem` mode is not part of this macOS run.
- **No promotion:** frozen `expected`/`status` fields, `manifest.artifact_digest_pending`, `design_conformance.json`, `DESIGN_SHA256` and all pinned spans are unchanged. No service-side cursor/snapshot pagination, replay or real-provider behavior is claimed.

## Publication

The publication unit is the nine candidate paths listed above, including the completed plan and critique. After all documentation is written and reviewed, rerun all seven audits in full, then stage each explicit path, review status and the staged diff, and scan staged bytes plus evidence for credentials. Credential scans report redacted locations only and stop on any hit; environment-variable names in commands are not credentials. Preserve the final nine-file source manifest, porcelain status and audit/log digests externally.

Use normal hooks, the single commit message `v24: close out Node list and search tools`, and non-force `git push origin main`. No `git add -A`, `git add .`, `--no-verify`, or force push is permitted. Unrelated pre-existing files remain outside the commit. The actual commit SHA and push outcome are recorded in the external publication receipt and reported after execution; this record does not embed its own commit hash.
