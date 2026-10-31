# v24 Tool/Plugin ABI M3 declaration execution record

Date: 2026-11-01 (+08:00). Scope: the M3 declaration in design Appendix C.18 and the [closeout plan](../plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md), work items M3-0…M3-6. This record reports only this run's measurements. It does not embed its own SHA or the future commit SHA.

## Result

The required 32 commands ran serially in the plan's order and all exited 0. The first command started at 2026-10-31T16:38:23Z and the last at 2026-10-31T16:40:30Z; these are command start times, not an end-to-end duration. Commands 1–31 ended in their exact command-specific `[passed]` lines. Command 32 was the pinned SQL diff: exit 0, a zero-byte log, an empty last-line field, and no `[passed]`. No exit 2, `[SKIP]` or missing required marker occurred.

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
```

**M3 is complete under the C.18 evidence standard**: W5 supplies the read evidence, W6 supplies the list/search evidence, and this run supplies the current 32-command sweep and seven scope audits. Rows 14–24 are the eleven frozen closeout commands. Closeout remains **11/11**; s13 is extension evidence, not a twelfth item. `tool.search_budget_timing_m3_pending` stays the frozen `m3_pending` provenance token; `linux_real=not_run`. This record does not start or claim M5.

## Candidate and provenance

- Checkout `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `23070776b0ac16749a7ff87729bb1782fb331f27` (`v24: close out Node list and search tools`). `origin/main` was the same commit before the run.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`, Python `3.14.6`, Node `v24.13.1` at `/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`, PostgreSQL `17.11 (Homebrew)`, Darwin `25.6.0` / macOS `26.6.2` / arm64; real local plugin subprocesses and the local database.
- Exactly ten candidate paths: `docs/plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md`, `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md`, `v24/s13/vectors/design_conformance.json`, `v24/s13/test_contracts.py`, `v24/s13/README.md`, `docs/reviews/v24-conformance-matrix-2026-10-23.md`, `docs/reviews/v24-deviation-ledger-2026-10-23.md`, this execution record, `docs/investigations/v24-m3-budget-closeout-2026-10-31.md`, and `docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md`.
- Evidence directory `/tmp/v24-abi-m3-20261031T163642Z/`. It contains provenance, the initial porcelain and untracked path+sha256 snapshot, the design baseline copy and span inventory, the repin proof and diff, `01.log`–`32.log`, `results.tsv`, `merged.log`, `scope-precheck/` and the final audit directory. The publication receipt records the actual commit SHA and push outcome externally.
- The pre-existing `.ctx-export-*`, `.token-probe*`, `ctx_export_check*` and `v20/experiments/ce_native_d5/**` remain outside the candidate set and outside staging.

The implementation and artifact digests at the sweep boundary are:

| Source / artifact | SHA-256 |
|---|---|
| `v24/s13/plugins/fs_read.py` (source, installed copy and approved entry; row 29) | `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c` |
| `v24/s13/plugins/fs_tools.js` (source; S24 asserts source/copy/entry equality) | `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5` |
| `v24/s13/fixtures.py` | `f2b5b84d9539ad9580645cabb15bf92dd169bb6a75b00c2eb1f25f069ac99bf5` |
| `v24/s13/test_tools.py` | `4df195f18d9583d920e64b1e5a5715d3626b97abdc00ffb0313651879d992d92` |
| Unchanged pre-append ABI design | `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` |
| Appended ABI design | `778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d` |

Stable evidence digests:

| Evidence file | SHA-256 |
|---|---|
| `results.tsv` | `0094409f55a9e7e8529702856df29f31bb3cfd9427eccfd695603b5420a80c39` |
| `merged.log` | `8197b121c27985dfb28d1869c73779010a7b293f7a1a47a75a92b1ddfc927167` |
| `29.log` | `afd23cc6707c266dd50e750ad25cf362f110607ac974604a4a27b89d3a7d0818` |
| `provenance.txt` | `549c6fc9ac79658c2377e8ddc172596bd236e679a7527e2999962354770b2e6c` |
| `baseline-untracked.txt` | `b8676b0edcb73639be1b6ec480e02403bb30c0c5520c7eddb4dbc356084d4f33` |
| `scope-precheck/scope-audit.tsv` | `40db9e7184ad7c82629bb51cd2c6cd6856b9a914303b8d61702cbc88969c72ca` |
| `design-original.md` | `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` |

## Repin and frozen bytes

Appending C.18 changed the design from 113843 bytes to 121521 bytes. `sha256(new[0:113843])` equals the old SHA `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b`, so the old bytes are an exact prefix; the appended region is 7678 bytes with no edits inside the old file. Both pins are now `778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d`:

- `v24/s13/vectors/design_conformance.json` → only `design_input.sha256_at_review`;
- `v24/s13/test_contracts.py` → only `DESIGN_SHA256`.

`git diff --stat -- v24/s13` is exactly two files, each one insertion and one deletion. All 25 references to 23 pinned spans retain their `line_start`/`line_end`, heading and content SHA; the maximum `line_end` remains 1178. The frozen 16 read, 7 list and 24 search outputs are byte-identical.

## Declaration and evidence mapping

| C.18.2 item | Evidence in this run | Result |
|---|---|---|
| (a) §10 M3 done-when: `test_tools` green, real subprocess, pagination convergence | row 29; 140 cases; real Python/Node subprocesses; `pagination_converged=true` | Pass |
| (b) frozen 16 read / 7 list / 24 search outputs byte-identical | rows 5, 9–11 and 29; audit 2 vectors except mapping | Pass |
| (c) four stop reasons and §5.6 page-fill branch through production code | row 29 S01–S12 (file-cap five shapes), S06–S11 (time-cap four shapes, EOF/sentinel priority) | Pass |
| (d) legal worst-case read within the 5000 ms host deadline, current observation recorded | row 29 R26 `success`; `read_1m_wall_ms=97`; `read_peak_kib=3959.904` | Pass |
| (e) C.18.3 three-layer evidence | T1/T2/T3 below | Pass |
| (f) 32-command sweep and seven audits | 32/32 exit 0; 7/7 precheck and final | Pass |

The 12-second evidence is three separate layers, not a wall-clock guarantee:

| Layer | This run's evidence | Boundary |
|---|---|---|
| T1 | S06–S11 through the exported production `searchTool` with injected clock; time-cap count-full/before-fill/before-offset/empty and EOF/sentinel priority | Not a separately written reference algorithm; not frame-level clock injection |
| T2 | S24: `SCAN_BUDGET_MS=12000`, search `timeout_ms=15000`, margin 3000, `hrtime` only in `searchTool`, `process.env` only in `rootPath` | 3000 ms is a configuration margin, not a scan/IO worst-case bound |
| T3 | S25: `real_clock_elapsed_ms=50.463`, overshoot `0.463`; result in the allowed cutoff/empty set | Elapsed is recorded only; no threshold and no requirement to reproduce a particular value |

`[evidence] non_utf8_source=preload_shim; linux_real=not_run` and `[evidence] read_artifact_sha256=...; read_1m_wall_ms=97; read_peak_kib=3959.904; permission_probe=real` were captured from the complete row-29 log. R26 is the DB-backed wide-input harness case; its success is asserted under the unchanged 5000 ms descriptor deadline. This run does not reuse W5's 113 ms value.

## Scope and compatibility audits

All seven checks passed the precheck. The release procedure reruns the entire set after all documentation and immediately before staging; the final run is recorded below.

| # | Check | Base | Exit | Actual last line |
|---|---|---:|---:|---|
| 1 | Frozen modules/s13 tests and no new frozen-directory files | `c8c4bd0` / `2307077` | 0 | `[scope] passed frozen_modules_and_untracked` |
| 2 | Vectors except design metadata | `c8c4bd0` / `2307077` | 0 | `[scope] passed vectors_except_design_conformance` |
| 3 | Design-conformance restoration after SHA substitution | `c8c4bd0` / `2307077` | 0 | `[scope] passed design_conformance_restore` |
| 4 | Registry exact D12 patch and whole-file equality | `c8c4bd0` | 0 | `[scope] passed registry_exact_patch` |
| 5 | Host import purity | `c8c4bd0` | 0 | `[scope] passed host_import_purity` |
| 6 | SQL zero diff | `c8c4bd0` | 0 | `[scope] passed sql_zero_diff` |
| 7 | Tracked M3 delta union changed/new/removed untracked is a ten-path candidate subset | `2307077` | 0 | `[scope] passed m3_candidate_only` |

Audit 1 extends the inherited frozen check to the W2/W3 s13 test/reference files and asserts `test_contracts.py` restores byte-for-byte after replacing only its design SHA with the `2307077` value. It also freezes `v24/host`, `v24/sql` and `v24/s13` at `2307077`, exempting only `README.md`, the mapping SHA and the test constant. Audit 3 normalizes the new SHA back to `ab4636fc…` and compares both the mapping and `test_contracts.py` byte-for-byte with `2307077`; the inherited `c8c4bd0` check additionally normalizes to that baseline's own old pin. Audit 7 compares the `2307077` tracked delta and the M3-0 untracked path+sha256 snapshot, so an unchanged path with changed bytes is a delta; it also re-proves the design prefix and every span's line range, heading and content SHA.

### Final audit (after documentation)

The full set ran again after README, matrix, ledger, investigation, record and plan Result were written, starting at 2026-10-31T16:42:59Z. All seven exited 0 with these last lines:

| # | Check | Exit | Actual last line | Log SHA-256 |
|---|---|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 0 | `[scope] passed frozen_modules_and_untracked` | `e4bd70fc4910b7ab794bc2cc47b09e5b21e0715a1dcca297bfed0a87de0b111b` |
| 2 | `vectors_except_design_conformance` | 0 | `[scope] passed vectors_except_design_conformance` | `bad3b92a01050931a3f54a511d5d2c1bd5cdf6aa9819f30fcf7c08b688b7c329` |
| 3 | `design_conformance_restore` | 0 | `[scope] passed design_conformance_restore` | `adeaa2e556426c2e7e82c05fecca73bb2695012fb771eb36234ef2f9bd5047c5` |
| 4 | `registry_exact_patch` | 0 | `[scope] passed registry_exact_patch` | `ce61a55b37c1c8e79b0871fa5e70381e3e2b323c9b2737de59523c88c83cbf33` |
| 5 | `host_import_purity` | 0 | `[scope] passed host_import_purity` | `f22b3a92ba8926508ee266282111acb354f4098f7f21f77a6310568b520f98b3` |
| 6 | `sql_zero_diff` | 0 | `[scope] passed sql_zero_diff` | `89f69d2e7dcd649ca47f5094ff8820ba349bf688ca43708db3fcf2248985950d` |
| 7 | `m3_candidate_only` | 0 | `[scope] passed m3_candidate_only` | `7ff8ef795bfd1e31a0494afc955c9f57c9374d0855d8977a156cf55fab7069be` |

`scope-final/scope-audit.tsv` SHA-256 is `c88aa3a8209e66f82375b37f2dc215cf9bacf7db124745d89d0100bb085e1930`. Because this table and the plan Result are themselves documentation edits made after that run, a post-record confirmation run is executed before staging and recorded in the external receipt; the seven checks do not depend on documentation bytes.

## Final 32-command serial run

Every command below used the exact prefix `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`. Start times are UTC; last lines and log digests come directly from the producer logs.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T16:38:23Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T16:38:53Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T16:38:57Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T16:38:57Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T16:38:58Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T16:38:58Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T16:38:59Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T16:39:00Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T16:39:00Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T16:39:01Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T16:39:03Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T16:39:05Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T16:39:07Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T16:39:09Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T16:39:09Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T16:39:11Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T16:39:12Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T16:39:15Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T16:39:17Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T16:39:26Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `598f48af8b67b87617df9bd5812f2f7ea285b28f19744993534654517397f887` |
| 21 | 2026-10-31T16:39:31Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `87dcd5260a4d7653c5051724996c0c439cc7750da00a2f76f646428323bfda15` |
| 22 | 2026-10-31T16:39:35Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `a60e89f40d2f69254e86490935a7a805fc952ab8452c90234d289685d354ff59` |
| 23 | 2026-10-31T16:39:39Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `f2007f03997a65ac034897781f7cd2f0cac75fd2a352cb5de5e3ae0e6461a752` |
| 24 | 2026-10-31T16:39:41Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `e3f8a10caea5116525f4702d1ce31438bca41c955309f13608da0b2fb65edf5a` |
| 25 | 2026-10-31T16:39:48Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T16:39:51Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T16:39:54Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T16:39:57Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `d7d758540a81059709fbd97c0cd92b09194f4ad9a041f84d0f7b2f1b789bf0d8` |
| 29 | 2026-10-31T16:39:59Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `afd23cc6707c266dd50e750ad25cf362f110607ac974604a4a27b89d3a7d0818` |
| 30 | 2026-10-31T16:40:17Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true` | `e0e76e0b042bf67dbc7b3db3586940bf59f06eb98cd2b065ebbbbf99daf476a4` |
| 31 | 2026-10-31T16:40:29Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-10-31T16:40:30Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Deviations

D-ABI-M3-1…7 in the [ledger](v24-deviation-ledger-2026-10-23.md) record the accepted authority, over-claim correction, evidence standard, clock seam, frozen-token provenance, declaration boundary and investigation provenance. No production source, plugin, fixture, test behavior, host, SQL, loader or frozen-vector byte changed; the only code-adjacent edits are the two design pins. No STOP condition fired.

## Limits

- **Not a hard real-time 12-second claim:** T1 proves deterministic classification through the production function, T2 proves the configured constants/structure, and T3 records one observation. Synchronous `readdir`/`readFile` cannot be preempted; exceeding the host's 15000 ms deadline would be an `unknown/timeout`, not the plugin's `search_scope_too_large`.
- **Pagination convergence is bounded:** the §5.6 rule proves that a cutoff page is returned only with count-full or `k<m` evidence; it does not promise that any slow scope converges within the budget.
- **Platform coverage:** `linux_real=not_run`; the non-UTF-8 evidence is the macOS root-level preload shim. macOS subdirectory injection and Linux real behavior remain outside this run.
- **Structural file-cap evidence:** S02 proves the `k<m` byte-full structure, not a real byte-full tree reproduction. `entry_too_large` and the `addSafe` overflow remain defensive/narrowed-cap paths.
- **No promotion:** all frozen `status`/`expected` fields, the two `"M3-pending"` placeholders, `manifest.artifact_digest_pending`, `compatibility.*_claimed=false` and the 34 pending-token positions remain unchanged. The 34 positions are adjudicated in M5, not here.
- **No M5 claim:** this record does not execute the §7.5 main-design revisions, the 34-position adjudication, or the M5 sweep.

## Publication

The publication unit is the ten candidate paths listed above, including the completed plan, the investigation, and the plan critique. After all documentation is written and reviewed, rerun all seven audits in full, then stage each explicit path, review status and the staged diff, and scan staged bytes plus evidence for credentials. Credential scans report redacted locations only and stop on any hit; environment-variable names in commands are not credentials. Preserve the final ten-file source manifest, porcelain status and audit/log digests externally.

Use normal hooks, the single commit message `v24: declare Tool/Plugin ABI M3 complete`, and non-force `git push origin main`. No `git add -A`, `git add .`, `--no-verify`, or force push is permitted. Unrelated pre-existing files remain outside the commit. The actual commit SHA and push outcome are recorded in the external publication receipt and reported after execution; this record does not embed its own commit hash.
