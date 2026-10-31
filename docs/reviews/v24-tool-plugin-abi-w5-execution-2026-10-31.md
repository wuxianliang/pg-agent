# v24 Tool/Plugin ABI W5 execution record

Date: 2026-10-31 (+08:00). Scope: Python `read` closeout in the [W5 plan](../plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md), within design §10 M3. W5-0…W5-4 were completed and independently verified before this closeout run; W5-5…W5-7 reuse those inputs. D1–D14 and O1–O6 remain settled. W5 does not complete M3's search timing/cutoff work.

## Result

The required 32 commands ran serially in the plan's order and all exited 0. The first command started at 2026-10-31T07:29:24Z and the last command started at 07:31:31Z; these are command start times, not a measured end-to-end duration. Commands 1–31 ended in their exact command-specific `[passed]` lines. Command 32 was the pinned SQL diff: exit 0, a zero-byte log, an empty actual last-line field, and no `[passed]`. No exit 2, `[SKIP]` or missing required marker occurred.

```text
[evidence] read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c; read_1m_wall_ms=113; read_peak_kib=3959.904; permission_probe=real
[passed] W4 fs tools; cases=103; read=16; read_probes=29; list=7; search=24; pagination_converged=true; page_contracts_imported=3
```

Rows 14–24 are the eleven frozen closeout commands. Closeout remains **11/11**; s13 is extension evidence, not a twelfth item. W5 closes the Python read gaps; **M3 timing/cutoff remains pending**, `tool.search_budget_timing_m3_pending` stays `m3_pending`, and `linux_real=not_run`.

## Candidate and provenance

