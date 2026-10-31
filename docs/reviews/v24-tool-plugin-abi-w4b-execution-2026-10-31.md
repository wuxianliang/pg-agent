# v24 Tool/Plugin ABI W4b execution record

Date: 2026-10-31 (+08:00). Scope: W4b filesystem read/list/search tools in [W4 plan](../plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md), corresponding to design §10 M3 implementation. This record does not claim M3 completion; timing/cutoff remains pending.

## Result

The required 30 serial commands ran in the specified order and all exited 0. Command 30 (`v24/s13/test_tools.py`) is the W4b gate and printed both the macOS-first evidence line and its marker:

```text
[evidence] non_utf8_source=preload_shim; linux_real=not_run
[passed] W4 fs tools; cases=74; read=16; list=7; search=24; pagination_converged=true; page_contracts_imported=3
```

Rows 14–24 are the 11 frozen closeout commands. Closeout remains **11/11**; s13 is not a twelfth closeout item. No exit 2, `[SKIP]`, missing pass marker or `not_run` occurred in the 30 commands. No real provider call was made. **M3 implementation is complete, timing/cutoff pending** (O8=B): this is not an M3-complete declaration, `tool.search_budget_timing_m3_pending` remains `m3_pending`, and no 12-second wall-clock gate exists.

## Candidate and provenance

- Checkout: `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `3d95d5fa7ceeb593942b2a76275f69cff962b577`.
- The authoritative sweep started at the first row below and ended at command 30; the six scope audits ran immediately afterwards. The run identity is in `results.tsv`, `merged.log` and the per-command log hashes.
- Candidate paths: `v24/s13/plugins/fs_read.py`, `v24/s13/plugins/fs_tools.js`, `v24/s13/fixtures.py`, `v24/s13/w4b_non_utf8_preload.cjs`, `v24/s13/test_tools.py`, `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`, `v24/s13/test_contracts.py`, `v24/s13/vectors/design_conformance.json`, the W4 plan, this record, the matrix/ledger and `v24/s13/README.md`.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`; Python `3.12.11`; Node `v24.13.1`. PostgreSQL is the local test database used by the inherited closeout/G9/G10 and the W4b DB integration cases.
- Evidence directory: `/tmp/w4b-20261031T043334/`. It contains `provenance.txt`, `git-status-porcelain.txt`, `source-sha256.txt`, redacted `credential-scan.txt`, `01.log`–`30.log`, `results.tsv`, `merged.log`, `scope-audit.tsv`, and six `scope-*.log` files.
- `results.tsv` SHA-256: `8823c45a3261a965f6dc6454f68de36a9d10fc41b50bf9fe43ff8b996e9304d9`.
- `merged.log` SHA-256: `12ee007817cb4d116fc0f4fcabbc7adb883e9149e96d382708084bd2ac78db8f`.
- `scope-audit.tsv` SHA-256: `9e3996ec4219710fb878103e9a97245caad5b3e60c53be8cc56926af48531644`.
- `source-sha256.txt` SHA-256: `56b4d0958d5f591e1f15f2440942591e262103eabfa17cdcb840195281f3282c`; `credential-scan.txt` SHA-256: `44c9ba9d59d50e31ef63b45d45ed80c4243132be51c229fa8c1cbd434555c71b`.
- `provenance.txt` SHA-256: `1b1ef314950f34859fb7ff4d06b552e1d47148570eccf4078b08cf13afc1ed4a`; `git-status-porcelain.txt` is generated after the sweep with the full `git status --porcelain=v2` and version/identity snapshot.

Every command used exactly this prefix:

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

The runner redirected each producer to its own log, then immediately captured `rc=$?`; no tail or pipeline supplied the exit status. The TSV stores the expanded command, UTC start time, exit code, actual last line and SHA-256 of the log. A nonzero exit or missing required marker would have stopped the run before publication.

## Implementation and coverage

