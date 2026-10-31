# v24 Tool/Plugin ABI M5 closeout execution record

Date: 2026-11-01 (+08:00). Scope: the M5 closeout in design §10 and C.18.1, executed against the [closeout plan](../plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md), work items M5-0…M5-6. This record reports only this run's measurements. It does not embed its own SHA or the future commit SHA.

## Result

The required 32 commands ran serially in the plan's order and all exited 0. The first command started at 2026-10-31T16:45:18Z and the last at 2026-10-31T16:47:28Z; these are command start times, not an end-to-end duration. Commands 1–31 ended in their exact command-specific `[passed]` lines. Command 32 was the pinned SQL diff: exit 0, a zero-byte log, an empty last-line field, and no `[passed]`. No exit 2, `[SKIP]` or missing required marker occurred.

```text
[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3
```

**M5 is complete under design §10 and C.18.1**: §7.5 items 1–3 are executed, items 4–5 were already delivered by the W1–W6 increments, all 34 frozen `status` positions are adjudicated in the matrix, the 32-command sweep passed 32/32, seven scope audits passed, `git diff --exit-code -- v24/sql` is empty, and closeout remains **11/11**. s13 is extension evidence, not a twelfth closeout item. The M5-0 vectors baseline is the actual M3 commit `e58204c29afacd27b72e35e9e7eaeb6e32c11dac`, not `2307077`.

## Candidate and provenance

- Checkout `/Users/wxl/Projects/pg-agent`; branch `main`; upstream `origin/main`; HEAD at sweep start `e58204c29afacd27b72e35e9e7eaeb6e32c11dac` (`v24: declare Tool/Plugin ABI M3 complete`), with `origin/main` at the same commit.
- Environment: uv `0.8.24 (252f88733 2025-10-07)`, Python `3.14.6`, Node `v24.13.1` at `/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`, PostgreSQL `17.11 (Homebrew)`, Darwin `25.6.0` / macOS `26.6.2` / arm64; real local plugin subprocesses and the local database.
- Exactly seven candidate paths: `docs/designs/v24-pg-agent-2026-10-22.md`, `docs/investigations/v24-drift-factcheck-2026-10-29.md`, `docs/reviews/v24-conformance-matrix-2026-10-23.md`, `docs/reviews/v24-deviation-ledger-2026-10-23.md`, this execution record, `v24/s13/README.md`, and `docs/plans/v24-tool-plugin-abi-m3-m5-closeout-2026-10-31.md`.
- Evidence directory `/tmp/v24-abi-m5-20261031T164407Z/`. It contains provenance, the initial porcelain and untracked path+sha256 snapshot, the original main-design and drift files, `01.log`–`32.log`, `results.tsv`, `merged.log`, `scope-precheck/` and the final audit directory. The publication receipt records the actual commit SHA and push outcome externally.
- M5-0 read-only reviewed the W1, W2, W3, W4, W4b and W4c execution records, the W4/W5 plans, and the W5/W6 critiques. The 34-row bindings below cite those evidence layers plus this round's sweep; no prior gate was re-run as a substitute for the current sweep.

The current implementation and artifact digests are:

| Source / artifact | SHA-256 |
|---|---|
| `v24/s13/plugins/fs_read.py` (source, installed copy and approved entry; row 29) | `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c` |
| `v24/s13/plugins/fs_tools.js` (source; S24 asserts source/copy/entry equality) | `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5` |
| `v24/s13/fixtures.py` | `f2b5b84d9539ad9580645cabb15bf92dd169bb6a75b00c2eb1f25f069ac99bf5` |
| `v24/s13/test_tools.py` | `4df195f18d9583d920e64b1e5a5715d3626b97abdc00ffb0313651879d992d92` |
| Main design after M5 | `1f92104ef151932ff8a9efa80a999919583935017153ffe1733d016307f85e75` |
| Drift-factcheck after M5 | `ca2c19532975ca3f3f5334a08276af8c74c22afb0e7d7ee02c01f4f9d898ba40` |

Stable evidence digests:

| Evidence file | SHA-256 |
|---|---|
| `results.tsv` | `80c954298b4c10f105665c35ae0732cf76525745776b571668b31ed73ac37e10` |
| `merged.log` | `1a57c5f6219530efb3ade429a49fd3f60a1940a94a6c597c0027749b1cc1ec7d` |
| `29.log` | `e1b9bed4b1ff1cda89def086d12622beef24dbb74977a02b0d3e88f9395131a1` |
| `provenance.txt` | `9f617d081f8407bc59a7d2fab51b498a9e6c9d06426a2186e6e7e926287f2003` |
| `baseline-untracked.txt` | `da8f76e74ec4abddaeb12464e1133f919e4728266601d360b1fb48128696b114` |
| `scope-precheck/scope-audit.tsv` | `a2db609b051474b5b52635e66af65d775bec9a50eb4f6e510cdeee5f4637c062` |
| `main-design-original.md` | `5a79f71ff63b0cd63e070e9544746b56dc84a062db7af8bbd61688d079a0822f` |
| `drift-original.md` | `8a6d2f10906af130ad323ef3c3b336e6a28e473105ccbbf509100071b0cd4076` |