- Checkout `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `5771ce3809dea8bf979a617fef3fdbf03f07a340` (W4c).
- Environment inherited from the W5-0 provenance: uv `0.8.24 (252f88733 2025-10-07)`, Python `3.12.11`, Node `v24.13.1`, Darwin `25.6.0` / arm64; local PostgreSQL and real local plugin subprocesses.
- Exactly nine candidate paths: `v24/s13/plugins/fs_read.py`, `v24/s13/fixtures.py`, `v24/s13/test_tools.py`, `v24/s13/README.md`, `docs/reviews/v24-conformance-matrix-2026-10-23.md`, `docs/reviews/v24-deviation-ledger-2026-10-23.md`, this execution record, `docs/reviews/v24-tool-plugin-abi-w5-python-read-plan-critique-2026-10-31.md`, and `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md`.
- Evidence directory `/tmp/w5-20261031T063812Z/` is reused. The original provenance, W5-0 untracked/status/source snapshots, red baseline, W5-4 logs and handoff are retained. Sweep/precheck artifacts are `01.log`–`32.log`, `results.tsv`, `merged.log`, `scope-precheck/`, retained `scope-precheck-runner-error/`, and redacted credential scans. The publication sequence creates `scope-final/`, replaces the top-level `scope-audit.tsv` and `scope-1..7.log` with final-audit evidence, and writes the final nine-path `source-sha256.txt` and porcelain snapshots. Until the final rerun, the top-level scope files are copies of the precheck. Initial source/status snapshots are preserved separately before updating their final names.

The implementation bytes at the sweep boundary are:

| Source / artifact | SHA-256 |
|---|---|
| `v24/s13/plugins/fs_read.py` (source, installed copy and approved entry) | `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c` |
| `v24/s13/fixtures.py` | `5f4ececa111e9e95b4c6a500fd76a496015855ea6aa9e0efe1d37ba9e2290fd4` |
| `v24/s13/test_tools.py` | `407f7bc1ec59dae57a92666aa9f010a6b662956978dc9953bb10afb42845ed8f` |
| Unchanged ABI design | `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` |

The final nine-path source manifest includes this record after documentation is complete; its digest is stored externally rather than embedding a self-dependent hash in this file. Stable evidence digests are:

| Evidence file | SHA-256 |
|---|---|
| `results.tsv` | `8d38bc410a8b424eddb543721e15f242fbb9fff4966105c5eb6549c8f96e9537` |
| `merged.log` | `3b9872407d027f4692c6eac6bde5b32c5b30369f0a9b7a2460ff4b8f326ec9ce` |
| `provenance.txt` | `9b6cb691ee50ebdc7af845ff184ae8b4fb45a679a657d60384d709fee00417c3` |
| `baseline-untracked.txt` | `2d58ed787d030d2d390d05a601ac9169e5ab827155d148f562ba9948d2cfb6b4` |
| `red-baseline.log` | `31b4a0569d1517942757eb8948d672c9d68340e18e83f4e389212fd3f8d3e8b5` |
| `baseline-actual-and-frozen.log` | `07e454b1e9ed1ea61ff4e6c5a4c8688dbdaee1f294089d158b9aac51097c31a5` |
| `HANDOFF-w5-4.md` | `7b6c3a2afdd4a1de6030bc89a062301938f3cd380d31820f6e399516a687aab0` |
| `scope-precheck/scope-audit.tsv` | `8d35be88c66c114188bb6a6b74815d35fdb3b18f481f94278b1deb9dc5e3284f` |

Every sweep command used exactly this prefix, including the final SQL diff:

```bash
ENVPFX="env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1"
```

The runner launches one producer at a time from the repository root, redirects stdout/stderr to its numbered log, and captures the producer's return code directly. The TSV stores the fully expanded command, UTC start, exit code, real last line and log SHA-256. No pipeline/tail supplies an exit code or synthesizes a marker. Empty SQL output is an empty string in the TSV; `<empty>` in the table below is presentation only.

## Implementation and coverage

The closeout run preserves the already-verified implementation; it makes no further behavior changes to `fs_read.py`, `fixtures.py` or `test_tools.py`.

| Coverage | Implementation / evidence | Result |
|---|---|---|
| Four reproduced gaps | Single-fd 64 KiB scanning and window `pread`; O(limit) bookkeeping; additive measurement; footer inclusion; empty-file budgets after offset validation | Closed by R22–R27; frozen read bytes unchanged |
| R01–R07 | binary, directory/FIFO, permission, I/O, unavailable root and nonempty offset errors | Passed; permission probe is real on this non-root run |
| R08–R18 | late NUL, absolute inside/outside, intermediate symlink, normalization, empty/oversize/multibyte path, dotfile, value-only success and later overlong requested line | Passed |
| R19–R21 | Same `nine5` fixture at limit=4/5 distinguishes lines/bytes; no fitting first prefix | Passed; lines wins simultaneous binding |
| R22 | Four empty-page caps narrowed separately; offset error priority; restore normal frozen behavior | Passed; `output_too_large` stays plugin-emitted under the recorded ruling |
| R23 / R24 | Escaped byte/str differential; per-candidate value/content/meta/frame versus independent reference and host oracles; null and 9/10/99/100/1000 boundaries; footer affects selection | Passed |
| R25 | 1,048,576 newline bytes and 1,047,999-byte wide input, process-local `tracemalloc` | Both below 8 MiB; reported peak 3959.904 KiB; newline total=1048576 and final_newline=true |
| R26 / R27 | DB-backed PluginHarness → real executor with 5000 ms deadline; bounded empty-text skeleton serialization | Success; 113 ms in this sweep; growing-body serialization eliminated |
| R28 | Source/copy/entry digest equality, `require_artifact()` success, one-byte installed-copy tamper | Passed; tamper rejected as `artifact_digest_mismatch` |
| R29 | Append and same-size rewrite restoring mtime; signatures include ctime | Both detected as `io_error` |
| Compatibility | Frozen 16 read outputs compared byte-for-byte to old plugin; W1/B0/closeout/G9/G10/Node/lifecycle inherited gates | Passed; no vector/status/pin changes |

The reused W5-1 red baseline measured old host `unknown`/`timeout` at `wall_ms=5006`, old peak `128043.177 KiB`, old content 31 B versus footer-aware 86 B (delta 55 B), 2000 serializations of growing text (maximum text 1,047,999 B), and an empty value returned without budget checks. R28 was already baseline-green; R29 is green-only because the old `_scan` API did not exist. The plan's older 6.742 s/123.9 MiB and the critique's separate focused measurements remain earlier observations. W5-4 verified 92–93 ms is also prior evidence; **113 ms is the final sweep's actual R26 measurement**. None becomes an additional wall-clock gate.

## Scope and compatibility audits

All seven checks passed the precheck; their command start times span 2026-10-31T07:32:37Z–07:32:41Z. The release procedure reruns the entire set after all documentation and immediately before staging. That step creates `scope-final/` and replaces the top-level scope table/logs with its publication evidence; before it, only the precheck is authoritative. The table records the actual precheck last lines; the final run must reproduce them with exit 0. The external final-audit table and publication receipt record the resulting status without making this document depend on its own later digest.

| # | Check | Base | Exit | Actual last line |
|---|---|---|---:|---|
| 1 | Frozen modules/s13 tests and no new frozen-directory files | `c8c4bd0` | 0 | `[scope] passed frozen_modules_and_untracked` |
| 2 | Vectors except design metadata | `c8c4bd0` | 0 | `[scope] passed vectors_except_design_conformance` |
| 3 | Design-conformance restoration after SHA substitution | `c8c4bd0` | 0 | `[scope] passed design_conformance_restore` |
| 4 | Registry exact D12 patch and whole-file equality | `c8c4bd0` | 0 | `[scope] passed registry_exact_patch` |
| 5 | Host import purity | `c8c4bd0` | 0 | `[scope] passed host_import_purity` |
| 6 | SQL zero diff | `c8c4bd0` | 0 | `[scope] passed sql_zero_diff` |
| 7 | Tracked W5 delta union new-untracked-minus-snapshot is a nine-path candidate subset | `5771ce3` | 0 | `[scope] passed w5_candidate_only` |

Audit 1 extends the inherited frozen check to the W2/W3 s13 test/reference files; `test_contracts.py` restores byte-for-byte after replacing only its design SHA with the `c8c4bd0` value. W4-added files cannot be zero-diff against `c8c4bd0`; an additional W5 `5771ce3` check keeps all host/SQL/vectors/design files, `fs_tools.js`, preload, and the specified frozen tests/references unchanged. Audit 3 restores old `269e6bada20c6c18331cc681f385808d638bd6ac9403dd7b484352175f57e4b0` from current `ab4636fcae5361cc237b16cdd893c2c544d80e770e8e13269b3d4205713d528b` and compares the complete document; W5 itself changes neither SHA pin. Audit 4 proves exact replacement, one hunk under `-U1`, one deletion and five additions. Host import checks find no vector/reference import. Command 02 independently executes the inherited six audits.

Audit 7 uses the original W5-0 `baseline-untracked.txt`, not all untracked files. The pre-existing `.ctx-export-*`, `.token-probe*`, `ctx_export_check*`, M3 investigation and `v20/experiments/ce_native_d5/**` remain unrelated work and are excluded from staging. The existing plan and critique are themselves in the baseline-untracked snapshot; both remain explicit candidate paths for staging. No frozen manifest pending case is promoted.

## Final 32-command serial run

Every command below is prefixed by the exact `$ENVPFX` expansion above. Start times are UTC; last lines and log digests come directly from the producer logs.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T07:29:24Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T07:29:53Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T07:29:58Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T07:29:58Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T07:29:59Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T07:29:59Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T07:30:00Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T07:30:01Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T07:30:01Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T07:30:02Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T07:30:04Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T07:30:06Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T07:30:08Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T07:30:10Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T07:30:10Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T07:30:12Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T07:30:14Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T07:30:17Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T07:30:18Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T07:30:27Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `7f592180a74636b0326f00e221e171d9a3be957c0931d23662e312e3f7535e41` |
| 21 | 2026-10-31T07:30:31Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `65b7d17741f26a036bfdb6d2fbeebd37dadee8de9e929ec5c35832a2cfbc81e7` |
| 22 | 2026-10-31T07:30:36Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `bbf7ca7cf2858a28f5104f81274b7ed274e0aabd4af271c0a7f744702e998373` |
| 23 | 2026-10-31T07:30:39Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `1c6ca8d38cddc8ced324c101714e15ae3a75661d120d4b76369af17ca2ce0165` |
| 24 | 2026-10-31T07:30:42Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `722a28a67b2275094105a170c285a101c63ccd0ff40438a5b2b4a53259d66cc2` |
| 25 | 2026-10-31T07:30:49Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T07:30:52Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T07:30:55Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T07:30:57Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `919549645e733b2538f12fdebb2c58fdfe3c71df4070f0e84aadfa0b2b756e65` |
| 29 | 2026-10-31T07:30:59Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=103; read=16; read_probes=29; list=7; search=24; pagination_converged=true; page_contracts_imported=3` | `a5231735b19f6b35f51fc2442f3b37d2edb958816885eb0e6f7585451a165bf7` |
| 30 | 2026-10-31T07:31:14Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true` | `e0e76e0b042bf67dbc7b3db3586940bf59f06eb98cd2b065ebbbbf99daf476a4` |
| 31 | 2026-10-31T07:31:28Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-10-31T07:31:31Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | <empty> | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Deviations

D-ABI-W5-1…7 in the [ledger](v24-deviation-ledger-2026-10-23.md) record the four repaired gaps, additive formulas and differential evidence, open/change-detection boundaries, empty-page error ownership, decoding-window conflict, path-length units, unreachable parameter codes and artifact evidence. The existing [critique](v24-tool-plugin-abi-w5-python-read-plan-critique-2026-10-31.md) retains all ten original findings and its separate-adjudication resolution; an appended table maps each to the implementation outcome.

In particular, §5.6 specifies plugin `output_too_large` for an over-budget empty page, §6.2's fourteen-code list omits it, and §5.2 lists it as a host code. O1/D6 choose the specific pagination rule without changing design/pins; `invalid_tool_output` remains host-owned. D7 keeps the frozen full-request-window decoding semantics despite §5.6/§6.2 wording conflict. D8 keeps the 1024 UTF-8-byte path check despite schema scalar-count semantics. These are recorded internal specification conflicts, not claims of sentence-by-sentence conformity.

The first temporary audit-runner attempt assumed double quotes around `DESIGN_SHA256`; the actual file uses single quotes. It failed in the runner before its supplemental SHA assertion, not on a repository difference. That attempt is retained in `scope-precheck-runner-error/`. The runner now reads the constant through Python AST; the complete seven-check precheck was rerun successfully. No plugin/test/frozen file was changed to make the audit pass, and no product-defect STOP condition fired.

## Limits

- **M3 remains pending:** no proof of search's 12-second scan/cutoff timing, cross-platform timing or Linux real non-UTF-8 filenames; `tool.search_budget_timing_m3_pending` remains `m3_pending`, `linux_real=not_run`.
- **Digest is evidence, not promotion:** `manifest.artifact_digest_pending` and `manifest.five_field_key` retain exact status/expected bytes. The former stays `m3_pending`; all vectors and design/pins are unchanged.
- **Trusted workspace:** dev/ino/size/mtime_ns/ctime_ns comparison is best-effort mutation detection, not an atomic snapshot or protection from an adversary able to restore every signature field.
- **Timing boundary:** 113 ms and the earlier 92–93 ms are observations; R27's bounded skeleton work and the actual 5000 ms host deadline are the guards. Memory is process-local `tracemalloc`, not whole-system RSS.
- **Injected unreachable budgets:** empty-page `output_too_large` is exercised with narrowed caps; built-in caps do not reach it. Normal host validation rejects invalid offset/limit before plugin spawn.
- **No scope expansion:** no new SQL or load-order entry, host/kernel/replay, Node list/search, M5 design-document work or real provider execution. The inherited multilingual smoke uses local scripted transport. M4's existing claims are unchanged.

## Publication

The publication unit is the nine candidate paths listed above, including the completed plan and critique. After all documentation is written and reviewed, rerun all seven audits in full, then stage each explicit path, review status and the staged diff, and scan staged bytes plus evidence for credentials. Credential scans report redacted locations only and stop on any hit; environment-variable names in commands are not credentials. Preserve the final nine-file source manifest, porcelain status and audit/log digests externally.

Use normal hooks, the single commit message `v24: close out Python read plugin ABI`, and non-force `git push origin main`. No `git add -A`, `git add .`, `--no-verify`, or force push is permitted. Unrelated pre-existing files remain outside the commit. The actual commit SHA and push outcome are recorded in the external publication receipt and reported after execution; this record does not embed its own commit hash.