| Area | Measured coverage | Boundary |
|---|---|---|
| `fs_read.py` | All 16 `tool.read.contract` inputs: empty file/offset, tail LF, CR preservation, bad UTF-8 window/outside, empty line, 16384/16385-byte lines, exactly 1 MiB, over 1 MiB, line/byte truncation and cursor continuation | Real local Python subprocess; no network. The 1 MiB scan is in-memory for this gate. |
| `fs_tools.js` | All 7 `tool.list.contract` inputs (sorting, recursive DFS, symlink, hidden, `.git`, non-UTF-8, special, offset/total, 10000/10001 scan cap) and all 24 `tool.search.contract` inputs (literal, ASCII fold, Unicode column, glob `*`/`**`/`?`, context, 500-code-point hit truncation, skip counters, 10000-file budget, empty/complete, incomplete sentinel, cutoff errors) | Real local Node subprocess; no network. Search state is rescanned from the start for each page. |
| `fixtures.py` | Reviewed vector trees materialized from byte recipes; v2 manifests use the SQL-compatible `\x` adapter digest and direct `ApprovedPlugin` construction; DB harness reuse | Test fixture only. Real non-UTF-8 names on supported filesystems; macOS uses the preload shim. |
| `w4b_non_utf8_preload.cjs` | macOS-first test-only preload: exact realpath root, buffer `fs.readdirSync`, one appended `0xff` Buffer, ledger events, no stdout/stderr, env self-cleanup | Not a production plugin dependency; only loaded through the test subprocess's `NODE_OPTIONS`. |
| `test_tools.py` | 74 cases total: 16 read, 7 list, 24 search, 15 cross-language path-error probes, 4 selector probes, 3 DB harness cases, 5 shim differential/control guards | macOS `non_utf8_source=preload_shim`; `linux_real=not_run`. |

The page selectors (`fs_read.select_prefix` and `fs_tools.selectPrefix`) enumerate every prefix; the gate includes synthetic non-monotonic length sequences that fail first, pass shorter, then pass/ fail later. No binary search or first-failure early exit is used. The Node 10000-file budget is deterministic; `tool.search_budget_timing_m3_pending` was read but not executed as a wall-clock case and remains pending.

The DB section runs real read/list/search through `PluginHarness` and asserts the v1 prepare receipt, tool result value, `--spawn-log` process count and output-schema/page-contract checks. The vector section runs approved plugin subprocesses with the same `--spawn-log` argv; no journal event count is used as zero-spawn evidence.

## macOS-first non-UTF-8 fixture

APFS rejects raw non-UTF-8 filenames (`EILSEQ`); HFS+/HFS/MS-DOS images escape the byte to `%FF`. The fixture probe therefore distinguishes real filesystem support from a test-only readdir input shim:

- `filesystem` (Linux-first): create a real `b"\xff"` name and verify exact readback; the plugin sees a real directory entry.
- `preload_shim` (current macOS): load `v24/s13/w4b_non_utf8_preload.cjs` only into the Node plugin subprocess via `NODE_OPTIONS=--require`. The preload matches the realpath of exactly one `W4B_NON_UTF8_ROOT`, requires the plugin's buffer `readdirSync` form, appends one `Buffer.from([0xff])`, records `loaded`/`inject`/`mismatch` events in a ledger, and throws on unsupported forms. It does not create a fake file and does not touch `lstat`/`readFile`.
- Production plugins contain no `W4B_`, `NODE_OPTIONS`, preload or test branch; the gate scans both plugin sources.
- The shim is guarded by preload preflight, a control directory with no injection, ledger `mismatch=0`, list differential (`skipped_non_utf8` 1 vs 0, all other fields equal), search differential (`skipped.non_utf8` 2 vs 1, all other fields equal), and minimum-page pagination comparison.
- **Limitation:** macOS evidence proves the plugin's handling of an illegal UTF-8 directory entry, not that APFS can create/stat/open such a name. Linux real evidence (`non_utf8_source=filesystem`) is **not_run** in this sweep and must not be inferred from the shim. The real bad-content file that supplies the second search `non_utf8` is still created and read normally.

## Design revision and append-only span proof

Old design SHA-256 (HEAD `3d95d5f`):

`15afb72dfb8f4f274d36b1722ad3b50501388abbe2a6a0d0ce6e6eeba12f7800`

New design SHA-256:

`ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b`

C.17 was appended after C.16; the old bytes are an exact prefix. The proof compared every baseline/current `design_sections` object, recomputed every current line-slice SHA and checked its heading. There are **25 suite references to 23 unique spans**; every line range, heading and content SHA is unchanged. `test_contracts.py` changes only `DESIGN_SHA256`; `design_conformance.json` changes only `design_input.sha256_at_review`. Frozen vector case IDs, statuses and expected values were not changed.

## Scope and compatibility audits

All six checks are explicitly pinned to `c8c4bd0`; no bare `git diff` decided a result. The frozen check now also covers the s13 test files and asserts `test_contracts.py` changes only `DESIGN_SHA256`.

| Check | Exit | Actual result |
|---|---:|---|
| frozen modules, frozen s13 tests and no untracked frozen dirs | 0 | `[scope] passed frozen_modules_and_untracked` |
| vectors except design metadata | 0 | `[scope] passed vectors_except_design_conformance` |
| design restore after SHA substitution | 0 | `[scope] passed design_conformance_restore old=269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0 new=ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` |
| registry exact D12 patch | 0 | `[scope] passed registry_exact_patch plus=5 minus=1` |
| host import purity | 0 | `[scope] passed host_import_purity` |
| SQL zero diff | 0 | `[scope] passed sql_zero_diff` |