## §7.5 obligations

| # | Obligation | Result |
|---|---|---|
| 1 | Main design §5.1 parameter schema | Inline revision at line 275: DB shape-only, v1 host unchanged, v2 host closed subset before spawn, no defaults, no DB validator |
| 2 | Main design §5.4 result envelope | Inline revision at line 297: DB outer shape, v2 `{value,content,meta?}` / `{error,content,meta?}` / `{error}`, journal still transcript authority |
| 3 | Drift-factcheck D2/D3/D4 | Dated M5 notes in each 触碰面/gate and a status line; D2 cites the revised design; D3 keeps `replay_class` metadata and `no_replay`; D4 keeps journal transcript authority |
| 4 | Deviation ledger s13 entry | `D-ABI-M5-1…3` appended; no historical row rewritten |
| 5 | Conformance matrix s13 section | M5 section appended with the 34-row table; closeout count unchanged |

The main-design diff is exactly three hunks: line 275, line 297, and the EOF Appendix C.7 addition. Body lines 1–652 are byte-identical to `e58204c` except 275/297; no body line was inserted or removed, so the existing line-number anchors remain valid. The file grows from 786 to 795 lines.

## 34-position adjudication

The position set was script-derived before adjudication. Per-file pending counts are `tool_contracts=8`, `design_conformance=10`, `manifest_adapter_v2=5`, `results_v2=11`, total **34**. The 10 `design_conformance` positions are exactly `immutable_required_suites[*].status`; the two `design_resolved` values are `reviewed_design_decisions[*].status`, are not counted, and are not adjudicated here. Verdict counts are **E-SAT 28**, **E-SAT-T 3**, **E-SAT-PH 2**, **FROZEN-EXPECTED 1**.

The single adjudication table is the [M5 section of the conformance matrix](v24-conformance-matrix-2026-10-23.md), “## Post-closeout Tool/Plugin ABI M5 closeout (2026-11-01)”. Its final SHA-256 is `f7209fc292b36af2741bae05215416cf9e8777b67d0058cec1517a10621191a6`. This record deliberately does not duplicate the 34 rows, so there cannot be two divergent adjudications.

Zero-byte proof: `git diff --exit-code e58204c -- v24/s13/vectors` is empty; the mapping, `test_contracts.py` and the ABI design are byte-identical to `e58204c`; all 34 `status` bytes and both `"M3-pending"` placeholders are unchanged. `compatibility.production_behavior_claimed` and `gate_pass_claimed` remain `false`.

Current row-29 values used by the adjudication are `read_artifact_sha256=260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`, `read_1m_wall_ms=97`, `read_peak_kib=3959.904`, Node source/copy/entry equality for `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`, and S25 `real_clock_elapsed_ms=50.635` / overshoot `0.635`. W5/W6 values are historical cross-checks only; the read/Node artifact digests happen to be unchanged, but they are taken from this round's row 29 and S24 assertion.

## Scope and compatibility audits

All seven checks passed the precheck. The final run after all documentation is recorded below.

| # | Check | Base | Exit | Actual last line |
|---|---|---:|---:|---|
| 1 | Frozen modules/s13 tests and no new frozen-directory files | `c8c4bd0` / `e58204c` | 0 | `[scope] passed frozen_modules_and_untracked` |
| 2 | Whole vectors directory zero diff | `e58204c` | 0 | `[scope] passed vectors_zero_diff` |
| 3 | design_conformance/test_contracts/ABI design byte-identical; pins current | `e58204c` | 0 | `[scope] passed design_pins_zero_diff` |
| 4 | Registry exact D12 patch and whole-file equality | `c8c4bd0` | 0 | `[scope] passed registry_exact_patch` |
| 5 | Host import purity | `c8c4bd0` | 0 | `[scope] passed host_import_purity` |
| 6 | SQL zero diff | `c8c4bd0` / `e58204c` | 0 | `[scope] passed sql_zero_diff` |
| 7 | Tracked M5 delta union changed/new/removed untracked is a seven-path candidate subset | `e58204c` | 0 | `[scope] passed m5_candidate_only` |

Audit 1 runs the inherited `c8c4bd0` frozen checks and then freezes `v24/host`, `v24/sql` and `v24/s13` at `e58204c`, exempting only `v24/s13/README.md`. Audit 2 requires the entire vectors directory, including `design_conformance.json`, to be zero-diff from `e58204c`. Audit 3 uses the actual M3 commit and byte equality, not the `ab4636fc…` substitution used for M3; it does not use `2307077`. Audit 7 compares the `e58204c` tracked delta and the M5-0 untracked path+sha256 snapshot, then checks the main-design body and Appendix C.7 placement.

### Final audit (after documentation)

The full set ran again after README, matrix, ledger, M5 record and plan Result were written, starting at 2026-10-31T16:49:45Z. All seven exited 0 with these last lines:

| # | Check | Exit | Actual last line | Log SHA-256 |
|---|---|---:|---|---|
| 1 | `frozen_modules_and_untracked` | 0 | `[scope] passed frozen_modules_and_untracked` | `5deb4207f833f7b60517ff8b83e0977b8c660cdd7929fd6edfbe42e377abe3f7` |
| 2 | `vectors_zero_diff` | 0 | `[scope] passed vectors_zero_diff` | `6a50062806c768e03ff92c86454f1b7aa2cceb1f4f9754a0d757c322e7cc1d3a` |
| 3 | `design_pins_zero_diff` | 0 | `[scope] passed design_pins_zero_diff` | `eba014f8a1e7bd68691986b609bbdb419274ea88224f2cc1128c3251a9760508` |
| 4 | `registry_exact_patch` | 0 | `[scope] passed registry_exact_patch` | `ea1a744fa0f1430df824bcd3b98d7d48214af0b61e2e5d709a4b88f50e26e27c` |
| 5 | `host_import_purity` | 0 | `[scope] passed host_import_purity` | `f22b3a92ba8926508ee266282111acb354f4098f7f21f77a6310568b520f98b3` |
| 6 | `sql_zero_diff` | 0 | `[scope] passed sql_zero_diff` | `89f69d2e7dcd649ca47f5094ff8820ba349bf688ca43708db3fcf2248985950d` |
| 7 | `m5_candidate_only` | 0 | `[scope] passed m5_candidate_only` | `286a5e9b68b2bce1e6d68c7323003f57e590840733eba3952f1b928f06adefee` |

`scope-final/scope-audit.tsv` SHA-256 is `13c129759531a2f369d9558f9bc12ac7e567cc25fafabd7dc4dd9a7a6a441162`. Because this table is itself a documentation edit made after that run, a post-record confirmation run is executed before staging and recorded in the external receipt; the checks do not depend on documentation bytes.

## Final 32-command serial run

Every command below used the exact prefix `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`. Start times are UTC; last lines and log digests come directly from the producer logs.