`test_wiring.py` runs the same six checks at its end and printed `[scope] passed base=c8c4bd0 checks=6` during command 02. The SQL command 29 also exited 0 with empty output.

## Final 30-command serial run

All commands below are prefixed by the exact `$ENVPFX` expansion shown above. Start times are UTC.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T04:33:34Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T04:34:03Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T04:34:08Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T04:34:08Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T04:34:09Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T04:34:10Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T04:34:11Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T04:34:12Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T04:34:12Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T04:34:13Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T04:34:15Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T04:34:17Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T04:34:19Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T04:34:21Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T04:34:22Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T04:34:23Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T04:34:25Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T04:34:28Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T04:34:29Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T04:34:38Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `65bce85c1780ed1c45c90ff2240d4ca8dd4253cffb18d6c2037ca90100bd9881` |
| 21 | 2026-10-31T04:34:43Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `6008afc636b7291f8a388cfe8345d7b8109e360a0e8cdbfb52161b72c22c545b` |
| 22 | 2026-10-31T04:34:47Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `d51561f8536630b2bb77e723036f185c8bc99a78424e91c45a4dc3218e49a3b7` |
| 23 | 2026-10-31T04:34:51Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `ed56bcdec4db9b5b9eeca1b004cc485ae520d5afdf18bbd0d1c5b05b56750b6a` |
| 24 | 2026-10-31T04:34:54Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `3b2c812b53395b37a4467edf861df291832661d6c1fad39bb49d2514d360f4c4` |
| 25 | 2026-10-31T04:35:00Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T04:35:04Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T04:35:07Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T04:35:09Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `8801706194e98dd25eb2a33d9fad77e294ace8df30a82f0befba65526667541d` |
| 29 | 2026-10-31T04:35:11Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| 30 | 2026-10-31T04:35:11Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=74; read=16; list=7; search=24; pagination_converged=true; page_contracts_imported=3` | `af5e1f72bd02838fbda62a7fb28d045477ead46bfd4fa332882d9e3be2d3dc88` |

## Deviations, limits and unresolved assumptions

- **D-ABI-W4-8** (ledger) records the macOS-first non-UTF-8 fixture decision, its exact shim boundary and the `preload_shim`/`filesystem` evidence split. Design C.17 and plan D16 are the normative sources.
- **Historical flake:** an earlier full retry at `/tmp/w4b-20261031T043204/` stopped at command 24 with `G6-L3a` observing `blocking_pids={}` plus `ungranted_advisory=1`; the same unmodified G6 gate passed in the authoritative `/tmp/w4b-20261031T043334/` run. The failed directory is retained as historical evidence and is not used as final identity.
- **M3 implementation, not M3 completion:** timing/cutoff is pending; `tool.search_budget_timing_m3_pending` remains `m3_pending`; `tool.search_budget_file_count` was executed (10000/10001-file cases) with `search_scope_too_large` on the over-budget path; no `sleep(12)` or wall-clock gate was added.
- **macOS shim limitation:** APFS cannot create raw non-UTF-8 names; the preload supplies exactly one readdir entry. Linux real creation is the intended end-to-end proof and is `not_run` here. The shim does not alter production code, vectors, statuses or expected values.
- **No production seam:** `fs_read.py` and `fs_tools.js` contain no `W4B_`, `NODE_OPTIONS`, preload reference or test branch. `NODE_OPTIONS`/`W4B_*` are confined to test-only `ApprovedPlugin` allowlists and the direct plugin subprocess environment.
- **No network/provider:** all commands use local PostgreSQL, local Python/Node subprocesses and `ScriptedTransport`/fake providers only; no real provider or network socket was opened.
- **No pagination shortcut:** prefix selection enumerates all candidates; the synthetic selector probes and vector page cases cover the non-monotonic behavior. The Node list/search pagination path was exercised for 10000 entries, offsets, truncation and cursor continuation.

## Publication

This record, the README, matrix, ledger and W4b plan Result are documentation updates after the measured sweep. Publication uses the W4b file list plus the design/plan/README/matrix/ledger/record paths, normal hooks (no `--no-verify`), commit message `v24: add v2 filesystem read/list/search tools with page contracts`, and non-force `git push origin main`. It excludes the unrelated `.ctx-export-*`, `.token-probe*`, `ctx_export_check*` and `v20/experiments/ce_native_d5/` files. The resulting commit/push outcome is reported after execution; this file does not embed its own commit hash.