| # | Started (UTC) | Command | Exit | Actual last line | Log SHA-256 |
|---|---|---|---:|---|---|
| 1 | 2026-10-31T16:45:18Z | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` | `2f5c2b386fc5d8db36379bf170a2e7cd5796ebc8609ccd36807f19c99b89603c` |
| 2 | 2026-10-31T16:45:48Z | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` | `92db10111b5048b6d990d2aebc418b66cb2403a4b185ce1a739436c7a32b301c` |
| 3 | 2026-10-31T16:45:53Z | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` | `4694dcdbde658f9119b0cbe19e3da9e03aa4df2b2e4d90f59cd349b1c03a5a46` |
| 4 | 2026-10-31T16:45:53Z | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` | `a31891a792511bb43805a5b1ab0c51a989f9afbfd89df7a087d4aaf95ba01315` |
| 5 | 2026-10-31T16:45:54Z | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3` | `304d5c2daf1f52489986051fd04e8e9213a2b078d8815fa21dc47d193160b6b7` |
| 6 | 2026-10-31T16:45:54Z | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` | `e2d510a75ab1f30c2a0e7733d76f8c54b1e9a17b7ffbf55a854e4e0e3a885f78` |
| 7 | 2026-10-31T16:45:55Z | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` | `297d0fec146eb2446d5caaa726dbef0b271a6fa773aa90559ee5128529e6ca92` |
| 8 | 2026-10-31T16:45:56Z | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` | `50bcdf95ca0dd7871ec43f64ca60c90a5ea5967dfd750757e7dcf938e4912d65` |
| 9 | 2026-10-31T16:45:56Z | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` | `17aec449960e18e6e7688de30016ddb80b4c2d8321cb317c842826f79ddea1e3` |
| 10 | 2026-10-31T16:45:57Z | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` | `1d64318ab0b3e46dcb8ead3a4ac5c8d3dcf2d82c8fa0495940f1f7a650bb697c` |
| 11 | 2026-10-31T16:45:59Z | `uv run python v24/s13/test_vectors.py --node` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked` | `cb163457b78d081f30a2d7faa499de1c168f507d0c91ca37a5c7978e0e5b2a99` |
| 12 | 2026-10-31T16:46:01Z | `uv run python v24/b0/test_golden.py` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=29; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 18, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python` | `7026055f9dd0a45e7989602bb425cfc1e3681037a8739d96ec7e03b0de86d861` |
| 13 | 2026-10-31T16:46:03Z | `uv run python v24/b0/test_golden.py --node` | 0 | `[passed] B0 v1 golden read-only check; byte_cases=34; structural_cases=6; total_vectors=40; files={'descriptor_v1.json': 5, 'frames_v1.json': 23, 'provider_requests_v1.json': 4, 'tool_messages_v1.json': 2}; descriptor=PostgreSQL+Python; plugins=Python+Node` | `02295e3d60d9997370b2221f8befc3d264f1560137711052dc70af8d18badec0` |
| 14 | 2026-10-31T16:46:05Z | `uv run python v24/load.py` | 0 | `[passed] v24 loader self-check` | `4a075e787802496c039f5f9e539dc2578d70494a4c998edbe8d53e1a749d42bc` |
| 15 | 2026-10-31T16:46:06Z | `uv run python v24/s1/setup_db.py --self-check` | 0 | `[passed] v24/s1 setup self-check` | `1a55eac4135cfd18cc2e9f1efbc555027f33b9b7356fa3c02ce3d8f718d59450` |
| 16 | 2026-10-31T16:46:07Z | `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` | `6409b34f98c67f2691761ccba02e1ca3ad5eb843013a6cbf488f65aed79ea182` |
| 17 | 2026-10-31T16:46:09Z | `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` | `649efe3953c2eb71add548f0e7cdcf208a44864642953cc3345b7c348e52da1c` |
| 18 | 2026-10-31T16:46:12Z | `uv run python v24/s2/test_g3a.py` | 0 | `[passed] v24 S2 W1-W6: resolve, infra, admission, activation, deactivation, dispose` | `da2ec29cda323fad9231a03b49803f47165262bd5cc9f08ba6d82c3f2c0da717` |
| 19 | 2026-10-31T16:46:14Z | `uv run python v24/s3/test_g2.py` | 0 | `[passed] v24 S3 W1-W7: read surface + start + poll/wait_check + cancel + steer + respond (G2a-0/1/2/3/4/5/6/7/8/10/11; G3b-1..5; claimed/unknown settlement release reserved S4)` | `40d74c2093b8d77de9dfee6221c7ab6de3cb93eb02fb80dbb5b261736bdc2feb` |
| 20 | 2026-10-31T16:46:23Z | `uv run python v24/s4/test_g2b.py` | 0 | `[passed] v24 S4 W1-W6` | `2627f4f8a77ac550e0f9ce3dc50fff9f24b559820465349cccc9b3c284df0d27` |
| 21 | 2026-10-31T16:46:27Z | `uv run python v24/s5/test_g4.py` | 0 | `[passed] v24 S5 W1-W4` | `176a92744273e6a90153f90275ca07d8955ae5f0a90213118bcca2baaee35979` |
| 22 | 2026-10-31T16:46:32Z | `uv run python v24/s6/test_g5.py` | 0 | `[passed] v24 S6 W1-W4` | `c53782805bf392054e9c51493b01014bf6400da6a3e0d0be7225a6bffee620af` |
| 23 | 2026-10-31T16:46:36Z | `uv run python v24/s8/test_g7.py` | 0 | `[passed] v24 S8 W1-W3 G7-A…H + N1-N7: g7_a,g7_b,g7_c,g7_d,g7_e,g7_f,g7_g,g7_h,n1,n2,n3,n4,n5,n6,n7` | `a2d70a4fa8aa39a301213a62d47b40fd62cc75480b5883d1c20bcbf6f4c12a29` |
| 24 | 2026-10-31T16:46:38Z | `uv run python v24/s7/test_g6.py` | 0 | `[passed] v24 S7 W1-W2 G6-A…H + N1-N9 + L1-L5: g6_a1,g6_b1,g6_b2,g6_b3,g6_c1,g6_c2,g6_c3,g6_d1,g6_e1,g6_f1,g6_g1,g6_g2,g6_g3,g6_h1,g6_h2,g6_h3,g6_n1,g6_n2,g6_n3,g6_n4,g6_n5,g6_n6,g6_n7,g6_n8,g6_n9,g6_l1,g6_l2,g6_l3,g6_l4,g6_l5` | `d2b1ba6ab36067fcd0fa50bdaa0cde9b95a73d12d9d04242b34483bd1619e7e9` |
| 25 | 2026-10-31T16:46:45Z | `uv run python v24/s10/test_g9.py` | 0 | `[passed] v24 G9 M-R: 11 case(s): G9-A, G9-B, G9-C, G9-D, G9-E, G9-F, G9-L, G9-J1, G9-J2, G9-J3, G9-R` | `20628c7002df4c8be143bee040306bc55abf6096b6135261ee64819c59b123d8` |
| 26 | 2026-10-31T16:46:49Z | `uv run python v24/s11/test_g10.py` | 0 | `[passed] v24 G10 M-P Python: 8 case(s): G10-A, G10-B, G10-C, G10-D, G10-E, G10-F, G10-G, G10-H` | `0934eb58f94a031c45851e3168b4eb7e6af83ac6887ed732c6be2f265f609b7c` |
| 27 | 2026-10-31T16:46:52Z | `uv run python v24/s11/test_node.py --node` | 0 | `[passed] v24 G10 M-P Node: node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `095f896bcfa9f06aba93f3a9fb1ed759ba2ad63d9ebdbb6d4397a75e88a633df` |
| 28 | 2026-10-31T16:46:54Z | `uv run python -m v24.host.plugin_smoke --multilingual-smoke` | 0 | `[passed] v24 multilingual smoke python=ok node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node final=ok` | `bef1ddadc6c14ab74fe9a42918246ff828af4823cc5b8f3eaffcef61bf8c0e45` |
| 29 | 2026-10-31T16:46:56Z | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` | `e1b9bed4b1ff1cda89def086d12622beef24dbb74977a02b0d3e88f9395131a1` |
| 30 | 2026-10-31T16:47:14Z | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=14; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true` | `e0e76e0b042bf67dbc7b3db3586940bf59f06eb98cd2b065ebbbbf99daf476a4` |
| 31 | 2026-10-31T16:47:26Z | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` | `76e5d6a711354fcb6b47c5ba94435e89a1f2371624f01115238755ab625f0080` |
| 32 | 2026-10-31T16:47:28Z | `git diff --exit-code c8c4bd0 -- v24/sql` | 0 | `<empty>` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Deviations

D-ABI-M5-1…3 in the [ledger](v24-deviation-ledger-2026-10-23.md) record the document alignment, the 34-position adjudication, and this round's gate/audit/limits. No runtime, host, SQL, loader, fixture, plugin, test, vector or ABI-design byte changed; the only code-adjacent file in the candidate set is `v24/s13/README.md`. No STOP condition fired.

## Limits

- **No hard real-time 12-second claim:** T1/T2/T3 remain separate; synchronous filesystem calls cannot be preempted, and a host deadline overrun would be an `unknown/timeout`, not the plugin's `search_scope_too_large`.
- **No Linux real or subdirectory non-UTF-8:** `linux_real=not_run`; the non-UTF-8 evidence is the macOS root-level preload shim.
- **No slow-scope convergence claim:** the §5.6 page-fill rule only proves the cutoff decision, not that an arbitrary slow scope converges within the budget.
- **Structural file-cap evidence:** S02 proves the `k<m` structure, not a real byte-full tree; defensive/narrowed-cap paths remain defensive.
- **No promotion or replay expansion:** all 34 frozen `status`/`expected` fields, both `"M3-pending"` placeholders, `compatibility.*_claimed=false` and `replay_class` semantics remain; M5 does not add tool replay rights or automatic re-execution.
- **Adjudication is documentation only:** the 34 verdicts do not change JSON, production behavior or gate semantics.

## Publication

The publication unit is the seven candidate paths listed above, including the completed plan. After all documentation is written and reviewed, rerun all seven audits in full, then stage each explicit path, review status and the staged diff, and scan staged bytes plus evidence for credentials. Credential scans report redacted locations only and stop on any hit; environment-variable names in commands are not credentials. Preserve the final seven-file source manifest, porcelain status and audit/log digests externally.

Use normal hooks, the single commit message `v24: close out Tool/Plugin ABI M5`, and non-force `git push origin main`. No `git add -A`, `git add .`, `--no-verify`, or force push is permitted. Unrelated pre-existing files remain outside the commit. The actual commit SHA and push outcome are recorded in the external publication receipt and reported after execution; this record does not embed its own commit hash.
